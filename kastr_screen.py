"""Native screen / window sharing on the host (0.21.20, Windows first).

The page's Share panel lists every screen and window with live thumbnails (GET /api/screen/sources and
/api/screen/thumb, loopback only) and shares one with a single click as a screen:// feed on the RTSP machinery
(kastr_rtsp): ffmpeg's gfxcapture (Windows Graphics Capture) scaled at capture to fit 1920x1080, a constant 30 fps,
one hardware (or x264) encode, `moq import` -- no browser picker and no browser encode. "Include sound" adds the
computer's sound through process loopback that leaves out this host's own tree (its browser plays the room), so
viewers never hear themselves (kastr_loopback). While a share is on air a red border frames the shared screen or
window and a draggable bar offers Stop sharing (kastr_overlay); neither shows up in the capture.

  screen://monitor/<n>    the n-th screen of /api/screen/sources (primary first, then left to right)
  screen://window/<hwnd>  one top-level window
  screen://tab/<hwnd>/<i> tab i of a browser window (0.21.22): brought to the front of its window, the window captured
                          cropped to the web page (kastr_tabs)
"""
import os
import re
import sys
import threading
import time

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")
_x11grab = None   # 0.21.79: does this ffmpeg have x11grab (asked once)
MAX_W, MAX_H, FPS = 1920, 1080, 30
# 0.21.83 (D) (Kenton: "allow for switching to different windows/monitors on the device"): screen://monitor/99 = EVERY monitor
# at once (a fleet admin's private capture of an unattended machine) -- their union: x11grab of that rectangle on Linux, GDI's
# whole virtual desktop on Windows (Windows Graphics Capture takes one monitor or one window), scaled to MAX_W by the publisher
ALL_MONITORS = 99
RC_FPS = int(os.environ.get("KASTR_RC_FPS") or 30)   # 0.21.80: the frame rate while someone controls the share (kastr_rtsp.rc_screen_opts)
# the computer's sound: s16le PCM on ffmpeg's stdin. kastr_loopback writes it in real time and pads silence, so the
# sample count IS the clock -- timestamps from 0 like the capture's (wall-clock stamps put the audio ~50 years ahead)
LOOPBACK_INPUT = ["-thread_queue_size", "1024", "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", "pipe:0"]
_URL_RE = re.compile(r"^screen://(monitor|window|tab)/(\d{1,20})(?:/(\d{1,4}))?$", re.I)

_src = None


def _sources_mod():
    """kastr_screen_sources with the bundled ffmpeg (its own default is KASTR_FFMPEG or none)."""
    global _src
    if _src is None:
        import kastr_screen_sources as m
        try:
            import kastr_rtsp
            ff = kastr_rtsp.find_ffmpeg()
            if ff:
                m.FFMPEG = ff
        except Exception:
            pass
        _src = m
    return _src


def _ffmpeg():
    try:
        import kastr_rtsp
        return kastr_rtsp.find_ffmpeg() or "ffmpeg"
    except Exception:
        return "ffmpeg"


def linux_available():
    """0.21.79 (Kenton: remote control on "Linux X11"): native screen / window sharing on an X11 desktop -- ffmpeg's x11grab
    (the bundled static Linux ffmpeg has it). Never on Wayland (kastr_x11.session_kind), never without a display;
    KASTR_NATIVE_SCREEN=0 keeps the browser's picker."""
    global _x11grab
    if not LINUX or os.environ.get("KASTR_NATIVE_SCREEN") == "0":
        return False
    try:
        import kastr_x11
        if kastr_x11.session_kind() != "x11":
            return False
        with kastr_x11.Display():
            pass
    except Exception:
        return False
    if _x11grab is None:
        import subprocess
        try:
            r = subprocess.run([_ffmpeg(), "-hide_banner", "-devices"], capture_output=True, text=True, timeout=10)
            _x11grab = "x11grab" in (r.stdout or "")
        except Exception:
            _x11grab = False
    return bool(_x11grab)


def available():
    """Native capture works on Windows 10 1903+ with the bundled ffmpeg (gfxcapture); 0.21.79: and on Linux X11 (x11grab)."""
    if LINUX:
        return linux_available()
    if not WINDOWS:
        return False
    try:
        return bool(_sources_mod())
    except Exception:
        return False


def parse_url(url):
    m = _URL_RE.match(str(url or "").strip())
    if not m or (m.group(1).lower() == "tab") != (m.group(3) is not None):
        raise ValueError("screen urls are screen://monitor/<n>, screen://window/<hwnd> or screen://tab/<hwnd>/<index>")
    return m.group(1).lower(), int(m.group(2))


def tab_index(url):
    m = _URL_RE.match(str(url or "").strip())
    return int(m.group(3)) if m and m.group(3) is not None else 0


def _window_ready(hwnd):
    """0.21.26: a MINIMIZED window has no size and paints nothing, so its capture failed until it was maximized.
    Show it again without activating it (it stays behind whatever has focus), then let it lay itself out."""
    import ctypes
    u32 = ctypes.windll.user32
    if not u32.IsWindow(hwnd):
        raise ValueError("that window is no longer there")
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
        for _ in range(20):         # up to ~1 s for the restore animation + first paint
            time.sleep(0.05)
            if not u32.IsIconic(hwnd):
                break
        time.sleep(0.25)


def _tab_ready(hwnd, index):
    """Bring tab `index` to the front of its window (never stealing focus) and un-minimize the window without
    activating it -- a minimized Chromium window paints nothing."""
    import ctypes
    import kastr_tabs
    u32 = ctypes.windll.user32
    if not u32.IsWindow(hwnd):
        raise ValueError("that browser window is gone")
    r = kastr_tabs.activate_tab(hwnd, index)
    if not (r or {}).get("ok"):
        raise ValueError("could not bring that tab to the front")
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE


def check_url(url):
    if LINUX and linux_available():   # 0.21.79
        kind, n = parse_url(url)
        if kind == "tab":
            raise ValueError("sharing one browser tab natively needs Windows -- share its window instead")
        if not _resolve(kind, n):
            raise ValueError("that %s is no longer there" % ("screen" if kind == "monitor" else "window"))
        return
    if not WINDOWS:
        raise ValueError("native screen sharing needs Windows on this computer -- use Share content in a browser instead")
    kind, n = parse_url(url)
    if kind == "tab":
        _tab_ready(n, tab_index(url))
        return
    if kind == "window":
        _window_ready(n)   # 0.21.26 (Kenton: "an error on sharing a window until I maximized the window")
    if not _resolve(kind, n):
        raise ValueError("that %s is no longer there" % ("screen" if kind == "monitor" else "window"))


def _resolve(kind, n):
    """The live source dict behind a url (monitor by index, window by handle) or None."""
    if kind == "monitor" and n == ALL_MONITORS:   # 0.21.83 (D)
        return all_monitors()
    if LINUX:   # 0.21.79: X11 -- screens by index (RandR), windows by X window id
        import kastr_x11
        if kind == "monitor":
            return next((s for s in kastr_x11.list_monitors() if s.get("index") == n), None)
        r = kastr_x11.window_rect(n)
        return {"hwnd": n, "rect": {"x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]}, "width": r["w"], "height": r["h"]} if r else None
    m = _sources_mod()
    if kind == "monitor":
        for s in m.list_monitors():
            if s.get("index") == n:
                return s
        return None
    for s in m.list_windows(exclude_pids=()):
        if int(s.get("hwnd") or 0) == n:
            return s
    return None


def all_monitors():
    """0.21.83 (D): every monitor at once as one source {index: ALL_MONITORS, name, rect {x, y, w, h}, width, height}, or None."""
    try:
        if LINUX:
            import kastr_x11
            mons = kastr_x11.list_monitors()
        else:
            mons = _sources_mod().list_monitors()
    except Exception:
        return None
    rs = [m.get("rect") for m in mons if isinstance(m.get("rect"), dict) and m["rect"].get("w") and m["rect"].get("h")]
    if not rs:
        return None
    x0, y0 = min(r["x"] for r in rs), min(r["y"] for r in rs)
    x1, y1 = max(r["x"] + r["w"] for r in rs), max(r["y"] + r["h"] for r in rs)
    return {"index": ALL_MONITORS, "name": "All monitors", "rect": {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0},
            "width": x1 - x0, "height": y1 - y0, "all": True, "count": len(rs)}


def identity(url):
    """0.21.26 (Kenton: "reconnect a desktop, tab, window share when still available after a relaunch of KASTR"): what is
    needed to find the shared thing again after KASTR restarts -- handles survive a KASTR restart (the window's own process
    keeps it), but a window or tab may have been closed and reopened under a new handle."""
    try:
        kind, n = parse_url(url)
    except ValueError:
        return None
    try:
        if kind == "monitor":
            src = _resolve(kind, n) or {}
            return {"kind": kind, "index": n, "device": src.get("device") or ""}
        if kind == "window":
            src = _resolve(kind, n) or {}
            return {"kind": kind, "hwnd": n, "exe": src.get("exe") or "", "title": src.get("title") or ""}
        import kastr_tabs
        idx = tab_index(url)
        t = next((t for t in kastr_tabs.list_tabs(budget=1.5) if t["hwnd"] == n and t["index"] == idx), None) or {}
        return {"kind": kind, "hwnd": n, "index": idx, "title": t.get("title") or "", "browser": t.get("browser") or ""}
    except Exception:
        return {"kind": kind}


def relocate(url, ident):
    """0.21.26: the screen:// url to share after a relaunch, or None when the thing is gone (the share is then dropped).
    A screen: the same index. A window: the same handle when it still exists, else a window of the same program with the
    same title. A tab: the same browser window + the tab of the same title (its position may have moved), else that title
    in any browser window."""
    if not WINDOWS:
        return None
    try:
        kind, n = parse_url(url)
    except ValueError:
        return None
    ident = ident if isinstance(ident, dict) else {}
    try:
        if kind == "monitor":
            return url if _resolve(kind, n) else None
        if kind == "window":
            wins = _sources_mod().list_windows(exclude_pids=())
            if any(int(w.get("hwnd") or 0) == n for w in wins):
                return url
            title, exe = ident.get("title") or "", (ident.get("exe") or "").lower()
            if title:
                for w in wins:
                    if (w.get("title") or "") == title and (not exe or (w.get("exe") or "").lower() == exe):
                        return "screen://window/%d" % int(w["hwnd"])
            return None
        import kastr_tabs
        title = ident.get("title") or ""
        tabs = kastr_tabs.list_tabs(budget=2.0)
        same = [t for t in tabs if t["hwnd"] == n]
        if not title:   # nothing to match by: the same position in the same window, if that window is still there
            idx = tab_index(url)
            return url if any(t["index"] == idx for t in same) else None
        for pool in (same, [t for t in tabs if not ident.get("browser") or t.get("browser") == ident.get("browser")], tabs):
            t = next((t for t in pool if (t.get("title") or "") == title), None)
            if t:
                return "screen://tab/%d/%d" % (t["hwnd"], t["index"])
        return None
    except Exception:
        return None


def _fit(w, h):
    w, h = max(2, int(w or MAX_W)), max(2, int(h or MAX_H))
    k = min(1.0, MAX_W / w, MAX_H / h)
    return max(2, int(w * k) // 2 * 2), max(2, int(h * k) // 2 * 2)


def _tab_crop(hwnd):
    import kastr_tabs
    crop = kastr_tabs.content_crop(hwnd) or {"left": 0, "top": 0, "right": 0, "bottom": 0}
    cl = kastr_tabs.client_bounds(hwnd)
    w = max(2, (cl[2] - cl[0]) - crop["left"] - crop["right"])
    h = max(2, (cl[3] - cl[1]) - crop["top"] - crop["bottom"])
    return crop, w, h


def capture_size(url):
    kind, n = parse_url(url)
    if kind == "monitor" and n == ALL_MONITORS:   # 0.21.83 (D): the raw union -- the publisher scales it to MAX_W (Publisher `wide`)
        src = all_monitors() or {}
        return max(2, int(src.get("width") or MAX_W) // 2 * 2), max(2, int(src.get("height") or MAX_H) // 2 * 2)
    if kind == "tab":
        _, w, h = _tab_crop(n)
        return _fit(w, h)
    src = _resolve(kind, n) or {}
    r = src.get("rect") or {}
    w = src.get("width") or (r.get("right", 0) - r.get("left", 0)) or (r.get("w") if isinstance(r, dict) else 0)
    h = src.get("height") or (r.get("bottom", 0) - r.get("top", 0)) or (r.get("h") if isinstance(r, dict) else 0)
    return _fit(w, h)


def _clocked(cap, w, h, fps=FPS):
    """A steady 30 fps whatever the capture does: Windows Graphics Capture sends a frame only when the window repaints,
    and fps= releases frames only as newer ones arrive -- a still page sent nothing at all (lab 2026-10-06). A black
    clock at 30 fps carries the capture on top and repeats its last frame, so a still screen, window or tab keeps
    sending frames (and keyframes to late joiners) once its first frame is in."""
    return ("color=c=black:s=%dx%d:r=%d[kbg];%s,format=yuv420p[kfg];[kbg][kfg]overlay=eof_action=repeat:repeatlast=1:shortest=0,setsar=1"
            % (w, h, fps, cap))


def kick(url):
    """Make the shared thing repaint once so the capture gets its first frame (a still page never sends one): a tab
    -> another tab of its window and straight back; a browser window -> the same on its active tab; another window ->
    a redraw request; a screen -> the cursor one pixel over and back (the capture draws the cursor)."""
    import ctypes
    try:
        kind, n = parse_url(url)
        u32 = ctypes.windll.user32
        if kind in ("tab", "window"):
            import kastr_tabs
            win = next((w for w in kastr_tabs.list_windows(budget=0.8) if w["hwnd"] == n), None)
            tabs = (win or {}).get("tabs") or []
            idx = tab_index(url) if kind == "tab" else next((t["index"] for t in tabs if t.get("active")), None)
            other = next((t["index"] for t in tabs if t["index"] != idx), None)
            if idx is not None and other is not None:
                kastr_tabs.activate_tab(n, other)
                time.sleep(0.08)
                kastr_tabs.activate_tab(n, idx)
                return
            u32.RedrawWindow(n, None, None, 0x0001 | 0x0080 | 0x0100 | 0x0400)   # INVALIDATE|ALLCHILDREN|UPDATENOW|FRAME
            return

        class PT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        p = PT()
        if u32.GetCursorPos(ctypes.byref(p)):
            u32.SetCursorPos(p.x + 1, p.y)
            u32.SetCursorPos(p.x, p.y)
    except Exception:
        pass


def _kick_soon(url):
    for delay in (1.0, 3.0):   # the capture opens ~0.5-1 s after ffmpeg starts
        t = threading.Timer(delay, kick, args=(url,))
        t.daemon = True
        t.start()


def capture_input(url, cursor=True, fps=None):
    """ffmpeg input args for a screen:// url: gfxcapture scaled at capture (aspect kept), CPU frames, a steady 30 fps
    (see _clocked), plus two repaint kicks so the first frame arrives even on a still page.
    0.21.80 (Kenton: "show my mouse with my name for the viewers"): cursor=False while someone remote-controls the share --
    the real cursor is left out of the picture (gfxcapture capture_cursor=0, x11grab -draw_mouse 0) because every viewer draws
    both people's pointers with their names from the share's ptr.json; fps = RC_FPS then."""
    kind, n = parse_url(url)
    fps = int(fps or FPS)
    cur = 1 if cursor else 0
    if LINUX:   # 0.21.79: x11grab -- a screen by its rectangle, a window by its id (followed as it moves)
        disp = os.environ.get("DISPLAY") or ":0"
        if kind == "window":
            return ["-f", "x11grab", "-framerate", str(fps), "-draw_mouse", str(cur), "-window_id", str(n), "-i", disp]
        r = (_resolve(kind, n) or {}).get("rect") or {"x": 0, "y": 0, "w": MAX_W, "h": MAX_H}
        return ["-f", "x11grab", "-framerate", str(fps), "-draw_mouse", str(cur), "-video_size",
                "%dx%d" % (max(2, int(r["w"]) // 2 * 2), max(2, int(r["h"]) // 2 * 2)), "-i", "%s+%d,%d" % (disp, int(r["x"]), int(r["y"]))]
    if kind == "monitor" and n == ALL_MONITORS:   # 0.21.83 (D): GDI's whole virtual desktop (gfxcapture takes one monitor)
        return ["-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", str(cur), "-i", "desktop"]
    _kick_soon(url)
    if kind == "tab":   # crop on the GPU side of the capture, then scale on the CPU (a crop + resize_mode order is not documented)
        import kastr_tabs
        crop, cw, ch = _tab_crop(n)
        w, h = _fit(cw, ch)
        cap = (kastr_tabs.gfxcapture_args(n, crop) + ":max_framerate=%d:capture_cursor=%d,hwdownload,format=bgra,"
               "scale=%d:%d:flags=bilinear" % (fps, cur, w, h))
        return ["-f", "lavfi", "-i", _clocked(cap, w, h, fps)]
    src = _resolve(kind, n) or {}
    w, h = capture_size(url)
    target = ("hmonitor=%d" % int(src.get("hmonitor") or 0)) if kind == "monitor" and src.get("hmonitor") \
        else ("monitor_idx=%d" % n) if kind == "monitor" else ("hwnd=%d" % n)
    cap = ("gfxcapture=%s:max_framerate=%d:width=%d:height=%d:resize_mode=scale_aspect:capture_cursor=%d,"
           "hwdownload,format=bgra,scale=%d:%d" % (target, fps, w, h, cur, w, h))
    return ["-f", "lavfi", "-i", _clocked(cap, w, h, fps)]


def feed_loopback(ff, exclude_pid=None, log=None):
    """Write the computer's sound (everything but this host's own process tree) into ffmpeg's stdin until it ends.
    Falls back to the device loopback (which also carries the room) only when process loopback is unavailable."""
    def run():
        cap = None
        try:
            import kastr_loopback
            sink = ff.stdin.write
            try:
                cap = kastr_loopback.LoopbackCapture(exclude_pid=exclude_pid)
                cap.start(sink=sink)
            except Exception as e:
                if log:
                    log("screen: process loopback unavailable (%s) -- device loopback (the room's sound is included)" % e)
                cap = kastr_loopback.LoopbackCapture()
                cap.start(sink=sink)
            while ff.poll() is None and not cap._stop.is_set() and cap._thread and cap._thread.is_alive():
                time.sleep(0.5)
        except Exception as e:
            if log:
                log("screen: sound capture ended: %s" % e)
        finally:
            try:
                if cap:
                    cap.stop()
            except Exception:
                pass
            try:
                ff.stdin.close()
            except Exception:
                pass
    threading.Thread(target=run, name="screen-sound", daemon=True).start()


# ---- the page's picker --------------------------------------------------------------------------------------------
_thumb_cache = {}          # (id, width) -> (time, bytes, mime)
_thumb_lock = threading.Lock()
THUMB_TTL = 1.2


def sources(exclude_pids=(), tabs=False):
    """JSON for /api/screen/sources: screens first (primary, then left to right), then windows in Z-order."""
    if not available():
        return {"ok": False, "reason": "native screen sharing needs Windows (or a Linux X11 desktop)"}
    if LINUX:   # 0.21.79
        import kastr_x11
        own = {os.getpid()} | set(int(p) for p in exclude_pids or ())
        screens = [{"id": "monitor:%d" % s["index"], "kind": "screen", "index": s["index"], "name": s["name"], "primary": bool(s.get("primary")),
                    "width": s["width"], "height": s["height"]} for s in kastr_x11.list_monitors()]
        windows = [{"id": w["id"], "kind": "window", "hwnd": w["hwnd"], "title": w["title"], "exe": w.get("exe") or "",
                    "minimized": bool(w.get("minimized"))} for w in kastr_x11.list_windows(exclude_pids=tuple(own))]
        return {"ok": True, "screens": screens, "windows": windows, "x11": True}
    m = _sources_mod()
    own = {os.getpid()} | set(int(p) for p in exclude_pids or ())
    screens, windows = [], []
    for s in m.list_monitors():
        screens.append({"id": "monitor:%d" % s["index"], "kind": "screen", "index": s["index"],
                        "name": s.get("name") or "Screen %d" % (s["index"] + 1), "primary": bool(s.get("primary")),
                        "width": s.get("width"), "height": s.get("height")})
    for s in m.list_windows(exclude_pids=tuple(own)):
        windows.append({"id": "window:%d" % s["hwnd"], "kind": "window", "hwnd": s["hwnd"], "title": s.get("title") or "",
                        "exe": s.get("exe") or "", "minimized": bool(s.get("minimized"))})
    out = {"ok": True, "screens": screens, "windows": windows}
    if tabs:   # 0.21.22: only while the panel's Tab list is open (UI Automation, ~0.1 s)
        out["tabs"] = []
        try:
            import kastr_tabs
            for t in kastr_tabs.list_tabs(exclude_pids=tuple(own), budget=1.2):
                if t.get("cloaked"):
                    continue
                out["tabs"].append({"id": "tab:%d:%d" % (t["hwnd"], t["index"]), "kind": "tab", "hwnd": t["hwnd"], "index": t["index"],
                                    "title": t.get("title") or "", "browser": t.get("browser") or "", "active": bool(t.get("active")),
                                    "minimized": bool(t.get("minimized"))})
        except Exception as e:
            out["tabsError"] = str(e)[:120]
    return out


def thumb(source_id, width=320):
    """(bytes, mime) for /api/screen/thumb, cached for a moment (several viewers of the panel, one capture), or None."""
    if not available():
        return None
    width = max(80, min(640, int(width or 320)))
    key = (str(source_id), width)
    now = time.time()
    with _thumb_lock:
        hit = _thumb_cache.get(key)
        if hit and now - hit[0] < THUMB_TTL:
            return hit[1], hit[2]
    kind, _, n = str(source_id).partition(":")
    if kind not in ("monitor", "window") or not n.isdigit():
        return None
    src = _resolve(kind, int(n))
    if not src:
        return None
    if LINUX:   # 0.21.79: one x11grab frame
        import kastr_x11
        data = kastr_x11.grab_jpeg(src.get("rect") or {}, width=width, ffmpeg=_ffmpeg())
        out = (data, "image/jpeg") if data else None
        if out:
            with _thumb_lock:
                _thumb_cache[key] = (now, out[0], out[1])
        return out
    m = _sources_mod()
    out = None
    try:
        r = m.thumbnail_ex(src, width=width, method="auto")
        if r and r.get("data"):
            out = (r["data"], r.get("mime") or "image/png")
        elif kind == "window":
            png = m.window_icon_png(int(n), size=64)
            if png:
                out = (png, "image/png")
    except Exception:
        out = None
    if out:
        with _thumb_lock:
            _thumb_cache[key] = (now, out[0], out[1])
            if len(_thumb_cache) > 64:
                for k in sorted(_thumb_cache, key=lambda k: _thumb_cache[k][0])[:16]:
                    _thumb_cache.pop(k, None)
    return out


# ---- the red border + Stop bar while a share is on air -----------------------------------------------------------
_overlays = {}             # feed id -> overlay
_ov_lock = threading.Lock()


def overlay_start(feed_id, url, on_stop):
    if not WINDOWS:
        return
    try:
        import kastr_overlay
        kind, n = parse_url(url)
        src = _resolve(kind, n) or {}
        with _ov_lock:
            old = _overlays.pop(feed_id, None)
        if old:
            old.stop()
        ov = kastr_overlay.ShareOverlay(on_stop=on_stop)
        if kind in ("window", "tab"):
            ov.start(hwnd=n, label=kind)
        else:
            r = src.get("rect") if isinstance(src.get("rect"), dict) else None
            if not src.get("hmonitor") and r and r.get("w"):   # 0.21.83 (D): All monitors -- a border around their union
                ov.start(monitor_rect=(r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]), label="screen")
            else:
                ov.start(hmonitor=int(src.get("hmonitor") or 0) or None, label="screen")
        with _ov_lock:
            _overlays[feed_id] = ov
    except Exception:
        pass


def overlay_mode(feed_id, mode="share", label=None, buttons=None, on_button=None):
    """0.21.79: the share's bar turns into the remote-control prompt ("prompt": Deny / Allow) or the red control bar
    ("control": Stop control), and back ("share"). -> True when the share has a bar to do it with."""
    with _ov_lock:
        ov = _overlays.get(feed_id)
    if ov is None:
        return False
    try:
        return bool(ov.set_mode(mode, label, buttons, on_button))
    except Exception:
        return False


def overlay_bar_rect(feed_id):
    """0.21.79: where the share's bar is (the controller's clicks never land on it)."""
    with _ov_lock:
        ov = _overlays.get(feed_id)
    try:
        return ov.bar_rect() if ov is not None else None
    except Exception:
        return None


def overlay_stop(feed_id):
    with _ov_lock:
        ov = _overlays.pop(feed_id, None)
    if ov:
        try:
            ov.stop()
        except Exception:
            pass
