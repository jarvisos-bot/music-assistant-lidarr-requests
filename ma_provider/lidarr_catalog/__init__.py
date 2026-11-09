"""Global read-only Lidarr catalogue search for Music Assistant.

The authenticated Lidarr Requests plugin owns the API connection. This music
source borrows its in-memory client; it never reads or stores API credentials.

Search items are catalogue references, not playable songs or library imports.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from music_assistant_models.config_entries import ConfigEntry, ProviderConfig
from music_assistant_models.enums import MediaType, ProviderFeature
from music_assistant_models.errors import MediaNotFoundError, ProviderUnavailableError
from music_assistant_models.media_items import (
    Album, Artist, ItemMapping, MediaItemMetadata, ProviderMapping, SearchResults,
    UniqueList,
)
from music_assistant.models.music_provider import MusicProvider
from music_assistant.providers.lidarr_requests.lidarr_client import LidarrError, Match

if TYPE_CHECKING:
    from music_assistant import MusicAssistant
    from music_assistant_models.provider import ProviderManifest
    from music_assistant.models import ProviderInstanceType

FEATURES = {ProviderFeature.SEARCH}
HELP_TEXT = (
    "Lidarr catalogue only. Not available for playback until the album has "
    "been downloaded and indexed. To request it, open Settings > Plugins > "
    "Lidarr Requests and search for this artist or album."
)


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    return LidarrCatalogue(mass, manifest, config, FEATURES)


class LidarrCatalogue(MusicProvider):
    """Provider that contributes request-only artist and album search results."""

    @property
    def supported_media_types(self) -> set[MediaType]:
        return {MediaType.ARTIST, MediaType.ALBUM}

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        return ()

    def _lidarr(self):
        """Resolve linked plugin lazily: provider loading order is not fixed."""
        plugin = self.mass.get_provider("lidarr_requests")
        client = getattr(plugin, "_client", None)
        if client is None:
            raise ProviderUnavailableError(
                "Lidarr Requests plugin is disconnected. Configure it under Settings > Plugins."
            )
        return client

    def _mapping(self, mbid: str) -> set[ProviderMapping]:
        return {
            ProviderMapping(
                item_id=mbid,
                provider_domain=self.domain,
                provider_instance=self.instance_id,
                available=False,
                in_library=False,
            )
        }

    def _artist(self, item: Match) -> Artist:
        artist = Artist(
            item_id=item.mbid,
            provider=self.instance_id,
            name=item.title,
            provider_mappings=self._mapping(item.mbid),
            is_playable=False,
            metadata=MediaItemMetadata(description=HELP_TEXT),
        )
        return artist

    def _album(self, item: Match) -> Album:
        parent = item.artist_mbid or item.artist or "Unknown artist"
        artist = ItemMapping(
            item_id=parent,
            provider=self.instance_id,
            name=item.artist or "Unknown artist",
            media_type=MediaType.ARTIST,
            is_playable=False,
            available=False,
        )
        return Album(
            item_id=item.mbid,
            provider=self.instance_id,
            name=item.title,
            provider_mappings=self._mapping(item.mbid),
            artists=UniqueList([artist]),
            is_playable=False,
            metadata=MediaItemMetadata(description=HELP_TEXT),
        )

    async def search(
        self, search_query: str, media_types: list[MediaType], limit: int = 5
    ) -> SearchResults:
        """Add artist and album suggestions to the global MA search.

        Tracks are not supplied: Lidarr only requests albums, not specific
        recordings. This does NOT add unavailable results to the music library.
        """
        result = SearchResults()
        query = search_query.strip()
        if not query or len(query) > 120:
            return result
        client = self._lidarr()
        limit = min(25, max(1, int(limit)))
        jobs: list[tuple[str, object]] = []
        if MediaType.ARTIST in media_types:
            jobs.append(("artist", client.lookup("artist", query, limit)))
        if MediaType.ALBUM in media_types:
            jobs.append(("album", client.lookup("album", query, limit)))
        if not jobs:
            return result
        responses = await asyncio.gather(*(job for _, job in jobs), return_exceptions=True)
        for (kind, _), items in zip(jobs, responses, strict=True):
            if isinstance(items, BaseException):
                # Keep credentials and potentially sensitive response bodies out of logs.
                self.logger.warning("Lidarr %s catalogue search failed: %s", kind,
                                    type(items).__name__)
                continue
            if kind == "artist":
                result.artists = [self._artist(m) for m in items if m.mbid][:limit]
            else:
                result.albums = [self._album(m) for m in items if m.mbid][:limit]
        return result

    async def get_artist(self, prov_artist_id: str) -> Artist:
        """Look up a catalogue item if opened in the Music Assistant UI."""
        matches = await self._lidarr().lookup("artist", prov_artist_id, 20)
        for item in matches:
            if item.mbid == prov_artist_id:
                return self._artist(item)
        raise MediaNotFoundError("Artist not found in Lidarr catalogue")

    async def get_album(self, prov_album_id: str) -> Album:
        """Look up a catalogue album without assuming it is playable."""
        matches = await self._lidarr().lookup("album", prov_album_id, 20)
        for item in matches:
            if item.mbid == prov_album_id:
                return self._album(item)
        raise MediaNotFoundError("Album not found in Lidarr catalogue")
