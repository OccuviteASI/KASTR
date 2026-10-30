"""0.21.95 (Kenton 2026-10-30: "With the streams being added to a room from the library, when I spotlight multiple things, only 1
stays on stage. It doesn't seem to work like streams that are actively in the room."). Cause: spotSetNow() drops every vote whose
target starts with another room unless it is listed from another room (xsTiles) -- a library stream (lib/<host>/<op>/<leaf>.hang)
is neither, so its "Spotlight for everyone" (my own vote AND the room board's copy) never reached the room's set: no mosaic, no
"Remove spotlight", only the tile I had clicked stayed."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LibrarySpotlight(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.src = f.read()

    def test_room_filter_lets_library_tiles_in(self):
        i = self.src.index("function spotSetNow()")
        body = self.src[i:self.src.index("return spotOrdered(", i)]
        self.assertIn('!== CHANNEL && !xsTiles.has(String(v.target)) && !libTiles.has(String(v.target))) return;', body)

    def test_board_spot_of_a_library_pin_is_posted(self):   # boardSpot: another room's / the library's path posts once pinned
        i = self.src.index("function boardSpot(")
        body = self.src[i:self.src.index("async function boardGrid(", i)]
        self.assertIn("if (from !== CHANNEL && !boardPinned(t) && !(await boardPin(t, true, true))) return;", body)

    def test_library_tiles_are_page_tiles(self):   # spotApplyWinner places targets that are tiles; libSync makes library tiles
        i = self.src.index("async function libSync()")
        body = self.src[i:self.src.index("setInterval(() => { try { libSync(); }", i)]
        self.assertIn("libTiles.set(p, { why });", body)
        self.assertIn("createTile(p)", body)


if __name__ == "__main__":
    unittest.main()
