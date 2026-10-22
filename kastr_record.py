# -*- coding: utf-8 -*-
"""0.21.81 (Kenton: "When recording is used, allow for saving in multiple different formats. Default to MP4."):
the Record save dialog's formats, converted on THIS computer with the bundled ffmpeg.

The page records the stage with MediaRecorder (MP4 = H.264 + AAC where the browser can, WebM otherwise) and keeps
the recording as a Blob (Chromium pages large blobs to disk). On Save it streams that Blob here; ffmpeg writes the
chosen format next to it, the page polls the progress ("Converting... 42 %") and then fetches the result straight to
the file the operator picked (or as a download). Nothing holds a second full copy in memory: the upload is read in
1 MB pieces onto disk and the result is sent back the same way.

Formats -- streams are COPIED whenever the recording's codecs fit the container, so MP4 from an H.264 + AAC
recording is a quick remux (real duration + index at the front, plays everywhere):
  mp4   H.264 + AAC                  (default)
  webm  VP8/VP9/AV1 + Opus           (copied from a WebM recording; else VP9 realtime + Opus)
  mkv   whatever the recording holds (copied; anything unusual becomes H.264 + AAC)
  mov   H.264 + AAC                  (QuickTime / editing apps)
  m4a   AAC, audio only
  mp3   MP3 (libmp3lame), audio only

Routes -- this computer's own KASTR pages only (kastr_relay.is_local: loopback Host AND peer, no proxy, and an
Origin / Sec-Fetch-Site that is this machine's page):
  GET  /api/record/formats                  what this KASTR can write
  POST /api/record/convert?fmt=&dur=        body = the recording; -> {"job": id, "video": plan, "audio": plan}
  GET  /api/record/job/<id>                 {"state": "converting"|"done"|"error"|"cancelled", "percent", "size"}
  GET  /api/record/job/<id>/file?name=      the converted file (attachment); the job's files go once it is sent
  POST /api/record/job/<id>/cancel          kills ffmpeg, deletes the files (also the page's pagehide beacon)

Temp files live in <state>/media as rec-<job>.src.<ext> / rec-<job>.out.<ext>: the source goes the moment ffmpeg
ends, the result once it has been sent, after KEEP_DONE_S unclaimed, or by the sweep (crash leftovers older than
STALE_S here, and kastr_serve's 12-hour media sweep)."""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import parse_qs, quote, unquote, urlparse

FORMATS = ("mp4", "webm", "mkv", "mov", "m4a", "mp3")
DEFAULT_FORMAT = "mp4"
AUDIO_ONLY = ("m4a", "mp3")
EXT = {"mp4": ".mp4", "webm": ".webm", "mkv": ".mkv", "mov": ".mov", "m4a": ".m4a", "mp3": ".mp3"}
MIME = {"mp4": "video/mp4", "webm": "video/webm", "mkv": "video/x-matroska", "mov": "video/quicktime",
        "m4a": "audio/mp4", "mp3": "audio/mpeg"}
MUXER = {"mp4": "mp4", "webm": "webm", "mkv": "matroska", "mov": "mov", "m4a": "ipod", "mp3": "mp3"}
# codecs each container takes as they are (copied, no re-encode)
FIT_VIDEO = {"mp4": ("h264",), "mov": ("h264",), "mkv": ("h264", "hevc", "vp8", "vp9", "av1"), "webm": ("vp8", "vp9", "av1")}
FIT_AUDIO = {"mp4": ("aac",), "mov": ("aac",), "m4a": ("aac",), "mkv": ("aac", "opus", "vorbis", "mp3", "flac"),
             "webm": ("opus", "vorbis"), "mp3": ("mp3",)}
# the encoder when a stream does not fit
ENC_VIDEO = {"webm": "libvpx-vp9"}           # every other video container: libx264
ENC_AUDIO = {"webm": "libopus", "mp3": "libmp3lame"}   # every other: aac (ffmpeg's native encoder)
NEEDS = ("libx264", "libvpx-vp9", "libopus", "libmp3lame", "aac")

UPLOAD_MAX = 8 * 1024 ** 3        # an 8 GB recording is ~4 hours at the recorder's 5 Mbit/s
MAX_ACTIVE = 2                    # conversions running at once
KEEP_DONE_S = 30 * 60             # a finished result nobody fetched
STALE_S = 6 * 3600                # rec-* files no job owns (a crash mid-conversion)
DISK_MARGIN = 256 * 1024 * 1024
JOB_RE = re.compile(r"^[0-9a-f]{32}$")
SRC_EXT = {"video/mp4": "mp4", "audio/mp4": "mp4", "video/webm": "webm", "audio/webm": "webm",
           "video/x-matroska": "mkv", "video/quicktime": "mov"}

JOBS = {}
JOBS_LOCK = threading.Lock()
_ENCODERS = {}                    # ffmpeg path -> set of the NEEDS it lists


def plan(fmt, vcodec, acodec):
    """-> (video, audio): "copy", an encoder name, or None (that stream is left out)."""
    if fmt not in FORMATS:
        raise ValueError("unknown format %r" % fmt)
    vcodec = (vcodec or "").lower() or None
    acodec = (acodec or "").lower() or None
    v = None
    if fmt not in AUDIO_ONLY and vcodec:
        v = "copy" if vcodec in FIT_VIDEO[fmt] else ENC_VIDEO.get(fmt, "libx264")
    a = None
    if acodec:
        a = "copy" if acodec in FIT_AUDIO[fmt] else ENC_AUDIO.get(fmt, "aac")
    if fmt in AUDIO_ONLY and not a:
        raise ValueError("the recording has no sound")
    if not v and not a:
        raise ValueError("the recording has no picture or sound")
    return v, a


def build_args(ff, src, dst, fmt, vcodec, acodec):
    """The ffmpeg argv that writes `dst` in `fmt` from `src` (whose streams are vcodec / acodec). Progress goes to
    stdout as key=value lines (-progress pipe:1); errors only on stderr."""
    v, a = plan(fmt, vcodec, acodec)
    argv = [ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y", "-i", src]
    argv += ["-map", "0:v:0"] if v else ["-vn"]
    argv += ["-map", "0:a:0"] if a else ["-an"]
    if v == "copy":
        argv += ["-c:v", "copy"]
    elif v == "libx264":
        # the recorder marks its frames full range; players expect limited -- converted once, here
        argv += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high", "-color_range", "tv"]
    elif v == "libvpx-vp9":
        argv += ["-vf", "format=yuv420p", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
                 "-row-mt", "1", "-b:v", "5M"]
    if a == "copy":
        argv += ["-c:a", "copy"]
    elif a == "aac":
        argv += ["-c:a", "aac", "-b:a", "192k"]
    elif a == "libopus":
        argv += ["-c:a", "libopus", "-b:a", "128k"]
    elif a == "libmp3lame":
        argv += ["-c:a", "libmp3lame", "-q:a", "2"]
    if fmt in ("mp4", "mov", "m4a"):
        argv += ["-movflags", "+faststart"]
    argv += ["-f", MUXER[fmt], dst]
    return argv


def encoders(ff):
    """The NEEDS this ffmpeg lists (`ffmpeg -encoders`), asked once per binary."""
    if not ff:
        return set()
    if ff not in _ENCODERS:
        got = set()
        try:
            r = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in (r.stdout or "").splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1] in NEEDS:
                    got.add(parts[1])
        except Exception:
            pass
        _ENCODERS[ff] = got
    return _ENCODERS[ff]


def formats_info(ff):
    """{fmt: {"ok": bool, "why": str}} -- a format whose possible encoders are all missing is not offered.
    (mp3 needs libmp3lame; the others always have a copy path or ffmpeg's native aac / the bundled libx264.)"""
    enc = encoders(ff)
    out = {}
    for f in FORMATS:
        if not ff:
            out[f] = {"ok": False, "why": "ffmpeg is not available here"}
        elif f == "mp3" and "libmp3lame" not in enc:
            out[f] = {"ok": False, "why": "this ffmpeg has no MP3 encoder"}
        else:
            out[f] = {"ok": True, "why": ""}
    return out


def probe(ff, path):
    """ffmpeg -i -> (video codec, audio codec, duration seconds or 0.0)."""
    try:
        r = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", path], capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        err = r.stderr or ""
    except Exception:
        return None, None, 0.0
    v = re.search(r"Stream #\d+:\d+(?:\[[^\]]*\])?(?:\([^)]*\))?: Video: ([A-Za-z0-9_]+)", err)
    a = re.search(r"Stream #\d+:\d+(?:\[[^\]]*\])?(?:\([^)]*\))?: Audio: ([A-Za-z0-9_]+)", err)
    d = re.search(r"Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)", err)
    dur = 0.0
    if d:
        try:
            dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))
        except ValueError:
            dur = 0.0
    return (v.group(1).lower() if v else None), (a.group(1).lower() if a else None), dur


def progress_seconds(line):
    """One -progress line -> seconds written so far, or None. (out_time_us; out_time_ms is microseconds too.)"""
    m = re.match(r"^out_time_(?:us|ms)=(\d+)\s*$", line.strip())
    if m:
        return int(m.group(1)) / 1e6
    m = re.match(r"^out_time=(\d+):(\d\d):(\d\d(?:\.\d+)?)\s*$", line.strip())
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return None


def safe_name(name, fmt):
    """A file name for Content-Disposition: no path, no characters Windows refuses, the format's extension."""
    n = os.path.basename(str(name or "").replace("\\", "/")).strip()
    n = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]+', "-", n).strip(" .")[:180] or "recording"
    n = re.sub(r"\.(webm|mp4|mkv|mov|m4a|mp3)$", "", n, flags=re.I) + EXT[fmt]
    return n


def media_dir(state_dir):
    d = os.path.join(state_dir or os.getcwd(), "media")
    os.makedirs(d, exist_ok=True)
    return d


class Job:
    def __init__(self, jid, fmt, src, dst, duration):
        self.id, self.fmt, self.src, self.dst, self.duration = jid, fmt, src, dst, float(duration or 0)
        self.state = "uploading"
        self.percent = 0.0
        self.size = 0
        self.error = ""
        self.proc = None
        self.video = self.audio = None
        self.created = time.time()
        self.finished = 0.0
        self.sending = False
        self.cancelled = False

    def view(self):
        return {"job": self.id, "fmt": self.fmt, "state": self.state, "percent": round(self.percent, 1),
                "size": self.size, "error": self.error, "video": self.video, "audio": self.audio,
                "duration": round(self.duration, 3)}


def _rm(path):
    for _ in range(10):   # Windows: a just-killed ffmpeg may hold the file a moment longer
        try:
            if path and os.path.exists(path):
                os.remove(path)
            return True
        except OSError:
            time.sleep(0.2)
    return False


def drop(job, state=None):
    """Forget a job and delete its files (killing ffmpeg first if it still runs)."""
    if state:
        job.state = state
    p = job.proc
    if p is not None:
        try:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=5)
        except Exception:
            pass
    _rm(job.src)
    _rm(job.dst)
    with JOBS_LOCK:
        if JOBS.get(job.id) is job:
            del JOBS[job.id]


def sweep(state_dir, now=None):
    """Finished jobs past KEEP_DONE_S and rec-* files no job owns older than STALE_S."""
    now = now or time.time()
    with JOBS_LOCK:
        jobs = list(JOBS.values())
    for j in jobs:
        if j.state in ("done", "error", "cancelled") and j.finished and now - j.finished > KEEP_DONE_S and not j.sending:
            drop(j)
    d = media_dir(state_dir)
    with JOBS_LOCK:
        owned = {os.path.basename(p) for j in JOBS.values() for p in (j.src, j.dst)}
    n = 0
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    for fn in names:
        if not fn.startswith("rec-") or fn in owned:
            continue
        p = os.path.join(d, fn)
        try:
            if os.path.isfile(p) and now - os.path.getmtime(p) > STALE_S:
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n


def _spawn_plain(argv):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    kw = {}
    if sys.platform == "win32":
        flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    else:
        kw["preexec_fn"] = lambda: os.nice(10)
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=flags, **kw)
    proc.kastr_errors = []

    def drain():
        try:
            for line in iter(proc.stderr.readline, b""):
                s = line.decode("utf-8", "replace").strip()
                if s:
                    proc.kastr_errors.append(s)
                    del proc.kastr_errors[:-4]
        except Exception:
            pass
        try:
            proc.stderr.close()
        except Exception:
            pass
    threading.Thread(target=drain, daemon=True).start()
    return proc


def run(job, argv, bridge=None, note=None):
    """ffmpeg for one job (blocking -- the caller's thread): percent from out_time vs the duration; the source goes
    when ffmpeg ends; a result nobody claims goes after KEEP_DONE_S."""
    spawn = getattr(bridge, "spawn_media", None) if bridge is not None else None
    release = getattr(bridge, "release_media", None) if bridge is not None else None
    job.state = "converting"
    t0 = time.time()
    try:
        proc = spawn(argv, tag="record", nice=True) if callable(spawn) else _spawn_plain(argv)
    except Exception as e:
        job.state, job.error, job.finished = "error", "could not start ffmpeg: %s" % e, time.time()
        _rm(job.src)
        return job
    job.proc = proc
    if job.cancelled:   # cancelled between upload and spawn
        drop(job, "cancelled")
    try:
        for raw in iter(proc.stdout.readline, b""):
            s = progress_seconds(raw.decode("utf-8", "replace"))
            if s is not None and job.duration > 0:
                job.percent = max(job.percent, min(99.0, 100.0 * s / job.duration))
    except Exception:
        pass
    rc = proc.wait()
    try:
        proc.stdout.close()
    except Exception:
        pass
    if callable(release):
        try:
            release(proc)
        except Exception:
            pass
    _rm(job.src)
    job.finished = time.time()
    if job.cancelled:
        job.state = "cancelled"
        _rm(job.dst)
    elif rc == 0 and os.path.exists(job.dst) and os.path.getsize(job.dst) > 0:
        job.size = os.path.getsize(job.dst)
        job.percent = 100.0
        job.state = "done"
        timer = threading.Timer(KEEP_DONE_S, lambda: (not job.sending) and drop(job))
        timer.daemon = True
        timer.start()
    else:
        errs = list(getattr(proc, "kastr_errors", []) or [])
        job.state, job.error = "error", ("ffmpeg: " + errs[-1]) if errs else "ffmpeg ended with code %s" % rc
        _rm(job.dst)
    if callable(note):
        try:
            note("record: %s -> %s %s in %.1f s (%s/%s)%s" % (os.path.basename(job.src), job.fmt, job.state,
                 time.time() - t0, job.video, job.audio, (" -- " + job.error) if job.error else ""))
        except Exception:
            pass
    return job


# ---- HTTP ---------------------------------------------------------------------------------------------------------
def _own_page(handler):
    """This computer's own KASTR page (or tool): loopback request AND no other site's page behind it."""
    try:
        import kastr_relay
        if not kastr_relay.is_local(handler):
            return False
    except Exception:
        return False
    origin = str(handler.headers.get("Origin") or "")
    site = str(handler.headers.get("Sec-Fetch-Site") or "")
    if origin and not re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", origin):
        return False
    return site in ("", "same-origin", "none")


def _reply(handler, code, obj):
    body = json.dumps(obj).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _drain(handler, limit=1 << 20):
    try:
        n = int(handler.headers.get("Content-Length") or 0)
        if 0 < n <= limit:
            handler.rfile.read(n)
    except Exception:
        pass


def _active():
    with JOBS_LOCK:
        return sum(1 for j in JOBS.values() if j.state in ("uploading", "converting"))


def handle_api(handler, bridge, state_dir, note=None):
    """Serve /api/record/*. Returns True when it answered."""
    path = handler.path.split("?", 1)[0]
    if not path.startswith("/api/record/"):
        return False
    method = handler.command
    if not _own_page(handler):
        if method == "POST":
            _drain(handler)
        return _reply(handler, 403, {"error": "recording conversion only for this computer's own KASTR"})
    ff = getattr(bridge, "ffmpeg", None) if bridge is not None else None
    qs = parse_qs(urlparse(handler.path).query)
    if path == "/api/record/formats" and method == "GET":
        try:
            sweep(state_dir)
        except Exception:
            pass
        return _reply(handler, 200, {"ffmpeg": bool(ff), "default": DEFAULT_FORMAT, "formats": formats_info(ff),
                                     "max": UPLOAD_MAX})
    if path == "/api/record/convert" and method == "POST":
        return _convert(handler, bridge, ff, state_dir, qs, note)
    m = re.match(r"^/api/record/job/([0-9a-f]{32})(/file|/cancel)?$", path)
    if not m:
        if method == "POST":
            _drain(handler)
        return _reply(handler, 404, {"error": "no such record route"})
    with JOBS_LOCK:
        job = JOBS.get(m.group(1))
    tail = m.group(2) or ""
    if tail == "/cancel" and method == "POST":
        _drain(handler)
        if job is None:
            return _reply(handler, 200, {"ok": True, "state": "gone"})
        job.cancelled = True
        drop(job, "cancelled")
        return _reply(handler, 200, {"ok": True, "state": "cancelled"})
    if method != "GET":
        _drain(handler)
        return _reply(handler, 405, {"error": "GET"})
    if job is None:
        return _reply(handler, 404, {"error": "no such conversion (finished results are kept for %d minutes)" % (KEEP_DONE_S // 60)})
    if tail == "/file":
        return _send(handler, job, (qs.get("name") or [""])[0])
    return _reply(handler, 200, job.view())


def _convert(handler, bridge, ff, state_dir, qs, note):
    def refuse(code, msg):
        _drain(handler)
        return _reply(handler, code, {"error": msg})
    if not ff:
        return refuse(503, "ffmpeg is not available here")
    fmt = ((qs.get("fmt") or [""])[0] or "").lower()
    if fmt not in FORMATS:
        return refuse(400, "fmt must be one of " + ", ".join(FORMATS))
    if not formats_info(ff)[fmt]["ok"]:
        return refuse(400, formats_info(ff)[fmt]["why"])
    try:
        dur = float((qs.get("dur") or ["0"])[0] or 0)
    except ValueError:
        dur = 0.0
    dur = dur if 0 < dur < 7 * 86400 else 0.0
    try:
        n = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        n = 0
    if n <= 0:
        return refuse(411, "send the recording with its length")
    if n > UPLOAD_MAX:
        return refuse(413, "the recording is larger than %d GB" % (UPLOAD_MAX // 1024 ** 3))
    try:
        sweep(state_dir)
    except Exception:
        pass
    if _active() >= MAX_ACTIVE:
        return refuse(429, "%d conversions are already running -- try again when one finishes" % MAX_ACTIVE)
    d = media_dir(state_dir)
    try:
        free = shutil.disk_usage(d).free
    except OSError:
        free = None
    if free is not None and free < 2 * n + DISK_MARGIN:   # the recording + the result, about as large
        return refuse(507, "not enough free disk space to convert (%d MB free)" % (free // 1048576))
    ctype = str(handler.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    jid = uuid.uuid4().hex
    src = os.path.join(d, "rec-%s.src.%s" % (jid, SRC_EXT.get(ctype, "bin")))
    dst = os.path.join(d, "rec-%s.out%s" % (jid, EXT[fmt]))
    job = Job(jid, fmt, src, dst, dur)
    with JOBS_LOCK:
        JOBS[jid] = job
    got = 0
    read1 = getattr(handler.rfile, "read1", None) or handler.rfile.read
    try:
        with open(src, "wb") as f:
            while got < n and not job.cancelled:
                chunk = read1(min(1 << 20, n - got))
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
    except (OSError, ValueError) as e:
        job.error = "upload: %s" % e
    if got < n or job.cancelled:
        drop(job, "cancelled")
        try:
            return _reply(handler, 400, {"error": job.error or "the upload ended early", "got": got, "size": n})
        except OSError:
            return True
    v, a, pdur = probe(ff, src)
    if pdur > 0:
        job.duration = pdur
    try:
        job.video, job.audio = plan(fmt, v, a)
        argv = build_args(ff, src, dst, fmt, v, a)
    except ValueError as e:
        drop(job, "error")
        return _reply(handler, 400, {"error": str(e)})
    job.state = "converting"
    threading.Thread(target=run, args=(job, argv, bridge, note), daemon=True, name="kastr-record-" + jid[:8]).start()
    out = job.view()
    out.update({"source": {"video": v, "audio": a}})
    return _reply(handler, 200, out)


def _send(handler, job, name):
    if job.state != "done":
        return _reply(handler, 409, {"error": "not ready", "state": job.state, "percent": round(job.percent, 1)})
    fn = safe_name(unquote(name or "") or ("recording" + EXT[job.fmt]), job.fmt)
    ascii_fn = re.sub(r"[^A-Za-z0-9._ ()+-]", "_", fn)
    try:
        size = os.path.getsize(job.dst)
        f = open(job.dst, "rb")
    except OSError:
        return _reply(handler, 410, {"error": "the converted file is gone"})
    job.sending = True
    sent = 0
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", MIME[job.fmt])
        handler.send_header("Content-Length", str(size))
        handler.send_header("Content-Disposition", "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (ascii_fn, quote(fn)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        with f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                handler.wfile.write(chunk)
                sent += len(chunk)
    except OSError:
        pass   # the page went away mid-send: the result stays for a retry until KEEP_DONE_S
    finally:
        job.sending = False
        try:
            f.close()
        except Exception:
            pass
    if sent >= size:
        drop(job)
    return True
