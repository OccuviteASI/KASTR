# -*- coding: utf-8 -*-
"""v0.21.91 ROOM NAMES NEED AN ACCESS CODE. Kenton: "Room names must not be visible to anyone without a fleet access code: the
public ~presence / ~channels / ~state announces, /api/rooms/list without a token, and anything else anonymous that leaks room or
member names. The Join room page shows no rooms until a code is typed and checked, then lists them."

The relay answers each session through KASTR's minter (POST /api/session): a session without a token now gets NOTHING (it got the
public kinds); every token of the fleet still carries them -- a member's (any room, the Lobby, library, vehicle) all of them, a
guest's (an invite link, a My room guest) only their own room's, and the new BROWSE token (POST /api/token {browse, code}: any
access code of the fleet) lets the Join room page read the rooms before joining. /api/rooms/list and the minter's /api/rooms
answer nothing without a token (the relay machine's own loopback pages -- the Relay page -- still see everything)."""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1", "admin": "adm-1"}


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def store(codes=CODES):
    st = kr.AuthStore(tempfile.mkdtemp())
    if codes:
        st.set_codes(**codes)
    return st


PRES = kr.NS + "presence"


class Grants(unittest.TestCase):
    def test_tokenless_sees_nothing(self):
        self.assertEqual(kr.public_grant(), {"publish": [], "subscribe": [kr.NS + "anon"]})   # admitted, reads nothing
        st, g, why = kr.session_grant({"path": "/"}, os.urandom(32))
        self.assertEqual((st, g["subscribe"], g["publish"]), ("public", [kr.ANON_KIND], []))
        self.assertNotIn(kr.ANON_KIND, kr.PUBLIC_KINDS)

    def test_a_member_reads_the_public_kinds(self):
        g = kr.claims_to_grant({"root": "", "get": "yard", "put": ["yard/kenton-ab12"], "exp": int(time.time()) + 60})
        for q in kr.public_patterns():
            self.assertIn(q, g["subscribe"])

    def test_a_guest_reads_its_room_only(self):
        g = kr.claims_to_grant({"root": "", "get": "yard", "put": ["yard/guest-cd34"], "inv": "0123abcd", "exp": int(time.time()) + 60})
        self.assertIn(PRES + "/yard", g["subscribe"])
        self.assertIn(kr.STATE_PREFIX + "/yard/**", g["subscribe"])
        self.assertNotIn(PRES, g["subscribe"])
        self.assertNotIn(PRES + "/**", g["subscribe"])
        self.assertFalse(any(x.startswith(kr.STATS_KIND) for x in g["subscribe"]))
        lob = kr.claims_to_grant({"root": "", "get": "main", "put": [kr.PRESENCE_KIND + "/main"], "lobby": 1, "inv": "0123abcd", "ir": "yard",
                                  "exp": int(time.time()) + 60})
        self.assertEqual(sorted(set(x.split("/")[1] for x in lob["subscribe"])), ["yard"])   # waiting in the Lobby: that room alone
        pg = kr.claims_to_grant({"root": "", "get": "me-0123456789ab", "put": ["me-0123456789ab/guest-cd34"], "pg": 1, "exp": int(time.time()) + 60})
        self.assertEqual(sorted(set(x.split("/")[1] for x in pg["subscribe"] if x.startswith(kr.NS))), ["me-0123456789ab"])

    def test_federation_and_links_unchanged(self):
        self.assertEqual(kr.claims_to_grant(dict(kr.FEDERATION_CLAIMS, exp=int(time.time()) + 60))["subscribe"], ["**"])


class Browse(unittest.TestCase):
    def setUp(self):
        self.key = os.urandom(32)
        self.svc = kr.AuthService("127.0.0.1", 0, self.key, 4443, store())

    def tearDown(self):
        self.svc.close()

    def test_any_access_code_of_the_fleet(self):
        for code in ("view-1", "pub-1", "adm-1"):
            d, c = self.svc.token({"browse": True, "code": code}, "10.0.0.%d" % len(code))
            self.assertEqual(c, 200, d)
            cl = kr.verify_token(d["tokens"]["browse"], self.key)
            self.assertEqual(cl["browse"], 1)
            g = kr.claims_to_grant(cl)
            self.assertEqual(g["publish"], [])                              # reads only
            self.assertIn(kr.CHANNELS_KIND + "/**", g["subscribe"])
            self.assertEqual(kr.claims_identity(cl), (None, None))          # in no room
            self.assertEqual(kr.claims_role(cl), "viewer")

    def test_a_wrong_code_is_a_guess(self):
        d, c = self.svc.token({"browse": True, "code": "nope"}, "10.0.0.9")
        self.assertEqual(c, 403)
        self.assertNotIn("tokens", d)
        self.assertEqual(self.svc.token({"browse": True, "code": ""}, "10.0.0.9")[1], 403)

    def test_a_relay_without_codes(self):
        svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store(codes=None))
        try:
            self.assertEqual(svc.token({"browse": True, "code": ""}, "10.0.0.9")[1], 200)
        finally:
            svc.close()


class Lists(unittest.TestCase):
    def test_the_list_needs_a_token(self):
        s, r = _read("kastr_serve.py"), _read("kastr_relay.py")
        self.assertIn("if self._local():\n                        return obj\n                    out = kastr_relay.rooms_for_guest(obj, set())\n"
                      "                    out.update(guest=False, needCode=True)", s.replace("\r\n", "\n"))
        self.assertIn("if c is None and self._peer() not in LOOPBACK_PEERS:", r)
        out = kr.rooms_for_guest({"rooms": [{"slug": "yard"}], "groups": {"g": {}}, "renamed": {"a": "b"}, "closed": {"x": 1}}, set())
        self.assertEqual((out["rooms"], out["groups"], out["renamed"], out["closed"]), ([], {}, {}, {}))


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html")

    def test_the_rooms_ride_a_token(self):
        p = self.p
        self.assertIn('{ const t = roomsToken(); roomsTokSeen = t; if (t) url.searchParams.set("jwt", t); }   // 0.21.91: the rooms ride a token', p)
        self.assertIn('body: JSON.stringify({ browse: true, code, host: HOST_RE.test(HOSTNAME1) ? HOSTNAME1 : undefined }) });', p)
        self.assertIn('const rt = roomsToken(), gh = rt ? { authorization: "Bearer " + rt } : undefined;', p)
        self.assertIn('joinEls.joinAccess?.addEventListener("change", () => {', p)
        self.assertIn("new URL(withToken(urlInput.value.trim()))", p)   # the relay nodes' stats
        self.assertNotIn("sessionStorage.setItem(roomsBrowseKey(), JSON.stringify({ token: roomsBrowse.token, exp: roomsBrowse.exp, base, code", p)   # the code is never kept


if __name__ == "__main__":
    unittest.main()
