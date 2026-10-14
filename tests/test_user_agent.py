"""0.21.64 (Kenton: the "Update now" button never showed on a desktop client connected through kastr.madlabs.app): Cloudflare
answers Python's default identity "Python-urllib/3.x" with 403 / error 1010, so every request KASTR makes must say KASTR.

Run: python -m unittest discover -s tests
"""
import os
import sys
import unittest
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_ua  # noqa: E402


class UserAgent(unittest.TestCase):
    def test_default_identity_is_kastr(self):
        ua = dict(urllib.request.build_opener().addheaders).get("User-agent", "")
        self.assertTrue(ua.startswith("KASTR/"), ua)
        self.assertNotIn("Python-urllib", ua)

    def test_an_explicit_identity_is_kept(self):
        seen = {}

        class Grab(urllib.request.BaseHandler):
            handler_order = 100   # ahead of the real HTTPHandler
            def http_open(self, req):
                seen["ua"] = req.get_header("User-agent")
                raise urllib.error.URLError("stop")
        op = urllib.request.build_opener(Grab)
        for headers, want in (({}, "KASTR/"), ({"User-Agent": "kastr-fetch"}, "kastr-fetch")):
            try:
                op.open(urllib.request.Request("http://127.0.0.1:9/x", headers=headers), timeout=1)
            except Exception:
                pass
            self.assertTrue(str(seen.get("ua")).startswith(want), seen)

    def test_every_networking_module_imports_it(self):
        for p in ("kastr.py", "kastr_serve.py", "kastr_relay.py", "kastr_browser.py", "kastr_rtsp.py", "kastr_release.py", "kastr_archive.py"):
            with open(os.path.join(HERE, p), encoding="utf-8") as f:
                self.assertIn("import kastr_ua", f.read(), p)


if __name__ == "__main__":
    unittest.main()
