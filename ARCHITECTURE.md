# KASTR Architecture

KASTR (Kenton's ASI Streaming Tool with Relay) is a desktop application for
publishing and watching low-latency video over Media over QUIC (MoQ). It wraps
a browser-based UI in a self-contained executable, bridges RTSP cameras into
the browser, and can host its own MoQ relay. This document describes the system
as of v0.7.0.

## System context

```
  UniFi / RTSP cameras ──RTSPS──▶ ffmpeg bridge ─┐
                                                 │ fMP4 over localhost HTTP
  webcams / screens / files ──▶ browser ◀────────┘
                                  │  WebCodecs encode
                                  ▼  MoQ (moq-lite-05) over WebTransport/QUIC
                            MoQ relay  ◀──── viewers (KASTR on other machines)
                    (shared 10.10.105.190:4443, or hosted locally)
```

Everything on the publishing machine is one process tree: the launcher, a local
HTTP server, per-feed ffmpeg children, an optional moq-relay child, and one
Chrome app window.

## Components

| Component | File | Role |
|---|---|---|
| Launcher | `kastr.py` | Frozen entry point. Starts the server, opens Chrome as an app window on a dedicated profile, ties process lifetime to the window, tears everything down on exit. |
| HTTP server | `kastr_serve.py` | Serves the UI with token substitution and COOP/COEP isolation; exposes the local APIs. |
| RTSP bridge | `kastr_rtsp.py` | One ffmpeg per feed. Turns RTSP/RTSPS into browser-playable fragmented MP4, video-only. |
| Relay supervisor | `kastr_relay.py` | Runs the bundled `moq-relay` (0.14.12) from a generated TOML config; TLS auto-generated, stats enabled. |
| Tab shell | `app.html` | The window's chrome: masthead nav as tabs over persistent iframes. Inactive tabs are parked, not hidden. |
| ~~Publish page (legacy)~~ | removed in 0.6.9 | The old stand-alone publisher lived one release as a fallback after the 0.6.6 merge, then was deleted and unbundled. dist/archive builds still carry it. |
| Live Streams page | `moq-watch-lite.html` (~12,000 lines) | Discovery, grid/program view, per-stream audio with level meters, ordering, stats — plus, since 0.6.6, a second module script carrying the ported publish core (sources, slots, encoder control, operator naming, resilience). Module scope is the collision boundary; `window.__mineAccept` and `window.__publisher` are the seams. |
| Brand/shell script | `assets/asi-brand.js` | Masthead, version + release-notes popover, relay badge with stats popover (polls `/api/instance` to follow runtime repoints), heartbeat, diagnostics self-report, window-geometry reporter. |
| Home / relay / stats | `index.html`, `relay.html`, `stats.html` | Cards, relay hosting UI, relay statistics (embedded in the relay badge popover). |
| Build | `build.py`, `fetch-helpers.py` | PyInstaller onefile builds, versioning, release archives, helper binaries. |

The MoQ implementation is the `@moq/publish` and `@moq/watch` libraries, loaded
from esm.sh (currently unpinned — see Risks).

## Local HTTP API

All served from the same loopback server as the pages.

| Endpoint | Purpose |
|---|---|
| `GET /api/instance` | Identity: `{app, version, frozen, pid, port, mode, viewing, chatHub}` (0.13.0: `viewing {n, ageS}` from the pages' diag snapshots or `null`; `chatHub` = this KASTR serves the shared chat store). Lets a second launch distinguish "another copy of this build" (defer to it) from "some other server" (step aside to a free port). `relay` is the value currently substituted into pages: the masthead badge (5 s) and the Relay page poll it so long-lived documents follow a runtime repoint. |
| `POST /api/alive` | Page heartbeat (5 s). The launcher's fallback liveness signal after a browser hand-off. |
| `POST/GET /api/diag` | Pages post their own state (publisher slots, encoder resolved config, recent library errors, watcher state); GET returns the latest per page. In-memory, loopback-only. |
| `POST /api/window` | The page reports window geometry; stored in `window.json` and replayed as Chrome flags on next launch. |
| `POST /api/rtsp/add,remove` · `GET /api/rtsp/list` | Manage bridge feeds. |
| `GET /rtsp/<id>` | The feed itself: an endless fragmented MP4. Each GET spawns/attaches an ffmpeg reader. |
| `POST /api/relay/start,stop,use` · `GET /api/relay/status` | Hosted-relay control. |
| `GET /api/auth` · `POST /api/token` (relay host, port+1) | Auth shape (`secured, codes, talking, chat, state`) and the minter: `{room, code, roomCode?, host?}` → identity-scoped tokens (0.13.0, see ledger). |

## Publishing paths

**Device sources** (camera, screen/window/tab, file) use the library's
`<moq-publish>` element per slot. Capture constraints, encoder config, naming
and announce state are driven from the page; going live flips
`announce="always"`.

Each device source can **pause its video and keep its audio**: the
element's `invisible` control gates the video encoder for every source
kind and the camera capture itself (a paused camera is released), while
the mic leg is gated by `muted` alone. The catalog's video and audio
halves are independently optional, so pausing drops the video renditions
live and viewers keep the audio subscription untouched. Each source also
carries a session-durable mic mute (`entry.micMuted`, the `videoPaused`
idiom): it is folded into every place the effective `muted` is derived
(start, restart, mic-target change), because those recompute it wholesale
and a bare property write would silently revert. Both levers are
remotely controllable over the sources channel.

**RTSP sources** cannot enter the browser directly, so they take the bridge:

```
camera ──RTSPS/TLS──▶ ffmpeg ──fMP4 (video-only)──▶ <video> element
       ▶ captureStream() ▶ Video.Capture ▶ VideoEncoder ▶ Broadcast ▶ relay
```

Bridge decisions, made once per URL from a ~3 s probe (codec, size, colour
range; cached):

| Source is… | Bridge does |
|---|---|
| H.264, ≤1920 wide, limited range | **stream copy** (~1.15× realtime, no quality loss) |
| anything else | re-encode: scale to ≤1920, full→limited range, hardware encoder (`h264_qsv → nvenc → amf → mf → libx264`), each candidate validated once against a local test pattern before trust |

The bridge output is **video-only, deliberately**. The RTSP publish path builds
a video-only broadcast, so camera audio was never published — and its presence
in the muxed stream throttled `captureStream()` to ~1 fps (bisected on a real
camera: with audio 1 fps, without 30 fps, resample to 48 kHz no help).
Publishing RTSP audio is future work: a separate audio pipeline, not a bridge
flag.

**Encoding is pull-based.** MoQ only produces what is subscribed to:
`encoderActive=false, frames=0` with no viewers is the *correct* idle state,
not a fault. This shaped several design decisions below.

**State tracks (0.13.0).** Everything about a member that is not media rides two
small JSON broadcasts written with `@moq/json`: `.state/<room>/<HOST>/<PEER>` on the
relay's public prefix (`state.json`: identity, join time, `publishing`, `speaking`,
`typing`, avatar, preview stamp; `preview`: 224 px WebP frames every 2 s) and
`<room>/<HOST>/.member/<PEER>` behind the room token (`room.json`: spotlight, recording,
stall reports, control pulses, grid geometry, media state, shared files; `chat.json`: a
50-record Window of this member's posts; `preview` when the room is locked). The producers
use the raw `Net.Broadcast.Producer` on a `Reload` that never gives up (`timeout: 0`):
every established connection re-creates the tracks (`latencyMax: 60000`), seeds their
group sequence from the wall clock and rewrites the latest values; a 20 s heartbeat
rewrites them again. Consumers (`stateSubscribe`) apply every value in order and
re-consume on error, on silence, or when no first value arrives. The 0.7–0.12 announce
idiom (`<room>/.kind/<ts>/<b64>`) remains only for `.channels` (the registry, whose
lifetime is deliberately not a member's) and, for one release, the `.since`/`.presence`
compat announces so 0.12 pages still see 0.13 members.

**Room rail (0.13.1).** `#sidebar` lists every room as a card (`.sbcard`), the joined one
marked `.cur`; order = `main`, then the operator's dragged order (`kastr.rooms.order.<opSlug>`),
then alphabetical; the open width is `--sbw-open` (grip, `kastr.sidebar.w`), collapsed 44 px. The
banner shows the room name only.

**Mic pipeline (0.13.1).** `kastr.mic.mode` off | browser | rnnoise: browser = getUserMedia
NS/AEC/AGC constraints; rnnoise adds `mic → RnnoiseWorkletNode (assets/noise/, 48 kHz mono) →
MediaStreamDestination → publish.audio.in.source {kind: "voice"}` with a re-inject watchdog and
a toast-and-fallback on any failure. `voiceIsolation` is requested only when the device has
reported it back.

**Relaunch (0.13.1).** `relaunch_self(reason)` → child env `KASTR_RELAUNCH{,_PID,_PORT}` →
`await_predecessor` (≤ 20 s) → no hand-off. In a container (`KASTR_CONTAINER=1`) the process
exits 75 and the entrypoint restarts it.

## Watch path

Discovery is the relay's `announced()` stream, filtered to `*.hang`. Each
stream gets a persistent tile (`<moq-watch>` + canvas); tiles are never
recreated on switch, so decoders stay warm.

- **Bandwidth follows the window**: the selected stream is always
  `visible="always"`; unselected grid tiles use an 800 px prefetch margin;
  hidden tiles download nothing.
- **Audio**: the library's `volume` drives a real GainNode with a 200 ms ramp.
  Exactly 0 flips the element to muted and tears the audio subscription down;
  anything below its .001 cutoff hard-zeros the gain *without* teardown. KASTR
  therefore does everything with plain volume writes: audible streams get
  `master × level`, silenced-but-warm streams get a floor value (0.0001), and
  warm-audio-off writes an exact 0 to deliberately drop the subscription. A
  1 s corrector re-asserts wanted volumes, because flipping the element's
  `muted` makes it save/restore `volume` behind the page's back — which is
  also why nothing ever writes `muted`. Modes: follows-selection →
  all-streams → manual.
- **Level meters**: one AnalyserNode per tile, a read-only parallel tap off
  the library's audio graph root — KASTR's only contact with the graph. A
  single rAF loop paints every meter (green = audible, grey = decoding but
  silenced) and parks while the tab is hidden. Streams whose catalog carries
  no audio get a crossed-out marker instead of audio controls.
- **Naming**: operator-tagged broadcasts (`host/kenton-j/cam.hang`) label as
  "Kenton J — cam"; legacy two-segment names keep showing the leaf.
- **Subscription is per stream, off by default**: a row exists for every
  announced broadcast, but a tile connects nothing until switched on. Each
  `<moq-watch>` element opens its own QUIC connection plus a catalog
  subscription even at `visible="never"`, so parking is the element kept in
  the DOM with **no `url` attribute** — the library then holds its
  connection URL undefined and opens nothing at all. Re-arming is
  `setAttribute("url", …)`; the element is never removed or moved (a DOM
  disconnect is the teardown that historically broke audio). The enabled
  set persists per device.
- **Audio-only tiles**: a catalog with no video renditions leaves the
  library's video pipeline inert and silent (no track, no decoder, no
  error; stats stay undefined), so such tiles get a face — big meter +
  “audio only” — instead of a black canvas, `visible="never"` (audio is
  gated by paused/muted alone), truthful stats, and a starvation-check
  exemption keyed on the catalog (`hasVideo === false`, deliberately not
  “unknown”: a catalog that never arrives still reports — the relay
  black-hole case the reporter exists for).
- **Tile sizing**: the grid is fine cells (`minmax(104px,1fr)` columns,
  88 px rows, dense flow); every pane carries inline column/row spans
  (default 3×2 ≈ the old tile), dragged by a corner grip and remembered
  per device (`kastr.watch.size`). Spans are clamped to the live track
  count at apply time; video letterboxes inside the fixed-height pane
  (grid mode only — program mode stays content-sized).
- **Ordering**: the grid and list are ordered together via `style.order` —
  the DOM never moves, because moving a `<moq-watch>` disconnects it and
  tears the stream down. Manual drag (remembered per machine) or name /
  person / newest sorts; arrows, digit keys and row numbers follow the
  visual order.
- **Stats honesty**: the library's `frameCount` counts chunks *received*, before
  decode. The panel labels it "chunks received" and adds a `picture: yes/no`
  row read from `video.out.frame` — the only signal that actually answers
  "is there something to draw".

## The kastr.sources channel

A BroadcastChannel shared by every view on this profile (the Live Streams
page's two halves, the legacy Publish tab, any second window). Within the
merged page the publish half ALSO hands each announcement to the watch
half synchronously (`window.__mineAccept`) — a channel object never
delivers to itself, and self-suppression must not lose the cold-start
race or depend on the channel existing at all. Messages:

| kind | sender | meaning |
|---|---|---|
| `sources` / `hello` | publish views | `{peer, view, sources[]}` — announce what this view publishes; `hello` also solicits replies. The Watch page sends a peer-less `hello` at load to solicit without owning anything. |
| `bye` | publish views | the view is going away (pagehide). |
| `stop` | any view | `{target, id}` — ask the owning peer to remove a source. |
| `control` | Watch self-view | `{target, id, set:{videoPaused?, micMuted?, cameraId?}}` — ask the owner to flip a lever; the owner applies it, repaints, and announces, which snaps the asker to authoritative state. |
| `micdev` | Watch self-view | `{target, micId}` — switch the owner's machine-wide microphone; applied through the same path as the picker (remembered, rate-limited rebind, announce). |
| `thumbs` | Watch | lease request: keep posting self-view thumbnails for ~12 s; sent every 5 s while the pane is visible. Zero standing cost once the asks stop. |
| `thumb` | publish views | `{peer, id, w, h, blob}` — one small webp of one source, ~every 800 ms while leased; same-profile IPC, never the relay. |
| `starved` | Watch | a subscribed stream delivered nothing for 25 s (report-only). |

Per-source announcement fields: `{id, kind, label, name, enabled, live,
videoPaused, micMuted, carriesAudio, pausable, deviceId}`. Entry ids are peer-local,
so commands are addressed by `(target peer, id)`. Both receivers dedup on
a state signature so 4 s liveness re-announcements do not rebuild UI.
State changes (pause, mute, mic retarget) announce immediately.
Announcements also carry peer-level device truth — `cameras[]`, `mics[]`
(physical devices only, the mic picker's filter) and `micDevice` — which
feeds the self-view's switch menus.

The Watch page renders these announcements as the “My streams” self-view
— fed by announcements, never subscriptions, so parked streams appear;
rows aggregate across peers; button flips are optimistic with the
owner's announce as the authority.

## Resilience

Everything here was added in response to an observed failure, and everything
speculative was later removed (see Decisions).

- **Software-encoder fallback** (publish page): the library picks encoders by
  `isConfigSupported(prefer-hardware)`, which can approve an encoder that fails
  on the first real frame ("Encoding error", browser-specific). The page shims
  `isConfigSupported` behind a per-machine flag (`localStorage
  kastr.encoder.software`) and watches the console for the library's failure
  line; the first failure sets the flag, rebuilds live sources on software
  encoding, and says so.
- **RTSP reconnect** on *unambiguous* signals only: the feed's `ended` event
  (UniFi invalidates RTSPS sessions) and the capture track's `readyState ===
  "ended"`. Backoff 1 s → 30 s, reset on recovery. No timers guessing from
  silence.
- **No automatic renames.** Names are deduplicated locally (this browser's own
  sources, plus the Share panel via BroadcastChannel). Relay-state-driven
  renaming was removed: a previous session's lingering announce is
  indistinguishable from a rival publisher.
- **RTSP freeze recovery** (publish page, 1 s poll): the bridge stream is
  endless, unseekable progressive fMP4, and Chrome reads only ~2 s ahead of
  the playhead — so a slow element never shows as buffered lag; the backlog
  piles up in ffmpeg and the sockets. The page therefore tracks **drift**
  (wall clock vs media clock — a live camera produces exactly real time),
  chases at 2× playback past ~3 s behind, and reconnects past 20 s. Three
  restart triggers observe broken facts directly (never idleness — the
  0.5.28 rule): playhead frozen >10 s while playing with data; a media
  error after wiring (previously invisible: `faultText` goes quiet once a
  slot wires); keyframes stopped while frames flow (a stranded encoder
  keyframe gate blanks every new viewer).
- **Bridge send timeout**: `handle_stream`'s pump used to block forever in
  `wfile.write()` when a reader stopped consuming, which wedged ffmpeg on
  `pipe:1` — and ffmpeg's own `-timeout` is camera-side socket IO that
  cannot fire while the child is stuck writing. A 15 s socket send timeout
  turns the wedge into an `OSError`, releasing the child; stale stderr is
  cleared per spawn so a fresh attempt reports its own errors.
- **Starvation reports**: the watch page posts `{kind:"starved"}` on the shared
  BroadcastChannel when a subscribed stream delivers zero bytes for 25 s; the
  publish page reports it in the status line. Report-only.

## Lifecycle

- **Single instance, build-aware**: on launch, `GET /api/instance` on the
  target port. Same build → show its window and exit. Different build or other
  server → take the next free port.
- **Window = process**: `supervise()` waits on the spawned browser process,
  with the profile lockfile (absence = window definitely gone) and the page
  heartbeat (150 s grace) covering the hand-off case. Every exit path funnels
  through one idempotent `teardown()`: ffmpeg first, then relay, then server,
  each step bounded, an 8 s daemon watchdog, and `os._exit()` from a `finally`
  so no failure inside teardown can prevent the exit. A windowed build has no
  stdio — everything that writes to a console is guarded.
- **Onefile pairing**: PyInstaller onefile runs as bootloader + child; the
  child waits on the parent's process handle (never `os.kill(pid, 0)`, which on
  Windows terminates) and dies with it.
- **Chrome flags**: dedicated profile, `--app=`, autoplay allowed, background
  throttling disabled (occluded windows would otherwise throttle capture to
  ~1 fps), geometry restored from `window.json` (`--start-maximized` on first
  run or implausible saved bounds).
- **Parked tabs stay painted**: inactive shell tabs get `.bg` (z-index 0,
  opacity 0.004, `inert`) instead of `display:none`, because `captureStream()`
  only produces frames from rendered elements.

## Build & release

**Platforms (0.13.1).** Windows (`build.py`), Linux (WSL, `build.py`), macOS (`build-mac.sh`, Apple Silicon, see `MACOS.md`), Docker (`docker-build.sh`, see `DOCKER.md`). The three-platform update feed is assembled with `build.py --publish-only` on the machine holding all three `dist/<plat>` trees; `latest.json` carries `win32`, `linux`, `darwin`.


- **PyInstaller onefile** per platform (no cross-compiling): Windows native,
  Linux via WSL (`/opt/kastrbuild`), macOS supported by the script but no
  hardware to build on. Bundled: site files, `VERSION` (generated from the
  version being built, not copied), `RELEASES.md`, ffmpeg + moq-relay from
  `bin/` (Linux ffmpeg pinned by SHA-256 in `fetch-helpers.py`).
- **Version discipline**: `VERSION` records the *last built* version, matching
  `BUILT_VERSION` markers and the running app. A build takes the next patch
  number; `--keep-version` joins the same release from a second platform.
  Failed builds burn nothing. Release notes are enforced: an undocumented
  version gets a visible stub.
- **Archives**: written *after* signing/plist finishing, one zip per release
  containing every platform folder whose `BUILT_VERSION` matches (provenance-
  gated, named skips), never silently shrunk (`--allow-shrink` to override),
  retention keeps the newest 5 (`--discard <ver>` retires a broken one).

## Decision ledger

| Decision | Reason (all measured, not assumed) |
|---|---|
| Bridge output is video-only | Camera audio in the mux throttled element capture to 1 fps; the publish path never sent audio anyway. |
| Software-encoder fallback | `isConfigSupported` approved a hardware encoder that failed on the first frame; browser-specific, invisible except in the console. |
| Encoder settings default to Auto | Forcing H.264@1080p made the library derive 1904×1072 against 1920×1088 frames → "Encoding error". Auto matches the source. |
| No timer watchdogs | The 20 s "encoder quiet" watchdog restarted healthy streams whenever viewers left (pull-based ⇒ idle is normal); the 15 s silence timer false-alarmed. |
| No relay-derived renaming | A relaunch's own lingering announce looks like a rival; caused `-2` renames every restart and a rotation death spiral. |
| Parked tabs, not hidden | `display:none` stops capture; 30 fps in front vs 0.24 fps hidden. |
| Warm audio via a floor volume, never a spliced gain | Library `volume` drives a real (ramped) gain; exactly 0 tears the subscription down, values under .001 silence without teardown. The old spliced GainNode ended up wired in parallel with the library's own path — which re-adds root→gain→destination on every volume write — so it muted one path while the other played on. Deleted in 0.6.1; the only KASTR node on the graph is a read-only meter tap. |
| `VERSION` = last built | The old "next build" meaning read as a version mismatch against the app and `BUILT_VERSION`. |
| Archive after finishing steps | The zip previously captured the unsigned exe / unpatched plist — the redistributed copy was wrong. |
| Room codes are the credential; the minter is the authority | A secured relay's kastr mints HS256 JWTs on relay-port+1 (pure stdlib: hmac+sha256; symmetric is correct — signer and verifier are one machine). Claims ride the relay's own contract: root/put/get/exp/iat, token in `?jwt=` on the connection URL (the cert fetch strips the query, bundle-verified). Member tokens scope put+get to the room; the registry announce rides its own token scoped to `.channels/<slug>`. Listing stays anonymous via `public = { subscribe = [".channels", ".stats"] }`. |
| The relay's key path must be RELATIVE | moq-relay 0.14.12 routes the auth key path through a layer that URL-parses it: `C:/...` reads as scheme `c`, every key load fails, every well-formed token dies as 502. The generated config says `key = "auth.jwk"` and the relay runs with cwd = state_dir. Proven live. |
| window.__auth is the one token seam | Detection (GET :port+1/api/auth, 2 s abort) + mint + `withToken(url, role)`; every relay connection site wraps through it and open relays get identity. Tokens live in sessionStorage per relay origin, never localStorage. |
| Layouts are grid PLACEMENT, never reparenting | Collage and spotlight assign the same #stage children rows/columns via classes and inline styles; a pane never moves in the DOM (the teardown rule that has held since 0.5.x). Content detection rides the 0.6.8 naming contract: camera leaves are literally `camera(-N)`, so any other leaf is content. |
| Collage cards are aspect-locked, px-sized | 0.7.5: the best-fit loop still picks the column count, but the stage writes `repeat(cols, <px>px)` with the tile width clamped to both the width and height budget; `aspect-ratio:16/9` + `grid-auto-rows:auto` + centered content derive row height from the cards instead of stretching them. Canvases crop (`cover`) everywhere except the spotlight main (`.mainstage` keeps `contain` — shared content never loses edges). |
| Room persistence is a sessionStorage ticket | 0.7.5: joining writes `kastr.rejoin` (room, code, name, toggles); gateShow replays it silently (awaiting authDetect so secured relays re-mint), Leave/confirmed-disconnect/app-close clear it, room switches update it, and any failed replay clears the ticket and falls back to the normal gate. sessionStorage = per app window, shared with same-origin iframes — exactly the requested lifetime. |
| The relay light is server-truth | 0.7.5: the shell polls /api/relay/status itself; the Relay page's frame is never asked (closed tab = no frame; hidden frame = throttled, stale status that once held the light on after a stop). The disconnect plug confirms while `__join.state()` is joined and leaves via `__join.leave()` so the ticket dies with the room. |
| Snap browsers get a snap-visible profile | 0.7.5: snap's home interface denies dot-directories, so `~/.local/share/ASI/KASTR/browser-profile` silently became an ephemeral profile (localStorage lost per run — the Linux "name not saved" report). `browser_is_snap()` routes those browsers to `~/snap/chromium/common/kastr-profile`; non-snap browsers rank first in discovery; launch log and --diagnose print the effective profile. |
| Publish URLs go through authUrl at EVERY commit | 0.7.6: the go-live rewrite was the one site passing the raw input — on a secured relay it stripped the token at the exact moment of going live and every publish died silently (reproduced: tokened URL before live, bare after, no discovery echo). Grep rule: any `setAttribute("url", ...)` or relay URL handed to a publish-side connection must wrap authUrl()/withToken(). |
| ON AIR badge = discovery echo, not attributes | The watch half exports its `suppressed` set as `window.__echoed` — exactly the own paths the relay handed back through discovery. An element slot live >8 s with no echo badges "NO RELAY" (3 s tick while live). The attribute-derived badge lied identically for auth failures, wrong relays and network holes. |
| Spotlight votes are room-scoped announces | `<room>/.spotlight/<ts>/<b64url target>` — the chanReg track-less-Broadcast pattern, but under the room prefix so plain member tokens cover it when secured. Newest ts wins, applied ONCE per winner (fighting the person at the keyboard helps nobody); votes clear on connect()/leaveChannel (room switches must not leak votes), and the stage releases when the last vote dies only if the user hasn't re-selected. |
| Host segments carry a MAC suffix | 0.7.6: cloned images (robot boxes) share hostnames; identical host segments = byte-identical broadcast paths = relay collision + every device suppressing the twin as "its own" (each sees only itself, all lights green). host_slug appends `-%04x` of uuid.getnode() — stable, stateless, invisible in the UI (labels are operator-based). |
| Top-bar camera controls ride the same bus | The main camera's mic/video/device controls by Leave resolve through minePeers and post the identical sendControl/micdev messages the rows post — no second control path to drift. The local camera row is simply filtered out of #mine-rows. |
| px-sized layouts must self-relayout | 0.7.5 made collage columns computed px, not fr-elastic — anything that changes the stage box (window resize, panel toggles) MUST re-run applyState. A debounced window resize listener + a ResizeObserver on #stagewrap do it (0.7.7). Note for rigs: RO delivery is render-gated — a hidden pane delivers nothing until a frame is painted (screenshot forces one). |
| One menu, one anchor memory | Every chevron opens the shared #mineMenu through openMineMenu; `mineMenuAnchor` there makes the opener also the closer. A per-chevron toggle would have meant N copies of the same state. |
| The gate is a formality, never a wall | 0.7.7: relay-only machines dismiss the gate (✕/Esc) and live at prejoin — the chip ("Join a room…") and ☰ reopen it. The gate covered the in-page masthead relay badge, which read as "can't reach the relay server" on machines using the bare page. |
| Occupancy = publishers, counted from paths | People per room = distinct host/operator segments: pre-join from the open-relay root scan (listChannels `count`), joined from tile keys + self. Pure viewers announce nothing and are honestly uncountable; secured relays hide the pre-join scan, so the badge is omitted rather than wrong. |
| The relay page probes its own relay anonymously | "Streams on this relay" opens a fresh 1.5 s announce drain every 5 s against `state().url` — no persistent connection to wedge, self-healing by construction, and truthful under auth (secured relays show room markers + a note, because that is exactly what anonymous subscribe can see). |
| Cluster-ready, config-only | moq-relay 0.14.12 (bundled) does symmetric mesh clustering: `[cluster] connect=[hub]` per spoke + `[client.tls] disable_verify=true` on a trusted LAN; paths federate unchanged so discovery/rooms need zero client work; each node needs a unique `[stats] node`. Secured mode needs the same JWK everywhere + a full-access relay token. kastr_relay does not write these yet — deliberate future UI. |
| Own panes are grid items via display:contents | 0.7.8: #mine and #pubPanes are display:contents wrappers, so each .pubpane is a direct #stage grid cell — first-class tiles without moving a node (the never-reparent rule holds; captureStream keeps painting). Every "my windows stack wrong" report traced to the one-card-with-sub-panes design; there is no card any more. |
| Collage rows are definite px | grid-auto-rows:auto lets CONTENT stretch a row (an RTSP video's natural height, a rows strip). applyState writes gridAutoRows = round(tw·9/16) with the px columns — no content anywhere can bend the grid. |
| Publish is healed by the discovery echo | The watch side always had heal loops; the publish side had none — the root of "I see them, they can't see me". A slot live 20 s under a healthy relay (tri ok + joined) with no echo of its own path in window.__echoed is objectively dead: rebuild it (30 s backoff). The echo is an observed fact; the guard on tri prevents pointless rebuilds during outages. |
| Non-MoQ pages probe reachability for the light | asi-brand: no __relayHealth and no proxy tri → CORS-fetch the in-use relay's /certificate.sha256 every 5 s (no-cors is impossible: COEP require-corp rejects opaque responses). Green on answers, red after 15 s of silence — "reachable" is exactly what such a page can honestly claim. |
| The streams panel probes the relay in USE | Local relay when hosted, else /api/instance's relay — and every message names the probed host. Probing only the local relay read as "stuck" on machines pointed at the shared relay. |
| RTSP panes attach on first data | The <video> loads detached; the pane joins #pubPanes on loadeddata. A camera that never delivers never opens a window — the toast (window.__toast) carries the fault instead, once per failed attempt. |
| HTTP ingest reuses the RTSP bridge unchanged downstream | input_args grows an http(s) branch (no rtsp knobs; NO -re and NO reconnects for static files — reconnect restarts fought Range seeks into NAL corruption, observed live, and pacing is pointless when the video element plays timestamped output at 1x); page URLs resolve via lazily-imported yt-dlp BEFORE the bridge lock (feed.url = resolved, feed.source_url = typed). Known-page hosts fail loudly; unknown hosts fall back to ffmpeg verbatim. |
| The operator name is install-state, not browser-state | operator.json beside the relay state (reachable in app AND dev via relay.state_dir); POST /api/operator on join, /api/instance carries it, the gate prefills from it when localStorage came back empty. Root cause history: snap Chromium's ephemeral profile, twice reported. Also: syncOperator runs for EVERY join now — the camera-branch-only call left viewer-joins nameless and every later share unlabeled. |
| Room embers are leaver-held announces | 5-minute `.channels/<slug>` announce from the page that just left (its own Reload connection, timer-closed). Cancelled by chanRegSet/joinChannel (a real holder or rejoin replaces the ember) and pagehide. The honest limit of a serverless room list: closing the app releases early. |
| Own-slot audio comes off audio.in.source | The element's `sources.audio` is device plumbing; the live track rides `publish.audio.in.source` as a {track, kind} wrapper (unwrap before use). One AudioContext (click-resumed) feeds per-slot analysers for the own-tile ring; FILE slots also get an <audio> monitor in the pane (dies with stopSlot; screens never monitored — feedback). |
| Elevated actions stay POST + loopback-only | /api/relay/firewall refuses GET (kastr_serve's do_GET dispatches into relay handlers too) and any non-loopback Host — a LAN-bound instance must not accept firewall changes from other machines. Windows elevation via Start-Process -Verb RunAs -Wait -PassThru; a UAC decline is a reported failure, not silence. |
| The relay host is the fleet's version authority | 0.8.1: clients MATCH the relay host's KASTR version at launch — different (either direction) means download, sha256-verify, rename-aside swap, relaunch (KASTR_UPDATED guards loops; failures launch as-is). Every KASTR serves its own binary; dist/updates/<plat>/ carries the other platform. The check runs BEFORE anything binds — no teardown obligations. Loopback relay hosts are skipped (that machine IS the authority). |
| Stats needs a NODE NAME | [stats] enabled without node publishes at exactly `.stats/node` — an announce whose path equals the page's prefix arrives with an empty relative path and is discarded by the stats bundle. One line (node = host_slug) fixed a page that "never worked"; clusters require the uniqueness anyway. |
| Federation is a saved hub URL | relay-cluster.json → [cluster] connect + [client.tls] disable_verify at config write; a running relay restarts itself on save. disable_verify is the honest LAN tradeoff (throwaway per-start self-signed certs make pinning impossible). |
| Stage chrome is hover-revealed, truth excepted | Labels/bars/chevrons rest at opacity 0 (pointer-events none) — but a warn badge (NO RELAY) forces its bar visible: the truth surface must never be hidden by a polish rule. |
| Rings die with their meters | A tile whose audio graph is torn down (mute → volume 0 teardown) must CLEAR .talking, not freeze it — the toggle now runs for analyser-less tiles in both meter loops, and attachMeter clears on root loss. |
| The PiP mini window rides the share gesture | Document Picture-in-Picture needs transient activation: the window opens synchronously with the screen-share click, never later (you cannot pop it when the user leaves — no gesture exists then). Absent API = silent no-op; controls act directly on the publish state. |
| Recording is composition, not capture | 0.8.6: the stage is recorded by redrawing every visible tile's canvas/video at its on-screen rect into one canvas -- not getDisplayMedia (no picker, no hall-of-mirrors) -- and mixing audio by bridging each tile's own AudioContext through a MediaStreamDestination into one recording context (contexts cannot connect directly). The room learns about it the way it learns about spotlights: a track-less announce under the room prefix. |
| The relay in use is the version authority, now | 0.8.6: the launch-time check missed every relay switch made afterwards. The launcher installs `kastr_serve.UPDATE_HOOK`; a relay switch or the Check-for-updates button runs the same probe/swap on demand, then `teardown()` (children + browser) before the delayed relaunch so the new version finds its ports free. |
| Every member holds the room lock | 0.8.6: the single-holder rule (`held`) read a cached channel list that still contained the holder's own just-cancelled ember, so a creator's rejoin cleared instead of set and the passcode vanished. Track-less registry announces tolerate several holders, so every joined member simply holds the record -- the lock lives as long as the room does. |
| Wedged encoders are detected by demand, never idleness | 0.8.6: the removed-for-cause watchdogs restarted healthy idle encoders. The stall detector only acts when `video.out.active` proves a viewer is pulling, the capture track is live and unmuted, and the frame count is flat -- then it does exactly what the operator did by hand (pause/unpause), escalating to a rebuild. A muted track (locked screen) is handled separately by pausing video for viewers. |
| The viewer is the only honest freeze detector | 0.8.7: the 0.8.6 detector keys on the encoder's frame count, which keeps moving when the wedge is downstream (track/transport) -- the field freeze survived it, and only the OWNER's rejoin cleared it. So the starving viewer says so: a track-less `<room>/.stalled/<ts>/<b64 path>` announce (spotlight idiom), which the owner's discovery loop maps to its own slot and answers with the manual remedy (nudge, then rebuild) per source. Demand-proven by construction; idle sources are never touched. |
| Rename re-stamps segment 2, never re-derives names | 0.8.7: `withOperator` deliberately leaves stamped 3-segment names alone (dedup suffixes must survive), so a live rename replaces only the operator segment and re-runs the dedup; element slots follow a `name` attribute write, RTSP/grid must rebuild (their announce is fixed at creation). |
| A failed swap rolls back; the folder always has KASTR.exe | 0.8.7: field report -- only `KASTR.old-<ts>.exe` remained after an update (AV/OneDrive held the fresh file during `os.replace`). Placement retries, then the aside copy is renamed back; the except path restores too. And the runtime sweeps `.old-*` because a field machine never runs build.py. |
| Files ride the relay HOST's KASTR, not the relay | 0.8.7: moq-relay moves tracks, not blobs; every KASTR web service already sits beside the relay, so `/api/files` on the relay host is the one address everyone in the room can reach. Presence is the lifetime: the sharer announces `.files/...` while joined and deletes (token) on leave/pagehide (sendBeacon `POST ?_method=DELETE`), with a 24 h server sweep for crashed pages. Cross-origin by design: CORS `*` + CORP `cross-origin` on those responses only. Same-host pages use their own origin (any port); others assume KASTR's default 8000. |
| People are cameras | 0.8.7: a box that only publishes RTSP/screen/file is a share, not a person -- People counts filter content paths, and such boxes can opt out of watching entirely (publish-only: visible=never + volume 0). |
| consume() lives on the established connection | 0.8.7: relay attribution was dead code since 0.8.2 -- the Reload wrapper exposes announced/stats/close only; `established.peek().consume(".stats/node/<name>")` yields the subscriber.json whose keys are full announced paths. `announced(prefix)` yields paths RELATIVE to the prefix. |
| The profile answers the name question once | 0.8.8: `kastr.profile` {first,last,avatar} replaces the loose operator-name and avatar keys (migrated on first load). A saved profile makes the launch a silent rejoin of `kastr.lastjoin` through the existing rejoin-ticket path -- joinNow itself did not change; Leave clears lastjoin so the picker returns. |
| Focus on content is visibility "never", not teardown | 0.8.8: the rail is emptied so every non-main tile takes the existing railHiddenNames → visible="never" road (no download, audio untouched); own panes are parked off-stage but still painted (captureStream stalls unpainted). One flag, one applyState. |
| Grid cell zoom is a CSS transform over shared rect math | 0.8.8: the composite is ONE stream; the owner announces its geometry ({n, layout, cells}) track-lessly and the viewer duplicates gridRects to map a click to a cell and to compute translate/scale for the canvas. The recorder crops the same rect. |
| Close the window before relaunching, two layers | 0.8.8: Chrome hands a second launch to the process already holding the profile, so the tracked Popen can be dead while the window lives. Layer 1: the heartbeat answers 205 and the page closes itself. Layer 2: browser processes whose command line names the profile dir are killed. The relaunch shell is detached (DETACHED_PROCESS, new group, breakaway) so os._exit cannot take it down. |
| Fine tracks centre the short row | 0.8.8: the collage's grid stays a grid (drag order, dense flow untouched): columns are doubled half-tracks, every cell spans two, and the first cell of a short last row starts best−k tracks in. |
| Two trust regimes, one relay | 0.8.9: desktop pages keep `http://relay:4443` -- the @moq library pins the relay's generated self-signed cert by fingerprint for WebTransport and falls back to plain ws. A phone page is https, cannot mix content and (iOS) has no WebTransport, so it needs chain validation: KASTR mints a per-install CA + leaf (kastr_tls), the relay gets a second `[web.https]` listener on port+2 with that leaf, and the https page is rewritten to `https://relay:4445`. The QUIC listener keeps `generate` so nothing changes for desktops. |
| The CA is installed by the person, once, on purpose | 0.8.9: no silent trust-store writes. The Phone access card serves `/ca.crt` and the two vendors' install recipes; until the phone trusts the CA the https page simply will not open, which is the honest failure. |
| Voice isolation rides the element's own seam | 0.8.9: `publish.audio.in.source` is the audio encoder input the library itself mirrors the mic into; setting `{track, kind:"voice"}` there keeps Opus in voip mode, and a subscribe() watchdog re-injects when a device switch or constraint change re-asserts the raw track -- the exact pattern the blur pipeline proved on `capture.in.source`. The gate is conservative (floor +6 dB, -20 dB floor gain, 80 ms hold): trims hiss between words, never fights a loud room. |
| A file picker is not another document | 0.8.9: the window-blur close exists for clicks that land in the shell's masthead; a native file dialog blurs the window too. `__pickFile` marks the interval so the popover that asked survives. |
| Convert audio KASTR cannot decode, keep the video | 0.8.9: Matroska commonly carries AC-3/DTS that no browser plays; a 4 MB EBML peek finds the audio CodecID and the bundled ffmpeg remuxes to MP4/AAC with `-c:v copy` -- seconds, not a transcode. The one-shot `/api/media/<id>` GET deletes the file behind it. |
| Relaunch is one function now | 0.8.9: `relaunch_self` (detached shell, env scrub, KASTR_UPDATED) is shared by the self-update and the Relay page's Apply & relaunch; the mode switch drops `--relay-only`/`--page` from argv so kastr.ini decides. |
| A shared file is played by KASTR, not the library | 0.8.10: the vendored file source plays a detached, muxed `<video>` and `captureStream()`s it -- exactly the configuration this repo had already measured stalling (unpainted element, muxed A/V), so viewers got audio-only catalogs. KASTR now owns the element (attached to the pane), draws it to a canvas it captures (rVFC + a 30 Hz timer so a minimized window keeps publishing) and routes audio through WebAudio, handing both tracks to the element's own signals -- the same seam the screen path uses. Owning the element is also what makes play/pause/seek/loop possible. |
| Room-wide controls are pulses, state is an announce | 0.8.10: `.media` carries the owner's playback state (position extrapolated by viewers from `at`); `.mediactl` carries commands as 2.5 s pulses with a nonce, and only the owner (mineNames) acts. Nothing in the relay knows or cares -- track-less announces again. |
| Convert what the browser cannot decode, keep what it can | 0.8.10: a server-side `ffmpeg -i` probe on the first megabytes decides per stream (video → H.264, audio → AAC, else copy); the client no longer guesses from the container. |
| Store where the file can actually be fetched | 0.8.10: the relay host is asked (`/api/files?room=`) before it is trusted; otherwise the file lives on the sharer's KASTR and is announced under a LAN address from `/api/mobile`, with the loopback caveat said out loud. |
| Going live is not a camera privilege | 0.8.11: Go live was only ever pressed by the join flow, and only when it published a camera -- a viewer-only join that later shared RTSP or a file was previewing to itself. Adding a source while joined now presses it (once a name exists), and presence (`.since`) carries {peer, op, name} so a member with nothing to publish is still a person in the list. |
| Full quality is a second path, not a bigger composite | 0.8.12: the mosaic stays a 720p signal-first stream; when a viewer wants one feed they get that feed's own broadcast (members keep their moq graphs in mode `both`), listed per cell in the `.grid` announce and hidden as tiles until asked for -- so N feeds cost N+1 encodes on the owner and exactly one download per viewer. |
| A grid cell is a seat, not a queue position | 0.8.12: membership is the set of feeds (entries with a seat), not the set of live slots; a reconnecting feed is a placeholder in its own cell and the order is remembered by url, so nothing on any viewer's stage moves when a camera blinks. |
| Zoom is state, not a transform | 0.8.12: `{s, cx, cy}` per canvas, clamped and re-applied on every layout pass; wheel, drag, buttons and the old cell-expand are all writers of the same state, and the recorder reads it -- one engine for remote tiles and the owner's own composite. |
| Interactions belong to the stage | 0.8.12: cell swap and cell zoom act only on the mainstage pane; in the rail a click means "show me this" and nothing else (a 6 px wobble used to swap cells and eat the click). |
| The app must not depend on a CDN | 0.8.13: the page imported the MoQ library from esm.sh at run time, unpinned -- a new upstream release that esm.sh could not build left every install with a dead gate. The library is mirrored at a pinned version into the app (vendor-moq.py, import map); upgrades are a deliberate re-pin, tested in the rig, never a surprise at launch. |
| A canvas track must say its rate | 0.8.13: `captureStream(0)` reports frameRate 0 and the library's `??` chain keeps 0 -- `configure({framerate:0})`. Every synthetic track KASTR hands the encoder declares a real rate; the guard treats a 0-rate resolved config as "no output". |
| Selection is the stage, not the name | 0.8.13: `selectedName` survives a self-spotlight; the click handler must ask "is this pane on the stage?" before treating a click as a zoom. |
| The launcher writes down what it did | 0.8.13: a --noconsole build printed into the void for eleven releases; launch.log + a print shim, a reachable no-window dialog, hand-off verification and a stall guard replace guessing from process lists. |
| The engine is part of the app | 0.9.0: KASTR's window is a Chromium engine; borrowing the machine's Chrome made a moving target (auto-updates under the app, profile locks, absent on fresh boxes) part of every field report. A pinned Chrome for Testing ships beside the binary with its own profile, and follows the fleet authority exactly like the binary does. The system browser is the fallback, never the plan. |
| A camera is published once, by the machine, not twice by a window | 0.9.1: the browser path decoded and re-encoded every RTSP feed and only worked while the window was open. moq-cli (the relay project's publisher, moq-lite-05, verified against relay 0.14.12 and the vendored web library) takes ffmpeg's MPEG-TS on stdin: copy for H.264, one ffmpeg encode otherwise, audio carried. The page became a monitor and a controller of publish state; supervision moved to Python. The mosaic stays browser-side on purpose -- an ffmpeg xstack over live inputs stalls when any one input stalls. |
| A setting must be reachable from the state it changes | 0.9.2: the feeds-mode control lived only on the composite pane, and the one mode that removes the composite ("Separate feeds") therefore removed the control. Every state a setting can produce must still show the setting: View menu + every feed's menu, plus a hint. |
| Ship what runs, not what came in the box | 0.9.3: the release zip dropped the exec bits on the bundled browser, and the launcher's fallback (the OS default browser) could never run KASTR -- so a permissions slip became "opens in Firefox". Every file the app must execute is listed in one place (`kastr_browser.EXECUTABLES`), the archive marks them, the launcher fixes and verifies them, and a failure names its cause instead of pretending. The same pass pruned the browser to what a window uses and removed the yt-dlp resolver, the browser-side RTSP encoder and the other dead paths: what ships is what runs. |
| A fallback that cannot work is worse than a dialog | 0.9.3: `webbrowser.open()` looked like success (a window appeared) while nothing could run in it. Fallbacks must be able to do the job -- `--no-sandbox`, then a system Chromium -- and the last resort tells the operator the reason and the address. |
| Membership is remembered, not re-derived per announce | 0.9.4: viewers rebuilt "which feeds hide behind this grid" from each geometry announce, so a member that was merely reconnecting (announced as null) or an announce that flickered un-hid the feed's tile and re-laid the stage on every viewer. A relationship that the owner asserted once holds until the owner withdraws it (or the grid is really gone), whatever a single announce says in between. |
| An announce is identified by its content, not its connection | 0.9.4: `keyedAnnouncer.set` always closed the old track-less announce and dialled a new one, so every unchanged re-announce reached viewers as inactive-then-active. The `.grid` announce now re-dials only when payload, relay or room change; the stall report keeps re-dialling on purpose (each report is an event). |
| A monitor is not a publisher | 0.9.4: the page restarted a feed's server-side publisher whenever its local monitor picture ended, withdrawing the broadcast from the relay for nothing -- the server already supervises the publisher with its own ladder. The page now reloads only what it owns (the `<video>`), and the mosaic says "reconnecting" rather than freezing. |
| A monitor that feeds a composite is a source, not a preview | 0.9.5: the mosaic is drawn from the members' monitor `<video>` elements, so their liveness IS the grid's liveness for every viewer -- yet since native publishing nothing watched them (the 0.8.x health rules sat inside a browser-publish branch and went with it). Whatever a published picture is drawn from gets the same health rules as a published stream: keep playing, chase the live edge, reconnect when frozen, and say "reconnecting" rather than show a stale frame. |
| A picture that stops moving is a stall, whatever the bytes say | 0.9.5: the viewer's stall detector counted bytes; a subscription can keep receiving and decode nothing new. Frames are the fact viewers care about, so frames flat while bytes flow re-subscribes locally, and a frozen source (bytes and frames flowing, picture identical) is left to the owner's monitor rules above. |
| A cell is a door, not a magnifier | 0.9.5: zooming the mosaic showed a blown-up composite; the operator wanted the camera. The member's own pane (full-resolution monitor) exists behind every cell, so a click opens it and the stage relation stays visible: click again, or "Grid", to return; losing the stage closes it. |
| Group controls act on the group | 0.9.5: the grid tile is silent by construction and its members carry the audio, so "mute the grid" muted nothing and the mosaic wore a permanent crossed-mic chip. A member is heard through its grid: the grid's mute and slider govern it, and the grid keeps its controls while any member has audio. |
| What a feed carries is the operator's call | 0.9.5: the native publisher always carried the camera's audio. Per feed, by camera address, the operator now decides, and the probe says when there is nothing to decide about. |
| Load is a count of encodes, not a thread | 0.9.6: "make it multithreaded" -- the server already is (ThreadingHTTPServer, a reader thread per monitor, drain threads) and each ffmpeg/x264 uses every core. What starved 4-core boxes at three feeds was two full encodes per non-H.264 camera (publisher + monitor) plus the relay sender. The lever is fewer and cheaper encodes: copy whenever a viewer can decode the camera as-is, and when the monitor must encode, encode only what the mosaic consumes (15 fps, 1280 wide, fastest preset). Measured on the rig: a copied 720p stream costs moq ~0.07 cores; TS vs fMP4 into moq made no meaningful difference (0.071 vs 0.058 cores, ffmpeg's mux cost went the other way), so the container stayed MPEG-TS. |
| Copy whenever the viewer can decode | 0.9.6: the passthrough switch was born as "H.265 only" because H.264 always copied and H.265 was the risk. The real rule is about the viewer, not the codec: pass through whatever the viewers' decoders accept (H.264 and H.265 in MPEG-TS today, size and range included), encode only what nobody could decode (MJPEG, MPEG-4). One function (`passthrough_ok`) decides for the publisher and the monitor alike; the page's `<video>` gets a fallback (`?transcode=1`) for the one case the rule cannot know in advance -- a copy this machine's browser cannot play. |
| Ask before doing the same thing twice | 0.9.6: two entries for one camera address doubled every cost above and gave the relay a second name for the same picture. The Add button now names the existing feed and offers to replace it; test patterns stay repeatable on purpose. |
| A live monitor is a buffer the page owns, not a file it hopes to keep up with | 0.9.7: four real cameras on passthrough, published feeds never restarting, yet every grid cell dropped about once a minute -- the preview `<video src>` on an endless progressive MP4 fell behind, stalled at timestamp gaps, and the 0.9.5 liveness rules did the only thing a progressive player allows: reconnect. Progressive playback cannot seek an unseekable stream; Media Source Extensions can, because the buffer is ours. Gaps are jumped, the live edge is a seek, old media is trimmed, and a reconnect is reserved for a bridge that stopped sending. The rule generalises: when the page must keep a live picture honest, it must own the buffer. |
| A hiccup is not an outage | 0.9.7: a placeholder flashed in a grid cell the instant a monitor reconnected, so a two-second recovery read as a drop to every viewer. The cell keeps its last frame through a short reconnect and says "reconnecting" only when it is really taking a while. |
| Bandwidth savings are the viewer's decision to pay for | 0.9.2: H.265 halves bitrate only where every viewer can decode it in hardware; the browser never falls back to software. So pass-through is opt-in per install, the viewer probes `isConfigSupported` and says out loud when it cannot decode, and H.264 stays the default. |
| Own-pane membership is observed, not inferred | 0.8.5: the publish module appends and removes .pubpane cells but cannot call applyState; for two releases the collage only recomputed when something incidental ran it (the relay echo suppressing our own path, ~5-10s after go-live -- and never at all while merely previewing). Tiles therefore sat in the previous head-count's template, i.e. stacked full-width in a one-column grid. A MutationObserver on #pubPanes (childList -> queueRelayout) makes the own-pane list itself the trigger; #stagewrap's ResizeObserver cannot serve, its box is flex-fixed and does not change when the grid inside it does. |
| A merged grid member is hidden, not just dimmed | 0.8.4: the composite is the view, so a member folded into it gets `.ingrid` (display:none) and drops out of `ownCells`/`pubEls`/`railOwn`. The 0.8.3 `.ghost` (opacity .03) left each member occupying a real collage cell, so the best-fit sized for N members + 1 composite and, on a tall stage, collapsed to `best=1` — the full-width-stacked report. Invariant restored: one collage cell per VISIBLE own source. The publish half can't reach applyState across the module boundary, so `window.__relayout = queueRelayout` is the seam it calls on merge/demerge (renderMine/recomputeMine don't relayout, and #stagewrap's ResizeObserver won't fire on an internal grid change). |
| Relay-only means reachable, or it means nothing | 0.8.4: a relay box exists to serve the LAN, so relay-only mode forces the web bind to 0.0.0.0 (an explicitly-pinned host still wins), forces the moq-relay `lan` bind regardless of the saved checkbox, and ensures firewall rules at startup (check-first, so the one UAC prompt only appears when a rule is actually missing). 0.8.3 booted relay-only to the Relay page but left it on loopback — reachable by nobody, updatable from nobody, which is exactly how a tester's fleet silently failed to update. The update feed is co-located into every app folder at build time (updates/<other-plat> beside the binary; the running platform is served from sys.executable) so any deployed KASTR is a whole-fleet relay with nothing to copy; 0.8.6: the archive INCLUDES that subfolder -- one zip is a complete fleet-serving deployment (distribution beat zip size). |
| The own mic ring taps the capture-output seam | 0.8.4: screen/file slots carry their audio on `audio.in.source` (KASTR sets it), but a camera's mic is library-managed and surfaces on `sources.audio.out.source` — the same capture-output signal the RTSP video path uses. armSlotAudio probes both, so the own preview's talking ring arms for cameras too. It never did before because the rig can't open a camera; every own-audio test used a file, and the file path happened to be the one wired. |
| The RTSP grid is a slot-shaped object over a canvas | 0.8.3: the mosaic composite reuses every slot mechanism instead of growing parallel ones — rebuildRtspMoq builds AND heals its moq graph (it only needs {entry, moq.track, liveSince, fault}), refreshUi paints its badge with the same echo test, and it rides mySources() so the watch half suppresses its announce like any own path (without that it came back as a phantom tile and the echo never proved delivery — observed in the rig). Members hand back only their four graph objects; their capture tracks stay, so demerging is the 0.8.2 rebuild, verified live. |
| Auto encoding is signal-first | 0.8.3: with everything on Auto the encoder used to match the source — a 4K camera meant a 4K encode nobody asked for. Auto now caps 1080p/1200kbps ("a signal making it across rather than quality"); explicit choices override; the Negotiated line names hardware/software so the question "is HW on?" has a place to be answered. Linux gets VA-API launch flags — prefer-hardware probes cannot succeed against a browser that shipped the feature off. |
| The stage moves only toward content, once | 0.8.3: auto-spotlight acts on ARRIVAL events only (newest !== autoContent), and even then yields when live shared content already holds the stage — a second share must never yank the first. Cameras are never an auto-spotlight target; removeTile's survivor pick prefers content in spot mode so a dying share falls to its sibling, not to whichever camera sorted first. |
| The updater's every outcome is written down | 0.8.3: check_update ran before the console existed and failed silently — a field tester's box simply "didn't update" (root cause: the authority's web port was unreachable). Every branch now writes update-check.json (status + detail + timestamp); /api/instance carries it; the Relay page renders it red when the authority is unreachable and names the ops fix (KASTR running, host 0.0.0.0, the "KASTR web" rule). |
| The relay you used last is the relay you get | 0.8.3: /api/relay/use persists relay-use.json beside the other state; the launcher resolves explicit --relay > last-used > kastr.ini > built-in. The ini stays what it always was — the shipped default — while the human's last choice survives relaunch. History is client-side (localStorage MRU) because suggestions belong to the person, not the install. |
| Explicit mute is volume 0, exactly | 0.8.2: the library's documented edge — exactly 0 tears the audio subscription down; anything below .001 is *supposed* to hard-zero the gain, but that guarantee lives in an unpinned esm.sh library and the field said "muted but audible". desiredVolume returns 0 for manualMute/mutedStreams; the warm floor is only for silent-but-warm. Person-wide mute exists because audioMode "all" keeps a person's OTHER streams audible — muting a tile was never muting the person. |
| RTSP slots obey the same relay truth | 0.8.2: an RTSP slot's ON AIR came from its own enabled signal — the one publish path with no echo test and no heal, so a wedged moq connection stayed silently "live" forever. slot.liveSince (stamped at go-live and at birth-while-live) + the 8s __echoed test badge it honestly; the 5s heal rebuilds the moq graph (connection/broadcast/capture/encoder) around the SAME capture track — ffmpeg and the <video> are healthy by definition when only the echo is missing. |
| The rail pages; it never shrinks below legibility | 0.8.2: capacity = rendered rows × columns (min 4 rows exist — the mainstage span needs height), pages = ceil(cells/capacity); paged-out panes are display:none + visible="never" (no pixels, no download) while audio stays volume-driven — paging must never change what you HEAR. Width is user-owned (drag grip, kastr.rail.w, 2 columns past ~300px); grid placement is explicit (col/row per cell) because column 1 is spanned by the mainstage. |
| Chimes are generated, person-keyed, and skeptical | 0.8.2: WebAudio synthesis (no asset, no fetch); keyed by personKeyOf so multi-stream people chime once (first tile in / last out); debounced 3s against announce flaps; silent during the 4s post-connect flood, when connection is null (leave sweeps are not departures), and under master mute. A chime is a claim someone ARRIVED — every guard exists because announces flap. |
| Blur rides the screen path's track seam | 0.8.2: capture.in.source IS where every video track lands, so the segmented composite injects there and everything downstream (encoder, catalog, preview, announce) is untouched; the raw track keeps flowing underneath, and a device switch is just a new raw track observed on the same signal (re-aim, re-inject). MediaPipe is vendored under assets/mediapipe — the LAN owes nothing to a CDN. Toggle rides sendControl like every other camera lever. |
| Presence UI includes the operator | 0.8.2: own paths never become tiles (suppression), so People/count derived from tiles alone showed a room without YOU in it. The "(you)" group feeds from minePeers' local sources and the count unions myPersonKey — keyed by operator, so your remote copy still merges to one person. |
| Check before prompting for privilege | 0.8.2: GET /api/relay/firewall reports rule presence (one PowerShell pass / ufw status) and the page offers the elevation button only when rules are missing — an "add rules" button on a configured box reads as a broken box. The check covers all FOUR names including "KASTR web" (the button added a rule the old hint never printed). |
| Relay-only is a mode, not a binary | 0.8.2: `mode = relay` / --relay-only forces page=/relay.html?solo=1 + relay autostart in the SAME executable — a second binary would fork the fleet updater's version authority. ?solo=1 just swaps the masthead nav for a "relay-only machine" tag: the capability is hidden, not removed. |
| The relay's name is its stats node | 0.8.2: relay-name.json (slugged, ≤32) feeds [stats] node with host_slug as fallback — humans name hubs and spokes ("garage"), and spoke attribution falls out free: a path with open announces in node X's subscriber.json originated at X, which is how the hub's streams panel labels "· via garage" with no new protocol. LAN URLs list before 127.0.0.1 — loopback never travels. |
| Autorun is per-user, no elevation | 0.8.2: HKCU Run / ~/.config/autostart — the two registration points that need no admin and unwind cleanly (delete the value/file). Frozen builds only: registering a dev checkout's python process would be a lie. Loopback-guarded POST like every other machine-state endpoint. |
| Speaker + audio ring are meter-fed | The per-tile analyser already computes RMS for the meters; `talking` is a thresholded hold on it and the speaker is the loudest EMA with 1.5 s stickiness — page-side, no protocol. Meters pause in hidden tabs, so the ring freezes there (production windows are visible). |
| Room switch = stop-announce, re-aim, re-announce | Moving rooms clicks the live toggle off, joins the new room (discovery + registry re-aimed), and clicks it back on — the go-live loop re-stamps every slot name through chanPath() under the new room. Devices never release; old-room viewers lose the feed by definition. |
| Cross-document popover collapse rides blur | A click inside an iframe never bubbles to the popover's document, but it always moves focus; window blur is the one signal that crosses the boundary, so both the brand popovers and the page popovers close on it. |
| “Rooms” is UI wording only | localStorage keys (kastr.channel…) and the `.channels/` relay prefix keep their names — renaming them would orphan stored state and break wire compat for nothing a user can see. |
| Output routing is per-tile setSinkId | Every tile's audio rides its own AudioContext (watch.audio.out.context); the sink is applied wherever a context first appears (attachMeter) and re-applied to all on change. "" follows the OS default. |
| The masthead badge owns relay changes | Server first (POST /api/relay/use — owns the value every future page load gets), then a live `__kastrSetRelay` fan-out to open pages (shared-field change event carries it into the publish half: slots + registry follow). |
| Channels are path prefixes, Scheme B | Internal names stay `HOST/op/leaf.hang`; the channel is prepended only at the five relay-commit boundaries, and discovery joins with `PREFIX = channel`. Labels parse right-anchored (leaf = last, operator = second-to-last), so 3- and 4-segment names read the same. Legacy channel-less publishers are invisible to channel-scoped pages — accepted. |
| Channel registry is announce-only and advisory | `.channels/<slug>` (or `.../locked/<salt>/<hash>`) is a track-less Broadcast held while joined — bundle-verified that announcement depends on the published path alone. The password is a client-side gate; v0.7 JWT makes it real. The list empties when unoccupied; `kastr.channels.mine` re-establishes a creator's lock. |
| Join gate owns connect() | No watching before joining: every connect() caller is refused until the gate has published this machine's presence (camera joins muted+paused). Leave is a full stop — a hot camera after Leave is a surprise nobody wants. |
| Relay health from the library's own status signal | `Connection.Reload.status` (disconnected/connecting/connected) feeds `__relayHealth`; the badge owns the 15 s red timer. A Reload that dies fatally while the relay is down never redials — the probe is rebuilt on observed death (a reconnect, not a watchdog: the fact is a dead connection, never idleness). |
| One page, two module scripts | The 0.6.6 merge ports the publish core into the watch page as a SECOND `<script type=module>`: module scope keeps `urlInput`/`log`/`stageEl`/`$` from colliding, and an eval failure there degrades the page to watch-only instead of killing it. |
| Local self-view is the live pane, not a thumbnail | The slot's own preview canvas/video renders in `#pubPanes` inside “My streams” — full framerate, zero IPC. The strip is never display:none'd while slots run: captureStream stalls to ~0.24 fps unpainted, so file/RTSP sources must stay painted (the shell's opacity-0.004 background compositing covers hidden tabs). webp thumbs remain for OTHER windows only. |
| Legacy publish page byte-frozen | The fallback must stay exactly the shipped, known-good page while the merge proves itself; it interoperates over the sources channel like any other window and is removed in a later release. |
| Own tiles suppressed via announce identity, fail-open | Watching yourself through the relay pays twice; the channel says which paths are ours. No channel means no suppression — v0.6.4 behaviour. A suppressed-set resurrects tiles when the owning view dies (announced() never re-delivers an active entry). |
| Self-view previews over the channel, never the relay | A selfview document owns no sources (“a stream cannot be decoded twice”); the publishing view paints its own slots into leased webp blobs instead. |
| Camera switch never renames | Renaming a live broadcast republishes and drops every viewer; the row keeps the original device's label, cosmetic staleness accepted. |
| Mic menu is peer-level | The publish page has one machine-wide mic binding shared by every slot; a per-row mic menu would lie. |
| Badge follows repoints by polling `/api/instance` | Serve-time substitution freezes the relay per document, and the shell's top document loads once per launch — no reload ever refreshes it. |
| `entry.micMuted` mirrors `videoPaused` | `startSlot` and the mic-target handler recompute `muted` wholesale; a bare write would silently revert. |
| Control commands addressed by `(peer, id)` | Entry ids are peer-local; mirrors the remote `stop`. Every publish view receives every message and only `target === PEER` acts. |
| Pause-video rides the library's `invisible`, never track surgery | It is the element's own enable gate: the camera is released, the mic leg untouched, and the catalog updates live. Anything hand-rolled would fight the element's source management. |
| Audio-only starve exemption keyed on the catalog, `=== false` | Audio-only tiles legally receive zero video bytes forever (the old check posted a false report every 30 s); a catalog that never arrives still reports, preserving the relay black-hole coverage. |
| Tile sizes as inline spans over fine tracks, dense flow | `style.order` reordering survives unchanged; dense backfill was chosen over holes, accepting that exact manual order is approximate around big tiles. |
| matchRendition writes `target` via `update()` | The element's own ResizeObserver and bandwidth probe share that signal; `set({name})` wiped their width/height/bitrate and disabled the library's picker. |
| Watch tiles park via the `url` attribute | Each element owns a QUIC connection + catalog even hidden; removing the attribute is a library-supported round-trip to zero network, while removing the element from the DOM is the teardown that broke audio. |
| RTSP live-edge kept by playbackRate + drift, never seeks | The bridge stream is unseekable (no Range support; `seekable` is [0,0] — a seek clamps to 0 and wedges playback), and Chrome's ~2 s readahead hides the real backlog from `buffered`, so wall-vs-media drift is the only true lag signal. |
| Freeze restarts observe facts, not silence | Frozen playhead / media error / stuck keyframe gate are directly observed broken states; the 0.5.28 watchdogs guessed from idleness and restarted healthy streams. |
| 15 s send timeout in `handle_stream` | A reader that stops consuming blocked the pump forever and wedged ffmpeg; ffmpeg's `-timeout` cannot fire while blocked writing to the pipe. |
| Teardown exits from `finally` | A flush on the windowed build's `None` stdout once threw *between* cleanup and exit, leaving a zombie holding the port. |

## Known limitations & risks

- **RTSP audio is not published** (never was; now explicit at the bridge).
- **macOS binary** is unbuilt/unverified — `build.py` supports it, no Mac here.
- **esm.sh imports are unpinned**: a library release can change behaviour per
  browser profile cache. Vendored copies exist in `assets/` but are not what
  the pages load. Pinning is recommended future work.
- **Shared relay state**: a long-lived relay accumulated a path that black-holed
  subscriptions once; restart clears it. KASTR reports starvation but no longer
  tries to route around relay faults.
- **OneDrive/antivirus** intermittently locks the exe during builds
  (PE-checksum retries succeed); excluding the folder from sync/scanning is
  advised.

### 0.9.8

- **A child must not outlive its parent.** The publisher pairs were plain
  children: nothing bound their lifetime to KASTR, so a hard kill left the
  operator's cameras on the relay as tiles nobody owned. The OS now holds the
  leash (a Job Object on Windows) and a registry on disk lets the next start
  reap what a dead run left behind -- matched by executable and start time,
  never by PID alone.
- **What the server runs is yours.** A page is a view of the bridge, not its
  memory. After a reload it asks the bridge what it publishes and adopts it,
  and the bridge answers a matching publish request with the running pair
  instead of a restart. A reload no longer costs viewers a frame.
- **The picture's shape is the decoder's, not the catalog's.** A copied
  anamorphic stream advertises its coded size; viewers stretched frames into it.
  The publisher converts such cameras (resampled to square pixels at the display
  width -- relabelling the SAR alone keeps the squeeze), and the
  viewer trusts the decoded frame's own shape over the catalog when they
  disagree.
- **Fill first, then centre.** The auto grid packs rows of different cell
  counts when that shows more picture, keeps every cell at least half the
  biggest, and centres what is left. Both halves of the page compute the same
  rectangles from the same text -- a hit-test that disagrees with the draw is a
  camera opened by mistake.
- **Repo location / archive.** `C:\Users\KentonJeffery\Claude\KASTR` (out of
  OneDrive); `dist/archive/v<ver>/KASTR-<plat>-v<ver>.zip`, latest version only.

### 0.9.9

- **A transform belongs to the box it renders into.** The 0.9.8 shape fix was
  right about the picture and wrong about time: it drew once and let the pane
  move underneath. Every path that resizes a pane or a cell now re-applies the
  corrected canvases along with the zoomed ones. (Field data: two South Ridge
  4K cameras announce 3840×3840 while decoding 3840×2160 -- the catalog can lie;
  the decoder cannot.)

### 0.9.10

- **A seat is a promise about the roster, not about the moment.** Membership was
  re-derived from whatever happened to be decoding, so every restart forgot the
  arrangement. The roster (seats) and the arrangement (order) are remembered by
  URL, the order is merged rather than rewritten, and a moment with fewer than two
  feeds is not a decision.
- **Absence is not a choice — store both states.** A map that stores only "off"
  cannot tell "on" from "never asked", so the default could never change. Both
  values are stored; the default is off.
- **Sweep by what a helper is, not by who wrote it down.** The registry reaps
  what a 0.9.8+ run recorded; the legacy sweep reaps any bundled helper whose
  parent is no longer a live KASTR. Two independent rules, one outcome: nothing
  outlives the app.
- **A device that only publishes should not pay to watch.** Subscribing is the
  expensive half of a room; publish-only reads the announces (presence, grid
  metadata, stall nudges) and skips the tiles.

### 0.10.0

- **The credential decides the role, the room decides the path.** A room code
  answered "may you enter this room?" and, on a secured relay, silently also
  "may you publish?" — and only for rooms somebody had registered since the last
  restart. Two relay-wide codes now answer the first question for every room
  (main included) and the role question at the same time: the publisher token
  scopes `put`+`get` to the room, the viewer token scopes `get` to the room and
  `put` to the presence-class kinds only. Room codes stay what they were — a
  lock on one room — but never a substitute for the relay's own door.
- **Measured relay claim semantics (2026-09-18, bundled moq-relay 0.14.12 + the
  `moq` CLI, subscriber-verified):** the token's claims are exactly `root put get
  exp iat`; `put`/`get` accept a string **or an array**; matching is per path
  segment (`put:"main/."` covers nothing under `main/.since/…`, `put:"main/.since"`
  covers `main/.since/1/x`); a token with no `put` is severed at connect ("token
  does not grant publisher access"); an announce outside the `put` scope is
  dropped silently and the session stays up (no reconnect storm); `get:"main"`
  receives `main/h/op/x.hang`. Hence one viewer token per room instead of a token
  per announce kind, and the page still refrains from announces it has no claim
  on so nothing depends on the drop being silent.
- **A control plane belongs to the machine that owns the relay.** `/api/relay/*`
  writes answered any client that could reach the web port — a remote page could
  stop a secured relay and restart it open. Host, peer and Origin must all be
  loopback now (Origin because `do_OPTIONS` answers every preflight with `*`);
  reads stay open because the Relay page's status is harmless and useful.
- **Persist what the credential check depends on.** The room table was in-memory
  "because holders re-register on a heartbeat" — true, and exactly the window in
  which an unregistered room minted for free. Codes and rooms live in
  `relay-auth.json`; a room ages out after a day without its heartbeat instead of
  living forever now that it is on disk.
- **Wrong guesses cost time, not CPU.** PBKDF2 makes a stolen file slow to crack;
  the per-IP lockout (5/min → 30 s doubling to 10 min) makes the live minter slow
  to guess against and bounds the PBKDF2 cost an attacker can impose.
- **A checkbox that cannot show its state is a footgun.** The bind-all box did
  four real things and painted none of them back, so the page's own Stop/Start
  and the autostart box quietly undid an operator's LAN choice. Every relay
  control now reads the running (or remembered) shape, and starting the relay
  remembers the shape it used.
- **Occupancy counts people, not publishers (revisited).** 0.8.11 made viewers
  announce presence; the room list still counted `*.hang` operators only. The
  list now unions publishers with `.since` announcers, so a room full of viewers
  is not "empty".
- **The switcher sits where the room is named.** The chip already said "Room:
  main · 3"; making it the door removes an unlabelled ☰ from the path (the ☰
  stays as a second door). Anchor-aware placement instead of a second menu.

### 0.11.0

- **A relay's credential comes from the relay it dials.** HS256 is symmetric, so the
  hub must sign the spoke's token; the hub mints it from a federation code the
  spoke presents. No key is ever copied between machines, rotation on the hub
  invalidates every spoke at once, and each spoke heals itself (watchdog: kid or
  expiry → re-mint → restart). Verified on 0.14.18: `{root:"", put:"", get:""}` is
  accepted, traffic crosses both ways, a wrong code is refused at the hub.
- **Attribution is declared, not inferred.** `subscriber.json` measures where an
  announce ENTERED a node; in a cluster that is every node it crossed, so "first
  node listing the path" is a race. The member says which relay it dialled in its
  presence; the stats guess stays only as a fallback. (Corrects the 0.8.2 premise
  recorded above under "Relay attribution".)
- **The master is the hub.** Clients matched their relay host's version at launch;
  relay hosts had nobody to match. A spoke's KASTR follows the hub's KASTR (launch +
  hourly), so one machine is the fleet's update point without a new service.
- **A room that exists must be visible to be joinable.** Persisting rooms (0.10.0)
  made an empty locked room a hidden landmine for "New room…". The minter lists
  what it remembers, the gate registers before it mints, and a publisher can
  re-key — every failure is shown, none is silent.
- **Launch lands on the gate.** Auto-joining the last room saved a click and cost
  every wrong-code surprise at startup; preselecting it and prefilling the codes
  keeps the click cheap and the choice explicit.
- **Rooms are a strip, not a menu.** The always-visible bubbles make "what rooms
  exist and who is where" a glance; the ☰ is the detail view. A public
  `.presence` prefix is what lets the strip count people on a secured relay.

### 0.12.0

- **A live process is not a live session.** `ffmpeg | moq` reported `running: true`
  while the relay refused every reconnect; then moq exited and the ladder brought the
  same dead token back. The observed fact is the refusal line on stderr, not the
  process state: a hard refusal parks the publisher, a fresh token unparks it, and a
  plain outage still ladders. Measured on moq 0.11.2: `session severed immediately …
  reason=unauthorized` every 1–5 s, exit after the 10 s backoff timeout; a clean relay
  bounce is one `session closed, reconnecting` and a silent reconnect after the QUIC
  idle timeout (now 15 s).
- **The token that was just refused must not be retried.** The reuse path used to
  refresh the URL for "the ladder's next start"; with a page joined that worked by
  accident, without one it never happened. The minter is asked from the server side
  (rate-limited), and the page's re-mint restarts a parked pair immediately — while a
  healthy pair is left alone whatever token a reload brings.
- **What the machine publishes, the machine remembers.** The page's localStorage was
  the only memory of "which cameras, which room, which codes"; a relaunch with no page
  joined had nothing. `rtsp-feeds.json` is written on operator intents and read at
  launch, so a fleet relaunch republishes before any window opens.
- **Rooms are a subscription, not a scan.** A periodic scan on a fresh connection is a
  race against the WAN; a permanent consumer with grace and a frozen state while
  disconnected is not. The list can dim, it can never blink.
- **The current room is a banner, the others are a list.** (Supersedes "Rooms are a
  strip, not a menu".) You need your own room's facts at a glance — people, time,
  lock, role — and the other rooms as a navigable list with members and who is
  speaking, above the join gate so the choice is informed before it is made.
- **Speaking is a toggle on one connection, not a re-dial per utterance.** The
  broadcast's `enabled` signal closes and re-creates the announce; two loud ticks on,
  two quiet seconds off. The payload names a peer, and peers resolve to operators
  through presence, so an icon can only be lit by the page that owns the mic.
- **Chat history is a file on the hub, delivery is a pulse.** MoQ carries the "there is
  something new" signal; HTTP carries the bytes and the history a late joiner needs. A
  spoke's KASTR forwards to the hub's with the relay-to-relay token it already holds,
  so one federation has one history per room name.
- **The store decides a room is closed, an announce only hints.** Any member could
  broadcast `closed`; only the room store (creator's roomKey or the operator) deletes
  a record. Members check the store when hinted and compare the tombstone to their own
  join time; a publisher box is never taken off the air by a remote signal.
- **Modes are the operator's declaration; absent means full.** A camera box, a viewer
  kiosk and a relay box need different chrome and different launch behaviour, and no
  default may turn a laptop into a publisher. The publisher modes' auto-join is the one
  exception to "launch lands on the gate": nobody is at that keyboard.
- **An occupancy timer belongs to every room.** "main is always on" was a shortcut;
  the timer starts when the first member arrives and stops when the last leaves,
  computed from presence timestamps that keep their original join time across re-dials.

### 0.13.0

- **State is a value, not a path.** Announce paths carried state for five releases because
  the relay retains announces and a track-less broadcast is cheap; the costs were a dial
  per change, no "latest value" for a late joiner beyond what is announced, payload bound
  by path length, and any member able to write any path. A JSON track per member has a
  readable latest value, changes are groups on one connection, and the writer is the only
  one whose token covers the path. Measured on the rig (moq-relay 0.14.18, @moq/net 0.3.5,
  @moq/json 0.3.3), all in the Step-0 file that fed this release:
  - the PRODUCER prunes closed groups older than `latencyMax` (5 s by default) on every
    append and on every new consumer attach, and the relay's own cache did not outlive
    1–2 minutes without a reader; a once-written track was unreadable minutes later. State
    tracks keep 60 s and a 20 s heartbeat rewrites them, so ≤ 3 small groups are replayed
    to a late subscriber and a relay restart is covered by the rewrite on reconnect;
  - a fresh subscriber receives the relay's cached latest group FIRST and then the live one:
    consumers must keep reading and apply every value in order;
  - a live subscriber is not moved onto a resumed broadcast ("remote error: 24" ~2 s after
    the producer's connection drops, even inside the relay's linger); consumers re-consume
    with backoff while the announce stays active;
  - group sequences restart at 0 with every new `Track.Producer`, and a relay that resumed
    the same path keeps its subscribers, who then drop every group below the old high-water
    mark — values silently vanished until the heartbeat passed it. Seeding each track with
    an empty closed group at a wall-clock sequence (`Date.now() − 1.79e12`) makes every
    generation monotonic; consumers skip an empty group;
  - a `Window` (chat) is legitimately empty until someone posts, so it gets no first-value
    or staleness timer (a first attempt re-subscribed every 8 s and churned the relay);
  - `/fetch/<path>/<track>` returned an empty chunked body and refused a jwt on a public
    path — previews ride the subscribe pool, not `/fetch`;
  - claims match per path segment: `"r1/hosta-1234"` covers `r1/hosta-1234/…`, not
    `r1/hosta-12345`; a trailing slash is also accepted; out-of-scope announces are
    dropped silently (0 bytes at any subscriber);
  - an idle native publisher into a spoke costs 0 bytes on the cluster link: the relay
    subscribes upstream on demand ("subscribe canceled (idle)" as soon as the last reader
    leaves), so an idle publisher-relay box burns announces and `.stats` only.
- **The minter cannot authenticate a machine, but it can scope it.** There is no PKI on a
  LAN relay; what a `host`-scoped token buys is that a member can only write under the host
  it named, so nobody clobbers another member's paths by accident, and a leaked viewer
  token writes four narrow prefixes instead of a room-wide list. A page without a
  substituted hostname takes the wide 0.12 token, logged once.
- **Chat delivery must ride the port a client is guaranteed to reach.** The relay port is
  the one thing every member has; the hub's web port was unreachable from the field while
  chat looked dead. Live delivery on each member's `chat.json`, history on the hub's store,
  and an honest "not saved" mark when the store did not answer — never a private empty
  store on the laptop's own origin (a laptop has no cluster link to forward to).
- **A test write that a control loop overwrites 180 ms later is not a lost write.** The
  first rig runs "lost" every `speaking` flip because the page's own speaking detector wrote
  `false` right after; the relay's debug log showed every group served. Rig facts are read
  from the relay log, not inferred from the page.
- **Only the room registry stays an announce.** `.channels/<slug>` is held by every member
  and kept as a 5-minute ember by a page that has already left; its lifetime is decoupled
  from any member on purpose — the opposite of a state track that dies with its publisher.

### 0.13.1

- **The rail is the server list; the banner is a label.** Discord's shape: every room in one
  left column, the one you are in marked in place, nothing about it repeated elsewhere. The
  banner keeps the name (and the facts on hover) because the top bar still needs to say where
  you are when the rail is collapsed to bubbles.
- **Order is the operator's, not the machine's.** Two people share a laptop; the rooms one of
  them drags to the top are noise to the other. The saved order is keyed by the operator slug,
  `main` never moves, and rooms nobody has placed stay alphabetical so a new room appears where
  you expect it.
- **Live pixels only for the room you are in.** The 0.13.0 thumbnails were a live view of every
  room — a 2 s WebP from every publisher, pulled by every lobby. Kenton measured the cost before
  the feature was a day old; it is gone entirely (producer and pool), not merely hidden.
- **Noise removal is a vendored model, not a hand gate.** A band-pass plus an adaptive gate
  cannot separate speech from a fan; RNNoise can (−54 dB on white noise, 0.1 dB on a voice-shaped
  tone on the rig). It runs where the microphone is, from files served by KASTR itself (the page
  is cross-origin isolated and loads nothing from a CDN), and when it cannot run the operator is
  told and the mode changes — a control that looks on while nothing happens is worse than none.
  Chrome's `voiceIsolation` is offered only after the device reported it back, for the same reason.
- **A meter shows input, not the floor.** Sixteen segments lit by a fan tell you nothing; the
  meter tracks the floor and lights only what rises above it, and after three silent seconds it
  says so in words.
- **A relaunch must know it is one.** The child of a mode switch found the parent still on the
  port, recognised its own build and did the polite thing — handed the window over and quit. The
  child now waits for the parent to die before it decides anything, and only a real update carries
  `KASTR_UPDATED` (its 10 s profile wait and sweeps were never meant for a mode switch).
- **A restart needs evidence.** The page's echo set is bookkeeping; the relay's announced list is
  the fact. A publisher restart on a lost echo without asking the relay was a "random drop" waiting
  to happen, and a restart nobody logged was unattributable. Every nudge now says why on the box,
  and the no-echo heal restarts only when the relay itself has stopped listing the path twice.
- **One Linux artifact.** The Docker image carries the same `dist/linux/KASTR` the fleet feed
  serves, so a container reports the same sha256 as a bare box and updates from the same feed. Its
  base is Ubuntu 26.04 because that is the glibc the WSL build links against.
- **A Mac client swaps its executable, not its bundle.** The feed serves the file inside
  `KASTR.app/Contents/MacOS/`, `update_from` replaces exactly that (it is `sys.executable`) and
  re-signs it ad hoc; the bundle around it never changes.

### 0.13.2

- **An ffmpeg option is validated only after the input opens.** The 0.13.1 rig check ran the new
  RTSP flags against a refused connection and saw the connection error, never the option error;
  every real camera rejected `-rw_timeout` on the first open and the ladder restarted the pair
  forever. Flags that touch a demuxer are tested against a source that answers (the lavfi test
  pattern published through the bridge, or a live camera), and the field diagnostics from 0.13.1
  (`lastExit`, the kept stderr) are what made the fault a one-line read.
- **"No minter" four seconds after our own relay started is not "open".** The token service binds
  a moment after the relay; a restore that races it dials bare into a secured relay and parks every
  pair. While the hosted relay says it is secured, the only answers that count are a token or a
  refusal.

### 0.13.3

- **Arrival order is not a contract.** The 0.9.4 rule ("the grid announce must reach viewers before the
  members' own broadcasts") was a property of announce ordering; moving geometry onto a subscribed state
  track in 0.13.0 quietly dropped it, and the first `applyState` chose a child it could not yet recognise.
  Re-announcing `.grid` cannot bring the order back (the identity-scoped token has no claim on
  `<room>/.grid`; the relay drops the announce without a word), so the viewer stopped trusting order:
  an automatic pick that turns out to be a grid child is handed back to the grid whenever geometry lands.
- **A remembered click is not a standing order.** `room.json` re-serves a spotlight forever; a viewer
  applies a winner once, so a ten-minute-old click still yanked every joiner's stage. Age it out, and read
  a spotlight on a grid child as the grid.
- **A viewer's starvation is a symptom, not an order.** The viewer-stall path restarted a native pair on
  any report; two silent cameras therefore restarted once a minute forever, and every hub dark spell
  restarted the healthy ones. The owner now checks its own evidence first — the relay's list and the
  pair's counters — and leaves a live pair alone. Read from the relay's `.stats` announce counters
  (public, cluster-wide): per-path `announced` climbing in steps is the fleet-wide restart monitor.
- **Counters must survive their own reset.** `restarts` forgets after sixty healthy seconds by design; a
  seventy-second cadence read as healthy. `restartsTotal`, `gen` and the per-generation launch.log lines
  are the record that does not forget.

### 0.14.0

- **The port is part of the app's identity.** Browser storage is keyed by `scheme://host:PORT`; an OS-picked
  port is a new identity every launch. A launcher that cannot have its port must still have *a* port it
  can keep -- remembered on disk, chosen deterministically, explicit config winning.
- **A setting that must outlive the browser profile lives on the server.** `operator.json` was the first
  such rescue (0.8.0); `prefs.json` generalises it for the page's whole whitelist, with the page seeding an
  empty origin from it. The codes stay out: what the server hands back over a GET is never a credential.
- **A grid member is present, tolerated-down, or evicted.** Sticky membership (0.9.4) was right for blips
  and wrong for a camera that is gone; the bridge's consecutive-restart counter is the honest line between
  the two, the seat memory is what makes the return seamless, and the viewer must follow the owner's
  geometry rather than remember every path it ever saw.
- **Nobody assumes 8000 any more.** The web port is a setting the operator owns (pinned from the Relay page,
  remembered on disk) and a fact the network learns (the token service every client and spoke already calls
  advertises it). Defaults are for first launch, not for identity.
- **A transcode is a stream, not a file.** ffmpeg writing to a pipe with `-copyts` gives the page real
  timestamps from any `-ss`, so playback controls stay honest without offset arithmetic; the reader's
  buffer is the throttle (a paused player stops reading and ffmpeg idles), and every child is owned
  (killed on stop, page close, DELETE, and reaped after a crash).

### 0.15.0

- **A port is a fact the network learns, before anything uses it.** 0.14.0 made the web port a setting; 0.15.0 makes
  every consumer ask for it first -- the launcher before its update check, the page before its first chat URL, the
  spoke before it proxies -- and remembers the answer per host. Literals are for the first probe only.
- **A relay box is a distribution point, so it carries the whole distribution.** Updating only your own binary while
  serving others' from install time is a silent version split; mirror what you serve.
- **A room's grouping belongs to the relay; its order belongs to you.** Groups are shared truth managed by the operator
  or creator; collapse state and order stay per user.
- **A grid is a set of feeds, not a singleton.** The viewer never assumed one grid per owner; the publisher did. Grid 1
  keeps its name so nothing in the field changes; new grids get stable ids, never their labels, as paths.
- **A toast is an interruption -- earn it.** Levels at the call sites, one policy in the primitive, and progress is a
  status line, not a notification.
- **What the camera menu shows must be what the pipeline runs.** The effect is pushed from one place whenever a camera
  appears, and the menu reads the source, not a singleton.

### 0.15.1

- **Count the encoders.** A shared file passed through two: ffmpeg on the server and WebCodecs in the page. Fixing the
  cushion made the first one invisible and left the second -- software VP9 -- as the stutter. Prefer the codec every
  machine encodes and decodes in hardware, and let the debug hook name the encoder actually in use.
