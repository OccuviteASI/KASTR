# KASTR

KASTR (Kenton's ASI Streaming Tool with Relay) is a desktop app for low-latency video rooms over
[Media over QUIC](https://quic.video): cameras, screens, RTSP feeds and media files are published to a
relay and watched by everyone in the room. It ships as one frozen binary per platform (Windows exe,
Linux binary, macOS app) that bundles a local web UI, a Chrome for Testing browser, ffmpeg and the
`moq-relay` / `moq` CLI. A box can be a viewer, a publisher, a relay, or all three, and relays federate
into a hub-and-spoke cluster.

## Layout

| Path | What |
|---|---|
| `kastr.py` | launcher: state dir, port, updater, relaunch protocol, `--diagnose` |
| `kastr_serve.py` | local HTTP API + static site (`/api/*`, media store, prefs) |
| `kastr_rtsp.py` | RTSP bridge: ffmpeg + moq publisher pairs, restart ladder, monitors |
| `kastr_relay.py` | hosted `moq-relay`: access codes, tokens, federation |
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
