# -*- coding: utf-8 -*-
"""0.21.86 (Kenton: "It still isn't saving position after upgrade. Or restart." -- maximized on the main monitor, KASTR came
back at a default size): Chromium honours --start-maximized only for a normal tabbed window, never an --app window, so the
launcher maximizes its own window once it shows (Windows: ShowWindow; Linux X11: _NET_WM_STATE)."""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr  # noqa: E402
import kastr_x11  # noqa: E402


class Proc:
    def __init__(self, pid=4242, alive=True):
        self.pid, self.alive = pid, alive

    def poll(self):
        return None if self.alive else 0


class Launcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr-win-")
        self.wf = os.path.join(self.tmp, "window.json")
        self.p = mock.patch.object(kastr, "window_file", lambda: self.wf)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save(self, geom):
        with open(self.wf, "w", encoding="utf-8") as f:
            json.dump(geom, f)

    def test_saved_maximized(self):
        self.assertFalse(kastr.saved_maximized())   # nothing saved
        self.save({"x": 0, "y": 0, "w": 1200, "h": 800, "maximized": False})
        self.assertFalse(kastr.saved_maximized())
        self.save({"x": -8, "y": -8, "w": 1936, "h": 1056, "maximized": True})
        self.assertTrue(kastr.saved_maximized())

    def test_only_a_maximized_kastr_window_is_touched(self):
        started = []
        with mock.patch.object(kastr.threading, "Thread", side_effect=lambda **k: started.append(k) or mock.Mock()):
            self.save({"maximized": False, "x": 0, "y": 0, "w": 900, "h": 700})
            kastr._maximize_later(Proc())
            self.assertEqual(started, [])
            self.save({"maximized": True})
            with mock.patch.object(kastr, "USER_BROWSER", [True]), mock.patch.object(kastr, "_PRE_WINDOWS", [None]):
                kastr._maximize_later(Proc())   # the person's own browser without a snapshot: nothing
            self.assertEqual(started, [])
            kastr._maximize_later(Proc())
            self.assertEqual(len(started), 1)
            self.assertIs(started[0]["target"], kastr.maximize_when_shown)
            with mock.patch.object(kastr, "USER_BROWSER", [True]), mock.patch.object(kastr, "_PRE_WINDOWS", [{5}]):
                kastr._maximize_later(Proc())   # 0.21.88: their browser -- only the new KASTR window is placed
            self.assertIs(started[1]["target"], kastr.place_user_window)
            self.assertEqual(started[1]["args"], ({5},))

    def test_waits_for_the_window_then_maximizes_once(self):
        calls = []

        def fake(pid):
            calls.append(pid)
            return 1 if len(calls) >= 3 else 0
        with mock.patch.object(kastr, "WINDOWS", True), mock.patch.object(kastr, "_maximize_windows", side_effect=fake), \
                mock.patch.object(kastr.time, "sleep"), mock.patch.object(kastr, "note") as note:
            kastr.maximize_when_shown(Proc(pid=77))
        self.assertEqual(calls, [77, 77, 77])
        self.assertIn("maximized, as it was", note.call_args[0][0])

    def test_no_browser_holds_the_profile(self):
        with mock.patch.object(kastr, "WINDOWS", True), mock.patch.object(kastr, "_maximize_windows") as mx,                 mock.patch.object(kastr, "_browser_pids_for", return_value=[]), mock.patch.object(kastr.time, "sleep"),                 mock.patch.object(kastr, "note"):
            kastr.maximize_when_shown(Proc(alive=False), limit=0.05, profile="C:/prof")
        mx.assert_not_called()

    def test_a_handed_off_window_is_found_in_the_browser_that_holds_the_profile(self):
        seen = []
        with mock.patch.object(kastr, "WINDOWS", True), mock.patch.object(kastr, "_browser_pids_for", return_value=[900]) as bp,                 mock.patch.object(kastr, "_maximize_windows", side_effect=lambda p: seen.append(p) or 1), mock.patch.object(kastr, "note"):
            kastr.maximize_when_shown(Proc(pid=77, alive=False), profile="C:/prof")
        bp.assert_called_with("C:/prof")
        self.assertEqual(seen, [900])

    def test_launch_wires_it_in(self):
        with open(os.path.join(HERE, "kastr.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertEqual(src.count("            _maximize_later(proc)\n"), 2)   # the bundled browser and a system one


@unittest.skipUnless(sys.platform == "win32", "Windows API")
class WindowsEnum(unittest.TestCase):
    def test_picks_the_chromium_windows_of_that_process(self):
        W = {101: (4242, "Chrome_WidgetWin_1", (0, 0, 1200, 800), True, 0),   # ours
             102: (4242, "Chrome_WidgetWin_1", (0, 0, 120, 40), True, 0),     # a tiny helper window
             103: (999, "Chrome_WidgetWin_1", (0, 0, 1200, 800), True, 0),    # someone else's Chrome
             104: (4242, "Chrome_WidgetWin_2", (0, 0, 300, 300), True, 101),  # an owned pop-up
             105: (4242, "Chrome_WidgetWin_1", (0, 0, 1200, 800), False, 0)}  # hidden
        shown = []

        class U:
            def EnumWindows(self, cb, _):
                for h in W:
                    cb(h, 0)
                return 1

            def IsWindowVisible(self, h):
                return W[h][3]

            def GetWindow(self, h, _):
                return W[h][4]

            def GetWindowThreadProcessId(self, h, ref):
                ref._obj.value = W[h][0]
                return 1

            def GetClassNameW(self, h, buf, n):
                buf.value = W[h][1]
                return len(W[h][1])

            def GetWindowRect(self, h, ref):
                r = ref._obj
                r.left, r.top, r.right, r.bottom = W[h][2]
                return 1

            def IsZoomed(self, h):
                return False

            def ShowWindow(self, h, cmd):
                shown.append((h, cmd))
                return 1
        with mock.patch.object(ctypes.windll, "user32", U()):
            self.assertEqual(kastr._maximize_windows(4242), 1)
        self.assertEqual(shown, [(101, 3)])


class X11(unittest.TestCase):
    def test_asks_the_window_manager_for_both_maximized_states(self):
        sent = []

        class X:
            class XSendEvent:
                restype = argtypes = None

                def __call__(self, dpy, root, prop, mask, ev):
                    e = ev._obj.xclient
                    sent.append((root, mask, e.type, e.window, e.message_type, e.format, list(e.l)))
                    return 1
            XSendEvent = XSendEvent()

            def XFlush(self, dpy):
                return 0

        class D:
            def __init__(self):
                self.x, self.dpy, self.root = X(), 1, 9

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def windows_prop(self, w, name):
                return [11, 12, 13]

            def pid(self, w):
                return {11: 4242, 12: 4242, 13: 5}[w]

            def rect(self, w):
                return {11: {"w": 1200, "viewable": True}, 12: {"w": 1200, "viewable": False}, 13: {"w": 900, "viewable": True}}[w]

            def atom(self, name):
                return {"_NET_WM_STATE": 300, "_NET_WM_STATE_MAXIMIZED_VERT": 301, "_NET_WM_STATE_MAXIMIZED_HORZ": 302}[name]
        with mock.patch.object(kastr_x11, "Display", D):
            self.assertEqual(kastr_x11.maximize_pid(4242), 1)
            self.assertEqual(kastr_x11.maximize_pid(31337), 0)
        self.assertEqual(sent, [(9, (1 << 19) | (1 << 20), 33, 11, 300, 32, [1, 301, 302, 1, 0])])


if __name__ == "__main__":
    unittest.main()


class OwnBrowser(unittest.TestCase):
    """0.21.88 (Kenton: "The window still isn't staying maximized." -- KASTR opens in his own default browser, Brave)."""

    def test_only_the_new_kastr_window_is_placed(self):
        placed = []
        seq = [{1: "KASTR"}, {1: "KASTR", 2: "KASTR"}]
        with mock.patch.object(kastr, "_saved_geom", return_value={"maximized": True}),                 mock.patch.object(kastr, "kastr_windows_now", side_effect=lambda any_size=False: seq.pop(0) if seq else {}),                 mock.patch.object(kastr, "WINDOWS", True), mock.patch.object(kastr, "_win_place", side_effect=lambda h, g: placed.append(h) or "maximized"),                 mock.patch.object(kastr.time, "sleep"), mock.patch.object(kastr, "note"):
            kastr.place_user_window({1}, limit=5)
        self.assertEqual(placed, [2])

    def test_nothing_saved_nothing_touched(self):
        with mock.patch.object(kastr, "_saved_geom", return_value=None), mock.patch.object(kastr, "kastr_windows_now") as kw:
            kastr.place_user_window(set(), limit=1)
        kw.assert_not_called()
        self.assertFalse(kastr.window_geom_ok_launcher({"x": -32000, "y": -32000, "w": 160, "h": 28}))
        self.assertTrue(kastr.window_geom_ok_launcher({"x": 6, "y": 0, "w": 1442, "h": 835}))

    def test_the_snapshot_is_taken_before_the_launch(self):
        with open(os.path.join(HERE, "kastr.py"), encoding="utf-8") as f:
            src = f.read()
        i_snap = src.index("_PRE_WINDOWS[0] = set(kastr_windows_now(any_size=True))")
        i_loop = src.index("    for cand, no_sandbox, label in attempts:")
        self.assertLess(i_snap, i_loop)
