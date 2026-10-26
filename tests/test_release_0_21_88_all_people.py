# -*- coding: utf-8 -*-
"""v0.21.88 ALL PEOPLE. Kenton: "I would like to add 'all people' in the people page, then a toggle to show online only."

The People panel's second tab is All people: with Online only (the default, remembered per device) it is 0.21.85's Everyone
online; switched off it adds everyone the hub has seen with a KASTR app or a web page in the last 30 days (the 0.21.68 Users
history, live check-ins, the spokes' users, the names pages say in their beats) -- ONE row per person (by name, whatever
devices), never camera boxes, relays or invite-link guests; people with a messaging key are listed too (0.22: people from the
directory who never logged in). Offline rows are greyed with "last seen"; every row has Message.
POST /api/people {op: "all"} answers it (a spoke asks the hub; the Lobby and invite-link guests get nothing)."""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

DAY = 86400


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def tok(svc, room, host, code="pub-1", invite=None):
    body = {"room": room, "code": code, "host": host}
    if invite is not None:
        body["invite"] = invite
    o, c = svc.token(body, "10.0.0.7")
    assert c == 200, (c, o)
    return o["tokens"]["member"]


def people(svc, t, body):
    return svc.people_api(body, "Bearer " + t, "10.0.0.7")


def rows_of(svc, t):
    o, c = people(svc, t, {"op": "all"})
    assert c == 200, o
    return {r["name"]: r for r in o["rows"]}


class Hub(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        now = int(time.time())
        # the 30-day history: an app, a web page of the same person, a box, a relay, someone gone 40 days, an invite guest
        self.svc._hist_note([
            {"node": "kris-desk-1a2b", "name": "Kris Price", "mode": "full", "at": now - 3 * DAY, "checkin": True},
            {"node": "web-0c0ffee0-77aa", "name": "kris  price", "mode": "web", "kind": "web", "at": now - DAY},
            {"node": "gate-box-9a8b", "name": "Gate box", "mode": "publisher", "at": now - 60},
            {"node": "relay-pc-4d4d", "name": "Relay PC", "mode": "relay", "at": now - 60},
            {"node": "old-pc-0001", "name": "Olga Old", "mode": "full", "at": now - 40 * DAY},
            {"node": "web-9e5e5e5e-1111", "name": "Gail Guest", "mode": "web", "kind": "web", "at": now - 100, "guest": True},
        ])
        self.ada = tok(self.svc, "alpha", "ada-laptop-3c4d")

    def tearDown(self):
        self.svc.close()

    def test_by_name_without_boxes_relays_guests_or_the_long_gone(self):
        r = rows_of(self.svc, self.ada)
        kris = [v for v in r.values() if v["key"] == "kris price"]   # "Kris Price" and "kris  price": one person
        self.assertEqual(len(kris), 1)                            # one person, two devices
        self.assertEqual(sorted(kris[0]["hosts"]), ["kris-desk-1a2b", "web-0c0ffee0-77aa"])
        self.assertTrue(kris[0]["web"] and kris[0]["app"])
        self.assertGreater(kris[0]["at"], int(time.time()) - 2 * DAY)   # the latest sighting
        for n in ("Gate box", "Relay PC", "Olga Old", "Gail Guest"):
            self.assertNotIn(n, r)

    def test_a_page_beating_now_is_listed_and_a_box_beat_is_not(self):
        people(self.svc, self.ada, {"op": "beat", "name": "Ada Lovelace", "mode": "full"})
        bt = tok(self.svc, "alpha", "cam-box-5b5b")
        people(self.svc, bt, {"op": "beat", "name": "Cam box", "mode": "publisher"})
        r = rows_of(self.svc, self.ada)
        self.assertIn("Ada Lovelace", r)
        self.assertNotIn("Cam box", r)

    def test_invite_link_guests_are_left_out(self):
        o, c = self.svc.invite_create_api({"room": "alpha", "ttl": 3600, "by": "Ada"}, "Bearer " + self.ada, "10.0.0.7")
        self.assertEqual(c, 200, o)
        g = tok(self.svc, "alpha", "web-6e6e6e6e-2222", code="", invite=o["token"])
        people(self.svc, g, {"op": "beat", "name": "Ivy Invited"})
        self.assertNotIn("Ivy Invited", rows_of(self.svc, self.ada))
        self.assertEqual(people(self.svc, g, {"op": "all"})[1], 403)   # and a guest's page asks nothing

    def test_a_guest_check_in_says_so(self):
        self.svc._sessions["s1"] = {"host": "web-7f7f7f7f-3333", "at": time.time(), "room": "alpha", "revoked": False}
        o, c = self.svc.client_checkin({"node": "web-7f7f7f7f-3333", "name": "Gus Guest", "mode": "web", "guest": True}, "10.0.0.8")
        self.assertEqual(c, 200)
        self.assertNotIn("Gus Guest", rows_of(self.svc, self.ada))

    def test_messaging_identities_are_people_too(self):
        o, c = kr.personal_op(self.svc.store, {"op": "create", "name": "Mo Message", "code": "mo-code-1234", "access": "pub-1"}, "10.0.0.5")
        m = self.svc._msgr()
        m.persons["mo message"] = {"name": "Mo Message", "kid": "0" * 16, "pub": "x", "devices": {}, "at": int(time.time()) - 5 * DAY}
        r = rows_of(self.svc, self.ada)
        self.assertTrue(r["Mo Message"]["msg"])
        self.assertEqual(r["Mo Message"]["hosts"], [])           # a person with no device (0.22: the directory's people)

    def test_the_lobby_asks_nothing(self):
        lob = tok(self.svc, "main", "lobby-pc-1111")
        self.assertEqual(people(self.svc, lob, {"op": "all"})[1], 403)


class Federation(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        self.base = ["http://127.0.0.1:%d" % self.hub.httpd.server_address[1]]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: self.base[0], fed_token=lambda: self.fed)

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def test_a_spoke_asks_the_hub_and_keeps_its_own_when_dark(self):
        self.hub._hist_note([{"node": "kris-desk-1a2b", "name": "Kris Price", "mode": "full", "at": int(time.time()) - 100, "checkin": True}])
        t = tok(self.spoke, "beta", "ada-laptop-3c4d")
        people(self.spoke, t, {"op": "beat", "name": "Ada Lovelace", "mode": "full"})
        o, c = people(self.spoke, t, {"op": "all"})
        self.assertEqual(c, 200)
        self.assertIn("Kris Price", [r["name"] for r in o["rows"]])
        self.assertNotIn("hubDown", o)
        self.base[0] = "http://127.0.0.1:9"
        self.spoke._pl().allcache.clear()
        o, c = people(self.spoke, t, {"op": "all"})
        self.assertTrue(o.get("hubDown"))
        self.assertIn("Ada Lovelace", [r["name"] for r in o["rows"]])   # its own pages still


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = _read("moq-watch-lite.html")

    def test_tab_toggle_and_rows(self):
        p = self.page
        self.assertIn('aria-controls="pplAll"', p)
        self.assertIn(">All people <span id=\"pplAllN\"", p)
        self.assertNotIn(">Everyone online <span", p)
        self.assertIn('<input type="checkbox" id="pplOnline" checked>', p)
        self.assertIn('const EO_ONLY_KEY = "kastr.people.onlineOnly";', p)
        self.assertIn('localStorage.getItem(EO_ONLY_KEY) !== "0"', p)          # on by default
        self.assertIn('body: JSON.stringify({ op: "all" })', p)
        self.assertIn('row.className = "pprow off"', p)                        # offline rows greyed
        self.assertIn('"Last seen " + eoAgo(r.at)', p)
        self.assertIn('mb.className = "ppmsg"', p)                             # Message on every row
        self.assertIn('value: "pinv-msg"', p)                                  # ... and in every person menu
        self.assertIn('"Messaging devices\\u2026 (admin)"', p.replace("…", "\\u2026"))


if __name__ == "__main__":
    unittest.main()
