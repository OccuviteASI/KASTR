"""0.21.91 (Kenton: "I believe the cameras off option in the view menu was misinterpreted. I want this to turn off my own shares
from me seeing them, not turn off for everyone. It's still using a bit of CPU to just show them."): the View menu has BOTH --
"Hide my shares" (this screen only, remembered per device) and the 0.21.16 switch, renamed "Stop my cameras for everyone".

Hide my shares: module 1 tags my own panes .hidemine (out of the stage, gallery and rail); module 2 stops their LOCAL previews
(an element share's preview renderer -> preview="none"; an RTSP camera's monitor player outside a grid -> detached) while every
publish pipeline keeps running (grid members keep their monitors: the mosaic is composed on this page from them). A pane I put
on my own stage deliberately (__selfSpot) shows while it holds it. Lab proof (CPU before/after, a viewer still receiving):
docs/review-0.21.91 + the 0.21.91 report. No network, no processes here.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def between(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


class ViewMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = read("moq-watch-lite.html")

    def once(self, x):
        self.assertEqual(self.s.count(x), 1, "expected exactly once: %r" % x)

    def test_both_items(self):
        self.once('id="viewHideMine"')
        self.once('Hide my shares<span class="chk">&#10003;</span></button>')
        self.once('Stop my cameras for everyone (spare CPU)<span class="chk">&#10003;</span></button>')
        self.assertNotIn("Cameras off (spare CPU)", self.s)
        # Hide my shares comes right before the renamed switch, inside the View card
        pop = between(self.s, '<div id="viewPop"', '<div id="camPop"')
        self.assertLess(pop.index('id="viewHideMine"'), pop.index('id="viewRtspOff"'))
        self.assertIn("NOBODY sees them while this is on", pop)
        self.assertIn("Everyone else still sees them live", pop)

    def test_switch_toasts_name_the_new_items(self):
        self.once("View \\u25b8 Stop my cameras for everyone) turns them back on.")
        self.once("(To stop only drawing them here: View \\u25b8 Hide my shares.)")
        self.assertNotIn("View \\u25b8 Cameras off", self.s)

    def test_state_is_remembered_and_declared_early(self):
        self.once('let hideMine = false, mineShowEl = null;')
        self.once('try { hideMine = localStorage.getItem("kastr.view.hideMine") === "1"; } catch {}')
        self.once('try { localStorage.setItem("kastr.view.hideMine", hideMine ? "1" : "0"); } catch {}')
        # declared before applyState (which reads it) -- no temporal-dead-zone error on the first layout
        self.assertLess(self.s.index("let hideMine = false"), self.s.index("  function applyState() {"))
        # a viewer device has no shares: the item hides with Hide me
        self.once('for (const id of ["shareBtn", "stopShareBtn", "viewPublishOnly", "viewHideMe", "viewHideMine", "joinPreview"]) {')

    def test_view_menu_paints_the_tick(self):
        self.once('on("viewHideMine", hideMine);   // 0.21.91')

    def test_prefs_mirror_keeps_it(self):
        self.assertIn("|view\\.hideMine$|theme$|theme\\.custom$|accent$|selfmirror$)/;", read(os.path.join("assets", "prefs.js")))
        self.assertIn('|toasts\\.|rooms\\.groups\\.|view\\.hideMine$"\n                         r"|theme$|theme\\.custom$|accent$|selfmirror$)")', read("kastr_serve.py"))
        import importlib, sys
        sys.path.insert(0, ROOT)
        ks = importlib.import_module("kastr_serve")
        self.assertTrue(ks.PREFS_ALLOW.match("kastr.view.hideMine"))
        self.assertFalse(ks.PREFS_ALLOW.match("kastr.view.hideMineX"))


class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = read("moq-watch-lite.html")

    def test_css_takes_hidden_panes_out(self):
        self.assertIn("  #stage .pubpane.hidemine { display:none !important; }", self.s)
        self.assertIn("#hideMineNote[hidden] { display:none; }", self.s)

    def test_cells_and_rail_skip_hidden_panes(self):
        st = between(self.s, "  function applyState() {", "    const railRemote = ")
        self.assertIn("try { tagHideMine(); } catch {}   // 0.21.91: before the cells are counted", st)
        self.assertLess(st.index("tagHideMine()"), st.index("const ownCells"))
        self.assertIn('!el.classList.contains("hideme") && !el.classList.contains("hidemine")).length;', st)
        self.assertIn('!pe.classList.contains("hideme") && !pe.classList.contains("hidemine"));', st)

    def test_tagging(self):
        f = between(self.s, "  function tagHideMine() {", "  function paintHideMineNote() {")
        self.assertIn("const want = hideMine && pe !== mineShowEl;", f)
        # the deliberate pick ends when it leaves my stage (another pick, the gallery, the switch off, a rebuilt pane)
        self.assertIn("if (mineShowEl && (!hideMine || !mineShowEl.isConnected || selfSpotEl !== mineShowEl || gridMode)) mineShowEl = null;", f)
        self.assertIn("if (changed) { try { window.__pubPreviewSync?.(); } catch {} }", f)
        self.assertIn('new MutationObserver(() => { tagHideMine(); }).observe(document.getElementById("pubPanes"), { childList: true });', self.s)

    def test_override_is_my_own_pick_only(self):
        sp = between(self.s, "  window.__selfSpot = (pane) => {", "    applyState();\n  };")
        self.assertIn('if (hideMine && pane?.classList?.contains("hidemine")) mineShowEl = pane;', sp)
        # the room's spotlight puts my pane in selfSpotEl directly -- it never sets mineShowEl
        win = between(self.s, "  function spotApplyWinner() {", "  window.__spotApply = spotApplyWinner;")
        self.assertNotIn("mineShowEl", win)

    def test_notes(self):
        self.assertIn('<div id="hideMineNote" hidden', self.s)
        self.assertIn("Your shares are hidden on this screen &middot; still live for everyone", self.s)
        self.assertIn('<p class="hint" id="hideMineShNote" hidden>Your shares are hidden on this screen (View &#9656; Hide my shares)', self.s)
        n = between(self.s, "  function paintHideMineNote() {", "  function setHideMine(on) {")
        self.assertIn('[...pp.children].some((pe) => pe.classList.contains("hidemine"))', n)


class Previews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = read("moq-watch-lite.html")
        cls.f = between(cls.s, "  function pubPreviewSync() {", "  window.__pubPreviewSync = pubPreviewSync;")

    def test_element_shares_draw_no_preview(self):
        self.assertIn('const want = previewOff.checked || hid ? "none" : "source";', self.f)
        self.assertIn('if (slot.publish.getAttribute("preview") !== want) slot.publish.setAttribute("preview", want);', self.f)

    def test_vendored_element_stops_its_renderer_on_none(self):
        # the element observes `preview`; its canvas renderer stops pulling frames on "none" (the encoder reads the capture)
        el = read(os.path.join("assets", "vendor", "esm", "@moq", "publish@0.5.2", "es2022", "element.mjs"))
        self.assertIn('var S=["url","name","muted","invisible","source","preview","announce"]', el)
        enc = read(os.path.join("assets", "vendor", "esm", "@moq", "publish@0.5.2", "es2022", "encoder-CjcsUSCu.mjs"))
        self.assertIn('if(t==="none"||!e.get(this.in.enabled)){e.set(this.#t,void 0);return}', enc)

    def test_rtsp_monitor_detached_outside_a_grid_only(self):
        self.assertIn("const off = hid && !!slot.native && !slot.inGrid && slot.entry.feedId != null;", self.f)
        self.assertIn("detachMonitor(slot);", self.f)
        self.assertIn("if (!rtspSuspended && slots.get(slot.entry.id) === slot) restartMonitor(slot);", self.f)
        self.assertIn("if (slot.entry.retryTimer) { clearTimeout(slot.entry.retryTimer); slot.entry.retryTimer = null; }", self.f)

    def test_pip_keeps_its_preview(self):
        self.assertIn('const hid = !!slot.pane?.classList?.contains("hidemine") && !slot.pip && !(pip && slot.entry.kind === "camera");', self.f)

    def test_ladder_never_reattaches_a_hidden_monitor(self):
        self.assertIn("    if (slots.get(entry.id)?.monHidden) return;   // 0.21.91: Hide my shares detached this monitor on purpose", self.s)
        self.assertIn("      if (slot.monHidden) return;   // 0.21.91: hidden on this screen meanwhile", self.s)
        self.assertIn("if (!rtspSuspended && slots.get(s.entry.id) === s && !s.monHidden) restartMonitor(s); };", self.s)

    def test_grid_membership_change_resyncs(self):
        g = between(self.s, "  function updateRtspGrid(modeSwitch) {", "  function stopSlot(id) {")
        self.assertIn("try { pubPreviewSync(); } catch {}   // 0.21.91", g)

    def test_grid_keeps_drawing(self):
        d = between(self.s, "  function drawRtspGrid(g) {", "  function gridCellAt(g, ev) {")
        self.assertNotIn("hidemine", d)   # the encoder reads the grid's canvas: nothing here looks at Hide my shares


if __name__ == "__main__":
    unittest.main()
