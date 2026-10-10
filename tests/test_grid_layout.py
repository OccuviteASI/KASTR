"""0.21.43: the grid layout editor -- templates and custom blocks (owner, everyone sees), the drawn geometry announced,
my own view of a grid (only I see it), up to 4 full-quality cells.

Run: python -m unittest discover -s tests
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _page():
    with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


def _js_fn(p, head):
    i = p.index(head)
    return p[i:p.index("\n  }", i) + 4]


class Templates(unittest.TestCase):
    """The template math, re-run in Python from the page's own numbers (24 x 24 units)."""

    @staticmethod
    def big1(n):
        GU = 24
        if n <= 1:
            return [[0, 0, GU, GU]]
        for sz in (8, 6, 4, 3):
            b = GU - sz
            if 1 + b // sz + GU // sz < n:
                continue
            out = [[0, 0, b, b]]
            y = 0
            while y + sz <= b and len(out) < n:
                out.append([b, y, sz, sz]); y += sz
            x = 0
            while x + sz <= GU and len(out) < n:
                out.append([x, b, sz, sz]); x += sz
            return out
        return None

    def test_page_uses_these_sizes(self):
        p = _page()
        self.assertIn("for (const sz of [8, 6, 4, 3]) {   // the big one is always bigger", p)
        self.assertIn('const GRID_TEMPLATES = [["auto", "Equal"], ["big1", "One big"], ["big2", "Two big"], ["row", "Side by side"], ["column", "Stacked"]];', p)

    def test_one_big_is_bigger_and_never_overlaps(self):
        for n in range(2, 17):
            u = self.big1(n)
            self.assertEqual(len(u), n, n)
            self.assertGreater(u[0][2], u[1][2], n)
            for i in range(n):
                for j in range(i + 1, n):
                    a, b = u[i], u[j]
                    self.assertFalse(a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3], (n, a, b))
                self.assertTrue(u[i][0] + u[i][2] <= 24 and u[i][1] + u[i][3] <= 24)


class OwnerLayout(unittest.TestCase):
    def test_drawn_rects_with_the_gap_are_announced(self):
        p = _page()
        self.assertIn("const raw = gridLayoutPx(g, ms, g.canvas.width, g.canvas.height);", p)
        self.assertIn("g.lastRects = rects;", p)
        self.assertIn("rects: (g.lastRects || []).length === ms.length ? g.lastRects.map(", p)
        self.assertIn("gap: gridGap(g) }));", p)

    def test_custom_blocks_belong_to_cameras(self):
        p = _page()
        self.assertIn('g.custom = Object.fromEntries(boxes.filter((b) => !String(b.key).startsWith("id:")).map((b) => [b.key, b.u]));', p)
        self.assertIn('gridPrefSet(g.id, "custom", JSON.stringify(g.custom || {}));', p)
        self.assertIn('if ((g.layout || "auto") === "custom") {   // 0.21.43: blocks belong to cameras', p)

    def test_menu_offers_templates_and_the_editor(self):
        p = _page()
        self.assertIn('items.push({ value: "edit", label: "Edit layout\\u2026" });', p)
        self.assertIn('else if (v === "edit") gridEditOpen(g);', p)

    def test_editing_takes_the_mouse(self):
        p = _page()
        self.assertIn('if (e.button !== 0 || e.target.closest("button") || g.editing) return;', p)
        self.assertIn('if (e.target.closest("button") || g.editing) return;', p)


class Editor(unittest.TestCase):
    def test_drop_on_another_box_trades_blocks(self):
        p = _page()
        self.assertIn("if (t) swapWith = { t, mine: t.u.slice(), theirs: u0.slice() };", p)

    def test_cancel_and_escape(self):
        p = _page()
        self.assertIn('c.key = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); } };', p)


class Viewers(unittest.TestCase):
    def test_use_the_owners_rects_or_fall_back(self):
        p = _page()
        body = _js_fn(p, "  function gridRectsOf(meta, W, H) {")
        self.assertIn("return gridRectsW(meta?.n || 1, meta?.layout || \"auto\", W, H);", body)
        self.assertEqual(len(re.findall(r"gridRectsW\(meta\.n, meta\.layout", p)), 0)

    def test_my_view_and_full_quality(self):
        p = _page()
        self.assertIn('const VG_KEY = "kastr.vgrid.", VG_HQ_MAX = 4;', p)
        self.assertIn("|| vgHqWanted(name);   // 0.21.43", p)
        self.assertIn('value: "vgedit", icon: "view", label: "Arrange this grid for me\\u2026"', p)
        self.assertIn("if (hq.size >= VG_HQ_MAX) {", p)
        self.assertIn("const rs = meta.path && vgHasRects(meta.path) ? vgDstRects(meta.path, meta, f.cw, f.ch) : gridRectsOf(meta, f.cw, f.ch);", p)


if __name__ == "__main__":
    unittest.main()
