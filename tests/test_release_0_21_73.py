# -*- coding: utf-8 -*-
"""v0.21.73, Kenton's 2026-10-15 asks:
- "lets work on encode only while watched" (he chose: only the cameras the box TRANSCODES) -- a grid camera whose pair
  encodes sleeps a minute after its last viewer and wakes on a viewer's demand (any site), copies stay on;
- "restart a client KASTR remotely through the fed hub or the relay they are connected to" (10 s notice, then restart);
- "force a client to move to a different relay" (this session only);
- "Admin needs to be able to do the same functions as a publisher in addition to admin";
- "In the user section, I would like a toggle to view offline in addition to online, and have this off by default".

Run: python -m unittest discover -s tests
"""
import hashlib
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_rtsp  # noqa: E402
import kastr_serve  # noqa: E402

SALT = "00112233aabbccdd"


def h(code):
    return hashlib.sha256((SALT + code).encode()).hexdigest()


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def svc():
    st = kr.AuthStore(tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)


class AdminLikePublisher(unittest.TestCase):
    def test_admin_code_locks_and_keeps_a_room(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        o, c = kr.register_room(st, {"slug": "admins", "salt": SALT, "hash": h("gate"), "access": "adm-1"}, "10.0.0.1")
        self.assertEqual(c, 200, o)
        o, c = kr.register_room(st, {"slug": "viewers", "salt": SALT, "hash": h("gate"), "access": "view-1"}, "10.0.0.1")
        self.assertEqual(c, 403)   # a viewer code still cannot

    def test_spoke_vouches_for_an_admin_and_the_hub_accepts_it(self):
        s = read("kastr_serve.py")
        self.assertIn('if store.check("admin", access) or (_a is not None and hasattr(_a, "_hub_admin_ok") and _a._hub_admin_ok(access)):', s)
        self.assertIn('vouched=p.get("vouch") in ("publisher", "admin"))', read("kastr_relay.py"))


class SleepUnwatched(unittest.TestCase):
    class P:   # the demand loop's view of a pair
        def __init__(self, sleepy=True, standby=False, wokeAt=0.0):
            self.broadcast, self.label, self.relay = "r/h/cam.hang", "cam", "http://x:4443/?jwt=t"
            self.ondemand, self.sleepy, self.standby, self.wokeAt, self.wantedAt = False, sleepy, standby, wokeAt, None
            self.running, self.lowPub, self.calls = not standby, None, []

        def wake(self, why):
            self.calls.append("wake"); self.standby = False

        def sleep(self, why):
            self.calls.append("sleep"); self.standby = True

    def bridge(self, wanted):
        b = kastr_rtsp.Bridge.__new__(kastr_rtsp.Bridge)
        b.web_base_for = lambda key: "http://relayhost:8000"
        b.sent = []

        def post(url, body):
            b.sent.append(body)
            return {"wanted": wanted}
        return b, post

    def test_sleeps_a_minute_after_the_last_viewer_and_wakes_on_demand(self):
        b, post = self.bridge({})
        p = self.P(wokeAt=1000.0)
        b.od_tick([p], now=1030.0, post=post)
        self.assertEqual(p.calls, [])                       # up less than a minute: stays on
        b.od_tick([p], now=1061.0, post=post)
        self.assertEqual(p.calls, ["sleep"])
        self.assertTrue(b.sent[-1]["feeds"][0]["idle"])     # the relay host is told it sleeps while unwatched
        b2, post2 = self.bridge({"r/h/cam.hang": 2.0})
        b2.od_tick([p], now=1100.0, post=post2)
        self.assertEqual(p.calls, ["sleep", "wake"])

    def test_the_relay_host_reports_demand_for_idle_feeds_whatever_its_ondemand_switch(self):
        kastr_serve.ONDEMAND.clear()
        was = kastr_rtsp.ONDEMAND_ENABLED
        kastr_rtsp.ONDEMAND_ENABLED = False
        try:
            out = kastr_serve.ondemand_sync("r", "h", [{"broadcast": "r/h/cam.hang", "idle": True}], now=5000.0)
            self.assertEqual(out, {})                       # nobody asked -> it may sleep
            out = kastr_serve.ondemand_sync("r", "h", [{"broadcast": "r/h/old.hang"}], now=5000.0)
            self.assertIn("r/h/old.hang", out)              # an older box's standby pair: kept awake (0.21.10)
            poked = []
            kastr_serve.ONDEMAND_POKE = lambda: poked.append(1)
            self.assertTrue(kastr_serve.ondemand_touch("r/h/cam.hang", now=5001.0))
            self.assertEqual(poked, [1])                    # the box runs its demand round now
            kastr_serve.ondemand_touch("r/h/cam.hang", now=5010.0)
            self.assertEqual(poked, [1])                    # a pulse while it is wanted is not a fresh demand
            self.assertIn("r/h/cam.hang", kastr_serve.ondemand_sync("r", "h", [{"broadcast": "r/h/cam.hang", "idle": True}], now=5011.0))
        finally:
            kastr_rtsp.ONDEMAND_ENABLED = was
            kastr_serve.ONDEMAND_POKE = None
            kastr_serve.ONDEMAND.clear()

    def test_only_encoding_grid_pairs_sleep(self):
        s = read("kastr_rtsp.py")
        self.assertIn('self.sleepy = bool(self.role == "main" and self.wantIdle and SLEEP_UNWATCHED and self.copy is False and not self.ondemand)', s)
        self.assertIn('"idle": bool(pub.wantIdle),', s)   # remembered across restarts

    def test_page(self):
        p = read("moq-watch-lite.html")
        self.assertIn("const idle = !!slot.inGrid;", p)
        self.assertIn("const asleep = !tiles.has(fp) && !down && !!meta;", p)
        self.assertIn("if ((!known.has(name) && !lowOnly && !inGrid.has(name)) || parkedStreams.has(name)) continue;", p)
        self.assertIn("pi.running === false && !pi.standby && attempts >= GRID_EVICT_AFTER", p)
        self.assertNotIn("if (!odOn) return;   // 0.21.10: no demand leaves this page", p)


class RestartAndMove(unittest.TestCase):
    def setUp(self):
        self.s = svc()

    def tearDown(self):
        self.s.close()

    def checkin(self, started=100):
        return self.s.client_checkin({"node": "pc-1a2b", "version": "0.21.73", "mode": "full", "name": "Pat", "started": started}, "10.0.0.9")[0]

    def test_a_command_rides_the_next_checkin_once(self):
        self.checkin()
        self.assertTrue(self.s.client_cmd("pc-1a2b", "restart"))
        self.assertEqual(self.s.clients_view("0.21.73")[0]["cmd"], "restart")
        o = self.checkin()
        self.assertEqual((o["cmd"]["kind"], o["cmd"]["to"]), ("restart", ""))
        self.assertNotIn("cmd", self.checkin())
        self.assertEqual(self.s.clients_view("0.21.73")[0]["started"], 100)
        self.checkin(started=200)
        self.assertEqual(self.s.clients_view("0.21.73")[0]["started"], 200)   # the Relay page's "restarted"

    def test_unknown_users_and_kinds_are_refused(self):
        self.assertFalse(self.s.client_cmd("ghost-0000", "restart"))
        self.checkin()
        self.assertFalse(self.s.client_cmd("pc-1a2b", "format-disk"))

    def test_a_stale_command_is_dropped(self):
        self.checkin()
        self.s.client_cmd("pc-1a2b", "move", "http://10.0.2.14:4443")
        self.s.clients["pc-1a2b"]["cmd"]["at"] -= 700
        self.assertNotIn("cmd", self.checkin())

    def test_move_targets(self):
        self.assertEqual(kr.client_move_target("10.0.2.14"), "http://10.0.2.14:4443")
        self.assertEqual(kr.client_move_target("10.0.2.14:5443"), "http://10.0.2.14:5443")
        self.assertEqual(kr.client_move_target("https://kastr.example.com/relay"), "https://kastr.example.com/relay")
        for bad in ("", "javascript:alert(1)", "http://a b", "http://x/<y>", "x" * 300):
            self.assertIsNone(kr.client_move_target(bad), bad)

    def test_spoke_users_keep_the_fields(self):
        r = kr.clean_clients([{"node": "pc-1a2b", "started": 123, "cmd": "move"}, {"node": "pc-2b3c", "cmd": "rm"}])
        self.assertEqual((r[0]["started"], r[0]["cmd"], r[1]["cmd"]), (123, "move", ""))

    def test_hub_forwards_to_the_spoke(self):
        self.assertIn('"clientCmd": list(self.cmd.get("clientCmd") or []),', read("kastr_relay.py"))
        self.assertIn('"/api/relay/clients/cmd",     # 0.21.73', read("kastr_relay.py"))

    def test_the_app_shows_a_notice_then_relaunches_on_the_new_relay(self):
        import kastr
        calls = []
        kastr_serve.ADMIN_RELAUNCH_HOOK = lambda relay=None: calls.append(relay)
        old = dict(os.environ)
        try:
            ok = kastr.admin_command({"id": "c1", "kind": "move", "to": "10.0.2.14"}, "hub", {"aliveAge": 2}, "full", sleep=lambda s: calls.append(("slept", s)))
            self.assertTrue(ok)
            self.assertEqual(kastr_serve.ADMIN_NOTICE["kind"], "move")
            for _ in range(50):
                if len(calls) >= 2:
                    break
                time.sleep(0.05)
            self.assertEqual(calls, [("slept", 10), "http://10.0.2.14:4443"])
            self.assertEqual(os.environ.get("KASTR_MOVED"), "http://10.0.2.14:4443")
            self.assertFalse(kastr.admin_command({"id": "c2", "kind": "move", "to": "javascript:x"}, "hub", {}, "full", sleep=lambda s: None))
        finally:
            os.environ.clear(); os.environ.update(old)
            kastr_serve.ADMIN_RELAUNCH_HOOK = None
            kastr_serve.ADMIN_NOTICE.clear()

    def test_relaunch_argv_replaces_the_relay(self):
        import kastr
        saved = sys.argv
        try:
            sys.argv = ["kastr", "--relay", "http://old:4443", "--port", "8001"]
            self.assertEqual(kastr.admin_relaunch_argv("http://new:4443"), ["--port", "8001", "--relay", "http://new:4443"])
            self.assertEqual(kastr.admin_relaunch_argv(None), ["--relay", "http://old:4443", "--port", "8001"])
        finally:
            sys.argv = saved

    def test_pages(self):
        p = read("moq-watch-lite.html")
        self.assertIn("if (!(d?.justUpdated || d?.justRestarted) || joinState", p)
        self.assertIn("if (inst?.justRestarted || inst?.adminMoved) return urlInput.value.trim() || null;", p)
        rel = read("relay.html")
        self.assertIn('<dialog id="mvDlg" class="hubmove">', rel)
        self.assertIn('const r = await api("/api/relay/clients/cmd", { node: ds.node, relay: ds.relay || "", kind, to: to || "" });', rel)


class OfflineUsers(unittest.TestCase):
    def test_off_by_default(self):
        rel = read("relay.html")
        self.assertIn('<input type="checkbox" id="usersOffline">', rel)
        self.assertIn('try { oldBox.checked = localStorage.getItem("kastr.relay.usersOffline") === "1"; } catch {}', rel)
        self.assertNotIn("usersOld", rel)


class SouthridgeZoom(unittest.TestCase):
    def test_assets_are_revalidated(self):
        self.assertIn('self.send_header("Cache-Control", "no-cache")', read("kastr_serve.py"))

    def test_a_cell_zoom_follows_a_rendition_switch(self):
        p = read("moq-watch-lite.html")
        self.assertIn("if (v.cw && (v.cw !== f.cw || v.ch !== f.ch)) { v.cx *= f.cw / v.cw; v.cy *= f.ch / v.ch; }", p)
        self.assertIn("v.cw = f.cw; v.ch = f.ch;", p)


class PauseShare(unittest.TestCase):   # 0.21.73 (Kenton: "a pause share button, so I don't have to stop all streaming before resharing")
    def test_pause_card_input(self):
        a = kastr_rtsp.pause_card_input("screen://monitor/0")
        self.assertEqual(a[:3], ["-f", "lavfi", "-i"])
        self.assertIn("color=c=0x0f2235", a[3])
        self.assertEqual(a[3].count("drawbox="), 2)

    def test_bridge_pause_and_retarget(self):
        b = kastr_rtsp.Bridge.__new__(kastr_rtsp.Bridge)
        b._pubs, b.log = {}, lambda *x: None
        self.assertIsNone(b.pause(1, True))   # no such share

        class P:
            def __init__(self):
                self.feed = type("F", (), {"url": "screen://window/1"})()
                self.paused, self.broadcast, self.why = False, "r/h/op/window.hang", []

            def nudge(self, why):
                self.why.append(why)

            def info(self):
                return {"paused": self.paused}
        pp = P()
        b._pubs[1] = pp
        self.assertEqual(b.pause(1, True), {"paused": True})
        self.assertEqual(b.pause(1, True), {"paused": True})
        self.assertEqual(pp.why, ["pause"])                # the same broadcast restarts once, on the card
        b.pause(1, False)
        self.assertEqual(pp.why, ["pause", "resume"])

    def test_wiring(self):
        r = read("kastr_rtsp.py")
        self.assertIn('"/api/rtsp/pause", "/api/rtsp/retarget",', r)   # loopback only, with publish
        self.assertIn('snd = is_screen(self.feed.url) and self.audio and self.role != "low" and not self.paused', r)
        p = read("moq-watch-lite.html")
        self.assertIn('<button id="pauseShareBtn" class="toggle" type="button" hidden', p)
        self.assertIn('items.push({ value: "spause", label: src.sharePaused ? "Resume sharing" : "Pause sharing" });', p)
        self.assertIn('if ("sharePaused" in m.set) setSharePaused(a, !!m.set.sharePaused);', p)
        self.assertIn("if (e.sharePaused) {   // 0.21.73: paused", p)                     # presenter mode draws the card
        self.assertIn("if (!slots.has(slot.entry.id) || slot.displayStream !== stream) return;", p)   # a swapped-out track is not a stop
        self.assertIn("if (shSwap != null) {   // 0.21.73", p)
        self.assertIn('const r = await nativePost("/api/rtsp/retarget", { id: fid, url });', p)
        self.assertIn('if (slot.goneN >= 2) { log("The share "', p)                          # the bar's Stop no longer leaves a ghost


if __name__ == "__main__":
    unittest.main()
