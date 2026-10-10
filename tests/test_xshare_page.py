"""0.21.41: the page side of "share to several rooms", the room-switch prompt, and screen sound off by default.

Run: python -m unittest discover -s tests
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _page():
    with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


class ShareToSeveralRooms(unittest.TestCase):
    def test_switch_in_more_and_menu_item(self):
        p = _page()
        self.assertIn('id="optXshare"', p)
        self.assertIn('if (xsOn()) items.push({ value: "xshare", label: "Also show in other rooms\\u2026" });', p)

    def test_listing_is_proven_by_both_rooms_tokens(self):
        p = _page()
        body = p[p.index("  async function xsPost(path, opts) {"):p.index("  function xsStop(path) {")]
        self.assertIn('headers.authorization = "Bearer " + authTokens.member', body)
        self.assertIn("tokens: stop ? {} : (x?.tokens || {})", body)

    def test_members_get_a_tile_on_its_own_connection(self):
        p = _page()
        self.assertIn("function tileUrl(name) {", p)
        self.assertEqual(p.count("tileUrl(name)") >= 6, True)
        self.assertIn('fetch(base + "/api/xshare?room=" + encodeURIComponent(CHANNEL), { cache: "no-store", headers })', p)
        self.assertIn('(from ? " (from " + from + ")" : wrTag(path))', p)

    def test_the_token_never_rides_the_listing_url(self):
        p = _page()
        body = p[p.index("  async function xsPoll() {"):p.index("  setInterval(() => { xsPoll(); xsOfferNew(); }, 8000);")]
        self.assertNotIn("jwt=", body)


class RoomSwitch(unittest.TestCase):
    def test_asks_first_and_arrives_quiet(self):
        p = _page()
        self.assertIn("Your microphone will be muted and your camera turned off.", p)
        body = p[p.index("  async function switchRoom(rec, code) {"):p.index("  async function switchRoom(rec, code) {") + 900]
        self.assertIn("src.micMuted = true;", body)
        self.assertIn("src.videoPaused = true;", body)


class ShareSound(unittest.TestCase):
    def test_off_by_default(self):
        p = _page()
        self.assertIn("    ss.checked = false;   // 0.21.41", p)
        self.assertNotIn('shareSound")?.checked ?? true', p)


if __name__ == "__main__":
    unittest.main()
