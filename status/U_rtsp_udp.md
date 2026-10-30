# 0.21.96 RTSP over UDP: status

Branch `udp-0.21.96`, based on e4678b8 (v0.21.95). Not merged, not pushed, not built. Main has since moved on (meetings, builder filters, drag-select), so the parent merges.

**Why:** the Convoy Tech IP1910IR plays in VLC, which uses UDP, but KASTR forced RTSP over TCP.

## What changed

### Transport per camera (kastr_rtsp.py)
- Each rtsp:// row on the Share panel has a **Transport select** with three choices: Auto (the default), TCP and UDP.
  - It is built at moq-watch-lite.html:27572.
  - A change goes to `POST /api/rtsp/transport` through `window.__rtspTransport` (html:34450).
  - For rtsps:// the select is disabled and its title says why: the encryption runs over the TCP connection.
- The pieces:
  - `TRANSPORTS`, `UDP_BUFFER` (4 MB) and `AUTO_PICKS` are at kastr_rtsp.py:1445-1447.
  - `feed_transport` (:1480) says what a feed uses now. rtsps:// is always TCP, and non-RTSP sources are untouched.
  - `udp_args` (:1516) adds `-rtsp_transport udp -buffer_size 4194304`, plus `-min_port/-max_port` when `KASTR_RTSP_UDP_PORTS=40000-40999` is set.
  - `input_args(..., transport=)` (:1657) takes the transport.
- Every camera reader passes its transport: the publisher pair, the low copy, the monitor and the probe.
- **Auto** (`sends_h264` :5771 / `_probe_once` :5853, with `_probed` keyed by `(url, transport)`) works like this:
  - It probes TCP first.
  - If TCP is refused (461 Unsupported Transport) or gives no picture, it probes UDP.
  - If UDP gives a picture, it is kept for the run in `AUTO_PICKS`, with its reason ("the camera refused TCP" or "TCP gave no picture").
  - A refusal seen later at runtime drops the cached TCP probe, so the next start asks again.
- **Persisted** per camera URL in rtsp-feeds.json under `"transports"` (load :4046, save :4152).
  - It is sealed like the feed URL (kastr_secret.py:407 `transports/*/url~`), so a camera password is never on disk in clear.
  - `Bridge.set_transport` (:5335) checks the input, saves, resets the Auto pick and refused stamps, and restarts the camera's readers.
- `Feed.info()` and `/api/rtsp/list` carry `transport, transportNow, transportWhy, tcpRefused, udpRefused, loss` (from `transport_info`, :1641).
- `/api/diag` has `_rtsp` = `Bridge.diag_feeds()` (:5380, wired at kastr_serve.py:2313). It has the camera URLs masked, the transport, the loss counts and the publisher state.

### Visible loss
- RTSP readers run at `-loglevel level+warning` (`RTSP_LOGLEVEL` :1449). The demuxer's loss lines are warnings and were invisible at `error`.
- `rtsp_line` (:1616) is the hook in the existing stderr drains: the publisher drain (:2780) and the monitor drain (`spawn`).
  - It counts loss lines on the feed's `LossMeter` (:1544, `LOSS_PATTERNS` :1454) and keeps them out of the error tail.
  - The kinds counted are missed packets, late (`max delay reached`), bad cseq, dropped MJPEG frames, and decoder concealment.
  - Every error-level line from the video decoder of a UDP reader counts as decode (`DECODER_CTX_RE` :1467). Over TCP such a line is still kept as an error.
  - Other warnings stay unseen, as before.
- The meter keeps totals since start plus the last 60 s, per reader (pub / low / mon). It also counts "Last message repeated N times" lines.
- The row line (`transportLine`, html:32763) reads like this:
  - "UDP · lost 37 packets in the last minute (212 since start) · 2 frames dropped in the last minute"
  - "Auto · using UDP — the camera refused TCP · no packets lost"
  - Nothing on TCP unless loss was reported. It turns amber while packets were lost in the last minute.
  - "late" is not added to "frames dropped", because each `max delay reached` line pairs with a `missed N packets` line.

### Refusal faults
- `transportFault` (html:32748) says "the camera refused RTSP over TCP — set Transport to UDP or Auto on its row", plus the Auto, UDP-refused and both-refused variants.
- A refusal that the camera's video has since outlived (`publish.videoAt` later than the refusal) is ignored.
- Where the text appears:
  - In `faultText` for browser-graph slots.
  - **On the row's transport line for server-published (native) cameras**, which is the normal mode (html:33015). `faultText` returns early for native slots, so the first lab run never showed the hint.
  - In the offline-camera alert's reason (html:35135).
- With no refusal seen, the generic fault on a TCP camera adds "(if it plays in VLC, set Transport to Auto or UDP on its row)".

### UDP cameras are encoded, not passed through (new; Kenton should know)
- `udp_copy_ok` (:419) is used by the publisher (:2439) and the monitor (`monitor_plan` :5918). An H.264/H.265 camera read over UDP is decoded and encoded once on the box, even with Pass through on.
- The lab showed why. A lost RTP packet leaves a hole in a copied bitstream, and Chrome does not conceal it:
  - The share page's `<video>` monitor of a 5%-loss copy hit `PIPELINE_ERROR_DECODE` every ~4 s and restarted in a loop. The grid mosaic, which is drawn from the monitors, went with it.
  - A viewer's `VideoDecoder` threw "Decoding error" over and over. The picture changed in only 3 of 39 one-second samples.
  - ffmpeg's decoder conceals the hole, which is also why the camera looks fine in VLC. With the encode, the viewer's picture moved in 39 of 39 samples with no decoder errors, and the monitor had 0 error events in 45 s.
- Cost: one encode per UDP camera, on the hardware encoder when there is one. `KASTR_RTSP_UDP_COPY=1` copies anyway, for a UDP link known to be clean.
- TCP cameras are unchanged.

### Two older bugs fixed on the way
- **The monitor's `?transcode=1` / `?pt=1` never reached the bridge.** kastr_serve's `do_GET` strips the query (kastr_serve.py:5246, since 0.14.0), so "converting the preview to H.264" asked for an encode and got the same copy again.
  - `stream_query` (:6306, used at :6376) recovers the query from the request line.
  - Side effect: a page with Pass through on now really gets copied monitors, and the H.265-without-decode fallback really encodes.
- **`PROGRESS_RE` (:3326) missed `speed=   1x` and `stream_0_0_q=-1.0`.** Those `-progress` lines landed in the publisher's error tail and showed as a slot's fault.

### MJPEG over RTSP
- RFC 2435 MJPEG works over TCP and over UDP. It is always encoded to H.264 (`copy False, codec h264`), even with the row's Pass through on, because MJPEG is not in `PASSTHROUGH_CODECS`.

## Tests
- New: `tests/test_release_0_21_96_rtsp_udp.py`, 39 tests.
  - Argv, including one run of the bundled ffmpeg 9.0.1 with the UDP options against a closed local port.
  - Transport and Auto probing (with `_probe_once` mocked): refused, silent, OK, neither, forced, rtsps, and a runtime refusal.
  - Persistence, including that the sealed camera password is not on disk.
  - The loss parser, the meter window, repeats and decoder errors.
  - Info and diag redaction.
  - Monitor: a UDP monitor and publisher are encodes, the env escape hatch, the query recovery, and the progress lines.
  - Page strings and CRLF.
  - `transportLine` / `transportFault` run in the bundled Chromium.
- Full suites (`python -m unittest discover -s tests -q`, with the lab down):
  - **Windows:** 2470 ran, 13 skipped, 2 failed.
    - `test_npu_fx` fails in a worktree (untracked model files).
    - `0_21_93_video_stall.StuckCaptureReal` patches `threading.Thread` for the whole process and loses a race under load. It passes alone (2 of 2), and it also failed in an earlier WSL run, before this branch's regex change.
  - **WSL** (`wsl -u kenton`): 2470 ran, 30 skipped, only `test_npu_fx` failed.

## Lab
The lab is in `C:\kastr-scratch\v02196\udp` and has been taken down.
- **Setup:**
  - All on 127.0.0.1: TCP 9460-9479, UDP 5080-5089.
  - A lab RTSP server (`rtsp_lab.py`, 9470) serves H.264 and RFC 2435 MJPEG. It can refuse TCP, accept TCP silently, drop a random % of RTP, or drop bursts, and it records per-session sent/dropped counts.
  - Three KASTR dev boxes (9460 camera box with the secured relay on 5080, 9461 viewer, 9462 one-camera box) run the worktree code with the main checkout's ffmpeg / moq / moq-relay.
  - The pages ran in headless Chrome for Testing with fake devices, `/api/screen/**` blocked and no getDisplayMedia.
- **Numbers (final run, all fixes in):**

| Case | Result |
|---|---|
| Auto, H.264 camera that refuses TCP | UDP video after **11.2 s**; row says "Auto · using UDP — the camera refused TCP · no packets lost"; a viewer has a moving picture |
| Auto, MJPEG that refuses TCP, Pass through on | UDP video after **6.1 s**, encoded to H.264 (copy false) |
| Auto, TCP accepted but silent | UDP after **30.7 s** (the TCP probe has to time out); "TCP gave no picture" |
| Forced UDP, 5% random loss, 60 s | server dropped **570 / 10834** and **572 / 10627** in the two long sessions; KASTR counted **574** (pub) and **578** (mon). The ~2 s probe sessions are not counted, by design |
| Forced UDP, burst of 30 every 4 s (MJPEG), 40 s | server dropped **300 + 300**; KASTR counted exactly **300 + 300**, plus 86 MJPEG frames dropped per reader |
| Forced TCP on a TCP-refusing camera | the row shows "TCP · the camera refused RTSP over TCP — set Transport to UDP or Auto on its row" within **1.0 s** |
| Viewer of a single lossy UDP camera (not in a grid) | picture moved in **39/39** one-second samples, 0 decoder errors (before the encode rule: 3/39, repeated "Decoding error") |
| Share page monitors with 5 UDP cameras | **0** `<video>` error events in 45 s (before the fixes: one decode error and restart every ~4 s on the lossy camera) |

- **Shots** (light and dark rows for every case): `C:\kastr-scratch\v02196\udp\shots\row-{auto,mjpeg,loss,burst,tcpfault,silent}-{light,dark}.png`, the share panels `share-*.png`, and the viewer `viewer-lossy-solo.png` (5%-loss picture with concealment artifacts).

## Not proven
- A real camera: the Convoy IP1910IR has not been tried. The lab server stands in for it.
- The Linux UDP runtime. The unit tests pass under WSL, but no UDP camera was run on Linux.
- 4:2:2 MJPEG (`LAB_MJPEG_FMT=yuvj422p`) was not run. Only 4:2:0 was.
- The encode cost of UDP cameras on the vehicle box's CPU or GPU.
- The relay's TCP companion ports 5080-5083 sat in this lab's 508x block. No clash was seen.

## Vehicle checklist (Kenton)
1. Share panel: on the Convoy camera's row, set **Transport: UDP**, or leave it on Auto. Auto will switch on its own if the camera refuses TCP or gives no picture over it.
2. The first time UDP is used, **Windows may ask to allow ffmpeg through the firewall**. Allow it on Private networks, or the camera's RTP cannot reach KASTR. If the network only opens ports, set `KASTR_RTSP_UDP_PORTS=40000-40999` and open that UDP range.
3. Drive. The line under the row shows "UDP · lost N packets in the last minute (M since start)", plus dropped frames for MJPEG. It turns amber while packets are lost.
4. Afterwards, send **/api/diag** (or copy it). `_rtsp` has per-camera totals and the last minute for each reader (pub / low / mon), with the camera URLs masked.
5. Expect concealment smears on a lossy picture rather than freezes. A UDP camera is re-encoded on the box, so watch the box's CPU and GPU with several UDP cameras.
