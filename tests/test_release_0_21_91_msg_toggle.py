"""0.21.91 (Kenton, Messages settings: "this should be a toggle and not a checkbox"): desktop notifications use the house
switch; the heading no longer reads "Change my My room code"."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class NotificationsToggle(unittest.TestCase):
    def test_switch_markup(self):
        s = read("assets/kastr-msg.js")
        self.assertIn('<label class="mchk"><span class="switch sm"><input type="checkbox" class="mnotif"><i></i></span>'
                      '<span>Desktop notifications while KASTR is minimised</span></label>', s)
        self.assertIn("<h4>Change My room code</h4>", s)
        self.assertNotIn("Change my My room code", s)

    def test_row_layout(self):
        s = read("moq-watch-lite.html")
        self.assertIn(".mchk { display:flex; flex-direction:row; gap:10px; align-items:center;", s)
        self.assertIn(".mchk .switch { flex:none; }", s)


if __name__ == "__main__":
    unittest.main()
