"""Secure interactive Music Assistant setup for Lidarr."""
from __future__ import annotations
from typing import TYPE_CHECKING
import aiohttp
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType
from music_assistant.models.setup_flow import SetupFlowError
from .lidarr_client import Lidarr, LidarrError

if TYPE_CHECKING:
    from music_assistant.models.setup_flow import SetupSession

FIELDS = (
    ConfigEntry(key="url", type=ConfigEntryType.STRING, required=True,
                default_value="http://localhost:8686",
                description="Lidarr address reachable by the MA server"),
    ConfigEntry(key="api_key", type=ConfigEntryType.SECURE_STRING, required=True,
                description="Encrypted inside Music Assistant, never public"),
)


async def run_setup(session: SetupSession) -> None:
    """Validate Lidarr credentials before saving them encrypted."""
    errors: dict[str, str] | None = None
    while True:
        values = await session.form(FIELDS, step_id="user", errors=errors, last_step=True)
        try:
            async with aiohttp.ClientSession() as http:
                await Lidarr(str(values["url"]), str(values["api_key"]), http).verify()
            await session.finish(values)
            return
        except (LidarrError, SetupFlowError) as exc:
            errors = {"base": getattr(exc, "translation_key", None) or str(exc)}
