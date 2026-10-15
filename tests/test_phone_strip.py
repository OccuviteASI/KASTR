# -*- coding: utf-8 -*-
"""0.21.59 (Kenton, iPhone: "I don't have the ability to see the side rail to pick anything other than the spotlighted
items"; chose live thumbnails below): an upright phone in speaker view keeps a rail -- a swipeable row of live thumbnails
under the stage. Rig: scratchpad v02159/pw_phonestrip.py (390x844 touch viewport: the stage on top, three thumbnails in
a row starting at the left, a tap puts one on the stage, sideways keeps the old full stage)."""
import io, os, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PhoneStrip(unittest.TestCase):
    def setUp(self):
        with io.open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.p = f.read()

    def test_an_upright_phone_keeps_a_rail(self):
        self.assertIn("const phoneStrip = !gridMode && isPhone() && !focusMode && !stageFullscreen() && window.innerHeight > window.innerWidth;", self.p)
        self.assertIn("const railOff = focusMode || (phoneTall() && !phoneStrip) || stageFullscreen();", self.p)   # 0.21.72: sideways keeps the rail

    def test_thumbnails_go_in_row_two(self):
        self.assertIn('el.style.display = ""; el.style.order = ""; el.style.gridRow = "2"; el.style.gridColumn = String(1 + stripIdx++);', self.p)
        self.assertIn('stageEl.style.gridTemplateRows = mainH + "px " + thumbH + "px";', self.p)

    def test_the_row_scrolls_under_a_sticky_stage_and_starts_at_the_left(self):
        self.assertIn("#stage.phonestrip { overflow-x:auto;", self.p)
        self.assertIn("#stage.phonestrip .mainstage { position:sticky; left:0;", self.p)
        self.assertNotIn("scroll-snap-type:x", self.p)   # re-snapping opened the row scrolled to its end
        self.assertIn("stageEl.scrollLeft = 0;   // a new stage starts the row at its beginning", self.p)


if __name__ == "__main__":
    unittest.main()
