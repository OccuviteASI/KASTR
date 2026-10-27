# -*- coding: utf-8 -*-
"""v0.21.91 (Kenton, 2026-10-27: "The Backstage selector should be reworked. The Backstage can control my mic and camera should
be an option per backstage person. I want to add an option to make other people presenters, and allow them to show their camera
instead of the main presenters camera while they are presenting their part of the slides.").

Decided (Kenton):
  1. The picker is TWO SECTIONS, Presenters (main first) and Backstage, each row with a ready dot and a remove x, an Add button
     opening a people picker (photo + name, searchable, only KASTRs that can do it); each backstage row carries the VIEWING
     presenter's own "Can control my mic and camera" (ON for a newly added person); never both roles; moving allowed; the
     round bubble row retired.
  2. Added presenters have the main presenter's powers (slides, notes, next, modes, Reporter backdrop, people, End). The deck
     goes on when the main presenter leaves: added presenters hold K + the store's write token; the owner role passes on.
  3. "Now presenting: <name>" / "Take over": that presenter's camera / cut-out is the one in the slide; their page publishes its
     cut-out only on its turn; a name tag on the viewers' tile; their own tile hidden meanwhile.
  4. Backstage mic / camera control is per presenter, per backstage person, checked on the TARGET presenter's page.
  5. Older KASTRs: only 0.21.91 pages can be presenters (presCo.cap), old viewers keep the slide + tiles, old backstage works."""
import os
import re
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


class TheRecord(unittest.TestCase):
    def test_presco_is_a_room_json_key(self):
        self.assertIn('case "presCo": if (value && typeof value === "object" && JSON.stringify(value).length < 8000) roomModel.presCo = value;', PAGE)
        mem = block(JS, "  window.__presMember = (path, v) => {", "  async function ensurePk()")
        self.assertIn('co: v.presCo && typeof v.presCo === "object" ? v.presCo : null', mem)

    def test_the_owner_publishes_presenters_with_wrapped_keys(self):
        pub = block(JS, "  function publish() {", "  function goTo(")
        self.assertIn("own: myPerson(), og: mine.og, cur: mine.cur, cn: nameOfPerson(mine.cur),", pub)
        self.assertIn('ps: mine.ps.map((x) => ({ p: x.p, n: x.name || nameOfPerson(x.p), w: x.w || "", t: x.t || "" })),', pub)
        self.assertNotIn("notes:", pub)   # still never a note in the public record
        self.assertNotIn("token:", pub)   # the write token travels wrapped only (ps[].t)
        rw = block(JS, "  async function rewrap() {", "  // 0.21.91: who is a presenter / backstage")
        self.assertIn("b.w = b64(await seal(wk, m.K));", rw)
        self.assertIn('b.t = pres ? b64(await seal(await hkdf(wk, "write"), enc.encode(m.token))) : "";', rw)   # presenters only
        self.assertIn("for (const x of m.ps) if (x.p !== me) await one(x.p, x, true);", rw)

    def test_capability_published_with_the_key(self):
        self.assertIn("const CAP = 2;", JS)
        ep = block(JS, "  async function ensurePk() {", "  // 0.21.91: one deck, one record")
        self.assertIn("coPublish();", ep)
        cp = block(JS, "  function coPublish() {", "  let coExtra = ")
        self.assertIn("const o = { cap: CAP };", cp)
        self.assertIn("const canCo = (pk) => { const co = coOf(pk); return !!(co && Number(co.cap) >= 2); };", JS)

    def test_one_record_per_deck_newest_owner_wins(self):
        self.assertIn("function recBetter(a, b) {", JS)
        dr = block(JS, "  function deckRecs() {", "  const coOf = ")
        self.assertIn("if (!cur || recBetter(rec, cur.rec)) out.set(rec.id, { rec, path });", dr)
        so = block(JS, "  function syncOverlays() {", "  async function paintOverlay(")
        self.assertIn("for (const { rec } of deckRecs().values()) if (rec.share) want.set(rec.share, rec);", so)


class Roles(unittest.TestCase):
    def setUp(self):
        self.sr = block(JS, "  function setRole(who, r, by) {", "  function setBackstage(")

    def test_never_both_and_the_owner_stays(self):
        self.assertIn('if (who === me && r !== "p") return false;', self.sr)
        self.assertIn("m.bs.delete(who);\n      m.ps.push(", self.sr)   # becoming a presenter leaves backstage
        self.assertIn("if (i >= 0) m.ps.splice(i, 1);\n      if (!m.bs.has(who))", self.sr)   # and the other way round
        self.assertIn("if (!canCo(who)) return false;", self.sr)   # only KASTRs that can co-present

    def test_the_one_presenting_now_falls_back_to_me(self):
        self.assertIn("if (m.cur !== me && !m.ps.some((x) => x.p === m.cur)) m.cur = me;", self.sr)
        mt = block(JS, "  function modeTick() {", "  let modeSigExtra = ")
        self.assertIn("else if (Date.now() - m.curGoneAt > 4000) {", mt)

    def test_copresenter_requests_are_presenter_only(self):
        ao = block(JS, "  function applyOp(ctl, who, isP) {", "  let rewrapT = null;")
        self.assertIn('if (ctl.pp && typeof ctl.pp === "object") { if (isP) presOp(ctl.pp, who); else T("drop"', ao)
        po = block(JS, "  function presOp(pp, who) {", "  let audienceOp")
        for op in ('case "role":', 'case "cur":', 'case "rbg":', 'case "end":', 'case "note":'):
            self.assertIn(op, po)
        self.assertIn("unseal(m.notesKey, unb64(pp.c))", po)   # a co-presenter's note travels sealed with the notes key

    def test_intents_carry_the_last_few(self):
        cs = block(JS, "  function ctlSend(o) {", "  function sendIntent(")
        self.assertIn("ctlQ.push(op); while (ctlQ.length > 6) ctlQ.shift();", cs)
        co = block(JS, "  function ctlOps(ctl) {", "  function applyIntent(")
        self.assertIn("return q.slice(-8).sort((a, b) => a.seq - b.seq);", co)
        ai = block(JS, "  function applyIntent(path, ctl) {", "  function applyOp(")
        self.assertIn("if (!(o.seq > last) || o.id !== mine.id) continue;", ai)   # each once, this deck only


class ThePickerAndSections(unittest.TestCase):
    def test_two_sections_replace_the_bubbles(self):
        self.assertIn('<div class="pplbox"><div class="psec psp"><div class="cap">Presenters', JS)
        self.assertIn('class="addp"', JS)
        self.assertIn('class="addb"', JS)
        self.assertNotIn("bsbox", JS)   # the round bubble row is gone
        self.assertNotIn("paintBackstage", JS)

    def test_rows(self):
        pp = block(JS, "    function paintPeople(v, M) {", "    // the people picker")
        self.assertIn('dot.className = "dot" + (!here ? "" : x.ready ? " ready" : " wait");', pp)
        self.assertIn('btn("takeover", "Take over"', pp)
        self.assertIn('btn("nowbtn", "Now presenting: " + first(x.n)', pp)
        self.assertIn('t.textContent = "Presenting now";', pp)
        self.assertIn('btn("mv", "→ Backstage"', pp)
        self.assertIn('btn("mv", "→ Presenter"', pp)
        self.assertIn('btn("x", "×"', pp)
        self.assertIn("if (M.edit && x.p !== M.own) {", pp)   # the page that runs the deck cannot be removed
        self.assertIn('lab.append(cb, document.createTextNode("Can control my mic and camera"));', pp)
        self.assertIn("cb.checked = self.al.has(x.p);", pp)   # MY setting for that person
        self.assertIn("if (M.mePres) {", pp)   # presenters only (backstage sees the sections read-only)

    def test_picker(self):
        pk = block(JS, "    function paintPicker() {", "  })();")
        self.assertIn("for (const p of (ctx()?.people || [])) {", pk)
        self.assertIn('if (q && !name.toLowerCase().includes(q)) continue;', pk)   # searchable
        self.assertIn("personAvatar(av, who, name);", pk)   # photo + name
        self.assertIn('if (pickKind === "p" && !canCo(who)) why = ', pk)
        self.assertIn("older than 0.21.91", pk)
        self.assertIn("b.disabled = !!why;", pk)
        pa = block(JS, "    function personAvatar(el, pk, name) {", "    function btn(")
        self.assertIn("K?.photo?.(el, name);", pa)   # the page's own photo painter (0.21.90: from the hub, never a broken image)
        self.assertIn("photo: (el, name) => { try { paintAvatar(el,", PAGE)

    def test_backstage_sees_read_only(self):
        pm = block(JS, "    function pplModel(v) {", "    function roleAct(")
        self.assertIn('edit: v.role === "copresenter", mePres: v.role === "copresenter"', pm)
        ra = block(JS, "    function roleAct(who, r) {", "    function curAct(")
        self.assertIn('if (v.role === "copresenter") return sendPresOp(v.id, { op: "role", p: who, r });', ra)


class HandOver(unittest.TestCase):
    def test_each_presenter_cuts_out_on_its_turn_only(self):
        st = block(JS, "  function selfTick() {", "  function modeInit(m) {")
        self.assertIn("s.turn = cur === myPerson();", st)
        self.assertIn("const wantCut = s.turn && live && cutMode(cm)", st)
        self.assertIn('s.cam = live ? ci.path : "";', st)   # the camera path is published whenever live (the switch is instant)

    def test_the_owner_copies_the_presenter_presenting_now(self):
        mt = block(JS, "  function modeTick() {", "  let modeSigExtra = ")
        self.assertIn("const src = m.cur === me ? self.ms : co && co.id === m.id ? co : {};", mt)
        self.assertIn('s.cam = live ? String(src.cam || "") : "";', mt)
        self.assertIn('s.cut = live && cutMode(m.cm) ? String(src.cut || "") : "";', mt)
        mem = block(JS, "  window.__presMember = (path, v) => {", "  async function ensurePk()")
        self.assertIn("if (mine && next.co && personOfPath(path) === mine.cur) { try { modeTick(); } catch {} }", mem)   # at once

    def test_name_tag_on_the_viewers_tile(self):
        cl = block(JS, "  function camLayer(o) {", "  const slideRectFn")
        self.assertIn('o.tagged = n && multiPres(rec) ? drawTag(g, L, rec.cn, W, H) : "";', cl)
        self.assertIn("const multiPres = (rec) => !!(rec && Array.isArray(rec.ps) && rec.ps.length > 1);", JS)

    def test_set_cur(self):
        sc = block(JS, "  function setCur(who, by) {", "  function presOp(")
        self.assertIn("if (!m || !m.ps.some((x) => x.p === who)) return false;", sc)
        self.assertIn("modeTick(); publish();", sc)


class Ownership(unittest.TestCase):
    def test_leaving_hands_over_when_a_copresenter_can_run_it(self):
        lm = block(JS, "  function leaveMine(why) {", "  window.addEventListener(\"pagehide\"")
        self.assertIn("const keep = coReady(mine);", lm)
        self.assertIn("endMine(why, keep);", lm)
        self.assertIn('window.addEventListener("pagehide", () => { if (mine) leaveMine("pagehide"); });', JS)
        em = block(JS, "  function endMine(why, keep) {", "  // 0.21.91: a co-presenter who can run the deck on")
        self.assertLess(em.index("if (!keep) {"), em.index("/end?token="))   # a hand-over never deletes the deck
        self.assertIn("endMark = { id: m.id, at: Date.now() };", em)   # an END says so (presCo.end): nobody takes it over

    def test_the_next_present_presenter_takes_over(self):
        ow = block(JS, "  function ownership() {", "  async function adopt(bk) {")
        self.assertIn("if (!released && inPresence(rec.own)) continue;", ow)   # a room.json gap alone never moves the deck
        self.assertIn("if (now - (bk.seenAt || 0) < (released ? 300 : HANDOVER_MS) + rank * 2000) continue;", ow)
        self.assertIn("if (relMark && Date.now() - relMark.at < 60000) o.rel = relMark.id;", JS)   # a deliberate hand-over says so
        self.assertIn("recBetter(rec, { og: mine.og, own: me })", ow)   # a returning old owner steps down
        self.assertIn('endMine("a newer owner", true);', ow)
        ad = block(JS, "  async function adopt(bk) {", "  let adoptExtra = ")
        self.assertIn('"/notes.bin?rt="', ad)   # the store still holds it? (an End removed it)
        self.assertIn("if (r.status === 404 || r.status === 403) { bk.ended = true;", ad)
        self.assertIn('"/live?token=" + encodeURIComponent(bk.wt)', ad)   # the write token works before anything is announced
        self.assertIn("og: (Number(rec.og) || 1) + 1,", ad)
        self.assertIn("m.lastSeq.set(who,", ad)   # requests already made are not applied again
        self.assertIn("startShare();\n    publish();\n    rewrap();", ad)

    def test_handed_over_deck_reads_its_slides_from_the_store(self):
        sf = block(JS, "  async function stillFor(deckId, i) {", "  function publish() {")
        self.assertIn("if (mine && deckId === mine.id && mine.adopted) {", sf)
        self.assertIn("bitmapFromCipher(baseFor({ base: m.base }), deckId, i, m.keys[i], m.rt)", sf)
        self.assertIn("function vidList(m, i) { return (((m.src && m.src.videos) || [])[i] || [])", JS)   # no videos after a hand-over

    def test_orphaned_deck_waits_then_goes(self):
        sb = block(JS, "  async function syncBackstage() {", "  function endSeen(id, path) {")
        self.assertIn("if (recs.has(id) || bk.ended || (mine && mine.id === id) || !bk.K || Date.now() - (bk.seenAt || 0) > ORPHAN_MS)", sb)
        self.assertIn("bk.orphan = true;", sb)
        es = block(JS, "  function endSeen(id, path) {", "  // 0.21.91: my requests")
        self.assertIn("if (who !== rec.own && !(rec.ps || []).some((x) => x.p === who)) return;", es)   # only its presenters say it ended


class MicCameraPerPresenter(unittest.TestCase):
    def test_target_presenter_checks(self):
        ap = block(JS, "  function avApply(who, op, seq) {", "  // 0.21.91: requests that reach a presenter who is not the owner")
        self.assertLess(ap.index("deckBs(pd).includes(who)"), ap.index("AV.mic("))
        self.assertLess(ap.index("self.al.has(who)"), ap.index("AV.mic("))
        self.assertIn("hasn't allowed you to control their mic and camera", ap)

    def test_backstage_picks_whose(self):
        pr = block(JS, "  function paintAvRow(mv) {", "  let avExtra = ")
        self.assertIn('if (!to) to = (ts.find((t) => t.p === mv.cur) || ts[0] || {}).p || "";', pr)   # the one presenting now by default
        self.assertIn('lab.textContent = "Control:";', pr)
        self.assertIn('b.textContent = x.name + (x.p === mv.cur ? " · now" : "");', pr)
        at = block(JS, "  function avTargets(mv) {", "  function paintAvRow(")
        self.assertIn("co.al.includes(me)", at)   # what THAT presenter allows me
        self.assertIn("const allowed = old ? !!(rec.av && rec.av.ok)", at)   # an older owner: its one switch


class OlderKastrs(unittest.TestCase):
    def test_older_pages_keep_working(self):
        pub = block(JS, "  function publish() {", "  function goTo(")
        self.assertIn('bs: [...mine.bs.entries()].map(([p, b]) => ({ p, n: b.name || "", w: b.w || "" })),', pub)   # an older backstage page reads bs as before
        self.assertIn("...modeFields(),", pub)   # cam / cut of the presenter presenting now: an older viewer draws it too
        cs = block(JS, "  function ctlSend(o) {", "  function sendIntent(")
        self.assertIn("Object.assign({}, op, { q:", cs)   # the newest at the top level, as older owners read it
        sa = block(JS, "  function sendAvIntent(deckId, op, to) {", "  // ---- the presenter view")
        self.assertIn("if (co) av.to = tgt;   // an older owner reads {op} as \"mine\"", sa)

    def test_line_endings_kept(self):
        with open(os.path.join(HERE, "assets", "kastr-pres.js"), "rb") as f:
            self.assertNotIn(b"\r\n", f.read())
        with open(os.path.join(HERE, "moq-watch-lite.html"), "rb") as f:
            raw = f.read()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))


if __name__ == "__main__":
    unittest.main()
