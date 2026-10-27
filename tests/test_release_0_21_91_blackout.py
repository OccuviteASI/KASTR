# -*- coding: utf-8 -*-
"""v0.21.91 (Kenton, 2026-10-27: "If I use the black/white out option, I want to still see the preview myself, and only hide it for
the room. It should stay persistent until I turn it off, not just for that 1 slide.").

Decided (Kenton):
  1. Black / White hides the slide for the ROOM only: the presenters' and backstage views keep the real slide (live, notes,
     next) with a "Room sees: Black" / "Room sees: White" marker and the button lit; viewers and recordings get the blank; a
     playing slide video / sound clip keeps playing under it.
  2. It persists across slide changes until a presenter (or backstage) turns it off; Black <-> White switches directly; late
     joiners see the blank.
  3. Every presenter mode: the blank covers the slide area only -- the presenter's camera / cut-out stays in front of it."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


JS = read("assets/kastr-pres.js")


def block(src, start, end):
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


class PersistsAcrossMoves(unittest.TestCase):
    def test_a_move_keeps_the_blank(self):
        go = block(JS, "  function goTo(i, by, blank) {", "  async function postLive(")
        self.assertIn("const nb = blank === undefined ? mine.blank : (blank || null);", go)
        st = block(JS, "    function step(d) {", "    function blank(kind) {")
        self.assertIn("goTo(to, myPerson());", st)   # no blank argument: kept
        self.assertIn("sendIntent(v.id, to);", st)
        self.assertNotIn("null)", st)
        ao = block(JS, "  function applyOp(ctl, who, isP) {", "  let rewrapT = null;")
        self.assertIn("goTo(ctl.to, who, ctl.blank);", ao)   # a 0.21.91 backstage / co-presenter Next keeps it too
        self.assertIn('go: (i) => { const v = view.deck(); if (!v) return false; if (v.role === "presenter") goTo(i, myPerson()); else sendIntent(v.id, i);', JS)

    def test_black_to_white_directly(self):
        bl = block(JS, "    function blank(kind) {", "    function toggleEdit() {")
        self.assertIn("const nb = v.blank === kind ? null : kind;", bl)


class TheRoomOnly(unittest.TestCase):
    def test_no_key_and_no_live_slide_under_a_blank(self):
        pub = block(JS, "  function publish() {", "  function goTo(")
        self.assertIn('k: mine.blank ? "" : b64(kIdx)', pub)
        go = block(JS, "  function goTo(i, by, blank) {", "  async function postLive(")
        self.assertIn("if (nb || ni === m.liveIdx) tell();", go)   # the store is not told the slide underneath
        self.assertIn("m.liveChain = m.liveChain.then(() => postLive(m, ni)).then(tell, tell);", go)   # unblank: the store first

    def test_viewers_and_the_recording_get_the_blank(self):
        ds = block(JS, "  async function drawShare() {", "  let endMark")
        self.assertIn("drawContain(m.shareCv, bmp, m.blank,", ds)   # the share (older KASTRs, phones, the recorder)
        po = block(JS, "  async function paintOverlay(path, o) {", "  // ---- the presenter view")
        self.assertIn("if (!rec.blank) {", po)   # a viewer fetches nothing under a blank
        vf = block(JS, "  function vidFrame() {", "  // ---- 0.21.89: PRESENTER MODES")
        self.assertIn("!rec.blank && x.k !== \"a\"", vf)   # the video is not drawn for the room (its sound goes on)

    def test_presenter_and_backstage_views_keep_the_slide(self):
        pt = block(JS, "    async function paint() {", "    function paintAll()")
        self.assertIn('rs.textContent = v.blank === "black" ? "Room sees: Black" : v.blank === "white" ? "Room sees: White" : "";', pt)
        self.assertIn("[$(\".curcv\"), v.idx, null]", pt)   # the real slide, never the blank
        self.assertIn('$(".blk").classList.toggle("on", v.blank === "black");', pt)
        dv = block(JS, "    function drawVid() {", "    let paintSeq")
        self.assertNotIn("!mine.blank", dv)   # the playing video shows in the view under the room's blank
        self.assertNotIn("!v.blank", dv)

    def test_what_the_room_sees_preview_shows_the_blank(self):
        self.assertIn("let roomBlank = (mv) => mv.v.blank;", JS)
        mf = block(JS, "  function modeUiFrame() {", "  let roomBlank")
        self.assertIn("drawLaid(cv, mui.still.bmp, roomBlank(mv), mv.eff, ar,", mf)

    def test_camera_stays_over_the_blank_in_camera_modes(self):
        dl = block(JS, "  function drawLaid(cv, bmp, blank, mode, ar, label, rbg) {", "  function drawBoxCam(")
        self.assertIn('g.fillStyle = blank === "white" ? "#fff" : "#000"; g.fillRect(s.x, s.y, s.w, s.h);', dl)   # the slide area only
        cl = block(JS, "  function camLayer(o) {", "  const slideRectFn")
        self.assertNotIn("blank", cl)   # the camera layer ignores the blank


if __name__ == "__main__":
    unittest.main()
