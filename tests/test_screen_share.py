"""0.21.20: native screen / window share -- the host-side rules that must not regress.

Run: python -m unittest tests.test_screen_share
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import kastr_rtsp   # noqa: E402


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()

import kastr_screen  # noqa: E402


class Urls(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(kastr_screen.parse_url("screen://monitor/2"), ("monitor", 2))
        self.assertEqual(kastr_screen.parse_url("screen://window/123456"), ("window", 123456))
        for bad in ("screen://monitor/", "screen://window/abc", "screen://disk/1", "screen://monitor/1/../x", "file:///c:/x"):
            with self.assertRaises(ValueError):
                kastr_screen.parse_url(bad)

    def test_is_screen(self):
        self.assertTrue(kastr_rtsp.is_screen("screen://monitor/1"))
        self.assertTrue(kastr_rtsp.is_screen(" SCREEN://window/5"))
        self.assertFalse(kastr_rtsp.is_screen("rtsp://cam/stream"))
        self.assertFalse(kastr_rtsp.is_screen(kastr_rtsp.TEST_URL))

    def test_refused_off_windows(self):
        with mock.patch.object(kastr_screen, "WINDOWS", False):
            with self.assertRaises(ValueError):
                kastr_screen.check_url("screen://monitor/1")
            self.assertFalse(kastr_screen.available())
            self.assertFalse(kastr_screen.sources()["ok"])

    def test_bridge_add_validates(self):
        b = kastr_rtsp.Bridge(state_dir=None, log=lambda *a: None)
        with mock.patch.object(kastr_screen, "check_url", side_effect=ValueError("gone")) as chk:
            with self.assertRaises(ValueError):
                b.add("screen://window/1")
            chk.assert_called_once()


class Tabs(unittest.TestCase):
    def test_tab_urls(self):
        self.assertEqual(kastr_screen.parse_url("screen://tab/4242/3"), ("tab", 4242))
        self.assertEqual(kastr_screen.tab_index("screen://tab/4242/3"), 3)
        for bad in ("screen://tab/4242", "screen://window/1/2", "screen://tab/x/1"):
            with self.assertRaises(ValueError):
                kastr_screen.parse_url(bad)

    def test_tabs_listed_only_on_request(self):
        src = _read("kastr_serve.py")
        self.assertIn('kastr_screen.sources(tabs=(qs.get("tabs") or [""])[0] == "1")', src)
        page = _read("moq-watch-lite.html")
        self.assertIn('"/api/screen/sources" + (shTabOpen ? "?tabs=1" : "")', page)
        self.assertIn("let shTabOpen = false;", page)

    def test_overlay_names_a_tab(self):
        self.assertIn('"tab": "You\'re sharing a tab"', _read("kastr_overlay.py"))


class Security(unittest.TestCase):
    def test_web_clients_never_start_a_screen_share(self):
        b = kastr_rtsp.Bridge(state_dir=None, log=lambda *a: None)
        with self.assertRaises(ValueError) as cm:
            b.remote_add("screen://monitor/1", "main", "x", "web-abc")
        self.assertIn("screen", str(cm.exception))

    def test_picker_routes_are_local_only(self):
        src = _read("kastr_serve.py")
        i = src.index("def _screen_api(self, path):")
        body = src[i:i + 2500]
        self.assertLess(body.index("if not self._local():"), body.index("/api/screen/sources"))
        self.assertIn('"/api/screen/sound"', src)


class Persistence(unittest.TestCase):
    def test_screen_feeds_are_persisted_with_their_identity(self):
        # 0.21.26 (Kenton): "reconnect a desktop, tab, window share when still available after a relaunch"
        b = kastr_rtsp.Bridge(state_dir=None, log=lambda *a: None)
        pub = mock.Mock(stopping=False, broadcast="r/h/o/screen.hang", audio=True, passthrough=False, keep=False,
                        wantOndemand=False, wantLow=False, label="Screen 1")
        pub.feed = mock.Mock(source_url="screen://window/77", added_by="", room="",
                             screen_ident={"kind": "window", "hwnd": 77, "exe": "notepad.exe", "title": "notes"})
        cam = mock.Mock(stopping=False, broadcast="r/h/o/cam.hang", audio=False, passthrough=False, keep=True,
                        wantOndemand=False, wantLow=False, label="Cam")
        cam.feed = mock.Mock(source_url="rtsp://cam/1", added_by="", room="")
        b._pubs = {1: pub, 2: cam}
        recs = {r["url"]: r for r in b._feed_records()}
        self.assertEqual(sorted(recs), ["rtsp://cam/1", "screen://window/77"])
        self.assertTrue(recs["screen://window/77"]["keep"])
        self.assertEqual(recs["screen://window/77"]["screen"]["title"], "notes")


class Relocate(unittest.TestCase):
    """0.21.26: after a relaunch a share comes back only if the thing is still there."""

    def _wins(self, *ws):
        return mock.patch.object(kastr_screen, "_sources_mod", return_value=mock.Mock(list_windows=lambda exclude_pids=(): list(ws)))

    def test_same_window_handle(self):
        with mock.patch.object(kastr_screen, "WINDOWS", True), self._wins({"hwnd": 77, "title": "x", "exe": "a.exe"}):
            self.assertEqual(kastr_screen.relocate("screen://window/77", {"title": "x"}), "screen://window/77")

    def test_reopened_window_found_by_program_and_title(self):
        with mock.patch.object(kastr_screen, "WINDOWS", True), self._wins({"hwnd": 91, "title": "notes", "exe": "Notepad.exe"}):
            self.assertEqual(kastr_screen.relocate("screen://window/77", {"title": "notes", "exe": "notepad.exe"}), "screen://window/91")

    def test_closed_window_is_dropped(self):
        with mock.patch.object(kastr_screen, "WINDOWS", True), self._wins({"hwnd": 5, "title": "other", "exe": "b.exe"}):
            self.assertIsNone(kastr_screen.relocate("screen://window/77", {"title": "notes", "exe": "notepad.exe"}))

    def test_tab_found_by_title_after_it_moved(self):
        tabs = [{"hwnd": 10, "index": 0, "title": "Mail", "browser": "chrome"}, {"hwnd": 10, "index": 3, "title": "Dashboard", "browser": "chrome"}]
        fake_tabs = mock.Mock(list_tabs=mock.Mock(return_value=tabs))   # kastr_tabs is Windows-only: a stand-in on Linux too
        with mock.patch.object(kastr_screen, "WINDOWS", True), mock.patch.dict(sys.modules, {"kastr_tabs": fake_tabs}):
            self.assertEqual(kastr_screen.relocate("screen://tab/10/1", {"title": "Dashboard", "browser": "chrome"}), "screen://tab/10/3")
            self.assertIsNone(kastr_screen.relocate("screen://tab/10/1", {"title": "Closed tab"}))

    def test_restore_drops_what_is_gone(self):
        self.assertIn("is no longer there -- dropped", _read("kastr_rtsp.py"))


class Ffmpeg(unittest.TestCase):
    def test_sound_input_has_no_wallclock_stamps(self):
        # wall-clock stamps put the audio ~50 years ahead of the capture's video (2026-10-06 lab)
        self.assertNotIn("-use_wallclock_as_timestamps", kastr_screen.LOOPBACK_INPUT)
        self.assertEqual(kastr_screen.LOOPBACK_INPUT[-2:], ["-i", "pipe:0"])

    def test_sound_maps_input_one(self):
        args = kastr_rtsp.publish_output_args(False, encoder="libx264", audio=True, audio_input=1, screen=True)
        self.assertIn("1:a:0", args)
        self.assertIn("5M", args)
        cam = kastr_rtsp.publish_output_args(False, encoder="libx264", audio=True)
        self.assertIn("0:a:0?", cam)
        self.assertIn("3M", cam)

    def test_capture_input(self):
        with mock.patch.object(kastr_screen, "_resolve", return_value={"hmonitor": 77, "width": 2880, "height": 1800}),                 mock.patch.object(kastr_screen, "_kick_soon"):
            args = kastr_screen.capture_input("screen://monitor/2")
        self.assertEqual(args[:3], ["-f", "lavfi", "-i"])
        g = args[3]
        self.assertIn("gfxcapture=hmonitor=77", g)
        self.assertIn("width=1728:height=1080", g)   # 2880x1800 fitted into 1920x1080, aspect kept
        self.assertIn("color=c=black:s=1728x1080:r=30", g)   # 0.21.22: a 30 fps clock carries the capture --
        self.assertIn("overlay=eof_action=repeat:repeatlast=1", g)   # a still page / window / screen keeps sending frames
        with mock.patch.object(kastr_screen, "_resolve", return_value={"rect": {"x": 0, "y": 0, "w": 800, "h": 601}}),                 mock.patch.object(kastr_screen, "_kick_soon"):
            g2 = kastr_screen.capture_input("screen://window/99")[3]
        self.assertIn("hwnd=99", g2)
        self.assertIn("width=800:height=600", g2)    # even sizes, never upscaled


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = _read("moq-watch-lite.html")

    def test_screens_join_a_grid_only_when_picked(self):
        # 0.21.26 (Kenton: grids take screens, windows and tabs too) -- but a share starts in "No grid"
        p = self.page
        self.assertIn('function gridIdOf(a) { return String(a?.gridId || (a?.screen ? "none" : "1")); }', p)
        self.assertIn('added.filter((a) => a.kind === RTSP && gridIdOf(a) !== "none" && a.enabled && !a.evicted &&', p)
        self.assertIn('o.value = "none"; o.textContent = "No grid";', p)
        self.assertIn('if (a.url && a.url !== TEST_URL && !isScreenUrl(a.url) && !/^(device|media|rtmp-in):/i.test(a.url)) {', p)   # no pass-through on a capture

    def test_presenter_keeps_its_tracks(self):
        p = self.page
        self.assertIn("if (c && c.peek?.() !== p.track) c.set(p.track);", p)
        self.assertIn("clearInterval(p.timer); clearInterval(p.reattach); clearInterval(p.assert);", p)

    def test_fill_window_reaches_the_shell(self):
        self.assertIn("window.parent.postMessage({ kastrFillWin: fillWin }, location.origin)", self.page)
        app = _read("app.html")
        self.assertIn('typeof e.data.kastrFillWin === "boolean"', app)
        self.assertIn("if (e.origin !== location.origin) return;", app)


if __name__ == "__main__":
    unittest.main()
