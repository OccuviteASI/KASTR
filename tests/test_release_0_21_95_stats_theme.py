# -*- coding: utf-8 -*-
"""v0.21.95 STATS PAGE THEMES (Kenton: "add the stats.html fix to the next update"; found during 0.21.92: stats.html was
unreadable in the Light theme). The page's vendored Tailwind build and its stats bundle (assets/stats-*.js) are dark-only --
neutral-900 cards, white / neutral-300 text, and hex colours written straight into the SVG charts. stats.html now has ONE
colour source, <style id="kastrStatsTheme">, which maps every Tailwind colour the page and the bundle use onto the app's
theme tokens (assets/asi-brand.css: --bg / --surface / --line / --text*, the named palettes, Custom, the accent) and
overrides the bundle's SVG presentation attributes with CSS; the bundle stays byte-identical. The theme itself follows
the main page (localStorage kastr.theme + the head snippet + asi-brand.js's storage listener; prefs.js seeds a fresh
browser on this machine). Lab: C:\\kastr-scratch\\v02195\\stats (relay + test-pattern publishers, Playwright shots in every
theme, a WCAG contrast sweep of every visible text node).

Run: python -m unittest discover -s tests
"""
import glob
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# a Tailwind colour utility, with any variant prefixes (hover:, focus:, sm:) and an optional /opacity
TW = re.compile(r"(?<![\w-])(?:[a-z]+:)*(?:bg|text|border|ring|outline|divide|fill|stroke|from|to|via|accent|caret|decoration|shadow)-"
                r"((?:neutral|gray|zinc|slate|stone|emerald|green|sky|blue|cyan|teal|amber|yellow|orange|red|rose|pink|purple|violet|indigo|lime|fuchsia)-\d{2,3}|white|black)"
                r"(?:/\d+)?(?![\w-])")
LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb)\(")
NEUTRAL = re.compile(r"^(?:neutral|gray|zinc|slate|stone)-\d+$|^white$|^black$")


def read(*p):
    with open(os.path.join(HERE, *p), encoding="utf-8") as f:
        return f.read()


def bundle():
    html = read("stats.html")
    m = re.search(r'<script type="module" crossorigin src="/assets/(stats-[\w-]+\.js)"></script>', html)
    assert m, "stats.html no longer loads its stats bundle"
    return m.group(1), read("assets", m.group(1))


def lum(hexc):
    h = hexc.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    out = []
    for i in (0, 2, 4):
        v = int(h[i:i + 2], 16) / 255.0
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a, b):
    x, y = lum(a), lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


class StatsTheme(unittest.TestCase):
    def setUp(self):
        self.html = read("stats.html")
        m = re.search(r'<style id="kastrStatsTheme">(.*?)</style>', self.html, re.S)
        self.assertIsNotNone(m, "the token block is missing")
        self.block = m.group(1)
        self.outside = self.html[:m.start()] + self.html[m.end():]
        r = re.search(r"(?m)^\s*:root \{(.*?)\}", self.block, re.S)
        lt = re.search(r':root\[data-theme="light"\] \{(.*?)\}', self.block, re.S)
        self.assertIsNotNone(r)
        self.assertIsNotNone(lt)
        self.root, self.light = r.group(1), lt.group(1)

    def defs(self, text):
        return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", text))

    def test_block_sits_between_the_stylesheets_and_the_brand_script(self):
        h = self.html
        i = h.index('<style id="kastrStatsTheme">')
        self.assertLess(h.index('href="/assets/reload-'), i)          # after the Tailwind build: it wins
        self.assertLess(h.index('href="/assets/asi-brand.css"'), i)   # after the brand tokens it reads
        self.assertLess(i, h.index('src="/assets/asi-brand.js"'))

    def test_no_hardcoded_colours_outside_the_token_block(self):
        bad = [(m.group(0), self.outside[max(0, m.start() - 60):m.end() + 20]) for m in LITERAL.finditer(self.outside)]
        self.assertEqual(bad, [], "colour literals outside <style id=kastrStatsTheme>")
        for m in re.finditer(r'\bstyle\s*=\s*"([^"]*)"', self.outside):
            self.assertNotRegex(m.group(1), r"(?i)\b(?:color|background|border-color|fill|stroke)\s*:", "inline colour: " + m.group(0))
        self.assertEqual(len(re.findall(r"<style\b", self.html)), 1, "one style block: the token block")

    def test_every_tailwind_colour_the_page_and_bundle_use_is_mapped(self):
        _, js = bundle()
        used = set(TW.findall(self.outside)) | set(TW.findall(js))
        self.assertTrue({"neutral-900", "neutral-500", "white", "emerald-400", "sky-400"} <= used, used)   # the scan works
        root, light = self.defs(self.root), self.defs(self.light)
        for c in sorted(used):
            var = "--color-" + c
            if NEUTRAL.match(c):
                # text / lines / surfaces: theme tokens in every theme (Midnight, Slate, High contrast and Custom included)
                self.assertIn(var, root, c)
                self.assertIn("var(--", root[var], c)
            elif var not in root:
                # data colours: dark keeps Tailwind's own; light grounds need their own darker value
                self.assertIn(var, light, c + " has no light-theme value")

    def test_accent_drives_focus_and_selection(self):
        self.assertEqual(self.defs(self.root).get("--color-emerald-600"), "var(--asi-blue)")
        self.assertIn(".st-go { background: var(--asi-blue); color: var(--on-accent);", self.block)
        self.assertIn('class="st-go ', self.html)
        self.assertIn('class="st-err ', self.html)

    def test_bundle_svg_colours_are_overridden(self):
        _, js = bundle()
        hexes = set(re.findall(r"color:`(#[0-9a-fA-F]{6})`", js)) | set(re.findall(r"setAttribute\(`stroke`,`(#[0-9a-fA-F]{6})`\)", js))
        self.assertTrue({"#34d399", "#38bdf8", "#404040"} <= hexes, hexes)   # the scan works
        for h in sorted(hexes):
            self.assertRegex(self.block, r'\[stroke="%s"\] \{ stroke: var\(--' % h, h)
            if re.search(r"color:`%s`" % h, js):   # a series colour: also the gradient under the line
                self.assertRegex(self.block, r'\[stop-color="%s"\] \{ stop-color: var\(--' % h, h)
        root, light = self.defs(self.root), self.defs(self.light)
        for v in ("--st-egress", "--st-ingress"):
            self.assertIn(v, root)
            self.assertIn(v, light)
        self.assertEqual((root["--st-egress"].lower(), root["--st-ingress"].lower()), ("#34d399", "#38bdf8"))   # dark unchanged

    def test_light_data_colours_read_on_white(self):
        light = self.defs(self.light)
        grounds = ("#ffffff", "#eef2f6", "#f2f5f8", "#fffcf6", "#f3eee5")   # asi-brand.css light + warm surfaces / grounds
        for var, val in sorted(light.items()):
            if not val.startswith("#") or var.endswith("-800"):   # -800 = borders on a light ground
                continue
            need = 3.0 if var in ("--color-amber-400", "--color-red-400") else 4.5   # -400 amber/red = status dots
            for g in grounds:
                self.assertGreaterEqual(contrast(val, g), need, "%s %s on %s" % (var, val, g))

    def test_follows_the_app_theme(self):
        h = self.html
        self.assertIn('localStorage.getItem("kastr.theme")||"dark"', h)   # the shared head snippet (tests/test_release_0_21_72_themes.py)
        self.assertIn('<script type="module" src="/assets/asi-brand.js"></script>', h)   # live: storage event + accent
        js = read("assets", "asi-brand.js")
        self.assertIn('window.addEventListener("storage", (e) => { if (e.key === THEME_KEY || e.key === CUSTOM_KEY) themeApply(); });', js)
        self.assertIn('window.addEventListener("storage", (e) => { if (e.key === ACCENT_KEY) accentApply(); });', js)
        # prefs.js seeds the app's theme + accent into a browser that has never opened the main page here
        self.assertLess(h.index('src="/assets/client.js"'), h.index('src="/assets/prefs.js"'))
        self.assertLess(h.index('src="/assets/prefs.js"'), h.index('src="/assets/vault.js"'))
        self.assertIn("theme$|theme\\.custom$|accent$", read("assets", "prefs.js"))

    def test_bundle_left_as_vendored(self):
        name, js = bundle()
        self.assertEqual(sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, "assets", "stats-*.js"))), [name])
        self.assertIn("setAttribute(`stroke`,i.color)", js)   # still the attribute the CSS overrides

    def test_no_checkboxes_outside_a_switch(self):
        _, js = bundle()
        for m in re.finditer(r"<input\b[^>]*>", self.html):
            if re.search(r"""type\s*=\s*["']?checkbox""", m.group(0), re.I):
                self.assertRegex(self.html[max(0, m.start() - 80):m.start()], r'<(?:span|label)\b[^<>]*class="switch\b[^"]*"[^<>]*>\s*$', m.group(0))
        self.assertNotRegex(js, r"checkbox")


if __name__ == "__main__":
    unittest.main()
