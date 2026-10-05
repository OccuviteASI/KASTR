# -*- coding: utf-8 -*-
"""v0.21.17 room locks (Kenton 2026-10-05: 'a participant joined a LOCKED room by trying twice').
Server side: a lock registered at the hub is enforced at a federated spoke's minter (B1), a spoke cannot create a second
lock over a hub-locked name, a spoke-created lock is mirrored to the hub, and a room in use keeps its lock past ROOM_TTL
(B3). Page side: the gate and the sidebar Create never turn an existing room's name into a new lock (H1)."""
import hashlib, io, os, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1"}
SALT = "00112233aabbccdd"


def h(code):
    return hashlib.sha256((SALT + code).encode()).hexdigest()


def store(codes=CODES):
    st = kr.AuthStore(tempfile.mkdtemp())
    if codes:
        st.set_codes(**codes)
    return st


class Federation(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: base, fed_token=lambda: fed)

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def mint(self, svc, room_code, peer="10.0.0.9"):
        return svc.token({"room": "secret", "code": "view-1", "roomCode": room_code, "host": "box-1a2b"}, peer)

    def test_spoke_refuses_a_hub_locked_room(self):
        o, c = kr.register_room(self.hub.store, {"slug": "secret", "salt": SALT, "hash": h("right"), "access": "pub-1"}, "10.0.0.1")
        self.assertEqual(c, 200, o)
        o, c = self.mint(self.spoke, "")
        self.assertEqual(c, 403, o)                        # 0.21.16 answered 200 viewer
        o, c = self.mint(self.spoke, "guess", peer="10.0.0.10")
        self.assertEqual(c, 403, o)
        o, c = self.mint(self.spoke, "right", peer="10.0.0.11")
        self.assertEqual(c, 200, o)

    def test_spoke_cannot_shadow_a_hub_lock(self):
        kr.register_room(self.hub.store, {"slug": "secret", "salt": SALT, "hash": h("right"), "access": "pub-1"}, "10.0.0.1")
        o, c = self.spoke.register({"slug": "secret", "salt": SALT, "hash": h("mine"), "access": "pub-1"}, "10.0.0.2")
        self.assertEqual(c, 409, o)

    def test_spoke_lock_is_mirrored_to_the_hub(self):
        o, c = self.spoke.register({"slug": "yard", "salt": SALT, "hash": h("gate"), "access": "pub-1"}, "10.0.0.2")
        self.assertEqual(c, 200, o)
        for _ in range(50):
            if self.hub.store.room("yard"):
                break
            time.sleep(0.05)
        rec = self.hub.store.room("yard")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.get("hash"), h("gate"))
        o, c = self.hub.token({"room": "yard", "code": "view-1", "roomCode": "nope", "host": "box-1a2b"}, "10.0.0.12")
        self.assertEqual(c, 403, o)

    def test_open_rooms_still_mint_at_the_spoke(self):
        o, c = self.spoke.token({"room": "lobby", "code": "view-1", "host": "box-1a2b"}, "10.0.0.13")
        self.assertEqual(c, 200, o)

    def test_rooms_fed_needs_a_federation_token(self):
        o, c = self.hub.rooms_fed({"op": "check", "slug": "secret"}, None)
        self.assertEqual(c, 403)
        o, c = self.hub.rooms_fed({"op": "check", "slug": "secret"}, "Bearer not-a-token")
        self.assertEqual(c, 403)


class InUse(unittest.TestCase):
    def test_lock_survives_member_use_past_ttl(self):
        svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        try:
            kr.register_room(svc.store, {"slug": "secret", "salt": SALT, "hash": h("right"), "access": "pub-1"}, "10.0.0.1")
            svc.store.rooms["secret"]["at"] = time.time() - kr.ROOM_TTL + 120      # the creator left ~a day ago
            o, c = svc.token({"room": "secret", "code": "view-1", "roomCode": "right", "host": "box-1a2b"}, "10.0.0.5")
            self.assertEqual(c, 200, o)
            self.assertGreater(svc.store.rooms["secret"]["at"], time.time() - 60)
            o, c = svc.token({"room": "secret", "code": "view-1", "roomCode": "", "host": "box-1a2b"}, "10.0.0.6")
            self.assertEqual(c, 403, o)
        finally:
            svc.close()


class PageGate(unittest.TestCase):
    def setUp(self):
        with io.open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8", newline="") as f:
            self.page = f.read()

    def test_new_room_never_requires_an_empty_code_to_refuse(self):
        self.assertNotIn("if (taken && !joinEls.joinPwd.value)", self.page)
        self.assertNotIn("(r.locked || r.persistent)) && !codeInp.value", self.page)

    def test_existing_names_join_through_the_lock_check(self):
        self.assertEqual(self.page.count("const existing = lastChannelList.find((r) => r.slug === slug);"), 2)
        self.assertGreaterEqual(self.page.count("await lockedRoomRefusal("), 5)

    def test_locks_register_on_every_relay(self):
        self.assertNotIn("if ((rec.hash && authSecured) || rec.persistent) {", self.page)

    def test_record_builder_does_not_remember(self):
        i = self.page.index("async function createChannelRecord(")
        self.assertNotIn("rememberChannel(rec);", self.page[i:i + 400])


if __name__ == "__main__":
    unittest.main()
