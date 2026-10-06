"""0.21.21: NPU / GPU person matting + the WebGL2 effects renderer -- the rules that must not regress.

Run: python -m unittest tests.test_npu_fx
"""
import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class BrowserFlags(unittest.TestCase):
    def _args(self, platform):
        import kastr
        with mock.patch.object(kastr.sys, "platform", platform), mock.patch.object(kastr, "_is_root", return_value=False):
            return kastr.browser_args("chrome.exe", "http://127.0.0.1:8000/", "app.html")

    def test_one_enable_features_with_webnn(self):
        for plat in ("win32", "linux"):
            feats = [a for a in self._args(plat) if a.startswith("--enable-features=")]
            self.assertEqual(len(feats), 1, (plat, feats))   # Chromium honours only the last one
            self.assertIn("WebMachineLearningNeuralNetwork", feats[0])
            if plat == "linux":
                self.assertIn("VaapiVideoEncoder", feats[0])


class Assets(unittest.TestCase):
    def test_vendored_and_verified(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "vendor-npu.py"), "--check"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for lic in ("LICENSE-onnxruntime-web.txt", "LICENSE-modnet.txt"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "assets", "npu", lic)))

    def test_build_requires_them(self):
        self.assertIn('"assets", "npu", "manifest.json"', _read("build.py"))


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html")

    def test_ladder_and_fallbacks(self):
        p = self.p
        self.assertIn('const order = proc === "npu" ? ["npu"] : proc === "gpu" ? ["gpu"] : proc === "standard" ? [] : ["npu", "gpu"];', p)
        self.assertIn('executionProviders: [{ name: "webnn", deviceType: dev }]', p)
        self.assertIn("await modnetRun(m, m.cv);   // one run proves every op landed somewhere that works", p)
        self.assertIn('import("/assets/npu/ort.min.mjs")', p)   # never a CDN

    def test_renderer_has_a_2d_fallback(self):
        p = self.p
        self.assertIn('if (!gl || !gl.getExtension("EXT_color_buffer_float")) return null;', p)
        self.assertIn("} else if (needMask && b.haveMask && !glOut) {", p)
        self.assertIn("b.glFailed = true", p)

    def test_halo_free_blur(self):
        # the background is blurred weighted by (1 - matte) and the weight divided back out
        self.assertIn("o = vec4(texture(F, f).rgb * w, w);", self.p)
        self.assertIn("vec3 bg = bw.a > 0.002 ? bw.rgb / bw.a : c;", self.p)

    def test_frame_chain_never_breaks(self):
        # 0.21.21: the size-settle return used to end the requestVideoFrameCallback chain -- effects ran on the 120 ms
        # fallback timer (~8 fps, visibly late) from 0.21.5 until this fix
        p = self.p
        i = p.index("else { b.pendW = ow; b.pendH = oh;")
        self.assertIn("video.requestVideoFrameCallback(() => step(false))", p[i:i + 300])

    def test_launch_page_download_tiles(self):
        idx = _read("index.html")
        for t in ('id="dlWin" data-plat="win32"', 'id="dlLinux" data-plat="linux"', '"/api/update/zip?platform="'):
            self.assertIn(t, idx)
        self.assertIn('a.textContent = dlPlat(plat) + " ', self.p)   # About: the platform and its size only
        self.assertNotIn('" (prepared on the host when you click)"', self.p)

    def test_processor_setting_rides_every_bag(self):
        self.assertEqual(self.p.count('proc: ["auto", "npu", "gpu", "standard"].includes('), 2)
        self.assertIn('proc: camFx.proc || "auto" });', self.p)


if __name__ == "__main__":
    unittest.main()
