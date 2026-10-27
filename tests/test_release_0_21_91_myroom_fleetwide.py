# -*- coding: utf-8 -*-
"""v0.21.91 MY ROOM ACROSS THE FLEET. Kenton: "When switching relays I have to setup 'My Room' code again. This should be stored
across the fleet relays ... It was pointed at the 192.168.x.x address and I pointed it at 127.0.0.1 instead and it made me sign in
again."

The device kept My room's record under kastr.personal.<relay address as typed>. Now every relay of a fleet reports the fleet's id
in /api/auth (the hub's messages store id; a spoke repeats what the hub's long-poll said) and the page keeps the record under
kastr.personal.f.<fleet id>. An older per-address record is taken over once -- only when it is this fleet's (saved with this fleet
id, saved for this very address, or ITS relay's /api/auth says the same fleet: no code is sent to find out) and a quiet "open" on
this fleet's hub answers the same room; this fleet's per-address copies are dropped then."""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


class Fleet(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        self.base = ["http://127.0.0.1:%d" % self.hub.httpd.server_address[1]]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: self.base[0], fed_token=lambda: self.fed)
        self.other = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4463, store())   # a second hub: another fleet

    def tearDown(self):
        for s in (self.hub, self.spoke, self.other):
            s.close()

    def auth(self, svc):
        import json
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:%d/api/auth" % svc.httpd.server_address[1], timeout=5) as r:
            return json.loads(r.read())

    def test_every_relay_of_a_fleet_says_the_same_fleet(self):
        f = self.auth(self.hub)["fleet"]
        self.assertRegex(f, r"^[0-9a-f]{16}$")
        self.assertEqual(f, self.hub._msgr().fleet)
        self.assertIsNone(self.auth(self.spoke)["fleet"])                    # a spoke that has not heard from its hub says nothing
        self.spoke.personal_mirror_apply(self.hub.bans_for_spoke("Bearer " + self.fed)[0])
        self.assertEqual(self.auth(self.spoke)["fleet"], f)                  # ... then the hub's
        self.assertNotEqual(self.auth(self.other)["fleet"], f)               # another fleet: another id
        # a hub hand-over keeps it (the new hub's empty store takes the fleet's id)
        new = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4473, store())
        try:
            new._msgr().merge(self.hub._msgr().export(0))
            self.assertEqual(self.auth(new)["fleet"], f)
        finally:
            new.close()


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            cls.p = f.read()
        with open(os.path.join(HERE, "assets", "kastr-msg.js"), encoding="utf-8") as f:
            cls.js = f.read()

    def test_the_record_is_kept_per_fleet(self):
        p = self.p
        self.assertIn('const personalStoreKey = () => { const h = relayHostKey(), f = fleetFor(h); return f ? "kastr.personal.f." + f : (h ? "kastr.personal." + h : ""); };', p)
        self.assertIn('try { personalFleetSet(String(d.fleet || "")); } catch {}   // 0.21.91: My room is kept per fleet', p)
        self.assertIn('localStorage.setItem("kastr.fleet." + h, f)', p)       # remembered per address for the moments before /api/auth
        self.assertIn("personalReady: () => personalAdoptP,", p)
        self.assertIn("try { await K.personalReady?.(); } catch {}", self.js)  # the setup card waits for it

    def test_an_older_record_is_taken_over_only_on_its_own_fleet(self):
        p = self.p
        body = p[p.index("async function personalAdopt(f, h)"):p.index("async function personalAdopt(f, h)") + 2400]
        self.assertIn("let ours = c.r.fleet ? c.r.fleet === f : c.host === h;", body)
        self.assertIn("if (!ours && !c.r.fleet) ours = (await personalFleetOfHost(c.host)) === f;", body)
        self.assertIn("if (!ours) continue;   // another fleet's record: its code never goes to this fleet", body)
        # the open (the only call that carries a code) comes AFTER the fleet check, and must answer the same room
        self.assertLess(body.index("if (!ours) continue;"), body.index('personalApi({ op: "open"'))
        self.assertIn("if (!d.ok || d.slug !== c.r.slug) continue;", body)
        self.assertIn("for (const o of cands) if (o.r.fleet === f || o.r.slug === c.r.slug) localStorage.removeItem(o.k);", body)
        # asking another relay which fleet it is in sends no code: /api/auth only
        fo = p[p.index("async function personalFleetOfHost(host)"):p.index("async function personalAdopt(f, h)")]
        self.assertIn('"/api/auth"', fo)
        self.assertNotIn("code", fo)


if __name__ == "__main__":
    unittest.main()
