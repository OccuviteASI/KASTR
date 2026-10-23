# -*- coding: utf-8 -*-
"""v0.21.84 PROTOTYPE (Kenton: "start exploring using powerpoints, or other documents, directly inside of KASTR ... only
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
  * build.py hidden import, .gitignore keeps a lab pdf.js out of git, vendor-pdfjs.py refuses an unpinned fetch"""
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
import kastr_pres as kp  # noqa: E402
import kastr_serve  # noqa: E402


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
        did, tok = self.st.create("room1", "deck", 3)
        self.assertRegex(did, r"^[0-9a-f]{32}$")
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
        did, tok = self.st.create("r", "d", 1)
        with mock.patch.object(kp, "STORE_BLOB_MAX", 5):
            self.assertEqual(self.st.put(did, tok, "s0.bin", io.BytesIO(b"x" * 6), 6)[0], 413)
        with mock.patch.object(kp, "STORE_DECK_MAX", 8):
            self.assertEqual(self.st.put(did, tok, "s0.bin", io.BytesIO(b"x" * 6), 6)[0], 200)
            self.assertEqual(self.st.put(did, tok, "s1.bin", io.BytesIO(b"x" * 6), 6)[0], 413)
        with mock.patch.object(kp, "STORE_DECKS_MAX", 1):
            with self.assertRaises(ValueError):
                self.st.create("r", "d", 1)

    def test_sweep_after_a_day(self):
        did, tok = self.st.create("r", "d", 1, now=time.time() - kp.STORE_TTL_S - 5)
        self.assertEqual(self.st.sweep(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "pres", did)))


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
        st, d, h = self.req("POST", "/api/pres/%s/s0.bin?token=%s" % (j["id"], j["token"]), b"\x01\x02\x03")
        self.assertEqual(st, 200, d)
        st, d, h = self.req("POST", "/api/pres/%s/s1.bin?token=nope" % j["id"], b"\x01")
        self.assertEqual(st, 403)
        st, d, h = self.req("GET", "/api/pres/%s/s0.bin" % j["id"], headers={"Origin": "http://10.0.0.9:8000"})
        self.assertEqual((st, d), (200, b"\x01\x02\x03"))
        self.assertEqual(h.get("access-control-allow-origin"), "*")
        self.assertEqual(h.get("cross-origin-resource-policy"), "cross-origin")
        self.assertIn("immutable", h.get("cache-control", ""))
        st, d, h = self.req("GET", "/api/pres/%s/s1.bin" % j["id"])
        self.assertEqual(st, 404)
        st, d, h = self.req("POST", "/api/pres/%s/end?token=%s" % (j["id"], j["token"]), b"")
        self.assertEqual(st, 200)
        st, d, h = self.req("GET", "/api/pres/%s/s0.bin" % j["id"])
        self.assertEqual(st, 404)
        self.assertEqual(self.req("GET", "/api/pres/zzz/s0.bin")[0], 404)

    def test_convert(self):
        st, d, h = self.req("POST", "/api/pres/convert", make_deck(), {"X-Kastr-Name": "my%20deck.pptx"})
        self.assertEqual(st, 200, d[:300])
        j = json.loads(d)
        self.assertEqual((j["kind"], len(j["slides"]), j["name"]), ("scene", 3, "my deck.pptx"))
        st, d, h = self.req("POST", "/api/pres/convert", b"PK not really")
        self.assertEqual(st, 422)
        self.assertIn("error", json.loads(d))

    def test_office_is_this_computer_only(self):
        st, d, h = self.req("GET", "/api/pres/office")
        self.assertEqual(st, 200)
        self.assertEqual(set(json.loads(d)), {"powerpoint", "word", "libreoffice", "powerpointExport"})
        st, d, h = self.req("GET", "/api/pres/office", headers={"Origin": "https://evil.example"})
        self.assertEqual(st, 403)


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
        self.has('import("/assets/vendor/pdfjs/pdf.mjs")', j)
        self.has('GlobalWorkerOptions.workerSrc = "/assets/vendor/pdfjs/pdf.worker.mjs"', j)
        pub = j[j.index("  function publish() {"):j.index("  function goTo(")]
        self.hasnt("notes:", pub, "the public record never carries a note")
        self.has("k: b64(kIdx)", pub)   # only the LIVE slide's key
        self.has('hkdf(K, "slide/" + i)', j)
        self.has('hkdf(K, "notes")', j)
        self.has('namedCurve: "P-256"', j)
        self.has('"AES-GCM"', j)
        self.has("return bitmapFromCipher(baseFor(rec), rec.id, rec.idx, unb64(rec.k));", j)   # a viewer opens only the live slide
        self.has("if (ctl.bv !== mine.ver && mine.by !== who)", j)   # the collision rule
        self.has("if (!b) return;   // only the backstage people the presenter picked", j)
        self.has('stateSet("presPk", k.pub)', j)
        # notes are fetched only by backstage (after unwrapping K), never by the viewer path
        self.assertEqual(j.count('"notes.bin"'), 2)   # fetchBlob's no-store rule + the backstage fetch (uploadNotes posts /notes.bin)
        ov = j[j.index("  async function paintOverlay("):j.index("  // ---- the presenter view")]
        self.hasnt("notes", ov)
        self.has('fetchBlob(baseFor(rec), rec.id, "notes.bin", 10)', j)

    def test_server_and_build(self):
        s = read("kastr_serve.py")
        self.has('if path0 == "/api/pres" or path0.startswith("/api/pres/"):', s)
        self.has('if path.startswith("/api/pres/"):', s)
        self.has('"--hidden-import", "kastr_pres"', read("build.py"))
        self.has("/assets/vendor/pdfjs/", read(".gitignore"))

    def test_vendor_pdfjs_refuses_unpinned(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("vendor_pdfjs", os.path.join(HERE, "vendor-pdfjs.py"))
        vp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vp)
        self.assertEqual(vp.PINNED_VERSION, "")
        self.assertTrue(all(v is None for v in vp.FILES.values()))
        with mock.patch("urllib.request.urlopen") as uo:
            with self.assertRaises(SystemExit):
                vp.from_npm(False)
        uo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
