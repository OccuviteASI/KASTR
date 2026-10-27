"""0.21.91 (Kenton: "In the sharing page ... I can't click on the buttons behind the alert. I need all of the buttons to be
available no matter what in that page."): a camera row's long status pushed its buttons off the row. The badge now shrinks,
the full status has its own line, and the row's buttons wrap instead of leaving the row."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page():
    with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


class CamRowButtonsStayReachable(unittest.TestCase):
    def test_row_wraps_and_badge_shrinks(self):
        s = page()
        self.assertIn(".pubui .camrow .top { flex-wrap:wrap; row-gap:6px; }", s)
        self.assertIn(".pubui .camrow .top .badge { flex:0 1 auto; min-width:0; max-width:100%; overflow:hidden; "
                      "text-overflow:ellipsis; white-space:nowrap; }", s)
        self.assertIn(".pubui .camrow .stfull[hidden] { display:none; }", s)
        self.assertIn(".pubui .camrow .top .lbl { flex:1 1 90px; min-width:60px; }", s)

    def test_warn_badge_is_not_the_notice_box(self):
        # .pubui .warn (the amber notice box) also matched "badge warn"; the badge resets its box styles
        s = page()
        self.assertIn(".pubui .badge.warn, #pubPanes .badge.warn { padding:2px 7px; border:0; border-radius:3px; margin:0; "
                      "font-size:10px; line-height:normal; }", s)

    def test_badge_word_and_full_line(self):
        s = page()
        self.assertIn("function camBadgeShort(t)", s)
        self.assertIn('split(" \\u2014 ")[0].split(" \\u00b7 ")[0]', s)
        self.assertIn("b.textContent = short;", s)
        self.assertIn('sf.textContent = full !== short ? full : ""; sf.hidden = full === short;', s)

    def test_badge_word_logic(self):
        def short(t):   # mirrors camBadgeShort
            x = str(t or "").split(" — ")[0].split(" · ")[0].strip()
            return x or str(t or "")
        self.assertEqual(short("offline — removed from grid (monitor attempt 3); retrying"), "offline")
        self.assertEqual(short("in grid · asleep (nobody watching)"), "in grid")
        self.assertEqual(short("relay refused — retrying"), "relay refused")
        self.assertEqual(short("ON AIR"), "ON AIR")
        self.assertEqual(short(""), "")


if __name__ == "__main__":
    unittest.main()
