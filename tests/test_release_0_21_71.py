"""v0.21.71 (Kenton 2026-10-15):
- "When sharing the camera, it takes about 1 second for the background video to show up and hide the actual background" -- until a
  picture / GIF / video background has loaded, the effect loop drew the person over a BLUR OF THE REAL ROOM. Now a stand-in (the
  background's thumbnail, else a dark fill), and the chosen video is loaded before the camera starts and kept between restarts.
- "I would like to build these videos and backgrounds into the video background options" -- 7 pictures + 7 videos in assets/bg.
- "update the video selector menu to look more like this" -- an Elgato-style picker: thumbnails, Off / Blur, a camera badge on
  moving backgrounds, 16 to a page with a pager, an Add split button and Blur strength.

Run: python -m unittest discover -s tests
"""
import json
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page():
    with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


class BuiltInBackgrounds(unittest.TestCase):
    def test_manifest_and_files(self):
        with open(os.path.join(HERE, "assets", "bg", "manifest.json"), encoding="utf-8") as f:
            m = json.load(f)
        ids = [e["id"] for e in m]
        self.assertEqual(len(ids), len(set(ids)))
        for want in ("elgato-lights", "gray-home-office", "light-blue-home-office", "livingroom-night", "office-space", "porch-sunset",
                     "room-morning", "clock", "coffee-shop", "lofi-bedroom", "news-room", "office", "rainy-window", "view"):
            self.assertIn(want, ids)
        for e in m:
            for k in ("file", "poster"):
                path = os.path.join(HERE, "assets", "bg", e[k])
                self.assertTrue(os.path.isfile(path), path)
            if e.get("type") == "image":
                self.assertTrue(e["file"].endswith(".jpg"))
            else:
                self.assertTrue(e["file"].endswith(".webm"))
        total = sum(os.path.getsize(os.path.join(HERE, "assets", "bg", n)) for n in os.listdir(os.path.join(HERE, "assets", "bg")))
        self.assertLess(total, 16 * 1024 * 1024)   # the release zip stays reasonable

    def test_pictures_are_pictures(self):
        p = page()
        self.assertIn('const still = s.type === "image";', p)
        self.assertIn('mode: still ? "image" : "video", url: "/assets/bg/" + s.file, thumb: poster, poster, anim: !still', p)


class NoRealRoom(unittest.TestCase):
    def test_stand_in_while_loading(self):
        p = page()
        self.assertIn('const standIn = !replaced && (mode === "image" || mode === "gif" || mode === "video");', p)
        self.assertIn('const glMode = needMask && b.haveMask ? (replaced || standIn ? "person" : "blur") : null;', p)
        self.assertIn("else if (standIn && b.poster) drawCover(cx, b.poster,", p)
        self.assertIn('else if (standIn) { cx.fillStyle = "#101820"; cx.fillRect(0, 0, ow, oh); }', p)

    def test_video_kept_and_prewarmed(self):
        p = page()
        self.assertIn("const fxBgVids = new Map();", p)
        self.assertIn("const v = fxBgVideo(real);   // 0.21.71: kept between camera restarts", p)
        self.assertIn('try { window.__fxBgPrewarm(JSON.parse(localStorage.getItem("kastr.camfx") || "null")); } catch {}', p)
        self.assertIn("try { window.__fxBgPrewarm?.(camFxWire()); } catch {}", p)
        self.assertEqual(p.count('if (![...fxBgVids.values()].includes(b.vid)) b.vid.removeAttribute?.("src");'), 2)   # a kept one only pauses

    def test_poster_rides_the_bag(self):
        p = page()
        self.assertIn('poster: /^' + chr(92) + '/assets' + chr(92) + '/bg' + chr(92) + '/[' + chr(92) + 'w.-]+$/.test(camFx.bg.poster || "") ? camFx.bg.poster : "" },', p)


class Picker(unittest.TestCase):
    def test_layout(self):
        p = page()
        self.assertIn('<div class="bgfoot"><div class="bgpager" id="bgPager"></div>', p)
        self.assertIn('id="bgAddBtn" class="bgaddm"', p)
        self.assertIn('<input type="range" id="fxBlurAmt" min="1" max="100"', p)
        self.assertIn("const BG_PAGE = 16;", p)
        self.assertIn('{ id: "none", label: "Off" }, { id: "blur", label: "Blur" }', p)
        self.assertIn('a.innerHTML = icon("cam"); a.title = "Moving background";', p)
        self.assertNotIn('{ id: "addAnim", label: "+ Add GIF / video" }', p)   # adding moved to the Add button

    def test_blur_strength(self):
        p = page()
        self.assertIn("blurAmt: fxBlurAmt(),   // 0.21.71", p)
        self.assertIn('const amtK = Math.max(1, Math.min(100, Number(fxNow.blurAmt) || 50)) / 50;', p)
        self.assertIn("blur2(T.Q1, T.Q2, Math.max(1, Math.min(16, rr)), rr > 16 ? 3 : 2);", p)
        self.assertIn('cx.filter = "blur(" + Math.round(14 * amtK) + "px)";', p)


if __name__ == "__main__":
    unittest.main()
