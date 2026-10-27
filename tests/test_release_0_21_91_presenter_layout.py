# -*- coding: utf-8 -*-
"""v0.21.91 (Kenton, 2026-10-27: "I want to make sure the notes section is big enough to read all of the notes for anyone. If we
need to make any of the other sections smaller, then we can do that. The most important part is seeing my own preview and the
notes for that page.").

Decided (Kenton): (1) the live slide and (2) its NOTES first; everything else gives way. The live slide stays large on the left;
the notes take the rest of the right column; ONE small next slide; the mode picker, the Reporter backgrounds, mic / camera /
audience and the Presenters / Backstage sections are compact collapsible panels (closed at first, opening by themselves when
they need attention); a thinner strip that can be hidden; a draggable divider between the columns and one above the notes; the
layout remembered per device; the same for co-presenters and backstage; 1366x768 to 2560x1440, 200 % and phone width.
Lab (scratchpad v02191/copresent, pw_layout.py): a 267-word note at the default size -- 1920x1080: 7 -> 27 lines visible (all of
it); 1366x768: 2 -> 19 of 26 lines."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


JS = read("assets/kastr-pres.js")
CSS = JS[JS.index("  const CSS = `"):JS.index("  const view = (() => {")]


def block(src, start, end):
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


class Structure(unittest.TestCase):
    def test_slide_left_notes_take_the_rest(self):
        self.assertIn("grid-template-columns: minmax(0, var(--lcol, 3fr)) 10px minmax(280px, var(--rcol, 2fr));", CSS)
        self.assertIn("#presView .notes { flex:1; min-height:120px; overflow:auto;", CSS)   # scrolls only when it truly does not fit
        self.assertIn("#presView .panels { flex:none; max-height:var(--ptop, 42%); overflow:auto;", CSS)
        self.assertIn("#presView .side { display:flex; flex-direction:column; gap:6px; min-height:0; overflow:hidden; }", CSS)

    def test_one_small_next_slide(self):
        self.assertIn('<div class="nxt" title="The next slide"><canvas class="n1"></canvas><span class="nxl"></span></div>', JS)
        self.assertNotIn('class="n2"', JS)
        self.assertNotIn(".nexts", JS)
        pt = block(JS, "    async function paint() {", "    function paintAll()")
        self.assertIn("const cvs = [[$(\".curcv\"), v.idx, null], [$(\".n1\"), v.idx + 1, null]];", pt)
        self.assertIn("#presView .nxt canvas { width:84px;", CSS)

    def test_collapsible_panels_closed_at_first(self):
        for k in ("mode", "av", "ppl"):
            self.assertIn('<details class="pnl" data-k="%s">' % k, JS)
        lb = block(JS, "    function layoutBuild() {", "    function panelInfo(v, M) {")
        self.assertIn("d.open = !!(LY.open && LY.open[d.dataset.k]);", lb)   # closed unless this device opened it
        self.assertIn("#presView details.pnl[open] { flex-basis:100%; order:-1; }", CSS)   # closed ones share one row
        ub = block(JS, "  function modeUiBuild(root) {", "  // what the presenter view's deck shows")
        self.assertIn('const side = root.querySelector(".pmode") || root.querySelector(".side");', ub)
        self.assertIn('{ const pav = root.querySelector(".pav"); if (pav) pav.appendChild(mui.av); }', ub)

    def test_attention_opens_a_panel(self):
        pi = block(JS, "    function panelInfo(v, M) {", "    function setFs(v) {")
        self.assertIn("if (attn && !was && !d.open) { d.dataset.auto = \"1\"; d.open = true; }", pi)
        self.assertIn("const ex = panelAvInfo(v);", pi)
        pa = block(JS, "  function panelAvInfo(v) {", "  function amAct(v) {")
        self.assertIn("attn: hs.length > 0 && v.role !== \"backstage\"", pa)   # raised hands
        self.assertIn('set("mode",', pi)

    def test_no_preview_work_while_its_panel_is_closed(self):
        mf = block(JS, "  function modeUiFrame() {", "  let roomBlank")
        self.assertIn('if (!mui.box.closest("details")?.open) {', mf)


class Remembered(unittest.TestCase):
    def test_dividers_strip_and_panels_per_device(self):
        self.assertIn('try { LY = JSON.parse(localStorage.getItem("kastr.pres.layout") || "{}") || {}; } catch {}', JS)
        lb = block(JS, "    function layoutBuild() {", "    function panelInfo(v, M) {")
        self.assertIn('dragLine($(".vdiv"),', lb)
        self.assertIn('dragLine($(".hdiv"),', lb)
        self.assertIn('if (k === "ArrowLeft")', lb)   # the keyboard too
        self.assertIn('$(".stripbtn").addEventListener("click"', lb)
        la = block(JS, "    function layoutApply() {", "    function dragLine(")
        self.assertIn('LY.nostrip === undefined ? window.innerHeight < 900 : !!LY.nostrip', la)   # a short window starts without the strip
        self.assertIn("Math.max(0.3, Math.min(0.78,", la)
        # Kenton: below ~800 px tall the slide column shrinks so the notes widen (the font stays as the person set it)
        self.assertIn("(window.innerHeight < 740 ? 0.4 : window.innerHeight < 800 ? 0.46 : 0.6)", la)
        self.assertIn('try { fs = Number(localStorage.getItem("kastr.pres.notesSize")) || 20; } catch {}', JS)   # A- / A+ per device

    def test_thinner_strip(self):
        self.assertIn("#presView .strip .th canvas { width:88px; height:50px;", CSS)
        self.assertIn("#presView.nostrip .strip { display:none; }", CSS)


class Everywhere(unittest.TestCase):
    def test_phone_width(self):
        ph = CSS[CSS.index("@media (max-width: 760px) {"):]
        self.assertIn("#presView .pb { display:flex; flex-direction:column; }", ph)
        self.assertIn("#presView .vdiv, #presView .hdiv { display:none; }", ph)
        self.assertIn("#presView .panels { order:3; max-height:none; }", ph)   # notes before the panels

    def test_same_layout_for_copresenters_and_backstage(self):
        # one view for every role: the same markup; backstage only has fewer controls in the panels
        self.assertEqual(JS.count('<div class="side">'), 1)
        pp = block(JS, "    function paintPeople(v, M) {", "    // the people picker")
        self.assertIn('$(".addp").style.display = M.edit ? "" : "none";', pp)


if __name__ == "__main__":
    unittest.main()
