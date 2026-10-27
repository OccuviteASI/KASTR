"""Pointer mode on the SHARER's computer (0.21.83): other people's name-tagged pointers and click "sonar" ripples drawn on the
sharer's real screen -- and nothing else. Pointing NEVER injects input: this module has no way to press, move or type.

Kenton (2026-10-23): "On the remote control, I would like to make it so there is a view-only mode where the user is able to see
my mouse, as well as whoever else they allow to share, and lets them move their mouse around with their name and when they
click it makes a little sonar thing around the mouse click to show everyone where it was clicked. This will help with sharing
a screen and collaborating on a document, etc."

What runs where:
  * a viewer of a native screen / window share asks "Point on this screen" (a note through the relay, kinds pask / pallow /
    pdeny / pstop -- kastr_relay.rc_send; anyone in the room may ask, the sharer answers) -- or the sharer switches on "Let
    everyone point" for the share;
  * a pointing person's page publishes its pointer (normalised to the picture) + its recent clicks as pt.json on its OWN
    member broadcast (<room>/<host>/~member/<peer> -- a viewer token puts only there), ~30 a second while it moves;
  * the SHARER's page subscribes to each allowed pointing person (PT_MAX at most a share), hands their pointers and new clicks
    to THIS module over the loopback (/api/rc/ws {op: "pt-draw"}, POST /api/rc as the fallback) and AGGREGATES everything
    into ONE track for the viewers (pts.json on its ~rc broadcast): every viewer subscribes to the sharer only (V + N
    subscriptions instead of V x N), and every pointer and ripple carries the moment it appeared on the sharer's real screen
    (fleet time) -- viewers show it when their picture shows that moment, exactly like 0.21.80's pointers;
  * this module draws them: an arrow + name tag per pointing person (kastr_overlay.PointerOverlay on Windows -- layered,
    click-through, topmost, left out of every capture; kastr_x11.PointerWin on X11, which IS in the picture) and a SONAR per
    click (RIPPLE_RINGS expanding rings in the person's colour with their name, RIPPLE_S long: WinRipples / X11Ripples, the
    same window style); and it samples the SHARER's own pointer + clicks (PT_HZ) so viewers see the sharer's name beside their
    real cursor and a sonar where the sharer clicks (own=True, "Show my clicks").

A pointer mode lasts while the sharer's page renews it (pt-on every couple of seconds, PT_LEASE_S) and its share is on the air
and not paused. Full remote control (kastr_rc) stays a separate, stronger grant."""
import ctypes
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
PT_MAX = 12            # pointing people drawn on one share at most
PT_HZ = 30             # samples of the sharer's own pointer per second at most (only while it moves or clicks)
PT_LEASE_S = 10.0      # s: a pointer mode the sharer's page stops renewing ends (page closed, KASTR hung)
RIPPLE_S = 0.8         # s: one sonar, start to end
RIPPLE_RINGS = 3       # rings per sonar
RIPPLE_STAGGER_S = 0.16   # s between two rings' starts
RIPPLE_GROW_S = 0.48   # s: one ring grows from RIPPLE_R0 to RIPPLE_R (the last starts at 0.32 s and ends at RIPPLE_S)
RIPPLE_R0 = 4          # px (96 dpi): a ring's first radius
RIPPLE_R = 30          # px (96 dpi): a ring's last radius
RIPPLE_W = (3.0, 1.0)  # px (96 dpi): a ring's width, first -> last
RIPPLE_DOT_S = 0.3     # s: the dot at the click itself
RIPPLE_NAME_S = 0.7    # s: the name beside the sonar
RIPPLE_MAX = 24        # ripples alive at once (a click storm draws the newest)
WM_APP_RIPPLE = 0x8010 # WinRipples: new ripples are queued (posted to its own hidden host window only)
RIPPLE_TIMER = 7
ID_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,100}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# ---- pure geometry + timing (tested everywhere) ------------------------------------------------------------------------
def ripple_rings(t, scale=1.0):
    """-> [(radius px, width px)] of the rings alive t s after the click (outermost first); [] once RIPPLE_S is over.
    Ring i starts at i * RIPPLE_STAGGER_S and eases out from RIPPLE_R0 to RIPPLE_R over RIPPLE_GROW_S, thinning as it goes."""
    if t < 0 or t >= RIPPLE_S:
        return []
    out = []
    for i in range(RIPPLE_RINGS):
        f = (t - i * RIPPLE_STAGGER_S) / RIPPLE_GROW_S
        if 0 <= f < 1:
            e = 1 - (1 - f) ** 2
            r = (RIPPLE_R0 + (RIPPLE_R - RIPPLE_R0) * e) * scale
            w = (RIPPLE_W[0] + (RIPPLE_W[1] - RIPPLE_W[0]) * f) * scale
            out.append((int(round(r)), max(1, int(round(w)))))
    return out


def ripple_dot(t, scale=1.0):
    """-> the radius (px) of the dot at the click itself, 0 once it is gone."""
    if t < 0 or t >= RIPPLE_DOT_S:
        return 0
    return max(1, int(round((4 - 2 * t / RIPPLE_DOT_S) * scale)))


def ripple_layout(name, scale=1.0, char_w=7):
    """-> {w, h, cx, cy, tag (x, y, w, h)}: one sonar's window -- the rings round (cx, cy), the name tag centred ABOVE them (the
    person's pointer tag sits below right of the click: the two never cover each other)."""
    s = max(1.0, float(scale))
    pad = int(math.ceil((RIPPLE_W[0] + 2) * s))
    R = int(math.ceil(RIPPLE_R * s)) + pad
    name = str(name or "")[:28]
    tw, th = int(round((char_w * len(name) + 14) * s)) if name else 0, int(round(18 * s)) if name else 0
    gap = int(round(2 * s)) if name else 0
    half = max(R, tw // 2 + 1)
    cx, cy = half, R + th + gap
    return {"w": 2 * half + 1, "h": cy + R + 1, "cx": cx, "cy": cy, "tag": (cx - tw // 2, 0, tw, th), "scale": s}


def ring_spans(cx, cy, r, w):
    """[(y, x0, x1)] -- the pixel rows of an annulus of radius r and width w round (cx, cy), x1 exclusive (pixel centres
    between r - w/2 and r + w/2). w <= 0: a filled disc of radius r."""
    ro = r + w / 2.0 if w > 0 else float(r)
    ri = r - w / 2.0 if w > 0 else -1.0
    out = []
    for y in range(int(math.floor(cy - ro)), int(math.ceil(cy + ro)) + 1):
        dy = y + 0.5 - cy
        if abs(dy) >= ro:
            continue
        xo = math.sqrt(ro * ro - dy * dy)
        l, rr = int(math.floor(cx - xo + 0.5)), int(math.floor(cx + xo + 0.5))
        if ri > 0 and abs(dy) < ri:
            xi = math.sqrt(ri * ri - dy * dy)
            a, b = int(math.floor(cx - xi + 0.5)), int(math.floor(cx + xi + 0.5))
            if a > l:
                out.append((y, l, a))
            if rr > b:
                out.append((y, b, rr))
        elif rr > l:
            out.append((y, l, rr))
    return out


def ripple_frame(t, lay):
    """One frame of a sonar for a shaped window (X11): {outer: white edge spans (the window's shape), inner: colour spans,
    tag: (x, y, w, h) | None} -- or None once it is over."""
    rings = ripple_rings(t, lay["scale"])
    dot = ripple_dot(t, lay["scale"])
    if not rings and not dot:
        return None
    outer, inner = [], []
    for r, w in rings:
        outer += ring_spans(lay["cx"], lay["cy"], r, w + 2)
        inner += ring_spans(lay["cx"], lay["cy"], r, w)
    if dot:
        outer += ring_spans(lay["cx"], lay["cy"], dot + 1, 0)
        inner += ring_spans(lay["cx"], lay["cy"], dot, 0)
    tx, ty, tw, th = lay["tag"]
    return {"outer": outer, "inner": inner, "tag": (tx, ty, tw, th) if tw and t < RIPPLE_NAME_S else None}


def presses(before, now):
    """Mouse buttons pressed since the last sample (sorted): the sharer's own clicks."""
    return sorted(set(now) - set(before))


def to_px(u, v, rect):
    """(u, v) 0..1 on the shared surface -> a screen pixel, or None off it."""
    try:
        u, v = float(u), float(v)
    except (TypeError, ValueError):
        return None
    if not rect or not (0 <= u <= 1 and 0 <= v <= 1):
        return None
    return int(round(rect["x"] + u * max(0, rect["w"] - 1))), int(round(rect["y"] + v * max(0, rect["h"] - 1)))


def to_uv(p, rect):
    """A screen pixel -> [u, v, on] on the shared surface (on = 0 off it), or None."""
    if p is None or not rect or rect.get("w", 0) <= 0 or rect.get("h", 0) <= 0:
        return None
    u, v = (p[0] - rect["x"]) / float(rect["w"]), (p[1] - rect["y"]) / float(rect["h"])
    on = 1 if 0 <= u <= 1 and 0 <= v <= 1 else 0
    return [round(min(1.0, max(0.0, u)), 4), round(min(1.0, max(0.0, v)), 4), on]


def clean_name(n, default="Someone"):
    s = "".join(ch for ch in str(n or "") if ch.isprintable())[:28].strip()
    return s or default


def clean_color(c, default="#009fda"):
    c = str(c or "")
    return c.lower() if COLOR_RE.match(c) else default


def clean_pointers(lst):
    """The page's pointers -> [{id, n, c, x, y, on}] (PT_MAX at most, each id once)."""
    out, seen = [], set()
    for p in (lst if isinstance(lst, list) else [])[:PT_MAX * 2]:
        if not isinstance(p, dict) or not ID_RE.match(str(p.get("id") or "")) or p["id"] in seen:
            continue
        seen.add(p["id"])
        try:
            x, y = float(p.get("x")), float(p.get("y"))
        except (TypeError, ValueError):
            continue
        out.append({"id": str(p["id"]), "n": clean_name(p.get("n")), "c": clean_color(p.get("c")), "x": x, "y": y,
                    "on": bool(p.get("on")) and 0 <= x <= 1 and 0 <= y <= 1})
        if len(out) >= PT_MAX:
            break
    return out


def clean_ripples(lst):
    out = []
    for r in (lst if isinstance(lst, list) else [])[:RIPPLE_MAX]:
        if not isinstance(r, dict) or not ID_RE.match(str(r.get("id") or "")):
            continue
        try:
            x, y = float(r.get("x")), float(r.get("y"))
        except (TypeError, ValueError):
            continue
        if 0 <= x <= 1 and 0 <= y <= 1:
            out.append({"id": str(r["id"]), "n": clean_name(r.get("n")), "c": clean_color(r.get("c")), "x": x, "y": y})
    return out


# ---- what draws on the sharer's screen ---------------------------------------------------------------------------------
class MockBoard:
    """Records what would be drawn (tests; KASTR_RC_MOCK=1 labs)."""
    in_capture = False

    def __init__(self, url="", log=None):
        self.url = url
        self.events = []
        self.stopped = False

    def pointer(self, pid, name, color, px, py, on):
        self.events.append(("ptr", pid, name, color, px, py, bool(on)))

    def drop(self, pid):
        self.events.append(("drop", pid))

    def ripple(self, px, py, name, color):
        self.events.append(("ripple", px, py, name, color))

    def stop(self):
        self.stopped = True
        self.events.append(("stop",))


class WinRipples:
    """Sonar ripples on the sharer's real screen (Windows): one thread, one message loop, a colour-keyed window per ripple with
    the pointer window's styles (kastr_overlay.pointer_spec: layered, click-through, topmost, tool, no-activate -- and left out
    of every capture), repainted by a 16 ms timer, destroyed after RIPPLE_S. add() only queues and posts to its OWN hidden host
    window: the caller never waits on painting."""

    def __init__(self, exclude_from_capture=True):
        self.exclude_from_capture = exclude_from_capture
        self.affinity_ok = True
        self._q = deque(maxlen=RIPPLE_MAX)
        self._live = {}
        self._host = None
        self._thread = None
        self._ready = threading.Event()
        self._timer = False

    def start(self):
        import kastr_overlay as ko
        if not ko.AVAILABLE or ko.under_tests():   # 0.21.91: never a real window on the desktop from a test run
            return False
        self._thread = threading.Thread(target=self._run, name="kastr-point-ripples", daemon=True)
        self._thread.start()
        self._ready.wait(5.0)
        return self._host is not None

    def add(self, px, py, name, color):
        import kastr_overlay as ko
        self._q.append((int(px), int(py), clean_name(name, ""), ko.hex_colorref(color), time.monotonic()))
        h = self._host
        if h:
            ko.PostMessageW(h, WM_APP_RIPPLE, 0, 0)

    def stop(self, timeout=3.0):
        import kastr_overlay as ko
        h = self._host
        if h:
            ko.PostMessageW(h, ko.WM_APP_STOP, 0, 0)
        th = self._thread
        if th is not None and th is not threading.current_thread():
            th.join(timeout)

    def _run(self):
        import kastr_overlay as ko
        spec = ko.pointer_spec()
        h = None
        try:
            ko._thread_pmv2()
            if not ko._ensure_class():
                raise OSError("RegisterClassExW failed")
            h = ko.CreateWindowExW(spec["ex"], ko.CLASS_NAME, "KASTR pointer ripples", spec["style"], -32000, -32000, 1, 1,
                                   None, None, ko.GetModuleHandleW(None), None)
            if not h:
                raise OSError("CreateWindowExW failed")
            ko._INSTANCES[h] = (self, "host")
            self._host = h
        except Exception:
            ko.log.exception("pointer ripples: could not start")
            self._ready.set()
            return
        self._ready.set()
        msg = ko.wt.MSG()
        try:
            while True:
                r = ko.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0 or r == -1:
                    break
                ko.TranslateMessage(ctypes.byref(msg))
                ko.DispatchMessageW(ctypes.byref(msg))
        finally:
            for hh in list(self._live):
                self._drop(hh)
            hh, self._host = self._host, None
            if hh:
                ko.DestroyWindow(hh)
                ko._INSTANCES.pop(hh, None)

    def _make(self, item):
        import kastr_overlay as ko
        px, py, name, color, t0 = item
        if len(self._live) >= RIPPLE_MAX:
            self._drop(min(self._live, key=lambda k: self._live[k]["t0"]))
        hmon = ko.MonitorFromPoint(ko.wt.POINT(px, py), 2) if ko.MonitorFromPoint is not None else None   # MONITOR_DEFAULTTONEAREST
        lay = ripple_layout(name, ko._dpi_of(hmon) / 96.0)
        spec = ko.pointer_spec()
        h = ko.CreateWindowExW(spec["ex"], ko.CLASS_NAME, "KASTR pointer ripple", spec["style"], px - lay["cx"], py - lay["cy"],
                               lay["w"], lay["h"], None, None, ko.GetModuleHandleW(None), None)
        if not h:
            return
        ko.SetLayeredWindowAttributes(h, spec["key"], 0, spec["lwa"])
        if self.exclude_from_capture and ko.SetWindowDisplayAffinity is not None:
            if not ko.SetWindowDisplayAffinity(h, spec["affinity"]):
                self.affinity_ok = False
        s = lay["scale"]
        font = ko.CreateFontW(-max(9, round(12 * s)), 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 4, 0, "Segoe UI")   # ANTIALIASED, never ClearType (key fringes)
        self._live[h] = {"t0": t0, "lay": lay, "name": name, "color": color,
                         "gdi": [ko.CreateSolidBrush(spec["key"]), ko.CreateSolidBrush(color), font]}
        ko._INSTANCES[h] = (self, "ripple")
        ko.SetWindowPos(h, ko.HWND_TOPMOST, px - lay["cx"], py - lay["cy"], 0, 0,
                        ko.SWP_NOSIZE | ko.SWP_NOACTIVATE | ko.SWP_SHOWWINDOW | ko.SWP_NOOWNERZORDER)
        if not self._timer:
            ko.SetTimer(self._host, RIPPLE_TIMER, 16, None)
            self._timer = True

    def _drop(self, h):
        import kastr_overlay as ko
        st = self._live.pop(h, None)
        ko.DestroyWindow(h)
        ko._INSTANCES.pop(h, None)
        for o in (st or {}).get("gdi", []):
            ko.DeleteObject(o)

    def _tick(self):
        import kastr_overlay as ko
        now = time.monotonic()
        for h, st in list(self._live.items()):
            if now - st["t0"] >= RIPPLE_S:
                self._drop(h)
            else:
                ko.InvalidateRect(h, None, False)
        if not self._live and self._timer:
            ko.KillTimer(self._host, RIPPLE_TIMER)
            self._timer = False

    def _paint(self, hwnd):
        import kastr_overlay as ko
        st = self._live.get(hwnd)
        ps = ko.PAINTSTRUCT()
        hdc = ko.BeginPaint(hwnd, ctypes.byref(ps))
        try:
            if st is None:
                return
            lay, (key, fill, font) = st["lay"], st["gdi"]
            t = time.monotonic() - st["t0"]
            ko.FillRect(hdc, ctypes.byref(ko.wt.RECT(0, 0, lay["w"], lay["h"])), key)
            cx, cy = lay["cx"], lay["cy"]
            old_br = ko.SelectObject(hdc, ko.GetStockObject(5))   # NULL_BRUSH: rings, not discs
            for r, w in ripple_rings(t, lay["scale"]):
                for width, col in ((w + 2, 0xFFFFFF), (w, st["color"])):   # a white edge under the colour: seen on any background
                    pen = ko.CreatePen(0, width, col)
                    old = ko.SelectObject(hdc, pen)
                    ko.Ellipse(hdc, cx - r, cy - r, cx + r + 1, cy + r + 1)
                    ko.SelectObject(hdc, old)
                    ko.DeleteObject(pen)
            d = ripple_dot(t, lay["scale"])
            ko.SelectObject(hdc, ko.GetStockObject(ko.NULL_PEN))
            if d:
                ko.SelectObject(hdc, fill)
                ko.Ellipse(hdc, cx - d, cy - d, cx + d + 1, cy + d + 1)
            tx, ty, tw, th = lay["tag"]
            if tw and t < RIPPLE_NAME_S:
                ko.SelectObject(hdc, fill)
                ko.RoundRect(hdc, tx, ty, tx + tw + 1, ty + th + 1, th // 2, th // 2)
                ko.SetBkMode(hdc, ko.TRANSPARENT_BK)
                ko.SetTextColor(hdc, ko.ink_colorref(st["color"]))
                of = ko.SelectObject(hdc, font)
                ko.DrawTextW(hdc, st["name"], -1, ctypes.byref(ko.wt.RECT(tx, ty, tx + tw, ty + th)),
                             ko.DT_CENTER | ko.DT_VCENTER | ko.DT_SINGLELINE | ko.DT_NOPREFIX)
                ko.SelectObject(hdc, of)
            ko.SelectObject(hdc, old_br)
        finally:
            ko.EndPaint(hwnd, ctypes.byref(ps))

    def _handle(self, role, hwnd, msg, wp, lp):
        import kastr_overlay as ko
        if msg == ko.WM_NCHITTEST:
            return ko.HTTRANSPARENT
        if msg == ko.WM_MOUSEACTIVATE:
            return ko.MA_NOACTIVATE
        if msg == ko.WM_ERASEBKGND:
            return 1
        if msg == ko.WM_CLOSE:
            return 0
        if role == "ripple" and msg == ko.WM_PAINT:
            self._paint(hwnd)
            return 0
        if role == "host":
            if msg == WM_APP_RIPPLE:
                while self._q:
                    self._make(self._q.popleft())
                return 0
            if msg == ko.WM_TIMER:
                self._tick()
                return 0
            if msg == ko.WM_APP_STOP:
                ko.PostQuitMessage(0)
                return 0
        return None


class WinBoard:
    """Windows: a PointerOverlay per pointing person (their arrow + name, left out of the capture) + WinRipples."""
    in_capture = False

    def __init__(self, url="", log=None):
        self.url = url
        self.log = log or (lambda m: None)
        self.ptrs = {}
        self.rip = None

    def pointer(self, pid, name, color, px, py, on):
        import kastr_overlay as ko
        ov = self.ptrs.get(pid)
        if ov is None:
            if not on or len(self.ptrs) >= PT_MAX:
                return
            ov = ko.PointerOverlay(name, color)
            if not ov.start():
                return
            if not ov.affinity_ok:
                self.in_capture = True   # an older Windows draws it into the capture: viewers must not draw it twice
            self.ptrs[pid] = ov
        ov.move(px, py, on)

    def drop(self, pid):
        ov = self.ptrs.pop(pid, None)
        if ov is not None:
            ov.stop()

    def ripple(self, px, py, name, color):
        if self.rip is None:
            r = WinRipples()
            if not r.start():
                return
            self.rip = r
        self.rip.add(px, py, name, color)
        if not self.rip.affinity_ok:
            self.in_capture = True

    def stop(self):
        for pid in list(self.ptrs):
            self.drop(pid)
        r, self.rip = self.rip, None
        if r is not None:
            r.stop()


class X11Ripples:
    """Sonar ripples on an X11 desktop: override-redirect windows reshaped every frame to the rings (ripple_frame), with an
    EMPTY input shape (clicks fall through), one thread and one display connection. A window share's ripples are children of
    the shared window (x11grab -window_id captures them as drawn, like kastr_x11.PointerWin); X11 cannot keep them out of the
    picture -- viewers do not draw them again (cap)."""

    def __init__(self, display=None, parent=None):
        self.display = display
        self.parent = int(parent) if parent else 0
        self._q = deque(maxlen=RIPPLE_MAX)
        self._stop = threading.Event()
        self._r, self._w = os.pipe()
        self._th = None
        self.err = None
        self.drawn = 0

    def start(self):
        import kastr_overlay as ko
        if ko.under_tests():   # 0.21.91: never a real window on the desktop from a test run
            return False
        self._th = threading.Thread(target=self._run, name="kastr-point-x11-ripples", daemon=True)
        self._th.start()
        return True

    def add(self, px, py, name, color):
        try:
            rgb = int(clean_color(color).lstrip("#"), 16)
        except ValueError:
            rgb = 0x009FDA
        nm = clean_name(name, "").translate({0x2014: "-", 0x2013: "-", 0x2019: "'", 0x2018: "'"})
        self._q.append((int(px), int(py), nm, rgb, time.monotonic()))
        try:
            os.write(self._w, b"r")
        except OSError:
            pass

    def stop(self):
        self._stop.set()
        try:
            os.write(self._w, b"q")
        except OSError:
            pass
        if self._th and self._th is not threading.current_thread():
            self._th.join(2.0)
        for fd in (self._r, self._w):
            try:
                os.close(fd)
            except OSError:
                pass

    def _run(self):
        import kastr_x11 as kx
        from ctypes import c_int, c_void_p, POINTER
        try:
            d = kx.Display(self.display)
        except OSError as e:
            self.err = str(e)
            return
        x = d.x
        ext = kx._load("Xext")
        W = kx.Window
        x.XFillRectangles.argtypes = [c_void_p, W, c_void_p, POINTER(kx.XRectangle), c_int]
        x.XMoveWindow.argtypes = [c_void_p, W, c_int, c_int]
        if ext is not None:
            ext.XShapeCombineRectangles.argtypes = [c_void_p, W, c_int, c_int, c_int, POINTER(kx.XRectangle), c_int, c_int, c_int]
        parent = self.parent or d.root
        live = []   # [win, gc, t0, lay, rgb, label]

        def shape(win, rects, kind):
            if ext is None:
                return
            arr = (kx.XRectangle * max(1, len(rects)))(*rects) if rects else None
            ext.XShapeCombineRectangles(d.dpy, win, kind, 0, 0, arr, len(rects), 0, 0)   # kind 0 ShapeBounding / 2 ShapeInput, ShapeSet

        def make(item):
            px, py, name, rgb, t0 = item
            if len(live) >= RIPPLE_MAX:
                old = live.pop(0)
                x.XFreeGC(d.dpy, old[1])
                x.XDestroyWindow(d.dpy, old[0])
            lay = ripple_layout(name, 1.0)
            if parent != d.root:   # root coordinates -> the shared window's
                cx, cy, ch = c_int(), c_int(), W()
                if x.XTranslateCoordinates(d.dpy, d.root, parent, px, py, ctypes.byref(cx), ctypes.byref(cy), ctypes.byref(ch)):
                    px, py = cx.value, cy.value
            sa = kx.XSetWindowAttributes()
            sa.override_redirect = 1
            sa.background_pixel = 0xFFFFFF
            win = x.XCreateWindow(d.dpy, parent, px - lay["cx"], py - lay["cy"], lay["w"], lay["h"], 0, 0, 1, None,
                                  (1 << 1) | (1 << 9), ctypes.byref(sa))   # CWBackPixel | CWOverrideRedirect
            x.XStoreName(d.dpy, win, b"KASTR pointer ripple")
            shape(win, [], 2)   # ShapeInput: nothing -- clicks fall through
            shape(win, [], 0)   # nothing shows until the first frame
            gc = x.XCreateGC(d.dpy, win, 0, None)
            x.XMapRaised(d.dpy, win)
            live.append([win, gc, t0, lay, rgb, name.encode("latin-1", "replace")])

        def frame(ent, t):
            win, gc, t0, lay, rgb, label = ent
            fr = ripple_frame(t, lay)
            if fr is None:
                return False
            outer = [kx.XRectangle(a, y, b - a, 1) for y, a, b in fr["outer"]]
            inner = [kx.XRectangle(a, y, b - a, 1) for y, a, b in fr["inner"]]
            if fr["tag"]:
                tx, ty, tw, th = fr["tag"]
                outer.append(kx.XRectangle(tx, ty, tw, th))
            shape(win, outer, 0)
            x.XSetForeground(d.dpy, gc, 0xFFFFFF)
            x.XFillRectangle(d.dpy, win, gc, 0, 0, lay["w"], lay["h"])
            x.XSetForeground(d.dpy, gc, rgb)
            if inner:
                x.XFillRectangles(d.dpy, win, gc, (kx.XRectangle * len(inner))(*inner), len(inner))
            if fr["tag"]:
                x.XFillRectangle(d.dpy, win, gc, tx, ty, tw, th)
                x.XSetForeground(d.dpy, gc, kx.ink_for(rgb))
                x.XDrawString(d.dpy, win, gc, tx + 7, ty + 13, label, len(label))
            return True

        fd = x.XConnectionNumber(d.dpy)
        xev = kx.XEvent()
        try:
            while not self._stop.is_set():
                r, _, _ = select.select([fd, self._r], [], [], (1.0 / 30) if live else 0.5)
                if self._r in r:
                    try:
                        os.read(self._r, 4096)
                    except OSError:
                        pass
                while self._q:
                    make(self._q.popleft())
                    self.drawn += 1
                now = time.monotonic()
                for ent in list(live):
                    if not frame(ent, now - ent[2]):
                        live.remove(ent)
                        x.XFreeGC(d.dpy, ent[1])
                        x.XDestroyWindow(d.dpy, ent[0])
                while x.XPending(d.dpy):
                    x.XNextEvent(d.dpy, ctypes.byref(xev))
                x.XFlush(d.dpy)
        finally:
            try:
                for ent in live:
                    x.XFreeGC(d.dpy, ent[1])
                    x.XDestroyWindow(d.dpy, ent[0])
                x.XFlush(d.dpy)
            except Exception:
                pass
            d.close()


class X11Board:
    """X11: a kastr_x11.PointerWin per pointing person + X11Ripples -- children of the shared window for a window share."""
    in_capture = True

    def __init__(self, url="", log=None, display=None):
        import kastr_rc
        self.url = url
        s = kastr_rc.surface_of(url)
        self.parent = s[1] if s and s[0] != "monitor" else None
        self.display = display
        self.ptrs = {}
        self.rip = None

    def pointer(self, pid, name, color, px, py, on):
        import kastr_x11 as kx
        pw = self.ptrs.get(pid)
        if pw is None:
            if not on or len(self.ptrs) >= PT_MAX:
                return
            pw = kx.PointerWin(name, clean_color(color), self.display, parent=self.parent)
            pw.start()
            self.ptrs[pid] = pw
        pw.move(px, py, on)

    def drop(self, pid):
        pw = self.ptrs.pop(pid, None)
        if pw is not None:
            pw.stop()

    def ripple(self, px, py, name, color):
        if self.rip is None:
            self.rip = X11Ripples(self.display, self.parent)
            self.rip.start()
        self.rip.add(px, py, name, color)

    def stop(self):
        for pid in list(self.ptrs):
            self.drop(pid)
        r, self.rip = self.rip, None
        if r is not None:
            r.stop()


class NullBoard(MockBoard):
    """Nothing can be drawn on this desktop (Wayland, no X display, macOS): the viewers still draw every pointer and sonar
    (in_capture False) -- only the sharer's own screen goes without them."""
    drawn = False


def make_board(url, log=None):
    if os.environ.get("KASTR_RC_MOCK") == "1":
        return MockBoard(url, log)
    if WINDOWS:
        return WinBoard(url, log)
    if LINUX:
        try:
            import kastr_x11
            ok, _why = kastr_x11.available()
        except Exception:
            ok = False
        return X11Board(url, log) if ok or _why == "no-xtest" else NullBoard(url, log)   # drawing needs X11, not XTest
    return NullBoard(url, log)


# ---- the sharer's own pointer + buttons (observed, never moved) ----------------------------------------------------------
class _WinCursor:
    def __init__(self):
        self.u32 = ctypes.WinDLL("user32")
        self.u32.GetAsyncKeyState.restype = ctypes.c_short

    def __call__(self):
        class PT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        p = PT()
        if not self.u32.GetCursorPos(ctypes.byref(p)):
            return None
        down = set()
        for b, vk in ((0, 0x01), (2, 0x02), (1, 0x04)):   # VK_LBUTTON, VK_RBUTTON, VK_MBUTTON
            if self.u32.GetAsyncKeyState(vk) & 0x8001:     # down now, or pressed since the last look (a click shorter than a sample)
                down.add(b)
        return (p.x, p.y), down

    def close(self):
        pass


class _X11Cursor:
    """XQueryPointer for where the sharer's pointer is; the PHYSICAL presses (kastr_x11.RawMonitor: XInput2 raw events, never an
    XTEST device -- a remote controller's injected click is not the sharer's) for their clicks, however short."""

    def __init__(self, display=None):
        import kastr_x11 as kx
        self.kx = kx
        self.d = kx.Display(display)
        self._raw = deque(maxlen=32)
        self.mon = None
        try:
            m = kx.RawMonitor(self._on_raw, None, display)
            self.mon = m if m.start() else None
        except Exception:
            self.mon = None
        x = self.d.x
        from ctypes import c_int, c_uint, c_void_p, POINTER
        x.XQueryPointer.argtypes = [c_void_p, kx.Window, POINTER(kx.Window), POINTER(kx.Window), POINTER(c_int), POINTER(c_int),
                                    POINTER(c_int), POINTER(c_int), POINTER(c_uint)]
        x._kastr_qp = True

    def __call__(self):
        kx = self.kx
        r, c = kx.Window(), kx.Window()
        rx, ry, wx, wy, m = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_uint()
        if not self.d.x.XQueryPointer(self.d.dpy, self.d.root, ctypes.byref(r), ctypes.byref(c), ctypes.byref(rx), ctypes.byref(ry),
                                      ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(m)):
            return None
        down = {b for b, bit in ((0, 1 << 8), (1, 1 << 9), (2, 1 << 10)) if m.value & bit}   # Button1 / 2 / 3 masks
        if self.mon is not None:
            pressed = []
            while self._raw:
                pressed.append(self._raw.popleft())
            return (rx.value, ry.value), down, pressed
        return (rx.value, ry.value), down

    def _on_raw(self, kind, button=None):
        if kind == "down" and button in (0, 1, 2):
            self._raw.append(int(button))

    def close(self):
        m, self.mon = self.mon, None
        if m is not None:
            m.stop()
        self.d.close()


def make_cursor():
    if os.environ.get("KASTR_RC_MOCK") == "1":
        return None
    try:
        if WINDOWS:
            return _WinCursor()
        if LINUX:
            return _X11Cursor()
    except Exception:
        return None
    return None


# ---- pointer mode ------------------------------------------------------------------------------------------------------
class PointMode:
    """The pointer modes of this computer's shares (feed id -> state). rc: the kastr_rc.RemoteControl (share_info, and the
    backend's surface_rect under its lock). board_factory(url) -> a board; cursor() -> ((x, y), {buttons down}) | None."""

    def __init__(self, rc, board_factory=None, cursor=None, clock=time.monotonic, log=None):
        self.rc = rc
        self.board_factory = board_factory or (lambda url: make_board(url, log))
        self._cursor = cursor
        self._cursor_made = cursor is not None
        self._cursor_own = cursor is None   # made here (closed when the last pointer mode ends)
        self.clock = clock
        self.log = log or (lambda m: None)
        self.lock = threading.RLock()
        self.feeds = {}
        self.ended = {}           # feed -> why the last mode ended
        self._out = {}            # feed -> the sample waiting for the page {s, k: [[u, v, b]], cap}
        self._th = None
        self.stats = {"draws": 0, "ripples": 0, "own": 0, "pointers": 0}

    def cursor(self):
        if not self._cursor_made:
            self._cursor_made = True
            self._cursor = make_cursor()
        return self._cursor() if self._cursor else None

    def _rect(self, url):
        rc = self.rc
        try:
            with rc.lock:
                return rc._backend().surface_rect(url)
        except Exception:
            return None

    def _info(self, feed):
        try:
            return self.rc.share_info(feed)
        except Exception:
            return None

    def on(self, feed, share="", own=True, name="", color=None):
        import kastr_rc
        try:
            feed = int(feed)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad feed"}, 400
        info = self._info(feed)
        if not info or not info.get("live"):
            self.off(feed, "share")
            return {"ok": False, "error": "that share is not on the air", "why": "share"}, 409
        if info.get("paused"):
            self.off(feed, "paused")
            return {"ok": False, "error": "that share is paused", "why": "paused"}, 409
        if kastr_rc.surface_of(info.get("url")) is None:
            return {"ok": False, "error": "only a native screen, window or tab share takes pointers"}, 409
        with self.lock:
            st = self.feeds.get(feed)
            if st is not None and st["url"] != info["url"]:
                self._end_locked(feed, "retarget")
                st = None
            if st is None:
                try:
                    board = self.board_factory(info["url"])
                except Exception as e:
                    self.log("point: no overlay here: %s" % e)
                    board = MockBoard(info["url"])
                st = self.feeds[feed] = {"url": info["url"], "share": str(share or "")[:240], "board": board, "ptrs": {}, "rips": deque(maxlen=256),
                                         "own": True, "name": "", "color": "#009fda", "down": set(), "last": None, "at": self.clock()}
                self.log("point: pointer mode on for feed %s (%s)" % (feed, info["url"]))
            st.update(own=bool(own), name=clean_name(name, "Sharer"), color=clean_color(color), lease=self.clock() + PT_LEASE_S)
            self.ended.pop(feed, None)
        self._loop()
        return {"ok": True, "feed": feed, "cap": 1 if getattr(st["board"], "in_capture", False) else 0, "scap": 1,
                "overlay": not isinstance(st["board"], MockBoard) or os.environ.get("KASTR_RC_MOCK") == "1",
                "sample": self.take(feed, force=True)}, 200

    def off(self, feed=None, why="stopped"):
        with self.lock:
            for f in ([int(feed)] if feed is not None else list(self.feeds)):
                self._end_locked(f, why)
        return {"ok": True}, 200

    def _end_locked(self, feed, why):
        st = self.feeds.pop(feed, None)
        if st is None:
            return
        self._out.pop(feed, None)
        self.ended[feed] = why
        try:
            st["board"].stop()
        except Exception:
            pass
        self.log("point: pointer mode off for feed %s (%s)" % (feed, why))

    def draw(self, feed, ptrs, rips):
        """The pointing people's pointers (the full set: anyone missing is taken off the screen) and NEW clicks of theirs."""
        try:
            feed = int(feed)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad feed"}, 400
        with self.lock:
            st = self.feeds.get(feed)
            if st is None:
                return {"ok": False, "error": "no pointer mode on that share", "ended": self.ended.get(feed, "")}, 409
            st["lease"] = self.clock() + PT_LEASE_S
        rect = self._rect(st["url"])
        b = st["board"]
        want = clean_pointers(ptrs)
        seen = set()
        for p in want:
            seen.add(p["id"])
            xy = to_px(p["x"], p["y"], rect) if p["on"] else None
            key = (xy, p["n"], p["c"])
            if st["ptrs"].get(p["id"]) == key:
                continue
            st["ptrs"][p["id"]] = key
            try:
                b.pointer(p["id"], p["n"], p["c"], xy[0] if xy else 0, xy[1] if xy else 0, xy is not None)
            except Exception as e:
                self.log("point: pointer: %s" % e)
        for pid in [k for k in st["ptrs"] if k not in seen]:
            st["ptrs"].pop(pid, None)
            try:
                b.drop(pid)
            except Exception:
                pass
        n = 0
        for r in clean_ripples(rips):
            if r["id"] in st["rips"]:
                continue
            st["rips"].append(r["id"])
            xy = to_px(r["x"], r["y"], rect)
            if xy is None:
                continue
            try:
                b.ripple(xy[0], xy[1], r["n"], r["c"])
                n += 1
            except Exception as e:
                self.log("point: ripple: %s" % e)
        self.stats["draws"] += 1
        self.stats["ripples"] += n
        self.stats["pointers"] = len(st["ptrs"])
        return {"ok": True, "ripples": n, "pointers": len(st["ptrs"])}, 200

    # ---- the sharer's own pointer and clicks
    def poll(self):
        """One sample of the sharer's own pointer for every pointer mode: moves -> the page's next sample, a new press inside
        the shared surface -> a click (and its sonar here when "Show my clicks" is on). The real cursor is never moved."""
        with self.lock:
            feeds = list(self.feeds.items())
        if not feeds:
            return
        cur = self.cursor()
        if cur is None:
            return
        pos, down = cur[0], cur[1]
        raw = cur[2] if len(cur) > 2 else None   # X11: the physical presses since the last sample (else: edges of `down`)
        b = self.rc.backend
        if getattr(getattr(b, "warp", None), "active", False):   # a remote controller's warp-click borrows the cursor: not the sharer
            return
        for feed, st in feeds:
            rect = self._rect(st["url"])
            uv = to_uv(pos, rect)
            if uv is None:
                continue
            clicks = []
            for btn in (raw if raw is not None else presses(st["down"], down)):
                if uv[2]:
                    clicks.append([uv[0], uv[1], btn])
                    if st["own"]:
                        try:
                            st["board"].ripple(pos[0], pos[1], st["name"], st["color"])
                            self.stats["own"] += 1
                        except Exception:
                            pass
            st["down"] = set(down)
            if uv == st["last"] and not clicks:
                continue
            st["last"] = uv
            with self.lock:
                o = self._out.get(feed)
                ks = (o["k"] if o else []) + clicks
                self._out[feed] = {"s": uv, "k": ks[-16:], "cap": 1 if getattr(st["board"], "in_capture", False) else 0}

    def take(self, feed=None, force=False):
        """-> the samples waiting for the page ({feed: {s, k, cap}}; one feed's sample with `feed`), None when nothing moved."""
        with self.lock:
            if feed is not None:
                o = self._out.pop(int(feed), None)
                st = self.feeds.get(int(feed))
                if o is None and force and st is not None and st["last"] is not None:
                    o = {"s": st["last"], "k": [], "cap": 1 if getattr(st["board"], "in_capture", False) else 0}
                return o
            if not self._out:
                return None
            out, self._out = {str(k): v for k, v in self._out.items()}, {}
            return out

    def check(self):
        """The leases and the shares, now (the sampler every 0.5 s). -> [(feed, why)] ended."""
        out = []
        with self.lock:
            feeds = list(self.feeds.items())
        for feed, st in feeds:
            why = None
            if self.clock() > st["lease"]:
                why = "timeout"
            else:
                info = self._info(feed)
                if not info or not info.get("live"):
                    why = "share"
                elif info.get("paused"):
                    why = "paused"
                elif info.get("url") != st["url"]:
                    why = "retarget"
            if why:
                with self.lock:
                    self._end_locked(feed, why)
                out.append((feed, why))
        return out

    def _loop(self):
        if self._th is not None and self._th.is_alive():
            return
        self._th = threading.Thread(target=self._run, name="kastr-point-sampler", daemon=True)
        self._th.start()

    def _run(self):
        last_check = 0.0
        while True:
            with self.lock:
                if not self.feeds:
                    c = self._cursor if self._cursor_own else None
                    if c is not None:   # the last pointer mode ended: its X connection + raw-event monitor go too
                        self._cursor, self._cursor_made = None, False
                        try:
                            c.close()
                        except Exception:
                            pass
                    return
            try:
                self.poll()
            except Exception as e:
                self.log("point: sample: %s" % e)
            if time.monotonic() - last_check > 0.5:
                last_check = time.monotonic()
                self.check()
            time.sleep(1.0 / PT_HZ)

    def share_gone(self, feed_id, why):
        with self.lock:
            if int(feed_id) in self.feeds:
                self._end_locked(int(feed_id), why)

    def status(self):
        with self.lock:
            return {"ok": True, "feeds": {str(f): {"url": st["url"], "share": st["share"], "own": st["own"], "pointers": len(st["ptrs"]),
                                                   "cap": 1 if getattr(st["board"], "in_capture", False) else 0}
                                          for f, st in self.feeds.items()},
                    "ended": {str(k): v for k, v in self.ended.items()}, "stats": dict(self.stats)}


_PM = None
_PM_LOCK = threading.Lock()


def get(rc, log=None):
    global _PM
    with _PM_LOCK:
        if _PM is None:
            _PM = PointMode(rc, log=log)
        else:
            _PM.rc = rc
        return _PM


def current():
    return _PM


def share_gone(feed_id, why):
    pm = _PM
    if pm is not None:
        try:
            pm.share_gone(feed_id, why)
        except Exception:
            pass


def dispatch(rc, p, log=None):
    """kastr_rc's /api/rc + /api/rc/ws: {op: pt-on | pt-off | pt-draw | pt-status, feed, ...} -> (reply, code). Nothing here can
    inject input: pointers and ripples are drawn, the sharer's own pointer is read."""
    pm = get(rc, log)
    op = str(p.get("op") or "")
    if op == "pt-on":
        return pm.on(p.get("feed"), p.get("share"), p.get("own", True), p.get("name"), p.get("color"))
    if op == "pt-off":
        return pm.off(p.get("feed"), str(p.get("why") or "stopped")[:20])
    if op == "pt-draw":
        return pm.draw(p.get("feed"), p.get("p"), p.get("r"))
    if op == "pt-status":
        return pm.status(), 200
    return {"ok": False, "error": "op is pt-on | pt-off | pt-draw | pt-status"}, 400
