#!/usr/bin/env python3
"""RTSP ingest bridge.

Browsers cannot open RTSP -- there is no API for it and no flag to enable one.
So an ffmpeg child process pulls the RTSP feed and remuxes it to fragmented MP4,
which this module streams over plain HTTP to a <video> element in the page. The
page then does videoEl.captureStream() and publishes the resulting track over
MoQ, which is the same route the library's own "file" source takes.

    RTSP camera --> ffmpeg --> fMP4 over HTTP --> <video> --> captureStream()
                                                          --> MoQ Video.Encoder

Endpoints (wired up by kastr_serve):
    POST /api/rtsp/add     {"url": "rtsp://..."}  -> {"id": 1, "path": "/rtsp/1"}
    POST /api/rtsp/remove  {"id": 1}              -> {"ok": true}
    GET  /api/rtsp/list                           -> {"feeds": [...], "ffmpeg": bool}
    GET  /rtsp/<id>                               -> endless fragmented MP4
    GET  /api/rtsp/library                        -> 0.21.84: the box's stream library switches (see Bridge.lib_public)
    POST /api/rtsp/library {"id", "on": bool|null} | {"master": bool}
                           | {"id", "list": bool|null}                   0.21.85: a native share LISTED in the library (kept in its room)
                           | {"shares": [...], "relay"}                  0.21.85: the page's own listed shares (rows for the heartbeat)
    POST /api/rtsp/transport {"id", "transport": "auto"|"tcp"|"udp"}     0.21.96: how an rtsp:// camera is pulled (restarts its readers)

Transcoding costs latency -- expect a few hundred ms on top of the sub-100ms
WebCodecs path. Video is re-encoded to H.264 baseline because that is what
every browser can decode from an MP4 container; audio to AAC for the same
reason. `-tune zerolatency` and `-g 30` keep the fragment cadence tight.
"""
import json
import kastr_ua  # noqa: F401  -- 0.21.64: every request says KASTR (Cloudflare refuses Python-urllib)
import kastr_secret         # 0.21.92: rtsp-feeds.json keeps its codes (and camera passwords) sealed
import os
import shutil
import re
import subprocess
import time
import sys
import threading
import base64               # 0.12.0: token expiry from the jwt body
import urllib.request       # 0.12.0: the relay's token service (mint_member)
import urllib.error
from urllib.parse import urlsplit

# A synthetic feed, so the whole pipeline can be proven end to end without a
# camera on the network. Anything that reaches the <video> element here is also
# going to reach it from a real RTSP source.
TEST_URL = "test://pattern"
SCREEN_PREFIX = "screen://"      # 0.21.20: screen://monitor/<n> | screen://window/<hwnd> -- the host captures it natively


def is_screen(url):
    return str(url or "").strip().lower().startswith(SCREEN_PREFIX)


# 0.21.80 (Kenton: "I would like remote control to be faster if possible. There is a bit of delay."): while someone CONTROLS a
# native share its encode turns low-latency (the share restarts once into it and once back -- Bridge.rc_mode). Per encoder,
# each list validated once by a short test encode before it is used (Bridge.rc_lowlat; a hardware encoder that refuses an
# option keeps its normal arguments rather than failing the share). libx264 already runs -tune zerolatency (no B-frames, no
# lookahead): a VBV of ~200 ms caps a screen-wide change's frame so it leaves in one frame time instead of a burst.
RC_LOWLAT = {
    "libx264": ["-maxrate", "5M", "-bufsize", "1M"],
    "h264_nvenc": ["-preset", "p1", "-tune", "ull", "-zerolatency", "1", "-delay", "0", "-bf", "0", "-rc", "cbr"],
    "h264_qsv": ["-bf", "0", "-async_depth", "1", "-look_ahead", "0"],
    "h264_amf": ["-usage", "ultralowlatency", "-bf", "0"],
    "h264_mf": ["-scenario", "display_remoting"],
    "h264_vaapi": ["-bf", "0"],
}
RC_MUX = ["-flush_packets", "1"]   # every frame to moq-cli as it is muxed (measured per frame already on Linux; insurance elsewhere)


def is_private(feed):
    """0.21.83 (D): a fleet admin's private capture (Bridge.add_private) -- its `private` tag is the session id."""
    tag = getattr(feed, "private", None)
    return isinstance(tag, str) and bool(tag)


def _rc_gone(feed_id, why):
    """0.21.79: remote control of this share ends (it stopped, paused or now shows something else) -- only when kastr_rc
    was ever loaded (a box nobody controls never imports it)."""
    m = sys.modules.get("kastr_rc")
    if m is not None:
        try:
            m.share_gone(int(feed_id), why)
        except Exception:
            pass

# Longest we will wait for ffmpeg to name a stream's codec.
PROBE_TIMEOUT = 20.0
# 0.21.10: on-demand pairs (0.18.0 standby) and low copies (0.18.0 / 0.21.7 `-low.hang`) are OFF unless this is
# true -- env KASTR_ONDEMAND=1 here (dev harness, rigs), kastr.ini `ondemand = on` through the launcher (kastr.py).
# Read once at boot. A Publisher built while it is off never sleeps and never owns a low sibling, but remembers
# what was ASKED (wantOndemand / wantLow) so rtsp-feeds.json keeps the operator's choice for a later re-enable.
def ffmpeg_exit_reason(code):
    """0.21.52: what an ffmpeg exit code says (Linux keeps the low byte of the negative AVERROR, Windows the whole 32 bits)."""
    try:
        c = int(code)
    except (TypeError, ValueError):
        return ""
    if c > 0x7FFFFFFF:
        c -= 0x100000000
    known = {-1094995529: "invalid data from the camera", -541478725: "the camera's stream ended", -110: "the camera timed out",
             -138: "the camera timed out", -111: "the camera refused the connection", -10061: "the camera refused the connection",
             -5: "input/output error", -113: "no route to the camera", -10065: "no route to the camera", -2: "not found"}
    if c in known:
        return known[c]
    low = {183: -1094995529, 187: -541478725, 146: -110, 145: -111, 251: -5, 143: -113}
    return known.get(low.get(c & 0xFF if 0 < c < 256 else None), "")


ONDEMAND_ENABLED = str(os.environ.get("KASTR_ONDEMAND") or "").strip().lower() in ("1", "true", "yes", "on")
# 0.21.73 (Kenton, Mendon's CPU with pass through off: "encode only while watched"; he chose: only the cameras this box
# TRANSCODES): a grid camera whose pair encodes stops a minute after its last viewer and starts again on a viewer's demand
# (the grid keeps drawing from the camera's monitor). A pair that copies costs next to nothing and stays on (instant opens).
# kastr.ini `sleep_unwatched = off` (or KASTR_SLEEP_UNWATCHED=0) keeps every pair encoding always.
SLEEP_UNWATCHED = str(os.environ.get("KASTR_SLEEP_UNWATCHED") or "on").strip().lower() not in ("0", "false", "no", "off")
# 0.12.0: a probe that could not tell (camera off when a restored feed came
# back) is asked again after this long instead of being believed for the run.
PROBE_RETRY_S = 30.0
# 0.21.75 (Kenton: a Publisher box "shares its cameras into the rooms I pick" without being in a room): the BOX SERVER keeps
# each camera's cross-room listings (POST /api/xshare at its relay's minter, the 0.21.41 registry) -- so they hold with no
# window open and come back after a restart (rtsp-feeds.json `xs` / `xsCodes` per feed record).
XS_TICK_S = 60           # every listing is re-POSTed this often (the relay keeps one XSHARE_TTL = 180 s)
XS_AIR_CHECK_S = 10      # 0.21.76: how often the loop looks for a camera that started or stopped streaming
XS_DARK_S = 20           # 0.21.76: a camera with no data this long is withdrawn from its other rooms
XS_START_GRACE_S = 30    # ... except in its first seconds (no byte yet is not "dark" yet)


def xs_on_air(pub, now=None):
    """0.21.76 (Kenton: streams that "only run sometimes ... never go away when nothing is streamed, they always show
    connecting" in the rooms they are also shown in): a camera is listed in its other rooms only while it really streams --
    or while it sleeps because nobody watches (0.21.73), since a viewer's click there wakes it. A pair that runs against a
    dark camera, an RTMP ingest with no device pushing, a stopped share: withdrawn until data flows again."""
    now = time.time() if now is None else now
    if getattr(pub, "standby", False) and getattr(pub, "sleepy", False):
        return True
    if not getattr(pub, "running", False):
        return False
    fa = getattr(pub, "flowingAt", None)
    if fa and now - fa < XS_DARK_S:
        return True
    since = getattr(pub, "since", None)
    return bool(not fa and since and now - since < XS_START_GRACE_S)
XS_ROOMS_MAX = 16        # rooms one camera may show in (kastr_relay XSHARE_TARGETS_MAX)
XS_TOKEN_MIN_S = 600     # a cached member token is re-minted once it ends within this
HOME_PREFIX = "box-"     # a box's hidden home room: box-<host slug> (pages leave box-* rooms out of every list)
_XS_ROOM_RE = re.compile(r"^[a-z0-9-]{1,32}$")


def home_room(host):
    """0.21.75: a box's hidden HOME room -- box-<host slug>, cut to a room's 32 characters (the host's 4-hex suffix
    kept, so two boxes with one long name still get two rooms). The page's homeRoomOf() is the same rule."""
    h = re.sub(r"[^a-z0-9-]+", "-", str(host or "").lower()).strip("-") or "host"
    s = HOME_PREFIX + h
    if len(s) > 32:
        name, _, suf = h.rpartition("-")
        if name and len(suf) == 4:
            s = HOME_PREFIX + name[:32 - len(HOME_PREFIX) - 5].strip("-") + "-" + suf
        else:
            s = s[:32].rstrip("-")
    return s


def is_home_room(slug):
    """0.21.75: a box's home room (no person is ever in one; no list shows one)."""
    return str(slug or "").startswith(HOME_PREFIX)


# ---- 0.21.96 BOX-OUT (Kenton, 2026-10-30: "For Relays/Camera boxes, I would like them to not be able to directly connect to
# rooms, they connect to their 'My room' or no room at all, and their shares just go to the library or whatever rooms they tell
# them to."): a boxed machine (kastr_serve.boxout_state -- a camera box, or a KASTR that runs the relay itself) sits in its hidden
# home room (box-<host>) or its own My room. A box that sat in a real room moves out ONCE (boxout_migrate, at the launch of the
# new version) and keeps every camera LISTED back into that room (Show in rooms), its old path kept as a library alias.
BOXOUT_PERSONAL_RE = re.compile(r"^me-[0-9a-f]{12}$")
BOXOUT_LIB = "lib"   # (= LIB_ROOT, defined further down)
BOXOUT_REFUSED = ("this relay / camera box machine stays in No room or its My room -- its cameras show in rooms through "
                  "Show in rooms")


def boxout_real_room(slug):
    """0.21.96: a room a boxed machine may not sit in -- anything but its home room (box-*), a My room (me-*), the library
    root or no room at all. The Lobby (main) counts: a boxed machine never waits there."""
    s = str(slug or "").strip().lower()
    return bool(s) and not is_home_room(s) and not BOXOUT_PERSONAL_RE.match(s) and s != BOXOUT_LIB


def boxout_migrate(doc, host, now=None, why="box"):
    """0.21.96: rtsp-feeds.json of a boxed machine that still names a real room R -> its home room, once. Each of the
    machine's OWN cameras there (a web client's camera in its own room is left alone) moves R/<rest> -> box-<host>/<rest>,
    shows in R again (xs; R's code kept with it for a locked room) and keeps R/<rest> as a library alias (libAka: the hub
    rewrites every board naming it, pages their own grids and pins). -> (doc, note | None); `doc` is changed in place."""
    if not isinstance(doc, dict):
        return doc, None
    room = str(doc.get("room") or "").strip().lower()
    if not boxout_real_room(room) or not host:
        return doc, None
    home = home_room(host)
    now = int(time.time() if now is None else now)
    code = str(doc.get("roomCode") or "")
    listed = room != "main"   # (nothing is ever published in the Lobby -- nothing to list back there)
    moved = 0
    for rec in doc.get("feeds") or []:
        if not isinstance(rec, dict):
            continue
        if rec.get("room") and str(rec.get("room")) != room:
            continue   # a web client's camera in its own room (0.21.2)
        b = str(rec.get("broadcast") or "")
        if b.startswith(room + "/"):
            rec["broadcast"] = home + b[len(room):]
            if listed:
                aka = rec.get("libAka") if isinstance(rec.get("libAka"), dict) else {}
                aka.setdefault(b, now)
                rec["libAka"] = aka
            moved += 1
        rec.pop("room", None)
        if not listed:
            continue
        xs = [str(r) for r in (rec.get("xs") or []) if _XS_ROOM_RE.match(str(r)) and not is_home_room(r) and str(r) != room]
        if len(xs) >= XS_ROOMS_MAX:
            xs = xs[:XS_ROOMS_MAX - 1]
        rec["xs"] = xs + [room]
        if rec.get("xsAuto") == room:
            rec.pop("xsAuto", None)   # (the library's own listing-back becomes a kept one: R stays if the library goes)
        if code:
            codes = rec.get("xsCodes") if isinstance(rec.get("xsCodes"), dict) else {}
            codes.setdefault(room, code)
            rec["xsCodes"] = codes
    doc["room"] = home
    doc["roomCode"] = ""
    doc["boxout"] = {"from": room, "to": home, "at": now, "why": str(why or "box"), "feeds": moved}
    note = ("box-out: this %s left room %s for No room (%s) -- %d camera(s) moved, each still shown in %s"
            % ("relay machine" if why == "relay" else "camera box", room, home, moved, room if listed else "no room"))
    return doc, note


def _xs_fields(feed):
    """0.21.75: a feed's rooms (+ the codes of locked ones) for its rtsp-feeds.json record -- {} when it has none."""
    xs = getattr(feed, "xs", None)
    if not isinstance(xs, list) or not xs:
        return {}
    xs = [str(r) for r in xs]
    out = {"xs": xs}
    codes = getattr(feed, "xs_codes", None)
    codes = {r: str(c) for r, c in (codes if isinstance(codes, dict) else {}).items() if r in xs and c}
    if codes:
        out["xsCodes"] = codes
    gens = getattr(feed, "xs_gen", None)   # 0.21.91: the generation of each room it was accepted in (see kastr_relay xshare_gone)
    gens = {r: str(g) for r, g in (gens if isinstance(gens, dict) else {}).items() if r in xs and g}
    if gens:
        out["xsGen"] = gens
    return out

# ---- 0.21.84 (Kenton: "No-room box cameras join the library automatically on update, with the alias rewrite. New cameras added
# to a no-room box default to on." and "Boxes in a real room stay off by default; switching a camera on moves it to lib/ with
# the same alias rewrite, and the box lists it back into its own room."): the box side of the STREAM LIBRARY. A camera in the
# library publishes at lib/<host>/<op>/<leaf>.hang (the tail of its room path) on a library publisher token, and the box server
# heartbeats it to its relay (POST /api/library: every 60 s and at once when a camera starts / stops streaming; a 160x90 still
# every 5 minutes while it is live and on every state change). A camera moves only once its relay reports the library
# (/api/auth `library: 1` -- that relay's hub agrees); its old path rides the heartbeat as `aka` (the hub rewrites every room
# board naming it). kastr.ini `library = off` (or KASTR_LIBRARY=0) keeps this box out; `library_site` names its site.
LIBRARY_ENABLED = str(os.environ.get("KASTR_LIBRARY") or "on").strip().lower() not in ("0", "false", "no", "off")
LIBRARY_SITE = ""            # kastr.ini library_site: this box's own site name in the catalogue ("" = its relay's)
LIB_ROOT = "lib"
LIB_BEAT_S = 60              # every library camera is heartbeaten this often (the relay keeps a row LIB_TTL = 180 s)
LIB_BEAT_MIN_S = 10          # ... never more often (the relay refuses faster heartbeats; stops are never held back)
LIB_AIR_CHECK_S = 10         # how often the loop looks for a camera that started / stopped streaming
LIB_CAP_S = 60               # the relay's "library: 1" is asked again this often
LIB_STILL_EVERY_S = 300      # a still per live camera this often (and on each state change)
LIB_STILL_MAX = 12 * 1024
LIB_AKA_KEEP_S = 90 * 86400  # an old path rides the heartbeat this long
LIB_TOKEN_MIN_S = 600        # a cached library token is re-minted once it ends within this
LIB_STILL_VF = "scale=160:90:force_original_aspect_ratio=decrease,pad=160:90:(ow-iw)/2:(oh-ih)/2"
# ---- 0.21.85 (Kenton: "Publisher+relay boxes with shared streams should also show up under streams drop-down." He chose: every
# share of a KASTR app on a relay / hub machine is in the library AUTOMATICALLY; a person's own app gives each share an "In the
# stream library" switch, OFF by default): LISTED shares. A listed share stays in its room exactly as before (its room path, its
# tile, remote control, pointers -- nothing moves) and is ALSO published at lib/<host>/<op>/<leaf>.hang. A native share (this
# bridge's pairs: RTSP, a camera on this computer, a media file, an RTMP ingest, a screen / window) pumps its MPEG-TS to the
# room's moq AND to a second moq at the library path (LibMirror, a library publisher token): one capture, one encode, the
# upload only while someone watches it there. The page's own shares (a webcam, a browser screen, a media file, a grid) mirror
# inside the page (the vendored publish library's library-mirror patch) and hand their rows to this bridge (POST
# /api/rtsp/library {shares}). Every listed row rides this bridge's ONE heartbeat per relay (POST /api/library), beside the
# moved box cameras of 0.21.84 (a 0.21.84 relay takes them as they are). A share that stops is stopped in the library.
LIB_SHARE_TTL_S = 180         # a page's share row it has not repeated this long leaves the library (a closing page says so at once)
LIB_SHARE_MAX = 16            # page shares one page may list
LIB_SHARE_KINDS = ("webcam", "screen", "media", "grid", "camera", "other")
LIB_MIRROR_QMAX = 8 << 20     # bytes a library copy may fall behind the room's before it is restarted (at the next PAT)
LIB_MIRROR_RETRY_S = (2, 5, 10, 30, 60)
TS_PACKET = 188
_ANSI_RE = re.compile(chr(27) + r"\[[0-9;]*m")   # moq colours its log lines


def lib_share_kind(url):
    """0.21.85: the catalogue's kind of a LISTED native share."""
    return "screen" if is_screen(url) else lib_kind(url)


def _lib_mirror_of(pub):
    """0.21.85: a listed share's (lib path, library URL) -- what its pump publishes -- or None."""
    m = getattr(pub, "libMirror", None)
    return m if isinstance(m, tuple) and len(m) == 2 else None


def ts_pat_start(b, off):
    """0.21.85: where in this chunk of an MPEG-TS stream (its first byte is byte `off` of the stream) a library copy may start --
    the first 188-byte packet that begins a PAT (PID 0, payload start), so its moq reads the tables first. None = not in this
    chunk (ffmpeg repeats the PAT every 100 ms)."""
    i = (-int(off)) % TS_PACKET
    n = len(b)
    while i + 3 <= n:
        if b[i] == 0x47 and (b[i + 1] & 0x40) and ((b[i + 1] & 0x1F) << 8 | b[i + 2]) == 0:
            return i
        i += TS_PACKET
    return None


def lib_path_of(broadcast):
    """0.21.84: a camera's room path -> its library path (the same tail): <room>/<host>/<op>/<leaf>.hang -> lib/<host>/<op>/<leaf>.hang."""
    segs = str(broadcast or "").split("/")
    if len(segs) < 3 or not segs[-1].endswith(".hang"):
        return None
    return "/".join([LIB_ROOT] + segs[1:])


def is_lib(path):
    """0.21.84: a path in the stream library."""
    return str(path or "").startswith(LIB_ROOT + "/")


def lib_kind(url):
    """0.21.84: the catalogue's kind of a box feed."""
    u = str(url or "").lower()
    if is_device(u):
        return "camera"
    if is_hostmedia(u) or u.startswith(("http://", "https://")):
        return "media"
    return "rtsp"


def lib_state(pub, now=None):
    """0.21.84: what the catalogue says of a camera -- "asleep" (encodes only while watched, or on demand: a viewer's click wakes
    it), "live" (streaming), "dark" (switched off, or running against a camera that sends nothing)."""
    if getattr(pub, "suspended", False) or getattr(pub, "stopping", False):
        return "dark"
    if getattr(pub, "standby", False) and (getattr(pub, "sleepy", False) or getattr(pub, "ondemand", False)):
        return "asleep"
    return "live" if xs_on_air(pub, now) else "dark"


def _lib_fields(feed):
    """0.21.84: a feed's library switch, old paths and auto-listed room for its rtsp-feeds.json record -- {} when it has none."""
    out = {}
    v = getattr(feed, "lib", None)
    if v is not None:
        out["lib"] = bool(v)
    aka = getattr(feed, "lib_aka", None)
    if isinstance(aka, dict) and aka:
        out["libAka"] = {str(k): int(t) for k, t in aka.items()}
    if getattr(feed, "xs_auto", None):
        out["xsAuto"] = str(feed.xs_auto)
    v = getattr(feed, "lib_list", None)   # 0.21.85: a kept camera's "In the stream library" switch (never a screen's)
    if v is not None and not is_screen(getattr(feed, "url", "")):
        out["libList"] = bool(v)
    return out


def mint_library(relay_url, access, host, timeout=5):
    """0.21.84: a LIBRARY PUBLISHER token from the relay's minter (POST /api/token {library: true, code, host}) -> (status, url,
    detail) like mint_member: "token" (url carries ?jwt=), "off" (the library is switched off there), "refused", "down"."""
    parts, why = _relay_base(relay_url)
    if not parts:
        return "down", None, why
    base, minter = parts
    body = {"library": True, "code": str(access or ""), "host": str(host or "")}
    req = urllib.request.Request(minter + "/api/token", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:
            d = {}
        err = str(d.get("error") or "") if isinstance(d, dict) else ""
        if e.code == 403 and isinstance(d, dict) and d.get("library") == "off":
            return "off", None, err or "the stream library is switched off"
        if e.code in (400, 403):
            return "refused", None, err or "refused"
        return "down", None, "minter answered %d%s" % (e.code, (" (%s)" % err) if err else "")
    except Exception as e:
        return "down", None, str(e)
    tok = (d.get("tokens") or {}).get("member") if isinstance(d, dict) else None
    if not tok or not d.get("library"):
        return "down", None, "the minter answered without a library token (an older relay?)"
    return "token", base + ("" if base.endswith("/relay") else "/") + "?jwt=" + str(tok), str(d.get("role") or "publisher")


def relay_library(relay_url, timeout=3):
    """0.21.84: does this relay serve the stream library now (GET /api/auth `library`: 1 -- it and its hub run 0.21.84+, the fleet
    switch is on, no room is named "lib")? -> True / False / None (it did not answer)."""
    parts, _why = _relay_base(relay_url)
    if not parts:
        return None
    try:
        with urllib.request.urlopen(parts[1] + "/api/auth", timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return None
    return bool(isinstance(d, dict) and d.get("secured") and d.get("library") == 1)

# Longest a write to a stream reader may block. A browser that stops reading
# (frozen demuxer, wedged tab, abandoned socket) used to block wfile.write()
# forever, which blocked ffmpeg on pipe:1, which stopped the RTSP pull --
# ffmpeg's own -timeout is socket IO on the camera side and cannot fire while
# the child is stuck writing. This turns "reader went quiet" into an OSError,
# so the finally in handle_stream releases the child and /api/rtsp/list
# stops claiming a wedged feed is running.
SEND_TIMEOUT = 15.0

# Widest frame we hand to the browser untouched. Above this the browser
# spends more time scaling than encoding, so the bridge does it instead.
MAX_WIDTH = 1920

# Encoders to try for that downscale, best first. Hardware where available;
# libx264 is the floor and always exists. 0.9.6: h264_vaapi covers Intel/AMD
# iGPUs on Linux (probe-validated like the rest; needs the render node below).
ENCODERS = ("h264_qsv", "h264_nvenc", "h264_amf", "h264_mf", "h264_vaapi", "libx264")
# Per-encoder extras: args that must precede -i, and a filter suffix that
# uploads frames to the device. Empty for every software/CPU-fed encoder.
ENCODER_EXTRA = {
    "h264_vaapi": {"pre": ["-vaapi_device", "/dev/dri/renderD128"], "vf": ",format=nv12,hwupload"},
}


def encoder_pre_args(encoder):
    return list(ENCODER_EXTRA.get(encoder or "", {}).get("pre", []))


def encoder_vf(encoder, vf):
    return vf + ENCODER_EXTRA.get(encoder or "", {}).get("vf", "")


# 0.9.6: what viewers can decode straight from the camera -- the hang catalog
# and MPEG-TS both carry these, so copying is a zero-encode publish. The
# passthrough option lifts the H.264 size/range limits and admits H.265;
# without it H.264 copies as before (<= MAX_WIDTH, limited range) and
# everything else is encoded to H.264 once. MJPEG/MPEG-4 cameras can never be
# passed: no viewer decodes them.
PASSTHROUGH_CODECS = ("h264", "hevc", "h265")

# 0.9.6: the monitor feeds the owner's preview and the 15 fps mosaic. When it
# cannot copy, it encodes SMALL and FAST -- this used to be a second full-rate,
# full-size encode per camera, which is what saturated 4-core boxes with three
# feeds ("streams drop out and come back").
MONITOR_WIDTH = 1280
MONITOR_FPS = 15

# 0.9.8: square pixels before anything else. A camera whose SPS says SAR 2:1
# sends 960x1080 pixels meant to be shown 1920 wide; every consumer of a copied
# stream sized its picture from the coded 960 and squeezed it. Resample to the
# display width (a no-op for square pixels; an unset SAR counts as square),
# then declare 1:1 -- the rest of each chain sees an ordinary frame.
SQUARE_PIXELS = "scale=w='if(gt(sar,0),trunc(iw*sar/2)*2,iw)':h=ih,setsar=1"

# 0.9.6: container handed to moq-cli. "ts" (MPEG-TS, -pes_payload_size 0) or
# "fmp4" (fragmented MP4). Measured in the rig on 2026-09-16 -- see
# ARCHITECTURE "Load is a count of encodes, not a thread".
PUBLISH_MUX = "ts"


def passthrough_ok(vcodec, width, fullrange, passthrough, sar=None):
    """Copy or encode? The one rule both the publisher and the monitor use.

    0.9.8: a camera with non-square pixels (SAR != 1:1) is never copied. The
    catalog the viewer sizes its picture from carries the coded frame size,
    so a copied anamorphic stream shows squeezed on every viewer; one encode
    with setsar=1 gives it square pixels and the right shape."""
    if sar_nonsquare(sar):
        return False
    vc = (vcodec or "").lower()
    if vc not in PASSTHROUGH_CODECS:
        return False
    if passthrough:
        return True
    return vc == "h264" and (width or 0) <= MAX_WIDTH and not fullrange

def udp_copy_ok():
    """0.21.96: may a camera read over UDP be COPIED (passed through)? No, unless KASTR_RTSP_UDP_COPY=1. A lost RTP
    packet leaves a hole in the copied H.264/H.265 bitstream; Chrome's decoders do not conceal it -- the share page's
    <video> monitor stopped with a decode error every ~4 s at 5% loss, and a viewer's VideoDecoder threw 'Decoding
    error' until the next keyframe (the picture moved in 3 of 39 one-second samples). ffmpeg's decoder conceals the
    hole (VLC's does the same, which is why the camera looked fine there), so a UDP camera is decoded and encoded once
    on this machine. Costs one encode per UDP camera; KASTR_RTSP_UDP_COPY=1 copies anyway, for a link known clean."""
    return os.environ.get("KASTR_RTSP_UDP_COPY", "").strip() == "1"


def sar_nonsquare(sar):
    """(num, den) from the probe -> True when the pixels are not square."""
    try:
        a, b = int(sar[0]), int(sar[1])
    except (TypeError, ValueError, IndexError):
        return False
    return a > 0 and b > 0 and a != b


# 0.9.8: children die with KASTR. Publisher pairs (ffmpeg | moq) used to be
# plain children: a crash, a Task-Manager kill or close-kastr.ps1 left them
# publishing to the relay under this operator's paths, and the next KASTR saw
# its own cameras as a stranger's tiles it could not stop. Two layers:
#   * Windows: every child is assigned to one Job Object with
#     KILL_ON_JOB_CLOSE -- the OS ends them when this process ends, however it
#     ends. (KASTR_NO_JOB=1 disables it, to exercise the sweep.)
#   * Both platforms: every child is recorded in state_dir/rtsp-children-<pid>
#     .json and the next start reaps the recorded processes of a dead owner
#     -- matched by executable (and start time on Windows, argv on Linux), so
#     a reused PID is never someone else's process.
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x0800        # 0.16.0: a child may CREATE_BREAKAWAY_FROM_JOB (a relaunched KASTR must not die with the job)
JobObjectExtendedLimitInformation = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
STILL_ACTIVE = 259
_JOB_WARNED = [False]


def _k32():
    import ctypes
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _make_job(log=None):
    """A Job Object that kills its processes when the last handle closes (Windows)."""
    if sys.platform != "win32" or os.environ.get("KASTR_NO_JOB"):
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = _k32()
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)     # NULL name, non-inheritable handle
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
        if not k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                           ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
        return job
    except Exception as e:
        if log:
            log("rtsp: no job object for child processes (%s) -- relying on the startup sweep" % e)
        return None


_APP_JOB = [None, False]


def app_job(log=None):
    """The one job every KASTR child joins -- publishers, monitors and the
    relay (kastr_relay) alike. Created once per process; None where jobs are
    unavailable or disabled (KASTR_NO_JOB)."""
    if not _APP_JOB[1]:
        _APP_JOB[1] = True
        _APP_JOB[0] = _make_job(log)
    return _APP_JOB[0]


def _job_assign(job, proc, log=None):
    """Put one child into the job; a failure is logged once and tolerated."""
    if not job or proc is None:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        k32 = _k32()
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if not k32.AssignProcessToJobObject(job, wintypes.HANDLE(proc._handle)):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
        return True
    except Exception as e:
        if not _JOB_WARNED[0]:
            _JOB_WARNED[0] = True
            if log:
                log("rtsp: could not bind pid %s to the job (%s)" % (getattr(proc, "pid", "?"), e))
        return False


def _pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = _k32()
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            try:
                code = wintypes.DWORD()
                k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
                if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != STILL_ACTIVE:
                    return False
                return True
            finally:
                k32.CloseHandle.argtypes = [wintypes.HANDLE]
                k32.CloseHandle(h)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _pid_image(pid):
    """(executable path, creation epoch or None, argv list or None) of a live process."""
    pid = int(pid)
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = _k32()
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None, None, None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            exe = buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
            created = None
            ft = [wintypes.FILETIME() for _ in range(4)]
            k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            if k32.GetProcessTimes(h, *[ctypes.byref(f) for f in ft]):
                t = (ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime
                created = t / 1e7 - 11644473600.0
            return exe, created, None
        finally:
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.CloseHandle(h)
    exe = None
    try:
        exe = os.readlink("/proc/%d/exe" % pid).replace(" (deleted)", "")
    except OSError:
        pass
    argv = None
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
    except OSError:
        pass
    return exe, None, argv


def _same_file(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (TypeError, ValueError):
        return False


def _pid_matches(rec):
    """Is the recorded child still the process at that PID? (PID reuse guard.)"""
    pid = rec.get("pid")
    if not _pid_alive(pid):
        return False
    try:
        exe, created, argv = _pid_image(pid)
    except Exception:
        return False
    want = rec.get("exe") or ""
    if want:
        if not (exe and _same_file(exe, want)) and not (argv and _same_file(argv[0], want)):
            return False
    if created is not None and rec.get("started"):
        if abs(created - float(rec["started"])) > 5:
            return False
    sig = rec.get("sig") or []
    if argv is not None and sig:
        joined = " ".join(argv)
        digs = None
        for tok in sig:
            tok = str(tok)
            if tok.startswith("sha256:"):   # 0.21.92: a camera URL with a password is recorded as its digest
                if digs is None:
                    digs = {kastr_secret.digest(a) for a in argv}
                if tok not in digs:
                    return False
            elif tok not in joined:
                return False
    return True


def _kill_pid(pid):
    pid = int(pid)
    if sys.platform == "win32":
        try:
            from ctypes import wintypes
            k32 = _k32()
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if not h:
                return False
            try:
                k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
                return bool(k32.TerminateProcess(h, 1))
            finally:
                k32.CloseHandle.argtypes = [wintypes.HANDLE]
                k32.CloseHandle(h)
        except Exception:
            return False
    try:
        import signal
        os.kill(pid, signal.SIGKILL)
        return True
    except OSError:
        return False


# 0.9.10: sweep by what a helper IS, not by who wrote it down. The registry
# reaps what a 0.9.8+ run recorded; publisher pairs left by an older version
# (no job, no registry) and any orphaned monitor, probe or moq-relay were
# invisible to it. This lists every process running a bundled helper -- from a
# frozen extraction (`_MEIxxxx/bin`) or one of this install's helper folders --
# whose parent is no longer a live KASTR (or Python, for the dev harness).
HELPER_STEMS = ("ffmpeg", "moq", "moq-relay")


def helper_names():
    return tuple(n + (".exe" if sys.platform == "win32" else "") for n in HELPER_STEMS)


def helper_versions():
    """0.16.0: bin/.versions.json (fetch-helpers.py stamps what it fetched) -> dict."""
    for root in helper_roots():
        try:
            with open(os.path.join(root, ".versions.json"), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            continue
    return {}


def helper_roots():
    """Where bundled helpers live for THIS run (frozen extraction first)."""
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.join(sys._MEIPASS, "bin"))
    roots.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin"))
    return roots


def _processes():
    """[(pid, ppid, image basename)] for every process -- Toolhelp32 on Windows
    (no PowerShell spawn), /proc on Linux. Empty list when unavailable."""
    out = []
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = _k32()
            TH32CS_SNAPPROCESS = 0x2

            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                            ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
            k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
            k32.Process32FirstW.restype = wintypes.BOOL
            k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
            k32.Process32NextW.restype = wintypes.BOOL
            k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
            invalid = (1 << (8 * ctypes.sizeof(ctypes.c_void_p))) - 1
            snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if not snap or snap == invalid:
                return out
            try:
                e = PROCESSENTRY32W()
                e.dwSize = ctypes.sizeof(e)
                ok = k32.Process32FirstW(snap, ctypes.byref(e))
                while ok:
                    out.append((int(e.th32ProcessID), int(e.th32ParentProcessID), str(e.szExeFile)))
                    ok = k32.Process32NextW(snap, ctypes.byref(e))
            finally:
                k32.CloseHandle.argtypes = [wintypes.HANDLE]
                k32.CloseHandle(snap)
        except Exception:
            return out
        return out
    try:
        for fn in os.listdir("/proc"):
            if not fn.isdigit():
                continue
            pid = int(fn)
            try:
                with open("/proc/%d/stat" % pid, "r", encoding="utf-8", errors="replace") as f:
                    st = f.read()
                rest = st[st.rindex(")") + 2:].split()
                ppid = int(rest[1])
            except (OSError, ValueError, IndexError):
                continue
            try:
                name = os.path.basename(os.readlink("/proc/%d/exe" % pid).replace(" (deleted)", ""))
            except OSError:
                name = ""
            out.append((pid, ppid, name))
    except OSError:
        pass
    return out


def _is_helper_path(exe, own_dirs):
    """A bundled helper: under a `_MEI*/bin` folder, or in one of our helper dirs."""
    if not exe:
        return False
    parts = [p.lower() for p in re.split(r"[\\/]+", exe) if p]
    for i in range(len(parts) - 2):
        if parts[i].startswith("_mei") and parts[i + 1] == "bin":
            return True
    d = os.path.dirname(exe)
    return any(_same_file(d, o) for o in own_dirs if o)


def _kastr_like(image):
    n = (image or "").lower()
    return n.startswith("kastr") or n.startswith("python")


def helper_orphans(own_dirs=None, procs=None, image_of=None):
    """List-only: bundled helper processes whose parent is not a live KASTR/Python.
    Returns [{pid, ppid, name, exe, parent, why}]. `procs`/`image_of` are
    injectable for tests."""
    names = set(n.lower() for n in helper_names())
    own_dirs = list(own_dirs if own_dirs is not None else helper_roots())
    rows = _processes() if procs is None else procs
    by_pid = {pid: (ppid, name) for pid, ppid, name in rows}
    image_of = image_of or (lambda pid: _pid_image(pid)[0])
    me = os.getpid()
    out = []
    for pid, ppid, name in rows:
        if pid == me or ppid == me or (name or "").lower() not in names:
            continue
        try:
            exe = image_of(pid)
        except Exception:
            exe = None
        if not _is_helper_path(exe, own_dirs):
            continue
        parent = by_pid.get(ppid)
        if parent is None or not _pid_alive(ppid):
            why = "parent %d is gone" % ppid
        elif not _kastr_like(parent[1]):
            why = "parent %d is %s, not KASTR" % (ppid, parent[1] or "?")
        else:
            continue
        out.append({"pid": pid, "ppid": ppid, "name": name, "exe": exe,
                    "parent": parent[1] if parent else None, "why": why})
    return out


def registry_files(state_dir):
    """List-only view of the child registries in a state dir (for --diagnose)."""
    out = []
    if not state_dir or not os.path.isdir(state_dir):
        return out
    for fn in sorted(os.listdir(state_dir)):
        if fn.startswith("rtsp-children-") and fn.endswith(".json"):
            try:
                with open(os.path.join(state_dir, fn), encoding="utf-8") as f:
                    d = json.load(f)
                out.append("%s: owner %s%s, %d child(ren)" % (
                    fn, d.get("owner"), "" if _pid_alive(d.get("owner")) else " (dead)", len(d.get("children") or [])))
            except Exception as e:
                out.append("%s: unreadable (%s)" % (fn, e))
    return out


def _rtsp_leaf(url):
    """0.21.2: a broadcast leaf for a camera URL nobody named: host + last path segment (never credentials)."""
    try:
        from urllib.parse import urlsplit
        u = urlsplit(str(url or ""))
        seg = [s for s in u.path.split("/") if s]
        return "-".join(x for x in ((u.hostname or "").replace(".", "-"), seg[-1] if seg else "") if x) or "cam"
    except Exception:
        return "cam"


def _relay_key(url):
    """A relay URL without its room token: same relay, whatever the token says.
    0.13.3: nor is a trailing "/" a different relay -- mint_member returns
    `base + "/"`, the page posts without, and every adopt tore a healthy pair
    down on the mismatch (`reused` stuck at 0 was the tell)."""
    u = (url or "").strip()
    u = re.sub(r"([?&])jwt=[^&]*&?", r"\1", u)
    return u.rstrip("?&").rstrip("/").lower()


# ---- 0.12.0: tokens, redaction, the relay's minter --------------------------
def _relay_token(url):
    """The `jwt=` value of a relay URL, "" when it carries none."""
    m = re.search(r"[?&]jwt=([^&#]*)", url or "")
    return m.group(1) if m else ""


def _jwt_exp(tok):
    """The `exp` claim (int, seconds) of a JWT, None when absent or unreadable.
    Tolerant: no signature check, padding restored, any junk -> None."""
    try:
        body = str(tok or "").split(".")[1]
        d = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8", "replace"))
        exp = d.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


def _redact(text):
    """Log text with every `jwt=<token>` replaced -- moq never prints the token
    today, but the URL we hand it does carry one; nothing stored may."""
    return re.sub(r"jwt=[A-Za-z0-9._-]+", "jwt=<jwt>", text or "")


def _redact_url(u):
    """A camera URL for the page/log: `user:pass@` -> `***@`."""
    return re.sub(r"://([^/@]*)@", "://***@", u or "")


def _seed_label(broadcast, url):
    """0.14.0: the page's label for a kept feed (rtspPersistSet stores
    {url, label}). The broadcast is HOST/op/<slug(label)>: its leaf IS that
    slug. Without one, rtspLabel(url): last path segment minus a media
    extension, else the host, slugged."""
    leaf = (broadcast or "").strip().rsplit("/", 1)[-1]
    if leaf:
        return leaf
    try:
        rest = re.sub(r"^[a-z0-9+.-]+://", "", url or "")
        rest = rest.split("@", 1)[-1]
        host, _, path = rest.partition("/")
        seg = [p for p in path.split("?", 1)[0].split("/") if p]
        seg = re.sub(r"\.(mp4|webm|mkv|mov|avi|flv|m3u8|mpd|ts|mp3|aac|ogg)$", "", seg[-1], flags=re.I) if seg else ""
        base = seg or host.split(":", 1)[0]
        slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
        return slug or "rtsp"
    except Exception:
        return "rtsp"


# RE-MEASURED 2026-10-05 on moq CLI 0.14.0 + moq-relay 0.17.0 (secured): the same HARD ("connection loop exited
# err=unauthorized" / "Error: unauthorized", exit 1) and SOFT ("session closed, reconnecting") lines; 0.14.0 rides a
# 25 s outage by itself (keeps reconnecting) instead of exiting.
# What moq says about its relay session (moq CLI 0.11.2, measured 2026-09-19;
# RE-MEASURED 2026-09-25 on moq CLI 0.12.1 + moq-relay 0.15.1 with KASTR's auth
# server -- the same strings still fire: a refused token prints "Error: unauthorized"
# (HARD -> park -> re-mint, seen at first publish with a stale session token and
# again after `POST /api/relay/rotate`); a relay bounce prints "session closed,
# reconnecting peer=..." (SOFT, counted, the pair survives a 6 s bounce); a 25 s
# outage lets --backoff-timeout 10s expire and moq exits, which the pipe reports
# as ffmpeg exit 0xFFFFFFE0 (EPIPE) -> the ladder restarts, never parks).
# HARD: the relay refused the session -- a stale/invalid token, or moq's
# reconnect loop giving up (it exits 1 right after). Restarting with the same
# URL cannot help; only a fresh token can. SOFT: the session dropped and moq
# is reconnecting on its own (a relay bounce) -- counted, nothing to do.
HARD_RE = re.compile(r"unauthori[sz]ed|token (expired|invalid|does not grant)|code=6\b", re.I)
# 0.12.0: `reconnect timed out after` / `reconnect loop exited` are NOT hard on their own -- moq prints them
# for a plain relay outage too (measured: the dead-token exit line carries "unauthorized"); an outage must
# ladder, not park.
SOFT_RE = re.compile(r"session severed|session closed", re.I)


def _relay_base(relay_url):
    """-> (base 'scheme://host:port', minter 'http://host:port+1') or (None, why).
    0.19.0: a web relay -> ('https://name/relay', 'https://name') -- its web port
    carries the minter (proxied) and the media (WebSocket)."""
    u = (relay_url or "").strip()
    if not u:
        return None, "no relay url"
    try:
        import kastr_relay as _kr
        if _kr.is_web_relay(u):
            o = _kr.web_origin(u)
            return ((o + _kr.WEB_RELAY_PATH, o), None) if o else (None, "bad relay url")
    except ImportError:
        pass
    try:
        p = urlsplit(u if "://" in u else "http://" + u)
    except Exception as e:
        return None, "bad relay url: %s" % e
    host = p.hostname or ""
    if not host:
        return None, "relay url has no host"
    scheme = (p.scheme or "http").lower()
    scheme = {"ws": "http", "wss": "https"}.get(scheme, scheme)
    port = p.port or 4443
    h = ("[%s]" % host) if ":" in host else host
    return ("%s://%s:%d" % (scheme, h, port), "http://%s:%d" % (h, port + 1)), None


def mint_member(relay_url, room, access, room_code, timeout=5, host=None):
    """0.12.0: a member token for `room` from the relay's token service
    (relay-port+1) -> (status, url, detail), status in
        "open"    -- no minter, but the relay answers /certificate.sha256: the bare URL works
        "token"   -- url carries a fresh `?jwt=`; detail = the role minted
        "refused" -- wrong access or room code (retrying cannot help)
        "down"    -- unreachable, locked out (429) or an unexpected answer
    0.13.0: `host` (this machine's kastr_serve.host_slug) rides the body when
    given, so the minter scopes the puts to this host's own paths.
    urllib only; never raises."""
    parts, why = _relay_base(relay_url)
    if not parts:
        return "down", None, why
    base, minter = parts
    try:
        with urllib.request.urlopen(minter + "/api/auth", timeout=timeout) as r:
            auth = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except Exception as e:
        # no token service: an open relay has none at all -- is the relay itself up?
        try:
            probe = (minter + "/api/instance") if base.endswith("/relay") else (base + "/certificate.sha256")   # 0.19.0: a web relay
            with urllib.request.urlopen(probe, timeout=2) as r:
                r.read(128)
            return "open", base + ("" if base.endswith("/relay") else "/"), "no minter"
        except Exception as e2:
            return "down", None, "minter: %s; relay: %s" % (e, e2)
    if not isinstance(auth, dict) or not auth.get("secured"):
        return "open", base + ("" if base.endswith("/relay") else "/"), "relay is not secured"
    body = {"room": str(room or ""), "code": str(access or "")}
    if room_code:
        body["roomCode"] = str(room_code)
    if host:
        body["host"] = str(host)
    req = urllib.request.Request(minter + "/api/token", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        err = ""
        try:
            err = str(json.loads(e.read().decode("utf-8", "replace") or "{}").get("error") or "")
        except Exception:
            pass
        if e.code == 403:
            return "refused", None, err or "refused"
        if e.code == 429:
            return "down", None, "locked out" + ((" (%s)" % err) if err else "")
        return "down", None, "minter answered %d%s" % (e.code, (" (%s)" % err) if err else "")
    except Exception as e:
        return "down", None, str(e)
    tok = (d.get("tokens") or {}).get("member") if isinstance(d, dict) else None
    if not isinstance(d, dict) or not d.get("ok") or not tok:
        return "down", None, "minter answered without a token: %s" % ((d.get("error") if isinstance(d, dict) else None) or "?")
    return "token", base + ("" if base.endswith("/relay") else "/") + "?jwt=" + str(tok), str(d.get("role") or "member")   # 0.19.0: https://name/relay?jwt=


# URL paths that ARE the media -- handed to ffmpeg as-is. A page on a known
# video site is refused with a clear reason (0.9.3: the yt-dlp resolver was
# dropped -- a moving target in a 5 MB dependency the field never used); an
# unknown http(s) host still goes to ffmpeg verbatim, which handles HLS/DASH
# manifests and direct files.
MEDIA_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv",
              ".m3u8", ".mpd", ".ts", ".mp3", ".aac", ".ogg")
PAGE_SITES = ("youtube", "youtu.be", "vimeo", "twitch", "dailymotion")


# ---- 0.21.26 (Kenton: grids take "screen, window, tab, RTSP/HTTP, media file, etc"): HOST FEEDS --------------------
# A camera on THIS computer (device://video/<name>) or a media file uploaded to it (media://<32 hex id>) becomes a feed
# like an RTSP camera: published natively, in any grid, kept after a restart. A webcam opens only once, so the bridge
# captures it ONE time (DeviceCapture) and fans an H.264 MPEG-TS copy out over loopback UDP -- one port per reader
# (publisher, monitor, low copy). A media file is simply read by each reader, looped at real time.
DEVICE_PREFIX = "device://video/"
MEDIA_PREFIX = "media://"
HOSTMEDIA_DIR = [None]   # set by the Bridge: <state>/hostmedia (a copy of the upload that outlives the upload's own life)
DEVICES = {}             # url -> DeviceCapture
DEVICE_ROLES = ("pub", "mon", "low")
# 0.21.30 (field: a GoPro on RTMP ingest -> "bind failed: Error number -10048" = the monitor's port was already held):
# a port takes ONE reader, but a feed can have several monitors at once (a reconnect while the old one is still dying,
# the window and a web client of the same box) -- so the capture sends to MON_SLOTS monitor ports and each monitor
# claims a free one. Ports come from below every OS's ephemeral range, where outgoing sockets (QUIC, DNS) never land.
MON_SLOTS = 6
# 0.21.31: a loopback reader knows what the capture sends (MPEG-TS, H.264 + maybe AAC). ffmpeg's default 5 s stream
# analysis put every monitor's first byte at 5.1 s (measured), close to the page's 8 s no-bytes reconnect, and a window
# SHORTER than the source's keyframe spacing fails outright ("dimensions not set") -- so every capture sends a keyframe at
# least every 2 s (RTMP: every 1 s, re-encoded) and readers analyse for 3 s
LOOP_IN = ["-f", "mpegts", "-analyzeduration", "3000000", "-probesize", "5000000"]
RTMP_WIDTH, RTMP_BITRATE = 1920, "6M"
LOOP_PORTS = (20000, 31999)


def is_device(url):
    return str(url or "").startswith(DEVICE_PREFIX)


def is_hostmedia(url):
    return str(url or "").startswith(MEDIA_PREFIX)


# 0.21.29 (Kenton: "does a KASTR relay have an RTMP URL that I can point devices to, such as a go pro"): an RTMP INGEST --
# KASTR listens (ffmpeg -listen 1) on its own port per stream (one ffmpeg listener per port) for rtmp://<this host>:<port>/
# live/<key>; whatever a device pushes is fanned out like a host camera (copied, no re-encode) to the publisher, monitor
# and low copy. The key is random per stream, so nobody else can push into it.
RTMP_PREFIX = "rtmp-in://"
RTMP_PORTS = range(1935, 1945)


def is_rtmp_in(url):
    return str(url or "").startswith(RTMP_PREFIX)


def rtmp_parts(url):
    """rtmp-in://<port>/<key> -> (port, key) or (None, None)."""
    m = re.match(r"^rtmp-in://(\d{2,5})/([A-Za-z0-9]{6,40})$", str(url or ""))
    if not m or int(m.group(1)) not in RTMP_PORTS:
        return None, None
    return int(m.group(1)), m.group(2)


def rtmp_ports_in_use():
    return sorted({rtmp_parts(u)[0] for u in DEVICES if is_rtmp_in(u)} - {None})


def rtmp_free_port():
    """The first port of RTMP_PORTS no ingest uses and nothing else listens on (TCP)."""
    import socket
    used = set(rtmp_ports_in_use())
    for p in RTMP_PORTS:
        if p in used:
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return None


def is_host_feed(url):
    return is_device(url) or is_hostmedia(url) or is_rtmp_in(url)


def device_name(url):
    from urllib.parse import unquote
    return unquote(str(url)[len(DEVICE_PREFIX):]).strip()


def hostmedia_path(url):
    mid = str(url)[len(MEDIA_PREFIX):].strip().lower()
    d = HOSTMEDIA_DIR[0]
    if not re.match(r"^[0-9a-f]{32}$", mid) or not d or not os.path.isdir(d):
        return None
    for fn in sorted(os.listdir(d)):
        if fn.startswith(mid + ".") and re.match(r"^[0-9a-f]{32}\.[a-z0-9]{1,5}$", fn):
            return os.path.join(d, fn)
    return None


def list_devices(ffmpeg):
    """The cameras this computer can capture (ids for device://video/<id>): Windows = DirectShow video devices (by name),
    Linux = the V4L2 capture nodes (0.21.65: a stable /dev/v4l/by-id path when there is one)."""
    return [c["id"] for c in list_cameras(ffmpeg)[0] if not c.get("error")]


def _dshow_names(stderr):
    """0.21.65: the video device names of `ffmpeg -list_devices true -f dshow` -- both output styles (a `(video)` tag per
    line, or the older 'DirectShow video devices' section). Two cameras with the same name (two identical webcams) are
    told apart as "<name> #2", "#3" ... (DeviceCapture opens them with -video_device_number)."""
    out, section = [], None
    for line in (stderr or "").splitlines():
        if "DirectShow video devices" in line:
            section = "video"
            continue
        if "DirectShow audio devices" in line:
            section = "audio"
            continue
        if "Alternative name" in line:
            continue
        m = re.search(r'"([^"]+)"\s*\((video|audio|none)\)', line)
        if m:
            if m.group(2) != "video":
                continue
            name = m.group(1)
        else:
            m = re.search(r'\]\s+"([^"]+)"\s*$', line)
            if not m or section != "video":
                continue
            name = m.group(1)
        n, label = 1, name
        while label in out:
            n += 1
            label = "%s #%d" % (name, n)
        out.append(label)
    return out


DSHOW_DUP_RE = re.compile(r"^(.*) #(\d{1,2})$")
V4L2_CAP_DEVICE_CAPS = 0x80000000
V4L2_CAP_CAPTURE = 0x00000001 | 0x00001000   # VIDEO_CAPTURE | VIDEO_CAPTURE_MPLANE


def _v4l2_caps(path):
    """-> is this node a video CAPTURE node? VIDIOC_QUERYCAP; a UVC camera's second node (metadata) is not one."""
    import fcntl
    import struct
    fd = os.open(path, os.O_RDWR | getattr(os, "O_NONBLOCK", 0))
    try:
        buf = bytearray(104)
        fcntl.ioctl(fd, 0x80685600, buf, True)   # VIDIOC_QUERYCAP
        caps, dcaps = struct.unpack_from("<II", buf, 84)
        if caps & V4L2_CAP_DEVICE_CAPS:
            caps = dcaps
        return bool(caps & V4L2_CAP_CAPTURE)
    finally:
        os.close(fd)


def _linux_cameras(dev_dir="/dev", sys_dir="/sys/class/video4linux", caps=None):
    """0.21.65 (Kenton, Logan-ROC: a webcam that never showed in the share menu): every V4L2 node that CAPTURES video, named
    from sysfs (the camera's own name, not "video0"), addressed by its /dev/v4l/by-id link when one exists (survives a
    re-plug or a reboot that renumbers the nodes). A node KASTR may not open says why (most often: the user is not in the
    `video` group). -> (rows, note)."""
    import glob
    caps = caps or _v4l2_caps
    nodes = sorted(glob.glob(os.path.join(dev_dir, "video*")), key=lambda p: (len(p), p))
    if not nodes:
        return [], "No camera on this computer (no %s/video* device)." % dev_dir
    byid = {}
    for link in sorted(glob.glob(os.path.join(dev_dir, "v4l", "by-id", "*"))):
        try:
            byid.setdefault(os.path.realpath(link), link)
        except OSError:
            pass
    rows, denied, seen_names = [], 0, {}
    for node in nodes:
        base = os.path.basename(node)
        name = ""
        try:
            with open(os.path.join(sys_dir, base, "name"), encoding="utf-8", errors="replace") as f:
                name = f.read().strip()
        except OSError:
            pass
        try:
            with open(os.path.join(sys_dir, base, "index"), encoding="utf-8") as f:
                idx = f.read().strip()
        except OSError:
            idx = ""
        err = ""
        try:
            if not caps(node):
                continue   # a metadata / output node
        except PermissionError:
            if idx not in ("", "0"):
                continue   # an extra node of a camera whose node 0 is listed
            err = "KASTR may not open %s -- add this user to the 'video' group (sudo usermod -aG video $USER), then log in again" % node
            denied += 1
        except OSError as e:
            if idx not in ("", "0"):
                continue
            err = "%s could not be opened (%s)" % (node, getattr(e, "strerror", None) or e)
        real = os.path.realpath(node)
        cid = byid.get(real) or node
        label = name or base
        n = seen_names.get(label, 0) + 1
        seen_names[label] = n
        if n > 1:
            label = "%s #%d" % (label, n)
        row = {"id": cid, "name": label, "node": node}
        if err:
            row["error"] = err
        rows.append(row)
    note = ""
    if not rows:
        note = "No camera that captures video on this computer (%d video device%s found, none of them a camera)." % (len(nodes), "" if len(nodes) == 1 else "s")
    elif denied and denied == len(rows):
        note = "Cameras were found but KASTR may not open them: add this user to the 'video' group and log in again."
    return rows, note


def list_cameras(ffmpeg):
    """0.21.65: ([{id, name, error?}], note) -- what the Share panel's Webcam section lists."""
    if sys.platform.startswith("win"):
        if not ffmpeg:
            return [], "ffmpeg is missing, so KASTR cannot list this computer's cameras."
        try:
            r = subprocess.run([ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                               capture_output=True, text=True, errors="replace", timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            names = _dshow_names(r.stderr)
        except Exception as e:
            return [], "Could not list the cameras (%s)." % e
        return [{"id": n, "name": n} for n in names], ("" if names else "No camera found on this computer.")
    if sys.platform.startswith("linux"):
        try:
            return _linux_cameras()
        except Exception as e:
            return [], "Could not list the cameras (%s)." % e
    return [], "Sharing a webcam as a shared camera works on Windows and Linux (on a Mac, use the camera button on the toolbar)."


def _udp_free(port):
    """0.21.30: can a reader bind this loopback port right now?"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _free_udp_port(avoid=()):
    """0.21.30: a free loopback UDP port OUTSIDE the ephemeral ranges (Windows 49152+, Linux 32768+) -- an ephemeral
    port can be handed to any outgoing socket between our pick and the reader's bind."""
    import random
    import socket
    for _ in range(200):
        p = random.randint(LOOP_PORTS[0], LOOP_PORTS[1])
        if p not in avoid and _udp_free(p):
            return p
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


class DeviceCapture:
    """One ffmpeg owns the camera; H.264 (baseline, 2 s GOP, <= 1280 wide) goes out to one loopback UDP port per
    reader. Restarted with a back-off when it exits; stopped with the feed."""

    def __init__(self, ffmpeg, url, log=None):
        self.ffmpeg, self.url, self.log = ffmpeg, url, (log or (lambda m: None))
        self.ports = {}
        for r in DEVICE_ROLES:
            self.ports[r] = _free_udp_port(avoid=set(self.ports.values()))
        self.mon_ports = [self.ports["mon"]]   # 0.21.30: monitor slot 0 is ports["mon"]
        while len(self.mon_ports) < MON_SLOTS:
            self.mon_ports.append(_free_udp_port(avoid=set(self.ports.values()) | set(self.mon_ports)))
        self.claims = {}                       # 0.21.30: monitor port -> its ffmpeg (or the time it was handed out)
        self._claim_lock = threading.Lock()
        self.proc = None
        self.stopped = False
        self.restarts = 0
        self.last_error = ""
        self.connected_at = None   # 0.21.31: an RTMP device is pushing (ffmpeg named its input); None while it only listens
        self.last_end_at = None
        self.pushes = 0

    def args(self):
        if is_rtmp_in(self.url):   # 0.21.29: wait for a device to push, copy what it sends (video + audio) to every reader
            port, key = rtmp_parts(self.url)
            tee = self._tee()
            # 0.21.31: -loglevel info so the "Input #0, flv" line says the moment a device starts pushing
            return [self.ffmpeg, "-hide_banner", "-nostats", "-loglevel", "info", "-f", "flv", "-listen", "1",
                    "-i", "rtmp://0.0.0.0:%d/live/%s" % (port, key), "-map", "0:v:0", "-map", "0:a:0?",
                    # 0.21.31 (field: a GoPro 'Live' but "no video from the bridge"): re-encoded ONCE here with a keyframe
                    # every second -- a copied device stream starts every reader (preview, publisher, late viewers) at the
                    # device's own keyframe spacing, and a reader that analyses past it fails with "dimensions not set"
                    "-vf", "scale=w='min(iw,%d)':h=-2,format=yuv420p" % RTMP_WIDTH, "-c:v", "libx264", "-preset", "veryfast",
                    "-tune", "zerolatency", "-profile:v", "baseline", "-bf", "0", "-force_key_frames", "expr:gte(t,n_forced*1)",
                    "-b:v", RTMP_BITRATE, "-maxrate", RTMP_BITRATE, "-bufsize", RTMP_BITRATE, "-c:a", "copy",
                    "-f", "tee", tee]
        name = device_name(self.url)
        if name == "kastr-test":   # rig: a test pattern stands in for a camera
            src = ["-re", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30"]
        elif sys.platform.startswith("win"):
            m = DSHOW_DUP_RE.match(name)   # 0.21.65: the 2nd / 3rd camera of the same name
            if m and int(m.group(2)) >= 2:
                src = ["-f", "dshow", "-rtbufsize", "128M", "-video_device_number", str(int(m.group(2)) - 1), "-i", "video=" + m.group(1)]
            else:
                src = ["-f", "dshow", "-rtbufsize", "128M", "-i", "video=" + name]
        else:
            src = ["-f", "v4l2", "-i", name]
        tee = self._tee()
        return ([self.ffmpeg, "-hide_banner", "-loglevel", "error"] + src
                + ["-an", "-vf", "scale=w='min(iw,1280)':h=-2,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                   "-tune", "zerolatency", "-profile:v", "baseline", "-g", "60", "-bf", "0", "-b:v", "3M", "-maxrate", "3M",
                   "-bufsize", "3M", "-map", "0:v:0", "-f", "tee", tee])

    def out_ports(self):
        """Every loopback port the capture sends to: publisher, low copy, then the monitor slots."""
        return [self.ports["pub"], self.ports["low"]] + list(self.mon_ports)

    def _tee(self):
        # an unbound loopback port is the normal case (no reader yet) -- UDP sends to it never fail
        return "|".join("[f=mpegts]udp://127.0.0.1:%d?pkt_size=1316" % p for p in self.out_ports())

    def claim_mon(self):
        """0.21.30: a monitor port nobody reads -- its last ffmpeg has exited and the port binds. None when all are busy."""
        now = time.time()
        with self._claim_lock:
            for p in self.mon_ports:
                h = self.claims.get(p)
                if isinstance(h, float) and now - h < 15:
                    continue                                   # handed out, its ffmpeg is starting
                if h is not None and not isinstance(h, float) and h.poll() is None:
                    continue                                   # a running monitor reads it
                if not _udp_free(p):
                    continue                                   # something else holds it (a dying reader)
                self.claims[p] = now
                return p
        return None

    def attach(self, port, proc):
        with self._claim_lock:
            self.claims[port] = proc

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        wait = 1.0
        while not self.stopped:
            t0 = time.time()
            try:
                self.proc = subprocess.Popen(self.args(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                             errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    _job_assign(app_job(self.log), self.proc, self.log)   # 0.21.61: an RTMP listener held its port past an update
                except Exception:
                    pass
                tail = []
                for line in (self.proc.stderr or ()):   # 0.21.31: line by line -- a device connecting is news now, not at exit
                    line = line.rstrip()
                    if not line:
                        continue
                    if is_rtmp_in(self.url) and self.connected_at is None and line.startswith("Input #0"):
                        self.connected_at = time.time()
                        self.pushes += 1
                        self.log("rtsp: RTMP ingest on port %s -- a device is pushing" % rtmp_parts(self.url)[0])
                    if re.search(r"error|failed|invalid|refused|denied", line, re.I):
                        tail = (tail + [line])[-3:]
                self.proc.wait()
                self.last_error = " / ".join(tail)[-300:]
            except Exception as e:
                self.last_error = str(e)[:300]
            if self.connected_at is not None:
                self.last_end_at = time.time()
            self.connected_at = None
            if self.stopped:
                return
            self.restarts += 1
            if is_rtmp_in(self.url):   # 0.21.29: the device stopped pushing (or never came) -- listen again at once
                self.log("rtsp: RTMP ingest on port %s ended (%s) -- listening again" % (rtmp_parts(self.url)[0], self.last_error or "the device disconnected"))
                time.sleep(1.0)
                continue
            self.log("rtsp: camera capture %s ended (%s) -- again in %.0f s" % (device_name(self.url), self.last_error or "no reason given", wait))
            wait = 1.0 if time.time() - t0 > 60 else min(30.0, wait * 2)
            time.sleep(wait)

    def stop(self):
        self.stopped = True
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass


# ---- 0.21.96: RTSP transport (Auto / TCP / UDP) and the loss the demuxer reports --------------------------------------
# A camera that plays in VLC (RTP over UDP) but refuses RTP over TCP (461 Unsupported Transport) showed "no video from the
# bridge" forever: every reader forced -rtsp_transport tcp. Each rtsp:// camera now has a Transport: Auto (TCP first; when
# TCP gives no picture and UDP does, UDP for the rest of the run), TCP (as before) or UDP. rtsps:// stays TCP (TLS rides
# the TCP connection). Every reader of the camera -- probe, native pair + low copy, monitors, library stills -- uses the
# feed's effective transport (feed_transport), passed to input_args(transport=).
TRANSPORTS = ("auto", "tcp", "udp")
UDP_BUFFER = 4 * 1024 * 1024   # the RTSP demuxer's UDP receive buffer: a 4K I-frame burst outruns the OS default
AUTO_PICKS = {}                # url -> {"transport": "udp", "why": ..., "at": ...} -- Auto's pick, kept for the run
LOSS_WINDOW_S = 60
RTSP_LOGLEVEL = "level+warning"   # rtsp readers: level-tagged lines; the demuxer's loss lines are WARNINGs (unseen at "error")
REFUSE_RE = re.compile(r"SETUP failed: *461|Unsupported Transport|Nonmatching transport|unsupported lower transport", re.I)
LEVEL_RE = re.compile(r"^((?:\[[^\]]*\] )*?)\[(trace|debug|verbose|info|warning|error|fatal|panic)\] ?")
REPEAT_RE = re.compile(r"Last message repeated (\d+) times?")
KEEP_WARN_RE = re.compile(r"Failed reading RTSP data|Could not find codec parameters|method \w+ failed", re.I)   # warnings that say why
LOSS_PATTERNS = (
    (re.compile(r"RTP: missed (\d+) packets?"), "missed"),
    (re.compile(r"max delay reached|dropping old packet received too late", re.I), "late"),
    (re.compile(r"bad cseq", re.I), "badseq"),
    (re.compile(r"Received packet without a start (?:chunk|code)|dropping frame|RTP/JPEG.*(?:Invalid|Too short)", re.I), "frames"),
    (re.compile(r"error while decoding MB|concealing \d+ DC, \d+ AC, \d+ MV errors|non-existing PPS|no frame!|corrupt (?:decoded )?frame"
                r"|left block unavailable|top block unavailable|negative number of zero coeffs|out of range intra chroma pred mode"
                r"|cbp too large|mb_type \d+ in [IPB] slice too large|Missing reference picture|reference picture missing"
                r"|illegal short term buffer|co located POCs unavailable|mmco: unref short failure", re.I), "decode"),
)
LOSS_KINDS = ("missed", "late", "badseq", "frames", "decode")
# 0.21.96: any error from the video DECODER of a UDP reader is the loss showing through (ffmpeg names dozens of ways an
# H.264 slice can be broken -- "corrupted macroblock", "Slice overlaps with next" ...): counted as decode, never the error
DECODER_CTX_RE = re.compile(r"^\[(?:h264|hevc|mjpeg|vist#[^\]]*/(?:h264|hevc|mjpeg)) @ ", re.I)


def is_rtsp_url(url):
    return str(url or "").strip().lower().startswith(("rtsp://", "rtsps://"))


def transport_mode(feed):
    """The operator's choice for this camera: "auto" (the default), "tcp" or "udp"."""
    m = str(getattr(feed, "transport", None) or "auto").strip().lower()
    return m if m in TRANSPORTS else "auto"


def feed_transport(feed):
    """What this feed's readers use right now: "tcp" | "udp", or None (not an RTSP camera -- devices, RTMP ingests,
    screens, files, http(s) and the test pattern are untouched). rtsps:// is TCP whatever the choice."""
    url = str(getattr(feed, "url", "") or "").strip()
    low = url.lower()
    if low.startswith("rtsps://"):
        return "tcp"
    if not low.startswith("rtsp://"):
        return None
    mode = transport_mode(feed)
    if mode != "auto":
        return mode
    pick = AUTO_PICKS.get(url)
    return (pick or {}).get("transport") or "tcp"


def probe_ok(r):
    """A probe that found a picture: a video stream with its frame size (a silent camera names the codec from the SDP
    but never a size -- "Could not find codec parameters ... unspecified size")."""
    return bool(r) and bool(r.get("vcodec")) and bool(r.get("width"))


def auto_choice(tcp, udp=None):
    """Auto's decision from the probes: "tcp" (TCP gives a picture -- or neither does, and TCP stays, as before),
    "try-udp" (TCP gave none and UDP was not asked yet), "udp" (UDP gives the picture TCP did not)."""
    if probe_ok(tcp):
        return "tcp"
    if udp is None:
        return "try-udp"
    return "udp" if probe_ok(udp) else "tcp"


def auto_why(tcp_probe):
    return "the camera refused TCP" if (tcp_probe or {}).get("refused") else "TCP gave no picture"


def udp_args():
    """RTP over UDP: a bigger receive buffer, and optional fixed client ports (KASTR_RTSP_UDP_PORTS=40000-40999) for a
    firewall that opens ports rather than programs. -timeout (added after) still ends a silent camera."""
    args = ["-rtsp_transport", "udp", "-buffer_size", str(UDP_BUFFER)]
    rng = re.match(r"^\s*(\d{4,5})\s*-\s*(\d{4,5})\s*$", os.environ.get("KASTR_RTSP_UDP_PORTS", "") or "")
    if rng and 1024 <= int(rng.group(1)) < int(rng.group(2)) <= 65535:
        args += ["-min_port", rng.group(1), "-max_port", rng.group(2)]
    return args


def split_level(text):
    """'[in#0/rtsp @ 0x..] [warning] RTP: missed 3 packets' -> ('warning', '[in#0/rtsp @ 0x..] RTP: missed 3 packets');
    a line without a level tag -> (None, text)."""
    m = LEVEL_RE.match(text or "")
    if not m:
        return None, text
    return m.group(2), m.group(1) + text[m.end():]


def parse_loss_line(text):
    """-> (kind, n) for a line that reports loss (kinds: LOSS_KINDS), else None."""
    for rx, kind in LOSS_PATTERNS:
        m = rx.search(text or "")
        if m:
            return kind, (int(m.group(1)) if kind == "missed" else 1)
    return None


class LossMeter:
    """What the RTSP demuxer said it lost, per reader: "pub" (the native pair), "low" (its thumbnail copy) and "mon"
    (the page's monitor) each pull their own copy of the stream, so each loses on its own. Totals since `since` plus
    the last LOSS_WINDOW_S seconds (one bucket per second and kind)."""

    def __init__(self, now=None):
        self._lock = threading.Lock()
        self.since = now or time.time()
        self.lastAt = None
        self._r = {}       # reader -> {"total": {kind: n}, "ev": [[sec, kind, n], ...]}
        self._last = {}    # reader -> (kind, n) of its previous line ("Last message repeated N times" repeats it)

    def touch(self, reader):
        with self._lock:
            self._slot(reader)

    def _slot(self, reader):
        d = self._r.get(reader)
        if d is None:
            d = self._r[reader] = {"total": {k: 0 for k in LOSS_KINDS}, "ev": []}
        return d

    def add(self, reader, kind, n=1, now=None):
        if kind not in LOSS_KINDS or n <= 0:
            return
        now = now or time.time()
        sec = int(now)
        with self._lock:
            d = self._slot(reader)
            d["total"][kind] += n
            ev = d["ev"]
            if ev and ev[-1][0] == sec and ev[-1][1] == kind:
                ev[-1][2] += n
            else:
                ev.append([sec, kind, n])
                if len(ev) > 4 * LOSS_WINDOW_S * len(LOSS_KINDS):
                    del ev[:len(ev) - 4 * LOSS_WINDOW_S * len(LOSS_KINDS)]
            self.lastAt = now

    def line(self, reader, text, now=None):
        """Count one ffmpeg line (level tag already split off). -> the kind counted, or None (not a loss line)."""
        hit = parse_loss_line(text)
        if hit is None:
            m = REPEAT_RE.search(text or "")
            last = self._last.get(reader)
            if m and last:
                self.add(reader, last[0], last[1] * int(m.group(1)), now)
                return last[0]
            self._last[reader] = None
            return None
        self._last[reader] = hit
        self.add(reader, hit[0], hit[1], now)
        return hit[0]

    def info(self, now=None):
        now = now or time.time()
        per = {}
        with self._lock:
            for reader, d in self._r.items():
                d["ev"] = [e for e in d["ev"] if e[0] > now - LOSS_WINDOW_S]
                minute = {k: 0 for k in LOSS_KINDS}
                for _sec, kind, n in d["ev"]:
                    minute[kind] += n
                per[reader] = {"total": dict(d["total"]), "minute": minute}
        head = next((r for r in ("pub", "mon", "low") if r in per), None)
        out = {"reader": head, "since": self.since, "lastAt": self.lastAt, "window": LOSS_WINDOW_S, "readers": per}
        for k in LOSS_KINDS:
            out[k] = per[head]["total"][k] if head else 0
            out[k + "60"] = per[head]["minute"][k] if head else 0
        return out


def rtsp_line(feed, reader, transport, text, bridge=None):
    """One level-tagged line from an rtsp:// reader -> the text to keep as the reader's error (tag removed, as it read
    before), or None: a loss line is counted on feed.loss and kept out of the error tail (it would push the real reason
    out), and other warnings stay unseen, as they were at -loglevel error. A refused SETUP is noted on the feed; under
    Auto on TCP it drops the cached TCP probe so the next start asks again (and tries UDP)."""
    lvl, body = split_level(text)
    if REFUSE_RE.search(body):
        if transport in ("tcp", "udp"):
            setattr(feed, transport + "_refused", time.time())
            if transport == "tcp" and transport_mode(feed) == "auto" and bridge is not None:
                getattr(bridge, "_probed", {}).pop((getattr(feed, "url", None), "tcp"), None)
                feed.h264 = None
        return body
    loss = getattr(feed, "loss", None)
    if loss is not None and loss.line(reader, body):
        return None
    if loss is not None and transport == "udp" and lvl == "error" and DECODER_CTX_RE.match(body):
        loss.add(reader, "decode", 1)
        loss._last[reader] = ("decode", 1)   # a following "Last message repeated N times" counts too
        return None
    if lvl in (None, "error", "fatal", "panic") or KEEP_WARN_RE.search(body):
        return body
    return None


def transport_info(feed):
    """Feed.info()'s transport fields (None for anything that is not an RTSP camera)."""
    url = str(getattr(feed, "url", "") or "")
    if not is_rtsp_url(url):
        return {"transport": None, "transportNow": None, "transportWhy": None,
                "tcpRefused": None, "udpRefused": None, "loss": None}
    mode = transport_mode(feed)
    pick = AUTO_PICKS.get(url.strip()) if mode == "auto" else None
    secure = url.strip().lower().startswith("rtsps://")
    loss = getattr(feed, "loss", None)
    return {"transport": mode, "transportNow": feed_transport(feed),
            "transportWhy": ("rtsps:// always uses TCP" if secure else (pick or {}).get("why")),
            "tcpRefused": getattr(feed, "tcp_refused", None), "udpRefused": getattr(feed, "udp_refused", None),
            "loss": loss.info() if loss is not None else None}


def input_args(url, role="pub", claim=None, screen_opts=None, transport=None):
    if is_device(url) or is_rtmp_in(url):   # 0.21.26: the bridge's one capture of this camera, on this reader's own loopback port; 0.21.29: + RTMP ingest
        cap = DEVICES.get(url)
        if cap and role == "mon":   # 0.21.30: a free monitor slot (several monitors may read one capture)
            port = cap.claim_mon()
            if port is None:
                raise RuntimeError("every monitor of this camera is in use (%d) -- close one and try again" % len(cap.mon_ports))
            if claim is not None:
                claim["port"] = port
            return LOOP_IN + ["-i", "udp://127.0.0.1:%d?fifo_size=1000000&overrun_nonfatal=1" % port]
        port = cap.ports.get(role if role in DEVICE_ROLES else "pub") if cap else 0
        if port:   # 0.21.30: the previous reader of this port may still be dying -- give it up to 3 s
            for _ in range(30):
                if _udp_free(port):
                    break
                time.sleep(0.1)
        return LOOP_IN + ["-i", "udp://127.0.0.1:%d?fifo_size=1000000&overrun_nonfatal=1" % port]
    if is_hostmedia(url):   # 0.21.26: a media file on this host, looped at real time
        return ["-re", "-stream_loop", "-1", "-i", hostmedia_path(url) or "missing-media-file"]
    if is_screen(url):   # 0.21.20: Windows Graphics Capture, scaled on the GPU side of the capture, constant 30 fps
        import kastr_screen
        return kastr_screen.capture_input(url, **(screen_opts or {}))   # 0.21.80: + cursor / fps while remote-controlled
    if url == TEST_URL:
        return [
            "-re",                                  # emit at real time, not as fast as possible
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
        ]
    low = url.strip().lower()
    if low.startswith(("http://", "https://")):
        # Media over HTTP(S): a direct file or an HLS/DASH manifest. None of
        # the rtsp knobs apply -- and neither
        # -re nor reconnect belongs on a static file: reconnect restarts
        # fought the demuxer's Range seeks (NAL corruption, observed live),
        # and pacing is pointless because the <video> element plays the
        # timestamped output at 1x no matter how fast it arrives. Live
        # manifests keep reconnects for flaky sources; they pace themselves.
        live = low.split("?", 1)[0].endswith((".m3u8", ".mpd"))
        args = []
        if live:
            args += ["-reconnect", "1", "-reconnect_streamed", "1",
                     "-reconnect_delay_max", "5"]
        args += ["-i", url]
        return args
    secure = url.strip().lower().startswith("rtsps://")

    args = [
        # tcp because UDP loses fragments on most corp networks. This is also
        # correct for rtsps: "tls" is NOT a valid value here -- ffmpeg rejects
        # it outright -- the scheme alone tells ffmpeg to wrap the connection.
        "-rtsp_transport", "tcp",
    ]
    if transport == "udp" and low.startswith("rtsp://"):   # 0.21.96: the camera's Transport (never rtsps -- TLS needs TCP)
        args = udp_args()

    if secure:
        # The actual reason rtsps failed: ffmpeg reported
        #   "Peer certificate failed verification"
        # Cameras like UniFi Protect present a self-signed certificate on
        # their rtsps port, and nothing could validate an IP address on a
        # local network anyway. So verification is off by necessity: the
        # stream is still encrypted in transit, the camera is not authenticated.
        args += ["-tls_verify", "0"]

    args += [
        # Fail in ten seconds rather than blocking on connect forever. Without
        # this an unreachable camera produces no bytes AND no stderr, so the
        # page cannot tell "still starting up" from "never coming".
        "-timeout", "10000000",   # 0.13.2: NOT -rw_timeout -- the RTSP demuxer rejects it ("Option rw_timeout not found"), 0.13.1 killed every camera pair with it     # microseconds
        # 0.13.1: -timeout covers the connect; a camera that stops sending
        # mid-stream (rtsp over tcp) needs the read/write timeout too, or the
        # pair hangs silent until the QUIC side notices nothing arrives.
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        # Untouched, so a query string such as ?enableSrtp survives.
        "-i", url,
    ]
    return args


def output_args(url, copy_video, encoder=None, width=None, hvc1=False):
    """Args after the input, for the MONITOR stream (fragmented MP4 to pipe:1).

    copy_video repackages without touching the video (`hvc1` tags an H.265
    copy so the <video> element accepts the fMP4). Otherwise `encoder` says
    how to re-encode it -- 0.9.6: capped at MONITOR_WIDTH and MONITOR_FPS with
    the fastest preset, because this picture only feeds a preview and the
    15 fps mosaic. `width`, when given, sets the cap instead: below
    MONITOR_WIDTH for any source, up to 1920 for a screen source (0.21.20:
    presenter mode passes width=1920 because it composites this picture).
    """
    args = []

    if url != TEST_URL:
        # Video ONLY, deliberately. Bisected on a real camera: with its audio
        # muxed in, the browser's element capture delivers video at ~1 fps;
        # strip the audio and the same stream captures at the full ~30 fps.
        # Resampling did not help (48 kHz was just as slow), so the audio
        # track itself is what throttles capture. Nothing is lost: this stream
        # is the mosaic's source and the local monitor; the camera's audio
        # rides the native publisher's own path (0.9.1) unless the operator
        # turns it off for that feed (0.9.5).
        args += ["-map", "0:v:0"]

    if copy_video:
        # The camera already sends something the <video> element decodes, so
        # repackage rather than re-encode. This is the difference between
        # keeping up with a live feed and falling behind it.
        args += ["-c:v", "copy"]
        if hvc1:
            args += ["-tag:v", "hvc1"]   # 0.9.6: H.265 in fMP4 needs the hvc1 brand for Chrome
    else:
        # -2 keeps the aspect ratio and an even height, which yuv420p requires.
        # out_range=tv is the part that matters: a full-range camera produces
        # frames the browser's H.264 encoder rejects outright, and format=
        # yuv420p alone does NOT convert the range -- it only renames the
        # format. Without this the encoder throws "Encoding error", the
        # library rebuilds it, and viewers get RESET_STREAM and a black frame.
        # 0.9.6: never wider than MONITOR_WIDTH (the mosaic is 720 rows).
        cap = min(int(width), 1920 if is_screen(url) else MONITOR_WIDTH) if width else MONITOR_WIDTH   # 0.21.20: a presenter screen may be 1920 wide
        scale = "scale=w='min(iw,%d)':h=-2:in_range=pc:out_range=tv" % cap
        enc = encoder or "libx264"
        args += ["-vf", encoder_vf(enc, SQUARE_PIXELS + "," + scale + ",format=yuv420p"),   # 0.9.8: square pixels first
                 "-color_range", "tv", "-colorspace", "bt709",
                 "-r", str(MONITOR_FPS)]

        args += ["-c:v", enc]
        if enc == "libx264":
            args += [
                "-preset", "ultrafast",
                "-tune", "zerolatency",
                "-profile:v", "baseline",
                "-pix_fmt", "yuv420p",
                "-crf", "28",
                "-threads", "2",
            ]
        else:
            # Hardware encoders want a target rate rather than a CRF, and
            # their own low-latency switches vary, so keep it to the basics.
            args += ["-b:v", "1500k"]
        args += ["-g", str(MONITOR_FPS * 2)]

    args += [
        "-an",   # see above: bridge output is video-only
        "-f", "mp4",
        # Fragmented + empty moov = playable before the stream ends, which a
        # live feed never does. default_base_moof keeps Chrome's parser happy.
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-frag_duration", "200000",     # 200ms fragments
        "pipe:1",
    ]
    return args

def _darwin_fallback(exe):
    """0.13.1: a Finder-launched .app has a bare PATH -- look where Homebrew
    (Apple Silicon, Intel) installs before giving up on shutil.which."""
    if sys.platform != "darwin":
        return None
    for d in ("/opt/homebrew/bin", "/usr/local/bin"):
        cand = os.path.join(d, exe)
        if os.path.exists(cand):
            return cand
    return None


def find_ffmpeg():
    """Bundled copy first, then PATH.

    The packaged app ships ffmpeg.exe alongside the web files so operators do
    not have to install anything; a dev checkout falls back to PATH.
    """
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.join(sys._MEIPASS, "bin"))
    roots.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin"))
    for root in roots:
        cand = os.path.join(root, exe)
        if os.path.exists(cand):
            # A bundled binary loses its executable bit on some unpack paths.
            _ensure_exec(cand)
            return cand
    return _darwin_fallback(exe) or shutil.which("ffmpeg")


def find_moq():
    """0.9.1: the bundled moq-cli (native MoQ publisher), bundled copy then PATH."""
    exe = "moq.exe" if sys.platform == "win32" else "moq"
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.join(sys._MEIPASS, "bin"))
    roots.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin"))
    for root in roots:
        cand = os.path.join(root, exe)
        if os.path.exists(cand):
            _ensure_exec(cand)
            return cand
    return _darwin_fallback(exe) or shutil.which("moq")


def publish_output_args(copy_video, encoder=None, width=None, audio=True, mux=None, audio_input=0, screen=False, lowlat=None):
    """0.9.1: ffmpeg output for the native publisher -- MPEG-TS on stdout with
    audio carried (AAC) unless the operator turned it off for this feed (0.9.5:
    audio=False -> video only, -an), video copied when the camera is already
    H.264 and otherwise encoded once. This replaces the browser's second encode.
    0.21.20: a screen share's sound is a second input (audio_input=1, PCM on stdin) and screens get
    a higher bitrate -- text needs it."""
    args = ["-map", "0:v:0"] + (["-map", "%d:a:0%s" % (audio_input, "" if audio_input else "?")] if audio else [])
    if copy_video:
        args += ["-c:v", "copy"]
    else:
        scale = "scale=%s:-2:in_range=pc:out_range=tv" % (width or ("trunc(iw/2)*2" if screen else "iw"))   # 0.21.79: an X11 window may be odd-wide
        enc = encoder or "libx264"
        args += ["-vf", encoder_vf(enc, SQUARE_PIXELS + "," + scale + ",format=yuv420p"), "-color_range", "tv", "-colorspace", "bt709"]   # 0.9.8: square pixels first
        args += ["-c:v", enc]
        if enc == "libx264":
            args += ["-preset", "veryfast", "-tune", "zerolatency", "-profile:v", "main", "-pix_fmt", "yuv420p", "-b:v", "5M" if screen else "3M"]
        else:
            args += ["-b:v", "6M" if screen else "4M"]
        args += ["-g", "60"]
        if lowlat:   # 0.21.80: a remote-controlled share (RC_LOWLAT, validated by Bridge.rc_lowlat)
            args += list(lowlat)
    args += (["-c:a", "aac", "-b:a", "128k", "-ac", "2"] if audio else ["-an"])
    if lowlat is not None:
        args += RC_MUX
    if (mux or PUBLISH_MUX) == "fmp4":
        args += ["-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-"]
    else:
        args += ["-f", "mpegts", "-pes_payload_size", "0", "-"]
    return args


# 0.18.0 (landscape item 5): the thumbnail rendition. A sibling broadcast
# `<leaf>-low.hang` carries the same camera at 640 wide / 15 fps / 400 kb/s (always an
# encode) so rail tiles and grid cells stop pulling the full stream. moq-cli builds the
# catalog, so the pairing is a naming convention the viewer page understands.
LOW_WIDTH = 640
LOW_FPS = 15
LOW_BITRATE = "400k"


def low_broadcast(name):
    """room/host/op/leaf.hang -> room/host/op/leaf-low.hang (idempotent)."""
    n = str(name or "")
    if n.endswith("-low.hang"):
        return n
    return (n[:-5] if n.endswith(".hang") else n) + "-low.hang"


def low_output_args(encoder=None):
    """ffmpeg output for the low rendition: video only, small, cheap, MPEG-TS on stdout."""
    enc = encoder or "libx264"
    scale = "scale=w='min(iw,%d)':h=-2:in_range=pc:out_range=tv" % LOW_WIDTH
    args = ["-map", "0:v:0", "-vf", encoder_vf(enc, SQUARE_PIXELS + "," + scale + ",format=yuv420p"),
            "-color_range", "tv", "-colorspace", "bt709", "-r", str(LOW_FPS), "-c:v", enc]
    if enc == "libx264":
        args += ["-preset", "ultrafast", "-tune", "zerolatency", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
                 "-b:v", LOW_BITRATE, "-maxrate", LOW_BITRATE, "-bufsize", "800k", "-threads", "2"]
    else:
        args += ["-b:v", LOW_BITRATE]
    args += ["-g", str(LOW_FPS * 2), "-an", "-f", "mpegts", "-pes_payload_size", "0", "-"]
    return args


# 0.18.0 (landscape item 8): hooks -- operator commands run on feed events.
# kastr.ini hook_ready / hook_notready / hook_read (or KASTR_HOOK_READY/... in the
# environment for a dev checkout), each a shell command. They run detached with
# KASTR_EVENT, KASTR_BROADCAST, KASTR_FEED_ID, KASTR_RELAY (token-free), KASTR_REASON and
# KASTR_VIEWER set, stdout/stderr discarded, killed after hook_timeout seconds.
HOOK_EVENTS = ("ready", "notready", "read")
HOOK_READY_AFTER_S = 5          # a pair alive this long is "ready"


class Hooks:
    def __init__(self, cmds=None, log=None, timeout=30):
        cmds = cmds or {}
        self.cmds = {e: (str(cmds.get(e) or "").strip() or None) for e in HOOK_EVENTS}
        self.log = log or (lambda m: None)
        try:
            self.timeout = max(1, min(600, int(timeout)))
        except (TypeError, ValueError):
            self.timeout = 30
        self.fired = []          # the last 20 firings {at, event, broadcast, pid|error}

    @classmethod
    def from_env(cls, log=None):
        return cls({e: os.environ.get("KASTR_HOOK_" + e.upper()) for e in HOOK_EVENTS}, log,
                   os.environ.get("KASTR_HOOK_TIMEOUT") or 30)

    def configured(self):
        return {e: bool(c) for e, c in self.cmds.items()}

    def fire(self, event, broadcast="", feed_id="", relay="", reason="", viewer=""):
        cmd = self.cmds.get(event)
        if not cmd:
            return None
        env = dict(os.environ)
        env.update({"KASTR_EVENT": event, "KASTR_BROADCAST": str(broadcast or ""), "KASTR_FEED_ID": str(feed_id or ""),
                    "KASTR_RELAY": re.sub(r"\?jwt=[^&]*", "", str(relay or "")), "KASTR_REASON": str(reason or "")[:200],
                    "KASTR_VIEWER": str(viewer or "")[:120]})
        rec = {"at": time.time(), "event": event, "broadcast": broadcast}
        try:
            proc = subprocess.Popen(cmd, shell=True, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            rec["pid"] = proc.pid
            self.log("hook: %s %s -> pid %d" % (event, broadcast or "-", proc.pid))

            def reap(p=proc):
                try:
                    p.wait(timeout=self.timeout)
                except Exception:
                    try:
                        p.kill()
                        self.log("hook: %s %s pid %d killed after %d s" % (event, broadcast or "-", p.pid, self.timeout))
                    except Exception:
                        pass
            threading.Thread(target=reap, daemon=True).start()
        except Exception as e:
            rec["error"] = str(e)[:160]
            self.log("hook: %s %s failed to start: %s" % (event, broadcast or "-", e))
        self.fired.append(rec)
        del self.fired[:-20]
        return rec


PUBLISH_RETRY_S = [1, 2, 5, 10, 20, 30]
# 0.21.91 (field: a whole-screen share froze on one picture while the controller opened apps): the frozen-capture watchdog.
# A native screen share whose ffmpeg is alive but whose output has not grown for SCREEN_STALL_S seconds (a capture that stopped
# delivering, an encoder or pipe that stalled) restarts its capture and says so in launch.log -- never a silent freeze. A
# second freeze waits SCREEN_STALL_BACKOFF[n] s after the last restart (a locked box's capture must not churn); two quiet
# minutes start the count over. KASTR_SCREEN_STALL_S=0 switches the watchdog off.
try:
    SCREEN_STALL_S = float(os.environ.get("KASTR_SCREEN_STALL_S") or 8)
except ValueError:
    SCREEN_STALL_S = 8.0
SCREEN_STALL_BACKOFF = [0, 30, 60, 120, 300]
SCREEN_STALL_RESET_S = 120
SCREEN_STALL_RELAY_S = 20   # 0.21.91: a moq session line (SOFT/HARD) this recent means the relay link, not the capture, stalled
# 0.21.93 (field, Kordale's My room: a Teams window share's VIDEO stopped every few minutes while its SOUND kept playing; only
# Pause + Resume brought the picture back): the watchdog above measures ffmpeg's OUTPUT BYTES, which a share with sound could
# keep growing while its picture has stopped. A screen share's picture is a constant 30 fps clock (kastr_screen._clocked; the
# paused card too), so a flat video FRAME count (-progress `frame=`) on a running pair is never normal: it is judged by its own
# clock as well, with the same threshold, backoff and relay exemption, and shown in diag (videoFrames / videoAt).
# Lab 2026-10-28 (bundled ffmpeg 9.0.1, the real clocked graph, a capture branch that stops without ending, PCM sound on stdin):
# the overlay holds the clock AND ffmpeg's scheduler holds the sound with it -- frames and bytes go flat together, so the
# output-bytes check already restarts that one ("capture froze"). Sound that keeps playing while the picture is gone therefore
# points past ffmpeg (moq import / relay / the viewer); videoFrames climbing in diag during such a stall proves it. The frame
# clock is the safety net for an ffmpeg that does let the sound through ("video stopped ... sound kept flowing" in launch.log).
# 0.21.93 (item 4): the heal for the stall past ffmpeg. A VIEWER whose tile's picture stopped while its sound kept playing
# re-subscribes on its own first; still stalled 6 s later, it reports to the owner (room.json `stalled`, kind "video" -- My room
# and invite-link guests included). The owner's page posts /api/rtsp/heal and the pair restarts the cheapest part that cures it:
# first only its `moq import` (a fresh relay session and announce -- ffmpeg, the capture and the sound loopback keep running;
# the new moq starts at the next PAT, as LibMirror does), then -- a second report within HEAL_ESCALATE_S of an import restart
# means that did not bring the picture back -- the whole pair (ffmpeg-first quiet() + a fresh start: what ONE half of Pause +
# Resume does; Pause + Resume is two such restarts, onto the pause card and back). At most one heal per HEAL_GAP_S per share
# and HEAL_MAX per HEAL_WINDOW_S; each one (and each refusal) is one launch.log line.
HEAL_GAP_S = 30
HEAL_MAX = 6
HEAL_WINDOW_S = 600
HEAL_ESCALATE_S = 120
HEAL_SWAP_WAIT_S = 1.5    # the old moq's grace to close its session on EOF before it is killed


def _close_quiet(f):
    try:
        if f is not None:
            f.close()
    except Exception:
        pass


def screen_exit_reason(url, who, code):
    """0.21.91: launch.log's words for a screen share's ffmpeg that ended on its own with code 0 -- the capture ended
    (kastr_screen._clocked eof=endall: Windows closed the monitor's capture), or ""."""
    if who != "ffmpeg" or not is_screen(url or ""):
        return ""
    try:
        if int(code) != 0:
            return ""
    except (TypeError, ValueError):
        return ""
    return ("the screen capture ended -- Windows closed it (a display change: resolution, scaling, a monitor switched off or "
            "unplugged, a dock, a remote-desktop or graphics-driver reset); restarting it")
# 0.21.91 (Kenton: alerts "after 1 try, and maybe again after a few tries, but I don't need it repeating forever" -- and the
# log the same): a pair that keeps failing writes its start/exit lines in full for its FIRST try and its LOG_QUIET_AFTER-th
# (with "still failing ... retrying quietly"), nothing for the tries between or after, and one summary line every
# LOG_QUIET_SUMMARY_S while it keeps failing; the first time it streams again it says so (after how many failed tries). A
# generation that lived over a minute exits in full as before (that is news, not a retry).
LOG_QUIET_AFTER = 5
LOG_QUIET_SUMMARY_S = 600


def pause_card_input(url):
    """0.21.73 (Kenton: "a pause share button, so I don't have to stop all streaming before resharing"): what a paused
    share sends instead of the screen -- a dark card with a pause sign, at the size the share has (the same broadcast, so
    viewers keep its tile, pins and spotlight). No fonts needed (two boxes)."""
    w, h = 1280, 720
    try:
        import kastr_screen
        w, h = kastr_screen.capture_size(url)
    except Exception:
        pass
    w, h = max(320, int(w or 1280)) // 2 * 2, max(180, int(h or 720)) // 2 * 2
    bar = "drawbox=x=%s:y=ih*0.38:w=iw*0.035:h=ih*0.24:color=white@0.85:t=fill"
    vf = ("color=c=0x0f2235:s=%dx%d:r=%d," % (w, h, 30) + bar % "iw*0.455" + "," + bar % "iw*0.51" + ",format=yuv420p,setsar=1")
    return ["-f", "lavfi", "-i", vf]


def rc_screen_opts():
    """0.21.80: kastr_screen.capture_input options while a share is remote-controlled: no cursor drawn into the picture (the
    sharer's own pointer travels in ptr.json and every viewer draws it with the sharer's name), the remote-control frame rate."""
    import kastr_screen
    return {"cursor": False, "fps": kastr_screen.RC_FPS}


def nudge_bucket(why):
    """0.13.1: which counter a nudge reason lands in -- the page's viewer
    stall ("viewer", "stall*"), the page's no-echo heal ("no-echo"), or a
    plain API/tool call (anything else)."""
    w = str(why or "api").strip().lower()
    if w == "viewer" or w.startswith("stall"):
        return "viewer"
    if w in ("no-echo", "noecho", "no_echo"):
        return "noEcho"
    return "api"


class LibMirror:
    """0.21.85: a LISTED native share's library copy -- a second moq that publishes the pair's MPEG-TS at its lib/ path on a
    library publisher token. Fed by the pair's pump (Publisher._pump) it never slows the room's moq: a queue between them
    (LIB_MIRROR_QMAX), its own writer thread and its own restarts (a refused or dead moq comes back on LIB_MIRROR_RETRY_S; a copy
    that falls behind starts again at the next PAT). It runs while the share is listed (`pub.libMirror` = (path, url), set by
    the bridge's library round) and ends with the pair's generation (EOF: the relay withdraws the library path at once)."""

    def __init__(self, pub, gen):
        self.pub, self.gen = pub, gen
        self.proc = None
        self.key = None
        self.sync = True
        self.q = []
        self.qn = 0
        self.busy = 0
        self.cv = threading.Condition()
        self.closed = False
        self.fails = 0
        self.next_at = 0.0
        self.started = None
        self.error = None
        self.hard = False

    def want(self):
        m = _lib_mirror_of(self.pub)
        if not m or self.closed or self.pub.stopping or self.gen != self.pub._gen:
            return None
        return m

    def feed(self, b, off):
        """One chunk the room's moq already has (byte `off` onwards of the stream)."""
        if self.closed:
            return
        m = self.want()
        p = self.proc
        if p is not None and (m != self.key or p.poll() is not None):
            self._end("exited" if p.poll() is not None else "changed")
            p = None
        if m is None:
            return
        if p is None and (time.time() < self.next_at or not self._spawn(m)):
            return
        if self.sync:
            i = ts_pat_start(b, off)
            if i is None:
                return
            b = b[i:]
            self.sync = False
        behind = False
        with self.cv:
            if self.proc is None:
                return
            if self.qn + len(b) > LIB_MIRROR_QMAX:
                behind = True
            else:
                self.q.append(b)
                self.qn += len(b)
                self.cv.notify()
        if behind:
            self._end("behind")

    def _spawn(self, m):
        path, url = m
        bridge = self.pub.bridge
        if not getattr(bridge, "moq", None):
            return False
        argv = [bridge.moq, "--log-level", "warn", "--backoff-timeout", "10s", "--quic-idle-timeout", "15s",
                "--connect", url, "--broadcast", path, "import", "--max-age", "5s", PUBLISH_MUX]
        try:
            p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, bufsize=0,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            self.error = "could not start: %s" % e
            self._backoff(True)
            return False
        bridge._child_started(p, argv, [path], "moq-lib")
        with self.cv:
            self.proc, self.key, self.sync, self.started, self.hard, self.error = p, m, True, time.time(), False, None
            self.q, self.qn = [], 0
        threading.Thread(target=self._write, args=(p,), daemon=True, name="kastr-lib-copy").start()
        threading.Thread(target=self._drain, args=(p,), daemon=True, name="kastr-lib-copy-err").start()
        bridge.log("rtsp: %s listed in the stream library as %s (gen %d)" % (self.pub.broadcast, path, self.gen))
        return True

    def _write(self, p):
        while True:
            with self.cv:
                while not self.q and self.proc is p and not self.closed:
                    self.cv.wait(1.0)
                if self.proc is not p or not self.q:
                    return
                b = self.q.pop(0)
                self.qn -= len(b)
                self.busy += 1
            try:
                mv = memoryview(b)
                while mv:
                    n = p.stdin.write(mv)
                    if not n:
                        raise OSError("short write")
                    mv = mv[n:]
            except (OSError, ValueError):
                return   # its exit is seen by the next feed()
            finally:
                with self.cv:
                    self.busy -= 1

    def _drain(self, p):
        try:
            for line in p.stderr:
                text = _redact(_ANSI_RE.sub("", line.decode("utf-8", "replace")).strip())
                if text:
                    self.error = text[-160:]
                    if HARD_RE.search(text):
                        self.hard = True
        except Exception:
            pass

    def _backoff(self, failed):
        self.fails = self.fails + 1 if failed else 0
        wait = LIB_MIRROR_RETRY_S[min(max(self.fails - 1, 0), len(LIB_MIRROR_RETRY_S) - 1)]
        self.next_at = (time.time() + wait) if failed else 0.0

    def _end(self, why):
        with self.cv:
            p, self.proc, self.key = self.proc, None, None
            self.q, self.qn = [], 0
            self.sync = True
            self.cv.notify_all()
        if p is None:
            return
        lived = time.time() - (self.started or time.time())
        failed = why in ("exited", "behind") and lived < 60
        self._backoff(failed)
        bridge = self.pub.bridge
        if why == "exited" and self.hard:   # the relay refused its token: a fresh one is minted for the next try
            try:
                bridge._lib()["toks"].pop(_relay_key(self.pub.relay), None)
            except Exception:
                pass
        if why not in ("pair ended", "changed") or failed:
            bridge.log("rtsp: library copy of %s ended (%s after %.0f s%s)" % (self.pub.broadcast, why, lived,
                                                                            (": " + self.error) if (self.error and failed) else ""))

        def finish():
            try:
                p.stdin.close()   # EOF: moq ends its session, the relay withdraws the library path at once
            except Exception:
                pass
            try:
                p.wait(timeout=1.5)
            except Exception:
                pass
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
            bridge._child_ended(p.pid)
        threading.Thread(target=finish, daemon=True).start()

    def close(self):
        """The pair's generation ended: what is queued still goes out (up to 2 s), then EOF."""
        with self.cv:
            self.closed = True
            p = self.proc
            self.cv.notify_all()
        if p is None:
            return

        def drain():
            t0 = time.time()
            while time.time() - t0 < 2.0:
                with self.cv:
                    if (not self.q and not self.busy) or self.proc is not p:
                        break
                time.sleep(0.02)
            if self.proc is p:
                self._end("pair ended")
        threading.Thread(target=drain, daemon=True).start()

    def info(self):
        p = self.proc
        return {"path": (self.key or (None, None))[0], "running": bool(p is not None and p.poll() is None), "since": self.started,
                "fails": self.fails, "error": self.error}


class Publisher:
    """0.9.1: one camera on the relay without the browser -- ffmpeg | moq.

    ffmpeg pulls the feed (copy when H.264, else one hardware/x264 encode)
    and writes MPEG-TS to moq-cli, which publishes `broadcast` on `relay`
    (moq-lite; `?jwt=` in the URL carries a room token). Either process
    exiting restarts the pair on the RTSP retry ladder until stop()."""

    def __init__(self, bridge, feed, broadcast, relay, hevc=False, audio=True, passthrough=None,
                 minter=None, keep=True, ondemand=False, low=False, role="main", label="", idle=False):   # 0.12.0 / 0.18.0; 0.21.73 idle
        self.bridge = bridge
        self.feed = feed
        self.broadcast = broadcast
        self.relay = relay
        # 0.18.0: role "main" (the camera) or "low" (the thumbnail sibling it owns);
        # an on-demand main pair waits in STANDBY until a viewer asks (Bridge demand loop)
        self.role = role
        self.label = str(label or "")[:80]
        self.wantOndemand = bool(ondemand)   # 0.21.10: what was asked (persisted) ...
        self.wantLow = bool(low)
        self.ondemand = bool(ondemand) and role == "main" and ONDEMAND_ENABLED   # ... and what takes effect
        self.standby = self.ondemand
        self.wantedAt = None        # last time the relay host said a viewer wants it
        self.suspended = False      # 0.21.16: the box's RTSP switch is off -- recorded, nothing runs (Publisher.suspend / resume)
        self.wokeAt = None
        self.paused = False                              # 0.21.73: a paused share sends a "paused" card (Bridge.pause)
        self.rcmode = False                              # 0.21.80: someone controls this share -- no cursor in the capture, low-latency encode
        self.wantIdle = bool(idle) and role == "main"   # 0.21.73: the page says this camera is a grid member (asleep while unwatched)
        self.sleepy = False                              # ... and it takes effect once this pair is known to ENCODE (_sleepy_eval)
        self.lowPub = None
        if low and role == "main" and ONDEMAND_ENABLED:   # 0.21.10: no -low.hang sibling while the switch is off
            self.lowPub = Publisher(bridge, feed, low_broadcast(broadcast), relay, audio=False, minter=minter,
                                    keep=False, role="low")
        self._readyGen = None       # generation that fired the ready hook
        # 0.12.0: publishers that heal. `minter()` -> a fresh relay URL (with
        # ?jwt= on a secured relay, bare on an open one) or None; `keep` marks
        # the feed for republishing after a relaunch (rtsp-feeds.json).
        self.minter = minter
        self.keep = bool(keep)
        self.needsToken = False     # the relay refused our token; parked until a fresh one arrives
        self.lastFailAt = None      # when the last refused pair ended
        self.lastSession = None     # last classified moq line (jwt-free)
        self.sessionFails = 0       # SOFT: severed/closed, moq reconnecting on its own
        self.sessionKills = 0       # HARD: refused / reconnect loop gave up
        self.parked = False
        self.tokenExp = None        # `exp` of the token the RUNNING moq process holds (0.21.58: was "in self.relay")
        self.runToken = None        # 0.21.58: that token itself -- self.relay may already carry a fresher one
        self._hard = {}             # generation -> the refusal line that ends it
        self._drains = []           # this generation's stderr readers
        self._mintAt = 0            # last minter() call (one per minute at most)
        self._bareAt = 0            # last bare retry from a park (one per five minutes)
        self._renew = None          # token renewal timer (page-less boxes)
        # 0.9.6: pass the camera through whenever viewers can decode it (the
        # 0.9.2 H.265-only switch widened; `hevc` kept as the old name)
        self.passthrough = bool(passthrough if passthrough is not None else hevc)
        self.hevc = self.passthrough
        self.audio = bool(audio)    # 0.9.5: carry the camera's audio (operator's call, per feed)
        if self.audio and is_screen(getattr(feed, "url", "")) and sys.platform != "win32":
            self.audio = False      # 0.21.79: a Linux screen share (x11grab) has no computer-sound capture
        self.codec = None
        self.procs = ()
        self.running = False
        self.stopping = False
        self.restarts = 0
        self.copy = None
        self.errors = []
        self.error = None
        self.since = None
        self.reused = 0             # 0.9.8: publish requests answered by this same pair
        # 0.13.1: who restarted us and what died -- every "random drop" attributed
        self.nudges = {"viewer": 0, "noEcho": 0, "api": 0, "refused": 0}   # 0.21.8: + refused (a viewer report against a fresh pair)
        self.lastNudgeWhy = None
        self.lastNudgeAt = None
        self.lastExit = None        # {code, who: "ffmpeg"|"moq", at, lived} from _watch
        # 0.13.3: attribution that cannot lie -- `restarts` forgets after a good
        # minute, this never does; `lastSessionAt` = the last HARD/SOFT moq line
        self.restartsTotal = 0
        self.lastSessionAt = None
        self.flowingAt = None       # 0.21.31: the last time ffmpeg's output grew -- the camera is really streaming
        self.videoFrames = 0        # 0.21.93: ffmpeg's video frame count (-progress frame=) of the running generation
        self.videoAt = None         # 0.21.93: the last time that count grew -- the picture is really moving
        self._vFrames = 0
        self._vSeen = False         # 0.21.93: this generation printed frame= (an encode that reports its video count)
        self.captureStalls = 0      # 0.21.91: frozen-capture watchdog restarts (screen shares) -- never forgotten
        self.lastCaptureStall = None   # 0.21.91: {at, quiet, gen, paused, rc} of the last one
        self._stallAt = 0.0
        self._stallRun = 0
        self._outSize = 0
        self._timer = None
        self._lock = threading.Lock()
        self._gen = 0
        self.pumped = False         # 0.21.85: this generation's MPEG-TS passes a pump (a listed share's library copy rides on it)
        self.libMirror = None       # 0.21.85: (lib path, library URL) while this share is LISTED in the stream library
        self.libPipe = None         # 0.21.85: the running generation's LibMirror
        self.heals = {"import": 0, "pair": 0, "limited": 0, "refused": 0}   # 0.21.93: viewer-reported video stalls healed here
        self.lastHeal = None        # 0.21.93: {at, step, why, gen, ok, reason?} of the last heal request
        self._healHist = []         # 0.21.93: when the heals of the last HEAL_WINDOW_S ran
        self._mqArgv = None         # 0.21.93: this generation's moq argv (an import restart reuses it)
        self._mqDst = None          # 0.21.93: where the pump writes (the current moq's stdin; None = between moqs, dropped)
        self._mqSync = False        # 0.21.93: the next write starts at a PAT (a fresh moq reads the tables first)
        self._reimp = None          # 0.21.93: an import restart in flight (the watcher ignores the old moq's exit)
        self.importRestarts = 0     # 0.21.93: moq-only restarts -- never forgotten

    def info(self):
        return {"broadcast": self.broadcast,
                "relay": re.sub(r"\?jwt=[^&]*", "?jwt=...", self.relay),
                "running": self.running, "restarts": self.restarts,
                "copy": self.copy, "codec": self.codec, "hevc": self.hevc,
                "passthrough": self.passthrough, "audio": self.audio,
                "sar": ("%d:%d" % tuple(self.feed.sar)) if self.feed.sar else None,   # 0.9.8
                "reused": self.reused,
                "needsToken": self.needsToken, "parked": self.parked,           # 0.12.0
                "lastFailAt": self.lastFailAt, "lastSession": self.lastSession,
                "sessionFails": self.sessionFails, "sessionKills": self.sessionKills,
                "tokenExp": self.tokenExp, "keep": self.keep,
                "nudges": dict(self.nudges), "lastNudgeWhy": self.lastNudgeWhy,   # 0.13.1
                "lastNudgeAt": self.lastNudgeAt, "lastExit": self.lastExit,       # 0.13.1
                "gen": self._gen, "restartsTotal": self.restartsTotal,            # 0.13.3
                "lastSessionAt": self.lastSessionAt,                               # 0.13.3
                "ondemand": self.ondemand, "standby": self.standby,                # 0.18.0
                "sleepy": self.sleepy, "idle": self.wantIdle,                      # 0.21.73: encodes only while watched
                "paused": bool(self.paused),                                       # 0.21.73: a share showing its "paused" card
                "wantedAt": self.wantedAt, "role": self.role,
                "low": (self.lowPub.low_info() if self.lowPub else None),
                "lowLive": bool(self.lowPub is not None and self.lowPub.running),   # 0.21.7
                "suspended": bool(self.suspended),                                   # 0.21.16: the box's RTSP switch is off
                "flowingAt": self.flowingAt,                                         # 0.21.31
                "videoFrames": self.videoFrames, "videoAt": self.videoAt,            # 0.21.93: video-only stalls
                "captureStalls": self.captureStalls,                                 # 0.21.91: frozen-capture watchdog
                "lastCaptureStall": self.lastCaptureStall,                           # 0.21.91
                "heals": dict(self.heals), "lastHeal": self.lastHeal,                # 0.21.93: viewer-reported video stalls
                "importRestarts": self.importRestarts,                               # 0.21.93
                "library": self._library_info(),                                     # 0.21.84: the stream library (main pairs)
                "listed": self._listed_info(),                                       # 0.21.85: listed there too (its room path kept)
                "error": self.error, "since": self.since}

    def _library_info(self):
        if self.role != "main" or not hasattr(self.bridge, "_lib_info"):
            return None
        try:
            return self.bridge._lib_info(self.feed, self)
        except Exception:
            return None

    def _listed_info(self):
        """0.21.85: this share's library copy (never its URL -- the token is in it)."""
        if self.role != "main":
            return None
        out = {"pumped": bool(self.pumped), "path": (self.libMirror or (None, None))[0], "running": False}
        lp = self.libPipe
        if lp is not None and lp.gen == self._gen:
            out.update({k: v for k, v in lp.info().items() if k != "path"})
        return out

    def low_info(self):
        return {"broadcast": self.broadcast, "running": self.running, "restarts": self.restarts,
                "error": self.error, "since": self.since}

    def _args(self):
        ff = self.bridge.ffmpeg
        h264 = self.bridge.sends_h264(self.feed)
        vcodec = (self.feed.vcodec or ("h264" if h264 else "")).lower()
        wide = (self.feed.width or 0) > MAX_WIDTH
        # 0.9.6: one rule (passthrough_ok): copy whenever viewers can decode
        # what the camera sends and the operator allows it; H.264 within the
        # old limits copies regardless; everything else -> one H.264 encode.
        tr = feed_transport(self.feed)   # 0.21.96: "tcp" | "udp" for an rtsp:// camera, else None
        self.copy = passthrough_ok(vcodec, self.feed.width, self.feed.fullrange, self.passthrough, self.feed.sar)
        if self.copy and tr == "udp" and not udp_copy_ok():
            self.copy = False            # 0.21.96: see udp_copy_ok -- a lossy copy froze every viewer
        self.codec = vcodec if self.copy else "h264"
        if self.role == "low":      # 0.18.0: the thumbnail sibling is always a small encode
            self.copy = False
            self.codec = "h264"
        self._sleepy_eval()         # 0.21.73: an encoding grid camera sleeps while nobody watches
        enc = None if self.copy else self.bridge.usable_encoder()
        # 0.21.31: -progress on stderr -> flowingAt (a pair can RUN for a long time against a dark camera without one byte)
        scr = is_screen(self.feed.url)
        card = scr and self.paused and self.role != "low"   # 0.21.73: a paused share -- the card, and silence
        # 0.21.80: under remote control the capture leaves the real cursor out (viewers draw both people's pointers, tagged,
        # from the share's ptr.json) and the encode turns low-latency
        rc = bool(scr and self.rcmode and not card and self.role != "low")
        sopts = rc_screen_opts() if rc else None
        self._transport = tr
        self._lvl = tr is not None                           # 0.21.96: level-tagged lines -> the demuxer's loss is counted
        if tr is not None and getattr(self.feed, "loss", None) is not None:
            self.feed.loss.touch(self._reader())
        args = ([ff, "-hide_banner", "-loglevel", RTSP_LOGLEVEL if tr else "error", "-progress", "pipe:2", "-stats_period", "2"] + encoder_pre_args(enc)
                + (pause_card_input(self.feed.url) if card else input_args(self.feed.url, role="low" if self.role == "low" else "pub", screen_opts=sopts,
                                                                           transport=tr)))
        if card and self.audio:
            args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        elif scr and self.audio and self.role != "low":   # 0.21.20: the computer's sound, PCM on stdin (kastr_screen.Loopback)
            import kastr_screen
            args += kastr_screen.LOOPBACK_INPUT
        if self.role == "low":
            args += low_output_args(encoder=enc)
        else:
            args += publish_output_args(self.copy, encoder=enc, width=MAX_WIDTH if wide else None, audio=self.audio,
                                        audio_input=1 if scr else 0, screen=scr,
                                        lowlat=(self.bridge.rc_lowlat(enc or "libx264") if rc and hasattr(self.bridge, "rc_lowlat") else None))
        # 0.12.0: `warn` is where moq's reconnect/refusal lines live (the
        # classifier in _drain reads them); --backoff-timeout 10s is moq's
        # measured default made explicit (it exits 1 after that -> _watch);
        # a 15 s QUIC idle timeout (5 s keep-alives) notices a dead relay in
        # 15 s instead of 30. Root options go before the `import` subcommand.
        # 0.16.0 (moq-cli 0.12): --client-connect -> --connect, --client-quic-idle-timeout ->
        # --quic-idle-timeout, and `import --latency-max` -> `import --max-age` (a retention
        # budget: how long relays keep a non-latest group fetchable). Spellings read from
        # `moq --help` / `moq import --help` on 0.12.1, 2026-09-24.
        moq = [self.bridge.moq, "--log-level", "warn", "--backoff-timeout", "10s",
               "--quic-idle-timeout", "15s", "--connect", self.relay,
               "--broadcast", self.broadcast, "import", "--max-age", "5s", PUBLISH_MUX]
        return args, moq

    def start(self):
        with self._lock:
            if self.stopping or self.standby or self.suspended:   # 0.18.0: a standby pair starts only through wake(); 0.21.16: a suspended one only through resume()
                return
            # 0.13.3: whatever timer led here has fired (or was cancelled by the
            # caller); a spent timer left in place would block the next ladder
            # step (_schedule_restart_locked schedules only when none is queued)
            self._timer = None
            # 0.12.0: defensive -- a pair still alive from an older generation
            # (a nudge/retoken racing a queued timer) must not outlive this start
            stale = [p for p in self.procs if p.poll() is None]
            for p in stale:
                try:
                    p.kill()
                    p.wait(timeout=2)   # 0.21.30: gone before the next one binds the same loopback port
                except Exception:
                    pass
                self.bridge._child_ended(p.pid)
            self.procs = ()
            self._gen += 1
            gen = self._gen
            self._outSize = 0                                            # 0.21.31: this generation has delivered nothing yet
            self._vFrames, self._vSeen, self.videoFrames = 0, False, 0       # 0.21.93: nor a video frame
            self._hard = {g: r for g, r in self._hard.items() if g >= gen}   # 0.12.0: older verdicts are spent
            ff_args, moq_args = self._args()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ff = None
            pump = False   # 0.21.85: a listed share's output passes a pump (its library copy rides on it)
            try:
                pump = self.role == "main" and bool(self.bridge._lib_list_pump(self))
            except Exception:
                pump = False
            if self.role == "main" and is_screen(getattr(self.feed, "url", "")):
                pump = True   # 0.21.93: a screen share's moq import can be restarted alone (restart_import) -- the pump swaps it
            try:
                snd = is_screen(self.feed.url) and self.audio and self.role != "low" and not self.paused   # 0.21.20; 0.21.73: a paused share is silent
                ff = subprocess.Popen(ff_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      stdin=subprocess.PIPE if snd else subprocess.DEVNULL,
                                      bufsize=0, creationflags=flags)
                mq = subprocess.Popen(moq_args, stdin=(subprocess.PIPE if pump else ff.stdout), stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, creationflags=flags, **({"bufsize": 0} if pump else {}))
                if snd:
                    import kastr_screen
                    kastr_screen.feed_loopback(ff, exclude_pid=self.bridge.own_pid(), log=self.bridge.log)
            except OSError as e:
                if ff is not None and ff.poll() is None:   # 0.9.8: a moq that failed to start must not leak its ffmpeg
                    try:
                        ff.kill()
                    except OSError:
                        pass
                self.error = "could not start: %s" % e
                self.running = False
                self._schedule_restart_locked()                          # 0.13.3: lock held
                return
            if not pump:
                ff.stdout.close()       # moq owns the read end now
            self.procs = (ff, mq)
            self.pumped = pump
            self._mqArgv = list(moq_args)                                # 0.21.93
            self._mqDst, self._mqSync, self._reimp = (mq.stdin if pump else None), False, None
            # 0.9.8: into the job and the registry -- they die with KASTR now
            self.bridge._child_started(ff, ff_args, [self.feed.url], "ffmpeg")
            self.bridge._child_started(mq, moq_args, [self.broadcast], "moq")
            self.running = True
            self.since = time.time()
            # 0.13.3: one launch.log line per generation (formatted here, written
            # after the lock -- the log may block on I/O)
            start_line = ("rtsp pair %s gen=%d start restarts=%d total=%d copy=%s ffmpeg=%s moq=%s"
                          % (self.broadcast, gen, self.restarts, self.restartsTotal, self.copy, ff.pid, mq.pid))
            start_r = self.restarts                                       # 0.21.91: this try's place on the ladder
            self.errors.clear()
            self.error = None
            self.parked = False                                          # 0.12.0
            self.runToken = _relay_token(self.relay)                     # 0.21.58: what this generation dials with
            self.tokenExp = _jwt_exp(self.runToken)                      # 0.12.0
            drains = [threading.Thread(target=self._drain, args=(ff, "ffmpeg", gen), daemon=True),
                      threading.Thread(target=self._drain, args=(mq, "moq", gen), daemon=True)]
            self._drains = drains
        self._lq_line(start_line, start_r, "start")                       # 0.13.3; 0.21.91: quiet while it keeps failing
        for t in drains:
            t.start()
        if pump:   # 0.21.85
            threading.Thread(target=self._pump, args=(gen, ff, mq), daemon=True, name="kastr-pair-pump").start()
        threading.Thread(target=self._watch, args=(gen, ff, mq, drains), daemon=True).start()
        self._arm_renew()                                                # 0.12.0
        if self.role == "main":                                          # 0.18.0: the ready hook after 5 s alive
            rt = threading.Timer(HOOK_READY_AFTER_S, self._ready_check, args=(gen,))
            rt.daemon = True
            rt.start()
        low = self.lowPub
        if low is not None and not low.running and not low.stopping:   # 0.18.0: the thumbnail sibling rides along
            low.relay = self.relay
            low.standby = False
            low.start()

    def _pump(self, gen, ff, mq):
        """0.21.85: a LISTED share's pair -- ffmpeg's MPEG-TS to the room's moq (every byte written before the next is read: the
        back-pressure of the direct pipe it replaces) and a copy to the library's (LibMirror, never in the room's way)."""
        src = ff.stdout
        lm = LibMirror(self, gen)
        self.libPipe = lm
        off = 0
        try:
            while True:
                try:
                    b = src.read(65536)
                except (OSError, ValueError):
                    break
                if not b:
                    break
                # 0.21.93: the room's moq of this moment -- an import restart (restart_import) swaps it; between two moqs the
                # bytes are dropped (ffmpeg and the sound loopback never wait), and a fresh moq starts at the next PAT
                # no swap in flight (or a stale generation's pump): the pair's own moq, as before 0.21.93
                if gen == self._gen and (self._mqDst is not None or self._reimp is not None):
                    dst = self._mqDst
                else:
                    dst = mq.stdin
                w = b
                if dst is not None and self._mqSync:
                    i = ts_pat_start(b, off)
                    if i is None:
                        w = None
                    else:
                        w = b[i:]
                        self._mqSync = False
                if dst is not None and w:
                    try:
                        mv = memoryview(w)
                        while mv:
                            n = dst.write(mv)
                            if not n:
                                raise OSError("short write")
                            mv = mv[n:]
                    except (OSError, ValueError):
                        if gen != self._gen or (self._reimp is None and (self._mqDst is dst or self._mqDst is None)):
                            break   # the room's moq is gone (not swapped): the pair ends, the watcher restarts it
                try:
                    lm.feed(b, off)
                except Exception as e:
                    self.bridge.log("rtsp: library copy of %s: %s" % (self.broadcast, e))
                off += len(b)
        finally:
            for f in (self._mqDst if gen == self._gen else None, mq.stdin, src):
                try:
                    if f is not None:
                        f.close()
                except Exception:
                    pass
            lm.close()

    def _hooks(self):
        return getattr(self.bridge, "hooks", None)

    def _ready_check(self, gen):
        if gen != self._gen or not self.running or self.stopping:
            return
        self._readyGen = gen
        h = self._hooks()
        if h:
            h.fire("ready", self.broadcast, self.feed.id, self.relay, reason="gen %d" % gen)

    def _notready(self, reason):
        if self._readyGen is None:
            return
        self._readyGen = None
        h = self._hooks()
        if h:
            h.fire("notready", self.broadcast, self.feed.id, self.relay, reason=reason)

    def _sleepy_eval(self):
        """0.21.73: encode only while watched -- a grid camera (wantIdle) whose pair ENCODES joins the demand loop: it runs
        a minute from now, then sleeps until a viewer's demand wakes it. A copying pair, an on-demand one (0.18.0 shape) or
        the switch off (sleep_unwatched = off) never sleeps this way."""
        was = self.sleepy
        self.sleepy = bool(self.role == "main" and self.wantIdle and SLEEP_UNWATCHED and self.copy is False and not self.ondemand)
        if self.sleepy:
            if self.wokeAt is None or not was:
                self.wokeAt = time.time()
            try:
                self.bridge._od_ensure()
            except Exception:
                pass
        return self.sleepy

    # ---- 0.18.0: on-demand standby -------------------------------------------------
    def wake(self, reason="demand", viewer=""):
        """A viewer wants an on-demand pair: leave standby and start it (and its low sibling)."""
        with self._lock:
            if self.stopping or not self.standby or self.suspended:   # 0.21.16: the demand loop cannot wake a switched-off camera (no 'woken' line, no read hook, standby kept for resume)
                return False
            self.standby = False
            self.wokeAt = time.time()
        self.bridge.log("rtsp: on-demand %s woken (%s)" % (self.broadcast, reason))
        h = self._hooks()
        if h:
            h.fire("read", self.broadcast, self.feed.id, self.relay, reason=reason, viewer=viewer)
        self.start()
        return True

    def sleep(self, reason="idle"):
        """Back to standby: stop the processes but keep the publisher (and its settings)."""
        with self._lock:
            if self.stopping or self.standby or not (self.ondemand or self.sleepy):   # 0.21.73: + an encoding grid camera
                return False
            self.standby = True
            self._gen += 1
            t, self._timer = self._timer, None
            r, self._renew = self._renew, None
            procs = self.procs
        for x in (t, r):
            if x:
                x.cancel()
        self.parked = False
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
            self.bridge._child_ended(p.pid)
        self.running = False
        self.bridge.log("rtsp: on-demand %s back to standby (%s)" % (self.broadcast, reason))
        self._notready("standby: " + reason)
        # 0.21.7: the low copy STAYS on the air in standby -- a viewer's click shows the picture at once (the tile
        # lives on the low copy) and the full pair replaces it when it is up. Cost per on-demand camera: one RTSP
        # pull and a 640p / 15 fps / ~400 kb/s encode. stop() still ends both.
        return True

    # ---- 0.21.16: the box's RTSP switch ------------------------------------------
    def suspend(self, reason="operator"):
        """Stop the processes and every timer, keep the publisher and its settings. Unlike sleep()
        this is unconditional (on-demand or not) and start() stays refused until resume(): the
        ladder, a park retry, a renew, a re-token, a nudge and a wake all land on the gate."""
        with self._lock:
            if self.stopping:
                return False
            was = self.running
            self.suspended = True
            self._gen += 1
            t, self._timer = self._timer, None
            r, self._renew = self._renew, None
            procs = self.procs
        for x in (t, r):
            if x:
                x.cancel()
        self.parked = False
        _end_pair(procs, self.bridge._child_ended)   # 0.21.16: ffmpeg first -- viewers lose the member broadcasts at once, not after the relay's idle timeout
        self.running = False
        self._notready("suspended: " + reason)
        if self.lowPub is not None:
            self.lowPub.suspend(reason)
        return was

    def resume(self, reason="operator"):
        """The switch is back on: a plain pair starts now; an on-demand pair returns to standby
        (Bridge.resume re-arms the demand loop and its low copy, the 0.18.0 shape)."""
        with self._lock:
            if self.stopping or not self.suspended:
                return False
            self.suspended = False
            t, self._timer = self._timer, None
        if t:
            t.cancel()
        if self.lowPub is not None:
            self.lowPub.suspended = False
        if self.ondemand:
            self.standby = True
            self.wokeAt = None
            return True
        self.standby = False   # 0.21.73: a camera asleep when the switch went off comes back on air (it sleeps again unwatched)
        self.wokeAt = time.time()
        self.start()
        return True

    def _drain(self, proc, tag, gen=0):
        try:
            for line in proc.stderr:
                text = line.decode("utf-8", "replace").strip()
                if text and tag == "ffmpeg" and PROGRESS_RE.match(text):   # 0.21.31: a -progress line, never an error
                    if text.startswith("frame=") and text[6:].isdigit() and gen == self._gen:   # 0.21.93: the video's own clock
                        n = int(text[6:])
                        self._vSeen = True
                        if n > self._vFrames:
                            self._vFrames = self.videoFrames = n
                            self.videoAt = time.time()
                        continue
                    if text.startswith("total_size=") and text[11:].isdigit() and gen == self._gen:
                        n = int(text[11:])
                        if n > self._outSize:
                            self._outSize = n
                            self.flowingAt = time.time()
                            if self.__dict__.get("_lq"):
                                self._lq_back()   # 0.21.91
                    continue
                if text and tag == "ffmpeg" and self.__dict__.get("_lvl"):   # 0.21.96: an rtsp:// reader's level-tagged line
                    text = rtsp_line(self.feed, self._reader(), self.__dict__.get("_transport"), text, bridge=self.bridge)
                if text:
                    text = _redact(re.sub(r"\x1b\[[0-9;]*m", "", text))   # 0.12.0: never a token
                    text = _redact_url(text)     # 0.13.3: ffmpeg prints the camera URL, credentials and all, on a connect error
                    self.errors.append(tag + ": " + text[-200:])
                    del self.errors[:-8]                                 # 0.13.1: was 4 -- the ffmpeg reason survives
                    self.error = " / ".join(self.errors)
                    if tag == "moq":
                        self._classify(gen, text)                        # 0.12.0
        except Exception:
            pass

    def _reader(self):
        """0.21.96: this pair's name on the feed's LossMeter."""
        return "low" if self.role == "low" else "pub"

    def _classify(self, gen, text):
        """0.12.0: what moq said about its relay session. A HARD line (refused
        token, reconnect loop gave up) is this generation's verdict -- _watch
        parks the pair instead of restarting it; SOFT lines are only counted."""
        if HARD_RE.search(text):
            if gen not in self._hard:
                self._hard[gen] = text[-160:]
                self.sessionKills += 1
            self.lastSession = text[-160:]
            self.lastSessionAt = time.time()                             # 0.13.3
        elif SOFT_RE.search(text):
            self.sessionFails += 1
            self.lastSession = text[-160:]
            self.lastSessionAt = time.time()                             # 0.13.3

    def _cur_mq(self, gen, mq):
        """0.21.93: this generation's moq of this moment (an import restart swaps it in procs)."""
        p = self.procs
        return p[1] if gen == self._gen and len(p) == 2 and p[0] is not None else mq

    def _watch(self, gen, ff, mq, drains=()):
        # whichever ends first ends the pair
        while True:
            m = self._cur_mq(gen, mq)
            if ff.poll() is not None:
                break
            if m.poll() is not None and self._reimp is None and self._cur_mq(gen, mq) is m:
                break   # 0.21.93: an old moq that an import restart is replacing is not the pair ending
            time.sleep(0.5)
            if self.stopping or gen != self._gen:
                return
            if self._stall_check(gen):   # 0.21.91: a frozen screen capture -- restarted (the restart ends this generation)
                return
        mq = self._cur_mq(gen, mq)
        # 0.13.1: who ended the pair (poll() = its exit code), before the
        # survivor is killed below
        rc = ff.poll()
        if rc is not None:
            who, code = "ffmpeg", rc
        else:
            who, code = "moq", mq.poll()
        for p in (ff, mq):
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
            self.bridge._child_ended(p.pid)   # 0.9.8
        # 0.12.0: stderr EOF arrives with the exit -- let the readers finish so
        # this generation's verdict (HARD refusal or not) is in before deciding
        for t in drains:
            try:
                t.join(1.0)
            except Exception:
                pass
        decision = None                 # 0.13.3: "park" | "ladder" | None, decided under the lock
        with self._lock:
            if gen != self._gen:
                return
            self.running = False
            lived = time.time() - (self.since or time.time())
            self.lastExit = {"code": code, "who": who, "at": time.time(), "lived": round(lived, 1)}   # 0.13.1
            # 0.13.3: the generation's obituary for launch.log -- with the ladder
            # position BEFORE the good-minute reset below (written after the lock)
            # 0.21.52 (field, Mendon: a camera exited every 10.5 s and the line ended with the moq tool's message): the line
            # names the process that exited -- its own last stderr line, and what its exit code means
            mine = [e for e in self.errors if e.startswith(who + ":")]
            why = (ffmpeg_exit_reason(code) if who == "ffmpeg" else "") or screen_exit_reason(getattr(self.feed, "url", ""), who, code)   # 0.21.91
            self.lastExit["reason"] = why
            exit_line = ("rtsp pair %s gen=%d exit who=%s code=%s%s lived=%.1fs restarts=%d sessionFails=%d sessionKills=%d last=%s"
                         % (self.broadcast, gen, who, code, (" (" + why + ")") if why else "", lived, self.restarts, self.sessionFails, self.sessionKills,
                            ((mine or self.errors)[-1] if (mine or self.errors) else "")[:160]))
            exit_r = -1 if lived > 60 else self.restarts                  # 0.21.91: -1 = it was working -- always logged
            if lived > 60:
                self.restarts = 0       # it was working; forget the past
            hard = self._hard.pop(gen, None)                              # 0.12.0
            if hard:
                self.needsToken = True
                self.lastFailAt = time.time()
            # 0.13.3: hard/ladder decided while the lock is held -- a nudge or
            # retoken racing this exit either moved _gen first (we returned above)
            # or finds our timer to cancel; no second pair can slip in between
            if not self.stopping:
                if hard:
                    decision = "park"   # 0.12.0: the same URL cannot help; wait for a fresh token
                else:
                    decision = "ladder"
                    self._schedule_restart_locked()
        self._lq_line(exit_line, exit_r, "exit")                          # 0.21.91
        self._notready("exit %s code %s" % (who, code))                  # 0.18.0
        if decision == "park":
            self._park()                # logs and may mint: never under the lock

    def _stall_check(self, gen, now=None):
        """0.21.91: the frozen-capture watchdog (see SCREEN_STALL_S) for this generation -- True when it restarts the capture.
        A screen share's main pair only; a paused share runs on its card and is watched the same way."""
        if (SCREEN_STALL_S <= 0 or self.role != "main" or not is_screen(getattr(self.feed, "url", "")) or self.stopping
                or gen != self._gen or not self.running or self.standby or self.suspended):
            return False
        now = time.time() if now is None else now
        last_out = max(self.since or now, self.flowingAt or 0)
        # 0.21.93: and the picture's own clock, once this generation reports it -- bytes alone keep flowing on sound
        last_vid = max(self.since or now, self.videoAt or 0) if self._vSeen else last_out
        last = min(last_out, last_vid)
        video_only = now - last_out < SCREEN_STALL_S <= now - last_vid
        if now - last < SCREEN_STALL_S:
            if self._stallRun and now - self._stallAt >= SCREEN_STALL_RESET_S:
                self._stallRun = 0
            return False
        if self.lastSessionAt and now - self.lastSessionAt < SCREEN_STALL_RELAY_S:
            return False   # moq is fighting its relay link (its own reconnects / the ladder handle that) -- not the capture
        if self._stallAt and now - self._stallAt < SCREEN_STALL_BACKOFF[min(self._stallRun, len(SCREEN_STALL_BACKOFF) - 1)]:
            return False
        self._stallRun += 1
        self.captureStalls += 1
        self._stallAt = now
        quiet = round(now - last, 1)
        self.lastCaptureStall = {"at": now, "quiet": quiet, "gen": gen, "paused": bool(self.paused), "rc": bool(self.rcmode),
                                 "kind": "video" if video_only else "output", "frames": self._vFrames}   # 0.21.93
        if video_only:   # 0.21.93: the field case -- the sound kept the output growing, the picture had stopped
            self.bridge.log("screen: share %s video stopped -- no new video frame for %.0f s while its sound kept flowing (frames flat "
                            "at %d, gen %d, ffmpeg still running) -- restarting the capture (freeze #%d)"
                            % (self.broadcast, quiet, self._vFrames, gen, self.captureStalls))
        else:
            self.bridge.log("screen: share %s capture froze -- no new picture for %.0f s (gen %d, ffmpeg still running, %s) -- "
                            "restarting the capture (freeze #%d)" % (self.broadcast, quiet, gen,
                                                                     "never streamed" if (self.flowingAt or 0) < (self.since or 0) else "streamed before",
                                                                     self.captureStalls))
        threading.Thread(target=self._stall_restart, name="kastr-capture-stall", daemon=True).start()
        return True

    def _stall_restart(self):
        """0.21.91: end the frozen pair ffmpeg-first (quiet: the relay drops the old broadcast at once, players move on) and
        start a fresh capture."""
        try:
            if self.quiet():
                self.nudge("capture-stall")
        except Exception as e:
            self.bridge.log("screen: share %s capture restart failed: %s" % (self.broadcast, e))

    def _lq_line(self, line, r, kind):
        """0.21.91: launch.log for a pair's start / exit line -- `r` = its try's place on the ladder (restarts; -1 = always)."""
        q = self.__dict__.get("_lq")
        if q is None:
            q = self.__dict__["_lq"] = {"n": 0, "lines": 0, "since": 0.0, "at": 0.0, "last": ""}
        if r < 0 or r == 0 or r == LOG_QUIET_AFTER - 1:
            self.bridge.log(line)
            if kind == "exit" and r == LOG_QUIET_AFTER - 1:
                self.bridge.log("rtsp pair %s: still failing after %d tries -- KASTR keeps retrying quietly (a summary every %d min)"
                                % (self.broadcast, LOG_QUIET_AFTER, LOG_QUIET_SUMMARY_S // 60))
            if kind == "exit" and r > 0:
                q["n"] += 1
            return
        now = time.time()
        q["lines"] += 1
        if kind != "exit":
            return
        q["n"] += 1
        q["last"] = line
        if not q["since"]:
            q["since"] = q["at"] = now
        if now - q["at"] >= LOG_QUIET_SUMMARY_S:
            q["at"] = now
            self.bridge.log("rtsp pair %s: still failing -- %d failed tries since %s, KASTR keeps retrying quietly (last: %s)"
                            % (self.broadcast, q["n"], time.strftime("%H:%M", time.localtime(q["since"])), line[-220:]))

    def _lq_back(self):
        """0.21.91: the pair streams (ffmpeg's output grew): a quiet stretch ends with one line, the count starts over."""
        q = self.__dict__.get("_lq")
        if not q or not (q["lines"] or q["n"]):
            return
        quiet = q["lines"]
        self.__dict__["_lq"] = None
        if quiet:
            self.bridge.log("rtsp pair %s gen=%d streaming again after %d failed tr%s" % (self.broadcast, self._gen, max(1, self.restarts), "y" if self.restarts == 1 else "ies"))

    def _schedule_restart_locked(self):
        """0.13.3: queue the next ladder step. The caller holds self._lock
        (threading.Lock is not reentrant -- never call this without it). One
        tick at a time: a queued ladder/park timer or a stopping pair -> no-op."""
        if self.stopping or self._timer is not None:
            return
        wait = PUBLISH_RETRY_S[min(self.restarts, len(PUBLISH_RETRY_S) - 1)]
        self.restarts += 1
        self.restartsTotal += 1                                           # 0.13.3
        t = threading.Timer(wait, self.start)
        t.daemon = True
        self._timer = t
        t.start()

    def restart_import(self, why="heal"):
        """0.21.93: restart only this pair's `moq import` -- a fresh relay session and announce of the same broadcast -- while
        ffmpeg (the capture, the encoder, the sound loopback) keeps running. The old moq gets EOF (its session closes and the
        relay withdraws the broadcast at once; killed after HEAL_SWAP_WAIT_S), the new one is fed from the next PAT. Needs the
        pump (every screen share's main pair has it). False = nothing to restart (not running, no pump, one in flight)."""
        with self._lock:
            if (self.stopping or not self.running or not self.pumped or self._reimp is not None or len(self.procs) != 2
                    or not self._mqArgv or self.standby or self.suspended):
                return False
            gen = self._gen
            ff, old = self.procs
            if ff.poll() is not None:
                return False
            self._reimp = {"gen": gen, "why": str(why or "")[:32], "at": time.time()}
            self._mqDst = None               # the pump drops bytes until the new moq is in
        threading.Thread(target=self._reimport_run, args=(gen, ff, old, why), daemon=True, name="kastr-import-restart").start()
        return True

    def _reimport_run(self, gen, ff, old, why):
        t0 = time.time()
        try:
            # EOF: moq ends its session, the relay withdraws the broadcast. Closed on a helper thread: a pump write blocked on a
            # wedged moq must not hold this up (the kill below breaks that write)
            threading.Thread(target=_close_quiet, args=(old.stdin,), daemon=True, name="kastr-import-eof").start()
            try:
                old.wait(timeout=HEAL_SWAP_WAIT_S)
                how = "closed"
            except Exception:
                how = "killed"
                try:
                    old.kill()
                    old.wait(timeout=2)
                except Exception:
                    pass
            self.bridge._child_ended(old.pid)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            with self._lock:
                if gen != self._gen or self.stopping or ff.poll() is not None:
                    self._reimp = None
                    return
                argv = list(self._mqArgv)
            try:
                mq = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                      creationflags=flags, bufsize=0)
            except OSError as e:
                self.bridge.log("rtsp import restart %s gen=%d failed: %s -- restarting the pair" % (self.broadcast, gen, e))
                with self._lock:
                    self._reimp = None
                if gen == self._gen and not self.stopping:
                    self.nudge("heal-import-failed")
                return
            self.bridge._child_started(mq, argv, [self.broadcast], "moq")
            d = threading.Thread(target=self._drain, args=(mq, "moq", gen), daemon=True)
            with self._lock:
                if gen != self._gen or self.stopping:
                    stale = True
                else:
                    stale = False
                    self.procs = (ff, mq)
                    self._mqSync = True
                    self._mqDst = mq.stdin
                    self.importRestarts += 1
                    try:
                        self._drains.append(d)
                    except Exception:
                        pass
                self._reimp = None
            if stale:
                try:
                    mq.kill()
                except OSError:
                    pass
                self.bridge._child_ended(mq.pid)
                return
            d.start()
            self.bridge.log("rtsp import restart %s gen=%d why=%s -- old moq %s %s, new moq %s in %.1f s (ffmpeg %s kept, frames %d; import restart #%d)"
                            % (self.broadcast, gen, why, old.pid, how, mq.pid, time.time() - t0, ff.pid, self._vFrames, self.importRestarts))
        except Exception as e:
            with self._lock:
                self._reimp = None
            self.bridge.log("rtsp import restart %s failed: %s" % (self.broadcast, e))

    def heal(self, why="viewer-video", now=None):
        """0.21.93: a viewer's report that this screen share's PICTURE stopped while its sound kept playing (see HEAL_GAP_S).
        Restarts the cheapest part that cures it: the moq import alone first, the whole pair when an import restart in the
        last HEAL_ESCALATE_S did not help. Rate-limited per share. Returns {"did": import|pair|limited|refused, ...}."""
        now = time.time() if now is None else now
        why = str(why or "viewer-video")[:32]
        refuse = ("not a screen share" if self.role != "main" or not is_screen(getattr(self.feed, "url", "")) else
                  "stopping" if self.stopping else "asleep" if self.standby else "switched off" if self.suspended else
                  "paused (its card has no sound -- not this stall)" if self.paused else
                  "not running (the ladder restarts it)" if not self.running else "")
        if refuse:
            self.heals["refused"] += 1
            self.lastHeal = {"at": now, "step": "refused", "why": why, "gen": self._gen, "reason": refuse}
            self.bridge.log("rtsp heal %s refused why=%s -- %s" % (self.broadcast, why, refuse))
            return {"did": "refused", "reason": refuse}
        hist = [t for t in self._healHist if now - t < HEAL_WINDOW_S]
        self._healHist = hist
        last = self.lastHeal if self.lastHeal and self.lastHeal.get("step") in ("import", "pair") else None
        limit = ""
        if hist and now - hist[-1] < HEAL_GAP_S:
            limit = "healed %.0f s ago (one per %d s)" % (now - hist[-1], HEAL_GAP_S)
        elif len(hist) >= HEAL_MAX:
            limit = "%d heals in the last %d min (at most %d)" % (len(hist), HEAL_WINDOW_S // 60, HEAL_MAX)
        if limit:
            self.heals["limited"] += 1
            self.bridge.log("rtsp heal %s limited why=%s -- %s" % (self.broadcast, why, limit))
            return {"did": "limited", "reason": limit}
        step = "import"
        if last and last["step"] == "import" and now - last["at"] < HEAL_ESCALATE_S:
            step = "pair"      # the moq-only restart did not bring the picture back
        if step == "import" and not self.restart_import(why):
            step = "pair"      # no pump / one in flight: the whole pair
        hist.append(now)
        self.heals[step] += 1
        self.lastHeal = {"at": now, "step": step, "why": why, "gen": self._gen}
        self.bridge.log("rtsp heal %s step=%s why=%s gen=%d frames=%d (heal %d in %d min; %s)"
                        % (self.broadcast, step, why, self._gen, self._vFrames, len(hist), HEAL_WINDOW_S // 60,
                           "moq import only, ffmpeg kept" if step == "import" else
                           "the import restart %.0f s ago did not help -- full pair restart" % (now - last["at"]) if last and last["step"] == "import" else
                           "full pair restart"))
        if step == "pair":
            threading.Thread(target=self._heal_pair, name="kastr-heal-pair", daemon=True).start()
        return {"did": step, "n": len(hist)}

    def _heal_pair(self):
        try:
            if self.quiet():
                self.nudge("heal")
        except Exception as e:
            self.bridge.log("rtsp heal %s pair restart failed: %s" % (self.broadcast, e))

    def quiet(self):
        """0.21.83 (D) (lab v02183: after a source switch the admin's player waited 4-20 s, sometimes for good): end the running
        pair ffmpeg FIRST (_end_pair: moq sees EOF, closes its session, the relay withdraws the broadcast at once) without the
        ladder restarting it -- the caller starts the next pair (nudge). A nudge alone kills moq outright and the relay keeps
        the dead publisher's broadcast announced until its idle timeout, which is where new subscribers kept landing."""
        with self._lock:
            if self.stopping:
                return False
            self._gen += 1            # the old pair's watcher returns without a ladder restart
            t, self._timer = self._timer, None
            procs = self.procs
        if t:
            t.cancel()
        _end_pair(procs, self.bridge._child_ended, grace=0.8)
        return True

    def nudge(self, why="api"):
        """A viewer says the stream is frozen: restart the pair now.
        0.13.1: `why` (viewer / stall* / no-echo / api) is counted and kept."""
        if self.standby or self.suspended:   # 0.18.0: nothing runs; a viewer's demand wakes it instead; 0.21.16: nor while the box's RTSP switch is off
            return
        bucket = nudge_bucket(why)
        if bucket == "viewer" and self.running and self.since and time.time() - self.since < 60:
            # 0.21.8: the 0.13.3 evidence rule on the server side too -- a viewer's stall report restarts nothing that came up
            # in the last minute (the page's gate no longer sends one for a running pair; older pages still might)
            self.nudges["refused"] = self.nudges.get("refused", 0) + 1
            self.lastNudgeWhy = ("refused:" + str(why or ""))[:32]
            self.lastNudgeAt = time.time()
            self.bridge.log("rtsp nudge refused %s why=%s -- the pair is %d s into gen %d (a viewer's report is not evidence)"
                            % (self.broadcast, why, int(time.time() - self.since), self._gen))
            return
        self.nudges[bucket] += 1
        self.lastNudgeWhy = str(why or "api")[:32]
        self.lastNudgeAt = time.time()
        with self._lock:
            t, self._timer = self._timer, None      # 0.12.0: a queued ladder/park tick must not double-start
            self._gen += 1
            procs = self.procs
        if t:
            t.cancel()
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
        self.running = False
        if not self.stopping:
            self.restarts += 1
            self.restartsTotal += 1                                       # 0.13.3
            self.start()

    # ---- 0.12.0: publishers that heal -----------------------------------
    # Parked = the relay refused our token (HARD), so restarting with the same
    # URL only hammers the camera and the relay. A parked pair does nothing
    # but: ask the minter for a fresh token (at most once a minute) and, when
    # that yields nothing, retry the old URL once every five minutes in case
    # the relay reopened. A page re-posting /api/rtsp/publish with a new
    # token (Bridge.publish -> retoken) ends the park at once.
    def _park(self):
        self.parked = True
        self._bareAt = time.time()      # the first bare retry is five minutes out, not now
        self.bridge.log("rtsp: publisher %s refused by the relay (%s) -- parked until a fresh token arrives"
                        % (self.broadcast, self.lastSession))
        self._park_tick()

    def _park_tick(self):
        if self.suspended:          # 0.21.16: a park decided by _watch just before suspend() must not tick (no minting, no bare retry, no restarts bump)
            return
        if self.stopping or not self.parked:
            return
        now = time.time()
        url = None
        if self.minter and now - self._mintAt >= 60:
            self._mintAt = now
            try:
                url = self.minter()
            except Exception as e:
                self.bridge.log("rtsp: publisher %s: token request failed: %s" % (self.broadcast, e))
            if url:
                self.retoken(url)
                return
        live_exp = _jwt_exp(_relay_token(self.relay))
        if now - self._bareAt >= 300 and not (live_exp and live_exp <= now):   # 0.21.58: an expired token is refused for ever
            self._bareAt = now
            with self._lock:
                self.parked = False
            self.restarts += 1
            self.start()                # bounded bare retry with the old URL
            return
        if live_exp and live_exp <= now and now - getattr(self, "_expSaidAt", 0) > 1800:
            self._expSaidAt = now
            self.bridge.log("rtsp: publisher %s: its room token ran out %d min ago and no fresh one could be minted -- "
                            "waiting for the minter (it asks every minute)" % (self.broadcast, (now - live_exp) // 60))
        with self._lock:
            if self.stopping or not self.parked:
                return
            t = threading.Timer(15, self._park_tick)
            t.daemon = True
            self._timer = t
            t.start()

    def retoken(self, relay):
        """A fresh relay URL (new token): move the pair onto it now."""
        relay = (relay or "").strip()
        if not relay or self.stopping:
            return
        if self.lowPub is not None:                                      # 0.18.0
            self.lowPub.relay = relay
        if self.standby:                                                 # 0.18.0: remember it for the next wake
            self.relay = relay
            self.needsToken = False
            self.parked = False
            return
        with self._lock:
            t, self._timer = self._timer, None
            self.relay = relay
            self.needsToken = False
            self.parked = False
            self._gen += 1
            procs = self.procs
        if t:
            t.cancel()
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
            self.bridge._child_ended(p.pid)
        self.running = False
        self.start()

    def _arm_renew(self):
        """Page-less boxes: renew the room token 15 minutes before it ends,
        through the minter. A page that re-posts meanwhile makes it a no-op."""
        with self._lock:
            t, self._renew = self._renew, None
        if t:
            t.cancel()
        if self.stopping or self.suspended or not self.minter or not self.tokenExp:   # 0.21.16: a suspend() landing between start()'s lock and this call leaves no renewal timer behind
            return
        t = threading.Timer(max(30, self.tokenExp - time.time() - 900), self._renew_tick)
        t.daemon = True
        with self._lock:
            self._renew = t
        t.start()

    def _renew_tick(self):
        if self.stopping:
            return
        # 0.21.58 (field: Linux sites stale after a weekend, "auth server refusals"): this used to read the expiry of
        # self.relay -- which a page re-post had ALREADY refreshed (Bridge.publish keeps a healthy pair running and only
        # swaps self.relay) -- saw a day left and re-armed, while moq kept dialling with the OLD token until the relay cut
        # it ("bad or expired token"). Now: the token the process actually runs with decides; a fresher one waiting in
        # self.relay is moved onto here, 15 minutes before the old one ends (one planned restart instead of a cut).
        now = time.time()
        live = _relay_token(self.relay)
        live_exp = _jwt_exp(live)
        if live and live != self.runToken and live_exp and live_exp - now > 900:
            self.bridge.log("rtsp: publisher %s: moving onto the fresher room token before the old one ends" % self.broadcast)
            self.retoken(self.relay)    # start() re-arms from it
            return
        exp = _jwt_exp(self.runToken) if self.runToken else live_exp
        if exp and exp - now > 900:
            self.tokenExp = exp
            self._arm_renew()
            return
        url = None
        now = time.time()
        if self.minter and now - self._mintAt >= 60:
            self._mintAt = now
            try:
                url = self.minter()
            except Exception as e:
                self.bridge.log("rtsp: publisher %s: token renewal failed: %s" % (self.broadcast, e))
        if url and _relay_token(url) != _relay_token(self.relay):
            self.bridge.log("rtsp: publisher %s: room token renewed" % self.broadcast)
            self.retoken(url)           # start() re-arms from the new token
            return
        with self._lock:
            if self.stopping:
                return
            t = threading.Timer(60, self._renew_tick)
            t.daemon = True
            self._renew = t
            t.start()

    def stop(self):
        self.stopping = True
        with self._lock:
            self._gen += 1
            t, self._timer = self._timer, None
            r, self._renew = self._renew, None      # 0.12.0
            procs = self.procs
        if t:
            t.cancel()
        if r:
            r.cancel()
        self.parked = False
        _end_pair(procs, self.bridge._child_ended)   # 0.9.8; 0.21.16: ffmpeg first -- moq ends its session on EOF, the relay unannounces at once
        self.running = False
        self._notready("stopped")                                        # 0.18.0
        if self.lowPub is not None:
            self.lowPub.stop()


PROGRESS_RE = re.compile(r"^[a-z0-9_]+=\s*\S*$")   # 0.21.31: ffmpeg -progress key=value lines (0.21.96: + stream_0_0_q=, "speed=   1x")


def _end_pair(procs, ended, grace=1.0):
    """0.21.16: end an ffmpeg|moq pair ffmpeg FIRST. moq reads the encoded stream from ffmpeg's stdout: with ffmpeg
    gone it sees EOF, closes its session and the relay withdraws the broadcast at once. Killing moq outright left the
    broadcast announced until the relay's idle timeout (~20 s measured), and viewers kept a dead tile that long.
    moq gets `grace` seconds, then it is killed like before. `ended(pid)` is Bridge._child_ended."""
    procs = list(procs or ())
    for p in procs[:1]:
        if p.poll() is None:
            try:
                p.kill()
                p.wait(timeout=1)   # 0.21.30: its input (a loopback port, a camera) is free when the next pair starts
            except Exception:
                pass
    deadline = time.time() + grace
    for p in procs[1:]:
        if p.poll() is None:
            try:
                p.wait(timeout=max(0.05, deadline - time.time()))
            except Exception:
                pass
        if p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass
    for p in procs:
        ended(p.pid)


def _ensure_exec(path):
    """Make sure a bundled helper is executable (no-op on Windows)."""
    if sys.platform == "win32":
        return
    try:
        import stat
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


class Feed:
    def __init__(self, feed_id, url, source_url=None):
        self.id = feed_id
        self.url = url                    # what ffmpeg pulls (post-resolve)
        self.source_url = source_url or url   # what the operator typed
        # One ffmpeg per open reader, not one per feed. A <video> element is
        # free to re-request its src -- Chrome does, routinely -- and holding a
        # single `proc` meant the second request overwrote the first, orphaning
        # a running child and leaving `running` reporting on a process nobody
        # was reading. That made this endpoint lie about feeds that were fine.
        self.procs = set()
        self.error = None
        self.errors = []
        self.h264 = None        # set by the first codec probe
        self.vcodec = None      # 0.9.2: the codec name itself ("h264", "hevc", ...)
        self.acodec = None      # 0.9.5: audio codec from the probe; "" = the camera has no audio track; None = not probed
        self.width = None       # source frame size, from the same probe
        self.height = None
        self.fullrange = None   # full-range source: must be converted
        self.sar = None         # 0.9.8: (num, den) sample aspect ratio from the probe; None = square/unknown
        self.probe_failed_at = None   # 0.12.0: when a codec probe could not tell (re-asked after PROBE_RETRY_S)
        self.xs = []                  # 0.21.75: the OTHER rooms this camera shows in (the bridge's xs loop lists it there)
        self.xs_codes = {}            # 0.21.75: room -> code of a locked target room (rtsp-feeds.json only; never sent to a page)
        self.xs_state = {}            # 0.21.75: room -> "ok" | why that room refused it (the page's row shows the reason)
        self.xs_gen = {}              # 0.21.91: room -> the generation of the room it was accepted in (a newer room never inherits it)
        self.xs_dropped = []          # 0.21.91: [{room, at, why}] -- rooms it left because they were deleted (the page says so once)
        self.lib = None               # 0.21.84: this camera's stream library switch (None = the box's default: on in no room)
        self.lib_aka = {}             # 0.21.84: its old paths (the room paths it had before the library) -> when it left them
        self.xs_auto = None           # 0.21.84: the room it was listed back into when it joined the library from that room
        self.base_broadcast = None    # 0.21.84: its ROOM path (what the page asks for; a library camera publishes at lib/...)
        self.lib_status = None        # 0.21.84: the relay's last word on its heartbeat ("ok" | why)
        self.lib_list = None          # 0.21.85: "In the stream library" -- LISTED there, kept in its room (None = this machine's default)
        self.transport = "auto"       # 0.21.96: Auto | TCP | UDP for an rtsp:// camera (rtsps:// is TCP whatever this says)
        self.tcp_refused = None       # 0.21.96: when the camera last refused a TCP SETUP (461 Unsupported Transport ...)
        self.udp_refused = None       # 0.21.96: ...or a UDP one
        self.loss = LossMeter()       # 0.21.96: what the RTSP demuxer said it lost, per reader

    def info(self):
        return {
            "id": self.id,
            "url": self.source_url,       # the operator's URL, not the resolved one
            "path": f"/rtsp/{self.id}",
            "running": any(p.poll() is None for p in list(self.procs)),
            "error": self.error,
            "acodec": self.acodec,        # 0.9.5
            "sar": ("%d:%d" % tuple(self.sar)) if self.sar else None,   # 0.9.8
            "xs": list(self.xs), "xsState": dict(self.xs_state), "xsLocked": sorted(self.xs_codes),   # 0.21.75 (never the codes)
            "xsDropped": list(getattr(self, "xs_dropped", None) or [])[-8:],   # 0.21.91: rooms it left because they were deleted
            "lib": self.lib,              # 0.21.84: its stream library switch (null = the box's default)
            "libList": self.lib_list,     # 0.21.85: listed in the library (null = on when this machine runs the relay)
            **transport_info(self),       # 0.21.96: transport, transportNow, transportWhy, tcpRefused, udpRefused, loss
        }


class Bridge:
    """Owns the set of RTSP feeds and their ffmpeg children."""

    def __init__(self, state_dir=None, log=None, host_slug=None):
        self._feeds = {}
        self._removed = []        # 0.21.0: [{url, at}] the operator closed -- restore() and adopt leave them alone
        self._next = 1
        # 0.13.0: this machine's host slug (kastr_serve.host_slug -- set by the
        # caller, this module cannot import kastr_serve); the minter scopes the
        # publishers' tokens to it. None -> wide (0.12-shaped) tokens.
        self.host_slug = host_slug
        self._lock = threading.Lock()
        self.ffmpeg = find_ffmpeg()
        self.moq = find_moq()            # 0.9.1: native publishing when present
        self._pubs = {}                  # feed id -> Publisher
        # 0.18.0: operator hooks (the launcher replaces these with kastr.ini's) and the
        # on-demand loop. `web_base_for(relay_url)` -> the relay host's KASTR base URL
        # (kastr_serve.make_bridge injects it); the demand loop asks it who is wanted.
        self.hooks = Hooks.from_env(log)
        self.web_base_for = None
        self._feed_locks = {}
        self._od_thread = None
        self._od_said = {}
        self.suspended = False  # 0.21.16: the box's RTSP switch (rtsp-feeds.json `suspended`; _load_session below reads it)
        self._encoder = None    # cached hardware-encoder choice
        self._probed = {}       # (url, transport) -> (h264, width, height, ...) -- 0.21.96: per transport
        self._transports = {}   # 0.21.96: source url -> "tcp" | "udp" (Auto, the default, is not stored)
        self.encoder_note = None  # which one, for the feed list
        # 0.9.8: children die with KASTR -- see _make_job / sweep_orphans
        self.state_dir = state_dir
        self.log = log or print
        self._job = app_job(self.log)
        self._children = {}              # pid -> record, mirrored to rtsp-children-<pid>.json
        self._children_lock = threading.Lock()
        self._media = set()              # 0.14.0: plain argv children (spawn_media), killed at shutdown
        # 0.12.0: the room the feeds belong to (+ its codes) and the feed list,
        # mirrored to rtsp-feeds.json so a relaunch can republish them
        self._persist_lock = threading.Lock()
        self._session = {"room": "", "access": "", "roomCode": "", "relay": ""}
        # 0.21.61: kept feeds read from rtsp-feeds.json that are not on the air (yet) -- written back by every
        # persist_feeds until they publish again or the operator removes / un-keeps them
        self._pending = []
        # 0.21.75: the cross-room listings this box keeps for its cameras (xs_tick)
        self._xs_listed = {}      # path -> {"rooms": set, "base", "minter", "room"} -- what was accepted (a stop goes there)
        self._xs_toks = {}        # (relay, room) -> (member token, exp)
        self._xs_bad = {}         # (relay, room) -> (access, code, status, why, at): a refused mint is not retried with the same codes
        self._xs_lock = threading.Lock()
        self._xs_thread = None
        self._xs_evt = threading.Event()
        self._xs_said = {}
        self.lib_master = True    # 0.21.84: the box's stream library switch (rtsp-feeds.json "library": "off" turns it off)
        self._load_session()
        if self.suspended:   # 0.21.16
            self.log("rtsp: publishing is SUSPENDED on this box (rtsp-feeds.json suspended=true) -- cameras are recorded, none starts until the switch is turned on")
        self.started_at = time.time()
        self.swept = 0
        try:
            self.swept = self.sweep_orphans()
        except Exception as e:
            self.log("rtsp: orphan sweep failed: %s" % e)
        try:
            self.swept += self.legacy_sweep()     # 0.9.10: leftovers from older versions, by path + parent
        except Exception as e:
            self.log("rtsp: legacy sweep failed: %s" % e)

    # ---- child lifetime (0.9.8) -----------------------------------------
    def _children_file(self, pid=None):
        if not self.state_dir:
            return None
        return os.path.join(self.state_dir, "rtsp-children-%d.json" % (pid or os.getpid()))

    def _write_children(self):
        path = self._children_file()
        if not path:
            return
        # One writer at a time: publishers start from several threads at once,
        # and two of them sharing one .tmp name collided on Windows ("Permission
        # denied" on the second open, "Access is denied" on the replace).
        with self._children_lock:
            recs = list(self._children.values())
            try:
                if not recs:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    return
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = "%s.%d.tmp" % (path, threading.get_ident())
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"owner": os.getpid(), "ownerStarted": self.started_at, "children": recs}, f)
                # 0.9.10: a scanner (Defender, the indexer) may hold the freshly
                # written file for a moment and the swap fails with "Access is
                # denied". Retry briefly, then write the tiny file in place -- the
                # next start tolerates an unreadable registry, an unwritten one it cannot.
                swapped = False
                for attempt in range(10):
                    try:
                        os.replace(tmp, path)
                        swapped = True
                        break
                    except PermissionError:
                        time.sleep(0.02 * (attempt + 1))
                if not swapped:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump({"owner": os.getpid(), "ownerStarted": self.started_at, "children": recs}, f)
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            except Exception as e:
                self.log("rtsp: could not write the child registry: %s" % e)

    def _child_started(self, proc, argv, sig, tag):
        """A child is ours: into the job (Windows) and the on-disk registry."""
        _job_assign(self._job, proc, self.log)
        try:
            rec = {"pid": proc.pid, "exe": argv[0] if argv else "",   # 0.21.92: a credential in the signature -> its digest
                   "sig": [kastr_secret.digest(str(x)) if kastr_secret.has_creds(str(x)) else str(x) for x in (sig or [])],
                   "started": time.time(), "tag": tag}
            with self._children_lock:
                self._children[proc.pid] = rec
        except Exception:
            return
        self._write_children()

    def _child_ended(self, pid):
        with self._children_lock:
            gone = self._children.pop(pid, None) is not None
        if gone:
            self._write_children()

    def registry(self):
        """Every rtsp-children-*.json in the state dir (for --diagnose)."""
        out = []
        if not self.state_dir or not os.path.isdir(self.state_dir):
            return out
        for fn in sorted(os.listdir(self.state_dir)):
            if fn.startswith("rtsp-children-") and fn.endswith(".json"):
                try:
                    with open(os.path.join(self.state_dir, fn), encoding="utf-8") as f:
                        out.append((fn, json.load(f)))
                except Exception as e:
                    out.append((fn, {"error": str(e)}))
        return out

    def helper_dirs(self):
        dirs = list(helper_roots())
        for p in (self.ffmpeg, self.moq):
            if p:
                dirs.append(os.path.dirname(p))
        seen, out = set(), []
        for d in dirs:
            k = os.path.normcase(os.path.realpath(d))
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out

    def legacy_sweep(self):
        """0.9.10: end bundled helpers whose parent KASTR is gone -- publisher
        pairs left by a pre-0.9.8 run, orphaned monitors, probes, a moq-relay
        holding port 4443. A second live KASTR (or the dev harness) keeps its
        helpers: their parent is alive and KASTR-like."""
        rows = helper_orphans(self.helper_dirs())
        counts = {}
        swept = 0
        for r in rows:
            if _kill_pid(r["pid"]):
                swept += 1
                stem = os.path.splitext(r["name"] or "")[0].lower()
                counts[stem] = counts.get(stem, 0) + 1
        if swept:
            self.log("rtsp: swept %d helper process(es) left by earlier KASTR runs (%s)" % (
                swept, ", ".join("%s x%d" % (k, v) for k, v in sorted(counts.items()))))
        return swept

    def sweep_orphans(self):
        """Kill the recorded children of every KASTR that is no longer running."""
        swept = 0
        # a registry write cut short by a hard exit leaves its .tmp behind
        if self.state_dir and os.path.isdir(self.state_dir):
            for fn in os.listdir(self.state_dir):
                if fn.startswith("rtsp-children-") and fn.endswith(".tmp"):
                    try:
                        os.remove(os.path.join(self.state_dir, fn))
                    except OSError:
                        pass
        for fn, doc in self.registry():
            path = os.path.join(self.state_dir, fn)
            try:
                owner = int(doc.get("owner") or fn[len("rtsp-children-"):-len(".json")])
            except (TypeError, ValueError):
                owner = 0
            if owner == os.getpid():
                continue
            if owner and _pid_alive(owner):
                # the owner may be another live KASTR (different build on another
                # port) -- or a reused PID. Its start time decides.
                alive = True
                try:
                    _, created, _ = _pid_image(owner)
                    if created is not None and doc.get("ownerStarted") and abs(created - float(doc["ownerStarted"])) > 5:
                        alive = False
                except Exception:
                    pass
                if alive:
                    continue
            for rec in doc.get("children") or []:
                try:
                    if _pid_matches(rec) and _kill_pid(rec["pid"]):
                        swept += 1
                except Exception:
                    continue
            try:
                os.remove(path)
            except OSError:
                pass
            self.log("rtsp: swept %d orphaned publisher process(es) left by KASTR pid %s" % (swept, owner))
        return swept

    def _hostmedia_ready(self, url):
        """0.21.26: media://<id> -> its file in <state>/hostmedia, copied there from the upload (<state>/media) once."""
        if not self.state_dir:
            return False
        HOSTMEDIA_DIR[0] = os.path.join(self.state_dir, "hostmedia")
        if hostmedia_path(url):
            return True
        mid = str(url)[len(MEDIA_PREFIX):].strip().lower()
        if not re.match(r"^[0-9a-f]{32}$", mid):
            return False
        src_dir = os.path.join(self.state_dir, "media")
        try:
            names = sorted(os.listdir(src_dir))
        except OSError:
            return False
        for fn in names:
            if fn.startswith(mid + ".") and re.match(r"^[0-9a-f]{32}\.[a-z0-9]{1,5}$", fn):
                import shutil
                os.makedirs(HOSTMEDIA_DIR[0], exist_ok=True)
                shutil.copy2(os.path.join(src_dir, fn), os.path.join(HOSTMEDIA_DIR[0], fn))
                return True
        return False

    def add(self, url):
        url = (url or "").strip()
        if self.state_dir and HOSTMEDIA_DIR[0] is None:
            HOSTMEDIA_DIR[0] = os.path.join(self.state_dir, "hostmedia")
        if not url:
            raise ValueError("no url given")
        self._removed = [r for r in self._removed if r.get("url") != url]   # 0.21.0: adding again is an explicit act
        # Only ever hand ffmpeg a stream URL, never a local path or shell text.
        # (Popen is given an argv list, so there is no shell to inject into, but
        # a file:// or local path would still let a page read arbitrary files.)
        if is_screen(url):   # 0.21.20: a native screen / window share -- validated and resolved by kastr_screen
            import kastr_screen
            kastr_screen.check_url(url)
        elif is_device(url):   # 0.21.26: a camera on this computer, captured once by the bridge
            if not device_name(url):
                raise ValueError("no camera name given")
            if not self.ffmpeg:
                raise ValueError("ffmpeg is not available here")
            if url not in DEVICES:
                cap = DEVICES[url] = DeviceCapture(self.ffmpeg, url, self.log)
                cap.start()
                time.sleep(1.5)   # the first packets reach the loopback ports before a reader opens them
        elif is_rtmp_in(url):   # 0.21.29: an RTMP ingest -- listen on its port for a device to push
            port, key = rtmp_parts(url)
            if not port:
                raise ValueError("bad RTMP ingest (port %d-%d and a key of 6-40 letters or digits)" % (RTMP_PORTS[0], RTMP_PORTS[-1]))
            if not self.ffmpeg:
                raise ValueError("ffmpeg is not available here")
            if url not in DEVICES:
                if port in rtmp_ports_in_use():
                    raise ValueError("RTMP port %d is already in use by another ingest" % port)
                cap = DEVICES[url] = DeviceCapture(self.ffmpeg, url, self.log)
                cap.start()
                self.log("rtsp: RTMP ingest listening on port %d" % port)
        elif is_hostmedia(url):   # 0.21.26: a media file uploaded to this host -- kept in <state>/hostmedia
            if not self._hostmedia_ready(url):
                raise ValueError("that media file is not on this computer (upload it again)")
        elif url != TEST_URL and not url.lower().startswith(
                ("rtsp://", "rtsps://", "http://", "https://")):
            raise ValueError("url must start with rtsp://, rtsps://, http:// or https://")
        # 0.9.3: a video PAGE (YouTube etc.) is refused with a clear reason;
        # direct media URLs, manifests and unknown hosts go to ffmpeg verbatim.
        source = url
        low = url.lower()
        if url != TEST_URL and low.startswith(("http://", "https://")):
            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if (not (parsed.path or "").lower().endswith(MEDIA_EXTS)
                    and any(h in host for h in PAGE_SITES)):
                raise ValueError("video pages (YouTube, Vimeo, Twitch...) are not supported -- "
                                 "use a direct media URL (.mp4, .m3u8...) or an RTSP camera")
        with self._lock:
            feed = Feed(self._next, url, source_url=source)
            feed.transport = getattr(self, "_transports", {}).get(source, "auto")   # 0.21.96: its Transport, kept per URL
            self._feeds[feed.id] = feed
            self._next += 1
        if is_screen(url):   # 0.21.20: a red border + a Stop sharing bar around what is shared (never in the capture)
            import kastr_screen
            fid = feed.id
            kastr_screen.overlay_start(fid, url, on_stop=lambda: (self.log("screen: Stop sharing on the bar"), self.remove(fid)))
        return feed

    def remove(self, feed_id):
        if is_private(self.get(feed_id)):   # 0.21.83 (D): the pill's Stop sharing on a fleet admin's private capture
            return self.remove_private(feed_id)
        self.unpublish(feed_id, persist=False)   # 0.12.0: one write, below
        with self._lock:
            feed = self._feeds.pop(int(feed_id), None)
        if feed and (is_device(feed.url) or is_rtmp_in(feed.url)):   # 0.21.26: the camera is free again; 0.21.29: the RTMP port too
            cap = DEVICES.pop(feed.url, None)
            if cap:
                cap.stop()
        if feed and is_hostmedia(feed.url):   # 0.21.26: its kept copy goes with it
            p = hostmedia_path(feed.url)
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass
        if feed and is_screen(feed.url):   # 0.21.20
            import kastr_screen
            kastr_screen.overlay_stop(feed.id)
        if feed:
            self.kill(feed)
            # 0.21.0: remember the closed URL -- a relaunch restore or a page adopt must not bring it back
            # (field report: "my KASTR keeps trying to use an RTSP feed that I keep closing out")
            url = getattr(feed, "source_url", None) or getattr(feed, "url", None)
            if url:
                self._pending_drop(url)   # 0.21.61
                self._removed = [r for r in self._removed if r.get("url") != url] + [{"url": url, "at": int(time.time())}]
                self._removed = self._removed[-50:]
        self.persist_feeds()                     # 0.12.0
        if feed and getattr(self, "_xs_listed", None):   # 0.21.75: its cross-room listings go now, not when they run out
            self.xs_poke()
        return bool(feed)

    # ---- 0.21.83 (D) (Kenton: "allow remote control with the admin permissions on a relay/hub/camera box ... opt-in
    # only"): a fleet admin's PRIVATE capture of this machine (kastr_rcadmin). A screen feed like any other -- the bridge
    # publishes it, Bridge.retarget re-points it (the source switcher), kastr_rc grants control of it -- but it is never
    # listed (/api/rtsp/list: the box's own page never adopts or shows it), never written to rtsp-feeds.json and never
    # remembered as "closed" when it ends (a later share of the same screen in a room is not blocked).
    def add_private(self, url, tag):
        url = str(url or "")
        if not is_screen(url):
            raise ValueError("a private capture is a screen or a window")
        import kastr_screen
        kastr_screen.check_url(url)
        with self._lock:
            feed = Feed(self._next, url, source_url=url)
            feed.private = str(tag or "private")
            self._feeds[feed.id] = feed
            self._next += 1
        kastr_screen.overlay_start(feed.id, url, on_stop=lambda fid=feed.id: (self.log("screen: Stop sharing on the bar of a private capture"),
                                                                                _rc_gone(fid, "bar")))
        self.log("rtsp: private capture %d of %s (%s)" % (feed.id, url, feed.private[:8]))
        return feed

    def remove_private(self, feed_id):
        with self._lock:
            feed = self._feeds.get(int(feed_id))
        if feed is None or not is_private(feed):
            return False
        self.unpublish(feed_id, persist=False)
        with self._lock:
            self._feeds.pop(int(feed_id), None)
        import kastr_screen
        kastr_screen.overlay_stop(int(feed_id))
        self.kill(feed)
        self.log("rtsp: private capture %d ended" % int(feed_id))
        return True

    # ---- native publishing (0.9.1) --------------------------------------
    def publish(self, feed_id, broadcast, relay, hevc=False, audio=True, passthrough=None, force=False, keep=None,
                ondemand=False, low=False, label="", idle=False):   # 0.12.0: keep; 0.18.0: ondemand, low, label; 0.21.73: idle
        # 0.18.0: one publish at a time per feed -- two quick option toggles on the page sent two
        # requests that raced, and the older one could land last
        with self._lock:
            fl = self._feed_locks.setdefault(int(feed_id), threading.Lock())
        with fl:
            return self._publish(feed_id, broadcast, relay, hevc, audio, passthrough, force, keep, ondemand, low, label, idle)

    def _publish(self, feed_id, broadcast, relay, hevc, audio, passthrough, force, keep, ondemand, low, label, idle=False):
        feed = self.get(feed_id)
        if not feed:
            raise ValueError("no such feed")
        if not self.moq:
            raise RuntimeError("moq-cli not available")
        rl = (relay or "").strip().lower()   # 0.18.0: was `low`, which shadowed the low-rendition flag
        if not rl.startswith(("http://", "https://", "ws://", "wss://")):
            raise ValueError("relay must be an http(s) or ws(s) url")
        if not re.match(r"^[A-Za-z0-9._~:@+\-]+(/[A-Za-z0-9._~:@+\-]+)*$", broadcast or ""):
            raise ValueError("bad broadcast name")
        # 0.21.84: the stream library -- the page asks for a camera's ROOM path; a camera in the library publishes at
        # lib/<host>/<op>/<leaf>.hang on a library publisher token instead (/api/rtsp/list says which: publish.broadcast,
        # publish.library). The relay's word is the one heard last (the library loop and restore ask it; never inline here).
        base = self._lib_base(feed, broadcast)
        self._boxout_carry(feed, base)   # 0.21.96: box-out -- a camera leaving a real room keeps showing there
        lib_on = False
        if self._lib_effective(feed, base, relay, fetch=False):
            lurl = self._lib_url(relay)
            if lurl:
                lib_on, broadcast, relay = True, lib_path_of(base), lurl
        if not lib_on and is_lib(broadcast) and not is_lib(base):
            broadcast = base
        feed.base_broadcast = base
        # 0.9.8: the same request twice is one publisher, not a restart. A page
        # that reloads (or adopts feeds the server already runs) asks for what
        # is already on air; answering with the running pair keeps viewers'
        # pictures up. Only the token part of the relay URL may differ.
        want_pt = bool(passthrough if passthrough is not None else hevc)
        cur = self._pubs.get(int(feed_id))
        if (cur is not None and not force and not cur.stopping
                and cur.broadcast == broadcast
                and _relay_key(cur.relay) == _relay_key(relay)
                and cur.passthrough == want_pt and cur.audio == bool(audio)
                and (not ONDEMAND_ENABLED or (cur.ondemand == bool(ondemand) and (cur.lowPub is not None) == bool(low)))):   # 0.18.0; 0.21.10: flags that have no effect never restart a pair
            # 0.12.0: evidence-gated re-token. A reload/rejoin mints a new token
            # but must NOT restart a healthy pair (the 0.9.8 promise). A pair the
            # relay refused, one that is down, one that failed within the last
            # minute or one whose token ends within 15 minutes takes it now.
            new_tok, old_tok = _relay_token(relay), _relay_token(cur.relay)
            now = time.time()
            if new_tok != old_tok and (not cur.running or cur.needsToken
                                       or (cur.lastFailAt and now - cur.lastFailAt < 60)
                                       or (cur.tokenExp and cur.tokenExp - now < 900)):
                cur.retoken(relay)
            else:
                cur.relay = relay.strip()      # the ladder's next start carries the live token
            if keep is not None and bool(keep) != cur.keep:
                cur.keep = bool(keep)
                self.persist_feeds()
            if label and label != cur.label:                             # 0.18.0: a renamed feed
                cur.label = str(label)[:80]
            if bool(idle) != cur.wantIdle and cur.role == "main":          # 0.21.73: joined / left a grid -- no restart
                cur.wantIdle = bool(idle)
                if cur.copy is not None and not cur._sleepy_eval() and cur.standby and not cur.ondemand:
                    cur.wake("no longer a grid camera")                    # out of the grid: on the air for good
                self.persist_feeds()
            cur.reused += 1
            return cur
        old_b, old_relay = (cur.broadcast, cur.relay) if cur is not None else (None, None)   # 0.21.84
        self.unpublish(feed_id, persist=False, lib_stop=False)   # 0.12.0: the new pair is persisted below
        pub = Publisher(self, feed, broadcast, relay.strip(), hevc=bool(hevc), audio=bool(audio),
                        passthrough=passthrough,
                        minter=(self._lib_minter(feed) if lib_on else self._minter_for(feed, broadcast, relay)),   # 0.12.0; 0.21.84
                        keep=(True if keep is None else bool(keep)),
                        ondemand=bool(ondemand), low=bool(low), label=label,    # 0.18.0
                        idle=bool(idle))                                         # 0.21.73
        with self._lock:
            self._pubs[int(feed_id)] = pub
        try:
            self._lib_after_publish(feed, old_b, old_relay, broadcast, lib_on, base)   # 0.21.84
        except Exception as e:
            self.log("rtsp: stream library bookkeeping for %s failed: %s" % (broadcast, e))
        if (pub.wantOndemand or pub.wantLow) and not ONDEMAND_ENABLED:   # 0.21.10
            self.log("rtsp: %s asked for on demand/low -- ignored (ondemand = off; kastr.ini ondemand = on or KASTR_ONDEMAND=1 allows it)" % broadcast)
        self._pending_drop(feed.source_url)   # 0.21.61: on the air again
        pub.suspended = bool(self.suspended)   # 0.21.16: born while the switch is off -> recorded, not started
        if pub.suspended:
            self.log("rtsp: %s recorded while publishing is suspended -- not started" % broadcast)
        elif pub.ondemand:
            self.log("rtsp: %s published on demand -- standby until a viewer asks" % broadcast)
            self._od_ensure()
            self._low_standby(pub)   # 0.21.7: click-to-picture -- the low copy runs while the full pair waits
        else:
            pub.start()
        self.persist_feeds()                     # 0.12.0
        return pub

    def _low_standby(self, pub):
        """0.21.7: start an on-demand pair's low copy while the full pair is in standby (Publisher.start does the same
        when the full pair wakes; sleep() leaves it running)."""
        low = getattr(pub, "lowPub", None)
        if low is None or low.running or low.stopping:
            return
        try:
            low.relay = pub.relay
            low.standby = False
            low.start()
            self.log("rtsp: %s low copy on the air in standby (click-to-picture)" % pub.broadcast)
        except Exception as e:
            self.log("rtsp: %s low copy did not start: %s" % (pub.broadcast, e))

    # ---- 0.18.0: the on-demand loop -------------------------------------------------
    OD_POLL_S = 5
    OD_IDLE_S = 60

    def _od_ensure(self):
        with self._lock:
            if self._od_thread is not None and self._od_thread.is_alive():
                return
            t = threading.Thread(target=self._od_loop, daemon=True, name="kastr-ondemand")
            self._od_thread = t
        t.start()

    def od_poke(self):
        """0.21.73: a viewer's demand reached this box's KASTR -- run the demand round now, not at the next 5 s tick."""
        ev = getattr(self, "_od_evt", None)
        if ev is not None:
            ev.set()

    def _od_loop(self):
        if getattr(self, "_od_evt", None) is None:
            self._od_evt = threading.Event()
        while True:
            pubs = [p for p in list(self._pubs.values()) if (p.ondemand or p.sleepy) and not p.stopping]   # 0.21.73: + sleepy
            if not pubs:
                with self._lock:
                    self._od_thread = None
                return
            try:
                self.od_tick(pubs)
            except Exception as e:
                self.log("rtsp: on-demand tick failed: %s" % e)
            self._od_evt.wait(self.OD_POLL_S)   # 0.21.73: a demand pokes it awake at once
            self._od_evt.clear()

    def od_tick(self, pubs, now=None, post=None):
        """One demand round: tell each relay host which on-demand feeds exist, learn which are
        wanted, wake/sleep accordingly. `post(url, body) -> dict|None` is injectable (tests).
        0.21.85: a LISTED share is synced at its library path too (with the library token) -- a viewer in the library wakes it."""
        now = now or time.time()
        post = post or self._od_post
        groups = {}
        for p in pubs:   # 0.21.84: per relay AND room -- ondemand_sync takes the room from the token
            groups.setdefault((_relay_key(p.relay), str(p.broadcast).split("/", 1)[0]), []).append((p, p.broadcast, p.relay))
            lm = _lib_mirror_of(p)
            if lm and not is_lib(p.broadcast):
                groups.setdefault((_relay_key(p.relay), LIB_ROOT), []).append((p, lm[0], lm[1]))
        for (key, _room), ps in groups.items():
            base = None
            try:
                base = self.web_base_for(key) if callable(self.web_base_for) else None
            except Exception:
                base = None
            wanted = None
            if base:
                body = {"token": _relay_token(ps[0][2]) or "",
                        "feeds": [{"broadcast": b, "label": p.label or b.rsplit("/", 1)[-1][:-5],
                                   "live": bool(p.running), "low": (p.lowPub.broadcast if (p.lowPub and b == p.broadcast) else None),
                                   "idle": bool(p.sleepy)} for p, b, _r in ps]}   # 0.21.73: asleep only while unwatched, whatever the host's ondemand switch
                d = post(base.rstrip("/") + "/api/ondemand/sync", body)
                if isinstance(d, dict) and isinstance(d.get("wanted"), dict):
                    wanted = d["wanted"]
            for p, b, _r in ps:
                if wanted is not None and b in wanted:
                    try:
                        age = max(0.0, float(wanted[b]))
                    except (TypeError, ValueError):
                        age = None
                    if age is not None:
                        p.wantedAt = max(p.wantedAt or 0, now - age)
        for p in pubs:
            recent = p.wantedAt is not None and now - p.wantedAt < self.OD_IDLE_S
            if p.standby and recent:
                p.wake("viewer demand")
            elif not p.standby and not recent and now - (p.wokeAt or 0) >= self.OD_IDLE_S:
                p.sleep("no viewer for %d s" % self.OD_IDLE_S)

    def _od_post(self, url, body):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=4) as r:
                return json.loads(r.read().decode("utf-8", "replace") or "{}")
        except Exception as e:
            last = self._od_said.get(url, 0)
            if time.time() - last > 600:
                self._od_said[url] = time.time()
                self.log("rtsp: on-demand sync with %s failed: %s" % (re.sub(r"\?.*", "", url), str(e)[:120]))
            return None

    def unpublish(self, feed_id, persist=True, lib_stop=True):   # 0.12.0: persist; 0.21.84: lib_stop
        with self._lock:
            pub = self._pubs.pop(int(feed_id), None)
        if pub:
            pub.stop()
            if lib_stop and _lib_mirror_of(pub) and not getattr(self, "_shutting", False):
                self.lib_poke()   # 0.21.85: a listed share is stopped in the library on the next round (now)
            if lib_stop and is_lib(pub.broadcast) and pub.role == "main" and not getattr(self, "_shutting", False):
                self._lib()["stop"].setdefault(pub.broadcast, ("", _relay_key(pub.relay)))   # 0.21.84: out of the library
                self.lib_poke()
            if persist:
                self.persist_feeds()
            if pub.broadcast in getattr(self, "_xs_listed", {}):   # 0.21.75: off the air -> out of the other rooms now
                self.xs_poke()
        if is_screen(getattr(pub.feed, "url", "") if pub else ""):   # 0.21.20: the red border goes with the share
            _rc_gone(feed_id, "share")   # 0.21.79: and remote control of it
            import kastr_screen
            kastr_screen.overlay_stop(int(feed_id))
        return bool(pub)

    # ---- 0.12.0: feed + session memory (rtsp-feeds.json) ------------------
    def _feeds_file(self):
        return os.path.join(self.state_dir, "rtsp-feeds.json") if self.state_dir else None

    def _read_feeds_file(self):
        path = self._feeds_file()
        if not path:
            return {}
        try:
            with open(path, encoding="utf-8-sig") as f:
                d = json.load(f)
            return kastr_secret.open_doc(path, d) if isinstance(d, dict) else {}   # 0.21.92: the sealed codes opened
        except Exception:
            return {}

    def _load_session(self):
        d = self._read_feeds_file()
        if d:
            self._session = {"room": str(d.get("room") or "").strip().lower(),
                             "access": str(d.get("access") or ""),
                             "roomCode": str(d.get("roomCode") or ""),
                             "relay": _relay_key(d.get("relay") or "")}
            if self._session["room"]:
                self._last_session = dict(self._session)   # 0.21.58
            self.suspended = d.get("suspended") is True   # 0.21.16: the switch survives a relaunch
            self.lib_master = d.get("library") != "off"   # 0.21.84: the box's stream library switch
            self._transports = {str(t.get("url")): str(t.get("mode")).strip().lower() for t in (d.get("transports") or [])
                                if isinstance(t, dict) and t.get("url")
                                and str(t.get("mode") or "").strip().lower() in ("tcp", "udp")}   # 0.21.96
            rem = d.get("removed")   # 0.21.0
            self._removed = [{"url": str(r.get("url")), "at": int(r.get("at") or 0)} for r in (rem or [])
                             if isinstance(r, dict) and r.get("url")][-50:]
            gone = {r["url"] for r in self._removed}
            self._pending = [dict(f) for f in (d.get("feeds") or []) if isinstance(f, dict) and f.get("url")
                             and f.get("keep", True) and str(f.get("url")) not in gone]   # 0.21.61

    def _feed_records(self):
        out = []
        for pub in list(self._pubs.values()):
            if pub.stopping or is_private(pub.feed):   # 0.21.83 (D): a private capture never comes back after a relaunch
                continue
            if is_screen(pub.feed.source_url):   # 0.21.26 (Kenton): a screen / window / tab share comes back after a relaunch
                ident = getattr(pub.feed, "screen_ident", None)
                if ident is None:
                    try:
                        import kastr_screen
                        ident = pub.feed.screen_ident = kastr_screen.identity(pub.feed.source_url)
                    except Exception:
                        ident = None
                out.append({"url": pub.feed.source_url, "broadcast": pub.broadcast, "audio": bool(pub.audio),
                            "keep": True, "label": pub.label, "screen": ident or {},
                            "addedBy": getattr(pub.feed, "added_by", "") or "", "room": getattr(pub.feed, "room", "") or ""})
                out[-1].update(_xs_fields(pub.feed))   # 0.21.75
                continue
            out.append({"url": pub.feed.source_url, "broadcast": getattr(pub.feed, "base_broadcast", None) or pub.broadcast,   # 0.21.84: the ROOM path
                        "audio": bool(pub.audio), "passthrough": bool(pub.passthrough), "keep": bool(pub.keep),
                        "ondemand": bool(pub.wantOndemand), "low": bool(pub.wantLow), "label": pub.label,   # 0.18.0; 0.21.10: what was ASKED -- preserved while the switch is off
                        "idle": bool(pub.wantIdle),                                                          # 0.21.73
                        "addedBy": getattr(pub.feed, "added_by", "") or "", "room": getattr(pub.feed, "room", "") or ""})   # 0.21.2: a web client's feed
            out[-1].update(_xs_fields(pub.feed))   # 0.21.75: the other rooms it shows in (+ locked rooms' codes; the file is owner-only)
            out[-1].update(_lib_fields(pub.feed))  # 0.21.84: its stream library switch, old paths, the room it was listed back into
        # 0.21.61: what has not come back yet stays on file (a failed or unfinished restore, a Join mid-restore)
        live = {r["url"] for r in out}
        gone = {r.get("url") for r in getattr(self, "_removed", [])}
        out += [dict(p) for p in getattr(self, "_pending", []) if p.get("url") not in live and p.get("url") not in gone]
        return out

    def _pending_drop(self, url):
        """0.21.61: this kept feed is back on the air (or the operator let it go) -- no longer pending."""
        self._pending = [p for p in self._pending if p.get("url") != url]

    def remote_add(self, url, room, label, op):
        """0.21.2: a web client (publisher token, verified by the caller) adds an RTSP camera that THIS host
        pulls, hardware-transcodes and publishes into `room` under <room>/<host>/<op>/<leaf>.hang -- the adder's
        op, so People files it under them. Needs the box's saved publisher code (its own room session) to mint
        the host's token for that room. -> feed.info() + publish, or raises ValueError with the reason."""
        if is_host_feed(url):   # 0.21.26: a camera or file on this computer -- only from the computer itself
            raise ValueError("a camera or media file on the host is added from the host itself")
        if is_screen(url):   # 0.21.20: a screen is shared only from the computer it shows -- never by a web client
            raise ValueError("a screen share starts only on the computer whose screen it is")
        room = str(room or "").strip().lower()
        op = re.sub(r"[^a-z0-9-]+", "-", str(op or "").lower()).strip("-")[:40] or "web"
        if not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", room):
            raise ValueError("bad room")
        ses = self._session
        if not ses.get("relay") or not ses.get("access"):
            raise ValueError("this host has no publisher code saved -- join a room from the host's KASTR once")
        enc = self.usable_encoder()
        if not enc or enc == "libx264":
            raise ValueError("this host has no hardware encoder")
        label = str(label or "").strip()[:40]
        leaf = re.sub(r"[^a-z0-9-]+", "-", (label or _rtsp_leaf(url)).lower()).strip("-")[:32] or "cam"
        status, tok_url, detail = mint_member(ses["relay"], room, ses.get("access", ""), "", host=self.host_slug)
        if status not in ("token", "open"):
            raise ValueError("the relay did not mint a token for room %s: %s (%s)" % (room, status, detail))
        feed = self.add(url)
        feed.added_by = op
        feed.room = room
        broadcast = "%s/%s/%s/%s.hang" % (room, self.host_slug, op, leaf)
        n = 2
        while any(p.broadcast == broadcast and p.feed is not feed for p in self._pubs.values()):
            broadcast = "%s/%s/%s/%s-%d.hang" % (room, self.host_slug, op, leaf, n); n += 1
        try:
            self.publish(feed.id, broadcast, tok_url, keep=True, label=label or _rtsp_leaf(url))
        except Exception:
            self.remove(feed.id)
            raise
        self.log("rtsp: web client %s added %s -> %s (hardware %s)" % (op, _redact_url(url), broadcast, enc))
        d = feed.info()
        d["publish"] = self.publication(feed.id)
        d["url"] = _redact_url(d.get("url"))
        return d

    def persist_feeds(self):
        """Write room + codes + the feeds on air. Atomic (tmp + replace), owner-only
        on POSIX (the access code is in it). Never called from shutdown(): the file
        must survive a relaunch so restore() can republish."""
        path = self._feeds_file()
        if not path:
            return False
        s = self._session
        relay = _relay_key(s.get("relay", ""))
        if not relay:                   # no session posted yet: the relay the pairs are on (token stripped)
            for pub in list(self._pubs.values()):
                if not pub.stopping:
                    relay = _relay_key(pub.relay)
                    break
        doc = {"room": s.get("room", ""), "access": s.get("access", ""), "roomCode": s.get("roomCode", ""),
               "relay": relay, "feeds": self._feed_records(), "at": time.time(),
               "removed": self._removed[-50:],   # 0.21.0: closed URLs stay closed across relaunches
               "suspended": bool(self.suspended),   # 0.21.16: the box's RTSP switch -- a relaunch honours it
               "library": "on" if getattr(self, "lib_master", True) else "off",   # 0.21.84: the box's stream library switch
               "transports": [{"url": u, "mode": m}                                  # 0.21.96: each camera's Transport
                              for u, m in list(getattr(self, "_transports", {}).items())[-200:]]}   # (url sealed like feeds/*/url)
        with self._persist_lock:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = "%s.%d.tmp" % (path, threading.get_ident())
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(kastr_secret.seal_doc(path, doc), f)   # 0.21.92: codes + camera passwords sealed
                if os.name != "nt":
                    os.chmod(tmp, 0o600)
                for attempt in range(10):       # a scanner may hold the file for a moment (see _write_children)
                    try:
                        os.replace(tmp, path)
                        break
                    except PermissionError:
                        if attempt == 9:
                            raise
                        time.sleep(0.02 * (attempt + 1))
                return True
            except Exception as e:
                self.log("rtsp: could not write the feed list: %s" % e)
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                return False

    def set_keep(self, feed_id, keep):
        pub = self._pubs.get(int(feed_id))
        if not pub:
            return False
        pub.keep = bool(keep)
        self._pending_drop(pub.feed.source_url)   # 0.21.61
        self.persist_feeds()
        return True

    def set_session(self, room, access="", room_code="", relay=""):
        """The page's room + access code (leaving = room ""). Publishers born
        before the session was known get their minter now."""
        self._session = {"room": str(room or "").strip().lower(), "access": str(access or ""),
                         "roomCode": str(room_code or ""), "relay": _relay_key(relay)}
        kastr_secret.remember(self._session["access"])     # 0.21.92: masked in every log line from now on
        kastr_secret.remember(self._session["roomCode"])
        if self._session["room"]:
            self._last_session = dict(self._session)   # 0.21.58: kept for the pairs when the page leaves
            for pub in list(self._pubs.values()):
                if pub.minter is None:
                    pub.minter = self._minter_for(pub.feed, pub.broadcast, pub.relay)
        self.persist_feeds()

    def session_public(self):
        """What the page may see: room, whether a code is saved, relay, the
        persisted feeds (credentials redacted) -- NEVER the codes."""
        s = self._session
        doc = self._read_feeds_file()
        feeds = doc.get("feeds") if isinstance(doc.get("feeds"), list) else None
        if feeds is None:
            feeds = self._feed_records()
        out = {"room": s.get("room", ""), "hasAccess": bool(s.get("access")), "relay": s.get("relay", ""),
               "feeds": [{"broadcast": str(f.get("broadcast") or ""), "keep": bool(f.get("keep", True)),
                          "url": _redact_url(str(f.get("url") or ""))} for f in feeds if isinstance(f, dict)]}
        out["suspended"] = bool(self.suspended)   # 0.21.16: the gate's hint can say the feeds are kept but switched off
        if doc.get("restoreError"):
            out["restoreError"] = str(doc["restoreError"])
        return out

    def session_seed(self):
        """0.14.0: the rescue seed -- what a browser profile that lost its
        storage needs to come back as this box, keyed like the page's
        localStorage: kastr.lastjoin, kastr.rtsp.persist, kastr.rtsp.history
        (each a JSON string, or None when there is nothing to seed).

        Feed URLs travel unredacted (they go loopback-only to the page that
        added them); the room's codes NEVER do -- lastjoin carries code ""
        and access "" (standing rule: access codes never leave the state file
        and are never echoed)."""
        doc = self._read_feeds_file()
        s = self._session
        room = str(doc.get("room") or s.get("room") or "").strip().lower()
        relay = _relay_key(doc.get("relay") or s.get("relay") or "")
        feeds = doc.get("feeds") if isinstance(doc.get("feeds"), list) else None
        if feeds is None:
            feeds = self._feed_records()
        persist, history = [], []
        for f in feeds:
            if not isinstance(f, dict):
                continue
            url = str(f.get("url") or "").strip()
            if not url or url.startswith("test://"):
                continue
            if url not in history:
                history.append(url)                 # rememberRtsp: every url added, newest first, 15 max
            if f.get("keep") is False or any(p["url"] == url for p in persist):
                continue
            persist.append({"url": url, "label": _seed_label(str(f.get("broadcast") or ""), url)})
        out = {"kastr.lastjoin": None, "kastr.rtsp.persist": None, "kastr.rtsp.history": None}
        if room:
            out["kastr.lastjoin"] = json.dumps({"room": room, "code": "", "access": "", "relay": relay,
                                                "micOn": False, "vidOn": False})
        if persist:
            out["kastr.rtsp.persist"] = json.dumps(persist)
        if history:
            out["kastr.rtsp.history"] = json.dumps(list(reversed(history))[:15])
        return out

    def _minter_for(self, feed, broadcast, relay=""):
        """A fresh room token for one publisher via the relay's minter, from
        the session (room + access code). None when no room is known. The
        callable returns the tokened URL ("token"), the bare URL ("open") or
        None (refused / down), logging each new refusal reason once."""
        if not self._session.get("room") and not (getattr(self, "_last_session", None) or {}).get("room"):
            return None
        fid = feed.id
        last = [None]

        def mint():
            ses = self._session
            if not ses.get("room"):
                # 0.21.58: the page left its room (Leave posts room "") -- its kept cameras still publish there, and a
                # parked one used to wait for a token for ever; the last room the page was in still mints for them
                ses = getattr(self, "_last_session", None) or {}
                if not ses.get("room"):
                    return None
            cur = self._pubs.get(fid)
            base = ses.get("relay") or _relay_key(cur.relay if cur is not None else relay)
            room = getattr(feed, "room", "") or ses["room"]   # 0.21.2: a web client's feed lives in ITS room
            status, url, detail = mint_member(base, room, ses.get("access", ""), ses.get("roomCode", "") if room == ses.get("room") else "",
                                              host=self.host_slug)     # 0.13.0
            # 0.13.2: "open" because the minter did not answer is not a licence to go bare: a publisher
            # that had a token keeps waiting for one (a secured relay severs a bare dial with code=6).
            if status == "open" and "no minter" in str(detail) and cur is not None and "jwt=" in str(cur.relay or ""):
                status, detail = "down", "minter not answering (keeping the token)"
            if status in ("token", "open"):
                last[0] = None
                return url
            why = "%s (%s)" % (status, detail)
            if why != last[0]:
                last[0] = why
                self.log("rtsp: publisher %s could not get a token for room %s: %s" % (broadcast, ses["room"], why))
            return None
        return mint

    def _feed_by_source(self, url):
        for f in list(self._feeds.values()):
            if f.source_url == url:
                return f
        return None

    def restore(self, mint=None, log=None):
        """Republish the persisted feeds (keep=true) into the saved room at
        launch. `mint()` -> the relay URL to publish on (?jwt= on a secured
        relay, bare on an open one) or None; the caller has already waited for
        the relay to answer. Publishes run in parallel (each may probe its
        camera for up to PROBE_TIMEOUT). Returns how many came back."""
        log = log or self.log
        doc = self._read_feeds_file()
        room = str(doc.get("room") or "").strip().lower()
        gone = {str(r.get("url")) for r in (doc.get("removed") or []) if isinstance(r, dict) and r.get("url")}   # 0.21.0
        feeds = [f for f in (doc.get("feeds") or [])
                 if isinstance(f, dict) and f.get("url") and f.get("keep", True) and str(f.get("url")) not in gone]
        if not room or not feeds:
            return 0
        self._session = {"room": room, "access": str(doc.get("access") or ""),
                         "roomCode": str(doc.get("roomCode") or ""), "relay": _relay_key(doc.get("relay") or "")}
        url = None
        try:
            url = mint() if mint else (self._session["relay"] or None)
        except Exception as e:
            log("rtsp restore: minting a token failed: %s" % e)
        if not url:
            log("rtsp restore: no relay url for room %s -- %d feed(s) not republished" % (room, len(feeds)))
            return 0
        if LIBRARY_ENABLED and getattr(self, "lib_master", True):   # 0.21.84: ask the relay about the library ONCE, before the
            try:                                                   # cameras start (a no-room box's go straight to lib/)
                self._lib_cap(url)
            except Exception:
                pass
        done = [0]
        lock = threading.Lock()

        def one(rec):
            try:
                if is_screen(rec.get("url") or ""):   # 0.21.26: still there? (a closed window / tab is dropped, not retried)
                    import kastr_screen
                    now_url = kastr_screen.relocate(rec["url"], rec.get("screen"))
                    if not now_url:
                        what = (rec.get("screen") or {}).get("title") or rec.get("label") or rec["url"]
                        log("rtsp restore: %s share '%s' is no longer there -- dropped" % ((rec.get("screen") or {}).get("kind") or "screen", what))
                        self._pending_drop(rec["url"])   # 0.21.61
                        return
                    if now_url != rec["url"]:
                        log("rtsp restore: %s found again as %s" % (rec["url"], now_url))
                    rec = dict(rec, url=now_url)
                feed = self._feed_by_source(rec["url"]) or self.add(rec["url"])
                if isinstance(rec.get("xs"), list) and not getattr(feed, "xs", None):   # 0.21.75: the rooms it showed in
                    feed.xs = [str(r) for r in rec["xs"] if _XS_ROOM_RE.match(str(r)) and not is_home_room(r)][:XS_ROOMS_MAX]
                    codes = rec.get("xsCodes") if isinstance(rec.get("xsCodes"), dict) else {}
                    feed.xs_codes = {str(r): str(c) for r, c in codes.items() if str(r) in feed.xs and c}
                    gens = rec.get("xsGen") if isinstance(rec.get("xsGen"), dict) else {}   # 0.21.91
                    feed.xs_gen = {str(r): str(g)[:24] for r, g in gens.items() if str(r) in feed.xs and g}
                if rec.get("lib") in (True, False) and getattr(feed, "lib", None) is None:   # 0.21.84: its library switch, old paths
                    feed.lib = rec["lib"]
                if isinstance(rec.get("libAka"), dict) and not getattr(feed, "lib_aka", None):
                    feed.lib_aka = {str(k): int(v) for k, v in rec["libAka"].items() if isinstance(v, (int, float))}
                if rec.get("xsAuto") and not getattr(feed, "xs_auto", None):
                    feed.xs_auto = str(rec["xsAuto"])
                if rec.get("libList") in (True, False) and getattr(feed, "lib_list", None) is None:   # 0.21.85: listed in the library
                    feed.lib_list = rec["libList"]
                rurl = url
                if rec.get("room") and rec.get("room") != room:   # 0.21.2: a web client's feed in another room
                    feed.added_by = str(rec.get("addedBy") or ""); feed.room = str(rec.get("room"))
                    st, u2, det = mint_member(self._session["relay"], rec["room"], self._session.get("access", ""), "", host=self.host_slug)
                    if st not in ("token", "open"):
                        raise RuntimeError("no token for room %s: %s (%s)" % (rec["room"], st, det))
                    rurl = u2
                self.publish(feed.id, rec.get("broadcast") or ("cam%d" % feed.id), rurl,
                             audio=(rec.get("audio") is not False), passthrough=bool(rec.get("passthrough")), keep=True,
                             ondemand=bool(rec.get("ondemand")), low=bool(rec.get("low")), label=str(rec.get("label") or ""),   # 0.18.0
                             idle=bool(rec.get("idle")))   # 0.21.73
                with lock:
                    done[0] += 1
            except Exception as e:
                log("rtsp restore: %s -> %s failed: %s -- kept for the next launch" % (_redact_url(str(rec.get("url"))), rec.get("broadcast"), e))   # 0.21.61
        threads = [threading.Thread(target=one, args=(r,), daemon=True) for r in feeds]
        for t in threads:
            t.start()
        deadline = time.time() + 30
        for t in threads:
            t.join(max(0.1, deadline - time.time()))
        log("rtsp: %s %d persisted feed(s) into room %s" % ("recorded (publishing suspended)" if self.suspended else "republished", done[0], room))   # 0.21.16
        self.persist_feeds()
        if self._lib_wanted():   # 0.21.84: the library heartbeat (and the move of cameras its relay now serves)
            self.lib_poke()
        if self._xs_wanted():   # 0.21.75: the cameras' other rooms come back with them (the loop lists them now and every minute)
            self._xs_ensure()
            self.xs_poke()
        return done[0]

    # ---- 0.21.75 (Kenton: boxes "share without being in a room" -- each camera picks the rooms it shows in) -----------
    # The box server owns the listings: every XS_TICK_S each live main pair with rooms is POSTed to its relay's minter
    # (/api/xshare: Bearer = a member token of the pair's own room minted for this host, `tokens` = one member token per
    # target room, minted with the box's saved access code and, for a locked room, the code kept in rtsp-feeds.json);
    # a room dropped, a camera removed / unpublished / switched off is withdrawn (stop) on the next round.
    def set_xs(self, feed_id, rooms, codes=None):
        """POST /api/rtsp/xs {id, rooms, codes?}: exactly these other rooms for one camera (persisted), listed at once.
        -> {ok, id, xs, xsState, xsLocked} (never a code)."""
        try:
            feed = self.get(feed_id)
        except (TypeError, ValueError):
            feed = None
        if feed is None:
            raise ValueError("no such feed")
        if not isinstance(rooms, list):
            raise ValueError("rooms must be a list")
        pub = self._pubs.get(int(feed.id))
        own = (pub.broadcast.split("/", 1)[0] if pub is not None else "") or getattr(feed, "room", "") or self._session.get("room", "")
        out = []
        for r in rooms:
            r = str(r or "").strip().lower()
            if not _XS_ROOM_RE.match(r):
                raise ValueError("bad room name")
            if r == LIB_ROOT:
                raise ValueError("lib is the stream library, not a room")   # 0.21.84
            if r == own or r in out:   # its own room (the box's home too) and doubles drop out
                continue
            if is_home_room(r):
                raise ValueError("%s is a box's own room" % r)
            out.append(r)
        if len(out) > XS_ROOMS_MAX:
            raise ValueError("a camera shows in at most %d other rooms" % XS_ROOMS_MAX)
        old = dict(getattr(feed, "xs_codes", None) or {})
        keep = {r: old[r] for r in out if old.get(r)}
        for r, c in ((codes or {}).items() if isinstance(codes, dict) else []):
            r = str(r or "").strip().lower()
            if r in out and str(c or "").strip():
                keep[r] = str(c)[:128]
                for k in [k for k in self._xs_bad if k[1] == r]:   # a new code is tried at once
                    self._xs_bad.pop(k, None)
        feed.xs, feed.xs_codes = out, keep
        feed.xs_state = {r: v for r, v in (getattr(feed, "xs_state", None) or {}).items() if r in out}
        feed.xs_gen = {r: g for r, g in (getattr(feed, "xs_gen", None) or {}).items() if r in out}   # 0.21.91: a room picked again is learned anew
        self.persist_feeds()
        self.log("rtsp: %s shows in %s" % (pub.broadcast if pub is not None else "feed %s" % feed.id, ", ".join(out) or "its own room only"))
        try:
            self.xs_tick()
        except Exception as e:
            self.log("rtsp: cross-room listing failed: %s" % e)
        if self._xs_wanted():
            self._xs_ensure()
        return {"ok": True, "id": feed.id, "xs": list(feed.xs), "xsState": dict(feed.xs_state), "xsLocked": sorted(feed.xs_codes)}

    def _xs_wanted(self):
        if getattr(self, "_xs_lock", None) is None:   # (a bridge built without __init__ -- tests)
            return False
        return bool(self._xs_listed) or any(isinstance(getattr(f, "xs", None), list) and f.xs for f in list(self._feeds.values()))

    def _xs_ensure(self):
        with self._lock:
            if self._xs_thread is not None and self._xs_thread.is_alive():
                return
            t = threading.Thread(target=self._xs_loop, daemon=True, name="kastr-xshare")
            self._xs_thread = t
        t.start()

    def xs_poke(self):
        """Run the listing round now (a room dropped, a camera gone) -- the loop starts if it is not running."""
        if self._xs_wanted():
            self._xs_ensure()
        self._xs_evt.set()

    def _xs_air(self, now):
        """0.21.76: which listed cameras are on the air right now (a change runs a listing round at once)."""
        return frozenset(p.broadcast for p in list(self._pubs.values())
                         if getattr(p.feed, "xs", None) and p.role == "main" and xs_on_air(p, now))

    def _xs_loop(self):
        last, air = 0.0, None
        while True:
            if not self._xs_wanted():
                with self._lock:
                    self._xs_thread = None
                return
            now = time.time()
            cur = self._xs_air(now)
            if self._xs_evt.is_set() or cur != air or now - last >= XS_TICK_S:   # 0.21.76: a camera started / stopped streaming
                self._xs_evt.clear()
                air, last = cur, now
                try:
                    self.xs_tick()
                except Exception as e:
                    self.log("rtsp: cross-room listing round failed: %s" % e)
            self._xs_evt.wait(XS_AIR_CHECK_S)

    def _xs_token(self, base, room, access, code, mint, now):
        """-> (status, member token or "" (an open relay), why). Cached until XS_TOKEN_MIN_S before it ends; a mint the
        relay REFUSED is not retried with the same codes (a wrong code must not lock the box out), a down one after 60 s."""
        key = (base, room)
        hit = self._xs_toks.get(key)
        if hit and hit[1] - now > XS_TOKEN_MIN_S:
            return "token", hit[0], ""
        bad = self._xs_bad.get(key)
        if bad and bad[0] == access and bad[1] == code and (bad[2] == "refused" or now - bad[4] < 60):
            return bad[2], None, bad[3]
        st, url, det = mint(base, room, access, code)
        if st == "token":
            tok = _relay_token(url)
            self._xs_toks[key] = (tok, _jwt_exp(tok) or (now + 3600))
            self._xs_bad.pop(key, None)
            return "token", tok, ""
        if st == "open":
            return "open", "", ""
        why = str(det or st)[:80]
        if st == "refused" and not code and re.search(r"room code|locked", why, re.I):
            why = "locked -- enter its code"
        self._xs_bad[key] = (access, code, st, why, now)
        return st, None, why

    def _xs_post(self, url, body, bearer):
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=headers)
            with urllib.request.urlopen(req, timeout=6) as r:
                return json.loads(r.read().decode("utf-8", "replace") or "{}"), (getattr(r, "status", None) or 200)
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8", "replace") or "{}"), e.code
            except Exception:
                return None, e.code
        except Exception as e:
            if time.time() - self._xs_said.get(url, 0) > 600:
                self._xs_said[url] = time.time()
                self.log("rtsp: cross-room listing at %s failed: %s" % (re.sub(r"[?].*", "", url), str(e)[:120]))
            return None, 0

    def _xs_follow(self, feed, ren, path, now=None):
        """0.21.91: rooms the relay says were RENAMED ({old: new}) -- the camera's rooms follow (its code and generation move with
        the name), persisted; the new name is listed on the next round (at once: xs_poke)."""
        now = time.time() if now is None else now
        own = path.split("/", 1)[0]
        xs = list(getattr(feed, "xs", None) or [])
        moved = {}
        for old, new in ren.items():
            if old not in xs or not _XS_ROOM_RE.match(new) or new == LIB_ROOT or is_home_room(new):
                continue
            i = xs.index(old)
            if new in xs or new == own:
                xs.pop(i)                     # already shown there (or it is its own room now): the old name just goes
            else:
                xs[i] = new
            moved[old] = new
            for attr in ("xs_codes", "xs_gen"):
                m = getattr(feed, attr, None)
                if isinstance(m, dict) and old in m:
                    v = m.pop(old)
                    if new not in m and new != own:
                        m[new] = v
            if isinstance(getattr(feed, "xs_state", None), dict):
                feed.xs_state.pop(old, None)
            if getattr(feed, "xs_auto", None) == old:
                feed.xs_auto = new
        if not moved:
            return {}
        feed.xs = xs
        dropped = list(getattr(feed, "xs_dropped", None) or [])
        dropped += [{"room": o, "to": n, "at": int(now), "why": "renamed"} for o, n in moved.items()]
        feed.xs_dropped = dropped[-8:]
        rec = self._xs_listed.get(path)
        if rec:
            rec["rooms"] -= set(moved)
            if not rec["rooms"]:
                self._xs_listed.pop(path, None)
        self.persist_feeds()
        self.log("rtsp: %s follows renamed room(s) %s" % (path, ", ".join("%s -> %s" % kv for kv in moved.items())))
        self._xs_evt.set()   # the next round lists it under the new name (the loop runs again at once)
        return moved

    def _xs_forget(self, feed, rooms, path, now=None):
        """0.21.91: rooms the relay says were DELETED -- out of this camera's rooms (and their codes and generations), persisted,
        and kept in xs_dropped so the page tells the person once."""
        now = time.time() if now is None else now
        rooms = [r for r in rooms if r in (getattr(feed, "xs", None) or [])]
        if not rooms:
            return []
        feed.xs = [r for r in feed.xs if r not in rooms]
        for attr in ("xs_codes", "xs_gen", "xs_state"):
            m = getattr(feed, attr, None)
            if isinstance(m, dict):
                for r in rooms:
                    m.pop(r, None)
        if getattr(feed, "xs_auto", None) in rooms:
            feed.xs_auto = None
        dropped = list(getattr(feed, "xs_dropped", None) or [])
        dropped += [{"room": r, "at": int(now), "why": "deleted"} for r in rooms]
        feed.xs_dropped = dropped[-8:]
        rec = self._xs_listed.get(path)
        if rec:
            rec["rooms"] -= set(rooms)
            if not rec["rooms"]:
                self._xs_listed.pop(path, None)
        self.persist_feeds()
        self.log("rtsp: %s no longer shown in %s -- the room was deleted (removed from this camera's rooms)" % (path, ", ".join(rooms)))
        return rooms

    def xs_tick(self, now=None, post=None, mint=None):
        """One round. `post(url, body, bearer) -> (dict | None, http code)` and `mint(relay, room, access, room_code) ->
        (status, url, detail)` (mint_member's shape) are injectable (tests). -> {path: {room: "ok" | why}}."""
        now = time.time() if now is None else now
        post = post or self._xs_post
        mint = mint or (lambda base, room, access, code: mint_member(base, room, access, code, host=self.host_slug))
        with self._xs_lock:
            ses = self._session if self._session.get("room") else (getattr(self, "_last_session", None) or self._session)
            access = str(ses.get("access") or "")
            want = {}
            if not self.suspended:
                for pub in list(self._pubs.values()):
                    rooms = getattr(pub.feed, "xs", None)
                    rooms = list(rooms) if isinstance(rooms, list) else []
                    if rooms and not pub.stopping and not pub.suspended and pub.role == "main":
                        if xs_on_air(pub, now):
                            want[pub.broadcast] = (pub, rooms)
                        else:   # 0.21.76: not streaming -- withdrawn below, shown again as soon as data flows
                            pub.feed.xs_state = {r: "not streaming now \u2014 shown when it is" for r in rooms}
            out = {}
            for path, rec in list(self._xs_listed.items()):   # withdrawals first: a dropped room, a camera gone or off
                drop = sorted(rec["rooms"] - (set(want[path][1]) if path in want else set()))
                if drop:
                    room = rec["room"]
                    st, tok, _w = self._xs_htok(rec["base"], room, access, ses.get("roomCode", "") if room == ses.get("room") else "", mint, now)   # 0.21.84
                    if st in ("token", "open"):
                        post(rec["minter"] + "/api/xshare", {"path": path, "to": drop, "stop": True}, tok)
                    rec["rooms"] -= set(drop)   # (a stop that did not land runs out with the listing's ttl)
                    self.log("rtsp: %s no longer shown in %s" % (path, ", ".join(drop)))
                if not rec["rooms"]:
                    self._xs_listed.pop(path, None)
            for path, (pub, rooms) in want.items():
                state = {}
                base = _relay_key(ses.get("relay") or "") or _relay_key(pub.relay)
                parts, why = _relay_base(base)
                room = path.split("/", 1)[0]
                if not parts:
                    state = {r: "no relay (%s)" % why for r in rooms}
                else:
                    minter = parts[1]
                    st, htok, hwhy = self._xs_htok(base, room, access, ses.get("roomCode", "") if room == ses.get("room") else "", mint, now)   # 0.21.84: lib -> the library token
                    if st not in ("token", "open"):
                        state = {r: "no token for %s (%s)" % (room, hwhy) for r in rooms}
                    else:
                        toks = {}
                        for r in rooms:
                            s2, t2, w2 = self._xs_token(base, r, access, (getattr(pub.feed, "xs_codes", None) or {}).get(r, ""), mint, now)
                            if s2 in ("token", "open"):
                                toks[r] = t2
                            else:
                                state[r] = w2
                        to = [r for r in rooms if r in toks]
                        if to:
                            segs = path.split("/")
                            body = {"path": path, "to": to, "tokens": {r: t for r, t in toks.items() if t},
                                    "label": pub.label or segs[-1][:-5], "kind": "screen" if is_screen(pub.feed.url) else "rtsp",
                                    "by": segs[2] if len(segs) > 3 else ""}
                            gens = {r: g for r, g in (getattr(pub.feed, "xs_gen", None) or {}).items() if r in to and g}
                            if gens:
                                body["gens"] = gens   # 0.21.91: the rooms as they were when they took it (a newer one of that name is not them)
                            d, code = post(minter + "/api/xshare", body, htok)
                            if not isinstance(d, dict):
                                for r in to:
                                    state[r] = "the relay did not answer"
                            else:
                                acc = [r for r in (d.get("to") or []) if r in to]
                                for r in acc:
                                    state[r] = "ok"
                                gone = [r for r in (d.get("gone") or []) if r in to]
                                if gone:   # 0.21.91: deleted -- this camera leaves those rooms for good (never re-attached to a new one)
                                    self._xs_forget(pub.feed, gone, path, now)
                                    for r in gone:
                                        state.pop(r, None)
                                ren = {str(k): str(v) for k, v in (d.get("renamed") or {}).items() if str(k) in to} if isinstance(d.get("renamed"), dict) else {}
                                if ren:    # 0.21.91: renamed -- the camera follows the new name (listed there on the next round)
                                    self._xs_follow(pub.feed, ren, path, now)
                                    for r in ren:
                                        state.pop(r, None)
                                    gone = gone + list(ren)
                                ng = d.get("gens") if isinstance(d.get("gens"), dict) else {}
                                learned = False
                                for r in acc:
                                    g = str(ng.get(r) or "")[:24]
                                    if g and not (getattr(pub.feed, "xs_gen", None) or {}).get(r):
                                        if not isinstance(getattr(pub.feed, "xs_gen", None), dict):
                                            pub.feed.xs_gen = {}
                                        pub.feed.xs_gen[r] = g
                                        learned = True
                                if learned:
                                    self.persist_feeds()
                                ref = d.get("refused") if isinstance(d.get("refused"), dict) else {}
                                for r in to:
                                    if r not in state and r not in gone:
                                        state[r] = str(ref.get(r) or d.get("error") or "refused")[:80]
                                if acc:
                                    rec = self._xs_listed.setdefault(path, {"rooms": set(), "base": base, "minter": minter, "room": room})
                                    new = sorted(set(acc) - rec["rooms"])
                                    rec["rooms"] |= set(acc)
                                    if new:
                                        self.log("rtsp: %s shows in %s" % (path, ", ".join(new)))
                pub.feed.xs_state = state
                out[path] = state
            return out

    # ---- 0.21.84: the stream library (box side) -------------------------------------------------------------------------
    def _lib(self):
        """The bridge's library bookkeeping (made on first use -- a bridge built without __init__, in tests, too)."""
        d = self.__dict__.get("_libst")
        if d is None:
            d = self.__dict__["_libst"] = {"caps": {}, "toks": {}, "bad": {}, "beaten": {}, "stop": {}, "stills": {},
                                           "stillAt": {}, "beatAt": {}, "thread": None, "evt": threading.Event(),
                                           "grabbing": set(), "said": {}}
        return d

    def _lib_say(self, key, text, every=600):
        st = self._lib()
        if time.time() - st["said"].get(key, 0) > every:
            st["said"][key] = time.time()
            self.log(text)

    def _lib_ses(self):
        ses = self._session if self._session.get("room") else (getattr(self, "_last_session", None) or self._session)
        return ses or {}

    def _lib_base(self, feed, broadcast):
        """A camera's ROOM path -- what the page asks for (it may post the library path as well)."""
        b = str(broadcast or "")
        if not is_lib(b):
            return b
        cur = getattr(feed, "base_broadcast", None)
        if cur and lib_path_of(cur) == b:
            return cur
        room = getattr(feed, "room", "") or self._lib_ses().get("room") or ""
        return (room + b[len(LIB_ROOT):]) if room else b

    def _lib_want(self, feed, base):
        """Does this camera belong in the library? Its own switch; else the box's default: ON for a box in no room (its hidden
        home room), OFF in a real room. Never a screen share or a private capture (0.21.85: shares get their own switch)."""
        if not LIBRARY_ENABLED or not getattr(self, "lib_master", True) or feed is None:
            return False
        if is_screen(getattr(feed, "url", "")) or is_private(feed):
            return False
        v = getattr(feed, "lib", None)
        if v is not None:
            return bool(v)
        room = str(base or "").split("/", 1)[0]
        if room == LIB_ROOT:
            return True
        if getattr(feed, "room", "") and feed.room != (self._lib_ses().get("room") or ""):
            return False   # a web client's camera, in its own room
        return is_home_room(room)

    def _lib_cap_cached(self, relay):
        parts, _w = _relay_base(_relay_key(relay))
        hit = self._lib()["caps"].get(parts[1]) if parts else None
        return bool(hit and hit[1])

    def _lib_cap(self, relay, now=None, fetch=True):
        """Does the relay this camera publishes on serve the library now? Asked every LIB_CAP_S; a relay that does not answer
        keeps its last word (a dark relay never moves cameras back and forth). fetch=False: what was heard last only."""
        now = time.time() if now is None else now
        parts, _w = _relay_base(_relay_key(relay))
        if not parts:
            return False
        st, key = self._lib(), parts[1]
        hit = st["caps"].get(key)
        ask = getattr(self, "lib_cap_fetch", None)   # kastr_serve.make_bridge sets relay_library (a bare bridge never asks)
        if (hit and now - hit[0] < LIB_CAP_S) or not fetch or not callable(ask):
            return bool(hit and hit[1])
        on = ask(_relay_key(relay))
        if on is None:
            on = bool(hit and hit[1])
            st["caps"][key] = (now - LIB_CAP_S + 15, on)   # asked again in 15 s
        else:
            if bool(on) != bool(hit and hit[1]):
                self.log("rtsp: relay %s %s the stream library" % (key, "serves" if on else "does not serve"))
            st["caps"][key] = (now, bool(on))
        return bool(on)

    def _lib_token(self, relay, now=None):
        """-> (status, token, why): the library publisher token for this relay -- cached until LIB_TOKEN_MIN_S before it ends; a
        refused mint is not retried with the same code; an "off" answer turns the relay's library off here at once."""
        now = time.time() if now is None else now
        st, key = self._lib(), _relay_key(relay)
        hit = st["toks"].get(key)
        if hit and hit[1] - now > LIB_TOKEN_MIN_S:
            return "token", hit[0], ""
        access = str(self._lib_ses().get("access") or "")
        bad = st["bad"].get(key)
        if bad and bad[0] == access and (bad[1] == "refused" or now - bad[3] < 60):
            return bad[1], None, bad[2]
        mint = getattr(self, "lib_mint", None) or mint_library
        s, url, det = mint(key, access, self.host_slug)
        if s == "token":
            tok = _relay_token(url)
            st["toks"][key] = (tok, _jwt_exp(tok) or (now + 3600))
            st["bad"].pop(key, None)
            return "token", tok, ""
        if s == "off":
            parts, _w = _relay_base(key)
            if parts:
                st["caps"][parts[1]] = (now, False)
        st["bad"][key] = (access, s, str(det or s)[:120], now)
        self._lib_say("tok:" + key, "rtsp: no library token from %s: %s (%s)" % (key, s, str(det or "")[:120]))
        return s, None, str(det or s)[:120]

    def _lib_url(self, relay, now=None):
        """The relay URL a library camera publishes on (?jwt= = the library publisher token), or None."""
        s, tok, _why = self._lib_token(relay, now)
        parts, _w = _relay_base(_relay_key(relay))
        if s != "token" or not parts:
            return None
        return parts[0] + ("" if parts[0].endswith("/relay") else "/") + "?jwt=" + tok

    def _lib_minter(self, feed):
        """A library camera's minter (Publisher.minter): a FRESH library URL for its relay (renewals, a refused token), or None."""
        fid = feed.id

        def mint():
            cur = self._pubs.get(fid)
            relay = cur.relay if cur is not None else (self._lib_ses().get("relay") or "")
            st = self._lib()
            hit = st["toks"].get(_relay_key(relay))
            if hit and hit[1] - time.time() < 3600:
                st["toks"].pop(_relay_key(relay), None)
            return self._lib_url(relay)
        return mint

    def _lib_effective(self, feed, base, relay, now=None, fetch=True):
        return self._lib_want(feed, base) and self._lib_cap(relay, now, fetch=fetch)

    def _lib_note(self, feed, base, now=None):
        """A camera went into the library from `base`: its old path is kept (aka, LIB_AKA_KEEP_S -- the hub rewrites every board
        naming it, pages their own grids), its switch is ON from now on (it stays when the box later joins a room), and a box
        in a real room lists it back into that room (Show in rooms)."""
        now = time.time() if now is None else now
        aka = getattr(feed, "lib_aka", None)
        if not isinstance(aka, dict):
            aka = feed.lib_aka = {}
        if base and not is_lib(base) and base not in aka:
            aka[base] = int(now)
        for k in [k for k, t in aka.items() if now - t > LIB_AKA_KEEP_S]:
            aka.pop(k, None)
        if getattr(feed, "lib", None) is None:
            feed.lib = True
        room = str(base or "").split("/", 1)[0]
        if room and room != LIB_ROOT and not is_home_room(room):
            xs = [str(r) for r in (getattr(feed, "xs", None) or [])]
            if room not in xs and len(xs) < XS_ROOMS_MAX:
                feed.xs = xs + [room]
                feed.xs_auto = room
                self.log("rtsp: %s shows in its own room %s again (from the stream library)" % (lib_path_of(base), room))

    def _lib_unnote(self, feed):
        auto = getattr(feed, "xs_auto", None)
        if auto:
            feed.xs = [r for r in (getattr(feed, "xs", None) or []) if r != auto]
            feed.xs_auto = None

    def _boxout_carry(self, feed, base, now=None):
        """0.21.96 box-out: on a boxed machine (self.boxout(), set by kastr_serve) a camera of its own that moves from a real
        room R to its home room or My room (the page left R: a relay started under a page in a room, an old page) shows in
        R again (xs, R's code kept) and keeps its R path as a library alias -- viewers in R see no change."""
        fn = getattr(self, "boxout", None)
        try:
            if not callable(fn) or not fn():
                return
        except Exception:
            return
        old = str(getattr(feed, "base_broadcast", None) or "")
        old_room, new_room = old.split("/", 1)[0], str(base or "").split("/", 1)[0]
        if not old or old_room == new_room or not boxout_real_room(old_room) or old_room == "main" or boxout_real_room(new_room):
            return
        if getattr(feed, "room", ""):
            return   # a web client's camera (0.21.2: only those carry a room of their own)
        now = int(time.time() if now is None else now)
        xs = [str(r) for r in (getattr(feed, "xs", None) or []) if str(r) != new_room]
        if old_room not in xs and len(xs) < XS_ROOMS_MAX:
            xs = xs + [old_room]
            last = getattr(self, "_last_session", None) or {}
            if last.get("room") == old_room and last.get("roomCode"):
                codes = dict(getattr(feed, "xs_codes", None) or {})
                codes.setdefault(old_room, str(last["roomCode"]))
                feed.xs_codes = codes
        feed.xs = xs
        aka = getattr(feed, "lib_aka", None)
        if not isinstance(aka, dict):
            aka = feed.lib_aka = {}
        aka.setdefault(old, now)
        if getattr(feed, "xs_auto", None) == old_room:
            feed.xs_auto = None
        msg = "rtsp: box-out -- %s left room %s for %s; it still shows in %s (Show in rooms)" % (old, old_room, new_room, old_room)
        self.log(msg)
        try:
            note = getattr(self, "boxout_note", None)
            if callable(note):
                note(msg)
        except Exception:
            pass
        try:
            if self._xs_wanted():
                self._xs_ensure()
            self.xs_poke()
        except Exception:
            pass

    def _lib_after_publish(self, feed, old_b, old_relay, broadcast, lib_on, base):
        """_publish's bookkeeping: a camera that left the library is stopped there (with where it went); one that joined is noted."""
        st = self._lib()
        if old_b and is_lib(old_b) and old_b != broadcast:
            st["stop"][old_b] = ("" if is_lib(broadcast) else broadcast, _relay_key(old_relay))
        if lib_on:
            st["stop"].pop(broadcast, None)
            if not old_b or old_b != broadcast:
                st["stillAt"].pop(broadcast, None)   # a still at once (the relay forgot the last one when it left)
                self._lib_note(feed, base)
                self.log("rtsp: %s is in the stream library as %s" % (base, broadcast))
                if old_b or getattr(feed, "xs", None):
                    self.xs_poke()   # its other rooms: listed again from the new path (the old listings withdrawn)
            self.lib_poke()
        elif old_b and is_lib(old_b):
            self._lib_unnote(feed)
            self.log("rtsp: %s left the stream library (back at %s)" % (old_b, broadcast))
            self.xs_poke()
            self.lib_poke()
        elif self._lib_want(feed, base):
            self._lib_ensure()   # in the library once its relay serves it (the loop asks every minute)

    def _lib_move(self, pub, want, base):
        """Re-publish one camera at its library path (want) or back at its room path -- the same options; one gap of a few seconds
        while it reconnects. -> moved?"""
        feed = pub.feed
        if want:
            if not self._lib_url(pub.relay):
                feed.lib_status = "no library token from the relay"
                return False
            relay = pub.relay
        else:
            mint = self._minter_for(feed, base, pub.relay)
            relay = mint() if mint else None
            if not relay:
                feed.lib_status = "no room token for %s" % str(base).split("/", 1)[0]
                self._lib_say("back:" + base, "rtsp: %s cannot leave the stream library yet -- no token for its room" % base)
                return False
        try:
            self.publish(feed.id, base, relay, passthrough=pub.passthrough, audio=pub.audio, keep=pub.keep,
                         ondemand=pub.wantOndemand, low=pub.wantLow, label=pub.label, idle=pub.wantIdle)
            return True
        except Exception as e:
            self._lib_say("move:" + base, "rtsp: %s did not move %s the stream library: %s" % (base, "into" if want else "out of", e))
            return False

    def _lib_moves(self, now=None, fetch=True):
        moved = 0
        for pub in list(self._pubs.values()):
            if pub.role != "main" or pub.stopping or is_private(pub.feed) or is_screen(getattr(pub.feed, "url", "")):
                continue
            base = getattr(pub.feed, "base_broadcast", None) or pub.broadcast
            want = self._lib_effective(pub.feed, base, pub.relay, now, fetch=fetch)
            if want != is_lib(pub.broadcast) and self._lib_move(pub, want, base):
                moved += 1
        return moved

    def _lib_row(self, pub, now=None):
        feed, b = pub.feed, pub.broadcast
        row = {"path": b, "label": pub.label or b.rsplit("/", 1)[-1][:-5], "kind": lib_kind(getattr(feed, "url", "")),
               "state": lib_state(pub, now), "low": pub.lowPub is not None,
               "audio": bool(pub.audio and getattr(feed, "acodec", None) != "")}
        if getattr(feed, "width", None) and getattr(feed, "height", None):
            row["res"] = "%dx%d" % (int(feed.width), int(feed.height))
        aka = sorted(a for a in (getattr(feed, "lib_aka", None) or {}) if lib_path_of(a) == b)
        if aka:
            row["aka"] = aka[-4:]
        return row

    def _lib_box_name(self):
        return re.sub(r"-[0-9a-f]{4}$", "", str(self.host_slug or "")) or "box"

    def _lib_pubs(self):
        return [p for p in list(self._pubs.values()) if p.role == "main" and not p.stopping and is_lib(p.broadcast)]

    def _lib_air(self, now):
        air = {(p.broadcast, lib_state(p, now)) for p in self._lib_pubs()}
        for p in list(self._pubs.values()):   # 0.21.85: a listed share that starts / stops streaming, pauses or is switched
            if self._lib_list_want(p):
                air.add((lib_path_of(p.broadcast), "dark" if p.paused else lib_state(p, now), bool(_lib_mirror_of(p))))
        for path, r in list((self._lib().get("shares") or {}).items()):
            air.add((path, r.get("state"), r.get("label")))
        return frozenset(air)

    def _lib_wanted(self):
        if not LIBRARY_ENABLED:
            return False
        st = self._lib()
        if st["stop"] or st["stills"] or st.get("shares") or st.get("listed"):   # 0.21.85: + listed shares
            return True
        return any(p.role == "main" and not p.stopping and (is_lib(p.broadcast) or self._lib_want(
            p.feed, getattr(p.feed, "base_broadcast", None) or p.broadcast) or self._lib_list_want(p)) for p in list(self._pubs.values()))

    def _lib_ensure(self):
        st = self._lib()
        if not callable(getattr(self, "lib_cap_fetch", None)):
            return   # a bare bridge (tests): no relay to ask, no loop -- lib_tick runs only when called
        with self._lock:
            t = st.get("thread")
            if t is not None and t.is_alive():
                return
            t = threading.Thread(target=self._lib_loop, daemon=True, name="kastr-library")
            st["thread"] = t
        t.start()

    def lib_poke(self):
        """Run the library round now (a camera moved, stopped, switched) -- the loop starts if it is not running."""
        self._lib()["evt"].set()
        if self._lib_wanted():
            self._lib_ensure()

    def _lib_loop(self):
        st = self._lib()
        last, air = 0.0, None
        while True:
            if not self._lib_wanted():
                with self._lock:
                    st["thread"] = None
                return
            now = time.time()
            cur = self._lib_air(now)
            if st["evt"].is_set() or cur != air or now - last >= LIB_BEAT_S or st["stills"] or st.get("due"):
                st["evt"].clear()
                try:
                    self.lib_tick(now)
                    air, last = self._lib_air(time.time()), now
                except Exception as e:
                    self._lib_say("loop", "rtsp: stream library round failed: %s" % e)
            st["evt"].wait(LIB_AIR_CHECK_S)

    def lib_tick(self, now=None, post=None):
        """One library round: move cameras in / out of the library (their switch, the box's default, the relay's word), then ONE
        heartbeat per relay -- every library camera's row (+ its old paths, + a still when one is ready) and the stops. `post(url,
        body, bearer) -> (dict | None, code)` is injectable (tests). -> {relay: (code, reply)}."""
        now = time.time() if now is None else now
        post = post or self._xs_post
        st = self._lib()
        st["due"] = False   # set again below when a heartbeat had to wait (the 10 s limit, a 429)
        if not self.suspended:
            self._lib_moves(now)
        groups = {}
        for pub in self._lib_pubs():
            groups.setdefault(_relay_key(pub.relay), []).append(pub)
        lrows = self._lib_list_round(now)   # 0.21.85: the LISTED shares' rows (and stops for the ones that went)
        for rk in lrows:
            groups.setdefault(rk, [])
        for _p, (_mv, rk) in list(st["stop"].items()):
            groups.setdefault(rk, [])
        out = {}
        for rk, pubs in groups.items():
            stops = {p: mv for p, (mv, k) in list(st["stop"].items()) if k == rk}
            lr = lrows.get(rk, [])
            if not pubs and not stops and not lr:
                continue
            if (pubs or lr) and now - st["beatAt"].get(rk, 0) < LIB_BEAT_MIN_S:
                st["due"] = True   # a change within 10 s of the last heartbeat goes out on the next check
                continue
            parts, _why = _relay_base(rk)
            if not parts:
                continue
            s, tok, twhy = self._lib_token(rk, now)
            if s != "token":
                for pub in pubs:
                    pub.feed.lib_status = "no library token (%s)" % twhy
                continue
            body = {"rows": [self._lib_row(p, now) for p in pubs] + [dict(r) for r in lr], "box": self._lib_box_name()}
            if LIBRARY_SITE:
                body["site"] = LIBRARY_SITE
            stills = {p.broadcast: st["stills"].pop(p.broadcast) for p in pubs if p.broadcast in st["stills"]}
            stills.update({r["path"]: st["stills"].pop(r["path"]) for r in lr if r["path"] in st["stills"]})   # 0.21.85
            if stills:
                body["stills"] = stills
            if stops:
                body["stop"] = sorted(stops)
                mv = {p: m for p, m in stops.items() if m}
                if mv:
                    body["moved"] = mv
            d, code = post(parts[1] + "/api/library", body, tok)
            out[rk] = (code, d)
            if pubs or lr:
                st["beatAt"][rk] = now
            if isinstance(d, dict):
                for p in d.get("stopped") or []:
                    st["stop"].pop(p, None)
            if isinstance(d, dict) and code == 200:
                acc, ref = set(d.get("accepted") or []), d.get("refused") if isinstance(d.get("refused"), dict) else {}
                for pub in pubs:
                    ok = pub.broadcast in acc
                    pub.feed.lib_status = "ok" if ok else str(ref.get(pub.broadcast) or "refused")[:80]
                    if ok:
                        st["beaten"][pub.broadcast] = now
                ls = st.setdefault("listStatus", {})
                for r in lr:   # 0.21.85: the relay's word on each listed share
                    ok = r["path"] in acc
                    ls[r["path"]] = "ok" if ok else str(ref.get(r["path"]) or "refused")[:80]
                    if ok:
                        st.setdefault("listed", {})[r["path"]] = rk
            elif isinstance(d, dict) and code == 403 and d.get("off"):
                st["caps"][parts[1]] = (now, False)   # switched off at the hub: back at the room paths on the next round
                self.log("rtsp: the relay says the stream library is off (%s) -- cameras go back to their rooms" % str(d.get("error") or "")[:120])
                st["evt"].set()
            elif code == 403:
                st["toks"].pop(rk, None)   # a refused token: a fresh one next round
                for pub in pubs:
                    pub.feed.lib_status = str((d or {}).get("error") or "refused")[:80]
            elif code == 429:
                st["beatAt"][rk] = now   # too soon: the next round
                st["due"] = True
                st["stills"].update(stills)
            else:
                st["stills"].update(stills)   # the relay did not answer: the still goes with the next try
                for pub in pubs:
                    pub.feed.lib_status = "the relay did not answer"
        self._lib_stills_due(now)
        return out

    def _lib_still_ok(self, feed):
        """Stills are taken from the camera itself (one short ffmpeg on the monitor's input): RTSP cameras, the test pattern and
        media URLs. A local camera or an RTMP ingest is read through the bridge's one capture -- no still from those yet."""
        u = str(getattr(feed, "url", "") or "").lower()
        return bool(self.ffmpeg) and not (is_device(u) or is_rtmp_in(u) or is_screen(u))

    def _lib_grab(self, pub):
        """One still of a camera for the library: a 160x90 JPEG of at most LIB_STILL_MAX bytes (asked again more coarsely when the
        first is bigger), or None (no ffmpeg, the camera said nothing within 15 s)."""
        feed = pub.feed
        try:
            inp = input_args(feed.url, role="mon", transport=feed_transport(feed))   # 0.21.96: its Transport
        except Exception:
            return None
        for q in (8, 16, 28):
            argv = [self.ffmpeg, "-hide_banner", "-loglevel", "error"] + inp + [
                "-frames:v", "1", "-an", "-vf", LIB_STILL_VF, "-q:v", str(q), "-f", "mjpeg", "pipe:1"]
            proc = None
            try:
                proc = self.spawn_media(argv, tag="still", nice=True)
                data, _e = proc.communicate(timeout=15)
            except Exception:
                data = b""
            finally:
                self.release_media(proc)
            if data[:2] == bytes((0xFF, 0xD8)) and len(data) <= LIB_STILL_MAX:
                return data
            if not data:
                return None
        return None

    def _lib_stills_due(self, now):
        """Stills that are due start in the background (the next round carries them): every LIB_STILL_EVERY_S while a camera is
        live, and on each state change (an asleep camera shows its last picture)."""
        st = self._lib()
        grab = getattr(self, "lib_grab", None) or self._lib_grab
        targets = [(p, p.broadcast) for p in self._lib_pubs()]
        targets += [(p, _lib_mirror_of(p)[0]) for p in list(self._pubs.values())          # 0.21.85: listed shares (RTSP, media)
                    if _lib_mirror_of(p) and self._lib_list_want(p)]
        for pub, b in targets:
            state = lib_state(pub, now)
            last = st["stillAt"].get(b)
            if (last and now - last[0] < LIB_STILL_EVERY_S and last[1] == state) or b in st["grabbing"]:
                continue
            if (last and last[1] == state and state != "live") or state == "dark":
                st["stillAt"][b] = (now, state)
                continue
            st["stillAt"][b] = (now, state)
            if not self._lib_still_ok(pub.feed) and not getattr(self, "lib_grab", None):
                continue
            st["grabbing"].add(b)

            def run(pub=pub, b=b):
                try:
                    data = grab(pub)
                    if data and data[:2] == bytes((0xFF, 0xD8)) and len(data) <= LIB_STILL_MAX:
                        st["stills"][b] = base64.b64encode(data).decode("ascii")
                finally:
                    st["grabbing"].discard(b)
            if getattr(self, "lib_grab_sync", False):
                run()
            else:
                threading.Thread(target=run, daemon=True, name="kastr-library-still").start()

    def _lib_info(self, feed, pub=None):
        """/api/rtsp/list (publish.library) and /api/rtsp/library: one camera's library state for the page."""
        pub = pub if pub is not None else self._pubs.get(int(feed.id))
        base = getattr(feed, "base_broadcast", None) or (pub.broadcast if pub is not None else "")
        relay = pub.relay if pub is not None else (self._lib_ses().get("relay") or "")
        on = bool(pub is not None and is_lib(pub.broadcast))
        want = self._lib_want(feed, base)
        out = {"on": on, "want": want, "switch": getattr(feed, "lib", None), "base": base, "path": lib_path_of(base) if base else None,
               "available": self._lib_cap_cached(relay) if relay else False, "status": getattr(feed, "lib_status", None),
               "aka": sorted(getattr(feed, "lib_aka", None) or {}), "auto": getattr(feed, "xs_auto", None)}
        if on:
            out["state"] = lib_state(pub)
        try:
            out["listed"] = self._lib_list_info(feed, pub)   # 0.21.85
        except Exception:
            out["listed"] = None
        if not LIBRARY_ENABLED:
            out["why"] = "kastr.ini library = off on this box"
        elif not getattr(self, "lib_master", True):
            out["why"] = "the box's stream library switch is off"
        elif want and not on and not out["available"]:
            out["why"] = "the relay does not serve the stream library (yet)"
        return out

    def set_lib(self, feed_id, on):
        """POST /api/rtsp/library {id, on: true | false | null}: one camera in / out of the stream library (null = the box's
        default: on in no room, off in a room). Moves at once when the relay serves the library. -> {ok, id, moved, library}."""
        try:
            feed = self.get(feed_id)
        except (TypeError, ValueError):
            feed = None
        if feed is None:
            raise ValueError("no such feed")
        if is_screen(feed.url) or is_private(feed):
            raise ValueError("screen shares join the stream library from 0.21.85")
        if on is not None and not isinstance(on, bool):
            raise ValueError("`on` is true, false or null")
        feed.lib = on
        moved = False
        pub = self._pubs.get(int(feed.id))
        if pub is not None and pub.role == "main" and not pub.stopping and not self.suspended:
            base = getattr(feed, "base_broadcast", None) or pub.broadcast
            want = self._lib_effective(feed, base, pub.relay)
            if want != is_lib(pub.broadcast):
                moved = self._lib_move(pub, want, base)
        self.persist_feeds()
        self.lib_poke()
        return {"ok": True, "id": feed.id, "moved": moved, "library": self._lib_info(feed)}

    def set_lib_master(self, on):
        """POST /api/rtsp/library {master: bool}: the box's own stream library switch (every camera; kept in rtsp-feeds.json)."""
        if not isinstance(on, bool):
            raise ValueError("`master` is true or false")
        if getattr(self, "lib_master", True) != on:
            self.lib_master = on
            self.log("rtsp: the box's stream library switch is %s" % ("on" if on else "off"))
            self.persist_feeds()
            if not self.suspended:
                self._lib_moves()
            self.lib_poke()
        return self.lib_public()

    def lib_public(self):
        """GET /api/rtsp/library -> {ok, enabled (kastr.ini), master (the box's switch), available (its relay's word), why?,
        noRoom (the box sits in its hidden home room: cameras default on), feeds: [{id, broadcast, label, library}]}."""
        ses = self._lib_ses()
        relay = ses.get("relay") or next((p.relay for p in list(self._pubs.values()) if not p.stopping), "")
        feeds = []
        for f in list(self._feeds.values()):
            if is_private(f):
                continue
            pub = self._pubs.get(int(f.id))
            feeds.append({"id": f.id, "broadcast": pub.broadcast if pub is not None else None,
                          "label": pub.label if pub is not None else "", "library": self._lib_info(f, pub)})
        out = {"ok": True, "enabled": bool(LIBRARY_ENABLED), "master": bool(getattr(self, "lib_master", True)),
               "available": self._lib_cap_cached(relay) if relay else False, "noRoom": is_home_room(ses.get("room") or ""),
               "root": LIB_ROOT, "feeds": feeds,
               "relayHere": self._relay_here()}   # 0.21.85: this machine runs the relay -- its shares are listed by default
        if not LIBRARY_ENABLED:
            out["why"] = "kastr.ini library = off on this box"
        return out

    def _xs_htok(self, base, room, access, code, mint, now):
        """0.21.84: the token that proves a listing's own stream -- a member token of its room, or (a library camera) the
        library publisher token."""
        if room == LIB_ROOT:
            s, tok, why = self._lib_token(base, now)
            return s, tok, why
        return self._xs_token(base, room, access, code, mint, now)

    # ---- 0.21.85: LISTED shares (see LIB_SHARE_TTL_S) ----------------------------------------------------------------------
    def _relay_here(self):
        """Does this machine run the relay (kastr_serve sets `relay_here`)? Its shares are listed in the library by default."""
        f = getattr(self, "relay_here", None)
        try:
            return bool(f()) if callable(f) else False
        except Exception:
            return False

    def _lib_list_want(self, pub):
        """Is this share LISTED in the stream library (published at its lib/ path too, kept in its room)? Its own switch (the
        page's "In the stream library", feed.lib_list); without one, ON when this machine runs the relay (Kenton: a relay / hub
        machine's shares are listed automatically) and OFF in a person's app. Never a camera that MOVED into the library (0.21.84
        boxes), one switched out of it, a private capture, a box's home room or the Lobby, nor with the library off here."""
        if not LIBRARY_ENABLED or not getattr(self, "lib_master", True) or pub is None:
            return False
        if getattr(pub, "role", "main") != "main" or getattr(pub, "stopping", False):
            return False
        feed = pub.feed
        b = str(getattr(pub, "broadcast", "") or "")
        if feed is None or is_private(feed) or is_lib(b) or getattr(feed, "lib", None) is False:
            return False
        room = b.split("/", 1)[0]
        if not room or room == "main" or is_home_room(room) or not lib_path_of(b):
            return False
        v = getattr(feed, "lib_list", None)
        if v is not None:
            return bool(v)
        return self._relay_here()

    def _lib_list_pump(self, pub):
        """Publisher.start: does this generation's output pass a pump (so the library copy can ride on it)? A listed share on
        the MPEG-TS mux with moq here. Decided without a network call (the library round mints the token)."""
        return PUBLISH_MUX == "ts" and bool(getattr(self, "moq", None)) and self._lib_list_want(pub)

    def _lib_list_row(self, pub, now=None):
        feed = pub.feed
        path = lib_path_of(pub.broadcast)
        url = getattr(feed, "url", "")
        row = {"path": path, "label": pub.label or path.rsplit("/", 1)[-1][:-5], "kind": lib_share_kind(url),
               "state": "dark" if getattr(pub, "paused", False) else lib_state(pub, now), "low": False,
               "audio": bool(pub.audio and getattr(feed, "acodec", None) != "")}
        if getattr(feed, "width", None) and getattr(feed, "height", None):
            row["res"] = "%dx%d" % (int(feed.width), int(feed.height))
        return row

    def _lib_list_round(self, now):
        """The library round's listed shares -> {relay key: [rows]}: this machine's native shares (each one's libMirror -- what
        its pump publishes -- is set here: the relay serves the library and a library token is at hand) and the page's own
        (POST /api/rtsp/library {shares}, dropped after LIB_SHARE_TTL_S unrepeated). A row that was listed and is no longer gets
        a stop (the relay keeps "No longer in the library" for an hour)."""
        st = self._lib()
        out, cur = {}, {}
        for pub in list(self._pubs.values()):
            if not self._lib_list_want(pub):
                if getattr(pub, "libMirror", None) is not None:
                    pub.libMirror = None
                continue
            path, rk = lib_path_of(pub.broadcast), _relay_key(pub.relay)
            if not self._lib_cap(pub.relay, now):
                pub.libMirror = None
                st.setdefault("listStatus", {})[path] = "the relay does not serve the stream library (yet)"
                continue
            url = self._lib_url(pub.relay, now)
            if not url:
                pub.libMirror = None
                st.setdefault("listStatus", {})[path] = "no library token from the relay"
                continue
            pub.libMirror = (path, url)
            if pub.running and not pub.pumped and not pub.standby and not self.suspended:
                self.log("rtsp: %s restarts once to be listed in the stream library" % pub.broadcast)
                pub.retoken(pub.relay)   # switched on while it ran without a pump (another page, a restore): one restart
            out.setdefault(rk, []).append(self._lib_list_row(pub, now))
            cur[path] = rk
        shares = st.setdefault("shares", {})
        for p in [p for p, r in list(shares.items()) if now - float(r.get("at") or 0) > LIB_SHARE_TTL_S]:
            shares.pop(p, None)
        for p, r in list(shares.items()):
            if p in cur or not self._lib_cap(r["relay"], now):
                continue
            out.setdefault(r["relay"], []).append({k: r[k] for k in ("path", "label", "kind", "state", "audio", "res") if k in r})
            cur[p] = r["relay"]
        listed = st.setdefault("listed", {})
        for p, rk in list(listed.items()):
            if p not in cur:
                listed.pop(p, None)
                st["stop"].setdefault(p, ("", rk))
                self.log("rtsp: %s is no longer listed in the stream library" % p)
        return out

    def _lib_list_info(self, feed, pub=None):
        """/api/rtsp/list (publish.library.listed): a native share's "In the stream library" state for the page."""
        pub = pub if pub is not None else self._pubs.get(int(feed.id))
        want = bool(pub is not None and self._lib_list_want(pub))
        path = lib_path_of(pub.broadcast) if (pub is not None and not is_lib(pub.broadcast)) else None
        lp = getattr(pub, "libPipe", None) if pub is not None else None
        on = bool(want and lp is not None and lp.gen == pub._gen and lp.proc is not None and lp.proc.poll() is None)
        out = {"want": want, "on": on, "switch": getattr(feed, "lib_list", None), "default": self._relay_here(), "path": path,
               "status": (self._lib().get("listStatus") or {}).get(path) if path else None}
        if is_private(feed):
            out["why"] = "a private capture is never listed"
        elif pub is not None and is_lib(pub.broadcast):
            out["why"] = "this camera moved into the library (its box switch)"
        elif pub is not None and is_home_room(str(pub.broadcast).split("/", 1)[0]):
            out["why"] = "a box in no room puts its cameras in the library itself (its box switch)"
        elif not LIBRARY_ENABLED or not getattr(self, "lib_master", True):
            out["why"] = "the stream library is off on this machine"
        return out

    def set_transport(self, feed_id, mode):
        """0.21.96: POST /api/rtsp/transport {id, transport: "auto" | "tcp" | "udp"} -- how this rtsp:// camera is pulled.
        Kept per camera URL in rtsp-feeds.json (sealed like the feed's own URL). A change restarts its readers on the new
        transport: the monitor ffmpegs (the page reconnects) and the native pair + its low copy (in the background -- the
        start probes the camera). Auto decides again, from TCP. -> {ok, id, transport, transportNow, restarted}."""
        try:
            feed = self.get(feed_id)
        except (TypeError, ValueError):
            feed = None
        if feed is None:
            raise ValueError("no such feed")
        mode = str(mode or "auto").strip().lower()
        if mode not in TRANSPORTS:
            raise ValueError("`transport` is auto, tcp or udp")
        if not is_rtsp_url(feed.url):
            raise ValueError("only an rtsp:// camera has a transport")
        old = transport_mode(feed)
        feed.transport = mode
        if mode == "auto":
            self._transports.pop(feed.source_url, None)
        else:
            self._transports[feed.source_url] = mode
        restarted = False
        if mode != old:
            AUTO_PICKS.pop(feed.url, None)
            feed.tcp_refused = feed.udp_refused = None
            feed.loss = LossMeter()
            feed.h264 = None                  # probed again (the probe cache is per transport)
            feed.probe_failed_at = None
            self.kill(feed)
            pub = self._pubs.get(int(feed.id))
            if pub is not None:
                def restart(pub=pub):
                    try:
                        pub.nudge("transport")
                        if pub.lowPub is not None:
                            pub.lowPub.nudge("transport")
                    except Exception as e:
                        self.log("rtsp: transport restart of feed %s: %s" % (feed.id, e))
                threading.Thread(target=restart, daemon=True).start()
            restarted = True
            self.log("rtsp: feed %s transport %s -> %s" % (feed.id, old, mode))
        self.persist_feeds()
        return {"ok": True, "id": feed.id, "transport": mode, "transportNow": feed_transport(feed), "restarted": restarted}

    def diag_feeds(self):
        """0.21.96: /api/diag's `_rtsp` section -- each RTSP camera's transport and what its readers lost (URL redacted)."""
        out = []
        for feed in list(self._feeds.values()):
            if not is_rtsp_url(getattr(feed, "url", "")):
                continue
            d = {"id": feed.id, "url": _redact_url(feed.source_url)}
            d.update(transport_info(feed))
            pub = self._pubs.get(int(feed.id))
            if pub is not None:
                d["pub"] = {"running": pub.running, "restarts": pub.restartsTotal, "videoFrames": pub.videoFrames,
                            "videoAt": pub.videoAt, "copy": pub.copy, "codec": pub.codec}
            out.append(d)
        return out

    def set_lib_list(self, feed_id, on):
        """POST /api/rtsp/library {id, list: true | false | null}: list one native share in the stream library (kept in its room;
        null = this machine's default). A share running without a pump restarts once (a few seconds); turning it off ends its
        library copy at once. -> {ok, id, repiped, library}."""
        try:
            feed = self.get(feed_id)
        except (TypeError, ValueError):
            feed = None
        if feed is None:
            raise ValueError("no such feed")
        if on is not None and not isinstance(on, bool):
            raise ValueError("`list` is true, false or null")
        if is_private(feed):
            raise ValueError("a private capture is never listed in the stream library")
        feed.lib_list = on
        repiped = False
        pub = self._pubs.get(int(feed.id))
        if pub is not None:
            if not self._lib_list_want(pub):
                pub.libMirror = None
            elif pub.running and not pub.pumped and not pub.standby and not self.suspended:
                pub.retoken(pub.relay)   # its output now passes the pump the library copy rides on
                repiped = True
        self.persist_feeds()
        self.lib_poke()
        return {"ok": True, "id": feed.id, "repiped": repiped, "library": self._lib_info(feed)}

    def lib_shares(self, payload):
        """POST /api/rtsp/library {shares: [{path, label, kind, state, audio?, res?}], relay, stills?: {path: base64 JPEG}, token?}:
        the page's own LISTED shares (a webcam, a browser screen, a media file, a grid -- mirrored inside the page), heartbeaten
        with this machine's native shares. The page sends its whole list (every 30 s and on each change); a row it stops sending
        leaves the library. -> {ok, token (the library publisher token for the page's mirror connection) | null, why?, status}."""
        st = self._lib()
        now = time.time()
        rk = _relay_key(str(payload.get("relay") or ""))
        parts, _why = _relay_base(rk)
        if not parts:
            raise ValueError("relay must be the page's relay url")
        shares = st.setdefault("shares", {})
        keep, refused = {}, {}
        rows = payload.get("shares") if isinstance(payload.get("shares"), list) else []
        for r in rows[:LIB_SHARE_MAX]:
            if not isinstance(r, dict):
                continue
            p = str(r.get("path") or "")[:300]
            segs = p.split("/")
            if (not is_lib(p) or len(segs) < 3 or not p.endswith(".hang") or p.endswith("-low.hang")
                    or (self.host_slug and segs[1] != self.host_slug)):
                refused[p[:120] or "?"] = "not a library path of this computer"
                continue
            kind = str(r.get("kind") or "other")
            row = {"path": p, "label": str(r.get("label") or "")[:80].strip() or segs[-1][:-5],
                   "kind": kind if kind in LIB_SHARE_KINDS else "other", "state": "dark" if r.get("state") == "dark" else "live",
                   "audio": bool(r.get("audio")), "relay": rk, "at": now}
            res = str(r.get("res") or "")
            if re.match(r"^[0-9]{2,5}x[0-9]{2,5}$", res):
                row["res"] = res
            keep[p] = row
        before = {p: (x.get("state"), x.get("label"), x.get("kind")) for p, x in shares.items() if x.get("relay") == rk}
        for p in [p for p, x in list(shares.items()) if x.get("relay") == rk and p not in keep]:
            shares.pop(p, None)
        shares.update(keep)
        changed = before != {p: (x["state"], x["label"], x["kind"]) for p, x in keep.items()}
        got = 0
        stills = payload.get("stills") if isinstance(payload.get("stills"), dict) else {}
        for p, b64 in list(stills.items())[:LIB_SHARE_MAX]:
            if p not in keep:
                continue
            try:
                data = base64.b64decode(str(b64 or "").encode("ascii", "ignore"))
            except Exception:
                continue
            if 0 < len(data) <= LIB_STILL_MAX and data[:2] == bytes((0xFF, 0xD8)):
                st["stills"][p] = base64.b64encode(data).decode("ascii")
                got += 1
        if changed or got:
            self.lib_poke()
        elif keep and self._lib_wanted():
            self._lib_ensure()
        out = {"ok": True, "token": None, "available": self._lib_cap_cached(rk), "refused": refused,
               "status": {p: (st.get("listStatus") or {}).get(p) or "waiting" for p in keep}}
        if keep or payload.get("token"):
            s, tok, why = self._lib_token(rk, now)
            if s == "token":
                out["token"] = tok
            else:
                out["why"] = why or s
        return out

    def pause(self, feed_id, on):
        """0.21.73: pause / resume a screen share -- the same broadcast restarts on the "paused" card (and back), so viewers
        keep its tile; the border and the bar stay. -> the publisher's info, or None (no such share)."""
        pub = self._pubs.get(int(feed_id))
        if pub is None or not is_screen(pub.feed.url):
            return None
        if on:
            _rc_gone(feed_id, "paused")   # 0.21.79: a paused share is nobody's to control
        if bool(on) != pub.paused:
            pub.paused = bool(on)
            self.log("screen: share %s %s" % (pub.broadcast, "paused" if on else "resumed"))
            pub.nudge("pause" if on else "resume")
        return pub.info()

    def rc_mode(self, feed_id, on):
        """0.21.80: someone controls this native share (on) / control ended (off): the same broadcast restarts once into the
        remote-control capture + low-latency encode (rc_screen_opts, RC_LOWLAT) and once back. -> True when it changed."""
        pub = self._pubs.get(int(feed_id))
        if pub is None or not is_screen(pub.feed.url) or bool(on) == bool(pub.rcmode):
            return False
        if on:
            try:
                self.rc_lowlat(self.usable_encoder() if not pub.copy else "libx264")   # validated before the restart, not during it
            except Exception:
                pass
        pub.rcmode = bool(on)
        self.log("screen: share %s %s remote control (%s)" % (pub.broadcast, "under" if on else "out of", "no cursor, low latency" if on else "as before"))
        pub.nudge("rc-on" if on else "rc-off")
        return True

    def rc_lowlat(self, enc):
        """0.21.80: RC_LOWLAT[enc] when a 0.3 s test encode with it works here (asked once per encoder), else [] -- a hardware
        encoder that refuses an option keeps its normal arguments instead of failing the share."""
        cache = self.__dict__.setdefault("_rc_ll", {})
        enc = enc or "libx264"
        if enc in cache:
            return cache[enc]
        want = list(RC_LOWLAT.get(enc, []))
        ok = not want
        if want:
            cmd = ([self.ffmpeg, "-hide_banner", "-loglevel", "error"] + encoder_pre_args(enc)
                   + ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=0.3", "-vf", encoder_vf(enc, "format=yuv420p"),
                      "-c:v", enc] + (["-b:v", "4M"] if enc != "libx264" else ["-b:v", "5M"]) + want + ["-f", "null", "-"])
            try:
                ok = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode == 0
            except Exception:
                ok = False
            self.log("screen: low-latency %s arguments %s" % (enc, "work" if ok else "refused -- the normal encode stays"))
        cache[enc] = want if ok else []
        return cache[enc]

    def retarget(self, feed_id, url):
        """0.21.73 (Kenton chose: "Share something else" swaps in place): point a running screen share at another screen,
        window or tab -- the same feed id and broadcast (tile, pins and spotlight stay), a new capture, the border moves.
        -> the feed's info. ValueError for a bad or already shared target."""
        import kastr_screen
        url = str(url or "")
        if not is_screen(url):
            raise ValueError("only a screen, window or tab can be shared in place")
        kastr_screen.check_url(url)
        feed = self.get(feed_id)
        if feed is None or not is_screen(feed.url):
            raise ValueError("no such share")
        with self._lock:
            if any(f.url == url and f.id != feed.id for f in self._feeds.values()):
                raise ValueError("that is already shared")
            feed.url = feed.source_url = url
            feed.screen_ident = None
            feed.width = feed.height = None
        fid = feed.id
        _rc_gone(fid, "retarget")   # 0.21.79: control was granted for what it showed before
        kastr_screen.overlay_stop(fid)
        kastr_screen.overlay_start(fid, url, on_stop=lambda: (self.log("screen: Stop sharing on the bar"), self.remove(fid)))
        for p in list(feed.procs):   # the old monitor (the page's thumbnail) -- the page reopens it
            try:
                p.kill()
            except OSError:
                pass
        pub = self._pubs.get(fid)
        if pub is not None:
            pub.paused = False   # what was picked shows at once
            self.log("screen: share %s now shows %s" % (pub.broadcast, url))
            if callable(getattr(pub, "quiet", None)):
                pub.quiet()      # 0.21.83 (D): the old capture leaves the relay at once -- viewers move to the new one quickly
            pub.nudge("retarget")
        self.persist_feeds()
        return feed.info()

    def nudge(self, feed_id, why="api"):
        pub = self._pubs.get(int(feed_id))
        if pub:
            if getattr(pub, "suspended", False):   # 0.21.16: a viewer/no-echo report against a switched-off camera is not news -- no log line, no restart
                return False
            # 0.13.1: one line per restart request, counters as they stood
            self.log("rtsp nudge %s why=%s restarts=%d sessionFails=%d sessionKills=%d"
                     % (pub.broadcast, why, pub.restarts, pub.sessionFails, pub.sessionKills))
            pub.nudge(why)
        return bool(pub)

    def heal(self, feed_id, why="viewer-video"):
        """0.21.93: a viewer's video-stall report against my screen share (Publisher.heal)."""
        pub = self._pubs.get(int(feed_id))
        if not pub:
            return {"did": "refused", "reason": "no such share"}
        return pub.heal(why)

    def publication(self, feed_id):
        pub = self._pubs.get(int(feed_id))
        return pub.info() if pub else None

    def get(self, feed_id):
        return self._feeds.get(int(feed_id))

    def list(self, redact=False):
        """0.13.3: `redact` strips camera credentials from every URL (and the
        stderr tails that may quote one) -- for a page on ANOTHER machine, which
        never needed them; the box's own page keeps the raw URL it keys its
        per-URL settings by."""
        out = []
        for f in self._feeds.values():
            if is_private(f):   # 0.21.83 (D): a fleet admin's private capture is nobody's feed to list or adopt
                continue
            d = f.info()
            d["publish"] = self.publication(f.id)   # 0.9.1
            d["addedBy"] = getattr(f, "added_by", "") or ""   # 0.21.2: a web client's camera (empty = the box's own)
            if is_rtmp_in(f.url):   # 0.21.31: is the device pushing? (a listening ingest is waiting, not failed)
                cap = DEVICES.get(f.url)
                d["ingest"] = {"connected": bool(cap and cap.connected_at), "since": cap.connected_at if cap else None,
                               "lastEnd": cap.last_end_at if cap else None, "pushes": cap.pushes if cap else 0,
                               "lastError": cap.last_error if cap else ""}
            if redact:
                d["url"] = _redact_url(d.get("url"))
                if isinstance(d.get("error"), str):
                    d["error"] = _redact_url(d["error"])
                pub = d.get("publish")
                if isinstance(pub, dict):
                    for k in ("relay", "error", "lastSession"):
                        if isinstance(pub.get(k), str):
                            pub[k] = _redact_url(pub[k])
            out.append(d)
        return out

    def kill(self, feed):
        """Stop every reader's ffmpeg for this feed."""
        for p in list(feed.procs):
            self.release(feed, p)

    def release(self, feed, proc):
        """Stop one reader's ffmpeg, leaving the feed's other readers alone."""
        feed.procs.discard(proc)
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    # ---- 0.21.16: the box's RTSP switch -----------------------------------------------
    def suspend(self, who="operator"):
        """Stop publishing EVERY camera this box owns -- pairs, low copies and the owner's monitors -- and keep
        every record: feeds, publishers, rtsp-feeds.json, the page's rows and grids. start() refuses until
        resume(); a publish request meanwhile is recorded, not started. Not a watchdog: nothing here flips
        the switch by itself -- only /api/rtsp/suspend (page, Relay page) or the hub's `rtsp` command."""
        with self._lock:
            if self.suspended:
                return {"ok": True, "suspended": True, "stopped": 0, "monitors": 0, "records": len(self._pubs)}
            self.suspended = True
            pubs = [p for p in self._pubs.values() if not is_private(p.feed)]   # 0.21.83 (D): not a fleet admin's session
            feeds = [f for f in self._feeds.values() if not is_private(f)]
        stopped = sum(1 for p in pubs if p.suspend(who))
        mons = 0
        for f in feeds:
            mons += len(f.procs)
            self.kill(f)                      # the owner's monitors; the page stops re-attaching while suspended
        self.persist_feeds()
        self.log("rtsp: publishing SUSPENDED by %s -- %d pair(s) stopped, %d monitor(s) released, %d record(s) kept"
                 % (who, stopped, mons, len(pubs)))
        if getattr(self, "_xs_listed", None):   # 0.21.75: switched off -> out of the other rooms too
            self.xs_poke()
        return {"ok": True, "suspended": True, "stopped": stopped, "monitors": mons, "records": len(pubs)}

    def resume(self, who="operator"):
        """The switch is back on: every recorded pair starts again (an on-demand one returns to standby). The starts
        run in parallel and are joined for at most 30 s, like restore(): start() probes a camera nobody has probed
        yet (a feed recorded while the switch was off) for up to PROBE_TIMEOUT under the publisher's own lock."""
        with self._lock:
            if not self.suspended:
                return {"ok": True, "suspended": False, "started": 0, "records": len(self._pubs)}
            self.suspended = False
            pubs = list(self._pubs.values())
        done = []

        def one(p):
            try:
                if p.resume(who):
                    done.append(p.broadcast)
                    if p.ondemand:               # 0.18.0 shape: standby + demand loop + low copy (inert while ONDEMAND_ENABLED is off)
                        self._od_ensure()
                        self._low_standby(p)
            except Exception as e:
                self.log("rtsp: resuming %s failed: %s" % (p.broadcast, e))
        threads = [threading.Thread(target=one, args=(p,), daemon=True, name="kastr-rtsp-resume") for p in pubs]
        for t in threads:
            t.start()
        deadline = time.time() + 30
        for t in threads:
            t.join(max(0.1, deadline - time.time()))
        self.persist_feeds()
        self.log("rtsp: publishing RESUMED by %s -- %d of %d pair(s) starting" % (who, len(done), len(pubs)))
        if self._xs_wanted():   # 0.21.75
            self._xs_ensure()
            self.xs_poke()
        return {"ok": True, "suspended": False, "started": len(done), "records": len(pubs)}

    def shutdown(self):
        # 0.9.8: explicit kills as before; the job (shared with the relay, which
        # gets its own graceful stop right after this) closes with the process
        # and reaps anything these loops missed.
        self._shutting = True   # 0.21.84: a shutdown leaves the library entries (offline -- they come back), never withdraws them
        for fid in list(self._pubs):
            self.unpublish(fid, persist=False)   # 0.12.0: rtsp-feeds.json stays as it is -- restore() reads it next launch
        for feed in list(self._feeds.values()):
            self.kill(feed)
        for proc in list(self._media):   # 0.14.0: the player's ffmpeg children
            self.release_media(proc)
        for url, cap in list(DEVICES.items()):   # 0.21.61: camera captures + RTMP listeners (the port is free for the next launch)
            try:
                cap.stop()
            except Exception:
                pass
            DEVICES.pop(url, None)
        with self._children_lock:
            self._children.clear()
        self._write_children()           # removes our registry file

    def own_pid(self):
        """0.21.20: the process tree whose sound a screen share leaves out -- this host (its browser is a child)."""
        return os.getpid()

    def usable_encoder(self):
        """First encoder from ENCODERS that actually works here.

        Validated against a local test pattern rather than trusted from
        "ffmpeg -encoders": a laptop can list h264_nvenc and still fail to
        initialise it, which would otherwise produce a feed that never
        delivers a byte.
        """
        if self._encoder is not None:
            return self._encoder

        listed = set()
        try:
            out = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            listed = {name for name in ENCODERS if name in (out.stdout or "")}
        except Exception:
            pass

        for name in ENCODERS:
            if name not in listed and name != "libx264":
                continue
            cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error"] + encoder_pre_args(name) + [
                "-f", "lavfi", "-i", "testsrc2=size=3840x2160:rate=30:duration=0.2",
                "-vf", encoder_vf(name, "scale=%d:-2,format=yuv420p" % MAX_WIDTH),
                "-c:v", name,
            ]
            if name != "libx264":
                cmd += ["-b:v", "4M"]
            cmd += ["-f", "null", "-"]
            try:
                done = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if done.returncode == 0:
                    self._encoder = name
                    # Remembered so the choice is visible in the feed list
                    # rather than only in a console this app may not have.
                    self.encoder_note = name
                    return name
            except Exception:
                continue

        self._encoder = "libx264"
        return self._encoder

    def sends_h264(self, feed):
        """Is this feed already H.264? Probed once, then remembered.

        Worth a second on first connect: copying an H.264 camera runs at
        1.15x real time where re-encoding it managed 0.30x, and anything
        under 1.0x can never keep up with a live stream.
        """
        if getattr(feed, "h264", None) is not None:
            # 0.12.0: a probe that could not tell (camera off when a restored
            # feed came back) is believed for PROBE_RETRY_S, then asked again --
            # not for the rest of the run, which encoded copyable cameras.
            failed = getattr(feed, "probe_failed_at", None)
            if not failed or time.time() - failed < PROBE_RETRY_S:
                return feed.h264
            feed.h264 = None
        if feed.url == TEST_URL:
            feed.h264 = False           # lavfi is raw; it has to be encoded
            return False
        if is_rtmp_in(feed.url):        # 0.21.29: what a device pushes over RTMP is H.264 (+ AAC) -- copied
            feed.h264, feed.vcodec, feed.fullrange, feed.sar = True, "h264", False, None
            feed.width = feed.height = None
            return True
        if is_device(feed.url):         # 0.21.26: our own capture -- H.264 baseline, copied by every reader
            feed.h264, feed.vcodec, feed.fullrange, feed.sar = True, "h264", False, None
            feed.width, feed.height = 1280, 720
            return True
        if is_hostmedia(feed.url):      # 0.21.26: a looped file restarts its timestamps -- always encoded
            feed.h264, feed.vcodec, feed.fullrange, feed.sar = False, "file", False, None
            feed.width = feed.height = None
            return False
        if is_screen(feed.url):         # 0.21.20: a capture is raw too -- encoded, never copied
            import kastr_screen
            feed.h264, feed.vcodec, feed.fullrange, feed.sar = False, "rawvideo", False, None
            feed.width, feed.height = kastr_screen.capture_size(feed.url)
            return False

        # Keyed by url on the bridge (0.21.96: + transport), so a reconnect -- which builds a new feed
        # object -- does not pay for the probe again. Same camera, same answer.
        tr = feed_transport(feed)
        cached = self._probed.get((feed.url, tr))
        if cached is not None:
            feed.h264, feed.width, feed.height, feed.fullrange = cached[:4]
            feed.vcodec = cached[4] if len(cached) > 4 else ("h264" if feed.h264 else None)
            feed.acodec = cached[5] if len(cached) > 5 else None   # 0.9.5
            feed.sar = cached[6] if len(cached) > 6 else None      # 0.9.8
            return feed.h264

        r = self._probe_once(feed.url, tr)
        if r.get("refused") and tr:
            setattr(feed, tr + "_refused", time.time())
        # 0.21.96: Auto -- TCP first; no picture over TCP (refused, or silent) -> ask UDP; UDP's picture wins for the run
        if tr == "tcp" and transport_mode(feed) == "auto" and feed.url.strip().lower().startswith("rtsp://") \
                and auto_choice(r) == "try-udp":
            u = self._probe_once(feed.url, "udp")
            if u.get("refused"):
                feed.udp_refused = time.time()
            if auto_choice(r, u) == "udp":
                AUTO_PICKS[feed.url] = {"transport": "udp", "why": auto_why(r), "at": time.time()}
                self.log("rtsp: %s -- Auto uses UDP (%s)" % (_redact_url(feed.url), auto_why(r)))
                r, tr = u, "udp"
        if r.get("vcodec"):
            feed.vcodec = r["vcodec"]   # 0.9.2
            feed.h264 = feed.vcodec == "h264"
            if r.get("width"):
                feed.width, feed.height = r["width"], r["height"]
            feed.fullrange = r.get("fullrange")
            feed.sar = r.get("sar")
        if r.get("acodec") is not None:
            feed.acodec = r["acodec"]
        if feed.h264 is None:
            # Could not tell. Re-encoding works for anything, so prefer being
            # slow-but-correct over fast-but-maybe-undecodable.
            feed.h264 = False
            feed.probe_failed_at = time.time()   # 0.12.0: tentative -- not cached on the bridge either
        else:
            feed.probe_failed_at = None          # 0.12.0
            if feed.acodec is None:
                feed.acodec = ""       # 0.9.5: probed, and the camera has no audio track
            self._probed[(feed.url, tr)] = (feed.h264, feed.width, feed.height,
                                            feed.fullrange, feed.vcodec, feed.acodec, feed.sar)
        return feed.h264

    def _probe_once(self, url, transport=None):
        """One codec probe of `url` (0.21.96: over `transport`) -> {vcodec, width, height, fullrange, sar, acodec, refused}
        (None where it could not tell; acodec "" never -- None = no audio line seen).

        -c copy so it never decodes, and read only until it names the
        stream. Waiting for the whole command took 12.6s on a 4K camera;
        the codec line arrives about 2.9s in."""
        r = {"vcodec": None, "width": None, "height": None, "fullrange": None, "sar": None, "acodec": None, "refused": False}
        cmd = ([self.ffmpeg, "-hide_banner"] + input_args(url, transport=transport)
               + ["-c", "copy", "-f", "null", "-"])
        proc = None
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _job_assign(self._job, proc, self.log)   # 0.9.8: a probe cut short by a quit dies with us too
            deadline = time.monotonic() + PROBE_TIMEOUT
            seen_video = False
            for line in proc.stderr:
                if REFUSE_RE.search(line):   # 0.21.96: "method SETUP failed: 461 (Unsupported Transport)"
                    r["refused"] = True
                # 0.9.5: the audio stream line (before or after the video one)
                # tells the page whether "Send audio" has anything to send.
                aud = re.search(r"Stream #\d+:\d+.*?: Audio: (\w+)", line)
                if aud:
                    r["acodec"] = aud.group(1).lower()
                    if seen_video:
                        break
                    continue
                if seen_video:
                    # past the input streams: the output/mapping section starts
                    if line.startswith("Output #") or "Stream mapping" in line or "Press [q]" in line:
                        break
                    if time.monotonic() > deadline:
                        break
                    continue
                found = re.search(r"Stream #\d+:\d+.*?: Video: (\w+)", line)
                if found:
                    r["vcodec"] = found.group(1).lower()   # 0.9.2
                    # Same line carries the frame size, e.g. 3840x2160.
                    size = re.search(r"[ ,](\d{2,5})x(\d{2,5})[ ,]", line)
                    if size:
                        r["width"] = int(size.group(1))
                        r["height"] = int(size.group(2))
                    # ...and the colour range. Full range reads as yuvj420p or
                    # an explicit "(pc,". The browser's encoder refuses those.
                    r["fullrange"] = bool(re.search(r"yuvj\d|\(pc[,)]", line))
                    # 0.9.8: "[SAR 1:1 DAR 16:9]" -- non-square pixels must be encoded
                    sar = re.search(r"SAR (\d+):(\d+)", line)
                    r["sar"] = (int(sar.group(1)), int(sar.group(2))) if sar else None
                    seen_video = True      # keep reading a little for the audio line
                    continue
                if time.monotonic() > deadline:
                    break
        except Exception:
            pass
        finally:
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
        return r

    def monitor_plan(self, feed, transcode=False, passthrough=False):
        """(copy?, hvc1?) for the monitor stream -- the publisher's rule, plus
        the page's `transcode=1` override for a copy its <video> could not play."""
        h264 = self.sends_h264(feed)
        vcodec = (feed.vcodec or ("h264" if h264 else "")).lower()
        copy = (not transcode) and passthrough_ok(vcodec, feed.width, feed.fullrange, passthrough, feed.sar)
        if copy and feed_transport(feed) == "udp" and not udp_copy_ok():
            copy = False   # 0.21.96: see udp_copy_ok -- the monitor (and the grid mosaic drawn from it) restarted every ~4 s
        return copy, copy and vcodec in ("hevc", "h265")

    def monitor_codec(self, feed, transcode=False, passthrough=False):
        """What the monitor stream carries (0.9.7): the camera's own codec when
        copied, H.264 when encoded. The page opens its MediaSource with it."""
        copy, _ = self.monitor_plan(feed, transcode, passthrough)
        vc = (feed.vcodec or "h264").lower()
        return (vc if copy else "h264"), copy

    def spawn(self, feed, transcode=False, passthrough=False):
        """Start ffmpeg for this feed's monitor stream and return the process."""
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found")
        copy, hvc1 = self.monitor_plan(feed, transcode, passthrough)   # (probes first -- Auto may pick UDP there)
        tr = feed_transport(feed)   # 0.21.96: "tcp" | "udp" for an rtsp:// camera, else None
        head = [self.ffmpeg, "-hide_banner", "-loglevel", RTSP_LOGLEVEL if tr else "error"]
        if tr is not None and getattr(feed, "loss", None) is not None:
            feed.loss.touch("mon")
        claim = {}   # 0.21.30: the monitor slot this ffmpeg reads (camera / RTMP ingest captures)
        if copy:
            args = head + input_args(feed.url, role="mon", claim=claim, transport=tr) + output_args(feed.url, True, hvc1=hvc1)
        else:
            # 0.9.6: small and fast -- see output_args
            enc = self.usable_encoder()
            args = head + encoder_pre_args(enc) + input_args(feed.url, role="mon", claim=claim, transport=tr) + output_args(feed.url, False, encoder=enc,
                                                                       width=1920 if getattr(feed, "presenter", False) else None)   # 0.21.20: presenter mode composites this picture
        # Windows: keep the console window from flashing up for each feed.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, creationflags=flags,
        )
        _job_assign(self._job, proc, self.log)   # 0.9.8: dies with KASTR (its pipe would end it anyway)
        if claim.get("port") and DEVICES.get(feed.url):
            DEVICES[feed.url].attach(claim["port"], proc)
        feed.procs.add(proc)
        # Clear the tail as well as the summary: clearing only `error` let the
        # drain thread rebuild it from lines the PREVIOUS child left behind, so
        # a fresh attempt reported the last attempt's dying words.
        feed.errors.clear()
        feed.error = None

        # Drain stderr so a chatty ffmpeg can't block on a full pipe, and keep
        # the last line to report back as the feed's error.
        def drain():
            try:
                for line in proc.stderr:
                    text = line.decode("utf-8", "replace").strip()
                    if text and tr is not None:   # 0.21.96: level-tagged -- loss counted (not kept as an error)
                        text = rtsp_line(feed, "mon", tr, text, bridge=self)
                    if text:
                        # Keep a short tail, not just the last line: a TLS or
                        # auth failure explains itself a line or two earlier.
                        feed.errors.append(text)
                        del feed.errors[:-4]
                        feed.error = " / ".join(feed.errors)
            except Exception:
                pass

        threading.Thread(target=drain, daemon=True).start()
        return proc

    # ---- 0.14.0: media child processes (the player's ffmpeg/ffprobe) ------
    def spawn_media(self, argv, tag="media", nice=False):
        """A plain argv child -- no Feed. Registered like every other child
        (job object + rtsp-children-<pid>.json, so sweep_orphans reaps it
        after a crash). stdout is the caller's to read; stderr is drained so
        a chatty ffmpeg never blocks on a full pipe, its last 4 non-empty
        lines kept on proc.kastr_errors.
        0.16.0: `nice` runs the child below normal priority -- a media transcode
        must never starve the browser's own encoder (the viewers' picture)."""
        argv = [str(a) for a in argv]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kw = {}
        if nice:
            if sys.platform == "win32":
                flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            else:
                kw["preexec_fn"] = lambda: os.nice(10)
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                bufsize=0, creationflags=flags, **kw)
        proc.kastr_errors = []
        self._child_started(proc, argv, [argv[-1]] if len(argv) > 1 else [], tag)   # job + registry
        with self._children_lock:
            self._media.add(proc)

        def drain():
            try:
                for line in proc.stderr:
                    text = line.decode("utf-8", "replace").strip()
                    if text:
                        proc.kastr_errors.append(text)
                        del proc.kastr_errors[:-4]
            except Exception:
                pass
            # stderr closed = the child is gone (ffmpeg holds it to the end): out of
            # the registry even when nobody calls release_media (a conversion that
            # simply finished). EOF lands a beat before the exit is visible, so reap.
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            try:
                if proc.poll() is not None:
                    self.release_media(proc)
            except Exception:
                pass

        threading.Thread(target=drain, daemon=True).start()
        return proc

    def release_media(self, proc):
        """Kill (if alive) and unregister one spawn_media child. Best-effort."""
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
        except OSError:
            pass
        with self._children_lock:
            self._media.discard(proc)
        self._child_ended(proc.pid)


def handle_api(handler, bridge, path):
    """Serve the /api/rtsp/* endpoints. Returns True if it handled the request."""
    if not path.startswith("/api/rtsp"):
        return False

    def reply(obj, code=200):
        body = json.dumps(obj).encode()
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    def from_loopback():
        # 0.9.1: the page on this machine reaches us as 127.0.0.1/localhost;
        # anything else (LAN IP, phone over HTTPS, a remote page) is foreign.
        # 0.17.0: the request class -- Host AND peer AND Origin (a typed Host
        # header is not an identity). Imported here: kastr_relay imports us.
        import kastr_relay
        return kastr_relay.is_local(handler)

    def remote_claims(room, jwt):
        """0.21.2: a web client's member token (kastr_serve's handler verifies it; None outside kastr_serve).
        -> (claims, error_reply) -- claims when the token covers `room` and the relay here is secured."""
        fn = getattr(handler, "_room_claims", None)
        if not callable(fn):
            return None, ({"error": "feed changes only from the machine itself"}, 403)
        import kastr_relay
        relay_srv = getattr(handler, "kastr_relay_srv", None)
        if relay_srv is None or not getattr(relay_srv, "secured", False):
            return None, ({"error": "web clients may add cameras only through a relay that requires access codes"}, 403)
        err = fn(room, jwt)
        if err is not None:
            return None, ({"error": err[1]}, err[0])
        claims = getattr(handler, "_claims", None)
        if kastr_relay.claims_role(claims) not in ("publisher", "admin", "relay"):
            return None, ({"error": "the publisher access code is needed to add a camera"}, 403)
        return claims, None

    def bearer():
        h = str(handler.headers.get("Authorization") or "")
        return h[7:].strip() if h.lower().startswith("bearer ") else ""

    if path == "/api/rtsp/list":
        if not from_loopback():
            # 0.21.2: a web client with a publisher token sees the room's host-published feeds (redacted) + whether it may add
            q = dict(kv.split("=", 1) if "=" in kv else (kv, "") for kv in getattr(handler, "path", "").partition("?")[2].split("&") if kv)
            room = q.get("room", "")
            jwt = bearer() or q.get("jwt", "")
            if room and jwt:
                claims, err = remote_claims(room, jwt)
                if claims is not None:
                    import kastr_relay
                    me = ""
                    try:
                        _r, me_host = kastr_relay.claims_identity(claims)
                        me = str(me_host or "")
                    except Exception:
                        pass
                    rows = [f for f in bridge.list(redact=True) if str((f.get("publish") or {}).get("broadcast") or "").startswith(room + "/")]
                    enc = bridge.usable_encoder()
                    reply({"feeds": rows, "ffmpeg": bool(bridge.ffmpeg), "ffmpegPath": "", "moq": bool(bridge.moq), "remote": True,
                           "viaHost": True, "canAdd": bool(enc and enc != "libx264"), "hwEncoder": enc, "me": me})
                    return True
            # 0.17.0: a web client has no bridge here -- the page hides its RTSP paths
            reply({"feeds": [], "ffmpeg": False, "ffmpegPath": "", "moq": False, "remote": True})
            return True
        hk = getattr(bridge, "hooks", None)
        reply({"feeds": bridge.list(redact=False),
               "ffmpeg": bool(bridge.ffmpeg),
               "ffmpegPath": bridge.ffmpeg or "",
               "moq": bool(bridge.moq),                       # 0.9.1: native publishing available
               "hooks": (hk.configured() if hk else {}),       # 0.18.0: which hooks are set (never the commands)
               "hookLog": (list(hk.fired) if hk else []),
               "suspended": bool(getattr(bridge, "suspended", False))})   # 0.21.16: the box's RTSP switch
        return True

    if path in ("/api/rtsp/publish", "/api/rtsp/unpublish", "/api/rtsp/nudge", "/api/rtsp/suspend",   # 0.21.16: suspend
                "/api/rtsp/heal",                                            # 0.21.93: a viewer's video stall
                "/api/rtsp/pause", "/api/rtsp/retarget",                                             # 0.21.73: a share paused / swapped
                "/api/rtsp/keep", "/api/rtsp/persist", "/api/rtsp/note",    # 0.12.0: keep, persist; 0.21.5: note
                "/api/rtsp/xs",                                             # 0.21.75: the other rooms a camera shows in
                "/api/rtsp/library",                                        # 0.21.84: the stream library switches
                "/api/rtsp/transport"):                                     # 0.21.96: Auto / TCP / UDP per rtsp:// camera
        # 0.9.1: local pages only -- these start processes and name relays
        if not from_loopback():
            reply({"error": "publishing is controlled from the machine itself"}, 403)
            return True
        if path == "/api/rtsp/persist" and getattr(handler, "command", "POST") != "POST":   # 0.12.0: GET = read-back
            reply(bridge.session_public())
            return True
        if path == "/api/rtsp/library" and getattr(handler, "command", "POST") != "POST":   # 0.21.84: GET = read-back
            reply(bridge.lib_public())
            return True
        try:
            n = int(handler.headers.get("Content-Length") or 0)
            payload = json.loads(handler.rfile.read(n) or b"{}")
        except Exception:
            reply({"error": "bad json"}, 400)
            return True
        bo = getattr(bridge, "boxout", None)   # 0.21.96: box-out -- this machine's own page never puts it in a real room
        try:
            boxed = bool(callable(bo) and bo())
        except Exception:
            boxed = False
        if boxed and path in ("/api/rtsp/publish", "/api/rtsp/persist"):
            want = str(payload.get("broadcast") or "") if path == "/api/rtsp/publish" else str(payload.get("room") or "")
            want = want.strip().lower().split("/", 1)[0]
            if boxout_real_room(want):
                reply({"error": BOXOUT_REFUSED, "boxed": True}, 403)
                return True
        try:
            if path == "/api/rtsp/publish":
                had_pubs = bool(getattr(bridge, "_pubs", None))   # 0.21.16: the first camera record -> the hub's Cameras column
                pub = bridge.publish(payload.get("id"), payload.get("broadcast"), payload.get("relay"),
                                     hevc=bool(payload.get("hevc")),   # 0.9.2 (old name)
                                     audio=(payload.get("audio") is not False),   # 0.9.5: default on
                                     passthrough=bool(payload.get("passthrough", payload.get("hevc"))),   # 0.9.6
                                     force=bool(payload.get("force")),   # 0.9.8: otherwise the same request keeps the running pair
                                     keep=payload.get("keep"),           # 0.12.0: None = leave as is (new pair: on)
                                     ondemand=bool(payload.get("ondemand")), low=bool(payload.get("low")),   # 0.18.0
                                     label=str(payload.get("label") or ""),
                                     idle=bool(payload.get("idle")))   # 0.21.73: a grid camera -- encodes only while watched
                if not had_pubs:   # 0.21.16: a spoke re-registers now -- the hub's spokes table learns it HAS cameras (and their switch) at once, not at the 10-min tick
                    try:
                        getattr(handler, "kastr_relay_srv", None).spoke_sync_soon()
                    except Exception:
                        pass
                reply(pub.info())
            elif path == "/api/rtsp/unpublish":
                ok_un = bridge.unpublish(payload.get("id"))
                if not getattr(bridge, "_pubs", None):   # 0.21.16: the last camera record went -- the hub's column says so now
                    try:
                        getattr(handler, "kastr_relay_srv", None).spoke_sync_soon()
                    except Exception:
                        pass
                reply({"ok": ok_un})
            elif path == "/api/rtsp/keep":                                # 0.12.0
                reply({"ok": bridge.set_keep(payload.get("id"), payload.get("keep"))})
            elif path == "/api/rtsp/persist":                             # 0.12.0: the page's room + access code
                room = str(payload.get("room") or "").strip().lower()
                if not re.match(r"^[a-z0-9-]{0,32}$", room):
                    raise ValueError("bad room name")
                relay = str(payload.get("relay") or "").strip()
                if relay and not relay.lower().startswith(("http://", "https://")):
                    raise ValueError("relay must be an http(s) url")
                bridge.set_session(room, payload.get("access"), payload.get("roomCode"), relay)
                reply(bridge.session_public())
            elif path == "/api/rtsp/suspend":                             # 0.21.16: the box's RTSP switch -- {suspend: bool, who?}; {} = read-back
                if payload.get("suspend") is None:
                    reply({"ok": True, "suspended": bool(getattr(bridge, "suspended", False))})
                else:
                    who = re.sub(r"[^A-Za-z0-9 ._#:-]+", "", str(payload.get("who") or "operator")).strip()[:24] or "operator"
                    res = bridge.suspend(who) if payload.get("suspend") else bridge.resume(who)
                    try:   # the hub's spokes table (Cameras column) follows a local flip now, not at the next registration
                        getattr(handler, "kastr_relay_srv", None).spoke_sync_soon()
                    except Exception:
                        pass
                    reply(res)
            elif path == "/api/rtsp/pause":                               # 0.21.73: {id, paused}
                info = bridge.pause(payload.get("id"), bool(payload.get("paused")))
                reply(info if info is not None else {"error": "no such share"}, 200 if info is not None else 404)
            elif path == "/api/rtsp/retarget":                            # 0.21.73: {id, url}
                reply(bridge.retarget(payload.get("id"), payload.get("url")))
            elif path == "/api/rtsp/xs":                                  # 0.21.75: {id, rooms: [slug], codes?: {slug: code}}
                reply(bridge.set_xs(payload.get("id"), payload.get("rooms"), payload.get("codes")))
            elif path == "/api/rtsp/library":                             # 0.21.84: {id, on: true|false|null} | {master: bool} | {}
                if "master" in payload:
                    reply(bridge.set_lib_master(payload.get("master")))
                elif "id" in payload and "list" in payload:              # 0.21.85: a native share LISTED (kept in its room)
                    reply(bridge.set_lib_list(payload.get("id"), payload.get("list")))
                elif "id" in payload:
                    reply(bridge.set_lib(payload.get("id"), payload.get("on")))
                elif "shares" in payload:                                 # 0.21.85: the page's own listed shares
                    reply(bridge.lib_shares(payload))
                else:
                    reply(bridge.lib_public())
            elif path == "/api/rtsp/transport":                           # 0.21.96: {id, transport} -> {ok, transport, transportNow}
                reply(bridge.set_transport(payload.get("id"), payload.get("transport")))
            elif path == "/api/rtsp/heal":                                # 0.21.93: {id, why} -> {did, reason?|n}
                reply(bridge.heal(payload.get("id"), str(payload.get("why") or "viewer-video").strip()[:32]))
            elif path == "/api/rtsp/note":                                # 0.21.5: the page's grid events -> launch.log
                text = re.sub(r"\s+", " ", str(payload.get("text") or "")).strip()[:400]   # 0.21.93: was 240 -- a video-stall line carries its clocks + caption
                if text:
                    bridge.log("page: " + text)
                    if text.startswith("box-out:") and callable(getattr(bridge, "boxout_note", None)):   # 0.21.96: + /api/diag _boxout
                        bridge.boxout_note("page: " + text)
                reply({"ok": bool(text)})
            else:
                why = str(payload.get("why") or "api").strip()[:32] or "api"   # 0.13.1
                reply({"ok": bridge.nudge(payload.get("id"), why)})
        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            reply({"error": str(e)}, 400)
        return True

    if path in ("/api/rtsp/add", "/api/rtsp/remove"):
        try:
            n = int(handler.headers.get("Content-Length") or 0)
            payload = json.loads(handler.rfile.read(n) or b"{}")
        except Exception:
            reply({"error": "bad json"}, 400)
            return True
        if not from_loopback():
            # 0.21.2: a WEB CLIENT adds a camera that THIS host pulls -- publisher token for the room, hardware encoder
            room = str(payload.get("room") or "")
            jwt = bearer() or str(payload.get("jwt") or "")
            claims, err = remote_claims(room, jwt)
            if claims is None:
                reply(*err)
                return True
            import kastr_relay
            op = ""
            try:
                op = str(kastr_relay.claims_identity(claims)[1] or "")   # the web device's host id -- People keys on op; use the name the page sends
            except Exception:
                pass
            who = re.sub(r"[^a-z0-9-]+", "-", str(payload.get("op") or op or "web").lower()).strip("-")[:40] or "web"
            try:
                if path == "/api/rtsp/add":
                    if not bridge.ffmpeg:
                        reply({"error": "ffmpeg not available on the host"}, 503)
                        return True
                    reply(bridge.remote_add(payload.get("url"), room, payload.get("label"), who))
                else:
                    feed = bridge.get(payload.get("id"))
                    if feed is None:
                        reply({"error": "no such feed"}, 404)
                        return True
                    if getattr(feed, "added_by", "") != who and not kastr_relay.claims_admin(claims, room):
                        reply({"error": "only the person who added this camera (or an admin) can remove it"}, 403)
                        return True
                    reply({"ok": bridge.remove(feed.id)})
            except (ValueError, KeyError, TypeError) as e:
                reply({"error": str(e)}, 400)
            return True
        try:
            if path == "/api/rtsp/add":
                if not bridge.ffmpeg:
                    reply({"error": "ffmpeg not available"}, 503)
                    return True
                feed = bridge.add(payload.get("url"))
                if is_screen(feed.url) and payload.get("presenter"):   # 0.21.20: the page composites it -- a 1920-wide monitor, no native pair
                    feed.presenter = True
                reply(feed.info())
            else:
                reply({"ok": bridge.remove(payload.get("id"))})
        except (ValueError, KeyError, TypeError) as e:
            reply({"error": str(e)}, 400)
        return True

    reply({"error": "unknown endpoint"}, 404)
    return True


def parse_stream_path(path):
    """/rtsp/<id>[?pt=1][&transcode=1] -> (id, transcode, passthrough). 0.9.6:
    the page says whether copying is allowed (pt) and whether a copy failed to
    play in its <video> (transcode)."""
    base, _, query = path.partition("?")
    flags = {kv.split("=", 1)[0]: kv.split("=", 1)[1] if "=" in kv else "1" for kv in query.split("&") if kv}
    return base.rsplit("/", 1)[-1], flags.get("transcode") == "1", flags.get("pt") == "1"


def stream_query(handler, path):
    """0.21.96: the monitor path WITH its query. kastr_serve's do_GET hands handle_stream the path with the query cut
    off, so since 0.14.0 the page's pt=1 / transcode=1 never arrived: the 'converting the preview to H.264' fallback
    asked for an encode and got the same copy again. The raw request line still has them."""
    if "?" in path:
        return path
    raw = str(getattr(handler, "path", "") or "")
    return raw if raw.split("?", 1)[0] == path else path


_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_WS_SAID = [False]


def _ws_frame(payload, opcode=0x2):
    """0.21.10: one unmasked server->client WebSocket frame (FIN set)."""
    n = len(payload)
    if n < 126:
        head = bytes([0x80 | opcode, n])
    elif n < 65536:
        head = bytes([0x80 | opcode, 126]) + n.to_bytes(2, "big")
    else:
        head = bytes([0x80 | opcode, 127]) + n.to_bytes(8, "big")
    return head + payload


def _ws_watch(conn, alive):
    """0.21.10: answer the browser's close and ping frames on a monitor socket. A detached monitor
    sends a close frame and Chromium then waits up to 60 s for ours before dropping TCP; without
    this the pump would keep an ffmpeg child busy that long. recv only after select says readable,
    so the pump's SEND_TIMEOUT never trips here."""
    import select
    import socket
    try:
        while alive[0]:
            r, _, _ = select.select([conn], [], [], 1.0)
            if not r:
                continue
            data = conn.recv(4096)
            if not data:
                break
            op = data[0] & 0x0F
            if op == 0x8:
                try:
                    conn.sendall(bytes([0x88, 0x00]))
                except OSError:
                    pass
                break
            if op == 0x9:
                try:
                    conn.sendall(bytes([0x8A, 0x00]))
                except OSError:
                    pass
    except (OSError, ValueError):
        pass
    if alive[0]:
        alive[0] = False
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

def handle_stream(handler, bridge, path):
    """Serve GET /rtsp/<id> as an endless fragmented MP4."""
    if not path.startswith("/rtsp/"):
        return False
    import kastr_relay
    if not kastr_relay.is_local(handler):   # 0.17.0: the monitor is the owner page's
        handler.send_error(403, "feed monitors only for the machine itself")
        return True
    feed_id, transcode, passthrough = parse_stream_path(stream_query(handler, path))
    try:
        feed = bridge.get(feed_id)
    except ValueError:
        feed = None
    if not feed:
        handler.send_error(404, "no such feed")
        return True
    if getattr(bridge, "suspended", False):   # 0.21.16: no monitor decode while the box's RTSP switch is off (the page does not retry meanwhile)
        handler.send_error(503, "RTSP publishing is suspended on this box")
        return True

    # 0.21.11: the monitor follows the camera's publisher. The page sends pt=1 only when its own localStorage
    # switch is on; a box whose pairs were restored with passthrough=true (the operator's choice, persisted) was
    # re-encoding every monitor -- five software 4K H.265 decodes on one relay box. A copied monitor the page
    # cannot decode still falls back to transcode=1 on its own (monitorBroken), so this only ever removes work.
    if not passthrough and not transcode:
        pub = getattr(bridge, "_pubs", {}).get(feed.id)
        if pub is not None and getattr(pub, "passthrough", False) and getattr(pub, "copy", False):
            passthrough = True
            if not getattr(feed, "_mon_pt_said", False):
                feed._mon_pt_said = True
                bridge.log("rtsp monitor: feed %s follows its publisher's passthrough (copy, %s)" % (feed.id, getattr(pub, "codec", None) or "?"))

    try:
        proc = bridge.spawn(feed, transcode=transcode, passthrough=passthrough)
    except RuntimeError as e:
        handler.send_error(503, str(e))
        return True

    codec, copied = bridge.monitor_codec(feed, transcode, passthrough)
    # 0.21.10: the page asks for the monitor over a WebSocket when it can. Chromium allows six
    # concurrent HTTP/1.1 connections per host and every monitor held one for as long as the camera
    # streamed, so the seventh camera -- and every fetch the page made after it -- waited in the
    # browser's queue until a stream closed. WebSockets sit outside that pool. Same bytes, framed.
    ws_key = (handler.headers.get("Sec-WebSocket-Key") or "").strip()
    ws = bool(ws_key) and (handler.headers.get("Upgrade") or "").strip().lower() == "websocket"
    if ws:
        import base64
        import hashlib
        accept = base64.b64encode(hashlib.sha1((ws_key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
        try:
            handler.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                                 "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode("ascii"))
            handler.wfile.write(_ws_frame(json.dumps({"codec": codec, "copy": copied}).encode("utf-8"), 0x1))
        except (BrokenPipeError, ConnectionResetError, OSError):
            bridge.release(feed, proc)
            return True
        if not _WS_SAID[0]:
            _WS_SAID[0] = True
            bridge.log("rtsp monitor: streaming over WebSocket (outside the browser's six-connection cap)")
    else:
        handler.send_response(200)
        handler.send_header("Content-Type", "video/mp4")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-KASTR-Codec", codec)          # 0.9.7: the page's MSE player needs it up front
        handler.send_header("X-KASTR-Copy", "1" if copied else "0")
        # No Content-Length: the stream is open-ended, so the connection staying
        # open IS the framing.
        handler.end_headers()

    # Set AFTER the headers so it governs only the pump (the request itself
    # was fully read before dispatch). socket.timeout is an OSError, so the
    # except below already catches it, and this server speaks HTTP/1.0 with
    # connection-close framing, so the timeout cannot leak into another
    # request. The page-side live-edge keeper is what makes 15s safe: a
    # healthy reader is never more than ~3s behind, so only a genuinely
    # wedged one goes quiet this long.
    handler.connection.settimeout(SEND_TIMEOUT)

    alive = [True]
    if ws:
        threading.Thread(target=_ws_watch, args=(handler.connection, alive), daemon=True).start()
    try:
        while True:
            chunk = proc.stdout.read(16384)
            if not chunk:
                break
            handler.wfile.write(_ws_frame(chunk) if ws else chunk)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass          # viewer navigated away
    finally:
        alive[0] = False
        # Only this reader's child -- another connection to the same feed may
        # still be streaming.
        bridge.release(feed, proc)
    return True
