# -*- coding: utf-8 -*-
"""v0.21.75 PERSONAL ROOM ("My room"). Kenton: everyone can have a personal room that no other user sees in the rooms list,
where they set up their own views of feeds from other rooms; stored on the hub so it follows the person; identity = name + a
personal code picked once; an admin resets a forgotten code. The hub keeps "me-<12 hex>" records (never listed, the "me-"
prefix reserved, their own cap); /api/token opens one with the personal code (a spoke fails CLOSED while the hub is dark); its
token announces nothing public and carries `personal: 1`, which board_post takes as the room's publisher.
Loopback sockets only (ephemeral ports), no outside network."""
import io, os, re, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

HOST = "box-1a2b"
A_CAM = "alpha/box-1a2b/kenton/camera.hang"


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def mint(svc, room, host=HOST, code="pub-1", room_code=None, peer="10.0.0.7"):
    body = {"room": room, "code": code, "host": host}
    if room_code is not None:
        body["roomCode"] = room_code
    return svc.token(body, peer)


def claims(svc, tok):
    return kr.verify_token(tok, svc.key)


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.st = store(self.dir)
        self.lo = kr.Lockout()

    def op(self, body, peer="10.0.0.5", **kw):
        return kr.personal_op(self.st, body, peer, None, self.lo, **kw)

    def test_create_open_and_survive_a_restart(self):
        o, c = self.op({"op": "create", "name": "  Kenton   Jeffery ", "code": "abcd1234", "access": "view-1"})
        self.assertEqual(c, 200, o)
        slug = o["slug"]
        self.assertTrue(kr.PERSONAL_RE.match(slug), slug)
        self.assertTrue(o["created"])
        self.assertNotIn("abcd1234", repr(o))
        rec = self.st.room(slug)
        self.assertEqual(rec["personal"], {"owner": "Kenton Jeffery", "key": "kenton jeffery"})
        self.assertTrue(rec["persistent"] and rec["salt"] and rec["hash"])
        with open(os.path.join(self.dir, "relay-auth.json"), encoding="utf-8") as f:
            self.assertNotIn("abcd1234", f.read())                          # never the code itself
        # open: case-insensitive, trimmed name
        o, c = self.op({"op": "open", "name": "kenton jeffery", "code": "abcd1234"})
        self.assertEqual((c, o["slug"], o["name"]), (200, slug, "Kenton Jeffery"))
        # create again with the right code opens it (no second room)
        o, c = self.op({"op": "create", "name": "KENTON JEFFERY", "code": "abcd1234", "access": "pub-1"})
        self.assertEqual((c, o["slug"], o["created"]), (200, slug, False))
        again = kr.AuthStore(self.dir)
        self.assertEqual(again.personal_check("Kenton Jeffery", "abcd1234")[0], slug)
        self.assertEqual(again.personal_count(), 1)

    def test_wrong_code_and_lockout(self):
        self.op({"op": "create", "name": "K", "code": "abcd1234", "access": "pub-1"})
        o, c = self.op({"op": "open", "name": "K", "code": "nope1"})
        self.assertEqual((c, o.get("wrong")), (403, True))
        self.assertNotIn("slug", o)
        o, c = self.op({"op": "open", "name": "nobody", "code": "abcd1234"})   # an unknown name answers the same
        self.assertEqual((c, o["error"]), (403, "wrong name or personal code"))
        o, c = self.op({"op": "create", "name": "K", "code": "other-code", "access": "pub-1"})   # a taken name, another code
        self.assertEqual((c, o.get("wrong")), (403, True))
        self.assertIn("already has a personal room", o["error"])
        for _ in range(2):
            o, c = self.op({"op": "open", "name": "K", "code": "x" * 5})
        self.assertEqual(c, 429, o)                                         # five wrong codes in a minute
        o, c = self.op({"op": "open", "name": "K", "code": "abcd1234"})
        self.assertEqual(c, 429)                                            # even the right one waits
        self.assertEqual(self.op({"op": "open", "name": "K", "code": "abcd1234"}, peer="10.0.0.6")[1], 200)   # per address

    def test_create_needs_a_member_access_code(self):
        o, c = self.op({"op": "create", "name": "K", "code": "abcd1234"})
        self.assertEqual(c, 403, o)
        self.assertIn("access code", o["error"])
        o, c = self.op({"op": "create", "name": "K", "code": "abcd1234", "access": "wrong"})
        self.assertEqual(c, 403, o)
        self.assertNotIn("wrong", o)                                        # an access code, not a personal code
        self.assertEqual(self.st.personal_count(), 0)
        self.assertEqual(self.op({"op": "create", "name": "K", "code": "abcd1234"}, vouched=True)[1], 200)   # a spoke checked it
        self.assertEqual(self.op({"op": "create", "name": "Kim", "code": "abcd1234", "access": "adm-1"})[1], 200)
        self.assertEqual(self.op({"op": "create", "name": "Kai", "code": "abc", "access": "pub-1"})[1], 400)    # too short
        self.assertEqual(self.op({"op": "create", "name": "  ", "code": "abcd1234", "access": "pub-1"})[1], 400)
        self.assertEqual(self.op({"op": "zap", "name": "K", "code": "abcd1234"})[1], 400)

    def test_admin_reset(self):
        o, _ = self.op({"op": "create", "name": "K", "code": "abcd1234", "access": "pub-1"})
        slug = o["slug"]
        self.st.board_apply(slug, "spot", kr.board_item("spot", {"target": slug + "/box-1a2b/k/c.hang", "ts": 1})[0])
        self.assertEqual(self.op({"op": "reset", "name": "K"})[1], 403)                     # not an admin
        o, c = self.op({"op": "reset", "name": "K", "code": "new-code"}, admin=True)        # a new code, the board stays
        self.assertEqual((c, o["cleared"]), (200, False))
        self.assertEqual(self.st.personal_check("K", "abcd1234"), (None, None))
        self.assertEqual(self.st.personal_check("K", "new-code")[0], slug)
        self.assertEqual(len(self.st.board(slug)["spots"]), 1)
        o, c = self.op({"op": "reset", "name": "K"}, admin=True)                            # cleared
        self.assertEqual((c, o["cleared"]), (200, True))
        self.assertIsNone(self.st.room(slug))
        self.assertEqual(self.op({"op": "reset", "name": "K"}, admin=True)[1], 404)

    def test_cap(self):
        old = kr.PERSONAL_MAX
        kr.PERSONAL_MAX = 2
        try:
            for n in ("a", "b"):
                self.assertEqual(self.op({"op": "create", "name": n, "code": "abcd1234", "access": "pub-1"})[1], 200)
            o, c = self.op({"op": "create", "name": "c", "code": "abcd1234", "access": "pub-1"})
            self.assertEqual(c, 409, o)
            self.assertEqual(self.op({"op": "open", "name": "a", "code": "abcd1234"})[1], 200)
        finally:
            kr.PERSONAL_MAX = old
        # personal rooms never count against KEPT_MAX (and are not "kept rooms" for the Relay page)
        self.assertEqual(self.st.kept_slugs(), [])

    def test_never_listed(self):
        o, _ = self.op({"op": "create", "name": "K", "code": "abcd1234", "access": "pub-1"})
        slug = o["slug"]
        self.st.touch_room("beta")
        self.st.board_apply(slug, "spot", kr.board_item("spot", {"target": slug + "/box-1a2b/k/c.hang", "ts": 1})[0])
        self.assertEqual([r["slug"] for r in self.st.rooms_public()], ["beta"])
        self.assertNotIn(slug, self.st.boards_public(personal=False))
        self.assertIn(slug, self.st.boards_public())                       # spokes still copy it (the owner may use any relay)
        self.assertEqual(self.st.personal_public()["count"], 1)
        self.assertIn(slug, self.st.export_bundle()["rooms"])              # a hub hand-over carries it
        other = store()
        other.merge_bundle(self.st.export_bundle())
        self.assertEqual(other.personal_check("k", "abcd1234")[0], slug)

    def test_reserved_prefix(self):
        h = "ab" * 32
        for body in ({"slug": "me-0123456789ab", "plain": True}, {"slug": "me-team", "salt": "00112233", "hash": h, "access": "pub-1"},
                     {"slug": "me-x", "persistent": True, "access": "pub-1"}):
            o, c = kr.register_room(self.st, body, "10.0.0.1")
            self.assertEqual(c, 403, (body, o))
            self.assertIn("reserved", o["error"])
        self.assertFalse(self.st.touch_room("me-0123456789ab"))
        self.assertIsNone(self.st.room("me-0123456789ab"))
        b, c, err = self.st.board_apply("me-0123456789ab", "spot", {"target": "me-0123456789ab/box-1a2b/k/c.hang", "ts": 1})
        self.assertEqual(c, 404, err)
        self.assertIsNone(self.st.room("me-0123456789ab"))
        self.st.touch_room("beta")
        self.assertEqual(self.st.rename_room("beta", "me-0123456789ab")[1], 403)
        self.assertEqual(kr.room_settings(self.st, {"slug": "beta", "op": "rename", "to": "me-abc"}, admin=True)[1], 403)
        o, _ = self.op({"op": "create", "name": "K", "code": "abcd1234", "access": "pub-1"})
        slug = o["slug"]
        self.assertEqual(kr.room_settings(self.st, {"slug": slug, "op": "unlock"}, admin=True)[1], 403)
        self.assertEqual(self.st.rename_room(slug, "beta2")[1], 403)
        self.assertEqual(kr.close_room(self.st, slug, operator=True)[1], 403)
        self.assertEqual(kr.group_op(self.st, {"op": "assign", "slug": slug, "gid": None}, operator=True)[1], 403)
        self.assertIsNotNone(self.st.room(slug))

    def test_personal_feeds_stay_in_it(self):
        o, _ = self.op({"op": "create", "name": "K", "code": "abcd1234", "access": "pub-1"})
        slug = o["slug"]
        mine = slug + "/box-1a2b/k/camera.hang"
        b, c, err = self.st.board_apply("beta", "pin", kr.board_item("pin", {"path": mine})[0])
        self.assertEqual(c, 403, err)
        g = {"name": "G", "slots": [{"rect": [0, 0, 1, 1], "cams": [mine]}], "gap": 2, "sens": "medium"}
        item, why = kr.board_item("cgrid", dict(g, id="g1"))
        if not why:
            self.assertEqual(self.st.board_apply("beta", "cgrid", item)[1], 403)


class Service(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        o, c = kr.personal_op(self.svc.store, {"op": "create", "name": "K", "code": "abcd1234", "access": "pub-1"}, "10.0.0.5")
        assert c == 200, o
        self.slug = o["slug"]
        self.a = mint(self.svc, "alpha")[0]["tokens"]["member"]

    def tearDown(self):
        self.svc.close()

    def test_mint_needs_the_personal_code(self):
        o, c = mint(self.svc, self.slug, room_code="abcd1234")
        self.assertEqual(c, 200, o)
        self.assertTrue(o["personal"])
        self.assertEqual(list(o["tokens"]), ["member"])                    # no registry (~channels) token
        cl = claims(self.svc, o["tokens"]["member"])
        self.assertEqual((cl["personal"], cl["get"], cl["put"]), (1, self.slug, [self.slug + "/" + HOST]))
        puts = " ".join(map(str, cl["put"]))
        for kind in ("~presence", "~state", "~since", "~talking", "~chat", "~channels"):
            self.assertNotIn(kind, puts)
        g = kr.claims_to_grant(cl)
        self.assertFalse(any(p.startswith(("~presence", "~state", "~channels")) for p in g["publish"]))
        # wrong / no personal code; the personal code is never an access code
        self.assertEqual(mint(self.svc, self.slug, room_code="wrong")[1], 403)
        self.assertEqual(mint(self.svc, self.slug)[1], 403)
        self.assertEqual(mint(self.svc, self.slug, code="abcd1234", room_code="abcd1234")[1], 403)
        # a viewer access code: only its room.json; still personal
        o, c = mint(self.svc, self.slug, host="watch-9f9f", code="view-1", room_code="abcd1234")
        cl = claims(self.svc, o["tokens"]["member"])
        self.assertEqual((c, o["role"], cl["put"]), (200, "viewer", [self.slug + "/watch-9f9f/" + kr.MEMBER_SEG]))
        # an admin code mints a publisher-shaped personal token (no ~admin grant in My room)
        o, c = mint(self.svc, self.slug, code="adm-1", room_code="abcd1234")
        self.assertEqual((c, o["role"]), (200, "publisher"))
        self.assertFalse(kr.claims_admin(claims(self.svc, o["tokens"]["member"]), self.slug))
        # a me- room with no record never mints
        o, c = mint(self.svc, "me-0123456789ab", room_code="abcd1234")
        self.assertEqual(c, 404, o)

    def test_board_takes_the_personal_claim(self):
        viewer = mint(self.svc, self.slug, host="watch-9f9f", code="view-1", room_code="abcd1234")[0]["tokens"]["member"]
        o, c = self.svc.board_post({"room": self.slug, "op": "pin", "path": A_CAM, "label": "Yard", "tokens": {"alpha": self.a}},
                                   "Bearer " + viewer, "10.0.0.7")
        self.assertEqual(c, 200, o)
        o, c = self.svc.board_post({"room": self.slug, "op": "spot", "target": A_CAM}, "Bearer " + viewer, "10.0.0.7")
        self.assertEqual((c, [s["target"] for s in o["spots"]]), (200, [A_CAM]), o)
        o, c = self.svc.board_post({"room": self.slug, "op": "spotOrder", "targets": [A_CAM]}, "Bearer " + viewer, "10.0.0.7")
        self.assertEqual(c, 200, o)
        # a plain viewer of another room still cannot change ITS board
        v2 = mint(self.svc, "beta", host="watch-9f9f", code="view-1")[0]["tokens"]["member"]
        self.assertEqual(self.svc.board_post({"room": "beta", "op": "spot", "target": A_CAM}, "Bearer " + v2, "10.0.0.7")[1], 403)
        # the pinned feed is listed into My room and granted to its sessions
        g = self.svc.session({"event": "connect", "id": "s1", "remote": "10.0.0.9:5000", "path": "/", "query": "jwt=" + viewer}, "127.0.0.1")[0]
        self.assertIn(A_CAM, g["subscribe"])
        self.assertNotIn(self.slug, [r["slug"] for r in self.svc.store.rooms_public()])

    def test_personal_streams_are_never_listed_elsewhere(self):
        tok = mint(self.svc, self.slug, room_code="abcd1234")[0]["tokens"]["member"]
        b = mint(self.svc, "beta")[0]["tokens"]["member"]
        o, c = self.svc.xshare_post({"path": self.slug + "/" + HOST + "/kenton/camera.hang", "to": ["beta"], "tokens": {"beta": b}},
                                    "Bearer " + tok, "10.0.0.7")
        self.assertEqual(c, 403, o)
        o, c = self.svc.board_post({"room": "beta", "op": "pin", "path": self.slug + "/" + HOST + "/kenton/camera.hang",
                                    "tokens": {self.slug: tok}}, "Bearer " + b, "10.0.0.7")
        self.assertEqual(c, 403, o)

    def test_vehicle_refused(self):
        o, c = self.svc.vehicle({"key": "kv-00000000-" + "a" * 32, "room": self.slug}, "10.0.0.7")
        self.assertEqual(c, 403, o)
        self.assertIn("reserved", o["error"])


class Federation(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        self.base = ["http://127.0.0.1:%d" % self.hub.httpd.server_address[1]]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: self.base[0], fed_token=lambda: self.fed)

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def fed_op(self, body, vouch=None):
        return self.hub.rooms_fed({"op": "personal", "body": body, "peer": "10.0.0.5", "vouch": vouch}, "Bearer " + self.fed)

    def test_spoke_mints_through_the_hub_and_fails_closed(self):
        self.assertEqual(self.hub.rooms_fed({"op": "personal", "body": {"op": "open", "name": "K", "code": "abcd1234"}}, None)[1], 403)
        o, c = self.fed_op({"op": "create", "name": "K", "code": "abcd1234"})          # nobody vouched for an access code
        self.assertEqual(c, 403, o)
        o, c = self.fed_op({"op": "create", "name": "K", "code": "abcd1234"}, vouch="member")
        self.assertEqual(c, 200, o)
        slug = o["slug"]
        o, c = self.fed_op({"op": "open", "name": "k", "code": "nope1"})
        self.assertEqual((c, o.get("wrong")), (403, True))                             # the spoke counts it
        self.assertEqual(self.fed_op({"op": "reset", "name": "K"}, vouch="member")[1], 403)
        self.assertIsNone(self.spoke.store.room(slug))                                 # the hub alone holds it
        o, c = mint(self.spoke, slug, room_code="abcd1234")
        self.assertEqual(c, 200, o)
        self.assertEqual(claims(self.spoke, o["tokens"]["member"])["personal"], 1)
        self.assertEqual(mint(self.spoke, slug, room_code="wrong")[1], 403)
        self.assertEqual(mint(self.spoke, "me-0123456789ab", room_code="abcd1234")[1], 404)
        # the hub goes dark: a personal room never mints (fail closed), even with the right code
        self.base[0] = "http://127.0.0.1:9"
        o, c = mint(self.spoke, slug, room_code="abcd1234", peer="10.0.0.8")
        self.assertEqual(c, 503, o)
        self.assertNotIn("tokens", o)
        o, c = mint(self.spoke, "me-0123456789ab", room_code="x", peer="10.0.0.8")
        self.assertIn(c, (404, 503), o)                                                 # (the hub said "no such room" 1 s ago)
        self.assertNotIn("tokens", o)
        o, c = mint(self.spoke, "me-ba9876543210", room_code="x", peer="10.0.0.8")
        self.assertEqual(c, 503, o)

    def test_spoke_board_forwards(self):
        slug = self.fed_op({"op": "create", "name": "K", "code": "abcd1234"}, vouch="member")[0]["slug"]
        tok = mint(self.spoke, slug, room_code="abcd1234")[0]["tokens"]["member"]
        a = mint(self.spoke, "alpha")[0]["tokens"]["member"]
        o, c = self.spoke.board_post({"room": slug, "op": "pin", "path": A_CAM, "tokens": {"alpha": a}}, "Bearer " + tok, "10.0.0.7")
        self.assertEqual(c, 200, o)
        self.assertEqual([p["path"] for p in self.hub.store.board(slug)["pins"]], [A_CAM])
        payload = self.hub.bans_for_spoke("Bearer " + self.fed)[0]
        self.assertIn(slug, payload["boards"])                                         # spokes copy it (federation only)
        self.assertNotIn(slug, [r["slug"] for r in self.fed_list()["rooms"]])

    def fed_list(self):
        return self.hub.rooms_fed({"op": "list"}, "Bearer " + self.fed)[0]

    def test_spoke_cannot_mirror_a_lock_onto_a_reserved_name(self):
        o, c = self.hub.rooms_fed({"op": "lock", "slug": "me-0123456789ab", "salt": "00112233", "hash": "ab" * 32}, "Bearer " + self.fed)
        self.assertEqual(c, 403, o)
        o, c = self.hub.rooms_fed({"op": "touch", "slug": "me-0123456789ab"}, "Bearer " + self.fed)
        self.assertEqual((c, o["created"]), (200, False))
        self.assertIsNone(self.hub.store.room("me-0123456789ab"))


class Serve(unittest.TestCase):
    def test_endpoint_and_spoke_forwarding(self):
        with io.open(os.path.join(HERE, "kastr_serve.py"), encoding="utf-8") as f:
            s = f.read()
        self.assertIn('if path == "/api/rooms/personal":   # 0.21.75', s)
        self.assertIn("obj, code = kastr_relay.personal_op(store, p, self._chat_peer(), log, CHAT_LOCKOUT,", s)
        self.assertIn('body = {"op": "personal", "body": {k: v for k, v in p.items() if k != "access"}, "peer": peer, "vouch": vouch}', s)
        self.assertIn('lo, lc = CHAT_LOCKOUT.fail(peer, "wrong personal code", "(personal room)")', s)


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with io.open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            cls.p = f.read()

    def test_wiring(self):
        p = self.p
        self.assertIn("const PERSONAL_RE = /^me-[0-9a-f]{12}$/;", p)
        self.assertIn('const roomTitle = (slug) => (slug === LOBBY ? "Lobby" : isPersonalSlug(slug) ? personalTitle(slug) : String(slug || ""));', p)   # 0.21.78: someone else's reads "<owner>'s room"
        self.assertIn('<div id="sbMine" class="sbmine" hidden></div>', p)
        self.assertIn('id="optMyRoom"', p)
        self.assertIn('document.getElementById("optMyRoom").addEventListener("click", () => personalDialog());', p)
        self.assertIn('return "kastr.personal." + new URL(urlInput.value.trim()).host;', p)
        self.assertIn('fetch(base + "/api/rooms/personal"', p)
        self.assertIn("switchRoom({ slug: p.slug, personal: true }, p.code);", p)
        self.assertIn("try { personalCardPaint(); } catch {}   // 0.21.75", p)
        # other people's personal rooms never reach the rail
        self.assertIn('.filter((r) => r.slug !== "main" && !isPersonalSlug(r.slug)   // 0.21.75: never a personal room', p)
        self.assertIn('slug === "main" || isPersonalSlug(slug)) continue;   // 0.21.75', p)
        # nothing announced in My room: no registry, no ember, no public presence / state
        self.assertIn('if (chan !== "main" && !isPersonalSlug(chan)) {', p)
        self.assertIn('rec.slug === "main" || window.__isPersonalSlug?.(rec.slug)) return;   // 0.21.75: My room is never announced', p)
        self.assertIn('&& !(isPersonalSlug(CHANNEL) && ["~presence", "~talking", "~chat"].includes(kind))', p)
        self.assertIn('stateProducer(() => (isPersonalSlug(CHANNEL) ? "" : "~state/"', p)
        self.assertIn("{ clear(key, true); return; }", p)
        # the owner arranges it; Pin to My room from other rooms (three menus + module 2's grid menu)
        self.assertIn("(authPersonal && isPersonalSlug(CHANNEL))", p)
        self.assertIn("authPersonal = !!d.personal;", p)
        self.assertEqual(p.count('label: "Pin to My room"'), 3)
        self.assertIn('else if (v === "mypin") window.__personal?.pin?.(chanPath(ensureHang(g.entry.name)));', p)
        self.assertIn('const body = { room: p.slug, op: "pin", path, from, label, kind: xsKindOf(path)', p)
        # module 2 comes after module 1 defines the seam
        self.assertLess(p.index("window.__isPersonalSlug = isPersonalSlug;"), p.index("function chanRegSet(rec)"))
        # no raw personal code in a URL
        self.assertIsNone(re.search(r"/api/rooms/personal\?", p))


if __name__ == "__main__":
    unittest.main()
