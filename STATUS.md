# 0.21.94 effects branch (`fx-0.21.94`) -- "Fastest that fits" -- status

Kenton picked "Fastest that fits" for Auto (2026-10-29). The rest of the effects work (mask clean-up, colour-guided edges,
larger MODNet input, Studio Effects switch, engine in diag) is already in main (58d90d6); this branch was fast-forwarded
to it first. VERSION not bumped, nothing pushed, not merged.

## What changed (moq-watch-lite.html, MODNet block)

- **Auto times both devices.** When both the NPU and the GPU are candidates, the camera still starts at once on the first
  that runs (NPU, else GPU, at 512x288), then `matRace` times each device warm: `matReach` walks `MAT_SIZES`
  (512x288 -> 704x384 -> 896x512) and keeps climbing while the median of three warm runs (`matTime`) stays within
  `MAT_BUDGET_MS` 34. A size over the budget is released and not tried again this run.
- **The pick (`matChoose`, pure).** The device that reaches the larger input wins. The same size goes to the NPU (less
  power). If neither fits even the first size, the faster one runs it. Only one device = that one, grown as far as it fits.
  The loser's sessions are released 1.5 s later, once no camera loop runs on it. The answer is kept for the run per
  orientation (`matPickCache`) so the Camera-menu preview and the live camera agree and the second one starts instantly.
- **Re-deciding under load only.** Same trigger as the 0.21.94 step-down: over 1.6x the budget for 25 mattes in a row
  (`matUnderLoad`). Then `matLoadChoice` (pure): move to the other device when it reached at least the next size down
  (re-timed now, from its size down: `matMove`), else one size down, else stay.
  - **Hold time:** no change within `MAT_HOLD_MS` 30 s of the last one (the pick, a move or a step-down).
  - **Never back:** a device it moved away from is never chosen again this run (`b.matLeft`); a device that could not take
    the load is not asked again. So it cannot flip-flop; the worst case is one move plus step-downs.
  - The timing runs hold this loop's own mattes for ~0.1 s (`b.matHush`) so a session never runs twice at once.
- **A forced device** (the rig's `proc`) keeps the single-device grow / step-down, now also with the hold time.
- **Diag says why.** `/api/diag` publisher slot `fxEngine.pick` = `{dev, why, reach: {npu, gpu: {idx, floor, ms per size}},
  moves, holdS, left}`, e.g. `why: "the GPU reaches 896x512 within 34 ms, the NPU only 512x288"`. launch.log gets one line:
  `page: camera effects: MODNet on the GPU at 896x512, 32 ms a frame (picked: ...)`, and one per later move.

## Lab proof on this machine (fits_lab, port 9351, headless bundled Chrome with WebNN, clip720.mp4, no camera)

The page's MODNet block exactly as in the worktree, the real `modnet_fp16.onnx` over WebNN. Three fresh races:

| Run | Started on | Race done | NPU warm (512 / 704) | GPU warm (512 / 704 / 896) | Picked | Steady ms (10 s) |
|---|---|---|---|---|---|---|
| 1 | NPU 512x288 at 1.5 s | 5.0 s | 34 / 60 | 10 / 20 / 32 | **GPU 896x512** | 36 |
| 2 | NPU 512x288 at 0.7 s | 3.3 s | 35 / -- | 11 / 18 / 33 | **GPU 896x512** | 33 |
| 3 | NPU 512x288 at 0.6 s | 4.1 s | 32 / 53 | 11 / 19 / 32 | **GPU 896x512** | 36 |

So on this machine Auto = **the GPU at 896x512**, 3 of 3. The NPU stays at 512x288 (31-35 ms; its 704x384 takes 53-60 ms).
896x512 on the GPU sits right at the budget (32-33 ms against 34): in the full app, with the camera, the clean-up and the
renderer on the same thread, the warm timing may land just over and pick GPU 704x384 instead. Either is the right answer
for "fastest that fits"; it is decided once at the start and never toggles. About 24 mattes a second in the lab.

## Tests

- New `tests/test_release_0_21_94_fastest_fits.py` (LF): string checks, plus the page's MODNet block as shipped run in
  headless Chromium (ports 9343-9349) against a fake onnxruntime whose sessions sleep a set time per device and size:
  the GPU reaching further takes over (and the NPU's sessions are released), a tie goes to the NPU, the NPU reaching
  further wins, only one device, neither fits, a busy GPU moves once to the NPU and never back (even when the NPU then
  turns slow and the GPU recovers), nothing changes inside the hold time, plus the pure `matChoose` / `matLoadChoice`.
- `tests/test_release_0_21_94_fx.py`: the pinned under-load line now calls `matUnderLoad` (deliberate).
- Suites: see below.

## Draft release text (0.21.94, effects)

> **Background effects pick the fastest chip that fits.** On a computer with both an NPU and a graphics chip, KASTR
> times each one when your camera effects start and uses whichever can run the sharpest person outline within a
> frame's time; if both manage the same, it uses the NPU, which saves power. If the computer gets busy later it moves
> once to the other chip or steps the outline down a notch, and it never flips back and forth.

## Field checklist (Kenton)

1. Camera on, Blur or a background on. In Get diagnostics, `fxEngine.pick.why` should say which chip and why
   (on this laptop expect the GPU at 896x512 or 704x384).
2. launch.log: one `page: camera effects: ... (picked: ...)` line after a few seconds.
3. Start something heavy on the GPU (a game, a 4K video export) for a minute: at most one move
   (`fxEngine.pick.moves`, `left`), no back-and-forth.

## Not done / still pending

- The public matting clip with ground truth: NOT approved; left for 0.21.95.

## Suites

After `git merge main` (58d90d6) and this change:
- Windows: `python -m unittest discover -s tests -q` -- 2389 tests OK (skipped 11).
- WSL (root venv, KASTR_PRES_POWERPOINT=0): 2389 tests OK (skipped 28; the Chromium cases skip off Windows).
- Page scripts compile in headless Chromium (jscheck: 6 scripts, 0 bad).
