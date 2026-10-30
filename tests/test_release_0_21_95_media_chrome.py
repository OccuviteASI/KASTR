"""0.21.95 (Kenton 2026-10-30: "When sharing media, it never hides the control elements or the name ... It should only show them on
hover over the window itself, and fade out after."). Cause: a CLICKED Play / volume / seek kept focus inside the stage and
idleBusy() counted any focused button as "busy", so the idle chrome never came; the name also stayed up on :focus-within.
Now only keyboard focus holds the chrome, the media bar shows only while the pointer is on its own tile, and the name fades.
Lab (in-app browser, the page's own CSS + idle code): hover -> bar + name show; click Play, rest 5 s -> both hidden; the pointer
on another tile -> hidden."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MediaChrome(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.src = f.read()

    def test_clicked_focus_does_not_hold_the_chrome(self):
        i = self.src.index("const IDLE_MS = 3000")
        body = self.src[i:self.src.index("window.__idleChrome", i)]
        self.assertIn('document.addEventListener("pointerdown", () => { idleKey = false; }, true);', body)
        self.assertIn('document.addEventListener("keydown", () => { idleKey = true; }, true);', body)
        self.assertIn("|| (idleKey && document.activeElement", body)

    def test_media_bar_only_on_its_own_tile(self):
        self.assertIn('#stage .pane:not(:hover):not(:has(:focus-visible)):not(:has([data-scrub="1"])) > .mediabar', self.src)
        self.assertIn('#stage .pubpane:not(:hover):not(:has(:focus-visible)):not(:has([data-scrub="1"])) > .mediabar', self.src)

    def test_name_no_longer_held_by_a_click(self):
        self.assertNotIn("#stage .pane:focus-within .label .l", self.src)
        self.assertNotIn("#stage .pubpane:focus-within .bar .nm", self.src)
        self.assertIn("#stage .pane:has(:focus-visible) .label .l", self.src)
        self.assertIn("display .25s allow-discrete", self.src)


if __name__ == "__main__":
    unittest.main()
