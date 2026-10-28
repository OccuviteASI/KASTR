# -*- coding: utf-8 -*-
"""v0.21.66, Kenton 2026-10-14:
(n) drag to rearrange the spotlight -- the room board's `spotOrder` (op spotOrder {targets});
(o) back to the spotlight -- a stage button and the S key;
(e) grids of cameras from any room -- personal (this device) or the ROOM's (`customGrids`, ops cgrid / cgridDel); a camera of
    another room in a room grid is listed into the room (flag `cg`), its saver proves it can see it;
plus: the grid editor reserves room for its toolbar and camera list (never on top of the grid), and a grid of ANOTHER room
pinned / listed here takes this room's grid tools (its owner posts its geometry: op gridMeta; reads carry `gridMetas`; a
camera split out of it is listed into the room).

Run: python -m unittest discover -s tests
"""
import io, os, re, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

EOL = chr(13) + chr(10)   # the page is CRLF
HOST = "box-1a2b"
A_CAM = "alpha/box-1a2b/kenton/camera.hang"
A_CAM2 = "alpha/box-1a2b/kenton/yard.hang"
B_CAM = "beta/box-1a2b/kenton/camera.hang"
B_CAM2 = "beta/box-1a2b/kenton/gate.hang"
A_GRID = "alpha/box-1a2b/kenton/rtsp-grid.hang"


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def mint(svc, room, host=HOST, code="pub-1"):
    o, c = svc.token({"room": room, "code": code, "host": host}, "10.0.0.7")
    assert c == 200, o
    return o["tokens"]["member"]


def read(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return f.read()


def slot(rect, *cams, mode="motion"):
    return {"rect": list(rect), "cams": list(cams), "cycle": {"mode": mode, "every": 10, "hold": 15}}


def cgrid(gid="kv", name="Kenton's View", slots=None):
    return {"id": gid, "name": name, "slots": slots or [slot([0, 0, 12, 12], B_CAM), slot([12, 0, 12, 12], A_CAM, A_CAM2)],
            "gap": 2, "sens": "medium"}


META = {"path": A_GRID, "n": 2, "layout": "auto", "cells": ["Cam", "Yard"], "feeds": [A_CAM, A_CAM2],
        "members": [A_CAM, A_CAM2], "out": [], "down": [], "more": [], "mode": "both", "id": "1", "label": "Grid",
        "rects": [[0, 0, 0.5, 1], [0.5, 0, 0.5, 1]], "gap": 2, "ts": 1700000000000}


class SpotOrder(unittest.TestCase):
    def setUp(self):
        self.st = store()

    def test_validation_and_caps(self):
        self.assertIsNone(kr.board_item("spotOrder", {"targets": [B_CAM, B_CAM2]})[1])
        self.assertIsNotNone(kr.board_item("spotOrder", {"targets": "x"})[1])
        self.assertIsNotNone(kr.board_item("spotOrder", {"targets": ["beta/~state/x.hang"]})[1])
        many = ["beta/box-1a2b/k/c%d.hang" % i for i in range(kr.BOARD_SPOTS_MAX + 1)]
        self.assertIn("at most", kr.board_item("spotOrder", {"targets": many})[1])
        self.assertEqual(kr.board_item("spotOrder", {"targets": [B_CAM, B_CAM]})[0]["targets"], [B_CAM])

    def test_stored_cleaned_and_unspot_takes_its_place(self):
        for t in (B_CAM, B_CAM2):
            self.st.board_apply("beta", "spot", {"target": t, "ts": 1})
        b, code, err = self.st.board_apply("beta", "spotOrder", kr.board_item("spotOrder", {"targets": [B_CAM2, B_CAM]})[0])
        self.assertEqual((code, err), (200, None))
        self.assertEqual(self.st.board("beta")["spotOrder"], [B_CAM2, B_CAM])
        self.assertEqual(self.st.boards_public()["beta"]["spotOrder"], [B_CAM2, B_CAM])      # spokes copy it
        b, code, _ = self.st.board_apply("beta", "unspot", {"target": B_CAM2})
        self.assertEqual(b["spotOrder"], [B_CAM])
        self.assertEqual(kr.board_clean({"spotOrder": [B_CAM, "x", B_CAM]})["spotOrder"], [B_CAM])

    def test_view_lock(self):
        o, c = kr.register_room(self.st, {"slug": "beta", "plain": True}, "10.0.0.1")
        kr.room_settings(self.st, {"slug": "beta", "op": "viewlock", "locked": True}, admin=True)
        item = kr.board_item("spotOrder", {"targets": [B_CAM]})[0]
        self.assertEqual(self.st.board_apply("beta", "spotOrder", item)[1], 403)
        self.assertEqual(self.st.board_apply("beta", "spotOrder", item, room_key=o["roomKey"])[1], 200)
        self.assertEqual(self.st.board_apply("beta", "spotOrder", kr.board_item("spotOrder", {"targets": []})[0], boss=True)[1], 200)


class CustomGrids(unittest.TestCase):
    def setUp(self):
        self.st = store()

    def test_validation(self):
        it, why = kr.board_item("cgrid", cgrid())
        self.assertIsNone(why)
        self.assertEqual(it["grid"]["name"], "Kenton's View")
        self.assertIsNotNone(kr.board_item("cgrid", dict(cgrid(), id="Bad Id"))[1])
        self.assertIsNotNone(kr.board_item("cgrid", cgrid(slots=[slot([0, 0, 12, 12])]))[1])                  # no camera
        self.assertIn("overlap", kr.board_item("cgrid", cgrid(slots=[slot([0, 0, 12, 12], B_CAM), slot([6, 6, 12, 12], A_CAM)]))[1])
        self.assertIn("two spots", kr.board_item("cgrid", cgrid(slots=[slot([0, 0, 6, 6], B_CAM), slot([6, 0, 6, 6], B_CAM)]))[1])
        cams = ["alpha/box-1a2b/k/c%d.hang" % i for i in range(kr.BOARD_SLOT_CAMS_MAX + 1)]
        self.assertIn("at most", kr.board_item("cgrid", cgrid(slots=[slot([0, 0, 6, 6], *cams)]))[1])
        many = [slot([(i % 12) * 2, (i // 12) * 2, 2, 2], "alpha/box-1a2b/k/c%d.hang" % i) for i in range(kr.BOARD_SLOTS_MAX + 1)]
        self.assertIn("at most", kr.board_item("cgrid", cgrid(slots=many))[1])
        nested = kr.board_cgrid_path("beta", "other")
        self.assertIsNotNone(kr.board_item("cgrid", cgrid(slots=[slot([0, 0, 6, 6], nested)]))[1])           # never a grid in a grid
        self.assertIsNotNone(kr.board_item("cgrid", dict(cgrid(), sens="loud"))[1])
        self.assertIsNone(kr.board_item("cgridDel", {"id": "kv"})[1])

    def test_store_cap_keep_delete_and_listings(self):
        b, code, err = self.st.board_apply("beta", "cgrid", kr.board_item("cgrid", cgrid())[0])
        self.assertEqual((code, err), (200, None))
        self.assertTrue(self.st.room("beta")["persistent"])                                          # a room grid keeps the room
        self.assertEqual(self.st.board("beta")["customGrids"]["kv"]["slots"][1]["cams"], [A_CAM, A_CAM2])
        lst = kr.board_listings(self.st.boards_public())
        self.assertTrue(lst[(A_CAM, "beta")]["cg"])                                                  # another room's camera: listed, flagged
        self.assertNotIn((B_CAM, "beta"), lst)                                                       # this room's own: no listing
        reg = kr.XShareRegistry()
        kr.board_sync_registry(reg, self.st.boards_public())
        self.assertTrue([e for e in reg.into("beta") if e["path"] == A_CAM][0]["cg"])
        self.st.board_apply("beta", "pin", kr.board_item("pin", {"path": A_CAM})[0])                  # pinned too: a tile of its own
        kr.board_sync_registry(reg, self.st.boards_public())
        self.assertFalse([e for e in reg.into("beta") if e["path"] == A_CAM][0]["cg"])
        for i in range(kr.BOARD_CGRIDS_MAX - 1):
            self.assertEqual(self.st.board_apply("beta", "cgrid", kr.board_item("cgrid", cgrid(gid="g%d" % i))[0])[1], 200)
        self.assertEqual(self.st.board_apply("beta", "cgrid", kr.board_item("cgrid", cgrid(gid="nine"))[0])[1], 409)
        tp = kr.board_cgrid_path("beta", "kv")
        self.st.board_apply("beta", "spot", {"target": tp, "ts": 1})
        self.st.board_apply("beta", "spotOrder", {"targets": [tp]})
        b, code, _ = self.st.board_apply("beta", "cgridDel", {"id": "kv"})
        self.assertNotIn("kv", b["customGrids"])
        self.assertEqual((b["spots"], b.get("spotOrder", [])), ([], []))                            # its spotlight goes with it

    def test_rename_keeps_ids(self):
        self.st.board_apply("beta", "cgrid", kr.board_item("cgrid", cgrid(gid="beta"))[0])
        out = kr.board_clean(kr.board_rename(self.st.board("beta"), "beta", "gamma"))
        self.assertIn("beta", out["customGrids"])                                                    # an id named like the room stays
        self.assertEqual(out["customGrids"]["beta"]["slots"][0]["cams"], ["gamma/box-1a2b/kenton/camera.hang"])

    def test_view_lock(self):
        o, c = kr.register_room(self.st, {"slug": "beta", "plain": True}, "10.0.0.1")
        kr.room_settings(self.st, {"slug": "beta", "op": "viewlock", "locked": True}, admin=True)
        self.assertEqual(self.st.board_apply("beta", "cgrid", kr.board_item("cgrid", cgrid())[0])[1], 403)
        self.assertEqual(self.st.board_apply("beta", "cgrid", kr.board_item("cgrid", cgrid())[0], boss=True)[1], 200)


class Service(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: base, fed_token=lambda: self.fed)

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def test_room_grid_needs_proof_for_another_rooms_camera(self):
        b = mint(self.hub, "beta")
        o, c = self.hub.board_post(dict(cgrid(), room="beta", op="cgrid"), "Bearer " + b, "10.0.0.7")
        self.assertEqual(c, 403, o)
        self.assertIn("member token for alpha", o["error"])
        o, c = self.hub.board_post(dict(cgrid(), room="beta", op="cgrid", tokens={"alpha": mint(self.hub, "alpha")}), "Bearer " + b, "10.0.0.7")
        self.assertEqual(c, 200, o)
        self.assertIn("kv", o["customGrids"])
        # a later edit by someone else (no alpha token): the alpha cameras were already granted -- fine
        b2 = mint(self.hub, "beta", host="pc-9a9a")
        g = cgrid()
        g["slots"][0]["cams"] = [B_CAM, B_CAM2]
        o, c = self.hub.board_post(dict(g, room="beta", op="cgrid"), "Bearer " + b2, "10.0.0.8")
        self.assertEqual(c, 200, o)
        viewer = mint(self.hub, "beta", code="view-1", host="watch-1234")
        self.assertEqual(self.hub.board_post({"room": "beta", "op": "cgridDel", "id": "kv"}, "Bearer " + viewer, "10.0.0.9")[1], 403)
        g, c = self.hub.board_get("beta", "Bearer " + viewer)
        self.assertEqual(g["customGrids"]["kv"]["name"], "Kenton's View")
        items = self.hub.xshare_get("beta", "Bearer " + viewer)[0]["items"]
        self.assertTrue([x for x in items if x["path"] == A_CAM][0]["cg"])                          # readable by everyone in beta

    def test_spoke_forwards_and_mirrors_order_and_grids(self):
        b = mint(self.spoke, "beta")
        for t in (B_CAM, B_CAM2):
            self.assertEqual(self.spoke.board_post({"room": "beta", "op": "spot", "target": t}, "Bearer " + b, "10.0.0.7")[1], 200)
        o, c = self.spoke.board_post({"room": "beta", "op": "spotOrder", "targets": [B_CAM2, B_CAM]}, "Bearer " + b, "10.0.0.7")
        self.assertEqual((c, o.get("spotOrder")), (200, [B_CAM2, B_CAM]), o)
        o, c = self.spoke.board_post(dict(cgrid(), room="beta", op="cgrid", tokens={"alpha": mint(self.spoke, "alpha")}), "Bearer " + b, "10.0.0.7")
        self.assertEqual(c, 200, o)
        self.assertEqual(self.spoke.store.boards_public(), {})                                       # one writer: the hub
        self.assertEqual(self.hub.store.board("beta")["spotOrder"], [B_CAM2, B_CAM])
        self.assertIn("kv", self.hub.store.board("beta")["customGrids"])
        payload, code = self.hub.bans_for_spoke("Bearer " + self.fed)
        self.spoke._board_mirror = {}
        self.spoke.board_mirror_apply(payload)
        g, c = self.spoke.board_get("beta", "Bearer " + b, None, "10.0.0.8")
        self.assertEqual((g["spotOrder"], list(g["customGrids"])), ([B_CAM2, B_CAM], ["kv"]))
        self.spoke.xshare_mirror_apply(payload)
        self.assertTrue([e for e in self.spoke._xs("local").into("beta") if e["path"] == A_CAM][0]["cg"])

    def test_spoke_view_lock(self):
        o, c = kr.register_room(self.hub.store, {"slug": "beta", "plain": True}, "10.0.0.1")
        kr.room_settings(self.hub.store, {"slug": "beta", "op": "viewlock", "locked": True}, admin=True)
        b = mint(self.spoke, "beta")
        self.assertEqual(self.spoke.board_post({"room": "beta", "op": "spotOrder", "targets": [B_CAM]}, "Bearer " + b, "10.0.0.7")[1], 403)
        o, c = self.spoke.board_post({"room": "beta", "op": "spotOrder", "targets": [B_CAM], "roomKey": o["roomKey"]}, "Bearer " + b, "10.0.0.7")
        self.assertEqual(c, 200, o)

    def test_open_relay(self):
        st = store()
        o, c = kr.board_open("POST", st, dict(cgrid(), room="beta", op="cgrid"))
        self.assertEqual(c, 200, o)
        o, c = kr.board_open("POST", st, {"room": "beta", "op": "spotOrder", "targets": [B_CAM]})
        self.assertEqual((c, o["spotOrder"]), (200, [B_CAM]))
        self.assertIn("kv", kr.board_open("GET", st, room="beta")[0]["customGrids"])


class ForeignGrid(unittest.TestCase):
    """A camera grid of room alpha pinned into room beta: beta's board arranges it; its owner posts its geometry."""

    def setUp(self):
        self.hub = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        self.owner = mint(self.hub, "alpha")              # the box (host box-1a2b) owns A_GRID
        self.b = mint(self.hub, "beta", host="pc-9a9a")

    def tearDown(self):
        self.hub.close()

    def post(self, body, tok=None):
        return self.hub.board_post(body, "Bearer " + (tok or self.b), "10.0.0.7")

    def test_meta_only_from_the_owner_into_its_own_room(self):
        o, c = self.hub.board_post({"room": "alpha", "op": "gridMeta", "path": A_GRID, "meta": META}, "Bearer " + mint(self.hub, "alpha", host="pc-5555"), "10.0.0.7")
        self.assertEqual(c, 403, o)
        o, c = self.hub.board_post({"room": "alpha", "op": "gridMeta", "path": A_GRID, "meta": META}, "Bearer " + self.owner, "10.0.0.7")
        self.assertEqual(c, 200, o)
        self.assertEqual(self.hub.store.board("alpha")["metas"][A_GRID]["meta"]["members"], [A_CAM, A_CAM2])
        self.assertEqual(self.hub.store.board_apply("beta", "gridMeta", kr.board_item("gridMeta", {"path": A_GRID, "meta": META})[0])[1], 400)
        old = kr.BOARD_META_BYTES
        kr.BOARD_META_BYTES = 300
        try:
            self.assertIsNone(kr.board_meta_clean(A_GRID, dict(META, cells=["x" * 40] * 8)))                  # too big: refused
        finally:
            kr.BOARD_META_BYTES = old
        self.assertEqual(kr.board_meta_clean(A_GRID, dict(META, members=[B_CAM, A_CAM]))["members"], [A_CAM])   # its own room's cameras only

    def test_room_tools_for_a_pinned_grid_and_split_listing(self):
        self.hub.board_post({"room": "alpha", "op": "gridMeta", "path": A_GRID, "meta": META}, "Bearer " + self.owner, "10.0.0.7")
        lay = {"room": "beta", "op": "grid", "path": A_GRID, "slots": [slot([0, 0, 24, 24], A_CAM, A_CAM2)], "gap": 0}
        o, c = self.post(lay)
        self.assertEqual(c, 403, o)                                                                  # not seen in beta yet
        o, c = self.post({"room": "beta", "op": "split", "path": A_CAM})
        self.assertEqual(c, 403, o)
        o, c = self.post({"room": "beta", "op": "pin", "path": A_GRID, "tokens": {"alpha": mint(self.hub, "alpha", host="pc-9a9a")}})
        self.assertEqual(c, 200, o)
        self.assertEqual(o["gridMetas"][A_GRID]["members"], [A_CAM, A_CAM2])                         # its geometry rides beta's board
        viewer = mint(self.hub, "beta", code="view-1", host="watch-1234")
        self.assertIn(A_GRID, self.hub.board_get("beta", "Bearer " + viewer)[0]["gridMetas"])
        self.assertEqual(self.post(lay)[1], 200)
        self.assertEqual(self.post({"room": "beta", "op": "gridHide", "path": A_GRID, "member": A_CAM2})[1], 200)
        o, c = self.post({"room": "beta", "op": "split", "path": A_CAM})
        self.assertEqual(c, 200, o)
        self.assertEqual(self.post({"room": "beta", "op": "split", "path": "alpha/box-1a2b/kenton/other.hang"})[1], 403)
        items = self.hub.xshare_get("beta", "Bearer " + viewer)[0]["items"]
        row = [x for x in items if x["path"] == A_CAM][0]
        self.assertFalse(row["cg"])                                                                  # split: a tile for everyone in beta
        b = self.hub.store.board("beta")
        self.assertEqual((b["grids"][A_GRID]["hidden"], b["split"]), ([A_CAM2], [A_CAM]))
        self.assertNotIn(A_GRID, self.hub.store.board("alpha").get("grids", {}))                     # the grid's own room untouched
        o, c = self.post({"room": "beta", "op": "unpin", "path": A_GRID})                            # unpinning takes this room's tools along
        self.assertEqual((o["grids"], o["split"]), ({}, []))

    def test_meta_is_no_view_change(self):
        o, c = kr.register_room(self.hub.store, {"slug": "alpha", "plain": True}, "10.0.0.1")
        kr.room_settings(self.hub.store, {"slug": "alpha", "op": "viewlock", "locked": True}, admin=True)
        o, c = self.hub.board_post({"room": "alpha", "op": "gridMeta", "path": A_GRID, "meta": META}, "Bearer " + self.owner, "10.0.0.7")
        self.assertEqual(c, 200, o)


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = read("moq-watch-lite.html")

    def sec(self, start, end):
        i = self.p.index(start)
        return self.p[i:self.p.index(end, i + len(start))]

    def test_n_drag_rearranges_the_spotlight(self):
        p = self.p
        self.assertIn("if (!gridMode) { if (mosaicDragOk(name, pane, tile)) mosaicDragStart(e, name, pane); return; }", p)
        self.assertIn("const spotArrangeCan = () => pinsLive().length >= 2 || boardCan();", p)      # boardCan carries the view lock
        ok = self.sec("  function mosaicDragOk(", EOL + "  }" + EOL)
        self.assertIn('pane.classList.contains("mainstage") && !!stageMosaic && stageMosaicNames.has(name) && spotArrangeCan()', ok)
        mv = self.sec("  function mdragMove(e) {", EOL + "  }" + EOL)
        self.assertIn("< 6) return;", mv)                                                          # a click without moving stays a click
        self.assertIn("dragGhost.start(mdrag.el, e);", mv)                                         # the 0.21.25 ghost
        self.assertIn('over?.classList.add("drop-target")', mv)
        sw = self.sec("  function spotSwap(a, b) {", EOL + "  }" + EOL)
        self.assertIn("boardSpotOrder(order.flatMap(", sw)
        self.assertIn("pinsSave(); applyState();", sw)                                              # my pins: my own order
        self.assertIn('const d = await boardPost("spotOrder", { targets }, false);', p)
        self.assertIn("return spotOrdered([...add.values()]", p)
        so = self.sec("  function spotOrdered(list) {", EOL + "  }" + EOL)
        self.assertIn("[...list.filter((v) => rank.has(v.target)).sort((a, b) => rank.get(a.target) - rank.get(b.target)), ...list.filter((v) => !rank.has(v.target))]", so)
        self.assertIn("if (spotDone && setSig === spotSetSig) { spotDone = sig; if (items.length >= 2) spotStage = items; applyState(); return; }", p)   # an order change pulls nobody
        self.assertIn('const votes = set.map((v) => v.target + "@" + v.ts).sort().join("|");', p)
        self.assertIn("board.spotOrder = order; board.customGrids = cgs; board.gridMetas = metas;", p)

    def test_o_back_to_spotlight(self):
        p = self.p
        self.assertIn('spotBackBtn.classList.toggle("show", joinState === "joined" && CHANNEL !== LOBBY && sb.items.length > 0 && !spotShowing(sb));', p)
        idle = re.search(r'const IDLE_MS = 3000, IDLE_CTL = "([^"]*)"', p).group(1)
        self.assertNotIn("spotBack", idle)                                                         # never idles away
        sh = self.sec("  function spotShowing(s) {", EOL + "  }" + EOL)
        self.assertIn("if (gridMode || gridOpen || gridZoom) return false;", sh)
        self.assertIn('else if ((e.key === "s" || e.key === "S") && !e.shiftKey) { if (spotGoBack()) e.preventDefault(); }', p)
        kd = self.sec("    if (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement) return;", "  // ---- share (publish) dropdown")
        self.assertIn("if (t && t.isContentEditable) return;", kd)
        self.assertLess(kd.index("if (e.ctrlKey || e.altKey || e.metaKey) return;"), kd.index('e.key === "s"'))
        gb = self.sec("  function spotGoBack() {", EOL + "  }" + EOL)
        self.assertIn('spotDone = null; spotVotesDone = ""; galleryChosen = false; manualPick = false; selfSpotEl = null;', gb)
        self.assertIn("<tr><td><kbd>S</kbd></td><td>back to the spotlight", p)

    def test_e_grids_from_any_room(self):
        p = self.p
        self.assertIn('const cgKey = () => "kastr.mygrids." + sbRelayHost();', p)
        self.assertIn('const CG_ME = "~me", CG_ME_HOST = "mygrid-0000", CG_ROOM_HOST = "cgrid-0000", CG_MAX = 8;', p)
        self.assertIn('const d = await boardPost("cgrid", { ...body, tokens }, quiet);', p)
        self.assertIn('const d = await boardPost("cgridDel", { id }, quiet);', p)
        self.assertIn("try { tokens[r] = await boardFromToken(r); }", p)                           # proof for another room's camera
        self.assertIn("|| vgHqWanted(name) || cgWarm.has(name);", p)                                # keepWarm
        self.assertIn("if (w.pick.has(p) || cgCams.has(p)) return true;", p)                         # a watched room's unticked camera
        self.assertIn('kind: String(it.kind || ""), cg: !!it.cg });', p)                             # listed only for a room grid
        self.assertIn("|| (cgHide(name) && (gridMode || name !== selectedName))", p)               # hidden, opened from its spot
        self.assertIn("if (isWatched(name) && CLIENT.webcodecs && !isCgName(name)) watch.setAttribute", p)
        tick = self.sec("  function cgTick() {", EOL + "  }" + EOL)
        self.assertIn('gb.motion.sample("cg:" + n + "|" + k,', tick)                               # motion from each camera's own frames
        self.assertIn("if (motion) for (const k of avail) warm.add(k);", tick)                      # motion: every camera decodes
        self.assertIn("< 4000) warm.add(avail[(avail.indexOf(cur) + 1) % avail.length]);", tick)   # time: the next one 4 s early
        self.assertIn("const mt = k && tiles.get(k), fr = mt && vgFrameOf(mt);", self.sec("  function cgDraw(n, t) {", EOL + "  }" + EOL))
        self.assertIn('<button class="opt" id="optGrid" type="button"', p)
        self.assertIn('document.getElementById("optGrid").addEventListener("click", () => { closeAllPops(); cgNew(); });', p)
        menu = self.sec("  function cgMenu(anchor, name) {", EOL + "  }" + EOL)
        for need in ('value: "edit"', 'value: "rename"', 'label: "Keep only for me"', 'label: "Share with this room"', 'label: "Delete grid"',
                     "if (room && !viewLockedForMe())", "if (room && boardCan())"):
            self.assertIn(need, menu)
        ed = self.sec("  const gridEditor = (() => {", "  window.__gridEditor = gridEditor;")
        self.assertIn("if (o.name != null) {", ed)
        self.assertIn('sl.append(ssw, o.share.label || "Share with this room");', ed)   # 0.21.92: si wrapped in a .switch (ssw)
        self.assertIn('const ssw = mkEl("span", "switch sm"); ssw.append(si, mkEl("i"));', ed)
        self.assertIn("if (cgOpened && cgOpened.cam === name && tiles.has(cgOpened.grid))", p)

    def test_editor_keeps_its_own_band(self):
        p = self.p
        self.assertIn("let geInset = null;", p)
        fit = self.sec("  function fitMainstage(railRows) {", EOL + "  }" + EOL)
        self.assertIn("let cw = areaW - insR, chh = areaH - insT;", fit)
        self.assertIn("const ins = geInset && mains.length === 1 && mains[0] === geInset.pane ? geInset : null;", fit)
        self.assertNotIn("style.translate", fit)                                                    # a transform would carry the fixed toolbar
        ed = self.sec("  const gridEditor = (() => {", "  window.__gridEditor = gridEditor;")
        self.assertIn("const want = { top: (tools.offsetHeight || 40) + 16, right: 236 + 16 };", ed)
        self.assertIn('if (geInset === c.inset) { geInset = null; try { c.o.pane.style.marginTop = ""; c.o.pane.style.marginRight = ""; fitMainstage(lastRail.rows); } catch {} }', ed)

    def test_foreign_grid_geometry(self):
        p = self.p
        self.assertIn("try { if (p) window.__gridMetaOut?.(JSON.parse(p)); } catch {}", p)          # the box posts its grid's geometry
        self.assertIn('body: JSON.stringify({ room: CHANNEL, op: "gridMeta", path: gp, meta: e.meta })', p)
        ap = self.sec("  function boardMetasApply() {", EOL + "  }" + EOL)
        self.assertIn('if (cur && !String(cur.key || "").startsWith("~board:")) continue;', ap)      # a live copy wins
        self.assertIn('gridApply("~board:" + gp,', ap)

    def test_later_listings_get_a_session_of_their_own(self):
        p = self.p
        self.assertIn('return x ? u + (u.includes("?") ? "&" : "?") + "xs=" + encodeURIComponent(x.from) + (v ? "&xv=" + v : "") : u;', p)
        self.assertIn("for (const r of fresh) xsVer.set(r, (xsVer.get(r) || 0) + 1); }", p)
        self.assertIn("if (t.cg) continue;   // 0.21.66 (e): a grid of cameras has no catalog", p)
        self.assertIn("t.shed = !t.cg && congestShed(name, isSelected || (gridOpen && gridOpen.path === name) || cgWarm.has(name));", p)

    def test_rooms_rail(self):
        p = self.p
        self.assertNotIn("border-left:3px solid #fff", p)
        self.assertIn("#sbPeek { position:fixed;", p)
        self.assertIn("try { sbPeekPaint(); } catch {}   // 0.21.66: the collapsed rail's hover card stays live", p)
        pk = self.sec("  function sbPeekPaint() {", EOL + "  }" + EOL)
        self.assertIn("sbCardPaint(card, rec);", pk)
        self.assertIn('matchMedia("(hover: hover)")', p)
        self.assertIn("}, 150);", self.sec("  function sbPeekOpen(slug) {", EOL + "  }" + EOL))

    def test_crlf_kept(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), "rb") as f:
            raw = f.read()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))

class FieldFixes(unittest.TestCase):
    """0.21.66 field fixes: RNNoise silent with a Bluetooth headset; an all-offline grid hides; a parked camera's cell
    no longer leaves an empty stage (Mendon)."""
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            cls.p = f.read()

    def sec(self, start, end):
        i = self.p.index(start)
        return self.p[i:self.p.index(end, i)]

    def test_denoise_context_has_no_output_device(self):
        self.assertIn('denoiseCtx = new AudioContext({ sampleRate: 48000, latencyHint: "interactive", sinkId: { type: "none" } });', self.p)
        self.assertIn('catch { denoiseCtx = new AudioContext({ sampleRate: 48000, latencyHint: "interactive" }); }', self.p)

    def test_denoise_watchdog(self):
        g = self.sec("  function denoiseGuard(slot, ctx, src, node) {", "  function stopDenoise(")
        self.assertIn("frozen = t === lastT ? frozen + 1 : 0;", g)
        self.assertIn("Math.sqrt(e / ib.length) > 0.01 && mx < 1e-6", g)
        self.assertIn("if (slot.entry.micMuted)", g)
        self.assertIn("if (!slot.dnRebuilt) {", g)
        self.assertIn("denoiseFail(why);", g)
        self.assertIn("denoiseGuard(slot, d.ctx, src, node);", self.p)
        self.assertIn("clearInterval(slot.dnGuard); slot.dnGuard = null;   // 0.21.66", self.sec("  function stopDenoise(", "  function armDenoiseWatch("))

    def test_all_offline_grid_hidden(self):
        self.assertIn("allOut: meta.n != null && Number(meta.n) === 0 });", self.p)
        self.assertIn("gridDarkCheck(String(meta.path), !!cur?.allOut);", self.p)
        self.assertIn("    || gridDark(name);", self.p)
        self.assertIn("const gridDark = (name) => !!gridMeta.get(name)?.allOut && !(selectedName === name && window.__gridEditor?.isOpen?.());", self.p)
        d = self.sec("  function gridDarkCheck(gp, was) {", "    queueRelayout();")
        self.assertIn("gridDarkLeft = { gp, sel: next, mode };", d)
        self.assertIn("gridMode = gridDarkLeft.mode;", d)

    def test_parked_cell_click_watches_it(self):
        self.assertIn("if (fp && tiles.has(fp) && !isWatched(fp)) watchStream(fp);", self.p)
        a = self.sec("    autoContentCheck();" + chr(10) + "    {", "    for (const lit of [...spotLits.values()]) {")
        self.assertIn("!isWatched(selectedName) || deadMember(selectedName) || roomHid.has(selectedName)", a)
        self.assertIn("gridZoom = null; selectedName = gp;", a)


if __name__ == "__main__":
    unittest.main()
