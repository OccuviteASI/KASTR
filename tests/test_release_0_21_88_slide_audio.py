# -*- coding: utf-8 -*-
"""v0.21.88 (Kenton, 2026-10-26: embedded AUDIO clips on slides "play the same way as videos"): a sound clip on a slide
follows the deck's start setting / delay / loop / volume, the presenter and backstage get Play / Pause / seek, viewers only
listen, it stops on the slide change, there is no tile, and PowerPoint's own speaker icon stays drawn as PowerPoint draws
it (gone when the deck says "Hide during show").

Covered here:
  * kastr_pres: a:audioFile (+ the p14:media extension) -> the slide's `videos` entry with kind "audio" (autoplay, delay,
    loop, volume read like a video's); the deck's file listed with kind "audio"; the icon kept, or left out for
    showWhenStopped="0"; a linked sound -> a warning that names the file and says how to embed it; WMA accepted (KASTR
    converts it as it plays); an unknown sound format (MIDI) -> a warning, nothing to play
  * the HTTP surface: the sound is pulled out like a video and served with its audio type to the converting page
  * the page: __presVideo shares a sound clip as sound only (no picture track, probed so WMA converts), named
    presentation_audio_<n> (hidden + heard like a slide's video); kastr-pres.js publishes it with k "a", never draws
    it, and the presenter view's button says "Play sound" """
import http.client
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))
os.environ["KASTR_PRES_POWERPOINT"] = "0"   # never the real PowerPoint from a test (this desk has it)
import kastr_pres as kp  # noqa: E402
import kastr_serve  # noqa: E402
from test_release_0_21_87_slide_video import NSD, OD, MS_MEDIA, PNG1, rels, slide, timing, title  # noqa: E402

_PP_ENV = [None]


def setUpModule():
    _PP_ENV[0] = os.environ.get("KASTR_PRES_POWERPOINT")
    os.environ["KASTR_PRES_POWERPOINT"] = "0"


def tearDownModule():
    if _PP_ENV[0] is None:
        os.environ.pop("KASTR_PRES_POWERPOINT", None)
    else:
        os.environ["KASTR_PRES_POWERPOINT"] = _PP_ENV[0]


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def audio_pic(spid, link="rId3", embed="rId2", icon="rId4", name="Sound"):
    ext = ('<p:extLst><p:ext uri="{DAA4B4D4-6D71-4841-9C94-3DA1FA4D0E7F}"><p14:media r:embed="%s"/></p:ext></p:extLst>' % embed) if embed else ""
    return ('<p:pic><p:nvPicPr><p:cNvPr id="%s" name="%s"><a:hlinkClick r:id="" action="ppaction://media"/></p:cNvPr><p:cNvPicPr/>'
            '<p:nvPr><a:audioFile r:link="%s"/>%s</p:nvPr></p:nvPicPr><p:blipFill><a:blip r:embed="%s"/></p:blipFill>'
            '<p:spPr><a:xfrm><a:off x="10668000" y="5715000"/><a:ext cx="457200" cy="457200"/></a:xfrm><a:prstGeom prst="rect"/></p:spPr></p:pic>'
            ) % (spid, name, link, ext, icon)


def atiming(spid, mode, loop=False, hide=False):
    x = timing(spid, mode, loop).replace("<p:video>", "<p:audio>").replace("</p:video>", "</p:audio>")
    return x.replace('<p:cMediaNode vol="80000">', '<p:cMediaNode vol="80000" showWhenStopped="0">') if hide else x


def make_audio_deck(mp3=b"ID3\x03fake-mp3", m4a=b"\x00\x00\x00\x18ftypM4A fake", wma=b"0&\xb2u-fake-wma"):
    """Slides (16:9):
      1 title only
      2 an MP3, Start: Automatically, loops, the speaker icon drawn
      3 an M4A, In click sequence, "Hide during show" (no icon on the slide)
      4 a LINKED sound (theme.mp3 beside the deck)
      5 a WMA, with previous (starts with the slide)
      6 a MIDI file (cannot play here)"""
    s = [slide(title("Intro")),
         slide(title("Auto sound") + audio_pic(4), atiming(4, "auto", loop=True)),
         slide(title("Click sound") + audio_pic(5, name="Hidden icon"), atiming(5, "click", hide=True)),
         slide(title("Linked sound") + audio_pic(4, embed=None, link="rId5"), atiming(4, "click")),
         slide(title("WMA") + audio_pic(6), atiming(6, "with")),
         slide(title("MIDI") + audio_pic(7), atiming(7, "click"))]
    media = {2: "media1.mp3", 3: "media2.m4a", 5: "media3.wma", 6: "media4.mid"}
    b = io.BytesIO()
    z = zipfile.ZipFile(b, "w")
    z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    z.writestr("_rels/.rels", rels([("rId1", OD + "officeDocument", "ppt/presentation.xml")]))
    z.writestr("ppt/presentation.xml", '<p:presentation %s><p:sldIdLst>%s</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/></p:presentation>'
               % (NSD, "".join('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, 11 + i) for i in range(len(s)))))
    z.writestr("ppt/_rels/presentation.xml.rels", rels([("rId%d" % (11 + i), OD + "slide", "slides/slide%d.xml" % (i + 1)) for i in range(len(s))]))
    for i, x in enumerate(s, 1):
        z.writestr("ppt/slides/slide%d.xml" % i, x)
        rl = []
        if i in media:
            rl += [("rId2", MS_MEDIA, "../media/" + media[i]), ("rId3", OD + "audio", "../media/" + media[i]), ("rId4", OD + "image", "../media/image1.png")]
        if i == 4:
            rl += [("rId5", OD + "audio", "file:///C:\\Users\\someone\\Music\\theme.mp3", True), ("rId4", OD + "image", "../media/image1.png")]
        z.writestr("ppt/slides/_rels/slide%d.xml.rels" % i, rels(rl))
    z.writestr("ppt/media/media1.mp3", mp3)
    z.writestr("ppt/media/media2.m4a", m4a)
    z.writestr("ppt/media/media3.wma", wma)
    z.writestr("ppt/media/media4.mid", b"MThd-fake")
    z.writestr("ppt/media/image1.png", PNG1)
    z.close()
    return b.getvalue()


class AudioScene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = kp.convert_pptx(make_audio_deck())

    def test_sound_clips_per_slide(self):
        sl = self.sc["slides"]
        a2 = sl[1]["videos"][0]
        self.assertEqual({k: a2[k] for k in ("id", "kind", "auto", "delay", "loop", "vol")},
                         {"id": "v0", "kind": "audio", "auto": True, "delay": 0, "loop": True, "vol": 0.8})
        a3 = sl[2]["videos"][0]
        self.assertEqual((a3["id"], a3["kind"], a3["auto"], a3["loop"]), ("v1", "audio", False, False))
        self.assertEqual((sl[4]["videos"][0]["kind"], sl[4]["videos"][0]["auto"]), ("audio", True))   # with previous: starts with the slide
        self.assertNotIn("videos", sl[5])   # MIDI: nothing to play
        json.dumps(self.sc)

    def test_icon_as_powerpoint_draws_it(self):
        pics = lambda i: [it for it in self.sc["slides"][i]["items"] if it["t"] == "pic"]
        self.assertEqual(len(pics(1)), 1)            # the speaker icon stays on the slide
        self.assertEqual(pics(1)[0]["x"], 10668000)
        self.assertEqual(pics(2), [])                # "Hide during show": no icon in the show

    def test_deck_files(self):
        v = self.sc["videos"]
        self.assertEqual({k: (v[k]["ext"], v[k]["type"], v[k]["kind"]) for k in v},
                         {"v0": (".mp3", "audio/mpeg", "audio"), "v1": (".m4a", "audio/mp4", "audio"), "v2": (".wma", "audio/x-ms-wma", "audio")})

    def test_linked_and_unknown_warn(self):
        self.assertEqual(self.sc["slides"][3]["videos"], [{"linked": "theme.mp3", "kind": "audio"}])
        w = " | ".join(self.sc["warnings"])
        self.assertIn("the sound theme.mp3 on slide 4 is linked to a file", w)
        self.assertIn("Insert > Audio > Audio on My PC", w)
        self.assertIn("a MID sound cannot be played here (save it as MP3 or M4A in PowerPoint)", w)
        self.assertNotIn("sound in slides does not play here", w)   # the 0.21.84 blanket warning is gone

    def test_timing_hide_flag(self):
        import xml.etree.ElementTree as ET
        self.assertTrue(kp.media_timing(ET.fromstring(slide("", atiming(5, "click", hide=True))))[1]["5"]["hide"])
        self.assertFalse(kp.media_timing(ET.fromstring(slide("", atiming(5, "click"))))[1]["5"]["hide"])


class Endpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kastr-presaud-srv-")
        cls.patch = mock.patch.object(kastr_serve, "STATE_DIR", cls.tmp)
        cls.patch.start()
        cls.nopp = mock.patch.object(kp, "powerpoint_enabled", return_value=False)   # no PowerPoint, whatever the env says
        cls.nopp.start()
        cls.globals = (kastr_serve._MEDIA_BRIDGE[0], kastr_serve.RTSP_BRIDGE[0])
        cls.srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True, bridge=None)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        kastr_serve._MEDIA_BRIDGE[0], kastr_serve.RTSP_BRIDGE[0] = cls.globals
        cls.nopp.stop()
        cls.patch.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": "127.0.0.1:%d" % self.port}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        hdrs = {k.lower(): v for k, v in r.getheaders()}
        c.close()
        return r.status, data, hdrs

    def test_sound_pulled_out_and_served(self):
        mp3 = b"ID3\x03" + os.urandom(3000)
        st, d, h = self.req("POST", "/api/pres/convert", make_audio_deck(mp3=mp3))
        self.assertEqual(st, 200, d[:300])
        j = json.loads(d)
        v0 = j["videos"]["v0"]
        self.assertRegex(v0["url"], r"^/api/pres/conv/[0-9a-f]{32}/v0\.mp3$")
        st, body, h = self.req("GET", v0["url"])
        self.assertEqual((st, h.get("content-type"), body), (200, "audio/mpeg", mp3))
        self.assertEqual(self.req("GET", j["videos"]["v2"]["url"])[2].get("content-type"), "audio/x-ms-wma")
        self.assertEqual(self.req("POST", "/api/pres/conv/%s/done" % j["job"], b"")[0], 200)
        self.assertEqual(self.req("GET", v0["url"])[0], 404)


class PageSeams(unittest.TestCase):
    def has(self, needle, hay, msg=None):
        self.assertTrue(needle in hay, msg or repr(needle)[:160])

    @classmethod
    def setUpClass(cls):
        cls.page = read("moq-watch-lite.html")
        cls.js = read(os.path.join("assets", "kastr-pres.js"))

    def test_sound_only_share(self):
        p = self.page
        hook = p[p.index("  window.__presVideo = {"):p.index("  async function presAttach(slot) {")]
        self.has("await prepareMediaFile(file, { noPicker: true, probe: !!o.audio })", hook)   # probed: a WMA is converted as it plays
        self.has('(o.audio ? "presentation_audio_" : "presentation_video_")', hook)
        self.has("audioOnly: !!o.audio", hook)
        self.has("if (!opt?.probe && !/", p)
        self.has("if (!entry.audioOnly) { try { pubCap(slot.publish)?.in?.source.set(vtrack); } catch {} }", p)   # no picture track
        self.has(r"const PRES_VID_RE = /\/presentation_(?:video|audio)(?:_[a-z0-9]+)?(?:-\d+)?\.hang$/;", p)   # hidden + heard

    def test_module(self):
        j = self.js
        self.has('kind: v.kind === "audio" ? "audio" : "video"', j)
        self.has('k: e.sv.kind === "audio" ? "a" : "v"', j)
        self.has('audio: sv.kind === "audio" }', j)
        frame = j[j.index("  function vidFrame() {"):j.index("  // ---- the loop")]
        self.has('!rec.blank && x.k !== "a"', frame)   # heard, never drawn
        self.has('e.sv.kind !== "audio"', j)
        self.has('x.st && x.k !== "a"', j)
        self.has('(lv.audio ? "sound" : "video")', j)


if __name__ == "__main__":
    unittest.main()
