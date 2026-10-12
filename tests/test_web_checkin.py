# -*- coding: utf-8 -*-
"""0.21.55 (Kenton: "I need to have a name for web clients that shows in the relay server page"): a web page checks in with
its relay host (name + browser) -- accepted only for a web identity with a live session there. Rig: scratchpad
v02155/pw_webname.py (a visitor through the tunnel stand-in shows as "Dana Webster | Chrome on Windows" on its relay and the hub)."""
import io, os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402


class WebCheckin(unittest.TestCase):
    def setUp(self):
        self.s = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, kr.AuthStore(tempfile.mkdtemp()))

    def tearDown(self):
        self.s.close()

    def test_a_web_identity_needs_a_live_session(self):
        o, c = self.s.client_checkin({"node": "web-1a2b3c4d-5e6f", "name": "Dana"}, "203.0.113.7")
        self.assertEqual((c, o.get("ok")), (200, False))
        self.assertEqual(self.s.clients_view("0.21.55"), [])

    def test_a_web_visitor_is_listed_by_name_and_browser(self):
        self.s._sessions["s1"] = {"host": "web-1a2b3c4d-5e6f", "room": "main", "remote": "203.0.113.7", "at": time.time()}
        o, c = self.s.client_checkin({"node": "web-1a2b3c4d-5e6f", "name": "Dana Webster", "version": "0.21.55", "mode": "web",
                                      "platform": "Chrome on Windows"}, "203.0.113.7")
        self.assertEqual((c, o.get("ok")), (200, True))
        rows = self.s.clients_view("0.21.55")
        self.assertEqual([(r["name"], r["kind"], r["platform"], r["rooms"]) for r in rows], [("Dana Webster", "web", "Chrome on Windows", ["main"])])
        self.assertEqual(kr.clean_clients(rows)[0]["platform"], "Chrome on Windows")   # survives the spoke -> hub hop

    def test_a_revoked_session_does_not_count(self):
        self.s._sessions["s1"] = {"host": "web-1a2b3c4d-5e6f", "room": "main", "at": time.time(), "revoked": True}
        self.assertFalse(self.s.client_checkin({"node": "web-1a2b3c4d-5e6f", "name": "X"}, "")[0].get("ok"))


class Pages(unittest.TestCase):
    def test_the_page_checks_in_and_the_relay_page_shows_the_browser(self):
        with io.open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn('if (joinState === "joined" && /^web-/.test(HOSTNAME1)) {', page)
        self.assertIn('body: JSON.stringify({ node: HOSTNAME1, name: chatName(), version: KASTR_VER, mode: "web", platform: webBrowser() })', page)
        with io.open(os.path.join(HERE, "relay.html"), encoding="utf-8") as f:
            rel = f.read()
        self.assertIn('const machineText = (r) => r.kind === "web" && r.platform ? r.platform : (r.node || "");', rel)


if __name__ == "__main__":
    unittest.main()
