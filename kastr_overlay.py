"""share_overlay.py -- Teams-style "you are sharing" overlay for KASTR (Windows).

Draws, while the host shares a window or a monitor:

  * a red click-through border (#E5484D, ~4 px at 100 %) around the target
    that follows the window as it moves / resizes and hides while the
    window is minimised, cloaked (other virtual desktop) or closed;
  * a small draggable dark pill at the top centre of the target --
    grip, "You're sharing a window|your screen", red "Stop sharing" button.

Both windows ask Windows to leave them OUT of every screen capture
(SetWindowDisplayAffinity WDA_EXCLUDEFROMCAPTURE, Windows 10 2004+), so they
never show up inside the shared video.  ctypes + stdlib only.

    ov = ShareOverlay(on_stop=lambda: print("stop"))
    ov.start(hwnd=0x1234)                       # a window
    ov.start(hmonitor=list_monitors()[0]["handle"], label="screen")
    ov.start(monitor_rect=(0, 0, 1920, 1080))   # a fixed rectangle
    ov.retarget(hwnd=other)                     # same overlay, new target
    ov.stop()

The overlay runs on its own thread with its own message loop; every public
method is thread-safe and start/stop may be repeated freely.  on_stop (and
on_target_gone) run on a short-lived daemon thread, so they may call
ov.stop() or do slow work without freezing the overlay.

Importable on any platform; on non-Windows start() just returns False.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time

__all__ = ["ShareOverlay", "PointerOverlay", "list_monitors", "list_windows", "set_process_dpi_awareness"]

log = logging.getLogger("kastr.overlay")
AVAILABLE = sys.platform == "win32"

# ---------------------------------------------------------------- colours / sizes
def _rgb(r, g, b):
    return r | (g << 8) | (b << 16)

BORDER_RGB = _rgb(0xE5, 0x48, 0x4D)
BAR_BG = _rgb(0x1F, 0x23, 0x29)
BAR_TEXT = _rgb(0xFF, 0xFF, 0xFF)
GRIP_RGB = _rgb(0x8B, 0x90, 0x98)
BTN_RGB = _rgb(0xE5, 0x48, 0x4D)
BTN_HOVER = _rgb(0xEE, 0x63, 0x67)
BTN_DOWN = _rgb(0xC4, 0x37, 0x3C)
# 0.21.83 (Kenton: "The pill should be smaller also"): shorter labels (were "You're sharing a window" ...)
LABELS = {"window": "Sharing a window", "screen": "Sharing your screen", "tab": "Sharing a tab"}
BTN_TEXT = "Stop sharing"
# 0.21.83: the pill's size at 96 dpi (scaled by the monitor's DPI): 28 px tall (was 40), 11 px text (was 13), 20 px buttons (was
# 28), tighter padding. pill_metrics / pill_layout / pill_place are pure (tested without a window).
PILL = {"h": 28, "font": 11, "btn_h": 20, "pad_l": 10, "grip_w": 6, "gap": 6, "gap2": 10, "btn_pad": 9, "gapb": 5,
        "inset": 4, "above": 4}
# 0.21.83 (Kenton: "When remote controlling, I am unable to see the red sharing pill at the top, so when I try to click in that
# space it doesn't work to click on the things behind the pill"): the pill is LAYERED (alpha 255: it looks the same) so that
# WS_EX_TRANSPARENT can make it click-through for a moment -- while the controller's injected press / drag / wheel lands on its
# area (kastr_rc: RemoteControl._bar_pass). The sharer's own clicks reach its buttons at every other time.
PILL_EX = 0x80000 | 0x8 | 0x80 | 0x08000000   # WS_EX_LAYERED | TOPMOST | TOOLWINDOW | NOACTIVATE
PASS_BIT = 0x20                               # WS_EX_TRANSPARENT


def pill_metrics(dpi=96):
    """0.21.83: the pill's sizes in physical pixels at `dpi`."""
    s = max(0.5, float(dpi or 96) / 96.0)
    m = {k: round(v * s) for k, v in PILL.items()}
    m["font"] = max(8, m["font"])
    m["s"] = s
    return m


def pill_layout(label_w, btn_ws, dpi=96):
    """0.21.83: -> {W, H, btns [(x0, y0, x1, y1)], grip (x, cy, d, step), text (x0, 0, x1, H)} for a label `label_w` px wide
    and buttons whose TEXT is `btn_ws` px wide (each gets btn_pad either side)."""
    m = pill_metrics(dpi)
    H, bh = m["h"], m["btn_h"]
    widths = [int(w) + 2 * m["btn_pad"] for w in btn_ws]
    pad_r = (H - bh) // 2
    W = m["pad_l"] + m["grip_w"] + m["gap"] + int(label_w) + m["gap2"] + sum(widths) + m["gapb"] * max(0, len(widths) - 1) + pad_r
    by = (H - bh) // 2
    bx = W - pad_r - sum(widths) - m["gapb"] * max(0, len(widths) - 1)
    btns = []
    for bw in widths:
        btns.append((bx, by, bx + bw, by + bh))
        bx += bw + m["gapb"]
    x0 = m["pad_l"] + m["grip_w"] + m["gap"]
    return {"W": W, "H": H, "btns": btns, "grip": (m["pad_l"], H // 2, max(3, round(3 * m["s"])), max(4, round(4 * m["s"]))),
            "text": (x0, 0, x0 + int(label_w) + 2, H)}


def pill_place(outer, t, size, work, dpi=96, kind="window", drag=(0, 0)):
    """0.21.83: where the pill goes -> (x, y, "above" | "inside"). Centred on the target; JUST ABOVE a shared window's top edge
    (its red border) when the monitor's work area has room there -- like kastr_x11.Bar -- so it covers nothing that is shared;
    else (a screen, or a window at the top of the screen) inside the top edge. Then the sharer's own drag offset, kept on the
    work area."""
    m = pill_metrics(dpi)
    w, h = size
    x = (outer[0] + outer[2]) // 2 - w // 2
    ya = outer[1] - h - m["above"]
    if kind == "window" and ya >= work[1]:
        y, where = ya, "above"
    else:
        y, where = outer[1] + t + m["inset"], "inside"
    x, y = x + int(drag[0]), y + int(drag[1])
    x = max(work[0], min(x, work[2] - w))
    y = max(work[1], min(y, work[3] - h))
    return x, y, where


def pill_button_style(key, control=False):
    """A button's brush: Allow green, Deny grey, Stop control white (red text); 0.21.83: Stop sharing on the RED control pill is
    grey (red on red would vanish), red on the plain pill."""
    if key == "share-stop" and control:
        return "ghost"
    return {"allow": "ok", "deny": "ghost", "stop": "white"}.get(key, "btn")


def pill_route(key, mode, has_on_button):
    """0.21.83: what a press on the pill's button does -> "stop" (on_stop: the share ends) | "button" (on_button(key)) | None.
    While someone controls this computer, "Stop sharing" goes to on_button: kastr_rc ends control FIRST, then the share
    (Kenton: "have that as well as stop sharing, to close out the share and control at the same time")."""
    if key == "share-stop":
        return "button" if mode == "control" and has_on_button else "stop"
    return "button" if has_on_button else None


def passthrough_exstyle(ex, on):
    """0.21.83: the pill's extended style with WS_EX_TRANSPARENT on (click-through) or off."""
    ex = int(ex) & 0xFFFFFFFF
    return (ex | PASS_BIT) if on else (ex & ~PASS_BIT & 0xFFFFFFFF)
# 0.21.79 (remote control): the bar also ASKS ("<name> asks to control your screen" -- Deny / Allow) and, while someone
# controls this computer, turns red ("<name> is controlling your screen -- Stop control (Ctrl+Alt+Space)").
CTL_BG = _rgb(0xB4, 0x23, 0x18)
OK_RGB = _rgb(0x1F, 0x7A, 0x4D)
GHOST_RGB = _rgb(0x3A, 0x3F, 0x47)
WHITE_RGB = _rgb(0xFF, 0xFF, 0xFF)
INJECT_MAGIC = 0x4B525443        # kastr_rc.MAGIC: input KASTR injected never presses these buttons

# 0.21.80 (Kenton: "I would like to have a mouse with a name of the person controlling it, rather than them controlling my own
# mouse. Allow both mice at the same time"): the arrow + name tag of whoever controls this computer, in their colour. A popup
# that is LAYERED (colour-keyed: only the arrow and the tag show), TRANSPARENT (clicks fall through to what is under it),
# TOPMOST, a TOOLWINDOW (no taskbar button) and NOACTIVATE (never takes focus) -- and left out of every screen capture
# (WDA_EXCLUDEFROMCAPTURE): viewers draw both people's pointers themselves, tagged, from the share's ptr.json.
POINTER_EX = 0x80000 | 0x20 | 0x8 | 0x80 | 0x08000000   # WS_EX_LAYERED | TRANSPARENT | TOPMOST | TOOLWINDOW | NOACTIVATE
POINTER_STYLE = 0x80000000                              # WS_POPUP
POINTER_AFFINITY = 0x11                                 # WDA_EXCLUDEFROMCAPTURE
POINTER_LWA = 0x1                                       # LWA_COLORKEY
POINTER_KEY = _rgb(0xFF, 0x00, 0xFF)                    # the key colour (never drawn)
POINTER_ARROW = ((0, 0), (0, 20), (5, 15), (9, 23), (12, 22), (8, 14), (14, 14))   # = kastr_x11.ARROW; the tip is the hotspot


def pointer_spec():
    """The pointer window's styles, exactly as PointerOverlay creates it (tested without creating it)."""
    return {"ex": POINTER_EX, "style": POINTER_STYLE, "affinity": POINTER_AFFINITY, "lwa": POINTER_LWA, "key": POINTER_KEY}


def pointer_geometry(name, dpi=96, char_w=7):
    """-> {w, h, arrow [(x, y)], tag (x, y, w, h), hot (x, y)} in physical pixels: the arrow (1 px in, for its white edge)
    at the top left, the name tag under its tail."""
    s = max(1.0, dpi / 96.0)
    arrow = [(int(round(x * s)) + 1, int(round(y * s)) + 1) for x, y in POINTER_ARROW]
    name = str(name or "")[:28]
    tx, ty = int(round(12 * s)) + 1, int(round(20 * s)) + 1
    tw, th = int(round((char_w * len(name) + 14) * s)), int(round(18 * s))
    w = max(max(x for x, _ in arrow) + 2, tx + tw + 1)
    return {"w": w, "h": ty + th + 1, "arrow": arrow, "tag": (tx, ty, tw, th), "hot": (1, 1)}


def hex_colorref(c, default=(0x00, 0x9F, 0xDA)):
    """"#rrggbb" -> a COLORREF (0x00BBGGRR)."""
    s = str(c or "").lstrip("#")
    try:
        if len(s) != 6:
            raise ValueError(s)
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except (ValueError, TypeError):
        r, g, b = default
    if (r, g, b) == (0xFF, 0x00, 0xFF):
        r, g, b = 0xFE, 0x00, 0xFF   # never the key colour itself
    return _rgb(r, g, b)


def ink_colorref(cr):
    """Black or white text on a COLORREF background."""
    r, g, b = cr & 0xFF, (cr >> 8) & 0xFF, (cr >> 16) & 0xFF
    return _rgb(0, 0, 0) if (0.2126 * r + 0.7152 * g + 0.0722 * b) > 150 else _rgb(0xFF, 0xFF, 0xFF)

if AVAILABLE:
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def _dll(name):
        try:
            return ctypes.WinDLL(name)
        except OSError:
            return None

    dwmapi = _dll("dwmapi")
    shcore = _dll("shcore")

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC,
                                         ctypes.POINTER(wt.RECT), wt.LPARAM)
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
                    ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                    ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [("hdc", wt.HDC), ("fErase", wt.BOOL), ("rcPaint", wt.RECT),
                    ("fRestore", wt.BOOL), ("fIncUpdate", wt.BOOL),
                    ("rgbReserved", ctypes.c_byte * 32)]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                    ("dwFlags", wt.DWORD), ("szDevice", ctypes.c_wchar * 32)]

    class TRACKMOUSEEVENT(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("dwFlags", wt.DWORD),
                    ("hwndTrack", wt.HWND), ("dwHoverTime", wt.DWORD)]

    def _bind(dll, name, res, *args):
        fn = getattr(dll, name, None) if dll is not None else None
        if fn is not None:
            fn.restype, fn.argtypes = res, list(args)
        return fn

    P = ctypes.POINTER
    I = ctypes.c_int
    RegisterClassExW = _bind(user32, "RegisterClassExW", wt.ATOM, P(WNDCLASSEXW))
    CreateWindowExW = _bind(user32, "CreateWindowExW", wt.HWND, wt.DWORD, wt.LPCWSTR, wt.LPCWSTR,
                            wt.DWORD, I, I, I, I, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID)
    DestroyWindow = _bind(user32, "DestroyWindow", wt.BOOL, wt.HWND)
    DefWindowProcW = _bind(user32, "DefWindowProcW", LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    GetMessageW = _bind(user32, "GetMessageW", I, P(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
    TranslateMessage = _bind(user32, "TranslateMessage", wt.BOOL, P(wt.MSG))
    DispatchMessageW = _bind(user32, "DispatchMessageW", LRESULT, P(wt.MSG))
    PostMessageW = _bind(user32, "PostMessageW", wt.BOOL, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    PostThreadMessageW = _bind(user32, "PostThreadMessageW", wt.BOOL, wt.DWORD, wt.UINT,
                               wt.WPARAM, wt.LPARAM)
    PostQuitMessage = _bind(user32, "PostQuitMessage", None, I)
    SetWindowPos = _bind(user32, "SetWindowPos", wt.BOOL, wt.HWND, wt.HWND, I, I, I, I, wt.UINT)
    ShowWindow = _bind(user32, "ShowWindow", wt.BOOL, wt.HWND, I)
    SetWindowRgn = _bind(user32, "SetWindowRgn", I, wt.HWND, wt.HRGN, wt.BOOL)
    SetLayeredWindowAttributes = _bind(user32, "SetLayeredWindowAttributes", wt.BOOL, wt.HWND,
                                       wt.DWORD, wt.BYTE, wt.DWORD)
    SetWindowDisplayAffinity = _bind(user32, "SetWindowDisplayAffinity", wt.BOOL, wt.HWND, wt.DWORD)
    GetWindowDisplayAffinity = _bind(user32, "GetWindowDisplayAffinity", wt.BOOL, wt.HWND, P(wt.DWORD))
    GetWindowRect = _bind(user32, "GetWindowRect", wt.BOOL, wt.HWND, P(wt.RECT))
    IsWindow = _bind(user32, "IsWindow", wt.BOOL, wt.HWND)
    IsIconic = _bind(user32, "IsIconic", wt.BOOL, wt.HWND)
    IsWindowVisible = _bind(user32, "IsWindowVisible", wt.BOOL, wt.HWND)
    GetForegroundWindow = _bind(user32, "GetForegroundWindow", wt.HWND)
    SetTimer = _bind(user32, "SetTimer", ctypes.c_size_t, wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p)
    KillTimer = _bind(user32, "KillTimer", wt.BOOL, wt.HWND, ctypes.c_size_t)
    BeginPaint = _bind(user32, "BeginPaint", wt.HDC, wt.HWND, P(PAINTSTRUCT))
    EndPaint = _bind(user32, "EndPaint", wt.BOOL, wt.HWND, P(PAINTSTRUCT))
    InvalidateRect = _bind(user32, "InvalidateRect", wt.BOOL, wt.HWND, ctypes.c_void_p, wt.BOOL)
    FillRect = _bind(user32, "FillRect", I, wt.HDC, P(wt.RECT), wt.HBRUSH)
    DrawTextW = _bind(user32, "DrawTextW", I, wt.HDC, wt.LPCWSTR, I, P(wt.RECT), wt.UINT)
    LoadCursorW = _bind(user32, "LoadCursorW", wt.HANDLE, wt.HINSTANCE, ctypes.c_void_p)
    SetCursor = _bind(user32, "SetCursor", wt.HANDLE, wt.HANDLE)
    ScreenToClient = _bind(user32, "ScreenToClient", wt.BOOL, wt.HWND, P(wt.POINT))
    SetCapture = _bind(user32, "SetCapture", wt.HWND, wt.HWND)
    ReleaseCapture = _bind(user32, "ReleaseCapture", wt.BOOL)
    TrackMouseEvent = _bind(user32, "TrackMouseEvent", wt.BOOL, P(TRACKMOUSEEVENT))
    MonitorFromRect = _bind(user32, "MonitorFromRect", wt.HMONITOR, P(wt.RECT), wt.DWORD)
    GetMonitorInfoW = _bind(user32, "GetMonitorInfoW", wt.BOOL, wt.HMONITOR, P(MONITORINFOEXW))
    EnumDisplayMonitors = _bind(user32, "EnumDisplayMonitors", wt.BOOL, wt.HDC, ctypes.c_void_p,
                                MONITORENUMPROC, wt.LPARAM)
    EnumWindows = _bind(user32, "EnumWindows", wt.BOOL, WNDENUMPROC, wt.LPARAM)
    GetWindowTextW = _bind(user32, "GetWindowTextW", I, wt.HWND, wt.LPWSTR, I)
    GetWindowLongPtrW = _bind(user32, "GetWindowLongPtrW", ctypes.c_ssize_t, wt.HWND, I)
    GetDC = _bind(user32, "GetDC", wt.HDC, wt.HWND)
    ReleaseDC = _bind(user32, "ReleaseDC", I, wt.HWND, wt.HDC)
    SetThreadDpiAwarenessContext = _bind(user32, "SetThreadDpiAwarenessContext",
                                         ctypes.c_void_p, ctypes.c_void_p)
    SetProcessDpiAwarenessContext = _bind(user32, "SetProcessDpiAwarenessContext",
                                          wt.BOOL, ctypes.c_void_p)
    GetDpiForMonitor = _bind(shcore, "GetDpiForMonitor", ctypes.c_long, wt.HMONITOR, I,
                             P(wt.UINT), P(wt.UINT))
    DwmGetWindowAttribute = _bind(dwmapi, "DwmGetWindowAttribute", ctypes.c_long, wt.HWND,
                                  wt.DWORD, ctypes.c_void_p, wt.DWORD)
    GetModuleHandleW = _bind(kernel32, "GetModuleHandleW", wt.HMODULE, wt.LPCWSTR)
    GetCurrentThreadId = _bind(kernel32, "GetCurrentThreadId", wt.DWORD)
    GetMessageExtraInfo = _bind(user32, "GetMessageExtraInfo", wt.LPARAM)   # 0.21.79
    MonitorFromPoint = _bind(user32, "MonitorFromPoint", wt.HMONITOR, wt.POINT, wt.DWORD)   # 0.21.80
    SetWindowLongPtrW = _bind(user32, "SetWindowLongPtrW", ctypes.c_ssize_t, wt.HWND, I, ctypes.c_ssize_t)   # 0.21.83

    CreateRectRgn = _bind(gdi32, "CreateRectRgn", wt.HRGN, I, I, I, I)
    CreateRoundRectRgn = _bind(gdi32, "CreateRoundRectRgn", wt.HRGN, I, I, I, I, I, I)
    CombineRgn = _bind(gdi32, "CombineRgn", I, wt.HRGN, wt.HRGN, wt.HRGN, I)
    DeleteObject = _bind(gdi32, "DeleteObject", wt.BOOL, wt.HGDIOBJ)
    CreateSolidBrush = _bind(gdi32, "CreateSolidBrush", wt.HBRUSH, wt.DWORD)
    SelectObject = _bind(gdi32, "SelectObject", wt.HGDIOBJ, wt.HDC, wt.HGDIOBJ)
    GetStockObject = _bind(gdi32, "GetStockObject", wt.HGDIOBJ, I)
    CreateCompatibleDC = _bind(gdi32, "CreateCompatibleDC", wt.HDC, wt.HDC)
    CreateCompatibleBitmap = _bind(gdi32, "CreateCompatibleBitmap", wt.HBITMAP, wt.HDC, I, I)
    BitBlt = _bind(gdi32, "BitBlt", wt.BOOL, wt.HDC, I, I, I, I, wt.HDC, I, I, wt.DWORD)
    DeleteDC = _bind(gdi32, "DeleteDC", wt.BOOL, wt.HDC)
    SetBkMode = _bind(gdi32, "SetBkMode", I, wt.HDC, I)
    SetTextColor = _bind(gdi32, "SetTextColor", wt.DWORD, wt.HDC, wt.DWORD)
    CreateFontW = _bind(gdi32, "CreateFontW", wt.HFONT, I, I, I, I, I, wt.DWORD, wt.DWORD, wt.DWORD,
                        wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR)
    GetTextExtentPoint32W = _bind(gdi32, "GetTextExtentPoint32W", wt.BOOL, wt.HDC, wt.LPCWSTR, I,
                                  P(wt.SIZE))
    RoundRect = _bind(gdi32, "RoundRect", wt.BOOL, wt.HDC, I, I, I, I, I, I)
    Ellipse = _bind(gdi32, "Ellipse", wt.BOOL, wt.HDC, I, I, I, I)
    Polygon = _bind(gdi32, "Polygon", wt.BOOL, wt.HDC, P(wt.POINT), I)          # 0.21.80
    CreatePen = _bind(gdi32, "CreatePen", wt.HPEN, I, I, wt.DWORD)              # 0.21.80

    # ------------------------------------------------------------ constants
    WS_POPUP = 0x80000000
    WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOPMOST = 0x80000, 0x20, 0x8
    WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
    BORDER_EX = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    BAR_EX = PILL_EX   # 0.21.83: + WS_EX_LAYERED (was TOPMOST | TOOLWINDOW | NOACTIVATE): click-through on demand
    HWND_TOPMOST = wt.HWND(-1)
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
    SWP_SHOWWINDOW, SWP_NOOWNERZORDER = 0x40, 0x200
    SW_HIDE = 0
    LWA_ALPHA = 0x2
    WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11
    DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
    MONITOR_DEFAULTTONEAREST, MONITORINFOF_PRIMARY = 2, 1
    DPI_PMV2 = ctypes.c_void_p(-4)        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    DT_LEFT, DT_CENTER, DT_VCENTER, DT_SINGLELINE, DT_NOPREFIX = 0, 1, 4, 0x20, 0x800
    SRCCOPY, TRANSPARENT_BK, NULL_PEN, RGN_DIFF = 0xCC0020, 1, 8, 4
    IDC_ARROW, IDC_HAND = 32512, 32649
    TME_LEAVE = 0x2
    HTTRANSPARENT, HTCLIENT, HTCAPTION, MA_NOACTIVATE = -1, 1, 2, 3
    WM_CLOSE, WM_PAINT, WM_ERASEBKGND, WM_SETCURSOR = 0x10, 0x0F, 0x14, 0x20
    WM_MOUSEACTIVATE, WM_NCHITTEST, WM_NCLBUTTONDBLCLK = 0x21, 0x84, 0xA3
    WM_TIMER, WM_SYSCOMMAND, WM_QUIT = 0x113, 0x112, 0x12
    WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x200, 0x201, 0x202
    WM_ENTERSIZEMOVE, WM_EXITSIZEMOVE, WM_MOUSELEAVE, WM_DPICHANGED = 0x231, 0x232, 0x2A3, 0x2E0
    WM_APP_STOP, WM_APP_RETARGET, WM_APP_MODE = 0x8001, 0x8002, 0x8003   # 0.21.79: + MODE
    WM_APP_PMOVE = 0x8004                                                # 0.21.80: PointerOverlay.move
    TIMER_ID, TICK_MS = 1, 100
    CLASS_NAME = "KastrShareOverlay"

# ---------------------------------------------------------------- module helpers
_class_lock = threading.Lock()
_class_atom = 0
_INSTANCES: dict = {}            # hwnd -> (ShareOverlay, "border" | "bar")


def set_process_dpi_awareness() -> bool:
    """Make the whole process per-monitor DPI aware v2 (call before any window
    exists; harmless no-op if a manifest or earlier call already fixed it)."""
    if not AVAILABLE or SetProcessDpiAwarenessContext is None:
        return False
    return bool(SetProcessDpiAwarenessContext(DPI_PMV2))


def _thread_pmv2():
    if AVAILABLE and SetThreadDpiAwarenessContext is not None:
        SetThreadDpiAwarenessContext(DPI_PMV2)


def _monitor_info(hmon):
    mi = MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(mi)
    if not hmon or not GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    m, w = mi.rcMonitor, mi.rcWork
    return {"handle": hmon, "rect": (m.left, m.top, m.right, m.bottom),
            "work": (w.left, w.top, w.right, w.bottom),
            "primary": bool(mi.dwFlags & MONITORINFOF_PRIMARY), "device": mi.szDevice}


def list_monitors() -> list:
    """Monitors (physical pixels when the caller is PMv2 aware), primary first."""
    if not AVAILABLE:
        return []
    found = []

    def cb(hmon, _hdc, _rc, _lp):
        info = _monitor_info(hmon)
        if info:
            found.append(info)
        return True
    EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    found.sort(key=lambda m: not m["primary"])
    return found


def _cloaked(hwnd) -> bool:
    if DwmGetWindowAttribute is None:
        return False
    v = wt.DWORD(0)
    return DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), 4) == 0 and v.value != 0


def _frame_rect(hwnd):
    r = wt.RECT()
    if (DwmGetWindowAttribute is None or DwmGetWindowAttribute(
            hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0):
        if not GetWindowRect(hwnd, ctypes.byref(r)):
            return None
    return (r.left, r.top, r.right, r.bottom)


def list_windows() -> list:
    """Visible, titled, non-minimised, non-cloaked top-level windows: [(hwnd, title, rect)]."""
    if not AVAILABLE:
        return []
    out = []
    buf = ctypes.create_unicode_buffer(256)

    def cb(hwnd, _lp):
        if not IsWindowVisible(hwnd) or IsIconic(hwnd) or _cloaked(hwnd):
            return True
        if GetWindowLongPtrW(hwnd, -20) & WS_EX_TOOLWINDOW:
            return True
        if GetWindowTextW(hwnd, buf, 256) and buf.value.strip():
            rc = _frame_rect(hwnd)
            if rc and rc[2] - rc[0] > 50 and rc[3] - rc[1] > 50:
                out.append((hwnd, buf.value, rc))
        return True
    EnumWindows(WNDENUMPROC(cb), 0)
    return out


def _dpi_of(hmon) -> int:
    if GetDpiForMonitor is not None and hmon:
        x, y = wt.UINT(96), wt.UINT(96)
        if GetDpiForMonitor(hmon, 0, ctypes.byref(x), ctypes.byref(y)) == 0 and x.value:
            return x.value
    return 96


def _lp_xy(lp):
    return ctypes.c_short(lp & 0xFFFF).value, ctypes.c_short((lp >> 16) & 0xFFFF).value


if AVAILABLE:
    @WNDPROC
    def _wndproc(hwnd, msg, wp, lp):
        ent = _INSTANCES.get(hwnd)
        if ent is not None:
            try:
                r = ent[0]._handle(ent[1], hwnd, msg, wp, lp)
                if r is not None:
                    return r
            except Exception:                       # never raise through a ctypes callback
                log.exception("share overlay: message 0x%x failed", msg)
        return DefWindowProcW(hwnd, msg, wp, lp)


def _ensure_class():
    global _class_atom
    with _class_lock:
        if _class_atom:
            return True
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(wc)
        wc.lpfnWndProc = _wndproc
        wc.hInstance = GetModuleHandleW(None)
        wc.hCursor = LoadCursorW(None, ctypes.c_void_p(IDC_ARROW))
        wc.lpszClassName = CLASS_NAME
        atom = RegisterClassExW(ctypes.byref(wc))
        if not atom and ctypes.get_last_error() != 1410:     # ERROR_CLASS_ALREADY_EXISTS
            return False
        _class_atom = atom or 1
        return True


class _Target:
    __slots__ = ("kind", "hwnd", "hmon", "rect", "label")

    def __init__(self, hwnd=None, monitor_rect=None, hmonitor=None, label=None):
        if hwnd:
            self.kind = "window"
        elif hmonitor:
            self.kind = "monitor"
        elif monitor_rect:
            self.kind = "rect"
        else:
            raise ValueError("ShareOverlay needs hwnd=, hmonitor= or monitor_rect=")
        self.hwnd = int(hwnd) if hwnd else None
        self.hmon = int(hmonitor) if hmonitor else None
        self.rect = tuple(int(v) for v in monitor_rect) if monitor_rect else None
        if label not in LABELS:
            label = "window" if self.kind == "window" else "screen"
        self.label = label


# ---------------------------------------------------------------- the overlay
class ShareOverlay:
    """Red border + "Stop sharing" bar around a shared window or monitor."""

    def __init__(self, on_stop=None, on_target_gone=None, thickness=4,
                 exclude_from_capture=True, process_dpi=True):
        self.on_stop = on_stop
        self.on_target_gone = on_target_gone
        self.thickness = thickness
        self.exclude_from_capture = exclude_from_capture
        self.process_dpi = process_dpi
        self._lock = threading.Lock()
        self._thread = None
        self._ready = threading.Event()
        self._err = None
        self._border = self._bar = None
        self._tid = 0
        self._pending = None
        self._stopping = False
        self._mode = ("share", None, None)   # 0.21.79: (mode, label, [(key, text)]) -- "share" | "prompt" | "control"
        self._mode_next = None
        self.on_button = None                # 0.21.79: on_button(key) for a prompt / control button
        self._pass = False                   # 0.21.83: click-through right now (set_passthrough)
        self._bar_where = ""                 # 0.21.83: "above" the shared window | "inside" its top edge
        self._reset_state()

    # ---------------------------------------------------------- public API
    def start(self, hwnd=None, monitor_rect=None, label=None, hmonitor=None) -> bool:
        """Show the overlay (or retarget it if already running). True when up."""
        if not AVAILABLE:
            return False
        tgt = _Target(hwnd, monitor_rect, hmonitor, label)
        with self._lock:
            th = self._thread
            running = th is not None and th.is_alive() and not self._stopping
        if running:
            return self._post_target(tgt)
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(3.0)                               # a stop still winding down
        if self.process_dpi:
            set_process_dpi_awareness()
        with self._lock:
            self._ready = threading.Event()
            self._err = None
            self._pending = tgt
            self._stopping = False
            self._thread = threading.Thread(target=self._run, name="kastr-share-overlay", daemon=True)
            self._thread.start()
            ready = self._ready
        ready.wait(5.0)
        return self._err is None and self._bar is not None

    def retarget(self, hwnd=None, monitor_rect=None, label=None, hmonitor=None) -> bool:
        """Point the running overlay at a new window / monitor (starts it if idle)."""
        if not AVAILABLE:
            return False
        tgt = _Target(hwnd, monitor_rect, hmonitor, label)
        if not self.running:
            return self.start(hwnd, monitor_rect, label, hmonitor)
        return self._post_target(tgt)

    def stop(self, timeout=3.0) -> None:
        """Tear both windows down and end the thread. Safe from any thread, repeatable."""
        with self._lock:
            th, ready = self._thread, self._ready
            if th is None:
                return
            self._stopping = True
        ready.wait(5.0)
        with self._lock:
            if self._bar:
                PostMessageW(self._bar, WM_APP_STOP, 0, 0)
            elif self._tid:
                PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        if th is not threading.current_thread():
            th.join(timeout)
            with self._lock:
                if self._thread is th and not th.is_alive():
                    self._thread = None

    def set_mode(self, mode="share", label=None, buttons=None, on_button=None) -> bool:
        """0.21.79: "share" (the plain bar), "prompt" or "control" with its own label and buttons [(key, text)];
        on_button(key) runs on a short-lived thread. A click KASTR injected itself never presses a button."""
        if not AVAILABLE:
            return False
        with self._lock:
            self._mode_next = (mode if mode in ("share", "prompt", "control") else "share", label, list(buttons or []) or None)
            self.on_button = on_button if mode != "share" else None
            ok = bool(self._bar and PostMessageW(self._bar, WM_APP_MODE, 0, 0))
        if mode != "control" and self._pass:   # 0.21.83: never left click-through once control is over
            self.set_passthrough(False)
        return ok

    def bar_rect(self):
        """0.21.79: where the bar is on the screen {x, y, w, h} (physical pixels), or None while hidden."""
        p = self._bar_pos
        if not self._shown or not p:
            return None
        return {"x": p[0], "y": p[1], "w": p[2], "h": p[3], "where": self._bar_where}   # 0.21.83: + where

    def set_passthrough(self, on) -> bool:
        """0.21.83: the pill click-through (on) or clickable again (off): WS_EX_TRANSPARENT on the layered pill, so the
        controller's injected press / drag / wheel on its area reaches the window behind it. Immediate (SetWindowLongPtr is
        synchronous); any thread. -> True when the style is as asked."""
        h = self._bar
        if not AVAILABLE or not h or SetWindowLongPtrW is None:
            return False
        ex = GetWindowLongPtrW(h, -20) & 0xFFFFFFFF
        new = passthrough_exstyle(ex, bool(on))
        if new != ex:
            SetWindowLongPtrW(h, -20, new)
        self._pass = bool(on)
        return True

    @property
    def passthrough(self) -> bool:
        return bool(getattr(self, "_pass", False))

    def request_stop(self) -> bool:
        """0.21.83: Stop sharing, as if the sharer clicked the pill's own Stop sharing (once per share; on its own thread).
        kastr_rc calls it for the control bar's "Stop sharing" AFTER control has ended."""
        if self._clicked or self.on_stop is None:
            return False
        self._clicked = True
        self._fire(self.on_stop)
        return True

    @property
    def running(self) -> bool:
        th = self._thread
        return bool(th is not None and th.is_alive() and not self._stopping)

    def info(self) -> dict:
        """Diagnostics: hwnds, ex-styles, capture-exclusion result, visibility."""
        d = {"running": self.running, "target": None, "border": self._border, "bar": self._bar,
             "affinity": dict(self._affinity), "visible": self._shown, "dpi": self._bar_dpi}
        t = self._target
        if t is not None:
            d["target"] = {"kind": t.kind, "hwnd": t.hwnd, "hmonitor": t.hmon,
                           "rect": t.rect, "label": t.label}
        for role in ("border", "bar"):
            h = getattr(self, "_" + role)
            if h:
                d[role + "_exstyle"] = GetWindowLongPtrW(h, -20) & 0xFFFFFFFF
                da = wt.DWORD(0)
                if GetWindowDisplayAffinity is not None and GetWindowDisplayAffinity(h, ctypes.byref(da)):
                    d[role + "_display_affinity"] = da.value
                r = wt.RECT()
                GetWindowRect(h, ctypes.byref(r))
                d[role + "_rect"] = (r.left, r.top, r.right, r.bottom)
        return d

    # ---------------------------------------------------------- thread side
    def _reset_state(self):
        self._target = None
        self._shown = False
        self._border_geom = None
        self._bar_pos = None
        self._bar_dpi = 0
        self._bar_size = (0, 0)
        self._drag = False
        self._drag_off = (0, 0)
        self._bar_default = (0, 0)
        self._hover = self._pressed = None   # 0.21.79: the key of the button under the pointer / held down
        self._btns = []
        self._tracking = False
        self._clicked = False
        self._gone_fired = False
        self._ticks = 0
        self._affinity = {}
        self._fonts = []
        self._brushes = {}
        self._hand = None

    def _post_target(self, tgt) -> bool:
        with self._lock:
            self._pending = tgt
            return bool(self._bar and PostMessageW(self._bar, WM_APP_RETARGET, 0, 0))

    def _run(self):
        try:
            _thread_pmv2()
            self._tid = GetCurrentThreadId()
            self._reset_state()
            self._create()
        except Exception as e:                         # report to start()
            self._err = e
            log.exception("share overlay: could not create windows")
            self._teardown()
            self._ready.set()
            return
        self._ready.set()
        msg = wt.MSG()
        try:
            while True:
                r = GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0 or r == -1:
                    break
                TranslateMessage(ctypes.byref(msg))
                DispatchMessageW(ctypes.byref(msg))
        finally:
            self._teardown()

    def _create(self):
        if not _ensure_class():
            raise OSError("RegisterClassExW failed: %d" % ctypes.get_last_error())
        hinst = GetModuleHandleW(None)
        for name in ("_border", "_bar"):
            ex = BORDER_EX if name == "_border" else BAR_EX
            h = CreateWindowExW(ex, CLASS_NAME, "KASTR sharing", WS_POPUP,
                                -32000, -32000, 1, 1, None, None, hinst, None)
            if not h:
                raise OSError("CreateWindowExW failed: %d" % ctypes.get_last_error())
            _INSTANCES[h] = (self, name[1:])
            setattr(self, name, h)
            SetLayeredWindowAttributes(h, 0, 255, LWA_ALPHA)   # 0.21.83: the pill is layered too (fully opaque)
            ok = False
            if self.exclude_from_capture and SetWindowDisplayAffinity is not None:
                ok = bool(SetWindowDisplayAffinity(h, WDA_EXCLUDEFROMCAPTURE))
                if not ok:
                    log.info("share overlay: capture exclusion unavailable (%d)", ctypes.get_last_error())
            self._affinity[name[1:]] = ok
        b = self._brushes
        for key, col in (("border", BORDER_RGB), ("bg", BAR_BG), ("grip", GRIP_RGB),
                         ("btn", BTN_RGB), ("hover", BTN_HOVER), ("down", BTN_DOWN),
                         ("ctlbg", CTL_BG), ("ok", OK_RGB), ("ghost", GHOST_RGB), ("white", WHITE_RGB)):   # 0.21.79
            b[key] = CreateSolidBrush(col)
        self._hand = LoadCursorW(None, ctypes.c_void_p(IDC_HAND))
        with self._lock:
            self._target, self._pending = self._pending, None
        SetTimer(self._bar, TIMER_ID, TICK_MS, None)
        self._tick()

    def _teardown(self):
        for name in ("_bar", "_border"):
            h = getattr(self, name)
            if h:
                if name == "_bar":
                    KillTimer(h, TIMER_ID)
                DestroyWindow(h)
                _INSTANCES.pop(h, None)
            with self._lock:
                setattr(self, name, None)
        for f in self._fonts:
            DeleteObject(f)
        for br in self._brushes.values():
            DeleteObject(br)
        self._fonts, self._brushes = [], {}
        self._shown = False

    # ---------------------------------------------------------- geometry
    def _target_rect(self):
        t = self._target
        if t is None:
            return None, "hidden"
        if t.kind == "window":
            h = t.hwnd
            if not IsWindow(h):
                return None, "gone"
            if IsIconic(h) or not IsWindowVisible(h) or _cloaked(h):
                return None, "hidden"
            r = _frame_rect(h)
        elif t.kind == "monitor":
            info = _monitor_info(t.hmon)
            if info is None:
                return None, "gone"
            r = info["rect"]
        else:
            r = t.rect
        if not r or r[2] - r[0] < 8 or r[3] - r[1] < 8:
            return None, "hidden"
        return r, "ok"

    def _hide(self):
        if self._shown:
            ShowWindow(self._border, SW_HIDE)
            ShowWindow(self._bar, SW_HIDE)
            self._shown = False
            self._border_geom = self._bar_pos = None

    def _tick(self):
        if not self._border or not self._bar:
            return
        self._ticks += 1
        r, state = self._target_rect()
        if state != "ok":
            self._hide()
            if state == "gone" and not self._gone_fired:
                self._gone_fired = True
                self._fire(self.on_target_gone)
            return
        rc = wt.RECT(*r)
        hmon = MonitorFromRect(ctypes.byref(rc), MONITOR_DEFAULTTONEAREST)
        mon = _monitor_info(hmon) or {"rect": r, "work": r}
        dpi = _dpi_of(hmon)
        t = max(2, round(self.thickness * dpi / 96))
        mr = mon["rect"]
        if self._target.kind == "window":   # outside the frame where the monitor has room
            outer = (r[0] - t if r[0] - t >= mr[0] else r[0], r[1] - t if r[1] - t >= mr[1] else r[1],
                     r[2] + t if r[2] + t <= mr[2] else r[2], r[3] + t if r[3] + t <= mr[3] else r[3])
        else:
            outer = r
        was_shown = self._shown
        geom = (outer, t)
        if geom != self._border_geom:
            x, y, w, h = outer[0], outer[1], outer[2] - outer[0], outer[3] - outer[1]
            rgn = CreateRectRgn(0, 0, w, h)
            hole = CreateRectRgn(t, t, w - t, h - t)
            CombineRgn(rgn, rgn, hole, RGN_DIFF)
            DeleteObject(hole)
            SetWindowPos(self._border, HWND_TOPMOST, x, y, w, h,
                         SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOOWNERZORDER)
            if not SetWindowRgn(self._border, rgn, True):   # system owns rgn on success
                DeleteObject(rgn)
            self._border_geom = geom
        if not self._drag:
            self._place_bar(outer, t, dpi, force=not was_shown, work=mon["work"])
        self._shown = True
        if self._ticks % 10 == 0:                             # stay above new topmost windows
            for h in (self._border, self._bar):
                SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)

    def _place_bar(self, outer, t, dpi, force=False, work=None):
        if dpi != self._bar_dpi:
            self._layout(dpi)
        w, h = self._bar_size
        kind = self._target.kind if self._target is not None else "monitor"
        work = work or outer
        # 0.21.83: just ABOVE a shared window when its monitor has room there (pill_place), else inside its top edge
        dx, dy, _w0 = pill_place(outer, t, (w, h), work, self._bar_dpi, kind)
        self._bar_default = (dx, dy)
        x, y = dx + self._drag_off[0], dy + self._drag_off[1]
        rc = wt.RECT(x, y, x + w, y + h)
        hmon = MonitorFromRect(ctypes.byref(rc), MONITOR_DEFAULTTONEAREST)
        nd = _dpi_of(hmon)
        if nd != self._bar_dpi:                               # bar lands on a different-DPI monitor
            self._layout(nd)
            w, h = self._bar_size
        work2 = (_monitor_info(hmon) or {"work": work})["work"]
        x, y, where = pill_place(outer, t, (w, h), work2, self._bar_dpi, kind, self._drag_off)
        self._bar_where = where
        pos = (x, y, w, h)
        if pos != self._bar_pos or force:
            SetWindowPos(self._bar, HWND_TOPMOST, x, y, w, h,
                         SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOOWNERZORDER)
            self._bar_pos = pos

    def _measure(self, dpi):
        """0.21.83: fonts + the pill's layout (pill_layout) for the current mode at `dpi` -- no window needed (an offscreen
        render uses it too)."""
        m = pill_metrics(dpi)
        for f in self._fonts:
            DeleteObject(f)
        px = -m["font"]
        f_label = CreateFontW(px, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
        f_btn = CreateFontW(px, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
        self._fonts = [f_label, f_btn]
        mode, mlabel, mbtns = self._mode   # 0.21.79: a prompt / the control bar bring their own label and buttons
        label = mlabel if mode != "share" and mlabel else LABELS[self._target.label if self._target else "screen"]
        buttons = mbtns if mode != "share" and mbtns else [("share-stop", BTN_TEXT)]
        hdc = GetDC(None)
        sz = wt.SIZE()
        old = SelectObject(hdc, f_label)
        GetTextExtentPoint32W(hdc, label, len(label), ctypes.byref(sz))
        label_w = sz.cx
        SelectObject(hdc, f_btn)
        tws = []
        for _k, text in buttons:
            GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(sz))
            tws.append(sz.cx)
        SelectObject(hdc, old)
        ReleaseDC(None, hdc)
        lay = pill_layout(label_w, tws, dpi)
        W, H = lay["W"], lay["H"]
        self._btns = [(key, text, rc) for (key, text), rc in zip(buttons, lay["btns"])]
        self._btn = self._btns[-1][2]
        self._grip = lay["grip"]
        self._text_rc = lay["text"]
        self._label = label
        self._bar_size = (W, H)
        self._bar_dpi = dpi
        return W, H

    def _layout(self, dpi):
        W, H = self._measure(dpi)
        SetWindowPos(self._bar, None, 0, 0, W, H, SWP_NOMOVE | SWP_NOACTIVATE | 0x4)  # NOZORDER
        rgn = CreateRoundRectRgn(0, 0, W + 1, H + 1, H, H)
        if not SetWindowRgn(self._bar, rgn, True):
            DeleteObject(rgn)
        InvalidateRect(self._bar, None, False)
        self._bar_pos = None

    # ---------------------------------------------------------- painting
    def _paint_border(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = BeginPaint(hwnd, ctypes.byref(ps))
        FillRect(hdc, ctypes.byref(ps.rcPaint), self._brushes["border"])
        EndPaint(hwnd, ctypes.byref(ps))

    def _paint_bar(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = BeginPaint(hwnd, ctypes.byref(ps))
        try:
            W, H = self._bar_size
            if W <= 0 or not self._fonts:
                return
            mem = CreateCompatibleDC(hdc)
            bmp = CreateCompatibleBitmap(hdc, W, H)
            old_bmp = SelectObject(mem, bmp)
            self._draw(mem, W, H)
            BitBlt(hdc, 0, 0, W, H, mem, 0, 0, SRCCOPY)
            SelectObject(mem, old_bmp)
            DeleteObject(bmp)
            DeleteDC(mem)
        finally:
            EndPaint(hwnd, ctypes.byref(ps))

    def _draw(self, mem, W, H):
        """The pill's pixels into a memory DC (0.21.83: split out of _paint_bar -- an offscreen render draws the same)."""
        FillRect(mem, ctypes.byref(wt.RECT(0, 0, W, H)), self._brushes["ctlbg" if self._mode[0] == "control" else "bg"])   # 0.21.79
        old_pen = SelectObject(mem, GetStockObject(NULL_PEN))
        old_br = SelectObject(mem, self._brushes["grip"])
        gx, gy, d, step = self._grip                  # 2 x 3 dot grip
        for col in range(2):
            for row in (-1, 0, 1):
                cx, cy = gx + col * step, gy + row * step
                Ellipse(mem, cx, cy - d // 2, cx + d + 1, cy - d // 2 + d + 1)
        SetBkMode(mem, TRANSPARENT_BK)
        SetTextColor(mem, BAR_TEXT)
        old_font = SelectObject(mem, self._fonts[0])
        DrawTextW(mem, self._label, -1, ctypes.byref(wt.RECT(*self._text_rc)),
                  DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX)
        SelectObject(mem, self._fonts[1])
        control = self._mode[0] == "control"
        for bkey, btext, brc in self._btns:   # 0.21.79: one or more buttons
            base = pill_button_style(bkey, control)
            key = base if base != "btn" else ("down" if self._pressed == bkey and self._hover == bkey
                                              else "hover" if self._hover == bkey else "btn")
            SelectObject(mem, self._brushes[key])
            bx0, by0, bx1, by1 = brc
            bh = by1 - by0
            RoundRect(mem, bx0, by0, bx1 + 1, by1 + 1, bh, bh)
            SetTextColor(mem, CTL_BG if base == "white" else BAR_TEXT)
            DrawTextW(mem, btext, -1, ctypes.byref(wt.RECT(*brc)),
                      DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX)
        SelectObject(mem, old_font)
        SelectObject(mem, old_br)
        SelectObject(mem, old_pen)

    # ---------------------------------------------------------- messages
    def _in_btn(self, x, y):
        """0.21.79: the key of the button at (x, y), or None."""
        for key, _t, b in getattr(self, "_btns", None) or []:
            if b[0] <= x < b[2] and b[1] <= y < b[3]:
                return key
        return None

    def _set_hover(self, v):
        if v != self._hover:
            self._hover = v
            InvalidateRect(self._bar, None, False)

    def _fire(self, cb):
        if cb is not None:
            threading.Thread(target=self._safe_call, args=(cb,), daemon=True,
                             name="kastr-share-overlay-cb").start()

    @staticmethod
    def _safe_call(cb):
        try:
            cb()
        except Exception:
            log.exception("share overlay: callback failed")

    def _handle(self, role, hwnd, msg, wp, lp):
        if msg == WM_PAINT:
            (self._paint_border if role == "border" else self._paint_bar)(hwnd)
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if msg == WM_CLOSE:                         # only stop() closes these windows
            return 0
        if msg == WM_DPICHANGED:                    # we size ourselves in physical pixels
            if role == "bar" and self._target is not None:
                self._layout(wp & 0xFFFF)
            return 0
        if role == "border":
            return HTTRANSPARENT if msg == WM_NCHITTEST else None
        # ---- bar only
        if msg == WM_TIMER and wp == TIMER_ID:
            self._tick()
            return 0
        if msg == WM_NCHITTEST:
            pt = wt.POINT(*_lp_xy(lp))
            ScreenToClient(hwnd, ctypes.byref(pt))
            return HTCLIENT if self._in_btn(pt.x, pt.y) else HTCAPTION
        if msg == WM_SETCURSOR and (lp & 0xFFFF) == HTCLIENT:
            SetCursor(self._hand)
            return 1
        if msg == WM_MOUSEMOVE:
            if not self._tracking:
                tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE, hwnd, 0)
                self._tracking = bool(TrackMouseEvent(ctypes.byref(tme)))
            self._set_hover(self._in_btn(*_lp_xy(lp)))
            return 0
        if msg == WM_MOUSELEAVE:
            self._tracking = False
            self._set_hover(False)
            return 0
        if msg == WM_LBUTTONDOWN:
            k = self._in_btn(*_lp_xy(lp))
            injected = GetMessageExtraInfo is not None and (int(GetMessageExtraInfo() or 0) & 0xFFFFFFFF) == INJECT_MAGIC
            if k and not injected:                  # 0.21.79: the controller cannot press KASTR's own buttons
                self._pressed = k
                self._hover = k
                SetCapture(hwnd)
                InvalidateRect(hwnd, None, False)
            return 0
        if msg == WM_LBUTTONUP:
            if self._pressed:
                k, self._pressed = self._pressed, None
                ReleaseCapture()
                at = self._in_btn(*_lp_xy(lp))
                self._set_hover(at)
                InvalidateRect(hwnd, None, False)
                route = pill_route(k, self._mode[0], self.on_button is not None) if at == k else None   # 0.21.83
                if route == "stop":
                    if not self._clicked:
                        self._clicked = True        # one stop per share
                        self._fire(self.on_stop)
                elif route == "button":             # 0.21.79: Allow / Deny / Stop control; 0.21.83: + Stop sharing
                    cb = self.on_button
                    self._fire(lambda: cb(k))
            return 0
        if msg == WM_ENTERSIZEMOVE:
            self._drag = True
            return 0
        if msg == WM_EXITSIZEMOVE:
            self._drag = False
            r = wt.RECT()
            GetWindowRect(hwnd, ctypes.byref(r))
            self._drag_off = (r.left - self._bar_default[0], r.top - self._bar_default[1])
            self._bar_pos = (r.left, r.top) + self._bar_size
            return 0
        if msg == WM_NCLBUTTONDBLCLK:               # no maximise on double-click
            return 0
        if msg == WM_SYSCOMMAND and (wp & 0xFFF0) in (0xF000, 0xF020, 0xF030, 0xF060, 0xF120):
            return 0                                # size / min / max / close / restore
        if msg == WM_APP_RETARGET:
            with self._lock:
                tgt, self._pending = self._pending, None
            if tgt is not None:
                self._target = tgt
                self._drag_off = (0, 0)
                self._clicked = self._gone_fired = False
                self._bar_dpi = 0                   # relayout (label may change)
                self._border_geom = None
                self._hide()
                self._tick()
            return 0
        if msg == WM_APP_MODE:   # 0.21.79: the prompt / control bar / back to the plain bar
            with self._lock:
                nxt, self._mode_next = self._mode_next, None
            if nxt is not None:
                self._mode = nxt
                self._hover = self._pressed = None
                self._bar_dpi = 0                   # relayout: the label and buttons changed
                self._bar_pos = None
                self._tick()
                InvalidateRect(hwnd, None, False)
            return 0
        if msg == WM_APP_STOP:
            KillTimer(hwnd, TIMER_ID)
            PostQuitMessage(0)
            return 0
        return None


def render_pill(mode="share", label=None, buttons=None, target="window", dpi=96):
    """0.21.83: the pill's pixels WITHOUT any window (a memory bitmap, never on a screen) -> (W, H, BGRA bytes top-down):
    the same _measure + _draw the live pill paints with (screenshots, tests), plus [(button key, rect)]. The live pill is
    clipped to a round-ended region (SetWindowRgn); this bitmap is the full rectangle. Windows only; None elsewhere."""
    if not AVAILABLE:
        return None
    ov = ShareOverlay()
    ov._target = _Target(monitor_rect=(0, 0, 100, 100), label=target)
    ov._mode = (mode, label, list(buttons or []) or None)
    b = ov._brushes
    for key, col in (("border", BORDER_RGB), ("bg", BAR_BG), ("grip", GRIP_RGB), ("btn", BTN_RGB), ("hover", BTN_HOVER),
                     ("down", BTN_DOWN), ("ctlbg", CTL_BG), ("ok", OK_RGB), ("ghost", GHOST_RGB), ("white", WHITE_RGB)):
        b[key] = CreateSolidBrush(col)
    sdc = GetDC(None)
    mem = CreateCompatibleDC(sdc)
    try:
        W, H = ov._measure(dpi)
        bmp = CreateCompatibleBitmap(sdc, W, H)
        old = SelectObject(mem, bmp)
        ov._draw(mem, W, H)
        SelectObject(mem, old)

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
        bi = BIH(ctypes.sizeof(BIH), W, -H, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(W * H * 4)
        gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
        gdi32.GetDIBits(mem, bmp, 0, H, buf, ctypes.byref(bi), 0)
        DeleteObject(bmp)
        return W, H, buf.raw, [(k, rc) for k, _t, rc in ov._btns]
    finally:
        DeleteDC(mem)
        ReleaseDC(None, sdc)
        for f in ov._fonts:
            DeleteObject(f)
        for br in b.values():
            DeleteObject(br)


# ---------------------------------------------------------------- 0.21.80: the controller's pointer
class PointerOverlay:
    """The controller's own arrow + name tag on the sharer's screen (see POINTER_EX). start() -> True when the window is up;
    move(x, y, on) puts the arrow's tip at a screen pixel (on=False hides it); stop() ends it. Its own thread and message
    loop, like ShareOverlay; move() only posts a message, so the injector never waits on painting."""

    def __init__(self, name, color="#009fda", exclude_from_capture=True):
        self.name = str(name or "Someone")[:28]
        self.color = hex_colorref(color)
        self.exclude_from_capture = exclude_from_capture
        self.affinity_ok = False
        self._hwnd = None
        self._thread = None
        self._ready = threading.Event()
        self._pos = None
        self._geo = None
        self._gdi = []
        self._err = None

    def start(self) -> bool:
        if not AVAILABLE:
            return False
        self._thread = threading.Thread(target=self._run, name="kastr-rc-pointer", daemon=True)
        self._thread.start()
        self._ready.wait(5.0)
        return self._hwnd is not None

    def move(self, x, y, on=True):
        self._pos = (int(x), int(y)) if on else None
        h = self._hwnd
        if h:
            PostMessageW(h, WM_APP_PMOVE, 0, 0)

    def stop(self, timeout=3.0):
        h = self._hwnd
        if h:
            PostMessageW(h, WM_APP_STOP, 0, 0)
        th = self._thread
        if th is not None and th is not threading.current_thread():
            th.join(timeout)

    def _run(self):
        h = None
        try:
            _thread_pmv2()
            if not _ensure_class():
                raise OSError("RegisterClassExW failed: %d" % ctypes.get_last_error())
            hmon = MonitorFromPoint(wt.POINT(0, 0), 1) if MonitorFromPoint is not None else None   # MONITOR_DEFAULTTOPRIMARY
            s = _dpi_of(hmon) / 96.0
            g = self._geo = pointer_geometry(self.name, _dpi_of(hmon))
            spec = pointer_spec()
            h = CreateWindowExW(spec["ex"], CLASS_NAME, "KASTR pointer", spec["style"], -32000, -32000, g["w"], g["h"],
                                None, None, GetModuleHandleW(None), None)
            if not h:
                raise OSError("CreateWindowExW failed: %d" % ctypes.get_last_error())
            _INSTANCES[h] = (self, "pointer")
            SetLayeredWindowAttributes(h, spec["key"], 0, spec["lwa"])
            if self.exclude_from_capture and SetWindowDisplayAffinity is not None:
                self.affinity_ok = bool(SetWindowDisplayAffinity(h, spec["affinity"]))
            font = CreateFontW(-max(9, round(12 * s)), 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 4, 0, "Segoe UI")   # ANTIALIASED, never ClearType (key fringes)
            self._gdi = [CreateSolidBrush(POINTER_KEY), CreateSolidBrush(self.color), CreatePen(0, max(1, round(1.5 * s)), _rgb(0xFF, 0xFF, 0xFF)), font]
            self._hwnd = h
        except Exception as e:
            self._err = e
            log.exception("pointer overlay: could not create the window")
            if h:
                DestroyWindow(h)
                _INSTANCES.pop(h, None)
            self._ready.set()
            return
        self._ready.set()
        msg = wt.MSG()
        try:
            while True:
                r = GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0 or r == -1:
                    break
                TranslateMessage(ctypes.byref(msg))
                DispatchMessageW(ctypes.byref(msg))
        finally:
            hh, self._hwnd = self._hwnd, None
            if hh:
                DestroyWindow(hh)
                _INSTANCES.pop(hh, None)
            for o in self._gdi:
                DeleteObject(o)
            self._gdi = []

    def _paint(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = BeginPaint(hwnd, ctypes.byref(ps))
        try:
            g = self._geo
            key, fill, pen, font = self._gdi
            FillRect(hdc, ctypes.byref(wt.RECT(0, 0, g["w"], g["h"])), key)
            old_pen, old_br = SelectObject(hdc, pen), SelectObject(hdc, fill)
            pts = (wt.POINT * len(g["arrow"]))(*[wt.POINT(x, y) for x, y in g["arrow"]])
            Polygon(hdc, pts, len(g["arrow"]))
            SelectObject(hdc, GetStockObject(NULL_PEN))
            tx, ty, tw, th = g["tag"]
            RoundRect(hdc, tx, ty, tx + tw + 1, ty + th + 1, th // 2, th // 2)
            SetBkMode(hdc, TRANSPARENT_BK)
            SetTextColor(hdc, ink_colorref(self.color))
            old_font = SelectObject(hdc, font)
            DrawTextW(hdc, self.name, -1, ctypes.byref(wt.RECT(tx, ty, tx + tw, ty + th)), DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX)
            SelectObject(hdc, old_font)
            SelectObject(hdc, old_br)
            SelectObject(hdc, old_pen)
        finally:
            EndPaint(hwnd, ctypes.byref(ps))

    def _handle(self, role, hwnd, msg, wp, lp):
        if msg == WM_PAINT:
            self._paint(hwnd)
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_NCHITTEST:
            return HTTRANSPARENT
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if msg == WM_CLOSE:
            return 0
        if msg == WM_APP_PMOVE:
            p = self._pos
            if p is None:
                ShowWindow(hwnd, SW_HIDE)
            else:
                hx, hy = self._geo["hot"]
                SetWindowPos(hwnd, HWND_TOPMOST, p[0] - hx, p[1] - hy, 0, 0,
                             SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOOWNERZORDER)
            return 0
        if msg == WM_APP_STOP:
            PostQuitMessage(0)
            return 0
        return None


# ---------------------------------------------------------------- demo
def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="KASTR share overlay demo")
    ap.add_argument("--monitor", type=int, help="share monitor N (0 = primary)")
    ap.add_argument("--hwnd", type=lambda s: int(s, 0), help="share this window handle")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--no-exclude", action="store_true", help="debug: let captures see the overlay")
    ap.add_argument("--list", action="store_true", help="list monitors and windows, then exit")
    a = ap.parse_args(argv)
    if not AVAILABLE:
        print("Windows only")
        return 2
    set_process_dpi_awareness()
    if a.list:
        for i, m in enumerate(list_monitors()):
            print("monitor", i, m)
        for h, title, rc in list_windows():
            print("window 0x%x %r %s" % (h, title, rc))
        return 0
    clicked = threading.Event()

    def on_stop():
        print("Stop sharing clicked", flush=True)
        clicked.set()
    ov = ShareOverlay(on_stop=on_stop, on_target_gone=lambda: print("target closed", flush=True),
                      exclude_from_capture=not a.no_exclude)
    if a.monitor is not None:
        mons = list_monitors()
        ok = ov.start(hmonitor=mons[a.monitor]["handle"], label="screen")
    else:
        ok = ov.start(hwnd=a.hwnd or GetForegroundWindow(), label="window")
    print("started", ok, ov.info(), flush=True)
    clicked.wait(a.seconds)
    ov.stop()
    print("stopped", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main())
