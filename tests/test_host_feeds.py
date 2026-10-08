# -*- coding: utf-8 -*-
"""v0.21.26 -- host feeds (Kenton: grids take "screen, window, tab, RTSP/HTTP, media file, etc"; Logan-ROC's camera "should
show for everyone and act similar to an RTSP stream, that can be put into a grid").

A camera on this computer (device://video/<name>) is captured ONCE and fanned out over loopback UDP, one port per reader;
a media file uploaded to this host (media://<id>) is looped at real time by each reader."""
import os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_rtsp as kr  # noqa: E402


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class Urls(unittest.TestCase):
    def test_kinds(self):
        self.assertTrue(kr.is_device("device://video/Integrated%20Webcam"))
        self.assertEqual(kr.device_name("device://video/Integrated%20Webcam"), "Integrated Webcam")
        self.assertTrue(kr.is_hostmedia("media://" + "a" * 32))
        self.assertFalse(kr.is_host_feed("rtsp://cam/1"))

    def test_each_reader_has_its_own_port(self):
        cap = kr.DeviceCapture("ffmpeg", "device://video/x")
        self.assertEqual(len(set(cap.ports.values())), 3)
        with mock.patch.dict(kr.DEVICES, {"device://video/x": cap}):
            pub = kr.input_args("device://video/x", role="pub")
            mon = kr.input_args("device://video/x", role="mon")
        self.assertIn("udp://127.0.0.1:%d" % cap.ports["pub"], pub[-1])
        self.assertIn("udp://127.0.0.1:%d" % cap.ports["mon"], mon[-1])

    def test_capture_fans_out_one_encode(self):
        cap = kr.DeviceCapture("ffmpeg", "device://video/Integrated Webcam")
        a = cap.args()
        self.assertEqual(a.count("-i"), 1)                 # the camera is opened once
        self.assertIn("tee", a)
        self.assertEqual(a[-1].count("udp://127.0.0.1:"), 2 + kr.MON_SLOTS)

    def test_media_file_loops_from_the_kept_copy(self):
        d = tempfile.mkdtemp()
        mid = "b" * 32
        open(os.path.join(d, mid + ".mp4"), "wb").close()
        with mock.patch.object(kr, "HOSTMEDIA_DIR", [d]):
            args = kr.input_args("media://" + mid)
        self.assertEqual(args[:4], ["-re", "-stream_loop", "-1", "-i"])
        self.assertTrue(args[-1].endswith(mid + ".mp4"))

    def test_bad_media_id_never_reaches_ffmpeg_as_a_path(self):
        with mock.patch.object(kr, "HOSTMEDIA_DIR", [tempfile.mkdtemp()]):
            self.assertIsNone(kr.hostmedia_path("media://../../etc/passwd"))


class RtmpIngest(unittest.TestCase):
    """0.21.29 (Kenton: an RTMP URL to point a GoPro at)."""

    def test_url_rules(self):
        self.assertEqual(kr.rtmp_parts("rtmp-in://1935/GoProTest42x"), (1935, "GoProTest42x"))
        for bad in ("rtmp-in://80/GoProTest42x", "rtmp-in://1935/../x", "rtmp-in://1935/ab"):
            self.assertEqual(kr.rtmp_parts(bad), (None, None), bad)
        self.assertTrue(kr.is_host_feed("rtmp-in://1935/GoProTest42x"))   # never from a web client

    def test_listener_copies_and_fans_out(self):
        cap = kr.DeviceCapture("ffmpeg", "rtmp-in://1936/GoProTest42x")
        a = cap.args()
        self.assertIn("-listen", a)
        self.assertIn("rtmp://0.0.0.0:1936/live/GoProTest42x", a)
        self.assertEqual(a[a.index("-c:a") + 1], "copy")             # the device's sound untouched
        # 0.21.31 (field: GoPro 'Live', "no video from the bridge"): the picture is re-encoded once with a keyframe every
        # second, so no reader waits for the device's own keyframe spacing
        self.assertEqual(a[a.index("-c:v") + 1], "libx264")
        self.assertIn("expr:gte(t,n_forced*1)", a)
        self.assertIn("0:a:0?", a)                         # the device's audio comes along
        self.assertEqual(a[-1].count("udp://127.0.0.1:"), 2 + kr.MON_SLOTS)

    def test_firewall_rule_covers_the_range(self):
        import kastr_relay
        self.assertIn("KASTR RTMP ingest", kastr_relay.FIREWALL_RULES)
        self.assertEqual(kastr_relay._port_list("1935-1944"), list(range(1935, 1945)))

    def test_any_box_opens_only_the_rtmp_ports(self):
        # 0.21.31 (Kenton: a box that is not the relay asks to open the firewall, no Relay page needed)
        import kastr_relay
        d = tempfile.mkdtemp()
        with mock.patch.object(kastr_relay, "_FIREWALL_DIR", d), mock.patch.object(kastr_relay.sys, "platform", "win32"), \
                mock.patch.object(kastr_relay.subprocess, "call", return_value=0):
            kastr_relay.firewall_remember("windows", [(4443, "udp"), (8001, "tcp")])   # an earlier relay add
            out = kastr_relay.add_rtmp_firewall()
            with open(os.path.join(d, "kastr-firewall.ps1"), encoding="utf-8") as f:
                script = f.read()
            rec = kastr_relay.firewall_record()
        self.assertTrue(out["ok"])
        self.assertIn("RTMP ingest", out["note"])
        self.assertEqual(script.count("New-NetFirewallRule"), 1)
        self.assertIn('-DisplayName "KASTR RTMP ingest" -Direction Inbound -Protocol TCP -LocalPort "1935-1944"', script)
        self.assertIn("4443/udp", rec["ports"])                 # the relay's ports stay remembered
        self.assertIn("1935/tcp", rec["ports"])
        with mock.patch.object(kastr_relay, "_FIREWALL_DIR", d):
            self.assertTrue(kastr_relay.rtmp_firewall_status()["open"])   # recorded -> no check, no nag

    def test_ingest_reports_whether_a_device_is_pushing(self):
        cap = kr.DeviceCapture("ffmpeg", "rtmp-in://1943/GoProTest42x")
        b = kr.Bridge(state_dir=tempfile.mkdtemp(), log=lambda *x: None)
        f = kr.Feed(1, cap.url, source_url=cap.url)
        b._feeds[1] = f
        with mock.patch.dict(kr.DEVICES, {cap.url: cap}):
            self.assertEqual(b.list()[0]["ingest"]["connected"], False)
            cap.connected_at = 123.0
            self.assertEqual(b.list()[0]["ingest"]["connected"], True)
        p = _read("moq-watch-lite.html")
        self.assertIn("if (slot.feed?.ingest && !slot.feed.ingest.connected) return null;", p)   # waiting is not failed
        self.assertIn("Waiting for the device to connect", p)
        self.assertIn("-loglevel", cap.args())
        self.assertEqual(cap.args()[cap.args().index("-loglevel") + 1], "info")   # the "Input #0" line marks the push

    def test_readers_analyse_longer_than_the_keyframe_spacing(self):
        self.assertEqual(kr.LOOP_IN[kr.LOOP_IN.index("-analyzeduration") + 1], "3000000")

    def test_page_asks_and_offers_a_button(self):
        p = _read("moq-watch-lite.html")
        self.assertIn('fetch("/api/screen/rtmp/firewall", { method: "POST" })', p)
        self.assertIn('if (fw && fw.open === false) {', p)
        self.assertIn('fwb.textContent = "Allow through firewall"', p)
        self.assertNotIn("add the firewall rules on the Relay page", p)
        s = _read("kastr_serve.py")
        self.assertIn('if path0 == "/api/screen/rtmp/firewall":', s)
        self.assertIn("out = kastr_relay.add_rtmp_firewall()", s)

    def test_page_offers_it(self):
        p = _read("moq-watch-lite.html")
        self.assertIn('id="hostRtmpAdd"', p)
        self.assertIn('addRtsp("rtmp-in://" + d.port + "/" + key', p)
        self.assertIn('"/api/screen/rtmp"', _read("kastr_serve.py"))


class LoopbackPorts(unittest.TestCase):
    """0.21.30 (field: a GoPro on RTMP ingest failed with 'bind failed: Error number -10048' on the monitor's port)."""

    def test_ports_avoid_the_ephemeral_ranges(self):
        cap = kr.DeviceCapture("ffmpeg", "rtmp-in://1937/GoProTest42x")
        ports = cap.out_ports()
        self.assertEqual(len(set(ports)), 2 + kr.MON_SLOTS)
        for p in ports:
            self.assertTrue(kr.LOOP_PORTS[0] <= p <= kr.LOOP_PORTS[1], p)

    def test_two_monitors_get_two_ports(self):
        cap = kr.DeviceCapture("ffmpeg", "rtmp-in://1938/GoProTest42x")
        with mock.patch.dict(kr.DEVICES, {cap.url: cap}):
            c1, c2 = {}, {}
            kr.input_args(cap.url, role="mon", claim=c1)
            kr.input_args(cap.url, role="mon", claim=c2)
        self.assertNotEqual(c1["port"], c2["port"])

    def test_a_held_port_is_skipped_and_a_finished_monitor_frees_its_slot(self):
        import socket
        cap = kr.DeviceCapture("ffmpeg", "rtmp-in://1939/GoProTest42x")
        squat = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        squat.bind(("127.0.0.1", cap.mon_ports[0]))   # something else holds slot 0 (a dying reader)
        try:
            p = cap.claim_mon()
        finally:
            squat.close()
        self.assertEqual(p, cap.mon_ports[1])
        done = mock.Mock()
        done.poll.return_value = 0                     # that monitor has exited
        cap.attach(p, done)
        self.assertEqual(cap.claim_mon(), cap.mon_ports[0])   # slot 0 is free again
        self.assertEqual(cap.claim_mon(), cap.mon_ports[1])   # and the exited one's slot is reused

    def test_all_slots_busy_says_so(self):
        cap = kr.DeviceCapture("ffmpeg", "rtmp-in://1940/GoProTest42x")
        for _ in cap.mon_ports:
            self.assertIsNotNone(cap.claim_mon())
        with mock.patch.dict(kr.DEVICES, {cap.url: cap}):
            with self.assertRaises(RuntimeError):
                kr.input_args(cap.url, role="mon")

    def test_a_restarted_pair_waits_for_the_old_ffmpeg(self):
        src = _read("kastr_rtsp.py")
        self.assertIn("p.wait(timeout=2)   # 0.21.30: gone before the next one binds the same loopback port", src)
        self.assertIn("p.wait(timeout=1)   # 0.21.30: its input (a loopback port, a camera) is free when the next pair starts", src)


class Bridge(unittest.TestCase):
    def test_a_web_client_never_adds_a_host_feed(self):
        self.assertIn('raise ValueError("a camera or media file on the host is added from the host itself")', _read("kastr_rtsp.py"))

    def test_upload_is_copied_into_hostmedia(self):
        st = tempfile.mkdtemp()
        os.makedirs(os.path.join(st, "media"))
        mid = "c" * 32
        with open(os.path.join(st, "media", mid + ".mp4"), "wb") as f:
            f.write(b"x")
        b = kr.Bridge(state_dir=st, log=lambda *a: None)
        self.assertTrue(b._hostmedia_ready("media://" + mid))
        self.assertTrue(os.path.exists(os.path.join(st, "hostmedia", mid + ".mp4")))


class Page(unittest.TestCase):
    def test_share_panel_offers_host_feeds(self):
        p = _read("moq-watch-lite.html")
        self.assertIn('id="hostCamSel"', p)
        self.assertIn('addRtsp("device://video/" + encodeURIComponent(sel.value)', p)
        self.assertIn('addRtsp("media://" + id', p)
        self.assertIn('"/api/screen/devices"', _read("kastr_serve.py"))

    def test_toolbar_camera_can_be_moved_into_a_grid(self):
        # 0.21.27 (Kenton, Logan-ROC): the toolbar camera has a Sources row whose picker moves it to a host feed
        p = _read("moq-watch-lite.html")
        self.assertIn("if (!IS_WEB2) camrowsEl.appendChild(cameraGridRow(a));", p)
        self.assertIn("removeSource(a.id);   // the webcam opens once", p)
        self.assertIn('addRtsp("device://video/" + encodeURIComponent(dev), { label:', p)


if __name__ == "__main__":
    unittest.main()
