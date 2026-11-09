"""Lidarr Requests - Music Assistant native plugin options."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
import aiohttp
from music_assistant_models.config_entries import (
    ConfigEntry, ConfigValueOption, ProviderConfig,
)
from music_assistant_models.enums import ConfigEntryType, ProviderFeature
from music_assistant_models.errors import ActionUnavailable
from music_assistant.models.plugin import PluginProvider
from .lidarr_client import Lidarr, LidarrError, Match, percent

if TYPE_CHECKING:
    from music_assistant import MusicAssistant
    from music_assistant_models.provider import ProviderManifest
    from music_assistant.models import ProviderInstanceType

SUPPORTED_FEATURES: set[ProviderFeature] = set()


async def setup(mass: MusicAssistant, manifest: ProviderManifest,
                config: ProviderConfig) -> ProviderInstanceType:
    """Create a Lidarr plugin instance."""
    return LidarrRequests(mass, manifest, config, SUPPORTED_FEATURES)


class LidarrRequests(PluginProvider):
    """Manage Lidarr Wanted using authenticated native MA plugin settings."""

    def __init__(self, mass, manifest, config, supported_features):
        super().__init__(mass, manifest, config, supported_features)
        self._client: Lidarr | None = None
        self._session: aiohttp.ClientSession | None = None
        self._roots: list[dict] = []
        self._results: list[Match] = []
        self._queue: tuple[int, list[dict]] | None = None
        self._message = ""
        self._action_lock = asyncio.Lock()

    async def handle_async_init(self) -> None:
        """Connect after the plugin has loaded its encrypted setup data."""
        self._session = aiohttp.ClientSession()
        self._client = Lidarr(
            str(self.get_setup_value("url")),
            str(self.get_setup_value("api_key")),
            self._session,
        )
        try:
            await self._client.verify()
            self._roots = await self._client.roots()
        except Exception:
            await self._session.close()
            self._session = None
            raise

    async def unload(self, is_removed: bool = False) -> None:
        """Release HTTP resources."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._client = None

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """Render discovery, request controls and download queue."""
        entries = [
            ConfigEntry(
                key="search_kind", type=ConfigEntryType.STRING,
                default_value="album", immediate_apply=True, category="discovery",
                options=[ConfigValueOption(k, title=k.title())
                         for k in ("song", "album", "artist")],
            ),
            ConfigEntry(
                key="search_query", type=ConfigEntryType.STRING,
                default_value="", required=False, immediate_apply=True,
                category="discovery", description="Save a search term and tap Search.",
            ),
            ConfigEntry(
                key="search", type=ConfigEntryType.ACTION, required=False,
                action="search", action_label="Search Lidarr catalogue",
                category="discovery",
            ),
            ConfigEntry(
                key="root_folder", type=ConfigEntryType.STRING, required=False,
                default_value="", category="request_settings",
                description="Auto-select if exactly one Lidarr root exists.",
                options=[
                    ConfigValueOption("", title="Automatic (single root)"),
                    *[ConfigValueOption(str(r["path"]),
                                        title=str(r.get("name") or r["path"]))
                      for r in self._roots if r.get("path")],
                ],
            ),
            ConfigEntry(
                key="artist_policy", type=ConfigEntryType.STRING,
                default_value="future", category="request_settings",
                description="All albums may add a very large back catalogue to Wanted.",
                options=[ConfigValueOption("future", title="Future albums only"),
                         ConfigValueOption("all", title="All albums")],
            ),
            ConfigEntry(
                key="refresh", type=ConfigEntryType.ACTION, required=False,
                action="refresh", action_label="Refresh download progress",
                category="status",
            ),
        ]
        if self._message:
            entries.append(ConfigEntry(
                key="last_result", type=ConfigEntryType.LABEL, required=False,
                label=self._message, category="status",
            ))
        if self._results:
            entries.append(ConfigEntry(
                key="results_heading", type=ConfigEntryType.LABEL, required=False,
                label=f"{len(self._results)} results; choose what to request.",
                category="results",
            ))
        for i, item in enumerate(self._results):
            status = ("Already monitored" if item.monitored else
                      "Already in Lidarr" if item.present else "Not in Lidarr")
            entries.append(ConfigEntry(
                key=f"result_label_{i}", type=ConfigEntryType.LABEL,
                label=f"{item.title} - {item.artist} ({status})",
                description=item.note or f"MusicBrainz: {item.mbid}",
                category="results",
            ))
            if not item.monitored:
                entries.append(ConfigEntry(
                    key=f"request_{i}", type=ConfigEntryType.ACTION,
                    action=f"request:{i}",
                    action_label=f"Add to Wanted: {item.title[:52]}",
                    category="results",
                ))
        if self._queue is not None:
            total, rows = self._queue
            entries.append(ConfigEntry(
                key="queue_count", type=ConfigEntryType.LABEL,
                label=f"Download queue: {total} items", category="status",
            ))
            for i, row in enumerate(rows):
                p = percent(row)
                progress = f"{p}%" if p is not None else "unknown progress"
                entries.append(ConfigEntry(
                    key=f"queue_{i}", type=ConfigEntryType.LABEL,
                    label=f"{row.get('title', 'Download')}: {row.get('status', 'unknown')} - {progress}",
                    description=str(row.get("trackedDownloadState") or ""),
                    category="status",
                ))
        return tuple(entries)

    async def handle_config_action(self, action: str):
        """Handle one authenticated request from the Music Assistant UI."""
        if not self._client:
            raise ActionUnavailable("Lidarr is disconnected")
        async with self._action_lock:
            try:
                if action == "search":
                    kind = str(self.get_config_value("search_kind", "album"))
                    term = str(self.get_config_value("search_query", ""))
                    self._results = await self._client.lookup(kind, term)
                    self._message = f"{len(self._results)} results for '{term}'"
                    return await self.get_config_entries()
                if action == "refresh":
                    self._queue = await self._client.queue()
                    self._message = "Lidarr download queue refreshed"
                    return await self.get_config_entries()
                if action.startswith("request:"):
                    try:
                        item = self._results[int(action.partition(":")[2])]
                    except (IndexError, ValueError) as exc:
                        raise ActionUnavailable("Search again before requesting") from exc
                    self._message = await self._client.request(
                        item,
                        root=str(self.get_config_value("root_folder", "")),
                        artist_policy=str(self.get_config_value("artist_policy", "future")),
                    )
                    self._results = []
                    return await self.get_config_entries()
            except LidarrError as exc:
                self._message = str(exc)
                raise ActionUnavailable(self._message) from exc
        return await super().handle_config_action(action)
