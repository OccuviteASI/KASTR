"""Remote control on the SHARER's computer (0.21.79; two pointers since 0.21.80).

Kenton (2026-10-22): "I want to add the capability to request remote control when someone is sharing their desktop and a
prompt to allow that user to take control of your machine. Local input always overrides remote input."
Kenton (2026-10-22, 0.21.80): "I would like to have a mouse with a name of the person controlling it, rather than them
controlling my own mouse. Allow both mice at the same time and show my mouse with my name for the viewers. Instead of my mouse
taking over their remote control." -- and: "I would like remote control to be faster if possible."

What runs where:
  * the relay carries the notes (ask / allow / deny / stop) between the two pages and checks who may send them
    (kastr_relay.rc_send: publishers and admins of the share's room ask, the sharer answers, rate limits);
  * the controller's page publishes its input as a MoQ track under its OWN host path (<room>/<host>/~rc/<peer>) -- a member
    token puts only under its own host, so nobody can speak for the controller;
  * the sharer's page subscribes to exactly that path while a grant is live and hands the events to THIS module over the
    loopback (a WebSocket, /api/rc/ws, since 0.21.80; POST /api/rc as the fallback), which injects them -- or refuses: no
    grant, a wrong grant id or controller, the share no longer on air or paused, a point outside the shared screen / window.

TWO POINTERS (0.21.80). The controller never moves the sharer's cursor any more:
  * their pointer is their OWN -- an arrow with their name in their colour, drawn on the sharer's screen by a topmost,
    click-through overlay (Windows: kastr_overlay.PointerOverlay, left out of every capture; X11: kastr_x11.PointerWin, which
    X11 cannot keep out of x11grab, so ptr.json says it is in the picture). Moving it moves nothing else.
  * a click / wheel lands at THEIR pointer. Windows: when the window under it is a classic Win32 control (an allowlist of
    window classes -- WIN_POST_CLASSES; DPI-safe coordinates) the button messages are POSTED to that child window with client
    coordinates and MK_ flags (no cursor involved, works on a covered window); every other app (Chromium / Electron, WPF, UWP,
    Qt, games... -- they read the real input state) gets a WARP-CLICK: the cursor jumps to the controller's point for the
    click (down to up: one or a few frames) and comes straight back -- plus whatever the sharer moved meanwhile. A drag in such
    an app holds the warp for the whole drag (the trade-off: the sharer's cursor is borrowed while the controller drags). A
    warp never starts while the sharer holds a mouse button (their own drag): it waits for their release (WARP_WAIT_S at most).
    A physical click DURING a warp is held back by the hook, the warp ends, and the click is replayed where the sharer is.
    X11: a second XInput2 MASTER pointer + keyboard ("KASTR remote") when the server allows it (kastr_x11.Mpx) -- the controller
    then truly has an independent pointer and keyboard focus; otherwise the same warp-click with XTest.
  * keys: both people type at once. Windows: SendInput while the shared window is in front (or a screen is shared); while it is
    not, characters / navigation keys are POSTED (WM_CHAR / WM_KEYDOWN) to its focused classic control; else "click inside the
    shared window first" (a warp-click brings it to the front). X11 MPX: the second keyboard has its own focus (the shared
    window, or the controller's pointer for a screen).
  * local input no longer pauses remote input (LOCAL_HOLD 0). Stop control, Ctrl+Alt+Space, the share stopping / pausing,
    leaving, closing KASTR and the lease still end control.
  * pointer samples (both people, normalised to the shared surface, PTR_HZ while either moves, nothing while still) go to the
    sharer's page, which publishes them as ptr.json; every viewer draws both pointers tagged over the share's tile (the
    sharer's real cursor stays in the capture and gets its name beside it; kastr_rtsp.Bridge.rc_mode -- the capture without
    the cursor + a low-latency encode -- exists but is off unless KASTR_RC_SHARE_MODE=1: see bridge_mode).

A grant lasts until it is stopped: the sharer's Stop control (the page, the native bar, Ctrl+Alt+Space), the share stopping
or pausing, either side leaving -- and a lease the sharer's page renews every second lapses after LEASE_S (the page closed,
the controller went quiet for that long). Every key and button the controller holds is released when control ends. Clipboard
TEXT follows changes both ways while a grant is live (CLIP_MAX bytes), never outside one.

Backends: WinBackend (PostMessage / SendInput, ctypes), X11Backend (XInput2 MPX / XTest, kastr_x11), MockBackend (records --
tests, and any lab on a desktop nobody must touch: KASTR_RC_MOCK=1).
"""
import base64
import hashlib
import json
import math
import os
import re
import select
import sys
import threading
import time
from collections import deque

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")
LOCAL_HOLD = 0.0       # 0.21.80: local input no longer holds remote input off (two pointers); 0.21.79 held it 3 s
LEASE_S = 10.0         # s: a grant the page stops renewing ends (page closed, KASTR hung, the controller dropped)
PROMPT_S = 60.0        # s: an unanswered prompt goes away
CLIP_MAX = 65536       # bytes of clipboard text, either way
EV_MAX = 256           # events in one batch from the page
MAGIC = 0x4B525443     # dwExtraInfo of every event KASTR injects on Windows ("KRTC"): our own bars ignore such clicks
REPLAY_MAGIC = 0x4B52544C   # 0.21.80 ("KRTL"): a sharer's own click held back during a warp, replayed where they are
WARP_WAIT_S = 8.0      # 0.21.80: s a controller's warp-click waits for the sharer's own drag (a physical button down) to end
PHYS_STALE_S = 30.0    # 0.21.80: a physical button "down" this old without its release is forgotten (a missed hook event)
PTR_HZ = 30            # 0.21.80: pointer samples per second at most (only while someone moves)
RCID_RE = re.compile(r"^[a-z0-9]{8,32}$")
HOST_RE = re.compile(r"^[a-z0-9-]{1,32}-[0-9a-f]{4}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# browser KeyboardEvent.code -> (Windows set-1 scan code, extended?, X11 keysym name). Keys travel by POSITION (as remote
# desktops do): the sharer's own keyboard layout makes the characters; text the controller pastes arrives by clipboard.
KEYS = {"Escape": (0x01, 0, "Escape"), "Minus": (0x0C, 0, "minus"), "Equal": (0x0D, 0, "equal"), "Backspace": (0x0E, 0, "BackSpace"),
        "Tab": (0x0F, 0, "Tab"), "BracketLeft": (0x1A, 0, "bracketleft"), "BracketRight": (0x1B, 0, "bracketright"),
        "Enter": (0x1C, 0, "Return"), "ControlLeft": (0x1D, 0, "Control_L"), "Semicolon": (0x27, 0, "semicolon"),
        "Quote": (0x28, 0, "apostrophe"), "Backquote": (0x29, 0, "grave"), "ShiftLeft": (0x2A, 0, "Shift_L"),
        "Backslash": (0x2B, 0, "backslash"), "Comma": (0x33, 0, "comma"), "Period": (0x34, 0, "period"), "Slash": (0x35, 0, "slash"),
        "ShiftRight": (0x36, 0, "Shift_R"), "NumpadMultiply": (0x37, 0, "KP_Multiply"), "AltLeft": (0x38, 0, "Alt_L"),
        "Space": (0x39, 0, "space"), "CapsLock": (0x3A, 0, "Caps_Lock"), "NumLock": (0x45, 1, "Num_Lock"),
        "ScrollLock": (0x46, 0, "Scroll_Lock"), "NumpadSubtract": (0x4A, 0, "KP_Subtract"), "NumpadAdd": (0x4E, 0, "KP_Add"),
        "NumpadDecimal": (0x53, 0, "KP_Decimal"), "IntlBackslash": (0x56, 0, "less"), "F11": (0x57, 0, "F11"), "F12": (0x58, 0, "F12"),
        "NumpadEnter": (0x1C, 1, "KP_Enter"), "ControlRight": (0x1D, 1, "Control_R"), "NumpadDivide": (0x35, 1, "KP_Divide"),
        "PrintScreen": (0x37, 1, "Print"), "AltRight": (0x38, 1, "Alt_R"), "Home": (0x47, 1, "Home"), "ArrowUp": (0x48, 1, "Up"),
        "PageUp": (0x49, 1, "Prior"), "ArrowLeft": (0x4B, 1, "Left"), "ArrowRight": (0x4D, 1, "Right"), "End": (0x4F, 1, "End"),
        "ArrowDown": (0x50, 1, "Down"), "PageDown": (0x51, 1, "Next"), "Insert": (0x52, 1, "Insert"), "Delete": (0x53, 1, "Delete"),
        "MetaLeft": (0x5B, 1, "Super_L"), "MetaRight": (0x5C, 1, "Super_R"), "ContextMenu": (0x5D, 1, "Menu")}
for _i, _c in enumerate("1234567890"):
    KEYS["Digit" + _c] = (0x02 + _i, 0, _c)
for _row, _base in (("QWERTYUIOP", 0x10), ("ASDFGHJKL", 0x1E), ("ZXCVBNM", 0x2C)):
    for _i, _c in enumerate(_row):
        KEYS["Key" + _c] = (_base + _i, 0, _c.lower())
for _i in range(10):
    KEYS["F%d" % (_i + 1)] = (0x3B + _i, 0, "F%d" % (_i + 1))
for _c, _sc in (("7", 0x47), ("8", 0x48), ("9", 0x49), ("4", 0x4B), ("5", 0x4C), ("6", 0x4D), ("1", 0x4F), ("2", 0x50), ("3", 0x51), ("0", 0x52)):
    KEYS["Numpad" + _c] = (_sc, 0, "KP_" + _c)
# browser MouseEvent.button -> (Windows down flag, up flag, XBUTTON data, X11 button)
BUTTONS = {0: (0x0002, 0x0004, 0, 1), 1: (0x0020, 0x0040, 0, 2), 2: (0x0008, 0x0010, 0, 3), 3: (0x0080, 0x0100, 1, 8), 4: (0x0080, 0x0100, 2, 9)}
X11_TO_BROWSER = {1: 0, 2: 1, 3: 2, 8: 3, 9: 4}
MODIFIERS = {"ShiftLeft": "shift", "ShiftRight": "shift", "ControlLeft": "ctrl", "ControlRight": "ctrl", "AltLeft": "alt",
             "AltRight": "altgr", "MetaLeft": "meta", "MetaRight": "meta"}
WHY_TEXT = {"bar": "stopped on the sharer's bar", "hotkey": "stopped with Ctrl+Alt+Space", "stopped": "stopped by the sharer",
            "timeout": "lost touch for 10 s", "share": "the share stopped", "paused": "the share was paused",
            "retarget": "the share now shows something else", "released": "released by the controller", "left": "left the room",
            "closed": "KASTR closed"}


# ---- pure helpers (tested) ------------------------------------------------------------------------------------------
def norm_point(u, v, rect, clip):
    """Normalised (u, v) on the shared surface -> a pixel inside `rect` {x, y, w, h}. clip=True clamps (moves); clip=False
    answers None for a point outside the surface (buttons, wheel) -- input never lands beside what is shared."""
    try:
        u, v = float(u), float(v)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(u) and math.isfinite(v)) or not rect or rect.get("w", 0) <= 0 or rect.get("h", 0) <= 0:
        return None
    if clip:
        u, v = min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0)
    elif not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        return None
    w, h = int(rect["w"]), int(rect["h"])
    return int(rect["x"]) + min(w - 1, int(u * w)), int(rect["y"]) + min(h - 1, int(v * h))


def to_norm(p, rect):
    """0.21.80: a screen pixel -> [u, v, on] on the shared surface (4 decimals; on = 1 inside it). None in, None out."""
    if p is None or not rect or rect.get("w", 0) <= 0 or rect.get("h", 0) <= 0:
        return None
    u = (float(p[0]) - rect["x"] + 0.5) / rect["w"]
    v = (float(p[1]) - rect["y"] + 0.5) / rect["h"]
    on = 1 if (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0) else 0
    return [round(u, 4), round(v, 4), on]


def win_absolute(px, py, vscreen):
    """A pixel -> SendInput's absolute 0..65535 over the VIRTUAL desktop (vscreen = SM_X/YVIRTUALSCREEN, SM_CX/CYVIRTUALSCREEN),
    used with MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK so every monitor (negative origins too) is reachable."""
    vx, vy, vw, vh = vscreen
    dx = round((px - vx) * 65535 / max(1, vw - 1))
    dy = round((py - vy) * 65535 / max(1, vh - 1))
    return min(65535, max(0, dx)), min(65535, max(0, dy))


def in_rect(px, py, r):
    return bool(r) and r["x"] <= px < r["x"] + r["w"] and r["y"] <= py < r["y"] + r["h"]


def ll_mouse_physical(flags, extra):
    """WH_MOUSE_LL: LLMHF_INJECTED (1) / LLMHF_LOWER_IL_INJECTED (2) mark synthesized input; ours also carries MAGIC."""
    return not (int(flags) & 0x3) and int(extra or 0) not in (MAGIC, REPLAY_MAGIC)


def ll_key_physical(flags, extra):
    """WH_KEYBOARD_LL: LLKHF_INJECTED (0x10) / LLKHF_LOWER_IL_INJECTED (0x02)."""
    return not (int(flags) & 0x12) and int(extra or 0) != MAGIC


# WH_MOUSE_LL wParam -> ("down" | "up", browser button) for the physical-button tracking (0.21.80); XBUTTON from mouseData
LL_BUTTONS = {0x201: ("down", 0), 0x202: ("up", 0), 0x204: ("down", 2), 0x205: ("up", 2), 0x207: ("down", 1), 0x208: ("up", 1)}


def ll_button(wparam, mouse_data):
    """-> ("down" | "up", browser button) for a WH_MOUSE_LL message, or None (moves, wheels)."""
    hit = LL_BUTTONS.get(int(wparam))
    if hit:
        return hit
    if int(wparam) in (0x20B, 0x20C):   # WM_XBUTTONDOWN / UP: XBUTTON1 / 2 in the high word
        x = (int(mouse_data) >> 16) & 0xFFFF
        return ("down" if int(wparam) == 0x20B else "up", 3 if x == 1 else 4)
    return None


class HotkeyState:
    """Ctrl+Alt+Space from the PHYSICAL keyboard (virtual-key codes): feed(vk, down) -> True on the hotkey's Space press."""
    CTRL, ALT = (0x11, 0xA2, 0xA3), (0x12, 0xA4, 0xA5)

    def __init__(self):
        self.down = set()

    def feed(self, vk, down):
        if down:
            self.down.add(vk)
        else:
            self.down.discard(vk)
        return bool(down and vk == 0x20 and self.down & set(self.CTRL) and self.down & set(self.ALT))


def clip_ok(text):
    """-> (ok, bytes): text within CLIP_MAX (UTF-8)."""
    n = len(str(text).encode("utf-8"))
    return n <= CLIP_MAX, n


def surface_of(url):
    """screen://monitor/<n> | screen://window/<id> | screen://tab/<id>/<i> -> ("monitor"|"window"|"tab", n) or None."""
    m = re.match(r"^screen://(monitor|window|tab)/(\d{1,20})(?:/\d{1,4})?$", str(url or ""), re.I)
    return (m.group(1).lower(), int(m.group(2))) if m else None


def clean_color(c, default="#009fda"):
    return str(c).lower() if COLOR_RE.match(str(c or "")) else default


# ---- 0.21.80: Windows messages for a click at the controller's pointer (pure: tested without any window) ----------------
WM_MOUSEMOVE, WM_MOUSEWHEEL, WM_MOUSEHWHEEL = 0x0200, 0x020A, 0x020E
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0100, 0x0101, 0x0102
# browser button -> (down, up, double-click) messages
WIN_BTN_MSG = {0: (0x0201, 0x0202, 0x0203), 2: (0x0204, 0x0205, 0x0206), 1: (0x0207, 0x0208, 0x0209),
               3: (0x020B, 0x020C, 0x020D), 4: (0x020B, 0x020C, 0x020D)}
MK_BTN = {0: 0x0001, 2: 0x0002, 1: 0x0010, 3: 0x0020, 4: 0x0040}
MK_SHIFT, MK_CONTROL = 0x0004, 0x0008
# Classic Win32 controls that act on POSTED mouse / key messages (their window procedures read the message's own lParam /
# wParam). Everything else -- Chromium / Electron, Firefox, WPF, UWP / WinUI, Qt, DirectUI (Explorer), Office documents,
# consoles, games, menus -- reads the real input state (GetKeyState, raw input, the cursor) and gets a warp-click instead.
WIN_POST_CLASSES = frozenset({
    "Edit", "Button", "Static", "ComboBox", "ComboLBox", "ListBox", "SysListView32", "SysTreeView32", "SysTabControl32",
    "SysHeader32", "ToolbarWindow32", "ReBarWindow32", "msctls_trackbar32", "msctls_updown32", "msctls_statusbar32",
    "msctls_progress32", "SysLink", "SysDateTimePick32", "SysMonthCal32", "SysIPAddress32", "#32770", "Scintilla",
    "RichEdit20A", "RichEdit20W", "RICHEDIT50W", "RichEdit50W", "NotepadPlusPlus", "MDIClient", "ScrollBar"})
WIN_POST_PREFIXES = ("Afx", "WindowsForms10.", "ATL:")
WIN_WARP_HINTS = ("Chrome_", "Mozilla", "HwndWrapper", "Windows.UI.", "ApplicationFrame", "DirectUIHWND", "Qt", "SDL_",
                  "Unity", "GLFW", "CASCADIA", "ConsoleWindowClass", "PseudoConsoleWindow", "_WwG", "_WwB", "OpusApp",
                  "EXCEL", "XLMAIN", "PPTFrame", "mdiClass", "#32768", "Intermediate D3D", "CEF", "UnrealWindow", "Direct3D")


def make_lparam(x, y):
    """MAKELPARAM(x, y) with x / y as signed 16-bit (a client point left of / above a window is negative)."""
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def mk_flags(held, mods=()):
    """MK_ flags: the mouse buttons held (browser numbers) + Shift / Ctrl held by the controller."""
    f = 0
    for b in held or ():
        f |= MK_BTN.get(int(b), 0)
    m = set(mods or ())
    if "shift" in m:
        f |= MK_SHIFT
    if "ctrl" in m:
        f |= MK_CONTROL
    return f


def win_post_button(b, down, cx, cy, held_before, mods=(), dbl=False):
    """[(msg, wParam, lParam)] to POST to the child window under the controller's pointer for one button event, client
    coordinates. A press is preceded by a WM_MOUSEMOVE to the same point (controls hit-test on it). wParam's MK_ flags are the
    state AFTER the event (Windows reports the pressed button in its own WM_xBUTTONDOWN, not in its WM_xBUTTONUP); X buttons
    carry XBUTTON1 / 2 in the high word."""
    b = int(b)
    dn, up, dc = WIN_BTN_MSG[b]
    held = set(held_before or ())
    after = (held | {b}) if down else (held - {b})
    hi = ((1 if b == 3 else 2) << 16) if b in (3, 4) else 0
    lp = make_lparam(cx, cy)
    if down:
        return [(WM_MOUSEMOVE, mk_flags(held, mods), lp), (dc if dbl else dn, mk_flags(after, mods) | hi, lp)]
    return [(up, mk_flags(after, mods) | hi, lp)]


def win_post_move(cx, cy, held, mods=()):
    return (WM_MOUSEMOVE, mk_flags(held, mods), make_lparam(cx, cy))


def win_post_wheel(notches, horizontal, sx, sy, held=(), mods=()):
    """WM_MOUSEWHEEL / WM_MOUSEHWHEEL: the delta (120 a notch) in wParam's HIGH word, MK_ flags in its low word, and the
    point in SCREEN coordinates (unlike the button messages). Browser deltas say "down / right is positive"; the vertical wheel
    says "away from the user is positive"."""
    delta = int(round((notches if horizontal else -notches) * 120))
    return (WM_MOUSEHWHEEL if horizontal else WM_MOUSEWHEEL, ((delta & 0xFFFF) << 16) | mk_flags(held, mods), make_lparam(sx, sy))


def win_key_lparam(sc, ext, down, repeat=1):
    """WM_KEYDOWN / WM_KEYUP lParam: repeat count (bits 0-15), scan code (16-23), extended (24), previous state (30) and
    transition (31) both set on a release."""
    lp = (int(repeat) & 0xFFFF) | ((int(sc) & 0xFF) << 16) | ((1 if ext else 0) << 24)
    if not down:
        lp |= (1 << 30) | (1 << 31)
    return lp


def win_post_friendly(cls):
    cls = str(cls or "")
    if not cls or any(cls.startswith(h) for h in WIN_WARP_HINTS):
        return False
    return cls in WIN_POST_CLASSES or cls.startswith(WIN_POST_PREFIXES)


def click_plan(child_cls, top_cls, awareness, dpi_window, dpi_monitor):
    """0.21.80: post or warp for a click at the controller's pointer on Windows -> ("post" | "warp", why).
    Posted only to a classic control (win_post_friendly) inside a top-level that is not a known framework host, and only where
    client coordinates are physical pixels (a per-monitor-aware window, or a window whose DPI is the monitor's) -- a
    DPI-virtualised window would get the click scaled to the wrong spot."""
    if not win_post_friendly(child_cls):
        return "warp", "class"
    if top_cls and any(str(top_cls).startswith(h) for h in WIN_WARP_HINTS):
        return "warp", "host"
    if int(awareness or 0) != 2 and int(dpi_window or 96) != int(dpi_monitor or 96):
        return "warp", "dpi"
    return "post", ""


def is_dblclick(prev, now, b, hwnd, x, y, interval_ms=500, cx=4, cy=4):
    """A posted press never becomes a double-click by itself (the system pairs real presses): the second press of the same
    button on the same window within the double-click time and rectangle is posted as WM_xBUTTONDBLCLK. prev = (t, b, hwnd,
    x, y) of the last press, t in seconds."""
    if not prev:
        return False
    t0, b0, h0, x0, y0 = prev
    return b0 == b and h0 == hwnd and (now - t0) * 1000 <= interval_ms and abs(x - x0) <= cx and abs(y - y0) <= cy


def restore_point(saved, last, cur, vscreen):
    """Where a warp-click puts the cursor back: where it was before the warp plus whatever the sharer moved it meanwhile
    (cur - the last point KASTR put it at), kept on the virtual desktop."""
    vx, vy, vw, vh = vscreen
    x = int(saved[0]) + (int(cur[0]) - int(last[0])) if cur and last else int(saved[0])
    y = int(saved[1]) + (int(cur[1]) - int(last[1])) if cur and last else int(saved[1])
    return min(vx + vw - 1, max(vx, x)), min(vy + vh - 1, max(vy, y))


class WarpState:
    """0.21.80: a warp-click in flight on Windows. begin(saved cursor, target) / moved(target) / end(cur, vscreen) -> the
    restore point. The low-level mouse hook asks physical(kind, button) for every PHYSICAL press / release: a press during a
    warp is SWALLOWED (it would land at the controller's point) and replayed by take() after the warp ends -- and so is the
    release of a press swallowed that way, while the replay is pending."""

    def __init__(self):
        self.active = False
        self.saved = self.last = None
        self.swallowed = []
        self.lock = threading.Lock()

    def begin(self, saved, at):
        with self.lock:
            self.active, self.saved, self.last = True, tuple(saved), tuple(at)

    def moved(self, at):
        with self.lock:
            if self.active:
                self.last = tuple(at)

    def physical(self, kind, b):
        with self.lock:
            if self.active and kind == "down":
                self.swallowed.append(("down", b))
                return True
            if kind == "up" and any(k == "down" and x == b for k, x in self.swallowed):
                self.swallowed.append(("up", b))
                return True
            return False

    def end(self, cur, vscreen):
        with self.lock:
            if not self.active:
                return None
            self.active = False
            return restore_point(self.saved, self.last, cur, vscreen)

    def take(self):
        with self.lock:
            out, self.swallowed = self.swallowed, []
            return out


# ---- Windows: SendInput ----------------------------------------------------------------------------------------------
import ctypes  # noqa: E402

_DW, _LONG, _WORD, _ULP = ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint16, ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", _LONG), ("dy", _LONG), ("mouseData", _DW), ("dwFlags", _DW), ("time", _DW), ("dwExtraInfo", _ULP)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", _WORD), ("wScan", _WORD), ("dwFlags", _DW), ("time", _DW), ("dwExtraInfo", _ULP)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", _DW), ("wParamL", _WORD), ("wParamH", _WORD)]


class _INPUTU(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", _DW), ("u", _INPUTU)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0001, 0x0002, 0x0008


def win_mouse(dx=0, dy=0, flags=0, data=0, extra=MAGIC):
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(int(dx), int(dy), ctypes.c_uint32(int(data)).value, int(flags), 0, extra)
    return i


def win_move(px, py, vscreen, extra=MAGIC):
    dx, dy = win_absolute(px, py, vscreen)
    return win_mouse(dx, dy, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, extra=extra)


def win_button(b, down, extra=MAGIC):
    d, u, x, _ = BUTTONS[b]
    return win_mouse(0, 0, d if down else u, x, extra=extra)


def win_wheel(notches, horizontal=False):
    """Browser deltas say "down / right is positive"; Windows' vertical wheel says "away from the user is positive"."""
    delta = int(round((notches if horizontal else -notches) * 120))
    return win_mouse(0, 0, MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL, delta)


def win_key(code, down):
    k = KEYS.get(code)
    if k is None:
        return None
    sc, ext, _ = k
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(0, sc, KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if ext else 0) | (0 if down else KEYEVENTF_KEYUP), 0, MAGIC)
    return i


def win_warp_click(saved, target, b, down, vscreen):
    """0.21.80: the SendInput batch of a warp-click's press (saved -> target, press) or release (release at target): the
    restore move follows the release separately, once the cursor's current position is read (restore_point)."""
    return [win_move(target[0], target[1], vscreen), win_button(b, down)]


# ---- backends ---------------------------------------------------------------------------------------------------------
class MockBackend:
    """Records what would be injected (tests; KASTR_RC_MOCK=1 labs). `rects` maps a screen:// url to its rect.
    0.21.80: `mode` is what click_mode answers ("post" | "warp" | "mpx"); `routes` answers key_route; `cursor` is the sharer's
    own pointer (cursor_pos)."""
    name = "mock"
    pointer_in_capture = False

    def __init__(self, rects=None, vscreen=(0, 0, 1920, 1080)):
        self.rects = dict(rects or {})
        self.vscreen = vscreen
        self.events = []
        self.clip = ""
        self.clip_n = 0
        self.focus = True
        self.post_keys = False
        self.on_top = True
        self.blocked_why = ""
        self.raised = []
        self.mode = "post"
        self.cursor = (0, 0)
        self.ptr_shown = None
        self.ctl = []

    def surface_rect(self, url):
        return self.rects.get(url)

    def control_start(self, url, name, color):
        self.ctl.append(("start", url, name, color))
        return {"pointer": True, "mpx": False}

    def control_end(self):
        self.ctl.append(("end",))

    def pointer(self, px, py, on):
        self.ptr_shown = (px, py) if on else None
        self.events.append(("pointer", px, py, bool(on)))

    def cursor_pos(self):
        return self.cursor

    def click_mode(self, url, px, py):
        return self.mode

    def button(self, b, down, px, py, mode="post"):
        self.events.append(("button", b, bool(down), px, py, mode))

    def drag(self, px, py, mode):
        self.events.append(("drag", px, py, mode))

    def wheel(self, notches, horizontal=False, px=None, py=None, mode="post"):
        self.events.append(("wheel", round(notches, 3), bool(horizontal), mode))

    def key_route(self, url):
        return "send" if self.focus else ("post" if self.post_keys else None)

    def key(self, code, down, route="send", mods=()):
        if code not in KEYS:
            return False
        self.events.append(("key", code, bool(down), route))
        return True

    def target_at(self, url, px, py):
        return self.on_top

    def raise_target(self, url):
        self.raised.append(url)

    def focus_is(self, url):
        return self.focus

    def blocked(self, url, px=None, py=None):
        return self.blocked_why

    def clip_get(self):
        return self.clip

    def clip_set(self, text):
        self.clip = text
        self.clip_n += 1
        self.events.append(("clip", len(text)))
        return True

    def clip_seq(self):
        return self.clip_n

    def flush(self):
        pass

    def monitor(self, on_local, on_hotkey):
        return None

    def ui(self):
        return None


class WinBackend:
    """PostMessage to classic controls, SendInput (scan codes; every event tagged MAGIC) for everything else, an overlay for
    the controller's own pointer. Elevated windows (UIPI) and the secure desktop cannot receive a normal process's input --
    blocked() says so instead of failing silently."""
    name = "windows"
    pointer_in_capture = False   # PointerOverlay is excluded from every capture (WDA_EXCLUDEFROMCAPTURE)

    def __init__(self):
        import kastr_screen_sources as ss
        ss.ensure_dpi_aware()
        self.ss = ss
        self.u32 = ctypes.WinDLL("user32", use_last_error=True)
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.adv = ctypes.WinDLL("advapi32", use_last_error=True)
        self.u32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
        self.u32.SendInput.restype = ctypes.c_uint
        self.u32.WindowFromPoint.restype = ctypes.c_void_p
        self.u32.GetAncestor.restype = ctypes.c_void_p
        self.u32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.u32.GetForegroundWindow.restype = ctypes.c_void_p
        self.u32.OpenInputDesktop.restype = ctypes.c_void_p
        self.u32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        self.u32.PostMessageW.restype = ctypes.c_int
        self.u32.ChildWindowFromPointEx.restype = ctypes.c_void_p
        self.u32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        self.k32.OpenProcess.restype = ctypes.c_void_p
        self._pend = []
        self._il = {}
        self._rects = {}
        self.warp = WarpState()
        self._overlay = None
        self._tgt = None             # (hwnd, cx, cy) of the last click_mode() that answered "post"
        self._held_post = {}         # browser button -> hwnd its press was posted to
        self._last_press = None      # (t, b, hwnd, x, y) for double-clicks
        self._mods = ()
        self._key_h = None           # the shared window's focused classic control (key_route "post")
        self._warp_held = set()      # browser buttons pressed through the warp

    def vscreen(self):
        g = self.u32.GetSystemMetrics
        return g(76), g(77), g(78), g(79)   # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN

    def surface_rect(self, url):
        now = time.monotonic()
        hit = self._rects.get(url)
        if hit and now - hit[0] < 0.3:
            return hit[1]
        r = None
        s = surface_of(url)
        try:
            if s and s[0] == "monitor":
                import kastr_screen
                src = kastr_screen._resolve("monitor", s[1]) or {}
                rc = src.get("rect") or {}
                r = {"x": rc.get("x", 0), "y": rc.get("y", 0), "w": rc.get("w", 0), "h": rc.get("h", 0)} if rc else None
            elif s and self.u32.IsWindow(s[1]) and not self.u32.IsIconic(s[1]):
                if s[0] == "tab":
                    import kastr_tabs
                    crop = kastr_tabs.content_crop(s[1]) or {"left": 0, "top": 0, "right": 0, "bottom": 0}
                    cl = kastr_tabs.client_bounds(s[1])
                    r = {"x": cl[0] + crop["left"], "y": cl[1] + crop["top"], "w": cl[2] - cl[0] - crop["left"] - crop["right"],
                         "h": cl[3] - cl[1] - crop["top"] - crop["bottom"]}
                else:   # gfxcapture's default (capture_border=0) captures a window's CLIENT area -- the picture maps onto that
                    import kastr_tabs
                    cl = kastr_tabs.client_bounds(s[1])
                    r = {"x": cl[0], "y": cl[1], "w": cl[2] - cl[0], "h": cl[3] - cl[1]}
        except Exception:
            r = None
        self._rects[url] = (now, r)
        return r

    # ---- the controller's own pointer
    def control_start(self, url, name, color):
        try:
            import kastr_overlay
            self._overlay = kastr_overlay.PointerOverlay(name, color)
            ok = self._overlay.start()
        except Exception:
            self._overlay, ok = None, False
        return {"pointer": bool(ok), "mpx": False}

    def control_end(self):
        ov, self._overlay = self._overlay, None
        if ov is not None:
            try:
                ov.stop()
            except Exception:
                pass
        self._held_post.clear()

    def pointer(self, px, py, on):
        if self._overlay is not None:
            self._overlay.move(px, py, on)

    def cursor_pos(self):
        class PT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        p = PT()
        return (p.x, p.y) if self.u32.GetCursorPos(ctypes.byref(p)) else None

    def _push(self, inp):
        if inp is not None:
            self._pend.append(inp)

    # ---- where a click lands: the child window under the point, its class, its DPI
    def _class(self, h):
        buf = ctypes.create_unicode_buffer(128)
        return buf.value if self.u32.GetClassNameW(ctypes.c_void_p(h), buf, 128) else ""

    def _child_at(self, top, px, py):
        """The deepest visible, enabled child of `top` under the screen point (ChildWindowFromPointEx, descending) and the
        point in that child's client coordinates -- even when another window covers `top` there."""
        class PT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        self.u32.ScreenToClient.argtypes = [ctypes.c_void_p, ctypes.POINTER(PT)]
        self.u32.ChildWindowFromPointEx.argtypes = [ctypes.c_void_p, PT, ctypes.c_uint]
        cur = top
        for _ in range(32):
            pt = PT(px, py)
            self.u32.ScreenToClient(ctypes.c_void_p(cur), ctypes.byref(pt))
            nxt = self.u32.ChildWindowFromPointEx(ctypes.c_void_p(cur), pt, 0x0001 | 0x0002 | 0x0004)   # SKIPINVISIBLE|SKIPDISABLED|SKIPTRANSPARENT
            if not nxt or int(nxt) == int(cur):
                return cur, pt.x, pt.y
            cur = nxt
        pt = PT(px, py)
        self.u32.ScreenToClient(ctypes.c_void_p(cur), ctypes.byref(pt))
        return cur, pt.x, pt.y

    def _dpi(self, h, px, py):
        aware, dw, dm = 2, 96, 96
        try:
            u = self.u32
            u.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
            u.GetWindowDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            u.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            aware = int(u.GetAwarenessFromDpiAwarenessContext(u.GetWindowDpiAwarenessContext(ctypes.c_void_p(h))))
            u.GetDpiForWindow.argtypes = [ctypes.c_void_p]
            dw = int(u.GetDpiForWindow(ctypes.c_void_p(h)) or 96)

            class PT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            u.MonitorFromPoint.restype = ctypes.c_void_p
            u.MonitorFromPoint.argtypes = [PT, ctypes.c_uint]
            hm = u.MonitorFromPoint(PT(px, py), 2)
            x, y = ctypes.c_uint(96), ctypes.c_uint(96)
            ctypes.WinDLL("shcore").GetDpiForMonitor(ctypes.c_void_p(hm), 0, ctypes.byref(x), ctypes.byref(y))
            dm = int(x.value or 96)
        except Exception:
            pass
        return aware, dw, dm

    def click_mode(self, url, px, py):
        """"post" (a classic control: messages to it, the cursor untouched) or "warp" -- click_plan decides."""
        self._tgt = None
        try:
            s = surface_of(url)
            if s and s[0] != "monitor":
                top = s[1]
            else:
                h = self._root_at(px, py)
                top = int(h or 0)
            if not top:
                return "warp"
            child, cx, cy = self._child_at(top, px, py)
            mode, _why = click_plan(self._class(child), self._class(top), *self._dpi(child, px, py))
            if mode == "post":
                self._tgt = (int(child), cx, cy)
            return mode
        except Exception:
            return "warp"

    def _post(self, h, msgs):
        ok = True
        for m, wp, lp in msgs:
            ok = bool(self.u32.PostMessageW(ctypes.c_void_p(h), m, wp, lp)) and ok   # lParam zero-extended (MAKELPARAM)
        return ok

    def button(self, b, down, px, py, mode="warp"):
        held = set(self._held_post)
        if mode == "post":
            if down:
                if not self._tgt:
                    return
                h, cx, cy = self._tgt
                now = time.monotonic()
                dbl = is_dblclick(self._last_press, now, b, h, cx, cy, self.u32.GetDoubleClickTime(),
                                  self.u32.GetSystemMetrics(36), self.u32.GetSystemMetrics(37))   # SM_CXDOUBLECLK / SM_CYDOUBLECLK
                self._last_press = None if dbl else (now, b, h, cx, cy)
                self._post(h, win_post_button(b, True, cx, cy, held, self._mods, dbl))
                self._held_post[b] = (h, cx, cy)
            else:
                hit = self._held_post.pop(b, None)
                if hit is None:
                    return
                h = hit[0]
                cx, cy = self._client(h, px, py) if px is not None else hit[1:]
                self._post(h, win_post_button(b, False, cx, cy, held, self._mods))
            return
        vs = self.vscreen()
        if down:   # the warp: the cursor goes to the controller's point for this press, back at its release
            if not self.warp.active:
                self.warp.begin(self.cursor_pos() or (px, py), (px, py))
            for i in win_warp_click(None, (px, py), b, True, vs):
                self._push(i)
            self.warp.moved((px, py))
            self._warp_held.add(b)
            self.flush()
        else:
            if px is not None:
                self._push(win_move(px, py, vs))
                self.warp.moved((px, py))
            self._push(win_button(b, False))
            self._warp_held.discard(b)
            self.flush()
            if not self._warp_held:
                self._warp_end()

    def _warp_end(self):
        """After a warp's last held button: the cursor back where the sharer had it (+ their own moves meanwhile), then the
        sharer's own clicks the hook held back during the warp (WarpState.physical), where they are."""
        if self.warp.active:
            rest = self.warp.end(self.cursor_pos(), self.vscreen())
            if rest:
                self._push(win_move(rest[0], rest[1], self.vscreen()))
        for kind, b in self.warp.take():
            self._push(win_button(b, kind == "down", extra=REPLAY_MAGIC))
        self.flush()

    def _client(self, h, px, py):
        class PT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = PT(int(px if px is not None else 0), int(py if py is not None else 0))
        self.u32.ScreenToClient.argtypes = [ctypes.c_void_p, ctypes.POINTER(PT)]
        self.u32.ScreenToClient(ctypes.c_void_p(h), ctypes.byref(pt))
        return pt.x, pt.y

    def drag(self, px, py, mode):
        if mode == "post":
            for b, hit in list(self._held_post.items()):
                cx, cy = self._client(hit[0], px, py)
                self._post(hit[0], [win_post_move(cx, cy, set(self._held_post), self._mods)])
                break
        elif self.warp.active:
            self._push(win_move(px, py, self.vscreen()))
            self.warp.moved((px, py))

    def release_button(self, b):
        self.button(b, False, None, None, "post" if b in self._held_post else "warp")

    def wheel(self, notches, horizontal=False, px=None, py=None, mode="warp"):
        if mode == "post" and self._tgt:
            h = self._tgt[0]
            self._post(h, [win_post_wheel(notches, horizontal, px, py, set(self._held_post), self._mods)])
            return
        vs = self.vscreen()
        own = not self.warp.active
        if own:
            self.warp.begin(self.cursor_pos() or (px, py), (px, py))
        self._push(win_move(px, py, vs))
        self._push(win_wheel(notches, horizontal))
        self.warp.moved((px, py))
        if own:   # move, wheel and back in one SendInput batch each way -- never a visible jump
            self.flush()
            self._warp_end()

    # ---- keys
    def key_route(self, url):
        """"send" (SendInput: the shared window is in front, or a screen is shared) | "post" (its focused control is a classic
        one: WM_CHAR / WM_KEYDOWN to it, nothing in front changes) | None (keys would land in another app)."""
        if self.focus_is(url):
            return "send"
        self._key_h = self._key_target(url)
        return "post" if self._key_h else None

    def _key_target(self, url):
        s = surface_of(url)
        if not s or s[0] == "monitor":
            return None

        class GTI(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint32), ("flags", ctypes.c_uint32), ("hwndActive", ctypes.c_void_p),
                        ("hwndFocus", ctypes.c_void_p), ("hwndCapture", ctypes.c_void_p), ("hwndMenuOwner", ctypes.c_void_p),
                        ("hwndMoveSize", ctypes.c_void_p), ("hwndCaret", ctypes.c_void_p), ("rcCaret", ctypes.c_long * 4)]
        tid = self.u32.GetWindowThreadProcessId(ctypes.c_void_p(s[1]), None)
        g = GTI(cbSize=ctypes.sizeof(GTI))
        if not tid or not self.u32.GetGUIThreadInfo(tid, ctypes.byref(g)) or not g.hwndFocus:
            return None
        h = int(g.hwndFocus)
        return h if win_post_friendly(self._class(h)) else None

    def key(self, code, down, route="send", mods=()):
        self._mods = tuple(mods or ())
        if route == "post":
            return self._post_key(code, down, mods)
        i = win_key(code, down)
        self._push(i)
        return i is not None

    def _post_key(self, code, down, mods):
        k = KEYS.get(code)
        if k is None or code in MODIFIERS:
            return code in MODIFIERS   # modifiers live in the controller's state (they shape the characters below)
        m = set(mods or ())
        if m & {"ctrl", "alt", "meta"}:
            return False               # shortcuts need the real keyboard state: only with the shared window in front
        h = self._key_h
        if not h:
            return False
        sc, ext, _ = k
        hkl = self.u32.GetKeyboardLayout(self.u32.GetWindowThreadProcessId(ctypes.c_void_p(h), None))
        vk = self.u32.MapVirtualKeyExW(sc | (0xE000 if ext else 0), 3, ctypes.c_void_p(hkl))   # MAPVK_VSC_TO_VK_EX
        ch = ""
        if down:
            st = (ctypes.c_ubyte * 256)()
            if "shift" in m:
                st[0x10] = st[0xA0] = 0x80
            if "altgr" in m:
                st[0x11] = st[0xA2] = st[0x12] = st[0xA5] = 0x80
            buf = ctypes.create_unicode_buffer(8)
            n = self.u32.ToUnicodeEx(vk, sc, st, buf, 8, 0x4, ctypes.c_void_p(hkl))   # 0x4: leave the keyboard state alone
            ch = buf.value[:n] if n > 0 else ""
        if ch and ch.isprintable():
            return self._post(h, [(WM_CHAR, ord(c), win_key_lparam(sc, ext, True)) for c in ch]) if down else True
        return self._post(h, [(WM_KEYDOWN if down else WM_KEYUP, vk, win_key_lparam(sc, ext, down))])

    def flush(self):
        if not self._pend:
            return 0
        arr = (INPUT * len(self._pend))(*self._pend)
        self._pend = []
        return self.u32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))

    def _root_at(self, px, py):
        class PT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        self.u32.WindowFromPoint.argtypes = [PT]
        h = self.u32.WindowFromPoint(PT(px, py))
        return self.u32.GetAncestor(h, 2) if h else None   # GA_ROOT

    def target_at(self, url, px, py):
        s = surface_of(url)
        if not s or s[0] == "monitor":
            return True
        return int(self._root_at(px, py) or 0) == s[1]

    def raise_target(self, url):
        s = surface_of(url)
        if not s or s[0] == "monitor":
            return
        h = s[1]
        if self.u32.GetForegroundWindow() == h:
            return
        if not self.u32.SetForegroundWindow(h):   # this process sent the last input -- usually allowed; else borrow the foreground's queue
            fg = self.u32.GetForegroundWindow()
            me = self.k32.GetCurrentThreadId()
            other = self.u32.GetWindowThreadProcessId(fg, None) if fg else 0
            if other and other != me and self.u32.AttachThreadInput(me, other, True):
                try:
                    self.u32.SetForegroundWindow(h)
                    self.u32.BringWindowToTop(h)
                finally:
                    self.u32.AttachThreadInput(me, other, False)

    def _pid_of(self, hwnd):
        pid = ctypes.c_uint32()
        self.u32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        return pid.value

    def focus_is(self, url):
        s = surface_of(url)
        if not s or s[0] == "monitor":
            return True
        fg = self.u32.GetForegroundWindow()
        if not fg:
            return False
        root = self.u32.GetAncestor(fg, 3) or fg   # GA_ROOTOWNER: a dialog of the shared app counts
        return int(root) == s[1] or int(fg) == s[1] or self._pid_of(fg) == self._pid_of(s[1])

    def _integrity(self, pid):
        """The process's mandatory integrity level (0x2000 medium, 0x3000 high = elevated), None when it cannot be read --
        a process we may not even query is treated as above us."""
        now = time.monotonic()
        hit = self._il.get(pid)
        if hit and now - hit[0] < 5:
            return hit[1]
        lvl = None
        hp = self.k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if hp:
            tok = ctypes.c_void_p()
            try:
                if self.adv.OpenProcessToken(ctypes.c_void_p(hp), 0x0008, ctypes.byref(tok)):   # TOKEN_QUERY
                    try:
                        buf = ctypes.create_string_buffer(64)
                        n = ctypes.c_uint32()
                        if self.adv.GetTokenInformation(tok, 25, buf, 64, ctypes.byref(n)):   # TokenIntegrityLevel
                            psid = ctypes.c_void_p.from_buffer(buf).value
                            self.adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
                            self.adv.GetSidSubAuthority.restype = ctypes.POINTER(ctypes.c_uint32)
                            cnt = self.adv.GetSidSubAuthorityCount(ctypes.c_void_p(psid)).contents.value
                            lvl = self.adv.GetSidSubAuthority(ctypes.c_void_p(psid), cnt - 1).contents.value
                    finally:
                        self.k32.CloseHandle(tok)
            finally:
                self.k32.CloseHandle(ctypes.c_void_p(hp))
        self._il[pid] = (now, lvl)
        return lvl

    def blocked(self, url, px=None, py=None):
        """"" | "secure" (UAC prompt, lock screen, Ctrl+Alt+Del: the input desktop is not ours) | "elevated" (the window that
        would get it runs as administrator -- Windows drops a normal process's input there)."""
        d = self.u32.OpenInputDesktop(0, False, 0x0001)   # DESKTOP_READOBJECTS
        if not d:
            return "secure"
        try:
            buf = ctypes.create_unicode_buffer(64)
            n = ctypes.c_uint32()
            if self.u32.GetUserObjectInformationW(ctypes.c_void_p(d), 2, buf, 128, ctypes.byref(n)) and buf.value.lower() != "default":
                return "secure"
        finally:
            self.u32.CloseDesktop(ctypes.c_void_p(d))
        h = self._root_at(px, py) if px is not None else self.u32.GetForegroundWindow()
        s = surface_of(url)
        if px is not None and s and s[0] != "monitor":
            h = s[1]   # 0.21.80: a posted click goes to the shared window even when another one covers the point
        if not h:
            return ""
        mine, theirs = self._integrity(os.getpid()), self._integrity(self._pid_of(h))
        if mine is not None and (theirs is None or theirs > mine):
            return "elevated"
        return ""

    def clip_seq(self):
        return int(self.u32.GetClipboardSequenceNumber())

    def _open_clip(self):
        for _ in range(10):
            if self.u32.OpenClipboard(None):
                return True
            time.sleep(0.02)
        return False

    def clip_get(self):
        self.u32.GetClipboardData.restype = ctypes.c_void_p
        self.k32.GlobalLock.restype = ctypes.c_void_p
        if not self._open_clip():
            return None
        try:
            h = self.u32.GetClipboardData(13)   # CF_UNICODETEXT
            if not h:
                return ""
            p = self.k32.GlobalLock(ctypes.c_void_p(h))
            try:
                return ctypes.wstring_at(p)[:CLIP_MAX + 1] if p else ""
            finally:
                self.k32.GlobalUnlock(ctypes.c_void_p(h))
        finally:
            self.u32.CloseClipboard()

    def clip_set(self, text):
        self.k32.GlobalAlloc.restype = ctypes.c_void_p
        self.k32.GlobalLock.restype = ctypes.c_void_p
        data = (str(text) + "\0").encode("utf-16-le")
        if not self._open_clip():
            return False
        try:
            self.u32.EmptyClipboard()
            h = self.k32.GlobalAlloc(0x0002, len(data))   # GMEM_MOVEABLE
            p = self.k32.GlobalLock(ctypes.c_void_p(h))
            ctypes.memmove(p, data, len(data))
            self.k32.GlobalUnlock(ctypes.c_void_p(h))
            return bool(self.u32.SetClipboardData(13, ctypes.c_void_p(h)))
        finally:
            self.u32.CloseClipboard()

    def monitor(self, on_local, on_hotkey):
        m = WinHooks(on_local, on_hotkey, warp=self.warp)
        return m if m.start() else None

    def ui(self):
        return WinUI()


class WinHooks:
    """WH_MOUSE_LL + WH_KEYBOARD_LL on their own thread, only while a grant is live. They record only WHEN the person at
    this computer presses or releases a mouse button (never what was typed), swallow a physical Ctrl+Alt+Space (it ends
    control) and -- 0.21.80 -- a physical button press during a warp-click (WarpState.physical: replayed after the warp)."""

    def __init__(self, on_local, on_hotkey, warp=None):
        self.on_local, self.on_hotkey = on_local, on_hotkey
        self.warp = warp
        self.tid = 0
        self.hot = HotkeyState()
        self.ok = threading.Event()
        self.err = None

    def start(self):
        threading.Thread(target=self._run, name="kastr-rc-hooks", daemon=True).start()
        self.ok.wait(3.0)
        return self.err is None and self.tid != 0

    def stop(self):
        if self.tid:
            ctypes.windll.user32.PostThreadMessageW(self.tid, 0x0012, 0, 0)   # WM_QUIT
            self.tid = 0

    def _run(self):
        from ctypes import wintypes as wt
        u32, k32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        LRESULT = ctypes.c_ssize_t
        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

        class MSLL(ctypes.Structure):
            _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD), ("time", wt.DWORD), ("extra", ctypes.c_size_t)]

        class KBDLL(ctypes.Structure):
            _fields_ = [("vk", wt.DWORD), ("scan", wt.DWORD), ("flags", wt.DWORD), ("time", wt.DWORD), ("extra", ctypes.c_size_t)]

        u32.CallNextHookEx.restype = LRESULT
        u32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
        u32.SetWindowsHookExW.restype = ctypes.c_void_p
        u32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wt.DWORD]
        k32.GetModuleHandleW.restype = ctypes.c_void_p

        def mouse(n, wp, lp):
            if n == 0:
                m = ctypes.cast(lp, ctypes.POINTER(MSLL)).contents
                if ll_mouse_physical(m.flags, m.extra):
                    hit = ll_button(wp, m.mouseData)
                    if hit:
                        swallow = self.warp is not None and self.warp.physical(*hit)   # recorded BEFORE the report runs
                        threading.Thread(target=self.on_local, args=hit, daemon=True).start()
                        if swallow:
                            return 1   # held back: replayed where the sharer is once the warp ends
            return u32.CallNextHookEx(None, n, wp, lp)

        def kbd(n, wp, lp):
            if n == 0:
                k = ctypes.cast(lp, ctypes.POINTER(KBDLL)).contents
                if ll_key_physical(k.flags, k.extra):
                    if self.hot.feed(k.vk, wp in (0x100, 0x104)):   # WM_KEYDOWN / WM_SYSKEYDOWN
                        threading.Thread(target=self.on_hotkey, daemon=True).start()
                        return 1   # swallowed: the hotkey is KASTR's
            return u32.CallNextHookEx(None, n, wp, lp)

        self._procs = (HOOKPROC(mouse), HOOKPROC(kbd))   # kept alive as long as the hooks
        hm = u32.SetWindowsHookExW(14, self._procs[0], k32.GetModuleHandleW(None), 0)   # WH_MOUSE_LL
        hk = u32.SetWindowsHookExW(13, self._procs[1], k32.GetModuleHandleW(None), 0)   # WH_KEYBOARD_LL
        if not hm or not hk:
            self.err = "SetWindowsHookEx failed (%d)" % ctypes.get_last_error()
            self.ok.set()
            return
        self.tid = k32.GetCurrentThreadId()
        self.ok.set()
        msg = wt.MSG()
        try:
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u32.TranslateMessage(ctypes.byref(msg))
                u32.DispatchMessageW(ctypes.byref(msg))
        finally:
            u32.UnhookWindowsHookEx(ctypes.c_void_p(hm))
            u32.UnhookWindowsHookEx(ctypes.c_void_p(hk))


class WinUI:
    """The share's own red-border bar (kastr_overlay through kastr_screen) turns into the prompt or the control bar."""

    def show(self, feed, url, mode, label, buttons, on_button, rect_fn=None):
        import kastr_screen
        return kastr_screen.overlay_mode(int(feed), mode, label, buttons, on_button)

    def clear(self, feed):
        try:
            import kastr_screen
            kastr_screen.overlay_mode(int(feed), "share")
        except Exception:
            pass

    def rect(self, feed):
        try:
            import kastr_screen
            return kastr_screen.overlay_bar_rect(int(feed))
        except Exception:
            return None


class X11UI:
    def __init__(self):
        self.bars = {}

    def show(self, feed, url, mode, label, buttons, on_button, rect_fn=None):
        import kastr_x11
        b = self.bars.get(feed)
        if b is None:
            b = self.bars[feed] = kastr_x11.Bar(rect_fn, on_button)
            b.set(label, buttons, 0xB42318 if mode == "control" else 0x1F2329)
            b.start()
        else:
            b.on_button = on_button
            b.set(label, buttons, 0xB42318 if mode == "control" else 0x1F2329)
        return True

    def clear(self, feed):
        b = self.bars.pop(feed, None)
        if b:
            b.stop()

    def rect(self, feed):
        b = self.bars.get(feed)
        if b and b.geom:
            return {"x": b.geom[0], "y": b.geom[1], "w": b.geom[2], "h": b.H}
        return None


class X11Backend:
    """XTest on the session's X display (never Wayland: available() says "wayland" there). 0.21.80: a second XInput2 master
    pointer + keyboard for the controller when the server allows it (kastr_x11.Mpx; KASTR_RC_MPX=0 turns it off), else a
    warp-click; the controller's arrow + name tag is kastr_x11.PointerWin (X11 cannot keep it out of x11grab: it is IN the
    picture -- pointer_in_capture)."""
    name = "x11"
    pointer_in_capture = True

    def __init__(self, display=None):
        import kastr_x11
        self.x = kastr_x11
        self.inj = kastr_x11.Injector(display)
        self.display = display
        self._rects = {}
        self._clip_last = None
        self.mpx = None
        self.pw = None
        self.warp = WarpState()
        self._url = None

    def surface_rect(self, url):
        now = time.monotonic()
        hit = self._rects.get(url)
        if hit and now - hit[0] < 0.3:
            return hit[1]
        s = surface_of(url)
        r = None
        try:
            if s and s[0] == "monitor":
                m = next((m for m in self.x.list_monitors() if m["index"] == s[1]), None)
                r = dict(m["rect"]) if m else None
            elif s:
                rr = self.inj.d.rect(s[1])
                r = {"x": rr["x"], "y": rr["y"], "w": rr["w"], "h": rr["h"]} if rr and rr["viewable"] else None
        except Exception:
            r = None
        self._rects[url] = (now, r)
        return r

    def control_start(self, url, name, color):
        self._url = url
        if os.environ.get("KASTR_RC_MPX") != "0":
            try:
                m = self.x.Mpx("KASTR remote", self.display)
                self.mpx = m if m.ok else None
                if self.mpx is None:
                    m.close()
            except Exception:
                self.mpx = None
        if self.mpx is not None:
            s = surface_of(url)
            self.mpx.focus(s[1] if s and s[0] != "monitor" else None)
        try:
            s = surface_of(url)
            self.pw = self.x.PointerWin(name, clean_color(color), self.display, parent=s[1] if s and s[0] != "monitor" else None)
            self.pw.start()
        except Exception:
            self.pw = None
        return {"pointer": self.pw is not None, "mpx": self.mpx is not None}

    def control_end(self):
        pw, self.pw = self.pw, None
        if pw is not None:
            pw.stop()
        m, self.mpx = self.mpx, None
        if m is not None:
            m.close()

    def pointer(self, px, py, on):
        if self.pw is not None:
            self.pw.move(px, py, on)
        if on and self.mpx is not None:
            self.mpx.move(px, py)

    def cursor_pos(self):
        return self.inj.query_pointer()

    def click_mode(self, url, px, py):
        return "mpx" if self.mpx is not None else "warp"

    def button(self, b, down, px, py, mode="warp"):
        if mode == "mpx" and self.mpx is not None:
            if px is not None:
                self.mpx.move(px, py)
            self.mpx.button(BUTTONS[b][3], down)
            return
        if down:
            if not self.warp.active:
                self.warp.begin(self.cursor_pos() or (px, py), (px, py))
            self.inj.move(px, py)
            self.warp.moved((px, py))
            self.inj.button(BUTTONS[b][3], True)
        else:
            if px is not None:
                self.inj.move(px, py)
                self.warp.moved((px, py))
            self.inj.button(BUTTONS[b][3], False)
            self._warp_back()

    def _warp_back(self):
        if self.warp.active:
            self.inj.flush()
            w, h = self.inj.d.size()
            rest = self.warp.end(self.cursor_pos(), (0, 0, w, h))
            if rest:
                self.inj.move(*rest)
            self.warp.take()

    def drag(self, px, py, mode):
        if mode == "mpx" and self.mpx is not None:
            self.mpx.move(px, py)
        elif self.warp.active:
            self.inj.move(px, py)
            self.warp.moved((px, py))

    def release_button(self, b):
        if self.mpx is not None:
            self.mpx.button(BUTTONS[b][3], False)
        else:
            self.inj.button(BUTTONS[b][3], False)
            self._warp_back()

    def wheel(self, notches, horizontal=False, px=None, py=None, mode="warp"):
        n = int(round(abs(notches)))
        btn = (7 if notches > 0 else 6) if horizontal else (5 if notches > 0 else 4)
        if mode == "mpx" and self.mpx is not None:
            if px is not None:
                self.mpx.move(px, py)
            for _ in range(min(n, 20)):
                self.mpx.button(btn, True)
                self.mpx.button(btn, False)
            return
        own = not self.warp.active and px is not None
        if own:
            self.warp.begin(self.cursor_pos() or (px, py), (px, py))
            self.inj.move(px, py)
        for _ in range(min(n, 20)):
            self.inj.button(btn, True)
            self.inj.button(btn, False)
        if own:
            self._warp_back()

    def key_route(self, url):
        if self.mpx is not None:
            return "mpx"
        return "send" if self.focus_is(url) else None

    def key(self, code, down, route="send", mods=()):
        k = KEYS.get(code)
        if k is None:
            return False
        if route == "mpx" and self.mpx is not None:
            ok = self.mpx.key(k[2], down)
            if not ok and k[2] == "Alt_R":
                ok = self.mpx.key("ISO_Level3_Shift", down)
            return ok
        ok = self.inj.key(k[2], down)
        if not ok and k[2] == "Alt_R":
            ok = self.inj.key("ISO_Level3_Shift", down)
        return ok

    def target_at(self, url, px, py):
        s = surface_of(url)
        if not s or s[0] == "monitor":
            return True
        top = self.inj.top_at(px, py)
        return bool(top) and top == self.inj.top_level(s[1])

    def raise_target(self, url):
        s = surface_of(url)
        if s and s[0] != "monitor":
            self.inj.raise_window(s[1], focus=self.mpx is None)
            self.inj.flush()

    def focus_is(self, url):
        s = surface_of(url)
        if not s or s[0] == "monitor":
            return True
        d = self.inj.d
        foc, rev = ctypes.c_ulong(), ctypes.c_int()
        d.x.XGetInputFocus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)]
        d.x.XGetInputFocus(d.dpy, ctypes.byref(foc), ctypes.byref(rev))
        f = foc.value
        if f in (0, 1, d.root):   # None / PointerRoot / the root: keys follow the pointer -- is it over the window?
            return True
        return f == s[1] or d.top_level(f) == d.top_level(s[1])

    def blocked(self, url, px=None, py=None):
        return ""

    def flush(self):
        self.inj.flush()
        if self.mpx is not None:
            self.mpx.flush()

    def clip_seq(self):
        t = self.x.clip_get(CLIP_MAX)
        self._clip_last = t
        return hash(t) if t is not None else None

    def clip_get(self):
        return self._clip_last if self._clip_last is not None else self.x.clip_get(CLIP_MAX)

    def clip_set(self, text):
        return self.x.clip_set(text)

    def monitor(self, on_local, on_hotkey):
        m = self.x.RawMonitor(on_local, on_hotkey, self.display)
        return m if m.start() else None

    def ui(self):
        return X11UI()


def platform_caps():
    """-> (available, why, kind): what this computer can do. why: "" | "wayland" | "unsupported" | "no-display" | "no-xtest"."""
    if os.environ.get("KASTR_RC_MOCK") == "1":
        return True, "", "mock"
    if WINDOWS:
        return True, "", "windows"
    if LINUX:
        import kastr_x11
        ok, why = kastr_x11.available()
        return ok, ("" if ok else ("wayland" if why == "wayland" else why)), "x11"
    return False, "unsupported", sys.platform


def make_backend():
    if os.environ.get("KASTR_RC_MOCK") == "1":
        return MockBackend()
    if WINDOWS:
        return WinBackend()
    if LINUX:
        return X11Backend()
    raise OSError("remote control is not available on this computer")


# ---- the grant ---------------------------------------------------------------------------------------------------------
class RemoteControl:
    """One grant at a time on this computer (one extra pointer, one extra keyboard). share_info(feed id) -> {url, live,
    paused} | None. share_mode(feed id, on): the share's capture without the real cursor + a low-latency encode while
    control lasts (kastr_rtsp.Bridge.rc_mode) -- run on its own thread (it restarts the share)."""

    def __init__(self, backend=None, share_info=None, log=None, clock=time.monotonic, caps=None, ui=None, monitor=True,
                 share_mode=None):
        self.backend = backend
        self.share_info = share_info or (lambda fid: None)
        self.share_mode = share_mode
        self.log = log or (lambda m: None)
        self.clock = clock
        self._caps = caps
        self._ui = ui
        self.use_monitor = monitor
        self.lock = threading.RLock()
        self.grant = None
        self.last_end = None          # {rcid, why, at}
        self.last_local = -1e9
        self.held_keys = {}           # 0.21.80: code -> route ("send" | "post" | "mpx")
        self.held_buttons = {}        # 0.21.80: browser button -> mode ("post" | "warp" | "mpx")
        self.phys = {}                # 0.21.80: physical mouse buttons the sharer holds -> since (a warp waits for their release)
        self.wq = deque()             # 0.21.80: warp events waiting for that release: (at, fn)
        self.ptr = None               # 0.21.80: the controller's pointer (screen px) or None (off the picture)
        self._ptr_last = None
        self._ptr_at = 0.0
        self.prompts = {}             # rcid -> {feed, at, answer}
        self._mon = None
        self._watch = None
        self._clip_base = None
        self._clip_mine = None
        self._clip_out = None
        self._clip_n = 0
        self.ctl_info = {}
        self.stats = {"in": 0, "dropped": 0, "paused": 0, "outside": 0, "blocked": 0, "queued": 0, "post": 0, "warp": 0, "mpx": 0}

    # ---- capabilities
    def caps(self):
        ok, why, kind = self._caps if self._caps is not None else platform_caps()
        return {"ok": True, "available": bool(ok), "why": why, "platform": kind, "clipMax": CLIP_MAX, "hold": LOCAL_HOLD, "lease": LEASE_S,
                "pointers": True, "ws": True}   # 0.21.80: two pointers; the loopback WebSocket

    def _backend(self):
        if self.backend is None:
            self.backend = make_backend()
        return self.backend

    def ui(self):
        if self._ui is None:
            try:
                self._ui = self._backend().ui()
            except Exception:
                self._ui = None
        return self._ui

    # ---- the prompt (native, beside the page's own)
    def prompt(self, rcid, feed, name, label):
        if not RCID_RE.match(str(rcid or "")):
            return {"ok": False, "error": "bad request id"}, 400
        info = self.share_info(feed)
        if not info or not info.get("live"):
            return {"ok": False, "error": "that share is not on the air"}, 409
        with self.lock:
            self.prompts = {k: v for k, v in self.prompts.items() if self.clock() - v["at"] < PROMPT_S}
            self.prompts[rcid] = {"feed": int(feed), "at": self.clock(), "answer": None}
        text = "%s asks to control your %s" % (str(name or "Someone")[:40], str(label or "screen")[:60])
        ui = self.ui()
        if ui is not None and not (self.grant and self.grant["feed"] == int(feed)):
            try:
                ui.show(int(feed), info.get("url"), "prompt", text, [("deny", "Deny"), ("allow", "Allow")],
                        lambda key, r=rcid: self.answer(r, key), rect_fn=lambda u=info.get("url"): self._bar_rect(u))
            except Exception as e:
                self.log("rc: prompt bar: %s" % e)
        return {"ok": True}, 200

    def answer(self, rcid, key):
        with self.lock:
            p = self.prompts.get(rcid)
            if p is None or p["answer"]:
                return
            p["answer"] = "allow" if key == "allow" else "deny"
            feed = p["feed"]
        self.log("rc: %s on the bar (%s)" % (p["answer"], rcid))
        if not (self.grant and self.grant["feed"] == feed):
            ui = self.ui()
            if ui is not None:
                ui.clear(feed)

    def prompt_end(self, rcid):
        with self.lock:
            p = self.prompts.pop(rcid, None)
        if p and not (self.grant and self.grant["feed"] == p["feed"]):
            ui = self.ui()
            if ui is not None:
                ui.clear(p["feed"])
        return {"ok": True}, 200

    # ---- grant lifecycle
    def start(self, rcid, controller, name, feed, share="", color=None):
        if not RCID_RE.match(str(rcid or "")) or not HOST_RE.match(str(controller or "")):
            return {"ok": False, "error": "bad grant"}, 400
        c = self.caps()
        if not c["available"]:
            return {"ok": False, "error": "remote control is not available here", "why": c["why"]}, 409
        info = self.share_info(feed)
        if not info or not info.get("live"):
            return {"ok": False, "error": "that share is not on the air", "why": "share"}, 409
        if info.get("paused"):
            return {"ok": False, "error": "that share is paused", "why": "paused"}, 409
        if surface_of(info.get("url")) is None:
            return {"ok": False, "error": "only a native screen, window or tab share can be controlled"}, 409
        with self.lock:
            g = self.grant
            if g and g["rcid"] != rcid:
                return {"ok": False, "error": "someone else is controlling this computer", "why": "busy"}, 409
            if g:
                return {"ok": True, "status": self.status(rcid)}, 200
            try:
                b = self._backend()
            except Exception as e:
                return {"ok": False, "error": "remote control could not start: %s" % e, "why": "unsupported"}, 409
            now = self.clock()
            self.grant = {"rcid": rcid, "controller": controller, "name": str(name or controller)[:40], "feed": int(feed),
                          "url": info["url"], "share": str(share or "")[:240], "at": now, "lease": now + LEASE_S, "blocked": "",
                          "color": clean_color(color)}
            self.prompts.pop(rcid, None)
            self.held_keys, self.held_buttons = {}, {}
            self.phys, self.wq = {}, deque()
            self.ptr, self._ptr_last = None, None
            self.last_local = -1e9
            self._clip_out, self._clip_mine = None, None
            try:
                self._clip_base = b.clip_seq()   # the clipboard as it was: only CHANGES made during control travel
            except Exception:
                self._clip_base = None
            try:
                self.ctl_info = b.control_start(info["url"], self.grant["name"], self.grant["color"]) or {}
            except Exception as e:
                self.ctl_info = {}
                self.log("rc: the controller's pointer: %s" % e)
        self.log("rc: %s may control %s (feed %s, %s; pointer %s, %s)" % (controller, info["url"], feed, rcid,
                 "own" if self.ctl_info.get("pointer") else "none", "second X pointer" if self.ctl_info.get("mpx") else b.name))
        if self.use_monitor:
            try:
                self._mon = b.monitor(self.local_input, self.hotkey)
            except Exception as e:
                self._mon = None
                self.log("rc: no local-input monitor: %s" % e)
            if self._mon is None:
                self.log("rc: no physical-input monitor -- Ctrl+Alt+Space and the drag guard are unavailable here")
        self._mode(int(feed), True)
        self._bar()
        if self._watch is None or not self._watch.is_alive():
            self._watch = threading.Thread(target=self._watch_loop, name="kastr-rc-watch", daemon=True)
            self._watch.start()
        return {"ok": True, "status": self.status(rcid)}, 200

    def _mode(self, feed, on):
        if self.share_mode is None:
            return
        def run():
            try:
                self.share_mode(feed, on)
            except Exception as e:
                self.log("rc: share mode: %s" % e)
        threading.Thread(target=run, name="kastr-rc-mode", daemon=True).start()

    def _bar(self):
        g = self.grant
        ui = self.ui()
        if not g or ui is None:
            return
        text = "%s is controlling your %s — Stop control (Ctrl+Alt+Space)" % (g["name"], "window" if surface_of(g["url"])[0] != "monitor" else "screen")
        try:
            ui.show(g["feed"], g["url"], "control", text, [("stop", "Stop control")], self._bar_button,
                    rect_fn=lambda u=g["url"]: self._bar_rect(u))
        except Exception as e:
            self.log("rc: control bar: %s" % e)

    def _bar_rect(self, url):
        with self.lock:   # 0.21.80: the bar's thread shares the injector's X connection -- one thread on it at a time
            r = self._backend().surface_rect(url)
        return dict(r, screen=surface_of(url)[0] == "monitor") if r else None

    def _bar_button(self, key):
        if key in ("stop", "share-stop"):
            self.end(None, "bar")

    def renew(self, rcid):
        with self.lock:
            g = self.grant
            if g and g["rcid"] == rcid:
                g["lease"] = self.clock() + LEASE_S
                self._clip_poll()
        return self.status(rcid, ptr=True)

    def end(self, rcid=None, why="stopped"):
        with self.lock:
            g = self.grant
            if g is None or (rcid is not None and g["rcid"] != rcid):
                return False
            self._release_all()
            self.wq.clear()
            self.grant = None
            self.last_end = {"rcid": g["rcid"], "why": why, "at": self.clock(), "controller": g["controller"]}
            mon, self._mon = self._mon, None
            try:
                if self.backend is not None:
                    self.backend.control_end()
            except Exception:
                pass
            self.ptr = None
        if mon is not None:
            try:
                mon.stop()
            except Exception:
                pass
        ui = self.ui()
        if ui is not None:
            try:
                ui.clear(g["feed"])
            except Exception:
                pass
        self._mode(g["feed"], False)
        self.log("rc: control by %s ended (%s)" % (g["controller"], why))
        return True

    def share_gone(self, feed_id, why):
        g = self.grant
        if g and g["feed"] == int(feed_id):
            self.end(g["rcid"], why)

    def _watch_loop(self):
        while self.grant is not None:
            time.sleep(0.25)
            self.check()

    def check(self):
        """The lease and the share, now (the watch thread every 0.25 s). -> why the grant ended, or None."""
        with self.lock:
            g = self.grant
        if g is None:
            return None
        why = None
        if self.clock() > g["lease"]:
            why = "timeout"   # the sharer's page stopped renewing: it closed, or the controller went quiet
        else:
            try:
                info = self.share_info(g["feed"])
            except Exception:
                info = None
            if not info or not info.get("live"):
                why = "share"
            elif info.get("paused"):
                why = "paused"
            elif info.get("url") != g["url"]:
                why = "retarget"
        if why:
            self.end(g["rcid"], why)
        else:
            with self.lock:
                if self.wq:
                    self._drain()   # a warp that waited too long goes, or one whose drag ended runs
        return why

    # ---- the person at the keyboard (0.21.80: tracked, never a pause)
    def local_input(self, kind="input", button=None):
        """The monitor's report of PHYSICAL input on this computer: ("down" | "up", browser button) for mouse buttons (a
        warp-click waits while the sharer holds one), anything else just notes the time. Never pauses remote input."""
        now = self.clock()
        self.last_local = now
        if kind == "down" and button is not None:
            self.phys[int(button)] = now
            if any(m == "warp" for m in self.held_buttons.values()):
                threading.Thread(target=self._abort_warp_locked, daemon=True).start()
        elif kind == "up" and button is not None:
            self.phys.pop(int(button), None)
            if not self.phys and self.wq:
                threading.Thread(target=self._drain_locked, daemon=True).start()

    def hotkey(self):
        self.log("rc: Ctrl+Alt+Space on this computer")
        self.end(None, "hotkey")

    def paused(self):
        return False   # 0.21.80: both people use their own pointer and keyboard at once

    def phys_down(self):
        now = self.clock()
        for b, at in list(self.phys.items()):
            if now - at > PHYS_STALE_S:
                self.phys.pop(b, None)
        return bool(self.phys)

    def _drain_locked(self):
        with self.lock:
            self._drain()

    def _drain(self):
        """Run the warp events that waited for the sharer's release, in order; while the sharer still holds a button, only
        drop the ones that waited longer than WARP_WAIT_S."""
        b = self.backend
        ran = False
        while self.wq:
            at, fn = self.wq[0]
            if self.phys_down():
                if self.clock() - at > WARP_WAIT_S:
                    self.wq.popleft()
                    self.stats["dropped"] += 1
                    continue
                break
            self.wq.popleft()
            ran = True
            try:
                fn()
            except Exception as e:
                self.log("rc: queued: %s" % e)
        if ran:
            try:
                b.flush()
            except Exception:
                pass
        if not self.wq and self.grant is not None and self.grant.get("blocked") == "drag":
            self.grant["blocked"] = ""

    def _abort_warp_locked(self):
        """The sharer pressed a mouse button while the controller's press holds the warp (their drag in an app that needs the
        real cursor): the controller's warp buttons let go, the cursor goes back, the sharer's own press is replayed there
        (Windows' hook held it back). Local input wins a conflict."""
        with self.lock:
            b = self.backend
            for btn, mode in sorted(self.held_buttons.items()):
                if mode == "warp":
                    try:
                        b.button(btn, False, None, None, "warp")
                    except Exception:
                        pass
                    self.held_buttons.pop(btn, None)
            try:
                b.flush()
            except Exception:
                pass

    def _release_locked(self):
        with self.lock:
            self._release_all()

    def _release_all(self):
        b = self.backend
        if b is None or not (self.held_keys or self.held_buttons):
            return
        try:
            for code, route in sorted(self.held_keys.items()):
                b.key(code, False, route)
            for btn, mode in sorted(self.held_buttons.items()):
                b.button(btn, False, None, None, mode)
            b.flush()
        except Exception as e:
            self.log("rc: release: %s" % e)
        self.held_keys, self.held_buttons = {}, {}

    # ---- the pointers
    def _ptr_set(self, p):
        self.ptr = p
        try:
            self.backend.pointer(p[0], p[1], True) if p else self.backend.pointer(0, 0, False)
        except Exception:
            pass

    def ptr_sample(self, force=False):
        """0.21.80: both pointers on the shared surface -> {s: [u, v, on] the sharer's own, c: [u, v, on] the controller's,
        cap: the controller's arrow is in the picture (X11)} -- or None when nothing moved (force: the current one)."""
        g = self.grant
        b = self.backend
        if g is None or b is None:
            return None
        try:
            with self.lock:   # one X display connection is shared with the injector: never two threads on it at once
                rect = b.surface_rect(g["url"])
                cur = b.cursor_pos()
        except Exception:
            return None
        if not rect:
            return None
        s = to_norm(cur, rect) or [0, 0, 0]
        c = to_norm(self.ptr, rect) or [0, 0, 0]
        key = (tuple(s), tuple(c))
        if key == self._ptr_last and not force:
            return None
        self._ptr_last = key
        # cap: the controller's arrow is in the picture (X11 cannot leave it out); scap: the sharer's own cursor is (unless the
        # share runs its remote-control capture, which leaves the cursor out -- share_mode) -- a viewer then draws only the name
        return {"s": s, "c": c, "cap": 1 if getattr(b, "pointer_in_capture", False) else 0, "scap": 0 if self.share_mode else 1}

    # ---- clipboard
    def _clip_poll(self):
        b = self.backend
        if b is None or self.grant is None:
            return
        try:
            seq = b.clip_seq()
        except Exception:
            return
        if seq is None or seq == self._clip_base:
            return
        self._clip_base = seq
        try:
            text = b.clip_get()
        except Exception:
            text = None
        if not text or text == self._clip_mine:
            return
        ok, n = clip_ok(text)
        self._clip_n += 1
        self._clip_out = {"n": self._clip_n, "text": text} if ok else {"n": self._clip_n, "skipped": n}

    # ---- input
    def _mods(self):
        return tuple(sorted({MODIFIERS[c] for c in self.held_keys if c in MODIFIERS}))

    def inject(self, rcid, src, events):
        """The page hands over a batch from the controller's track. -> (status, code)."""
        with self.lock:
            g = self.grant
            if g is None or g["rcid"] != rcid:
                return dict(self.status(rcid), ok=False, error="no grant"), 403
            if src != g["controller"]:
                return dict(self.status(rcid), ok=False, error="not the controller this grant is for"), 403
            info = self.share_info(g["feed"])
            if not info or not info.get("live") or info.get("paused") or info.get("url") != g["url"]:
                why = "paused" if info and info.get("paused") else "share"
                self.end(rcid, why)
                return dict(self.status(rcid), ok=False, error="the share is not on the air"), 409
            g["lease"] = self.clock() + LEASE_S
            b = self.backend
            evs = events if isinstance(events, list) else []
            rect = None
            surf = surface_of(g["url"])[0]
            bar = None
            try:
                bar = self.ui().rect(g["feed"]) if self.ui() is not None else None
            except Exception:
                bar = None
            g["blocked"] = ""
            if self.wq:
                self._drain()
            for ev in evs[:EV_MAX]:
                if not isinstance(ev, dict):
                    continue
                t = ev.get("t")
                if t == "hb":
                    continue
                self.stats["in"] += 1
                if t == "clip":   # the controller's clipboard text, while a grant is live
                    text = str(ev.get("text") or "")
                    ok, n = clip_ok(text)
                    if ok and text:
                        try:
                            b.clip_set(text)
                            self._clip_mine = text
                            self._clip_base = b.clip_seq()
                        except Exception:
                            pass
                    continue
                if rect is None:
                    rect = b.surface_rect(g["url"])
                    if rect is None:
                        g["blocked"] = "hidden"
                        self.stats["dropped"] += 1
                        break
                if t == "m":
                    if ev.get("o"):   # 0.21.80: the controller's mouse left the picture -- their pointer goes
                        self._ptr_set(None)
                        continue
                    p = norm_point(ev.get("x"), ev.get("y"), rect, True)
                    if not p:
                        continue
                    self._ptr_set(p)
                    if self.held_buttons:   # a drag: the held buttons' window follows (posted moves, or the warped cursor)
                        modes = set(self.held_buttons.values())
                        mode = "warp" if "warp" in modes else ("mpx" if "mpx" in modes else "post")
                        if self.wq:
                            self.wq.append((self.clock(), lambda p=p, m=mode: b.drag(p[0], p[1], m)))
                        else:
                            b.drag(p[0], p[1], mode)
                elif t in ("d", "u", "w"):
                    p = norm_point(ev.get("x"), ev.get("y"), rect, t == "u")   # a release always lets go (clamped to the edge)
                    btn = ev.get("b") if t != "w" else 0
                    if p is None or (t != "w" and btn not in BUTTONS):
                        self.stats["outside"] += 1
                        continue
                    if t == "u" and btn not in self.held_buttons and not self.wq:
                        continue   # a release of a press we never sent (it began outside)
                    if bar and in_rect(p[0], p[1], bar):
                        self.stats["outside"] += 1   # KASTR's own bar is not the controller's to click
                        continue
                    if t != "u":
                        self._ptr_set(p)
                    mode = self.held_buttons.get(btn) if t == "u" else b.click_mode(g["url"], *p)
                    if t == "u" and mode is None:   # its press is still waiting in the queue: so does the release
                        self.wq.append((self.clock(), lambda btn=btn, p=p: self._up(b, btn, p)))
                        continue
                    if t == "d" and surf != "monitor" and mode != "post" and not b.target_at(g["url"], *p):
                        b.raise_target(g["url"])   # Kenton: "bring it to the front when the controller clicks"
                        if not b.target_at(g["url"], *p):
                            self.stats["outside"] += 1
                            continue
                    why = b.blocked(g["url"], *p) if t != "u" else ""
                    if why:
                        g["blocked"] = why
                        self.stats["blocked"] += 1
                        continue
                    if t == "w":
                        try:
                            n = max(-20.0, min(20.0, float(ev.get("n") or 0)))
                            hn = max(-20.0, min(20.0, float(ev.get("h") or 0)))
                        except (TypeError, ValueError):
                            n = hn = 0.0
                        def wheel(n=n, hn=hn, p=p, mode=mode):
                            if n:
                                b.wheel(n, False, p[0], p[1], mode)
                            if hn:
                                b.wheel(hn, True, p[0], p[1], mode)
                        if mode == "warp" and (self.phys_down() or self.wq):
                            self.wq.append((self.clock(), wheel))
                            self.stats["queued"] += 1
                            g["blocked"] = "drag"
                        else:
                            wheel()
                        continue
                    if t == "d":
                        if mode == "warp" and (self.phys_down() or self.wq):   # never while the sharer drags: after their release
                            self.wq.append((self.clock(), lambda btn=btn, p=p, mode=mode: self._down(b, btn, p, mode)))
                            self.stats["queued"] += 1
                            g["blocked"] = "drag"
                            continue
                        self._down(b, btn, p, mode)
                    else:
                        if self.wq:
                            self.wq.append((self.clock(), lambda btn=btn, p=p: self._up(b, btn, p)))
                            continue
                        self._up(b, btn, p)
                elif t == "k":
                    code, down = str(ev.get("c") or ""), bool(ev.get("d"))
                    if code not in KEYS:
                        self.stats["dropped"] += 1
                        continue
                    if not down and code not in self.held_keys:
                        continue
                    if down:
                        route = b.key_route(g["url"])
                        if route is None:
                            g["blocked"] = "focus"   # keys would land in another app: click in the shared window first
                            self.stats["blocked"] += 1
                            continue
                        why = b.blocked(g["url"])
                        if why:
                            g["blocked"] = why
                            self.stats["blocked"] += 1
                            continue
                        if b.key(code, True, route, self._mods()):
                            self.held_keys[code] = route
                    else:
                        route = self.held_keys.pop(code)
                        b.key(code, False, route, self._mods())
                else:
                    self.stats["dropped"] += 1
            try:
                b.flush()
            except Exception as e:
                self.log("rc: inject: %s" % e)
        return self.status(rcid), 200

    def _down(self, b, btn, p, mode):
        b.button(btn, True, p[0], p[1], mode)
        self.held_buttons[btn] = mode
        self.stats[mode] = self.stats.get(mode, 0) + 1

    def _up(self, b, btn, p):
        mode = self.held_buttons.pop(btn, None)
        if mode is not None:
            b.button(btn, False, p[0], p[1], mode)

    def status(self, rcid=None, ptr=False):
        g = self.grant
        out = {"ok": True, "active": False, "paused": False, "pauseLeft": 0, "ended": "", "blocked": "", "answer": None}
        if rcid and rcid in self.prompts:
            out["answer"] = self.prompts[rcid]["answer"]
        if g and (rcid is None or g["rcid"] == rcid):
            out.update(active=True, rcid=g["rcid"], controller=g["controller"], feed=g["feed"], paused=False, pauseLeft=0,
                       blocked=g.get("blocked") or "", clip=self._clip_out, monitor=self._mon is not None,
                       queued=len(self.wq), pointer=bool(self.ctl_info.get("pointer")), mpx=bool(self.ctl_info.get("mpx")))
            if ptr:
                out["ptr"] = self.ptr_sample(force=True)
        elif self.last_end and (rcid is None or self.last_end["rcid"] == rcid):
            out.update(rcid=self.last_end["rcid"], ended=self.last_end["why"])
        return out


_RC = None
_RC_LOCK = threading.Lock()


def get(share_info=None, log=None, share_mode=None):
    global _RC
    with _RC_LOCK:
        if _RC is None:
            _RC = RemoteControl(share_info=share_info, log=log, share_mode=share_mode)
        else:
            if share_info is not None:
                _RC.share_info = share_info
            if share_mode is not None:
                _RC.share_mode = share_mode
        return _RC


def share_gone(feed_id, why):
    """kastr_rtsp's Bridge: a screen share stopped / paused / now shows something else."""
    rc = _RC
    if rc is not None:
        try:
            rc.share_gone(feed_id, why)
        except Exception:
            pass


def bridge_info(bridge):
    """share_info for kastr_serve's Bridge: {url, live, paused} of a native screen share, else None."""
    def info(fid):
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            return None
        feed = bridge.get(fid) if bridge else None
        if feed is None or not str(getattr(feed, "url", "")).lower().startswith("screen://"):
            return None
        pub = getattr(bridge, "_pubs", {}).get(fid)
        return {"url": feed.url, "live": pub is not None, "paused": bool(pub is not None and pub.paused),
                "broadcast": getattr(pub, "broadcast", "") if pub is not None else ""}
    return info


def bridge_mode(bridge):
    """0.21.80: share_mode for kastr_serve's Bridge (rc_mode: no cursor in the capture, low-latency encode), or None.
    OFF unless KASTR_RC_SHARE_MODE=1: switching it restarts the share's capture, and in the v02180 lab the controller's picture
    then froze for 14 s or more (the viewers' players take that long to pick the restarted broadcast up again) -- far worse
    than what it buys (no measurable latency gain with libx264; the real cursor stays in the picture, so viewers draw only the
    sharer's NAME next to it -- ptr_sample's scap)."""
    if os.environ.get("KASTR_RC_SHARE_MODE") != "1":
        return None
    fn = getattr(bridge, "rc_mode", None) if bridge else None
    return (lambda fid, on: fn(int(fid), bool(on))) if fn else None


def _guard(handler):
    """This computer's own KASTR pages only: loopback, a loopback Origin (when there is one), same-origin fetch metadata."""
    import kastr_relay
    origin = str(handler.headers.get("Origin") or "")
    site = str(handler.headers.get("Sec-Fetch-Site") or "")
    return kastr_relay.is_local(handler) and (not origin or re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", origin)) \
        and site in ("", "same-origin", "none")


def _dispatch(rc, p):
    """One request from the page (HTTP body or WebSocket message) -> (reply, code)."""
    p = p if isinstance(p, dict) else {}
    op, rcid = str(p.get("op") or ""), str(p.get("rcid") or "")
    if op == "input":
        return rc.inject(rcid, str(p.get("src") or ""), p.get("ev"))
    if op == "renew":
        return rc.renew(rcid), 200
    if op == "prompt":
        return rc.prompt(rcid, p.get("feed"), p.get("name"), p.get("label"))
    if op == "prompt-end":
        return rc.prompt_end(rcid)
    if op == "grant":
        return rc.start(rcid, str(p.get("controller") or ""), p.get("name"), p.get("feed"), p.get("share"), p.get("color"))
    if op == "end":
        rc.end(rcid or None, str(p.get("why") or "stopped")[:20])
        return rc.status(rcid or None), 200
    return {"ok": False, "error": "op is prompt | prompt-end | grant | renew | input | end"}, 400


def handle_api(handler, bridge, log=None):
    """GET /api/rc[?rcid=] -> caps + status; POST /api/rc {op: prompt|prompt-end|grant|renew|input|end, ...}. This computer's
    own KASTR pages only: loopback, same-origin, and a custom header a foreign page cannot send without a preflight."""
    from urllib.parse import parse_qs, urlparse

    def send(code, obj):
        body = json.dumps(obj).encode()
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    if not _guard(handler):
        return send(403, {"ok": False, "error": "only on the computer itself"})
    rc = get(bridge_info(bridge), log, bridge_mode(bridge))
    if handler.command == "GET":
        q = parse_qs(urlparse(handler.path).query)
        rcid = (q.get("rcid") or [""])[0] or None
        return send(200, dict(rc.status(rcid), caps=rc.caps()))
    if handler.headers.get("X-KASTR-RC") != "1":
        return send(403, {"ok": False, "error": "missing X-KASTR-RC"})
    try:
        n = int(handler.headers.get("Content-Length") or 0)
        p = json.loads(handler.rfile.read(min(n, 1 << 20)) or b"{}") if n else {}
    except Exception:
        return send(400, {"ok": False, "error": "body must be JSON"})
    out, code = _dispatch(rc, p)
    return send(code, out)


# ---- 0.21.80: the loopback WebSocket (/api/rc/ws) -------------------------------------------------------------------------
# One socket for the whole grant instead of an HTTP request per batch: the sharer's page sends {op: "input" | "renew" | "end",
# ...} and gets each answer back ({re: op, code, ...status}); THIS side pushes {ptr: {s, c, cap}} at most PTR_HZ times a second
# while either pointer moves (the page publishes them as ptr.json for every viewer). The same guard as /api/rc: loopback, a
# loopback Origin (a browser always sends one on a WebSocket -- a foreign page's is its own site and is refused).
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_MAX = 1 << 20


def ws_accept(key):
    return base64.b64encode(hashlib.sha1((str(key).strip() + WS_GUID).encode("ascii")).digest()).decode("ascii")


def ws_frame(payload, opcode=0x1):
    """One unmasked server -> client frame (FIN set)."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    n = len(payload)
    if n < 126:
        head = bytes([0x80 | opcode, n])
    elif n < 65536:
        head = bytes([0x80 | opcode, 126]) + n.to_bytes(2, "big")
    else:
        head = bytes([0x80 | opcode, 127]) + n.to_bytes(8, "big")
    return head + payload


def ws_parse(buf):
    """-> (frames [(fin, opcode, payload)], rest) from a byte buffer of client frames (masked, as browsers send them)."""
    out = []
    i = 0
    while True:
        if len(buf) - i < 2:
            break
        b0, b1 = buf[i], buf[i + 1]
        n = b1 & 0x7F
        j = i + 2
        if n == 126:
            if len(buf) - j < 2:
                break
            n = int.from_bytes(buf[j:j + 2], "big")
            j += 2
        elif n == 127:
            if len(buf) - j < 8:
                break
            n = int.from_bytes(buf[j:j + 8], "big")
            j += 8
        if n > WS_MAX:
            raise ValueError("frame too large")
        mask = None
        if b1 & 0x80:
            if len(buf) - j < 4:
                break
            mask = buf[j:j + 4]
            j += 4
        if len(buf) - j < n:
            break
        data = bytes(buf[j:j + n])
        if mask:
            data = bytes(c ^ mask[k & 3] for k, c in enumerate(data))
        out.append((bool(b0 & 0x80), b0 & 0x0F, data))
        i = j + n
    return out, buf[i:]


def handle_ws(handler, bridge, log=None):
    """GET /api/rc/ws (Upgrade: websocket): the sharer page's channel to its own KASTR for the length of a grant."""
    if not _guard(handler):
        handler.send_error(403)
        return
    key = str(handler.headers.get("Sec-WebSocket-Key") or "")
    if str(handler.headers.get("Upgrade") or "").lower() != "websocket" or not key:
        handler.send_error(400)
        return
    rc = get(bridge_info(bridge), log, bridge_mode(bridge))
    handler.close_connection = True
    sock = handler.connection
    sock.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n"
                  % ws_accept(key)).encode("ascii"))
    sock.settimeout(None)
    buf, msg = b"", b""
    last_ptr = 0.0
    try:
        while True:
            r, _, _ = select.select([sock], [], [], 1.0 / PTR_HZ)
            if r:
                data = sock.recv(65536)
                if not data:
                    break
                frames, buf = ws_parse(buf + data)
                for fin, op, payload in frames:
                    if op == 0x8:   # close
                        try:
                            sock.sendall(ws_frame(payload[:2], 0x8))
                        except OSError:
                            pass
                        return
                    if op == 0x9:   # ping
                        sock.sendall(ws_frame(payload, 0xA))
                        continue
                    if op in (0x1, 0x0):
                        msg += payload
                        if not fin:
                            continue
                        text, msg = msg, b""
                        try:
                            p = json.loads(text.decode("utf-8"))
                        except ValueError:
                            continue
                        out, code = _dispatch(rc, p)
                        rep = dict(out, re=str(p.get("op") or "")[:12], code=code)
                        if p.get("n") is not None:
                            rep["n"] = p.get("n")   # the page's own request number (its latency echo)
                        sock.sendall(ws_frame(json.dumps(rep)))
            now = time.monotonic()
            if rc.grant is not None and now - last_ptr >= 1.0 / PTR_HZ - 0.002:
                last_ptr = now
                s = rc.ptr_sample()
                if s:
                    sock.sendall(ws_frame(json.dumps({"ptr": s, "rcid": rc.grant["rcid"] if rc.grant else ""})))
    except (OSError, ValueError):
        pass
