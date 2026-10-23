# -*- coding: utf-8 -*-
"""v0.21.83 FILES AND PICTURES OVER REMOTE CONTROL. Kenton (2026-10-23): "Am I able to copy a file on my machine or the remote
machine and paste it on the other side?" -- decided yes: files and folders copied on either computer during a grant are
fetched by the other KASTR (the files travel, never paths) and put on ITS clipboard so a paste in Explorer / a file manager
copies them there; pictures likewise (size-capped); a file dragged from the controller's desktop onto the shared screen is
sent and dropped where it was let go (an Explorer folder / the desktop / an XDND target, else Downloads/KASTR).

What is proven here (no network, NEVER the real clipboard or desktop: every clipboard is kastr_rcfiles.MockClip or a faked
xclip; Windows formats are checked as bytes -- DROPFILES, DIB <-> PNG):
  * names: Windows' reserved names, bad characters, "..", absolute / drive / UNC paths refused, free names in a folder;
    device paths never read; links never followed (a scan skips them);
  * CF_HDROP contents both ways, text/uri-list + x-special/gnome-copied-files both ways, DIB (24 / 32-bit, BI_RGB /
    BITFIELDS / V5, 8-bit palette, bottom-up / top-down) -> PNG, PNG (all five row filters) -> RGBA -> DIB;
  * the session (kastr_rcfiles.Files): only during a grant (the sharer's KASTR checks kastr_rc's), never the clipboard as it
    was before, offers of files / a folder / a picture, our own placement never offered back, chunk serving, receiving into a
    temp folder, placing on the clipboard, drop placement, per-transfer / per-session / picture caps, cancel, the lease, temp
    cleanup at the end (and the keep-for-a-late-paste window), stale folders of a dead KASTR swept;
  * the loopback API's guards, the relay's "allow" note carrying the transfer key (and nothing else of that shape), the page
    and build wiring.
Real end-to-end (two KASTRs, a relay, X11 clipboards on virtual X servers, a 200 MB file, a folder, pictures, a drop, cancel,
limits) runs in the WSL lab (scratchpad v02183/B)."""
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import unittest
import zlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_rcfiles as rf  # noqa: E402
import kastr_rcfiles_x11 as rfx  # noqa: E402
import kastr_relay as kr  # noqa: E402
import kastr_rc as rc  # noqa: E402

A, B = "alice-aa11", "bob-bb22"
SHARE = "alpha/%s/alice/screen.hang" % A


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return f.read()


# ---- names ------------------------------------------------------------------------------------------------------------------
class Names(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(rf.clean_name("report.docx"), "report.docx")
        self.assertEqual(rf.clean_name('a<b>c:d"e|f?g*h'), "a_b_c_d_e_f_g_h")
        self.assertEqual(rf.clean_name("tab\there\x7f"), "tab_here_")
        self.assertEqual(rf.clean_name("trailing. . "), "trailing")
        for bad in ("", ".", "..", "  ", ". ."):
            self.assertIsNone(rf.clean_name(bad), bad)
        for dev in ("CON", "con.txt", "NUL", "Com1.log", "LPT9", "aux .x", "COM\u00b9"):
            self.assertTrue(rf.clean_name(dev).startswith("_"), dev)
        self.assertEqual(rf.clean_name("CONSOLE.txt"), "CONSOLE.txt")   # only the exact device names
        long = "x" * 300 + ".pdf"
        c = rf.clean_name(long)
        self.assertTrue(len(c) <= 200 and c.endswith(".pdf"))

    def test_clean_rel_refuses_every_way_out(self):
        self.assertEqual(rf.clean_rel("Photos/2026/a.jpg"), ["Photos", "2026", "a.jpg"])
        self.assertEqual(rf.clean_rel("Photos\\2026\\a.jpg"), ["Photos", "2026", "a.jpg"])
        self.assertEqual(rf.clean_rel("a//b"), ["a", "b"])
        for bad in ("../x", "a/../../x", "a/./b", "/etc/passwd", "\\\\server\\share\\x", "C:\\Windows\\x", "c:x", "a\0b", "",
                    "/".join(["d"] * 40), "a/ .. /b"):
            self.assertIsNone(rf.clean_rel(bad), bad)
        self.assertEqual(rf.clean_rel("CON/aux.txt"), ["_CON", "_aux.txt"])

    def test_unique_name(self):
        d = tempfile.mkdtemp()
        try:
            self.assertEqual(rf.unique_name(d, "a.txt"), "a.txt")
            open(os.path.join(d, "a.txt"), "w").close()
            self.assertEqual(rf.unique_name(d, "a.txt"), "a (2).txt")
            open(os.path.join(d, "a (2).txt"), "w").close()
            self.assertEqual(rf.unique_name(d, "a.txt"), "a (3).txt")
            os.mkdir(os.path.join(d, "Folder"))
            self.assertEqual(rf.unique_name(d, "Folder"), "Folder (2)")
        finally:
            shutil.rmtree(d)

    def test_device_paths(self):
        for p in ("\\\\.\\PhysicalDrive0", "\\\\?\\GLOBALROOT\\Device\\HarddiskVolume1\\x", "\\??\\C:\\x", "\\Device\\Null"):
            self.assertTrue(rf.device_path(p), p)
        for p in ("C:\\Users\\k\\a.txt", "\\\\?\\UNC\\server\\share\\a", "\\\\server\\share\\a.txt", "/home/k/a.txt"):
            self.assertFalse(rf.device_path(p), p)
        if rf.LINUX:
            self.assertTrue(rf.device_path("/dev/sda"))
        if rf.WINDOWS:
            self.assertTrue(rf.device_path("C:\\temp\\NUL"))

    def test_fmt_size(self):
        self.assertEqual(rf.fmt_size(0), "0 bytes")
        self.assertEqual(rf.fmt_size(12 * 1048576), "12 MB")
        self.assertEqual(rf.fmt_size(1536), "1.5 KB")
        self.assertEqual(rf.fmt_size(2 << 30), "2.0 GB")


# ---- clipboard formats -----------------------------------------------------------------------------------------------------
class Formats(unittest.TestCase):
    def test_dropfiles_layout_and_round_trip(self):
        paths = ["C:\\Temp\\KASTR-rc\\1-abc\\report.docx", "C:\\Temp\\KASTR-rc\\1-abc\\Fotos \u00e9t\u00e9"]
        b = rf.build_dropfiles(paths)
        pfiles, x, y, nc, wide = struct.unpack_from("<IiiII", b, 0)
        self.assertEqual((pfiles, x, y, nc, wide), (20, 0, 0, 0, 1))
        self.assertTrue(b.endswith(b"\x00\x00\x00\x00"))           # the last path's NUL + the list's NUL (UTF-16)
        self.assertEqual(len(b), 20 + 2 * (sum(len(p) + 1 for p in paths) + 1))
        self.assertEqual(rf.parse_dropfiles(b), paths)
        ansi = struct.pack("<IiiII", 20, 0, 0, 0, 0) + b"C:\\a.txt\0C:\\b\0\0"
        self.assertEqual(rf.parse_dropfiles(ansi), ["C:\\a.txt", "C:\\b"])
        for junk in (b"", b"\x01" * 10, struct.pack("<IiiII", 999, 0, 0, 0, 1)):
            self.assertEqual(rf.parse_dropfiles(junk), [])

    def test_uri_lists(self):
        paths = ["/tmp/KASTR-rc/1-abc/a b.txt", "/tmp/KASTR-rc/1-abc/D\u00e9j\u00e0"]
        if rf.WINDOWS:
            paths = ["C:\\t\\a b.txt", "C:\\t\\D\u00e9j\u00e0"]
        ul = rf.uri_list(paths).decode()
        self.assertTrue(ul.endswith("\r\n") and ul.count("\r\n") == 2 and "a%20b.txt" in ul and "file://" in ul)
        self.assertEqual(rf.parse_uris(ul), paths)
        gc = rf.gnome_copied(paths).decode()
        self.assertTrue(gc.startswith("copy\nfile://"))
        self.assertEqual(rf.parse_uris(gc), paths)
        self.assertEqual(rf.parse_uris("# comment\r\nhttp://x/y\r\nfile://otherhost/z\r\nfile:///ok\r\n"), ["/ok"])
        self.assertEqual(rf.parse_uris("cut\nfile:///a"), ["/a"])


def _ref_png(w, h, rows_rgba, filters, ct=6):
    """A reference encoder with each row's filter chosen (0..4) -- what other programs write."""
    bpp = {6: 4, 2: 3, 0: 1, 4: 2}[ct]
    out, prev = b"", bytes(w * bpp)
    for y, row in enumerate(rows_rgba):
        ft = filters[y % len(filters)]
        f = bytearray()
        for x in range(len(row)):
            a = row[x - bpp] if x >= bpp else 0
            b_, c = prev[x], (prev[x - bpp] if x >= bpp else 0)
            if ft == 0:
                v = row[x]
            elif ft == 1:
                v = row[x] - a
            elif ft == 2:
                v = row[x] - b_
            elif ft == 3:
                v = row[x] - ((a + b_) >> 1)
            else:
                p = a + b_ - c
                pa, pb, pc = abs(p - a), abs(p - b_), abs(p - c)
                v = row[x] - (a if pa <= pb and pa <= pc else (b_ if pb <= pc else c))
            f.append(v & 255)
        out += bytes([ft]) + bytes(f)
        prev = row
    ch = lambda k, d: struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ct, 0, 0, 0)) + ch(b"IDAT", zlib.compress(out)) + ch(b"IEND", b"")


def _pixels(w, h):
    return [b"".join(bytes(((x * 37 + y * 11) & 255, (x * 5 + y * 90) & 255, (x * y) & 255, (200 + x + y) & 255)) for x in range(w))
            for y in range(h)]


class Images(unittest.TestCase):
    def test_png_round_trip(self):
        rows = _pixels(7, 5)
        png = rf.png_encode(7, 5, b"".join(rows), 4)
        self.assertEqual(rf.png_size(png), (7, 5))
        self.assertEqual(rf.png_decode(png), (7, 5, b"".join(rows)))

    def test_every_png_filter(self):
        rows = _pixels(9, 10)
        for filters in ([0], [1], [2], [3], [4], [0, 1, 2, 3, 4]):
            w, h, px = rf.png_decode(_ref_png(9, 10, rows, filters))
            self.assertEqual(px, b"".join(rows), filters)
        rgb = [bytes(b for i, b in enumerate(r) if i % 4 != 3) for r in rows]
        w, h, px = rf.png_decode(_ref_png(9, 10, rgb, [4, 1], ct=2))
        self.assertEqual(px[3::4], b"\xff" * 90)
        self.assertEqual(px[0::4], b"".join(r[0::4] for r in rows))
        # too slow without PIL: refused, not hung
        self.assertIsNone(rf.png_decode(_ref_png(9, 10, rows, [4]), slow_budget=10))
        self.assertIsNotNone(rf.png_decode(_ref_png(9, 10, rows, [2]), slow_budget=10))   # Up / Sub / None stay quick

    def test_palette_and_gray_png(self):
        def ch(k, d):
            return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)
        raw = b"\x00\x00\x01\x02" + b"\x00\x02\x01\x00"
        png = b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 3, 2, 8, 3, 0, 0, 0)) + ch(b"PLTE", b"\xff\x00\x00\x00\xff\x00\x00\x00\xff") \
            + ch(b"tRNS", b"\x80") + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")
        w, h, px = rf.png_decode(png)
        self.assertEqual(px[:12], bytes([255, 0, 0, 128, 0, 255, 0, 255, 0, 0, 255, 255]))
        gray = b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 0, 0, 0, 0)) + ch(b"IDAT", zlib.compress(b"\x00\x10\xf0")) + ch(b"IEND", b"")
        self.assertEqual(rf.png_decode(gray)[2], bytes([16, 16, 16, 255, 240, 240, 240, 255]))
        inter = b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 0, 0, 0, 1)) + ch(b"IEND", b"")
        self.assertIsNone(rf.png_decode(inter))
        self.assertIsNone(rf.png_decode(b"GIF89a"))

    def _dib(self, w, h, bpp, comp=0, hs=40, top_down=False, masks=None, pal=None, alpha=None):
        stride = ((w * bpp + 31) // 32) * 4
        head = struct.pack("<IiiHHIIiiII", hs, w, -h if top_down else h, 1, bpp, comp, stride * h, 0, 0, len(pal) // 4 if pal else 0, 0)
        if hs > 40:
            head += struct.pack("<IIII", *(masks or (0, 0, 0, 0))) + b"\x00" * (hs - 56)
        elif masks and comp == 3:
            head += struct.pack("<III", *masks[:3])
        if pal:
            head += pal
        rows = []
        for y in range(h):   # y = the row as shown (top first)
            r = bytearray()
            for x in range(w):
                if bpp == 8:
                    r.append((x + y) % 2)
                else:
                    r += bytes([x * 10 & 255, y * 20 & 255, 100]) + (bytes([alpha if alpha is not None else 0]) if bpp == 32 else b"")
            rows.append(bytes(r) + b"\x00" * (stride - len(r)))
        if not top_down:
            rows.reverse()
        return head + b"".join(rows)

    def _rgba(self, png):
        return rf.png_decode(png)

    def test_dib_24_bottom_up(self):
        w, h, px = self._rgba(rf.dib_to_png(self._dib(3, 2, 24)))
        self.assertEqual((w, h), (3, 2))
        self.assertEqual(px[:4], bytes([100, 0, 0, 255]))            # BGR(0, 0, 100) at the top left
        self.assertEqual(px[4 * 4:4 * 4 + 4], bytes([100, 20, 10, 255]))   # row 1, x 1

    def test_dib_32_zero_alpha_is_opaque_and_alpha_kept(self):
        _w, _h, px = self._rgba(rf.dib_to_png(self._dib(2, 2, 32, alpha=0)))
        self.assertEqual(px[3::4], b"\xff" * 4)
        _w, _h, px = self._rgba(rf.dib_to_png(self._dib(2, 2, 32, alpha=77, top_down=True)))
        self.assertEqual(px[3::4], bytes([77]) * 4)
        self.assertEqual(px[:3], bytes([100, 0, 0]))

    def test_dib_v5_bitfields(self):
        d = self._dib(2, 1, 32, comp=3, hs=124, masks=(0xFF0000, 0xFF00, 0xFF, 0xFF000000), alpha=9)
        self.assertEqual(self._rgba(rf.dib_to_png(d))[2][3], 9)
        d = self._dib(2, 1, 32, comp=3, hs=40, masks=(0xFF0000, 0xFF00, 0xFF))
        self.assertEqual(self._rgba(rf.dib_to_png(d))[2][3], 255)
        self.assertIsNone(rf.dib_to_png(self._dib(2, 1, 32, comp=3, hs=124, masks=(0xF800, 0x7E0, 0x1F, 0))))   # 565-style: not handled

    def test_dib_palette_and_unsupported(self):
        pal = b"\x00\x00\xff\x00" + b"\xff\x00\x00\x00"   # 0 = red, 1 = blue (BGRx)
        _w, _h, px = self._rgba(rf.dib_to_png(self._dib(2, 1, 8, pal=pal)))
        self.assertEqual(px, bytes([255, 0, 0, 255, 0, 0, 255, 255]))
        self.assertIsNone(rf.dib_to_png(self._dib(2, 1, 16)))
        self.assertIsNone(rf.dib_to_png(b"\x28\x00"))
        png = rf.png_encode(1, 1, b"\x01\x02\x03\x04")
        self.assertEqual(rf.dib_to_png(struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 0, 5, len(png), 0, 0, 0, 0) + png), png)   # BI_PNG

    def test_png_to_dib(self):
        rows = _pixels(5, 3)
        opaque = bytearray(b"".join(rows))
        opaque[3::4] = b"\xff" * 15
        dib = rf.png_to_dib(rf.png_encode(5, 3, bytes(opaque)))
        hs, w, h, _p, bpp, comp = struct.unpack_from("<IiiHHI", dib, 0)
        self.assertEqual((hs, w, h, bpp, comp), (40, 5, 3, 24, 0))
        self.assertEqual(self._rgba(rf.dib_to_png(dib))[2], bytes(opaque))   # and back
        dib = rf.png_to_dib(rf.png_encode(5, 3, b"".join(rows)))
        self.assertEqual(struct.unpack_from("<H", dib, 14)[0], 32)
        self.assertEqual(self._rgba(rf.dib_to_png(dib))[2], b"".join(rows))
        bmp = b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, 54) + dib
        self.assertEqual(rf.bmp_to_dib(bmp), dib)


# ---- the scan: links never followed --------------------------------------------------------------------------------------
class Scan(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "Folder", "sub"))
        for rel, n in (("Folder/a.txt", 5), ("Folder/sub/b.bin", 3000), ("Folder/empty.txt", 0), ("solo.docx", 12)):
            with open(os.path.join(self.d, *rel.split("/")), "wb") as f:
                f.write(os.urandom(n))
        self.out = tempfile.mkdtemp()
        with open(os.path.join(self.out, "secret.txt"), "w") as f:
            f.write("outside the copied set")
        self.links = True
        try:
            os.symlink(self.out, os.path.join(self.d, "Folder", "link-out"), target_is_directory=True)
            os.symlink(os.path.join(self.out, "secret.txt"), os.path.join(self.d, "Folder", "sub", "secret-link.txt"))
        except (OSError, NotImplementedError):
            self.links = False

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)
        shutil.rmtree(self.out, ignore_errors=True)

    def test_scan_walks_folders_in_order(self):
        items, srcs, skipped = rf.scan([os.path.join(self.d, "Folder"), os.path.join(self.d, "solo.docx"), "\\\\.\\PhysicalDrive0"])
        names = [it["p"] for it in items]
        self.assertEqual(names, ["Folder", "Folder/a.txt", "Folder/empty.txt", "Folder/sub", "Folder/sub/b.bin", "solo.docx"])
        self.assertEqual([it["d"] for it in items], [1, 0, 0, 1, 0, 0])
        self.assertEqual(items[4]["n"], 3000)
        self.assertIsNone(srcs[0])
        self.assertTrue(srcs[4].endswith("b.bin"))
        self.assertEqual(skipped.get("device"), 1)
        if self.links:
            self.assertEqual(skipped.get("links"), 2)
            self.assertFalse(any("secret" in n for n in names))
        self.assertEqual(rf.offer_summary(items), (4, 2, 3017))
        self.assertEqual(rf.describe(items), "4 files in 2 folders")
        self.assertEqual(rf.describe(items[:5]), "the folder Folder")

    def test_a_copied_link_itself_is_skipped(self):
        if not self.links:
            self.skipTest("symlinks need a privilege here")
        items, _s, skipped = rf.scan([os.path.join(self.d, "Folder", "link-out")])
        self.assertEqual((items, skipped), ([], {"links": 1}))

    def test_item_limit(self):
        items, _s, skipped = rf.scan([os.path.join(self.d, "Folder")], limit_items=2)
        self.assertEqual(len(items), 2)
        self.assertTrue(skipped.get("too many"))

    def test_chunk_plan(self):
        items = [{"p": "F", "n": 0, "d": 1}, {"p": "F/a", "n": 5}, {"p": "F/e", "n": 0}, {"p": "F/b", "n": 2500}, {"p": "c", "n": 1000}]
        starts, n = rf.chunk_plan(items, 1000)
        self.assertEqual((starts, n), ([0, 0, 1, 1, 4], 5))
        self.assertEqual(rf.chunk_at(items, starts, 1000, 0), (1, 0, 5))
        self.assertEqual(rf.chunk_at(items, starts, 1000, 1), (3, 0, 1000))
        self.assertEqual(rf.chunk_at(items, starts, 1000, 3), (3, 2000, 500))
        self.assertEqual(rf.chunk_at(items, starts, 1000, 4), (4, 0, 1000))
        self.assertIsNone(rf.chunk_at(items, starts, 1000, 5))


class Plan(unittest.TestCase):
    def test_sanitized_layout(self):
        d = tempfile.mkdtemp()
        try:
            offer = {"oid": "0123456789abcdef", "kind": "files", "cs": 1000, "items": [
                {"p": "Fold:er", "d": 1}, {"p": "Fold:er/CON.txt", "n": 10}, {"p": "../escape.txt", "n": 3}, {"p": "Fold_er", "d": 1},
                {"p": "a.txt", "n": 4}, {"p": "a.txt/b", "n": 1}, {"p": "A.TXT", "n": 2}, {"p": "deep/x/y.bin", "n": 2500}]}
            inc = rf.plan_incoming(offer, d, 1000)
            rel = [os.path.relpath(p, d).replace("\\", "/") if p else None for p in inc.paths]
            self.assertEqual(rel, ["Fold_er", "Fold_er/_CON.txt", None, None, "a.txt", None, None, "deep/x/y.bin"])
            self.assertEqual(inc.skipped, {"names": 4})
            self.assertEqual((inc.total, inc.wanted(), inc.nfiles()), (2514, 1 + 1 + 3, 3))
            self.assertEqual(inc.need_ranges(), [[0, 1], [2, 3], [5, 8]])   # never the skipped files' chunks
            for bad in ({"oid": "x"}, {"oid": "0123456789abcdef", "items": []}, {"oid": "0123456789abcdef", "items": [{"p": "a", "n": -1}]},
                        {"oid": "0123456789abcdef", "items": [{"p": "../a", "n": 1}]}):
                with self.assertRaises(ValueError):
                    rf.plan_incoming(bad, d, 1000)
        finally:
            shutil.rmtree(d)


# ---- the session --------------------------------------------------------------------------------------------------------------
class FakeRC:
    def __init__(self, rcid):
        self.grant = {"rcid": rcid, "url": "screen://monitor/0"}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


RCID = "abcdef1234"


class Session(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = tempfile.mkdtemp()
        self.ini = {"rc_files_keep_min": "0"}
        self.clip = rf.MockClip()
        self.clock = Clock()
        self.rc = FakeRC(RCID)
        self.logs = []
        self.drops = []
        self.f = rf.Files(clip=self.clip, log=self.logs.append, ini=lambda k: self.ini.get(k), clock=self.clock,
                          rc_get=lambda: self.rc, root=os.path.join(self.tmp, "KASTR-rc"), place=self._place)

    def tearDown(self):
        self.f.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.src, ignore_errors=True)

    def _place(self, inc, tops, pt):
        dest = os.path.join(self.tmp, "dropped")
        self.drops.append((pt, [os.path.basename(t) for t in tops]))
        return {"placed": "folder", "where": dest, "names": rf.deliver(tops, dest), "note": "dropped into dropped"}

    def make(self, rel, data):
        p = os.path.join(self.src, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def offer_now(self):
        out, code = self.f.renew(RCID, now=True)
        self.assertEqual(code, 200, out)
        return out["offer"]

    def pull(self, offer, rcid=RCID, pt=None):
        """The other side's whole round: recv, every chunk through chunk() -> put(), done."""
        out, code = self.f.recv(rcid, offer, pt)
        if code != 200:
            return out, code
        for a, b in out["need"]:
            for c in range(a, b):
                self.f.put(rcid, offer["oid"], c, self.f.chunk(rcid, offer["oid"], c))
        return self.f.done(rcid, offer["oid"])

    def test_sharer_needs_the_grant_and_the_session_follows_it(self):
        self.assertEqual(self.f.begin("zzzzzzzz99", "sharer")[1], 403)
        out, code = self.f.begin(RCID, "sharer", "Bob")
        self.assertEqual((code, out["caps"]["files"], out["caps"]["max"]), (200, True, 2048 << 20))
        self.rc.grant = None
        self.f.tick()
        self.assertIsNone(self.f.s)
        self.assertEqual(self.f.last["why"], "control ended")
        self.assertEqual(self.f.renew(RCID)[1], 409)

    def test_switched_off(self):
        self.ini["rc_files"] = "off"
        out, code = self.f.begin(RCID, "ctl")
        self.assertEqual(code, 409)
        self.assertIn("switched off", out["error"])

    def test_the_clipboard_before_the_session_never_travels(self):
        self.clip.set(files=[self.make("before.txt", b"old")])
        self.f.begin(RCID, "ctl")
        self.assertIsNone(self.offer_now())
        self.clip.set(text=True)
        self.assertIsNone(self.offer_now())                     # text is kastr_rc's (and wins over a picture)
        p = self.make("Docs/report.docx", b"R" * 2500)
        self.make("Docs/sub/x.bin", b"\x00" * 10)
        self.clip.set(files=[os.path.dirname(p)])
        off = self.offer_now()
        self.assertEqual((off["kind"], off["files"], off["dirs"], off["total"], off["name"]), ("files", 2, 2, 2510, "the folder Docs"))
        self.assertNotIn("srcs", off)                           # never a path of this computer
        self.assertFalse(any(it["p"].startswith("/") or "\\" in it["p"] or ":" in it["p"] or self.src in it["p"] for it in off["items"]))
        self.assertEqual([it["p"] for it in off["items"]], ["Docs", "Docs/report.docx", "Docs/sub", "Docs/sub/x.bin"])   # relative, "/"
        self.assertEqual(self.offer_now()["oid"], off["oid"])   # the same copy: the same offer

    def test_files_round_trip_onto_the_clipboard(self):
        self.f.begin(RCID, "ctl")
        big = os.urandom(rf.CHUNK * 2 + 123)
        self.make("A/big.bin", big)
        folder_a = os.path.dirname(self.make("A/empty", b""))
        self.clip.set(files=[folder_a, self.make("note.txt", b"hello")])
        off = self.offer_now()
        out, code = self.pull(off)
        self.assertEqual(code, 200, out)
        prog = out["progress"]
        self.assertEqual((prog["state"], prog["files"], prog["nfiles"], prog["bytes"]), ("done", 3, 3, len(big) + 5))
        self.assertEqual(prog["result"]["placed"], "clipboard")
        kind, tops = self.clip.puts[-1]
        self.assertEqual(kind, "files")
        self.assertEqual(sorted(os.path.basename(t) for t in tops), ["A", "note.txt"])
        with open(os.path.join([t for t in tops if t.endswith("A")][0], "big.bin"), "rb") as f:
            self.assertEqual(f.read(), big)
        self.assertTrue(all(t.startswith(os.path.join(self.tmp, "KASTR-rc")) for t in tops))
        self.assertIsNone(self.offer_now())                     # what I placed is never offered back
        self.assertEqual(self.f.status()["session"]["sent"], len(big) + 5)
        # the session ends: nothing stays (keep_min 0), the clipboard no longer points at deleted files
        self.f.end(RCID, "released")
        self.assertFalse(os.path.exists(tops[0]))
        self.assertEqual(self.clip.content, {})

    def test_a_late_paste_window_then_cleanup(self):
        self.ini["rc_files_keep_min"] = "10"
        self.f.begin(RCID, "ctl")
        self.clip.set(files=[self.make("k.txt", b"keep me")])
        self.pull(self.offer_now())
        tops = self.clip.puts[-1][1]
        self.f.end(RCID, "released")
        self.assertTrue(os.path.exists(tops[0]))                # still pasteable right after Release
        self.clock.t += 601
        self.f.tick()
        self.assertFalse(os.path.exists(tops[0]))
        self.assertEqual(self.clip.content, {})

    def test_picture_round_trip(self):
        self.f.begin(RCID, "ctl")
        png = rf.png_encode(2, 2, b"\x10\x20\x30\xff" * 4)
        self.clip.set(image=png)
        off = self.offer_now()
        self.assertEqual((off["kind"], off["w"], off["h"], off["total"], off["name"]), ("image", 2, 2, len(png), "a picture"))
        out, code = self.pull(off)
        self.assertEqual((code, out["progress"]["result"]["placed"]), (200, "clipboard"))
        self.assertEqual(self.clip.puts[-1], ("image", len(png)))
        self.assertEqual(self.clip.content["image"], png)

    def test_limits(self):
        self.ini.update(rc_file_max_mb="1", rc_session_max_mb="3", rc_image_max_mb="1")
        self.f.begin(RCID, "ctl")
        self.clip.set(files=[self.make("two.bin", b"x" * (2 << 20))])
        off = self.offer_now()
        self.assertTrue(off["over"])
        with self.assertRaises(PermissionError):
            self.f.chunk(RCID, off["oid"], 0)                   # the sender refuses it too
        out, code = self.f.recv(RCID, dict(off, oid="1" * 16))
        self.assertEqual((code, out["why"]), (413, "limit"))
        self.assertIn("over the 1.0 MB limit", out["error"])
        out, code = self.f.recv(RCID, {"oid": "2" * 16, "kind": "image", "cs": rf.CHUNK, "items": [{"p": "picture.png", "n": 2 << 20}]})
        self.assertEqual(code, 413)
        self.assertIn("picture", out["error"])
        one = {"oid": "3" * 16, "kind": "files", "cs": rf.CHUNK, "items": [{"p": "a.bin", "n": 1 << 20}]}
        for i in range(3):
            self.assertEqual(self.f.recv(RCID, dict(one, oid=str(i + 3) * 16))[1], 200)
        out, code = self.f.recv(RCID, dict(one, oid="7" * 16))
        self.assertEqual(code, 413)
        self.assertIn("session", out["error"])

    def test_cancel_deletes_the_partial_copy(self):
        self.f.begin(RCID, "ctl")
        self.clip.set(files=[self.make("c.bin", os.urandom(rf.CHUNK * 3))])
        off = self.offer_now()
        out, _ = self.f.recv(RCID, off)
        self.f.put(RCID, off["oid"], 0, self.f.chunk(RCID, off["oid"], 0))
        folder = self.f.s.incoming[off["oid"]].folder
        self.assertTrue(os.path.exists(os.path.join(folder, "c.bin")))
        self.assertEqual(self.f.cancel(RCID, off["oid"])[1], 200)
        self.assertFalse(os.path.exists(folder))
        with self.assertRaises(LookupError):
            self.f.put(RCID, off["oid"], 1, b"x")
        self.assertEqual(self.f.s.recv_bytes, rf.CHUNK)          # the reservation went back (what arrived counts)

    def test_bad_chunks_are_refused(self):
        self.f.begin(RCID, "ctl")
        self.clip.set(files=[self.make("d.bin", b"y" * 100)])
        off = self.offer_now()
        self.f.recv(RCID, off)
        with self.assertRaises(ValueError):
            self.f.put(RCID, off["oid"], 0, b"short")
        with self.assertRaises(LookupError):
            self.f.put(RCID, off["oid"], 9, b"y")
        with self.assertRaises(LookupError):
            self.f.chunk(RCID, "f" * 16, 0)
        self.assertEqual(self.f.done(RCID, off["oid"])[1], 409)   # not everything is in
        with self.assertRaises(PermissionError):
            self.f.chunk("otherrcid1", off["oid"], 0)

    def test_a_file_that_changed_is_not_sent_short(self):
        self.f.begin(RCID, "ctl")
        p = self.make("e.bin", b"z" * 1000)
        self.clip.set(files=[p])
        off = self.offer_now()
        with open(p, "wb") as f:
            f.write(b"z" * 10)
        with self.assertRaises(IOError):
            self.f.chunk(RCID, off["oid"], 0)

    def test_drop_lands_where_it_fell(self):
        self.f.begin(RCID, "sharer", "Bob")
        offer = {"oid": "a" * 16, "kind": "drop", "cs": rf.CHUNK, "items": [{"p": "x.txt", "n": 3}], "pt": [0.25, 0.5]}
        out, code = self.f.recv(RCID, offer, [0.25, 0.5])
        self.assertEqual(code, 200)
        self.f.put(RCID, offer["oid"], 0, b"abc")
        out, code = self.f.done(RCID, offer["oid"])
        self.assertEqual((code, out["progress"]["result"]["placed"]), (200, "folder"))
        self.assertEqual(self.drops, [((0.25, 0.5), ["x.txt"])])
        with open(os.path.join(self.tmp, "dropped", "x.txt"), "rb") as f:
            self.assertEqual(f.read(), b"abc")
        self.assertEqual(self.clip.puts, [])                     # a drop never touches the clipboard

    def test_a_drop_only_on_the_shared_computer(self):
        self.f.begin(RCID, "ctl")
        out, code = self.f.recv(RCID, {"oid": "b" * 16, "kind": "drop", "cs": rf.CHUNK, "items": [{"p": "x", "n": 1}]})
        self.assertEqual(code, 403)

    def test_lease(self):
        self.f.begin(RCID, "ctl")
        self.clock.t += rf.LEASE_S - 1
        self.f.renew(RCID)
        self.clock.t += rf.LEASE_S - 1
        self.f.tick()
        self.assertIsNotNone(self.f.s)
        self.clock.t += 2
        self.f.tick()
        self.assertIsNone(self.f.s)
        self.assertEqual(self.f.last["why"], "timeout")

    def test_unfinished_transfers_go_when_the_session_ends(self):
        self.ini["rc_files_keep_min"] = "10"
        self.f.begin(RCID, "ctl")
        self.clip.set(files=[self.make("u.bin", b"u" * 10)])
        off = self.offer_now()
        self.f.recv(RCID, off)
        folder = self.f.s.folder
        self.f.end(RCID, "left")
        self.assertFalse(os.path.exists(folder))                 # nothing finished: no late-paste window

    def test_stale_folders_of_a_dead_kastr_are_swept(self):
        root = os.path.join(self.tmp, "KASTR-rc")
        os.makedirs(os.path.join(root, "999999-abcdefgh12", "x"))
        os.makedirs(os.path.join(root, "%d-abcdefgh34" % os.getpid()))
        os.makedirs(os.path.join(root, "unrelated"))
        self.f.begin(RCID, "ctl")
        self.assertEqual(sorted(os.listdir(root)), sorted(["%d-abcdefgh34" % os.getpid(), "unrelated"]))

    def test_one_session_at_a_time(self):
        self.f.begin(RCID, "ctl")
        self.f.begin("bbbbbbbb22", "ctl")
        self.assertEqual(self.f.s.rcid, "bbbbbbbb22")
        self.assertEqual(self.f.last["why"], "replaced")

    def test_mock_switch(self):
        old = os.environ.get("KASTR_RC_MOCK")
        os.environ["KASTR_RC_MOCK"] = "1"
        try:
            self.assertIsInstance(rf.make_clip(), rf.MockClip)   # labs on a desktop nobody must touch
        finally:
            if old is None:
                os.environ.pop("KASTR_RC_MOCK", None)
            else:
                os.environ["KASTR_RC_MOCK"] = old


# ---- X11: what xclip says (faked -- no X server here) ---------------------------------------------------------------------
class X11Read(unittest.TestCase):
    def setUp(self):
        self._x = rfx._xclip
        self.ans = {}
        rfx._xclip = lambda args, cap, timeout=3.0: self.ans.get(args[1] if len(args) > 1 else "")

    def tearDown(self):
        rfx._xclip = self._x

    def test_targets(self):
        c = rfx.X11Clip()
        self.ans = {"TARGETS": b"TARGETS\nTIMESTAMP\nx-special/gnome-copied-files\ntext/uri-list\nUTF8_STRING\n",
                    "x-special/gnome-copied-files": b"copy\nfile:///home/a/x%20y.txt\nfile:///home/a/D"}
        self.assertEqual(c.read(1 << 20), {"files": ["/home/a/x y.txt", "/home/a/D"]})
        self.ans = {"TARGETS": b"TARGETS\ntext/uri-list\n", "text/uri-list": b"file:///a\r\n"}
        self.assertEqual(c.read(1 << 20), {"files": ["/a"]})
        self.ans = {"TARGETS": b"TARGETS\nUTF8_STRING\nimage/png\n", "image/png": b"\x89PNG..."}
        self.assertEqual(c.read(1 << 20), {"text": True})
        png = rf.png_encode(1, 1, b"\x00\x00\x00\xff")
        self.ans = {"TARGETS": b"TARGETS\nimage/png\n", "image/png": png}
        self.assertEqual(c.read(1 << 20), {"image": png})
        self.assertEqual(c.read(10), {"image_too_big": True})
        self.ans = {"TARGETS": b"TARGETS\napplication/x-kastr-rc\nimage/png\n"}
        self.assertEqual(c.read(1 << 20), {"ours": True})
        self.ans = {}
        self.assertEqual(c.read(1 << 20), {})


# ---- the loopback API -----------------------------------------------------------------------------------------------------------
class FakeHandler:
    def __init__(self, command, path, body=b"", headers=None):
        self.command, self.path = command, path
        raw = json.dumps(body).encode() if isinstance(body, dict) else body
        self.headers = dict({"Content-Length": str(len(raw))}, **(headers or {}))
        self.rfile, self.wfile = io.BytesIO(raw), io.BytesIO()
        self.code = None

    def send_response(self, c):
        self.code = c

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass


class Api(unittest.TestCase):
    H = {"X-KASTR-RC": "1", "Origin": "http://localhost:8001"}

    def setUp(self):
        self._local = kr.is_local
        kr.is_local = lambda h: getattr(h, "_is_local", True)
        self.tmp = tempfile.mkdtemp()
        self.clip = rf.MockClip()
        rf._F = rf.Files(clip=self.clip, ini=lambda k: None, root=os.path.join(self.tmp, "r"), rc_get=lambda: None)

    def tearDown(self):
        kr.is_local = self._local
        rf._F.shutdown()
        rf._F = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, command, path, body=b"", headers=None, local=True):
        h = FakeHandler(command, path, body, headers)
        h._is_local = local
        rf.handle_api(h)
        v = h.wfile.getvalue()
        try:
            return h.code, json.loads(v)
        except ValueError:
            return h.code, v

    def test_guards(self):
        self.assertEqual(self.call("GET", "/api/rcfiles", local=False)[0], 403)
        self.assertEqual(self.call("GET", "/api/rcfiles", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.call("GET", "/api/rcfiles", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        code, d = self.call("GET", "/api/rcfiles")
        self.assertEqual((code, d["caps"]["files"], d["session"]), (200, True, None))
        code, d = self.call("POST", "/api/rcfiles", {"op": "begin", "rcid": RCID, "role": "ctl"})
        self.assertEqual((code, d["error"]), (403, "missing X-KASTR-RC"))
        self.assertEqual(self.call("GET", "/api/rcfiles/chunk?rcid=%s&oid=%s&c=0" % (RCID, "a" * 16))[0], 403)   # bytes need the header too

    def test_round_trip_over_http(self):
        code, d = self.call("POST", "/api/rcfiles", {"op": "begin", "rcid": RCID, "role": "ctl", "name": "Alice"}, self.H)
        self.assertEqual(code, 200, d)
        src = os.path.join(self.tmp, "hello.txt")
        with open(src, "wb") as f:
            f.write(b"hello over http")
        self.clip.set(files=[src])
        code, d = self.call("POST", "/api/rcfiles", {"op": "renew", "rcid": RCID, "now": True}, self.H)
        off = d["offer"]
        code, d = self.call("POST", "/api/rcfiles", {"op": "recv", "rcid": RCID, "offer": off}, self.H)
        self.assertEqual((code, d["need"]), (200, [[0, 1]]))
        code, data = self.call("GET", "/api/rcfiles/chunk?rcid=%s&oid=%s&c=0" % (RCID, off["oid"]), headers=self.H)
        self.assertEqual((code, data), (200, b"hello over http"))
        code, d = self.call("POST", "/api/rcfiles/put?rcid=%s&oid=%s&c=0" % (RCID, off["oid"]), data, self.H)
        self.assertEqual((code, d["progress"]["got"]), (200, 1))
        code, d = self.call("POST", "/api/rcfiles", {"op": "done", "rcid": RCID, "oid": off["oid"]}, self.H)
        self.assertEqual((code, d["progress"]["result"]["placed"]), (200, "clipboard"))
        code, d = self.call("POST", "/api/rcfiles/put?rcid=%s&oid=%s&c=x" % (RCID, off["oid"]), b"z", self.H)
        self.assertEqual(code, 400)
        code, d = self.call("GET", "/api/rcfiles/chunk?rcid=%s&oid=%s&c=5" % (RCID, off["oid"]), headers=self.H)
        self.assertEqual(code, 404)
        code, d = self.call("POST", "/api/rcfiles", {"op": "nope"}, self.H)
        self.assertEqual(code, 400)
        code, d = self.call("POST", "/api/rcfiles", {"op": "end", "rcid": RCID}, self.H)
        self.assertEqual((code, rf._F.s), (200, None))


# ---- the relay's "allow" carries the key ------------------------------------------------------------------------------------
class Relay(unittest.TestCase):
    def setUp(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)

    def tearDown(self):
        self.svc.close()

    def tok(self, host):
        o, c = self.svc.token({"room": "alpha", "code": "pub-1", "host": host}, "10.0.0.7")
        return o["tokens"]["member"]

    def inbox(self, t):
        o, _c = self.svc.people_api({"op": "beat"}, "Bearer " + t, "10.0.0.7")
        return [x for x in o["inbox"] if x.get("kind") == "rc"]

    def test_allow_carries_the_key(self):
        ta, tb = self.tok(A), self.tok(B)
        fk = "A" * 21 + "-_" + "z" * 20
        self.svc.people_api({"op": "rc", "kind": "ask", "to": A, "share": SHARE, "id": "abcdef12", "peer": "P-b"}, "Bearer " + tb, "10.0.0.7")
        self.assertNotIn("fk", self.inbox(ta)[0])
        o, c = self.svc.people_api({"op": "rc", "kind": "allow", "to": B, "share": SHARE, "id": "abcdef12", "peer": "P-a", "fk": fk}, "Bearer " + ta, "10.0.0.7")
        self.assertEqual(c, 200, o)
        self.assertEqual(self.inbox(tb)[0]["fk"], fk)

    def test_only_on_an_allow_and_only_that_shape(self):
        it = {"kind": "rc", "rc": "allow", "rcid": "abcdef12", "room": "alpha", "share": SHARE, "from": A, "fk": "k" * 43}
        self.assertEqual(kr.rc_item_clean(it)["fk"], "k" * 43)
        for bad in ("k" * 42, "k" * 44, "k" * 42 + "!", "<script>" + "k" * 35):
            self.assertNotIn("fk", kr.rc_item_clean(dict(it, fk=bad)), bad)
        self.assertNotIn("fk", kr.rc_item_clean(dict(it, rc="stop")))
        self.assertNotIn("fk", kr.rc_item_clean(dict(it, rc="ask")))


# ---- wiring ------------------------------------------------------------------------------------------------------------------------
class Wiring(unittest.TestCase):
    def test_page(self):
        p = read("moq-watch-lite.html")
        # Kenton's prompt names file transfer
        self.assertIn('" asks to control " + what + ". They\\u2019ll be able to use your mouse, keyboard and clipboard, and copy files to and from your computer', p)
        self.assertIn("and copy files to and from their computer", p)
        # one session per grant, both ends; the key in the allow note
        self.assertIn('rcfStart("ctl", c);', p)
        self.assertIn('rcfStart("sharer", g);', p)
        self.assertIn("by: myOpName() || undefined, fk: g.fk }, p.tok);", p)
        self.assertIn('c.fk = RCF_FK_RE.test(String(it.fk || "")) ? String(it.fk) : "";', p)
        self.assertEqual(p.count("    rcfStop(why);"), 2)
        # the tracks: offers + wants under MY host, the chunks on their own broadcast below the video
        self.assertIn('CHANNEL + "/" + HOSTNAME1 + "/~rcf/" + statePeer()', p)
        self.assertIn('CHANNEL + "/" + HOSTNAME1 + "/~rcd/" + statePeer()', p)
        self.assertIn('["fo.json", "fq.json"]', p)
        self.assertIn('["fd"], { priority: RCF_PRIO, maxAge: 3000 }', p)
        self.assertIn("const RCF_WIN_BYTES = 8 * 1048576, RCF_RESEND_MS = 2500, RCF_PRIO = 30", p)
        self.assertIn("win: Math.max(4, Math.min(64, Math.ceil((Number(window.__rcfWinBytes) || RCF_WIN_BYTES) / (Number(e.pub.cs) || RCF_CS)))) };", p)
        self.assertEqual(rf.CHUNK, 512 << 10)
        self.assertIn("const RCF_CS = 524288,", p)   # a drop's chunks = kastr_rcfiles.CHUNK
        self.assertIn('crypto.subtle.encrypt({ name: "AES-GCM", iv: rcfIv(o.pub.oid, c)', p)
        # the paste waits for the files; a drop on the shared screen
        self.assertIn("rcfPaste(c).then(() => { fDone = true; go(); }", p)
        self.assertIn('cap.addEventListener("drop", (e) => rcfDropOn(c, t, e));', p)
        self.assertIn('"/api/rcfiles/put?rcid="', p)
        self.assertIn('"/api/rcfiles/chunk?rcid="', p)
        self.assertIn("#kRcFiles { position:fixed;", p)
        # the module is plain ASCII (escapes, the page's style) and its rows say n of m, MB and %
        i, j = p.index("// ---- 0.21.83 FILES AND PICTURES"), p.index("// ---- 0.21.66 (e) GRIDS FROM ANY ROOM")
        self.assertTrue(all(ord(ch) < 128 for ch in p[i:j]))
        self.assertIn('x.files + " of " + x.nfiles + " files, " : "") + rcfSize(x.bytes) + " of " + rcfSize(x.total) + " (" + pct + "%)"', p)
        self.assertIn('"Received " + what + " (" + rcfSize(r.bytes) + ") from " + s.name', p)
        self.assertIn('" copied " + what + " from your computer"', p)
        # the card's rows are kept by key and updated in place: a repaint never swaps the Cancel button under a click
        card = p[p.index("  function rcfPaint() {"):p.index("  function rcfAction(a) {")]
        self.assertNotIn("replaceChildren", card)
        self.assertIn("const keep = new Map([...el.children].map((n) => [n.dataset.k, n]));", card)
        self.assertIn("if (btn.textContent !== r.b[1]) btn.textContent = r.b[1];", card)
        self.assertIn("for (const n of keep.values()) n.remove();", card)
        # an "~rcf" / "~rcd" broadcast never becomes a tile (not .hang)
        self.assertIn('if (!path.endsWith(".hang")) continue; // skip internal .stats etc.', p)

    def test_server_and_build(self):
        s = read("kastr_serve.py")
        self.assertEqual(s.count('kastr_rcfiles.handle_api(self, _note, ini_get)'), 2)
        b = read("build.py")
        self.assertIn('"--hidden-import", "kastr_rcfiles", "--hidden-import", "kastr_rcfiles_x11"', b)
        for name in ("kastr_rcfiles.py", "kastr_rcfiles_x11.py"):
            with open(os.path.join(HERE, name), "rb") as f:
                raw = f.read()
            self.assertNotIn(b"\r\n", raw, name)   # LF like kastr_rc / kastr_x11

    def test_ini_templates_document_the_keys(self):
        for plat in ("windows", "linux"):
            t = read(os.path.join("extras", plat, "kastr.ini"))
            for k in ("rc_files", "rc_file_max_mb", "rc_session_max_mb", "rc_files_auto_mb", "rc_image_max_mb", "rc_files_keep_min"):
                self.assertIn("; " + k + " = ", t, (plat, k))


if __name__ == "__main__":
    unittest.main()
