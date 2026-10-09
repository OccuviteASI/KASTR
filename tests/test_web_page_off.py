# -*- coding: utf-8 -*-
"""v0.21.32 (Kenton: "I don't have the ability to turn off the web client toggle" -- on a relay box it was locked on,
because the box's web port must stay on the network for spokes). Off now stops handing the PAGE to browsers on other
devices; /api/ routes, the /relay pipe and this computer's own window keep working."""
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_serve  # noqa: E402


class WebPageOff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path, remote):
        h = {"X-Forwarded-For": "10.1.2.3"} if remote else {}
        try:
            with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), headers=h), timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_off_refuses_only_the_page_for_other_devices(self):
        with mock.patch.object(kastr_serve, "_WEB_PAGE_OFF", [True]):
            code, body = self.get("/moq-watch-lite.html", remote=True)
            self.assertEqual(code, 403)
            self.assertIn(b"Web clients are off on this relay", body)
            self.assertEqual(self.get("/", remote=True)[0], 403)
            self.assertEqual(self.get("/api/instance", remote=True)[0], 200)     # KASTR boxes keep the API
            self.assertEqual(self.get("/moq-watch-lite.html", remote=False)[0], 200)   # this computer's window

    def test_on_serves_everyone(self):
        with mock.patch.object(kastr_serve, "_WEB_PAGE_OFF", [False]):
            self.assertEqual(self.get("/moq-watch-lite.html", remote=True)[0], 200)

    def test_relay_page_switch_is_not_locked_on_relays(self):
        with open(os.path.join(HERE, "relay.html"), encoding="utf-8") as f:
            r = f.read()
        self.assertIn('$("webClients").disabled = !LOCAL;', r)
        self.assertNotIn('$("webClients").disabled = !LOCAL || !!w.relayOnly;', r)
        with open(os.path.join(HERE, "kastr_serve.py"), encoding="utf-8") as f:
            s = f.read()
        self.assertIn('if MODE in ("relay", "publisher-relay"):   # 0.21.32: the port stays on the network; only the page goes', s)


if __name__ == "__main__":
    unittest.main()
