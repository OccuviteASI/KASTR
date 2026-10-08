# -*- coding: utf-8 -*-
"""v0.21.25 -- the hub owns rooms, and a hub can hand its duties to another box.

Kenton 2026-10-08: "They should all be stored on the hub and distributed to all relays to see. Some of them are storing on
the relays ... I was on the Logan Relay and created a room. I couldn't even see it on the laptop I have connected to the
relay." Decisions: plain rooms are stored on the hub and expire ~10 min after their last use; a spoke whose hub is dark
REFUSES to create; a hand-over moves rooms, groups, chat history, access codes and kicks."""
import hashlib, json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1", "admin": "boss-1", "federation": "fed-1"}
SALT = "00112233aabbccdd"


def h(code):
    return hashlib.sha256((SALT + code).encode()).hexdigest()


def store(codes=CODES):
    st = kr.AuthStore(tempfile.mkdtemp())
    if codes:
        st.set_codes(**codes)
    return st


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class PlainRooms(unittest.TestCase):
    def test_plain_room_is_stored_and_listed(self):
        st = store()
        o, c = kr.register_room(st, {"slug": "logan-ops", "plain": True, "creator": "Kenton"}, "10.0.0.1")
        self.assertEqual(c, 200, o)
        self.assertTrue(o.get("plain"))
        rows = {r["slug"]: r for r in st.rooms_public()}
        self.assertIn("logan-ops", rows)
        self.assertTrue(rows["logan-ops"]["plain"])
        self.assertFalse(rows["logan-ops"]["locked"])

    def test_plain_room_survives_a_restart_and_expires_after_use(self):
        st = store()
        st.touch_room("yard")
        again = kr.AuthStore(st.state_dir)   # a relay bounce keeps it
        self.assertIsNotNone(again.room("yard"))
        with again.lock:
            again.rooms["yard"]["at"] = time.time() - kr.PLAIN_TTL - 5
        self.assertIsNone(again.room("yard"))
        self.assertNotIn("yard", [r["slug"] for r in again.rooms_public()])

    def test_touch_keeps_it_alive_and_never_unlocks(self):
        st = store()
        kr.register_room(st, {"slug": "secret", "salt": SALT, "hash": h("x"), "access": "pub-1"}, "10.0.0.1")
        self.assertFalse(st.touch_room("secret"))
        self.assertEqual(st.room("secret")["hash"], h("x"))

    def test_a_plain_room_can_be_locked_by_a_publisher(self):
        st = store()
        kr.register_room(st, {"slug": "yard", "plain": True}, "10.0.0.1")
        o, c = kr.register_room(st, {"slug": "yard", "salt": SALT, "hash": h("gate"), "access": "pub-1"}, "10.0.0.2")
        self.assertEqual(c, 200, o)
        self.assertEqual(st.room("yard")["hash"], h("gate"))

    def test_joining_a_plain_room_is_not_a_conflict(self):
        st = store()
        kr.register_room(st, {"slug": "yard", "plain": True}, "10.0.0.1")
        o, c = kr.register_room(st, {"slug": "yard", "plain": True}, "10.0.0.2")
        self.assertEqual(c, 200, o)

    def test_unkeeping_leaves_a_plain_room(self):
        st = store()
        o, _ = kr.register_room(st, {"slug": "kept", "persistent": True, "access": "pub-1"}, "10.0.0.1")
        o2, c = kr.register_room(st, {"slug": "kept", "roomKey": o["roomKey"], "persistent": False}, "10.0.0.1")
        self.assertEqual(c, 200, o2)
        self.assertTrue(st.room("kept").get("plain"))


class HubOwnsRooms(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        self.fed = "Bearer " + kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))

    def tearDown(self):
        self.hub.close()

    def test_register_list_touch_close_through_the_hub(self):
        o, c = self.hub.rooms_fed({"op": "register", "body": {"slug": "logan-ops", "plain": True}, "peer": "10.0.0.5"}, self.fed)
        self.assertEqual(c, 200, o)
        o, c = self.hub.rooms_fed({"op": "list"}, self.fed)
        self.assertIn("logan-ops", [r["slug"] for r in o["rooms"]])
        o, c = self.hub.rooms_fed({"op": "touch", "slug": "other-room"}, self.fed)
        self.assertTrue(o["created"])
        closed = []
        with mock.patch.object(kr, "ROOM_CLOSE_HOOK", [closed.append]):
            o, c = self.hub.rooms_fed({"op": "close", "slug": "logan-ops", "vouch": "admin"}, self.fed)
        self.assertEqual(c, 200, o)
        self.assertEqual(closed, ["logan-ops"])   # the hub's chat transcript goes too

    def test_a_spoke_vouches_for_its_publisher_code(self):
        body = {"slug": "kept", "persistent": True, "access": "the-spokes-own-code"}
        o, c = self.hub.rooms_fed({"op": "register", "body": body}, self.fed)
        self.assertEqual(c, 403, o)           # the hub cannot check another box's code
        o, c = self.hub.rooms_fed({"op": "register", "body": body, "vouch": "publisher"}, self.fed)
        self.assertEqual(c, 200, o)

    def test_room_ops_need_a_federation_token(self):
        o, c = self.hub.rooms_fed({"op": "list"}, None)
        self.assertEqual(c, 403)

    def test_adopt(self):
        rec = {"salt": SALT, "hash": h("a"), "roomKey": "k" * 32, "persistent": True, "creator": "Kenton"}
        o, c = self.hub.rooms_fed({"op": "adopt", "slug": "spoke-room", "rec": rec}, self.fed)
        self.assertTrue(o.get("adopted"), o)
        self.assertEqual(self.hub.store.room("spoke-room")["roomKey"], "k" * 32)   # its creator still closes it
        o, c = self.hub.rooms_fed({"op": "adopt", "slug": "spoke-room", "rec": dict(rec, persistent=False)}, self.fed)
        self.assertTrue(o.get("merged"), o)
        o, c = self.hub.rooms_fed({"op": "adopt", "slug": "spoke-room", "rec": dict(rec, hash=h("b"))}, self.fed)
        self.assertEqual(c, 409, o)


class HandOver(unittest.TestCase):
    def setUp(self):
        self.key = os.urandom(32)
        self.old = kr.AuthService("127.0.0.1", 0, self.key, 4443, store(), is_hub=lambda: None, on_handover=mock.Mock())
        self.fed = "Bearer " + kr._mint(self.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        kr.register_room(self.old.store, {"slug": "kept", "persistent": True, "access": "pub-1"}, "10.0.0.1")
        cdir = os.path.join(self.old.store.state_dir, "chat")
        os.makedirs(cdir)
        with open(os.path.join(cdir, "kept.jsonl"), "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps({"id": 1, "ts": 1, "op": "kenton", "text": "hello"}) + "\n")

    def tearDown(self):
        self.old.close()

    def test_needs_the_admin_code(self):
        o, c = self.old.hub_handover({"admin": "wrong", "hub": "https://10.0.0.9:4443"}, self.fed, "10.0.0.9")
        self.assertEqual(c, 403, o)
        o, c = self.old.hub_handover({"admin": "boss-1", "hub": "https://10.0.0.9:4443"}, None, "10.0.0.9")
        self.assertEqual(c, 403, o)

    def test_hands_over_records_and_tells_the_spokes(self):
        o, c = self.old.hub_handover({"admin": "boss-1", "hub": "https://10.0.0.9:4443", "web": 8001, "code": "fed-1"}, self.fed, "10.0.0.9")
        self.assertEqual(c, 200, o)
        self.assertIn("kept", o["store"]["rooms"])
        self.assertTrue(o["store"]["codes"]["admin"]["hash"])
        self.assertIn("hello", o["chat"]["kept"]["text"])
        self.assertEqual(self.old.cmd["rehome"]["hub"], "https://10.0.0.9:4443")
        # the new hub imports: codes and rooms carry over
        new = store(codes=None)
        n = new.import_bundle(o["store"])
        self.assertEqual(n["codes"], 4)
        self.assertTrue(new.check("admin", "boss-1"))
        self.assertIsNotNone(new.room("kept"))

    def test_an_old_hub_tells_late_spokes_where_the_hub_went(self):
        a = kr.AuthService("127.0.0.1", 0, self.key, 4443, store(), is_hub=lambda: False,
                           rehome_info=lambda: {"hub": "https://10.0.0.9:4443", "web": 8001})
        try:
            o, c = a.bans_for_spoke(self.fed)
            self.assertEqual(c, 403)
            self.assertEqual(o["rehome"]["hub"], "https://10.0.0.9:4443")
        finally:
            a.close()


class SpokeSide(unittest.TestCase):
    def _relay(self, connect="https://10.0.0.1:4443", tok="tok", hub_flag=None):
        r = kr.Relay.__new__(kr.Relay)
        r._cluster_raw = lambda: {"connect": connect, "hub": hub_flag, "code": "fed-1"}
        r._hub_minter_url = lambda: ("http://10.0.0.1:4444" if connect else None)
        r._fed_active = tok
        r.federation = {"reason": "test"}
        return r

    def test_not_a_spoke(self):
        self.assertIsNone(self._relay(connect="").hub_rooms_call({"op": "list"}))
        self.assertIsNone(self._relay(hub_flag=True).hub_rooms_call({"op": "list"}))

    def test_no_token_is_hub_down(self):
        with self.assertRaises(kr.HubDown):
            self._relay(tok=None).hub_rooms_call({"op": "list"})

    def test_unreachable_hub_is_hub_down(self):
        r = self._relay()
        r._hub_minter_url = lambda: "http://127.0.0.1:9"   # discard port: nothing answers
        with self.assertRaises(kr.HubDown):
            r.hub_rooms_call({"op": "list"}, timeout=1)


class Rehome(unittest.TestCase):
    def _relay(self, connect, hub_flag=None):
        r = kr.Relay.__new__(kr.Relay)
        r._cluster_raw = lambda: {"connect": connect, "hub": hub_flag, "code": "fed-1"}
        r.set_cluster = mock.Mock(return_value={"ok": True})
        r.log = lambda *a: None
        return r

    def test_a_spoke_re_points_to_the_new_hub(self):
        r = self._relay("https://10.0.0.1:4443")
        r._hub_cmd("rehome", {"hub": "https://10.0.0.9:4443", "web": 8001, "seq": 3})
        r.set_cluster.assert_called_once_with({"connect": "https://10.0.0.9:4443", "web": 8001})

    def test_the_new_hub_ignores_its_own_rehome(self):
        r = self._relay("", hub_flag=True)
        r._hub_cmd("rehome", {"hub": "https://10.0.0.9:4443"})
        r.set_cluster.assert_not_called()

    def test_already_there(self):
        r = self._relay("https://10.0.0.9:4443")
        r._hub_cmd("rehome", {"hub": "https://10.0.0.9:4443/"})
        r.set_cluster.assert_not_called()


class CommandChannel(unittest.TestCase):
    """0.21.26: the re-point command reaches spokes on the long-poll (0.21.25 raised it but never sent it), and an update
    can target one spoke."""

    def setUp(self):
        self.key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.key, 4443, store())
        self.fed = "Bearer " + kr._mint(self.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))

    def tearDown(self):
        self.hub.close()

    def test_rehome_and_update_one_ride_the_reply(self):
        self.hub.raise_cmd("rehome", {"hub": "https://10.0.0.9:4443", "web": 8001})
        self.hub.raise_cmd("updateOne", {"version": "0.21.26", "spoke": "logan-roc"})
        self.hub.raise_cmd("updateOne", {"version": "0.21.26", "spoke": "tremonton"})
        o, c = self.hub.bans_for_spoke(self.fed)
        self.assertEqual(c, 200)
        self.assertEqual(o["cmd"]["rehome"]["hub"], "https://10.0.0.9:4443")
        self.assertEqual([x["spoke"] for x in o["cmd"]["updateOne"]], ["logan-roc", "tremonton"])   # two clicks, both kept

    def test_targeted_update_reaches_only_that_spokes_address(self):
        # 0.21.27: works for OLD spokes too -- they act on `update` when its seq moves past what they saw
        self.hub.register_spoke({"name": "logan-roc", "version": "0.21.20"}, peer="10.0.5.5", bearer=self.fed)
        self.hub.register_spoke({"name": "mendon", "version": "0.21.20"}, peer="10.0.6.6", bearer=self.fed)
        everyone = self.hub.raise_cmd("update", {"version": "0.21.27"})
        one = self.hub.raise_cmd("update", {"version": "0.21.27", "spoke": "logan-roc"})
        o, _ = self.hub.bans_for_spoke(self.fed, peer="10.0.5.5")
        self.assertEqual(o["cmd"]["update"]["seq"], one["seq"])        # logan-roc sees its update
        o, _ = self.hub.bans_for_spoke(self.fed, peer="10.0.6.6")
        self.assertEqual(o["cmd"]["update"]["seq"], everyone["seq"])   # mendon sees nothing new
        self.assertLess(o["cmd"]["update"]["seq"], o["cmd"]["seq"])

    def test_spoke_acts_only_on_its_own_update(self):
        r = kr.Relay.__new__(kr.Relay)
        r.relay_name = lambda: "logan-roc"
        r.log = lambda *a: None
        hook = mock.Mock()
        import kastr_serve
        with mock.patch.object(kastr_serve, "FEDERATION_UPDATE_HOOK", hook, create=True):
            r._hub_cmd("update", {"seq": 4, "spoke": "tremonton", "version": "0.21.26"})
            hook.assert_not_called()
            r._hub_cmd("update", {"seq": 5, "spoke": "logan-roc", "version": "0.21.26"})
            hook.assert_called_once()

    def test_relay_page_update_one_and_quiet_button(self):
        r = _read("relay.html")
        self.assertIn('api("/api/relay/spokes/update", { spoke: sp })', r)
        self.assertIn('$("spokesUpdate").classList.toggle("ghost", nBehind === 0);', r)


class Pages(unittest.TestCase):
    def test_serve_forwards_room_calls_and_routes_federation(self):
        s = _read("kastr_serve.py")
        self.assertIn('fwd = self._rooms_at_hub(method, path, store, log)', s)
        self.assertIn('if path0 in ("/api/rooms/fed", "/api/ondemand/forward", "/api/hub/handover"):', s)
        self.assertIn('"hubDown": True', s)
        self.assertIn("kastr_relay.ROOM_CLOSE_HOOK[0] = _room_close_hook", s)

    def test_page_registers_every_room_and_touches_it(self):
        p = _read("moq-watch-lite.html")
        self.assertIn("plain: !(rec.hash || rec.persistent) };", p)
        self.assertIn("if (!g.ok && (rec.hash || rec.persistent || g.hubDown))", p)
        self.assertIn('fetch(hb + "/api/rooms/touch"', p)
        self.assertIn("if (d5.hubDown) return { ok: false, hubDown: true", p)

    def test_relay_page_hand_over_prompt(self):
        r = _read("relay.html")
        self.assertIn('<dialog id="hubMove"', r)
        self.assertIn('api("/api/relay/hub/takeover", { address: addr, admin })', r)
        self.assertIn("if (on && was) { $(\"fedHub\").checked = false; hubMoveOpen(was); return; }", r)


if __name__ == "__main__":
    unittest.main()
