"""0.21.93: the rail room badge's lock + kept-open discs carry their own ink.

Kenton (lime theme): the icons on the left of the room he was in showed black -- the discs are var(--surface)
and took the current badge's var(--on-accent) colour, which is dark on light accents.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RailIcons(unittest.TestCase):
    def test_lock_and_keep_have_own_colour(self):
        with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
            page = f.read()
        for cls in ("lk", "kp"):
            m = re.search(r"\.rb \." + cls + r" \{([^}]*)\}", page)
            self.assertIsNotNone(m, cls)
            self.assertIn("background:var(--surface)", m.group(1), cls)
            self.assertIn("color:var(--text)", m.group(1), cls)


if __name__ == "__main__":
    unittest.main()
