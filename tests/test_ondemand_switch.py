"""0.21.10: the on-demand / low-copy kill switch (kastr_rtsp.ONDEMAND_ENABLED).

Run: python -m unittest discover -s tests -t .   (build.py runs it before every build)

Off (the release default): a Publisher asked for on demand + a low copy is a plain full pair -- no standby, no
-low.hang sibling -- but remembers what was asked, and the stored record keeps those flags for a later re-enable.
The pair-reuse rule ignores the two flags while off, so a page re-posting its remembered flags never restarts a
healthy camera. On: today's 0.18.0 behaviour.
"""
import os
import sys
import tempfile
import threading
import types
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_rtsp  # noqa: E402


def feed_stub():
    return types.SimpleNamespace(id=1, url="test://pattern", source_url="test://pattern", sar=None, width=None,
                                 height=None, fullrange=False, h264=None, hevc=None)


def quiet_bridge():
    return types.SimpleNamespace(log=lambda *a, **k: None)


class SwitchOff(unittest.TestCase):
    def setUp(self):
        self.saved = kastr_rtsp.ONDEMAND_ENABLED
        kastr_rtsp.ONDEMAND_ENABLED = False

    def tearDown(self):
        kastr_rtsp.ONDEMAND_ENABLED = self.saved

    def test_publisher_is_a_plain_full_pair_but_remembers_the_request(self):
        p = kastr_rtsp.Publisher(quiet_bridge(), feed_stub(), "r/h/o/cam.hang", "http://127.0.0.1:4443",
                                 ondemand=True, low=True)
        self.assertFalse(p.ondemand)
        self.assertFalse(p.standby)
        self.assertIsNone(p.lowPub)
        self.assertTrue(p.wantOndemand)
        self.assertTrue(p.wantLow)
        info = p.info()
        self.assertFalse(info["ondemand"])
        self.assertFalse(info["standby"])
        self.assertFalse(info["lowLive"])
        self.assertIsNone(info["low"])
        self.assertEqual(info["role"], "main")
        # the stored record carries what was ASKED, not what took effect
        recs = kastr_rtsp.Bridge._feed_records(types.SimpleNamespace(_pubs={1: p}))
        self.assertEqual(len(recs), 1)
        self.assertTrue(recs[0]["ondemand"])
        self.assertTrue(recs[0]["low"])

    def test_reuse_ignores_inert_flags_and_no_demand_thread_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = kastr_rtsp.Bridge(state_dir=tmp, log=lambda *a, **k: None)
            b.moq = "moq"                        # publish() refuses without a moq binary; nothing is spawned below
            b.persist_feeds = lambda: None
            started = []
            saved_start = kastr_rtsp.Publisher.start
            kastr_rtsp.Publisher.start = lambda self: started.append(self.broadcast)
            try:
                feed = b.add("test://pattern")
                p1 = b.publish(feed.id, "r/h/o/cam.hang", "http://127.0.0.1:4443", audio=False, keep=True,
                               ondemand=True, low=True)
                p2 = b.publish(feed.id, "r/h/o/cam.hang", "http://127.0.0.1:4443", audio=False, keep=True,
                               ondemand=False, low=False)   # a page whose memory differs from the record
                self.assertIs(p1, p2)
                self.assertEqual(p2.reused, 1)
                self.assertEqual(started, ["r/h/o/cam.hang"])   # started once as a classic pair, never restarted
                self.assertIsNone(b._od_thread)
                self.assertNotIn("kastr-ondemand", [t.name for t in threading.enumerate()])
                b.unpublish(feed.id, persist=False)
            finally:
                kastr_rtsp.Publisher.start = saved_start


class SwitchOn(unittest.TestCase):
    def setUp(self):
        self.saved = kastr_rtsp.ONDEMAND_ENABLED
        kastr_rtsp.ONDEMAND_ENABLED = True

    def tearDown(self):
        kastr_rtsp.ONDEMAND_ENABLED = self.saved

    def test_publisher_sleeps_and_owns_a_low_sibling(self):
        p = kastr_rtsp.Publisher(quiet_bridge(), feed_stub(), "r/h/o/cam.hang", "http://127.0.0.1:4443",
                                 ondemand=True, low=True)
        self.assertTrue(p.ondemand)
        self.assertTrue(p.standby)
        self.assertIsNotNone(p.lowPub)
        self.assertEqual(p.lowPub.role, "low")
        self.assertEqual(p.lowPub.broadcast, "r/h/o/cam-low.hang")
        self.assertTrue(p.wantOndemand and p.wantLow)
        recs = kastr_rtsp.Bridge._feed_records(types.SimpleNamespace(_pubs={1: p}))
        self.assertTrue(recs[0]["ondemand"] and recs[0]["low"])

    def test_differing_flags_make_a_new_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = kastr_rtsp.Bridge(state_dir=tmp, log=lambda *a, **k: None)
            b.moq = "moq"
            b.persist_feeds = lambda: None
            saved_start = kastr_rtsp.Publisher.start
            kastr_rtsp.Publisher.start = lambda self: None
            saved_ensure = kastr_rtsp.Bridge._od_ensure
            kastr_rtsp.Bridge._od_ensure = lambda self: None     # no demand thread in a unit test
            saved_low = kastr_rtsp.Bridge._low_standby
            kastr_rtsp.Bridge._low_standby = lambda self, pub: None
            try:
                feed = b.add("test://pattern")
                p1 = b.publish(feed.id, "r/h/o/cam.hang", "http://127.0.0.1:4443", audio=False, keep=True,
                               ondemand=False, low=False)
                p2 = b.publish(feed.id, "r/h/o/cam.hang", "http://127.0.0.1:4443", audio=False, keep=True,
                               ondemand=True, low=True)
                self.assertIsNot(p1, p2)        # today's 0.18.0 compare: the flags matter while on
                b.unpublish(feed.id, persist=False)
            finally:
                kastr_rtsp.Publisher.start = saved_start
                kastr_rtsp.Bridge._od_ensure = saved_ensure
                kastr_rtsp.Bridge._low_standby = saved_low


if __name__ == "__main__":
    unittest.main()
