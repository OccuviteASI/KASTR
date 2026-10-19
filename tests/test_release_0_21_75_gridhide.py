# -*- coding: utf-8 -*-
"""v0.21.75 (Kenton: "hide individual cameras in my grid view"): a viewer hides cameras of a grid on THEIR screen only.

A box's camera grid: my view of it (kastr.vgrid.<grid>) keeps `hidden: [vgKey(camera)]`; vgEff unions them into the hidden set
of whatever layout draws the grid (mine, the room's, the owner's), so the rest reflow and clicks never land on a hidden camera;
their own tiles leave my gallery / rail / stage (myHid folded into roomHid). Right-click a cell: "Hide <camera> for me"; "Show
hidden cameras (n)..." brings them back; the "Arrange this grid for me" editor removes / adds back the same way. A grid of
cameras from any room (0.21.66 e) keeps its own device-local hides (kastr.cghide.<relay>, "<grid id>|<camera>"). Nothing is sent
anywhere: nobody else sees a change.

Run: python -m unittest discover -s tests
"""
import os, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EOL = chr(13) + chr(10)   # the page is CRLF
BS = chr(92)


class Page(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), "rb") as f:
            raw = f.read()
        self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))   # CRLF throughout
        self.p = raw.decode("utf-8")

    def sec(self, a, b):
        p = self.p
        i = p.index(a)
        return p[i:p.index(b, i + len(a))]

    def test_vgset_keeps_a_view_with_only_hidden_cameras(self):
        s = self.sec("  function vgSet(gp, v) {", EOL + "  }" + EOL)
        self.assertIn("!(v.slots || []).length && !(v.hidden || []).length)) localStorage.removeItem(VG_KEY + vgKey(gp));", s)
        self.assertIn("try { roomGridChanged(); }", s)   # the camera's own tile goes / comes back at once

    def test_vgeff_unions_my_hidden_for_every_source(self):
        eff = self.sec("  function vgEff(gp) {", "  const vgLaidOut =")
        self.assertIn("const v = vgGet(gp), hidden = vgMineHidden(gp, v, new Set(roomGridOf(gp)?.hidden || []));", eff)
        # the one `hidden` set is what the me / room / owner returns carry; the draft (the room editor) stays the room's own
        for src in ('src: "me"', 'src: "room"', 'src: "owner"'):
            line = [ln for ln in eff.split(EOL) if src in ln][0]
            self.assertIn(" hidden, key:", line)
        mh = self.sec("  function vgMineHidden(gp, v, into) {", EOL + "  }" + EOL)
        self.assertIn("for (const mp of vgCamsOf(gridMeta.get(gp))) if (ks.includes(vgKey(mp))) into.add(mp);", mh)
        self.assertIn("const vgLaidOut = (gp) => { const e = vgEff(gp); return !!(e.rects || e.slots || e.hidden.size); };", self.p)

    def test_reflow_and_clicks(self):
        dst = self.sec("  function vgDstRects(gp, meta, W, H, noGap) {", "  function vgHqWanted(")
        self.assertIn("return ms.map((mp) => (e.hidden.has(mp) ? null : px(auto[j++])));", dst)
        self.assertIn("return rs.findIndex((r) => r && px >= r.x", self.p)

    def test_my_hidden_folds_into_roomhid(self):
        rb = self.sec("  function roomHidRebuild() {", EOL + "  }" + EOL)
        self.assertIn("roomHidBoard.clear(); for (const m of roomHid) roomHidBoard.add(m);", rb)
        self.assertIn("myHid.clear(); for (const gp of gridMeta.keys()) vgMineHidden(gp, vgGet(gp), myHid);", rb)
        self.assertIn("for (const m of myHid) roomHid.add(m);", rb)
        self.assertLess(rb.index("roomHidBoard.clear()"), rb.index("for (const m of myHid) roomHid.add(m);"))
        self.assertIn("const myHid = new Set(), roomHidBoard = new Set();", self.p)
        # a camera I hid joining a grid later is hidden at once
        ga = self.sec("  function gridApply(path, meta, ts, active) {", "  function gridCellAtW(")
        self.assertIn('const was = [...myHid].join("|"); roomHidRebuild(); if ([...myHid].join("|") !== was) roomGridChanged();', ga)
        # on my stage: back to its grid (roomGridChanged), and the Build-a-grid list still offers it (the room's removals only)
        self.assertIn("if (selectedName && roomHid.has(selectedName)) {", self.sec("  function roomGridChanged() {", "  const roomGridCan ="))
        self.assertIn("mineNames.has(p) || roomHidBoard.has(p) || !p.endsWith", self.sec("  function cgStreams() {", "  function cgClean("))

    def test_cell_menu_items(self):
        p = self.p
        self.assertIn('items.push({ value: "vghide", icon: "eye", label: "Hide " + String(gm.cells?.[idx] || "this camera").slice(0, 24) + " for me"', p)
        self.assertIn('if (nh) items.push({ value: "vgshow", icon: "eye", label: "Show hidden cameras (" + nh + ")' + BS + 'u2026"', p)
        self.assertIn('if (v === "vghide") { if (hqCell) vgHideMine(name, hqCell); return; }', p)
        self.assertIn('if (v === "vgshow") { hidShowMenu(anchor, vgMyHidList(name), (ks) => vgShowMine(name, ks)); return; }', p)
        # the hide item is NOT gated by roomGridCan: viewers have it
        menu = self.sec("                hqCell = mp;", "                const on = vgHq(name).has(vgKey(mp));")
        i = menu.index('value: "vghide"')
        line = menu[menu.rindex(EOL, 0, i):i]
        self.assertNotIn("roomGridCan", line)

    def test_hide_and_show(self):
        hm = self.sec("  function vgHideMine(gp, mp, quiet) {", EOL + "  }" + EOL)
        self.assertIn("h.add(k); v.hidden = [...h];", hm)
        self.assertIn('v.hq = v.hq.filter((x) => String(x) !== k);', hm)   # its full-quality cell goes with it
        self.assertIn("Keep at least one camera in the grid", hm)
        sm = self.sec("  function vgShowMine(gp, keys, inEditor) {", EOL + "  }" + EOL)
        self.assertIn("v.hidden = (v.hidden || []).map(String).filter((k) => !ks.has(k));", sm)
        self.assertIn("v.slots.push({ rect: u, cams: [k], cycle: null })", sm)   # my spots: a free block of its own
        menu = self.sec("  function hidShowMenu(anchor, list, show) {", EOL + "  }" + EOL)
        self.assertIn("setTimeout(() => openMineMenu(anchor, items, \"\", (v) => {", menu)   # after the first menu's click closed it
        self.assertIn('{ value: "all", icon: "eye", label: "Show all (" + list.length + ")" }', menu)

    def test_my_editor_removes_and_adds_back(self):
        ed = self.sec("  function vgEdit(name) {", "  function rgEdit(name) {")
        self.assertIn("removed: () => vgMyHidList(name),", ed)
        self.assertIn("onRemove: (k) => { const mp = vgCamsOf(meta).find((m) => vgKey(m) === k); return mp ? vgHideMine(name, mp, true) : false; },", ed)
        self.assertIn("onAddBack: (k) => { vgShowMine(name, [k], true); return true; },", ed)
        self.assertIn("const skip = (mp) => roomHid.has(mp);", ed)   # room + mine
        self.assertIn("h = vgGet(name)?.hidden || []; if (h.length) v.hidden = h; else delete v.hidden;", ed)   # Cancel keeps them hidden

    def test_cross_room_grid_hides(self):
        p = self.p
        self.assertIn('const cghKey = () => "kastr.cghide." + sbRelayHost();', p)
        self.assertIn('const cgHid = (id, k) => cghSet().has(id + "|" + k);', p)
        tick = self.sec("  function cgTick() {", EOL + "  }" + EOL)
        self.assertIn("const avail = cgVis(t, (s.cams || []).map(String)).filter((k) => tiles.has(k));", tick)
        draw = self.sec("  function cgDraw(n, t) {", "  function cgCamAt(")
        self.assertIn("cams = cgVis(t, all)", draw)
        self.assertIn('(all.length ? "Hidden for you" : "Empty spot")', draw)
        sync = self.sec("  function cgSync() {", "  setInterval(() => { try { cgSync(); }")
        self.assertIn("if (!cgHid(d.id, String(k))) cgCams.add(String(k));", sync)
        menu = self.sec("  function cgMenu(anchor, name) {", "  window.__cg = {")
        self.assertIn('items.push({ value: "cghide", icon: "eye", label: "Hide " + cgLabelOf(hcam).slice(0, 24) + " for me"', menu)
        self.assertIn('items.push({ value: "cgshow", icon: "eye", label: "Show hidden cameras (" + nHid + ")', menu)
        self.assertIn("cgHidPut(def.id, [hcam], true);", menu)
        self.assertIn("(ks) => cgHidPut(def.id, ks, false)", menu)
        # the hide is offered outside `if (can)` -- viewers of a room grid have it
        self.assertLess(menu.index('value: "cghide"'), menu.index("    if (can) {"))

    def test_build_a_grid_still_offered(self):
        self.assertIn("function cgNew() {", self.p)
        self.assertIn("window.__cg = { list:", self.p)


if __name__ == "__main__":
    unittest.main()
