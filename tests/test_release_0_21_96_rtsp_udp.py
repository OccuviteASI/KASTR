"""0.21.96 -- an rtsp:// camera's Transport (Auto / TCP / UDP), and what UDP lost.

Field: a Convoy Tech IP1910IR plays in VLC (RTP over UDP) but KASTR forced `-rtsp_transport tcp` and the row read
"failed -- no video from the bridge ... retrying". Kenton: add a UDP fallback, and show how much UDP drops on a drive.

  argv      every ffmpeg that reads the camera takes input_args(..., transport=...): udp -> `-rtsp_transport udp
            -buffer_size 4194304` (+ -min_port/-max_port from KASTR_RTSP_UDP_PORTS); rtsps:// is TCP whatever is asked;
            http(s), devices, the test pattern untouched; -timeout before -i; never -rw_timeout (0.13.1 killed every camera)
  Auto      TCP first; no picture over TCP (SETUP refused -- 461 -- or silent) -> one UDP probe; UDP's picture wins for the
            rest of the run (AUTO_PICKS), the probe cache is keyed (url, transport)
  kept      Bridge._transports -> rtsp-feeds.json `transports` [{url, mode}] (url sealed like feeds/*/url); a new Bridge
            restores it and add() applies it; Auto is not stored
  loss      "RTP: missed N packets", "max delay reached", "bad cseq", MJPEG "dropping frame", decoder errors -- counted per
            reader over the run and the last 60 s; kept out of the error tail
  info      Feed.info() / Bridge.diag_feeds() (/api/diag `_rtsp`) / __publisher.state() carry transport + loss
  page      the row's "Transport:" select (disabled for rtsps), the transport line, faultText says when TCP was refused

No camera, no network beyond 127.0.0.1 (one optional real-ffmpeg argv check against a closed local port)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_rtsp as kr  # noqa: E402
import kastr_secret as ks  # noqa: E402


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


PAGE = _read("moq-watch-lite.html")
SERVE = _read("kastr_serve.py")
RTSP_SRC = _read("kastr_rtsp.py")

CAM = "rtsp://192.0.2.10:554/stream1"
CAMPW = "camLabPw-7Hq"
CAM_CREDS = "rtsp://admin:%s@192.0.2.11:554/ch0" % CAMPW
SECURE = "rtsps://192.0.2.12:7441/abc"


def _js_fn(p, head):
    i = p.index(head)
    return p[i:p.index("\n  }\n", i) + 4]


def _chrome():
    for p in (os.environ.get("KASTR_TEST_CHROME") or "", os.path.join(HERE, "dist", "windows", "browser", "chrome.exe")):
        if p and os.path.isfile(p):
            return p
    d = HERE   # a git worktree: the main checkout's bundled browser
    for _ in range(4):
        d = os.path.dirname(d)
        c = os.path.join(d, "dist", "windows", "browser", "chrome.exe")
        if os.path.isfile(c):
            return c
    return None


def _ffmpeg():
    try:
        ff = kr.find_ffmpeg()
    except Exception:
        ff = None
    if ff and os.path.exists(ff):
        return ff
    d = HERE
    for _ in range(4):
        d = os.path.dirname(d)
        c = os.path.join(d, "bin", "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def F(url, transport="auto"):
    """A feed as the bridge makes one, with its Transport set."""
    f = kr.Feed(1, url)
    f.transport = transport
    return f


def _opt(args, name):
    return args[args.index(name) + 1] if name in args else None


class Argv(unittest.TestCase):
    def tearDown(self):
        kr.AUTO_PICKS.clear()

    def test_default_and_tcp_are_tcp(self):
        for tr in (None, "tcp", "auto"):
            a = kr.input_args(CAM, transport=tr)
            self.assertEqual(_opt(a, "-rtsp_transport"), "tcp", tr)
            self.assertNotIn("-buffer_size", a)

    def test_udp(self):
        with mock.patch.dict(os.environ, {"KASTR_RTSP_UDP_PORTS": ""}):
            a = kr.input_args(CAM, transport="udp")
        self.assertEqual(_opt(a, "-rtsp_transport"), "udp")
        self.assertEqual(_opt(a, "-buffer_size"), str(4 * 1024 * 1024))
        self.assertNotIn("-min_port", a)
        self.assertEqual(a.count("-rtsp_transport"), 1)
        self.assertIn("-timeout", a)                       # a silent camera still ends
        self.assertLess(a.index("-timeout"), a.index("-i"))
        self.assertEqual(a[a.index("-i") + 1], CAM)
        self.assertNotIn("-rw_timeout", a)                 # 0.13.1: killed every camera
        self.assertNotIn("-tls_verify", a)

    def test_udp_ports_env(self):
        with mock.patch.dict(os.environ, {"KASTR_RTSP_UDP_PORTS": "40000-40999"}):
            a = kr.input_args(CAM, transport="udp")
        self.assertEqual((_opt(a, "-min_port"), _opt(a, "-max_port")), ("40000", "40999"))
        for bad in ("40999-40000", "80-90", "abc", "40000"):
            with mock.patch.dict(os.environ, {"KASTR_RTSP_UDP_PORTS": bad}):
                self.assertNotIn("-min_port", kr.input_args(CAM, transport="udp"), bad)

    def test_rtsps_stays_tcp(self):
        a = kr.input_args(SECURE, transport="udp")
        self.assertEqual(_opt(a, "-rtsp_transport"), "tcp")
        self.assertIn("-tls_verify", a)
        self.assertNotIn("-buffer_size", a)

    def test_other_sources_untouched(self):
        for url in ("http://192.0.2.5/a.mp4", "https://192.0.2.5/live.m3u8", kr.TEST_URL):
            self.assertEqual(kr.input_args(url, transport="udp"), kr.input_args(url), url)
            self.assertNotIn("-rtsp_transport", kr.input_args(url, transport="udp"))

    def test_monitor_role_too(self):
        a = kr.input_args(CAM, role="mon", transport="udp")
        self.assertEqual(_opt(a, "-rtsp_transport"), "udp")

    def test_every_camera_reader_passes_its_transport(self):
        # the publisher, the monitor (both input_args calls in spawn), the library grab and the probe
        self.assertIn("input_args(url, transport=transport)", RTSP_SRC)                 # _probe_once
        self.assertIn("transport=feed_transport(feed)", RTSP_SRC)                       # _lib_grab
        self.assertGreaterEqual(RTSP_SRC.count("transport=tr"), 3)                      # Publisher._args + spawn x2
        self.assertIn('RTSP_LOGLEVEL if tr else "error"', RTSP_SRC)
        self.assertNotIn('"-rw_timeout"', RTSP_SRC)

    def test_bundled_ffmpeg_accepts_the_udp_options(self):
        ff = _ffmpeg()
        if not ff:
            self.skipTest("no bundled ffmpeg")
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                           # a closed local port: "Connection refused", fast
        with mock.patch.dict(os.environ, {"KASTR_RTSP_UDP_PORTS": "40000-40999"}):
            a = kr.input_args("rtsp://127.0.0.1:%d/x" % port, transport="udp")
        a[a.index("-timeout") + 1] = "2000000"
        r = subprocess.run([ff, "-hide_banner", "-loglevel", kr.RTSP_LOGLEVEL] + a + ["-f", "null", "-"],
                           capture_output=True, text=True, errors="replace", timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        err = r.stderr
        self.assertNotIn("Unrecognized option", err)
        self.assertNotIn("Option not found", err)
        self.assertNotIn("Error splitting the argument list", err)
        self.assertIn("[error]", err)                       # level tags: what rtsp_line splits


class Transport(unittest.TestCase):
    def tearDown(self):
        kr.AUTO_PICKS.clear()

    def test_feed_transport(self):
        self.assertEqual(kr.feed_transport(F(CAM)), "tcp")
        self.assertEqual(kr.feed_transport(F(CAM, "udp")), "udp")
        self.assertEqual(kr.feed_transport(F(CAM, "tcp")), "tcp")
        self.assertEqual(kr.feed_transport(F(CAM, "nonsense")), "tcp")
        self.assertEqual(kr.feed_transport(F(SECURE, "udp")), "tcp")
        for url in ("http://192.0.2.5/a.mp4", kr.TEST_URL, "screen:0"):
            self.assertIsNone(kr.feed_transport(F(url, "udp")), url)
        kr.AUTO_PICKS[CAM] = {"transport": "udp", "why": "the camera refused TCP"}
        self.assertEqual(kr.feed_transport(F(CAM)), "udp")          # Auto follows its pick
        self.assertEqual(kr.feed_transport(F(CAM, "tcp")), "tcp")   # a forced choice does not

    def test_auto_choice(self):
        ok = {"vcodec": "h264", "width": 640, "height": 360}
        silent = {"vcodec": "h264", "width": None}
        refused = {"vcodec": None, "refused": True}
        self.assertEqual(kr.auto_choice(ok), "tcp")
        self.assertEqual(kr.auto_choice(refused), "try-udp")
        self.assertEqual(kr.auto_choice(silent), "try-udp")
        self.assertEqual(kr.auto_choice({}), "try-udp")
        self.assertEqual(kr.auto_choice(refused, ok), "udp")
        self.assertEqual(kr.auto_choice(refused, {}), "tcp")         # neither: TCP stays, as before
        self.assertEqual(kr.auto_why(refused), "the camera refused TCP")
        self.assertEqual(kr.auto_why(silent), "TCP gave no picture")
        self.assertFalse(kr.probe_ok(None))
        self.assertTrue(kr.probe_ok(ok))


class AutoProbe(unittest.TestCase):
    """Bridge.sends_h264 with _probe_once replaced: which transports it asks, and what it keeps."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr096-")
        ks.forget_all()
        ks.configure(self.tmp)
        self.b = kr.Bridge(state_dir=self.tmp, log=lambda *a, **k: None)
        self.asked = []

    def tearDown(self):
        kr.AUTO_PICKS.clear()
        ks.forget_all()
        ks.configure(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def probe(self, answers):
        def once(url, transport=None):
            self.asked.append(transport)
            return dict(answers[transport])
        self.b._probe_once = once

    OK = {"vcodec": "h264", "width": 640, "height": 360, "fullrange": False, "sar": None, "acodec": None, "refused": False}
    MJPEG = {"vcodec": "mjpeg", "width": 640, "height": 360, "fullrange": True, "sar": None, "acodec": None, "refused": False}
    REFUSED = {"vcodec": None, "width": None, "height": None, "fullrange": None, "sar": None, "acodec": None, "refused": True}
    SILENT = {"vcodec": "h264", "width": None, "height": None, "fullrange": None, "sar": None, "acodec": None, "refused": False}

    def test_tcp_refused_auto_uses_udp(self):
        self.probe({"tcp": self.REFUSED, "udp": self.OK})
        f = F(CAM)
        self.assertTrue(self.b.sends_h264(f))
        self.assertEqual(self.asked, ["tcp", "udp"])
        self.assertEqual(kr.AUTO_PICKS[CAM]["transport"], "udp")
        self.assertEqual(kr.AUTO_PICKS[CAM]["why"], "the camera refused TCP")
        self.assertIn((CAM, "udp"), self.b._probed)
        self.assertNotIn((CAM, "tcp"), self.b._probed)
        self.assertTrue(f.tcp_refused)
        self.assertEqual(kr.feed_transport(f), "udp")
        info = kr.transport_info(f)
        self.assertEqual((info["transport"], info["transportNow"], info["transportWhy"]), ("auto", "udp", "the camera refused TCP"))
        # a reconnect (new feed object): the cache answers, no probe
        self.asked.clear()
        g = F(CAM)
        self.assertTrue(self.b.sends_h264(g))
        self.assertEqual(self.asked, [])
        self.assertEqual((g.width, g.height), (640, 360))

    def test_tcp_silent_auto_uses_udp_mjpeg(self):
        self.probe({"tcp": self.SILENT, "udp": self.MJPEG})
        f = F(CAM)
        self.assertFalse(self.b.sends_h264(f))          # MJPEG -> encoded
        self.assertEqual(f.vcodec, "mjpeg")
        self.assertEqual(kr.AUTO_PICKS[CAM]["why"], "TCP gave no picture")
        self.assertFalse(f.tcp_refused)

    def test_tcp_ok_no_udp_probe(self):
        self.probe({"tcp": self.OK, "udp": self.OK})
        self.assertTrue(self.b.sends_h264(F(CAM)))
        self.assertEqual(self.asked, ["tcp"])
        self.assertNotIn(CAM, kr.AUTO_PICKS)

    def test_neither_keeps_tcp(self):
        self.probe({"tcp": self.REFUSED, "udp": self.REFUSED})
        f = F(CAM)
        self.assertFalse(self.b.sends_h264(f))
        self.assertEqual(self.asked, ["tcp", "udp"])
        self.assertNotIn(CAM, kr.AUTO_PICKS)
        self.assertTrue(f.tcp_refused and f.udp_refused)
        self.assertEqual(kr.feed_transport(f), "tcp")
        self.assertTrue(f.probe_failed_at)

    def test_forced_tcp_never_asks_udp(self):
        self.probe({"tcp": self.REFUSED, "udp": self.OK})
        f = F(CAM, "tcp")
        self.b.sends_h264(f)
        self.assertEqual(self.asked, ["tcp"])
        self.assertTrue(f.tcp_refused)

    def test_forced_udp_asks_udp_only(self):
        self.probe({"tcp": self.OK, "udp": self.OK})
        self.assertTrue(self.b.sends_h264(F(CAM, "udp")))
        self.assertEqual(self.asked, ["udp"])
        self.assertIn((CAM, "udp"), self.b._probed)

    def test_rtsps_never_asks_udp(self):
        self.probe({"tcp": self.REFUSED, "udp": self.OK})
        self.b.sends_h264(F(SECURE))
        self.assertEqual(self.asked, ["tcp"])

    def test_runtime_refusal_drops_the_tcp_cache(self):
        f = F(CAM)
        self.b._probed[(CAM, "tcp")] = (True, 640, 360, False, "h264", "", None)
        f.h264 = True
        body = kr.rtsp_line(f, "pub", "tcp", "[in#0 @ 0000] [error] method SETUP failed: 461 Unsupported Transport", bridge=self.b)
        self.assertIn("461", body)
        self.assertNotIn("[error]", body)
        self.assertTrue(f.tcp_refused)
        self.assertNotIn((CAM, "tcp"), self.b._probed)
        self.assertIsNone(f.h264)
        # a forced TCP keeps its cache (nothing else would be tried)
        g = F(CAM, "tcp")
        self.b._probed[(CAM, "tcp")] = (True, 640, 360, False, "h264", "", None)
        kr.rtsp_line(g, "pub", "tcp", "[error] method SETUP failed: 461 Unsupported Transport", bridge=self.b)
        self.assertIn((CAM, "tcp"), self.b._probed)


class Persist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr096-")
        ks.forget_all()
        ks.configure(self.tmp)
        self.logs = []

    def tearDown(self):
        kr.AUTO_PICKS.clear()
        ks.forget_all()
        ks.configure(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bridge(self):
        return kr.Bridge(state_dir=self.tmp, log=self.logs.append)

    def doc(self):
        with open(os.path.join(self.tmp, "rtsp-feeds.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_round_trip(self):
        b = self.bridge()
        f1, f2 = b.add(CAM), b.add(CAM_CREDS)
        self.assertEqual(f1.transport, "auto")
        r = b.set_transport(f1.id, "udp")
        self.assertEqual((r["ok"], r["transport"], r["transportNow"], r["restarted"]), (True, "udp", "udp", True))
        self.assertFalse(b.set_transport(f1.id, "UDP")["restarted"])     # same choice: nothing restarts
        b.set_transport(f2.id, "tcp")
        d = self.doc()
        modes = sorted(t["mode"] for t in d["transports"])
        self.assertEqual(modes, ["tcp", "udp"])
        self.assertIn({"url": CAM, "mode": "udp"}, d["transports"])
        with open(os.path.join(self.tmp, "rtsp-feeds.json"), "rb") as fh:
            self.assertNotIn(CAMPW.encode(), fh.read())                   # the camera password is sealed
        # a relaunch: restored per URL, applied by add()
        ks.forget_all()
        ks.configure(self.tmp)
        b2 = self.bridge()
        self.assertEqual(b2._transports.get(CAM), "udp")
        self.assertEqual(b2._transports.get(CAM_CREDS), "tcp")
        self.assertEqual(b2.add(CAM).transport, "udp")
        g = b2.add(CAM_CREDS)
        self.assertEqual(g.transport, "tcp")
        self.assertEqual(b2.add("rtsp://192.0.2.99/other").transport, "auto")
        # Auto is the default: not stored
        b2.set_transport(g.id, "auto")
        self.assertNotIn(CAM_CREDS, [t.get("url") for t in self.doc()["transports"]] + list(b2._transports))
        self.assertEqual(len(self.doc()["transports"]), 1)

    def test_bad_input(self):
        b = self.bridge()
        f = b.add(CAM)
        with self.assertRaises(ValueError):
            b.set_transport(f.id, "quic")
        with self.assertRaises(ValueError):
            b.set_transport(999, "udp")
        h = b.add("http://192.0.2.5/a.mp4")
        with self.assertRaises(ValueError):
            b.set_transport(h.id, "udp")

    def test_change_resets_and_restarts(self):
        b = self.bridge()
        f = b.add(CAM)
        kr.AUTO_PICKS[CAM] = {"transport": "udp", "why": "x"}
        f.tcp_refused = time.time()
        f.loss.add("pub", "missed", 5)
        f.h264 = True
        killed = []
        b.kill = lambda feed: killed.append(feed.id)
        b.set_transport(f.id, "tcp")
        self.assertEqual(killed, [f.id])
        self.assertNotIn(CAM, kr.AUTO_PICKS)
        self.assertIsNone(f.tcp_refused)
        self.assertIsNone(f.h264)
        self.assertEqual(f.loss.info()["missed"], 0)
        self.assertTrue(any("transport auto -> tcp" in str(x) for x in self.logs))

    def test_api_route_is_local_only(self):
        i = RTSP_SRC.index('"/api/rtsp/transport"')
        self.assertIn("bridge.set_transport(payload.get(\"id\"), payload.get(\"transport\"))", RTSP_SRC)
        self.assertIn('"transports/*/url~"', _read("kastr_secret.py"))
        self.assertGreater(i, 0)


class Loss(unittest.TestCase):
    LINES = [
        ("[in#0/rtsp @ 000001] [warning] RTP: missed 7 packets", ("missed", 7)),
        ("[in#0/rtsp @ 000001] [warning] RTP: missed 1 packet", ("missed", 1)),
        ("[in#0/rtsp @ 000001] [warning] max delay reached. need to consume packet", ("late", 1)),
        ("[rtsp @ 0x55] [warning] bad cseq 0003 expected=0002", ("badseq", 1)),
        ("[in#0/rtsp @ 000001] [error] Received packet without a start chunk; dropping frame.", ("frames", 1)),
        ("[h264 @ 000002] [error] error while decoding MB 12 7, bytestream -5", ("decode", 1)),
        ("[h264 @ 000002] [error] concealing 120 DC, 120 AC, 120 MV errors in P frame", ("decode", 1)),
    ]

    def test_parser(self):
        for text, want in self.LINES:
            _lvl, body = kr.split_level(text)
            self.assertEqual(kr.parse_loss_line(body), want, text)
        for text in ("[in#0 @ 1] [error] method SETUP failed: 461 Unsupported Transport",
                     "Stream #0:0: Video: h264 (High), yuv420p, 640x360, 25 fps",
                     "frame=  100 fps= 25 q=-1.0 size=N/A time=00:00:04.00"):
            self.assertIsNone(kr.parse_loss_line(kr.split_level(text)[1]), text)

    def test_split_level(self):
        self.assertEqual(kr.split_level("[in#0/rtsp @ 0x1] [warning] RTP: missed 3 packets"),
                         ("warning", "[in#0/rtsp @ 0x1] RTP: missed 3 packets"))
        self.assertEqual(kr.split_level("[error] Error opening input: Error number -135"),
                         ("error", "Error opening input: Error number -135"))
        self.assertEqual(kr.split_level("plain line"), (None, "plain line"))

    def test_meter_window_repeat_headline(self):
        m = kr.LossMeter(now=1000)
        m.touch("mon")
        self.assertEqual(m.info(now=1000)["reader"], "mon")
        t = 1000.0
        m.line("pub", "RTP: missed 10 packets", now=t)
        m.line("pub", "    Last message repeated 3 times", now=t + 1)     # 10 more x 3
        m.line("pub", "frame= 1 fps=25", now=t + 1)
        m.line("pub", "    Last message repeated 2 times", now=t + 1)     # after a non-loss line: nothing
        m.line("pub", "RTP: missed 2 packets", now=t + 90)
        m.line("mon", "RTP: missed 50 packets", now=t + 90)
        m.line("pub", "max delay reached. need to consume packet", now=t + 90)
        i = m.info(now=t + 91)
        self.assertEqual(i["reader"], "pub")                               # the native pair is the headline
        self.assertEqual(i["missed"], 42)
        self.assertEqual(i["missed60"], 2)                                 # the first 40 left the window
        self.assertEqual((i["late"], i["late60"]), (1, 1))
        self.assertEqual(i["readers"]["mon"]["total"]["missed"], 50)
        self.assertEqual(i["window"], 60)
        self.assertEqual(i["lastAt"], t + 90)

    def test_rtsp_line_returns(self):
        f = F(CAM, "udp")
        self.assertIsNone(kr.rtsp_line(f, "pub", "udp", "[in#0/rtsp @ 1] [warning] RTP: missed 4 packets"))
        self.assertIsNone(kr.rtsp_line(f, "pub", "udp", "[in#0/rtsp @ 1] [error] Received packet without a start chunk; dropping frame."))
        self.assertIsNone(kr.rtsp_line(f, "pub", "udp", "[in#0/rtsp @ 1] [warning] some other warning"))
        self.assertEqual(kr.rtsp_line(f, "pub", "udp", "[in#0 @ 1] [error] Error opening input: Error number -138"),
                         "[in#0 @ 1] Error opening input: Error number -138")
        self.assertEqual(kr.rtsp_line(f, "pub", "tcp", "[in#0/rtsp @ 1] [warning] Failed reading RTSP data: Error number -138"),
                         "[in#0/rtsp @ 1] Failed reading RTSP data: Error number -138")       # a warning that says why
        self.assertEqual(kr.rtsp_line(f, "pub", "udp", "Error opening input"), "Error opening input")   # untagged: kept
        i = f.loss.info()
        self.assertEqual((i["missed"], i["frames"]), (4, 1))
        g = F(CAM, "udp")
        kr.rtsp_line(g, "pub", "udp", "[in#0 @ 1] [error] method SETUP failed: 461 Unsupported Transport")
        self.assertTrue(g.udp_refused)
        self.assertIsNone(g.tcp_refused)

    def test_udp_decoder_errors_are_counted_not_kept(self):
        f = F("rtsp://127.0.0.1:9/x", "udp")
        for line in ("[h264 @ 0000015251766780] [error] Slice overlaps with next at 720",
                     "[h264 @ 0000015251766780] [error] corrupted macroblock 18 4 (total_coeff=16)",
                     "Last message repeated 2 times"):
            self.assertIsNone(kr.rtsp_line(f, "mon", "udp", line))
        self.assertEqual(f.loss.info()["readers"]["mon"]["total"]["decode"], 4)
        # over TCP a decoder error is still kept: there it says something is wrong with the camera
        self.assertEqual(kr.rtsp_line(F("rtsp://127.0.0.1:9/x", "tcp"), "mon", "tcp", "[h264 @ 0x1] [error] Slice overlaps"), "[h264 @ 0x1] Slice overlaps")

    def test_drains_use_rtsp_line(self):
        self.assertIn('rtsp_line(feed, "mon", tr, text, bridge=self)', RTSP_SRC)
        self.assertGreaterEqual(RTSP_SRC.count("rtsp_line("), 3)


class Monitor(unittest.TestCase):
    """The share page's monitor of a UDP camera: always an encode, and the page's ?transcode=1 / ?pt=1 now arrive."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr096-")
        self.b = kr.Bridge(state_dir=self.tmp, log=lambda *a, **k: None)

    def tearDown(self):
        kr.AUTO_PICKS.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def feed(self, transport):
        f = F("rtsp://127.0.0.1:9/cam", transport)
        f.h264, f.vcodec, f.width, f.fullrange, f.sar = True, "h264", 640, False, None
        return f

    def test_udp_monitor_is_an_encode(self):
        self.assertEqual(self.b.monitor_plan(self.feed("tcp"), False, True), (True, False))   # a TCP H.264 camera: copied
        self.assertEqual(self.b.monitor_plan(self.feed("udp"), False, True), (False, False))  # UDP: a lost packet is a decode error in Chrome
        self.assertEqual(self.b.monitor_codec(self.feed("udp"), False, True), ("h264", False))
        self.assertEqual(self.b.monitor_plan(self.feed("tcp"), True, True), (False, False))   # transcode=1 always encodes

    def test_udp_publisher_is_an_encode(self):
        def args(transport, env=None):
            f = self.feed(transport)
            br = types.SimpleNamespace(ffmpeg="ffmpeg", moq="moq", sends_h264=lambda f: True, usable_encoder=lambda: "libx264",
                                       rc_lowlat=lambda e: [], _od_ensure=lambda: None)
            pub = kr.Publisher(br, f, "alpha/h-aa11/me/cam.hang", "http://relay:4443", audio=False, keep=False, passthrough=True)
            with mock.patch.dict(os.environ, env or {}, clear=False):
                if not env:
                    os.environ.pop("KASTR_RTSP_UDP_COPY", None)
                ff, _ = pub._args()
            return pub.copy, ff
        copy, ff = args("tcp")
        self.assertTrue(copy)
        copy, ff = args("udp")
        self.assertFalse(copy)                       # decoded (ffmpeg conceals the lost packets) and encoded once
        self.assertEqual(_opt(ff, "-rtsp_transport"), "udp")
        self.assertIn("libx264", ff)
        copy, _ = args("udp", {"KASTR_RTSP_UDP_COPY": "1"})
        self.assertTrue(copy)                        # the escape hatch for a link known clean
        with mock.patch.dict(os.environ, {"KASTR_RTSP_UDP_COPY": "1"}):
            self.assertEqual(self.b.monitor_plan(self.feed("udp"), False, True), (True, False))

    def test_stream_query_recovers_the_flags(self):
        class H:
            path = "/rtsp/3?pt=1&transcode=1"
        self.assertEqual(kr.parse_stream_path(kr.stream_query(H(), "/rtsp/3")), ("3", True, True))
        self.assertEqual(kr.parse_stream_path(kr.stream_query(H(), "/rtsp/3?transcode=1")), ("3", True, False))
        H.path = "/rtsp/4?transcode=1"   # not this request's path: ignored
        self.assertEqual(kr.parse_stream_path(kr.stream_query(H(), "/rtsp/3")), ("3", False, False))
        self.assertIn("parse_stream_path(stream_query(handler, path))", RTSP_SRC)

    def test_progress_lines_are_not_errors(self):
        for line in ("speed=   1x", "stream_0_0_q=-1.0", "frame=12", "total_size=4096", "progress=continue"):
            self.assertTrue(kr.PROGRESS_RE.match(line), line)
        for line in ("[h264 @ 0x1] error while decoding MB 1 2", "Connection to tcp://x failed: Error number -138 occurred"):
            self.assertFalse(kr.PROGRESS_RE.match(line), line)


class Info(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr096-")
        ks.forget_all()
        ks.configure(self.tmp)

    def tearDown(self):
        kr.AUTO_PICKS.clear()
        ks.forget_all()
        ks.configure(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_feed_info_and_diag(self):
        b = kr.Bridge(state_dir=self.tmp, log=lambda *a, **k: None)
        f = b.add(CAM_CREDS)
        s = b.add(SECURE)
        h = b.add("http://192.0.2.5/a.mp4")
        kr.AUTO_PICKS[f.url] = {"transport": "udp", "why": "the camera refused TCP", "at": 1}
        f.loss.add("pub", "missed", 37)
        i = f.info()
        for k in ("transport", "transportNow", "transportWhy", "tcpRefused", "udpRefused", "loss"):
            self.assertIn(k, i)
        self.assertEqual((i["transport"], i["transportNow"]), ("auto", "udp"))
        self.assertEqual(i["loss"]["missed"], 37)
        self.assertEqual(i["loss"]["missed60"], 37)
        self.assertEqual(s.info()["transportNow"], "tcp")
        self.assertEqual(s.info()["transportWhy"], "rtsps:// always uses TCP")
        self.assertIsNone(h.info()["transport"])
        self.assertIsNone(h.info()["loss"])
        json.dumps(i)
        d = b.diag_feeds()
        self.assertEqual(sorted(x["id"] for x in d), sorted([f.id, s.id]))
        blob = json.dumps(d)
        self.assertNotIn(CAMPW, blob)
        self.assertIn("***@192.0.2.11", blob)
        row = next(x for x in d if x["id"] == f.id)
        self.assertEqual((row["transportNow"], row["loss"]["missed"]), ("udp", 37))

    def test_diag_and_publisher_state_carry_it(self):
        self.assertIn('out["_rtsp"] = bridge.diag_feeds()', SERVE)
        self.assertIn("transport: s.feed?.transport ? { mode: s.feed.transport", PAGE)
        self.assertIn("line: transportLine(s.feed)", PAGE)


class Page(unittest.TestCase):
    def test_row_select(self):
        self.assertIn('tsel.className = "gsel tsel"', PAGE)
        for t in ('"Transport: Auto"', '"Transport: TCP"', '"Transport: UDP"'):
            self.assertIn(t, PAGE)
        self.assertIn("tsel.disabled = secure", PAGE)
        self.assertIn("rtsps:// always uses TCP", PAGE)
        self.assertIn("window.__rtspTransport?.set?.(a.id, tsel.value)", PAGE)
        self.assertIn('nativePost("/api/rtsp/transport", { id: a.feedId, transport: mode })', PAGE)
        self.assertIn(".pubui .camrow .tsel", PAGE)
        self.assertIn(".pubui .camrow .trline", PAGE)

    def test_fault_text(self):
        self.assertIn("const th = transportFault(slot.feed);", PAGE)
        self.assertIn("set Transport to UDP or Auto on its row", PAGE)
        self.assertIn("(if it plays in VLC, set Transport to Auto or UDP on its row)", PAGE)
        # a server-published (native) camera never reaches faultText's transport branch: the row line and the alert carry it
        self.assertIn("const flt = transportFault(f), txt = flt ?", PAGE)
        self.assertIn("(slot.native && transportFault(slot.feed))", PAGE)

    def test_page_is_crlf(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), "rb") as fh:
            raw = fh.read()
        self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))
        with open(os.path.join(HERE, "kastr_rtsp.py"), "rb") as fh:
            raw = fh.read()
        self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))


PAGE_JS = "\n".join([_js_fn(PAGE, "  function transportFault(f) {"), _js_fn(PAGE, "  function transportLine(f) {")])


class PageJs(unittest.TestCase):
    """transportLine / transportFault run in the bundled Chromium (skipped without Playwright)."""

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            raise unittest.SkipTest("no Playwright")
        if not _chrome():
            raise unittest.SkipTest("no bundled Chrome")
        cls._pw = sync_playwright().start()
        cls._br = cls._pw.chromium.launch(executable_path=_chrome(), headless=True)
        cls._pg = cls._br.new_page()
        cls._pg.route("**/*", lambda r: r.abort())
        cls._pg.set_content("<!doctype html><script>" + PAGE_JS + "\nwindow.tl = transportLine; window.tf = transportFault;</script>")

    @classmethod
    def tearDownClass(cls):
        cls._br.close()
        cls._pw.stop()

    def line(self, f):
        return self._pg.evaluate("(f) => window.tl(f)", f)

    def fault(self, f):
        return self._pg.evaluate("(f) => window.tf(f)", f)

    def test_lines(self):
        loss = {"missed": 212, "missed60": 37, "frames60": 2, "late60": 1, "frames": 5}
        self.assertEqual(self.line({"transport": "udp", "transportNow": "udp", "loss": loss}),
                         "UDP · lost 37 packets in the last minute (212 since start) · 2 frames dropped in the last minute")
        self.assertEqual(self.line({"transport": "auto", "transportNow": "udp", "transportWhy": "the camera refused TCP", "loss": {}}),
                         "Auto · using UDP — the camera refused TCP · no packets lost")
        self.assertEqual(self.line({"transport": "tcp", "transportNow": "tcp", "loss": {}}), "")
        self.assertEqual(self.line({"transport": "auto", "transportNow": "tcp", "loss": {}}), "")
        self.assertEqual(self.line({"transport": "tcp", "transportNow": "tcp", "loss": {"missed": 3, "missed60": 1}}),
                         "TCP · lost 1 packet in the last minute (3 since start)")
        self.assertEqual(self.line(None), "")
        self.assertEqual(self.line({"transport": None}), "")

    def test_faults(self):
        self.assertEqual(self.fault({"transport": "tcp", "transportNow": "tcp", "tcpRefused": 1}),
                         "the camera refused RTSP over TCP — set Transport to UDP or Auto on its row")
        self.assertIn("gave no picture over UDP either",
                      self.fault({"transport": "auto", "transportNow": "tcp", "tcpRefused": 1, "udpRefused": 1}))
        self.assertEqual(self.fault({"transport": "udp", "transportNow": "udp", "udpRefused": 1}),
                         "the camera refused RTSP over UDP — set Transport to TCP or Auto on its row")
        self.assertEqual(self.fault({"transport": "tcp", "transportNow": "tcp"}), "")
        self.assertEqual(self.fault(None), "")
        # a refusal the camera's video has since outlived is history; one after the last video still counts
        self.assertEqual(self.fault({"transport": "tcp", "transportNow": "tcp", "tcpRefused": 100, "publish": {"videoAt": 200}}), "")
        self.assertIn("refused RTSP over TCP", self.fault({"transport": "tcp", "transportNow": "tcp", "tcpRefused": 200, "publish": {"videoAt": 100}}))


if __name__ == "__main__":
    unittest.main()
