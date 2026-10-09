# -*- coding: utf-8 -*-
"""v0.21.41 "share to several rooms" (Kenton: ONE stream, LISTED in other rooms -- no extra upload), server side.
POST /api/xshare lists a room-A broadcast in other rooms (Bearer = the A member token, one member token per target);
GET /api/xshare?room=B answers the live listings; session() adds them to room-B grants. The hub keeps the registry
(op "xshare" on /api/rooms/fed), spokes mirror it from the bans long-poll (`xshare` + `xshareVer`). Loopback sockets
only (ephemeral ports), no outside network."""
import json, os, sys, tempfile, time, unittest, urllib.error, urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1"}
HOST = "box-1a2b"
PATH = "alpha/box-1a2b/kenton/cam.hang"


def store():
    st = kr.AuthStore(tempfile.mkdtemp())
    st.set_codes(**CODES)
    return st


def mint(svc, room, host=HOST, code="pub-1", peer="10.0.0.7"):
    o, c = svc.token({"room": room, "code": code, "host": host}, peer)
    assert c == 200, o
    return o["tokens"]["member"]


def connect(svc, tok, sid="s1", ev="connect"):
    return svc.session({"event": ev, "id": sid, "remote": "10.0.0.9:5000", "path": "/", "query": "jwt=" + tok}, "127.0.0.1")


class Standalone(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        self.a = mint(self.svc, "alpha")
        self.b = mint(self.svc, "beta")
        self.c = mint(self.svc, "gamma")

    def tearDown(self):
        self.svc.close()

    def post(self, body, tok=None):
        return self.svc.xshare_post(body, "Bearer " + (tok or self.a), "10.0.0.7")

    def share(self, **kw):
        body = {"path": PATH, "to": ["beta"], "tokens": {"beta": self.b}, "label": "Kenton cam", "kind": "camera", "by": "Kenton"}
        body.update(kw)
        return self.post(body)

    def test_list_and_get(self):
        o, c = self.share()
        self.assertEqual(c, 200, o)
        self.assertEqual(o["to"], ["beta"])
        self.assertEqual(o["refused"], {})
        self.assertGreater(o["expires"], time.time() + kr.XSHARE_TTL - 5)
        o, c = self.svc.xshare_get("beta", "Bearer " + self.b, None, "10.0.0.8")
        self.assertEqual(c, 200, o)
        self.assertEqual([(i["path"], i["from"], i["label"], i["kind"], i["by"]) for i in o["items"]],
                         [(PATH, "alpha", "Kenton cam", "camera", "Kenton")])
        o, c = self.svc.xshare_get("gamma", None, self.c, "10.0.0.8")     # ?jwt= works; another room sees nothing
        self.assertEqual((c, o["items"]), (200, []))

    def test_get_needs_a_token_for_that_room_unless_loopback(self):
        self.share()
        self.assertEqual(self.svc.xshare_get("beta", None, None, "10.0.0.8")[1], 403)
        self.assertEqual(self.svc.xshare_get("beta", "Bearer " + self.c, None, "10.0.0.8")[1], 403)
        o, c = self.svc.xshare_get("beta", None, None, "127.0.0.1")
        self.assertEqual((c, len(o["items"])), (200, 1))
        self.assertEqual(self.svc.xshare_get("Bad!", None, None, "127.0.0.1")[1], 400)

    def test_owner_must_own_the_path(self):
        other = mint(self.svc, "alpha", host="other-9f9f")
        o, c = self.post({"path": PATH, "to": ["beta"], "tokens": {"beta": self.b}}, tok=other)
        self.assertEqual(c, 403, o)
        o, c = self.share(path="beta/box-1a2b/kenton/cam.hang")          # a path in another room
        self.assertEqual(c, 403, o)
        for bad in ("alpha/box-1a2b/~state/x.hang", "alpha/box-1a2b/../cam.hang", "alpha/box-1a2b/kenton/cam.json"):
            self.assertEqual(self.share(path=bad)[1], 403, bad)
        viewer = mint(self.svc, "alpha", code="view-1")                     # a viewer token does not publish media
        self.assertEqual(self.post({"path": PATH, "to": ["beta"], "tokens": {"beta": self.b}}, tok=viewer)[1], 403)
        self.assertEqual(self.svc.xshare_post({"path": PATH, "to": ["beta"]}, None, "10.0.0.7")[1], 403)
        self.assertEqual(self.svc.xshare_post({"path": PATH, "to": ["beta"]}, "Bearer junk", "10.0.0.7")[1], 403)

    def test_target_token_must_be_for_that_room(self):
        o, c = self.share(to=["beta", "gamma", "alpha", "Nope!"], tokens={"beta": self.b, "gamma": self.b})
        self.assertEqual(c, 200, o)
        self.assertEqual(o["to"], ["beta"])
        self.assertEqual(set(o["refused"]), {"gamma", "alpha", "Nope!"})
        o, c = self.share(tokens={"beta": "junk"})
        self.assertEqual(c, 403, o)
        o, c = self.share(tokens={"beta": kr._mint(self.svc.key, dict(kr.FEDERATION_CLAIMS, exp=int(time.time()) + 60))})
        self.assertEqual(c, 403, o)                                          # a relay token names no room

    def test_banned_identity_refused(self):
        now = int(time.time())
        self.svc.bans.add({"room": "alpha", "host": HOST, "remotes": [], "target": HOST + "/kenton", "at": now, "until": now + 600})
        o, c = self.share()
        self.assertEqual(c, 403, o)
        self.svc.bans.clear("alpha", HOST)
        self.svc.bans.add({"room": "beta", "host": HOST, "remotes": [], "target": HOST + "/kenton", "at": now, "until": now + 600})
        o, c = self.share()
        self.assertEqual(c, 403, o)
        self.assertIn("beta", o["refused"])

    def test_ttl_expiry(self):
        self.share()
        for e in self.svc._xs("local").items.values():
            e["exp"] = time.time() - 1
        o, _ = self.svc.xshare_get("beta", None, None, "127.0.0.1")
        self.assertEqual(o["items"], [])
        self.assertNotIn(PATH, connect(self.svc, self.b)[0]["subscribe"])

    def test_refresh_keeps_one_entry(self):
        self.share()
        self.share(label="renamed")
        reg = self.svc._xs("local")
        self.assertEqual(len(reg.items), 1)
        self.assertEqual(reg.into("beta")[0]["label"], "renamed")

    def test_stop(self):
        self.share(to=["beta", "gamma"], tokens={"beta": self.b, "gamma": self.c})
        o, c = self.post({"path": PATH, "to": ["gamma"], "stop": True})
        self.assertEqual((c, o["to"]), (200, ["gamma"]))
        self.assertEqual(len(self.svc.xshare_get("beta", None, None, "127.0.0.1")[0]["items"]), 1)
        o, c = self.post({"path": PATH, "stop": True})                       # no targets: every listing of the path
        self.assertEqual((c, o["to"]), (200, ["beta"]))
        self.assertEqual(self.svc.xshare_get("beta", None, None, "127.0.0.1")[0]["items"], [])

    def test_limits(self):
        rooms = ["r%d" % i for i in range(kr.XSHARE_TARGETS_MAX + 2)]
        toks = {r: mint(self.svc, r) for r in rooms}
        o, c = self.share(to=rooms, tokens=toks)
        self.assertEqual(c, 200, o)
        self.assertEqual(len(o["to"]), kr.XSHARE_TARGETS_MAX)
        self.assertEqual(len(o["refused"]), 2)

    def test_session_grant(self):
        self.assertNotIn(PATH, connect(self.svc, self.b)[0]["subscribe"])
        self.share()
        g, code = connect(self.svc, self.b, sid="s2")
        self.assertEqual(code, 200)
        self.assertIn(PATH, g["subscribe"])
        self.assertIn(PATH[:-5] + "-low.hang", g["subscribe"])               # the thumbnail copy rides along
        self.assertNotIn(PATH, connect(self.svc, self.c, sid="s3")[0]["subscribe"])   # room C never
        # a jwt-less revalidate recomputes the listings from the stored room
        rv = lambda: self.svc.session({"event": "revalidate", "id": "s2", "remote": "10.0.0.9:5000"}, "127.0.0.1")[0]
        self.assertIn(PATH, rv()["subscribe"])
        self.post({"path": PATH, "stop": True})
        self.assertNotIn(PATH, rv()["subscribe"])
        self.assertNotIn(PATH, connect(self.svc, self.b, sid="s2", ev="revalidate")[0]["subscribe"])
        self.share()
        self.assertIn(PATH, connect(self.svc, self.b, sid="s2", ev="revalidate")[0]["subscribe"])

    def test_relay_grant_untouched(self):
        self.share()
        fed = kr._mint(self.svc.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))
        self.assertEqual(connect(self.svc, fed)[0]["subscribe"], ["**"])

    def test_http_endpoints(self):
        base = "http://127.0.0.1:%d" % self.svc.httpd.server_address[1]
        body = json.dumps({"path": PATH, "to": ["beta"], "tokens": {"beta": self.b}, "kind": "screen"}).encode()
        req = urllib.request.Request(base + "/api/xshare", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.a})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(json.loads(r.read())["to"], ["beta"])
        with urllib.request.urlopen(base + "/api/xshare?room=beta", timeout=5) as r:   # loopback: no token needed
            self.assertEqual([i["kind"] for i in json.loads(r.read())["items"]], ["screen"])
        with urllib.request.urlopen(base + "/api/xshare?room=beta&jwt=" + self.b, timeout=5) as r:
            self.assertEqual(len(json.loads(r.read())["items"]), 1)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(urllib.request.Request(base + "/api/xshare", data=body, method="POST",
                                                          headers={"Content-Type": "application/json"}), timeout=5)
        self.assertEqual(cm.exception.code, 403)
        cm.exception.close()


class Federation(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: base, fed_token=lambda: self.fed)
        self.a = mint(self.spoke, "alpha")
        self.b = mint(self.spoke, "beta")

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def fed_op(self, bearer, **kw):
        body = {"op": "xshare", "vouch": "member", "path": PATH, "from": "alpha", "host": HOST, "to": ["beta"], "kind": "rtsp"}
        body.update(kw)
        return self.hub.rooms_fed(body, bearer)

    def test_hub_op_needs_the_federation_bearer(self):
        self.assertEqual(self.fed_op(None)[1], 403)
        self.assertEqual(self.fed_op("Bearer " + mint(self.hub, "alpha"))[1], 403)   # a member token is not a relay
        self.assertEqual(self.fed_op("Bearer " + self.fed, vouch=None)[1], 403)
        self.assertEqual(self.fed_op("Bearer " + self.fed, path="alpha/other-1111/x/cam.hang")[1], 400)
        o, c = self.fed_op("Bearer " + self.fed)
        self.assertEqual((c, o["to"]), (200, ["beta"]))
        self.assertEqual(len(self.hub._xs("local").into("beta")), 1)
        o, c = self.fed_op("Bearer " + self.fed, stop=True, to=[])
        self.assertEqual((c, o["to"]), (200, ["beta"]))

    def test_long_poll_carries_registry_and_version(self):
        v0 = self.hub.bans.ver
        p0, _ = self.hub.bans_for_spoke("Bearer " + self.fed)
        self.assertEqual(p0["xshare"], [])
        self.fed_op("Bearer " + self.fed)
        self.assertGreater(self.hub.bans.ver, v0)                            # held long-polls wake
        p1, c = self.hub.bans_for_spoke("Bearer " + self.fed)
        self.assertEqual(c, 200)
        self.assertGreater(p1["xshareVer"], p0["xshareVer"])
        self.assertEqual([(e["path"], e["from"], e["to"]) for e in p1["xshare"]], [(PATH, "alpha", "beta")])

    def test_spoke_forwards_to_the_hub_and_answers_from_the_mirror(self):
        o, c = self.spoke.xshare_post({"path": PATH, "to": ["beta"], "tokens": {"beta": self.b}, "label": "Yard"},
                                      "Bearer " + self.a, "10.0.0.7")
        self.assertEqual((c, o["to"]), (200, ["beta"]), o)
        self.assertNotIn("hubDown", o)
        self.assertEqual(len(self.hub._xs("local").into("beta")), 1)          # the hub holds it
        self.assertEqual(self.spoke._xs("local").items, {})                  # single writer: nothing local
        payload, _ = self.hub.bans_for_spoke("Bearer " + self.fed)
        self.spoke._xs("mirror").items.clear()
        self.spoke.xshare_mirror_apply(payload)
        o, c = self.spoke.xshare_get("beta", "Bearer " + self.b, None, "10.0.0.8")
        self.assertEqual((c, [(i["path"], i["label"]) for i in o["items"]]), (200, [(PATH, "Yard")]))
        self.assertNotIn("hubDown", o)
        self.assertIn(PATH, connect(self.spoke, self.b)[0]["subscribe"])
        # stop forwards too; the next payload empties the copy
        o, c = self.spoke.xshare_post({"path": PATH, "stop": True}, "Bearer " + self.a, "10.0.0.7")
        self.assertEqual((c, o["to"]), (200, ["beta"]))
        self.assertEqual(self.hub._xs("local").into("beta"), [])
        self.spoke.xshare_mirror_apply(self.hub.bans_for_spoke("Bearer " + self.fed)[0])
        self.assertEqual(self.spoke.xshare_get("beta", None, None, "127.0.0.1")[0]["items"], [])

    def test_spoke_mirror_from_payload_only(self):
        payload = {"xshare": [{"path": PATH, "from": "alpha", "to": "beta", "label": "x", "kind": "grid", "by": "k",
                               "exp": int(time.time()) + 100},
                              {"path": "alpha/~state/x.hang", "from": "alpha", "to": "beta", "exp": int(time.time()) + 100},
                              {"path": PATH, "from": "alpha", "to": "gamma", "exp": int(time.time()) - 5}], "xshareVer": 7}
        self.spoke.xshare_mirror_apply(payload)
        o, _ = self.spoke.xshare_get("beta", None, None, "127.0.0.1")
        self.assertEqual([(i["path"], i["kind"]) for i in o["items"]], [(PATH, "grid")])
        self.assertEqual(o["ver"], 7)

    def test_spoke_without_its_hub_keeps_it_locally(self):
        hub = [None]   # tokens first (a spoke's minter asks the hub about room locks), then the hub goes dark
        dead = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4463, store(), hub=lambda: hub[0], fed_token=lambda: self.fed)
        try:
            a, b = mint(dead, "alpha"), mint(dead, "beta")
            hub[0] = "http://127.0.0.1:9"
            o, c = dead.xshare_post({"path": PATH, "to": ["beta"], "tokens": {"beta": b}}, "Bearer " + a, "10.0.0.7")
            self.assertEqual((c, o["to"], o.get("hubDown")), (200, ["beta"], True), o)
            o, _ = dead.xshare_get("beta", None, None, "127.0.0.1")
            self.assertTrue(o.get("hubDown"))
            self.assertEqual(len(o["items"]), 1)
            self.assertIn(PATH, connect(dead, b)[0]["subscribe"])
        finally:
            dead.close()


class OpenRelay(unittest.TestCase):
    def setUp(self):
        kr.XSHARE_OPEN.items.clear()

    def test_open_relay_lists_without_tokens(self):
        o, c = kr.xshare_open("POST", {"from": "alpha", "path": PATH, "to": ["beta", "alpha"], "kind": "media"})
        self.assertEqual((c, o["to"], list(o["refused"])), (200, ["beta"], ["alpha"]))
        o, c = kr.xshare_open("GET", room="beta")
        self.assertEqual((c, [i["kind"] for i in o["items"]]), (200, ["media"]))
        self.assertEqual(kr.xshare_open("POST", {"path": PATH, "to": ["beta"]})[1], 400)            # `from` required
        self.assertEqual(kr.xshare_open("POST", {"from": "beta", "path": PATH, "to": ["gamma"]})[1], 403)   # not that room's
        o, c = kr.xshare_open("POST", {"from": "alpha", "path": PATH, "stop": True})
        self.assertEqual((c, o["to"]), (200, ["beta"]))
        self.assertEqual(kr.xshare_open("GET", room="beta")[0]["items"], [])


if __name__ == "__main__":
    unittest.main()
