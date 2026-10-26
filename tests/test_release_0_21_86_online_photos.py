# -*- coding: utf-8 -*-
"""0.21.86 (Kenton: "The people page is showing a circle with a color and initials, not the uploaded photo from profile"):
Everyone online used only the photos announced in MY room. Now: my own photo from my profile, people in public rooms from
their room's state record, people in personal rooms from their beat (kept with where they are, passed to the hub)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
from tests.test_release_0_21_85_everyone_online import Hub, beat, online, people, GUEST, OWNER, _read  # noqa: E402

PHOTO = "http://10.0.2.14:8001/api/files/0123456789abcdef"


class CleanAvatar(unittest.TestCase):
    def test_only_relay_file_urls(self):
        self.assertEqual(kr.clean_avatar(PHOTO), PHOTO)
        self.assertEqual(kr.clean_avatar("https://kastr.madlabs.app/api/files/abc_DEF-123"), "https://kastr.madlabs.app/api/files/abc_DEF-123")
        for bad in ("javascript:alert(1)", "http://x/api/files/../../etc", "data:image/png;base64,AAAA", "http://x/other/abcdef12",
                    PHOTO + "?t=1", "http://x y/api/files/abcdef12", "", None, "http://h/api/files/" + "a" * 300):
            self.assertEqual(kr.clean_avatar(bad), "", bad)


class PhotosOnline(Hub):
    def test_a_beat_carries_the_photo_to_the_list(self):
        o, c = people(self.svc, self.bob, {"op": "beat", "name": "Bob", "mode": "full", "avatar": PHOTO})
        self.assertEqual(c, 200, o)
        rows = {r["host"]: r for r in online(self.svc, self.eve)["rows"]}
        self.assertEqual(rows[GUEST]["avatar"], PHOTO)            # a private-room row keeps its name and photo, never the room
        self.assertNotIn("avatar", rows[OWNER])                   # no photo set: nothing
        people(self.svc, self.bob, {"op": "beat", "name": "Bob", "avatar": "javascript:alert(1)"})
        rows = {r["host"]: r for r in online(self.svc, self.eve)["rows"]}
        self.assertNotIn("avatar", rows[GUEST])                   # a bad one replaces it with none

    def test_spoke_forwards_it(self):
        o, c = self.svc._p_fed("pwhere", {"op": "pwhere", "slug": self.slug, "host": "dave-0a0b", "name": "Dave", "mode": "full",
                                          "via": "mendon", "avatar": PHOTO})
        self.assertEqual(c, 200, o)
        rows = {r["host"]: r for r in online(self.svc, self.eve)["rows"]}
        self.assertEqual(rows["dave-0a0b"]["avatar"], PHOTO)
        src = _read("kastr_relay.py")
        self.assertIn('body = {"op": "pwhere", "slug": room, "host": host, "name": name, "mode": mode, "via": via, "avatar": avatar}', src)
        self.assertIn('"via": self.relay_name(), "avatar": av}, timeout=4)', src)
        self.assertEqual(src.count("clean_avatar(p.get(\"avatar\")))"), 2)   # pwhere + pbeat on the hub


class Page(unittest.TestCase):
    def test_everyone_online_paints_photos(self):
        p = _read("moq-watch-lite.html")
        self.assertIn('const eoAvatar = (x) => (x.me && window.__avatarLocal) || avatarUrls.get(x.op) || x.avatar || "";', p)
        self.assertIn("paintAvatar(av, eoAvatar(x));", p)
        self.assertIn("if (!x.avatar && w.avatar) x.avatar = String(w.avatar);", p)
        self.assertIn('avatar: window.__avatarUrl?.() || "" }) });', p)
        self.assertIn('window.__avatarUrl = () => avatarRemote?.url || "";', p)


if __name__ == "__main__":
    unittest.main()
