# -*- coding: utf-8 -*-
"""v0.21.91 (Kenton, 2026-10-27: "By default when presenting, everyone else should be muted and not able to unmute themselves unless
they are added as a presenter.").

Decided (Kenton):
  1. Only PRESENTERS talk while a presentation is live: the audience AND backstage are muted and cannot unmute; their Mic shows a
     lock and why ("Muted while <name> presents"); the microphone's own key cannot unmute either; becoming a presenter lifts it at
     once, being removed mutes again; when the presentation ends everyone's mic is as it was before it.
  2. "Audience muted" in the presenter (and co-presenter) view, ON when a presentation starts, any presenter turns it off / on; it
     is in the pres record, so late joiners obey.
  3. "Ask to speak": a raised hand (one small field in the asker's presCo), Let <name> talk / Dismiss on a presenter's page; let
     talk = may unmute (never forced) until Done, a presenter mutes them again, or the end.
  4. Enforced on BOTH sides: the sender's own page mutes through the real path (micMuted + sendControl + renderMine, never the
     library's `muted`); EVERY 0.21.91 page plays a person's mic that may not talk at gain 0 (the volume path, the warm floor).
     A person's mic = a person's camera stream in my room (<room>/<host>/<op>/camera(-n).hang, not a box)."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


PAGE = read("moq-watch-lite.html")
JS = read("assets/kastr-pres.js")
AUD = JS[JS.index("  // ---- 0.21.91: AUDIENCE MUTE ---"):JS.index("  window.__pres = {")]


def block(src, start, end):
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


class TheRecord(unittest.TestCase):
    def test_on_when_a_presentation_starts(self):
        self.assertIn("function audienceInit(m) { m.am = 1; m.ask = 1; m.lt = new Set(); m.hx = new Map(); }", AUD)   # + Ask to speak (on)
        sf = block(JS, "  async function startFromFile(file) {", "  function ensureSlide(i) {")
        self.assertLess(sf.index("audienceInit(mine);"), sf.index("publish();"))
        pub = block(JS, "  function publish() {", "  function goTo(")
        self.assertIn("...audFields(),", pub)   # in the record: late joiners obey
        self.assertIn("return m && m.lt ? { am: m.am ? 1 : 0, ask: m.ask === 0 ? 0 : 1, lt: [...m.lt], hx: [...m.hx].slice(-24) } : {};", AUD)

    def test_any_presenter_switches_it(self):
        self.assertIn('if (pp.op === "am") return setAm(!!pp.v, who) || true;', AUD)
        self.assertIn('if (v0.role === "copresenter") return sendPresOp(v0.id, { op: "am", v: v ? 1 : 0 });', AUD)
        self.assertIn("let audienceOp = () => false;", JS)
        po = block(JS, "  function presOp(pp, who) {", "  let audienceOp")
        self.assertIn("default: if (!audienceOp(pp, who))", po)   # presenter-only (applyOp checks isP before presOp)
        self.assertIn('lab.append(cb, document.createTextNode("Audience muted"));', AUD)

    def test_handover_keeps_it(self):
        self.assertIn("adoptExtra = (m, rec) => { m.am = rec.am === undefined ? 1 : Number(rec.am) ? 1 : 0;", AUD)


class WhoMayTalk(unittest.TestCase):
    def test_presenters_and_people_let_talk(self):
        self.assertIn("const mayTalk = (d, who) => !d.am || who === d.own || d.ps.includes(who) || d.lt.includes(who);", AUD)
        self.assertIn('return "Muted while " + d.cn + " presents";', AUD)
        tt = block(AUD, "  function talkTick() {", "  setInterval(() => { try { talkTick(); }")
        self.assertIn("for (const p of [d.own, ...d.ps, ...d.lt]) if (p) allowed.add(String(p).toLowerCase());", tt)

    def test_a_person_mic_only(self):
        self.assertIn("const PERSON_CAM = /^camera(-\\d+)?\\.hang$/;", AUD)
        si = block(AUD, "  function silent(path) {", "  function talkTick() {")
        self.assertIn("if (p.length !== 4 || !PERSON_CAM.test(p[3])) return false;", si)   # shares, media, RTSP, slide videos keep their sound
        self.assertIn("if (!c || p[0] !== c.channel) return false;", si)   # my room only
        self.assertIn("return !talk.allowed.has(key) && !talk.boxes.has(key);", si)
        tt = block(AUD, "  function talkTick() {", "  setInterval(() => { try { talkTick(); }")
        self.assertIn('/^(publisher|publisher-relay|relay)$/.test(p.mode)', tt)   # boxes keep their sound


class TheSendersOwnPage(unittest.TestCase):
    def test_mutes_through_the_real_path_and_remembers(self):
        tt = block(AUD, "  function talkTick() {", "  setInterval(() => { try { talkTick(); }")
        self.assertIn("if (talk.was === null) talk.was = micOn;", tt)
        self.assertIn("if (micOn) { try { AV.mic(true); } catch {}", tt)   # __presAV.mic: micMuted + sendControl + renderMine
        self.assertIn("if (was && !micOn) { try { AV?.mic(false); } catch {} }", tt)   # the end: as it was
        self.assertIn("if (!lk && talk.was !== null && ds.length && talk.unlockMic !== null && micOn !== talk.unlockMic) talk.was = null;", tt)   # they took the mic themselves while free
        self.assertNotIn(".muted =", AUD)

    def test_the_page_refuses_to_unmute(self):
        mic = block(PAGE, '  topMicBtn.addEventListener("click", () => {', '  topCamBtn.addEventListener("click"')
        self.assertLess(mic.index("window.__presTalk?.lock?.()"), mic.index("src.micMuted = !src.micMuted;"))
        self.assertIn("if (lk && (s0 ? !!s0.micMuted : !joinMicOn))", mic)   # muting stays possible
        dev = block(PAGE, "  function setMicFromDevice(muted, why) {", "  function hwMicName() {")
        self.assertLess(dev.index("window.__presTalk?.lock?.()"), dev.index("src.micMuted = !!muted;"))   # the microphone's own key
        ctl = block(PAGE, '        if ("micMuted" in m.set) {', '        if ("sharePaused" in m.set)')
        self.assertIn('if (!m.set.micMuted && a.kind === "camera") { try { if (window.__presTalk?.lock?.()) m.set.micMuted = true; } catch {} }', ctl)

    def test_the_mic_button_shows_a_lock_and_why(self):
        tc = block(PAGE, "  function paintTopCam() {", "  async function ensureLocalCamera(")
        self.assertIn('topMicBtn.classList.toggle("talklock", !!talkLock);', tc)
        self.assertIn('icon("lock")', tc)
        self.assertIn("if (talkLock) topMicBtn.title = talkLock", tc)


class EveryReceivingPage(unittest.TestCase):
    def test_gain_zero_through_the_volume_never_muted(self):
        dv = block(PAGE, "  function desiredVolume(name) {", "  window.__presTalkChanged")
        self.assertIn("try { if (window.__presTalk?.silent?.(name)) return isAudible(name) || warmAudio ? WARM_FLOOR : 0; } catch {}", dv)
        self.assertIn("window.__presTalkChanged = () => { try { applyVolumes(); paintTopCam(); } catch {} };", PAGE)
        self.assertIn("try { window.__presTalkChanged?.(); } catch {}", AUD)


class RaiseAHand(unittest.TestCase):
    def test_cheap_and_rate_limited(self):
        rh = block(AUD, "  function raiseHand(on) {", "  // the owner page: the switch")
        self.assertIn("if (now - talk.lastHand < 1500) return false;", rh)
        self.assertIn("handState = { id: d.id, at: now };", rh)
        self.assertIn("coExtra = () => (handState ? { hand: handState } : {});", AUD)

    def test_let_talk_dismiss_done(self):
        st = block(AUD, "  function setTalk(p, v, by) {", "  audienceOp = ")
        self.assertIn("if (v) { if (!handOf(p) || m.ask === 0) return false; m.lt.add(p); m.hx.delete(p); }", st)   # only a raised hand
        self.assertIn("else { m.lt.delete(p); const at = handOf(p); if (at) m.hx.set(p, at); }", st)
        pr = block(AUD, "  function audiencePrune() {", "  setInterval(() => { try { audiencePrune(); }")
        self.assertIn("for (const p of [...m.lt]) if (!handOf(p)) { m.lt.delete(p);", pr)   # Done = the hand lowered
        tt = block(AUD, "  function talkTick() {", "  setInterval(() => { try { talkTick(); }")
        self.assertIn("const dismissed = d && d.hx.some((h) => Array.isArray(h) && h[0] === me && Number(h[1]) === handState.at);", tt)
        sa = block(AUD, "  function setAm(v, by) {", "  function setTalk(")
        self.assertIn("if (nv) m.lt.clear();", sa)

    def test_the_pill_and_the_presenters_list(self):
        self.assertIn('const b = letMe ? "Done" : handState ? "Lower hand" : "Ask to speak";', AUD)
        self.assertIn('a.textContent = "Let " + String(h.name).split(/\\s+/)[0] + " talk";', AUD)
        self.assertIn('x.textContent = "Dismiss";', AUD)
        self.assertIn('x.textContent = "Mute again";', AUD)


if __name__ == "__main__":
    unittest.main()
