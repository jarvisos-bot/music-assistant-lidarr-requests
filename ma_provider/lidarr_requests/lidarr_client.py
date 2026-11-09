"""Lidarr client and MusicBrainz discovery helpers. Never log credentials."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import aiohttp


class LidarrError(Exception):
    """Credential-safe, human-readable integration error."""


@dataclass
class Match:
    kind: str
    title: str
    artist: str
    mbid: str
    present: bool = False
    monitored: bool = False
    note: str = ""
    artist_mbid: str = ""


def clean_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise LidarrError("Expected a http(s) Lidarr URL")
    if parts.username or parts.password or parts.fragment or parts.query:
        raise LidarrError("The Lidarr URL must not contain credentials or query strings")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def percent(row: dict) -> int | None:
    try:
        total, left = float(row.get("size") or 0), float(row.get("sizeleft") or 0)
        return round(max(0, min(100, (total - left) * 100 / total))) if total > 0 else None
    except (ValueError, TypeError):
        return None


class Lidarr:
    """Small asynchronous client, only allowing known API endpoints."""

    def __init__(self, url: str, api_key: str, session: aiohttp.ClientSession):
        self.base = clean_url(url)
        self._key = api_key.strip()
        if not self._key:
            raise LidarrError("Lidarr API key is missing")
        self.session = session

    async def api(self, method: str, path: str, *, params: dict | None = None,
                  data: dict | None = None, timeout: int = 12) -> Any:
        if method not in {"GET", "PUT", "POST"} or ".." in path or path.startswith("/"):
            raise LidarrError("Unsupported API request")
        try:
            async with self.session.request(
                method, f"{self.base}/api/v1/{path}",
                params=params, json=data, headers={"X-Api-Key": self._key},
                timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise LidarrError("Lidarr rejected its API credential")
                if response.status >= 300:
                    raise LidarrError(f"Lidarr returned HTTP {response.status}")
                if response.status == 204:
                    return {}
                return await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise LidarrError("Lidarr request failed or timed out") from exc

    async def verify(self) -> str:
        info = await self.api("GET", "system/status")
        return str(info.get("version", "?"))

    async def roots(self) -> list[dict]:
        return await self.api("GET", "rootfolder")

    async def lookup(self, kind: str, term: str, limit: int = 8) -> list[Match]:
        term = term.strip()
        if not 2 <= len(term) <= 120:
            raise LidarrError("Enter 2 to 120 characters to search")
        if kind == "artist":
            items = await self.api("GET", "artist/lookup", params={"term": term})
            return [
                Match("artist", x.get("artistName") or "Unknown", x.get("artistName") or "",
                      x["foreignArtistId"], bool(x.get("id")), bool(x.get("monitored")))
                for x in items if x.get("foreignArtistId")
            ][:limit]
        if kind == "album":
            items = await self.api("GET", "album/lookup", params={"term": term})
            return self._album_matches(items, limit=limit)
        if kind == "song":
            return await self._recording_matches(term, limit)
        raise LidarrError("Search type must be artist, album or song")

    @staticmethod
    def _album_matches(items: list[dict], limit: int = 8, song: str = "") -> list[Match]:
        result: list[Match] = []
        seen: set[str] = set()
        for x in items:
            mbid = x.get("foreignAlbumId")
            if not mbid or mbid in seen:
                continue
            seen.add(mbid)
            artist = x.get("artist") or {}
            result.append(Match(
                "album", x.get("title") or "Unknown album",
                artist.get("artistName", "") if isinstance(artist, dict) else "",
                mbid, bool(x.get("id")), bool(x.get("monitored")),
                f'Song "{song}" -> whole album' if song else "",
                artist.get("foreignArtistId", "") if isinstance(artist, dict) else "",
            ))
            if len(result) >= limit:
                break
        return result

    async def _recording_matches(self, term: str, limit: int) -> list[Match]:
        """A song maps to a containing release: Lidarr cannot monitor one track."""
        try:
            async with self.session.get(
                "https://musicbrainz.org/ws/2/recording",
                params={"query": term, "fmt": "json", "limit": "15"},
                headers={"User-Agent": "MA-Lidarr-Requests/0.1 (public-source plugin)"},
                timeout=aiohttp.ClientTimeout(total=12),
            ) as response:
                if response.status != 200:
                    raise LidarrError(f"MusicBrainz returned HTTP {response.status}")
                records = (await response.json()).get("recordings", [])
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise LidarrError("Song discovery could not contact MusicBrainz") from exc
        results: list[Match] = []
        searched: set[str] = set()
        for record in records:
            name = next((x["artist"].get("name", "") for x in record.get("artist-credit", [])
                         if isinstance(x, dict) and x.get("artist")), "")
            for release in record.get("releases", [])[:8]:
                release_group = release.get("release-group") or {}
                if release.get("status") not in ("Official", None):
                    continue
                if release_group.get("primary-type") not in ("Album", "EP", "Single", None):
                    continue
                title = release.get("title", "")
                key = (name + "/" + title).casefold()
                if not title or key in searched:
                    continue
                searched.add(key)
                albums = await self.api("GET", "album/lookup",
                                        params={"term": f"{name} {title}"}, timeout=9)
                matches = [x for x in albums if x.get("title", "").casefold() == title.casefold()]
                results += self._album_matches(matches, limit, song=record.get("title", term))
                if len(results) >= limit:
                    return results[:limit]
        return results[:limit]

    async def _defaults(self, wanted_root: str) -> tuple[str, int, int]:
        roots = await self.roots()
        if wanted_root:
            roots = [r for r in roots if r.get("path") == wanted_root]
        if len(roots) != 1:
            raise LidarrError("Choose a Lidarr root folder in the plugin options")
        root = roots[0]
        if not root.get("accessible", True):
            raise LidarrError("Lidarr music root is inaccessible")
        quality = root.get("defaultQualityProfileId")
        metadata = root.get("defaultMetadataProfileId")
        if not quality:
            qs = await self.api("GET", "qualityprofile")
            quality = qs[0]["id"] if len(qs) == 1 else None
        if not metadata:
            ms = await self.api("GET", "metadataprofile")
            metadata = ms[0]["id"] if len(ms) == 1 else None
        if not quality or not metadata:
            raise LidarrError("Set default quality and metadata profiles on the Lidarr root")
        return root["path"], int(quality), int(metadata)

    async def _ensure_artist(self, artist_mbid: str, root: str, monitor: str = "none") -> int:
        found = await self.api("GET", "artist/lookup", params={"term": artist_mbid})
        artist = next((a for a in found if a.get("foreignArtistId") == artist_mbid), None)
        if not artist:
            raise LidarrError("Artist no longer found in Lidarr")
        if artist.get("id"):
            return int(artist["id"])
        folder, quality, metadata = await self._defaults(root)
        payload = {k: v for k, v in artist.items() if k != "id"}
        payload.update({
            "rootFolderPath": folder, "qualityProfileId": quality,
            "metadataProfileId": metadata, "monitored": True,
            "addOptions": {"monitor": monitor, "searchForMissingAlbums": False,
                           "searchForCutoffUnmetAlbums": False},
        })
        created = await self.api("POST", "artist", data=payload, timeout=25)
        if not created.get("id"):
            raise LidarrError("Lidarr did not confirm the artist was added")
        return int(created["id"])

    async def request(self, item: Match, *, root: str = "", artist_policy: str = "future") -> str:
        if not item.mbid:
            raise LidarrError("Cannot request an item without a MusicBrainz identifier")
        if item.kind == "artist":
            # Existing unmonitored artists must be requestable too.
            if item.present:
                candidates = await self.api(
                    "GET", "artist/lookup", params={"term": item.mbid}
                )
                current = next(
                    (a for a in candidates if a.get("foreignArtistId") == item.mbid),
                    None,
                )
                if not current or not current.get("id"):
                    raise LidarrError("Existing artist could not be reloaded")
                if current.get("monitored"):
                    return f"Artist already Wanted: {item.title}"
                data = dict(current)
                data["monitored"] = True
                # Keep existing album monitor selections unchanged. No search.
                await self.api("PUT", f"artist/{int(current['id'])}",
                               data=data, timeout=25)
                return f"Artist added to Wanted: {item.title}"
            # Adding future releases does not trigger historical bulk downloads.
            policy = "all" if artist_policy == "all" else "future"
            await self._ensure_artist(item.mbid, root, monitor=policy)
            return f"Artist added: {item.title} ({policy} albums, no automatic search)"
        if item.kind != "album":
            raise LidarrError("Unsupported request type")
        found = await self.api("GET", "album/lookup", params={"term": item.mbid})
        album = next((x for x in found if x.get("foreignAlbumId") == item.mbid), None)
        if not album:
            raise LidarrError("Album no longer found in Lidarr")
        if album.get("id"):
            if album.get("monitored"):
                return f"Album already wanted: {item.title}"
            payload = dict(album)
            payload["monitored"] = True
            await self.api("PUT", f"album/{int(album['id'])}", data=payload, timeout=25)
            return f"Album added to Wanted: {item.title}"
        artist = album.get("artist") or {}
        aid = artist.get("foreignArtistId")
        if not aid:
            raise LidarrError("Album does not include a MusicBrainz artist identifier")
        artist_id = await self._ensure_artist(aid, root)
        payload = {k: v for k, v in album.items() if k != "id"}
        payload["artistId"] = artist_id
        payload["monitored"] = True
        payload["addOptions"] = {"searchForNewAlbum": False}
        await self.api("POST", "album", data=payload, timeout=25)
        return f"Album added to Wanted: {item.title}"

    async def queue(self, count: int = 12) -> tuple[int, list[dict]]:
        data = await self.api("GET", "queue",
                              params={"page": 1, "pageSize": count}, timeout=10)
        return int(data.get("totalRecords") or 0), data.get("records", [])[:count]
