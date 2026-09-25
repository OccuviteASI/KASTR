#!/usr/bin/env python3
"""Shared static-file server for the KASTR pages.

Single source of truth for the two things the pages need from their host:

1. COOP/COEP headers, so the document is cross-origin isolated and
   SharedArrayBuffer is available. @moq/watch uses SharedArrayBuffer for its
   primary (reliable) audio path; without isolation it silently falls back to a
   postMessage path that can stall indefinitely.

2. Relay substitution. stats.html is a prebuilt bundle with
   `http://localhost:4443` baked in as a minified constant and reads no query
   param or localStorage override (the upstream watch.html/publish.html demo
   pages were dropped in 0.9.3). Rewriting on the way out keeps the build on
   disk pristine and puts the relay in exactly one place.

Used by both kastr-serve.py (plain CLI) and kastr.py (packaged app).
"""
import hashlib
import json
import mimetypes      # 0.14.0: media sources keep their own extension
import os
import re
import socket
import sys
import time
import uuid
import subprocess
import threading      # 0.12.0
from urllib.parse import quote, parse_qs, urlparse
import urllib.request
import urllib.error
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import kastr_relay
import kastr_rtsp

# The string baked into the prebuilt bundles.
BUILTIN_RELAY = "http://localhost:4443"

# Placeholder the pages carry; replaced with this machine's name as they are
# served. Broadcast names must be unique per machine or two publishers collide
# on the relay and clobber each other -- which is exactly what the upstream
# demo's hardcoded "me.hang" does on every computer that opens it.
HOST_TOKEN = "__ASI_HOSTNAME__"

# The upstream demo pages hardcoded this as their broadcast name (kept: any
# page carrying it is still rewritten).
BUILTIN_NAME = '"me.hang"'

# 0.17.0: who the page is being served to -- "app" for the machine's own window,
# "web" for a browser on another device that opened this relay host's web port.
# Substituted per request like the hostname; the page reads it synchronously.
CLIENT_TOKEN = "__KASTR_CLIENT__"

# Replaced with the build's version as pages are served.
VERSION_TOKEN = "__KASTR_VERSION__"


def read_version():
    "The version stamped into this build; bundled beside the web files."
    roots = [os.path.dirname(os.path.abspath(__file__))]
    if getattr(sys, "frozen", False):
        roots.insert(0, os.path.join(sys._MEIPASS, "site"))
        roots.insert(1, sys._MEIPASS)
    for root in roots:
        try:
            with open(os.path.join(root, "VERSION"), encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                # VERSION names the last build. A source checkout is ahead of
                # it by whatever is uncommitted, so "0.5.4-dev" rather than a
                # bare number that would claim to BE that build.
                return v if getattr(sys, "frozen", False) else v + "-dev"
        except OSError:
            continue
    return "dev"



def autorun_state():
    """Is KASTR registered to start with this machine? Per-user, no admin.
    Windows: HKCU Run key; Linux: ~/.config/autostart. Frozen builds only
    (a dev checkout has no stable exe to point at)."""
    if not getattr(sys, "frozen", False):
        return {"enabled": False, "supported": False,
                "note": "autorun applies to the installed app, not a source checkout"}
    exe = sys.executable
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                val, _ = winreg.QueryValueEx(k, "KASTR")
            return {"enabled": exe.lower() in str(val).lower(), "supported": True}
        except OSError:
            return {"enabled": False, "supported": True}
    desk = os.path.expanduser("~/.config/autostart/kastr.desktop")
    return {"enabled": os.path.exists(desk), "supported": True}


def autorun_set(enabled):
    if not getattr(sys, "frozen", False):
        return {"error": "autorun is for the installed app (frozen builds) only"}
    exe = sys.executable
    if sys.platform == "win32":
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            if enabled:
                winreg.SetValueEx(k, "KASTR", 0, winreg.REG_SZ, '"%s"' % exe)
            else:
                try:
                    winreg.DeleteValue(k, "KASTR")
                except OSError:
                    pass
        return {"ok": True, "enabled": bool(enabled)}
    d = os.path.expanduser("~/.config/autostart")
    desk = os.path.join(d, "kastr.desktop")
    if enabled:
        os.makedirs(d, exist_ok=True)
        with open(desk, "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\nType=Application\nName=KASTR\n"
                    "Comment=Kenton's ASI Streaming Tool with Relay\n"
                    'Exec="%s"\nX-GNOME-Autostart-enabled=true\n' % exe)
    else:
        try:
            os.remove(desk)
        except OSError:
            pass
    return {"ok": True, "enabled": bool(enabled)}


def _ini_file():
    """The kastr.ini next to the running thing -- same first candidate the
    launcher's config_paths() checks."""
    base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "kastr.ini")


# 0.12.0: the four operating modes + the default. kastr.ini `mode = viewer |
# publisher | relay | publisher-relay`; absent or anything else = "full", the
# 0.11 client -- no default may turn a laptop into a publisher box.
MODES = ("full", "viewer", "publisher", "relay", "publisher-relay")
# 0.12.0: the mode THIS process boots as. The launcher (kastr.py) and the dev
# harness set it; /api/instance and /api/mode report it so the shell and the
# masthead can shape themselves (no Relay tab on a viewer box, and so on).
MODE = "full"


def mode_state():
    """kastr.ini's operating mode (0.12.0; 0.8.3's relay-only flag generalized).
    `mode` is the ini value normalized to MODES ("full" when absent/unknown),
    `relay` stays for old callers (true for both relay modes), `running` is
    what this process actually booted as."""
    mode = str(ini_get("mode") or "").strip().lower()
    if mode not in MODES:
        mode = "full"
    return {"mode": mode,
            "relay": mode in ("relay", "publisher-relay"),
            "running": MODE,
            "path": _ini_file(),
            "note": "applies when KASTR relaunches (Apply & relaunch)"}


INI_KEYS = ("mode", "host")   # what the pages may write (0.8.6)


def ini_get(key):
    """Current value of `key` in kastr.ini, or None."""
    try:
        with open(_ini_file(), encoding="utf-8-sig") as f:
            txt = f.read()
    except OSError:
        return None
    m = re.search(r"(?mi)^[ \t]*%s[ \t]*=[ \t]*(.*?)[ \t]*\r?$" % re.escape(key), txt)
    return m.group(1) if m else None


def ini_set(key, value):
    """Add/replace (value) or remove (None) `key = value` under [streamer],
    textually -- comments and line endings preserved; the file is created
    with a [streamer] section if absent. (0.8.3's mode toggle, generalized.)"""
    p = _ini_file()
    try:
        with open(p, encoding="utf-8-sig") as f:
            txt = f.read()
    except OSError:
        txt = ""
    nl = "\r\n" if "\r\n" in txt else ("\n" if txt else os.linesep)
    txt = re.sub(r"(?mi)^[ \t]*%s[ \t]*=.*(?:\r?\n|\r|$)" % re.escape(key), "", txt)
    if value is not None:
        line = "%s = %s" % (key, value)
        if re.search(r"(?mi)^\[streamer\][ \t]*\r?$", txt):
            txt = re.sub(r"(?mi)^(\[streamer\][ \t]*\r?\n)",
                         lambda m: m.group(1) + line + nl, txt, count=1)
        else:
            if txt and not txt.endswith(("\n", "\r")):
                txt += nl
            txt += "[streamer]" + nl + line + nl
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(txt)
    os.replace(tmp, p)


def mode_set(want):
    """Operating mode in kastr.ini (0.12.0; 0.8.3's relay-only on/off kept).
    True / False -> "relay" / removed; a string in MODES -> that mode, where
    "full" (also None / "") REMOVES the key so the default client boots.
    Anything else raises ValueError (the /api/mode handler answers 400)."""
    if want is None or isinstance(want, bool):
        mode = "relay" if want else "full"
    else:
        mode = str(want).strip().lower() or "full"
    if mode not in MODES:
        raise ValueError("unknown mode %r (one of: %s)" % (mode, ", ".join(MODES)))
    ini_set("mode", None if mode == "full" else mode)
    return mode_state()


def host_slug(name=None):
    """This machine's name, reduced to something safe in a MoQ path, plus a
    stable per-machine suffix. Cloned images (normal on robot boxes) share a
    hostname, and identical host segments mean byte-identical broadcast
    paths: they collide on the relay AND every device suppresses the other's
    tile as "its own" -- each machine then sees only itself. The MAC-derived
    suffix needs no stored state and survives reinstalls."""
    raw = name or socket.gethostname() or "host"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.split(".")[0].lower()).strip("-")
    slug = slug[:32] or "host"
    return "%s-%04x" % (slug, uuid.getnode() & 0xFFFF)

# The relay currently on the network.
DEFAULT_RELAY = "http://10.10.105.190:4443"

# 0.8.6: the launcher installs its on-demand updater here (None in a dev
# harness -- source checkouts never self-update).
UPDATE_HOOK = None
# 0.8.8: set by the launcher when a self-update is about to relaunch; the
# heartbeat then answers 205 and the page closes its own window.
CLOSING = [False]
# 0.8.9: the Relay page's "Apply & relaunch" -- installed by the launcher.
RELAUNCH_HOOK = None
# 0.9.8: POST /api/quit -- installed by the launcher (ends KASTR the way closing
# the window does, children included) and by the dev harness (server.shutdown).
QUIT_HOOK = None
# 0.8.9: filled by the launcher when the https listener is up.
HTTPS_INFO = {"port": None, "fingerprint": None, "ca": None, "names": [],
              "trust": None, "hostname": None, "expires": None, "error": None}   # 0.17.0: + trust path, operator hostname, last error

# 0.8.13: converted media files outlive their GET now (Range streaming), so the
# folder is swept; and the bundled ffmpeg's version is reported once.
_FFMPEG_VER = [None]


def ffmpeg_version(ff):
    if _FFMPEG_VER[0] is None:
        try:
            r = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            m = re.search(r"ffmpeg version (\S+)", r.stdout or "")
            _FFMPEG_VER[0] = m.group(1) if m else ((r.stdout or "").splitlines() or ["?"])[0][:60]
        except Exception:
            _FFMPEG_VER[0] = "unavailable"
    return _FFMPEG_VER[0]


def sweep_media(state_dir, max_age=12 * 3600):
    """Delete converted media (and probe leftovers) older than max_age."""
    d = os.path.join(state_dir, "media")
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    n, now = 0, time.time()
    for fn in names:
        p = os.path.join(d, fn)
        try:
            if os.path.isfile(p) and now - os.path.getmtime(p) > max_age:
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n


def start_media_sweeper(state_dir, every=3600):
    import threading

    def tick():
        try:
            sweep_media(state_dir)
        except Exception:
            pass
        t = threading.Timer(every, tick)
        t.daemon = True
        t.start()
    tick()


# ---- 0.14.0: media shares stream WHILE the source uploads -------------------
# One registry of the sources on disk (<state>/media/<id>.<ext>, id = the
# page's 32-hex share id) and the ffmpeg child each one feeds right now. The
# page uploads with POST /api/media/upload?id= and plays GET
# /api/media/<id>/stream?t=&v=&a= -- a fragmented MP4 straight out of ffmpeg,
# which may start before the last byte has landed. ONE child per share: a new
# stream request (a seek) kills the previous one. Children are spawned and
# released through the bridge (job object + registry) when it offers
# spawn_media/release_media, else through the plain fallback below.
MEDIA = {}
MEDIA_LOCK = threading.Lock()
_MEDIA_BRIDGE = [None]          # set by make_server: whose spawn_media/release_media own the children
_MEDIA_LOG = [None]             # the launcher's note(), when make_server has one
MEDIA_UPLOAD_MAX = 4 * 1024 * 1024 * 1024
MEDIA_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MEDIA_FILE_RE = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{1,5}$")
MEDIA_STREAM_TIMEOUT = 600      # a paused player may hold the connection a long while


def _note(msg):
    fn = _MEDIA_LOG[0]
    try:
        if callable(fn):
            fn(msg)
        elif sys.stderr is not None:
            sys.stderr.write(msg + "\n")
    except Exception:
        pass


def _media_rec(mid):
    with MEDIA_LOCK:
        return MEDIA.get(mid)


def _media_find(media_dir, mid):
    """The source file for an id (any extension) on disk, or None."""
    if not media_dir or not MEDIA_ID_RE.match(mid or ""):
        return None
    try:
        names = os.listdir(media_dir)
    except OSError:
        return None
    for fn in sorted(names):
        if fn.startswith(mid + ".") and MEDIA_FILE_RE.match(fn):
            return os.path.join(media_dir, fn)
    return None


def _spawn_media_plain(argv, tag="", nice=False):
    """Fallback when the bridge has no spawn_media yet: a Popen with a stderr
    drain into .kastr_errors (last 20 lines). No job object, no registry.
    0.16.0: `nice` = below-normal priority (see Bridge.spawn_media)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    kw = {}
    if nice:
        if sys.platform == "win32":
            flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        else:
            kw["preexec_fn"] = lambda: os.nice(10)
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=flags, **kw)
    proc.kastr_errors = []
    proc.kastr_tag = tag

    def drain():
        try:
            for line in iter(proc.stderr.readline, b""):
                s = line.decode("utf-8", "replace").rstrip()
                if s:
                    proc.kastr_errors.append(s)
                    del proc.kastr_errors[:-20]
        except Exception:
            pass
    threading.Thread(target=drain, daemon=True, name="media-stderr").start()
    return proc


def _media_release_proc(proc):
    """Hand a media child back to the bridge (kills + reaps + unregisters), or
    kill it ourselves when the bridge has no release_media."""
    b = _MEDIA_BRIDGE[0]
    rel = getattr(b, "release_media", None) if b is not None else None
    if rel is not None:
        try:
            rel(proc)
            return
        except Exception as e:
            _note("media: release_media failed: %s" % e)
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError:
        pass
    try:
        proc.wait(2)
    except Exception:
        pass


def _media_kill(rec):
    """Stop every ffmpeg feeding this share."""
    with MEDIA_LOCK:
        procs = list(rec.get("procs") or ())
    for p in procs:
        _media_release_proc(p)
        with MEDIA_LOCK:
            rec["procs"].discard(p)


def _media_forget(mid, remove_files=True, media_dir=None):
    """Drop a share: kill its child and (by default) remove <media>/<id>.* ."""
    with MEDIA_LOCK:
        rec = MEDIA.pop(mid, None)
    if rec is not None:
        _media_kill(rec)
        if not rec.get("done"):
            rec["aborted"] = True
    d = media_dir or (os.path.dirname(rec["path"]) if rec and rec.get("path") else None)
    if remove_files and d and MEDIA_ID_RE.match(mid or ""):
        try:
            names = os.listdir(d)
        except OSError:
            names = []
        for fn in names:
            if not fn.startswith(mid + "."):
                continue
            p = os.path.join(d, fn)
            for _ in range(5):      # Windows: the killed child may hold the file for a moment
                try:
                    os.remove(p)
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    time.sleep(0.2)
    return rec


def media_shutdown():
    """Kill every media child -- the launcher's teardown (make_server hooks it
    into server.shutdown/server_close). Files stay: a restart re-adopts them."""
    with MEDIA_LOCK:
        recs = list(MEDIA.values())
    for rec in recs:
        try:
            _media_kill(rec)
        except Exception:
            pass
    try:
        hls_shutdown()      # 0.18.0
    except Exception:
        pass


# ---- 0.14.0: /api/prefs -- the page's localStorage mirrored server-side ----
# Chrome for Testing's profile is disposable and snap-confined Chromium loses
# localStorage silently (the operator.json lesson), so the page keeps its
# durable keys here too: prefs.json in the state dir, whitelist below, caps,
# and the session secrets (access/code inside kastr.lastjoin, kastr.auth*)
# never stored -- the page strips them as well; this is belt and braces.
PREFS_ALLOW = re.compile(r"^kastr\.(lastjoin|rtsp\.|grid\.|profile$|sidebar|mic\.|volume$|relay\.history$"
                         r"|channels\.mine$|channel$|operator\.name$|publishOnly$|rail\.w$|watch\.|camfx$|toasts\.|rooms\.groups\.)")
PREFS_DENY = re.compile(r"^kastr\.auth")
PREFS_SECRET_FIELDS = ("access", "code")
PREFS_VALUE_MAX = 64 * 1024
PREFS_KEYS_MAX = 200
PREFS_TOTAL_MAX = 512 * 1024
PREFS_BODY_MAX = 1 << 20
PREFS_LOCK = threading.Lock()
_PREFS_WARNED = set()


def _prefs_warn(kind, detail=""):
    """One log line per kind of drop per process -- the page retries every
    change, so anything louder would flood the launch log."""
    if kind in _PREFS_WARNED:
        return
    _PREFS_WARNED.add(kind)
    _note("prefs: " + kind + ((" (" + detail + ")") if detail else "") + " -- further ones are silent")


def _prefs_scrub(obj):
    """Blank `access` / `code` wherever they occur (nested dicts and lists too)."""
    if isinstance(obj, dict):
        return {k: ("" if k in PREFS_SECRET_FIELDS else _prefs_scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_prefs_scrub(v) for v in obj]
    return obj


def _prefs_clean_value(key, val):
    """The string to store for one key, or None to drop it (not JSON where JSON
    is expected, or over the per-value cap). Non-strings are stored as JSON."""
    if val is None:
        return None
    if not isinstance(val, str):
        try:
            val = json.dumps(val, separators=(",", ":"))
        except Exception:
            return None
    if key == "kastr.lastjoin":
        try:
            obj = json.loads(val)
        except Exception:
            _prefs_warn("kastr.lastjoin is not JSON -- dropped")
            return None
        val = json.dumps(_prefs_scrub(obj), separators=(",", ":"))
    if len(val.encode("utf-8")) > PREFS_VALUE_MAX:
        _prefs_warn("a value over 64 KB was dropped", key[:60])
        return None
    return val


def _prefs_size(items):
    return sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in items.items())


def prefs_filter(items):
    """Whitelist + redaction + caps over a whole mapping (a seed, a loaded file);
    None values are dropped."""
    out = {}
    for k, v in (items or {}).items():
        if not isinstance(k, str) or PREFS_DENY.match(k) or not PREFS_ALLOW.match(k):
            continue
        s = _prefs_clean_value(k, v)
        if s is None:
            continue
        if len(out) >= PREFS_KEYS_MAX or _prefs_size(out) + len(k.encode("utf-8")) + len(s.encode("utf-8")) > PREFS_TOTAL_MAX:
            _prefs_warn("over the key/size cap -- extra keys dropped", k[:60])
            continue
        out[k] = s
    return out


def prefs_load(path):
    """The stored items, or None when prefs.json is missing / empty / unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        d = json.loads(raw)
    except Exception:
        return None
    items = d.get("items") if isinstance(d, dict) else None
    return items if isinstance(items, dict) and items else None   # an EMPTY file counts as missing (the seed applies again)


def prefs_merge(path, updates):
    """Apply {key: value | None} (None deletes) and write prefs.json atomically
    (tmp + os.replace, the operator.json way). Returns the stored items."""
    with PREFS_LOCK:
        items = prefs_filter(prefs_load(path) or {})
        for k, v in updates.items():
            if not isinstance(k, str):
                continue
            if PREFS_DENY.match(k):
                _prefs_warn("a kastr.auth* key was refused")
                continue
            if v is None:
                items.pop(k, None)
                continue
            if not PREFS_ALLOW.match(k):
                _prefs_warn("key outside the whitelist dropped", k[:60])
                continue
            s = _prefs_clean_value(k, v)
            if s is None:
                continue
            old = items.pop(k, None)
            if len(items) >= PREFS_KEYS_MAX or _prefs_size(items) + len(k.encode("utf-8")) + len(s.encode("utf-8")) > PREFS_TOTAL_MAX:
                if old is not None:
                    items[k] = old
                _prefs_warn("over the key/size cap -- extra keys dropped", k[:60])
                continue
            items[k] = s
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "at": time.time(), "items": items}, f)
        for i in range(5):
            try:
                os.replace(tmp, path)
                break
            except OSError:         # a scanner holding the fresh file: retry briefly
                if i == 4:
                    raise
                time.sleep(0.1)
        return items
# 0.8.10: the launcher's state dir + plain-http facts, so a KASTR that hosts no
# relay can still store shared files and name a LAN address for them.
STATE_DIR = None
HTTP_PORT = None
LAN_OK = False
WEB_VIDEO = ("h264", "vp8", "vp9", "av1")
WEB_AUDIO = ("aac", "mp3", "opus", "vorbis", "flac", "pcm")
# The relay's wss listener rides the relay port + 2 (4443 -> 4445).
WSS_OFFSET = 2

# Only text formats get substituted; everything else is streamed byte-for-byte.
REWRITE_EXTS = (".html", ".js", ".css")

COEP_MODES = ("require-corp", "credentialless")

# ---- room chat + kept rooms (0.12.0) -----------------------------------------
# The relay HOST's KASTR keeps each room's transcript (kastr_chat) and answers
# /api/chat/<room>[/files[/<id>]|/<id>] for the room's members. The credential
# is the member token the relay's own minter issued (?jwt= or X-Kastr-Jwt),
# verified here with the same signing key; an open relay (not secured) trusts
# the LAN like /api/files. A SPOKE (relay-cluster.json `connect`) forwards the
# whole call to the hub's KASTR with its federation token as the Bearer -- one
# transcript per federated room -- and a hub serves a Bearer call locally
# whatever its own cluster file says (hop guard). /api/rooms/{list,register,
# close} front the relay's AuthStore for pages on other machines (CORS-open):
# kept rooms outlive the 24 h heartbeat window; a closed room answers 410 for
# an hour so pages learn why.
CHAT = None                        # the one ChatStore (the http and https listeners share it)
_CHAT_LOCK = threading.Lock()
_CHAT_RELAY = [None]               # the Relay object make_server was given
_CHAT_SWEEPER = [False]
CHAT_RE = re.compile(r"^/api/chat/([a-z0-9-]{1,32})(?:(/files)(?:/([0-9a-f]{32}))?|/(\d{1,20}))?$")
CHAT_INLINE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
CHAT_TIMEOUT = 10                  # a forwarded chat call
CHAT_FILE_TIMEOUT = 60             # a forwarded attachment
HUB_WEB_PORT = 8000                # relay-cluster.json "web" default
# 0.15.0: host -> {"web", "https"}: the web ports of other KASTRs (the hub's) as
# learned -- hub-web.json (the launcher loads it at start), the 5-minute learner,
# and the relay's federation path (kastr_relay.hub_web_note writes into the sink).
HUB_WEB = {}
kastr_relay.HUB_WEB_SINK = HUB_WEB
_CHAT_HUB_SAID = set()             # hosts whose "hub is this KASTR on another port" line was logged


def hub_web_for(host, default=8000):
    """0.15.0: the KASTR web port learned for `host`, else `default`."""
    try:
        rec = HUB_WEB.get(str(host or "").strip().lower()) or {}
        web = int(rec.get("web") or 0)
        return web if 1 <= web <= 65535 else int(default)
    except (TypeError, ValueError, AttributeError):
        return int(default)


def _chat_log(m):
    """The relay's log (the launcher's note()) once make_server has run."""
    log = getattr(_CHAT_RELAY[0], "log", None)
    if callable(log):
        try:
            log(m)
        except Exception:
            pass


CHAT_LOCKOUT = kastr_relay.Lockout(_chat_log)     # wrong access codes at /api/rooms/register
_OWN_HOSTS = [0.0, set()]


def _own_hosts():
    """Names this machine answers to (loopback, LAN IPs, hostname), cached a
    minute -- a spoke checks them on every forwarded chat call."""
    now = time.time()
    if now - _OWN_HOSTS[0] > 60:
        own = set(kastr_relay.LOOPBACK_HOSTS)
        try:
            own |= {h.lower() for h in kastr_relay.local_ips()}
            own.add((socket.gethostname() or "").lower())
        except Exception:
            pass
        _OWN_HOSTS[0], _OWN_HOSTS[1] = now, own
    return _OWN_HOSTS[1]


_REMOTE_SEEN = {}

# 0.17.0: the fMP4 fallback (docs/moq-landscape item 7). A browser without WebCodecs
# (an insecure http page, an older WebKit, a kiosk) cannot run <moq-watch>; the relay
# host consumes the broadcast for it with the bundled moq CLI (`export fmp4`) and
# streams CMAF over plain HTTP -- one child per viewer, the viewer's own token, a cap.
WATCH_MAX = 6
_WATCH_LIVE = [0]
_WATCH_LOCK = threading.Lock()
WATCH_SEG_RE = re.compile(r"^(?!\.\.?$)[A-Za-z0-9._-]+$")   # 0.18.0: never "." or ".."


# 0.18.0: on-demand cameras (docs/moq-landscape item 3). A camera box's bridge syncs its
# standby feeds here every 5 s ({broadcast: {room, label, low, at, wantedAt, live}}); viewer
# pages list them and send demand; the bridge wakes a feed wanted within the last minute.
ONDEMAND = {}
ONDEMAND_LOCK = threading.Lock()
ONDEMAND_TTL = 30          # a registration the bridge stopped refreshing is gone
ONDEMAND_WANT = 120        # demand older than this is not reported back

# 0.18.0: HLS for browsers without MSE (iPhones before iOS 17): one `moq export hls` per
# broadcast on a loopback port, shared by its viewers, reached through /api/hls/<key>/...
HLS = {}                   # broadcast -> {proc, port, last, started}
HLS_KEYS = {}              # key -> {b, at}
HLS_LOCK = threading.Lock()
HLS_IDLE_S = 45
ARCHIVE_WANTS = lambda broadcast: False   # 0.18.0: make_server points this at the archiver's picks
HLS_KEY_IDLE_S = 120   # a keyed playlist unused this long is gone (players poll every few seconds)
HLS_WINDOW = "12s"
ARCHIVE_HOURS = 24         # kastr.ini archive_hours (the launcher sets it)


def ondemand_touch(broadcast, now=None):
    """A viewer is watching `broadcast` (a demand pulse or an /api/watch / HLS pump)."""
    now = now or time.time()
    with ONDEMAND_LOCK:
        rec = ONDEMAND.get(broadcast)
        if rec is not None:
            rec["wantedAt"] = now
            return True
    return False


def ondemand_sync(room, host, feeds, now=None):
    """The bridge's registration round -> {broadcast: seconds since the last want}. Feeds whose
    path is not under room/host (when a host is known) are ignored."""
    now = now or time.time()
    out = {}
    with ONDEMAND_LOCK:
        for f in feeds or []:
            if not isinstance(f, dict):
                continue
            b = str(f.get("broadcast") or "")
            segs = b.split("/")
            if len(segs) < 3 or any(not WATCH_SEG_RE.match(x) for x in segs) or segs[0] != room:
                continue
            if host and segs[1] != host:
                continue
            rec = ONDEMAND.get(b) or {"wantedAt": None}
            rec.update(room=room, label=str(f.get("label") or segs[-1])[:80], live=bool(f.get("live")),
                       low=(str(f.get("low")) if f.get("low") else None), at=now)
            ONDEMAND[b] = rec
            try:
                if ARCHIVE_WANTS(b):   # the operator records it -> keep it awake
                    rec["wantedAt"] = now
            except Exception:
                pass
            if rec.get("wantedAt") and now - rec["wantedAt"] < ONDEMAND_WANT:
                out[b] = round(now - rec["wantedAt"], 1)
        for b in [k for k, r in ONDEMAND.items() if now - r.get("at", 0) > ONDEMAND_TTL * 4]:
            ONDEMAND.pop(b, None)
    return out


def ondemand_list(room, now=None):
    now = now or time.time()
    with ONDEMAND_LOCK:
        return [{"broadcast": b, "label": r.get("label"), "live": bool(r.get("live")), "low": r.get("low"),
                 "wantedAgo": (round(now - r["wantedAt"]) if r.get("wantedAt") else None)}
                for b, r in sorted(ONDEMAND.items())
                if r.get("room") == room and now - r.get("at", 0) <= ONDEMAND_TTL]


def _od_web_base(relay_key):
    """0.18.0: the KASTR that hosts `relay_key` -- where a bridge syncs its on-demand feeds."""
    try:
        h = (urlparse(relay_key).hostname or "").lower()
    except Exception:
        return None
    if not h:
        return None
    if h in _own_hosts():
        return "http://127.0.0.1:%d" % int(HTTP_PORT or 8000)
    return "http://%s:%d" % (("[%s]" % h) if ":" in h else h, hub_web_for(h, 8000))


def _free_port():
    import socket as _s
    sk = _s.socket()
    try:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]
    finally:
        sk.close()


def hls_shutdown():
    with HLS_LOCK:
        recs = list(HLS.values())
        HLS.clear()
    for r in recs:
        try:
            r["proc"].kill()
        except Exception:
            pass


def _fmp4_codecs(head):
    """The MIME codecs string for an fMP4 init segment (best effort from the box tags)."""
    out = []
    i = head.find(b"avcC")
    if i >= 0 and len(head) >= i + 8:
        p = head[i + 5:i + 8]   # configurationVersion, then profile / compat / level
        out.append("avc1.%02X%02X%02X" % (p[0], p[1], p[2]) if len(p) == 3 else "avc1.42E01E")
    elif b"hvc1" in head or b"hev1" in head:
        out.append("hvc1.1.6.L93.B0")
    elif b"vp09" in head or b"vpcC" in head:
        out.append("vp09.00.10.08")
    elif b"av01" in head:
        out.append("av01.0.04M.08")
    if b"mp4a" in head:
        out.append("mp4a.40.2")
    elif b"Opus" in head:
        out.append("opus")
    return ",".join(out)


def _remote_seen(handler, what):
    """0.17.0: log a remote client once an hour per address (never per request --
    a web page polls every few seconds)."""
    try:
        peer = (handler.client_address[0] if handler.client_address else "") or "?"
        now = time.time()
        if now - _REMOTE_SEEN.get(peer, 0) < 3600:
            return
        _REMOTE_SEEN[peer] = now
        if len(_REMOTE_SEEN) > 512:
            for k in [k for k, t in _REMOTE_SEEN.items() if now - t > 3600][:256]:
                _REMOTE_SEEN.pop(k, None)
        _note("web: remote client %s served %s" % (peer, what))
    except Exception:
        pass


def page_relay(current, tls=False, req_host=None, remote=False, own_hosts=None):
    """0.17.0: the relay URL a served page should dial.

    A page opened on THIS machine keeps `current` verbatim (its relay may be
    another box, or this one by any spelling). A page served to ANOTHER device
    (remote) or over https must never be handed a loopback address -- the relay
    this box hosts is named by the address the client used to reach us
    (`req_host`), and an https page gets the relay's wss listener (port + 2).
    Pure: unit-tested with a fake own_hosts set."""
    try:
        u = urlparse(current or BUILTIN_RELAY)
        rh = u.hostname or "localhost"
        port = u.port or 4443
    except Exception:
        rh, port = "localhost", 4443
    own = own_hosts if own_hosts is not None else _own_hosts()
    loop = rh in kastr_relay.LOOPBACK_HOSTS
    if req_host and (loop or (remote and rh in own)):
        rh = req_host
    if ":" in rh and not rh.startswith("["):
        rh = "[" + rh + "]"
    if tls:
        return "https://%s:%d" % (rh, port + WSS_OFFSET)
    return "http://%s:%d" % (rh, port)


def chat_store(state_dir=None, relay_srv=None):
    """The process-wide ChatStore, created on first use from the relay's state
    dir (or the launcher's STATE_DIR); None when there is no state dir at all.
    Creating it also hooks the relay's room close to the transcript's removal."""
    global CHAT
    with _CHAT_LOCK:
        if CHAT is None:
            rs = relay_srv if relay_srv is not None else _CHAT_RELAY[0]
            # the caller's relay first, then the launcher's STATE_DIR, then the relay make_server remembered
            base = (state_dir or getattr(relay_srv, "state_dir", None) or STATE_DIR
                    or getattr(_CHAT_RELAY[0], "state_dir", None))
            if not base:
                return None
            import kastr_chat
            log = getattr(rs, "log", None)
            CHAT = kastr_chat.ChatStore(base, log=log if callable(log) else None,
                                        files_dir=os.path.join(base, "shared"))
            if rs is not None:
                try:
                    rs.on_room_close = lambda slug, _c=CHAT: _c.delete_room(slug)
                except Exception:
                    pass
        return CHAT


def chat_sweep_once(relay_srv=None):
    """Transcripts idle for a day that nobody keeps are gone -> swept slugs."""
    store = chat_store(relay_srv=relay_srv)
    if store is None:
        return []
    rs = relay_srv if relay_srv is not None else _CHAT_RELAY[0]
    kept = set()
    try:
        kept = set(rs.store.kept_slugs())
    except Exception:
        pass
    return store.sweep(kept)


def start_chat_sweeper(relay_srv=None, every=3600):
    """Hourly, once per process (the start_media_sweeper idiom)."""
    if _CHAT_SWEEPER[0]:
        return
    _CHAT_SWEEPER[0] = True
    if relay_srv is not None:
        _CHAT_RELAY[0] = relay_srv

    def tick():
        try:
            chat_sweep_once(relay_srv)
        except Exception:
            pass
        t = threading.Timer(every, tick)
        t.daemon = True
        t.start()
    tick()


class _BoundedReader:
    """Hands urllib exactly Content-Length bytes of a request body being
    forwarded (a socket file never reports EOF on its own)."""

    def __init__(self, f, n):
        self.f, self.left = f, int(n)

    def read(self, n=-1):
        if self.left <= 0:
            return b""
        n = self.left if (n is None or n < 0) else min(int(n), self.left)
        b = self.f.read(n)
        self.left = self.left - len(b) if b else 0
        return b


def make_handler(root, coep=COEP_MODES[0], relay=DEFAULT_RELAY, quiet=False,
                 hostname=None, bridge=None, relay_srv=None, relay_ref=None,
                 alive_ref=None, window_file=None):
    host = host_slug(hostname)
    # relay_ref is a one-element list so the relay can be repointed at runtime
    # (the Relay page's "use this relay") without rebuilding the handler.
    if relay_ref is None:
        relay_ref = [relay]
    if alive_ref is None:
        alive_ref = [0.0]

    def subs(tls=False, req_host=None, remote=False):
        current = relay_ref[0] or BUILTIN_RELAY
        # 0.8.9: a page served over https cannot use an http:// relay (mixed
        # content; no fingerprint pinning either) -- it gets the relay's wss
        # listener instead: https://<relay host>:<port+2>. A relay on THIS
        # machine is named by the address the phone used to reach us.
        # 0.17.0: a REMOTE page (another device on this relay host's web port)
        # gets the same treatment on plain http -- never a loopback relay --
        # and its own identity: `web` for the host token (the page derives a
        # per-device slug from it) and "web" as its client class.
        if tls or remote:
            current = page_relay(current, tls=tls, req_host=req_host, remote=remote)
        page_host = "web" if remote else host
        out = [
            (VERSION_TOKEN.encode(), read_version().encode()),
            (HOST_TOKEN.encode(), page_host.encode()),
            (CLIENT_TOKEN.encode(), (b"web" if remote else b"app")),
            # Give the upstream demo page a machine-specific default too.
            (BUILTIN_NAME.encode(), f'"{page_host}/me.hang"'.encode()),
        ]
        if current != BUILTIN_RELAY:
            out.append((BUILTIN_RELAY.encode(), current.encode()))
        return out

    # Latest self-report per page. In memory only; never written anywhere.
    diag_ref = {}

    # Fleet updates (0.8.1): this instance serves its own binary -- and any
    # OTHER platform's binary dropped into updates/<windows|linux|macos>/
    # next to it -- so clients can match the relay host's version at launch.
    _upd_cache = {}   # path -> (mtime, size, sha256)

    def _update_platforms():
        plats = {}

        def add(plat, p):
            try:
                st = os.stat(p)
            except OSError:
                return
            c = _upd_cache.get(p)
            if not c or c[0] != st.st_mtime:
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                c = (st.st_mtime, st.st_size, h.hexdigest())
                _upd_cache[p] = c
            plats[plat] = {"path": p, "size": c[1], "sha256": c[2]}

        frozen = bool(getattr(sys, "frozen", False))
        if frozen:
            me = ("win32" if sys.platform == "win32"
                  else "darwin" if sys.platform == "darwin" else "linux")
            add(me, sys.executable)
        base = os.path.dirname(sys.executable if frozen
                               else os.path.abspath(__file__))
        for plat, sub, fn in (("win32", "windows", "KASTR.exe"),
                              ("linux", "linux", "KASTR"),
                              ("darwin", "macos", "KASTR")):
            if plat not in plats:
                add(plat, os.path.join(base, "updates", sub, fn))
        return plats

    def _browser_feed():
        """0.9.0: the bundled browser this install can hand to the fleet --
        updates/browser/chrome-<key>.zip beside the binary (build.py --publish
        puts both platforms there) and the version they carry."""
        base = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                               else os.path.abspath(__file__))
        out = {"version": None, "platforms": {}}
        for vf in (os.path.join(base, "updates", "browser", "VERSION"), os.path.join(base, "browser", "VERSION")):
            try:
                with open(vf, encoding="utf-8") as f:
                    out["version"] = f.read().strip() or None
                if out["version"]:
                    break
            except OSError:
                continue
        for api, key, root in (("win32", "win64", "chrome-win64"), ("linux", "linux64", "chrome-linux64")):
            p = os.path.join(base, "updates", "browser", "chrome-%s.zip" % key)
            try:
                st = os.stat(p)
            except OSError:
                continue
            c = _upd_cache.get(p)
            if not c or c[0] != st.st_mtime:
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                c = (st.st_mtime, st.st_size, h.hexdigest())
                _upd_cache[p] = c
            out["platforms"][api] = {"path": p, "size": c[1], "sha256": c[2], "root": root}
        return out

    # Operator name, persisted server-side (0.8.0): browser localStorage is
    # silently ephemeral under snap-confined Chromium (the Linux "name never
    # sticks" report), so the install remembers it instead. Lives next to the
    # relay's state because that dir exists in both the app and the dev
    # harness.
    op_file = os.path.join(relay_srv.state_dir, "operator.json") if relay_srv else None
    op_ref = [""]
    if op_file:
        try:
            with open(op_file, encoding="utf-8") as f:
                op_ref[0] = str(json.load(f).get("name") or "")[:30]
        except Exception:
            pass

    class Handler(SimpleHTTPRequestHandler):
        # 0.8.2: MIME types the Windows registry (which mimetypes consults)
        # often lacks. .mjs MUST be a JavaScript type -- module imports are
        # MIME-strict, and octet-stream kills the background-blur bundle.
        extensions_map = {
            **SimpleHTTPRequestHandler.extensions_map,
            ".js": "text/javascript",
            ".mjs": "text/javascript",
            ".wasm": "application/wasm",
            ".tflite": "application/octet-stream",
            ".webmanifest": "application/manifest+json",   # 0.17.0: PWA manifest
        }

        # 0.17.0: the request class (kastr_relay.request_class) -- "local" is the
        # machine's own window/tools, "remote" a LAN box or a web client.
        def _local(self):
            return kastr_relay.is_local(self)

        def _deny(self, what):
            return kastr_relay.deny_remote(self, what)

        def end_headers(self):
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", coep)
            # Our own assets are same-origin, but stamping this makes the pages
            # embeddable from another COEP document without extra config.
            # 0.8.7: shared files / avatars are fetched cross-origin by other
            # machines' KASTR pages -- those responses opt into cross-origin.
            self.send_header("Cross-Origin-Resource-Policy",
                             "cross-origin" if getattr(self, "_corp_cross", False) else "same-origin")
            super().end_headers()

        def _rewritten(self):
            """Substituted bytes for this request, or None to fall through.

            None means "let SimpleHTTPRequestHandler handle it normally" --
            directory listings, missing files, and non-text assets.
            """
            path = self.translate_path(self.path)
            # A directory means the index file. Without this, "/" skipped both
            # the substitution and the no-store header, so browsers cached the
            # home page and kept serving an old copy after an upgrade.
            if os.path.isdir(path):
                for index in ("index.html", "index.htm"):
                    candidate = os.path.join(path, index)
                    if os.path.exists(candidate):
                        path = candidate
                        break
                else:
                    return None             # a real directory listing
            if not path.lower().endswith(REWRITE_EXTS):
                return None
            self._rewritten_path = path
            try:
                with open(path, "rb") as f:
                    body = f.read()
            except OSError:
                return None
            tls = bool(getattr(self.server, "is_tls", False))
            req_host = kastr_relay._host_of(self.headers.get("Host")) or None
            remote = not self._local()   # 0.17.0: another device -> web identity + a dialable relay
            for needle, value in subs(tls, req_host, remote):
                body = body.replace(needle, value)
            if tls and BUILTIN_RELAY.encode() in body:
                # relay_ref still IS the builtin (localhost): the plain
                # substitution above skipped it -- point the https page at
                # this machine's wss listener anyway.
                body = body.replace(BUILTIN_RELAY.encode(),
                                    ("https://%s:%d" % (req_host or "localhost", 4443 + WSS_OFFSET)).encode())
            return body

        def _serve_rewritten(self, body, include_body):
            self.send_response(200)
            # From the resolved file: guess_type on "/" does not say text/html.
            resolved = getattr(self, "_rewritten_path", None) or self.translate_path(self.path)
            self.send_header("Content-Type", self.guess_type(resolved))
            self.send_header("Content-Length", str(len(body)))
            # No Last-Modified/If-Modified-Since on rewritten files: the mtime on
            # disk says nothing about which relay was substituted in, so a 304
            # could hand the browser a stale relay after the relay changes.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if include_body:
                self.wfile.write(body)

        def _set_relay(self, url):
            relay_ref[0] = url or BUILTIN_RELAY
            # 0.8.3: the choice survives relaunch -- the launcher reads
            # relay-use.json before kastr.ini (an explicit --relay still wins).
            if relay_srv and getattr(relay_srv, "state_dir", None):
                try:
                    p = os.path.join(relay_srv.state_dir, "relay-use.json")
                    tmp = p + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump({"url": url or ""}, f)
                    os.replace(tmp, p)
                except OSError:
                    pass

        def _alive(self):
            """Heartbeat from a served page.

            The launcher cannot rely on the browser process it spawned: Chrome
            hands the URL to an instance already holding the profile and the
            spawned process exits at once, which looked exactly like "the user
            closed the window" and tore the server down. A ping from the page
            itself is the honest signal, and it works the same on every OS.
            0.17.0: only the machine's own window -- a web client's ping must
            not keep a closed KASTR alive, nor be told to close (205).
            """
            if not self._local():
                return self._deny("heartbeat")
            alive_ref[0] = time.monotonic()
            self.send_response(205 if CLOSING[0] else 204)   # 0.8.8: 205 = please close
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _window_post(self):
            """Where the window is, so the next launch can put it back."""
            if not self._local():
                return self._deny("window geometry")   # 0.17.0
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b"{}"
                geom = json.loads(body.decode("utf-8", "replace"))
            except Exception:
                self.send_response(400)
                self.end_headers()
                return
            if window_file:
                try:
                    # Whole-file replace: a half-written geometry would be
                    # read back as a broken window next launch.
                    tmp = window_file + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(geom, f)
                    os.replace(tmp, window_file)
                except OSError:
                    pass
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _diag_post(self):
            """A page reporting what it is doing.

            Kept only in memory, only the latest per page, and only ever
            served back to this machine. It exists so a fault can be read
            rather than inferred from the outside.
            """
            if not self._local():
                return self._deny("diagnostics")   # 0.17.0
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b"{}"
                snap = json.loads(body.decode("utf-8", "replace"))
            except Exception:
                self.send_response(400)
                self.end_headers()
                return
            key = str(snap.get("page") or "?")[:120]
            snap["at"] = time.strftime("%H:%M:%S")
            snap["_at"] = time.time()        # 0.13.0: receive time -- /api/instance ages the snapshots
            diag_ref[key] = snap
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _diag_get(self):
            if not self._local():
                return self._deny("diagnostics")   # 0.17.0
            body = json.dumps(diag_ref, indent=1, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _update_check(self):
            """The launcher's update-check.json, if one was written."""
            if not (relay_srv and getattr(relay_srv, "state_dir", None)):
                return None
            try:
                with open(os.path.join(relay_srv.state_dir, "update-check.json"),
                          encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None

        VIEWING_FRESH_S = 30

        def _viewing(self):
            """0.13.0 (F2): how many feeds the pages on THIS box are pulling.
            The page counts its tiles with a live `url` and sends the integer as
            `watcher.viewing` in its 3 s diag POST; here it is the MAX over the
            watcher snapshots younger than VIEWING_FRESH_S, with the age of the
            newest one: {"n": int, "ageS": float}. None when no such snapshot
            exists -- a `?solo=1` box (no page reporting), a hidden-only page or
            a 0.12 page without the field: "unknown", never 0."""
            now = time.time()
            best, newest = None, None
            for snap in list(diag_ref.values()):
                try:
                    w = snap.get("watcher")
                    if not isinstance(w, dict):
                        continue
                    v = w.get("viewing")
                    if isinstance(v, bool) or not isinstance(v, (int, float)):
                        continue
                    age = now - float(snap.get("_at") or 0)
                    if age < 0 or age >= self.VIEWING_FRESH_S:
                        continue
                except Exception:
                    continue
                best = int(v) if best is None else max(best, int(v))
                newest = age if newest is None else min(newest, age)
            if best is None:
                return None
            return {"n": best, "ageS": round(newest, 1)}

        def _chat_hub_here(self):
            """0.13.0 (F1b): does GET /api/chat/<room> on THIS origin reach the
            fleet's SHARED transcript? The page uses its own origin for chat
            only when this is true. The rule follows _chat_api/_chat_auth:
              - a store must exist here (chat_store not None; otherwise 503), and
              - either _chat_hub() resolves a hub on another machine (this KASTR is
                a spoke: every call is proxied to the hub's store), or
              - _chat_hub() is None AND this KASTR hosts the RUNNING relay (it IS
                the chat hub; its store is the one every dialled-in page reads).
            A KASTR with no running relay and no cluster link also answers chat
            (mode "local") -- but from a private store nobody else reads, which
            is the split-brain the flag exists to rule out -> False."""
            try:
                if chat_store(relay_srv=relay_srv) is None:
                    return False
                if self._chat_hub() is not None:
                    return True
                return bool(relay_srv is not None and relay_srv.running())
            except Exception:
                return False

        def _instance(self):
            """Who is serving here.

            The launcher uses this to tell its own build apart from any other
            copy on the same port -- a source checkout answers the heartbeat
            exactly like a frozen app does, and used to capture its launch.

            A GET, and deliberately read-only: probing for a running instance
            must not refresh that instance's heartbeat and keep it alive.

            0.17.0: a REMOTE caller (LAN box, web client) gets the public shape:
            no pid/operator/diagnostics/helper detail, `mode` is always "full"
            (a web client is a full client whatever this box boots as; the real
            mode rides `hostMode`), `relay` is the address that caller can dial,
            and `client` says "web".
            """
            local = self._local()
            tls = bool(getattr(self.server, "is_tls", False))
            req_host = kastr_relay._host_of(self.headers.get("Host")) or None
            d = {
                "app": "KASTR",
                "version": read_version(),
                "frozen": bool(getattr(sys, "frozen", False)),
                "pid": os.getpid(),
                # 0.9.10: helper processes ended at start (registry + legacy sweeps)
                "swept": getattr(bridge, "swept", None),
                # The SERVER's platform: pages tailor host-side instructions
                # (firewall commands on the Relay page) to the machine that
                # would run them, not to whatever browser is looking.
                "platform": sys.platform,
                "port": self.server.server_address[1],
                # The relay currently substituted into served pages.
                # Substitution is per response, so a long-lived document
                # (the app shell's top document loads once per launch)
                # freezes its copy; the masthead polls this to follow a
                # runtime repoint.
                "relay": relay_ref[0] or BUILTIN_RELAY,
                # 0.11.0: the name of the relay THIS machine hosts (running), so a page
                # dialled into it can say "via <name>" (through /api/peer/instance).
                "relayName": self._relay_name(),
                # 0.12.0: the operating mode this KASTR boots as (full | viewer |
                # publisher | relay | publisher-relay); the shell drops its Relay
                # tab and the masthead its relay controls on a viewer box.
                "mode": MODE,
                # Server-remembered operator name (0.8.0) -- the fallback
                # when the browser profile lost its localStorage.
                "operator": op_ref[0],
                # 0.8.3: the launch-time fleet-update check's outcome (the
                # updater used to fail in silence). null in dev harnesses
                # and on pre-0.8.3 launches.
                "updateCheck": self._update_check(),
                # 0.8.13: seconds since the app window last pinged (None: never)
                # -- the launcher's hand-off check reads it -- and the bundled
                # ffmpeg's version, so a smoke test can assert the bundle.
                "aliveAge": (round(time.monotonic() - alive_ref[0], 1) if alive_ref and alive_ref[0] else None),
                "ffmpeg": ffmpeg_version(getattr(bridge, "ffmpeg", None)) if bridge and getattr(bridge, "ffmpeg", None) else None,
                # 0.13.0: feeds the pages on this box are pulling ({n, ageS} or
                # null = no page reporting) and whether chat on this origin is
                # the fleet's shared store (see _viewing / _chat_hub_here).
                "viewing": self._viewing(),
                "chatHub": self._chat_hub_here(),
                # 0.15.0: this KASTR's own web + https ports (a probing spoke reads
                # `web` -- kastr_relay.probe_hub_web) and the hub web ports it has
                # learned itself (host -> {web, https}).
                "web": int(HTTP_PORT or self.server.server_address[1]),
                "https": HTTPS_INFO.get("port"),
                "hubWeb": {h: {"web": r.get("web"), "https": r.get("https")} for h, r in HUB_WEB.items()},
            }
            if not local:
                for k in ("pid", "swept", "operator", "updateCheck", "aliveAge", "ffmpeg", "viewing", "hubWeb", "platform"):
                    d.pop(k, None)
                d["hostMode"] = MODE
                d["mode"] = "full"
                d["client"] = "web"
                d["relay"] = page_relay(relay_ref[0] or BUILTIN_RELAY, tls=tls, req_host=req_host, remote=True)
                _remote_seen(self, "/api/instance")
            body = json.dumps(d).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        # ---- shared files (0.8.7) --------------------------------------------
        # Any KASTR can host; the fleet uses the relay host's. Cross-origin by
        # design (LAN pages upload/download), so CORS + CORP cross-origin.
        FILE_LIMIT = 500 * 1024 * 1024

        def _state_dir(self):
            return getattr(relay_srv, "state_dir", None) or STATE_DIR

        def _files_dir(self):
            base = self._state_dir()
            if not base:
                return None
            d = os.path.join(base, "shared")
            os.makedirs(d, exist_ok=True)
            return d

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, X-Kastr-Name, X-Kastr-Room, X-Kastr-Owner, X-Kastr-Kind, "
                             "X-Kastr-Op, X-Kastr-Jwt, X-Kastr-Via, X-Kastr-Persistent, Authorization")   # 0.12.0: chat
            self.send_header("Access-Control-Expose-Headers", "Content-Disposition")

        def _json_cors(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self._corp_cross = True
            self.end_headers()
            self.wfile.write(body)

        def _json_plain(self, code, obj):
            """0.14.0: JSON without CORS -- for loopback-only endpoints."""
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()

        def _file_post(self):
            d = self._files_dir()
            if not d:
                return self._json_cors(503, {"error": "no storage here"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0:
                return self._json_cors(400, {"error": "empty upload"})
            if n > self.FILE_LIMIT:
                return self._json_cors(413, {"error": "file exceeds the 500 MB limit"})
            from urllib.parse import unquote
            fid = uuid.uuid4().hex
            token = uuid.uuid4().hex
            name = os.path.basename(unquote(self.headers.get("X-Kastr-Name") or "file"))[:200] or "file"
            meta = {"id": fid, "name": name, "size": n, "token": token,
                    "room": (self.headers.get("X-Kastr-Room") or "")[:64],
                    "owner": unquote(self.headers.get("X-Kastr-Owner") or "")[:64],
                    "kind": (self.headers.get("X-Kastr-Kind") or "file")[:16],
                    "at": int(time.time())}
            path = os.path.join(d, fid)
            got = 0
            with open(path, "wb") as f:
                while got < n:
                    chunk = self.rfile.read(min(1 << 20, n - got))
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
            if got != n:
                try:
                    os.remove(path)
                except OSError:
                    pass
                return self._json_cors(400, {"error": "short upload"})
            with open(path + ".json", "w", encoding="utf-8") as f:
                json.dump(meta, f)
            return self._json_cors(200, {"id": fid, "token": token, "size": n, "url": "/api/files/" + fid})

        def _file_list(self, qs):
            """0.8.8: the room's shared files (tokens withheld) -- a viewer who
            joined after the sharer's announce still sees them."""
            d = self._files_dir()
            if not d:
                return self._json_cors(200, {"files": []})
            room = (qs.get("room") or [""])[0][:64]
            out = []
            try:
                names = sorted(os.listdir(d))
            except OSError:
                names = []
            for fn in names:
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        m = json.load(f)
                except (OSError, ValueError):
                    continue
                if room and m.get("room") != room:
                    continue
                if m.get("kind") == "avatar":
                    continue
                out.append({"id": m.get("id"), "name": m.get("name"), "size": m.get("size"),
                            "owner": m.get("owner"), "at": m.get("at"),
                            "url": "/api/files/" + str(m.get("id"))})
            return self._json_cors(200, {"files": out})

        def _file_get(self, fid, head=False):
            d = self._files_dir()
            if not d or not re.match(r"^[0-9a-f]{32}$", fid):
                return self._json_cors(404, {"error": "no such file"})
            path = os.path.join(d, fid)
            try:
                with open(path + ".json", encoding="utf-8") as f:
                    meta = json.load(f)
                size = os.path.getsize(path)
            except OSError:
                return self._json_cors(404, {"error": "no such file"})
            from urllib.parse import quote
            self.send_response(200)
            ctype = "image/jpeg" if meta.get("kind") == "avatar" else "application/octet-stream"
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            if meta.get("kind") != "avatar":
                self.send_header("Content-Disposition",
                                 "attachment; filename*=UTF-8''" + quote(meta.get("name") or "file"))
            self.send_header("Cache-Control", "private, max-age=3600")
            self._cors()
            self._corp_cross = True
            self.end_headers()
            if head:
                return
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

        def _file_delete(self, fid, token):
            d = self._files_dir()
            if not d or not re.match(r"^[0-9a-f]{32}$", fid):
                return self._json_cors(404, {"error": "no such file"})
            path = os.path.join(d, fid)
            try:
                with open(path + ".json", encoding="utf-8") as f:
                    meta = json.load(f)
            except OSError:
                return self._json_cors(404, {"error": "no such file"})
            if token != meta.get("token"):
                return self._json_cors(403, {"error": "not the owner"})
            for p in (path, path + ".json"):
                try:
                    os.remove(p)
                except OSError:
                    pass
            return self._json_cors(200, {"ok": True})

        # ---- room chat + kept rooms (0.12.0) ---------------------------------
        # See the module comment above make_handler for the rules.

        def _chat_drain(self, cap=1 << 20):
            """Read a small unread body before an error reply so the client sees
            the status, not a reset (HTTP/1.0: the connection closes anyway)."""
            if getattr(self, "_chat_body_read", False):
                return
            self._chat_body_read = True
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if 0 < n <= cap:
                try:
                    self.rfile.read(n)
                except OSError:
                    pass

        def _chat_reply(self, code, obj, headers=None):
            self._chat_drain()
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, str(v))
            self._cors()
            self._corp_cross = True
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def _chat_body_json(self, cap=1 << 20):
            """The JSON body (a dict), {} when unparsable, None when too large."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n > cap:
                return None
            self._chat_body_read = True
            try:
                raw = self.rfile.read(n) if n else b"{}"
                d = json.loads(raw.decode("utf-8", "replace") or "{}")
                return d if isinstance(d, dict) else {}
            except Exception:
                return {}

        def _chat_peer(self):
            return (self.client_address[0] if self.client_address else "") or ""

        def _chat_via(self):
            """What this relay is called -- the poster's `via` on the hub."""
            return self._relay_name() or host_slug()

        def _room_persistent(self, room):
            try:
                rec = relay_srv.store.room(room) if relay_srv is not None else None
            except Exception:
                rec = None
            return bool(rec and rec.get("persistent"))

        def _chat_closed(self, room):
            """The close timestamp (ms) while the tombstone stands, else None."""
            try:
                if relay_srv is not None and relay_srv.store.is_closed(room):
                    return relay_srv.store.closed_public().get(room) or int(time.time() * 1000)
            except Exception:
                pass
            return None

        def _chat_hub(self):
            """{host, web, hub, code} when this KASTR is a spoke whose hub is
            another machine; None when it answers chat itself (no hub, or the
            hub is this very KASTR -- 0.15.0: own host, WHATEVER port the cluster
            file names for it; the stored web port used to have to match too, so
            a hub whose KASTR had moved ports proxied chat to itself).
            The hub's web port: the one stored in relay-cluster.json (learned
            from its minter), else hub-web.json / the learner (HUB_WEB), else
            the file's 8000 fallback."""
            if relay_srv is None:
                return None
            try:
                fed = relay_srv._cluster_raw()
            except Exception:
                return None
            hub = kastr_relay._normalize_hub(fed.get("connect") or "")
            if not hub:
                return None
            hhost = (urlparse(hub).hostname or "").lower()
            try:
                web = int(fed.get("webStored") or hub_web_for(hhost, 0) or fed.get("web") or HUB_WEB_PORT)
            except (TypeError, ValueError):
                web = HUB_WEB_PORT
            try:
                own_port = int(HTTP_PORT or self.server.server_address[1])
            except Exception:
                own_port = HTTP_PORT or 0
            own = set(_own_hosts())
            try:
                rh = (urlparse(relay_ref[0] or "").hostname or "").lower()
                if rh and relay_srv.running():
                    own.add(rh)             # the address our own relay is dialled by
            except Exception:
                pass
            if hhost in own:
                if web != own_port and hhost not in _CHAT_HUB_SAID:
                    _CHAT_HUB_SAID.add(hhost)
                    _chat_log("chat: the hub %s is this KASTR (cluster file says web port %d, this "
                              "server is on %d) -- answering chat locally" % (hhost, web, own_port))
                return None
            return {"host": hhost, "web": web, "hub": hub, "code": fed.get("code") or ""}

        def _chat_auth(self, room, qs):
            """The member check every chat call passes -> {"mode": "local"|"proxy",
            "via", "fed", "hub"} or None after an error reply.
            (1) Authorization: Bearer <federation token> = a spoke forwarding for
                its members: verified with OUR key, served here (hop guard).
            (2) ?jwt= / X-Kastr-Jwt = a member token: signature + exp + covers the room.
            (3) an open relay trusts the LAN like /api/files; a secured relay
                without its key answers 403 to every credential.
            (4) anything else: 401 token required.
            A spoke checks its own members BEFORE forwarding (its members hold
            tokens ITS minter issued -- the hub could not verify them)."""
            auth = self.headers.get("Authorization") or ""
            bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            jwt = (qs.get("jwt") or [""])[0] or (self.headers.get("X-Kastr-Jwt") or "")
            secured = bool(relay_srv is not None and getattr(relay_srv, "secured", False))
            state = self._state_dir()
            key = kastr_relay.read_jwk(state) if state else None
            if bearer:
                if secured:
                    claims = kastr_relay.verify_token(bearer, key) if key else None
                    if not claims or not kastr_relay.is_relay_claims(claims):
                        self._chat_reply(403, {"error": "federation token not accepted here"})
                        return None
                via = (self.headers.get("X-Kastr-Via") or "").strip()[:64] or self._chat_via()
                return {"mode": "local", "via": via, "fed": True, "hub": None}
            hub = self._chat_hub()
            mode = "proxy" if hub else "local"
            if not secured:
                return {"mode": mode, "via": self._chat_via(), "fed": False, "hub": hub}
            if not key:
                self._chat_reply(403, {"error": "relay is secured but has no signing key here"})
                return None
            if jwt:
                claims = kastr_relay.verify_token(jwt, key)
                if claims is None:
                    self._chat_reply(403, {"error": "bad token"})
                    return None
                if not kastr_relay.claims_cover(claims, room):
                    self._chat_reply(401, {"error": "token does not cover this room"})
                    return None
                return {"mode": mode, "via": self._chat_via(), "fed": False, "hub": hub}
            self._chat_reply(401, {"error": "token required"})
            return None

        def _chat_api(self, method):
            """/api/chat/<room>[...] and /api/rooms/{list,register,close}."""
            u = urlparse(self.path)
            path, qs = u.path, parse_qs(u.query)
            if path.startswith("/api/rooms/"):
                return self._rooms_api(method, path, qs)
            m = CHAT_RE.match(path)
            if not m:
                return self._chat_reply(404, {"error": "no such chat endpoint"})
            room, files, fid, msgid = m.group(1), m.group(2), m.group(3), m.group(4)
            store = chat_store(relay_srv=relay_srv)
            if store is None:
                return self._chat_reply(503, {"error": "no storage here"})
            ctx = self._chat_auth(room, qs)
            if ctx is None:
                return
            if ctx["mode"] == "proxy":
                return self._chat_proxy(method, room, ctx["hub"], files=bool(files))
            if ctx.get("fed"):
                # the spoke says whether IT keeps this room; the hub keeps the transcript for it
                keep = (self.headers.get("X-Kastr-Persistent") or "").strip()
                if keep == "1":
                    store.mark_keep(room, True)
                elif keep == "0":
                    store.mark_keep(room, False)
            if files:
                if fid:
                    if method in ("GET", "HEAD"):
                        return self._chat_file_get(room, fid, store, head=(method == "HEAD"))
                    return self._chat_reply(405, {"error": "GET or HEAD"})
                if method == "POST":
                    return self._chat_file_post(room, store, ctx)
                return self._chat_reply(405, {"error": "POST only"})
            if msgid:
                if method == "DELETE":
                    return self._chat_delete(room, msgid, qs, store)
                return self._chat_reply(405, {"error": "DELETE only"})
            if method == "GET":
                return self._chat_get(room, qs, store)
            if method == "POST":
                return self._chat_post(room, store, ctx)
            return self._chat_reply(405, {"error": "GET or POST"})

        def _chat_get(self, room, qs, store):
            ts = self._chat_closed(room)
            if ts:
                return self._chat_reply(410, {"error": "room closed", "closed": ts})
            try:
                msgs = store.read(room, (qs.get("since") or ["0"])[0], (qs.get("limit") or ["200"])[0])
            except ValueError as e:
                return self._chat_reply(400, {"error": str(e)})
            return self._json_cors(200, {"room": room, "messages": msgs,
                                         "persistent": self._room_persistent(room) or store.is_kept(room),
                                         "closed": False})

        def _chat_post(self, room, store, ctx):
            ts = self._chat_closed(room)
            if ts:
                return self._chat_reply(410, {"error": "room closed", "closed": ts})
            p = self._chat_body_json()
            if p is None:
                return self._chat_reply(413, {"error": "message too large"})
            try:
                rec = store.append(room, p.get("op"), p.get("name"), p.get("text"), p.get("files"),
                                   ctx.get("via") or "")
            except ValueError as e:
                return self._chat_reply(400, {"error": str(e)})
            if self._room_persistent(room):
                store.mark_keep(room, True)
            return self._json_cors(201, rec)          # the ONLY reply that carries the delete token

        def _chat_delete(self, room, msgid, qs, store):
            token = (qs.get("token") or [""])[0]
            force = kastr_relay._local_only(self)     # the operator on the relay host may delete anything
            try:
                ok = store.delete(room, int(msgid), token or None, force=force)
            except ValueError as e:
                return self._chat_reply(400, {"error": str(e)})
            if not ok:
                return self._chat_reply(403, {"error": "not your message (or already gone)"})
            return self._json_cors(200, {"ok": True})

        def _chat_file_post(self, room, store, ctx):
            """An attachment: stored like a shared file (kind "chat", the room,
            its content type) so the sweeps and the room close find it."""
            ts = self._chat_closed(room)
            if ts:
                return self._chat_reply(410, {"error": "room closed", "closed": ts})
            d = self._files_dir()
            if not d:
                return self._chat_reply(503, {"error": "no storage here"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0:
                return self._chat_reply(400, {"error": "empty upload"})
            if n > self.FILE_LIMIT:
                return self._chat_reply(413, {"error": "file exceeds the 500 MB limit"})
            from urllib.parse import unquote
            fid = uuid.uuid4().hex
            name = os.path.basename(unquote(self.headers.get("X-Kastr-Name") or "file"))[:200] or "file"
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()[:80]
            if not re.match(r"^[a-z0-9.+-]+/[a-z0-9.+-]+$", ctype):
                ctype = "application/octet-stream"
            meta = {"id": fid, "name": name, "size": n, "token": uuid.uuid4().hex,
                    "room": room, "owner": unquote(self.headers.get("X-Kastr-Op") or "")[:64],
                    "kind": "chat", "ctype": ctype, "via": ctx.get("via") or "", "at": int(time.time())}
            path = os.path.join(d, fid)
            self._chat_body_read = True
            got = 0
            with open(path, "wb") as f:
                while got < n:
                    chunk = self.rfile.read(min(1 << 20, n - got))
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
            if got != n:
                try:
                    os.remove(path)
                except OSError:
                    pass
                return self._chat_reply(400, {"error": "short upload"})
            with open(path + ".json", "w", encoding="utf-8") as f:
                json.dump(meta, f)
            store.touch(room)
            if self._room_persistent(room):
                store.mark_keep(room, True)
            return self._json_cors(200, {"id": fid, "name": name, "size": n, "type": ctype,
                                         "url": "/api/chat/%s/files/%s" % (room, fid)})

        def _chat_file_get(self, room, fid, store, head=False):
            """Images the page can show inline come back with their type; anything
            else is a download (octet-stream + attachment), never sniffed."""
            d = self._files_dir()
            if not d:
                return self._chat_reply(404, {"error": "no such file"})
            path = os.path.join(d, fid)
            try:
                with open(path + ".json", encoding="utf-8") as f:
                    meta = json.load(f)
                size = os.path.getsize(path)
            except (OSError, ValueError):
                return self._chat_reply(404, {"error": "no such file"})
            if meta.get("kind") != "chat" or meta.get("room") != room:
                return self._chat_reply(404, {"error": "no such file"})
            from urllib.parse import quote
            ctype = str(meta.get("ctype") or "")
            self.send_response(200)
            if ctype in CHAT_INLINE_TYPES:
                self.send_header("Content-Type", ctype)
            else:
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition",
                                 "attachment; filename*=UTF-8''" + quote(meta.get("name") or "file"))
            self.send_header("Content-Length", str(size))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "private, max-age=3600")
            self._cors()
            self._corp_cross = True
            self.end_headers()
            store.touch(room)
            if head:
                return
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return

        def _hub_token(self, hub):
            """The federation token the running relay dials with, else a mint/cached
            one -> (token | None, info). Open hub (no codes) -> None with hubCodes False."""
            tok = getattr(relay_srv, "_fed_active", None)
            if tok:
                return tok, {"hubCodes": True}
            try:
                tok, _why, info = relay_srv.federation_token(hub["hub"], hub["code"])
                return tok, (info or {})
            except Exception:
                return None, {}

        def _chat_proxy(self, method, room, hub, files=False):
            """A spoke forwards the whole call to the hub's KASTR with its
            federation token; the hub's reply comes back as-is, except a 404
            from a hub without a chat service and a 410 (room closed there)."""
            tok, info = self._hub_token(hub)
            if not tok and info.get("hubCodes"):
                return self._chat_reply(502, {"error": "no federation token for the hub"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            self._chat_body_read = True
            hosttxt = ("[" + hub["host"] + "]") if ":" in hub["host"] else hub["host"]
            target = "http://%s:%d%s" % (hosttxt, hub["web"], self.path)
            headers = {"X-Kastr-Via": self._chat_via()}
            if tok:
                headers["Authorization"] = "Bearer " + tok
            ct = self.headers.get("Content-Type")
            if ct:
                headers["Content-Type"] = ct
            for k in ("X-Kastr-Name", "X-Kastr-Op", "X-Kastr-Jwt", "X-Kastr-Room", "X-Kastr-Owner", "X-Kastr-Kind"):
                v = self.headers.get(k)
                if v:
                    headers[k] = v
            if self._room_persistent(room):
                headers["X-Kastr-Persistent"] = "1"     # the hub keeps the transcript for us
            data = None
            if n > 0:
                if files:
                    data = _BoundedReader(self.rfile, n)
                    headers["Content-Length"] = str(n)
                else:
                    data = self.rfile.read(n)
            req = urllib.request.Request(target, data=data, method=method, headers=headers)
            try:
                r = urllib.request.urlopen(req, timeout=CHAT_FILE_TIMEOUT if files else CHAT_TIMEOUT)
            except urllib.error.HTTPError as e:
                r = e
            except Exception as e:
                return self._chat_reply(502, {"error": "hub KASTR unreachable: %s" % str(e)[:160]})
            with r:
                code = getattr(r, "status", None) or r.code
                hdrs = r.headers
                if code == 404 and "json" not in (hdrs.get("Content-Type") or ""):
                    return self._chat_reply(502, {"error": "hub KASTR is older than 0.12.0 (no chat service)"})
                if code == 410:
                    return self._chat_reply(502, {"error": "hub chat closed this room"})
                self.send_response(code)
                for k in ("Content-Type", "Content-Length", "Content-Disposition", "Cache-Control",
                          "Retry-After", "X-Content-Type-Options"):
                    v = hdrs.get(k)
                    if v:
                        self.send_header(k, v)
                self._cors()
                self._corp_cross = True
                self.end_headers()
                if method == "HEAD":
                    return
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return

        def _chat_unkeep_at_hub(self, slug):
            """A spoke closed a room it kept: tell the hub (X-Kastr-Persistent: 0
            on a one-message read) so the transcript there falls to the idle
            sweep instead of living forever. Best effort, off-thread."""
            hub = self._chat_hub()
            if not hub:
                return
            tok, _info = self._hub_token(hub)
            hosttxt = ("[" + hub["host"] + "]") if ":" in hub["host"] else hub["host"]
            url = "http://%s:%d/api/chat/%s?limit=1" % (hosttxt, hub["web"], slug)
            headers = {"X-Kastr-Via": self._chat_via(), "X-Kastr-Persistent": "0"}
            if tok:
                headers["Authorization"] = "Bearer " + tok

            def go():
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=CHAT_TIMEOUT):
                        pass
                except Exception:
                    pass
            threading.Thread(target=go, daemon=True).start()

        def _rooms_api(self, method, path, qs):
            """The relay's room records for pages anywhere (CORS-open)."""
            store = getattr(relay_srv, "store", None) if relay_srv is not None else None
            if store is None:
                return self._chat_reply(503, {"error": "no relay on this KASTR"})
            log = getattr(relay_srv, "log", None)
            log = log if callable(log) else None
            if path == "/api/rooms/list":
                if method != "GET":
                    return self._chat_reply(405, {"error": "GET only"})
                # 0.15.0: + the relay-defined room groups {gid: {name, order, rooms}}
                return self._json_cors(200, {"rooms": store.rooms_public(), "closed": store.closed_public(),
                                             "groups": store.groups_public()})
            if path == "/api/rooms/group":
                # 0.15.0: a room's creator (roomKey) files its room under a group; the
                # operator's create/rename/delete live on /api/relay/rooms/group.
                if method != "POST":
                    return self._chat_reply(405, {"error": "POST only"})
                p = self._chat_body_json()
                if p is None:
                    return self._chat_reply(413, {"error": "body too large"})
                obj, code = kastr_relay.group_op(store, p, operator=False, log=log)
                return self._chat_reply(code, obj)
            if path == "/api/rooms/register":
                if method != "POST":
                    return self._chat_reply(405, {"error": "POST only"})
                p = self._chat_body_json()
                if p is None:
                    return self._chat_reply(413, {"error": "body too large"})
                obj, code = kastr_relay.register_room(store, p, self._chat_peer(), log, CHAT_LOCKOUT)
                hdrs = {"Retry-After": obj.get("retryAfter", 30)} if code == 429 else None
                return self._chat_reply(code, obj, hdrs)
            if path == "/api/rooms/close":
                if method != "POST":
                    return self._chat_reply(405, {"error": "POST only"})
                p = self._chat_body_json()
                if p is None:
                    return self._chat_reply(413, {"error": "body too large"})
                cs = chat_store(relay_srv=relay_srv)
                hook = (lambda slug, _c=cs: _c.delete_room(slug)) if cs is not None else None
                slug = str(p.get("slug") or "")
                obj, code = kastr_relay.close_room(store, slug, p.get("roomKey"), False, hook=hook, log=log)
                if code == 200:
                    self._chat_unkeep_at_hub(slug)
                return self._chat_reply(code, obj)
            return self._chat_reply(404, {"error": "no such rooms endpoint"})

        def do_DELETE(self):
            path = self.path.split("?", 1)[0]
            if path.startswith("/api/chat/") or path.startswith("/api/rooms/"):   # 0.12.0
                return self._chat_api("DELETE")
            if path.startswith("/api/media/"):   # 0.8.13
                return self._media_delete(path[len("/api/media/"):])
            if path.startswith("/api/files/"):
                qs = parse_qs(urlparse(self.path).query)
                return self._file_delete(path[len("/api/files/"):], (qs.get("token") or [""])[0])
            self.send_error(404, "not found")

        def _relaunch(self):
            """0.8.9: relay-only mode switch -> restart KASTR now (local pages only)."""
            if not self._local():   # 0.17.0: Host + peer + Origin
                return self._json_cors(403, {"error": "relaunch only from the machine itself"})
            if RELAUNCH_HOOK is None:
                return self._json_cors(200, {"status": "dev", "note": "source checkouts do not relaunch"})
            import threading
            threading.Timer(0.6, RELAUNCH_HOOK).start()   # let this reply land first
            # 0.13.1: pid + version so the Relay page can watch the hand-over
            return self._json_cors(200, {"status": "relaunching", "pid": os.getpid(),
                                         "version": read_version()})

        def _relay_name(self):
            try:
                if relay_srv and relay_srv.running():
                    return relay_srv.relay_name() or host_slug()
            except Exception:
                pass
            return ""

        def _quit(self):
            """0.9.8: end KASTR cleanly -- publishers, monitors, relay, window --
            from a local page or a local tool (close-kastr.ps1). Loopback only."""
            h = (self.headers.get("Host") or "").split(":")[0].lower()
            peer = (self.client_address[0] if self.client_address else "") or ""
            if h not in ("127.0.0.1", "localhost") or peer not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
                return self._json_cors(403, {"error": "quit only from the machine itself"})
            if QUIT_HOOK is None:
                return self._json_cors(200, {"status": "dev", "note": "source checkouts stop with Ctrl+C"})
            import threading
            threading.Timer(0.3, QUIT_HOOK).start()       # let this reply land first
            return self._json_cors(200, {"status": "quitting", "pid": os.getpid()})

        def _auth_proxy(self, method):
            """0.8.9: the room-code service (relay host, port+1) is plain http;
            an https page reaches it through its own origin. 0.10.0: the real
            client rides X-Forwarded-For so the minter's lockout counts per
            phone, not per proxy (the minter trusts it from a loopback peer only)."""
            try:
                u = urlparse(relay_ref[0] or BUILTIN_RELAY)
                rh = u.hostname or "127.0.0.1"
                # 0.17.0: the minter honours X-Forwarded-For from a LOOPBACK peer only.
                # When the relay is this very machine (named by its LAN IP), dial it on
                # loopback so every phone's wrong codes count against that phone.
                if rh.lower() in _own_hosts():
                    rh = "127.0.0.1"
                base = "http://%s:%d" % (rh, (u.port or 4443) + 1)
                target = base + self.path
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else None
                peer = (self.client_address[0] if self.client_address else "") or ""
                req = urllib.request.Request(target, data=body, method=method,
                                             headers={"Content-Type": self.headers.get("Content-Type") or "application/json",
                                                      "X-Forwarded-For": peer})
                retry_after = None
                with urllib.request.urlopen(req, timeout=5) as r:
                    data = r.read()
                    code = r.status
            except urllib.error.HTTPError as e:
                data = e.read(); code = e.code
                retry_after = e.headers.get("Retry-After") if e.headers else None   # 0.10.0: lockouts travel through
            except Exception as e:
                return self._json_cors(502, {"error": "room-code service unreachable: %s" % e})
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if retry_after:
                self.send_header("Retry-After", str(retry_after))
            self._cors()
            self._corp_cross = True
            self.end_headers()
            self.wfile.write(data)

        def _probe_codecs(self, path):
            """ffmpeg -i on a (partial) file -> ('h264', 'ac3', 6.0): codec names
            and the container's duration in seconds (0.14.0; 0.0 when N/A)."""
            ff = getattr(bridge, "ffmpeg", None) if bridge else None
            if not ff:
                return None, None, 0.0
            try:
                r = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True, timeout=60,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                err = r.stderr or ""
            except Exception:
                return None, None, 0.0
            v = re.search(r"Stream #\d+:\d+(?:\[[^\]]*\])?(?:\([^)]*\))?: Video: ([A-Za-z0-9_]+)", err)
            a = re.search(r"Stream #\d+:\d+(?:\[[^\]]*\])?(?:\([^)]*\))?: Audio: ([A-Za-z0-9_]+)", err)
            d = re.search(r"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)", err)
            dur = 0.0
            if d:
                try:
                    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))
                except ValueError:
                    dur = 0.0
            # 0.16.0: the video's frame rate ("..., 29.97 fps, ...") -- the owner's composite follows it
            fps = 0.0
            fm = re.search(r"Video:[^\n]*?, ([0-9]+(?:\.[0-9]+)?) fps", err)
            if fm:
                try:
                    fps = float(fm.group(1))
                except ValueError:
                    fps = 0.0
            return (v.group(1).lower() if v else None), (a.group(1).lower() if a else None), dur, fps

        def _media_probe(self):
            """0.8.10: what does the browser need converted? (first MBs of the file)"""
            if not self._local():   # 0.17.0: Host + peer + Origin
                return self._json_cors(403, {"error": "probe only for the machine itself"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0 or n > 64 * 1024 * 1024:
                return self._json_cors(400, {"error": "send the first megabytes of the file"})
            base_dir = os.path.join(self._state_dir() or os.getcwd(), "media")
            os.makedirs(base_dir, exist_ok=True)
            from urllib.parse import unquote
            name = os.path.basename(unquote(self.headers.get("X-Kastr-Name") or "probe.bin"))
            ext = os.path.splitext(name)[1] or ".bin"
            tmp = os.path.join(base_dir, "probe-" + uuid.uuid4().hex + ext)
            got = 0
            with open(tmp, "wb") as f:
                while got < n:
                    chunk = self.rfile.read(min(1 << 20, n - got))
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
            try:
                v, a, dur, fps = self._probe_codecs(tmp)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            cv = bool(v) and not any(v.startswith(x) for x in WEB_VIDEO)
            ca = bool(a) and not any(a.startswith(x) for x in WEB_AUDIO)
            return self._json_cors(200, {"video": v, "audio": a, "duration": dur, "fps": fps, "convertVideo": cv, "convertAudio": ca})   # 0.16.0: + fps

        # ---- 0.14.0: stream-while-converting media (replaces the 0.8.9 convert endpoint) ----
        def _media_local(self):
            return self._local()   # 0.17.0: the request class, not the Host header alone

        def _media_dir(self):
            d = os.path.join(self._state_dir() or os.getcwd(), "media")
            os.makedirs(d, exist_ok=True)
            return d

        def _media_upload(self):
            """POST /api/media/upload?id=<32 hex>: the source lands on disk as it
            arrives (record registered BEFORE the read loop, `got` per chunk), so
            /api/media/<id>/stream can start before the last byte. Reply after
            the last byte carries the probe (codecs + duration)."""
            if not self._media_local():
                return self._json_cors(403, {"error": "media upload only for the machine itself"})
            ff = getattr(bridge, "ffmpeg", None) if bridge else None
            if not ff:
                return self._json_cors(503, {"error": "ffmpeg is not available here"})
            qs = parse_qs(urlparse(self.path).query)
            mid = (qs.get("id") or [""])[0].lower()
            if not MEDIA_ID_RE.match(mid):
                return self._json_cors(400, {"error": "id must be 32 hex characters"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0 or n > MEDIA_UPLOAD_MAX:
                return self._json_cors(400, {"error": "empty or oversized upload"})
            base_dir = self._media_dir()
            from urllib.parse import unquote
            name = os.path.basename(unquote(self.headers.get("X-Kastr-Name") or "media.mkv"))
            ext = re.sub(r"[^a-z0-9]", "", os.path.splitext(name)[1].lower())[:5] or "bin"
            src = os.path.join(base_dir, mid + "." + ext)
            rec = {"path": src, "size": n, "got": 0, "done": False, "aborted": False, "procs": set(),
                   "errors": [], "video": None, "audio": None, "duration": 0.0, "probedAt": -1, "at": time.time()}
            with MEDIA_LOCK:
                taken = mid in MEDIA or bool(_media_find(base_dir, mid))
                if not taken:
                    MEDIA[mid] = rec
            if taken:
                return self._json_cors(409, {"error": "that media id is already in use"})
            got = 0
            read1 = getattr(self.rfile, "read1", None) or self.rfile.read   # read1: what has arrived, not a full MB
            try:
                with open(src, "wb") as f:
                    while got < n:
                        chunk = read1(min(1 << 20, n - got))
                        if not chunk:
                            break
                        f.write(chunk)
                        f.flush()           # a child may be reading the file right now
                        got += len(chunk)
                        rec["got"] = got
            except (OSError, ValueError) as e:
                rec["errors"].append("upload: %s" % e)
            if got < n:
                rec["aborted"] = True
                _media_forget(mid, media_dir=base_dir)
                try:
                    return self._json_cors(400, {"error": "upload ended early", "got": got, "size": n})
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
            rec["done"] = True
            v, a, dur, _fps = self._probe_codecs(src)
            rec["video"], rec["audio"], rec["duration"], rec["probedAt"] = v, a, dur, got
            return self._json_cors(200, {"id": mid, "url": "/api/media/" + mid, "size": n,
                                         "duration": dur, "video": v, "audio": a})

        def _media_adopt(self, mid, base_dir):
            """A source on disk from before a restart -> a complete record."""
            src = _media_find(base_dir, mid)
            if not src:
                return None
            try:
                size = os.path.getsize(src)
            except OSError:
                return None
            v, a, dur, _fps = self._probe_codecs(src)
            rec = {"path": src, "size": size, "got": size, "done": True, "aborted": False, "procs": set(),
                   "errors": [], "video": v, "audio": a, "duration": dur, "probedAt": size, "at": time.time()}
            with MEDIA_LOCK:
                return MEDIA.setdefault(mid, rec)

        @staticmethod
        def _num(x):
            s = "%.3f" % float(x or 0)
            return s.rstrip("0").rstrip(".") if "." in s else s

        def _media_stream(self, mid):
            """GET /api/media/<id>/stream?t=<sec>&v=copy|transcode&a=copy|aac ->
            fragmented MP4 from `t` straight out of ffmpeg (no Content-Length:
            the connection closing is the framing). ONE child per share."""
            if not self._media_local():
                return self._json_cors(403, {"error": "media streams only for the machine itself"})
            ff = getattr(bridge, "ffmpeg", None) if bridge else None
            if not ff:
                return self._json_cors(503, {"error": "ffmpeg is not available here"})
            qs = parse_qs(urlparse(self.path).query)
            try:
                t = float((qs.get("t") or ["0"])[0] or 0)
            except ValueError:
                return self._json_cors(400, {"error": "t must be seconds"})
            if not (t >= 0) or t > 1e7:          # NaN / inf / nonsense
                t = 0.0
            v = ((qs.get("v") or ["copy"])[0] or "copy").lower()
            a = ((qs.get("a") or ["aac"])[0] or "aac").lower()
            if v not in ("copy", "transcode") or a not in ("copy", "aac"):
                return self._json_cors(400, {"error": "v=copy|transcode, a=copy|aac"})
            base_dir = self._media_dir()
            rec = _media_rec(mid) or self._media_adopt(mid, base_dir)
            if rec is None:
                return self._json_cors(404, {"error": "no such media"})
            src = rec["path"]
            if not rec["done"]:
                # The duration sits in the container header, so a partial file
                # has it; look again once the upload grew 4 MB if the first look
                # came up empty.
                if rec.get("probedAt", -1) < 0 or (not rec["duration"] and rec["got"] - rec["probedAt"] >= 4 << 20):
                    pv, pa, pdur, pfps = self._probe_codecs(src)
                    if pfps:
                        rec["fps"] = pfps   # 0.16.0
                    rec["probedAt"] = rec["got"]
                    if pv:
                        rec["video"] = pv
                    if pa:
                        rec["audio"] = pa
                    if pdur:
                        rec["duration"] = pdur
                dur, got, size = rec["duration"], rec["got"], rec["size"]
                if dur and size and t > got / float(size) * dur - 10:
                    return self._json_cors(409, {"error": "not uploaded yet", "uploaded": got / float(size)})
            _media_kill(rec)
            try:
                os.utime(src, None)      # a share still playing after 12 h keeps its file (sweep_media)
            except OSError:
                pass
            # 0.15.1: the transcode uses the machine's hardware H.264 encoder when the bridge has
            # validated one (NVENC / QSV / AMF / MediaFoundation / VA-API -- the RTSP path's list),
            # libx264 superfast otherwise; `q=low` (the page asks for it after two rebuffers) drops
            # to 960 wide / 24 fps so a weak laptop still outruns playback.
            low = (qs.get("q", [""])[0] or "").lower() == "low"
            enc = "libx264"
            try:
                enc = (bridge.usable_encoder() if (bridge and hasattr(bridge, "usable_encoder")) else None) or "libx264"
            except Exception:
                enc = "libx264"
            pre = list(kastr_rtsp.encoder_pre_args(enc)) if enc != "libx264" else []
            vf = "scale='min(%d,iw)':-2,format=yuv420p" % (960 if low else 1280)
            vcodec = ["-vf", kastr_rtsp.encoder_vf(enc, vf), *(["-r", "24"] if low else []), "-c:v", enc]
            if enc == "libx264":
                # 0.16.0: half the cores (at least 2) -- a software transcode used every core and
                # starved the browser's own encoder, so viewers saw the composite hitch (Mikey's share)
                thr = max(2, (os.cpu_count() or 4) // 2)
                vcodec += ["-preset", "ultrafast" if low else "superfast", "-tune", "fastdecode", "-crf", "26" if low else "23", "-threads", str(thr)]
            else:
                vcodec += ["-b:v", "2M" if low else "4M"]
            vcodec += ["-g", "48" if low else "60"]
            argv = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", *pre,
                    *(["-ss", "%.3f" % t] if t > 0 else []),
                    "-i", src, "-map", "0:v:0?", "-map", "0:a:0?", "-copyts",
                    *(["-c:v", "copy"] if v == "copy" else vcodec),
                    *(["-c:a", "copy"] if a == "copy" else ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]),
                    "-f", "mp4", "-movflags", "empty_moov+default_base_moof", "-frag_duration", "500000", "pipe:1"]
            spawn = getattr(bridge, "spawn_media", None) if bridge else None
            try:
                try:
                    proc = (spawn or _spawn_media_plain)(argv, tag="media:" + mid[:8], nice=True)   # 0.16.0: below normal priority
                except TypeError:
                    proc = (spawn or _spawn_media_plain)(argv, tag="media:" + mid[:8])              # an older bridge without `nice`
            except Exception as e:
                return self._json_cors(500, {"error": "ffmpeg failed to start: %s" % e})
            with MEDIA_LOCK:
                rec["procs"].add(proc)
            try:
                first = proc.stdout.read(16384)
            except (OSError, ValueError):
                first = b""
            if not first:
                try:
                    proc.wait(2)
                except Exception:
                    pass
                errs = []
                for _ in range(10):      # the stderr drain may land a beat after exit
                    errs = list(getattr(proc, "kastr_errors", None) or [])
                    if errs:
                        break
                    time.sleep(0.05)
                _media_release_proc(proc)
                with MEDIA_LOCK:
                    rec["procs"].discard(proc)
                    if errs:
                        rec["errors"] = (rec["errors"] + errs)[-20:]
                    msg = "\n".join((errs or rec["errors"])[-5:]) or "ffmpeg produced no output"
                return self._json_cors(502, {"error": msg[-800:], "copy": v == "copy"})
            vc = None
            if rec.get("video"):
                if v == "copy" and rec["video"] in ("hevc", "h265"):
                    vc = "hvc1.1.6.L93.B0"
                else:
                    vc = "avc1.42E01E"      # transcode, h264 copy, or anything else
            ac = None
            if rec.get("audio"):
                ac = "mp4a.40.2"
                if a == "copy":
                    ac = {"ac3": "ac-3", "eac3": "ec-3", "opus": "opus", "flac": "flac", "mp3": "mp4a.40.34"}.get(rec["audio"], ac)
            if not vc and not ac:            # nothing probed at all: assume the common shape
                vc, ac = "avc1.42E01E", "mp4a.40.2"
            codecs = ", ".join(c for c in (vc, ac) if c)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-KASTR-Mime", 'video/mp4; codecs="%s"' % codecs)
            self.send_header("X-KASTR-Copy", "1" if v == "copy" else "0")
            self.send_header("X-KASTR-Encoder", "copy" if v == "copy" else enc + ("/low" if low else ""))   # 0.15.1
            self.send_header("X-KASTR-Fps", self._num(rec.get("fps") or 0))   # 0.16.0
            self.send_header("X-KASTR-Start", self._num(t))
            self.send_header("X-KASTR-Duration", self._num(rec["duration"]))
            self.end_headers()
            # After the headers: governs only the pump (kastr_rtsp.handle_stream discipline)
            self.connection.settimeout(MEDIA_STREAM_TIMEOUT)
            try:
                self.wfile.write(first)
                while True:
                    chunk = proc.stdout.read(16384)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass          # the player seeked, paused out, or left
            finally:
                _media_release_proc(proc)
                with MEDIA_LOCK:
                    rec["procs"].discard(proc)

        def _media_list(self):
            """GET /api/media -> the registry (harness / --diagnose)."""
            if not self._media_local():
                return self._json_cors(403, {"error": "media list only for the machine itself"})
            with MEDIA_LOCK:
                out = [{"id": mid, "size": r.get("size"), "got": r.get("got"), "done": bool(r.get("done")),
                        "aborted": bool(r.get("aborted")), "procs": len(r.get("procs") or ()),
                        "errors": list(r.get("errors") or []), "video": r.get("video"), "audio": r.get("audio"),
                        "duration": r.get("duration")} for mid, r in MEDIA.items()]
            return self._json_cors(200, out)

        def _media_get(self, fn, head=False):
            """0.8.13: the page's <video> streams a file from here by Range
            (instant start, seeking) and the file stays until DELETE or the
            sweeper. 0.14.0: any <id>.<ext> source, typed by its extension."""
            if not MEDIA_FILE_RE.match(fn):
                return self._json_cors(404, {"error": "no such media"})
            path = os.path.join(self._state_dir() or os.getcwd(), "media", fn)
            try:
                size = os.path.getsize(path)
            except OSError:
                return self._json_cors(404, {"error": "no such media"})
            ctype = mimetypes.guess_type(fn)[0] or "video/mp4"
            start, end, partial = 0, size - 1, False
            rng = (self.headers.get("Range") or "").strip()
            m = re.match(r"^bytes=(\d*)-(\d*)$", rng) if rng else None
            if m:
                a, b = m.group(1), m.group(2)
                if a == "" and b:
                    start = max(0, size - int(b))
                else:
                    start = int(a or 0)
                    if b:
                        end = min(size - 1, int(b))
                if size == 0 or start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                partial = True
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if partial:
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if head:
                return
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return   # the player seeked or stopped: normal
                    left -= len(chunk)

        def _media_delete(self, rest):
            """DELETE /api/media/<id> (also <id>/stream, <id>.<ext>; 0.14.0) --
            kill the share's ffmpeg and remove its source."""
            m = re.match(r"^([0-9a-f]{32})(?:/stream|\.[a-z0-9]{1,5})?$", (rest or "").split("?", 1)[0])
            if not self._media_local() or not m:
                return self._json_cors(404, {"error": "no such media"})
            mid = m.group(1)
            _media_forget(mid, media_dir=self._media_dir())
            return self._json_cors(200, {"deleted": mid})

        # ---- 0.14.0: /api/prefs (loopback only: Host + peer + Origin) ----------
        def _prefs_path(self):
            return os.path.join(self._state_dir() or os.getcwd(), "prefs.json")

        def _prefs_get(self):
            """GET /api/prefs -> {"items": {...}}; when prefs.json is missing or
            empty, the bridge's session files stand in ({"seed": true}) and
            nothing is written."""
            if not kastr_relay._local_only(self):
                return self._json_plain(403, {"error": "prefs only for the machine itself"})
            items = prefs_load(self._prefs_path())
            if items is not None:
                return self._json_plain(200, {"items": prefs_filter(items)})
            seed_fn = getattr(bridge, "session_seed", None) if bridge else None
            if seed_fn is not None:
                try:
                    seed = seed_fn() or {}
                except Exception as e:
                    _note("prefs: session_seed failed: %s" % e)
                    seed = {}
                return self._json_plain(200, {"items": prefs_filter(seed), "seed": True})
            return self._json_plain(200, {"items": {}})

        def _prefs_post(self):
            """POST /api/prefs {"set": {key: value | null}} -> 204. The body is
            JSON whatever the Content-Type says (navigator.sendBeacon sends
            text/plain)."""
            if not kastr_relay._local_only(self):
                return self._json_plain(403, {"error": "prefs only for the machine itself"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n > PREFS_BODY_MAX:
                return self._json_plain(413, {"error": "body too large"})
            if n <= 0:
                return self._json_plain(400, {"error": "empty body"})
            try:
                d = json.loads(self.rfile.read(n).decode("utf-8"))
            except Exception:
                return self._json_plain(400, {"error": "body must be JSON"})
            upd = d.get("set") if isinstance(d, dict) else None
            if not isinstance(upd, dict):
                return self._json_plain(400, {"error": 'body must be {"set": {key: value | null}}'})
            try:
                stored = prefs_merge(self._prefs_path(), upd)
                _note("prefs: %d key(s) posted, %d stored" % (len(upd) if isinstance(upd, dict) else -1, len(stored or {})))
            except OSError as e:
                return self._json_plain(500, {"error": "could not write prefs.json: %s" % e})
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def do_POST(self):
            path0 = self.path.split("?", 1)[0]
            if path0.startswith("/api/chat/") or path0.startswith("/api/rooms/"):   # 0.12.0
                return self._chat_api("POST")
            if path0 == "/api/media/upload":       # 0.14.0: stream-while-converting source (convert is gone)
                return self._media_upload()
            if path0 == "/api/media/probe":
                return self._media_probe()
            if path0.startswith("/api/media/"):     # 0.14.0: pagehide beacon: POST ...?_method=DELETE
                qs = parse_qs(urlparse(self.path).query)
                if (qs.get("_method") or [""])[0].upper() == "DELETE":
                    return self._media_delete(path0[len("/api/media/"):])
            if path0 == "/api/prefs":               # 0.14.0
                return self._prefs_post()
            if path0 == "/api/web":                 # 0.17.0: web clients switch
                return self._web_api("POST")
            if path0 in ("/api/ondemand/sync", "/api/ondemand/demand"):   # 0.18.0
                return self._ondemand_api("POST", path0)
            if path0 == "/api/archive":             # 0.18.0: the operator picks what the host records
                return self._archive_api("POST", path0)
            if path0 == "/api/relaunch":
                return self._relaunch()
            if path0 in ("/api/token", "/api/auth", "/api/room", "/api/kick"):   # 0.10.0: /api/room too (https pages hold room locks); 0.17.0: /api/kick
                return self._auth_proxy("POST")
            if path0 == "/api/files":
                return self._file_post()
            if path0.startswith("/api/files/"):
                # sendBeacon fallback for a closing page: POST ...?_method=DELETE
                qs = parse_qs(urlparse(self.path).query)
                if (qs.get("_method") or [""])[0].upper() == "DELETE":
                    return self._file_delete(path0[len("/api/files/"):], (qs.get("token") or [""])[0])
            if self.path.split("?", 1)[0] == "/api/diag":
                return self._diag_post()
            if self.path.split("?", 1)[0] == "/api/window":
                return self._window_post()
            path = self.path.split("?", 1)[0]
            if path == "/api/alive":
                return self._alive()
            if path == "/api/quit":
                return self._quit()       # 0.9.8
            if path == "/api/autorun":
                # Machine-boot autorun (0.8.2). Local pages only.
                if not self._local():   # 0.17.0: Host + peer + Origin
                    body = json.dumps({"error": "autorun changes only from the machine itself"}).encode()
                    self.send_response(403)
                else:
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                        want = bool(json.loads(self.rfile.read(n) or b"{}").get("enabled"))
                    except Exception:
                        want = False
                    body = json.dumps(autorun_set(want)).encode()
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/update/check":
                # 0.8.6: on-demand fleet update. Local pages only. Runs on a
                # thread; progress lands in update-check.json (/api/instance).
                if not self._local():   # 0.17.0: Host + peer + Origin
                    body = json.dumps({"error": "update checks only from the machine itself"}).encode()
                    self.send_response(403)
                else:
                    host = ""
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                        host = str(json.loads(self.rfile.read(n) or b"{}").get("host") or "").strip()
                    except Exception:
                        host = ""
                    if not host:
                        try:
                            host = urlparse(relay_ref[0] or "").hostname or ""
                        except Exception:
                            host = ""
                    if UPDATE_HOOK is None:
                        body = json.dumps({"status": "dev", "host": host}).encode()
                    else:
                        import threading
                        threading.Thread(target=UPDATE_HOOK, args=(host,), daemon=True).start()
                        body = json.dumps({"status": "checking", "host": host}).encode()
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/ini":
                # 0.8.6: allow-listed kastr.ini keys (host, mode). Local only.
                if not self._local():   # 0.17.0: Host + peer + Origin
                    body = json.dumps({"error": "ini changes only from the machine itself"}).encode()
                    self.send_response(403)
                else:
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                        d = json.loads(self.rfile.read(n) or b"{}")
                        key = str(d.get("key") or "")
                        val = d.get("value")
                        if key not in INI_KEYS:
                            raise ValueError("key not allowed: " + key)
                        if val is not None and not re.match(r"^[A-Za-z0-9.:_\-]{1,64}$", str(val)):
                            raise ValueError("bad value")
                        ini_set(key, None if val is None else str(val))
                        body = json.dumps({"key": key, "value": ini_get(key), "path": _ini_file(),
                                           "note": "takes effect at the next launch"}).encode()
                        self.send_response(200)
                    except Exception as e:
                        body = json.dumps({"error": str(e)}).encode()
                        self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/mode":
                # Relay-only mode toggle (0.8.3): edits kastr.ini next to the
                # binary. Local pages only, same guard as autorun.
                if not self._local():   # 0.17.0: Host + peer + Origin
                    body = json.dumps({"error": "mode changes only from the machine itself"}).encode()
                    self.send_response(403)
                else:
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                        d = json.loads(self.rfile.read(n) or b"{}")
                        # 0.12.0: {mode: "viewer" | ...} preferred; {relay: bool} is the 0.8.3 body
                        want = d.get("mode") if d.get("mode") is not None else bool(d.get("relay"))
                        body = json.dumps(mode_set(want)).encode()
                        self.send_response(200)
                    except ValueError as e:   # 0.12.0: unknown mode / bad JSON = the caller's mistake
                        body = json.dumps({"error": str(e)}).encode()
                        self.send_response(400)
                    except Exception as e:
                        body = json.dumps({"error": str(e)}).encode()
                        self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/operator":
                if not self._local():
                    return self._deny("the operator name")   # 0.17.0: a web client would rename the host
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    name = str(json.loads(self.rfile.read(n) or b"{}").get("name") or "")
                except Exception:
                    name = ""
                name = " ".join(name.split())[:30]
                if name:
                    op_ref[0] = name
                    if op_file:
                        try:
                            tmp = op_file + ".tmp"
                            with open(tmp, "w", encoding="utf-8") as f:
                                json.dump({"name": name}, f)
                            os.replace(tmp, op_file)
                        except OSError:
                            pass
                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if bridge and kastr_rtsp.handle_api(self, bridge, path):
                return
            if relay_srv and kastr_relay.handle_api(self, relay_srv, path, self._set_relay):
                return
            self.send_error(404, "not found")

        def _client_api(self):
            """0.17.0: GET /api/client -- what kind of client this page is and what it
            may do here. Open (no secrets), no-store, CORS. `client` is "app" for
            the machine's own window, "web" for another device; a web client's
            masthead polls it (with /api/instance) and reloads when `version`
            moves -- so browser clients always run the relay host's build."""
            local = self._local()
            tls = bool(getattr(self.server, "is_tls", False))
            req_host = kastr_relay._host_of(self.headers.get("Host")) or None
            web = not local
            feats = {"publish": True, "chat": True, "admin": True,
                     "rtsp": not web, "media": not web, "relayControls": not web,
                     "updates": not web, "prefs": not web, "window": not web}
            return self._json_cors(200, {
                "app": "KASTR", "version": read_version(),
                "client": "web" if web else "app",
                "relay": page_relay(relay_ref[0] or BUILTIN_RELAY, tls=tls, req_host=req_host, remote=web),
                "hostMode": MODE,
                "web": int(HTTP_PORT or self.server.server_address[1]),
                "https": HTTPS_INFO.get("port"),
                "trust": HTTPS_INFO.get("trust") or ("local-ca" if HTTPS_INFO.get("ca") else None),
                "ca": "/ca.crt" if HTTPS_INFO.get("ca") else None,
                "hostname": HTTPS_INFO.get("hostname"),
                "closing": bool(CLOSING[0]),
                "now": int(time.time() * 1000),   # 0.18.0: the relay host's clock (latency stamps are corrected to it)
                "features": feats,
            })

        def _web_urls(self):
            """0.17.0: the addresses a device opens, by trust path. Local CA: every LAN IP and
            the mDNS name (the CA must be installed once). Operator certificate: the DNS name
            first, LAN IPs only when they are names IN that certificate (public CAs do not
            issue for private addresses)."""
            import kastr_relay as _kr
            port = HTTPS_INFO.get("port")
            if not port:
                return []
            trust = HTTPS_INFO.get("trust") or "local-ca"
            names = [str(n).lower() for n in (HTTPS_INFO.get("names") or [])]
            hn = HTTPS_INFO.get("hostname")
            out = []
            if trust == "operator":
                if hn:
                    out.append("https://%s:%d/moq-watch-lite.html" % (hn, port))
                for ip in _kr.local_ips():
                    if ip.lower() in names:
                        out.append("https://%s:%d/moq-watch-lite.html" % (ip, port))
            else:
                if hn:
                    out.append("https://%s:%d/moq-watch-lite.html" % (hn, port))
                for ip in _kr.local_ips():
                    out.append("https://%s:%d/moq-watch-lite.html" % (ip, port))
                for n in names:
                    if n.endswith(".local"):
                        out.append("https://%s:%d/moq-watch-lite.html" % (n, port))
            seen, uniq = set(), []
            for u in out:
                if u not in seen:
                    seen.add(u); uniq.append(u)
            return uniq

        def _room_claims(self, room, jwt):
            """0.18.0: None when the caller may act for `room` here (open relay, or a member token
            covering it), else the (code, error) to answer."""
            self._claims = None   # keep-alive: never a previous request's identity
            secured = bool(relay_srv is not None and getattr(relay_srv, "secured", False))
            if not secured:
                return None
            state = self._state_dir()
            key = kastr_relay.read_jwk(state) if state else None
            claims = kastr_relay.verify_token(jwt, key) if (key and jwt) else None
            if claims is None:
                return (401, "token required")
            if room and not kastr_relay.claims_cover(claims, room):
                return (403, "token does not cover this room")
            self._claims = claims
            if self._banned(room, claims):
                return (403, "removed from this room by an admin")
            return None

        def _banned(self, room, claims):
            """0.18.0: a relay-side kick also closes this host's side doors (HLS, archive, on-demand)."""
            auth = getattr(relay_srv, "auth", None) if relay_srv is not None else None
            bans = getattr(auth, "bans", None) if auth is not None else None
            if not bans or not room:
                return None
            _r, host = kastr_relay.claims_identity(claims or {})
            peer = (self.client_address[0] if self.client_address else "") or None
            return bans.hit(room, host, peer)

        def _body_json(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                d = json.loads(self.rfile.read(n) or b"{}") if n else {}
                return d if isinstance(d, dict) else {}
            except Exception:
                return {}

        # ---- 0.18.0: on-demand cameras --------------------------------------------------
        def _ondemand_api(self, method, path):
            qs = parse_qs(urlparse(self.path).query)
            if method == "GET" and path == "/api/ondemand":
                room = (qs.get("room") or [""])[0].strip().lower()
                if not re.match(r"^[a-z0-9-]{1,32}$", room):
                    return self._json_cors(400, {"error": "bad room"})
                bad = self._room_claims(room, (qs.get("jwt") or [""])[0] or (self.headers.get("X-Kastr-Jwt") or ""))
                if bad:
                    return self._json_cors(bad[0], {"error": bad[1]})
                return self._json_cors(200, {"feeds": ondemand_list(room)})
            p = self._body_json()
            if path == "/api/ondemand/sync":
                feeds = p.get("feeds") if isinstance(p.get("feeds"), list) else []
                secured = bool(relay_srv is not None and getattr(relay_srv, "secured", False))
                room = host = None
                if secured:
                    state = self._state_dir()
                    key = kastr_relay.read_jwk(state) if state else None
                    claims = kastr_relay.verify_token(str(p.get("token") or ""), key) if key else None
                    if not claims:
                        return self._json_cors(401, {"error": "token required"})
                    room, host = kastr_relay.claims_identity(claims)
                    if not room:
                        return self._json_cors(403, {"error": "a member token is required"})
                else:
                    first = next((str(f.get("broadcast") or "") for f in feeds if isinstance(f, dict)), "")
                    room = first.split("/", 1)[0]
                wanted = ondemand_sync(room, host, feeds)
                return self._json_cors(200, {"wanted": wanted})
            if path == "/api/ondemand/demand":
                room = str(p.get("room") or "").strip().lower()
                b = str(p.get("broadcast") or "")
                if not re.match(r"^[a-z0-9-]{1,32}$", room) or not b.startswith(room + "/"):
                    return self._json_cors(400, {"error": "bad room or broadcast"})
                bad = self._room_claims(room, str(p.get("jwt") or ""))
                if bad:
                    return self._json_cors(bad[0], {"error": bad[1]})
                return self._json_cors(200, {"ok": True, "known": ondemand_touch(b)})
            return self._json_cors(404, {"error": "unknown endpoint"})

        # ---- 0.18.0: host recording ---------------------------------------------------
        def _archive_api(self, method, path):
            arch = getattr(relay_srv, "archiver", None) if relay_srv is not None else None
            if arch is None:
                return self._json_cors(503, {"error": "recording is not available on this KASTR"})
            qs = parse_qs(urlparse(self.path).query)
            jwt = (qs.get("jwt") or [""])[0] or (self.headers.get("X-Kastr-Jwt") or "")
            if method == "POST":
                if not self._local():
                    return self._deny("recording changes")
                p = self._body_json()
                try:
                    return self._json_plain(200, arch.set(str(p.get("broadcast") or ""), bool(p.get("on"))))
                except ValueError as e:
                    return self._json_plain(400, {"error": str(e)})
            if path == "/api/archive":
                if self._local():
                    return self._json_cors(200, arch.status())
                room = (qs.get("room") or [""])[0].strip().lower()
                if not re.match(r"^[a-z0-9-]{1,32}$", room):
                    return self._json_cors(400, {"error": "room required"})
                bad = self._room_claims(room, jwt)
                if bad:
                    return self._json_cors(bad[0], {"error": bad[1]})
                return self._json_cors(200, arch.status(room))
            b = (qs.get("b") or [""])[0].strip()
            segs = b.split("/")
            if len(segs) < 2 or any(not WATCH_SEG_RE.match(x) for x in segs) or segs[0].startswith("."):
                return self._json_cors(400, {"error": "bad broadcast path"})
            if not self._local():
                bad = self._room_claims(segs[0], jwt)
                if bad:
                    return self._json_cors(bad[0], {"error": bad[1]})
            leaf = segs[-1][:-5] if segs[-1].endswith(".hang") else segs[-1]
            if path == "/api/archive/seg":
                fp = arch.seg_path(b, (qs.get("f") or [""])[0])
                if not fp:
                    return self._json_cors(404, {"error": "no such segment"})
                size = os.path.getsize(fp)
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", 'attachment; filename="%s-%s"' % (leaf, os.path.basename(fp)))
                self.send_header("Cache-Control", "no-store")
                self._cors(); self._corp_cross = True
                self.end_headers()
                try:
                    with open(fp, "rb") as f:
                        while True:
                            chunk = f.read(1 << 20)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                return
            if path == "/api/archive/get":
                def num(k):
                    try:
                        v = (qs.get(k) or [""])[0]
                        return float(v) if v else None
                    except ValueError:
                        return None
                files = arch.range_files(b, num("t0"), num("t1"))
                if not files:
                    return self._json_cors(404, {"error": "nothing recorded in that range"})
                ff = getattr(bridge, "ffmpeg", None) if bridge else None
                if not ff:
                    return self._json_cors(503, {"error": "ffmpeg not available here"})
                import tempfile
                lst = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
                for fp in files:
                    lst.write("file '%s'\n" % fp.replace("\\", "/").replace("'", "'\\''"))
                lst.close()
                argv = [ff, "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst.name,
                        "-c", "copy", "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", "pipe:1"]
                proc = None
                try:
                    proc = (bridge.spawn_media if bridge is not None else _spawn_media_plain)(argv, tag="archive-get")
                    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(num("t0") or time.time()))
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Disposition", 'attachment; filename="%s-%s.mp4"' % (leaf, stamp))
                    self.send_header("Cache-Control", "no-store")
                    self._cors(); self._corp_cross = True
                    self.end_headers()
                    try:
                        while True:
                            chunk = proc.stdout.read(1 << 16)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                finally:
                    if proc is not None:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        try:
                            bridge.release_media(proc)
                        except Exception:
                            pass
                    try:
                        os.remove(lst.name)
                    except OSError:
                        pass
                return
            return self._json_cors(404, {"error": "unknown endpoint"})

        # ---- 0.18.0: HLS -----------------------------------------------------------------
        def _hls_exporter(self, bcast):
            """The shared exporter for `bcast` (started on first use) -> its port, or None."""
            now = time.time()
            with HLS_LOCK:
                rec = HLS.get(bcast)
                if rec and rec["proc"].poll() is None:
                    rec["last"] = now
                    return rec["port"]
            url = relay_srv.operator_url() if relay_srv is not None and hasattr(relay_srv, "operator_url") else None
            moq = getattr(bridge, "moq", None) if bridge else None
            if not url or not moq:
                return None
            port = _free_port()
            argv = [moq, "--log-level", "warn", "--quic-idle-timeout", "15s", "--connect", url, "--broadcast", bcast,
                    "export", "hls", "--listen", "127.0.0.1:%d" % port, "--window", HLS_WINDOW]
            try:
                try:
                    proc = bridge.spawn_media(argv, tag="hls:" + bcast.rsplit("/", 1)[-1][:24], nice=True)
                except TypeError:
                    proc = bridge.spawn_media(argv, tag="hls:" + bcast.rsplit("/", 1)[-1][:24])
            except Exception as e:
                _note("hls: %s failed to start: %s" % (bcast, e))
                return None
            rec = {"proc": proc, "port": port, "last": now, "started": now}
            with HLS_LOCK:
                HLS[bcast] = rec
            blog = getattr(bridge, "log", None) or _note
            blog("hls: exporter for %s on 127.0.0.1:%d (pid %d)" % (bcast, port, proc.pid))

            def reaper(b=bcast, r=rec):
                while r["proc"].poll() is None:
                    time.sleep(5)
                    if time.time() - r["last"] > HLS_IDLE_S:
                        try:
                            r["proc"].kill()
                        except Exception:
                            pass
                        break
                with HLS_LOCK:
                    if HLS.get(b) is r:
                        HLS.pop(b, None)
                try:
                    bridge.release_media(r["proc"])
                except Exception:
                    pass
                blog("hls: exporter for %s stopped after %ds" % (b, time.time() - r["started"]))
            threading.Thread(target=reaper, daemon=True).start()
            # wait until it answers the master playlist (the first segment needs a keyframe) --
            # at most 10 s: a broadcast that is not live yet (an on-demand camera waking) makes
            # the player retry instead of holding this request
            deadline = time.time() + 10
            while time.time() < deadline:
                time.sleep(0.25)
                try:
                    with urllib.request.urlopen("http://127.0.0.1:%d/%s/master.m3u8" % (port, bcast),
                                                timeout=max(0.3, min(1.5, deadline - time.time()))) as r:
                        if r.status == 200:
                            break
                except Exception:
                    pass
            return port

        def _hls_start(self, bcast):
            """GET /api/watch/<b>.m3u8?jwt= -> 302 to the keyed playlist path."""
            if not (relay_srv is not None and relay_srv.running()):
                return self._json_cors(503, {"error": "no relay on this machine -- open the relay host's KASTR"})
            qs = parse_qs(urlparse(self.path).query)
            bad = self._room_claims(bcast.split("/", 1)[0], (qs.get("jwt") or [""])[0] or (self.headers.get("X-Kastr-Jwt") or ""))
            if bad:
                return self._json_cors(bad[0], {"error": bad[1]})
            ondemand_touch(bcast)   # first: an on-demand camera wakes while the exporter starts
            if self._hls_exporter(bcast) is None:
                return self._json_cors(503, {"error": "HLS exporter unavailable"})
            key = uuid.uuid4().hex[:16]
            now = time.time()
            cl = getattr(self, "_claims", None) or {}
            with HLS_LOCK:
                # 0.18.0: the key carries the caller's identity + token expiry (checked on every fetch)
                HLS_KEYS[key] = {"b": bcast, "at": now, "claims": cl, "exp": cl.get("exp")}
                for k in [k for k, v in HLS_KEYS.items() if now - v["at"] > HLS_KEY_IDLE_S]:
                    HLS_KEYS.pop(k, None)
            ondemand_touch(bcast)
            hk = getattr(bridge, "hooks", None)   # 0.18.0: an HLS viewer is a read
            if hk:
                hk.fire("read", bcast, "", "", reason="hls viewer", viewer=(self.client_address[0] if self.client_address else ""))
            self.send_response(302)
            self.send_header("Location", "/api/hls/%s/%s/master.m3u8" % (key, "/".join(quote(x) for x in bcast.split("/"))))
            self.send_header("Cache-Control", "no-store")
            self._cors(); self._corp_cross = True
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _hls_proxy(self, path):
            """GET /api/hls/<key>/<broadcast>/<rest> -> the exporter's /<broadcast>/<rest>."""
            m = re.match(r"^/api/hls/([0-9a-f]{16})/(.+)$", path)
            if not m:
                return self._json_cors(404, {"error": "no such playlist"})
            with HLS_LOCK:
                k = HLS_KEYS.get(m.group(1))
            now = time.time()
            if k and (now - k["at"] > HLS_KEY_IDLE_S or (k.get("exp") and now > float(k["exp"]))):
                with HLS_LOCK:
                    HLS_KEYS.pop(m.group(1), None)
                k = None
            if not k:
                return self._json_cors(403, {"error": "unknown or expired key"})
            if k.get("claims") and self._banned(k["b"].split("/", 1)[0], k["claims"]):
                with HLS_LOCK:
                    HLS_KEYS.pop(m.group(1), None)
                return self._json_cors(403, {"error": "removed from this room by an admin"})
            from urllib.parse import unquote
            rest = unquote(m.group(2))
            if not rest.startswith(k["b"] + "/") or ".." in rest:
                return self._json_cors(403, {"error": "key does not cover this path"})
            k["at"] = time.time()
            port = self._hls_exporter(k["b"])
            if port is None:
                return self._json_cors(503, {"error": "HLS exporter unavailable"})
            ondemand_touch(k["b"])
            q = urlparse(self.path).query
            target = "http://127.0.0.1:%d/%s%s" % (port, "/".join(quote(x) for x in rest.split("/")), ("?" + q) if q else "")
            try:
                with urllib.request.urlopen(target, timeout=15) as r:
                    data = r.read()
                    ctype = r.headers.get("Content-Type") or "application/octet-stream"
                    code = r.status
            except urllib.error.HTTPError as e:
                data, ctype, code = e.read(), e.headers.get("Content-Type") or "text/plain", e.code
            except Exception as e:
                return self._json_cors(502, {"error": "exporter: %s" % str(e)[:120]})
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self._cors(); self._corp_cross = True
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def _watch_stream(self, path):
            """0.17.0: GET /api/watch/<broadcast path>.mp4[?jwt=] -> endless fragmented MP4 of one
            broadcast, consumed from the relay on this machine by the bundled moq CLI. The
            caller's member token governs the subscription (bans apply); an open relay trusts
            the LAN like /api/files. Lifetime = this request; no timers."""
            rel = path[len("/api/watch/"):]
            low = rel.lower()
            if not (low.endswith(".mp4") or low.endswith(".m3u8")):
                return self._json_cors(404, {"error": "use /api/watch/<broadcast>.mp4 (or .m3u8 for HLS)"})
            from urllib.parse import unquote
            bcast = unquote(rel[:-(4 if low.endswith(".mp4") else 5)]).strip("/")
            segs = bcast.split("/")
            if len(segs) < 2 or segs[0].startswith(".") or any(not WATCH_SEG_RE.match(x) for x in segs):
                return self._json_cors(400, {"error": "bad broadcast path"})
            if low.endswith(".m3u8"):
                return self._hls_start(bcast)   # 0.18.0
            if not (relay_srv is not None and relay_srv.running()):
                return self._json_cors(503, {"error": "no relay on this machine -- open the relay host's KASTR"})
            moq = getattr(bridge, "moq", None) if bridge else None
            if not moq:
                return self._json_cors(503, {"error": "moq helper not available here"})
            qs = parse_qs(urlparse(self.path).query)
            jwt = (qs.get("jwt") or [""])[0] or (self.headers.get("X-Kastr-Jwt") or "")
            secured = bool(getattr(relay_srv, "secured", False))
            if secured:
                state = self._state_dir()
                key = kastr_relay.read_jwk(state) if state else None
                claims = kastr_relay.verify_token(jwt, key) if (key and jwt) else None
                if claims is None:
                    return self._json_cors(401, {"error": "token required"})
                if not kastr_relay.claims_cover(claims, segs[0]):
                    return self._json_cors(403, {"error": "token does not cover this room"})
            with _WATCH_LOCK:
                if _WATCH_LIVE[0] >= WATCH_MAX:
                    return self._json_cors(503, {"error": "too many fallback viewers on this relay host (%d)" % WATCH_MAX})
                _WATCH_LIVE[0] += 1
            peer = (self.client_address[0] if self.client_address else "") or "?"
            leaf = segs[-1]
            blog = getattr(bridge, "log", None) or _note
            url = relay_srv.url().rstrip("/") + "/" + (("?jwt=" + jwt) if (secured and jwt) else "")
            argv = [moq, "--log-level", "warn", "--connect-once", "--quic-idle-timeout", "15s",
                    "--connect", url, "--broadcast", bcast,
                    "export", "fmp4", "--max-age", "4s"]   # no --video-name: the native pairs' rendition is not called "video" (measured); 0.18 names renditions; 4 s = join mid-GOP
            proc = None
            try:
                try:
                    proc = bridge.spawn_media(argv, tag="watch:" + leaf[:24], nice=True)
                except TypeError:
                    proc = bridge.spawn_media(argv, tag="watch:" + leaf[:24])
                # the init segment first (a helper thread: `moq` may sit on an absent broadcast)
                # `moq export` writes an empty ftyp+moov first and the real init (with the codec
                # boxes) only when tracks arrive -- gather until the first fragment (moof), 64 KiB
                # or 3 s after the first byte, so X-KASTR-Mime names the codecs
                first = [b""]
                def rd():
                    t_first = None
                    try:
                        while True:
                            chunk = proc.stdout.read(65536)
                            if not chunk:
                                break
                            first[0] += chunk
                            if t_first is None:
                                t_first = time.time()
                            if b"moof" in first[0] or len(first[0]) >= 65536 or time.time() - t_first > 3:
                                break
                    except Exception:
                        pass
                th = threading.Thread(target=rd, daemon=True); th.start(); th.join(12)
                head = first[0]
                if not head:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    err = " | ".join(getattr(proc, "kastr_errors", [])[-3:]) or "no data from the relay within 12 s (is the broadcast live?)"
                    blog("watch: %s for %s failed -- %s" % (bcast, peer, err[:160]))
                    return self._json_cors(502, {"error": err[:300]})
                codecs = _fmp4_codecs(head)
                mime = 'video/mp4; codecs="%s"' % codecs if codecs else "video/mp4"
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("X-KASTR-Mime", mime)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Expose-Headers", "X-KASTR-Mime")
                self._cors()
                self._corp_cross = True
                self.end_headers()
                blog("watch: start %s for %s (%s)" % (bcast, peer, codecs or "unknown codecs"))
                hk = getattr(bridge, "hooks", None)          # 0.18.0: a fallback viewer is a read
                if hk:
                    hk.fire("read", bcast, "", "", reason="fallback viewer", viewer=peer)
                self.connection.settimeout(15)
                t0 = time.time()
                sent = 0
                touched = 0
                try:
                    self.wfile.write(head); sent += len(head)
                    while True:
                        chunk = proc.stdout.read(16384)
                        if not chunk:
                            break
                        self.wfile.write(chunk); sent += len(chunk)
                        if time.time() - touched > 10:       # 0.18.0: keeps an on-demand camera awake
                            touched = time.time()
                            ondemand_touch(bcast)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass   # the viewer left
                blog("watch: end %s for %s after %ds, %d KB" % (bcast, peer, time.time() - t0, sent // 1024))
            finally:
                with _WATCH_LOCK:
                    _WATCH_LIVE[0] = max(0, _WATCH_LIVE[0] - 1)
                if proc is not None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        bridge.release_media(proc)
                    except Exception:
                        pass

        def _mobile(self):
            """0.8.9: what a phone needs -- the https links, the CA, readiness.
            0.17.0: + the trust path (local CA vs operator certificate) and the relay's reach."""
            import kastr_relay as _kr
            port = HTTPS_INFO.get("port")
            ips = _kr.local_ips()
            urls = self._web_urls()
            lan = ["http://%s:%d" % (ip, HTTP_PORT) for ip in ips] if (LAN_OK and HTTP_PORT) else []
            trust = (HTTPS_INFO.get("trust") or "local-ca") if port else None
            relay_running = bool(relay_srv and relay_srv.running())
            return self._json_cors(200, {
                "ready": bool(port), "https": urls, "port": port, "lan": lan,
                "trust": trust,
                "ca": "/ca.crt" if (port and trust == "local-ca") else None, "fingerprint": HTTPS_INFO.get("fingerprint"),
                "names": HTTPS_INFO.get("names") or [],
                "hostname": HTTPS_INFO.get("hostname"),
                "expires": HTTPS_INFO.get("expires"),
                "relayRunning": relay_running,
                "relayLan": bool(relay_running and getattr(relay_srv, "bind_all", False)),
                "note": None if port else (HTTPS_INFO.get("error") and ("HTTPS listener failed: " + HTTPS_INFO["error"])) or (None if port else
                                          ("HTTPS is off -- the web host is loopback only. Turn on "
                                           "'Web clients' (or 'Allow other KASTR machines to update from this one') on "
                                           "the Relay page and relaunch.")),
            })

        def _web_api(self, method):
            """0.17.0: GET/POST /api/web -- the turnkey switch for browser clients. Loopback only.
            on: kastr.ini host = 0.0.0.0, https on, firewall rules for web/https/relay ports;
            off: host removed. Applies at the next launch (Apply & relaunch)."""
            if not self._local():
                return self._deny("web client settings")
            import kastr_relay as _kr
            if method == "POST":
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    want = bool(json.loads(self.rfile.read(n) or b"{}").get("enabled"))
                except Exception:
                    want = False
                try:
                    if want:
                        ini_set("host", "0.0.0.0")
                        if str(ini_get("https") or "").lower() in ("off", "false", "0", "no"):
                            ini_set("https", None)
                        fw = None
                        try:
                            if relay_srv is not None:
                                if not _kr._FIREWALL_WEB_PORT:
                                    _kr._FIREWALL_WEB_PORT = int(HTTP_PORT or self.server.server_address[1])
                                if not _kr._FIREWALL_HTTPS_PORT:
                                    try:
                                        _kr._FIREWALL_HTTPS_PORT = int(ini_get("https_port") or 8443)
                                    except (TypeError, ValueError):
                                        _kr._FIREWALL_HTTPS_PORT = 8443
                                fw = _kr.add_firewall_rules(getattr(relay_srv, "port", None) or 4443)
                        except Exception as e:
                            fw = {"error": str(e)[:200]}
                        _note("web: clients ON by the operator (host=0.0.0.0, firewall %s)" % (json.dumps(fw)[:120] if fw is not None else "untouched"))
                    else:
                        ini_set("host", None)
                        _note("web: clients OFF by the operator (host removed from kastr.ini)")
                except Exception as e:
                    return self._json_plain(500, {"error": str(e)})
            host = ini_get("host")
            enabled = bool(host) and host.strip() not in ("127.0.0.1", "localhost", "::1") \
                and str(ini_get("https") or "").lower() not in ("off", "false", "0", "no")
            live = bool(HTTPS_INFO.get("port")) and LAN_OK
            relay_running = bool(relay_srv and relay_srv.running())
            fw_state = None   # no firewall probe here: it shells out to PowerShell for seconds (the Relay page has its own block)
            return self._json_plain(200, {
                "enabled": enabled or MODE in ("relay", "publisher-relay"),
                "live": live,
                "web": int(HTTP_PORT or self.server.server_address[1]),
                "https": HTTPS_INFO.get("port"),
                "httpsError": HTTPS_INFO.get("error"),
                "trust": HTTPS_INFO.get("trust") if HTTPS_INFO.get("port") else None,
                "hostname": HTTPS_INFO.get("hostname"),
                "expires": HTTPS_INFO.get("expires"),
                "urls": self._web_urls(),
                "lan": ["http://%s:%d" % (ip, HTTP_PORT) for ip in _kr.local_ips()] if (LAN_OK and HTTP_PORT) else [],
                "relayRunning": relay_running,
                "relayLan": bool(relay_running and getattr(relay_srv, "bind_all", False)),
                "firewall": fw_state,
                "relayOnly": MODE in ("relay", "publisher-relay"),
                "hostIni": host,
                "path": _ini_file(),
                "note": None if live else "applies at the next launch -- Apply & relaunch",
            })

        def _ca_cert(self):
            data = None
            try:
                if HTTPS_INFO.get("ca"):
                    with open(HTTPS_INFO["ca"], "rb") as f:
                        data = f.read()
            except OSError:
                data = None
            if not data:
                return self._json_cors(404, {"error": "no certificate authority yet"})
            self.send_response(200)
            self.send_header("Content-Type", "application/x-x509-ca-cert")
            self.send_header("Content-Disposition", "attachment; filename=kastr-ca.crt")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self._corp_cross = True
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path.startswith("/api/chat/") or path.startswith("/api/rooms/"):   # 0.12.0 (NOT /api/rooms itself: the minter proxy)
                return self._chat_api("GET")
            if path.startswith("/api/watch/"):                                # 0.17.0: the fMP4 fallback
                return self._watch_stream(path)
            if path.startswith("/api/hls/"):                                  # 0.18.0: HLS behind a key
                return self._hls_proxy(path)
            if path == "/api/ondemand":                                       # 0.18.0
                return self._ondemand_api("GET", path)
            if path in ("/api/archive", "/api/archive/seg", "/api/archive/get"):   # 0.18.0
                return self._archive_api("GET", path)
            if path == "/ca.crt":
                return self._ca_cert()
            if path == "/api/media":                                        # 0.14.0: the registry
                return self._media_list()
            _ms = re.match(r"^/api/media/([0-9a-f]{32})/stream$", path)      # 0.14.0
            if _ms:
                return self._media_stream(_ms.group(1))
            if path.startswith("/api/media/"):
                return self._media_get(path[len("/api/media/"):])
            if path == "/api/prefs":                                        # 0.14.0
                return self._prefs_get()
            if path == "/api/mobile":
                return self._mobile()
            if path in ("/api/auth", "/api/token", "/api/rooms"):   # 0.11.0: + remembered rooms
                return self._auth_proxy("GET")
            if path == "/api/files":
                return self._file_list(parse_qs(urlparse(self.path).query))
            if path.startswith("/api/files/"):
                return self._file_get(path[len("/api/files/"):])
            if path == "/api/alive":
                return self._alive()
            if path == "/api/instance":
                return self._instance()
            if path == "/api/client":                                       # 0.17.0
                return self._client_api()
            if path == "/api/web":                                          # 0.17.0
                return self._web_api("GET")
            if path in ("/api/autorun", "/api/ini", "/api/mode") and not self._local():
                return self._deny("host settings")   # 0.17.0
            if path == "/api/autorun":
                body = json.dumps(autorun_state()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/ini":
                qs = parse_qs(urlparse(self.path).query)
                key = (qs.get("key") or [""])[0]
                body = json.dumps({"key": key, "value": ini_get(key) if key in INI_KEYS else None}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/peer/instance":
                # 0.8.6: what KASTR runs on another machine (the relay host)
                # -- proxied because a page can't cross-origin fetch it under
                # COEP without CORS.
                qs = parse_qs(urlparse(self.path).query)
                host = (qs.get("host") or [""])[0].strip()
                port = (qs.get("port") or ["8000"])[0]
                data = {"error": "bad host"}
                if not self._local():
                    # 0.17.0: a remote page may ask about THIS machine only (the web
                    # client's "Relay host:" line), never use us to dial elsewhere.
                    try:
                        relay_host = (urlparse(relay_ref[0] or "").hostname or "").lower()
                    except Exception:
                        relay_host = ""
                    if host.strip("[]").lower() in _own_hosts() or (relay_host and host.lower() == relay_host):
                        return self._instance()
                    return self._deny("peer probes")
                if re.match(r"^[A-Za-z0-9.\-\[\]:]{1,253}$", host) and re.match(r"^\d{1,5}$", port):
                    try:
                        import urllib.request
                        with urllib.request.urlopen("http://%s:%s/api/instance" % (host, port), timeout=2) as r:
                            data = json.load(r)
                    except Exception as e:
                        data = {"error": "unreachable", "detail": str(e)[:120]}
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/mode":
                body = json.dumps(mode_state()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/update/manifest":
                plats = _update_platforms()
                bf = _browser_feed()   # 0.9.0
                body = json.dumps({
                    "app": "KASTR", "version": read_version(),
                    "platforms": {k: {"size": v["size"], "sha256": v["sha256"]}
                                  for k, v in plats.items()},
                    "browser": {"version": bf["version"],
                                "platforms": {k: {"size": v["size"], "sha256": v["sha256"], "root": v["root"]}
                                              for k, v in bf["platforms"].items()}},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/update/browser":   # 0.9.0: the bundled browser zip
                plat = (parse_qs(urlparse(self.path).query).get("platform") or [""])[0]
                info = _browser_feed()["platforms"].get(plat)
                if not info:
                    return self.send_error(404, "no browser for that platform here")
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(info["size"]))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    with open(info["path"], "rb") as f:
                        while True:
                            chunk = f.read(1 << 20)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                return
            if path == "/api/update/binary":
                plat = (parse_qs(urlparse(self.path).query).get("platform") or [""])[0]
                info = _update_platforms().get(plat)
                if not info:
                    return self.send_error(404, "no binary for that platform here")
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(info["size"]))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    with open(info["path"], "rb") as f:
                        while True:
                            chunk = f.read(1 << 20)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                return
            if path == "/api/diag":
                return self._diag_get()
            if relay_srv and kastr_relay.handle_api(self, relay_srv, path, self._set_relay):
                return
            if bridge:
                # RTSP endpoints are dynamic, so they must be checked before the
                # static file handler turns the path into a 404.
                if kastr_rtsp.handle_api(self, bridge, path):
                    return
                if kastr_rtsp.handle_stream(self, bridge, path):
                    return
            body = self._rewritten()
            if body is None:
                return super().do_GET()
            self._serve_rewritten(body, include_body=True)

        def do_HEAD(self):
            if self.path.split("?", 1)[0].startswith("/api/chat/"):   # 0.12.0: attachments
                return self._chat_api("HEAD")
            if self.path.split("?", 1)[0].startswith("/api/files/"):   # 0.8.7
                return self._file_get(self.path.split("?", 1)[0][len("/api/files/"):], head=True)
            if self.path.split("?", 1)[0].startswith("/api/media/"):   # 0.8.13
                return self._media_get(self.path.split("?", 1)[0][len("/api/media/"):], head=True)
            body = self._rewritten()
            if body is None:
                return super().do_HEAD()
            self._serve_rewritten(body, include_body=False)

        def log_message(self, fmt, *args):
            if not quiet:
                # None in a windowed build, where there is no console.
                if sys.stderr is not None:
                    sys.stderr.write("%s - %s\n"
                                     % (self.address_string(), fmt % args))

    return partial(Handler, directory=root)


def make_server(root, host="127.0.0.1", port=8000, coep=COEP_MODES[0],
                relay=DEFAULT_RELAY, quiet=False, hostname=None, bridge=None,
                relay_srv=None, alive_ref=None, window_file=None, relay_ref=None):
    """Bind a server. Port 0 asks the OS for a free port.

    Threading matters here: the page pulls several large assets plus worker
    scripts in parallel, a single-threaded server serializes them -- and each
    live RTSP feed holds its connection open indefinitely, which would block
    every other request outright.
    """
    if relay_ref is None:
        relay_ref = [relay]          # 0.8.9: the https listener shares the http one's
    if alive_ref is None:
        alive_ref = [0.0]
    class _Server(ThreadingHTTPServer):
        # 0.14.0: media children die with the server -- the launcher's teardown
        # calls shutdown() (and server_close() on the extra listeners).
        def shutdown(self):
            media_shutdown()
            return super().shutdown()

        def server_close(self):
            media_shutdown()
            return super().server_close()

    srv = _Server(
        (host, port),
        make_handler(root, coep, relay, quiet, hostname, bridge, relay_srv,
                     relay_ref, alive_ref, window_file))
    srv.rtsp = bridge
    srv.relay = relay_srv
    if relay_srv is not None and bridge is not None and getattr(relay_srv, "archiver", None) is None:
        try:   # 0.18.0: host recording (kastr_archive) -- resumes whenever the relay starts
            import kastr_archive
            relay_srv.archiver = kastr_archive.Archiver(relay_srv.state_dir, relay_srv, bridge,
                                                        getattr(relay_srv, "log", None), hours=ARCHIVE_HOURS)
            global ARCHIVE_WANTS
            ARCHIVE_WANTS = lambda b, a=relay_srv.archiver: b in a.enabled
        except Exception as e:
            _note("archive: not available: %s" % e)
    if bridge is not None:
        _MEDIA_BRIDGE[0] = bridge          # 0.14.0: spawn_media / release_media owner
    for src_ in (bridge, relay_srv):
        fn = getattr(src_, "log", None) if src_ is not None else None
        if callable(fn):
            _MEDIA_LOG[0] = fn
            break
    # 0.8.7: shared files older than a day are gone -- sharers delete on leave,
    # but a crashed page cannot.
    try:
        shared = os.path.join(relay_srv.state_dir, "shared") if relay_srv else None
        if shared and os.path.isdir(shared):
            cutoff = time.time() - 86400
            names = os.listdir(shared)
            # 0.12.0: chat attachments live as long as their room (kastr_chat removes them)
            chat_ids = set()
            for fn in names:
                if fn.endswith(".json"):
                    try:
                        with open(os.path.join(shared, fn), encoding="utf-8") as f:
                            if json.load(f).get("kind") == "chat":
                                chat_ids.add(fn[:-5])
                    except Exception:
                        pass
            for fn in names:
                if fn.split(".")[0] in chat_ids:   # 0.12.0
                    continue
                fp = os.path.join(shared, fn)
                try:
                    if os.path.getmtime(fp) < cutoff:
                        os.remove(fp)
                except OSError:
                    pass
        # 0.8.9: converted media is one-shot; anything older than an hour is a leftover
        media = os.path.join(relay_srv.state_dir, "media") if relay_srv else None
        if media and os.path.isdir(media):
            cutoff = time.time() - 3600
            for fn in os.listdir(media):
                fp = os.path.join(media, fn)
                try:
                    if os.path.getmtime(fp) < cutoff:
                        os.remove(fp)
                except OSError:
                    pass
    except Exception:
        pass
    if relay_srv is not None:
        start_chat_sweeper(relay_srv)   # 0.12.0: idle transcripts go hourly (kept rooms stay); once per process
    srv.relay_ref = relay_ref
    srv.alive_ref = alive_ref
    return srv


def make_bridge(state_dir=None, log=None, hostname=None):
    """An RTSP bridge; reports ffmpeg availability via its .ffmpeg attribute.
    0.9.8: `state_dir` hosts the child registry, `log` the launcher's note().
    0.13.0: `hostname` must be the SAME value the launcher gives make_server /
    make_handler (both None today): the bridge's publishers mint tokens scoped
    to host_slug(hostname), and the page's HOSTNAME comes from the same slug."""
    b = kastr_rtsp.Bridge(state_dir=state_dir, log=log, host_slug=host_slug(hostname))
    b.web_base_for = _od_web_base      # 0.18.0: where the on-demand loop syncs
    return b


def make_relay(state_dir, log=None):
    """A supervisor for the bundled moq-relay (0.10.0: with the launcher's log)."""
    return kastr_relay.Relay(state_dir, log)


def make_tls_server(root, host, port, tls_paths, **kw):
    """0.8.9: the same site over HTTPS (phones). `tls_paths` from kastr_tls.ensure."""
    import kastr_tls
    try:
        srv = make_server(root, host, port, **kw)
    except OSError:
        srv = make_server(root, host, 0, **kw)
    ctx = kastr_tls.ssl_context(tls_paths)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.is_tls = True
    srv.tls_ctx = ctx      # 0.17.0: kept so reload_tls can swap the chain in place
    return srv


def reload_tls(srv, tls_paths):
    """0.17.0: load a new certificate chain into the running https listener. OpenSSL
    applies it to new handshakes; connections already open finish on the old one."""
    ctx = getattr(srv, "tls_ctx", None)
    if ctx is None:
        raise RuntimeError("listener has no TLS context")
    ctx.load_cert_chain(tls_paths["chain"], tls_paths["key"])


def bind_free(root, host="127.0.0.1", preferred=8000, **kw):
    """Try the preferred port, then fall back to an OS-assigned one.

    A packaged app can't assume 8000 is free -- another copy of itself, or any
    other dev server, may already hold it.
    """
    try:
        return make_server(root, host, preferred, **kw)
    except OSError:
        return make_server(root, host, 0, **kw)
