# -*- coding: utf-8 -*-
"""v0.21.74 (Kenton 2026-10-19: Mendon's grid "split into separate streams" and its room lost the play icon after a weekend
alone -- the box's KASTR kept its cameras on the air but its window was no longer drawing the grid or in the room; a relaunch
fixed it; he chose: build the safeguard). In the box modes the launcher reopens its window when the page stops reporting or
sits outside the box's room.

Run: python -m unittest discover -s tests
"""
import os
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr  # noqa: E402


class Reasons(unittest.TestCase):
    def test_report_reads_the_newest_box_page(self):
        now = 1000.0
        diag = {"/relay.html": {"page": "/relay.html", "_at": 999.0},
                "/moq-watch-lite.html?embed=1&v=1": {"page": "/moq-watch-lite.html?embed=1&v=1", "_at": 990.0, "watcher": {"joined": True}}}
        self.assertEqual(kastr.box_page_report(diag, now), (10.0, True))
        self.assertIsNone(kastr.box_page_report({"/relay.html": {"page": "/relay.html", "_at": 999.0}}, now))

    def test_reasons(self):
        r = kastr.box_keeper_reason
        self.assertIsNone(r(None, True, "mendon", 999))                         # never saw the page: nothing to judge
        self.assertIn("since the window opened", r(None, True, "", 0, since_open=200))   # a window whose page never came up
        self.assertIn("not reported", r((200.0, True), True, "mendon", 0))      # hung while the browser runs
        self.assertIsNone(r((200.0, True), False, "mendon", 0))                 # the browser is gone: supervise() handles that
        self.assertIn("out of room mendon", r((3.0, False), True, "mendon", 301))
        self.assertIsNone(r((3.0, False), True, "mendon", 200))                 # not long enough yet
        self.assertIsNone(r((3.0, False), True, "", 999))                       # left on purpose: no room saved
        self.assertIsNone(r((3.0, True), True, "mendon", 999))


class Loop(unittest.TestCase):
    class Proc:
        def __init__(self):
            self.dead = False

        def poll(self):
            return 0 if self.dead else None

    def run_keeper(self, reports, ticks):
        srv = type("S", (), {})()
        srv.diag_ref = {}
        launched = []
        proc_ref = [self.Proc()]
        it = iter(range(ticks))
        clock = [0.0]

        def sleep(_s):
            try:
                i = next(it)
            except StopIteration:
                return True
            clock[0] += 120.0
            srv.diag_ref.clear()
            srv.diag_ref.update(reports(i))
            return False

        def fake_launch(browser, url, page):
            launched.append(clock[0])
            return self.Proc()
        with mock.patch.object(kastr, "BOX_SETTLE_S", 0.0), \
                mock.patch.object(kastr, "launch", fake_launch), \
                mock.patch.object(kastr, "close_app_window", lambda *a, **k: None), \
                mock.patch.object(kastr, "browser_gone", lambda p: True), \
                mock.patch.object(kastr, "box_room", lambda: "mendon"), \
                mock.patch.object(kastr, "note", lambda *a: None), \
                mock.patch.object(kastr.time, "monotonic", lambda: clock[0]), \
                mock.patch.object(kastr.time, "time", lambda: clock[0]):
            kastr.KEEPER_PROC[0] = None
            kastr.box_keeper(srv, "chrome", "http://127.0.0.1:8001", "/app.html", proc_ref, "publisher-relay", sleep=sleep)
        kastr.KEEPER_PROC[0] = None
        return launched

    def test_a_box_out_of_its_room_is_reopened_at_most_three_times(self):
        out = lambda i: {"p": {"page": "/moq-watch-lite.html", "_at": 0.0 + 120.0 * (i + 1) - 1, "watcher": {"joined": False}}}
        launched = self.run_keeper(out, 60)
        self.assertEqual(len(launched), 3)
        self.assertTrue(all(b - a >= 600 for a, b in zip(launched, launched[1:])))   # once per 10 minutes

    def test_a_box_in_its_room_is_left_alone(self):
        ok = lambda i: {"p": {"page": "/moq-watch-lite.html", "_at": 120.0 * (i + 1) - 1, "watcher": {"joined": True}}}
        self.assertEqual(self.run_keeper(ok, 30), [])

    def test_other_modes_never_run_it(self):
        self.assertIsNone(kastr.box_keeper(None, "chrome", "u", "/", [None], "full", sleep=lambda s: True))

    def test_wiring(self):
        k = open(os.path.join(HERE, "kastr.py"), encoding="utf-8").read()
        self.assertIn("if mode in BOX_KEEP_MODES and not USER_BROWSER[0]:", k)
        self.assertIn("proc, started, died_at = KEEPER_PROC[0], time.monotonic(), None", k)
        self.assertIn("srv.diag_ref = DIAG_REF", open(os.path.join(HERE, "kastr_serve.py"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
