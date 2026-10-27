"""0.21.91 (Kenton: "When messaging someone I don't have the ability to select their message and copy content out of it"):
the page turns text selection off everywhere except listed places; the text of messages in Messages is now one of them."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MessagesSelectable(unittest.TestCase):
    def test_message_text_selects(self):
        with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
            s = f.read()
        self.assertIn("body { -webkit-user-select:none; user-select:none; }", s)
        self.assertIn(".mlog .mtxt, .mlog .mtxt *, .mlog .mwho, .mlog .msys { -webkit-user-select:text; user-select:text; cursor:text; }", s)
        # after the page-wide "none", so it wins
        self.assertLess(s.index("body { -webkit-user-select:none; user-select:none; }"), s.index(".mlog .mtxt, .mlog .mtxt *"))


if __name__ == "__main__":
    unittest.main()
