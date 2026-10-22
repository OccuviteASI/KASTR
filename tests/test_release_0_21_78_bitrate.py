# -*- coding: utf-8 -*-
"""0.21.78 (E): the zoomed relay showed a page's camera at ~16 bit/s (the relay's measure) next to "up ~500 kbit/s" (the
page's own figure). Lab (scratchpad v02178/E): both were right at their own moment -- an unwatched camera stops encoding at
once (@moq/publish runs the video encoder only while the relay asks for the track; the page's encoded bytes froze the second
its last viewer left), the relay's rate fell to catalog / keep-alive bytes within one ~30 s window, but the figure the map
showed came from a check-in up to a minute old. Now: the client checks in early when its figure moves (idle <-> sending, or
> 30 %), its upload counts the mic only while its track is live, the relay reconciles the two (the newer one wins, the map
says why) and anything under MESH_IDLE_BPS reads "idle" on both sides."""
import io, os, re, sys, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

PAT = "web-8a612695-b412"
CAM = "lab/%s/pat/camera.hang" % PAT
LIVE = "lab/%s/pat/Live-jq1d0p" % PAT


def rd(path):
    with io.open(os.path.join(HERE, path), encoding="utf-8") as f:
        return f.read()


def load(at, cam_bps, live_bps=38):
    return {"at": at, "paths": {"in": [{"path": CAM, "bps": cam_bps}, {"path": LIVE, "bps": live_bps}], "out": []}}


def client(up, at):
    return {"node": PAT, "name": "Pat", "kind": "web", "net": {"down": 0, "up": up, "streams": [], "at": at, "win": 15}}


class NetCheck(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(kr.mesh_net_check({"up": 514432, "at": 1792681410}, 512894, 1792681411), "")           # watched: -0.3 %
        self.assertEqual(kr.mesh_net_check({"up": 0, "at": 1792681470}, 0, 1792681475), "")                     # unwatched: both idle
        self.assertEqual(kr.mesh_net_check({"up": 1200, "at": 5}, 16, 9), "")                                   # idle = idle
        self.assertEqual(kr.mesh_net_check({"up": 504000, "at": 100}, 16, 150), "client-older")                 # the part C shot
        self.assertEqual(kr.mesh_net_check({"up": 0, "at": 1792681470}, 224450, 1792681459), "relay-older")      # just stopped
        self.assertEqual(kr.mesh_net_check({"up": 500000}, 16, 150), "differs")
        self.assertEqual(kr.mesh_net_check(None, 16, 150), "")
        self.assertEqual(kr.mesh_net_check({"up": None, "at": 1}, 16, 150), "")
        self.assertEqual(kr.mesh_net_check({"up": 500000, "at": 1}, None, 150), "")
        self.assertEqual(kr.mesh_net_check({"up": 560000, "at": 1}, 500000, 150), "")                          # within 25 %


class Zoom(unittest.TestCase):
    def zoom(self, c, ld):
        z = kr.mesh_zoom("labm8e-e", [c], ld)
        return z, z["clients"][0]

    def test_watched_agree(self):
        z, c = self.zoom(client(514432, 1792681410), load(1792681411, 512894))
        self.assertEqual((c["upNote"], c["upFrom"], c["upBps"]), ("", "client", 514432))
        self.assertEqual([s["idle"] for s in c["publishes"]], [False, True])        # the presence beacon is idle

    def test_unwatched_stale_checkin_is_not_shown_as_the_upload(self):
        # the part C anomaly: a check-in from before the camera's viewer left vs the relay's newer measure
        z, c = self.zoom(client(504000, 1000), load(1050, 16, 0))
        self.assertEqual((c["upNote"], c["upFrom"], c["upBps"]), ("client-older", "relay", 16))
        self.assertTrue(all(s["idle"] for s in c["publishes"]))
        z, c = self.zoom(client(0, 1060), load(1050, 16, 0))                         # it checked in again: idle both sides
        self.assertEqual((c["upNote"], c["upFrom"], c["upBps"]), ("", "client", 0))

    def test_relay_older(self):
        z, c = self.zoom(client(0, 1792681470), load(1792681459, 224450))
        self.assertEqual((c["upNote"], c["upFrom"], c["upBps"]), ("relay-older", "client", 0))

    def test_a_client_that_left_is_not_drawn_sending(self):
        # lab: Alex closed its page -- nothing of it on the relay any more, its last check-in (a minute old) said 503 kbit/s up
        alex = {"node": "web-5d0300c6-7fb1", "kind": "web", "net": {"down": 493000, "up": 503000, "at": 1000}}
        z, c = self.zoom(alex, load(1060, 0, 0))
        self.assertEqual((c["upNote"], c["upFrom"], c["upBps"], c["publishes"]), ("not-here", "relay", 0, []))
        # ... and its download: a minute-old 493 kbit/s while this relay now sends its clients nothing at all
        z, c = self.zoom(alex, dict(load(1060, 0, 0), local={"in": 0, "out": 157}))
        self.assertEqual((c["downNote"], c["downBps"]), ("client-older", 157))
        z, c = self.zoom(alex, dict(load(990, 0, 0), local={"in": 0, "out": 157}))  # the relay's sample is the older one
        self.assertEqual((c["downNote"], c["downBps"]), ("", 493000))
        z, c = self.zoom(alex, dict(load(1060, 0, 0), local={"in": 0, "out": 480000}))   # it fits what the relay sends
        self.assertEqual((c["downNote"], c["downBps"]), ("", 493000))
        z, c = self.zoom(alex, {"at": 1060})                                         # an older spoke: no per-stream figures
        self.assertEqual((c["upNote"], c["upFrom"], c["upBps"]), ("", "client", 503000))
        z, c = self.zoom(alex, None)
        self.assertEqual((c["upNote"], c["upBps"]), ("", 503000))

    def test_no_figure_and_viewer(self):
        z, c = self.zoom({"node": PAT, "kind": "box"}, load(10, 600000))
        self.assertEqual((c["upNote"], c["upFrom"], c["upBps"]), ("", "relay", 600038))   # an older KASTR: the relay's measure
        z, c = self.zoom({"node": "web-0000", "kind": "web", "net": {"down": 5, "up": 0, "at": 9}}, load(10, 600000))
        self.assertEqual((c["upNote"], c["upFrom"], c["upBps"]), ("", "client", 0))
        self.assertEqual(z["other"][0]["idle"], False)


class AppCheckin(unittest.TestCase):
    def test_net_moved(self):
        import kastr
        self.assertFalse(kastr.net_moved({"up": 514432, "down": 0}, {"up": 498000, "down": 0}))
        self.assertTrue(kastr.net_moved({"up": 514432, "down": 0}, {"up": 0, "down": 0}))           # stopped: idle now
        self.assertTrue(kastr.net_moved({"up": 0, "down": 0}, {"up": 300000, "down": 0}))
        self.assertTrue(kastr.net_moved({"up": 0, "down": 3400000}, {"up": 0, "down": 1900000}))     # > 30 %
        self.assertFalse(kastr.net_moved({"up": 0, "down": 100000}, {"up": 0, "down": 140000}))     # < 64 kbit/s
        self.assertTrue(kastr.net_moved(None, {"up": 1}))
        self.assertFalse(kastr.net_moved({"up": 1}, None))

    def test_wait_goes_early_when_the_figure_moved(self):
        import kastr
        clock = [0.0]

        def wait(s):
            clock[0] += s
            return False
        figs = iter([{"up": 514432}, {"up": 0}])
        with mock.patch.object(kastr.STOP, "wait", wait), mock.patch.object(kastr.time, "time", lambda: clock[0]), \
                mock.patch.object(kastr, "_checkin_net", lambda port: next(figs, {"up": 0})):
            self.assertFalse(kastr._checkin_wait(60, 8000, {"up": 514432}))
            self.assertEqual(clock[0], 15)                        # 5 s too soon to look, 10 s same figure, 15 s idle: now
            clock[0] = 0.0
            self.assertFalse(kastr._checkin_wait(60, 8000, None))  # no figure carried last time: the plain minute
            self.assertEqual(clock[0], 60)
        with mock.patch.object(kastr.STOP, "wait", lambda s: True):
            self.assertTrue(kastr._checkin_wait(60, 8000, {"up": 1}))


class Wiring(unittest.TestCase):
    def has(self, x, s):
        self.assertTrue(x in s, x[:120])

    def test_page(self):
        s = rd("moq-watch-lite.html")
        self.has("sentAudio:", s)                                                  # the mic's bytes + whether its track is live
        self.has("a.active && was.active", s)                                       # mic bytes only while live
        self.has("up: up + netAudioSent", s)
        self.has("function netMoved(a, b)", s)
        self.has("NET_IDLE_BPS = 2000", s)
        self.has("if (ciAt && Date.now() - ciAt >= 10000 && netMoved(ciNet, window.__netRate?.())) webCheckin();", s)   # the early check-in (+ the first figure)
        self.has("ciTimer = setTimeout(webCheckin, next)", s)

    def test_relay_page(self):
        s = rd("relay.html")
        self.has('const fmtRate = (b) => b != null && b < 2000 ? "idle" : fmtBps(b);', s)
        self.has("function meshUpNote(c)", s)
        for note in ("client-older", "relay-older", "not-here"):
            self.has('c.upNote === "%s"' % note, s)
        self.assertEqual(len(re.findall(r"c\.upBps !== undefined", s)), 2)              # node label + edge width
        self.assertEqual(len(re.findall(r"c\.downBps !== undefined", s)), 2)
        self.has("c.downNote ?", s)
        self.has("meshUpNote(c)", s.split("function meshClientTip(c)")[1].split("function meshCenterTip")[0])
        self.assertEqual(kr.MESH_IDLE_BPS, 2000)

    def test_line_endings(self):
        for p, crlf in (("moq-watch-lite.html", True), ("relay.html", True), ("kastr.py", True), ("kastr_relay.py", False)):
            with open(os.path.join(HERE, p), "rb") as f:
                b = f.read()
            self.assertEqual(b.count(b"\r\n") == b.count(b"\n"), crlf, p)


if __name__ == "__main__":
    unittest.main()
