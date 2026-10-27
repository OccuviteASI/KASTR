"""0.21.91 -- a whole-screen share froze on one picture (field: the controller saw the sharer's KASTR window, never the apps
they opened). Nothing here captures, lists or touches a real screen: the capture is a finite test source standing in for
gfxcapture, kicks are stubbed, the publisher's processes are fakes."""
import os
import subprocess
import sys
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kastr_rtsp    # noqa: E402
import kastr_screen  # noqa: E402


def _ffmpeg():
    try:
        ff = kastr_rtsp.find_ffmpeg()
    except Exception:
        ff = None
    if ff and os.path.exists(ff):
        return ff
    # a git worktree has no bundled helpers: the main checkout's bin/ (up to 4 levels up)
    d = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _ in range(4):
        d = os.path.dirname(d)
        c = os.path.join(d, "bin", "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


class ClockedEof(unittest.TestCase):
    """kastr_screen._clocked: what happens when the capture ENDS."""

    def test_default_repeats_and_screen_ends(self):
        g = kastr_screen._clocked("testsrc2", 320, 180)
        self.assertIn("overlay=eof_action=repeat:repeatlast=1", g)
        self.assertIn("overlay=eof_action=endall:repeatlast=1", kastr_screen._clocked("testsrc2", 320, 180, eof="endall"))
        self.assertIn("eof_action=repeat", kastr_screen._clocked("testsrc2", 320, 180, eof="bogus"))

    @mock.patch.object(kastr_screen, "LINUX", False)
    def test_monitor_ends_window_and_tab_repeat(self):
        with mock.patch.object(kastr_screen, "_resolve", return_value={"hmonitor": 5, "width": 1920, "height": 1080}), \
                mock.patch.object(kastr_screen, "_kick_soon") as kick:
            g = kastr_screen.capture_input("screen://monitor/1")[3]
        kick.assert_called_once()   # stubbed: a test never moves the real cursor
        self.assertIn("gfxcapture=hmonitor=5", g)
        self.assertIn("eof_action=endall", g)
        with mock.patch.object(kastr_screen, "_resolve", return_value={"rect": {"x": 0, "y": 0, "w": 800, "h": 600}}), \
                mock.patch.object(kastr_screen, "_kick_soon"):
            g2 = kastr_screen.capture_input("screen://window/42")[3]
        self.assertIn("eof_action=repeat", g2)

    @mock.patch.object(kastr_screen, "LINUX", False)
    def test_escape_hatch(self):
        with mock.patch.object(kastr_screen, "MONITOR_EOF", "repeat"), \
                mock.patch.object(kastr_screen, "_resolve", return_value={"hmonitor": 5, "width": 1920, "height": 1080}), \
                mock.patch.object(kastr_screen, "_kick_soon"):
            g = kastr_screen.capture_input("screen://monitor/1")[3]
        self.assertIn("eof_action=repeat", g)


@unittest.skipUnless(_ffmpeg(), "no ffmpeg here")
class ClockedEofReal(unittest.TestCase):
    """The proof, with real ffmpeg: a capture that ends after 1 s (testsrc2 d=1 in gfxcapture's place)."""

    def _run(self, eof):
        cap = "testsrc2=size=320x180:rate=30:duration=1,format=bgra,scale=320:180"
        args = [_ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-progress", "pipe:1", "-f", "lavfi",
                "-i", kastr_screen._clocked(cap, 320, 180, 30, eof=eof), "-t", "5", "-c:v", "rawvideo", "-f", "null", "-"]
        r = subprocess.run(args, capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        frames = [int(x.split("=", 1)[1]) for x in r.stdout.splitlines() if x.startswith("frame=") and x[6:].isdigit()]
        return r.returncode, (frames[-1] if frames else 0), r.stderr

    def test_repeat_freezes_silently(self):
        code, frames, err = self._run("repeat")
        self.assertEqual(code, 0)
        self.assertEqual(frames, 150)   # 4 s of the last frame after the capture ended -- the field's frozen picture
        self.assertEqual(err.strip(), "")   # and not one word at -loglevel error

    def test_endall_ends_with_the_capture(self):
        code, frames, _err = self._run("endall")
        self.assertEqual(code, 0)
        self.assertLessEqual(frames, 31)   # ffmpeg ends with the capture -> the pair restarts it


class _Proc:
    def __init__(self, pid):
        self.pid, self.alive = pid, True

    def poll(self):
        return None if self.alive else 0

    def kill(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


def _pub(url="screen://monitor/1", role="main"):
    logs = []
    bridge = types.SimpleNamespace(_child_ended=lambda pid: None, log=logs.append)
    pub = kastr_rtsp.Publisher(bridge, types.SimpleNamespace(url=url, sar=None, id=1), "room/h/screen.hang", "http://r/",
                               audio=False, role=role)
    pub.running = True
    pub.since = 1000.0
    return pub, logs


class Watchdog(unittest.TestCase):
    """Publisher._stall_check: a screen share's ffmpeg alive, its output not growing."""

    def setUp(self):
        p = mock.patch.object(kastr_rtsp, "SCREEN_STALL_S", 8.0)
        p.start()
        self.addCleanup(p.stop)

    def test_fresh_pair_has_grace(self):
        pub, logs = _pub()
        with mock.patch.object(pub, "_stall_restart") as rs:
            self.assertFalse(pub._stall_check(pub._gen, now=1005.0))
        rs.assert_not_called()
        self.assertEqual(logs, [])

    def test_flowing_pair_is_left_alone(self):
        pub, _ = _pub()
        pub.flowingAt = 1095.0
        with mock.patch.object(pub, "_stall_restart") as rs:
            self.assertFalse(pub._stall_check(pub._gen, now=1100.0))
        rs.assert_not_called()

    def test_frozen_pair_restarts_logged_and_backs_off(self):
        pub, logs = _pub()
        pub.flowingAt = 1010.0
        started = []
        with mock.patch.object(kastr_rtsp.threading, "Thread",
                               side_effect=lambda **kw: types.SimpleNamespace(start=lambda: started.append(kw["name"]))):
            self.assertTrue(pub._stall_check(pub._gen, now=1030.0))
            self.assertEqual(started, ["kastr-capture-stall"])
            self.assertEqual(pub.captureStalls, 1)
            self.assertEqual(pub.lastCaptureStall["quiet"], 20.0)
            self.assertIn("capture froze -- no new picture for 20 s", logs[-1])
            self.assertIn("streamed before", logs[-1])
            self.assertIn("freeze #1", logs[-1])
            # the next generation froze too: it waits SCREEN_STALL_BACKOFF[1] s after the last restart
            pub.since, pub.flowingAt = 1031.0, None
            self.assertFalse(pub._stall_check(pub._gen, now=1045.0))
            self.assertTrue(pub._stall_check(pub._gen, now=1061.0))
            self.assertIn("never streamed", logs[-1])
            self.assertEqual(pub.captureStalls, 2)
        info = pub.info()
        self.assertEqual(info["captureStalls"], 2)
        self.assertEqual(info["lastCaptureStall"]["gen"], pub._gen)

    def test_quiet_minutes_reset_the_backoff(self):
        pub, _ = _pub()
        pub._stallRun, pub._stallAt = 3, 1000.0
        pub.flowingAt = 1200.0
        self.assertFalse(pub._stall_check(pub._gen, now=1201.0))
        self.assertEqual(pub._stallRun, 0)

    def test_not_for_cameras_low_pairs_relay_trouble_or_off(self):
        cam, _ = _pub(url="rtsp://cam/1")
        low, _ = _pub(role="low")
        relay, _ = _pub()
        relay.lastSessionAt = 1025.0
        stopped, _ = _pub()
        stopped.stopping = True
        for p in (cam, low, relay, stopped):
            with mock.patch.object(p, "_stall_restart") as rs:
                self.assertFalse(p._stall_check(p._gen, now=1030.0))
            rs.assert_not_called()
        old, _ = _pub()
        self.assertFalse(old._stall_check(old._gen - 1, now=1030.0))   # an older generation's watcher
        off, _ = _pub()
        with mock.patch.object(kastr_rtsp, "SCREEN_STALL_S", 0):
            self.assertFalse(off._stall_check(off._gen, now=1030.0))

    def test_restart_is_quiet_first_then_nudge(self):
        pub, _ = _pub()
        calls = []
        with mock.patch.object(pub, "quiet", side_effect=lambda: calls.append("quiet") or True), \
                mock.patch.object(pub, "nudge", side_effect=lambda why: calls.append("nudge " + why)):
            pub._stall_restart()
        self.assertEqual(calls, ["quiet", "nudge capture-stall"])

    def test_watch_loop_hands_over(self):
        """_watch returns (no ladder restart of its own) once the watchdog has restarted the capture."""
        pub, _ = _pub()
        ff, mq = _Proc(1), _Proc(2)
        with mock.patch.object(pub, "_stall_check", return_value=True) as sc, \
                mock.patch.object(kastr_rtsp.time, "sleep"), \
                mock.patch.object(pub, "_schedule_restart_locked") as ladder:
            pub._watch(pub._gen, ff, mq)
        sc.assert_called_once()
        ladder.assert_not_called()
        self.assertTrue(pub.running)


class ExitReason(unittest.TestCase):
    def test_screen_capture_ended(self):
        why = kastr_rtsp.screen_exit_reason("screen://monitor/1", "ffmpeg", 0)
        self.assertIn("the screen capture ended", why)
        self.assertEqual(kastr_rtsp.screen_exit_reason("screen://monitor/1", "ffmpeg", 1), "")
        self.assertEqual(kastr_rtsp.screen_exit_reason("screen://monitor/1", "moq", 0), "")
        self.assertEqual(kastr_rtsp.screen_exit_reason("rtsp://cam/1", "ffmpeg", 0), "")
        self.assertEqual(kastr_rtsp.screen_exit_reason("screen://monitor/1", "ffmpeg", None), "")

    def test_watch_logs_it(self):
        pub, logs = _pub()
        ff, mq = _Proc(1), _Proc(2)
        ff.alive = False   # ffmpeg ended with code 0: the capture ended (eof_action=endall)
        with mock.patch.object(pub, "_schedule_restart_locked") as ladder:
            pub._watch(pub._gen, ff, mq)
        ladder.assert_called_once()
        self.assertTrue(any("exit who=ffmpeg code=0 (the screen capture ended" in m for m in logs), logs)
        self.assertIn("the screen capture ended", pub.lastExit["reason"])


if __name__ == "__main__":
    unittest.main()
