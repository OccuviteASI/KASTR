# -*- coding: utf-8 -*-
"""0.21.54 (Kenton: "There still isn't a way to get back to the spotlight view without adding/removing a spotlight"):
View > Speaker / G go back to the room's spotlight, and View > Spotlight shows while the room has one. Rig:
scratchpad v02154/pw_spotback.py (gallery -> Spotlight, another tile -> Speaker, gallery -> G, all back on the spotlight)."""
import io, os, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SpotBack(unittest.TestCase):
    def setUp(self):
        with io.open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.page = f.read()

    def test_menu_item(self):
        self.assertIn('id="viewSpot" type="button" title="Back to what the room spotlighted" hidden>', self.page)
        self.assertIn('b.hidden = !spotSetNow().length; b.classList.toggle("on", roomSpotOnStage());', self.page)

    def test_speaker_and_g_go_back_to_the_rooms_spotlight(self):
        i = self.page.index("  function enterSpotlight() {")
        body = self.page[i:i + 300]
        self.assertLess(body.index("if (pinsShow()) return;"), body.index("if (spotBack()) return;"))   # my pins still win
        self.assertIn('if (e.key === "g" || e.key === "G") { if (gridMode) enterSpotlight();', self.page)

    def test_spot_back_reapplies_once(self):
        i = self.page.index("  function spotBack() {")
        body = self.page[i:i + 900]
        self.assertIn("spotDone = null; galleryChosen = false; manualPick = false;", body)   # the one-shot guard re-armed
        self.assertIn("spotApplyWinner();", body)
        self.assertNotIn("focusMode = false", body)   # Focus on content keeps its switch


if __name__ == "__main__":
    unittest.main()
