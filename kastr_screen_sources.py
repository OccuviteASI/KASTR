"""screen_sources.py -- KASTR share-picker prototype (Windows only).

Enumerates every MONITOR and every shareable top-level WINDOW (the same
filter Teams / Chrome's getDisplayMedia picker use) and makes small JPEG
thumbnails for them, by one of two methods:

  win32   monitors: BitBlt from the screen DC of the monitor rect;
          windows : PrintWindow(hwnd, PW_RENDERFULLCONTENT) into a DIB;
          then StretchBlt(HALFTONE) to ~320 px and encode.
  ffmpeg  one frame from the bundled ffmpeg's gfxcapture filter
          (Windows.Graphics.Capture, hwnd= / hmonitor=), mjpeg to a pipe.
  auto    win32 first; a window whose PrintWindow picture comes back
          (nearly) all black is retried with ffmpeg.  (Recommended: on
          Win11 26200 win32 took ~50 ms vs ~260 ms and no GPU window --
          Chrome, Brave, Teams, Outlook, Claude -- came out black.)

Stdlib + ctypes.  Pillow is used ONLY for JPEG encoding when importable;
without it the win32 path returns PNG (stdlib zlib) -- see README.txt.

API
  list_sources(exclude_pids=()) -> [dict]
  thumbnail(source, width=320, method="auto") -> bytes | None
  thumbnail_ex(source, width=320, method="auto", force=False) -> dict
  window_icon_png(hwnd, size=32) -> bytes | None

CLI
  python screen_sources.py --list
  python screen_sources.py --thumbs OUTDIR [--method win32|ffmpeg|both] [--width 320]
"""

import ctypes
import ctypes.wintypes as W
import json
import os
import struct
import subprocess
import sys
import time
import zlib

try:                                    # optional -- JPEG encoding only
    from PIL import Image as _PILImage  # type: ignore
except Exception:                       # pragma: no cover
    _PILImage = None

FFMPEG = os.environ.get("KASTR_FFMPEG") or r"C:\Users\KentonJeffery\Claude\KASTR\bin\ffmpeg.exe"
FFMPEG_TIMEOUT = 5.0
JPEG_QUALITY = 70

# ---------------------------------------------------------------- ctypes ---

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
shell32 = ctypes.WinDLL("shell32")
try:
    shcore = ctypes.WinDLL("shcore")
except OSError:                         # pre-8.1
    shcore = None

LONG_PTR = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
HRESULT = ctypes.c_long


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT),
                ("dwFlags", W.DWORD), ("szDevice", W.WCHAR * 32)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG),
                ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG),
                ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", W.DWORD * 3)]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", W.UINT), ("flags", W.UINT), ("showCmd", W.UINT),
                ("ptMinPosition", W.POINT), ("ptMaxPosition", W.POINT),
                ("rcNormalPosition", W.RECT)]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", W.DWORD), ("DeviceName", W.WCHAR * 32), ("DeviceString", W.WCHAR * 128),
                ("StateFlags", W.DWORD), ("DeviceID", W.WCHAR * 128), ("DeviceKey", W.WCHAR * 128)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, ctypes.POINTER(W.RECT), W.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


def _proto(fn, res, *args):
    fn.restype = res
    fn.argtypes = list(args)
    return fn


_proto(user32.EnumDisplayMonitors, W.BOOL, W.HDC, ctypes.POINTER(W.RECT), MONITORENUMPROC, W.LPARAM)
_proto(user32.GetMonitorInfoW, W.BOOL, W.HMONITOR, ctypes.POINTER(MONITORINFOEXW))
_proto(user32.EnumDisplayDevicesW, W.BOOL, W.LPCWSTR, W.DWORD, ctypes.POINTER(DISPLAY_DEVICEW), W.DWORD)
_proto(user32.EnumWindows, W.BOOL, WNDENUMPROC, W.LPARAM)
_proto(user32.IsWindowVisible, W.BOOL, W.HWND)
_proto(user32.IsIconic, W.BOOL, W.HWND)
_proto(user32.IsHungAppWindow, W.BOOL, W.HWND)
_proto(user32.IsWindow, W.BOOL, W.HWND)
_proto(user32.GetWindowTextLengthW, ctypes.c_int, W.HWND)
_proto(user32.GetWindowTextW, ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
_proto(user32.GetClassNameW, ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
_proto(user32.GetWindowLongPtrW, LONG_PTR, W.HWND, ctypes.c_int)
_proto(user32.GetClassLongPtrW, ULONG_PTR, W.HWND, ctypes.c_int)
_proto(user32.GetWindow, W.HWND, W.HWND, W.UINT)
_proto(user32.GetWindowThreadProcessId, W.DWORD, W.HWND, ctypes.POINTER(W.DWORD))
_proto(user32.GetWindowRect, W.BOOL, W.HWND, ctypes.POINTER(W.RECT))
_proto(user32.GetWindowPlacement, W.BOOL, W.HWND, ctypes.POINTER(WINDOWPLACEMENT))
_proto(user32.SendMessageTimeoutW, LONG_PTR, W.HWND, W.UINT, W.WPARAM, W.LPARAM, W.UINT, W.UINT,
       ctypes.POINTER(ULONG_PTR))
_proto(user32.PrintWindow, W.BOOL, W.HWND, W.HDC, W.UINT)
_proto(user32.GetDC, W.HDC, W.HWND)
_proto(user32.ReleaseDC, ctypes.c_int, W.HWND, W.HDC)
_proto(user32.DrawIconEx, W.BOOL, W.HDC, ctypes.c_int, ctypes.c_int, W.HICON, ctypes.c_int,
       ctypes.c_int, W.UINT, W.HBRUSH, W.UINT)
_proto(user32.DestroyIcon, W.BOOL, W.HICON)
_proto(user32.GetDpiForWindow, W.UINT, W.HWND)
_proto(user32.MonitorFromWindow, W.HMONITOR, W.HWND, W.DWORD)
_proto(gdi32.CreateCompatibleDC, W.HDC, W.HDC)
_proto(gdi32.DeleteDC, W.BOOL, W.HDC)
_proto(gdi32.CreateDIBSection, W.HBITMAP, W.HDC, ctypes.POINTER(BITMAPINFO), W.UINT,
       ctypes.POINTER(ctypes.c_void_p), W.HANDLE, W.DWORD)
_proto(gdi32.SelectObject, W.HGDIOBJ, W.HDC, W.HGDIOBJ)
_proto(gdi32.DeleteObject, W.BOOL, W.HGDIOBJ)
_proto(gdi32.BitBlt, W.BOOL, W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
       W.HDC, ctypes.c_int, ctypes.c_int, W.DWORD)
_proto(gdi32.StretchBlt, W.BOOL, W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
       W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.DWORD)
_proto(gdi32.SetStretchBltMode, ctypes.c_int, W.HDC, ctypes.c_int)
_proto(gdi32.SetBrushOrgEx, W.BOOL, W.HDC, ctypes.c_int, ctypes.c_int, ctypes.POINTER(W.POINT))
_proto(gdi32.GdiFlush, W.BOOL)
_proto(kernel32.OpenProcess, W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
_proto(kernel32.CloseHandle, W.BOOL, W.HANDLE)
_proto(kernel32.QueryFullProcessImageNameW, W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD))
_proto(dwmapi.DwmGetWindowAttribute, HRESULT, W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD)
_proto(shell32.ExtractIconExW, W.UINT, W.LPCWSTR, ctypes.c_int, ctypes.POINTER(W.HICON),
       ctypes.POINTER(W.HICON), W.UINT)
if shcore is not None:
    _proto(shcore.GetDpiForMonitor, HRESULT, W.HMONITOR, ctypes.c_int,
           ctypes.POINTER(W.UINT), ctypes.POINTER(W.UINT))

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_NOACTIVATE = 0x80, 0x40000, 0x08000000
WS_CHILD = 0x40000000
GW_OWNER = 4
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
MONITORINFOF_PRIMARY = 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PW_RENDERFULLCONTENT = 2
SRCCOPY = 0x00CC0020
HALFTONE = 4
WM_GETICON, ICON_SMALL, ICON_BIG, ICON_SMALL2 = 0x7F, 0, 1, 2
GCLP_HICON, GCLP_HICONSM = -14, -34
SMTO_ABORTIFHUNG, SMTO_BLOCK = 0x2, 0x1
DI_NORMAL = 3
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                 "Windows.UI.Core.CoreWindow", "Button"}

_dpi_done = False


def ensure_dpi_aware():
    """Per-monitor-v2 DPI awareness so every rect is in physical pixels.
    Must run before the process creates any window (KASTR's host has none)."""
    global _dpi_done
    if _dpi_done:
        return
    _dpi_done = True
    try:
        user32.SetProcessDpiAwarenessContext.restype = W.BOOL
        user32.SetProcessDpiAwarenessContext.argtypes = [W.HANDLE]
        if user32.SetProcessDpiAwarenessContext(W.HANDLE(-4)):
            return
    except AttributeError:
        pass
    try:
        if shcore is not None:
            shcore.SetProcessDpiAwareness(2)
            return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def _rect(r):
    return {"x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top}


# --------------------------------------------------------------- listing ---

def _monitor_names():
    """\\\\.\\DISPLAY1 -> adapter string (EnumDisplayDevices); best effort."""
    out = {}
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(dd)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        mon = DISPLAY_DEVICEW()
        mon.cb = ctypes.sizeof(mon)
        if user32.EnumDisplayDevicesW(dd.DeviceName, 0, ctypes.byref(mon), 0) and mon.DeviceString:
            out[dd.DeviceName] = mon.DeviceString
        i += 1
    return out


def list_monitors():
    ensure_dpi_aware()
    handles = []

    @MONITORENUMPROC
    def cb(hmon, _hdc, _rc, _lp):
        handles.append(hmon)
        return True

    user32.EnumDisplayMonitors(None, None, cb, 0)
    names = _monitor_names()
    mons = []
    for hmon in handles:
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            continue
        scale = 1.0
        if shcore is not None:
            dx, dy = W.UINT(), W.UINT()
            if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                scale = round(dx.value / 96.0, 3)
        mons.append({"hmonitor": int(hmon), "device": mi.szDevice,
                     "model": names.get(mi.szDevice, ""),
                     "rect": _rect(mi.rcMonitor), "work": _rect(mi.rcWork),
                     "primary": bool(mi.dwFlags & MONITORINFOF_PRIMARY), "scale": scale})
    # Primary first, then left-to-right, top-to-bottom (what people call "Screen 1, 2")
    mons.sort(key=lambda m: (not m["primary"], m["rect"]["x"], m["rect"]["y"]))
    out = []
    for n, m in enumerate(mons, 1):
        out.append({"id": "monitor:%d" % n, "kind": "screen", "index": n,
                    "hmonitor": m["hmonitor"], "name": "Screen %d" % n,
                    "device": m["device"], "model": m["model"],
                    "rect": m["rect"], "work": m["work"], "primary": m["primary"],
                    "width": m["rect"]["w"], "height": m["rect"]["h"], "scale": m["scale"]})
    return out


def _exe_of(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = W.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def _cloaked(hwnd):
    v = W.DWORD()
    hr = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v))
    return hr == 0 and v.value != 0


def _frame_rect(hwnd):
    """Visible bounds (no invisible resize border); falls back to GetWindowRect."""
    r = W.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r),
                                    ctypes.sizeof(r)) == 0:
        return r
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def _text(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def list_windows(exclude_pids=()):
    ensure_dpi_aware()
    skip = set(int(p) for p in exclude_pids) | {os.getpid()}
    hwnds = []

    @WNDENUMPROC
    def cb(hwnd, _lp):
        hwnds.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)               # Z-order, topmost first -- keep it
    out = []
    for hwnd in hwnds:
        if not user32.IsWindowVisible(hwnd):
            continue
        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if style & WS_CHILD:
            continue
        appwin = bool(ex & WS_EX_APPWINDOW)
        if (ex & WS_EX_TOOLWINDOW) and not appwin:
            continue
        if user32.GetWindow(hwnd, GW_OWNER) and not appwin:
            continue
        if (ex & WS_EX_NOACTIVATE) and not appwin:   # overlays, tooltips, OSDs
            continue
        title = _text(hwnd)
        if not title.strip():
            continue
        cls = _class(hwnd)
        if cls in SHELL_CLASSES:
            continue
        if _cloaked(hwnd):                  # other virtual desktop / suspended UWP
            continue
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in skip:
            continue
        minimized = bool(user32.IsIconic(hwnd))
        if minimized:
            wp = WINDOWPLACEMENT()
            wp.length = ctypes.sizeof(wp)
            user32.GetWindowPlacement(hwnd, ctypes.byref(wp))
            rc = wp.rcNormalPosition          # where it will come back to
        else:
            rc = _frame_rect(hwnd)
        if rc.right - rc.left <= 0 or rc.bottom - rc.top <= 0:
            continue
        path = _exe_of(pid.value)
        out.append({"id": "window:%d" % hwnd, "kind": "window", "hwnd": int(hwnd),
                    "title": title, "exe": os.path.basename(path), "class": cls,
                    "pid": pid.value, "rect": _rect(rc), "minimized": minimized,
                    "hung": bool(user32.IsHungAppWindow(hwnd))})
    return out


def list_sources(exclude_pids=()):
    """Monitors first, then windows in Z-order (most recently used first)."""
    return list_monitors() + list_windows(exclude_pids)


# ------------------------------------------------------------ GDI helpers ---

class _Dib:
    """32-bit top-down DIB section selected into its own memory DC."""

    def __init__(self, w, h, ref_dc=None):
        self.w, self.h = w, h
        bmi = BITMAPINFO()
        hdr = bmi.bmiHeader
        hdr.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        hdr.biWidth, hdr.biHeight = w, -h
        hdr.biPlanes, hdr.biBitCount, hdr.biCompression = 1, 32, 0
        self.dc = gdi32.CreateCompatibleDC(ref_dc)
        self.bits = ctypes.c_void_p()
        self.bmp = gdi32.CreateDIBSection(self.dc, ctypes.byref(bmi), 0, ctypes.byref(self.bits), None, 0)
        if not self.bmp or not self.bits:
            gdi32.DeleteDC(self.dc)
            raise OSError("CreateDIBSection %dx%d failed (%d)" % (w, h, ctypes.get_last_error()))
        self.old = gdi32.SelectObject(self.dc, self.bmp)

    def data(self):
        gdi32.GdiFlush()
        return ctypes.string_at(self.bits, self.w * self.h * 4)   # BGRX rows, top-down

    def fill(self, byte):
        ctypes.memset(self.bits, byte, self.w * self.h * 4)

    def close(self):
        if self.dc:
            gdi32.SelectObject(self.dc, self.old)
            gdi32.DeleteObject(self.bmp)
            gdi32.DeleteDC(self.dc)
            self.dc = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _fit(w, h, width):
    tw = max(2, min(width, w))
    th = max(2, round(h * tw / w))
    return tw, th + (th & 1)


def _scaled_from(src_dc, sx, sy, sw, sh, width):
    """StretchBlt(HALFTONE) a region of src_dc into a new thumbnail DIB -> (bgrx, w, h)."""
    tw, th = _fit(sw, sh, width)
    with _Dib(tw, th) as dst:
        gdi32.SetStretchBltMode(dst.dc, HALFTONE)
        gdi32.SetBrushOrgEx(dst.dc, 0, 0, None)
        if not gdi32.StretchBlt(dst.dc, 0, 0, tw, th, src_dc, sx, sy, sw, sh, SRCCOPY):
            raise OSError("StretchBlt failed (%d)" % ctypes.get_last_error())
        return dst.data(), tw, th


def _grab_monitor_win32(src, width):
    r = src["rect"]
    screen = user32.GetDC(None)
    try:
        # Two steps (BitBlt full-size, HALFTONE from memory) -- HALFTONE straight
        # from the screen DC reads the frame buffer pixel by pixel and is slower.
        with _Dib(r["w"], r["h"], screen) as full:
            if not gdi32.BitBlt(full.dc, 0, 0, r["w"], r["h"], screen, r["x"], r["y"], SRCCOPY):
                raise OSError("BitBlt failed (%d)" % ctypes.get_last_error())
            return _scaled_from(full.dc, 0, 0, r["w"], r["h"], width)
    finally:
        user32.ReleaseDC(None, screen)


def _window_dpi_factor(hwnd):
    """window DPI / its monitor's DPI: 1.0 for per-monitor-aware windows,
    0.8 for an unaware window on a 125% monitor (what PrintWindow renders at)."""
    try:
        wdpi = user32.GetDpiForWindow(hwnd)
        hmon = user32.MonitorFromWindow(hwnd, 2)        # MONITOR_DEFAULTTONEAREST
        dx, dy = W.UINT(), W.UINT()
        if not wdpi or shcore is None or shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)):
            return 1.0
        return min(1.0, wdpi / float(dx.value or 96))
    except Exception:
        return 1.0


def _grab_window_win32(src, width):
    hwnd = W.HWND(src["hwnd"])
    wr = W.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(wr)):
        raise OSError("window gone")
    fr = _frame_rect(hwnd)
    ww, wh = wr.right - wr.left, wr.bottom - wr.top
    if ww <= 0 or wh <= 0:
        raise OSError("empty window")
    screen = user32.GetDC(None)
    try:
        with _Dib(ww, wh, screen) as full:
            if not user32.PrintWindow(hwnd, full.dc, PW_RENDERFULLCONTENT):
                raise OSError("PrintWindow failed (%d)" % ctypes.get_last_error())
            # crop the invisible resize border (and the off-monitor overhang of a maximized window)
            cx, cy = max(0, fr.left - wr.left), max(0, fr.top - wr.top)
            cw = min(ww - cx, fr.right - fr.left) or ww
            ch = min(wh - cy, fr.bottom - fr.top) or wh
            # A DPI-unaware / system-aware window is printed at its LOGICAL size into
            # the top-left of the physical-size DIB (the rest stays black) -- crop that.
            f = _window_dpi_factor(hwnd)
            if f < 0.99:
                cx, cy, cw, ch = int(cx * f), int(cy * f), max(2, int(cw * f)), max(2, int(ch * f))
            return _scaled_from(full.dc, cx, cy, cw, ch, width)
    finally:
        user32.ReleaseDC(None, screen)


# --------------------------------------------------------------- encoding ---

def _bgrx_to_rgb(buf):
    n = len(buf) // 4
    rgb = bytearray(n * 3)
    rgb[0::3] = buf[2::4]
    rgb[1::3] = buf[1::4]
    rgb[2::3] = buf[0::4]
    return bytes(rgb)


def _png(rgb, w, h, mode=2):
    """Minimal PNG writer (stdlib). mode 2 = RGB, 6 = RGBA."""
    bpp = 3 if mode == 2 else 4
    stride = w * bpp
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride] for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, mode, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def encode_bgrx(buf, w, h):
    """-> (bytes, mime).  JPEG with Pillow, PNG without."""
    if _PILImage is not None:
        import io
        im = _PILImage.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
        bio = io.BytesIO()
        im.save(bio, "JPEG", quality=JPEG_QUALITY)
        return bio.getvalue(), "image/jpeg"
    return _png(_bgrx_to_rgb(buf), w, h), "image/png"


def black_stats(buf, w, h, step=7):
    """(mean luma 0-255, fraction of pixels with luma < 16) from BGRX; sampled."""
    total = dark = n = 0
    for i in range(0, w * h, step):
        o = i * 4
        y = (29 * buf[o] + 150 * buf[o + 1] + 77 * buf[o + 2]) >> 8
        total += y
        dark += y < 16
        n += 1
    return (total / n if n else 0.0), (dark / n if n else 1.0)


def is_black(buf, w, h):
    mean, dark = black_stats(buf, w, h)
    return dark > 0.97 and mean < 8


# ----------------------------------------------------------------- ffmpeg ---

def _grab_ffmpeg(src, width):
    if src["kind"] == "screen":
        sel = "hmonitor=%d" % src["hmonitor"]
    else:
        sel = "hwnd=%d" % src["hwnd"]
    graph = ("gfxcapture=%s:max_framerate=5:capture_cursor=0,hwdownload,format=bgra,"
             "scale=%d:-2:flags=area,setsar=1,format=yuvj420p" % (sel, width))
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-filter_complex", graph,
           "-frames:v", "1", "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "4", "-"]
    # ffmpeg 9.0.1's gfxcapture often writes the frame and then never exits
    # (window captures hang in teardown), so read until the JPEG's EOI and kill.
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         stdin=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    import threading
    timer = threading.Timer(FFMPEG_TIMEOUT, p.kill)
    timer.start()
    buf = bytearray()
    try:
        fd = p.stdout.fileno()
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk
            if buf.startswith(b"\xff\xd8") and buf.endswith(b"\xff\xd9"):
                break
    finally:
        timer.cancel()
        if p.poll() is None:
            p.kill()
        try:
            err = p.communicate(timeout=2)[1]
        except Exception:
            err = b""
    if not (buf.startswith(b"\xff\xd8") and buf.endswith(b"\xff\xd9")):
        raise OSError("ffmpeg no frame within %.0fs (rc=%s): %s" % (
            FFMPEG_TIMEOUT, p.returncode, (err or b"").decode("utf-8", "replace").strip()[-300:]))
    return bytes(buf)


def _jpeg_size(data):
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        m = data[i + 1]
        ln = struct.unpack(">H", data[i + 2:i + 4])[0]
        if m in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + ln
    return None


# ------------------------------------------------------------- thumbnails ---

def thumbnail_ex(source, width=320, method="auto", force=False):
    """-> {"data", "mime", "w", "h", "method", "ms", "black", "error"}.
    A minimized window gives data=None (the page draws an icon placeholder)
    unless force=True (diagnostics only)."""
    ensure_dpi_aware()
    res = {"data": None, "mime": None, "w": 0, "h": 0, "method": method, "ms": 0.0,
           "black": None, "error": None}
    t0 = time.perf_counter()
    try:
        if source["kind"] == "window":
            hwnd = W.HWND(source["hwnd"])
            if not user32.IsWindow(hwnd):
                raise OSError("window gone")
            if user32.IsIconic(hwnd) and not force:
                res["error"] = "minimized"
                return res
            if user32.IsHungAppWindow(hwnd) and method != "ffmpeg":
                method = "ffmpeg"           # PrintWindow would block on a hung window
        if method in ("win32", "auto"):
            grab = _grab_monitor_win32 if source["kind"] == "screen" else _grab_window_win32
            buf, w, h = grab(source, width)
            black = is_black(buf, w, h)
            if black and method == "auto" and source["kind"] == "window":
                method = "ffmpeg"           # GPU surface PrintWindow could not read
            else:
                res["data"], res["mime"] = encode_bgrx(buf, w, h)
                res.update(w=w, h=h, black=black, method="win32")
        if method == "ffmpeg":
            data = _grab_ffmpeg(source, width)
            res["data"], res["mime"], res["method"] = data, "image/jpeg", "ffmpeg"
            res["w"], res["h"] = _jpeg_size(data) or (0, 0)
    except Exception as e:                  # noqa: BLE001 -- picker keeps going
        res["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        res["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return res


def thumbnail(source, width=320, method="auto"):
    """Thumbnail bytes (JPEG; PNG on the win32 path when Pillow is absent) or None."""
    return thumbnail_ex(source, width, method)["data"]


# ------------------------------------------------------------------- icon ---

def _hicon_of(hwnd, exe_path=None):
    """(hicon, owned) -- owned icons must be DestroyIcon'd."""
    res = ULONG_PTR()
    for kind in (ICON_BIG, ICON_SMALL2, ICON_SMALL):
        if user32.SendMessageTimeoutW(hwnd, WM_GETICON, kind, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK,
                                      200, ctypes.byref(res)) and res.value:
            return res.value, False
    for idx in (GCLP_HICON, GCLP_HICONSM):
        h = user32.GetClassLongPtrW(hwnd, idx)
        if h:
            return h, False
    if exe_path:
        big = W.HICON()
        if shell32.ExtractIconExW(exe_path, 0, ctypes.byref(big), None, 1) and big:
            return big.value, True
    return None, False


def window_icon_png(hwnd, size=32):
    """The window's app icon as a size x size RGBA PNG, or None.
    Alpha is recovered by drawing on black and on white (works for every icon kind)."""
    hwnd = W.HWND(int(hwnd))
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    hicon, owned = _hicon_of(hwnd, _exe_of(pid.value))
    if not hicon:
        return None
    try:
        with _Dib(size, size) as d:
            d.fill(0)
            user32.DrawIconEx(d.dc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
            on_black = d.data()
            d.fill(255)
            user32.DrawIconEx(d.dc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
            on_white = d.data()
    finally:
        if owned:
            user32.DestroyIcon(hicon)
    rgba = bytearray(size * size * 4)
    for i in range(size * size):
        o = i * 4
        a = 255 - (on_white[o + 1] - on_black[o + 1])        # green channel difference
        a = 0 if a < 0 else (255 if a > 255 else a)
        rgba[o + 3] = a
        if a:
            for c, s in ((0, 2), (1, 1), (2, 0)):            # BGR -> RGB, un-premultiply
                v = on_black[o + s] * 255 // a
                rgba[o + c] = 255 if v > 255 else v
    if not any(rgba[3::4]):
        return None
    return _png(bytes(rgba), size, size, mode=6)


# -------------------------------------------------------------------- CLI ---

def _cli_thumbs(outdir, methods, width):
    os.makedirs(outdir, exist_ok=True)
    srcs = list_sources()
    rows = []
    for s in srcs:
        for m in methods:
            r = thumbnail_ex(s, width, m, force=True)
            row = {"id": s["id"], "kind": s["kind"], "exe": s.get("exe", ""),
                   "minimized": s.get("minimized", False), "method": r["method"],
                   "asked": m, "ms": r["ms"], "bytes": len(r["data"] or b""),
                   "w": r["w"], "h": r["h"], "error": r["error"]}
            if r["data"]:
                ext = ".jpg" if r["mime"] == "image/jpeg" else ".png"
                fn = os.path.join(outdir, "%s_%s%s" % (s["id"].replace(":", "_"), m, ext))
                with open(fn, "wb") as f:
                    f.write(r["data"])
                row["file"] = os.path.basename(fn)
                if _PILImage is not None:   # blackness of what was actually produced
                    import io
                    im = _PILImage.open(io.BytesIO(r["data"])).convert("RGB")
                    raw = im.tobytes("raw", "BGRX")
                    mean, dark = black_stats(raw, im.width, im.height)
                    row["mean_luma"], row["dark_frac"] = round(mean, 1), round(dark, 3)
            if s["kind"] == "window" and m == methods[0]:
                t0 = time.perf_counter()
                ic = window_icon_png(s["hwnd"])
                row["icon_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                row["icon_bytes"] = len(ic or b"")
                if ic:
                    with open(os.path.join(outdir, "%s_icon.png" % s["id"].replace(":", "_")), "wb") as f:
                        f.write(ic)
            rows.append(row)
            print(json.dumps(row), flush=True)
    return rows


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="KASTR share-picker sources prototype")
    ap.add_argument("--list", action="store_true", help="print sources as JSON")
    ap.add_argument("--thumbs", metavar="OUTDIR", help="write every thumbnail + print timing")
    ap.add_argument("--method", default="both", choices=["win32", "ffmpeg", "auto", "both"])
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--exclude-pid", type=int, action="append", default=[])
    a = ap.parse_args(argv)
    ensure_dpi_aware()
    if a.list:
        t0 = time.perf_counter()
        srcs = list_sources(a.exclude_pid)
        print(json.dumps({"ms": round((time.perf_counter() - t0) * 1000, 1), "sources": srcs}, indent=1))
    if a.thumbs:
        methods = ["win32", "ffmpeg"] if a.method == "both" else [a.method]
        _cli_thumbs(a.thumbs, methods, a.width)
    if not (a.list or a.thumbs):
        ap.print_help()


if __name__ == "__main__":
    main()
