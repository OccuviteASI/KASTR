"""0.21.91 (Kenton: "In the streams menu, I would like to be able to right-click for the options and not just the
ellipsis."): a Streams row's context menu opens the same actions as its ... button, at the pointer."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class StreamsRightClick(unittest.TestCase):
    def test_contextmenu_opens_the_actions(self):
        with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
            s = f.read()
        i = s.index('row.addEventListener("contextmenu", (ev) => {\n        const e = libCat.get(el.dataset.path);'.replace("\n", os.linesep if False else "\n"))
        body = s[i:i + 900]
        self.assertIn("ev.preventDefault();", body)
        self.assertIn("libActOpen(e, {", body)
        self.assertIn("getBoundingClientRect: () => ({ left: x, right: x + w, top: y, bottom: y })", body)
        self.assertIn("closest: (sel) => row.closest(sel)", body)


if __name__ == "__main__":
    unittest.main()
