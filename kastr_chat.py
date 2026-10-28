#!/usr/bin/env python3
"""Room chat, kept on the relay host's disk (0.12.0).

One append-only JSON-lines file per room under state_dir/chat/<room>.jsonl:

    {"id", "ts", "op", "name", "text", "files": [{id, name, size, type}], "via", "token"}
    {"del": <id>}                       a tombstone -- the message is hidden from read()

`id` is an int that only grows within a room (now_ms * 1000 + a counter, seeded
from the file so a restart never re-issues one), so a page polls with
`since=<last id>` and misses nothing. `token` is the poster's delete secret: it
is stored so the poster can take a message back, handed out ONCE (in the reply
to the append) and never listed. `via` names the relay the poster came through
(the spoke's name on a federated hub) -- the "via" the pages already show.

A room's file is deleted after a day without a read or a write, unless the room
is kept: either the relay's AuthStore says `persistent`, or a `.keep` marker sits
beside the file (the hub drops one when a spoke forwards for a room the SPOKE
keeps). Closing a room removes the file, the marker and the room's chat
attachments in the shared-files dir (meta kind "chat").

Everything runs under one lock; files are opened with newline="" so a Windows
build and a Linux build write identical bytes; a torn last line (power cut mid
write) is skipped, and the next append starts on a fresh line.

0.21.93 timers (Kenton 2026-10-27/28) -- disappearing messages, send later, view once:

    a record may carry "exp" (hub epoch s; "ttl" = its length) and "vo": 1 (+ "pw", the poster's device digest)
    {"id", ..., "sys": "ttl", "s": <s>}   the room's default length changed (anyone in the room; everyone sees the line)
    {"vop": <id>, "w": <device digest>, "at"}   a view-once message was opened on that device (once each)
    {"sch": <sid>, "rel", "at", "tk", "rec": {...}}   send later: held here, released at `rel` on THIS host's clock
    {"srel": <sid>, "rel", "at"}          its time changed (the newest `at` wins)
    {"sdone": <sid>, "id": <released id | 0>}   released (or cancelled)

A room has no read receipts, so a room's timer starts when the message is SENT. Deleting is real: a tombstone
is appended (it replicates to the standby like any line) and the dead line is overwritten IN PLACE with a
tombstone of the same length (scrub_file) -- the file's size never changes, so the standby's byte offsets stay
true, and the standby scrubs its copy the same way when the tombstone reaches it. The message's attachments
go too. Pages older than 0.21.93 (no `tv` on their read) get a line instead of a timed or view-once message.
"""
import json
import os
import re
import threading
import time
import uuid

SLUG_RE = re.compile(r"^[a-z0-9-]{1,32}$")
FID_RE = re.compile(r"^[0-9a-f]{32}$")
TEXT_MAX = 4000
FILES_MAX = 10
NAME_MAX = 64
FILE_NAME_MAX = 200
TYPE_MAX = 80
READ_LIMIT = 200
MAX_IDLE = 86400
# 0.21.93 timers (the same lengths as Messages, kastr_msg.py)
TIMER_MIN_S = 60                    # a timer is 1 minute ...
TIMER_MAX_S = 90 * 86400            # ... to 90 days
TIMER_CAP_S = 7 * 86400             # a view-once message is gone within 7 days (a room has no list of who must open it)
VO_OPEN_S = 300                     # its pictures may be fetched this long after this device opened it
SCHED_MIN_S = 20                    # send later: at least this far ahead (on this host's clock) ...
SCHED_MAX_S = 90 * 86400            # ... at most 90 days
SID_RE = re.compile(r"^[0-9a-f]{16}$")
OLD_STUB = {"vo": "a view-once message -- update KASTR to see it",
            "ttl": "a disappearing message -- update KASTR to see it"}


def ttl_ok(v):
    """0.21.93: a timer length in seconds -> it (0 = off), or None when it is not one."""
    try:
        v = int(v or 0)
    except (TypeError, ValueError):
        return None
    return v if v == 0 or TIMER_MIN_S <= v <= TIMER_MAX_S else None


def ttl_words(s):
    s = int(s or 0)
    for n, w in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if s >= n and s % n == 0:
            return "%d %s%s" % (s // n, w, "" if s // n == 1 else "s")
    return "%d minutes" % max(1, round(s / 60))


def _scrubbed(obj, n):
    """A tombstone line of exactly n bytes (spaces pad it; JSON ignores them)."""
    b = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    if len(b) > n:
        b = b"{}" if n >= 2 else b""
    return b + b" " * (n - len(b))


def scrub_file(path):
    """0.21.93: overwrite, in place and at the same length, every line a tombstone in this file kills -- a deleted or
    expired message (`del`), a scheduled one that went or was cancelled (`sdone`) -- and any broken line that is not the
    last. The file's size never changes (the standby copies it by byte offset). Called on the hub under the store's lock,
    on the standby by its copier. -> lines scrubbed."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return 0
    lines, pos = [], 0
    while True:
        j = raw.find(b"\n", pos)
        if j < 0:
            break   # a torn tail stays as it is (the next append starts a fresh line)
        lines.append((pos, raw[pos:j]))
        pos = j + 1
    objs, dead, done = [], set(), set()
    for _off, b in lines:
        d = None
        if b.strip():
            try:
                d = json.loads(b.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                d = False
            if d is not False and not isinstance(d, dict):
                d = False
        objs.append(d)
        if d:
            try:
                if "del" in d:
                    dead.add(int(d["del"]))
                elif "sdone" in d:
                    done.add(str(d["sdone"]))
            except (TypeError, ValueError):
                pass
    patches = []
    for (off, b), d in zip(lines, objs):
        if d is None or (d and ("del" in d or "sdone" in d or "srel" in d or "vop" in d)):
            continue
        if d is False:
            if b.strip() != b"{}":
                patches.append((off, _scrubbed({}, len(b))))
            continue
        if "sch" in d:
            if str(d["sch"]) in done:
                patches.append((off, _scrubbed({"sdone": str(d["sch"]), "z": 1}, len(b))))
            continue
        try:
            mid = int(d.get("id"))
        except (TypeError, ValueError):
            continue   # a kind this build does not know: left alone
        if mid in dead:
            patches.append((off, _scrubbed({"del": mid, "z": 1}, len(b))))
    if patches:
        try:
            with open(path, "r+b") as f:
                for off, data in patches:
                    f.seek(off)
                    f.write(data)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
        except OSError:
            return 0
    return len(patches)


def check_room(room):
    """The slug the HTTP route already matched, checked again here: the store is
    also called from the relay's close hook and from the sweeper."""
    if not isinstance(room, str) or not SLUG_RE.match(room):
        raise ValueError("bad room slug")
    return room


def _clean_files(files):
    out = []
    for f in (files or [])[:FILES_MAX + 1]:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "")
        if not FID_RE.match(fid):
            continue
        try:
            size = int(f.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        out.append({"id": fid,
                    "name": str(f.get("name") or "file")[:FILE_NAME_MAX],
                    "size": max(0, size),
                    "type": str(f.get("type") or "")[:TYPE_MAX]})
    if len(out) > FILES_MAX:
        raise ValueError("at most %d files per message" % FILES_MAX)
    return out


class ChatStore:
    def __init__(self, state_dir, log=None, files_dir=None, attachments_for=None):
        self.state_dir = state_dir
        self.dir = os.path.join(state_dir, "chat")
        # Where chat attachments live (kastr_serve's shared dir) -- delete_room
        # removes the ones whose meta says kind "chat" for that room. A caller
        # may instead hand in attachments_for(room) -> [file paths] to remove.
        self.files_dir = files_dir
        self.attachments_for = attachments_for
        self.log = log or (lambda m: None)
        self.lock = threading.RLock()
        self._last_id = {}          # room -> the last id issued or seen
        self._due = None            # 0.21.93: room -> when its next timer runs out (None: look at every room on the next tick)
        self._vo_tix = {}           # 0.21.93: a view-once opening's ticket -> (room, its file ids, until)

    # ---- paths ------------------------------------------------------------

    def _path(self, room):
        return os.path.join(self.dir, room + ".jsonl")

    def _keep_path(self, room):
        return os.path.join(self.dir, room + ".keep")

    # ---- file access (call with the lock held) ------------------------------

    def _lines(self, room):
        """-> (records by id, set of tombstoned ids). Broken lines are skipped;
        the last line is the one a crash tears, so no record is trusted until
        it parses."""
        P = self._parse(room)
        return P["recs"], P["dead"]

    def _parse(self, room):
        """0.21.93: every kind of line -> {recs, dead, sch: sid -> line, sdone: sid -> released id (0 = cancelled),
        srel: sid -> (at, rel), vop: id -> {device digest: at}}."""
        P = {"recs": {}, "dead": set(), "sch": {}, "sdone": {}, "srel": {}, "vop": {}}
        try:
            with open(self._path(room), "r", encoding="utf-8", newline="") as f:
                raw = f.read()
        except OSError:
            return P
        for line in raw.split("\n"):
            line = line.strip("\r").strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            try:
                if "del" in d:
                    P["dead"].add(int(d["del"]))
                elif "sch" in d:
                    if SID_RE.match(str(d["sch"])) and isinstance(d.get("rec"), dict):
                        P["sch"][str(d["sch"])] = d
                elif "sdone" in d:
                    sid = str(d["sdone"])
                    P["sdone"][sid] = max(P["sdone"].get(sid, 0), int(d.get("id") or 0))   # a scrubbed `sch` says 0
                elif "srel" in d:
                    sid, at = str(d["srel"]), float(d.get("at") or 0)
                    if sid not in P["srel"] or at >= P["srel"][sid][0]:
                        P["srel"][sid] = (at, int(d.get("rel") or 0))
                elif "vop" in d:
                    P["vop"].setdefault(int(d["vop"]), {})[str(d.get("w") or "")] = float(d.get("at") or 0)
                else:
                    P["recs"][int(d.get("id"))] = d
            except (TypeError, ValueError):
                continue
        return P

    # ---- 0.21.93 timers (call with the lock held) -----------------------------

    @staticmethod
    def _rel_of(P, sid):
        s = P["sch"].get(sid) or {}
        return int(P["srel"][sid][1]) if sid in P["srel"] else int(s.get("rel") or 0)

    def _due_calc(self, P):
        ts = [int(r.get("exp") or 0) for mid, r in P["recs"].items() if r.get("exp") and mid not in P["dead"]]
        ts += [self._rel_of(P, sid) for sid in P["sch"] if sid not in P["sdone"]]
        ts = [t for t in ts if t > 0]
        return min(ts) if ts else None

    def _due_note(self, room, t):
        if self._due is not None and t:
            if room not in self._due or t < self._due[room]:
                self._due[room] = t

    def _files_meta(self, room, files, **set_):
        """The room's attachments among `files` -> [(file path, meta path, meta)]; with set_, those meta fields are written."""
        d, out = self.files_dir, []
        if not d:
            return out
        for f in files or []:
            fid = str((f or {}).get("id") or "")
            if not FID_RE.match(fid):
                continue
            mp = os.path.join(d, fid + ".json")
            try:
                with open(mp, encoding="utf-8") as fh:
                    m = json.load(fh)
            except (OSError, ValueError):
                continue
            if m.get("kind") != "chat" or m.get("room") != room:
                continue
            if set_:
                m.update(set_)
                try:
                    with open(mp, "w", encoding="utf-8", newline="") as fh:
                        json.dump(m, fh)
                except OSError:
                    pass
            out.append((os.path.join(d, fid), mp, m))
        return out

    def _drop_files(self, room, files):
        n = 0
        for fp, mp, _m in self._files_meta(room, files):
            for p in (fp, mp):
                try:
                    os.remove(p)
                    n += 1
                except OSError:
                    pass
        return n

    def _kill(self, room, rec, why):
        """A message is gone for real: its tombstone, its line overwritten, its attachments removed."""
        self._append_line(room, {"del": int(rec["id"]), "x": why} if why else {"del": int(rec["id"])})
        self._drop_files(room, rec.get("files"))
        scrub_file(self._path(room))

    def _append_line(self, room, obj):
        os.makedirs(self.dir, exist_ok=True)
        p = self._path(room)
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        with open(p, "a+b") as f:        # a+: readable, every write lands at the end
            # A torn last line (no newline) must not swallow this one.
            try:
                f.seek(0, os.SEEK_END)
                if f.tell() > 0:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        f.write(b"\n")
            except OSError:
                pass
            f.write((line + "\n").encode("utf-8"))
            f.flush()

    def _next_id(self, room):
        if room not in self._last_id:
            recs, dead = self._lines(room)
            self._last_id[room] = max(list(recs) + list(dead) + [0])
        nid = int(time.time() * 1000) * 1000
        last = self._last_id[room]
        if nid <= last:
            nid = last + 1
        self._last_id[room] = nid
        return nid

    # ---- API ------------------------------------------------------------------

    @staticmethod
    def _body(text, files):
        text = "" if text is None else str(text)
        if len(text) > TEXT_MAX:
            raise ValueError("message longer than %d characters" % TEXT_MAX)
        files = _clean_files(files)
        if not text.strip() and not files:
            raise ValueError("empty message")
        return text, files

    @staticmethod
    def _timer(ttl, vo):
        """0.21.93 -> (ttl, vo) checked."""
        t = ttl_ok(ttl)
        if t is None:
            raise ValueError("a timer is 1 minute to 90 days")
        return t, (1 if vo else 0)

    def append(self, room, op, name, text, files=None, via="", ttl=0, vo=0, dev="", now=None):
        """-> the stored record INCLUDING its delete token (the poster's copy). 0.21.93: `ttl` (s) makes it disappear
        that long after now; `vo` makes it view once (each device opens it once; gone at its timer or within 7 days);
        `dev` = the poster's device (it does not open its own)."""
        room = check_room(room)
        text, files = self._body(text, files)
        ttl, vo = self._timer(ttl, vo)
        now = time.time() if now is None else now
        rec = {
            "id": 0,
            "ts": int(now * 1000),
            "op": str(op or "")[:NAME_MAX],
            "name": str(name or "")[:NAME_MAX],
            "text": text,
            "files": files,
            "via": str(via or "")[:NAME_MAX],
            "token": uuid.uuid4().hex,
        }
        import kastr_secret
        pw = kastr_secret.digest(str(dev)[:64]) if vo and dev else ""
        if ttl:
            rec.update(ttl=ttl, exp=int(now) + ttl)
        if vo:
            rec.update(vo=1, exp=int(now) + min(ttl or TIMER_CAP_S, TIMER_CAP_S))
        with self.lock:
            rec["id"] = self._next_id(room)
            self._append_line(room, dict(rec, token=kastr_secret.digest(rec["token"]), **({"pw": pw} if pw else {})))   # 0.21.92: only its digest is kept
            if ttl or vo:
                self._files_meta(room, files, t=1, **({"vo": 1} if vo else {}))   # 0.21.93: never cached; view once by ticket only
                self._due_note(room, rec["exp"])
        return dict(rec)

    # ---- 0.21.93 the room's default timer, view once, send later, the timer beat ----

    def room_ttl(self, room):
        """The room's default timer (s, 0 = off): the newest live `sys: ttl` line."""
        room = check_room(room)
        with self.lock:
            P = self._parse(room)
        for mid in sorted(P["recs"], reverse=True):
            r = P["recs"][mid]
            if r.get("sys") == "ttl" and mid not in P["dead"]:
                return int(r.get("s") or 0)
        return 0

    def set_ttl(self, room, s, op, name, via="", now=None):
        """Anyone in the room changes its default; everyone sees the line (a page older than 0.21.93 reads its text)."""
        room = check_room(room)
        s = ttl_ok(s)
        if s is None:
            raise ValueError("a timer is 1 minute to 90 days")
        now = time.time() if now is None else now
        who = str(name or op or "someone")[:NAME_MAX]
        text = ("%s set disappearing messages to %s: new messages here disappear %s after they are sent "
                "(update KASTR to see them)" % (who, ttl_words(s), ttl_words(s))) if s else "%s turned off disappearing messages" % who
        rec = {"id": 0, "ts": int(now * 1000), "op": str(op or "")[:NAME_MAX], "name": str(name or "")[:NAME_MAX],
               "text": text, "files": [], "via": str(via or "")[:NAME_MAX], "sys": "ttl", "s": s, "token": uuid.uuid4().hex}
        import kastr_secret
        with self.lock:
            rec["id"] = self._next_id(room)
            self._append_line(room, dict(rec, token=kastr_secret.digest(rec["token"])))
        return dict(rec)

    def open_vo(self, room, msg_id, dev, now=None):
        """A view-once message, opened on one device: its text + files and a ticket for its pictures (VO_OPEN_S), once
        per device -> (status, reply). 410 = already opened here, 403 = the poster's own, 404 = gone."""
        room = check_room(room)
        now = time.time() if now is None else now
        dev = str(dev or "")[:64]
        if len(dev) < 8:
            return 400, {"error": "no device"}
        try:
            msg_id = int(msg_id)
        except (TypeError, ValueError):
            return 400, {"error": "bad message"}
        import kastr_secret
        w = kastr_secret.digest(dev)
        with self.lock:
            P = self._parse(room)
            r = P["recs"].get(msg_id)
            if not r or msg_id in P["dead"] or not r.get("vo") or int(r.get("exp") or 0) <= now:
                return 404, {"error": "it is gone", "gone": True}
            if r.get("pw") and r["pw"] == w:
                return 403, {"error": "your own view-once message"}
            seen = P["vop"].get(msg_id) or {}
            if w in seen:
                return 410, {"error": "already opened", "opened": int(seen[w])}
            self._append_line(room, {"vop": msg_id, "w": w, "at": int(now)})
            for t in [t for t, v in self._vo_tix.items() if v[2] <= now]:
                self._vo_tix.pop(t, None)
            ft = uuid.uuid4().hex
            self._vo_tix[ft] = (room, {f["id"] for f in r.get("files") or []}, now + VO_OPEN_S)
        return 200, {"ok": True, "id": msg_id, "text": r.get("text") or "", "files": r.get("files") or [], "ft": ft,
                     "window": VO_OPEN_S, "opened": int(now), "name": r.get("name") or "", "ts": r.get("ts")}

    def vo_file_ok(self, room, fid, ft, now=None):
        now = time.time() if now is None else now
        with self.lock:
            v = self._vo_tix.get(str(ft or ""))
        return bool(v and v[0] == room and fid in v[1] and v[2] > now)

    def schedule(self, room, rel, op, name, text, files=None, via="", ttl=0, vo=0, dev="", now=None):
        """Send later: held here and released at `rel` (this host's epoch s) even with the poster's computer off.
        -> {sched, sid, tk (to change / cancel it), dtk (its delete token once it went), rel, now}."""
        room = check_room(room)
        text, files = self._body(text, files)
        ttl, vo = self._timer(ttl, vo)
        now = time.time() if now is None else now
        try:
            rel = int(rel)
        except (TypeError, ValueError):
            raise ValueError("bad time")
        if not now + SCHED_MIN_S <= rel <= now + SCHED_MAX_S:
            raise ValueError("pick a time from a minute to 90 days ahead")
        import kastr_secret
        sid, tk, dtk = uuid.uuid4().hex[:16], uuid.uuid4().hex, uuid.uuid4().hex
        rec = {"op": str(op or "")[:NAME_MAX], "name": str(name or "")[:NAME_MAX], "text": text, "files": files,
               "via": str(via or "")[:NAME_MAX], "ttl": ttl, "vo": vo, "token": kastr_secret.digest(dtk)}
        if vo and dev:
            rec["pw"] = kastr_secret.digest(str(dev)[:64])
        with self.lock:
            self._append_line(room, {"sch": sid, "rel": rel, "at": int(now), "tk": kastr_secret.digest(tk), "rec": rec})
            self._files_meta(room, files, t=1, **({"vo": 1} if vo else {}))   # nobody fetches them before it goes
            self._due_note(room, rel)
            self.touch(room)
        return {"ok": True, "sched": 1, "sid": sid, "tk": tk, "dtk": dtk, "rel": rel, "now": int(now)}

    def sched_op(self, room, sid, tk, do, rel=None, now=None):
        """The poster's scheduled message: do = get | time | now | cancel -> (status, reply)."""
        room = check_room(room)
        now = time.time() if now is None else now
        sid = str(sid or "")
        if not SID_RE.match(sid):
            return 400, {"error": "bad id"}
        import kastr_secret
        with self.lock:
            P = self._parse(room)
            s = P["sch"].get(sid)
            if sid in P["sdone"]:
                rid = P["sdone"][sid]
                st = {"state": "sent" if rid else "cancelled", "id": rid or None, "sent": bool(rid), "now": int(now)}
                return (200, dict(st, ok=True)) if do == "get" else (409, dict(st, error="it already went" if rid else "it was cancelled"))
            if not s:
                return 404, {"error": "no such scheduled message", "state": "gone"}
            if not kastr_secret.digest_matches(s.get("tk"), tk):
                return 403, {"error": "not yours"}
            r = s["rec"]
            if do == "get":
                return 200, {"ok": True, "state": "waiting", "rel": self._rel_of(P, sid), "text": r.get("text") or "",
                             "files": r.get("files") or [], "ttl": int(r.get("ttl") or 0), "vo": int(r.get("vo") or 0), "now": int(now)}
            if do == "time":
                try:
                    rel = int(rel)
                except (TypeError, ValueError):
                    return 400, {"error": "bad time"}
                if not now + SCHED_MIN_S <= rel <= now + SCHED_MAX_S:
                    return 400, {"error": "pick a time from a minute to 90 days ahead"}
                self._append_line(room, {"srel": sid, "rel": rel, "at": now})
                self._due_note(room, rel)
                return 200, {"ok": True, "rel": rel, "now": int(now)}
            if do == "now":
                rid = self._release_one(room, sid, s, now)
                return 200, {"ok": True, "id": rid, "now": int(now)}
            if do == "cancel":
                self._append_line(room, {"sdone": sid, "id": 0})
                self._drop_files(room, r.get("files"))
                scrub_file(self._path(room))
                return 200, {"ok": True, "now": int(now)}
        return 400, {"error": "do = get, time, now or cancel"}

    def _release_one(self, room, sid, s, now):
        r = s["rec"]
        ttl, vo = int(r.get("ttl") or 0), 1 if r.get("vo") else 0
        rec = {"id": self._next_id(room), "ts": int(now * 1000), "op": r.get("op") or "", "name": r.get("name") or "",
               "text": r.get("text") or "", "files": r.get("files") or [], "via": r.get("via") or "", "token": r.get("token") or ""}
        if ttl:
            rec.update(ttl=ttl, exp=int(now) + ttl)
        if vo:
            rec.update(vo=1, exp=int(now) + min(ttl or TIMER_CAP_S, TIMER_CAP_S))
            if r.get("pw"):
                rec["pw"] = r["pw"]
        self._append_line(room, rec)
        self._append_line(room, {"sdone": sid, "id": rec["id"]})
        scrub_file(self._path(room))   # the held copy's text goes: the posted line has it now
        if rec.get("exp"):
            self._due_note(room, rec["exp"])
        self.touch(room)
        return rec["id"]

    def tick(self, now=None):
        """The timer beat (every few seconds): scheduled messages go out, timed ones go -- for real.
        -> {released, expired}."""
        now = time.time() if now is None else now
        out = {"released": 0, "expired": 0}
        with self.lock:
            if self._due is None:
                self._due = {}
                for room in self.rooms():
                    t = self._due_calc(self._parse(room))
                    if t:
                        self._due[room] = t
            for room in [r for r, t in self._due.items() if t <= now]:
                P = self._parse(room)
                for sid, s in sorted(P["sch"].items(), key=lambda kv: self._rel_of(P, kv[0])):
                    if sid not in P["sdone"] and self._rel_of(P, sid) <= now:
                        self._release_one(room, sid, s, now)
                        out["released"] += 1
                P = self._parse(room)
                for mid, r in sorted(P["recs"].items()):
                    if r.get("exp") and mid not in P["dead"] and int(r["exp"]) <= now:
                        self._kill(room, r, "t")
                        out["expired"] += 1
                t = self._due_calc(self._parse(room))
                if t:
                    self._due[room] = t
                else:
                    self._due.pop(room, None)
            for t in [t for t, v in self._vo_tix.items() if v[2] <= now]:
                self._vo_tix.pop(t, None)
        if out["released"] or out["expired"]:
            self.log("chat: timers -- %d scheduled message(s) sent, %d gone" % (out["released"], out["expired"]))
        return out

    def read(self, room, since=0, limit=READ_LIMIT, tv=False, now=None):
        """Live messages with id > since, oldest first, the NEWEST `limit` of
        them, tokens withheld. Counts as access (the idle sweep keys on it).
        0.21.93: a message past its time is never listed (even before the beat removes it); a view-once one is a stub
        (no text, no files: `nf` + `opn`, the devices that opened it); a page without `tv` (older than 0.21.93) gets a
        line instead of a timed or view-once message -- it would keep the text and never let it go."""
        now = time.time() if now is None else now
        room = check_room(room)
        try:
            since = int(since or 0)
        except (TypeError, ValueError):
            since = 0
        try:
            limit = max(1, min(int(limit or READ_LIMIT), 1000))
        except (TypeError, ValueError):
            limit = READ_LIMIT
        with self.lock:
            P = self._parse(room)
            recs, dead = P["recs"], P["dead"]
            self.touch(room)
        out = []
        for mid in sorted(recs):
            if mid <= since or mid in dead:
                continue
            r = dict(recs[mid])
            r.pop("token", None)
            r.pop("pw", None)
            exp = int(r.get("exp") or 0)
            if exp and exp <= now:
                continue
            if exp and not tv:
                r = {"id": mid, "ts": r.get("ts"), "op": r.get("op"), "name": r.get("name"), "via": r.get("via"),
                     "text": OLD_STUB["vo" if r.get("vo") else "ttl"], "files": []}
            elif r.get("vo"):
                r.update(text="", files=[], nf=len(recs[mid].get("files") or []), opn=len(P["vop"].get(mid) or {}))
            out.append(r)
        return out[-limit:]

    def delete(self, room, msg_id, token=None, force=False):
        """Tombstone one message. The poster's token must match unless forced
        (an operator on the relay host)."""
        room = check_room(room)
        try:
            msg_id = int(msg_id)
        except (TypeError, ValueError):
            return False
        with self.lock:
            recs, dead = self._lines(room)
            rec = recs.get(msg_id)
            if rec is None or msg_id in dead:
                return False
            if not force:
                import kastr_secret
                if not kastr_secret.digest_matches(rec.get("token"), token):   # 0.21.92: a digest (or an old plain token)
                    return False
            self._kill(room, rec, "")   # 0.21.93: its line is overwritten and its attachments go too (was: a tombstone only)
            self.touch(room)
        return True

    def merge_in(self, room, text, keep=None):
        """0.21.53 (standby hub): add the lines of `text` this transcript does not have yet (a take-over or a hand-back
        merges another hub's copy). Under the lock; the id counter is re-read afterwards. -> lines added."""
        room = check_room(room)
        with self.lock:
            os.makedirs(self.dir, exist_ok=True)
            have = set()
            try:
                with open(self._path(room), encoding="utf-8") as f:
                    have = {ln.rstrip("\n").rstrip() for ln in f}
            except OSError:
                pass
            # 0.21.93: what either copy deleted stays deleted -- a dead message (or a scheduled one that went) is not
            # brought back, and a tombstone that arrives scrubs the line it kills here
            P = self._parse(room)
            dead, done, theirs = set(P["dead"]), set(P["sdone"]), []
            for ln in str(text or "").splitlines():
                ln = ln.rstrip()
                if not ln.strip() or ln in have:
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue   # a broken line is not copied
                if not isinstance(d, dict):
                    continue
                try:
                    if "del" in d:
                        dead.add(int(d["del"]))
                    elif "sdone" in d:
                        done.add(str(d["sdone"]))
                except (TypeError, ValueError):
                    pass
                theirs.append((ln, d))
            add = []
            for ln, d in theirs:
                if "sch" in d and str(d["sch"]) in done:
                    continue
                if not any(k in d for k in ("del", "sch", "sdone", "srel", "vop")):
                    try:
                        if int(d.get("id")) in dead:
                            continue
                    except (TypeError, ValueError):
                        pass
                add.append(ln)
            if add:
                with open(self._path(room), "a", encoding="utf-8", newline="") as f:   # LF line ends, like append()
                    f.write("\n".join(add) + "\n")
            if add or dead != P["dead"] or done != set(P["sdone"]):
                scrub_file(self._path(room))
            self._due = None
            if keep is not None:
                try:
                    if keep:
                        open(self._keep_path(room), "a").close()
                    elif os.path.exists(self._keep_path(room)):
                        os.remove(self._keep_path(room))
                except OSError:
                    pass
            self._last_id.pop(room, None)
        return len(add)

    def delete_room(self, room):
        """The room's transcript, keep marker and chat attachments are gone."""
        room = check_room(room)
        removed = []
        with self.lock:
            for p in (self._path(room), self._keep_path(room)):
                try:
                    os.remove(p)
                    removed.append(p)
                except OSError:
                    pass
            for p in self._attachments(room):
                try:
                    os.remove(p)
                    removed.append(p)
                except OSError:
                    pass
            self._last_id.pop(room, None)
            if self._due is not None:
                self._due.pop(room, None)   # 0.21.93
        if removed:
            self.log("chat: room %s deleted (%d files)" % (room, len(removed)))
        return removed

    def rename_room(self, old, new):
        """0.21.65: a renamed room keeps its history -- the transcript, its keep marker and its chat attachments' room move
        from `old` to `new` (a transcript already under `new` keeps its lines; the old ones are added). -> moved?"""
        old, new = check_room(old), check_room(new)
        moved = False
        with self.lock:
            src = self._path(old)
            if os.path.exists(src):
                if os.path.exists(self._path(new)):
                    try:
                        with open(src, encoding="utf-8", newline="") as f:
                            text = f.read()
                    except OSError:
                        text = ""
                    self.merge_in(new, text)
                    try:
                        os.remove(src)
                    except OSError:
                        pass
                else:
                    os.replace(src, self._path(new))
                moved = True
            if os.path.exists(self._keep_path(old)):
                try:
                    os.replace(self._keep_path(old), self._keep_path(new))
                except OSError:
                    pass
            d = self.files_dir
            if d and self.attachments_for is None:
                try:
                    names = os.listdir(d)
                except OSError:
                    names = []
                for fn in names:
                    if not fn.endswith(".json"):
                        continue
                    mp = os.path.join(d, fn)
                    try:
                        with open(mp, encoding="utf-8") as f:
                            m = json.load(f)
                        if m.get("kind") == "chat" and m.get("room") == old:
                            m["room"] = new
                            with open(mp, "w", encoding="utf-8", newline="") as f:
                                json.dump(m, f)
                    except (OSError, ValueError):
                        continue
            self._last_id.pop(old, None)
            self._last_id.pop(new, None)
            self._due = None   # 0.21.93
        if moved:
            self.log("chat: room %s renamed to %s (history moved)" % (old, new))
        return moved

    def _attachments(self, room):
        if self.attachments_for is not None:
            try:
                return list(self.attachments_for(room) or [])
            except Exception:
                return []
        d = self.files_dir
        if not d:
            return []
        out = []
        try:
            names = os.listdir(d)
        except OSError:
            return out
        for fn in names:
            if not fn.endswith(".json"):
                continue
            mp = os.path.join(d, fn)
            try:
                with open(mp, encoding="utf-8") as f:
                    m = json.load(f)
            except (OSError, ValueError):
                continue
            if m.get("kind") == "chat" and m.get("room") == room:
                out.append(os.path.join(d, fn[:-5]))
                out.append(mp)
        return out

    def touch(self, room):
        """Read and append both count as use; the idle sweep keys on mtime."""
        try:
            os.utime(self._path(check_room(room)), None)
        except OSError:
            pass

    def mark_keep(self, room, keep):
        room = check_room(room)
        with self.lock:
            p = self._keep_path(room)
            if keep:
                os.makedirs(self.dir, exist_ok=True)
                try:
                    with open(p, "w", encoding="utf-8", newline="") as f:
                        f.write(json.dumps({"at": int(time.time())}))
                except OSError:
                    pass
            else:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def is_kept(self, room):
        return os.path.exists(self._keep_path(check_room(room)))

    def rooms(self):
        """Slugs that have a transcript on disk."""
        out = []
        try:
            names = os.listdir(self.dir)
        except OSError:
            return out
        for fn in names:
            if fn.endswith(".jsonl") and SLUG_RE.match(fn[:-6]):
                out.append(fn[:-6])
        return sorted(out)

    def sweep(self, kept=(), max_idle=MAX_IDLE):
        """Delete the rooms nobody keeps that saw no read or write for max_idle
        seconds. `kept` = the AuthStore's persistent slugs. -> swept slugs."""
        kept = set(kept or ())
        swept = []
        now = time.time()
        with self.lock:
            for room in self.rooms():
                if room in kept or self.is_kept(room):
                    continue
                try:
                    idle = now - os.path.getmtime(self._path(room))
                except OSError:
                    continue
                if idle > max_idle:
                    self.delete_room(room)
                    swept.append(room)
        if swept:
            self.log("chat: swept %d idle room(s): %s" % (len(swept), ", ".join(swept)))
        return swept


if __name__ == "__main__":
    import tempfile
    import shutil
    d = tempfile.mkdtemp(prefix="kastr-chat-")
    try:
        s = ChatStore(d, files_dir=os.path.join(d, "shared"))
        a = s.append("demo", "kj", "Kenton", "hello", [], "hub")
        b = s.append("demo", "kj", "Kenton", "world", [], "hub")
        assert b["id"] > a["id"]
        got = s.read("demo")
        assert [m["text"] for m in got] == ["hello", "world"] and "token" not in got[0]
        assert [m["id"] for m in s.read("demo", since=a["id"])] == [b["id"]]
        assert [m["id"] for m in s.read("demo", limit=1)] == [b["id"]]
        assert not s.delete("demo", a["id"], "nope") and s.delete("demo", a["id"], a["token"])
        assert [m["id"] for m in s.read("demo")] == [b["id"]]
        with open(s._path("demo"), "ab") as f:
            f.write(b'{"id": 99999, "ts"')           # a torn tail
        assert [m["id"] for m in s.read("demo")] == [b["id"]]
        c = s.append("demo", "kj", "Kenton", "after tear")
        assert [m["id"] for m in s.read("demo")] == [b["id"], c["id"]]
        s.mark_keep("demo", True)
        old = time.time() - 2 * MAX_IDLE
        os.utime(s._path("demo"), (old, old))
        assert s.sweep() == [] and s.is_kept("demo")
        s.mark_keep("demo", False)
        assert s.sweep(kept={"demo"}) == []
        assert s.sweep() == ["demo"] and s.rooms() == []
        try:
            s.append("Bad Room", "x", "x", "x")
            raise AssertionError("slug check")
        except ValueError:
            pass
        print("kastr_chat self-check OK")
    finally:
        shutil.rmtree(d, ignore_errors=True)
