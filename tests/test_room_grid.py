# -*- coding: utf-8 -*-
"""v0.21.64 the ROOM'S GRID LAYOUT (Kenton: "I need to be able to customize the grid for everyone in the room to see. I need
to be able to remove feeds from that grid as well."). The room board keeps, per camera grid, the room's own layout (rects in
the editor's 24 x 24 units + gap) and the cameras the room removed (hidden). Any publisher member changes it (ops grid /
gridHide / gridShow / gridReset on POST /api/rooms/board); spokes forward and mirror it like pins. The page draws the grid
with MY layout > the ROOM's > the owner's, never draws or opens a removed camera, and offers the editor for everyone in the
room. Loopback sockets only (ephemeral ports), no outside network."""
import os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

HOST = "box-1a2b"
GRID = "beta/box-1a2b/kenton/grid-1.hang"
CAM1 = "beta/box-1a2b/kenton/yard.hang"
CAM2 = "beta/box-1a2b/kenton/gate.hang"
CAM3 = "beta/box-1a2b/kenton/dock.hang"


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def mint(svc, room, host=HOST, code="pub-1"):
    o, c = svc.token({"room": room, "code": code, "host": host}, "10.0.0.7")
    assert c == 200, o
    return o["tokens"]["member"]


def item(op, **kw):
    it, why = kr.board_item(op, dict(kw))
    assert why is None, why
    return it


class Validation(unittest.TestCase):
    def test_grid_item_shapes(self):
        ok = kr.board_item("grid", {"path": GRID, "rects": {CAM1: [0, 0, 12, 12], CAM2: [12, 0, 12, 12]}, "gap": 4})
        self.assertIsNone(ok[1])
        self.assertEqual(ok[0]["rects"][CAM2], [12, 0, 12, 12])
        self.assertEqual(ok[0]["gap"], 4)
        bad = [
            {"path": "beta/~grid/x.hang", "rects": {CAM1: [0, 0, 4, 4]}},          # a control path
            {"path": GRID, "rects": {}},                                           # nothing to lay out
            {"path": GRID, "rects": [[0, 0, 4, 4]]},                               # not a map
            {"path": GRID, "rects": {CAM1: [0, 0, 1, 4]}},                         # under 2 x 2
            {"path": GRID, "rects": {CAM1: [20, 0, 6, 4]}},                        # outside the picture
            {"path": GRID, "rects": {CAM1: [0, 0, 4.5, 4]}},                       # not whole units
            {"path": GRID, "rects": {CAM1: [0, 0, 4]}},                            # three numbers
            {"path": GRID, "rects": {CAM1: [-1, 0, 4, 4]}},
            {"path": GRID, "rects": {CAM1: [0, 0, True, 4]}},
            {"path": GRID, "rects": {"beta/box-1a2b/../x.hang": [0, 0, 4, 4]}},    # not a camera path
            {"path": GRID, "rects": {CAM1: [0, 0, 4, 4]}, "gap": 30},
            {"path": GRID, "rects": {CAM1: [0, 0, 4, 4]}, "gap": "2"},
        ]
        for b in bad:
            self.assertIsNotNone(kr.board_item("grid", b)[1], b)
        many = {"beta/box-1a2b/k/c%d.hang" % i: [0, 0, 2, 2] for i in range(kr.BOARD_GRID_MEMBERS_MAX + 1)}
        self.assertIn("at most", kr.board_item("grid", {"path": GRID, "rects": many})[1])
        self.assertIsNotNone(kr.board_item("gridHide", {"path": GRID, "member": "nope"})[1])
        self.assertIsNotNone(kr.board_item("gridShow", {"path": GRID})[1])
        self.assertIsNone(kr.board_item("gridReset", {"path": GRID})[1])
        self.assertIn("gridReset", kr.board_item("zap", {})[1])

    def test_clean_drops_bad_rows(self):
        b = kr.board_clean({"grids": {GRID: {"rects": {CAM1: [0, 0, 12, 12], "x": [0, 0, 2, 2], CAM2: [0, 0, 30, 2]},
                                             "hidden": [CAM3, CAM3, "junk"], "gap": 99},
                                      "beta/~x/y.hang": {"rects": {CAM1: [0, 0, 4, 4]}},
                                      "beta/box-1a2b/k/empty.hang": {"rects": {}, "hidden": []}}})
        self.assertEqual(list(b["grids"]), [GRID])
        g = b["grids"][GRID]
        self.assertEqual((g["rects"], g["hidden"], g["gap"]), ({CAM1: [0, 0, 12, 12]}, [CAM3], 24))
        self.assertTrue(kr.board_has({"pins": [], "spots": [], "grids": {GRID: g}}))
        self.assertFalse(kr.board_has(kr.board_clean(None)))


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.st = store(self.dir)

    def test_layout_hide_show_reset(self):
        b, code, err = self.st.board_apply("beta", "grid", item("grid", path=GRID, rects={CAM1: [0, 0, 16, 16], CAM2: [16, 0, 8, 8]}, gap=6, by="Kenton"))
        self.assertEqual((code, err), (200, None))
        g = b["grids"][GRID]
        self.assertEqual((g["rects"][CAM1], g["gap"], g["hidden"], g["by"]), ([0, 0, 16, 16], 6, [], "Kenton"))
        b, code, _ = self.st.board_apply("beta", "gridHide", item("gridHide", path=GRID, member=CAM2))
        self.assertEqual(b["grids"][GRID]["hidden"], [CAM2])
        self.st.board_apply("beta", "gridHide", item("gridHide", path=GRID, member=CAM2))   # twice: once
        self.assertEqual(self.st.board("beta")["grids"][GRID]["hidden"], [CAM2])
        b, code, _ = self.st.board_apply("beta", "grid", item("grid", path=GRID, rects={CAM1: [0, 0, 24, 24]}, gap=0))
        self.assertEqual(b["grids"][GRID]["hidden"], [CAM2])                               # a new layout keeps the removals
        again = kr.AuthStore(self.dir)                                                     # a restart reads it back
        self.assertEqual(again.board("beta")["grids"][GRID]["rects"], {CAM1: [0, 0, 24, 24]})
        b, _, _ = self.st.board_apply("beta", "gridShow", item("gridShow", path=GRID, member=CAM2))
        self.assertEqual(b["grids"][GRID]["hidden"], [])
        b, _, _ = self.st.board_apply("beta", "gridReset", item("gridReset", path=GRID))
        self.assertEqual(b["grids"], {})
        self.assertEqual(self.st.boards_public(), {})

    def test_hide_alone_and_last_show_drops_the_entry(self):
        b, code, _ = self.st.board_apply("beta", "gridHide", item("gridHide", path=GRID, member=CAM3))
        self.assertEqual((code, b["grids"][GRID]["rects"], b["grids"][GRID]["hidden"]), (200, {}, [CAM3]))
        b, _, _ = self.st.board_apply("beta", "gridShow", item("gridShow", path=GRID, member=CAM3))
        self.assertEqual(b["grids"], {})
        b, code, _ = self.st.board_apply("beta", "gridShow", item("gridShow", path=GRID, member=CAM3))   # nothing to show: fine
        self.assertEqual((code, b["grids"]), (200, {}))

    def test_a_grid_layout_keeps_the_room_and_counts(self):
        self.st.touch_room("beta")
        self.assertFalse(self.st.room("beta")["persistent"])
        self.st.board_apply("beta", "gridHide", item("gridHide", path=GRID, member=CAM1))
        self.assertTrue(self.st.room("beta")["persistent"])
        row = [r for r in self.st.rooms_public() if r["slug"] == "beta"][0]
        self.assertEqual(row["board"], {"pins": 0, "spots": 0, "grids": 1})
        self.assertEqual(list(self.st.boards_public()), ["beta"])

    def test_caps_and_lobby(self):
        for i in range(kr.BOARD_GRIDS_MAX):
            self.assertEqual(self.st.board_apply("beta", "gridHide", item("gridHide", path="beta/box-1a2b/k/g%d.hang" % i, member=CAM1))[1], 200)
        b, code, err = self.st.board_apply("beta", "gridHide", item("gridHide", path=GRID, member=CAM1))
        self.assertEqual(code, 409)
        self.assertIn("grid layouts", err)
        self.st.board_apply("beta", "gridReset", item("gridReset", path="beta/box-1a2b/k/g0.hang"))
        for i in range(kr.BOARD_GRID_MEMBERS_MAX):
            self.assertEqual(self.st.board_apply("beta", "gridHide", item("gridHide", path=GRID, member="beta/box-1a2b/k/c%d.hang" % i))[1], 200)
        self.assertEqual(self.st.board_apply("beta", "gridHide", item("gridHide", path=GRID, member=CAM1))[1], 409)
        self.assertEqual(self.st.board_apply("main", "gridHide", item("gridHide", path=GRID, member=CAM1))[1], 403)


class Service(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        self.b = mint(self.svc, "beta")

    def tearDown(self):
        self.svc.close()

    def post(self, body, tok=None):
        return self.svc.board_post(body, "Bearer " + (tok or self.b), "10.0.0.7")

    def test_publishers_of_the_room_only(self):
        body = {"room": "beta", "op": "gridHide", "path": GRID, "member": CAM1}
        viewer = mint(self.svc, "beta", host="watch-9f9f", code="view-1")
        self.assertEqual(self.post(body, tok=viewer)[1], 403)
        self.assertEqual(self.post(body, tok=mint(self.svc, "alpha"))[1], 403)
        self.assertEqual(self.svc.board_post(body, None, "10.0.0.7")[1], 403)
        self.assertEqual(self.post(dict(body, room="main"), tok=mint(self.svc, "main"))[1], 403)
        self.assertEqual(self.post(dict(body, member="junk"))[1], 400)
        o, c = self.post(body)
        self.assertEqual((c, o["grids"][GRID]["hidden"], o["grids"][GRID]["by"]), (200, [CAM1], HOST))
        g, c = self.svc.board_get("beta", "Bearer " + self.b, None, "10.0.0.8")
        self.assertEqual((c, list(g["grids"])), (200, [GRID]))
        o, c = self.post({"room": "beta", "op": "grid", "path": GRID, "rects": {CAM2: [0, 0, 24, 24]}, "gap": 0})
        self.assertEqual((c, o["grids"][GRID]["rects"]), (200, {CAM2: [0, 0, 24, 24]}))
        o, c = self.post({"room": "beta", "op": "gridReset", "path": GRID})
        self.assertEqual((c, o["grids"]), (200, {}))

    def test_open_relay(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        o, c = kr.board_open("POST", st, {"room": "beta", "op": "grid", "path": GRID, "rects": {CAM1: [0, 0, 12, 12]}})
        self.assertEqual((c, o["grids"][GRID]["gap"]), (200, 2))
        self.assertEqual(kr.board_open("GET", st, room="beta")[0]["grids"][GRID]["rects"], {CAM1: [0, 0, 12, 12]})
        self.assertEqual(kr.board_open("POST", st, {"room": "beta", "op": "grid", "path": GRID, "rects": {CAM1: [0, 0, 1, 1]}})[1], 400)


class Federation(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: base, fed_token=lambda: self.fed)
        self.b = mint(self.spoke, "beta")

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def test_spoke_forwards_and_mirrors(self):
        o, c = self.spoke.board_post({"room": "beta", "op": "grid", "path": GRID, "rects": {CAM1: [0, 0, 16, 16], CAM2: [16, 0, 8, 8]}, "gap": 3},
                                     "Bearer " + self.b, "10.0.0.7")
        self.assertEqual(c, 200, o)
        o, c = self.spoke.board_post({"room": "beta", "op": "gridHide", "path": GRID, "member": CAM2}, "Bearer " + self.b, "10.0.0.7")
        self.assertEqual((c, o["grids"][GRID]["hidden"]), (200, [CAM2]), o)
        hub = self.hub.store.board("beta")["grids"][GRID]                               # the hub holds it
        self.assertEqual((hub["rects"][CAM1], hub["gap"], hub["hidden"]), ([0, 0, 16, 16], 3, [CAM2]))
        self.assertEqual(self.spoke.store.boards_public(), {})                          # single writer
        payload, code = self.hub.bans_for_spoke("Bearer " + self.fed)
        self.assertEqual(list(payload["boards"]["beta"]["grids"]), [GRID])
        self.spoke._board_mirror = {}
        self.spoke.board_mirror_apply(payload)
        g, c = self.spoke.board_get("beta", "Bearer " + self.b, None, "10.0.0.8")
        self.assertEqual((c, g["grids"][GRID]["hidden"]), (200, [CAM2]))
        again = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4463, self.spoke.store, hub=lambda: None)   # restart: from disk
        try:
            self.assertEqual(list(again._board_mirror["beta"]["grids"]), [GRID])
        finally:
            again.close()
        o, c = self.spoke.board_post({"room": "beta", "op": "gridReset", "path": GRID}, "Bearer " + self.b, "10.0.0.7")
        self.assertEqual((c, o["grids"]), (200, {}))
        self.spoke.board_mirror_apply(self.hub.bans_for_spoke("Bearer " + self.fed)[0])
        self.assertEqual(self.spoke.board_get("beta", None, None, "127.0.0.1")[0]["grids"], {})

    def test_hub_op_validates_the_item(self):
        body = {"op": "board", "vouch": "publisher", "room": "beta", "act": "grid", "item": {"path": GRID, "rects": {CAM1: [0, 0, 1, 1]}}}
        self.assertEqual(self.hub.rooms_fed(body, "Bearer " + self.fed)[1], 400)
        body["item"]["rects"] = {CAM1: [0, 0, 4, 4]}
        self.assertEqual(self.hub.rooms_fed(body, None)[1], 403)
        o, c = self.hub.rooms_fed(body, "Bearer " + self.fed)
        self.assertEqual((c, o["grids"][GRID]["rects"]), (200, {CAM1: [0, 0, 4, 4]}))


class Page(unittest.TestCase):
    """The page: precedence (mine > the room's > the owner's), removed cameras skipped everywhere, menus, editor wiring."""

    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.p = f.read()

    def sec(self, a, b):
        p = self.p
        return p[p.index(a):p.index(b, p.index(a))]

    def test_precedence_mine_then_room_then_owner(self):
        eff = self.sec("  function vgEff(gp) {", "  const vgLaidOut =")
        i_draft, i_me, i_room = eff.index('src: "draft"'), eff.index('src: "me"'), eff.index('src: "room"')
        self.assertLess(i_draft, i_me)
        self.assertLess(i_me, i_room)
        self.assertLess(i_room, eff.index('src: "owner"'))
        self.assertIn("const roomGridOf = (gp) => (board.room === CHANNEL && CHANNEL !== LOBBY && board.grids && board.grids[gp]) || null;", self.p)

    def test_removed_cameras_are_skipped(self):
        p = self.p
        units = self.sec("  function vgUnits(gp, meta, e) {", "  function vgDstRects(")
        self.assertIn("!e.hidden.has(mp)", units)
        dst = self.sec("  function vgDstRects(gp, meta, W, H, noGap) {", "  function vgHqWanted(")
        self.assertIn("return ms.map((mp) => (e.hidden.has(mp) ? null : px(auto[j++])));", dst)   # equal cells for the rest
        self.assertIn("autoRows(Math.max(1, keep.length), W, H)", dst)
        draw = self.sec("  function vgDraw(name, t) {", "  function vgToggleHq(")
        self.assertIn("if (!d || !sr) return;", draw)
        self.assertIn("return rs.findIndex((r) => r && px >= r.x", p)                                  # clicks never land on one
        self.assertIn("vgLaidOut(meta.path) ? vgDstRects(meta.path, meta, f.cw, f.ch)", p)
        self.assertIn("|| leavingExMember(name) || roomHid.has(name)", p)                             # rail, gallery, stage
        self.assertIn("      if (roomHid.has(n)) continue;   // 0.21.64", p)                                   # People
        self.assertIn("orderedNames().filter((n) => !roomHid.has(n) && !isCgName(n) && !cgHide(n)).filter((n) => isWatched(n) && isContentPath(n)", p)   # arrivals
        self.assertIn('if (isGridChild(n) || roomHid.has(n)) return "gridchild";', p)
        self.assertIn("if (!tiles.has(name) || roomHid.has(name)) return;", p)                         # never opened
        self.assertIn("if (selectedName === undefined && !roomHid.has(name) && !cgHide(name) && isWatched(name) && !isGridChild(name) && !wrRoomOf(name))", p)
        chg = self.sec("  function roomGridChanged() {", "  const roomGridCan =")
        for need in ("roomHidRebuild();", "vgSync();", "applyState();", "if (selectedName && roomHid.has(selectedName))"):
            self.assertIn(need, chg)

    def test_board_poll_applies_grids_live(self):
        take = self.sec("  function boardTake(d, gen) {", "  let boardBusy = false;")
        self.assertIn("board.grids = grids;", take)
        self.assertIn("if (JSON.stringify([grids, split]) !== gridsWas) { try { roomGridChanged(); } catch {} }", take)   # 0.21.65: + split
        self.assertIn("grid: boardGrid, split: boardSplit,", self.p)   # 0.21.66: + spotOrder, cgrid   # 0.21.65: + split

    def test_menus(self):
        p = self.p
        self.assertIn('items.push({ value: "rgedit", icon: "view", label: "Arrange for everyone in this room\\u2026"', p)
        self.assertIn('label: roomGridSet(name) ? "Use the room\\u2019s layout" : "Use the owner\\u2019s layout"', p)   # 0.21.65: rects or spots
        self.assertIn('items.push({ value: "rghidecam", icon: "eye", label: "Remove from this room",', p)
        self.assertIn('if (v === "rgedit") { rgEdit(name); return; }', p)
        self.assertIn('if (v === "rghidecam") { const g2 = gridChildOf.get(name); if (g2) rgHide(g2, name); return; }', p)
        can = self.sec("  const roomGridCan = (gp) =>", "\n")
        self.assertIn("boardCan() && gridMeta.has(gp) && !wrRoomOf(gp)", can)   # boardCan: publishers, not Lobby / box / viewer

    def test_editor_wiring(self):
        p = self.p
        rg = self.sec("  function rgEdit(name) {", "  async function rgHide(gp, mp) {")
        self.assertIn('boardGrid("gridHide", name, { member: mp })', rg)
        self.assertIn('boardGrid("gridShow", name, { member: mp })', rg)
        self.assertIn('boardGrid("gridReset", name, {})', rg)
        self.assertIn('boardGrid("grid", name, { rects, gap:', rg)
        self.assertIn('"Grid layout saved for everyone in " + roomTitle(room)', rg)
        self.assertIn('resetLabel: "Reset to the box\\u2019s layout"', rg)
        ed = self.sec("  const gridEditor = (() => {", "  window.__gridEditor = gridEditor;")
        self.assertIn('const x = mkEl("button", "gex", "\\u2715");', ed)   # 0.21.65: the builder -- a spot's x
        self.assertIn('"Removed (" + list.length + "):"', ed)
        self.assertIn('b.textContent = "Add back " + (x.label || "camera");', ed)
        self.assertIn("o.onDone?.(", ed)
        self.assertIn('mk(o.resetLabel || "Reset", "ghost"', ed)
        bg = self.sec("  async function boardGrid(op, gp, extra, quiet) {", "  window.__board = {")
        self.assertIn('const d = await boardPost(op, { path: gp, ...(extra || {}) }, quiet);', bg)

    def test_owner_announces_the_drawn_rects(self):
        # the room's layout crops each cell at the owner's announced rect: an announce made before the first draw had none
        draw = self.sec("  function drawRtspGrid(g) {", "    // 0.9.7: cells repaint individually")
        self.assertIn("g.lastRects = rects;", draw)
        draw = self.sec("    if (g.lastGeo !== geo) {", "\n    for ")
        self.assertIn("if (g.annGeo !== geo && live) { g.annGeo = geo; try { announceGrid(); } catch {} }", draw)

    def test_relay_page_counts_grids(self):
        with open(os.path.join(HERE, "relay.html"), encoding="utf-8") as f:
            r = f.read()
        self.assertIn('if (b.grids) parts.push(b.grids + " grid layout" + (b.grids === 1 ? "" : "s"));', r)


if __name__ == "__main__":
    unittest.main()
