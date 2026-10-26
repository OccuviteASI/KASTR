"""0.21.89 (Kenton: "remove the x in the corner of the Join room page"): the Join room gate has no close button any more;
Escape still puts it away on a relay-only machine."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page():
    with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


class GateHasNoCloseX(unittest.TestCase):
    def test_no_close_button_style_or_handler(self):
        self.assertNotIn("joinGateClose", page())

    def test_escape_still_puts_the_gate_away(self):
        s = page()
        self.assertIn('e.key === "Escape" && !joinEls.joinGate.hidden', s)
        self.assertIn('joinState === "prejoin" && !rejoinRec) gateHide();', s)


if __name__ == "__main__":
    unittest.main()
