"""0.21.96 (Kenton 2026-10-30: "When adding cameras from the stream library, give me some filters for what is viewable. I don't
always want all cameras, sometimes I only want online." + "I didn't see a filter when I was building a grid."). The grid builder's
Library group gets a filter bar: Online (default) / Live / All, type chips (only the types there are, with counts), the site, and
"N of M" on its header; the choice is remembered for the next grid (kastr.gelib.ui).
Lab (two KASTR boxes + a camera box, 3 live library streams + lab-only offline / not-streaming / unreachable rows): Online hides
offline + unreachable, All shows them, Live only live, Vehicles chip, site, empty hint, kept after a reload; light + dark shots."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class BuilderLibraryFilters(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.src = f.read()
        i = self.src.index("function paintLib(f)")
        self.lib = self.src[i:self.src.index("function drawThumb(th)", i)]
        j = self.src.index("function libBuilderSrc()")
        self.srcfn = self.src[j:self.src.index("// ---- the box:", j)]

    def test_state_filter_online_live_all(self):
        self.assertIn('[["online", "Online"', self.lib)
        self.assertIn('["live", "Live"', self.lib)
        self.assertIn('["all", "All"', self.lib)
        # Online = not offline / not an unreachable site; Live = live + asleep (an asleep camera starts when added)
        self.assertIn('U.show === "all" || (U.show === "live" ? s.state === "live" || s.state === "asleep" : s.state !== "offline" && s.state !== "site")', self.lib)

    def test_type_chips_and_site(self):
        self.assertIn('mkEl("button", "gelibchip", t)', self.lib)
        self.assertIn("if (!on && !kn.get(k)) continue;", self.lib)
        self.assertIn('U.kinds.includes(s.kind)', self.lib)
        self.assertIn('sel.addEventListener("change", () => { U.site = sel.value; save(); });', self.lib)
        self.assertIn('kind: libKindOf(e.kind)', self.srcfn)
        self.assertIn('kinds: LIB_CHIPS.filter(([k]) => k !== "live")', self.srcfn)

    def test_header_counts_and_empty_hint(self):
        self.assertIn('m.length + " of " + rows.length', self.lib)
        self.assertIn("All shows the others.", self.lib)

    def test_remembered(self):
        self.assertIn('const GELIB_KEY = "kastr.gelib.ui";', self.src)
        self.assertIn('const gelibUi = { show: "online", kinds: [], site: "" };', self.src)
        self.assertIn("save: () => { try { localStorage.setItem(GELIB_KEY, JSON.stringify(gelibUi)); } catch {} },", self.srcfn)
        self.assertIn("ui: gelibUi,", self.srcfn)
        # the stored value is checked before use (a bad or old value falls back to the defaults)
        self.assertIn('if (["online", "live", "all"].includes(o.show)) gelibUi.show = o.show;', self.src)

    def test_filter_bar_styled_both_themes_by_tokens(self):
        css = self.src[self.src.index("/* 0.21.96 (Kenton: \"give me some filters"):]
        css = css[:css.index("/* the box picker's library switch */")]
        for sel in (".gelibseg button[aria-pressed=\"true\"]", ".gelibchip[aria-pressed=\"true\"]", ".gelibchip:focus-visible"):
            self.assertIn(sel, css)
        self.assertFalse(re.search(r"#[0-9a-fA-F]{3,6}\b", css), "the filter bar uses the theme tokens only")


if __name__ == "__main__":
    unittest.main()
