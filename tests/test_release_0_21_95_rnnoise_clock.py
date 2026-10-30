"""0.21.95 (Kenton 2026-10-30: "I'm still getting a crackling when using the background noise removal"). Cause: 0.21.66 put the
RNNoise context on a timer clock (sinkId none) while the publish library's capture context, which reads the filtered track, runs on
the output device's clock. Lab (fake mic playing speech, lab copies of both contexts): with sinkId none the capture got 10 ms holes
of silence every few seconds, and once the timer clock fell behind for good (27 s rendered in 40 s, ~900 holes = steady crackle);
on the device clock 0 holes in 8 of 8 runs, idle and with a busy page. The Bluetooth freeze sinkId none answered is the guard's:
a stopped clock, or one 3 % off real time for 10 s, rebuilds the filter -- once a minute, not once a session."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RnnoiseClock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            cls.p = f.read()

    def sec(self, start, end):
        i = self.p.index(start)
        return self.p[i:self.p.index(end, i)]

    def test_filter_context_uses_the_output_device_clock(self):
        e = self.sec("  async function ensureDenoise() {", "  function denoiseNode(d) {")
        self.assertIn('denoiseCtx = new AudioContext({ sampleRate: 48000, latencyHint: "interactive" });', e)
        self.assertNotIn("sinkId: {", e)
        self.assertIn('if (denoiseCtx.state !== "running") denoiseCtx.resume()', e)

    def test_guard_catches_a_drifting_clock(self):
        g = self.sec("  function denoiseGuard(slot, ctx, src, node) {", "  function stopDenoise(")
        self.assertIn("const rate = (t - base.t) / ((p - base.p) / 1000); off = Math.abs(rate - 1) > 0.03 ? off + 1 : 0;", g)
        self.assertIn("if (frozen < 2 && silent < 3 && off < 2) return;", g)
        self.assertIn("% of real time", g)
        # muted: the baseline restarts, so a long mute never reads as drift
        self.assertIn("frozen = silent = off = 0; lastT = ctx.currentTime; base = { t: lastT, p: performance.now() };", g)
        self.assertIn("if (!base) base = { t, p };", g)   # the first 5 s window starts after start-up

    def test_rebuild_once_a_minute(self):
        g = self.sec("  function denoiseGuard(slot, ctx, src, node) {", "  function stopDenoise(")
        self.assertIn("if (!slot.dnRebuilt || performance.now() - slot.dnRebuilt > 60000) {", g)
        self.assertIn("slot.dnRebuilt = performance.now();", g)
        self.assertIn("denoiseFail(why);", g)


if __name__ == "__main__":
    unittest.main()
