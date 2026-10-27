"""0.21.91 (Kenton: "When hovering over a relay in the mesh map, I don't need all of this information. I just need the name,
people count, total in/out."): the full-mesh relay hover is three lines; the zoomed relay keeps the detail."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page():
    with open(os.path.join(ROOT, "relay.html"), encoding="utf-8") as f:
        return f.read()


class MeshHover(unittest.TestCase):
    def test_short_tip_is_name_people_total(self):
        s = page()
        i = s.index("function meshNodeTipShort(n) {")
        body = s[i:s.index("function meshNodeTip(n) {", i)]
        self.assertIn('"<b>" + esc(n.name) + "</b>"', body)
        self.assertIn('(p === 1 ? " person" : " people")', body)
        self.assertIn('"<br>Total in <b>" + fmtBps(L.total.in)', body)
        for gone in ("Local ", "Relay links", "hub RTT", "KASTR ", "measured "):
            self.assertNotIn(gone, body)

    def test_people_are_live_apps_and_web_pages_on_that_relay(self):
        s = page()
        self.assertIn('!r.offline && (r.kind === "app" || r.kind === "web") && names.has(String(r.relay || "").toLowerCase())', s)

    def test_full_mesh_hovers_use_the_short_tip(self):
        s = page()
        self.assertIn('v.tip = () => meshNodeTipShort(v.n);', s)
        self.assertIn("else if (n) t.innerHTML = meshNodeTipShort(n);", s)
        self.assertIn("meshNodeTip(zd.me)", s)   # the zoomed relay keeps the detail


if __name__ == "__main__":
    unittest.main()
