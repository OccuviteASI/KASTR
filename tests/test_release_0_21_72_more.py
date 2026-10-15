"""v0.21.72, more of Kenton's 2026-10-15 asks:
- "On the lobby page I don't need to be searching for broadcasts" -- the empty-stage line is hidden in the Lobby;
- "On the cameras set the default to mirror" (he chose: only my own view) -- the self view is mirrored on screen, nothing sent changes;
- iPhone landscape "should be more like the desktop app ... video on the left and the rail on the right".

Run: python -m unittest discover -s tests
"""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page():
    with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


class Lobby(unittest.TestCase):
    def test_no_searching_line(self):
        self.assertIn("stageEmpty.hidden = watching > 0 || inLobby();", page())


class SelfMirror(unittest.TestCase):
    def test_on_by_default_display_only(self):
        p = page()
        self.assertIn('const selfMirrorOn = () => { try { return localStorage.getItem("kastr.selfmirror") !== "0"; } catch { return true; } };', p)
        self.assertIn('document.body.classList.toggle("selfmirror", selfMirrorOn());', p)
        self.assertIn("body.selfmirror #stage .pubpane.camkind moq-publish canvas, body.selfmirror #stage .pubpane.camkind moq-publish video,", p)
        self.assertIn("body.selfmirror #camPrev, body.selfmirror #joinPrevVideo { transform:scaleX(-1); }", p)
        self.assertIn('<span>Mirror my own view<small>Only you see it mirrored</small></span>', p)
        self.assertIn('<span>Mirror for everyone<small>Flips the picture you send</small></span>', p)
        self.assertIn("mirror: !!camFx.mirror", p)   # what is SENT is still the separate, off-by-default switch


class Landscape(unittest.TestCase):
    def test_desktop_layout_sideways(self):
        p = page()
        self.assertIn("const phoneLand = () => isPhone() && window.innerWidth > window.innerHeight;", p)
        self.assertIn("const railOff = focusMode || (phoneTall() && !phoneStrip) || stageFullscreen();", p)
        self.assertIn("if (phoneTall()) best = 1;", p)
        self.assertIn("if (phoneTall()) mk = 1;", p)
        self.assertIn("const railWNow = () => (phoneLand() ? Math.min(railW, Math.max(140, Math.round((stageWrap.clientWidth || 800) * 0.28))) : railW);", p)
        self.assertIn("(railWNow() < 240 && !phoneLand())", p)
        self.assertIn("#stage.spot #railPager.show { display:flex !important; }", p)


if __name__ == "__main__":
    unittest.main()
