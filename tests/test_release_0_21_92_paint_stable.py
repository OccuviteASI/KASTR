# -*- coding: utf-8 -*-
"""v0.21.92 THE LIVE SLIDE NEVER SHRINKS. Kenton (0.21.91 field use): "When I added a user as the presenter, when they went back
to the room the view of the slides kept shrinking every second or two." Two causes, both fixed:
  1. an added presenter who went to another room took the deck over FROM THAT ROOM (its record had vanished from their view) and
     on the way back ENDED it in the store -- the presenter view and the stage then had no slides; a deck now belongs to its room
     (awayFrom) and is forgotten, never adopted, from another room;
  2. the live slide's size came from a box that could follow the slide (floored each paint): the box is now fixed by the grid
     (grid-template-rows: minmax(0, 1fr)), the slide is placed in it (absolute) and curFit sizes it from the box alone.
The browser check runs curFit 20 times in the real presenter-view CSS and markup at laptop, desktop and phone sizes, panels open,
long notes; it is skipped where no Chromium + Playwright is installed (the string checks always run)."""
import io
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def _read(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


JS = _read(os.path.join("assets", "kastr-pres.js"))


def _chrome():
    for p in (os.environ.get("KASTR_TEST_CHROME") or "", os.path.join(HERE, "dist", "windows", "browser", "chrome.exe")):
        if p and os.path.isfile(p):
            return p
    return None


class Strings(unittest.TestCase):
    def test_box_fixed_by_the_grid(self):
        self.assertIn("grid-template-rows: minmax(0, 1fr); gap:4px; padding:10px 12px; }", JS)
        self.assertIn("#presView .curwrap { flex:1 1 0; min-height:0; min-width:0; position:relative; overflow:hidden; }", JS)
        self.assertIn("#presView .curwrap > canvas.curcv { position:absolute; left:0; top:0; }", JS)

    def test_size_from_the_box_alone(self):
        self.assertIn("function curFit(wrap, cv, ar, narrow) {", JS)
        self.assertIn('const w = curFit($(".curwrap"), $(".curcv"), ar, narrow);', JS)
        self.assertNotIn("Math.min(r.width, r.height * ar)), h = w / ar;", JS)   # the old self-measuring paint

    def test_a_deck_belongs_to_its_room(self):
        self.assertIn('const awayFrom = (bk) => { const c = ctx(); return !!(c && c.channel && bk && bk.path && c.channel !== roomOfPath(bk.path)); };', JS)
        self.assertIn("> ORPHAN_MS || awayFrom(bk)) { backstage.delete(id);", JS)
        self.assertIn("!bk.wt || !bk.rec || awayFrom(bk)) continue;", JS)
        self.assertIn("if (mine || !c || !c.joined || awayFrom(bk)) return;", JS)
        self.assertIn("if (mine || backstage.get(rec.id) !== bk || awayFrom(bk)) return;", JS)


@unittest.skipUnless(_chrome(), "no Chromium for the layout check")
class PaintTwentyTimes(unittest.TestCase):
    def test_stable(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            self.skipTest("no Playwright")
        css = re.search(r"const CSS = `(.*?)`;", JS, re.S).group(1)
        markup = re.search(r"root\.innerHTML = `(.*?)`;", JS, re.S).group(1)
        fit = re.search(r"(  function curFit\(wrap, cv, ar, narrow\) \{.*?\n  \}\n)", JS, re.S).group(1)
        page = ("<!doctype html><html><head><style>" + css + "</style></head><body><div id='presView' class='show'>" + markup
                + "</div><script>" + fit + "</script></body></html>")
        run = """([col, ar]) => {
          const root = document.getElementById('presView');
          root.style.setProperty('--lcol', col + 'fr'); root.style.setProperty('--rcol', (1 - col) + 'fr');
          for (const d of root.querySelectorAll('details.pnl')) d.open = true;
          root.querySelector('.notes').textContent = 'A long note line that wraps. '.repeat(300);
          root.querySelector('.n1').style.width = '100%';
          const narrow = matchMedia('(max-width: 760px)').matches;
          const wrap = root.querySelector('.curwrap'), cv = root.querySelector('.curcv'), out = [];
          for (let i = 0; i < 20; i++) { curFit(wrap, cv, ar, narrow); const r = cv.getBoundingClientRect(), b = wrap.getBoundingClientRect();
            out.push([Math.round(r.width), Math.round(r.height), r.left >= b.left - 0.5 && r.right <= b.right + 0.5 && (narrow || r.bottom <= b.bottom + 0.5)]); }
          return out; }"""
        with sync_playwright() as pw:
            br = pw.chromium.launch(executable_path=_chrome(), headless=True)
            try:
                for (w, h) in ((1366, 768), (1280, 720), (1025, 579), (1920, 1080), (700, 900)):
                    pg = br.new_page(viewport={"width": w, "height": h})
                    pg.set_content(page)
                    for col in (0.4, 0.6, 0.78):
                        for ar in (16 / 9, 4 / 3):
                            out = pg.evaluate(run, [col, ar])
                            sizes = {(a, b) for a, b, _in in out}
                            self.assertEqual(len(sizes), 1, "%dx%d col %.2f: the live slide changed size: %r" % (w, h, col, sorted(sizes)))
                            self.assertTrue(all(x[2] for x in out), "%dx%d col %.2f: the slide is outside its box" % (w, h, col))
                            self.assertGreater(out[0][0], 150, "%dx%d col %.2f: the slide is too small" % (w, h, col))
                    pg.close()
            finally:
                br.close()


if __name__ == "__main__":
    unittest.main()
