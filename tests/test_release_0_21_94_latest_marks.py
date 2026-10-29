"""0.21.94 (Kenton 2026-10-29: "I don't need to show the seen/read/sent icon for all messages, just for the latest message. It's
implied that the previous messages have been read if the last one has been. Keep showing the previous message as read until the
last message shows read."): in Messages the step mark (sending / sent / delivered / read) sits on MY NEWEST message only; while
that one is not read yet the eye stays on my most recent read one (two marks at most). A failed send keeps its own line, a group
shows "sent" on the newest only, and hovering any of my messages' time still names its sent / delivered / read times.

CASES is the rule as a table; the lab (Chrome) runs the page's own window.__msgLatestMarks over the same table."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# each case: (messages as [seq, mine, extra], ticks {d, r} or None, group, the seqs that carry a mark)
CASES = [
    ("nothing of mine", [[1, False, {}], [2, False, {}]], {"d": 2, "r": 2}, False, []),
    ("newest read: only it", [[1, True, {}], [2, True, {}], [3, True, {}]], {"d": 3, "r": 3}, False, [3]),
    ("newest delivered, older read", [[1, True, {}], [2, True, {}], [3, True, {}]], {"d": 3, "r": 2}, False, [2, 3]),
    ("newest sent, nothing read", [[1, True, {}], [2, True, {}]], {"d": 0, "r": 0}, False, [2]),
    ("newest sending, older read", [[1, True, {}], [2, True, {}], [0, True, {"sending": True}]], {"d": 2, "r": 1}, False, [1, 0]),
    ("their reply last, mine read", [[1, True, {}], [2, True, {}], [3, False, {}]], {"d": 2, "r": 2}, False, [2]),
    ("failed newest is not the newest", [[1, True, {}], [2, True, {}], [0, True, {"err": "offline"}]], {"d": 2, "r": 1}, False, [1, 2]),
    ("waiting ones are skipped", [[1, True, {}], [0, True, {"waiting": True}]], {"d": 1, "r": 1}, False, [1]),
    ("scheduled and system lines skipped", [[1, True, {}], [2, True, {"kind": "sys"}], [0, True, {"sched": True}]], {"d": 1, "r": 0}, False, [1]),
    ("group: newest only", [[1, True, {}], [2, True, {}]], None, True, [2]),
    ("no ticks yet: newest only", [[1, True, {}], [2, True, {}]], None, False, [2]),
    ("last read one expired: the next older read one", [[1, True, {}], [3, True, {}]], {"d": 3, "r": 2}, False, [1, 3]),
]


def _step(m, tk, group):
    if m.get("sending") or not m.get("seq"):
        return "sending"
    if group or not tk:
        return "sent"
    return "read" if tk["r"] >= m["seq"] else "dlv" if tk["d"] >= m["seq"] else "sent"


def latest_marks(recs, tk, group):
    """The same rule as kastr-msg.js latestMarks (the lab checks the page agrees on CASES)."""
    mine = [r for r in recs if r.get("mine") and not r.get("sched") and r.get("kind") != "sys" and not r.get("err") and not r.get("waiting")]
    if not mine:
        return []
    on = [mine[-1]]
    if _step(mine[-1], tk, group) != "read":
        for r in reversed(mine[:-1]):
            if _step(r, tk, group) == "read":
                on.insert(0, r)
                break
    return on


def recs_of(rows):
    return [dict({"seq": s, "mine": mine, "kind": "msg"}, **x) for s, mine, x in rows]


class Rule(unittest.TestCase):
    def test_cases(self):
        for name, rows, tk, group, want in CASES:
            got = [r["seq"] for r in latest_marks(recs_of(rows), tk, group)]
            self.assertEqual(sorted(got), sorted(want), name)

    def test_at_most_two(self):
        for name, rows, tk, group, want in CASES:
            self.assertLessEqual(len(want), 2, name)


class Page(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "assets", "kastr-msg.js"), encoding="utf-8", newline="") as f:
            self.js = f.read()

    def test_rule_in_the_page(self):
        js = self.js
        self.assertIn("const markOn = latestMarks(recs, tk, !!g);", js)
        self.assertIn('const mine = recs.filter((r) => r.mine && !r.sched && r.kind !== "sys" && !r.err && !r.waiting);', js)
        self.assertIn('if (stepOf(newest, tk, group) !== "read") {', js)
        self.assertIn('if (group || !tk) return "sent";', js)
        self.assertIn("window.__msgLatestMarks = latestMarks;", js)

    def test_failed_and_waiting_keep_their_line(self):
        js = self.js
        i = js.index("const step = stepOf(r, tk, !!g), words = stepWords(r, tk, step);")
        blk = js[i:i + 900]
        self.assertLess(blk.index('s.textContent = " ⚠ Not sent: " + r.err'), blk.index("else if (markOn.has(r)) stMark(s, step, words);"))
        self.assertIn('else if (r.waiting) s.textContent = " ⏲ Waiting for the hub";', blk)

    def test_hover_times_on_every_message(self):
        js = self.js
        self.assertIn("if (!r.err && !r.waiting) meta.title = stepTimes(r, tk, !!g);", js)
        self.assertIn('const out = ["Sent " + fmtWhen(r.at)];', js)
        self.assertIn('return out.join(" · ");', js)

    def test_repaints_with_receipts(self):
        # the log's signature carries every record's seq / sending / err and the ticks, so a receipt, a send or a
        # message vanishing repaints -- and the marks are worked out again from what is left
        js = self.js
        self.assertIn("const sig = JSON.stringify([recs.map((r) => [r.k, r.seq, !!r.sending, !!r.waiting, r.err", js)
        self.assertIn("]), read, tk]);", js)

    def test_line_endings(self):
        self.assertNotIn("\r", self.js)


if __name__ == "__main__":
    unittest.main()
