# -*- coding: utf-8 -*-
"""0.21.91 (Kenton: "I also don't need an alert every single time an RTSP share isn't connected and retries. I just need it
after 1 try, and maybe again after a few tries, but I don't need it repeating forever."). Root cause: the 0.7.8 fault toast
lived on the SLOT, and a camera that never came up is rebuilt slot by slot by the page's retry ladder -- every rebuild was a
fresh slot with a fresh "RTSP source failed" toast, forever (every ~50 s once the ladder reached its 30 s step).

Now the page counts per camera (the ENTRY): one alert after the first failed attempt, one more at the 5th ("still failing
after 5 tries -- KASTR keeps retrying quietly"), then nothing; a camera that comes back starts over; cameras failing together
make one notice. launch.log: a pair that keeps failing logs its 1st and 5th try in full, then a summary every 10 minutes.
"""
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_rtsp  # noqa: E402


def page():
    with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


def between(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


class PageAlerts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = page()
        cls.tick = between(cls.s, "  function feedAlertTick() {", "  function feedAlertFlush() {")
        cls.flush = between(cls.s, "  function feedAlertFlush() {", "  setInterval(feedAlertTick, 1000);")
        cls.state = between(cls.s, "  function feedAlertState(slot) {", "  function feedAlertTick() {")

    def test_old_per_slot_toast_is_gone(self):
        self.assertNotIn('"RTSP source failed \\u2014 " + faultText(slot)', self.s)
        self.assertNotIn("slot.toasted = true;", self.s)
        self.assertIn("const FEED_ALERT_AGAIN = 5, FEED_ALERT_GROUP_MS = 3000, FEED_ALERT_NAMES = 3;", self.s)

    def test_count_lives_on_the_entry(self):
        t = self.tick
        self.assertIn("const a = slot.entry;", t)
        self.assertIn("if (st.tries >= FEED_ALERT_AGAIN && (a.alertN || 0) < 2) {", t)
        self.assertIn("} else if (st.tries >= 1 && !a.alertN) {", t)
        self.assertIn("a.alertN = 0; a.alertSlotFails = 0;", t)                  # back -> starts over
        self.assertIn("if (!slot.native && !slot.alertCounted && slotFailed(slot)) { slot.alertCounted = true; a.alertSlotFails = (a.alertSlotFails || 0) + 1; }", t)
        self.assertIn("if (!slot.rtsp || slot.feed?.ingest) continue;", t)       # an RTMP ingest waiting for its device is not a fault
        self.assertIn("if (rtspSuspended) { feedAlertQ.length = 0; return; }", t)  # the box's cameras switched off

    def test_attempts(self):
        st = self.state
        self.assertIn("if (pi && (pi.parked || pi.needsToken || pi.standby || pi.suspended)) return { down: false, tries: 0, ok: false };", st)
        self.assertIn("const down = !!a.evicted || !!(pi && pi.running === false && (pi.restarts || 0) > 0);", st)
        self.assertIn("return { down, tries, ok: !down && !!pi?.running && (pi.restarts || 0) === 0 };", st)
        self.assertIn("const tries = Math.max(a.retries || 0, a.alertSlotFails || 0);", st)
        self.assertIn("if (slot.monitorLoaded) return { down: false, tries: 0, ok: true };", st)

    def test_one_grouped_notice(self):
        f = self.flush
        self.assertIn("const q = feedAlertQ.splice(0);", f)
        self.assertIn('first.length + " cameras are offline (" + names(first) + ")"', f)
        self.assertIn('" still failing after " + FEED_ALERT_AGAIN + " tries (" + names(still) + ")"', f)
        self.assertIn("KASTR keeps retrying quietly", f)
        self.assertEqual(f.count("window.__toast?.("), 1)
        self.assertIn("if (feedAlertQ.length && now - feedAlertQ[0].at >= FEED_ALERT_GROUP_MS) feedAlertFlush();", self.tick)

    def test_rule_simulated(self):
        """The tick's rule on a camera's tries over time (mirrors feedAlertTick): alerts at try 1 and 5 only."""
        def run(seq):
            n, said = 0, []
            for tries, down, ok in seq:
                if ok:
                    n = 0
                    continue
                if not down:
                    continue
                if tries >= 5 and n < 2:
                    n = 2
                    said.append(("still", tries))
                elif tries >= 1 and not n:
                    n = 1
                    said.append(("first", tries))
            return said
        forever = [(t, True, False) for t in range(1, 40)]
        self.assertEqual(run(forever), [("first", 1), ("still", 5)])
        back = forever[:7] + [(0, False, True)] + [(t, True, False) for t in range(1, 3)]
        self.assertEqual(run(back), [("first", 1), ("still", 5), ("first", 1)])   # a later failure starts over
        late = [(12, True, False), (13, True, False)]                               # a page opened on a long outage
        self.assertEqual(run(late), [("still", 12)])

    def test_row_still_shows_the_live_state(self):
        # the badge keeps its word; the row's status line (the 0.21.91 camrow work) carries the reason and the try now
        st = between(self.s, "  function slotStatus(slot) {", "  // The echo can appear or vanish with no publish-side event")
        self.assertIn('const att = (slot.entry.retries || 0) > 0 ? "retrying (try " + (slot.entry.retries + 1) + ")" : "";', st)
        self.assertIn('return { text: "failed" + (why || att ? " — " + [why, att].filter(Boolean).join("; ") : ""), cls: "warn", onair: false }; }', st)
        self.assertIn('if (!slot.moq) return { text: "connecting…" + (att ? " — " + att : ""), cls: "", onair: false };', st)
        self.assertIn('sf.textContent = full !== short ? full : ""; sf.hidden = full === short;', self.s)

    def test_reason_without_ffmpeg_noise(self):
        r = between(self.s, "  function feedAlertReason(slot) {", "  function feedAlertState(slot) {")
        self.assertIn('.replace(/\\[[^\\]]* @ [0-9a-fx]+\\]\\s*/gi, "").replace(/\\?[^ \\/]*/g, "")', r)
        import re
        s = ("ffmpeg: [tcp @ 000001e73ffb3f00] Connection to tcp://127.0.0.1:18555?timeout=10000000 failed: Error number -138 occurred"
             " / [in#0 @ 0000021025084d80] Error opening input: Error number -138 occurred")
        out = re.sub(r"\?[^ /]*", "", re.sub(r"\[[^\]]* @ [0-9a-fx]+\]\s*", "", s, flags=re.I))   # the same two expressions
        self.assertEqual(out.split(" / ")[0], "ffmpeg: Connection to tcp://127.0.0.1:18555 failed: Error number -138 occurred")

    def test_badge_word_of_the_new_texts(self):
        def short(t):   # mirrors camBadgeShort
            x = str(t or "").split(" — ")[0].split(" · ")[0].strip()
            return x or str(t or "")
        self.assertEqual(short("failed — Connection refused; retrying (try 8)"), "failed")
        self.assertEqual(short("connecting… — retrying (try 3)"), "connecting…")


class FakeBridge:
    def __init__(self):
        self.lines = []

    def log(self, m, *a, **k):
        self.lines.append(str(m))


class PairLog(unittest.TestCase):
    def pub(self):
        p = kastr_rtsp.Publisher.__new__(kastr_rtsp.Publisher)
        p.bridge = FakeBridge()
        p.broadcast = "yard/box/cam.hang"
        p._gen = 1
        p.restarts = 0
        return p

    def fail_forever(self, p, n, t0=1000.0, step=30.0, monkey=None):
        now = [t0]
        saved = kastr_rtsp.time.time
        kastr_rtsp.time.time = lambda: now[0]
        try:
            for r in range(n):
                p.restarts = r
                p._lq_line("rtsp pair %s gen=%d start restarts=%d" % (p.broadcast, r + 1, r), r, "start")
                p._lq_line("rtsp pair %s gen=%d exit who=ffmpeg code=1 lived=0.5s restarts=%d" % (p.broadcast, r + 1, r), r, "exit")
                now[0] += step
        finally:
            kastr_rtsp.time.time = saved

    def test_first_and_fifth_try_then_a_summary(self):
        p = self.pub()
        self.fail_forever(p, 60)                                   # 60 tries 30 s apart: 30 minutes
        lines = p.bridge.lines
        full = [ln for ln in lines if " gen=" in ln and (" start " in ln or " exit " in ln) and "still failing" not in ln]
        self.assertEqual([ln.split(" gen=")[1].split(" ")[0] for ln in full], ["1", "1", "5", "5"])
        self.assertEqual(sum("still failing after 5 tries" in ln for ln in lines), 1)
        summaries = [ln for ln in lines if "still failing --" in ln]
        self.assertEqual(len(summaries), 2)                         # one per 10 minutes, not one per try
        self.assertIn("failed tries since", summaries[0])
        self.assertLess(len(lines), 10)

    def test_streaming_again_says_so_and_starts_over(self):
        p = self.pub()
        self.fail_forever(p, 3)
        p.restarts = 3
        p._lq_back()
        self.assertTrue(p.bridge.lines[-1].endswith("streaming again after 3 failed tries"))
        n = len(p.bridge.lines)
        p._lq_back()                                                # once
        self.assertEqual(len(p.bridge.lines), n)
        p.restarts = 0
        p._lq_line("rtsp pair x gen=9 start restarts=0", 0, "start")
        self.assertEqual(p.bridge.lines[-1], "rtsp pair x gen=9 start restarts=0")

    def test_a_working_pair_logs_as_before(self):
        p = self.pub()
        p._lq_line("start", 0, "start")
        p._lq_back()                                                # flowing: nothing to say
        p._lq_line("exit after an hour", -1, "exit")
        p._lq_line("start again", 0, "start")
        self.assertEqual(p.bridge.lines, ["start", "exit after an hour", "start again"])

    def test_wired_into_the_pair(self):
        with open(os.path.join(HERE, "kastr_rtsp.py"), encoding="utf-8") as f:
            s = f.read()
        self.assertIn('self._lq_line(start_line, start_r, "start")', s)
        self.assertIn('self._lq_line(exit_line, exit_r, "exit")', s)
        self.assertIn("exit_r = -1 if lived > 60 else self.restarts", s)
        self.assertIn("                                self._lq_back()   # 0.21.91", s)
        self.assertEqual((kastr_rtsp.LOG_QUIET_AFTER, kastr_rtsp.LOG_QUIET_SUMMARY_S), (5, 600))


if __name__ == "__main__":
    unittest.main()
