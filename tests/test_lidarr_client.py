"""Offline unit tests for Lidarr Requests."""
import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock

ROOT = pathlib.Path(__file__).resolve().parents[1]
src = ROOT / "ma_provider" / "lidarr_requests" / "lidarr_client.py"
spec = importlib.util.spec_from_file_location("lidarr_test_client", src)
lib = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lib
spec.loader.exec_module(lib)


class ClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = lib.Lidarr("http://example.invalid:8686", "test-placeholder", object())
        self.client.api = AsyncMock()

    def test_reject_credentials_in_url(self):
        for value in ("http://user:pw@example.com", "file:///tmp/test", "http://localhost/?key=x"):
            with self.subTest(value=value), self.assertRaises(lib.LidarrError):
                lib.clean_url(value)

    def test_download_progress(self):
        self.assertEqual(lib.percent({"size": 100, "sizeleft": 25}), 75)
        self.assertEqual(lib.percent({"size": 100, "sizeleft": -4}), 100)
        self.assertIsNone(lib.percent({"size": 0}), None)

    async def test_artist_discovery(self):
        self.client.api.return_value = [
            {"foreignArtistId": "artist-id", "artistName": "Test Artist", "id": 13, "monitored": True},
            {"artistName": "Bad artist"},
        ]
        results = await self.client.lookup("artist", "Test")
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].monitored)

    async def test_album_discovery_dedupes(self):
        self.client.api.return_value = [
            {"foreignAlbumId": "album-id", "title": "Example",
             "artist": {"artistName": "Example Artist"}},
            {"foreignAlbumId": "album-id", "title": "Example"},
        ]
        results = await self.client.lookup("album", "Example")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].artist, "Example Artist")

    async def test_idempotent_monitored_album(self):
        self.client.api.return_value = [
            {"foreignAlbumId": "album-id", "id": 8, "monitored": True}
        ]
        result = await self.client.request(lib.Match("album", "Example", "Artist", "album-id"))
        self.assertIn("already wanted", result)
        self.client.api.assert_awaited_once()

    async def test_add_unmonitored_album_to_wanted(self):
        self.client.api.return_value = [
            {"foreignAlbumId": "album-id", "id": 8, "monitored": False}
        ]
        await self.client.request(lib.Match("album", "Example", "Artist", "album-id"))
        self.assertEqual(self.client.api.call_args.args[:2], ("PUT", "album/8"))
        self.assertTrue(self.client.api.call_args.kwargs["data"]["monitored"])

    async def test_existing_artist_never_modified(self):
        result = await self.client.request(
            lib.Match("artist", "Already Present", "Already Present", "artist-id", present=True)
        )
        self.assertIn("already in Lidarr", result)
        self.client.api.assert_not_awaited()

    async def test_multi_root_requires_selection(self):
        self.client.api.return_value = [{"path": "/a"}, {"path": "/b"}]
        with self.assertRaises(lib.LidarrError):
            await self.client._defaults("")

    async def test_queue_progress(self):
        self.client.api.return_value = {
            "totalRecords": 12, "records": [{"title": "Example", "size": 100, "sizeleft": 30}]
        }
        count, rows = await self.client.queue()
        self.assertEqual(count, 12)
        self.assertEqual(lib.percent(rows[0]), 70)

    def test_public_source_without_tokens(self):
        for path in (ROOT / "ma_provider").rglob("*"):
            if path.suffix not in (".py", ".json"):
                continue
            data = path.read_text()
            self.assertNotIn("eyJhbGciOi", data)
            self.assertNotIn("X-Vault-Token", data)


if __name__ == "__main__":
    unittest.main()
