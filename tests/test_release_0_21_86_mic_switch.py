# -*- coding: utf-8 -*-
"""0.21.86 (Kenton: "When switching between noise isolation options it will stop my mic from working and I have to mute and
unmute to get it working again"): leaving RNNoise stopped the filtered track while it still fed the encoder; a constraint
change re-opened the mic under a restored stale track. The mic now goes in before the filter is taken apart, and for a few
seconds after a switch the encoder follows the live microphone track."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MicSwitch(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.p = f.read()

    def test_the_mic_goes_in_before_the_filter_comes_apart(self):
        p = self.p
        i_set = p.index('if (live) { try { pubAud(slot.publish)?.source.set({ track: live, kind: "voice" }); } catch {} }')
        i_stop = p.index("setTimeout(dismantle, 400);")
        self.assertLess(i_set, i_stop)
        body = p[p.index("function stopDenoise("):p.index("function micFollow(")]
        self.assertEqual(body.count("v.processed.stop()"), 1)   # only inside dismantle

    def test_the_encoder_follows_the_live_mic_after_a_switch(self):
        p = self.p
        self.assertIn("function micFollow(slot, ms = 6000) {", p)
        self.assertIn('if (!dev || dev.readyState !== "live") return;   // the mic is re-opening', p)
        self.assertIn("if (mode === \"rnnoise\") applyDenoise(s2); else { stopDenoise(s2); micFollow(s2); }", p)


if __name__ == "__main__":
    unittest.main()


class PointingClicks(unittest.TestCase):
    """0.21.86 (Kenton: people pointing on his shared screen "are clicking on my screen and it is doing the normal zoom in/out
    instead of just showing me the clicks")."""

    def test_a_pointing_click_on_the_stage_is_only_a_sonar(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            p = f.read()
        self.assertIn("if (rcIn(p)) { ptClick(name, p); if (name === selectedName) pane.__ptAt = Date.now(); }", p)
        self.assertIn('pane.addEventListener("click", ptSwallow, true);', p)
        self.assertIn('pane.addEventListener("dblclick", ptSwallow, true);', p)
        self.assertIn("e.stopImmediatePropagation(); e.preventDefault();", p[p.index("const ptSwallow"):p.index("const ptSwallow") + 300])
