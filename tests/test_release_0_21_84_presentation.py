# -*- coding: utf-8 -*-
"""v0.21.84 (Kenton: "start exploring using powerpoints, or other documents, directly inside of KASTR ... only
show the preview for those being casted to ... The person presenting and the 'backstage' person controlling need to see
the notes/slides upcoming as well as what is live while others only see the presentation.").

Share > Presentation (mode 1, KASTR renders the deck). Covered here:
  * kastr_pres: the .pptx -> scene converter (placeholders inherit the layout / master boxes and text styles, theme
    colours with lumMod/lumOff, bullets, notes, pictures as data: URLs, tables, groups, hidden slides), its refusals
    (not a zip, entity declarations, size caps), colour maths
  * the encrypted blob store: create / put / get / end, the presenter token, names, sizes, the 24 h sweep
  * the HTTP surface on a real kastr_serve server: /api/pres/new, a blob up and down (CORS + CORP cross-origin for
    other machines' pages), /api/pres/convert, /api/pres/office (this computer only), unknown routes
  * the PowerPoint COM export script (WithWindow false, read-only, quits only a PowerPoint it started) -- never run
  * the page seams (Share > Presentation row, the share hook, room.json pres / presCtl / presPk, memberApply /
    memberClear hooks, the people hook, no share PiP for a presentation) and assets/kastr-pres.js's guarantees
    (notes never in the public record, viewers open slides only with the live key, ECDH-wrapped backstage keys, the
    collision rule, no CDN, pdf.js only from /assets/vendor/pdfjs)
  * LIVE SLIDE ONLY for viewers (Kenton 2026-10-23): the store serves a reader without the deck's read token the live
    slide only (uncacheable), never the notes; the page keeps no earlier slide for a viewer; the API moves nothing
  * PowerPoint COM ON WHENEVER POWERPOINT IS INSTALLED (Kenton 2026-10-23) -- with a FAKE PowerShell only: this module
    sets KASTR_PRES_POWERPOINT=0 at import, so nothing here can start the real PowerPoint on a developer's desk
  * pdf.js: pdfjs-dist 6.4.299 pinned (sha256 + size) in vendor-pdfjs.py and assets/vendor/pdfjs/manifest.json,
    verified by build.py like assets/npu and assets/mediapipe; the two files git-ignored, the manifest tracked
  * build.py hidden import"""
import base64
import http.client
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
# never the real PowerPoint from a test (this desk has it): the COM path below runs a fake PowerShell
_PP_ENV = os.environ.get("KASTR_PRES_POWERPOINT")
os.environ["KASTR_PRES_POWERPOINT"] = "0"
import kastr_pres as kp  # noqa: E402
import kastr_serve  # noqa: E402
import build  # noqa: E402


def tearDownModule():
    if _PP_ENV is None:
        os.environ.pop("KASTR_PRES_POWERPOINT", None)
    else:
        os.environ["KASTR_PRES_POWERPOINT"] = _PP_ENV


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def raw(name):
    with open(os.path.join(HERE, name), "rb") as f:
        return f.read()


# ---- a small but real-shaped deck: master + layout + theme, three slides (the third hidden), notes ------------------
NSD = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
       'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
RELNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
PNG1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _rels(items):
    return ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join('<Relationship Id="%s" Type="%s%s" Target="%s"/>' % (i, RELNS, t, g) for i, t, g in items) + "</Relationships>")


def _tree(inner):
    return ('<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>%s'
            '</p:spTree></p:cSld>' % inner)


def _sp(ph="", xfrm="", body="", fill="", geom=""):
    return ('<p:sp><p:nvSpPr><p:cNvPr id="2" name="s"/><p:cNvSpPr/><p:nvPr>%s</p:nvPr></p:nvSpPr><p:spPr>%s%s%s</p:spPr>'
            '<p:txBody><a:bodyPr/><a:lstStyle/>%s</p:txBody></p:sp>') % (ph, xfrm, geom, fill, body or "<a:p/>")


def _x(x, y, w, h):
    return '<a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>' % (x, y, w, h)


def make_deck():
    theme = ('<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="t"><a:themeElements>'
             '<a:clrScheme name="c"><a:dk1><a:srgbClr val="111111"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
             '<a:dk2><a:srgbClr val="0B2545"/></a:dk2><a:lt2><a:srgbClr val="EEF2F7"/></a:lt2><a:accent1><a:srgbClr val="009FDA"/></a:accent1>'
             '<a:accent2><a:srgbClr val="F59E0B"/></a:accent2><a:accent3><a:srgbClr val="10B981"/></a:accent3><a:accent4><a:srgbClr val="EF4444"/></a:accent4>'
             '<a:accent5><a:srgbClr val="8B5CF6"/></a:accent5><a:accent6><a:srgbClr val="EC4899"/></a:accent6><a:hlink><a:srgbClr val="0563C1"/></a:hlink>'
             '<a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme><a:fontScheme name="f"><a:majorFont><a:latin typeface="Major Face"/></a:majorFont>'
             '<a:minorFont><a:latin typeface="Minor Face"/></a:minorFont></a:fontScheme><a:fmtScheme name="m"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
             '</a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:bgFillStyleLst>'
             '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
    master = ('<p:sldMaster %s><p:cSld><p:bg><p:bgPr><a:solidFill><a:schemeClr val="bg2"/></a:solidFill></p:bgPr></p:bg><p:spTree>'
              '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>' % NSD
              + _sp('<p:ph type="title"/>', _x(100, 200, 3000, 400))
              + _sp('<p:ph type="body" idx="1"/>', _x(100, 800, 3000, 2000))
              + _sp("", _x(0, 3900, 4000, 100), fill='<a:solidFill><a:schemeClr val="tx2"/></a:solidFill>', geom='<a:prstGeom prst="rect"/>')
              + '</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
              'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
              '<p:txStyles><p:titleStyle><a:lvl1pPr algn="ctr"><a:defRPr sz="4400" b="1"><a:solidFill><a:schemeClr val="tx2"/></a:solidFill>'
              '<a:latin typeface="+mj-lt"/></a:defRPr></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr marL="228600" indent="-228600"><a:buChar char="o"/>'
              '<a:defRPr sz="2800"><a:solidFill><a:schemeClr val="tx1"><a:lumMod val="50000"/></a:schemeClr></a:solidFill><a:latin typeface="+mn-lt"/></a:defRPr>'
              '</a:lvl1pPr></p:bodyStyle><p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>')
    layout = '<p:sldLayout %s>%s</p:sldLayout>' % (NSD, _tree(_sp('<p:ph type="title"/>') + _sp('<p:ph idx="1"/>')))
    r = lambda t: '<a:r><a:rPr lang="en-US"/><a:t>%s</a:t></a:r>' % t
    s1 = '<p:sld %s>%s</p:sld>' % (NSD, _tree(_sp('<p:ph type="title"/>', body="<a:p>%s</a:p>" % r("Hello deck"))
                                             + _sp('<p:ph idx="1"/>', body="<a:p>%s</a:p><a:p>%s</a:p>" % (r("first point"), r("second point")))))
    pic = ('<p:pic><p:nvPicPr><p:cNvPr id="5" name="p"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rId3"/>'
           '<a:srcRect l="10000" r="10000"/></p:blipFill><p:spPr>%s<a:prstGeom prst="ellipse"/></p:spPr></p:pic>') % _x(2000, 1000, 1000, 1000)
    grp = ('<p:grpSp><p:nvGrpSpPr><p:cNvPr id="6" name="g"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="1000" y="3000"/>'
           '<a:ext cx="2000" cy="500"/><a:chOff x="0" y="0"/><a:chExt cx="200" cy="50"/></a:xfrm></p:grpSpPr>%s</p:grpSp>') % _sp(
        "", _x(100, 0, 100, 50), fill='<a:solidFill><a:schemeClr val="accent2"/></a:solidFill>', geom='<a:prstGeom prst="roundRect"/>')
    tbl = ('<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="7" name="t"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="0" y="0"/>'
           '<a:ext cx="2000" cy="600"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblGrid>'
           '<a:gridCol w="1000"/><a:gridCol w="1000"/></a:tblGrid><a:tr h="300"><a:tc><a:txBody><a:bodyPr/><a:p>%s</a:p></a:txBody><a:tcPr>'
           '<a:solidFill><a:schemeClr val="accent1"/></a:solidFill></a:tcPr></a:tc><a:tc><a:txBody><a:bodyPr/><a:p>%s</a:p></a:txBody><a:tcPr/></a:tc></a:tr>'
           '</a:tbl></a:graphicData></a:graphic></p:graphicFrame>') % (r("A"), r("B"))
    chart = ('<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="8" name="c"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="0" y="0"/>'
             '<a:ext cx="500" cy="500"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"/></a:graphic></p:graphicFrame>')
    s2 = '<p:sld %s>%s</p:sld>' % (NSD, _tree(pic + grp + tbl + chart))
    s3 = '<p:sld %s show="0">%s</p:sld>' % (NSD, _tree(_sp('<p:ph type="title"/>', body="<a:p>%s</a:p>" % r("Hidden"))))
    notes1 = '<p:notes %s>%s</p:notes>' % (NSD, _tree(_sp('<p:ph type="sldImg"/>') + _sp('<p:ph type="body" idx="1"/>',
                                                                                           body="<a:p>%s</a:p><a:p>%s<a:br/>%s</a:p>" % (r("Say SECRET one"), r("line"), r("two")))))
    b = io.BytesIO()
    z = zipfile.ZipFile(b, "w")
    z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    z.writestr("_rels/.rels", _rels([("rId1", "officeDocument", "ppt/presentation.xml")]))
    z.writestr("ppt/presentation.xml", '<p:presentation %s><p:sldIdLst><p:sldId id="256" r:id="rId11"/><p:sldId id="257" r:id="rId12"/>'
               '<p:sldId id="258" r:id="rId13"/></p:sldIdLst><p:sldSz cx="4000" cy="4000"/></p:presentation>' % NSD)
    z.writestr("ppt/_rels/presentation.xml.rels", _rels([("rId11", "slide", "slides/slide1.xml"), ("rId12", "slide", "slides/slide2.xml"),
                                                         ("rId13", "slide", "slides/slide3.xml")]))
    for n, s in ((1, s1), (2, s2), (3, s3)):
        z.writestr("ppt/slides/slide%d.xml" % n, s)
        rl = [("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")]
        if n == 1:
            rl.append(("rId2", "notesSlide", "../notesSlides/notesSlide1.xml"))
        if n == 2:
            rl.append(("rId3", "image", "../media/image1.png"))
        z.writestr("ppt/slides/_rels/slide%d.xml.rels" % n, _rels(rl))
    z.writestr("ppt/media/image1.png", PNG1)
    z.writestr("ppt/notesSlides/notesSlide1.xml", notes1)
    z.writestr("ppt/slideLayouts/slideLayout1.xml", layout)
    z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _rels([("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")]))
    z.writestr("ppt/slideMasters/slideMaster1.xml", master)
    z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _rels([("rId1", "theme", "../theme/theme1.xml")]))
    z.writestr("ppt/theme/theme1.xml", theme)
    z.close()
    return b.getvalue()


class Colours(unittest.TestCase):
    def test_lum_mod_and_off(self):
        self.assertEqual(kp.apply_color_mods("FFFFFF", [("lumMod", 0.5)])[0], "#808080")
        self.assertEqual(kp.apply_color_mods("000000", [("lumOff", 1.0)])[0], "#ffffff")
        self.assertEqual(kp.apply_color_mods("FF0000", [("alpha", 0.5)]), ("#ff0000", 0.5))
        self.assertEqual(kp.css_color("#ff0000", 0.5), "rgba(255,0,0,0.500)")

    def test_tint_shade(self):
        self.assertEqual(kp.apply_color_mods("000000", [("tint", 0.0)])[0], "#ffffff")
        self.assertEqual(kp.apply_color_mods("FFFFFF", [("shade", 0.5)])[0], "#808080")


class Converter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = kp.convert_pptx(make_deck())

    def test_shape_of_the_scene(self):
        sc = self.sc
        self.assertEqual((sc["kind"], sc["w"], sc["h"], len(sc["slides"])), ("scene", 4000, 4000, 3))
        self.assertEqual([s["hidden"] for s in sc["slides"]], [False, False, True])
        json.dumps(sc)   # plain JSON for the page

    def test_placeholders_inherit_boxes_and_styles(self):
        s1 = self.sc["slides"][0]
        self.assertEqual(s1["bg"], {"c": "#eef2f7"})   # master bg2 -> lt2
        texts = [it for it in s1["items"] if it.get("tx")]
        title, body = texts[0], texts[1]
        self.assertEqual((title["x"], title["y"], title["w"], title["h"]), (100, 200, 3000, 400))   # from the master
        self.assertEqual((body["x"], body["y"]), (100, 800))
        r0 = title["tx"]["ps"][0]["rs"][0]
        self.assertEqual((r0["t"], r0["sz"], r0.get("b"), r0["c"], r0["f"]), ("Hello deck", 4400, 1, "#0b2545", "Major Face"))
        self.assertEqual(title["tx"]["ps"][0]["al"], "ctr")
        p0 = body["tx"]["ps"][0]
        self.assertEqual(p0["bu"]["c"], "o")
        self.assertEqual((p0["ml"], p0["ind"]), (228600, -228600))
        self.assertEqual(p0["rs"][0]["c"], "#080808")   # tx1 (111111) at lumMod 50 %
        self.assertEqual(p0["rs"][0]["f"], "Minor Face")
        deco = [it for it in s1["items"] if it.get("fill") and not it.get("tx")]
        self.assertTrue(any(d["fill"] == {"c": "#0b2545"} for d in deco), "the master's band is drawn under the slide")

    def test_notes(self):
        self.assertEqual(self.sc["slides"][0]["notes"], "Say SECRET one\nline\ntwo")
        self.assertEqual(self.sc["slides"][1]["notes"], "")

    def test_pictures_tables_groups(self):
        items = self.sc["slides"][1]["items"]
        pic = next(it for it in items if it["t"] == "pic")
        self.assertTrue(self.sc["media"][pic["m"]].startswith("data:image/png;base64,"))
        self.assertEqual(pic["crop"], [0.1, 0.0, 0.1, 0.0])
        self.assertEqual(pic["geom"]["prst"], "ellipse")
        grp = [it for it in items if it["t"] == "sp" and it.get("geom", {}).get("prst") == "roundRect"][0]
        self.assertEqual((grp["x"], grp["y"], grp["w"], grp["h"]), (2000.0, 3000.0, 1000.0, 500.0))   # child space x10
        self.assertEqual(grp["fill"], {"c": "#f59e0b"})
        tbl = next(it for it in items if it["t"] == "tbl")
        self.assertEqual(tbl["cols"], [1000, 1000])
        self.assertEqual(tbl["rows"][0]["cells"][0]["fill"], "#009fda")
        self.assertEqual(tbl["rows"][0]["cells"][1]["tx"]["ps"][0]["rs"][0]["t"], "B")
        self.assertTrue(any("chart" in w for w in self.sc["warnings"]), self.sc["warnings"])

    def test_refusals(self):
        with self.assertRaises(kp.ConvertError):
            kp.convert_pptx(b"not a zip at all")
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("ppt/presentation.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')
        with self.assertRaises(kp.ConvertError):
            kp.convert_pptx(b.getvalue())
        with mock.patch.object(kp, "CONVERT_MAX", 10):
            with self.assertRaises(kp.ConvertError):
                kp.convert_pptx(make_deck())
        b2 = io.BytesIO()
        with zipfile.ZipFile(b2, "w") as z:
            z.writestr("ppt/presentation.xml", '<p:presentation %s/>' % NSD)
        with self.assertRaises(kp.ConvertError):   # no slides
            kp.convert_pptx(b2.getvalue())

    def test_notes_only(self):
        self.assertEqual(kp.notes_only(make_deck())[0], "Say SECRET one\nline\ntwo")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr-pres-")
        self.st = kp.Store(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_round_trip_and_token(self):
        did, tok, rtok = self.st.create("room1", "deck", 3)
        self.assertRegex(did, r"^[0-9a-f]{32}$")
        self.assertNotEqual(tok, rtok)
        self.assertEqual(self.st.put(did, "wrong", "s0.bin", io.BytesIO(b"x" * 10), 10)[0], 403)
        self.assertEqual(self.st.put(did, tok, "s0.bin", io.BytesIO(b"x" * 10), 10), (200, "ok"))
        with open(self.st.path(did, "s0.bin"), "rb") as f:
            self.assertEqual(f.read(), b"x" * 10)
        self.assertEqual(self.st.put(did, tok, "../meta.json", io.BytesIO(b"x"), 1)[0], 404)
        self.assertEqual(self.st.put(did, tok, "meta.json", io.BytesIO(b"x"), 1)[0], 404)
        self.assertEqual(self.st.put(did, tok, "s1.bin", io.BytesIO(b"xy"), 5)[0], 400)   # short upload
        self.assertIsNone(self.st.path(did, "s1.bin"))
        self.assertIsNone(self.st.path(did, "meta.json"))
        self.assertEqual(self.st.end(did, "wrong"), 403)
        self.assertEqual(self.st.end(did, tok), 200)
        self.assertIsNone(self.st.path(did, "s0.bin"))

    def test_limits(self):
        did, tok, rtok = self.st.create("r", "d", 1)
        with mock.patch.object(kp, "STORE_BLOB_MAX", 5):
            self.assertEqual(self.st.put(did, tok, "s0.bin", io.BytesIO(b"x" * 6), 6)[0], 413)
        with mock.patch.object(kp, "STORE_DECK_MAX", 8):
            self.assertEqual(self.st.put(did, tok, "s0.bin", io.BytesIO(b"x" * 6), 6)[0], 200)
            self.assertEqual(self.st.put(did, tok, "s1.bin", io.BytesIO(b"x" * 6), 6)[0], 413)
        with mock.patch.object(kp, "STORE_DECKS_MAX", 1):
            with self.assertRaises(ValueError):
                self.st.create("r", "d", 1)

    def test_sweep_after_a_day(self):
        did, tok, rtok = self.st.create("r", "d", 1, now=time.time() - kp.STORE_TTL_S - 5)
        self.assertEqual(self.st.sweep(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "pres", did)))

    def test_live_slide_only_without_the_read_token(self):
        did, tok, rtok = self.st.create("r", "d", 5)
        self.assertEqual(self.st.readable(did, "s0.bin", ""), (True, False))   # slide 1 is live from the start
        self.assertEqual(self.st.readable(did, "s1.bin", ""), (False, False))
        self.assertEqual(self.st.readable(did, "notes.bin", ""), (False, False))
        self.assertEqual(self.st.readable(did, "s3.bin", "wrong"), (False, False))
        self.assertEqual(self.st.readable(did, "s3.bin", rtok), (True, True))
        self.assertEqual(self.st.readable(did, "notes.bin", rtok), (True, True))
        self.assertEqual(self.st.set_live(did, "wrong", 3), 403)
        self.assertEqual(self.st.set_live(did, rtok, 3), 403)   # the read token cannot move the slides
        self.assertEqual(self.st.set_live(did, tok, 3), 200)
        self.assertEqual(self.st.readable(did, "s3.bin", ""), (True, False))
        self.assertEqual(self.st.readable(did, "s0.bin", ""), (False, False))   # no paging back
        self.assertEqual(self.st.set_live("0" * 32, tok, 1), 404)


class Endpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kastr-pres-srv-")
        cls.patch = mock.patch.object(kastr_serve, "STATE_DIR", cls.tmp)
        cls.patch.start()
        cls.globals = (kastr_serve._MEDIA_BRIDGE[0], kastr_serve.RTSP_BRIDGE[0])
        cls.srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True, bridge=None)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        kastr_serve._MEDIA_BRIDGE[0], kastr_serve.RTSP_BRIDGE[0] = cls.globals
        cls.patch.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Host": "127.0.0.1:%d" % self.port}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        hdrs = {k.lower(): v for k, v in r.getheaders()}
        c.close()
        return r.status, data, hdrs

    def test_store_round_trip_cross_origin(self):
        st, d, h = self.req("POST", "/api/pres/new", json.dumps({"room": "r1", "name": "Deck", "n": 2}), {"Content-Type": "application/json"})
        self.assertEqual(st, 200, d)
        j = json.loads(d)
        self.assertIn("rtoken", j)
        st, d, h = self.req("POST", "/api/pres/%s/s0.bin?token=%s" % (j["id"], j["token"]), b"\x01\x02\x03")
        self.assertEqual(st, 200, d)
        st, d, h = self.req("POST", "/api/pres/%s/s1.bin?token=nope" % j["id"], b"\x01")
        self.assertEqual(st, 403)
        st, d, h = self.req("GET", "/api/pres/%s/s0.bin" % j["id"], headers={"Origin": "http://10.0.0.9:8000"})
        self.assertEqual((st, d), (200, b"\x01\x02\x03"))
        self.assertEqual(h.get("access-control-allow-origin"), "*")
        self.assertEqual(h.get("cross-origin-resource-policy"), "cross-origin")
        self.assertEqual(h.get("cache-control"), "no-store")   # a viewer's copy of the live slide is not kept
        st, d, h = self.req("POST", "/api/pres/%s/s1.bin?token=%s" % (j["id"], j["token"]), bytes([4, 5]))
        self.assertEqual(st, 200)
        st, d, h = self.req("POST", "/api/pres/%s/notes.bin?token=%s" % (j["id"], j["token"]), bytes([9]))
        self.assertEqual(st, 200)
        self.assertEqual(self.req("GET", "/api/pres/%s/s1.bin" % j["id"])[0], 403)   # not live
        self.assertEqual(self.req("GET", "/api/pres/%s/notes.bin" % j["id"])[0], 403)   # never for a viewer
        st, d, h = self.req("GET", "/api/pres/%s/s1.bin?rt=%s" % (j["id"], j["rtoken"]))   # backstage
        self.assertEqual((st, d), (200, bytes([4, 5])))
        self.assertIn("immutable", h.get("cache-control", ""))
        self.assertEqual(self.req("GET", "/api/pres/%s/notes.bin?rt=%s" % (j["id"], j["rtoken"]))[2].get("cache-control"), "no-store")
        self.assertEqual(self.req("POST", "/api/pres/%s/live?token=%s&i=1" % (j["id"], j["rtoken"]), b"")[0], 403)
        self.assertEqual(self.req("POST", "/api/pres/%s/live?token=%s&i=1" % (j["id"], j["token"]), b"")[0], 200)
        self.assertEqual(self.req("GET", "/api/pres/%s/s1.bin" % j["id"])[0], 200)
        self.assertEqual(self.req("GET", "/api/pres/%s/s0.bin" % j["id"])[0], 403)   # the slide before: gone for viewers
        self.assertEqual(self.req("GET", "/api/pres/%s/s7.bin?rt=%s" % (j["id"], j["rtoken"]))[0], 404)
        st, d, h = self.req("POST", "/api/pres/%s/end?token=%s" % (j["id"], j["token"]), b"")
        self.assertEqual(st, 200)
        st, d, h = self.req("GET", "/api/pres/%s/s0.bin" % j["id"])
        self.assertEqual(st, 404)
        self.assertEqual(self.req("GET", "/api/pres/zzz/s0.bin")[0], 404)

    def test_convert(self):
        self.assertFalse(kp.powerpoint_enabled())   # KASTR_PRES_POWERPOINT=0 here: the built-in drawing
        st, d, h = self.req("POST", "/api/pres/convert", make_deck(), {"X-Kastr-Name": "my%20deck.pptx"})
        self.assertEqual(st, 200, d[:300])
        j = json.loads(d)
        self.assertEqual((j["kind"], len(j["slides"]), j["name"]), ("scene", 3, "my deck.pptx"))
        st, d, h = self.req("POST", "/api/pres/convert", b"PK not really")
        self.assertEqual(st, 422)
        self.assertIn("error", json.loads(d))

    def test_convert_through_powerpoint_fake(self):
        runs = []
        with mock.patch.object(kp, "powerpoint_enabled", return_value=True), mock.patch.object(kp, "run_powershell", side_effect=lambda sc, t, run=None: runs.append(sc) or fake_export(sc)):
            st, d, h = self.req("POST", "/api/pres/convert", make_deck(), {"X-Kastr-Name": "deck.pptx"})
        self.assertEqual(st, 200, d[:300])
        j = json.loads(d)
        self.assertEqual((j["kind"], j["via"], len(runs)), ("images", "powerpoint", 1))
        self.assertEqual([x.get("hidden") for x in j["slides"]], [False, False, True])
        self.assertEqual(j["slides"][0]["notes"], "Say SECRET one" + chr(10) + "line" + chr(10) + "two")
        st, d, h = self.req("GET", j["slides"][1]["img"])
        self.assertEqual((st, h.get("content-type")), (200, "image/png"))
        self.assertEqual(self.req("GET", j["slides"][1]["img"], headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", "/api/pres/conv/%s/done" % j["job"], b"")[0], 200)
        self.assertEqual(self.req("GET", j["slides"][1]["img"])[0], 404)

    def test_convert_falls_back_when_powerpoint_fails(self):
        with mock.patch.object(kp, "powerpoint_enabled", return_value=True), mock.patch.object(kp, "run_powershell", return_value=mock.Mock(stderr=b"boom")):
            st, d, h = self.req("POST", "/api/pres/convert", make_deck())
        j = json.loads(d)
        self.assertEqual((st, j["kind"]), (200, "scene"))
        self.assertIn("PowerPoint could not export", j["warnings"][0])
        self.assertEqual(os.listdir(os.path.join(self.tmp, "pres-conv")), [])   # its job folder is gone

    def test_office_is_this_computer_only(self):
        st, d, h = self.req("GET", "/api/pres/office")
        self.assertEqual(st, 200)
        self.assertEqual(set(json.loads(d)), {"powerpoint", "word", "libreoffice", "powerpointExport"})
        st, d, h = self.req("GET", "/api/pres/office", headers={"Origin": "https://evil.example"})
        self.assertEqual(st, 403)


def fake_export(script):
    """A stand-in for PowerShell + PowerPoint: writes s<i>.png where the script would (slides 1 and 2; 3 is hidden)."""
    m = re.search(r"Join-Path '([^']+)'", script)
    for i in (1, 2):
        with open(os.path.join(m.group(1).replace("''", "'"), "s%d.png" % i), "wb") as f:
            f.write(PNG1)
    return mock.Mock(stderr=b"", returncode=0)


class PowerPointCom(unittest.TestCase):
    """Kenton: "ON WHENEVER POWERPOINT IS INSTALLED (fall back to the built-in converter)" -- never the real one here."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr-pres-pp-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_enabled_rule(self):
        self.assertEqual(os.environ.get("KASTR_PRES_POWERPOINT"), "0")
        self.assertFalse(kp.powerpoint_enabled({"powerpoint": True}))   # switched off (lab, tests)
        with mock.patch.dict(os.environ, {"KASTR_PRES_POWERPOINT": ""}), mock.patch.object(kp.os, "name", "nt"):
            self.assertTrue(kp.powerpoint_enabled({"powerpoint": True}))   # on whenever installed
            self.assertFalse(kp.powerpoint_enabled({"powerpoint": False}))
        with mock.patch.dict(os.environ, {"KASTR_PRES_POWERPOINT": ""}), mock.patch.object(kp.os, "name", "posix"):
            self.assertFalse(kp.powerpoint_enabled({"powerpoint": True}))

    def test_powershell_is_hidden_and_encoded(self):
        seen = {}

        def run(cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
            return mock.Mock(stderr=b"")
        kp.run_powershell("Write-Output 'x'", 77, run)
        cmd = seen["cmd"]
        self.assertEqual(cmd[:6], ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand"])
        self.assertEqual(base64.b64decode(cmd[6]).decode("utf-16-le"), "Write-Output 'x'")
        self.assertEqual(seen["kw"]["timeout"], 77)
        if os.name == "nt":
            self.assertEqual(seen["kw"]["creationflags"], 0x08000000)   # CREATE_NO_WINDOW

    def test_export_maps_pictures_to_shown_slides(self):
        deck = make_deck()
        scene = kp.convert_pptx(deck)
        scripts = []
        out = kp.convert_with_powerpoint(deck, self.tmp, scene, run=lambda cmd, **kw: scripts.append(cmd) or fake_export(base64.b64decode(cmd[6]).decode("utf-16-le")))
        script = base64.b64decode(scripts[0][6]).decode("utf-16-le")
        self.assertIn("'PNG', 2560, 2560", script)   # the lab deck is square (4000 x 4000 EMU)
        self.assertIn("Presentations.Open(", script)
        self.assertEqual([x.get("img", "").rsplit("/", 1)[-1] for x in out["slides"]], ["s1.png", "s2.png", ""])
        job = os.path.join(self.tmp, "pres-conv", out["job"])
        self.assertEqual(sorted(os.listdir(job)), ["s1.png", "s2.png"])   # the copy of the deck is gone

    def test_failures_raise_and_clean_up(self):
        deck = make_deck()
        scene = kp.convert_pptx(deck)
        import subprocess

        def slow(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        with self.assertRaises(kp.ConvertError):
            kp.convert_with_powerpoint(deck, self.tmp, scene, run=slow, timeout=1)
        with self.assertRaises(kp.ConvertError):
            kp.convert_with_powerpoint(deck, self.tmp, scene, run=lambda cmd, **kw: mock.Mock(stderr=b"COM error"))
        with self.assertRaises(kp.ConvertError):
            kp.convert_with_powerpoint(deck, self.tmp, scene, run=mock.Mock(side_effect=OSError("no powershell")))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "pres-conv")), [])

    def test_a_web_clients_deck_never_opens_powerpoint(self):
        h = mock.Mock()
        h.path, h.command = "/api/pres/convert", "POST"
        deck = make_deck()
        h.headers = {"Content-Length": str(len(deck)), "X-Kastr-Name": "x.pptx"}
        h.rfile = io.BytesIO(deck)
        with mock.patch.object(kp, "powerpoint_enabled", return_value=True), mock.patch.object(kp, "_own_page", return_value=False), \
                mock.patch.object(kp, "convert_with_powerpoint") as cw:
            kp.handle_api(h, self.tmp)
        cw.assert_not_called()


class PowerPointScript(unittest.TestCase):
    def test_script_shape(self):
        s = kp.powerpoint_export_script(r"C:\x\it's.pptx", r"C:\out", 2560, 1440)
        self.assertIn("New-Object -ComObject PowerPoint.Application", s)
        self.assertIn("Presentations.Open('C:\\x\\it''s.pptx', -1, 0, 0)", s)   # ReadOnly, not Untitled, WithWindow = false
        self.assertIn("'PNG', 2560, 1440", s)
        self.assertNotIn("Visible", s)
        self.assertIn("if (-not $had -and $pp.Presentations.Count -eq 0) { $pp.Quit() }", s)

    def test_status_never_launches(self):
        with mock.patch("subprocess.Popen") as po, mock.patch("subprocess.run") as ru:
            st = kp.office_status()
        po.assert_not_called()
        ru.assert_not_called()
        self.assertIn("powerpoint", st)


class PageSeams(unittest.TestCase):
    def has(self, needle, hay, msg=None):   # a short failure message (the page is 1.8 MB)
        self.assertTrue(needle in hay, msg or repr(needle)[:160])

    def hasnt(self, needle, hay, msg=None):
        self.assertFalse(needle in hay, msg or repr(needle)[:160])

    @classmethod
    def setUpClass(cls):
        cls.page = read("moq-watch-lite.html")
        cls.js = read(os.path.join("assets", "kastr-pres.js"))

    def test_line_endings(self):
        b = raw("moq-watch-lite.html")
        self.assertEqual(b.count(b"\n"), b.count(b"\r\n"), "the page stays CRLF")
        j = raw(os.path.join("assets", "kastr-pres.js"))
        self.hasnt(b"\r\n", j)
        s = raw("kastr_serve.py")
        self.assertEqual(s.count(b"\n"), s.count(b"\r\n"))
        self.hasnt(b"\r\n", raw("kastr_pres.py"))

    def test_share_row_and_script(self):
        p = self.page
        self.has('id="srcPresBtn"', p)
        self.assertRegex(p, r'<input type="file" id="presFile" accept="[^"]*\.pptx[^"]*\.pdf')
        self.has('<script type="module" src="/assets/kastr-pres.js"></script>\n</body>', p)
        self.has('$("presFile").addEventListener("change"', p)
        self.has("window.__pres.startFromFile(f);", p)

    def test_share_hook(self):
        p = self.page
        self.has("window.__presShare = {", p)
        self.has('addSource(SCREEN, null, "Presentation", { presCanvas: canvas, presFps: fps || 5, name: uniqueName(base) })', p)
        self.has("async function presAttach(slot)", p)
        self.has("if (entry.native) capturePresenter(slot); else if (entry.presCanvas) presAttach(slot); else captureDisplay(slot);", p)
        self.has("if (!entry.presCanvas) openSharePip(slot);", p)
        self.has("!pubCap(slot.publish)?.in?.source", p[p.index("async function presAttach"):p.index("async function presAttach") + 1200])

    def test_room_json_fields(self):
        p = self.page
        for k in ("pres", "presCtl", "presPk"):
            self.has('case "%s":' % k, p)
        self.has("try { window.__presMember?.(path, v); } catch {}", p)
        self.has("try { window.__presMember?.(path, null); } catch {}", p)
        self.has("window.__presPeople = () => ({", p)

    def test_module_guarantees(self):
        j = self.js
        self.hasnt("https://", j, "no CDN")
        self.has('import("/assets/vendor/pdfjs/pdf.min.mjs")', j)
        self.has('GlobalWorkerOptions.workerSrc = "/assets/vendor/pdfjs/pdf.worker.min.mjs"', j)
        pub = j[j.index("  function publish() {"):j.index("  function goTo(")]
        self.hasnt("notes:", pub, "the public record never carries a note")
        self.has("k: b64(kIdx)", pub)   # only the LIVE slide's key
        self.has('hkdf(K, "slide/" + i)', j)
        self.has('hkdf(K, "notes")', j)
        self.has('namedCurve: "P-256"', j)
        self.has('"AES-GCM"', j)
        self.has("const b = await bitmapFromCipher(baseFor(rec), rec.id, rec.idx, unb64(rec.k));", j)   # a viewer opens only the live slide, without the read token
        self.has("if (ctl.bv !== mine.ver && mine.by !== who)", j)   # the collision rule
        self.has("if (!isB && !isP) return;   // only the backstage people and the presenters", j)   # 0.21.91: + added presenters
        self.has('stateSet("presPk", k.pub)', j)
        # notes are fetched only by backstage (after unwrapping K), never by the viewer path
        self.assertEqual(j.count('"notes.bin"'), 2)   # fetchBlob's no-store rule + the backstage fetch (uploadNotes posts /notes.bin)
        ov = j[j.index("  async function paintOverlay("):j.index("  // ---- the presenter view")]
        self.hasnt("notes", ov)
        self.has('fetchBlob(baseFor(rec), rec.id, "notes.bin", 10, bk.rt)', j)

    def test_viewers_live_slide_only(self):
        j = self.js
        ov = j[j.index("  async function paintOverlay("):j.index("  // ---- the presenter view")]
        self.hasnt("cacheGet(", ov)   # a viewer's slides never enter the LRU
        self.has("try { o.vBmp?.close(); } catch {}", ov)   # the slide before is dropped
        go = j[j.index("  function goTo("):j.index("  function applyIntent(")]
        self.assertLess(go.index("postLive(m, ni)"), go.index("then(tell, tell)"))   # the store hears first, then the room
        self.has("rt: mine.rtEnc", j)   # the read token rides inside K
        self.has('hkdf(K, "read")', j)
        self.has('go: (i) => { const v = view.deck(); if (!v) return false;', j)
        self.has("if (!id) return false; view.open", j)

    def test_server_and_build(self):
        s = read("kastr_serve.py")
        self.has('if path0 == "/api/pres" or path0.startswith("/api/pres/"):', s)
        self.has('if path.startswith("/api/pres/"):', s)
        self.has('"--hidden-import", "kastr_pres"', read("build.py"))
        self.has('"/assets/kastr-pres.js"]', s)   # the service worker caches the module with the shell


class PdfJs(unittest.TestCase):
    """Kenton: pdf.js APPROVED -- pdfjs-dist 6.4.299, the two minified build files kept, vendored like npu/mediapipe."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("vendor_pdfjs", os.path.join(HERE, "vendor-pdfjs.py"))
        cls.vp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.vp)
        cls.man_path = os.path.join(HERE, "assets", "vendor", "pdfjs", "manifest.json")

    def test_pins(self):
        vp = self.vp
        self.assertEqual((vp.PKG["package"], vp.PKG["version"], vp.PKG["license"]), ("pdfjs-dist", "6.4.299", "Apache-2.0"))
        self.assertEqual(vp.PKG["url"], "https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.4.299.tgz")
        self.assertTrue(vp.PKG["integrity"].startswith("sha512-"))
        self.assertEqual({k: (v[0], v[2]) for k, v in vp.FILES.items()},
                         {"build/pdf.min.mjs": ("pdf.min.mjs", 458904), "build/pdf.worker.min.mjs": ("pdf.worker.min.mjs", 1264342)})

    def test_manifest_matches_the_script_and_build_checks_it(self):
        with open(self.man_path, encoding="utf-8") as f:
            man = json.load(f)
        self.assertEqual(man["runtime"], {n: {"sha256": h, "bytes": b} for (n, h, b) in self.vp.FILES.values()})
        self.assertEqual(man["runtime_source"]["version"], "6.4.299")
        self.assertIn((self.man_path, "vendor-pdfjs.py"), build.VENDORED)
        self.assertEqual(sorted(os.path.basename(p) for p, _, _ in build.vendored_files(self.man_path)), ["pdf.min.mjs", "pdf.worker.min.mjs"])
        self.assertTrue(os.path.isfile(os.path.join(HERE, "assets", "vendor", "pdfjs", "LICENSE.txt")))

    def test_the_two_files_are_git_ignored_and_pinned(self):
        ignored = [ln.strip().lstrip("/") for ln in read(".gitignore").splitlines() if ln.strip().lstrip("/").startswith("assets/vendor/pdfjs/")]
        self.assertEqual(sorted(ignored), ["assets/vendor/pdfjs/pdf.min.mjs", "assets/vendor/pdfjs/pdf.worker.min.mjs"])
        pinned = {os.path.relpath(p, HERE).replace(os.sep, "/") for p, _, _ in build.vendored_files(self.man_path)}
        self.assertEqual(set(ignored), pinned)

    def test_present_files_verify(self):
        if not all(os.path.isfile(os.path.join(HERE, "assets", "vendor", "pdfjs", n)) for (n, _, _) in self.vp.FILES.values()):
            self.skipTest("pdf.js not fetched in this checkout (python vendor-pdfjs.py; build.py fetches it before a build)")
        self.assertEqual(build.verify_vendored(self.man_path), [])
        self.assertEqual(self.vp.stale(), [])

    def test_a_bad_tarball_writes_nothing(self):
        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        with mock.patch.object(self.vp, "DEST", tempfile.mkdtemp(prefix="kastr-pdfjs-")) as d, \
                mock.patch("urllib.request.urlopen", return_value=R(b"not the tarball")):
            with self.assertRaises(SystemExit):
                self.vp.fetch(list(self.vp.FILES))
            self.assertEqual(os.listdir(d), [])
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
