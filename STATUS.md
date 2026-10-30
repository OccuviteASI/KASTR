# 0.21.95 media A/V sync -- status

Bug (Kenton, field, v0.21.94): "The audio is off a bit when sharing media. It is behind the video by about half a
second." (Share > Media file; Kenton was a viewer.)

## Root causes (both on the sharer)

1. **The file's sound was timestamped on the wrong clock.**
   - Old path (moq-watch-lite.html `wire()`, now ~30755): element -> `m.actx` -> MediaStreamDestination track -> the
     library's audio capture (`@moq/publish@0.5.2` `encoder-CjcsUSCu.mjs`, line 168: the track path makes a SECOND
     AudioContext + worklet; line 151/157: `timestamp = sampleCount / sampleRate + zero`, zero = performance.now() when
     the node is made).
   - That second context starts rendering 0.25-0.7 s after `zero` (lab), and the track hop between contexts buffers on
     top, so the sound's stamps sat 180-420 ms off the picture's (the canvas frames are stamped performance.now() as they
     leave the pacer, `restampCaptureTrack`).
   - The viewer lines sound and picture up by those stamps. The 0.21.9 adaptive audio delay (`window.__audioDelay`,
     ~18861) only reacts to the player's "late audio frame" reports and widens the delay of audio AND video together, so
     it cannot correct a stamp skew between them (it never fired in any run: extra 0, late 0).
2. **Converted files (the MSE path) lost their edit lists.** `kastr_serve.py` `fmp4_start` (line 1264) renamed every
   `edts` to `free` (0.21.0, to drop the seek's empty edit). That also dropped each track's own media_time: the video's
   B-frame delay (1072/16000 = 67 ms for copied H.264/HEVC, 1536/12288 for x264) and the AAC priming (1024/48000 =
   21 ms). The element itself then played the picture ~46 ms late against its sound, on the sharer and for everyone.

The lab gives the skew as audio EARLY; the field reported it LATE. The size of the error depends on how late that second
AudioContext starts on the machine, and the direction depends on the viewer's audio ring (see "Left over"). Both
sharer causes are removed whichever way they fell.

## Fix

- `mediaAudioSource(m, src)` (moq-watch-lite.html ~31307): an AudioWorklet (`kastr-media-clock`) beside the element
  source sends the library `{ samples, sampleRate, channelCount, kind: "music", track }`. `track` is the old element track
  (the speaking ring, the meter and the sharer's earpiece still use it).
  - Each 512-frame block is stamped with its frame on the element graph's own clock, mapped to performance time by the
    fastest delivery seen. The first 500 ms are held while that offset is found.
  - The picture's own delay is added: canvas draw, capture and pacer queue. It is measured per share:
    - `mediaDrawOf` matches each captured frame back to the draw that made it, using the rVFC expectedDisplayTime;
    - `mediaVlagSample` takes the median of 91 frames;
    - the restamper's `__tagIn` / `__tagOut` hooks feed both.
    The value is taken once, and moves only when it stays 30 ms away for 5 s.
  - Stamps stay back to back. A change past 20 ms re-anchors forward by padding silence (up to 1 s; a longer gap jumps)
    and backward only by dropping the overlap. A stamp below one already sent closes the viewer's audio track ('group
    timestamp is below the live edge'), and any gap restarts the encoder.
  - If AudioWorklet or AudioData is missing, it falls back to the old track source.
  - The picture is never held back. Camera and mic (`kind: "voice"`) are untouched, so calls keep their latency.
- `fmp4_start` (kastr_serve.py 1264): each track's elst becomes ONE normal entry whose media_time folds in its empty edit
  relative to the common start S = max(empty edit - media_time/timescale). The page puts S in timestampOffset as before.
  - Leftover entries become a `free` box inside `edts`, so the head keeps its size.
  - A head without an elst is returned untouched.
  - Lab: the flash frame now plays at element mediaTime 2.000 (it was 2.067).
- `__mediaDebug()[i].aclock` = { off, lead, jumps, padded, trimmed, sent, dropped, lastLag }, plus `vlag`.

## Lab numbers

Headless Chrome (fake devices) on a local relay (UDP 5062), sharer 9420 and viewer 9421. The test clip has a white flash
and a 1 kHz beep every 2 s. The viewer measures the flash drawn on the tile canvas against the beep rendered by the tile's
audio graph (output-latency mapped). Values are the median of 12-13 beeps per run, in ms; + = sound LATE.

| clip | before: viewer | before: stamp skew | after: viewer (runs) | after: stamp skew |
|---|---|---|---|---|
| plain H.264 + AAC mp4 (direct) | -253, -355, -193 | -237, -192 | -7, -43, +36, -4, -25 | -12, -9, +3, -6, -39 |
| H.264 + AC-3 mkv (converted, MSE) | -356 | -644 | +6, 0 | -2, -61 |
| HEVC + AC-3 mkv (converted) | -314 | -341 | +4, +18 | +3, -10 |
| MPEG-4 + MP3 avi (transcoded) | -389 | -416 | -47, +63, +75 | -30, -20, -16 |
| camera + mic (unchanged path) | +157 | +53 | +102 | -142 |

- The sharer side (stamp skew, what the fix controls) is now within about +-40 ms on every clip, compared with -190 to
  -640 before. The viewer number adds the viewer's own audio-ring placement, which varies by run (see "Left over"). The
  AVI's +63/+75 runs have a stamp skew of -20/-16, so that difference comes from the viewer.
- Under CPU load (the full unit suite running alongside), the viewer's audio stepped about 120 ms early mid-run in two
  runs (plain -164, avi -146) while the stamps stayed put. At that moment the viewer's sync reference and audio ring
  re-anchored together.
- Sharer's own tile (its earpiece vs its own tile draw), after: -15 to +46 (before: -51 to +15).
- Stamp jumps after the fix: 0 in every run. Silence pads: 0-1. Trims: 0-3 (CPU-starved sharer).
- Picture delay (lead) measured: 2-66 ms (the transcoded AVI is the highest).
- Evidence: C:\kastr-scratch02195vsyncesults\ (before*, after6-after14), rig avsync.py / summ.py / ana.py.

## Tests

- `tests/test_release_0_21_95_media_avsync.py` has 10 tests:
  - functional `fmp4_start` on synthetic moovs: no seek, a seek, a version-1 elst, a head without an elst, a truncated head;
  - static checks on the worklet source, forward-only and gap-free stamps, warm-up, lead hysteresis, restamper hooks,
    camera/mic untouched, and the debug fields.
- `python -m unittest discover -s tests -q`: 2405 tests, 2 failures. Both also fail at the base commit 06e0141:
  test_npu_fx (fails in worktrees only) and test_standby_hub ViewOnlyName (the earlier media-chrome change dropped a
  `:focus-within` rule that test still expects).

## Left over

- **Viewer audio ring (library, not changed):**
  - `@moq/watch@0.6.2` plays audio from a ring anchored to the first sample that arrives. Video waits on the sync clock.
  - An underrun leaves the ring's read position behind for good, so the sound gets later. An overflow skips it ahead.
  - So the viewer's sound can step against its picture by tens to ~120 ms, whatever the stamps say. This is the camera's
    steady +100 and the loaded-run steps above.
  - On a jittery multi-hop field path, repeated underruns can push the sound up to the ring's capacity behind
    (buffered mode = 2 x latency). That would match "behind by about half a second" even with perfect stamps.
  - The next step would be a viewer-side check: the ring's read timestamp vs `sync.now()` per tile, then re-anchor
    (reset the ring at the right moment) when they drift past ~40 ms. That needs a library patch (vendored
    `player-*.mjs`), so it was not done here.
- Pacer phase noise is +-1 frame (33 ms at 30 fps) per beep, so single beeps scatter about +-35 ms around the median.
- Field check for Kenton: share a file, watch as a viewer, then compare
  `__mediaDebug()[0].aclock` (jumps ~0, lead 15-50) and the audio/video feel against v0.21.94.
