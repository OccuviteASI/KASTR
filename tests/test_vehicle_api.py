# -*- coding: utf-8 -*-
"""v0.21.63 the vehicle API (Kenton: "I need to be able to send a POST request without having to set a room code").
A vehicle API key per vehicle, made on the hub's Relay page (hash only stored, shown once, revocable); POST /api/vehicle
{key, room} mints a publish-only token for <room>/<host> on the relay the vehicle dials, creating the room as a PLAIN room
when it is missing and touching it on every call; a spoke asks the hub about keys it does not hold (federation token) and
caches a good answer for 60 s. Also: register_room makes a code-less, not-kept create a plain room (was 400)."""
import hashlib, json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1"}
SALT = "00112233aabbccdd"


def store(codes=CODES):
    st = kr.AuthStore(tempfile.mkdtemp())
    if codes:
        st.set_codes(**codes)
    return st


def claims_of(jwt, key):
    c = kr.verify_token(jwt, key)
    assert c is not None, "token does not verify"
    return c


class Keys(unittest.TestCase):
    def setUp(self):
        self.st = store()

    def test_create_shape_and_hash_only_storage(self):
        row, key = self.st.vehicle_create("Vehicle 12")
        m = kr.VEHICLE_KEY_RE.match(key)
        self.assertIsNotNone(m, key)
        self.assertEqual(m.group(1), row["id"])
        self.assertEqual(len(m.group(2)), 32)
        self.assertEqual(row["host"], "vehicle-12-" + row["id"][:4])
        self.assertTrue(kr.HOST_RE.match(row["host"]))
        with open(os.path.join(self.st.state_dir, "relay-auth.json"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn(key, text)
        self.assertNotIn(m.group(2), text)
        rec = json.loads(text)["vehicles"][row["id"]]
        self.assertTrue(rec["salt"] and rec["hash"])
        self.assertEqual(rec["name"], "Vehicle 12")
        for r in self.st.vehicles_public():   # the page's rows never carry a secret
            self.assertFalse({"salt", "hash", "key"} & set(r))

    def test_verify_revoke_delete(self):
        row, key = self.st.vehicle_create("Truck")
        self.assertEqual(self.st.vehicle_check(key)[0], "ok")
        self.assertEqual(self.st.vehicle_check(key[:-1] + ("A" if key[-1] != "A" else "B"))[0], "wrong")
        self.assertEqual(self.st.vehicle_check("kv-zzzz")[0], "wrong")
        self.assertEqual(self.st.vehicle_check("")[0], "wrong")
        self.assertTrue(self.st.vehicle_revoke(row["id"])["revoked"])
        self.assertEqual(self.st.vehicle_check(key)[0], "revoked")
        self.assertTrue(self.st.vehicle_delete(row["id"]))
        self.assertEqual(self.st.vehicle_check(key)[0], "wrong")
        self.assertFalse(self.st.vehicle_delete(row["id"]))

    def test_survives_a_restart_and_rejects_blank_or_twin_names(self):
        row, key = self.st.vehicle_create("Loader 3")
        again = kr.AuthStore(self.st.state_dir)
        self.assertEqual(again.vehicle_check(key)[0], "ok")
        self.assertEqual(self.st.vehicle_create("   ")[0], None)
        self.assertEqual(self.st.vehicle_create("loader 3")[0], None)   # one live key per name

    def test_keys_travel_with_a_hub_hand_over(self):
        row, key = self.st.vehicle_create("Hauler")
        other = store(None)
        other.import_bundle(self.st.export_bundle())
        self.assertEqual(other.vehicle_check(key)[0], "ok")
        self.st.vehicle_revoke(row["id"])
        other.merge_bundle(self.st.export_bundle())
        self.assertEqual(other.vehicle_check(key)[0], "revoked")


class OnTheHub(unittest.TestCase):
    def setUp(self):
        self.key = os.urandom(32)
        self.svc = kr.AuthService("127.0.0.1", 0, self.key, 4443, store())
        self.row, self.vkey = self.svc.store.vehicle_create("Vehicle 12")

    def tearDown(self):
        self.svc.close()

    def post(self, body, peer="10.1.1.1"):
        return self.svc.vehicle(body, peer, "http://hub.example:4443/")

    def test_mints_a_publish_only_token_and_creates_a_plain_room(self):
        o, c = self.post({"key": self.vkey, "room": "yard-west"})
        self.assertEqual(c, 200, o)
        host = self.row["host"]
        self.assertEqual((o["room"], o["host"], o["op"]), ("yard-west", host, "vehicle"))
        self.assertEqual(o["prefix"], "yard-west/%s/vehicle/" % host)
        self.assertEqual(o["relay"], "http://hub.example:4443/")
        self.assertEqual(o["connect"], "http://hub.example:4443/?jwt=" + o["jwt"])
        self.assertEqual(o["refreshEvery"], 300)
        self.assertTrue(o["created"])
        cl = claims_of(o["jwt"], self.key)
        self.assertNotIn("get", cl)                               # vehicles do not watch
        self.assertEqual(cl["put"], ["yard-west/" + host, kr.STATE_PREFIX + "/yard-west/" + host, kr.PRESENCE_KIND + "/yard-west"])
        self.assertAlmostEqual(cl["exp"] - cl["iat"], kr.TOKEN_TTL)
        self.assertEqual(o["exp"], cl["exp"])
        g = kr.claims_to_grant(cl)
        self.assertIn("yard-west/%s/**" % host, g["publish"])
        self.assertFalse([s for s in g["subscribe"] if s.startswith("yard-west")])   # only the public kinds
        self.assertEqual(kr.claims_role(cl), "publisher")
        rec = self.svc.store.room("yard-west")
        self.assertTrue(rec and rec.get("plain") and not rec.get("hash"))
        self.assertEqual(rec["creator"], "Vehicle 12")
        row = [r for r in self.svc.store.vehicles_public() if r["id"] == self.row["id"]][0]
        self.assertEqual(row["lastRoom"], "yard-west")
        self.assertTrue(row["lastUsed"])

    def test_every_call_keeps_the_room_alive(self):
        self.post({"key": self.vkey, "room": "yard-west"})
        with self.svc.store.lock:
            self.svc.store.rooms["yard-west"]["at"] = time.time() - (kr.ROOM_TTL - 30)
        o, c = self.post({"key": self.vkey, "room": "yard-west"})
        self.assertEqual(c, 200, o)
        self.assertFalse(o["created"])
        self.assertGreater(self.svc.store.room("yard-west")["at"], time.time() - 5)

    def test_refuses_the_lobby_and_bad_names(self):
        self.assertEqual(self.post({"key": self.vkey, "room": "main"})[1], 403)
        self.assertEqual(self.post({"key": self.vkey, "room": "Bad Room"})[1], 400)
        self.assertIsNone(self.svc.store.room("main"))

    def test_locked_room_needs_its_code(self):
        h = hashlib.sha256((SALT + "gate").encode()).hexdigest()
        kr.register_room(self.svc.store, {"slug": "secret", "salt": SALT, "hash": h, "access": "pub-1"}, "10.0.0.1")
        o, c = self.post({"key": self.vkey, "room": "secret"})
        self.assertEqual(c, 403, o)
        self.assertTrue(o.get("locked"))
        o, c = self.post({"key": self.vkey, "room": "secret", "roomCode": "nope"}, peer="10.1.1.2")
        self.assertEqual(c, 403, o)
        self.assertEqual(self.svc.lockout._fails["10.1.1.2"]["n"], 1)   # a wrong room code is a guess
        o, c = self.post({"key": self.vkey, "room": "secret", "roomCode": "gate"})
        self.assertEqual(c, 200, o)
        self.assertTrue(self.svc.store.room("secret").get("hash"))   # still locked: the vehicle only joined

    def test_wrong_key_counts_toward_the_lockout(self):
        bad = "kv-%s-%s" % (self.row["id"], "A" * 32)
        codes = [self.post({"key": bad, "room": "yard"}, peer="10.9.9.9")[1] for _ in range(5)]
        self.assertEqual(codes[:4], [403] * 4)
        self.assertEqual(codes[4], 429)
        o, c = self.post({"key": self.vkey, "room": "yard"}, peer="10.9.9.9")   # locked out, even with the right key
        self.assertEqual(c, 429, o)
        self.assertIsNone(self.svc.store.room("yard"))

    def test_revoked_key_is_refused_without_counting(self):
        self.svc.store.vehicle_revoke(self.row["id"])
        for _ in range(6):
            o, c = self.post({"key": self.vkey, "room": "yard"}, peer="10.7.7.7")
            self.assertEqual(c, 403, o)
            self.assertEqual(o["error"], "this vehicle key was revoked")
        self.assertIsNone(self.svc.store.room("yard"))

    def test_session_grant_and_kick_identity(self):
        o, _ = self.post({"key": self.vkey, "room": "yard-west"})
        g, c = self.svc.session({"event": "connect", "id": "s1", "remote": "10.1.1.1", "query": "jwt=" + o["jwt"]}, "127.0.0.1")
        self.assertEqual(c, 200, g)
        self.assertIn("yard-west/%s" % o["host"], g["publish"])
        self.assertNotIn("yard-west/**", g["subscribe"])
        self.assertEqual((self.svc._sessions["s1"]["room"], self.svc._sessions["s1"]["host"]), ("yard-west", o["host"]))
        self.assertEqual(kr.claims_identity(claims_of(o["jwt"], self.key)), (None, None))   # not a member at the chat/file doors

    def test_over_http(self):
        import urllib.request
        port = self.svc.httpd.server_address[1]
        req = urllib.request.Request("http://127.0.0.1:%d/api/vehicle" % port, method="POST",
                                     data=json.dumps({"key": self.vkey, "room": "dock"}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read())
        self.assertTrue(d["ok"])
        self.assertEqual(d["relay"], "http://127.0.0.1:4443/")


class RelayUrl(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())

    def tearDown(self):
        self.svc.close()

    def h(self, peer, **headers):
        return mock.Mock(client_address=(peer, 1234), headers=headers)

    def test_direct_and_proxied(self):
        self.assertEqual(self.svc.vehicle_relay_url(self.h("10.0.0.5", Host="hub.example:4444")), "http://hub.example:4443/")
        self.assertEqual(self.svc.vehicle_relay_url(self.h("127.0.0.1", Host="127.0.0.1:4444", **{"X-Kastr-Host": "10.0.0.2:8000",
                                                                                                    "X-Kastr-Via": "web"})),
                         "http://10.0.0.2:4443/")
        self.assertEqual(self.svc.vehicle_relay_url(self.h("127.0.0.1", Host="127.0.0.1:4444", **{"X-Kastr-Host": "kastr.example.com",
                                                                                                    "X-Kastr-Via": "tunnel"})),
                         "https://kastr.example.com/relay")
        # a remote caller cannot steer the URL with the proxy's headers
        self.assertEqual(self.svc.vehicle_relay_url(self.h("10.0.0.5", Host="hub.example:4444", **{"X-Kastr-Host": "evil.example",
                                                                                                     "X-Kastr-Via": "tunnel"})),
                         "http://hub.example:4443/")


class OnASpoke(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke_key = os.urandom(32)
        self.spoke = kr.AuthService("127.0.0.1", 0, self.spoke_key, 4453, store(), hub=lambda: base, fed_token=lambda: fed)
        self.row, self.vkey = self.hub.store.vehicle_create("Vehicle 7")

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def test_the_hub_verifies_and_holds_the_room(self):
        o, c = self.spoke.vehicle({"key": self.vkey, "room": "north-pit"}, "10.2.2.2", "http://spoke.example:4453/")
        self.assertEqual(c, 200, o)
        self.assertTrue(o["created"])
        self.assertEqual(o["relay"], "http://spoke.example:4453/")
        claims_of(o["jwt"], self.spoke_key)                       # a token for the relay the vehicle dials
        rec = self.hub.store.room("north-pit")
        self.assertTrue(rec and rec.get("plain"))                 # created at the hub, like a page's create
        self.assertEqual(rec["creator"], "Vehicle 7")
        self.assertIsNone(self.spoke.store.room("north-pit"))
        row = [r for r in self.hub.store.vehicles_public() if r["id"] == self.row["id"]][0]
        self.assertEqual(row["lastRoom"], "north-pit")

    def test_a_good_answer_is_cached_for_a_minute(self):
        calls = []
        real = self.spoke._hub_fed

        def spy(body, timeout=6):
            calls.append(body.get("op"))
            return real(body, timeout)
        with mock.patch.object(self.spoke, "_hub_fed", side_effect=spy):
            self.assertEqual(self.spoke.vehicle({"key": self.vkey, "room": "north-pit"}, "10.2.2.2")[1], 200)
            self.assertEqual(self.spoke.vehicle({"key": self.vkey, "room": "north-pit"}, "10.2.2.2")[1], 200)
        self.assertEqual(calls.count("vehicle"), 1)
        self.assertEqual(calls.count("touch"), 2)                 # but every call still keeps the room alive at the hub
        self.assertNotIn(self.vkey, json.dumps({k: list(v) for k, v in self.spoke._veh_cache.items()}))

    def test_wrong_and_revoked_keys(self):
        bad = "kv-%s-%s" % (self.row["id"], "B" * 32)
        o, c = self.spoke.vehicle({"key": bad, "room": "north-pit"}, "10.3.3.3")
        self.assertEqual(c, 403, o)
        self.assertEqual(self.spoke.lockout._fails["10.3.3.3"]["n"], 1)   # counted where the vehicle is
        self.hub.store.vehicle_revoke(self.row["id"])
        o, c = self.spoke.vehicle({"key": self.vkey, "room": "north-pit"}, "10.3.3.4")
        self.assertEqual((c, o.get("revoked")), (403, True), o)
        self.assertNotIn("10.3.3.4", self.spoke.lockout._fails)

    def test_hub_locked_room(self):
        h = hashlib.sha256((SALT + "gate").encode()).hexdigest()
        kr.register_room(self.hub.store, {"slug": "secret", "salt": SALT, "hash": h, "access": "pub-1"}, "10.0.0.1")
        self.assertEqual(self.spoke.vehicle({"key": self.vkey, "room": "secret"}, "10.4.4.4")[1], 403)
        self.assertEqual(self.spoke.vehicle({"key": self.vkey, "room": "secret", "roomCode": "x"}, "10.4.4.5")[1], 403)
        self.assertEqual(self.spoke.vehicle({"key": self.vkey, "room": "secret", "roomCode": "gate"}, "10.4.4.6")[1], 200)

    def test_hub_dark_is_503_not_a_wrong_key(self):
        with mock.patch.object(self.spoke, "_hub_fed", return_value=None):
            o, c = self.spoke.vehicle({"key": self.vkey, "room": "north-pit"}, "10.5.5.5")
        self.assertEqual(c, 503, o)
        self.assertNotIn("10.5.5.5", self.spoke.lockout._fails)

    def test_rooms_fed_vehicle_needs_a_federation_token(self):
        self.assertEqual(self.hub.rooms_fed({"op": "vehicle", "key": self.vkey}, None)[1], 403)


class RelayPage(unittest.TestCase):
    def _relay(self, connect="", hub_flag=None):
        r = kr.Relay.__new__(kr.Relay)
        r._cluster_raw = lambda: {"connect": connect, "hub": hub_flag, "code": ""}
        r.store = store()
        r.log = lambda m: None
        r.proc, r.secured, r.port = None, False, 4443
        return r

    def test_hub_manages_keys(self):
        r = self._relay()
        o, c = r.vehicles_op({"op": "create", "name": "Vehicle 12"})
        self.assertEqual(c, 200, o)
        self.assertTrue(kr.VEHICLE_KEY_RE.match(o["key"]))
        view = r.vehicles_view()
        self.assertFalse(view["spoke"])
        self.assertNotIn(o["key"], json.dumps(view))
        self.assertEqual(r.vehicles_op({"op": "revoke", "id": o["vehicle"]["id"]})[1], 200)
        self.assertTrue(r.vehicles_view()["vehicles"][0]["revoked"])
        self.assertEqual(r.vehicles_op({"op": "delete", "id": o["vehicle"]["id"]})[1], 200)
        self.assertEqual(r.vehicles_view()["vehicles"], [])
        self.assertEqual(r.vehicles_op({"op": "nope"})[1], 400)

    def test_a_spoke_points_at_the_hub(self):
        r = self._relay(connect="https://10.0.0.1:4443")
        self.assertTrue(r.vehicles_view()["spoke"])
        o, c = r.vehicles_op({"op": "create", "name": "Vehicle 12"})
        self.assertEqual(c, 409)
        self.assertIn("managed on the hub", o["error"])
        self.assertFalse(self._relay(connect="https://10.0.0.1:4443", hub_flag=True).vehicles_view()["spoke"])

    def test_posts_are_guarded(self):
        self.assertIn("/api/relay/vehicles", kr.GUARDED_POSTS)


class PlainByDefault(unittest.TestCase):
    def test_a_code_less_create_is_a_plain_room(self):
        st = store()
        o, c = kr.register_room(st, {"slug": "yard", "creator": "kenton"}, "10.0.0.1")
        self.assertEqual(c, 200, o)
        rec = st.room("yard")
        self.assertTrue(rec["plain"])
        self.assertEqual(rec["creator"], "kenton")

    def test_a_heartbeat_for_a_gone_record_is_still_refused(self):
        st = store()
        o, c = kr.register_room(st, {"slug": "yard", "roomKey": "ab" * 16}, "10.0.0.1")
        self.assertEqual(c, 400, o)
        self.assertIsNone(st.room("yard"))

    def test_lobby_still_refused(self):
        self.assertEqual(kr.register_room(store(), {"slug": "main"}, "10.0.0.1")[1], 400)


if __name__ == "__main__":
    unittest.main()
