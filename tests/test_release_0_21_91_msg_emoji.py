"""0.21.91 (Kenton: "messages should allow for the emojis to be used"): the Messages composer has the Room Chat emoji grid;
a pick goes in at the cursor, sending or Escape closes the grid."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class MessagesEmoji(unittest.TestCase):
    def test_page_shares_the_chat_grid(self):
        s = read("moq-watch-lite.html")
        self.assertIn("window.__kastrEmoji = CHAT_EMOJI;", s)
        self.assertIn("emoji: () => window.__kastrEmoji || [],", s)
        self.assertIn(".memogrid { flex:none; display:grid; grid-template-columns:repeat(8, 1fr);", s)

    def test_composer_button_and_grid(self):
        s = read("assets/kastr-msg.js")
        self.assertIn('<div class="memogrid" hidden></div>', s)
        self.assertIn('<button type="button" class="memo" title="Emoji">', s)
        self.assertIn("for (const ch of (K.emoji?.() || []))", s)
        self.assertIn("ta.value = ta.value.slice(0, st) + ch + ta.value.slice(en);", s)
        self.assertIn('if (e.key === "Escape" && !eg.hidden)', s)
        self.assertIn('pane.querySelector(".memogrid").hidden = true;', s)
        # the order in the composer: emoji, attach, the box, send
        i = s.index('class="memo"'); j = s.index('class="mattach"', i); k = s.index('class="mcin"', j); m = s.index('class="msend"', k)
        self.assertTrue(i < j < k < m)


if __name__ == "__main__":
    unittest.main()
