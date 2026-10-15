"""v0.21.67 (Kenton 2026-10-14): "We need a way to show which room I'm in and it needs to be different than how it shows
what rooms I'm pulling feeds from." My room = tinted card, solid accent bubble, "You're here" tag; a watched room = no fill,
dashed outline + dashed ring, an eye on the bubble, "Watching" tag.

Run: python -m unittest discover -s tests
"""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RoomMarks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            cls.p = f.read()

    def test_my_room(self):
        p = self.p
        self.assertIn(".sbcard.cur { border-color:var(--asi-blue); background:color-mix(in srgb, var(--asi-blue) 16%, var(--surface)); }", p)
        self.assertIn(".sbcard.cur .rb { border-color:var(--asi-blue); background:var(--asi-blue); color:#fff;", p)
        self.assertIn('.sbcard.cur .sbtag.here { display:inline-block;', p)
        self.assertIn(r'here.className = "sbtag here"; here.textContent = "You\u2019re here";', p)

    def test_watched_room(self):
        p = self.p
        self.assertIn(".sbcard.watching { border-color:var(--asi-blue-dim); border-style:dashed; }", p)
        self.assertIn(".sbcard.watching .rb { box-shadow:none; outline:1.5px dashed var(--asi-blue);", p)
        self.assertIn(".sbcard.watching .rb .wb { display:inline-flex; }", p)
        self.assertIn('wtag.className = "sbtag wtag"; wtag.textContent = "Watching";', p)
        self.assertIn('wb.className = "wb"; wb.innerHTML = icon("eye");', p)

    def test_collapsed_rail_lets_the_bubble_say_it(self):
        self.assertIn("body.sb-collapsed .sbcard.cur, body.sb-collapsed .sbcard.watching { border-color:transparent; background:transparent; }", self.p)


if __name__ == "__main__":
    unittest.main()
