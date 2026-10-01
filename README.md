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

Since 0.18.0 an RTSP camera can sleep until a viewer asks for it (the row's "On demand" switch; off by default since 0.21.10, see below), publish a small copy
for thumbnails ("Low for thumbnails"), and be recorded on the relay host (Relay page "Record"; segments kept
`archive_hours`, default 24, downloadable from the Relay page and the room's Files panel). kastr.ini also takes
`hook_ready` / `hook_notready` / `hook_read` (commands run on camera up, down and a viewer's first HLS or fallback request -- and, with `ondemand = on`, an on-demand wake -- with `KASTR_EVENT`,
`KASTR_BROADCAST`, `KASTR_FEED_ID`, `KASTR_RELAY`, `KASTR_REASON`, `KASTR_VIEWER` in the environment) and
`hook_timeout` (seconds, default 30).

Since 0.19.0 the relay host's web port also carries the video (`/relay`, WebSocket), so one Cloudflare Tunnel
name pointed at `http://localhost:8000` is enough: browsers open `https://<name>/`, KASTR apps and spokes use
`https://<name>/relay` as the relay address. See `docs/cloudflare-tunnel.md`. Since 0.20.0 browser clients keep an
offline shell (service worker), a kick reaches spokes behind a tunnel in about a second, and an open relay behind a
tunnel is flagged on the Relay page and the gate (set codes and require them).

Since 0.21.4 every response carries `X-KASTR-Version`; a browser's service worker from an older build stands aside
(fresh page, fresh shell), and the page purges a worker that still serves an old masthead — a phone stuck on 0.20.0
heals on its first visit.

Since 0.21.11 the grid composite keeps encoding while the KASTR window is hidden (minimised, a locked console, the Relay
tab in front): the page pushes each drawn frame into the capture stream whenever the browser's automatic capture goes
quiet, and the grid's events say when that happens. Camera monitors copy whenever the camera's publisher copies.

Since 0.21.10 every camera publishes its full pair always: on-demand standby and the 640-wide low copies are off by default
(kastr.ini `ondemand = on` on every box of the fleet, or `KASTR_ONDEMAND=1`, brings both back; stored flags are kept, not
cleared), and the owner page's camera monitors ride WebSockets, so Chromium's six-connection limit no longer caps the
cameras on one page.

Since 0.21.9 the audio delay adapts to the path (it widens while the player reports late frames and relaxes when they stop),
the speaking ring, the mic meter's live tap and the RNNoise noise removal work again (they had read a field the 0.16.0 library
upgrade moved), and a scripted field viewer measures what a tunnel viewer actually receives.

Since 0.21.8 a viewer's stall report no longer restarts a healthy RTSP pair, rebuilds a speaker's camera or evicts a
grid member without the source's own evidence (a secured relay gives none, and one starving remote viewer was cutting
every Mendon and Southridge camera for everyone every 45 s), audio rides a fixed 150 ms delay on the LAN too, the fMP4
fallback player backs off and stops instead of asking every two seconds, the relay host and the page count and log
reconnect loops (the tell behind the 250 Mbit/s bursts), the Windows firewall check takes under a second, a host fetches
the other platform's browser to assemble its install zip, and the avatar initials fit their (slightly bigger) circle.

Since 0.21.7 the Relay dropdown names the host's KASTR on the port it actually runs (no more `:8000`), remote panes carry no
OS tooltip, a web client downloads the full Windows or Linux install zip from More → Settings → About (assembled on the
host from what every install already carries), with `ondemand = on` an on-demand camera shows its low copy the instant it is clicked and the
full picture takes over in place — also when the camera sits behind another site's relay — the spoke's cluster link
writes its state to launch.log and the Relay page, audio through a tunnel no longer clips (a 1 s floor on the audio
buffer's drop rule in the vendored player, plus wider budgets over WebSocket), and a Linux box asks for its firewall
rules once, not on every launch.

Since 0.21.5 phones get the layout they were promised (the phone rules now win the cascade), an iPhone camera goes out
upright (the canvas loop runs wherever WebKit would lose the orientation), an RTSP grid rebuilds only on its own evidence
instead of on any viewer's stall report, a dead camera leaves the grid on its monitor's ladder, and an open spoke says
why it is not registering with the hub.

Since 0.21.0 phones get the phone layout in portrait and landscape (every menu a bottom sheet, camera rotate and mirror),
shared media files scrub without restarting and the sharer hears them ("Hear it myself"), every shared file gets a
resolution picker, the latency stamp is a thin strip in the bottom-right corner, a spotlight follows the participant,
full screen is the whole stage, a hub can update its spokes with one button, and the Relay page is a card grid.
Since 0.21.2 unattended boxes have no camera tile, a grid quadrant wakes and opens its camera, rooms close from the
sidebar (creator or admin) and from the hub, admins remove files and chat lines, web clients' file links work through
the tunnel, and a web client can add an RTSP camera that the relay host pulls on its hardware encoder.

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
