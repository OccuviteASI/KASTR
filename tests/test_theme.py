# -*- coding: utf-8 -*-
"""0.21.61 (Kenton: "Let people choose light/dark mode or the system default"; chose Dark as the default and a dark video
stage in light mode). Rigs: scratchpad v02161/pw_light.py (screenshots), v02161/pw_system.py (System follows the
device; a choice on one page reaches the other pages live)."""
import io, os, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class Theme(unittest.TestCase):
    def test_every_page_sets_the_theme_before_it_paints(self):
        for f in ("moq-watch-lite.html", "relay.html", "index.html", "app.html", "watch.html", "stats.html"):
            p = read(f)
            i = p.index('<meta charset="utf-8">')
            self.assertIn('localStorage.getItem("kastr.theme")||"dark"', p[i:i + 600], f)   # Dark unless chosen

    def test_light_palette_and_the_dark_stage(self):
        css = read(os.path.join("assets", "asi-brand.css"))
        self.assertIn(':root[data-theme="light"] {', css)
        self.assertIn(':root[data-theme="light"] .asi-dark, :root[data-theme="light"] .asi-header', css)
        self.assertIn('<div id="stagewrap" class="asi-dark">', read("moq-watch-lite.html"))

    def test_the_setting_and_its_switch(self):
        js = read(os.path.join("assets", "asi-brand.js"))
        self.assertIn('const THEME_KEY = "kastr.theme";', js)
        self.assertIn('window.addEventListener("storage", (e) => { if (e.key === THEME_KEY) themeApply(); });', js)
        self.assertIn('if (themeGet() === "system") themeApply();', js)
        page = read("moq-watch-lite.html")
        self.assertIn('<div class="opt themerow" role="radiogroup" aria-label="Appearance">', page)
        for v in ("dark", "light", "system"):
            self.assertIn('data-theme="%s" role="radio"' % v, page)


if __name__ == "__main__":
    unittest.main()
