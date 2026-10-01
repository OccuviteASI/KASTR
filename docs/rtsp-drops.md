# Diagnosing an RTSP feed that "drops"

A native camera feed is an `ffmpeg | moq` pair supervised by KASTR. Every path that can restart
or kill that pair is attributable since 0.13.1. When a feed drops, collect three things on the
camera box and, if a viewer saw it, one on the viewer:

1. **On the box** (PowerShell, next to the running KASTR):

   ```bash
   .\KASTR.exe --diagnose drop.txt
   ```

   `drop.txt` has one `rtsp publish` line per feed:
   `running restarts sessionFails sessionKills nudges=viewer:N/noEcho:N/api:N lastNudgeWhy lastExit=<who> code <c> after <lived> s parked lastSession gen=N total=N since=…`,
   plus `instance`, `viewing` (feeds pulled by pages on this box) and `chatHub`.

2. **The launcher log**: `%LOCALAPPDATA%\ASI\KASTR\launch.log` (Linux: `~/.local/share/ASI/KASTR/launch.log`,
   Docker: `/data/state/launch.log`). Look for `rtsp nudge <broadcast> why=... restarts=... sessionFails=... sessionKills=...`
   and the `rtsp restore` / `relaunching` lines around the time of the drop.

3. **`/api/rtsp/list`** from the box itself (loopback only): `curl http://127.0.0.1:8000/api/rtsp/list`.

4. **On the viewer** that saw the drop: View › Log, copy the lines around the time (stall reports say
   "reported ... stalled"; hidden-tab teardown says "Hidden for 60 s").

Since 0.13.3 the launch.log also carries one line per pair generation: `rtsp pair <broadcast> gen=N start …` and
`… exit who= code= lived= restarts= sessionFails= sessionKills= last=<last stderr line>` — the timeline of every drop.
`restarts` forgets after 60 healthy seconds; `restartsTotal` and `gen` do not. `--diagnose` no longer needs `--port`.

## The grid (0.21.5)

The RTSP grid is composited and encoded in the owner's own page, so until 0.21.5 nothing about it reached launch.log
and `/api/diag` listed only the individual camera slots. Now:

- **launch.log** carries `page: grid <name>: …` lines (loopback `/api/rtsp/note`, at most one per two seconds per grid):
  `built 1280x720 layout=auto`, `relayout n=..|..|WxH`, `viewer stall ignored — grid live here (enc advancing, connected,
  echoed=true, reports=N)`, `rebuild reason=viewer-stall/<encFlat|disconnected|relay-unlisted|no-evidence> (…)`,
  `rebuild reason=no-echo (…)`, `rebuild reason=token-refresh`, `evicted <camera> (monitor attempt 6)`, `readmitted <camera>`,
  `torn down`.
- **`/api/diag`** → `publisher.grids[]`: `members`, `evicted`, `layout`, `canvas`, `liveS`, `connected`, `announcing`,
  `encoded` (the encoder's own frame count), `encFlatS` (seconds since the counter last moved), `lastRebuild {at, why}`,
  `stallReports {n, lastAt}` and the last twelve events.

Reading it: a grid that remote viewers see going black every ~45 s while the box shows it live was, before 0.21.5, being
rebuilt on every viewer stall report; after 0.21.5 the same reports show as `viewer stall ignored — grid live here` and
`stallReports.n` climbs while `lastRebuild` stays old. A `rebuild reason=viewer-stall/encFlat` means the owner's encoder
really stopped; `…/disconnected` means the owner's relay connection dropped — look at the relay log and the federation
lines next.

## The cluster link (0.21.7)

A spoke's grid that remote viewers lose while the spoke's own page shows it live points at the link between the relays.
Since 0.21.7 the spoke reads its relay's log for that link and writes:

- **launch.log** `relay federation: cluster link to <hub> up (… connected peer=…)` / `… down (… cluster peer error …)`,
  one line per transition, plus `relay federation: hub relayed a viewer's demand for <camera> -> woken here | not
  registered here` when a viewer elsewhere opens an on-demand camera (only with `ondemand = on` since 0.21.10), and `relay federation: hub unreachable -- keeping
  the stored certificate pin (no restart)` once per hub outage.
- **`/api/relay/status`** (loopback) and **`/api/relay/health`** → `federation.link {up, since, changedAt, drops, repins,
  last}` and `federation.hubSees {nodes, sessions, seesYou}` (what the hub's relay reports of its cluster when the spoke
  registered); the Relay page's Hub line reads `link up 12 m, 3 drops, 1 re-pin, hub sees 2 nodes`.
- **The grid gate** adds `link=up|down N s, drops=N, hubSees=…` to every `viewer stall …` line, and a link that changed in
  the last 60 s makes the report `viewer stall noted — cluster link flapped N s ago, not rebuilding`.

Reading it: `repins` climbing with every hub restart is expected (a QUIC hub's certificate is regenerated per start and
the spoke restarts its relay to pin it — each restart is one blink for every downstream viewer); `drops` climbing while
the hub did not restart is the network between the sites. Match the `down`/`up` timestamps against the blackouts.

## The push that went nowhere (0.21.14)

Page visible, encoder frozen: the hidden-window push was being made on the pacer's generator track, which has no
`requestFrame()`, so a covered or minimised window (which still reads "visible" under the app's backgrounding flags)
got no frames at all. Since 0.21.14 the push reaches the capture behind the pacer and `/api/diag` shows
`publisher.restamp.pushes` climbing whenever the automatic capture is silent. The signature on 0.21.12 or 0.21.13:
`encoded.frames` flat, `visibility` visible, no `restamp` field in the diag.

## Frames in batches (0.21.13)

With the clock fixed the picture stayed frozen: a hidden document hands its captured frames over in batches, and both
ways of stamping a batch lose it (within microseconds the library keeps one frame; spread backwards the early ones are
late). Since 0.21.13 the frames queue and leave one per frame interval. The signature: viewer decoding about one frame per
keyframe interval with a stalled buffer while the publisher's `window.__restamp.burstMax` is large.

## Frames with a frozen clock (0.21.12)

The follow-up to the dark grid: with 0.21.11 the hidden window kept producing frames, and the viewers still saw nothing.
At the tunnel the composite arrived at 15 fps with one timestamp on every frame — the player's buffered range was a single
point — because a frame pushed from a hidden document inherits the clock of the last visible paint. Since 0.21.12 the
composites re-stamp their frames with the page's clock. The signature on an older build: `w.video.out.stats.frameCount`
climbing at the viewer while `w.video.out.frame.peek().timestamp` never changes and `buffered` is one point.

## The grid that drew into the dark (0.21.11)

A relay box whose grid every viewer saw frozen, while its cameras, pairs and hub link were all healthy: `/api/diag`
showed `publisher.grids[0].encoded.frames` at 0 for hours and `visibility: hidden`. A hidden Chromium document stops
automatic canvas capture, so the composite was drawn fifteen times a second into a stream that carried nothing. Since
0.21.11 the page pushes the frames itself when the document is hidden or the encoder stalls, and the grid's events
(`/api/diag`, launch.log) say `window hidden -- composite frames pushed by the timer`. The signature to look for on an
older build: `encoded.frames` flat with `visibility` hidden while every monitor's `time` advances.

## The six-camera wall (0.21.10)

"Add does nothing past six cameras, and closing one makes the new camera appear once per click" is not a KASTR rule: a
browser allows six concurrent HTTP/1.1 connections to one host, every camera's monitor stream on the owner page held one
open, and the page's other requests queued behind them. Since 0.21.10 the monitors ride WebSockets (outside that pool)
and `/api/diag` shows `monitor.ws` per slot; a box on an older build can be checked with `scratchpad/v02110/pw_monitors.py`
against the dev harness (adds one to five answer in milliseconds, the sixth leaves the next fetch hanging).

## Seen from the tunnel (0.21.9)

`scratchpad/v0219/../v0218/pw_field.py <host> <viewer code> --room <slug> [--open <substring>]` joins as a viewer and prints,
per tile, the frames delivered per second and the longest gaps over the sample, the rendition and tuning, the audio sync
state (`delay`, `jitter`, `maxAge`, `stalled`) and every console line about audio. Frames arriving in clusters at the
encoder's spacing with multi-second holes between them (Southridge, 2026-09-30) point at the link into the hub; a steady
low rate points at the encoder; `sync[audio]: N late frame(s)` lines are the dropped speech behind "static".

## Viewer reports (0.21.8)

A stall report from a viewer is a hint about that viewer's path, never an order. Since 0.21.8 the lines to look for:

- `page: pair <camera>: viewer stall noted -- no relay evidence, pair running (gen G, N s), not restarting` — the owner's
  page received a report for a running pair and did nothing. Many of these from one camera means one viewer is
  starving (a phone, the tunnel, two hops), not that the camera is failing.
- `rtsp nudge refused <camera> why=viewer -- the pair is N s into gen G` — an older page (or a tool) asked for a restart
  of a pair that came up less than a minute ago; refused. `/api/rtsp/list` → `publish.nudges.refused` counts them.
- `rtsp nudge <camera> why=viewer …` followed by `rtsp pair … start` — a restart that DID happen: the pair was troubled
  (an exit or a lost session in the last 60 s) or the relay listed the room without it. Those are the ones to read.
- `page: grid <name>: evicted <camera> (monitor attempt N)` — a monitor-ladder eviction; since 0.21.8 only for a camera
  whose pair is not running, is in standby (only with `ondemand = on` since 0.21.10), or exited in the last 30 s.

## Reconnect loops (0.21.8)

A client re-subscribing to everything every couple of seconds pulls the latest group of every stream each time — a
burst for the whole relay and, for a spoke's cameras, a re-pull over the cluster link. The lines that name it:
`watch: fallback viewer <peer> is looping on <b> (N starts in 30 s)` (a browser that cannot play the fMP4 fallback),
`relay pipe: <peer> opened N short pipes in 60 s` (a web client's `/relay` WebSocket dying and coming back),
`relay auth: <remote> opened N sessions in 60 s` (any client reconnecting), plus `/api/relay/health` → `auth.churn`
and, on the client, `window.__netEvents` (in `/api/diag` → `netEvents`).

## Reading the counters

| Pattern | Meaning | Row in ARCHITECTURE's restart table |
|---|---|---|
| `sessionKills` climbing, `parked: true`, `lastSession` says unauthorized / expired | the relay refused the token; the pair parks and re-mints | 2–5 |
| `sessionFails` climbing, `restarts` low, `lastSession` "session severed/closed" | relay bounce; moq reconnects by itself, viewers lose picture for the gap | soft |
| `restarts` climbing, `lastExit.who = ffmpeg`, `error` shows ffmpeg text | the camera side dropped the RTSP session (no `-reconnect` exists for RTSP; each hiccup is a pair restart) | 1 |
| `nudges.viewer` climbing | viewers reported the feed frozen (stall reports) | 8 |
| `nudges.noEcho` climbing | the relay stopped listing the path twice in a row while the pair was up (0.13.1 evidence rule) | 9 |
| `nudges.api` | a hand or the page's Keep/republish path | 6–7 |
| Share row says `offline — removed from grid (attempt N); retrying` | 0.14.0: `restarts` passed 5 with the pair down; the camera left the grid (seat kept) and returns ~5 s after the pair publishes again | eviction |
| nothing climbs, viewers still lose it | look at the viewer: a tab hidden > 60 s drops non-selected tiles until shown; a publisher-mode box never creates viewer tiles | viewer-side |

0.15.0: a feed belongs to one grid (`gridId`, Share-row picker); eviction and re-admission are per grid, and `__gridStates()` lists every grid's members/evicted. `restarts` resets to 0 after a pair has lived 60 s; `sessionFails` / `sessionKills` / `nudges` never reset.

0.16.0: a self-update that does not come back reads, in launch.log, `relaunching (update) ...` -> `relaunch: child pid N` (or `relaunch: child exited at once (code C) -- respawning` / `relaunch: shell launch` when the fresh exe was still being scanned) -> in the NEW process `relaunch: predecessor pid N gone` -> `update-check: updated`. If the successor never answered, the old process logs `relaunch: successor never came up -- staying on v<mine>`, writes `update-check.json` status `relaunch-failed` and shows a dialog instead of exiting. `--diagnose` output and `/api/relay/health` (pairs: `gen`, `restartsTotal`, `sessionFails`, `sessionKills`, `lastSessionAt`) carry the same counters as `/api/rtsp/list`; `/api/relay/metrics` (loopback) exports them as `kastr_rtsp_pair_*` gauges.
