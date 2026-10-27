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

    def lapse(self, room="beta"):
        with self.st.lock:
            self.st.rooms[room]["at"] = time.time() - kr.ROOM_TTL - 5       # nobody used it for ROOM_TTL

    def test_lapsed_room_keeps_its_shares(self):
        # follow-up (Kenton): a room that lapses ~10 min after the last person leaves is NOT deleted
        o, _ = self.share()
        gen = o["gens"]["beta"]
        self.lapse()
        self.assertEqual(self.st.room_slugs(), [])                           # the lapse sweep (any room list)
        self.assertEqual(self.listed(), [PATH])                              # the listing stays
        self.assertEqual(self.st.lapsed_gen("beta"), gen)                    # its generation is remembered
        o, c = self.share(gens={"beta": gen})                               # the sharer's heartbeat while it is lapsed
        self.assertEqual((c, o["to"], o.get("gone")), (200, ["beta"], None), o)
        self.assertEqual(o["gens"], {})                                     # no record to name (the sharer keeps its own)

    def test_lapsed_room_used_again_is_the_same_room(self):
        o, _ = self.share()
        gen = o["gens"]["beta"]
        self.lapse()
        self.assertTrue(self.st.touch_room("beta", "later"))                # a page enters the name again: a record again ...
        self.assertEqual(kr.room_gen(self.st.room("beta")), gen)            # ... of the SAME generation
        self.assertEqual(self.listed(), [PATH])
        o, c = self.share(gens={"beta": gen})
        self.assertEqual((c, o["to"], o["gens"]), (200, ["beta"], {"beta": gen}))
        self.assertIsNone(self.st.lapsed_gen("beta"))                        # used up

    def test_lapse_then_registered_and_survives_a_restart(self):
        o, _ = self.share()
        gen = o["gens"]["beta"]
        self.lapse()
        self.st.room_slugs()
        again = kr.AuthStore(self.st.state_dir)                              # relay-auth.json keeps the memory
        self.assertEqual(again.lapsed_gen("beta"), gen)
        again.put_room("beta", {"salt": "", "hash": "", "roomKey": "k", "at": time.time(), "persistent": True, "created": time.time()})
        self.assertEqual(kr.room_gen(again.room("beta")), gen)               # registered (kept) after the lapse: same room

    def test_close_after_a_lapse_is_a_delete(self):
        o, _ = self.share()
        gen = o["gens"]["beta"]
        self.lapse()
        self.st.room_slugs()
        kr.close_room(self.st, "beta", operator=True)                        # the operator deletes the lapsed name
        self.assertEqual(self.listed(), [])
        self.assertIsNone(self.st.lapsed_gen("beta"))
        self.st.closed.clear()                                               # an hour later: the tombstone is gone too
        self.st.touch_room("beta", "someone")                                # a DIFFERENT room under the name
        self.assertNotEqual(kr.room_gen(self.st.room("beta")), gen)
        self.assertEqual(self.share(gens={"beta": gen})[0].get("gone"), ["beta"])   # never inherited

    def test_lapse_memory_is_bounded(self):
        with self.st.lock:
            for i in range(kr.LAPSED_MAX + 5):
                self.st._lapse_locked("r%d" % i, {"created": 1700000000 + i})
            self.st._lapse_locked("old", {"created": 1600000000})
            self.st.lapsed["old"]["at"] = int(time.time()) - kr.LAPSED_TTL - 5
            self.st._lapse_locked("new", {"created": 1700009999})
        self.assertLessEqual(len(self.st.lapsed), kr.LAPSED_MAX)
        self.assertNotIn("old", self.st.lapsed)
        self.assertIn("new", self.st.lapsed)

    def test_live_room_with_its_generation_stays(self):
        o, _ = self.share()
        o, c = self.share(gens=o["gens"])
        self.assertEqual((c, o["to"], o.get("gone")), (200, ["beta"], None))

    def test_no_generation_no_record_unchanged(self):
        o, c = self.share(to=["gamma"], tokens={"gamma": mint(self.svc, "gamma")})   # a name with no record (as before 0.21.91)
        self.assertEqual((c, o["to"], o["gens"]), (200, ["gamma"], {}))

    def test_renamed_room_tells_the_sharer_to_follow(self):
        # follow-up (Kenton): when a room is RENAMED the camera shares FOLLOW the new name
        o, _ = self.share()
        gen = o["gens"]["beta"]
        o, c = kr.room_settings(self.st, {"slug": "beta", "op": "rename", "to": "beta-2"}, admin=True, xs=self.svc._xs("local"))
        self.assertEqual(c, 200, o)
        self.assertEqual(self.listed("beta-2"), [PATH])                     # the listing moved with the room
        o, c = self.share(gens={"beta": gen})                               # the sharer still names the old room
        self.assertEqual((c, o.get("renamed"), o.get("gone")), (403, {"beta": "beta-2"}, None), o)
        self.assertEqual(self.listed("beta"), [])                            # never re-listed under the old name
        o, c = self.share(to=["beta-2"], tokens={"beta-2": mint(self.svc, "beta-2")}, gens={"beta-2": gen})   # it follows
        self.assertEqual((c, o["to"], o["gens"]), (200, ["beta-2"], {"beta-2": gen}))   # the same room (generation kept)

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

    def test_spoke_passes_a_rename_through(self):
        o, _ = self.post()
        o, c = self.hub.rooms_fed({"op": "settings", "vouch": "admin", "body": {"slug": "beta", "op": "rename", "to": "gate"}},
                                  "Bearer " + self.fed)                     # renamed at the hub (a spoke's admin)
        self.assertEqual(c, 200, o)
        o, c = self.post()
        self.assertEqual((c, o.get("renamed")), (403, {"beta": "gate"}), o)

    def test_hub_lapse_is_not_a_delete(self):
        o, _ = self.post()
        gen = o["gens"]["beta"]
        with self.hub.store.lock:
            self.hub.store.rooms["beta"]["at"] = time.time() - kr.ROOM_TTL - 5
        self.hub.store.room_slugs()
        self.assertEqual(len(self.hub._xs("local").into("beta")), 1)
        o, c = self.post(gens={"beta": gen})
        self.assertEqual((c, o["to"], o.get("gone")), (200, ["beta"], None), o)

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

    def test_open_relay_rename_followed(self):
        o, c = kr.xshare_open("POST", {"from": "alpha", "path": PATH, "to": ["beta"]}, store=self.st)
        o, c = kr.room_settings(self.st, {"slug": "beta", "op": "rename", "to": "gate"}, admin=True, xs=kr.XSHARE_OPEN)
        self.assertEqual(c, 200, o)
        self.assertEqual([i["path"] for i in kr.xshare_open("GET", room="gate")[0]["items"]], [PATH])
        o, c = kr.xshare_open("POST", {"from": "alpha", "path": PATH, "to": ["beta"]}, store=self.st)
        self.assertEqual((c, o.get("renamed")), (403, {"beta": "gate"}))

    def test_open_relay_settings_route_renames_the_open_registry(self):
        self.assertIn('else kastr_relay.XSHARE_OPEN   # 0.21.91: an open relay', read("kastr_serve.py"))


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

    def test_renamed_room_followed(self):
        b = self.bridge()
        feed = self.camera(b)
        feed.xs = ["ra", "rb"]
        feed.xs_codes = {"rb": "secret"}
        b.xs_tick(post=self.gone_post(), mint=self.relay.mint)

        def post(url, body, bearer):
            if not body.get("stop") and "rb" in body["to"]:
                self.relay.posts.append((url, json.loads(json.dumps(body)), bearer))
                acc = [r for r in body["to"] if r != "rb"]
                return {"ok": True, "to": acc, "refused": {"rb": "renamed to gate"}, "renamed": {"rb": "gate"},
                        "gens": {r: "g-" + r for r in acc}}, 200
            return self.gone_post()(url, body, bearer)
        b.xs_tick(post=post, mint=self.relay.mint)
        self.assertEqual(feed.xs, ["ra", "gate"])                             # same place in the list
        self.assertEqual((feed.xs_codes, feed.xs_gen), ({"gate": "secret"}, {"ra": "g-ra", "gate": "g-rb"}))   # code + generation follow
        self.assertEqual([(d["room"], d["to"], d["why"]) for d in feed.xs_dropped], [("rb", "gate", "renamed")])
        self.assertEqual(self.feeds_doc()["feeds"][0]["xs"], ["ra", "gate"])
        self.assertTrue(any("follows renamed room(s) rb -> gate" in ln for ln in self.lines))
        b.xs_tick(post=self.gone_post(), mint=self.relay.mint)                 # the next round lists it under the new name
        last = self.relay.lists()[-1][1]
        self.assertEqual((last["to"], last["gens"]), (["ra", "gate"], {"ra": "g-ra", "gate": "g-rb"}))

    def test_rename_into_a_room_it_already_shows_in(self):
        b = self.bridge()
        feed = self.camera(b)
        feed.xs = ["ra", "rb"]
        moved = b._xs_follow(feed, {"rb": "ra"}, PATH1)
        self.assertEqual((moved, feed.xs), ({"rb": "ra"}, ["ra"]))

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
        self.assertIn("if (gone.includes(slug) || ren.some(([a]) => a === slug)) continue;", s)   # one notice, not two

    def test_page_share_follows_a_rename(self):
        s = self.s
        self.assertIn("if (ren.length) xsFollow(path, ren);", s)
        self.assertIn("async function xsFollow(path, ren) {", s)
        self.assertIn("try { x.tokens[b] = await xsTokenFor(b, xsCodes[a] || \"\"); x.rooms.add(b);", s)
        self.assertIn("xsGensSet(path, (g) => { for (const [a, b] of moved) { if (g[a] && !g[b]) g[b] = g[a]; delete g[a]; } });", s)
        self.assertIn("if (Array.isArray(keep)) xsSave(path, [...new Set(keep.map((sl) => (moved.find(([a]) => a === sl) || [])[1] || sl))]", s)
        self.assertIn('if (gone.includes(slug) || ren.some(([a]) => a === slug)) continue;', s)
        self.assertIn('to: x.why === "renamed" ? String(x.to || "") : ""', s)   # the box page says so too

    def test_box_page_says_it_once(self):
        s = self.s
        self.assertIn("xsDroppedNote(d.feeds ?? []);   // 0.21.91", s)
        self.assertIn('const k = f.id + "|" + x.room + "|" + x.at;', s)
        self.assertIn("if (now - Number(x.at || 0) < 600) news.push(", s)

    def test_open_relay_post_passes_the_store(self):
        self.assertIn('kastr_relay.xshare_open("POST", _ob, store=getattr(relay_srv, "store", None), judge=_judge)', read("kastr_serve.py"))


if __name__ == "__main__":
    unittest.main()
