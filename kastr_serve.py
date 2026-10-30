#!/usr/bin/env python3
"""KASTR's HTTP server: the pages and the whole local API.

Used by both kastr-serve.py (plain CLI) and kastr.py (packaged app), so the two
cannot drift apart.

Pages: every document is served with COOP/COEP headers, so it is cross-origin
isolated and SharedArrayBuffer is available (@moq/watch's reliable audio path
needs it; without isolation it silently falls back to a postMessage path that
can stall). Pages are rewritten on the way out -- this machine's name, the
version, the client class and the relay address replace placeholders (the
prebuilt stats bundle has `http://localhost:4443` baked in and reads no
override) -- so the files on disk stay pristine and the relay lives in one
place.

API (/api/*): instance and diagnostics, the RTSP bridge (kastr_rtsp), the
bundled relay's control plane and token service (kastr_relay), chat, media,
archive, the fMP4 stream watch.html plays (/api/watch/), fleet updates and
install downloads.
"""
import hashlib
import json
import kastr_ua  # noqa: F401  -- 0.21.64: every request says KASTR (Cloudflare refuses Python-urllib)
import mimetypes      # 0.14.0: media sources keep their own extension
import os
import re
import socket
import struct         # 0.21.0: fmp4_start reads the muxer's edit list
import sys
import time
import uuid

_SERVE_T0 = time.time()   # 0.21.61: when this KASTR started (justUpdated below)
import subprocess
import threading      # 0.12.0
from urllib.parse import quote, parse_qs, urlparse
import urllib.request
import urllib.error
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import kastr_relay
import kastr_rtsp
import kastr_secret   # 0.21.92: secrets at rest sealed, logs and diag masked
import kastr_release   # 0.21.7: the install zip a web client downloads, assembled on this host

# The string baked into the prebuilt bundles.
BUILTIN_RELAY = "http://localhost:4443"

# Placeholder the pages carry; replaced with this machine's name as they are
# served. Broadcast names must be unique per machine or two publishers collide
# on the relay and clobber each other -- which is exactly what the upstream
# demo's hardcoded "me.hang" does on every computer that opens it.
HOST_TOKEN = "__ASI_HOSTNAME__"

# 0.17.0: who the page is being served to -- "app" for the machine's own window,
# "web" for a browser on another device that opened this relay host's web port.
# Substituted per request like the hostname; the page reads it synchronously.
CLIENT_TOKEN = "__KASTR_CLIENT__"

# Replaced with the build's version as pages are served.
VERSION_TOKEN = "__KASTR_VERSION__"
PRECACHE_TOKEN = "__KASTR_PRECACHE__"   # 0.20.0: sw.js -- the JSON list of shell files to cache
_PRECACHE = [None]                       # computed once per process from the served folder


def precache_list(root):
    """0.20.0: what the service worker caches at install -- the shell pages, the brand and
    client scripts, icons, and every vendored ESM file (about 3 MB). Never mediapipe, the
    noise model or the scenes (cached on first use), never anything under /api/."""
    if _PRECACHE[0] is not None:
        return _PRECACHE[0]
    out = ["/moq-watch-lite.html", "/index.html", "/watch.html", "/manifest.webmanifest",
           "/assets/asi-brand.css", "/assets/asi-brand.js", "/assets/client.js", "/assets/prefs.js",
           "/assets/asi-favicon.svg", "/assets/asi-logo.svg", "/assets/asi-logo-dark.svg",
           "/assets/kastr-pres.js"]   # 0.21.84: the page's presentation module (pdf.js itself is cached on first use)
    out.append("/assets/kastr-presrec.js")   # 0.21.92 H: record the presentation (the switch, Recordings, the recorder page)
    out.append("/assets/vault.js")   # 0.21.92: the codes in the browser's storage kept wrapped
    out.append("/assets/kastr-msg.js")   # 0.21.88: private messages (end-to-end encrypted)
    out.append("/assets/kastr-gif.js")   # 0.21.91: the GIF picker (Messages + Room Chat)
    out.append("/assets/kastr-rcf.js")   # 0.21.92: remote-control files (the app page, rcx.html, rcx-agent.html)
    out.append("/assets/kastr-pmreset.js")   # 0.21.91 passcode reset: the admin's Reset My room passcode dialog (People + Relay page)
    for sub in ("assets/icons", "assets/vendor/esm"):
        base = os.path.join(root, sub)
        for dp, _dn, fns in os.walk(base):
            for fn in sorted(fns):
                rel = os.path.relpath(os.path.join(dp, fn), root).replace(os.sep, "/")
                if not fn.startswith(".") and rel not in out:
                    out.append("/" + rel)
    out = [p for p in out if os.path.isfile(os.path.join(root, p.lstrip("/")))]
    _PRECACHE[0] = out
    return out


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


_VERSION_STAMP = [None]   # 0.21.4: read once per process; stamped on every response


def version_stamp():
    """0.21.4: the version this server stamps on every response as X-KASTR-Version. A browser's
    service worker compares it with its own and stands aside when the host has moved on (an iPhone
    showed the 0.20.0 masthead under a 0.21.3 host for a week and reloaded forever)."""
    if _VERSION_STAMP[0] is None:
        _VERSION_STAMP[0] = read_version()
    return _VERSION_STAMP[0]



# ---- 0.21.75: room invite links -- the app hand-off ------------------------------------------------------------------
# Kenton: "the link opens the installed KASTR app if present, otherwise the host's web page". The /join page tries
# kastr://join?i=<token>&room=<slug>&relay=<relay>; Windows starts KASTR.exe --invite "<that URL>" (kastr.py registers the
# scheme). A fresh start sets it here before the window opens; a second launch POSTs it to the running instance
# (/api/invite/pending, loopback). The page takes it ONCE (GET, loopback) within INVITE_PENDING_S -- an update relaunch
# re-runs argv, and kastr.py strips the invite from argv so it is never replayed.
INVITE_PENDING = [None]
INVITE_PENDING_S = 120
# 0.21.86 (Kenton: a coworker's invite link "opened the app and then took him straight to the lobby" -- the app updated itself
# right after the click, the relaunch had no invite and the update's resume put him back where he was): the invite is also
# kept on disk for INVITE_PENDING_S, and a NEW KASTR process (the update / restart relaunch) offers it to its page once more.
INVITE_FILE = [None]
_INVITE_TOKEN_RE = re.compile(r"^ki-[0-9a-f]{8}-[A-Za-z0-9_-]{32,64}$")


def window_geom_ok(geom):
    """0.21.84 (Kenton: after an upgrade KASTR sometimes didn't come back in the same window state): only a real window's bounds
    are kept. Windows reports a minimized window at about -32000 with a tiny size; saved, the launcher refused it and opened
    maximized. Maximized is a state and is always kept."""
    if not isinstance(geom, dict):
        return False
    if geom.get("maximized") is True:
        return True
    try:
        x, y, w, h = int(geom["x"]), int(geom["y"]), int(geom["w"]), int(geom["h"])
    except (KeyError, TypeError, ValueError):
        return False
    return x > -30000 and y > -30000 and 320 <= w <= 20000 and 240 <= h <= 20000


def native_kastr_zoomed(geom):
    """0.21.91 (Kenton: "The KASTR window isn't starting as maximized, just as expanded most of the way"): the page guesses
    "maximized" from its size against the screen, which missed at his 200 % scale, so a maximized window was saved as a large
    plain one and came back "expanded most of the way". On Windows, ask the window itself: a visible KASTR browser window that
    IS maximized (IsZoomed) and has the reported size is maximized, whatever the guess said."""
    if sys.platform != "win32" or not isinstance(geom, dict):
        return False
    try:
        import ctypes
        from ctypes import wintypes as wt
        u = ctypes.windll.user32
        try:
            old = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # per-monitor v2 on this thread: physical pixels
        except Exception:
            old = None
        gw, gh = float(geom.get("w") or 0), float(geom.get("h") or 0)
        hit = []
        proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def cb(h, _):
            try:
                if not u.IsWindowVisible(h) or not u.IsZoomed(h):
                    return True
                cls = ctypes.create_unicode_buffer(64)
                u.GetClassNameW(h, cls, 64)
                if not cls.value.startswith("Chrome_WidgetWin"):
                    return True
                t = ctypes.create_unicode_buffer(256)
                u.GetWindowTextW(h, t, 256)
                if "KASTR" not in t.value:
                    return True
                r = wt.RECT()
                u.GetWindowRect(h, ctypes.byref(r))
                sc = (u.GetDpiForWindow(h) or 96) / 96.0
                if abs((r.right - r.left) / sc - gw) <= 40 and abs((r.bottom - r.top) / sc - gh) <= 40:
                    hit.append(h)
            except Exception:
                pass
            return True
        u.EnumWindows(proc(cb), 0)
        try:
            if old is not None:
                u.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))
        except Exception:
            pass
        return bool(hit)
    except Exception:
        return False


def invite_parse(url):
    """kastr://join?i=..&room=..&relay=.. (or a /join#i=.. link, or ?invite=) -> {token, room, relay} or None."""
    s = str(url or "").strip()[:2048]
    if not s:
        return None
    q = ""
    for sep in ("#", "?"):
        if sep in s:
            q = s.split(sep, 1)[1]
            break
    try:
        d = parse_qs(q.replace("#", "&"))
    except Exception:
        return None
    tok = ((d.get("i") or d.get("invite") or [""])[0]).strip()
    room = ((d.get("room") or [""])[0]).strip().lower()
    relay = ((d.get("relay") or [""])[0]).strip()
    if not _INVITE_TOKEN_RE.match(tok) or not kastr_relay.SLUG_RE.match(room) or room == kastr_relay.LOBBY_SLUG:
        return None
    if relay and not re.match(r"^https?://[A-Za-z0-9.\-\[\]:]{1,260}(/[A-Za-z0-9._~/-]{0,64})?$", relay):
        relay = ""
    return {"token": tok, "room": room, "relay": relay}


def invite_pending_set(url):
    """-> True when the URL was a usable invite (kept for the page to take within INVITE_PENDING_S)."""
    inv = invite_parse(url)
    if inv is None:
        return False
    INVITE_PENDING[0] = dict(inv, at=time.time())
    if INVITE_FILE[0]:
        try:
            tmp = INVITE_FILE[0] + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:   # 0.21.92: the invite token sealed
                json.dump(kastr_secret.seal_doc(INVITE_FILE[0], INVITE_PENDING[0]), f)
            if os.name != "nt":
                os.chmod(tmp, 0o600)
            os.replace(tmp, INVITE_FILE[0])
        except OSError:
            pass
    return True


def invite_pending_restore(path, now=None):
    """0.21.86: at start -- an invite opened less than INVITE_PENDING_S ago (before an update / restart relaunch) is pending
    again. The file goes once it is older."""
    INVITE_FILE[0] = path
    now = time.time() if now is None else now
    try:
        with open(path, encoding="utf-8-sig") as f:
            inv = kastr_secret.open_doc(path, json.load(f))   # 0.21.92: the sealed token opened
    except (OSError, ValueError):
        return False
    at = float((inv or {}).get("at") or 0) if isinstance(inv, dict) else 0
    if not at or now - at > INVITE_PENDING_S:
        try:
            os.remove(path)
        except OSError:
            pass
        return False
    ok = invite_parse("kastr://join?i=%s&room=%s&relay=%s" % (inv.get("token") or "", inv.get("room") or "", quote(str(inv.get("relay") or ""), safe="")))
    if not ok:
        return False
    INVITE_PENDING[0] = dict(ok, at=at)
    return True


def invite_pending_take():
    """The pending invite, once (None when there is none or it is older than INVITE_PENDING_S)."""
    inv, INVITE_PENDING[0] = INVITE_PENDING[0], None
    if not inv or time.time() - float(inv.get("at") or 0) > INVITE_PENDING_S:
        return None
    return {k: inv[k] for k in ("token", "room", "relay")}


# 0.21.92 (Kenton: "add the auto-start KASTR option on startup into the options available to everyone, not just admins"): the
# Profile menu has the switch too, plus "Start minimized" -- the Run key / autostart entry then carries AUTORUN_FLAG, and that
# launch opens the window minimized (still connecting, still going straight into the main room). The choice is kept in
# autorun.json in the state folder, so the Relay page's switch (which knows nothing of it) rewrites the entry with the same flag.
AUTORUN_FLAG = "--minimized"
_AUTORUN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTORUN_FLAG_RE = re.compile(r"(?:^|\s)--minimized(?:\s|$)")


def _autorun_pref_file():
    return os.path.join(STATE_DIR, "autorun.json") if STATE_DIR else None


def autorun_pref_minimized():
    """The saved "Start minimized" choice (False when never set)."""
    p = _autorun_pref_file()
    if not p:
        return False
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("minimized") is True
    except (OSError, ValueError, AttributeError):
        return False


def _autorun_pref_save(minimized):
    p = _autorun_pref_file()
    if not p:
        return
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"minimized": bool(minimized)}, f)
        os.replace(tmp, p)
    except OSError:
        pass


def _autorun_desktop():
    return os.path.expanduser("~/.config/autostart/kastr.desktop")


def _autorun_read():
    """-> the command KASTR's autorun entry runs ("" when there is none). Windows: the HKCU Run value; Linux: the Exec line."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTORUN_RUN_KEY) as k:
                val, _ = winreg.QueryValueEx(k, "KASTR")
            return str(val or "")
        except OSError:
            return ""
    try:
        with open(_autorun_desktop(), encoding="utf-8") as f:
            for line in f:
                if line.startswith("Exec="):
                    return line[5:].strip() or " "
        return " "   # an entry without an Exec line is still ours to report (0.8.2 judged by the file alone)
    except OSError:
        return ""


def _autorun_command(exe, minimized):
    return '"%s"%s' % (exe, (" " + AUTORUN_FLAG) if minimized else "")


def _autorun_write(exe, enabled, minimized):
    if sys.platform == "win32":
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _AUTORUN_RUN_KEY) as k:
            if enabled:
                winreg.SetValueEx(k, "KASTR", 0, winreg.REG_SZ, _autorun_command(exe, minimized))
            else:
                try:
                    winreg.DeleteValue(k, "KASTR")
                except OSError:
                    pass
        return
    desk = _autorun_desktop()
    if enabled:
        os.makedirs(os.path.dirname(desk), exist_ok=True)
        with open(desk, "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\nType=Application\nName=KASTR\n"
                    "Comment=Kenton's ASI Streaming Tool with Relay\n"
                    "Exec=%s\nX-GNOME-Autostart-enabled=true\n" % _autorun_command(exe, minimized))
    else:
        try:
            os.remove(desk)
        except OSError:
            pass


def autorun_state():
    """Is KASTR registered to start with this machine? Per-user, no admin.
    Windows: HKCU Run key; Linux: ~/.config/autostart. Frozen builds only
    (a dev checkout has no stable exe to point at).
    0.21.92: + minimized -- the entry's own flag while it is on, the saved choice while it is off."""
    if not getattr(sys, "frozen", False):
        return {"enabled": False, "supported": False, "minimized": False,
                "note": "autorun applies to the installed app, not a source checkout"}
    exe = sys.executable
    cmd = _autorun_read()
    if sys.platform == "win32":
        enabled = bool(cmd) and exe.lower() in cmd.lower()
    else:
        enabled = bool(cmd)
    minimized = bool(_AUTORUN_FLAG_RE.search(cmd)) if enabled else autorun_pref_minimized()
    return {"enabled": enabled, "supported": True, "minimized": minimized}


def autorun_set(enabled, minimized=None):
    """Turn KASTR's autorun entry on (written fresh, with the "Start minimized" flag when chosen) or off (the entry goes).
    `minimized` None = keep the saved choice (the Relay page's switch); True / False = save it."""
    if not getattr(sys, "frozen", False):
        return {"error": "autorun is for the installed app (frozen builds) only"}
    if minimized is not None:
        _autorun_pref_save(bool(minimized))
    flag = autorun_pref_minimized() if minimized is None else bool(minimized)
    _autorun_write(sys.executable, bool(enabled), flag)
    return {"ok": True, "enabled": bool(enabled), "minimized": flag}


def autorun_flag_fix(keep):
    """0.21.92: the launcher's repair of the entry's flag, never its on / off. keep=False drops --minimized (before this
    machine moves to a KASTR older than 0.21.92, whose launcher would refuse the unknown flag and never start at sign-in);
    keep=True puts it back when the saved choice says so (after such a version came and went). -> what it did ("" = nothing)."""
    if not getattr(sys, "frozen", False):
        return ""
    st = autorun_state()
    if not st.get("enabled"):
        return ""
    has = bool(_AUTORUN_FLAG_RE.search(_autorun_read()))
    if keep and has:
        return ""   # only ever puts it back -- a flag the saved choice does not know of stays (a reset state folder)
    want = bool(keep) and autorun_pref_minimized()
    if has == want:
        return ""
    try:
        _autorun_write(sys.executable, True, want)
    except OSError as e:
        return "could not rewrite the autorun entry (%s)" % e
    return "start minimized flag " + ("restored" if want else "dropped")


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


# 0.21.32 (Kenton: "I don't have the ability to turn off the web client toggle" -- "I am going to turn it off on most
# relays"): a relay box must keep its web port on the network (spokes reach the hub there: updates, rooms, chat,
# federation), so on a relay the switch no longer closes the port -- `web_page = off` in kastr.ini stops handing the
# PAGE to browsers on other devices while every /api/ route and the /relay pipe stay open. Read once, then cached.
_WEB_PAGE_OFF = [None]


def web_page_off():
    if _WEB_PAGE_OFF[0] is None:
        _WEB_PAGE_OFF[0] = str(ini_get("web_page") or "").strip().lower() in ("off", "false", "0", "no")
    return _WEB_PAGE_OFF[0]


def set_web_page(on):
    ini_set("web_page", None if on else "off")
    _WEB_PAGE_OFF[0] = not on


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
    was = str(ini_get("mode") or "full").strip().lower()
    ini_set("mode", None if mode == "full" else mode)
    # 0.21.37 (Kenton: "When setting a device as a relay, keep web-client access off by default"): becoming a relay box
    # turns the page for other devices off (the Relay page's Web clients switch turns it back on). Only on the change --
    # a relay that already serves web clients (the tunnel's hub) keeps them across updates.
    if mode in ("relay", "publisher-relay") and was not in ("relay", "publisher-relay"):
        try:
            set_web_page(False)
        except Exception:
            pass
    return mode_state()


def host_slug(name=None):
    """This machine's name, reduced to something safe in a MoQ path, plus a
    stable per-machine suffix. Cloned images (normal on robot boxes) share a
    hostname, and identical host segments mean byte-identical broadcast
    paths: they collide on the relay AND every device suppresses the other's
    tile as "its own" -- each machine then sees only itself. The suffix comes
    from a MAC address (host_suffix: kept in the state folder, 0.21.46)."""
    raw = name or socket.gethostname() or "host"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.split(".")[0].lower()).strip("-")
    slug = slug[:32] or "host"
    return "%s-%04x" % (slug, host_suffix())


# 0.21.46 (field, Southridge): uuid.getnode() reads "a" MAC at every launch -- with VPN / virtual / USB adapters coming
# and going (or none readable: a RANDOM node) the suffix changed between launches (obs-svr-1980 -> obs-svr-395f). The
# box's restored camera pairs kept publishing under the OLD host segment, which its token no longer grants: the relay
# refused them and every full-quality stream from that site vanished while the grid (published fresh) kept working.
# Now the suffix is chosen once and kept in <state>/host-id with the MAC it came from; it is kept while that MAC is still
# one of this machine's adapters (adapters coming and going never move it). A cloned image carrying the file onto other
# hardware (that MAC absent) or a replaced network card gets a fresh suffix -- the clone rule above still holds.
_HOST_SUFFIX = None


def _machine_macs():
    """Every adapter MAC this machine reports, as 12 lower-case hex digits; empty when it cannot tell."""
    out = set()
    try:
        if sys.platform.startswith("linux"):
            for nic in os.listdir("/sys/class/net"):
                try:
                    with open("/sys/class/net/%s/address" % nic, encoding="ascii") as f:
                        out.add(f.read().strip().lower().replace(":", ""))
                except OSError:
                    pass
        else:
            cmd = ["getmac", "/fo", "csv", "/nh", "/v"] if sys.platform == "win32" else ["ifconfig", "-a"]
            kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # CREATE_NO_WINDOW
            txt = subprocess.run(cmd, capture_output=True, text=True, timeout=8, **kw).stdout or ""
            for m in re.finditer(r"(?i)\b([0-9a-f]{2}(?:[-:][0-9a-f]{2}){5})\b", txt):
                out.add(re.sub(r"[-:]", "", m.group(1).lower()))
    except Exception:
        pass
    out.discard("000000000000")
    return out


def host_suffix():
    global _HOST_SUFFIX
    if _HOST_SUFFIX is not None:
        return _HOST_SUFFIX
    node = uuid.getnode()
    real = not (node >> 40) & 1          # the multicast bit marks uuid's random fallback
    mac = "%012x" % node
    path = os.path.join(STATE_DIR, "host-id") if STATE_DIR else None
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
            sfx, smac = int(rec.get("suffix")) & 0xFFFF, str(rec.get("mac") or "").lower()
            if smac == mac or (smac and smac in _machine_macs()) or (not real and smac):
                _HOST_SUFFIX = sfx       # the same machine: keep the name it has always had
                return sfx
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    sfx = node & 0xFFFF
    if not path:
        return sfx                       # no state folder yet (a harness, or before launch set it): not kept
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"suffix": sfx, "mac": mac if real else "", "at": int(time.time())}, f)
        os.replace(tmp, path)
    except OSError:
        pass
    _HOST_SUFFIX = sfx
    return sfx

# 0.21.93 (Kenton: "use the web address as the relay on the first run, then have the hub distribute the known relays"): the
# ONLY relay address built in -- the fleet's public web address, reached through Cloudflare (WebSocket). The hub hands every
# member its registry after the access code and the app moves to the fastest relay; no private IPs ship in the app. kastr.ini
# `relay =` and --relay still override it; KASTR_DEFAULT_RELAY replaces it for labs and tests (never production).
WEB_RELAY = "https://kastr.madlabs.app/relay"


def _default_relay():
    v = str(os.environ.get("KASTR_DEFAULT_RELAY") or "").strip()
    return v if re.match(r"^(https?|wss?)://[A-Za-z0-9._~%\-\[\]:]+(/[A-Za-z0-9._~/-]*)?$", v) else WEB_RELAY


DEFAULT_RELAY = _default_relay()
WEB_RELAY_TOKEN = "__KASTR_WEB_RELAY__"   # 0.21.93: the pages' first-run / last-resort relay (DEFAULT_RELAY)

# 0.8.6: the launcher installs its on-demand updater here (None in a dev
# harness -- source checkouts never self-update).
UPDATE_HOOK = None
FEDERATION_UPDATE_HOOK = None   # 0.21.0: the launcher's "match the federation master now" (a hub command)
# 0.21.50: an Update pressed for THIS app on a Relay page (it arrives in the check-in reply): {version, host, at, deadline,
# state: "asked" | "deferred" | "updating"}; the page asks the person (Update now / In 10 minutes), the launcher updates by
# itself at the deadline (or at once with no page open / on an unattended box)
UPDATE_OFFER = {}
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
    msg = kastr_secret.mask(msg)   # 0.21.92
    try:
        if callable(fn):
            fn(msg)
        elif sys.stderr is not None:
            sys.stderr.write(msg + "\n")
    except Exception:
        pass


# 0.21.94 (Kenton: "Can KASTR read the Windows Studio effects for the blur and background options?"): the camera driver's own
# background blur (KSPROPERTY_CAMERACONTROL_EXTENDED_BACKGROUNDSEGMENTATION) through kastr_studiofx's helper process. Local
# pages only; started on first use; the helper puts every camera back when KASTR closes (or dies: its pipe closes).
_STUDIOFX = [None]
_STUDIOFX_LOCK = threading.Lock()


def studiofx():
    with _STUDIOFX_LOCK:
        if _STUDIOFX[0] is None:
            import kastr_studiofx
            import atexit
            fx = kastr_studiofx.StudioFx(log=_note)
            atexit.register(fx.close)
            _STUDIOFX[0] = fx
        return _STUDIOFX[0]


def studiofx_state():
    """For /api/diag: what the Studio Effects side did this run (no helper is started for it)."""
    fx = _STUDIOFX[0]
    if fx is None:
        return {"used": False}
    cams = (fx.cache or {}).get("cams") or []
    return {"used": True, "held": len(fx.held), "deaths": fx.deaths, "error": fx.last_error or "",
            "cams": [{"name": c.get("name"), "blur": c.get("blur"), "mask": c.get("mask"), "shallow": c.get("shallow"),
                      "on": c.get("on")} for c in cams]}


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
                         r"|channels\.mine$|channel$|operator\.name$|publishOnly$|rail\.w$|pres\.(layout|notesSize)$|watch\.|camfx$|share\.locked$|toasts\.|rooms\.groups\.|mainroom$|view\.hideMine$"
                         r"|theme$|theme\.custom$|accent$|selfmirror$)")   # 0.21.72: + theme, custom colours, accent; 0.21.91: + view.hideMine (Hide my shares); 0.21.92: + the presenter view's layout + notes size, + mainroom (the page kept it since 0.21.91); 0.21.96: + share.locked (locked shares: no codes, no camera URLs)
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
    if key == "kastr.lastjoin" and re.match(r"^kv1:[A-Za-z0-9_-]+$", val):
        pass   # 0.21.92: the page's wrapped form (assets/vault.js: AES-GCM under the browser's own key) -- kept as it is
    elif key == "kastr.lastjoin":
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
        d = kastr_secret.open_doc(path, json.loads(raw))   # 0.21.92: camera URLs with a password are kept sealed
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
        with open(tmp, "w", encoding="utf-8") as f:   # 0.21.92: a value carrying a password / token sealed
            json.dump(kastr_secret.seal_doc(path, {"v": 1, "at": time.time(), "items": items}), f)
        if os.name != "nt":
            os.chmod(tmp, 0o600)
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


_RELAY_WS = [0]       # 0.19.0: live /relay WebSocket pipes
TUNNEL_SEEN = {}      # 0.19.0: the last proxied visitor {"base", "at"} (the Relay page's one-port card); 0.20.0: + "open"
HUB_PUBLIC = [None]   # 0.21.86: the hub's public web address (its /api/client publicWeb) -- spokes learn it with the hub clock


def clean_public_url(s):
    """0.21.86 (Kenton: an invite link carried the relay's internal IP): the public web address invite links use --
    https://<DNS name>[:port] only. No path, no IP address: a private address is what those links must not carry, and
    the headers a visitor sends are never trusted for it (an invite link holds a secret)."""
    s = str(s or "").strip().rstrip("/")
    m = re.match(r"^https://((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(:[0-9]{1,5})?$", s, re.I)
    if not m or re.match(r"^[0-9.]+$", m.group(1)):
        return None
    return "https://" + m.group(1).lower() + (m.group(2) or "")


def public_web_base():
    """The address anyone can open: kastr.ini public_url on this machine, else the hub's."""
    return clean_public_url(ini_get("public_url")) or HUB_PUBLIC[0]


def public_relay_url():
    """0.21.93: this machine's own public web relay (kastr.ini public_url + /relay) for the hub's registry row -- the web
    address counts as part of the fleet. Never the hub's learned address: a spoke must not claim the hub's."""
    b = clean_public_url(ini_get("public_url"))
    return (b + kastr_relay.WEB_RELAY_PATH) if b else None


kastr_relay.PUBLIC_RELAY_FN = public_relay_url
_TUNNEL_OPEN_SAID = [0.0]   # 0.20.0: when the "proxied visitors reach an OPEN relay" line was last logged
SINGLE_PORT = False   # 0.19.0: kastr.ini single_port -- every remote page gets the /relay web relay
RTSP_BRIDGE = [None]  # 0.21.16: the running Bridge (make_server sets it) -- kastr_relay's hub `rtsp` command and the spoke registration reach the switch through it


def hub_web_base(host_or_url, default=8000):
    """0.19.0: the KASTR web base for a host or relay URL: a web relay's origin
    (https://name/relay -> https://name), a learned base (hub-web.json `base`),
    else http://host:<learned web port | default>."""
    v = str(host_or_url or "").strip()
    if not v:
        return None
    if "/" in v and kastr_relay.is_web_relay(v):
        return kastr_relay.web_origin(v)
    host = (urlparse(kastr_relay._as_url(v)).hostname or "") if "/" in v or "://" in v else v.strip("[]")
    host = host.lower()
    if not host:
        return None
    rec = HUB_WEB.get(host) or {}
    if rec.get("base"):
        return rec["base"]
    return "http://%s:%d" % (("[%s]" % host) if ":" in host else host, hub_web_for(host, default))


BYE_AT = [0.0]   # 0.21.40: monotonic time of the page's last goodbye (pagehide)
DIAG_REF = {}    # 0.21.74: the pages' latest self-reports (/api/diag), shared with the launcher
PAGES = {}       # 0.21.40: page id -> monotonic time of its last heartbeat (a page that said goodbye leaves)
HUB_CLOCK = {"off": 0.0, "rtt": None, "at": 0}   # 0.21.37: this host's clock offset to the HUB's (ms; 0 on the hub / unknown)
_HUB_CLOCK_RUNNING = [False]


def hub_clock_tick(relay_srv):
    """0.21.37 (Kenton: "latency -1404 ms"): a page measures its clock against its OWN relay host; a publisher on another
    relay measured against THAT host, so two host clocks a second apart read as a negative latency. A spoke measures its
    clock against the hub's (best of three /api/client round trips) and hands the offset to its pages, which then all
    agree on the hub's time."""
    import ssl
    try:
        connect = (relay_srv._cluster_raw() or {}).get("connect")
        if not connect or (relay_srv._cluster_raw() or {}).get("hub") is True:
            HUB_CLOCK.update(off=0.0, rtt=None, at=time.time())
            HUB_PUBLIC[0] = None
            return
        base = hub_web_base(connect)
        if not base:
            return
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        best = None
        for _ in range(3):
            t0 = time.time() * 1000.0
            with urllib.request.urlopen(base + "/api/client", timeout=4, context=ctx if base.startswith("https") else None) as r:
                d = json.loads(r.read(8192) or b"{}")
            t1 = time.time() * 1000.0
            HUB_PUBLIC[0] = clean_public_url(d.get("publicWeb"))   # 0.21.86: the hub's public address, for invite links
            if not isinstance(d.get("now"), (int, float)):
                return
            rtt, off = t1 - t0, d["now"] - (t0 + t1) / 2.0
            if best is None or rtt < best[0]:
                best = (rtt, off)
        if best:
            HUB_CLOCK.update(off=round(best[1], 1), rtt=round(best[0], 1), at=time.time())
    except Exception:
        pass   # the last measurement stands


def start_hub_clock(relay_srv, every=180.0):
    if _HUB_CLOCK_RUNNING[0] or relay_srv is None:
        return
    _HUB_CLOCK_RUNNING[0] = True

    def tick():
        hub_clock_tick(relay_srv)
        t = threading.Timer(every, tick)
        t.daemon = True
        t.start()
    t0 = threading.Timer(8.0, tick)
    t0.daemon = True
    t0.start()


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
_WATCH_STARTS = {}     # 0.21.8: "peer|broadcast" -> start times in the last 30 s (a looping fallback player)
_WATCH_LOOP_SAID = {}  # 0.21.8: "peer|broadcast" -> when the loop was last logged
_PIPE_SHORT = {}       # 0.21.8: peer -> end times of /relay pipes that lived under 15 s (a reconnecting browser)
_PIPE_SAID = {}
WATCH_SEG_RE = re.compile(r"^(?!\.\.?$)[A-Za-z0-9._-]+$")   # 0.18.0: never "." or ".."


# 0.18.0: on-demand cameras (docs/moq-landscape item 3). A camera box's bridge syncs its
# standby feeds here every 5 s ({broadcast: {room, label, low, at, wantedAt, live}}); viewer
# pages list them and send demand; the bridge wakes a feed wanted within the last minute.
ONDEMAND = {}
ONDEMAND_LOCK = threading.Lock()
ONDEMAND_TTL = 30          # a registration the bridge stopped refreshing is gone
ONDEMAND_WANT = 120        # demand older than this is not reported back
ONDEMAND_POKE = None       # 0.21.73: the bridge's od_poke -- a fresh demand starts the camera now, not at the next 5 s round
ADMIN_NOTICE = {}          # 0.21.73: an admin's Restart / Move about to happen {id, kind, to, from, at, deadline} -- the window says so
ADMIN_RELAUNCH_HOOK = None  # 0.21.73: kastr.py -- relaunch (optionally on another relay for this run)

# 0.18.0: HLS for browsers without MSE (iPhones before iOS 17): one `moq export hls` per
# broadcast on a loopback port, shared by its viewers, reached through /api/hls/<key>/...
HLS = {}                   # broadcast -> {proc, port, last, started}
HLS_KEYS = {}              # key -> {b, at}
HLS_LOCK = threading.Lock()
HLS_IDLE_S = 45
ARCHIVE_WANTS = lambda broadcast: False   # 0.18.0: make_server points this at the archiver's picks
HLS_KEY_IDLE_S = 120
# 0.21.0: the media resolution picker -- output heights the stream accepts (never upscaled) and the
# bitrate a hardware encoder gets for each; "one rung below" is what the low ladder drops to
MEDIA_HEIGHTS = (2160, 1440, 1080, 720, 480, 360)
MEDIA_HW_KBPS = {2160: 12000, 1440: 8000, 1080: 4500, 720: 2500, 480: 1200, 360: 800}


def fmp4_start(buf):
    """0.21.0: (start_seconds, patched_bytes) for the head of an ffmpeg fragmented MP4 written with
    -copyts + delay_moov after an input seek. ffmpeg's mp4 muxer starts every track's decode time at 0 and
    records the seek offset as an EMPTY EDIT (media_time -1, duration in mvhd units) -- which MSE ignores, so
    a seek to 90 s used to buffer at 0 and the page 'restarted from the beginning'. The start is read off
    that edit and the page puts it in the SourceBuffer's timestampOffset.
    0.21.95 (Kenton: converted media "audio is off"): each track's edit ALSO carries its own media_time -- the
    video's B-frame delay (2 frames = 67 ms for x264 / a copied H.264 or HEVC) and the AAC encoder's priming
    (1024 samples = 21 ms). 0.21.0 renamed every edts box to 'free', so the browser lost both: every converted
    file played its picture ~46 ms late against its sound on the sharer, and the whole share carried it. Now
    each track's edit list is rewritten to ONE normal entry (what Chromium's MSE parser applies) whose
    media_time folds in that track's empty edit relative to the common start S = the latest
    (empty edit - media_time) of all tracks, so one timestampOffset (S) places both tracks right. The box keeps
    its size (the dropped entries become a 'free' box inside edts). A head without an edit list returns 0.0 and
    the bytes untouched."""
    out = bytearray(buf)

    def boxes(off, end):
        while off + 8 <= end:
            size, typ = struct.unpack(">I4s", buf[off:off + 8])
            hdr = 8
            if size == 1:
                if off + 16 > end:
                    return
                size = struct.unpack(">Q", buf[off + 8:off + 16])[0]
                hdr = 16
            if size == 0:
                size = end - off
            if size < hdr:
                return
            yield typ, off, off + hdr, min(end, off + size)
            off += size

    def timescale(a, e):   # mvhd / mdhd: version 0 -> u32 at 12, version 1 -> u32 at 20
        return struct.unpack(">I", buf[a + 12:a + 16])[0] if buf[a] == 0 else struct.unpack(">I", buf[a + 20:a + 24])[0]

    try:
        tracks = []   # [elst_off, elst_end, version, track timescale, empty edit (s), media_time (track units), seg_dur]
        mvts = 1000
        for typ, _o, a, e in boxes(0, len(buf)):
            if typ != b"moov":
                continue
            for t2, _o2, a2, e2 in boxes(a, e):
                if t2 == b"mvhd" and e2 - a2 >= 24:
                    mvts = timescale(a2, e2) or 1000
            for t2, _o2, a2, e2 in boxes(a, e):
                if t2 != b"trak":
                    continue
                tts, el = 0, None
                for t3, o3, a3, e3 in boxes(a2, e2):
                    if t3 == b"mdia":
                        for t4, _o4, a4, e4 in boxes(a3, e3):
                            if t4 == b"mdhd" and e4 - a4 >= 24:
                                tts = timescale(a4, e4)
                    if t3 == b"edts":
                        for t4, o4, a4, e4 in boxes(a3, e3):
                            if t4 == b"elst" and e4 - a4 >= 8:
                                el = (o4, a4, e4)
                if not el or not tts:
                    continue
                o4, a4, e4 = el
                v = buf[a4]
                n = struct.unpack(">I", buf[a4 + 4:a4 + 8])[0]
                esz = 20 if v == 1 else 12
                if n < 1 or a4 + 8 + n * esz > e4:
                    continue
                empty, mt, seg = 0.0, 0, 0
                for i in range(n):
                    q = a4 + 8 + i * esz
                    sd, m = struct.unpack(">Qq", buf[q:q + 16]) if v == 1 else struct.unpack(">Ii", buf[q:q + 8])
                    if m == -1:
                        empty += sd / float(mvts)
                    else:
                        mt, seg = m, sd
                        break
                tracks.append([o4, a4, e4, v, tts, empty, mt, seg, n])
            break
        if not tracks:
            return 0.0, buf
        start = max(0.0, max(tr[5] - tr[6] / float(tr[4]) for tr in tracks))
        for o4, a4, e4, v, tts, empty, mt, seg, n in tracks:
            m2 = max(0, int(round(mt - (empty - start) * tts)))
            esz = 20 if v == 1 else 12
            q = a4 + 8
            out[a4 + 4:a4 + 8] = struct.pack(">I", 1)
            out[q:q + esz] = struct.pack(">QqhH", seg, m2, 1, 0) if v == 1 else struct.pack(">IihH", min(seg, 0xFFFFFFFF), m2, 1, 0)
            if n > 1:   # the dropped entries -> a 'free' box beside the elst (same edts size, no re-layout)
                end1 = q + esz
                out[o4:o4 + 4] = struct.pack(">I", end1 - o4)
                out[end1:end1 + 8] = struct.pack(">I4s", e4 - end1, b"free")
    except (struct.error, IndexError, ValueError):
        return 0.0, buf
    return start, bytes(out)


def _media_rung(h, low):
    try:
        i = MEDIA_HEIGHTS.index(int(h))
    except ValueError:
        return int(h)
    return MEDIA_HEIGHTS[min(len(MEDIA_HEIGHTS) - 1, i + 1)] if low else MEDIA_HEIGHTS[i]   # a keyed playlist unused this long is gone (players poll every few seconds)
HLS_WINDOW = "12s"
ARCHIVE_HOURS = 24         # kastr.ini archive_hours (the launcher sets it)


def ondemand_touch(broadcast, now=None):
    """A viewer is watching `broadcast` (a demand pulse or an /api/watch / HLS pump)."""
    now = now or time.time()
    with ONDEMAND_LOCK:
        rec = ONDEMAND.get(broadcast)
        if rec is None:
            return False
        fresh = not rec.get("wantedAt") or now - rec["wantedAt"] > 30
        rec["wantedAt"] = now
    if fresh and callable(ONDEMAND_POKE):   # 0.21.73: a sleeping camera starts within a second of the click
        try:
            ONDEMAND_POKE()
        except Exception:
            pass
    return True


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
                if ARCHIVE_WANTS(b) or (not kastr_rtsp.ONDEMAND_ENABLED and not f.get("idle")):   # the operator records it -> keep it awake; 0.21.10: this host is off -> an older box's standby pairs wake and stay up; 0.21.73: a camera that encodes only while watched sleeps whatever this switch says
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
    """0.18.0: the KASTR that hosts `relay_key` -- where a bridge syncs its on-demand feeds.
    0.19.0: a web relay's KASTR is its origin."""
    if kastr_relay.is_web_relay(relay_key):
        return kastr_relay.web_origin(relay_key)
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
        peer = kastr_relay.client_ip(handler) or "?"   # 0.19.0: the visitor behind a tunnel
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


_HUB_ROOMS_CACHE = [None]   # 0.21.25: {"at", "obj"} -- the hub's last /api/rooms answer on a spoke
_HUB_ROOMS_KEEPER = [False]
HUB_ROOMS_FILE = "hub-rooms.json"


def hub_rooms_remember(state_dir, obj):
    """0.21.35 (Kenton: "Store a local copy of the rooms on each relay, so if the hub goes down, they are still visible"):
    the hub's room list, in memory AND on disk (<state>/hub-rooms.json) -- a relay restarted while the hub is dark still
    lists the rooms. Written only when the list changed."""
    prev = (_HUB_ROOMS_CACHE[0] or {}).get("obj")
    _HUB_ROOMS_CACHE[0] = {"at": time.time(), "obj": obj}
    if not state_dir or prev == obj:
        return
    try:
        kastr_relay.save_json(os.path.join(state_dir, HUB_ROOMS_FILE), {"at": int(time.time()), "obj": obj}, backup=False)
    except Exception:
        pass


def hub_rooms_load(state_dir):
    """0.21.35: the saved copy, when this process has none yet."""
    if _HUB_ROOMS_CACHE[0] is not None or not state_dir:
        return
    try:
        d, _why = kastr_relay.load_json(os.path.join(state_dir, HUB_ROOMS_FILE), retries=1)
        if isinstance(d, dict) and isinstance((d.get("obj") or {}).get("rooms"), list):
            _HUB_ROOMS_CACHE[0] = {"at": float(d.get("at") or 0), "obj": d["obj"]}
    except Exception:
        pass


def start_hub_rooms_keeper(relay_srv, every=60.0):
    """0.21.35: on a spoke, ask the hub for its rooms once a minute (nobody has to open a room list for the copy to stay
    current). Once per process; a box that is not a spoke asks nothing."""
    if _HUB_ROOMS_KEEPER[0] or relay_srv is None:
        return
    _HUB_ROOMS_KEEPER[0] = True
    sd = getattr(relay_srv, "state_dir", None) or STATE_DIR
    hub_rooms_load(sd)

    def tick():
        try:
            if relay_srv._hub_minter_url() and relay_srv._cluster_raw().get("hub") is not True:
                out = relay_srv.hub_rooms_call({"op": "list"}, timeout=5)
                if out and out[1] == 200 and isinstance((out[0] or {}).get("rooms"), list):
                    hub_rooms_remember(sd, out[0])
        except Exception:
            pass   # HubDown and friends: the copy stays as it was
        t = threading.Timer(every, tick)
        t.daemon = True
        t.start()
    t0 = threading.Timer(15.0, tick)
    t0.daemon = True
    t0.start()


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


def _room_close_hook(slug):
    """0.21.25: a room closed at the hub by a spoke's page -- the hub's transcript goes too (chat store created lazily)."""
    cs = chat_store()
    if cs is not None:
        cs.delete_room(slug)


kastr_relay.ROOM_CLOSE_HOOK[0] = _room_close_hook


def _room_rename_hook(old, new):
    """0.21.65: a room renamed at the hub (Room settings) keeps its chat history (transcript + attachments move)."""
    cs = chat_store()
    if cs is not None:
        cs.rename_room(old, new)


kastr_relay.ROOM_RENAME_HOOK[0] = _room_rename_hook


def chat_sweep_once(relay_srv=None):
    """Transcripts idle for a day that nobody keeps are gone -> swept slugs."""
    store = chat_store(relay_srv=relay_srv)
    if store is None:
        return []
    rs = relay_srv if relay_srv is not None else _CHAT_RELAY[0]
    kept = set()
    try:   # 0.21.96: + every scheduled meeting's own room (its chat stays from one occurrence to the next)
        kept = set(getattr(rs.store, "chat_kept_slugs", rs.store.kept_slugs)())
    except Exception:
        pass
    return store.sweep(kept)


CHAT_TIMER_BEAT_S = 5   # 0.21.94


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

    def beat():   # 0.21.94: Room Chat timers -- scheduled messages out, timed ones gone (on this host's clock)
        while True:
            time.sleep(CHAT_TIMER_BEAT_S)
            try:
                cs = chat_store(relay_srv=relay_srv)
                if cs is not None:
                    cs.tick()
            except Exception:
                pass
    threading.Thread(target=beat, daemon=True, name="chat-timers").start()


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


_ENC_PROBE_STARTED = [False]   # 0.21.2: the hardware-encoder probe runs once, off the request thread


def rtsp_remote_ok(bridge, relay_srv):
    """0.21.2: the hardware encoder name when a web client may add RTSP cameras through this host: the relay
    here runs secured (a publisher token is the permission) and ffmpeg has a hardware H.264 encoder (a software
    transcode of several cameras would starve the box). None otherwise; the encoder probe is cached by the bridge."""
    try:
        if bridge is None or relay_srv is None or not getattr(relay_srv, "secured", False) or not relay_srv.running():
            return None
        if not hasattr(bridge, "usable_encoder"):
            return None
        enc = getattr(bridge, "_encoder", None)
        if enc is None:
            # the probe runs ffmpeg once per encoder (seconds): never inside a page request -- start it once, answer
            # "not yet"; the page asks again when the RTSP row opens
            if not _ENC_PROBE_STARTED[0]:
                _ENC_PROBE_STARTED[0] = True
                threading.Thread(target=lambda: bridge.usable_encoder(), daemon=True).start()
            return None
        return enc if enc and enc != "libx264" else None
    except Exception:
        return None


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

    def subs(tls=False, req_host=None, remote=False, override=None):
        current = relay_ref[0] or BUILTIN_RELAY
        # 0.8.9: a page served over https cannot use an http:// relay (mixed
        # content; no fingerprint pinning either) -- it gets the relay's wss
        # listener instead: https://<relay host>:<port+2>. A relay on THIS
        # machine is named by the address the phone used to reach us.
        # 0.17.0: a REMOTE page (another device on this relay host's web port)
        # gets the same treatment on plain http -- never a loopback relay --
        # and its own identity: `web` for the host token (the page derives a
        # per-device slug from it) and "web" as its client class.
        if override:
            current = override          # 0.19.0: this origin's /relay (a proxied or single-port visitor)
        elif tls or remote:
            current = page_relay(current, tls=tls, req_host=req_host, remote=remote)
        page_host = "web" if remote else host
        out = [
            (VERSION_TOKEN.encode(), read_version().encode()),
            (PRECACHE_TOKEN.encode(), json.dumps(precache_list(root)).encode()),   # 0.20.0: sw.js
            (HOST_TOKEN.encode(), page_host.encode()),
            (CLIENT_TOKEN.encode(), (b"web" if remote else b"app")),
            (WEB_RELAY_TOKEN.encode(), DEFAULT_RELAY.encode()),   # 0.21.93: the first-run / last-resort relay
            # 0.21.17: the prebuilt stats bundle (assets/stats-*.js) names the relay's stats prefix and skips '.'-led
            # keys; the relay now publishes under ~stats (relay.toml [stats] prefix) -- retarget it at serve time so the
            # vendored bundle on disk stays byte-identical. Both needles occur only in that bundle.
            (b"`.stats/node`", ("`%s/node`" % kastr_relay.STATS_KIND).encode()),
            (b"d=e=>e.startsWith(`.`)", ("d=e=>e.startsWith(`.`)||e.startsWith(`%s`)" % kastr_relay.NS).encode()),
            # 0.21.92 (Kenton: "Room names must not be visible to anyone without a fleet access code"): ~stats rides a token now --
            # stats.html asks for the access code (or reuses a saved one) and the bundle's connection carries its browse token
            (b"m=new i(new URL(a))", b"m=new i(new URL(window.__kastrTok?window.__kastrTok(a):a))"),
            (b"m.set(new URL(D.value.trim()))", b"m.set(new URL(window.__kastrTok?window.__kastrTok(D.value.trim()):D.value.trim()))"),
            (b"D.value=m.peek()?.toString()??a", b"D.value=String(m.peek()?.toString()??a).replace(/[?&]jwt=[^&]*/,``)"),   # the box never shows the token
        ]
        if current != BUILTIN_RELAY:
            out.append((BUILTIN_RELAY.encode(), current.encode()))
        return out

    # Latest self-report per page. In memory only; never written anywhere. 0.21.74: one per process (DIAG_REF) -- the
    # launcher's box keeper reads it
    diag_ref = DIAG_REF

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
            # 0.21.1: the version beside a co-located binary (build.py writes updates/<sub>/BUILT_VERSION);
            # the running binary's own version for sys.executable
            ver = None
            if frozen and p == sys.executable:
                ver = read_version()
            else:
                try:
                    with open(os.path.join(os.path.dirname(p), "BUILT_VERSION"), encoding="utf-8-sig") as f:
                        ver = f.read().strip() or None
                except OSError:
                    ver = None
            plats[plat] = {"path": p, "size": c[1], "sha256": c[2], "version": ver}

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

        # 0.17.0: the request class (kastr_relay.is_local) -- "local" is the
        # machine's own window/tools, "remote" a LAN box or a web client.
        def _local(self):
            return kastr_relay.is_local(self)

        # ---- 0.21.22: relays on the LAN (this machine only) -------------------------------------
        def _lan_api(self, path, method):
            def send(code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            if not self._local():
                return send(403, {"error": "only on the computer itself"})
            sd = getattr(relay_srv, "state_dir", None) if relay_srv is not None else None
            if path == "/api/lan/advertise":
                if method == "POST":
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                    except Exception:
                        return send(400, {"error": "bad json"})
                    mdns_advertise(sd, bool(body.get("advertise")))
                return send(200, {"advertise": mdns_advertise(sd), "listening": MDNS_ADV[0] is not None})
            if path == "/api/lan/closest":   # 0.21.91: the candidate relays by measured round trip (this machine only)
                if method != "POST":
                    return send(405, {"error": "POST"})
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(min(n, 65536)) or b"{}") if n else {}
                except Exception:
                    return send(400, {"error": "bad json"})
                try:
                    samples = max(1, min(5, int(body.get("samples") or 3)))
                except (TypeError, ValueError):
                    samples = 3
                t0 = time.time()
                out = closest_relays(body.get("relays") if isinstance(body.get("relays"), list) else [], samples=samples)
                return send(200, {"relays": out, "ms": int((time.time() - t0) * 1000)})
            if method != "GET":
                return send(405, {"error": "GET"})
            qs = parse_qs(urlparse(self.path).query)
            if path == "/api/lan/probe":
                return send(200, probe_relay((qs.get("url") or [""])[0]))
            if path == "/api/lan/nearest":   # 0.21.36: ?url=a&url=b... -> the relays nearest first (this machine only)
                return send(200, {"relays": rank_relays((qs.get("url") or [])[:24])})
            if path == "/api/lan/discover":
                try:
                    import kastr_mdns
                    found = kastr_mdns.browse(1.6)
                except Exception as e:
                    return send(200, {"relays": [], "error": str(e)[:120]})
                out = []
                for r in found:
                    t = r.get("txt") or {}
                    rp = t.get("rp") or ""
                    if not rp.isdigit():
                        continue
                    out.append({"name": t.get("nm") or r.get("name") or "", "urls": ["http://%s:%s" % (ip, rp) for ip in r.get("ips") or []],
                                "secured": t.get("sec") == "1", "fp": (t.get("fp") or "").lower(), "version": t.get("v") or "",
                                "web": ["http://%s:%s" % (ip, t.get("wp")) for ip in (r.get("ips") or []) if (t.get("wp") or "").isdigit()]})
                return send(200, {"relays": out})
            return send(404, {"error": "no such route"})

        # ---- 0.21.20: native screen / window share picker (this machine only) -----------------
        def _screen_api(self, path):
            import kastr_screen
            def send(code, body, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            if not self._local():   # a LAN box or a web client never sees this computer's screens or window titles
                return send(403, json.dumps({"ok": False, "error": "only on the computer itself"}).encode(), "application/json")
            qs = parse_qs(urlparse(self.path).query)
            try:
                if path == "/api/screen/sound":   # presenter mode: the computer's sound (minus this host's tree) as s16le 48 kHz stereo
                    import kastr_loopback
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.send_header("X-KASTR-Audio", "s16le;rate=48000;channels=2")
                    self.end_headers()
                    gone = threading.Event()
                    def sink(b):
                        if gone.is_set():
                            return
                        try:
                            self.wfile.write(b)
                        except Exception:
                            gone.set()
                    cap = kastr_loopback.LoopbackCapture(exclude_pid=os.getpid())
                    try:
                        cap.start(sink=sink)
                        while not gone.wait(0.5):
                            pass
                    finally:
                        cap.stop()
                    self.close_connection = True
                    return
                if path == "/api/screen/sources":
                    return send(200, json.dumps(kastr_screen.sources(tabs=(qs.get("tabs") or [""])[0] == "1")).encode(), "application/json")
                if path == "/api/screen/rtmp/firewall":   # 0.21.31: GET = are the RTMP ports open here; POST = open them (UAC)
                    if kastr_relay._FIREWALL_DIR is None and STATE_DIR:
                        kastr_relay._FIREWALL_DIR = STATE_DIR
                    if self.command == "POST":
                        try:
                            n = int(self.headers.get("Content-Length") or 0)
                            if n:
                                self.rfile.read(n)
                        except Exception:
                            pass
                        out = kastr_relay.add_rtmp_firewall()
                        self.log_message("rtmp firewall: %s", out.get("note") or out.get("error"))
                        return send(200 if out.get("ok") else 409, json.dumps(out).encode(), "application/json")
                    return send(200, json.dumps(kastr_relay.rtmp_firewall_status()).encode(), "application/json")
                if path == "/api/screen/rtmp":   # 0.21.29: a free RTMP ingest port + the addresses devices can reach this host by
                    ips = [ip for ip in kastr_relay.local_ips() if not ip.startswith(("127.", "172."))] or kastr_relay.local_ips()
                    return send(200, json.dumps({"ok": True, "port": kastr_rtsp.rtmp_free_port(), "hosts": ips}).encode(), "application/json")
                if path == "/api/screen/devices":   # 0.21.26: cameras this computer can capture as a host feed
                    # 0.21.65: + `cams` [{id, name, error?}] (the camera's own name; why one cannot be opened) and a `note`
                    cams, note = kastr_rtsp.list_cameras(getattr(bridge, "ffmpeg", None) if bridge else None)
                    devs = [c["id"] for c in cams if not c.get("error")]
                    return send(200, json.dumps({"ok": True, "devices": devs, "cams": cams, "note": note}).encode(), "application/json")
                w = int((qs.get("w") or ["320"])[0] or 320)
                got = kastr_screen.thumb((qs.get("id") or [""])[0], width=w)
                if not got:
                    return send(404, b"", "text/plain")
                return send(200, got[0], got[1])
            except Exception as e:
                return send(500, json.dumps({"ok": False, "error": str(e)[:200]}).encode(), "application/json")

        # ---- 0.19.0: one web port -------------------------------------------------------
        def _web_base(self):
            """The origin this visitor used: scheme from X-Forwarded-Proto / Cf-Visitor
            (a tunnel terminates TLS), host from X-Forwarded-Host or Host."""
            tls = bool(getattr(self.server, "is_tls", False))
            proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
            if proto not in ("http", "https"):
                m = re.search(r'"scheme"\s*:\s*"(https?)"', self.headers.get("Cf-Visitor") or "")
                proto = m.group(1) if m else ("https" if tls else "http")
            host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").split(",")[0].strip().lower()
            if not re.match(r"^[a-z0-9.\-\[\]:]{1,260}$", host):
                host = "localhost"
            if (proto == "https" and host.endswith(":443")) or (proto == "http" and host.endswith(":80")):
                host = host.rsplit(":", 1)[0]
            return "%s://%s" % (proto, host)

        def _web_relay_for(self):
            """The /relay address for a visitor who came through a proxy (or any remote
            visitor with kastr.ini single_port) -- only when THIS machine runs the relay."""
            # 0.21.92 H: record the presentation -- the headless recorder page (Host presrec.localhost, a web client by its
            # Host) always dials THIS machine's own relay, whatever relay this KASTR's own page uses
            if (str(self.headers.get("Host") or "").split(":")[0].strip().lower() == "presrec.localhost"
                    and relay_srv is not None and relay_srv.running()):
                return "http://presrec.localhost:%d" % int(relay_srv.port)
            # 0.21.92 H: end
            if not (SINGLE_PORT or kastr_relay.is_forwarded(self)):
                return None
            if not (relay_srv is not None and relay_srv.running()):
                return None
            base = self._web_base()
            if kastr_relay.is_forwarded(self):
                TUNNEL_SEEN.update(base=base, at=time.time())
                if not getattr(relay_srv, "secured", False):
                    # 0.20.0: an open relay trusts "the LAN"; through a tunnel that is everyone. Warn, never refuse
                    # (the operator's choice, 2026-09-28).
                    TUNNEL_SEEN["open"] = True
                    if time.time() - _TUNNEL_OPEN_SAID[0] > 3600:
                        _TUNNEL_OPEN_SAID[0] = time.time()
                        _note("web: proxied visitors reach an OPEN relay -- anyone with the name %s can watch and publish; "
                              "set access codes on the Relay page" % base)
                else:
                    TUNNEL_SEEN["open"] = False
            return base + kastr_relay.WEB_RELAY_PATH

        def _relay_ws(self):
            """GET /relay (Upgrade: websocket) -> the relay's own WebSocket listener on
            loopback, path rewritten to / (query kept), bytes piped both ways on ONE
            thread (select; an SSL socket is never used from two threads)."""
            import select
            if not (relay_srv is not None and relay_srv.running()):
                return self._json_cors(503, {"error": "no relay on this machine"})
            port = int(getattr(relay_srv, "port", 0) or 4443)
            u = urlparse(self.path)
            rest = u.path[len(kastr_relay.WEB_RELAY_PATH):] or "/"
            if not rest.startswith("/"):
                return self._json_cors(404, {"error": "not found"})
            try:
                up = socket.create_connection(("127.0.0.1", port), timeout=5)
            except OSError as e:
                return self._json_cors(503, {"error": "relay unreachable: %s" % e})   # 0.20.0: 503 passes a tunnel
            lines = ["GET %s%s HTTP/1.1" % (rest, ("?" + u.query) if u.query else ""), "Host: 127.0.0.1:%d" % port]
            for k, v in self.headers.items():
                if k.lower() in ("host", "x-forwarded-for"):
                    continue
                lines.append("%s: %s" % (k, v))
            lines.append("X-Forwarded-For: %s" % kastr_relay.client_ip(self))
            self.close_connection = True
            if kastr_relay.is_forwarded(self):
                TUNNEL_SEEN.update(base=self._web_base(), at=time.time())
            cs = self.connection
            t0 = time.time()
            nbytes = [0, 0]   # 0.21.8: browser -> relay, relay -> browser
            peer = kastr_relay.client_ip(self) or "?"
            try:
                up.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1", "replace"))
                cs.settimeout(None); up.settimeout(None)
                _RELAY_WS[0] += 1
                pend = getattr(cs, "pending", None)
                while True:
                    ready = [cs] if (pend and pend()) else []
                    if not ready:
                        ready, _w, _x = select.select([cs, up], [], [], 60)
                    done = False
                    for sk in ready:
                        data = sk.recv(65536)
                        if not data:
                            done = True
                            break
                        nbytes[0 if sk is cs else 1] += len(data)
                        (up if sk is cs else cs).sendall(data)
                    if done:
                        break
            except (OSError, ValueError):
                pass
            finally:
                _RELAY_WS[0] = max(0, _RELAY_WS[0] - 1)
                lived = time.time() - t0
                if lived < 15:
                    # 0.21.8: a pipe that lived seconds is a browser reconnecting; each reconnect re-pulls every stream it
                    # watches (a burst per reconnect for the whole relay). Say so once a minute per peer past three.
                    try:
                        now1 = time.time()
                        hist = [t for t in _PIPE_SHORT.get(peer, []) if now1 - t < 60] + [now1]
                        _PIPE_SHORT[peer] = hist
                        if len(_PIPE_SHORT) > 256:
                            for k in sorted(_PIPE_SHORT, key=lambda k: _PIPE_SHORT[k][-1])[:len(_PIPE_SHORT) - 256]:
                                _PIPE_SHORT.pop(k, None)
                        if len(hist) >= 3 and now1 - _PIPE_SAID.get(peer, 0) > 60:
                            _PIPE_SAID[peer] = now1
                            (getattr(bridge, "log", None) or _note)("relay pipe: %s opened %d short pipes in 60 s (the last lived %.1f s, %d KB in / %d KB out) -- a browser reconnecting in a loop?"
                                                                   % (peer, len(hist), lived, nbytes[0] // 1024, nbytes[1] // 1024))
                    except Exception:
                        pass
                for sk in (up,):
                    try:
                        sk.close()
                    except OSError:
                        pass

        def _deny(self, what):
            return kastr_relay.deny_remote(self, what)

        def end_headers(self):
            # 0.21.73 (Kenton: users at Southridge still see a camera "zoom to the top left"): /assets went out with
            # Last-Modified and no Cache-Control, so a browser kept a vendored player module by heuristic (about a tenth of
            # its age) -- the 0.21.63 HEVC fix patched player-DqpNnBDT.mjs under the SAME name, and a machine that had the
            # old one kept running it after updating. Every asset is now revalidated (a 304 is cheap).
            if self.path.split("?", 1)[0].startswith("/assets/") and not any(
                    bytes(h).lower().startswith(b"cache-control:") for h in getattr(self, "_headers_buffer", [])):
                self.send_header("Cache-Control", "no-cache")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("X-KASTR-Version", version_stamp())   # 0.21.4: a stale service worker reads this
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
            for needle, value in subs(tls, req_host, remote, self._web_relay_for() if remote else None):
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

        def _alive_bye(self):
            """0.21.40: the page is going (pagehide) -- the launcher ends KASTR unless a heartbeat follows (a reload)."""
            if not self._local():
                return self._deny("heartbeat")
            BYE_AT[0] = time.monotonic()
            PAGES.pop((parse_qs(urlparse(self.path).query).get("p") or [""])[0], None)
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

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
            PAGES[(parse_qs(urlparse(self.path).query).get("p") or [""])[0]] = alive_ref[0]   # 0.21.40
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
            if not window_geom_ok(geom):   # 0.21.84: a minimized / hidden window's report never replaces the last real bounds
                self.send_response(204)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if geom.get("maximized") is not True and native_kastr_zoomed(geom):   # 0.21.91: the window says it is maximized
                geom["maximized"] = True
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
            out = dict(diag_ref)
            out["_studiofx"] = studiofx_state()   # 0.21.94: Windows Studio Effects blur (cameras that offer it, held or not)
            if bridge is not None and hasattr(bridge, "diag_feeds"):   # 0.21.96: each RTSP camera's transport + what it lost
                try:
                    out["_rtsp"] = bridge.diag_feeds()
                except Exception as e:
                    out["_rtsp"] = {"error": str(e)[:200]}
            body = kastr_secret.mask(json.dumps(out, indent=1, default=str)).encode()   # 0.21.92: no code or token
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
            exists -- a `?solo=1` box (no page reporting) or a hidden-only page:
            "unknown", never 0."""
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

        def _release_zip(self, method):
            """0.21.7: the full install zip for a platform, assembled on this host from the parts every install
            already carries (kastr_release: own binary + browser folder, the other platform's mirrored binary +
            browser zip, the feed's templates). POST starts the assembly (idempotent); GET streams the file when
            it is ready, else 409 {status: building | not prepared}. Remote callers allowed like the sibling
            update routes: a web client downloads the app it is looking at."""
            qs = parse_qs(urlparse(self.path).query)
            plat = (qs.get("platform") or [""])[0]
            sd = self._state_dir()
            if plat not in kastr_release.PLATFORMS or not sd:
                return self._json_cors(404, {"error": "no install zip for that platform here"})
            ver = read_version()
            if method == "POST":
                st = kastr_release.prepare(plat, ver, sd, log=_note)
                _remote_seen(self, "/api/update/zip")
                return self._json_cors(200 if st["can"] else 409, st)
            p = kastr_release.path_for(plat, ver, sd)
            if not p:
                st = kastr_release.status(plat, ver, sd)
                st["status"] = "building" if st["building"] else ("not prepared" if st["can"] else "unavailable")
                return self._json_cors(409 if st["can"] else 404, st)
            size = os.path.getsize(p)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % os.path.basename(p))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                with open(p, "rb") as f:
                    while True:
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def _release_extra(self):
            """0.21.7: one template file from updates/<plat>/extras (the mirror fetches them like binaries)."""
            qs = parse_qs(urlparse(self.path).query)
            plat = (qs.get("platform") or [""])[0]
            name = (qs.get("name") or [""])[0]
            if plat not in kastr_release.EXTRAS or name not in kastr_release.EXTRAS[plat] or not kastr_release.EXTRA_RE.match(name):
                return self.send_error(404, "no such template here")
            p = os.path.join(kastr_release.extras_dir(kastr_release.app_root(), plat), name)
            if not os.path.isfile(p):
                return self.send_error(404, "no such template here")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(os.path.getsize(p)))
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                with open(p, "rb") as f:
                    self.wfile.write(f.read())
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

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
                "ondemand": bool(kastr_rtsp.ONDEMAND_ENABLED),   # 0.21.10: the kill switch -- the page hides the two RTSP switches, drops -low.hang and sends no demand when false
                "rtspSuspended": bool(getattr(bridge, "suspended", False)),   # 0.21.16: the box's RTSP switch (the page paints it before its first /api/rtsp/list)
                # Server-remembered operator name (0.8.0) -- the fallback
                # when the browser profile lost its localStorage.
                "operator": op_ref[0],
                # 0.8.3: the launch-time fleet-update check's outcome (the
                # updater used to fail in silence). null in dev harnesses.
                "updateCheck": self._update_check(),
                # 0.21.61: this KASTR is the relaunch of an update (the last 15 min) -- the page rejoins its room
                "justUpdated": os.environ.get("KASTR_UPDATED") == "1" and time.time() - _SERVE_T0 < 900,
                "justRestarted": os.environ.get("KASTR_RESTARTED") == "1" and time.time() - _SERVE_T0 < 900,   # 0.21.73: an admin's Restart / Move
                "adminMoved": (os.environ.get("KASTR_MOVED") or "") if time.time() - _SERVE_T0 < 900 else "",
                # 0.8.13: seconds since the app window last pinged (None: never)
                # -- the launcher's hand-off check reads it -- and the bundled
                # ffmpeg's version, so a smoke test can assert the bundle.
                "aliveAge": (round(time.monotonic() - alive_ref[0], 1) if alive_ref and alive_ref[0] else None), "pages": len(PAGES),
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
                for k in ("pid", "swept", "operator", "updateCheck", "aliveAge", "ffmpeg", "viewing", "hubWeb", "platform",
                          "adminMoved"):   # 0.21.92: the room an admin moved this machine to
                    d.pop(k, None)
                d["hostMode"] = MODE
                d["mode"] = "full"
                d["client"] = "web"
                d["relay"] = self._web_relay_for() or page_relay(relay_ref[0] or BUILTIN_RELAY, tls=tls, req_host=req_host, remote=True)
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
            meta = {"id": fid, "name": name, "size": n, "token": kastr_secret.digest(token),   # 0.21.92: the uploader holds the token
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

        def _files_may_list(self, room, qs):
            """0.21.92 (Kenton: "Room names must not be visible to anyone without a fleet access code"): who may read a file list
            here. The machine itself always; every room's files (no ?room=) nobody else; a room's on a SECURED relay a member
            token covering that room (Authorization: Bearer, or ?jwt=); a KASTR without a secured relay keeps its open list."""
            try:
                if self._local():
                    return True
                if not room:
                    return False
                if not (relay_srv is not None and getattr(relay_srv, "secured", False)):
                    return True
                jwt = self._bearer(qs)
                return bool(jwt) and self._room_claims(room, jwt) is None
            except Exception:
                return False

        def _file_list(self, qs):
            """0.8.8: the room's shared files (tokens withheld) -- a viewer who
            joined after the sharer's announce still sees them."""
            d = self._files_dir()
            if not d:
                return self._json_cors(200, {"files": []})
            room = (qs.get("room") or [""])[0][:64]
            if not self._files_may_list(room, qs):
                # 0.21.92: no list without the room's token -- still a 200, so a page older than 0.21.92 keeps choosing this
                # store for its uploads (it checks r.ok); new pages send their member token
                return self._json_cors(200, {"files": [], "needToken": True})
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
            if not kastr_secret.digest_matches(meta.get("token"), token) and not self._admin_for(str(meta.get("room") or "")) and not kastr_relay._local_only(self):   # 0.21.2: or an admin of its room; 0.21.3: or the operator's own page
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
            return kastr_relay.client_ip(self) or ""   # 0.19.0: lockouts per visitor, not per tunnel

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
            return {"host": hhost, "web": web, "hub": hub, "code": fed.get("code") or "",
                    "base": (kastr_relay.web_origin(hub) if kastr_relay.is_web_relay(hub) else None)}   # 0.19.0

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
                # 0.21.3: remember whether this member is an ADMIN of the room -- a spoke vouches for it to the hub
                return {"mode": mode, "via": self._chat_via(), "fed": False, "hub": hub, "admin": kastr_relay.claims_admin(claims, room)}
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
            if room == kastr_relay.LIB_ROOT:   # 0.21.84: "lib" is the stream library -- no chat, no files (a library token covers it)
                return self._chat_reply(403, {"error": kastr_relay.LIB_RESERVED})
            store = chat_store(relay_srv=relay_srv)
            if store is None:
                return self._chat_reply(503, {"error": "no storage here"})
            ctx = self._chat_auth(room, qs)
            if ctx is None:
                return
            if ctx["mode"] == "proxy":
                return self._chat_proxy(method, room, ctx["hub"], files=bool(files), admin=bool(ctx.get("admin")))
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
            if room == "main":   # 0.21.60: the Lobby keeps no history to show
                return self._json_cors(200, {"room": room, "messages": [], "persistent": False, "closed": False, "lobby": True})
            ts = self._chat_closed(room)
            if ts:
                return self._chat_reply(410, {"error": "room closed", "closed": ts})
            try:   # 0.21.94: tv=1 = a page that knows timers (an older one gets a line instead of a timed message)
                msgs = store.read(room, (qs.get("since") or ["0"])[0], (qs.get("limit") or ["200"])[0],
                                  tv=(qs.get("tv") or [""])[0] == "1")
                rttl = store.room_ttl(room)
            except ValueError as e:
                return self._chat_reply(400, {"error": str(e)})
            return self._json_cors(200, {"room": room, "messages": msgs,
                                         "persistent": self._room_persistent(room) or store.is_kept(room),
                                         "closed": False, "tv": 1, "now": int(time.time()), "ttl": rttl})   # 0.21.94: this host's clock

        def _chat_post(self, room, store, ctx):
            if room == "main":   # 0.21.60: the Lobby has no chat (nothing shared there; the page hides it too)
                return self._chat_reply(403, {"error": "the Lobby has no chat -- join a room", "lobby": True})
            ts = self._chat_closed(room)
            if ts:
                return self._chat_reply(410, {"error": "room closed", "closed": ts})
            p = self._chat_body_json()
            if p is None:
                return self._chat_reply(413, {"error": "message too large"})
            # 0.21.94 timers: act = ttl (the room's default) | open (view once, this device) | sched (my scheduled one);
            # a post may carry ttl (else the room's default applies -- an older page's posts too), vo + dev, rel (send later)
            act = str(p.get("act") or "")
            try:
                if act == "ttl":
                    rec = store.set_ttl(room, p.get("s"), p.get("op"), p.get("name"), ctx.get("via") or "")
                    if self._room_persistent(room):
                        store.mark_keep(room, True)
                    return self._json_cors(201, rec)
                if act == "open":
                    code, obj = store.open_vo(room, p.get("id"), p.get("dev"))
                    return self._json_cors(code, obj)
                if act == "sched":
                    code, obj = store.sched_op(room, p.get("sid"), p.get("tk"), str(p.get("do") or ""), p.get("rel"))
                    return self._json_cors(code, obj)
                if act:
                    return self._chat_reply(400, {"error": "unknown act"})
                ttl = p.get("ttl") if "ttl" in p else store.room_ttl(room)
                if p.get("rel"):
                    obj = store.schedule(room, p.get("rel"), p.get("op"), p.get("name"), p.get("text"), p.get("files"),
                                         ctx.get("via") or "", ttl=ttl, vo=p.get("vo"), dev=p.get("dev"))
                    if self._room_persistent(room):
                        store.mark_keep(room, True)
                    return self._json_cors(201, obj)
                rec = store.append(room, p.get("op"), p.get("name"), p.get("text"), p.get("files"),
                                   ctx.get("via") or "", ttl=ttl, vo=p.get("vo"), dev=p.get("dev"))
            except ValueError as e:
                return self._chat_reply(400, {"error": str(e)})
            if rec.get("vo"):   # 0.21.94: the poster's page shows the stub too (it never opens its own)
                rec = dict(rec, text="", files=[], nf=len(rec.get("files") or []), opn=0)
            if self._room_persistent(room):
                store.mark_keep(room, True)
            return self._json_cors(201, rec)          # the ONLY reply that carries the delete token

        def _bearer(self, qs=None):
            """0.21.2: the member token a page sends as Authorization: Bearer (or ?jwt=)."""
            h = str(self.headers.get("Authorization") or "")
            if h.lower().startswith("bearer "):
                return h[7:].strip()
            return ((qs or {}).get("jwt") or [""])[0] if qs is not None else ""

        def _settings_admin(self):
            """0.21.65: may this caller change ANY room's settings as an admin? The relay operator's own page (loopback), or
            a member token of this relay carrying an admin grant (the admin code is relay-wide; the token may be for another
            room, or the Lobby's)."""
            try:
                if self._local():
                    return True
            except Exception:
                pass
            jwt = self._bearer(None)
            if not jwt:
                return False
            if self._room_claims("", jwt) is not None:
                return False
            return kastr_relay.claims_admin_any(self._claims)

        # ---- 0.21.91 passcode reset: who an admin's My room reset / remove is audited as (never a code) ----
        def _personal_who(self, p):
            relay = ""
            try:
                relay = relay_srv.auth._rcx_name()
            except Exception:
                pass
            by = kastr_relay.clean_label((p or {}).get("by"), 40)
            try:
                if self._local():
                    return {"name": ("relay operator (%s)" % by) if by else "relay operator", "host": "", "relay": relay}
            except Exception:
                pass
            host = ""
            try:
                _r, host = kastr_relay.claims_identity(getattr(self, "_claims", None) or {})
            except Exception:
                pass
            return {"name": by or host or "an admin", "host": host or "", "relay": relay}
        # ---- end 0.21.91 passcode reset ----

        def _admin_for(self, room, qs=None):
            """0.21.2: True when the caller's token carries `<room>/~admin` (the admin access code). On an
            OPEN relay nobody is an admin this way (_room_claims returns None with no claims)."""
            jwt = self._bearer(qs)
            if not jwt or not room:
                return False
            if self._room_claims(room, jwt) is not None:
                return False
            return kastr_relay.claims_admin(self._claims, room)

        @property
        def kastr_relay_srv(self):
            return relay_srv   # 0.21.2: kastr_rtsp.handle_api checks the relay is secured before a web client adds a camera

        def _fed_vouched_admin(self):
            """0.21.3: a forwarding SPOKE says the caller is an admin of the room (X-Kastr-Admin: 1). Trusted only
            under a federation token this secured hub verifies; an open hub trusts its LAN anyway (no vouch)."""
            if self.headers.get("X-Kastr-Admin") != "1":
                return False
            auth = self.headers.get("Authorization") or ""
            bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            if not bearer or not (relay_srv is not None and getattr(relay_srv, "secured", False)):
                return False
            state = self._state_dir()
            key = kastr_relay.read_jwk(state) if state else None
            claims = kastr_relay.verify_token(bearer, key) if key else None
            return bool(claims and kastr_relay.is_relay_claims(claims))

        def _chat_purge(self):
            """0.21.3: the relay operator (a loopback page) deletes a room's chat -- transcript, keep marker and
            attachments stored HERE -- and the room stays. On a hub this covers the spokes' rooms too (their chat
            lives here)."""
            if not kastr_relay._local_only(self):
                try:
                    self.rfile.read(int(self.headers.get("Content-Length") or 0) or 0)
                except Exception:
                    pass
                return self._json_cors(403, {"error": "chat purges only from the machine that hosts the relay"})
            p = self._chat_body_json() or {}
            slug = str(p.get("slug") or "")
            if not kastr_relay.SLUG_RE.match(slug):
                return self._json_cors(400, {"error": "bad room name"})
            cs = chat_store(relay_srv=relay_srv)
            if cs is None:
                return self._json_cors(503, {"error": "no chat store on this KASTR"})
            try:
                removed = cs.delete_room(slug)
            except Exception as e:
                return self._json_cors(500, {"error": str(e)})
            n = len(removed) if isinstance(removed, (list, tuple)) else removed
            if callable(globals().get("_chat_log")):
                _chat_log("chat: operator purged room %s (%s file(s))" % (slug, n if n is not None else "?"))
            return self._json_cors(200, {"ok": True, "slug": slug, "removed": n})

        def _chat_delete(self, room, msgid, qs, store):
            token = (qs.get("token") or [""])[0]
            force = kastr_relay._local_only(self)     # the operator on the relay host may delete anything
            if not force and self._fed_vouched_admin():   # 0.21.3: an admin on a spoke, vouched for by that spoke
                force = True
                if callable(globals().get("_chat_log")):
                    _chat_log("chat: admin (via %s) removed message %s in %s" % ((self.headers.get("X-Kastr-Via") or "spoke")[:40], msgid, room))
            if not force and self._admin_for(room, qs):   # 0.21.2: an admin removes any line
                force = True
                if callable(globals().get("_chat_log")):
                    _chat_log("chat: admin removed message %s in %s" % (msgid, room))
            try:
                ok = store.delete(room, int(msgid), token or None, force=force)
            except ValueError as e:
                return self._chat_reply(400, {"error": str(e)})
            if not ok:
                return self._chat_reply(403, {"error": "not your message (or already gone)"})
            return self._json_cors(200, {"ok": True})

        def _chat_file_post(self, room, store, ctx):
            if room == "main":   # 0.21.60: the Lobby has no chat (nothing shared there; the page hides it too)
                return self._chat_reply(403, {"error": "the Lobby has no chat -- join a room", "lobby": True})
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
            meta = {"id": fid, "name": name, "size": n, "token": kastr_secret.digest(uuid.uuid4().hex),   # 0.21.92
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
            if meta.get("vo"):   # 0.21.94: a view-once picture -- only with the ticket its opening handed out (5 minutes)
                ft = (parse_qs(urlparse(self.path).query).get("ft") or [""])[0]
                if not store.vo_file_ok(room, fid, ft):
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
            self.send_header("Cache-Control", "no-store" if meta.get("t") or meta.get("vo") else "private, max-age=3600")   # 0.21.94: a timed one is never cached
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

        def _chat_proxy(self, method, room, hub, files=False, admin=False):
            """A spoke forwards the whole call to the hub's KASTR with its
            federation token; the hub's reply comes back as-is, except a 404
            from a hub without a chat service and a 410 (room closed there;
            a view-once "already opened" 410 passes)."""
            tok, info = self._hub_token(hub)
            if not tok and info.get("hubCodes"):
                return self._chat_reply(502, {"error": "no federation token for the hub"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            self._chat_body_read = True
            hosttxt = ("[" + hub["host"] + "]") if ":" in hub["host"] else hub["host"]
            # 0.21.91: the reader's room token stays here -- this spoke checked it; the hub trusts the federation token (and
            # could not verify a token another minter signed). Every other query (since, limit, a delete token) goes on.
            _u = urlparse(self.path)
            _q = [kv for kv in urllib.parse.parse_qsl(_u.query, keep_blank_values=True) if kv[0] != "jwt"]
            fwd_path = _u.path + ("?" + urllib.parse.urlencode(_q) if _q else "")
            target = (hub.get("base") or "http://%s:%d" % (hosttxt, hub["web"])) + fwd_path   # 0.19.0: a web relay's origin
            headers = {"X-Kastr-Via": self._chat_via()}
            if tok:
                headers["Authorization"] = "Bearer " + tok
            if admin:
                headers["X-Kastr-Admin"] = "1"   # 0.21.3: this spoke verified its admin's token; the hub cannot (other minter)
            ct = self.headers.get("Content-Type")
            if ct:
                headers["Content-Type"] = ct
            for k in ("X-Kastr-Name", "X-Kastr-Op", "X-Kastr-Room", "X-Kastr-Owner", "X-Kastr-Kind"):   # 0.21.91: never X-Kastr-Jwt
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
                    return self._chat_reply(502, {"error": "hub chat unavailable"})
                if code == 410:
                    # 0.21.94: only the hub's "room closed" turns into 502; a view-once "already opened" 410 goes on as-is
                    try:
                        body = json.loads(r.read(65536) or b"{}")
                    except Exception:
                        body = {}
                    if not isinstance(body, dict) or not body or "closed" in body:
                        return self._chat_reply(502, {"error": "hub chat closed this room"})
                    return self._chat_reply(410, body)
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
            url = (hub.get("base") or "http://%s:%d" % (hosttxt, hub["web"])) + "/api/chat/%s?limit=1" % slug   # 0.19.0
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

        def _rooms_guest_cut(self, obj):
            """0.21.91 (Kenton: guests "see ONLY the Lobby and the room(s) they were invited to"): a list asked with a GUEST's token
            (an invite-link member or a personal-room guest of this relay's minter) answers their room alone -- nothing else of the
            fleet (rooms, groups, renames). A member's or a browse token (an access code): every room. No token: none."""
            try:
                if not (relay_srv is not None and getattr(relay_srv, "secured", False)):
                    return obj   # 0.21.92: an OPEN relay has no access code to ask for -- its rooms stay open, as its sessions are
                auth = getattr(relay_srv, "auth", None) if relay_srv is not None else None
                hdr = self.headers.get("Authorization") or ""
                claims = auth._member_claims(hdr) if (auth is not None and hdr and hasattr(auth, "_member_claims")) else None
                if claims is None:
                    # 0.21.91 (Kenton: "Room names must not be visible to anyone without a fleet access code"): no token -> no
                    # rooms. 0.21.92: the relay machine's loopback neither -- its Relay page reads /api/relay/rooms
                    out = kastr_relay.rooms_for_guest(obj, set())
                    out.update(guest=False, needCode=True)
                    return out
                g = kastr_relay.guest_rooms(claims)
                return kastr_relay.rooms_for_guest(obj, g) if g is not None else obj
            except Exception:
                return kastr_relay.rooms_for_guest(obj, set())

        def _rooms_api(self, method, path, qs):
            """The relay's room records for pages anywhere (CORS-open)."""
            store = getattr(relay_srv, "store", None) if relay_srv is not None else None
            if store is None:
                return self._chat_reply(503, {"error": "no relay on this KASTR"})
            log = getattr(relay_srv, "log", None)
            log = log if callable(log) else None
            if hasattr(relay_srv, "hub_rooms_call"):
                fwd = self._rooms_at_hub(method, path, store, log)   # 0.21.25: a spoke -> the hub owns rooms
                if fwd is not False:
                    return fwd
            if path == "/api/rooms/list":
                if method != "GET":
                    return self._chat_reply(405, {"error": "GET only"})
                # 0.15.0: + the relay-defined room groups {gid: {name, order, rooms}}; 0.21.65: + renamed {old: new}
                return self._json_cors(200, self._rooms_guest_cut({"rooms": store.rooms_public(), "closed": store.closed_public(),
                                                                   "closedWhy": store.closed_why_public() if hasattr(store, "closed_why_public") else {},   # 0.21.92
                                                                   "groups": store.groups_public(), "renamed": store.renamed_public()}))

            if path == "/api/rooms/settings":
                # 0.21.65 (Kenton: "Ability to change room settings after the fact. Only for admin or creator."): the
                # creator's roomKey, an admin's member token (Authorization: Bearer) or the relay operator's own page
                if method != "POST":
                    return self._chat_reply(405, {"error": "POST only"})
                p = self._chat_body_json()
                if p is None:
                    return self._chat_reply(413, {"error": "body too large"})
                _auth = getattr(relay_srv, "auth", None) if relay_srv is not None else None
                xs = _auth._xs("local") if _auth is not None and hasattr(_auth, "_xs") else kastr_relay.XSHARE_OPEN   # 0.21.91: an open relay's listings follow a rename too
                obj, code = kastr_relay.room_settings(store, p, admin=self._settings_admin(), log=log, xs=xs)
                if code == 200:
                    try:
                        relay_srv.spoke_sync_soon()
                    except Exception:
                        pass
                return self._chat_reply(code, obj)
            if path == "/api/rooms/group":
                # 0.15.0: a room's creator (roomKey) files its room under a group; the
                # operator's create/rename/delete live on /api/relay/rooms/group.
                if method != "POST":
                    return self._chat_reply(405, {"error": "POST only"})
                p = self._chat_body_json()
                if p is None:
                    return self._chat_reply(413, {"error": "body too large"})
                # 0.21.68 (Kenton: "I'm not able to group the rooms because I can't create a group name"): an admin (the
                # admin code's token) manages groups too -- before, only a page on the relay box itself could create one
                obj, code = kastr_relay.group_op(store, p, operator=self._settings_admin(), log=log)
                return self._chat_reply(code, obj)
            if path == "/api/rooms/register":
                if method != "POST":
                    return self._chat_reply(405, {"error": "POST only"})
                p = self._chat_body_json()
                if p is None:
                    return self._chat_reply(413, {"error": "body too large"})
                _auth = getattr(relay_srv, "auth", None) if relay_srv is not None else None   # 0.21.17: a spoke checks/mirrors with its hub
                _hooks = _auth.lock_hooks() if _auth is not None and hasattr(_auth, "lock_hooks") else {}
                obj, code = kastr_relay.register_room(store, p, self._chat_peer(), log, CHAT_LOCKOUT, **_hooks)
                hdrs = {"Retry-After": obj.get("retryAfter", 30)} if code == 429 else None
                if code == 200:
                    try:
                        relay_srv.spoke_sync_soon()   # 0.21.2
                    except Exception:
                        pass
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
                # 0.21.2: an admin-code holder (Authorization: Bearer <member token> with the room's ~admin grant)
                # closes like the operator; the creator still proves itself with the roomKey
                admin = self._admin_for(slug)
                obj, code = kastr_relay.close_room(store, slug, p.get("roomKey"), admin, hook=hook, log=log)
                if code == 200:
                    if admin and log:
                        log("relay: room %s closed by an admin" % slug)
                    self._chat_unkeep_at_hub(slug)
                    try:
                        relay_srv.spoke_sync_soon()   # 0.21.2: the hub's spoke table lists my rooms
                    except Exception:
                        pass
                return self._chat_reply(code, obj)
            if path == "/api/rooms/personal":   # 0.21.75: My room -- make / open (name + personal code) / an admin's reset
                if method != "POST":
                    return self._chat_reply(405, {"error": "POST only"})
                p = self._chat_body_json()
                if p is None:
                    return self._chat_reply(413, {"error": "body too large"})
                _auth = getattr(relay_srv, "auth", None) if relay_srv is not None else None
                _hadm = (lambda c: bool(_auth._hub_admin_ok(c))) if _auth is not None and hasattr(_auth, "_hub_admin_ok") else None
                _padm = p.get("op") in ("reset", "list") and self._settings_admin()   # 0.21.91 passcode reset: + the admin's list
                obj, code = kastr_relay.personal_op(store, p, self._chat_peer(), log, CHAT_LOCKOUT,
                                                    admin=_padm, admin_check=_hadm,
                                                    who=self._personal_who(p) if _padm and p.get("op") == "reset" else None)
                hdrs = {"Retry-After": obj.get("retryAfter", 30)} if code == 429 else None
                return self._chat_reply(code, obj, hdrs)
            if path == "/api/rooms/touch":   # 0.21.25: a room in use (any member) -- plain rooms live while used
                if method != "POST":
                    return self._chat_reply(405, {"error": "POST only"})
                p = self._chat_body_json() or {}
                slug = str(p.get("slug") or "")
                if not kastr_relay.SLUG_RE.match(slug) or slug == "main":
                    return self._chat_reply(400, {"error": "bad room"})
                if not self._touch_may_create(slug):   # 0.21.92
                    store.touch_room(slug, str(p.get("creator") or ""), create=False)
                    return self._chat_reply(200, {"ok": True})
                created = store.touch_room(slug, str(p.get("creator") or ""))
                return self._chat_reply(200, {"ok": True, "created": created})
            return self._chat_reply(404, {"error": "no such rooms endpoint"})

        HUB_DOWN = "The hub is unreachable \u2014 rooms are created on the hub. Try again when it is back."

        def _touch_may_create(self, slug):
            """0.21.92: may this touch MAKE room `slug`? The machine itself, an open relay, or a member token covering the room
            (Authorization: Bearer -- 0.21.92 pages send it). Anyone else only keeps a live room alive."""
            try:
                if self._local():
                    return True
                return self._room_claims(slug, self._bearer(None)) is None
            except Exception:
                return False

        def _rooms_at_hub(self, method, path, store, log):
            """0.21.25 (Kenton: "they should all be stored on the hub and distributed to all relays to see"): on a SPOKE every
            room call goes to the hub. What only this box can check (its publisher code, its admins' tokens) is checked
            here and vouched for. -> a sent reply, or False when this relay is not a spoke (handle locally)."""
            try:
                probe = relay_srv.hub_rooms_call is not None and relay_srv._hub_minter_url()
                if not probe or relay_srv._cluster_raw().get("hub") is True:
                    return False
            except Exception:
                return False
            peer = self._chat_peer()
            if path == "/api/rooms/list":
                if method != "GET":
                    return self._chat_reply(405, {"error": "GET only"})
                try:
                    out = relay_srv.hub_rooms_call({"op": "list"}, timeout=4)
                    obj, code = out if out else ({}, 0)
                    if code == 200 and isinstance(obj.get("rooms"), list):
                        hub_rooms_remember(self._state_dir(), obj)   # 0.21.35: kept on disk too
                        return self._json_cors(200, self._rooms_guest_cut(self._rooms_merge(obj, store, False)))   # 0.21.91
                except kastr_relay.HubDown:
                    pass
                hub_rooms_load(self._state_dir())   # 0.21.35: a relay restarted while the hub is dark
                cached = (_HUB_ROOMS_CACHE[0] or {}).get("obj") or {"rooms": [], "closed": {}, "groups": {}}
                return self._json_cors(200, self._rooms_guest_cut(self._rooms_merge(cached, store, True)))   # 0.21.91
            if method != "POST":
                return self._chat_reply(405, {"error": "POST only"})
            p = self._chat_body_json()
            if p is None:
                return self._chat_reply(413, {"error": "body too large"})
            slug = str(p.get("slug") or "")
            if path == "/api/rooms/register":
                wait = CHAT_LOCKOUT.locked_for(peer)
                if wait:
                    return self._chat_reply(429, {"error": "too many attempts -- try again in %d s" % wait, "retryAfter": wait},
                                            {"Retry-After": wait})
                access = str(p.get("access") or "")
                vouch = "publisher" if (access and store.configured() and store.check("publisher", access)) else None
                if not vouch and access and store.configured():   # 0.21.73: an admin code does what a publisher's does (here, or the hub's)
                    _a = getattr(relay_srv, "auth", None)
                    if store.check("admin", access) or (_a is not None and hasattr(_a, "_hub_admin_ok") and _a._hub_admin_ok(access)):
                        vouch = "admin"
                body = {"op": "register", "body": p, "peer": peer, "vouch": vouch}
            elif path == "/api/rooms/close":
                body = {"op": "close", "slug": slug, "roomKey": p.get("roomKey"), "vouch": "admin" if self._admin_for(slug) else None}
            elif path == "/api/rooms/group":   # 0.21.68: an admin this box verified may create / rename / delete groups too
                body = {"op": "group", "body": p, "vouch": "admin" if self._settings_admin() else None}
            elif path == "/api/rooms/touch":
                body = {"op": "touch", "slug": slug, "creator": str(p.get("creator") or "")[:64]}
                if not self._touch_may_create(slug):
                    body["only"] = True   # 0.21.92: no member token here -- the hub keeps a live room alive, makes none
            elif path == "/api/rooms/settings":   # 0.21.65: the hub owns rooms; this box vouches for an admin it verified
                body = {"op": "settings", "body": p, "vouch": "admin" if self._settings_admin() else None}
            elif path == "/api/rooms/personal":   # 0.21.75: personal rooms live on the hub; this box checks the access code
                wait = CHAT_LOCKOUT.locked_for(peer)
                if wait:
                    return self._chat_reply(429, {"error": "too many attempts -- try again in %d s" % wait, "retryAfter": wait},
                                            {"Retry-After": wait})
                vouch = None
                pwho = None
                if p.get("op") in ("reset", "list"):   # 0.21.91 passcode reset: + the admin's list; the hub audits `who`
                    vouch = "admin" if self._settings_admin() else None
                    if vouch and p.get("op") == "reset":
                        pwho = self._personal_who(p)
                elif p.get("op") == "create":
                    access = str(p.get("access") or "")
                    _a = getattr(relay_srv, "auth", None)
                    if not store.configured():
                        vouch = "member"   # this relay has no access codes: nothing more to check here
                    elif access and (store.check("viewer", access) or store.check("publisher", access) or store.check("admin", access)
                                     or (_a is not None and hasattr(_a, "_hub_admin_ok") and _a._hub_admin_ok(access))):
                        vouch = "member"
                    elif access:
                        lo, lc = CHAT_LOCKOUT.fail(peer, "wrong access code", "(personal room)")
                        return self._chat_reply(lc, dict(lo, ok=False))
                    else:
                        return self._chat_reply(403, {"ok": False, "error": "making your room needs this relay's access code -- join a room first"})
                body = {"op": "personal", "body": {k: v for k, v in p.items() if k != "access"}, "peer": peer, "vouch": vouch}
                if pwho:
                    body["who"] = pwho   # 0.21.91 passcode reset
            else:
                return self._chat_reply(404, {"error": "no such rooms endpoint"})
            try:
                out = relay_srv.hub_rooms_call(body)
            except kastr_relay.HubDown as e:
                if path == "/api/rooms/touch":
                    return self._chat_reply(200, {"ok": True, "offline": True})
                if log:
                    log("relay federation: room %s %s -- the hub is unreachable (%s)" % (slug or "?", path.rsplit("/", 1)[-1], e))
                return self._chat_reply(503, {"error": self.HUB_DOWN, "hubDown": True, "why": str(e)[:120]})
            if out is None:
                return False
            obj, code = out
            if path == "/api/rooms/touch" and body.get("only"):
                obj = {"ok": bool(obj.get("ok", code == 200))}   # 0.21.92: an older hub may still say "created" -- never pass it on
            if path == "/api/rooms/register" and code == 403 and p.get("access"):
                CHAT_LOCKOUT.fail(peer, "wrong publisher access code", slug)   # the guess counts here, where the member is
            if path == "/api/rooms/personal":   # 0.21.75
                if code == 400 and obj.get("error") == "bad room":
                    return self._chat_reply(501, {"ok": False, "error": "the hub runs an older KASTR without personal rooms -- update the hub first"})
                if code == 403 and obj.get("wrong"):
                    lo, lc = CHAT_LOCKOUT.fail(peer, "wrong personal code", "(personal room)")   # the guess counts here, where the person is
                    if lc == 429:
                        obj, code = dict(lo, ok=False), 429
                if p.get("op") == "list" and isinstance(obj, dict):
                    obj = dict(obj, spoke=True)   # 0.21.91 passcode reset: the Relay page says "on the hub"
                    if code == 400 and "unknown op" in str(obj.get("error") or ""):
                        obj, code = {"ok": False, "spoke": True, "old": True, "error": "the hub runs an older KASTR -- update the hub first"}, 501
            if path == "/api/rooms/settings" and code == 200:   # 0.21.65: this box asks the hub again (a lock is enforced at once)
                try:
                    _a = getattr(relay_srv, "auth", None)
                    with _a.lock:
                        for s in (slug, str(obj.get("slug") or "")):
                            _a._hub_open.pop(s, None)
                            _a._hub_locks.pop(s, None)
                except Exception:
                    pass
            if path == "/api/rooms/close" and code == 200:
                try:
                    if store.room(slug) is not None:
                        store.close_room(slug)   # a copy left from before the hub owned rooms
                except Exception:
                    pass
                if log and body.get("vouch") == "admin":
                    log("relay: room %s closed at the hub by an admin here" % slug)
            hdrs = {"Retry-After": obj.get("retryAfter", 30)} if code == 429 else None
            return self._chat_reply(code, obj, hdrs)

        def _rooms_merge(self, hub_obj, store, offline):
            """The hub's rooms, plus any room this spoke still holds itself (a name the hub has differently)."""
            rooms = [dict(r, source="hub") for r in (hub_obj.get("rooms") or []) if isinstance(r, dict)]
            have = {r.get("slug") for r in rooms}
            try:
                rooms += [dict(r, source="local") for r in store.rooms_public() if r.get("slug") not in have]
            except Exception:
                pass
            out = {"rooms": rooms, "closed": hub_obj.get("closed") or {}, "groups": hub_obj.get("groups") or {}, "fromHub": True,
                   "renamed": hub_obj.get("renamed") or {},   # 0.21.65
                   "closedWhy": hub_obj.get("closedWhy") or {}}   # 0.21.92: "pres" -- a template's room closed at End
            if offline:
                out["hubOffline"] = True
                out["hubAt"] = int((_HUB_ROOMS_CACHE[0] or {}).get("at") or 0)
            return out

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
            if not self._local():   # 0.19.0: the shared check -- a proxied request (tunnel) is never the machine
                return self._json_cors(403, {"error": "quit only from the machine itself"})
            if QUIT_HOOK is None:
                return self._json_cors(200, {"status": "dev", "note": "source checkouts stop with Ctrl+C"})
            import threading
            threading.Timer(0.3, QUIT_HOOK).start()       # let this reply land first
            return self._json_cors(200, {"status": "quitting", "pid": os.getpid()})

        def _rcadmin_dir(self):
            """0.21.83 (D): where this machine's opt-in (rcadmin.json) and its session log live -- the state folder."""
            return STATE_DIR or (relay_srv.state_dir if relay_srv is not None else None) or getattr(bridge, "state_dir", None) or "."

        def _auth_proxy(self, method):
            """0.8.9: the room-code service (relay host, port+1) is plain http;
            an https page reaches it through its own origin. 0.10.0: the real
            client rides X-Forwarded-For so the minter's lockout counts per
            phone, not per proxy (the minter trusts it from a loopback peer only)."""
            try:
                cur = relay_ref[0] or BUILTIN_RELAY
                u = urlparse(cur)
                rh = u.hostname or "127.0.0.1"
                # 0.17.0: the minter honours X-Forwarded-For from a LOOPBACK peer only.
                # When the relay is this very machine (named by its LAN IP), dial it on
                # loopback so every phone's wrong codes count against that phone.
                if rh.lower() in _own_hosts():
                    rh = "127.0.0.1"
                base = "http://%s:%d" % (rh, (u.port or 4443) + 1)
                hop = bool(self.headers.get("X-Kastr-Hop"))
                if kastr_relay.is_web_relay(cur) and not hop:
                    base = kastr_relay.web_origin(cur)      # 0.19.0: that KASTR's web port proxies its minter
                elif hop and relay_srv is not None and relay_srv.running():
                    base = "http://127.0.0.1:%d" % (int(relay_srv.port) + 1)   # 0.19.0: we ARE the web relay
                elif hop:
                    return self._json_cors(508, {"error": "web relay loop (this machine runs no relay)"})
                # 0.21.92 H: record the presentation -- the recorder page (Host presrec.localhost) mints at THIS machine's own
                # relay: its grant lives here, and its relay is this one (_web_relay_for)
                if (str(self.headers.get("Host") or "").split(":")[0].strip().lower() == "presrec.localhost"
                        and relay_srv is not None and relay_srv.running()):
                    base = "http://127.0.0.1:%d" % (int(relay_srv.port) + 1)
                # 0.21.92 H: end
                path0 = self.path.split("?", 1)[0]
                if (relay_srv is not None and relay_srv.running() and not getattr(relay_srv, "secured", False)
                        and base.startswith("http://127.0.0.1:")):
                    # 0.20.0: an OPEN relay runs no token service. Answer its shape here (200) instead of
                    # a 502 nobody can read: Cloudflare replaces an origin 502 with its own text page, and
                    # watch.html took that for "no KASTR here".
                    _obody = self.rfile.read(int(self.headers.get("Content-Length") or 0) or 0)
                    if path0 == "/api/xshare":   # 0.21.41: an OPEN relay lists cross-room shares too (no tokens: `from` names the room)
                        if method == "GET":
                            _q = parse_qs(urlparse(self.path).query)
                            obj, code = kastr_relay.xshare_open("GET", room=(_q.get("room") or [""])[0],
                                                                store=getattr(relay_srv, "store", None))   # 0.21.63: + board pins
                        else:
                            try:
                                _ob = json.loads(_obody or b"{}")
                            except ValueError:
                                _ob = {}
                            try:   # 0.21.91: this relay judges deleted rooms only when it owns its rooms (not a spoke)
                                _judge = not (relay_srv.hub_rooms_call is not None and relay_srv._hub_minter_url()
                                              and relay_srv._cluster_raw().get("hub") is not True)
                            except Exception:
                                _judge = True
                            obj, code = kastr_relay.xshare_open("POST", _ob, store=getattr(relay_srv, "store", None), judge=_judge)
                        return self._json_cors(code, obj)
                    if path0 == "/api/rooms/board":   # 0.21.63: an OPEN relay keeps room boards too (no tokens)
                        if method == "GET":
                            _q = parse_qs(urlparse(self.path).query)
                            obj, code = kastr_relay.board_open("GET", getattr(relay_srv, "store", None), room=(_q.get("room") or [""])[0])
                        else:
                            try:
                                _ob = json.loads(_obody or b"{}")
                            except ValueError:
                                _ob = {}
                            obj, code = kastr_relay.board_open("POST", getattr(relay_srv, "store", None), _ob)
                        return self._json_cors(code, obj)
                    if path0 == "/api/auth":
                        return self._json_cors(200, {"app": "KASTR", "secured": False, "codes": False, "legacy": False,
                                                     "federation": False, "open": True, "relayPort": int(relay_srv.port),
                                                     "web": int(HTTP_PORT or self.server.server_address[1]),
                                                     "https": HTTPS_INFO.get("port"), "talking": True, "chat": True, "state": True,
                                                     "ns": kastr_relay.NS})   # 0.21.17: the control namespace
                    if path0 == "/api/rooms":
                        st = getattr(relay_srv, "store", None)
                        return self._json_cors(200, {"rooms": st.rooms_public() if st else [], "groups": st.groups_public() if st else []})
                    if path0 == "/api/token":
                        return self._json_cors(200, {"ok": True, "open": True, "role": "member"})
                    return self._json_cors(503, {"error": "this relay has no access codes (set them on the Relay page)"})
                target = base + self.path
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else None
                peer = kastr_relay.client_ip(self)          # 0.19.0: the visitor behind a tunnel
                hdrs = {"Content-Type": self.headers.get("Content-Type") or "application/json", "X-Forwarded-For": peer}
                if path0 == "/api/vehicle":
                    # 0.21.63: the minter names the relay URL a vehicle dials from the name the vehicle used here (and a
                    # tunnelled request gets the web relay https://<name>/relay -- a tunnel carries no QUIC)
                    fwd = kastr_relay.is_forwarded(self)
                    hdrs["X-Kastr-Host"] = ((self.headers.get("X-Forwarded-Host") if fwd else None) or self.headers.get("Host") or "").split(",")[0].strip()
                    hdrs["X-Kastr-Via"] = "tunnel" if fwd else "web"
                if self.headers.get("Authorization"):
                    hdrs["Authorization"] = self.headers.get("Authorization")   # 0.19.0: federation Bearer (bans, spokes)
                if kastr_relay.is_web_relay(cur) and not hop:
                    hdrs["X-Kastr-Hop"] = "1"
                req = urllib.request.Request(target, data=body, method=method, headers=hdrs)
                retry_after = None
                # 0.20.0: a spoke's ban long-poll (GET /api/bans?since=&wait=) may hold for 30 s
                to = 40 if (method == "GET" and path0 == "/api/bans" and "wait=" in self.path) else 5
                if path0 in ("/api/rcx/poll", "/api/rcx/fed"):   # 0.21.83 (D): a machine's poll is held up to 25 s at the hub
                    to = 45
                elif path0.startswith("/api/rcx"):
                    to = 15
                elif path0 == "/api/msg/file":   # 0.21.88: up to 25 MB through a spoke to the hub
                    to = 150
                elif path0 == "/api/msg":        # 0.21.88: a spoke asks the hub (PBKDF2 happens in the browser, not here)
                    to = 30
                elif path0 == "/api/templates/deck":   # 0.21.92: a template deck's file (up to 64 MB, through a spoke to the hub)
                    to = 320
                elif path0 == "/api/templates":  # 0.21.92: meeting templates (a spoke asks the hub; an apply runs many board ops there)
                    to = 40
                elif path0 in ("/api/meetings", "/api/meetings/ics"):   # 0.21.96: scheduled meetings (a spoke asks the hub)
                    to = 25
                elif path0 == "/api/people":     # 0.21.90: a profile photo goes on to the hub through a spoke
                    to = 20
                elif path0.startswith("/api/avatar/"):   # 0.21.90: a spoke may fetch the photo from the hub first
                    to = 15
                elif path0.startswith("/api/gif/"):      # 0.21.91: GIF search -- a spoke asks the hub, the hub asks GIPHY
                    to = 30
                ctype = None
                ccache = None
                with urllib.request.urlopen(req, timeout=to) as r:
                    data = r.read()
                    code = r.status
                    ctype = r.headers.get("Content-Type") if r.headers else None   # 0.21.84: a library still is image/jpeg
                    ccache = r.headers.get("Cache-Control") if r.headers else None   # 0.21.90: a photo of one version keeps
                    cdisp = r.headers.get("Content-Disposition") if r.headers else None   # 0.21.96: a meeting's .ics names its file
            except urllib.error.HTTPError as e:
                data = e.read(); code = e.code
                retry_after = e.headers.get("Retry-After") if e.headers else None   # 0.10.0: lockouts travel through
            except Exception as e:
                return self._json_cors(503, {"error": "room-code service unreachable: %s" % e})   # 0.20.0: 503, never 502 (Cloudflare swaps 502s)
            self.send_response(code)
            _ct = locals().get("ctype")
            self.send_header("Content-Type", _ct if (code == 200 and (str(_ct or "").startswith("image/") or str(_ct or "") == "application/octet-stream"
                                                                      or str(_ct or "").startswith("text/calendar"))) else "application/json")   # 0.21.88: + an attachment's ciphertext; 0.21.96: + a meeting's .ics
            _cd = locals().get("cdisp")
            if code == 200 and _cd and str(_ct or "").startswith("text/calendar"):
                self.send_header("Content-Disposition", _cd)   # 0.21.96
            self.send_header("Content-Length", str(len(data)))
            _cc = locals().get("ccache")
            _p0 = self.path.split("?", 1)[0]
            self.send_header("Cache-Control", _cc if (code == 200 and _cc and _p0.startswith("/api/avatar/")) else "no-store")
            if retry_after:
                self.send_header("Retry-After", str(retry_after))
            self._cors()
            self._corp_cross = True
            self.end_headers()
            self.wfile.write(data)

        def _avatar_get(self):
            """0.21.90: a profile photo for this machine's pages, from the fleet's store (never a host URL another site may not
            reach). The relay machine's own loopback pages are answered here (the relay's photo service, in process); every
            other caller goes through the room-code proxy with its member token (the minter checks it)."""
            path0 = self.path.split("?", 1)[0]
            auth = getattr(relay_srv, "auth", None) if relay_srv is not None else None
            if auth is not None and relay_srv.running() and kastr_relay._local_only(self):
                try:
                    obj, hdrs, code = auth.avatar_get(path0[len("/api/avatar/"):], parse_qs(urlparse(self.path).query),
                                                      self.headers.get("Authorization"), "127.0.0.1", trusted=True)
                except Exception as e:
                    return self._json_cors(500, {"ok": False, "error": "photo service: %s" % str(e)[:120]})
                if not isinstance(obj, (bytes, bytearray)):
                    return self._json_cors(code, obj)
                self.send_response(200)
                for k, v in (hdrs or {}).items():
                    self.send_header(k, str(v))
                self.send_header("Content-Length", str(len(obj)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self._cors()
                self.end_headers()
                self.wfile.write(obj)
                return
            return self._auth_proxy("GET")

        def _probe_codecs(self, path):
            """ffmpeg -i on a (partial) file -> ('h264', 'ac3', 6.0, 29.97, 1920, 1080): codec names, the
            container's duration in seconds (0.14.0; 0.0 when N/A), the frame rate (0.16.0) and the picture
            size (0.21.0 -- the resolution picker). Every path returns the same six values (the 0.14-0.20
            failure path returned three and every caller unpacked four)."""
            ff = getattr(bridge, "ffmpeg", None) if bridge else None
            if not ff:
                return None, None, 0.0, 0.0, 0, 0
            try:
                r = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True, timeout=60,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                err = r.stderr or ""
            except Exception:
                return None, None, 0.0, 0.0, 0, 0
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
            pw = ph = 0
            sm = re.search(r"Video:[^\n]*?[ ,](\d{2,5})x(\d{2,5})[ ,\[]", err)   # "..., 1920x1080 [SAR..." (the 0x31637661 tag has one digit before x)
            if sm:
                try:
                    pw, ph = int(sm.group(1)), int(sm.group(2))
                except ValueError:
                    pw = ph = 0
            return (v.group(1).lower() if v else None), (a.group(1).lower() if a else None), dur, fps, pw, ph

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
                v, a, dur, fps, pw, ph = self._probe_codecs(tmp)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            cv = bool(v) and not any(v.startswith(x) for x in WEB_VIDEO)
            ca = bool(a) and not any(a.startswith(x) for x in WEB_AUDIO)
            return self._json_cors(200, {"video": v, "audio": a, "duration": dur, "fps": fps, "convertVideo": cv, "convertAudio": ca,
                                         "width": pw, "height": ph})   # 0.16.0: + fps; 0.21.0: + size

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
            v, a, dur, _fps, pw, ph = self._probe_codecs(src)
            rec["video"], rec["audio"], rec["duration"], rec["probedAt"] = v, a, dur, got
            rec["width"], rec["height"] = pw, ph   # 0.21.0
            return self._json_cors(200, {"id": mid, "url": "/api/media/" + mid, "size": n,
                                         "duration": dur, "video": v, "audio": a, "width": pw, "height": ph})

        def _media_adopt(self, mid, base_dir):
            """A source on disk from before a restart -> a complete record."""
            src = _media_find(base_dir, mid)
            if not src:
                return None
            try:
                size = os.path.getsize(src)
            except OSError:
                return None
            v, a, dur, _fps, pw, ph = self._probe_codecs(src)
            rec = {"path": src, "size": size, "got": size, "done": True, "aborted": False, "procs": set(),
                   "errors": [], "video": v, "audio": a, "duration": dur, "probedAt": size, "at": time.time(),
                   "width": pw, "height": ph}
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
            # 0.21.0: the resolution picker -- a whitelist of heights; ignored for a copy (nothing to scale)
            hsel = 0
            if (qs.get("h") or [""])[0]:
                try:
                    hsel = int((qs.get("h") or ["0"])[0])
                except ValueError:
                    hsel = -1
                if hsel not in MEDIA_HEIGHTS:
                    return self._json_cors(400, {"error": "h must be one of %s" % ",".join(str(x) for x in MEDIA_HEIGHTS)})
            if v == "copy":
                hsel = 0
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
                    pv, pa, pdur, pfps, ppw, pph = self._probe_codecs(src)
                    if pfps:
                        rec["fps"] = pfps   # 0.16.0
                    if pph:
                        rec["width"], rec["height"] = ppw, pph   # 0.21.0
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
            if hsel:
                hout = _media_rung(hsel, low)
                vf = "scale=-2:'min(%d,ih)',format=yuv420p" % hout        # 0.21.0: the chosen height, never upscaled
            else:
                hout = 0
                vf = "scale='min(%d,iw)':-2,format=yuv420p" % (960 if low else 1280)
            vcodec = ["-vf", kastr_rtsp.encoder_vf(enc, vf), *(["-r", "24"] if low else []), "-c:v", enc]
            if enc == "libx264":
                # 0.16.0: half the cores (at least 2) -- a software transcode used every core and
                # starved the browser's own encoder, so viewers saw the composite hitch (Mikey's share)
                thr = max(2, (os.cpu_count() or 4) // 2)
                vcodec += ["-preset", "ultrafast" if low else "superfast", "-tune", "fastdecode", "-crf", "26" if low else "23", "-threads", str(thr)]
            else:
                kb = MEDIA_HW_KBPS.get(hout) if hout else None
                vcodec += ["-b:v", ("%dk" % kb) if kb else ("2M" if low else "4M"), "-maxrate", ("%dk" % kb) if kb else ("2M" if low else "4M"),
                           "-bufsize", ("%dk" % (kb * 2)) if kb else ("4M" if low else "8M")]
            vcodec += ["-g", "48" if low else "60"]
            argv = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", *pre,
                    *(["-ss", "%.3f" % t, "-noaccurate_seek"] if t > 0 else []),   # 0.21.0: BOTH tracks start at the demuxer's keyframe -- one timestampOffset fits them (accurate seek moved the decoded audio to t and left the copied video at the keyframe: 6 s of A/V skew)
                    "-i", src, "-map", "0:v:0?", "-map", "0:a:0?", "-copyts",
                    *(["-c:v", "copy"] if v == "copy" else vcodec),
                    *(["-c:a", "copy"] if a == "copy" else ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]),
                    "-f", "mp4", "-movflags", "empty_moov+default_base_moof+delay_moov", "-frag_duration", "500000", "pipe:1"]   # 0.21.0: delay_moov = the edit list carries the real start (fmp4_start)
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
                return self._json_cors(503, {"error": msg[-800:], "copy": v == "copy"})
            # 0.21.0: the real start of this stream (a copy begins at the keyframe before t; a transcode at t)
            start_s, first = fmp4_start(first)
            if t > 0 and not start_s:
                start_s = t
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
            self.send_header("X-KASTR-Height", str(hout if v != "copy" else 0))   # 0.21.0: 0 = legacy width cap / copy
            self.send_header("X-KASTR-Fps", self._num(rec.get("fps") or 0))   # 0.16.0
            self.send_header("X-KASTR-Start", "%.3f" % start_s)   # 0.21.0: the REAL start (was the requested t)
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

        def _invite_pending(self, method):
            """0.21.75: the app hand-off of an invite link -- this machine only, never another site's page (Origin /
            Sec-Fetch-Site), and taken once."""
            if not self._local():
                return self._deny("invite hand-off")
            origin = str(self.headers.get("Origin") or "")
            site = str(self.headers.get("Sec-Fetch-Site") or "")
            if (origin and not re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", origin)) or site not in ("", "same-origin", "none"):
                return self._json_plain(403, {"error": "this machine's own KASTR pages only"})
            if method == "POST":
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    url = str(json.loads(self.rfile.read(min(n, 8192)) or b"{}").get("url") or "")
                except Exception:
                    url = ""
                ok = invite_pending_set(url)
                _note("invite: an invite link was handed to this KASTR (%s)" % ("kept for the page" if ok else "not usable"))
                return self._json_plain(200 if ok else 400, {"ok": ok})
            return self._json_plain(200, {"invite": invite_pending_take()})

        def do_POST(self):
            path0 = self.path.split("?", 1)[0]
            if path0 == "/api/invite/pending":      # 0.21.75: a second launch hands its invite link to this one
                return self._invite_pending("POST")
            if path0 in ("/api/rooms/fed", "/api/ondemand/forward", "/api/hub/handover"):   # 0.21.25: federation calls reach the
                return self._auth_proxy("POST")                                            # minter (the chat branch 404ed them)
            if path0 == "/api/rooms/board":         # 0.21.63: the room board lives at the minter (token-checked there)
                return self._auth_proxy("POST")
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
            if path0.startswith("/api/rcfiles"):    # 0.21.83: files + pictures over remote control (kastr_rcfiles)
                import kastr_rcfiles
                return kastr_rcfiles.handle_api(self, _note, ini_get)
            if path0 == "/api/prefs":               # 0.14.0
                return self._prefs_post()
            if path0.startswith("/api/lan/"):       # 0.21.22
                return self._lan_api(path0, "POST")
            if path0 == "/api/screen/rtmp/firewall":   # 0.21.31: open the RTMP ingest ports (this computer only)
                return self._screen_api(path0)
            if path0 == "/api/rc":                  # 0.21.79: remote control -- the prompt, the grant, the controller's input
                import kastr_rc
                return kastr_rc.handle_api(self, bridge, _note)
            if path0 in ("/api/rcadmin", "/api/rcadmin/ctl", "/api/rcadmin/ask"):   # 0.21.83 (D): the opt-in checkbox (THIS machine only) + the source switcher; 0.21.92: + an admin's ask answered here
                import kastr_rcadmin
                return kastr_rcadmin.handle_api(self, self._rcadmin_dir(), _note)
            if path0.startswith("/api/record/"):    # 0.21.81: Record's save formats -- the convert upload + cancel
                import kastr_record
                return kastr_record.handle_api(self, bridge, self._state_dir(), _note)
            if path0 == "/api/presrec" or path0.startswith("/api/presrec/"):   # 0.21.92 H: record the presentation
                import kastr_presrec
                return kastr_presrec.handle_api(self, _note)
            if path0 == "/api/pres" or path0.startswith("/api/pres/"):   # 0.21.84 (prototype): presentations -- convert + the encrypted slide store
                import kastr_pres
                return kastr_pres.handle_api(self, self._state_dir(), _note)
            if path0 == "/api/web/public":          # 0.21.86: the public web address invite links use (this machine only)
                return self._web_public()
            if path0 == "/api/web":                 # 0.17.0: web clients switch
                return self._web_api("POST")
            if path0 in ("/api/ondemand/sync", "/api/ondemand/demand"):   # 0.18.0
                return self._ondemand_api("POST", path0)
            if path0 == "/api/archive":             # 0.18.0: the operator picks what the host records
                return self._archive_api("POST", path0)
            if path0 == "/api/relaunch":
                return self._relaunch()
            if path0 == "/api/update/zip":         # 0.21.7: start assembling the install zip
                return self._release_zip("POST")
            if path0 in ("/api/token", "/api/auth", "/api/room", "/api/kick",   # 0.10.0: /api/room too (https pages hold room locks); 0.17.0: /api/kick
                         "/api/spokes/register", "/api/bans/notify",          # 0.19.0: federation through a web relay
                         "/api/clients/checkin",                              # 0.21.50: an app says who it is to the relay it uses
                         "/api/clients/logs", "/api/logs/upload",             # 0.21.51: logs collected at the hub
                         "/api/vehicle",                                      # 0.21.63: a vehicle's key -> a publish token
                         "/api/invite", "/api/invite/revoke", "/api/invites",  # 0.21.75: room invite links (the minter keeps them)
                         "/api/people",                                       # 0.21.78: beats, person invites, My room shared
                         "/api/access",                                       # 0.21.89: Ask for access (ask, status, cancel, answer)
                         "/api/msg", "/api/msg/file",                         # 0.21.88: private messages (+ an attachment's ciphertext)
                         "/api/templates", "/api/templates/fed", "/api/templates/deck",   # 0.21.92: meeting templates (+ their decks)
                         "/api/meetings",                                     # 0.21.96: scheduled meetings
                         "/api/rcx", "/api/rcx/poll", "/api/rcx/claim", "/api/rcx/end", "/api/rcx/fed",   # 0.21.83 (D): unattended remote control
                         "/api/library", "/api/library/token", "/api/library/admin",   # 0.21.84: the stream library
                         "/api/xshare"):                                      # 0.21.41: list a stream in other rooms
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
            if path == "/api/alive/bye":   # 0.21.40
                return self._alive_bye()
            if path == "/api/quit":
                return self._quit()       # 0.9.8
            if path == "/api/camfx/studio":
                # 0.21.94: switch the camera driver's own (Windows Studio Effects) blur on / off. Local pages only.
                if not self._local():
                    return self._deny("camera settings")
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    req = json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    req = {}
                cid = str(req.get("id") or "")[:64]
                res = studiofx().set(cid, bool(req.get("on")), bool(req.get("shallow"))) if cid else {"ok": False, "why": "no camera"}
                _note("camera effects: Windows Studio Effects blur %s -> %s" % ("on" if req.get("on") else "off",
                      "ok" if res.get("ok") else (res.get("why") or "failed")))
                return self._json_plain(200, res)
            if path == "/api/autorun":
                # Machine-boot autorun (0.8.2). Local pages only.
                if not self._local():   # 0.17.0: Host + peer + Origin
                    body = json.dumps({"error": "autorun changes only from the machine itself"}).encode()
                    self.send_response(403)
                else:
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                        req = json.loads(self.rfile.read(n) or b"{}")
                        want = bool(req.get("enabled"))
                        mini = req.get("minimized")   # 0.21.92: the Profile menu's "Start minimized"; absent = keep the saved one
                        mini = None if mini is None else bool(mini)
                    except Exception:
                        want, mini = False, None
                    try:
                        body = json.dumps(autorun_set(want, mini)).encode()
                    except OSError as e:
                        body = json.dumps({"error": "could not change the autorun entry: %s" % e}).encode()
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/update/offer":   # 0.21.50: the person's answer -- "now" updates at once, "later" waits for the deadline
                if not self._local():
                    return self._deny("update answers")
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    ans = str(json.loads(self.rfile.read(n) or b"{}").get("answer") or "")
                except Exception:
                    ans = ""
                off = UPDATE_OFFER
                if not off.get("version"):
                    body, code = {"ok": False, "error": "no update offered"}, 409
                elif ans == "now" and UPDATE_HOOK is not None:
                    off["state"] = "updating"
                    import threading
                    threading.Thread(target=UPDATE_HOOK, args=(off.get("host") or "",), daemon=True).start()
                    body, code = {"ok": True, "state": "updating"}, 200
                elif ans == "later":
                    off["state"] = "deferred"
                    body, code = {"ok": True, "state": "deferred", "deadline": off.get("deadline")}, 200
                else:
                    body, code = {"ok": False, "error": "answer now or later"}, 400
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)
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
            if path == "/api/relay/chat/purge":   # 0.21.3: operator purge (kastr_serve owns the chat store)
                return self._chat_purge()
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
            hw = rtsp_remote_ok(bridge, relay_srv)   # 0.21.2: web clients may add RTSP through THIS host (hardware encoder + secured relay)
            feats = {"publish": True, "chat": True, "admin": True,
                     "rtsp": (not web) or bool(hw), "media": not web, "relayControls": not web,
                     "updates": not web, "prefs": not web, "window": not web,
                     "rtspViaHost": bool(hw) and web, "hwEncoder": hw or None,
                     "ondemand": bool(kastr_rtsp.ONDEMAND_ENABLED)}   # 0.21.10
            return self._json_cors(200, {
                "app": "KASTR", "version": read_version(),
                "client": "web" if web else "app",
                "relay": (self._web_relay_for() if web else None) or page_relay(relay_ref[0] or BUILTIN_RELAY, tls=tls, req_host=req_host, remote=web),
                "webRelay": bool(web and self._web_relay_for()),   # 0.19.0
                "openTunnel": bool(web and self._web_relay_for() and not getattr(relay_srv, "secured", False)),   # 0.20.0: warn the visitor
                "hostMode": MODE,
                "web": int(HTTP_PORT or self.server.server_address[1]),
                "https": HTTPS_INFO.get("port"),
                "trust": HTTPS_INFO.get("trust") or ("local-ca" if HTTPS_INFO.get("ca") else None),
                "ca": "/ca.crt" if HTTPS_INFO.get("ca") else None,
                "hostname": HTTPS_INFO.get("hostname"),
                "closing": bool(CLOSING[0]),
                "now": int(time.time() * 1000),   # 0.18.0: the relay host's clock (latency stamps are corrected to it)
                "hubOff": HUB_CLOCK.get("off") or 0,   # 0.21.37: this host's offset to the hub's clock -- pages add it (one fleet clock)
                "publicWeb": public_web_base(),   # 0.21.86: invite links open this (kastr.ini public_url here or on the hub)
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
            if room and not kastr_relay.claims_cover(claims, room) and not (
                    room == kastr_relay.LIB_ROOT and claims.get("libv") and isinstance(claims.get("get"), list)):
                return (403, "token does not cover this room")   # 0.21.84: a guest's library viewer token reads named lib/ paths
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
            peer = kastr_relay.client_ip(self) or None   # 0.19.0
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
                if bad and bad[0] == 403 and "cover" in bad[1]:
                    # 0.21.73: a camera from another room on my stage (a watched room, a cross-room grid): any member token
                    # of this relay may ask for it -- a demand only wakes a camera, it grants nothing
                    bad = self._room_claims("", str(p.get("jwt") or ""))
                if bad:
                    return self._json_cors(bad[0], {"error": bad[1]})
                known = ondemand_touch(b)
                fwd = None
                if not known and relay_srv is not None and hasattr(relay_srv, "wake_forward"):
                    # 0.21.7: the camera is registered with ANOTHER site's KASTR (a spoke behind a tunnel, or the hub's
                    # other spoke). Demand travels the way bans and room closes do: up to the hub with the federation
                    # token, out to every spoke over the command channel (kastr_relay.Relay.wake_forward).
                    try:
                        fwd = relay_srv.wake_forward(room, b, 0)
                    except Exception as e:
                        fwd = ["error: " + str(e)[:80]]
                return self._json_cors(200, {"ok": True, "known": known, "forwarded": fwd})
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
            if len(segs) < 2 or any(not WATCH_SEG_RE.match(x) for x in segs) or segs[0].startswith((".", kastr_relay.NS)):
                return self._json_cors(400, {"error": "bad broadcast path"})
            if not self._local():
                bad = self._room_claims(segs[0], jwt)
                if bad:
                    return self._json_cors(bad[0], {"error": bad[1]})
            leaf = segs[-1][:-5] if segs[-1].endswith(".hang") else segs[-1]
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
                hk.fire("read", bcast, "", "", reason="hls viewer", viewer=kastr_relay.client_ip(self))
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
                return self._json_cors(503, {"error": "exporter: %s" % str(e)[:120]})
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
            if len(segs) < 2 or segs[0].startswith((".", kastr_relay.NS)) or any(not WATCH_SEG_RE.match(x) for x in segs):
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
            peer = kastr_relay.client_ip(self) or "?"   # 0.19.0
            now0 = time.time()
            with _WATCH_LOCK:
                # 0.21.8: a fallback player that cannot play asks again every 2-3 s, and every ask is a moq export child that
                # pulls the last 4 s of every track -- a burst for the whole relay per retry (the field's 250 Mbit/s spikes
                # every couple of seconds on the tunnel host). Three starts per peer+broadcast in 30 s is a loop: 429 with
                # Retry-After, one launch.log line a minute.
                key0 = peer + "|" + bcast
                hist = [t for t in _WATCH_STARTS.get(key0, []) if now0 - t < 30]
                if len(hist) >= 3:
                    _WATCH_STARTS[key0] = hist
                    if now0 - _WATCH_LOOP_SAID.get(key0, 0) > 60:
                        _WATCH_LOOP_SAID[key0] = now0
                        (getattr(bridge, "log", None) or _note)("watch: fallback viewer %s is looping on %s (%d starts in 30 s) -- its browser cannot play it; refusing for 30 s" % (peer, bcast, len(hist)))
                    self.send_response(429)
                    self.send_header("Retry-After", "30")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                _WATCH_STARTS[key0] = hist + [now0]
                for k in [k for k, v in _WATCH_STARTS.items() if not v or now0 - v[-1] > 300][:64]:
                    _WATCH_STARTS.pop(k, None)
                if _WATCH_LIVE[0] >= WATCH_MAX:
                    return self._json_cors(503, {"error": "too many fallback viewers on this relay host (%d)" % WATCH_MAX})
                _WATCH_LIVE[0] += 1
            leaf = segs[-1]
            blog = getattr(bridge, "log", None) or _note
            url = relay_srv.url().rstrip("/") + "/" + (("?jwt=" + jwt) if (secured and jwt) else "")
            argv = [moq, "--log-level", "warn", "--connect-once", "--quic-idle-timeout", "15s",
                    "--connect", url, "--broadcast", bcast,
                    "export", "fmp4", "--max-age", "4s"]   # no --video-name: the native pairs' rendition is not called "video" (measured); 0.18 names renditions; 4 s = join mid-GOP
            proc = None
            try:
                proc = bridge.spawn_media(argv, tag="watch:" + leaf[:24], nice=True)
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
                    return self._json_cors(503, {"error": err[:300]})
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

        def _web_page_refused(self, head=False):
            """0.21.32: `web_page = off` -> a browser on another device gets a short notice instead of the page. This
            computer's own window, every /api/ route and the /relay pipe are never refused (KASTR boxes use those)."""
            p = self.path.split("?", 1)[0]
            if not web_page_off() or self._local() or p.startswith("/api/") or p == kastr_relay.WEB_RELAY_PATH:
                return False
            body = ("<!doctype html><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\">"
                    "<title>KASTR</title><body style=\"font:16px system-ui;background:#0b0f14;color:#dfe7ef;padding:32px\">"
                    "<h1 style=\"font-size:20px\">Web clients are off on this relay</h1>"
                    "<p>Open KASTR from the app, or from a relay that has web clients turned on.</p>").encode()
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not head:
                self.wfile.write(body)
            return True

        def _web_public(self):
            """0.21.86: POST /api/web/public {url} -- kastr.ini public_url (empty clears it). Loopback only: the address
            people outside open (e.g. the Cloudflare Tunnel name); the hub hands it to every spoke for invite links."""
            if not self._local():
                return self._deny("web client settings")
            try:
                n = int(self.headers.get("Content-Length") or 0)
                raw = str(json.loads(self.rfile.read(n) or b"{}").get("url") or "").strip() if 0 <= n <= 4096 else ""
            except Exception:
                raw = ""
            url = clean_public_url(raw)
            if raw and not url:
                return self._json_plain(400, {"error": "use https://<name> -- the address people outside your network open (no IP address, no path)"})
            ini_set("public_url", url)
            _note("web: public address %s by the operator" % (url or "cleared"))
            return self._json_plain(200, {"ok": True, "publicUrl": url or ""})

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
                    if MODE in ("relay", "publisher-relay"):   # 0.21.32: the port stays on the network; only the page goes
                        set_web_page(want)
                        _note("web: clients %s by the operator on a relay box (web_page %s; the API stays open for KASTR boxes)"
                              % ("ON" if want else "OFF", "on" if want else "off"))
                    elif want:
                        set_web_page(True)
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
                "enabled": (not web_page_off()) if MODE in ("relay", "publisher-relay") else (enabled and not web_page_off()),   # 0.21.32
                "pageOff": web_page_off(),
                "live": live,
                "web": int(HTTP_PORT or self.server.server_address[1]),
                "https": HTTPS_INFO.get("port"),
                "httpsError": HTTPS_INFO.get("error"),
                "trust": HTTPS_INFO.get("trust") if HTTPS_INFO.get("port") else None,
                "hostname": HTTPS_INFO.get("hostname"),
                "expires": HTTPS_INFO.get("expires"),
                "urls": self._web_urls(),
                "publicUrl": clean_public_url(ini_get("public_url")) or "",   # 0.21.86: invite links (One port card)
                "publicHub": HUB_PUBLIC[0],
                "lan": ["http://%s:%d" % (ip, HTTP_PORT) for ip in _kr.local_ips()] if (LAN_OK and HTTP_PORT) else [],
                "relayRunning": relay_running,
                "relayLan": bool(relay_running and getattr(relay_srv, "bind_all", False)),
                "firewall": fw_state,
                "relayOnly": MODE in ("relay", "publisher-relay"),
                "hostIni": host,
                "path": _ini_file(),
                "note": None if live else "applies at the next launch -- Apply & relaunch",
                # 0.19.0: one port -- what to give cloudflared, and whether anything came through it
                "tunnel": {"origin": "http://localhost:%d" % int(HTTP_PORT or self.server.server_address[1]),
                           "path": kastr_relay.WEB_RELAY_PATH, "pipes": _RELAY_WS[0], "singlePort": SINGLE_PORT,
                           "seen": TUNNEL_SEEN.get("base"),
                           "seenAgo": (int(time.time() - TUNNEL_SEEN["at"]) if TUNNEL_SEEN.get("at") else None),
                           # 0.20.0: proxied visitors have reached this relay while it had no access codes
                           "open": bool(TUNNEL_SEEN.get("at") and relay_running and not getattr(relay_srv, "secured", False))},
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
            if re.match(r"^/relay(/|$)", path) and (self.headers.get("Upgrade") or "").lower() == "websocket":
                return self._relay_ws()                                       # 0.19.0: media through the web port
            if path == "/api/rooms/board":                                    # 0.21.63: the room board lives at the minter
                return self._auth_proxy("GET")
            if path.startswith("/api/chat/") or path.startswith("/api/rooms/"):   # 0.12.0 (NOT /api/rooms itself: the minter proxy)
                return self._chat_api("GET")
            if path.startswith("/api/watch/"):                                # 0.17.0: the fMP4 fallback
                return self._watch_stream(path)
            if path.startswith("/api/hls/"):                                  # 0.18.0: HLS behind a key
                return self._hls_proxy(path)
            if path == "/api/ondemand":                                       # 0.18.0
                return self._ondemand_api("GET", path)
            if path == "/api/update/offer":                                   # 0.21.50: is an update waiting for the person's answer?
                if not self._local():
                    return self._deny("update offers")
                off = dict(UPDATE_OFFER) if UPDATE_OFFER.get("version") else None
                adm = dict(ADMIN_NOTICE) if ADMIN_NOTICE.get("kind") and time.time() < float(ADMIN_NOTICE.get("deadline") or 0) + 30 else None   # 0.21.73
                raw = json.dumps({"offer": off, "version": read_version(), "admin": adm}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)
                return
            if path in ("/api/archive", "/api/archive/get"):   # 0.18.0
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
            if path in ("/api/auth", "/api/token", "/api/rooms", "/api/bans", "/api/spokes/link",   # 0.11.0: + remembered rooms; 0.19.0: + the hub's bans; 0.21.25: + spokes/link
                        "/api/xshare",                                                          # 0.21.41: the cross-room listings into a room
                        "/api/fleet/relays",                                                    # 0.21.91: the fleet's relays (the closest relay)
                        "/api/library", "/api/library/still",                                   # 0.21.84: the stream library's catalogue, a still
                        "/api/invites"):                                                        # 0.21.75: a room's live invite links
                return self._auth_proxy("GET")
            if path == "/api/msg/file":                                         # 0.21.88: a message attachment's ciphertext
                return self._auth_proxy("GET")
            if path == "/api/templates/deck":                                   # 0.21.92: a template deck's file (a read grant)
                return self._auth_proxy("GET")
            if path == "/api/meetings/ics":                                     # 0.21.96: a meeting's calendar link (its key is the capability)
                return self._auth_proxy("GET")
            if path.startswith("/api/avatar/"):                                 # 0.21.90: a person's profile photo (the hub's copy)
                return self._avatar_get()
            if path.startswith("/api/gif/"):                                    # 0.21.91: GIF search (the member token rides along)
                return self._auth_proxy("GET")
            if path == "/api/invite/pending":                                 # 0.21.75: the app hand-off (this machine only)
                return self._invite_pending("GET")
            if path == "/api/files":
                return self._file_list(parse_qs(urlparse(self.path).query))
            if path.startswith("/api/files/"):
                return self._file_get(path[len("/api/files/"):])
            if path == "/api/alive":
                return self._alive()
            if path == "/api/lockstate":   # 0.21.41: is this computer locked? (screen shares stop) -- this machine's window only
                if not self._local():
                    return self._deny("session state")
                import kastr_lock
                return self._json_plain(200, {"locked": kastr_lock.locked()})
            if path == "/api/mic/hwmute":   # 0.21.41: the microphones' own (Windows) mute -- this machine's window only
                if not self._local():
                    return self._deny("microphone state")
                import kastr_micmute
                return self._json_plain(200, kastr_micmute.snapshot())
            if path == "/api/instance":
                return self._instance()
            if path == "/api/client":                                       # 0.17.0
                return self._client_api()
            if path == "/api/web":                                          # 0.17.0
                return self._web_api("GET")
            if path == "/api/camfx/studio":
                # 0.21.94: which cameras offer the Windows Studio Effects blur (cached; ?fresh=1 asks again). Local pages only.
                if not self._local():
                    return self._deny("camera settings")
                fresh = (parse_qs(urlparse(self.path).query).get("fresh") or [""])[0] == "1"
                return self._json_plain(200, studiofx().cameras(fresh=fresh))
            if path in ("/api/autorun", "/api/mode") and not self._local():
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
            if path == "/api/peer/instance":
                # 0.8.6: what KASTR runs on another machine (the relay host)
                # -- proxied because a page can't cross-origin fetch it under
                # COEP without CORS.
                qs = parse_qs(urlparse(self.path).query)
                host = (qs.get("host") or [""])[0].strip()
                port = (qs.get("port") or [""])[0].strip()   # 0.21.7: optional -- the learned web port is the fallback, never a literal
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
                relay_q = (qs.get("relay") or [""])[0].strip()
                if host.strip("[]").lower() in _own_hosts() and not (relay_q and kastr_relay.is_web_relay(relay_q)):
                    return self._instance()   # 0.21.7: the relay host is this very machine -- no dial, no guessed port
                wbase = None
                host_ok = bool(re.match(r"^[A-Za-z0-9.\-\[\]:]{1,253}$", host))
                if relay_q and kastr_relay.is_web_relay(relay_q):
                    wbase = kastr_relay.web_origin(relay_q)          # 0.19.0: https://name/relay -> https://name
                elif host_ok and re.match(r"^\d{1,5}$", port):
                    wbase = "http://%s:%s" % (host, port)             # the caller knows the port
                elif host_ok:
                    # 0.21.7: the learned base (hub-web.json), else the learned web port, else this box's
                    # configured hub default -- Agg and Mendon run their web on 8001 and the line said :8000
                    wbase = hub_web_base(host, HUB_WEB_PORT)
                if wbase:
                    try:
                        import urllib.request
                        with urllib.request.urlopen(wbase + "/api/instance", timeout=3) as r:
                            data = json.load(r)
                    except Exception as e:
                        data = {"error": "unreachable", "detail": str(e)[:120]}
                if isinstance(data, dict):
                    data["base"] = wbase                              # 0.21.7: the page words its line from this
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
                sd = self._state_dir()
                body = json.dumps({
                    "app": "KASTR", "version": read_version(),
                    "platforms": {k: {"size": v["size"], "sha256": v["sha256"], "version": v.get("version")}   # 0.21.1: + version
                                  for k, v in plats.items()},
                    "browser": {"version": bf["version"],
                                "platforms": {k: {"size": v["size"], "sha256": v["sha256"], "root": v["root"]}
                                              for k, v in bf["platforms"].items()}},
                    # 0.21.7: the templates the feed carries (updates/<plat>/extras, mirrored like the binaries) and
                    # the full install zips this host can assemble for a web client (kastr_release)
                    "extras": {k: kastr_release.extras_manifest(kastr_release.app_root(), k) for k in kastr_release.EXTRAS},
                    "zip": ({k: kastr_release.status(k, read_version(), sd) for k in kastr_release.PLATFORMS} if sd else {}),
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
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % os.path.basename(info["path"]))   # 0.21.7
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
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % os.path.basename(info["path"]))   # 0.21.7
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
            if path == "/api/update/zip":         # 0.21.7: the full install zip, assembled here (POST prepares it)
                return self._release_zip("GET")
            if path == "/api/update/extra":       # 0.21.7: one template file of the feed (kastr.ini, Linux extras)
                return self._release_extra()
            if path == "/api/diag":
                return self._diag_get()
            if path == "/api/relay/chat/purge":   # 0.21.3: operator purge (kastr_serve owns the chat store)
                return self._chat_purge()
            if relay_srv and kastr_relay.handle_api(self, relay_srv, path, self._set_relay):
                return
            if path.startswith("/api/rcfiles"):     # 0.21.83: files + pictures over remote control -- caps, status, a chunk
                import kastr_rcfiles
                return kastr_rcfiles.handle_api(self, _note, ini_get)
            if path.startswith("/api/lan/"):   # 0.21.22: relay discovery + probe (this machine only)
                return self._lan_api(path, "GET")
            if path in ("/api/screen/sources", "/api/screen/thumb", "/api/screen/sound", "/api/screen/devices", "/api/screen/rtmp", "/api/screen/rtmp/firewall"):   # 0.21.20: the native share picker + presenter sound; 0.21.26: + cameras
                return self._screen_api(path)
            if path in ("/api/rcadmin", "/api/rcadmin/session", "/api/rcadmin/ask"):   # 0.21.83 (D): this machine's opt-in, its sessions; the helper page's session; 0.21.92: the Allow prompt's monitors
                import kastr_rcadmin
                return kastr_rcadmin.handle_api(self, self._rcadmin_dir(), _note)
            if path == "/api/rc":                   # 0.21.79: remote control -- what this computer can do + the grant's state
                import kastr_rc
                return kastr_rc.handle_api(self, bridge, _note)
            if path == "/api/rc/ws":                # 0.21.80: the sharer page's WebSocket to it while a grant lasts (input in, pointers out)
                import kastr_rc
                return kastr_rc.handle_ws(self, bridge, _note)
            if path.startswith("/api/record/"):     # 0.21.81: Record's save formats -- what ffmpeg can write, progress, the result
                import kastr_record
                return kastr_record.handle_api(self, bridge, self._state_dir(), _note)
            if path.startswith("/api/presrec/"):    # 0.21.92 H: record the presentation -- its state, a recording's file, the recorder page
                import kastr_presrec
                return kastr_presrec.handle_api(self, _note)
            if path.startswith("/api/pres/"):       # 0.21.84 (prototype): an encrypted slide / the notes, Office detection
                import kastr_pres
                return kastr_pres.handle_api(self, self._state_dir(), _note)
            if bridge:
                # RTSP endpoints are dynamic, so they must be checked before the
                # static file handler turns the path into a 404.
                if kastr_rtsp.handle_api(self, bridge, path):
                    return
                if kastr_rtsp.handle_stream(self, bridge, path):
                    return
            if path in ("/join", "/join.html"):
                return self._join_page()                                      # 0.21.75: an invite link lands here
            if self._web_page_refused():   # 0.21.32
                return
            body = self._rewritten()
            if body is None:
                return super().do_GET()
            self._serve_rewritten(body, include_body=True)

        def _join_page(self, head=False):
            """0.21.75: /join#i=<token>&room=<slug> -- opens the KASTR app (kastr://) when it is installed, else this host's
            web page. Served even when web clients are off (the app hand-off still works; the browser button hides)."""
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            self.path = "/join.html" + ("?" + q if q else "")
            body = self._rewritten()
            if body is None:
                return self.send_error(404, "join page missing")
            body = body.replace(b"__KASTR_WEB_PAGE__", b"off" if web_page_off() else b"on")
            self._serve_rewritten(body, include_body=not head)

        def do_HEAD(self):
            if self.path.split("?", 1)[0].startswith("/api/chat/"):   # 0.12.0: attachments
                return self._chat_api("HEAD")
            if self.path.split("?", 1)[0].startswith("/api/files/"):   # 0.8.7
                return self._file_get(self.path.split("?", 1)[0][len("/api/files/"):], head=True)
            if self.path.split("?", 1)[0].startswith("/api/media/"):   # 0.8.13
                return self._media_get(self.path.split("?", 1)[0][len("/api/media/"):], head=True)
            if self.path.split("?", 1)[0] in ("/join", "/join.html"):   # 0.21.75
                return self._join_page(head=True)
            if self._web_page_refused(head=True):   # 0.21.32
                return
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


# ---- 0.21.22: relay discovery on the LAN (kastr_mdns) ---------------------------------------------------------------
MDNS_ADV = [None]
_MDNS_FP = {"at": 0.0, "fp": ""}


def mdns_advertise(state_dir, value=None):
    """Read (value None) or write the 'advertise this relay on mDNS' switch -- mdns.json, ON unless switched off."""
    p = os.path.join(state_dir or "", "mdns.json")
    if value is not None:
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"advertise": bool(value)}, f)
        except OSError:
            pass
        return bool(value)
    try:
        with open(p, encoding="utf-8") as f:
            return bool(json.load(f).get("advertise", True))
    except Exception:
        return True


def _mdns_info(relay_srv, web_port):
    """What the advertiser says about this relay right now -- None while it is not reachable from other machines."""
    try:
        if not (relay_srv.running() and relay_srv.bind_all and mdns_advertise(relay_srv.state_dir)):
            return None
        now = time.time()
        if now - _MDNS_FP["at"] > 30:   # the fingerprint is an HTTP fetch -- not on every query
            _MDNS_FP["fp"], _MDNS_FP["at"] = relay_srv.fingerprint() or "", now
        shown = relay_srv.relay_name() or socket.gethostname()
        inst = re.sub(r"[^A-Za-z0-9 ._-]+", "-", shown)[:40].strip() or "relay"
        return {"name": inst + " (KASTR)", "host": host_slug(), "port": web_port,
                "txt": {"v": read_version(), "nm": shown[:40], "rp": str(relay_srv.port), "wp": str(web_port),
                        "sec": "1" if relay_srv.secured else "0", "fp": _MDNS_FP["fp"]}}
    except Exception:
        return None


def probe_relay(url, timeout=1.5, name=True):
    """Is a relay address online? A native relay answers /certificate.sha256 over HTTP on its own port (the fingerprint
    comes back too); a web relay (an address ending /relay) is its host's web server. 0.21.91: name=False skips the name
    lookup (the extra samples of closest_relays)."""
    import ssl
    try:
        u = urlparse(str(url or "").strip())
        if not u.hostname or u.scheme not in ("http", "https"):
            return {"online": False, "error": "not a relay address"}
        web = (u.path or "").rstrip("/").endswith("/relay")
        hn = "127.0.0.1" if u.hostname in ("localhost", "::1") else u.hostname   # localhost tried ::1 first and waited out the timeout
        target = ("%s://%s/api/client" % (u.scheme, u.netloc)) if web else ("http://%s:%d/certificate.sha256" % (hn, u.port or 443))
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE   # liveness only
        t0 = time.time()
        with urllib.request.urlopen(target, timeout=timeout, context=ctx if target.startswith("https") else None) as r:
            body = r.read(512).decode("ascii", "replace").strip()
        fp = "" if web else (body if re.match(r"^[0-9a-fA-F:]{40,}$", body) else "")
        out = {"online": True, "fp": fp.lower(), "ms": int((time.time() - t0) * 1000), "web": web}
        if not name:
            return out
        # 0.21.33: the relay's name for the pickers -- its access-code service answers /api/auth (port + 1 on a native
        # relay, the web port behind a web relay); an open relay has none and stays nameless
        try:
            auth = ("%s://%s/api/auth" % (u.scheme, u.netloc)) if web else ("http://%s:%d/api/auth" % (hn, (u.port or 443) + 1))
            with urllib.request.urlopen(auth, timeout=1.0, context=ctx if auth.startswith("https") else None) as r2:
                nm = json.loads(r2.read(4096) or b"{}").get("name")
            if isinstance(nm, str) and nm.strip():
                out["name"] = nm.strip()[:32]
        except Exception:
            pass
        return out
    except Exception as e:
        return {"online": False, "error": str(e)[:120]}


def _is_private_ip(ip):
    """0.21.36: RFC 1918, CGNAT 100.64/10, link-local and loopback count as 'on our network'."""
    import ipaddress
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.is_private or a.is_loopback or a.is_link_local or (a.version == 4 and a in ipaddress.ip_network("100.64.0.0/10"))


def hops_to(ip, timeout_ms=1000):
    """0.21.36 (Kenton: "auto selecting a relay based on hops"): the hop count from ONE ping's reply TTL -- what a
    traceroute counts, in one round trip. The sender's starting TTL is the next of 64 / 128 / 255 at or above the reply's
    (Linux / Windows / network gear). None when the host does not answer ICMP."""
    win = sys.platform == "win32"
    cmd = ["ping", "-n", "1", "-w", str(int(timeout_ms)), ip] if win else ["ping", "-c", "1", "-W", str(max(1, int(timeout_ms / 1000))), ip]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout_ms / 1000.0 + 3,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        m = re.search(r"ttl[=:]\s*(\d+)", out.stdout or "", re.I)
        if not m:
            return None
        ttl = int(m.group(1))
        start = 64 if ttl <= 64 else 128 if ttl <= 128 else 255
        return max(0, start - ttl)
    except Exception:
        return None


def rank_relays(urls, probe=None, hops=None, resolve=None):
    """0.21.36: the relays nearest first. Each: {url, online, private, hops, ms, name}. Online beats offline; a PRIVATE
    address beats a public one (the public address is only for when no relay on our network answers); then fewer hops
    (an unknown hop count after every known one), then the faster answer (Kenton: "hops, then time")."""
    import socket
    from concurrent.futures import ThreadPoolExecutor
    probe = probe or probe_relay
    hops = hops or hops_to
    resolve = resolve or (lambda h: socket.gethostbyname(h))
    seen, todo = set(), []
    for u in urls or []:
        u = str(u or "").strip()
        if u and u not in seen and u.startswith(("http://", "https://")):
            seen.add(u)
            todo.append(u)

    def one(u):
        rec = {"url": u, "online": False, "private": False, "hops": None, "ms": None}
        try:
            host = urlparse(u).hostname or ""
            ip = host if re.match(r"^[0-9.]+$|:", host) else resolve(host)
            rec["private"] = _is_private_ip(ip) and not kastr_relay.is_web_relay(u)   # a tunnel address is the public way in
        except Exception:
            ip = None
        r = probe(u)
        rec["online"] = bool(r.get("online"))
        if rec["online"]:
            rec["ms"] = r.get("ms")
            if r.get("name"):
                rec["name"] = r["name"]
            if ip:
                rec["hops"] = hops(ip)
        return rec
    with ThreadPoolExecutor(max_workers=min(16, max(1, len(todo)))) as ex:
        out = list(ex.map(one, todo))
    big = 10 ** 6
    out.sort(key=lambda r: (not r["online"], not r["private"], r["hops"] if r["hops"] is not None else big, r["ms"] if r["ms"] is not None else big))
    return out


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def closest_relays(cands, samples=3, timeout=1.5, probe=None, resolve=None):
    """0.21.91 (Kenton: "On launch of KASTR always do a check to find the closest relay and select that ... If none are online
    and available, put a note"): the candidate relays nearest first by MEASURED round trip. cands: [{name, urls, fleet, lan}]
    -- a relay with every address it is known by (LAN / private / public). Every address is sampled `samples` times (the relay's
    own /certificate.sha256 over HTTP, `timeout` each; an address that does not answer its first sample is not asked again),
    the addresses in parallel; an address's RTT is the median of its answers. A relay is dialled at its reachable address -- a
    private (LAN) one before a public one, then the fastest -- and ranks by that RTT: online first, then the lowest; a tie
    (within 1 ms) goes to the fleet's relay. -> [{name, url, ms, online, private, fleet, lan, fp, addrs: [{url, ms, online,
    private}]}]."""
    import socket
    from concurrent.futures import ThreadPoolExecutor
    probe = probe or probe_relay
    resolve = resolve or (lambda h: socket.gethostbyname(h))
    rel, jobs = [], []
    for c in (cands or [])[:32]:
        if not isinstance(c, dict):
            continue
        urls = []
        for u in (c.get("urls") or [])[:8]:
            u = str(u or "").strip()
            if u.startswith(("http://", "https://")) and u not in urls:
                urls.append(u)
        if not urls:
            continue
        rel.append({"name": str(c.get("name") or "")[:40], "fleet": bool(c.get("fleet")), "lan": bool(c.get("lan")), "urls": urls})
        for u in urls:
            jobs.append(u)
    jobs = list(dict.fromkeys(jobs))

    def one(u):
        rec = {"url": u, "online": False, "ms": None, "private": False, "fp": "", "name": ""}
        try:
            host = urlparse(u).hostname or ""
            ip = host if re.match(r"^[0-9.]+$|:", host) else resolve(host)
            rec["private"] = _is_private_ip(ip) and not kastr_relay.is_web_relay(u)
        except Exception:
            pass
        got = []
        for i in range(max(1, int(samples))):
            r = probe(u, timeout, name=(i == 0)) if i == 0 else probe(u, timeout, name=False)
            if not r.get("online"):
                if i == 0:
                    break
                continue
            got.append(float(r.get("ms") or 0))
            if i == 0:
                rec["fp"] = r.get("fp") or ""
                rec["name"] = r.get("name") or ""
        if got:
            rec["online"] = True
            rec["ms"] = round(_median(got), 1)
            rec["samples"] = [round(x, 1) for x in got]
        return rec
    with ThreadPoolExecutor(max_workers=min(24, max(1, len(jobs)))) as ex:
        res = dict(zip(jobs, ex.map(one, jobs)))
    out = []
    for r in rel:
        addrs = [res[u] for u in r["urls"]]
        up = [a for a in addrs if a["online"]]
        pick = sorted(up, key=lambda a: (not a["private"], a["ms"]))[0] if up else addrs[0]
        out.append({"name": r["name"] or pick.get("name") or "", "url": pick["url"], "ms": pick["ms"] if up else None, "online": bool(up),
                    "private": pick["private"], "fleet": r["fleet"], "lan": r["lan"], "fp": pick.get("fp") or "",
                    "addrs": [{"url": a["url"], "ms": a["ms"], "online": a["online"], "private": a["private"]} for a in addrs]})
    big = 10 ** 9
    out.sort(key=lambda r: (not r["online"], round(r["ms"]) if r["ms"] is not None else big, not r["fleet"]))
    return out


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
        # 0.21.91: a page opens ~50 files at once; socketserver's default listen queue of 5 refused some of them (pages that
        # half-loaded until a reload)
        request_queue_size = 128

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
    RTSP_BRIDGE[0] = bridge   # 0.21.16
    if bridge is not None and relay_srv is not None:
        # 0.21.85 (Kenton: a relay / hub machine's shares are listed in the stream library automatically): the bridge asks
        # whether THIS machine runs the relay -- its shares (native and the page's own) are then listed by default
        bridge.relay_here = lambda rs=relay_srv: bool(rs.running())
    if relay_srv is not None and MDNS_ADV[0] is None:   # 0.21.22: discovery-only mDNS advertisement of this relay
        try:
            import kastr_mdns
            web_port = srv.server_address[1]
            MDNS_ADV[0] = kastr_mdns.Advertiser(lambda: _mdns_info(relay_srv, web_port), log=_note)
            MDNS_ADV[0].start()
        except Exception as e:
            _note("mdns: not started: %s" % e)
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
        start_hub_rooms_keeper(relay_srv)   # 0.21.35: the hub's rooms, copied here every minute
        start_hub_clock(relay_srv)          # 0.21.37: one fleet clock for latency (the hub's)
    srv.relay_ref = relay_ref
    srv.alive_ref = alive_ref
    srv.diag_ref = DIAG_REF   # 0.21.74: the box keeper reads the box page's own reports (kastr.box_keeper)
    if bridge is not None and not getattr(srv, "is_tls", False):
        _rcadmin_start(srv, bridge, relay_srv, relay_ref, hostname)   # 0.21.83 (D)
    if relay_srv is not None and not getattr(srv, "is_tls", False):   # 0.21.92 H: record the presentation (on the relay host)
        try:
            import kastr_presrec
            kastr_presrec.start(getattr(relay_srv, "state_dir", None) or STATE_DIR, relay=relay_srv,
                                web_port=lambda: HTTP_PORT or srv.server_address[1],
                                ffmpeg=getattr(bridge, "ffmpeg", None) if bridge is not None else None, note=_note)
        except Exception as e:
            _note("presrec: not available: %r" % e)
    return srv


def _rcadmin_start(srv, bridge, relay_srv, relay_ref, hostname=None):
    """0.21.83 (D) (Kenton: "allow remote control with the admin permissions on a relay/hub/camera box ... opt-in only"):
    the machine's agent (kastr_rcadmin.Agent) -- it does nothing until this machine's own Relay page ticks "Let fleet admins
    control this machine without asking"; then it polls the hub through the relay this KASTR uses."""
    try:
        import kastr_rcadmin
    except Exception as e:
        _note("rcx: not available: %s" % e)
        return None
    sd = STATE_DIR or (relay_srv.state_dir if relay_srv is not None else None) or getattr(bridge, "state_dir", None)
    if not sd:
        return None

    def info():
        name = ""
        if relay_srv is not None:
            try:
                with open(os.path.join(relay_srv.state_dir, "operator.json"), encoding="utf-8") as f:
                    name = str(json.load(f).get("name") or "")[:30]
            except Exception:
                name = ""
        return {"operator": name, "mode": MODE}
    agent = kastr_rcadmin.start_agent(sd, bridge, lambda: relay_ref[0] or BUILTIN_RELAY, relay_srv, _note,
                                      web_port=lambda: HTTP_PORT or srv.server_address[1], info=info)
    if agent is not None and hostname and agent.node is None:
        agent.node = host_slug(hostname)   # the identity this KASTR's pages and bridge use (a lab harness names it)
    return agent


def make_bridge(state_dir=None, log=None, hostname=None):
    """An RTSP bridge; reports ffmpeg availability via its .ffmpeg attribute.
    0.9.8: `state_dir` hosts the child registry, `log` the launcher's note().
    0.13.0: `hostname` must be the SAME value the launcher gives make_server /
    make_handler (both None today): the bridge's publishers mint tokens scoped
    to host_slug(hostname), and the page's HOSTNAME comes from the same slug."""
    global STATE_DIR
    if state_dir and not STATE_DIR:
        STATE_DIR = state_dir   # 0.21.46: the kept host id lives there -- the bridge is made before the launcher sets it
    b = kastr_rtsp.Bridge(state_dir=state_dir, log=log, host_slug=host_slug(hostname))
    b.web_base_for = _od_web_base      # 0.18.0: where the on-demand loop syncs
    b.lib_cap_fetch = kastr_rtsp.relay_library   # 0.21.84: the box asks its relay whether it serves the stream library
    global ONDEMAND_POKE
    ONDEMAND_POKE = b.od_poke          # 0.21.73
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
