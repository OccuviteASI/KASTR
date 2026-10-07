import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class RnnoiseDefault(unittest.TestCase):
    """0.21.23 (Kenton): background noise removal (RNNoise) is on by default; a saved choice is kept."""

    def setUp(self):
        self.page = _read("moq-watch-lite.html")

    def test_unset_mode_defaults_to_rnnoise(self):
        self.assertIn('every((e) => e.value === "off") ? "off" : "rnnoise";', self.page)
        self.assertIn('micMode = localStorage.getItem(MIC_MODE_KEY) || ""', self.page)

    def test_a_failure_does_not_save_the_fallback(self):
        self.assertIn('setMicMode("browser", false)', self.page)
        self.assertIn("if (persist) try { localStorage.setItem(MIC_MODE_KEY, mode); }", self.page)

    def test_switching_suppression_back_on_returns_to_rnnoise(self):
        self.assertIn('document.getElementById("nsRnnoise").checked = mode !== "browser";', self.page)
        self.assertIn('setMicMode(on ? (micMode === "browser" ? "browser" : "rnnoise") : "off")', self.page)


if __name__ == "__main__":
    unittest.main()
