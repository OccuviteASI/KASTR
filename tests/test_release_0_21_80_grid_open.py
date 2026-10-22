# -*- coding: utf-8 -*-
"""v0.21.80 GRID CELL OPEN. Kenton (2026-10-22): "I sometimes can't click on a single stream from a grid and go full quality. It
expands the view like it's going full and then closes immediately and goes back to the grid." -- "It is doing the snapback on
the regular grid, not just the pulled grid to my room." -- "On the mendon grid, it is happening on all cameras except the mining
loop and the main track."

Root causes (lab scratchpad v02180/grid: a Publisher box + a viewer, its grid in the viewer's own room and pulled into another):
  1. THE DOUBLE-CLICK (Mendon: every camera passed through, all bounce but two). A cell's first click opens its camera; a camera
     not decoding yet takes the cold open (0.21.15: the cell zooms -- "expands like it's going full" -- while the first frame
     comes). The second click was ignored (0.21.20), but the dblclick that follows saw the zoomed cell as "zoomed in" and
     un-zoomed it, which abandons the cold open -- back to the grid. A camera already decoding (split out in the room, a
     full-quality cell, shown elsewhere) opened instantly and survived: Mendon's two. Lab, five pass-through cameras (H.264 /
     H.265, 720p / 4K, one with audio), two split out: double-click 5 of 11 before (the 6 failures = every cold camera, status
     "Opening ... waiting for its first frame" then the grid), single click 11 of 11.
  2. A PARKED SLEEPING CAMERA. A transcoded camera sleeps while unwatched (0.21.73) so it has no tile at the click; the tile
     made when it wakes was made PARKED (kastr.watch.parked) -> gridOpenStart refused it -> select() -> the 0.21.66 guard "not
     watched" sent the stage back ~0.7 s after the click. Lab: 5 of 10 bounced before, every one this case.
  3. A PULLED GRID whose cameras are not listed in this room: no tile can ever come -- a click waited 90 s for nothing; and a
     listed camera that was asleep took ~10 s (no wake at the click).

What is proven here (static, the page is not run): a dblclick within the cell-open gesture does nothing; the click is the ask
(gridOpenStart and the wake path WATCH a parked camera instead of refusing it); a camera a click put on the stage is held for
GRID_PICK_GRACE_MS against a `down` flap and is never hidden while held; the 0.21.66 protection stays for automatic picks, a
removed camera, a camera without a tile and a camera still down after the grace; a listed camera without a tile gets one at the
click and is woken at once; an unreachable one stays on the cell with a reason; every "back to its grid" (and every abandoned
cell open) lands in a 20-entry ring that rides /api/diag (watcher.gridBacks)."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page():
    with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8", newline="") as f:
        return f.read()


class GridOpen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = page()

    def once(self, s):
        self.assertEqual(self.p.count(s), 1, s)

    def sec(self, start, end):
        i = self.p.index(start)
        j = self.p.index(end, i + len(start))
        return self.p[i:j]

    def guard(self):
        return self.sec("    autoContentCheck();\r\n    {", "    for (const lit of [...spotLits.values()]) {")

    # ---- the file -------------------------------------------------------------------------------------------------
    def test_page_stays_crlf(self):
        crlf = self.p.count("\r\n")
        self.assertGreater(crlf, 0)
        self.assertEqual(self.p.count("\n") - crlf, 0, "bare LF in moq-watch-lite.html")

    # ---- the diag ring ----------------------------------------------------------------------------------------------
    def test_ring_is_declared_before_applystate_runs(self):
        # applyState runs during module start-up: the ring and the pick's grace are declared with the other early state
        # (beside `let gridOpen`), never after function applyState (a TDZ error would kill the page)
        ring = self.p.index("const gridBackLog = [];")
        self.assertLess(self.p.index("let gridOpen = null;"), ring)
        self.assertLess(ring, self.p.index("  function applyState() {"))
        for s in ("let cellClick = null;", "function gridBackNote(kind, path, gp, why) {", "const GRID_PICK_GRACE_MS = 10000;",
                  "let gridPick = null;", "function gridPickNote(path) {", "const gridPickHeld = (path) =>"):
            self.once(s)
            self.assertLess(self.p.index(s), self.p.index("  function applyState() {"), s)

    def test_ring_keeps_the_last_twenty_with_reason_and_click_age(self):
        f = self.sec("function gridBackNote(kind, path, gp, why) {", "window.__gridBacks = ")
        self.assertIn("{ at: now, kind, path: p, gp: String(gp || \"\"), why: String(why || \"\"), clickAgoMs: cellClick && cellClick.path === p ? now - cellClick.at : null }", f)
        self.assertIn("if (gridBackLog.length > 20) gridBackLog.shift();", f)
        self.once("window.__gridBacks = () => gridBackLog.slice();   // rig")

    def test_ring_rides_the_diag(self):
        # __switcher.state() is the watcher half of the diag POST (/api/diag watcher.*)
        st = self.sec("  window.__switcher = {", "    }),")
        self.assertIn("gridBacks: gridBackLog.map((e) => ({ ...e, agoS: Math.round((Date.now() - e.at) / 1000) })),", st)

    def test_every_back_to_grid_is_noted(self):
        g = self.guard()
        self.assertIn('gridBackNote("guard", selectedName, gp, why);', g)
        self.assertIn('console.warn("KASTR: " + selectedName + " cannot be shown (" + why + ") -- back to its grid");', g)
        self.assertIn('gridBackNote("selfix", selectedName, gp, "an automatic pick of a grid camera");', self.sec("  function gridSelectionFix() {", "  function pruneGridMeta() {"))
        tick = self.sec("  function gridOpenTick() {", "  function gridOpenEnd(swap) {")
        self.assertIn('gridBackNote("open-end", o.path, o.gp,', tick)
        self.assertIn('gridBackNote("open-gave-up", o.path, o.gp, why);', tick)
        self.assertIn('gridBackNote("wake-gave-up", fp, gp, "no tile for the camera after 90 s");', self.sec("  function gridWakeStart(gp, idx, fp) {", "  function paintGridWait() {"))

    def test_clicks_stamp_the_ring_clock(self):
        self.once("if (fp) cellClick = { gp: name, idx, path: String(fp), at: Date.now() };   // 0.21.80: the diag ring's clock")
        self.once("if (k) cellClick = { gp: name, idx: -1, path: String(k), at: Date.now() };   // 0.21.80: the diag ring's clock")

    # ---- the cause: a parked camera that was asleep at the click ------------------------------------------------------
    def test_watchstream_has_a_quiet_form(self):
        f = self.sec("  function watchStream(name, quiet) {", "  function parkStream(name) {")
        self.assertIn("parkedStreams.delete(name);", f)
        self.assertIn("enabledStreams.add(name);", f)
        q = f.index("if (quiet) return;")
        self.assertLess(f.index('t.watch.setAttribute("url", tileUrl(name));'), q)   # the subscription is armed either way
        self.assertLess(q, f.index("applyState();"))                                  # ... the layout is the caller's

    def test_cold_open_watches_a_parked_camera_instead_of_refusing(self):
        f = self.sec("  function gridOpenStart(gp, idx, fp) {", "  function gridOpenBytes(o) {")
        self.assertIn("if (!t || t.fb || !CLIENT.webcodecs) return false;", f)
        self.assertNotIn("!isWatched(fp)) return false", f)
        w = f.index("if (!isWatched(fp)) watchStream(fp, true);")
        self.assertLess(f.index("if (gridMode || selfSpotEl || selectedName !== gp || !gridMeta.has(gp)) return false;"), w)   # only from the composite on the stage
        self.assertLess(w, f.index("gridOpen = { gp, idx, path: fp,"))

    def test_woken_camera_is_watched_before_it_opens(self):
        f = self.sec("  function gridWakeCheck(name) {", "  window.__gridWake = () => gridWake;")
        w = f.index("if (tiles.has(name) && !isWatched(name)) watchStream(name, true);")
        o = f.index("setTimeout(() => { if (tiles.has(name) && !gridOpenStart(gp, idx, name)) { gridPickNote(name); select(name); } }, 0);")
        self.assertLess(w, o)

    def test_every_click_pick_starts_the_grace(self):
        self.once("gridPickNote(fp); select(fp); return;")   # a warm camera: opened at once
        self.once("gridOpenEnd(true); gridPickNote(o.path); select(o.path); return;")   # the cold open's swap
        self.once("if (k && tiles.has(k)) { if (!isWatched(k)) watchStream(k, true); cgOpened = { cam: k, grid: name }; gridPickNote(k); select(k); return; }")   # a grid of cameras' spot
        # the 0.21.66 cell click still watches an awake parked camera first
        self.once("if (fp && tiles.has(fp) && !isWatched(fp)) watchStream(fp);")

    # ---- the 0.21.66 guard: held for a click, kept for everything else ------------------------------------------------
    def test_guard_condition_is_unchanged(self):
        g = self.guard()
        self.assertIn("if (gp && !gridMode && !selfSpotEl && tiles.has(gp) && (!tiles.has(selectedName) || !isWatched(selectedName) || deadMember(selectedName) || roomHid.has(selectedName))) {", g)
        self.assertIn('const why = !tiles.has(selectedName) ? "no tile" : !isWatched(selectedName) ? "not watched" : deadMember(selectedName) ? "down" : "removed here";', g)

    def test_guard_holds_only_a_recent_click(self):
        g = self.guard()
        self.assertIn("const held = manualPick && gridPickHeld(selectedName);", g)
        self.assertIn("const gridPickHeld = (path) => !!gridPick && gridPick.path === String(path) && Date.now() - gridPick.at < GRID_PICK_GRACE_MS;", self.p)
        # not watched + a click: watched, the stage stays
        i = g.index('if (held && why === "not watched") {')
        j = g.index('} else if (held && why === "down") {')
        k = g.index("} else {", j)
        nw = g[i:j]
        self.assertIn("watchStream(selectedName, true);", nw)
        self.assertNotIn("selectedName = gp", nw)
        # down + a click: held once, judged again when the grace ends
        dn = g[j:k]
        self.assertIn("if (!gridPick.held) {", dn)
        self.assertIn("setTimeout(() => { try { applyState(); } catch {} }, Math.max(0, GRID_PICK_GRACE_MS - (Date.now() - gridPick.at)) + 50);", dn)
        self.assertNotIn("selectedName = gp", dn)
        # everything else -- an automatic pick, no tile, removed here, down after the grace -- goes back to its grid (0.21.66)
        rest = g[k:]
        self.assertIn("gridZoom = null; selectedName = gp;", rest)
        self.assertEqual(g.count("selectedName = gp;"), 1)

    def test_no_tile_and_removed_are_never_held(self):
        g = self.guard()
        held = g[g.index('if (held && why === "not watched") {'):g.index("} else {", g.index('} else if (held && why === "down") {'))]
        self.assertNotIn('"no tile"', held)
        self.assertNotIn('"removed here"', held)
        self.assertIn("if (!tiles.has(name) || roomHid.has(name)) return;   // 0.21.64", self.sec("  function select(name) {", "  function step(delta) {"))

    def test_held_camera_is_not_hidden(self):
        self.once("(deadMember(name) && !(name === selectedName && !gridMode && gridPickHeld(name)))")
        h = self.sec("  const hiddenChild = (name) =>", "\r\n")
        self.assertNotIn("|| deadMember(name) ||", h)
        self.assertIn("roomHid.has(name)", h)

    def test_automatic_corrections_still_skip_a_click(self):
        # gridSelectionFix (a grid whose geometry arrives after its cameras) leaves a deliberate pick alone
        self.assertIn("if (manualPick || gridMode || !selectedName || !isGridChild(selectedName)) return;", self.sec("  function gridSelectionFix() {", "  function pruneGridMeta() {"))

    # ---- the double-click: one gesture, never an un-zoom of the cell it opens ----------------------------------------------
    def test_dblclick_on_an_opening_cell_does_nothing(self):
        d = self.sec('    pane.addEventListener("dblclick", (e) => {', "\r\n    });")
        sw = d.index("if (gridDblIsCellOpen(pane)) { e.preventDefault(); return; }")
        self.assertLess(d.index("clearTimeout(pane.__clickT); pane.__clickT = null;"), sw)
        self.assertLess(sw, d.index("if (!c || !allow()"))
        self.assertLess(sw, d.index("if (viewZoomed(c)) { gridOpenEnd(false); gridZoom = null; viewReset(c); }"))   # the un-zoom that abandoned the open

    def test_dbl_gesture_window(self):
        f = self.sec("  function gridDblIsCellOpen(pane) {", "  window.__gridDblIsCellOpen = ")
        self.once("const GRID_DBL_MS = 800;")
        self.assertIn("if ((gridOpen && on(gridOpen.gp)) || (gridWake && on(gridWake.gp))) return true;", f)   # a cell opening / waking
        self.assertIn("return !!cellClick && Date.now() - cellClick.at < GRID_DBL_MS && (on(cellClick.gp) || on(cellClick.path));", f)   # the grid clicked, or the camera it opened at once
        self.assertIn("const on = (n) => !!n && tiles.get(n)?.pane === pane;", f)

    def test_second_click_still_never_cancels(self):
        self.once("if (gridOpen && gridOpen.gp === name) { gridOpen.clicks = (gridOpen.clicks || 0) + 1; paintGridWait(); return; }")   # 0.21.20

    # ---- a camera that falls asleep around the click (0.21.73) ----------------------------------------------------------
    def test_click_always_asks_the_box(self):
        c = self.click()
        self.assertIn("odWake(fp);   // 0.21.80: the click IS a viewer", c)
        self.assertNotIn("if (!fullLive.has(fp) && (odFeeds.some((f) => f.broadcast === fp) || lowAvail.has(fp))) odWake(fp);", c)

    def test_opening_camera_resubscribes_when_it_comes_back(self):
        tick = self.sec("  function gridOpenTick() {", "  function gridOpenEnd(swap) {")
        # no demand loop of its own while it opens (odPulse already pulses a subscribed grid camera): a stream the relay does not
        # deliver must still be free to sleep and come back fresh (lab: an awake pulled camera whose route never delivered)
        self.assertNotIn("odWake(o.path)", tick)
        self.assertIn('// (5) one retry, never a loop\r\n    if (now - o.at > GRID_OPEN_GIVEUP_MS) {', tick)   # the give-up is code, not part of the comment
        self.once("if (!b.startsWith(CHANNEL + \"/\") && tiles.has(b) && hasPicture(tiles.get(b))) { odWanted.delete(b); continue; }")   # another room's camera: its click demand ends with its picture
        self.assertIn('if (o.bytes <= 0 && !o.retried && now - o.at > GRID_OPEN_NODATA_MS) { o.retried = true; resubscribe(o.path, "No data from the relay"); }', tick)   # still one retry, never a loop
        self.once('else if (gridOpen && gridOpen.path === path && !(gridOpen.bytes > 0)) resubscribe(path, "The camera came back while it was opening");')
        i = self.p.index('else if (gridOpen && gridOpen.path === path && !(gridOpen.bytes > 0)) resubscribe(')
        self.assertLess(self.p.index("if (!tiles.has(path)) createTile(path);", i - 400), i)   # in the announce loop's active branch

    def test_camera_leaving_mid_open_waits_on_the_cell(self):
        tick = self.sec("  function gridOpenTick() {", "  function gridOpenEnd(swap) {")
        a = tick.index("if (!t && !gridMode && !selfSpotEl && selectedName === o.gp && gridMeta.has(o.gp)) {")
        self.assertLess(a, tick.index("if (!t || gridMode || selfSpotEl || selectedName !== o.gp || !gridMeta.has(o.gp)) {"))
        blk = tick[a:tick.index("if (!t || gridMode")]
        self.assertIn("if (gridWakeStart(gp, idx, path)) { gridBackNote(\"open-wait\", path, gp,", blk)   # woken, the cell stays
        self.assertIn('gridBackNote("open-end", path, gp, "the camera\'s tile left (its grid lists it down)");', blk)   # a down camera: back to its grid

    # ---- a pulled grid (shown here from another room) ------------------------------------------------------------------
    def click(self):
        return self.sec("        const meta = gridMeta.get(name);\r\n        if (meta && meta.n > 1", "        gridMode = true; applyState();")

    def test_listed_camera_without_a_tile_gets_one_at_the_click(self):
        c = self.click()
        mk = c.index("if (fp && !tiles.has(fp) && xsTiles.has(fp) && !publishOnly) { cancelPendingRemoval(fp); createTile(fp); }")
        self.assertLess(mk, c.index("if (fp && tiles.has(fp) && !isWatched(fp)) watchStream(fp);"))
        self.assertLess(mk, c.index("if (gridOpenStart(name, idx, fp)) return;"))

    def test_unreachable_camera_stays_on_the_cell_with_a_reason(self):
        self.once("const gridCamReachable = (fp) => { const r = String(fp).split(\"/\", 1)[0]; return r === CHANNEL || xsTiles.has(String(fp)) || watchRooms.has(r) || tiles.has(String(fp)); };")
        c = self.click()
        i = c.index("if (fp && !gridCamReachable(fp)) {")
        self.assertLess(i, c.index("if (fp && gridWakeStart(name, idx, fp)) return;"))   # never a 90 s wait for a tile that cannot come
        blk = c[i:c.index("if (fp && gridWakeStart(name, idx, fp)) return;")]
        self.assertIn('gridBackNote("cell-only", fp, name,', blk)
        self.assertIn("is not shown in this room at full quality \\u2014 this is the grid\\u2019s picture", blk)
        self.assertIn("gridZoom = { name, idx }; fitMainstage(lastRail.rows); paintGridZoom(); return;", blk)
        self.assertNotIn("select(", blk)

    def test_cell_point_rig_hook_maps_like_the_click(self):
        f = self.sec("  window.__gridCellPoint = (gp, idx) => {", "  };")
        self.assertIn("vgLaidOut(meta.path) ? vgDstRects(meta.path, meta, f.cw, f.ch) : gridRectsOf(meta, f.cw, f.ch)", f)
        self.assertIn("vgLaidOut(meta.path) ? vgDstRects(meta.path, meta, f.cw, f.ch) : gridRectsOf(meta, f.cw, f.ch)", self.sec("  function gridCellAtW(t, meta, ev) {", "  }"))

    def test_new_code_is_ascii(self):
        for a, b in (("const gridBackLog = [];", "window.__gridBacks = "), ("const GRID_PICK_GRACE_MS", "const gridPickHeld"),
                     ("if (held && why", "gridZoom = null; selectedName = gp;")):
            s = self.sec(a, b)
            self.assertEqual(sorted({ch for ch in s if ord(ch) > 127}), [], a)

    def test_style_marker(self):
        self.assertGreaterEqual(len(re.findall(r"// 0\.21\.80", self.p)), 4)
        self.assertIn('0.21.80 (Kenton: "It expands the view like it\'s going full and then closes immediately and goes back to the grid")', self.p)


if __name__ == "__main__":
    unittest.main()
