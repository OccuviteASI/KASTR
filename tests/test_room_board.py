# -*- coding: utf-8 -*-
"""v0.21.63 the ROOM BOARD (Kenton: "Spotlights are not staying in a room when I add views to a room, spotlight, leave the
room, and come back. The spotlights should stay tied to the room." / "When pinning a feed to a room, does it show for
everyone?"). The hub keeps, in the room record, the feeds pinned to the room and its spotlights; any publisher member
changes them (GET/POST /api/rooms/board); a pin of another room's feed is a permanent cross-room listing. Spokes forward
(op "board") and mirror the boards from the bans long-poll. Loopback sockets only (ephemeral ports), no outside network."""
import hashlib, json, os, sys, tempfile, time, unittest, urllib.error, urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

HOST = "box-1a2b"
A_CAM = "alpha/box-1a2b/kenton/camera.hang"     # a feed of room alpha
B_CAM = "beta/box-1a2b/kenton/camera.hang"      # a feed of room beta
SALT = "00112233aabbccdd"


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def mint(svc, room, host=HOST, code="pub-1", room_code=None):
    body = {"room": room, "code": code, "host": host}
    if room_code is not None:
        body["roomCode"] = room_code
    o, c = svc.token(body, "10.0.0.7")
    assert c == 200, o
    return o["tokens"]["member"]


def connect(svc, tok, sid="s1", ev="connect"):
    return svc.session({"event": ev, "id": sid, "remote": "10.0.0.9:5000", "path": "/", "query": "jwt=" + tok}, "127.0.0.1")


def pin_item(path, label="Cam"):
    return kr.board_item("pin", {"path": path, "label": label, "kind": "camera", "by": "Kenton"})[0]


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.st = store(self.dir)

    def test_board_persists_with_the_room(self):
        b, code, err = self.st.board_apply("beta", "pin", pin_item(A_CAM))
        self.assertEqual((code, err), (200, None))
        self.assertEqual([p["path"] for p in b["pins"]], [A_CAM])
        b, code, _ = self.st.board_apply("beta", "spot", kr.board_item("spot", {"target": B_CAM, "ts": int(time.time() * 1000)})[0])
        self.assertEqual((code, [s["target"] for s in b["spots"]]), (200, [B_CAM]))
        again = kr.AuthStore(self.dir)                       # a restart reads it back
        b2 = again.board("beta")
        self.assertEqual(([p["path"] for p in b2["pins"]], [s["target"] for s in b2["spots"]]), ([A_CAM], [B_CAM]))
        self.assertEqual(b2["pins"][0]["from"], "alpha")
        self.assertEqual(again.boards_public().keys(), {"beta"})

    def test_first_item_keeps_the_room_and_the_last_does_not_unkeep(self):
        self.st.touch_room("beta")                           # a plain room
        self.assertFalse(self.st.room("beta")["persistent"])
        self.st.board_apply("beta", "spot", kr.board_item("spot", {"target": B_CAM})[0])
        rec = self.st.room("beta")
        self.assertTrue(rec["persistent"])
        self.assertNotIn("plain", rec)
        self.st.board_apply("beta", "unspot", {"target": B_CAM})
        self.assertTrue(self.st.room("beta")["persistent"])  # Kenton turns Keep off himself
        row = [r for r in self.st.rooms_public() if r["slug"] == "beta"][0]
        self.assertNotIn("board", row)                       # empty board: no counts

    def test_the_holders_heartbeat_never_unkeeps_a_board_room(self):
        o, c = kr.register_room(self.st, {"slug": "beta", "salt": SALT, "hash": "ab" * 32, "access": "pub-1"}, "10.0.0.1")
        self.assertEqual(c, 200, o)
        self.st.board_apply("beta", "spot", {"target": B_CAM, "ts": 1})
        o, c = kr.register_room(self.st, {"slug": "beta", "salt": SALT, "hash": "ab" * 32, "roomKey": o["roomKey"],
                                          "persistent": False}, "10.0.0.1")   # the page repeats its create-time flag
        self.assertEqual(c, 200, o)
        self.assertTrue(self.st.room("beta")["persistent"])
        self.assertEqual(len(self.st.board("beta")["spots"]), 1)

    def test_a_room_without_a_record_gets_one(self):
        self.assertIsNone(self.st.room("gamma"))
        self.st.board_apply("gamma", "pin", pin_item("gamma/box-1a2b/kenton/screen.hang"))
        self.assertTrue(self.st.room("gamma")["persistent"])
        row = [r for r in self.st.rooms_public() if r["slug"] == "gamma"][0]
        self.assertEqual(row["board"], {"pins": 1, "spots": 0})

    def test_kept_cap_refuses_with_a_clear_error(self):
        old = kr.KEPT_MAX
        kr.KEPT_MAX = 1
        try:
            self.st.board_apply("beta", "pin", pin_item(B_CAM))
            b, code, err = self.st.board_apply("gamma", "pin", pin_item(B_CAM))
            self.assertEqual(code, 409)
            self.assertIn("keeps 1 rooms open", err)
            self.assertIsNone(self.st.room("gamma"))
            self.assertEqual(self.st.board_apply("beta", "pin", pin_item(A_CAM))[1], 200)   # a kept room still takes more
        finally:
            kr.KEPT_MAX = old

    def test_caps(self):
        for i in range(kr.BOARD_PINS_MAX):
            self.assertEqual(self.st.board_apply("beta", "pin", pin_item("beta/box-1a2b/k/cam-%d.hang" % i))[1], 200)
        b, code, err = self.st.board_apply("beta", "pin", pin_item("beta/box-1a2b/k/one-more.hang"))
        self.assertEqual(code, 409)
        self.assertIn("unpin one first", err)
        for i in range(kr.BOARD_SPOTS_MAX):
            self.assertEqual(self.st.board_apply("beta", "spot", {"target": "beta/box-1a2b/k/cam-%d.hang" % i, "ts": 1})[1], 200)
        self.assertEqual(self.st.board_apply("beta", "spot", {"target": "beta/box-1a2b/k/x.hang", "ts": 1})[1], 409)
        self.assertEqual(len(self.st.board("beta")["pins"]), kr.BOARD_PINS_MAX)

    def test_lobby_and_bad_input(self):
        self.assertEqual(self.st.board_apply("main", "pin", pin_item(A_CAM))[1], 403)
        self.assertEqual(self.st.board_apply("Bad!", "pin", pin_item(A_CAM))[1], 400)
        self.assertEqual(self.st.board_apply("beta", "zap", {})[1], 400)
        for bad in ("alpha/~state/x.hang", "alpha/box-1a2b/../cam.hang", "alpha/box-1a2b/cam.json", "main/box-1a2b/k/c.hang"):
            self.assertIsNotNone(kr.board_item("pin", {"path": bad})[1], bad)
        self.assertIsNotNone(kr.board_item("pin", {"path": A_CAM, "from": "beta"})[1])   # `from` must be the path's room

    def test_spot_of_another_rooms_feed_needs_its_pin_and_unpin_takes_it(self):
        b, code, err = self.st.board_apply("beta", "spot", {"target": A_CAM, "ts": 5})
        self.assertEqual(code, 409)
        self.assertIn("pin it", err)
        self.st.board_apply("beta", "pin", pin_item(A_CAM))
        self.assertEqual(self.st.board_apply("beta", "spot", {"target": A_CAM, "ts": 5})[1], 200)
        b, code, _ = self.st.board_apply("beta", "unpin", {"path": A_CAM})
        self.assertEqual((b["pins"], b["spots"]), ([], []))

    def test_newer_spot_moves_the_time_and_spot_ts_is_clamped(self):
        now = time.time()
        it = kr.board_item("spot", {"target": B_CAM, "ts": 5}, now)[0]   # a day off -> now
        self.assertAlmostEqual(it["ts"] / 1000, now, delta=2)
        self.st.board_apply("beta", "spot", {"target": B_CAM, "ts": 1000, "by": "a"})
        self.st.board_apply("beta", "spot", {"target": B_CAM, "ts": 2000, "by": "b"})
        self.st.board_apply("beta", "spot", {"target": B_CAM, "ts": 1500, "by": "c"})   # older: no change
        self.assertEqual([(s["ts"], s["by"]) for s in self.st.board("beta")["spots"]], [(2000, "b")])

    def test_a_heartbeat_never_overwrites_the_board(self):
        self.st.board_apply("beta", "pin", pin_item(B_CAM))
        stale = self.st.room("beta")
        stale["board"] = {"pins": [], "spots": []}
        self.st.put_room("beta", stale)
        self.assertEqual(len(self.st.board("beta")["pins"]), 1)

    def test_close_removes_the_board_and_fires(self):
        fired = []
        self.st.on_board = lambda: fired.append(1)
        self.st.board_apply("beta", "pin", pin_item(A_CAM))
        self.assertEqual(len(fired), 1)
        kr.close_room(self.st, "beta", operator=True)
        self.assertEqual(len(fired), 2)
        self.assertEqual(self.st.board("beta"), {"pins": [], "spots": [], "grids": {}, "split": []})   # 0.21.64: + grids; 0.21.65: + split
        self.assertEqual(self.st.boards_public(), {})


class Service(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        self.a = mint(self.svc, "alpha")
        self.b = mint(self.svc, "beta")

    def tearDown(self):
        self.svc.close()

    def post(self, body, tok=None):
        return self.svc.board_post(body, "Bearer " + (tok or self.b), "10.0.0.7")

    def test_pin_and_get(self):
        o, c = self.post({"room": "beta", "op": "pin", "path": B_CAM, "label": "Kenton cam", "kind": "camera"})
        self.assertEqual(c, 200, o)
        self.assertEqual([p["path"] for p in o["pins"]], [B_CAM])
        self.assertEqual(o["pins"][0]["by"], "box-1a2b")      # no `by` sent: the token's host
        g, c = self.svc.board_get("beta", "Bearer " + self.b, None, "10.0.0.8")
        self.assertEqual((c, [p["label"] for p in g["pins"]], g["spots"]), (200, ["Kenton cam"], []))
        self.assertIn("ver", g)
        self.assertEqual(self.svc.board_get("beta", None, None, "10.0.0.8")[1], 403)            # no token, not loopback
        self.assertEqual(self.svc.board_get("beta", "Bearer " + self.a, None, "10.0.0.8")[1], 403)   # another room's token
        self.assertEqual(self.svc.board_get("beta", None, None, "127.0.0.1")[1], 200)           # the relay box's own page
        self.assertEqual(self.svc.board_get("beta", None, self.b, "10.0.0.8")[1], 200)          # ?jwt=

    def test_only_publishers_of_that_room(self):
        viewer = mint(self.svc, "beta", host="watch-9f9f", code="view-1")
        o, c = self.post({"room": "beta", "op": "spot", "target": B_CAM}, tok=viewer)
        self.assertEqual(c, 403, o)
        self.assertIn("viewers", o["error"])
        o, c = self.post({"room": "beta", "op": "spot", "target": B_CAM}, tok=self.a)   # an alpha token in beta
        self.assertEqual(c, 403, o)
        self.assertEqual(self.svc.board_post({"room": "beta", "op": "spot", "target": B_CAM}, None, "10.0.0.7")[1], 403)
        self.assertEqual(self.svc.board_post({"room": "beta", "op": "spot", "target": B_CAM}, "Bearer junk", "10.0.0.7")[1], 403)
        lobby = mint(self.svc, "main")
        self.assertEqual(self.post({"room": "main", "op": "spot", "target": B_CAM}, tok=lobby)[1], 403)
        fed = kr._mint(self.svc.key, dict(kr.FEDERATION_CLAIMS, exp=int(time.time()) + 60))
        self.assertEqual(self.post({"room": "beta", "op": "spot", "target": B_CAM}, tok=fed)[1], 403)

    def test_banned_member_refused(self):
        now = int(time.time())
        self.svc.bans.add({"room": "beta", "host": HOST, "remotes": [], "target": HOST + "/kenton", "at": now, "until": now + 600})
        self.assertEqual(self.post({"room": "beta", "op": "spot", "target": B_CAM})[1], 403)

    def test_cross_room_pin_needs_the_from_rooms_token(self):
        o, c = self.post({"room": "beta", "op": "pin", "path": A_CAM})
        self.assertEqual(c, 403, o)
        self.assertIn("member token for alpha", o["error"])
        gamma = mint(self.svc, "gamma")
        self.assertEqual(self.post({"room": "beta", "op": "pin", "path": A_CAM, "tokens": {"alpha": gamma}})[1], 403)
        self.assertEqual(self.post({"room": "beta", "op": "pin", "path": A_CAM, "tokens": {"alpha": "junk"}})[1], 403)
        o, c = self.post({"room": "beta", "op": "pin", "path": A_CAM, "from": "alpha", "tokens": {"alpha": self.a}})
        self.assertEqual(c, 200, o)

    def test_a_locked_rooms_feed_needs_the_admin_unless_it_is_mine(self):
        kr.register_room(self.svc.store, {"slug": "alpha", "salt": SALT, "hash": hashlib.sha256((SALT + "right").encode()).hexdigest(),
                                          "access": "pub-1"}, "10.0.0.1")
        other = mint(self.svc, "alpha", host="watch-9f9f", room_code="right")   # a plain member of the lock, another machine
        o, c = self.post({"room": "beta", "op": "pin", "path": A_CAM, "tokens": {"alpha": other}})
        self.assertEqual(c, 403, o)
        self.assertIn("admin", o["error"])
        mine = mint(self.svc, "alpha", room_code="right")                       # the feed's own machine
        self.assertEqual(self.post({"room": "beta", "op": "pin", "path": A_CAM, "tokens": {"alpha": mine}})[1], 200)
        self.post({"room": "beta", "op": "unpin", "path": A_CAM})
        adm = mint(self.svc, "alpha", host="boss-1111", code="adm-1", room_code="right")
        self.assertEqual(self.post({"room": "beta", "op": "pin", "path": A_CAM, "tokens": {"alpha": adm}})[1], 200)

    def pin_alpha(self):
        o, c = self.post({"room": "beta", "op": "pin", "path": A_CAM, "label": "Yard", "tokens": {"alpha": self.a}})
        self.assertEqual(c, 200, o)

    def test_pinned_feed_is_a_permanent_listing_and_granted(self):
        self.assertNotIn(A_CAM, connect(self.svc, self.b)[0]["subscribe"])
        self.pin_alpha()
        o, _ = self.svc.xshare_get("beta", "Bearer " + self.b, None, "10.0.0.8")
        self.assertEqual([(i["path"], i["from"], i["label"], i["pinned"]) for i in o["items"]], [(A_CAM, "alpha", "Yard", True)])
        self.assertGreater(o["items"][0]["exp"], time.time() + kr.XSHARE_TTL * 2)        # long-lived, re-applied by the board
        self.assertIn(A_CAM, connect(self.svc, self.b, sid="s2")[0]["subscribe"])
        # the sharer's own stop leaves the pin listed
        self.svc.xshare_post({"path": A_CAM, "stop": True}, "Bearer " + self.a, "10.0.0.7")
        self.assertEqual(len(self.svc.xshare_get("beta", None, None, "127.0.0.1")[0]["items"]), 1)
        # gone from the registry (a restart): the board puts it back
        self.svc._xs("local").items.clear()
        self.assertTrue(self.svc.board_sync())
        self.assertEqual(len(self.svc.xshare_get("beta", None, None, "127.0.0.1")[0]["items"]), 1)
        # unpin: listing and grant go
        o, c = self.post({"room": "beta", "op": "unpin", "path": A_CAM})
        self.assertEqual((c, o["pins"]), (200, []))
        self.assertEqual(self.svc.xshare_get("beta", None, None, "127.0.0.1")[0]["items"], [])
        self.assertNotIn(A_CAM, connect(self.svc, self.b, sid="s2", ev="revalidate")[0]["subscribe"])

    def test_unpin_leaves_a_listing_its_sharer_still_heartbeats(self):
        self.svc.xshare_post({"path": A_CAM, "to": ["beta"], "tokens": {"beta": self.b}, "label": "Shared"}, "Bearer " + self.a, "10.0.0.7")
        self.pin_alpha()
        items = self.svc.xshare_get("beta", None, None, "127.0.0.1")[0]["items"]
        self.assertEqual([(i["label"], i["pinned"]) for i in items], [("Shared", True)])   # one entry; the sharer's label
        self.post({"room": "beta", "op": "unpin", "path": A_CAM})
        items = self.svc.xshare_get("beta", None, None, "127.0.0.1")[0]["items"]
        self.assertEqual([(i["pinned"], i["exp"] <= time.time() + kr.XSHARE_TTL + 2) for i in items], [(False, True)])

    def test_spot_unspot_and_own_room_pins_need_no_listing(self):
        o, c = self.post({"room": "beta", "op": "pin", "path": B_CAM})
        self.assertEqual(c, 200, o)
        self.assertEqual(self.svc.xshare_get("beta", None, None, "127.0.0.1")[0]["items"], [])
        o, c = self.post({"room": "beta", "op": "spot", "target": B_CAM, "ts": int(time.time() * 1000)})
        self.assertEqual((c, [s["target"] for s in o["spots"]]), (200, [B_CAM]))
        o, c = self.post({"room": "beta", "op": "spot", "target": A_CAM})
        self.assertEqual(c, 409, o)                                                   # another room's feed: pin it first
        o, c = self.post({"room": "beta", "op": "unspot", "target": B_CAM})
        self.assertEqual((c, o["spots"]), (200, []))
        self.assertEqual(self.post({"room": "beta", "op": "bogus", "target": B_CAM})[1], 400)

    def test_room_close_removes_board_and_listing(self):
        self.pin_alpha()
        self.assertEqual(len(self.svc._xs("local").into("beta")), 1)
        kr.close_room(self.svc.store, "beta", operator=True)
        self.assertEqual(self.svc._xs("local").into("beta"), [])
        self.assertEqual(self.svc.board_get("beta", None, None, "127.0.0.1")[0]["pins"], [])

    def test_http_endpoints(self):
        base = "http://127.0.0.1:%d" % self.svc.httpd.server_address[1]
        body = json.dumps({"room": "beta", "op": "spot", "target": B_CAM}).encode()
        req = urllib.request.Request(base + "/api/rooms/board", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.b})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual([s["target"] for s in json.loads(r.read())["spots"]], [B_CAM])
        with urllib.request.urlopen(base + "/api/rooms/board?room=beta", timeout=5) as r:   # loopback: no token needed
            self.assertEqual(len(json.loads(r.read())["spots"]), 1)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(urllib.request.Request(base + "/api/rooms/board", data=body, method="POST",
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

    def test_hub_op_needs_federation_and_vouch(self):
        body = {"op": "board", "vouch": "publisher", "room": "beta", "act": "spot", "item": {"target": B_CAM}}
        self.assertEqual(self.hub.rooms_fed(body, None)[1], 403)
        self.assertEqual(self.hub.rooms_fed(body, "Bearer " + mint(self.hub, "beta"))[1], 403)
        self.assertEqual(self.hub.rooms_fed(dict(body, vouch=None), "Bearer " + self.fed)[1], 403)
        self.assertEqual(self.hub.rooms_fed(dict(body, item={"target": "beta/~state/x.hang"}), "Bearer " + self.fed)[1], 400)
        o, c = self.hub.rooms_fed(body, "Bearer " + self.fed)
        self.assertEqual((c, [s["target"] for s in o["spots"]]), (200, [B_CAM]))

    def test_spoke_forwards_mirrors_and_grants(self):
        v0 = self.hub.bans.ver
        o, c = self.spoke.board_post({"room": "beta", "op": "pin", "path": A_CAM, "label": "Yard", "tokens": {"alpha": self.a}},
                                     "Bearer " + self.b, "10.0.0.7")
        self.assertEqual(c, 200, o)
        self.assertEqual([p["path"] for p in self.hub.store.board("beta")["pins"]], [A_CAM])   # the hub holds it
        self.assertEqual(self.spoke.store.boards_public(), {})                                # single writer
        self.assertTrue(self.hub.store.room("beta")["persistent"])
        self.assertGreater(self.hub.bans.ver, v0)                                             # held long-polls wake
        payload, code = self.hub.bans_for_spoke("Bearer " + self.fed)
        self.assertEqual(code, 200)
        self.assertEqual(list(payload["boards"]), ["beta"])
        self.assertTrue(str(payload["boardsVer"]).endswith(".%d" % self.hub.store.board_ver))
        self.assertEqual([(e["path"], e["to"], e["pinned"]) for e in payload["xshare"]], [(A_CAM, "beta", True)])
        # a fresh spoke copy: from the long-poll payload only
        self.spoke._board_mirror = {}
        self.spoke._xs("mirror").items.clear()
        self.spoke.board_mirror_apply(payload)
        self.spoke.xshare_mirror_apply(payload)
        g, c = self.spoke.board_get("beta", "Bearer " + self.b, None, "10.0.0.8")
        self.assertEqual((c, [p["label"] for p in g["pins"]]), (200, ["Yard"]))
        self.assertNotIn("hubDown", g)
        self.assertIn(A_CAM, connect(self.spoke, self.b)[0]["subscribe"])
        self.assertEqual(len(self.spoke._xs("local").into("beta")), 1)   # kept locally too, for when the hub is dark
        # the spoke restarts: its copy comes back from disk
        again = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4463, self.spoke.store, hub=lambda: None)
        try:
            self.assertEqual(list(again._board_mirror), ["beta"])
        finally:
            again.close()
        # unpin forwards too; the next payload empties the copy and the listing
        o, c = self.spoke.board_post({"room": "beta", "op": "unpin", "path": A_CAM}, "Bearer " + self.b, "10.0.0.7")
        self.assertEqual((c, o["pins"]), (200, []))
        self.spoke.board_mirror_apply(self.hub.bans_for_spoke("Bearer " + self.fed)[0])
        self.assertEqual(self.spoke.board_get("beta", None, None, "127.0.0.1")[0]["pins"], [])
        self.assertEqual(self.spoke._xs("local").into("beta"), [])

    def test_spoke_checks_the_member_itself(self):
        viewer = mint(self.spoke, "beta", host="watch-9f9f", code="view-1")
        self.assertEqual(self.spoke.board_post({"room": "beta", "op": "spot", "target": B_CAM}, "Bearer " + viewer, "10.0.0.7")[1], 403)
        o, c = self.spoke.board_post({"room": "beta", "op": "pin", "path": A_CAM}, "Bearer " + self.b, "10.0.0.7")
        self.assertEqual(c, 403, o)
        self.assertEqual(self.hub.store.boards_public(), {})

    def test_spoke_without_its_hub_says_so(self):
        hub = [None]
        dead = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4473, store(), hub=lambda: hub[0], fed_token=lambda: self.fed)
        try:
            b = mint(dead, "beta")
            hub[0] = "http://127.0.0.1:9"
            o, c = dead.board_post({"room": "beta", "op": "spot", "target": B_CAM}, "Bearer " + b, "10.0.0.7")
            self.assertEqual((c, o.get("hubDown")), (503, True), o)
            self.assertTrue(dead.board_get("beta", None, None, "127.0.0.1")[0].get("hubDown"))
        finally:
            dead.close()


class OpenRelay(unittest.TestCase):
    def setUp(self):
        kr.XSHARE_OPEN.items.clear()

    def test_open_relay_board_lists_its_pins(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        o, c = kr.board_open("POST", st, {"room": "beta", "op": "pin", "path": A_CAM, "label": "Yard"})
        self.assertEqual((c, [p["path"] for p in o["pins"]]), (200, [A_CAM]))
        o, c = kr.board_open("GET", st, room="beta")
        self.assertEqual((c, len(o["pins"])), (200, 1))
        o, c = kr.xshare_open("GET", room="beta", store=st)
        self.assertEqual([(i["path"], i["pinned"]) for i in o["items"]], [(A_CAM, True)])
        kr.board_open("POST", st, {"room": "beta", "op": "unpin", "path": A_CAM})
        self.assertEqual(kr.xshare_open("GET", room="beta", store=st)[0]["items"], [])
        self.assertEqual(kr.board_open("POST", None, {})[1], 503)


class Page(unittest.TestCase):
    """The page side: menus, the board's spotlights as votes, removal hits the board, routes and the Relay page column."""

    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.p = f.read()

    def test_menus_offer_pin_to_this_room(self):
        p = self.p
        self.assertEqual(p.count('label: rp ? "Unpin from this room" : "Pin to this room"'), 4)   # 0.21.66: + a room grid of cameras   # remote tile, own share, own grid
        self.assertIn('if (v === "rpin" || v === "rpinoff") { boardPin(name, v === "rpin"); return; }', p)
        self.assertIn('boardPin(CHANNEL + "/" + hangName(ref.name), v === "rpin");', p)
        self.assertIn('window.__board?.pin?.(chanPath(ensureHang(g.entry.name)), v === "rpin");', p)
        can = p[p.index("  const boardCan = () =>"):p.index("  const boardPinned = (path) =>")]
        for need in ("!publishOnly", "!isPublisherMode()", "CHANNEL !== LOBBY", 'authRole !== "viewer"'):
            self.assertIn(need, can)

    def test_board_spotlights_are_votes_of_the_room(self):
        p = self.p
        body = p[p.index("  function boardVotes() {"):p.index("  function boardReset() {")]
        self.assertIn('by: "room"', body)
        self.assertIn('spotVotes.set("~board", list)', body)
        self.assertIn("for (const [k, arr] of spotVotes) { if (vl && k !== \"~board\") continue; for (const v of arr) addV(v, v.by || k); }", p)   # spotSetNow reads them

    def test_spotlight_and_removal_write_the_board(self):
        p = self.p
        add = p[p.index("  function spotAdd(targetPath) {"):p.index("  function spotOff(targetPath) {")]
        self.assertIn("window.__board?.spot?.(t, true, ts);", add)
        off = p[p.index("  function spotOff(targetPath) {"):p.index("  function spotSet(targetPath, announceOnly) {")]
        self.assertIn("window.__board?.spot?.(t, false);", off)
        self.assertLess(off.index("window.__board?.spot?.(t, false);"), off.index("spotCommit();"))
        spot = p[p.index("  function boardSpot(target, on, ts) {"):p.index("  window.__board = {")]
        self.assertIn('boardPost("unspot", { target: t }, true);', spot)
        self.assertIn('await boardPost("spot", { target: t, ts: Number(ts) || Date.now() }, false);', spot)

    def test_watched_feed_spotlight_pins_it_first(self):
        p = self.p
        body = p[p.index("  async function wrSpotForAll(path) {"):p.index("    if (!(await xsBring(path))) return;")]
        self.assertIn("if (boardCan() && await boardPin(path, true, true)) {", body)

    def test_fetched_with_the_poll_and_on_join(self):
        p = self.p
        self.assertIn("  setInterval(boardPoll, 8000);", p)
        self.assertIn("    setTimeout(() => { boardPoll(); xsPoll(); }, 1200);", p)
        self.assertIn('fetch(base + "/api/rooms/board?room=" + encodeURIComponent(CHANNEL), { cache: "no-store", headers })', p)
        self.assertIn('rp.className = "rpin"; rp.title = "Pinned to this room";', p)
        self.assertIn('t.pane.classList.toggle("roompin", rn)', p)

    def test_routes_and_relay_page(self):
        with open(os.path.join(HERE, "kastr_serve.py"), encoding="utf-8") as f:
            s = f.read()
        self.assertEqual(s.count('== "/api/rooms/board"'), 3)   # GET + POST to the minter, and the open relay's answer
        self.assertLess(s.index('if path == "/api/rooms/board":'), s.index('if path.startswith("/api/chat/") or path.startswith("/api/rooms/"):   # 0.12.0 (NOT'))
        with open(os.path.join(HERE, "relay.html"), encoding="utf-8") as f:
            r = f.read()
        self.assertIn(">Board</th>", r)
        self.assertIn('fillRow(tr, r, closed[slug], (d.boards || {})[slug]);', r)


if __name__ == "__main__":
    unittest.main()
