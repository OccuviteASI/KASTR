"""browser_tabs -- list / activate / crop the tabs of the user's real browsers.

KASTR "Share a tab" prototype (Windows only).  Stdlib + ctypes: Windows UI
Automation is driven as a hand-rolled COM client (CoCreateInstance
CLSID_CUIAutomation, IUIAutomation* vtables called by index), so there is no
comtypes / pywin32 and no PowerShell round trip.

    list_windows()            -> one dict per browser window, tabs inside
    list_tabs()               -> flat list of tab dicts (id = "<hwnd>:<index>")
    activate_tab(hwnd, which) -> bring tab `which` (index or title) to the front
    content_crop(hwnd)        -> gfxcapture crop_* for the web-page area
    frame_bounds(hwnd)        -> DWMWA_EXTENDED_FRAME_BOUNDS (physical px)

CLI:  python browser_tabs.py --list [--json] | --crop <hwnd> | --activate <hwnd> <i>
      (--list prints counts and title LENGTHS only, never tab titles)

Every call is safe from any thread: COM is initialised (MTA) per thread and
one IUIAutomation object is kept per thread.
"""
import ctypes
import ctypes.wintypes as wt
import os
import re
import sys
import threading
import time

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("browser_tabs is Windows only")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")
oleaut32 = ctypes.WinDLL("oleaut32")
dwmapi = ctypes.WinDLL("dwmapi")

# ---------------------------------------------------------------- DPI ---
_DPI_DONE = None


def ensure_dpi_awareness():
    """Per-monitor-v2 DPI awareness: once for the process (fails harmlessly
    when a manifest already fixed it) and, every call, for the CALLING THREAD
    (SetThreadDpiAwarenessContext works even in a system-aware process, so
    the rects below are physical pixels whatever KASTR.exe's manifest says).
    Returns the thread's awareness: 'pmv2', 'pm', 'system' or 'unaware'."""
    global _DPI_DONE
    if _DPI_DONE is None:
        try:
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PMv2
        except Exception:
            pass
        _DPI_DONE = True
    try:
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass
    return dpi_awareness()


def dpi_awareness():
    try:
        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        ctx = user32.GetThreadDpiAwarenessContext()
        a = user32.GetAwarenessFromDpiAwarenessContext(ctx)
        user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        if a == 2 and user32.AreDpiAwarenessContextsEqual(ctypes.c_void_p(ctx), ctypes.c_void_p(-4)):
            return "pmv2"
        return {0: "unaware", 1: "system", 2: "pm"}.get(a, str(a))
    except Exception:
        return "unknown"


# ------------------------------------------------------------- Win32 ----
class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]

    def t(self):
        return (self.left, self.top, self.right, self.bottom)


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.EnumChildWindows.argtypes = [wt.HWND, WNDENUMPROC, wt.LPARAM]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.IsWindow.argtypes = [wt.HWND]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
user32.GetWindow.restype = wt.HWND
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetDpiForWindow.argtypes = [wt.HWND]
user32.GetForegroundWindow.restype = wt.HWND
dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]

# window class -> engine; exe -> short browser name (Electron apps and
# Thunderbird share these classes, so the exe decides).
_CLASSES = {"Chrome_WidgetWin_1": "chromium", "MozillaWindowClass": "firefox"}
BROWSERS = {
    "chrome.exe": "chrome", "msedge.exe": "msedge", "brave.exe": "brave",
    "opera.exe": "opera", "opera_gx.exe": "opera", "vivaldi.exe": "vivaldi",
    "chromium.exe": "chromium", "arc.exe": "arc", "thorium.exe": "thorium",
    "firefox.exe": "firefox", "librewolf.exe": "librewolf",
    "waterfox.exe": "waterfox", "floorp.exe": "floorp", "zen.exe": "zen",
}


def _cls(hwnd):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, b, 256)
    return b.value


def _text(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, b, n + 2)
    return b.value


def _pid(hwnd):
    p = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


_EXE_CACHE = {}


def _exe(pid):
    if pid in _EXE_CACHE:
        return _EXE_CACHE[pid]
    name = ""
    h = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if h:
        b = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, b, ctypes.byref(n)):
            name = b.value
        kernel32.CloseHandle(h)
    _EXE_CACHE[pid] = name
    return name


def _cloaked(hwnd):
    v = wt.DWORD()
    if dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(v), 4) == 0:
        return bool(v.value)
    return False


def frame_bounds(hwnd):
    """DWMWA_EXTENDED_FRAME_BOUNDS: the window without its invisible resize
    border / shadow = what gfxcapture hands over with capture_border=1.
    Always physical pixels (DWM ignores the caller's DPI awareness)."""
    r = RECT()
    if dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        ensure_dpi_awareness()
        user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r))
    return r.t()


def client_bounds(hwnd):
    """Client area in screen coordinates, physical pixels (needs PMv2 -- an
    unaware caller gets DPI-virtualised numbers).  gfxcapture's DEFAULT
    (capture_border=0) captures exactly this rectangle, clipped to the frame:
    measured 1232x867 client vs 1234x868 frame on a 125 % Chrome window."""
    ensure_dpi_awareness()
    r = RECT()
    user32.GetClientRect(wt.HWND(hwnd), ctypes.byref(r))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(wt.HWND(hwnd), ctypes.byref(pt))
    return (pt.x, pt.y, pt.x + r.right, pt.y + r.bottom)


def _top_windows():
    out = []

    def cb(h, _):
        out.append(h)
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def _child_windows(hwnd):
    out = []

    def cb(h, _):
        out.append(h)
        return True
    user32.EnumChildWindows(wt.HWND(hwnd), WNDENUMPROC(cb), 0)
    return out


def browser_windows(exclude_pids=()):
    """Top-level windows of known browsers: [(hwnd, engine, browser, pid)].
    Pass KASTR's own bundled-browser pid(s) in exclude_pids."""
    ensure_dpi_awareness()
    res = []
    for h in _top_windows():
        eng = _CLASSES.get(_cls(h))
        if not eng or not user32.IsWindowVisible(h):
            continue
        if user32.GetWindow(h, 4):            # GW_OWNER: dialogs / popups
            continue
        pid = _pid(h)
        if pid in exclude_pids:
            continue
        exe = os.path.basename(_exe(pid)).lower()
        br = BROWSERS.get(exe)
        if not br:
            continue
        if not _text(h) and eng == "chromium":  # hidden helper widgets
            continue
        res.append((int(h), eng, br, pid))
    return res


# ---------------------------------------------------------------- COM ---
HRESULT = ctypes.c_long


class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]

    def __init__(self, s):
        super().__init__()
        ole32.CLSIDFromString(ctypes.c_wchar_p("{%s}" % s), ctypes.byref(self))


class VARIANT(ctypes.Structure):  # 24 bytes on x64
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("val", ctypes.c_longlong), ("val2", ctypes.c_longlong)]


oleaut32.SysStringLen.argtypes = [ctypes.c_void_p]
oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
oleaut32.VariantClear.argtypes = [ctypes.POINTER(VARIANT)]

CLSID_CUIAutomation = GUID("ff48dba4-60ef-4201-aa87-54103eef594e")
IID_IUIAutomation = GUID("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee")

# property / control-type / pattern ids (UIAutomationClient.h)
P_PROCESSID, P_CONTROLTYPE, P_NAME, P_CLASSNAME = 30002, 30003, 30005, 30012
P_HWND, P_OFFSCREEN, P_ISSELECTED, P_LEGACYSTATE = 30020, 30022, 30079, 30096
P_AUTOMATIONID = 30011
CT_TAB, CT_TABITEM, CT_DOCUMENT = 50018, 50019, 50030
PAT_INVOKE, PAT_SELITEM, PAT_LEGACY = 10000, 10010, 10018
SCOPE_CHILDREN, SCOPE_DESCENDANTS, SCOPE_SUBTREE = 2, 4, 7

_protos = {}
_BYREF = type(ctypes.byref(ctypes.c_int()))


def _vcall(ptr, idx, *args):
    """Call vtable slot `idx` of COM interface pointer `ptr` (args are ctypes
    instances; every slot is stdcall HRESULT(this, ...))."""
    types = tuple(ctypes.c_void_p if type(a) is _BYREF else type(a) for a in args)
    key = (idx,) + types
    fn = _protos.get(key)
    if fn is None:
        fn = _protos[key] = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, *types)
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return fn(vtbl[idx])(ptr, *args)


class UIAError(OSError):
    pass


class _Com:
    """Owning wrapper around one interface pointer (Release on GC)."""
    __slots__ = ("p",)

    def __init__(self, p):
        self.p = p

    def __del__(self):
        p, self.p = self.p, None
        if p:
            try:
                _vcall(p, 2)
            except Exception:
                pass

    def call(self, idx, *args):
        hr = _vcall(self.p, idx, *args)
        if hr < 0:
            raise UIAError("COM slot %d failed: 0x%08X" % (idx, hr & 0xFFFFFFFF))
        return hr

    def out(self, idx, *args):
        """Call a method whose last argument is an interface out-pointer."""
        o = ctypes.c_void_p()
        self.call(idx, *args, ctypes.byref(o))
        return o.value


def _bstr(p):
    if not p:
        return ""
    s = ctypes.wstring_at(p, oleaut32.SysStringLen(p))
    oleaut32.SysFreeString(p)
    return s


def _variant_value(v):
    vt = v.vt
    if vt == 3:            # VT_I4
        return ctypes.c_int32(v.val & 0xFFFFFFFF).value
    if vt == 19:           # VT_UI4
        return v.val & 0xFFFFFFFF
    if vt == 11:           # VT_BOOL
        return (v.val & 0xFFFF) != 0
    if vt == 8:            # VT_BSTR
        p = v.val
        return ctypes.wstring_at(p, oleaut32.SysStringLen(p)) if p else ""
    if vt == 20 or vt == 37:  # VT_I8 / VT_INT_PTR
        return v.val
    return None


class Element(_Com):
    __slots__ = ()

    # IUIAutomationElement slots
    def prop(self, pid, cached=False):
        v = VARIANT()
        self.call(12 if cached else 10, ctypes.c_int(pid), ctypes.byref(v))
        try:
            return _variant_value(v)
        finally:
            oleaut32.VariantClear(ctypes.byref(v))

    def rect(self, cached=False):
        r = RECT()
        self.call(75 if cached else 43, ctypes.byref(r))
        return r.t()

    def pattern(self, pat):
        o = self.out(16, ctypes.c_int(pat))
        return _Com(o) if o else None

    def find_all(self, scope, cond, cache=None):
        if cache is not None:
            arr = self.out(8, ctypes.c_int(scope), ctypes.c_void_p(cond.p), ctypes.c_void_p(cache.p))
        else:
            arr = self.out(6, ctypes.c_int(scope), ctypes.c_void_p(cond.p))
        return _elements(arr)


def _elements(arr):
    if not arr:
        return []
    a = _Com(arr)
    n = ctypes.c_int()
    a.call(3, ctypes.byref(n))
    return [Element(a.out(4, ctypes.c_int(i))) for i in range(n.value)]


class UIA:
    """Per-thread IUIAutomation + the few conditions / cache requests used."""
    _tls = threading.local()

    @classmethod
    def get(cls):
        u = getattr(cls._tls, "uia", None)
        if u is None:
            u = cls._tls.uia = cls()
        return u

    def __init__(self):
        ensure_dpi_awareness()
        ole32.CoInitializeEx(None, 0)  # MTA; S_FALSE / RPC_E_CHANGED_MODE are fine
        p = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(CLSID_CUIAutomation), None, 1,  # INPROC_SERVER
                                    ctypes.byref(IID_IUIAutomation), ctypes.byref(p))
        if hr < 0:
            raise UIAError("CoCreateInstance(CUIAutomation) failed: 0x%08X" % (hr & 0xFFFFFFFF))
        self.a = _Com(p.value)
        self.true = _Com(self.a.out(21))
        # One cache request: everything the walk needs, fetched with the
        # children in ONE cross-process round trip per node.
        self.cache = _Com(self.a.out(20))
        for pid in (P_CONTROLTYPE, P_NAME, P_CLASSNAME, P_ISSELECTED, P_LEGACYSTATE, P_OFFSCREEN, P_HWND):
            self.cache.call(3, ctypes.c_int(pid))
        self.cache.call(4, ctypes.c_int(PAT_SELITEM))
        self.cache.call(4, ctypes.c_int(PAT_LEGACY))
        # IUIAutomationCacheRequest: 75 = cached BoundingRectangle needs the property cached
        self.cache.call(3, ctypes.c_int(30001))

    def from_hwnd(self, hwnd):
        return Element(self.a.out(6, ctypes.c_void_p(hwnd)))

    def children(self, el):
        return el.find_all(SCOPE_CHILDREN, self.true, self.cache)


# ------------------------------------------------------------ tab walk ---
_MAX_DEPTH = 14


def _find_tabstrip(u, root, deadline, enter_docs=False):
    """Breadth-first walk of the browser's OWN UI (never descends into a
    Document = web content, so page role=tab widgets are ignored and Chrome is
    not asked for the page's accessibility tree).  Returns (tab items list,
    documents seen) -- tab items in on-screen order."""
    level, depth, docs = [root], 0, []
    while level and depth < _MAX_DEPTH and time.monotonic() < deadline:
        nxt = []
        for el in level:
            try:
                kids = u.children(el)
            except UIAError:
                continue
            for k in kids:
                ct = k.prop(P_CONTROLTYPE, True)
                if ct == CT_DOCUMENT:
                    docs.append(k)
                    if not enter_docs:
                        continue
                if ct == CT_TAB:
                    items = _tabitems(u, k, deadline)
                    if items:
                        return items, docs
                nxt.append(k)
        level, depth = nxt, depth + 1
    return [], docs


def _tabitems(u, tabctl, deadline, depth=0):
    """TabItems under a Tab control, in order; descends into tab groups
    (Chromium) but not into TabItems themselves."""
    out = []
    try:
        kids = u.children(tabctl)
    except UIAError:
        return out
    for k in kids:
        ct = k.prop(P_CONTROLTYPE, True)
        if ct == CT_TABITEM:
            out.append(k)
        elif ct != CT_DOCUMENT and depth < 3 and time.monotonic() < deadline:
            out.extend(_tabitems(u, k, deadline, depth + 1))
    return out


def _is_selected(el):
    try:
        v = el.prop(P_ISSELECTED, True)
        if v is not None:
            return bool(v)
    except UIAError:
        pass
    try:
        st = el.prop(P_LEGACYSTATE, True)
        return bool((st or 0) & 0x2)  # STATE_SYSTEM_SELECTED
    except UIAError:
        return False


# Chromium appends state to a tab's accessible name (English UI shown; other
# UI languages keep their suffix -- `name` always carries the raw string).
_SUFFIX = re.compile(r"( - (Memory usage - [\d.,]+ ?[KMG]B|Audio playing|Audio muted|Muted|Pinned|"
                     r"Network error|Crashed|Camera( or microphone)? recording|Microphone recording|"
                     r"Sharing (your screen|window|tab)( contents)?|Connected to (a )?[^-]+device|"
                     r"Bluetooth device connected|Loading|Unresponsive|"
                     r"(High|Medium|Low) memory usage|Part of group [^-]+|Page is in Picture-in-picture))+$")


def clean_title(name):
    return _SUFFIX.sub("", name or "")


def _window_tabs(u, hwnd, deadline, engine=None):
    root = u.from_hwnd(hwnd)
    items, _ = _find_tabstrip(u, root, deadline)
    if not items and engine == "firefox" and time.monotonic() < deadline:
        # UNVERIFIED (no Firefox on the test box): should Firefox expose its
        # XUL chrome as a Document, look inside Documents too; BFS still
        # meets the shallow tab strip before any page-level tablist.
        items, _ = _find_tabstrip(u, root, deadline, enter_docs=True)
    tabs = []
    for i, it in enumerate(items):
        try:
            name = it.prop(P_NAME, True) or ""
        except UIAError:
            name = ""
        tabs.append({"index": i, "title": clean_title(name), "name": name,
                     "active": _is_selected(it), "_el": it})
    return tabs


def list_windows(exclude_pids=(), budget=1.5):
    """One dict per browser window:
    {hwnd, browser, engine, pid, window_title, minimized, cloaked, frame, tabs:[...]}.
    Windows with no tab strip (apps, popups, PWAs) come back with tabs == []."""
    u = UIA.get()
    t_end = time.monotonic() + budget
    wins = []
    for hwnd, eng, br, pid in browser_windows(exclude_pids):
        per = max(0.25, (t_end - time.monotonic()))
        try:
            tabs = _window_tabs(u, hwnd, time.monotonic() + per, eng)
        except UIAError:
            tabs = []
        for t in tabs:
            t.pop("_el", None)
        wins.append({"hwnd": hwnd, "browser": br, "engine": eng, "pid": pid,
                     "window_title": _text(hwnd), "minimized": bool(user32.IsIconic(hwnd)),
                     "cloaked": _cloaked(hwnd), "frame": frame_bounds(hwnd), "tabs": tabs})
    return wins


def list_tabs(exclude_pids=(), budget=1.5):
    """Flat list, one dict per tab:
    {id "<hwnd>:<index>", hwnd, browser, pid, title, active, index,
     window_title, minimized, cloaked}."""
    out = []
    for w in list_windows(exclude_pids, budget):
        for t in w["tabs"]:
            out.append({"id": "%d:%d" % (w["hwnd"], t["index"]), "hwnd": w["hwnd"],
                        "browser": w["browser"], "pid": w["pid"], "title": t["title"],
                        "active": t["active"], "index": t["index"],
                        "window_title": w["window_title"], "minimized": w["minimized"],
                        "cloaked": w["cloaked"]})
    return out


_ACTIVATE = {  # name -> (pattern, vtable slot, extra args)
    "select": (PAT_SELITEM, 3, ()),                        # SelectionItem.Select
    "legacy-select": (PAT_LEGACY, 3, (ctypes.c_long(2),)),  # accSelect(TAKESELECTION)
    "legacy-default": (PAT_LEGACY, 4, ()),                  # accDoDefaultAction
    "invoke": (PAT_INVOKE, 3, ()),                          # Invoke
}
# legacy (MSAA accSelect / accDoDefaultAction) first: measured on Chromium, they
# switch the tab WITHOUT activating the window; UIA Select foregrounds it.
ACTIVATE_ORDER = ("legacy-select", "legacy-default", "select", "invoke")


def activate_tab(hwnd, which, timeout=1.0, methods=ACTIVATE_ORDER):
    """Bring tab `which` (int index, or exact/substring title) to the front of
    window `hwnd`, trying `methods` in order and confirming each by
    re-reading the tab's selection.  Never calls SetForegroundWindow itself,
    but Chromium activates its window when a tab is selected this way (see
    README); returns {ok, method, index, title, foreground_changed}."""
    u = UIA.get()
    fg0 = user32.GetForegroundWindow()
    tabs = _window_tabs(u, hwnd, time.monotonic() + 2.0)
    tab = None
    if isinstance(which, int) or (isinstance(which, str) and which.isdigit()):
        i = int(which)
        tab = tabs[i] if 0 <= i < len(tabs) else None
    else:
        tab = next((t for t in tabs if t["title"] == which), None) or \
            next((t for t in tabs if which.lower() in t["title"].lower()), None)
    if tab is None:
        return {"ok": False, "error": "no such tab", "count": len(tabs)}
    if tab["active"]:
        return {"ok": True, "method": "already", "index": tab["index"], "title": tab["title"],
                "foreground_changed": False}
    el = tab["_el"]
    method = None
    for name in methods:
        pat, slot, extra = _ACTIVATE[name]
        try:
            p = el.pattern(pat)
            if not p:
                continue
            p.call(slot, *extra)
        except UIAError:
            continue
        method = name
        t_end = time.monotonic() + timeout
        ok = False
        while time.monotonic() < t_end:
            try:
                ok = bool(el.prop(P_ISSELECTED))
            except UIAError:
                ok = False
            if ok:
                break
            time.sleep(0.03)
        if ok:
            break
    else:
        ok = False
    return {"ok": bool(method) and ok, "method": method, "index": tab["index"], "title": tab["title"],
            "foreground_changed": user32.GetForegroundWindow() != fg0}


# ---------------------------------------------------------------- crop ---
def _visible_child_rects(hwnd, cls):
    out = []
    for c in _child_windows(hwnd):
        if _cls(c) == cls and user32.IsWindowVisible(c):
            r = RECT()
            user32.GetWindowRect(c, ctypes.byref(r))
            if r.right > r.left and r.bottom > r.top:
                out.append(r.t())
    return out


def _area(r):
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def content_rect(hwnd):
    """Screen rect (physical px) of the web page area, plus how it was found."""
    ensure_dpi_awareness()
    # Chromium: the page's legacy child HWND sits exactly over the content.
    rects = _visible_child_rects(hwnd, "Chrome_RenderWidgetHostHWND")
    if rects:
        return max(rects, key=_area), "Chrome_RenderWidgetHostHWND"
    # Firefox (no content HWND) and fallback: the largest on-screen Document
    # among the browser UI's direct Documents (the walk never enters them).
    docs = _ui_documents(UIA.get(), hwnd)
    best = None
    for d in docs:
        try:
            if d.prop(P_OFFSCREEN, True):
                continue
            r = d.rect(True)
        except UIAError:
            continue
        if _area(r) and (best is None or _area(r) > _area(best)):
            best = r
    return best, ("uia-document" if best else None)


def _ui_documents(u, hwnd):
    """Walk the whole browser UI (not entering Documents or the tab strip)
    collecting the Documents it hangs off."""
    root = u.from_hwnd(hwnd)
    level, depth, docs = [root], 0, []
    deadline = time.monotonic() + 2.0
    while level and depth < _MAX_DEPTH and time.monotonic() < deadline:
        nxt = []
        for el in level:
            try:
                kids = u.children(el)
            except UIAError:
                continue
            for k in kids:
                ct = k.prop(P_CONTROLTYPE, True)
                if ct == CT_DOCUMENT:
                    docs.append(k)
                elif ct != CT_TAB:
                    nxt.append(k)
        level, depth = nxt, depth + 1
    return docs


# Pixels (in DIPs) the browser paints over the edge of its content HWND,
# measured with a 6-px red page border at 125 %:
#   chrome: the 1-DIP toolbar separator covers the first content row
#   msedge: a 1-DIP outline of the rounded content frame on top + left
#   brave : exact on all four sides
TRIM_DIP = {"chrome": (0, 1, 0, 0), "msedge": (1, 1, 0, 0)}


def content_crop(hwnd, capture_border=False, trim=None):
    """gfxcapture crop for window `hwnd`: pixels to remove from each side of
    the captured image so only the web page is left.

    Reference rectangle = what gfxcapture actually captures:
      capture_border=False (ffmpeg's default) -> the CLIENT area
      capture_border=True                     -> DWMWA_EXTENDED_FRAME_BOUNDS
    trim: extra (left, top, right, bottom) px to drop inside the content rect;
    None = the per-browser table TRIM_DIP (measured, see README).
    Returns {left, top, right, bottom, ref, frame, client, content, source,
    dpi} (all physical px) or None when no content area was found."""
    ensure_dpi_awareness()
    fr = frame_bounds(hwnd)
    cl = client_bounds(hwnd)
    if capture_border:
        ref = fr
    else:  # the capture is the client area clipped to the visible frame
        ref = (max(cl[0], fr[0]), max(cl[1], fr[1]), min(cl[2], fr[2]), min(cl[3], fr[3]))
    cr, src = content_rect(hwnd)
    if not cr:
        return None
    dpi = user32.GetDpiForWindow(wt.HWND(hwnd)) or 96
    if trim is None:
        br = BROWSERS.get(os.path.basename(_exe(_pid(wt.HWND(hwnd)))).lower(), "")
        trim = tuple(n and max(n, round(n * dpi / 96)) for n in TRIM_DIP.get(br, (0, 0, 0, 0)))
    cr = (cr[0] + trim[0], cr[1] + trim[1], cr[2] - trim[2], cr[3] - trim[3])
    c = (max(cr[0], ref[0]), max(cr[1], ref[1]), min(cr[2], ref[2]), min(cr[3], ref[3]))
    return {"left": c[0] - ref[0], "top": c[1] - ref[1], "right": ref[2] - c[2], "bottom": ref[3] - c[3],
            "capture_border": bool(capture_border), "ref": ref, "frame": fr, "client": cl, "content": cr,
            "source": src, "dpi": dpi}


def gfxcapture_args(hwnd, crop=None):
    """The gfxcapture source string KASTR would pass to ffmpeg."""
    crop = crop or content_crop(hwnd) or {"left": 0, "top": 0, "right": 0, "bottom": 0}
    return "gfxcapture=hwnd=%d:capture_border=%d:crop_left=%d:crop_top=%d:crop_right=%d:crop_bottom=%d" % (
        hwnd, 1 if crop.get("capture_border") else 0, crop["left"], crop["top"], crop["right"], crop["bottom"])


# ----------------------------------------------------------------- CLI ---
def _main(argv):
    import json
    ensure_dpi_awareness()
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--list":
        t0 = time.perf_counter()
        wins = list_windows()
        dt = time.perf_counter() - t0
        if "--json" in argv:  # still no titles: lengths only
            for w in wins:
                w["window_title"] = len(w["window_title"])
                for t in w["tabs"]:
                    t["title"] = len(t["title"])
            print(json.dumps({"seconds": round(dt, 3), "windows": wins}, indent=1))
            return 0
        print("dpi awareness: %s   listing took %.0f ms" % (dpi_awareness(), dt * 1000))
        by = {}
        for w in wins:
            by.setdefault(w["browser"], []).append(w)
        for br, ws in sorted(by.items()):
            n = sum(len(w["tabs"]) for w in ws)
            print("%-8s %d window(s), %d tab(s)" % (br, len(ws), n))
            for w in ws:
                lens = [len(t["title"]) for t in w["tabs"]]
                act = [t["index"] for t in w["tabs"] if t["active"]]
                flags = ",".join(f for f, on in (("minimized", w["minimized"]), ("cloaked", w["cloaked"])) if on)
                print("   hwnd=%-9d pid=%-6d tabs=%-3d active=%s title_len=%d %s frame=%s%s" % (
                    w["hwnd"], w["pid"], len(w["tabs"]), act, len(w["window_title"]),
                    "tab_title_lens=%s" % lens, w["frame"], (" [" + flags + "]") if flags else ""))
        return 0
    if argv[0] == "--crop" and len(argv) > 1:
        h = int(argv[1], 0)
        t0 = time.perf_counter()
        c = content_crop(h)
        print(json.dumps(c), "  (%.0f ms)" % ((time.perf_counter() - t0) * 1000))
        if c:
            print(gfxcapture_args(h, c))
        return 0 if c else 1
    if argv[0] == "--activate" and len(argv) > 2:
        t0 = time.perf_counter()
        r = activate_tab(int(argv[1], 0), argv[2])
        r.pop("title", None)
        print(json.dumps(r), "  (%.0f ms)" % ((time.perf_counter() - t0) * 1000))
        return 0 if r.get("ok") else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
