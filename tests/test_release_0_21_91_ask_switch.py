# -*- coding: utf-8 -*-
"""v0.21.91 (Kenton, 2026-10-27: "Yes, add a switch to turn off ask to speak.").

An "Ask to speak" switch under "Audience muted" in the presenter view's Mic & audience panel, ON by default, for presenters and
co-presenters. OFF: the audience pill offers no Ask to speak, raised hands go down, new raises are refused -- on the asker's page
and on every page that reads the record (a raised hand from an older or a modified page is not listed, nobody can be let talk).
It rides the pres record next to `am` as `ask` (absent = on, for older owners); a meeting template's audience.ask sets it
(startFromFile's second argument) and window.__pres.audSnap() reports it."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(HERE, "assets", "kastr-pres.js"), encoding="utf-8") as f:
    JS = f.read()
AUD = JS[JS.index("  // ---- 0.21.91: AUDIENCE MUTE ---"):JS.index("  window.__pres = {")]


def block(src, start, end):
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


class TheRecord(unittest.TestCase):
    def test_on_by_default_next_to_am(self):
        self.assertIn("function audienceInit(m) { m.am = 1; m.ask = 1;", AUD)
        self.assertIn("{ am: m.am ? 1 : 0, ask: m.ask === 0 ? 0 : 1, lt:", AUD)
        self.assertIn("ask: rec.ask === undefined || Number(rec.ask) ? 1 : 0,", AUD)   # an older owner: on
        self.assertIn("m.ask = rec.ask === undefined || Number(rec.ask) ? 1 : 0;", AUD)   # a hand-over keeps it

    def test_presenters_and_copresenters_switch_it(self):
        self.assertIn('if (pp.op === "ask") return setAsk(!!pp.v, who) || true;', AUD)
        aa = block(AUD, "  function askAct(v) {", "  function panelAvInfo(")
        self.assertIn('if (v0.role === "copresenter") return sendPresOp(v0.id, { op: "ask", v: v ? 1 : 0 });', aa)
        self.assertIn('al.append(ac, document.createTextNode("Ask to speak"));', AUD)
        ax = block(AUD, "  avExtra = (row) => {", "  // the audience's pill")
        self.assertLess(ax.index('"Audience muted"'), ax.index('"Ask to speak"'))   # under Audience muted


class OffMeansNoHands(unittest.TestCase):
    def test_the_askers_page(self):
        rh = block(AUD, "  function raiseHand(on) {", "  // the owner page: the switch")
        self.assertIn("if (!d || handState || !d.ask) return false;", rh)   # refused
        tt = block(AUD, "  function talkTick() {", "  setInterval(() => { try { talkTick(); }")
        self.assertIn("if (!d || !d.am || !d.ask || dismissed)", tt)   # a raised hand goes down
        self.assertIn("bb.hidden = !letMe && !handState && !!dk && !dk.ask;", AUD)   # no Ask to speak in the pill

    def test_every_page_that_reads_the_record(self):
        hs = block(AUD, "  function hands(deckId) {", "  function panelAvInfo(")
        self.assertIn("if (!d || !d.ask) return out;", hs)
        st = block(AUD, "  function setTalk(p, v, by) {", "  audienceOp = ")
        self.assertIn("if (!handOf(p) || m.ask === 0) return false;", st)
        sa = block(AUD, "  function setAsk(v, by) {", "  function askAct(")
        self.assertIn("for (const p of [...m.lt]) { m.lt.delete(p); }", sa)   # nobody stays let talk


class Templates(unittest.TestCase):
    def test_audience_ask_from_a_template_and_back(self):
        sf = block(JS, "  async function startFromFile(file) {", "  function ensureSlide(i) {")
        self.assertIn("askPreset(mine, arguments[1]);", sf)
        self.assertLess(sf.index("audienceInit(mine);"), sf.index("askPreset(mine, arguments[1]);"))
        self.assertIn("(o.audience && (o.audience.ask === 0 || o.audience.ask === false))", AUD)
        self.assertIn("audSnap: () => (mine && mine.lt ? { am: mine.am ? 1 : 0, ask: mine.ask === 0 ? 0 : 1 } : null),", JS)


if __name__ == "__main__":
    unittest.main()
