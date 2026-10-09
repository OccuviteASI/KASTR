# -*- coding: utf-8 -*-
"""v0.21.38 (Kenton): a chat tone of its own, the Gallery button only in full screen / Fill window (icon until hovered),
and the launch auto-pick keeps the saved access codes."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class ChatToneGallery(unittest.TestCase):
    def setUp(self):
        self.p = _read("moq-watch-lite.html")

    def test_chat_tone_is_not_the_join_chime(self):
        self.assertIn("function chatTone() {", self.p)
        self.assertIn("[[1174.66, 0], [1567.98, 0.09]]", self.p)   # not the C-E-G triad of chimeTone
        self.assertIn('if (n > was && chatRoom && joinState === "joined" && Date.now() - chatBoundAt > 6000) { try { chatTone(); } catch {} }', self.p)

    def test_gallery_button_only_when_filled(self):
        self.assertIn('stageBack.classList.toggle("show", !gridMode && stageFullscreen());', self.p)
        self.assertIn("#stageBack .gl { display:none; }", self.p)
        self.assertIn('<button class="opt" id="viewGallery"', self.p)   # still in the View options

    def test_auto_pick_keeps_codes(self):
        self.assertIn("await gateRelayApply(best.url, { keepCodes: true });", self.p)
        self.assertIn("if (!opts?.keepCodes) {", self.p)


if __name__ == "__main__":
    unittest.main()
