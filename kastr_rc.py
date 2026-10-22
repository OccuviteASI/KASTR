"""Remote control on the SHARER's computer (0.21.79).

Kenton (2026-10-22): "I want to add the capability to request remote control when someone is sharing their desktop and a
prompt to allow that user to take control of your machine. Local input always overrides remote input."

What runs where:
  * the relay carries the notes (ask / allow / deny / stop) between the two pages and checks who may send them
    (kastr_relay.rc_send: publishers and admins of the share's room ask, the sharer answers, rate limits);
  * the controller's page publishes its input as a MoQ track under its OWN host path (<room>/<host>/~rc/<peer>) -- a member
    token puts only under its own host, so nobody can speak for the controller;
  * the sharer's page subscribes to exactly that path while a grant is live and hands the events to THIS module over the
    loopback API (/api/rc), which injects them -- or refuses: no grant, a wrong grant id or controller, the share no longer
    on air or paused, a point outside the shared screen / window, or the person at the keyboard used it in the last
    LOCAL_HOLD seconds (physical input is told from injected input by the OS: Windows low-level hooks' INJECTED flags,
    X11 XInput2 raw events' source device).

A grant lasts until it is stopped: the sharer's Stop control (the page, the native bar, Ctrl+Alt+Space), the share stopping
or pausing, either side leaving -- and a lease the sharer's page renews every second lapses after LEASE_S (the page closed,
the controller went quiet for that long). Every key and button the controller holds is released when control ends or the
local person takes over. Clipboard TEXT follows changes both ways while a grant is live (CLIP_MAX bytes), never outside one.

Backends: WinBackend (SendInput, ctypes), X11Backend (XTest, kastr_x11), MockBackend (records -- tests, and any lab on a
desktop nobody must touch: KASTR_RC_MOCK=1).
"""
import json
import math
import os
import re
import sys
import threading
import time

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")
LOCAL_HOLD = 3.0       # s: remote input waits this long after the last physical input on this computer
LEASE_S = 10.0         # s: a grant the page stops renewing ends (page closed, KASTR hung, the controller dropped)
PROMPT_S = 60.0        # s: an unanswered prompt goes away
CLIP_MAX = 65536       # bytes of clipboard text, either way
EV_MAX = 256           # events in one batch from the page
MAGIC = 0x4B525443     # dwExtraInfo of every event KASTR injects on Windows ("KRTC"): our own bars ignore such clicks
RCID_RE = re.compile(r"^[a-z0-9]{8,32}$")
HOST_RE = re.compile(r"^[a-z0-9-]{1,32}-[0-9a-f]{4}$")

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
    return not (int(flags) & 0x3) and int(extra or 0) != MAGIC


def ll_key_physical(flags, extra):
    """WH_KEYBOARD_LL: LLKHF_INJECTED (0x10) / LLKHF_LOWER_IL_INJECTED (0x02)."""
    return not (int(flags) & 0x12) and int(extra or 0) != MAGIC


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


def win_mouse(dx=0, dy=0, flags=0, data=0):
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(int(dx), int(dy), ctypes.c_uint32(int(data)).value, int(flags), 0, MAGIC)
    return i


def win_move(px, py, vscreen):
    dx, dy = win_absolute(px, py, vscreen)
    return win_mouse(dx, dy, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)


def win_button(b, down):
    d, u, x, _ = BUTTONS[b]
    return win_mouse(0, 0, d if down else u, x)


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


# ---- backends ---------------------------------------------------------------------------------------------------------
class MockBackend:
    """Records what would be injected (tests; KASTR_RC_MOCK=1 labs). `rects` maps a screen:// url to its rect."""
    name = "mock"

    def __init__(self, rects=None, vscreen=(0, 0, 1920, 1080)):
        self.rects = dict(rects or {})
        self.vscreen = vscreen
        self.events = []
        self.clip = ""
        self.clip_n = 0
        self.focus = True
        self.on_top = True
        self.blocked_why = ""
        self.raised = []

    def surface_rect(self, url):
        return self.rects.get(url)

    def move(self, px, py):
        self.events.append(("move", px, py))

    def button(self, b, down, px, py):
        self.events.append(("button", b, bool(down), px, py))

    def release_button(self, b):
        self.events.append(("button", b, False, None, None))

    def wheel(self, notches, horizontal=False):
        self.events.append(("wheel", round(notches, 3), bool(horizontal)))

    def key(self, code, down):
        if code not in KEYS:
            return False
        self.events.append(("key", code, bool(down)))
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
    """SendInput with scan codes; every event tagged MAGIC. Elevated windows (UIPI) and the secure desktop cannot receive
    a normal process's input -- blocked() says so instead of failing silently."""
    name = "windows"

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
        self.k32.OpenProcess.restype = ctypes.c_void_p
        self._pend = []
        self._il = {}
        self._rects = {}

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

    def _push(self, inp):
        if inp is not None:
            self._pend.append(inp)

    def move(self, px, py):
        self._push(win_move(px, py, self.vscreen()))

    def button(self, b, down, px, py):
        self._push(win_move(px, py, self.vscreen()))
        self._push(win_button(b, down))

    def release_button(self, b):
        self._push(win_button(b, False))

    def wheel(self, notches, horizontal=False):
        self._push(win_wheel(notches, horizontal))

    def key(self, code, down):
        i = win_key(code, down)
        self._push(i)
        return i is not None

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
        m = WinHooks(on_local, on_hotkey)
        return m if m.start() else None

    def ui(self):
        return WinUI()


class WinHooks:
    """WH_MOUSE_LL + WH_KEYBOARD_LL on their own thread, only while a grant is live. They record only WHEN the person at
    this computer last used it (never what was typed), and swallow a physical Ctrl+Alt+Space (it ends control)."""

    def __init__(self, on_local, on_hotkey):
        self.on_local, self.on_hotkey = on_local, on_hotkey
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
                    self.on_local("mouse")
            return u32.CallNextHookEx(None, n, wp, lp)

        def kbd(n, wp, lp):
            if n == 0:
                k = ctypes.cast(lp, ctypes.POINTER(KBDLL)).contents
                if ll_key_physical(k.flags, k.extra):
                    if self.hot.feed(k.vk, wp in (0x100, 0x104)):   # WM_KEYDOWN / WM_SYSKEYDOWN
                        threading.Thread(target=self.on_hotkey, daemon=True).start()
                        return 1   # swallowed: the hotkey is KASTR's
                    self.on_local("key")
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
    """XTest on the session's X display (never Wayland: available() says "wayland" there)."""
    name = "x11"

    def __init__(self, display=None):
        import kastr_x11
        self.x = kastr_x11
        self.inj = kastr_x11.Injector(display)
        self.display = display
        self._rects = {}
        self._clip_last = None

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

    def move(self, px, py):
        self.inj.move(px, py)

    def button(self, b, down, px, py):
        self.inj.move(px, py)
        self.inj.button(BUTTONS[b][3], down)

    def release_button(self, b):
        self.inj.button(BUTTONS[b][3], False)

    def wheel(self, notches, horizontal=False):
        n = int(round(abs(notches)))
        btn = (7 if notches > 0 else 6) if horizontal else (5 if notches > 0 else 4)
        for _ in range(min(n, 20)):
            self.inj.button(btn, True)
            self.inj.button(btn, False)

    def key(self, code, down):
        k = KEYS.get(code)
        if k is None:
            return False
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
            self.inj.raise_window(s[1])
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
    """One grant at a time on this computer (one mouse, one keyboard). share_info(feed id) -> {url, live, paused} | None."""

    def __init__(self, backend=None, share_info=None, log=None, clock=time.monotonic, caps=None, ui=None, monitor=True):
        self.backend = backend
        self.share_info = share_info or (lambda fid: None)
        self.log = log or (lambda m: None)
        self.clock = clock
        self._caps = caps
        self._ui = ui
        self.use_monitor = monitor
        self.lock = threading.RLock()
        self.grant = None
        self.last_end = None          # {rcid, why, at}
        self.last_local = -1e9
        self.held_keys = set()
        self.held_buttons = set()
        self.prompts = {}             # rcid -> {feed, at, answer}
        self._mon = None
        self._watch = None
        self._clip_base = None
        self._clip_mine = None
        self._clip_out = None
        self._clip_n = 0
        self.stats = {"in": 0, "dropped": 0, "paused": 0, "outside": 0, "blocked": 0}

    # ---- capabilities
    def caps(self):
        ok, why, kind = self._caps if self._caps is not None else platform_caps()
        return {"ok": True, "available": bool(ok), "why": why, "platform": kind, "clipMax": CLIP_MAX, "hold": LOCAL_HOLD, "lease": LEASE_S}

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
    def start(self, rcid, controller, name, feed, share=""):
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
                          "url": info["url"], "share": str(share or "")[:240], "at": now, "lease": now + LEASE_S, "blocked": ""}
            self.prompts.pop(rcid, None)
            self.held_keys, self.held_buttons = set(), set()
            self.last_local = -1e9
            self._clip_out, self._clip_mine = None, None
            try:
                self._clip_base = b.clip_seq()   # the clipboard as it was: only CHANGES made during control travel
            except Exception:
                self._clip_base = None
        self.log("rc: %s may control %s (feed %s, %s)" % (controller, info["url"], feed, rcid))
        if self.use_monitor:
            try:
                self._mon = b.monitor(self.local_input, self.hotkey)
            except Exception as e:
                self._mon = None
                self.log("rc: no local-input monitor: %s" % e)
            if self._mon is None:
                self.log("rc: WARNING -- physical input cannot be told apart here; remote input is not paused by local input")
        self._bar()
        if self._watch is None or not self._watch.is_alive():
            self._watch = threading.Thread(target=self._watch_loop, name="kastr-rc-watch", daemon=True)
            self._watch.start()
        return {"ok": True, "status": self.status(rcid)}, 200

    def _bar(self):
        g = self.grant
        ui = self.ui()
        if not g or ui is None:
            return
        text = "%s is controlling your %s \u2014 Stop control (Ctrl+Alt+Space)" % (g["name"], "window" if surface_of(g["url"])[0] != "monitor" else "screen")
        try:
            ui.show(g["feed"], g["url"], "control", text, [("stop", "Stop control")], self._bar_button,
                    rect_fn=lambda u=g["url"]: self._bar_rect(u))
        except Exception as e:
            self.log("rc: control bar: %s" % e)

    def _bar_rect(self, url):
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
        return self.status(rcid)

    def end(self, rcid=None, why="stopped"):
        with self.lock:
            g = self.grant
            if g is None or (rcid is not None and g["rcid"] != rcid):
                return False
            self._release_all()
            self.grant = None
            self.last_end = {"rcid": g["rcid"], "why": why, "at": self.clock(), "controller": g["controller"]}
            mon, self._mon = self._mon, None
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
        return why

    # ---- the person at the keyboard
    def local_input(self, kind="input"):
        self.last_local = self.clock()
        if self.held_keys or self.held_buttons:
            threading.Thread(target=self._release_locked, daemon=True).start()

    def hotkey(self):
        self.log("rc: Ctrl+Alt+Space on this computer")
        self.end(None, "hotkey")

    def paused(self):
        return self.clock() - self.last_local < LOCAL_HOLD

    def _release_locked(self):
        with self.lock:
            self._release_all()

    def _release_all(self):
        b = self.backend
        if b is None or not (self.held_keys or self.held_buttons):
            return
        try:
            for code in sorted(self.held_keys):
                b.key(code, False)
            for btn in sorted(self.held_buttons):
                b.release_button(btn)
            b.flush()
        except Exception as e:
            self.log("rc: release: %s" % e)
        self.held_keys, self.held_buttons = set(), set()

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
                if self.paused():
                    self.stats["paused"] += 1
                    continue
                if rect is None:
                    rect = b.surface_rect(g["url"])
                    if rect is None:
                        g["blocked"] = "hidden"
                        self.stats["dropped"] += 1
                        break
                if t == "m":
                    p = norm_point(ev.get("x"), ev.get("y"), rect, True)
                    if p:
                        b.move(*p)
                elif t in ("d", "u", "w"):
                    p = norm_point(ev.get("x"), ev.get("y"), rect, t == "u")   # a release always lets go (clamped to the edge)
                    btn = ev.get("b") if t != "w" else 0
                    if p is None or (t != "w" and btn not in BUTTONS):
                        self.stats["outside"] += 1
                        continue
                    if t == "u" and btn not in self.held_buttons:
                        continue   # a release of a press we never sent (it began while paused, or outside)
                    if bar and in_rect(p[0], p[1], bar):
                        self.stats["outside"] += 1   # KASTR's own bar is not the controller's to click
                        continue
                    if t == "d" and surf != "monitor" and not b.target_at(g["url"], *p):
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
                        b.move(*p)
                        try:
                            n = max(-20.0, min(20.0, float(ev.get("n") or 0)))
                            hn = max(-20.0, min(20.0, float(ev.get("h") or 0)))
                        except (TypeError, ValueError):
                            n = hn = 0.0
                        if n:
                            b.wheel(n, False)
                        if hn:
                            b.wheel(hn, True)
                    else:
                        b.button(btn, t == "d", *p)
                        if t == "d":
                            self.held_buttons.add(btn)
                        else:
                            self.held_buttons.discard(btn)
                elif t == "k":
                    code, down = str(ev.get("c") or ""), bool(ev.get("d"))
                    if code not in KEYS:
                        self.stats["dropped"] += 1
                        continue
                    if not down and code not in self.held_keys:
                        continue
                    if down and not b.focus_is(g["url"]):
                        g["blocked"] = "focus"   # keys would land in another app: click in the shared window first
                        self.stats["blocked"] += 1
                        continue
                    why = b.blocked(g["url"]) if down else ""
                    if why:
                        g["blocked"] = why
                        self.stats["blocked"] += 1
                        continue
                    if b.key(code, down):
                        if down:
                            self.held_keys.add(code)
                        else:
                            self.held_keys.discard(code)
                else:
                    self.stats["dropped"] += 1
            try:
                b.flush()
            except Exception as e:
                self.log("rc: inject: %s" % e)
        return self.status(rcid), 200

    def status(self, rcid=None):
        g = self.grant
        out = {"ok": True, "active": False, "paused": False, "pauseLeft": 0, "ended": "", "blocked": "", "answer": None}
        if rcid and rcid in self.prompts:
            out["answer"] = self.prompts[rcid]["answer"]
        if g and (rcid is None or g["rcid"] == rcid):
            left = max(0.0, LOCAL_HOLD - (self.clock() - self.last_local))
            out.update(active=True, rcid=g["rcid"], controller=g["controller"], feed=g["feed"], paused=left > 0,
                       pauseLeft=int(left * 1000), blocked=g.get("blocked") or "", clip=self._clip_out,
                       monitor=self._mon is not None)
        elif self.last_end and (rcid is None or self.last_end["rcid"] == rcid):
            out.update(rcid=self.last_end["rcid"], ended=self.last_end["why"])
        return out


_RC = None
_RC_LOCK = threading.Lock()


def get(share_info=None, log=None):
    global _RC
    with _RC_LOCK:
        if _RC is None:
            _RC = RemoteControl(share_info=share_info, log=log)
        elif share_info is not None:
            _RC.share_info = share_info
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


def handle_api(handler, bridge, log=None):
    """GET /api/rc[?rcid=] -> caps + status; POST /api/rc {op: prompt|prompt-end|grant|renew|input|end, ...}. This computer's
    own KASTR pages only: loopback, same-origin, and a custom header a foreign page cannot send without a preflight."""
    import kastr_relay
    from urllib.parse import parse_qs, urlparse

    def send(code, obj):
        body = json.dumps(obj).encode()
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    origin = str(handler.headers.get("Origin") or "")
    site = str(handler.headers.get("Sec-Fetch-Site") or "")
    if not kastr_relay.is_local(handler) or (origin and not re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", origin)) \
            or site not in ("", "same-origin", "none"):
        return send(403, {"ok": False, "error": "only on the computer itself"})
    rc = get(bridge_info(bridge), log)
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
    p = p if isinstance(p, dict) else {}
    op, rcid = str(p.get("op") or ""), str(p.get("rcid") or "")
    if op == "input":
        out, code = rc.inject(rcid, str(p.get("src") or ""), p.get("ev"))
        return send(code, out)
    if op == "renew":
        return send(200, rc.renew(rcid))
    if op == "prompt":
        out, code = rc.prompt(rcid, p.get("feed"), p.get("name"), p.get("label"))
        return send(code, out)
    if op == "prompt-end":
        out, code = rc.prompt_end(rcid)
        return send(code, out)
    if op == "grant":
        out, code = rc.start(rcid, str(p.get("controller") or ""), p.get("name"), p.get("feed"), p.get("share"))
        return send(code, out)
    if op == "end":
        rc.end(rcid or None, str(p.get("why") or "stopped")[:20])
        return send(200, rc.status(rcid or None))
    return send(400, {"ok": False, "error": "op is prompt | prompt-end | grant | renew | input | end"})
