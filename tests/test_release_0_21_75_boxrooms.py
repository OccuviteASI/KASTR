# -*- coding: utf-8 -*-
"""v0.21.75 (Kenton: "boxes that share without being in a room"). A Publisher box may join NO room: it sits in its hidden
home room box-<host slug> and each camera row picks the rooms it shows in ("Show in rooms..."). The BOX SERVER keeps those
listings (kastr_rtsp.Bridge: rtsp-feeds.json `xs` / `xsCodes`, a 60 s loop POSTing /api/xshare at its relay's minter), so
they hold with no window open and come back after a restart; viewers' pages leave every box-* room out of their lists.

Run: python -m unittest discover -s tests
No network, no processes: the minter and the xshare POST are injected, Popen refuses, the sweeps are inert.
"""
import base64
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_rtsp  # noqa: E402
import kastr_relay  # noqa: E402

RELAY = "http://127.0.0.1:4443"
HOME = "box-yard-0001"
PATH1 = HOME + "/yard-0001/yard-box/gate-cam.hang"
PATH2 = HOME + "/yard-0001/yard-box/dock-cam.hang"


def _page():
    with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


def jwt(room, exp=None):
    body = base64.urlsafe_b64encode(json.dumps({"get": room, "exp": int(exp or time.time() + 86400)}).encode()).decode().rstrip("=")
    return "h." + body + ".s-" + room


class FakeRelay:
    """mint(base, room, access, code) and post(url, body, bearer) as the bridge calls them."""

    def __init__(self, locked=None, banned=None):
        self.locked = dict(locked or {})     # room -> its code
        self.banned = set(banned or ())
        self.mints, self.posts = [], []

    def mint(self, base, room, access, code, timeout=5, host=None):
        self.mints.append((room, access, code))
        if room in self.locked and code != self.locked[room]:
            return "refused", None, "wrong room code"
        return "token", base + "/?jwt=" + jwt(room), "member"

    def post(self, url, body, bearer):
        self.posts.append((url, json.loads(json.dumps(body)), bearer))
        if body.get("stop"):
            return {"ok": True, "to": list(body.get("to") or []), "stopped": list(body.get("to") or [])}, 200
        acc = [r for r in body["to"] if r not in self.banned]
        ref = {r: "removed from that room by an admin" for r in body["to"] if r in self.banned}
        return {"ok": bool(acc), "to": acc, "refused": ref, "expires": int(time.time() + 180)}, (200 if acc else 403)

    def lists(self):
        return [p for p in self.posts if not p[1].get("stop")]

    def stops(self):
        return [p for p in self.posts if p[1].get("stop")]


class FakeHandler:
    def __init__(self, path, body=None, command="POST"):
        raw = json.dumps(body).encode() if body is not None else b""
        self.path, self.command = path, command
        self.headers = {"Content-Length": str(len(raw)), "Host": "127.0.0.1:8000"}
        self.client_address = ("127.0.0.1", 50000)
        self.rfile, self.wfile = io.BytesIO(raw), io.BytesIO()
        self.code = None

    def send_response(self, code):
        self.code = code

    def send_header(self, k, v):
        pass

    def end_headers(self):
        pass

    def body(self):
        return json.loads(self.wfile.getvalue().decode() or "null")


SAVED_ON_AIR = kastr_rtsp.xs_on_air   # 0.21.76: the real rule (Sandbox stubs it)


class Sandbox(unittest.TestCase):
    def setUp(self):
        self._saved = [(kastr_rtsp.subprocess, "Popen", kastr_rtsp.subprocess.Popen),
                       (kastr_rtsp.Bridge, "legacy_sweep", kastr_rtsp.Bridge.legacy_sweep),
                       (kastr_rtsp.Bridge, "sweep_orphans", kastr_rtsp.Bridge.sweep_orphans),
                       (kastr_rtsp.Publisher, "start", kastr_rtsp.Publisher.start),
                       (kastr_rtsp, "mint_member", kastr_rtsp.mint_member),
                       (kastr_relay, "is_local", kastr_relay.is_local),
                       (kastr_rtsp, "xs_on_air", kastr_rtsp.xs_on_air)]

        def no_spawn(*a, **k):
            raise AssertionError("a process was spawned")
        kastr_rtsp.subprocess.Popen = no_spawn
        kastr_rtsp.Bridge.legacy_sweep = lambda self: 0
        kastr_rtsp.Bridge.sweep_orphans = lambda self: 0
        kastr_rtsp.Publisher.start = lambda self: None
        kastr_relay.is_local = lambda h: True
        kastr_rtsp.xs_on_air = lambda pub, now=None: getattr(self, "on_air", True)   # 0.21.76: these pairs never start (on air unless a test says not)
        self.relay = FakeRelay(locked={"rl": "1234"}, banned={"rbn"})
        kastr_rtsp.mint_member = self.relay.mint      # set_xs ticks with the module's minter
        self.tmp = tempfile.TemporaryDirectory()
        self.lines = []

    def tearDown(self):
        for obj, name, val in reversed(self._saved):
            setattr(obj, name, val)
        self.tmp.cleanup()

    def bridge(self, session=True):
        b = kastr_rtsp.Bridge(state_dir=self.tmp.name, log=lambda m, *a, **k: self.lines.append(str(m)), host_slug="yard-0001")
        b.moq = "moq"
        b._xs_post = self.relay.post                  # the instance's POST (xs_tick's default)
        self.ensured = []
        b._xs_ensure = lambda: self.ensured.append(1)  # no background loop in a test
        if session:
            b.set_session(HOME, "ACC", "", RELAY)
        return b

    def camera(self, b, path=PATH1, label="Gate Cam"):
        feed = b.add("test://pattern")
        b.publish(feed.id, path, RELAY + "/?jwt=" + jwt(HOME), audio=False, keep=True, label=label)
        return feed

    def tick(self, b):
        return b.xs_tick(post=self.relay.post, mint=self.relay.mint)

    def feeds_doc(self):
        import kastr_secret   # 0.21.92: the codes are sealed on disk; the reader opens them
        p = os.path.join(self.tmp.name, "rtsp-feeds.json")
        with open(p, encoding="utf-8") as f:
            return kastr_secret.open_doc(p, json.load(f))


class HomeRoom(unittest.TestCase):
    def test_rule(self):
        self.assertEqual(kastr_rtsp.home_room("yard-0001"), "box-yard-0001")
        long = "a-very-long-robot-box-name-here-x-1a2b"
        h = kastr_rtsp.home_room(long)
        self.assertLessEqual(len(h), 32)
        self.assertTrue(h.startswith("box-") and h.endswith("-1a2b"), h)
        self.assertTrue(kastr_relay.SLUG_RE.match(h))       # a room the relay accepts
        self.assertTrue(kastr_rtsp.is_home_room(h))
        self.assertFalse(kastr_rtsp.is_home_room("yard"))
        self.assertFalse(kastr_rtsp.is_home_room(""))


class Loop(Sandbox):
    def test_lists_with_the_home_token_and_one_member_token_per_room(self):
        b = self.bridge()
        feed = self.camera(b)
        feed.xs = ["ra", "rb"]
        out = self.tick(b)
        self.assertEqual(out, {PATH1: {"ra": "ok", "rb": "ok"}})
        self.assertEqual(feed.xs_state, {"ra": "ok", "rb": "ok"})
        (url, body, bearer), = self.relay.lists()
        self.assertEqual(url, "http://127.0.0.1:4444/api/xshare")            # the relay's minter (port + 1)
        self.assertIn(".s-" + HOME, bearer)                                    # proven by the pair's own room
        self.assertEqual(sorted(body["tokens"]), ["ra", "rb"])
        self.assertIn(".s-ra", body["tokens"]["ra"])
        self.assertEqual((body["path"], body["to"], body["label"], body["kind"], body["by"]),
                         (PATH1, ["ra", "rb"], "Gate Cam", "rtsp", "yard-box"))
        self.assertTrue(all(m[1] == "ACC" for m in self.relay.mints))         # the box's saved access code
        n = len(self.relay.mints)
        self.tick(b)                                                           # the heartbeat: tokens are cached
        self.assertEqual(len(self.relay.mints), n)
        self.assertEqual(len(self.relay.lists()), 2)
        self.assertIn(PATH1, b._xs_listed)

    def test_dropped_room_removed_camera_and_switch_off_withdraw(self):
        b = self.bridge()
        f1, f2 = self.camera(b), self.camera(b, PATH2, "Dock Cam")
        f1.xs, f2.xs = ["ra", "rb"], ["rb"]
        self.tick(b)
        f1.xs = ["ra"]
        self.tick(b)
        self.assertEqual([(s[1]["path"], s[1]["to"]) for s in self.relay.stops()], [(PATH1, ["rb"])])
        self.assertIn(".s-" + HOME, self.relay.stops()[0][2])                 # a stop needs the home token only
        b.unpublish(f2.id)                                                     # off the air -> out of rb
        self.tick(b)
        self.assertEqual(self.relay.stops()[-1][1]["path"], PATH2)
        b.suspend("t")                                                         # the box's Cameras switch
        self.tick(b)
        self.assertEqual((self.relay.stops()[-1][1]["path"], self.relay.stops()[-1][1]["to"]), (PATH1, ["ra"]))
        self.assertEqual(b._xs_listed, {})
        posts = len(self.relay.posts)
        self.tick(b)
        self.assertEqual(len(self.relay.posts), posts)                         # nothing more while off

    def test_refusals_show_on_the_row_and_a_wrong_code_is_not_retried(self):
        b = self.bridge()
        feed = self.camera(b)
        feed.xs = ["ra", "rl", "rbn"]
        self.tick(b)
        self.assertEqual(feed.xs_state["ra"], "ok")
        self.assertIn("locked", feed.xs_state["rl"])
        self.assertIn("admin", feed.xs_state["rbn"])
        tries = [m for m in self.relay.mints if m[0] == "rl"]
        self.tick(b)
        self.assertEqual([m for m in self.relay.mints if m[0] == "rl"], tries)  # the same (missing) code is not tried again
        r = b.set_xs(feed.id, ["ra", "rl", "rbn"], {"rl": "1234"})           # the code typed on the row
        self.assertEqual(r["xsState"]["rl"], "ok")
        self.assertEqual(r["xsLocked"], ["rl"])
        self.assertNotIn("1234", json.dumps(r))
        self.assertNotIn("1234", json.dumps(b.list()))
        self.assertEqual(self.feeds_doc()["feeds"][0]["xsCodes"], {"rl": "1234"})   # rtsp-feeds.json keeps it (sealed, 0.21.92)


class SetAndPersist(Sandbox):
    def test_set_xs_validates_and_persists(self):
        b = self.bridge()
        feed = self.camera(b)
        with self.assertRaises(ValueError):
            b.set_xs(feed.id, ["Bad Name!"])
        with self.assertRaises(ValueError):
            b.set_xs(feed.id, ["box-other-0002"])                              # never into a box's home
        with self.assertRaises(ValueError):
            b.set_xs(feed.id, ["r%d" % i for i in range(kastr_rtsp.XS_ROOMS_MAX + 1)])
        with self.assertRaises(ValueError):
            b.set_xs(999, ["ra"])
        r = b.set_xs(feed.id, ["ra", HOME, "ra", "rb"])                        # its own room and doubles drop out
        self.assertEqual(r["xs"], ["ra", "rb"])
        self.assertEqual(r["xsState"], {"ra": "ok", "rb": "ok"})
        self.assertEqual(self.ensured, [1])                                    # the loop keeps it listed
        rec = self.feeds_doc()["feeds"][0]
        self.assertEqual(rec["xs"], ["ra", "rb"])
        self.assertNotIn("xsCodes", rec)
        self.assertEqual(b.list()[0]["xs"], ["ra", "rb"])
        b.set_xs(feed.id, [])
        self.assertNotIn("xs", self.feeds_doc()["feeds"][0])
        self.assertEqual([s[1]["to"] for s in self.relay.stops()], [["ra", "rb"]])

    def test_restore_brings_the_rooms_back(self):
        doc = {"room": HOME, "access": "ACC", "roomCode": "", "relay": RELAY,
               "feeds": [{"url": "test://pattern", "broadcast": PATH1, "keep": True, "label": "Gate Cam", "audio": False,
                          "xs": ["ra", "rl", "box-x-0003"], "xsCodes": {"rl": "1234", "zz": "9"}}]}
        with open(os.path.join(self.tmp.name, "rtsp-feeds.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f)
        b = self.bridge(session=False)
        before = b._feed_records()                                             # not restored yet: the pending record keeps them
        self.assertEqual(before[0]["xs"], ["ra", "rl", "box-x-0003"])
        self.assertEqual(b.restore(mint=lambda: RELAY + "/?jwt=" + jwt(HOME)), 1)
        feed = list(b._feeds.values())[0]
        self.assertEqual(feed.xs, ["ra", "rl"])                                # a box-* name never comes back
        self.assertEqual(feed.xs_codes, {"rl": "1234"})
        self.assertTrue(self.ensured)                                          # the loop starts with the restore
        out = self.tick(b)
        self.assertEqual(out[PATH1], {"ra": "ok", "rl": "ok"})
        rec = self.feeds_doc()["feeds"][0]
        self.assertEqual((rec["xs"], rec["xsCodes"]), (["ra", "rl"], {"rl": "1234"}))


class Endpoint(Sandbox):
    def test_api_rtsp_xs(self):
        b = self.bridge()
        feed = self.camera(b)
        h = FakeHandler("/api/rtsp/xs", {"id": feed.id, "rooms": ["ra"]})
        self.assertTrue(kastr_rtsp.handle_api(h, b, "/api/rtsp/xs"))
        self.assertEqual((h.code, h.body()["xs"], h.body()["xsState"]), (200, ["ra"], {"ra": "ok"}))
        h = FakeHandler("/api/rtsp/xs", {"id": feed.id, "rooms": ["box-q-0004"]})
        kastr_rtsp.handle_api(h, b, "/api/rtsp/xs")
        self.assertEqual(h.code, 400)
        kastr_relay.is_local = lambda h: False
        h = FakeHandler("/api/rtsp/xs", {"id": feed.id, "rooms": []})
        kastr_rtsp.handle_api(h, b, "/api/rtsp/xs")
        self.assertEqual(h.code, 403)                                          # from the box itself only
        self.assertEqual(feed.xs, ["ra"])


class Page(unittest.TestCase):
    def setUp(self):
        self.p = _page()

    def test_home_room_helpers_match_the_server_rule(self):
        p = self.p
        self.assertIn('const HOME_PREFIX = "box-";', p)
        self.assertIn('const isHomeRoom = (slug) => String(slug || "").startsWith(HOME_PREFIX);', p)
        self.assertIn("name.slice(0, 32 - HOME_PREFIX.length - 5)", p)
        self.assertEqual(kastr_rtsp.HOME_PREFIX, "box-")

    def test_the_box_gate_offers_no_room(self):
        p = self.p
        self.assertIn('if (isPublisherMode()) sel.appendChild(new Option("No room \\u2014 this box only shares its cameras into the rooms I pick", "__home"));', p)
        self.assertIn('} else if (joinEls.joinChanSel.value === "__home") {', p)
        self.assertIn("slug = homeRoomOf(HOSTNAME1);", p)
        self.assertIn('if (isHomeRoom(want)) want = isPublisherMode() ? "__home" : "main";', p)

    def test_nobody_creates_a_box_room(self):
        p = self.p
        self.assertEqual(p.count("are kept for camera boxes"), 3)              # the gate, the rail's form, Room settings > rename

    def test_viewers_hide_home_rooms(self):
        p = self.p
        self.assertIn("if (isPublisherMode() && isHomeRoom(CHANNEL)) pubModel.home = 1; else delete pubModel.home;", p)
        self.assertIn("home: v.home === 1", p)
        self.assertIn("if (p.who.home) homeOnly.add(p.slug);", p)
        self.assertIn("(r.slug === inNow || !(isHomeRoom(r.slug) || (homeOnly.has(r.slug) && !r.members.size)))", p)
        self.assertIn("r.slug !== LOBBY && !isHomeRoom(r.slug)).sort(", p)    # the show-in-rooms picker
        body = p[p.index("  function shortLabel(path, hover) {"):p.index("  window.__pretty = prettyOperator;")]
        self.assertIn("fromBox = !!xt && isHomeRoom(xt.from)", body)
        self.assertIn("(fromBox && String(xt.label || \"\").replace(", body)   # a page-listed label already names its sharer

    def test_box_rows_are_server_owned(self):
        p = self.p
        self.assertIn('const xsServerPath = (path) => isPublisherMode() && xsKindOf(path) !== "grid";', p)
        self.assertIn('fetch("/api/rtsp/xs", { method: "POST"', p)
        self.assertIn("const xsRowBtn = (a) => {", p)
        self.assertIn("{ const xb = xsRowBtn(a); if (xb)", p)
        self.assertIn('b.textContent = !rooms.length ? "Show in rooms\\u2026"', p)
        self.assertIn('why.className = "xswhy";', p)
        self.assertIn("const srv = opts?.server || null;", p)
        tick = p[p.index("  async function xsTick() {"):p.index("  // members' side: what is listed into my room")]
        self.assertNotIn("publishOnly || CHANNEL === LOBBY) return;", tick)       # 0.21.75: the publish-only gap is closed
        self.assertIn("if (xsServerPath(p)) {", tick)
        mine = p[p.index("  function paintXsTable(force) {"):p.index("  window.__xsRooms = {")]
        self.assertIn("!xsServerPath(p)", mine)                                # the Share table never posts a box camera itself


class SleepingListedCameras(unittest.TestCase):   # 0.21.75 integration lab: a box camera listed into another room wakes for viewers there
    def test_wiring(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            p = f.read()
        self.assertIn("!inGrid.has(name) && !xsTiles.has(name)) || parkedStreams.has(name)) continue;", p)
        self.assertIn("function odQuick() {", p)
        self.assertIn('(t.watch.getAttribute("visible") !== "never" || t.noCatalog)) t.watch.setAttribute("url", tileUrl(name)); }, 400);', p)   # resubscribe restores a parked tile
        self.assertIn('if (!t.odResub && now - t.odAt > 6000) { t.odResub = true; resubscribe(name, "a camera shown here from another room was asleep"); }', p)
        self.assertIn("if (isHomeRoom(r.slug)) continue;   // 0.21.75: the box's own home room is the \"No room\" choice above", p)


class OnAirOnly(Sandbox):   # 0.21.76 (Kenton: streams that "only run sometimes ... always show connecting" in their other rooms)
    def test_a_dark_camera_is_withdrawn_and_comes_back(self):
        b = self.bridge()
        f1 = self.camera(b)
        f1.xs = ["ra", "rb"]
        self.tick(b)
        self.assertEqual(len(self.relay.lists()), 1)
        self.on_air = False                                                    # the camera went dark / the device stopped pushing
        self.tick(b)
        self.assertEqual([(s[1]["path"], s[1]["to"]) for s in self.relay.stops()], [(PATH1, ["ra", "rb"])])
        self.assertTrue(all("not streaming" in v for v in f1.xs_state.values()))
        n = len(self.relay.lists())
        self.tick(b)
        self.assertEqual(len(self.relay.lists()), n)                           # nothing listed while dark
        self.on_air = True
        self.tick(b)
        self.assertEqual(len(self.relay.lists()), n + 1)                       # listed again once data flows
        self.assertEqual(f1.xs_state, {"ra": "ok", "rb": "ok"})


class OnAirRule(unittest.TestCase):
    def test_rule(self):
        class P:
            running, standby, sleepy, flowingAt, since = True, False, False, None, None
        p, now = P(), 1000.0
        p.flowingAt = 995.0
        self.assertTrue(SAVED_ON_AIR(p, now))                                  # data in the last 20 s
        p.flowingAt = 970.0
        self.assertFalse(SAVED_ON_AIR(p, now))                                 # dark for 30 s
        p.flowingAt, p.since = None, 990.0
        self.assertTrue(SAVED_ON_AIR(p, now))                                  # just started: its first bytes may still come
        p.since = 900.0
        self.assertFalse(SAVED_ON_AIR(p, now))                                 # an RTMP ingest nobody pushes to
        p.running, p.standby, p.sleepy = False, True, True
        self.assertTrue(SAVED_ON_AIR(p, now))                                  # asleep (0.21.73) -- a click there wakes it
        p.sleepy = False
        self.assertFalse(SAVED_ON_AIR(p, now))

    def test_page(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            pg = f.read()
        self.assertIn("if (x.listed !== false && now - x.offSince > 20000) { x.listed = false; xsPost(p, { stop: true, to: [...x.rooms] }); }", pg)
        self.assertIn("if (suppressed.has(p)) {", pg)


if __name__ == "__main__":
    unittest.main()
