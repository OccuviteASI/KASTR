# -*- coding: utf-8 -*-
"""0.21.96 SCHEDULED MEETINGS -- the hub's meeting store, the recurrence rules and the calendar (.ics) file.

Kenton (2026-10-28): "templates to also be setup to configure a webmeeting, like a teams meeting. Where I can schedule it for a
weekly/daily meeting, or just a 1 time meeting"; (2026-10-30): "add scheduled meetings to the next update".

A MEETING is a title, a start (the organizer's time zone NAME + the LOCAL wall time, so a weekly 09:00 stays 09:00 across a
daylight-saving change -- kastr_tz), a length, how it repeats (once, daily, weekly on chosen days, optionally until a date), an
optional template (0.21.92, applied when the room opens), "Requires the host to join" (default OFF), the people invited (KASTR
people by NAME, each optionally a presenter) and a guest link switch (guests come in by a 0.21.75 invite link).

THE ROOM: by default a meeting has ONE ROOM OF ITS OWN for the whole series (mt-<12 hex>), so its chat and files are kept from
one occurrence to the next. That room is hidden like My room: no public presence / state / registry record (the minter never
grants those puts), never in the rooms rail, refused to anyone not invited (the hub decides every mint), joinable from
EARLY_S before a start until the room empties after the scheduled end. A room admin may instead hold a meeting in a room of
theirs (an existing, visible room): invitees then get that room for the meeting's windows without its codes.

EDITS: the series (title, time, length, repeat, people, ...) or ONE occurrence (moved, made longer, retitled, cancelled) --
an occurrence is named by its ORIGINAL local start ("YYYY-MM-DDTHH:MM", the iCalendar RECURRENCE-ID), so editing the series
time later keeps the exceptions that still match. Cancelling the series keeps the record CANCELLED_KEEP_S so invitees see it
was cancelled (and can take the cancelling .ics).

STORAGE: <state>/meetings/meetings.json on the hub, carried in the records bundle (AuthStore.export_bundle) like the
templates: hand-over, the standby's replica and the hand-back move it. No code, token or invite link is ever stored here: a
meeting's guest link is DERIVED (HMAC of the hub's key, the meeting id and a generation), its digest kept by the invite store.
"""
import copy
import datetime as _dt
import hashlib
import json
import os
import re
import threading
import time

import kastr_tz

MID_RE = re.compile(r"^m[0-9a-f]{12}$")
ROOM_PREFIX = "mt-"
ROOM_RE = re.compile(r"^mt-[0-9a-f]{12}$")
SLUG_RE = re.compile(r"^[a-z0-9-]{1,32}$")
TID_RE = re.compile(r"^t[0-9a-f]{12}$")
WALL_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
FREQS = ("once", "daily", "weekly")
DAY_NAMES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")   # datetime.weekday() order

EARLY_S = 600                 # the room opens this long before a start (Kenton: "joinable from about 10 min before")
REMIND_S = 300                # the page's reminder (Kenton: "a reminder about 5 min before")
EMPTY_S = 120                 # after the scheduled end, the room closes this long after its last person left
LIVE_S = 45                   # a page's beat older than this: that page left
OVERRUN_S = 12 * 3600         # a meeting still going after its end stays open at most this long past it
DUR_MIN, DUR_MAX = 5, 12 * 60
TITLE_MAX, NOTE_MAX = 80, 600
PEOPLE_MAX = 60
PER_PERSON_MAX = 60           # meetings one person organizes
PER_ROOM_MAX = 60             # meetings held in one existing room
TOTAL_MAX = 3000
EX_MAX = 120                  # one series' changed / cancelled occurrences
DONE_KEEP = 24                # the ended occurrences a series remembers
MOVE_MAX_S = 31 * 86400       # an occurrence moves at most this far from its original time
SERIES_MAX_DAYS = 3 * 366     # an "until" at most this far after the start
CANCELLED_KEEP_S = 14 * 86400   # a cancelled meeting stays listed (as cancelled) this long
ENDED_KEEP_S = 30 * 86400       # a series whose last occurrence ended this long ago is dropped
GONE_KEEP_S = 60 * 86400        # a deleted meeting's tombstone (a hand-back never brings it back)
LIST_SCAN_DAYS = 400          # how far ahead the list looks for a next occurrence


def _now():
    return time.time()


def txt(v, n):
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]+", " ", str(v or "")).strip()
    return s[:n]


def name_disp(v):
    return " ".join(str(v or "").split())[:48]


def name_key(v):
    """The person key -- kastr_templates.name_key / kastr_relay.personal_key (lowercased, collapsed, at most 48)."""
    return name_disp(v).lower()


def _int(v, lo, hi, dflt=0):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return dflt
    return max(lo, min(hi, v))


def parse_wall(s):
    """'YYYY-MM-DDTHH:MM' -> naive datetime, or None."""
    m = WALL_RE.match(str(s or ""))
    if not m:
        return None
    try:
        return _dt.datetime(*[int(x) for x in m.groups()])
    except ValueError:
        return None


def wall_str(w):
    return "%04d-%02d-%02dT%02d:%02d" % (w.year, w.month, w.day, w.hour, w.minute)


def parse_date(s):
    m = DATE_RE.match(str(s or ""))
    if not m:
        return None
    try:
        return _dt.date(*[int(x) for x in m.groups()])
    except ValueError:
        return None


def new_id():
    return "m" + os.urandom(6).hex()


def new_room():
    return ROOM_PREFIX + os.urandom(6).hex()


def is_room(slug):
    return bool(ROOM_RE.match(str(slug or "")))


def _people(v):
    out, seen = [], set()
    for x in (v if isinstance(v, list) else [])[:PEOPLE_MAX * 2]:
        if isinstance(x, str):
            x = {"name": x}
        if not isinstance(x, dict):
            continue
        nm = name_disp(x.get("name"))
        nk = name_key(nm)
        if not nk or nk in seen:
            continue
        seen.add(nk)
        out.append({"name": nm, "nk": nk, "pres": bool(x.get("pres"))})
        if len(out) >= PEOPLE_MAX:
            break
    return out


def clean_ex(v):
    """The changed / cancelled occurrences: {original local start: {cancel: 1} | {start?, dur?, title?}}."""
    out = {}
    for k, e in (v.items() if isinstance(v, dict) else []):
        w0 = parse_wall(k)
        if w0 is None or not isinstance(e, dict) or len(out) >= EX_MAX:
            continue
        if e.get("cancel"):
            out[k] = {"cancel": 1}
            continue
        c = {}
        w = parse_wall(e.get("start"))
        if w is not None and abs((w - w0).total_seconds()) <= MOVE_MAX_S:
            c["start"] = wall_str(w)
        if e.get("dur") not in (None, ""):
            c["dur"] = _int(e.get("dur"), DUR_MIN, DUR_MAX, 30)
        t = txt(e.get("title"), TITLE_MAX)
        if t:
            c["title"] = t
        if c:
            out[k] = c
    return out


def clean_meeting(d):
    """A meeting as the hub keeps it -> (meeting, None) | (None, why)."""
    if not isinstance(d, dict):
        return None, "bad meeting"
    mid = str(d.get("id") or "")
    if not MID_RE.match(mid):
        return None, "bad meeting id"
    title = txt(d.get("title"), TITLE_MAX)
    if not title:
        return None, "give the meeting a title"
    tz = str(d.get("tz") or "")
    if not kastr_tz.known(tz):
        return None, "unknown time zone"
    w = parse_wall(d.get("start"))
    if w is None:
        return None, "pick a start date and time"
    freq = d.get("freq") if d.get("freq") in FREQS else "once"
    days = sorted({_int(x, 0, 6) for x in (d.get("days") if isinstance(d.get("days"), list) else []) if str(x).lstrip("-").isdigit()})
    if freq == "weekly" and not days:
        days = [w.weekday()]
    if freq != "weekly":
        days = []
    until = parse_date(d.get("until")) if freq != "once" else None
    if until is not None:
        if until < w.date():
            return None, "the repeat ends before the first meeting"
        if (until - w.date()).days > SERIES_MAX_DAYS:
            until = w.date() + _dt.timedelta(days=SERIES_MAX_DAYS)
    room = str(d.get("room") or "")
    if not SLUG_RE.match(room):
        return None, "bad room"
    org = d.get("org") if isinstance(d.get("org"), dict) else {}
    oname = name_disp(org.get("name"))
    if not oname:
        return None, "no organizer"
    out = {"id": mid, "title": title, "note": txt(d.get("note"), NOTE_MAX), "room": room, "own": is_room(room),
           "org": {"nk": name_key(org.get("nk") or oname), "name": oname},
           "tz": tz, "start": wall_str(w), "dur": _int(d.get("dur"), DUR_MIN, DUR_MAX, 30),
           "freq": freq, "days": days, "until": until.isoformat() if until else "",
           "tpl": str(d.get("tpl") or "") if TID_RE.match(str(d.get("tpl") or "")) else "",
           "host": bool(d.get("host")), "guests": bool(d.get("guests")),
           "people": _people(d.get("people")), "ex": clean_ex(d.get("ex")),
           "cancelled": _int(d.get("cancelled"), 0, 1 << 40), "by": txt(d.get("by"), 48),
           "created": _int(d.get("created"), 0, 1 << 40), "upd": _int(d.get("upd"), 0, 1 << 40),
           "seq": _int(d.get("seq"), 0, 1 << 20), "gen": _int(d.get("gen"), 0, 1 << 20),
           "linkId": str(d.get("linkId") or "") if re.match(r"^[0-9a-f]{8}$", str(d.get("linkId") or "")) else "",
           "done": {}}
    for k, at in (d.get("done").items() if isinstance(d.get("done"), dict) else []):
        if parse_wall(k) is not None:
            out["done"][k] = _int(at, 0, 1 << 40)
    if len(out["done"]) > DONE_KEEP:
        out["done"] = dict(sorted(out["done"].items())[-DONE_KEEP:])
    out["people"] = [x for x in out["people"] if x["nk"] != out["org"]["nk"]]
    return out, None


# ---- recurrence ------------------------------------------------------------------------------------------------------------

def _originals(m, d_from, d_to):
    """The ORIGINAL local starts (naive datetimes) of `m` on local dates d_from..d_to."""
    w0 = parse_wall(m["start"])
    first = w0.date()
    until = parse_date(m.get("until")) if m.get("until") else None
    if m["freq"] == "once":
        if d_from <= first <= d_to:
            yield w0
        return
    d = max(first, d_from)
    end = min(d_to, until) if until else d_to
    days = set(m.get("days") or [])
    while d <= end:
        if m["freq"] == "daily" or d.weekday() in days:
            yield _dt.datetime(d.year, d.month, d.day, w0.hour, w0.minute)
        d += _dt.timedelta(days=1)


def occurrence(m, key, w=None):
    """One occurrence (by its original local start) -> {key, start, end, local, dur, title, moved, cancelled}."""
    w0 = w or parse_wall(key)
    e = (m.get("ex") or {}).get(key) or {}
    wl = parse_wall(e.get("start")) if e.get("start") else w0
    dur = int(e.get("dur") or m["dur"])
    s = kastr_tz.to_utc(m["tz"], wl)
    return {"key": key, "start": s, "end": s + dur * 60, "local": wall_str(wl), "dur": dur,
            "title": e.get("title") or m["title"], "moved": bool(e.get("start") or e.get("dur") or e.get("title")),
            "cancelled": bool(e.get("cancel"))}


def occurrences(m, frm, to, limit=500, cancelled=False):
    """The occurrences of `m` overlapping UTC epochs [frm, to) in start order (cancelled ones only when asked)."""
    pad = MOVE_MAX_S + 2 * 86400
    lo = kastr_tz.to_local(m["tz"], frm - pad)[0].date()
    hi = kastr_tz.to_local(m["tz"], to + pad)[0].date()
    out = []
    for w in _originals(m, lo, hi):
        o = occurrence(m, wall_str(w), w)
        if o["end"] <= frm or o["start"] >= to or (o["cancelled"] and not cancelled):
            continue
        out.append(o)
    out.sort(key=lambda o: (o["start"], o["key"]))
    return out[:limit]


def has_original(m, key):
    w = parse_wall(key)
    if w is None:
        return False
    return any(wall_str(x) == key for x in _originals(m, w.date(), w.date()))


def next_occ(m, now, live=False):
    """The occurrence that is on now (its room open: from EARLY_S before the start to its end -- or later while `live`) or
    the next one -> occurrence dict + `state` ("open" | "soon" | "later"), or None when the series is over."""
    if m.get("cancelled"):
        return None
    done = m.get("done") or {}
    look = [now - 14 * 86400, now + LIST_SCAN_DAYS * 86400]
    for o in occurrences(m, look[0], look[1], limit=64):
        if o["key"] in done:
            continue
        if o["end"] <= now and not (live and o["start"] <= now and now - o["end"] < OVERRUN_S):
            continue
        if o["start"] - EARLY_S <= now:
            return dict(o, state="open")
        return dict(o, state="soon" if o["start"] - now <= 3600 else "later")
    return None


def window(m, now, live=False):
    """The occurrence whose room is open now (None when none is) -- live: someone is still in the room after the end."""
    o = next_occ(m, now, live)
    return o if o and o["state"] == "open" else None


def series_over(m, now):
    """The last occurrence ended (and the series will never meet again)."""
    if m.get("cancelled"):
        return True
    if m["freq"] != "once" and not m.get("until"):
        return False
    return next_occ(m, now - EMPTY_S) is None


def last_end(m):
    """The UTC end of the series' last occurrence (None for an open-ended series)."""
    if m["freq"] != "once" and not m.get("until"):
        return None
    w0 = parse_wall(m["start"])
    end = parse_date(m["until"]) if m.get("until") else w0.date()
    occ = []
    for w in _originals(m, w0.date(), end + _dt.timedelta(days=1)):
        occ.append(occurrence(m, wall_str(w), w))
    return max((o["end"] for o in occ), default=None)


# ---- the calendar file -----------------------------------------------------------------------------------------------------

def _ics_text(s):
    return str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")


def _fold(line):
    """RFC 5545 3.1: lines over 75 octets go on with CRLF + one space (never inside a UTF-8 character)."""
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        cb = ch.encode("utf-8")
        if len(cur) + len(cb) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += cb
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def _utc(ts):
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(ts))


def _wall_ics(w):
    return "%04d%02d%02dT%02d%02d00" % (w.year, w.month, w.day, w.hour, w.minute)


def ics(m, now=None, join_url="", host_name="KASTR", cancel=False):
    """The meeting as an iCalendar file (text, CRLF). TZID + a VTIMEZONE made from the zone's rule when it can be said in
    iCalendar terms, UTC times otherwise. A series: RRULE + EXDATE (cancelled occurrences) + one VEVENT per changed
    occurrence (RECURRENCE-ID). cancel=True (or a cancelled meeting): METHOD:CANCEL, STATUS:CANCELLED -- a calendar takes it
    off. `join_url` goes in URL and the description (never an invite link unless the caller put one there)."""
    now = _now() if now is None else now
    cancel = cancel or bool(m.get("cancelled"))
    vt = kastr_tz.vtimezone(m["tz"])
    uid = "%s@kastr" % m["id"]
    seq = int(m.get("seq") or 0)

    def dt_line(prop, w, ts):
        if vt:
            return "%s;TZID=%s:%s" % (prop, m["tz"], _wall_ics(w))
        return "%s:%s" % (prop, _utc(ts))

    desc = m.get("note") or ""
    if join_url:
        desc = (desc + "\n\n" if desc else "") + "Join in KASTR: " + join_url
    org = (m.get("org") or {}).get("name") or ""
    if org:
        desc = (desc + "\n" if desc else "") + "Organizer: " + org
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ASI//KASTR meetings 0.21.96//EN", "CALSCALE:GREGORIAN",
         "METHOD:" + ("CANCEL" if cancel else "PUBLISH")]
    if vt:
        L += vt

    def event(w, dur, title, extra):
        ts = kastr_tz.to_utc(m["tz"], w)
        ev = ["BEGIN:VEVENT", "UID:" + uid, "SEQUENCE:%d" % seq, "DTSTAMP:" + _utc(now),
              dt_line("DTSTART", w, ts), dt_line("DTEND", w + _dt.timedelta(minutes=dur), ts + dur * 60)]
        ev += extra
        ev += ["SUMMARY:" + _ics_text(title), "STATUS:" + ("CANCELLED" if cancel else "CONFIRMED")]
        if desc:
            ev.append("DESCRIPTION:" + _ics_text(desc))
        if join_url:
            ev += ["URL:" + join_url, "LOCATION:" + _ics_text(host_name or "KASTR")]
        ev.append("END:VEVENT")
        return ev

    w0 = parse_wall(m["start"])
    rr = []
    if m["freq"] != "once":
        r = "RRULE:FREQ=" + ("DAILY" if m["freq"] == "daily" else "WEEKLY")
        if m["freq"] == "weekly":
            r += ";BYDAY=" + ",".join(DAY_NAMES[d] for d in m["days"])
        if m.get("until"):
            u = parse_date(m["until"])
            last = _dt.datetime(u.year, u.month, u.day, 23, 59)
            r += ";UNTIL=" + _utc(kastr_tz.to_utc(m["tz"], last))
        rr.append(r)
        for k, e in sorted((m.get("ex") or {}).items()):
            if e.get("cancel") and has_original(m, k):
                w = parse_wall(k)
                rr.append(dt_line("EXDATE", w, kastr_tz.to_utc(m["tz"], w)))
    first_ex = (m.get("ex") or {}).get(m["start"]) if m["freq"] == "once" else None
    if first_ex and not first_ex.get("cancel"):   # a one-time meeting's own change is the meeting
        o = occurrence(m, m["start"])
        L += event(parse_wall(o["local"]), o["dur"], o["title"], rr)
    else:
        L += event(w0, m["dur"], m["title"], rr)
    if m["freq"] != "once":
        for k, e in sorted((m.get("ex") or {}).items()):
            if e.get("cancel") or not has_original(m, k):
                continue
            o = occurrence(m, k)
            wk = parse_wall(k)
            L += event(parse_wall(o["local"]), o["dur"], o["title"], [dt_line("RECURRENCE-ID", wk, kastr_tz.to_utc(m["tz"], wk))])
    L.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in L) + "\r\n"


def ics_name(m):
    base = re.sub(r"[^A-Za-z0-9 _-]+", "", m.get("title") or "meeting").strip().replace(" ", "-")[:40] or "meeting"
    return base + ".ics"


# ---- what a page sees ------------------------------------------------------------------------------------------------------

def role_of(m, nk):
    """'org' | 'pres' | 'in' | '' for a person key."""
    if not nk:
        return ""
    if (m.get("org") or {}).get("nk") == nk:
        return "org"
    for x in m.get("people") or []:
        if x["nk"] == nk:
            return "pres" if x.get("pres") else "in"
    return ""


def public(m, now, nk="", manage=False, live=None):
    """A meeting as the Meetings list shows it (never a link token)."""
    o = next_occ(m, now, bool(live and live.get("n")))
    out = {"id": m["id"], "title": m["title"], "note": m.get("note") or "", "room": m["room"], "own": m["own"],
           "org": (m.get("org") or {}).get("name") or "", "tz": m["tz"], "start": m["start"], "dur": m["dur"],
           "freq": m["freq"], "days": list(m.get("days") or []), "until": m.get("until") or "", "tpl": m.get("tpl") or "",
           "host": bool(m.get("host")), "guests": bool(m.get("guests")), "role": role_of(m, nk), "manage": bool(manage),
           "people": [{"name": x["name"], "pres": bool(x.get("pres"))} for x in m.get("people") or []],
           "cancelled": int(m.get("cancelled") or 0), "upd": int(m.get("upd") or 0), "seq": int(m.get("seq") or 0)}
    if o:
        out["next"] = {k: o[k] for k in ("key", "start", "end", "local", "dur", "title", "moved", "state")}
        out["next"]["abbr"] = kastr_tz.abbr(m["tz"], o["start"])
    if live:
        out["live"] = {"n": int(live.get("n") or 0), "hostIn": bool(live.get("hostIn"))}
    if manage:
        out["ex"] = copy.deepcopy(m.get("ex") or {})
    return out


# ---- the store -------------------------------------------------------------------------------------------------------------

def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, path)


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


class MeetingBook:
    """<state>/meetings/meetings.json: {meetings: {mid: meeting}, gone: {mid: at}}."""

    def __init__(self, state_dir=None, log=None):
        self.state_dir = state_dir or os.getcwd()
        self.dir = os.path.join(self.state_dir, "meetings")
        self.log = log or (lambda m: None)
        self.lock = threading.RLock()
        self.meetings, self.gone = {}, {}
        self.on_save = None   # AuthStore: a save moves the store's version (the standby's replica copies the bundle)
        self.n = 0
        d = _load(self._path())
        if isinstance(d, dict):
            self._import_locked(d, replace=True)

    def _path(self):
        return os.path.join(self.dir, "meetings.json")

    def ver(self):
        return self.n

    def _save_locked(self):
        os.makedirs(self.dir, exist_ok=True)
        _save(self._path(), {"meetings": self.meetings, "gone": self.gone})
        self.n += 1
        cb = self.on_save
        if callable(cb):
            try:
                cb()
            except Exception:
                pass

    def _import_locked(self, d, replace=False):
        n = 0
        if replace:
            self.meetings, self.gone = {}, {}
        for mid, at in (d.get("gone") if isinstance(d.get("gone"), dict) else {}).items():
            if MID_RE.match(str(mid)):
                self.gone[str(mid)] = max(int(self.gone.get(str(mid)) or 0), _int(at, 0, 1 << 40))
        for mid, m in (d.get("meetings") if isinstance(d.get("meetings"), dict) else {}).items():
            if str(mid) in self.gone or not isinstance(m, dict):
                continue
            c, _why = clean_meeting(dict(m, id=mid))
            if c is None:
                continue
            mine = self.meetings.get(c["id"])
            if mine is None or replace or c["upd"] > mine["upd"] or (c["upd"] == mine["upd"] and len(c["done"]) > len(mine["done"])):
                if mine is not None and not replace:   # the occurrences ended on either box stay ended
                    c["done"] = dict(sorted({**mine.get("done", {}), **c["done"]}.items())[-DONE_KEEP:])
                self.meetings[c["id"]] = c
                n += 1
        return n

    # ---- the bundle (hand-over, the standby's replica, the hand-back) ------------------------------------------------------
    def export(self):
        with self.lock:
            return json.loads(json.dumps({"meetings": self.meetings, "gone": self.gone}))

    def import_(self, b):
        """A new hub takes the old hub's meetings (its own stay where the old hub had none)."""
        if not isinstance(b, dict):
            return 0
        with self.lock:
            n = self._import_locked(b)
            self._save_locked()
        return n

    def merge(self, b):
        """A hand-back: newer edits win, deletions stick (tombstones)."""
        if not isinstance(b, dict):
            return 0
        with self.lock:
            n = self._import_locked(b)
            for mid in list(self.gone):
                self.meetings.pop(mid, None)
            self._save_locked()
        return n

    # ---- meetings ----------------------------------------------------------------------------------------------------------
    def get(self, mid):
        with self.lock:
            m = self.meetings.get(str(mid or ""))
            return copy.deepcopy(m) if m else None

    def by_room(self, room):
        """The meeting holding its own room `room` (mt-...) -> meeting | None."""
        with self.lock:
            for m in self.meetings.values():
                if m["own"] and m["room"] == room:
                    return copy.deepcopy(m)
        return None

    def in_room(self, room):
        """Every meeting held in `room` (an existing room: several may)."""
        with self.lock:
            return [copy.deepcopy(m) for m in self.meetings.values() if m["room"] == room]

    def all(self):
        with self.lock:
            return [copy.deepcopy(m) for m in self.meetings.values()]

    def own_rooms(self):
        """The hidden rooms of meetings not cancelled -- kept (their chat stays between occurrences)."""
        with self.lock:
            return sorted(m["room"] for m in self.meetings.values() if m["own"] and not m.get("cancelled"))

    def put(self, m, new=False):
        """Save a meeting -> (meeting, None, 200) | (None, why, code). A new one gets its id (and its own room) first."""
        m = dict(m)
        now = int(_now())
        with self.lock:
            if new:
                if len(self.meetings) >= TOTAL_MAX:
                    return None, "this hub keeps too many meetings -- cancel some first", 409
                nk = (m.get("org") or {}).get("nk") or name_key((m.get("org") or {}).get("name"))
                mine = [x for x in self.meetings.values() if x["org"]["nk"] == nk and not x.get("cancelled")]
                if len(mine) >= PER_PERSON_MAX:
                    return None, "you organize %d meetings already -- cancel some first" % PER_PERSON_MAX, 409
                if m.get("room") and not is_room(m["room"]):
                    held = [x for x in self.meetings.values() if x["room"] == m["room"] and not x.get("cancelled")]
                    if len(held) >= PER_ROOM_MAX:
                        return None, "room %s holds %d meetings already" % (m["room"], PER_ROOM_MAX), 409
                m["id"] = new_id()
                while m["id"] in self.meetings or m["id"] in self.gone:
                    m["id"] = new_id()
                if not m.get("room"):
                    m["room"] = new_room()
                m["created"] = now
            old = self.meetings.get(m.get("id"))
            if not new and old is None:
                return None, "no such meeting", 404
            m["upd"] = max(now, int((old or {}).get("upd") or 0) + 1)
            if old is not None:
                m["seq"] = int(old.get("seq") or 0) + 1
                m.setdefault("done", old.get("done") or {})
                m.setdefault("created", old.get("created") or now)
            c, why = clean_meeting(m)
            if c is None:
                return None, why, 400
            self.meetings[c["id"]] = c
            self._save_locked()
            return copy.deepcopy(c), None, 200

    def mark_done(self, mid, key, at=None):
        """An occurrence ended (End pressed / the room emptied after its end) -- its window never reopens."""
        with self.lock:
            m = self.meetings.get(mid)
            if m is None or key in (m.get("done") or {}):
                return False
            m.setdefault("done", {})[key] = int(at or _now())
            if len(m["done"]) > DONE_KEEP:
                m["done"] = dict(sorted(m["done"].items())[-DONE_KEEP:])
            m["upd"] = max(int(_now()), int(m.get("upd") or 0) + 1)
            self._save_locked()
            return True

    def delete(self, mid):
        with self.lock:
            m = self.meetings.pop(mid, None)
            if m is None:
                return None
            self.gone[mid] = int(_now())
            self._save_locked()
            return m

    def rename_person(self, old, new, new_name):
        """A person changed their name (kastr_relay rename): their meetings and invitations follow."""
        n = 0
        with self.lock:
            for m in self.meetings.values():
                if m["org"]["nk"] == old:
                    m["org"] = {"nk": new, "name": new_name}
                    n += 1
                for x in m.get("people") or []:
                    if x["nk"] == old:
                        x.update(nk=new, name=new_name)
                        n += 1
            if n:
                self._save_locked()
        return n

    def rename_room(self, old, new):
        n = 0
        with self.lock:
            for m in self.meetings.values():
                if m["room"] == old and not m["own"]:
                    m["room"] = new
                    n += 1
            if n:
                self._save_locked()
        return n

    def sweep(self, now=None):
        """Drop meetings cancelled over CANCELLED_KEEP_S ago and series whose last occurrence ended over ENDED_KEEP_S ago,
        and old tombstones -> the dropped meetings (the caller closes their own rooms)."""
        now = _now() if now is None else now
        out = []
        with self.lock:
            for mid, m in list(self.meetings.items()):
                c = int(m.get("cancelled") or 0)
                drop = bool(c) and now - c > CANCELLED_KEEP_S
                if not drop and not c:
                    le = last_end(m)
                    drop = le is not None and now - le > ENDED_KEEP_S
                if drop:
                    out.append(self.meetings.pop(mid))
                    self.gone[mid] = int(now)
            for mid in [k for k, at in self.gone.items() if now - at > GONE_KEEP_S]:
                self.gone.pop(mid, None)
            if out:
                self._save_locked()
        return out


def link_secret(key_bytes, mid, gen):
    """A meeting's guest link secret, DERIVED (never stored): 32 base64url characters from HMAC-SHA256(hub key, id, gen)."""
    import base64
    import hmac
    d = hmac.new(key_bytes, ("kastr-meet-link|%s|%d" % (mid, int(gen))).encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(d[:24]).decode("ascii").rstrip("=")


def link_id(key_bytes, mid, gen):
    import hmac
    return hmac.new(key_bytes, ("kastr-meet-lid|%s|%d" % (mid, int(gen))).encode("ascii"), hashlib.sha256).hexdigest()[:8]


def ics_key(key_bytes, mid, gen):
    """The capability in a meeting's calendar link (a calendar app fetches it without signing in) -- derived, never stored."""
    import hmac
    return hmac.new(key_bytes, ("kastr-meet-ics|%s|%d" % (mid, int(gen))).encode("ascii"), hashlib.sha256).hexdigest()[:32]
