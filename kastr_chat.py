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
        recs, dead = {}, set()
        try:
            with open(self._path(room), "r", encoding="utf-8", newline="") as f:
                raw = f.read()
        except OSError:
            return recs, dead
        for line in raw.split("\n"):
            line = line.strip("\r")
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            if "del" in d:
                try:
                    dead.add(int(d["del"]))
                except (TypeError, ValueError):
                    pass
                continue
            try:
                mid = int(d.get("id"))
            except (TypeError, ValueError):
                continue
            recs[mid] = d
        return recs, dead

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

    def append(self, room, op, name, text, files=None, via=""):
        """-> the stored record INCLUDING its delete token (the poster's copy)."""
        room = check_room(room)
        text = "" if text is None else str(text)
        if len(text) > TEXT_MAX:
            raise ValueError("message longer than %d characters" % TEXT_MAX)
        files = _clean_files(files)
        if not text.strip() and not files:
            raise ValueError("empty message")
        rec = {
            "id": 0,
            "ts": int(time.time() * 1000),
            "op": str(op or "")[:NAME_MAX],
            "name": str(name or "")[:NAME_MAX],
            "text": text,
            "files": files,
            "via": str(via or "")[:NAME_MAX],
            "token": uuid.uuid4().hex,
        }
        with self.lock:
            rec["id"] = self._next_id(room)
            self._append_line(room, rec)
        return dict(rec)

    def read(self, room, since=0, limit=READ_LIMIT):
        """Live messages with id > since, oldest first, the NEWEST `limit` of
        them, tokens withheld. Counts as access (the idle sweep keys on it)."""
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
            recs, dead = self._lines(room)
            self.touch(room)
        out = []
        for mid in sorted(recs):
            if mid <= since or mid in dead:
                continue
            r = dict(recs[mid])
            r.pop("token", None)
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
                want = str(rec.get("token") or "")
                if not token or not want or str(token) != want:
                    return False
            self._append_line(room, {"del": msg_id})
            self.touch(room)
        return True

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
        if removed:
            self.log("chat: room %s deleted (%d files)" % (room, len(removed)))
        return removed

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
