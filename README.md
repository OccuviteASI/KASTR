# KASTR

KASTR (Kenton's ASI Streaming Tool with Relay) is a desktop app for low-latency video rooms over
[Media over QUIC](https://quic.video): cameras, screens, RTSP feeds and media files are published to a
relay and watched by everyone in the room. It ships as one frozen binary per platform (Windows exe,
Linux binary, macOS app) that bundles a local web UI, a Chrome for Testing browser, ffmpeg and the
`moq-relay` / `moq` CLI. A box can be a viewer, a publisher, a relay, or all three, and relays federate
into a hub-and-spoke cluster.

Since 0.17.0 a relay host also serves KASTR to any browser: open `https://<relay-host>:8443/` (install the host's
certificate once from `/ca.crt`, or give the host a real certificate with `tls_cert` / `tls_key` / `tls_hostname` in
kastr.ini) for the full client, or `http://<relay-host>:8000/` for the lobby (rooms, People, chat, one stream played
through the host). Turn it on from the Relay page's "Web clients" switch. Browser clients follow the relay host's version.

Since 0.18.0 an RTSP camera can sleep until a viewer asks for it (the row's "On demand" switch), publish a small copy
for thumbnails ("Low for thumbnails"), and be recorded on the relay host (Relay page "Record"; segments kept
`archive_hours`, default 24, downloadable from the Relay page and the room's Files panel). kastr.ini also takes
`hook_ready` / `hook_notready` / `hook_read` (commands run on camera up, down and viewer demand, with `KASTR_EVENT`,
`KASTR_BROADCAST`, `KASTR_FEED_ID`, `KASTR_RELAY`, `KASTR_REASON`, `KASTR_VIEWER` in the environment) and
`hook_timeout` (seconds, default 30).

Fleet updates flow hub-first: update the hub relay box, its spokes follow the hub's version within the hour, and
clients pick the new build up on their next launch; browser clients reload on their own. Relay operators set viewer, publisher and (since 0.16.0) admin
access codes on the Relay page; an admin code set on the hub is honoured by every federated spoke.

## Layout

| Path | What |
|---|---|
| `kastr.py` | launcher: state dir, port, updater, relaunch protocol, `--diagnose` |
| `kastr_serve.py` | local HTTP API + static site (`/api/*`, media store, prefs) |
| `kastr_rtsp.py` | RTSP bridge: ffmpeg + moq publisher pairs, restart ladder, monitors |
| `kastr_relay.py` | hosted `moq-relay`: access codes, tokens, federation |
| `kastr_archive.py` | host recording: per-stream segment recorder, retention sweep |
| `kastr_chat.py`, `kastr_tls.py`, `kastr_browser.py` | room chat on the hub, phone HTTPS, bundled browser |
| `moq-watch-lite.html` | the app page (watch module + publish module) |
| `assets/` | vendored MoQ library, RNNoise worklet, MediaPipe, brand |
| `docs/` | field diagnostics (`rtsp-drops.md`) |
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

```bash
python kastr-serve.py 8971     # dev harness serving the page on http://localhost:8971
python kastr.py                # the full launcher (opens the bundled browser)
```
