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
    GET  /api/relay/rooms   -> {"rooms":[{slug,locked,persistent,creator,created,at}], "closed":{slug:ts_ms}}  (0.12.0)
    POST /api/relay/rooms/close {"slug"}  -> operator close: record, chat and attachments gone (0.12.0)
Token service (its own listener, relay-port+1):
    GET  /api/auth          -> {"app":"KASTR","secured":true,"codes":bool,"legacy":bool,"federation":bool,"kid":...,"state":true}
    GET  /api/rooms         -> {"rooms":[{"slug","locked","persistent","creator","created","at"}]}   (0.11.0 names; 0.12.0 rows)
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
CLOSED_TTL = 3600
# 0.12.0: root-prefixed announce kinds every member may put beside .presence:
# .talking/<room> (who is speaking) and .chat/<room> (a new-message nudge).
MEMBER_KINDS = (".presence", ".talking", ".chat")
# 0.13.0: state tracks. Each member publishes its facts as JSON tracks under
# `.state/<room>/<host>` (public, subscribe-only, so the lobby reads them);
# a token scoped to a host may write only that host's paths. The claim
# strings carry NO trailing slash: the relay matches per path segment, so
# "r1/host" covers r1/host/..., not r1/hostx.
STATE_PREFIX = ".state"
HOST_RE = re.compile(r"^[a-z0-9-]{1,32}-[0-9a-f]{4}$")

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
        self.codes = {"viewer": None, "publisher": None, "federation": None}   # 0.11.0: + federation
        self.rooms = {}
        self.closed = {}         # 0.12.0: slug -> ms timestamp of its close (CLOSED_TTL)
        self._load()

    def _path(self):
        return os.path.join(self.state_dir, "relay-auth.json")

    def _load(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return
        for k in ("viewer", "publisher", "federation"):
            v = d.get(k)
            self.codes[k] = v if isinstance(v, dict) and v.get("salt") and v.get("hash") else None
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

    def _save(self):
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self._path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"viewer": self.codes["viewer"], "publisher": self.codes["publisher"],
                       "federation": self.codes["federation"], "rooms": self.rooms,
                       "closed": self.closed}, f)     # 0.12.0: + closed tombstones
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
                    "federation": bool(self.codes["federation"])}

    def set_codes(self, viewer=None, publisher=None, federation=None):
        """None = unchanged, "" = clear, anything else = the new code."""
        with self.lock:
            for k, v in (("viewer", viewer), ("publisher", publisher), ("federation", federation)):
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
            self._save()
            return rec

    def drop_room(self, slug):
        """Forget a record WITHOUT a tombstone (a room un-kept and unlocked)."""
        with self.lock:
            rec = self.rooms.pop(slug, None)
            if rec is not None:
                self._save()
            return rec


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

    def __init__(self, host, port, key, relay_port, store=None, log=None):
        self.store = store or AuthStore(os.getcwd(), log)
        self.log = log or (lambda m: None)
        self.lock = threading.Lock()
        self.lockout = Lockout(self.log)     # 0.12.0: the brute-force counter, one class with kastr_serve
        self._fails = self.lockout._fails
        self._wide_logged = set()            # 0.13.0: peers that took a wide (no-host) token, logged once each
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
                                 "web": WEB_PORT or _FIREWALL_WEB_PORT or None})
                elif path == "/api/rooms":
                    # 0.11.0: the locked rooms this relay remembers (possibly empty) so a
                    # gate can list them and take their codes -- names only.
                    # 0.12.0: rows {slug, locked, persistent, creator, created, at} -- old pages read .slug
                    self._reply({"rooms": svc.store.rooms_public()})
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
                ip = (self.client_address[0] if self.client_address else "") or ""
                if ip in LOOPBACK_PEERS:
                    xff = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
                    if xff:
                        return xff
                return ip

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
        ttl = TOKEN_TTL if role == "publisher" else VIEWER_TTL
        exp = now + ttl
        if host:
            # 0.13.0: identity-scoped puts. A token writes only under the host
            # it named (its media / its .member broadcast, its .state track) plus
            # the two one-release compat announces (`<room>/.since`,
            # `.presence/<room>`, gone in 0.14). The viewer's `<room>/<host>/.member`
            # is narrower than the publisher's `<room>/<host>`: that is what keeps
            # a viewer token off media.
            if role == "publisher":
                puts = [slug + "/" + host, STATE_PREFIX + "/" + slug + "/" + host,
                        slug + "/.since", ".presence/" + slug]
            else:
                puts = [STATE_PREFIX + "/" + slug + "/" + host, slug + "/" + host + "/.member",
                        slug + "/.since", ".presence/" + slug]
            member = _mint(self.key, {"root": "", "get": slug, "put": puts, "iat": now, "exp": exp})
        elif role == "publisher":
            # 0.11.0: `.presence/<slug>` is the public room-occupancy announce (arrays are fine)
            # 0.12.0: + .talking/<slug> and .chat/<slug> (speaking + chat nudges)
            self._wide_once(peer)
            member = _mint(self.key, {"root": "", "put": [slug] + [k + "/" + slug for k in MEMBER_KINDS],
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

    def _wide_once(self, peer):
        """0.13.0: a member without a `host` took the 0.12-shaped (room-wide put)
        token -- a 0.12 page or an unsubstituted one. Noted once per peer."""
        key = peer or "?"
        with self.lock:
            if key in self._wide_logged:
                return
            self._wide_logged.add(key)
        self.log("relay auth: wide token (no host) for %s" % key)


def _normalize_hub(url):
    """'host', 'host:4443', 'https://host:4443/?jwt=x' -> 'https://host:4443'
    (scheme kept, path/query dropped: the token comes from the code, never a paste)."""
    u = str(url or "").strip()
    if not u:
        return ""
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
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
    """-> (host, relay port, minter base 'http://host:port+1')."""
    p = urlparse(hub)
    host = p.hostname or ""
    port = p.port or 4443
    h = ("[" + host + "]") if ":" in host else host
    return host, port, "http://%s:%d" % (h, port + 1)


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
                # The signing key the token service (port+1) mints against.
                # RELATIVE on purpose (the relay runs with cwd = state_dir):
                # an absolute Windows path ("C:/...") goes through the relay's
                # file layer as a URL, where the drive letter parses as a
                # scheme -- every key load then fails and every well-formed
                # token dies with 502. Proven live, 2026-09-01.
                'key = "auth.jwk"',
                # Room listing, lock badges and the stats page stay public
                # (subscribe-only) so the pre-join screen needs no token.
                # 0.11.0: `.presence/<room>` too -- room occupancy for the bubbles.
                # 0.12.0: `.talking/<room>` (who speaks) and `.chat/<room>` (new-message nudge).
                # 0.13.0: `.state/<room>/<host>` -- every member's JSON state tracks (the
                # lobby and 0.13 pages read them without a token).
                'public = { subscribe = [".channels", ".stats", ".presence", ".talking", ".chat", ".state"] }',
            ]
        else:
            auth = [
                "[auth]",
                # Empty prefix = the whole namespace is public. The KASTR pages
                # connect without a token, so anything else would refuse them.
                'public = ""',
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
            url = hub + "/" + (("?jwt=" + tok) if tok else "")
            self._fed_active = tok
            self.federation = {"hub": hub, "token": bool(tok), "reason": why,
                               "exp": self._fed_cache().get("exp") if tok else None, **info}
            cluster = [
                "[cluster]",
                "connect = [%s]" % json.dumps(url),    # TOML basic strings share JSON's escapes
                # 0.12.0: a restarted publisher resumes at a group boundary instead of re-announcing
                'linger = "20s"',
                "",
                "[client.tls]",
                "disable_verify = true",
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

        cfg = [
            "[server]",
            f'bind = "{host}:{port}"',
            "",
            "[server.tls]",
            "generate = [" + ", ".join(f'"{h}"' for h in hosts) + "]",
            "",
            *auth,
            "",
            *cluster,
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
                    "web": web}
        except Exception:
            return {"connect": "", "code": "", "master": True, "web": 8000}

    def cluster_config(self):
        """The public shape (status(), GET /api/relay/cluster): never the code."""
        raw = self._cluster_raw()
        return {"connect": raw["connect"], "master": raw["master"], "hasCode": bool(raw["code"]),
                "web": raw["web"]}     # 0.12.0

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
                "kid": auth.get("kid")}
        self._cluster_note_web(auth.get("web"))     # 0.14.0 F: the hub told us its web port
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

    def _federation_tick(self):
        """-> True when the relay was restarted with a fresh hub token (a rotated
        hub key, fewer than 7 days left, or a hub that was dark at start)."""
        fed = self._cluster_raw()
        hub = _normalize_hub(fed["connect"])
        if not hub:
            return False
        tok, why, info = self.federation_token(hub, fed["code"])
        if tok and tok != self._fed_active:
            self.log("relay federation: %s -- restarting the relay with the fresh hub token" % why)
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

    def _cluster_note_web(self, web):
        """0.14.0 F: remember the hub's advertised web port (from its /api/auth)
        in relay-cluster.json when it differs from what is stored."""
        try:
            web = int(web)
        except (TypeError, ValueError):
            return
        if not (1 <= web <= 65535):
            return
        cur = self._cluster_raw()
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
                self.error = self._last_log() or f"exited with code {self.proc.returncode}"
                self.proc = None
                break
            if self.fingerprint():
                break
            time.sleep(0.2)

        if secured and self.running():
            _, key = _ensure_jwk(self.state_dir)
            try:
                self.auth = AuthService("" if bind_all else "127.0.0.1",
                                        port + 1, key, port, self.store, self.log)
            except OSError as e:
                # A secured relay without its minter would lock everyone out
                # silently -- refuse to half-start.
                self.stop()
                raise RuntimeError(
                    f"token service could not bind port {port + 1}: {e}")
            if not self.store.configured():
                self.log("relay: secured WITHOUT access codes -- any room code mints a token; "
                         "set the viewer and publisher codes on the Relay page")
        if self.running():
            # 0.10.0: the shape that runs is the shape that is remembered, so
            # the Relay page (and the next autostart) can show it back.
            self._persist_shape(port, bind_all, secured)
            if self._cluster_raw()["connect"]:
                self._federation_watch_start()   # 0.11.0: renew the hub token in time
        return self.status()

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
        st = self.store.set_codes(payload.get("viewer"), payload.get("publisher"), payload.get("federation"))
        self.log("relay: access codes updated -- viewer %s, publisher %s, federation %s" % (
            "set" if st["viewer"] else "not set", "set" if st["publisher"] else "not set",
            "set" if st["federation"] else "not set"))
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

    def status(self):
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
                  "KASTR MoQ Relay (wss)", "KASTR web (https)")   # 0.8.9: phone paths
_FIREWALL_HTTPS_PORT = None   # set by the launcher when the https listener is up


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
            " && ufw allow %d/tcp && ufw allow %d/tcp"
            % (port, port, port + 1, _FIREWALL_WEB_PORT or 8000, port + 2, _FIREWALL_HTTPS_PORT or 8443))
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
                 "/api/relay/webport")         # 0.14.0 F


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

    if path == "/api/relay/status":
        reply(relay.status())
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
        reply({"rooms": relay.store.rooms_public(), "closed": relay.store.closed_public()})
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
