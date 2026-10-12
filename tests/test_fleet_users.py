# -*- coding: utf-8 -*-
"""0.21.50: fleet users on the hub's Relay page (Kenton: "see all of the users ... push an update to the client and see what
version it is. The update push should come from the connected relay, not the hub" + Update buttons that spin until done).
Apps check in with the relay they use; spokes pass their users to the hub; an Update for a spoke's user rides the hub's
command channel down to that spoke, whose next check-in reply tells the app to update from it. Loopback only."""
import os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402


def svc():
    st = kr.AuthStore(tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1")
    return kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)


class CheckIn(unittest.TestCase):
    def setUp(self):
        self.s = svc()
        self.changed = []
        self.s.on_clients = lambda: self.changed.append(1)

    def tearDown(self):
        self.s.close()

    def checkin(self, version="0.21.40", offer="", node="testpc-1a2b"):
        return self.s.client_checkin({"node": node, "version": version, "mode": "full", "platform": "win32", "name": "Test PC", "offer": offer}, "10.0.0.9")

    def test_a_checkin_lists_the_app(self):
        o, c = self.checkin()
        self.assertEqual((c, o), (200, {"ok": True}))
        rows = self.s.clients_view("0.21.50", "relaybox-0001")
        self.assertEqual([(r["node"], r["name"], r["version"], r["kind"], r["checkin"]) for r in rows], [("testpc-1a2b", "Test PC", "0.21.40", "app", True)])
        self.assertTrue(self.changed)   # a new user -> the spoke tells the hub soon

    def test_a_bad_node_is_refused(self):
        o, c = self.s.client_checkin({"node": "no spaces!"}, "10.0.0.9")
        self.assertEqual(c, 400)

    def test_update_handshake(self):
        self.checkin()
        self.assertTrue(self.s.client_pend("testpc-1a2b", "0.21.50"))
        o, _ = self.checkin(offer="asked")
        self.assertEqual(o.get("update"), "0.21.50")            # the next check-in is told
        self.assertEqual(self.s.clients_view("0.21.50")[0]["pending"], "0.21.50")
        o, _ = self.checkin(version="0.21.50")                   # back on the new version
        self.assertNotIn("update", o)
        self.assertEqual(self.s.clients_view("0.21.50")[0]["pending"], "")

    def test_unknown_or_silent_user_cannot_be_asked(self):
        self.assertFalse(self.s.client_pend("ghost-0000", "0.21.50"))
        self.checkin()
        self.s.clients["testpc-1a2b"]["at"] -= self.s.CLIENT_FORGET_S + 5
        self.assertFalse(self.s.client_pend("testpc-1a2b", "0.21.50"))

    def test_sessions_add_web_visitors_and_older_apps(self):
        self.s._sessions["a"] = {"host": "web-1234abcd-12ab", "room": "mendon", "remote": "10.0.0.5", "at": time.time()}
        self.s._sessions["b"] = {"host": "oldpc-9f9f", "room": "main", "remote": "10.0.0.6", "at": time.time()}
        self.s._sessions["c"] = {"host": "relaybox-0001", "room": "main", "remote": "127.0.0.1", "at": time.time()}   # the relay's own machine
        rows = {r["node"]: r for r in self.s.clients_view("0.21.50", "relaybox-0001")}
        self.assertEqual(rows["web-1234abcd-12ab"]["kind"], "web")
        self.assertEqual(rows["web-1234abcd-12ab"]["version"], "0.21.50")   # a web visitor runs its relay's page
        self.assertEqual(rows["web-1234abcd-12ab"]["rooms"], ["mendon"])
        self.assertFalse(rows["oldpc-9f9f"]["checkin"])                     # older than 0.21.50: no version, no Update
        self.assertNotIn("relaybox-0001", rows)


class HubView(unittest.TestCase):
    def setUp(self):
        self.s = svc()

    def tearDown(self):
        self.s.close()

    def test_spoke_users_are_kept_cleaned_and_tagged(self):
        tok = kr._mint(self.s.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))
        bad = [{"node": "testpc-1a2b", "name": "Test PC", "version": "0.21.40", "kind": "app", "checkin": True, "rooms": ["main", "BAD ROOM"], "secret": "x"},
               {"node": "not a node"}]
        o, c = self.s.register_spoke({"name": "mendon-relay", "version": "0.21.48", "clients": bad}, "10.0.0.2", "Bearer " + tok)
        self.assertEqual(c, 200, o)
        rows = self.s.fleet_clients("hub", "0.21.50")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["relay"], r["relayVersion"], r["rooms"]), ("mendon-relay", "0.21.48", ["main"]))
        self.assertNotIn("secret", r)

    def test_update_client_rides_the_command_channel(self):
        tok = kr._mint(self.s.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))
        self.s.register_spoke({"name": "mendon-relay", "version": "0.21.48"}, "10.0.0.2", "Bearer " + tok)
        rec = self.s.raise_cmd("updateClient", {"spoke": "mendon-relay", "node": "testpc-1a2b"})
        d, c = self.s.bans_for_spoke("Bearer " + tok, peer="10.0.0.2")
        self.assertEqual(c, 200)
        self.assertEqual([(x["seq"], x["spoke"], x["node"]) for x in d["cmd"]["updateClient"]], [(rec["seq"], "mendon-relay", "testpc-1a2b")])


class Sources(unittest.TestCase):
    def setUp(self):
        self.src = {n: open(os.path.join(HERE, n), encoding="utf-8").read() for n in ("kastr.py", "kastr_serve.py", "kastr_relay.py", "relay.html", "moq-watch-lite.html")}

    def test_launcher_checks_in_and_updates_from_its_relay(self):
        k = self.src["kastr.py"]
        self.assertIn('req = urllib.request.Request(base + "/api/clients/checkin"', k)
        self.assertIn("box = mode in (\"publisher\", \"publisher-relay\", \"relay\")", k)
        self.assertIn("if box or no_window or time.time() >= off.get(\"deadline\", 0):", k)
        self.assertIn("OFFER_WAIT_S = 600", k)
        self.assertIn("threading.Thread(target=client_checkin_loop, args=(_current_relay, ini, args.port, mode), daemon=True).start()", k)

    def test_the_web_port_forwards_the_checkin(self):
        self.assertIn('"/api/clients/checkin",                              # 0.21.50', self.src["kastr_serve.py"])
        self.assertIn('if path == "/api/update/offer":', self.src["kastr_serve.py"])

    def test_the_window_asks_first(self):
        p = self.src["moq-watch-lite.html"]
        self.assertIn('ok: "Update now", cancel: "In " + mins + " minute"', p)
        self.assertIn('body: JSON.stringify({ answer: now ? "now" : "later" })', p)

    def test_relay_page_spins_until_done(self):
        r = self.src["relay.html"]
        self.assertIn("const UPD_WAIT_MS = 600000;", r)
        self.assertIn('pendStart("spoke:" + sp, d.version, sp);', r)
        self.assertIn('pendStart("user:" + b.dataset.node, b.dataset.ver, b.dataset.label, b.dataset.relay);', r)
        self.assertIn('if (present && version && version === p.target) {', r)
        self.assertIn('<div id="usersBox"', r)

    def test_relay_log_on_disk_and_search(self):
        k = self.src["kastr_relay.py"]
        self.assertIn('self._log_disk(line)   # 0.21.50', k)
        self.assertIn('if path == "/api/relay/logfind":', k)


class LogFind(unittest.TestCase):
    def test_find_reads_both_files_newest_last(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "relay.log.1"), "w", encoding="utf-8") as f:
            f.write("a mikey/camera.hang old\nother\n")
        with open(os.path.join(d, "relay.log"), "w", encoding="utf-8") as f:
            f.write("b MIKEY/camera.hang new\nmore\n")
        r = kr.Relay.__new__(kr.Relay)
        r.state_dir = d
        self.assertEqual(kr.Relay.log_find(r, "mikey/camera"), ["a mikey/camera.hang old", "b MIKEY/camera.hang new"])
        self.assertEqual(kr.Relay.log_find(r, ""), [])


if __name__ == "__main__":
    unittest.main()
