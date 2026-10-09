"""0.21.22: launch page, private per-stream latency, sidebar role icons, footers.

Run: python -m unittest tests.test_launch_latency
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class Latency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html")

    def test_no_time_code_in_anyones_picture(self):
        self.assertNotIn('id="viewLatency"', self.p)
        self.assertIn("window.__latencyStamp = false;", self.p)

    def test_viewer_choice_per_stream(self):
        p = self.p
        self.assertIn('items.push({ value: "lat", label: latencyShown.has(name) ? "Hide latency" : "Show latency (only you see it)" });', p)
        self.assertIn('if (v === "lat") { latencyToggle(name); return; }', p)
        self.assertIn('if (!latencyShown.has(name) || (t.watch.getAttribute("visible") || "never") === "never")', p)

    def test_catalog_clock_and_offsets(self):
        p = self.p
        self.assertIn("const captured = 1577836800000 + (clk.wall + ts * sc / 1e6) * 1000 / sc + memberClk(name);", p)
        self.assertIn("pubModel.clk = Math.round((window.__clockOffset || 0) / 10) * 10;", p)
        self.assertIn("clk: Number.isFinite(v.clk) ? v.clk : null", p)
        # an older publisher's strip is still read while the fleet updates
        self.assertIn("if (d == null) { const v = stampRead(t);", p)


class Ui(unittest.TestCase):
    def test_sidebar_role_icons(self):
        p = _read("moq-watch-lite.html")
        self.assertIn('li.querySelector(".role").innerHTML = icon(pub ? "bcast" : "eye");', p)
        # 0.21.35: in the joined room the rail follows the tiles (the view-only tile's rule)
        self.assertIn("pub = [...tiles.keys()].some((n) => personKeyOf(n) === String(m.op || \"\").toLowerCase());", p)
        self.assertNotIn('"\\u25B2" : "\\u25CB"', p)

    def test_footers_name_the_negotiated_protocol(self):
        for name in ("index.html", "moq-watch-lite.html", "relay.html"):
            s = _read(name)
            self.assertIn("moq-lite-06", s, name)
            self.assertNotIn(">moq-lite-05<", s, name)

    def test_phone_has_no_footer(self):
        p = _read("moq-watch-lite.html")
        i = p.index("@media (max-width: 720px), (max-height: 500px) {   /* 0.21.0: a landscape phone is a phone too */")
        self.assertIn("footer.asi-footer { display:none !important; }", p[i:i + 300])

    def test_download_tiles_have_os_marks(self):
        idx = _read("index.html")
        self.assertEqual(idx.count('<svg class="osic"'), 2)


if __name__ == "__main__":
    unittest.main()
