# -*- coding: utf-8 -*-
"""0.21.54 (Kenton: "Give an option to collapse the top bar with the ASI logo, version, etc. and then an option to expand when
collapsed"): the masthead's chevron hides it, a tab at the top centre brings it back, remembered per machine.
Rig: scratchpad v02154/pw_mast.py (Relay page, app shell, room page)."""
import io, os, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class Masthead(unittest.TestCase):
    def test_wiring(self):
        js = read(os.path.join("assets", "asi-brand.js"))
        self.assertIn('const MAST_KEY = "kastr.masthead.collapsed";', js)
        self.assertIn("header.append(mark, product, nav, relay, fold);", js)
        self.assertIn("document.body.appendChild(tab);", js)
        self.assertIn('fold.setAttribute("aria-label", "Hide the top bar");', js)
        self.assertIn('tab.setAttribute("aria-label", "Show the top bar");', js)
        self.assertIn('window.dispatchEvent(new Event("resize"))', js)   # stages re-fit to the taller window

    def test_styles(self):
        css = read(os.path.join("assets", "asi-brand.css"))
        self.assertIn("body.asi-hdr-off .asi-header { display: none !important; }", css)
        self.assertIn("body.asi-hdr-off .asi-hdrtab { display: grid; }", css)
        self.assertIn("body.fillwin .asi-hdrtab, body.asi-embed .asi-hdrtab { display: none !important; }", css)


if __name__ == "__main__":
    unittest.main()
