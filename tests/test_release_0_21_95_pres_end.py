"""0.21.95 (Kenton, field, v0.21.94, My room, a deck with slide videos: "I started a presentation and after I closed the presentation
it still shows that I'm presenting." -- his own share tile, black, "You're presenting · Presentation · Ow…"; a few minutes later
the page's added / slots held only his camera, so the tile had nothing behind it).

Root causes found and fixed:
  1. End during "Preparing…" (deckId is null while the deck opens, so deck() is null): endNow only closed the view and
     startFromFile went on behind it -- the deck started anyway with its share tile up. End now cancels the start (prepTok,
     checked after every await) and ends a deck that came up meanwhile; the store forgets a deck it already made.
  2. stopSlot: a teardown step that threw skipped pane.remove() (and removeSource's added.splice) -- the tile stayed. The pane
     and the slot now always go.
  3. presAttach waited by id, not by slot: a rebuilt slot with the same id let the old one carry on. Now by identity.
Safety net: window.__presShare.sweep -- when a deck ends and every ~3 s, kastr-pres.js removes every presentation share /
slide video its running deck does not use (none when no deck runs here) and any of my tiles (.pubpane) no live slot owns.
The presenter view closes when its deck is gone. Lab proof: C:\\kastr-scratch\\v02195\\prestile (results-*.json, run_*.log).
Static checks only: no network, no processes.
"""
import os

import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8", newline="") as f:
        return f.read()


def between(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i + len(start))]


class EndDuringPrep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = read("assets/kastr-pres.js")
        cls.start = between(cls.js, "async function startFromFile(file) {", "\n  // 0.21.92 (Kenton: a template's presentation")

    def test_prep_token(self):
        self.assertIn("let prepTok = null;", self.js)
        self.assertIn("const prepGone = (tok) => !!tok && (tok.cancel || prepTok !== tok);", self.js)
        self.assertIn("const tok = prepTok = { cancel: false, at: Date.now() };", self.start)
        self.assertIn("finally { if (prepTok === tok) prepTok = null; }", self.start)

    def test_no_second_start_while_preparing(self):
        self.assertIn("if (prepTok && !prepTok.cancel) {", self.start)

    def test_every_await_checks_cancel(self):
        body = between(self.start, "async function startPrepared(", "\n    renderRest();")
        # each await in the start is followed by a cancel check before anything is shown or published
        for at in ('"open"', '"new"', '"keys"', '"slide"', '"notes"'):
            self.assertIn('T("start-cancelled", { at: ' + at + ' })', body)
        self.assertLess(body.index('at: "notes"'), body.index("startShare();"))
        self.assertLess(body.index('at: "keys"'), body.index("mine = {"))

    def test_cancel_forgets_the_store_deck(self):
        body = between(self.start, "const forget = () => {", "};")
        self.assertIn('"/api/pres/" + deck.id + "/end?token=" + deck.token', body)
        self.assertIn("src.close()", body)

    def test_end_now_cancels_and_ends(self):
        body = between(self.js, "    function endNow() {", "\n    function tick() {")
        self.assertIn("if (prepTok) prepTok.cancel = true;", body)
        self.assertIn('if (mine && (!v || (v.role === "presenter" && v.id === mine.id))) { endMine("ended"); close(); return; }', body)
        self.assertLess(body.index("prepTok.cancel = true"), body.index('endMine("ended")'))


class SafetyNet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = read("assets/kastr-pres.js")
        cls.page = read("moq-watch-lite.html")

    def test_end_mine_closes_view_and_sweeps(self):
        body = between(self.js, "  function endMine(why, keep) {", "\n  function presSweep() {")
        self.assertIn("if (!keep && view.isOpen() && !view.deck()) view.close();", body)
        self.assertIn("presSweep();", body)

    def test_pres_sweep_keeps_the_running_deck(self):
        body = between(self.js, "  function presSweep() {", "\n  // 0.21.91: a co-presenter who can run the deck on")
        self.assertIn("if (!mine && prepTok && !prepTok.cancel) return sw({ panesOnly: true });", body)
        self.assertIn("keep.push(mine.share.id)", body)
        self.assertIn("for (const e of mine.vids.values()) if (e.shareId != null) keep.push(e.shareId);", body)
        self.assertIn("sw({ keep, vids: !mine })", body)   # a video still starting under a running deck is left alone

    def test_periodic_sweep(self):
        self.assertIn("let sweepTick = 0;", self.js)
        self.assertIn("if (++sweepTick % 4 === 0) presSweep();", self.js)

    def test_page_sweep(self):
        body = between(self.page, "    sweep(o) {", "\n  };")
        self.assertIn("const keep = new Set((o && o.keep) || []);", body)
        self.assertIn("if (a.presCanvas || (a.presVideo && !(o && o.vids === false))) {", body)
        self.assertIn("if (!(o && o.panesOnly)) {", body)
        self.assertIn("const owned = new Set([...slots.values()].map((s2) => s2.pane));", body)
        self.assertIn('document.querySelectorAll(".pubpane:not(.dgclone)")) if (!owned.has(p)) { p.remove(); n++; }', body)
        self.assertNotIn('a.kind === "camera"', body)   # only presentation sources are ever touched

    def test_page_crlf_kept(self):
        self.assertNotIn("\n", self.page.replace("\r\n", ""))


class SlotTeardown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = read("moq-watch-lite.html")

    def test_pane_always_goes(self):
        body = between(self.page, "  function stopSlot(id) {", "\n  function stopSlotParts(slot) {")
        self.assertIn('try { stopSlotParts(slot); } catch (e) { console.warn("KASTR stopSlot", e); }', body)
        self.assertLess(body.index("stopSlotParts(slot)"), body.index("slot.pane.remove()"))
        self.assertLess(body.index("slot.pane.remove()"), body.index("slots.delete(id);"))
        parts = between(self.page, "  function stopSlotParts(slot) {", "\n  function bindSlotDevice(slot) {")
        self.assertNotIn("slot.pane.remove()", parts)
        self.assertNotIn("slots.delete", parts)
        self.assertIn("stopFileMedia(slot);", parts)

    def test_pres_attach_by_identity(self):
        body = between(self.page, "  async function presAttach(slot) {", "\n  $(\"srcPresBtn\")")
        self.assertIn("slots.get(slot.entry.id) === slot; i++)", body)
        self.assertIn("if (slots.get(slot.entry.id) !== slot || !slot.pane.isConnected) { try { track.stop(); } catch {} return; }", body)
        self.assertNotIn("slots.has(slot.entry.id)", body)


if __name__ == "__main__":
    unittest.main()
