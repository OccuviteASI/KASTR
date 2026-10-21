# -*- coding: utf-8 -*-
"""v0.21.78 MY ROOM SHARED. Kenton: "Put a 'My room' option in the room rail at the top ... set the passcode and give information
about the my room capabilities"; "I need to be able to share out access to 'my room' as wanted" (people with access + invite
links; guests WATCH + TALK; only the owner -- or one guest raised to co-arrange -- arranges); "Only allow people in 'My room' if
the owner is in it. If the owner leaves the room, it should kick everyone to the lobby"; "Allow right clicking on a person on
the left and inviting to the room you're in, or my room and have it display for that user to join or ignore" (and the same
menu on the People panel's rows).

The hub keeps people (device hosts) + the co-arranger in the personal room's record, the owner's presence LIVE (owner beats on
POST /api/people, ~4 s; gone after PERSONAL_OWNER_GRACE s or on "leave"), refuses a guest's mint while the owner is out, ends
guest sessions when the owner leaves (here, and on every spoke through the bans long-poll's `personal`), and hands person
invites (an invite link bound to one device) to the invited page on its next beat. Loopback sockets only, no outside network."""
import hashlib
import io
import os
import re
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

OWNER, GUEST, OTHER = "kenton-ab12", "bob-cd34", "eve-ef56"
A_CAM = "alpha/box-1a2b/kenton/camera.hang"


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def mint(svc, room, host=OWNER, code="pub-1", room_code=None, invite=None, peer="10.0.0.7"):
    body = {"room": room, "code": code, "host": host}
    if room_code is not None:
        body["roomCode"] = room_code
    if invite is not None:
        body["invite"] = invite
    return svc.token(body, peer)


def tok(svc, *a, **kw):
    o, c = mint(svc, *a, **kw)
    assert c == 200, (c, o)
    return o["tokens"]["member"]


def claims(svc, t):
    return kr.verify_token(t, svc.key)


def people(svc, t, body, peer="10.0.0.7"):
    return svc.people_api(body, "Bearer " + t, peer)


def connect(svc, t, sid, remote="10.0.0.9:5000"):
    return svc.session({"event": "connect", "id": sid, "remote": remote, "path": "/", "query": "jwt=" + t}, "127.0.0.1")


def revalidate(svc, sid, remote="10.0.0.9:5000"):
    return svc.session({"event": "revalidate", "id": sid, "remote": remote, "path": "/"}, "127.0.0.1")


class Hub(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        o, c = kr.personal_op(self.svc.store, {"op": "create", "name": "Kenton", "code": "abcd1234", "access": "pub-1"}, "10.0.0.5")
        assert c == 200, o
        self.slug = o["slug"]
        self.own = tok(self.svc, self.slug, room_code="abcd1234")

    def tearDown(self):
        self.svc.close()

    def share(self, host=GUEST, name="Bob", on=True, t=None):
        return people(self.svc, t or self.own, {"op": "share", "to": host, "name": name, "on": on})

    def beat(self, t, **kw):
        o, c = people(self.svc, t, dict({"op": "beat"}, **kw))
        assert c == 200, o
        return o

    def test_owner_token_names_its_device(self):
        cl = claims(self.svc, self.own)
        self.assertEqual((cl["personal"], cl["ph"], cl["put"]), (1, OWNER, [self.slug + "/" + OWNER]))
        self.assertEqual(kr.claims_identity(cl), (self.slug, OWNER))
        # the owner's mint alone does not open the room (a side token for "Pin to My room" mints the same way)
        self.assertFalse(self.svc.personal_open(self.slug))

    def test_owner_gate(self):
        self.assertEqual(self.share()[1], 200)
        o, c = mint(self.svc, self.slug, host=GUEST)
        self.assertEqual((c, o.get("ownerAway"), o.get("owner")), (403, True, "Kenton"), o)
        self.assertEqual(o["error"], "Kenton isn't in their room right now")
        self.assertNotIn("tokens", o)
        # a stranger learns nothing about the owner's presence (a wrong code, counted)
        o, c = mint(self.svc, self.slug, host=OTHER)
        self.assertEqual(c, 403)
        self.assertNotIn("ownerAway", o)
        # the owner's page beats from My room -> open
        b = self.beat(self.own)
        self.assertEqual(b["personal"], {"owner": True, "open": True})
        self.assertTrue(self.svc.personal_open(self.slug))
        o, c = mint(self.svc, self.slug, host=GUEST)
        self.assertEqual(c, 200, o)
        self.assertEqual((o["guest"], o["personal"], o["owner"], o["role"], o["co"]), (True, True, "Kenton", "publisher", False))
        self.assertEqual(list(o["tokens"]), ["member"])                   # no registry (~channels) token
        cl = claims(self.svc, o["tokens"]["member"])
        self.assertEqual((cl["pg"], cl["ph"], cl["get"]), (1, GUEST, self.slug))
        self.assertNotIn("personal", cl)
        self.assertEqual(kr.claims_identity(cl), (self.slug, GUEST))
        # the owner's presence fades after the grace
        self.assertEqual(self.svc.personal_sweep(time.time() + kr.PERSONAL_OWNER_GRACE + 1), [self.slug])
        self.assertFalse(self.svc.personal_open(self.slug))
        o, c = mint(self.svc, self.slug, host=GUEST)
        self.assertEqual((c, o.get("ownerAway")), (403, True))

    def test_guest_puts_media_chat_under_their_host_never_public(self):
        self.share()
        self.beat(self.own)
        g = tok(self.svc, self.slug, host=GUEST, code="view-1")       # a viewer access code -- still WATCH + TALK here
        cl = claims(self.svc, g)
        self.assertEqual(cl["put"], [self.slug + "/" + GUEST])            # media, room.json + chat.json (~member) under their host
        self.assertEqual(kr.claims_role(cl), "publisher")
        puts = " ".join(map(str, cl["put"]))
        for kind in ("~presence", "~state", "~since", "~talking", "~chat", "~channels", "~admin"):
            self.assertNotIn(kind, puts)
        grant = kr.claims_to_grant(cl)
        self.assertFalse(any(p.startswith(("~presence", "~state", "~channels", "~talking", "~chat")) for p in grant["publish"]))
        self.assertIn(self.slug, " ".join(grant["subscribe"]))

    def test_board_owner_and_co_arranger_only(self):
        self.share()
        self.share(OTHER, "Eve")
        self.beat(self.own)
        g = tok(self.svc, self.slug, host=GUEST)
        e = tok(self.svc, self.slug, host=OTHER)
        a = tok(self.svc, "alpha", host=GUEST)
        spot = {"room": self.slug, "op": "spot", "target": self.slug + "/" + OWNER + "/kenton/camera.hang"}
        o, c = self.svc.board_post(spot, "Bearer " + g, "10.0.0.7")
        self.assertEqual(c, 403, o)
        self.assertIn("owner", o["error"])
        self.assertEqual(self.svc.board_post({"room": self.slug, "op": "pin", "path": A_CAM, "tokens": {"alpha": a}}, "Bearer " + g, "10.0.0.7")[1], 403)
        self.assertEqual(self.svc.board_post(spot, "Bearer " + self.own, "10.0.0.7")[1], 200)
        # the owner raises Bob to co-arrange
        o, c = people(self.svc, self.own, {"op": "co", "to": GUEST})
        self.assertEqual((c, o["co"]), (200, GUEST), o)
        self.assertEqual(self.svc.board_post(dict(spot, op="unspot"), "Bearer " + g, "10.0.0.7")[1], 200)
        self.assertEqual(self.svc.board_post(spot, "Bearer " + e, "10.0.0.7")[1], 403)       # Eve still watches + talks
        self.assertTrue(self.beat(g)["personal"]["co"])
        self.assertFalse(self.beat(e)["personal"]["co"])
        # a guest never shares the room, never lists who may come in, never raises anyone
        for body in ({"op": "list"}, {"op": "share", "to": OTHER, "on": True}, {"op": "co", "to": OTHER}, {"op": "seen"}):
            self.assertEqual(people(self.svc, g, body)[1], 403, body)
        # lowering: only the owner arranges again; removing Bob also drops his co-arranging
        people(self.svc, self.own, {"op": "co", "to": ""})
        self.assertEqual(self.svc.board_post(spot, "Bearer " + g, "10.0.0.7")[1], 403)
        people(self.svc, self.own, {"op": "co", "to": GUEST})
        self.share(on=False)
        self.assertEqual(self.svc.store.personal_info(self.slug)["co"], "")

    def test_kick_on_leave(self):
        self.share()
        self.beat(self.own)
        g = tok(self.svc, self.slug, host=GUEST)
        grant, c = connect(self.svc, g, "s-guest")
        self.assertEqual(c, 200, grant)
        self.assertEqual(connect(self.svc, self.own, "s-owner")[1], 200)
        st = self.beat(g)["personal"]
        self.assertEqual((st["open"], st["owner"], st["access"]), (True, "Kenton", True))
        # the owner switches rooms (or closes KASTR: the page's beacon) -> everyone else goes, at once
        o, c = people(self.svc, self.own, {"op": "leave"})
        self.assertEqual(c, 200, o)
        self.assertFalse(self.svc.personal_open(self.slug))
        st = self.beat(g)["personal"]
        self.assertEqual((st["open"], st["why"], st["owner"]), (False, "left", "Kenton"))
        self.assertEqual(revalidate(self.svc, "s-guest")[1], 403)          # the hub stops the guest's session
        self.assertEqual(connect(self.svc, g, "s-guest2")[1], 403)         # and refuses a new one / a re-mint
        self.assertEqual(mint(self.svc, self.slug, host=GUEST)[0].get("ownerAway"), True)
        self.assertEqual(revalidate(self.svc, "s-owner")[1], 200)          # the owner's own session is not a guest's
        # the leave beacon carries the token in its body (a closing page cannot set headers)
        self.beat(self.own)
        self.assertTrue(self.svc.personal_open(self.slug))
        o, c = self.svc.people_api({"op": "leave", "token": self.own}, None, "10.0.0.7")
        self.assertEqual(c, 200, o)
        self.assertFalse(self.svc.personal_open(self.slug))
        # two devices of the owner: one leaving keeps the room open while the other is in
        own2 = tok(self.svc, self.slug, host="kenton-1ab2", room_code="abcd1234")
        self.beat(self.own)
        self.beat(own2)
        people(self.svc, self.own, {"op": "leave"})
        self.assertTrue(self.svc.personal_open(self.slug))
        # silence = gone (KASTR closed without a beacon, the network went): "gone"
        self.svc.personal_sweep(time.time() + kr.PERSONAL_OWNER_GRACE + 1)
        self.assertEqual(self.beat(g)["personal"]["why"], "gone")

    def test_people_with_access_grant_and_revoke(self):
        o, c = self.share()
        self.assertEqual(c, 200, o)
        self.assertEqual([(p["host"], p["name"]) for p in o["people"]], [(GUEST, "Bob")])
        self.assertEqual(self.svc.store.personal_shared_with(GUEST), [{"slug": self.slug, "owner": "Kenton"}])
        # Bob's rail learns it from his beats (any room)
        bob_alpha = tok(self.svc, "alpha", host=GUEST)
        self.assertEqual(self.beat(bob_alpha)["shared"], [{"slug": self.slug, "owner": "Kenton", "open": False}])
        self.beat(self.own)
        self.assertEqual(self.beat(bob_alpha)["shared"][0]["open"], True)
        g = tok(self.svc, self.slug, host=GUEST)
        self.assertEqual(connect(self.svc, g, "s-bob")[1], 200)
        # removed: his session ends now, his re-mint fails, his beat says so; the record keeps no trace of him
        o, c = self.share(on=False)
        self.assertEqual((c, o["people"]), (200, []))
        self.assertEqual(revalidate(self.svc, "s-bob")[1], 403)
        self.assertEqual(mint(self.svc, self.slug, host=GUEST)[1], 403)
        self.assertFalse(self.beat(g)["personal"]["access"])
        self.assertEqual(self.beat(bob_alpha)["shared"], [])
        # given back: the minute's kick is lifted
        self.share()
        self.assertEqual(mint(self.svc, self.slug, host=GUEST)[1], 200)
        # bad requests, the cap
        self.assertEqual(self.share(host="nobody")[1], 400)
        old = kr.PERSONAL_PEOPLE_MAX
        kr.PERSONAL_PEOPLE_MAX = 1
        try:
            o, c = self.share(OTHER, "Eve")
            self.assertEqual(c, 400, o)
        finally:
            kr.PERSONAL_PEOPLE_MAX = old
        # the people survive a restart (the room record), the live presence does not
        again = kr.AuthStore(self.svc.store.state_dir)
        self.assertEqual(list(again.personal_info(self.slug)["people"]), [GUEST])

    def test_people_seen_on_the_hub(self):
        self.svc.client_checkin({"node": OTHER, "name": "Eve", "version": "0.21.78"}, "10.0.0.8")
        self.beat(tok(self.svc, "alpha", host=GUEST), name="Bob")
        o, c = people(self.svc, self.own, {"op": "seen"})
        self.assertEqual(c, 200, o)
        seen = {p["host"]: p["name"] for p in o["people"]}
        self.assertEqual((seen.get(OTHER), seen.get(GUEST)), ("Eve", "Bob"))
        self.assertNotIn(OWNER, seen)                                     # not me
        self.assertFalse({"ip", "hostname", "user"} & set(o["people"][0]))   # names only, never where or who on the machine
        # the Users list names a web page from its beats
        connect(self.svc, tok(self.svc, "alpha", host="web-0a1b2c3d-9f9f"), "s-web")
        self.beat(tok(self.svc, "alpha", host="web-0a1b2c3d-9f9f"), name="Phone")
        row = [r for r in self.svc.clients_view() if r["node"] == "web-0a1b2c3d-9f9f"]
        self.assertEqual(row[0]["name"], "Phone")

    def test_invite_links_for_my_room(self):
        # the owner makes one (any room's member could not; a guest could not)
        o, c = self.svc.invite_create_api({"room": self.slug, "ttl": 3600}, "Bearer " + self.own, "10.0.0.7")
        self.assertEqual(c, 200, o)
        link = o["token"]
        self.share()
        self.beat(self.own)
        g = tok(self.svc, self.slug, host=GUEST)
        o2, c2 = self.svc.invite_create_api({"room": self.slug, "ttl": 3600}, "Bearer " + g, "10.0.0.7")
        self.assertEqual(c2, 403, o2)
        self.assertEqual(self.svc.store.invite_create(self.slug, 3600)[2], 403)   # never without the owner's say
        # Eve (not in the people list) joins with the link -- while the owner is in
        o, c = mint(self.svc, self.slug, host=OTHER, code="", invite=link)
        self.assertEqual(c, 200, o)
        cl = claims(self.svc, o["tokens"]["member"])
        self.assertEqual((cl["pg"], cl["inv"], o["guest"]), (1, o["invite"]["id"], True))
        self.assertTrue(self.beat(o["tokens"]["member"])["personal"]["access"])
        # the link does not bypass the owner's presence
        people(self.svc, self.own, {"op": "leave"})
        o, c = mint(self.svc, self.slug, host=OTHER, code="", invite=link)
        self.assertEqual((c, o.get("ownerAway")), (403, True), o)
        # the owner lists and revokes its links (no roomKey, no admin code)
        o, c = self.svc.invite_manage_api("list", {"room": self.slug}, "Bearer " + self.own, "10.0.0.7")
        self.assertEqual((c, len(o["invites"])), (200, 1), o)
        self.assertEqual(self.svc.invite_manage_api("list", {"room": self.slug}, "Bearer " + g, "10.0.0.7")[1], 403)
        o, c = self.svc.invite_manage_api("revoke", {"room": self.slug, "all": True}, "Bearer " + self.own, "10.0.0.7")
        self.assertEqual((c, o["revoked"]), (200, 1), o)

    def test_never_listed_even_when_shared(self):
        self.share()
        self.beat(self.own)
        g = tok(self.svc, self.slug, host=GUEST)
        connect(self.svc, g, "s-g")
        self.assertNotIn(self.slug, [r["slug"] for r in self.svc.store.rooms_public()])
        self.assertNotIn(self.slug, self.svc.store.boards_public(personal=False))
        self.assertNotIn(self.slug, self.svc.store.kept_slugs())
        o, _ = mint(self.svc, self.slug, host=GUEST)
        self.assertNotIn("registry", o["tokens"])
        rows = self.svc.clients_view()
        self.assertTrue(all(self.slug in r["rooms"] for r in rows if r["node"] == GUEST))   # the hub's own Users table (admins)
        page = _read("kastr_relay.py")
        self.assertIn('st["rooms"] = [s for s in self.store.room_slugs() if not is_personal(s)]', page)

    def test_person_invite_delivery_rate_limit_and_sender_in_room(self):
        salt = "00112233"   # a LOCKED room: the person invite opens it without its room code
        self.svc.store.put_room("alpha", {"salt": salt, "hash": hashlib.sha256((salt + "alpha-code").encode()).hexdigest(), "roomKey": "k",
                                          "at": time.time(), "persistent": True, "creator": "Kenton", "created": time.time()})
        self.assertEqual(mint(self.svc, "alpha", host=GUEST)[1], 403)
        # Kenton is in room alpha; he invites Bob (in the Lobby) to alpha
        k_alpha = tok(self.svc, "alpha", room_code="alpha-code")
        bob_lobby = tok(self.svc, "main", host=GUEST)
        o, c = people(self.svc, k_alpha, {"op": "invite", "to": GUEST, "toName": "Bob", "by": "Kenton"})
        self.assertEqual(c, 200, o)
        self.assertEqual((o["room"], o["to"]), ("alpha", GUEST))
        box = self.beat(bob_lobby)["inbox"]
        self.assertEqual(len(box), 1)
        it = box[0]
        self.assertEqual((it["kind"], it["room"], it["title"], it["by"], it["from"]), ("invite", "alpha", "alpha", "Kenton", OWNER))
        self.assertTrue(kr.INVITE_RE.match(it["token"]))
        self.assertEqual(self.beat(bob_lobby)["inbox"], [])                # taken once
        # the link opens alpha for Bob's device only (Join), no access code needed
        self.assertEqual(mint(self.svc, "alpha", host=OTHER, code="", invite=it["token"])[1], 403)
        o, c = mint(self.svc, "alpha", host=GUEST, code="", invite=it["token"])
        self.assertEqual((c, o["role"]), (200, "publisher"), o)
        rows = self.svc.store.invites_public("alpha")
        self.assertEqual([r["person"] for r in rows], ["Bob"])             # Room settings says whom it was for
        # the Lobby has nothing to invite to; a guest never invites into someone's room; no self-invites
        self.assertEqual(people(self.svc, bob_lobby, {"op": "invite", "to": OWNER})[1], 403)
        self.share()
        self.beat(self.own)
        g = tok(self.svc, self.slug, host=GUEST)
        o, c = people(self.svc, g, {"op": "invite", "to": OTHER})
        self.assertEqual(c, 403, o)
        self.assertEqual(people(self.svc, k_alpha, {"op": "invite", "to": OWNER})[1], 400)
        self.assertEqual(people(self.svc, k_alpha, {"op": "invite", "to": "not a host"})[1], 400)
        # the owner invites to My room from another room with My room's own token (the sender owns it)
        o, c = people(self.svc, self.own, {"op": "invite", "to": OTHER, "toName": "Eve", "by": "Kenton"})
        self.assertEqual((c, o["room"], o["away"]), (200, self.slug, False), o)
        eve_alpha = tok(self.svc, "beta", host=OTHER)
        it = self.beat(eve_alpha)["inbox"][0]
        self.assertEqual(it["title"], "Kenton's room")
        o, c = mint(self.svc, self.slug, host=OTHER, code="", invite=it["token"])
        self.assertEqual((c, o["guest"]), (200, True), o)
        # rate limit per sender
        n, _w = kr.PINVITE_RATE
        codes = [people(self.svc, k_alpha, {"op": "invite", "to": "h%d-0a0a" % i})[1] for i in range(n + 1)]
        self.assertEqual(codes[-1], 429, codes)
        self.assertTrue(all(c == 200 for c in codes[: n - 2]), codes)      # (two were used above: alpha and My room -- one device)

    def test_unknown_op_and_no_token(self):
        self.assertEqual(self.svc.people_api({"op": "beat"}, None, "10.0.0.7")[1], 403)
        self.assertEqual(people(self.svc, self.own, {"op": "zap"})[1], 400)
        wide = kr._mint(self.svc.key, {"root": "", "get": "alpha", "put": ["alpha"], "iat": int(time.time()), "exp": int(time.time()) + 60})
        self.assertEqual(people(self.svc, wide, {"op": "beat"})[1], 403)   # a 0.12-shaped token names no device


class Federation(unittest.TestCase):
    """The owner on the hub, the guest on a spoke (and the other way round)."""

    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        self.base = ["http://127.0.0.1:%d" % self.hub.httpd.server_address[1]]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: self.base[0], fed_token=lambda: self.fed)
        o, c = self.hub.rooms_fed({"op": "personal", "body": {"op": "create", "name": "Kenton", "code": "abcd1234"}, "vouch": "member"},
                                  "Bearer " + self.fed)
        assert c == 200, o
        self.slug = o["slug"]

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def poll(self):
        return self.spoke.personal_mirror_apply(self.hub.bans_for_spoke("Bearer " + self.fed)[0])

    def test_guest_on_a_spoke(self):
        own = tok(self.hub, self.slug, room_code="abcd1234")
        o, c = people(self.hub, own, {"op": "share", "to": GUEST, "name": "Bob", "on": True})
        self.assertEqual(c, 200, o)
        o, c = mint(self.spoke, self.slug, host=GUEST)
        self.assertEqual((c, o.get("ownerAway")), (403, True), o)         # the hub says the owner is out
        self.assertEqual(mint(self.spoke, self.slug, host=OTHER)[1], 403)
        people(self.hub, own, {"op": "beat"})
        o, c = mint(self.spoke, self.slug, host=GUEST)
        self.assertEqual((c, o["guest"]), (200, True), o)
        g = o["tokens"]["member"]
        self.assertEqual(connect(self.spoke, g, "sp-g")[1], 200)          # the hub's "in" counts for the connect
        self.poll()
        bob_beat = people(self.spoke, g, {"op": "beat"})[0]
        self.assertEqual((bob_beat["personal"]["open"], bob_beat["personal"]["owner"]), (True, "Kenton"))
        self.assertEqual([r["slug"] for r in bob_beat["shared"]], [self.slug])
        # a guest's board change is refused on the spoke too
        self.assertEqual(self.spoke.board_post({"room": self.slug, "op": "spot", "target": A_CAM}, "Bearer " + g, "10.0.0.7")[1], 403)
        # the owner leaves: the long-poll ends the guest's session on the spoke, his beat says why
        people(self.hub, own, {"op": "leave"})
        self.assertEqual(self.poll(), 1)
        self.assertEqual(revalidate(self.spoke, "sp-g")[1], 403)
        st = people(self.spoke, g, {"op": "beat"})[0]["personal"]
        self.assertEqual((st["open"], st["why"]), (False, "left"))
        self.assertEqual(mint(self.spoke, self.slug, host=GUEST)[0].get("ownerAway"), True)
        # the hub goes dark: a guest is never let in (fail closed)
        people(self.hub, own, {"op": "beat"})
        self.poll()
        self.base[0] = "http://127.0.0.1:9"
        o, c = mint(self.spoke, self.slug, host=GUEST, peer="10.0.0.9")
        self.assertEqual(c, 503, o)
        self.assertNotIn("tokens", o)
        self.spoke._pl().mirror_at = 0
        self.spoke._pl().open_local.clear()
        self.assertFalse(self.spoke.personal_open(self.slug))
        st = people(self.spoke, g, {"op": "beat"})[0]["personal"]
        self.assertIsNone(st["open"])                                     # a late copy never sends a guest away by itself
        self.assertEqual(connect(self.spoke, g, "sp-g3")[1], 403)        # ... but its sessions fail closed

    def test_owner_on_a_spoke_keeps_it_open_and_shares_through_the_hub(self):
        own = tok(self.spoke, self.slug, room_code="abcd1234")
        self.assertEqual(claims(self.spoke, own)["personal"], 1)
        o, c = people(self.spoke, own, {"op": "beat"})
        self.assertEqual((c, o["personal"]), (200, {"owner": True, "open": True}), o)
        self.assertTrue(self.hub.personal_open(self.slug))                # the beat reached the hub
        o, c = people(self.spoke, own, {"op": "share", "to": GUEST, "name": "Bob", "on": True})
        self.assertEqual((c, [p["host"] for p in o["people"]]), (200, [GUEST]), o)
        self.assertEqual(people(self.spoke, own, {"op": "co", "to": GUEST})[0]["co"], GUEST)
        self.assertEqual(people(self.spoke, own, {"op": "list"})[0]["owner"], "Kenton")
        self.assertEqual(people(self.spoke, own, {"op": "seen"})[1], 200)
        o, c = self.spoke.invite_create_api({"room": self.slug, "ttl": 3600}, "Bearer " + own, "10.0.0.7")
        self.assertEqual(c, 200, o)                                      # made at the hub, vouched "owner"
        self.assertEqual(self.spoke.invite_manage_api("list", {"room": self.slug}, "Bearer " + own, "10.0.0.7")[1], 200)
        # Bob on the hub is let in; the co-arranger arranges through the hub's record
        g = tok(self.hub, self.slug, host=GUEST)
        self.assertEqual(self.hub.board_post({"room": self.slug, "op": "spot", "target": self.slug + "/" + OWNER + "/kenton/camera.hang"}, "Bearer " + g, "10.0.0.7")[1], 200)
        o, c = people(self.spoke, own, {"op": "leave"})
        self.assertEqual(c, 200, o)
        self.assertFalse(self.hub.personal_open(self.slug))

    def test_person_invite_reaches_a_page_on_a_spoke(self):
        k = tok(self.hub, "alpha")
        o, c = people(self.hub, k, {"op": "invite", "to": GUEST, "toName": "Bob", "by": "Kenton"})
        self.assertEqual(c, 200, o)
        bob = tok(self.spoke, "main", host=GUEST)
        self.assertEqual(people(self.spoke, bob, {"op": "beat"})[0]["inbox"], [])
        self.poll()                                                       # the bans long-poll carries it
        box = people(self.spoke, bob, {"op": "beat"})[0]["inbox"]
        self.assertEqual([(x["room"], x["by"]) for x in box], [("alpha", "Kenton")])
        self.poll()
        self.assertEqual(people(self.spoke, bob, {"op": "beat"})[0]["inbox"], [])   # once
        o, c = mint(self.spoke, "alpha", host=GUEST, code="", invite=box[0]["token"])
        self.assertEqual(c, 200, o)
        # and the other way: a sender on the spoke (the hub makes the link)
        e = tok(self.spoke, "beta", host=OTHER)
        o, c = people(self.spoke, e, {"op": "invite", "to": OWNER, "by": "Eve"})
        self.assertEqual(c, 200, o)
        self.assertEqual(people(self.hub, tok(self.hub, "main"), {"op": "beat"})[0]["inbox"][0]["room"], "beta")


class Serve(unittest.TestCase):
    def test_people_endpoint_reaches_the_minter(self):
        s = _read("kastr_serve.py")
        self.assertIn('"/api/people",                                       # 0.21.78: beats, person invites, My room shared', s)
        r = _read("kastr_relay.py")
        self.assertIn('elif path == "/api/people":            # 0.21.78: beats, person invites, My room shared', r)
        self.assertIn("bearer = \"Bearer \" + str(p.get(\"token\"))[:4096]", r)   # a closing page's beacon carries its token in the body
        self.assertNotIn("raise_cmd(\"pinvite\"", r)                           # invites never ride the saved command list (no token on disk)


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html")

    def test_rail_card_before_setup_and_the_dialog(self):
        p = self.p
        self.assertIn('<div id="sbMine" class="sbmine" hidden></div>', p)          # unhidden by personalCardPaint, set up or not
        self.assertIn("    host.hidden = false;", p)
        self.assertIn('card.querySelector(".sbcnt").textContent = !p ? "Set up" :', p)
        self.assertIn("card.classList.toggle(\"setup\", !p);", p)
        self.assertIn('if (!p) { personalDialog(); return; }', p)                  # personalEnter: the card opens the dialog first
        self.assertIn("<ul class=\"pmcaps\">", p)
        self.assertEqual(p.count("<li>Guests are only let in while you are in it. When you leave, everyone else goes to the Lobby.</li>"), 1)
        self.assertIn('<span class="lbl">Passcode</span>', p)
        # Kenton: two Close buttons in My room -- one Close; the main button goes in My room
        self.assertIn("q(\".pmok\").hidden = inMine;", p)
        self.assertNotIn('CHANNEL === p.slug ? "Close" : "Go to My room"', p)
        self.assertIn('<button type="button" class="ghost pmshare" hidden>Share My room', p)

    def test_beats_leave_and_kick(self):
        p = self.p
        self.assertIn('fetch(base + "/api/people", { method: "POST", headers: { "content-type": "application/json", authorization: "Bearer " + tok },', p)
        self.assertIn('body: JSON.stringify({ op: "beat", name: myOpName() }) });', p)
        self.assertIn('new Blob(["setInterval(() => postMessage(0), 4000);"], { type: "text/javascript" })', p)   # a worker tick
        self.assertIn('window.addEventListener("pagehide", () => personalLeaveSend(true));', p)
        self.assertIn("if (pbOwner && e?.detail?.room !== pbOwner.slug) personalLeaveSend(false);", p)
        self.assertIn("try { personalLeaveSend(false); } catch {}   // 0.21.78: the owner leaving My room", p)   # leaveMeeting
        self.assertIn('navigator.sendBeacon(base + "/api/people", new Blob([body], { type: "text/plain" }))', p)
        self.assertIn('message: why + ", so everyone in it was sent to the Lobby."', p)
        self.assertIn("await switchRoom(lastChannelList.find((r) => r.slug === LOBBY) || { slug: LOBBY }, \"\");", p)
        self.assertIn("no.hidden = !!o.noCancel;", p)                              # kastrConfirm: a note with one button
        # a guest watches + talks: the view-lock path (only the owner's / co-arranger's spotlights count, no board items)
        self.assertIn("if (isPersonalSlug(CHANNEL)) return true;   // 0.21.78: a personal room", p)
        self.assertIn("if (isPersonalSlug(CHANNEL)) return !authSecured || (authPersonal && !authGuest) || authCo; } catch {}", p)
        self.assertIn("authGuest = !!d.guest; authCo = !!d.co;   // 0.21.78", p)
        # someone else's personal room reads "<owner>'s room"; mine stays "My room"
        self.assertIn('return mine || (!o && !window.__personal) ? "My room" : o ? o + "' + BS + 'u2019s room" : "Private room";', p)

    def test_one_menu_for_the_rail_and_the_people_panel(self):
        p = self.p
        # Kenton: "Allow right clicking on a person in the people menu to have the same options as on the left" -- both open
        # participantMenu, which carries the invite items (in the tile's own menu when the person has a tile)
        start = p.index("  function participantMenu(p, anchor) {")
        body = p[start:p.index("  function paintParticipants(force) {")]
        self.assertIn("const inv = personInviteItems(p);", body)
        self.assertIn("if (pane?.__openMenu) { pane.__openMenu(anchor, inv); return true; }", body)
        self.assertIn("if (inv) { if (items.length) items.push({ sep: true }); items.push(...inv.items); }", body)
        self.assertIn("if (personInviteItems(p)) return true;   // 0.21.78", p)        # participantHasMenu: the ... and the right-click
        self.assertIn("const open = (anchor) => { if (participantMenu(p, anchor)) { row.classList.add(\"menu\"); watchMenuClose(row); } };", p)   # People rows
        self.assertIn("if (!participantMenu(p, anchor)) window.__toast?.(", p)          # the rail (sbMemberMenu)
        self.assertIn('if (ppl.rows.querySelector(".pprow.menu") && mineMenu && !mineMenu.hidden) return;   // never repaint under an open menu', p)
        self.assertIn("const openTileMenu = (anchor, extra) => {", p)
        self.assertIn("if (extra?.items?.length) items.push({ sep: true }, ...extra.items);", p)
        self.assertIn('if (extra?.pick && String(v).startsWith("pinv")) { extra.pick(v); return; }', p)
        # people in OTHER rooms on the rail get the same menu; "Invite to <this room>" only when they are not in it already
        self.assertIn('li.classList.toggle("menuable", !!sbMemberPerson(m.op, here ? CHANNEL : rec.slug, m.name));', p)
        self.assertIn("const there = !p.room || p.room === CHANNEL;   // already in the room I am in", p)
        self.assertIn('if (!there && CHANNEL !== LOBBY && !(isPersonalSlug(CHANNEL) && (authGuest || !authPersonal)))', p)
        self.assertIn('items.push({ value: "pinv-mine", icon: "share", label: "Invite to My room"', p)

    def test_the_invited_page_asks_join_or_ignore(self):
        p = self.p
        self.assertIn('message: (it.by || "Someone") + " invites you to " + t,', p)
        self.assertIn('ok: "Join", cancel: "Ignore" });', p)
        self.assertIn("inviteSet({ token: String(it.token), room, at: Date.now() });", p)   # the one-device link rides the mint: no code
        self.assertIn('body: JSON.stringify({ op: "invite", to: host, toName: who, by: myOpName() || undefined }) });', p)
        self.assertIsNone(re.search(r"/api/people" + re.escape("?"), p))                  # no token in a URL


def _read(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


BS = chr(92)


if __name__ == "__main__":
    unittest.main()
