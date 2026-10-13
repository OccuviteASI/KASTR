# -*- coding: utf-8 -*-
"""0.21.60 (Kenton: "an update to the help section with a guide for basic use") + the phone's collapsed top bar as a strip
of its own (Kenton, iPhone web app: the expand button overlapped the People button and sat under the status bar).
Rigs: scratchpad v02160/pw_help.py, v02160/pw_strip.py."""
import io, os, re, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class HelpGuide(unittest.TestCase):
    def setUp(self):
        with io.open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.p = f.read()

    def test_sections(self):
        i = self.p.index('<div id="helpPop" class="popcard" hidden>')
        body = self.p[i:self.p.index("</div>\n</div>", i) if "</div>\n</div>" in self.p[i:] else i + 20000]
        got = re.findall(r"<summary>([^<]+)</summary>", body)
        self.assertEqual(got, ["Getting started", "The screen", "Watching", "Talking", "Sharing", "Rooms", "Phones and tablets",
                               "Keyboard shortcuts", "Something not working?"])
        self.assertNotIn("My streams", body)                       # the 0.7 text it replaces
        self.assertIn("Add to Home Screen", body)
        self.assertIn("<details open><summary>Getting started</summary>", body)

    def test_menu_and_scroll(self):
        self.assertIn("Help &amp; guide</button>", self.p)
        self.assertIn("#helpPop .body { max-height:min(72vh, 680px); overflow:auto; }", self.p)

    def test_drawer_clears_the_status_bar(self):
        self.assertIn("padding:max(10px, env(safe-area-inset-top)) 10px", self.p)


if __name__ == "__main__":
    unittest.main()
