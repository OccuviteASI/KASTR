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
"""
import os
import re
import sys
import threading
import time

WINDOWS = sys.platform == "win32"
MAX_W, MAX_H, FPS = 1920, 1080, 30
# the computer's sound: s16le PCM on ffmpeg's stdin. kastr_loopback writes it in real time and pads silence, so the
# sample count IS the clock -- timestamps from 0 like the capture's (wall-clock stamps put the audio ~50 years ahead)
LOOPBACK_INPUT = ["-thread_queue_size", "1024", "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", "pipe:0"]
_URL_RE = re.compile(r"^screen://(monitor|window)/(\d{1,20})$", re.I)

_src = None


def _sources_mod():
    """kastr_screen_sources with the bundled ffmpeg (its own default is a dev path)."""
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


def available():
    """Native capture works on Windows 10 1903+ with the bundled ffmpeg (gfxcapture)."""
    if not WINDOWS:
        return False
    try:
        return bool(_sources_mod())
    except Exception:
        return False


def parse_url(url):
    m = _URL_RE.match(str(url or "").strip())
    if not m:
        raise ValueError("screen urls are screen://monitor/<n> or screen://window/<hwnd>")
    return m.group(1).lower(), int(m.group(2))


def check_url(url):
    if not WINDOWS:
        raise ValueError("native screen sharing needs Windows on this computer -- use Share content in a browser instead")
    kind, n = parse_url(url)
    if not _resolve(kind, n):
        raise ValueError("that %s is no longer there" % ("screen" if kind == "monitor" else "window"))


def _resolve(kind, n):
    """The live source dict behind a url (monitor by index, window by handle) or None."""
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


def _fit(w, h):
    w, h = max(2, int(w or MAX_W)), max(2, int(h or MAX_H))
    k = min(1.0, MAX_W / w, MAX_H / h)
    return max(2, int(w * k) // 2 * 2), max(2, int(h * k) // 2 * 2)


def capture_size(url):
    kind, n = parse_url(url)
    src = _resolve(kind, n) or {}
    r = src.get("rect") or {}
    w = src.get("width") or (r.get("right", 0) - r.get("left", 0)) or (r.get("w") if isinstance(r, dict) else 0)
    h = src.get("height") or (r.get("bottom", 0) - r.get("top", 0)) or (r.get("h") if isinstance(r, dict) else 0)
    return _fit(w, h)


def capture_input(url):
    """ffmpeg input args for a screen:// url: gfxcapture scaled at capture (aspect kept), CPU frames, a steady 30 fps
    (Windows Graphics Capture only delivers frames when something changes -- fps= repeats the last one so a still screen
    still sends keyframes to late joiners)."""
    kind, n = parse_url(url)
    src = _resolve(kind, n) or {}
    w, h = capture_size(url)
    target = ("hmonitor=%d" % int(src.get("hmonitor") or 0)) if kind == "monitor" and src.get("hmonitor") \
        else ("monitor_idx=%d" % n) if kind == "monitor" else ("hwnd=%d" % n)
    graph = ("gfxcapture=%s:max_framerate=%d:width=%d:height=%d:resize_mode=scale_aspect:capture_cursor=1,"
             "hwdownload,format=bgra,fps=%d,setsar=1" % (target, FPS, w, h, FPS))
    return ["-f", "lavfi", "-i", graph]


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


def sources(exclude_pids=()):
    """JSON for /api/screen/sources: screens first (primary, then left to right), then windows in Z-order."""
    if not available():
        return {"ok": False, "reason": "native screen sharing needs Windows"}
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
    return {"ok": True, "screens": screens, "windows": windows}


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
        if kind == "window":
            ov.start(hwnd=n, label="window")
        else:
            ov.start(hmonitor=int(src.get("hmonitor") or 0) or None, label="screen")
        with _ov_lock:
            _overlays[feed_id] = ov
    except Exception:
        pass


def overlay_stop(feed_id):
    with _ov_lock:
        ov = _overlays.pop(feed_id, None)
    if ov:
        try:
            ov.stop()
        except Exception:
            pass
