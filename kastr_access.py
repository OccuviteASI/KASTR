# -*- coding: utf-8 -*-
"""0.21.89 ASK FOR ACCESS -- the hub's desk of knocks on locked doors.

Kenton (2026-10-26): "I would like to add the ability to let someone prompt people in a locked room that lets someone with
permissions in the room already to allow them in without a code." / "Maybe an 'Ask for access' in the same pop-up as the code
entry." Decided:
  * who answers: the room's ADMINS and its CREATOR who are IN the room right now (live presence) -- for a My room, only its
    OWNER while the owner is in it. Nobody of them in the room -> the asker is told so at once ("nobody can let you in");
  * what the admitted person gets: what typing the room code would have given them (their access code's role), never admin --
    in a My room, a guest's seat;
  * how long: this visit only. The grant lives while its holder's page beats from that room (a brief drop or an update
    relaunch is inside IDLE_S); gone longer, or left on purpose (the page forgets it), they ask again or type the code.

This module is the pure part, so the rules are testable without a network: AccessDesk is the HUB's registry (who may answer
and is present, the pending asks, the answers, the grants, the rate limits) and AccessMirror is a SPOKE's copy of what the
hub's bans long-poll carries (the cards its pages show, the states its askers poll). kastr_relay.AuthService wires them to
the minter (/api/access, the beat, /api/token's `admit`) and to the federation (rooms_fed op "access", spoke -> hub, vouched).

The asker's credential is a per-ask KEY (24 random bytes) that only the asker's page ever holds: the hub keeps sha256(key).
After "Let in" the page mints with `admit: "ka-<id>-<key>"`; the hub accepts it only from the asker's own device (host), for
that room, while the grant lives. Nothing secret travels the long-poll (digests and states only)."""
import hashlib
import hmac
import re
import secrets
import threading
import time

ASK_TTL = 120            # s: an ask waits this long for an answer ("No answer -- try again or ask for the code")
PRESENT_S = 20           # s: a page that may let people in counts as IN the room this long after its last beat (pages beat every 4 s)
FWD_S = 8                # s: a spoke forwards one such page's beats to the hub at most this often (a room change at once)
KEEP_FWD_S = 20          # s: a spoke forwards an admitted page's "still here" at most this often
NOBODY_GRACE = 20        # s: an ask whose room has had nobody who can answer this long ends as "nobody"
RATE_PAIR = (3, 60)      # asks one device may send ONE room per minute
RATE_HOST = (6, 60)      # ... and to every room together
RATE_ROOM = (12, 60)     # asks one room takes per minute from everyone together
DECLINE_COOL = 30        # s: after a "no" that device waits this long before asking that room again
REDEEM_S = 120           # s: after "Let in" the asker's page has this long to come in
IDLE_S = 180             # s: an admitted page silent this long (left, KASTR closed) -- the grant is over
GRANT_MAX_S = 12 * 3600  # s: the longest one visit lasts
TOKEN_TTL = 1800         # s: a token minted on a grant (the page re-mints ~10 min before; the grant must still live)
CLOSED_SHOW_S = 30       # s: an answered ask stays on the other answerers' cards ("Ada let them in") this long
KEEP_S = 600             # s: an ended ask's record answers its asker's status this long
PER_ROOM_MAX = 20        # pending asks one room holds at once
PENDING_MAX = 200        # pending asks one hub holds at once
MIRROR_FRESH = 45        # s: a spoke trusts the hub's long-poll copy this long (the long-poll is held up to 30 s)
KINDS = ("admin", "creator", "owner")
STATES = ("pending", "let", "declined", "timeout", "cancelled", "nobody", "ended")
ROLES = ("viewer", "publisher")

ID_RE = re.compile(r"^[0-9a-f]{12}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{32}$")
GRANT_RE = re.compile(r"^ka-([0-9a-f]{12})-([A-Za-z0-9_-]{32})$")
HOST_RE = re.compile(r"^[a-z0-9-]{1,32}-[0-9a-f]{4}$")
SLUG_RE = re.compile(r"^[a-z0-9-]{1,32}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

NOBODY_TEXT = "nobody who can let you in is in this room right now -- ask for the code or an invite link"
REFUSED = {"wrong": "this access grant is not valid -- ask again or enter the room's code",
           "expired": "your access to this room has ended -- ask again or enter the room's code",
           "pending": "nobody has let you in yet",
           "room": "this access grant is for another room"}


def label(v, n=40):
    """A display name as it travels (no markup, one line, at most n)."""
    s = re.sub(r"[<>\"'`\\]", "", " ".join(str(v or "").split()))
    return s[:n]


def digest(key):
    return hashlib.sha256(str(key or "").encode("ascii", "replace")).hexdigest()


def grant_token(aid, key):
    return "ka-%s-%s" % (aid, key)


def device_of(host):
    """A device's short name from its host slug (krisdesk-1a2b -> krisdesk)."""
    h = str(host or "")
    return h.rsplit("-", 1)[0] if HOST_RE.match(h) else ""


def role_cap(role):
    """What a grant may carry: a viewer stays a viewer, everyone else (an admin included) is a publisher at most."""
    return "viewer" if role == "viewer" else "publisher"


def _rate(rate, key, lim, now):
    """-> (ok, retry s). Counts this ask when it fits."""
    n, win = lim
    ts = [t for t in rate.get(key, []) if now - t < win]
    if len(ts) >= n:
        rate[key] = ts
        return False, int(win - (now - ts[0])) + 1
    ts.append(now)
    rate[key] = ts
    return True, 0


class AccessDesk:
    """HUB: who may let people in and is in their room now, the asks, their answers and the grants. Live state only -- a hub
    restart forgets it (a pending ask then times out on the asker's page; a grant ends, which is "this visit only")."""

    def __init__(self, log=None):
        self.lock = threading.Lock()
        self.log = log or (lambda m: None)
        self.present = {}    # room -> {host: {at, name, kind}}
        self.asks = {}       # id -> {id, room, host, name, device, role, personal, at, exp, state, by, ans, dig, to, used, seen, none}
        self.rate = {}       # ("p", host, room) | ("h", host) | ("r", room) -> [when]
        self.cool = {}       # (host, room) -> when that room last said no to that device
        self.ver = 0

    # ---- presence -------------------------------------------------------------------------------------------------------
    @staticmethod
    def _allowed(kind, personal):
        return kind == "owner" if personal else kind in ("admin", "creator")

    def beat(self, room, host, name, kind, personal, now=None):
        """One beat of a page that may let people in (its relay checked the kind). -> True when it is new in that room."""
        now = time.time() if now is None else now
        if not (SLUG_RE.match(str(room)) and HOST_RE.match(str(host)) and self._allowed(kind, personal)):
            return False
        with self.lock:
            for r in list(self.present):
                if r != room and host in self.present[r]:
                    self.present[r].pop(host, None)
                    if not self.present[r]:
                        self.present.pop(r, None)
            hs = self.present.setdefault(room, {})
            old = hs.get(host)
            new = old is None or now - old["at"] > PRESENT_S or old.get("kind") != kind
            hs[host] = {"at": now, "name": label(name), "kind": kind}
            if new:
                self.ver += 1
            return new

    def gone(self, host, room=None):
        """That page left (another room, or closed)."""
        with self.lock:
            for r in list(self.present):
                if (room is None or r == room) and host in self.present[r]:
                    self.present[r].pop(host, None)
                    if not self.present[r]:
                        self.present.pop(r, None)
                    self.ver += 1

    def _eligible_locked(self, room, personal, now):
        return {h: e for h, e in (self.present.get(room) or {}).items()
                if now - e["at"] <= PRESENT_S and self._allowed(e.get("kind"), personal)}

    def eligible(self, room, personal, now=None):
        now = time.time() if now is None else now
        with self.lock:
            return dict(self._eligible_locked(room, personal, now))

    # ---- the asker ----------------------------------------------------------------------------------------------------
    def ask(self, room, host, name, role, personal, device="", now=None):
        """-> (reply, http code). A 429 reply carries `abuse` (the relay counts it toward its lockout)."""
        now = time.time() if now is None else now
        if not (SLUG_RE.match(str(room)) and HOST_RE.match(str(host))):
            return {"ok": False, "error": "bad request"}, 400
        with self.lock:
            t = self.cool.get((host, room))
            if t is not None and now - t < DECLINE_COOL:
                return {"ok": False, "abuse": True, "retryAfter": int(DECLINE_COOL - (now - t)) + 1,
                        "error": "you were not let in a moment ago -- wait a little before asking again"}, 429
            for key, lim in ((("p", host, room), RATE_PAIR), (("h", host), RATE_HOST), (("r", room), RATE_ROOM)):
                n, win = lim
                ts = [x for x in self.rate.get(key, []) if now - x < win]
                if len(ts) >= n:
                    self.rate[key] = ts
                    return {"ok": False, "abuse": True, "retryAfter": int(win - (now - ts[0])) + 1,
                            "error": "too many requests to join -- wait a minute"}, 429
            for key in (("p", host, room), ("h", host), ("r", room)):
                self.rate[key] = [x for x in self.rate.get(key, []) if now - x < 60] + [now]
            # one open ask per device per room: a new one replaces the old (the page reloaded, or asked again)
            for a in self.asks.values():
                if a["host"] == host and a["room"] == room and a["state"] == "pending":
                    a.update(state="cancelled", ans=now, by="")
                    self.ver += 1
            elig = self._eligible_locked(room, personal, now)
            if not elig:
                return {"ok": False, "nobody": True, "error": NOBODY_TEXT}, 409
            live = [a for a in self.asks.values() if a["state"] == "pending"]
            if len(live) >= PENDING_MAX or sum(1 for a in live if a["room"] == room) >= PER_ROOM_MAX:
                return {"ok": False, "retryAfter": 30, "error": "too many people are asking to join right now -- try again shortly"}, 429
            aid = secrets.token_hex(6)
            while aid in self.asks:
                aid = secrets.token_hex(6)
            key = secrets.token_urlsafe(24)   # 32 base64url characters
            self.asks[aid] = {"id": aid, "room": room, "host": host, "name": label(name) or device_of(host) or "Someone",
                              "device": label(device) or device_of(host), "role": role_cap(role), "personal": bool(personal),
                              "at": now, "exp": now + ASK_TTL, "state": "pending", "by": "", "ans": 0.0, "dig": digest(key),
                              "to": set(elig), "used": False, "seen": 0.0, "none": None}
            self.ver += 1
        return {"ok": True, "id": aid, "key": key, "exp": int(now + ASK_TTL), "ttl": ASK_TTL}, 200

    def _mine_locked(self, aid, key):
        a = self.asks.get(str(aid or ""))
        if a is None or not KEY_RE.match(str(key or "")) or not hmac.compare_digest(a["dig"], digest(key)):
            return None
        return a

    @staticmethod
    def _status_of(a):
        out = {"ok": True, "id": a["id"], "state": a["state"]}
        if a["state"] == "pending":
            out["exp"] = int(a["exp"])
        if a["state"] in ("let", "declined") and a.get("by"):
            out["by"] = a["by"]                      # the admitter's display name (Kenton accepts it) -- never who else is in
        if a["state"] == "let":
            out.update(room=a["room"], role=a["role"], personal=a["personal"])
        return out

    def status(self, aid, key, now=None):
        now = time.time() if now is None else now
        self.sweep(now)
        with self.lock:
            a = self._mine_locked(aid, key)
            if a is None:
                return {"ok": False, "error": "no such request"}, 404
            return self._status_of(a), 200

    def cancel(self, aid, key, now=None):
        now = time.time() if now is None else now
        with self.lock:
            a = self._mine_locked(aid, key)
            if a is None:
                return {"ok": False, "error": "no such request"}, 404
            if a["state"] == "pending":
                a.update(state="cancelled", ans=now)
                self.ver += 1
            elif a["state"] == "let":   # let in, then the page said "no thanks" / left before coming in
                a.update(state="ended")
                self.ver += 1
            return {"ok": True, "state": a["state"]}, 200

    # ---- the answer -----------------------------------------------------------------------------------------------------
    def answer(self, aid, room, host, kind, allow, by="", now=None):
        """An answer from the page of (room, host), whose relay checked its member token and says what it is (`kind`). Only
        a page that may let people in (that kind, for THAT room) and is in the room now answers; the first answer wins."""
        now = time.time() if now is None else now
        self.sweep(now)
        with self.lock:
            a = self.asks.get(str(aid or ""))
            if a is None:
                return {"ok": False, "error": "that request is over"}, 404
            if a["room"] != room:
                return {"ok": False, "error": "that request is for another room"}, 403
            if not self._allowed(kind, a["personal"]):
                return {"ok": False, "error": ("only the owner lets people into their room" if a["personal"]
                                               else "only the room's admins or its creator can let people in")}, 403
            e = self._eligible_locked(room, a["personal"], now).get(host)
            if e is None:
                return {"ok": False, "error": "only someone in the room who can let people in answers"}, 403
            if a["state"] != "pending":
                return {"ok": False, "already": a["state"], "by": a.get("by") or "", "name": a["name"],
                        "error": "already answered"}, 409
            who = label(by) or e.get("name") or device_of(host) or "Someone"
            a.update(state="let" if allow else "declined", by=who, byHost=host, ans=now)
            a["to"].add(host)
            if not allow:
                self.cool[(a["host"], room)] = now
            self.ver += 1
            return {"ok": True, "state": a["state"], "name": a["name"]}, 200

    # ---- the grant ------------------------------------------------------------------------------------------------------
    def check(self, token, host, room, now=None):
        """A mint with `admit` -> ("ok", {id, room, role, personal}) | (verdict, None): "wrong" (not one of ours / not this
        device -- a guess), "room" (another room's), "pending" (not let in), "expired" (over)."""
        now = time.time() if now is None else now
        m = GRANT_RE.match(str(token or ""))
        if not m:
            return "wrong", None
        with self.lock:
            a = self._mine_locked(m.group(1), m.group(2))
            if a is None or a["host"] != str(host or ""):
                return "wrong", None
            if a["room"] != room:
                return "room", None
            if a["state"] == "pending":
                return "pending", None
            if a["state"] != "let":
                return "expired", None
            if (now - a["ans"] > GRANT_MAX_S) or (not a["used"] and now - a["ans"] > REDEEM_S) or (a["used"] and now - a["seen"] > IDLE_S):
                a["state"] = "ended"
                self.ver += 1
                return "expired", None
            a["used"], a["seen"] = True, now
            return "ok", {"id": a["id"], "room": a["room"], "role": a["role"], "personal": a["personal"]}

    def keep(self, aid, host, room, now=None):
        """The admitted page beats from that room: its grant lives on."""
        now = time.time() if now is None else now
        with self.lock:
            a = self.asks.get(str(aid or ""))
            if a and a["state"] == "let" and a["used"] and a["host"] == host and a["room"] == room and now - a["seen"] <= IDLE_S:
                a["seen"] = now
                return True
        return False

    # ---- cards for the pages that may answer ----------------------------------------------------------------------------
    @staticmethod
    def _card(a):
        return {"id": a["id"], "name": a["name"], "device": a["device"], "at": int(a["at"]), "exp": int(a["exp"])}

    @staticmethod
    def _closed(a):
        return {"id": a["id"], "state": a["state"], "by": a.get("by") or "", "name": a["name"]}

    def cards(self, host, room, now=None):
        """-> {asks: [pending asks of my room], closed: [asks I was shown that ended a moment ago]} -- only for a page that
        may answer and is in that room now."""
        now = time.time() if now is None else now
        out = {"asks": [], "closed": []}
        with self.lock:
            for a in sorted(self.asks.values(), key=lambda x: x["at"]):
                if a["room"] != room:
                    continue
                if a["state"] == "pending" and now < a["exp"]:
                    if host in self._eligible_locked(room, a["personal"], now):
                        a["to"].add(host)
                        out["asks"].append(self._card(a))
                elif a["state"] != "pending" and host in a["to"] and now - (a["ans"] or a["at"]) <= CLOSED_SHOW_S:
                    out["closed"].append(self._closed(a))
        return out

    # ---- housekeeping + the spokes' copy ----------------------------------------------------------------------------------
    def sweep(self, now=None):
        """Pending asks past ASK_TTL time out; one whose room has had nobody who can answer for NOBODY_GRACE ends as
        "nobody"; old records, rates and cool-downs go. -> anything changed (the long-poll is nudged)."""
        now = time.time() if now is None else now
        changed = False
        with self.lock:
            for r in list(self.present):
                for h in [h for h, e in self.present[r].items() if now - e["at"] > 3 * PRESENT_S]:
                    self.present[r].pop(h, None)
                if not self.present[r]:
                    self.present.pop(r, None)
            for a in self.asks.values():
                if a["state"] == "pending":
                    if now >= a["exp"]:
                        a.update(state="timeout", ans=now)
                        changed = True
                        continue
                    if self._eligible_locked(a["room"], a["personal"], now):
                        a["none"] = None
                    elif a["none"] is None:
                        a["none"] = now
                    elif now - a["none"] >= NOBODY_GRACE:
                        a.update(state="nobody", ans=now)
                        changed = True
                elif a["state"] == "let":
                    if now - a["ans"] > GRANT_MAX_S or (not a["used"] and now - a["ans"] > REDEEM_S) or (a["used"] and now - a["seen"] > IDLE_S):
                        a["state"] = "ended"
                        changed = True
            for k in [k for k, a in self.asks.items() if a["state"] not in ("pending", "let") and now - (a["ans"] or a["at"]) > KEEP_S]:
                self.asks.pop(k, None)
            for k in [k for k, ts in self.rate.items() if not ts or now - ts[-1] > 60]:
                self.rate.pop(k, None)
            for k in [k for k, t in self.cool.items() if now - t > DECLINE_COOL]:
                self.cool.pop(k, None)
            if changed:
                self.ver += 1
        return changed

    def feed(self, now=None):
        """The bans long-poll's `access` for the spokes: the pending asks (with who may answer them now), the asks that ended a
        moment ago (with whom they were shown) and every record's state + key digest (the spokes' askers poll them there)."""
        now = time.time() if now is None else now
        with self.lock:
            pend, closed, states = [], [], {}
            for a in self.asks.values():
                if a["state"] == "pending" and now < a["exp"]:
                    el = self._eligible_locked(a["room"], a["personal"], now)
                    a["to"].update(el)
                    pend.append(dict(self._card(a), room=a["room"], to=sorted(el)))
                elif a["state"] != "pending" and now - (a["ans"] or a["at"]) <= CLOSED_SHOW_S:
                    closed.append(dict(self._closed(a), room=a["room"], to=sorted(a["to"])))
                st = {"state": a["state"], "room": a["room"], "dig": a["dig"], "exp": int(a["exp"])}
                if a["state"] in ("let", "declined"):
                    st["by"] = a.get("by") or ""
                if a["state"] == "let":
                    st.update(role=a["role"], personal=a["personal"])
                states[a["id"]] = st
            return {"ver": self.ver, "at": int(now), "pending": pend, "closed": closed, "states": states}


class AccessMirror:
    """SPOKE: the hub's `access` from the bans long-poll -- cards for this relay's pages, states for its askers."""

    def __init__(self):
        self.lock = threading.Lock()
        self.d = None
        self.at = 0.0

    @staticmethod
    def clean(f):
        if not isinstance(f, dict):
            return None
        out = {"pending": [], "closed": [], "states": {}}
        for x in (f.get("pending") or [])[:PENDING_MAX] if isinstance(f.get("pending"), list) else []:
            if isinstance(x, dict) and ID_RE.match(str(x.get("id") or "")) and SLUG_RE.match(str(x.get("room") or "")):
                try:
                    at, exp = int(x.get("at") or 0), int(x.get("exp") or 0)
                except (TypeError, ValueError):
                    continue
                out["pending"].append({"id": str(x["id"]), "room": str(x["room"]), "name": label(x.get("name")),
                                       "device": label(x.get("device")), "at": at, "exp": exp,
                                       "to": [str(h) for h in (x.get("to") or [])[:64] if HOST_RE.match(str(h))]})
        for x in (f.get("closed") or [])[:PENDING_MAX] if isinstance(f.get("closed"), list) else []:
            if isinstance(x, dict) and ID_RE.match(str(x.get("id") or "")) and x.get("state") in STATES:
                out["closed"].append({"id": str(x["id"]), "room": str(x.get("room") or ""), "state": x["state"],
                                      "by": label(x.get("by")), "name": label(x.get("name")),
                                      "to": [str(h) for h in (x.get("to") or [])[:64] if HOST_RE.match(str(h))]})
        sts = f.get("states") if isinstance(f.get("states"), dict) else {}
        for k, v in list(sts.items())[:2000]:
            if ID_RE.match(str(k)) and isinstance(v, dict) and v.get("state") in STATES and DIGEST_RE.match(str(v.get("dig") or "")):
                s = {"state": v["state"], "room": str(v.get("room") or ""), "dig": str(v["dig"]), "by": label(v.get("by"))}
                if v["state"] == "let":
                    s.update(role=role_cap(v.get("role")), personal=bool(v.get("personal")))
                try:
                    s["exp"] = int(v.get("exp") or 0)
                except (TypeError, ValueError):
                    s["exp"] = 0
                out["states"][str(k)] = s
        return out

    def apply(self, f, now=None):
        c = self.clean(f)
        if c is None:
            return False
        with self.lock:
            self.d, self.at = c, (time.time() if now is None else now)
        return True

    def fresh(self, now=None):
        now = time.time() if now is None else now
        return self.d is not None and now - self.at <= MIRROR_FRESH

    def cards(self, host, room, now=None):
        now = time.time() if now is None else now
        out = {"asks": [], "closed": []}
        with self.lock:
            if self.d is None or now - self.at > MIRROR_FRESH:
                return out
            for x in self.d["pending"]:
                if x["room"] == room and host in x["to"] and now < x["exp"]:
                    out["asks"].append({k: x[k] for k in ("id", "name", "device", "at", "exp")})
            for x in self.d["closed"]:
                if x["room"] == room and host in x["to"]:
                    out["closed"].append({k: x[k] for k in ("id", "state", "by", "name")})
        return out

    def status(self, aid, key, now=None):
        """An asker on this spoke polls here (never the hub). Unknown yet (the long-poll is a moment behind) -> pending."""
        now = time.time() if now is None else now
        aid = str(aid or "")
        if not ID_RE.match(aid) or not KEY_RE.match(str(key or "")):
            return {"ok": False, "error": "no such request"}, 404
        with self.lock:
            s = (self.d or {}).get("states", {}).get(aid) if self.d is not None else None
        if s is None:
            return {"ok": True, "id": aid, "state": "pending", "late": True}, 200
        if not hmac.compare_digest(s["dig"], digest(key)):
            return {"ok": False, "error": "no such request"}, 404
        out = {"ok": True, "id": aid, "state": s["state"]}
        if s["state"] == "pending":
            out["exp"] = s["exp"]
        if s["state"] in ("let", "declined") and s.get("by"):
            out["by"] = s["by"]
        if s["state"] == "let":
            out.update(room=s["room"], role=s.get("role") or "publisher", personal=bool(s.get("personal")))
        return out, 200
