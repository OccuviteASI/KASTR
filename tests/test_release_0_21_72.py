"""v0.21.72 (Kenton 2026-10-15: "In the video options, show a preview of the camera even if the camera is not enabled in the room."):
with the room camera off, the Video effects panel opens the chosen camera for itself and runs it through the same background effect
(a stand-alone loop with no publisher -- nothing is sent); it follows the effect and the device, and stops when the panel closes or
the room camera comes on.

Run: python -m unittest discover -s tests
"""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CameraPreview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            cls.p = f.read()

    def test_private_loop(self):
        p = self.p
        self.assertIn('const slot = { entry: { id: "fx-preview", kind: "camera", fx: fx || null }, publish: null, preview: true };', p)
        self.assertIn("st = await navigator.mediaDevices.getUserMedia({ video: deviceId ? { ...v, deviceId: { exact: deviceId } } : v, audio: false });", p)
        self.assertIn("window.__fxPreview = {", p)
        stop = p[p.index("  function fxPreviewStop() {"):p.index("  window.__fxPreview = {")]
        self.assertIn("stopBlur(pv.slot);", stop)
        self.assertIn("for (const t of pv.st.getTracks()) t.stop();", stop)   # the camera is released

    def test_panel_wiring(self):
        p = self.p
        self.assertIn('if (!tr) tr = camPreviewTrack(src?.deviceId ?? document.getElementById("joinCam")?.value ?? "");', p)
        self.assertIn("if (tr) camPreviewStop();   // the room camera is on: it is the preview", p)
        self.assertIn('new MutationObserver(() => { if (camPop.hidden) { camPreviewStop(); camPv.failed = false; } }).observe(camPop, { attributes: true, attributeFilter: ["hidden"] });', p)
        self.assertIn("var camPv = { dev: null, tr: null, busy: false, failed: false };", p)   # var: pushCamFx may run first
        self.assertIn("try { if (camPv?.tr) { const t = window.__fxPreview?.retune(camFxWire());", p)


if __name__ == "__main__":
    unittest.main()
