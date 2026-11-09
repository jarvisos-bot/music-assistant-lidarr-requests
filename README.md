# Music Assistant Lidarr Requests

A community Music Assistant 2.10+ integration with two components: native Lidarr Requests plugin settings for Wanted actions and download progress, plus a read-only Lidarr Discovery music source for artist/album results in Music Assistant global search.

## Features

- Search for artists and albums in the existing Lidarr catalogue, including from Music Assistant global search through the optional Lidarr Discovery source.
- Discover recordings using MusicBrainz; resolve a song to a containing album.
- Add new artists or albums to Lidarr Wanted; never create duplicates.
- Enable monitoring on existing unmonitored albums and artists.
- Display [Wanted] / [Not Wanted] against artists and albums in global search.
- From an item originating in Lidarr Discovery, use Music Assistant's native Add to Library action to request that artist/album in Lidarr Wanted; requests do not trigger download-client searches.
- Read the Lidarr queue, download state and percent progress.
- Use an existing Lidarr root's default quality and metadata profiles.

## Important limitations

Lidarr monitors artists and albums, not individual songs. A requested song therefore adds the selected album, clearly labelled before the request. Discovery can return several releases of the same song.

Music Assistant does not offer a generic third-party API to inject request buttons beside every playable track. The dedicated request buttons live under Settings -> Plugins -> Lidarr Requests; the native Add to Library action on a Lidarr Discovery search result also requests it in Lidarr Wanted. Music Assistant currently does not provide a third-party API for relabelling this context menu button to "Add to Wanted". The **Lidarr Discovery (request only)** companion source contributes non-playable artists and albums to global search. Search results are catalogue entries, not downloaded audio, and do not automatically populate your Library. The global search source cannot monitor individual tracks. Removing a Music Assistant library entry deliberately does not remove or delete anything from Lidarr.

No API command starts a download client or bypasses existing Lidarr schedules. It only requests monitored items.

## Install (Docker, Music Assistant 2.10.9)

Bind-mount the provider directory read-only into the package path inside your existing Music Assistant container:

~~~yaml
services:
  music-assistant:
    volumes:
      - ./ma_provider/lidarr_requests:/app/venv/lib/python3.14/site-packages/music_assistant/providers/lidarr_requests:ro
      - ./ma_provider/lidarr_catalog:/app/venv/lib/python3.14/site-packages/music_assistant/providers/lidarr_catalog:ro
~~~

Keep all existing data and music volumes. Confirm the Python version/path for your own Music Assistant image before installing. Restart Music Assistant and select Settings -> Plugins -> Add a Plugin -> Lidarr Requests.

Enter the Lidarr URL (reachable from the server, e.g. http://nas:8686) and API key through the Music Assistant setup form. Music Assistant encrypts the API key at rest; it never goes into this Git repository. Then add **Settings -> Music Sources -> Lidarr Discovery (request only)**. This companion source uses the existing Lidarr Requests plugin's in-memory client, so no second key is requested or stored.

To use: search for an artist or album globally, open the result originating from Lidarr Discovery, and choose Add to Library to request it in Lidarr Wanted. Results display [Wanted] or [Not Wanted]; refresh search if status is cached. Alternatively open plugin options to request a desired result. In plugin settings, choose Song/Album/Artist, enter a query, save the search field, select Search, review the result, and tap Add to Wanted. Select Refresh download progress to show current Lidarr queue activity.

## Security

- No credentials, passwords or API tokens are committed here. The global-search source does not read OpenBao or encrypted settings; it uses the linked plugin's client in memory.
- The Lidarr API key is SECURE_STRING in the Music Assistant setup flow.
- Requests use the X-Api-Key HTTP header without following redirects.
- Provider actions are protected by Music Assistant's config-provider authentication and permissions.
- The plugin does not host a public HTTP route.
- No credentials are printed in error messages or logs.
- No modifications to the music library itself.
- The setup URL forbids embedded credentials and query parameters.

## Testing

Run the offline test suite inside a Music Assistant 2.10.9-compatible runtime:

~~~sh
docker run --rm --network none --entrypoint /app/venv/bin/python   -v "$PWD:/workspace:ro"   -v "$PWD/ma_provider/lidarr_requests:/app/venv/lib/python3.14/site-packages/music_assistant/providers/lidarr_requests:ro"   -v "$PWD/ma_provider/lidarr_catalog:/app/venv/lib/python3.14/site-packages/music_assistant/providers/lidarr_catalog:ro"   ghcr.io/music-assistant/server:latest -m unittest discover -s /workspace/tests -v
~~~

This is an independent open-source project, not an official Music Assistant plugin. Licensed MIT.
