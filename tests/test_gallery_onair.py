"""0.21.40: a chosen gallery stays; a room's play badge counts only pictures on the air.

Run: python -m unittest discover -s tests
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _page():
    with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


class Gallery(unittest.TestCase):
    def test_every_way_back_uses_one_reset(self):
        p = _page()
        self.assertIn('document.getElementById("viewGallery").addEventListener("click", () => { closeAllPops(); goGallery(); });', p)
        self.assertIn('stageBack.addEventListener("click", (e) => { e.stopPropagation(); goGallery(); });', p)
        self.assertIn('if (v === "unpin") { goGallery(); return; }', p)
        self.assertIn("if (gridMode) enterSpotlight(); else goGallery();", p)

    def test_reset_covers_open_cell_own_pane_fill_and_full_screen(self):
        p = _page()
        body = p[p.index("  function goGallery() {"):p.index("  window.__goGallery = goGallery;")]
        for part in ("gridOpenEnd(false)", "galleryChosen = true", "selfSpotEl = null", "focusMode = false",
                     "toggleFillWindow(null)", "document.exitFullscreen", "gridMode = true"):
            self.assertIn(part, body)

    def test_only_a_new_spotlight_takes_the_stage_back(self):
        p = _page()
        self.assertIn("if (galleryChosen && gridMode && !news) {", p)
        self.assertIn("if (!curIsContent && !(galleryChosen && gridMode)) {", p)
        # a pick on the stage ends the chosen gallery
        sel = p[p.index("  function select(name) {"):p.index("  function select(name) {") + 300]
        self.assertIn("galleryChosen = false;", sel)


class OnAir(unittest.TestCase):
    def test_box_cameras_need_proof_of_a_picture(self):
        p = _page()
        body = p[p.index("  function onAirCount() {"):p.index("  function pushOnAir()")]
        self.assertIn("pi?.flowingAt && nowS - pi.flowingAt < 15", body)
        self.assertIn("if (!flowing && !playing) continue;", body)
        self.assertIn("if (rtspSuspended) continue;", body)

    def test_viewers_trust_video_from_new_boxes(self):
        p = _page()
        self.assertIn('window.__state?.set?.("airv", 1)', p)
        self.assertIn("airv: v.airv === 1", p)
        self.assertTrue(re.search(r"if \(p\.state && \(p\.who\.airv \? p\.who\.video > 0", p))


if __name__ == "__main__":
    unittest.main()
