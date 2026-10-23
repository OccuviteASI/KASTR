# -*- coding: utf-8 -*-
"""0.21.84 (Kenton 2026-10-23: "sometimes after an upgrade while launching KASTR, it doesn't hold my same window state").
Two causes: the Relay / stats pages load asi-brand.js too and their windows' bounds overwrote the main window's; and a minimized
window (about -32000, tiny) was saved, so the launcher threw it away and opened maximized."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_serve  # noqa: E402


class ServerGuard(unittest.TestCase):
    def test_minimized_and_junk_refused(self):
        ok = kastr_serve.window_geom_ok
        self.assertFalse(ok({"x": -32000, "y": -32000, "w": 160, "h": 28, "maximized": False}))
        self.assertFalse(ok({"x": 10, "y": 10, "w": 200, "h": 100}))
        self.assertFalse(ok({"x": "a"}))
        self.assertFalse(ok([]))
        self.assertTrue(ok({"x": 100, "y": 50, "w": 1400, "h": 900, "maximized": False}))
        self.assertTrue(ok({"x": -1920, "y": 0, "w": 1280, "h": 800}))        # a monitor left of the main one
        self.assertTrue(ok({"maximized": True, "x": -8, "y": -8, "w": 1936, "h": 1056}))

    def test_post_checks_before_saving(self):
        with open(os.path.join(HERE, "kastr_serve.py"), encoding="utf-8", newline="") as f:
            s = f.read()
        i = s.index("        def _window_post(self):")
        body = s[i:s.index("        def _diag_post(self):", i)]
        self.assertLess(body.index("if not window_geom_ok(geom):"), body.index("os.replace(tmp, window_file)"))


class PageReporter(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "assets", "asi-brand.js"), encoding="utf-8", newline="") as f:
            self.js = f.read()

    def test_only_the_main_window_reports(self):
        self.assertIn("const KASTR_GEOM_PAGE = !/" + chr(92) + "/(relay|stats|rcx|rcx-agent|join)" + chr(92) + ".html$/i.test(location.pathname);", self.js)
        self.assertIn("if (window.top === window && !IS_WEB && KASTR_GEOM_PAGE) {", self.js)

    def test_never_while_minimized_or_hidden(self):
        i = self.js.index("const reportGeometry = () => {")
        body = self.js[i:self.js.index('fetch("/api/window"', i)]
        self.assertIn('if (document.visibilityState === "hidden") return;', body)
        self.assertIn("window.screenX <= -30000", body)
        self.assertIn("window.outerWidth < 320", body)


if __name__ == "__main__":
    unittest.main()
