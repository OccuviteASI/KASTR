# KASTR

KASTR (Kenton's ASI Streaming Tool with Relay) is a desktop app for low-latency video rooms over
[Media over QUIC](https://quic.video): cameras, screens, RTSP feeds and media files are published to a
relay and watched by everyone in the room. It ships as one frozen binary per platform (Windows exe,
Linux binary, macOS app) that bundles a local web UI, a Chrome for Testing browser, ffmpeg and the
`moq-relay` / `moq` CLI. A box can be a viewer, a publisher, a relay, or all three, and relays federate
into a hub-and-spoke cluster.

What it does today (v0.21.40; RELEASES.md has what changed in each build):

- **Rooms.** The first join goes to `main`, later joins to the room you were in last. Rooms live on the hub and every
  relay lists them; a room can be locked with a code or kept open, and any other room closes about 10 minutes after the
  last person leaves. Chat with attachments, a Participants panel, pin and spotlight (several spotlights share the stage
  as a grid), Fill window and full screen, and stage recording.
- **Sources.** Camera and microphone with background effects (on the GPU, or the NPU where there is one) and RNNoise
  noise removal; screen, window and browser-tab sharing (native capture with the computer's sound on Windows, the
  browser's picker elsewhere); media files. The host publishes RTSP/HTTP cameras, a camera on this computer, a looping
  media file and RTMP pushes (a GoPro) natively with `ffmpeg | moq`, with per-feed audio and passthrough, and gathers any
  of them into grids. One switch turns a box's own cameras off and on without forgetting them.
- **Relays.** Any KASTR can host a relay, and relays federate into a hub-and-spoke fleet: the hub owns the rooms and the
  chat history, spokes check in about every 30 s, and hub duties can move to another relay. Relay operators set viewer,
  publisher and admin access codes on the Relay page (plus a federation code for spokes); an admin code set on the hub
  is honoured by every federated spoke. At launch a desktop KASTR connects to the nearest relay it knows (a private
  address first, then the fewest network hops) and finds relays on the local network over mDNS.
- **Machine modes.** Full, Viewer, Publisher, Relay and Publisher + relay (kastr.ini `mode`, or More ▸ KASTR mode and
  relay settings…).
- **Your own browser.** On a person's computer KASTR opens in their default browser when it is Chromium-based, with
  their own profile, so Share lists their real browser tabs (kastr.ini `browser = auto`, the default since 0.21.40).
  Boxes (relay, hub and spoke machines, Publisher and Viewer modes, machines with camera feeds or grids) and computers
  whose default browser is not Chromium-based use the bundled Chrome for Testing; `browser = bundled` forces it.
- **Browser clients.** A relay host serves KASTR to any browser: `https://<relay-host>:8443/` for the full client
  (install the host's certificate once from `/ca.crt`, or give the host a real certificate with `tls_cert` /
  `tls_key` / `tls_hostname` in kastr.ini) and `http://<relay-host>:8000/` for the lobby (rooms, People, chat, one
  stream played through the host). The web port also carries the video (`/relay`, WebSocket), so one Cloudflare Tunnel
  name is enough; see `docs/cloudflare-tunnel.md`. The Relay page's "Web clients" switch (`web_page = off` in
  kastr.ini) stops handing the page to other devices; relay modes start with it off. Browser clients follow the relay
  host's version.
- **Recording and hooks.** A relay host records the streams picked on its Relay page ("Record"; segments kept
  `archive_hours`, default 24, downloadable from the Relay page and the room's Files panel). kastr.ini also takes
  `hook_ready` / `hook_notready` / `hook_read` (commands run on camera up, down and a viewer's first HLS or fallback
  request, with `KASTR_EVENT`, `KASTR_BROADCAST`, `KASTR_FEED_ID`, `KASTR_RELAY`, `KASTR_REASON`, `KASTR_VIEWER` in the
  environment) and `hook_timeout` (seconds, default 30). On-demand cameras and low thumbnail copies are off by default
  since 0.21.10; `ondemand = on` on every box of the fleet brings both back.
- **Updates.** Fleet updates flow hub-first: update the hub relay box, its spokes follow the hub's version within the
  hour, and clients pick the new build up on their next launch; browser clients reload on their own. A box that serves
  its page to the network keeps both install zips (Windows and Linux) ready for download.

REQUIREMENTS.md lists what must hold and ARCHITECTURE.md explains why it is built this way.

## Layout

| Path | What |
|---|---|
| `kastr.py` | launcher: state dir, port, updater, relaunch protocol, `--diagnose` |
| `kastr_serve.py` | local HTTP API + static site (`/api/*`, media store, prefs) |
| `kastr_rtsp.py` | RTSP bridge: ffmpeg + moq publisher pairs, restart ladder, monitors |
| `kastr_relay.py` | hosted `moq-relay`: access codes, tokens, federation |
| `kastr_archive.py` | host recording: per-stream segment recorder, retention sweep |
| `kastr_chat.py`, `kastr_tls.py`, `kastr_browser.py` | room chat on the hub, phone HTTPS, bundled browser |
| `kastr_screen.py`, `kastr_screen_sources.py`, `kastr_tabs.py`, `kastr_overlay.py`, `kastr_loopback.py` | native screen, window and tab sharing on Windows: sources and thumbnails, browser tabs, the red border and Stop sharing bar, the computer's sound |
| `kastr_mdns.py` | relay discovery on the local network (mDNS, `_kastr._tcp`) |
| `kastr_release.py` | assembles the install zips a host offers for download |
| `moq-watch-lite.html` | the app page (watch module + publish module) |
| `relay.html`, `index.html`, `app.html` | the Relay page, the launch page, the app window's tab shell |
| `assets/` | vendored MoQ library, RNNoise worklet, MediaPipe, the NPU model (`assets/npu`), background images (`assets/bg`), brand |
| `extras/` | templates a release ships beside the binary (kastr.ini; on Linux also README.txt, install.sh, kastr.svg) |
| `tests/` | unit and page tests (`python -m unittest discover -s tests`; the build runs them first) |
| `tools/` | `kastr-field-check.ps1` / `.sh`: a read-only field report for any box |
| `docs/` | `rtsp-drops.md` (field diagnostics), `cloudflare-tunnel.md` (one name, one port), `moq-landscape.md` (MoQ research and backlog) |
| `RELEASES.md` / `REQUIREMENTS.md` / `ARCHITECTURE.md` | what shipped, what must hold, why it is built this way |

## Build

```bash
python fetch-helpers.py        # downloads ffmpeg, moq-relay and moq into bin/ (not in git)
python build.py --publish      # Windows; Linux: run the same under WSL with the kastr venv
./build-mac.sh                 # macOS, see MACOS.md
```

`dist/` (builds, archives, update feeds) and `bin/` are build outputs and stay out of the repository.
Docker: see `DOCKER.md`.

## Run from source

The large model and wasm files (NPU person cutout, MediaPipe) are not in git; `build.py` fetches them by sha256.
Before running from source on a fresh clone, fetch them once:

```bash
python vendor-npu.py
python vendor-mediapipe.py
python kastr-serve.py 8971     # dev harness serving the page on http://localhost:8971
python kastr.py                # the full launcher (opens the app window; see `browser =` in kastr.ini)
```
