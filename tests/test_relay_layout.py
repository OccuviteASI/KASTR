"""The Relay page's cards: 0.21.52 dragged by their title and remembered; 0.21.56 (Kenton: "allow for collapsing individual
tiles on the relay server page. Also allow for resizing and snap to grid instead of highlighting the other tile edges";
chose: cards float up, width + height, 12 columns) -- a 12-column snap grid with float-up packing, a collapse chevron per
card, a resize grip, a dashed box where a dragged card lands. Rig: scratchpad v02156/pw_grid12.py."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RelayLayout(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "relay.html"), encoding="utf-8") as f:
            self.p = f.read()

    def test_snap_grid(self):
        self.assertIn("const COLS = 12, ROW = 8, GAP = 14, MINW = 3, MINROWS = 11, NARROW = 760;", self.p)
        self.assertIn("const y = Math.max(...sky.slice(x, x + w));", self.p)           # float up: as high as the cards above allow
        self.assertIn("for (let c = x; c < x + w; c++) sky[c] = y + rows;", self.p)
        self.assertNotIn("drop-before", self.p)                                          # no more edge highlighting
        self.assertIn('const ph = document.createElement("div"); ph.className = "gph";', self.p)

    def test_collapse_resize_and_remembered(self):
        self.assertIn('b.type = "button"; b.className = "pcol";', self.p)
        self.assertIn("#main.g12 > section.panel.collapsed > :not(h2) { display:none !important; }", self.p)
        self.assertIn('g.className = "rsz"; g.dataset.for = p.id;', self.p)
        self.assertIn('gr.addEventListener("dblclick", () => { S(p).h = 0;', self.p)    # back to fitting its contents
        self.assertIn('const KEY = "kastr.relay.grid", OLD_KEY = "kastr.relay.layout";', self.p)
        self.assertIn('id="layoutReset"', self.p)

    def test_drag_by_title(self):
        self.assertIn('h.addEventListener("pointerdown", (e) => {', self.p)
        self.assertIn('if (e.button !== 0 || e.target.closest("button, input, select, a")) return;', self.p)

    def test_every_card_has_an_id(self):
        for pid in ("serverPanel", "detailsPanel", "logPanel"):
            self.assertIn('id="%s"' % pid, self.p)

    def test_hidden_badges_stay_hidden(self):   # 0.21.56: the empty role badge showed on every non-standby page in 0.21.55
        self.assertIn(".sbbadge[hidden] { display:none !important; }", self.p)


if __name__ == "__main__":
    unittest.main()
