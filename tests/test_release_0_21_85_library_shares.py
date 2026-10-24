# -*- coding: utf-8 -*-
"""v0.21.85 -- LISTED SHARES in the stream library (Kenton: "Publisher+relay boxes with shared streams should also show up under
streams drop-down."). He chose: every share of a KASTR app on a relay / hub machine is listed automatically; a person's own app
gives each share an "In the stream library" switch, OFF by default. A listed share stays in its room exactly as before (its room
path: tile, remote control, pointers) and is ALSO published at lib/<host>/<op>/<leaf>.hang -- native shares through a pump
and a second moq (LibMirror), the page's own shares through the vendored publish library's library-mirror patch. Every listed
row rides the bridge's one heartbeat per relay; a 0.21.84 relay takes them as they are.

Run: python -m unittest discover -s tests
No real processes: Popen is a fake everywhere a pair would start."""
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_rtsp  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1", "admin": "adm-1", "federation": "fed-1"}
HOST = "yard-0001"
ROOM = "north"
RP = ROOM + "/yard-0001/yard/gate.hang"         # a share's ROOM path
LP = "lib/yard-0001/yard/gate.hang"             # ... and the same stream listed in the library
RELAY = "http://127.0.0.1:4443"
JPEG = bytes((0xFF, 0xD8, 0xFF, 0xE0)) + b"still" * 20


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def ts(pid, pusi=False, fill=0):
    """One 188-byte MPEG-TS packet."""
    return bytes((0x47, (0x40 if pusi else 0) | ((pid >> 8) & 0x1F), pid & 0xFF, 0x10)) + bytes((fill,)) * 184


class FakeWriter:
    def __init__(self, gate=None):
        self.data, self.closed, self.lock, self.gate = bytearray(), False, threading.Lock(), gate

    def write(self, b):
        if self.gate is not None:
            self.gate.wait(10)
        if self.closed:
            raise ValueError("closed")
        with self.lock:
            self.data += bytes(b)
        return len(b)

    def close(self):
        self.closed = True


class FakeReader:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def read(self, n=-1):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True


class FakeProc:
    made = []

    def __init__(self, argv, stdin=None, stdout=None, stderr=None, bufsize=-1, creationflags=0, **kw):
        FakeProc.made.append(self)
        self.pid = 90000 + len(FakeProc.made)
        self.argv, self.kw = list(argv), {"stdin": stdin, "stdout": stdout, "bufsize": bufsize}
        self.rc = None
        self.stdin = FakeWriter()
        self.stdout = FakeReader([])
        self.stderr = io.BytesIO(b"")

    def poll(self):
        return self.rc

    def kill(self):
        if self.rc is None:
            self.rc = -9

    def wait(self, timeout=None):
        if self.rc is None:
            self.rc = 0
        return self.rc


def until(fn, limit=5.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    return fn()


def fake_bridge(lines=None):
    return types.SimpleNamespace(moq="moq", log=(lines.append if lines is not None else (lambda m: None)),
                                 _child_started=lambda *a, **k: None, _child_ended=lambda pid: None, _lib=lambda: {"toks": {}})


class Helpers(unittest.TestCase):
    def test_pat_start_is_packet_aligned(self):
        s = ts(0x100) + ts(0x100) + ts(0, pusi=True) + ts(0x100)
        self.assertEqual(kastr_rtsp.ts_pat_start(s, 0), 2 * 188)
        self.assertIsNone(kastr_rtsp.ts_pat_start(s[:300], 0))           # no PAT in this chunk
        self.assertEqual(kastr_rtsp.ts_pat_start(s[100:], 100), 2 * 188 - 100)   # a chunk that starts mid-packet
        self.assertIsNone(kastr_rtsp.ts_pat_start(ts(0, pusi=False), 0))  # PID 0 without a payload start is not a table start
        self.assertIsNone(kastr_rtsp.ts_pat_start(ts(0, pusi=True)[:2], 0))

    def test_kinds(self):
        k = kastr_rtsp.lib_share_kind
        self.assertEqual(k("screen://monitor/0"), "screen")
        self.assertEqual(k("screen://window/123"), "screen")
        self.assertEqual(k("device://video/Cam"), "camera")
        self.assertEqual(k("rtsp://10.0.0.5/live"), "rtsp")
        self.assertEqual(k("https://example.com/a.mp4"), "media")
        self.assertIn("webcam", kastr_rtsp.LIB_SHARE_KINDS)
        self.assertTrue(set(kastr_rtsp.LIB_SHARE_KINDS) <= set(kr.LIB_KINDS))   # every kind a 0.21.84 relay already takes

    def test_lib_fields_keep_a_camera_switch_never_a_screen_s(self):
        self.assertEqual(kastr_rtsp._lib_fields(types.SimpleNamespace(url="rtsp://x/y", lib_list=True)), {"libList": True})
        self.assertEqual(kastr_rtsp._lib_fields(types.SimpleNamespace(url="screen://monitor/0", lib_list=True)), {})
        self.assertEqual(kastr_rtsp._lib_fields(types.SimpleNamespace(url="rtsp://x/y", lib_list=None)), {})


class Mirror(unittest.TestCase):
    """LibMirror: the library copy of a native share -- starts at a PAT, never in the room's way, follows its key."""

    def setUp(self):
        FakeProc.made = []
        self.p = mock.patch.object(kastr_rtsp.subprocess, "Popen", FakeProc)
        self.p.start()
        self.lines = []
        self.pub = types.SimpleNamespace(bridge=fake_bridge(self.lines), stopping=False, _gen=1, broadcast=RP, relay=RELAY + "/?jwt=room",
                                         libMirror=(LP, RELAY + "/?jwt=LIB1"))

    def tearDown(self):
        self.p.stop()

    def stream(self, n=12):
        out = b""
        for i in range(n):
            out += ts(0, pusi=True) if i in (3, 9) else ts(0x100, fill=i)
        return out

    def test_starts_at_a_pat_and_carries_every_byte_after_it(self):
        lm = kastr_rtsp.LibMirror(self.pub, 1)
        s = self.stream()
        for off in range(0, len(s), 100):
            lm.feed(s[off:off + 100], off)
        (mq,) = FakeProc.made
        self.assertIn("--broadcast", mq.argv)
        self.assertEqual(mq.argv[mq.argv.index("--broadcast") + 1], LP)
        self.assertEqual(mq.argv[mq.argv.index("--connect") + 1], RELAY + "/?jwt=LIB1")
        self.assertEqual((mq.kw["stdin"], mq.kw["bufsize"]), (subprocess.PIPE, 0))
        until(lambda: len(mq.stdin.data) == len(s) - 3 * 188)
        self.assertEqual(bytes(mq.stdin.data), s[3 * 188:])                    # from the first PAT on, every byte
        self.assertTrue(any("listed in the stream library as " + LP in x for x in self.lines))
        lm.close()
        self.assertTrue(until(lambda: mq.stdin.closed))                          # EOF: moq withdraws the path at once

    def test_follows_its_key_and_stops_when_unlisted(self):
        lm = kastr_rtsp.LibMirror(self.pub, 1)
        s = self.stream()
        lm.feed(s, 0)
        self.pub.libMirror = (LP, RELAY + "/?jwt=LIB2")                         # a renewed token: a new copy
        lm.feed(s, len(s))
        self.assertEqual(len(FakeProc.made), 2)
        self.assertEqual(FakeProc.made[1].argv[FakeProc.made[1].argv.index("--connect") + 1], RELAY + "/?jwt=LIB2")
        self.assertTrue(until(lambda: FakeProc.made[0].stdin.closed))
        self.pub.libMirror = None                                                  # switched off
        lm.feed(s, 2 * len(s))
        self.assertTrue(until(lambda: FakeProc.made[1].stdin.closed))
        self.assertIsNone(lm.proc)
        self.pub.libMirror = (LP, RELAY + "/?jwt=LIB2")
        self.pub._gen = 2                                                          # another generation's pump owns it now
        lm.feed(s, 3 * len(s))
        self.assertEqual(len(FakeProc.made), 2)

    def test_a_dead_or_slow_copy_backs_off_and_never_blocks(self):
        lm = kastr_rtsp.LibMirror(self.pub, 1)
        s = self.stream()
        lm.feed(s, 0)
        FakeProc.made[0].rc = 1                                                    # it died at once
        lm.feed(s, len(s))
        self.assertGreater(lm.next_at, time.time())                                # retried after a back-off ...
        self.assertEqual(len(FakeProc.made), 1)
        lm.next_at = 0
        gate = threading.Event()
        with mock.patch.object(kastr_rtsp, "LIB_MIRROR_QMAX", 3 * 188):
            lm.feed(s, 2 * len(s))
            FakeProc.made[1].stdin.gate = gate                                     # its moq stops reading
            t0 = time.time()
            for i in range(6):
                lm.feed(s, (3 + i) * len(s))
            self.assertLess(time.time() - t0, 1.0)                                 # ... the room's pump never waits for it
        gate.set()
        self.assertTrue(any("behind" in x for x in self.lines))
        lm.close()


class Pump(unittest.TestCase):
    def test_every_byte_to_the_room_and_a_copy_to_the_library(self):
        FakeProc.made = []
        with mock.patch.object(kastr_rtsp.subprocess, "Popen", FakeProc):
            feed = kastr_rtsp.Feed(1, "test://pattern")
            pub = kastr_rtsp.Publisher(fake_bridge(), feed, RP, RELAY + "/?jwt=room")
            pub.libMirror = (LP, RELAY + "/?jwt=LIB")
            s = b"".join(ts(0, pusi=True) if i % 5 == 0 else ts(0x100, fill=i) for i in range(20))
            ff = types.SimpleNamespace(stdout=FakeReader([s[i:i + 333] for i in range(0, len(s), 333)]))
            mq = types.SimpleNamespace(stdin=FakeWriter())
            pub._pump(pub._gen, ff, mq)
            self.assertEqual(bytes(mq.stdin.data), s)                             # the room's moq: everything, in order
            self.assertTrue(mq.stdin.closed and ff.stdout.closed)
            (lib,) = FakeProc.made
            until(lambda: len(lib.stdin.data) == len(s))
            self.assertEqual(bytes(lib.stdin.data), s)                            # the stream starts with a PAT here
            self.assertTrue(until(lambda: lib.stdin.closed))
            self.assertEqual(pub._listed_info()["path"], LP)
            self.assertNotIn("jwt", json.dumps(pub._listed_info()))                # never the token


class BridgeSandbox(unittest.TestCase):
    def setUp(self):
        self._saved = [(kastr_rtsp.subprocess, "Popen", kastr_rtsp.subprocess.Popen),
                       (kastr_rtsp.Bridge, "legacy_sweep", kastr_rtsp.Bridge.legacy_sweep),
                       (kastr_rtsp.Bridge, "sweep_orphans", kastr_rtsp.Bridge.sweep_orphans),
                       (kastr_rtsp.Publisher, "start", kastr_rtsp.Publisher.start),
                       (kastr_rtsp, "xs_on_air", kastr_rtsp.xs_on_air),
                       (kastr_rtsp, "_job_assign", kastr_rtsp._job_assign)]

        def no_spawn(*a, **k):
            raise AssertionError("a process was spawned")
        kastr_rtsp.subprocess.Popen = no_spawn
        kastr_rtsp.Bridge.legacy_sweep = lambda self: 0
        kastr_rtsp.Bridge.sweep_orphans = lambda self: 0
        kastr_rtsp.Publisher.start = lambda self: None
        kastr_rtsp.xs_on_air = lambda pub, now=None: True
        kastr_rtsp._job_assign = lambda *a, **k: False
        self.tmp = tempfile.TemporaryDirectory()
        self.lines, self.posts = [], []
        self.cap = True
        self.here = False

    def tearDown(self):
        for obj, name, val in reversed(self._saved):
            setattr(obj, name, val)
        self.tmp.cleanup()

    def post(self, url, body, bearer):
        self.posts.append((url, json.loads(json.dumps(body)), bearer))
        acc = [r["path"] for r in body.get("rows") or []]
        return {"ok": True, "accepted": acc, "refused": {}, "stopped": list(body.get("stop") or [])}, 200

    def bridge(self, room=ROOM):
        b = kastr_rtsp.Bridge(state_dir=self.tmp.name, log=lambda m, *a, **k: self.lines.append(str(m)), host_slug=HOST)
        b.moq = "moq"
        b.lib_cap_fetch = lambda relay: self.cap
        b.lib_mint = lambda relay, access, host: ("token", relay + "/?jwt=LIBTOK", "publisher")
        b._lib_ensure = lambda: None
        b._xs_ensure = lambda: None
        b._xs_post = lambda url, body, bearer: ({"ok": True, "to": body.get("to") or [], "refused": {}}, 200)
        b.relay_here = lambda: self.here
        b.set_session(room, "pub-1", "", RELAY)
        return b

    def share(self, b, path=RP, url="test://pattern", label="Gate"):
        feed = b.add(url)
        b._lib_cap(RELAY)
        b.publish(feed.id, path, RELAY + "/?jwt=room-" + path.split("/", 1)[0], audio=False, keep=True, label=label)
        return feed

    def tick(self, b):
        b._lib()["beatAt"].clear()
        return b.lib_tick(post=self.post)

    def doc(self):
        with open(os.path.join(self.tmp.name, "rtsp-feeds.json"), encoding="utf-8") as f:
            return json.load(f)


class Listed(BridgeSandbox):
    def test_a_relay_machine_lists_its_shares_automatically_and_keeps_the_room_path(self):
        self.here = True
        b = self.bridge()
        f = self.share(b)
        pub = b._pubs[f.id]
        self.assertEqual(pub.broadcast, RP)                                       # listed, NOT moved: the room path stays
        self.assertNotIn("LIBTOK", pub.relay)
        self.assertTrue(b._lib_list_want(pub))
        self.assertTrue(b._lib_list_pump(pub))
        self.tick(b)
        (url, body, bearer), = self.posts
        self.assertEqual((url, bearer), ("http://127.0.0.1:4444/api/library", "LIBTOK"))
        (r,) = body["rows"]
        self.assertEqual((r["path"], r["kind"], r["state"], r["low"]), (LP, "rtsp", "live", False))
        self.assertNotIn("aka", r)                                                # never an alias: boards keep the room path
        self.assertEqual(pub.libMirror, (LP, RELAY + "/?jwt=LIBTOK"))
        self.assertEqual(b._lib()["listed"], {LP: kastr_rtsp._relay_key(RELAY)})
        info = b._lib_info(f)["listed"]
        self.assertEqual((info["want"], info["default"], info["path"], info["status"]), (True, True, LP, "ok"))
        # the room's xshare / room logic is untouched: no listing, no move
        self.assertEqual(f.xs, [])
        self.assertIsNone(f.lib)

    def test_a_person_s_app_lists_a_share_only_when_switched_on(self):
        b = self.bridge()
        f = self.share(b)
        pub = b._pubs[f.id]
        self.assertFalse(b._lib_list_want(pub))
        self.tick(b)
        self.assertEqual(self.posts, [])
        out = b.set_lib_list(f.id, True)
        self.assertEqual((out["ok"], out["repiped"]), (True, False))
        self.assertTrue(out["library"]["listed"]["want"])
        self.assertEqual(self.doc()["feeds"][0]["libList"], True)               # a kept camera remembers it
        self.tick(b)
        self.assertEqual([r["path"] for r in self.posts[-1][1]["rows"]], [LP])
        b.set_lib_list(f.id, False)
        self.assertIsNone(pub.libMirror)                                          # the library copy ends at once
        self.tick(b)
        self.assertEqual((self.posts[-1][1].get("rows"), self.posts[-1][1]["stop"]), ([], [LP]))   # "No longer in the library"
        self.assertEqual(b._lib()["listed"], {})
        with self.assertRaises(ValueError):
            b.set_lib_list(f.id, "yes")

    def test_switching_a_running_pair_on_restarts_it_once_into_the_pump(self):
        b = self.bridge()
        f = self.share(b)
        pub = b._pubs[f.id]
        pub.running, pub.pumped = True, False
        with mock.patch.object(pub, "retoken") as rt:
            out = b.set_lib_list(f.id, True)
        self.assertTrue(out["repiped"])
        rt.assert_called_once_with(pub.relay)
        pub.pumped = True
        with mock.patch.object(pub, "retoken") as rt:
            b.set_lib_list(f.id, True)
            self.tick(b)
        rt.assert_not_called()                                                    # already pumped: the copy just starts

    def test_never_listed(self):
        self.here = True
        b = self.bridge()
        f = self.share(b)
        pub = b._pubs[f.id]
        f.lib = False                                                             # switched OUT of the library (0.21.84 switch)
        self.assertFalse(b._lib_list_want(pub))
        f.lib = None
        f.private = "admin"                                                       # a fleet admin's private capture
        self.assertFalse(b._lib_list_want(pub))
        f.private = None
        with mock.patch.object(kastr_rtsp, "LIBRARY_ENABLED", False):
            self.assertFalse(b._lib_list_want(pub))
        b.lib_master = False
        self.assertFalse(b._lib_list_want(pub))
        b.lib_master = True
        for room in ("main", "box-yard-0001"):                                    # the Lobby, a box's home room
            pub.broadcast = room + "/yard-0001/yard/gate.hang"
            self.assertFalse(b._lib_list_want(pub), room)
        pub.broadcast = LP                                                        # a camera that MOVED is in the library already
        self.assertFalse(b._lib_list_want(pub))
        pub.broadcast = RP
        self.cap = False                                                          # a relay without the library: no row, no copy
        b._lib()["caps"].clear()
        self.tick(b)
        self.assertEqual(self.posts, [])
        self.assertIsNone(pub.libMirror)

    def test_no_room_box_cameras_still_move(self):
        self.here = True
        b = self.bridge("box-yard-0001")
        f = self.share(b, "box-yard-0001/yard-0001/yard/gate.hang")
        self.assertEqual(b._pubs[f.id].broadcast, LP)                             # 0.21.84 unchanged: moved, with its alias
        self.assertFalse(b._lib_list_want(b._pubs[f.id]))
        self.tick(b)
        (r,) = self.posts[-1][1]["rows"]
        self.assertEqual(r["aka"], ["box-yard-0001/yard-0001/yard/gate.hang"])

    def test_states_and_stills(self):
        self.here = True
        b = self.bridge()
        f = self.share(b)
        pub = b._pubs[f.id]
        b.lib_grab = lambda p: JPEG
        b.lib_grab_sync = True
        self.tick(b)
        self.tick(b)
        self.assertEqual(base64.b64decode(self.posts[-1][1]["stills"][LP]), JPEG)
        pub.paused = True
        self.assertIn((LP, "dark", True), b._lib_air(time.time()))               # a paused share: "Not streaming" (and a beat now)
        self.tick(b)
        self.assertEqual(self.posts[-1][1]["rows"][0]["state"], "dark")
        pub.paused = False
        b.unpublish(f.id)                                                         # the share stopped
        self.tick(b)
        self.assertEqual(self.posts[-1][1]["stop"], [LP])

    def test_restore_brings_the_switch_back(self):
        doc = {"room": ROOM, "access": "pub-1", "roomCode": "", "relay": RELAY,
               "feeds": [{"url": "test://pattern", "broadcast": RP, "keep": True, "label": "Gate", "audio": False, "libList": True}]}
        with open(os.path.join(self.tmp.name, "rtsp-feeds.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        b = self.bridge()
        b._load_session()
        self.assertEqual(b.restore(mint=lambda: RELAY + "/?jwt=room-" + ROOM), 1)
        f = list(b._feeds.values())[0]
        self.assertTrue(f.lib_list)
        self.assertEqual(b._pubs[f.id].broadcast, RP)
        self.assertTrue(b._lib_list_want(b._pubs[f.id]))


class PageShares(BridgeSandbox):
    ROW = {"path": "lib/yard-0001/kenton/camera.hang", "label": "Kenton", "kind": "webcam", "state": "live", "audio": True}

    def test_rows_token_stills_and_withdrawal(self):
        b = self.bridge()
        out = b.lib_shares({"shares": [self.ROW, {"path": "lib/other-0002/x/y.hang"}, {"path": "north/yard-0001/kenton/camera.hang"},
                                       dict(self.ROW, path="lib/yard-0001/kenton/camera-low.hang")],
                            "relay": RELAY, "stills": {self.ROW["path"]: base64.b64encode(JPEG).decode(), "lib/other-0002/x/y.hang": "x"}})
        self.assertEqual(out["token"], "LIBTOK")                                  # the page's mirror connection dials with it
        self.assertEqual(len(out["refused"]), 3)                                  # another host's, a room path, a -low copy
        self.assertEqual(out["status"], {self.ROW["path"]: "waiting"})
        self.tick(b)
        (_u, body, bearer), = self.posts
        self.assertEqual(bearer, "LIBTOK")
        self.assertEqual(body["rows"], [{k: self.ROW[k] for k in ("path", "label", "kind", "state", "audio")}])
        self.assertEqual(base64.b64decode(body["stills"][self.ROW["path"]]), JPEG)
        self.assertEqual(b.lib_shares({"shares": [self.ROW], "relay": RELAY})["status"], {self.ROW["path"]: "ok"})
        b.lib_shares({"shares": [], "relay": RELAY})                             # switched off / stopped on the page
        self.tick(b)
        self.assertEqual(self.posts[-1][1]["stop"], [self.ROW["path"]])

    def test_a_page_that_goes_quiet_leaves_the_library(self):
        b = self.bridge()
        b.lib_shares({"shares": [dict(self.ROW, kind="weird", state="paused")], "relay": RELAY})
        self.tick(b)
        r = self.posts[-1][1]["rows"][0]
        self.assertEqual((r["kind"], r["state"]), ("other", "live"))             # enums enforced here too
        b._lib()["shares"][self.ROW["path"]]["at"] -= kastr_rtsp.LIB_SHARE_TTL_S + 1
        self.tick(b)
        self.assertEqual(self.posts[-1][1]["stop"], [self.ROW["path"]])

    def test_one_heartbeat_for_native_and_page_rows(self):
        self.here = True
        b = self.bridge()
        self.share(b)
        b.lib_shares({"shares": [self.ROW], "relay": RELAY})
        self.tick(b)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(sorted(r["path"] for r in self.posts[0][1]["rows"]), [self.ROW["path"], LP])
        with self.assertRaises(ValueError):
            b.lib_shares({"shares": [self.ROW], "relay": ""})

    def test_loopback_api(self):
        self.here = True
        b = self.bridge()
        f = self.share(b)

        class H:
            def __init__(self, path, body=None, command="POST"):
                raw = json.dumps(body).encode() if body is not None else b""
                self.path, self.command = path, command
                self.headers = {"Content-Length": str(len(raw)), "Host": "127.0.0.1:8000"}
                self.client_address = ("127.0.0.1", 50000)
                self.rfile, self.wfile = io.BytesIO(raw), io.BytesIO()

            def send_response(self, code):
                self.code = code

            def send_header(self, k, v):
                pass

            def end_headers(self):
                pass
        with mock.patch.object(kr, "is_local", lambda h: True):
            h = H("/api/rtsp/library", None, "GET")
            kastr_rtsp.handle_api(h, b, "/api/rtsp/library")
            d = json.loads(h.wfile.getvalue())
            self.assertTrue(d["relayHere"])
            self.assertTrue(d["feeds"][0]["library"]["listed"]["want"])
            h = H("/api/rtsp/library", {"id": f.id, "list": False})
            kastr_rtsp.handle_api(h, b, "/api/rtsp/library")
            self.assertEqual(h.code, 200)
            self.assertFalse(json.loads(h.wfile.getvalue())["library"]["listed"]["want"])
            h = H("/api/rtsp/library", {"shares": [self.ROW], "relay": RELAY})
            kastr_rtsp.handle_api(h, b, "/api/rtsp/library")
            self.assertEqual((h.code, json.loads(h.wfile.getvalue())["token"]), (200, "LIBTOK"))


class PumpMode(BridgeSandbox):
    """Publisher.start: a listed share's moq reads from a pump (stdin PIPE, unbuffered); any other pair keeps the direct pipe."""

    def run_start(self, here):
        self.here = here
        FakeProc.made = []
        kastr_rtsp.subprocess.Popen = FakeProc
        kastr_rtsp.Publisher.start = self._saved[3][2]
        b = self.bridge()
        b.ffmpeg = "ffmpeg"
        with mock.patch.object(kastr_rtsp.Publisher, "_args", lambda self: (["ffmpeg"], ["moq", "--broadcast", self.broadcast])):
            f = self.share(b)
            pub = b._pubs[f.id]
            ff, mq = FakeProc.made[:2]
            out = (pub.pumped, mq.kw["stdin"], mq.kw["bufsize"], ff.stdout)
            pub.stop()
        return out

    def test_pump_only_for_a_listed_share(self):
        pumped, stdin, bufsize, _ffout = self.run_start(True)
        self.assertEqual((pumped, stdin, bufsize), (True, subprocess.PIPE, 0))
        pumped, stdin, bufsize, ffout = self.run_start(False)
        self.assertFalse(pumped)
        self.assertIs(stdin, ffout)                                               # the 0.9.1 direct pipe, untouched
        self.assertEqual(bufsize, -1)


class OnDemand(unittest.TestCase):
    def test_a_listed_sleeping_share_wakes_from_the_library(self):
        b = kastr_rtsp.Bridge.__new__(kastr_rtsp.Bridge)
        b.web_base_for = lambda key: "http://127.0.0.1:1"
        posts = []

        def post(url, body):
            posts.append(body)
            return {"wanted": {LP: 1.0}} if body["token"] == "LIBTOK" else {"wanted": {}}
        woke = []
        p = types.SimpleNamespace(broadcast=RP, relay=RELAY + "/?jwt=ROOMTOK", label="Gate", running=False, lowPub=None, sleepy=True,
                                  wantedAt=None, standby=True, wokeAt=0, libMirror=(LP, RELAY + "/?jwt=LIBTOK"),
                                  wake=lambda why: woke.append(why), sleep=lambda why: None)
        b.od_tick([p], post=post)
        self.assertEqual(sorted((x["token"], x["feeds"][0]["broadcast"]) for x in posts), [("LIBTOK", LP), ("ROOMTOK", RP)])
        self.assertEqual(woke, ["viewer demand"])                                 # a viewer in the library woke it
        import kastr_serve as ks
        with mock.patch.dict(ks.ONDEMAND, {}, clear=True):                        # the relay host takes lib/ under a library token
            ks.ondemand_sync("lib", HOST, [{"broadcast": LP, "idle": True}])
            self.assertIn(LP, ks.ONDEMAND)


class Relay(unittest.TestCase):
    """A 0.21.84 relay already takes listed rows (kinds screen / webcam / media) -- hidden, guests, boards as for cameras."""

    def setUp(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(**CODES)
        self.s = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)

    def tearDown(self):
        self.s.close()

    def member(self, room, code="pub-1", host="viewer-cd34"):
        r, c = self.s.token({"room": room, "code": code, "host": host}, "10.0.0.1")
        assert c == 200, r
        return "Bearer " + r["tokens"]["member"]

    def test_listed_rows_guests_hide_and_remote_control(self):
        s = self.s
        r, c = s.token({"library": True, "code": "pub-1", "host": "kenton-ab12"}, "10.0.0.9")
        self.assertEqual(c, 200, r)
        tok = "Bearer " + r["tokens"]["member"]
        rows = [{"path": "lib/kenton-ab12/kenton/screen.hang", "label": "Screen 1", "kind": "screen", "state": "live"},
                {"path": "lib/kenton-ab12/kenton/camera.hang", "label": "Kenton", "kind": "webcam", "state": "live", "audio": True},
                {"path": "lib/kenton-ab12/kenton/media-clip.hang", "label": "Clip", "kind": "media", "state": "dark"}]
        d, c = s.library_post({"rows": rows, "box": "kenton"}, tok, "10.0.0.9")
        self.assertEqual((c, sorted(d["accepted"])), (200, sorted(x["path"] for x in rows)))
        got = {x["path"]: x for x in s.library_get({}, self.member("yard", "view-1"), None, "10.0.0.1")[0]["rows"]}
        self.assertEqual(got["lib/kenton-ab12/kenton/screen.hang"]["kind"], "screen")
        self.assertEqual(got["lib/kenton-ab12/kenton/camera.hang"]["kind"], "webcam")
        self.assertEqual(got["lib/kenton-ab12/kenton/media-clip.hang"]["state"], "dark")
        # a room adds one (no proof token), a guest of that room sees only it
        d, c = s.board_post({"room": "yard", "op": "pin", "path": "lib/kenton-ab12/kenton/screen.hang", "from": "lib", "label": "Screen 1"}, self.member("yard"))
        self.assertEqual(c, 200, d)
        guest = kr.verify_token(self.member("yard")[7:], s.key)
        gtok = "Bearer " + kr._mint(s.key, dict(guest, inv="ab12cd34"))
        self.assertEqual([x["path"] for x in s.library_get({}, gtok, None, "10.0.0.1")[0]["rows"]], ["lib/kenton-ab12/kenton/screen.hang"])
        # an admin hides it fleet-wide
        s.library_admin_api({"op": "hide", "path": "lib/kenton-ab12/kenton/camera.hang"}, self.member("yard", "adm-1"), "10.0.0.1")
        self.assertNotIn("lib/kenton-ab12/kenton/camera.hang", [x["path"] for x in s.library_get({}, self.member("yard"), None, "10.0.0.1")[0]["rows"]])
        # remote control is never asked from the library: the share is not in the asker's room
        claims = kr.verify_token(self.member("yard", host="asker-ef56")[7:], s.key)
        d, c = s.rc_send({"kind": "ask", "to": "kenton-ab12", "share": "lib/kenton-ab12/kenton/screen.hang", "id": "abcdef0123"},
                         claims, "yard", "asker-ef56")
        self.assertEqual(c, 403, d)
        self.assertIn("not in your room", d["error"])


class Sources(unittest.TestCase):
    def test_vendor_mirror_patch(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("vendor_moq", os.path.join(HERE, "vendor-moq.py"))
        vm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vm)
        self.assertIn("library-mirror", [p["id"] for p in vm.PATCHES])
        enc = _read(os.path.join("assets", "vendor", "esm", "@moq", "publish@0.5.2", "es2022", "encoder-CjcsUSCu.mjs"))
        for frag in ("/* KASTR-PATCH: library-mirror */mirrorOrigin:j(t?.mirrorOrigin),mirrorName:j(t?.mirrorName)",
                     "kastrMirror(t){", "static KastrTee=class{", "static KastrTeeGroup=class{", "this.#i.run(e=>this.kastrMirror(e))",
                     "U=f.get(h.used)||!!(M&&f.get(M.used))"):
            self.assertIn(frag, enc)
        self.assertEqual(enc.count("close(){this.#i.close()}},su=on({Renderer:"), 0)

    def test_page(self):
        s = _read("moq-watch-lite.html")
        for frag in ("window.__libShares = {", "function libSharePickerRow(path, label)", "async function libShareToggle(path, label, on)",
                     'items.push({ value: "libsh"', 'v === "libsh"', "function libTwinHere(path)", "async boxList(id, on)",
                     '"libpub=1&jwt="', "bc.in.mirrorName.set(", "on: libOn,", 'const libKindOf = (k) => (k === "rtsp" || k === "webcam" ? "camera" : k);',
                     'tag("Shared in this room"', 'body: JSON.stringify({ shares: rows, relay: urlInput.value.trim(), stills, token: rows.length > 0 })'):
            self.assertIn(frag, s)
        # lab-proven robustness: a slow answer never takes my shares out, a timed-out post goes again at once, a closing
        # window withdraws its rows, a webcam is listed by its person's name, a presentation's still is its slide
        for frag in ('else if (r.status === 404) LIBSH.here = null;', 'signal: AbortSignal.timeout(20000)', 'LIBSH.sig = ""; LIBSH.postAt = 0;',
                     'navigator.sendBeacon?.("/api/rtsp/library"', 'it.kind === "webcam" && operator ? operator', "it.e.presCanvas ||",
                     '!(it.e.kind === "camera" && it.e.videoPaused)'):
            self.assertIn(frag, s)
        self.assertEqual(kastr_rtsp.LIB_SHARE_TTL_S, 180)
        # remote control is offered only on a tile of MY room (a library tile never)
        i = s.index("function rcMenuItem(name)")
        self.assertIn('!String(name).startsWith(CHANNEL + "/")', s[i:i + 400])
        # the page never prints or stores the library publisher token
        j = s.index("const LIBSH = {")
        seg = s[j:s.index("window.__publisher = {", j)]
        self.assertNotIn("localStorage", seg)
        self.assertNotIn("console.", seg)
        self.assertIn("never the token", seg)

    def test_serve_and_rtsp(self):
        self.assertIn("bridge.relay_here = lambda rs=relay_srv: bool(rs.running())", _read("kastr_serve.py"))
        r = _read("kastr_rtsp.py")
        self.assertIn('elif "id" in payload and "list" in payload:', r)
        self.assertIn('elif "shares" in payload:', r)
        self.assertNotIn("libsh", _read("kastr_relay.py"))                         # no relay change: a 0.21.84 relay takes the rows


if __name__ == "__main__":
    unittest.main()
