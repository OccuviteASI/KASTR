# -*- coding: utf-8 -*-
"""0.21.84 (Kenton: "start exploring using powerpoints, or other documents, directly inside of KASTR. Allowing another
user, or multiple users, to see the slides and progress forward/backward, but only show the preview for those being
casted to ... The person presenting and the 'backstage' person controlling need to see the notes/slides upcoming as
well as what is live while others only see the presentation."): PROTOTYPE -- the server half of Share > Presentation.

Two jobs, no state shared between them:

1. CONVERT (this computer's KASTR, or the relay host's for a web client): a .pptx becomes a SCENE -- every slide as
   resolved boxes (EMU), colours, text runs, pictures (data: URLs) and its speaker notes -- that the presenter's page
   draws into slide pictures itself (assets/kastr-pres.js). Pure standard library: zipfile + ElementTree, no
   python-pptx, no LibreOffice, no PowerPoint. Placeholders inherit their boxes and text styles from the layout and
   the master, theme colours / fonts resolve, pictures (cropped), round rects / ellipses / arrows / custom paths,
   tables, groups, backgrounds, bullets and autofit are drawn; charts, SmartArt and EMF/WMF pictures are not (a note
   on the slide says so). PDFs need no conversion: the page draws them with pdf.js.
   Optional full fidelity on Windows with PowerPoint installed (KASTR_PRES_POWERPOINT=1, NOT run in the lab -- it
   would open PowerPoint on the desktop): powerpoint_export_script() exports every slide as PNG through COM.

2. STORE (the relay host's KASTR): a dumb blob store for ENCRYPTED slide pictures + notes. The presenter's page
   encrypts slide i with its own key k_i (HKDF of a master key K that never leaves the presenter / backstage pages) and
   the notes with another; the live slide's k_i rides the presenter's room.json, so viewers can open exactly the
   slides that went live and nothing else; backstage people get K wrapped to their own ECDH key. This server only
   ever holds ciphertext -- it cannot read a slide or a note, and needs no token check (capability ids, like
   /api/files). A deck goes when its presenter ends it, or 24 h after it was made.

Routes (kastr_serve dispatches /api/pres*):
  POST /api/pres/convert          body = the .pptx (X-Kastr-Name)  -> {kind:'scene', w, h, slides:[...], media:{...}}
  GET  /api/pres/office           this computer only: {powerpoint, word, libreoffice, powerpointExport}
  POST /api/pres/new              {room, name, n} -> {id, token}
  POST /api/pres/<id>/<file>?token=   body = one encrypted blob (s<i>.bin | notes.bin)
  GET  /api/pres/<id>/<file>      the blob (CORS + CORP cross-origin: other machines' pages fetch it)
  POST /api/pres/<id>/end?token=  remove the deck (also the presenter page's pagehide beacon)
"""
import base64
import io
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
import posixpath
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, unquote, urlparse

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
A, P, R = "{%s}" % NS["a"], "{%s}" % NS["p"], "{%s}" % NS["r"]
MC = "{%s}" % NS["mc"]
REL_SLIDE = "/slide"
EMU_PT = 12700

# limits -- a hostile upload must not eat the machine
CONVERT_MAX = 200 * 1024 * 1024        # the .pptx itself
UNZIP_MAX = 800 * 1024 * 1024          # everything it unpacks to
XML_MAX = 24 * 1024 * 1024             # one XML part
MEDIA_MAX = 40 * 1024 * 1024           # one picture
SLIDES_MAX = 500
STORE_BLOB_MAX = 40 * 1024 * 1024      # one encrypted slide picture
STORE_DECK_MAX = 600 * 1024 * 1024     # one deck
STORE_TOTAL_MAX = 4 * 1024 ** 3        # every deck on this relay host
STORE_DECKS_MAX = 300
STORE_TTL_S = 24 * 3600
BLOB_RE = re.compile(r"^(s\d{1,4}|notes)\.bin$")
ID_RE = re.compile(r"^[0-9a-f]{32}$")
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".bmp": "image/bmp", ".webp": "image/webp", ".svg": "image/svg+xml"}
CONVERT_LOCK = threading.Lock()       # one conversion at a time per KASTR
STORE_LOCK = threading.Lock()


class ConvertError(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------------
# colours

PRESET_COLORS = {"black": "000000", "white": "FFFFFF", "red": "FF0000", "green": "008000", "blue": "0000FF",
                 "yellow": "FFFF00", "gray": "808080", "grey": "808080", "darkGray": "A9A9A9", "lightGray": "D3D3D3",
                 "orange": "FFA500", "purple": "800080", "navy": "000080", "teal": "008080", "silver": "C0C0C0"}
SYS_COLORS = {"windowText": "000000", "window": "FFFFFF", "btnFace": "F0F0F0", "highlight": "0078D7",
              "highlightText": "FFFFFF", "menuText": "000000", "grayText": "6D6D6D"}


def _rgb_hsl(r, g, b):
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        h = (g - b) / d + (6 if g < b else 0)
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h / 6, s, l


def _hsl_rgb(h, s, l):
    def f(p, q, t):
        t %= 1.0
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p
    if s == 0:
        v = round(l * 255)
        return v, v, v
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    return round(f(p, q, h + 1 / 3) * 255), round(f(p, q, h) * 255), round(f(p, q, h - 1 / 3) * 255)


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def apply_color_mods(hexrgb, mods):
    """hex 'RRGGBB' + [(name, value/100000)] -> ('#rrggbb', alpha 0..1). lumMod/lumOff in HSL (what PowerPoint does for
    theme tints), tint/shade towards white/black, alpha."""
    r, g, b = int(hexrgb[0:2], 16), int(hexrgb[2:4], 16), int(hexrgb[4:6], 16)
    alpha = 1.0
    for name, v in mods:
        if name in ("lumMod", "lumOff", "satMod", "satOff", "hueOff", "hueMod"):
            h, s, l = _rgb_hsl(r, g, b)
            if name == "lumMod":
                l = _clamp(l * v)
            elif name == "lumOff":
                l = _clamp(l + v)
            elif name == "satMod":
                s = _clamp(s * v)
            elif name == "satOff":
                s = _clamp(s + v)
            elif name == "hueOff":
                h = (h + v * 100000 / 21600000.0) % 1.0
            elif name == "hueMod":
                h = (h * v) % 1.0
            r, g, b = _hsl_rgb(h, s, l)
        elif name == "tint":     # towards white
            r, g, b = (round(255 - (255 - c) * v) for c in (r, g, b))
        elif name == "shade":    # towards black
            r, g, b = (round(c * v) for c in (r, g, b))
        elif name == "alpha":
            alpha = _clamp(v)
        elif name == "inv":
            r, g, b = 255 - r, 255 - g, 255 - b
        elif name == "gray":
            y = round(0.3 * r + 0.59 * g + 0.11 * b)
            r = g = b = y
    r, g, b = (int(_clamp(c, 0, 255)) for c in (r, g, b))
    return "#%02x%02x%02x" % (r, g, b), alpha


def css_color(hx, alpha):
    if alpha >= 0.999:
        return hx
    return "rgba(%d,%d,%d,%.3f)" % (int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16), alpha)


# ---------------------------------------------------------------------------------------------------------------------
# the package


class Package:
    def __init__(self, data):
        if len(data) > CONVERT_MAX:
            raise ConvertError("the file is larger than %d MB" % (CONVERT_MAX // 1048576))
        try:
            self.z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ConvertError("not a PowerPoint .pptx file (an old .ppt? save it as .pptx or PDF first)")
        infos = self.z.infolist()
        if len(infos) > 20000:
            raise ConvertError("too many parts in this file")
        total = sum(i.file_size for i in infos)
        if total > UNZIP_MAX:
            raise ConvertError("the file unpacks to more than %d MB" % (UNZIP_MAX // 1048576))
        self.names = {i.filename for i in infos}
        self.sizes = {i.filename: i.file_size for i in infos}
        self._xml = {}
        self._rels = {}

    def read(self, name, limit):
        if name not in self.names:
            return None
        if self.sizes.get(name, 0) > limit:
            raise ConvertError("%s is too large" % name)
        return self.z.read(name)

    def xml(self, name):
        if name in self._xml:
            return self._xml[name]
        raw = self.read(name, XML_MAX)
        root = None
        if raw is not None:
            if b"<!ENTITY" in raw[:4096] or b"<!DOCTYPE" in raw[:4096]:
                raise ConvertError("%s declares entities -- refused" % name)
            try:
                root = ET.fromstring(raw)
            except ET.ParseError as e:
                raise ConvertError("%s is not valid XML (%s)" % (name, e))
        self._xml[name] = root
        return root

    def rels(self, part):
        """part 'ppt/slides/slide1.xml' -> {rId: (type, target part)}"""
        if part in self._rels:
            return self._rels[part]
        d, b = posixpath.split(part)
        rp = posixpath.join(d, "_rels", b + ".rels")
        out = {}
        root = self.xml(rp)
        if root is not None:
            for rel in root:
                rid, typ, tgt = rel.get("Id"), rel.get("Type") or "", rel.get("Target") or ""
                if rel.get("TargetMode") == "External":
                    out[rid] = (typ, None)
                    continue
                full = posixpath.normpath(posixpath.join(d, tgt)) if not tgt.startswith("/") else tgt.lstrip("/")
                out[rid] = (typ, full)
        self._rels[part] = out
        return out

    def rel_of_type(self, part, suffix):
        for typ, tgt in self.rels(part).values():
            if typ.endswith(suffix) and tgt:
                return tgt
        return None


# ---------------------------------------------------------------------------------------------------------------------
# theme + colour maps


class Theme:
    def __init__(self, root):
        self.colors = {}
        self.major, self.minor = "Calibri Light", "Calibri"
        self.fills, self.lines, self.bgfills = [], [], []
        if root is None:
            return
        cs = root.find(".//" + A + "clrScheme")
        if cs is not None:
            for el in cs:
                tag = el.tag.split("}")[1]
                c = el.find(A + "srgbClr")
                if c is not None:
                    self.colors[tag] = (c.get("val") or "000000").upper()
                else:
                    s = el.find(A + "sysClr")
                    if s is not None:
                        self.colors[tag] = (s.get("lastClr") or SYS_COLORS.get(s.get("val"), "000000")).upper()
        fs = root.find(".//" + A + "fontScheme")
        if fs is not None:
            mj = fs.find(A + "majorFont/" + A + "latin")
            mn = fs.find(A + "minorFont/" + A + "latin")
            if mj is not None and mj.get("typeface"):
                self.major = mj.get("typeface")
            if mn is not None and mn.get("typeface"):
                self.minor = mn.get("typeface")
        fm = root.find(".//" + A + "fmtScheme")
        if fm is not None:
            for lst, out in (("fillStyleLst", self.fills), ("lnStyleLst", self.lines), ("bgFillStyleLst", self.bgfills)):
                e = fm.find(A + lst)
                if e is not None:
                    out.extend(list(e))

    def font(self, face):
        if not face:
            return None
        if face.startswith("+mj"):
            return self.major
        if face.startswith("+mn"):
            return self.minor
        return face


DEFAULT_CLRMAP = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2", "accent1": "accent1", "accent2": "accent2",
                  "accent3": "accent3", "accent4": "accent4", "accent5": "accent5", "accent6": "accent6",
                  "hlink": "hlink", "folHlink": "folHlink"}


class Ctx:
    """What one slide's shapes resolve against: the theme, the colour map, the part (for r:embed), phClr."""

    def __init__(self, conv, part, theme, clrmap):
        self.conv, self.part, self.theme, self.clrmap = conv, part, theme, clrmap
        self.ph = None   # phClr ('#rrggbb', alpha) while resolving a style reference

    def with_part(self, part):
        c = Ctx(self.conv, part, self.theme, self.clrmap)
        c.ph = self.ph
        return c

    def color(self, parent):
        """The colour child of `parent` (a fill / clr element) -> css string or None."""
        if parent is None:
            return None
        for el in parent:
            tag = el.tag.split("}")[1]
            base = None
            if tag == "srgbClr":
                base = (el.get("val") or "000000").upper()
            elif tag == "schemeClr":
                v = el.get("val") or "tx1"
                if v == "phClr":
                    if self.ph:
                        hx, al = self.ph
                        mods = _mods(el)
                        hx2, al2 = apply_color_mods(hx[1:], mods)
                        return css_color(hx2, min(al, al2))
                    v = "tx1"
                v = self.clrmap.get(v, v)
                base = self.theme.colors.get(v, "000000")
            elif tag == "sysClr":
                base = (el.get("lastClr") or SYS_COLORS.get(el.get("val"), "000000")).upper()
            elif tag == "prstClr":
                base = PRESET_COLORS.get(el.get("val") or "", "000000")
            elif tag == "scrgbClr":
                def lin(x):
                    x = int(x or 0) / 100000.0
                    return round(255 * (12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055))
                base = "%02X%02X%02X" % tuple(int(_clamp(lin(el.get(k)), 0, 255)) for k in ("r", "g", "b"))
            elif tag == "hslClr":
                rr, gg, bb = _hsl_rgb(int(el.get("hue") or 0) / 21600000.0, int(el.get("sat") or 0) / 100000.0,
                                      int(el.get("lum") or 0) / 100000.0)
                base = "%02X%02X%02X" % (rr, gg, bb)
            if base is not None:
                hx, al = apply_color_mods(base, _mods(el))
                return css_color(hx, al)
        return None

    def color_tuple(self, parent):
        c = self.color(parent)
        if not c:
            return None
        if c.startswith("#"):
            return c, 1.0
        m = re.match(r"rgba\((\d+),(\d+),(\d+),([\d.]+)\)", c)
        return ("#%02x%02x%02x" % (int(m.group(1)), int(m.group(2)), int(m.group(3))), float(m.group(4))) if m else None


def _mods(el):
    out = []
    for m in el:
        tag = m.tag.split("}")[1]
        v = m.get("val")
        if v is None:
            if tag in ("inv", "gray"):
                out.append((tag, 0))
            continue
        try:
            out.append((tag, int(v) / 100000.0))
        except ValueError:
            pass
    return out


def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


# ---------------------------------------------------------------------------------------------------------------------
# text styles: a level's paragraph properties merged down the chain


PPR_ATTRS = ("algn", "marL", "indent", "lvl")
RPR_ATTRS = ("sz", "b", "i", "u", "strike", "baseline", "cap")


def _merge_ppr(base, ppr, ctx):
    """base dict + one a:pPr / a:lvlNpPr element -> new dict. Keys: algn marL indent spcBef spcAft lnSpc bu* rpr{}"""
    d = dict(base)
    d["rpr"] = dict(base.get("rpr") or {})
    if ppr is None:
        return d
    for k in ("algn", "marL", "indent"):
        if ppr.get(k) is not None:
            d[k] = ppr.get(k)
    for k in ("spcBef", "spcAft", "lnSpc"):
        e = ppr.find(A + k)
        if e is not None:
            pts, pct = e.find(A + "spcPts"), e.find(A + "spcPct")
            if pts is not None:
                d[k] = {"pts": _int(pts.get("val"))}
            elif pct is not None:
                d[k] = {"pct": _int(pct.get("val"), 100000) / 100000.0}
    if ppr.find(A + "buNone") is not None:
        d["bu"] = None
    ch = ppr.find(A + "buChar")
    if ch is not None:
        d["bu"] = {"c": ch.get("char") or "\u2022"}
    an = ppr.find(A + "buAutoNum")
    if an is not None:
        d["bu"] = {"n": an.get("type") or "arabicPeriod", "start": _int(an.get("startAt"), 1)}
    bf = ppr.find(A + "buFont")
    if bf is not None and bf.get("typeface"):
        d["buFont"] = bf.get("typeface")
    bc = ppr.find(A + "buClr")
    if bc is not None:
        d["buClr"] = ctx.color(bc)
    bs = ppr.find(A + "buSzPct")
    if bs is not None:
        d["buSz"] = _int(bs.get("val"), 100000) / 100000.0
    dr = ppr.find(A + "defRPr")
    if dr is not None:
        d["rpr"] = _merge_rpr(d["rpr"], dr, ctx)
    return d


def _merge_rpr(base, rpr, ctx):
    d = dict(base)
    if rpr is None:
        return d
    for k in RPR_ATTRS:
        if rpr.get(k) is not None:
            d[k] = rpr.get(k)
    sf = rpr.find(A + "solidFill")
    if sf is not None:
        d["color"] = ctx.color(sf)
    elif rpr.find(A + "gradFill") is not None:
        gs = rpr.find(A + "gradFill/" + A + "gsLst/" + A + "gs")
        if gs is not None:
            d["color"] = ctx.color(gs)
    elif rpr.find(A + "noFill") is not None:
        d["color"] = "rgba(0,0,0,0)"
    lt = rpr.find(A + "latin")
    if lt is not None and lt.get("typeface"):
        d["font"] = ctx.theme.font(lt.get("typeface"))
    return d


def _lvl_el(lst, lvl):
    if lst is None:
        return None
    return lst.find(A + "lvl%dpPr" % (lvl + 1))


# ---------------------------------------------------------------------------------------------------------------------
# the converter


PH_STYLE = {"title": "title", "ctrTitle": "title", "subTitle": "body", "body": "body", "obj": "body", None: "body",
            "dt": "other", "ftr": "other", "sldNum": "other", "hdr": "other", "pic": "body", "tbl": "body",
            "chart": "body", "dgm": "body", "media": "body", "clipArt": "body", "sldImg": "other"}
PH_MATCH = {"ctrTitle": ("ctrTitle", "title"), "title": ("title", "ctrTitle"), "subTitle": ("subTitle", "body"),
            "body": ("body",), "obj": ("body", "obj"), None: ("body", "obj")}
GEOMS = {"rect", "roundRect", "ellipse", "triangle", "rtTriangle", "diamond", "parallelogram", "trapezoid", "pentagon",
         "hexagon", "octagon", "chevron", "homePlate", "rightArrow", "leftArrow", "upArrow", "downArrow", "leftRightArrow",
         "line", "straightConnector1", "star5", "plus", "snip1Rect", "round1Rect", "round2SameRect", "flowChartProcess",
         "flowChartAlternateProcess", "flowChartDecision", "flowChartTerminator", "wedgeRectCallout", "wedgeRoundRectCallout",
         "can", "donut", "frame", "teardrop", "heart", "cloud", "bentConnector3", "curvedConnector3"}


class Converter:
    def __init__(self, data, note=None):
        self.pkg = Package(data)
        self.note = note or (lambda *a: None)
        self.media = {}          # part name -> media id
        self.media_out = {}      # media id -> data URL
        self.media_bytes = 0
        self.warn = []
        self.themes = {}

    # ---- media -----------------------------------------------------------------------------------------------------
    def media_id(self, part):
        if part in self.media:
            return self.media[part]
        ext = posixpath.splitext(part)[1].lower()
        typ = MEDIA_TYPES.get(ext)
        if not typ:
            self.media[part] = None
            self._warn("a %s picture cannot be shown (save pictures as PNG/JPEG, or present the PDF)" % (ext.lstrip(".").upper() or "picture"))
            return None
        raw = self.pkg.read(part, MEDIA_MAX)
        if raw is None:
            self.media[part] = None
            return None
        self.media_bytes += len(raw)
        if self.media_bytes > UNZIP_MAX:
            raise ConvertError("the pictures in this deck are too large")
        mid = "m%d" % len(self.media_out)
        self.media_out[mid] = "data:%s;base64,%s" % (typ, base64.b64encode(raw).decode("ascii"))
        self.media[part] = mid
        return mid

    def _warn(self, msg):
        if msg not in self.warn and len(self.warn) < 20:
            self.warn.append(msg)

    def theme_for(self, master_part):
        t = self.pkg.rel_of_type(master_part, "/theme") if master_part else None
        if t not in self.themes:
            self.themes[t] = Theme(self.pkg.xml(t) if t else None)
        return self.themes[t]

    # ---- the deck -----------------------------------------------------------------------------------------------------
    def run(self):
        pres_part = "ppt/presentation.xml"
        root = self.pkg.xml(pres_part)
        if root is None:
            # find the main part through _rels/.rels
            rels = self.pkg.rels("")
            for typ, tgt in rels.values():
                if typ.endswith("/officeDocument") and tgt:
                    pres_part = tgt
                    root = self.pkg.xml(tgt)
            if root is None:
                raise ConvertError("no presentation inside this file")
        sz = root.find(P + "sldSz")
        self.cx = _int(sz.get("cx"), 12192000) if sz is not None else 12192000
        self.cy = _int(sz.get("cy"), 6858000) if sz is not None else 6858000
        self.default_style = root.find(P + "defaultTextStyle")
        prels = self.pkg.rels(pres_part)
        slides = []
        lst = root.find(P + "sldIdLst")
        ids = list(lst) if lst is not None else []
        if len(ids) > SLIDES_MAX:
            raise ConvertError("more than %d slides" % SLIDES_MAX)
        for n, sid in enumerate(ids):
            rid = sid.get(R + "id")
            typ, part = prels.get(rid, ("", None))
            if not part:
                continue
            try:
                slides.append(self.slide(part, n + 1))
            except ConvertError:
                raise
            except Exception as e:   # one broken slide must not lose the deck
                self._warn("slide %d could not be read (%s)" % (n + 1, type(e).__name__))
                slides.append({"bg": {"c": "#ffffff"}, "items": [], "notes": "", "hidden": False, "broken": True})
        if not slides:
            raise ConvertError("this presentation has no slides")
        return {"kind": "scene", "w": self.cx, "h": self.cy, "slides": slides, "media": self.media_out, "warnings": self.warn}

    def slide(self, part, num):
        root = self.pkg.xml(part)
        layout = self.pkg.rel_of_type(part, "/slideLayout")
        master = self.pkg.rel_of_type(layout, "/slideMaster") if layout else None
        lroot = self.pkg.xml(layout) if layout else None
        mroot = self.pkg.xml(master) if master else None
        theme = self.theme_for(master)
        clrmap = dict(DEFAULT_CLRMAP)
        cm = mroot.find(P + "clrMap") if mroot is not None else None
        if cm is not None:
            clrmap.update(cm.attrib)
        for ov_root in (lroot, root):
            ov = ov_root.find(P + "clrMapOvr/" + A + "overrideClrMapping") if ov_root is not None else None
            if ov is not None:
                clrmap.update(ov.attrib)
        ctx = Ctx(self, part, theme, clrmap)
        self.cur = {"layout": lroot, "master": mroot, "lpart": layout, "mpart": master, "num": num,
                    "txstyles": mroot.find(P + "txStyles") if mroot is not None else None}
        # background: slide -> layout -> master
        bg = None
        for r_, p_ in ((root, part), (lroot, layout), (mroot, master)):
            if r_ is None:
                continue
            b = r_.find(P + "cSld/" + P + "bg")
            if b is not None:
                bg = self.background(b, ctx.with_part(p_))
                if bg:
                    break
        items = []
        show_master = (root.get("showMasterSp") != "0")
        if show_master and lroot is not None and lroot.get("showMasterSp") != "0" and mroot is not None:
            items += self.tree(mroot.find(P + "cSld/" + P + "spTree"), ctx.with_part(master), deco=True)
        if show_master and lroot is not None:
            items += self.tree(lroot.find(P + "cSld/" + P + "spTree"), ctx.with_part(layout), deco=True)
        items += self.tree(root.find(P + "cSld/" + P + "spTree"), ctx, deco=False)
        notes = ""
        np_ = self.pkg.rel_of_type(part, "/notesSlide")
        if np_:
            notes = self.notes_text(self.pkg.xml(np_))
        return {"bg": bg or {"c": "#ffffff"}, "items": items, "notes": notes, "hidden": root.get("show") == "0"}

    def background(self, b, ctx):
        pr = b.find(P + "bgPr")
        if pr is not None:
            f = self.fill(pr, ctx)
            return f if f is not None else None
        ref = b.find(P + "bgRef")
        if ref is not None:
            idx = _int(ref.get("idx"))
            phc = ctx.color_tuple(ref)
            lst = ctx.theme.bgfills if idx >= 1001 else ctx.theme.fills
            k = idx - 1001 if idx >= 1001 else idx - 1
            if 0 <= k < len(lst):
                c2 = ctx.with_part(ctx.part)
                c2.ph = phc
                wrap = ET.Element("x")
                wrap.append(lst[k])
                f = self.fill(wrap, c2)
                if f is not None:
                    return f
            if phc:
                return {"c": css_color(*phc)}
        return None

    # ---- fills -------------------------------------------------------------------------------------------------------
    def fill(self, parent, ctx):
        """The fill child of an spPr / bgPr / tcPr: {'c': css} | {'g': {...}} | {'img': media} | {'none': 1} | None (absent)."""
        if parent is None:
            return None
        if parent.find(A + "noFill") is not None:
            return {"none": 1}
        sf = parent.find(A + "solidFill")
        if sf is not None:
            c = ctx.color(sf)
            return {"c": c} if c else None
        gf = parent.find(A + "gradFill")
        if gf is not None:
            stops = []
            for gs in gf.findall(A + "gsLst/" + A + "gs"):
                c = ctx.color(gs)
                if c:
                    stops.append([_int(gs.get("pos")) / 100000.0, c])
            stops.sort(key=lambda s: s[0])
            lin = gf.find(A + "lin")
            ang = _int(lin.get("ang")) / 60000.0 if lin is not None else 90.0
            radial = gf.find(A + "path") is not None
            if stops:
                return {"g": {"stops": stops, "ang": ang, "radial": radial}}
            return None
        pf = parent.find(A + "pattFill")
        if pf is not None:
            c = ctx.color(pf.find(A + "fgClr"))
            return {"c": c} if c else None
        bf = parent.find(A + "blipFill")
        if bf is not None:
            mid = self.blip(bf, ctx)
            if mid:
                return {"img": mid, "crop": self.crop(bf)}
        return None

    def blip(self, bf, ctx):
        bl = bf.find(A + "blip")
        if bl is None:
            return None
        rid = bl.get(R + "embed")
        if not rid:
            if bl.get(R + "link"):
                self._warn("a linked (not embedded) picture cannot be shown")
            return None
        typ, tgt = self.pkg.rels(ctx.part).get(rid, ("", None))
        return self.media_id(tgt) if tgt else None

    @staticmethod
    def crop(bf):
        sr = bf.find(A + "srcRect")
        if sr is None:
            return None
        c = [_int(sr.get(k)) / 100000.0 for k in ("l", "t", "r", "b")]
        return c if any(c) else None

    def line(self, sppr, ctx, style):
        ln = sppr.find(A + "ln") if sppr is not None else None
        w = None
        if ln is not None:
            w = _int(ln.get("w"), 12700) if ln.get("w") else None
            if ln.find(A + "noFill") is not None:
                return None
            sf = ln.find(A + "solidFill")
            if sf is not None:
                c = ctx.color(sf)
                return {"c": c, "w": w or 12700, "dash": self._dash(ln)} if c else None
        # the shape's style reference
        if style is not None:
            ref = style.find(A + "lnRef")
            if ref is not None and _int(ref.get("idx")) > 0:
                phc = ctx.color_tuple(ref)
                k = _int(ref.get("idx")) - 1
                lst = ctx.theme.lines
                lw = 12700
                if 0 <= k < len(lst):
                    lw = _int(lst[k].get("w"), 12700)
                    if lst[k].find(A + "noFill") is not None:
                        return None
                if phc:
                    return {"c": css_color(*phc), "w": w or lw, "dash": self._dash(ln) if ln is not None else None}
        return None

    @staticmethod
    def _dash(ln):
        d = ln.find(A + "prstDash") if ln is not None else None
        v = d.get("val") if d is not None else None
        return v if v and v != "solid" else None

    def style_fill(self, style, ctx):
        if style is None:
            return None
        ref = style.find(A + "fillRef")
        if ref is None or _int(ref.get("idx")) <= 0:
            return None
        phc = ctx.color_tuple(ref)
        k = _int(ref.get("idx")) - 1
        lst = ctx.theme.fills
        if 0 <= k < len(lst):
            c2 = ctx.with_part(ctx.part)
            c2.ph = phc
            wrap = ET.Element("x")
            wrap.append(lst[k])
            f = self.fill(wrap, c2)
            if f is not None:
                return f
        return {"c": css_color(*phc)} if phc else None

    # ---- shapes ------------------------------------------------------------------------------------------------------
    def tree(self, sptree, ctx, deco, xf=None):
        out = []
        if sptree is None:
            return out
        for el in sptree:
            tag = el.tag
            try:
                if tag == MC + "AlternateContent":
                    ch = el.find(MC + "Choice")
                    fb = el.find(MC + "Fallback")
                    got = self.tree(ch, ctx, deco, xf) if ch is not None else []
                    out += got if got else (self.tree(fb, ctx, deco, xf) if fb is not None else [])
                elif tag == P + "sp":
                    s = self.shape(el, ctx, deco, xf)
                    if s:
                        out.append(s)
                elif tag == P + "cxnSp":
                    s = self.shape(el, ctx, deco, xf, connector=True)
                    if s:
                        out.append(s)
                elif tag == P + "pic":
                    s = self.picture(el, ctx, deco, xf)
                    if s:
                        out.append(s)
                elif tag == P + "grpSp":
                    out += self.group(el, ctx, deco, xf)
                elif tag == P + "graphicFrame":
                    s = self.frame(el, ctx, deco, xf)
                    if s:
                        out.append(s)
            except ConvertError:
                raise
            except Exception as e:
                self._warn("a shape on slide %s could not be read (%s)" % (self.cur.get("num"), type(e).__name__))
        return out

    @staticmethod
    def _xfrm(x):
        if x is None:
            return None
        off, ext = x.find(A + "off"), x.find(A + "ext")
        if off is None or ext is None:
            return None
        return {"x": _int(off.get("x")), "y": _int(off.get("y")), "w": _int(ext.get("cx")), "h": _int(ext.get("cy")),
                "rot": _int(x.get("rot")) / 60000.0, "fh": x.get("flipH") == "1", "fv": x.get("flipV") == "1"}

    @staticmethod
    def _apply(box, xf):
        """A child box through the enclosing groups' transforms (xf = (ox, oy, sx, sy, cx0, cy0) composed outer->inner)."""
        if not xf or not box:
            return box
        b = dict(box)
        for (ox, oy, sx, sy, cx0, cy0) in reversed(xf):
            b["x"] = ox + (b["x"] - cx0) * sx
            b["y"] = oy + (b["y"] - cy0) * sy
            b["w"] = b["w"] * sx
            b["h"] = b["h"] * sy
        return b

    def group(self, el, ctx, deco, xf):
        gp = el.find(P + "grpSpPr")
        x = gp.find(A + "xfrm") if gp is not None else None
        xfl = list(xf or [])
        if x is not None:
            off, ext, cho, che = x.find(A + "off"), x.find(A + "ext"), x.find(A + "chOff"), x.find(A + "chExt")
            if off is not None and ext is not None and cho is not None and che is not None:
                cw, ch = _int(che.get("cx")) or 1, _int(che.get("cy")) or 1
                xfl.append((_int(off.get("x")), _int(off.get("y")), _int(ext.get("cx")) / cw, _int(ext.get("cy")) / ch,
                            _int(cho.get("x")), _int(cho.get("y"))))
        return self.tree(el, ctx, deco, xfl)

    def placeholder(self, el):
        nv = el.find(".//" + P + "nvPr")
        ph = nv.find(P + "ph") if nv is not None else None
        if ph is None:
            return None
        return {"type": ph.get("type"), "idx": ph.get("idx")}

    def _find_ph(self, root, ph, by_idx=True):
        if root is None or ph is None:
            return None
        tree = root.find(P + "cSld/" + P + "spTree")
        if tree is None:
            return None
        cands = []
        for el in tree.iter():
            if el.tag not in (P + "sp", P + "pic"):
                continue
            q = self.placeholder(el)
            if q is None:
                continue
            cands.append((el, q))
        if by_idx and ph.get("idx") is not None:   # the layout matches by idx (PowerPoint's rule), the type breaks ties
            same = [(el, q) for el, q in cands if q.get("idx") == ph["idx"]]
            for el, q in same:
                if (q.get("type") or "body") == (ph.get("type") or "body"):
                    return el
            if same:
                return same[0][0]
        want = PH_MATCH.get(ph.get("type"), (ph.get("type"),))
        for w in want:
            for el, q in cands:
                if q.get("type") == w or (w in ("body", "obj") and q.get("type") is None and ph.get("type") in (None, "obj", "body")):
                    return el
        return None

    def ph_chain(self, el, deco):
        """[slide shape, layout ph, master ph] for a placeholder (deco layers return [el])."""
        ph = self.placeholder(el)
        if ph is None or deco:
            return ph, [el]
        lay = self._find_ph(self.cur["layout"], ph)
        lph = self.placeholder(lay) if lay is not None else ph
        mas = self._find_ph(self.cur["master"], {"type": (lph or ph).get("type"), "idx": None}, by_idx=False)
        return ph, [x for x in (el, lay, mas) if x is not None]

    def shape(self, el, ctx, deco, xf, connector=False):
        ph, chain = self.ph_chain(el, deco)
        if deco and ph is not None:
            return None   # a master/layout placeholder is a template, never drawn itself
        sppr = el.find(P + "spPr")
        box = None
        for c in chain:
            box = self._xfrm(c.find(P + "spPr/" + A + "xfrm"))
            if box:
                break
        if not box:
            return None
        box = self._apply(box, xf)
        style = el.find(P + "style")
        geom = self.geometry(sppr)
        fill = self.fill(sppr, ctx) if sppr is not None else None
        if fill is None and ph is not None:
            for c in chain[1:]:
                fill = self.fill(c.find(P + "spPr"), ctx)
                if fill is not None:
                    break
        if fill is None:
            fill = self.style_fill(style, ctx)
        if connector and fill is None:
            fill = {"none": 1}
        line = self.line(sppr, ctx, style)
        item = {"t": "sp", "geom": geom, "fill": fill if fill and not fill.get("none") else None, "ln": line}
        item.update(box)
        tx = self.text(el, ctx, ph, chain, style)
        if tx:
            item["tx"] = tx
        if not item["fill"] and not item["ln"] and not tx:
            return None
        return item

    def geometry(self, sppr):
        if sppr is None:
            return {"prst": "rect"}
        pg = sppr.find(A + "prstGeom")
        if pg is not None:
            prst = pg.get("prst") or "rect"
            adj = {}
            for gd in pg.findall(A + "avLst/" + A + "gd"):
                m = re.match(r"val\s+(-?\d+)", gd.get("fmla") or "")
                if m:
                    adj[gd.get("name")] = int(m.group(1))
            if prst not in GEOMS:
                self._warn("the shape '%s' is drawn as a rectangle" % prst)
                prst = "rect"
            return {"prst": prst, "adj": adj} if adj else {"prst": prst}
        cg = sppr.find(A + "custGeom")
        if cg is not None:
            paths = []
            for pth in cg.findall(A + "pathLst/" + A + "path"):
                pw, phh = _int(pth.get("w")), _int(pth.get("h"))
                cmds = []
                for c in pth:
                    t = c.tag.split("}")[1]
                    pts = [v for pt in c.findall(A + "pt") for v in (_int(pt.get("x")), _int(pt.get("y")))]
                    op = {"moveTo": "M", "lnTo": "L", "cubicBezTo": "C", "quadBezTo": "Q"}.get(t)
                    if op:
                        cmds.append([op] + pts)
                    elif t == "close":
                        cmds.append(["Z"])
                    elif t == "arcTo":
                        cmds.append(["A", _int(c.get("wR")), _int(c.get("hR")), _int(c.get("stAng")), _int(c.get("swAng"))])
                paths.append({"w": pw, "h": phh, "d": cmds, "fill": pth.get("fill") != "none", "stroke": pth.get("stroke") != "0"})
            if paths:
                return {"prst": "cust", "paths": paths}
        return {"prst": "rect"}

    def picture(self, el, ctx, deco, xf):
        ph, chain = self.ph_chain(el, deco)
        if deco and ph is not None:
            return None
        box = None
        for c in chain:
            box = self._xfrm(c.find(P + "spPr/" + A + "xfrm"))
            if box:
                break
        if not box:
            return None
        box = self._apply(box, xf)
        bf = el.find(P + "blipFill")
        mid = self.blip(bf, ctx) if bf is not None else None
        if not mid:
            if el.find(".//" + P + "nvPr/" + A + "videoFile") is not None or el.find(".//" + P + "nvPr/" + A + "audioFile") is not None:
                self._warn("video and sound in slides do not play here (present them with PowerPoint)")
            return None
        item = {"t": "pic", "m": mid, "crop": self.crop(bf), "geom": self.geometry(el.find(P + "spPr")),
                "ln": self.line(el.find(P + "spPr"), ctx, el.find(P + "style"))}
        item.update(box)
        return item

    def frame(self, el, ctx, deco, xf):
        box = self._xfrm(el.find(P + "xfrm"))
        if not box:
            return None
        box = self._apply(box, xf)
        gd = el.find(A + "graphic/" + A + "graphicData")
        if gd is None:
            return None
        uri = gd.get("uri") or ""
        tbl = gd.find(A + "tbl")
        if tbl is not None:
            return self.table(tbl, box, ctx)
        kind = "chart" if uri.endswith("/chart") else "SmartArt" if "diagram" in uri else "object"
        self._warn("%s objects are shown as a box (present with PowerPoint for full fidelity)" % kind)
        item = {"t": "sp", "geom": {"prst": "rect"}, "fill": {"c": "rgba(127,127,127,0.12)"}, "ln": {"c": "#9ca3af", "w": 9525, "dash": "dash"},
                "tx": {"anchor": "ctr", "ins": [91440, 45720, 91440, 45720], "wrap": True, "scale": 1, "lnRed": 0,
                       "ps": [{"al": "ctr", "ml": 0, "ind": 0, "rs": [{"t": "[" + kind + "]", "sz": 1400, "c": "#6b7280", "f": ctx.theme.minor}]}]}}
        item.update(box)
        return item

    def table(self, tbl, box, ctx):
        cols = [_int(g.get("w")) for g in tbl.findall(A + "tblGrid/" + A + "gridCol")]
        rows = []
        tstyle = ctx.theme.minor
        for tr in tbl.findall(A + "tr"):
            cells = []
            for tc in tr.findall(A + "tc"):
                if tc.get("hMerge") == "1" or tc.get("vMerge") == "1":
                    cells.append({"skip": 1})
                    continue
                tcpr = tc.find(A + "tcPr")
                f = self.fill(tcpr, ctx) if tcpr is not None else None
                body = tc.find(A + "txBody")
                tx = self.text_body(body, ctx, base_style=None, kind="other", bodypr_chain=[]) if body is not None else None
                if tx and tcpr is not None:
                    tx["ins"] = [_int(tcpr.get("marL"), 91440), _int(tcpr.get("marT"), 45720), _int(tcpr.get("marR"), 91440), _int(tcpr.get("marB"), 45720)]
                    tx["anchor"] = {"ctr": "ctr", "b": "b"}.get(tcpr.get("anchor"), "t")
                cells.append({"tx": tx, "fill": f.get("c") if f and "c" in f else None,
                              "span": _int(tc.get("gridSpan"), 1), "rspan": _int(tc.get("rowSpan"), 1)})
            rows.append({"h": _int(tr.get("h")), "cells": cells})
        item = {"t": "tbl", "cols": cols, "rows": rows, "font": tstyle}
        item.update(box)
        return item

    # ---- text --------------------------------------------------------------------------------------------------------
    def text(self, el, ctx, ph, chain, style):
        body = el.find(P + "txBody")
        if body is None:
            return None
        kind = PH_STYLE.get(ph.get("type"), "body") if ph is not None else "other"
        base = {}
        if style is not None:   # the shape style's font colour (shapes drawn by hand: white text on accent fills)
            fr = style.find(A + "fontRef")
            if fr is not None:
                c = ctx.color(fr)
                if c:
                    base["color"] = c
                if fr.get("idx") == "major":
                    base["font"] = ctx.theme.major
        return self.text_body(body, ctx, base_style=base, kind=kind, bodypr_chain=chain[1:] if ph is not None else [], chain=chain if ph is not None else [el])

    def _lst_chain(self, kind, chain):
        """The list styles a paragraph level merges, lowest first: defaultTextStyle, master txStyles(kind), master ph
        lstStyle, layout ph lstStyle, the shape's own lstStyle."""
        out = [self.default_style] if self.default_style is not None else []
        txs = self.cur.get("txstyles")
        if txs is not None:
            st = txs.find(P + {"title": "titleStyle", "body": "bodyStyle"}.get(kind, "otherStyle"))
            if st is not None:
                out.append(st)
        for c in reversed(chain):
            ls = c.find(P + "txBody/" + A + "lstStyle")
            if ls is not None:
                out.append(ls)
        return out

    def text_body(self, body, ctx, base_style, kind, bodypr_chain, chain=None):
        # bodyPr: the shape's own attributes win over the layout's, then the master's
        bp = {}
        for c in reversed([x.find(P + "txBody/" + A + "bodyPr") for x in bodypr_chain] + [body.find(A + "bodyPr")]):
            if c is None:
                continue
            bp.update(c.attrib)
            if c.find(A + "normAutofit") is not None:
                na = c.find(A + "normAutofit")
                bp["_fit"] = (_int(na.get("fontScale"), 100000) / 100000.0, _int(na.get("lnSpcReduction"), 0) / 100000.0)
            elif c.find(A + "noAutofit") is not None or c.find(A + "spAutoFit") is not None:
                bp["_fit"] = (1.0, 0.0)
        lsts = self._lst_chain(kind, chain or [])
        paras = []
        any_text = False
        for p in body.findall(A + "p"):
            ppr = p.find(A + "pPr")
            lvl = _int(ppr.get("lvl")) if ppr is not None else 0
            d = {"rpr": dict(base_style or {})}
            if kind == "other" and base_style is None:
                d = {"rpr": {}}
            for ls in lsts:
                d = _merge_ppr(d, _lvl_el(ls, lvl), ctx)
            if base_style:   # fontRef colour beats the list styles' (PowerPoint: the shape style is the shape's own)
                d["rpr"].update({k: v for k, v in base_style.items()})
            d = _merge_ppr(d, ppr, ctx)
            runs = []
            for r in p:
                t = r.tag
                if t == A + "r" or t == A + "fld":
                    rp = _merge_rpr(d["rpr"], r.find(A + "rPr"), ctx)
                    txt = (r.find(A + "t").text if r.find(A + "t") is not None else "") or ""
                    if t == A + "fld" and (r.get("type") or "") == "slidenum":
                        txt = str(self.cur.get("num", ""))
                    if txt:
                        any_text = any_text or bool(txt.strip())
                        runs.append(self._run(txt, rp, ctx))
                elif t == A + "br":
                    rp = _merge_rpr(d["rpr"], r.find(A + "rPr"), ctx)
                    runs.append(dict(self._run("\n", rp, ctx), br=1))
            end = p.find(A + "endParaRPr")
            esz = _int(_merge_rpr(d["rpr"], end, ctx).get("sz"), 1800)
            bu = d.get("bu")
            if bu and not any(r_.get("t", "").strip() for r_ in runs):
                bu = None   # an empty paragraph carries no bullet
            para = {"al": d.get("algn") or "l", "ml": _int(d.get("marL")), "ind": _int(d.get("indent")),
                    "rs": runs, "esz": esz}
            for k in ("spcBef", "spcAft", "lnSpc"):
                if d.get(k):
                    para[k] = d[k]
            if bu:
                b2 = dict(bu)
                if d.get("buClr"):
                    b2["col"] = d["buClr"]
                if d.get("buSz"):
                    b2["sz"] = d["buSz"]
                if d.get("buFont") and not d["buFont"].startswith("+"):
                    b2["f"] = d["buFont"]
                para["bu"] = b2
                para["lvl"] = lvl
            paras.append(para)
        if not any_text:
            return None
        fit = bp.get("_fit", (1.0, 0.0))
        ins = [_int(bp.get("lIns"), 91440), _int(bp.get("tIns"), 45720), _int(bp.get("rIns"), 91440), _int(bp.get("bIns"), 45720)]
        anchor = {"ctr": "ctr", "b": "b"}.get(bp.get("anchor"), "t")
        return {"anchor": anchor, "ins": ins, "wrap": bp.get("wrap") != "none", "scale": fit[0], "lnRed": fit[1],
                "ps": paras, "vert": bp.get("vert") if bp.get("vert") not in (None, "horz") else None,
                "actr": bp.get("anchorCtr") == "1"}

    @staticmethod
    def _run(txt, rp, ctx):
        r = {"t": txt, "sz": _int(rp.get("sz"), 1800)}
        if rp.get("b") in ("1", "true"):
            r["b"] = 1
        if rp.get("i") in ("1", "true"):
            r["i"] = 1
        if rp.get("u") not in (None, "none"):
            r["u"] = 1
        if rp.get("strike") not in (None, "noStrike"):
            r["s"] = 1
        if rp.get("baseline"):
            r["bl"] = _int(rp.get("baseline")) / 100000.0
        if rp.get("cap") == "all":
            r["t"] = txt.upper()
        r["c"] = rp.get("color") or "#000000"
        r["f"] = rp.get("font") or ctx.theme.minor
        return r

    def notes_text(self, root):
        if root is None:
            return ""
        out = []
        for sp in root.iter(P + "sp"):
            ph = self.placeholder(sp)
            if ph is None or ph.get("type") not in ("body", None) or ph.get("type") == "sldImg":
                continue
            if ph.get("type") is None and ph.get("idx") is None:
                continue
            for p in sp.findall(".//" + A + "p"):
                line = ""
                for r in p:
                    if r.tag in (A + "r", A + "fld"):
                        t = r.find(A + "t")
                        line += (t.text or "") if t is not None else ""
                    elif r.tag == A + "br":
                        line += "\n"
                out.append(line)
        while out and not out[-1].strip():
            out.pop()
        return "\n".join(out).strip("\n")


def convert_pptx(data, note=None):
    """bytes of a .pptx -> the scene dict (see the module doc). Raises ConvertError with a sentence for the person."""
    return Converter(data, note).run()


def notes_only(data):
    """bytes of a .pptx -> [notes per slide] (the PowerPoint-export path keeps its own pictures but needs these)."""
    c = Converter(data)
    sc = c.run()
    return [s.get("notes", "") for s in sc["slides"]]


# ---------------------------------------------------------------------------------------------------------------------
# office programs on this computer (design + the opt-in fidelity path; nothing here starts a program)


def office_status():
    """What could convert here at full fidelity. Detection only: a registry key / a file, never a launched program."""
    out = {"powerpoint": False, "word": False, "libreoffice": None,
           "powerpointExport": os.environ.get("KASTR_PRES_POWERPOINT") == "1"}
    if os.name == "nt":
        try:
            import winreg
            for prog, key in (("powerpoint", "PowerPoint.Application"), ("word", "Word.Application")):
                try:
                    winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key))
                    out[prog] = True
                except OSError:
                    pass
        except ImportError:
            pass
    for cand in ("soffice", "libreoffice"):
        p = shutil.which(cand)
        if p:
            out["libreoffice"] = p
            break
    if not out["libreoffice"] and os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            p = os.path.join(base, "LibreOffice", "program", "soffice.exe")
            if os.path.exists(p):
                out["libreoffice"] = p
                break
    return out


def powerpoint_export_script(src, outdir, width=2560, height=1440):
    """The PowerShell that exports every slide of `src` as s<i>.png through PowerPoint's COM server (WithWindow =
    msoFalse: no window; ReadOnly; quits PowerPoint only when it started it). Returned, not run -- the caller decides
    (0.21.84 prototype: only with KASTR_PRES_POWERPOINT=1, never in the lab)."""
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$had = $null -ne (Get-Process POWERPNT -ErrorAction SilentlyContinue)",
        "$pp = New-Object -ComObject PowerPoint.Application",
        "$pres = $pp.Presentations.Open(%s, -1, 0, 0)" % q(src),   # ReadOnly=msoTrue, Untitled=msoFalse, WithWindow=msoFalse
        "try {",
        "  $i = 0",
        "  foreach ($s in $pres.Slides) { $i++; if ($s.SlideShowTransition.Hidden) { continue }",
        "    $s.Export((Join-Path %s ('s' + $i + '.png')), 'PNG', %d, %d) }" % (q(outdir), int(width), int(height)),
        "} finally { $pres.Close(); if (-not $had -and $pp.Presentations.Count -eq 0) { $pp.Quit() } }",
    ])


# ---------------------------------------------------------------------------------------------------------------------
# the blob store (relay host)


class Store:
    def __init__(self, base):
        self.root = os.path.join(base, "pres")
        os.makedirs(self.root, exist_ok=True)

    def _meta(self, did):
        try:
            with open(os.path.join(self.root, did, "meta.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _decks(self):
        try:
            return [d for d in os.listdir(self.root) if ID_RE.match(d)]
        except OSError:
            return []

    def _size(self, did):
        tot = 0
        try:
            for fn in os.listdir(os.path.join(self.root, did)):
                if fn == "meta.json":
                    continue
                try:
                    tot += os.path.getsize(os.path.join(self.root, did, fn))
                except OSError:
                    pass
        except OSError:
            pass
        return tot

    def sweep(self, now=None):
        now = now or time.time()
        gone = 0
        for d in self._decks():
            m = self._meta(d)
            if m is None or now - float(m.get("at") or 0) > STORE_TTL_S:
                shutil.rmtree(os.path.join(self.root, d), ignore_errors=True)
                gone += 1
        return gone

    def create(self, room, name, n, now=None):
        with STORE_LOCK:
            self.sweep(now)
            decks = self._decks()
            if len(decks) >= STORE_DECKS_MAX:
                raise ValueError("this relay host holds too many presentations -- try again later")
            if sum(self._size(d) for d in decks) > STORE_TOTAL_MAX:
                raise ValueError("this relay host's presentation space is full")
            did, tok = uuid.uuid4().hex, uuid.uuid4().hex
            os.makedirs(os.path.join(self.root, did))
            meta = {"id": did, "token": tok, "room": str(room or "")[:64], "name": str(name or "")[:120],
                    "n": max(0, min(SLIDES_MAX, _int(n))), "at": int(now or time.time())}
            with open(os.path.join(self.root, did, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f)
            return did, tok

    def put(self, did, token, fname, rfile, length):
        if not ID_RE.match(did or "") or not BLOB_RE.match(fname or ""):
            return 404, "no such presentation file"
        m = self._meta(did)
        if m is None:
            return 404, "no such presentation"
        if not token or token != m.get("token"):
            return 403, "not the presenter"
        if length <= 0:
            return 400, "empty"
        if length > STORE_BLOB_MAX:
            return 413, "one slide picture may be at most %d MB" % (STORE_BLOB_MAX // 1048576)
        if self._size(did) + length > STORE_DECK_MAX:
            return 413, "this presentation is too large"
        path = os.path.join(self.root, did, fname)
        got = 0
        with open(path + ".part", "wb") as f:
            while got < length:
                chunk = rfile.read(min(1 << 20, length - got))
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
        if got != length:
            try:
                os.remove(path + ".part")
            except OSError:
                pass
            return 400, "short upload"
        os.replace(path + ".part", path)
        return 200, "ok"

    def path(self, did, fname):
        if not ID_RE.match(did or "") or not BLOB_RE.match(fname or ""):
            return None
        p = os.path.join(self.root, did, fname)
        return p if os.path.isfile(p) else None

    def end(self, did, token):
        if not ID_RE.match(did or ""):
            return 404
        m = self._meta(did)
        if m is None:
            return 200
        if token != m.get("token"):
            return 403
        shutil.rmtree(os.path.join(self.root, did), ignore_errors=True)
        return 200


# ---------------------------------------------------------------------------------------------------------------------
# HTTP glue (kastr_serve hands its handler here)


def _own_page(handler):
    try:
        import kastr_relay
        if not kastr_relay.is_local(handler):
            return False
    except Exception:
        return False
    origin = str(handler.headers.get("Origin") or "")
    if origin and not re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", origin):
        return False
    return str(handler.headers.get("Sec-Fetch-Site") or "") in ("", "same-origin", "same-site", "none")


def _cors(handler):
    try:
        handler._cors()
    except AttributeError:
        handler.send_header("Access-Control-Allow-Origin", "*")
    handler._corp_cross = True


def _reply(handler, code, obj):
    body = json.dumps(obj).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    _cors(handler)
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _drain(handler, limit=1 << 20):
    try:
        n = int(handler.headers.get("Content-Length") or 0)
        if 0 < n <= limit:
            handler.rfile.read(n)
    except Exception:
        pass


def _length(handler):
    try:
        return int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        return 0


def handle_api(handler, state_dir, note=None):
    """Serve /api/pres*. Returns True when it answered."""
    path = handler.path.split("?", 1)[0]
    if not (path == "/api/pres" or path.startswith("/api/pres/")):
        return False
    method = handler.command
    qs = parse_qs(urlparse(handler.path).query)
    note = note or (lambda *a: None)
    if path == "/api/pres/office":
        if not _own_page(handler):
            return _reply(handler, 403, {"error": "only on the computer itself"})
        return _reply(handler, 200, office_status())
    if path == "/api/pres/convert":
        if method != "POST":
            return _reply(handler, 405, {"error": "POST the .pptx"})
        n = _length(handler)
        if n <= 0:
            return _reply(handler, 400, {"error": "empty upload"})
        if n > CONVERT_MAX:
            _drain(handler)
            return _reply(handler, 413, {"error": "the file is larger than %d MB" % (CONVERT_MAX // 1048576)})
        name = os.path.basename(unquote(handler.headers.get("X-Kastr-Name") or "deck.pptx"))[:200]
        data = handler.rfile.read(n)
        if not CONVERT_LOCK.acquire(timeout=60):
            return _reply(handler, 503, {"error": "another presentation is being prepared here -- try again in a minute"})
        try:
            t0 = time.time()
            out = convert_pptx(data)
            out["name"] = name
            out["ms"] = int((time.time() - t0) * 1000)
            note("pres: converted %s (%d slides, %d pictures) in %d ms" % (name, len(out["slides"]), len(out["media"]), out["ms"]))
            return _reply(handler, 200, out)
        except ConvertError as e:
            return _reply(handler, 422, {"error": str(e)})
        except Exception as e:
            note("pres: conversion of %s failed: %r" % (name, e))
            return _reply(handler, 422, {"error": "this file could not be read as a presentation (%s)" % type(e).__name__})
        finally:
            CONVERT_LOCK.release()
    if not state_dir:
        _drain(handler)
        return _reply(handler, 503, {"error": "no storage here"})
    store = Store(state_dir)
    if path == "/api/pres/new":
        if method != "POST":
            return _reply(handler, 405, {"error": "POST"})
        n = _length(handler)
        try:
            body = json.loads(handler.rfile.read(n) or b"{}") if 0 < n <= 65536 else {}
        except ValueError:
            body = {}
        try:
            did, tok = store.create(body.get("room"), body.get("name"), body.get("n"))
        except ValueError as e:
            return _reply(handler, 507, {"error": str(e)})
        note("pres: new deck %s (%s slides) for room %s" % (did[:8], body.get("n"), str(body.get("room") or "")[:40]))
        return _reply(handler, 200, {"id": did, "token": tok})
    m = re.match(r"^/api/pres/([0-9a-f]{32})/([A-Za-z0-9._-]{1,48})$", path)
    if not m:
        _drain(handler)
        return _reply(handler, 404, {"error": "no such presentation route"})
    did, fname = m.group(1), m.group(2)
    token = (qs.get("token") or [""])[0]
    if fname == "end":
        _drain(handler)
        code = store.end(did, token)
        return _reply(handler, code, {"ok": code == 200})
    if method == "POST":
        code, msg = store.put(did, token, fname, handler.rfile, _length(handler))
        if code != 200:
            _drain(handler, STORE_BLOB_MAX)
        return _reply(handler, code, {"ok": code == 200} if code == 200 else {"error": msg})
    if method not in ("GET", "HEAD"):
        return _reply(handler, 405, {"error": "GET"})
    p = store.path(did, fname)
    if not p:
        return _reply(handler, 404, {"error": "not there (yet)"})
    size = os.path.getsize(p)
    handler.send_response(200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Length", str(size))
    # a slide picture never changes under its name (a new deck = a new id); the notes are rewritten when edited
    handler.send_header("Cache-Control", "no-store" if fname == "notes.bin" else "private, max-age=86400, immutable")
    _cors(handler)
    handler.end_headers()
    if method == "HEAD":
        return True
    with open(p, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            handler.wfile.write(chunk)
    return True
