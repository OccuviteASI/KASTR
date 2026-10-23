"""Files and images over remote control (0.21.83).

Kenton (2026-10-23): "Am I able to copy a file on my machine or the remote machine and paste it on the other side?" -- yes:
  * FILES both ways: copy file(s) / folders in Explorer (CF_HDROP; on X11 x-special/gnome-copied-files or text/uri-list) on
    either computer while control is live -> the other KASTR fetches them and puts them on ITS clipboard as files (a temp
    folder + CF_HDROP + "Preferred DropEffect: copy" on Windows; gnome-copied-files + text/uri-list on X11), so Ctrl+V / Paste
    in Explorer / a file manager copies them where that person is. The FILES travel, never paths.
  * IMAGES both ways (CF_DIB / CF_DIBV5 / "PNG" on Windows, image/png on X11), size-capped -- only when the clipboard holds no
    text (Excel / Word put a picture beside their text: the text is what a paste wants, and it already travels -- kastr_rc).
  * DRAG-AND-DROP from the controller's desktop onto the shared screen in their KASTR view -> sent to the sharer's computer and
    delivered where it was released: an Explorer folder window or the desktop (Windows), any XDND target -- a file manager, the
    desktop -- on X11; anywhere else it lands in Downloads/KASTR with a note.

Who does what:
  * THIS module (each side's KASTR, loopback API /api/rcfiles, the page's own computer only): watches the clipboard while a
    session lives (never what was on it before -- the baseline), builds an OFFER of what was copied (relative names, sizes; the
    absolute paths stay here), serves its chunks to the page, takes the other side's chunks into a temp folder, and finally
    places them (clipboard / folder / XDND). Names are sanitized (Windows' reserved names, "..", bad characters), symlinks and
    junctions are never followed (they are skipped), device paths refused, per-transfer and per-session caps enforced.
  * the pages carry the bytes over MoQ through the relay (moq-watch-lite.html, rcf*): each side publishes
    <room>/<host>/~rcf/<peer> (fo.json: my offers; fq.json: what I want of theirs + my progress) and <room>/<host>/~rcd/<peer>
    (fd: one chunk a group, AES-GCM with the key the sharer handed over in the relay's "allow" note) -- the receiver PULLS a
    window of chunks, so nothing is lost and a stalled chunk is simply asked for again.
  * a session = one remote-control grant (the sharer's KASTR checks kastr_rc's grant; the controller's lives by its page's
    lease). When it ends, unfinished transfers are deleted at once; finished ones that are still on the clipboard stay
    rc_files_keep_min minutes (a paste right after Release must still work), then go -- and so does the clipboard pointing at them.

kastr.ini (all optional): rc_files = on|off, rc_file_max_mb (2048: one transfer), rc_session_max_mb (8192: both ways together in
one session), rc_files_auto_mb (100: a copy up to this size is fetched at once; a bigger one waits for a paste or "Get them"),
rc_image_max_mb (32), rc_files_keep_min (10).
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
import unicodedata
import uuid
import zlib
from urllib.parse import parse_qs, quote, unquote, urlparse

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")

CHUNK_MIN, CHUNK_MAX = 64 << 10, 4 << 20
# bytes a chunk (one MoQ group). Lab v02183 (60 MB, relay over the WebSocket fallback, the receiver pulling 8 MB at a time):
# 64 KB 3.8 MB/s, 128 KB 8 MB/s, 256 KB 9 MB/s, 512 KB 12 MB/s, 1 MB 12 MB/s -- every one with page stalls under 0.1 s; what
# broke a page was 24 MB in flight, not the chunk size. KASTR_RC_CHUNK_KB is the lab's knob.
try:
    CHUNK = min(CHUNK_MAX, max(CHUNK_MIN, int(os.environ.get("KASTR_RC_CHUNK_KB") or 512) << 10))
except ValueError:
    CHUNK = 512 << 10
LEASE_S = 10.0                  # a session its page stops renewing ends
MAX_ITEMS = 10000               # files + folders in one offer
MAX_DEPTH = 32
MAX_REL = 1000                  # characters of a relative path
OFFERS_KEPT = 4                 # offers still served (an older copy whose transfer is under way)
DEFAULTS = {"rc_files": "on", "rc_file_max_mb": 2048, "rc_session_max_mb": 8192, "rc_files_auto_mb": 100,
            "rc_image_max_mb": 32, "rc_files_keep_min": 10}
OID_RE = re.compile(r"^[0-9a-f]{16}$")
RCID_RE = re.compile(r"^[a-z0-9]{8,32}$")
MARK = "application/x-kastr-rc"          # X11 target that says "KASTR put this here"
WIN_MARK = "KASTR remote files"           # the Windows clipboard format that says the same


# ---- names (pure, tested) ---------------------------------------------------------------------------------------------
WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {"COM%s" % c for c in "123456789¹²³"} \
    | {"LPT%s" % c for c in "123456789¹²³"}
BAD_CHARS = set('<>:"/\\|?*')


def clean_name(s):
    """One path component as it may be created on Windows AND Linux, or None (empty, ".", ".."). Bad characters become "_",
    trailing dots / spaces go (Windows drops them), a reserved device name (CON, NUL, COM1.txt ...) gets a "_" in front,
    long names are shortened (their extension kept)."""
    s = unicodedata.normalize("NFC", str(s or ""))
    s = "".join("_" if (c in BAD_CHARS or ord(c) < 32 or ord(c) == 127) else c for c in s)
    s = s.strip().rstrip(". ")
    if s in ("", ".", ".."):
        return None
    if s.split(".")[0].rstrip(" ").upper() in WIN_RESERVED:
        s = "_" + s
    if len(s) > 200:
        stem, dot, ext = s.rpartition(".")
        s = (stem[:200 - len(ext) - 1] + "." + ext) if dot and len(ext) <= 16 and stem else s[:200]
        s = s.rstrip(". ") or "_"
    return s


def clean_rel(p):
    """"a/b/c.txt" (either slash) -> ["a", "b", "c.txt"], or None: a ".." / "." step, an absolute path, a drive, a UNC or device
    prefix -- anything that could step out of the folder it lands in -- is refused, never "fixed"."""
    p = str(p or "")
    if not p or len(p) > MAX_REL or p[0] in "/\\" or re.match(r"^[A-Za-z]:", p) or "\0" in p:
        return None
    parts = [x for x in re.split(r"[\\/]+", p) if x != ""]
    if not parts or len(parts) > MAX_DEPTH or any(x.strip() in (".", "..") for x in parts):
        return None
    out = [clean_name(x) for x in parts]
    return None if any(x is None for x in out) else out


def unique_name(folder, name, exists=os.path.exists):
    """name, or "name (2).ext", "name (3).ext" ... -- whatever is free in `folder`."""
    if not exists(os.path.join(folder, name)):
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    for i in range(2, 10000):
        cand = "%s (%d)%s" % (stem, i, ("." + ext) if ext else "")
        if not exists(os.path.join(folder, cand)):
            return cand
    return "%s-%s%s" % (stem, uuid.uuid4().hex[:8], ("." + ext) if ext else "")


def device_path(p):
    """A path that names a device, a pipe or the object namespace -- never read from (\\\\.\\, \\\\?\\GLOBALROOT, \\??\\, CON...)."""
    s = str(p or "")
    low = s.replace("/", "\\").lower()
    if low.startswith("\\\\.\\") or low.startswith("\\??\\") or low.startswith("\\\\?\\globalroot") or low.startswith("\\device\\"):
        return True
    if low.startswith("\\\\?\\unc\\"):
        return False
    base = os.path.basename(s.rstrip("\\/")).split(".")[0].rstrip(" ").upper()
    if WINDOWS and base in WIN_RESERVED:
        return True
    if LINUX and (s.startswith("/dev/") or s.startswith("/proc/") or s.startswith("/sys/")):
        return True
    return False


def fmt_size(n):
    n = float(n or 0)
    for u in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return ("%d %s" % (n, u)) if u == "bytes" else ("%.1f %s" % (n, u) if n < 10 else "%d %s" % (round(n), u))
        n /= 1024.0


# ---- the clipboard formats (pure, tested) ----------------------------------------------------------------------------
DROPFILES_SIZE = 20   # DWORD pFiles; POINT pt; BOOL fNC; BOOL fWide


def build_dropfiles(paths):
    """CF_HDROP's HGLOBAL contents: DROPFILES {pFiles = 20, pt 0,0, fNC 0, fWide 1} + every path in UTF-16LE, each ending in
    NUL, the list ending in one more NUL."""
    head = struct.pack("<IiiII", DROPFILES_SIZE, 0, 0, 0, 1)
    body = "".join(str(p) + "\0" for p in paths) + "\0"
    return head + body.encode("utf-16-le")


def parse_dropfiles(buf):
    """CF_HDROP contents -> [paths] (wide or ANSI lists)."""
    b = bytes(buf or b"")
    if len(b) < DROPFILES_SIZE:
        return []
    off, _x, _y, _nc, wide = struct.unpack_from("<IiiII", b, 0)
    if off < DROPFILES_SIZE or off >= len(b):
        return []
    data = b[off:]
    if wide:
        if len(data) % 2:
            data = data[:-1]
        txt = data.decode("utf-16-le", "replace")
    else:
        txt = data.decode("mbcs" if WINDOWS else "latin-1", "replace")
    out = []
    for s in txt.split("\0"):
        if not s:
            break
        out.append(s)
    return out


def uri_of(path):
    p = os.path.abspath(path)
    if WINDOWS:
        p = "/" + p.replace("\\", "/")   # file:///C:/...
    return "file://" + quote(p, safe="/:@!$&'()*+,;=-._~")


def uri_list(paths):
    """text/uri-list (RFC 2483: CRLF, file:// URIs)."""
    return "".join(uri_of(p) + "\r\n" for p in paths).encode("utf-8")


def gnome_copied(paths):
    """x-special/gnome-copied-files: "copy" then one URI a line (GNOME Files, Nemo, Caja read it; Thunar / Dolphin read the
    uri-list)."""
    return ("copy\n" + "\n".join(uri_of(p) for p in paths)).encode("utf-8")


def parse_uris(text):
    """gnome-copied-files ("copy" / "cut" first) or a uri-list -> local file paths (other schemes and remote hosts dropped)."""
    out = []
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    if lines and lines[0].strip() in ("copy", "cut"):
        lines = lines[1:]
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        u = urlparse(ln)
        if u.scheme != "file" or u.netloc not in ("", "localhost"):
            continue
        p = unquote(u.path)
        if WINDOWS and re.match(r"^/[A-Za-z]:", p):
            p = p[1:].replace("/", "\\")
        out.append(p)
    return out


# ---- images: DIB <-> PNG (pure, tested; PIL is not in the build) -------------------------------------------------------
def _png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_encode(w, h, pix, channels=4, level=3):
    """Rows of 8-bit RGB / RGBA (top-down, no padding) -> PNG with filter None on every row (fast to write and to read back)."""
    stride = w * channels
    raw = b"".join(b"\x00" + pix[y * stride:(y + 1) * stride] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6 if channels == 4 else 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(raw, level)) + _png_chunk(b"IEND", b"")


def _swap_rb(buf, n):
    """BGR(A) <-> RGB(A) for a whole buffer of n-byte pixels (slices: no Python loop per pixel)."""
    b = bytearray(buf)
    b[0::n], b[2::n] = buf[2::n], buf[0::n]
    return bytes(b)


def dib_to_png(dib):
    """A packed DIB (CF_DIB / CF_DIBV5: BITMAPINFOHEADER / V4 / V5 + masks + palette + pixels) -> PNG bytes, or None for a
    layout not handled (16-bit, RLE, 1 / 4-bit). 32-bit: an all-zero alpha (BI_RGB "reserved") is opaque. BI_PNG inside a DIB
    is its own PNG."""
    b = bytes(dib or b"")
    if len(b) < 40:
        return None
    hs, w, h, _planes, bpp, comp = struct.unpack_from("<IiiHHI", b, 0)
    clr_used = struct.unpack_from("<I", b, 32)[0]
    if hs < 40 or hs > 124 or w <= 0 or h == 0 or w > 32768 or abs(h) > 32768:
        return None
    if comp == 5:   # BI_PNG
        data = b[hs:]
        return data if data.startswith(b"\x89PNG") else None
    top_down, h = h < 0, abs(h)
    off = hs
    masks = None
    if comp in (3, 6):   # BI_BITFIELDS / BI_ALPHABITFIELDS
        if hs >= 52:
            masks = struct.unpack_from("<IIII", b, 40) if hs >= 56 else struct.unpack_from("<III", b, 40) + (0,)
        else:
            n = 3 if comp == 3 else 4
            if len(b) < hs + 4 * n:
                return None
            masks = struct.unpack_from("<" + "I" * n, b, hs) + ((0,) if n == 3 else ())
            off += 4 * n
    elif comp != 0:
        return None
    pal = None
    if bpp == 8:
        nc = clr_used or 256
        if nc > 256 or len(b) < off + nc * 4:
            return None
        pal = b[off:off + nc * 4]
        off += nc * 4
    elif bpp not in (24, 32):
        return None
    if bpp == 32 and masks and masks[:3] != (0xFF0000, 0xFF00, 0xFF):
        return None
    stride = ((w * bpp + 31) // 32) * 4
    if len(b) < off + stride * h:
        return None
    px = b[off:off + stride * h]
    rows = [px[y * stride:(y + 1) * stride] for y in range(h)]
    if not top_down:
        rows.reverse()
    if bpp == 32:
        flat = b"".join(r[:w * 4] for r in rows)
        rgba = _swap_rb(flat, 4)
        amask = masks[3] if masks else 0
        if (masks is not None and amask == 0) or not any(rgba[3::4]):
            rgba = bytearray(rgba)
            rgba[3::4] = b"\xff" * (w * h)
            return png_encode(w, h, bytes(rgba), 4)
        return png_encode(w, h, rgba, 4)
    if bpp == 24:
        flat = b"".join(r[:w * 3] for r in rows)
        return png_encode(w, h, _swap_rb(flat, 3), 3)
    # 8-bit palette: three translate tables
    n = len(pal) // 4
    tr = [bytes(pal[i * 4 + k] if i < n else 0 for i in range(256)) for k in (2, 1, 0)]
    flat = b"".join(r[:w] for r in rows)
    out = bytearray(w * h * 3)
    out[0::3], out[1::3], out[2::3] = flat.translate(tr[0]), flat.translate(tr[1]), flat.translate(tr[2])
    return png_encode(w, h, bytes(out), 3)


def _unfilter(data, w, h, bpp, stride, slow_budget):
    """PNG row filters -> raw rows. None (Up via one big-int add per row, Sub via accumulate) are quick; Average and Paeth
    need a byte loop -- `slow_budget` bytes of those at most, else None (too slow without PIL)."""
    out = bytearray(stride * h)
    prev = bytes(stride)
    i = 0
    slow = 0
    m7 = int.from_bytes(b"\x7f" * stride, "big") if stride else 0
    m8 = int.from_bytes(b"\x80" * stride, "big") if stride else 0
    for y in range(h):
        if i + 1 + stride > len(data):
            return None
        ft = data[i]
        line = data[i + 1:i + 1 + stride]
        i += 1 + stride
        if ft == 0:
            row = line
        elif ft == 2:   # Up: bytewise (a + b) mod 256 across the whole row at once
            a, c = int.from_bytes(line, "big"), int.from_bytes(prev, "big")
            row = (((a & m7) + (c & m7)) ^ ((a ^ c) & m8)).to_bytes(stride, "big")
        elif ft == 1:   # Sub: a running sum per channel
            from itertools import accumulate
            r = bytearray(stride)
            for ch in range(bpp):
                r[ch::bpp] = bytes(map((255).__and__, accumulate(line[ch::bpp])))
            row = bytes(r)
        elif ft in (3, 4):
            slow += stride
            if slow > slow_budget:
                return None
            r = bytearray(line)
            for x in range(stride):
                left = r[x - bpp] if x >= bpp else 0
                up = prev[x]
                if ft == 3:
                    r[x] = (r[x] + ((left + up) >> 1)) & 255
                else:
                    ul = prev[x - bpp] if x >= bpp else 0
                    p = left + up - ul
                    pa, pb, pc = abs(p - left), abs(p - up), abs(p - ul)
                    r[x] = (r[x] + (left if pa <= pb and pa <= pc else (up if pb <= pc else ul))) & 255
            row = bytes(r)
        else:
            return None
        out[y * stride:(y + 1) * stride] = row
        prev = row
    return bytes(out)


def png_decode(png, slow_budget=6 << 20):
    """PNG -> (w, h, RGBA bytes top-down), or None (interlaced, 1 / 2 / 4-bit, too slow, damaged)."""
    b = bytes(png or b"")
    if not b.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    i, ihdr, plte, trns, idat = 8, None, None, None, []
    while i + 8 <= len(b):
        n, kind = struct.unpack_from(">I4s", b, i)
        data = b[i + 8:i + 8 + n]
        i += 12 + n
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", data[:13])
        elif kind == b"PLTE":
            plte = data
        elif kind == b"tRNS":
            trns = data
        elif kind == b"IDAT":
            idat.append(data)
        elif kind == b"IEND":
            break
    if not ihdr:
        return None
    w, h, depth, ct, _c, _f, inter = ihdr
    if inter or depth not in (8, 16) or ct not in (0, 2, 3, 4, 6) or (ct == 3 and depth != 8) or w <= 0 or h <= 0:
        return None
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    bpp = ch * depth // 8
    stride = w * bpp
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error:
        return None
    pix = _unfilter(raw, w, h, bpp, stride, slow_budget)
    if pix is None:
        return None
    if depth == 16:
        pix = pix[0::2]   # the high byte of every sample
    n = w * h
    out = bytearray(n * 4)
    if ct == 6:
        return w, h, pix
    if ct == 2:
        out[0::4], out[1::4], out[2::4] = pix[0::3], pix[1::3], pix[2::3]
        out[3::4] = b"\xff" * n
    elif ct == 0:
        out[0::4] = out[1::4] = out[2::4] = pix
        out[3::4] = b"\xff" * n
    elif ct == 4:
        out[0::4] = out[1::4] = out[2::4] = pix[0::2]
        out[3::4] = pix[1::2]
    else:
        if not plte:
            return None
        np_ = len(plte) // 3
        tr = [bytes(plte[k * 3 + c] if k < np_ else 0 for k in range(256)) for c in range(3)]
        ta = bytes((trns[k] if trns and k < len(trns) else 255) for k in range(256))
        out[0::4], out[1::4], out[2::4], out[3::4] = pix.translate(tr[0]), pix.translate(tr[1]), pix.translate(tr[2]), pix.translate(ta)
    return w, h, bytes(out)


def png_size(png):
    b = bytes(png or b"")
    if len(b) >= 24 and b.startswith(b"\x89PNG\r\n\x1a\n") and b[12:16] == b"IHDR":
        return struct.unpack(">II", b[16:24])
    return None


def png_to_dib(png, slow_budget=6 << 20):
    """PNG -> a packed CF_DIB (BITMAPINFOHEADER, bottom-up): 24-bit when it is opaque, 32-bit BI_RGB with its alpha otherwise
    (the "PNG" format beside it carries the real transparency). None when the PNG cannot be read quickly."""
    d = png_decode(png, slow_budget)
    if d is None:
        return None
    w, h, rgba = d
    opaque = all(x == 255 for x in rgba[3::4]) if len(rgba) < (1 << 16) else rgba[3::4].count(255) == w * h
    if opaque:
        rgb = bytearray(w * h * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = rgba[2::4], rgba[1::4], rgba[0::4]   # BGR
        stride, bpp, src, rs = ((w * 24 + 31) // 32) * 4, 24, bytes(rgb), w * 3
    else:
        stride, bpp, src, rs = w * 4, 32, _swap_rb(rgba, 4), w * 4
    pad = b"\x00" * (stride - rs)
    rows = [src[y * rs:(y + 1) * rs] + pad for y in range(h - 1, -1, -1)]
    head = struct.pack("<IiiHHIIiiII", 40, w, h, 1, bpp, 0, stride * h, 2835, 2835, 0, 0)
    return head + b"".join(rows)


def bmp_to_dib(bmp):
    """A .bmp file (image/bmp on X11) -> its packed DIB (the 14-byte BITMAPFILEHEADER dropped)."""
    b = bytes(bmp or b"")
    return b[14:] if len(b) > 54 and b[:2] == b"BM" else None


# ---- what was copied: a scan that never follows a link out of the copied set ------------------------------------------
def _is_link(st, path):
    import stat as _st
    if _st.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0) or 0
    if attrs & 0x400:   # FILE_ATTRIBUTE_REPARSE_POINT: a junction, a symlink, a mount point (OneDrive placeholders are not)
        tag = getattr(st, "st_reparse_tag", 0) or 0
        return tag in (0xA0000003, 0xA000000C) or tag == 0   # IO_REPARSE_TAG_MOUNT_POINT / SYMLINK (unknown tag: be safe)
    return False


def scan(paths, limit_items=MAX_ITEMS):
    """Copied paths -> (items [{p, n, d, t}], sources [abs path | None for a folder], skipped {why: count}). Relative names keep
    each top-level item's own name; folders are walked depth-first in name order; symlinks / junctions anywhere (the copied
    item itself too) are skipped, so are devices, pipes, sockets and anything unreadable."""
    import stat as _st
    items, srcs, skipped = [], [], {}
    seen_top = set()

    def skip(why):
        skipped[why] = skipped.get(why, 0) + 1

    def add(rel, src, st, is_dir):
        if len(items) >= limit_items:
            skip("too many")
            return False
        items.append({"p": rel, "n": 0 if is_dir else int(st.st_size), "d": 1 if is_dir else 0, "t": int(st.st_mtime)})
        srcs.append(None if is_dir else src)
        return True

    def walk(folder, rel, depth):
        if depth > MAX_DEPTH:
            skip("too deep")
            return
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            skip("unreadable")
            return
        for nm in names:
            full = os.path.join(folder, nm)
            try:
                st = os.lstat(full)
            except OSError:
                skip("unreadable")
                continue
            if _is_link(st, full):
                skip("links")
                continue
            r = rel + "/" + nm
            if _st.S_ISDIR(st.st_mode):
                if add(r, full, st, True):
                    walk(full, r, depth + 1)
            elif _st.S_ISREG(st.st_mode):
                add(r, full, st, False)
            else:
                skip("special")

    for p in paths:
        p = str(p or "")
        if not p or device_path(p):
            skip("device")
            continue
        try:
            st = os.lstat(p)
        except OSError:
            skip("unreadable")
            continue
        if _is_link(st, p):
            skip("links")
            continue
        nm = os.path.basename(p.rstrip("\\/")) or "item"
        key = nm.lower()
        if key in seen_top:
            skip("duplicate")
            continue
        seen_top.add(key)
        if _st.S_ISDIR(st.st_mode):
            if add(nm, p, st, True):
                walk(p, nm, 1)
        elif _st.S_ISREG(st.st_mode):
            add(nm, p, st, False)
        else:
            skip("special")
    return items, srcs, skipped


def chunk_plan(items, cs):
    """-> (starts, total chunks): starts[i] = the first chunk of item i (folders and empty files have none)."""
    starts, n = [], 0
    for it in items:
        starts.append(n)
        if not it.get("d"):
            n += (int(it.get("n") or 0) + cs - 1) // cs
    return starts, n


def chunk_at(items, starts, cs, c):
    """Global chunk number -> (item index, byte offset, length), or None."""
    import bisect
    i = bisect.bisect_right(starts, c) - 1
    while i >= 0 and (items[i].get("d") or not items[i].get("n")):
        i -= 1
    if i < 0:
        return None
    k = c - starts[i]
    n = int(items[i]["n"])
    off = k * cs
    if k < 0 or off >= n:
        return None
    return i, off, min(cs, n - off)


def offer_summary(items):
    files = sum(1 for it in items if not it.get("d"))
    dirs = sum(1 for it in items if it.get("d"))
    total = sum(int(it.get("n") or 0) for it in items if not it.get("d"))
    return files, dirs, total


def describe(items, kind="files"):
    """"report.docx" / "3 files" / "the folder Photos" / "a picture" -- for the notes."""
    if kind == "image":
        return "a picture"
    tops = [it for it in items if "/" not in it["p"]]
    files, dirs, _ = offer_summary(items)
    if len(tops) == 1:
        return ("the folder " if tops[0].get("d") else "") + tops[0]["p"]
    return "%d file%s" % (files, "" if files == 1 else "s") + (" in %d folder%s" % (dirs, "" if dirs == 1 else "s") if dirs else "")


# ---- an incoming transfer -------------------------------------------------------------------------------------------------
class Incoming:
    """The peer's offer being written into tmp/<oid>/: the sanitized plan, which chunks arrived, per-file progress."""

    def __init__(self, oid, offer, folder, cs):
        self.oid, self.offer, self.folder, self.cs = oid, offer, folder, cs
        self.kind = offer.get("kind") or "files"
        self.items = offer["items"]
        self.starts, self.N = chunk_plan(self.items, cs)
        self.paths = [None] * len(self.items)   # where item i goes (None: skipped)
        self.left = {}                          # item index -> chunks still missing
        self.got = bytearray((self.N + 7) // 8)
        self.ngot = 0
        self.bytes = 0
        self.total = 0
        self.skipped = {}
        self.state = "get"
        self.result = None
        self.lock = threading.Lock()
        self.at = time.time()

    def has(self, c):
        return bool(self.got[c >> 3] & (1 << (c & 7)))

    def need_ranges(self):
        """Chunk ranges [a, b) still wanted (skipped files' chunks never are)."""
        out = []
        for i, it in enumerate(self.items):
            if it.get("d") or not it.get("n") or self.paths[i] is None:
                continue
            a = self.starts[i]
            b = a + (int(it["n"]) + self.cs - 1) // self.cs
            if out and out[-1][1] == a:
                out[-1][1] = b
            else:
                out.append([a, b])
        return out

    def wanted(self):
        return sum(b - a for a, b in self.need_ranges())

    def files_done(self):
        return sum(1 for i, it in enumerate(self.items) if not it.get("d") and self.paths[i] is not None and self.left.get(i, 0) == 0)

    def nfiles(self):
        return sum(1 for i, it in enumerate(self.items) if not it.get("d") and self.paths[i] is not None)

    def progress(self):
        return {"oid": self.oid, "state": self.state, "got": self.ngot, "N": self.wanted(), "bytes": self.bytes, "total": self.total,
                "files": self.files_done(), "nfiles": self.nfiles(), "result": self.result}


def plan_incoming(offer, folder, cs):
    """Validate + sanitize the peer's offer and lay it out under `folder` -> Incoming. Raises ValueError with the reason."""
    if not isinstance(offer, dict) or not OID_RE.match(str(offer.get("oid") or "")):
        raise ValueError("bad offer")
    items = offer.get("items")
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        raise ValueError("too many items" if isinstance(items, list) and items else "nothing offered")
    clean = []
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("bad item")
        try:
            n = int(it.get("n") or 0)
            t = int(it.get("t") or 0)
        except (TypeError, ValueError):
            raise ValueError("bad item")
        if n < 0 or n > (1 << 44):
            raise ValueError("bad size")
        clean.append({"p": str(it.get("p") or ""), "n": 0 if it.get("d") else n, "d": 1 if it.get("d") else 0, "t": t})
    inc = Incoming(str(offer["oid"]), dict(offer, items=clean), folder, cs)
    taken = {}
    for i, it in enumerate(clean):
        parts = clean_rel(it["p"])
        if parts is None:
            inc.skipped["names"] = inc.skipped.get("names", 0) + 1
            continue
        key = "/".join(parts).lower()
        parent = "/".join(parts[:-1]).lower()
        if key in taken or (parent and taken.get(parent) == "f"):
            inc.skipped["names"] = inc.skipped.get("names", 0) + 1
            continue
        for k in range(1, len(parts)):   # implied folders
            pk = "/".join(parts[:k]).lower()
            if taken.get(pk) == "f":
                break
            taken.setdefault(pk, "d")
        else:
            taken[key] = "d" if it["d"] else "f"
            inc.paths[i] = os.path.join(folder, *parts)
            if not it["d"]:
                inc.total += it["n"]
                k = (it["n"] + cs - 1) // cs
                if k:
                    inc.left[i] = k
            continue
        inc.skipped["names"] = inc.skipped.get("names", 0) + 1
    if not any(p is not None for p in inc.paths):
        raise ValueError("no usable names")
    return inc


# ---- clipboard backends ---------------------------------------------------------------------------------------------------
class MockClip:
    """Tests and labs on a desktop nobody must touch (KASTR_RC_MOCK=1): a clipboard in memory."""
    name = "mock"

    def __init__(self):
        self.content = {}
        self.seq = 0
        self.ours = None
        self.puts = []

    def set(self, **content):   # tests: someone copied
        self.content = content
        self.seq += 1

    def signature(self):
        return self.seq

    def read(self, image_max):
        return dict(self.content)

    def put_files(self, paths, oid):
        self.content = {"files": list(paths), "ours": True}
        self.seq += 1
        self.ours = self.seq
        self.puts.append(("files", list(paths)))
        return True

    def put_image(self, png, oid):
        self.content = {"image": png, "ours": True}
        self.seq += 1
        self.ours = self.seq
        self.puts.append(("image", len(png)))
        return True

    def still_ours(self):
        return self.ours is not None and self.ours == self.seq

    def release(self):
        if self.still_ours():
            self.content = {}
            self.seq += 1
        self.ours = None

    def close(self):
        pass


class WinClip:
    """The Windows clipboard (ctypes, a message-only window as its owner). Reads CF_HDROP / "PNG" / CF_DIBV5 / CF_DIB; writes
    CF_HDROP + "Preferred DropEffect" (copy) or "PNG" + CF_DIB, each with WIN_MARK so our own placement is never offered back."""
    name = "windows"

    def __init__(self):
        u, k = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        self.u, self.k = u, k
        vp = ctypes.c_void_p
        u.GetClipboardData.restype, u.GetClipboardData.argtypes = vp, [ctypes.c_uint]
        u.SetClipboardData.restype, u.SetClipboardData.argtypes = vp, [ctypes.c_uint, vp]
        u.OpenClipboard.argtypes = [vp]
        u.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
        u.RegisterClipboardFormatW.restype, u.RegisterClipboardFormatW.argtypes = ctypes.c_uint, [ctypes.c_wchar_p]
        u.GetClipboardSequenceNumber.restype = ctypes.c_uint32
        u.CreateWindowExW.restype = vp
        u.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, vp, vp, vp, vp]
        k.GlobalAlloc.restype, k.GlobalAlloc.argtypes = vp, [ctypes.c_uint, ctypes.c_size_t]
        k.GlobalLock.restype, k.GlobalLock.argtypes = vp, [vp]
        k.GlobalUnlock.argtypes = [vp]
        k.GlobalSize.restype, k.GlobalSize.argtypes = ctypes.c_size_t, [vp]
        k.GlobalFree.restype, k.GlobalFree.argtypes = vp, [vp]
        self.cf_png = u.RegisterClipboardFormatW("PNG")
        self.cf_effect = u.RegisterClipboardFormatW("Preferred DropEffect")
        self.cf_mark = u.RegisterClipboardFormatW(WIN_MARK)
        self.hwnd = u.CreateWindowExW(0, "STATIC", "KASTR clipboard", 0, 0, 0, 0, 0, vp(-3), None, None, None)   # HWND_MESSAGE
        self.ours = None

    def signature(self):
        return int(self.u.GetClipboardSequenceNumber())

    def _open(self):
        for _ in range(20):
            if self.u.OpenClipboard(self.hwnd):
                return True
            time.sleep(0.02)
        return False

    def _get(self, fmt, cap):
        h = self.u.GetClipboardData(fmt)
        if not h:
            return None
        n = int(self.k.GlobalSize(h))
        if n <= 0 or n > cap:
            return None
        p = self.k.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.string_at(p, n)
        finally:
            self.k.GlobalUnlock(h)

    def read(self, image_max):
        if not self._open():
            return None
        try:
            ok = self.u.IsClipboardFormatAvailable
            if ok(self.cf_mark):
                return {"ours": True}
            if ok(15):   # CF_HDROP
                return {"files": parse_dropfiles(self._get(15, 64 << 20) or b"")}
            if ok(13) or ok(1):   # CF_UNICODETEXT / CF_TEXT: text travels on its own (kastr_rc) and wins over a picture
                return {"text": True}
            if ok(self.cf_png):
                b = self._get(self.cf_png, image_max)
                if b and b.startswith(b"\x89PNG"):
                    return {"image": b}
            for fmt in (17, 8):   # CF_DIBV5, CF_DIB
                if ok(fmt):
                    d = self._get(fmt, 600 << 20)
                    png = dib_to_png(d) if d else None
                    if png and len(png) <= image_max:
                        return {"image": png}
                    return {"image_too_big": True} if png else {}
            return {}
        finally:
            self.u.CloseClipboard()

    def _put(self, formats):
        if not self._open():
            return False
        ok = True
        try:
            self.u.EmptyClipboard()
            for fmt, data in formats:
                h = self.k.GlobalAlloc(0x0002, len(data))   # GMEM_MOVEABLE
                if not h:
                    ok = False
                    continue
                p = self.k.GlobalLock(h)
                ctypes.memmove(p, data, len(data))
                self.k.GlobalUnlock(h)
                if not self.u.SetClipboardData(fmt, h):
                    self.k.GlobalFree(h)
                    ok = False
        finally:
            self.u.CloseClipboard()
        self.ours = self.signature()
        return ok

    def put_files(self, paths, oid):
        return self._put([(15, build_dropfiles(paths)), (self.cf_effect, struct.pack("<I", 1)), (self.cf_mark, oid.encode() + b"\0")])

    def put_image(self, png, oid):
        fm = [(self.cf_png, png)]
        dib = png_to_dib(png)
        if dib:
            fm.append((8, dib))
        fm.append((self.cf_mark, oid.encode() + b"\0"))
        return self._put(fm)

    def still_ours(self):
        return self.ours is not None and self.ours == self.signature()

    def release(self):
        if self.still_ours() and self._open():
            try:
                self.u.EmptyClipboard()
            finally:
                self.u.CloseClipboard()
        self.ours = None

    def close(self):
        pass


def make_clip():
    if os.environ.get("KASTR_RC_MOCK") == "1":
        return MockClip()
    if WINDOWS:
        return WinClip()
    if LINUX:
        import kastr_rcfiles_x11
        return kastr_rcfiles_x11.X11Clip()
    raise OSError("no clipboard here")


# ---- where a drop lands ---------------------------------------------------------------------------------------------------
def _known_folder(guid):
    """SHGetKnownFolderPath (Windows) -> path or None."""
    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]
    u = uuid.UUID(guid)
    g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    p = ctypes.c_wchar_p()
    sh = ctypes.WinDLL("shell32")
    sh.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    if sh.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) != 0:
        return None
    try:
        return p.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(p)


def downloads_dir():
    if WINDOWS:
        try:
            d = _known_folder("374DE290-123F-4565-9164-39C4925E467B")
            if d:
                return d
        except Exception:
            pass
        return os.path.join(os.path.expanduser("~"), "Downloads")
    return _xdg_dir("DOWNLOAD", "Downloads")


def desktop_dir():
    if WINDOWS:
        try:
            d = _known_folder("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")
            if d:
                return d
        except Exception:
            pass
        return os.path.join(os.path.expanduser("~"), "Desktop")
    return _xdg_dir("DESKTOP", "Desktop")


def _xdg_dir(key, default):
    home = os.path.expanduser("~")
    try:
        with open(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "user-dirs.dirs"), encoding="utf-8") as f:
            for ln in f:
                m = re.match(r'^\s*XDG_%s_DIR\s*=\s*"(.*)"\s*$' % key, ln)
                if m:
                    return m.group(1).replace("$HOME", home)
    except OSError:
        pass
    return os.path.join(home, default)


EXPLORER_PS = r"""$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$h = [int64]$env:KASTR_HWND; $t = [string]$env:KASTR_TITLE; $best = $null
foreach ($w in (New-Object -ComObject Shell.Application).Windows()) {
  if ([int64]$w.HWND -ne $h) { continue }
  $p = $w.Document.Folder.Self.Path
  if (-not $p) { continue }
  if ($w.LocationName -and $t.StartsWith([string]$w.LocationName)) { $best = $p; break }
  if (-not $best) { $best = $p }
}
if ($best) { [Console]::Out.Write($best) }
"""


def win_folder_at(px, py):
    """The folder a drop at the screen point (px, py) means on Windows -> (path, "folder" | "desktop") or (None, what is there).
    An Explorer window (CabinetWClass: its folder through Shell.Application -- the tab whose name the window title shows) or
    the desktop (Progman / WorkerW); nothing else takes files this way."""
    import subprocess
    u = ctypes.WinDLL("user32")

    class PT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    u.WindowFromPoint.restype, u.WindowFromPoint.argtypes = ctypes.c_void_p, [PT]
    u.GetAncestor.restype, u.GetAncestor.argtypes = ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_uint]
    u.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    u.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    h = u.WindowFromPoint(PT(int(px), int(py)))
    root = u.GetAncestor(h, 2) if h else None
    if not root:
        return None, "nothing"
    buf = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(root, buf, 256)
    cls = buf.value
    if cls in ("Progman", "WorkerW"):
        return desktop_dir(), "desktop"
    if cls != "CabinetWClass":
        return None, cls
    u.GetWindowTextW(root, buf, 256)
    env = dict(os.environ, KASTR_HWND=str(int(root)), KASTR_TITLE=buf.value)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", EXPLORER_PS], capture_output=True, timeout=8,
                           env=env, creationflags=0x08000000)   # CREATE_NO_WINDOW
        p = r.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.TimeoutExpired):
        p = ""
    return (p, "folder") if p and os.path.isdir(p) else (None, "explorer")


def deliver(top_paths, dest):
    """Move each top-level item of a finished transfer into `dest` under a free name -> [final names]."""
    os.makedirs(dest, exist_ok=True)
    out = []
    for p in top_paths:
        nm = unique_name(dest, os.path.basename(p))
        shutil.move(p, os.path.join(dest, nm))
        out.append(nm)
    return out


# ---- the session ------------------------------------------------------------------------------------------------------------
def _cfg(ini, key):
    v = None
    try:
        v = ini(key) if ini else None
    except Exception:
        v = None
    env = os.environ.get("KASTR_" + key.upper())
    if env:
        v = env
    d = DEFAULTS[key]
    if isinstance(d, int):
        try:
            return max(0, int(float(v))) if v not in (None, "") else d
        except ValueError:
            return d
    return str(v).strip().lower() if v not in (None, "") else d


def temp_root():
    return os.path.join(tempfile.gettempdir(), "KASTR-rc")


def _pid_alive(pid):
    if pid == os.getpid():
        return True
    if WINDOWS:
        k = ctypes.WinDLL("kernel32")
        k.OpenProcess.restype = ctypes.c_void_p
        h = k.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        code = ctypes.c_uint32()
        k.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))
        k.CloseHandle(ctypes.c_void_p(h))
        return code.value == 259   # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def sweep_stale(root=None, log=None):
    """At start: session folders left by a KASTR that is gone (crashed, killed) are deleted."""
    root = root or temp_root()
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    n = 0
    for nm in names:
        m = re.match(r"^(\d+)-[a-z0-9]{8,32}$", nm)
        if not m or _pid_alive(int(m.group(1))):
            continue
        shutil.rmtree(os.path.join(root, nm), ignore_errors=True)
        n += 1
    if n and log:
        log("rc files: removed %d stale transfer folder%s" % (n, "" if n == 1 else "s"))
    return n


class Session:
    def __init__(self, rcid, role, name, cfg, folder, now):
        self.rcid, self.role, self.name, self.cfg, self.folder = rcid, role, name, cfg, folder
        self.lease = now + LEASE_S
        self.offers = {}            # oid -> {offer, srcs, image}
        self.order = []             # oids, newest last
        self.current = None         # the oid of what is on my clipboard now (None: nothing to offer)
        self.incoming = {}          # oid -> Incoming
        self.sent = {}              # oid -> set of chunks served (unique bytes count once)
        self.sent_bytes = 0
        self.recv_bytes = 0
        self.base = None            # the clipboard's signature when the session began / last looked at
        self.scan = None            # a scan in progress (thread)
        self.note = None            # the last "why there is no offer" (too big, links skipped ...)
        self.ended = None

    def used(self):
        return self.sent_bytes + self.recv_bytes


class Files:
    """One session at a time on this computer (one grant)."""

    def __init__(self, clip=None, log=None, ini=None, clock=time.monotonic, rc_get=None, root=None, place=None):
        self._clip = clip
        self.log = log or (lambda m: None)
        self.ini = ini
        self.clock = clock
        self.rc_get = rc_get          # -> the kastr_rc.RemoteControl (the sharer's grant), or None
        self.root = root or temp_root()
        self.place_drop = place       # tests: (inc, top paths, pt) -> result
        self.lock = threading.RLock()
        self.s = None
        self.last = None
        self.kept = []                # [(folder, until)]: finished transfers kept for a late paste
        self._sweeper = None
        self._swept = False

    # ---- plumbing
    def clip(self):
        if self._clip is None:
            self._clip = make_clip()
        return self._clip

    def caps(self):
        cfg = self._config()
        on = cfg["rc_files"] not in ("off", "0", "no", "false")
        return {"files": on, "images": on, "drop": on, "chunk": CHUNK, "max": cfg["rc_file_max_mb"] << 20,
                "sessionMax": cfg["rc_session_max_mb"] << 20, "auto": cfg["rc_files_auto_mb"] << 20,
                "imageMax": cfg["rc_image_max_mb"] << 20, "keepMin": cfg["rc_files_keep_min"],
                "platform": "windows" if WINDOWS else ("x11" if LINUX else sys.platform)}

    def _config(self):
        return {k: _cfg(self.ini, k) for k in DEFAULTS}

    def _grant_ok(self, rcid):
        rc = self.rc_get() if self.rc_get else None
        g = getattr(rc, "grant", None) if rc is not None else None
        return bool(g) and g.get("rcid") == rcid

    # ---- lifecycle
    def begin(self, rcid, role, name=""):
        if not RCID_RE.match(str(rcid or "")) or role not in ("ctl", "sharer"):
            return {"ok": False, "error": "bad session"}, 400
        caps = self.caps()
        if not caps["files"]:
            return {"ok": False, "error": "file transfer is switched off on this computer (kastr.ini rc_files)", "caps": caps}, 409
        if role == "sharer" and not self._grant_ok(rcid):
            return {"ok": False, "error": "no remote-control grant for that session"}, 403
        with self.lock:
            if not self._swept:
                self._swept = True
                try:
                    sweep_stale(self.root, self.log)
                except Exception:
                    pass
            s = self.s
            if s is not None and s.rcid == rcid:
                s.lease = self.clock() + LEASE_S
                return {"ok": True, "caps": caps, "status": self.status()}, 200
            if s is not None:
                self._end_locked("replaced")
            folder = os.path.join(self.root, "%d-%s" % (os.getpid(), rcid))
            s = self.s = Session(rcid, role, str(name or "")[:40], self._config(), folder, self.clock())
            try:
                s.base = self.clip().signature()   # only what is copied FROM NOW ON travels
            except Exception as e:
                s.base = None
                self.log("rc files: clipboard: %s" % e)
        self.log("rc files: session %s begins (%s, %s)" % (rcid, "sharer" if role == "sharer" else "controller", self.clip().name))
        self._sweep_start()
        return {"ok": True, "caps": caps, "status": self.status()}, 200

    def end(self, rcid=None, why="stopped"):
        with self.lock:
            s = self.s
            if s is None or (rcid and s.rcid != rcid):
                return False
            self._end_locked(why)
        return True

    def _end_locked(self, why):
        s = self.s
        self.s = None
        s.ended = why
        self.last = {"rcid": s.rcid, "why": why, "sent": s.sent_bytes, "recv": s.recv_bytes}
        for inc in s.incoming.values():
            if inc.state == "get":
                inc.state = "cancel"
                shutil.rmtree(inc.folder, ignore_errors=True)   # unfinished: gone now
        keep = s.cfg["rc_files_keep_min"] * 60
        placed = [inc for inc in s.incoming.values() if inc.state == "done" and inc.result and inc.result.get("placed") == "clipboard"]
        try:
            still = bool(placed) and self.clip().still_ours()
        except Exception:
            still = False
        if still and keep > 0:
            self.kept.append((s.folder, self.clock() + keep))
            self.log("rc files: session %s ended (%s) -- what was received stays on the clipboard %d min" % (s.rcid, why, keep // 60))
        else:
            if still:
                try:
                    self.clip().release()
                except Exception:
                    pass
            shutil.rmtree(s.folder, ignore_errors=True)
            self.log("rc files: session %s ended (%s), temp files removed" % (s.rcid, why))

    def _sweep_start(self):
        if self._sweeper is None or not self._sweeper.is_alive():
            self._sweeper = threading.Thread(target=self._sweep_loop, name="kastr-rcfiles-sweep", daemon=True)
            self._sweeper.start()

    def _sweep_loop(self):
        while True:
            time.sleep(5)
            if self.tick() is False:
                return

    def tick(self):
        """The lease, the sharer's grant, the kept folders. -> False once there is nothing left to watch."""
        with self.lock:
            s = self.s
            if s is not None:
                if self.clock() > s.lease:
                    self._end_locked("timeout")
                elif s.role == "sharer" and not self._grant_ok(s.rcid):
                    self._end_locked("control ended")
            now = self.clock()
            for folder, until in list(self.kept):
                if now >= until:
                    self.kept.remove((folder, until))
                    try:
                        if self.s is None:
                            self.clip().release()   # the clipboard must not keep pointing at files that are gone
                    except Exception:
                        pass
                    shutil.rmtree(folder, ignore_errors=True)
                    self.log("rc files: kept transfer folder removed")
            return self.s is not None or bool(self.kept)

    def shutdown(self):
        """KASTR closing: nothing stays behind."""
        with self.lock:
            if self.s is not None:
                self._end_locked("closed")
            for folder, _u in self.kept:
                shutil.rmtree(folder, ignore_errors=True)
            if self.kept:
                try:
                    self.clip().release()
                except Exception:
                    pass
            self.kept = []

    def _sess(self, rcid):
        s = self.s
        if s is None or s.rcid != rcid:
            raise PermissionError("no file-transfer session")
        return s

    # ---- my clipboard -> an offer
    def renew(self, rcid, now=False):
        with self.lock:
            try:
                s = self._sess(rcid)
            except PermissionError:
                return {"ok": False, "error": "no file-transfer session", "ended": (self.last or {}).get("why", "")}, 409
            s.lease = self.clock() + LEASE_S
            if s.role == "sharer" and not self._grant_ok(rcid):
                self._end_locked("control ended")
                return {"ok": False, "error": "control ended", "ended": "control ended"}, 409
        self._poll(s, wait=now)
        return dict(self.status(), ok=True), 200

    def _poll(self, s, wait=False):
        try:
            sig = self.clip().signature()
        except Exception:
            return
        if sig is None or sig == s.base:
            if wait and s.scan is not None:
                s.scan.join(3.0)
            return
        s.base = sig
        th = threading.Thread(target=self._read_clip, args=(s, sig), name="kastr-rcfiles-scan", daemon=True)
        s.scan = th
        th.start()
        if wait:
            th.join(3.0)

    def _read_clip(self, s, sig):
        try:
            got = self.clip().read(s.cfg["rc_image_max_mb"] << 20)
        except Exception as e:
            self.log("rc files: reading the clipboard: %s" % e)
            return
        if got is None:
            return   # it was busy: the next look tries again
        with self.lock:
            if self.s is not s:
                return
        if got.get("ours"):   # what I received replaced my own copy there: nothing of mine to offer now
            with self.lock:
                if self.s is s:
                    s.current = None
            return
        offer = None
        if got.get("files"):
            items, srcs, skipped = scan(got["files"])
            files, dirs, total = offer_summary(items)
            if not items:
                s.note = {"why": "nothing", "skipped": skipped}
            else:
                offer = {"kind": "files", "items": items, "srcs": srcs, "skipped": skipped, "total": total}
                if total > s.cfg["rc_file_max_mb"] << 20:
                    offer["over"] = 1
        elif got.get("image"):
            png = got["image"]
            wh = png_size(png) or (0, 0)
            offer = {"kind": "image", "items": [{"p": "picture.png", "n": len(png), "d": 0, "t": int(time.time())}], "srcs": [None],
                     "image": png, "skipped": {}, "total": len(png), "w": wh[0], "h": wh[1]}
        elif got.get("image_too_big"):
            s.note = {"why": "image too big"}
        with self.lock:
            if self.s is not s:
                return
            if offer is None:
                if s.current is not None:
                    self.log("rc files: the clipboard holds no files now")
                s.current = None
                return
            oid = uuid.uuid4().hex[:16]
            files, dirs, total = offer_summary(offer["items"])
            pub = {"oid": oid, "kind": offer["kind"], "cs": CHUNK, "items": offer["items"], "total": total, "files": files, "dirs": dirs,
                   "name": describe(offer["items"], offer["kind"]), "skipped": offer["skipped"], "at": int(time.time() * 1000)}
            if offer.get("over"):
                pub["over"] = 1
            if offer["kind"] == "image":
                pub.update(w=offer["w"], h=offer["h"])
            starts, nchunks = chunk_plan(offer["items"], CHUNK)
            s.offers[oid] = {"pub": pub, "srcs": offer["srcs"], "image": offer.get("image"), "starts": starts, "N": nchunks}
            s.order.append(oid)
            while len(s.order) > OFFERS_KEPT:
                s.offers.pop(s.order.pop(0), None)
            s.current = oid
            s.note = None
        self.log("rc files: offering %s (%s)%s" % (pub["name"], fmt_size(total), " -- over the limit" if pub.get("over") else ""))

    def chunk(self, rcid, oid, c):
        """GET /api/rcfiles/chunk: one chunk of one of MY offers -> bytes. Re-opened every time, never through a link."""
        with self.lock:
            s = self._sess(rcid)
            o = s.offers.get(oid)
            if o is None:
                raise LookupError("no such offer")
            if o["pub"].get("over"):
                raise PermissionError("over the per-transfer limit")
            sent = s.sent.setdefault(oid, set())
            fresh = c not in sent
            hit = chunk_at(o["pub"]["items"], o["starts"], CHUNK, c)
            if hit is None:
                raise LookupError("no such chunk")
            i, off, n = hit
            if fresh and s.used() + n > s.cfg["rc_session_max_mb"] << 20:
                raise PermissionError("over this session's limit")
        if o["image"] is not None:
            data = o["image"][off:off + n]
        else:
            data = _read_at(o["srcs"][i], off, n)
        if len(data) != n:
            raise IOError("the file changed while it was being copied")
        with self.lock:
            if fresh and c not in sent:
                sent.add(c)
                s.sent_bytes += n
        return data

    def sent(self, rcid, oid, state, who=""):
        """The page: the other side finished (or cancelled) taking one of my offers -- for the log (and the sharer's note)."""
        with self.lock:
            s = self._sess(rcid)
            o = s.offers.get(oid)
            name = o["pub"]["name"] if o else "files"
            size = o["pub"]["total"] if o else 0
        if state == "done":
            self.log("rc files: %s copied %s (%s) from this computer" % (who or "the other side", name, fmt_size(size)))
        else:
            self.log("rc files: %s %s taking %s" % (who or "the other side", "cancelled" if state == "cancel" else "failed", name))
        return {"ok": True}, 200

    # ---- their offer -> here
    def recv(self, rcid, offer, pt=None):
        with self.lock:
            s = self._sess(rcid)
            if not isinstance(offer, dict):
                return {"ok": False, "error": "bad offer"}, 400
            oid = str(offer.get("oid") or "")
            if oid in s.incoming and s.incoming[oid].state in ("get", "done"):
                inc = s.incoming[oid]
                return {"ok": True, "oid": oid, "need": inc.need_ranges(), "progress": inc.progress()}, 200
            if offer.get("kind") == "drop" and s.role != "sharer":
                return {"ok": False, "error": "only the shared computer takes a drop"}, 403
            try:
                cs = int(offer.get("cs") or CHUNK)
            except (TypeError, ValueError):
                cs = 0
            if not (CHUNK_MIN <= cs <= CHUNK_MAX):
                return {"ok": False, "error": "bad chunk size"}, 400
            try:
                inc = plan_incoming(offer, os.path.join(s.folder, oid), cs)
            except ValueError as e:
                return {"ok": False, "error": str(e)}, 400
            if inc.kind == "image" and inc.total > s.cfg["rc_image_max_mb"] << 20:
                return {"ok": False, "error": "that picture is over the %d MB limit" % s.cfg["rc_image_max_mb"], "why": "limit"}, 413
            if inc.total > s.cfg["rc_file_max_mb"] << 20:
                return {"ok": False, "error": "that is %s -- over the %s limit for one transfer" % (fmt_size(inc.total), fmt_size(s.cfg["rc_file_max_mb"] << 20)),
                        "why": "limit"}, 413
            if s.used() + inc.total > s.cfg["rc_session_max_mb"] << 20:
                return {"ok": False, "error": "over this session's %s limit" % fmt_size(s.cfg["rc_session_max_mb"] << 20), "why": "limit"}, 413
            try:
                os.makedirs(inc.folder, exist_ok=True)
                free = shutil.disk_usage(inc.folder).free
            except OSError as e:
                return {"ok": False, "error": "no room for it: %s" % e}, 507
            if inc.total + (256 << 20) > free:
                shutil.rmtree(inc.folder, ignore_errors=True)
                return {"ok": False, "error": "not enough free disk space (%s free)" % fmt_size(free), "why": "disk"}, 507
            if isinstance(pt, (list, tuple)) and len(pt) == 2:
                inc.pt = (pt[0], pt[1])
            else:
                inc.pt = None
            inc.who = str(offer.get("by") or "")[:40]
            try:
                for i, it in enumerate(inc.items):
                    p = inc.paths[i]
                    if p is None:
                        continue
                    if it["d"]:
                        os.makedirs(p, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(p), exist_ok=True)
                        with open(p, "xb") as f:
                            if it["n"]:
                                f.truncate(it["n"])
            except OSError as e:
                shutil.rmtree(inc.folder, ignore_errors=True)
                return {"ok": False, "error": "could not lay it out: %s" % e}, 500
            s.incoming[oid] = inc
            s.recv_bytes += inc.total   # reserved against the session cap now
        self.log("rc files: receiving %s (%s, %d chunk%s)" % (describe(inc.items, inc.kind), fmt_size(inc.total), inc.wanted(), "" if inc.wanted() == 1 else "s"))
        out = {"ok": True, "oid": oid, "need": inc.need_ranges(), "progress": inc.progress()}
        if inc.wanted() == 0:
            out["progress"] = self.done(rcid, oid)[0].get("progress")
        return out, 200

    def put(self, rcid, oid, c, data):
        with self.lock:
            s = self._sess(rcid)
            inc = s.incoming.get(oid)
            if inc is None or inc.state != "get":
                raise LookupError("no such transfer")
        hit = chunk_at(inc.items, inc.starts, inc.cs, c)
        if hit is None:
            raise LookupError("no such chunk")
        i, off, n = hit
        if inc.paths[i] is None:
            return inc.progress()
        if len(data) != n:
            raise ValueError("chunk %d is %d bytes, not %d" % (c, len(data), n))
        with inc.lock:
            if inc.has(c):
                return inc.progress()
        with open(inc.paths[i], "r+b") as f:
            f.seek(off)
            f.write(data)
        with inc.lock:
            if not inc.has(c) and inc.state == "get":
                inc.got[c >> 3] |= 1 << (c & 7)
                inc.ngot += 1
                inc.bytes += n
                inc.left[i] = inc.left.get(i, 1) - 1
            return inc.progress()

    def done(self, rcid, oid):
        """Every chunk is in: times set, then placed -- the clipboard (files or a picture) or, for a drop, where it fell."""
        with self.lock:
            s = self._sess(rcid)
            inc = s.incoming.get(oid)
            if inc is None:
                return {"ok": False, "error": "no such transfer"}, 404
            if inc.state == "done":
                return {"ok": True, "progress": inc.progress()}, 200
            if inc.ngot < inc.wanted():
                return {"ok": False, "error": "%d chunks still missing" % (inc.wanted() - inc.ngot)}, 409
        for i, it in enumerate(inc.items):
            p = inc.paths[i]
            if p is not None and it.get("t") and not it["d"]:
                try:
                    os.utime(p, (it["t"], it["t"]))
                except OSError:
                    pass
        tops = []
        for i, it in enumerate(inc.items):
            parts = clean_rel(it["p"]) if inc.paths[i] is not None else None
            if parts and len(parts) == 1:
                tops.append(inc.paths[i])
        what = describe([it for i, it in enumerate(inc.items) if inc.paths[i] is not None], inc.kind)
        res = {"what": what, "n": inc.nfiles(), "bytes": inc.total, "skipped": inc.skipped}
        try:
            if inc.kind == "image":
                with open(inc.paths[0], "rb") as f:
                    png = f.read()
                ok = self.clip().put_image(png, oid)
                res.update(placed="clipboard" if ok else "failed", note="on your clipboard — paste it" if ok else "could not reach the clipboard")
            elif inc.kind == "drop":
                res.update(self._drop(inc, tops))
            else:
                ok = self.clip().put_files(tops, oid)
                res.update(placed="clipboard" if ok else "failed", note="on your clipboard — paste them (Ctrl+V)" if ok else "could not reach the clipboard")
        except Exception as e:
            res.update(placed="failed", note=str(e)[:200])
        with self.lock:
            inc.state = "done"
            inc.result = res
        self.log("rc files: received %s (%s) -> %s%s" % (what, fmt_size(inc.total), res.get("placed"), (" " + res["where"]) if res.get("where") else ""))
        return {"ok": True, "progress": inc.progress()}, 200

    def _drop(self, inc, tops):
        """Where the controller let go on the shared screen: a folder (Explorer / the desktop) or an XDND target there; else
        Downloads/KASTR."""
        if self.place_drop is not None:
            return self.place_drop(inc, tops, inc.pt)
        px = py = None
        rc = self.rc_get() if self.rc_get else None
        g = getattr(rc, "grant", None) if rc is not None else None
        if g and inc.pt is not None:
            try:
                import kastr_rc
                with rc.lock:
                    rect = rc._backend().surface_rect(g["url"])
                p = kastr_rc.norm_point(inc.pt[0], inc.pt[1], rect, False)
                if p:
                    px, py = p
            except Exception:
                px = py = None
        if px is not None:
            try:
                if WINDOWS:
                    folder, what = win_folder_at(px, py)
                    if folder:
                        names = deliver(tops, folder)
                        return {"placed": what, "where": folder, "names": names,
                                "note": "dropped into %s" % ("the desktop" if what == "desktop" else os.path.basename(folder.rstrip("\\")) or folder)}
                elif LINUX:
                    import kastr_rcfiles_x11
                    r, info = kastr_rcfiles_x11.xdnd_drop(tops, px, py)
                    if r == "done":
                        self.kept.append((inc.folder, self.clock() + 600))   # the target copies from here, maybe later
                        return {"placed": "xdnd", "where": info, "note": "dropped into %s" % (info or "the window there")}
                    if r == "desktop":
                        folder = desktop_dir()
                        if os.path.isdir(folder):
                            names = deliver(tops, folder)
                            return {"placed": "desktop", "where": folder, "names": names, "note": "dropped onto the desktop"}
            except Exception as e:
                self.log("rc files: drop: %s" % e)
        dest = os.path.join(downloads_dir(), "KASTR")
        names = deliver(tops, dest)
        return {"placed": "downloads", "where": dest, "names": names,
                "note": "saved to %s (that spot doesn't take files)" % os.path.join(os.path.basename(downloads_dir()), "KASTR")}

    def cancel(self, rcid, oid):
        with self.lock:
            s = self._sess(rcid)
            inc = s.incoming.get(oid)
            if inc is None or inc.state != "get":
                return {"ok": True}, 200
            inc.state = "cancel"
            s.recv_bytes -= inc.total - inc.bytes   # the reservation goes back (what arrived counts)
        shutil.rmtree(inc.folder, ignore_errors=True)
        self.log("rc files: transfer of %s cancelled" % describe(inc.items, inc.kind))
        return {"ok": True}, 200

    # ---- what the page reads
    def status(self):
        s = self.s
        if s is None:
            return {"session": None, "last": self.last}
        cur = s.offers.get(s.current) if s.current else None
        return {"session": {"rcid": s.rcid, "role": s.role, "sent": s.sent_bytes, "recv": s.recv_bytes, "used": s.used(),
                            "max": s.cfg["rc_session_max_mb"] << 20},
                "offer": cur["pub"] if cur else None, "note": s.note,
                "rx": {oid: inc.progress() for oid, inc in list(s.incoming.items())[-6:]}}


def _read_at(path, off, n):
    """n bytes at off of a regular file -- opened without following a link (O_NOFOLLOW where there is one; on Windows the
    path was lstat-checked when it was offered and is checked again here)."""
    import stat as _st
    st = os.lstat(path)
    if _is_link(st, path) or not _st.S_ISREG(st.st_mode):
        raise IOError("not a regular file any more")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        os.lseek(fd, off, 0)
        out = []
        left = n
        while left > 0:
            b = os.read(fd, left)
            if not b:
                break
            out.append(b)
            left -= len(b)
        return b"".join(out)
    finally:
        os.close(fd)


_F = None
_F_LOCK = threading.Lock()


def get(log=None, ini=None):
    global _F
    with _F_LOCK:
        if _F is None:
            def rc_get():
                try:
                    import kastr_rc
                    return kastr_rc._RC
                except Exception:
                    return None
            _F = Files(log=log, ini=ini, rc_get=rc_get)
            import atexit
            atexit.register(shutdown)   # KASTR closing: no temp files, no clipboard pointing at them
        else:
            if log is not None:
                _F.log = log
            if ini is not None:
                _F.ini = ini
        return _F


def shutdown():
    f = _F
    if f is not None:
        try:
            f.shutdown()
        except Exception:
            pass


# ---- the loopback API --------------------------------------------------------------------------------------------------------
def _dispatch(f, p):
    op, rcid = str(p.get("op") or ""), str(p.get("rcid") or "")
    try:
        if op == "begin":
            return f.begin(rcid, str(p.get("role") or ""), p.get("name"))
        if op == "renew":
            return f.renew(rcid, bool(p.get("now")))
        if op == "end":
            f.end(rcid or None, str(p.get("why") or "stopped")[:24])
            return {"ok": True}, 200
        if op == "recv":
            return f.recv(rcid, p.get("offer"), p.get("pt"))
        if op == "done":
            return f.done(rcid, str(p.get("oid") or ""))
        if op == "cancel":
            return f.cancel(rcid, str(p.get("oid") or ""))
        if op == "sent":
            return f.sent(rcid, str(p.get("oid") or ""), str(p.get("state") or ""), str(p.get("who") or "")[:40])
    except PermissionError as e:
        return {"ok": False, "error": str(e)}, 409
    return {"ok": False, "error": "op is begin | renew | end | recv | done | cancel | sent"}, 400


def handle_api(handler, log=None, ini=None):
    """GET /api/rcfiles -> caps + status; GET /api/rcfiles/chunk?rcid=&oid=&c= -> bytes; POST /api/rcfiles {op...};
    POST /api/rcfiles/put?rcid=&oid=&c= (body: the chunk). This computer's own KASTR pages only (kastr_rc's guard) and,
    for everything but the plain GET, the X-KASTR-RC header (a foreign page cannot send it without a preflight)."""
    import kastr_rc
    f = get(log, ini)
    u = urlparse(handler.path)
    path = u.path

    def send(code, obj=None, body=None, ctype="application/json"):
        data = body if body is not None else json.dumps(obj).encode()
        handler.send_response(code)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(data)

    if not kastr_rc._guard(handler):
        return send(403, {"ok": False, "error": "only on the computer itself"})
    if handler.command == "GET" and path == "/api/rcfiles":
        return send(200, dict(f.status(), ok=True, caps=f.caps()))
    if handler.headers.get("X-KASTR-RC") != "1":
        return send(403, {"ok": False, "error": "missing X-KASTR-RC"})
    q = parse_qs(u.query)
    one = lambda k: (q.get(k) or [""])[0]
    if path in ("/api/rcfiles/chunk", "/api/rcfiles/put"):
        rcid, oid = one("rcid"), one("oid")
        try:
            c = int(one("c"))
        except ValueError:
            c = -1
        if not OID_RE.match(oid) or c < 0:
            return send(400, {"ok": False, "error": "bad chunk"})
        try:
            if path == "/api/rcfiles/chunk" and handler.command == "GET":
                return send(200, body=f.chunk(rcid, oid, c), ctype="application/octet-stream")
            if path == "/api/rcfiles/put" and handler.command == "POST":
                n = int(handler.headers.get("Content-Length") or 0)
                if n < 0 or n > CHUNK_MAX:
                    return send(413, {"ok": False, "error": "chunk too large"})
                data = handler.rfile.read(n) if n else b""
                return send(200, {"ok": True, "progress": f.put(rcid, oid, c, data)})
        except PermissionError as e:
            return send(409, {"ok": False, "error": str(e)})
        except LookupError as e:
            return send(404, {"ok": False, "error": str(e)})
        except (ValueError, IOError, OSError) as e:
            return send(422, {"ok": False, "error": str(e)[:200]})
        return send(405, {"ok": False, "error": "method"})
    if handler.command != "POST" or path != "/api/rcfiles":
        return send(404, {"ok": False, "error": "no such call"})
    try:
        n = int(handler.headers.get("Content-Length") or 0)
        p = json.loads(handler.rfile.read(min(n, 16 << 20)) or b"{}") if n else {}
    except Exception:
        return send(400, {"ok": False, "error": "body must be JSON"})
    out, code = _dispatch(f, p if isinstance(p, dict) else {})
    return send(code, out)
