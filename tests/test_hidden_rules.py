"""0.21.40: elements the scripts hide with `hidden` must have a [hidden] rule when an author rule sets `display`.

Run: python -m unittest discover -s tests
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class HiddenRules(unittest.TestCase):
    def test_chat_strip_emoji_and_file_warning_hide(self):
        self.assertIn(".row[hidden], .catt[hidden], .cemoji[hidden] { display:none; }", _read("moq-watch-lite.html"))

    def test_download_tiles_hide(self):
        self.assertIn("a.card[hidden] { display:none; }", _read("index.html"))


if __name__ == "__main__":
    unittest.main()
