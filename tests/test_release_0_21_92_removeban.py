# -*- coding: utf-8 -*-
"""v0.21.92 REMOVE / BAN. Kenton (2026-10-28): "When in My room, or an admin for other rooms, give an option on people that
allows me to kick from the room. This doesn't kick them for any specific timeframe. This doesn't block them from coming back.
Add an option to ban (timeframe)."

POST /api/kick {token, room, mode, ...}: "remove" closes their sessions and sets NO ban (they may come straight back); "ban"
removes them and refuses them for 15 min / 1 h / 24 h / 7 days or until lifted (by device, by the person key their page
sends, and by an invite link only they had used); "list" / "lift" drive the Bans lists. No `mode` = a 0.21.91 page: 0.17.0's
kick (an hour by default). In My room only its owner may; elsewhere the room's admin token. Nobody removes themselves; only a
fleet admin removes a fleet admin. A ban reaches every spoke through the bans long-poll, and so does a Lift; a closed room's
bans go with it (templates close their room at End). Loopback sockets only, no outside network."""
import json
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

BOSS, BOB, CAROL, OWNER, EVE = "boss-ff66", "bob-cd34", "carol-1a2b", "kenton-ab12", "eve-ef56"


def _read(name):
    with open(os.path.join(HERE, name), "rb") as f:
        return f.read().decode("utf-8")


def store():
    st = kr.AuthStore(tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def mint(svc, room, host, code="pub-1", op=None, invite=None, room_code=None, peer="10.0.0.7"):
    body = {"room": room, "code": code, "host": host}
    if op:
        body["op"] = op
    if invite is not None:
        body["invite"] = invite
    if room_code is not None:
        body["roomCode"] = room_code
    return svc.token(body, peer)


def tok(svc, *a, **kw):
    o, c = mint(svc, *a, **kw)
    assert c == 200, (c, o)
    return o["tokens"]["member"]


def kick(svc, t, room, **kw):
    return svc.kick(dict({"token": t, "room": room}, **kw), "10.0.0.1")


def connect(svc, t, sid, remote="10.0.0.9:5000"):
    return svc.session({"event": "connect", "id": sid, "remote": remote, "path": "/", "query": "jwt=" + t}, "127.0.0.1")


def revalidate(svc, sid, remote="10.0.0.9:5000"):
    return svc.session({"event": "revalidate", "id": sid, "remote": remote, "path": "/"}, "127.0.0.1")


class Rooms(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        self.svc.store.touch_room("yard", "kenton")
        self.adm = tok(self.svc, "yard", BOSS, code="adm-1", op="boss")

    def tearDown(self):
        self.svc.close()

    def test_remove_does_not_block(self):
        t = tok(self.svc, "yard", BOB, op="bob")
        self.assertEqual(connect(self.svc, t, "s-bob")[1], 200)
        o, c = kick(self.svc, self.adm, "yard", mode="remove", target=BOB + "/bob/p1", by="Boss", byOp="boss")
        self.assertEqual((c, o["mode"], o["ban"]), (200, "remove", None), o)
        self.assertEqual(len(o["revoked"]), 1)
        self.assertEqual(revalidate(self.svc, "s-bob")[1], 403)          # the session it closed stays closed
        self.assertEqual(self.svc.bans.active("yard"), [])                 # no ban
        t2 = tok(self.svc, "yard", BOB, op="bob")                          # an immediate rejoin works
        self.assertEqual(connect(self.svc, t2, "s-bob2")[1], 200)
        self.assertEqual(revalidate(self.svc, "s-bob2")[1], 200)

    def test_each_ban_length_until_it_ends(self):
        for secs in kr.AuthService.BAN_SECS:
            with self.subTest(secs=secs):
                t0 = time.time()
                o, c = kick(self.svc, self.adm, "yard", mode="ban", secs=secs, target=BOB + "/bob", who="Bob", by="Boss")
                self.assertEqual((c, o["mode"]), (200, "ban"), o)
                self.assertAlmostEqual(o["ban"]["until"], t0 + secs, delta=3)
                r, c = mint(self.svc, "yard", BOB, op="bob")
                self.assertEqual(c, 403, r)
                self.assertEqual(r["error"], "removed from this room by an admin")   # 0.21.91 pages match this text
                self.assertEqual((r["ban"]["kind"], r["ban"]["forever"], r["ban"]["by"], r["ban"]["who"]), ("ban", False, "Boss", "Bob"))
                self.assertNotIn("remotes", r["ban"])
                # the same person on another device (by their name) -- and a different person there is fine
                self.assertEqual(mint(self.svc, "yard", "bob-laptop-0b0b", op="bob")[1], 403)
                self.assertEqual(mint(self.svc, "yard", CAROL, op="carol")[1], 200)
                self.assertEqual(mint(self.svc, "dock", BOB, op="bob")[1], 200)   # this room only
                with mock.patch.object(kr.time, "time", return_value=t0 + secs + 5):
                    self.assertEqual(mint(self.svc, "yard", BOB, op="bob")[1], 200)
                self.svc.bans.clear("yard")

    def test_bad_length_and_who_may(self):
        self.assertEqual(kick(self.svc, self.adm, "yard", mode="ban", secs=60, target=BOB + "/bob")[1], 400)
        self.assertEqual(kick(self.svc, self.adm, "yard", mode="bogus", target=BOB + "/bob")[1], 400)
        pub = tok(self.svc, "yard", CAROL, op="carol")
        for mode in ("remove", "ban", "list", "lift"):
            self.assertEqual(kick(self.svc, pub, "yard", mode=mode, secs=900, target=BOB + "/bob", host=BOB)[1], 403)
        other = tok(self.svc, "dock", BOSS, code="adm-1")                   # an admin token for another room
        self.assertEqual(kick(self.svc, other, "yard", mode="remove", target=BOB + "/bob")[1], 403)

    def test_until_lifted_and_lift(self):
        o, c = kick(self.svc, self.adm, "yard", mode="ban", forever=True, target=BOB + "/bob", who="Bob", by="Boss")
        self.assertEqual((c, o["ban"]["forever"]), (200, True), o)
        with mock.patch.object(kr.time, "time", return_value=time.time() + 400 * 86400):
            self.assertEqual(mint(self.svc, "yard", BOB, op="bob")[1], 403)   # a year on: still out
        r, _ = mint(self.svc, "yard", BOB, op="bob")
        self.assertTrue(r["ban"]["forever"])
        lst, c = kick(self.svc, self.adm, "yard", mode="list")
        self.assertEqual((c, [(b["host"], b["who"], b["by"], b["forever"]) for b in lst["bans"]]), (200, [(BOB, "Bob", "Boss", True)]))
        self.assertNotIn("remotes", json.dumps(lst))
        o, c = kick(self.svc, self.adm, "yard", mode="lift", host=BOB)
        self.assertEqual((c, o["lifted"], o["bans"]), (200, 1, []), o)
        self.assertEqual(mint(self.svc, "yard", BOB, op="bob")[1], 200)

    def test_no_self_removal(self):
        o, c = kick(self.svc, self.adm, "yard", mode="remove", target=BOSS + "/boss")
        self.assertEqual((c, o.get("self")), (400, True), o)
        # the same person on another device of theirs (the page's own person key)
        o, c = kick(self.svc, self.adm, "yard", mode="ban", secs=900, target="boss-phone-1111/boss", byOp="boss")
        self.assertEqual((c, o.get("self")), (400, True), o)
        self.assertEqual(self.svc.bans.active(), [])

    def test_admin_may_remove_a_fleet_admin(self):
        tok(self.svc, "dock", "admin2-2222", code="adm-1")                  # another fleet admin's device
        o, c = kick(self.svc, self.adm, "yard", mode="remove", target="admin2-2222/al")
        self.assertEqual(c, 200, o)

    def test_old_kick_keeps_the_hour(self):
        t0 = time.time()
        o, c = kick(self.svc, self.adm, "yard", target=BOB + "/bob")         # a 0.21.91 page: no `mode`
        self.assertEqual(c, 200, o)
        self.assertAlmostEqual(o["ban"]["until"], t0 + 3600, delta=3)
        self.assertNotEqual(o["ban"].get("kind"), "ban")
        r, c = mint(self.svc, "yard", BOB, op="bob")
        self.assertEqual((c, r["ban"]["kind"]), (403, "kick"), r)
        self.assertEqual(mint(self.svc, "yard", "bob-laptop-0b0b", op="bob")[1], 200)   # an old kick is by device only
        o, c = kick(self.svc, self.adm, "yard", target=CAROL + "/carol", until=600)
        self.assertAlmostEqual(o["ban"]["until"], t0 + 600, delta=3)

    def test_a_banned_persons_invite_link_is_refused(self):
        mem = "Bearer " + tok(self.svc, "yard", CAROL, op="carol")
        own = self.svc.invite_create_api({"room": "yard", "ttl": 86400, "by": "Carol"}, mem, "10.0.0.1")[0]
        shared = self.svc.invite_create_api({"room": "yard", "ttl": 86400, "by": "Carol"}, mem, "10.0.0.1")[0]
        self.assertEqual(mint(self.svc, "yard", BOB, code="", invite=own["token"])[1], 200)       # only Bob used this one
        self.assertEqual(mint(self.svc, "yard", "dan-3c3c", code="", invite=shared["token"])[1], 200)
        self.assertEqual(mint(self.svc, "yard", BOB, code="", invite=shared["token"])[1], 200)    # ... and Dan's too
        o, c = kick(self.svc, self.adm, "yard", mode="ban", secs=86400, target=BOB + "/bob")
        self.assertEqual(c, 200, o)
        r, c = mint(self.svc, "yard", BOB, code="", invite=own["token"])
        self.assertEqual((c, r["ban"]["kind"]), (403, "ban"), r)
        r, c = mint(self.svc, "yard", "bob-new-4d4d", code="", invite=own["token"])               # their link, another device
        self.assertEqual((c, r["ban"]["kind"]), (403, "ban"), r)
        self.assertEqual(mint(self.svc, "yard", "dan-3c3c", code="", invite=shared["token"])[1], 200)   # a shared link: others fine
        stored = json.dumps(self.svc.bans.active())
        for t in (own["token"], shared["token"], self.adm):
            self.assertNotIn(t, stored)                                      # ids only, never a link or a token

    def test_a_closed_room_takes_its_bans(self):
        kick(self.svc, self.adm, "yard", mode="ban", forever=True, target=BOB + "/bob")
        kick(self.svc, self.adm, "dock", mode="ban", forever=True, target=BOB + "/bob")   # (no admin token for dock: refused)
        self.assertEqual(len(self.svc.bans.active("yard")), 1)
        self.svc.store.close_room("yard", why="pres")                      # a template's room closed at End
        self.assertEqual(self.svc.bans.active("yard"), [])
        self.assertEqual(mint(self.svc, "yard", BOB, op="bob")[1], 200)


class MyRoom(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        o, c = kr.personal_op(self.svc.store, {"op": "create", "name": "Kenton", "code": "abcd1234", "access": "pub-1"}, "10.0.0.5")
        assert c == 200, o
        self.slug = o["slug"]
        self.own = tok(self.svc, self.slug, OWNER, room_code="abcd1234", op="kenton")
        self.svc.people_api({"op": "share", "to": BOB, "name": "Bob", "on": True}, "Bearer " + self.own, "10.0.0.7")
        self.beat(self.own)

    def tearDown(self):
        self.svc.close()

    def beat(self, t):
        o, c = self.svc.people_api({"op": "beat"}, "Bearer " + t, "10.0.0.7")
        assert c == 200, o
        return o

    def test_owner_removes_then_bans_an_invite_guest(self):
        link = self.svc.invite_create_api({"room": self.slug, "ttl": 3600}, "Bearer " + self.own, "10.0.0.7")[0]["token"]
        g = tok(self.svc, self.slug, EVE, code="", invite=link, op="eve")
        self.assertEqual(connect(self.svc, g, "s-eve")[1], 200)
        o, c = kick(self.svc, self.own, self.slug, mode="remove", target=EVE + "/eve", by="Kenton")
        self.assertEqual((c, len(o["revoked"])), (200, 1), o)
        self.assertEqual(revalidate(self.svc, "s-eve")[1], 403)
        st = self.beat(g)["personal"]
        self.assertEqual((st["access"], st["removed"]["by"]), (False, "Kenton"), st)   # her page says why (a 0.21.91 page: access false)
        g2 = tok(self.svc, self.slug, EVE, code="", invite=link, op="eve")             # straight back in with the same link
        self.assertNotIn("removed", self.beat(g2)["personal"])
        self.assertEqual(connect(self.svc, g2, "s-eve2")[1], 200)
        o, c = kick(self.svc, self.own, self.slug, mode="ban", secs=900, target=EVE + "/eve", who="Eve", by="Kenton")
        self.assertEqual(c, 200, o)
        self.assertEqual(revalidate(self.svc, "s-eve2")[1], 403)
        st = self.beat(g2)["personal"]
        self.assertEqual((st["access"], st["banned"]["by"], st["banned"]["kind"]), (False, "Kenton", "ban"), st)
        r, c = mint(self.svc, self.slug, EVE, code="", invite=link, op="eve")
        self.assertEqual((c, r["ban"]["who"]), (403, "Eve"), r)
        self.assertEqual(mint(self.svc, self.slug, "eve-tab-5e5e", code="", invite=link)[1], 403)   # her link, another device
        lst, c = kick(self.svc, self.own, self.slug, mode="list")
        self.assertEqual((c, [b["host"] for b in lst["bans"]]), (200, [EVE]))
        self.assertEqual(kick(self.svc, self.own, self.slug, mode="lift", host=EVE)[1], 200)
        self.assertEqual(mint(self.svc, self.slug, EVE, code="", invite=link, op="eve")[1], 200)

    def test_owner_bans_a_person_with_access(self):
        o, c = kick(self.svc, self.own, self.slug, mode="ban", forever=True, target=BOB + "/bob", who="Bob")
        self.assertEqual(c, 200, o)
        r, c = mint(self.svc, self.slug, BOB, op="bob")                     # still on the access list -- still refused
        self.assertEqual((c, r["ban"]["forever"]), (403, True), r)
        # giving access again never lifts a Ban (Lift does)
        self.svc.people_api({"op": "share", "to": BOB, "name": "Bob", "on": True}, "Bearer " + self.own, "10.0.0.7")
        self.assertEqual(mint(self.svc, self.slug, BOB, op="bob")[1], 403)
        self.svc.people_api({"op": "share", "to": BOB, "name": "Bob", "on": False}, "Bearer " + self.own, "10.0.0.7")
        self.assertEqual(self.svc.bans.active(self.slug)[0].get("kind"), "ban")   # the minute's "personal" kick never replaced it

    def test_only_the_owner(self):
        g = tok(self.svc, self.slug, BOB, op="bob")                         # a guest (a person with access)
        for mode in ("remove", "ban", "list", "lift"):
            o, c = kick(self.svc, g, self.slug, mode=mode, secs=900, target=EVE + "/eve", host=EVE)
            self.assertEqual(c, 403, (mode, o))
        adm = tok(self.svc, "yard", BOSS, code="adm-1")                     # an admin of another room
        self.assertEqual(kick(self.svc, adm, self.slug, mode="remove", target=BOB + "/bob")[1], 403)
        self.assertEqual(kick(self.svc, self.own, self.slug, mode="remove", target=OWNER + "/kenton")[0].get("self"), True)

    def test_owner_cannot_remove_a_fleet_admin(self):
        tok(self.svc, "yard", BOSS, code="adm-1")                           # BOSS's device holds the admin code
        o, c = kick(self.svc, self.own, self.slug, mode="ban", secs=900, target=BOSS + "/boss")
        self.assertEqual((c, o.get("fleetAdmin")), (403, True), o)
        o, c = kick(self.svc, self.own, self.slug, mode="remove", target=BOSS + "/boss")
        self.assertEqual(c, 403, o)
        self.assertEqual(self.svc.bans.active(self.slug), [])


class OnASpoke(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: base, fed_token=lambda: self.fed)
        self.hub.store.touch_room("north", "kenton")

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def wait(self, fn, secs=6):
        end = time.time() + secs
        while time.time() < end:
            if fn():
                return True
            time.sleep(0.1)
        return False

    def test_a_hub_ban_and_its_lift_reach_the_spoke(self):
        adm = tok(self.hub, "north", BOSS, code="adm-1")
        t = tok(self.spoke, "north", BOB, op="bob")
        self.assertEqual(connect(self.spoke, t, "s-bob")[1], 200)
        o, c = kick(self.hub, adm, "north", mode="ban", secs=604800, target=BOB + "/bob", who="Bob", by="Boss")
        self.assertEqual(c, 200, o)
        self.assertGreaterEqual(self.spoke.pull_hub_bans(), 1)
        self.assertEqual(revalidate(self.spoke, "s-bob")[1], 403)
        r, c = mint(self.spoke, "north", "bob-laptop-0b0b", op="bob")       # the name rides along to the spoke
        self.assertEqual((c, r["ban"]["kind"], r["ban"]["who"]), (403, "ban", "Bob"), r)
        self.assertAlmostEqual(r["ban"]["until"], time.time() + 604800, delta=5)   # never capped at a day
        self.assertEqual(kick(self.hub, adm, "north", mode="lift", host=BOB)[1], 200)
        self.spoke.pull_hub_bans()
        self.assertEqual(mint(self.spoke, "north", BOB, op="bob")[1], 200)

    def test_a_spoke_ban_reaches_the_hub_and_a_hub_lift_comes_back(self):
        adm = tok(self.spoke, "north", BOSS, code="adm-1")
        o, c = kick(self.spoke, adm, "north", mode="ban", secs=604800, target=BOB + "/bob", who="Bob")
        self.assertEqual(c, 200, o)
        self.assertTrue(self.wait(lambda: any(b.get("kind") == "ban" for b in self.hub.bans.active("north"))))
        hb = self.hub.bans.active("north")[0]
        self.assertGreater(hb["until"], time.time() + 6 * 86400)          # the hub keeps the length (an old hub: a day)
        self.assertTrue(self.wait(lambda: (self.spoke.bans.active("north") or [{}])[0].get("via") == "hub"))
        self.assertEqual(mint(self.hub, "north", BOB, op="bob")[1], 403)
        hadm = tok(self.hub, "north", BOSS, code="adm-1")
        self.assertEqual(kick(self.hub, hadm, "north", mode="lift", host=BOB)[1], 200)
        self.spoke.pull_hub_bans()
        self.assertEqual(self.spoke.bans.active("north"), [])
        self.assertEqual(mint(self.spoke, "north", BOB, op="bob")[1], 200)

    def test_a_spoke_lift_reaches_the_hub(self):
        adm = tok(self.spoke, "north", BOSS, code="adm-1")
        kick(self.spoke, adm, "north", mode="ban", forever=True, target=BOB + "/bob")
        self.assertTrue(self.wait(lambda: bool(self.hub.bans.active("north"))))
        self.assertEqual(kick(self.spoke, adm, "north", mode="lift", host=BOB)[1], 200)
        self.assertTrue(self.wait(lambda: not self.hub.bans.active("north")))

    def test_a_spoke_remove_closes_hub_sessions_without_a_ban(self):
        t = tok(self.hub, "north", BOB, op="bob")
        self.assertEqual(connect(self.hub, t, "s-hub-bob")[1], 200)
        adm = tok(self.spoke, "north", BOSS, code="adm-1")
        self.assertEqual(kick(self.spoke, adm, "north", mode="remove", target=BOB + "/bob")[1], 200)
        self.assertTrue(self.wait(lambda: revalidate(self.hub, "s-hub-bob")[1] == 403))
        self.assertEqual(self.hub.bans.active(), [])
        self.assertEqual(mint(self.hub, "north", BOB, op="bob")[1], 200)

    def test_old_spokes_still_understood(self):
        # a 0.21.91 spoke forwards a kick with only the old fields: the hub caps it at a day, as before
        now = time.time()
        o, c = self.hub.kick({"ban": {"room": "north", "host": BOB, "target": BOB + "/bob", "by": "admin", "until": now + 604800}},
                             "10.0.0.2", "Bearer " + self.fed)
        self.assertEqual(c, 200, o)
        self.assertLessEqual(o["ban"]["until"], now + 86400 + 2)
        self.assertNotEqual(o["ban"].get("kind"), "ban")
        # ... and the long-poll rows keep the six fields a 0.21.91 spoke reads
        d, c = self.hub.bans_for_spoke("Bearer " + self.fed)
        self.assertEqual(c, 200, d)
        for k in ("room", "host", "target", "by", "at", "until"):
            self.assertIn(k, d["bans"][0])
        # a 0.21.91 spoke's Lift-less list: our Remove/Lift bodies are separate keys it never sends
        self.assertEqual(self.hub.kick({"lift": {"room": "north", "host": BOB}}, "10.0.0.2", "Bearer " + self.fed)[1], 200)
        self.assertEqual(self.hub.bans.active(), [])


class StandbyCopy(unittest.TestCase):
    """The standby hub's copy (/api/hub/replica), the take-over, the hand-back: a Ban survives a failover as on the main hub."""

    def setUp(self):
        self.key = os.urandom(32)
        self.main = kr.AuthService("127.0.0.1", 0, self.key, 4443, store())
        self.main.standby_info = lambda: {"node": "sb-node", "secret": "s3cr"}
        self.fed = "Bearer " + kr._mint(self.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.main.store.touch_room("yard", "kenton")
        self.adm = tok(self.main, "yard", BOSS, code="adm-1", op="boss")
        self.sb = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, kr.AuthStore(tempfile.mkdtemp()))

    def tearDown(self):
        for s in (self.main, self.sb):
            s.close()

    def copy(self, since=None):
        o, c = self.main.replica({"node": "sb-node", "since": since or {}, "wait": 0}, self.fed, "10.0.0.2")
        self.assertEqual(c, 200, o)
        return o

    def test_export_take_over_refuses_like_the_main_hub(self):
        self.assertEqual(kick(self.main, self.adm, "yard", mode="ban", forever=True, target=BOB + "/bob", who="Bob", by="Boss")[1], 200)
        self.assertEqual(kick(self.main, self.adm, "yard", mode="ban", secs=604800, target=CAROL + "/carol", who="Carol", by="Boss")[1], 200)
        self.assertEqual(kick(self.main, self.adm, "yard", target=EVE + "/eve", until=1800)[1], 200)   # a 0.21.91 page's kick
        o = self.copy()
        rows = {r["host"]: r for r in o["bans"]}
        for r in rows.values():                       # what a 0.21.91 standby reads, unchanged
            for k in kr.BAN_BUNDLE_OLD:
                self.assertIn(k, r)
            self.assertIsInstance(r["until"], int)
            self.assertNotIn("remotes", r)
        self.assertEqual((rows[BOB]["kind"], rows[BOB]["forever"], rows[BOB]["name"], rows[BOB]["who"]), ("ban", True, "bob", "Bob"))
        self.assertNotIn("kind", rows[EVE])            # a kick stays a kick
        blob = json.dumps(o["bans"])
        for secret in ("adm-1", "pub-1", "view-1", self.adm, self.fed[7:]):
            self.assertNotIn(secret, blob)
        # the take-over: the store and the bans
        self.sb.store.import_bundle(o["store"])
        self.assertEqual(kr.ban_bundle_take(self.sb.bans, o["bans"]), 3)
        self.assertEqual(kr.ban_bundle_take(self.sb.bans, o["bans"]), 0)          # idempotent
        r, c = mint(self.sb, "yard", BOB, op="bob")
        self.assertEqual((c, r["ban"]["kind"], r["ban"]["forever"]), (403, "ban", True), r)
        self.assertGreater(r["ban"]["until"], time.time() + 9 * 365 * 86400)         # forever stays forever
        self.assertEqual(mint(self.sb, "yard", "bob-laptop-0b0b", op="bob")[1], 403)  # the person key too
        r, c = mint(self.sb, "yard", CAROL, op="carol")
        self.assertEqual(c, 403)
        self.assertAlmostEqual(r["ban"]["until"], time.time() + 604800, delta=5)       # 7 days, not a day
        self.assertEqual(mint(self.sb, "yard", EVE, op="eve")[1], 403)                 # the kick by device ...
        self.assertEqual(mint(self.sb, "yard", "eve-laptop-0c0c", op="eve")[1], 200)   # ... only
        self.assertEqual(mint(self.sb, "yard", "dan-1d1d", op="dan")[1], 200)

    def test_lifts_reach_the_copy_and_come_back_at_hand_back(self):
        kick(self.main, self.adm, "yard", mode="ban", forever=True, target=BOB + "/bob", who="Bob", by="Boss")
        kick(self.main, self.adm, "yard", mode="ban", forever=True, target=CAROL + "/carol", who="Carol", by="Boss")
        o = self.copy()
        self.assertEqual(kick(self.main, self.adm, "yard", mode="lift", host=CAROL)[1], 200)   # the main hub's Lift ...
        o2 = self.copy({"store": o["storeVer"], "bans": o["bansVer"]})
        self.assertEqual([r["host"] for r in o2["bans"]], [BOB])                               # ... leaves the copy
        self.sb.store.import_bundle(o["store"])
        kr.ban_bundle_take(self.sb.bans, o2["bans"])
        self.assertEqual(mint(self.sb, "yard", CAROL, op="carol")[1], 200)
        # the standby is the hub now: its admin lifts Bob; the hand-back carries the Lift to the main hub
        sadm = tok(self.sb, "yard", BOSS, code="adm-1", op="boss")
        self.assertEqual(kick(self.sb, sadm, "yard", mode="lift", host=BOB)[1], 200)
        self.assertEqual(mint(self.sb, "yard", BOB, op="bob")[1], 200)
        hand = json.loads(json.dumps({"bans": kr.ban_bundle_rows(self.sb.bans.active()), "lifted": list(self.sb.bans.lifts)}))
        self.assertEqual(mint(self.main, "yard", BOB, op="bob")[1], 403)                     # before the hand-back
        kr.ban_bundle_take(self.main.bans, hand["bans"])
        self.assertEqual(kr.ban_bundle_lifts(self.main.bans, hand["lifted"]), 1)
        self.assertEqual(mint(self.main, "yard", BOB, op="bob")[1], 200)
        # a Ban made after that Lift is not undone by it
        with mock.patch.object(kr.time, "time", return_value=time.time() + 60):
            kick(self.main, self.adm, "yard", mode="ban", secs=3600, target=BOB + "/bob", who="Bob", by="Boss")
        self.assertEqual(kr.ban_bundle_lifts(self.main.bans, hand["lifted"]), 0)
        self.assertEqual(len(self.main.bans.active("yard")), 1)
        # the Lifts are kept on disk (a standby restarted mid-failover still hands them back)
        self.assertEqual([(x["room"], x["host"]) for x in kr.BanList(self.sb.store.state_dir).lifts], [("yard", BOB)])

    def test_a_0_21_91_hand_over_reads_the_rows(self):
        kick(self.main, self.adm, "yard", mode="ban", forever=True, target=BOB + "/bob", who="Bob", by="Boss")
        b = self.copy()["bans"][0]
        old = {"room": str(b["room"]), "host": (str(b["host"]) if b.get("host") else None), "remotes": [],   # 0.21.91's own import
               "target": str(b.get("target") or "")[:120], "by": str(b.get("by") or "")[:40],
               "at": int(b.get("at") or 0), "until": int(b["until"])}
        bl = kr.BanList(tempfile.mkdtemp())
        bl.add(old)
        self.assertIsNotNone(bl.hit("yard", BOB))
        self.assertIsNone(bl.hit("yard", "bob-laptop-0b0b", name="bob"))   # by device only on an old hub, as STATUS.md says


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = _read("moq-watch-lite.html")

    def test_crlf_kept(self):
        raw = self.page.encode("utf-8")
        self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))
        self.assertNotIn("\r\n", _read("kastr_relay.py"))

    def test_menu_items_and_dialog(self):
        p = self.page
        self.assertIn('label: "Remove " + nm + " from the room"', p)
        self.assertIn('label: "Ban " + nm + "\\u2026", danger: true', p)
        for t in ("15 minutes", "1 hour", "24 hours", "7 days", "Until I lift it"):
            self.assertIn('label: "' + t + '"', p)
        self.assertIn('#mineMenu .mi.danger', p)
        self.assertIn('(it.danger ? " danger" : "")', p)
        self.assertNotIn('value: "akick"', p)                             # the old admin-only item is gone from every menu
        # the ban dialog is a segmented choice -- no checkbox anywhere in it
        blk = p[p.index("function rbBanAsk"):p.index("function rbSend")]
        self.assertNotIn("checkbox", blk)
        self.assertIn('role="radiogroup"', blk)

    def test_wire(self):
        p = self.page
        self.assertIn("mode: opt.mode, secs: opt.secs, forever: !!opt.forever", p)
        self.assertIn('window.__adminKick(cmd.target, { mode: "remove" })', p)   # a plain announce-kick no longer blocks
        self.assertNotIn("re-entry blocked for", p)
        self.assertIn('op: String(window.__publisher?.opSlug?.() || "").toLowerCase() || undefined', p)
        self.assertIn("You\\u2019re banned from ", p)
        self.assertIn('if (kind === "banned") return { title: rbBannedText(room, info?.ban)', p)
        self.assertIn("const rbt = rbEndedText(room, kind, who, owner, info);", p)
        self.assertIn('if (st.banned || st.removed) { rbPersonalOut(room, st); return; }', p)
        self.assertIn('<div class="rsrow rsban" hidden><span class="lbl">Bans</span>', p)
        self.assertIn('<div class="rsrow msban" hidden><span class="lbl">Bans</span>', p)

    def test_marked_blocks(self):
        self.assertGreaterEqual(self.page.count("0.21.92 I: remove / ban"), 20)
        self.assertGreaterEqual(_read("kastr_relay.py").count("0.21.92 I: remove / ban"), 15)


if __name__ == "__main__":
    unittest.main()
