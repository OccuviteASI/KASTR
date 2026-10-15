"""v0.21.72 (Kenton 2026-10-15: "I would like more theme options other than light/dark/system"; he chose named themes, High
contrast and a Custom theme): html[data-theme] stays the dark / light BASE (every page's light rules keep working) and
html[data-palette] picks the colours; Custom mixes the rest from three colours and keeps them for the page heads.

Run: python -m unittest discover -s tests
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ("app.html", "index.html", "moq-watch-lite.html", "relay.html", "stats.html", "watch.html")


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class Themes(unittest.TestCase):
    def test_palettes(self):
        css = read("assets/asi-brand.css")
        for pal in ("midnight", "slate", "warm", "contrast"):
            self.assertIn(':root[data-palette="%s"] {' % pal, css)
        self.assertIn(':root[data-palette="contrast"] :focus-visible { outline:3px solid #ffffff !important;', css)
        self.assertLess(css.index(':root[data-theme="light"] {'), css.index(':root[data-palette="warm"]'))   # a palette wins over its base

    def test_setting(self):
        js = read("assets/asi-brand.js")
        self.assertIn('const THEMES = ["system", "dark", "midnight", "slate", "light", "warm", "contrast", "custom"];', js)
        self.assertIn("d.dataset.theme = base; d.dataset.palette = pal;", js)
        self.assertIn('try { localStorage.setItem(VARS_KEY, JSON.stringify(cv)); } catch {}', js)
        self.assertIn("window.__kastrTheme = { get: themeGet, set: themeSet, custom: customGet, setCustom: customSet, list: THEMES.slice() };", js)

    def test_every_page_head_knows_the_palettes(self):
        snips = []
        for f in PAGES:
            m = re.search(r'try\{var d=document\.documentElement,t=localStorage\.getItem\("kastr\.theme"\).*?catch\(e\)\{document\.documentElement\.dataset\.theme="dark";\}', read(f))
            self.assertIsNotNone(m, f)
            snips.append(m.group(0))
            self.assertIn('localStorage.getItem("kastr.theme.vars")', m.group(0))
            self.assertIn("d.dataset.palette=p;", m.group(0))
        self.assertEqual(len(set(snips)), 1)   # one snippet, everywhere

    def test_more_menu(self):
        p = read("moq-watch-lite.html")
        self.assertIn('<span class="thgrid" id="optThemeGrid"></span>', p)
        self.assertIn('<span class="thcustom" id="optThemeCustom" hidden>', p)
        for v, label in (("dark", "ASI Navy"), ("midnight", "Midnight"), ("slate", "Slate"), ("warm", "Warm light"), ("contrast", "High contrast"), ("custom", "Custom")):
            self.assertIn('{ v: "%s", label: "%s"' % (v, label), p)

    def test_remembered_with_the_app(self):
        self.assertIn("|theme$|theme" + chr(92) + ".custom$|accent$)/;", read("assets/prefs.js"))
        self.assertIn('r"|theme$|theme' + chr(92) + '.custom$|accent$)")', read("kastr_serve.py"))


if __name__ == "__main__":
    unittest.main()
