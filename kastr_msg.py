# -*- coding: utf-8 -*-
"""0.21.88 PRIVATE MESSAGES -- the hub's end-to-end encrypted store-and-forward.

Kenton (2026-10-26): "I would like to add a private messaging feature. Ability to message people privately whether
online/offline. If offline, send it when back online. Ability to setup group messages. These messages are not tied to any
rooms." + "If a user connects with the same name and enters the same 'my room' password, then they should be able to access
the previous messages."

WHO IS WHO (until 0.22 SSO): a PERSON = a name with a My room (0.21.75: name + personal code, kept on the hub). Each person
has ONE identity key pair (ECDH P-256). The browser that sets messaging up first makes the pair, wraps the private key with
AES-GCM under PBKDF2-SHA256(My room code, a random salt, >= 600 000 iterations) and hands the hub {public key, wrapped private
key, iv, salt, iterations}. Any device that proves name + My room code to the hub (the same check My room makes) gets the
wrapped key back and opens it locally into a NON-EXTRACTABLE WebCrypto key kept in that browser's IndexedDB. The hub never
holds the private key or the code-derived key; it holds the code's salted hash (My room) and the wrapped key.
0.22: the person record keeps a `sub` slot -- the Entra object id the identity is re-bound to later.

MESSAGES: the sender encrypts the body once with a random AES-GCM key and wraps that key for every recipient PERSON (and for
itself, so the sender's other devices show what was sent): ECDH(sender's identity key, recipient's public key) -> HKDF ->
AES-GCM. The hub keeps only {iv, ciphertext, wraps by key id} (+ who may read it, by name) for 90 days. Files are encrypted
with their own key (inside the message body) and uploaded as ciphertext. Devices pull (since a cursor) and ack; a ping rides
the 4 s people beat so a device pulls at once. Groups: hub-visible membership (names only); bodies stay end to end.

Everything here runs on the HUB (or a lone relay). A spoke checks the page's member token and forwards the call
(rooms_fed op "msg", the federation token vouching for the device) -- see AuthService.msg_api in kastr_relay.py."""
import base64
import hashlib
import json
import os
import re
import threading
import time

MSG_KEEP_S = 90 * 86400             # Kenton: history kept 90 days (the hub deletes ciphertext older than that)
MSG_CODE_MIN = 8                    # a My room code that also protects a messaging key (offline guessing of the wrapped key)
MSG_PBKDF2_MIN = 600000             # iterations the wrapped key must claim (OWASP 2023 for PBKDF2-SHA256)
MSG_CT_MAX = 96 * 1024              # base64 characters of one message body (text + file keys; ~70 KB)
MSG_FILE_MAX = 25 * 1024 * 1024 + 1024   # one attachment's ciphertext (25 MB + the GCM tag and some slack)
MSG_FILES_TOTAL = 8 * 1024 ** 3     # every attachment the hub keeps
MSG_PULL_MAX = 100                  # messages one pull hands out
MSG_PULL_BYTES = 6 * 1024 * 1024    # ... and about this many bytes
MSG_GROUP_MAX = 50                  # people in one group
MSG_SEND_RATE = (120, 60)           # messages one device may send per minute
MSG_FILE_RATE = (40, 600)           # attachments one device may upload per 10 minutes
MSG_TOTAL_MAX = 200000              # messages one hub keeps (the oldest go first)
MSG_NOTE_KEEP_S = 30 * 86400        # "a new device unlocked your messages" notes
MSG_PING_KEEP_S = 600

KID_RE = re.compile(r"^[0-9a-f]{16}$")
GID_RE = re.compile(r"^g-[0-9a-f]{16}$")
FID_RE = re.compile(r"^f-[0-9a-f]{32}$")
CID_RE = re.compile(r"^[A-Za-z0-9_-]{8,48}$")
B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
HOST_RE = re.compile(r"^[a-z0-9-]{1,32}-[0-9a-f]{4}$")
NAME_MAX = 48


def name_disp(name):
    """A person's name as shown (trimmed, inner spaces collapsed, at most 48) -- kastr_relay.personal_name."""
    return " ".join(str(name or "").split())[:NAME_MAX]


def name_key(name):
    """The lookup key of a name (case-insensitive) -- kastr_relay.personal_key: the same person My room knows."""
    return name_disp(name).lower()


def b64ok(s, lo, hi):
    s = str(s or "")
    return lo <= len(s) <= hi and bool(B64_RE.match(s))


def kid_of(pub_b64):
    """The key id of a public key: the first 16 hex of sha256 over its raw bytes."""
    try:
        raw = base64.b64decode(pub_b64)
    except Exception:
        return ""
    return hashlib.sha256(raw).hexdigest()[:16]


def pub_ok(pub_b64):
    """An uncompressed P-256 point (65 bytes, 0x04 first) -- what WebCrypto exports as "raw"."""
    try:
        raw = base64.b64decode(str(pub_b64 or ""), validate=True)
    except Exception:
        return False
    return len(raw) == 65 and raw[0] == 4


def _save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    for i in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 5:
                raise
            time.sleep(0.02 * (i + 1))


def _load(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


class Messenger:
    """The hub's message store. `check_code(name, code)` -> bool (the My room check), `has_room(name)` -> bool,
    `set_code(name, code)` -> bool (a new My room code), `ping(hosts, seq)` (tell those devices to pull)."""

    def __init__(self, state_dir, log=None, check_code=None, has_room=None, set_code=None, ping=None):
        self.dir = os.path.join(state_dir, "messages")
        self.log = log or (lambda m: None)
        self.check_code = check_code or (lambda n, c: False)
        self.has_room = has_room or (lambda n: False)
        self.set_code = set_code or (lambda n, c: False)
        self.ping = ping or (lambda hosts, seq: None)
        self.lock = threading.RLock()
        self.meta_path = os.path.join(self.dir, "meta.json")
        m = _load(self.meta_path) or {}
        self.fleet = str(m.get("fleet") or "") if re.match(r"^[0-9a-f]{16}$", str(m.get("fleet") or "")) else os.urandom(8).hex()
        self.seq = int(m.get("seq") or 0)
        self.persons = m.get("persons") if isinstance(m.get("persons"), dict) else {}
        self.groups = m.get("groups") if isinstance(m.get("groups"), dict) else {}
        self.reads = m.get("reads") if isinstance(m.get("reads"), dict) else {}        # nk -> {conv: seq}
        self.cursors = m.get("cursors") if isinstance(m.get("cursors"), dict) else {}  # device host -> {nk: seq, "at": t}
        self.notes = m.get("notes") if isinstance(m.get("notes"), dict) else {}        # nk -> [{id, at, host, kind}]
        self.files = m.get("files") if isinstance(m.get("files"), dict) else {}        # fid -> {at, size, by, who: [nk] | None}
        self.msgs = {}                                                                   # seq -> envelope
        self.rate = {}
        self.ver = 0                     # moves with every change (a standby's copy asks for the store again when it moved)
        self.boot = os.urandom(4).hex()  # ... and a restarted hub counts from 0 again
        self._dirty = False
        self._saved = 0.0
        self._timer = None
        md = os.path.join(self.dir, "m")
        try:
            names = os.listdir(md)
        except OSError:
            names = []
        cut = time.time() - MSG_KEEP_S
        for fn in names:
            if not fn.endswith(".json"):
                continue
            e = _load(os.path.join(md, fn))
            if isinstance(e, dict) and isinstance(e.get("seq"), int) and float(e.get("at") or 0) >= cut:
                self.msgs[e["seq"]] = e
                self.seq = max(self.seq, e["seq"])
        if not m:
            self._dirty = True
        self.sweep()

    # ---- persistence ----------------------------------------------------------------------------------------------
    def _meta(self):
        return {"fleet": self.fleet, "seq": self.seq, "persons": self.persons, "groups": self.groups, "reads": self.reads,
                "cursors": self.cursors, "notes": self.notes, "files": self.files}

    def _touch(self, now=False):
        """Meta changed: written at once (`now`: identities, groups) or within two seconds (cursors, reads)."""
        self._dirty = True
        self.ver += 1
        if now:
            self.flush()
            return
        if self._timer is None:
            self._timer = threading.Timer(2.0, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self):
        with self.lock:
            t, self._timer = self._timer, None
            doc = json.loads(json.dumps(self._meta())) if self._dirty else None
            self._dirty = False
        if t:
            try:
                t.cancel()
            except Exception:
                pass
        if doc is not None:
            try:
                _save(self.meta_path, doc)
                self._saved = time.time()
            except Exception as e:
                self.log("messages: could not save: %s" % e)

    def _msg_path(self, seq):
        return os.path.join(self.dir, "m", "%010d.json" % int(seq))

    def _file_path(self, fid):
        return os.path.join(self.dir, "f", fid + ".bin")

    def sweep(self, now=None):
        """Forget what is older than 90 days: messages, attachments (and uploads no message took within an hour), notes,
        cursors of devices gone 90 days, deleted groups' tombstones."""
        now = time.time() if now is None else now
        cut = now - MSG_KEEP_S
        gone_m, gone_f = [], []
        with self.lock:
            for s in [s for s, e in self.msgs.items() if float(e.get("at") or 0) < cut]:
                self.msgs.pop(s, None)
                gone_m.append(s)
            if len(self.msgs) > MSG_TOTAL_MAX:
                for s in sorted(self.msgs)[:len(self.msgs) - MSG_TOTAL_MAX]:
                    self.msgs.pop(s, None)
                    gone_m.append(s)
            for fid, f in list(self.files.items()):
                at = float(f.get("at") or 0)
                if at < cut or (f.get("who") is None and now - at > 3600):
                    self.files.pop(fid, None)
                    gone_f.append(fid)
            for nk in list(self.notes):
                self.notes[nk] = [x for x in self.notes[nk] if now - float(x.get("at") or 0) <= MSG_NOTE_KEEP_S][-20:]
                if not self.notes[nk]:
                    self.notes.pop(nk, None)
            for h in [h for h, c in self.cursors.items() if now - float(c.get("at") or 0) > MSG_KEEP_S]:
                self.cursors.pop(h, None)
            for gid in [g for g, r in self.groups.items() if r.get("deleted") and now - float(r.get("deleted") or 0) > MSG_KEEP_S]:
                self.groups.pop(gid, None)
            if gone_m or gone_f:
                self._dirty = True
        for s in gone_m:
            try:
                os.remove(self._msg_path(s))
            except OSError:
                pass
        for fid in gone_f:
            try:
                os.remove(self._file_path(fid))
            except OSError:
                pass
        if gone_m or gone_f:
            self.log("messages: %d message(s), %d attachment(s) older than 90 days deleted" % (len(gone_m), len(gone_f)))
            self.flush()
        return len(gone_m), len(gone_f)

    # ---- helpers -----------------------------------------------------------------------------------------------------
    def _rate_ok(self, key, rule, now):
        n, win = rule
        ts = [t for t in self.rate.get(key, []) if now - t < win]
        if len(ts) >= n:
            self.rate[key] = ts
            return False
        ts.append(now)
        self.rate[key] = ts
        return True

    def _unlocked(self, nk, host):
        p = self.persons.get(nk)
        return bool(p) and host in (p.get("devices") or {}) and host not in (p.get("blocked") or {})

    def _pub_row(self, nk):
        p = self.persons.get(nk)
        if not p:
            return None
        return {"name": p.get("name") or nk, "kid": p["kid"], "pub": p["pub"], "devices": len(p.get("devices") or {}),
                "at": int(p.get("at") or 0)}

    def _device_note(self, nk, host, now, kind="device"):
        nid = os.urandom(6).hex()
        self.notes.setdefault(nk, []).append({"id": nid, "at": int(now), "host": host, "kind": kind})
        self.notes[nk] = self.notes[nk][-20:]

    def _ping_person(self, nks, seq, skip=None):
        hosts = set()
        for nk in nks:
            p = self.persons.get(nk) or {}
            for h in p.get("devices") or {}:
                if h != skip and h not in (p.get("blocked") or {}):
                    hosts.add(h)
        if hosts:
            try:
                self.ping(sorted(hosts), seq)
            except Exception as e:
                self.log("messages: ping failed: %s" % e)

    def _store_msg(self, env):
        os.makedirs(os.path.join(self.dir, "m"), exist_ok=True)
        _save(self._msg_path(env["seq"]), env)

    def _sys(self, gid, ev, by, now, **kw):
        """A group event in its conversation (hub-visible metadata: names only)."""
        self.seq += 1
        g = self.groups[gid]
        who = sorted(set(g.get("members") or []) | set(kw.pop("extra", []) or []))
        env = {"seq": self.seq, "uid": "s:" + os.urandom(8).hex(), "at": int(now), "kind": "sys", "gid": gid, "from": by, "fromName": (self.persons.get(by) or {}).get("name") or by,
               "who": who, "sys": dict(kw, ev=ev)}
        self.msgs[env["seq"]] = env
        self._store_msg(env)
        return env

    def _group_public(self, g):
        return {"gid": g["gid"], "name": g.get("name") or "", "creator": g.get("creator") or "", "members": list(g.get("members") or []),
                "names": {k: v for k, v in (g.get("names") or {}).items() if k in (g.get("members") or [])},
                "at": int(g.get("at") or 0), "ver": int(g.get("ver") or 0), "deleted": bool(g.get("deleted"))}

    # ---- the API ---------------------------------------------------------------------------------------------------
    def api(self, p, host, admin=False, now=None):
        """One POST /api/msg {op, ...} from the device `host` (its member token checked by the minter that took it).
        -> (reply, http code). A wrong My room code answers 403 with `wrong: true` (the minter that took the call counts it
        toward its lockout)."""
        now = time.time() if now is None else now
        p = p if isinstance(p, dict) else {}
        op = str(p.get("op") or "")
        if not HOST_RE.match(str(host or "")):
            return {"ok": False, "error": "this page's token names no device -- rejoin a room"}, 403
        fn = getattr(self, "op_" + op, None) if re.match(r"^[a-z]{2,12}$", op) else None
        if fn is None:
            return {"ok": False, "error": "unknown op"}, 400
        if op in ("devices", "devremove", "devallow") and not admin:
            return {"ok": False, "error": "only an admin manages someone's messaging devices"}, 403
        with self.lock:
            return fn(p, host, now)

    def _who(self, p, host, key="as"):
        """The person this device acts as (`as`: a name it unlocked) -> (nk, error reply)."""
        nk = name_key(p.get(key))
        if not nk:
            return None, ({"ok": False, "error": "who are you? (your name)"}, 400)
        if not self._unlocked(nk, host):
            return None, ({"ok": False, "locked": True, "error": "this device has not unlocked messages for %s" % name_disp(p.get(key))}, 403)
        return nk, None

    def _code(self, p):
        name, code = name_disp(p.get("name")), str(p.get("code") or "")
        if not name:
            return None, ({"ok": False, "error": "your name is required"}, 400)
        if not code or len(code) > 128 or not self.check_code(name, code):
            return None, ({"ok": False, "wrong": True, "error": "wrong name or My room code"}, 403)
        return name, None

    def op_status(self, p, host, now):
        """{name} -> {fleet, has (a messaging identity), myRoom (a My room under that name), unlocked (this device), kid}."""
        name = name_disp(p.get("name"))
        nk = name_key(name)
        per = self.persons.get(nk) if nk else None
        out = {"ok": True, "fleet": self.fleet, "codeMin": MSG_CODE_MIN, "iter": MSG_PBKDF2_MIN, "has": bool(per),
               "myRoom": bool(nk) and bool(self.has_room(name)), "unlocked": bool(per) and self._unlocked(nk, host),
               "blocked": bool(per) and host in (per.get("blocked") or {})}
        if per:
            out.update(kid=per["kid"], name=per.get("name") or name)
        return out, 200

    def op_unlock(self, p, host, now):
        """{name, code} -> the wrapped identity (this device is then one of the person's), or {setup: true} when the person has
        none yet. A new device leaves a note for the person's other devices."""
        name, err = self._code(p)
        if err:
            return err
        nk = name_key(name)
        per = self.persons.get(nk)
        if not per:
            return {"ok": True, "setup": True, "fleet": self.fleet, "codeMin": MSG_CODE_MIN, "iter": MSG_PBKDF2_MIN}, 200
        if host in (per.get("blocked") or {}):
            return {"ok": False, "blocked": True, "error": "an admin removed this device from %s's messages -- ask an admin to allow it again" % per.get("name")}, 403
        devs = per.setdefault("devices", {})
        fresh = host not in devs
        devs[host] = {"at": int(now), "first": int((devs.get(host) or {}).get("first") or now)}
        if fresh:
            self._device_note(nk, host, now)
            self._ping_person([nk], self.seq, skip=host)
            self.log("messages: %s unlocked %s's messages (a new device)" % (host, per.get("name")))
        self._touch(now=fresh)
        return {"ok": True, "fleet": self.fleet, "person": {"name": per.get("name"), "nk": nk, "kid": per["kid"], "pub": per["pub"],
                "wrapped": per["wrapped"], "iv": per["iv"], "salt": per["salt"], "iter": per["iter"],
                "old": [dict(x) for x in per.get("old") or []]}}, 200

    def _wrapped_ok(self, p):
        try:
            it = int(p.get("iter") or 0)
        except (TypeError, ValueError):
            it = 0
        return (b64ok(p.get("wrapped"), 64, 1024) and b64ok(p.get("iv"), 16, 16) and b64ok(p.get("salt"), 24, 44)
                and MSG_PBKDF2_MIN <= it <= 10 * MSG_PBKDF2_MIN), it

    def op_setup(self, p, host, now):
        """{name, code, newCode?, pub, wrapped, iv, salt, iter, replace?} -> the person's identity is made (first device).
        `newCode` first gives My room a new (longer) code -- the key is wrapped under it. `replace` makes a new identity for a
        person whose old key nobody can open any more (an admin reset the code): older messages stay unreadable."""
        name, err = self._code(p)
        if err:
            return err
        nk = name_key(name)
        per = self.persons.get(nk)
        if per and not p.get("replace"):
            return {"ok": False, "exists": True, "error": "%s already has a messaging key -- unlock it" % per.get("name")}, 409
        new = str(p.get("newCode") or "")
        use = new or str(p.get("code") or "")
        if len(use) < MSG_CODE_MIN:
            return {"ok": False, "short": True, "codeMin": MSG_CODE_MIN,
                    "error": "messages need a My room code of at least %d characters" % MSG_CODE_MIN}, 400
        ok, it = self._wrapped_ok(p)
        if not ok or not pub_ok(p.get("pub")):
            return {"ok": False, "error": "bad key material"}, 400
        if per and host in (per.get("blocked") or {}):
            return {"ok": False, "blocked": True, "error": "an admin removed this device from these messages"}, 403
        if new and new != str(p.get("code") or "") and not self.set_code(name, new):
            return {"ok": False, "error": "could not change the My room code"}, 500
        kid = kid_of(p["pub"])
        old = list((per or {}).get("old") or [])
        if per:
            old.append({"kid": per["kid"], "pub": per["pub"], "until": int(now)})
        self.persons[nk] = {"name": name, "kid": kid, "pub": p["pub"], "wrapped": p["wrapped"], "iv": p["iv"], "salt": p["salt"], "iter": it,
                            "at": int(now), "created": int(now), "by": host, "devices": {host: {"at": int(now), "first": int(now)}},
                            "blocked": dict((per or {}).get("blocked") or {}), "old": old[-8:],
                            "keyAt": int(now),               # when the key material last changed (merges keep the newer)
                            "sub": (per or {}).get("sub")}   # 0.22: the Entra object id this identity is re-bound to
        if per:
            self._device_note(nk, host, now, kind="replaced")
        self._touch(now=True)
        self.log("messages: %s set up %s's messaging key%s" % (host, name, " (a NEW key: older messages stay unreadable)" if per else ""))
        return {"ok": True, "fleet": self.fleet, "kid": kid, "replaced": bool(per), "recoded": bool(new)}, 200

    def op_recode(self, p, host, now):
        """{name, code, newCode, wrapped, iv, salt, iter} -> My room takes the new code and the messaging key is wrapped under
        it (the page opened the old wrap with the old code and wrapped the same key again). Every device keeps working."""
        name, err = self._code(p)
        if err:
            return err
        nk = name_key(name)
        per = self.persons.get(nk)
        new = str(p.get("newCode") or "")
        if len(new) < MSG_CODE_MIN or len(new) > 128:
            return {"ok": False, "short": True, "codeMin": MSG_CODE_MIN, "error": "pick a code of at least %d characters" % MSG_CODE_MIN}, 400
        it = 0
        if per:
            ok, it = self._wrapped_ok(p)
            if not ok:
                return {"ok": False, "error": "bad key material"}, 400
        if not self.set_code(name, new):
            return {"ok": False, "error": "could not change the My room code"}, 500
        if per:
            per.update(wrapped=p["wrapped"], iv=p["iv"], salt=p["salt"], iter=it, at=int(now), keyAt=int(now))
            self._touch(now=True)
        self.log("messages: %s changed %s's My room code%s" % (host, name, " and re-wrapped the messaging key" if per else ""))
        return {"ok": True, "rewrapped": bool(per)}, 200

    def op_keys(self, p, host, now):
        """{names: [...]} -> {keys: {nk: {name, kid, pub, devices, at} | null}} -- who can be messaged (has a key)."""
        names = p.get("names") if isinstance(p.get("names"), list) else []
        out = {}
        for n in names[:300]:
            nk = name_key(n)
            if nk:
                out[nk] = self._pub_row(nk)
        return {"ok": True, "keys": out}, 200

    def op_send(self, p, host, now):
        """{as, to (a name) | gid, cid, iv, ct, wraps: {kid: {iv, w}}, files: [fid]} -> {seq, at}. Every reader's CURRENT key
        must have a wrap (else 409 `stale` names whose keys to fetch again)."""
        nk, err = self._who(p, host)
        if err:
            return err
        if not self._rate_ok(("send", host), MSG_SEND_RATE, now):
            return {"ok": False, "error": "too many messages -- wait a minute", "retryAfter": 30}, 429
        cid = str(p.get("cid") or "")
        if not CID_RE.match(cid):
            return {"ok": False, "error": "a message id (cid) is required"}, 400
        for e in self.msgs.values():   # a resend after a lost answer
            if e.get("cid") == cid and e.get("from") == nk:
                return {"ok": True, "seq": e["seq"], "at": e["at"], "dup": True}, 200
        gid = str(p.get("gid") or "")
        if gid:
            g = self.groups.get(gid)
            if not GID_RE.match(gid) or not g or g.get("deleted"):
                return {"ok": False, "error": "no such group"}, 404
            if nk not in (g.get("members") or []):
                return {"ok": False, "error": "you are not in this group"}, 403
            who = sorted(set(g["members"]))
            to = None
        else:
            to = name_key(p.get("to"))
            if not to:
                return {"ok": False, "error": "to whom?"}, 400
            if to not in self.persons:
                return {"ok": False, "nokey": True, "error": "%s has not set up messages yet" % name_disp(p.get("to"))}, 409
            who = sorted({nk, to})
        iv, ct = str(p.get("iv") or ""), str(p.get("ct") or "")
        if not b64ok(iv, 16, 16) or not b64ok(ct, 24, MSG_CT_MAX):
            return {"ok": False, "error": "bad ciphertext (or too long)"}, 400
        wraps = p.get("wraps") if isinstance(p.get("wraps"), dict) else {}
        clean = {}
        for k, v in list(wraps.items())[:MSG_GROUP_MAX + 2]:
            if KID_RE.match(str(k)) and isinstance(v, dict) and b64ok(v.get("iv"), 16, 16) and b64ok(v.get("w"), 40, 80):
                clean[str(k)] = {"iv": v["iv"], "w": v["w"]}
        stale = [self.persons[x].get("name") or x for x in who if x in self.persons and self.persons[x]["kid"] not in clean]
        if stale:
            return {"ok": False, "stale": stale, "error": "keys changed -- fetch them again"}, 409
        readers = [x for x in who if x in self.persons]
        files = []
        for fid in (p.get("files") if isinstance(p.get("files"), list) else [])[:10]:
            f = self.files.get(str(fid))
            if not FID_RE.match(str(fid)) or not f or f.get("by") != nk:
                return {"ok": False, "error": "an attachment is missing (upload it again)"}, 400
            files.append(str(fid))
        self.seq += 1
        env = {"seq": self.seq, "uid": "m:%s:%s" % (nk, cid), "at": int(now), "cid": cid, "kind": "msg", "from": nk, "fromName": self.persons[nk].get("name") or nk,
               "fromKid": self.persons[nk]["kid"], "iv": iv, "ct": ct, "wraps": clean, "who": readers}
        if gid:
            env["gid"] = gid
        else:
            env["to"] = to
            env["toName"] = self.persons[to].get("name") or to
        if files:
            env["files"] = files
            for fid in files:
                f = self.files[fid]
                f["who"] = sorted(set(f.get("who") or []) | set(readers))
        self.msgs[env["seq"]] = env
        self._store_msg(env)
        self._touch()
        self._ping_person(readers, env["seq"], skip=host)
        return {"ok": True, "seq": env["seq"], "at": env["at"]}, 200

    def op_pull(self, p, host, now):
        """{as: [names], since, ack?} -> {msgs, more, groups, reads, keys, notes, locked, cur}. `ack` = the highest seq this
        device has safely kept (delivered); `since` = what it already has."""
        names = p.get("as") if isinstance(p.get("as"), list) else [p.get("as")]
        mine, locked = [], []
        for n in names[:8]:
            nk = name_key(n)
            if not nk:
                continue
            (mine if self._unlocked(nk, host) else locked).append(nk)
        try:
            since = max(0, int(p.get("since") or 0))
        except (TypeError, ValueError):
            since = 0
        try:
            ack = max(0, int(p.get("ack") or 0))
        except (TypeError, ValueError):
            ack = 0
        if ack and mine:
            c = self.cursors.setdefault(host, {})
            for nk in mine:
                c[nk] = max(int(c.get(nk) or 0), min(ack, self.seq))
            c["at"] = int(now)
            for nk in mine:
                d = (self.persons[nk].setdefault("devices", {})).get(host)
                if d is not None:
                    d["at"] = int(now)
            self._touch()
        mset = set(mine)
        out, size, more = [], 0, False
        kids = set()
        for s in sorted(x for x in self.msgs if x > since):
            e = self.msgs[s]
            if not mset.intersection(e.get("who") or []):
                continue
            if len(out) >= MSG_PULL_MAX or size > MSG_PULL_BYTES:
                more = True
                break
            x = {k: v for k, v in e.items() if k not in ("wraps", "who")}
            if e.get("wraps"):
                mykids = {self.persons[nk]["kid"] for nk in mine} | {o["kid"] for nk in mine for o in self.persons[nk].get("old") or []}
                x["wraps"] = {k: v for k, v in e["wraps"].items() if k in mykids}
                kids.add(e.get("fromKid"))
            out.append(x)
            size += len(e.get("ct") or "") + 300
        keys = {}
        for nk, per in self.persons.items():   # the senders' public keys (current and older) for the key ids handed out
            for row in [per] + list(per.get("old") or []):
                if row.get("kid") in kids:
                    keys[row["kid"]] = {"nk": nk, "pub": row["pub"]}
        groups = [self._group_public(g) for g in self.groups.values() if mset.intersection(g.get("members") or []) or
                  (g.get("deleted") and mset.intersection(g.get("was") or []))]
        notes = {nk: [dict(x) for x in self.notes.get(nk) or []] for nk in mine}
        return {"ok": True, "fleet": self.fleet, "msgs": out, "more": more, "cur": out[-1]["seq"] if out else max(since, 0),
                "top": self.seq, "groups": groups, "reads": {nk: dict(self.reads.get(nk) or {}) for nk in mine}, "keys": keys,
                "notes": notes, "locked": locked}, 200

    def op_read(self, p, host, now):
        """{as, conv ("p:<name key>" | "g:<gid>"), seq} -> the person has read that conversation up to seq (every device of
        theirs shows it read)."""
        nk, err = self._who(p, host)
        if err:
            return err
        conv = str(p.get("conv") or "")
        if not (re.match(r"^p:.{1,48}$", conv) or (conv.startswith("g:") and GID_RE.match(conv[2:]))):
            return {"ok": False, "error": "which conversation?"}, 400
        try:
            seq = min(int(p.get("seq") or 0), self.seq)
        except (TypeError, ValueError):
            return {"ok": False, "error": "seq?"}, 400
        r = self.reads.setdefault(nk, {})
        if seq > int(r.get(conv) or 0):
            r[conv] = seq
            if len(r) > 2000:
                for k in sorted(r, key=lambda k: r[k])[:len(r) - 2000]:
                    r.pop(k, None)
            self._touch()
            self._ping_person([nk], self.seq, skip=host)   # my other devices clear their unread marks
        return {"ok": True}, 200

    def op_ticks(self, p, host, now):
        """{as, names: [...]} -> {ticks: {nk: {d: delivered seq (any of their devices), r: read seq of our conversation}}}."""
        nk, err = self._who(p, host)
        if err:
            return err
        out = {}
        for n in (p.get("names") if isinstance(p.get("names"), list) else [])[:20]:
            o = name_key(n)
            per = self.persons.get(o)
            if not per:
                continue
            d = max([int((self.cursors.get(h) or {}).get(o) or 0) for h in (per.get("devices") or {})] or [0])
            out[o] = {"d": d, "r": int((self.reads.get(o) or {}).get("p:" + nk) or 0)}
        return {"ok": True, "ticks": out}, 200

    # ---- groups ------------------------------------------------------------------------------------------------------
    def _members(self, names, cap):
        out, disp, missing = [], {}, []
        for n in (names if isinstance(names, list) else [])[:cap]:
            k = name_key(n)
            if not k or k in out:
                continue
            if k not in self.persons:
                missing.append(name_disp(n))
                continue
            out.append(k)
            disp[k] = self.persons[k].get("name") or name_disp(n)
        return out, disp, missing

    def op_gcreate(self, p, host, now):
        nk, err = self._who(p, host)
        if err:
            return err
        name = name_disp(p.get("name"))[:40]
        if not name:
            return {"ok": False, "error": "a group name is required"}, 400
        mem, disp, missing = self._members(p.get("members"), MSG_GROUP_MAX)
        if missing:
            return {"ok": False, "nokey": missing, "error": "not set up for messages yet: " + ", ".join(missing)}, 409
        mem = [nk] + [m for m in mem if m != nk]
        disp[nk] = self.persons[nk].get("name") or nk
        if len(mem) < 2 or len(mem) > MSG_GROUP_MAX:
            return {"ok": False, "error": "a group has 2 to %d people" % MSG_GROUP_MAX}, 400
        gid = "g-" + os.urandom(8).hex()
        self.groups[gid] = {"gid": gid, "name": name, "creator": nk, "members": mem, "names": disp, "at": int(now), "ver": 1}
        env = self._sys(gid, "create", nk, now, name=name, names=[disp[m] for m in mem if m != nk])
        self._touch(now=True)
        self._ping_person(mem, env["seq"])
        return {"ok": True, "gid": gid, "group": self._group_public(self.groups[gid])}, 200

    def _group(self, p, nk):
        gid = str(p.get("gid") or "")
        g = self.groups.get(gid) if GID_RE.match(gid) else None
        if not g or g.get("deleted"):
            return None, ({"ok": False, "error": "no such group"}, 404)
        if nk not in (g.get("members") or []):
            return None, ({"ok": False, "error": "you are not in this group"}, 403)
        return g, None

    def op_gadd(self, p, host, now):
        nk, err = self._who(p, host)
        if err:
            return err
        g, err = self._group(p, nk)
        if err:
            return err
        mem, disp, missing = self._members(p.get("members"), MSG_GROUP_MAX)
        if missing:
            return {"ok": False, "nokey": missing, "error": "not set up for messages yet: " + ", ".join(missing)}, 409
        add = [m for m in mem if m not in g["members"]]
        if not add:
            return {"ok": True, "group": self._group_public(g)}, 200
        if len(g["members"]) + len(add) > MSG_GROUP_MAX:
            return {"ok": False, "error": "a group has at most %d people" % MSG_GROUP_MAX}, 400
        g["members"] = g["members"] + add
        g.setdefault("names", {}).update({m: disp[m] for m in add})
        g["ver"] = int(g.get("ver") or 0) + 1
        env = self._sys(g["gid"], "add", nk, now, names=[disp[m] for m in add])
        self._touch(now=True)
        self._ping_person(g["members"], env["seq"])
        return {"ok": True, "group": self._group_public(g)}, 200

    def op_gremove(self, p, host, now):
        """The creator takes someone out (anyone may take themselves out: gleave)."""
        nk, err = self._who(p, host)
        if err:
            return err
        g, err = self._group(p, nk)
        if err:
            return err
        who = name_key(p.get("member"))
        if who == nk:
            return self.op_gleave(p, host, now)
        if g.get("creator") != nk:
            return {"ok": False, "error": "only the group's creator removes people"}, 403
        if who not in g["members"]:
            return {"ok": False, "error": "not in this group"}, 404
        nm = (g.get("names") or {}).get(who) or who
        g["members"] = [m for m in g["members"] if m != who]
        g["ver"] = int(g.get("ver") or 0) + 1
        env = self._sys(g["gid"], "remove", nk, now, names=[nm], extra=[who])
        self._touch(now=True)
        self._ping_person(g["members"] + [who], env["seq"])
        return {"ok": True, "group": self._group_public(g)}, 200

    def op_gleave(self, p, host, now):
        nk, err = self._who(p, host)
        if err:
            return err
        g, err = self._group(p, nk)
        if err:
            return err
        g["members"] = [m for m in g["members"] if m != nk]
        g["ver"] = int(g.get("ver") or 0) + 1
        nm = (g.get("names") or {}).get(nk) or nk
        if not g["members"]:
            g["deleted"] = int(now)
            g["was"] = [nk]
        elif g.get("creator") == nk:
            g["creator"] = g["members"][0]   # the group carries on: the longest-standing member may rename / delete it
        env = self._sys(g["gid"], "leave", nk, now, names=[nm], extra=[nk])
        self._touch(now=True)
        self._ping_person(g["members"] + [nk], env["seq"])
        return {"ok": True}, 200

    def op_grename(self, p, host, now):
        nk, err = self._who(p, host)
        if err:
            return err
        g, err = self._group(p, nk)
        if err:
            return err
        if g.get("creator") != nk:
            return {"ok": False, "error": "only the group's creator renames it"}, 403
        name = name_disp(p.get("name"))[:40]
        if not name:
            return {"ok": False, "error": "a group name is required"}, 400
        g["name"] = name
        g["ver"] = int(g.get("ver") or 0) + 1
        env = self._sys(g["gid"], "rename", nk, now, name=name)
        self._touch(now=True)
        self._ping_person(g["members"], env["seq"])
        return {"ok": True, "group": self._group_public(g)}, 200

    def op_gdelete(self, p, host, now):
        """The creator deletes the group: its messages leave the hub at once (devices keep their own copies)."""
        nk, err = self._who(p, host)
        if err:
            return err
        g, err = self._group(p, nk)
        if err:
            return err
        if g.get("creator") != nk:
            return {"ok": False, "error": "only the group's creator deletes it"}, 403
        gid = g["gid"]
        was = list(g["members"])
        drop = [s for s, e in self.msgs.items() if e.get("gid") == gid]
        for s in drop:
            self.msgs.pop(s, None)
            try:
                os.remove(self._msg_path(s))
            except OSError:
                pass
        g.update(deleted=int(now), was=was, members=[], ver=int(g.get("ver") or 0) + 1)
        self.seq += 1   # members pull: the group comes back deleted
        self._touch(now=True)
        self._ping_person(was, self.seq)
        self.log("messages: group %s deleted by its creator (%d message(s) removed from the hub)" % (gid, len(drop)))
        return {"ok": True}, 200

    # ---- admins: a person's devices --------------------------------------------------------------------------------
    def op_devices(self, p, host, now):
        nk = name_key(p.get("name"))
        per = self.persons.get(nk)
        if not per:
            return {"ok": True, "has": False, "devices": []}, 200
        rows = [{"host": h, "at": int(d.get("at") or 0), "first": int(d.get("first") or 0), "blocked": False} for h, d in (per.get("devices") or {}).items()]
        rows += [{"host": h, "at": int(v or 0), "first": 0, "blocked": True} for h, v in (per.get("blocked") or {}).items()]
        rows.sort(key=lambda r: (r["blocked"], -r["at"]))
        return {"ok": True, "has": True, "name": per.get("name"), "devices": rows}, 200

    def op_devremove(self, p, host, now):
        """An admin takes a device out of a person's messages: it pulls nothing more and cannot unlock again until an admin
        allows it (devallow). The person's other devices get a note."""
        nk = name_key(p.get("name"))
        per = self.persons.get(nk)
        dev = str(p.get("host") or "")
        if not per or not HOST_RE.match(dev):
            return {"ok": False, "error": "no such person or device"}, 404
        per.setdefault("devices", {}).pop(dev, None)
        per.setdefault("blocked", {})[dev] = int(now)
        self.cursors.pop(dev, None)
        self._device_note(nk, dev, now, kind="removed")
        self._touch(now=True)
        self._ping_person([nk], self.seq)
        self.log("messages: an admin removed device %s from %s's messages" % (dev, per.get("name")))
        return {"ok": True}, 200

    def op_devallow(self, p, host, now):
        nk = name_key(p.get("name"))
        per = self.persons.get(nk)
        dev = str(p.get("host") or "")
        if not per or dev not in (per.get("blocked") or {}):
            return {"ok": False, "error": "that device is not blocked"}, 404
        per["blocked"].pop(dev, None)
        per.setdefault("allowed", {})[dev] = int(now)   # a merge knows the allow came after the removal
        self._touch(now=True)
        return {"ok": True}, 200

    # ---- attachments -------------------------------------------------------------------------------------------------
    def file_put(self, data, host, as_name, now=None):
        """The ciphertext of one attachment from a device that unlocked `as_name` -> ({fid, size}, 200)."""
        now = time.time() if now is None else now
        nk = name_key(as_name)
        with self.lock:
            if not self._unlocked(nk, host):
                return {"ok": False, "locked": True, "error": "this device has not unlocked messages"}, 403
            if not self._rate_ok(("file", host), MSG_FILE_RATE, now):
                return {"ok": False, "error": "too many attachments -- wait a few minutes", "retryAfter": 60}, 429
            if not data or len(data) > MSG_FILE_MAX:
                return {"ok": False, "error": "an attachment is at most 25 MB"}, 413
            if sum(int(f.get("size") or 0) for f in self.files.values()) + len(data) > MSG_FILES_TOTAL:
                return {"ok": False, "error": "the hub's message attachments are full -- try again later"}, 507
            fid = "f-" + os.urandom(16).hex()
        os.makedirs(os.path.join(self.dir, "f"), exist_ok=True)
        tmp = self._file_path(fid) + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, self._file_path(fid))
        with self.lock:
            self.files[fid] = {"at": int(now), "size": len(data), "by": nk, "who": None}
            self._touch()
        return {"ok": True, "fid": fid, "size": len(data)}, 200

    def file_get(self, fid, host):
        """-> (bytes, None) for a device of someone who may read it (a reader of a message that carries it, or its uploader),
        else (None, (reply, code))."""
        with self.lock:
            f = self.files.get(str(fid)) if FID_RE.match(str(fid or "")) else None
            if not f:
                return None, ({"ok": False, "error": "no such attachment (older than 90 days?)"}, 404)
            may = set(f.get("who") or []) | {f.get("by")}
            if not any(self._unlocked(nk, host) for nk in may if nk):
                return None, ({"ok": False, "error": "not yours to read"}, 403)
        try:
            with open(self._file_path(fid), "rb") as fh:
                return fh.read(), None
        except OSError:
            return None, ({"ok": False, "error": "attachment missing on the hub"}, 404)

    # ---- 0.21.88 (Kenton: "Yes, carry them"): hub hand-over, the standby's copy, the hand-back ------------------------
    # export() pages the store (meta + messages after a seq); merge() takes a page into this store -- idempotent (a message
    # is known by its uid, whatever its number there), never an older person key over a newer one, deletions kept (a deleted
    # group's messages never come back), the 90-day / 1-hour retention applied. Attachments travel apart: missing_files()
    # names the ones whose ciphertext this box lacks, file_raw() / file_store() move the bytes (catch_up() below).
    SYNC_MSGS = 2000
    SYNC_BYTES = 8 * 1024 * 1024

    @staticmethod
    def uid_of(e):
        if e.get("uid"):
            return str(e["uid"])[:120]
        if e.get("kind") == "msg" and e.get("cid"):
            return "m:%s:%s" % (e.get("from"), e.get("cid"))
        return "s:%s:%s:%s" % (e.get("seq"), e.get("at"), e.get("gid") or "")

    def export(self, since=0, meta_ver=None):
        """-> a page: {v, fleet, seq, metaVer, meta? (when meta_ver differs), msgs (seq > since, capped), more, top}."""
        try:
            since = max(0, int(since or 0))
        except (TypeError, ValueError):
            since = 0
        with self.lock:
            mv = "%s.%d" % (self.boot, self.ver)
            out = {"v": 1, "fleet": self.fleet, "seq": self.seq, "metaVer": mv}
            if meta_ver != mv:
                out["meta"] = json.loads(json.dumps({"persons": self.persons, "groups": self.groups, "reads": self.reads,
                                                     "cursors": self.cursors, "notes": self.notes, "files": self.files}))
            msgs, size, more = [], 0, False
            for q in sorted(x for x in self.msgs if x > since):
                if len(msgs) >= self.SYNC_MSGS or size > self.SYNC_BYTES:
                    more = True
                    break
                e = dict(self.msgs[q])
                e["uid"] = self.uid_of(e)
                msgs.append(e)
                size += len(e.get("ct") or "") + 400
            out.update(msgs=msgs, more=more, top=msgs[-1]["seq"] if msgs else since)
        return out

    @staticmethod
    def _key_at(p):
        try:
            return int(p.get("keyAt") or p.get("created") or p.get("at") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _ts_map(v, keyok=HOST_RE.match):
        out = {}
        for k, t in (v.items() if isinstance(v, dict) else []):
            try:
                if keyok(str(k)):
                    out[str(k)] = int(t)
            except (TypeError, ValueError):
                pass
        return out

    def _person_clean(self, p):
        if not isinstance(p, dict) or not KID_RE.match(str(p.get("kid") or "")) or not pub_ok(p.get("pub")):
            return None
        if not (b64ok(p.get("wrapped"), 64, 1024) and b64ok(p.get("iv"), 16, 16) and b64ok(p.get("salt"), 24, 44)):
            return None
        devs = {}
        for h, d in (p.get("devices") or {}).items() if isinstance(p.get("devices"), dict) else []:
            if HOST_RE.match(str(h)) and isinstance(d, dict):
                devs[str(h)] = {"at": int(d.get("at") or 0), "first": int(d.get("first") or d.get("at") or 0)}
        old = [{"kid": str(o["kid"]), "pub": str(o["pub"]), "until": int(o.get("until") or 0)} for o in (p.get("old") or [])
               if isinstance(o, dict) and KID_RE.match(str(o.get("kid") or "")) and pub_ok(o.get("pub"))][-8:]
        try:
            it = int(p.get("iter") or 0)
        except (TypeError, ValueError):
            it = 0
        return {"name": name_disp(p.get("name")), "kid": str(p["kid"]), "pub": str(p["pub"]), "wrapped": str(p["wrapped"]),
                "iv": str(p["iv"]), "salt": str(p["salt"]), "iter": it, "at": int(p.get("at") or 0), "created": int(p.get("created") or 0),
                "keyAt": self._key_at(p), "by": str(p.get("by") or "")[:40], "devices": devs, "blocked": self._ts_map(p.get("blocked")),
                "allowed": self._ts_map(p.get("allowed")), "old": old, "sub": p.get("sub") if isinstance(p.get("sub"), str) else None}

    def merge(self, b, now=None):
        """Take one export() page into this store. -> counts."""
        now = time.time() if now is None else now
        cut = now - MSG_KEEP_S
        n = {"persons": 0, "groups": 0, "msgs": 0, "renumbered": 0, "files": 0}
        if not isinstance(b, dict):
            return n
        with self.lock:
            if not self.persons and not self.msgs and re.match(r"^[0-9a-f]{16}$", str(b.get("fleet") or "")):
                self.fleet = str(b["fleet"])   # an empty store takes the fleet's id (the pages keep their history and cursors)
            meta = b.get("meta") if isinstance(b.get("meta"), dict) else {}
            for nk, p in (meta.get("persons") or {}).items() if isinstance(meta.get("persons"), dict) else []:
                nk = name_key(nk)
                inc = self._person_clean(p)
                if not nk or inc is None:
                    continue
                mine = self.persons.get(nk)
                if mine is None:
                    self.persons[nk] = inc
                    n["persons"] += 1
                    continue
                before = json.dumps(mine, sort_keys=True)
                if self._key_at(inc) > self._key_at(mine):   # a newer key (set up again / a new code) wins; never an older one
                    if inc["kid"] != mine.get("kid"):
                        inc["old"] = inc["old"] + [{"kid": mine["kid"], "pub": mine["pub"], "until": self._key_at(inc)}]
                    for k in ("name", "kid", "pub", "wrapped", "iv", "salt", "iter", "keyAt", "created", "by", "sub"):
                        mine[k] = inc[k]
                olds = {o["kid"]: o for o in list(mine.get("old") or []) + inc["old"] if o["kid"] != mine["kid"]}
                mine["old"] = sorted(olds.values(), key=lambda o: o.get("until") or 0)[-8:]
                devs = mine.setdefault("devices", {})
                for h, d in inc["devices"].items():
                    o = devs.get(h)
                    devs[h] = {"at": max(d["at"], int((o or {}).get("at") or 0)), "first": min(d["first"], int((o or {}).get("first") or d["first"]))}
                for k in ("blocked", "allowed"):
                    cur = self._ts_map(mine.get(k))
                    for h, t in inc[k].items():
                        cur[h] = max(t, cur.get(h, 0))
                    mine[k] = cur
                for h in [h for h, t in mine["blocked"].items() if mine["allowed"].get(h, 0) >= t]:
                    mine["blocked"].pop(h, None)
                for h in mine["blocked"]:
                    devs.pop(h, None)
                mine["at"] = max(int(mine.get("at") or 0), inc["at"])
                if json.dumps(mine, sort_keys=True) != before:
                    n["persons"] += 1
            for gid, g in (meta.get("groups") or {}).items() if isinstance(meta.get("groups"), dict) else []:
                if not GID_RE.match(str(gid)) or not isinstance(g, dict):
                    continue
                mine = self.groups.get(gid)
                if mine is None or int(g.get("ver") or 0) > int(mine.get("ver") or 0):
                    self.groups[gid] = {"gid": gid, "name": name_disp(g.get("name"))[:40], "creator": name_key(g.get("creator")),
                                        "members": [name_key(m) for m in (g.get("members") or []) if name_key(m)][:MSG_GROUP_MAX],
                                        "names": {name_key(k): name_disp(v) for k, v in (g.get("names") or {}).items() if name_key(k)} if isinstance(g.get("names"), dict) else {},
                                        "at": int(g.get("at") or 0), "ver": int(g.get("ver") or 0)}
                    if g.get("deleted"):
                        self.groups[gid].update(deleted=int(g["deleted"]), was=[name_key(m) for m in (g.get("was") or []) if name_key(m)])
                    n["groups"] += 1
            dead = {gid for gid, g in self.groups.items() if g.get("deleted")}
            for q in [q for q, e in self.msgs.items() if e.get("gid") in dead]:   # a group deleted there: its messages go here too
                self.msgs.pop(q, None)
                try:
                    os.remove(self._msg_path(q))
                except OSError:
                    pass
            for nk, r in (meta.get("reads") or {}).items() if isinstance(meta.get("reads"), dict) else []:
                if not isinstance(r, dict):
                    continue
                mine = self.reads.setdefault(name_key(nk), {})
                for conv, q in r.items():
                    try:
                        mine[str(conv)[:60]] = max(int(q), int(mine.get(str(conv)[:60]) or 0))
                    except (TypeError, ValueError):
                        pass
            for h, c in (meta.get("cursors") or {}).items() if isinstance(meta.get("cursors"), dict) else []:
                if not HOST_RE.match(str(h)) or not isinstance(c, dict):
                    continue
                mine = self.cursors.setdefault(str(h), {})
                for k, q in c.items():
                    try:
                        mine[str(k)[:60]] = max(int(q), int(mine.get(str(k)[:60]) or 0))
                    except (TypeError, ValueError):
                        pass
            for nk, lst in (meta.get("notes") or {}).items() if isinstance(meta.get("notes"), dict) else []:
                have = {x.get("id") for x in self.notes.get(name_key(nk)) or []}
                add = [dict(x) for x in (lst if isinstance(lst, list) else []) if isinstance(x, dict) and x.get("id") and x.get("id") not in have]
                if add:
                    self.notes[name_key(nk)] = sorted((self.notes.get(name_key(nk)) or []) + add, key=lambda x: int(x.get("at") or 0))[-20:]
            for fid, f in (meta.get("files") or {}).items() if isinstance(meta.get("files"), dict) else []:
                if not FID_RE.match(str(fid)) or not isinstance(f, dict) or float(f.get("at") or 0) < cut:
                    continue
                mine = self.files.get(fid)
                who = f.get("who") if isinstance(f.get("who"), list) else None
                if mine is None:
                    self.files[fid] = {"at": int(f.get("at") or 0), "size": int(f.get("size") or 0), "by": name_key(f.get("by")),
                                       "who": [name_key(x) for x in who if name_key(x)] if who is not None else None}
                    n["files"] += 1
                elif who is not None:
                    mine["who"] = sorted(set(mine.get("who") or []) | {name_key(x) for x in who if name_key(x)})
            have = {self.uid_of(e): q for q, e in self.msgs.items()}
            for e in b.get("msgs") or []:
                if not isinstance(e, dict) or not isinstance(e.get("seq"), int) or float(e.get("at") or 0) < cut:
                    continue
                if e.get("gid") in dead:
                    continue
                uid = self.uid_of(e)
                if uid in have:
                    continue
                q = e["seq"]
                if q <= 0 or q in self.msgs:   # that number is taken here by another message: the next free one
                    q = max(self.seq, max(self.msgs or [0])) + 1
                    n["renumbered"] += 1
                env = dict(e, seq=q, uid=uid)
                self.msgs[q] = env
                have[uid] = q
                self.seq = max(self.seq, q)
                self._store_msg(env)
                n["msgs"] += 1
            seq0 = self.seq
            try:
                self.seq = max(self.seq, int(b.get("seq") or 0))   # new messages here never take a number the source used
            except (TypeError, ValueError):
                pass
            if meta or n["msgs"] or self.seq != seq0:
                self._touch(now=True)
        if n["msgs"] or n["files"]:
            self.sweep(now)
        return n

    def missing_files(self):
        with self.lock:
            return [fid for fid, f in sorted(self.files.items(), key=lambda kv: -int(kv[1].get("at") or 0))
                    if not os.path.isfile(self._file_path(fid))]

    def file_raw(self, fid):
        with self.lock:
            if not FID_RE.match(str(fid or "")) or fid not in self.files:
                return None
        try:
            with open(self._file_path(fid), "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def file_store(self, fid, data):
        """The ciphertext of an attachment this store knows (from a merge) -> kept when its size matches."""
        with self.lock:
            f = self.files.get(str(fid)) if FID_RE.match(str(fid or "")) else None
            if not f or not isinstance(data, (bytes, bytearray)) or (f.get("size") and len(data) != int(f["size"])):
                return False
        os.makedirs(os.path.join(self.dir, "f"), exist_ok=True)
        tmp = self._file_path(fid) + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, self._file_path(fid))
        return True

    # ---- the People panel ----------------------------------------------------------------------------------------------
    def identities(self):
        """{nk: {name, at, devices}} -- who has a messaging identity (All people lists them even when not seen lately)."""
        with self.lock:
            return {nk: {"name": p.get("name") or nk, "at": int(max([int(d.get("at") or 0) for d in (p.get("devices") or {}).values()] or [p.get("at") or 0])),
                         "devices": len(p.get("devices") or {})} for nk, p in self.persons.items()}


def fetch_files(m, fetch, log=None, deadline=3600.0, sleep=time.sleep, quiet=False):
    """0.21.88: the attachments `m` knows (from a merge) but lacks -> fetched one by one (`fetch(fid)` -> ciphertext or None),
    three tries each, for `deadline` s at most. -> (bytes copied, still missing)."""
    log = log or (lambda x: None)
    t0, got = time.time(), 0
    for fid in m.missing_files():
        if time.time() - t0 >= deadline:
            break
        for attempt in range(3):
            try:
                data = fetch(fid)
            except Exception:
                data = None
            if data is not None and m.file_store(fid, data):
                got += len(data)
                break
            sleep(1.0 + attempt)
    left = len(m.missing_files())
    if (got or left) and not quiet:
        log("messages: %d attachment byte(s) copied%s" % (got, (" -- %d attachment(s) still missing" % left) if left else ""))
    return got, left


def catch_up(m, export, fetch, log=None, deadline=1800.0, since=0, meta_ver=None, sleep=time.sleep, files=True, retries=60):
    """0.21.88: copy a store into `m` page by page (then, with `files`, the attachments it lacks). `export(since, meta_ver)` ->
    a page (None: the other side did not answer -- tried `retries` times), `fetch(fid)` -> its ciphertext (or None).
    -> (since, meta_ver, counts) for the next round (a standby keeps asking from there)."""
    log = log or (lambda x: None)
    t0 = time.time()
    tot = {"persons": 0, "groups": 0, "msgs": 0, "renumbered": 0, "files": 0, "bytes": 0, "pages": 0}
    tries = 0
    while time.time() - t0 < deadline:
        try:
            page = export(since, meta_ver)
        except Exception:
            page = None
        if not isinstance(page, dict):
            tries += 1
            if tries >= retries:
                break
            sleep(min(30.0, 2.0 * tries))
            continue
        tries = 0
        c = m.merge(page)
        for k in ("persons", "groups", "msgs", "renumbered", "files"):
            tot[k] += c.get(k, 0)
        tot["pages"] += 1
        meta_ver = page.get("metaVer") or meta_ver
        try:
            since = max(since, int(page.get("top") or 0))
        except (TypeError, ValueError):
            pass
        if not page.get("more"):
            break
    if files and fetch is not None:
        tot["bytes"], tot["missing"] = fetch_files(m, fetch, log, max(1.0, deadline - (time.time() - t0)), sleep, quiet=True)
    if tot["msgs"] or tot["persons"] or tot["groups"] or tot["bytes"]:
        log("messages: copied %d message(s), %d person key(s), %d group(s), %d attachment byte(s) in %d page(s)%s"
            % (tot["msgs"], tot["persons"], tot["groups"], tot["bytes"], tot["pages"],
               (" -- %d attachment(s) still missing" % tot["missing"]) if tot.get("missing") else ""))
    return since, meta_ver, tot
