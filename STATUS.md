# Agent K -- 0.21.93: a window share's picture stopped while its sound kept playing

Field (Kordale's My room, viewer = Support Laptop as an invite-link guest): a Teams window showing a PowerPoint slideshow,
shared with sound. About 5 times in 45 minutes the viewer's tile showed the audio bars and a "waiting on connection"-style
message. The sound kept playing, the picture stopped, and Kordale's Pause sharing + Resume fixed it every time.

## What changed (worktree only: no VERSION bump, nothing merged or pushed)

1. **The video frame clock** (`kastr_rtsp.py`, `Publisher._drain`). ffmpeg's `-progress frame=` lines are now read per
   generation into `videoFrames` / `videoAt`. Lines from an older generation and moq lines are ignored, and a new
   generation starts the count over (`start()`).
2. **A video-freshness stall check** (`Publisher._stall_check`). A screen or window share's main pair is now judged by its
   output bytes AND its video frame count. It uses the same 8 s threshold, the same backoff (0/30/60/120/300 s), and the
   same exemption while moq is fighting its relay link. An encode that never prints `frame=` is judged by bytes as before.
3. **A distinct log line and diag fields.**
   - When only the picture stopped, launch.log says:
     `screen: share <b> video stopped -- no new video frame for N s while its sound kept flowing (frames flat at F, gen G, ffmpeg still running) -- restarting the capture (freeze #n)`.
   - When both stopped, the 0.21.91 `capture froze -- no new picture ...` line is unchanged.
   - `lastCaptureStall` now has `kind` (`video` or `output`) and `frames`.
   - `info()` (diag) has `videoFrames` and `videoAt` for every pair.
4. **The hourly relay move waits while you share** (`moq-watch-lite.html`).
   - `relayBusy()` returns "sharing a screen or window" through the new `window.__publisher.sharingScreen()`. That is true
     for any screen, window or tab share, native or browser, paused ones too.
   - The move would otherwise reload the page mid-share: a browser share ends, and a native one restarts.
   - The log says `Closer relay X -- the move waits (sharing a screen or window)`.
   - Failover (a dead relay) is not affected.

## Lab finding: this probably isn't the field cause

Lab setup:
- The bundled ffmpeg 9.0.1, the real `kastr_screen._clocked` graph and the publisher's own output args.
- A capture branch that stops without ending: a TCP rawvideo source standing in for gfxcapture.
- PCM sound on stdin, like the loopback.
- The real `_drain` and `_stall_check`.

Result:
- The overlay holds the 30 fps clock when its capture input stalls.
- **ffmpeg's scheduler also holds the sound input**, so `frame=` and `total_size=` go flat together.
- The 0.21.91 output-bytes watchdog already restarts that case ("capture froze", about 8-9 s after the stall).

So in this lab, a stall inside ffmpeg stops the sound too. In the field the sound kept playing, so Kordale's ffmpeg was
probably still producing video. The stall is more likely past ffmpeg: moq import's video track, the relay, or the viewer
(subscription, decode, or the congestion ladder's "video paused" shed).

The new frame clock is therefore mainly:
- **evidence**: `videoFrames` climbing in diag during a stall proves the publisher's ffmpeg was fine;
- a safety net, should an ffmpeg ever let the sound through without the picture.

The permanent lab is `StuckCaptureReal` in `tests/test_release_0_21_93_video_stall.py`. The scratch version is
`C:\Users\KENTON~1\AppData\Local\Temp\claude\C--Users-KentonJeffery-Claude\5342b5da-d8f4-41a9-963e-6bc5eebb097e\scratchpad\k_video_stall_lab.py`.

## Item 4: the heal path (viewer -> owner -> the cheapest restart)

**What Pause + Resume does (from the code).** `Bridge.pause` sets `paused` and calls `Publisher.nudge("pause")`, then
`nudge("resume")`. Each nudge kills ffmpeg AND moq and starts a new pair: a new capture, encode, moq session and announce.
So Pause + Resume is **two full pair restarts** (one onto the pause card, one back). It never restarts the import alone.

### The steps

1. **Viewer** (`moq-watch-lite.html`, `vstallStep` / `vstallTick`, checked once a second for every tile).
   - Video frames flat while sound bytes arrive (sound newer than the last frame, and within 3 s): armed after 2 s.
   - **6 s** without a frame: the page re-subscribes the tile (`resubscribe`).
   - **6 s** after that, still nothing: it reports to the owner (room.json `stalled`, kind `video`). It reports again
     every **15 s** (with a fresh re-subscribe each time), **6 reports** at most, then gives up until a frame lands.
   - Never for: a tile this page shed itself (`video paused -- weak connection`), a parked / hidden / unwatched tile, a
     hidden page, a tile with no video, a fallback player, a codec it cannot decode, or a silent tile (a paused share's
     card has no sound; picture AND sound stopping is the older stall check's case). The sound stopping mid-stall ends it.
   - The older "Picture stopped" re-subscribe and `stallReport` stand aside while this stall is active.
2. **Report path** (My room and invite-link guests included). room.json rides `<room>/<host>/~member/<peer>`. It is
   written in My room too (only the PUBLIC state, `pubState`, is "" there). A My room guest's token (invite link or a
   shared person) may publish `<room>/<guest host>`, which covers it, and the owner subscribes the whole room.
   `memberApply` now passes the report's kind and the reporter's path to `nudgeFromViewer`.
3. **Owner** (`nudgeFromViewer` -> `healFromViewer` -> `POST /api/rtsp/heal` -> `Publisher.heal`).
   - A `video` report on a running native screen/window share goes here BEFORE the old 8 s / 45 s / evidence gates.
     (Without relay evidence, that gate refused every report on a running native pair, which is why nothing healed
     in the field.)
   - Not for a share that is paused or not on air (logged and noted, nothing restarted). Duplicate reports within 5 s are
     dropped.
   - **Rate limit, per share:** one heal per **30 s**, **6 per 10 min**. Extra reports are logged as `limited`.
   - **Escalation:** the first heal restarts **only the moq import**. ffmpeg (capture, encode, sound loopback) keeps
     running, the old moq gets EOF (killed if still alive after 1.5 s), and a new moq with the same arguments is fed from
     the next PAT. If another report comes within **120 s** of an import restart, the next heal is the **full pair**
     (`quiet()` ffmpeg-first, then `nudge("heal")`, the same as one Pause + Resume step). After a pair restart, the next
     heal is the import again.
   - Every screen share's main pair now passes the pump (`pumped`), so its moq can be swapped. Before, only listed shares
     did.
   - diag `info()` adds `heals {import, pair, limited, refused}`, `lastHeal` and `importRestarts`. The page adds
     `vstall` (totals, the last 12 stalls with their captions, track clocks and steps, and the active tiles).

### One line per step (so one meeting's launch.log tells the suspects apart)

- Viewer (on the app, through `/api/rtsp/note`; a web client logs it in its status bar only):
  - `page: video stall on <path>: the picture stopped N s ago while the sound plays -- re-subscribing (video frame X s ago (F), video bytes Y s ago, sound bytes Z s ago; caption "...")`
  - `page: video stall on <path>: still no picture N s in -- reported to its owner (report n) (...)`
  - `page: video stall on <path>: picture back after N s (re-subscribed Rx, reported Px)`, or `gave up` / `exempt -- <why>` / `silent`.
- Owner:
  - `page: pair <path>: video stall reported by <host> (picture stopped, sound playing; report n) -- asking the bridge to heal it`
  - `rtsp heal <b> step=import|pair why=viewer-video gen=G frames=F (heal n in 10 min; ...)`, or `rtsp heal <b> limited ...` / `refused ...`
  - `rtsp import restart <b> gen=G why=... -- old moq P closed|killed, new moq Q in T s (ffmpeg R kept, frames F; import restart #n)`

How to read it: if `frames` keeps climbing in the owner's lines while the viewer reports, ffmpeg was fine. If the import
restart brings the picture back, the fault was in that moq session (or the relay's copy of it). If only the pair restart
helps, it was the capture/encode. If the viewer's re-subscribe alone brings it back (`picture back` before any report), it was
the viewer's subscription.

### Lab (local moq-relay, real Publisher pair, real `moq export fmp4` subscriber)

Setup: relay on ws 127.0.0.1:9285, the real Publisher (the publisher's own output args, a lavfi test source in place of the
screen, a synthetic sine on the loopback stdin), the pump, `moq import`. Fault: the video packets stop reaching the current
moq while the sound flows. A Python stand-in for the viewer used the page's timings and called `Publisher.heal`.
Scratch: `C:\Users\KENTON~1\AppData\Local\Temp\claude\C--Users-KentonJeffery-Claude\5342b5da-d8f4-41a9-963e-6bc5eebb097e\scratchpad\k_heal_lab.py`.

- **A. Fault in that moq session:** re-subscribe at +7 s (no help), report at +13 s -> `step=import` (old moq closed,
  new moq in 0.0 s, ffmpeg kept, same gen) -> **picture back 2.9 s after the report** (16 s after the fault).
- **B. Fault that follows every moq of that ffmpeg:** report at +13 s -> import (no help), +28 s -> `limited` (15 s
  after the last heal), +43 s -> `step=pair` -> **picture back 3.0 s after the pair restart** (46 s after the fault).
- The ~3 s is the next keyframe plus the new catalog. A lab artifact to know about: when a session ends, the group the fault
  cut short reaches the old subscriber (a few frames). The page may log a quick `picture back` there and re-arm if it does
  not last.

## Open

- What really triggers it (gfxcapture on a still Teams/PowerPoint window, a hardware-encoder hang, moq import, the relay or
  the viewer) is unproven. The heal now cures it either way, and its lines (above) tell these apart.
- Lab B shows the escalation takes about 46 s when the import restart does not help. Pause + Resume by hand is still
  faster there.

## Windows field checklist (Kenton / Kordale, on 0.21.93)

1. Kordale shares a Teams window with a PowerPoint slideshow, sound on, into his My room. Support Laptop joins with an
   invite link. Run it for 30+ minutes, and leave the slides still for long stretches.
2. When the viewer's picture stops while the sound keeps playing:
   - [ ] Support Laptop: write down the **exact** caption on the tile. Each one points somewhere different:
     - "video paused -- weak connection" is the viewer's congestion ladder.
     - "connecting..." or "waiting on relay X..." means there is no catalog.
     - "no data from the relay -- re-subscribed, still waiting (N s)" or "waiting for the camera's next keyframe" means the
       viewer never painted a frame.
   - [ ] Support Laptop: save a diag if possible (stats page / diagnostics) at that moment.
   - [ ] Kordale: **before** pausing, open diag and look at the share's pair:
     - `videoFrames`: refresh twice a few seconds apart. Is it climbing?
     - `videoAt`: is it recent?
     - `captureStalls` and `lastCaptureStall.kind`.
3. Kordale's launch.log around the time:
   - [ ] Any `video stopped -- ... while its sound kept flowing` line (the new check fired: the picture stopped inside ffmpeg).
   - [ ] Any `capture froze -- no new picture` line (ffmpeg stopped both).
   - [ ] Neither line, with `videoFrames` still climbing: ffmpeg was fine, so the fault is in moq import, the relay or the
     viewer. The item 4 lines (step 4) say which.
   - [ ] Any moq session lines (SOFT/HARD) or `exit who=moq` near the time.
4. **The heal (item 4).** Don't press Pause + Resume for the first minute.
   - [ ] Support Laptop's tile: the picture should come back by itself in about **15-20 s** (a 6 s re-subscribe, a report
     6 s later, then about 3 s for the owner's import restart). If the import restart does not cure it, expect about **45-50 s**
     (the pair restart).
   - [ ] Kordale's launch.log: `page: pair ...: video stall reported by support-...`, then `rtsp heal ... step=import`, then
     `rtsp import restart ... old moq ... closed, new moq ... (ffmpeg ... kept ...)`. Is `frames` climbing between them?
   - [ ] Support Laptop's launch.log (the app, not a browser): `page: video stall on ...: ... re-subscribing (...; caption "...")`,
     `... reported to its owner (report 1)` and `... picture back after N s`. Write down the caption and the three clocks.
   - [ ] Which step brought it back: the viewer's re-subscribe alone, the import restart, or the pair restart? That is the
     answer to "where is the fault".
   - [ ] Kordale's diag: `heals`, `lastHeal`, `importRestarts`. Support Laptop's diag: `vstall`.
   - [ ] No heal while Kordale has the share paused, or while Support Laptop shows `video paused -- weak connection`, or
     while its window is minimised.
   - [ ] A stall that keeps coming back: at most one heal per 30 s and 6 per 10 min (`rtsp heal ... limited` lines).
5. Relay move:
   - [ ] Share a window for over an hour on a machine whose closest relay differs from the current one. The log should show
     `Closer relay ... -- the move waits (sharing a screen or window)`, and the share is never cut by a reload.
   - [ ] Stop sharing. The next hourly check may then move as before.
6. Regression:
   - [ ] A normal whole-screen share and a camera still work.
   - [ ] Pause sharing + Resume still works.
   - [ ] A minimised shared window shows its card (no restart loop in launch.log).

## Tests

- New: `tests/test_release_0_21_93_video_stall.py` has 14 tests: frame parsing, the video-only restart and its line,
  fallback, backoff, relay exemption, info fields, the real-ffmpeg stuck-capture lab, and the relayBusy/sharingScreen page
  checks.
- New (item 4): `tests/test_release_0_21_93_heal.py` has 34 tests:
  - the viewer's detection and exemptions: the page's own `vstallStep` / `vstallExempt` run in the bundled Chromium
    (Playwright; skipped without it), plus a compile check of every inline script in the page;
  - the My room / invite-link report path, with real tokens from `AuthService`;
  - the owner's rate limit and escalation;
  - import-only versus full pair, with a real ffmpeg through the real pump into stand-in moq processes (same ffmpeg, new
    moq, starts at a PAT, a wedged moq killed);
  - the page strings.
- Existing 0.21.91 capture-freeze and closest-relay tests: pass unchanged.
- Full suites (2026-10-28): Windows 2226 tests, only test_npu_fx failing (always fails). WSL 2226 tests, only test_npu_fx
  failing after one fix to the new lab test: Linux ffmpeg 8.0.1 probes the TCP input for about 5 s, so the lab now arms
  the watchdog only after the first frame. The new file passes 3/3 on WSL and 3/3 on Windows after that fix.
- Full suites after item 4 (2026-10-28): Windows 2247 tests and WSL 2247 tests, only test_npu_fx failing on each (it always
  fails). The first Windows run found two of my own breaks, both fixed before the reruns:
  - the pump dropped every byte when it was run without `start()` (the 0.21.85 library-copy test). With no import swap in
    flight, it now writes to the pair's own moq, as before;
  - the suspend test's anchor still had the old `nudgeFromViewer(fullPath)` signature. The suspend gate is unchanged and is
    still the first line.
