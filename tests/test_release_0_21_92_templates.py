# -*- coding: utf-8 -*-
"""v0.21.92 MEETING TEMPLATES, phase 1 "by hand" (Kenton 2026-10-23 design + 2026-10-27 presentation section): a saved snapshot of
how a room is set up, in sections (Layout & view, Streams & cameras, Presentation & roles, Room settings, Invites, My view).
The hub keeps them (kastr_templates.TemplateBook, carried in the records bundle) and runs save / preview / apply / undo against
its room records, re-checking every item against the applier's rights. Decks live on the hub, encrypted at rest.
Loopback sockets only (ephemeral ports), no outside network."""
import base64, hashlib, json, os, re, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_templates as kt  # noqa: E402

HOST = "kenton-pc-1a2b"
OTHER = "carlo-pc-3c4d"
BOX = "box-77aa"
SALT = "00112233aabbccdd"
CODE = "Gate-Code-42"                     # a room code (lab value, only its digest is ever stored)
MYCODE = "kenton-myroom-1"                # a My room code (lab value)
A_CAM = "alpha/%s/kenton/yard.hang" % BOX
A_GRID = "alpha/%s/kenton/grid-1.hang" % BOX
A_G1, A_G2 = "alpha/%s/kenton/rtsp-1.hang" % BOX, "alpha/%s/kenton/rtsp-2.hang" % BOX
B_CAM = "beta/%s/kenton/camera.hang" % BOX
B_SCR = "beta/%s/kenton/screen.hang" % BOX
SEC_CAM = "secret/%s/kenton/camera.hang" % BOX


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


def digest(code, salt=SALT):
    return hashlib.sha256((salt + code).encode()).hexdigest()


def pin(svc, room, path, tok, label="Cam", tokens=None):
    o, c = svc.board_post({"room": room, "op": "pin", "path": path, "label": label, "kind": "camera", "tokens": tokens or {}},
                          "Bearer " + tok, "10.0.0.7")
    assert c == 200, o
    return o


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def board_sig(b):
    b = kt.clean_layout(b)
    b.pop("start", None)
    return json.dumps(b, sort_keys=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store(self.dir))
        self.st = self.svc.store
        o, c = kr.register_room(self.st, {"slug": "beta", "salt": SALT, "hash": digest(CODE), "access": "pub-1", "persistent": True,
                                          "creator": "Kenton"}, "10.0.0.1")
        assert c == 200, o
        self.room_key = o["roomKey"]
        self.adm = mint(self.svc, "beta", code="adm-1", room_code=CODE)
        self.pub = mint(self.svc, "beta", host=OTHER, room_code=CODE)
        self.view = mint(self.svc, "beta", host="watch-9f9f", code="view-1", room_code=CODE)
        self.a = mint(self.svc, "alpha")

    def tearDown(self):
        self.svc.close()

    def api(self, body, tok=None, peer="10.0.0.7"):
        return self.svc.templates_api(body, "Bearer " + (tok or self.adm), peer)

    def arrange(self):
        """beta: a pin from alpha (a cross-room pin), its own camera pinned + spotlit with the screen, a grid layout of alpha's
        grid (pinned), a room grid, the spotlight order."""
        pin(self.svc, "beta", A_CAM, self.adm, "Yard", {"alpha": self.a})
        pin(self.svc, "beta", B_CAM, self.adm, "Front desk")
        pin(self.svc, "beta", A_GRID, self.adm, "Alpha grid", {"alpha": self.a})
        post = lambda body: self.svc.board_post(dict(body, room="beta"), "Bearer " + self.adm, "10.0.0.7")
        self.st.board_apply("alpha", "gridMeta", {"path": A_GRID, "meta": kr.board_meta_clean(A_GRID, {
            "path": A_GRID, "n": 2, "members": [A_G1, A_G2], "feeds": [A_G1, A_G2]})})
        o, c = post({"op": "grid", "path": A_GRID, "rects": {A_G1: [0, 0, 12, 24], A_G2: [12, 0, 12, 24]}, "gap": 4})
        assert c == 200, o
        o, c = post({"op": "cgrid", "id": "lobby-wall", "name": "Wall", "slots": [{"rect": [0, 0, 12, 12], "cams": [B_CAM, B_SCR]}],
                     "gap": 2, "sens": "medium"})
        assert c == 200, o
        for t in (B_CAM, B_SCR):
            o, c = post({"op": "spot", "target": t, "ts": int(time.time() * 1000)})
            assert c == 200, o
        o, c = post({"op": "spotOrder", "targets": [B_SCR, B_CAM]})
        assert c == 200, o
        return self.st.board("beta")


class Store(unittest.TestCase):
    def test_clean_caps_and_never_a_code(self):
        t = {"id": "t0123456789ab", "scope": "room", "room": "beta", "name": "  Morning\nstand-up  ",
             "settings": {"locked": True, "salt": SALT, "hash": digest(CODE), "code": CODE, "keep": True},
             "invites": {"people": ["Ada", {"name": "ada"}, {"name": "Bob", "host": "bob-pc-0001"}], "link": {"ttl": 86400}}}
        c, why = kt.clean_template(t)
        self.assertIsNone(why)
        self.assertEqual(c["name"], "Morning stand-up")
        self.assertNotIn("code", json.dumps(c))                       # only the digest survives
        self.assertEqual([p["name"] for p in c["invites"]["people"]], ["Ada", "Bob"])
        pub = kt.public(c)
        self.assertNotIn("salt", pub["settings"])
        self.assertNotIn("hash", pub["settings"])
        self.assertTrue(pub["counts"]["settings"]["locked"])
        big = dict(t, note="x" * 300, layout={"pins": [{"path": "beta/%s/k/c%d.hang" % (BOX, i), "label": "L" * 80} for i in range(32)]},
                   pres={"presenters": [{"name": "P%d" % i} for i in range(9)]})
        self.assertIsNotNone(kt.clean_template(big)[0])               # the board's own caps keep it under 32 KB
        huge = dict(t, view={"grids": {"g%d" % i: {"x": "y" * 5000} for i in range(10)}}, scope="me", owner="kenton")
        c2, why = kt.clean_template(huge)
        self.assertLessEqual(len(json.dumps(c2["view"])), kt.VIEW_BYTES_MAX)
        self.assertIsNotNone(kt.clean_template(dict(t, name=""))[1])
        self.assertIsNotNone(kt.clean_template(dict(t, scope="x"))[1])

    def test_pres_shape(self):
        p = kt.clean_pres({"deck": {"id": "d0123456789abcdef", "name": "Q3", "slides": 12, "start": 3},
                           "presenters": [{"name": "Kenton"}, {"name": "Ada", "main": True}, {"name": "kenton"}],
                           "backstage": [{"name": "Bob", "control": ["Ada", "Nobody"]}, {"name": "Ada"}],
                           "audience": {"muted": False}, "mode": "reporter", "reporterBg": "asi-03"})
        self.assertEqual([(x["name"], x["main"]) for x in p["presenters"]], [("Kenton", False), ("Ada", True)])
        self.assertEqual(p["backstage"], [{"name": "Bob", "control": ["Ada"]}])   # a presenter is never also backstage
        self.assertEqual((p["audience"], p["mode"], p["deck"]["start"]), ({"muted": False, "ask": True}, "reporter", 3))
        self.assertEqual(kt.clean_pres({"presenters": ["A", "B"]})["presenters"][0]["main"], True)   # one main presenter

    def test_book_limits_persist_and_tombstones(self):
        d = tempfile.mkdtemp()
        b = kt.TemplateBook(d)
        ids = []
        for i in range(kt.TPL_ROOM_MAX):
            t, why, code = b.put({"id": "t000000000000", "scope": "room", "room": "beta", "name": "T%d" % i, "layout": {}}, new=True)
            self.assertEqual(code, 200, why)
            ids.append(t["id"])
        t, why, code = b.put({"id": "t000000000000", "scope": "room", "room": "beta", "name": "one more", "layout": {}}, new=True)
        self.assertEqual(code, 409)
        self.assertIn("20 templates", why)
        b.delete(ids[0])
        again = kt.TemplateBook(d)
        self.assertEqual(len(again.list("room", "beta")), kt.TPL_ROOM_MAX - 1)
        # a hand-back never brings a deleted template back
        other = kt.TemplateBook(tempfile.mkdtemp())
        other.import_(kt.TemplateBook(d).export())
        exp = b.export()
        self.assertIn(ids[0], exp["gone"])
        old = json.loads(json.dumps(exp))
        old["rooms"]["beta"][ids[0]] = dict(old["rooms"]["beta"][ids[1]], id=ids[0])
        b.merge(old)
        self.assertIsNone(b.get(ids[0]))

    def test_plan_replace_merge_and_undo_keys(self):
        cur = {"pins": [{"path": A_CAM, "from": "alpha", "label": "Yard"}, {"path": B_SCR, "from": "beta", "label": "Screen"}],
               "spots": [{"target": B_SCR, "ts": 5}], "grids": {}, "split": [], "customGrids": {}}
        tgt = {"pins": [{"path": B_CAM, "from": "beta", "label": "Desk", "kind": "camera"}], "spots": [B_CAM], "spotOrder": [],
               "grids": {}, "customGrids": {}, "split": []}
        rep = kt.plan_ops(tgt, cur, "replace", 1000)
        self.assertEqual([o for o, _ in rep], ["unspot", "unpin", "unpin", "pin", "spot"])
        mer = kt.plan_ops(tgt, cur, "merge", 1000)
        self.assertEqual([o for o, _ in mer], ["pin", "spot"])
        after = {"pins": [{"path": B_CAM, "from": "beta", "label": "Desk"}], "spots": [{"target": B_CAM, "ts": 1001}]}
        back = kt.undo_ops(cur, after, after)
        self.assertEqual(sorted(o for o, _ in back), ["pin", "pin", "spot", "unpin", "unspot"])
        self.assertEqual([it["ts"] for o, it in back if o == "spot"], [5])         # the old spotlight's own time

    def test_map_paths_origin_and_choices(self):
        self.assertEqual(kt.map_path(B_CAM, "beta", "gamma"), "gamma/%s/kenton/camera.hang" % BOX)   # this room's feed follows
        self.assertEqual(kt.map_path(A_CAM, "beta", "gamma"), A_CAM)                                  # another room's stays
        self.assertIsNone(kt.map_path(A_CAM, "beta", "gamma", streams_on=False))                      # Streams & cameras off
        self.assertIsNone(kt.map_path(A_CAM, "beta", "beta", choices={A_CAM: {"act": "drop"}}))
        self.assertEqual(kt.map_path(A_CAM, "beta", "beta", choices={A_CAM: {"act": "swap", "to": SEC_CAM}}), SEC_CAM)
        self.assertEqual(kt.map_path(A_CAM, "beta", "beta", choices={A_CAM: {"act": "keep"}}), A_CAM)


class Service(Base):
    def test_save_close_apply_identical(self):
        before = self.arrange()
        o, c = self.api({"op": "save", "name": "Ops room", "note": "every morning", "roomKey": self.room_key,
                         "invites": {"people": [{"name": "Carlo", "host": OTHER}], "link": {"ttl": 3600}},
                         "sections": ["layout", "streams", "settings", "invites"], "start": "spotlight", "by": "Kenton"})
        self.assertEqual(c, 200, o)
        t = o["template"]
        self.assertEqual(t["counts"]["layout"], {"pins": 3, "spots": 2, "grids": 1, "cgrids": 1, "split": 0, "start": "spotlight"})
        self.assertEqual((t["counts"]["settings"]["locked"], t["counts"]["settings"]["keep"]), (True, True))
        self.assertNotIn(digest(CODE), json.dumps(o))                    # the page never sees the digest
        with open(os.path.join(self.dir, "templates", "templates.json"), encoding="utf-8") as f:
            raw = f.read()
        self.assertIn(digest(CODE), raw)                                 # the hub keeps the digest ...
        self.assertNotIn(CODE, raw)                                      # ... never the code
        self.assertEqual(t["counts"]["streams"]["foreign"], 2)
        # the room closes (its board goes with it) -- then comes back plain, and the template puts it back
        kr.close_room(self.st, "beta", operator=True)
        self.assertIsNone(self.st.room("beta"))
        self.st.touch_room("beta", "Kenton")
        pub2 = mint(self.svc, "beta", host=OTHER)                        # unlocked now: no room code
        adm2 = mint(self.svc, "beta", code="adm-1")
        pv, c = self.api({"op": "preview", "id": t["id"], "live": [A_CAM, B_CAM]}, adm2)
        self.assertEqual(c, 200, pv)
        self.assertEqual(pv["changes"]["pins+"], 3)
        self.assertEqual([s["words"] for s in pv["settings"]], ["locks the room", "keeps it open"])
        self.assertEqual(pv["invites"]["people"], ["Carlo"])              # by name (his device as the hint)
        self.assertEqual(pv["invites"]["link"], {"ttl": 3600})
        st = {x["path"]: x["status"] for x in pv["cams"]}
        self.assertEqual((st[A_CAM], st[B_CAM]), ("live", "live"))
        t0 = time.time()
        ap, c = self.api({"op": "apply", "id": t["id"], "tokens": {"alpha": self.a}}, adm2)
        self.assertEqual(c, 200, ap)
        self.assertLess(time.time() - t0, 2.0)
        self.assertEqual(ap["notes"], [])
        self.assertEqual(board_sig(self.st.board("beta")), board_sig(before))   # IDENTICAL
        rec = self.st.room("beta")
        self.assertEqual((rec["hash"], rec["salt"], rec["persistent"]), (digest(CODE), SALT, True))
        self.assertTrue(ap["link"]["token"].startswith("ki-"))
        self.assertIsNotNone(ap["undo"])
        del pub2

    def test_merge_vs_replace_and_undo(self):
        self.arrange()
        o, c = self.api({"op": "save", "name": "Full", "sections": ["layout", "streams"]})
        tid = o["template"]["id"]
        # the room moves on: everything unpinned, one new pin and a different spotlight
        for op, it in kt.plan_ops({"pins": [], "spots": [], "grids": {}, "customGrids": {}, "split": []}, self.st.board("beta"), "replace"):
            self.st.board_apply("beta", op, it)
        extra = "beta/%s/kenton/media.hang" % BOX
        pin(self.svc, "beta", extra, self.adm, "Clip")
        self.svc.board_post({"room": "beta", "op": "spot", "target": extra}, "Bearer " + self.adm, "10.0.0.7")
        o, c = self.api({"op": "apply", "id": tid, "mode": "merge", "tokens": {"alpha": self.a}})
        self.assertEqual(c, 200, o)
        b = self.st.board("beta")
        self.assertIn(extra, [p["path"] for p in b["pins"]])            # merge keeps what the room has
        self.assertEqual(len(b["pins"]), 4)
        self.assertEqual(len(b["spots"]), 3)
        # undo the merge: back to exactly what it was
        u, c = self.api({"op": "undo", "undo": o["undo"]})
        self.assertEqual(c, 200, u)
        b = self.st.board("beta")
        self.assertEqual(([p["path"] for p in b["pins"]], [s["target"] for s in b["spots"]]), ([extra], [extra]))
        self.assertEqual(self.api({"op": "undo", "undo": o["undo"]})[1], 409)   # once
        # replace: the room is the template's again (the extra pin and its spotlight go)
        o, c = self.api({"op": "apply", "id": tid, "mode": "replace", "tokens": {"alpha": self.a}})
        b = self.st.board("beta")
        self.assertNotIn(extra, [p["path"] for p in b["pins"]])
        self.assertEqual(len(b["pins"]), 3)
        self.assertEqual(o["changes"]["pins-"], 1)
        # someone pins another feed after the apply -- undo leaves it alone
        later = "beta/%s/kenton/tab.hang" % BOX
        pin(self.svc, "beta", later, self.pub, "Tab")
        u, c = self.api({"op": "undo", "undo": o["undo"]})
        b = self.st.board("beta")
        self.assertEqual(sorted(p["path"] for p in b["pins"]), sorted([extra, later]))
        # only the device that applied it may undo it
        o, c = self.api({"op": "apply", "id": tid, "tokens": {"alpha": self.a}})
        self.assertEqual(self.api({"op": "undo", "undo": o["undo"]}, self.pub)[1], 409)

    def test_publisher_gets_layout_but_not_settings_and_viewer_only_sees(self):
        self.arrange()
        o, c = self.api({"op": "save", "name": "Locked open", "roomKey": self.room_key,
                         "sections": ["layout", "settings", "invites"], "invites": {"link": {"ttl": 3600}}})
        tid = o["template"]["id"]
        kr.room_settings(self.st, {"slug": "beta", "op": "unlock"}, admin=True)
        for op, it in kt.plan_ops({"pins": [], "spots": [], "grids": {}, "customGrids": {}, "split": []}, self.st.board("beta"), "replace"):
            self.st.board_apply("beta", op, it)
        # a viewer: list, get, preview -- nothing else
        lst, c = self.api({"op": "list"}, self.view)
        self.assertEqual((c, [t["name"] for t in lst["templates"]]), (200, ["Locked open"]))
        self.assertEqual((lst["can"]["save"], lst["can"]["apply"]), (False, False))
        self.assertEqual(self.api({"op": "get", "id": tid}, self.view)[1], 200)
        pv, c = self.api({"op": "preview", "id": tid}, self.view)
        self.assertEqual(c, 200)
        self.assertFalse(pv["can"]["layout"])
        o, c = self.api({"op": "apply", "id": tid}, self.view)
        self.assertEqual(c, 200)
        self.assertEqual(self.st.board("beta")["pins"], [])                 # nothing changed for a viewer
        self.assertIn("viewers cannot change", o["notes"][0]["why"])
        for op in ("save", "delete", "update"):
            self.assertEqual(self.api({"op": op, "id": tid, "name": "x"}, self.view)[1], 403, op)
        # a publisher: layout yes, settings and invites no (each skipped with a note)
        o, c = self.api({"op": "apply", "id": tid, "tokens": {"alpha": mint(self.svc, "alpha", host=OTHER)}}, self.pub)
        self.assertEqual(c, 200, o)
        self.assertEqual(len(self.st.board("beta")["pins"]), 3)
        self.assertFalse(self.st.room("beta").get("hash"))                 # still unlocked: settings need an admin
        why = {n["section"]: n["why"] for n in o["notes"]}
        self.assertIn("room settings need a room admin", why["settings"])
        self.assertIn("invites from a template need a room admin", why["invites"])
        self.assertNotIn("link", o)
        self.assertEqual(self.api({"op": "save", "name": "mine?"}, self.pub)[1], 403)   # publishers do not save room templates
        # the room's creator (roomKey) is a room admin too
        o, c = self.api({"op": "apply", "id": tid, "roomKey": self.room_key}, self.pub)
        self.assertEqual(self.st.room("beta").get("hash"), digest(CODE))

    def test_view_lock_refuses_publishers(self):
        self.arrange()
        o, c = self.api({"op": "save", "name": "L", "sections": ["layout"]})
        tid = o["template"]["id"]
        for op, it in kt.plan_ops({"pins": [], "spots": [], "grids": {}, "customGrids": {}, "split": []}, self.st.board("beta"), "replace"):
            self.st.board_apply("beta", op, it)
        kr.room_settings(self.st, {"slug": "beta", "op": "viewlock", "locked": True}, admin=True)
        o, c = self.api({"op": "apply", "id": tid, "mode": "replace"}, self.pub)
        self.assertEqual(c, 200)
        self.assertEqual(o["notes"][0]["why"], kr.VIEW_LOCKED_TEXT)
        self.assertEqual(self.st.board("beta")["pins"], [])
        lst, _ = self.api({"op": "list"}, self.pub)
        self.assertFalse(lst["can"]["layout"])
        self.assertTrue(self.api({"op": "list"})[0]["can"]["layout"])        # an admin still may

    def test_locked_source_room_needs_proof(self):
        o, c = kr.register_room(self.st, {"slug": "secret", "salt": SALT, "hash": digest("s3cret-room"), "access": "pub-1"}, "10.0.0.1")
        s_tok = mint(self.svc, "secret", room_code="s3cret-room")
        pin(self.svc, "beta", SEC_CAM, self.adm, "Vault", {"secret": mint(self.svc, "secret", code="adm-1", room_code="s3cret-room")})
        o, c = self.api({"op": "save", "name": "Vault view", "sections": ["layout"]})
        tid = o["template"]["id"]
        self.st.board_apply("beta", "unpin", {"path": SEC_CAM})
        o, c = self.api({"op": "apply", "id": tid}, self.pub)                 # no proof for "secret"
        self.assertEqual(self.st.board("beta")["pins"], [])
        self.assertIn("secret is locked", o["notes"][0]["why"])
        o, c = self.api({"op": "apply", "id": tid, "tokens": {"secret": s_tok}}, self.pub)   # a member, not an admin, not the owner
        self.assertIn("only an admin", o["notes"][0]["why"])
        own = mint(self.svc, "secret", host=BOX, room_code="s3cret-room")   # the camera's own box shows it may
        o, c = self.api({"op": "apply", "id": tid, "tokens": {"secret": own}}, self.pub)
        self.assertEqual([p["path"] for p in self.st.board("beta")["pins"]], [SEC_CAM])

    def test_missing_camera_keep_drop_swap(self):
        self.arrange()
        o, c = self.api({"op": "save", "name": "Cams", "sections": ["layout", "streams"]})
        tid = o["template"]["id"]
        for op, it in kt.plan_ops({"pins": [], "spots": [], "grids": {}, "customGrids": {}, "split": []}, self.st.board("beta"), "replace"):
            self.st.board_apply("beta", op, it)
        gone_cam = A_CAM
        # the library knows the box camera moved there (its alias) -> "moved"; another camera nobody knows -> "missing"
        pv, c = self.api({"op": "preview", "id": tid, "live": [B_CAM, B_SCR]})
        st = {x["path"]: x["status"] for x in pv["cams"]}
        self.assertEqual(st[B_CAM], "live")
        self.assertIn(st[gone_cam], ("missing", "offline"))
        self.assertEqual(st[A_G1], "offline")                                  # known from its grid's geometry
        # drop it
        o, c = self.api({"op": "apply", "id": tid, "tokens": {"alpha": self.a}, "choices": {gone_cam: {"act": "drop"}}})
        self.assertNotIn(gone_cam, [p["path"] for p in self.st.board("beta")["pins"]])
        self.api({"op": "undo", "undo": o["undo"]})
        # swap it for another stream
        other = "beta/%s/kenton/door.hang" % BOX
        pv, c = self.api({"op": "preview", "id": tid, "choices": {gone_cam: {"act": "swap", "to": other}}, "live": [other]})
        self.assertEqual({x["path"]: x["to"] for x in pv["cams"]}[gone_cam], other)
        o, c = self.api({"op": "apply", "id": tid, "tokens": {"alpha": self.a}, "choices": {gone_cam: {"act": "swap", "to": other}}})
        self.assertIn(other, [p["path"] for p in self.st.board("beta")["pins"]])
        self.api({"op": "undo", "undo": o["undo"]})
        # keep it (pinned anyway -- it shows when it comes back)
        o, c = self.api({"op": "apply", "id": tid, "tokens": {"alpha": self.a}, "choices": {gone_cam: {"act": "keep"}}})
        self.assertIn(gone_cam, [p["path"] for p in self.st.board("beta")["pins"]])
        # the same origin live in another room -> "moved" with where
        pv, c = self.api({"op": "preview", "id": tid, "live": ["gamma/%s/kenton/yard.hang" % BOX]})
        row = [x for x in pv["cams"] if x["path"] == gone_cam][0]
        self.assertEqual((row["status"], row["found"]), ("moved", "gamma/%s/kenton/yard.hang" % BOX))

    def test_applied_to_another_room_follows_and_streams_off(self):
        self.arrange()
        o, c = self.api({"op": "save", "name": "Pattern", "sections": ["layout", "streams"]})
        tid = o["template"]["id"]
        gtok = mint(self.svc, "gamma", code="adm-1")
        o, c = self.api({"op": "apply", "id": tid, "tokens": {"beta": self.adm, "alpha": self.a}}, gtok)
        self.assertEqual(c, 200, o)
        g = self.st.board("gamma")
        self.assertIn("gamma/%s/kenton/camera.hang" % BOX, [p["path"] for p in g["pins"]])   # beta's own camera -> gamma's
        self.assertIn(A_CAM, [p["path"] for p in g["pins"]])                                   # alpha's stays alpha's
        self.assertEqual(g["customGrids"]["lobby-wall"]["slots"][0]["cams"], ["gamma/%s/kenton/camera.hang" % BOX, "gamma/%s/kenton/screen.hang" % BOX])
        # without the beta proof a room template of beta is not visible from gamma
        self.assertEqual(self.api({"op": "apply", "id": tid}, gtok)[1], 403)
        # Streams & cameras off: nothing pulled in from other rooms
        dtok = mint(self.svc, "delta", code="adm-1")
        o, c = self.api({"op": "apply", "id": tid, "on": {"streams": False}, "tokens": {"beta": self.adm}}, dtok)
        self.assertEqual(c, 200, o)
        self.assertTrue(all(p["from"] == "delta" for p in self.st.board("delta")["pins"]))

    def test_rename_moves_templates(self):
        o, c = self.api({"op": "save", "name": "R", "sections": ["layout"]})
        err, code = self.st.rename_room("beta", "beta2")
        self.assertEqual(code, 200, err)
        self.assertEqual([t["name"] for t in self.st.tplbook.list("room", "beta2")], ["R"])
        self.assertEqual(self.st.tplbook.list("room", "beta"), [])


class Personal(Base):
    def setUp(self):
        super().setUp()
        o, c = kr.personal_op(self.st, {"op": "create", "name": "Kenton Jeffery", "code": MYCODE, "access": "pub-1"}, "10.0.0.5")
        assert c == 200, o
        self.my = o["slug"]
        self.mytok = mint(self.svc, self.my, room_code=MYCODE)

    def test_personal_templates_follow_the_person(self):
        self.arrange()
        me = {"pname": "Kenton Jeffery", "pcode": MYCODE}
        view = {"grids": {"box-77aa/kenton/grid-1.hang": {"rects": {"x": [0, 0, 12, 12]}, "gap": 2}}, "pins": [A_CAM],
                "dock": ["people", "chat"], "mode": "gallery"}
        o, c = self.api(dict(me, op="save", scope="me", name="My desk", sections=["layout", "streams", "view"], view=view), self.pub)
        self.assertEqual(c, 200, o)
        tid = o["template"]["id"]
        self.assertEqual(o["template"]["counts"]["view"], {"grids": 1, "pins": 1, "dock": 2, "mode": "gallery"})
        # not a room template: others in beta do not see it
        lst, _ = self.api({"op": "list"}, self.view)
        self.assertEqual(lst["templates"], [])
        self.assertIsNone(lst["mine"])
        # wrong My room code: refused and counted
        o, c = self.api({"op": "list", "pname": "Kenton Jeffery", "pcode": "nope-nope"}, self.pub, peer="10.9.9.9")
        self.assertEqual((c, o.get("wrong")), (403, True))
        for i in range(6):
            o, c = self.api({"op": "list", "pname": "Kenton Jeffery", "pcode": "guess-%d" % i}, self.pub, peer="10.9.9.9")
        self.assertEqual(c, 429)
        # apply it to My room (the owner's own token -- no code needed there)
        lst, c = self.api({"op": "list"}, self.mytok)
        self.assertEqual(([t["name"] for t in lst["mine"]], lst["me"]), (["My desk"], "Kenton Jeffery"))
        self.assertEqual(lst["templates"], [])                               # My room keeps personal templates only
        o, c = self.api({"op": "apply", "id": tid, "tokens": {"beta": self.pub, "alpha": self.a}}, self.mytok)
        self.assertEqual(c, 200, o)
        mine = self.st.board(self.my)
        self.assertIn(A_CAM, [p["path"] for p in mine["pins"]])
        self.assertIn("%s/%s/kenton/camera.hang" % (self.my, BOX), [p["path"] for p in mine["pins"]] + [""])
        self.assertEqual(o["view"]["mode"], "gallery")                       # the page applies My view on its own device
        # another person cannot see it, even with a code of their own
        kr.personal_op(self.st, {"op": "create", "name": "Ada", "code": "ada-code-99", "access": "pub-1"}, "10.0.0.5")
        o, c = self.api({"op": "get", "id": tid, "pname": "Ada", "pcode": "ada-code-99"}, self.pub)
        self.assertEqual(c, 403)
        # a room template cannot live in My room
        self.assertEqual(self.api({"op": "save", "name": "x", "sections": ["layout"]}, self.mytok)[1], 403)

    def test_a_renamed_person_keeps_their_templates(self):
        me = {"pname": "Kenton Jeffery", "pcode": MYCODE}
        o, c = self.api(dict(me, op="save", scope="me", name="Mine", sections=["layout"]), self.pub)
        self.assertEqual(c, 200, o)
        verdict, info = self.st.personal_rename("Kenton Jeffery", "Kenton J", MYCODE)
        self.assertEqual(verdict, "renamed")
        lst, c = self.api({"op": "list", "pname": "Kenton J", "pcode": MYCODE}, self.pub)
        self.assertEqual(([t["name"] for t in lst["mine"]], lst["mine"][0]["ownerName"]), (["Mine"], "Kenton J"))
        self.assertTrue(self.st.personal_unrename("Kenton J", "Kenton Jeffery"))
        lst, c = self.api(dict(me, op="list"), self.pub)
        self.assertEqual([t["name"] for t in lst["mine"]], ["Mine"])

    def test_personal_cap(self):
        me = {"pname": "Kenton Jeffery", "pcode": MYCODE}
        for i in range(kt.TPL_PERSON_MAX):
            self.assertEqual(self.api(dict(me, op="save", scope="me", name="T%d" % i, sections=["layout"]), self.pub)[1], 200)
        o, c = self.api(dict(me, op="save", scope="me", name="more", sections=["layout"]), self.pub)
        self.assertEqual(c, 409)


class Decks(Base):
    def test_deck_store_encrypted_served_to_presenters_only(self):
        o, c = self.api({"op": "save", "name": "Board meeting", "sections": ["layout", "pres"],
                         "pres": {"presenters": [{"name": "Kenton", "main": True}], "backstage": [{"name": "Ada", "control": ["Kenton"]}],
                                  "audience": {"muted": True, "ask": True}, "mode": "standout"}})
        tid = o["template"]["id"]
        slide = b"SLIDE-ONE-PLAINTEXT" * 1000
        d, c = self.api({"op": "deckNew", "id": tid, "name": "Q3.pptx", "kind": "pptx", "slides": 2, "size": len(slide) * 2,
                         "pageKey": base64.b64encode(os.urandom(32)).decode()})
        self.assertEqual(c, 200, d)
        self.assertEqual(self.api({"op": "deckNew", "id": tid, "size": kt.DECK_MAX + 1})[1], 413)
        q = {"d": [d["deck"]], "f": ["s0.bin"], "ut": [d["utok"]]}
        self.assertEqual(self.svc.tpl_deck_post(slide, q, None)[1], 200)
        self.assertEqual(self.svc.tpl_deck_post(slide, dict(q, f=["s1.bin"]), None)[1], 200)
        self.assertEqual(self.svc.tpl_deck_post(slide, dict(q, ut=["0" * 32]), None)[1], 404)   # the upload token is the credential
        o, c = self.api({"op": "deckDone", "id": tid, "deck": d["deck"], "utok": d["utok"], "start": 1})
        self.assertEqual(c, 200, o)
        self.assertEqual(o["template"]["pres"]["deck"]["start"], 1)
        self.assertEqual(o["template"]["deckFile"]["size"], len(slide) * 2)
        # at rest: no plaintext anywhere in the hub's templates folder, no key in the bundle
        blob = b""
        for root, _d, files in os.walk(os.path.join(self.dir, "templates")):
            for fn in files:
                if fn != "deck.key":
                    with open(os.path.join(root, fn), "rb") as f:
                        blob += f.read()
        self.assertNotIn(b"SLIDE-ONE-PLAINTEXT", blob)
        bundle = json.dumps(self.st.export_bundle())
        self.assertIn(d["deck"], bundle)
        self.assertNotIn('"wk"', bundle)
        self.assertNotIn('"pk"', bundle)
        # Kenton (2026-10-27): before it is presented, ONLY the template's named presenters + backstage (proven by name + My room
        # code) and the room's admins open the deck -- not any publisher, not a name a page merely says
        for n, code in (("Ada", "ada-code-99"), ("Bob", "bob-code-99")):
            kr.personal_op(self.st, {"op": "create", "name": n, "code": code, "access": "pub-1"}, "10.0.0.5")
        o, c = self.api({"op": "deckOpen", "id": tid}, self.pub)                          # a publisher, not named
        self.assertEqual((c, o.get("named")), (403, False))
        self.assertEqual(self.api({"op": "deckOpen", "id": tid, "by": "Ada"}, self.pub)[1], 403)   # saying a name is not enough
        self.assertEqual(self.api({"op": "deckOpen", "id": tid, "pname": "Bob", "pcode": "bob-code-99"}, self.pub)[1], 403)   # a person, not named
        o, c = self.api({"op": "deckOpen", "id": tid, "pname": "Ada", "pcode": "wrong-wrong"}, self.pub)
        self.assertEqual((c, o.get("wrong")), (403, True))                              # a wrong code is counted
        o, c = self.api({"op": "deckOpen", "id": tid, "pname": "Ada", "pcode": "ada-code-99"}, self.pub)   # named backstage
        self.assertEqual(c, 200, o)
        self.assertIn("pageKey", o)
        data, c = self.svc.tpl_deck_get({"d": [d["deck"]], "f": ["s0.bin"], "rt": [o["rt"]]}, None)
        self.assertEqual((c, data), (200, slide))
        self.assertEqual(self.svc.tpl_deck_get({"d": [d["deck"]], "f": ["s0.bin"], "rt": ["x.1.y"]}, None)[1], 403)
        o, c = self.api({"op": "deckOpen", "id": tid, "pname": "Ada", "pcode": "ada-code-99"}, self.view)   # named, even on a viewer code
        self.assertEqual(c, 200, o)
        self.assertEqual(self.api({"op": "deckOpen", "id": tid}, self.view)[1], 403)       # a viewer, not named
        self.assertEqual(self.api({"op": "deckOpen", "id": tid})[1], 200)                  # a room admin (the admin code)
        o, c = self.api({"op": "deckOpen", "id": tid, "roomKey": self.room_key}, self.pub)   # the room's creator is a room admin
        self.assertEqual(c, 200, o)
        g = mint(self.svc, "gamma", code="adm-1")                                         # another room -- even an admin there
        self.assertEqual(self.api({"op": "deckOpen", "id": tid, "pname": "Ada", "pcode": "ada-code-99", "tokens": {"beta": self.pub}}, g)[1], 403)
        # the deck goes with its template
        self.api({"op": "delete", "id": tid})
        self.assertFalse(os.path.exists(os.path.join(self.dir, "templates", "decks", d["deck"])))
        self.assertEqual(self.st.tplbook.decks, {})

    def test_a_rename_never_cuts_deck_access_or_a_role(self):
        kr.personal_op(self.st, {"op": "create", "name": "Kenton Jeffery", "code": MYCODE, "access": "pub-1"}, "10.0.0.5")
        kr.personal_op(self.st, {"op": "create", "name": "Ada", "code": "ada-code-99", "access": "pub-1"}, "10.0.0.5")
        o, c = self.api({"op": "save", "name": "Briefing", "sections": ["layout", "pres"],
                         "pres": {"presenters": [{"name": "Kenton Jeffery", "main": True}, {"name": "Bob"}],
                                  "backstage": [{"name": "Ada", "control": ["Kenton Jeffery", "Bob"]}]}})
        tid = o["template"]["id"]
        d, c = self.api({"op": "deckNew", "id": tid, "name": "D", "size": 10})
        self.svc.tpl_deck_post(b"0123456789", {"d": [d["deck"]], "f": ["s0.bin"], "ut": [d["utok"]]}, None)
        self.api({"op": "deckDone", "id": tid, "deck": d["deck"], "utok": d["utok"]})
        self.assertEqual(self.st.personal_rename("Kenton Jeffery", "Kenton J", MYCODE)[0], "renamed")
        pr = self.st.tplbook.get(tid)["pres"]
        self.assertEqual([p["name"] for p in pr["presenters"]], ["Kenton J", "Bob"])          # the role follows the person
        self.assertEqual(pr["backstage"][0]["control"], ["Kenton J", "Bob"])                  # and Ada's "Can control my mic and camera"
        self.assertEqual(self.api({"op": "deckOpen", "id": tid, "pname": "Kenton J", "pcode": MYCODE}, self.pub)[1], 200)
        self.assertEqual(self.api({"op": "deckOpen", "id": tid, "pname": "Ada", "pcode": "ada-code-99"}, self.pub)[1], 200)
        # put back: the template names him as before
        self.assertTrue(self.st.personal_unrename("Kenton J", "Kenton Jeffery"))
        pr = self.st.tplbook.get(tid)["pres"]
        self.assertEqual((pr["presenters"][0]["name"], pr["backstage"][0]["control"][0]), ("Kenton Jeffery", "Kenton Jeffery"))
        # the fallback: a copy that still holds the old name (e.g. handed back from the standby) -- the hub's 90-day alias
        self.st.personal_rename("Kenton Jeffery", "Kenton J", MYCODE)
        t = self.st.tplbook.get(tid)
        t["pres"]["presenters"][0]["name"] = "Kenton Jeffery"
        self.st.tplbook.put(t)
        self.assertEqual(self.st.tplbook.get(tid)["pres"]["presenters"][0]["name"], "Kenton Jeffery")
        self.assertEqual(self.api({"op": "deckOpen", "id": tid, "pname": "Kenton J", "pcode": MYCODE}, self.pub)[1], 200)
        # ... and nobody else gets in through it
        kr.personal_op(self.st, {"op": "create", "name": "Carlo", "code": "carlo-code-9", "access": "pub-1"}, "10.0.0.5")
        self.assertEqual(self.api({"op": "deckOpen", "id": tid, "pname": "Carlo", "pcode": "carlo-code-9"}, self.pub)[1], 403)

    def test_apply_gets_the_presentation_ready_for_the_main_presenter(self):
        # Kenton (2026-10-27, item 7): "Ready, with a Start button" -- the main presenter's device is told; nothing goes live here
        o, c = self.api({"op": "save", "name": "Q3", "sections": ["layout", "pres"],
                         "pres": {"presenters": [{"name": "Carlo Bos", "main": True}, {"name": "Kenton"}],
                                  "backstage": [{"name": "Ada", "control": ["Carlo Bos"]}], "mode": "side", "audience": {"muted": False}}})
        self.assertEqual(c, 200, o)
        t = o["template"]
        self.assertEqual(t["pres"]["mode"], "sbs")                                     # kastr-pres.js's id for Side-by-side
        self.svc.people_api({"op": "beat", "name": "Carlo Bos"}, "Bearer " + self.pub, "10.0.0.8")   # Carlo's device is known
        pv, c = self.api({"op": "preview", "id": t["id"]})
        self.assertEqual(pv["presFor"]["name"], "Carlo Bos")
        self.assertNotIn("host", pv["presFor"])
        self.assertEqual(self.svc.people_api({"op": "beat", "name": "Carlo Bos"}, "Bearer " + self.pub, "10.0.0.8")[0]["inbox"], [])   # a preview tells nobody
        ap, c = self.api({"op": "apply", "id": t["id"], "by": "Kenton"})
        self.assertEqual((ap["presFor"]["me"], ap["presFor"]["told"]), (False, True))
        box = self.svc.people_api({"op": "beat", "name": "Carlo Bos"}, "Bearer " + self.pub, "10.0.0.8")[0]["inbox"]
        self.assertEqual([(x["kind"], x["tid"], x["room"], x["for"]) for x in box], [("tplpres", t["id"], "beta", "Carlo Bos")])
        # the main presenter applying it himself: ready on his own page, nobody else is told
        ap, c = self.api({"op": "apply", "id": t["id"], "by": "Carlo Bos"}, self.pub)
        self.assertTrue(ap["presFor"]["me"])
        self.assertNotIn("told", ap["presFor"])
        # an edit changes roles and the start slide, never which deck the hub keeps
        o, c = self.api({"op": "update", "id": t["id"], "pres": {"deck": {"id": "d0123456789abcdef", "name": "forged", "start": 3},
                                                                  "presenters": [{"name": "Ada", "main": True}], "mode": "reporter"}})
        self.assertEqual(c, 200, o)
        self.assertIsNone(o["template"]["pres"]["deck"])
        self.assertEqual((o["template"]["pres"]["presenters"][0]["name"], o["template"]["pres"]["mode"]), ("Ada", "reporter"))

    def test_ask_to_speak_and_co_presenters_own_control_lists(self):
        # 0.21.91: "Ask to speak" is a switch of its own (kept while muted); co-presenters have the same powers and their OWN
        # "Can control my mic and camera" -- after Start presenting, each co-presenter's device hears whom the template says THEY
        # do not allow (from the hub's template, never from the page)
        o, c = self.api({"op": "save", "name": "Board", "sections": ["layout", "pres"],
                         "pres": {"presenters": [{"name": "Kenton", "main": True}, {"name": "Carlo Bos"}, {"name": "Bob"}],
                                  "backstage": [{"name": "Ada", "control": ["Kenton", "Bob"]}, {"name": "Bea", "control": ["Kenton", "Carlo Bos", "Bob"]}],
                                  "audience": {"muted": True, "ask": False}, "mode": "reporter"}})
        self.assertEqual(c, 200, o)
        tid = o["template"]["id"]
        self.assertEqual(o["template"]["pres"]["audience"], {"muted": True, "ask": False})
        o, c = self.api({"op": "update", "id": tid, "pres": dict(o["template"]["pres"], audience={"muted": True, "ask": True})})
        self.assertEqual(o["template"]["pres"]["audience"], {"muted": True, "ask": True})
        self.assertEqual(self.api({"op": "presCo", "id": tid, "deck": "pd-1a2b3c4d"})[1], 404)            # no deck kept: nothing to start
        d, c = self.api({"op": "deckNew", "id": tid, "name": "Board.pdf", "kind": "pdf", "slides": 4, "size": 3000})
        self.svc.tpl_deck_post(b"x" * 3000, {"d": [d["deck"]], "f": ["part.000"], "ut": [d["utok"]]}, None)
        self.api({"op": "deckDone", "id": tid, "deck": d["deck"], "utok": d["utok"], "start": 2})
        bob = mint(self.svc, "beta", host="bob-pc-5e6f", room_code=CODE)
        self.svc.people_api({"op": "beat", "name": "Carlo Bos"}, "Bearer " + self.pub, "10.0.0.8")
        self.svc.people_api({"op": "beat", "name": "Bob"}, "Bearer " + bob, "10.0.0.9")
        self.assertEqual(self.api({"op": "presCo", "id": tid, "deck": "../x"})[1], 400)
        r, c = self.api({"op": "presCo", "id": tid, "deck": "pd-1a2b3c4d", "deny": ["Bea"]})
        self.assertEqual((c, r["told"]), (200, 1))                                 # Bob allows everyone: nothing to tell him
        box = self.svc.people_api({"op": "beat", "name": "Carlo Bos"}, "Bearer " + self.pub, "10.0.0.8")[0]["inbox"]
        self.assertEqual([(x["kind"], x["deck"], x["deny"], x["owner"]) for x in box], [("tplco", "pd-1a2b3c4d", ["Ada"], "Kenton")])
        # only the template's named people (or admins) may send it
        kr.personal_op(self.st, {"op": "create", "name": "Zed", "code": "zed-code-99", "access": "pub-1"}, "10.0.0.5")
        self.assertEqual(self.api({"op": "presCo", "id": tid, "deck": "pd-1a2b3c4d", "pname": "Zed", "pcode": "zed-code-99"}, self.pub)[1], 403)
        # applied to a FRESH room: there its deck opens (and the template reads) for the named people and that room's admins
        gadm = mint(self.svc, "gamma", code="adm-1")
        gpub = mint(self.svc, "gamma", host="zed-pc-7a7a", code="pub-1")
        self.assertEqual(self.api({"op": "get", "id": tid}, gadm)[1], 403)
        self.assertEqual(self.api({"op": "deckOpen", "id": tid}, gadm)[1], 403)
        o, c = self.api({"op": "apply", "id": tid, "on": {"layout": False}, "tokens": {"beta": self.adm}, "by": "Kenton", "here": "beta"}, gadm)
        self.assertEqual(c, 200, o)
        # Kenton (the main presenter) applied it to a room he is not in: his own device keeps it for when he goes there
        self.assertEqual((o["presFor"]["me"], o["presFor"].get("away"), o["presFor"].get("told")), (True, True, True))
        self.assertEqual(self.api({"op": "get", "id": tid}, gadm)[1], 200)
        self.assertEqual(self.api({"op": "deckOpen", "id": tid}, gadm)[1], 200)
        self.assertEqual(self.api({"op": "get", "id": tid, "pname": "Zed", "pcode": "zed-code-99"}, gpub)[1], 403)   # not named
        self.assertEqual(self.api({"op": "deckOpen", "id": tid}, mint(self.svc, "delta", code="adm-1"))[1], 403)    # not applied there

    def test_decks_and_templates_move_with_the_hub(self):
        o, c = self.api({"op": "save", "name": "Moves", "sections": ["layout", "pres"], "pres": {}})
        tid = o["template"]["id"]
        d, c = self.api({"op": "deckNew", "id": tid, "name": "D", "size": 5000})
        self.svc.tpl_deck_post(b"x" * 5000, {"d": [d["deck"]], "f": ["s0.bin"], "ut": [d["utok"]]}, None)
        self.api({"op": "deckDone", "id": tid, "deck": d["deck"], "utok": d["utok"]})
        new = kr.AuthStore(tempfile.mkdtemp())
        new.import_bundle(self.st.export_bundle())                           # what a hand-over / promote does
        self.assertEqual([t["name"] for t in new.tplbook.list("room", "beta")], ["Moves"])
        miss = new.tplbook.missing()
        self.assertEqual((miss["keys"], miss["files"]), ([d["deck"]], [(d["deck"], "s0.bin")]))
        old = self.st.tplbook
        n = kt.deck_sync(new.tplbook, old.keys_export, old.deck_raw, sleep=lambda s: None)
        self.assertEqual((n["keys"], n["files"], n["missing"]), (1, 1, 0))
        self.assertEqual(new.tplbook.deck_file(d["deck"], "s0.bin"), b"x" * 5000)
        self.assertNotEqual(new.tplbook._master(), old._master())           # wrapped under the new hub's own key
        # a hand-back: an edit on the standby wins, a delete there sticks
        nt = new.tplbook.get(tid)
        nt["name"] = "Moved and renamed"
        new.tplbook.put(nt)
        self.st.merge_bundle(new.export_bundle())
        self.assertEqual(self.st.tplbook.get(tid)["name"], "Moved and renamed")
        new.tplbook.delete(tid)
        self.st.merge_bundle(new.export_bundle())
        self.assertIsNone(self.st.tplbook.get(tid))


class TemplateRoom(Base):
    """Kenton (2026-10-28): "When creating a presentation using the template and having it create a room for it, close the room
    after the presenter ends the meeting." -- the page creates the room (the Create room path), the hub marks it as made by this
    run (op room), End -> op presEnd closes it like an admin close. Never a room that existed before; only that run's presenters,
    the room's creator and admins."""

    def setUp(self):
        super().setUp()
        for n, code in (("Carlo Bos", "carlo-code-99"), ("Ada", "ada-code-99"), ("Zed", "zed-code-99")):
            kr.personal_op(self.st, {"op": "create", "name": n, "code": code, "access": "pub-1"}, "10.0.0.5")
        o, c = self.api({"op": "save", "name": "Q3 review", "sections": ["layout", "pres"],
                         "pres": {"presenters": [{"name": "Kenton", "main": True}, {"name": "Carlo Bos"}],
                                  "backstage": [{"name": "Ada", "control": ["Kenton"]}], "mode": "standout"}})
        self.assertEqual(c, 200, o)
        self.tid = o["template"]["id"]
        self.closed = []
        self._hook = kr.ROOM_CLOSE_HOOK[0]
        kr.ROOM_CLOSE_HOOK[0] = self.closed.append      # what kastr_serve's hook does: the room's chat goes

    def tearDown(self):
        kr.ROOM_CLOSE_HOOK[0] = self._hook
        super().tearDown()

    def make(self, slug, host=HOST):
        """The page's Create room path (a plain room) + the starter's token there -> (roomKey, token)."""
        o, c = kr.register_room(self.st, {"slug": slug, "plain": True, "creator": "Kenton"}, "10.0.0.7")
        self.assertEqual(c, 200, o)
        return o.get("roomKey"), mint(self.svc, slug, host=host)

    def test_the_switch_is_kept_in_the_template(self):
        t = self.st.tplbook.get(self.tid)
        self.assertIs(t["pres"]["closeOnEnd"], True)                               # on by default
        o, c = self.api({"op": "update", "id": self.tid, "pres": dict(t["pres"], closeOnEnd=False)})
        self.assertIs(o["template"]["pres"]["closeOnEnd"], False)
        self.assertIs(kt.clean_pres({"closeOnEnd": True})["closeOnEnd"], True)

    def test_create_a_room_then_end_closes_it(self):
        key, tok = self.make("q3-review")
        self.svc.people_api({"op": "beat", "name": "Carlo Bos"}, "Bearer " + self.pub, "10.0.0.8")   # Carlo's device is known
        self.assertEqual(self.api({"op": "room", "id": self.tid, "tokens": {"beta": self.adm}}, tok)[1], 403)   # no roomKey: not its maker
        mk, c = self.api({"op": "room", "id": self.tid, "roomKey": key, "tokens": {"beta": self.adm}, "by": "Kenton"}, tok)
        self.assertEqual(c, 200, mk)
        self.assertTrue(mk["close"])
        self.assertEqual(self.api({"op": "room", "id": self.tid, "roomKey": key, "tokens": {"beta": self.adm}}, tok)[1], 409)   # never twice
        rec = self.st.room("q3-review")
        self.assertEqual((rec["tpl"]["id"], rec["tpl"]["run"]), (self.tid, mk["run"]))
        self.assertTrue(next(r for r in self.st.rooms_public() if r["slug"] == "q3-review")["tplClose"])
        ap, c = self.api({"op": "apply", "id": self.tid, "roomKey": key, "tokens": {"beta": self.adm}, "by": "Kenton", "here": "q3-review",
                          "run": mk["run"]}, tok)
        self.assertEqual(c, 200, ap)
        self.assertEqual(ap["sent"], ["Carlo Bos"])                                    # the usual invite for the named people
        self.assertTrue(any(n["what"] == "Invite Ada" for n in ap["notes"]))           # Ada: not seen -- her role waits for her
        self.assertEqual(ap["tplRoom"]["close"], True)
        self.assertTrue(ap["presFor"]["me"])
        box = self.svc.people_api({"op": "beat", "name": "Carlo Bos"}, "Bearer " + self.pub, "10.0.0.8")[0]["inbox"]
        self.assertTrue(any(x.get("room") == "q3-review" for x in box))
        inv, c = self.svc._invite_make("q3-review", 3600, "Kenton")
        self.assertEqual(c, 200, inv)
        # End by a named co-presenter (proven by name + My room code) -> the hub closes it like an admin close
        carlo = mint(self.svc, "q3-review", host=OTHER)
        o, c = self.api({"op": "presEnd", "pname": "Carlo Bos", "pcode": "carlo-code-99"}, carlo)
        self.assertEqual(c, 200, o)
        self.assertIsNone(self.st.room("q3-review"))
        self.assertIn("q3-review", self.st.closed_public())
        self.assertEqual(self.st.closed_why_public().get("q3-review"), "pres")       # the pages' note: "The presentation ended ..."
        self.assertEqual(self.closed, ["q3-review"])                                   # its chat goes
        self.assertTrue(self.st.invites[inv["id"]]["revoked"])                         # its invite links stop working
        g = kr.rooms_for_guest({"rooms": [], "closed": {"q3-review": 1, "beta": 2}, "closedWhy": {"q3-review": "pres"}}, {"beta"})
        self.assertEqual(g["closedWhy"], {})                                           # a guest learns only its own rooms
        # an admin close afterwards is an ordinary close again
        self.st.close_room("q3-review")
        self.assertNotIn("q3-review", self.st.closed_why_public())

    def test_a_room_that_existed_before_is_never_closed(self):
        # beta: the template's own room (made before this run) -- never marked, never closed by End
        self.st.rooms["beta"]["created"] = time.time() - 3600
        o, c = self.api({"op": "room", "id": self.tid, "roomKey": self.room_key})
        self.assertEqual(c, 409, o)
        o, c = self.api({"op": "presEnd"})                                             # even an admin: not a template's room
        self.assertEqual((c, o.get("kept")), (409, True))
        self.assertIsNotNone(self.st.room("beta"))
        # an older plain room its maker still holds the key to: too old to be "made by this run"
        key, tok = self.make("old-room")
        self.st.rooms["old-room"]["created"] = time.time() - kr.TPL_ROOM_NEW_S - 5
        self.assertEqual(self.api({"op": "room", "id": self.tid, "roomKey": key, "tokens": {"beta": self.adm}}, tok)[1], 409)
        self.assertEqual(self.api({"op": "presEnd", "roomKey": key}, tok)[1], 409)
        self.assertIsNotNone(self.st.room("old-room"))
        # a room that was there when the page tried to create it: the Create room path gives no roomKey -> nothing to mark with
        o, c = kr.register_room(self.st, {"slug": "old-room", "plain": True, "creator": "Mallory"}, "10.0.0.9")
        self.assertIsNone(o.get("roomKey"))
        # the switch off: End leaves it open
        key2, tok2 = self.make("q3-open")
        mk, c = self.api({"op": "room", "id": self.tid, "roomKey": key2, "close": False, "tokens": {"beta": self.adm}}, tok2)
        self.assertEqual((c, mk["close"]), (200, False))
        self.assertEqual(self.api({"op": "presEnd", "roomKey": key2}, tok2)[1], 409)
        self.assertIsNotNone(self.st.room("q3-open"))
        self.assertEqual(self.closed, [])

    def test_only_that_runs_presenters_close_it(self):
        key, tok = self.make("q3-b")
        mk, c = self.api({"op": "room", "id": self.tid, "roomKey": key, "tokens": {"beta": self.adm}}, tok)
        self.assertEqual(c, 200, mk)
        other = mint(self.svc, "q3-b", host="zed-pc-7a7a")
        viewer = mint(self.svc, "q3-b", host="watch-9f9f", code="view-1")
        self.assertEqual(self.api({"op": "presEnd"}, other)[1], 403)                                   # a publisher, not named
        self.assertEqual(self.api({"op": "presEnd", "by": "Carlo Bos"}, other)[1], 403)               # saying a name is not enough
        self.assertEqual(self.api({"op": "presEnd", "pname": "Zed", "pcode": "zed-code-99"}, other)[1], 403)   # a person, not named
        self.assertEqual(self.api({"op": "presEnd", "pname": "Ada", "pcode": "ada-code-99"}, other)[1], 403)   # backstage is no presenter
        o, c = self.api({"op": "presEnd", "pname": "Carlo Bos", "pcode": "wrong-wrong"}, other)
        self.assertEqual((c, o.get("wrong")), (403, True))
        self.assertEqual(self.api({"op": "presEnd"}, viewer)[1], 403)
        self.assertEqual(self.api({"op": "presEnd", "run": "0" * 12, "roomKey": key}, tok)[1], 409)   # another run's room
        # apply, a second apply, undo: none of them closes it (only End does)
        ap, c = self.api({"op": "apply", "id": self.tid, "roomKey": key, "tokens": {"beta": self.adm}, "here": "q3-b", "run": mk["run"]}, tok)
        self.assertEqual(c, 200, ap)
        self.assertEqual(self.api({"op": "undo", "undo": ap["undo"], "roomKey": key}, tok)[1], 200)
        self.assertIsNotNone(self.st.room("q3-b"))
        o, c = self.api({"op": "presEnd", "roomKey": key, "run": mk["run"]}, tok)                    # the room's creator (the starter)
        self.assertEqual(c, 200, o)
        self.assertIsNone(self.st.room("q3-b"))
        self.assertEqual(self.api({"op": "presEnd", "roomKey": key}, tok)[1], 409)                    # gone: nothing left to close
        # an admin closes one too
        key3, tok3 = self.make("q3-c")
        self.api({"op": "room", "id": self.tid, "roomKey": key3, "tokens": {"beta": self.adm}}, tok3)
        self.assertEqual(self.api({"op": "presEnd"}, mint(self.svc, "q3-c", host="admin-pc-1111", code="adm-1"))[1], 200)
        self.assertEqual(self.closed, ["q3-b", "q3-c"])

    def test_invited_presenters_close_it_and_the_pages_hint_finds_them(self):
        # the lab: Carlo's page is on a spoke the hub has no check-in from -- the applying page says which device it saw him on
        key, tok = self.make("q3-g")
        mk, c = self.api({"op": "room", "id": self.tid, "roomKey": key, "tokens": {"beta": self.adm}}, tok)
        ap, c = self.api({"op": "apply", "id": self.tid, "roomKey": key, "tokens": {"beta": self.adm}, "here": "q3-g", "run": mk["run"],
                          "by": "Kenton", "people": [{"name": "Carlo Bos", "host": "carlo-pc-5e6f"}, {"name": "Mallory", "host": "mal-pc-6666"},
                                                     {"name": "Ada", "host": "not a host"}]}, tok)
        self.assertEqual(c, 200, ap)
        self.assertEqual(ap["sent"], ["Carlo Bos"])                     # Mallory is not the template's; Ada's "host" is no device
        # they join by that invite -> invite-link guests in the room; a named presenter among them still closes it, nobody else
        def guest(host):
            inv, c = self.svc._invite_make("q3-g", 3600, "Kenton")
            r, c = self.svc.token({"room": "q3-g", "invite": inv["token"], "host": host}, "10.0.0.9")
            self.assertEqual(c, 200, r)
            return r["tokens"]["member"]
        carlo, ada, zed = guest("carlo-pc-5e6f"), guest("ada-pc-1234"), guest("zed-pc-7a7a")
        self.assertEqual(self.api({"op": "apply", "id": self.tid, "here": "q3-g"}, carlo)[1], 403)            # a guest applies nothing
        self.assertEqual(self.api({"op": "presEnd"}, carlo)[1], 403)                                          # not proven
        self.assertEqual(self.api({"op": "presEnd", "pname": "Ada", "pcode": "ada-code-99"}, ada)[1], 403)    # backstage
        self.assertEqual(self.api({"op": "presEnd", "pname": "Zed", "pcode": "zed-code-99"}, zed)[1], 403)    # not named
        self.assertIsNotNone(self.st.room("q3-g"))
        o, c = self.api({"op": "presEnd", "pname": "Carlo Bos", "pcode": "carlo-code-99"}, carlo)
        self.assertEqual(c, 200, o)
        self.assertIsNone(self.st.room("q3-g"))

    def test_only_end_calls_the_hook(self):
        # hand over, take over, Leave (which hands over) and a dropped connection never close the room: the page's End button is
        # the ONE caller of window.__pres.onEnd (kastr-pres.js endPress); kastr-templates.js calls presEnd only from that hook
        src = _read(os.path.join(HERE, "assets", "kastr-pres.js"))
        self.assertEqual(len(re.findall(r"__pres\.onEnd|\.onEnd\b", src)), 2, "endPress reads it; the export declares it")
        body = src[src.index("function endPress()"):src.index("function endNow()")]
        self.assertIn("window.__pres.onEnd", body)
        for fn in ("function leaveMine(", "function endMine(", "function setCur(", "function presOp("):
            i = src.index(fn)
            self.assertNotIn("onEnd", src[i:src.index("\n  }", i)])
        tpl = _read(os.path.join(HERE, "assets", "kastr-templates.js"))
        self.assertEqual(tpl.count('op: "presEnd"'), 1)
        i = tpl.index("async function closeTplRoom(")
        self.assertIn("return () => closeTplRoom(slug);", tpl[tpl.index("async function presEndHook("):i])
        self.assertIn("End the presentation and close", tpl)
        self.assertIn("Create a new room for this", tpl)
        self.assertIn("Close the room when the presentation ends", tpl)
        page = _read(os.path.join(HERE, "moq-watch-lite.html"))
        self.assertIn('"The presentation ended and " + roomTitle(room) + " was closed."', page)
        # a spoke's page learns why too: the spoke's merge of the hub's rooms keeps closedWhy (the lab caught it dropping it)
        serve = _read(os.path.join(HERE, "kastr_serve.py"))
        self.assertIn('"closedWhy": hub_obj.get("closedWhy") or {}', serve[serve.index("def _rooms_merge("):])


class Federation(Base):
    def setUp(self):
        super().setUp()
        self.hub = self.svc
        self.hub_key = self.svc.key
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.base = [base]
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: self.base[0], fed_token=lambda: self.fed)
        self.sadm = mint(self.spoke, "beta", host="ada-pc-5e6f", code="adm-1", room_code=CODE)

    def tearDown(self):
        self.spoke.close()
        super().tearDown()

    def test_spoke_forwards_to_the_hub(self):
        self.arrange()
        o, c = self.spoke.templates_api({"op": "save", "name": "From the spoke", "sections": ["layout", "settings"]},
                                        "Bearer " + self.sadm, "10.0.0.8")
        self.assertEqual(c, 200, o)
        self.assertEqual([t["name"] for t in self.hub.store.tplbook.list("room", "beta")], ["From the spoke"])
        self.assertEqual(self.spoke.store.tplbook.list("room", "beta"), [])    # one writer: the hub
        for op, it in kt.plan_ops({"pins": [], "spots": [], "grids": {}, "customGrids": {}, "split": []}, self.hub.store.board("beta"), "replace"):
            self.hub.store.board_apply("beta", op, it)
        sa = mint(self.spoke, "alpha", host="ada-pc-5e6f")
        o, c = self.spoke.templates_api({"op": "apply", "id": o["template"]["id"], "tokens": {"alpha": sa}}, "Bearer " + self.sadm, "10.0.0.8")
        self.assertEqual(c, 200, o)
        self.assertEqual(len(self.hub.store.board("beta")["pins"]), 3)
        # a dark hub: a clear answer
        self.base[0] = "http://127.0.0.1:9"
        o, c = self.spoke.templates_api({"op": "list"}, "Bearer " + self.sadm, "10.0.0.8")
        self.assertEqual((c, o.get("hubDown")), (503, True))

    def test_a_spoke_carries_template_notes_to_its_pages(self):
        # a co-presenter (or the main presenter) whose page beats on a spoke hears the hub's tplco / tplpres there, once, cleaned
        co = {"id": "a1b2c3d4e5f6", "kind": "tplco", "room": "beta", "tid": "t0123456789ab", "deck": "dc5fe7cc33f4f3931",
              "owner": "Kenton", "deny": ["Ada Backstage"], "at": time.time(), "code": "never-carried"}
        ready = {"id": "b1b2c3d4e5f6", "kind": "tplpres", "room": "beta", "tid": "t0123456789ab", "name": "Board meeting",
                 "by": "Kenton", "for": "Carlo Bos", "at": time.time()}
        feed = {"open": [], "rooms": {}, "away": {}, "inbox": [{"seq": 1, "to": "carlo-pc-3c4d", "item": co},
                                                             {"seq": 2, "to": "carlo-pc-3c4d", "item": ready},
                                                             {"seq": 3, "to": "carlo-pc-3c4d", "item": dict(co, id="c1b2c3d4e5f6", deck="../x")},
                                                             {"seq": 4, "to": "carlo-pc-3c4d", "item": dict(co, id="d1b2c3d4e5f6", deny=[])}]}
        self.spoke.personal_mirror_apply({"personal": feed})
        self.spoke.personal_mirror_apply({"personal": feed})   # the same long-poll answer again: not twice
        got = [x for x in self.spoke._p_inbox_take("carlo-pc-3c4d", time.time()) if str(x.get("kind")).startswith("tpl")]
        self.assertEqual(sorted(x["kind"] for x in got), ["tplco", "tplpres"])
        c = next(x for x in got if x["kind"] == "tplco")
        self.assertEqual((c["deck"], c["deny"], c["room"], c["owner"]), ("dc5fe7cc33f4f3931", ["Ada Backstage"], "beta", "Kenton"))
        self.assertNotIn("code", c)
        self.assertIsNone(kr.tpl_item_clean(dict(co, room="Not A Slug")))
        self.assertIsNone(kr.tpl_item_clean(dict(co, kind="rc")))

    def test_rooms_fed_needs_federation_and_a_vouch(self):
        body = {"op": "tpl", "vouch": {"room": "beta", "host": HOST, "adminAny": True}, "body": {"op": "list"}}
        self.assertEqual(self.hub.rooms_fed(body, None)[1], 403)
        self.assertEqual(self.hub.rooms_fed(dict(body, vouch={}), "Bearer " + self.fed)[1], 403)
        self.assertEqual(self.hub.rooms_fed(body, "Bearer " + self.fed)[1], 200)


class Page(unittest.TestCase):
    """The page half: assets/kastr-templates.js through the page's bridge (window.__ktpl)."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            cls.page = f.read()
        with open(os.path.join(HERE, "assets", "kastr-templates.js"), encoding="utf-8") as f:
            cls.js = f.read()

    def test_wired(self):
        self.assertIn('<script type="module" src="/assets/kastr-templates.js"></script>', self.page)
        self.assertIn("window.__ktpl = {", self.page)
        self.assertIn('id="optTpl"', self.page)
        self.assertIn('value: "tplApply"', self.page)                        # a room card's right-click
        self.assertIn("window.__tplUI?.roomSettings", self.page)             # Room settings' Templates row
        self.assertIn("window.__tplUI?.myRoom", self.page)                   # the My room dialog

    def test_never_on_an_open_relay_and_never_a_code_in_logs(self):
        self.assertRegex(self.js, r"available\s*=\s*\(\)\s*=>[^\n]*secured\(\)")
        self.assertNotRegex(self.js, r"console\.(log|info|warn)\([^)]*pcode")
        self.assertIn("/api/templates", self.js)

    def test_presentation_wiring(self):
        with open(os.path.join(HERE, "assets", "kastr-pres.js"), encoding="utf-8") as f:
            pres = f.read()
        # the template's start applies BEFORE the first publish (the room never sees slide 1 first)
        i_pre, i_pub = pres.index("tplPreset(mine, file, opts);"), pres.index("mine.startedMs = Math.round(performance.now() - t0);\n    publish();")
        self.assertLess(i_pre, i_pub)
        # 0.21.95: the same step, on the deck the start made (m0) -- End during the preparation cancels it (test_release_0_21_95_pres_end)
        self.assertIn("await ensureSlide(m0.idx); if (m0.idx && mine === m0) await postLive(m0, m0.idx);", pres)
        self.assertLess(pres.index("await ensureSlide(m0.idx);"), i_pub)
        self.assertIn("    tplSnap,   // 0.21.92", pres)
        # 0.21.91's audience switches: Save takes Ask to speak from audSnap, Start sets it before the first publish
        self.assertIn("const aud = window.__pres.audSnap() ||", pres)
        self.assertLess(pres.index("askPreset(mine, arguments[1]);"), i_pub)
        self.assertIn("ask: p.audience?.ask === false ? 0 : 1", self.js)
        self.assertIn('"Ask to speak"', self.js)
        # co-presenters' own control lists: the hub tells their devices; their page switches its own
        self.assertIn('it?.kind === "tplco"', self.page)
        self.assertIn("tplCo: (id, names) =>", pres)
        self.assertIn('op: "presCo"', self.js)
        # people who are NOT here stay in the template and are handed to the role code as they are (one seam: giveRole)
        self.assertIn("const giveRole = (x, r) =>", self.js)
        self.assertIn('placeholder = "or type a name"', self.js)
        # Update from this room re-takes a presentation I run there
        self.assertIn('body.add = ["pres"]', self.js)
        self.assertIn('it?.kind === "tplpres"', self.page)
        # Start presenting is the only thing that starts it; the deck is loaded before (nothing published)
        self.assertIn("window.__pres.startFromFile(R.file, {", self.js)
        self.assertEqual(self.js.count("startFromFile("), 1)
        self.assertIn('"Start presenting"', self.js)

    def test_every_presentation_toggle_rides_one_table(self):
        # Kenton: "Add any of the toggles to the presentation templates" -- one table on the page, any key kept by the hub
        with open(os.path.join(HERE, "assets", "kastr-pres.js"), encoding="utf-8") as f:
            pres = f.read()
        self.assertIn("const TPL_OPTS = [", pres)
        for key in ('key: "cm"', 'key: "rbg"', 'key: "am"', 'key: "ask"'):
            self.assertIn(key, pres)
        self.assertIn("for (const t of TPL_OPTS) if (Object.prototype.hasOwnProperty.call(oo, t.key))", pres)   # unknown keys skipped
        self.assertIn("tplOpts: () => TPL_OPTS.map(", pres)
        self.assertIn("o: p.opts || {}, tpl: t.id", self.js)
        self.assertIn("for (const o of optRows().filter((x) => x.sw))", self.js)
        c = kt.clean_pres({"presenters": [{"name": "Kenton", "main": True}],
                           "opts": {"am": 0, "ask": False, "cm": "reporter", "rbg": "asi-2", "see": 1, "Bad Key": 1, "x": {"no": 1},
                                    "url": "https://x", "n": 7}})
        self.assertEqual(c["opts"], {"am": 0, "ask": 0, "cm": "reporter", "rbg": "asi-2", "see": 1})   # a toggle from a newer page kept
        self.assertEqual((c["audience"], c["mode"], c["reporterBg"]), ({"muted": False, "ask": False}, "reporter", "asi-2"))
        old = kt.clean_pres({"presenters": [{"name": "Kenton"}], "audience": {"muted": True, "ask": False}, "mode": "sbs"})
        self.assertEqual(old["opts"], {"am": 1, "ask": 0, "cm": "sbs"})                                 # an older template: in step
        mix = kt.clean_pres({"presenters": [{"name": "Kenton"}], "audience": {"muted": True, "ask": True}, "opts": {"am": 0, "ask": 0, "see": 0}})
        self.assertEqual((mix["audience"], mix["opts"]["see"]), ({"muted": True, "ask": True}, 0))     # a named field the body carries wins

    def test_every_on_off_option_is_a_switch(self):
        # Kenton's standing rule: a toggle switch, never a plain checkbox (nor a lit-up chip standing in for one)
        self.assertNotIn('<input type="checkbox" aria-label', self.js)
        self.assertNotRegex(self.js, r'div\("ktchip" \+ \([^)]*\? " on"')
        self.assertIn('<span class="switch sm"><input type="checkbox"><i></i></span>', self.js)
        self.assertIn('<label class="switch sm"><input type="checkbox"><i></i></label>', self.js)
        for words in ('"Audience muted"', '"Ask to speak"', '"Locked"', '"Kept open"', '"View locked"', "mic and camera"):
            self.assertIn(words, self.js)

    def test_build_has_the_module(self):
        with open(os.path.join(HERE, "build.py"), encoding="utf-8") as f:
            self.assertIn('"--hidden-import", "kastr_templates"', f.read())


if __name__ == "__main__":
    unittest.main()
