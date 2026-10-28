"""0.21.93 -- a window share's picture stopped while its sound kept playing (field: Kordale's My room, a Teams window
showing a PowerPoint slideshow, ~5 times in 45 min; Pause + Resume fixed it each time).

The frozen-capture watchdog (0.21.91) watched ffmpeg's output bytes only; it now watches the video frame count as well, shows
it in diag (videoFrames / videoAt) and says which one stopped. The hourly closest-relay move waits while a screen or window is
shared. Nothing here captures, lists or touches a real screen: the capture is a TCP test source standing in for gfxcapture."""
import os
import re
import socket
import subprocess
import sys
import threading
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kastr_rtsp    # noqa: E402
import kastr_screen  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ffmpeg():
    try:
        ff = kastr_rtsp.find_ffmpeg()
    except Exception:
        ff = None
    if ff and os.path.exists(ff):
        return ff
    d = ROOT   # a git worktree has no bundled helpers: the main checkout's bin/ (up to 4 levels up)
    for _ in range(4):
        d = os.path.dirname(d)
        c = os.path.join(d, "bin", "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _pub(url="screen://window/42", role="main"):
    logs = []
    bridge = types.SimpleNamespace(_child_ended=lambda pid: None, log=logs.append)
    pub = kastr_rtsp.Publisher(bridge, types.SimpleNamespace(url=url, sar=None, id=1), "room/h/screen.hang", "http://r/",
                               audio=False, role=role)
    pub.running = True
    pub.since = 1000.0
    return pub, logs


class _Lines:
    """A finished process whose stderr is the given lines."""

    def __init__(self, lines):
        self.stderr = [(x + "\n").encode() for x in lines]


def _threads(started):
    return mock.patch.object(kastr_rtsp.threading, "Thread",
                             side_effect=lambda **kw: types.SimpleNamespace(start=lambda: started.append(kw["name"])))


class FrameParsing(unittest.TestCase):
    """Publisher._drain: -progress frame= is the picture's own clock."""

    def test_frames_and_bytes(self):
        pub, _ = _pub()
        with mock.patch.object(kastr_rtsp.time, "time", return_value=1234.0):
            pub._drain(_Lines(["frame=30", "fps=30.0", "total_size=1000", "progress=continue",
                               "frame=60", "total_size=2000", "frame=60"]), "ffmpeg", pub._gen)
        self.assertEqual(pub.videoFrames, 60)
        self.assertEqual(pub.videoAt, 1234.0)
        self.assertTrue(pub._vSeen)
        self.assertEqual(pub._outSize, 2000)
        self.assertEqual(pub.flowingAt, 1234.0)

    def test_flat_count_keeps_the_old_time(self):
        pub, _ = _pub()
        pub._vFrames, pub.videoFrames, pub.videoAt = 60, 60, 1100.0
        with mock.patch.object(kastr_rtsp.time, "time", return_value=1200.0):
            pub._drain(_Lines(["frame=60", "frame=N/A", "total_size=5000"]), "ffmpeg", pub._gen)
        self.assertEqual(pub.videoAt, 1100.0)   # the count did not grow
        self.assertEqual(pub.flowingAt, 1200.0)   # the bytes did

    def test_older_generation_and_moq_lines_are_ignored(self):
        pub, _ = _pub()
        pub._drain(_Lines(["frame=99"]), "ffmpeg", pub._gen - 1)
        pub._drain(_Lines(["frame=99"]), "moq", pub._gen)
        self.assertEqual(pub.videoFrames, 0)
        self.assertIsNone(pub.videoAt)
        self.assertFalse(pub._vSeen)

    def test_info_has_the_video_clock(self):
        pub, _ = _pub()
        pub.videoFrames, pub.videoAt = 77, 1500.0
        info = pub.info()
        self.assertEqual(info["videoFrames"], 77)
        self.assertEqual(info["videoAt"], 1500.0)

    def test_a_new_generation_starts_over(self):
        with open(os.path.join(ROOT, "kastr_rtsp.py"), encoding="utf-8") as f:
            src = f.read()
        i = src.index("self._outSize = 0                                            # 0.21.31: this generation has delivered nothing yet")
        self.assertIn("self._vFrames, self._vSeen, self.videoFrames = 0, False, 0", src[i:i + 300])


class VideoWatchdog(unittest.TestCase):
    """Publisher._stall_check: bytes still growing (the sound), the frame count flat."""

    def setUp(self):
        p = mock.patch.object(kastr_rtsp, "SCREEN_STALL_S", 8.0)
        p.start()
        self.addCleanup(p.stop)

    def _video_stuck(self):
        pub, logs = _pub()
        pub._vSeen, pub._vFrames, pub.videoFrames, pub.videoAt = True, 600, 600, 1020.0
        pub.flowingAt = 1039.0   # the sound keeps the output growing
        return pub, logs

    def test_flat_frames_restart_with_their_own_line(self):
        pub, logs = self._video_stuck()
        started = []
        with _threads(started):
            self.assertTrue(pub._stall_check(pub._gen, now=1040.0))
        self.assertEqual(started, ["kastr-capture-stall"])
        self.assertEqual(pub.captureStalls, 1)
        self.assertEqual(pub.lastCaptureStall["kind"], "video")
        self.assertEqual(pub.lastCaptureStall["frames"], 600)
        self.assertEqual(pub.lastCaptureStall["quiet"], 20.0)
        self.assertIn("video stopped -- no new video frame for 20 s while its sound kept flowing (frames flat at 600", logs[-1])
        self.assertIn("freeze #1", logs[-1])

    def test_moving_frames_are_left_alone(self):
        pub, logs = self._video_stuck()
        pub.videoAt = 1038.0
        with mock.patch.object(pub, "_stall_restart") as rs:
            self.assertFalse(pub._stall_check(pub._gen, now=1040.0))
        rs.assert_not_called()
        self.assertEqual(logs, [])

    def test_no_frame_lines_falls_back_to_bytes(self):
        pub, _ = _pub()
        pub.flowingAt = 1039.0   # an encode that never printed frame= (_vSeen False): judged by its bytes as before
        with mock.patch.object(pub, "_stall_restart") as rs:
            self.assertFalse(pub._stall_check(pub._gen, now=1040.0))
        rs.assert_not_called()

    def test_both_flat_is_the_old_capture_froze_line(self):
        pub, logs = _pub()
        pub._vSeen, pub._vFrames, pub.videoAt, pub.flowingAt = True, 300, 1010.0, 1010.0
        with _threads([]):
            self.assertTrue(pub._stall_check(pub._gen, now=1030.0))
        self.assertEqual(pub.lastCaptureStall["kind"], "output")
        self.assertIn("capture froze -- no new picture for 20 s", logs[-1])

    def test_relay_trouble_and_backoff_still_apply(self):
        pub, _ = self._video_stuck()
        pub.lastSessionAt = 1035.0   # moq is fighting its relay link -- not the capture
        with mock.patch.object(pub, "_stall_restart") as rs:
            self.assertFalse(pub._stall_check(pub._gen, now=1040.0))
        rs.assert_not_called()
        pub2, _ = self._video_stuck()
        with _threads([]):
            self.assertTrue(pub2._stall_check(pub2._gen, now=1040.0))
            # the next generation's video is flat too: it waits SCREEN_STALL_BACKOFF[1] s after the last restart
            pub2.since, pub2.videoAt, pub2.flowingAt = 1041.0, None, 1069.0
            self.assertFalse(pub2._stall_check(pub2._gen, now=1060.0))
            self.assertTrue(pub2._stall_check(pub2._gen, now=1071.0))
        self.assertEqual(pub2.captureStalls, 2)

    def test_cameras_and_low_pairs_untouched(self):
        for url, role in (("rtsp://cam/1", "main"), ("screen://window/42", "low")):
            pub, _ = _pub(url=url, role=role)
            pub._vSeen, pub.videoAt, pub.flowingAt = True, 1001.0, 1039.0
            with mock.patch.object(pub, "_stall_restart") as rs:
                self.assertFalse(pub._stall_check(pub._gen, now=1040.0))
            rs.assert_not_called()


@unittest.skipUnless(_ffmpeg(), "no ffmpeg here")
class StuckCaptureReal(unittest.TestCase):
    """The lab, with real ffmpeg and the real clocked graph: a capture branch that stops WITHOUT ending (a TCP rawvideo
    source in gfxcapture's place) while PCM sound keeps arriving on stdin. Its -progress runs through the real _drain; the
    real _stall_check restarts it. Lab finding (ffmpeg 9.0.1): the scheduler holds the sound with the stuck picture, so
    frames AND bytes go flat together -- either clock catches it."""

    W, H, FPS = 160, 90, 30

    def test_stuck_capture_is_restarted(self):
        frame = bytes([16]) * (self.W * self.H) + bytes([128]) * (self.W * self.H // 2)
        srv = socket.socket()
        try:
            srv.bind(("127.0.0.1", 9283))
        except OSError:
            srv.close()
            srv = socket.socket()
            srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        stop = threading.Event()

        def video():
            try:
                c, _ = srv.accept()
            except OSError:
                return
            t0, n = time.time(), 0
            while not stop.is_set():
                if time.time() - t0 < 7.0:   # longer than ffmpeg's input probe (~5 s on Linux)
                    c.sendall(frame)
                    n += 1
                    time.sleep(max(0.0, t0 + n / self.FPS - time.time()))
                else:
                    time.sleep(0.1)   # stuck: open, silent
            c.close()

        cap = (r"movie=filename='tcp\://127.0.0.1\:%d':f=rawvideo:format_opts='video_size=%dx%d\:pixel_format=yuv420p"
               r"\:framerate=%d',format=bgra,scale=%d:%d" % (port, self.W, self.H, self.FPS, self.W, self.H))
        args = ([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-progress", "pipe:2", "-stats_period", "0.5",
                 "-f", "lavfi", "-i", kastr_screen._clocked(cap, self.W, self.H, self.FPS)] + kastr_screen.LOOPBACK_INPUT
                + kastr_rtsp.publish_output_args(False, encoder=None, audio=True, audio_input=1, screen=True))
        threading.Thread(target=video, daemon=True).start()
        ff = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def sink():
            while ff.stdout.read(65536):
                pass

        def sound():
            chunk = b"\x00\x01" * (48000 * 2 // 50)   # 20 ms of stereo s16le
            t0, n = time.time(), 0
            while not stop.is_set():
                try:
                    ff.stdin.write(chunk)
                    ff.stdin.flush()
                except Exception:
                    return
                n += 1
                time.sleep(max(0.0, t0 + n * 0.02 - time.time()))

        pub, logs = _pub()
        pub.since = time.time() + 3600   # armed below, once the picture is in
        for fn in (sink, sound):
            threading.Thread(target=fn, daemon=True).start()
        threading.Thread(target=pub._drain, args=(ff, "ffmpeg", pub._gen), daemon=True).start()
        started, fired_at, frames_at_fire, quiet_at_fire = [], None, None, None
        try:
            with mock.patch.object(kastr_rtsp, "SCREEN_STALL_S", 3.0), _threads(started):
                t0 = time.time()
                while time.time() - t0 < 30 and fired_at is None:
                    time.sleep(0.25)
                    if not pub.videoFrames:
                        continue   # still opening / probing the input
                    if pub.since > time.time():
                        pub.since = time.time()
                    if pub._stall_check(pub._gen):
                        fired_at, frames_at_fire = time.time() - t0, pub.videoFrames
                        quiet_at_fire = time.time() - pub.videoAt
        finally:
            stop.set()
            try:
                ff.stdin.close()
            except Exception:
                pass
            ff.kill()
            ff.wait(timeout=10)
            for pipe in (ff.stdout, ff.stderr):
                try:
                    pipe.close()
                except Exception:
                    pass
            srv.close()
        self.assertIsNotNone(fired_at, "the watchdog never restarted the stuck capture")
        self.assertEqual(started, ["kastr-capture-stall"])
        self.assertGreater(frames_at_fire, 20)        # it streamed first
        self.assertLess(frames_at_fire, 7 * self.FPS + 30)   # and then the clock stopped with the capture
        self.assertGreaterEqual(quiet_at_fire, 2.5)   # flat for the (patched) 3 s threshold before the restart
        self.assertIsNotNone(pub.videoAt)
        self.assertIn(pub.lastCaptureStall["kind"], ("video", "output"))
        self.assertTrue(any("restarting the capture (freeze #1)" in m for m in logs), logs)


class RelayMoveWaitsForShares(unittest.TestCase):
    """The hourly closest-relay move reloads the page: it waits while a screen or window is shared."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
            cls.page = f.read()

    def test_relay_busy_names_it(self):
        i = self.page.index("function relayBusy() {")
        body = self.page[i:self.page.index("\n  }", i)]
        self.assertIn('window.__publisher?.sharingScreen?.()) return "sharing a screen or window"', body)
        self.assertLess(body.index("sharing a screen or window"), body.index('"talking"'))

    def test_publisher_exposes_sharing_screen(self):
        i = self.page.index("window.__publisher = {")
        obj = self.page[i:i + 6000]
        m = re.search(r"sharingScreen: \(\) => \{ try \{ return added\.some\(\(a\) => isScreenShare\(a\)\); \} catch \{ return false; \} \}", obj)
        self.assertIsNotNone(m)
        # the move logs the reason it waits
        self.assertIn('-- the move waits (" + busy + ")"', self.page)


if __name__ == "__main__":
    unittest.main()
