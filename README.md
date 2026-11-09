# Music Assistant Lidarr Requests

A community Music Assistant 2.10+ plugin that adds Lidarr discovery, artist/album requests and download progress in native Music Assistant plugin settings.

## Features

- Search for artists and albums in the existing Lidarr catalogue.
- Discover recordings using MusicBrainz; resolve a song to a containing album.
- Add new artists or albums to Lidarr Wanted; never create duplicates.
- Enable monitoring on existing unmonitored albums.
- Read the Lidarr queue, download state and percent progress.
- Use an existing Lidarr root's default quality and metadata profiles.

## Important limitations

Lidarr monitors artists and albums, not individual songs. A requested song therefore adds the selected album, clearly labelled before the request. Discovery can return several releases of the same song.

Music Assistant does not offer a generic third-party API to inject context menu buttons beside every playable track. This integration lives within Settings -> Plugins -> Lidarr Requests rather than replacing Music Assistant's built-in Discover tab.

No API command starts a download client or bypasses existing Lidarr schedules. It only requests monitored items.

## Install (Docker, Music Assistant 2.10.9)

Bind-mount the provider directory read-only into the package path inside your existing Music Assistant container:

~~~yaml
services:
  music-assistant:
    volumes:
      - ./ma_provider/lidarr_requests:/app/venv/lib/python3.14/site-packages/music_assistant/providers/lidarr_requests:ro
~~~

Keep all existing data and music volumes. Confirm the Python version/path for your own Music Assistant image before installing. Restart Music Assistant and select Settings -> Plugins -> Add a Plugin -> Lidarr Requests.

Enter the Lidarr URL (reachable from the server, e.g. http://nas:8686) and API key through the Music Assistant setup form. Music Assistant encrypts the API key at rest; it never goes into this Git repository.

To use: open the plugin options, choose Song/Album/Artist and type a query, save the search field, select Search, review each result and tap Add to Wanted. Select Refresh download progress to show current Lidarr queue activity.

## Security

- No credentials, passwords or API tokens are committed here.
- The Lidarr API key is SECURE_STRING in the Music Assistant setup flow.
- Requests use the X-Api-Key HTTP header without following redirects.
- Provider actions are protected by Music Assistant's config-provider authentication and permissions.
- The plugin does not host a public HTTP route.
- No credentials are printed in error messages or logs.
- No modifications to the music library itself.
- The setup URL forbids embedded credentials and query parameters.

## Testing

~~~sh
python -m pip install aiohttp
python -m unittest discover -s tests -v
~~~

This is an independent open-source project, not an official Music Assistant plugin. Licensed MIT.
