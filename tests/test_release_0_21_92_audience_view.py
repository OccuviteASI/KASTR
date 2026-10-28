# -*- coding: utf-8 -*-
"""v0.21.92 AUDIENCE VIEW. While a presentation is live an audience member's page shows only the presentation's camera(s) -- the
other cameras are left out AND unsubscribed (visible="never"); presenters and backstage still see everyone. The presenters'
"Audience can see each other" switch (on by default): off, audience members do not see each other's cameras anywhere (rail,
stage, custom grids) and Room Chat names them "Audience member". Templates: audSnap / audApply + rolesSnap / rolesApply.
NOTE: client-enforced only -- the relay still serves the streams and /api/chat keeps real names (see STATUS.md)."""
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def _read(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return f.read()


JS = _read(os.path.join("assets", "kastr-pres.js"))
HTML = _read("moq-watch-lite.html")


class AudienceView(unittest.TestCase):
    def test_page_hides_and_unsubscribes(self):
        self.assertIn("function presAudHidden(name, inGrid) {", HTML)
        self.assertIn("|| presAudHidden(name, false)", HTML)
        self.assertIn(".filter((k) => !presAudHidden(k, true));", HTML)
        self.assertIn("window.__presAudHide = (a) => {", HTML)

    def test_pres_feeds_the_page(self):
        self.assertIn('if (typeof window.__presAudHide !== "function") return;', JS)
        self.assertIn("try { window.__presAudHide(a); } catch (e) {", JS)

    def test_chat_anon(self):
        self.assertIn('who.textContent = anon ? "Audience member" : m.name || m.op || "someone";', HTML)
        self.assertIn('presAnon(m.op) ? "Audience member"', HTML)


class SeeSwitch(unittest.TestCase):
    def test_switch_and_rig(self):
        self.assertIn('document.createTextNode("Audience can see each other")', JS)
        self.assertIn("sl.append(switchOf(sc),", JS)
        self.assertIn("see: (on) => seeAct(on !== false),", JS)
        self.assertIn("function setSee(v, by) {", JS)

    def test_record_field_default_on(self):
        self.assertIn("m.see = rec.see === undefined || Number(rec.see) ? 1 : 0;", JS)   # adoptExtra: an older owner = on
        self.assertIn("see: m.see === 0 ? 0 : 1,", JS)
        self.assertIn("function audPreset(m, o) {", JS)


class Templates(unittest.TestCase):
    def test_api(self):
        self.assertIn("audSnap, audApply, rolesSnap, rolesApply,", JS)
        self.assertIn("function audSnap() {", JS)
        self.assertIn('if ("see" in s) out.see = seeAct(on(s.see));', JS)
        self.assertIn("function rolesApply(s) {", JS)
        self.assertIn("roleAbsent: (name, r, o) =>", JS)
        self.assertIn("function preDenied(id, p) {", JS)

    def test_template_table_carries_see(self):
        self.assertIn('{ key: "see", sw: 1, text: "Audience can see each other", def: 1, read: (m) => (m.see === 0 ? 0 : 1), apply: (m, v) => { m.see = v ? 1 : 0; } },', JS)
        self.assertIn("for (const x of rs.backstage) if (!x.here && !has.has(nk(x.name)))", JS)   # tplSnap keeps the waiting people
        self.assertNotIn("audSnap: () => (mine && mine.lt ?", JS)   # one audSnap (with see)
        self.assertIn("const hook = window.__pres && window.__pres.onEnd, v0 = deck();", JS)   # B's End hook kept

    def test_roles_snapshot_names_and_presence(self):
        self.assertIn("const kept = new Map();", JS)
        self.assertIn("const here = (p) => p === me || inRoom.has(p);", JS)
        self.assertIn("main: p === own, here: here(p) }", JS)
        self.assertIn("control: ps.filter((x) => alOf(x).has(p)).map(nm), here: here(p) }", JS)


class LineEndings(unittest.TestCase):
    def test_kept(self):
        self.assertNotIn("\r\n", JS)
        self.assertIn("\r\n", HTML)
        self.assertNotIn("\r\n", _read(os.path.join("tests", "test_release_0_21_92_audience_view.py")))


if __name__ == "__main__":
    unittest.main()
