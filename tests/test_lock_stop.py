"""0.21.41: a locked computer stops screen / window / tab shares; they never come back by themselves; boxes are exempt.

Run: python -m unittest discover -s tests
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kastr_lock   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class Host(unittest.TestCase):
    def test_answers_true_false_or_none(self):
        kastr_lock._cache["at"] = 0
        self.assertIn(kastr_lock.locked(), (True, False, None))

    def test_unknown_platform_is_none(self):
        kastr_lock._cache["at"] = 0
        with mock.patch.object(kastr_lock.sys, "platform", "darwin"):
            self.assertIsNone(kastr_lock.locked())
        kastr_lock._cache["at"] = 0

    def test_windows_struct_is_aligned(self):
        self.assertIn('("Level", wintypes.DWORD), ("pad", wintypes.DWORD), ("Data", WTSINFOEX_LEVEL1)', _read("kastr_lock.py"))

    def test_local_only_route_and_build(self):
        src = _read("kastr_serve.py")
        i = src.index('if path == "/api/lockstate":')
        self.assertIn('return self._deny("session state")', src[i:i + 300])
        self.assertIn('"--hidden-import", "kastr_lock"', _read("build.py"))


class Page(unittest.TestCase):
    def test_only_screen_captures_and_not_on_boxes(self):
        p = _read("moq-watch-lite.html")
        body = p[p.index("  async function lockTick() {"):p.index("  setInterval(lockTick, 2000);")]
        self.assertIn('if (["publisher", "publisher-relay"].includes(window.__pageMode?.())) return;', body)
        self.assertIn("for (const a of added.filter(isScreenShare)) { try { removeSource(a.id); } catch {} }", body)
        self.assertIn("const isScreenShare = (a) => a.kind === SCREEN || (a.kind === RTSP && (a.screen || isScreenUrl(a.url)));", p)


if __name__ == "__main__":
    unittest.main()
