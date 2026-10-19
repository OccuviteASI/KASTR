"""0.21.61 page wiring (Kenton, 2026-10-13):
- two colours: Profile > Your colour (state.json `hc`, everyone sees it on my rings) and More > Accent colour (kastr.accent,
  replaces ASI blue in my own app only, on every page via asi-brand.js);
- a room switch is shown at once: the same page announcing in another room drops its old-room entry (no 8 s grace);
- a spotlit RTSP camera / grid is held 10 minutes through a reboot / an upgrade (localStorage copy, kept on page close);
- an update relaunch rejoins the room with the mic / camera / spotlights as they were (justUpdated + kastr.live);
- an RTMP ingest that stops flowing leaves the grid after 10 s and comes back after 15 s of flow.

Run: python -m unittest discover -s tests
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(p):
    with open(os.path.join(HERE, p), encoding="utf-8") as f:
        return f.read()


class Colours(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = read("moq-watch-lite.html")
        cls.js = read("assets/asi-brand.js")
        cls.css = read("assets/asi-brand.css")

    def test_two_separate_settings(self):
        self.assertIn('id="profHc"', self.p)
        self.assertIn('id="optAccent"', self.p)
        self.assertIn('hcPicker(document.getElementById("profHc")', self.p)
        self.assertIn('hcPicker(document.getElementById("optAccent")', self.p)

    def test_my_colour_rides_state_and_rings_use_it(self):
        self.assertIn('case "hc":', self.p)
        self.assertIn('window.__state?.set?.("hc", p.color || "")', self.p)
        self.assertIn("hiNote(v.op, v.hc);", self.p)
        for sel in ("#stage.spot .pane.talking { border-color:var(--pc, var(--asi-blue))",
                    ".sbcard .sbm.talk .nm { box-shadow:inset 0 0 0 1.5px var(--pc, var(--asi-blue))",
                    ".pprow.talk .ppav { box-shadow:0 0 0 2px var(--pc, var(--asi-blue))",
                    "#stage .pubpane.talking { border-color:var(--pc-me, var(--asi-blue))"):
            self.assertIn(sel, self.p)
        self.assertRegex(self.p, r"function personColor\(key\) \{\s*\{ const hc = hiOf\(key\); if \(hc\) return hc; \}")

    def test_accent_is_this_app_only(self):
        self.assertIn('const ACCENT_KEY = "kastr.accent";', self.js)
        self.assertIn('st.setProperty("--asi-blue", c)', self.js)
        self.assertIn('localStorage.getItem("kastr.accent")', self.p.split("</script>", 1)[0], "applied before the first paint")
        # the glow follows whatever --asi-blue is (light palette and the dark stage included)
        self.assertNotIn("--asi-blue-glow: rgba(", self.css)


class RoomMove(unittest.TestCase):
    def test_moved_peer_leaves_the_old_room_at_once(self):
        p = read("moq-watch-lite.html")
        self.assertIn("function roomsMoved(key, peer, slug)", p)
        self.assertEqual(p.count("roomsMoved("), 3)   # the definition + ~presence + ~state
        self.assertIn("if (!r.moved) r.goneAt = Date.now();", p)


class SpotHold(unittest.TestCase):
    def test_held_copy_survives_the_page_closing(self):
        p = read("moq-watch-lite.html")
        self.assertIn("const SPOT_LIT_HOLD_MS = 600000;", p)
        self.assertIn('window.addEventListener("pagehide", () => { spotLitGoing = true; }, { capture: true });', p)
        self.assertIn("else if (!spotLitGoing) localStorage.removeItem(SPOT_LIT_KEY());", p)
        self.assertIn("!(lit.restoredAt && Date.now() - lit.restoredAt < 30000)", p)


class ResumeAfterUpdate(unittest.TestCase):
    def test_wiring(self):
        p = read("moq-watch-lite.html")
        s = read("kastr_serve.py")
        self.assertIn('"justUpdated": os.environ.get("KASTR_UPDATED") == "1"', s)
        self.assertIn('const LIVE_KEY = "kastr.live";', p)
        self.assertIn("if (!(d?.justUpdated || d?.justRestarted) || joinState !== \"prejoin\"", p)   # 0.21.73: + an admin's Restart / Move
        self.assertIn("try { localStorage.removeItem(LIVE_KEY); } catch {}   // 0.21.61: Leave = nothing to resume", p)
        self.assertIn("if (saved.resumed && joinState === \"joined\") resumeAfterJoin(saved);", p)


class IngestEviction(unittest.TestCase):
    def test_constants(self):
        p = read("moq-watch-lite.html")
        self.assertIn("const GRID_INGEST_OUT_S = 10, GRID_INGEST_BACK_S = 15;", p)
        self.assertIn('a.evictWhy = "ingest"', p)


if __name__ == "__main__":
    unittest.main()
