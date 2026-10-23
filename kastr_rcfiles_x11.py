"""X11 for files and images over remote control (0.21.83; kastr_rcfiles): the CLIPBOARD selection as files / a picture, and a
drop where the controller let go (XDND). ctypes over libX11 (+ libXfixes when present) through kastr_x11's Display; reading
the clipboard uses xclip (as kastr_x11's text clipboard does).

  * X11Clip.signature(): XFixes counts every new CLIPBOARD owner (a copy) on a thread of its own; without XFixes, the
    owner window + its TIMESTAMP.
  * X11Clip.read(): TARGETS first -- our own marker (application/x-kastr-rc) means "ours, never offered back";
    x-special/gnome-copied-files or text/uri-list -> files; a text target -> text (it travels on its own and wins over a
    picture); image/png (or image/bmp) -> a picture.
  * ClipOwner: owns CLIPBOARD and answers TARGETS / TIMESTAMP / its targets, large ones with INCR (ICCCM 2.7.2), until
    someone else copies (SelectionClear) or it is released.
  * xdnd_drop(paths, x, y): XDND v5 as a SOURCE -- the topmost managed window under the root point that is XdndAware gets
    Enter / Position / (its Status) / Drop, then reads XdndSelection (text/uri-list) from us and says Finished. "none" when
    nothing there takes drops (the caller saves to Downloads/KASTR), "desktop" when the point is on the bare root.
"""
import ctypes
import os
import select
import shutil
import subprocess
import threading
import time

import kastr_rcfiles as rf
import kastr_x11 as x11

c_ulong, c_long, c_int, c_uint, c_void_p, c_char_p = ctypes.c_ulong, ctypes.c_long, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p, ctypes.c_char_p
Window = Atom = c_ulong
SELECTION_CLEAR, SELECTION_REQUEST, SELECTION_NOTIFY, PROPERTY_NOTIFY, CLIENT_MESSAGE = 29, 30, 31, 28, 33
PROPERTY_CHANGE_MASK = 1 << 22
XA_ATOM, XA_INTEGER = 4, 19
FILE_TARGETS = ("x-special/gnome-copied-files", "text/uri-list")
TEXT_TARGETS = ("UTF8_STRING", "STRING", "TEXT", "text/plain", "text/plain;charset=utf-8", "COMPOUND_TEXT")


class XSelectionRequestEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p), ("owner", Window),
                ("requestor", Window), ("selection", Atom), ("target", Atom), ("property", Atom), ("time", c_ulong)]


class XSelectionEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p), ("requestor", Window),
                ("selection", Atom), ("target", Atom), ("property", Atom), ("time", c_ulong)]


class XPropertyEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p), ("window", Window),
                ("atom", Atom), ("time", c_ulong), ("state", c_int)]


class XClientMessageEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p), ("window", Window),
                ("message_type", Atom), ("format", c_int), ("l", c_long * 5)]


def _lib():
    x = x11._x11()
    if x is None:
        raise OSError("libX11 is not installed")
    if not getattr(x, "_kastr_rcf", False):
        x.XSetSelectionOwner.argtypes = [c_void_p, Atom, Window, c_ulong]
        x.XGetSelectionOwner.restype, x.XGetSelectionOwner.argtypes = Window, [c_void_p, Atom]
        x.XChangeProperty.argtypes = [c_void_p, Window, Atom, Atom, c_int, c_int, c_void_p, c_int]
        x.XDeleteProperty.argtypes = [c_void_p, Window, Atom]
        x.XSendEvent.argtypes = [c_void_p, Window, c_int, c_long, c_void_p]
        x.XCreateSimpleWindow.restype = Window
        x.XCreateSimpleWindow.argtypes = [c_void_p, Window, c_int, c_int, c_uint, c_uint, c_uint, c_ulong, c_ulong]
        x.XGetAtomName.restype, x.XGetAtomName.argtypes = c_void_p, [c_void_p, Atom]
        x.XMaxRequestSize.restype, x.XMaxRequestSize.argtypes = c_long, [c_void_p]
        x._kastr_rcf = True
    return x


def _event_time(d, win):
    """A server timestamp (ICCCM: never CurrentTime for ownership): append nothing to a property of our own window and
    read the PropertyNotify's time."""
    x = d.x
    x.XSelectInput(d.dpy, win, PROPERTY_CHANGE_MASK)
    a = d.atom("KASTR_TS")
    x.XChangeProperty(d.dpy, win, a, XA_INTEGER, 8, 2, None, 0)   # PropModeAppend, zero bytes
    x.XFlush(d.dpy)
    ev = x11.XEvent()
    t0 = time.time()
    fd = x.XConnectionNumber(d.dpy)
    while time.time() - t0 < 2.0:
        if not x.XPending(d.dpy):
            select.select([fd], [], [], 0.05)
            continue
        x.XNextEvent(d.dpy, ctypes.byref(ev))
        if (ev[0] & 0xFFFFFFFF) == PROPERTY_NOTIFY:
            pe = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(XPropertyEvent)).contents
            if pe.window == win and pe.atom == a:
                return pe.time
    return 0


class _SelServer:
    """Answers SelectionRequests for one selection on one window: TARGETS, TIMESTAMP and `data` {target name: bytes}; INCR
    for anything bigger than one request may carry."""

    def __init__(self, d, win, selection, data, ts):
        self.d, self.win, self.sel, self.ts = d, win, selection, ts
        self.data = {d.atom(k): v for k, v in data.items()}
        self.incr = {}        # (requestor, property) -> [type atom, bytes, offset]
        self.served = 0
        mx = int(d.x.XMaxRequestSize(d.dpy) or 65536) * 4 - 1024
        self.step = max(4096, min(mx, 256 << 10))

    def _reply(self, req, prop):
        ev = XSelectionEvent(type=SELECTION_NOTIFY, serial=0, send_event=1, display=self.d.dpy, requestor=req.requestor,
                             selection=req.selection, target=req.target, property=prop, time=req.time)
        self.d.x.XSendEvent(self.d.dpy, req.requestor, 0, 0, ctypes.byref(ev))

    def request(self, req):
        x, d = self.d.x, self.d
        prop = req.property or req.target
        tgt = req.target
        if req.selection != self.sel:
            return self._reply(req, 0)
        if tgt == d.atom("TARGETS"):
            atoms = [d.atom("TARGETS"), d.atom("TIMESTAMP")] + list(self.data)
            arr = (c_ulong * len(atoms))(*atoms)
            x.XChangeProperty(d.dpy, req.requestor, prop, XA_ATOM, 32, 0, ctypes.cast(arr, c_void_p), len(atoms))
        elif tgt == d.atom("TIMESTAMP"):
            arr = (c_ulong * 1)(self.ts)
            x.XChangeProperty(d.dpy, req.requestor, prop, XA_INTEGER, 32, 0, ctypes.cast(arr, c_void_p), 1)
        elif tgt in self.data:
            b = self.data[tgt]
            if len(b) > self.step:
                x.XSelectInput(d.dpy, req.requestor, PROPERTY_CHANGE_MASK)
                arr = (c_ulong * 1)(len(b))
                x.XChangeProperty(d.dpy, req.requestor, prop, d.atom("INCR"), 32, 0, ctypes.cast(arr, c_void_p), 1)
                self.incr[(req.requestor, prop)] = [tgt, b, 0]
            else:
                buf = ctypes.create_string_buffer(b, len(b))
                x.XChangeProperty(d.dpy, req.requestor, prop, tgt, 8, 0, ctypes.cast(buf, c_void_p), len(b))
            self.served += 1
        else:
            prop = 0
        self._reply(req, prop)
        x.XFlush(d.dpy)

    def property(self, pe):
        """The requestor deleted the property we filled: the next INCR piece (an empty one ends it)."""
        if pe.state != 1:   # PropertyDelete
            return
        k = (pe.window, pe.atom)
        st = self.incr.get(k)
        if st is None:
            return
        tgt, b, off = st
        piece = b[off:off + self.step]
        buf = ctypes.create_string_buffer(piece, len(piece)) if piece else None
        self.d.x.XChangeProperty(self.d.dpy, pe.window, pe.atom, tgt, 8, 0, ctypes.cast(buf, c_void_p) if buf else None, len(piece))
        self.d.x.XFlush(self.d.dpy)
        if piece:
            st[2] = off + len(piece)
        else:
            self.incr.pop(k, None)


class ClipOwner:
    """CLIPBOARD owned by KASTR, serving `data` {target: bytes} (+ the marker) on a thread of its own until someone else
    copies or stop()."""

    def __init__(self, data, display=None):
        self.data = dict(data)
        self.display = display
        self.win = 0
        self.lost = threading.Event()
        self.ready = threading.Event()
        self._stop = threading.Event()
        self.ok = False
        self._th = threading.Thread(target=self._run, name="kastr-rcfiles-clip", daemon=True)

    def start(self):
        self._th.start()
        self.ready.wait(3.0)
        return self.ok

    def stop(self):
        self._stop.set()
        if self._th.is_alive() and self._th is not threading.current_thread():
            self._th.join(2.0)

    def _run(self):
        try:
            _lib()
            d = x11.Display(self.display)
        except OSError:
            self.ready.set()
            return
        x = d.x
        win = self.win = x.XCreateSimpleWindow(d.dpy, d.root, -10, -10, 1, 1, 0, 0, 0)
        try:
            ts = _event_time(d, win)
            sel = d.atom("CLIPBOARD")
            srv = _SelServer(d, win, sel, self.data, ts)
            x.XSetSelectionOwner(d.dpy, sel, win, ts)
            x.XFlush(d.dpy)
            self.ok = x.XGetSelectionOwner(d.dpy, sel) == win
            self.ready.set()
            if not self.ok:
                return
            fd = x.XConnectionNumber(d.dpy)
            ev = x11.XEvent()
            while not self._stop.is_set():
                if not x.XPending(d.dpy):
                    select.select([fd], [], [], 0.2)
                    continue
                x.XNextEvent(d.dpy, ctypes.byref(ev))
                t = ev[0] & 0xFFFFFFFF
                if t == SELECTION_REQUEST:
                    srv.request(ctypes.cast(ctypes.byref(ev), ctypes.POINTER(XSelectionRequestEvent)).contents)
                elif t == PROPERTY_NOTIFY:
                    srv.property(ctypes.cast(ctypes.byref(ev), ctypes.POINTER(XPropertyEvent)).contents)
                elif t == SELECTION_CLEAR:
                    self.lost.set()
                    break
            if not self.lost.is_set():   # released: give CLIPBOARD up (an empty clipboard, not one pointing at deleted files)
                x.XSetSelectionOwner(d.dpy, sel, 0, ts)
                x.XFlush(d.dpy)
        finally:
            self.ready.set()
            try:
                x.XDestroyWindow(d.dpy, win)
                x.XFlush(d.dpy)
            except Exception:
                pass
            d.close()


class _OwnerWatch:
    """XFixes: every SetSelectionOwner on CLIPBOARD (each copy, by anyone) bumps `n`."""

    def __init__(self, display=None):
        self.n = 0
        self.ok = False
        self._stop = threading.Event()
        self._ready = threading.Event()
        threading.Thread(target=self._run, args=(display,), name="kastr-rcfiles-xfixes", daemon=True).start()
        self._ready.wait(2.0)

    def _run(self, display):
        xf = x11._load("Xfixes")
        try:
            _lib()
            d = x11.Display(display)
        except OSError:
            self._ready.set()
            return
        try:
            if xf is None:
                return
            xf.XFixesQueryExtension.argtypes = [c_void_p, ctypes.POINTER(c_int), ctypes.POINTER(c_int)]
            xf.XFixesSelectSelectionInput.argtypes = [c_void_p, Window, Atom, c_ulong]
            eb, erb = c_int(), c_int()
            if not xf.XFixesQueryExtension(d.dpy, ctypes.byref(eb), ctypes.byref(erb)):
                return
            xf.XFixesSelectSelectionInput(d.dpy, d.root, d.atom("CLIPBOARD"), 1)   # SetSelectionOwnerNotifyMask
            d.x.XFlush(d.dpy)
            self.ok = True
            self._ready.set()
            fd = d.x.XConnectionNumber(d.dpy)
            ev = x11.XEvent()
            while not self._stop.is_set():
                if not d.x.XPending(d.dpy):
                    select.select([fd], [], [], 0.25)
                    continue
                d.x.XNextEvent(d.dpy, ctypes.byref(ev))
                if (ev[0] & 0xFFFFFFFF) == eb.value:   # XFixesSelectionNotify
                    self.n += 1
        finally:
            self._ready.set()
            d.close()

    def stop(self):
        self._stop.set()


def _xclip(args, cap, timeout=3.0):
    p = shutil.which("xclip")
    if not p:
        return None
    try:
        r = subprocess.run([p, "-selection", "clipboard"] + args + ["-o"], capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout[:cap + 1]


class X11Clip:
    name = "x11"

    def __init__(self, display=None):
        self.display = display
        self.owner = None
        self._w = None
        self._lock = threading.Lock()

    def _watch(self):
        if self._w is None:
            self._w = _OwnerWatch(self.display)
        return self._w

    def signature(self):
        w = self._watch()
        if w.ok:
            return ("x", w.n)
        ts = _xclip(["-t", "TIMESTAMP"], 64)
        return ("t", ts)

    def read(self, image_max):
        t = _xclip(["-t", "TARGETS"], 1 << 16)
        if t is None:
            return {}
        targets = set(t.decode("utf-8", "replace").split())
        if rf.MARK in targets:
            return {"ours": True}
        for ft in FILE_TARGETS:
            if ft in targets:
                b = _xclip(["-t", ft], 8 << 20)
                paths = rf.parse_uris((b or b"").decode("utf-8", "replace"))
                if paths:
                    return {"files": paths}
        if targets & set(TEXT_TARGETS):
            return {"text": True}
        if "image/png" in targets:
            b = _xclip(["-t", "image/png"], image_max, timeout=10)
            if b and len(b) <= image_max and b.startswith(b"\x89PNG"):
                return {"image": b}
            return {"image_too_big": True} if b else {}
        if "image/bmp" in targets:
            b = _xclip(["-t", "image/bmp"], 600 << 20, timeout=10)
            png = rf.dib_to_png(rf.bmp_to_dib(b)) if b else None
            if png and len(png) <= image_max:
                return {"image": png}
        return {}

    def _own(self, data, oid):
        with self._lock:
            old, self.owner = self.owner, None
            if old is not None:
                old.stop()
            o = ClipOwner(dict(data, **{rf.MARK: oid.encode()}), self.display)
            ok = o.start()
            self.owner = o if ok else None
            return ok

    def put_files(self, paths, oid):
        return self._own({"x-special/gnome-copied-files": rf.gnome_copied(paths), "text/uri-list": rf.uri_list(paths)}, oid)

    def put_image(self, png, oid):
        return self._own({"image/png": bytes(png)}, oid)

    def still_ours(self):
        o = self.owner
        return o is not None and not o.lost.is_set()

    def release(self):
        with self._lock:
            o, self.owner = self.owner, None
        if o is not None:
            o.stop()

    def close(self):
        self.release()
        if self._w is not None:
            self._w.stop()


# ---- XDND: a drop where the controller let go ----------------------------------------------------------------------------
def _target_at(d, x, y):
    """-> (window, version) of the XdndAware window under the root point (the outermost on the way down from the topmost
    managed top-level there; override-redirect windows -- menus, KASTR's own pointer and bar -- are never targets), "desktop"
    when the point is on the bare root, or None."""
    kids, _ = d.children(d.root)
    top = 0
    for k in reversed(kids):
        a = d.attrs(k)
        if a is None or a.map_state != 2 or a.override_redirect:
            continue
        r = d.rect(k)
        if r and r["x"] <= x < r["x"] + r["w"] and r["y"] <= y < r["y"] + r["h"]:
            top = k
            break
    if not top:
        return "desktop"
    cur = top
    for _ in range(16):
        p = d.prop(cur, "XdndAware")
        if p and p[1] == 32 and p[2]:
            ver = int(c_ulong.from_buffer_copy(p[2][:ctypes.sizeof(c_ulong)]).value)
            px = d.prop(cur, "XdndProxy")
            if px and px[1] == 32 and px[2]:
                cur = int(c_ulong.from_buffer_copy(px[2][:ctypes.sizeof(c_ulong)]).value) or cur
            return cur, ver
        wtype = d.windows_prop(cur, "_NET_WM_WINDOW_TYPE")
        if d.atom("_NET_WM_WINDOW_TYPE_DESKTOP") in wtype:
            pass
        nxt = 0
        kids, _ = d.children(cur)
        for k in reversed(kids):
            a = d.attrs(k)
            if a is None or a.map_state != 2:
                continue
            r = d.rect(k)
            if r and r["x"] <= x < r["x"] + r["w"] and r["y"] <= y < r["y"] + r["h"]:
                nxt = k
                break
        if not nxt:
            break
        cur = nxt
    return None


def xdnd_drop(paths, x, y, display=None, status_s=3.0, finish_s=30.0):
    """Drop `paths` (a text/uri-list) at the root point (x, y) -> ("done", window title) | ("refused", title) | ("none", "")
    | ("desktop", "")."""
    _lib()
    d = x11.Display(display)
    xl = d.x
    win = xl.XCreateSimpleWindow(d.dpy, d.root, -10, -10, 1, 1, 0, 0, 0)
    try:
        hit = _target_at(d, int(x), int(y))
        if hit == "desktop":
            return "desktop", ""
        if not hit:
            return "none", ""
        tgt, ver = hit
        ver = max(3, min(5, ver))
        title = d.title(d.top_level(tgt)) or d.title(tgt)
        ts = _event_time(d, win)
        sel = d.atom("XdndSelection")
        srv = _SelServer(d, win, sel, {"text/uri-list": rf.uri_list(paths)}, ts)
        xl.XSetSelectionOwner(d.dpy, sel, win, ts)

        def cm(kind, l):
            ev = XClientMessageEvent(type=CLIENT_MESSAGE, serial=0, send_event=1, display=d.dpy, window=tgt,
                                     message_type=d.atom(kind), format=32, l=(c_long * 5)(*[ctypes.c_long(v & 0xFFFFFFFFFFFFFFFF).value for v in l]))
            xl.XSendEvent(d.dpy, tgt, 0, 0, ctypes.byref(ev))
            xl.XFlush(d.dpy)

        cm("XdndEnter", [win, ver << 24, d.atom("text/uri-list"), 0, 0])
        cm("XdndPosition", [win, 0, (int(x) << 16) | (int(y) & 0xFFFF), ts, d.atom("XdndActionCopy")])
        fd = xl.XConnectionNumber(d.dpy)
        ev = x11.XEvent()
        accepted, dropped, t0 = None, False, time.time()
        while True:
            limit = finish_s if dropped else status_s
            if time.time() - t0 > limit:
                break
            if not xl.XPending(d.dpy):
                select.select([fd], [], [], 0.05)
                continue
            xl.XNextEvent(d.dpy, ctypes.byref(ev))
            t = ev[0] & 0xFFFFFFFF
            if t == SELECTION_REQUEST:
                srv.request(ctypes.cast(ctypes.byref(ev), ctypes.POINTER(XSelectionRequestEvent)).contents)
            elif t == PROPERTY_NOTIFY:
                srv.property(ctypes.cast(ctypes.byref(ev), ctypes.POINTER(XPropertyEvent)).contents)
            elif t == CLIENT_MESSAGE:
                m = ctypes.cast(ctypes.byref(ev), ctypes.POINTER(XClientMessageEvent)).contents
                if m.message_type == d.atom("XdndStatus") and not dropped:
                    accepted = bool(m.l[1] & 1)
                    if accepted:
                        cm("XdndDrop", [win, 0, ts, 0, 0])
                        dropped, t0 = True, time.time()
                    else:
                        cm("XdndLeave", [win, 0, 0, 0, 0])
                        return "refused", title
                elif m.message_type == d.atom("XdndFinished") and dropped:
                    return ("done" if (ver < 5 or (m.l[1] & 1) or srv.served) else "refused"), title
        if dropped:
            return ("done" if srv.served else "refused"), title
        cm("XdndLeave", [win, 0, 0, 0, 0])
        return "none", title
    finally:
        try:
            xl.XDestroyWindow(d.dpy, win)
            xl.XFlush(d.dpy)
        except Exception:
            pass
        d.close()
