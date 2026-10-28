# -*- coding: utf-8 -*-
"""v0.21.92 BIGGER NEXT SLIDE + SWITCHES. Kenton: "I want the next slide to be bigger than it is currently" -- it starts at half
the live slide's width, its corner drags it (arrow keys too, double-click: half again), the size is remembered on this device
(kastr.pres.layout nx); the notes keep at least about three lines. And every on / off in the presenter view is a switch."""
import io
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def _read(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


JS = _read(os.path.join("assets", "kastr-pres.js"))


class NextSlide(unittest.TestCase):
    def test_half_the_live_slide(self):
        self.assertIn("const NX_DEF = 0.5, NX_MIN = 0.2, NX_MAX = 1;", JS)
        self.assertIn("nxW.cur = w; nxW.ar = ar; nxtApply();", JS)
        self.assertIn("#presView .nxt { position:relative; flex:none; width:var(--nxw, 200px); max-width:100%;", JS)

    def test_notes_keep_three_lines(self):
        self.assertIn("const notesMin = Math.max(90, Math.round(fs * 1.45 * 3 + 22));", JS)
        self.assertIn('$(".nxtbox").hidden = w < 64;', JS)

    def test_grip_remembered(self):
        self.assertIn('<span class="nxgrip" role="separator"', JS)
        self.assertIn('g.addEventListener("dblclick", (e) => { e.preventDefault(); delete LY.nx; layoutApply(); lySave(); paint(); });', JS)
        self.assertIn("LY.nx = Math.max(NX_MIN, Math.min(NX_MAX, Math.min(px, nxW.max || px) / nxW.cur));", JS)

    def test_prefs_sync_keeps_the_layout(self):
        wl = re.search(r"var WL = (/.*?/);", _read(os.path.join("assets", "prefs.js"))).group(1)
        self.assertIn(r"pres\.(layout|notesSize)$", wl)
        sv = _read("kastr_serve.py")
        self.assertIn(r"|pres\.(layout|notesSize)$|", sv)
        self.assertIn(r"|mainroom$|view\.hideMine$", sv)   # the page kept mainroom since 0.21.91; the app's store now does too


class Switches(unittest.TestCase):
    def test_every_on_off_is_a_switch(self):
        self.assertIn('function switchOf(cb) { const s = document.createElement("span"); s.className = "switch sm"; s.append(cb, document.createElement("i")); return s; }', JS)
        for label in ("Can control my mic and camera", "Audience muted", "Ask to speak"):
            self.assertRegex(JS, r'\.append\(switchOf\((cb|ac)\), document\.createTextNode\("%s"\)\);' % re.escape(label))
            self.assertNotRegex(JS, r'\.append\((cb|ac), document\.createTextNode\("%s"\)\);' % re.escape(label))
        self.assertIn("#presView .prow label.allow .switch { flex:none; }", JS)


if __name__ == "__main__":
    unittest.main()
