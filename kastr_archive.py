"""KASTR host recording (0.18.0, docs/moq-landscape.md item 6).

The relay host records the broadcasts its operator picks. For each one a pipeline
    moq --connect <this relay, operator token> --broadcast <b> export ts
      | ffmpeg -c copy -f segment (60 s fragmented-MP4 files)
writes <state>/archive/<room>__<host>__...__<leaf>/<YYYYmmddTHHMMSS>.mp4 (local time of the
segment start). Both children join the bridge's job object and child registry, so they die
with KASTR. A pipeline that exits is restarted on a ladder while its broadcast stays enabled
(a broadcast that is not live makes moq exit after its resolve timeout -- the ladder covers
that too). Segments older than `hours` (kastr.ini archive_hours, default 24) are swept hourly.

The picked set lives in <state>/archive.json and resumes whenever the relay starts. This
module never decides WHO may read a recording: kastr_serve checks tokens before calling it.
"""
import json
import os
import re
import subprocess
import threading
import time

ARCHIVE_DIR = "archive"
SEGMENT_S = 60
RESTART_S = [2, 5, 10, 30, 60]
SEG_RE = re.compile(r"^(\d{8}T\d{6})\.mp4$")
BCAST_RE = re.compile(r"^(?!(?:.*/)?\.\.?(?:/|$))[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+$")   # never a "." or ".." segment


def safe_name(broadcast):
    """room/host/op/leaf.hang -> room__host__op__leaf.hang (one directory per broadcast)."""
    return str(broadcast).replace("/", "__")


def seg_start(name):
    """Epoch seconds of a segment file name (local time, as ffmpeg's strftime wrote it)."""
    m = SEG_RE.match(name)
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(1), "%Y%m%dT%H%M%S"))
    except (ValueError, OverflowError):
        return None


class Pipe:
    """One broadcast's moq | ffmpeg recorder."""

    def __init__(self, arch, broadcast):
        self.arch = arch
        self.broadcast = broadcast
        self.dir = os.path.join(arch.root, safe_name(broadcast))
        self.procs = ()
        self.running = False
        self.stopping = False
        self.since = None
        self.restarts = 0
        self.error = None
        self._timer = None
        self._lock = threading.Lock()
        self._gen = 0

    def info(self):
        return {"running": self.running, "since": self.since, "restarts": self.restarts, "error": self.error}

    def start(self):
        br = self.arch.bridge
        with self._lock:
            if self.stopping:
                return
            self._timer = None
            url = self.arch.relay.operator_url() if self.arch.relay else None
            if not url or not getattr(br, "moq", None) or not getattr(br, "ffmpeg", None):
                self.error = "relay not running" if not url else "moq/ffmpeg not bundled"
                self.running = False
                self._schedule_locked()
                return
            os.makedirs(self.dir, exist_ok=True)
            self._gen += 1
            gen = self._gen
            moq = [br.moq, "--log-level", "warn", "--backoff-timeout", "10s", "--quic-idle-timeout", "15s",
                   "--connect", url, "--broadcast", self.broadcast, "export", "ts", "--max-age", "2s"]
            ff = [br.ffmpeg, "-hide_banner", "-loglevel", "error", "-fflags", "+genpts", "-i", "pipe:0",
                  "-map", "0", "-c", "copy", "-f", "segment", "-segment_time", str(SEGMENT_S),
                  "-segment_format", "mp4",
                  "-segment_format_options", "movflags=+frag_keyframe+empty_moov+default_base_moof",
                  "-reset_timestamps", "1", "-strftime", "1",
                  os.path.join(self.dir, "%Y%m%dT%H%M%S.mp4")]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if os.name == "nt":
                flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            mq = fp = None
            try:
                mq = subprocess.Popen(moq, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, creationflags=flags)
                fp = subprocess.Popen(ff, stdin=mq.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                      creationflags=flags)
            except OSError as e:
                for p in (mq, fp):
                    if p is not None and p.poll() is None:
                        try:
                            p.kill()
                        except OSError:
                            pass
                self.error = "could not start: %s" % e
                self.running = False
                self._schedule_locked()
                return
            mq.stdout.close()
            self.procs = (mq, fp)
            for p, argv, tag in ((mq, moq, "moq"), (fp, ff, "ffmpeg")):
                try:
                    br._child_started(p, argv, [self.broadcast], "archive-" + tag)
                except Exception:
                    pass
            self.running = True
            self.since = time.time()
            self.error = None
        self.arch.log("archive: recording %s (moq %d, ffmpeg %d)" % (self.broadcast, mq.pid, fp.pid))
        errs = []

        def drain(p, tag):
            try:
                for line in p.stderr:
                    t = re.sub(r"\x1b\[[0-9;]*m", "", line.decode("utf-8", "replace")).strip()
                    t = re.sub(r"jwt=[^&\s]+", "jwt=...", t)
                    if t:
                        errs.append(tag + ": " + t[-200:])
                        del errs[:-6]
            except Exception:
                pass
        for p, tag in ((mq, "moq"), (fp, "ffmpeg")):
            threading.Thread(target=drain, args=(p, tag), daemon=True).start()
        threading.Thread(target=self._watch, args=(gen, mq, fp, errs), daemon=True).start()

    def _watch(self, gen, mq, fp, errs):
        while mq.poll() is None and fp.poll() is None:
            time.sleep(0.5)
            if self.stopping or gen != self._gen:
                return
        who = "moq" if mq.poll() is not None else "ffmpeg"
        time.sleep(0.3)
        for p in (mq, fp):
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
            try:
                self.arch.bridge._child_ended(p.pid)
            except Exception:
                pass
        with self._lock:
            if gen != self._gen:
                return
            lived = time.time() - (self.since or time.time())
            self.running = False
            self.error = "%s exited after %.0f s%s" % (who, lived, (" -- " + errs[-1]) if errs else "")
            if lived > 120:
                self.restarts = 0
            if not self.stopping:
                self._schedule_locked()
        self.arch.log("archive: %s stopped (%s)" % (self.broadcast, self.error))

    def _schedule_locked(self):
        if self.stopping or self._timer is not None:
            return
        wait = RESTART_S[min(self.restarts, len(RESTART_S) - 1)]
        self.restarts += 1
        t = threading.Timer(wait, self.start)
        t.daemon = True
        self._timer = t
        t.start()

    def stop(self):
        with self._lock:
            self.stopping = True
            self._gen += 1
            t, self._timer = self._timer, None
            procs = self.procs
        if t:
            t.cancel()
        # moq first: ffmpeg then sees EOF and closes its last segment cleanly
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
            try:
                self.arch.bridge._child_ended(p.pid)
            except Exception:
                pass
        self.running = False


class Archiver:
    def __init__(self, state_dir, relay, bridge, log=None, hours=24):
        self.state_dir = state_dir
        self.root = os.path.join(state_dir, ARCHIVE_DIR)
        self.relay = relay
        self.bridge = bridge
        self.log = log or (lambda m: None)
        try:
            self.hours = max(1, min(24 * 30, float(hours)))
        except (TypeError, ValueError):
            self.hours = 24.0
        self.lock = threading.Lock()
        self.enabled = set()
        self.pipes = {}
        self._load()
        if relay is not None:
            try:
                relay.on_start.append(lambda r: self.resume())
                relay.on_stop.append(lambda r: self.halt())
            except AttributeError:
                pass
        threading.Thread(target=self._sweeper, daemon=True, name="kastr-archive-sweep").start()

    # ---- the picked set ----------------------------------------------------------
    def _file(self):
        return os.path.join(self.state_dir, "archive.json")

    def _load(self):
        try:
            with open(self._file(), encoding="utf-8-sig") as f:
                d = json.load(f)
            self.enabled = {b for b in (d.get("broadcasts") or []) if isinstance(b, str) and BCAST_RE.match(b)}
        except Exception:
            self.enabled = set()

    def _save(self):
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            tmp = self._file() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"broadcasts": sorted(self.enabled), "hours": self.hours}, f)
            os.replace(tmp, self._file())
        except Exception as e:
            self.log("archive: could not save the recording list: %s" % e)

    def set(self, broadcast, on):
        b = str(broadcast or "").strip()
        if not BCAST_RE.match(b) or b.startswith("."):
            raise ValueError("bad broadcast path")
        with self.lock:
            if on:
                self.enabled.add(b)
            else:
                self.enabled.discard(b)
            self._save()
            pipe = self.pipes.pop(b, None) if not on else None
        if pipe:
            pipe.stop()
        if on and self.relay is not None and self.relay.running():
            self._start(b)
        self.log("archive: %s %s by the operator" % (b, "recording" if on else "stopped"))
        return self.status_one(b)

    def _start(self, b):
        with self.lock:
            if b in self.pipes and not self.pipes[b].stopping:
                return self.pipes[b]
            pipe = Pipe(self, b)
            self.pipes[b] = pipe
        pipe.start()
        return pipe

    def resume(self):
        for b in sorted(self.enabled):
            self._start(b)

    def halt(self):
        with self.lock:
            pipes = list(self.pipes.values())
            self.pipes = {}
        for p in pipes:
            p.stop()

    # ---- what is on disk -----------------------------------------------------------
    def segments(self, broadcast):
        d = os.path.join(self.root, safe_name(broadcast))
        try:
            names = sorted(n for n in os.listdir(d) if SEG_RE.match(n))
        except OSError:
            return []
        out = []
        for i, n in enumerate(names):
            t0 = seg_start(n)
            if t0 is None:
                continue
            p = os.path.join(d, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            t1 = seg_start(names[i + 1]) if i + 1 < len(names) else None
            if t1 is None:
                t1 = max(t0, st.st_mtime)
            out.append({"file": n, "t0": round(t0), "t1": round(t1), "size": st.st_size, "path": p})
        return out

    def broadcasts_on_disk(self):
        try:
            names = os.listdir(self.root)
        except OSError:
            return []
        return sorted(n.replace("__", "/") for n in names if os.path.isdir(os.path.join(self.root, n)))

    def status_one(self, b):
        segs = self.segments(b)
        pipe = self.pipes.get(b)
        return {"broadcast": b, "recording": b in self.enabled, **(pipe.info() if pipe else {"running": False}),
                "segments": [{k: s[k] for k in ("file", "t0", "t1", "size")} for s in segs],
                "bytes": sum(s["size"] for s in segs),
                "t0": segs[0]["t0"] if segs else None, "t1": segs[-1]["t1"] if segs else None}

    def status(self, room=None):
        names = set(self.enabled) | set(self.broadcasts_on_disk())
        if room:
            names = {n for n in names if n.split("/", 1)[0] == room}
        return {"hours": self.hours, "broadcasts": [self.status_one(b) for b in sorted(names)]}

    def range_files(self, broadcast, t0=None, t1=None):
        """Segment paths overlapping [t0, t1] (epoch seconds; None = open end)."""
        out = []
        for s in self.segments(broadcast):
            if t1 is not None and s["t0"] > t1:
                continue
            if t0 is not None and s["t1"] < t0:
                continue
            out.append(s["path"])
        return out

    def seg_path(self, broadcast, name):
        if not SEG_RE.match(str(name or "")):
            return None
        p = os.path.join(self.root, safe_name(broadcast), name)
        return p if os.path.isfile(p) else None

    # ---- retention -----------------------------------------------------------------
    def sweep(self, now=None):
        now = now or time.time()
        cut = now - self.hours * 3600
        gone = 0
        for b in self.broadcasts_on_disk():
            d = os.path.join(self.root, safe_name(b))
            for s in self.segments(b):
                if s["t1"] < cut:
                    try:
                        os.remove(s["path"])
                        gone += 1
                    except OSError:
                        pass
            try:
                if not os.listdir(d) and b not in self.enabled:
                    os.rmdir(d)
            except OSError:
                pass
        if gone:
            self.log("archive: swept %d segment(s) older than %g h" % (gone, self.hours))
        return gone

    def _sweeper(self):
        while True:
            time.sleep(3600)
            try:
                self.sweep()
            except Exception as e:
                self.log("archive: sweep failed: %s" % e)
