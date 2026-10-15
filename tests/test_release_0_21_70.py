"""v0.21.70 (Kenton 2026-10-14: "The group settings button is in a weird spot and doesn't make sense."): the rooms rail's
group button shared the class of the grid's pop-up menu (.gmenu: position absolute, top-right) and floated over the first room
card. It has its own class now, sits on the group's row (shown on hover), right-click on the row opens the same menu, and
admins get it as well as the relay operator.

Run: python -m unittest discover -s tests
"""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class GroupButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            cls.p = f.read()

    def test_own_class_on_the_row(self):
        p = self.p
        self.assertNotIn("sbgroup .gmenu", p)
        self.assertIn('mb.className = "sbgmenu"; mb.innerHTML = icon("more");', p)
        self.assertIn(".sbgroup:hover .sbgmenu, .sbgroup .sbgmenu:focus-visible { visibility:visible; }", p)
        self.assertIn('if (e.target.closest(".sbgmenu")) { openGroupMenu(mb, h.__g); return; }', p)

    def test_right_click_and_admins(self):
        p = self.p
        self.assertIn('openGroupMenu(pointAnchor(e.clientX, e.clientY), h.__g); });   // 0.21.70', p)
        self.assertIn('h.querySelector(".sbgmenu").hidden = !canManageGroups();', p)


if __name__ == "__main__":
    unittest.main()
