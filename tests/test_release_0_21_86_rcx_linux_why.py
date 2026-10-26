# -*- coding: utf-8 -*-
"""0.21.86 (Kenton: a Linux relay with unattended control on showed "nobody is signed in" and a greyed Control): every X11
reason was folded into "nosession". The real one now reaches the hub and its Machines table."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_rcadmin as ra  # noqa: E402
import kastr_x11  # noqa: E402


class LinuxReasons(unittest.TestCase):
    def test_x11_reasons_kept(self):
        for why in ("no-display", "no-x11", "no-xtest", "wayland"):
            with mock.patch.object(ra, "LINUX", True), mock.patch.object(ra, "WINDOWS", False), \
                    mock.patch.object(kastr_x11, "available", return_value=(False, why)):
                self.assertEqual(ra._desktop_state(), {"ok": False, "why": why})
                self.assertEqual(ra.clean_desktop({"ok": False, "why": why}), {"ok": False, "why": why})
        self.assertEqual(ra.clean_desktop({"ok": False, "why": "made-up"})["why"], "unsupported")

    def test_pages_word_them(self):
        with open(os.path.join(HERE, "relay.html"), encoding="utf-8") as f:
            r = f.read()
        self.assertIn('"no-display": "KASTR runs without a desktop display"', r)
        self.assertIn("RCX_DESK[m.desktop?.why] ||", r)
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            p = f.read()
        self.assertIn('w === "no-display" ? "KASTR runs without a desktop display on " + rcxName(m)', p)
        with open(os.path.join(HERE, "kastr_rcadmin.py"), encoding="utf-8") as f:
            self.assertIn('"no-display": "KASTR on %s runs without a desktop display (no DISPLAY)', f.read())


if __name__ == "__main__":
    unittest.main()
