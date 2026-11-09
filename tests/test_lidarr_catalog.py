"""Test the read-only global-search Music Assistant companion provider.

Requires Music Assistant 2.10+ runtime (provided by the Docker image).
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from music_assistant_models.enums import MediaType, ProviderFeature
from music_assistant.providers.lidarr_catalog import LidarrCatalogue
from music_assistant.providers.lidarr_requests.lidarr_client import Match


class FakeLidarr:
    def __init__(self):
        self.calls: list[tuple] = []
        self.requests: list[tuple] = []

    async def request(self, item, *, root="", artist_policy="future"):
        self.requests.append((item, root, artist_policy))
        return f"Requested {item.title} in Lidarr Wanted"

    async def lookup(self, kind: str, search: str, limit: int = 5):
        self.calls.append((kind, search, limit))
        if kind == "artist":
            return [
                Match("artist", "James Blunt", "James Blunt",
                      "54bf2b5e-1a90-4aaa-a4be-e45ca7c2bb53")
            ]
        return [
            Match("album", "Back to Bedlam", "James Blunt",
                  "56e495da-8c17-4d40-8ee6-a2eef5d44e21",
                  artist_mbid="54bf2b5e-1a90-4aaa-a4be-e45ca7c2bb53")
        ]


class CatalogueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = FakeLidarr()
        self.plugin = SimpleNamespace(_client=self.client)
        self.catalog = object.__new__(LidarrCatalogue)
        self.catalog.mass = SimpleNamespace(get_provider=lambda name: self.plugin)
        self.catalog.config = SimpleNamespace(instance_id="lidarr_catalog")
        self.catalog.manifest = SimpleNamespace(domain="lidarr_catalog")
        self.catalog.logger = SimpleNamespace(warning=lambda *args: None, info=lambda *args: None)

    def test_search_feature_declared(self):
        self.assertIn(ProviderFeature.SEARCH,
                      __import__("music_assistant.providers.lidarr_catalog",
                                 fromlist=["FEATURES"]).FEATURES)
        self.assertEqual(self.catalog.supported_media_types,
                         {MediaType.ARTIST, MediaType.ALBUM})

    async def test_global_search_returns_unplayable_catalogue_items(self):
        results = await self.catalog.search(
            "james blunt", [MediaType.ARTIST, MediaType.ALBUM], 8
        )
        self.assertEqual(results.artists[0].name, "James Blunt [Not Wanted]")
        self.assertEqual(results.albums[0].name, "Back to Bedlam [Not Wanted]")
        self.assertEqual(results.albums[0].artists[0].name, "James Blunt")
        for item in (results.artists[0], results.albums[0]):
            self.assertFalse(item.is_playable)
            self.assertFalse(item.available)
            self.assertFalse(next(iter(item.provider_mappings)).in_library)
            self.assertIn("not available for playback", item.metadata.description.lower())
            self.assertTrue(item.to_dict())
        self.assertEqual(len(self.client.calls), 2)

    async def test_tracks_not_exposed_as_playable(self):
        found = await self.catalog.search("james blunt", [MediaType.TRACK])
        self.assertEqual(found.tracks, [])
        self.assertEqual(self.client.calls, [])

    async def test_artist_open(self):
        found = await self.catalog.get_artist(
            "54bf2b5e-1a90-4aaa-a4be-e45ca7c2bb53"
        )
        self.assertEqual(found.name, "James Blunt [Not Wanted]")

    async def test_album_open(self):
        found = await self.catalog.get_album(
            "56e495da-8c17-4d40-8ee6-a2eef5d44e21"
        )
        self.assertEqual(found.name, "Back to Bedlam [Not Wanted]")

    def test_wanted_status_visible_for_monitored_artist_and_album(self):
        artist = Match("artist", "James Blunt", "James Blunt", "m1",
                       present=True, monitored=True)
        album = Match("album", "25", "Adele", "m2",
                      present=True, monitored=True)
        self.assertEqual(self.catalog._artist(artist).name, "James Blunt [Wanted]")
        self.assertEqual(self.catalog._album(album).name, "25 [Wanted]")
        self.assertIn("WANTED", self.catalog._artist(artist).metadata.description)

    async def test_native_add_to_library_requests_lidarr_artist(self):
        item = (await self.catalog.search("james blunt", [MediaType.ARTIST])).artists[0]
        self.assertTrue(await self.catalog.library_add(item))
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(self.client.requests[0][0].kind, "artist")
        self.assertEqual(self.client.requests[0][2], "future")

    async def test_native_add_to_library_requests_lidarr_album(self):
        item = (await self.catalog.search("james blunt", [MediaType.ALBUM])).albums[0]
        self.assertTrue(await self.catalog.library_add(item))
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(self.client.requests[0][0].kind, "album")

    async def test_no_client_graceful_error(self):
        self.catalog.mass = SimpleNamespace(get_provider=lambda name: None)
        with self.assertRaisesRegex(Exception, "Lidarr Requests"):
            await self.catalog.search("james blunt", [MediaType.ARTIST])


if __name__ == "__main__":
    unittest.main()
