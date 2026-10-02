"""0.21.15 (Part 39 item 5): join/leave chimes ring for PEOPLE only -- one classifier (pathClass) shared by the tile
gate, the 0.21.2 presence sweep, the People head and personChime; a join is judged after CHIME_SETTLE_MS with the tile
still present; first-in / last-out counts person-class tiles only; the People head reads a cache (reclassifyTiles),
never the classifier, because paintPersonGroups runs inside the 1 s applyState loop.

Run: python -m unittest discover -s tests -t .   (build.py runs it before every build)

Page-marker tests read moq-watch-lite.html the way tests/test_vendor_patch.py reads the vendored player
(newline=""); the classifier table test runs the page's own isContentPath / personKeyOf / pathClass under node when
`node` is on PATH and is skipped otherwise. No network, no processes besides that optional node.
"""
import os
import re
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
PAGE = os.path.join(HERE, "moq-watch-lite.html")


def page_text():
    with open(PAGE, encoding="utf-8", newline="") as f:
        return f.read()


def func_source(text, name):
    """The source of `function <name>(...) { ... }` from the page (brace-balanced, strings ignored well enough
    for these three helpers, which hold no braces inside string literals)."""
    m = re.search(r"\n  function %s\([^)]*\) \{" % re.escape(name), text)
    if not m:
        return None
    i = m.end() - 1
    depth = 0
    j = i
    while j < len(text):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[m.start() + 1:j + 1]
        j += 1
    return None


class ChimeMarkers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = page_text()

    def count(self, needle):
        return self.text.count(needle)

    def test_one_classifier(self):
        self.assertEqual(self.count("function pathClass(name) {"), 1)
        self.assertEqual(self.count("window.__pathClass = pathClass;"), 1)
        # the classifier composes the five rules in this order: low, grid, gridchild, content, box, person
        src = func_source(self.text, "pathClass")
        self.assertIsNotNone(src)
        order = [src.index(k) for k in ("LOW_RE.test(n)", "gridMeta.has(n)", "isGridChild(n)", "isContentPath(n)", "boxHiddenPath(n)", 'return "person"')]
        self.assertEqual(order, sorted(order), "pathClass rule order")

    def test_box_rule_has_one_home(self):
        # boxHiddenPath is called from pathClass only (its declaration + that one call); the tile gate and the
        # 0.21.2 sweep read the classifier
        self.assertEqual(self.count("boxHiddenPath("), 2)
        self.assertEqual(self.count("if (boxHiddenPath(name)) return;   // 0.21.2"), 0)
        self.assertEqual(self.count('if (pathClass(name) === "box") return;'), 1)
        self.assertEqual(self.count('if (pathClass(n) === "box") removeTile(n);'), 1)

    def test_chime_path(self):
        self.assertEqual(self.count("const CHIME_SETTLE_MS = 1500;"), 1)
        self.assertEqual(self.count("function personChimeJudge(path, joined) {"), 1)
        self.assertEqual(self.count("function personChime(path, joined) {"), 1)
        # tile-driven as before: createTile rings a join, removeTile a leave -- exactly one call each
        self.assertEqual(self.count("personChime(name, true);"), 1)
        self.assertEqual(self.count("personChime(name, false);"), 1)
        # the old 'not actually new' guard is gone (the verdict now runs after tiles.set)
        self.assertEqual(self.count("if (joined && tiles.has(path)) return;"), 0)
        # personChimeJudge is the only caller of chimeTone (plus its declaration)
        self.assertEqual(self.count("chimeTone("), 2)
        judge = func_source(self.text, "personChimeJudge")
        self.assertIsNotNone(judge)
        self.assertIn('if (cls !== "person")', judge)
        self.assertIn("personTilesOf(key, path).length", judge)
        self.assertIn("chimeTone(joined);", judge)
        chime = func_source(self.text, "personChime")
        self.assertIn("setTimeout(() => personChimeJudge(path, true), CHIME_SETTLE_MS)", chime)
        self.assertIn("personChimeJudge(path, false);", chime)
        self.assertNotIn("chimeTone(", chime)

    def test_person_tiles_ignore_shares(self):
        self.assertEqual(self.count("const personTilesOf = (key, except) ="), 1)
        line = [l for l in self.text.splitlines() if "const personTilesOf" in l][0]
        self.assertIn("isPersonPath(n)", line)
        self.assertIn("personKeyOf(n) === key", line)

    def test_verdict_log_rides_state(self):
        self.assertEqual(self.count("window.__chimeLog = chimeLog;"), 1)
        self.assertEqual(self.count("chimes: { played: chimeLog.played, held: chimeLog.held, last: chimeLog.last.slice(-5) },"), 1)
        state_classes = "      classes: Object.fromEntries(tileClasses),   // 0.21.15: what each tile is"
        self.assertEqual(self.count(state_classes), 1)
        # both sit inside __switcher.state(), right after `streams`
        i = self.text.index("      streams: [...tiles.keys()],")
        self.assertLess(i, self.text.index("chimes: { played:"))
        self.assertLess(self.text.index("chimes: { played:"), self.text.index(state_classes))
        self.assertLess(self.text.index(state_classes) - i, 600)
        # the rig hook exposes the same cache plus the box operators
        self.assertEqual(self.count("window.__tileClasses = () => ({ classes: Object.fromEntries(tileClasses), boxOps: [...boxOps] });"), 1)

    def test_cache_not_classifier_in_the_paint_loop(self):
        # reclassifyTiles() runs once per tile / presence / grid diff: createTile, removeTile, roomsChanged, rebuildGridChildren
        self.assertEqual(self.count("function reclassifyTiles() {"), 1)
        self.assertEqual(self.count("reclassifyTiles();"), 4)
        for anchor in ("    tiles.set(name, tile);\r\n    reclassifyTiles();", "    tiles.delete(name);\r\n    reclassifyTiles();",
                       "      gridChildOf.set(f, gp);\r\n    }\r\n    try { reclassifyTiles(); } catch {}"):
            self.assertEqual(self.count(anchor), 1, anchor[:50])
        paint = func_source(self.text, "paintPersonGroups")
        self.assertIsNotNone(paint)
        code = "\n".join(l for l in paint.splitlines() if not l.strip().startswith("//"))   # comments may name the rule
        self.assertNotIn("pathClass(", code, "paintPersonGroups must read the cache, not the classifier")
        self.assertNotIn("boxHiddenPath(", code)
        self.assertNotIn("roomsPres", code)
        self.assertIn("boxOps.has(op)", paint)
        self.assertIn("tileClasses.get(r.title)", paint)

    def test_people_head_keeps_the_escape_idiom(self):
        # the page writes the em dash as the JS escape sequence, never the character
        line = [l for l in self.text.splitlines() if '" feeds (box)"' in l]
        self.assertEqual(len(line), 1)
        self.assertIn('+ " \\u2014 " + n + (box ?', line[0])
        self.assertNotIn("—", line[0])
        self.assertEqual(self.count('(n === 1 ? " feed (box)" : " feeds (box)")'), 1)
        self.assertEqual(self.count('(n === 1 ? " stream" : " streams")'), 1)

    def test_room_switch_tone_untouched(self):
        self.assertEqual(self.count("chimeRoom();   // 0.15.0 (D3)"), 1)
        self.assertEqual(self.count("function chimeRoom() {"), 1)
        self.assertEqual(self.count("window.__chimeRoom = chimeRoom;"), 1)

    def test_crlf_only(self):
        self.assertNotRegex(self.text, r"(?<!\r)\n", "moq-watch-lite.html is CRLF")


class ClassifierTable(unittest.TestCase):
    """The page's own isContentPath / personKeyOf / pathClass, run under node with the four runtime rules stubbed."""

    CASES = [
        ("r/h/pat/camera.hang", "person"),
        ("r/h/pat/camera-2.hang", "person"),
        ("r/h/pat/screen.hang", "content"),
        ("r/h/pat/movie.hang", "content"),
        ("r/h/box/rtsp-grid.hang", "grid"),
        ("r/h/box/rtsp-test.hang", "gridchild"),
        ("r/h/box/rtsp-cam2.hang", "content"),
        ("r/h/box/camera.hang", "box"),
        ("r/h/pat/camera-low.hang", "low"),
    ]

    def test_table(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        text = page_text()
        parts = [func_source(text, n) for n in ("isContentPath", "personKeyOf", "pathClass")]
        self.assertTrue(all(parts), "page helpers not found")
        js = "\n".join([
            "const LOW_RE = /-low\\.hang$/;",
            'const gridMeta = new Map([["r/h/box/rtsp-grid.hang", {}]]);',
            'const isGridChild = (n) => n === "r/h/box/rtsp-test.hang";',
            'const boxHiddenPath = (n) => n === "r/h/box/camera.hang";',
            "const tiles = new Map();",
        ] + parts + [
            "const cases = %s;" % repr([c[0] for c in self.CASES]).replace("'", '"'),
            "process.stdout.write(JSON.stringify(cases.map((p) => pathClass(p))));",
            'process.stdout.write("\\n" + JSON.stringify(cases.map((p) => personKeyOf(p))));',
        ])
        out = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        classes, keys = out.stdout.strip().split("\n")
        import json
        self.assertEqual(json.loads(classes), [c[1] for c in self.CASES])
        self.assertEqual(json.loads(keys), ["pat", "pat", "pat", "pat", "box", "box", "box", "box", "pat"])


if __name__ == "__main__":
    unittest.main()
