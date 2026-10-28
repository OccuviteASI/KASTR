# -*- coding: utf-8 -*-
"""0.21.92 (Kenton: "add the auto-start KASTR option on startup into the options available to everyone, not just admins"):
the Profile menu's "Start KASTR when I sign in to this computer" + "Start minimized" (the Run key / autostart entry carries
--minimized; that launch's window opens minimized, a restore brings it back maximized when it was). The real HKCU Run key and
the real ~/.config/autostart are never touched here: winreg is a fake, the .desktop path a temp file."""
import ctypes
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr  # noqa: E402
import kastr_serve  # noqa: E402
import kastr_x11  # noqa: E402

EXE = r"C:\Users\someone\AppData\Local\KASTR\KASTR.exe"


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def fake_winreg(store):
    """A winreg with one key: store = {value name: data}."""
    w = types.ModuleType("winreg")
    w.HKEY_CURRENT_USER, w.REG_SZ = object(), 1

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(root, path):
        assert path == r"Software\Microsoft\Windows\CurrentVersion\Run", path
        return Key()

    def QueryValueEx(k, name):
        if name not in store:
            raise FileNotFoundError(name)
        return store[name], 1

    def SetValueEx(k, name, _r, typ, val):
        store[name] = val

    def DeleteValue(k, name):
        if name not in store:
            raise FileNotFoundError(name)
        del store[name]
    w.OpenKey, w.CreateKey, w.QueryValueEx, w.SetValueEx, w.DeleteValue = OpenKey, OpenKey, QueryValueEx, SetValueEx, DeleteValue
    return w


class Base(unittest.TestCase):
    platform = "win32"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr-autorun-")
        self.store = {"OneDrive": r'"C:\OneDrive.exe" /background'}   # someone else's entry: never touched
        self.desk = os.path.join(self.tmp, "autostart", "kastr.desktop")
        ps = [mock.patch.dict(sys.modules, {"winreg": fake_winreg(self.store)}),
              mock.patch.object(sys, "platform", self.platform),
              mock.patch.object(sys, "frozen", True, create=True),
              mock.patch.object(sys, "executable", EXE if self.platform == "win32" else "/opt/kastr/KASTR"),
              mock.patch.object(kastr_serve, "STATE_DIR", os.path.join(self.tmp, "state")),
              mock.patch.object(kastr_serve, "_autorun_desktop", lambda: self.desk)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pref(self):
        with open(os.path.join(self.tmp, "state", "autorun.json"), encoding="utf-8") as f:
            return json.load(f)


class WindowsRunKey(Base):
    def test_off_by_default(self):
        self.assertEqual(kastr_serve.autorun_state(), {"enabled": False, "supported": True, "minimized": False})

    def test_on_minimized_relay_page_and_off(self):
        self.assertEqual(kastr_serve.autorun_set(True), {"ok": True, "enabled": True, "minimized": False})
        self.assertEqual(self.store["KASTR"], '"%s"' % EXE)
        self.assertEqual(kastr_serve.autorun_set(True, True), {"ok": True, "enabled": True, "minimized": True})
        self.assertEqual(self.store["KASTR"], '"%s" --minimized' % EXE)
        self.assertEqual(self.pref(), {"minimized": True})
        self.assertEqual(kastr_serve.autorun_state(), {"enabled": True, "supported": True, "minimized": True})
        # the Relay page's switch names no `minimized`: the saved choice is kept
        kastr_serve.autorun_set(True)
        self.assertEqual(self.store["KASTR"], '"%s" --minimized' % EXE)
        # off removes the entry entirely; the choice stays for the next time it is turned on
        self.assertEqual(kastr_serve.autorun_set(False), {"ok": True, "enabled": False, "minimized": True})
        self.assertNotIn("KASTR", self.store)
        self.assertEqual(kastr_serve.autorun_state(), {"enabled": False, "supported": True, "minimized": True})
        kastr_serve.autorun_set(True)
        self.assertEqual(self.store["KASTR"], '"%s" --minimized' % EXE)
        kastr_serve.autorun_set(True, False)
        self.assertEqual(self.store["KASTR"], '"%s"' % EXE)
        self.assertEqual(self.store["OneDrive"], r'"C:\OneDrive.exe" /background')

    def test_an_existing_entry_is_left_as_it_is(self):
        self.store["KASTR"] = '"%s"' % EXE   # written by 0.8.2 .. 0.21.91
        self.assertEqual(kastr_serve.autorun_state(), {"enabled": True, "supported": True, "minimized": False})
        self.assertEqual(kastr_serve.autorun_flag_fix(True), "")
        self.assertEqual(self.store["KASTR"], '"%s"' % EXE)

    def test_another_exe_is_not_ours(self):
        self.store["KASTR"] = r'"D:\old\KASTR.exe" --minimized'
        self.assertFalse(kastr_serve.autorun_state()["enabled"])

    def test_flag_dropped_before_a_downgrade_and_put_back_after(self):
        kastr_serve.autorun_set(True, True)
        self.assertEqual(kastr_serve.autorun_flag_fix(False), "start minimized flag dropped")
        self.assertEqual(self.store["KASTR"], '"%s"' % EXE)
        self.assertEqual(kastr_serve.autorun_flag_fix(False), "")
        self.assertEqual(kastr_serve.autorun_flag_fix(True), "start minimized flag restored")
        self.assertEqual(self.store["KASTR"], '"%s" --minimized' % EXE)
        self.assertEqual(kastr_serve.autorun_flag_fix(True), "")
        kastr_serve.autorun_set(False)
        self.assertEqual(kastr_serve.autorun_flag_fix(True), "")   # never turns it on
        self.assertNotIn("KASTR", self.store)

    def test_a_flag_the_saved_choice_does_not_know_stays(self):
        self.store["KASTR"] = '"%s" --minimized' % EXE   # no autorun.json (a reset state folder)
        self.assertEqual(kastr_serve.autorun_flag_fix(True), "")
        self.assertEqual(self.store["KASTR"], '"%s" --minimized' % EXE)

    def test_dev_checkout(self):
        with mock.patch.object(sys, "frozen", False):
            self.assertEqual(kastr_serve.autorun_state()["supported"], False)
            self.assertIn("error", kastr_serve.autorun_set(True, True))
            self.assertEqual(kastr_serve.autorun_flag_fix(True), "")
        self.assertNotIn("KASTR", self.store)


class LinuxAutostart(Base):
    platform = "linux"

    def exec_line(self):
        with open(self.desk, encoding="utf-8") as f:
            return [ln for ln in f.read().splitlines() if ln.startswith("Exec=")]

    def test_desktop_entry_carries_the_flag(self):
        self.assertFalse(kastr_serve.autorun_state()["enabled"])
        kastr_serve.autorun_set(True, True)
        self.assertEqual(self.exec_line(), ['Exec="/opt/kastr/KASTR" --minimized'])
        self.assertEqual(kastr_serve.autorun_state(), {"enabled": True, "supported": True, "minimized": True})
        kastr_serve.autorun_set(True)
        self.assertEqual(self.exec_line(), ['Exec="/opt/kastr/KASTR" --minimized'])
        self.assertEqual(kastr_serve.autorun_flag_fix(False), "start minimized flag dropped")
        self.assertEqual(self.exec_line(), ['Exec="/opt/kastr/KASTR"'])
        kastr_serve.autorun_set(False)
        self.assertFalse(os.path.exists(self.desk))


class Endpoint(unittest.TestCase):
    def test_post_passes_minimized_only_when_named(self):
        seen = []
        srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with mock.patch.object(kastr_serve, "autorun_set", side_effect=lambda e, m=None: seen.append((e, m)) or {"ok": True}):
                for body in ({"enabled": True}, {"enabled": True, "minimized": True}, {"enabled": False, "minimized": False}):
                    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
                    c.request("POST", "/api/autorun", body=json.dumps(body), headers={"Content-Type": "application/json"})
                    self.assertEqual(c.getresponse().status, 200)
                    c.close()
                c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
                c.request("POST", "/api/autorun", body=b"{}", headers={"Origin": "https://evil.example"})
                self.assertEqual(c.getresponse().status, 403)
                c.close()
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(seen, [(True, None), (True, True), (False, False)])


class Proc:
    pid = 4242

    def poll(self):
        return None


class Launcher(unittest.TestCase):
    def test_flag_is_taken_out_of_argv(self):
        self.assertEqual(kastr.split_minimized_argv(["--minimized"]), (True, []))
        self.assertEqual(kastr.split_minimized_argv(["--port", "8001", "--minimized"]), (True, ["--port", "8001"]))
        self.assertEqual(kastr.split_minimized_argv(["kastr://join?x=1"]), (False, ["kastr://join?x=1"]))
        self.assertTrue(kastr.build_parser({}).parse_args(["--minimized"]).minimized)   # --help names it
        src = read("kastr.py")
        i = src.index("START_MINIMIZED[0], _rest = split_minimized_argv(_rest)")
        self.assertLess(i, src.index("args = build_parser(ini).parse_args(_rest)"))
        self.assertLess(i, src.index("sys.argv[1:] = _rest", i))   # a relaunch never replays it

    def test_sign_in_launch_minimizes_once(self):
        started = []
        with mock.patch.object(kastr.threading, "Thread", side_effect=lambda **k: started.append(k) or mock.Mock()), \
                mock.patch.object(kastr, "saved_maximized", return_value=True), mock.patch.object(kastr, "START_MINIMIZED", [True]):
            kastr._maximize_later(Proc())
            kastr._maximize_later(Proc())   # a browser relaunch later on: maximized as always
        self.assertIs(started[0]["target"], kastr.minimize_when_shown)
        self.assertIs(started[1]["target"], kastr.maximize_when_shown)

    def test_own_browser_window_is_minimized(self):
        started = []
        with mock.patch.object(kastr.threading, "Thread", side_effect=lambda **k: started.append(k) or mock.Mock()), \
                mock.patch.object(kastr, "USER_BROWSER", [True]), mock.patch.object(kastr, "_PRE_WINDOWS", [{5}]), \
                mock.patch.object(kastr, "START_MINIMIZED", [True]):
            kastr._maximize_later(Proc())
        self.assertIs(started[0]["target"], kastr.place_user_window)
        self.assertEqual((started[0]["args"], started[0]["kwargs"]), (({5},), {"minimize": True}))

    def test_own_browser_minimize_keeps_maximized_for_the_restore(self):
        done = []
        seq = [{1: "KASTR"}, {1: "KASTR", 2: "KASTR"}]
        for geom, want in (({"maximized": True}, True), (None, False)):
            seq[:] = [{1: "KASTR"}, {1: "KASTR", 2: "KASTR"}]
            with mock.patch.object(kastr, "_saved_geom", return_value=geom), mock.patch.object(kastr, "WINDOWS", True), \
                    mock.patch.object(kastr, "kastr_windows_now", side_effect=lambda any_size=False: seq.pop(0) if seq else {}), \
                    mock.patch.object(kastr, "_win_minimize", side_effect=lambda h, m: done.append((h, m)) or True), \
                    mock.patch.object(kastr, "_win_place") as place, mock.patch.object(kastr.time, "sleep"), mock.patch.object(kastr, "note"):
                kastr.place_user_window({1}, limit=5, minimize=True)
            place.assert_not_called()
            self.assertEqual(done.pop(), (2, want))

    def test_waits_for_the_window_then_minimizes(self):
        calls = []
        with mock.patch.object(kastr, "WINDOWS", True), mock.patch.object(kastr, "_starts_maximized", return_value=True), \
                mock.patch.object(kastr, "_minimize_windows", side_effect=lambda p, m: calls.append((p, m)) or (1 if len(calls) > 2 else 0)), \
                mock.patch.object(kastr.time, "sleep"), mock.patch.object(kastr, "note") as note:
            kastr.minimize_when_shown(Proc(), limit=5)
        self.assertEqual(calls, [(4242, True)] * 3)
        self.assertIn("started minimized", note.call_args[0][0])

    def test_wayland_leaves_it_open(self):
        with mock.patch.object(kastr, "WINDOWS", False), mock.patch.object(kastr.sys, "platform", "linux"), \
                mock.patch.object(kastr_x11, "session_kind", return_value="wayland"), \
                mock.patch.object(kastr_x11, "iconify_pid") as ic, mock.patch.object(kastr, "note") as note:
            kastr.minimize_when_shown(Proc(), limit=5)
        ic.assert_not_called()
        self.assertIn("Wayland", note.call_args[0][0])

    def test_placement_minimizes_without_activating_and_restores_maximized(self):
        placed = []

        class U:
            def GetWindowPlacement(self, h, ref):
                ref._obj.flags, ref._obj.showCmd = 0, 1
                return 1

            def IsZoomed(self, h):
                return False

            def SetWindowPlacement(self, h, ref):
                placed.append((h, ref._obj.flags, ref._obj.showCmd))
                return 1

            def IsIconic(self, h):
                return True

            def ShowWindow(self, h, cmd):
                raise AssertionError("not needed")
        with mock.patch.object(ctypes, "windll", types.SimpleNamespace(user32=U()), create=True):   # (Linux has no windll)
            self.assertTrue(kastr._win_minimize(77, True))
            self.assertTrue(kastr._win_minimize(78, False))
        self.assertEqual(placed, [(77, 2, 7), (78, 0, 7)])   # WPF_RESTORETOMAXIMIZED, SW_SHOWMINNOACTIVE

    def test_flag_leaves_before_a_launcher_that_does_not_know_it(self):
        with mock.patch.object(kastr_serve, "autorun_flag_fix", return_value="start minimized flag dropped") as fx, \
                mock.patch.object(kastr, "note"):
            self.assertEqual(kastr.autorun_for_version("0.21.91"), "start minimized flag dropped")
            fx.assert_called_once_with(False)
            fx.reset_mock()
            for v in ("0.21.92", "0.22.0", "1.0.0", ""):
                self.assertEqual(kastr.autorun_for_version(v), "")
            fx.assert_not_called()
        src = read("kastr.py")
        self.assertLess(src.index("autorun_for_version(theirs)   #"), src.index("# 0.21.3: Windows -- a detached helper swaps"))
        self.assertIn("kastr_serve.autorun_flag_fix(True)", src)

    def test_a_sign_in_start_leaves_a_running_kastr_alone(self):
        src = read("kastr.py")
        i = src.index("the sign-in start leaves it as it is")
        self.assertLess(i, src.index("if squatter and same_build(squatter) and not args.no_browser and not relaunched:\n        browser = find_browser()"))


class X11(unittest.TestCase):
    def test_iconify_maximizes_first_then_iconic(self):
        sent = []

        class X:
            class XSendEvent:
                restype = argtypes = None

                def __call__(self, dpy, root, prop, mask, ev):
                    e = ev._obj.xclient
                    sent.append((root, e.window, e.message_type, list(e.l)))
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
                return [11, 13]

            def pid(self, w):
                return {11: 4242, 13: 5}[w]

            def rect(self, w):
                return {"w": 1200, "viewable": True}

            def atom(self, name):
                return {"_NET_WM_STATE": 300, "_NET_WM_STATE_MAXIMIZED_VERT": 301, "_NET_WM_STATE_MAXIMIZED_HORZ": 302,
                        "WM_CHANGE_STATE": 400}[name]
        with mock.patch.object(kastr_x11, "Display", D):
            self.assertEqual(kastr_x11.iconify_pid(4242, maximize=True), 1)
            self.assertEqual(sent, [(9, 11, 300, [1, 301, 302, 1, 0]), (9, 11, 400, [3, 0, 0, 0, 0])])
            sent.clear()
            self.assertTrue(kastr_x11.iconify_xid(13))
            self.assertEqual(sent, [(9, 13, 400, [3, 0, 0, 0, 0])])


class Pages(unittest.TestCase):
    def test_profile_menu_switches(self):
        p = read("moq-watch-lite.html")
        row = p[p.index('id="profBootRow"'):p.index('id="profSave"')]
        self.assertIn('<label class="switch"><input type="checkbox" id="profBoot"><i></i></label><span>Start KASTR when I sign in to this computer</span>', row)
        self.assertIn('<div class="sw" id="profBootMinRow" hidden><label class="switch"><input type="checkbox" id="profBootMin"><i></i></label><span>Start minimized</span>', row)
        self.assertLess(p.index('id="profMainRow"'), p.index('id="profBootRow"'))   # next to Main room
        js = p[p.index("async function bootPaint()"):p.index('document.getElementById("profBootMin").addEventListener')]
        self.assertIn("if (IS_WEB) { row.hidden = true; return; }", js)
        self.assertIn('if (!a || a.error || a.supported === false) { row.hidden = true; return; }', js)
        self.assertIn('document.getElementById("profBootMinRow").hidden = !on;', p)
        self.assertIn('bootSet(e.target.checked, document.getElementById("profBootMin").checked)', p)   # the flag stays
        self.assertIn("bootPaint();   // 0.21.92", p[p.index("function openProfile("):p.index("function closeProfile(")])

    def test_relay_page_stays_in_step(self):
        r = read("relay.html")
        self.assertIn('api("/api/autorun", { enabled: $("bootrun").checked })', r)   # names no `minimized`: the saved choice stays
        self.assertIn('document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") bootPaint(); });', r)


if __name__ == "__main__":
    unittest.main()
