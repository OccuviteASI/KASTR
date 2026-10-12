"""0.21.45: pin several sources for myself (any room, watched rooms too) -- up to 9, my pins win over the room's spotlight,
kept per relay on this device.

Run: python -m unittest discover -s tests
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _page():
    with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


def _js_fn(p, head):
    i = p.index(head)
    return p[i:p.index("\n  }", i) + 4]


class PinList(unittest.TestCase):
    def test_declared_before_the_stage_reads_it(self):
        p = _page()
        self.assertLess(p.index("let myPins = []"), p.index("function applyState("))
        self.assertIn("const PIN_MAX = 9;", p)

    def test_toggle_adds_removes_and_caps(self):
        body = _js_fn(_page(), "  function pinToggle(name) {")
        self.assertIn("myPins = myPins.filter((n) => n !== name);", body)
        self.assertIn("if (myPins.length >= PIN_MAX) myPins = myPins.filter((n) => tiles.has(n));", body)
        self.assertIn("unpin one first", body)
        self.assertIn("myPins.push(name);", body)

    def test_kept_per_relay_on_this_device(self):
        p = _page()
        self.assertIn('const pinKey = () => "kastr.pins." + sbRelayHost();', p)
        self.assertIn("localStorage.setItem(pinKey(), JSON.stringify(myPins))", p)


class Stage(unittest.TestCase):
    def test_pins_win_over_the_room_spotlight(self):
        p = _page()
        self.assertIn("const stageSet = pinNow.length ? pinNow.map((n) => ({ target: n, name: n })) : spotStage;", p)
        body = _js_fn(p, "  function spotApplyWinner() {")
        self.assertIn("if (pinsLive().length) { spotStage = items.length >= 2 ? items : []; return; }", body)

    def test_last_unpin_hands_back_to_the_spotlight_or_gallery(self):
        body = _js_fn(_page(), "  function pinsGone() {")
        self.assertIn("spotApplyWinner();", body)
        self.assertIn("else goGallery();", body)

    def test_shares_arriving_never_push_pins_aside(self):
        p = _page()
        self.assertIn("&& !pinsLive().length) {   // 0.21.40: a chosen gallery stays; 0.21.45: so do my pins", p)
        self.assertIn("if (!pinsLive().length) gridMode = true;", p)

    def test_view_speaker_and_returning_sources(self):
        p = _page()
        self.assertIn("    if (pinsShow()) return;   // 0.21.45: my pins first", p)
        self.assertIn("if (isPinned(name) && !manualPick && !galleryChosen) setTimeout(", p)


class Menu(unittest.TestCase):
    def test_pin_for_me_adds_and_unpin_removes_one(self):
        p = _page()
        self.assertIn("const pinned = isPinned(name);", p)
        self.assertIn('if (v === "unpin") { pinToggle(name); return; }', p)
        self.assertIn('else if (v === "me") pinToggle(name);', p)

    def test_badge(self):
        p = _page()
        self.assertIn('pc.className = "pinc"; pc.title = "Pinned for you"; pc.innerHTML = icon("pin");', p)
        self.assertIn("#stage .pane.mypin .pinc { display:flex; }", p)


if __name__ == "__main__":
    unittest.main()
