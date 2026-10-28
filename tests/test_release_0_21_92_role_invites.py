# -*- coding: utf-8 -*-
"""v0.21.92 ADD ANYONE AS PRESENTER / BACKSTAGE. Kenton: "I want to be able to add any person as a presenter or backstage even
if they aren't in the room".

The presenter view's picker lists the room, then everyone online on the fleet, then any typed name. A person not in the room is
a WAITING role on the owner page (pres.pend, name key + device when known); someone online elsewhere gets a presenter /
backstage invitation (a person invite that names the role: Join brings them in -- locked room or My room -- with the role),
Ignore / offline leaves the role waiting for any route in. The hub answers how role invites stand (istate), takes the invited
page's Join / Ignore (ianswer) and lets a member of the room withdraw one (irevoke: the link stops working, its prompt goes
from every inbox). Guests (invite-link) may be given a role but add people from the room only. Loopback sockets only."""
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

OWNER, BOB, EVE = "kenton-ab12", "bob-cd34", "eve-ef56"


def _read(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


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


def people(svc, t, body, peer="10.0.0.7"):
    return svc.people_api(body, "Bearer " + t, peer)


def lock(svc, room="alpha", code="alpha-code"):
    salt = "00112233"
    svc.store.put_room(room, {"salt": salt, "hash": hashlib.sha256((salt + code).encode()).hexdigest(), "roomKey": "k",
                              "at": time.time(), "persistent": True, "creator": "Kenton", "created": time.time()})


class Store(unittest.TestCase):
    def test_invite_state_and_role(self):
        st = store()
        row, t, c = st.invite_create("alpha", 3600, "Kenton", bound=BOB, bound_name="Bob", role="p")
        self.assertEqual(c, 200)
        self.assertEqual(st.invite_state(row["id"]), {"room": "alpha", "role": "p", "for": BOB, "state": "pending"})
        self.assertEqual(st.invite_state(row["id"], now=row["exp"] + 1)["state"], "expired")
        st.invite_revoke("alpha", row["id"])
        self.assertEqual(st.invite_state(row["id"])["state"], "revoked")
        self.assertIsNone(st.invite_state("deadbeef"))
        # a role only on a person invite; a link for anyone never carries one
        row2, _t, _c = st.invite_create("alpha", 3600, "Kenton", role="b")
        self.assertEqual(st.invite_state(row2["id"])["role"], "")
        self.assertNotIn(t, repr(st.invite_state(row["id"])))   # the token never comes back


class Hub(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        lock(self.svc)
        self.k = tok(self.svc, "alpha", room_code="alpha-code")

    def tearDown(self):
        self.svc.close()

    def beat(self, t):
        o, c = people(self.svc, t, {"op": "beat"})
        assert c == 200, o
        return o["inbox"]

    def test_presenter_invite_opens_a_locked_room(self):
        bob = tok(self.svc, "beta", host=BOB)
        o, c = people(self.svc, self.k, {"op": "invite", "to": BOB, "toName": "Bob", "by": "Kenton", "role": "p", "deck": "Q3 review"})
        self.assertEqual((c, o["role"]), (200, "p"), o)
        iid = o["id"]
        it = self.beat(bob)[0]
        self.assertEqual((it["role"], it["deck"], it["room"], it["by"]), ("p", "Q3 review", "alpha", "Kenton"))
        o, c = people(self.svc, self.k, {"op": "istate", "ids": [iid], "names": ["bob"]})
        self.assertEqual((c, o["states"]), (200, {iid: "pending"}), o)
        # Bob says Join (only the invited device may answer); then the link opens the locked room with no room code
        self.assertEqual(people(self.svc, self.k, {"op": "ianswer", "id": iid, "a": "join"})[1], 404)
        o, c = people(self.svc, bob, {"op": "ianswer", "id": iid, "a": "join"})
        self.assertEqual((c, o["state"]), (200, "pending"), o)
        o, c = mint(self.svc, "alpha", host=BOB, code="", invite=it["token"])
        self.assertEqual(c, 200, o)
        self.assertEqual(people(self.svc, self.k, {"op": "istate", "ids": [iid]})[0]["states"], {iid: "used"})

    def test_ignore_shows_and_revoke_withdraws(self):
        bob = tok(self.svc, "beta", host=BOB)
        iid = people(self.svc, self.k, {"op": "invite", "to": BOB, "toName": "Bob", "by": "Kenton", "role": "b"})[0]["id"]
        it = self.beat(bob)[0]
        people(self.svc, bob, {"op": "ianswer", "id": iid, "a": "ignore"})
        self.assertEqual(people(self.svc, self.k, {"op": "istate", "ids": [iid]})[0]["states"], {iid: "ignored"})
        # a guest of the room cannot withdraw; a member can -- the link stops working
        o, c = people(self.svc, self.k, {"op": "irevoke", "id": iid})
        self.assertEqual((c, o["revoked"]), (200, 1), o)
        self.assertEqual(people(self.svc, self.k, {"op": "istate", "ids": [iid]})[0]["states"], {iid: "revoked"})
        self.assertEqual(mint(self.svc, "alpha", host=BOB, code="", invite=it["token"])[1], 403)
        self.assertEqual(people(self.svc, bob, {"op": "ianswer", "id": iid, "a": "join"})[0]["state"], "revoked")
        # another room's member sees "gone" and cannot withdraw it
        b2 = tok(self.svc, "beta")
        self.assertEqual(people(self.svc, b2, {"op": "istate", "ids": [iid]})[0]["states"], {iid: "gone"})
        self.assertEqual(people(self.svc, b2, {"op": "irevoke", "id": iid})[1], 404)

    def test_withdrawn_before_seen_leaves_no_prompt(self):
        bob = tok(self.svc, "beta", host=BOB)
        iid = people(self.svc, self.k, {"op": "invite", "to": BOB, "toName": "Bob", "role": "p"})[0]["id"]
        people(self.svc, self.k, {"op": "irevoke", "id": iid})
        self.assertEqual(self.beat(bob), [])

    def test_plain_invites_are_not_role_invites(self):
        iid = people(self.svc, self.k, {"op": "invite", "to": BOB, "toName": "Bob"})[0]["id"]
        self.assertEqual(people(self.svc, self.k, {"op": "istate", "ids": [iid]})[0]["states"], {iid: "gone"})
        self.assertEqual(people(self.svc, self.k, {"op": "irevoke", "id": iid})[1], 404)   # Room settings revokes those
        self.assertEqual(people(self.svc, self.k, {"op": "irevoke", "id": "nope"})[1], 400)

    def test_guests_and_the_lobby(self):
        o, c = kr.personal_op(self.svc.store, {"op": "create", "name": "Kenton", "code": "abcd1234", "access": "pub-1"}, "10.0.0.5")
        slug = o["slug"]
        own = tok(self.svc, slug, room_code="abcd1234")
        people(self.svc, own, {"op": "beat"})
        iid = people(self.svc, own, {"op": "invite", "to": BOB, "toName": "Bob", "role": "p"})[0]["id"]
        it = self.beat(tok(self.svc, "beta", host=BOB))[0]
        g = mint(self.svc, slug, host=BOB, code="", invite=it["token"])[0]["tokens"]["member"]
        self.assertEqual(people(self.svc, g, {"op": "invite", "to": EVE, "role": "p"})[1], 403)   # a guest adds from the room only
        self.assertEqual(people(self.svc, g, {"op": "irevoke", "id": iid})[1], 403)
        self.assertEqual(people(self.svc, g, {"op": "istate", "ids": [iid]})[1], 200)
        lobby = tok(self.svc, "main", host=EVE)
        self.assertEqual(people(self.svc, lobby, {"op": "istate", "ids": []})[1], 403)

    def test_renames_reach_the_presenter(self):
        if not hasattr(self.svc.store, "personal_alias"):
            self.skipTest("no aliases")
        src = _read("kastr_relay.py")
        self.assertIn("a = self.store.personal_alias(k, now) if k else None", src)
        self.assertIn('alias[k] = {"to": str(a["to"]), "name": clean_label(a.get("name"), 48)}', src)


class Federation(unittest.TestCase):
    """The presenter on a spoke, the invited person on the hub: the spoke vouches "member" and the hub keeps the invites."""

    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        self.base = ["http://127.0.0.1:%d" % self.hub.httpd.server_address[1]]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: self.base[0], fed_token=lambda: self.fed)

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def test_from_a_spoke(self):
        k = tok(self.spoke, "alpha")
        o, c = people(self.spoke, k, {"op": "invite", "to": BOB, "toName": "Bob", "by": "Kenton", "role": "p", "deck": "Deck"})
        self.assertEqual((c, o.get("role")), (200, "p"), o)
        iid = o["id"]
        bob = tok(self.hub, "beta", host=BOB)
        it = people(self.hub, bob, {"op": "beat"})[0]["inbox"][0]
        self.assertEqual((it["role"], it["room"]), ("p", "alpha"))
        o, c = people(self.spoke, k, {"op": "istate", "ids": [iid], "names": ["bob"]})
        self.assertEqual((c, o["states"]), (200, {iid: "pending"}), o)
        o, c = people(self.spoke, k, {"op": "irevoke", "id": iid})
        self.assertEqual((c, o["revoked"]), (200, 1), o)
        self.assertEqual(self.hub.store.invite_state(iid)["state"], "revoked")
        # the hub refuses a spoke that does not vouch, and a guest's role invite
        self.assertEqual(self.hub.rooms_fed({"op": "pistate", "room": "alpha", "host": OWNER, "ids": [iid]}, "Bearer " + self.fed)[1], 403)
        o, c = self.hub.rooms_fed({"op": "pinvite", "vouch": "member", "room": "alpha", "host": OWNER, "to": BOB, "role": "p", "guest": True},
                                  "Bearer " + self.fed)
        self.assertEqual(c, 403, o)


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html")
        cls.js = _read(os.path.join("assets", "kastr-pres.js"))

    def test_invited_page(self):
        self.assertIn('title: role === "p" ? "Presenter invitation" : "Backstage invitation"', self.p)
        self.assertIn('" wants you as " + (role === "p" ? "presenter" : "backstage") + " in " + t', self.p)
        self.assertIn('const d = await roleInvCall("ianswer", { id: String(it.id), a: go ? "join" : "ignore" });', self.p)
        self.assertIn('rinv: (op, body) => (/^i(state|revoke|answer)$/.test(String(op))', self.p)
        self.assertIn("fetch: (force) => eoFetch(force === true)", self.p)

    def test_waiting_roles(self):
        js = self.js
        self.assertIn("const nk = (s) => nameDisp(s).toLowerCase();", js)
        self.assertIn('try { a = window.__msg?.renamed?.(cur) || null; } catch {}', js)   # 0.21.91 renames are followed
        self.assertIn("const people = (c.people || []).filter((x) => !BOX_MODE.test(x.mode || \"\"));", js)
        self.assertIn("if (who && who !== me && (r === \"b\" || canCo(who))) {", js)   # in the room now: the role now
        self.assertIn('if (e.inv) rinv("irevoke", { id: e.inv })', js)                 # withdraw = the invite stops working
        self.assertIn("if (co && co.g) { T(\"drop\"", js)                              # never from a guest
        self.assertIn("if (amGuest()) o.g = 1;", js)
        self.assertIn("pendAdopt(m, rec);   // 0.21.92", js)                            # hand-over / takeover keeps them
        self.assertIn("|| (d.pp || []).includes(who);", js)                             # audience mute: a waiting presenter talks

    def test_picker(self):
        js = self.js
        for s in ('sec("In this room")', 'sec("Online elsewhere")', 'sec("Anyone")', '"Search people — or type any name"'):
            self.assertIn(s, js)
        a, b, c = js.index('sec("In this room")'), js.index('sec("Online elsewhere")'), js.index('sec("Anyone")')
        self.assertLess(a, b)
        self.assertLess(b, c)

    def test_template_api(self):
        js = self.js
        self.assertIn("pend: () => ((view.people() || {}).pend || []), unpend: (k) => view.unpend(k),", js)

    def test_line_endings(self):
        for name, crlf in (("moq-watch-lite.html", True), ("kastr_serve.py", True), ("kastr_relay.py", False),
                           (os.path.join("assets", "kastr-pres.js"), False), (os.path.join("assets", "kastr-msg.js"), False),
                           (os.path.join("assets", "prefs.js"), False)):
            with open(os.path.join(HERE, name), "rb") as f:
                raw = f.read()
            if crlf:
                self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)
            else:
                self.assertNotIn(b"\r\n", raw, name)


if __name__ == "__main__":
    unittest.main()
