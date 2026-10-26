# -*- coding: utf-8 -*-
"""0.21.86 (Kenton): "In the people section I am still seeing initials on the 'this room' section" and "When I hover over these
options, it blows out the pill and it is difficult to see the text" (the Share menu's rows)."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
from tests.test_release_0_21_85_everyone_online import store  # noqa: E402


def read(fn):
    with open(os.path.join(HERE, fn), encoding="utf-8") as f:
        return f.read()


class AvatarAnnounce(unittest.TestCase):
    def test_room_tokens_may_announce_the_photo_again(self):
        svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store(tempfile.mkdtemp()))
        try:
            for code in ("pub-1", "view-1"):
                o, c = svc.token({"room": "alpha", "code": code, "host": "kenton-ab12"}, "10.0.0.7")
                self.assertEqual(c, 200, o)
                claims = kr.verify_token(o["tokens"]["member"], svc.key)
                self.assertIn("alpha/~avatar", claims["put"], code)
            o, c = svc.token({"room": kr.LOBBY_SLUG, "code": "pub-1", "host": "kenton-ab12"}, "10.0.0.7")
            self.assertNotIn(kr.LOBBY_SLUG + "/~avatar", kr.verify_token(o["tokens"]["member"], svc.key)["put"])   # the Lobby: presence only
        finally:
            svc.close()


class Page(unittest.TestCase):
    def test_my_own_row_and_a_visible_upload_failure(self):
        p = read("moq-watch-lite.html")
        self.assertIn("paintAvatar(av, (p.me && window.__avatarLocal) || avatarUrls.get(p.key));", p)
        self.assertIn('Others see your initials, not your photo', p)
        self.assertNotIn("Profile picture stays local", p)

    def test_my_room_members_name_themselves_in_room_json(self):
        # My room has no public state records: the backstage list (and photos) read the room-only room.json instead
        p = read("moq-watch-lite.html")
        self.assertIn("roomModel.who = isPersonalSlug(CHANNEL) ? { op: pubModel.op", p)
        self.assertIn('const key = "rj:" + path, cur = members.get(key);', p)
        self.assertIn('if (members.delete("rj:" + path))', p)
        self.assertIn("if (m.state && !m.rj && !live.has(key))", p)
        self.assertIn("people: [...members.values()].filter((m) => m.state && m.host && m.peer)", p)   # what the presentation reads

    def test_share_rows_keep_their_colours_on_hover(self):
        p = read("moq-watch-lite.html")
        self.assertIn(".pubui .shrow:hover, .pubui .shrow:hover:not(:disabled) { background:var(--surface-2); color:var(--text); border-color:var(--asi-blue); }", p)


if __name__ == "__main__":
    unittest.main()
