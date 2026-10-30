# -*- coding: utf-8 -*-
"""v0.21.96 BOX-OUT. Kenton (2026-10-30): "For Relays/Camera boxes, I would like them to not be able to directly connect to
rooms, they connect to their 'My room' or no room at all, and their shares just go to the library or whatever rooms they tell
them to."

WHICH machines (kastr_serve.boxout_state): a camera box (mode publisher / publisher-relay -> "box"), or a KASTR that runs the
relay itself (mode relay, its relay running, relay autostart on in relay-autostart.json or kastr.ini -> "relay"). A viewer
display never is; a person's everyday KASTR that runs no relay never is; only the machine's OWN page is told (/api/instance to
a local caller), never a web client of a relay host nor its presentation recorder.

Such a machine sits in its hidden home room (box-<host>, "No room") or its own My room. A box that sat in a real room R moves
out ONCE at the launch of this version (kastr.feeds_boxout -> kastr_rtsp.boxout_migrate): every camera moves to box-<host>/...,
shows in R again through Show in rooms (xs, R's code kept) and keeps its R path as a library alias -- viewers in R see no
change. The relay's minter refuses a `boxed` page a real room; the box server refuses its own page a real room for its
cameras; listing tokens (Show in rooms) never carry the flag. No machine identity exists before 0.22: the flag is the page's
own word -- page + local KASTR enforcement, backed by the minter.

Run: python -m unittest discover -s tests
No network, no processes."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_rtsp  # noqa: E402
import kastr_relay  # noqa: E402
import kastr_serve  # noqa: E402

TESTS = os.path.dirname(os.path.abspath(__file__))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)
import test_release_0_21_75_boxrooms as br  # noqa: E402  (the 0.21.75 sandbox: no processes, injected minter)

HOST = "yard-0001"
HOME = "box-yard-0001"


def _read(name):
    with open(os.path.join(HERE, name), "rb") as f:
        return f.read().decode("utf-8")


class FakeRelaySrv:
    def __init__(self, running=False, auto=False):
        self._r, self._a = running, auto

    def running(self):
        return self._r

    def autostart_config(self):
        return {"enabled": self._a}


class WhichMachines(unittest.TestCase):
    def setUp(self):
        self._mode = kastr_serve.MODE
        self._ini = mock.patch.object(kastr_serve, "ini_get", lambda k: None)
        self._ini.start()

    def tearDown(self):
        kastr_serve.MODE = self._mode
        self._ini.stop()

    def st(self, mode, relay=None):
        kastr_serve.MODE = mode
        return kastr_serve.boxout_state(relay)

    def test_camera_boxes(self):
        self.assertEqual(self.st("publisher"), {"on": True, "why": "box"})
        self.assertEqual(self.st("publisher-relay", FakeRelaySrv(running=True)), {"on": True, "why": "box"})

    def test_relay_machines(self):
        self.assertEqual(self.st("relay"), {"on": True, "why": "relay"})
        self.assertEqual(self.st("full", FakeRelaySrv(running=True)), {"on": True, "why": "relay"})
        self.assertEqual(self.st("full", FakeRelaySrv(auto=True)), {"on": True, "why": "relay"})
        with mock.patch.object(kastr_serve, "ini_get", lambda k: "true" if k == "relay_autostart" else None):
            self.assertEqual(self.st("full"), {"on": True, "why": "relay"})

    def test_a_persons_kastr_and_viewer_displays_never(self):
        self.assertFalse(self.st("full")["on"])                                   # everyday KASTR, no relay here
        self.assertFalse(self.st("full", FakeRelaySrv())["on"])                   # a relay server object that is not running
        self.assertFalse(self.st("viewer", FakeRelaySrv(running=True))["on"])     # a viewer display watches rooms

    def test_a_broken_relay_object_is_not_a_relay(self):
        class Bad:
            def running(self):
                raise RuntimeError("x")

            def autostart_config(self):
                raise RuntimeError("x")
        self.assertFalse(self.st("full", Bad())["on"])

    def test_only_the_machines_own_page_is_told(self):
        s = _read("kastr_serve.py")
        self.assertIn('if local:   # 0.21.96: box-out', s)
        self.assertIn('d["boxout"] = boxout_state(relay_srv)', s)
        self.assertIn('out["_boxout"] = dict(boxout_state(relay_srv), log=list(BOXOUT_LOG))', s)
        self.assertIn('bridge.boxout = lambda rs=relay_srv: bool(boxout_state(rs)["on"])', s)

    def test_note_log_is_bounded(self):
        saved = list(kastr_serve.BOXOUT_LOG)
        try:
            for i in range(60):
                kastr_serve.boxout_note("n%d" % i)
            self.assertEqual(len(kastr_serve.BOXOUT_LOG), kastr_serve.BOXOUT_LOG_MAX)
            self.assertEqual(kastr_serve.BOXOUT_LOG[-1]["text"], "n59")
        finally:
            kastr_serve.BOXOUT_LOG[:] = saved


class RealRoom(unittest.TestCase):
    def test_rule(self):
        r = kastr_rtsp.boxout_real_room
        for s in ("yard", "main", "mt-0123456789ab", "a"):
            self.assertTrue(r(s), s)
        for s in ("", None, HOME, "box-other-0002", "me-0123456789ab", "lib"):
            self.assertFalse(r(s), s)


def doc_in(room="yard", code="1234"):
    return {"room": room, "roomCode": code, "access": "ACC", "relay": "http://127.0.0.1:4443", "feeds": [
        {"url": "rtsp://cam/1", "broadcast": room + "/yard-0001/yard-box/gate-cam.hang", "keep": True, "xs": ["dock", "yard"]},
        {"url": "rtsp://cam/2", "broadcast": room + "/yard-0001/yard-box/dock-cam.hang", "keep": True, "xsAuto": room},
        {"url": "rtsp://web/3", "broadcast": "other/web-1/op/cam.hang", "room": "other", "keep": True},   # a web client's
    ]}


class Migrate(unittest.TestCase):
    def test_moves_out_and_keeps_listing(self):
        doc, note = kastr_rtsp.boxout_migrate(doc_in(), HOST, now=1000)
        self.assertEqual((doc["room"], doc["roomCode"]), (HOME, ""))
        f1, f2, web = doc["feeds"]
        self.assertEqual(f1["broadcast"], HOME + "/yard-0001/yard-box/gate-cam.hang")
        self.assertEqual(f1["xs"], ["dock", "yard"])                          # R once, last
        self.assertEqual(f1["xsCodes"], {"yard": "1234"})                     # the locked room's code rides with it
        self.assertEqual(f1["libAka"], {"yard/yard-0001/yard-box/gate-cam.hang": 1000})
        self.assertEqual(f2["xs"], ["yard"])
        self.assertNotIn("xsAuto", f2)                                        # the library's listing-back is now a kept one
        self.assertEqual(web["broadcast"], "other/web-1/op/cam.hang")        # a web client's camera: untouched
        self.assertEqual(web["room"], "other")
        self.assertEqual(doc["boxout"], {"from": "yard", "to": HOME, "at": 1000, "why": "box", "feeds": 2})
        self.assertIn("left room yard for No room (" + HOME + ")", note)
        self.assertIn("2 camera(s) moved, each still shown in yard", note)
        self.assertNotIn("1234", note)

    def test_once(self):
        doc, _ = kastr_rtsp.boxout_migrate(doc_in(), HOST, now=1000)
        snap = json.dumps(doc, sort_keys=True)
        doc2, note2 = kastr_rtsp.boxout_migrate(doc, HOST, now=2000)
        self.assertIsNone(note2)
        self.assertEqual(json.dumps(doc2, sort_keys=True), snap)

    def test_home_personal_empty_untouched(self):
        for room in (HOME, "me-0123456789ab", ""):
            d = doc_in(room)
            snap = json.dumps(d, sort_keys=True)
            self.assertIsNone(kastr_rtsp.boxout_migrate(d, HOST)[1])
            self.assertEqual(json.dumps(d, sort_keys=True), snap)

    def test_lobby_lists_nothing_back(self):
        doc, note = kastr_rtsp.boxout_migrate(doc_in("main", ""), HOST, now=5, why="relay")
        f1 = doc["feeds"][0]
        self.assertEqual(doc["room"], HOME)
        self.assertEqual(f1["broadcast"], HOME + "/yard-0001/yard-box/gate-cam.hang")
        self.assertEqual(f1["xs"], ["dock", "yard"])                          # (its own picks stay, nothing added)
        self.assertNotIn("libAka", f1)
        self.assertIn("this relay machine left room main", note)

    def test_xs_cap(self):
        d = doc_in()
        d["feeds"][0]["xs"] = ["r%d" % i for i in range(kastr_rtsp.XS_ROOMS_MAX)]
        doc, _ = kastr_rtsp.boxout_migrate(d, HOST)
        xs = doc["feeds"][0]["xs"]
        self.assertEqual(len(xs), kastr_rtsp.XS_ROOMS_MAX)
        self.assertEqual(xs[-1], "yard")


class Launch(unittest.TestCase):
    """kastr.feeds_boxout: the launch's one-time move, written back sealed and logged (launch.log + /api/diag)."""

    def setUp(self):
        import kastr
        self.k = kastr
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "rtsp-feeds.json")
        self.notes = []
        self.saved_log = list(kastr_serve.BOXOUT_LOG)

    def tearDown(self):
        kastr_serve.BOXOUT_LOG[:] = self.saved_log
        self.tmp.cleanup()

    def run_it(self, on, why="box"):
        bridge = type("B", (), {"host_slug": HOST})()
        with mock.patch.object(kastr_serve, "boxout_state", lambda relay=None: {"on": on, "why": why if on else ""}), \
                mock.patch.object(self.k, "note", self.notes.append):
            return self.k.feeds_boxout(self.path, doc_in(), bridge, None, now=77)

    def test_boxed_moves_and_writes_sealed(self):
        doc = self.run_it(True)
        self.assertEqual(doc["room"], HOME)
        with open(self.path, encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn('"1234"', raw)                                       # the codes stay sealed on disk
        import kastr_secret
        disk = kastr_secret.open_doc(self.path, json.loads(raw))
        self.assertEqual(disk["room"], HOME)
        self.assertEqual(disk["feeds"][0]["xsCodes"], {"yard": "1234"})
        self.assertEqual(len(self.notes), 1)
        self.assertIn("box-out: this camera box left room yard", self.notes[0])
        self.assertIn(self.notes[0], [e["text"] for e in kastr_serve.BOXOUT_LOG])

    def test_not_boxed_nothing(self):
        doc = self.run_it(False)
        self.assertEqual(doc["room"], "yard")
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.notes, [])

    def test_wired_before_the_restore(self):
        s = _read("kastr.py")
        i = s.index("doc = feeds_boxout(path, doc, bridge, getattr(server, \"relay\", None))")
        self.assertLess(s.index("doc = kastr_secret.open_doc(path, doc)   # 0.21.92"), i)
        self.assertLess(i, s.index('room = str(doc.get("room") or "").strip().lower()', i))


class Carry(br.Sandbox):
    """A camera of a boxed machine that leaves a real room for its home room keeps showing there."""

    def test_carry_on_republish(self):
        b = self.bridge(session=False)
        b.set_session("yard", "ACC", "4321", br.RELAY)
        b.boxout = lambda: False
        notes = []
        b.boxout_note = notes.append
        old = "yard/yard-0001/yard-box/gate-cam.hang"
        feed = b.add("test://pattern")
        b.publish(feed.id, old, br.RELAY + "/?jwt=" + br.jwt("yard"), audio=False, keep=True, label="Gate")
        self.assertFalse(getattr(feed, "xs", None))
        b.boxout = lambda: True
        b.set_session(HOME, "ACC", "", br.RELAY)
        b.publish(feed.id, br.PATH1, br.RELAY + "/?jwt=" + br.jwt(HOME), audio=False, keep=True, label="Gate", force=True)
        self.assertEqual(feed.xs, ["yard"])
        self.assertIn(old, feed.lib_aka)
        self.assertTrue(any("left room yard" in n for n in notes))

    def test_no_carry_when_not_boxed(self):
        b = self.bridge(session=False)
        b.set_session("yard", "ACC", "", br.RELAY)
        b.boxout = lambda: False
        feed = b.add("test://pattern")
        b.publish(feed.id, "yard/yard-0001/yard-box/gate-cam.hang", br.RELAY + "/?jwt=" + br.jwt("yard"), audio=False, keep=True)
        b.publish(feed.id, br.PATH1, br.RELAY + "/?jwt=" + br.jwt(HOME), audio=False, keep=True, force=True)
        self.assertFalse(getattr(feed, "xs", None))

    def test_box_server_refuses_its_page_a_real_room(self):
        b = self.bridge()
        b.boxout = lambda: True
        feed = b.add("test://pattern")
        h = br.FakeHandler("/api/rtsp/publish", {"id": feed.id, "broadcast": "yard/yard-0001/yard-box/gate-cam.hang", "relay": br.RELAY})
        self.assertTrue(kastr_rtsp.handle_api(h, b, "/api/rtsp/publish"))
        self.assertEqual(h.code, 403)
        self.assertTrue(h.body()["boxed"])
        self.assertIn("No room or its My room", h.body()["error"])
        h = br.FakeHandler("/api/rtsp/persist", {"room": "yard", "access": "ACC"})
        kastr_rtsp.handle_api(h, b, "/api/rtsp/persist")
        self.assertEqual(h.code, 403)
        h = br.FakeHandler("/api/rtsp/persist", {"room": HOME, "access": "ACC"})
        kastr_rtsp.handle_api(h, b, "/api/rtsp/persist")
        self.assertNotEqual(h.code, 403)
        b.boxout = lambda: False                                              # a person's KASTR: as before
        h = br.FakeHandler("/api/rtsp/persist", {"room": "yard", "access": "ACC"})
        kastr_rtsp.handle_api(h, b, "/api/rtsp/persist")
        self.assertNotEqual(h.code, 403)


class Minter(unittest.TestCase):
    def setUp(self):
        st = kastr_relay.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        self.svc = kastr_relay.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)
        self.svc.store.touch_room("yard", "kenton")

    def tearDown(self):
        self.svc.close()

    def mint(self, room, boxed=None, host=HOST, **kw):
        body = dict({"room": room, "code": "pub-1", "host": host}, **kw)
        if boxed is not None:
            body["boxed"] = boxed
        return self.svc.token(body, "10.0.0.7")

    def test_boxed_page_refused_a_real_room(self):
        o, c = self.mint("yard", boxed=True)
        self.assertEqual(c, 403)
        self.assertTrue(o["boxed"])
        self.assertEqual(o["error"], kastr_relay.BOXOUT_REFUSED)
        self.assertEqual(self.mint("main", boxed=True)[1], 403)               # nor the Lobby

    def test_boxed_page_gets_its_home_room(self):
        o, c = self.mint(HOME, boxed=True)
        self.assertEqual(c, 200, o)
        self.assertEqual(self.mint("box-other-0002", boxed=True)[1], 403)     # never another box's home

    def test_a_persons_page_and_listing_tokens_unchanged(self):
        self.assertEqual(self.mint("yard")[1], 200)                           # no flag: a person, or Show in rooms' listing mint
        self.assertEqual(self.mint("yard", boxed=False)[1], 200)

    def test_my_room_rule(self):
        r = kastr_relay.boxout_refusal
        self.assertEqual(r("me-0123456789ab", HOST, {}, False), "")
        self.assertTrue(r("me-0123456789ab", HOST, {"invite": "tok"}, False))  # a guest's invite is not its own My room
        self.assertTrue(r("me-0123456789ab", HOST, {"admit": "ka-1-2"}, False))
        self.assertTrue(r("me-0123456789ab", HOST, {"meet": {"n": 1}}, False))
        self.assertEqual(r(HOME, HOST, {}, False), "")
        self.assertTrue(r(HOME, "other-0002", {}, True))
        self.assertTrue(r("yard", HOST, {}, False))

    def test_same_words_both_sides(self):
        self.assertEqual(kastr_relay.BOXOUT_REFUSED, kastr_rtsp.BOXOUT_REFUSED)


class Page(unittest.TestCase):
    def setUp(self):
        self.p = _read("moq-watch-lite.html")

    def test_join_page_offers_only_my_room_and_no_room(self):
        p = self.p
        i = p.index("function gatePaintChannels() {")
        j = p.index("if (boxedOut()) {", i)
        blk = p[j:p.index("return;\r\n    }", j)]
        self.assertIn('new Option(BOXOUT_HOME_TEXT(), "__home")', blk)
        self.assertIn('new Option("My room", "__mine")', blk)
        self.assertNotIn("lastChannelList", blk)
        self.assertNotIn("__new", blk)
        self.assertIn('"No room \\u2014 this machine only shares into " + (lib ? "the library and " : "") + "the rooms I pick"', p)

    def test_every_way_in_is_refused_with_one_line(self):
        p = self.p
        for fn in ("async function sbCardClick(card, rec) {", "async function switchRoom(rec, code, opts) {",
                   "async function inviteArrive(inv) {", "async function personalGuestEnter(slug) {",
                   "async function authMint(room, access, roomCode) {"):
            i = p.index(fn)
            self.assertIn("boxedOut()", p[i:i + 600], fn)
        i = p.index("async function personInviteArrive(it) {")
        self.assertIn("boxedOut() && !boxRoomOk(room)", p[i:i + 1600])
        i = p.index('document.getElementById("sbCreate")?.addEventListener("click"')
        self.assertIn("creates no room", p[i:i + 400])
        i = p.index("async function joinNow() {")
        blk = p[i:i + 9000]
        self.assertIn('if (boxedOut()) return joinFail("This " + boxWhat() + " creates no room', blk)
        self.assertIn("if (boxedOut() && !boxRoomOk(slug)) {", blk)
        self.assertIn("body.boxout #sbCreate, body.boxout #sbCreateHd { display:none !important; }", p)

    def test_mint_says_boxed_and_listing_mints_do_not(self):
        p = self.p
        self.assertIn("boxed: boxedOut() || undefined,", p)
        self.assertEqual(p.count("boxed: boxedOut()"), 1)                      # only authMint -- xsTokenFor never sends it
        i = p.index("function xsTokenFor")
        self.assertNotIn("boxed", p[i:i + 2500])

    def test_my_room_and_home_only(self):
        p = self.p
        i = p.index("function boxRoomOk(slug) {")
        blk = p[i:i + 400]
        self.assertIn("s === boxHome()", blk)
        self.assertIn("s === personalGet()?.slug", blk)
        self.assertIn("function boxHome() { try { return homeRoomOf(HOSTNAME1);", p)

    def test_old_rooms_move_out_on_the_page_too(self):
        p = self.p
        i = p.index("function boxoutGate() {")
        blk = p[i:i + 2600]
        self.assertIn('sessionStorage.setItem("kastr.rejoin", JSON.stringify({ ...t, room: home, code: "", main: false }))', blk)
        self.assertIn('localStorage.setItem("kastr.lastjoin", JSON.stringify({ ...lj, room: home, code: "" }))', blk)
        i = p.index("function gateShow() {")
        self.assertIn("boxoutGate();", p[i:i + 4000])
        self.assertIn("(isPublisherMode() || boxedOut()) && !pubRejoinStop", p)
        self.assertIn('PAGE_MODE !== "relay" && !boxedOut();', p)             # mainPerson: the Join room page, as a box
        i = p.index("function boxCarry(from, code) {")
        self.assertIn("xsCodes[from] = String(code)", p[i:i + 1500])         # (memory only -- never stored)
        self.assertNotIn("kastr.boxout.carry\", JSON.stringify({ from, to: home, until: Date.now() + 600000, code", p)

    def test_instance_read_and_polled(self):
        p = self.p
        self.assertIn("boxoutRead(d);   // 0.21.96: box-out", p)
        self.assertIn("if (!IS_WEB) setInterval(() => { boxoutPoll(); }, 30000);", p)
        self.assertIn("function boxedOut() { try { return !IS_WEB && !!BOXOUT.on; }", p)

    def test_cameras_are_the_box_servers(self):
        p = self.p
        self.assertIn('|| (boxedOut() && (xsKindOf(path) === "rtsp" || window.__xsServer?.owned?.(path) != null));', p)
        self.assertIn("|| !!window.__boxout?.on?.();   // 0.21.96", p)

    def test_join_heading_names_no_room_or_my_room(self):
        p = self.p
        i = p.index("function gateHeadingSlug(cur, joined) {")
        blk = p[i:i + 500]
        self.assertIn("if (boxedOut() && !joined) {", blk)
        self.assertIn('sel === "__home" || !boxRoomOk(cur) ? boxHome() : cur', blk)
        self.assertIn('function gateHeadingTitle(slug) { return isHomeRoom(slug) ? "No room" : roomTitle(slug); }', p)
        self.assertEqual(p.count("joinEls.joinChannelCur.textContent = gateHeadingTitle(gateHeadingSlug("), 2)
        self.assertEqual(p.count('boxSay("Invite link not used. " + boxRefusal('), 2)

    def test_no_plain_checkbox_added(self):
        p = self.p
        i = p.index("// ---- 0.21.96 BOX-OUT")
        blk = p[i:p.index("window.__boxout = {", i)]
        self.assertNotIn("checkbox", blk)


if __name__ == "__main__":
    unittest.main()
