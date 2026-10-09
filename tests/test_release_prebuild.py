# -*- coding: utf-8 -*-
"""v0.21.32 (Kenton: "Why can't the app download be readily available instead of having to prepare it?" ... "Only to
boxes that serve the webpage"): a host that serves the web page keeps both install zips of its version ready."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_release as kr  # noqa: E402


def _st(ready=False, building=False, can=True):
    return {"ready": ready, "building": building, "can": can}


class Prebuild(unittest.TestCase):
    def tick(self, states):
        started = []
        with mock.patch.object(kr, "status", side_effect=lambda plat, *a, **k: states[plat]), \
                mock.patch.object(kr, "prepare", side_effect=lambda plat, *a, **k: started.append(plat)):
            out = kr.prebuild_tick("0.21.32", "/state")
        return out, started

    def test_one_zip_at_a_time(self):
        out, started = self.tick({"win32": _st(), "linux": _st()})
        self.assertEqual(out, "building")
        self.assertEqual(len(started), 1)

    def test_the_second_waits_for_the_first(self):
        out, started = self.tick({"win32": _st(building=True), "linux": _st()})
        self.assertEqual((out, started), ("building", []))

    def test_next_one_starts_when_the_first_is_done(self):
        out, started = self.tick({"win32": _st(ready=True), "linux": _st()})
        self.assertEqual((out, started), ("building", ["linux"]))

    def test_ready_and_waiting(self):
        self.assertEqual(self.tick({"win32": _st(ready=True), "linux": _st(ready=True)}), ("ready", []))
        self.assertEqual(self.tick({"win32": _st(ready=True), "linux": _st(can=False)}), ("waiting", []))

    def test_only_a_host_that_serves_the_page(self):
        with open(os.path.join(HERE, "kastr.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("    if kastr_serve.LAN_OK:   # 0.21.32: a box that serves the web page keeps its install downloads ready", src)
        self.assertIn("_krel.start_prebuilder(state_dir(), kastr_serve.read_version, log=note,", src)
        self.assertIn("enabled=lambda: not kastr_serve.web_page_off())", src)   # Web clients off -> nothing to prepare


if __name__ == "__main__":
    unittest.main()
