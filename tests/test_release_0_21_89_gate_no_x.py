"""0.21.89 (Kenton: "remove the x in the corner of the Join room page", then "remove escape too"): the Join room gate
has no close button and Escape no longer puts it away."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page():
    with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


class GateIsNotDismissible(unittest.TestCase):
    def test_no_close_button_style_or_handler(self):
        self.assertNotIn("joinGateClose", page())

    def test_escape_no_longer_hides_the_gate(self):
        s = page()
        self.assertNotIn('e.key === "Escape" && !joinEls.joinGate.hidden', s)
        self.assertIn("the gate is no\n    // longer dismissible", s.replace("\r\n", "\n"))


class GateHeadingNamesThePickedRoom(unittest.TestCase):
    def test_heading_follows_the_list_before_joining(self):
        s = page()
        self.assertIn("function gateHeadingSlug(cur, joined)", s)
        self.assertIn('sel !== "__new" && lastChannelList.some((r) => r.slug === sel)) ? sel : cur', s)
        self.assertIn("gateHeadingTitle(gateHeadingSlug(c, joined))", s)   # 0.21.96: gateHeadingTitle = roomTitle, "No room" for a box's home
        self.assertIn('gateHeadingTitle(gateHeadingSlug(readChannel(), joinState === "joined"))', s)


if __name__ == "__main__":
    unittest.main()
