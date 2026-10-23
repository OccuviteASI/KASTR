# -*- coding: utf-8 -*-
"""v0.21.84 -- the STREAM LIBRARY, server and box side (Kenton: "Library first."). One fleet-wide namespace outside every
room: lib/<host>/<op>/<leaf>.hang. Publishers heartbeat their own relay (POST /api/library with a library publisher token);
each relay keeps a LibraryRegistry, spokes push to the hub (rooms_fed op "library"), the hub keeps the catalogue
(LibraryBook -> library.json, handed over with the store bundle) and spokes mirror it through the bans long-poll
(libSince). A room adds a library stream with an ordinary board entry whose `from` is "lib" (no proof token). Boxes move
their no-room cameras into the library once their relay serves it, with aliases (aka) the hub rewrites every board from.

Run: python -m unittest discover -s tests
No processes: the box's pairs never start; hub and spoke are two AuthService instances talking over loopback HTTP."""
import base64
import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_rtsp  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1", "admin": "adm-1", "federation": "fed-1"}
HOST = "yard-0001"
HOME = "box-yard-0001"
P1 = "lib/yard-0001/yard/gate.hang"
P2 = "lib/yard-0001/yard/dock.hang"
OLD1 = HOME + "/yard-0001/yard/gate.hang"
JPEG = bytes((0xFF, 0xD8, 0xFF, 0xE0)) + b"still" * 20


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def store(codes=CODES):
    st = kr.AuthStore(tempfile.mkdtemp())
    if codes:
        st.set_codes(**codes)
    return st


def svc(st=None, **kw):
    return kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st or store(), **kw)


def member(s, room, code="pub-1", host="kenton-ab12", peer="10.0.0.1"):
    r, c = s.token({"room": room, "code": code, "host": host}, peer)
    assert c == 200, r
    return "Bearer " + r["tokens"]["member"]


def libtok(s, host=HOST, code="pub-1"):
    r, c = s.token({"library": True, "code": code, "host": host}, "10.0.0.9")
    assert c == 200, r
    return "Bearer " + r["tokens"]["member"]


def row(path=P1, **kw):
    return dict({"path": path, "label": "Gate", "kind": "rtsp", "state": "live", "low": True}, **kw)


def beat(s, tok, rows, **kw):
    s._lib_reg().beats.clear()   # (the 10 s heartbeat limit is tested on its own)
    return s.library_post(dict({"rows": rows}, **kw), tok, "10.0.0.9")


class Reserved(unittest.TestCase):
    def setUp(self):
        self.s = svc()

    def tearDown(self):
        self.s.close()

    def test_helper(self):
        self.assertEqual(kr.reserved_slug("lib"), kr.LIB_RESERVED)
        self.assertIsNone(kr.reserved_slug("library"))
        self.assertIsNone(kr.reserved_slug("yard"))
        self.assertEqual(kr.reserved_slug(HOME), kr.BOX_RESERVED)
        self.assertIsNone(kr.reserved_slug(HOME, HOST))          # the box itself
        self.assertEqual(kr.reserved_slug(HOME, "other-0002"), kr.BOX_RESERVED)

    def test_lib_refused_everywhere_a_slug_is_taken(self):
        s, st = self.s, self.s.store
        r, c = s.token({"room": "lib", "code": "pub-1", "host": "kenton-ab12"}, "10.0.0.1")
        self.assertEqual(c, 403, r)
        self.assertEqual(kr.register_room(st, {"slug": "lib", "plain": True})[1], 403)
        st.touch_room("yard")
        self.assertFalse(st.touch_room("lib"))
        self.assertIsNone(st.room("lib"))
        self.assertEqual(st.rename_room("yard", "lib")[1], 403)
        self.assertEqual(st.board_apply("lib", "pin", {"path": "yard/kenton-ab12/k/cam.hang", "from": "yard"})[1], 403)
        self.assertEqual(st.invite_create("lib", 3600)[2], 403)
        self.assertEqual(s.vehicle({"key": "x", "room": "lib"})[1], 403)
        # xshare targets: a stream of yard listed "into" lib or a box's home room is refused
        tok = member(s, "yard")
        d, c = s.xshare_post({"path": "yard/kenton-ab12/k/cam.hang", "to": ["lib", HOME], "tokens": {}}, tok)
        self.assertEqual(c, 403)
        self.assertEqual(d["refused"], {"lib": kr.LIB_RESERVED, HOME: kr.BOX_RESERVED})
        # a library token "covers" room lib -- the board and the chat door still refuse it
        lt = libtok(s)
        self.assertEqual(s.board_post({"room": "lib", "op": "spot", "target": P1}, lt)[1], 403)
        self.assertIn("LIB_ROOT", _read("kastr_serve.py").split("def _chat_api", 1)[1][:900])

    def test_box_home_room_is_the_box_s_own(self):
        s = self.s
        r, c = s.token({"room": HOME, "code": "pub-1", "host": HOST}, "10.0.0.2")
        self.assertEqual((c, r["role"]), (200, "publisher"))                     # the box itself
        r, c = s.token({"room": HOME, "code": "pub-1", "host": "kenton-ab12"}, "10.0.0.1")
        self.assertEqual((c, r["role"]), (200, "viewer"))                        # anyone else: may watch (a pin's proof), never publish
        cl = kr.verify_token(r["tokens"]["member"], s.key)
        self.assertEqual(kr.claims_role(cl), "viewer")
        r, c = s.token({"room": HOME, "code": "adm-1", "host": "kenton-ab12"}, "10.0.0.1")
        self.assertEqual(r["role"], "viewer")
        self.assertEqual(kr.register_room(s.store, {"slug": "box-other-0002", "plain": True})[1], 403)
        s.store.touch_room("yard")
        self.assertEqual(s.store.rename_room("yard", HOME)[1], 403)


class Tokens(unittest.TestCase):
    def setUp(self):
        self.s = svc()

    def tearDown(self):
        self.s.close()

    def test_library_publisher_token(self):
        s = self.s
        r, c = s.token({"library": True, "code": "pub-1", "host": HOST}, "10.0.0.9")
        self.assertEqual(c, 200, r)
        self.assertTrue(r["library"])
        cl = kr.verify_token(r["tokens"]["member"], s.key)
        self.assertEqual((cl["root"], cl["get"], cl["put"], cl["lib"]), ("", "lib", ["lib/" + HOST], HOST))
        self.assertEqual(kr.claims_identity(cl), ("lib", HOST))
        self.assertEqual(kr.claims_role(cl), "publisher")
        g = kr.claims_to_grant(cl)
        self.assertEqual(g["publish"], ["lib/" + HOST, "lib/" + HOST + "/**"])
        self.assertIn("lib/**", g["subscribe"])
        self.assertEqual(s.token({"library": True, "code": "adm-1", "host": HOST}, "10.0.0.9")[0]["role"], "admin")
        self.assertEqual(s.token({"library": True, "code": "view-1", "host": HOST}, "10.0.0.9")[1], 403)   # viewers never publish
        self.assertEqual(s.token({"library": True, "code": "wrong", "host": HOST}, "10.0.0.8")[1], 403)
        self.assertEqual(s.token({"library": True, "code": "pub-1", "host": "Bad Host"}, "10.0.0.9")[1], 400)
        self.assertEqual(s.token({"library": True, "code": "pub-1", "host": HOST, "invite": "ki-x"}, "10.0.0.9")[1], 403)
        s.bans.add({"room": "lib", "host": HOST, "until": int(time.time()) + 60})   # "Remove publisher"
        self.assertEqual(s.token({"library": True, "code": "pub-1", "host": HOST}, "10.0.0.9")[1], 403)

    def test_library_token_session_reads_no_listings(self):
        s = self.s
        cl = kr.verify_token(libtok(s)[7:], s.key)
        with mock.patch.object(s, "_xs_grant", side_effect=AssertionError("no listings for a library session")):
            g, c = s.session({"event": "connect", "id": "x1", "query": "jwt=" + libtok(s)[7:]}, "127.0.0.1")
        self.assertEqual(c, 200, g)
        self.assertEqual(s._sessions["x1"]["room"], "lib")
        self.assertEqual(s._sessions["x1"]["host"], HOST)
        self.assertTrue(cl)

    def test_viewer_token_scope(self):
        s = self.s
        boards = {"yard": {"pins": [{"path": P1, "from": "lib"}], "customGrids": {"g": {"slots": [{"cams": [P2]}]}}}}
        full = kr.verify_token(member(s, "yard", "view-1")[7:], s.key)
        self.assertEqual(kr.library_scope(full, "yard", boards), "lib")                          # viewers browse the whole library
        guest = dict(full, inv="ab12cd34")
        self.assertEqual(kr.library_scope(guest, "yard", boards),
                         sorted([P1, P2, kr.lib_low(P1), kr.lib_low(P2)]))                       # invite-link guests: the room's only
        self.assertEqual(kr.library_scope(dict(full, pg=1), "yard", {}), [])                     # a personal-room guest of an empty board
        lobby = kr.verify_token(member(s, "main")[7:], s.key)
        self.assertIsNone(kr.library_scope(lobby, "main", boards))
        self.assertIsNone(kr.library_scope({"vehicle": 1, "room": "yard", "put": ["yard/v-0001"]}, "yard", boards))
        self.assertIsNone(kr.library_scope(dict(kr.FEDERATION_CLAIMS), "yard", boards))
        # the API: a member token -> a library viewer token (never longer than the member token)
        vt = member(s, "yard", "view-1")
        o, c = s.library_token_api({}, vt, "10.0.0.1")
        self.assertEqual((c, o["scope"]), (200, "all"), o)
        full = kr.verify_token(vt[7:], s.key)
        lv = kr.verify_token(o["token"], s.key)
        self.assertEqual((lv["get"], lv["put"], lv["libv"]), ("lib", [], 1))
        self.assertLessEqual(lv["exp"], full["exp"])
        self.assertEqual(kr.claims_role(lv), "viewer")
        self.assertEqual(kr.claims_to_grant(lv)["publish"], [])
        self.assertEqual(s.library_token_api({}, member(s, "main"), "10.0.0.1")[1], 403)        # the Lobby has no library
        self.assertEqual(s.library_token_api({}, "Bearer " + o["token"], "10.0.0.1")[1], 403)    # not a library token itself
        self.assertEqual(s.library_token_api({}, libtok(s), "10.0.0.1")[1], 403)

    def test_auth_reports_the_capability(self):
        f = self.s.library_auth_fields()
        self.assertEqual((f["library"], f["libRoot"]), (1, "lib"))
        self.s._lib_book().set_on(False)
        f = self.s.library_auth_fields()
        self.assertEqual(f["library"], 0)
        self.assertIn("off", f["libraryWhy"])

    def test_preflight_a_room_named_lib_keeps_it_off(self):
        st = self.s.store
        st.rooms["lib"] = {"salt": "", "hash": "", "roomKey": "k", "at": time.time(), "persistent": True}   # from before 0.21.84
        on, why = self.s.library_state()
        self.assertFalse(on)
        self.assertIn("rename", why)
        out, _c = self.s.library_operator_view()
        self.assertFalse(out["preflight"]["ok"])
        self.assertEqual(self.s.token({"library": True, "code": "pub-1", "host": HOST}, "10.0.0.9")[0].get("library"), "off")


class Catalogue(unittest.TestCase):
    def setUp(self):
        self.s = svc()
        self.tok = libtok(self.s)

    def tearDown(self):
        self.s.close()

    def test_heartbeat_checks_and_the_version(self):
        s = self.s
        d, c = beat(s, self.tok, [row(), row(P2, state="asleep"), row("lib/other-0002/x/y.hang"),
                                  row("yard/yard-0001/yard/gate.hang"), row(kr.lib_low(P1)), row(P1 + "x", kind="weird")])
        self.assertEqual(c, 200, d)
        self.assertEqual(sorted(d["accepted"]), [P2, P1])
        self.assertEqual(len(d["refused"]), 4)
        reg = s._lib_reg()
        v = reg.ver
        beat(s, self.tok, [row(), row(P2, state="asleep")])
        self.assertEqual(reg.ver, v)                                  # a heartbeat that only refreshes `seen` moves nothing
        bv = s._lib_book().ver
        beat(s, self.tok, [row(), row(P2, state="asleep")])
        self.assertEqual(s._lib_book().ver, bv)
        beat(s, self.tok, [row(), row(P2, state="live")])
        self.assertGreater(reg.ver, v)                                # a state change does
        self.assertNotEqual(s._lib_book().ver, bv)
        # 10 s between heartbeats; a stop-only body is never held back
        self.assertEqual(s.library_post({"rows": [row()]}, self.tok, "10.0.0.9")[1], 429)
        d, c = s.library_post({"stop": [P2]}, self.tok, "10.0.0.9")
        self.assertEqual((c, d["stopped"]), (200, [P2]))
        rows = {r["path"]: r for r in s.library_get({}, None, None, "127.0.0.1")[0]["rows"]}
        self.assertTrue(rows[P2]["gone"])                             # a 1 h tombstone ("no longer in the library")
        self.assertEqual(rows[P1]["state"], "live")
        self.assertEqual(s.library_post({"rows": [row()]}, member(s, "yard"), "10.0.0.9")[1], 403)   # a room token is not one

    def test_per_host_cap_and_stills(self):
        s = self.s
        rows = [row()] + [row("lib/yard-0001/yard/c%d.hang" % i) for i in range(kr.LIB_PER_HOST + 2)]
        d, _c = beat(s, self.tok, rows)
        self.assertEqual(len(d["accepted"]), kr.LIB_PER_HOST)
        self.assertEqual(len(d["refused"]), 3)
        big = bytes((0xFF, 0xD8)) + b"x" * kr.LIB_STILL_MAX
        d, _c = beat(s, self.tok, [row()], stills={P1: base64.b64encode(JPEG).decode(), "lib/yard-0001/yard/c1.hang": base64.b64encode(big).decode()})
        self.assertIn("lib/yard-0001/yard/c1.hang", d["refused"])
        img, c = s.library_still({"path": P1}, None, None, "127.0.0.1")
        self.assertEqual((c, img), (200, JPEG))
        v = s._lib_reg().stills[P1][0]
        beat(s, self.tok, [row()], stills={P1: base64.b64encode(JPEG + b"2").decode()})
        self.assertEqual(s._lib_reg().stills[P1][0], v)               # at most one still a stream per 5 minutes ...
        beat(s, self.tok, [row(state="asleep")], stills={P1: base64.b64encode(JPEG + b"3").decode()})
        self.assertEqual(s._lib_reg().stills[P1][1], JPEG + b"3")      # ... sooner on a state change

    def test_reading_needs_a_member_and_guests_see_their_room_only(self):
        s = self.s
        beat(s, self.tok, [row(), row(P2)])
        d, c = s.library_get({}, member(s, "yard", "view-1"), None, "10.0.0.1")
        self.assertEqual((c, len(d["rows"])), (200, 2))
        self.assertEqual(s.library_get({"since": d["ver"]}, member(s, "yard", "view-1"), None, "10.0.0.1")[0].get("same"), True)
        self.assertEqual(s.library_get({}, None, None, "10.0.0.1")[1], 403)
        self.assertEqual(s.library_get({}, member(s, "main"), None, "10.0.0.1")[1], 403)
        s.store.board_apply("yard", "pin", {"path": P1, "from": "lib", "label": "Gate"})
        with mock.patch.object(kr, "claims_identity", wraps=kr.claims_identity):
            guest = kr.verify_token(member(s, "yard")[7:], s.key)
        gtok = "Bearer " + kr._mint(s.key, dict(guest, inv="ab12cd34"))
        d, c = s.library_get({}, gtok, None, "10.0.0.1")
        self.assertEqual([r["path"] for r in d["rows"]], [P1])
        self.assertEqual(d["rows"][0]["usedIn"], 1)
        self.assertEqual(s.library_still({"path": P2}, gtok, None, "10.0.0.1")[1], 403)
        d, c = s.library_get({"paths": P1 + "," + P2 + ",lib/x-0001/a/b.hang"}, member(s, "yard"), None, "10.0.0.1")
        self.assertEqual([r["path"] for r in d["rows"]], [P1, P2])
        self.assertEqual(d["missing"], ["lib/x-0001/a/b.hang"])

    def test_admin_hide_label_site_remove(self):
        s = self.s
        beat(s, self.tok, [row(), row(P2)])
        self.assertEqual(s.library_admin_api({"op": "hide", "path": P2}, member(s, "yard"), "10.0.0.1")[1], 403)   # only admins
        d, c = s.library_admin_api({"op": "hide", "path": P2}, member(s, "yard", "adm-1"), "10.0.0.1")
        self.assertEqual(c, 200, d)
        rows = s.library_get({}, member(s, "yard"), None, "10.0.0.1")[0]["rows"]
        self.assertEqual([r["path"] for r in rows], [P1])                          # hidden for everyone ...
        rows = s.library_get({}, member(s, "yard", "adm-1"), None, "10.0.0.1")[0]["rows"]
        self.assertTrue([r for r in rows if r["path"] == P2][0]["hidden"])          # ... but admins (to unhide it)
        self.assertEqual(s.board_post({"room": "yard", "op": "pin", "path": P2, "from": "lib"}, member(s, "yard"))[1], 403)
        s.library_admin_api({"op": "label", "path": P1, "label": "North gate"}, None, "127.0.0.1")   # the hub operator's page
        r1 = [r for r in s.library_get({}, member(s, "yard"), None, "10.0.0.1")[0]["rows"] if r["path"] == P1][0]
        self.assertEqual((r1["label"], r1["edited"]), ("North gate", True))
        beat(s, self.tok, [row(label="Gate 2"), row(P2)])
        r1 = [r for r in s.library_get({}, member(s, "yard"), None, "10.0.0.1")[0]["rows"] if r["path"] == P1][0]
        self.assertEqual(r1["label"], "North gate")                                 # an admin's label wins over the publisher's
        node = r1["node"]
        s.library_admin_api({"op": "site", "node": node, "site": "Mendon"}, None, "127.0.0.1")
        self.assertEqual([r for r in s.library_get({}, member(s, "yard"), None, "10.0.0.1")[0]["rows"] if r["path"] == P1][0]["site"], "Mendon")
        d, c = s.library_admin_api({"op": "remove", "host": HOST}, member(s, "yard", "adm-1"), "10.0.0.1")
        self.assertEqual(c, 200, d)
        self.assertIsNotNone(s.bans.hit("lib", HOST))
        self.assertEqual(beat(s, self.tok, [row()])[1], 403)                          # its heartbeats refused
        # persisted: a hub restart keeps the hide, the label and the site
        st2 = kr.AuthStore(s.store.state_dir)
        e = st2.libbook.entries
        self.assertTrue(e[P2]["hidden"])
        self.assertEqual(e[P1]["adminLabel"], "North gate")
        self.assertEqual(st2.libbook.sites[node]["name"], "Mendon")

    def test_kill_switch(self):
        s = self.s
        beat(s, self.tok, [row()])
        out, c = s.library_operator({"on": False})
        self.assertEqual((c, out["on"], out["switch"]), (200, False, False))
        d, c = s.library_get({}, member(s, "yard"), None, "10.0.0.1")
        self.assertEqual((d["on"], d["rows"]), (False, []))
        d, c = beat(s, self.tok, [row()], stop=[P2])
        self.assertEqual((c, d.get("off")), (403, True))
        self.assertEqual(s.board_post({"room": "yard", "op": "pin", "path": P1, "from": "lib"}, member(s, "yard"))[1], 403)
        self.assertEqual(s.library_token_api({}, member(s, "yard"), "10.0.0.1")[1], 403)
        self.assertFalse(kr.AuthStore(s.store.state_dir).libbook.on)                 # kept across a restart
        s.library_operator({"on": True})
        self.assertTrue(s.library_state()[0])
        self.assertIn("/api/relay/library", kr.GUARDED_POSTS)


class Board(unittest.TestCase):
    def setUp(self):
        self.s = svc()
        self.tok = libtok(self.s)
        beat(self.s, self.tok, [row(), row(P2)])

    def tearDown(self):
        self.s.close()

    def test_pin_spot_and_cgrid_from_the_library_need_no_proof(self):
        s = self.s
        tok = member(s, "yard")
        d, c = s.board_post({"room": "yard", "op": "pin", "path": P1, "from": "lib", "label": "Gate"}, tok)
        self.assertEqual(c, 200, d)
        self.assertEqual(d["pins"][0]["from"], "lib")
        d, c = s.board_post({"room": "yard", "op": "spot", "target": P1, "ts": int(time.time() * 1000)}, tok)
        self.assertEqual(c, 200, d)
        d, c = s.board_post({"room": "yard", "op": "pin", "path": "lib/nobody-0009/x/y.hang", "from": "lib"}, tok)
        self.assertEqual(c, 404, d)                                                    # a known entry only
        grid = {"room": "yard", "op": "cgrid", "id": "g1", "name": "Yard", "slots": [
            {"rect": [0, 0, 12, 12], "cams": [P1]}, {"rect": [12, 0, 12, 12], "cams": [P2]}]}
        d, c = s.board_post(grid, tok)
        self.assertEqual(c, 200, d)
        self.assertIn("g1", d["customGrids"])
        self.assertEqual(s.board_post(dict(grid, slots=[{"rect": [0, 0, 12, 12], "cams": ["lib/nobody-0009/x/y.hang"]}]), tok)[1], 404)
        self.assertEqual(s.board_post({"room": "yard", "op": "pin", "path": P1, "from": "lib"}, member(s, "yard", "view-1"))[1], 403)   # viewers never
        me = kr.personal_key("Kenton")
        self.assertTrue(me)

    def test_board_listings_only_compatibility_rows(self):
        boards = {"yard": {"pins": [{"path": P1, "from": "lib"}, {"path": "north/k-ab12/k/c.hang", "from": "north"}],
                           "customGrids": {"g": {"slots": [{"cams": [P2]}]}}}}
        out = kr.board_listings(boards)
        self.assertTrue(out[(P1, "yard")]["lib"])
        self.assertTrue(out[(P2, "yard")]["lib"] and out[(P2, "yard")]["cg"])
        self.assertNotIn("lib", out[("north/k-ab12/k/c.hang", "yard")])
        reg = kr.XShareRegistry()
        for i in range(kr.XSHARE_MAX):
            reg.apply("r%d/h-0001/x/c.hang" % i, "r%d" % i, ["yard"])
        self.assertTrue(reg.apply("rz/h-0001/x/c.hang", "rz", ["yard"])[1])           # the registry is full ...
        kr.board_sync_registry(reg, boards)
        self.assertIn((P1, "yard"), reg.items)                                         # ... a compatibility row still fits
        self.assertTrue(reg.items[(P1, "yard")]["lib"])
        ver, rows = reg.snapshot()
        self.assertTrue(rows[-1]["lib"] and not rows[0]["lib"])                        # last (an older spoke keeps the first 256)
        rep = kr.XShareRegistry()
        rep.replace(rows, ver)
        self.assertTrue(rep.items[(P1, "yard")]["lib"])
        # a real Show-in-rooms listing of the same path is no compatibility row
        reg2 = kr.XShareRegistry()
        kr.board_sync_registry(reg2, boards)
        reg2.apply(P1, "lib", ["yard"], "Gate", "rtsp", "yard")
        self.assertFalse(reg2.items[(P1, "yard")]["lib"])

    def test_old_pages_get_the_grant_through_the_compat_listing(self):
        s = self.s
        s.board_post({"room": "yard", "op": "pin", "path": P1, "from": "lib", "label": "Gate"}, member(s, "yard"))
        g = s._xs_grant({"publish": [], "subscribe": ["yard", "yard/**"]}, "yard")
        self.assertIn(P1, g["subscribe"])
        items = s.xshare_get("yard", member(s, "yard"))[0]["items"]
        self.assertTrue([i for i in items if i["path"] == P1][0]["lib"])              # a 0.21.84 page skips the row

    def test_xshare_from_the_library(self):
        s = self.s
        d, c = s.xshare_post({"path": P1, "to": ["north"], "tokens": {"north": member(s, "north", host=HOST)[7:]},
                              "label": "Gate", "kind": "rtsp"}, self.tok)
        self.assertEqual(c, 200, d)
        self.assertEqual(d["to"], ["north"])
        self.assertEqual(s.xshare_post({"path": "lib/other-0002/x/y.hang", "to": ["north"],
                                        "tokens": {"north": member(s, "north")[7:]}}, self.tok)[1], 403)   # its own host only

    def test_alias_rewrites_every_board(self):
        s, st = self.s, self.s.store
        old_low = kr.lib_low(OLD1)
        tok = member(s, "yard")
        st.board_apply("yard", "pin", {"path": OLD1, "from": HOME, "label": "Gate"})
        st.board_apply("yard", "spot", {"target": OLD1, "ts": int(time.time() * 1000)})
        st.board_apply("yard", "spotOrder", {"targets": [OLD1]})
        st.board_apply("north", "cgrid", {"id": "g1", "grid": {"name": "G", "slots": [{"rect": [0, 0, 12, 12], "cams": [OLD1, old_low]}],
                                                                "gap": 2, "sens": "medium"}})
        bv = st.board_ver
        beat(s, self.tok, [row(aka=[OLD1, "yard/other-0002/yard/gate.hang", "lib/x-0001/a.hang"])])
        b = st.board("yard")
        self.assertEqual([p["path"] for p in b["pins"]], [P1])
        self.assertEqual(b["pins"][0]["from"], "lib")
        self.assertEqual(b["spots"][0]["target"], P1)
        self.assertEqual(b["spotOrder"], [P1])
        self.assertEqual(st.board("north")["customGrids"]["g1"]["slots"][0]["cams"], [P1, kr.lib_low(P1)])
        self.assertGreater(st.board_ver, bv)
        e = st.libbook.entries[P1]
        self.assertEqual(sorted(e["aka"]), [OLD1])                                     # only its own host's, same tail
        bv = st.board_ver
        beat(s, self.tok, [row(aka=[OLD1])])
        self.assertEqual(st.board_ver, bv)                                              # first sight only ...
        st.board_apply("west", "pin", {"path": OLD1, "from": HOME, "label": "Gate"})    # ... an older page pins the old path again:
        s._lib_rewrite(st.libbook.aka_map())                                            # the hub's 30 s tick puts it right
        self.assertEqual(st.board("west")["pins"][0]["path"], P1)
        bv = st.board_ver
        self.assertEqual(st.libbook.resolve(OLD1), P1)
        d, c = s.library_get({"paths": OLD1}, tok, None, "10.0.0.1")
        self.assertEqual((d["rows"][0]["path"], d["rows"][0]["alias"]), (P1, OLD1))
        d, c = s.board_post({"room": "east", "op": "pin", "path": OLD1, "from": "lib"}, member(s, "east"))
        self.assertEqual(c, 400, d)                                                    # (an old path is a room's, not "lib")
        # a camera switched back to its room: the stop names where it went, boards follow
        d, c = s.library_post({"stop": [P1], "moved": {P1: "yard/yard-0001/yard/gate.hang"}}, self.tok, "10.0.0.9")
        self.assertEqual(c, 200, d)
        self.assertEqual(st.board("yard")["pins"][0]["path"], "yard/yard-0001/yard/gate.hang")
        beat(s, self.tok, [row()])                                                      # switched on again (or the fleet switch)
        self.assertEqual(st.board("yard")["pins"][0]["path"], P1)                       # the boards follow it back in

    def test_board_same_room_follows_a_camera_into_the_library(self):
        self.assertTrue(kr.board_same_room(HOME + "/yard-0001/yard/grid.hang", P1))
        self.assertFalse(kr.board_same_room(HOME + "/yard-0001/yard/grid.hang", "lib/other-0002/yard/x.hang"))


class HubAndSpoke(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        self.base = ["http://127.0.0.1:%d" % self.hub.httpd.server_address[1]]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: self.base[0], fed_token=lambda: self.fed)
        if not self._testMethodName.endswith("_says_off"):
            self.poll()                                                         # the hub's first word (switch on)
            self.tok = libtok(self.spoke)

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def poll(self, since=None):
        d, c = self.hub.bans_for_spoke("Bearer " + self.fed, lib_since=since if since is not None else
                                       (self.spoke._lib_mirror().get("ver") or "0"))
        self.assertEqual(c, 200, d)
        self.spoke.library_mirror_apply(d)
        return d

    def test_spoke_before_its_hub_says_off(self):
        self.assertFalse(self.spoke.library_state()[0])                       # a hub that never said = an older KASTR
        self.assertEqual(self.spoke.token({"library": True, "code": "pub-1", "host": HOST}, "10.0.0.9")[1], 403)

    def test_push_mirror_and_libsince_gating(self):
        self.poll()
        self.assertTrue(self.spoke.library_state()[0])
        tok = libtok(self.spoke)
        d, c = beat(self.spoke, tok, [row(aka=[OLD1])])
        self.assertEqual(c, 200, d)
        self.assertTrue(self.spoke._lib_wake().is_set() or P1 in self.hub.store.libbook.entries)   # the push loop is woken ...
        self.spoke._lib_push()                                               # (rooms_fed op library)
        self.assertIn(P1, self.hub.store.libbook.entries)
        self.assertEqual(self.hub.store.libbook.entries[P1]["node"], kr._machine_node() or "relay")
        d = self.poll()
        self.assertIn("library", d)
        self.assertIn(P1, self.spoke._lib_mirror()["rows"])
        d = self.poll()
        self.assertNotIn("library", d)                                       # the same version: no rows
        self.assertIn("libraryVer", d)
        d0, _c = self.hub.bans_for_spoke("Bearer " + self.fed)
        self.assertNotIn("libraryVer", d0)                                   # an older spoke never asks: its reply never grows
        # keepalives: no version change, the hub knows the node's version
        st = self.spoke.__dict__["_lib_pushed"]
        st["at"] = 0
        self.assertTrue(self.spoke._lib_push())
        v = self.hub.store.libbook.ver
        st["at"] = 0
        self.spoke._lib_push()
        self.assertEqual(self.hub.store.libbook.ver, v)

    def test_hub_dark_fail_closed_never_open(self):
        self.poll()
        beat(self.spoke, self.tok, [row(), row(P2)])
        self.spoke._lib_push()
        self.hub.library_admin_api({"op": "hide", "path": P2}, None, "127.0.0.1")
        self.poll()
        self.assertTrue(self.spoke._lib_mirror()["rows"][P2]["hidden"])
        self.base[0] = "http://127.0.0.1:9"                                   # the hub goes dark
        self.spoke._lib_mirror()["heard"] = 0
        d, c = self.spoke.library_get({}, member(self.spoke, "yard"), None, "10.0.0.1")
        self.assertEqual(c, 200)
        self.assertTrue(d["hubDown"])
        self.assertEqual([r["path"] for r in d["rows"]], [P1])               # local entries still appear; the hidden stays hidden
        self.assertEqual(self.spoke.library_admin_api({"op": "unhide", "path": P2}, member(self.spoke, "yard", "adm-1"), "10.0.0.1")[1], 503)
        self.assertEqual(self.spoke.board_post({"room": "yard", "op": "pin", "path": P1, "from": "lib"}, member(self.spoke, "yard"))[1], 503)
        d, c = beat(self.spoke, self.tok, [row()])
        self.assertEqual(c, 200)                                              # local publishers keep publishing
        self.assertTrue(d["hubDown"])
        # a spoke restarted while the hub is dark: the mirror loads from hub-library.json (hidden included)
        sp2 = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4454, kr.AuthStore(self.spoke.store.state_dir),
                             hub=lambda: self.base[0], fed_token=lambda: self.fed)
        try:
            self.assertTrue(sp2.library_state()[0])
            self.assertTrue(sp2._lib_mirror()["rows"][P2]["hidden"])
            self.assertEqual(sp2.library_known(P2)[0], None)
        finally:
            sp2.close()

    def test_admin_on_a_spoke_goes_to_the_hub(self):
        self.poll()
        beat(self.spoke, self.tok, [row(), row(P2)])
        self.spoke._lib_push()
        d, c = self.spoke.library_admin_api({"op": "hide", "path": P2}, member(self.spoke, "yard", "adm-1"), "10.0.0.1")
        self.assertEqual(c, 200, d)
        self.assertTrue(self.hub.store.libbook.entries[P2]["hidden"])
        self.assertTrue(self.hub.library_poll_fields("0")["library"]["rows"])

    def test_spoke_board_pin_from_the_library(self):
        self.poll()
        beat(self.spoke, self.tok, [row()])
        self.spoke._lib_push()
        self.poll()
        self.hub.store.touch_room("yard")
        d, c = self.spoke.board_post({"room": "yard", "op": "pin", "path": P1, "from": "lib", "label": "Gate"}, member(self.spoke, "yard"))
        self.assertEqual(c, 200, d)
        self.assertEqual(self.hub.store.board("yard")["pins"][0]["path"], P1)

    def test_still_from_the_hub(self):
        self.poll()
        hub_tok = libtok(self.hub, "dock-0002")
        beat(self.hub, hub_tok, [row("lib/dock-0002/d/cam.hang")], stills={"lib/dock-0002/d/cam.hang": base64.b64encode(JPEG).decode()})
        self.poll()
        img, c = self.spoke.library_still({"path": "lib/dock-0002/d/cam.hang"}, member(self.spoke, "yard"), None, "10.0.0.1")
        self.assertEqual((c, img), (200, JPEG))

    def test_handover_and_handback_carry_the_catalogue(self):
        tok = libtok(self.hub)
        beat(self.hub, tok, [row(), row(P2)])
        self.hub.library_admin_api({"op": "hide", "path": P2}, None, "127.0.0.1")
        b = self.hub.store.export_bundle()
        new = store()
        new.import_bundle(b)
        self.assertTrue(new.libbook.entries[P2]["hidden"])
        time.sleep(0.01)
        new.libbook.admin("unhide", path=P2)
        self.assertEqual(self.hub.store.merge_bundle(new.export_bundle())["library"] >= 1, True)
        self.assertFalse(self.hub.store.libbook.entries[P2]["hidden"])          # the hand-back: the later unhide wins
        v = self.hub.store.ver
        self.hub.store.libbook.admin("hide", path=P2)
        self.assertGreater(self.hub.store.ver, v)                               # the standby's replica copies it again


class OnDemand(unittest.TestCase):
    def test_sync_and_demand_for_lib(self):
        import kastr_serve as ks
        with mock.patch.dict(ks.ONDEMAND, {}, clear=True):
            w = ks.ondemand_sync("lib", HOST, [{"broadcast": P1, "label": "Gate", "idle": True},
                                               {"broadcast": "yard/" + HOST + "/yard/x.hang"}])
            self.assertEqual(w, {})
            self.assertIn(P1, ks.ONDEMAND)
            self.assertNotIn("yard/" + HOST + "/yard/x.hang", ks.ONDEMAND)
            with mock.patch.object(ks, "ONDEMAND_POKE", None):
                self.assertTrue(ks.ondemand_touch(P1))
            self.assertIn(P1, ks.ondemand_sync("lib", HOST, [{"broadcast": P1, "idle": True}]))

    def test_od_tick_groups_per_relay_and_room(self):
        b = kastr_rtsp.Bridge.__new__(kastr_rtsp.Bridge)
        b.web_base_for = lambda key: "http://127.0.0.1:1"
        posts = []

        def post(url, body):
            posts.append(body)
            return {"wanted": {}}
        mk = lambda br, tok: mock.Mock(broadcast=br, relay="http://127.0.0.1:4443/?jwt=" + tok, label="", running=True, lowPub=None,
                                       sleepy=True, wantedAt=None, standby=True, wokeAt=0)
        b.od_tick([mk(P1, "LIBTOK"), mk(HOME + "/" + HOST + "/yard/x.hang", "ROOMTOK")], post=post)
        self.assertEqual(sorted(p["token"] for p in posts), ["LIBTOK", "ROOMTOK"])   # each room's own token


SAVED_ON_AIR = kastr_rtsp.xs_on_air


class BoxSandbox(unittest.TestCase):
    def setUp(self):
        self._saved = [(kastr_rtsp.subprocess, "Popen", kastr_rtsp.subprocess.Popen),
                       (kastr_rtsp.Bridge, "legacy_sweep", kastr_rtsp.Bridge.legacy_sweep),
                       (kastr_rtsp.Bridge, "sweep_orphans", kastr_rtsp.Bridge.sweep_orphans),
                       (kastr_rtsp.Publisher, "start", kastr_rtsp.Publisher.start),
                       (kastr_rtsp, "mint_member", kastr_rtsp.mint_member),
                       (kastr_rtsp, "xs_on_air", kastr_rtsp.xs_on_air)]

        def no_spawn(*a, **k):
            raise AssertionError("a process was spawned")
        kastr_rtsp.subprocess.Popen = no_spawn
        kastr_rtsp.Bridge.legacy_sweep = lambda self: 0
        kastr_rtsp.Bridge.sweep_orphans = lambda self: 0
        kastr_rtsp.Publisher.start = lambda self: None
        kastr_rtsp.xs_on_air = lambda pub, now=None: True
        self.mints = []

        def mint(base, room, access, code, timeout=5, host=None):
            self.mints.append(room)
            return "token", base + "/?jwt=room-" + room, "member"
        kastr_rtsp.mint_member = mint
        self.tmp = tempfile.TemporaryDirectory()
        self.lines, self.posts = [], []
        self.cap = True
        self.reply = None

    def tearDown(self):
        for obj, name, val in reversed(self._saved):
            setattr(obj, name, val)
        self.tmp.cleanup()

    def post(self, url, body, bearer):
        self.posts.append((url, json.loads(json.dumps(body)), bearer))
        if self.reply:
            return self.reply
        acc = [r["path"] for r in body.get("rows") or []]
        return {"ok": True, "accepted": acc, "refused": {}, "stopped": list(body.get("stop") or [])}, 200

    def bridge(self, room=HOME):
        b = kastr_rtsp.Bridge(state_dir=self.tmp.name, log=lambda m, *a, **k: self.lines.append(str(m)), host_slug=HOST)
        b.moq = "moq"
        b.lib_cap_fetch = lambda relay: self.cap
        b.lib_mint = lambda relay, access, host: ("token", relay + "/?jwt=LIBTOK", "publisher")
        b._lib_ensure = lambda: None              # no background loop in a test
        b._xs_ensure = lambda: None
        b._xs_post = lambda url, body, bearer: ({"ok": True, "to": body.get("to") or [], "refused": {}}, 200)
        b.set_session(room, "pub-1", "", "http://127.0.0.1:4443")
        return b

    def camera(self, b, path=HOME + "/yard-0001/yard/gate.hang", label="Gate", relay_room=HOME):
        feed = b.add("test://pattern")
        b._lib_cap("http://127.0.0.1:4443")       # the relay's word, as the loop / restore ask it
        b.publish(feed.id, path, "http://127.0.0.1:4443/?jwt=room-" + relay_room, audio=False, keep=True, label=label)
        return feed

    def doc(self):
        with open(os.path.join(self.tmp.name, "rtsp-feeds.json"), encoding="utf-8") as f:
            return json.load(f)


class BoxMigration(BoxSandbox):
    def test_no_room_box_goes_into_the_library_with_its_alias(self):
        b = self.bridge()
        f = self.camera(b)
        pub = b._pubs[f.id]
        self.assertEqual(pub.broadcast, P1)                                 # the same tail under lib/
        self.assertIn("jwt=LIBTOK", pub.relay)
        self.assertEqual(f.lib_aka and sorted(f.lib_aka), [OLD1])
        self.assertTrue(f.lib)
        self.assertEqual(self.doc()["feeds"][0]["broadcast"], OLD1)         # the record keeps the room path
        self.assertEqual(self.doc()["feeds"][0]["lib"], True)
        out = b.lib_tick(post=self.post)
        (url, body, bearer), = self.posts
        self.assertEqual(url, "http://127.0.0.1:4444/api/library")
        self.assertEqual(bearer, "LIBTOK")
        self.assertEqual(body["rows"][0]["path"], P1)
        self.assertEqual(body["rows"][0]["aka"], [OLD1])
        self.assertEqual(body["rows"][0]["state"], "live")
        self.assertEqual(f.lib_status, "ok")
        self.assertTrue(out)
        b.lib_tick(post=self.post)
        self.assertEqual(len(self.posts), 1)                                # never twice within 10 s ...
        self.assertTrue(b._lib()["due"])                                    # ... but the loop comes back for it
        # the page re-posts the room path: the same pair (no restart)
        again = b.publish(f.id, OLD1, "http://127.0.0.1:4443/?jwt=room-" + HOME, audio=False, label="Gate")
        self.assertIs(again, pub)
        self.assertEqual(pub.info()["library"]["on"], True)
        self.assertEqual(pub.info()["library"]["base"], OLD1)

    def test_relay_without_the_library_keeps_the_home_room(self):
        self.cap = False
        b = self.bridge()
        f = self.camera(b)
        self.assertEqual(b._pubs[f.id].broadcast, OLD1)
        b.lib_tick(post=self.post)
        self.assertEqual(self.posts, [])
        self.cap = True                                                     # the relay (and hub) update: the loop moves it
        b._lib()["caps"].clear()
        b.lib_tick(post=self.post)
        self.assertEqual(b._pubs[f.id].broadcast, P1)

    def test_real_room_box_stays_off_until_switched_on(self):
        b = self.bridge("north")
        f = self.camera(b, "north/yard-0001/yard/gate.hang", relay_room="north")
        self.assertEqual(b._pubs[f.id].broadcast, "north/yard-0001/yard/gate.hang")
        r = b.set_lib(f.id, True)
        self.assertTrue(r["moved"])
        self.assertEqual(b._pubs[f.id].broadcast, P1)
        self.assertEqual(f.xs, ["north"])                                   # listed back into its own room
        self.assertEqual(f.xs_auto, "north")
        r = b.set_lib(f.id, False)
        self.assertEqual(b._pubs[f.id].broadcast, "north/yard-0001/yard/gate.hang")
        self.assertEqual(f.xs, [])
        self.assertEqual(b._lib()["stop"][P1][0], "north/yard-0001/yard/gate.hang")
        b.lib_tick(post=self.post)
        (_u, body, _b), = self.posts
        self.assertEqual((body["stop"], body["moved"]), ([P1], {P1: "north/yard-0001/yard/gate.hang"}))
        self.assertEqual(b._lib()["stop"], {})

    def test_master_switch_ini_and_state(self):
        b = self.bridge()
        f = self.camera(b)
        out = b.set_lib_master(False)
        self.assertFalse(out["master"])
        self.assertEqual(b._pubs[f.id].broadcast, OLD1)
        self.assertEqual(self.doc()["library"], "off")
        b2 = kastr_rtsp.Bridge(state_dir=self.tmp.name, log=lambda m, *a, **k: None, host_slug=HOST)
        self.assertFalse(b2.lib_master)                                     # kept in rtsp-feeds.json
        b.set_lib_master(True)
        self.assertEqual(b._pubs[f.id].broadcast, P1)
        with mock.patch.object(kastr_rtsp, "LIBRARY_ENABLED", False):        # kastr.ini library = off
            self.assertFalse(b._lib_want(f, OLD1))
            self.assertIn("kastr.ini", b.lib_public()["why"])
        self.assertIn('ini.get("library")', _read("kastr.py"))

    def test_states_stills_and_unpublish(self):
        b = self.bridge()
        f = self.camera(b)
        pub = b._pubs[f.id]
        b.lib_grab = lambda p: JPEG
        b.lib_grab_sync = True
        b.lib_tick(post=self.post)
        b._lib()["beatAt"].clear()
        b.lib_tick(post=self.post)
        self.assertEqual(base64.b64decode(self.posts[-1][1]["stills"][P1]), JPEG)
        pub.standby, pub.sleepy = True, True
        self.assertEqual(kastr_rtsp.lib_state(pub), "asleep")
        pub.standby = False
        kastr_rtsp.xs_on_air = lambda p, now=None: False
        self.assertEqual(kastr_rtsp.lib_state(pub), "dark")
        b.unpublish(f.id)
        self.assertIn(P1, b._lib()["stop"])
        b._lib()["beatAt"].clear()
        b.lib_tick(post=self.post)
        self.assertEqual(self.posts[-1][1]["stop"], [P1])

    def test_shutdown_never_withdraws(self):
        b = self.bridge()
        self.camera(b)
        b.shutdown()
        self.assertEqual(b._lib()["stop"], {})

    def test_off_answer_moves_cameras_back(self):
        b = self.bridge()
        f = self.camera(b)
        self.reply = ({"ok": False, "off": True, "error": "off"}, 403)
        b.lib_tick(post=self.post)
        self.reply = None
        b._lib()["beatAt"].clear()
        b.lib_tick(post=self.post)
        self.assertEqual(b._pubs[f.id].broadcast, OLD1)

    def test_restore_and_api(self):
        doc = {"room": HOME, "access": "pub-1", "roomCode": "", "relay": "http://127.0.0.1:4443",
               "feeds": [{"url": "test://pattern", "broadcast": OLD1, "keep": True, "label": "Gate", "audio": False,
                          "lib": True, "libAka": {OLD1: int(time.time())}}]}
        with open(os.path.join(self.tmp.name, "rtsp-feeds.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        b = kastr_rtsp.Bridge(state_dir=self.tmp.name, log=lambda m, *a, **k: None, host_slug=HOST)
        b.moq = "moq"
        b.lib_cap_fetch = lambda relay: True
        b.lib_mint = lambda relay, access, host: ("token", relay + "/?jwt=LIBTOK", "publisher")
        b._lib_ensure = lambda: None
        self.assertEqual(b.restore(mint=lambda: "http://127.0.0.1:4443/?jwt=room-" + HOME), 1)
        f = list(b._feeds.values())[0]
        self.assertEqual(b._pubs[f.id].broadcast, P1)                       # straight into the library (no second move)
        self.assertEqual(list(f.lib_aka), [OLD1])

        class H:
            def __init__(self, path, body=None, command="POST"):
                raw = json.dumps(body).encode() if body is not None else b""
                self.path, self.command = path, command
                self.headers = {"Content-Length": str(len(raw)), "Host": "127.0.0.1:8000"}
                self.client_address = ("127.0.0.1", 50000)
                self.rfile, self.wfile = io.BytesIO(raw), io.BytesIO()

            def send_response(self, code):
                self.code = code

            def send_header(self, k, v):
                pass

            def end_headers(self):
                pass
        with mock.patch.object(kr, "is_local", lambda h: True):
            h = H("/api/rtsp/library", None, "GET")
            kastr_rtsp.handle_api(h, b, "/api/rtsp/library")
            d = json.loads(h.wfile.getvalue())
            self.assertEqual((d["master"], d["feeds"][0]["library"]["on"]), (True, True))
            h = H("/api/rtsp/library", {"id": f.id, "on": None})
            kastr_rtsp.handle_api(h, b, "/api/rtsp/library")
            self.assertEqual(h.code, 200)
            self.assertEqual(json.loads(h.wfile.getvalue())["library"]["switch"], None)
            h = H("/api/rtsp/library", {"id": f.id, "on": "yes"})
            kastr_rtsp.handle_api(h, b, "/api/rtsp/library")
            self.assertEqual(h.code, 400)

    def test_show_in_rooms_from_the_library(self):
        b = self.bridge()
        f = self.camera(b)
        f.xs = ["north"]
        posts = []
        out = b.xs_tick(post=lambda url, body, bearer: (posts.append((body, bearer)) or ({"ok": True, "to": body.get("to") or [], "refused": {}}, 200)),
                        mint=lambda base, room, access, code: ("token", base + "/?jwt=room-" + room, "member"))
        self.assertEqual(out[P1], {"north": "ok"})
        body, bearer = posts[0]
        self.assertEqual((body["path"], bearer), (P1, "LIBTOK"))              # proven by the library token
        with self.assertRaises(ValueError):
            b.set_xs(f.id, ["lib"])


class Sources(unittest.TestCase):
    def test_proxy_and_routes(self):
        s = _read("kastr_serve.py")
        self.assertIn('"/api/library", "/api/library/still"', s)
        self.assertIn('"/api/library", "/api/library/token", "/api/library/admin"', s)
        r = _read("kastr_relay.py")
        for p in ('path == "/api/library"', 'path == "/api/library/still"', 'path == "/api/library/token"', 'path == "/api/library/admin"',
                  'path == "/api/relay/library"'):
            self.assertIn(p, r)
        self.assertIn("lib_cap_fetch = kastr_rtsp.relay_library", s)


if __name__ == "__main__":
    unittest.main()
