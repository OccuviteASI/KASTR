"""0.21.41: the room rail's people -- alphabetical, a hide switch, a speaking ring around the name, the person's menu.

Run: python -m unittest discover -s tests
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _page():
    with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


class RailPeople(unittest.TestCase):
    def test_alphabetical(self):
        p = _page()
        self.assertIn('const sorted = [...rec.members].sort((a, b) => String(a.name || a.op).localeCompare(String(b.name || b.op), undefined, { sensitivity: "base" }));', p)
        self.assertIn("ul.appendChild(li);   // in name order (an existing row moves)", p)

    def test_hide_switch_is_remembered(self):
        p = _page()
        self.assertIn('id="sbPeopleTog"', p)
        self.assertIn('localStorage.getItem("kastr.rail.people") === "off"', p)
        self.assertIn("body.sb-nopeople .sbcard .sbmembers { display:none; }", p)

    def test_speaking_ring_follows_what_this_window_hears(self):
        p = _page()
        self.assertIn(".sbcard .sbm.talk .nm { box-shadow:0 0 0 1.5px var(--asi-blue);", p)
        self.assertIn("sbTalkPaint(nowMs);   // 0.21.41", p)
        body = p[p.index("  function sbTalkPaint(nowMs) {"):p.index("  // 0.21.41: the rail's person")]
        self.assertIn("nowMs < (t.talkUntil ?? 0)", body)

    def test_menu_from_the_rail(self):
        p = _page()
        self.assertIn("sbMemberMenu(li, pointAnchor(e.clientX, e.clientY))", p)
        body = p[p.index("  function sbMemberMenu(li, anchor) {"):p.index("  function sbMemberMenu(li, anchor) {") + 400]
        self.assertIn("participantMenu(p, anchor)", body)


    def test_meta_beside_the_name_when_it_fits(self):
        p = _page()
        self.assertIn('head.append(nm, meta);', p)
        self.assertIn(".sbcard .sbhd { flex:1; min-width:0; display:flex; flex-wrap:wrap;", p)

    def test_create_room_is_a_circled_plus_in_the_header(self):
        p = _page()
        self.assertIn('id="sbCreateHd" class="sbppl sbnew" title="Create a room"', p)
        self.assertIn('hb.innerHTML = icon("plusc");', p)
        self.assertIn("body.sb-collapsed .sbfoot { display:block; }", p)


class ZoomControls(unittest.TestCase):
    def test_small_buttons_and_the_percent_only_while_zooming(self):
        p = _page()
        self.assertIn(".zoomctl button { min-width:20px; height:20px;", p)
        self.assertIn(".zoomctl .zpct { display:none;", p)
        self.assertIn('ctl.__zchgT = setTimeout(() => ctl.classList.remove("zchg"), 1500);', p)


if __name__ == "__main__":
    unittest.main()
