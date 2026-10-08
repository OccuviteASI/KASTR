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
        self.assertEqual(a[-1].count("udp://127.0.0.1:"), 3)

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
