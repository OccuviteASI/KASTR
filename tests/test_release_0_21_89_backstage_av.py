# -*- coding: utf-8 -*-
"""v0.21.89 (Kenton: "I want 'Backstage' to have the ability to mute/unmute and to share/pause video for presenter.").

Decided (Kenton):
  1. Backstage people (only those the presenter made backstage, only while that presentation is live) mute / unmute the
     presenter's mic and pause / resume the presenter's video STRAIGHT AWAY; the presenter always sees who did it ("Unmuted by
     Ada", "Video paused by Ada") in the presenter view and as a toast; "Backstage can control my mic and camera" is ON by
     default for this presentation only, and off refuses (backstage's buttons grey out with the reason).
  2. Backstage only pauses / resumes a camera the presenter turned on ("<name>'s camera is off"); paused -> Content only.
  3. The mic goes through the page's REAL path (the toolbar's Mic button: micMuted + sendControl + renderMine) -- never the
     library's `muted`; unmuting never fights the microphone's own mute and reports an unavailable mic.
  4. Requests go through presCtl, are checked on the presenter's page (backstage + live presentation + switch on) and are
     idempotent; control ends with the presentation or the backstage role.
  5. Backstage sees the presenter's CURRENT mic / video state from the presenter's page (the record), within ~1 s.
Lab (headless, scratchpad v02189): see the release notes."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


PAGE = read("moq-watch-lite.html")
JS = read("assets/kastr-pres.js")


def block(src, start, end):
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


class ThePagesRealPath(unittest.TestCase):
    def setUp(self):
        self.av = block(PAGE, "  window.__presAV = {", "  // the chevrons open the Camera / Audio popovers")

    def test_mic_like_the_toolbar_button(self):
        mic = block(self.av, "    mic(mute) {", "    cam(pause) {")
        self.assertIn("const { src } = localCamSrc();", mic)
        self.assertIn("src.micMuted = !!mute;", mic)
        self.assertIn("sendControl(window.__publisher.peer, src.id, { micMuted: src.micMuted });", mic)
        self.assertIn("renderMine();", mic)
        self.assertNotIn(".muted =", self.av)   # never the library's muted

    def test_unmute_never_fights_the_hardware_mute_and_undeafens(self):
        mic = block(self.av, "    mic(mute) {", "    cam(pause) {")
        self.assertIn('hwMuteSeen.endsWith("|1")', mic)
        self.assertIn("the microphone is muted on the device itself", mic)
        self.assertIn("if (!mute && deafened) setDeafen(false);", mic)
        self.assertIn('return { ok: false, why: "no microphone is available" };', mic)

    def test_idempotent(self):
        self.assertIn("if (!!src.micMuted === !!mute) return { ok: true, noop: true };", self.av)
        self.assertIn("if (!!src.videoPaused === !!pause) return { ok: true, noop: true };", self.av)

    def test_camera_pause_is_the_camera_buttons_pause(self):
        cam = block(self.av, "    cam(pause) {", "  };")
        self.assertIn("src.videoPaused = !!pause;", cam)
        self.assertIn("sendControl(window.__publisher.peer, src.id, { videoPaused: src.videoPaused });", cam)


class ThePresentersPage(unittest.TestCase):
    def setUp(self):
        self.ap = block(JS, "  function applyModeAv(ctl, who) {", "  // backstage: the requests")

    def test_checked_on_the_presenter(self):
        ai = block(JS, "  function applyIntent(path, ctl) {", "  let rewrapT = null;")
        self.assertLess(ai.index("if (!b) return;"), ai.index("applyModeAv(ctl, who)"))   # backstage only
        self.assertIn('if (!["mute", "unmute", "pause", "resume"].includes(op))', self.ap)
        self.assertIn("if (!m.avOk) return answer(false,", self.ap)
        self.assertIn("turned off backstage control of their mic and camera", self.ap)
        mem = block(JS, "  window.__presMember = (path, v) => {", "  async function ensurePk()")
        self.assertIn("if (mine && next.ctl && next.ctl.id === mine.id) applyIntent(path, next.ctl);", mem)   # a live presentation only

    def test_notices_name_who(self):
        for t in ('"Muted by "', '"Unmuted by "', '"Video paused by " + name', '"Video resumed by " + name'):
            self.assertIn(t, self.ap)
        nt = block(JS, "  function avNotice(m, text, by) {", "  function applyModeAv(")
        self.assertIn('toast(text, 6000, "event");', nt)   # the main page too
        self.assertIn("if (!r.noop) avNotice(", self.ap)    # a no-op says nothing

    def test_backstage_cannot_start_a_camera_that_is_off(self):
        self.assertIn("if (!m.avBp) return answer(false, me + \"'s camera is off\");", self.ap)
        self.assertIn("m.avBp = true; m.avBpAt = Date.now();", self.ap)

    def test_switch_on_by_default_for_this_presentation(self):
        mi = block(JS, "  function modeInit(m) {", "  function modeFields() {")
        self.assertIn("m.avOk = true; m.avBp = false;", mi)
        self.assertIn("Backstage can control my mic and camera", JS)
        self.assertIn("avSwitch: (on) =>", JS)

    def test_state_published_for_backstage(self):
        mf = block(JS, "  function modeFields() {", "  function modeTick() {")
        self.assertIn("av: { m: s.mic, c: s.camSt, bp: !!m.avBp, ok: !!m.avOk,", mf)
        self.assertIn("ack: m.ack || null", mf)
        mt = block(JS, "  function modeTick() {", "  function modeEnd(m) {")
        self.assertIn("s.mic = av ? av.mic : \"none\";", mt)
        self.assertIn("setInterval(() => { try { modeTick(); }", JS)   # the presenter's own changes reach backstage within ~1 s

    def test_paused_camera_falls_back_to_content(self):
        mt = block(JS, "  function modeTick() {", "  function modeEnd(m) {")
        self.assertIn('const eff = live ? m.cm : "content";', mt)
        ui = block(JS, "  function modeUiPaint() {", "  const ago = ")
        self.assertIn('"Video paused by "', ui)


class BackstagesButtons(unittest.TestCase):
    def test_requests_through_presctl_only_to_a_presenter_that_has_them(self):
        sa = block(JS, "  function sendAvIntent(deckId, op) {", "  // ---- the presenter view: the mode picker")
        self.assertIn("if (!bk || !bk.rec.av ||", sa)
        self.assertIn('stateSet("presCtl", { id: deckId, seq: ctlSeq, bv: bk.rec.ver, to: bk.rec.idx, at: Date.now(), av: { op } });', sa)
        api = block(JS, "    av: (op) =>", "    avSwitch:")
        self.assertIn("if (mine) return false;", api)

    def test_buttons_show_the_presenters_state_and_grey_out(self):
        pr = block(JS, "  function paintAvRow(mv, who) {", "  // the preview: the same composition")
        self.assertIn('mic.className = "avmic"', pr)
        self.assertIn('cam.className = "avcam"', pr)
        self.assertIn('mic.disabled = off || av.m === "none"', pr)
        self.assertIn('cam.disabled = off || av.c === "off"', pr)
        self.assertIn("\"'s camera is off\"", pr)
        self.assertIn('"Not done: " + lastAck.why', pr)


if __name__ == "__main__":
    unittest.main()
