"""0.21.40: KASTR opens in the computer's default browser (own profile, tabs shareable) unless it is a box.

Run: python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kastr          # noqa: E402
import kastr_serve    # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class Choice(unittest.TestCase):
    def setUp(self):
        self._mode, self._pref = kastr_serve.MODE, kastr.BROWSER_PREF
        self.addCleanup(self._restore)

    def _restore(self):
        kastr_serve.MODE, kastr.BROWSER_PREF = self._mode, self._pref
        kastr.USER_BROWSER[0] = False

    def _pick(self, mode="full", relay=False, feeds=False, default="C:/x/brave.exe", pref="auto"):
        kastr_serve.MODE, kastr.BROWSER_PREF = mode, pref
        d = tempfile.mkdtemp()
        if feeds:
            with open(os.path.join(d, "rtsp-feeds.json"), "w") as f:
                f.write('{"feeds": [{"url": "rtsp://cam/1"}]}')
        with mock.patch.object(kastr, "hosts_relay", lambda *a, **k: relay), \
                mock.patch.object(kastr, "state_dir", lambda: d), \
                mock.patch.object(kastr, "default_browser", lambda: default), \
                mock.patch.object(kastr, "bundled_browser", lambda: "C:/kastr/browser/chrome.exe"):
            b = kastr.find_browser()
        return b, kastr.USER_BROWSER[0]

    def test_a_person_gets_their_default_browser(self):
        self.assertEqual(self._pick(), ("C:/x/brave.exe", True))

    def test_boxes_keep_the_kastr_browser(self):
        for kw in ({"mode": "relay"}, {"mode": "publisher-relay"}, {"mode": "publisher"}, {"mode": "viewer"},
                   {"relay": True}, {"feeds": True}):
            b, user = self._pick(**kw)
            self.assertEqual((b, user), ("C:/kastr/browser/chrome.exe", False), kw)

    def test_no_chromium_default_falls_back(self):
        self.assertEqual(self._pick(default=None), ("C:/kastr/browser/chrome.exe", False))

    def test_explicit_ini_choice_wins(self):
        self.assertEqual(self._pick(pref="bundled"), ("C:/kastr/browser/chrome.exe", False))

    def test_user_mode_args_are_only_the_app_window(self):
        kastr.USER_BROWSER[0] = True
        a = kastr.browser_args("C:/x/brave.exe", "http://127.0.0.1:8001", "/moq-watch-lite.html")
        self.assertEqual(len(a), 2)
        self.assertTrue(a[1].startswith("--app=http://127.0.0.1:8001/moq-watch-lite.html?launch="))
        self.assertFalse(any("user-data-dir" in x for x in a))


class Supervise(unittest.TestCase):
    """In the person's own browser only the pages count: the last goodbye ends KASTR, a reload does not."""

    def setUp(self):
        kastr.USER_BROWSER[0] = True
        kastr_serve.PAGES.clear()
        kastr_serve.BYE_AT[0] = 0.0
        self.addCleanup(lambda: (kastr.USER_BROWSER.__setitem__(0, False), kastr_serve.PAGES.clear(),
                                 kastr_serve.BYE_AT.__setitem__(0, 0.0)))
        p = mock.patch.object(kastr, "BYE_GRACE", 0.6)
        p.start()
        self.addCleanup(p.stop)

    def _run(self, script, limit=4.0):
        server = mock.Mock()
        server.alive_ref = [time.monotonic()]
        done = []
        t = threading.Thread(target=lambda: (kastr.supervise(mock.Mock(), server), done.append(time.monotonic())))
        t0 = time.monotonic()
        t.start()
        script(server)
        t.join(limit)
        return (done[0] - t0) if done else None

    def test_last_goodbye_ends(self):
        def s(server):
            kastr_serve.PAGES["a"] = time.monotonic()
            time.sleep(0.3)
            kastr_serve.PAGES.pop("a")
            kastr_serve.BYE_AT[0] = time.monotonic()
        self.assertIsNotNone(self._run(s))

    def test_reload_and_other_page_keep_it(self):
        def s(server):
            kastr_serve.PAGES.update(a=time.monotonic(), relay=time.monotonic())
            time.sleep(0.2)
            kastr_serve.PAGES.pop("a")                     # the window reloads...
            kastr_serve.BYE_AT[0] = time.monotonic()
            time.sleep(0.2)
            kastr_serve.PAGES["b"] = time.monotonic()      # ...and comes back
            kastr_serve.PAGES.pop("relay")                 # the Relay page tab closes
            kastr_serve.BYE_AT[0] = time.monotonic()
        try:
            self.assertIsNone(self._run(s, limit=2.0))
        finally:
            kastr.STOP.set()
            time.sleep(0.7)
            kastr.STOP.clear()

    def test_teardown_never_kills_their_browser(self):
        src = _read("kastr.py")
        body = src[src.index("def teardown("):src.index("def teardown(") + 4000]
        self.assertRegex(body, r"if not USER_BROWSER\[0\]:   # 0\.21\.40: never the person's own browser\r?\n\s+stop_child\(proc, 3\)")


class Page(unittest.TestCase):
    def test_pages_say_goodbye_with_their_id(self):
        js = _read("assets/asi-brand.js")
        self.assertIn('fetch("/api/alive?p=" + pageId', js)
        self.assertIn('addEventListener("pagehide", () => { try { navigator.sendBeacon("/api/alive/bye?p=" + pageId', js)
        self.assertIn("if (r.status === 205) closeSelf();", js)

    def test_server_tracks_pages(self):
        src = _read("kastr_serve.py")
        self.assertIn('if path == "/api/alive/bye":', src)
        self.assertIn("PAGES.pop(", src)


if __name__ == "__main__":
    unittest.main()
