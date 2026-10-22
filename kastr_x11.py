"""X11 for KASTR on Linux (0.21.79): screens and windows for native sharing, XTest input for remote control, XInput2 raw
events to tell the person at the keyboard from injected input, and a small always-on-top bar. ctypes only (libX11, libXtst,
libXi, libXrandr when present); importable anywhere -- every entry point answers "unavailable" off X11.

Kenton (2026-10-22): "Local input always overrides remote input." On X11 every injected event comes from the server's XTEST
slave devices; the physical keyboard and mouse are other slaves. raw_monitor() watches XI_Raw* events on the root window and
reports only the ones whose `sourceid` is not an XTEST device (and Ctrl+Alt+Space, from the physical keyboard only).

Wayland: X11 clients there run under XWayland and XTest reaches only XWayland windows, so a Wayland session is reported as
"wayland" and nothing is offered (session_kind()).
"""
import ctypes
import ctypes.util
import os
import select
import shutil
import subprocess
import sys
import threading
import time

LINUX = sys.platform.startswith("linux")
_lib = {}
_lock = threading.Lock()


def session_kind(env=None):
    """"x11" | "wayland" | "none" (no display at all) | "other" (not Linux)."""
    env = os.environ if env is None else env
    if not LINUX and env is os.environ:
        return "other"
    if str(env.get("XDG_SESSION_TYPE") or "").lower() == "wayland":
        return "wayland"
    if env.get("WAYLAND_DISPLAY") and str(env.get("XDG_SESSION_TYPE") or "").lower() != "x11":
        return "wayland"
    return "x11" if env.get("DISPLAY") else "none"


def _load(name):
    with _lock:
        if name in _lib:
            return _lib[name]
        lib = None
        for cand in (ctypes.util.find_library(name), "lib%s.so.6" % name, "lib%s.so" % name):
            if not cand:
                continue
            try:
                lib = ctypes.CDLL(cand)
                break
            except OSError:
                continue
        _lib[name] = lib
        return lib


c_ulong, c_long, c_int, c_uint, c_char_p, c_void_p = ctypes.c_ulong, ctypes.c_long, ctypes.c_int, ctypes.c_uint, ctypes.c_char_p, ctypes.c_void_p
Window = c_ulong
Atom = c_ulong


class XWindowAttributes(ctypes.Structure):
    _fields_ = [("x", c_int), ("y", c_int), ("width", c_int), ("height", c_int), ("border_width", c_int), ("depth", c_int),
                ("visual", c_void_p), ("root", Window), ("class_", c_int), ("bit_gravity", c_int), ("win_gravity", c_int),
                ("backing_store", c_int), ("backing_planes", c_ulong), ("backing_pixel", c_ulong), ("save_under", c_int),
                ("colormap", c_ulong), ("map_installed", c_int), ("map_state", c_int), ("all_event_masks", c_long),
                ("your_event_mask", c_long), ("do_not_propagate_mask", c_long), ("override_redirect", c_int), ("screen", c_void_p)]


class XSetWindowAttributes(ctypes.Structure):
    _fields_ = [("background_pixmap", c_ulong), ("background_pixel", c_ulong), ("border_pixmap", c_ulong),
                ("border_pixel", c_ulong), ("bit_gravity", c_int), ("win_gravity", c_int), ("backing_store", c_int),
                ("backing_planes", c_ulong), ("backing_pixel", c_ulong), ("save_under", c_int), ("event_mask", c_long),
                ("do_not_propagate_mask", c_long), ("override_redirect", c_int), ("colormap", c_ulong), ("cursor", c_ulong)]


class XButtonEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p), ("window", Window),
                ("root", Window), ("subwindow", Window), ("time", c_ulong), ("x", c_int), ("y", c_int), ("x_root", c_int),
                ("y_root", c_int), ("state", c_uint), ("button", c_uint), ("same_screen", c_int)]


class XGenericEventCookie(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p), ("extension", c_int),
                ("evtype", c_int), ("cookie", c_uint), ("data", c_void_p)]


class XIValuatorState(ctypes.Structure):
    _fields_ = [("mask_len", c_int), ("mask", ctypes.POINTER(ctypes.c_ubyte)), ("values", ctypes.POINTER(ctypes.c_double))]


class XIRawEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p), ("extension", c_int),
                ("evtype", c_int), ("time", c_ulong), ("deviceid", c_int), ("sourceid", c_int), ("detail", c_int),
                ("flags", c_int), ("valuators", XIValuatorState), ("raw_values", ctypes.POINTER(ctypes.c_double))]


class XIEventMask(ctypes.Structure):
    _fields_ = [("deviceid", c_int), ("mask_len", c_int), ("mask", ctypes.POINTER(ctypes.c_ubyte))]


class XIDeviceInfo(ctypes.Structure):
    _fields_ = [("deviceid", c_int), ("name", c_char_p), ("use", c_int), ("attachment", c_int), ("enabled", c_int),
                ("num_classes", c_int), ("classes", c_void_p)]


class XRRMonitorInfo(ctypes.Structure):
    _fields_ = [("name", Atom), ("primary", c_int), ("automatic", c_int), ("noutput", c_int), ("x", c_int), ("y", c_int),
                ("width", c_int), ("height", c_int), ("mwidth", c_int), ("mheight", c_int), ("outputs", c_void_p)]


XEvent = c_long * 24
GENERIC_EVENT, BUTTON_PRESS, EXPOSE = 35, 4, 12
XI_RAW_KEY_PRESS, XI_RAW_KEY_RELEASE, XI_RAW_BUTTON_PRESS, XI_RAW_BUTTON_RELEASE, XI_RAW_MOTION = 13, 14, 15, 16, 17
XI_ALL_MASTER_DEVICES = 1
_ERR_HANDLER = None


def _x11():
    """libX11 with its prototypes (once) and a NON-FATAL error handler -- a window that vanished between two calls must not
    end KASTR (Xlib's default handler exits the process on BadWindow)."""
    global _ERR_HANDLER
    x = _load("X11")
    if x is None or getattr(x, "_kastr_ready", False):
        return x
    x.XOpenDisplay.restype, x.XOpenDisplay.argtypes = c_void_p, [c_char_p]
    x.XCloseDisplay.argtypes = [c_void_p]
    x.XDefaultRootWindow.restype, x.XDefaultRootWindow.argtypes = Window, [c_void_p]
    x.XDefaultScreen.argtypes = [c_void_p]
    x.XDisplayWidth.argtypes = x.XDisplayHeight.argtypes = [c_void_p, c_int]
    x.XQueryTree.argtypes = [c_void_p, Window, ctypes.POINTER(Window), ctypes.POINTER(Window), ctypes.POINTER(ctypes.POINTER(Window)), ctypes.POINTER(c_uint)]
    x.XGetWindowAttributes.argtypes = [c_void_p, Window, ctypes.POINTER(XWindowAttributes)]
    x.XTranslateCoordinates.argtypes = [c_void_p, Window, Window, c_int, c_int, ctypes.POINTER(c_int), ctypes.POINTER(c_int), ctypes.POINTER(Window)]
    x.XFetchName.argtypes = [c_void_p, Window, ctypes.POINTER(c_char_p)]
    x.XFree.argtypes = [c_void_p]
    x.XInternAtom.restype, x.XInternAtom.argtypes = Atom, [c_void_p, c_char_p, c_int]
    x.XGetWindowProperty.argtypes = [c_void_p, Window, Atom, c_long, c_long, c_int, Atom, ctypes.POINTER(Atom), ctypes.POINTER(c_int),
                                     ctypes.POINTER(c_ulong), ctypes.POINTER(c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
    x.XRaiseWindow.argtypes = [c_void_p, Window]
    x.XSetInputFocus.argtypes = [c_void_p, Window, c_int, c_ulong]
    x.XFlush.argtypes = [c_void_p]
    x.XSync.argtypes = [c_void_p, c_int]
    x.XStringToKeysym.restype, x.XStringToKeysym.argtypes = c_ulong, [c_char_p]
    x.XKeysymToKeycode.restype, x.XKeysymToKeycode.argtypes = ctypes.c_ubyte, [c_void_p, c_ulong]
    x.XQueryExtension.argtypes = [c_void_p, c_char_p, ctypes.POINTER(c_int), ctypes.POINTER(c_int), ctypes.POINTER(c_int)]
    x.XConnectionNumber.argtypes = [c_void_p]
    x.XPending.argtypes = [c_void_p]
    x.XNextEvent.argtypes = [c_void_p, ctypes.POINTER(XEvent)]
    x.XGetEventData.argtypes = [c_void_p, ctypes.POINTER(XGenericEventCookie)]
    x.XFreeEventData.argtypes = [c_void_p, ctypes.POINTER(XGenericEventCookie)]
    x.XCreateWindow.restype = Window
    x.XCreateWindow.argtypes = [c_void_p, Window, c_int, c_int, c_uint, c_uint, c_uint, c_int, c_uint, c_void_p, c_ulong, ctypes.POINTER(XSetWindowAttributes)]
    x.XSelectInput.argtypes = [c_void_p, Window, c_long]
    x.XMapRaised.argtypes = x.XUnmapWindow.argtypes = x.XDestroyWindow.argtypes = [c_void_p, Window]
    x.XMoveResizeWindow.argtypes = [c_void_p, Window, c_int, c_int, c_uint, c_uint]
    x.XCreateGC.restype, x.XCreateGC.argtypes = c_void_p, [c_void_p, Window, c_ulong, c_void_p]
    x.XFreeGC.argtypes = [c_void_p, c_void_p]
    x.XSetForeground.argtypes = [c_void_p, c_void_p, c_ulong]
    x.XFillRectangle.argtypes = [c_void_p, Window, c_void_p, c_int, c_int, c_uint, c_uint]
    x.XDrawString.argtypes = [c_void_p, Window, c_void_p, c_int, c_int, c_char_p, c_int]
    x.XStoreName.argtypes = [c_void_p, Window, c_char_p]
    handler_t = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p)
    _ERR_HANDLER = handler_t(lambda d, e: 0)
    x.XSetErrorHandler.restype, x.XSetErrorHandler.argtypes = c_void_p, [handler_t]
    x.XSetErrorHandler(_ERR_HANDLER)
    x._kastr_ready = True
    return x


def _xtst():
    t = _load("Xtst")
    if t is None or getattr(t, "_kastr_ready", False):
        return t
    t.XTestQueryExtension.argtypes = [c_void_p] + [ctypes.POINTER(c_int)] * 4
    t.XTestFakeMotionEvent.argtypes = [c_void_p, c_int, c_int, c_int, c_ulong]
    t.XTestFakeButtonEvent.argtypes = [c_void_p, c_uint, c_int, c_ulong]
    t.XTestFakeKeyEvent.argtypes = [c_void_p, c_uint, c_int, c_ulong]
    t._kastr_ready = True
    return t


def _xi():
    i = _load("Xi")
    if i is None or getattr(i, "_kastr_ready", False):
        return i
    i.XIQueryVersion.argtypes = [c_void_p, ctypes.POINTER(c_int), ctypes.POINTER(c_int)]
    i.XISelectEvents.argtypes = [c_void_p, Window, ctypes.POINTER(XIEventMask), c_int]
    i.XIQueryDevice.restype, i.XIQueryDevice.argtypes = ctypes.POINTER(XIDeviceInfo), [c_void_p, c_int, ctypes.POINTER(c_int)]
    i.XIFreeDeviceInfo.argtypes = [ctypes.POINTER(XIDeviceInfo)]
    i._kastr_ready = True
    return i


class Display:
    """One connection (each thread that loops on events keeps its own)."""

    def __init__(self, name=None):
        self.x = _x11()
        if self.x is None:
            raise OSError("libX11 is not installed")
        nm = name if name is not None else os.environ.get("DISPLAY")
        self.name = nm
        self.dpy = self.x.XOpenDisplay(nm.encode() if nm else None)
        if not self.dpy:
            raise OSError("cannot open X display %s" % (nm or "(default)"))
        self.root = self.x.XDefaultRootWindow(self.dpy)
        self.screen = self.x.XDefaultScreen(self.dpy)
        self._atoms = {}

    def close(self):
        if self.dpy:
            try:
                self.x.XCloseDisplay(self.dpy)
            except Exception:
                pass
            self.dpy = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def size(self):
        return self.x.XDisplayWidth(self.dpy, self.screen), self.x.XDisplayHeight(self.dpy, self.screen)

    def atom(self, name):
        a = self._atoms.get(name)
        if a is None:
            a = self._atoms[name] = self.x.XInternAtom(self.dpy, name.encode(), 0)
        return a

    def prop(self, w, name, req=0, maxlen=65536):
        """-> (type atom, format, bytes) or None."""
        at, fmt, n, after = Atom(), c_int(), c_ulong(), c_ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        r = self.x.XGetWindowProperty(self.dpy, w, self.atom(name), 0, maxlen // 4, 0, req, ctypes.byref(at), ctypes.byref(fmt),
                                      ctypes.byref(n), ctypes.byref(after), ctypes.byref(data))
        if r != 0 or not data:
            return None
        try:
            unit = {8: 1, 16: ctypes.sizeof(ctypes.c_short), 32: ctypes.sizeof(c_long)}.get(fmt.value, 1)
            return at.value, fmt.value, ctypes.string_at(data, n.value * unit)
        finally:
            self.x.XFree(data)

    def windows_prop(self, w, name):
        p = self.prop(w, name)
        if not p or p[1] != 32:
            return []
        n = len(p[2]) // ctypes.sizeof(c_long)
        return list((c_ulong * n).from_buffer_copy(p[2]))

    def children(self, w):
        """Children of `w`, bottom to top (stacking order)."""
        root, parent, kids, n = Window(), Window(), ctypes.POINTER(Window)(), c_uint()
        if not self.x.XQueryTree(self.dpy, w, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(kids), ctypes.byref(n)):
            return [], 0
        try:
            return [kids[i] for i in range(n.value)], parent.value
        finally:
            if kids:
                self.x.XFree(kids)

    def parent(self, w):
        return self.children(w)[1]

    def attrs(self, w):
        a = XWindowAttributes()
        if not self.x.XGetWindowAttributes(self.dpy, w, ctypes.byref(a)):
            return None
        return a

    def rect(self, w):
        """The window's rectangle in root coordinates -> {x, y, w, h, viewable} or None (gone)."""
        a = self.attrs(w)
        if a is None:
            return None
        rx, ry, ch = c_int(), c_int(), Window()
        if not self.x.XTranslateCoordinates(self.dpy, w, self.root, 0, 0, ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(ch)):
            return None
        return {"x": rx.value, "y": ry.value, "w": a.width, "h": a.height, "viewable": a.map_state == 2}

    def title(self, w):
        p = self.prop(w, "_NET_WM_NAME", self.atom("UTF8_STRING"))
        if p and p[2]:
            return p[2].decode("utf-8", "replace")
        s = c_char_p()
        if self.x.XFetchName(self.dpy, w, ctypes.byref(s)) and s.value:
            try:
                return s.value.decode("utf-8", "replace")
            finally:
                self.x.XFree(s)
        return ""

    def pid(self, w):
        p = self.prop(w, "_NET_WM_PID")
        if p and p[1] == 32 and len(p[2]) >= ctypes.sizeof(c_long):
            return int(c_ulong.from_buffer_copy(p[2][:ctypes.sizeof(c_long)]).value)
        return 0

    def top_level(self, w):
        """The child of the root that holds `w` (a reparenting window manager's frame, or `w` itself)."""
        cur = w
        for _ in range(16):
            par = self.parent(cur)
            if not par or par == self.root:
                return cur
            cur = par
        return cur

    def top_at(self, x, y):
        """The topmost viewable child of the root under the root point (x, y), or 0."""
        kids, _ = self.children(self.root)
        for k in reversed(kids):
            r = self.rect(k)
            if r and r["viewable"] and r["x"] <= x < r["x"] + r["w"] and r["y"] <= y < r["y"] + r["h"]:
                return k
        return 0

    def flush(self):
        self.x.XFlush(self.dpy)


def available():
    """-> (ok, why): X11 with XTest here? why = "" | "wayland" | "no-display" | "no-x11" | "no-xtest" | "not-linux"."""
    if not LINUX:
        return False, "not-linux"
    kind = session_kind()
    if kind == "wayland":
        return False, "wayland"
    if kind != "x11":
        return False, "no-display"
    if _x11() is None:
        return False, "no-x11"
    t = _xtst()
    if t is None:
        return False, "no-xtest"
    try:
        with Display() as d:
            a, b, c, e = c_int(), c_int(), c_int(), c_int()
            if not t.XTestQueryExtension(d.dpy, ctypes.byref(a), ctypes.byref(b), ctypes.byref(c), ctypes.byref(e)):
                return False, "no-xtest"
    except OSError:
        return False, "no-display"
    return True, ""


# ---- screens and windows (the Share panel on Linux) ------------------------------------------------------------------
def list_monitors():
    """[{index (from 1), name, rect {x,y,w,h}, width, height, primary}] -- RandR monitors, else the whole screen."""
    out = []
    with Display() as d:
        rr = _load("Xrandr")
        mons = []
        if rr is not None:
            try:
                rr.XRRGetMonitors.restype = ctypes.POINTER(XRRMonitorInfo)
                rr.XRRGetMonitors.argtypes = [c_void_p, Window, c_int, ctypes.POINTER(c_int)]
                rr.XRRFreeMonitors.argtypes = [ctypes.POINTER(XRRMonitorInfo)]
                n = c_int()
                p = rr.XRRGetMonitors(d.dpy, d.root, 1, ctypes.byref(n))
                if p:
                    try:
                        mons = [(p[i].x, p[i].y, p[i].width, p[i].height, bool(p[i].primary)) for i in range(n.value)]
                    finally:
                        rr.XRRFreeMonitors(p)
            except Exception:
                mons = []
        if not mons:
            w, h = d.size()
            mons = [(0, 0, w, h, True)]
        mons.sort(key=lambda m: (not m[4], m[0], m[1]))
        for i, (x, y, w, h, pri) in enumerate(mons, 1):
            out.append({"index": i, "name": "Screen %d" % i, "rect": {"x": x, "y": y, "w": w, "h": h}, "width": w, "height": h,
                        "primary": pri or i == 1})
    return out


def _exe(pid):
    try:
        with open("/proc/%d/comm" % pid, encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, ValueError):
        return ""


def list_windows(exclude_pids=()):
    """Top-level application windows, topmost first: [{hwnd (the X window id), title, exe, pid, rect, minimized}]."""
    skip = set(int(p) for p in exclude_pids or ()) | {os.getpid()}
    out = []
    with Display() as d:
        wins = d.windows_prop(d.root, "_NET_CLIENT_LIST_STACKING") or d.windows_prop(d.root, "_NET_CLIENT_LIST")
        if not wins:   # no window manager (a bare X server): the root's named children
            kids, _ = d.children(d.root)
            wins = [k for k in kids if d.title(k)]
        for w in reversed(wins):
            title = d.title(w)
            if not title.strip() or title.startswith("KASTR control"):
                continue
            pid = d.pid(w)
            if pid and pid in skip:
                continue
            r = d.rect(w)
            if not r or r["w"] < 8 or r["h"] < 8:
                continue
            out.append({"id": "window:%d" % w, "kind": "window", "hwnd": int(w), "title": title, "exe": _exe(pid) if pid else "",
                        "pid": pid, "rect": {"x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]}, "minimized": not r["viewable"]})
    return out


def window_rect(xid):
    try:
        with Display() as d:
            r = d.rect(int(xid))
            return r if r and r["viewable"] else None
    except OSError:
        return None


def grab_jpeg(rect, width=320, ffmpeg="ffmpeg", display=None, timeout=4.0):
    """A still of a root rectangle as JPEG bytes (the Share panel's thumbnail), or None."""
    w, h = max(2, int(rect["w"]) // 2 * 2), max(2, int(rect["h"]) // 2 * 2)
    disp = display or os.environ.get("DISPLAY") or ":0"
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "x11grab", "-video_size", "%dx%d" % (w, h), "-draw_mouse", "0",
            "-i", "%s+%d,%d" % (disp, int(rect["x"]), int(rect["y"])), "-frames:v", "1", "-vf", "scale=%d:-2" % int(width),
            "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "6", "-"]
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout)
        return r.stdout if r.returncode == 0 and r.stdout[:2] == b"\xff\xd8" else None
    except (OSError, subprocess.TimeoutExpired):
        return None


# ---- injection (XTest) -----------------------------------------------------------------------------------------------
class Injector:
    """XTest on one display connection. Every call is a no-op when the display went away."""

    def __init__(self, name=None):
        self.d = Display(name)
        self.t = _xtst()
        if self.t is None:
            raise OSError("libXtst is not installed")
        self._codes = {}

    def keycode(self, keysym_name):
        k = self._codes.get(keysym_name)
        if k is None:
            ks = self.d.x.XStringToKeysym(keysym_name.encode())
            k = self._codes[keysym_name] = int(self.d.x.XKeysymToKeycode(self.d.dpy, ks)) if ks else 0
        return k

    def move(self, x, y):
        self.t.XTestFakeMotionEvent(self.d.dpy, -1, int(x), int(y), 0)

    def button(self, n, down):
        self.t.XTestFakeButtonEvent(self.d.dpy, int(n), 1 if down else 0, 0)

    def key(self, keysym_name, down):
        k = self.keycode(keysym_name)
        if not k:
            return False
        self.t.XTestFakeKeyEvent(self.d.dpy, k, 1 if down else 0, 0)
        return True

    def raise_window(self, xid):
        try:
            top = self.d.top_level(int(xid))
            self.d.x.XRaiseWindow(self.d.dpy, top)
            self.d.x.XSetInputFocus(self.d.dpy, int(xid), 2, 0)   # RevertToParent, CurrentTime
        except Exception:
            pass

    def top_at(self, x, y):
        return self.d.top_at(x, y)

    def top_level(self, xid):
        return self.d.top_level(int(xid))

    def flush(self):
        self.d.flush()

    def close(self):
        self.d.close()


# ---- the person at the keyboard (XInput2 raw events) -----------------------------------------------------------------
class RawMonitor:
    """Calls on_local(kind) for every PHYSICAL key / button / motion (not from an XTEST device) and on_hotkey() for a
    physical Ctrl+Alt+Space. Its own thread and display connection; stop() ends both."""

    HOT = ("Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R", "space")

    def __init__(self, on_local, on_hotkey=None, name=None):
        self.on_local, self.on_hotkey, self.name = on_local, on_hotkey, name
        self._stop = threading.Event()
        self._th = None
        self.err = None
        self.xtest_ids = set()
        self.ready = threading.Event()

    def start(self):
        self._th = threading.Thread(target=self._run, name="kastr-rc-x11-raw", daemon=True)
        self._th.start()
        self.ready.wait(3.0)
        return self.err is None

    def stop(self):
        self._stop.set()
        if self._th and self._th is not threading.current_thread():
            self._th.join(2.0)

    def _run(self):
        try:
            d = Display(self.name)
        except OSError as e:
            self.err = str(e)
            self.ready.set()
            return
        xi = _xi()
        try:
            if xi is None:
                raise OSError("libXi is not installed")
            op, ev, er = c_int(), c_int(), c_int()
            if not d.x.XQueryExtension(d.dpy, b"XInputExtension", ctypes.byref(op), ctypes.byref(ev), ctypes.byref(er)):
                raise OSError("no XInput extension")
            maj, mnr = c_int(2), c_int(0)
            if xi.XIQueryVersion(d.dpy, ctypes.byref(maj), ctypes.byref(mnr)) != 0:
                raise OSError("XInput 2 is not available")
            n = c_int()
            devs = xi.XIQueryDevice(d.dpy, 0, ctypes.byref(n))   # XIAllDevices
            try:
                for i in range(n.value):
                    nm = (devs[i].name or b"").decode("utf-8", "replace")
                    if "XTEST" in nm.upper():
                        self.xtest_ids.add(devs[i].deviceid)
            finally:
                xi.XIFreeDeviceInfo(devs)
            buf = (ctypes.c_ubyte * 4)()
            for e in (XI_RAW_KEY_PRESS, XI_RAW_KEY_RELEASE, XI_RAW_BUTTON_PRESS, XI_RAW_BUTTON_RELEASE, XI_RAW_MOTION):
                buf[e >> 3] |= 1 << (e & 7)
            m = XIEventMask(XI_ALL_MASTER_DEVICES, 4, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
            xi.XISelectEvents(d.dpy, d.root, ctypes.byref(m), 1)
            d.x.XSync(d.dpy, 0)
            codes = {}
            for k in self.HOT:
                ks = d.x.XStringToKeysym(k.encode())
                kc = int(d.x.XKeysymToKeycode(d.dpy, ks)) if ks else 0
                if kc:
                    codes[kc] = k
        except OSError as e:
            self.err = str(e)
            d.close()
            self.ready.set()
            return
        self.ready.set()
        down = set()
        fd = d.x.XConnectionNumber(d.dpy)
        xev = XEvent()
        try:
            while not self._stop.is_set():
                if not d.x.XPending(d.dpy):
                    select.select([fd], [], [], 0.2)
                    continue
                d.x.XNextEvent(d.dpy, ctypes.byref(xev))
                cookie = ctypes.cast(ctypes.byref(xev), ctypes.POINTER(XGenericEventCookie)).contents
                if cookie.type != GENERIC_EVENT or cookie.extension != op.value:
                    continue
                if not d.x.XGetEventData(d.dpy, ctypes.byref(cookie)):
                    continue
                try:
                    raw = ctypes.cast(cookie.data, ctypes.POINTER(XIRawEvent)).contents
                    src, kind, detail = raw.sourceid, cookie.evtype, raw.detail
                finally:
                    d.x.XFreeEventData(d.dpy, ctypes.byref(cookie))
                if src in self.xtest_ids:
                    continue   # injected (ours, or another XTest client): never the person at the keyboard
                if kind in (XI_RAW_KEY_PRESS, XI_RAW_KEY_RELEASE) and detail in codes:
                    k = codes[detail]
                    if kind == XI_RAW_KEY_PRESS:
                        down.add(k)
                    else:
                        down.discard(k)
                    if (kind == XI_RAW_KEY_PRESS and k == "space" and down & {"Control_L", "Control_R"}
                            and down & {"Alt_L", "Alt_R", "Meta_L", "Meta_R"} and self.on_hotkey):
                        try:
                            self.on_hotkey()
                        except Exception:
                            pass
                        continue
                try:
                    self.on_local({XI_RAW_MOTION: "move", XI_RAW_BUTTON_PRESS: "button", XI_RAW_BUTTON_RELEASE: "button"}.get(kind, "key"))
                except Exception:
                    pass
        finally:
            d.close()


# ---- the bar (always on top) -----------------------------------------------------------------------------------------
class Bar:
    """A small override-redirect window at the top centre of a root rectangle: a coloured strip, a label and buttons.
    set(label, buttons=[(key, text)], color) repaints it; on_button(key) runs on its thread. rect_fn() -> {x,y,w,h} of
    what it sits on (followed once a second)."""

    H = 30

    def __init__(self, rect_fn, on_button, name=None):
        self.rect_fn, self.on_button, self.name = rect_fn, on_button, name
        self.label, self.buttons, self.color = "", [], 0xB42318
        self._hits = []
        self._stop = threading.Event()
        self._dirty = threading.Event()
        self._th = None
        self.geom = None
        self.err = None

    def set(self, label, buttons, color=0xB42318):
        # the core "fixed" font is Latin-1: dashes and curly quotes go plain
        tr = {0x2014: " - ", 0x2013: "-", 0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2026: "..."}
        self.label, self.buttons, self.color = str(label).translate(tr), list(buttons), int(color)
        self._dirty.set()

    def start(self):
        self._th = threading.Thread(target=self._run, name="kastr-rc-x11-bar", daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()
        if self._th and self._th is not threading.current_thread():
            self._th.join(2.0)

    def _layout(self):
        cw = 7   # the server's "fixed" font is 6-7 px a character
        x = 12 + cw * len(self.label) + 16
        hits = []
        for key, text in self.buttons:
            w = cw * len(text) + 20
            hits.append((key, text, x, 4, w, self.H - 8))
            x += w + 8
        return x + 4, hits

    def _run(self):
        try:
            d = Display(self.name)
        except OSError as e:
            self.err = str(e)
            return
        x = d.x
        sa = XSetWindowAttributes()
        sa.override_redirect = 1
        sa.background_pixel = self.color
        sa.border_pixel = 0xFFFFFF
        sa.event_mask = (1 << 15) | (1 << 2)   # Exposure | ButtonPress
        CW = (1 << 1) | (1 << 3) | (1 << 9) | (1 << 11)   # BackPixel | BorderPixel | OverrideRedirect | EventMask
        win = x.XCreateWindow(d.dpy, d.root, 0, 0, 200, self.H, 1, 0, 1, None, CW, ctypes.byref(sa))   # CopyFromParent depth/visual, InputOutput
        x.XStoreName(d.dpy, win, b"KASTR control")
        gc = x.XCreateGC(d.dpy, win, 0, None)
        fd = x.XConnectionNumber(d.dpy)
        xev = XEvent()
        last_place = 0.0
        shown = False

        def paint():
            W, hits = self._layout()
            self._hits = hits
            x.XSetForeground(d.dpy, gc, self.color)
            x.XFillRectangle(d.dpy, win, gc, 0, 0, W, self.H)
            x.XSetForeground(d.dpy, gc, 0xFFFFFF)
            lb = self.label.encode("latin-1", "replace")
            x.XDrawString(d.dpy, win, gc, 12, 19, lb, len(lb))
            for key, text, bx, by, bw, bh in hits:
                x.XSetForeground(d.dpy, gc, 0xFFFFFF if key in ("stop", "allow") else 0x3A3F47)
                x.XFillRectangle(d.dpy, win, gc, bx, by, bw, bh)
                x.XSetForeground(d.dpy, gc, 0xB42318 if key in ("stop", "allow") else 0xFFFFFF)
                tb = text.encode("latin-1", "replace")
                x.XDrawString(d.dpy, win, gc, bx + 10, by + 15, tb, len(tb))
            x.XFlush(d.dpy)
            return W

        try:
            while not self._stop.is_set():
                now = time.time()
                if self._dirty.is_set() or now - last_place > 1.0:
                    self._dirty.clear()
                    last_place = now
                    r = None
                    try:
                        r = self.rect_fn()
                    except Exception:
                        r = None
                    if r:
                        W = self._layout()[0]
                        gx = int(r["x"] + max(0, (r["w"] - W) // 2))
                        # above a window when the screen has room there (X11 cannot keep it out of the capture, and over the
                        # window it would hide what is shared); inside the top edge of a screen share or a window at the top
                        gy = int(r["y"] - self.H - 4) if r["y"] - self.H - 4 >= 0 and not r.get("screen") else int(r["y"] + 6)
                        if self.geom != (gx, gy, W):
                            x.XMoveResizeWindow(d.dpy, win, gx, gy, W, self.H)
                            self.geom = (gx, gy, W)
                        x.XMapRaised(d.dpy, win)   # also re-raises it above anything mapped since
                        shown = True
                        paint()
                    elif shown:
                        x.XUnmapWindow(d.dpy, win)
                        shown = False
                        self.geom = None
                    x.XFlush(d.dpy)
                if not x.XPending(d.dpy):
                    select.select([fd], [], [], 0.1)
                    continue
                x.XNextEvent(d.dpy, ctypes.byref(xev))
                t = xev[0] & 0xFFFFFFFF
                if t == EXPOSE:
                    paint()
                elif t == BUTTON_PRESS:
                    be = ctypes.cast(ctypes.byref(xev), ctypes.POINTER(XButtonEvent)).contents
                    for key, _t, bx, by, bw, bh in self._hits:
                        if bx <= be.x < bx + bw and by <= be.y < by + bh:
                            threading.Thread(target=self._fire, args=(key,), daemon=True).start()
                            break
        finally:
            try:
                x.XFreeGC(d.dpy, gc)
                x.XDestroyWindow(d.dpy, win)
                x.XFlush(d.dpy)
            except Exception:
                pass
            d.close()

    def _fire(self, key):
        try:
            self.on_button(key)
        except Exception:
            pass


# ---- clipboard (xclip / xsel) ----------------------------------------------------------------------------------------
def clip_tool():
    for t in ("xclip", "xsel"):
        p = shutil.which(t)
        if p:
            return t, p
    return None, None


def clip_get(limit):
    t, p = clip_tool()
    if not t:
        return None
    args = [p, "-selection", "clipboard", "-o"] if t == "xclip" else [p, "--clipboard", "--output"]
    try:
        r = subprocess.run(args, capture_output=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return ""
    return r.stdout[:limit + 1].decode("utf-8", "replace")


def clip_set(text):
    t, p = clip_tool()
    if not t:
        return False
    args = [p, "-selection", "clipboard", "-i"] if t == "xclip" else [p, "--clipboard", "--input"]
    try:   # xclip stays behind to serve the selection -- detached, its own session
        pr = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        pr.stdin.write(text.encode("utf-8"))
        pr.stdin.close()
        return True
    except OSError:
        return False
