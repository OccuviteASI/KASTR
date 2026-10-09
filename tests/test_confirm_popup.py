"""0.21.42: KASTR asks every yes/no question in its own centred popup; a locked room asks for its code there.

Run: python -m unittest discover -s tests
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _page():
    with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


class ConfirmPopup(unittest.TestCase):
    def test_no_browser_confirm_left(self):
        p = _page()
        left = [m.group(0) for m in re.finditer(r"(?<![A-Za-z_.])(window\.)?confirm\(", p)]
        self.assertEqual(left, [])

    def test_keys_scrim_and_focus(self):
        p = _page()
        body = p[p.index("  function kastrConfirm(o) {"):p.index("  window.__confirm = kastrConfirm;")]
        self.assertIn('if (e.key === "Escape")', body)
        self.assertIn('else if (e.key === "Enter")', body)
        self.assertIn("el.onclick = (e) => { if (e.target === el) done(false); };", body)
        self.assertIn("(o.input ? inp : yes).focus();", body)
        self.assertIn("kcBusy = p.catch(() => {});", body)   # one question at a time
        self.assertIn("#kConfirm { position:fixed; inset:0; z-index:140;", p)

    def test_room_change_asks_in_the_popup_with_the_code(self):
        p = _page()
        body = p[p.index("  async function sbCardClick(card, rec) {"):p.index("  async function sbCardClick(card, rec) {") + 2600]
        self.assertIn("const needCode = !!rec.locked;", body)
        self.assertIn("await xsTokenFor(rec.slug, v)", body)
        self.assertIn('detail: "Your microphone will be muted and your camera turned off."', body)

    def test_nothing_is_muted_when_the_switch_is_refused(self):
        p = _page()
        body = p[p.index("  async function switchRoom(rec, code) {"):p.index("  async function switchRoom(rec, code) {") + 1600]
        self.assertLess(body.index("await authMint(rec.slug"), body.index("src.micMuted = true;"))

    def test_rail_forms_scroll_into_view(self):
        self.assertIn('sbFormEl.scrollIntoView({ block: "nearest" });', _page())


if __name__ == "__main__":
    unittest.main()
