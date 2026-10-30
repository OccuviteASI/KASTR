"""0.21.96 (Kenton 2026-10-30: "There are several spots where in an entry field I can't click and drag, it closes the tab when I
do that."). Selecting text in a field and letting go outside it made the browser send a click to the nearest parent of both (the
page, a dialog's backdrop), which every "click outside closes it" handler read as a click outside. One window-level capture guard
swallows such a click before any closer sees it; plain clicks, label clicks and keyboard clicks pass.
Lab: Share panel + a dialog, drag-select from a field to outside -> both stay open; a real outside click still closes."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DragSelectIsNoClick(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            src = f.read()
        i = src.index('document.addEventListener("click", () => closeAllPops());')
        self.g = src[i:i + 1600]

    def test_guard_runs_first_on_the_window(self):
        self.assertIn('window.addEventListener("pointerdown", (e) => { downAt = { t: e.target, x: e.clientX, y: e.clientY }; }, true);', self.g)
        self.assertIn("e.stopImmediatePropagation(); e.preventDefault();\n  }, true);", self.g.replace("\r\n", "\n"))

    def test_only_a_press_that_ended_elsewhere(self):
        # same element, keyboard clicks (detail 0) and label -> input clicks (target not a parent of the press) pass
        self.assertIn("if (!d || !e.detail || e.target === d.t || !e.target?.contains?.(d.t)) return;", self.g)
        # a tiny wobble off an icon still clicks its button; from a field any distance is a selection
        self.assertIn('Math.hypot(e.clientX - d.x, e.clientY - d.y) < 10 && !d.t.closest?.("input, textarea, select', self.g)


if __name__ == "__main__":
    unittest.main()
