"""0.21.91 (Kenton saw "KASTR sharing" bars on his desktop while test suites ran): no test run ever shows a real window."""
import unittest

import kastr_overlay as ko


class NoDesktopWindowsUnderTests(unittest.TestCase):
    def test_guard_is_on(self):
        self.assertTrue(ko.under_tests())

    def test_overlays_refuse(self):
        self.assertFalse(ko.ShareOverlay().start(monitor_rect=(0, 0, 100, 100), label="screen"))
        self.assertFalse(ko.PointerOverlay("Bob").start())
        import kastr_point
        self.assertFalse(kastr_point.WinRipples().start() if hasattr(kastr_point, "WinRipples") else False)


if __name__ == "__main__":
    unittest.main()
