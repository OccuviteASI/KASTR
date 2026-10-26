# -*- coding: utf-8 -*-
"""v0.21.89 ASK FOR ACCESS. Kenton (2026-10-26): "I would like to add the ability to let someone prompt people in a locked room
that lets someone with permissions in the room already to allow them in without a code." / "Maybe an 'Ask for access' in the
same pop-up as the code entry." Decided:
  1. who answers: the room's ADMINS and its CREATOR who are IN the room right now; nobody of them there -> "nobody can let you in";
  2. the admitted person gets what typing the room code would have given them, never admin;
  3. this visit only (a brief drop / an update relaunch stays inside the grant's idle window);
  4. My room the same way -- only its OWNER, only while the owner is in it.

What is proven here (loopback objects, no network): the hub's desk (kastr_access) and its wiring in kastr_relay -- asks, the
cards on the beat, the first answer wins, forged answers refused, nobody present, timeouts, rate limits + the lockout, bans,
the Lobby / unlocked rooms, the grant (this device, this room, the code's role, redeem window, idle end, keep-alive), My room
(owner only, owner present), a spoke -> hub round trip (vouch, the long-poll copy, the mint's check), an older / unreachable
hub; and the page / proxy / build wiring. The live two-relay lab is scratchpad v02189/lab."""
import hashlib
import os
import re
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_access as ka  # noqa: E402
import kastr_relay as kr  # noqa: E402

ADM, ADM2, PUB, ASK, ASK2, VIEW = "ada-aa11", "bea-bb22", "pete-cc33", "kris-dd44", "lou-ee55", "vic-ff66"
ROOM_CODE, ROOM_KEY = "alpha-code-7", "k" * 32
PEER = "10.0.0.9"


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return f.read()


def lock_room(store, slug, code=ROOM_CODE, key=ROOM_KEY):
    now = time.time()
    store.put_room(slug, {"salt": "s1", "hash": hashlib.sha256(("s1" + code).encode()).hexdigest(), "roomKey": key, "at": now,
                          "persistent": True, "creator": "", "created": now})


class Base(unittest.TestCase):
    def setUp(self):
        self.st = kr.AuthStore(tempfile.mkdtemp())
        self.st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        lock_room(self.st, "alpha")
        lock_room(self.st, "beta", code="beta-code")
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, self.st)

    def tearDown(self):
        self.svc.close()

    def mint(self, host, code="pub-1", room="alpha", rc=ROOM_CODE, peer=PEER, **kw):
        return self.svc.token(dict({"room": room, "code": code, "roomCode": rc, "host": host}, **kw), peer)

    def tok(self, host, code="adm-1", room="alpha", rc=ROOM_CODE):
        o, c = self.mint(host, code, room, rc)
        assert c == 200, o
        return o["tokens"]["member"]

    def beat(self, t, acc=True, **kw):
        body = dict({"op": "beat", "name": kw.pop("name", "")}, **kw)
        if acc:
            body["acc"] = 1
        o, c = self.svc.people_api(body, "Bearer " + t, PEER)
        assert c == 200, o
        return o

    def ask(self, host=ASK, room="alpha", code="pub-1", peer=PEER, **kw):
        return self.svc.access_api(dict({"op": "ask", "room": room, "code": code, "host": host, "name": "Kris Price", "device": "krisdesk"}, **kw), None, peer)

    def answer(self, t, aid, allow=True, by="Ada", **kw):
        return self.svc.access_api(dict({"op": "answer", "id": aid, "allow": allow, "by": by}, **kw), "Bearer " + t, PEER)

    def status(self, o):
        return self.svc.access_api({"op": "status", "id": o["id"], "key": o["key"]}, None, PEER)

    @staticmethod
    def grant(o):
        return ka.grant_token(o["id"], o["key"])


class LetIn(Base):
    def test_let_in_end_to_end_and_the_role_is_the_codes(self):
        ta = self.tok(ADM)
        self.assertEqual(self.beat(ta)["access"], {"asks": [], "closed": []})
        o, c = self.ask()
        self.assertEqual(c, 200, o)
        self.assertTrue(ka.ID_RE.match(o["id"]) and ka.KEY_RE.match(o["key"]))
        self.assertNotIn(ADM, repr(o))                                  # the asker never learns who is in the room
        cards = self.beat(ta)["access"]["asks"]
        self.assertEqual([(x["id"], x["name"], x["device"]) for x in cards], [(o["id"], "Kris Price", "krisdesk")])
        s, _ = self.status(o)
        self.assertEqual(s["state"], "pending")
        a, c = self.answer(ta, o["id"])
        self.assertEqual((c, a["state"], a["name"]), (200, "let", "Kris Price"))
        s, _ = self.status(o)
        self.assertEqual((s["state"], s["by"], s["room"], s["role"]), ("let", "Ada", "alpha", "publisher"))
        # no room code: the grant opens it -- the role is the access code's (as with the room code)
        m, c = self.mint(ASK, rc="", admit=self.grant(o))
        self.assertEqual((c, m["role"], m["admit"]["room"]), (200, "publisher", "alpha"), m)
        cl = kr.verify_token(m["tokens"]["member"], self.svc.key)
        self.assertEqual(cl["acc"], o["id"])
        self.assertLessEqual(cl["exp"] - int(time.time()), ka.TOKEN_TTL)
        same, c2 = self.mint("kris-dd45", rc=ROOM_CODE)   # what typing the code gives someone else
        self.assertEqual((c2, same["role"]), (200, m["role"]))
        self.assertFalse(kr.claims_admin(cl, "alpha"))
        self.assertEqual(self.beat(ta)["access"]["asks"], [])          # the card is gone once answered

    def test_role_viewer_stays_viewer_admin_becomes_publisher(self):
        ta = self.tok(ADM)
        self.beat(ta)
        for host, code, want, typed in ((VIEW, "view-1", "viewer", "viewer"), (ASK2, "adm-1", "publisher", "admin")):
            o, c = self.ask(host=host, code=code)
            self.assertEqual(c, 200, o)
            self.answer(ta, o["id"])
            m, c = self.mint(host, code=code, rc="", admit=self.grant(o))
            self.assertEqual((c, m["role"]), (200, want))
            t, _ = self.mint(host, code=code, rc=ROOM_CODE)            # the code path: an admin code gives admin there --
            self.assertEqual(t["role"], typed)                         # the grant never does (Kenton: "never admin")
            self.assertFalse(kr.claims_admin(kr.verify_token(m["tokens"]["member"], self.svc.key), "alpha"))

    def test_declined_names_the_admitter_and_cools_down(self):
        ta = self.tok(ADM)
        self.beat(ta)
        o, _ = self.ask()
        a, c = self.answer(ta, o["id"], allow=False, by="Ada Lovelace")
        self.assertEqual((c, a["state"]), (200, "declined"))
        s, _ = self.status(o)
        self.assertEqual((s["state"], s["by"]), ("declined", "Ada Lovelace"))
        self.assertNotIn("room", s)
        m, c = self.mint(ASK, rc="", admit=self.grant(o))
        self.assertEqual((c, m["admit"]), (403, "expired"))
        o2, c = self.ask()
        self.assertEqual(c, 429)
        self.assertIn("wait a little", o2["error"])

    def test_cancel_closes_the_cards(self):
        ta = self.tok(ADM)
        self.beat(ta)
        o, _ = self.ask()
        self.beat(ta)
        c, code = self.svc.access_api({"op": "cancel", "id": o["id"], "key": o["key"]}, None, PEER)
        self.assertEqual((code, c["state"]), (200, "cancelled"))
        acc = self.beat(ta)["access"]
        self.assertEqual(acc["asks"], [])
        self.assertEqual([(x["id"], x["state"]) for x in acc["closed"]], [(o["id"], "cancelled")])
        bad, code = self.svc.access_api({"op": "cancel", "id": o["id"], "key": "x" * 32}, None, PEER)
        self.assertEqual(code, 404)


class Timing(Base):
    def test_timeout_after_two_minutes(self):
        ta = self.tok(ADM)
        self.beat(ta)
        o, _ = self.ask()
        d = self.svc._acc()
        t0 = d.asks[o["id"]]["at"]
        with d.lock:
            d.present["alpha"][ADM]["at"] = t0 + ka.ASK_TTL   # still there, nobody answered
        d.sweep(t0 + ka.ASK_TTL - 1)
        self.assertEqual(d.status(o["id"], o["key"], t0 + ka.ASK_TTL - 1)[0]["state"], "pending")
        d.sweep(t0 + ka.ASK_TTL + 0.5)
        self.assertEqual(d.status(o["id"], o["key"], t0 + ka.ASK_TTL + 0.5)[0]["state"], "timeout")
        self.assertEqual(d.answer(o["id"], "alpha", ADM, "admin", True, "", t0 + ka.ASK_TTL + 1)[1], 409)

    def test_everyone_who_could_answer_left(self):
        ta = self.tok(ADM)
        self.beat(ta)
        o, _ = self.ask()
        d = self.svc._acc()
        t0 = time.time()
        d.sweep(t0 + ka.PRESENT_S + 1)            # the admin's page went quiet: the clock for "nobody" starts
        d.sweep(t0 + ka.PRESENT_S + 1 + ka.NOBODY_GRACE)
        self.assertEqual(d.status(o["id"], o["key"], t0 + 60)[0]["state"], "nobody")

    def test_grant_redeem_window_idle_end_and_keepalive(self):
        d = ka.AccessDesk()
        t0 = 1000.0
        d.beat("alpha", ADM, "Ada", "admin", False, t0)
        o, _ = d.ask("alpha", ASK, "Kris", "publisher", False, now=t0)
        d.answer(o["id"], "alpha", ADM, "admin", True, "Ada", t0 + 5)
        g = ka.grant_token(o["id"], o["key"])
        self.assertEqual(d.check(g, ASK, "alpha", t0 + 5 + ka.REDEEM_S + 1)[0], "expired")   # never came in
        d.beat("alpha", ADM, "Ada", "admin", False, t0 + 200)
        o, _ = d.ask("alpha", ASK2, "Lou", "publisher", False, now=t0 + 200)
        d.answer(o["id"], "alpha", ADM, "admin", True, "Ada", t0 + 201)
        g = ka.grant_token(o["id"], o["key"])
        self.assertEqual(d.check(g, ASK2, "alpha", t0 + 202)[0], "ok")                         # came in
        self.assertEqual(d.check(g, ASK2, "alpha", t0 + 202 + ka.IDLE_S - 1)[0], "ok")         # a re-mint within the visit
        self.assertTrue(d.keep(o["id"], ASK2, "alpha", t0 + 202 + ka.IDLE_S + 100))            # beating from the room
        self.assertFalse(d.keep(o["id"], ASK2, "beta", t0 + 202 + ka.IDLE_S + 101))            # another room keeps nothing
        self.assertEqual(d.check(g, ASK2, "alpha", t0 + 202 + 2 * ka.IDLE_S + 99)[0], "ok")    # a brief drop / an update relaunch
        self.assertEqual(d.check(g, ASK2, "alpha", t0 + 202 + 4 * ka.IDLE_S)[0], "expired")    # left: ask again
        self.assertEqual(d.check(g, ASK2, "alpha", t0 + 202 + 4 * ka.IDLE_S + 1)[0], "expired")


class Nobody(Base):
    def test_nobody_present(self):
        o, c = self.ask()
        self.assertEqual((c, o["ok"], o.get("nobody")), (409, False, True))
        self.assertIn("nobody who can let you in", o["error"])
        self.assertNotIn("key", o)

    def test_members_without_the_right_never_count(self):
        tp = self.tok(PUB, code="pub-1")
        self.assertEqual(self.beat(tp)["access"], {"asks": [], "closed": []})   # a publisher who typed the code: not an answerer
        tw = self.tok("pete-cc34", code="pub-1")
        self.beat(tw, roomKey="z" * 32)                                     # a wrong room key is nobody's
        self.assertEqual(self.ask()[1], 409)

    def test_an_old_page_never_counts(self):
        ta = self.tok(ADM)
        self.beat(ta, acc=False)                                           # a 0.21.88 page: no `acc` in its beat
        self.assertEqual(self.ask()[0].get("nobody"), True)

    def test_creator_with_the_room_key_counts(self):
        tc = self.tok(PUB, code="pub-1")
        self.beat(tc, roomKey=ROOM_KEY)
        o, c = self.ask()
        self.assertEqual(c, 200, o)
        a, c = self.answer(tc, o["id"], roomKey=ROOM_KEY)
        self.assertEqual((c, a["state"]), (200, "let"))


class FirstAnswerWins(Base):
    def test_two_admins(self):
        ta, tb = self.tok(ADM), self.tok(ADM2)
        self.beat(ta)
        self.beat(tb)
        o, _ = self.ask()
        self.assertEqual([x["id"] for x in self.beat(ta)["access"]["asks"]], [o["id"]])
        self.assertEqual([x["id"] for x in self.beat(tb)["access"]["asks"]], [o["id"]])
        a, c = self.answer(tb, o["id"], by="Bea")
        self.assertEqual(c, 200)
        late, c = self.answer(ta, o["id"], allow=False)
        self.assertEqual((c, late["already"], late["by"]), (409, "let", "Bea"))
        acc = self.beat(ta)["access"]
        self.assertEqual((acc["asks"], [(x["state"], x["by"]) for x in acc["closed"]]), ([], [("let", "Bea")]))
        self.assertEqual(self.status(o)[0]["state"], "let")

    def test_several_askers_stack(self):
        ta = self.tok(ADM)
        self.beat(ta)
        ids = [self.ask(host=h)[0]["id"] for h in (ASK, ASK2, VIEW)]
        self.assertEqual([x["id"] for x in self.beat(ta)["access"]["asks"]], ids)


class Forged(Base):
    def setUp(self):
        super().setUp()
        self.ta = self.tok(ADM)
        self.beat(self.ta)
        self.o, _ = self.ask()

    def assertRefused(self, out, code):
        self.assertEqual(code, 403, out)
        self.assertEqual(self.status(self.o)[0]["state"], "pending")

    def test_a_publisher_in_the_room(self):
        self.assertRefused(*self.answer(self.tok(PUB, code="pub-1"), self.o["id"]))

    def test_a_wrong_room_key(self):
        tp = self.tok(PUB, code="pub-1")
        self.beat(tp, roomKey="z" * 32)
        self.assertRefused(*self.answer(tp, self.o["id"], roomKey="z" * 32))

    def test_an_admin_of_another_room(self):
        tb = self.tok(ADM2, room="beta", rc="beta-code")
        self.beat(tb)
        self.assertRefused(*self.answer(tb, self.o["id"]))

    def test_an_admin_in_the_lobby(self):
        tl = self.tok(ADM2, room="main", rc="")
        self.assertRefused(*self.answer(tl, self.o["id"]))

    def test_an_admin_not_in_the_room_now(self):
        tb = self.tok(ADM2)                                   # an admin token for alpha, but its page never beat there
        self.assertRefused(*self.answer(tb, self.o["id"]))

    def test_no_token_or_a_forged_one(self):
        self.assertRefused(*self.svc.access_api({"op": "answer", "id": self.o["id"], "allow": True}, None, PEER))
        self.assertRefused(*self.svc.access_api({"op": "answer", "id": self.o["id"], "allow": True}, "Bearer eyJhbGciOi.x.y", PEER))

    def test_a_personal_guest_never_answers_for_the_owner(self):
        self.assertEqual(self.svc._acc_kind_local("me-0123456789ab", "member", ROOM_KEY), "")
        self.assertEqual(self.svc._acc_kind_local("me-0123456789ab", "admin", ""), "")
        self.assertEqual(self.svc._acc_kind_local("main", "admin", ""), "")


class Limits(Base):
    def test_rate_per_asker_and_room_then_lockout(self):
        ta = self.tok(ADM)
        self.beat(ta)
        codes = [self.ask(peer="10.0.0.20")[1] for _ in range(3)]
        self.assertEqual(codes, [200, 200, 200])                 # one open at a time: each replaces the one before
        d = self.svc._acc()
        self.assertEqual(sum(1 for a in d.asks.values() if a["state"] == "pending"), 1)
        o, c = self.ask(peer="10.0.0.20")
        self.assertEqual((c, "too many" in o["error"]), (429, True))
        for _ in range(4):                                        # abuse counts toward the relay's lockout
            o, c = self.ask(peer="10.0.0.20")
        self.assertEqual(c, 429)
        self.assertIn("too many attempts", o["error"])
        o, c = self.mint("other-1234", peer="10.0.0.20")          # the lockout is the relay's own (the mint too)
        self.assertEqual(c, 429)

    def test_rate_per_room_and_per_host(self):
        d = ka.AccessDesk()
        d.beat("alpha", ADM, "Ada", "admin", False, 0.0)
        d.beat("beta", ADM2, "Bea", "admin", False, 0.0)
        hosts = ["h%02d-%04x" % (i, i) for i in range(ka.RATE_ROOM[0] + 1)]
        res = [d.ask("alpha", h, "x", "publisher", False, now=1.0)[1] for h in hosts]
        self.assertEqual(res[-1], 429)
        d2 = ka.AccessDesk()
        for r in ("r1", "r2", "r3", "r4", "r5", "r6", "r7"):
            d2.beat(r, "a%s-0001" % r, "A", "admin", False, 0.0)
        res = [d2.ask(r, ASK, "Kris", "publisher", False, now=1.0)[1] for r in ("r1", "r2", "r3", "r4", "r5", "r6", "r7")]
        self.assertEqual(res, [200] * ka.RATE_HOST[0] + [429])

    def test_wrong_access_code_counts(self):
        for _ in range(4):
            o, c = self.ask(code="nope", peer="10.0.0.30")
            self.assertEqual(c, 403)
        o, c = self.ask(code="nope", peer="10.0.0.30")
        self.assertEqual(c, 429)

    def test_banned_device_cannot_ask(self):
        self.beat(self.tok(ADM))
        now = int(time.time())
        self.svc.bans.add({"room": "alpha", "host": ASK, "remotes": [], "target": ASK, "by": "admin", "at": now, "until": now + 600})
        o, c = self.ask()
        self.assertEqual(c, 403)
        self.assertIn("removed", o["error"])

    def test_never_the_lobby_and_unlocked_rooms_need_no_ask(self):
        self.assertEqual(self.ask(room="main")[1], 403)
        self.assertEqual(self.ask(room="lib")[1], 403)
        o, c = self.ask(room="gamma")
        self.assertEqual((c, o.get("open")), (409, True))
        self.assertEqual(self.ask(host="no host")[1], 400)


class Grant(Base):
    def let_in(self, host=ASK, code="pub-1"):
        ta = self.tok(ADM)
        self.beat(ta)
        o, _ = self.ask(host=host, code=code)
        self.answer(ta, o["id"])
        return o

    def test_only_the_asker_device_and_only_that_room(self):
        o = self.let_in()
        m, c = self.mint(ASK2, rc="", admit=self.grant(o))            # someone else's device: a guess (counted)
        self.assertEqual((c, m.get("admit")), (403, "wrong"))
        m, c = self.mint(ASK, room="beta", rc="", admit=self.grant(o))
        self.assertEqual((c, m.get("admit")), (403, "room"))
        m, c = self.mint(ASK, rc="", admit="ka-%s-%s" % (o["id"], "y" * 32))
        self.assertEqual((c, m.get("admit")), (403, "wrong"))
        m, c = self.mint(ASK, rc="", admit=self.grant(o))
        self.assertEqual(c, 200)
        m, c = self.mint(ASK, rc="", admit=self.grant(o))            # a re-mint in the same visit
        self.assertEqual(c, 200)

    def test_pending_grant_does_not_open(self):
        self.beat(self.tok(ADM))
        o, _ = self.ask()
        m, c = self.mint(ASK, rc="", admit=self.grant(o))
        self.assertEqual((c, m.get("admit")), (403, "pending"))

    def test_without_the_grant_the_code_is_still_needed(self):
        self.let_in()
        m, c = self.mint(ASK, rc="")
        self.assertEqual(c, 403)
        self.assertIn("wrong room code", m["error"])

    def test_the_access_code_is_still_checked(self):
        o = self.let_in()
        m, c = self.mint(ASK, code="nope", rc="", admit=self.grant(o))
        self.assertEqual(c, 403)
        self.assertIn("wrong access code", m["error"])

    def test_beats_keep_the_visit_and_leaving_ends_it(self):
        o = self.let_in()
        m, _ = self.mint(ASK, rc="", admit=self.grant(o))
        d = self.svc._acc()
        rec = d.asks[o["id"]]
        rec["seen"] -= ka.IDLE_S - 5
        self.beat(m["tokens"]["member"], acc=False)                  # an admitted page's beat (its token says acc)
        self.assertGreater(rec["seen"], time.time() - 2)
        rec["seen"] -= ka.IDLE_S + 1                                 # gone that long: over
        m2, c = self.mint(ASK, rc="", admit=self.grant(o))
        self.assertEqual((c, m2.get("admit")), (403, "expired"))
        self.assertEqual(self.status(o)[0]["state"], "ended")

    def test_the_feed_carries_no_secret(self):
        o = self.let_in()
        f = self.svc.access_feed()
        self.assertNotIn(o["key"], repr(f))
        self.assertEqual(f["states"][o["id"]]["dig"], ka.digest(o["key"]))
        self.assertIsNone(self.svc._acc_m().d)


class MyRoom(Base):
    def setUp(self):
        super().setUp()
        self.slug, _ = self.st.personal_create("Ada Lovelace", "ada-secret")
        self.towner = self.tok(ADM, code="pub-1", room=self.slug, rc="ada-secret")

    def test_owner_present_gets_the_card_and_lets_in(self):
        b = self.beat(self.towner, name="Ada Lovelace")
        self.assertTrue(b["personal"]["owner"])
        o, c = self.ask(room="", via=ADM)                           # from Everyone online: the room the owner is in
        self.assertEqual(c, 200, o)
        self.assertEqual([x["id"] for x in self.beat(self.towner)["access"]["asks"]], [o["id"]])
        a, c = self.answer(self.towner, o["id"], by="Ada Lovelace")
        self.assertEqual(c, 200)
        s, _ = self.status(o)
        self.assertEqual((s["state"], s["room"], s["personal"]), ("let", self.slug, True))
        m, c = self.mint(ASK, room=self.slug, rc="", admit=self.grant(o))
        self.assertEqual(c, 200, m)
        self.assertTrue(m["guest"] and m["personal"])
        cl = kr.verify_token(m["tokens"]["member"], self.svc.key)
        self.assertEqual((cl["pg"], cl["acc"]), (1, o["id"]))
        st = self.beat(m["tokens"]["member"], acc=False)["personal"]
        self.assertTrue(st["access"])                               # not "removed your access"

    def test_owner_absent_is_nobody(self):
        o, c = self.ask(room=self.slug)
        self.assertEqual((c, o.get("nobody")), (409, True))
        o, c = self.ask(room="", via=ADM)
        self.assertEqual(c, 404)

    def test_only_the_owner_answers(self):
        self.beat(self.towner, name="Ada Lovelace")
        o, _ = self.ask(room=self.slug)
        ta = self.tok(ADM2, code="adm-1", room="alpha")             # a relay admin elsewhere
        self.beat(ta)
        self.assertEqual(self.answer(ta, o["id"])[1], 403)
        self.st.personal_share(self.slug, PUB, "Pete", True)       # a guest in My room
        tg, c = self.mint(PUB, room=self.slug, rc="")
        self.assertEqual(c, 200, tg)
        tg = tg["tokens"]["member"]
        self.assertEqual(self.beat(tg).get("access"), {"asks": [], "closed": []})
        self.assertEqual(self.answer(tg, o["id"])[1], 403)
        self.assertEqual(self.status(o)[0]["state"], "pending")

    def test_shared_people_need_not_ask(self):
        self.beat(self.towner)
        self.st.personal_share(self.slug, ASK, "Kris", True)
        o, c = self.ask(room=self.slug)
        self.assertEqual((c, o.get("shared")), (409, True))


class Spoke(unittest.TestCase):
    """A spoke and a hub wired back to back (the federation call is a direct method call)."""

    def setUp(self):
        self.hs = kr.AuthStore(tempfile.mkdtemp())
        self.hs.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        lock_room(self.hs, "alpha")
        self.hub = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, self.hs)
        self.hub._bearer_relay = lambda b: True
        ss = kr.AuthStore(tempfile.mkdtemp())
        ss.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        self.sp = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, ss)
        self.sp._p_spoke = lambda: True
        self.calls = []
        self.sp._hub_fed = lambda body, timeout=6: (self.calls.append(body) or self.hub.rooms_fed(dict(body), "Bearer fed"))
        self.sp._acc_send = lambda body: self.sp._hub_fed(body)   # synchronous here (a thread in the relay)
        self.sp.hub_room = lambda slug, code=None: "ok" if code == ROOM_CODE else "wrong"

    def tearDown(self):
        self.hub.close()
        self.sp.close()

    def poll(self):   # the bans long-poll's answer reaching the spoke
        self.sp.access_mirror_apply({"access": self.hub.access_feed()})

    def test_round_trip(self):
        o, c = self.hub.token({"room": "alpha", "code": "adm-1", "roomCode": ROOM_CODE, "host": ADM}, PEER)
        ta = o["tokens"]["member"]
        self.hub.people_api({"op": "beat", "acc": 1, "name": "Ada"}, "Bearer " + ta, PEER)
        # an admin on the SPOKE too: its beat goes to the hub with the spoke's vouch
        o, c = self.sp.token({"room": "alpha", "code": "adm-1", "roomCode": ROOM_CODE, "host": ADM2}, PEER)
        self.assertEqual(c, 200, o)
        tb = o["tokens"]["member"]
        self.sp.people_api({"op": "beat", "acc": 1, "name": "Bea"}, "Bearer " + tb, PEER)
        self.assertEqual((self.calls[-1]["aop"], self.calls[-1]["vouch"]), ("beat", "admin"))
        o, c = self.sp.access_api({"op": "ask", "room": "alpha", "code": "pub-1", "host": ASK, "name": "Kris"}, None, PEER)
        self.assertEqual(c, 200, o)
        self.assertEqual((self.calls[-1]["aop"], self.calls[-1]["vouch"]), ("ask", "publisher"))
        self.assertEqual(self.sp.access_api({"op": "status", "id": o["id"], "key": o["key"]}, None, PEER)[0]["state"], "pending")
        self.poll()
        b = self.sp.people_api({"op": "beat", "acc": 1, "name": "Bea"}, "Bearer " + tb, PEER)[0]
        self.assertEqual([x["id"] for x in b["access"]["asks"]], [o["id"]])
        n = len(self.calls)
        a, c = self.sp.access_api({"op": "answer", "id": o["id"], "allow": True, "by": "Bea"}, "Bearer " + tb, PEER)
        self.assertEqual((c, a["state"]), (200, "let"))
        self.assertEqual((self.calls[n]["aop"], self.calls[n]["vouch"], self.calls[n]["host"]), ("answer", "admin", ADM2))
        self.poll()
        s, _ = self.sp.access_api({"op": "status", "id": o["id"], "key": o["key"]}, None, PEER)
        self.assertEqual((s["state"], s["by"], s["room"]), ("let", "Bea", "alpha"))
        bad, c = self.sp.access_api({"op": "status", "id": o["id"], "key": "q" * 32}, None, PEER)
        self.assertEqual(c, 404)
        m, c = self.sp.token({"room": "alpha", "code": "pub-1", "roomCode": "", "host": ASK, "admit": ka.grant_token(o["id"], o["key"])}, PEER)
        self.assertEqual((c, m["role"]), (200, "publisher"), m)
        self.assertEqual(self.calls[-1]["aop"], "check")
        # the hub's own admin sees the closed note
        acc = self.hub.people_api({"op": "beat", "acc": 1}, "Bearer " + ta, PEER)[0]["access"]
        self.assertEqual([(x["state"], x["by"]) for x in acc["closed"]], [("let", "Bea")])
        # the admitted page on the spoke keeps its grant alive through the hub
        self.sp.people_api({"op": "beat"}, "Bearer " + m["tokens"]["member"], PEER)
        self.assertEqual(self.calls[-1]["aop"], "keep")

    def test_forged_vouch_from_a_spoke_page(self):
        o, c = self.hub.token({"room": "alpha", "code": "adm-1", "roomCode": ROOM_CODE, "host": ADM}, PEER)
        self.hub.people_api({"op": "beat", "acc": 1}, "Bearer " + o["tokens"]["member"], PEER)
        ask, _ = self.sp.access_api({"op": "ask", "room": "alpha", "code": "pub-1", "host": ASK}, None, PEER)
        o, c = self.sp.token({"room": "alpha", "code": "pub-1", "roomCode": ROOM_CODE, "host": PUB}, PEER)
        a, c = self.sp.access_api({"op": "answer", "id": ask["id"], "allow": True}, "Bearer " + o["tokens"]["member"], PEER)
        self.assertEqual(c, 403)
        # even a hand-made fed call claiming "admin" for a host that is not in the room is refused at the hub
        a, c = self.hub.rooms_fed({"op": "access", "aop": "answer", "vouch": "admin", "room": "alpha", "host": PUB, "id": ask["id"], "allow": True}, "Bearer fed")
        self.assertEqual(c, 403)

    def test_old_or_unreachable_hub(self):
        self.sp._hub_fed = lambda body, timeout=6: ({"ok": False, "error": "bad room"}, 400)
        o, c = self.sp.access_api({"op": "ask", "room": "alpha", "code": "pub-1", "host": ASK}, None, PEER)
        self.assertEqual((c, o.get("old")), (501, True))
        self.sp._hub_fed = lambda body, timeout=6: None
        o, c = self.sp.access_api({"op": "ask", "room": "alpha", "code": "pub-1", "host": ASK}, None, PEER)
        self.assertEqual((c, o.get("hubDown")), (503, True))
        m, c = self.sp.token({"room": "alpha", "code": "pub-1", "roomCode": "", "host": ASK, "admit": "ka-%s-%s" % ("a" * 12, "b" * 32)}, PEER)
        self.assertEqual((c, m.get("hubDown")), (503, True))

    def test_mirror_cleans_what_it_is_given(self):
        m = ka.AccessMirror()
        m.apply({"pending": [{"id": "zz", "room": "alpha", "to": [ADM]}, {"id": "a" * 12, "room": "alpha", "name": "<b>K</b>", "to": [ADM, "bad host"], "at": 1, "exp": 9e9}],
                 "closed": [{"id": "b" * 12, "state": "bogus"}], "states": {"c" * 12: {"state": "let", "dig": "nope"}}})
        self.assertEqual([x["id"] for x in m.d["pending"]], ["a" * 12])
        self.assertEqual((m.d["pending"][0]["name"], m.d["pending"][0]["to"]), ("bK/b", [ADM]))
        self.assertEqual((m.d["closed"], m.d["states"]), ([], {}))


class Wiring(unittest.TestCase):
    def test_proxy_build_and_route(self):
        self.assertIn('"/api/access",', read("kastr_serve.py"))
        self.assertIn('"--hidden-import", "kastr_access"', read("build.py"))
        rel = read("kastr_relay.py")
        self.assertIn('elif path == "/api/access":', rel)
        self.assertIn('"access": self.access_feed(),', rel)
        self.assertIn("self.access_mirror_apply(d)", rel)

    def test_line_endings(self):
        for name, crlf in (("kastr_access.py", False), ("kastr_relay.py", False), ("kastr_serve.py", True), ("moq-watch-lite.html", True)):
            with open(os.path.join(HERE, name), "rb") as f:
                raw = f.read()
            if crlf:
                self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)
            else:
                self.assertNotIn(b"\r\n", raw, name)

    def test_page(self):
        pg = read("moq-watch-lite.html")
        self.assertIn("Ask for access", pg)
        self.assertIn("is asking to join", pg)
        self.assertIn("No answer \\u2014 try again or ask for the code", pg)
        self.assertIn("didn\\u2019t let you in", pg)
        self.assertIn("Nobody who can let you in is in ", pg)
        self.assertRegex(pg, r'op: "beat"[^\n]*acc: 1')                    # the page says it can answer asks
        self.assertIn("admit: admTok", pg)                                   # the grant rides the mint
        m = re.search(r"function accCardsPaint\(.*?\r?\n  }\r?\n", pg, re.S)
        self.assertTrue(m)
        self.assertNotIn(".focus(", m.group(0))                              # the card never takes the keyboard
        self.assertIn('kastr.access', pg)                                    # the grant survives a reload in this window only

    def test_join_room_page(self):
        """Kenton: "an 'Ask for access' in the same pop-up as the code entry" -- the Join room page's Room code field too."""
        pg = read("moq-watch-lite.html")
        row = pg[pg.index('<label class="f" id="joinPwdRow"'):pg.index('<label class="f asi-sw" id="joinKeepRow"')]
        self.assertIn('id="joinPwd"', row)
        self.assertIn('<button type="button" id="joinAskBtn" class="ghost" hidden', row)     # beside the field, hidden until it applies
        self.assertIn('<div id="joinAskWait" role="status" hidden>', row)                     # the waiting state, with Cancel
        self.assertIn('id="joinAskCancel">Cancel</button>', row)
        # shown only for a listed LOCKED room (never a new room) when asking is possible on this relay
        self.assertIn('ab.hidden = isNew || !rec?.locked || !accCanAsk(rec.slug, true);', pg)
        # a let-in visit has no code: both join paths of a listed room skip the page's own code check (the mint checks the grant)
        self.assertEqual(pg.count("if (!accGrantFor(slug)) { const why = await lockedRoomRefusal(rec, joinEls.joinPwd.value);"), 2)
        m = re.search(r"let accGateAsk = null;.*?\r?\n  // Everyone online:", pg, re.S)
        self.assertTrue(m)
        gate = m.group(0)
        self.assertIn("await accAskRun(accGateApi(slug), { room: slug, title: roomTitle(slug), code: access, name: name || undefined });", gate)
        self.assertIn("joinNow();", gate)                                   # Let in -> the gate's own join goes on
        self.assertNotIn("Escape", gate)                                    # the Join room page has no Escape (0.21.89) -- Cancel only
        self.assertIn('gateMsg("Enter this relay\\u2019s access code first.")', gate)   # never a guess that the lockout counts
        self.assertIn('code: t.code ?? (authAccessCode || "")', pg)         # the gate's typed access code rides the ask
        # a room link (?room=<locked room>) picks its room once the list has it (the first list may come without it)
        self.assertIn("if (invited && !gateLinkUsed && list.some((r) => r.slug === invited)) { want = invited; gateLinkUsed = true; }", pg)


if __name__ == "__main__":
    unittest.main()
