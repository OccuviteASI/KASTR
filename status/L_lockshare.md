# lockshare-0.21.96 -- "lock a share in the shared sources ... they stay there and can be started again. Per share option."

Kenton, 2026-10-30. On the details he said: "My share list, I restart."

## What it does
- Each share has a **Lock** switch in two places: its row in Share > Sources, and its own ▾ menu ("Lock this share"). It is
  off by default.
- **Stop on a locked share** stops the stream exactly as today, but keeps a stopped row in my Share list. The row has a
  "stopped" badge, the Lock switch (on), Start and ✕. The ✕ (or switching Lock off) forgets the share for good.
- **Stream library**: a stopped locked share stays listed as "Not streaming" (dark). It disappears only once it is unlocked
  and stopped, or removed.
- **Restart**: locked shares survive a KASTR restart, both stopped ones and live ones. A live locked share comes back as a
  stopped row. Nothing starts by itself.
- **Start** brings the share back under the SAME broadcast path (room/HOST/op/leaf.hang). Viewers' tiles, pins, spotlights,
  grids and library entries reconnect. Only the owner sees the row, so only the owner can start it.
- The ▾ menu's Stop reads "Stop sharing (stays in your list)" while the share is locked.
- Other ways a locked share stops also leave it stopped in the list: Leave, the computer-lock auto-stop, and a locked media
  file reaching its end.
- Unlocked shares are unchanged.

## What can be locked
- **Can be locked**:
  - browser screen, window and tab shares
  - presenter mode
  - native screen://monitor, window and tab shares
  - media files
- **Not lockable**:
  - the toolbar camera
  - RTSP, webcam, host-file and RTMP camera feeds. These already have "Keep after restart" and "On air", which are
    persistent, so locks would double them up.
  - grids, presentation tiles and slide videos/sounds

## Start, per kind
| Kind | On Start |
|---|---|
| Browser screen / window / tab | Opens the browser's own picker straight from the Start click (nothing is awaited before it). Cancel in the picker leaves it stopped. Sound is asked for again only if the share had it. |
| Presenter mode | Same as above, presenter options kept. |
| Native monitor / window / tab | Asks the native list. Starts at once only when the exact source is still there: the monitor is present; the window handle exists with the same program (exe), or with the same title when no exe is known; the tab is still in the same window. Otherwise Share opens with a note ("Pick what to share as ‹name›") and the next pick takes the share's name. Nothing is captured without a click. |
| Media file | In the same session it reuses the file it kept. After a restart it opens the file chooser. With the same file name, the size picker is skipped and size/loop/gain are kept. |

## Persisted (per device)
- Stored in `localStorage["kastr.share.locked"]` as `{v:1, items:[...]}`, at most 24 items. It is mirrored to this device's
  `prefs.json` through prefs.js: `share\.locked$` was added to the WL in `assets/prefs.js` and to `PREFS_ALLOW` in
  `kastr_serve.py`.
- Each item holds:
  - k, kind, name (the broadcast path), label
  - room slug, at
  - lib (library on/off)
  - the screen:// URL only (`isScreenUrl`, nothing else is stored), plus exe and audio for native shares
  - surface and sound for browser shares, plus the presenter flag
  - fileName, shareH, loop and gain for files
- Not stored: access codes, room codes, tokens, invite tokens, camera URLs or RTSP passwords. The loader rebuilds every
  record through a field whitelist.
- Extra rooms (xshare) come back because they are remembered per share by broadcast path (`kastr.xshare.paths.<relay>`),
  and the path does not change.
- Effects (`a.fx`) are not stored. Backgrounds and blur are camera features, and cameras are not lockable.
- The record of a live locked share is refreshed every 10 s (only when it changed) and on visibilitychange→hidden, before
  the prefs mirror's pagehide flush.

## Not kept (defaults for Kenton to confirm)
- Stage position: not kept. The tile returns where a new share goes.
- Encoder quality: global, so unchanged. No per-share copy.

## Code
- `moq-watch-lite.html`:
  - lock block near the publisher's `added[]`: lockable, lockSpec, lockLoad/lockSave, lockSet, parkShare, lockClaim,
    lockForget, lockPlan, lockStart, shRestartTake, `window.__shareLock`
  - renderSources: the live-row switch and the parked rows
  - openMineMenu: switch items
  - __shareMenu: "Lock this share"
  - removeSource(id, forget)
  - mediaFinished
  - shareSurface / shareNative / shareMediaFile take a pending restart
  - libShSync: dark rows for parked records
  - displayAsk(surface, sound)
- `assets/prefs.js`, `kastr_serve.py`: mirror allow-list entries.

## Tests
- `tests/test_release_0_21_96_locked_shares.py`: 17 static checks.
- `tests/test_page_switches` flagged the menu switch as a `<span>`, so it is now a `<label>`. `.misw` keeps
  `pointer-events:none`, so the row's own click still toggles it.
- `test_release_0_21_87_slide_video` pinned the old `pickedH` line. It now pins the form with `opt?.pickH`.
- Full suites, 2491 tests each:
  - WSL: only test_npu_fx fails (worktree-only, missing model files).
  - Windows: test_npu_fx fails, plus the known StuckCaptureReal flake under load. That flake passes alone (14/14) and
    passed in the first full run.

## Lab (C:\kastr-scratch\v02196\lockshare; boxes 9520/9521/9522, relay UDP 5100)
- All PASS (results-lock.json):
  - share → viewer tile, pin and spotlight
  - library live → lock from the row and from the menu → Stop → stopped row in 0.04 s
  - the viewer's tile goes, its pin and spotlight stay
  - library "Not streaming" in 2 s
  - reload: still stopped. New browser profile (prefs mirror only): still stopped, library still dark.
  - Start by a real click: one picker, same path, the viewer's tile back with frames in 2.5 s, pin live, spotlight back,
    library live
  - Start then Cancel: stopped again
  - computer lock: stopped, no restart after unlock
  - an unlocked share: removed as before, never listed dark
  - file: stopped at end and on Stop. Start in-session, and after a new browser via the file chooser, same name and no size
    picker.
  - native plan: 11 synthetic cases
- Screen and window shares used a stubbed getDisplayMedia (canvas). Native capture was checked through `__shareLock.plan`
  only: no real screens in the lab.
- Screenshots: C:/kastr-scratch/v02196/lockshare/shots (light + dark).

## Left
- Field test on Kenton's machine: a native window share, then restart KASTR and Start (exact window → straight back).
