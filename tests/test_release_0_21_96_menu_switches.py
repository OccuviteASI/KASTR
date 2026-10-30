"""0.21.96 (Kenton 2026-10-28, standing: "the check box should be a toggle. This should always be this way for all check boxes
unless told differently"). The share / grid / pointer menus still drew on/off rows as tick glyphs; the locked-shares work gave the
menu builder a switch (it.sw), and every such row now wears it."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MenuRowsAreSwitches(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.src = f.read()

    def test_no_tick_glyphs_left(self):
        self.assertNotIn("\u2611", self.src)
        self.assertNotIn("☑", self.src)

    def test_rows_wear_switches(self):
        for row in ('sw: !!(ls.want), label: "In the stream library"', 'sw: !!(gridLock), label: "Lock cells',
                    'sw: !!(gridNames), label: "Show names on grid cells"', 'sw: !!(window.__gridFeeds?.lock?.()), label: "Lock cells',
                    'sw: !!(on), label: "Full quality in the grid: "', 'sw: !!(ptOwnPref()), label: "Show my clicks"'):
            self.assertIn(row, self.src)
        self.assertIn('if (typeof it.sw === "boolean") {', self.src)

    def test_pointer_bar(self):
        self.assertIn('all.append(ptSw(m.everyone), "Let everyone point");', self.src)
        self.assertIn("#kPtBar .tog .misw { pointer-events:none;", self.src)


if __name__ == "__main__":
    unittest.main()
