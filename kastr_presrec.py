# -*- coding: utf-8 -*-
"""0.21.92 H (Kenton, 2026-10-28: "Add a toggle for recording the presentation also."): Record the presentation.

WHAT IS RECORDED -- what the audience sees and hears: the live slide with the presenter's camera in the room's presenter mode
(Content / Standout / Side-by-side / Reporter), the slide videos with their sound, the presenters' microphones and the people a
presenter let talk (Ask to speak). Never the notes, the next slide, the presenter view or the audience's cameras.

WHERE -- on the RELAY HOST that holds the deck (the /api/pres store the presenter's page uploaded to; a hand-over keeps the same
deck and the same host). That host's KASTR runs one headless Chromium per recording on its own page, reached as
http://presrec.localhost:<web port>/ -- Chrome resolves *.localhost to loopback, but the Host is not one of the loopback names,
so KASTR serves it as a WEB client: every this-machine-only endpoint refuses it, it dials THIS host's relay (kastr_serve's
_web_relay_for hook) and it joins the deck's room with a grant only this module hands out (the Ask-for-access seam: admit
ka-<id>-<key>). The relay answers that grant with a WATCH-ONLY token whose put list names nothing a page announces, so the
recorder is never in People, never in the room's state and never on the mesh map's members. The page composes the
presentation tile (the share's picture + kastr-pres.js's slide / video / camera layers) at 30 fps, mixes the heard tiles'
sound and MediaRecorder's it (H.264 + AAC MP4 where the browser can, measured in the bundled Chrome for Testing 153) in 2 s
pieces POSTed back here. Measured on the lab box (1080p, Standout + cut-out): the page costs ~44 % of one core just watching,
~63 % recording; ~0.2 Mbit/s for a still slide + camera.

WHY NOT ffmpeg ON THE MoQ TRACKS -- the share stream is the slide alone; the mode layout, the cut-out matte (colour|mask
frames), the Reporter backdrop, the slide videos' spots, who presents now (a hand-over moves the camera to another person) and
whose microphone may be heard all live in the page. An ffmpeg graph would re-implement all of it and restart on every change.

STORAGE -- <state>/presrec/<rid>/: meta.json + part<n>.rec while recording, <n>.mp4 when finished (ffmpeg -c copy
+faststart; the raw fragmented MP4 is kept when ffmpeg is missing or fails). Kept until a presenter or an admin deletes it.
A relay host restart (or a crashed / stalled recorder) keeps the file so far and carries on into part 2, 3, ...

WHO -- the store's tokens decide: the write token (the owner + co-presenters) or the read token (presenters + backstage) may
switch it on / off and download; deleting needs the write token or an admin. Both are kept as SHA-256 here (the deck folder
goes at End), so the files stay reachable after the deck is gone. The audience holds neither and is never told.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

HOST = "presrec.localhost"
RID_RE = re.compile(r"^[0-9a-f]{16}$")
DID_RE = re.compile(r"^[0-9a-f]{32}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
LINUX = sys.platform.startswith("linux")
GB = 1 << 30


def _env_gb(name, dflt):
    try:
        v = float(os.environ.get(name) or dflt)
        return int(v * GB) if v > 0 else int(dflt * GB)
    except ValueError:
        return int(dflt * GB)


MAX_BYTES = _env_gb("KASTR_PRESREC_MAX_GB", 8)       # one recording (every part) -- it stops there, the file is kept
FREE_FLOOR = _env_gb("KASTR_PRESREC_FREE_GB", 2)     # a recording stops when the disk's free space falls under this
TOTAL_MAX = _env_gb("KASTR_PRESREC_TOTAL_GB", 100)   # every kept recording together -- no new one past it
WARN_FRAC = 0.8                                     # presenters are warned from 80 % of MAX_BYTES / free < 2 x the floor
LIVE_MAX = 3                                        # recordings at once on one relay host (each is a headless browser)
STALL_S = 30                                        # no piece this long -> a new recorder, a new part
BOOT_S = 75                                         # ... the first one (the page loads, joins the room, finds the deck)
STOP_WAIT_S = 15                                    # after Stop / End: the recorder's last piece, then it is closed
CHUNK_MAX = 64 << 20
GRANT_TTL = 6 * 3600                                # the recorder's watch token (re-minted with the grant while it records)
RELAUNCH_MAX = 4                                    # recorders started within RELAUNCH_WINDOW_S before it waits
RELAUNCH_WINDOW_S = 120
LISTS_MAX = 200

WHY = {
    "stop": "switched off",
    "ended": "the presentation ended",
    "size": "it reached the size limit for one recording",
    "disk": "the relay host's disk is nearly full",
    "restart": "the relay host restarted",
    "gone": "the presentation is no longer on the relay host",
    "absent": "the presentation was not showing in its room",
}


def _h(s):
    return hashlib.sha256(str(s or "").encode()).hexdigest()


def _eq(a, b):
    return bool(a) and bool(b) and hmac.compare_digest(str(a), str(b))


def _stored_h(stored):
    """A deck's stored token as its SHA-256 hex: 0.21.92 keeps "sha256:<hex>" (kastr_secret.digest), a 0.21.91 deck the plain token."""
    stored = str(stored or "")
    if not stored:
        return ""
    return stored[7:] if stored.startswith("sha256:") else _h(stored)


def _tok_eq(stored, given):
    """A request's token against a deck's stored one (digest or plain) -- constant time."""
    h = _stored_h(stored)
    return bool(h) and bool(given) and hmac.compare_digest(h, _h(given))


def _now_ms():
    return int(time.time() * 1000)


def browser_path():
    """The Chromium a recorder runs on: KASTR_PRESREC_BROWSER (a lab), else the one KASTR runs its other helper pages on."""
    env = os.environ.get("KASTR_PRESREC_BROWSER")
    if env:
        return env if os.path.isfile(env) else None
    try:
        import kastr_rcadmin
        return kastr_rcadmin.browser_path()
    except Exception:
        return None


class Session:
    """One recording while it runs (in memory; its meta.json is the lasting half)."""

    def __init__(self, meta):
        self.meta = meta
        self.rid = meta["rid"]
        self.key = secrets.token_urlsafe(24)            # the recorder page's own key for /hello /chunk /done
        self.gid = secrets.token_hex(6)                 # the room grant (admit ka-<gid>-<gkey>)
        self.gkey = secrets.token_urlsafe(24)[:32]
        self.nonce = ""                                 # the one-use boot link of the current launch
        self.proc = None
        self.part = 0
        self.seq = 0
        self.last = 0.0                                 # the last piece (or the launch)
        self.launches = []
        self.stopping = False
        self.stop_at = 0.0
        self.done_part = 0
        self.finishing = False
        self.dur = {}                                   # part -> ms recorded (the page says)
        self.why_wait = ""                              # why no recorder runs now (shown to presenters)


class PresRec:
    def __init__(self, state_dir, relay=None, web_port=None, ffmpeg=None, note=None, launch=None, clock=None, free=None):
        self.state_dir = state_dir
        self.root = os.path.join(state_dir, "presrec")
        os.makedirs(self.root, exist_ok=True)
        self.relay = relay
        self.web_port = web_port
        self.ffmpeg = ffmpeg
        self.note = note or (lambda *a: None)
        self.launch = launch            # tests: a stub; None -> the real headless browser
        self.clock = clock or time.time
        self.free = free                # tests: a stub for the disk's free bytes
        self.lock = threading.RLock()
        self.live = {}                  # rid -> Session
        self._stop = threading.Event()
        self._thread = None

    # ---- the deck store's tokens -------------------------------------------------------------------------------------
    def _deck(self, did):
        if not DID_RE.match(did or ""):
            return None
        try:
            with open(os.path.join(self.state_dir, "pres", did, "meta.json"), encoding="utf-8") as f:
                m = json.load(f)
            return m if isinstance(m, dict) else None
        except (OSError, ValueError):
            return None

    def who(self, did, k):
        """'presenter' (the write token), 'backstage' (the read token) or None."""
        m = self._deck(did)
        if not m or not k:
            return None
        if _tok_eq(m.get("token"), k):
            return "presenter"
        if _tok_eq(m.get("rtoken"), k):
            return "backstage"
        return None

    # ---- files --------------------------------------------------------------------------------------------------------
    def _dir(self, rid):
        return os.path.join(self.root, rid)

    def _load(self, rid):
        if not RID_RE.match(rid or ""):
            return None
        try:
            with open(os.path.join(self._dir(rid), "meta.json"), encoding="utf-8") as f:
                m = json.load(f)
            return m if isinstance(m, dict) else None
        except (OSError, ValueError):
            return None

    def _save(self, meta):
        p = os.path.join(self._dir(meta["rid"]), "meta.json")
        tmp = p + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        for k in range(5):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                time.sleep(0.05 * (k + 1))
        os.replace(tmp, p)

    def _all(self):
        out = []
        try:
            names = os.listdir(self.root)
        except OSError:
            return out
        for rid in names:
            m = self._load(rid)
            if m:
                out.append(m)
        return out

    def _free_bytes(self):
        if self.free is not None:
            return self.free()
        try:
            return shutil.disk_usage(self.root).free
        except OSError:
            return 1 << 62

    def _total_bytes(self):
        return sum(int(m.get("size") or 0) for m in self._all())

    # ---- what a presenter's switch asks ------------------------------------------------------------------------------
    def unavailable(self):
        """Why this relay host cannot record now ("" = it can)."""
        r = self.relay
        if r is None or not callable(getattr(r, "running", None)) or not r.running():
            return "the relay on the relay host is not running"
        if not getattr(r, "secured", False):
            return "recording needs access codes on the relay (Relay page) -- an open relay would show the recorder to everyone"
        if self.launch is None and not browser_path():
            return "the relay host has no browser to record with"
        return ""

    def _live_for(self, did):
        for s in self.live.values():
            if s.meta.get("deck") == did and not s.stopping:
                return s
        return None

    def start(self, did, k, name="", by_name=""):
        who = self.who(did, k)
        if not who:
            return 403, {"error": "only the presenters and backstage can record this presentation"}
        with self.lock:
            s = self._live_for(did)
            if s:
                return 200, self._state(s, who)
            why = self.unavailable()
            if why:
                return 409, {"error": why}
            if sum(1 for x in self.live.values() if not x.stopping) >= LIVE_MAX:
                return 429, {"error": "the relay host is already recording %d presentations -- try again when one ends" % LIVE_MAX}
            free = self._free_bytes()
            if free < 2 * FREE_FLOOR:
                return 507, {"error": "the relay host's disk has only %.1f GB free -- not enough to record" % (free / GB)}
            tot = self._total_bytes()
            if tot >= TOTAL_MAX:
                return 507, {"error": "the kept recordings fill the %d GB this relay host keeps for them -- delete some first" % (TOTAL_MAX // GB)}
            deck = self._deck(did) or {}
            rid = secrets.token_hex(8)
            os.makedirs(self._dir(rid), exist_ok=True)
            meta = {"v": 1, "rid": rid, "deck": did, "room": str(deck.get("room") or "")[:64],
                    "name": str(name or deck.get("name") or "Presentation")[:120], "at": _now_ms(), "end": 0,
                    "by": who, "byName": str(by_name or "")[:60], "state": "rec", "why": "", "warn": "", "size": 0, "parts": [],
                    "tokH": _stored_h(deck.get("token")), "rtH": _stored_h(deck.get("rtoken")), "dk": secrets.token_urlsafe(18)}
            self._save(meta)
            s = Session(meta)
            self.live[rid] = s
            self.note("presrec: recording %s started (%s)" % (rid, who))
            self._launch(s)
            return 200, self._state(s, who)

    def stop(self, did, k, why="stop"):
        who = self.who(did, k)
        if not who:
            return 403, {"error": "only the presenters and backstage can stop the recording"}
        with self.lock:
            s = self._live_for(did)
            if s:
                self._stopping(s, why)
        return 200, {"on": False, "deck": did}

    def deck_ended(self, did):
        """kastr_pres's End (the deck left the store): every recording of it finishes."""
        with self.lock:
            for s in list(self.live.values()):
                if s.meta.get("deck") == did and not s.stopping:
                    self._stopping(s, "ended")

    def _stopping(self, s, why):
        s.stopping = True
        s.stop_at = self.clock()
        s.meta["why"] = why
        if why in ("size", "disk"):
            s.meta["warn"] = "Recording stopped: " + WHY[why] + "."
        try:
            self._save(s.meta)
        except OSError:
            pass
        self.note("presrec: recording %s stopping (%s)" % (s.rid, WHY.get(why, why)))

    def state(self, did, k):
        who = self.who(did, k)
        if not who:
            return 403, {"error": "not a presenter of this presentation"}
        with self.lock:
            s = self._live_for(did)
            if s:
                return 200, self._state(s, who)
            last = None
            for m in self._all():
                if m.get("deck") == did and (last is None or m.get("at", 0) > last.get("at", 0)):
                    last = m
            out = {"on": False, "deck": did, "can": self.unavailable() == ""}
            why = self.unavailable()
            if why:
                out["why"] = why
            if last:
                out.update(last={"id": last["rid"], "state": last.get("state"), "why": WHY.get(last.get("why"), ""),
                                 "warn": last.get("warn") or "", "at": last.get("at"), "end": last.get("end")})
            return 200, out

    def _state(self, s, who):
        m = s.meta
        out = {"on": True, "deck": m["deck"], "id": s.rid, "at": m["at"], "el": max(0, _now_ms() - int(m["at"])), "size": m.get("size", 0),
               "part": s.part, "can": True, "by": m.get("by")}   # el: how long it has run (the relay host's clock -- pages use this)
        warn = m.get("warn") or ""
        if not warn and m.get("size", 0) >= WARN_FRAC * MAX_BYTES:
            warn = "The recording is nearly at its size limit (%d GB) -- it stops there." % (MAX_BYTES // GB)
        if not warn and self._free_bytes() < 2 * FREE_FLOOR:
            warn = "The relay host's disk is nearly full -- the recording stops at %d GB free." % (FREE_FLOOR // GB)
        if s.why_wait:
            warn = warn or s.why_wait
        if warn:
            out["warn"] = warn
        return out

    # ---- the recorder page -------------------------------------------------------------------------------------------
    def _launch(self, s):
        """Start the next part's recorder (the lock is held)."""
        why = self.unavailable()
        if why:
            s.why_wait = "Recording paused: " + why + "."
            return False
        t = self.clock()
        s.launches = [x for x in s.launches if t - x < RELAUNCH_WINDOW_S]
        if len(s.launches) >= RELAUNCH_MAX:
            s.why_wait = "The recorder keeps stopping on the relay host -- it tries again shortly."
            return False
        s.launches.append(t)
        s.part = max([s.part] + [int(p.get("n") or 0) for p in s.meta.get("parts", [])] + self._part_numbers(s.rid)) + 1
        s.seq = 0
        s.nonce = secrets.token_urlsafe(18)
        s.last = t
        s.why_wait = ""
        url = "http://%s:%d/api/presrec/%s/boot?n=%s" % (HOST, int(self._port() or 0), s.rid, s.nonce)
        try:
            s.proc = (self.launch or self._launch_browser)(s, url)
        except Exception as e:
            self.note("presrec: the recorder could not start: %s" % e)
            s.proc = None
        if s.proc is None:
            s.why_wait = "The recorder could not start on the relay host."
            return False
        self.note("presrec: recorder for %s part %d started" % (s.rid, s.part))
        return True

    def _port(self):
        p = self.web_port
        return p() if callable(p) else p

    def _launch_browser(self, s, url):
        try:
            import kastr_overlay
            if kastr_overlay.under_tests():   # a test run never starts a real browser
                return None
        except Exception:
            pass
        exe = browser_path()
        if not exe or not self._port():
            return None
        prof = os.path.join(self._dir(s.rid), "profile")
        args = [exe, "--headless=new", "--user-data-dir=" + prof, "--no-first-run", "--no-default-browser-check", "--mute-audio",
                "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
                "--autoplay-policy=no-user-gesture-required", "--deny-permission-prompts", "--window-size=1920,1080",
                "--force-device-scale-factor=1", "--disable-extensions", "--disable-sync", "--no-pings"]
        if "browser" in os.path.normcase(exe):
            args.append("--test-type=gpu")
        if LINUX and hasattr(os, "geteuid") and os.geteuid() == 0:
            args.append("--no-sandbox")   # Chromium refuses its sandbox as root (crbug.com/638180); it loads only this host's page
        args.append(url)
        p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            import kastr_rtsp
            kastr_rtsp._job_assign(kastr_rtsp.app_job(self.note), p, self.note)   # dies with KASTR
        except Exception:
            pass
        return p

    def _kill(self, s):
        p, s.proc = s.proc, None
        if p is None:
            return
        try:
            p.kill()
        except Exception:
            pass
        try:
            p.wait(timeout=5)
        except Exception:
            pass

    def _session(self, rid, key):
        s = self.live.get(rid or "")
        return s if s and _eq(key, s.key) else None

    def boot(self, rid, nonce):
        """The recorder's first page (one use): its keys into sessionStorage, then the KASTR page."""
        with self.lock:
            s = self.live.get(rid or "")
            if not s or not _eq(nonce, s.nonce):
                return None
            s.nonce = ""
            cfg = {"rid": s.rid, "key": s.key, "deck": s.meta["deck"], "part": s.part, "room": s.meta["room"]}
            grant = {"room": s.meta["room"], "id": s.gid, "key": s.gkey, "at": _now_ms()}
            rejoin = {"room": s.meta["room"], "code": "", "access": "", "name": "Recorder", "micOn": False, "vidOn": False}
        j = lambda o: json.dumps(json.dumps(o))
        return ("<!doctype html><meta charset=\"utf-8\"><title>KASTR recorder</title><script>"
                "try{sessionStorage.setItem('kastr.presrec',%s);sessionStorage.setItem('kastr.access',%s);"
                "sessionStorage.setItem('kastr.rejoin',%s);sessionStorage.setItem('kastr.autopicked','1');"
                "localStorage.setItem('kastr.operator.name','Recorder');}catch(e){}"
                "location.replace('/moq-watch-lite.html');</script>" % (j(cfg), j(grant), j(rejoin)))

    def hello(self, rid, key):
        with self.lock:
            s = self._session(rid, key)
            if not s:
                return 403, {"error": "no such recording", "stop": True}
            if not s.seq:
                s.last = self.clock()   # before its first piece the page waits for the deck to show (it ends itself if never)
            return 200, {"deck": s.meta["deck"], "room": s.meta["room"], "part": s.part, "stop": s.stopping}

    def chunk(self, rid, key, part, seq, data, ms=0):
        with self.lock:
            s = self._session(rid, key)
            if not s or s.finishing:
                return 403, {"error": "no such recording", "stop": True}
            if part != s.part:
                return 409, {"error": "an older part", "stop": True}
            if seq != s.seq:
                return 409, {"error": "piece %d expected" % s.seq, "seq": s.seq}
            if s.meta.get("size", 0) + len(data) > MAX_BYTES:
                self._stopping(s, "size")
                return 200, {"ok": False, "stop": True}
            with open(os.path.join(self._dir(rid), "part%d.rec" % part), "ab") as f:
                f.write(data)
            s.seq += 1
            s.last = self.clock()
            s.meta["size"] = int(s.meta.get("size", 0)) + len(data)
            if ms:
                s.dur[part] = max(s.dur.get(part, 0), int(ms))
            if not s.stopping and self._free_bytes() < FREE_FLOOR:
                self._stopping(s, "disk")
            elif s.seq % 5 == 1:
                self._save(s.meta)
            return 200, {"ok": True, "stop": s.stopping}

    def next_part(self, rid, key, part):
        """The recorder page reloaded itself (an update, a crash of its tab): what it records now goes into a new part -- a
        second MP4 header in the middle of a part file would spoil it."""
        with self.lock:
            s = self._session(rid, key)
            if not s or s.finishing:
                return 403, {"error": "no such recording", "stop": True}
            if part == s.part and s.seq:
                self._close_part(s)
                s.part = max([s.part] + self._part_numbers(s.rid)) + 1
                s.seq = 0
                s.last = self.clock()
            return 200, {"part": s.part, "stop": s.stopping}

    def done(self, rid, key, part, absent=False):
        """The recorder's last piece is in. absent: the page never saw (or lost for long) this deck showing in its room -- it
        records nothing there (the deck's room is only the creator's claim), so the recording ends."""
        with self.lock:
            s = self._session(rid, key)
            if not s:
                return 403, {"error": "no such recording"}
            if part == s.part:
                s.done_part = part
            if absent and not s.stopping:
                self._stopping(s, "absent")
            return 200, {"ok": True}

    def admit_ok(self, admit, slug):
        """kastr_relay's token minter: is this ka-<id>-<key> one of my recorders' room grants (for this room, while it runs)?"""
        m = re.match(r"^ka-([0-9a-f]{12})-([A-Za-z0-9_-]{32})$", str(admit or ""))
        if not m:
            return False
        with self.lock:
            for s in self.live.values():
                if s.gid == m.group(1) and _eq(m.group(2), s.gkey) and s.meta.get("room") == slug and not s.finishing:
                    return True
        return False

    # ---- the watcher ---------------------------------------------------------------------------------------------------
    def tick(self):
        """Every 2 s: finish what stopped, notice a deck gone, a dead or stalled recorder (-> the next part)."""
        fin = []
        with self.lock:
            t = self.clock()
            for s in list(self.live.values()):
                if s.finishing:
                    continue
                if not s.stopping and self._deck(s.meta["deck"]) is None:
                    self._stopping(s, "gone")
                if s.stopping:
                    if s.proc is None or s.done_part == s.part or t - s.stop_at > STOP_WAIT_S:
                        s.finishing = True
                        fin.append(s)
                    continue
                dead = s.proc is not None and s.proc.poll() is not None
                stalled = s.proc is not None and t - s.last > (STALL_S if s.seq else BOOT_S)   # the first piece: the page joins first
                if dead or stalled:
                    self.note("presrec: recorder for %s part %d %s -- a new part" % (s.rid, s.part, "stopped" if dead else "stalled"))
                    self._close_part(s)
                    self._kill(s)
                if s.proc is None:
                    self._launch(s)
        for s in fin:
            self._finish(s)
        return len(fin)

    def _close_part(self, s):
        if s.part and os.path.exists(os.path.join(self._dir(s.rid), "part%d.rec" % s.part)):
            s.meta.setdefault("parts", [])
            if not any(int(p.get("n") or 0) == s.part for p in s.meta["parts"]):
                s.meta["parts"].append({"n": s.part, "ms": s.dur.get(s.part, 0)})
            self._save(s.meta)

    def _part_numbers(self, rid):
        out = []
        try:
            for fn in os.listdir(self._dir(rid)):
                m = re.match(r"^(?:part)?(\d{1,4})\.(?:rec|mp4)$", fn)
                if m:
                    out.append(int(m.group(1)))
        except OSError:
            pass
        return out

    def _finish(self, s):
        self._kill(s)
        self._close_part(s)
        self.finalize_files(s.meta)
        with self.lock:
            self.live.pop(s.rid, None)
        shutil.rmtree(os.path.join(self._dir(s.rid), "profile"), ignore_errors=True)
        self.note("presrec: recording %s finished (%s, %d MB in %d part(s))" % (s.rid, WHY.get(s.meta.get("why"), "-"),
                                                                               s.meta.get("size", 0) >> 20, len(s.meta.get("parts", []))))

    def finalize_files(self, meta):
        """part<n>.rec -> <n>.mp4 (a stream copy with the index up front; the raw piece file when ffmpeg cannot)."""
        d = self._dir(meta["rid"])
        parts = []
        for n in sorted(set(self._part_numbers(meta["rid"]))):
            raw, out = os.path.join(d, "part%d.rec" % n), os.path.join(d, "%d.mp4" % n)
            if os.path.exists(raw):
                if os.path.getsize(raw) == 0:
                    os.remove(raw)
                    continue
                ok = False
                if self.ffmpeg:
                    try:
                        r = subprocess.run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", raw, "-c", "copy",
                                            "-movflags", "+faststart", out], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.PIPE, timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        ok = r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0
                    except Exception:
                        ok = False
                if ok:
                    os.remove(raw)
                else:
                    try:
                        os.replace(raw, out)
                    except OSError:
                        continue
            if os.path.exists(out):
                ms = next((int(p.get("ms") or 0) for p in meta.get("parts", []) if int(p.get("n") or 0) == n), 0)
                parts.append({"n": n, "ms": ms, "bytes": os.path.getsize(out)})
        meta["parts"] = parts
        meta["size"] = sum(p["bytes"] for p in parts)
        meta["state"] = "done" if parts else "empty"
        meta["end"] = meta.get("end") or _now_ms()
        if parts:
            self._save(meta)
        else:
            shutil.rmtree(d, ignore_errors=True)

    def resume(self):
        """At start: a recording that was running when KASTR stopped keeps its file so far and carries on in the next part
        while its deck is still on this relay host (else it is finished)."""
        with self.lock:
            for m in self._all():
                if m.get("state") != "rec" or m["rid"] in self.live:
                    continue
                if self._deck(m.get("deck")) is None:
                    m["why"] = m.get("why") or "restart"
                    self.finalize_files(m)
                    continue
                d = self._dir(m["rid"])
                for n in self._part_numbers(m["rid"]):
                    if os.path.exists(os.path.join(d, "part%d.rec" % n)) and not any(int(p.get("n") or 0) == n for p in m.get("parts", [])):
                        m.setdefault("parts", []).append({"n": n, "ms": 0})
                shutil.rmtree(os.path.join(d, "profile"), ignore_errors=True)
                s = Session(m)
                s.part = max([0] + self._part_numbers(m["rid"]))
                self.live[m["rid"]] = s
                self._save(m)
                self.note("presrec: recording %s carries on after a restart (part %d next)" % (m["rid"], s.part + 1))

    def run(self):
        self.resume()
        while not self._stop.wait(2.0):
            try:
                self.tick()
            except Exception as e:
                self.note("presrec: watcher: %r" % e)

    def start_thread(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self.run, name="kastr-presrec", daemon=True)
            self._thread.start()

    # ---- the Recordings list, the files ---------------------------------------------------------------------------------
    def _rights(self, m, keys, admin):
        """-> (see, delete) for one recording: the deck's write token (presenters) sees + deletes, its read token (backstage)
        sees, an admin (or this machine's own page) both."""
        if admin:
            return True, True
        th = {_h(k.get("k")) for k in keys if k.get("d") == m.get("deck") and k.get("k")}
        if m.get("tokH") in th:
            return True, True
        if m.get("rtH") in th:
            return True, False
        return False, False

    def listing(self, keys, admin=False, room=None):
        keys = [k for k in (keys or [])[:LISTS_MAX] if isinstance(k, dict)]
        out = []
        with self.lock:
            live = {rid: s for rid, s in self.live.items()}
            for m in self._all():
                see, dele = self._rights(m, keys, admin)
                if not see or (admin and room and not any(k.get("d") == m.get("deck") for k in keys) and m.get("room") != room):
                    continue
                s = live.get(m["rid"])
                rec = {"id": m["rid"], "deck": m.get("deck"), "name": m.get("name"), "room": m.get("room"), "at": m.get("at"),
                       "end": m.get("end"), "state": "rec" if s else m.get("state"), "size": m.get("size", 0),
                       "parts": [{"n": p["n"], "ms": p.get("ms", 0), "bytes": p.get("bytes", 0)} for p in m.get("parts", []) if p.get("bytes")],
                       "dk": m.get("dk"), "del": dele, "why": WHY.get(m.get("why"), ""), "warn": m.get("warn") or ""}
                out.append(rec)
        out.sort(key=lambda r: -(r.get("at") or 0))
        return 200, {"recordings": out, "maxGb": MAX_BYTES // GB}

    def file(self, rid, n, dk):
        m = self._load(rid)
        if not m or not _eq(dk, m.get("dk")) or rid in self.live:
            return None, None
        p = os.path.join(self._dir(rid), "%d.mp4" % n)
        if not os.path.isfile(p):
            return None, None
        nm = re.sub(r"[^A-Za-z0-9 ._()-]+", "", str(m.get("name") or "Presentation")).strip()[:80] or "Presentation"
        when = time.strftime("%Y-%m-%d %H-%M", time.localtime((m.get("at") or 0) / 1000))
        multi = len(m.get("parts", [])) > 1
        return p, "%s %s%s.mp4" % (nm, when, (" part %d" % n) if multi else "")

    def delete(self, rid, keys, admin=False):
        m = self._load(rid)
        if not m:
            return 404, {"error": "no such recording"}
        see, dele = self._rights(m, keys, admin)
        if not dele:
            return 403, {"error": "only a presenter of it or an admin can delete a recording"}
        with self.lock:
            s = self.live.get(rid)
            if s:
                return 409, {"error": "it is still recording -- switch it off first"}
            shutil.rmtree(self._dir(rid), ignore_errors=True)
        self.note("presrec: recording %s deleted" % rid)
        return 200, {"ok": True}


# ---------------------------------------------------------------------------------------------------------------------
# the one instance KASTR runs (kastr_serve.make_server) + the seams other modules call

_INST = [None]


def start(state_dir, relay=None, web_port=None, ffmpeg=None, note=None):
    if _INST[0] is None and state_dir:
        _INST[0] = PresRec(state_dir, relay=relay, web_port=web_port, ffmpeg=ffmpeg, note=note)
        _INST[0].start_thread()
    return _INST[0]


def deck_ended(state_dir, did):
    inst = _INST[0]
    if inst is not None:
        try:
            inst.deck_ended(did)
        except Exception:
            pass


def admit_ok(admit, slug):
    inst = _INST[0]
    return bool(inst is not None and inst.admit_ok(admit, slug))


# ---- HTTP (kastr_serve hands its handler here) -----------------------------------------------------------------------

def _reply(handler, code, obj):
    body = json.dumps(obj).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    try:
        handler._cors()
    except AttributeError:
        handler.send_header("Access-Control-Allow-Origin", "*")
    handler._corp_cross = True
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _body(handler, limit=1 << 20):
    try:
        n = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        n = 0
    if n <= 0:
        return b""
    if n > limit:
        return None
    return handler.rfile.read(n)


def _json_body(handler):
    raw = _body(handler, 256 << 10)
    try:
        v = json.loads((raw or b"{}").decode("utf-8"))
        return v if isinstance(v, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def _admin(inst, handler, bearer):
    try:
        import kastr_relay
        if kastr_relay.is_local(handler) and not _recorder_host(handler):
            return True   # this relay host's own page
        auth = getattr(inst.relay, "auth", None)
        claims = kastr_relay.verify_token(str(bearer or ""), auth.key) if auth is not None and bearer else None
        return bool(claims) and kastr_relay.claims_admin_any(claims)
    except Exception:
        return False


def _recorder_host(handler):
    host = str(handler.headers.get("Host") or "").split(":")[0].strip().lower()
    return host == HOST


def _loopback(handler):
    try:
        return str(handler.client_address[0]) in ("127.0.0.1", "::1", "::ffff:127.0.0.1")
    except Exception:
        return False


def handle_api(handler, note=None):
    """Serve /api/presrec*. Returns True when it answered."""
    path = handler.path.split("?", 1)[0]
    if not (path == "/api/presrec" or path.startswith("/api/presrec/")):
        return False
    inst = _INST[0]
    qs = parse_qs(urlparse(handler.path).query)
    q = lambda k: (qs.get(k) or [""])[0]
    method = handler.command
    if inst is None:
        _body(handler)
        return _reply(handler, 503, {"error": "this KASTR does not record presentations"})
    if path in ("/api/presrec/start", "/api/presrec/stop"):
        if method != "POST":
            return _reply(handler, 405, {"error": "POST"})
        b = _json_body(handler)
        if path.endswith("/start"):
            code, obj = inst.start(q("deck"), q("k"), name=str(b.get("name") or ""), by_name=str(b.get("by") or ""))
        else:
            code, obj = inst.stop(q("deck"), q("k"))
        return _reply(handler, code, obj)
    if path == "/api/presrec/state":
        code, obj = inst.state(q("deck"), q("k"))
        return _reply(handler, code, obj)
    if path == "/api/presrec/list":
        if method != "POST":
            return _reply(handler, 405, {"error": "POST"})
        b = _json_body(handler)
        keys = b.get("keys") if isinstance(b.get("keys"), list) else []
        code, obj = inst.listing(keys, admin=_admin(inst, handler, b.get("bearer")), room=str(b.get("room") or "") or None)
        return _reply(handler, code, obj)
    m = re.match(r"^/api/presrec/([0-9a-f]{16})/(boot|hello|next|chunk|done|delete|(\d{1,4})[.]mp4)$", path)
    if not m:
        _body(handler)
        return _reply(handler, 404, {"error": "no such recording call"})
    rid, what = m.group(1), m.group(2)
    if what == "delete":
        if method != "POST":
            return _reply(handler, 405, {"error": "POST"})
        b = _json_body(handler)
        keys = b.get("keys") if isinstance(b.get("keys"), list) else []
        code, obj = inst.delete(rid, keys, admin=_admin(inst, handler, b.get("bearer")))
        return _reply(handler, code, obj)
    if m.group(3):
        p, fname = inst.file(rid, int(m.group(3)), q("k"))
        if not p:
            return _reply(handler, 404, {"error": "no such recording"})
        size = os.path.getsize(p)
        handler.send_response(200)
        handler.send_header("Content-Type", "video/mp4")
        handler.send_header("Content-Length", str(size))
        handler.send_header("Content-Disposition", "attachment; filename=\"%s\"" % fname.replace('"', ""))
        handler.send_header("Cache-Control", "no-store")
        try:
            handler._cors()
        except AttributeError:
            handler.send_header("Access-Control-Allow-Origin", "*")
        handler._corp_cross = True
        handler.end_headers()
        with open(p, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                handler.wfile.write(chunk)
        return True
    # the recorder's own calls: only its headless page on this machine (Host presrec.localhost, a loopback peer)
    if not (_recorder_host(handler) and _loopback(handler)):
        _body(handler)
        return _reply(handler, 403, {"error": "the recorder's own call"})
    if what == "boot":
        html = inst.boot(rid, q("n"))
        if html is None:
            return _reply(handler, 403, {"error": "this recorder link was used already"})
        body = html.encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)
        return True
    if what == "hello":
        code, obj = inst.hello(rid, q("k"))
        return _reply(handler, code, obj)
    if what == "next":
        _body(handler)
        try:
            part = int(q("p") or 0)
        except ValueError:
            part = 0
        code, obj = inst.next_part(rid, q("k"), part)
        return _reply(handler, code, obj)
    if what == "chunk":
        if method != "POST":
            return _reply(handler, 405, {"error": "POST"})
        data = _body(handler, CHUNK_MAX)
        if data is None:
            return _reply(handler, 413, {"error": "too large"})
        try:
            part, seq, ms = int(q("p") or 0), int(q("s") or 0), int(q("t") or 0)
        except ValueError:
            return _reply(handler, 400, {"error": "bad piece"})
        code, obj = inst.chunk(rid, q("k"), part, seq, data, ms)
        return _reply(handler, code, obj)
    if what == "done":
        _body(handler)
        try:
            part = int(q("p") or 0)
        except ValueError:
            part = 0
        code, obj = inst.done(rid, q("k"), part, absent=q("x") == "absent")
        return _reply(handler, code, obj)
    return _reply(handler, 404, {"error": "no such recording call"})
