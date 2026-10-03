"""0.21.16: the box's own-RTSP switch (kastr_rtsp.Bridge.suspended, POST /api/rtsp/suspend).

Run: python -m unittest discover -s tests   (build.py's exact invocation, before every build)

Off = every camera pair, low copy and owner monitor this box runs stops, and NOTHING is forgotten: the publishers stay
recorded, rtsp-feeds.json keeps the feeds and carries `suspended: true`, a relaunch comes back off, a publish request
meanwhile is recorded but not started. Every restart path (ladder, park tick, renew, retoken, nudge, wake) lands on the
start() gate. No network, no processes: subprocess.Popen raises if anything tries to spawn, the orphan sweeps (which
enumerate and may kill other processes) are stubbed, and Publisher.start is replaced wherever a pair would start.
"""
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_rtsp  # noqa: E402
import kastr_relay  # noqa: E402

RELAY = "http://127.0.0.1:4443"


def feed_stub():
    return types.SimpleNamespace(id=1, url="test://pattern", source_url="test://pattern", sar=None, width=None,
                                 height=None, fullrange=False, h264=None, hevc=None)


def quiet_bridge(lines=None):
    sink = lines if lines is not None else []
    return types.SimpleNamespace(log=lambda m, *a, **k: sink.append(str(m)), _child_ended=lambda pid: None)


def no_spawn(*a, **k):
    raise AssertionError("a process was spawned: %r" % (a[:1],))


class Sandbox(unittest.TestCase):
    """Popen refuses, the sweeps are inert, ONDEMAND_ENABLED is restored."""

    def setUp(self):
        self._saved = [(kastr_rtsp.subprocess, "Popen", kastr_rtsp.subprocess.Popen),
                       (kastr_rtsp.Bridge, "legacy_sweep", kastr_rtsp.Bridge.legacy_sweep),
                       (kastr_rtsp.Bridge, "sweep_orphans", kastr_rtsp.Bridge.sweep_orphans),
                       (kastr_rtsp, "ONDEMAND_ENABLED", kastr_rtsp.ONDEMAND_ENABLED)]
        kastr_rtsp.subprocess.Popen = no_spawn
        kastr_rtsp.Bridge.legacy_sweep = lambda self: 0
        kastr_rtsp.Bridge.sweep_orphans = lambda self: 0
        kastr_rtsp.ONDEMAND_ENABLED = False
        self.tmp = tempfile.TemporaryDirectory()
        self.lines = []

    def tearDown(self):
        for obj, name, val in reversed(self._saved):
            setattr(obj, name, val)
        self.tmp.cleanup()

    def bridge(self):
        b = kastr_rtsp.Bridge(state_dir=self.tmp.name, log=lambda m, *a, **k: self.lines.append(str(m)))
        b.moq = "moq"                     # publish() refuses without a moq binary; nothing is spawned
        return b

    def record_starts(self):
        started = []
        saved = kastr_rtsp.Publisher.start
        # the real start() gate (test_start_is_refused_while_suspended proves it), then a record instead of a spawn
        kastr_rtsp.Publisher.start = lambda self: (None if (self.stopping or self.standby or self.suspended)
                                                   else started.append(self.broadcast))
        self._saved.append((kastr_rtsp.Publisher, "start", saved))
        return started

    def feeds_doc(self):
        with open(os.path.join(self.tmp.name, "rtsp-feeds.json"), encoding="utf-8") as f:
            return json.load(f)


class PublisherGate(Sandbox):
    def test_start_is_refused_while_suspended(self):
        p = kastr_rtsp.Publisher(quiet_bridge(), feed_stub(), "r/h/o/cam.hang", RELAY)
        p.suspended = True
        gen = p._gen
        p.start()                                       # Popen would raise
        self.assertFalse(p.running)
        self.assertEqual(p._gen, gen)
        p.nudge("viewer")
        p.nudge("no-echo")
        self.assertEqual(p.nudges, {"viewer": 0, "noEcho": 0, "api": 0, "refused": 0})
        self.assertIsNone(p.lastNudgeWhy)
        self.assertEqual(p.restarts, 0)
        p.retoken(RELAY + "/?jwt=fresh")                # the relay URL is kept current, nothing starts
        self.assertIn("jwt=fresh", p.relay)
        self.assertFalse(p.running)

    def test_suspend_cancels_timers_and_keeps_settings(self):
        p = kastr_rtsp.Publisher(quiet_bridge(), feed_stub(), "r/h/o/cam.hang", RELAY, audio=False,
                                 passthrough=True, keep=True, label="Front door")
        t1, t2 = threading.Timer(60, lambda: None), threading.Timer(60, lambda: None)
        t1.daemon = t2.daemon = True
        t1.start(); t2.start()
        p._timer, p._renew = t1, t2
        p.running, p.parked, p.procs = True, True, ()
        self.assertTrue(p.suspend("test"))              # it was running
        self.assertTrue(t1.finished.is_set() and t2.finished.is_set())   # cancelled
        self.assertIsNone(p._timer)
        self.assertIsNone(p._renew)
        self.assertTrue(p.suspended)
        self.assertFalse(p.running)
        self.assertFalse(p.parked)
        self.assertFalse(p.stopping)                    # not a stop: the record lives on
        self.assertEqual((p.keep, p.audio, p.passthrough, p.label), (True, False, True, "Front door"))
        self.assertTrue(p.info()["suspended"])

    def test_resume_starts_plain_pair_and_restands_ondemand(self):
        started = self.record_starts()
        p = kastr_rtsp.Publisher(quiet_bridge(), feed_stub(), "r/h/o/cam.hang", RELAY)
        p.suspend()
        self.assertTrue(p.resume())
        self.assertEqual(started, ["r/h/o/cam.hang"])
        self.assertFalse(p.suspended)
        self.assertFalse(p.resume())                    # idempotent: not suspended -> nothing
        kastr_rtsp.ONDEMAND_ENABLED = True
        q = kastr_rtsp.Publisher(quiet_bridge(), feed_stub(), "r/h/o/od.hang", RELAY, ondemand=True)
        self.assertTrue(q.standby)
        q.suspend()
        self.assertTrue(q.resume())
        self.assertEqual(started, ["r/h/o/cam.hang"])   # an on-demand pair goes back to standby, not on air
        self.assertTrue(q.standby)

    def test_wake_refused_while_suspended(self):
        kastr_rtsp.ONDEMAND_ENABLED = True
        lines = []
        p = kastr_rtsp.Publisher(quiet_bridge(lines), feed_stub(), "r/h/o/od.hang", RELAY, ondemand=True)
        p.suspended = True
        self.assertFalse(p.wake("viewer demand"))
        self.assertTrue(p.standby)                      # kept for resume()
        self.assertFalse(any("woken" in ln for ln in lines))

    def test_park_tick_silent_while_suspended(self):
        calls = []
        p = kastr_rtsp.Publisher(quiet_bridge(), feed_stub(), "r/h/o/cam.hang", RELAY,
                                 minter=lambda: calls.append(1) or RELAY + "/?jwt=x")
        p.parked, p.suspended = True, True
        p._mintAt = 0
        p._bareAt = 0                                   # a bare retry would be due too
        p._park_tick()
        self.assertIsNone(p._timer)                     # no 15 s tick queued
        self.assertEqual(calls, [])                     # the minter was not asked
        self.assertEqual(p.restarts, 0)

    def test_no_renewal_timer_while_suspended(self):
        p = kastr_rtsp.Publisher(quiet_bridge(), feed_stub(), "r/h/o/cam.hang", RELAY, minter=lambda: None)
        p.tokenExp = time.time() + 3600
        p.suspended = True
        p._arm_renew()
        self.assertIsNone(p._renew)


class BridgeSwitch(Sandbox):
    def test_bridge_suspend_persists_and_reloads(self):
        started = self.record_starts()
        b = self.bridge()
        feed = b.add("test://pattern")
        b.publish(feed.id, "r/h/o/cam.hang", RELAY, audio=False, keep=True)
        self.assertEqual(started, ["r/h/o/cam.hang"])
        res = b.suspend("t")
        self.assertEqual((res["ok"], res["suspended"], res["records"]), (True, True, 1))
        self.assertTrue(b.suspended)
        self.assertTrue(b.list()[0]["publish"]["suspended"])
        self.assertIn(feed.id, b._pubs)                  # the record is kept ...
        recs = b._feed_records()
        self.assertEqual(len(recs), 1)
        self.assertEqual((recs[0]["url"], recs[0]["broadcast"]), ("test://pattern", "r/h/o/cam.hang"))
        doc = self.feeds_doc()
        self.assertIs(doc["suspended"], True)            # ... and so is the switch
        self.assertEqual(len(doc["feeds"]), 1)
        self.assertTrue(any("publishing SUSPENDED by t" in ln for ln in self.lines))
        self.assertEqual(b.suspend("t")["stopped"], 0)   # idempotent
        b2 = self.bridge()                               # a relaunch
        self.assertTrue(b2.suspended)
        self.assertTrue(any("SUSPENDED on this box" in ln for ln in self.lines))

    def test_publish_while_suspended_is_recorded_not_started(self):
        started = self.record_starts()
        b = self.bridge()
        f1 = b.add("test://pattern")
        b.publish(f1.id, "r/h/o/cam.hang", RELAY, audio=False, keep=True)
        b.suspend("t")
        f2 = b.add("test://pattern")                     # two feeds may share a URL (test patterns)
        p2 = b.publish(f2.id, "r/h/o/cam2.hang", RELAY, audio=False, keep=True)
        self.assertEqual(started, ["r/h/o/cam.hang"])    # recorded, not started
        self.assertEqual(len(b._pubs), 2)
        self.assertTrue(p2.info()["suspended"])
        again = b.publish(f1.id, "r/h/o/cam.hang", RELAY + "/?jwt=fresh", audio=False, keep=True)   # a token re-post
        self.assertIs(again, b._pubs[f1.id])
        self.assertIn("jwt=fresh", again.relay)          # the record carries the live token for the resume
        self.assertEqual(started, ["r/h/o/cam.hang"])
        res = b.resume("t")
        self.assertEqual((res["suspended"], res["started"], res["records"]), (False, 2, 2))
        self.assertEqual(sorted(started), ["r/h/o/cam.hang", "r/h/o/cam.hang", "r/h/o/cam2.hang"])
        self.assertIs(self.feeds_doc()["suspended"], False)
        self.assertTrue(any("publishing RESUMED by t -- 2 of 2" in ln for ln in self.lines))
        self.assertEqual(b.resume("t")["started"], 0)    # idempotent

    def test_restore_while_suspended_records(self):
        started = self.record_starts()
        with open(os.path.join(self.tmp.name, "rtsp-feeds.json"), "w", encoding="utf-8") as f:
            json.dump({"room": "r", "relay": RELAY, "suspended": True,
                       "feeds": [{"url": "test://pattern", "broadcast": "r/h/o/cam.hang", "keep": True}]}, f)
        b = self.bridge()
        self.assertTrue(b.suspended)
        n = b.restore(mint=lambda: RELAY, log=lambda m: self.lines.append(str(m)))
        self.assertEqual(n, 1)
        self.assertEqual(started, [])
        pub = list(b._pubs.values())[0]
        self.assertTrue(pub.suspended)
        self.assertTrue(any("recorded (publishing suspended) 1 persisted feed" in ln for ln in self.lines))
        self.assertIs(self.feeds_doc()["suspended"], True)
        self.assertTrue(b.session_public()["suspended"])

    def test_bridge_nudge_silent_while_suspended(self):
        self.record_starts()
        b = self.bridge()
        feed = b.add("test://pattern")
        p = b.publish(feed.id, "r/h/o/cam.hang", RELAY, audio=False, keep=True)
        b.suspend("t")
        before = len(self.lines)
        self.assertFalse(b.nudge(feed.id, "viewer"))
        self.assertFalse(any(ln.startswith("rtsp nudge") for ln in self.lines[before:]))
        self.assertEqual(p.nudges["viewer"], 0)

    def test_unpublish_still_forgets_on_purpose(self):
        self.record_starts()
        b = self.bridge()
        feed = b.add("test://pattern")
        b.publish(feed.id, "r/h/o/cam.hang", RELAY, audio=False, keep=True)
        b.suspend("t")
        self.assertTrue(b.unpublish(feed.id))           # the operator may still close a feed while off
        self.assertEqual(self.feeds_doc()["feeds"], [])
        self.assertIs(self.feeds_doc()["suspended"], True)


class FakeHandler:
    def __init__(self, path, body=None, command="POST"):
        raw = json.dumps(body).encode() if body is not None else b""
        self.path = path
        self.command = command
        self.headers = {"Content-Length": str(len(raw)), "Host": "127.0.0.1:8000"}
        self.client_address = ("127.0.0.1", 50000)
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.code = None
        self.errors = []

    def send_response(self, code):
        self.code = code

    def send_header(self, k, v):
        pass

    def end_headers(self):
        pass

    def send_error(self, code, msg=""):
        self.errors.append((code, msg))

    def body(self):
        return json.loads(self.wfile.getvalue().decode() or "null")


class Endpoints(Sandbox):
    def setUp(self):
        super().setUp()
        self._saved.append((kastr_relay, "is_local", kastr_relay.is_local))
        kastr_relay.is_local = lambda h: True           # from_loopback() looks it up per request

    def test_handle_api_suspend(self):
        self.record_starts()
        b = self.bridge()
        feed = b.add("test://pattern")
        b.publish(feed.id, "r/h/o/cam.hang", RELAY, audio=False, keep=True)
        h = FakeHandler("/api/rtsp/suspend", {"suspend": True, "who": "page\n<x>"})
        self.assertTrue(kastr_rtsp.handle_api(h, b, "/api/rtsp/suspend"))
        self.assertEqual(h.code, 200)
        self.assertIs(h.body()["suspended"], True)
        self.assertTrue(b.suspended)
        self.assertTrue(any("SUSPENDED by pagex" in ln for ln in self.lines))   # `who` sanitised for launch.log
        h = FakeHandler("/api/rtsp/suspend", {})
        kastr_rtsp.handle_api(h, b, "/api/rtsp/suspend")
        self.assertEqual(h.body(), {"ok": True, "suspended": True})          # read-back
        h = FakeHandler("/api/rtsp/list", command="GET")
        kastr_rtsp.handle_api(h, b, "/api/rtsp/list")
        d = h.body()
        self.assertIs(d["suspended"], True)
        self.assertTrue(d["feeds"][0]["publish"]["suspended"])
        h = FakeHandler("/api/rtsp/persist", command="GET")
        kastr_rtsp.handle_api(h, b, "/api/rtsp/persist")
        self.assertIs(h.body()["suspended"], True)
        h = FakeHandler("/api/rtsp/suspend", {"suspend": False})
        kastr_rtsp.handle_api(h, b, "/api/rtsp/suspend")
        self.assertIs(h.body()["suspended"], False)
        self.assertFalse(b.suspended)

    def test_suspend_is_loopback_only(self):
        b = self.bridge()
        kastr_relay.is_local = lambda h: False
        h = FakeHandler("/api/rtsp/suspend", {"suspend": True})
        kastr_rtsp.handle_api(h, b, "/api/rtsp/suspend")
        self.assertEqual(h.code, 403)
        self.assertFalse(b.suspended)

    def test_handle_stream_503_while_suspended(self):
        b = self.bridge()
        feed = b.add("test://pattern")                  # the 503 gate sits after the feed lookup (404 first)
        spawned = []
        b.spawn = lambda *a, **k: spawned.append(a) or no_spawn()
        b.suspend("t")
        h = FakeHandler("/rtsp/%d" % feed.id, command="GET")
        self.assertTrue(kastr_rtsp.handle_stream(h, b, "/rtsp/%d" % feed.id))
        self.assertEqual([c for c, _m in h.errors], [503])
        self.assertEqual(spawned, [])
        h = FakeHandler("/rtsp/99", command="GET")
        kastr_rtsp.handle_stream(h, b, "/rtsp/99")
        self.assertEqual([c for c, _m in h.errors], [404])


if __name__ == "__main__":
    unittest.main()
