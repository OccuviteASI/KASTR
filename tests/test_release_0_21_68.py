"""v0.21.68: the Relay page's Pull test shows the moq tool's last line without terminal colour codes.

Run: python -m unittest discover -s tests
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PullTestText(unittest.TestCase):
    def test_colour_codes_stripped(self):
        with open(os.path.join(HERE, "kastr_relay.py"), encoding="utf-8") as f:
            src = f.read()
        i = src.index("# 0.21.68: no terminal colour codes")
        line = src[src.rindex(chr(10), 0, i):i]
        pat = re.search(r're\.sub\(r"(.*?)", ""', line).group(1)
        self.assertNotIn(chr(27), line)
        raw = chr(27) + "[2m2026-10-15T02:34:59Z" + chr(27) + "[0m " + chr(27) + "[32m INFO" + chr(27) + "[0m subscribe started"
        self.assertEqual(re.sub(pat, "", raw), "2026-10-15T02:34:59Z  INFO subscribe started")


if __name__ == "__main__":
    unittest.main()
