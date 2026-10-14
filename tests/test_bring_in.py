# -*- coding: utf-8 -*-
"""0.21.49: a BRING-IN listing (Kenton: "I'm still not able to spotlight a share from another room") -- a member of room A
lists one of A's streams into its own room B, so "Spotlight for everyone" on a watched tile reaches the whole room. A
locked room's stream needs the admin code. Also: presence says which KASTR a member runs (Participants flags older ones)
and the RTMP push address can be chosen. Loopback only, no outside network."""
import hashlib, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

SALT = "00112233aabbccdd"
PATH = "alpha/box-1a2b/kenton/cam.hang"


def h(code):
    return hashlib.sha256((SALT + code).encode()).hexdigest()


class BringIn(unittest.TestCase):
    def setUp(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)

    def tearDown(self):
        self.svc.close()

    def mint(self, room, host, code, room_code=None):
        body = {"room": room, "code": code, "host": host}
        if room_code is not None:
            body["roomCode"] = room_code
        o, c = self.svc.token(body, "10.0.0.7")
        self.assertEqual(c, 200, o)
        return o["tokens"]["member"]

    def bring(self, a_tok, b_tok, path=PATH, to="beta", **kw):
        body = {"path": path, "bring": True, "to": [to], "tokens": {to: b_tok}, "label": "cam", "kind": "camera", "by": "Watcher"}
        body.update(kw)
        return self.svc.xshare_post(body, "Bearer " + a_tok, "10.0.0.8")

    def test_a_viewer_of_room_a_brings_a_stream_into_its_room(self):
        a = self.mint("alpha", "watch-9f9f", "view-1")   # a VIEW-only member of alpha, another machine than the stream's
        b = self.mint("beta", "watch-9f9f", "view-1")
        o, c = self.bring(a, b)
        self.assertEqual(c, 200, o)
        self.assertEqual(o["to"], ["beta"])
        items, c2 = self.svc.xshare_get("beta", "Bearer " + b, None, "10.0.0.8")
        self.assertEqual([i["path"] for i in items["items"]], [PATH])

    def test_without_bring_a_foreign_stream_is_still_refused(self):
        a = self.mint("alpha", "watch-9f9f", "pub-1")
        b = self.mint("beta", "watch-9f9f", "pub-1")
        o, c = self.svc.xshare_post({"path": PATH, "to": ["beta"], "tokens": {"beta": b}}, "Bearer " + a, "10.0.0.8")
        self.assertEqual(c, 403, o)

    def test_only_the_tokens_own_room(self):
        g = self.mint("gamma", "watch-9f9f", "view-1")
        b = self.mint("beta", "watch-9f9f", "view-1")
        o, c = self.bring(g, b)   # a gamma token cannot bring an alpha stream
        self.assertEqual(c, 403, o)

    def test_a_locked_rooms_stream_needs_the_admin_code(self):
        kr.register_room(self.svc.store, {"slug": "alpha", "salt": SALT, "hash": h("right"), "access": "pub-1"}, "10.0.0.1")
        a = self.mint("alpha", "watch-9f9f", "pub-1", room_code="right")
        b = self.mint("beta", "watch-9f9f", "pub-1")
        o, c = self.bring(a, b)
        self.assertEqual(c, 403, o)
        self.assertIn("admin", o["error"])
        adm = self.mint("alpha", "boss-1111", "adm-1", room_code="right")
        b2 = self.mint("beta", "boss-1111", "adm-1")
        o, c = self.bring(adm, b2)
        self.assertEqual(c, 200, o)

    def test_the_target_room_still_needs_its_member_token(self):
        a = self.mint("alpha", "watch-9f9f", "view-1")
        o, c = self.bring(a, "not-a-token")
        self.assertEqual(c, 403, o)
        self.assertIn("beta", o["refused"])

    def test_stop_withdraws_it(self):
        a = self.mint("alpha", "watch-9f9f", "view-1")
        b = self.mint("beta", "watch-9f9f", "view-1")
        self.bring(a, b)
        o, c = self.bring(a, b, stop=True)
        self.assertEqual(c, 200, o)
        items, _ = self.svc.xshare_get("beta", "Bearer " + b, None, "10.0.0.8")
        self.assertEqual(items["items"], [])


class Page(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.p = f.read()

    def test_watched_tile_offers_spotlight_for_everyone(self):
        self.assertIn('if ((!wrSrc || wrBring) && !viewLockedForMe()) items.push({ value: lit ? "unspot" : (wrSrc ? "wrall" : "all")', self.p)
        self.assertIn('const wrBring = !!wrSrc && (authRole === "admin" || !(lastChannelList || []).find((r) => r.slug === wrSrc)?.locked);', self.p)
        self.assertIn('if (v === "wrall") { wrSpotForAll(name); return; }', self.p)
        self.assertIn("const body = { path, bring: true, from: slug, to: [CHANNEL], stop: !!stop,", self.p)

    def test_listing_lives_while_spotlit(self):
        self.assertIn("if (spotOnRoom(p)) { b.idleSince = 0; xsBring(p, false, true); continue; }", self.p)
        self.assertIn("if (Date.now() - b.idleSince > 60000) { xsBrought.delete(p); xsBring(p, true, true); }", self.p)

    def test_presence_carries_the_version_and_participants_flag_old_ones(self):
        self.assertIn("kv: KASTR_VER };", self.p)
        self.assertIn('kv: String(v.kv || "").slice(0, 24),', self.p)
        self.assertIn('"Older KASTR \\u2014 needs updating"', self.p)
        self.assertLess(self.p.index("const KASTR_VER ="), self.p.index("kv: KASTR_VER };"))

    def test_rtmp_address_can_be_chosen(self):
        self.assertIn('if (rtmpHosts.length && !rtmpHosts.includes(rtmpHostV)) rtmpHostSet(rtmpHosts[0]);', self.p)
        self.assertIn('hs.className = "rtmphost";', self.p)


if __name__ == "__main__":
    unittest.main()
