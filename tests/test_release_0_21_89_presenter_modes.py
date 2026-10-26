# -*- coding: utf-8 -*-
"""v0.21.89 (Kenton: "I would like to add the option to present a power point and also share my video, with options to switch
between the different presenter modes. (content only, standout, side-by-side, and reporter)").

Decided (Kenton): the presenter AND their backstage people switch (backstage through presCtl, accepted only from the people the
presenter made backstage); everyone sees the same mode; presentations only for now (the layout is plain geometry, ready for
shares later); a deck starts in Standout when the camera is on, else Content only; camera off / paused -> Content only until it
is back, said in the presenter view ("Camera off -- showing the slide only").

Covered here (the page / module source, like the other release tests):
  * kastr-pres.js: the four modes, the record fields (cm / cme / cam / cut / nocut / cwhy) the presenter alone writes, the
    default, the camera fallback, backstage's request through presCtl (and never to an older presenter), a viewer refused, the
    layout (pure geometry, exported for the rig), the slide placed by the mode, the slide's video moved with the slide, the
    camera layer (the cut-out unpacked in WebGL, else the camera in a box), the picker + live preview in the presenter view
  * the page: the presenter's camera tile not shown a second time (but still decoded), the cut-out published as a .cut (never
    a tile anywhere, older KASTRs included) and subscribed by its own hidden <moq-watch>, the effects matte reused, the
    recorder drawing a presentation tile as it is seen
Lab (headless, scratchpad v02189): see the release notes."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def raw(name):
    with open(os.path.join(HERE, name), "rb") as f:
        return f.read()


PAGE = read("moq-watch-lite.html")
JS = read("assets/kastr-pres.js")


def block(src, start, end):
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


class LineEndings(unittest.TestCase):
    def test_line_endings_kept(self):
        b = raw("moq-watch-lite.html")
        self.assertEqual(b.count(b"\n"), b.count(b"\r\n"), "moq-watch-lite.html stays CRLF")
        self.assertNotIn(b"\r\n", raw("assets/kastr-pres.js"), "kastr-pres.js stays LF")


class ModesInTheRecord(unittest.TestCase):
    def test_four_modes(self):
        self.assertIn('const MODES = ["content", "standout", "sbs", "reporter"];', JS)
        for name in ("Content only", "Standout", "Side-by-side", "Reporter"):
            self.assertIn(name, JS)

    def test_record_fields_written_by_the_presenter_only(self):
        pub = block(JS, "  function publish() {", "  function goTo(")
        self.assertIn("...modeFields(),", pub)
        mf = block(JS, "  function modeFields() {", "  function modeTick() {")
        for k in ("cm: m.cm", "cme: s.eff", "cam: s.cam", "cut: s.cut", "nocut: s.nocut", "cwhy: s.why"):
            self.assertIn(k, mf)
        self.assertIn("if (!m || !m.ms) return {};", mf)   # a viewer / backstage page never writes them

    def test_older_presenter_means_content_only(self):
        self.assertIn('const modeOf = (rec) => (rec && modeOk(rec.cme) ? rec.cme : "content");', JS)

    def test_default_standout_when_the_camera_is_on(self):
        mi = block(JS, "  function modeInit(m) {", "  function modeFields() {")
        self.assertIn('m.cm = ci && ci.live ? "standout" : "content";', mi)
        self.assertIn("modeInit(mine);", block(JS, "  async function startFromFile(file) {", "  function ensureSlide(i) {"))

    def test_camera_off_falls_back_and_comes_back(self):
        mt = block(JS, "  function modeTick() {", "  function modeEnd(m) {")
        self.assertIn('const eff = live ? m.cm : "content";', mt)   # the chosen mode is kept; the room shows the slide alone
        self.assertIn('s.cam = live ? ci.path : "";', mt)
        self.assertIn('s.why = live ? "" : ', mt)
        ui = block(JS, "  function modeUiPaint() {", "  // the preview: the same composition")
        self.assertIn("Camera off", ui)
        self.assertIn("— showing the slide only", ui)

    def test_cut_out_only_for_standout_and_reporter_with_the_camera_on(self):
        self.assertIn('const cutMode = (m) => m === "standout" || m === "reporter";', JS)
        mt = block(JS, "  function modeTick() {", "  function modeEnd(m) {")
        self.assertIn("const wantCut = live && cutMode(eff) && !!C && ci.canCut !== false;", mt)
        self.assertIn("C.start()", mt)
        self.assertIn("C.stop()", mt)
        self.assertIn('s.cut = cs && cs.ready ? cs.path : "";', mt)   # announced to the room only once it has a picture
        self.assertIn("modeEnd(m);", block(JS, "  function endMine(why) {", "  window.addEventListener(\"pagehide\""))

    def test_no_segmenter_falls_back_to_a_box_and_says_so(self):
        mt = block(JS, "  function modeTick() {", "  function modeEnd(m) {")
        self.assertIn("s.nocut = ci && ci.canCut === false", mt)
        ui = block(JS, "  function modeUiPaint() {", "  // the preview: the same composition")
        self.assertIn("the room sees it in a box", ui)
        cs = block(JS, "  function camSourceFor(rec, mode) {", "  const camLabel")
        self.assertIn('kind: "box"', cs)   # no cut-out picture (yet): the ordinary camera in the same place


class BackstageAndViewers(unittest.TestCase):
    def test_backstage_asks_through_presctl(self):
        sm = block(JS, "  function sendModeIntent(deckId, cm) {", "  // ---- the presenter view: the mode picker")
        self.assertIn('stateSet("presCtl", { id: deckId, seq: ctlSeq, bv: bk.rec.ver, to: bk.rec.idx, at: Date.now(), cm });', sm)
        self.assertIn("!bk.rec.cm", sm)   # an older presenter (no modes) is never asked

    def test_presenter_applies_only_its_backstage(self):
        ai = block(JS, "  function applyIntent(path, ctl) {", "  let rewrapT = null;")
        bs = ai.index("if (!b) return;   // only the backstage people the presenter picked")
        seq = ai.index("if (!(ctl.seq > last)) return;")
        cm = ai.index("applyModeAv(ctl, who)")
        self.assertLess(bs, cm)
        self.assertLess(seq, cm)
        self.assertLess(cm, ai.index("applyVidOp(ctl.vid, who)"))
        ap = block(JS, "  function applyModeAv(ctl, who) {", "  // backstage: the requests")
        self.assertIn("if (!modeOk(ctl.cm))", ap)

    def test_viewer_cannot_switch(self):
        api = block(JS, "    mode: (cm) => {", "    modes: () => modeState(),")
        self.assertIn("if (mine) return setMode(cm, myPerson());", api)
        self.assertIn("return bk ? sendModeIntent(bk.rec.id, cm) : false;", api)   # no deck key -> not backstage -> false

    def test_same_mode_for_everyone(self):
        # no per-viewer override: every tile reads the presenter's record
        self.assertNotIn("kastr.pres.mode", JS)
        self.assertIn("const rec = o.rec, mode = modeOf(rec);", JS)


class Drawing(unittest.TestCase):
    def test_layout_is_pure_and_exported(self):
        lay = block(JS, "  function presLayout(mode, W, H, ar, camAr, cut) {", "  function drawBackdrop(")
        self.assertNotIn("document", lay)
        self.assertNotIn("window", lay)
        for m in ('mode === "standout"', 'mode === "sbs"', 'mode === "reporter"'):
            self.assertIn(m, lay)
        self.assertIn("L.stacked = true;", lay)          # a tall tile stacks side-by-side
        self.assertIn("st.w * 0.58", lay)                 # Reporter's slide ~58 % over the shoulder
        self.assertIn("layout: presLayout,", JS)

    def test_content_only_draws_exactly_as_before(self):
        dl = block(JS, "  function drawLaid(cv, bmp, blank, mode, ar, label) {", "  function drawBoxCam(")
        self.assertIn('if (mode === "content") return drawContain(cv, bmp, blank, label || "");', dl)
        po = block(JS, "  async function paintOverlay(path, o) {", "  // ---- the presenter view")
        self.assertIn("drawLaid(o.cv, bmp, rec.blank, modeOf(rec), rec.ar, \"\");", po)

    def test_slide_video_moves_with_the_slide(self):
        dv = block(JS, "  function drawVids(cv, ar, items, rectFn) {", "  // a picture that stops")
        self.assertIn("const R = rectFn ? rectFn(W, H) : null;", dv)
        self.assertIn("drawVids(o.vcv, rec.ar || 16 / 9, items, slideRectFn(rec));", JS)
        self.assertIn("const slideRectFn = (rec) => (W, H) => presLayout(modeOf(rec), W, H, rec.ar, 16 / 9, true).slide;", JS)

    def test_camera_layer_per_tile(self):
        so = block(JS, "  function syncOverlays() {", "  async function paintOverlay(")
        self.assertIn('ccv.className = "prescam";', so)
        self.assertIn('+ "/" + modeOf(rec);', so)   # a new mode repaints the still
        self.assertIn("presCamSync();", so)
        vf = block(JS, "  function vidFrame() {", "  // ---- the loop")
        self.assertIn("if (camLayer(o)) more = true;", vf)
        self.assertIn("if (modeUiFrame()) more = true;", vf)
        self.assertIn(".pane canvas.prescam {", JS)

    def test_cut_out_unpacked_in_webgl(self):
        up = block(JS, "  function makeUnpacker() {", "  let unp = null;")
        self.assertIn('getContext("webgl2"', up)
        self.assertIn("texture(F, vec2(x + 0.5, y))", up)   # alpha = the right half's grey
        self.assertIn("o = vec4(min(c, vec3(a)), a);", up)  # premultiplied: the colour was sent over black
        uc = block(JS, "  function unpackCut(f) {", "  // the presenter's picture as this page has it")
        self.assertIn("if (unp.last !== f)", uc)          # one unpack per frame for every tile

    def test_unchanged_frame_not_redrawn(self):
        cl = block(JS, "  function camLayer(o) {", "  const slideRectFn")
        self.assertIn("if (!resized && fk === o.camFk) return true;", cl)

    def test_person_tile_hidden_only_where_the_tile_draws_it(self):
        ps = block(JS, "  function presCamSync() {", "  // ---- the presenter: the chosen mode")
        self.assertIn("for (const o of overlays.values())", ps)
        self.assertIn("window.__presCamHide?.(hide)", ps)
        self.assertIn("window.__presCutWant?.(cuts)", ps)

    def test_picker_and_preview_in_the_presenter_view(self):
        self.assertIn("modeUiBuild(root);", block(JS, "    function build() {", "    function setFs(v)"))
        self.assertIn("modeUiPaint();   // 0.21.89", JS)
        ub = block(JS, "  function modeUiBuild(root) {", "  // what the presenter view's deck shows")
        self.assertIn('data-mode="${k}"', ub)
        self.assertIn("What the room sees", ub)
        self.assertIn('side.insertBefore(box, side.firstChild);', ub)
        mv = block(JS, "  function modeView() {", "  function modeUiPaint() {")
        self.assertIn('role: "backstage"', mv)   # backstage gets the same picker


class PageSeams(unittest.TestCase):
    def test_person_tile_hidden_but_decoded(self):
        self.assertIn("const presCamHide = new Set();", PAGE)
        self.assertIn("cgWarm.has = (n) => has0(n) || presCamHide.has(n);", PAGE)   # cgWarm: keeps decoding
        hc = block(PAGE, "  const hiddenChild = (name) =>", "  // 0.21.66 (Kenton: an RTMP grid")
        self.assertIn("(presCamHide.has(name) && (gridMode || name !== selectedName) && !stageMosaicNames.has(name))", hc)
        self.assertIn("window.__presCamFrame = (path) =>", PAGE)
        self.assertIn("window.__presCamHide = (paths) =>", PAGE)

    def test_cut_out_is_not_a_hang(self):
        cut = block(PAGE, "  // ---- 0.21.89 (Kenton: \"present a power point", "  async function presAttach(slot) {")
        self.assertIn('const leaf = "presentation_cutout_" + Date.now().toString(36) + ".cut";', cut)
        self.assertNotIn("addSource(", cut)                     # a bare <moq-publish>: no Share row, no arrival
        self.assertIn('document.createElement("moq-publish")', cut)
        self.assertIn('pub.setAttribute("announce", "always");', cut)
        # every KASTR (this one and older ones) skips an announce that is not a .hang -- never a tile
        self.assertIn('if (!path.endsWith(".hang")) continue; // skip internal .stats etc.', PAGE)
        m = re.search(r"const PRES_CUT_RE = /(.+)/;", PAGE)
        rx = re.compile(m.group(1).replace("\\/", "/"))
        self.assertTrue(rx.match("room/host-1a2b/alice/presentation_cutout_mvpnm89o.cut"))
        self.assertFalse(rx.match("room/host-1a2b/alice/camera.hang"))
        self.assertFalse(re.search(r"/presentation_video(?:_[a-z0-9]+)?(?:-\d+)?\.hang$", "room/h/a/presentation_cutout_x.cut"))

    def test_cut_out_packs_colour_and_mask(self):
        cut = block(PAGE, "  // ---- 0.21.89 (Kenton: \"present a power point", "  async function presAttach(slot) {")
        self.assertIn("const PCUT = { W: 640, FPS: 24, KBPS: 900, SEG_MS: 66 };", cut)
        self.assertIn("put(px, 0);", cut)                       # left: colour over black
        self.assertIn("px.drawImage(c.white, w, 0);", cut)      # right: the mask as grey
        self.assertIn('c.gl.render(vid, maskCv, w, h, "person")', cut)
        self.assertIn('ensureSegmenter("balanced")', cut)
        self.assertIn("mainSubjectMask(c.conf, mw, mh)", cut)
        self.assertIn("if (b && b.haveMask && b.maskCv && b.video && b.video.videoWidth && !rig)", cut)   # the effects matte reused
        self.assertIn("b.maskCv = maskCv;   // 0.21.89", PAGE)
        self.assertIn('codec: avc1Ok ? "avc1" : "vp09"', cut)
        self.assertIn("pushCaptureFrame(c.track)", cut)         # a hidden window keeps sending

    def test_cut_out_subscribed_by_its_own_watch(self):
        cw = block(PAGE, "  window.__presCutWant = (paths) =>", "  window.__presCutFrame = (path) =>")
        self.assertIn('document.createElement("moq-watch")', cw)
        self.assertIn('w.setAttribute("visible", "always");', cw)
        self.assertNotIn(".muted", cw)
        cf = block(PAGE, "  window.__presCutFrame = (path) =>", "  window.__presCutStats")
        self.assertIn("now - c.at > 3000", cf)                   # a stalled picture asks afresh

    def test_recorder_follows_the_mode(self):
        rec = block(PAGE, "  function recStart() {", "  function recStop() {")
        self.assertIn('el.querySelectorAll("canvas.presov, canvas.presvid, canvas.prescam")', rec)

    def test_cam_info_seam(self):
        cut = block(PAGE, "  window.__presCut = {", "  async function presAttach(slot) {")
        for k in ("camInfo()", "start: pcutStart", "stop: pcutStop", "state()", "person()", "camVideo()"):
            self.assertIn(k, cut)
        self.assertIn("live: !!slot && !paused", cut)


if __name__ == "__main__":
    unittest.main()
