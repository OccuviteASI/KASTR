# -*- coding: utf-8 -*-
"""v0.21.81 (Kenton: "When recording is used, allow for saving in multiple different formats. Default to MP4.").

Record's save dialog offers MP4 (default), WebM, MKV, MOV, M4A and MP3. The KASTR app converts on this computer
(kastr_record.py + the bundled ffmpeg); a web viewer gets what its browser recorded and the rest greyed.

Covered here:
  * the conversion plan + ffmpeg argument set per format (copy when the recording's codecs fit, else the encoder)
  * progress parsing, file names, the formats list (MP3 only with libmp3lame)
  * the endpoints: this computer only (remote / proxied / another site's page refused), validation (format, length,
    size cap, disk space, too many at once), unknown jobs, cancel
  * end to end with the real ffmpeg when one is present: every format from an H.264 + AAC (fragmented MP4, the
    browser's) and a VP9 + Opus (WebM) recording, the result's codecs, and that every temp file is gone afterwards;
    a cancel mid-conversion kills ffmpeg and deletes its files
  * the page: the format list + MP4 default, the recorder's MP4-first mime list, the convert / cancel calls, the web
    viewer's greyed formats, Record's room announce kept
  * the server routes + the build's hidden import"""
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_record as kr  # noqa: E402
import kastr_serve  # noqa: E402


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def find_ffmpeg():
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    p = os.path.join(HERE, "bin", exe)
    if os.path.exists(p) and os.access(p, os.X_OK):
        return p
    return shutil.which("ffmpeg")


FF = find_ffmpeg()


class Plan(unittest.TestCase):
    def test_default_and_list(self):
        self.assertEqual(kr.FORMATS, ("mp4", "webm", "mkv", "mov", "m4a", "mp3"))
        self.assertEqual(kr.DEFAULT_FORMAT, "mp4")

    def test_browser_mp4_recording_copies_where_it_fits(self):
        self.assertEqual(kr.plan("mp4", "h264", "aac"), ("copy", "copy"))
        self.assertEqual(kr.plan("mov", "h264", "aac"), ("copy", "copy"))
        self.assertEqual(kr.plan("mkv", "h264", "aac"), ("copy", "copy"))
        self.assertEqual(kr.plan("m4a", "h264", "aac"), (None, "copy"))
        self.assertEqual(kr.plan("mp3", "h264", "aac"), (None, "libmp3lame"))
        self.assertEqual(kr.plan("webm", "h264", "aac"), ("libvpx-vp9", "libopus"))

    def test_webm_recording(self):
        self.assertEqual(kr.plan("webm", "vp9", "opus"), ("copy", "copy"))
        self.assertEqual(kr.plan("webm", "vp8", "vorbis"), ("copy", "copy"))
        self.assertEqual(kr.plan("mkv", "vp9", "opus"), ("copy", "copy"))
        self.assertEqual(kr.plan("mp4", "vp9", "opus"), ("libx264", "aac"))
        self.assertEqual(kr.plan("mov", "vp8", "opus"), ("libx264", "aac"))
        self.assertEqual(kr.plan("m4a", "vp9", "opus"), (None, "aac"))
        self.assertEqual(kr.plan("mp3", "vp9", "opus"), (None, "libmp3lame"))

    def test_linux_chromium_mp4_with_opus_reencodes_only_the_sound(self):
        self.assertEqual(kr.plan("mp4", "h264", "opus"), ("copy", "aac"))
        self.assertEqual(kr.plan("mkv", "h264", "opus"), ("copy", "copy"))

    def test_mkv_unusual_codecs_become_h264_aac(self):
        self.assertEqual(kr.plan("mkv", "mpeg4", "pcm_s16le"), ("libx264", "aac"))

    def test_no_sound_or_nothing(self):
        with self.assertRaisesRegex(ValueError, "no sound"):
            kr.plan("m4a", "h264", None)
        with self.assertRaisesRegex(ValueError, "no sound"):
            kr.plan("mp3", "vp9", None)
        self.assertEqual(kr.plan("mp4", "h264", None), ("copy", None))
        with self.assertRaises(ValueError):
            kr.plan("mp4", None, None)
        with self.assertRaises(ValueError):
            kr.plan("avi", "h264", "aac")


class Args(unittest.TestCase):
    def a(self, fmt, v, a):
        return kr.build_args("ffmpeg", "in.src", "out.x", fmt, v, a)

    def common(self, argv, muxer):
        self.assertEqual(argv[0], "ffmpeg")
        for flag in ("-nostdin", "-y", "-hide_banner"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("-progress") + 1], "pipe:1")
        self.assertEqual(argv[argv.index("-loglevel") + 1], "error")
        self.assertEqual(argv[argv.index("-i") + 1], "in.src")
        self.assertEqual(argv[-3:], ["-f", muxer, "out.x"])
        self.assertLess(argv.index("-progress"), argv.index("-i"))   # global options before the input

    def test_mp4_remux(self):
        argv = self.a("mp4", "h264", "aac")
        self.common(argv, "mp4")
        s = " ".join(argv)
        self.assertIn("-map 0:v:0 -map 0:a:0 -c:v copy -c:a copy -movflags +faststart", s)
        self.assertNotIn("libx264", s)

    def test_mp4_from_webm_encodes_h264_aac(self):
        s = " ".join(self.a("mp4", "vp9", "opus"))
        self.assertIn("-c:v libx264 -preset veryfast -crf 20 -profile:v high", s)
        self.assertIn("out_range=tv,format=yuv420p", s)
        self.assertIn("-c:a aac -b:a 192k", s)
        self.assertIn("+faststart", s)

    def test_mov(self):
        argv = self.a("mov", "h264", "aac")
        self.common(argv, "mov")
        self.assertIn("+faststart", argv)

    def test_mkv_copy(self):
        argv = self.a("mkv", "vp9", "opus")
        self.common(argv, "matroska")
        self.assertEqual(argv[argv.index("-c:v") + 1], "copy")
        self.assertEqual(argv[argv.index("-c:a") + 1], "copy")
        self.assertNotIn("-movflags", argv)

    def test_webm_from_mp4(self):
        argv = self.a("webm", "h264", "aac")
        self.common(argv, "webm")
        s = " ".join(argv)
        self.assertIn("-c:v libvpx-vp9 -deadline realtime -cpu-used 8 -row-mt 1 -b:v 5M", s)
        self.assertIn("-c:a libopus -b:a 128k", s)

    def test_m4a_audio_only(self):
        argv = self.a("m4a", "h264", "aac")
        self.common(argv, "ipod")
        self.assertIn("-vn", argv)
        self.assertNotIn("0:v:0", argv)
        self.assertEqual(argv[argv.index("-c:a") + 1], "copy")
        self.assertIn("+faststart", argv)

    def test_mp3_audio_only(self):
        argv = self.a("mp3", "vp9", "opus")
        self.common(argv, "mp3")
        self.assertIn("-vn", argv)
        self.assertIn("-c:a libmp3lame -q:a 2", " ".join(argv))

    def test_video_only_recording(self):
        argv = self.a("mp4", "h264", None)
        self.assertIn("-an", argv)
        self.assertNotIn("0:a:0", argv)


class Bits(unittest.TestCase):
    def test_progress(self):
        self.assertEqual(kr.progress_seconds("out_time_us=12500000\n"), 12.5)
        self.assertEqual(kr.progress_seconds("out_time_ms=2000000"), 2.0)   # ffmpeg's _ms is microseconds too
        self.assertAlmostEqual(kr.progress_seconds("out_time=00:01:02.500000"), 62.5)
        self.assertIsNone(kr.progress_seconds("progress=continue"))
        self.assertIsNone(kr.progress_seconds("out_time_us=N/A"))

    def test_safe_name(self):
        self.assertEqual(kr.safe_name("KASTR-room-2026-10-22_10-00.webm", "mp4"), "KASTR-room-2026-10-22_10-00.mp4")
        self.assertEqual(kr.safe_name("..\\..\\evil:name?.mp4", "mp3"), "evil-name-.mp3")
        self.assertEqual(kr.safe_name("/etc/passwd", "mkv"), "passwd.mkv")
        self.assertEqual(kr.safe_name("", "m4a"), "recording.m4a")
        self.assertEqual(kr.safe_name("Zoë's take", "mov"), "Zoë's take.mov")

    def test_formats_info_mp3_needs_lame(self):
        with mock.patch.object(kr, "encoders", return_value={"libx264", "aac", "libvpx-vp9", "libopus"}):
            info = kr.formats_info("ffmpeg")
        self.assertFalse(info["mp3"]["ok"])
        self.assertIn("MP3", info["mp3"]["why"])
        self.assertTrue(all(info[f]["ok"] for f in ("mp4", "webm", "mkv", "mov", "m4a")))
        with mock.patch.object(kr, "encoders", return_value=set(kr.NEEDS)):
            self.assertTrue(all(v["ok"] for v in kr.formats_info("ffmpeg").values()))
        self.assertFalse(any(v["ok"] for v in kr.formats_info(None).values()))

    @unittest.skipUnless(FF, "no ffmpeg here")
    def test_bundled_ffmpeg_has_every_encoder(self):
        self.assertEqual(kr.encoders(FF), set(kr.NEEDS))


class FakeBridge:
    def __init__(self, ff):
        self.ffmpeg = ff


class Endpoints(unittest.TestCase):
    """The HTTP surface on a real kastr_serve server (bridge = an object with .ffmpeg)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kastr-rec-")
        cls.patch = mock.patch.object(kastr_serve, "STATE_DIR", cls.tmp)
        cls.patch.start()
        cls.globals = (kastr_serve._MEDIA_BRIDGE[0], kastr_serve.RTSP_BRIDGE[0])   # make_server sets both
        cls.srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True, bridge=FakeBridge(FF or "ffmpeg-missing"))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.media = os.path.join(cls.tmp, "media")
        if FF:
            cls.clips = {}
            for name, args in (
                    ("h264aac.mp4", ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                                     "-movflags", "frag_keyframe+empty_moov+default_base_moof"]),   # the browser's fragmented MP4
                    ("vp9opus.webm", ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus"])):
                p = os.path.join(cls.tmp, name)
                subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
                                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "3"] + args + [p],
                               check=True, timeout=120)
                cls.clips[name] = p

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.patch.stop()
        kastr_serve._MEDIA_BRIDGE[0], kastr_serve.RTSP_BRIDGE[0] = cls.globals
        with kr.JOBS_LOCK:
            jobs = list(kr.JOBS.values())
        for j in jobs:
            kr.drop(j)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        # 0.21.92: under a loaded machine (the full suite next to a Linux build) Windows once in a while gave up on the
        # loopback CONNECT itself (WinError 10060 after ~21 s of unanswered SYNs) while the server kept serving -- every
        # request here is a new connection (HTTP/1.0) and the server closes first, so its TIME_WAITs pile up on this port.
        # Nothing was sent yet when the connect fails, so a fresh connection (a new client port) is a safe retry.
        for attempt in range(4):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
            try:
                c.connect()
                break
            except (ConnectionError, TimeoutError, OSError):
                c.close()
                if attempt == 3:
                    raise
                time.sleep(0.5 * (attempt + 1))
        h = dict(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data, r

    def jreq(self, *a, **k):
        code, data, _r = self.req(*a, **k)
        try:
            return code, json.loads(data or b"{}")
        except ValueError:
            return code, {"raw": data[:200]}

    def rec_files(self):
        try:
            return sorted(f for f in os.listdir(self.media) if f.startswith("rec-"))
        except OSError:
            return []

    def test_this_computer_only(self):
        self.assertEqual(self.jreq("GET", "/api/record/formats", headers={"X-Forwarded-For": "10.1.2.3"})[0], 403)
        self.assertEqual(self.jreq("GET", "/api/record/formats", headers={"Host": "10.0.0.5:8000"})[0], 403)
        self.assertEqual(self.jreq("GET", "/api/record/formats", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.jreq("GET", "/api/record/formats", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.jreq("POST", "/api/record/convert?fmt=mp4", body=b"x" * 10,
                                   headers={"Origin": "http://evil.example", "Content-Length": "10"})[0], 403)
        code, d = self.jreq("GET", "/api/record/formats", headers={"Origin": "http://127.0.0.1:%d" % self.port, "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(code, 200)
        self.assertEqual(d["default"], "mp4")
        self.assertEqual(list(d["formats"]), list(kr.FORMATS))
        self.assertEqual(d["max"], kr.UPLOAD_MAX)

    def test_validation(self):
        if not FF:
            self.skipTest("no ffmpeg here")
        self.forget_jobs()
        self.assertEqual(self.jreq("POST", "/api/record/convert?fmt=avi", body=b"x" * 10)[0], 400)
        self.assertEqual(self.jreq("POST", "/api/record/convert?fmt=mp4", body=b"")[0], 411)
        with mock.patch.object(kr, "UPLOAD_MAX", 100):
            self.assertEqual(self.jreq("POST", "/api/record/convert?fmt=mp4", body=b"x" * 101)[0], 413)
        with mock.patch.object(kr.shutil, "disk_usage", return_value=mock.Mock(free=10)):
            code, d = self.jreq("POST", "/api/record/convert?fmt=mp4", body=b"x" * 1000)
            self.assertEqual(code, 507)
            self.assertIn("disk space", d["error"])
        busy = [kr.Job(("%032x" % i), "mp4", "", "", 0) for i in range(kr.MAX_ACTIVE)]
        for j in busy:
            j.state = "converting"
            kr.JOBS[j.id] = j
        try:
            self.assertEqual(self.jreq("POST", "/api/record/convert?fmt=mp4", body=b"x" * 1000)[0], 429)
        finally:
            for j in busy:
                kr.JOBS.pop(j.id, None)
        code, d = self.jreq("POST", "/api/record/convert?fmt=mp4", body=b"not a video at all" * 100)
        self.assertEqual(code, 400)
        self.assertEqual(self.rec_files(), [])   # the refused upload is gone
        with mock.patch.object(kr, "encoders", return_value={"libx264", "aac"}):
            code, d = self.jreq("POST", "/api/record/convert?fmt=mp3", body=b"x" * 1000)
            self.assertEqual(code, 400)
            self.assertIn("MP3", d["error"])

    def test_unknown_jobs(self):
        self.assertEqual(self.jreq("GET", "/api/record/job/" + "a" * 32)[0], 404)
        self.assertEqual(self.jreq("GET", "/api/record/job/" + "a" * 32 + "/file")[0], 404)
        self.assertEqual(self.jreq("GET", "/api/record/job/../../etc")[0], 404)
        code, d = self.jreq("POST", "/api/record/job/" + "a" * 32 + "/cancel")
        self.assertEqual((code, d.get("state")), (200, "gone"))

    def test_no_ffmpeg(self):
        srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True, bridge=None)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
            c.request("GET", "/api/record/formats")
            d = json.loads(c.getresponse().read())
            self.assertFalse(d["ffmpeg"])
            self.assertFalse(any(v["ok"] for v in d["formats"].values()))
            c.request("POST", "/api/record/convert?fmt=mp4", body=b"x" * 100)
            self.assertEqual(c.getresponse().status, 503)
            c.close()
        finally:
            srv.shutdown()
            srv.server_close()

    def wait_job(self, job, limit=120):
        t0 = time.time()
        while time.time() - t0 < limit:
            code, d = self.jreq("GET", "/api/record/job/" + job)
            if d.get("state") in ("done", "error", "cancelled"):
                return d
            time.sleep(0.4)   # 0.21.92: fewer connections while a conversion runs
        self.fail("job did not finish")

    @staticmethod
    def forget_jobs():
        """0.21.92: a subtest that failed half-way leaves no job / files behind for the next one to trip over."""
        with kr.JOBS_LOCK:
            jobs = list(kr.JOBS.values())
        for j in jobs:
            kr.drop(j)

    def probe_out(self, data, fmt):
        p = os.path.join(self.tmp, "check" + kr.EXT[fmt])
        with open(p, "wb") as f:
            f.write(data)
        v, a, dur = kr.probe(FF, p)
        os.remove(p)
        return v, a, dur

    @unittest.skipUnless(FF, "no ffmpeg here")
    def test_every_format_end_to_end(self):
        want = {  # (source clip, fmt) -> (video codec, audio codec)
            ("h264aac.mp4", "mp4"): ("h264", "aac"), ("h264aac.mp4", "mov"): ("h264", "aac"),
            ("h264aac.mp4", "mkv"): ("h264", "aac"), ("h264aac.mp4", "webm"): ("vp9", "opus"),
            ("h264aac.mp4", "m4a"): (None, "aac"), ("h264aac.mp4", "mp3"): (None, "mp3"),
            ("vp9opus.webm", "webm"): ("vp9", "opus"), ("vp9opus.webm", "mp4"): ("h264", "aac"),
            ("vp9opus.webm", "mkv"): ("vp9", "opus"), ("vp9opus.webm", "mov"): ("h264", "aac"),
            ("vp9opus.webm", "m4a"): (None, "aac"), ("vp9opus.webm", "mp3"): (None, "mp3"),
        }
        for (clip, fmt), (wv, wa) in want.items():
            with self.subTest(clip=clip, fmt=fmt):
                self.forget_jobs()
                with open(self.clips[clip], "rb") as f:
                    body = f.read()
                ctype = "video/mp4" if clip.endswith(".mp4") else "video/webm;codecs=vp9,opus"
                code, d = self.jreq("POST", "/api/record/convert?fmt=%s&dur=3.00" % fmt, body=body, headers={"Content-Type": ctype})
                self.assertEqual(code, 200, d)
                self.assertEqual(d["source"]["video"], "h264" if clip.endswith(".mp4") else "vp9")
                done = self.wait_job(d["job"])
                self.assertEqual(done["state"], "done", done)
                self.assertEqual(done["percent"], 100.0)
                code, data, r = self.req("GET", "/api/record/job/%s/file?name=%s" % (d["job"], "My%20take.webm"))
                self.assertEqual(code, 200)
                self.assertEqual(r.getheader("Content-Type"), kr.MIME[fmt])
                self.assertIn("filename*=UTF-8''My%20take" + kr.EXT[fmt], r.getheader("Content-Disposition"))
                self.assertEqual(int(r.getheader("Content-Length")), len(data))
                v, a, dur = self.probe_out(data, fmt)
                self.assertEqual((v, a), (wv, wa))
                self.assertAlmostEqual(dur, 3.0, delta=0.5)
                self.assertEqual(self.rec_files(), [])                      # source + result both gone once sent
                self.assertEqual(self.jreq("GET", "/api/record/job/" + d["job"])[0], 404)

    @unittest.skipUnless(FF, "no ffmpeg here")
    def test_cancel_kills_ffmpeg_and_deletes(self):
        long_clip = os.path.join(self.tmp, "long.mp4")
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                        "-f", "lavfi", "-i", "sine", "-t", "40", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", long_clip],
                       check=True, timeout=300)
        with open(long_clip, "rb") as f:
            body = f.read()
        code, d = self.jreq("POST", "/api/record/convert?fmt=webm&dur=40", body=body, headers={"Content-Type": "video/mp4"})
        self.assertEqual(code, 200, d)
        job = kr.JOBS[d["job"]]
        t0 = time.time()
        while job.proc is None and time.time() - t0 < 10:
            time.sleep(0.05)
        proc = job.proc
        self.assertIsNotNone(proc)
        self.assertTrue(any(f.startswith("rec-" + d["job"]) for f in self.rec_files()))
        code, c = self.jreq("POST", "/api/record/job/%s/cancel" % d["job"])
        self.assertEqual((code, c["state"]), (200, "cancelled"))
        proc.wait(timeout=10)
        self.assertIsNotNone(proc.poll())
        t0 = time.time()
        while self.rec_files() and time.time() - t0 < 10:
            time.sleep(0.1)
        self.assertEqual(self.rec_files(), [])
        self.assertEqual(self.jreq("GET", "/api/record/job/" + d["job"])[0], 404)
        os.remove(long_clip)

    def test_sweep_stale_leftovers(self):
        os.makedirs(self.media, exist_ok=True)
        old = os.path.join(self.media, "rec-" + "b" * 32 + ".src.mp4")
        new = os.path.join(self.media, "rec-" + "c" * 32 + ".out.mp4")
        other = os.path.join(self.media, "d" * 32 + ".mp4")   # a media share's file is not ours
        for p in (old, new, other):
            with open(p, "wb") as f:
                f.write(b"x")
        t = time.time() - kr.STALE_S - 60
        os.utime(old, (t, t))
        os.utime(other, (t, t))
        self.assertEqual(kr.sweep(self.tmp), 1)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))
        self.assertTrue(os.path.exists(other))
        for p in (new, other):
            os.remove(p)
        j = kr.Job("e" * 32, "mp4", os.path.join(self.media, "rec-x.src"), os.path.join(self.media, "rec-x.out.mp4"), 1)
        j.state, j.finished = "done", time.time() - kr.KEEP_DONE_S - 5
        with open(j.dst, "wb") as f:
            f.write(b"x")
        kr.JOBS[j.id] = j
        kr.sweep(self.tmp)
        self.assertNotIn(j.id, kr.JOBS)
        self.assertFalse(os.path.exists(j.dst))


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = read("moq-watch-lite.html")

    def test_format_list_and_default(self):
        p = self.page
        m = re.search(r"const REC_FORMATS = \[(.*?)\n  \];", p, re.S)
        self.assertIsNotNone(m)
        ids = re.findall(r'\{ id: "(\w+)", label: "(\w+)", hint: "([^"]+)", ext: "(\.\w+)"', m.group(1))
        self.assertEqual([x[0] for x in ids], list(kr.FORMATS))
        self.assertEqual({x[0]: x[3] for x in ids}, kr.EXT)
        hints = {x[0]: x[2] for x in ids}
        self.assertEqual(hints["mp4"], "plays everywhere")
        self.assertEqual(hints["webm"], "as recorded, fastest")
        self.assertEqual(hints["mov"], "QuickTime / editing apps")
        self.assertEqual(hints["m4a"], "audio only")
        self.assertEqual(hints["mp3"], "audio only")
        self.assertIn('const REC_DEFAULT = "mp4";', p)
        self.assertIn("recPaintFormats(REC_DEFAULT);   // MP4 every time", p)
        self.assertIn('<div id="recFmts" role="radiogroup" aria-label="Format"></div>', p)
        self.assertIn('id="recCancel"', p)

    def test_recorder_prefers_mp4(self):
        p = self.page
        m = re.search(r"const mimes = \[(.*?)\];", p, re.S)
        mimes = re.findall(r'"([^"]+)"', m.group(1))
        self.assertEqual(mimes[0], "video/mp4;codecs=avc1.640028,mp4a.40.2")
        self.assertLess(mimes.index("video/mp4;codecs=avc1.640028,opus"), mimes.index("video/webm;codecs=vp9,opus"))
        self.assertIn("const vbps = /^video\\/mp4/i.test(mime) ? 5000000 : 4000000;", p)

    def test_convert_flow(self):
        p = self.page
        self.assertIn('xhr.open("POST", "/api/record/convert?fmt=" + f.id + "&dur="', p)
        self.assertIn("xhr.send(recPending.blob);", p)
        self.assertIn('"/api/record/job/" + job.job + "/file?name=" + encodeURIComponent(name)', p)
        self.assertIn("await r.body.pipeTo(w);", p)          # the result streams into the picked file
        self.assertIn("navigator.sendBeacon(u)", p)          # pagehide cancels a conversion
        self.assertIn('recProgress("Converting\\u2026 " + Math.floor(j.percent || 0) + " %"', p)
        self.assertIn('fetch("/api/record/formats", { cache: "no-store" })', p)

    def test_web_viewer_greys_what_needs_the_app(self):
        p = self.page
        self.assertIn('if ((window.__kastrClient?.class || "app") === "web") return { ffmpeg: false, web: true };', p)
        self.assertIn('return { ok: false, hint: "needs the KASTR app", asIs };', p)

    def test_record_announce_kept(self):
        p = self.page
        self.assertIn("window.__recAnnounce?.set?.(", p)
        self.assertIn("window.__recAnnounce?.clear?.()", p)

    def test_old_hardcoded_webm_gone(self):
        p = self.page
        self.assertNotIn('" MB \\u00b7 webm"', p)
        self.assertNotIn("function recDownloadNow()", p)


class Wiring(unittest.TestCase):
    def test_routes_and_build(self):
        s = read("kastr_serve.py")
        self.assertEqual(s.count("return kastr_record.handle_api(self, bridge, self._state_dir(), _note)"), 2)   # GET + POST
        self.assertIn('"--hidden-import", "kastr_record"', read("build.py"))


if __name__ == "__main__":
    unittest.main()
