"""0.21.91 (Kenton: "Let's rename 'Chat' to 'Room Chat'. This should remove any ambiguity when seeing Chat and Messages right
next to each other.")."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RoomChatLabel(unittest.TestCase):
    def test_button_panel_and_pin_name(self):
        with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
            s = f.read()
        self.assertIn('tbHtml("chat", "Room Chat")', s)
        self.assertIn('<div class="head"><span>Room Chat</span><span id="chatRoomLbl"', s)
        self.assertIn('name: "Room Chat", fl: 1.4', s)
        self.assertNotIn('tbHtml("chat", "Chat")', s)


if __name__ == "__main__":
    unittest.main()
