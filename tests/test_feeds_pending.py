"""0.21.61 (Kenton: "RTMP URLs didn't stick after upgrading on the Support Laptop"): rtsp-feeds.json only shrinks on an
operator act. A kept feed read at launch stays on file until it is back on the air, removed, or un-kept -- a restore that
failed, one still on its way, or a Join that rewrites the file mid-restore never erases it. RTMP ingests (and host
cameras / files) are kept from the moment they are added; the RTMP listener dies with KASTR.

Run: python -m unittest discover -s tests
"""
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_rtsp  # noqa: E402

PAGE = os.path.join(HERE, "moq-watch-lite.html")
RTMP = "rtmp-in://1935/abcdef123456"
CAM = "rtsp://10.0.0.5/stream1"


def no_spawn(*a, **k):
    raise AssertionError("a process was spawned: %r" % (a[:1],))


class Pending(unittest.TestCase):
    def setUp(self):
        self._saved = [(kastr_rtsp.subprocess, "Popen", kastr_rtsp.subprocess.Popen),
                       (kastr_rtsp.Bridge, "legacy_sweep", kastr_rtsp.Bridge.legacy_sweep),
                       (kastr_rtsp.Bridge, "sweep_orphans", kastr_rtsp.Bridge.sweep_orphans)]
        kastr_rtsp.subprocess.Popen = no_spawn
        kastr_rtsp.Bridge.legacy_sweep = lambda self: 0
        kastr_rtsp.Bridge.sweep_orphans = lambda self: 0
        self.tmp = tempfile.TemporaryDirectory()
        doc = {"room": "support", "access": "", "roomCode": "", "relay": "http://10.0.0.2:4443",
               "feeds": [{"url": RTMP, "broadcast": "gopro", "keep": True, "label": "GoPro"},
                         {"url": CAM, "broadcast": "cam1", "keep": True, "label": "Door"},
                         {"url": "rtsp://10.0.0.9/x", "broadcast": "cam9", "keep": False}],
               "removed": [], "suspended": False}
        with open(os.path.join(self.tmp.name, "rtsp-feeds.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def tearDown(self):
        for obj, name, val in reversed(self._saved):
            setattr(obj, name, val)
        self.tmp.cleanup()

    def doc(self):
        with open(os.path.join(self.tmp.name, "rtsp-feeds.json"), encoding="utf-8") as f:
            return json.load(f)

    def bridge(self):
        return kastr_rtsp.Bridge(state_dir=self.tmp.name, log=lambda *a, **k: None)

    def test_a_rewrite_before_the_restore_keeps_the_kept_feeds(self):
        b = self.bridge()
        b.set_session("support", "", "", "http://10.0.0.2:4443")   # the page's Join, mid-restore
        urls = [f["url"] for f in self.doc()["feeds"]]
        self.assertIn(RTMP, urls)
        self.assertIn(CAM, urls)
        self.assertNotIn("rtsp://10.0.0.9/x", urls, "an un-kept feed is not carried")

    def test_a_removed_feed_is_not_pending(self):
        b = self.bridge()
        b._pending_drop(CAM)
        b._removed.append({"url": RTMP, "at": 1})
        b.persist_feeds()
        self.assertEqual([f["url"] for f in self.doc()["feeds"]], [])

    def test_shutdown_stops_the_listeners(self):
        b = self.bridge()
        stopped = []

        class Cap:
            def stop(self):
                stopped.append(1)
        kastr_rtsp.DEVICES[RTMP] = Cap()
        try:
            b.shutdown()
        finally:
            kastr_rtsp.DEVICES.pop(RTMP, None)
        self.assertEqual(stopped, [1])
        self.assertNotIn(RTMP, kastr_rtsp.DEVICES)


class PageKeepsIngests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PAGE, encoding="utf-8") as f:
            cls.p = f.read()

    def test_rtmp_ingest_is_always_kept(self):
        self.assertRegex(self.p, r'addRtsp\("rtmp-in://" \+ d\.port \+ "/" \+ key, \{[^}]*keep: true')

    def test_keep_is_recorded_before_the_first_publish(self):
        i = self.p.index("async function addRtsp(url, opts)")
        body = self.p[i:i + 4000]
        self.assertLess(body.index("if (opts?.keep) { rtspPersistSet("), body.index("const entry = addSource(RTSP"))

    def test_capture_joins_the_kill_job(self):
        with open(os.path.join(HERE, "kastr_rtsp.py"), encoding="utf-8") as f:
            src = f.read()
        i = src.index("class DeviceCapture")
        self.assertIn("_job_assign(app_job(self.log), self.proc, self.log)", src[i:i + 6000])


if __name__ == "__main__":
    unittest.main()
