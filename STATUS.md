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

## Open

- **Item 4 (deferred): the My room viewer evidence path.** A viewer's `~stalled` report rides the room state model. In My
  room, `pubState`'s path is "" (moq-watch-lite.html ~19068), so the owner never hears it. The owner's `nudgeFromViewer`
  gate also refuses to restart a running native pair when there is no exit, no session line and no relay evidence.
  Given the lab finding, this is the most likely real heal path: a viewer that gets sound but no picture should reach the
  sharer and trigger the same restart that Pause + Resume does.
- What really triggers it (gfxcapture on a still Teams/PowerPoint window, a hardware-encoder hang, moq import, the relay or
  the viewer) is unproven. The checklist below is meant to tell these apart.

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
     viewer. Item 4 is then the fix to build next.
   - [ ] Any moq session lines (SOFT/HARD) or `exit who=moq` near the time.
4. Did the share heal by itself within about 10-40 s, without Pause + Resume? (Only possible if the new check fired.)
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
- Existing 0.21.91 capture-freeze and closest-relay tests: pass unchanged.
- Full suites (2026-10-28): Windows 2226 tests, only test_npu_fx failing (always fails). WSL 2226 tests, only test_npu_fx
  failing after one fix to the new lab test: Linux ffmpeg 8.0.1 probes the TCP input for about 5 s, so the lab now arms
  the watchdog only after the first frame. The new file passes 3/3 on WSL and 3/3 on Windows after that fix.
