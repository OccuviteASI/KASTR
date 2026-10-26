# -*- coding: utf-8 -*-
"""0.21.86 (Kenton: "Invite link is using the internal IP of the relay I'm connected to, and not a web address that
anyone can access"): the hub's Relay page sets a public web address (kastr.ini public_url), every spoke learns it with
the hub clock, and the page builds invite links on it with the tunnel's /relay."""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_serve  # noqa: E402


def read(fn):
    with open(os.path.join(HERE, fn), encoding="utf-8") as f:
        return f.read()


class CleanUrl(unittest.TestCase):
    def test_only_https_names(self):
        c = kastr_serve.clean_public_url
        self.assertEqual(c("https://kastr.madlabs.app"), "https://kastr.madlabs.app")
        self.assertEqual(c(" https://KASTR.madlabs.app/ "), "https://kastr.madlabs.app")
        self.assertEqual(c("https://hub.kastr.asirobots.com:8443"), "https://hub.kastr.asirobots.com:8443")
        for bad in ("https://10.0.2.14:8001", "http://kastr.madlabs.app", "https://kastr.madlabs.app/relay", "https://localhost",
                    "kastr.madlabs.app", "https://evil.com\nhttps://x", "https://a b.com", "", None, "javascript:alert(1)"):
            self.assertIsNone(c(bad), bad)


class Endpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kastr-pub-")
        cls.ini = os.path.join(cls.tmp, "kastr.ini")
        cls.p_ini = mock.patch.object(kastr_serve, "_ini_file", lambda: cls.ini)
        cls.p_ini.start()
        cls.srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.p_ini.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        try:
            os.remove(self.ini)
        except OSError:
            pass
        kastr_serve.HUB_PUBLIC[0] = None

    def call(self, path, body=None, remote=False):
        h = {"Content-Type": "application/json"}
        if remote:
            h["X-Forwarded-For"] = "10.1.2.3"
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), headers=h,
                                     data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_set_clear_and_reject(self):
        self.assertEqual(self.call("/api/client")[1].get("publicWeb"), None)
        code, d = self.call("/api/web/public", {"url": "https://kastr.madlabs.app/"})
        self.assertEqual((code, d.get("publicUrl")), (200, "https://kastr.madlabs.app"))
        self.assertEqual(kastr_serve.ini_get("public_url"), "https://kastr.madlabs.app")
        self.assertEqual(self.call("/api/client")[1].get("publicWeb"), "https://kastr.madlabs.app")
        self.assertEqual(self.call("/api/web")[1].get("publicUrl"), "https://kastr.madlabs.app")
        code, d = self.call("/api/web/public", {"url": "http://10.0.2.14:8001"})
        self.assertEqual(code, 400)
        self.assertIn("no IP address", d.get("error", ""))
        self.assertEqual(kastr_serve.ini_get("public_url"), "https://kastr.madlabs.app")   # a bad try keeps the old one
        self.assertEqual(self.call("/api/web/public", {"url": ""})[0], 200)
        self.assertIsNone(kastr_serve.ini_get("public_url"))

    def test_only_this_computer_sets_it(self):
        self.assertNotEqual(self.call("/api/web/public", {"url": "https://evil.example.com"}, remote=True)[0], 200)
        self.assertIsNone(kastr_serve.ini_get("public_url"))

    def test_a_spoke_hands_out_the_hubs_address_unless_it_has_its_own(self):
        kastr_serve.HUB_PUBLIC[0] = "https://kastr.madlabs.app"
        self.assertEqual(self.call("/api/client")[1].get("publicWeb"), "https://kastr.madlabs.app")
        self.assertEqual(self.call("/api/web")[1].get("publicHub"), "https://kastr.madlabs.app")
        kastr_serve.ini_set("public_url", "https://site.example.com")
        self.assertEqual(self.call("/api/client")[1].get("publicWeb"), "https://site.example.com")


class HubClockLearns(unittest.TestCase):
    def tick(self, answer, hub=False):
        rs = mock.Mock()
        rs._cluster_raw.return_value = {"connect": "https://10.0.2.1:4443", "hub": True if hub else None}
        body = json.dumps(dict({"now": 1}, **answer)).encode()

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        with mock.patch.object(kastr_serve, "hub_web_base", return_value="https://10.0.2.1:8443"), \
                mock.patch.object(kastr_serve.urllib.request, "urlopen", side_effect=lambda *a, **k: R(body)):
            kastr_serve.hub_clock_tick(rs)

    def test_spoke_learns_and_validates(self):
        kastr_serve.HUB_PUBLIC[0] = None
        self.tick({"publicWeb": "https://kastr.madlabs.app"})
        self.assertEqual(kastr_serve.HUB_PUBLIC[0], "https://kastr.madlabs.app")
        self.tick({"publicWeb": "http://10.0.2.1:8001"})
        self.assertIsNone(kastr_serve.HUB_PUBLIC[0])
        self.tick({"publicWeb": "https://kastr.madlabs.app"})
        self.tick({}, hub=True)   # this machine is the hub: its own kastr.ini is the only source
        self.assertIsNone(kastr_serve.HUB_PUBLIC[0])


class PageAndRelayPage(unittest.TestCase):
    def test_invite_link_uses_the_public_address_and_its_relay(self):
        p = read("moq-watch-lite.html")
        self.assertIn('const d = await fetch((relayHostBase() || location.origin) + "/api/client", { cache: "no-store" }).then((r) => r.json());', p)
        self.assertIn('encodeURIComponent(pub ? pub + "/relay" : inviteRelayFor(base))', p)
        self.assertIn("    const pub = await publicWebBase();\n    if (pub) return pub;", p.replace("\r\n", "\n"))
        self.assertIn("if (privateLink(link)) window.__toast?.(\"This link uses an address inside your network", p)

    def test_relay_page_field(self):
        r = read("relay.html")
        for s in ('id="pubUrl"', 'id="pubSave"', 'id="pubUse"', 'fetch("/api/web/public"', "pubPaint(w);"):
            self.assertIn(s, r)


if __name__ == "__main__":
    unittest.main()
