"""0.21.15: a grid with evicted members survives at ZERO live members (moq-watch-lite.html updateRtspGrid).

Run: python -m unittest discover -s tests   (build.py's exact invocation, before every build; tests/ is not a package, so no -t)

The keep rule, the placeholder cell, the evidence lines and the rig hooks are inline JS in an 18k-line page, so this
guards the exact text a merge could drop -- the way tests/test_vendor_patch.py guards the vendored patches. No network,
no processes: it reads the page once.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
PAGE = os.path.join(HERE, "moq-watch-lite.html")


class GridKeepRuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PAGE, encoding="utf-8", newline="") as f:
            cls.text = f.read()

    def test_keep_rule_present_once_and_old_clause_gone(self):
        new = 'if (gridFeeds !== "separate" && (entries.length >= 2 || (g && evicted.length > 0))) {'
        old = "(g && evicted.length && entries.length >= 1)"
        self.assertEqual(self.text.count(new), 1, "0.21.15 keep rule missing or duplicated")
        self.assertNotIn(old, self.text, "0.14.0 one-live-member clause is back")
        # the 0.14.0 comment above the rule no longer promises 'one surviving member'
        self.assertNotIn("One surviving member keeps the grid alive meanwhile", self.text)
        self.assertEqual(self.text.count("ANY evicted seat keeps the grid alive"), 1)

    def test_owner_evidence_line(self):
        # the all-out <-> some-back transition reaches the status bar, the diag ring and launch.log via gridNote
        self.assertEqual(self.text.count("members offline -- grid kept on the air, members hidden as out"), 1)
        # noteAt = 0: the line must not be swallowed by gridNote's 2 s per-grid bridge throttle, which the same tick's
        # `evicted ...` / `readmitted ...` gridNoteAll has just armed (that throttle is why `torn down` never landed)
        self.assertEqual(self.text.count("if (allOut !== !!g.allOut) { g.allOut = allOut; g.noteAt = 0; gridNote(g,"), 1)

    def test_placeholder_cell_uses_the_escape_idiom(self):
        # the page writes an em dash in JS strings as the six characters backslash-u-2-0-1-4
        self.assertEqual(self.text.count('"cameras offline \\u2014 reconnecting ("'), 1)
        self.assertNotIn("cameras offline — reconnecting", self.text, "literal em dash in the placeholder text")
        self.assertEqual(self.text.count("if (!ms.length && rects[0]) {"), 1)

    def test_viewer_belt(self):
        self.assertEqual(self.text.count("function gridForget(gp, m)"), 1)
        self.assertEqual(self.text.count("gridForget("), 3, "definition + pruneGridMeta + the tile-removal site")
        self.assertEqual(self.text.count("const GRID_FORGOT_HOLD_MS = 60000;"), 1)
        self.assertEqual(self.text.count("gridForgot: Object.fromEntries"), 1)
        # the console line carries the module's KASTR: prefix, not a new one
        self.assertEqual(self.text.count('console.warn("KASTR: \\"" + name + "\\" was a member of " + gp'), 1)
        self.assertNotIn('console.warn("switcher:', self.text)
        # the trailing comment reads 'split up in the presence' -- a raw Python string once left the backslashes in
        self.assertEqual(self.text.count("// 0.21.15: the 'split up in the presence' evidence"), 1)
        self.assertNotIn("\\'split up in the presence\\'", self.text)

    def test_rig_hooks(self):
        self.assertEqual(self.text.count("evict: (url, on = true) =>"), 1)
        self.assertEqual(self.text.count('if (!back || a.evictWhy === "rig") continue;'), 1)
        self.assertNotIn("        if (!back) continue;\r\n", self.text)

    def test_page_stays_crlf_and_escape_clean(self):
        # the patch must not leave a lone LF (a CRLF file with one LF line breaks the repo's EOL discipline)
        stripped = self.text.replace("\r\n", "")
        self.assertNotIn("\n", stripped, "a bare LF slipped into the CRLF page")
        self.assertNotIn("\r", stripped, "a bare CR slipped into the CRLF page")


if __name__ == "__main__":
    unittest.main()
