# -*- coding: utf-8 -*-
"""v0.21.87 (Kenton: "This powerpoint has a video in it, it doesn't appear to be working and I need that to be able to
function inside of KASTR."). Decided: "Play it on the slide" (KASTR pulls the video out of the .pptx and, while its slide
is live, plays it in the video's spot for everyone in the room, with sound, through the Share > Media file streaming) and
"Follow the deck" (it starts by itself when PowerPoint is set to play it automatically, otherwise the presenter or a
backstage person presses Play; viewers just see and hear it; a slide change stops it).

Covered here:
  * kastr_pres: video shapes (a:videoFile r:link + the p14:media r:embed extension) -> each slide's `videos` (box, autoplay,
    loop, name) and the deck's `videos` files; the poster stays the picture; the autoplay rule read from p:timing (main
    sequence, a click group that starts with the slide, with/after effect) vs on click and "when clicked on"; loop; a
    LINKED video (TargetMode External) -> a warning naming the file, nothing to play; hidden slides; unknown video formats
  * the HTTP surface: /api/pres/convert pulls the videos into the job folder, the converting page fetches them by the job
    id (also a web client), the bytes are the deck's own, done removes them, the PowerPoint path carries the videos too
  * the page seams: window.__presVideo (Media file pipeline, no size picker, paused unless autoplay, its own
    presentation_video.hang name), a slide's video never a tile of its own yet decoded and heard, never controlled by a
    viewer's ~mediactl pulse, no "share ended" at its end; kastr-pres.js: vids in the public record only for the live
    slide, Play / Pause / seek only from the presenter or its backstage people, the viewer path never fetches a video file
Lab (headless, scratchpad v02187): see the release notes."""
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import subprocess
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
from test_release_0_21_84_presentation import PNG1  # noqa: E402

_PP_ENV = [None]


def setUpModule():   # set again here: another module's tearDown may have restored the variable since this one was imported
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


# ---- a deck with videos ------------------------------------------------------------------------------------------------
NSD = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
       'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
       'xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main"')
OD = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
MS_MEDIA = "http://schemas.microsoft.com/office/2007/relationships/media"


def rels(items):
    """items: (id, full type, target[, external])"""
    out = []
    for it in items:
        ext = ' TargetMode="External"' if len(it) > 3 and it[3] else ""
        out.append('<Relationship Id="%s" Type="%s" Target="%s"%s/>' % (it[0], it[1], it[2], ext))
    return '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % "".join(out)


def video_pic(spid, x, y, w, h, link="rId3", embed="rId2", poster="rId4", name="Clip"):
    ext = ('<p:extLst><p:ext uri="{DAA4B4D4-6D71-4841-9C94-3DA1FA4D0E7F}"><p14:media r:embed="%s"/></p:ext></p:extLst>' % embed) if embed else ""
    vf = '<a:videoFile r:link="%s"/>' % link if link else ""
    blip = '<p:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>' % poster if poster else "<p:blipFill/>"
    return ('<p:pic><p:nvPicPr><p:cNvPr id="%s" name="%s"><a:hlinkClick r:id="" action="ppaction://media"/></p:cNvPr><p:cNvPicPr/>'
            '<p:nvPr>%s%s</p:nvPr></p:nvPicPr>%s<p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
            '<a:prstGeom prst="rect"/></p:spPr></p:pic>') % (spid, name, vf, ext, blip, x, y, w, h)


def timing(spid, mode, loop=False):
    """mode: 'auto' (Start: Automatically), 'click' (In click sequence), 'trigger' (When clicked on), 'with' (with previous,
    in the first auto group), 'none' (no play command at all)."""
    media = ('<p:video><p:cMediaNode vol="80000"><p:cTn id="20" fill="hold" display="0"%s><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst>'
             '</p:cTn><p:tgtEl><p:spTgt spid="%s"/></p:tgtEl></p:cMediaNode></p:video>') % (' repeatCount="indefinite"' if loop else "", spid)
    cmd = ('<p:cmd type="call" cmd="%s"><p:cBhvr><p:cTn id="6" dur="3000" fill="hold"/><p:tgtEl><p:spTgt spid="%s"/></p:tgtEl></p:cBhvr></p:cmd>')
    if mode == "trigger":
        seq = ('<p:seq concurrent="1" nextAc="seek"><p:cTn id="8" restart="whenNotActive" fill="hold" evtFilter="cancelBubble" nodeType="interactiveSeq">'
               '<p:stCondLst><p:cond evt="onClick" delay="0"><p:tgtEl><p:spTgt spid="%s"/></p:tgtEl></p:cond></p:stCondLst><p:childTnLst>'
               '<p:par><p:cTn id="9" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst><p:par><p:cTn id="10" fill="hold">'
               '<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst><p:par><p:cTn id="11" presetID="2" presetClass="mediacall" presetSubtype="0" '
               'fill="hold" nodeType="clickEffect"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>%s</p:childTnLst></p:cTn></p:par>'
               '</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn><p:nextCondLst><p:cond evt="onClick" delay="0">'
               '<p:tgtEl><p:spTgt spid="%s"/></p:tgtEl></p:cond></p:nextCondLst></p:seq>') % (spid, cmd % ("togglePause", spid), spid)
    elif mode == "none":
        seq = ""
    else:
        starts = '<p:cond delay="indefinite"/>' + ('<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond>' if mode in ("auto", "with") else "")
        node = {"auto": "afterEffect", "with": "withEffect", "click": "clickEffect"}[mode]
        seq = ('<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst><p:par><p:cTn id="3" fill="hold">'
               '<p:stCondLst>%s</p:stCondLst><p:childTnLst><p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
               '<p:par><p:cTn id="5" presetID="1" presetClass="mediacall" presetSubtype="0" fill="hold" nodeType="%s"><p:stCondLst><p:cond delay="0"/>'
               '</p:stCondLst><p:childTnLst>%s</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>'
               '</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
               '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>') % (starts, node, cmd % ("playFrom(0.0)", spid))
    return ('<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>%s%s</p:childTnLst></p:cTn></p:par>'
            '</p:tnLst></p:timing>') % (seq, media)


def title(text):
    return ('<p:sp><p:nvSpPr><p:cNvPr id="2" name="t"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="400000" y="200000"/>'
            '<a:ext cx="8000000" cy="800000"/></a:xfrm><a:prstGeom prst="rect"/></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r>'
            '<a:rPr lang="en-US" sz="3600"/><a:t>%s</a:t></a:r></a:p></p:txBody></p:sp>') % text


def slide(inner, tm="", show=True):
    return ('<p:sld %s%s><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>%s'
            '</p:spTree></p:cSld>%s</p:sld>') % (NSD, "" if show else ' show="0"', inner, tm)


def make_video_deck(mp4=b"\x00\x00\x00\x18ftypmp42not-a-real-video", poster=PNG1, wmv=None):
    """Slides (16:9, 12192000 x 6858000 EMU):
      1 title only
      2 the video, Start: Automatically, loops -- box (1219200, 1371600) 6096000 x 3429000
      3 the SAME video file, In click sequence (waits for Play)
      4 a LINKED video (clip-on-disk.mp4 beside the deck): a warning, nothing to play
      5 hidden, with a video (When clicked on)
      6 a WMV (converted as it plays) when given, else a title"""
    cx, cy = 12192000, 6858000
    vbox = (1219200, 1371600, 6096000, 3429000)
    s = [slide(title("Intro")),
         slide(title("Auto") + video_pic(4, *vbox), timing(4, "auto", loop=True)),
         slide(title("Click") + video_pic(5, 600000, 600000, 3000000, 1687500, name="Second"), timing(5, "click")),
         slide(title("Linked") + video_pic(4, *vbox, embed=None, link="rId5"), timing(4, "click")),
         slide(title("Hidden") + video_pic(4, *vbox), timing(4, "trigger"), show=False),
         slide(title("WMV") + (video_pic(7, *vbox, name="Old clip") if wmv else ""), timing(7, "with") if wmv else "")]
    b = io.BytesIO()
    z = zipfile.ZipFile(b, "w")
    z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    z.writestr("_rels/.rels", rels([("rId1", OD + "officeDocument", "ppt/presentation.xml")]))
    z.writestr("ppt/presentation.xml", '<p:presentation %s><p:sldIdLst>%s</p:sldIdLst><p:sldSz cx="%d" cy="%d"/></p:presentation>'
               % (NSD, "".join('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, 11 + i) for i in range(len(s))), cx, cy))
    z.writestr("ppt/_rels/presentation.xml.rels", rels([("rId%d" % (11 + i), OD + "slide", "slides/slide%d.xml" % (i + 1)) for i in range(len(s))]))
    for i, x in enumerate(s, 1):
        z.writestr("ppt/slides/slide%d.xml" % i, x)
        rl = []
        if i in (2, 3, 5):
            rl += [("rId2", MS_MEDIA, "../media/media1.mp4"), ("rId3", OD + "video", "../media/media1.mp4"), ("rId4", OD + "image", "../media/image1.png")]
        if i == 4:
            rl += [("rId5", OD + "video", "file:///C:\\Users\\someone\\Videos\\clip-on-disk.mp4", True), ("rId4", OD + "image", "../media/image1.png")]
        if i == 6 and wmv:
            rl += [("rId2", MS_MEDIA, "../media/media2.wmv"), ("rId3", OD + "video", "../media/media2.wmv"), ("rId4", OD + "image", "../media/image1.png")]
        z.writestr("ppt/slides/_rels/slide%d.xml.rels" % i, rels(rl))
    z.writestr("ppt/media/media1.mp4", mp4)
    z.writestr("ppt/media/image1.png", poster)
    if wmv:
        z.writestr("ppt/media/media2.wmv", wmv)
    z.close()
    return b.getvalue()


def ffmpeg():
    for root in (HERE, os.path.dirname(os.path.dirname(os.path.dirname(HERE)))):   # the worktree, then the main checkout
        for n in ("ffmpeg.exe", "ffmpeg"):
            p = os.path.join(root, "bin", n)
            if os.path.isfile(p) and (os.name == "nt") == n.endswith(".exe"):
                return p
    return shutil.which("ffmpeg")


def make_mp4(seconds=2, ff=None):
    """A real little H.264 + AAC clip (moving test pattern, a 440 Hz tone) from the bundled ffmpeg -- None without one."""
    ff = ff or ffmpeg()
    if not ff:
        return None
    d = tempfile.mkdtemp(prefix="kastr-vid-")
    out = os.path.join(d, "clip.mp4")
    try:
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi",
                        "-i", "sine=frequency=440:sample_rate=48000", "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-preset", "ultrafast", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", "-y", out],
                       check=True, capture_output=True, timeout=60)
        with open(out, "rb") as f:
            return f.read()
    except Exception:
        return None
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---- the converter -------------------------------------------------------------------------------------------------------
class Timing(unittest.TestCase):
    def t(self, xml):
        import xml.etree.ElementTree as ET
        return kp.media_timing(ET.fromstring(slide("", xml)))

    def test_autoplay_rule(self):
        auto = lambda xml: self.t(xml)[0]
        self.assertEqual(auto(timing(4, "auto")), {"4": 0})
        self.assertEqual(auto(timing(4, "with")), {"4": 0})
        self.assertEqual(auto(timing(4, "click")), {})     # In click sequence: waits for Play
        self.assertEqual(auto(timing(4, "trigger")), {})   # When clicked on: waits for Play
        self.assertEqual(auto(timing(4, "none")), {})
        self.assertEqual(self.t(""), ({}, {}))             # no timing at all (PowerPoint's default: on click)

    def test_delay_loop_and_volume(self):
        # Kenton's own deck (2026-10-26): Start: Automatically with a 1 s delay -- <p:cond delay="1000"/> on the effect
        xml = timing(6, "auto").replace('nodeType="afterEffect"><p:stCondLst><p:cond delay="0"/>', 'nodeType="afterEffect"><p:stCondLst><p:cond delay="1000"/>')
        self.assertEqual(self.t(xml)[0], {"6": 1000})
        self.assertEqual(self.t(timing(9, "auto", loop=True)), ({"9": 0}, {"9": {"loop": True, "vol": 0.8, "hide": False}}))   # 0.21.88: + hide
        self.assertEqual(self.t(timing(9, "click"))[1], {"9": {"loop": False, "vol": 0.8, "hide": False}})
        self.assertEqual(self.t(timing(9, "click").replace(' vol="80000"', ' vol="80000" mute="1"'))[1]["9"]["vol"], 0.0)
        self.assertEqual(self.t(timing(9, "click").replace(' vol="80000"', ""))[1]["9"]["vol"], 1.0)


class VideoScene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = kp.convert_pptx(make_video_deck())

    def test_videos_per_slide(self):
        sl = self.sc["slides"]
        self.assertEqual(len(sl), 6)
        self.assertNotIn("videos", sl[0])
        v2 = sl[1]["videos"]
        self.assertEqual(len(v2), 1)
        self.assertEqual({k: v2[0][k] for k in ("id", "x", "y", "w", "h", "auto", "delay", "loop", "vol")},
                         {"id": "v0", "x": 1219200, "y": 1371600, "w": 6096000, "h": 3429000, "auto": True, "delay": 0, "loop": True, "vol": 0.8})
        self.assertEqual(v2[0]["name"], "Clip")
        v3 = sl[2]["videos"]
        self.assertEqual((v3[0]["id"], v3[0]["auto"], v3[0]["loop"], v3[0]["name"]), ("v0", False, False, "Second"))   # the same file, once
        self.assertEqual(sl[4]["hidden"], True)
        self.assertEqual((sl[4]["videos"][0]["id"], sl[4]["videos"][0]["auto"]), ("v0", False))
        json.dumps(self.sc)

    def test_poster_stays_the_picture(self):
        pics = [it for it in self.sc["slides"][1]["items"] if it["t"] == "pic"]
        self.assertEqual(len(pics), 1)
        self.assertEqual((pics[0]["x"], pics[0]["w"]), (1219200, 6096000))
        self.assertTrue(self.sc["media"][pics[0]["m"]].startswith("data:image/png;base64,"))

    def test_deck_files(self):
        self.assertEqual(self.sc["videos"], {"v0": {"part": "ppt/media/media1.mp4", "ext": ".mp4", "type": "video/mp4",
                                                    "size": len(b"\x00\x00\x00\x18ftypmp42not-a-real-video"), "name": "media1.mp4", "kind": "video"}})   # 0.21.88: + kind
        self.assertNotIn("data:video", json.dumps(self.sc))   # never inline

    def test_linked_video_warns(self):
        sl = self.sc["slides"][3]
        self.assertEqual(sl["videos"], [{"linked": "clip-on-disk.mp4"}])
        w = [x for x in self.sc["warnings"] if "linked" in x]
        self.assertEqual(len(w), 1)
        self.assertIn("clip-on-disk.mp4", w[0])
        self.assertIn("slide 4", w[0])
        self.assertIn("Insert > Video > This Device", w[0])
        self.assertTrue([it for it in sl["items"] if it["t"] == "pic"])   # its poster is still drawn

    def test_no_old_blanket_warning(self):
        self.assertFalse([x for x in self.sc["warnings"] if "video and sound in slides do not play" in x])

    def test_no_poster_draws_a_black_box(self):
        d = make_video_deck()
        b = io.BytesIO()
        zin, zout = zipfile.ZipFile(io.BytesIO(d)), zipfile.ZipFile(b, "w")
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename == "ppt/slides/slide2.xml":
                data = data.replace(b'<p:blipFill><a:blip r:embed="rId4"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>', b"<p:blipFill/>")
            zout.writestr(it, data)
        zout.close()
        sc = kp.convert_pptx(b.getvalue())
        box = [it for it in sc["slides"][1]["items"] if it["t"] == "sp" and it.get("fill") == {"c": "#000000"}]
        self.assertEqual(len(box), 1)
        self.assertEqual(sc["slides"][1]["videos"][0]["id"], "v0")

    def test_wmv_and_unknown_formats(self):
        sc = kp.convert_pptx(make_video_deck(wmv=b"0&\xb2u-not-real"))
        self.assertEqual(sc["videos"]["v1"]["ext"], ".wmv")
        self.assertEqual(sc["slides"][5]["videos"][0]["auto"], True)   # with previous, in the group that starts with the slide
        d = make_video_deck().replace(b"x", b"x")
        b = io.BytesIO()
        zin, zout = zipfile.ZipFile(io.BytesIO(d)), zipfile.ZipFile(b, "w")
        for it in zin.infolist():
            data = zin.read(it.filename).replace(b"media1.mp4", b"media1.swf")
            zout.writestr(it.filename.replace("media1.mp4", "media1.swf"), data)
        zout.close()
        sc2 = kp.convert_pptx(b.getvalue())
        self.assertNotIn("videos", sc2)
        self.assertTrue(any("SWF video cannot be played" in w for w in sc2["warnings"]))


# ---- the HTTP surface ----------------------------------------------------------------------------------------------------
class Endpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kastr-presvid-srv-")
        cls.patch = mock.patch.object(kastr_serve, "STATE_DIR", cls.tmp)
        cls.patch.start()
        cls.nopp = mock.patch.object(kp, "powerpoint_enabled", return_value=False)   # belt and braces: no PowerPoint, whatever the env says
        cls.nopp.start()
        cls.globals = (kastr_serve._MEDIA_BRIDGE[0], kastr_serve.RTSP_BRIDGE[0])
        cls.srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True, bridge=None)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.mp4 = make_mp4() or (b"\x00\x00\x00\x18ftypmp42" + os.urandom(4000))

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

    def test_convert_pulls_the_videos_out(self):
        st, d, h = self.req("POST", "/api/pres/convert", make_video_deck(self.mp4), {"X-Kastr-Name": "video%20deck.pptx"})
        self.assertEqual(st, 200, d[:300])
        j = json.loads(d)
        self.assertEqual(j["kind"], "scene")
        v = j["videos"]["v0"]
        self.assertNotIn("part", v)
        self.assertRegex(v["url"], r"^/api/pres/conv/[0-9a-f]{32}/v0\.mp4$")
        self.assertEqual(j["job"], v["url"].split("/")[4])
        st, body, h = self.req("GET", v["url"])
        self.assertEqual((st, h.get("content-type"), h.get("cache-control")), (200, "video/mp4", "no-store"))
        self.assertEqual(hashlib.sha256(body).hexdigest(), hashlib.sha256(self.mp4).hexdigest())   # the deck's own bytes
        # a web client presenting through this relay host converts here too: the job id it alone holds is the key
        self.assertEqual(self.req("GET", v["url"], headers={"Origin": "https://relay.example", "Sec-Fetch-Site": "cross-site"})[0], 200)
        self.assertEqual(self.req("GET", "/api/pres/conv/%s/v0.mp4" % ("0" * 32))[0], 404)
        self.assertEqual(self.req("GET", "/api/pres/conv/%s/v0.exe" % j["job"])[0], 404)
        self.assertEqual(self.req("GET", "/api/pres/conv/%s/../v0.mp4" % j["job"])[0], 404)
        self.assertEqual(self.req("POST", "/api/pres/conv/%s/done" % j["job"], b"")[0], 200)
        self.assertEqual(self.req("GET", v["url"])[0], 404)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "pres-conv", j["job"])))

    def test_no_videos_no_job(self):
        from test_release_0_21_84_presentation import make_deck
        st, d, h = self.req("POST", "/api/pres/convert", make_deck())
        j = json.loads(d)
        self.assertEqual(st, 200)
        self.assertNotIn("videos", j)
        self.assertNotIn("job", j)

    def test_powerpoint_path_carries_the_videos(self):
        def fake(sc, t, run=None):   # PowerPoint's pictures for the five shown slides (slide 5 is hidden)
            m = re.search(r"Join-Path '([^']+)'", sc)
            for i in (1, 2, 3, 4, 6):
                with open(os.path.join(m.group(1).replace("''", "'"), "s%d.png" % i), "wb") as f:
                    f.write(PNG1)
            return mock.Mock(stderr=b"", returncode=0)
        with mock.patch.object(kp, "powerpoint_enabled", return_value=True), mock.patch.object(kp, "run_powershell", side_effect=fake):   # a FAKE PowerShell
            st, d, h = self.req("POST", "/api/pres/convert", make_video_deck(self.mp4))
        j = json.loads(d)
        self.assertEqual((st, j["kind"], j["via"]), (200, "images", "powerpoint"))
        self.assertEqual(j["slides"][1]["videos"][0]["auto"], True)
        self.assertEqual(j["slides"][3]["videos"], [{"linked": "clip-on-disk.mp4"}])
        self.assertTrue(j["videos"]["v0"]["url"].startswith("/api/pres/conv/%s/" % j["job"]))   # one job: the pictures + the video
        self.assertEqual(self.req("GET", j["videos"]["v0"]["url"])[0], 200)
        self.assertEqual(self.req("POST", "/api/pres/conv/%s/done" % j["job"], b"")[0], 200)

    def test_stash_without_storage(self):
        out = {"videos": {"v0": {"part": "ppt/media/media1.mp4", "ext": ".mp4"}}}
        kp.stash_videos(make_video_deck(), None, out)
        self.assertNotIn("videos", out)
        self.assertTrue(out["warnings"])


# ---- the page --------------------------------------------------------------------------------------------------------------
class PageSeams(unittest.TestCase):
    def has(self, needle, hay, msg=None):
        self.assertTrue(needle in hay, msg or repr(needle)[:160])

    def hasnt(self, needle, hay, msg=None):
        self.assertFalse(needle in hay, msg or repr(needle)[:160])

    @classmethod
    def setUpClass(cls):
        cls.page = read("moq-watch-lite.html")
        cls.js = read(os.path.join("assets", "kastr-pres.js"))

    def test_line_endings(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), "rb") as f:
            b = f.read()
        self.assertEqual(b.count(b"\n"), b.count(b"\r\n"))
        for n in ("kastr_pres.py", os.path.join("assets", "kastr-pres.js")):
            with open(os.path.join(HERE, n), "rb") as f:
                self.assertNotIn(b"\r\n", f.read())

    def test_media_file_pipeline_for_slide_videos(self):
        p = self.page
        hook = p[p.index("  window.__presVideo = {"):p.index("  async function presAttach(slot) {")]
        self.has("await prepareMediaFile(file, { noPicker: true, probe: !!o.audio })", hook)   # the same upload / convert-as-it-plays path, no size picker
        self.has("addSource(FILE, null, o.audio ? \"Presentation sound\" : \"Presentation video\"", hook)
        self.has('"presentation_video_"', hook)
        self.has("presVideo: true", hook)
        self.has("resume: { t: 0, paused: !o.auto }", hook)   # waits on its first frame unless the deck autoplays it
        self.has("const pickedH = opt?.noPicker ? 0 : await pickFileRes(f, probe);", p)
        self.has("const pickedH = opt?.noPicker ? 0 : await pickFileRes(f, wp);", p)
        self.has("if (slot.entry.presVideo) { announceMedia(slot, true); return; }", p)   # no "share ended" + Play again toast

    def test_viewers_cannot_drive_it(self):
        p = self.page
        self.has("mediaCtl: (meta) => ([...slots.values()].some((s2) => s2.entry.presVideo && chanPath(ensureHang(s2.entry.name)) === meta?.path) ? false : mediaCtl(meta)),", p)
        self.hasnt("\n    mediaCtl,   // 0.8.10", p)

    def test_hidden_tile_decoded_and_heard(self):
        p = self.page
        self.has(r"const PRES_VID_RE = /\/presentation_(?:video|audio)(?:_[a-z0-9]+)?(?:-\d+)?\.hang$/;", p)   # 0.21.88: + audio
        self.has('const leaf = (o.audio ? "presentation_audio_" : "presentation_video_") + (++presVidSeq).toString(36)', p)   # a fresh stream per visit: never an earlier visit's frame
        self.has("const roomHid = new (class extends Set { has(n) { return super.has(n) || isPresVid(n); } })();", p)
        self.has("const cgWarm = new (class extends Set { has(n) { return super.has(n) || isPresVid(n); } })();", p)   # keepWarm + never shed
        self.has("if (isPresVid(name)) return !(manualMute || mutedStreams.has(name));", p)
        self.has("&& !isPresVid(name)) ? \"never\"", p)
        self.has("window.__presVidFrame = (path) =>", p)
        kick = p[p.index("  window.__presVidKick = (path) => {"):p.index("  let vgRaf = 0, vgLast = 0;")]
        self.has("isPresVid(path) && tiles.get(String(path))", kick)   # only a slide's video stream is ever re-asked
        self.has('t.watch.removeAttribute("url");', kick)
        rx = re.compile(r"/presentation_(?:video|audio)(?:_[a-z0-9]+)?(?:-\d+)?\.hang$")
        self.assertTrue(rx.search("room/HOST/kenton-j/presentation_video.hang"))
        self.assertTrue(rx.search("room/HOST/kenton-j/presentation_video_1k3x9.hang"))
        self.assertTrue(rx.search("room/HOST/kenton-j/presentation_video-2.hang"))
        self.assertFalse(rx.search("room/HOST/kenton-j/presentation-video.hang"))   # a file someone named "Presentation video" stays a tile

    def test_module(self):
        j = self.js
        pub = j[j.index("  function publish() {"):j.index("  function goTo(")]
        self.has("vids: [...mine.vids.values()].filter((e) => e.path && e.i === mine.idx)", pub)   # only the live slide's
        self.hasnt("notes:", pub)
        go = j[j.index("  function goTo("):j.index("  async function postLive(")]
        self.has("syncVideos();", go)
        ai = j[j.index("  function applyIntent("):j.index("  let rewrapT = null;")]
        self.assertLess(ai.index("if (!b) return;"), ai.index("applyVidOp(ctl.vid, who)"))   # only the backstage people the presenter picked
        av = j[j.index("  function applyVidOp("):]
        self.has("x.i === mine.idx", av[:400])   # only the video of the slide live now
        self.has('["play", "pause", "seek"].includes(op.op)', av[:600])
        # viewers draw the stream, never fetch a video file; the presenter never uploads one to the slide store
        ov = j[j.index("  function syncOverlays("):j.index("  // ---- the presenter view")]
        self.hasnt("videoFile", ov)
        self.hasnt("/api/pres/conv", ov)
        frame = j[j.index("  function vidFrame() {"):j.index("  // ---- the loop")]
        self.has("x.i === rec.idx && x.st && x.p && !rec.blank", frame)
        self.has("window.__presVidFrame?.(x.p)", frame)
        wd = j[j.index("  function vidWatchdog("):j.index("  function vidFrame() {")]
        self.has("it.pl && now - s.at > 1500 && now - s.kickAt > 5000 && window.__presVidKick?.(it.p)", wd)   # a stopped picture while it plays: re-asked, rate-limited
        self.assertEqual(j.count("/api/pres/conv/"), 2)   # the job's done (PowerPoint + built-in) and nothing else: the video urls come from the server
        st = j[j.index("  async function startVid("):j.index("  function stopVid(")]
        self.has("const now = sv.auto && !(sv.delay > 0);", st)   # Start: Automatically with a delay -> played when the delay is up
        self.has('if (!e.gone && mine === m && !e.st) vidCtl(e, "play");', st)
        self.has("loop: !!sv.loop, vol: sv.vol, audio: sv.kind === \"audio\" }", st)
        self.has("gain: o.vol == null ? 1 : Math.max(0, Math.min(1, Number(o.vol)))", self.page)   # the player starts at the deck's volume
        sv = j[j.index("  function stopVid("):j.index("  function publishVid(")]
        self.hasnt("publish()", sv)   # a move publishes after the store heard of it, not before
        self.has("if (m && m.told >= m.pubSeq) publish();", j)

    def test_old_presentation_test_contract_kept(self):
        j = self.js
        self.assertEqual(j.count('"notes.bin"'), 2)
        ov = j[j.index("  async function paintOverlay("):j.index("  // ---- the presenter view")]
        self.hasnt("notes", ov)
        self.hasnt("cacheGet(", ov)


if __name__ == "__main__":
    unittest.main()
