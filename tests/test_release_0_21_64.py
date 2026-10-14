"""0.21.64 wiring (Kenton, 2026-10-14): viewer-code members see Share / Camera / Mic greyed with the reason; an app whose
check-in fails learns the relay's KASTR web port and logs it; the Relay page says "not reporting" instead of "older KASTR";
the rooms rail's speaking rings clear when the meter loop stops.

Run: python -m unittest discover -s tests
"""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(p):
    with open(os.path.join(HERE, p), encoding="utf-8") as f:
        return f.read()


class ViewOnly(unittest.TestCase):
    def test_buttons_greyed_for_viewer_tokens(self):
        p = read("moq-watch-lite.html")
        self.assertIn('const VIEW_ONLY_BTNS = ["topCamBtn", "topCamChev", "topMicBtn", "topMicChev", "shareBtn"];', p)
        self.assertIn('const vo = authRole === "viewer";', p)
        self.assertIn("body.viewonly #topCamBtn", p)
        self.assertIn('window.addEventListener("kastr:auth", paintViewOnly);', p)


class CheckIn(unittest.TestCase):
    def test_failed_checkin_learns_the_web_port_and_says_so(self):
        k = read("kastr.py")
        self.assertIn("if learn_hub_web_host(host, relay, ini, budget=3.0):", k)
        self.assertIn('note("check-in with the relay %s failed (%s): %s', k)

    def test_relay_page_says_not_reporting(self):
        r = read("relay.html")
        self.assertIn(">not reporting</span>", r)
        self.assertNotIn(">older KASTR</span>", r)


class RailRings(unittest.TestCase):
    def test_rings_cleared_when_the_meter_loop_stops(self):
        p = read("moq-watch-lite.html")
        self.assertIn("else { sbTalkAt = 0; sbTalkPaint(nowMs); }", p)
        self.assertIn("if (!micOpen) { talkLoud = 0; talkLastLoud = 0; talkApply(false); return; }", p)


if __name__ == "__main__":
    unittest.main()
