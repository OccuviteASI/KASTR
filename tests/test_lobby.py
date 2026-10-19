# -*- coding: utf-8 -*-
"""0.21.60 (Kenton: "change main to something like waiting room ... disable all views and people seeing each other").
Chose: "Lobby"; other rooms names + counts; no cameras/mics/sharing, no seeing who is there, no chat, no watching from it;
boxes left in main stop publishing; enforced by the relay. Rig: scratchpad v02160/pw_lobby.py."""
import io, os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402


class LobbyToken(unittest.TestCase):
    def setUp(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        self.s = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)

    def tearDown(self):
        self.s.close()

    def grant(self, room, code="pub-1"):
        o, c = self.s.token({"room": room, "code": code, "host": "box-1a2b"}, "10.0.0.9")
        self.assertEqual(c, 200, o)
        claims = kr.verify_token(o["tokens"]["member"], self.s.key)
        return o, claims, kr.claims_to_grant(claims)

    def test_the_lobby_publishes_only_presence_and_watches_nothing(self):
        for code in ("pub-1", "adm-1", "view-1"):
            o, claims, g = self.grant("main", code)
            self.assertTrue(o.get("lobby"))
            self.assertEqual(sorted(g["publish"]), sorted([kr.STATE_PREFIX + "/main/box-1a2b", kr.STATE_PREFIX + "/main/box-1a2b/**",
                                                           kr.PRESENCE_KIND + "/main", kr.PRESENCE_KIND + "/main/**"]))
            self.assertNotIn("main", g["subscribe"])
            self.assertNotIn("main/**", g["subscribe"])
            self.assertEqual(kr.claims_role(claims), "viewer")             # nothing it holds is media
            self.assertEqual(kr.claims_identity(claims), ("main", "box-1a2b"))   # a kick still knows who it was

    def test_a_room_is_unchanged(self):
        o, claims, g = self.grant("site-a")
        self.assertFalse(o.get("lobby"))
        self.assertIn("site-a/box-1a2b", g["publish"])
        self.assertIn("site-a/**", g["subscribe"])

    def test_the_public_kinds_stay_public_in_the_lobby(self):
        _o, _c, g = self.grant("main")
        for q in kr.public_patterns():
            self.assertIn(q, g["subscribe"])                              # the rooms list still works from the Lobby


class Pages(unittest.TestCase):
    def test_page(self):
        with io.open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            p = f.read()
        self.assertIn('const roomTitle = (slug) => (slug === LOBBY ? "Lobby" : isPersonalSlug(slug) ? "My room" : String(slug || ""));', p)   # 0.21.75: + My room
        self.assertIn("if (rec.slug === LOBBY || inLobby()) { ul.replaceChildren(); ul.hidden = true; return; }", p)
        self.assertIn("const want = show && !inLobby() ? viewerOps() : new Map();", p)
        self.assertIn("body.inlobby #topCamBtn", p)
        self.assertIn('lobbyEl = document.createElement("div"); lobbyEl.id = "lobbyCard";', p)

    def test_chat_refused(self):
        with io.open(os.path.join(HERE, "kastr_serve.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertEqual(src.count('if room == "main":   # 0.21.60'), 3)   # post, file post, history


if __name__ == "__main__":
    unittest.main()
