"""0.21.52: the Relay page's cards take only the height they need and can be dragged where you want them (Kenton)."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RelayLayout(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "relay.html"), encoding="utf-8") as f:
            self.p = f.read()

    def test_masonry_rows(self):
        self.assertIn("#main.masonry { grid-auto-rows:4px; row-gap:0; grid-auto-flow:row dense; }", self.p)
        self.assertIn('p.style.gridRowEnd = h ? "span " + Math.ceil((h + 14) / 4) : "";', self.p)
        self.assertIn("const ro = new ResizeObserver(", self.p)

    def test_drag_by_title_and_remembered(self):
        self.assertIn('h.addEventListener("pointerdown", (e) => {', self.p)
        self.assertIn("if (d.after) d.target.after(p); else d.target.before(p);", self.p)
        self.assertIn('const KEY = "kastr.relay.layout";', self.p)
        self.assertIn('id="layoutReset"', self.p)

    def test_every_card_has_an_id(self):
        for pid in ("serverPanel", "detailsPanel", "logPanel"):
            self.assertIn('id="%s"' % pid, self.p)


if __name__ == "__main__":
    unittest.main()
