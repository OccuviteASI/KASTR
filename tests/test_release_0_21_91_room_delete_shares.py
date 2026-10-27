# -*- coding: utf-8 -*-
"""0.21.91 (Kenton: "When a room is deleted, it doesn't delete the sharing of the cameras going to that room."). Root cause:
nothing tied a cross-room listing to the room it pointed at. A sharer (a box's camera -- rtsp-feeds.json `xs` -- or a page's
share -- kastr.xshare.paths) re-lists its stream every minute with a member token it MINTS for each target room, and a token
mints for any free name: a closed or expired room kept the listing (and a later room of the same name inherited it, silently).

Now (kastr_relay): deleting a room -- closed by its creator, an admin, the hub, or expired ROOM_TTL after its last use --
drops every listing INTO it at once (AuthStore.on_room_gone -> XShareRegistry.drop_into); a listing into a deleted room is
refused as GONE (`gone: [room]`) -- a tombstone, or with the room GENERATION the sharer was accepted under (`gens`: the
record's `created`) no record / a newer record; the box (kastr_rtsp) and the page drop that room for good.

Run: python -m unittest discover -s tests. No outside network, no processes (loopback services on ephemeral ports).
"""
import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_rtsp  # noqa: E402

from test_release_0_21_75_boxrooms import Sandbox, PATH1, HOME  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1"}
HOST = "box-1a2b"
PATH = "alpha/box-1a2b/kenton/cam.hang"


def store():
    st = kr.AuthStore(tempfile.mkdtemp())
    st.set_codes(**CODES)
    return st


def mint(svc, room, host=HOST, code="pub-1", peer="10.0.0.7"):
    o, c = svc.token({"room": room, "code": code, "host": host}, peer)
    assert c == 200, o
    return o["tokens"]["member"]


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class Server(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        self.st = self.svc.store
        self.st.touch_room("beta", "kenton")                     # room B exists (a page in it touched it)
        self.a, self.b = mint(self.svc, "alpha"), mint(self.svc, "beta")

    def tearDown(self):
        self.svc.close()

    def share(self, **kw):
        body = {"path": PATH, "to": ["beta"], "tokens": {"beta": self.b}, "label": "Gate", "kind": "rtsp", "by": "Kenton"}
        body.update(kw)
        return self.svc.xshare_post(body, "Bearer " + self.a, "10.0.0.7")

    def listed(self, room="beta"):
        return [i["path"] for i in self.svc.xshare_get(room, None, None, "127.0.0.1")[0]["items"]]

    def test_accept_names_the_room_generation(self):
        o, c = self.share()
        self.assertEqual((c, o["to"]), (200, ["beta"]), o)
        self.assertEqual(o["gens"], {"beta": kr.room_gen(self.st.room("beta"))})
        self.assertNotIn("gone", o)
        self.assertEqual(self.listed(), [PATH])

    def test_close_drops_listings_into_it_and_refuses_as_gone(self):
        self.share()
        self.svc._xs("local").apply("alpha/box-1a2b/kenton/pinned.hang", "alpha", ["beta"], now=time.time(), pinned=True)   # a board pin too
        o, c = kr.close_room(self.st, "beta", operator=True)
        self.assertEqual(c, 200, o)
        self.assertEqual(self.listed(), [])                                  # gone at once, pinned or not
        o, c = self.share()                                                  # the sharer's next heartbeat (a token still mints)
        self.assertEqual(c, 403, o)
        self.assertEqual(o["gone"], ["beta"])
        self.assertEqual(o["refused"], {"beta": kr.XSHARE_GONE_TEXT})
        self.assertEqual(self.listed(), [])

    def test_a_new_room_of_the_same_name_is_not_the_old_one(self):
        o, _ = self.share()
        gen = o["gens"]["beta"]
        kr.close_room(self.st, "beta", operator=True)
        time.sleep(0.01)
        self.st.touch_room("beta", "someone")                                # made again (the tombstone goes)
        self.assertFalse(self.st.is_closed("beta"))
        o, c = self.share(gens={"beta": gen})                                # the old generation -> gone, not re-attached
        self.assertEqual((c, o.get("gone")), (403, ["beta"]), o)
        self.assertEqual(self.listed(), [])
        o, c = self.share()                                                  # someone shares into the NEW room on purpose: fine
        self.assertEqual((c, o["to"]), (200, ["beta"]))
        self.assertNotEqual(o["gens"]["beta"], gen)

    def test_expired_room_drops_listings_and_is_gone(self):
        o, _ = self.share()
        gen = o["gens"]["beta"]
        with self.st.lock:
            self.st.rooms["beta"]["at"] = time.time() - kr.ROOM_TTL - 5      # nobody used it for ROOM_TTL
        self.assertEqual(self.st.room_slugs(), [])                           # the expiry sweep (any room list)
        self.assertEqual(self.listed(), [])
        o, c = self.share(gens={"beta": gen})
        self.assertEqual((c, o.get("gone")), (403, ["beta"]), o)

    def test_expired_on_touch_is_a_new_room(self):
        o, _ = self.share()
        gen = o["gens"]["beta"]
        with self.st.lock:
            self.st.rooms["beta"]["at"] = time.time() - kr.ROOM_TTL - 5
        self.assertTrue(self.st.touch_room("beta", "later"))                # a page enters the name again: a new record
        self.assertEqual(self.listed(), [])
        self.assertEqual(self.share(gens={"beta": gen})[0].get("gone"), ["beta"])

    def test_live_room_with_its_generation_stays(self):
        o, _ = self.share()
        o, c = self.share(gens=o["gens"])
        self.assertEqual((c, o["to"], o.get("gone")), (200, ["beta"], None))

    def test_no_generation_no_record_unchanged(self):
        o, c = self.share(to=["gamma"], tokens={"gamma": mint(self.svc, "gamma")})   # a name with no record (as before 0.21.91)
        self.assertEqual((c, o["to"], o["gens"]), (200, ["gamma"], {}))

    def test_renamed_room_is_not_gone(self):
        o, _ = self.share()
        self.st.rename_room("beta", "beta-2")
        o, c = self.share(gens=o["gens"])
        self.assertNotIn("gone", o)

    def test_hook_registered_once(self):
        n = sum(1 for f in self.st.on_room_gone if getattr(f, "__self__", None) is self.svc)
        self.assertEqual(n, 1)


class Federation(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: base, fed_token=lambda: self.fed)
        self.hub.store.touch_room("beta", "kenton")                           # the hub owns the rooms
        self.a, self.b = mint(self.spoke, "alpha"), mint(self.spoke, "beta")

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def post(self, **kw):
        body = {"path": PATH, "to": ["beta"], "tokens": {"beta": self.b}, "label": "Yard"}
        body.update(kw)
        return self.spoke.xshare_post(body, "Bearer " + self.a, "10.0.0.7")

    def test_spoke_passes_the_hub_verdict_through(self):
        o, c = self.post()
        self.assertEqual((c, o["to"]), (200, ["beta"]), o)
        gen = o["gens"]["beta"]
        self.assertEqual(gen, kr.room_gen(self.hub.store.room("beta")))
        kr.close_room(self.hub.store, "beta", operator=True)                 # closed at the hub (any spoke's page, an admin)
        self.assertEqual(self.hub._xs("local").into("beta"), [])
        p, _ = self.hub.bans_for_spoke("Bearer " + self.fed)                 # the spokes' copy follows on the long-poll
        self.spoke.xshare_mirror_apply(p)
        self.assertEqual(self.spoke.xshare_get("beta", None, None, "127.0.0.1")[0]["items"], [])
        o, c = self.post(gens={"beta": gen})
        self.assertEqual((c, o.get("gone")), (403, ["beta"]), o)

    def test_spoke_with_a_dark_hub_judges_nothing(self):
        hub = [None]
        dead = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4463, store(), hub=lambda: hub[0], fed_token=lambda: self.fed)
        try:
            a, b = mint(dead, "alpha"), mint(dead, "beta")
            hub[0] = "http://127.0.0.1:9"
            o, c = dead.xshare_post({"path": PATH, "to": ["beta"], "tokens": {"beta": b}, "gens": {"beta": "123"}}, "Bearer " + a, "10.0.0.7")
            self.assertEqual((c, o["to"], o.get("hubDown"), o.get("gone")), (200, ["beta"], True, None), o)   # no record here: not proof
        finally:
            dead.close()


class OpenRelay(unittest.TestCase):
    def setUp(self):
        kr.XSHARE_OPEN.items.clear()
        self.st = store()
        self.st.touch_room("beta", "k")

    def test_open_relay_gone_and_drop(self):
        o, c = kr.xshare_open("POST", {"from": "alpha", "path": PATH, "to": ["beta"]}, store=self.st)
        self.assertEqual((c, o["to"]), (200, ["beta"]))
        gen = o["gens"]["beta"]
        kr.close_room(self.st, "beta", operator=True)
        self.assertEqual(kr.xshare_open("GET", room="beta")[0]["items"], [])   # the store's hook empties the open registry
        o, c = kr.xshare_open("POST", {"from": "alpha", "path": PATH, "to": ["beta"], "gens": {"beta": gen}}, store=self.st)
        self.assertEqual((c, o.get("gone")), (403, ["beta"]))
        o, c = kr.xshare_open("POST", {"from": "alpha", "path": PATH, "to": ["beta"]}, store=self.st, judge=False)   # a spoke's open relay
        self.assertEqual(c, 200)


class Box(Sandbox):
    """The box's camera rooms (rtsp-feeds.json): a deleted room leaves the camera for good."""

    def gone_post(self, gone=(), gens=None):
        real = self.relay.post

        def post(url, body, bearer):
            if body.get("stop"):
                return real(url, body, bearer)
            self.relay.posts.append((url, json.loads(json.dumps(body)), bearer))
            acc = [r for r in body["to"] if r not in gone]
            out = {"ok": bool(acc), "to": acc, "refused": {r: kr.XSHARE_GONE_TEXT for r in body["to"] if r in gone},
                   "expires": int(time.time() + 180), "gens": {r: (gens or {}).get(r, "g-" + r) for r in acc}}
            if [r for r in body["to"] if r in gone]:
                out["gone"] = [r for r in body["to"] if r in gone]
            return out, (200 if acc else 403)
        return post

    def test_learns_generations_and_sends_them_back(self):
        b = self.bridge()
        feed = self.camera(b)
        feed.xs = ["ra", "rb"]
        b.xs_tick(post=self.gone_post(), mint=self.relay.mint)
        self.assertEqual(feed.xs_gen, {"ra": "g-ra", "rb": "g-rb"})
        self.assertEqual(self.feeds_doc()["feeds"][0]["xsGen"], {"ra": "g-ra", "rb": "g-rb"})   # persisted
        b.xs_tick(post=self.gone_post(), mint=self.relay.mint)
        self.assertEqual(self.relay.posts[-1][1]["gens"], {"ra": "g-ra", "rb": "g-rb"})

    def test_gone_room_dropped_for_good(self):
        b = self.bridge()
        feed = self.camera(b)
        feed.xs = ["ra", "rb"]
        feed.xs_codes = {"rb": "secret"}
        b.xs_tick(post=self.gone_post(), mint=self.relay.mint)
        b.xs_tick(post=self.gone_post(gone=("rb",)), mint=self.relay.mint)
        self.assertEqual(feed.xs, ["ra"])
        self.assertEqual((feed.xs_codes, feed.xs_gen), ({}, {"ra": "g-ra"}))
        self.assertNotIn("rb", feed.xs_state)
        self.assertEqual([(d["room"], d["why"]) for d in feed.xs_dropped], [("rb", "deleted")])
        rec = self.feeds_doc()["feeds"][0]
        self.assertEqual((rec["xs"], rec.get("xsCodes")), (["ra"], None))   # rtsp-feeds.json forgets it (and its code)
        self.assertEqual(b.list()[0]["xsDropped"][0]["room"], "rb")           # the page says so once
        self.assertTrue(any("no longer shown in rb -- the room was deleted" in ln for ln in self.lines))
        n = len(self.relay.lists())
        b.xs_tick(post=self.gone_post(), mint=self.relay.mint)                # not posted to rb again, even when "rb" exists anew
        self.assertEqual(self.relay.lists()[n][1]["to"], ["ra"])

    def test_all_rooms_gone_stops_listing(self):
        b = self.bridge()
        feed = self.camera(b)
        feed.xs = ["rb"]
        b.xs_tick(post=self.gone_post(), mint=self.relay.mint)
        b.xs_tick(post=self.gone_post(gone=("rb",)), mint=self.relay.mint)
        self.assertEqual((feed.xs, b._xs_listed), ([], {}))
        self.assertFalse(b._xs_wanted())                                     # the loop ends

    def test_restore_keeps_generations(self):
        doc = {"room": HOME, "access": "ACC", "roomCode": "", "relay": "http://127.0.0.1:4443",
               "feeds": [{"url": "test://pattern", "broadcast": PATH1, "keep": True, "label": "Gate Cam", "audio": False,
                          "xs": ["ra"], "xsGen": {"ra": "1700000000000", "zz": "1"}}]}
        with open(os.path.join(self.tmp.name, "rtsp-feeds.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f)
        from test_release_0_21_75_boxrooms import jwt
        b = self.bridge(session=False)
        b.restore(mint=lambda: "http://127.0.0.1:4443/?jwt=" + jwt(HOME))
        feed = list(b._feeds.values())[0]
        self.assertEqual(feed.xs_gen, {"ra": "1700000000000"})

    def test_set_xs_keeps_generations_of_kept_rooms_only(self):
        b = self.bridge()
        feed = self.camera(b)
        feed.xs, feed.xs_gen = ["ra", "rb"], {"ra": "1", "rb": "2"}
        b._xs_post = self.gone_post(gens={"ra": "1", "rc": "3"})
        b.set_xs(feed.id, ["ra", "rc"])
        self.assertEqual(feed.xs_gen, {"ra": "1", "rc": "3"})


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = read("moq-watch-lite.html")

    def test_page_share_sends_generations_and_drops_gone_rooms(self):
        s = self.s
        self.assertIn('if (!stop) { const g = xsGensOf(path), gens = {}; for (const sl of to) if (g[sl]) gens[sl] = g[sl]; if (Object.keys(gens).length) body.gens = gens; }', s)
        self.assertIn("const gone = !stop && x && Array.isArray(d.gone) ? d.gone.map(String).filter((sl) => x.rooms.has(sl)) : [];", s)
        self.assertIn("if (Array.isArray(keep)) xsSave(path, keep.filter((sl) => !gone.includes(sl)));", s)   # a restart never brings it back
        self.assertIn('const XS_GENS_KEY = () => "kastr.xshare.gens." + sbRelayHost();', s)
        self.assertIn("if (gone.includes(slug)) continue;", s)            # one notice, not two

    def test_box_page_says_it_once(self):
        s = self.s
        self.assertIn("xsDroppedNote(d.feeds ?? []);   // 0.21.91", s)
        self.assertIn('const k = f.id + "|" + x.room + "|" + x.at;', s)
        self.assertIn("if (now - Number(x.at || 0) < 600) news.push(", s)

    def test_open_relay_post_passes_the_store(self):
        self.assertIn('kastr_relay.xshare_open("POST", _ob, store=getattr(relay_srv, "store", None), judge=_judge)', read("kastr_serve.py"))


if __name__ == "__main__":
    unittest.main()
