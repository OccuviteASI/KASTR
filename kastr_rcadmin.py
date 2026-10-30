# -*- coding: utf-8 -*-
"""Unattended remote control for FLEET ADMINS (0.21.83, part D).

Kenton (2026-10-23): "I would like to set it up to allow remote control with the admin permissions on a relay/hub/camera
box. This should be opt-in only and a check box in the relay server page allowing remote control without having to ask."
And: "how would I access this from my own KASTR?" -- and later: "When remoted in to an unattended box, allow for switching
to different windows/monitors on the device."

What was decided, and where each part lives:
  * OPT-IN, on the machine itself: "Let fleet admins control this machine without asking" on THAT machine's own Relay page.
    It is set only by a loopback request from the machine's own page (handle_api: loopback, a loopback Origin, a custom
    header a foreign page cannot send without a preflight) and kept in <state>/rcadmin.json. The hub SEES each machine's
    setting (the machine says it in every poll) but nothing in the hub protocol can switch it on. Default off.
  * WHO: fleet admins only -- the admin access code role, verified by the relay that minted the admin's member token (a
    spoke with no admin code of its own asks the hub, kastr_relay._hub_admin_ok) and vouched for to the hub over the spoke's
    federation token. 0.22 maps this to the Entra KASTR-Fleet-Admins group. Room admins and publishers still ask (0.21.79).
  * THE MACHINE polls the hub through the relay it uses (POST /api/rcx/poll at that relay's minter; a spoke forwards to the
    hub): that poll is also how the hub knows the machine is online, opted in, who is signed in (a desktop), its monitors and
    whether KASTR runs as administrator there. Each machine holds a random 32-byte KEY (rcadmin.json) the hub pins on first
    sight (TOFU, sent once on the hub's "enroll"); every poll / claim / end carries an HMAC with it, so nobody can speak for
    the machine, and a different key is refused while the pinned one was heard from within the last hour.
  * CONTROL: an admin's Machines... (More, the Relay popover) lists the opted-in machines fleet-wide (HubRegistry.machines_
    view); Control -> the hub checks the admin claim and the machine's opt-in, mints a session (a random sid, a short pending
    window, rate limits) and wakes the machine's poll; the machine CLAIMS it with its key (the hub's answer carries an HMAC
    the machine checks -- the machine re-verifies the hub-minted session), its relay mints it a token that may put ONLY
    ~rcx/<sid>/{m, s.hang} and get ~rcx/<sid>/a, and it starts a PRIVATE native capture of its desktop under ~rcx/<sid>/s.hang
    (never announced in any room: no room token covers ~rcx, and the admin's relay mints the admin a token that may get only
    ~rcx/<sid>/{m, s.hang} and put ~rcx/<sid>/a). Control is granted at once (kastr_rc.RemoteControl, no prompt): the 0.21.80
    two pointers and the low-latency path apply. A headless KASTR helper page on the machine (rcx-agent.html) carries the MoQ
    side: the admin's in.json -> the loopback WebSocket /api/rc/ws, st.json / ptr.json / src.json back.
  * ON THE MACHINE the red pill names the admin ("<admin> (fleet admin) is controlling this machine -- Stop control
    (Ctrl+Alt+Space)"); anyone there ends it. Every session (who, from where, start, end, duration, why) is audit-logged on the
    machine (<state>/rcadmin-audit.jsonl) and on the hub (<state>/relay-rcx.json, the last AUDIT_MAX; the Relay page's
    Remote sessions table).
  * ADMINISTRATOR WINDOWS behave as in a normal session (Windows keeps a normal process's input and window commands out of
    them): for a Windows machine whose KASTR is not elevated, Machines... and the session view say "Minimize, move, resize and
    close need KASTR to run as administrator on <machine>'s computer" (the controller badge's wording).
  * A machine with nobody signed in (no desktop: a service session, no X display) cannot be captured or controlled by a normal
    process -- Machines... says "nobody is signed in on <machine>" (0.23's service mode is the answer to that).
  * SOURCES (Kenton: "allow for switching to different windows/monitors on the device"): the session view lists the machine's
    monitors (each, and All monitors) and its windows; a pick re-points the private capture in place (kastr_rtsp.Bridge.
    retarget -- the same session, control kept: the grant is re-made for the new target at once), a window share follows the
    window, and Bring to front raises the picked window with normal rights (Windows may refuse; the view says so).
  * 0.21.92 ASKS (Kenton, 2026-10-27: "As an admin logged in, I need an option when right clicking a user to request remote
    control, or take control if it's already allowed in the permissions."): a fleet admin's "Request remote control..." on a
    PERSON's computer. The hub mints an ASK session (no opt-in: the person answers every ask), its note rides that device's
    inbox (the people beats, like a person invite) with a one-time claim key `ck`; the person's KASTR shows Allow / Deny with a
    monitor picker (the main one first, All monitors). Allow -> that KASTR claims the session with `ck` (MACs exactly like an
    opted-in machine's key) and runs the SAME private capture as Machines... -- never announced in any room -- with the pill
    "<admin> is controlling this screen". Deny / no answer in ASK_S -> the admin hears "declined" / "no answer". It never
    polls like an opted-in machine: while it runs, it tells the hub every ASK_SEEN_S that it still does (ask_seen), and hears
    there when the admin ended it. Both logs keep every ask (allowed or not, who, when, how long).
"""
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")

NS = "~rcx"                    # the private namespace: no room token covers it
ALL_MONITORS = 99              # screen://monitor/99 = every monitor at once (kastr_screen.ALL_MONITORS)
POLL_WAIT_S = 25               # a machine's poll is held this long at the hub (a start wakes it at once)
ONLINE_S = 70                  # a machine heard from within this is online
LIST_KEEP_S = 7 * 86400        # an opted-in machine stays listed (offline) this long after its last poll
KEY_KEEP_S = 30 * 86400        # the hub keeps a machine's pinned key this long after its last poll
KEY_REPIN_S = 3600             # a different key is refused while the pinned one was heard from within this
MAC_SKEW_S = 300               # a poll / claim / end stamped further from the hub's clock is refused
PENDING_S = 30                 # a Control the machine has not claimed in this long ends ("no answer")
SESSION_MAX_S = 8 * 3600       # the longest one session lasts (its tokens end with it)
LOST_S = 90                    # a live session whose machine stopped polling this long ends ("lost")
QUIET_S = 10                   # = kastr_rc.LEASE_S: the helper page ends a session whose admin went quiet this long
AUDIT_MAX = 200                # the hub's Remote sessions table
LOCAL_AUDIT_MAX = 500          # the machine's own log (rcadmin-audit.jsonl keeps the newest)
START_RATE_ADMIN = (6, 60)     # Controls one admin may start a minute
START_RATE_MACHINE = (10, 60)  # ... and one machine may be asked for
POLL_RATE = (40, 60)           # polls one machine may make a minute (a held poll is one)
MONITORS_MAX = 16
# A source switch answers at once: with the old capture ending ffmpeg-first (Publisher.quiet) the admin's player finds the new
# broadcast by itself -- lab v02183, 8 switches: picture back in 0.6-1.6 s, none re-subscribed. Waiting for the new capture's
# first output (KASTR_RCX_SWITCH_WAIT=<s>) measured 4.7-5.2 s (ffmpeg's -progress reports every 2 s, then a fresh session).
SWITCH_WAIT_S = float(os.environ.get("KASTR_RCX_SWITCH_WAIT") or 0)
SID_RE = re.compile(r"^[0-9a-f]{32}$")
RCID_RE = re.compile(r"^[a-z0-9]{8,32}$")
HOST_RE = re.compile(r"^[a-z0-9-]{1,32}-[0-9a-f]{4}$")
KEY_RE = re.compile(r"^[0-9a-f]{64}$")
KID_RE = re.compile(r"^[0-9a-f]{16}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SRC_RE = re.compile(r"^screen://(monitor|window)/([0-9]{1,20})$")
# ---- 0.21.92: admin asks (see the docstring)
ASK_S = 60                     # an ask nobody answers ends "noanswer" (the person's prompt counts the same)
ASK_SEEN_S = 5                 # the person's KASTR says its ask session still runs this often (it does not poll)
CK_RE = re.compile(r"^[0-9a-f]{32}$")
WHY_TEXT = {"admin": "the admin ended it", "operator": "the hub's operator ended it", "hotkey": "Ctrl+Alt+Space on the machine",
            "bar": "Stop control on the machine", "stopped": "stopped on the machine", "timeout": "lost touch for 10 s",
            "share": "the capture stopped", "noanswer": "the machine did not answer", "lost": "the machine went quiet",
            "limit": "the 8-hour limit", "off": "the machine's opt-in was switched off", "busy": "someone else controls it",
            "desktop": "nobody is signed in on the machine", "error": "it could not start", "closed": "KASTR closed",
            "released": "the admin gave it back", "retarget": "the capture changed", "restart": "the hub restarted",
            "paused": "the capture was paused", "left": "the admin left",
            "denied": "they declined"}   # 0.21.92: an ask's answer
END_WHYS = tuple(WHY_TEXT)


def _now():
    return time.time()


def _txt(v, n):
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(v or "")).strip()
    return s[:n]


def new_key():
    return os.urandom(32).hex()


def kid_of(key_hex):
    try:
        return hashlib.sha256(bytes.fromhex(str(key_hex))).hexdigest()[:16]
    except ValueError:
        return ""


def mac(key_hex, *parts):
    """HMAC-SHA256 (hex) of the parts joined by "|" with the machine's key."""
    try:
        k = bytes.fromhex(str(key_hex))
    except ValueError:
        return ""
    return hmac.new(k, "|".join(str(p) for p in parts).encode("utf-8"), hashlib.sha256).hexdigest()


def mac_ok(key_hex, got, *parts):
    want = mac(key_hex, *parts)
    return bool(want) and isinstance(got, str) and hmac.compare_digest(want, got)


def paths(sid):
    """The three broadcasts of one session -- the machine's capture, the machine's state, the admin's input."""
    base = NS + "/" + str(sid)
    return {"screen": base + "/s.hang", "machine": base + "/m", "admin": base + "/a"}


def machine_claims(sid, exp, now=None):
    """The machine's session token: put its capture + its state, get the admin's input. Nothing else."""
    now = int(_now() if now is None else now)
    p = paths(sid)
    return {"root": "", "put": [p["machine"], p["screen"]], "get": [p["admin"]], "rcx": sid, "rcxr": "m", "iat": now, "exp": int(exp)}


def admin_claims(sid, exp, now=None):
    """The admin's session token: get the capture + the machine's state, put the input. Nothing else."""
    now = int(_now() if now is None else now)
    p = paths(sid)
    return {"root": "", "put": [p["admin"]], "get": [p["machine"], p["screen"]], "rcx": sid, "rcxr": "a", "iat": now, "exp": int(exp)}


def role_label(mode, relay=""):
    """What the machine is, for Machines...: Hub / Relay / Camera box / App."""
    if relay == "hub":
        return "Hub"
    if relay == "spoke" or mode in ("relay", "publisher-relay"):
        return "Relay" if mode != "publisher-relay" else "Relay + cameras"
    if mode == "publisher":
        return "Camera box"
    return "App" if mode in ("full", "viewer", "") else str(mode)


def admin_windows(platform, elevated):
    """'limited' on a Windows machine whose KASTR is not elevated (Windows keeps a normal process's input out of an
    administrator's windows), else 'full'."""
    return "limited" if str(platform) == "win32" and not elevated else "full"


def pill_text(admin):
    return "%s (fleet admin) is controlling this machine — Stop control (Ctrl+Alt+Space)" % (_txt(admin, 40) or "A fleet admin")


def ask_pill_text(admin):
    """0.21.92: the pill on a person's computer that allowed an admin's ask."""
    return "%s is controlling this screen — Stop control (Ctrl+Alt+Space)" % (_txt(admin, 40) or "An admin")


def monitor_url(mon):
    try:
        n = int(mon)
    except (TypeError, ValueError):
        n = 0
    return "screen://monitor/%d" % max(0, n)


def source_ok(url):
    """A source an admin may point the capture at: a monitor (by index, or ALL_MONITORS) or a window (by id)."""
    return bool(SRC_RE.match(str(url or "")))


def clean_monitors(v):
    out = []
    for m in (v if isinstance(v, list) else [])[:MONITORS_MAX]:
        if not isinstance(m, dict):
            continue
        try:
            idx = int(m.get("index"))
        except (TypeError, ValueError):
            continue
        try:
            w, h = int(m.get("width") or m.get("w") or 0), int(m.get("height") or m.get("h") or 0)
        except (TypeError, ValueError):
            w = h = 0
        out.append({"index": idx, "name": _txt(m.get("name"), 40) or "Screen %d" % (idx + 1), "width": max(0, w), "height": max(0, h),
                    "primary": bool(m.get("primary"))})
    return out


def clean_desktop(v):
    v = v if isinstance(v, dict) else {}
    why = str(v.get("why") or "")
    return {"ok": bool(v.get("ok")), "why": why if why in ("", "nosession", "locked", "wayland", "unsupported", "no-display", "no-x11", "no-xtest") else "unsupported"}


# ---- the machine's own setting ---------------------------------------------------------------------------------------
def settings_path(state_dir):
    return os.path.join(state_dir or ".", "rcadmin.json")


def _read_settings(state_dir):
    """0.21.92: rcadmin.json as stored, its sealed key opened (an old plain one still reads)."""
    import kastr_secret
    try:
        with open(settings_path(state_dir), encoding="utf-8-sig") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d = kastr_secret.open_doc(settings_path(state_dir), d) if isinstance(d, dict) else {}
    return d if isinstance(d, dict) else {}


def load_settings(state_dir):
    """{on, key, since} -- off (and no key) when the file is missing or unreadable."""
    d = _read_settings(state_dir)
    key = str(d.get("key") or "")
    return {"on": d.get("on") is True and bool(KEY_RE.match(key)), "key": key if KEY_RE.match(key) else "",
            "since": int(d.get("since") or 0) if str(d.get("since") or "0").isdigit() else 0}


def save_settings(state_dir, d):
    path = settings_path(state_dir)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    import kastr_secret
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:   # 0.21.92: the key sealed (DPAPI / the owner-only key file)
        json.dump(kastr_secret.seal_doc(path, {"on": bool(d.get("on")), "key": d.get("key") or "", "since": int(d.get("since") or 0)}), f)
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def set_optin(state_dir, on, log=None):
    """The checkbox (THIS machine only -- handle_api guards the caller). The key is made once and kept (unticking and
    ticking again keeps the hub's pin)."""
    s = load_settings(state_dir)
    old_key = str(_read_settings(state_dir).get("key") or "")
    key = s["key"] or (old_key if KEY_RE.match(old_key) else "") or new_key()
    was = s["on"]
    out = {"on": bool(on), "key": key, "since": int(_now()) if (bool(on) and not was) else (s["since"] if on else 0)}
    save_settings(state_dir, out)
    if log and bool(on) != was:
        log("rcx: fleet admins %s control this machine without asking (set on this machine)" % ("may now" if on else "may no longer"))
    return out


# ---- the audit log on the machine --------------------------------------------------------------------------------------
def audit_path(state_dir):
    return os.path.join(state_dir or ".", "rcadmin-audit.jsonl")


def audit_append(state_dir, row):
    path = audit_path(state_dir)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
        if os.path.getsize(path) > 400000:   # keep the newest LOCAL_AUDIT_MAX lines
            rows = audit_read(state_dir, LOCAL_AUDIT_MAX * 2)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                for r in rows[-LOCAL_AUDIT_MAX:]:
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")
            os.replace(path + ".tmp", path)
    except OSError:
        pass


def audit_read(state_dir, n=50):
    try:
        with open(audit_path(state_dir), encoding="utf-8") as f:
            lines = f.readlines()[-max(1, int(n)) * 2:]
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out[-max(1, int(n)):]


def audit_sessions(state_dir, n=50):
    """The machine's log folded per session (a start line, later an end line) -> newest first."""
    rows = {}
    order = []
    for r in audit_read(state_dir, n * 4):
        sid = str(r.get("sid") or "")
        if not sid:
            continue
        if sid not in rows:
            rows[sid] = {}
            order.append(sid)
        rows[sid].update({k: v for k, v in r.items() if k != "ev"})
    return [rows[s] for s in reversed(order)][:n]


# ---- the hub's registry -------------------------------------------------------------------------------------------------
class HubRegistry:
    """The hub's view of every opted-in machine and every unattended session. Machines (and their pinned keys) and the
    audit table are kept in <state>/relay-rcx.json; live sessions are not (a hub restart ends them, "restart")."""

    def __init__(self, state_dir, log=None, clock=None):
        self.state_dir = state_dir
        self.path = os.path.join(state_dir, "relay-rcx.json") if state_dir else None
        self.log = log or (lambda m: None)
        self.clock = clock or _now
        self.cv = threading.Condition(threading.RLock())
        self.machines = {}     # node -> row (with its pinned key)
        self.sessions = {}     # sid -> session
        self.audit = []        # audit rows, newest last (a session's row is updated as it goes)
        self.rates = {}
        self._saved_at = 0.0
        self._load()

    # ---- persistence
    def _load(self):
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8-sig") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        import kastr_secret
        d = kastr_secret.open_doc(self.path, d)   # 0.21.92: the pinned keys are kept sealed
        now = self.clock()
        for node, r in ((d or {}).get("machines") or {}).items():
            if isinstance(r, dict) and HOST_RE.match(str(node)) and KEY_RE.match(str(r.get("key") or "")) and now - float(r.get("at") or 0) < KEY_KEEP_S:
                self.machines[str(node)] = dict(r, node=str(node))
        for r in ((d or {}).get("audit") or [])[-AUDIT_MAX:]:
            if isinstance(r, dict) and SID_RE.match(str(r.get("sid") or "")):
                if r.get("state") in ("pending", "live"):   # it was going when the hub stopped
                    r = dict(r, state="ended", why="restart", end=r.get("end") or (int(now) if r.get("start") else None))
                self.audit.append(r)

    def _save_locked(self, force=True):
        if not self.path:
            return
        now = self.clock()
        if not force and now - self._saved_at < 600:
            return
        self._saved_at = now
        doc = {"machines": {k: {x: y for x, y in v.items() if x != "node"} for k, v in self.machines.items()}, "audit": self.audit[-AUDIT_MAX:]}
        try:
            import kastr_secret
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(kastr_secret.seal_doc(self.path, doc), f)   # 0.21.92: the pinned keys sealed
            if os.name != "nt":
                os.chmod(tmp, 0o600)
            for n in range(5):   # 0.21.96: Windows can hold the old file a moment (a scanner) -- a lost save dropped the newest row
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if n == 4:
                        raise
                    time.sleep(0.05 * (n + 1))
        except OSError as e:
            self.log("rcx: could not write relay-rcx.json: %s" % e)

    # ---- helpers
    def _rate_ok_locked(self, key, n, win, now):
        ts = [t for t in self.rates.get(key, []) if now - t < win]
        if len(ts) >= n:
            self.rates[key] = ts
            return False, int(win - (now - ts[0])) + 1
        self.rates[key] = ts + [now]
        if len(self.rates) > 2048:
            for k in [k for k, v in self.rates.items() if not v or now - v[-1] > 600]:
                self.rates.pop(k, None)
        return True, 0

    def _end_locked(self, s, why, by=""):
        if s["state"] == "ended":
            return False
        now = self.clock()
        was_live = s["state"] == "live"
        s.update(state="ended", endedAt=now, why=why if why in END_WHYS else "stopped", endedBy=_txt(by, 60))
        row = s["row"]
        row.update(state="ended", why=s["why"], endedBy=s["endedBy"])
        if was_live and s.get("liveAt"):
            row.update(end=int(now), dur=int(now - s["liveAt"]))
        self.log("rcx: session %s on %s %s (%s)" % (s["sid"][:8], s["machine"] or s["node"],
                 "ended" if was_live else "did not start", WHY_TEXT.get(s["why"], s["why"])))
        self._save_locked()
        self.cv.notify_all()
        return True

    def sweep(self):
        with self.cv:
            self._sweep_locked(self.clock())

    def _sweep_locked(self, now):
        for s in list(self.sessions.values()):
            if s["state"] == "pending" and now - s["at"] > (ASK_S if s.get("ask") else PENDING_S):   # 0.21.92: an ask waits longer
                if s.get("ask"):
                    s["row"]["answer"] = "none"
                self._end_locked(s, "noanswer")
            elif s["state"] == "live":
                m = self.machines.get(s["node"]) or {}
                if now > s["exp"]:
                    self._end_locked(s, "limit")
                elif s.get("ask"):   # 0.21.92: a person's KASTR does not poll -- its ask_seen keeps the session
                    if now - float(s.get("seen") or s.get("liveAt") or now) > LOST_S:
                        self._end_locked(s, "lost")
                elif now - float(m.get("at") or 0) > LOST_S:
                    self._end_locked(s, "lost")
            elif s["state"] == "ended" and now - s.get("endedAt", now) > 86400:
                self.sessions.pop(s["sid"], None)

    def _busy_locked(self, node):
        return next((s for s in self.sessions.values() if s["node"] == node and s["state"] in ("pending", "live")), None)

    def _items_locked(self, node, now):
        start = [{"sid": s["sid"], "admin": s["admin"], "via": s["adminRelay"], "monitor": s["monitor"], "exp": int(s["exp"])}
                 for s in self.sessions.values() if s["node"] == node and s["state"] == "pending" and not s.get("ask")]   # 0.21.92: never an ask
        stop = [s["sid"] for s in self.sessions.values() if s["node"] == node and s["state"] == "ended" and s.get("liveAt")
                and not s.get("ack") and not s.get("ask") and now - s.get("endedAt", now) < 300]
        return start, stop

    def dead(self, sid):
        """Is this session over (the relay re-checks a session token against it)?"""
        with self.cv:
            s = self.sessions.get(str(sid))
            return bool(s) and s["state"] == "ended"

    # ---- the machine's side
    def poll(self, p, via="", ip="", wait=True):
        """POST /api/rcx/poll from a machine (here, or through a spoke). -> (reply, code)."""
        p = p if isinstance(p, dict) else {}
        if p.get("ask"):   # 0.21.92: a person's KASTR running an ask session says it still does (ask_seen)
            return self.ask_seen(p)
        node = str(p.get("node") or "")
        if not HOST_RE.match(node):
            return {"ok": False, "error": "node required"}, 400
        now = self.clock()
        try:
            ts = int(p.get("ts"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "ts required"}, 400
        if abs(now - ts) > MAC_SKEW_S:
            return {"ok": False, "error": "this machine's clock is off by %d s -- set its time" % int(ts - now), "clock": True}, 401
        kid = str(p.get("kid") or "")
        with self.cv:
            row = self.machines.get(node)
            key = None
            if row and row.get("key"):
                if kid != row.get("kid"):
                    if now - float(row.get("at") or 0) < KEY_REPIN_S:
                        return {"ok": False, "keyConflict": True,
                                "error": "this machine's key changed -- the hub keeps the one it knows while it was heard from in the last hour"}, 409
                    newk = str(p.get("key") or "")
                    if not (KEY_RE.match(newk) and kid_of(newk) == kid):
                        return {"ok": False, "enroll": True, "error": "send the key"}, 401
                    key = newk
                    self.log("rcx: %s has a new key (the old one was last heard from %d min ago)" % (node, int(now - float(row.get("at") or 0)) // 60))
                else:
                    key = row["key"]
            else:
                newk = str(p.get("key") or "")
                if not (KEY_RE.match(newk) and kid_of(newk) == kid):
                    return {"ok": False, "enroll": True, "error": "send the key"}, 401
                key = newk
            if not mac_ok(key, p.get("mac"), "poll", node, ts, "1" if p.get("on") else "0"):
                return {"ok": False, "error": "the poll does not check"}, 401
            ok, wait_s = self._rate_ok_locked(("poll", node), POLL_RATE[0], POLL_RATE[1], now)
            if not ok:
                return {"ok": False, "error": "too many polls", "retryAfter": wait_s}, 429
            first = row is None or row.get("key") != key
            was_on = bool(row and row.get("on"))
            new = dict(row or {})
            new.update(node=node, key=key, kid=kid, at=now, ip=_txt(ip, 64), via=_txt(via, 40), on=bool(p.get("on")),
                       name=_txt(p.get("name"), 60), hostname=_txt(p.get("hostname"), 64), user=_txt(p.get("user"), 32),
                       mode=_txt(p.get("mode"), 24), relay=p.get("relay") if p.get("relay") in ("hub", "spoke") else "",
                       relayName=_txt(p.get("relayName"), 40), version=_txt(p.get("version"), 24), platform=_txt(p.get("platform"), 24),
                       desktop=clean_desktop(p.get("desktop")), monitors=clean_monitors(p.get("monitors")),
                       elevated=bool(p.get("elevated")), busy=_txt(p.get("busy"), 60))
            new.setdefault("first", now)
            sig = (new.get("on"), new.get("version"), new.get("name"), new.get("hostname"), new.get("via"), json.dumps(new.get("monitors")))
            old_sig = (row or {}).get("_sig")
            new["_sig"] = list(sig)
            self.machines[node] = new
            if first or was_on != new["on"] or old_sig != list(sig):
                if was_on != new["on"]:
                    self.log("rcx: %s (%s) %s fleet admins to control it without asking" % (new["hostname"] or new["name"] or node, node,
                             "now allows" if new["on"] else "no longer allows"))
                self._save_locked()
            else:
                self._save_locked(force=False)
            if not new["on"]:
                for s in list(self.sessions.values()):   # switched off: whatever was going on there ends
                    if s["node"] == node and s["state"] in ("pending", "live"):
                        self._end_locked(s, "off")
                start, stop = self._items_locked(node, now)
                return {"ok": True, "on": False, "stop": stop}, 200
            self._sweep_locked(now)
            start, stop = self._items_locked(node, now)
            if wait and not start and not stop and not first and was_on:   # a new machine / a fresh tick hears "listed" at once
                try:
                    w = max(0.0, min(float(POLL_WAIT_S if p.get("wait") is None else p.get("wait")), float(POLL_WAIT_S)))
                except (TypeError, ValueError):
                    w = float(POLL_WAIT_S)
                end_at = time.monotonic() + w
                while True:
                    left = end_at - time.monotonic()
                    if left <= 0:
                        break
                    self.cv.wait(min(left, 5.0))
                    now = self.clock()
                    self._sweep_locked(now)
                    start, stop = self._items_locked(node, now)
                    if start or stop:
                        break
                cur = self.machines.get(node)
                if cur is not None:
                    cur["at"] = max(float(cur.get("at") or 0), self.clock())   # a held poll is a live machine
            return {"ok": True, "on": True, "known": True, "start": start, "stop": stop}, 200

    def claim(self, p):
        """POST /api/rcx/claim: the machine takes the session it was woken for (its key proves it is that machine). The
        answer carries `check` = HMAC(key, ok|sid|rcid|exp|admin): the machine verifies the hub minted this session."""
        p = p if isinstance(p, dict) else {}
        node, sid = str(p.get("node") or ""), str(p.get("sid") or "")
        if not HOST_RE.match(node) or not SID_RE.match(sid):
            return {"ok": False, "error": "node and sid required"}, 400
        now = self.clock()
        try:
            ts = int(p.get("ts"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "ts required"}, 400
        with self.cv:
            s = self.sessions.get(sid)
            if s is not None and s.get("ask"):   # 0.21.92: an ask -- the person's KASTR proves it with the ask's claim key
                return self._ask_claim_locked(s, p, node, sid, ts, now)
            row = self.machines.get(node)
            if not row or not row.get("key") or abs(now - ts) > MAC_SKEW_S or not mac_ok(row["key"], p.get("mac"), "claim", sid, node, ts):
                return {"ok": False, "error": "the claim does not check"}, 401
            self._sweep_locked(now)
            if not s or s["node"] != node:
                return {"ok": False, "error": "no such session for this machine"}, 404
            if s["state"] == "ended":
                return {"ok": False, "error": "that session is over (%s)" % WHY_TEXT.get(s["why"], s["why"]), "why": s["why"]}, 410
            if not row.get("on"):
                self._end_locked(s, "off")
                return {"ok": False, "error": "this machine does not allow it any more", "why": "off"}, 409
            if s["state"] == "pending":
                s.update(state="live", liveAt=now)
                s["row"].update(state="live", start=int(now))
                self.log("rcx: %s (fleet admin, %s) is controlling %s (%s, session %s)" % (s["admin"], s["adminFrom"], s["machine"] or node, node, sid[:8]))
                self._save_locked()
                self.cv.notify_all()
            return {"ok": True, "sid": sid, "rcid": s["rcid"], "admin": s["admin"], "adminHost": s["adminHost"], "adminFrom": s["adminFrom"],
                    "color": s["color"], "monitor": s["monitor"], "exp": int(s["exp"]), "kind": s["kind"],
                    "check": mac(row["key"], "ok", sid, s["rcid"], int(s["exp"]), s["admin"])}, 200

    def machine_end(self, p):
        """POST /api/rcx/end from the machine: its session ended there (Stop control, Ctrl+Alt+Space, the lease, ...)."""
        p = p if isinstance(p, dict) else {}
        node, sid, why = str(p.get("node") or ""), str(p.get("sid") or ""), str(p.get("why") or "stopped")
        if not HOST_RE.match(node) or not SID_RE.match(sid):
            return {"ok": False, "error": "node and sid required"}, 400
        now = self.clock()
        try:
            ts = int(p.get("ts"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "ts required"}, 400
        with self.cv:
            s0 = self.sessions.get(sid)
            if s0 is not None and s0.get("ask"):   # 0.21.92: the person said no / did not answer / their session ended there
                if s0["node"] != node or abs(now - ts) > MAC_SKEW_S or not mac_ok(s0["ck"], p.get("mac"), "end", sid, node, ts, why):
                    return {"ok": False, "error": "the end does not check"}, 401
                s0["ack"] = True
                if s0["state"] == "pending":   # the audit row says the answer (Allow is set by the claim)
                    s0["row"]["answer"] = "denied" if why == "denied" else "none" if why == "noanswer" else why
                self._end_locked(s0, why, by=s0.get("person") or node)
                return {"ok": True, "sid": sid, "state": "ended", "why": s0["why"]}, 200
            row = self.machines.get(node)
            if not row or abs(now - ts) > MAC_SKEW_S or not mac_ok(row.get("key") or "", p.get("mac"), "end", sid, node, ts, why):
                return {"ok": False, "error": "the end does not check"}, 401
            s = self.sessions.get(sid)
            if not s or s["node"] != node:
                return {"ok": False, "error": "no such session for this machine"}, 404
            s["ack"] = True
            self._end_locked(s, why, by=row.get("hostname") or node)
            return {"ok": True, "sid": sid, "state": "ended", "why": s["why"]}, 200

    # ---- the admin's side
    def start(self, node, monitor=None, who=None):
        """A fleet admin (vouched for by its relay) or the hub's operator asks to control `node`. -> (reply, code)."""
        who = who if isinstance(who, dict) else {}
        node = str(node or "")
        now = self.clock()
        if not HOST_RE.match(node):
            return {"ok": False, "error": "which machine?"}, 400
        host = str(who.get("host") or "")
        if not HOST_RE.match(host):
            return {"ok": False, "error": "this KASTR is too old to control a machine -- update it first"}, 400
        with self.cv:
            self._sweep_locked(now)
            row = self.machines.get(node)
            name = (row or {}).get("hostname") or (row or {}).get("name") or node
            if not row or not row.get("on"):
                return {"ok": False, "error": "%s does not allow fleet admins to control it without asking" % name, "why": "off"}, 403
            if now - float(row.get("at") or 0) > ONLINE_S:
                return {"ok": False, "error": "%s is offline" % name, "why": "offline"}, 409
            dk = row.get("desktop") or {}
            if not dk.get("ok"):
                msg = {"locked": "the screen is locked on %s" % name, "wayland": "%s runs a Wayland desktop -- remote control needs X11" % name,
                       "no-display": "KASTR on %s runs without a desktop display (no DISPLAY) -- start it from the signed-in desktop" % name,
                       "no-x11": "the X11 libraries are missing on %s (install libx11-6 and libxtst6)" % name,
                       "no-xtest": "the X server on %s has no XTest (install libxtst6)" % name,
                       "unsupported": "%s cannot be controlled remotely" % name}.get(dk.get("why"), "nobody is signed in on %s" % name)
                return {"ok": False, "error": msg, "why": "desktop"}, 409
            cur = self._busy_locked(node)
            if cur is not None:
                return {"ok": False, "error": "%s is connected to %s now" % (cur["admin"], name), "why": "busy", "by": cur["admin"]}, 409
            if row.get("busy"):
                return {"ok": False, "error": "%s is being controlled by %s (asked in a room)" % (name, row["busy"]), "why": "busy"}, 409
            ok, w = self._rate_ok_locked(("start", host), START_RATE_ADMIN[0], START_RATE_ADMIN[1], now)
            if not ok:
                return {"ok": False, "error": "too many Control requests -- wait a minute", "retryAfter": w}, 429
            ok, w = self._rate_ok_locked(("startm", node), START_RATE_MACHINE[0], START_RATE_MACHINE[1], now)
            if not ok:
                return {"ok": False, "error": "%s was asked too often -- wait a minute" % name, "retryAfter": w}, 429
            mons = [m["index"] for m in row.get("monitors") or []]
            try:
                mon = int(monitor) if monitor is not None and str(monitor) != "" else None
            except (TypeError, ValueError):
                mon = None
            if mon is None or (mon != ALL_MONITORS and mons and mon not in mons):
                mon = next((m["index"] for m in row.get("monitors") or [] if m.get("primary")), mons[0] if mons else 0)
            sid, rcid = os.urandom(16).hex(), os.urandom(8).hex()
            admin = _txt(who.get("name"), 40) or host
            frm = " · ".join(x for x in (_txt(who.get("relay"), 40), _txt(who.get("ip"), 64)) if x)
            color = str(who.get("color") or "") if COLOR_RE.match(str(who.get("color") or "")) else "#009fda"
            arow = {"sid": sid, "node": node, "machine": name, "site": row.get("via") or "", "admin": admin, "adminHost": host,
                    "from": frm, "kind": "operator" if who.get("kind") == "operator" else "admin", "monitor": mon, "at": int(now),
                    "state": "pending", "start": None, "end": None, "dur": None, "why": ""}
            s = {"sid": sid, "rcid": rcid, "node": node, "machine": name, "admin": admin, "adminHost": host, "adminRelay": _txt(who.get("relay"), 40),
                 "adminFrom": frm or "?", "kind": arow["kind"], "color": color, "monitor": mon, "at": now, "exp": now + SESSION_MAX_S,
                 "state": "pending", "row": arow}
            self.sessions[sid] = s
            self.audit.append(arow)
            del self.audit[:-AUDIT_MAX]
            self.log("rcx: %s (%s) asks to control %s (%s) -- session %s" % (admin, frm or host, name, node, sid[:8]))
            self._save_locked()
            self.cv.notify_all()
            return {"ok": True, "sid": sid, "rcid": rcid, "exp": int(s["exp"]), "monitor": mon, "machine": self._public(row, now)}, 200

    def stop(self, sid, who=None, why="admin"):
        who = who if isinstance(who, dict) else {}
        with self.cv:
            s = self.sessions.get(str(sid))
            if not s:
                return {"ok": False, "error": "no such session"}, 404
            was = s["state"]
            self._end_locked(s, why if why in ("admin", "operator", "released", "left", "closed") else "admin", by=who.get("name") or "")
            out = {"ok": True, "sid": s["sid"], "state": s["state"], "why": s["why"]}
            if s.get("ask") and was == "pending":   # 0.21.92: the admin withdrew the ask -- the person's prompt closes (its inbox)
                out["_cancel"] = {"to": s["node"], "note": {"id": "rcx-x-" + s["sid"], "kind": "rcx", "sid": s["sid"], "x": "cancel",
                                                            "by": s["admin"], "from": s["adminHost"]}}
            return out, 200

    def status(self, sid):
        with self.cv:
            self._sweep_locked(self.clock())
            s = self.sessions.get(str(sid))
            if not s:
                return {"ok": False, "error": "no such session"}, 404
            return {"ok": True, "sid": s["sid"], "state": s["state"], "why": s.get("why") or "", "whyText": WHY_TEXT.get(s.get("why") or "", ""),
                    "at": int(s["at"]), "liveAt": int(s["liveAt"]) if s.get("liveAt") else None, "exp": int(s["exp"]),
                    "ask": bool(s.get("ask")), "wait": ASK_S if s.get("ask") else PENDING_S}, 200   # 0.21.92: + ask

    # ---- 0.21.92: an admin asks a PERSON's KASTR (no opt-in: the person answers)
    def ask(self, node, person=None, who=None):
        """A fleet admin (vouched for by its relay) asks `node` -- a person's computer -- for remote control. -> (reply, code);
        the reply's "_note" is the person's inbox note (the caller delivers it and never hands it to the admin)."""
        who = who if isinstance(who, dict) else {}
        node = str(node or "")
        now = self.clock()
        if not HOST_RE.match(node):
            return {"ok": False, "error": "who? (their device)"}, 400
        host = str(who.get("host") or "")
        if not HOST_RE.match(host):
            return {"ok": False, "error": "this KASTR is too old to ask -- update it first"}, 400
        if host == node:
            return {"ok": False, "error": "that is your own computer"}, 400
        name = _txt(person, 40) or node
        with self.cv:
            self._sweep_locked(now)
            cur = self._busy_locked(node)
            if cur is not None:
                msg = ("%s is connected to %s now" if cur["state"] == "live" else "%s is asking %s already") % (cur["admin"], name)
                return {"ok": False, "error": msg, "why": "busy", "by": cur["admin"]}, 409
            ok, w = self._rate_ok_locked(("start", host), START_RATE_ADMIN[0], START_RATE_ADMIN[1], now)
            if not ok:
                return {"ok": False, "error": "too many remote control requests -- wait a minute", "retryAfter": w}, 429
            ok, w = self._rate_ok_locked(("startm", node), START_RATE_MACHINE[0], START_RATE_MACHINE[1], now)
            if not ok:
                return {"ok": False, "error": "%s was asked too often -- wait a minute" % name, "retryAfter": w}, 429
            sid, rcid, ck = os.urandom(16).hex(), os.urandom(8).hex(), os.urandom(16).hex()
            admin = _txt(who.get("name"), 40) or host
            frm = " · ".join(x for x in (_txt(who.get("relay"), 40), _txt(who.get("ip"), 64)) if x)
            color = str(who.get("color") or "") if COLOR_RE.match(str(who.get("color") or "")) else "#009fda"
            arow = {"sid": sid, "node": node, "machine": name, "site": "", "admin": admin, "adminHost": host, "from": frm, "kind": "admin",
                    "ask": True, "monitor": None, "at": int(now), "state": "pending", "start": None, "end": None, "dur": None, "why": ""}
            s = {"sid": sid, "rcid": rcid, "node": node, "machine": name, "person": name, "admin": admin, "adminHost": host,
                 "adminRelay": _txt(who.get("relay"), 40), "adminFrom": frm or "?", "kind": "admin", "color": color, "monitor": None,
                 "at": now, "exp": now + SESSION_MAX_S, "state": "pending", "row": arow, "ask": True, "ck": ck, "seen": None}
            self.sessions[sid] = s
            self.audit.append(arow)
            del self.audit[:-AUDIT_MAX]
            self.log("rcx: %s (%s) asks %s (%s) for remote control -- session %s" % (admin, frm or host, name, node, sid[:8]))
            self._save_locked()
            self.cv.notify_all()
            note = {"id": "rcx-" + sid, "kind": "rcx", "sid": sid, "ck": ck, "by": admin, "from": host, "exp": int(now + ASK_S)}
            return {"ok": True, "sid": sid, "rcid": rcid, "exp": int(s["exp"]), "ask": True, "wait": ASK_S,
                    "machine": {"node": node, "name": name, "hostname": name, "role": "Person", "monitors": [], "adminWindows": "full",
                                "online": True, "site": ""},
                    "_note": note}, 200

    def _ask_claim_locked(self, s, p, node, sid, ts, now):
        """The person allowed: their KASTR claims the ask with its claim key (and says which monitor they picked)."""
        if s["node"] != node or abs(now - ts) > MAC_SKEW_S or not mac_ok(s["ck"], p.get("mac"), "claim", sid, node, ts):
            return {"ok": False, "error": "the claim does not check"}, 401
        self._sweep_locked(now)
        if s["state"] == "ended":
            return {"ok": False, "error": "that request is over (%s)" % WHY_TEXT.get(s["why"], s["why"]), "why": s["why"]}, 410
        if s["state"] == "pending":
            try:
                mon = int(p.get("monitor"))
            except (TypeError, ValueError):
                mon = 0
            if mon < 0 or (mon >= 64 and mon != ALL_MONITORS):
                mon = 0
            s.update(state="live", liveAt=now, seen=now, monitor=mon)
            s["row"].update(state="live", start=int(now), monitor=mon, answer="allowed")
            self.log("rcx: %s allowed %s (admin, %s) to control their screen (%s, session %s)" % (s["person"], s["admin"], s["adminFrom"], node, sid[:8]))
            self._save_locked()
            self.cv.notify_all()
        return {"ok": True, "sid": sid, "rcid": s["rcid"], "admin": s["admin"], "adminHost": s["adminHost"], "adminFrom": s["adminFrom"],
                "color": s["color"], "monitor": s["monitor"], "exp": int(s["exp"]), "kind": s["kind"], "ask": True,
                "check": mac(s["ck"], "ok", sid, s["rcid"], int(s["exp"]), s["admin"])}, 200

    def ask_seen(self, p):
        """POST /api/rcx/poll {ask, node, sid, ts, mac} from a person's KASTR running an ask session: it still runs (the hub
        ends it "lost" after LOST_S without one) -- and the answer says when the admin ended it."""
        p = p if isinstance(p, dict) else {}
        node, sid = str(p.get("node") or ""), str(p.get("sid") or p.get("ask") or "")
        if not HOST_RE.match(node) or not SID_RE.match(sid):
            return {"ok": False, "error": "node and sid required"}, 400
        now = self.clock()
        try:
            ts = int(p.get("ts"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "ts required"}, 400
        with self.cv:
            s = self.sessions.get(sid)
            if not s or not s.get("ask") or s["node"] != node or abs(now - ts) > MAC_SKEW_S or not mac_ok(s["ck"], p.get("mac"), "seen", sid, node, ts):
                return {"ok": False, "error": "the poll does not check", "gone": not s}, 401
            ok, wait_s = self._rate_ok_locked(("askseen", node), POLL_RATE[0], POLL_RATE[1], now)
            if not ok:
                return {"ok": False, "error": "too many polls", "retryAfter": wait_s}, 429
            self._sweep_locked(now)
            if s["state"] == "live":
                s["seen"] = now
            return {"ok": True, "sid": sid, "state": s["state"], "why": s.get("why") or ""}, 200

    def _public(self, r, now, nicks=None):
        live = self._busy_locked(r["node"])
        on = now - float(r.get("at") or 0) <= ONLINE_S
        return {"node": r["node"], "name": r.get("name") or "", "nick": (nicks or {}).get(r["node"], ""), "hostname": r.get("hostname") or "",
                "user": r.get("user") or "", "mode": r.get("mode") or "", "relay": r.get("relay") or "", "relayName": r.get("relayName") or "",
                "role": role_label(r.get("mode"), r.get("relay")), "site": r.get("via") or "", "version": r.get("version") or "",
                "platform": r.get("platform") or "", "online": on, "at": int(r.get("at") or 0), "desktop": r.get("desktop") or {"ok": False, "why": ""},
                "monitors": r.get("monitors") or [], "elevated": bool(r.get("elevated")),
                "adminWindows": admin_windows(r.get("platform"), r.get("elevated")),
                "busy": (live["admin"] if live else "") or r.get("busy") or "",
                "session": {"sid": live["sid"][:8], "admin": live["admin"], "state": live["state"], "since": int(live.get("liveAt") or live["at"])} if live else None}

    def machines_view(self, nicks=None):
        """Opted-in machines (online first) for Machines... and the Relay page -- never a key."""
        now = self.clock()
        with self.cv:
            self._sweep_locked(now)
            rows = [self._public(r, now, nicks) for r in self.machines.values() if r.get("on") and now - float(r.get("at") or 0) < LIST_KEEP_S]
        return sorted(rows, key=lambda r: (not r["online"], (r["nick"] or r["hostname"] or r["name"] or r["node"]).lower()))

    def audit_view(self, n=AUDIT_MAX):
        with self.cv:
            self._sweep_locked(self.clock())
            return [dict(r) for r in reversed(self.audit[-max(1, int(n)):])]


# ---- the machine's agent ------------------------------------------------------------------------------------------------
BROWSER = [None]   # kastr.py sets a callable -> the Chromium to run the helper page with (the bundled one first)


def browser_path():
    env = os.environ.get("KASTR_RCX_BROWSER")
    if env and os.path.exists(env):
        return env
    fn = BROWSER[0]
    if callable(fn):
        try:
            p = fn()
            if p:
                return p
        except Exception:
            pass
    try:
        import kastr_browser
        here = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
        return kastr_browser.bundled_exe(here)
    except Exception:
        return None


_PROBE_LOCK = threading.Lock()
_PROBE = {}   # what -> (at, value): the display probes, one thread at a time and at most every few seconds


def _cached(what, ttl, fn):
    with _PROBE_LOCK:
        hit = _PROBE.get(what)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        try:
            v = fn()
        except Exception:
            v = None
        _PROBE[what] = (time.monotonic(), v)
        return v


def desktop_state():
    """{ok, why}: can a normal process on this machine capture and control its desktop now? (Probed at most every 3 s.)"""
    return dict(_cached("desktop", 3.0, _desktop_state) or {"ok": False, "why": "unsupported"})


def _desktop_state():
    if LINUX:
        try:
            import kastr_x11
            ok, why = kastr_x11.available()
        except Exception:
            ok, why = False, "no-display"
        if ok:
            try:
                import kastr_screen
                if not kastr_screen.available():
                    return {"ok": False, "why": "unsupported"}
            except Exception:
                return {"ok": False, "why": "unsupported"}
            return {"ok": True, "why": ""}
        # 0.21.86 (Kenton: a Linux relay said "nobody is signed in" -- every X11 reason was folded into that): the real reason
        return {"ok": False, "why": why if why in ("wayland", "no-display", "no-x11", "no-xtest") else "nosession"}
    if WINDOWS:
        try:
            import ctypes
            sess = ctypes.c_uint32()
            if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sess)) and sess.value == 0:
                return {"ok": False, "why": "nosession"}   # a service: session 0 has no desktop anyone sees
            d = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0001)
            if not d:
                return {"ok": False, "why": "locked"}
            ctypes.windll.user32.CloseDesktop(ctypes.c_void_p(d))
        except Exception:
            return {"ok": False, "why": "unsupported"}
        return {"ok": True, "why": ""}
    return {"ok": False, "why": "unsupported"}


def is_elevated():
    if not WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def list_monitors():
    def probe():
        import kastr_screen
        src = kastr_screen.sources()
        return clean_monitors(src.get("screens") or []) if src.get("ok") else []
    return list(_cached("monitors", 10.0, probe) or [])


def _http_json(url, body, timeout):
    """POST JSON -> (dict, code); (None, 0) when nothing answered."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
            return (d if isinstance(d, dict) else {}), (getattr(r, "status", None) or 200)
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:
            d = {}
        return (d if isinstance(d, dict) else {}), e.code
    except Exception:
        return None, 0


class Agent:
    """The machine's side: polls the hub while opted in, claims a session, runs the private capture + the grant + the
    headless helper page, ends it (and says so to the hub and in the machine's own log)."""

    def __init__(self, state_dir, bridge=None, relay_url=None, relay_srv=None, log=None, node=None, web_port=None, info=None,
                 http=None, clock=None, launch=None, rc=None):
        self.state_dir = state_dir
        self.bridge = bridge
        self.relay_url = relay_url or (lambda: "")
        self.relay_srv = relay_srv
        self.log = log or (lambda m: None)
        self.node = node
        self.web_port = web_port or (lambda: None)
        self.info = info or (lambda: {})
        self.http = http or _http_json
        self.clock = clock or _now
        self.launch = launch or self._launch_page
        self._rc = rc
        self.session = None
        self.last = {"state": "", "error": "", "at": 0, "via": "", "base": ""}
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._poke = threading.Event()
        self._enroll = False
        self._told_on = False
        self._said = {}
        self._thread = None

    # ---- plumbing
    def _say(self, key, msg, every=600):
        now = self.clock()
        if now - self._said.get(key, 0) > every:
            self._said[key] = now
            self.log(msg)

    def node_id(self):
        if self.node:
            return self.node() if callable(self.node) else self.node
        import kastr_serve
        return kastr_serve.host_slug()

    def rc(self):
        if self._rc is not None:
            return self._rc
        import kastr_rc
        return kastr_rc.get(kastr_rc.bridge_info(self.bridge), self.log, kastr_rc.bridge_mode(self.bridge))

    def bases(self):
        """(media base, minter) of the relay this KASTR uses, or (None, None)."""
        relay = ""
        try:
            relay = self.relay_url() or ""
        except Exception:
            relay = ""
        if not relay:
            return None, None
        try:
            import kastr_rtsp
            parts, _why = kastr_rtsp._relay_base(relay)
        except Exception:
            parts = None
        if not parts:
            return None, None
        base, minter = parts
        try:   # this machine's own relay: its minter on loopback (the relay page names it by its LAN address)
            from urllib.parse import urlparse
            h = (urlparse(minter).hostname or "").lower()
            rs = self.relay_srv
            if rs is not None and rs.running() and h not in ("127.0.0.1", "localhost", "::1"):
                import kastr_serve
                if h in kastr_serve._own_hosts() and str(urlparse(minter).port) == str(int(rs.port) + 1):
                    minter = "http://127.0.0.1:%d" % (int(rs.port) + 1)
        except Exception:
            pass
        return base, minter

    def relay_role(self):
        rs = self.relay_srv
        try:
            if rs is None or not rs.running():
                return ""
            return "spoke" if rs.is_spoke() else "hub"
        except Exception:
            return ""

    def poll_body(self, s, on=True):
        node = self.node_id()
        ts = int(self.clock())
        inf = {}
        try:
            inf = self.info() or {}
        except Exception:
            inf = {}
        body = {"node": node, "ts": ts, "kid": kid_of(s["key"]), "on": bool(on), "wait": POLL_WAIT_S if on else 0,
                "mac": mac(s["key"], "poll", node, ts, "1" if on else "0")}
        if self._enroll:
            body["key"] = s["key"]
        if on:
            sess = self.session
            busy = ""
            try:
                g = self.rc().grant
                if g and not (sess and g.get("rcid") == sess.get("rcid")):
                    busy = g.get("name") or "someone"
            except Exception:
                busy = ""
            try:
                import kastr_serve
                ver = kastr_serve.read_version()
            except Exception:
                ver = ""
            rn = ""
            try:
                rn = self.relay_srv.relay_name() if self.relay_srv is not None else ""
            except Exception:
                rn = ""
            body.update(name=_txt(inf.get("operator"), 60), hostname=_txt(_hostname(), 64), user=_txt(_osuser(), 32),
                        mode=_txt(inf.get("mode"), 24), relay=self.relay_role(), relayName=rn, version=ver, platform=sys.platform,
                        desktop=desktop_state(), monitors=list_monitors(), elevated=is_elevated(), busy=busy)
        return body

    # ---- the loop
    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="kastr-rcx-agent", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._poke.set()
        sess = self.session
        if sess and sess.get("sid"):
            self.end_session(sess["sid"], "closed")

    def poke(self):
        self._poke.set()

    def tell_off(self):
        """The box was unticked: the hub hears it now (the loop's own poll may be held at the hub for up to POLL_WAIT_S)."""
        def run():
            s = load_settings(self.state_dir)
            base, minter = self.bases()
            if s["on"] or not s["key"] or not minter:
                return
            d, code = self.http(minter + "/api/rcx/poll", self.poll_body(s, on=False), 10)
            if code == 200:
                self._told_on = False
            self.last.update(state="off", error="", at=int(self.clock()))
        threading.Thread(target=run, name="kastr-rcx-off", daemon=True).start()

    def _wait(self, s):
        self._poke.clear()
        self._poke.wait(s)
        return self._stop.is_set()

    def _loop(self):
        backoff = 5
        while not self._stop.is_set():
            try:
                backoff = self.tick(backoff)
            except Exception as e:
                self._say("loop", "rcx: agent: %s" % e, 300)
                backoff = 30
            if backoff and self._wait(backoff):
                return

    def tick(self, backoff=5):
        """One round: -> seconds to wait before the next (0 = at once)."""
        s = load_settings(self.state_dir)
        if not s["on"]:
            if self._told_on and s["key"]:
                base, minter = self.bases()
                if minter:
                    self.http(minter + "/api/rcx/poll", self.poll_body(s, on=False), 10)
                self._told_on = False
            sess = self.session
            if sess and sess.get("sid") and not sess.get("ask"):   # 0.21.92: an ask the person allowed is not the opt-in's
                self.end_session(sess["sid"], "off")
            self.last.update(state="off", error="", at=int(self.clock()))
            return 3
        base, minter = self.bases()
        if not minter:
            self.last.update(state="norelay", error="this KASTR uses no relay", at=int(self.clock()))
            return 10
        d, code = self.http(minter + "/api/rcx/poll", self.poll_body(s), POLL_WAIT_S + 15)
        self.last.update(at=int(self.clock()), base=minter)
        if d is None:
            self.last.update(state="down", error="the relay did not answer")
            self._say("down", "rcx: the relay's minter %s did not answer -- trying again" % minter, 600)
            return min(60, max(5, backoff * 2))
        if code == 401 and d.get("enroll"):
            self._enroll = True
            return 0
        if code == 404:
            self.last.update(state="old", error="the relay runs a KASTR older than 0.21.83")
            self._say("old", "rcx: the relay %s runs a KASTR without unattended remote control (0.21.83) -- update it" % minter, 3600)
            return 60
        if code == 409 and d.get("keyConflict"):
            self.last.update(state="key", error=d.get("error") or "key conflict")
            self._say("key", "rcx: the hub refused this machine's key: %s" % d.get("error"), 1800)
            return 60
        if code != 200 or not d.get("ok"):
            self.last.update(state="error", error=str(d.get("error") or ("HTTP %d" % code))[:160])
            self._say("err", "rcx: poll refused (%d): %s" % (code, d.get("error")), 600)
            return 30 if code in (403, 501) else 10
        self._enroll = False
        self._told_on = True
        self.last.update(state="ok", error="", via=str(d.get("via") or ""))
        for sid in d.get("stop") or []:
            cur = self.session
            if cur and cur.get("sid") == sid:
                self.end_session(sid, "admin", tell=True)
            else:
                self._machine_end(sid, "admin", s)   # the hub wants to hear it ended (an ack)
        for st in d.get("start") or []:
            if isinstance(st, dict) and SID_RE.match(str(st.get("sid") or "")):
                threading.Thread(target=self.begin, args=(st,), name="kastr-rcx-begin", daemon=True).start()
        return 0

    # ---- one session
    def _machine_end(self, sid, why, s=None, ck=None):
        """Tell the hub a session ended here -- with the machine's key, or (0.21.92) an ask's claim key `ck`."""
        if not ck:
            s = s or load_settings(self.state_dir)
        base, minter = self.bases()
        if not minter or not (ck or s["key"]):
            return None
        node, ts = self.node_id(), int(self.clock())
        why = why if why in END_WHYS else "stopped"
        return self.http(minter + "/api/rcx/end", {"node": node, "sid": sid, "ts": ts, "why": why, "mac": mac(ck or s["key"], "end", sid, node, ts, why)}, 10)

    def begin(self, notice):
        sid = str(notice.get("sid") or "")
        with self.lock:
            if self.session is not None:
                self._say("dup" + sid, "rcx: a Control for session %s arrived while another runs -- ignored" % sid[:8], 60)
                return False
            self.session = {"sid": sid, "state": "claiming", "at": self.clock()}
        try:
            return self._begin(sid, notice)
        except Exception as e:
            self.log("rcx: session %s could not start: %s" % (sid[:8], e))
            self._cleanup(why="error", tell=True)
            return False

    def _begin(self, sid, notice):
        s = load_settings(self.state_dir)
        if not s["on"]:
            self._cleanup(why="off", tell=True)
            return False
        base, minter = self.bases()
        node, ts = self.node_id(), int(self.clock())
        d, code = self.http(minter + "/api/rcx/claim", {"node": node, "sid": sid, "ts": ts, "mac": mac(s["key"], "claim", sid, node, ts)}, 15)
        if d is None or code != 200 or not d.get("ok") or not d.get("token"):
            self.log("rcx: session %s: the claim was refused (%s: %s)" % (sid[:8], code, (d or {}).get("error")))
            with self.lock:
                self.session = None
            return False
        rcid, admin, exp = str(d.get("rcid") or ""), str(d.get("admin") or ""), int(d.get("exp") or 0)
        if not mac_ok(s["key"], d.get("check"), "ok", sid, rcid, exp, admin) or not RCID_RE.match(rcid):
            self.log("rcx: session %s: the hub's answer does not check with this machine's key -- refused" % sid[:8])
            self._cleanup(why="error", tell=True)
            return False
        return self._run(sid, d, base)[0]

    def _run(self, sid, d, base, ck=None):
        """The hub's claim answer checked: the private capture, the grant, the helper page, the logs. ck = an ask's claim key
        (0.21.92: a person allowed an admin's ask) -- else an opted-in machine's session. -> (ok, why)."""
        rcid, admin, exp = str(d.get("rcid") or ""), str(d.get("admin") or ""), int(d.get("exp") or 0)
        dk = desktop_state()
        if not dk["ok"]:
            self.log("rcx: session %s: nobody is signed in here (%s) -- nothing to show" % (sid[:8], dk["why"]))
            self._cleanup(why="desktop", tell=True)
            return False, "desktop"
        if self.bridge is None:
            self._cleanup(why="error", tell=True)
            return False, "error"
        pp = paths(sid)
        relay = base + ("" if base.endswith("/relay") else "/") + "?jwt=" + str(d["token"])
        url = monitor_url(d.get("monitor"))
        with self.lock:
            self.session.update(state="starting", rcid=rcid, admin=admin, adminHost=str(d.get("adminHost") or ""),
                                adminFrom=str(d.get("adminFrom") or ""), color=str(d.get("color") or "#009fda"), exp=exp, url=url,
                                relay=relay, paths=pp, pk=os.urandom(16).hex(), feed=None, proc=None, n=0, switching=False,
                                monitor=d.get("monitor"), kind=str(d.get("kind") or "admin"), ask=bool(ck), ck=ck or "")   # 0.21.92: + ask
        try:
            feed = self.bridge.add_private(url, sid)
        except Exception as e:
            self.log("rcx: session %s: the capture of %s could not start: %s" % (sid[:8], url, e))
            fallback = monitor_url(0)
            if url == fallback:
                raise
            feed = self.bridge.add_private(fallback, sid)
            url = fallback
        with self.lock:
            self.session.update(feed=feed.id, url=url)
        pub = self.bridge.publish(feed.id, pp["screen"], relay, audio=False, keep=False, label="Remote session")
        pub.minter = (lambda r=relay: r)   # the session token covers exactly this path, for the whole session
        if getattr(pub, "suspended", False):   # the box's camera switch is off: not a reason to show the admin nothing
            pub.suspended = False
            pub.start()
        ok, why = self._grant()
        if not ok:
            self._cleanup(why=why or "busy", tell=True)
            return False, why or "busy"
        proc = self.launch(sid, self.session["pk"])
        with self.lock:
            self.session.update(proc=proc, state="live", started=self.clock())
        audit_append(self.state_dir, {"ev": "start", "sid": sid, "admin": admin, "adminHost": self.session["adminHost"],
                                      "from": self.session["adminFrom"], "kind": "ask" if ck else self.session["kind"], "monitor": d.get("monitor"),
                                      "start": int(self.clock()), "state": "live"})
        if ck:   # 0.21.92
            self.log("rcx: %s (admin, %s) is controlling this screen -- asked, and allowed here (session %s, %s)" % (admin, self.session["adminFrom"], sid[:8], url))
        else:
            self.log("rcx: %s (fleet admin, %s) is controlling this machine (session %s, %s)" % (admin, self.session["adminFrom"], sid[:8], url))
        threading.Thread(target=self._watch, args=(sid,), name="kastr-rcx-watch", daemon=True).start()
        if ck:   # 0.21.92: an ask session does not poll -- it tells the hub it still runs, and hears there when the admin ended it
            threading.Thread(target=self._ask_beat, args=(sid,), name="kastr-rcx-askbeat", daemon=True).start()
        return True, ""

    def _grant(self):
        sess = self.session
        rc = self.rc()
        out, code = rc.start(sess["rcid"], sess["adminHost"], sess["admin"], sess["feed"], share=sess["paths"]["screen"],
                             color=sess["color"], bar=(ask_pill_text if sess.get("ask") else pill_text)(sess["admin"]))   # 0.21.92: an ask's own words
        if code != 200:
            self.log("rcx: session %s: control could not start: %s" % (sess["sid"][:8], out.get("error")))
            return False, out.get("why") or "busy"
        return True, ""

    def _watch(self, sid):
        """The grant is the session on this machine: when it ends (Stop control, Ctrl+Alt+Space, the lease, the capture),
        the session ends."""
        while not self._stop.is_set():
            time.sleep(0.5)
            sess = self.session
            if not sess or sess.get("sid") != sid:
                return
            if sess.get("switching"):
                continue
            try:
                rc = self.rc()
                g = rc.grant
            except Exception:
                return
            if g is None or g.get("rcid") != sess.get("rcid"):
                le = getattr(rc, "last_end", None) or {}
                why = le.get("why") if le.get("rcid") == sess.get("rcid") else "stopped"
                self.end_session(sid, why or "stopped", tell=True)
                return
            if self.clock() > float(sess.get("exp") or 0):
                self.end_session(sid, "limit", tell=True)
                return

    def end_session(self, sid, why, tell=True):
        sess = self.session
        if not sess or sess.get("sid") != sid:
            return False
        self._cleanup(why=why, tell=tell)
        return True

    def _cleanup(self, why="stopped", tell=True):
        with self.lock:
            sess, self.session = self.session, None
        if not sess:
            return
        sid = sess.get("sid") or ""
        try:
            rc = self.rc()
            if rc.grant and rc.grant.get("rcid") == sess.get("rcid"):
                rc.end(sess.get("rcid"), why)
        except Exception:
            pass
        if sess.get("feed") is not None and self.bridge is not None:
            try:
                self.bridge.remove_private(sess["feed"])
            except Exception as e:
                self.log("rcx: the private capture did not stop cleanly: %s" % e)
        p = sess.get("proc")
        if p is not None:
            try:
                p.kill()
            except Exception:
                pass
        if tell:
            try:
                self._machine_end(sid, why, ck=sess.get("ck") or None)   # 0.21.92: an ask's claim key
            except Exception:
                pass
        if sess.get("state") in ("live", "starting"):
            st = float(sess.get("started") or sess.get("at") or self.clock())
            audit_append(self.state_dir, {"ev": "end", "sid": sid, "end": int(self.clock()), "dur": int(self.clock() - st), "why": why, "state": "ended"})
            self.log("rcx: session %s ended (%s)" % (sid[:8], WHY_TEXT.get(why, why)))

    # ---- the helper page and its requests
    def _launch_page(self, sid, pk):
        exe = browser_path()
        port = self.web_port() if callable(self.web_port) else self.web_port
        if not exe or not port:
            self.log("rcx: no browser (or web port) for the session's helper page -- the admin sees the screen but cannot control it")
            return None
        prof = os.path.join(self.state_dir, "rcx-agent-profile")
        args = [exe, "--headless=new", "--user-data-dir=" + prof, "--no-first-run", "--no-default-browser-check", "--mute-audio",
                "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
                "--autoplay-policy=no-user-gesture-required", "--window-size=640,480"]
        try:
            import kastr_browser
            if "browser" in os.path.normcase(exe):
                args.append("--test-type=gpu")
        except Exception:
            pass
        if LINUX and hasattr(os, "geteuid") and os.geteuid() == 0:
            args.append("--no-sandbox")   # Chromium refuses its sandbox as root (crbug.com/638180); it loads only this page
        args.append("http://127.0.0.1:%d/rcx-agent.html#s=%s&k=%s" % (int(port), sid, pk))
        env = dict(os.environ)
        try:
            p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            self.log("rcx: the helper page could not start: %s" % e)
            return None
        try:
            import kastr_rtsp
            kastr_rtsp._job_assign(kastr_rtsp.app_job(self.log), p, self.log)   # dies with KASTR
        except Exception:
            pass
        return p

    def page_session(self, sid, pk):
        """GET /api/rcadmin/session for the helper page: what it needs, once it proves it is the page this agent opened."""
        sess = self.session
        if not sess or sess.get("sid") != sid or not pk or not hmac.compare_digest(str(sess.get("pk") or ""), str(pk)):
            return {"ok": False, "error": "no such session"}, 404
        return {"ok": True, "sid": sid, "rcid": sess["rcid"], "relay": sess["relay"], "paths": sess["paths"], "admin": sess["admin"],
                "adminHost": sess["adminHost"], "color": sess["color"], "url": sess["url"], "feed": sess["feed"], "exp": sess["exp"],
                "machine": _hostname(), "quiet": QUIET_S}, 200

    def sources(self, thumbs=False):
        """The machine's monitors (each + All monitors) and windows for the admin's source switcher."""
        try:
            import kastr_screen
            with _PROBE_LOCK:   # one display probe of this module at a time
                src = kastr_screen.sources()
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        if not src.get("ok"):
            return {"ok": False, "error": src.get("reason") or "no native capture here"}
        mons = clean_monitors(src.get("screens") or [])
        own = set()
        try:
            own = {int(self.session["proc"].pid)} if self.session and self.session.get("proc") is not None else set()
        except Exception:
            own = set()
        wins = []
        for w in (src.get("windows") or [])[:40]:
            try:
                hwnd = int(w.get("hwnd"))
            except (TypeError, ValueError):
                continue
            wins.append({"url": "screen://window/%d" % hwnd, "id": "window:%d" % hwnd, "title": _txt(w.get("title"), 80), "app": _txt(w.get("exe"), 40),
                         "minimized": bool(w.get("minimized"))})
        out = {"ok": True, "monitors": [dict(m, url=monitor_url(m["index"]), id="monitor:%d" % m["index"]) for m in mons],
               "windows": wins, "all": len(mons) > 1}
        if thumbs:
            out["thumbs"] = self._thumbs([m["id"] for m in out["monitors"]] + [w["id"] for w in wins[:24]])
        return out

    def _thumbs(self, ids):
        out = {}
        try:
            import base64
            import kastr_screen
        except Exception:
            return out
        for i in ids:
            try:
                t = kastr_screen.thumb(i, 160)
            except Exception:
                t = None
            if t:
                data, mime = t
                if len(data) <= 24000:
                    out[i] = "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))
        return out

    def switch(self, url):
        """Re-point the private capture in place (Bridge.retarget: the same feed and broadcast), then make the grant again
        for the new target -- control is kept, no new session. -> (reply, code)."""
        url = str(url or "")
        if not source_ok(url):
            return {"ok": False, "error": "pick a monitor or a window"}, 400
        sess = self.session
        if not sess or sess.get("state") != "live":
            return {"ok": False, "error": "no session"}, 409
        if url == sess.get("url"):
            return {"ok": True, "url": url, "same": True}, 200
        t0, t_wall = time.monotonic(), time.time()
        pub = (getattr(self.bridge, "_pubs", None) or {}).get(sess["feed"])
        with self.lock:
            sess["switching"] = True
        try:
            try:
                self.bridge.retarget(sess["feed"], url)
            except ValueError as e:
                return {"ok": False, "error": str(e)}, 409
            sess["url"] = url
            self._private_overlay(sess)
            ok, why = self._grant()
            if not ok:
                self.end_session(sess["sid"], why or "retarget", tell=True)
                return {"ok": False, "error": "control could not be kept on the new source", "ended": why}, 409
        finally:
            with self.lock:
                sess["switching"] = False
        # optionally (KASTR_RCX_SWITCH_WAIT) the answer waits for the NEW capture's first output (its ffmpeg's -progress)
        live = None
        if pub is not None and hasattr(pub, "flowingAt") and SWITCH_WAIT_S > 0:
            live = False
            while time.monotonic() - t0 < SWITCH_WAIT_S:
                fa = getattr(pub, "flowingAt", None)
                if fa and fa >= t_wall:
                    live = True
                    break
                time.sleep(0.05)
        ms = int((time.monotonic() - t0) * 1000)
        self.log("rcx: session %s now shows %s (%d ms%s)" % (sess["sid"][:8], url, ms, "" if live is None else (", capture live" if live else ", no output yet")))
        return {"ok": True, "url": url, "ms": ms, "live": live}, 200

    def _private_overlay(self, sess):
        """Windows: the share's bar of a private capture ends the SESSION (retarget put back the plain share bar)."""
        if not WINDOWS:
            return
        try:
            import kastr_screen
            fid, sid = sess["feed"], sess["sid"]
            kastr_screen.overlay_stop(fid)
            kastr_screen.overlay_start(fid, sess["url"], on_stop=lambda s=sid: self.end_session(s, "bar", tell=True))
        except Exception:
            pass

    def front(self, url=None):
        """Bring a window to the front on this machine with normal rights. -> (reply, code)."""
        sess = self.session
        url = str(url or (sess or {}).get("url") or "")
        m = SRC_RE.match(url)
        if not m or m.group(1) != "window":
            return {"ok": False, "error": "only a window comes to the front"}, 400
        hwnd = int(m.group(2))
        try:
            rc = self.rc()
            with rc.lock:
                b = rc._backend()
                if WINDOWS and getattr(b, "name", "") == "windows":   # the real injector (never a test's or a lab's mock)
                    import ctypes
                    u32 = ctypes.windll.user32
                    if not u32.IsWindow(hwnd):
                        return {"ok": False, "error": "that window is gone"}, 404
                    if u32.IsIconic(hwnd):
                        u32.ShowWindow(hwnd, 9)   # SW_RESTORE
                b.raise_target(url)
                front = bool(b.focus_is(url))
        except Exception as e:
            return {"ok": False, "error": "could not bring it to the front: %s" % str(e)[:120]}, 500
        if not front:
            return {"ok": False, "front": False, "error": "Windows refused to bring that window to the front (another app holds the focus)" if WINDOWS
                    else "the window manager did not bring that window to the front"}, 200
        return {"ok": True, "front": True}, 200

    # ---- 0.21.92: an admin's ask on THIS computer (the person's page asks; nothing here runs without their Allow)
    def ask_info(self, monitors=True):
        """GET /api/rcadmin/ask: what the Allow prompt shows -- this computer's monitors, whether its desktop can be shared, and
        whether someone controls it already. monitors=False (?probe=1, the page's capability check every 30 s): no screen
        listing at all."""
        busy = ""
        try:
            g = self.rc().grant
            if g:
                busy = g.get("name") or "someone"
        except Exception:
            busy = ""
        sess = self.session
        if sess and not busy:
            busy = sess.get("admin") or "someone"
        live = {"sid": sess["sid"], "admin": sess.get("admin") or ""} if sess and sess.get("ask") and sess.get("state") == "live" else None
        return {"ok": True, "monitors": list_monitors() if monitors else [], "desktop": desktop_state(), "busy": busy, "platform": sys.platform,
                "all": ALL_MONITORS, "wait": ASK_S, "session": live}

    def answer_ask(self, sid, ck, answer, monitor=None, by=""):
        """POST /api/rcadmin/ask {sid, ck, answer: allow | deny | timeout, monitor?, by?} from this computer's own page (the
        person's click). Allow -> the claim at the hub (with the ask's claim key), then the private capture + the grant exactly
        like Machines... -> (reply, code)."""
        sid, ck, answer = str(sid or ""), str(ck or ""), str(answer or "")
        if not SID_RE.match(sid) or not CK_RE.match(ck):
            return {"ok": False, "error": "bad request"}, 400
        if answer not in ("allow", "deny", "timeout", "stop"):
            return {"ok": False, "error": "answer: allow | deny | timeout | stop"}, 400
        if answer == "stop":   # the page's own Stop control (its in-page bar) -- only for the ask it allowed
            sess = self.session
            if not sess or sess.get("sid") != sid or not hmac.compare_digest(str(sess.get("ck") or ""), ck):
                return {"ok": False, "error": "no such session"}, 404
            self.end_session(sid, "bar", tell=True)
            return {"ok": True}, 200
        by = _txt(by, 40) or "An admin"
        base, minter = self.bases()
        if not minter:
            return {"ok": False, "error": "this KASTR uses no relay"}, 409
        if answer != "allow":
            why = "denied" if answer == "deny" else "noanswer"
            try:
                self._machine_end(sid, why, ck=ck)
            except Exception:
                pass
            audit_append(self.state_dir, {"ev": "ask", "sid": sid, "admin": by, "kind": "ask", "at": int(self.clock()), "state": "ended", "why": why})
            self.log("rcx: %s asked to control this screen -- %s" % (by, "declined here" if why == "denied" else "no answer here"))
            return {"ok": True, "answer": answer}, 200
        dk = desktop_state()
        if not dk["ok"]:
            self._machine_end(sid, "desktop", ck=ck)
            return {"ok": False, "error": "this screen cannot be shared now (%s)" % (dk.get("why") or "no desktop"), "why": "desktop"}, 409
        with self.lock:
            busy = self.session is not None
            if not busy:
                self.session = {"sid": sid, "state": "claiming", "at": self.clock(), "ask": True, "ck": ck}
        if busy:
            self._machine_end(sid, "busy", ck=ck)
            return {"ok": False, "error": "another remote session runs on this computer", "why": "busy"}, 409
        node, ts = self.node_id(), int(self.clock())
        try:
            mon = int(monitor)
        except (TypeError, ValueError):
            mon = 0
        try:
            d, code = self.http(minter + "/api/rcx/claim", {"node": node, "sid": sid, "ts": ts, "monitor": mon, "mac": mac(ck, "claim", sid, node, ts)}, 15)
            if d is None or code != 200 or not d.get("ok") or not d.get("token"):
                with self.lock:
                    self.session = None
                err = (d or {}).get("error") or ("the relay did not answer" if d is None else "HTTP %d" % code)
                self.log("rcx: ask %s: the claim was refused (%s: %s)" % (sid[:8], code, err))
                return {"ok": False, "error": err, "why": (d or {}).get("why") or ""}, (410 if code == 410 else 409)
            rcid, admin, exp = str(d.get("rcid") or ""), str(d.get("admin") or ""), int(d.get("exp") or 0)
            if not mac_ok(ck, d.get("check"), "ok", sid, rcid, exp, admin) or not RCID_RE.match(rcid):
                self.log("rcx: ask %s: the hub's answer does not check with the ask's key -- refused" % sid[:8])
                self._cleanup(why="error", tell=True)
                return {"ok": False, "error": "the hub's answer does not check -- refused"}, 409
            ok, why = self._run(sid, d, base, ck=ck)
        except Exception as e:
            self.log("rcx: ask %s could not start: %s" % (sid[:8], e))
            self._cleanup(why="error", tell=True)
            return {"ok": False, "error": "it could not start: %s" % str(e)[:120], "why": "error"}, 500
        if not ok:
            return {"ok": False, "error": WHY_TEXT.get(why, "it could not start"), "why": why}, 409
        return {"ok": True, "sid": sid, "admin": admin, "monitor": d.get("monitor")}, 200

    def ask_beat_once(self, sid):
        """One "still running" to the hub for an ask session -> the hub's state ("live", "ended", ...) or None. An ended answer
        (the admin stopped, the hub restarted) ends it here."""
        sess = self.session
        if not sess or sess.get("sid") != sid or not sess.get("ck"):
            return None
        base, minter = self.bases()
        if not minter:
            return None
        node, ts = self.node_id(), int(self.clock())
        d, code = self.http(minter + "/api/rcx/poll", {"ask": sid, "node": node, "sid": sid, "ts": ts, "mac": mac(sess["ck"], "seen", sid, node, ts)}, 10)
        if d is None:
            return None
        if code == 200 and d.get("state") == "ended":
            self.end_session(sid, d.get("why") if d.get("why") in END_WHYS else "admin", tell=False)
            return "ended"
        if code == 401 and d.get("gone"):   # the hub no longer knows it (it restarted)
            self.end_session(sid, "restart", tell=False)
            return "ended"
        return d.get("state") if code == 200 else None

    def _ask_beat(self, sid):
        while not self._stop.wait(ASK_SEEN_S):
            sess = self.session
            if not sess or sess.get("sid") != sid:
                return
            try:
                if self.ask_beat_once(sid) == "ended":
                    return
            except Exception as e:
                self._say("askbeat", "rcx: ask %s: %s" % (sid[:8], e), 300)

    def status(self):
        s = load_settings(self.state_dir)
        sess = self.session
        dk = desktop_state()
        return {"ok": True, "on": s["on"], "since": s["since"], "kid": kid_of(s["key"]) if s["key"] else "", "desktop": dk,
                "platform": sys.platform, "elevated": is_elevated(), "adminWindows": admin_windows(sys.platform, is_elevated()),
                "hub": dict(self.last),
                "session": {"sid": sess["sid"][:8], "admin": sess.get("admin") or "", "from": sess.get("adminFrom") or "", "since": int(sess.get("started") or sess.get("at") or 0),
                            "url": sess.get("url") or "", "state": sess.get("state"), "ask": bool(sess.get("ask"))} if sess else None,   # 0.21.92: + ask
                "audit": audit_sessions(self.state_dir, 50)}


def _hostname():
    try:
        import socket
        return socket.gethostname()[:64]
    except Exception:
        return ""


def _osuser():
    try:
        import getpass
        return getpass.getuser()[:32]
    except Exception:
        return ""


_AGENT = [None]
_AGENT_LOCK = threading.Lock()


def get_agent():
    return _AGENT[0]


def start_agent(state_dir, bridge, relay_url, relay_srv=None, log=None, web_port=None, info=None):
    """Once per process (kastr_serve.make_server): the agent idles until the checkbox is ticked."""
    with _AGENT_LOCK:
        if _AGENT[0] is None and state_dir and os.environ.get("KASTR_RCX") != "0":
            _AGENT[0] = Agent(state_dir, bridge=bridge, relay_url=relay_url, relay_srv=relay_srv, log=log, web_port=web_port, info=info).start()
        return _AGENT[0]


# ---- the loopback API on the machine (kastr_serve routes /api/rcadmin*) ----------------------------------------------------
def _guard(handler):
    """This machine's own pages only: loopback (never a forwarded request), a loopback Origin, same-origin fetch metadata."""
    import kastr_relay
    origin = str(handler.headers.get("Origin") or "")
    site = str(handler.headers.get("Sec-Fetch-Site") or "")
    return kastr_relay.is_local(handler) and (not origin or bool(re.match(r"^https?://(127[.]0[.]0[.]1|localhost|\[::1\])(:[0-9]+)?$", origin))) \
        and site in ("", "same-origin", "none")


def handle_api(handler, state_dir, log=None):
    """GET /api/rcadmin -> this machine's setting, its desktop, the hub's last word, its sessions;
    POST /api/rcadmin {on} -> the checkbox (THIS machine only); GET /api/rcadmin/session?sid=&k= -> the helper page's session;
    POST /api/rcadmin/ctl {sid, k, op: sources | src | front | thumbs} -> the source switcher;
    0.21.92: GET /api/rcadmin/ask -> what the Allow prompt shows; POST /api/rcadmin/ask {sid, ck, answer, monitor?, by?} -> the
    person's answer to an admin's ask (this computer's own page only, like the checkbox)."""
    from urllib.parse import parse_qs, urlparse

    def send(code, obj):
        body = json.dumps(obj).encode()
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    path = handler.path.split("?", 1)[0]
    if not _guard(handler):
        try:
            n = int(handler.headers.get("Content-Length") or 0)
            if n:
                handler.rfile.read(min(n, 1 << 20))
        except Exception:
            pass
        return send(403, {"ok": False, "error": "only on this machine itself (open KASTR on it)"})
    agent = get_agent()
    if handler.command == "GET":
        q = parse_qs(urlparse(handler.path).query)
        if path == "/api/rcadmin/session":
            if agent is None:
                return send(404, {"ok": False, "error": "no agent"})
            out, code = agent.page_session((q.get("sid") or [""])[0], (q.get("k") or [""])[0])
            return send(code, out)
        if path == "/api/rcadmin/ask":   # 0.21.92
            if agent is None:
                return send(404, {"ok": False, "error": "remote control is not available in this KASTR"})
            return send(200, agent.ask_info(monitors=(q.get("probe") or [""])[0] != "1"))
        if agent is not None:
            return send(200, agent.status())
        s = load_settings(state_dir)
        return send(200, {"ok": True, "on": s["on"], "since": s["since"], "desktop": desktop_state(), "platform": sys.platform,
                          "elevated": is_elevated(), "adminWindows": admin_windows(sys.platform, is_elevated()), "hub": {}, "session": None,
                          "audit": audit_sessions(state_dir, 50)})
    if handler.headers.get("X-KASTR-RC") != "1":
        return send(403, {"ok": False, "error": "missing X-KASTR-RC"})
    try:
        n = int(handler.headers.get("Content-Length") or 0)
        p = json.loads(handler.rfile.read(min(n, 1 << 20)) or b"{}") if n else {}
    except Exception:
        return send(400, {"ok": False, "error": "body must be JSON"})
    p = p if isinstance(p, dict) else {}
    if path == "/api/rcadmin":
        if not isinstance(p.get("on"), bool):
            return send(400, {"ok": False, "error": "on: true | false"})
        set_optin(state_dir, p["on"], log)
        if agent is not None:
            agent.poke()
            if not p["on"]:
                sess = agent.session
                if sess and sess.get("sid") and not sess.get("ask"):   # 0.21.92: an allowed ask is not the opt-in's
                    agent.end_session(sess["sid"], "off", tell=True)
                agent.tell_off()
            return send(200, agent.status())
        return send(200, {"ok": True, "on": p["on"]})
    if path == "/api/rcadmin/ask":   # 0.21.92: the person's Allow / Deny (or their prompt timing out)
        if agent is None:
            return send(404, {"ok": False, "error": "remote control is not available in this KASTR"})
        out, code = agent.answer_ask(p.get("sid"), p.get("ck"), p.get("answer"), p.get("monitor"), p.get("by"))
        return send(code, out)
    if path == "/api/rcadmin/ctl":
        if agent is None:
            return send(404, {"ok": False, "error": "no agent"})
        sess = agent.session
        if not sess or sess.get("sid") != p.get("sid") or not hmac.compare_digest(str(sess.get("pk") or ""), str(p.get("k") or "")):
            return send(404, {"ok": False, "error": "no such session"})
        op = str(p.get("op") or "")
        if op in ("sources", "thumbs"):
            return send(200, agent.sources(thumbs=op == "thumbs"))
        if op == "src":
            out, code = agent.switch(p.get("url"))
            return send(code, out)
        if op == "front":
            out, code = agent.front(p.get("url"))
            return send(code, out)
        if op == "end":
            why = str(p.get("why") or "stopped")
            agent.end_session(sess["sid"], why if why in END_WHYS else "stopped", tell=True)
            return send(200, {"ok": True})
        return send(400, {"ok": False, "error": "op is sources | thumbs | src | front | end"})
    return send(404, {"ok": False, "error": "unknown endpoint"})
