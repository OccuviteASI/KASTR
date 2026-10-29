# 0.21.94 effects branch (`fx-0.21.94`) -- status

Kenton's question (2026-10-28): "Can KASTR read the Windows Studio effects for the blur and background options? Instead of
using the built in person detection? I would like to clean up the detection so it's cleaner. Do we need to do more training?"

He chose both options: (1) a "Use Windows Studio Effects blur" switch, and (2) a cleaner version of KASTR's own detection
without training. VERSION is not bumped, nothing is merged and nothing is pushed.

## Short answers

- **Can KASTR use Windows Studio Effects?** Partly. The driver's background **blur** can be switched on from KASTR, and
  this branch does that. The driver's **mask** (the person outline) is not something a browser page can read. KASTR
  would need its own native capture path to get at it, so replacement backgrounds still use KASTR's own mask.
- **Do we need more training?** No, not for this round. Most of the rough look came from how the mask was cleaned up,
  not from the models themselves. One better pretrained model is worth a lab test (see "Downloads wanted"). It is
  Apache-2.0 and needs no training.

## What changed

### 1. Cleaner detection, no training (`moq-watch-lite.html`)

**One clean-up step: `fxPostMask` (`FX_POST.seg` / `FX_POST.mat`).**
- It replaces `mainSubjectMask` and the per-call alpha ramps, and serves both the effects loop and the presenter cut-out.
- It works on a coarse copy of the mask (at most 320 x 180 cells, each holding the maximum of its block), so a thin
  arm or headset band survives the shrink.
- **Keeps one person.** Confident regions are joined 8-way, so a diagonal wrist or headset band is no longer split
  off. The biggest region is kept, with distance from the centre breaking ties. Everything else is dropped: the chair,
  the door frame, someone behind you.
- **Hysteresis in time.** A cell that was the person last frame stays the person down to (core + lo) / 2, so edge
  parts do not blink in and out.
- **Reach (MODNet only).** Half-sure cells that touch the person and lie within 3% of the frame height of it are kept:
  a hand, a headset cup, the edge of the hair. The reach never carries into the next frame, so a weak bridge cannot
  pull in a desk. MediaPipe's reach is 0, because on the real clip it grew background bits.
- **Holes up to 2% of the frame are filled** (a dark shirt patch, the gap under a headset band).
- One soft rim cell is kept, then the alpha ramp is applied. The temporal smoothing (EMA) is unchanged.

**Edge refinement (`fx-gl`).**
- The WebGL guided filter now steers by the frame's colour instead of its brightness, with radius 12 and statistics
  at half resolution (`FX_GUIDE`).
- The colour version separates hair and skin from a background of similar brightness.

**MODNet input grows when the device can afford it.**
- Sizes: 512x288, then 704x384, then 896x512 (`MAT_SIZES`).
- A bigger size is built in the background and kept only if its warm run takes at most `MAT_BUDGET_MS` (34 ms).
- A size that later runs slower than 1.6x the budget for 25 frames steps back down.
- The bigger input is what brings back the headset band and the hands (see the numbers below).

### 2. Which engine runs, and how fast

- **In /api/diag:** each camera slot of the publisher gets `fxEngine`, with these fields:
  - `engine`: modnet, mediapipe, loading or none
  - `device`: npu or gpu
  - `model`, `quality`, `input` (e.g. `704x384`) and `ms` (model time per frame)
  - `webnn`, `slow`, `failed`
  - `post`: the clean-up's own stats (regions, dropped, holes, grown, area, ms)
  - `driverBlur`: Chrome's view of the camera's own background blur
- **Also in /api/diag:** `fxStudio` (the camera blurs itself) and a top-level `_studiofx` (cameras that offer it,
  held or not).
- **In launch.log:** one line per change, e.g. `page: camera effects: modnet npu 512x288 ...` or
  `... 704x384 took 62 ms -- staying`.
- **In the rig:** `__fxEngine().info`.
- **No codes or tokens anywhere.** The diag body still goes through `kastr_secret.mask`.

### 3. "Use Windows Studio Effects blur" (`kastr_studiofx.py`, `kastr_serve.py`, `kastr.py`, `build.py`, page)

**The switch.**
- It sits in the Camera card under Background quality.
- It shows only when the chosen camera's driver offers KSPROPERTY_CAMERACONTROL_EXTENDED_BACKGROUNDSEGMENTATION
  BLUR, which needs Windows 11 22H2 or later.
- It never shows on web or remote pages, and it is saved in the fx bag as `studio`.

**What happens when it is on and the background is set to Blur.**
- KASTR's own blur stands down (`fxStudioEff`) and the driver blurs instead.
- Replacement backgrounds (pictures, videos) still use KASTR's mask. The switch only affects Blur.

**How the setting is changed.**
- A separate process does it: `KASTR --studiofx-helper`, run with the user's own rights (no admin, no UAC, no
  service, no scheduled task).
- It uses ctypes and Media Foundation: it activates the camera's source, then goes `IMFGetService` ->
  `IMFExtendedCameraController` -> `GetExtendedCameraControl(0xFFFFFFFF, 41)`, then `SetFlags` + `CommitSettings`.
- It keeps the source open while the blur is held. When it lets go, it puts back the flags it found; the MASK bit and
  any other bits are kept.
- It restores on release, on quit and on EOF, so if the KASTR server dies, the helper restores and exits.
- A driver or COM crash can only kill the helper. After two helper deaths the switch gives up for the run.

**Routes and logging.**
- Both routes are local only (otherwise "camera settings" is denied):
  - `GET /api/camfx/studio[?fresh=1]`
  - `POST /api/camfx/studio {id, on, shallow}`
- Each set is logged as `camera effects: Windows Studio Effects blur on/off -> ...`.
- `KASTR_STUDIOFX_READONLY=1` refuses every set.

**Mask metadata.** It is probed and reported (`mask: true` in the listing). As agreed, there is no native capture path
that reads it.

**This machine (read-only probe).** "Integrated Webcam" (a MIPI camera with no vid:pid) offers blur, mask and shallow
focus, with its flags at 0. Nothing was written to it.

## Numbers (before = main d3af295, after = this branch, the same models)

**How they were measured.**
- The lab is headless bundled Chromium on this machine, lab ports 9341/9342, with no camera, screen or microphone.
- Each engine runs on two drawn scenes with ground truth, 14 frames each:
  - an office with a blue shirt and a chair the colour of the shirt;
  - a living room with a dark shirt.
- Each engine also runs on clip720.mp4, a real webcam clip with no ground truth, so only stray blobs and flicker can
  be measured there.

**What the columns mean.**
- IoU: overlap of the mask with the truth.
- BF2: how well the edge lands, within 2 px.
- Hands, headset: how much of each part is recalled.
- Strays: separate blobs bigger than 64 px.
- Flicker: mean frame-to-frame alpha change.

**Office scene, before -> after:**

| Engine | IoU | BF2 (edge) | Hands | Headset | Strays (real clip) | Flicker |
|---|---|---|---|---|---|---|
| MediaPipe best (landscape 256x144) | .956 -> .960 | .616 -> **.671** | .892 -> .913 | .613 -> .628 | 0 -> 0 | .0038 -> .0038 |
| MediaPipe balanced (256x256) | .921 -> .925 | .544 -> **.627** | .683 -> .718 | .606 -> .624 | 0 -> 0 | .0052 -> .0052 |
| MODNet GPU 512x288 | .847 -> .851 | .497 -> .533 | .534 -> **.635** | .213 -> .223 | **2 -> 0** | .0152 -> .0135 |
| MODNet GPU 704x384 | .854 -> .854 | .572 -> .608 | .868 -> .881 | .717 -> .739 | 0 -> 0 | .0067 -> .0064 |
| MODNet GPU 896x512 | .847 -> .853 | .572 -> .625 | .871 -> .879 | .985 -> .990 | 0 -> 0 | .0063 -> .0060 |
| MODNet NPU 512x288 | the same as GPU 512 (.851, .534, .633) | | | | 2 -> 0 | |

**Dark-shirt scene, BF2 before -> after:**
- MediaPipe best: .517 -> .590
- MediaPipe balanced: .479 -> .545
- MODNet: +.005 to +.017

**What the bigger MODNet input buys** (office, same clean-up, 512 -> 704 -> 896):
- Headset band: .22 -> .74 -> .99
- Hands: .64 -> .88 -> .88
- BF2: .53 -> .61 -> .63

**Model time per frame in the lab** (median of 15; the page measures roughly double, because the camera loop shares
the GPU):

| Engine | 512x288 | 704x384 | 896x512 |
|---|---|---|---|
| MODNet GPU | 10.4 ms | 17.9 ms | 30.2 ms |
| MODNet NPU | 31 ms | 61.7 ms | – |

- MediaPipe best: 14 ms. MediaPipe balanced: 13.4 ms.
- Clean-up (`fxPostMask`): about 2-6 ms per frame.
- The colour guided filter's render was faster than the old one in every run (about 13 ms against 15-17 ms, including
  the lab's readback).

**Flicker:** no added flicker. On the clip it moved by 0.0001-0.0005 in either direction; in the scenes it fell or
stayed flat.

**What did not get better, honestly:**
- **A chair touching the person and the same colour** stays: fp_chair ≈ 1.0 on the dark-shirt scene for every engine,
  before and after. It is one region with the person, so dropping blobs cannot remove it. Only a better model can.
- **MODNet 704 shows one extra small stray blob** on the drawn scenes after the change (0 -> 1). It comes from the
  colour filter at full resolution, not from the clean-up. It is not on the real clip.
- **MODNet does badly on the drawn dark-shirt figure** (hands 0) before and after. That is a limit of the drawn
  footage, not a regression.

**How far to trust these numbers:**
- The figures are drawn, and the clip has no ground truth.
- The direction of each change (edges better, strays down, flicker flat) is reliable.
- The exact sizes on a real face, hair and headset are not. They need Kenton's field look, or a public matting clip
  (see below).

## Engine per kind of machine (from the code)

**The ladder (`pickMatte`, Processor always `auto` since 0.21.93).**
- If WebNN exists, MODNet runs on the NPU first, then the GPU. Otherwise MediaPipe runs (GPU delegate, CPU fallback).
- Only the bundled browser is started with `--enable-features=WebMachineLearningNeuralNetwork`.

**By kind of machine:**

| Machine | Browser | Engine |
|---|---|---|
| Desktop app on Windows with the bundled browser (the default, and every machine without its own Chromium) | bundled Chromium + WebNN | MODNet on the **NPU** if there is one (Copilot+ / Core Ultra / Snapdragon X), otherwise the **GPU** |
| Boxes (relay / publisher modes, hosted relay, RTSP feeds) | bundled | the same ladder, but boxes rarely run camera effects |
| Desktop app with browser = auto on a machine with Chrome/Edge | the person's own Chrome or Edge, no WebNN flag | **MediaPipe** (best = landscape 256x144, balanced = 256x256) |
| Web pages (invite guests, kastr.madlabs.app) | any browser | MediaPipe |
| Linux / macOS | bundled where shipped | WebNN is mostly absent, so MediaPipe |

**Kenton's machine.** A read-only GET of its /api/diag (0.21.93) showed the camera off and no effects loop. 0.21.93
does not report the engine, so 0.21.94's `fxEngine` will tell. This laptop has an NPU, so the desktop app picks MODNet
on the NPU at 512x288:
- 31 ms in the lab, about 60 ms in the page.
- 704 on the NPU took 62 ms, so it stays at 512. **That is the size that loses the headset band.**

**Question for Kenton.** On this machine the GPU runs MODNet three times faster than the NPU (10 against 31 ms) and can
afford 704 or 896. NPU first was chosen in 0.21.21 to keep the GPU and the battery free. Should `auto` pick the faster
device instead, or try GPU 704 when the NPU cannot grow? Not changed here; it is a one-line ladder change once he
decides.

## Model candidates, checked on paper (licence text and model card read)

| Candidate | Licence (where read) | Size / input | Verdict |
|---|---|---|---|
| **MediaPipe selfie_multiclass_256x256** | **Apache-2.0**: Google's model card, page 1: "LICENSED UNDER Apache License, Version 2.0", model date May 10, 2023 | 16,371,837 bytes, float32, 256x256, Vision Transformer, 6 classes: background, hair, body-skin, face-skin, clothes, others (accessories) | **Best candidate; lab-tested after approval, see Downloads.** Classes for hair and accessories (headsets) are exactly Kenton's misses. Same MediaPipe runtime: person = 1 - background, no new code path. The card gives 77.2 mean IoU on its fairness set. Out of scope per the card: surveillance and identity, life-critical uses. Needs a lab speed check: a transformer is slower than the 250 KB selfie model. |
| MediaPipe selfie_segmenter_landscape | Apache-2.0 (already vendored, assets/mediapipe/LICENSE.txt) | 250 KB, 256x144 | Already shipped as "best". |
| PP-HumanSeg v2 portrait (PaddleSeg) | Repo LICENSE is Apache-2.0. The model files and the PP-HumanSeg14K dataset state no separate terms (the dataset is by e-mail request). | 5.4 MB, 256x144, Paddle inference format | Not recommended. Same input size as what we ship, and running it needs paddle2onnx (another package download) and a conversion. |
| MODNet webcam checkpoint (ZHKKKe/MODNet) | Apache-2.0 (repo README: code, models, demos) | Same architecture as our MODNet; trained for webcam video | Possible later. Our Xenova export is the photographic model. The webcam weights would need PyTorch plus an ONNX export (package downloads), and they are hosted on Google Drive. |
| MediaPipe hair_segmenter | Apache-2.0 (per its model card, via search; card not read in full) | 512x512 float32 | Only if hair edges are still the complaint after this round. It is an extra model per frame. |
| RVM (Robust Video Matting) | GPL-3.0 | – | Excluded (Kenton's rule). |

## Downloads

### Done: `selfie_multiclass_256x256.tflite`

Approved by Kenton (via main) on 2026-10-29, for this one file only.

**The file.**
- Source: https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite
- Size: 16,371,837 bytes, exactly as expected.
- sha256: `c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0`
- Licence: Apache-2.0. Google's model card, page 1: "LICENSED UNDER Apache License, Version 2.0".
- Model card details: author Adel Ahmadyan (Google), model date May 10, 2023, a Vision Transformer.
  - Classes: 1 background, 2 hair, 3 body-skin, 4 face-skin, 5 clothes, 6 others (accessories).
  - Input 256x256x3; output 256x256x6 probabilities.
  - Out of scope per the card: surveillance and identity recognition, and life-critical uses or anything needing
    pixel-perfect masks.
- Kept in its own directory in the session scratchpad (`dl_multiclass\`). **It is not in the repo and not vendored.**

**Lab result** (person = 1 - background; GPU delegate; same clean-up as shipped):

| | MediaPipe best (shipped) | multiclass 256 | MODNet GPU 704 |
|---|---|---|---|
| Model time per frame (lab) | 9.3 ms | **30.9 ms** | 18.4 ms |
| Drawn scenes (IoU) | .960 | **.01** | .854 |
| Real clip, desk and plant pot in front of the person | **kept** as part of the person | **dropped** | dropped |
| Real clip, hands and fingers | soft | crisp | crisp |
| Real clip, stray blobs | 0 | 3 (small, at the bottom edge) | 0 |

- **It does not see the drawn figures as people at all**, so the synthetic numbers cannot judge it.
- **On the one real clip it is clearly better than the MediaPipe models we ship.** It drops the desk and pot that
  "best" glues onto the person, the same kind of mistake as Kenton's chair. It is about as good as MODNet at 704.
- **Verdict: not vendored in this branch.**
  - It is about 3x slower than "best" (31 ms in the lab, so roughly 60 ms in the page, every mask frame, on the main
    thread).
  - The only evidence is one clip with no ground truth.
  - It would add 16 MB to every install.
  - Kenton's own machine runs MODNet and would not use it. It would help the MediaPipe machines: browser = auto with
    the person's own Chrome or Edge, and web guests.
- **Recommended follow-up (0.21.95?).** Make it the "best" quality on the MediaPipe path when a timed warm run fits
  (the same pattern as MODNet's `matGrow`), with landscape as the fallback.
  - Its three readers (`segmentForVideo` in the effects loop, the gate preview and the presenter cut-out) take mask 0
    and invert it.
  - `vendor-mediapipe.py` gains the file with the sha256 above.
  - Before that: one more real clip, ideally with a headset.
- Lab sheets: `fx094\out\multi\*.png`.

### Still wanted (not done; needs a new approval)

1. **(Optional) a public portrait-matting test clip with ground truth**
   - Its own licence would be checked first. No specific file is chosen yet.
   - Why: real hair and headset edges with truth, instead of drawn figures. The multiclass result shows how little the
     drawn scenes can say about real people.

## Honest limits

**Studio Effects:**
- **Whether a SET from KASTR's helper reaches Chrome's camera stream is unproven.** The helper opens its own Media
  Foundation source on the camera. Windows camera sharing should apply a driver-level control to every client, but
  Chrome may hold the camera in a mode where the set is refused, or the driver may apply it only to a new stream. This
  is Kenton's field test. The read path works on this machine; the write path is proven only with a fake backend and
  fake COM vtables.
- **The setting may persist after the helper closes,** depending on the driver. The helper always writes back what it
  found, but a crash of the whole machine would leave the driver as set. The Windows Settings camera page can turn it
  off.
- **`driverBlur` in diag is Chrome's view** (`getSettings().backgroundBlur`). It can stay false even while the driver
  blurs.
- **Chrome's own `backgroundBlur` constraint** is another route to the same driver blur. It is not used here, but it is
  worth knowing if the helper route fails.

**Cleaner detection:**
- The figures are synthetic and drawn, the clip has no truth, and a chair the shirt's colour that touches the person
  stays (above).
- Growing MODNet's size builds a second session while the first keeps running, which can cause a one-off stutter of
  about a second at the start.

## Tests

**New file:** `tests/test_release_0_21_94_fx.py`, 37 tests:
- Page strings for fx-post and fx-gl, the sizes and budget, the diag engine, the switch markup and the fx bag.
- kastr_studiofx with `FakeBackend`: list, set, restore, read-only, refusals, MASK kept, ids.
- `helper_main` over pipes, including the restore at EOF.
- A real helper process with a fake backend, and the stop after two deaths.
- `ExtControl` over hand-built COM vtables: the slots, the arguments, release.
- Server routes are local only.
- **fxPostMask exactly as shipped, run in headless bundled Chromium** on lab ports 9343-9349, Windows only: stray
  dropped, hole filled, a corner-joined arm kept, reach for MODNet only, hysteresis, nobody, and a big mask.

**Updated on purpose:** `tests/test_release_0_21_89_presenter_modes.py` (the cut-out now calls
`fxPostMask(c.conf, mw, mh, FX_POST.seg`).

**Kept as before:** the diag line pinned by `tests/test_fx_paused_toast.py`. The engine info sits on its own
`fxEngine` key instead of inside `fx`.

**Suites:**
Both were run after `git merge main`, which brought in the timers and live-feeds work.
- Windows `python -m unittest discover -s tests -q`: **2374 tests OK** (11 skipped).
- WSL (root venv): **2374 tests OK** (18 skipped).

## Kenton's field checklist (0.21.94)

1. **Default camera, background Blur.** Open Diagnostics or /api/diag and check `fxEngine`: engine, device, input and
   ms. launch.log should have one `page: camera effects:` line. Note whether it says npu 512x288.
2. **Hair, hands, arms, headset, shoulders.** Wave both hands, wear the headset, turn the head. Compared with 0.21.93,
   do the hands, arms and headset stay in? Do the edges of the hair look less rough?
3. **Chair and door frame.** Sit so the chair back shows beside you, with the door frame behind you. Bits that are not
   touching you should be gone. A chair touching you, the same colour as your shirt, may stay (known limit).
4. **No new flicker.** Sit still for 30 s and watch the edges.
5. **Studio Effects switch.**
   - With the Integrated Webcam chosen and the background on Blur, the switch "Use Windows Studio Effects blur" shows.
     With a USB camera that has no Studio Effects, it is hidden.
   - Turn it on. Do others in the room see the driver's blur? Does KASTR's own blur stop (`fxStudio: true` in diag)?
     launch.log should say `Windows Studio Effects blur on -> ok`.
   - Turn it off. Check that Windows Settings > Camera > Integrated Webcam > Background effects shows what it showed
     before.
   - Quit KASTR with the switch on, then check Windows Settings again. It should be back to what it was.
   - Switch to a picture background. KASTR's own mask should take over (the driver blur is not used for replacement).
6. **Presenter cut-out (Standout / Reporter).** The cut-out edge should look at least as clean as before.
7. **NPU vs GPU.** If the headset band still drops out and diag says `npu 512x288`, tell us whether the GPU (faster
   here, 704 or 896) should be preferred.

## Draft for RELEASES.md

```
## v0.21.94 — Cleaner background effects, and Windows Studio Effects blur

**Cleaner person detection, no new training (Kenton: "I would like to clean up the detection so it's cleaner. Do we need to do more training?").**
- No training needed this round: the same models, read better. KASTR now keeps only you -- one person -- and drops loose bits around you (a chair back, the door frame, someone walking behind), fills small holes (a dark shirt, the gap under a headset band) and keeps edge parts steady from frame to frame, so a hand or the headset no longer blinks in and out.
- Edges follow the picture's colour, not just its brightness, so hair and skin separate better from a wall of the same brightness.
- On a fast graphics chip, KASTR now feeds the person model a bigger picture when the machine keeps up (704x384 or 896x512 instead of 512x288). That is what brings back the headset band and the hands. It steps back down by itself if the machine gets busy.
- In the lab: edges about 10-15% sharper with MediaPipe, stray blobs on a real webcam clip down from 2 to 0 with the NPU/GPU model, no added flicker.
- Diagnostics now say which engine runs your effects (NPU, GPU or MediaPipe), at what size and how many ms per frame, and launch.log has one line whenever that changes.
- Known limit: a chair the same colour as your shirt that touches you can still show. Only a better model can fix that; one Apache-licensed candidate (Google's multiclass selfie model) did well on a real clip in the lab and is lined up for a later build.

**Use Windows Studio Effects blur (Kenton: "Can KASTR read the Windows Studio effects for the blur and background options?").**
- On a Windows 11 laptop whose camera has Windows Studio Effects, the Camera card shows a new switch, "Use Windows Studio Effects blur". With Blur chosen, the camera blurs the background itself (on the NPU) and KASTR's own blur stands down.
- Pictures and video backgrounds still use KASTR's own detection: Windows does not hand its outline to a browser.
- KASTR puts the camera back exactly as it found it when you turn the switch off or quit. No admin rights, nothing installed.
- Cameras without Studio Effects never show the switch.
```

## Commits on `fx-0.21.94`

See `git log d3af295..fx-0.21.94`.

**Scratch tools** (not committed): in the session scratchpad `fx094\`.
- `run_lab.py` + `lab\lab.html`: the before/after lab, which runs the page's blocks exactly as shipped.
- `summ2.py`
- `jscheck.py`: compiles every inline script of the page in headless Chromium.
- `probe_studio.py`: the read-only Studio Effects probe.
