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
    # 0.21.91 (Kenton: "Backstage can control my mic and camera should be an option per backstage person"): the request is
    # answered on the TARGET presenter's own page (avApply) -- the owner's or an added presenter's -- and the one switch became
    # each presenter's own per-person allow list (self.al)
    def setUp(self):
        self.ap = block(JS, "  function avApply(who, op, seq) {", "  // 0.21.91: requests that reach a presenter who is not the owner")

    def test_checked_on_the_presenter(self):
        ai = block(JS, "  function applyIntent(path, ctl) {", "  let rewrapT = null;")
        self.assertLess(ai.index("if (!isB && !isP) return;"), ai.index("avApply(who, ctl.av.op, ctl.seq)"))   # backstage (or presenters) only
        self.assertIn("if (!ctl.av.to || ctl.av.to === myPerson()) avApply(", ai)   # a request for another presenter is theirs
        self.assertIn('if (!["mute", "unmute", "pause", "resume"].includes(op))', self.ap)
        self.assertIn("if (!deckBs(pd).includes(who)) return answer(false,", self.ap)   # backstage in this deck
        self.assertIn("if (!self.al.has(who)) return answer(false, me + \" hasn't allowed you to control their mic and camera\");", self.ap)
        self.assertIn('if (!pd) return answer(false, "the presentation is over");', self.ap)   # a live presentation only
        mem = block(JS, "  window.__presMember = (path, v) => {", "  async function ensurePk()")
        self.assertIn("if (next.ctl) ctlArrived(path, next.ctl);", mem)
        ca = block(JS, "  function ctlArrived(path, ctl) {", "  // backstage / co-presenters: the requests")
        self.assertIn("if (mine && ctl.id === mine.id) { applyIntent(path, ctl); return; }", ca)
        self.assertIn("o.av.to === me) avApply(who, o.av.op, o.seq);", ca)   # an added presenter answers what is addressed to them

    def test_notices_name_who(self):
        for t in ('"Muted by "', '"Unmuted by "', '"Video paused by " + name', '"Video resumed by " + name'):
            self.assertIn(t, self.ap)
        nt = block(JS, "  function avNotice(text, by) {", "  function avApply(")
        self.assertIn('presNote(text, 6000, "event");', nt)   # the presenter view's notice line, or a toast on the main page
        self.assertIn("if (!r.noop) avNotice(", self.ap)    # a no-op says nothing

    def test_backstage_cannot_start_a_camera_that_is_off(self):
        self.assertIn("if (!self.bp) return answer(false, me + \"'s camera is off\");", self.ap)
        self.assertIn("self.bp = true; self.bpAt = Date.now();", self.ap)

    def test_allowed_by_default_for_each_newly_added_backstage_person(self):
        st = block(JS, "  function selfTick() {", "  function modeInit(m) {")
        self.assertIn("for (const p of bs) if (!self.alSeen.has(p)) { self.alSeen.add(p); if (!preDenied(pd.id, p)) self.al.add(p); }", st)   # 0.21.92: unless said no in advance (a template)
        self.assertIn("for (const p of [...self.alSeen]) if (!bs.includes(p)) { self.alSeen.delete(p); self.al.delete(p); }", st)
        self.assertNotIn('createTextNode("Backstage can control my mic and camera")', JS)   # the one global switch is gone
        self.assertNotIn("avSwitch:", JS)
        self.assertIn('lab.append(switchOf(cb), document.createTextNode("Can control my mic and camera"));', JS)   # on each backstage row

    def test_state_published_for_backstage(self):
        mf = block(JS, "  function modeFields() {", "  function modeTick() {")
        self.assertIn("av: { m: o.mic, c: o.camSt, bp: !!self.bp, ok: self.al.size > 0,", mf)   # what an older backstage page reads
        self.assertIn("ack: self.ack || null", mf)
        cp = block(JS, "  function coPublish() {", "  let coExtra = ")
        self.assertIn("o.al = [...self.al];", cp)   # each presenter's own allow list, in its own presCo
        self.assertIn("o.av = { m: s.mic, c: s.camSt,", cp)
        self.assertIn("if (self.ack) o.ack = self.ack;", cp)
        st = block(JS, "  function selfTick() {", "  function modeInit(m) {")
        self.assertIn("s.mic = av ? av.mic : \"none\";", st)
        self.assertIn("setInterval(() => { try { modeTick(); }", JS)   # the presenter's own changes reach backstage within ~1 s

    def test_paused_camera_falls_back_to_content(self):
        mt = block(JS, "  function modeTick() {", "  let modeSigExtra = ")
        self.assertIn('s.eff = live ? m.cm : "content";', mt)
        ui = block(JS, "  function modeUiPaint() {", "  const ago = ")
        self.assertIn('"Video paused by "', ui)


class BackstagesButtons(unittest.TestCase):
    def test_requests_through_presctl_only_to_a_presenter_that_has_them(self):
        sa = block(JS, "  function sendAvIntent(deckId, op, to) {", "  // ---- the presenter view: the mode picker")
        self.assertIn('if (!bk || !["mute", "unmute", "pause", "resume"].includes(op)) return false;', sa)
        self.assertIn("if (!co && !rec.av) return false;", sa)   # an older presenter without mic / camera control
        self.assertIn("if (co) av.to = tgt;", sa)   # 0.21.91: the target presenter (an older owner reads {op} as its own)
        self.assertIn("const ctl = ctlSend({ id: deckId, bv: rec.ver, to: rec.idx, av });", sa)
        self.assertIn("const tgt = to || rec.cur || rec.own", sa)   # default: the presenter presenting now
        api = block(JS, "    av: (op, to) =>", "    allow: (who, on) =>")
        self.assertIn("b.keys && !b.pr", api)   # backstage only

    def test_buttons_show_the_presenters_state_and_grey_out(self):
        pr = block(JS, "  function paintAvRow(mv) {", "  // the preview: the same composition")
        self.assertIn('mic.className = "avmic"', pr)
        self.assertIn('cam.className = "avcam"', pr)
        self.assertIn('mic.disabled = off || !t.av || av.m === "none"', pr)
        self.assertIn('cam.disabled = off || !t.av || av.c === "off"', pr)
        self.assertIn("\"'s camera is off\"", pr)
        self.assertIn('"Not done: " + lastAck.why', pr)
        self.assertIn("offWhy = who + \" hasn't allowed you to control their mic and camera\"", pr)


if __name__ == "__main__":
    unittest.main()
