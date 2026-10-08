import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class DragGhost(unittest.TestCase):
    """0.21.25 (Kenton): what is dragged floats under the pointer; a click-drag never selects text."""

    def setUp(self):
        self.page = _read("moq-watch-lite.html")

    def test_no_selection_on_chrome(self):
        p = self.page
        self.assertIn("  body { -webkit-user-select:none; user-select:none; }", p)
        self.assertIn("#chatLog, #chatLog *", p)   # chat stays selectable
        self.assertIn("img, svg, canvas, video { -webkit-user-drag:none; }", p)

    def test_every_drag_shows_the_ghost(self):
        p = self.page
        self.assertIn("dragGhost.start(tiles.get(drag.name)?.pane, e);   // 0.21.25", p)
        self.assertIn("dragGhost.start(sbDrag.card, e);   // 0.21.25", p)
        self.assertIn("window.__dragGhost?.startCanvas(g.canvas, cell, e, box);", p)
        self.assertIn("dragGhost.end();   // 0.21.25", p)

    def test_ghost_never_counts_as_a_tile(self):
        p = self.page
        self.assertIn('stageEl.querySelectorAll(".pane:not(.dgclone), .pubpane:not(.dgclone)")', p)
        self.assertIn('stageEl.querySelectorAll(".mainstage:not(.dgclone)")', p)
        self.assertIn(".dragghost { position:fixed; left:0; top:0; z-index:10000; pointer-events:none; opacity:.62;", p)


if __name__ == "__main__":
    unittest.main()
