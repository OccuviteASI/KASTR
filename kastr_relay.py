#!/usr/bin/env python3
"""Supervises a bundled moq-relay, so KASTR can BE the relay as well as use one.

moq-relay is the upstream Rust server (kixelated/moq). Speaking moq-lite over
QUIC/WebTransport is not something to reimplement, so the official binary is
bundled and driven here -- the same approach as ffmpeg for RTSP.

Configuration goes through a generated TOML file rather than CLI flags: the
public-access prefix for an unauthenticated relay is the empty string, and an
empty argv entry is unreliable to pass through a Windows shell.

Secured mode (0.7.0): the relay verifies HS256 JWTs against a locally
generated JWK, and a tiny token service on relay-port+1 mints them -- room
codes are the only credential. Lock holders register {slug, salt, hash}
records; joiners present the raw code. The room table is in-memory: holders
re-POST on a heartbeat, so a restart heals itself. Room listing and stats
stay public (subscribe-only) so the pre-join screen needs no token.

Access codes (0.10.0): relay-wide VIEWER and PUBLISHER codes, kept hashed
(PBKDF2-HMAC-SHA256) in relay-auth.json beside the locked-room records, decide
the ROLE of a token; the room decides its paths. With codes configured every
room -- main included -- refuses to mint without one. A viewer token can
subscribe to the room and announce the presence-class kinds (.since, .stalled,
.spotlight, .recording, .mediactl, .avatar) but carries no publish claim on
media; the relay drops such an announce and keeps the session (measured
2026-09-18: claims may be arrays, prefix matching is per path segment). Room
codes remain an extra per-room lock. Without codes a secured relay keeps the
0.7-0.9 behaviour (any room code mints) and status() says so (`legacy`).
The relay control plane (/api/relay/* POSTs) answers the machine itself only.

Endpoints (wired up by kastr_serve):
    GET  /api/relay/status  -> {running, url, port, bind, fingerprint, codes, legacy, ...}
    POST /api/relay/start   {"port":4443,"lan":true,"secured":true}   (persists the shape)
    POST /api/relay/stop
    GET  /api/relay/codes   -> {"viewer":bool,"publisher":bool,"federation":bool,"configured":bool}
    POST /api/relay/codes   {"viewer":"..."|""|null, "publisher":..., "federation":...}  ("" clears, null keeps)
    GET  /api/relay/cluster -> {"connect","master","hasCode"};  POST {connect?, code?, master?}  (0.11.0)
    POST /api/relay/rotate  -> new signing key (every token dies), relay restarted
    GET  /api/relay/rooms   -> {"rooms":[{slug,locked,persistent,creator,created,at}], "closed":{slug:ts_ms}, "groups":{gid:{name,order,rooms}}}  (0.12.0; 0.15.0 groups)
    POST /api/relay/rooms/close {"slug"}  -> operator close: record, chat and attachments gone (0.12.0)
    POST /api/relay/rooms/group {"op":"create|rename|delete|assign","gid"?,"name"?,"order"?,"slug"?} -> {"ok":true,"groups"}  (0.15.0, operator)
Token service (its own listener, relay-port+1):
    GET  /api/auth          -> {"app":"KASTR","secured":true,"codes":bool,"legacy":bool,"federation":bool,"kid":...,"state":true,"web":int|null,"https":int|null}
    GET  /api/rooms         -> {"rooms":[{"slug","locked","persistent","creator","created","at"}],"groups":{gid:{name,order,rooms}}}   (0.11.0 names; 0.12.0 rows; 0.15.0 groups)
    POST /api/room          {"slug","salt"?,"hash"?,"roomKey"?,"code"?,"access"?,"persistent"?,"creator"?,"rekey"?}  (0.12.0: kept rooms)
    POST /api/token         {"federation":"<code>"} -> {"ok":true,"role":"relay","token",...}  (0.11.0)
    POST /api/room          {"slug","salt","hash","roomKey"?,"code"?,"access"?}
    POST /api/token         {"room","code","roomCode"?,"host"?} -> {"ok":true,"role","exp",tokens:{member,registry}}
                            0.13.0: with "host" (<slug>-<4 hex>) the member token's puts are scoped to that
                            host's own paths (+ the .state/<room>/<host> track); without it the 0.12 shape.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import kastr_rtsp

LOG_LINES = 200
TOKEN_TTL = 86400          # 24 h: outlives a shift; refresh handles the rest
VIEWER_TTL = 43200         # 0.10.0: a viewer token lives half a day (pages re-mint at <10 min)
ROOM_TTL = 86400           # 0.10.0: a persisted room record without a heartbeat for a day is forgotten
PBKDF2_ITER = 100000       # 0.10.0: relay access codes (the lockout bounds the cost of a wrong guess)
# The dotted announce kinds a viewer legitimately publishes (presence, stall
# reports, spotlight votes, recording notice, media control pulses, avatar).
# .grid, .files and .media stay publisher-only.
VIEWER_KINDS = (".since", ".stalled", ".spotlight", ".recording", ".mediactl", ".avatar")
LOOPBACK_PEERS = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
# 0.11.0: federation. A spoke relay dials the hub with a token the HUB minted
# from its federation code (HS256 is symmetric, so the hub must be the signer;
# no key is shared between machines). The token covers the whole namespace
# both ways; the spoke's watchdog re-mints before it ends or when the hub's
# key changes (/api/auth `kid`).
FEDERATION_TTL = 30 * 86400
FEDERATION_RENEW = 7 * 86400
FEDERATION_CHECK = 600
FEDERATION_CLAIMS = {"root": "", "put": "", "get": ""}
SLUG_RE = re.compile(r"[a-z0-9-]{1,32}$")
# 0.12.0: kept (persistent) rooms -- their records and chat outlive the 24 h
# heartbeat window -- are capped, and a closed room leaves an hour-long
# tombstone so pages learn WHY the chat answers 410.
KEPT_MAX = 64
GROUPS_MAX = 32            # 0.15.0: room groups a relay defines (shared by every page dialled in)
GROUP_ROOMS_MAX = 64       # 0.15.0: rooms in one group
CLOSED_TTL = 3600
# 0.12.0: root-prefixed announce kinds every member may put beside .presence:
# .talking/<room> (who is speaking) and .chat/<room> (a new-message nudge).
MEMBER_KINDS = (".presence", ".talking", ".chat")
# 0.16.0: the ADMIN role. A third relay-wide code; its token also puts under
# <room>/.admin, where stop / mute / kick commands ride as track-less announces
# (viewer and publisher grants have no .admin pattern, so the relay drops a
# forged command at the door). A spoke without an admin code of its own asks
# its hub's minter to verify the code (POST /api/token {admin, verify:true}).
ADMIN_KIND = ".admin"
# 0.16.0: a spoke pins the hub's QUIC certificate; when the relay reports a
# certificate problem on the cluster link the pin is re-learned (the hub's
# generated cert changes on every hub start).
# 0.16.0 (measured on the rig, moq-relay 0.15.1, hub restarted with a new cert): the QUIC dial fails silently,
# the WebSocket fallback logs 'WebSocket connection failed err=... received corrupt message of type
# InvalidContentType' and the cluster loop logs 'cluster peer error; will retry'. Both are matched: a re-learn
# is cheap (debounced 30 s, restarts the relay only when the pin actually changed), and a hub that is merely
# down answers with its cached pin, so an outage never churns the spoke.
TLS_FAIL_RE = re.compile(r"invalid peer certificate|fingerprint[^\n]*(mismatch|not match|unknown)|UnknownIssuer|CertificateUnknown|BadSignature|InvalidContentType|cluster peer error", re.I)
LAN_SECRET_RE = re.compile(r"^[0-9a-f]{64}$")
# 0.13.0: state tracks. Each member publishes its facts as JSON tracks under
# `.state/<room>/<host>` (public, subscribe-only, so the lobby reads them);
# a token scoped to a host may write only that host's paths. The claim
# strings carry NO trailing slash: the relay matches per path segment, so
# "r1/host" covers r1/host/..., not r1/hostx.
STATE_PREFIX = ".state"
HOST_RE = re.compile(r"^[a-z0-9-]{1,32}-[0-9a-f]{4}$")
# 0.16.0: moq-relay 0.15 no longer verifies JWTs itself -- it POSTs one JSON
# Request per session event (connect | revalidate | end) to [auth] url and
# applies the Grant we answer: {publish: [patterns], subscribe: [patterns],
# root?, expires?, revalidate?}. The token service on relay port+1 answers
# that (POST /api/session, loopback only) by verifying OUR tokens -- the exact
# 0.13-shaped {root, put, get, exp} claims the minter still issues, so 0.15.1
# pages and native publishers keep working -- and translating the prefix
# lists into patterns ("main" -> "main", "main/**").
PUBLIC_KINDS = (".channels", ".stats", ".presence", ".talking", ".chat", ".state")   # subscribe-only for anyone (the pre-join screen, bubbles, stats)
SESSION_REVALIDATE = 600     # s: the relay re-asks; a rotated key ends every session within this
SESSIONS_MAX = 4096

# moq-relay colourises its output even when piped, which would render as
# literal escape sequences in the log panel.
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def find_relay():
    """Bundled copy first, then PATH."""
    exe = "moq-relay.exe" if sys.platform == "win32" else "moq-relay"
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.join(sys._MEIPASS, "bin"))
    roots.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin"))
    for root in roots:
        cand = os.path.join(root, exe)
        if os.path.exists(cand):
            kastr_rtsp._ensure_exec(cand)
            return cand
    # 0.13.1: a Finder-launched .app has a bare PATH -- Homebrew's bin first on macOS
    fb = getattr(kastr_rtsp, "_darwin_fallback", None)
    return (fb(exe) if fb else None) or shutil.which("moq-relay")


def local_ips():
    """IPv4 addresses other machines could reach this one on."""
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "169.254.")) and ip not in out:
                out.append(ip)
    except OSError:
        pass
    return out


# ---- tokens (0.7.0) --------------------------------------------------------
#
# Pure stdlib on purpose: the frozen app carries no crypto wheels, HS256 is
# hmac+sha256, and the signer and verifier are the same machine -- symmetric
# is the correct choice here, not a compromise.

def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _ensure_jwk(state_dir):
    """The relay's signing key, generated once and kept next to the config so
    outstanding tokens survive a relay bounce. Delete the file to rotate."""
    path = os.path.join(state_dir, "auth.jwk")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            k = json.load(f).get("k", "")
        return path, base64.urlsafe_b64decode(k + "=" * (-len(k) % 4))
    key = os.urandom(32)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"kty": "oct", "alg": "HS256", "k": _b64u(key)}, f)
    return path, key


def key_id(key):
    """0.11.0: a public fingerprint of the signing key (spokes detect rotation)."""
    return hashlib.sha256(key).hexdigest()[:16]


def _mint(key, claims):
    head = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"},
                            separators=(",", ":")).encode())
    body = _b64u(json.dumps(claims, separators=(",", ":")).encode())
    signing = (head + "." + body).encode("ascii")
    return head + "." + body + "." + _b64u(hmac.new(key, signing, hashlib.sha256).digest())


def _room_code_ok(rec, code):
    """The page's advisory scheme, verified server-side: sha256(salt + code)."""
    try:
        want = str(rec.get("hash") or "")
        got = hashlib.sha256((str(rec.get("salt") or "") + str(code)).encode()).hexdigest()
        return bool(want) and hmac.compare_digest(want, got)
    except Exception:
        return False


# ---- 0.12.0: verification (kastr_serve checks chat callers with the relay's key)

def read_jwk(state_dir):
    """The signing key IF it exists -- never generated here. None means the
    relay on this machine was never secured (or the key was rotated away)."""
    try:
        with open(os.path.join(state_dir, "auth.jwk"), "r", encoding="utf-8") as f:
            k = str(json.load(f).get("k") or "")
        return base64.urlsafe_b64decode(k + "=" * (-len(k) % 4)) if k else None
    except Exception:
        return None


def _b64u_dec(s):
    s = str(s or "")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_token(tok, key, now=None):
    """HS256 signature + exp -> the claims dict, or None for anything else."""
    if not key or not tok:
        return None
    try:
        head, body, sig = str(tok).split(".")
        signing = (head + "." + body).encode("ascii")
        want = hmac.new(key, signing, hashlib.sha256).digest()
        if not hmac.compare_digest(want, _b64u_dec(sig)):
            return None
        if json.loads(_b64u_dec(head).decode("utf-8")).get("alg") != "HS256":
            return None
        claims = json.loads(_b64u_dec(body).decode("utf-8"))
        if not isinstance(claims, dict):
            return None
        exp = claims.get("exp")
        if exp is None or float(exp) <= (time.time() if now is None else now):
            return None
        return claims
    except Exception:
        return None


def is_relay_claims(claims):
    """The federation shape (root, put and get all ""): a relay, not a person."""
    return (isinstance(claims, dict) and claims.get("root") == ""
            and claims.get("put") == "" and claims.get("get") == "")


def claims_cover(claims, room):
    """Does a member token admit `room`? Its `get` names the room (a string or
    a list), or the token is rooted there. Viewers chat too: `get` suffices."""
    if not isinstance(claims, dict) or not room:
        return False
    if claims.get("root") == room:
        return True
    get = claims.get("get")
    if isinstance(get, str):
        return get == room
    if isinstance(get, (list, tuple)):
        return room in get
    return False


# ---- 0.16.0: the relay's per-session auth contract -------------------------

def _patterns(v):
    """A KASTR claim prefix (str or list) -> relay 0.15 patterns. "" -> ["**"];
    "main" -> ["main", "main/**"]; ".state/main/h-1a2b" -> [itself, itself/**].
    Per-segment semantics are preserved ("r1/host/**" never covers r1/hostx)."""
    items = v if isinstance(v, (list, tuple)) else [v]
    out = []
    for it in items:
        if it is None:
            continue
        p = str(it).strip().strip("/")
        if p == "":
            return ["**"]
        for q in (p, p + "/**"):
            if q not in out:
                out.append(q)
    return out


def public_patterns():
    out = []
    for k in PUBLIC_KINDS:
        out += [k, k + "/**"]
    return out


def public_grant():
    """What a tokenless session gets: the public kinds, subscribe only (today's
    `public = { subscribe = [...] }`). Publishing always needed a token."""
    return {"publish": [], "subscribe": public_patterns()}


def claims_to_grant(claims, now=None):
    """Verified claims -> the relay's Grant. Accepts the 0.13 shape {root, put,
    get, exp} (str or list values), the federation shape (root/put/get all "")
    and a future {publish: [...], subscribe: [...]} shape. The public kinds are
    always added to `subscribe` (public stays public)."""
    now = time.time() if now is None else now
    if is_relay_claims(claims):
        pub, sub = ["**"], ["**"]
    elif "publish" in claims or "subscribe" in claims:
        pub = [str(x) for x in (claims.get("publish") or []) if x is not None]
        sub = [str(x) for x in (claims.get("subscribe") or []) if x is not None]
    else:
        pub = _patterns(claims.get("put")) if claims.get("put") is not None else []
        sub = _patterns(claims.get("get")) if claims.get("get") is not None else []
    if "**" not in sub:
        for q in public_patterns():
            if q not in sub:
                sub.append(q)
    grant = {"publish": pub, "subscribe": sub}
    root = str(claims.get("root") or "")
    if root:
        grant["root"] = root
    try:
        exp = int(float(claims.get("exp")))
        grant["expires"] = exp
        grant["revalidate"] = max(30, min(SESSION_REVALIDATE, exp - int(now)))
    except (TypeError, ValueError):
        pass
    return grant


def session_jwt(req):
    """The `?jwt=` a session dialled with: the Request's raw `query`, or a query
    left in `path`."""
    from urllib.parse import parse_qs
    q = str(req.get("query") or "")
    path = str(req.get("path") or "")
    if not q and "?" in path:
        q = path.split("?", 1)[1]
    q = q.lstrip("?")
    return (parse_qs(q).get("jwt") or [""])[0]


def claims_identity(claims):
    """0.17.0: (room, host) a member token names -- room = its `get` (one room per member
    token), host = the `<host>` of its `.state/<room>/<host>` put. (None, None) for a
    federation or 0.12-shaped wide token. This is the identity a relay-side kick bans:
    operator and peer are not in the token."""
    try:
        room = claims.get("get")
        if not isinstance(room, str) or not room:
            return None, None
        host = None
        for p in _patterns(claims.get("put")) if claims.get("put") is not None else []:
            m = re.match(r"^\.state/%s/([a-z0-9-]{1,32}-[0-9a-f]{4})$" % re.escape(room), str(p))
            if m:
                host = m.group(1)
                break
        return room, host
    except Exception:
        return None, None


def claims_role(claims):
    if is_relay_claims(claims):
        return "relay"
    puts = _patterns(claims.get("put")) if claims.get("put") is not None else []
    for p in puts:
        if p == "**" or (not p.startswith(".") and "/.member" not in p and "/.since" not in p):
            return "publisher"
    return "viewer"


def session_grant(req, key, now=None):
    """The relay's Request -> (status, grant | None, why). status is "grant",
    "public" (no token) or "refuse" (a token that does not verify)."""
    tok = session_jwt(req)
    if not tok:
        return "public", public_grant(), "tokenless"
    claims = verify_token(tok, key, now)
    if claims is None:
        return "refuse", None, "bad or expired token"
    return "grant", claims_to_grant(claims, now), claims_role(claims)


class Lockout:
    """0.10.0's brute-force counter, its own class in 0.12.0 so the minter and
    kastr_serve's room endpoints count the same way: five wrong codes within a
    minute earn a lockout that doubles from 30 s to 10 min."""

    def __init__(self, log=None):
        self.log = log or (lambda m: None)
        self.lock = threading.Lock()
        self._fails = {}         # peer ip -> {n, since, until, len}

    def locked_for(self, peer):
        with self.lock:
            st = self._fails.get(peer)
            if not st:
                return 0
            rem = st.get("until", 0) - time.time()
            return int(rem) + 1 if rem > 0 else 0

    def fail(self, peer, why, slug, what="room"):
        now = time.time()
        locked = 0
        with self.lock:
            st = self._fails.setdefault(peer, {"n": 0, "since": now, "until": 0, "len": 30})
            if now - st["since"] > 60:
                st["n"], st["since"] = 0, now
            st["n"] += 1
            if st["n"] >= 5:
                st["until"] = now + st["len"]
                locked = st["len"]
                st["len"] = min(600, st["len"] * 2)
                st["n"], st["since"] = 0, now
        self.log("relay auth: %s for %s %s from %s%s" % (
            why, what, slug or "?", peer or "?", (" -- locked out for %d s" % locked) if locked else ""))
        if locked:
            return {"error": "too many attempts -- try again in %d s" % locked, "retryAfter": locked}, 429
        return {"error": why}, 403

    def ok(self, peer):
        with self.lock:
            self._fails.pop(peer, None)


class BanList:
    """0.17.0: who an admin removed, so the relay refuses them for a while.

    A ban keys on (room, host): the host slug the member's token carries (a
    machine's `<name>-<4hex>`, a web device's `web-<8hex>-<4hex>`), plus the
    remote addresses of the sessions that were live when the kick landed (for
    0.12-shaped tokens without a host). Kept in relay-bans.json; expired rows
    are pruned on load and on every add. `until` is capped at a day."""

    MAX = 500

    def __init__(self, state_dir, log=None):
        self.state_dir = state_dir
        self.log = log or (lambda m: None)
        self.lock = threading.Lock()
        self.bans = []
        self._load()

    def _path(self):
        return os.path.join(self.state_dir, "relay-bans.json")

    def _load(self):
        try:
            with open(self._path(), encoding="utf-8-sig") as f:
                d = json.load(f)
            rows = d.get("bans") if isinstance(d, dict) else None
            now = time.time()
            self.bans = [b for b in (rows or []) if isinstance(b, dict) and float(b.get("until") or 0) > now]
        except Exception:
            self.bans = []

    def _save(self):
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            tmp = self._path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"bans": self.bans}, f)
            for i in range(6):
                try:
                    os.replace(tmp, self._path())
                    return
                except PermissionError:
                    if i == 5:
                        raise
                    time.sleep(0.02 * (i + 1))
        except Exception as e:
            self.log("relay auth: bans not saved: %s" % e)

    def _prune(self, now):
        self.bans = [b for b in self.bans if float(b.get("until") or 0) > now][-self.MAX:]

    def add(self, ban):
        with self.lock:
            now = time.time()
            self._prune(now)
            # one row per (room, host|target): a repeat kick extends it
            key = (ban.get("room"), ban.get("host") or ban.get("target"))
            self.bans = [b for b in self.bans if (b.get("room"), b.get("host") or b.get("target")) != key]
            self.bans.append(ban)
            self._save()
        return ban

    def hit(self, room, host, remote=None, now=None):
        """The active ban covering this identity, or None."""
        now = now or time.time()
        with self.lock:
            for b in self.bans:
                if float(b.get("until") or 0) <= now or b.get("room") != room:
                    continue
                if host and b.get("host") and b.get("host") == host:
                    return dict(b)
                if remote and not b.get("host") and remote in (b.get("remotes") or []) and not is_loopback_addr(remote):
                    return dict(b)
            return None

    def active(self, room=None):
        now = time.time()
        with self.lock:
            return [dict(b) for b in self.bans if float(b.get("until") or 0) > now and (room is None or b.get("room") == room)]

    def clear(self, room, host=None):
        with self.lock:
            before = len(self.bans)
            self.bans = [b for b in self.bans if not (b.get("room") == room and (host is None or b.get("host") == host))]
            n = before - len(self.bans)
            if n:
                self._save()
            return n


class AuthStore:
    """0.10.0: what a secured relay remembers, in state_dir/relay-auth.json --
    the relay-wide viewer and publisher access codes (PBKDF2-HMAC-SHA256, a
    salt per code, never the code itself) and the locked rooms
    ({slug: salt, hash, roomKey, at}). Persisted so a relay bounce forgets
    nothing: the in-memory room table of 0.7-0.9 emptied on every restart,
    which is exactly when tokens for unregistered rooms minted for free.
    0.12.0: a record may also carry `persistent` (kept: never expires, may be
    unlocked -- no salt/hash), `creator` (an operator slug) and `created`;
    `closed` = {slug: ts_ms} remembers rooms closed within the hour."""

    def __init__(self, state_dir, log=None):
        self.state_dir = state_dir
        self.log = log or (lambda m: None)
        self.lock = threading.Lock()
        self.codes = {"viewer": None, "publisher": None, "federation": None, "admin": None}   # 0.11.0: + federation; 0.16.0: + admin
        self.lan = {"enabled": False, "secret": None, "at": 0}   # 0.16.0: mDNS LAN mesh (secret = 64 hex, plaintext, loopback-written, never echoed)
        self.rooms = {}
        self.closed = {}         # 0.12.0: slug -> ms timestamp of its close (CLOSED_TTL)
        self.groups = {}         # 0.15.0: gid -> {"name", "order", "rooms": [slug]} (a slug in at most one group)
        self._load()

    def _path(self):
        return os.path.join(self.state_dir, "relay-auth.json")

    def _load(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return
        for k in ("viewer", "publisher", "federation", "admin"):
            v = d.get(k)
            self.codes[k] = v if isinstance(v, dict) and v.get("salt") and v.get("hash") else None
        lan = d.get("lan")                   # 0.16.0
        if isinstance(lan, dict):
            sec = str(lan.get("secret") or "").lower()
            self.lan = {"enabled": bool(lan.get("enabled")), "secret": sec if LAN_SECRET_RE.match(sec) else None,
                        "at": int(lan.get("at") or 0)}
        rooms = d.get("rooms")
        if isinstance(rooms, dict):
            now = time.time()
            for slug, rec in rooms.items():
                # 0.12.0: a kept room may be unlocked (persistent without salt/hash)
                if isinstance(rec, dict) and ((rec.get("hash") and rec.get("salt")) or rec.get("persistent")):
                    rec.setdefault("at", now)
                    self.rooms[slug] = rec
        closed = d.get("closed")            # 0.12.0
        if isinstance(closed, dict):
            for slug, ts in closed.items():
                try:
                    self.closed[str(slug)] = int(ts)
                except (TypeError, ValueError):
                    pass
            self._prune_closed()
        groups = d.get("groups")            # 0.15.0
        if isinstance(groups, dict):
            seen = set()
            for gid, g in groups.items():
                gid = str(gid)
                if not (isinstance(g, dict) and SLUG_RE.match(gid)) or len(self.groups) >= GROUPS_MAX:
                    continue
                rooms = []
                for s in (g.get("rooms") or []):
                    if isinstance(s, str) and SLUG_RE.match(s) and s not in seen and len(rooms) < GROUP_ROOMS_MAX:
                        rooms.append(s)
                        seen.add(s)
                try:
                    order = int(g.get("order") or 0)
                except (TypeError, ValueError):
                    order = 0
                self.groups[gid] = {"name": str(g.get("name") or gid)[:48], "order": order, "rooms": rooms}

    def _save(self):
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self._path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"viewer": self.codes["viewer"], "publisher": self.codes["publisher"],
                       "federation": self.codes["federation"], "rooms": self.rooms,
                       "admin": self.codes["admin"],   # 0.16.0
                       "lan": self.lan,                # 0.16.0
                       "closed": self.closed,          # 0.12.0: + closed tombstones
                       "groups": self.groups}, f)     # 0.15.0: + room groups
        for i in range(6):
            # 0.12.0: Windows -- a scanner holding the just-written file fails the
            # replace with "access denied" for a moment; registers now save often.
            try:
                os.replace(tmp, self._path())
                return
            except PermissionError:
                if i == 5:
                    raise
                time.sleep(0.02 * (i + 1))

    @staticmethod
    def _derive(code, salt_hex, iters):
        return hashlib.pbkdf2_hmac("sha256", str(code).encode("utf-8"),
                                   bytes.fromhex(salt_hex), int(iters)).hex()

    # ---- relay-wide codes

    def configured(self):
        with self.lock:
            return bool(self.codes["viewer"] or self.codes["publisher"])

    def codes_status(self):
        with self.lock:
            return {"viewer": bool(self.codes["viewer"]), "publisher": bool(self.codes["publisher"]),
                    "federation": bool(self.codes["federation"]), "admin": bool(self.codes["admin"])}   # 0.16.0: + admin

    def set_codes(self, viewer=None, publisher=None, federation=None, admin=None):
        """None = unchanged, "" = clear, anything else = the new code."""
        with self.lock:
            for k, v in (("viewer", viewer), ("publisher", publisher), ("federation", federation), ("admin", admin)):
                if v is None:
                    continue
                v = str(v)
                if v == "":
                    self.codes[k] = None
                else:
                    salt = os.urandom(16).hex()
                    self.codes[k] = {"salt": salt, "hash": self._derive(v, salt, PBKDF2_ITER),
                                     "iter": PBKDF2_ITER}
            self._save()
        return self.codes_status()

    # ---- 0.16.0: mDNS LAN mesh

    def lan_status(self):
        with self.lock:
            return {"enabled": bool(self.lan.get("enabled")), "hasSecret": bool(self.lan.get("secret"))}

    def set_lan(self, enabled=None, secret=None):
        """None = unchanged, secret "" = clear; a secret must be 64 hex characters."""
        with self.lock:
            if secret is not None:
                sec = str(secret).strip().lower()
                if sec == "":
                    self.lan["secret"] = None
                elif LAN_SECRET_RE.match(sec):
                    self.lan["secret"] = sec
                else:
                    raise ValueError("the LAN secret must be 64 hexadecimal characters")
            if enabled is not None:
                self.lan["enabled"] = bool(enabled)
            self.lan["at"] = int(time.time())
            self._save()
        return self.lan_status()

    def lan_secret(self):
        with self.lock:
            return self.lan.get("secret")

    def check(self, kind, code):
        with self.lock:
            rec = self.codes.get(kind)
        if not rec or code is None or code == "":
            return False
        try:
            return hmac.compare_digest(
                self._derive(code, rec["salt"], rec.get("iter") or PBKDF2_ITER), rec["hash"])
        except Exception:
            return False

    # ---- rooms

    def room(self, slug):
        with self.lock:
            rec = self.rooms.get(slug)
            # 0.12.0: a kept room never expires
            if rec and not rec.get("persistent") and time.time() - float(rec.get("at") or 0) > ROOM_TTL:
                del self.rooms[slug]
                try:
                    self._save()
                except OSError:
                    pass
                rec = None
            return dict(rec) if rec else None

    def put_room(self, slug, rec):
        with self.lock:
            self.rooms[slug] = dict(rec)
            self.closed.pop(slug, None)      # 0.12.0: registering a name re-opens it
            self._save()

    def room_slugs(self):
        """Live (unexpired) room names -- for /api/rooms and the codes status."""
        with self.lock:
            now = time.time()
            dead = [k for k, r in self.rooms.items()
                    if not r.get("persistent") and now - float(r.get("at") or 0) > ROOM_TTL]   # 0.12.0
            for k in dead:
                del self.rooms[k]
            if dead:
                try:
                    self._save()
                except OSError:
                    pass
            return sorted(self.rooms)

    # ---- kept rooms + close tombstones (0.12.0)

    def _prune_closed(self):
        """Call with the lock held (or from _load)."""
        cutoff = int(time.time() * 1000) - CLOSED_TTL * 1000
        for k in [k for k, ts in self.closed.items() if ts < cutoff]:
            del self.closed[k]

    def kept_slugs(self):
        with self.lock:
            return sorted(k for k, r in self.rooms.items() if r.get("persistent"))

    def rooms_public(self):
        """The /api/rooms rows -- a superset of 0.11's [{slug}]: what a gate or a
        room list needs about each name, never the key, salt or hash."""
        self.room_slugs()                    # expire first
        with self.lock:
            return [{"slug": k, "locked": bool(r.get("hash")), "persistent": bool(r.get("persistent")),
                     "creator": str(r.get("creator") or ""), "created": r.get("created"), "at": r.get("at")}
                    for k, r in sorted(self.rooms.items())]

    def closed_public(self):
        with self.lock:
            self._prune_closed()
            return dict(self.closed)

    def is_closed(self, slug):
        with self.lock:
            self._prune_closed()
            return slug in self.closed

    def close_room(self, slug):
        """Forget the record and leave a tombstone -> the removed record or None."""
        with self.lock:
            rec = self.rooms.pop(slug, None)
            self.closed[slug] = int(time.time() * 1000)
            self._prune_closed()
            self._group_forget(slug)         # 0.15.0: a closed room leaves its group
            self._save()
            return rec

    def drop_room(self, slug):
        """Forget a record WITHOUT a tombstone (a room un-kept and unlocked)."""
        with self.lock:
            rec = self.rooms.pop(slug, None)
            changed = self._group_forget(slug)   # 0.15.0
            if rec is not None or changed:
                self._save()
            return rec

    # ---- room groups (0.15.0) ------------------------------------------------
    # Relay-defined, shared by every page dialled in: {gid: {name, order, rooms}}.
    # A slug sits in at most one group; the operator creates/renames/deletes,
    # a room's creator (roomKey) or the operator assigns.

    @staticmethod
    def group_slug(name):
        s = re.sub(r"[^a-z0-9-]+", "-", str(name or "").lower()).strip("-")[:32]
        return s or "group"

    def groups_public(self):
        """The whole table, safe to publish (names and slugs only)."""
        with self.lock:
            return {gid: {"name": g["name"], "order": g["order"], "rooms": list(g["rooms"])}
                    for gid, g in self.groups.items()}

    def group_set(self, gid=None, name=None, order=None):
        """Create (gid None -> a unique slug of the name) or rename/reorder -> gid.
        ValueError on a bad name or the cap, KeyError on an unknown gid."""
        with self.lock:
            if gid is None:
                name = str(name or "").strip()[:48]
                if not name:
                    raise ValueError("group name required")
                if len(self.groups) >= GROUPS_MAX:
                    raise ValueError("at most %d groups" % GROUPS_MAX)
                base = self.group_slug(name)
                gid, n = base, 2
                while gid in self.groups:
                    suffix = "-%d" % n
                    gid = base[:32 - len(suffix)] + suffix
                    n += 1
                self.groups[gid] = {"name": name, "order": len(self.groups), "rooms": []}
            else:
                gid = str(gid)
                g = self.groups.get(gid)
                if g is None:
                    raise KeyError(gid)
                if name is not None:
                    name = str(name).strip()[:48]
                    if not name:
                        raise ValueError("group name required")
                    g["name"] = name
            if order is not None:
                try:
                    self.groups[gid]["order"] = int(order)
                except (TypeError, ValueError):
                    raise ValueError("order must be a number")
            self._save()
            return gid

    def group_delete(self, gid):
        """-> the removed group. KeyError when unknown."""
        with self.lock:
            g = self.groups.pop(str(gid), None)
            if g is None:
                raise KeyError(gid)
            self._save()
            return g

    def group_assign(self, slug, gid):
        """Put a room in ONE group (gid None = in no group) -> gid.
        ValueError on a bad slug or a full group, KeyError on an unknown gid."""
        slug = str(slug or "")
        if not SLUG_RE.match(slug):
            raise ValueError("bad room name")
        with self.lock:
            if gid is not None:
                gid = str(gid)
                g = self.groups.get(gid)
                if g is None:
                    raise KeyError(gid)
                if slug not in g["rooms"] and len(g["rooms"]) >= GROUP_ROOMS_MAX:
                    raise ValueError("at most %d rooms in a group" % GROUP_ROOMS_MAX)
            changed = self._group_forget(slug, keep=gid)
            if gid is not None and slug not in self.groups[gid]["rooms"]:
                self.groups[gid]["rooms"].append(slug)
                changed = True
            if changed:
                self._save()
            return gid

    def group_of(self, slug):
        with self.lock:
            for gid, g in self.groups.items():
                if slug in g["rooms"]:
                    return gid
            return None

    def _group_forget(self, slug, keep=None):
        """Lock held: drop `slug` from every group but `keep` -> changed?"""
        changed = False
        for gid, g in self.groups.items():
            if gid != keep and slug in g["rooms"]:
                g["rooms"] = [s for s in g["rooms"] if s != slug]
                changed = True
        return changed


def register_room(store, p, peer="", log=None, lockout=None):
    """0.12.0: the ONE room-record writer behind the minter's POST /api/room and
    kastr_serve's POST /api/rooms/register -> (reply, http code).

    {slug, salt, hash} locks a name (0.7); `persistent: true` KEEPS it (record
    and chat outlive the 24 h heartbeat window), with or without a lock. With
    access codes configured, creating a locked or kept room -- or keeping an
    existing one -- takes the publisher access code. A body whose roomKey
    matches (or whose `code` is the room's own) is a HEARTBEAT: it refreshes
    `at`, the salt/hash when sent and the kept flag when sent, and never
    re-keys. A publisher whose roomKey does not match takes a room over only
    with `rekey: true` (persistent/creator/created survive; the old roomKey
    dies). A WRONG access code counts toward the lockout like a wrong code at
    the minter; no code at all is a plain refusal."""
    log = log or (lambda m: None)
    slug = str(p.get("slug") or "")
    salt = str(p.get("salt") or "")
    hsh = str(p.get("hash") or "")
    keep = p.get("persistent")
    keep = None if keep is None else bool(keep)
    creator = str(p.get("creator") or "")[:64]
    access = str(p.get("access") or "")
    room_key = p.get("roomKey")
    locking = bool(salt and hsh)
    if not SLUG_RE.match(slug) or slug == "main" or bool(salt) != bool(hsh):
        return {"error": "bad room record"}, 400
    if lockout is not None:
        wait = lockout.locked_for(peer)
        if wait:
            return {"error": "too many attempts -- try again in %d s" % wait, "retryAfter": wait}, 429
    codes = store.configured()
    pub_ok = bool(codes and access and store.check("publisher", access))

    def wrong_code(why):
        if access and lockout is not None:          # a guess counts; silence does not
            return lockout.fail(peer, why, slug)
        log("relay auth: room %s -- %s (from %s)" % (slug, why, peer or "?"))
        return {"error": why}, 403

    def over_cap(name):
        kept = store.kept_slugs()
        return len(kept) >= KEPT_MAX and name not in kept

    now = time.time()
    cur = store.room(slug)
    if cur is None and not (locking or keep):
        return {"error": "bad room record"}, 400       # nothing to lock or keep (an existing room's holder may heartbeat with the key alone)
    if cur is not None:
        by_key = bool(room_key) and room_key == cur.get("roomKey")
        by_code = p.get("code") is not None and _room_code_ok(cur, p.get("code"))
        if by_key or by_code:
            # HEARTBEAT: the holder refreshes its record; never a new key.
            if locking:
                cur.update(salt=salt, hash=hsh)
            cur["at"] = now
            if creator and not cur.get("creator"):
                cur["creator"] = creator
            if keep is not None and keep != bool(cur.get("persistent")):
                if keep:
                    if codes and not pub_ok:
                        return wrong_code("keeping a room needs the publisher access code")
                    if over_cap(slug):
                        return {"error": "too many kept rooms"}, 409
                cur["persistent"] = keep
            if lockout is not None:
                lockout.ok(peer)
            if not cur.get("hash") and not cur.get("persistent"):
                store.drop_room(slug)            # neither locked nor kept: an ordinary room again
                return {"ok": True, "roomKey": cur["roomKey"], "persistent": False, "dropped": True}, 200
            store.put_room(slug, cur)
            return {"ok": True, "roomKey": cur["roomKey"], "persistent": bool(cur.get("persistent"))}, 200
        if codes and access and not pub_ok:
            return wrong_code("wrong publisher access code")
        if pub_ok and p.get("rekey"):
            # 0.11.0: rooms persist, so a publisher (the trusted operator) may re-key a
            # room whose code was lost -- logged, and the old roomKey dies. 0.12.0: only
            # when asked (rekey: true); a stale key is otherwise a 409, not a takeover.
            log("relay auth: room %s re-keyed with the publisher access code (from %s)" % (slug, peer or "?"))
            rec = dict(cur)
            if locking:
                rec.update(salt=salt, hash=hsh)
            if keep is not None:
                if keep and not rec.get("persistent") and over_cap(slug):
                    return {"error": "too many kept rooms"}, 409
                rec["persistent"] = keep
            rec.update(roomKey=os.urandom(16).hex(), at=now)
            if lockout is not None:
                lockout.ok(peer)
            store.put_room(slug, rec)
            return {"ok": True, "roomKey": rec["roomKey"], "rekeyed": True,
                    "persistent": bool(rec.get("persistent"))}, 200
        out = {"error": "room name is locked by someone else on this relay"}
        if pub_ok:
            out["canRekey"] = True               # the page may offer a take-over
        return out, 409
    # A new record. 0.10.0: with access codes on, only a publisher-code holder may
    # create a locked room -- otherwise a viewer could lock a name and hand out its
    # code, which admits as publisher. 0.12.0: the same for a kept room.
    if codes and not pub_ok:
        if access:
            return wrong_code("wrong publisher access code")
        log("relay auth: room %s not created -- no publisher access code (from %s)" % (slug, peer or "?"))
        return {"error": "creating a %s room needs the publisher access code"
                         % ("locked" if locking else "kept")}, 403
    if keep and over_cap(slug):
        return {"error": "too many kept rooms"}, 409
    if lockout is not None:
        lockout.ok(peer)
    rec = {"salt": salt, "hash": hsh, "roomKey": os.urandom(16).hex(), "at": now,
           "persistent": bool(keep), "creator": creator, "created": now}
    store.put_room(slug, rec)
    return {"ok": True, "roomKey": rec["roomKey"], "persistent": bool(keep)}, 200


def close_room(store, slug, roomKey=None, operator=False, hook=None, log=None):
    """0.12.0: close a room -> (reply, http code). The creator proves itself with
    the roomKey; the operator (the Relay page on the relay host) needs none and
    may also purge an unregistered room's chat. The record goes, the tombstone
    stays an hour, and `hook(slug)` (kastr_serve: the chat store's delete_room)
    removes the transcript and its attachments."""
    log = log or (lambda m: None)
    slug = str(slug or "")
    if not SLUG_RE.match(slug):
        return {"error": "bad room name"}, 400
    cur = store.room(slug)
    if cur is None and not operator:
        return {"error": "no such room on this relay"}, 404
    if not operator and not (roomKey and roomKey == cur.get("roomKey")):
        return {"error": "not the room's creator"}, 403
    store.close_room(slug)
    if hook is not None:
        try:
            hook(slug)
        except Exception as e:
            log("relay: room %s closed but its chat could not be removed: %s" % (slug, e))
    log("relay: room %s closed by %s" % (slug, "the operator" if operator else "its creator"))
    return {"ok": True, "slug": slug}, 200


def group_op(store, p, operator=False, log=None):
    """0.15.0: room groups -> (reply, http code), modelled on close_room.
    p["op"]: create {name, order?} / rename {gid, name?, order?} / delete {gid}
    (operator only: the Relay page on the relay host, or the token service's
    operator) / assign {slug, gid|null, roomKey?} (the room's creator proves
    itself with the roomKey exactly as for close; the operator needs none and
    may group a room that has no record). Replies {ok, op, gid, groups} or
    {error} with 400 (bad input) / 403 (not allowed) / 404 (unknown room or group)."""
    log = log or (lambda m: None)
    p = p if isinstance(p, dict) else {}
    op = str(p.get("op") or "")
    gid = p.get("gid") if p.get("gid") is not None else p.get("group")   # the page says `group`, the CLI recipe `gid`
    gid = str(gid) if gid not in (None, "") else None
    try:
        if op in ("create", "rename", "delete"):
            if not operator:
                return {"error": "only the relay's operator manages groups"}, 403
            if op == "create":
                same = next((g for g, rec in store.groups_public().items() if str(rec.get("name") or "").strip().lower() == str(p.get("name") or "").strip().lower()), None)
                gid = same or store.group_set(None, p.get("name"), p.get("order"))   # same name -> same group
                log("relay: room group %s created" % gid)
            elif op == "rename":
                if gid is None:
                    return {"error": "gid required"}, 400
                store.group_set(gid, p.get("name"), p.get("order"))
            else:
                if gid is None:
                    return {"error": "gid required"}, 400
                store.group_delete(gid)
                log("relay: room group %s deleted" % gid)
        elif op == "assign":
            slug = str(p.get("slug") or "")
            if not SLUG_RE.match(slug):
                return {"error": "bad room name"}, 400
            if not operator:
                cur = store.room(slug)
                if cur is None:
                    return {"error": "no such room on this relay"}, 404
                rk = p.get("roomKey")
                if not (rk and rk == cur.get("roomKey")):
                    return {"error": "not the room's creator"}, 403
            store.group_assign(slug, gid)
            log("relay: room %s %s by %s" % (slug, ("grouped under %s" % gid) if gid else "ungrouped",
                                             "the operator" if operator else "its creator"))
        else:
            return {"error": "unknown op (create|rename|delete|assign)"}, 400
    except KeyError:
        return {"error": "no such group"}, 404
    except ValueError as e:
        return {"error": str(e)}, 400
    return {"ok": True, "op": op, "gid": gid, "groups": store.groups_public()}, 200


class AuthService:
    """Token minting for a secured relay, on TCP relay-port+1.

    CORS is wide open by design: the credential is the code in the request
    body, never a cookie, and the pages calling in are served from every
    user's own machine. 0.10.0: the AuthStore decides -- relay-wide access
    codes give the ROLE (publisher: put+get on the room; viewer: get on the
    room plus put on its presence-class kinds), a registered room's own code
    is an extra lock, and five wrong codes a minute earn a lockout that
    doubles from 30 s to 10 min.
    """

    bans = None   # 0.17.0: set by __init__; a test double without one simply never bans

    def __init__(self, host, port, key, relay_port, store=None, log=None, hub=None, fed_token=None, revalidate=None):
        self.store = store or AuthStore(os.getcwd(), log)
        self.hub = hub                       # 0.16.0: callable -> the hub minter's base URL (a spoke forwards admin codes there), or None
        self.fed_token = fed_token           # 0.17.0: callable -> this spoke's federation token (a kick rides it to the hub), or None
        self.revalidate = revalidate         # 0.17.0: callable -> asks the relay to re-validate its sessions now ("post"|"get"|"unavailable")
        self.log = log or (lambda m: None)
        self.bans = BanList(getattr(self.store, "state_dir", os.getcwd()), log)   # 0.17.0: relay-side kicks
        # 0.18.0: the spokes that federate here (hub side) -- their minter URLs, so a ban on
        # the hub reaches every spoke (each pulls the hub's bans with its federation token)
        self.spokes = {}
        self._spokes_path = os.path.join(getattr(self.store, "state_dir", os.getcwd()), "relay-spokes.json")
        try:
            with open(self._spokes_path, encoding="utf-8-sig") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("spokes"), dict):
                self.spokes = {str(k): v for k, v in d["spokes"].items() if isinstance(v, dict)}
        except Exception:
            self.spokes = {}
        self._pull_at = 0
        self.lock = threading.Lock()
        self.lockout = Lockout(self.log)     # 0.12.0: the brute-force counter, one class with kastr_serve
        self._fails = self.lockout._fails
        self._wide_logged = set()            # 0.13.0: peers that took a wide (no-host) token, logged once each
        # 0.16.0: the relay's per-session auth (see session()); the relay asks us
        self._sessions = {}                  # relay session id -> {at, remote, role, publisher, expires, grant}
        self._refused = []                   # the last 20 refusals {at, remote, path, why}
        self._refuse_said = {}               # remote -> last log time (one line per remote per minute)
        self._events = []                    # the last 20 session events, shape only
        self.grants = self.refusals = self.ended = 0
        self.fingerprint = None              # the relay's QUIC certificate sha256 (Relay sets it once the relay is up)
        svc = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, obj, code=200, headers=None):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                for k, v in (headers or {}).items():
                    self.send_header(k, str(v))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self):
                path = self.path.split("?")[0]
                if path == "/api/auth":
                    codes = svc.store.configured()
                    self._reply({"app": "KASTR", "secured": True,
                                 "relayPort": relay_port, "ttlSec": TOKEN_TTL,
                                 "codes": codes, "legacy": not codes,
                                 # 0.11.0: can relays join here, and which key signs
                                 "federation": svc.store.codes_status()["federation"],
                                 "kid": svc.kid,
                                 # 0.12.0: members may announce .talking/<room> and .chat/<room>
                                 "talking": True, "chat": True,
                                 # 0.13.0: this minter scopes tokens to a host and the relay
                                 # publishes .state/<room>/<host> tracks
                                 "state": True,
                                 # 0.14.0 F: the hub KASTR's web port -- spokes (chat proxy, peer
                                 # lookups, version follow) and pages stop assuming 8000
                                 "web": WEB_PORT or _FIREWALL_WEB_PORT or None,
                                 # 0.15.0: its https listener (None = loopback-only web host)
                                 "https": HTTPS_PORT,
                                 # 0.16.0: this minter also answers the relay's per-session auth, and the
                                 # relay's certificate fingerprint (spokes pin it instead of disable_verify)
                                 "session": True, "fingerprint": svc.fingerprint,
                                 # 0.16.0: an admin code exists here (the gate can say so)
                                 "adminCode": svc.store.codes_status()["admin"]})
                elif path == "/api/rooms":
                    # 0.11.0: the locked rooms this relay remembers (possibly empty) so a
                    # gate can list them and take their codes -- names only.
                    # 0.12.0: rows {slug, locked, persistent, creator, created, at} -- old pages read .slug
                    # 0.15.0: + the relay-defined room groups
                    self._reply({"rooms": svc.store.rooms_public(), "groups": svc.store.groups_public()})
                elif path == "/api/bans":              # 0.18.0: the hub's active bans, for its spokes only
                    obj, code = svc.bans_for_spoke(self.headers.get("Authorization"))
                    self._reply(obj, code)
                else:
                    self._reply({"error": "unknown endpoint"}, 404)

            def _payload(self):
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    return json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    return {}

            def _peer(self):
                # The KASTR https proxy forwards the real client; trusted
                # only when the proxy itself is the loopback peer.
                return client_ip(self)   # 0.19.0: + Cf-Connecting-IP / X-Real-IP (loopback proxies only)

            def do_POST(self):
                path = self.path.split("?")[0]
                p = self._payload()
                if path == "/api/room":
                    obj, code = svc.register(p, self._peer())
                    self._reply(obj, code)
                elif path == "/api/token":
                    obj, code = svc.token(p, self._peer())
                    hdrs = {"Retry-After": obj.get("retryAfter", 30)} if code == 429 else None
                    self._reply(obj, code, hdrs)
                elif path in ("/api/session", "/"):
                    # 0.16.0: the relay's session events. The PEER must be loopback itself
                    # (never X-Forwarded-For -- the relay runs beside us).
                    ip = (self.client_address[0] if self.client_address else "") or ""
                    obj, code = svc.session(p, ip)
                    self._reply(obj, code)
                elif path == "/api/kick":   # 0.17.0: an admin removes a member relay-side
                    obj, code = svc.kick(p, self._peer(), self.headers.get("Authorization"))
                    self._reply(obj, code)
                elif path == "/api/spokes/register":   # 0.18.0: a spoke tells its hub where its minter is
                    obj, code = svc.register_spoke(p, self._peer(), self.headers.get("Authorization"))
                    self._reply(obj, code)
                elif path == "/api/bans/notify":       # 0.18.0: the hub says "bans changed" -- no data, we pull
                    obj, code = svc.bans_notified(self._peer())
                    self._reply(obj, code)
                else:
                    self._reply({"error": "unknown endpoint"}, 404)

        self.key = key
        self.kid = key_id(key)          # 0.11.0: spokes compare it to notice a rotated hub key
        self.httpd = ThreadingHTTPServer((host, port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass

    # ---- brute force (0.10.0; 0.12.0: the Lockout class above) -----------------

    def locked_for(self, peer):
        return self.lockout.locked_for(peer)

    def _fail(self, peer, why, slug, what="room"):
        return self.lockout.fail(peer, why, slug, what)

    def _ok(self, peer):
        self.lockout.ok(peer)

    # ---- endpoints -------------------------------------------------------

    def register(self, p, peer=""):
        # 0.12.0: one implementation with kastr_serve's POST /api/rooms/register
        return register_room(self.store, p, peer, self.log, self.lockout)

    def _federation_token(self, code, peer=""):
        """0.11.0: a relay joining this one presents the FEDERATION code and gets a
        whole-namespace token (put + get on everything) for 30 days. Not counted
        as a failure when no federation code exists here (nothing to guess)."""
        wait = self.locked_for(peer)
        if wait:
            return {"error": "too many attempts -- try again in %d s" % wait, "retryAfter": wait}, 429
        if not self.store.codes_status()["federation"]:
            self.log("relay auth: federation refused -- no federation code set here (from %s)" % (peer or "?"))
            return {"error": "no federation code on this relay"}, 403
        if not self.store.check("federation", code):
            return self._fail(peer, "wrong federation code", "(federation)", what="relay")
        self._ok(peer)
        now = int(time.time())
        exp = now + FEDERATION_TTL
        tok = _mint(self.key, dict(FEDERATION_CLAIMS, iat=now, exp=exp))
        self.log("relay auth: federation token minted for %s (valid %d days)" % (peer or "?", FEDERATION_TTL // 86400))
        return {"ok": True, "role": "relay", "exp": exp, "kid": self.kid, "token": tok}, 200

    def token(self, p, peer=""):
        if p.get("federation") is not None and not p.get("room"):   # 0.11.0: a relay, not a person
            return self._federation_token(str(p.get("federation") or ""), peer)
        if p.get("verify") and p.get("admin") is not None:          # 0.16.0: a spoke asks "is this OUR admin code?"
            return self._admin_verify(str(p.get("admin") or ""), peer)
        slug = str(p.get("room") or "")
        access = str(p.get("code") or "")
        room_code = p.get("roomCode")
        room_code = None if room_code is None else str(room_code)
        # 0.13.0: the member's host slug (kastr_serve.host_slug) scopes the puts.
        # Absent -> the 0.12 shape (a 0.12 page, or an unsubstituted page);
        # present but malformed -> 400.
        host = p.get("host")
        host = None if host is None else str(host)
        if not SLUG_RE.match(slug):
            return {"error": "bad room name"}, 400
        if host is not None and not HOST_RE.match(host):
            return {"ok": False, "error": "bad host"}, 400
        b = self.bans.hit(slug, host, peer) if self.bans else None   # 0.17.0: removed by an admin -- not a wrong code, no lockout
        if b:
            return {"ok": False, "error": "removed from this room by an admin", "until": int(b.get("until") or 0),
                    "by": b.get("by")}, 403
        wait = self.locked_for(peer)
        if wait:
            return {"error": "too many attempts -- try again in %d s" % wait, "retryAfter": wait}, 429
        rec = self.store.room(slug)
        # The room's own code is what old pages (and the second gate row) send
        # in `code`; with access codes on it travels in `roomCode`.
        rc = room_code if room_code is not None else access
        if self.store.configured():
            if self.store.check("publisher", access):
                role = "publisher"
            elif self.store.check("viewer", access):
                role = "viewer"
            elif self.store.check("admin", access) or self._hub_admin_ok(access):   # 0.16.0: here, or the hub's
                role = "admin"
            elif rec is not None and _room_code_ok(rec, access):
                role, rc = "publisher", access     # the room's creator (a publisher) delegated its code
            else:
                return self._fail(peer, "wrong access code", slug)
            if rec is not None and rec.get("hash") and not _room_code_ok(rec, rc):   # 0.12.0: a kept room may be unlocked
                return self._fail(peer, "wrong room code", slug)
        else:
            # Legacy (secured, no codes yet): today's behaviour, so a fleet
            # update cannot lock a working relay out. Relay.start logs it.
            role = "publisher"
            if rec is not None and rec.get("hash") and not _room_code_ok(rec, rc):   # 0.12.0: a kept room may be unlocked
                return self._fail(peer, "wrong room code", slug)
        self._ok(peer)
        now = int(time.time())
        ttl = TOKEN_TTL if role in ("publisher", "admin") else VIEWER_TTL   # 0.16.0: admin = a publisher with .admin
        exp = now + ttl
        if host:
            # 0.13.0: identity-scoped puts. A token writes only under the host
            # it named (its media / its .member broadcast, its .state track) plus
            # the two one-release compat announces (`<room>/.since`,
            # `.presence/<room>`, gone in 0.14). The viewer's `<room>/<host>/.member`
            # is narrower than the publisher's `<room>/<host>`: that is what keeps
            # a viewer token off media.
            if role in ("publisher", "admin"):
                puts = [slug + "/" + host, STATE_PREFIX + "/" + slug + "/" + host,
                        slug + "/.since", ".presence/" + slug]
                if role == "admin":
                    puts.append(slug + "/" + ADMIN_KIND)   # 0.16.0: stop / mute / kick commands
            else:
                puts = [STATE_PREFIX + "/" + slug + "/" + host, slug + "/" + host + "/.member",
                        slug + "/.since", ".presence/" + slug]
            member = _mint(self.key, {"root": "", "get": slug, "put": puts, "iat": now, "exp": exp})
        elif role in ("publisher", "admin"):
            # 0.11.0: `.presence/<slug>` is the public room-occupancy announce (arrays are fine)
            # 0.12.0: + .talking/<slug> and .chat/<slug> (speaking + chat nudges)
            self._wide_once(peer)
            member = _mint(self.key, {"root": "", "put": [slug] + [k + "/" + slug for k in MEMBER_KINDS]
                                                        + ([slug + "/" + ADMIN_KIND] if role == "admin" else []),   # 0.16.0
                                      "get": slug, "iat": now, "exp": exp})
        else:
            # Measured against the bundled relay (2026-09-18): `put` may be a
            # list, matching is per path segment, and an announce outside the
            # list is dropped without closing the session -- so one token
            # covers subscribing plus every presence-class announce.
            self._wide_once(peer)
            member = _mint(self.key, {"root": "", "get": slug,
                                      "put": [slug + "/" + k for k in VIEWER_KINDS] + [k + "/" + slug for k in MEMBER_KINDS],   # 0.12.0
                                      "iat": now, "exp": exp})
        # Every member holds the room's registry record (0.8.6).
        registry = _mint(self.key, {"root": "", "put": ".channels/" + slug, "iat": now, "exp": exp})
        return {"ok": True, "exp": exp, "role": role,
                "tokens": {"member": member, "registry": registry}}, 200

    # ---- 0.16.0: the relay's per-session auth ------------------------------------

    def session(self, req, peer=""):
        """POST /api/session from the relay beside us: one Request per session event.
        connect/revalidate -> a Grant (200) or a refusal (403); end -> bookkeeping.
        Reply first, log after -- the relay waits on this answer."""
        if peer not in LOOPBACK_PEERS:
            return {"error": "session auth answers the relay on this machine only"}, 403
        if not isinstance(req, dict):
            return {"error": "bad request"}, 400
        ev = str(req.get("event") or "connect")
        sid = str(req.get("id") or "")
        remote = str(req.get("remote") or "?")
        now = time.time()
        with self.lock:   # the last 20 events, shape only (field diagnostics: what the relay sends)
            self._events.append({"at": int(now), "event": ev, "remote": remote, "keys": sorted(str(k) for k in req),
                                 "jwt": bool(session_jwt(req)), "role": str(req.get("role") or ""), "transport": str(req.get("transport") or "")})
            del self._events[:-20]
        if ev == "end":
            with self.lock:
                rec = self._sessions.pop(sid, None)
                self.ended += 1
            reason = str(req.get("reason") or "")
            if rec and (rec.get("publisher") or reason):
                self.log("relay session: end %s remote=%s role=%s %ss %s bytes%s"
                         % (sid[:8] or "?", rec.get("remote"), rec.get("role"), req.get("duration", "?"),
                            req.get("bytes", "?"), (" reason=" + reason) if reason else ""))
            return {}, 200
        if ev == "revalidate" and not session_jwt(req):
            # a revalidate that carries no query: hand back the grant we gave at connect while it
            # lasts (never a downgrade to the public grant -- that would end a publisher's session)
            with self.lock:
                rec = self._sessions.get(sid)
            if rec and (rec.get("revoked") or (self.bans and self.bans.hit(rec.get("room"), rec.get("host"), rec.get("remote"), now))):
                return self._revoked_answer(ev, sid, remote, now)   # 0.17.0: an admin removed this identity
            if rec and float(rec.get("expires") or 0) > now:
                return rec["grant"], 200
        status, grant, why = session_grant(req, self.key, now)
        room = host = None
        if status == "grant":
            claims = verify_token(session_jwt(req), self.key, now) or {}
            room, host = claims_identity(claims)
            if self.bans and self.bans.hit(room, host, remote, now):   # 0.17.0
                return self._revoked_answer(ev, sid, remote, now)
        if status == "refuse":
            with self.lock:
                self.refusals += 1
                self._refused.append({"at": int(now), "remote": remote, "path": str(req.get("path") or ""), "why": why})
                del self._refused[:-20]
                last = self._refuse_said.get(remote)
                say = not last or now - last > 60
                if say:
                    self._refuse_said[remote] = now
            if say:
                self.log("relay session: refused %s from %s (%s)" % (ev, remote, why))
            return {"error": why}, 403
        with self.lock:
            self.grants += 1
            if sid:
                if len(self._sessions) >= SESSIONS_MAX:
                    for k in sorted(self._sessions, key=lambda k: self._sessions[k]["at"])[:len(self._sessions) - SESSIONS_MAX + 1]:
                        self._sessions.pop(k, None)
                self._sessions[sid] = {"at": now, "remote": remote, "role": why,
                                       "publisher": bool(grant.get("publish")),
                                       "expires": grant.get("expires") or (now + 86400), "grant": grant,
                                       "room": room, "host": host, "revoked": False}   # 0.17.0: the identity a kick keys on
        return grant, 200

    # ---- 0.17.0: relay-side kicks --------------------------------------------------------
    # The relay answers to us for every session: a banned identity is refused at connect,
    # at revalidate (the relay re-asks on a timer, and at once when we POST
    # /sessions/revalidate on its internal listener) and at the minter. REVOKE_ANSWER picks
    # the refusal shape: "refuse" = HTTP 403 (the relay logs "the auth server refused the
    # session" and closes it); "empty" = 200 with no patterns ("grant names nothing; the
    # session is refused"). Measured on the rig; see ARCHITECTURE.md.
    REVOKE_ANSWER = "refuse"
    REVOKED_TEXT = "removed from this room by an admin"

    def _revoked_answer(self, ev, sid, remote, now):
        with self.lock:
            self.refusals += 1
            self._refused.append({"at": int(now), "remote": remote, "path": "", "why": "banned"})
            del self._refused[:-20]
            rec = self._sessions.get(sid)
            if rec:
                rec["revoked"] = True
        self.log("relay session: refused %s from %s (removed by an admin)" % (ev, remote))
        if self.REVOKE_ANSWER == "empty":
            return {"publish": [], "subscribe": []}, 200
        return {"error": self.REVOKED_TEXT}, 403

    def revoke_sessions(self, room, host):
        """Mark the live sessions of (room, host) revoked; -> (session ids, their remotes)."""
        ids, remotes = [], []
        with self.lock:
            for sid, rec in self._sessions.items():
                if rec.get("room") == room and host and rec.get("host") == host:
                    rec["revoked"] = True
                    ids.append(sid)
                    if rec.get("remote") and rec["remote"] not in remotes and not is_loopback_addr(rec["remote"]):   # 0.19.0
                        remotes.append(rec["remote"])
        return ids, remotes

    def trigger_revalidate(self):
        try:
            return self.revalidate() if callable(self.revalidate) else "unavailable"
        except Exception:
            return "unavailable"

    def kick(self, p, peer="", bearer=None):
        """POST /api/kick. From an admin page: {token, room, target: "host/op[/peer]", until?}
        (the token must carry the room's .admin put). From a SPOKE: Authorization: Bearer
        <federation token> + {ban} -- applied here as well (the hub), never forwarded on."""
        now = time.time()
        if bearer and str(bearer).lower().startswith("bearer "):
            claims = verify_token(str(bearer)[7:].strip(), self.key, now)
            if not claims or not is_relay_claims(claims):
                return {"ok": False, "error": "not a federation token"}, 403
            ban = p.get("ban") if isinstance(p, dict) else None
            if not isinstance(ban, dict) or not SLUG_RE.match(str(ban.get("room") or "")):
                return {"ok": False, "error": "bad ban"}, 400
            ban = {"room": str(ban.get("room")), "host": (str(ban.get("host")) if ban.get("host") else None),
                   "remotes": [str(r) for r in (ban.get("remotes") or [])][:16], "target": str(ban.get("target") or "")[:120],
                   "by": str(ban.get("by") or "")[:40], "at": int(now), "until": min(int(now) + 86400, max(int(now) + 60, int(ban.get("until") or 0))),
                   "via": "spoke:" + (peer or "?")}
            ids, _ = self.revoke_sessions(ban["room"], ban["host"])
            self.bans.add(ban)
            how = self.trigger_revalidate()
            threading.Thread(target=self.fanout_bans, daemon=True).start()   # 0.18.0: every other spoke too
            self.log("relay auth: kick %s in %s forwarded by a spoke (%s) -- %d sessions revoked, until %s"
                     % (ban["target"] or ban["host"], ban["room"], peer, len(ids), time.strftime("%H:%M:%S", time.localtime(ban["until"]))))
            return {"ok": True, "ban": ban, "revoked": [i[:8] for i in ids], "revalidate": how}, 200
        tok = str(p.get("token") or "")
        slug = str(p.get("room") or "")
        target = str(p.get("target") or "").strip()
        if not SLUG_RE.match(slug):
            return {"ok": False, "error": "bad room name"}, 400
        m = re.match(r"^([a-z0-9-]{1,32}-[0-9a-f]{4})/([a-z0-9-]{1,40})(?:/([A-Za-z0-9-]{1,40}))?$", target)
        if not m:
            return {"ok": False, "error": "bad target (host/operator[/peer])"}, 400
        claims = verify_token(tok, self.key, now)
        if not claims:
            return {"ok": False, "error": "token refused"}, 403
        puts = _patterns(claims.get("put")) if claims.get("put") is not None else []
        if (slug + "/" + ADMIN_KIND) not in puts and (slug + "/" + ADMIN_KIND + "/**") not in puts:
            return {"ok": False, "error": "not an admin token for this room"}, 403
        try:
            until_s = int(p.get("until") or 3600)
        except (TypeError, ValueError):
            until_s = 3600
        until_s = min(86400, max(60, until_s))
        host = m.group(1)
        ids, remotes = self.revoke_sessions(slug, host)
        by = str(p.get("by") or "")[:40]
        if not by:
            _r, admin_host = claims_identity(claims)
            by = admin_host or "admin"
        ban = {"room": slug, "host": host, "remotes": remotes[:16], "target": target, "by": by,
               "at": int(now), "until": int(now) + until_s, "via": "local"}
        self.bans.add(ban)
        how = self.trigger_revalidate()
        self.log("relay auth: kick %s in %s by %s -- %d sessions revoked, until %s (revalidate %s)"
                 % (target, slug, by, len(ids), time.strftime("%H:%M:%S", time.localtime(ban["until"])), how))
        threading.Thread(target=self._forward_ban, args=(ban,), daemon=True).start()
        threading.Thread(target=self.fanout_bans, daemon=True).start()   # 0.18.0: a hub tells its spokes
        return {"ok": True, "ban": ban, "revoked": [i[:8] for i in ids], "revalidate": how}, 200

    # ---- 0.18.0: ban fan-out (hub -> every spoke) ----------------------------------------
    def _bearer_relay(self, bearer):
        if not bearer or not str(bearer).lower().startswith("bearer "):
            return None
        claims = verify_token(str(bearer)[7:].strip(), self.key)
        return claims if (claims and is_relay_claims(claims)) else None

    def register_spoke(self, p, peer="", bearer=None):
        if not self._bearer_relay(bearer):
            return {"ok": False, "error": "federation token required"}, 403
        url = str((p or {}).get("minter") or "").strip().rstrip("/")
        if not re.match(r"^https?://[A-Za-z0-9.\-\[\]:]{1,260}$", url):
            return {"ok": False, "error": "bad minter url"}, 400
        with self.lock:
            fresh = url not in self.spokes
            self.spokes[url] = {"at": int(time.time()), "peer": peer}
            if len(self.spokes) > 64:
                for k in sorted(self.spokes, key=lambda k: self.spokes[k].get("at", 0))[:len(self.spokes) - 64]:
                    self.spokes.pop(k, None)
            snap = dict(self.spokes)
        try:
            tmp = self._spokes_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"spokes": snap}, f)
            os.replace(tmp, self._spokes_path)
        except Exception:
            pass
        if fresh:
            self.log("relay auth: spoke %s registered for ban fan-out (from %s)" % (url, peer or "?"))
        return {"ok": True, "bans": len(self.bans.active())}, 200

    def bans_for_spoke(self, bearer):
        if not self._bearer_relay(bearer):
            return {"error": "federation token required"}, 403
        rows = [{k: b.get(k) for k in ("room", "host", "target", "by", "at", "until")} for b in self.bans.active()]
        return {"bans": rows}, 200

    def fanout_bans(self):
        """Hub side: nudge every registered spoke (no data -- each pulls with its own token)."""
        with self.lock:
            urls = list(self.spokes)
        n = 0
        for url in urls:
            try:
                req = urllib.request.Request(url + "/api/bans/notify", data=b"{}", method="POST",
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3):
                    n += 1
            except Exception:
                pass
        if urls:
            self.log("relay auth: ban fan-out -- %d of %d spoke(s) notified" % (n, len(urls)))
        return n

    def bans_notified(self, peer=""):
        """Spoke side: the hub said bans changed. Rate-limited; the pull happens off-thread."""
        now = time.time()
        if now - self._pull_at < 3:
            return {"ok": True, "throttled": True}, 200
        self._pull_at = now
        threading.Thread(target=self.pull_hub_bans, daemon=True).start()
        return {"ok": True}, 200

    def pull_hub_bans(self):
        """Spoke side: copy the hub's active bans (federation token as Bearer), revoke the
        matching live sessions here and ask the relay to re-validate. -> bans applied."""
        try:
            minter = self.hub() if callable(self.hub) else None
            tok = self.fed_token() if callable(self.fed_token) else None
        except Exception:
            minter = tok = None
        if not minter or not tok:
            return 0
        try:
            req = urllib.request.Request(minter + "/api/bans", headers={"Authorization": "Bearer " + tok})
            with urllib.request.urlopen(req, timeout=4) as r:
                d = json.loads(r.read().decode("utf-8", "replace") or "{}")
        except Exception as e:
            self.log("relay auth: pulling the hub's bans failed: %s" % str(e)[:120])
            return 0
        now = time.time()
        have = {(b.get("room"), b.get("host") or b.get("target")) for b in self.bans.active()}
        added = 0
        for b in d.get("bans") or []:
            if not isinstance(b, dict) or not SLUG_RE.match(str(b.get("room") or "")):
                continue
            try:
                until = int(b.get("until") or 0)
            except (TypeError, ValueError):
                continue
            key = (b.get("room"), b.get("host") or b.get("target"))
            if until <= now or key in have:
                continue
            ban = {"room": str(b["room"]), "host": (str(b["host"]) if b.get("host") else None), "remotes": [],
                   "target": str(b.get("target") or "")[:120], "by": str(b.get("by") or "")[:40],
                   "at": int(b.get("at") or now), "until": until, "via": "hub"}
            self.revoke_sessions(ban["room"], ban["host"])
            self.bans.add(ban)
            added += 1
        if added:
            how = self.trigger_revalidate()
            self.log("relay auth: %d ban(s) copied from the hub (revalidate %s)" % (added, how))
        return added

    def _forward_ban(self, ban):
        """A spoke tells its hub (the hub applies the ban to its own sessions; other spokes
        rely on the cooperative .admin announce -- documented gap)."""
        try:
            minter = self.hub() if callable(self.hub) else None
            tok = self.fed_token() if callable(self.fed_token) else None
        except Exception:
            minter = tok = None
        if not minter or not tok:
            return
        try:
            req = urllib.request.Request(minter + "/api/kick", data=json.dumps({"ban": ban}).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok},
                                         method="POST")
            with urllib.request.urlopen(req, timeout=4) as r:
                d = json.loads(r.read().decode("utf-8", "replace") or "{}")
            self.log("relay auth: kick %s forwarded to the hub -- %s" % (ban.get("target"), "applied" if d.get("ok") else d.get("error")))
        except Exception as e:
            self.log("relay auth: kick %s not forwarded to the hub: %s" % (ban.get("target"), str(e)[:120]))

    def stats(self):
        with self.lock:
            pubs = sum(1 for r in self._sessions.values() if r.get("publisher"))
            return {"up": True, "sessions": len(self._sessions), "publishers": pubs,
                    "grants": self.grants, "refusals": self.refusals, "ended": self.ended,
                    "bans": len(self.bans.active()) if self.bans else 0,   # 0.17.0
                    "lastRefusal": (dict(self._refused[-1]) if self._refused else None),
                    "recent": [dict(e) for e in self._events[-8:]]}

    # ---- 0.16.0: the admin code, here or at the hub ---------------------------------

    def _admin_verify(self, code, peer=""):
        """POST /api/token {admin, verify:true} from a SPOKE's minter: yes/no, no token."""
        wait = self.locked_for(peer)
        if wait:
            return {"error": "too many attempts -- try again in %d s" % wait, "retryAfter": wait}, 429
        if not self.store.codes_status()["admin"]:
            return {"ok": False, "error": "no admin code on this relay"}, 403
        if not self.store.check("admin", code):
            return self._fail(peer, "wrong admin code", "(admin)", what="admin")
        self._ok(peer)
        return {"ok": True, "role": "admin"}, 200

    def _hub_admin_ok(self, code):
        """A spoke with no admin code of its own asks the hub: is this the fleet's
        admin code? The code travels only to the minter the client already trusts
        with it. False on any doubt (no hub, hub dark, refused, throttled)."""
        if not code or self.store.codes_status()["admin"]:
            return False
        try:
            minter = self.hub() if callable(self.hub) else None
        except Exception:
            minter = None
        if not minter:
            return False
        try:
            req = urllib.request.Request(minter + "/api/token",
                                         data=json.dumps({"admin": code, "verify": True}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=4) as r:
                d = json.loads(r.read().decode("utf-8", "replace") or "{}")
            ok = bool(d.get("ok")) and d.get("role") == "admin"
            if ok:
                self.log("relay auth: admin code verified by the hub %s" % minter)
            return ok
        except Exception as e:
            self.log("relay auth: hub admin verify failed (%s)" % e)
            return False

    def _wide_once(self, peer):
        """0.13.0: a member without a `host` took the 0.12-shaped (room-wide put)
        token -- a 0.12 page or an unsubstituted one. Noted once per peer."""
        key = peer or "?"
        with self.lock:
            if key in self._wide_logged:
                return
            self._wide_logged.add(key)
        self.log("relay auth: wide token (no host) for %s" % key)


# ---- 0.19.0: web relays ---------------------------------------------------------------
# A relay address whose path is /relay (https://kastr.example.com/relay) names a KASTR
# whose WEB PORT carries everything: its API is the URL's origin, its media rides
# WebSocket through that port (kastr_serve's /relay proxy). Made for Cloudflare Tunnel
# and other single-port proxies, which carry HTTP + WebSocket but no QUIC.
WEB_RELAY_PATH = "/relay"
FORWARD_HEADERS = ("Cf-Connecting-IP", "Cf-Ray", "X-Forwarded-For", "X-Real-IP", "X-Forwarded-Host",
                   "X-Forwarded-Proto", "Forwarded")


def _as_url(url):
    u = str(url or "").strip()
    if u and "://" not in u:
        u = "https://" + u
    return u


def is_web_relay(url):
    """True for a relay URL whose path is /relay (any query; ws/wss/http/https)."""
    try:
        u = _as_url(url)
        return bool(u) and (urlparse(u).path or "").rstrip("/") == WEB_RELAY_PATH
    except Exception:
        return False


def web_origin(url):
    """'wss://Name:8443/relay?jwt=x' -> 'https://name:8443' (ws->http, wss->https;
    the port only when explicit). '' when unparsable."""
    try:
        p = urlparse(_as_url(url))
        host = (p.hostname or "").lower()
        if not host:
            return ""
        scheme = {"ws": "http", "wss": "https"}.get((p.scheme or "https").lower(), (p.scheme or "https").lower())
        h = ("[" + host + "]") if ":" in host else host
        return "%s://%s%s" % (scheme, h, (":%d" % p.port) if p.port else "")
    except Exception:
        return ""


def web_origin_port(url):
    try:
        p = urlparse(web_origin(url))
        return p.port or (443 if p.scheme == "https" else 80)
    except Exception:
        return None


def is_loopback_addr(addr):
    """'127.0.0.1', '127.0.0.1:5000', '[::1]:5000', '::1', '[::ffff:127.0.0.1]:1' -> True."""
    a = str(addr or "").strip()
    if a in LOOPBACK_PEERS:
        return True
    m = re.match(r"^\[([^\]]+)\](?::\d+)?$", a) or re.match(r"^([0-9.]+)(?::\d+)?$", a)
    return bool(m) and m.group(1).lower() in LOOPBACK_PEERS


def is_forwarded(handler):
    """0.19.0: the request came through a proxy (cloudflared, nginx, ...)."""
    try:
        return any(handler.headers.get(h) for h in FORWARD_HEADERS)
    except Exception:
        return False


def client_ip(handler):
    """0.19.0: the visitor's address -- Cf-Connecting-IP / X-Real-IP / the first
    X-Forwarded-For when the peer is a loopback proxy (cloudflared dials from
    127.0.0.1), else the peer itself."""
    ip = (handler.client_address[0] if getattr(handler, "client_address", None) else "") or ""
    if ip in LOOPBACK_PEERS:
        for h in ("Cf-Connecting-IP", "X-Real-IP"):
            v = (handler.headers.get(h) or "").strip()
            if v and re.match(r"^[0-9A-Fa-f:.]{2,45}$", v):
                return v
        xff = (handler.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if xff and re.match(r"^[0-9A-Fa-f:.]{2,45}$", xff):
            return xff
    return ip


def _normalize_hub(url):
    """'host', 'host:4443', 'https://host:4443/?jwt=x' -> 'https://host:4443'
    (scheme kept, path/query dropped: the token comes from the code, never a paste).
    0.19.0: a web relay keeps its path: 'https://name/relay?jwt=x' -> 'https://name/relay'."""
    u = str(url or "").strip()
    if not u:
        return ""
    if u.lower().startswith(("ws://", "wss://")):   # 0.19.0: a WebSocket spelling of the same relay
        u = "http" + u[2:]
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    if is_web_relay(u):
        o = web_origin(u)
        return (o + WEB_RELAY_PATH) if o else ""
    try:
        p = urlparse(u)
        host = p.hostname or ""
        if not host:
            return ""
        if ":" in host:
            host = "[" + host + "]"
        return "%s://%s:%d" % (p.scheme, host, p.port or 4443)
    except Exception:
        return ""


def _hub_parts(hub):
    """-> (host, relay port, minter base 'http://host:port+1').
    0.19.0: a web relay -> (host, its web port, its origin) -- the web port proxies the minter."""
    if is_web_relay(hub):
        return (urlparse(web_origin(hub)).hostname or ""), web_origin_port(hub), web_origin(hub)
    p = urlparse(hub)
    host = p.hostname or ""
    port = p.port or 4443
    h = ("[" + host + "]") if ":" in host else host
    return host, port, "http://%s:%d" % (h, port + 1)


# ---- the hub KASTR's web port (0.15.0) -----------------------------------------
# Every consumer of "the KASTR on the relay host" (update feed, chat proxy, peer
# lookups) assumed 8000 until 0.14.0 pinned the port; a hub that moved to 8001
# was simply unreachable. The port is now LEARNED -- from the minter's /api/auth
# when the hub is secured, else by probing /api/instance on a short candidate
# list -- and remembered per host in state_dir/hub-web.json.

HUB_WEB_CANDIDATES = tuple(range(8000, 8011))
HUB_WEB_PROBE_TIMEOUT = 0.75


def _hub_auth_get(hub, timeout=3.0):
    """GET <hub minter>/api/auth -> dict, {} when it is not a KASTR minter, None
    when unreachable (an open hub has no minter). Module-level twin of
    Relay.hub_auth for callers without a Relay (the launcher)."""
    host, port, minter = _hub_parts(hub)
    try:
        with urllib.request.urlopen(minter + "/api/auth", timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
        return d if isinstance(d, dict) and d.get("app") == "KASTR" else {}
    except Exception:
        return None


def _port_or_none(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if 1 <= v <= 65535 else None


def probe_hub_web(relay_url, candidates=(), budget=3.0):
    """0.15.0: -> {"web": int, "https": int|None, "via": "minter"|"instance"} or None.
    The minter (relay port+1) answers first when the hub is secured; otherwise
    the candidates (callers pass the stored/ini ports first) then 8000..8010
    are asked for /api/instance, HUB_WEB_PROBE_TIMEOUT each, until `budget`
    seconds are spent. An old hub whose /api/instance lacks `web` still counts:
    the port that answered is the port. Pure: no file IO."""
    hub = _normalize_hub(relay_url)
    if not hub:
        return None
    if is_web_relay(hub):   # 0.19.0: the origin IS the web base -- confirm it is a KASTR
        base = web_origin(hub)
        try:
            with urllib.request.urlopen(base + "/api/instance", timeout=max(0.5, min(3.0, budget))) as r:
                d = json.loads(r.read().decode("utf-8", "replace") or "{}")
        except Exception:
            return None
        if not (isinstance(d, dict) and d.get("app") == "KASTR"):
            return None
        return {"web": web_origin_port(hub), "https": None, "via": "origin", "base": base}
    host, _port, _minter = _hub_parts(hub)
    if not host:
        return None
    start = time.monotonic()
    auth = _hub_auth_get(hub, timeout=max(0.2, min(1.5, budget / 2.0)))
    if isinstance(auth, dict):
        web = _port_or_none(auth.get("web"))
        if web:
            return {"web": web, "https": _port_or_none(auth.get("https")), "via": "minter"}
    order, seen = [], set()
    for c in list(candidates or ()) + list(HUB_WEB_CANDIDATES):
        c = _port_or_none(c)
        if c and c not in seen:
            seen.add(c)
            order.append(c)
    h = ("[" + host + "]") if ":" in host else host
    for c in order:
        left = budget - (time.monotonic() - start)
        if left <= 0:
            break
        try:
            with urllib.request.urlopen("http://%s:%d/api/instance" % (h, c),
                                        timeout=min(HUB_WEB_PROBE_TIMEOUT, left)) as r:
                d = json.loads(r.read().decode("utf-8", "replace") or "{}")
        except Exception:
            continue
        if not (isinstance(d, dict) and d.get("app") == "KASTR"):
            continue
        return {"web": _port_or_none(d.get("web")) or c, "https": _port_or_none(d.get("https")),
                "via": "instance"}
    return None


HUB_WEB_SINK = None        # 0.15.0: kastr_serve.HUB_WEB once loaded -- hub_web_note mirrors into it


def _hub_web_file(state_dir):
    return os.path.join(state_dir, "hub-web.json")


def hub_web_load(state_dir):
    """state_dir/hub-web.json -> {host: {"web", "https", "at"}} (validated; {} when absent)."""
    try:
        with open(_hub_web_file(state_dir), encoding="utf-8-sig") as f:
            d = json.load(f)
    except Exception:
        return {}
    out = {}
    if isinstance(d, dict):
        for host, rec in d.items():
            if not isinstance(rec, dict):
                continue
            web = _port_or_none(rec.get("web"))
            if not web:
                continue
            try:
                at = float(rec.get("at") or 0)
            except (TypeError, ValueError):
                at = 0.0
            base = rec.get("base")
            base = base if isinstance(base, str) and re.match(r"^https?://[A-Za-z0-9.\-\[\]:]{1,260}$", base) else None
            out[str(host).strip().lower()] = {"web": web, "https": _port_or_none(rec.get("https")), "at": at, "base": base}
    return out


def hub_web_note(state_dir, host, web, https=None, base=None):
    """Remember `host`'s KASTR web (+https) port in hub-web.json (tmp + os.replace)
    and in HUB_WEB_SINK -> True when something changed. ValueError on a bad port.
    0.19.0: `base` = the full web origin of a web relay (https://name)."""
    host = str(host or "").strip().lower()
    web = _port_or_none(web)
    https = _port_or_none(https)
    base = base if isinstance(base, str) and base else None
    if not host or not web:
        raise ValueError("bad host/port")
    cur = hub_web_load(state_dir)
    prev = cur.get(host)
    changed = not (prev and prev["web"] == web and prev.get("https") == https and prev.get("base") == base)
    if changed:
        cur[host] = {"web": web, "https": https, "at": time.time(), "base": base}
        os.makedirs(state_dir, exist_ok=True)
        tmp = _hub_web_file(state_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f)
        os.replace(tmp, _hub_web_file(state_dir))
    if HUB_WEB_SINK is not None:
        HUB_WEB_SINK[host] = {"web": web, "https": https, "base": base}
    return changed


class Relay:
    def __init__(self, state_dir, log=None):
        self.binary = find_relay()
        self.state_dir = state_dir
        self.log = log or print                         # 0.10.0: the launcher's note()
        self.store = AuthStore(state_dir, self.log)     # 0.10.0: codes + rooms, persisted
        # 0.11.0: federation (spoke side) -- what the last config write found out,
        # the token in use, and the watchdog that renews it.
        self.federation = None
        self.on_room_close = None                       # 0.12.0: kastr_serve hooks the chat store's delete_room
        self.on_start = []                              # 0.18.0: callables(relay) after a successful start (the archiver)
        self.on_stop = []                               # 0.18.0: callables(relay) before a stop
        self._ctl = threading.RLock()                   # start/stop/restart never interleave
        self._fed_stop = None
        self._fed_active = None
        self._fed_last_reason = None
        self.proc = None
        self.port = 4443
        self.bind_all = False
        self.secured = False
        self.auth = None
        self.error = None
        self._log = []
        self._lock = threading.Lock()

    # ---- config ----------------------------------------------------------

    def _write_config(self, port, bind_all, secured):
        host = "[::]" if bind_all else "127.0.0.1"
        # Name every address a client might use, because the browser checks the
        # certificate against the host in the URL even when it was pinned by
        # fingerprint.
        names = ["localhost", "127.0.0.1", socket.gethostname()] + local_ips()
        seen, hosts = set(), []
        for n in names:
            if n and n not in seen:
                seen.add(n)
                hosts.append(n)

        if secured:
            _ensure_jwk(self.state_dir)
            auth = [
                "[auth]",
                # 0.16.0 (moq-relay 0.15): the relay verifies nothing itself. It POSTs one
                # Request per session event to this URL and applies the Grant. The token
                # service on port+1 (AuthService.session) verifies OUR tokens with auth.jwk
                # and answers patterns; the public kinds ride every grant, subscribe-only
                # (.channels/.stats/.presence/.talking/.chat/.state -- the pre-join screen).
                # http:// is accepted for a loopback host only; the minter always binds
                # loopback too (or everything, which includes it).
                'url = "http://127.0.0.1:%d/api/session"' % (port + 1),
            ]
        else:
            auth = [
                "[auth]",
                # Everything public, both ways: the KASTR pages connect without a token.
                'public = "**"',
            ]

        # Federation (0.8.1): a saved hub URL clusters this relay to it.
        # disable_verify is the trusted-LAN tradeoff -- KASTR relays run on
        # throwaway self-signed certs regenerated per start, so pinning is
        # impossible and a private CA is overkill for one LAN.
        cluster = []
        fed = self._cluster_raw()
        hub = _normalize_hub(fed["connect"])
        self.federation = None
        if hub:
            # 0.11.0: the hub mints our relay-to-relay token from its federation
            # code; it rides the connect URL (`?jwt=` -- the relay's documented
            # form). An open hub (no minter) is dialled bare, as before.
            tok, why, info = self.federation_token(hub, fed["code"])
            url = (hub if is_web_relay(hub) else hub + "/") + (("?jwt=" + tok) if tok else "")   # 0.19.0: https://name/relay?jwt=
            self._fed_active = tok
            self.federation = {"hub": hub, "token": bool(tok), "reason": why,
                               "exp": self._fed_cache().get("exp") if tok else None, **info}
            # 0.16.0: pin the hub's certificate (I1) -- advertised by its /api/auth, else fetched, else remembered
            self._hub_pin, tls_state = self._hub_pin_for(hub, info.get("fingerprint"))
            self.federation["tls"] = tls_state
            self.federation["fingerprint"] = self._hub_pin
            if tls_state == "insecure":
                self._fed_say("hub certificate fingerprint unavailable -- connecting without verification")
            cluster = [
                "[cluster]",
                "connect = [%s]" % json.dumps(url),    # TOML basic strings share JSON's escapes
                # 0.16.0: `linger` is gone (moq-relay 0.15 keeps a resumed broadcast's
                # subscribers on its own); [client] became [connect]. The hub's certificate
                # is pinned when its fingerprint is known (I1), else trusted blind as before.
                "",
                "[connect]",
                *self._connect_tls_lines(hub),
                "",
            ]

        # The stats NODE NAME is load-bearing twice over (0.8.1): without it
        # the relay publishes its one stats broadcast at exactly .stats/node,
        # whose announce the stats page DISCARDS (an entry whose path equals
        # the prefix arrives with an empty relative path) -- the eternal
        # "searching for nodes..." with a green light. And in a cluster,
        # nodes without distinct names collide on the same path.
        node = self.relay_name()   # user-set relay name wins (0.8.2)
        if not node:
            try:
                import kastr_serve
                node = kastr_serve.host_slug()
            except Exception:
                node = socket.gethostname() or "node"

        # 0.16.0: the internal ops listener (/metrics, /health, /nodes, /sessions) --
        # plain HTTP on loopback only, never a firewall rule.
        self.internal_port = self._pick_internal_port(port)
        cfg = [
            "[listen]",                                   # 0.16.0: was [server] / [server.tls]
            f'bind = "{host}:{port}"',
            "tls.generate = [" + ", ".join(f'"{h}"' for h in hosts) + "]",
            "",
            *auth,
            "",
            *cluster,
            *(["[internal]", f'listen = "127.0.0.1:{self.internal_port}"', ""] if self.internal_port else []),
            *self._lan_lines(bind_all, secured),   # 0.16.0: [cluster.lan] when enabled
            "[web]",
            "ws = true",           # WebSocket fallback for clients without WebTransport
            "",
            "[web.http]",
            # Serves /certificate.sha256, which is how a browser trusts the
            # generated self-signed certificate.
            f'listen = "{host}:{port}"',
            "",
            # 0.8.9: phones. A second, TLS web listener on port+2 with the
            # install's CA-signed leaf (kastr_tls) -- wss:// for iOS, and the
            # chain-validated path a https page must use. The QUIC listener
            # keeps the generated cert so desktop fingerprint pinning is
            # untouched.
            *(["[web.https]",
               f'listen = "{host}:{port + 2}"',
               'cert = "%s"' % str(self.tls["chain"]).replace("\\", "/"),
               'key = "%s"' % str(self.tls["key"]).replace("\\", "/"),
               ""] if getattr(self, "tls", None) else []),
            "[stats]",
            "enabled = true",      # publishes .stats/<node> for the stats page
            f'node = "{node}"',
            "",
        ]
        path = os.path.join(self.state_dir, "relay.toml")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(cfg))
        return path

    # ---- federation (0.8.1) ------------------------------------------------

    def _cluster_file(self):
        return os.path.join(self.state_dir, "relay-cluster.json")

    def _connect_tls_lines(self, hub):
        """0.16.0: how this spoke trusts the hub's QUIC certificate -- pinned by
        sha256 when known (I1 fills `self._hub_pin`), else `insecure` as before."""
        if is_web_relay(hub):   # 0.19.0: system roots (the tunnel's public certificate)
            return []
        pin = getattr(self, "_hub_pin", None)
        if pin:
            return ['tls.fingerprint = ["%s"]' % pin]
        return ["tls.insecure = true"]

    def _pick_internal_port(self, port):
        """0.16.0: a free loopback port for the relay's internal ops listener --
        port+3, else the next free up to port+9, else none (the relay runs without)."""
        for cand in range(int(port) + 3, int(port) + 10):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sk:
                    sk.bind(("127.0.0.1", cand))
                return cand
            except OSError:
                continue
        return None

    def internal_get(self, path, timeout=1.0):
        """GET <internal listener>/<path> -> text, or None."""
        port = getattr(self, "internal_port", None)
        if not port or not self.running():
            return None
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            return None

    def internal_post(self, path, body=None, timeout=2.0):
        """0.17.0: POST <internal listener>/<path> -> (status, text), or (None, None)."""
        port = getattr(self, "internal_port", None)
        if not port or not self.running():
            return None, None
        try:
            data = json.dumps(body).encode() if body is not None else b""
            req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception:
            return None, None

    def _force_revalidate(self):
        """0.17.0: ask the relay to re-validate its sessions now (a kick must not wait for the
        600 s revalidate timer). POST first, GET on 405; -> "post" | "get" | "unavailable"."""
        code, _ = self.internal_post("/sessions/revalidate")
        if code is not None and 200 <= code < 300:
            return "post"
        if code == 405 or code is None:
            txt = self.internal_get("/sessions/revalidate")
            if txt is not None:
                return "get"
        return "unavailable"

    def _hub_minter_url(self):
        """0.16.0: the hub minter's base URL (relay port + 1) when a hub is saved, else None."""
        try:
            hub = _normalize_hub(self._cluster_raw()["connect"])
            return _hub_parts(hub)[2] if hub else None
        except Exception:
            return None

    def _hub_pin_for(self, hub, hint=None):
        """0.16.0: -> (sha256 hex | None, "pinned" | "pinned-cached" | "insecure").
        `hint` = the fingerprint the hub's /api/auth advertised; else the hub's
        /certificate.sha256 is fetched (3 s); else what relay-cluster.json remembers."""
        if is_web_relay(hub):   # 0.19.0: a tunnel's certificate is public -- the system roots verify it
            return None, "public"
        pin = None
        h = str(hint or "").strip().lower()
        if re.match(r"^[0-9a-f]{64}$", h):
            pin = h
        if not pin:
            try:
                host, port, _m = _hub_parts(hub)
                with urllib.request.urlopen("http://%s:%d/certificate.sha256" % (host, port), timeout=3) as r:
                    h = r.read().decode("ascii", "replace").strip().lower()
                if re.match(r"^[0-9a-f]{64}$", h):
                    pin = h
            except Exception:
                pin = None
        stored = (self._cluster_raw().get("fingerprint") or {}).get("sha256")
        if pin:
            if pin != stored:
                self._cluster_note_fp(pin)
            return pin, "pinned"
        if stored:
            return stored, "pinned-cached"
        return None, "insecure"

    def _cluster_note_fp(self, pin):
        try:
            with open(self._cluster_file(), encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        d["fingerprint"] = {"sha256": pin, "at": int(time.time())}
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            tmp = self._cluster_file() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(tmp, self._cluster_file())
            self.log("relay federation: hub certificate pinned (%s...)" % pin[:12])
        except OSError as e:
            self.log("relay federation: could not note the hub fingerprint: %s" % e)

    def _fingerprint_check(self, reason):
        """0.16.0: the relay logged a certificate problem on the cluster link --
        re-learn the hub's fingerprint (debounced 30 s) off the log thread."""
        now = time.time()
        if now - getattr(self, "_fp_check_at", 0) < 30:
            return
        self._fp_check_at = now
        self.log("relay federation: %s -- re-learning the hub certificate" % reason)
        threading.Thread(target=lambda: self._federation_tick(), daemon=True).start()

    def _lan_lines(self, bind_all, secured):
        """0.16.0: the [cluster.lan] block when the operator enabled the LAN mesh.
        A loopback-only relay has no LAN to mesh on; a secured relay needs a secret."""
        st = self.store.lan_status()
        if not st["enabled"]:
            return []
        if not bind_all:
            self.log("relay: LAN mesh enabled but the relay is loopback-only -- tick 'Allow other machines'")
            return []
        secret = self.store.lan_secret()
        if secured and not secret:
            self.log("relay: LAN mesh needs a secret on a secured relay -- not enabled")
            return []
        lines = ["[cluster.lan]", "enabled = true", 'app = "kastr"']
        if secret:
            p = os.path.join(self.state_dir, "lan.secret")
            try:
                tmp = p + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(secret)
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass
                os.replace(tmp, p)
                lines.append('secret = "lan.secret"')   # RELATIVE: the relay runs with cwd = state_dir (the auth.jwk lesson)
            except OSError as e:
                self.log("relay: could not write lan.secret (%s) -- LAN mesh not enabled" % e)
                return []
        else:
            self.log("relay: LAN mesh is OPEN (no secret) -- anyone on this network may join it")
        lines.append("")
        return lines

    def lan_status(self):
        st = self.store.lan_status()
        st["active"] = bool(self.running() and st["enabled"] and self.bind_all)
        return st

    def set_lan(self, payload):
        """POST /api/relay/lan {enabled?, secret?} (loopback-guarded)."""
        st = self.store.set_lan(payload.get("enabled"), payload.get("secret"))
        self.log("relay: LAN mesh %s%s" % ("enabled" if st["enabled"] else "disabled", " with a secret" if st["hasSecret"] else ""))
        restarted = self._restart()
        out = self.lan_status()
        out["ok"] = True
        out["restarted"] = restarted
        return out

    def admin_token(self, room):
        """0.16.0: the operator's own admin token for `room` (loopback-guarded: the
        Relay page pushes stop / kick commands with it). No code needed -- the
        machine that owns the relay is its operator."""
        if not (self.auth and self.running() and self.secured):
            return {"error": "the relay is not running secured on this machine"}, 400
        slug = str(room or "")
        now = int(time.time())
        exp = now + 3600
        if not slug:
            # the whole relay (the Relay page's stream probe + push): the machine that owns
            # the relay is its operator -- the same shape a federated relay holds
            tok = _mint(self.auth.key, dict(FEDERATION_CLAIMS, iat=now, exp=exp))
            return {"ok": True, "role": "operator", "exp": exp, "token": tok}, 200
        if not SLUG_RE.match(slug):
            return {"error": "bad room name"}, 400
        tok = _mint(self.auth.key, {"root": "", "get": slug,
                                    "put": [slug] + [k + "/" + slug for k in MEMBER_KINDS] + [slug + "/" + ADMIN_KIND],
                                    "iat": now, "exp": exp})
        return {"ok": True, "role": "admin", "exp": exp, "token": tok}, 200

    def _cluster_raw(self):
        """{connect, code, master} as stored -- `code` is the hub's federation
        code in PLAIN TEXT (this relay must present it); private to this class."""
        try:
            with open(self._cluster_file(), encoding="utf-8") as f:
                d = json.load(f)
            try:
                web = int(d.get("web") or 8000)       # 0.12.0: the hub KASTR's web port (chat forwarding)
            except (TypeError, ValueError):
                web = 8000
            return {"connect": str(d.get("connect") or ""),
                    "code": str(d.get("code") or ""),
                    "master": bool(d.get("master", True)),
                    "web": web,
                    # 0.15.0: the port as STORED (None = never learned; `web` above is the
                    # 8000 fallback) so kastr_serve can prefer a learned hub-web.json entry
                    "webStored": web if d.get("web") else None,
                    # 0.16.0: the hub's pinned QUIC certificate {sha256, at}
                    "fingerprint": d.get("fingerprint") if isinstance(d.get("fingerprint"), dict) else None}
        except Exception:
            return {"connect": "", "code": "", "master": True, "web": 8000, "webStored": None, "fingerprint": None}

    def cluster_config(self):
        """The public shape (status(), GET /api/relay/cluster): never the code."""
        raw = self._cluster_raw()
        return {"connect": raw["connect"], "master": raw["master"], "hasCode": bool(raw["code"]),
                "web": raw["web"],     # 0.12.0
                "fingerprint": (raw.get("fingerprint") or {}).get("sha256")}   # 0.16.0: public (it is the hub's cert hash)

    # ---- federation token (spoke side, 0.11.0) --------------------------------

    def _fed_cache_file(self):
        return os.path.join(self.state_dir, "relay-federation.json")

    def _fed_cache(self):
        try:
            with open(self._fed_cache_file(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _fed_cache_write(self, d):
        try:
            tmp = self._fed_cache_file() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(tmp, self._fed_cache_file())
        except OSError as e:
            self.log("relay federation: could not cache the hub token: %s" % e)

    def _fed_say(self, why):
        if why != self._fed_last_reason:
            self._fed_last_reason = why
            self.log("relay federation: " + why)

    def hub_auth(self, hub):
        """GET <hub minter>/api/auth -> dict, {} when it is not a KASTR minter,
        None when unreachable (an open hub has no minter at all)."""
        host, port, minter = _hub_parts(hub)
        try:
            with urllib.request.urlopen(minter + "/api/auth", timeout=3) as r:
                d = json.loads(r.read().decode("utf-8", "replace") or "{}")
            return d if isinstance(d, dict) and d.get("app") == "KASTR" else {}
        except Exception:
            return None

    def federation_token(self, hub, code, force=False):
        """-> (token | None, reason, info). Reuses the cached token while the hub's
        key is unchanged and more than FEDERATION_RENEW remains."""
        host, port, minter = _hub_parts(hub)
        now = time.time()
        cache = self._fed_cache()
        cached_ok = cache.get("hub") == hub and cache.get("token") and float(cache.get("exp") or 0) > now
        auth = self.hub_auth(hub)
        info = {}
        if auth is None:
            if cached_ok:
                why = "hub minter %s unreachable -- using the cached token" % minter
                self._fed_say(why)
                return cache["token"], why, info
            why = "no token service at %s (open hub, or its port+1 is closed) -- connecting without a token" % minter
            self._fed_say(why)
            return None, why, info
        info = {"hubCodes": bool(auth.get("codes")), "hubFederation": bool(auth.get("federation")),
                "kid": auth.get("kid"), "fingerprint": auth.get("fingerprint")}   # 0.16.0: the hub's QUIC cert hash
        self._cluster_note_web(auth.get("web"), hub=hub, https=auth.get("https"))   # 0.14.0 F / 0.15.0: the hub told us its web (+https) port
        if not auth.get("codes"):
            why = "hub is open (no access codes) -- connecting without a token"
            self._fed_say(why)
            return None, why, info
        if (cached_ok and not force and float(cache["exp"]) - now > FEDERATION_RENEW
                and (not auth.get("kid") or cache.get("kid") in (None, auth.get("kid")))):
            return cache["token"], "hub token cached", info
        if not auth.get("federation"):
            why = "hub has no federation code set (set one on the hub's Relay page) -- connecting without a token"
            self._fed_say(why)
            return None, why, info
        if not code:
            why = "hub requires a federation code -- none saved here (Relay page > Federation)"
            self._fed_say(why)
            return None, why, info
        try:
            req = urllib.request.Request(minter + "/api/token",
                                         data=json.dumps({"federation": code}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as r:
                d = json.loads(r.read().decode("utf-8", "replace") or "{}")
            if d.get("ok") and d.get("token"):
                self._fed_cache_write({"hub": hub, "token": d["token"], "exp": int(d.get("exp") or 0),
                                       "kid": d.get("kid") or auth.get("kid"), "at": int(now)})
                why = "hub token minted (valid until %s)" % time.strftime("%Y-%m-%d", time.localtime(int(d.get("exp") or 0)))
                self._fed_say(why)
                return d["token"], why, info
            why = "hub answered without a token: %s" % (d.get("error") or "?")
        except urllib.error.HTTPError as e:
            if e.code == 403:
                why = "hub refused the federation code -- check it on both Relay pages"
            elif e.code == 429:
                why = "hub throttled the federation mint (too many wrong codes) -- retrying later"
                if cached_ok:
                    self._fed_say(why)
                    return cache["token"], why, info
            else:
                why = "hub minter error %s" % e.code
        except Exception as e:
            why = "hub minter %s failed: %s" % (minter, e)
        self._fed_say(why + " -- connecting without a token")
        if cached_ok:
            return cache["token"], why, info
        return None, why, info

    def _restart(self):
        """Stop + start with the same shape (a config change, a key rotation, a
        fresh hub token). Serialised with start/stop through _ctl."""
        with self._ctl:
            if not self.running():
                return False
            port, lan, sec = self.port, self.bind_all, self.secured
            self.stop()
            self.start(port, lan, sec)
            return True

    def _federation_watch_start(self):
        if self._fed_stop:
            self._fed_stop.set()
        evt = threading.Event()
        self._fed_stop = evt
        threading.Thread(target=self._federation_watch, args=(evt,), daemon=True).start()

    def _federation_watch(self, evt):
        while not evt.wait(FEDERATION_CHECK):
            if not self.running():
                return
            try:
                if self._federation_tick():
                    return          # the restart spawned a fresh watcher
            except Exception as e:
                self.log("relay federation: watchdog error: %s" % e)

    def _spoke_sync(self):
        """0.18.0: tell the hub where this relay's minter answers (so its bans reach us) and
        copy its active bans. Needs a federation token and a LAN-reachable minter."""
        auth = self.auth
        tok = self._fed_active
        minter = self._hub_minter_url()
        if not (auth and tok and minter and self.bind_all):
            return
        ips = [ip for ip in local_ips() if not ip.startswith("172.")] or local_ips()
        if not ips:
            return
        body = json.dumps({"minter": "http://%s:%d" % (ips[0], self.port + 1)}).encode()
        try:
            req = urllib.request.Request(minter + "/api/spokes/register", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok})
            with urllib.request.urlopen(req, timeout=4):
                pass
        except Exception as e:
            self.log("relay federation: spoke registration with the hub failed: %s" % str(e)[:120])
        try:
            auth.pull_hub_bans()
        except Exception:
            pass

    def _federation_tick(self):
        """-> True when the relay was restarted with a fresh hub token (a rotated
        hub key, fewer than 7 days left, or a hub that was dark at start)."""
        fed = self._cluster_raw()
        hub = _normalize_hub(fed["connect"])
        if not hub:
            return False
        threading.Thread(target=self._spoke_sync, daemon=True).start()   # 0.18.0
        tok, why, info = self.federation_token(hub, fed["code"])
        if tok and tok != self._fed_active:
            self.log("relay federation: %s -- restarting the relay with the fresh hub token" % why)
            self._restart()
            return True
        pin, _st = self._hub_pin_for(hub, info.get("fingerprint"))   # 0.16.0: the hub's cert changes on every hub start
        if pin and pin != getattr(self, "_hub_pin", None):
            self.log("relay federation: hub certificate changed -- restarting the relay pinned to %s..." % pin[:12])
            self._restart()
            return True
        return False

    def _name_file(self):
        return os.path.join(self.state_dir, "relay-name.json")

    def relay_name(self):
        try:
            with open(self._name_file(), encoding="utf-8") as f:
                return str(json.load(f).get("name") or "")[:32]
        except Exception:
            return ""

    def set_name(self, payload):
        # MoQ-path-safe: the name becomes the [stats] node segment, which is
        # how the hub attributes streams to spokes.
        import re as _re
        name = _re.sub(r"[^a-z0-9-]+", "-",
                       str(payload.get("name") or "").lower()).strip("-")[:32]
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self._name_file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"name": name}, f)
        os.replace(tmp, self._name_file())
        restarted = self._restart()
        return {"ok": True, "name": name, "restarted": restarted}

    def _cluster_note_web(self, web, hub=None, https=None):
        """0.14.0 F: remember the hub's advertised web port (from its /api/auth)
        in relay-cluster.json when it differs from what is stored.
        0.15.0: ALSO in hub-web.json (hub_web_note, per host, with the https
        port) whether or not a cluster link is stored -- the update feed and the
        chat proxy read it through kastr_serve.HUB_WEB."""
        cur0 = self._cluster_raw()
        if is_web_relay(hub or cur0.get("connect")):
            # 0.19.0: the minter's `web` names the hub's own port behind the proxy -- useless
            # from here; a web relay's web base is its origin.
            wr = hub or cur0.get("connect")
            try:
                if hub_web_note(self.state_dir, urlparse(web_origin(wr)).hostname, web_origin_port(wr), None, web_origin(wr)):
                    self.log("relay federation: hub %s is a web relay (%s) -- noted in hub-web.json" % (web_origin(wr), WEB_RELAY_PATH))
            except Exception as e:
                self.log("relay federation: could not note the hub web base: %s" % e)
            return
        try:
            web = int(web)
        except (TypeError, ValueError):
            return
        if not (1 <= web <= 65535):
            return
        cur = self._cluster_raw()
        host = ""
        try:
            host = (urlparse(hub or cur["connect"]).hostname or "").lower()
        except Exception:
            host = ""
        if host:
            try:
                if hub_web_note(self.state_dir, host, web, https):
                    self.log("relay federation: hub %s KASTR web port %d%s noted in hub-web.json"
                             % (host, web, (" (https %s)" % https) if https else ""))
            except Exception as e:
                self.log("relay federation: could not note the hub web port: %s" % e)
        if cur["web"] == web or not cur["connect"]:
            return
        cur["web"] = web
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            tmp = self._cluster_file() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f)
            os.replace(tmp, self._cluster_file())
            self.log("relay federation: hub KASTR web port is %d (learned from its token service)" % web)
        except OSError as e:
            self.log("relay federation: could not store the hub web port: %s" % e)

    def set_cluster(self, payload):
        """0.11.0: partial update of {connect, code, master}. A key that is absent
        or null keeps the stored value; "" clears it; an empty connect drops the
        code too. The code is never echoed back."""
        cur = self._cluster_raw()
        prev = dict(cur)
        if "connect" in payload and payload.get("connect") is not None:
            hub = str(payload.get("connect") or "").strip()
            if hub and not hub.lower().startswith(("http://", "https://")):
                hub = "https://" + hub
            cur["connect"] = _normalize_hub(hub) if hub else ""
        if "code" in payload and payload.get("code") is not None:
            cur["code"] = str(payload.get("code"))
        if "master" in payload and payload.get("master") is not None:
            cur["master"] = bool(payload.get("master"))
        if "web" in payload and payload.get("web") is not None:      # 0.12.0: hub KASTR web port
            try:
                cur["web"] = max(1, min(65535, int(payload.get("web"))))
            except (TypeError, ValueError):
                pass
        if not cur["connect"]:
            cur["code"] = ""
        if cur["connect"] != prev["connect"] or cur["code"] != prev["code"]:
            # a new hub or a new code must mint afresh -- a cached token would hide
            # a wrong code until it expired weeks later
            try:
                os.remove(self._fed_cache_file())
            except OSError:
                pass
        if cur["connect"] != prev["connect"]:
            cur["fingerprint"] = None    # 0.16.0: a new hub is pinned afresh
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self._cluster_file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f)
        os.replace(tmp, self._cluster_file())
        self._fed_last_reason = None          # say the new situation out loud once
        # A running relay picks the change up by restarting with its own shape.
        restarted = self._restart()
        return {"ok": True, "connect": cur["connect"], "master": cur["master"],
                "hasCode": bool(cur["code"]), "web": cur["web"], "restarted": restarted}

    # ---- rooms (0.12.0) ------------------------------------------------------

    def close_room(self, slug, roomKey=None, operator=False):
        """A creator (roomKey) or the operator (Relay page, loopback) closes a
        room: record gone, an hour-long tombstone, chat + attachments removed
        through on_room_close -> (reply, http code)."""
        return close_room(self.store, slug, roomKey, operator, hook=self.on_room_close, log=self.log)

    # ---- lifecycle -------------------------------------------------------

    def start(self, port=4443, bind_all=False, secured=False):
        with self._ctl:                       # 0.11.0: never interleaved with stop/restart
            return self._start_locked(port, bind_all, secured)

    def _start_locked(self, port=4443, bind_all=False, secured=False):
        if self.running():
            return self.status()
        if not self.binary:
            raise RuntimeError("moq-relay binary not found")

        port = int(port)
        secured = bool(secured)
        os.makedirs(self.state_dir, exist_ok=True)
        cfg = self._write_config(port, bind_all, secured)

        with self._lock:
            self._log = []
        self.error = None
        if secured:
            # 0.16.0: the relay admits NO session until [auth] url answers, so the token
            # service (which also answers the relay's session events) comes up FIRST.
            _, key = _ensure_jwk(self.state_dir)
            try:
                self.auth = AuthService("" if bind_all else "127.0.0.1",
                                        port + 1, key, port, self.store, self.log,
                                        hub=self._hub_minter_url,   # 0.16.0: admin codes are verified at the hub when none is set here
                                        fed_token=lambda: self._fed_active,      # 0.17.0: a kick rides the federation token to the hub
                                        revalidate=self._force_revalidate)       # 0.17.0: the relay re-asks at once
            except OSError as e:
                # A secured relay without its minter would lock everyone out
                # silently -- refuse to half-start.
                raise RuntimeError(
                    f"token service could not bind port {port + 1}: {e}")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            [self.binary, cfg, "--log-level", "info"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=1, universal_newlines=True, creationflags=flags,
            # cwd anchors the config's RELATIVE auth.jwk (see _write_config).
            cwd=self.state_dir,
        )
        # 0.9.8: the relay dies with KASTR too -- an orphaned moq-relay kept
        # port 4443 and the next start failed with "address in use".
        kastr_rtsp._job_assign(kastr_rtsp.app_job(), self.proc, print)   # 0.9.10: a failed binding is logged
        self.port, self.bind_all, self.secured = port, bind_all, secured
        threading.Thread(target=self._drain, daemon=True).start()

        # Give it a moment to bind, so the UI reports a real outcome rather
        # than "starting" and a failure the user never sees.
        for _ in range(30):
            if self.proc.poll() is not None:
                # 0.16.0: a renamed/unknown config key makes moq-relay 0.15 refuse to boot
                # with a "these settings were renamed" line -- surface THAT, not the last line
                with self._lock:
                    said = [l for l in self._log if "renamed" in l or "error" in l.lower()]
                self.error = (said[0] if said else self._last_log()) or f"exited with code {self.proc.returncode}"
                self.proc = None
                break
            if self.fingerprint():
                break
            time.sleep(0.2)

        if secured and not self.running() and self.auth:
            self.auth.close()
            self.auth = None
        if secured and self.running():
            self.auth.fingerprint = self.fingerprint()   # 0.16.0: /api/auth advertises it (spokes pin it)
            if not self.store.configured():
                self.log("relay: secured WITHOUT access codes -- any room code mints a token; "
                         "set the viewer and publisher codes on the Relay page")
        if self.running():
            # 0.10.0: the shape that runs is the shape that is remembered, so
            # the Relay page (and the next autostart) can show it back.
            self._persist_shape(port, bind_all, secured)
            if self._cluster_raw()["connect"]:
                self._federation_watch_start()   # 0.11.0: renew the hub token in time
                threading.Thread(target=self._spoke_sync, daemon=True).start()   # 0.18.0: ban fan-out registration
            for cb in list(getattr(self, "on_start", [])):   # 0.18.0: the archiver resumes its recordings
                try:
                    cb(self)
                except Exception as e:
                    self.log("relay: start callback failed: %s" % e)
        return self.status()

    def operator_url(self):
        """0.18.0: this relay's loopback URL with an operator-wide token (secured) -- what
        KASTR's own consumers (the recorder, the HLS exporter) dial. None when not running."""
        if not self.running():
            return None
        base = "http://127.0.0.1:%d/" % self.port
        if not self.secured:
            return base
        obj, code = self.admin_token("")
        return base + "?jwt=" + obj["token"] if code == 200 and obj.get("token") else None

    def _persist_shape(self, port, bind_all, secured):
        try:
            cfg = self.autostart_config()
            cfg.update(port=int(port), lan=bool(bind_all), secured=bool(secured))
            os.makedirs(self.state_dir, exist_ok=True)
            tmp = self._autostart_file() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            os.replace(tmp, self._autostart_file())
        except Exception as e:
            self.log("relay: could not remember the relay shape: %s" % e)

    # ---- access codes (0.10.0) ----------------------------------------------

    def codes_status(self):
        st = self.store.codes_status()
        st["configured"] = bool(st["viewer"] or st["publisher"])
        st["secured"] = bool(self.secured and self.running())
        st["rooms"] = self.store.room_slugs()
        return st

    def set_codes(self, payload):
        st = self.store.set_codes(payload.get("viewer"), payload.get("publisher"), payload.get("federation"),
                                  payload.get("admin"))   # 0.16.0
        self.log("relay: access codes updated -- viewer %s, publisher %s, federation %s, admin %s" % (
            "set" if st["viewer"] else "not set", "set" if st["publisher"] else "not set",
            "set" if st["federation"] else "not set", "set" if st["admin"] else "not set"))
        return {"ok": True, "codes": st, "configured": bool(st["viewer"] or st["publisher"])}

    def rotate(self):
        """A new signing key: every outstanding token dies. Pages re-mint with
        their cached codes within a minute; native publishers restart on their
        ladder with the refreshed relay URL."""
        try:
            os.remove(os.path.join(self.state_dir, "auth.jwk"))
        except FileNotFoundError:
            pass
        restarted = self._restart()
        self.log("relay: signing key rotated%s" % (" -- relay restarted" if restarted else ""))
        return {"ok": True, "restarted": restarted}

    def stop(self):
        with self._ctl:
            return self._stop_locked()

    def _stop_locked(self):
        for cb in list(getattr(self, "on_stop", [])):   # 0.18.0: the archiver stops its pipelines first
            try:
                cb(self)
            except Exception:
                pass
        if self._fed_stop:
            self._fed_stop.set()
            self._fed_stop = None
        if self.auth:
            self.auth.close()
            self.auth = None
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except OSError:
                    pass
        return self.status()

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def _drain(self):
        p = self.proc
        try:
            for line in p.stdout:
                line = ANSI.sub("", line).rstrip()
                if not line:
                    continue
                with self._lock:
                    self._log.append(line)
                    del self._log[:-LOG_LINES]
                if getattr(self, "_hub_pin", None) and TLS_FAIL_RE.search(line):   # 0.16.0
                    self._fingerprint_check("relay reported a certificate problem")
        except Exception:
            pass

    def _last_log(self):
        with self._lock:
            return self._log[-1] if self._log else None

    # ---- status ----------------------------------------------------------

    def fingerprint(self):
        """Fetch the self-signed certificate hash the relay serves."""
        if not self.running():
            return None
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/certificate.sha256", timeout=1) as r:
                return r.read().decode("ascii", "replace").strip()
        except Exception:
            return None

    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def lan_urls(self):
        if not self.bind_all:
            return []
        return [f"http://{ip}:{self.port}" for ip in local_ips()]

    def wss_urls(self):
        """0.8.9: the TLS web listener phones use (port + 2), when configured."""
        if not getattr(self, "tls", None):
            return []
        hosts = local_ips() if self.bind_all else ["127.0.0.1"]
        return [f"https://{ip}:{self.port + 2}" for ip in hosts]

    # 0.17.0: a remote reader (a LAN box, a web client) gets the public shape -- no
    # relay log, binary path, cluster/auth/internal/LAN detail; the federation block
    # keeps hub/token/tls only. The machine's own pages see everything.
    PUBLIC_STATUS_DROP = ("log", "binary", "error", "auth", "internal", "cluster", "autostart", "lan")

    def status(self, public=False):
        d = self._status_full()
        if public:
            for k in self.PUBLIC_STATUS_DROP:
                d.pop(k, None)
            fed = d.get("federation")
            if isinstance(fed, dict):
                d["federation"] = {k: fed.get(k) for k in ("hub", "token", "tls") if k in fed}
        return d

    def _status_full(self):
        with self._lock:
            log = list(self._log[-40:])
        return {
            "available": bool(self.binary),
            "binary": self.binary or "",
            "running": self.running(),
            "port": self.port,
            "bindAll": self.bind_all,
            "secured": self.secured and self.running(),
            "authPort": (self.port + 1) if (self.secured and self.running()) else None,
            "url": self.url() if self.running() else "",
            "lanUrls": self.lan_urls() if self.running() else [],
            "fingerprint": self.fingerprint(),
            "error": self.error,
            "log": log,
            "autostart": self.autostart_config(),
            "cluster": self.cluster_config(),
            "name": self.relay_name(),
            # 0.10.0: which access codes are set (never the codes), and whether a
            # secured relay is still running on room codes alone.
            "codes": self.store.codes_status(),
            "legacy": bool(self.secured and self.running() and not self.store.configured()),
            # 0.11.0: spoke side -- hub, whether a token rides the link, and why not
            "federation": self.federation,
            # 0.16.0: the per-session auth server the relay depends on, and the internal ops port
            "authUp": bool(self.auth is not None and getattr(self.auth, "httpd", None) is not None),
            "auth": (self.auth.stats() if self.auth else None),
            "internal": (getattr(self, "internal_port", None) if self.running() else None),
            "lan": self.lan_status(),   # 0.16.0
        }

    # ---- autostart (0.8.0) -------------------------------------------------
    # A small json in state_dir; the launcher reads it after the web server
    # is up and starts the relay with the saved shape.

    def _autostart_file(self):
        return os.path.join(self.state_dir, "relay-autostart.json")

    def autostart_config(self):
        try:
            with open(self._autostart_file(), encoding="utf-8") as f:
                d = json.load(f)
            return {"enabled": bool(d.get("enabled")),
                    "port": int(d.get("port") or 4443),
                    "lan": bool(d.get("lan")),
                    "secured": bool(d.get("secured"))}
        except Exception:
            return {"enabled": False, "port": 4443, "lan": False, "secured": False}

    def set_autostart(self, payload):
        cfg = {"enabled": bool(payload.get("enabled")),
               "port": int(payload.get("port") or 4443),
               "lan": bool(payload.get("lan")),
               "secured": bool(payload.get("secured"))}
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self._autostart_file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        os.replace(tmp, self._autostart_file())
        return {"ok": True, "autostart": cfg}


# Set by handle_api before invoking the firewall helper: where the script
# file may live, and which port the web UI answered on (opened too -- fleet
# updates and remote UI ride it).
_FIREWALL_DIR = None
_FIREWALL_WEB_PORT = None
WEB_PORT = None            # 0.14.0 F: this KASTR's web port (set by the launcher after bind); /api/auth advertises it
# The rules the button creates -- checked by name before ever prompting.
FIREWALL_RULES = ("KASTR MoQ Relay", "KASTR MoQ Relay (cert)",
                  "KASTR room codes", "KASTR web",
                  "KASTR MoQ Relay (wss)", "KASTR web (https)",   # 0.8.9: phone paths
                  "KASTR MoQ Relay (mDNS)")                        # 0.16.0: LAN mesh discovery
_FIREWALL_HTTPS_PORT = None   # set by the launcher when the https listener is up
HTTPS_PORT = None             # 0.15.0: this KASTR's https listener port (launcher); /api/auth advertises it (None = none)


def firewall_status():
    """Are the KASTR firewall rules already in place? (0.8.2)

    {present: true|false|null} -- null means "cannot tell" (no ufw, odd
    platform), and the UI treats that like missing (offer the button)."""
    try:
        if sys.platform == "win32":
            # One powershell call; prints each existing DisplayName.
            names = ";".join("'%s'" % n for n in FIREWALL_RULES)
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "@(%s) | ForEach-Object { if (Get-NetFirewallRule -DisplayName $_ "
                 "-ErrorAction SilentlyContinue) { $_ } }" % names.replace(";", ",")],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            found = [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
            return {"present": all(n in found for n in FIREWALL_RULES),
                    "found": found}
        # Linux: ufw only (the hint we print is ufw); inactive ufw means
        # nothing blocks -- report present so nobody is nagged.
        out = subprocess.run(["ufw", "status"], capture_output=True, text=True,
                             timeout=10)
        text = (out.stdout or "")
        if "Status: inactive" in text:
            return {"present": True, "note": "ufw inactive"}
        return {"present": None if out.returncode != 0 else
                (str(_FIREWALL_WEB_PORT or 8000) in text or "4443" in text)}
    except Exception:
        return {"present": None}


def add_firewall_rules(port):
    """Open the relay's ports in the host firewall (0.8.0).

    Windows: an elevated PowerShell runs the same three New-NetFirewallRule
    commands the Relay page prints (same DisplayNames, so re-running is just
    duplicate-named rules, not an error). The UAC prompt appears on the
    machine; declining reports honestly. Linux: pkexec runs the ufw commands
    when a desktop is present; headless boxes get the commands to run."""
    port = int(port)
    if sys.platform == "win32":
        # 0.8.1: the rules go through a SCRIPT FILE, not nested -Command
        # quoting -- the double-quoted rule text inside two PowerShell layers
        # was a quoting casualty in the field (the button "did nothing").
        # -File has no inner quoting at all. Also opens the KASTR web port:
        # fleet updates and remote UI both ride it.
        state = os.path.dirname(os.path.abspath(__file__))
        try:
            # prefer the relay state dir if importable context provides one;
            # fall back next to the module (source checkouts)
            state = _FIREWALL_DIR or state
        except NameError:
            pass
        script = os.path.join(state, "kastr-firewall.ps1")
        rules = "\n".join([
            'New-NetFirewallRule -DisplayName "KASTR MoQ Relay" -Direction Inbound '
            "-Protocol UDP -LocalPort %d -Action Allow" % port,
            'New-NetFirewallRule -DisplayName "KASTR MoQ Relay (cert)" -Direction Inbound '
            "-Protocol TCP -LocalPort %d -Action Allow" % port,
            'New-NetFirewallRule -DisplayName "KASTR room codes" -Direction Inbound '
            "-Protocol TCP -LocalPort %d -Action Allow" % (port + 1),
            'New-NetFirewallRule -DisplayName "KASTR web" -Direction Inbound '
            "-Protocol TCP -LocalPort %d -Action Allow" % (_FIREWALL_WEB_PORT or 8000),
            'New-NetFirewallRule -DisplayName "KASTR MoQ Relay (wss)" -Direction Inbound '
            "-Protocol TCP -LocalPort %d -Action Allow" % (port + 2),
            'New-NetFirewallRule -DisplayName "KASTR web (https)" -Direction Inbound '
            "-Protocol TCP -LocalPort %d -Action Allow" % (_FIREWALL_HTTPS_PORT or 8443),
            'New-NetFirewallRule -DisplayName "KASTR MoQ Relay (mDNS)" -Direction Inbound '
            "-Protocol UDP -LocalPort 5353 -Action Allow",   # 0.16.0
            'exit 0',
        ])
        with open(script, "w", encoding="utf-8") as f:
            f.write(rules)
        outer = ("$p = Start-Process powershell -Verb RunAs -Wait -PassThru "
                 "-ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','%s'); "
                 "exit $p.ExitCode" % script.replace("'", "''"))
        code = subprocess.call(
            ["powershell", "-NoProfile", "-Command", outer],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if code == 0:
            return {"ok": True, "note": "firewall rules added (relay, room codes, KASTR web)"}
        return {"ok": False,
                "error": "the elevated script did not run (UAC declined, or "
                         "the rules failed) -- run the printed commands in an "
                         "admin PowerShell instead"}
    cmds = ("ufw allow %d/udp && ufw allow %d/tcp && ufw allow %d/tcp && ufw allow %d/tcp"
            " && ufw allow %d/tcp && ufw allow %d/tcp && ufw allow 5353/udp"
            % (port, port, port + 1, _FIREWALL_WEB_PORT or 8000, port + 2, _FIREWALL_HTTPS_PORT or 8443))   # 0.16.0: + mDNS
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        code = subprocess.call(["pkexec", "sh", "-c", cmds])
        if code == 0:
            return {"ok": True, "note": "firewall rules added"}
        return {"ok": False, "error": "pkexec did not run the commands -- run "
                                      "them with sudo instead: sudo " + cmds}
    return {"ok": False, "error": "no desktop session to ask for privileges -- "
                                  "run: sudo " + cmds}


# 0.10.0: the relay control plane belongs to the machine that owns the relay.
# Everything that changes the relay (start/stop/repoint/cluster/name/
# autostart/firewall/codes/rotate) answers only a request whose Host header
# names loopback, whose peer IS loopback, and -- because kastr_serve answers
# every CORS preflight with `*` -- whose Origin (when a browser sends one) is
# a loopback page too. Reads (status, name, cluster, autostart, codes status)
# stay open.
GUARDED_POSTS = ("/api/relay/start", "/api/relay/stop", "/api/relay/use",
                 "/api/relay/cluster", "/api/relay/name", "/api/relay/autostart",
                 "/api/relay/firewall", "/api/relay/codes", "/api/relay/rotate",
                 "/api/relay/rooms/close",     # 0.12.0
                 "/api/relay/webport",         # 0.14.0 F
                 "/api/relay/rooms/group",     # 0.15.0
                 "/api/relay/lan",             # 0.16.0
                 "/api/relay/admin/token",     # 0.16.0
                 "/api/relay/bans/clear")      # 0.17.0


def _host_of(value):
    """Hostname out of a Host header or an Origin URL ([::1]:8000 included)."""
    v = str(value or "").strip()
    if "://" in v:
        try:
            return (urlparse(v).hostname or "").lower()
        except Exception:
            return ""
    v = re.sub(r":\d+$", "", v)
    return v.strip("[]").lower()


def _local_only(handler):
    host = _host_of(handler.headers.get("Host"))
    peer = (handler.client_address[0] if handler.client_address else "") or ""
    if host not in LOOPBACK_HOSTS or peer not in LOOPBACK_PEERS:
        return False
    if is_forwarded(handler):
        # 0.19.0: cloudflared and other proxies dial from loopback and may rewrite Host
        # to localhost (httpHostHeader); a forwarded request is never the machine itself.
        return False
    origin = handler.headers.get("Origin")
    if origin and _host_of(origin) not in LOOPBACK_HOSTS:
        return False
    return True


def _payload_of(handler):
    try:
        n = int(handler.headers.get("Content-Length") or 0)
        return json.loads(handler.rfile.read(n) or b"{}")
    except Exception:
        return {}


# 0.17.0: ONE notion of who is asking. "local" = the machine's own pages and tools
# (Host names loopback AND the peer IS loopback AND any Origin is a loopback page);
# "remote" = everything else -- a LAN KASTR box, a phone, a browser on another
# computer that opened this relay host's web port. A Host header alone is a claim
# any client can type; the peer address makes it an identity.
def request_class(handler):
    return "local" if _local_only(handler) else "remote"


def is_local(handler):
    return _local_only(handler)


def deny_remote(handler, what, code=403):
    """Refuse a remote caller with a JSON error (no CORS) after draining its body,
    so the connection stays sane. Returns True for `return deny_remote(...)`."""
    _payload_of(handler)
    body = json.dumps({"error": "%s only from the machine itself" % what}).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def handle_api(handler, relay, path, set_relay_url=None):
    """Serve /api/relay/*. Returns True if it handled the request."""
    if not path.startswith("/api/relay"):
        return False
    global WEB_PORT
    if not WEB_PORT:
        # 0.14.0 F: this handler runs inside the web server -- its bound port IS the
        # web port (the launcher sets it explicitly; the dev harness learns it here)
        try:
            WEB_PORT = int(handler.server.server_address[1])
        except Exception:
            pass

    def reply(obj, code=200):
        body = json.dumps(obj).encode()
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    if handler.command == "POST" and path in GUARDED_POSTS and not _local_only(handler):
        _payload_of(handler)     # drain the body so the connection stays sane
        reply({"error": "relay controls only from the machine itself (open KASTR on this computer)"}, 403)
        return True

    local = _local_only(handler)
    if path == "/api/relay/status":
        reply(relay.status(public=not local))
        return True
    # 0.17.0: every other read under /api/relay/* (name, cluster, autostart, codes,
    # firewall, webport, lan, health, bans) belongs to the Relay page, which is a
    # host page; the room list stays public (pages on other machines list rooms).
    if not local and handler.command in ("GET", "HEAD") and not path.startswith("/api/relay/rooms"):
        reply({"error": "relay settings are read from the machine itself"}, 403)
        return True

    if path == "/api/relay/bans":   # 0.17.0: who an admin removed (host page; never the remotes)
        auth = getattr(relay, "auth", None)
        rows = [{k: b.get(k) for k in ("room", "host", "target", "by", "at", "until", "via")} for b in (auth.bans.active() if auth else [])]
        reply({"bans": rows, "authUp": auth is not None})
        return True
    if path == "/api/relay/bans/clear":
        p = _payload_of(handler)
        auth = getattr(relay, "auth", None)
        n = auth.bans.clear(str(p.get("room") or ""), (str(p.get("host")) if p.get("host") else None)) if auth else 0
        if n:
            relay.log("relay auth: %d ban(s) cleared by the operator (%s%s)" % (n, p.get("room"), ("/" + str(p.get("host"))) if p.get("host") else ""))
        reply({"ok": True, "cleared": n})
        return True

    if path == "/api/relay/webport":
        # 0.14.0 F: the KASTR web port this box should bind at the next launch.
        # GET -> {port: live, pinned: N|null, default: 8000}; POST {port: N} pins
        # it in state_dir/port.json (POST {port: null} clears the pin; the
        # launcher then falls back to kastr.ini / the remembered port / 8000).
        # Applies at the next launch (Apply & relaunch on the Relay page).
        pm = os.path.join(relay.state_dir, "port.json")
        def read_pm():
            try:
                with open(pm, encoding="utf-8-sig") as f:
                    d = json.load(f)
                return d if isinstance(d, dict) else {}
            except Exception:
                return {}
        live = WEB_PORT or globals().get("_FIREWALL_WEB_PORT") or None   # handle_api declares that global further down
        if handler.command == "POST":
            payload = _payload_of(handler)
            want = payload.get("port") if isinstance(payload, dict) else None
            d = read_pm()
            if want in (None, "", 0):
                d["pinned"] = False
            else:
                try:
                    want = int(want)
                except (TypeError, ValueError):
                    reply({"error": "port must be a number"}, 400)
                    return True
                if not (1024 <= want <= 65535):
                    reply({"error": "port must be between 1024 and 65535"}, 400)
                    return True
                d.update({"port": want, "pinned": True, "at": time.time()})
                d.setdefault("host", "127.0.0.1")
                d.setdefault("wanted", 8000)
            try:
                os.makedirs(relay.state_dir, exist_ok=True)
                with open(pm + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(d, f)
                os.replace(pm + ".tmp", pm)
            except OSError as e:
                reply({"error": "could not write port.json: %s" % e}, 500)
                return True
        d = read_pm()
        pinned = None
        try:
            pinned = int(d.get("port")) if d.get("pinned") else None
        except (TypeError, ValueError):
            pinned = None
        reply({"port": live, "pinned": pinned, "default": 8000, "path": pm})
        return True

    if path == "/api/relay/rooms":
        # 0.12.0: every room this relay remembers + the recently closed (readable like status)
        # 0.15.0: + the room groups
        reply({"rooms": relay.store.rooms_public(), "closed": relay.store.closed_public(),
               "groups": relay.store.groups_public()})
        return True

    if path == "/api/relay/rooms/close":
        # 0.12.0: the operator closes a room (GUARDED: the machine itself)
        if handler.command != "POST":
            reply({"error": "POST only"}, 405)
            return True
        payload = _payload_of(handler)
        obj, code = relay.close_room(str(payload.get("slug") or ""), operator=True)
        reply(obj, code)
        return True

    if path == "/api/relay/rooms/group":
        # 0.15.0: the operator manages room groups (GUARDED: the machine itself)
        if handler.command != "POST":
            reply({"error": "POST only"}, 405)
            return True
        payload = _payload_of(handler)
        obj, code = group_op(relay.store, payload, operator=True, log=relay.log)
        reply(obj, code)
        return True

    if path == "/api/relay/lan":
        # 0.16.0: the mDNS LAN mesh -- GET {enabled, hasSecret, active}; POST {enabled?, secret?} (GUARDED)
        if handler.command == "POST":
            try:
                reply(relay.set_lan(_payload_of(handler)))
            except ValueError as e:
                reply({"error": str(e)}, 400)
            except Exception as e:
                reply({"error": str(e)}, 400)
        else:
            reply(relay.lan_status())
        return True

    if path == "/api/relay/admin/token":
        # 0.16.0: the operator's admin token for a room (GUARDED: the machine itself)
        if handler.command != "POST":
            reply({"error": "POST only"}, 405)
            return True
        payload = _payload_of(handler)
        obj, code = relay.admin_token(str(payload.get("room") or ""))
        reply(obj, code)
        return True

    if path == "/api/relay/health":
        # 0.16.0: counts only (no paths) -- readable like status
        st = relay.status()
        auth = st.get("auth") or {}
        sessions = nodes = None
        try:
            js = relay.internal_get("/sessions")
            if js:
                sessions = len((json.loads(js) or {}).get("sessions") or [])
        except Exception:
            sessions = None
        try:
            jn = relay.internal_get("/nodes")
            if jn:
                d = json.loads(jn)
                nodes = len(d.get("nodes") if isinstance(d, dict) and isinstance(d.get("nodes"), list) else (d if isinstance(d, list) else []))
        except Exception:
            nodes = None
        pairs = []
        try:
            bridge = getattr(handler.server, "rtsp", None)
            for f in (bridge.list() if bridge else []):
                pub = f.get("publish") or {}
                pairs.append({"broadcast": pub.get("broadcast") or f.get("broadcast") or "", "running": bool(pub.get("running")),
                              "parked": bool(pub.get("parked")), "gen": pub.get("gen"), "restartsTotal": pub.get("restartsTotal"),
                              "sessionFails": pub.get("sessionFails"), "sessionKills": pub.get("sessionKills"),
                              "lastSessionAt": pub.get("lastSessionAt")})
        except Exception:
            pairs = []
        try:
            helpers = kastr_rtsp.helper_versions()
        except Exception:
            helpers = {}
        reply({"relay": {"running": st.get("running"), "port": st.get("port"), "internal": bool(st.get("internal")),
                         "sessions": sessions if sessions is not None else auth.get("sessions"), "nodes": nodes},
               "auth": ({"up": bool(st.get("authUp")), **{k: auth.get(k) for k in ("sessions", "publishers", "grants", "refusals", "ended", "lastRefusal")}}
                        if st.get("secured") else {"up": None}),
               "federation": ({"hub": (st.get("federation") or {}).get("hub"), "token": (st.get("federation") or {}).get("token"),
                               "tls": (st.get("federation") or {}).get("tls"), "fingerprint": (st.get("federation") or {}).get("fingerprint")}
                              if st.get("federation") else None),
               "lan": st.get("lan"), "pairs": pairs, "helpers": helpers})
        return True

    if path == "/api/relay/metrics":
        # 0.16.0: Prometheus text -- the relay's own /metrics plus KASTR's pair gauges.
        # Loopback only: the text names broadcast paths (rooms, hosts, operators).
        if not _local_only(handler):
            handler.send_response(403)
            handler.send_header("Content-Type", "text/plain")
            handler.end_headers()
            handler.wfile.write(b"metrics answer the machine itself only\n")
            return True
        st = relay.status()
        out = []
        rm = relay.internal_get("/metrics", timeout=2.0)
        out.append(rm.rstrip("\n") if rm else "# relay internal API unreachable (relay stopped or no [internal] listener)")
        auth = st.get("auth") or {}
        out.append("# KASTR")
        out.append("kastr_relay_up %d" % (1 if st.get("running") else 0))
        out.append("kastr_auth_up %d" % (1 if st.get("authUp") else 0))
        for k, name in (("sessions", "kastr_auth_sessions"), ("publishers", "kastr_auth_publishers"),
                        ("grants", "kastr_auth_grants_total"), ("refusals", "kastr_auth_refusals_total"), ("ended", "kastr_auth_ended_total")):
            if auth.get(k) is not None:
                out.append("%s %d" % (name, int(auth.get(k) or 0)))
        def esc(v):
            return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        try:
            bridge = getattr(handler.server, "rtsp", None)
            for f in (bridge.list() if bridge else []):
                pub = f.get("publish") or {}
                b = esc(pub.get("broadcast") or f.get("broadcast") or "")
                for k, name in (("running", "kastr_rtsp_pair_running"), ("parked", "kastr_rtsp_pair_parked"), ("gen", "kastr_rtsp_pair_gen"),
                                ("restartsTotal", "kastr_rtsp_pair_restarts_total"), ("sessionFails", "kastr_rtsp_pair_session_fails_total"),
                                ("sessionKills", "kastr_rtsp_pair_session_kills_total")):
                    v = pub.get(k)
                    out.append('%s{broadcast="%s"} %d' % (name, b, int(bool(v)) if isinstance(v, bool) else int(v or 0)))
        except Exception:
            pass
        body = ("\n".join(out) + "\n").encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)
        return True

    if path == "/api/relay/codes":
        # 0.10.0: GET says WHICH codes are set (never the codes); POST sets them
        # ("" clears one, null/absent keeps it).
        if handler.command == "POST":
            try:
                reply(relay.set_codes(_payload_of(handler)))
            except Exception as e:
                reply({"error": str(e)}, 400)
        else:
            reply(relay.codes_status())
        return True

    if path == "/api/relay/rotate":
        if handler.command != "POST":
            reply({"error": "POST only"}, 405)
            return True
        _payload_of(handler)
        try:
            reply(relay.rotate())
        except Exception as e:
            reply({"error": str(e)}, 400)
        return True

    if path == "/api/relay/firewall":
        # GET = presence check (no elevation); POST = add the rules
        # (elevated, local machine only -- the guard above).
        if handler.command != "POST":
            reply(firewall_status())
            return True
        try:
            n = int(handler.headers.get("Content-Length") or 0)
            payload = json.loads(handler.rfile.read(n) or b"{}")
        except Exception:
            payload = {}
        try:
            global _FIREWALL_DIR, _FIREWALL_WEB_PORT
            _FIREWALL_DIR = relay.state_dir
            try:
                _FIREWALL_WEB_PORT = handler.server.server_address[1]
            except Exception:
                _FIREWALL_WEB_PORT = None
            reply(add_firewall_rules(int(payload.get("port") or 4443)))
        except Exception as e:
            reply({"error": str(e)}, 400)
        return True

    if path == "/api/relay/name":
        if handler.command == "POST":
            try:
                n = int(handler.headers.get("Content-Length") or 0)
                payload = json.loads(handler.rfile.read(n) or b"{}")
            except Exception:
                payload = {}
            try:
                reply(relay.set_name(payload))
            except Exception as e:
                reply({"error": str(e)}, 400)
        else:
            reply({"name": relay.relay_name()})
        return True

    if path == "/api/relay/cluster":
        if handler.command == "POST":
            try:
                n = int(handler.headers.get("Content-Length") or 0)
                payload = json.loads(handler.rfile.read(n) or b"{}")
            except Exception:
                payload = {}
            try:
                reply(relay.set_cluster(payload))
            except Exception as e:
                reply({"error": str(e)}, 400)
        else:
            reply(relay.cluster_config())
        return True

    if path == "/api/relay/autostart":
        if handler.command == "POST":
            try:
                n = int(handler.headers.get("Content-Length") or 0)
                payload = json.loads(handler.rfile.read(n) or b"{}")
            except Exception:
                payload = {}
            try:
                reply(relay.set_autostart(payload))
            except Exception as e:
                reply({"error": str(e)}, 400)
        else:
            reply(relay.autostart_config() or {"enabled": False})
        return True

    if path in ("/api/relay/start", "/api/relay/stop", "/api/relay/use"):
        try:
            n = int(handler.headers.get("Content-Length") or 0)
            payload = json.loads(handler.rfile.read(n) or b"{}")
        except Exception:
            payload = {}
        try:
            if path == "/api/relay/start":
                reply(relay.start(payload.get("port", 4443), bool(payload.get("lan")),
                                  bool(payload.get("secured"))))
            elif path == "/api/relay/stop":
                reply(relay.stop())
            else:
                # Repoint every served page at a relay without a restart.
                if set_relay_url:
                    set_relay_url(payload.get("url") or "")
                    reply({"ok": True, "relay": payload.get("url")})
                else:
                    reply({"error": "not supported"}, 400)
        except Exception as e:
            reply({"error": str(e)}, 400)
        return True

    reply({"error": "unknown endpoint"}, 404)
    return True
