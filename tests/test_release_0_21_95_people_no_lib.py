"""0.21.95 (Kenton 2026-10-30: "I don't want the library 'users' to show up in the people page"): a stream pulled in from the
stream library (lib/<host>/<op>/<leaf>.hang) is a tile on the stage, never a row in People -- 0.21.84's personKeyOf gave it a
"lib:<host>" key, so participantList showed "Lib:<host>  Presenting" rows for each library box."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PeopleNoLibrary(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.src = f.read()

    def test_participant_list_skips_library_paths(self):
        i = self.src.index("function participantList()")
        body = self.src[i:self.src.index("const key = personKeyOf(n);", i)]
        self.assertRegex(body, r"if \(isLibPath\(n\)\) continue;")

    def test_skip_comes_before_the_person_key(self):
        i = self.src.index("function participantList()")
        j = self.src.index("isLibPath(n)) continue;", i)
        k = self.src.index("const key = personKeyOf(n);", i)
        self.assertLess(j, k)

    def test_library_tiles_keep_their_own_menu(self):   # the stage tile menu of a library stream is not a People row's
        self.assertTrue(re.search(r'startsWith\("lib:"\)\) \{ libTileMenuPick', self.src))


if __name__ == "__main__":
    unittest.main()
