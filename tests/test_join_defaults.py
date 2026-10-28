# -*- coding: utf-8 -*-
"""v0.21.34 (Kenton): the join card has no room question (main the first time, the last room after that), the fleet's
relays are always in the relay lists, and the rail's resize grip never shows without a rail (Fill window, full screen)."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class JoinDefaults(unittest.TestCase):
    def test_no_room_question(self):
        p = _read("moq-watch-lite.html")
        self.assertIn('<label class="f" id="joinRoomRow" hidden><span>Room</span>', p)
        self.assertIn(': lj && lj.room ? channelSlug(lj.room) : "main");   // 0.21.34: main the first time', p)
        # a locked last room without its saved code -> main, never a failed join
        self.assertIn('if (want !== invited && wantRec?.locked && !(lj && channelSlug(lj.room) === want && lj.code)) want = "main";', p)

    def test_fleet_relays_listed(self):
        # 0.21.93 (Kenton: "remove the built-in relay addresses"): the fleet's relays in the lists are the hub's (cached after the
        # access code) plus the web address -- no relay IPs ship in the page any more
        b = _read("assets/asi-brand.js")
        for ip in ("10.10.105.190", "10.13.20.196", "10.126.104.2", "10.11.252.203"):
            self.assertNotIn(ip, b)
        self.assertNotIn("__KASTR_KNOWN_RELAYS", b)
        self.assertIn('const d = JSON.parse(localStorage.getItem("kastr.relays.fleet") || "null");', b)
        self.assertIn("const list = [...recent, ...fl.map((f) => f.url).filter((u) => !recent.includes(u))];", b)
        p = _read("moq-watch-lite.html")
        self.assertNotIn("__KASTR_KNOWN_RELAYS", p)
        self.assertIn("for (const [u, nm] of [[cur], ...hist.map((h) => [h]), ...fl, [WEB_RELAY]]) {", p)

    def test_no_grip_without_a_rail(self):
        p = _read("moq-watch-lite.html")
        self.assertIn('railGrip.style.display = (gridMode || ownPip || railOff || phoneStrip || stageMosaic?.railGone) ? "none" : "block";', p)
        self.assertIn('railPager.style.gridColumn = rcols === 2 ? RC0 + " / span 2" : String(RC0);', p)


if __name__ == "__main__":
    unittest.main()
