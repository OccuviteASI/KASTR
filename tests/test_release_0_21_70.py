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


class CreateRoomSettings(unittest.TestCase):
    """0.21.70 (Kenton: "When creating a room, give it the same options of the room settings from an admin"): Create room has
    Lock the view and Group too (with New group for admins), applied right after the room registers."""
    def test_wired(self):
        p = open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8").read()
        body = p[p.index("  function roomMenuCreate(menu) {"):p.index("  function roomMenuPassword(menu, rec) {")]
        self.assertIn('viewRow.append(viewSw, document.createTextNode(" Lock the view', body)
        self.assertIn('grpSel.setAttribute("aria-label", "Room group");', body)
        self.assertIn('if (viewInp.checked) { const d = await rsPost({ slug: rec.slug, op: "viewlock", locked: true });', body)
        self.assertIn('if (gid) { const d = await rsPost({ slug: rec.slug, op: "group", group: gid });', body)
        self.assertIn("menu.append(row1, row2, keepRow, viewRow, grpRow, err, acts);", body)
        self.assertLess(body.index("rememberChannel(rec);"), body.index('op: "viewlock"'))   # after it registered (its roomKey)


class HoverCards(unittest.TestCase):
    """0.21.70 (Kenton: two pop-ups on hover; the right-click menu half covered by the hover card)."""
    def test_one_popup(self):
        p = open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8").read()
        self.assertNotIn("rb.title = roomTitle(rec.slug)", p)
        self.assertIn('rb.removeAttribute("title");', p)
        self.assertIn('rb.setAttribute("aria-label", roomTitle(rec.slug)', p)

    def test_press_hushes_the_card(self):
        p = open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8").read()
        self.assertIn('sbPeekHush = e.target.closest?.(".sbcard")?.dataset?.slug || ""; });', p)
        self.assertIn("if (sbPeekHush && card.dataset.slug === sbPeekHush) return;", p)
        self.assertIn("card.dataset.slug !== sbPeekHush) sbPeekOpen(card.dataset.slug); });", p)
        self.assertIn("if (slug === sbPeekHush) return;   // 0.21.70: pressed in the meantime", p)


if __name__ == "__main__":
    unittest.main()
