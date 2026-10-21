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


class Seen(unittest.TestCase):   # 0.21.55 (Kenton: hide users not seen for 24 hours, a checkbox shows them)
    def test_an_open_session_is_seen_now_and_keeps_since(self):
        s = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, kr.AuthStore(tempfile.mkdtemp()))
        try:
            started = time.time() - 2 * 86400
            s._sessions["s1"] = {"host": "box-1a2b", "room": "main", "remote": "10.0.0.9", "at": started}
            r = s.clients_view("0.21.55")[0]
            self.assertGreater(r["at"], time.time() - 5)          # connected = seen now (was: the connect time)
            self.assertEqual(r["since"], int(started))
            self.assertEqual(kr.clean_clients([dict(r, kind="app")])[0]["since"], int(started))
        finally:
            s.close()

    def test_the_relay_page_hides_a_day_old_row(self):
        with io.open(os.path.join(HERE, "relay.html"), encoding="utf-8") as f:
            rel = f.read()
        self.assertIn('<span class="switch"><input type="checkbox" id="usersOffline"><i></i></span>', rel)   # 0.21.73: offline users, off by default
        self.assertIn("const isOld = (r) => (!!r.offline || (!!r.at && nowS - r.at > OLD_S)) && !pending.has(\"user:\" + r.node);", rel)
        self.assertIn('localStorage.getItem("kastr.relay.usersOffline") === "1"', rel)


class UpdateAll(unittest.TestCase):   # 0.21.55 (Kenton: "I want an update all users button")
    def test_button_and_who_it_asks(self):
        with io.open(os.path.join(HERE, "relay.html"), encoding="utf-8") as f:
            rel = f.read()
        self.assertIn('<button id="usersUpdateAll" type="button" class="ghost">All users up to date</button>', rel)
        self.assertIn('usersBehind = rows.filter((r) => behind(r) && !isOld(r) && !pending.has("user:" + r.node));', rel)
        self.assertIn('const res = await api("/api/relay/clients/update", { node: r.node, relay: r.relay || "" });', rel)
        self.assertIn('pendStart("user:" + r.node, r.relayVersion || "", r.name || r.node, r.relay || "");', rel)


class Pages(unittest.TestCase):
    def test_the_page_checks_in_and_the_relay_page_shows_the_browser(self):
        with io.open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn('if (joinState === "joined" && /^web-/.test(HOSTNAME1)) {', page)
        self.assertIn('body: JSON.stringify({ node: HOSTNAME1, name: chatName(), version: KASTR_VER, mode: "web", platform: webBrowser(), net: window.__netRate?.() ?? null })', page)   # 0.21.78: + its own rates
        with io.open(os.path.join(HERE, "relay.html"), encoding="utf-8") as f:
            rel = f.read()
        self.assertIn('const machineText = (r) => r.nick || (r.kind === "web" && r.platform ? r.platform : (r.hostname || r.node || ""));', rel)   # 0.21.69: nickname / hostname first


if __name__ == "__main__":
    unittest.main()
