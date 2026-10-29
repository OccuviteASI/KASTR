"""0.21.93 (Kenton: "change the way it shows whether a message is sent/delivered/viewed" -> "Clearer icons on each"):
a different mark per step (open circle sending, check sent, filled check delivered, eye read) with the words and the TIME on
hover. The hub keeps when each person's delivered and read cursors moved (Messenger.rcpt, [[seq, at], ...]) and op ticks
hands them out as dt / rt; they follow a rename, age out with the messages and ride the standby sync."""
import os
import re
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))
import kastr_msg as km  # noqa: E402
import test_release_0_21_88_messages as t88  # noqa: E402


class Merge(unittest.TestCase):
    def test_earliest_time_per_seq_and_covered_entries_dropped(self):
        got = km._rcpt_merge([[10, 100], [20, 200]], [[12, 90], [20, 150], [30, 300]])
        self.assertEqual(got, [[12, 90], [20, 150], [30, 300]])   # 12 reached at 90 covers 10 (reached at 100)

    def test_bad_rows_and_the_cap(self):
        self.assertEqual(km._rcpt_merge(None, [["x", 1], [3], "no", [4, 40]]), [[4, 40]])
        rows = [[i, i * 10] for i in range(1, km.RCPT_KEEP + 30)]
        got = km._rcpt_merge(rows, [])
        self.assertEqual(len(got), km.RCPT_KEEP)
        self.assertEqual(got[-1], rows[-1])


class Hub(t88.Base):   # t88.Hub's own setUp, without running its tests again here
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = t88.kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, t88.store(self.dir))
        for n, c in (("Kris Price", t88.KRIS_CODE), ("Ada", t88.ADA_CODE)):
            self.mkroom(self.svc, n, c)
        self.kris = t88.Device(self.svc, "kris-desk-1a2b")
        self.ada = t88.Device(self.svc, "ada-laptop-3c4d", room="beta")

    def tearDown(self):
        self.svc.close()

    def _deliver_and_read(self):
        self.kris.unlock("Kris Price", t88.KRIS_CODE)
        self.ada.unlock("Ada", t88.ADA_CODE)
        seq = self.kris.send("Kris Price", {"t": "hi"}, to="Ada")[0]["seq"]
        seq2 = self.kris.send("Kris Price", {"t": "there"}, to="Ada")[0]["seq"]
        self.ada.pull(["Ada"])
        self.ada.pull(["Ada"])   # the ack rides the next pull
        self.assertEqual(self.ada.api({"op": "read", "as": "Ada", "conv": "p:kris price", "seq": seq2})[1], 200)
        return seq, seq2

    def test_ticks_carry_when_delivered_and_read(self):
        seq, seq2 = self._deliver_and_read()
        t = self.kris.api({"op": "ticks", "as": "Kris Price", "names": ["Ada"]})[0]["ticks"]["ada"]
        self.assertEqual((t["d"], t["r"]), (seq2, seq2))
        for lst in (t["dt"], t["rt"]):
            self.assertTrue(lst and lst[-1][0] == seq2 and abs(lst[-1][1] - time.time()) < 30, lst)
        # nothing new: no second entry for the same seq
        self.ada.pull(["Ada"])
        self.ada.api({"op": "read", "as": "Ada", "conv": "p:kris price", "seq": seq2})
        t = self.kris.api({"op": "ticks", "as": "Kris Price", "names": ["Ada"]})[0]["ticks"]["ada"]
        self.assertEqual(len(t["rt"]), 1)

    def test_times_age_out_with_the_messages(self):
        self._deliver_and_read()
        m = self.svc._msgr()
        self.assertIn("ada", m.rcpt)
        m.sweep(now=time.time() + km.MSG_KEEP_S + 60)
        self.assertNotIn("ada", m.rcpt)

    def test_rename_moves_the_times(self):
        self._deliver_and_read()
        m = self.svc._msgr()
        with m.lock:
            m._rename_refs("ada", "ada lovelace", "Ada Lovelace", "Ada", time.time(), announce=False)
        self.assertIn("ada lovelace", m.rcpt)
        self.assertNotIn("ada", m.rcpt)
        self.assertIn("p:kris price", m.rcpt["ada lovelace"])

    def test_standby_copy_keeps_the_times(self):
        self._deliver_and_read()
        m = self.svc._msgr()
        b = km.Messenger(tempfile.mkdtemp())
        b.merge(m.export())
        self.assertEqual(b.rcpt.get("ada"), m.rcpt.get("ada"))
        b.merge(m.export())   # again: nothing doubles
        self.assertEqual(b.rcpt.get("ada"), m.rcpt.get("ada"))


class Page(unittest.TestCase):
    def test_marks_and_hover_words(self):
        with open(os.path.join(HERE, "assets", "kastr-msg.js"), encoding="utf-8") as f:
            js = f.read()
        for k in ("sending", "sent", "dlv", "read"):
            self.assertIn(k + ":", js[js.index("const ST_SVG"):js.index("function stMark")])
        # 0.21.94: the words live in stepWords / stepTimes (the mark goes on the latest message only -- see test_release_0_21_94_latest_marks)
        self.assertIn('step === "read" ? "Read" + rcptAt(tk.rt, r.seq) : step === "dlv" ? "Delivered" + rcptAt(tk.dt, r.seq)', js)
        self.assertIn("else if (markOn.has(r)) stMark(s, step, words);", js)
        self.assertNotIn('s.textContent = " ✓✓"', js)
        self.assertEqual(int(re.search(r"const RCPT_KEEP = (\d+)", js).group(1)), km.RCPT_KEEP)
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertIn(".mst.st-dlv { --mst-ink:var(--asi-blue); }", html)


if __name__ == "__main__":
    unittest.main()
