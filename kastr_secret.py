"""0.21.92 (Kenton: "fix the plain text passcodes"): SECRETS AT REST.

KASTR used to keep some secrets in its state folder as plain text -- the My room passcode and the publisher code in
rtsp-feeds.json, the hub's federation code in relay-cluster.json, the GIPHY key, link tokens, the remote-control keys,
room keys, camera URLs with a password in them. This module is the one place that decides how such a value is kept.

  seal(plain)            -> "ksec1:dp:<b64>"           Windows: DPAPI (CryptProtectData, the CURRENT USER, no UI)
                         -> "ksec1:kf:<kid>:<b64>"     elsewhere: a random 32-byte key in <state>/secret.key (0600)
                         -> "ksec1:kr:<kid>:<b64>"     ... or that key kept in the desktop keyring (Secret Service),
                                                        only for a person's KASTR ("full" mode) and only when one is there
  unseal(value)          -> the plain value; a value without the prefix is an OLD plain one and comes back as it is
                            (so a 0.21.91 file still works the first time); None when it cannot be opened (logged once)
  digest(plain)          -> "sha256:<hex>"  for what is only ever COMPARED (delete tokens, presenter tokens)
  mask(text)             -> text with tokens, codes, passwords and known secrets replaced by *** (logs, diag)
  seal_doc / open_doc    -> a JSON document of a known state file with its secret fields sealed / opened (POLICY)
  migrate_state(dir)     -> rewrites the known files (and their .bak / .corrupt copies) sealed; first start of 0.21.92

The key-file cipher is stdlib only: HMAC-SHA256 in counter mode as the keystream, encrypt-then-MAC (a separate HMAC key),
a random 16-byte nonce per value. DPAPI blobs and key-file values never move between machines: what a hub hands over
(hub-replica, room keys) travels in the clear inside the relay's own TLS + federation token and each machine seals its
own copy. A box (no window, maybe no desktop session) must re-share into locked rooms after a restart, so box modes use
DPAPI / the key file and never a keyring that might be locked at boot.

DOWNGRADE: a 0.21.91 binary reads "ksec1:..." as the code itself. Rolling back means re-entering the codes (or restoring
the .pre092 copies migrate_state does NOT keep -- by design, a plain copy is what this release removes).
"""
import base64
import fnmatch
import hashlib
import hmac
import json
import os
import re
import sys
import threading

PREFIX = "ksec1:"
_ENTROPY = b"KASTR ksec1"
_lock = threading.RLock()
_state_dir = None            # the state folder kastr.py runs from (configure); else the folder of each file
_store = None                # "dpapi" | "file" | "keyring" (configure / KASTR_SECRET_STORE)
_log = None
_said = set()
_seal_cache = {}             # plain -> sealed (one DPAPI call per value per run; the same plain seals the same way)
_open_cache = {}             # sealed -> plain
_known = {}                  # plain secret -> True (mask() replaces them in any text); insertion-ordered, capped
_KNOWN_MAX = 512
_known_re = None
_keys = {}                   # key dir -> (kid, key)


def _say(msg):
    if msg in _said:
        return
    _said.add(msg)
    try:
        (_log or (lambda m: sys.stderr.write(m + "\n")))(msg)
    except Exception:
        pass


def configure(state_dir=None, prefer_keyring=False, log=None):
    """kastr.py at start: the state folder, whether a keyring may hold the key (a person's KASTR only), the log.
    KASTR_SECRET_STORE=file|keyring|dpapi|auto overrides the choice."""
    global _state_dir, _store, _log
    with _lock:
        _state_dir = os.path.abspath(state_dir) if state_dir else None
        if log:
            _log = log
        want = (os.environ.get("KASTR_SECRET_STORE") or "auto").strip().lower()
        if want not in ("file", "keyring", "dpapi"):
            want = "dpapi" if os.name == "nt" else ("keyring" if prefer_keyring else "file")
        if want == "dpapi" and os.name != "nt":
            want = "file"
        if want == "keyring" and not _keyring():
            _say("secrets: no desktop keyring is available -- the key that seals saved codes is kept in secret.key "
                 "(owner-only) in the state folder instead")
            want = "file"
        _store = want
        _seal_cache.clear()
        _open_cache.clear()
        _keys.clear()
    return _store


def store():
    if _store is None:
        configure(_state_dir)
    return _store


# ---- Windows DPAPI ---------------------------------------------------------------------------------------------------
def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b):
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    src, _b1 = blob(data)
    ent, _b2 = blob(_ENTROPY)
    out = BLOB()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(BLOB), ctypes.c_void_p if not protect else wintypes.LPCWSTR, ctypes.POINTER(BLOB),
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
    fn.restype = wintypes.BOOL
    ok = fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out))   # CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise OSError("DPAPI error %d" % ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        k32.LocalFree.argtypes = [ctypes.c_void_p]
        k32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


# ---- the key file / keyring --------------------------------------------------------------------------------------------
def _keyring():
    try:
        import keyring  # optional; not bundled
        kr = keyring.get_keyring()
        name = type(kr).__name__.lower()
        if "fail" in name or "null" in name or "chainer" in name and not getattr(kr, "backends", None):
            return None
        return keyring
    except Exception:
        return None


def _key_dir(where):
    if _state_dir and where:
        try:
            if os.path.commonpath([_state_dir, os.path.abspath(where)]) == _state_dir:
                return _state_dir
        except ValueError:
            pass
    if where:
        p = os.path.abspath(where)
        return p if os.path.isdir(p) else os.path.dirname(p)
    return _state_dir or os.getcwd()


def _kid(key):
    return hashlib.sha256(b"kid" + key).hexdigest()[:8]


def _keyring_user(kdir):
    return "secret-key-" + hashlib.sha256(os.path.normcase(kdir).encode("utf-8")).hexdigest()[:16]


def _load_key(kdir, create, via="file"):
    """-> (kid, key) or None. The key file is written owner-only (0600) before the key goes in."""
    with _lock:
        hit = _keys.get((kdir, via))
        if hit:
            return hit
        key = None
        if via == "keyring":
            kr = _keyring()
            if not kr:
                _say("secrets: the desktop keyring is not available (locked or not running) -- saved codes sealed with it "
                     "cannot be read until it is unlocked; KASTR asks for them again")
                return None
            try:
                v = kr.get_password("KASTR", _keyring_user(kdir))
                key = base64.b64decode(v) if v else None
                if key is None and create:
                    key = os.urandom(32)
                    kr.set_password("KASTR", _keyring_user(kdir), base64.b64encode(key).decode("ascii"))
            except Exception as e:
                _say("secrets: the desktop keyring refused (%s) -- using the owner-only key file" % type(e).__name__)
                return _load_key(kdir, create, "file")
        else:
            path = os.path.join(kdir, "secret.key")
            try:
                with open(path, "rb") as f:
                    raw = f.read().strip()
                key = base64.b64decode(raw) if raw else None
                if key is not None and len(key) != 32:
                    key = None
            except FileNotFoundError:
                key = None
            except Exception as e:
                _say("secrets: %s unreadable (%s)" % (path, type(e).__name__))
                key = None
            if key is None and create:
                key = os.urandom(32)
                os.makedirs(kdir, exist_ok=True)
                tmp = "%s.%d.tmp" % (path, os.getpid())
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(base64.b64encode(key))
                if os.name != "nt":
                    os.chmod(tmp, 0o600)
                os.replace(tmp, path)
        if key is None:
            return None
        hit = (_kid(key), key)
        _keys[(kdir, via)] = hit
        return hit


def _stream(key, nonce, n):
    ek = hmac.new(key, b"ksec1 enc", hashlib.sha256).digest()
    out, i = bytearray(), 0
    while len(out) < n:
        out += hmac.new(ek, nonce + i.to_bytes(4, "big"), hashlib.sha256).digest()
        i += 1
    return bytes(out[:n])


def _tag(key, nonce, ct):
    mk = hmac.new(key, b"ksec1 mac", hashlib.sha256).digest()
    return hmac.new(mk, b"ksec1" + nonce + ct, hashlib.sha256).digest()[:16]


def _b64e(b):
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s):
    s = str(s)
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---- the API ---------------------------------------------------------------------------------------------------------
def is_sealed(v):
    return isinstance(v, str) and v.startswith(PREFIX)


def seal(plain, where=None):
    """-> the sealed form of `plain` (a str). "" and None stay as they are; a sealed value is not sealed twice."""
    if plain is None or plain == "" or not isinstance(plain, str) or is_sealed(plain):
        return plain
    remember(plain)
    with _lock:
        how = store()
        ck = (how, _key_dir(where) if how != "dpapi" else "", plain)
        hit = _seal_cache.get(ck)
        if hit:
            return hit
    data = plain.encode("utf-8")
    out = None
    if how == "dpapi":
        try:
            out = PREFIX + "dp:" + _b64e(_dpapi(data, True))
        except Exception as e:
            _say("secrets: Windows could not protect a saved code (%s) -- using the owner-only key file" % e)
            how = "file"
    if out is None:
        kd = _key_dir(where)
        via = "keyring" if how == "keyring" else "file"
        k = _load_key(kd, True, via) or _load_key(kd, True, "file")
        if k is None:
            raise OSError("no key to seal with")
        kid, key = k
        nonce = os.urandom(16)
        ct = bytes(a ^ b for a, b in zip(data, _stream(key, nonce, len(data))))
        out = PREFIX + ("kr:" if via == "keyring" and _keys.get((kd, "keyring")) == k else "kf:") + kid + ":" \
            + _b64e(nonce + ct + _tag(key, nonce, ct))
    with _lock:
        _seal_cache[ck] = out
        _open_cache[out] = plain
    return out


def unseal(v, where=None):
    """-> the plain value. An unprefixed value is an old plain one (returned as it is); None when it cannot be opened."""
    if not is_sealed(v):
        return v
    with _lock:
        hit = _open_cache.get(v)
    if hit is not None:
        return hit
    plain = None
    try:
        body = v[len(PREFIX):]
        kind, _, rest = body.partition(":")
        if kind == "dp":
            if os.name != "nt":
                raise ValueError("a Windows-protected value on another system")
            plain = _dpapi(_b64d(rest), False).decode("utf-8")
        elif kind in ("kf", "kr"):
            kid, _, b = rest.partition(":")
            k = _load_key(_key_dir(where), False, "keyring" if kind == "kr" else "file")
            if k is None or k[0] != kid:
                raise ValueError("the key that sealed it is not here (secret.key %s)" % ("missing" if k is None else "differs"))
            raw = _b64d(b)
            nonce, ct, tag = raw[:16], raw[16:-16], raw[-16:]
            if not hmac.compare_digest(tag, _tag(k[1], nonce, ct)):
                raise ValueError("it was changed or sealed with another key")
            plain = bytes(a ^ b for a, b in zip(ct, _stream(k[1], nonce, len(ct)))).decode("utf-8")
        else:
            raise ValueError("unknown kind %r" % kind[:4])
    except Exception as e:
        _say("secrets: a saved code in %s cannot be opened on this machine / account (%s) -- it is treated as not saved; "
             "enter it again" % (os.path.basename(where or "") or "the state folder", str(e)[:120]))
        return None
    remember(plain)
    with _lock:
        _open_cache[v] = plain
    return plain


def digest(plain):
    """For a value that is only ever compared: "sha256:<hex>"."""
    return "sha256:" + hashlib.sha256(str(plain).encode("utf-8")).hexdigest()


def digest_matches(stored, given):
    """A stored token (digest, or an old plain one) against what a request carries -- constant time."""
    if not stored or not given:
        return False
    stored, given = str(stored), str(given)
    if stored.startswith("sha256:"):
        return hmac.compare_digest(stored, digest(given))
    return hmac.compare_digest(stored, given)


# ---- masking ---------------------------------------------------------------------------------------------------------
_SECRET_NAMES = (r"access|accessCode|code|roomCode|roomKey|token|rtoken|key|apiKey|api_key|secret|password|passwd|pwd|"
                 r"jwt|invite|inviteToken|adminCode|viewerCode|publisherCode|federationCode|passcode|pass|admin|"
                 r"publisher|viewer|federation|newCode|oldCode|room_code|bearer")
_MASKS = [
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]{1,15}://)[^/\s@\"'<>]+@"), r"\1***@"),                     # user:pass@
    (re.compile(r"(?i)([?&;](?:jwt|token|access|code|roomcode|key|apikey|api_key|secret|password|passwd|pwd|pass|"
                r"auth|invite|sig|rtoken|i)=)[^&\s\"'#<>]+"), r"\1***"),                                # ?jwt=... &code=...
    (re.compile(r"(?i)([\"'](?:" + _SECRET_NAMES + r")[\"']\s*:\s*[\"'])[^\"']+([\"'])"), r"\1***\2"),   # "code": "..."
    (re.compile(r"(?i)(?<![A-Za-z0-9_?&;])((?:roomcode|newcode|passcode|code|access|password|passwd|token|secret|key)=)"
                r"(?!\d{1,5}(?![^\s&\"',;)]))[^\s&\"',;)]{4,}"), r"\1***"),                         # code=... in free text
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{6,}"), r"\1***"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}(?:\.[A-Za-z0-9_-]*)?"), "eyJ***"),           # a JWT
    (re.compile(r"\bki-([0-9a-f]{8})-[A-Za-z0-9_-]{32,64}"), r"ki-\1-***"),                              # an invite token
    (re.compile(r"ksec1:[a-z]{2}:[A-Za-z0-9_:-]{8,}"), "ksec1:***"),                                     # even sealed ones
]


def remember(v):
    """A secret this process saw (sealed, opened, typed): mask() replaces it anywhere. Short all-digit ones are left
    to the patterns (they would eat timestamps and ports)."""
    global _known_re
    if not isinstance(v, str):
        return
    v = v.strip()
    if len(v) < 4 or (v.isdigit() and len(v) < 6) or v in _known or is_sealed(v):
        return
    with _lock:
        _known[v] = True
        while len(_known) > _KNOWN_MAX:
            _known.pop(next(iter(_known)))
        _known_re = None


def forget_all():
    """Tests: drop the known-secret registry and the caches."""
    global _known_re
    with _lock:
        _known.clear()
        _known_re = None
        _seal_cache.clear()
        _open_cache.clear()
        _keys.clear()
        _said.clear()


def mask(text):
    """Text for a log line or a diag report with every token, code, password and known secret replaced by ***."""
    global _known_re
    if text is None:
        return text
    t = str(text)
    for rx, rep in _MASKS:
        t = rx.sub(rep, t)
    with _lock:
        if _known and _known_re is None:
            alts = sorted(_known, key=len, reverse=True)
            _known_re = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(a) for a in alts) + r")(?![A-Za-z0-9])")
        rx = _known_re
    if rx is not None:
        t = rx.sub("***", t)
    return t


_CRED_RE = re.compile(r"(?i)(://[^/\s@]+@|[?&;](?:jwt|token|access|code|key|apikey|api_key|secret|password|passwd|pwd|"
                      r"pass|auth|invite|sig|i)=[^&\s]|\bki-[0-9a-f]{8}-|\beyJ[A-Za-z0-9_-]{6,}\.)")


def has_creds(s):
    """Does this URL / text carry a credential (user:pass@, ?jwt=, ?key=, an invite token, a JWT)?"""
    return isinstance(s, str) and bool(_CRED_RE.search(s))


# ---- documents (per-file policy) -------------------------------------------------------------------------------------
# path syntax: keys joined by "/", "*" = every value of a dict / item of a list, a trailing "~" = seal only when the
# string carries a credential (camera URLs: most have none, and a plain one is matched against what pages send).
POLICY = [
    ("rtsp-feeds.json", ("access", "roomCode", "feeds/*/url~", "feeds/*/xsCodes/*", "removed/*/url~")),
    ("relay-auth.json", ("rooms/*/roomKey",)),
    ("relay-auth.corrupt-*.json", ("rooms/*/roomKey",)),
    ("hub-replica.json", ("store/rooms/*/roomKey",)),
    ("relay-cluster.json", ("code", "standby/secret", "standbyOf/secret")),
    ("relay-federation.json", ("token",)),
    ("relay-mesh.json", ("links/*/token",)),
    ("relay-link.json", ("tokens/*/token",)),
    ("gif-search.json", ("key",)),
    ("rcadmin.json", ("key",)),
    ("relay-rcx.json", ("machines/*/key",)),
    ("invite-pending.json", ("token",)),
    ("prefs.json", ("items/*~",)),
]


def policy_for(path):
    b = os.path.basename(str(path or ""))
    if b.endswith(".bak"):
        b = b[:-4]
    for pat, fields in POLICY:
        if fnmatch.fnmatchcase(b, pat):
            return fields
    return ()


def _walk(obj, parts, fn):
    """Apply fn to every leaf the path names (in place on a copy made by the caller) -> how many changed."""
    if not parts:
        return 0
    head, rest = parts[0], parts[1:]
    n = 0
    if head == "*":
        items = list(obj.items()) if isinstance(obj, dict) else (list(enumerate(obj)) if isinstance(obj, list) else [])
    else:
        items = [(head, obj.get(head))] if isinstance(obj, dict) and head in obj else []
    for k, v in items:
        if rest:
            n += _walk(v, rest, fn)
        else:
            nv = fn(v)
            if nv is not v and nv != v:
                obj[k] = nv
                n += 1
    return n


def _apply(path, doc, sealing):
    fields = policy_for(path)
    if not fields or not isinstance(doc, (dict, list)):
        return doc, 0
    doc = json.loads(json.dumps(doc))   # never change the caller's object
    n = 0
    for spec in fields:
        cond = spec.endswith("~")
        parts = (spec[:-1] if cond else spec).split("/")
        if sealing:
            def fn(v, cond=cond):
                if not isinstance(v, str) or not v or is_sealed(v):
                    return v
                if cond and not has_creds(v):
                    return v
                return seal(v, path)
        else:
            def fn(v):
                if not is_sealed(v):
                    return v
                p = unseal(v, path)
                return "" if p is None else p
        n += _walk(doc, parts, fn)
    return doc, n


def seal_doc(path, doc):
    """The document as it goes to disk: the secret fields of this file sealed."""
    return _apply(path, doc, True)[0]


def open_doc(path, doc):
    """The document as read from disk: sealed fields opened (an unopenable one reads as "" -- not saved)."""
    return _apply(path, doc, False)[0]


def needs_migration(path, doc):
    return _apply(path, doc, True)[1] > 0


def write_json(path, doc, mode=0o600):
    """Atomic, owner-only on POSIX, the policy applied."""
    data = json.dumps(seal_doc(path, doc))
    tmp = "%s.%d.%d.mig.tmp" % (path, os.getpid(), threading.get_ident())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    if os.name != "nt":
        os.chmod(tmp, mode)
    for i in range(10):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError:
            if i == 9:
                raise
            import time
            time.sleep(0.02 * (i + 1))
    return False


def read_json(path):
    """-> the opened document, or None."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return open_doc(path, json.load(f))
    except Exception:
        return None


def migrate_state(state_dir, log=None):
    """First start of 0.21.92: every known file (and its .bak / .corrupt copies) rewritten with its secrets sealed;
    stale *.tmp copies of them (a crash mid-write could leave a plain one) removed. -> [basename, ...] migrated."""
    done = []
    if not state_dir or not os.path.isdir(state_dir):
        return done
    try:
        names = sorted(os.listdir(state_dir))
    except OSError:
        return done
    for fn in names:
        p = os.path.join(state_dir, fn)
        if not os.path.isfile(p):
            continue
        base = fn
        if fn.endswith(".tmp"):
            stem = re.sub(r"(\.\d+)*(\.mig)?\.tmp$", "", fn)
            if policy_for(stem):
                try:
                    os.remove(p)
                    done.append(fn + " (removed)")
                except OSError:
                    pass
            continue
        if not policy_for(base):
            continue
        try:
            with open(p, encoding="utf-8-sig") as f:
                doc = json.load(f)
        except Exception:
            continue
        try:
            if needs_migration(p, doc):
                write_json(p, doc)
                done.append(fn)
        except Exception as e:
            if log:
                try:
                    log("secrets: could not seal %s: %s" % (fn, e))
                except Exception:
                    pass
    if done and log:
        try:
            log("secrets: sealed the saved codes in %s (%s)" % (", ".join(done), store()))
        except Exception:
            pass
    return done


def owner_only(path):
    """A file a helper must read in the clear (moq-relay's relay.toml / relay-peers.json / auth.jwk): owner-only on
    POSIX. On Windows the state folder under %LOCALAPPDATA% already allows only the user (and SYSTEM / admins)."""
    if os.name == "nt" or not path:
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
