#!/usr/bin/env python3
"""RTSP ingest bridge.

Browsers cannot open RTSP -- there is no API for it and no flag to enable one.
So an ffmpeg child process pulls the RTSP feed and remuxes it to fragmented MP4,
which this module streams over plain HTTP to a <video> element in the page. The
page then does videoEl.captureStream() and publishes the resulting track over
MoQ, which is the same route the library's own "file" source takes.

    RTSP camera --> ffmpeg --> fMP4 over HTTP --> <video> --> captureStream()
                                                          --> MoQ Video.Encoder

Endpoints (wired up by kastr_serve):
    POST /api/rtsp/add     {"url": "rtsp://..."}  -> {"id": 1, "path": "/rtsp/1"}
    POST /api/rtsp/remove  {"id": 1}              -> {"ok": true}
    GET  /api/rtsp/list                           -> {"feeds": [...], "ffmpeg": bool}
    GET  /rtsp/<id>                               -> endless fragmented MP4

Transcoding costs latency -- expect a few hundred ms on top of the sub-100ms
WebCodecs path. Video is re-encoded to H.264 baseline because that is what
every browser can decode from an MP4 container; audio to AAC for the same
reason. `-tune zerolatency` and `-g 30` keep the fragment cadence tight.
"""
import json
import os
import shutil
import re
import subprocess
import time
import sys
import threading
import base64               # 0.12.0: token expiry from the jwt body
import urllib.request       # 0.12.0: the relay's token service (mint_member)
import urllib.error
from urllib.parse import urlsplit

# A synthetic feed, so the whole pipeline can be proven end to end without a
# camera on the network. Anything that reaches the <video> element here is also
# going to reach it from a real RTSP source.
TEST_URL = "test://pattern"
SCREEN_PREFIX = "screen://"      # 0.21.20: screen://monitor/<n> | screen://window/<hwnd> -- the host captures it natively


def is_screen(url):
    return str(url or "").strip().lower().startswith(SCREEN_PREFIX)

# Longest we will wait for ffmpeg to name a stream's codec.
PROBE_TIMEOUT = 20.0
# 0.21.10: on-demand pairs (0.18.0 standby) and low copies (0.18.0 / 0.21.7 `-low.hang`) are OFF unless this is
# true -- env KASTR_ONDEMAND=1 here (dev harness, rigs), kastr.ini `ondemand = on` through the launcher (kastr.py).
# Read once at boot. A Publisher built while it is off never sleeps and never owns a low sibling, but remembers
# what was ASKED (wantOndemand / wantLow) so rtsp-feeds.json keeps the operator's choice for a later re-enable.
ONDEMAND_ENABLED = str(os.environ.get("KASTR_ONDEMAND") or "").strip().lower() in ("1", "true", "yes", "on")
# 0.12.0: a probe that could not tell (camera off when a restored feed came
# back) is asked again after this long instead of being believed for the run.
PROBE_RETRY_S = 30.0

# Longest a write to a stream reader may block. A browser that stops reading
# (frozen demuxer, wedged tab, abandoned socket) used to block wfile.write()
# forever, which blocked ffmpeg on pipe:1, which stopped the RTSP pull --
# ffmpeg's own -timeout is socket IO on the camera side and cannot fire while
# the child is stuck writing. This turns "reader went quiet" into an OSError,
# so the finally in handle_stream releases the child and /api/rtsp/list
# stops claiming a wedged feed is running.
SEND_TIMEOUT = 15.0

# Widest frame we hand to the browser untouched. Above this the browser
# spends more time scaling than encoding, so the bridge does it instead.
MAX_WIDTH = 1920

# Encoders to try for that downscale, best first. Hardware where available;
# libx264 is the floor and always exists. 0.9.6: h264_vaapi covers Intel/AMD
# iGPUs on Linux (probe-validated like the rest; needs the render node below).
ENCODERS = ("h264_qsv", "h264_nvenc", "h264_amf", "h264_mf", "h264_vaapi", "libx264")
# Per-encoder extras: args that must precede -i, and a filter suffix that
# uploads frames to the device. Empty for every software/CPU-fed encoder.
ENCODER_EXTRA = {
    "h264_vaapi": {"pre": ["-vaapi_device", "/dev/dri/renderD128"], "vf": ",format=nv12,hwupload"},
}


def encoder_pre_args(encoder):
    return list(ENCODER_EXTRA.get(encoder or "", {}).get("pre", []))


def encoder_vf(encoder, vf):
    return vf + ENCODER_EXTRA.get(encoder or "", {}).get("vf", "")


# 0.9.6: what viewers can decode straight from the camera -- the hang catalog
# and MPEG-TS both carry these, so copying is a zero-encode publish. The
# passthrough option lifts the H.264 size/range limits and admits H.265;
# without it H.264 copies as before (<= MAX_WIDTH, limited range) and
# everything else is encoded to H.264 once. MJPEG/MPEG-4 cameras can never be
# passed: no viewer decodes them.
PASSTHROUGH_CODECS = ("h264", "hevc", "h265")

# 0.9.6: the monitor feeds the owner's preview and the 15 fps mosaic. When it
# cannot copy, it encodes SMALL and FAST -- this used to be a second full-rate,
# full-size encode per camera, which is what saturated 4-core boxes with three
# feeds ("streams drop out and come back").
MONITOR_WIDTH = 1280
MONITOR_FPS = 15

# 0.9.8: square pixels before anything else. A camera whose SPS says SAR 2:1
# sends 960x1080 pixels meant to be shown 1920 wide; every consumer of a copied
# stream sized its picture from the coded 960 and squeezed it. Resample to the
# display width (a no-op for square pixels; an unset SAR counts as square),
# then declare 1:1 -- the rest of each chain sees an ordinary frame.
SQUARE_PIXELS = "scale=w='if(gt(sar,0),trunc(iw*sar/2)*2,iw)':h=ih,setsar=1"

# 0.9.6: container handed to moq-cli. "ts" (MPEG-TS, -pes_payload_size 0) or
# "fmp4" (fragmented MP4). Measured in the rig on 2026-09-16 -- see
# ARCHITECTURE "Load is a count of encodes, not a thread".
PUBLISH_MUX = "ts"


def passthrough_ok(vcodec, width, fullrange, passthrough, sar=None):
    """Copy or encode? The one rule both the publisher and the monitor use.

    0.9.8: a camera with non-square pixels (SAR != 1:1) is never copied. The
    catalog the viewer sizes its picture from carries the coded frame size,
    so a copied anamorphic stream shows squeezed on every viewer; one encode
    with setsar=1 gives it square pixels and the right shape."""
    if sar_nonsquare(sar) and not os.environ.get("KASTR_IGNORE_SAR"):   # the env switch only exists to reproduce the old behaviour in a rig
        return False
    vc = (vcodec or "").lower()
    if vc not in PASSTHROUGH_CODECS:
        return False
    if passthrough:
        return True
    return vc == "h264" and (width or 0) <= MAX_WIDTH and not fullrange

def sar_nonsquare(sar):
    """(num, den) from the probe -> True when the pixels are not square."""
    try:
        a, b = int(sar[0]), int(sar[1])
    except (TypeError, ValueError, IndexError):
        return False
    return a > 0 and b > 0 and a != b


# 0.9.8: children die with KASTR. Publisher pairs (ffmpeg | moq) used to be
# plain children: a crash, a Task-Manager kill or close-kastr.ps1 left them
# publishing to the relay under this operator's paths, and the next KASTR saw
# its own cameras as a stranger's tiles it could not stop. Two layers:
#   * Windows: every child is assigned to one Job Object with
#     KILL_ON_JOB_CLOSE -- the OS ends them when this process ends, however it
#     ends. (KASTR_NO_JOB=1 disables it, to exercise the sweep.)
#   * Both platforms: every child is recorded in state_dir/rtsp-children-<pid>
#     .json and the next start reaps the recorded processes of a dead owner
#     -- matched by executable (and start time on Windows, argv on Linux), so
#     a reused PID is never someone else's process.
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x0800        # 0.16.0: a child may CREATE_BREAKAWAY_FROM_JOB (a relaunched KASTR must not die with the job)
JobObjectExtendedLimitInformation = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
STILL_ACTIVE = 259
_JOB_WARNED = [False]


def _k32():
    import ctypes
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _make_job(log=None):
    """A Job Object that kills its processes when the last handle closes (Windows)."""
    if sys.platform != "win32" or os.environ.get("KASTR_NO_JOB"):
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = _k32()
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)     # NULL name, non-inheritable handle
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
        if not k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                           ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
        return job
    except Exception as e:
        if log:
            log("rtsp: no job object for child processes (%s) -- relying on the startup sweep" % e)
        return None


_APP_JOB = [None, False]


def app_job(log=None):
    """The one job every KASTR child joins -- publishers, monitors and the
    relay (kastr_relay) alike. Created once per process; None where jobs are
    unavailable or disabled (KASTR_NO_JOB)."""
    if not _APP_JOB[1]:
        _APP_JOB[1] = True
        _APP_JOB[0] = _make_job(log)
    return _APP_JOB[0]


def _job_assign(job, proc, log=None):
    """Put one child into the job; a failure is logged once and tolerated."""
    if not job or proc is None:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        k32 = _k32()
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if not k32.AssignProcessToJobObject(job, wintypes.HANDLE(proc._handle)):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
        return True
    except Exception as e:
        if not _JOB_WARNED[0]:
            _JOB_WARNED[0] = True
            if log:
                log("rtsp: could not bind pid %s to the job (%s)" % (getattr(proc, "pid", "?"), e))
        return False


def _job_terminate(job):
    if not job:
        return
    try:
        from ctypes import wintypes
        k32 = _k32()
        k32.TerminateJobObject.restype = wintypes.BOOL
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.TerminateJobObject(job, 1)
    except Exception:
        pass


def _job_close(job):
    if not job:
        return
    try:
        from ctypes import wintypes
        k32 = _k32()
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle(job)
    except Exception:
        pass


def _pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = _k32()
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            try:
                code = wintypes.DWORD()
                k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
                if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != STILL_ACTIVE:
                    return False
                return True
            finally:
                k32.CloseHandle.argtypes = [wintypes.HANDLE]
                k32.CloseHandle(h)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _pid_image(pid):
    """(executable path, creation epoch or None, argv list or None) of a live process."""
    pid = int(pid)
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = _k32()
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None, None, None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            exe = buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
            created = None
            ft = [wintypes.FILETIME() for _ in range(4)]
            k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            if k32.GetProcessTimes(h, *[ctypes.byref(f) for f in ft]):
                t = (ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime
                created = t / 1e7 - 11644473600.0
            return exe, created, None
        finally:
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.CloseHandle(h)
    exe = None
    try:
        exe = os.readlink("/proc/%d/exe" % pid).replace(" (deleted)", "")
    except OSError:
        pass
    argv = None
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
    except OSError:
        pass
    return exe, None, argv


def _same_file(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (TypeError, ValueError):
        return False


def _pid_matches(rec):
    """Is the recorded child still the process at that PID? (PID reuse guard.)"""
    pid = rec.get("pid")
    if not _pid_alive(pid):
        return False
    try:
        exe, created, argv = _pid_image(pid)
    except Exception:
        return False
    want = rec.get("exe") or ""
    if want:
        if not (exe and _same_file(exe, want)) and not (argv and _same_file(argv[0], want)):
            return False
    if created is not None and rec.get("started"):
        if abs(created - float(rec["started"])) > 5:
            return False
    sig = rec.get("sig") or []
    if argv is not None and sig:
        joined = " ".join(argv)
        if not all(str(tok) in joined for tok in sig):
            return False
    return True


def _kill_pid(pid):
    pid = int(pid)
    if sys.platform == "win32":
        try:
            from ctypes import wintypes
            k32 = _k32()
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if not h:
                return False
            try:
                k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
                return bool(k32.TerminateProcess(h, 1))
            finally:
                k32.CloseHandle.argtypes = [wintypes.HANDLE]
                k32.CloseHandle(h)
        except Exception:
            return False
    try:
        import signal
        os.kill(pid, signal.SIGKILL)
        return True
    except OSError:
        return False


# 0.9.10: sweep by what a helper IS, not by who wrote it down. The registry
# reaps what a 0.9.8+ run recorded; publisher pairs left by an older version
# (no job, no registry) and any orphaned monitor, probe or moq-relay were
# invisible to it. This lists every process running a bundled helper -- from a
# frozen extraction (`_MEIxxxx/bin`) or one of this install's helper folders --
# whose parent is no longer a live KASTR (or Python, for the dev harness).
HELPER_STEMS = ("ffmpeg", "moq", "moq-relay")


def helper_names():
    return tuple(n + (".exe" if sys.platform == "win32" else "") for n in HELPER_STEMS)


def helper_versions():
    """0.16.0: bin/.versions.json (fetch-helpers.py stamps what it fetched) -> dict."""
    for root in helper_roots():
        try:
            with open(os.path.join(root, ".versions.json"), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            continue
    return {}


def helper_roots():
    """Where bundled helpers live for THIS run (frozen extraction first)."""
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.join(sys._MEIPASS, "bin"))
    roots.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin"))
    return roots


def _processes():
    """[(pid, ppid, image basename)] for every process -- Toolhelp32 on Windows
    (no PowerShell spawn), /proc on Linux. Empty list when unavailable."""
    out = []
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = _k32()
            TH32CS_SNAPPROCESS = 0x2

            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                            ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
            k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
            k32.Process32FirstW.restype = wintypes.BOOL
            k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
            k32.Process32NextW.restype = wintypes.BOOL
            k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
            invalid = (1 << (8 * ctypes.sizeof(ctypes.c_void_p))) - 1
            snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if not snap or snap == invalid:
                return out
            try:
                e = PROCESSENTRY32W()
                e.dwSize = ctypes.sizeof(e)
                ok = k32.Process32FirstW(snap, ctypes.byref(e))
                while ok:
                    out.append((int(e.th32ProcessID), int(e.th32ParentProcessID), str(e.szExeFile)))
                    ok = k32.Process32NextW(snap, ctypes.byref(e))
            finally:
                k32.CloseHandle.argtypes = [wintypes.HANDLE]
                k32.CloseHandle(snap)
        except Exception:
            return out
        return out
    try:
        for fn in os.listdir("/proc"):
            if not fn.isdigit():
                continue
            pid = int(fn)
            try:
                with open("/proc/%d/stat" % pid, "r", encoding="utf-8", errors="replace") as f:
                    st = f.read()
                rest = st[st.rindex(")") + 2:].split()
                ppid = int(rest[1])
            except (OSError, ValueError, IndexError):
                continue
            try:
                name = os.path.basename(os.readlink("/proc/%d/exe" % pid).replace(" (deleted)", ""))
            except OSError:
                name = ""
            out.append((pid, ppid, name))
    except OSError:
        pass
    return out


def _is_helper_path(exe, own_dirs):
    """A bundled helper: under a `_MEI*/bin` folder, or in one of our helper dirs."""
    if not exe:
        return False
    parts = [p.lower() for p in re.split(r"[\\/]+", exe) if p]
    for i in range(len(parts) - 2):
        if parts[i].startswith("_mei") and parts[i + 1] == "bin":
            return True
    d = os.path.dirname(exe)
    return any(_same_file(d, o) for o in own_dirs if o)


def _kastr_like(image):
    n = (image or "").lower()
    return n.startswith("kastr") or n.startswith("python")


def helper_orphans(own_dirs=None, procs=None, image_of=None):
    """List-only: bundled helper processes whose parent is not a live KASTR/Python.
    Returns [{pid, ppid, name, exe, parent, why}]. `procs`/`image_of` are
    injectable for tests."""
    names = set(n.lower() for n in helper_names())
    own_dirs = list(own_dirs if own_dirs is not None else helper_roots())
    rows = _processes() if procs is None else procs
    by_pid = {pid: (ppid, name) for pid, ppid, name in rows}
    image_of = image_of or (lambda pid: _pid_image(pid)[0])
    me = os.getpid()
    out = []
    for pid, ppid, name in rows:
        if pid == me or ppid == me or (name or "").lower() not in names:
            continue
        try:
            exe = image_of(pid)
        except Exception:
            exe = None
        if not _is_helper_path(exe, own_dirs):
            continue
        parent = by_pid.get(ppid)
        if parent is None or not _pid_alive(ppid):
            why = "parent %d is gone" % ppid
        elif not _kastr_like(parent[1]):
            why = "parent %d is %s, not KASTR" % (ppid, parent[1] or "?")
        else:
            continue
        out.append({"pid": pid, "ppid": ppid, "name": name, "exe": exe,
                    "parent": parent[1] if parent else None, "why": why})
    return out


def registry_files(state_dir):
    """List-only view of the child registries in a state dir (for --diagnose)."""
    out = []
    if not state_dir or not os.path.isdir(state_dir):
        return out
    for fn in sorted(os.listdir(state_dir)):
        if fn.startswith("rtsp-children-") and fn.endswith(".json"):
            try:
                with open(os.path.join(state_dir, fn), encoding="utf-8") as f:
                    d = json.load(f)
                out.append("%s: owner %s%s, %d child(ren)" % (
                    fn, d.get("owner"), "" if _pid_alive(d.get("owner")) else " (dead)", len(d.get("children") or [])))
            except Exception as e:
                out.append("%s: unreadable (%s)" % (fn, e))
    return out


def _rtsp_leaf(url):
    """0.21.2: a broadcast leaf for a camera URL nobody named: host + last path segment (never credentials)."""
    try:
        from urllib.parse import urlsplit
        u = urlsplit(str(url or ""))
        seg = [s for s in u.path.split("/") if s]
        return "-".join(x for x in ((u.hostname or "").replace(".", "-"), seg[-1] if seg else "") if x) or "cam"
    except Exception:
        return "cam"


def _relay_key(url):
    """A relay URL without its room token: same relay, whatever the token says.
    0.13.3: nor is a trailing "/" a different relay -- mint_member returns
    `base + "/"`, the page posts without, and every adopt tore a healthy pair
    down on the mismatch (`reused` stuck at 0 was the tell)."""
    u = (url or "").strip()
    u = re.sub(r"([?&])jwt=[^&]*&?", r"\1", u)
    return u.rstrip("?&").rstrip("/").lower()


# ---- 0.12.0: tokens, redaction, the relay's minter --------------------------
def _relay_token(url):
    """The `jwt=` value of a relay URL, "" when it carries none."""
    m = re.search(r"[?&]jwt=([^&#]*)", url or "")
    return m.group(1) if m else ""


def _jwt_exp(tok):
    """The `exp` claim (int, seconds) of a JWT, None when absent or unreadable.
    Tolerant: no signature check, padding restored, any junk -> None."""
    try:
        body = str(tok or "").split(".")[1]
        d = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8", "replace"))
        exp = d.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


def _redact(text):
    """Log text with every `jwt=<token>` replaced -- moq never prints the token
    today, but the URL we hand it does carry one; nothing stored may."""
    return re.sub(r"jwt=[A-Za-z0-9._-]+", "jwt=<jwt>", text or "")


def _redact_url(u):
    """A camera URL for the page/log: `user:pass@` -> `***@`."""
    return re.sub(r"://([^/@]*)@", "://***@", u or "")


def _seed_label(broadcast, url):
    """0.14.0: the page's label for a kept feed (rtspPersistSet stores
    {url, label}). The broadcast is HOST/op/<slug(label)>: its leaf IS that
    slug. Without one, rtspLabel(url): last path segment minus a media
    extension, else the host, slugged."""
    leaf = (broadcast or "").strip().rsplit("/", 1)[-1]
    if leaf:
        return leaf
    try:
        rest = re.sub(r"^[a-z0-9+.-]+://", "", url or "")
        rest = rest.split("@", 1)[-1]
        host, _, path = rest.partition("/")
        seg = [p for p in path.split("?", 1)[0].split("/") if p]
        seg = re.sub(r"\.(mp4|webm|mkv|mov|avi|flv|m3u8|mpd|ts|mp3|aac|ogg)$", "", seg[-1], flags=re.I) if seg else ""
        base = seg or host.split(":", 1)[0]
        slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
        return slug or "rtsp"
    except Exception:
        return "rtsp"


# RE-MEASURED 2026-10-05 on moq CLI 0.14.0 + moq-relay 0.17.0 (secured): the same HARD ("connection loop exited
# err=unauthorized" / "Error: unauthorized", exit 1) and SOFT ("session closed, reconnecting") lines; 0.14.0 rides a
# 25 s outage by itself (keeps reconnecting) instead of exiting.
# What moq says about its relay session (moq CLI 0.11.2, measured 2026-09-19;
# RE-MEASURED 2026-09-25 on moq CLI 0.12.1 + moq-relay 0.15.1 with KASTR's auth
# server -- the same strings still fire: a refused token prints "Error: unauthorized"
# (HARD -> park -> re-mint, seen at first publish with a stale session token and
# again after `POST /api/relay/rotate`); a relay bounce prints "session closed,
# reconnecting peer=..." (SOFT, counted, the pair survives a 6 s bounce); a 25 s
# outage lets --backoff-timeout 10s expire and moq exits, which the pipe reports
# as ffmpeg exit 0xFFFFFFE0 (EPIPE) -> the ladder restarts, never parks).
# HARD: the relay refused the session -- a stale/invalid token, or moq's
# reconnect loop giving up (it exits 1 right after). Restarting with the same
# URL cannot help; only a fresh token can. SOFT: the session dropped and moq
# is reconnecting on its own (a relay bounce) -- counted, nothing to do.
HARD_RE = re.compile(r"unauthori[sz]ed|token (expired|invalid|does not grant)|code=6\b", re.I)
# 0.12.0: `reconnect timed out after` / `reconnect loop exited` are NOT hard on their own -- moq prints them
# for a plain relay outage too (measured: the dead-token exit line carries "unauthorized"); an outage must
# ladder, not park.
SOFT_RE = re.compile(r"session severed|session closed", re.I)


def _relay_base(relay_url):
    """-> (base 'scheme://host:port', minter 'http://host:port+1') or (None, why).
    0.19.0: a web relay -> ('https://name/relay', 'https://name') -- its web port
    carries the minter (proxied) and the media (WebSocket)."""
    u = (relay_url or "").strip()
    if not u:
        return None, "no relay url"
    try:
        import kastr_relay as _kr
        if _kr.is_web_relay(u):
            o = _kr.web_origin(u)
            return ((o + _kr.WEB_RELAY_PATH, o), None) if o else (None, "bad relay url")
    except ImportError:
        pass
    try:
        p = urlsplit(u if "://" in u else "http://" + u)
    except Exception as e:
        return None, "bad relay url: %s" % e
    host = p.hostname or ""
    if not host:
        return None, "relay url has no host"
    scheme = (p.scheme or "http").lower()
    scheme = {"ws": "http", "wss": "https"}.get(scheme, scheme)
    port = p.port or 4443
    h = ("[%s]" % host) if ":" in host else host
    return ("%s://%s:%d" % (scheme, h, port), "http://%s:%d" % (h, port + 1)), None


def mint_member(relay_url, room, access, room_code, timeout=5, host=None):
    """0.12.0: a member token for `room` from the relay's token service
    (relay-port+1) -> (status, url, detail), status in
        "open"    -- no minter, but the relay answers /certificate.sha256: the bare URL works
        "token"   -- url carries a fresh `?jwt=`; detail = the role minted
        "refused" -- wrong access or room code (retrying cannot help)
        "down"    -- unreachable, locked out (429) or an unexpected answer
    0.13.0: `host` (this machine's kastr_serve.host_slug) rides the body when
    given, so the minter scopes the puts to this host's own paths.
    urllib only; never raises."""
    parts, why = _relay_base(relay_url)
    if not parts:
        return "down", None, why
    base, minter = parts
    try:
        with urllib.request.urlopen(minter + "/api/auth", timeout=timeout) as r:
            auth = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except Exception as e:
        # no token service: an open relay has none at all -- is the relay itself up?
        try:
            probe = (minter + "/api/instance") if base.endswith("/relay") else (base + "/certificate.sha256")   # 0.19.0: a web relay
            with urllib.request.urlopen(probe, timeout=2) as r:
                r.read(128)
            return "open", base + ("" if base.endswith("/relay") else "/"), "no minter"
        except Exception as e2:
            return "down", None, "minter: %s; relay: %s" % (e, e2)
    if not isinstance(auth, dict) or not auth.get("secured"):
        return "open", base + ("" if base.endswith("/relay") else "/"), "relay is not secured"
    body = {"room": str(room or ""), "code": str(access or "")}
    if room_code:
        body["roomCode"] = str(room_code)
    if host:
        body["host"] = str(host)
    req = urllib.request.Request(minter + "/api/token", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        err = ""
        try:
            err = str(json.loads(e.read().decode("utf-8", "replace") or "{}").get("error") or "")
        except Exception:
            pass
        if e.code == 403:
            return "refused", None, err or "refused"
        if e.code == 429:
            return "down", None, "locked out" + ((" (%s)" % err) if err else "")
        return "down", None, "minter answered %d%s" % (e.code, (" (%s)" % err) if err else "")
    except Exception as e:
        return "down", None, str(e)
    tok = (d.get("tokens") or {}).get("member") if isinstance(d, dict) else None
    if not isinstance(d, dict) or not d.get("ok") or not tok:
        return "down", None, "minter answered without a token: %s" % ((d.get("error") if isinstance(d, dict) else None) or "?")
    return "token", base + ("" if base.endswith("/relay") else "/") + "?jwt=" + str(tok), str(d.get("role") or "member")   # 0.19.0: https://name/relay?jwt=


# URL paths that ARE the media -- handed to ffmpeg as-is. A page on a known
# video site is refused with a clear reason (0.9.3: the yt-dlp resolver was
# dropped -- a moving target in a 5 MB dependency the field never used); an
# unknown http(s) host still goes to ffmpeg verbatim, which handles HLS/DASH
# manifests and direct files.
MEDIA_EXTS = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv",
              ".m3u8", ".mpd", ".ts", ".mp3", ".aac", ".ogg")
PAGE_SITES = ("youtube", "youtu.be", "vimeo", "twitch", "dailymotion")


# ---- 0.21.26 (Kenton: grids take "screen, window, tab, RTSP/HTTP, media file, etc"): HOST FEEDS --------------------
# A camera on THIS computer (device://video/<name>) or a media file uploaded to it (media://<32 hex id>) becomes a feed
# like an RTSP camera: published natively, in any grid, kept after a restart. A webcam opens only once, so the bridge
# captures it ONE time (DeviceCapture) and fans an H.264 MPEG-TS copy out over loopback UDP -- one port per reader
# (publisher, monitor, low copy). A media file is simply read by each reader, looped at real time.
DEVICE_PREFIX = "device://video/"
MEDIA_PREFIX = "media://"
HOSTMEDIA_DIR = [None]   # set by the Bridge: <state>/hostmedia (a copy of the upload that outlives the upload's own life)
DEVICES = {}             # url -> DeviceCapture
DEVICE_ROLES = ("pub", "mon", "low")
# 0.21.30 (field: a GoPro on RTMP ingest -> "bind failed: Error number -10048" = the monitor's port was already held):
# a port takes ONE reader, but a feed can have several monitors at once (a reconnect while the old one is still dying,
# the window and a web client of the same box) -- so the capture sends to MON_SLOTS monitor ports and each monitor
# claims a free one. Ports come from below every OS's ephemeral range, where outgoing sockets (QUIC, DNS) never land.
MON_SLOTS = 6
LOOP_PORTS = (20000, 31999)


def is_device(url):
    return str(url or "").startswith(DEVICE_PREFIX)


def is_hostmedia(url):
    return str(url or "").startswith(MEDIA_PREFIX)


# 0.21.29 (Kenton: "does a KASTR relay have an RTMP URL that I can point devices to, such as a go pro"): an RTMP INGEST --
# KASTR listens (ffmpeg -listen 1) on its own port per stream (one ffmpeg listener per port) for rtmp://<this host>:<port>/
# live/<key>; whatever a device pushes is fanned out like a host camera (copied, no re-encode) to the publisher, monitor
# and low copy. The key is random per stream, so nobody else can push into it.
RTMP_PREFIX = "rtmp-in://"
RTMP_PORTS = range(1935, 1945)


def is_rtmp_in(url):
    return str(url or "").startswith(RTMP_PREFIX)


def rtmp_parts(url):
    """rtmp-in://<port>/<key> -> (port, key) or (None, None)."""
    m = re.match(r"^rtmp-in://(\d{2,5})/([A-Za-z0-9]{6,40})$", str(url or ""))
    if not m or int(m.group(1)) not in RTMP_PORTS:
        return None, None
    return int(m.group(1)), m.group(2)


def rtmp_ports_in_use():
    return sorted({rtmp_parts(u)[0] for u in DEVICES if is_rtmp_in(u)} - {None})


def rtmp_free_port():
    """The first port of RTMP_PORTS no ingest uses and nothing else listens on (TCP)."""
    import socket
    used = set(rtmp_ports_in_use())
    for p in RTMP_PORTS:
        if p in used:
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return None


def is_host_feed(url):
    return is_device(url) or is_hostmedia(url) or is_rtmp_in(url)


def device_name(url):
    from urllib.parse import unquote
    return unquote(str(url)[len(DEVICE_PREFIX):]).strip()


def hostmedia_path(url):
    mid = str(url)[len(MEDIA_PREFIX):].strip().lower()
    d = HOSTMEDIA_DIR[0]
    if not re.match(r"^[0-9a-f]{32}$", mid) or not d or not os.path.isdir(d):
        return None
    for fn in sorted(os.listdir(d)):
        if fn.startswith(mid + ".") and re.match(r"^[0-9a-f]{32}\.[a-z0-9]{1,5}$", fn):
            return os.path.join(d, fn)
    return None


def list_devices(ffmpeg):
    """The cameras this computer can capture: Windows = DirectShow video devices (by name), Linux = /dev/video*."""
    out = []
    if sys.platform.startswith("win") and ffmpeg:
        try:
            r = subprocess.run([ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                               capture_output=True, text=True, errors="replace", timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in (r.stderr or "").splitlines():
                m = re.search(r'"([^"]+)"\s*\(video\)', line)
                if m and m.group(1) not in out:
                    out.append(m.group(1))
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        import glob
        out = sorted(glob.glob("/dev/video*"))
    return out


def _udp_free(port):
    """0.21.30: can a reader bind this loopback port right now?"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _free_udp_port(avoid=()):
    """0.21.30: a free loopback UDP port OUTSIDE the ephemeral ranges (Windows 49152+, Linux 32768+) -- an ephemeral
    port can be handed to any outgoing socket between our pick and the reader's bind."""
    import random
    import socket
    for _ in range(200):
        p = random.randint(LOOP_PORTS[0], LOOP_PORTS[1])
        if p not in avoid and _udp_free(p):
            return p
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


class DeviceCapture:
    """One ffmpeg owns the camera; H.264 (baseline, 2 s GOP, <= 1280 wide) goes out to one loopback UDP port per
    reader. Restarted with a back-off when it exits; stopped with the feed."""

    def __init__(self, ffmpeg, url, log=None):
        self.ffmpeg, self.url, self.log = ffmpeg, url, (log or (lambda m: None))
        self.ports = {}
        for r in DEVICE_ROLES:
            self.ports[r] = _free_udp_port(avoid=set(self.ports.values()))
        self.mon_ports = [self.ports["mon"]]   # 0.21.30: monitor slot 0 is ports["mon"]
        while len(self.mon_ports) < MON_SLOTS:
            self.mon_ports.append(_free_udp_port(avoid=set(self.ports.values()) | set(self.mon_ports)))
        self.claims = {}                       # 0.21.30: monitor port -> its ffmpeg (or the time it was handed out)
        self._claim_lock = threading.Lock()
        self.proc = None
        self.stopped = False
        self.restarts = 0
        self.last_error = ""

    def args(self):
        if is_rtmp_in(self.url):   # 0.21.29: wait for a device to push, copy what it sends (video + audio) to every reader
            port, key = rtmp_parts(self.url)
            tee = self._tee()
            return [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "flv", "-listen", "1",
                    "-i", "rtmp://0.0.0.0:%d/live/%s" % (port, key), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                    "-f", "tee", tee]
        name = device_name(self.url)
        if name == "kastr-test":   # rig: a test pattern stands in for a camera
            src = ["-re", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30"]
        elif sys.platform.startswith("win"):
            src = ["-f", "dshow", "-rtbufsize", "128M", "-i", "video=" + name]
        else:
            src = ["-f", "v4l2", "-i", name]
        tee = self._tee()
        return ([self.ffmpeg, "-hide_banner", "-loglevel", "error"] + src
                + ["-an", "-vf", "scale=w='min(iw,1280)':h=-2,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                   "-tune", "zerolatency", "-profile:v", "baseline", "-g", "60", "-bf", "0", "-b:v", "3M", "-maxrate", "3M",
                   "-bufsize", "3M", "-map", "0:v:0", "-f", "tee", tee])

    def out_ports(self):
        """Every loopback port the capture sends to: publisher, low copy, then the monitor slots."""
        return [self.ports["pub"], self.ports["low"]] + list(self.mon_ports)

    def _tee(self):
        # an unbound loopback port is the normal case (no reader yet) -- UDP sends to it never fail
        return "|".join("[f=mpegts]udp://127.0.0.1:%d?pkt_size=1316" % p for p in self.out_ports())

    def claim_mon(self):
        """0.21.30: a monitor port nobody reads -- its last ffmpeg has exited and the port binds. None when all are busy."""
        now = time.time()
        with self._claim_lock:
            for p in self.mon_ports:
                h = self.claims.get(p)
                if isinstance(h, float) and now - h < 15:
                    continue                                   # handed out, its ffmpeg is starting
                if h is not None and not isinstance(h, float) and h.poll() is None:
                    continue                                   # a running monitor reads it
                if not _udp_free(p):
                    continue                                   # something else holds it (a dying reader)
                self.claims[p] = now
                return p
        return None

    def attach(self, port, proc):
        with self._claim_lock:
            self.claims[port] = proc

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        wait = 1.0
        while not self.stopped:
            t0 = time.time()
            try:
                self.proc = subprocess.Popen(self.args(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                             errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                err = self.proc.stderr.read() if self.proc.stderr else ""
                self.proc.wait()
                self.last_error = (err or "").strip()[-300:]
            except Exception as e:
                self.last_error = str(e)[:300]
            if self.stopped:
                return
            self.restarts += 1
            if is_rtmp_in(self.url):   # 0.21.29: the device stopped pushing (or never came) -- listen again at once
                self.log("rtsp: RTMP ingest on port %s ended (%s) -- listening again" % (rtmp_parts(self.url)[0], self.last_error or "the device disconnected"))
                time.sleep(1.0)
                continue
            self.log("rtsp: camera capture %s ended (%s) -- again in %.0f s" % (device_name(self.url), self.last_error or "no reason given", wait))
            wait = 1.0 if time.time() - t0 > 60 else min(30.0, wait * 2)
            time.sleep(wait)

    def stop(self):
        self.stopped = True
        p = self.proc
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass


def input_args(url, role="pub", claim=None):
    if is_device(url) or is_rtmp_in(url):   # 0.21.26: the bridge's one capture of this camera, on this reader's own loopback port; 0.21.29: + RTMP ingest
        cap = DEVICES.get(url)
        if cap and role == "mon":   # 0.21.30: a free monitor slot (several monitors may read one capture)
            port = cap.claim_mon()
            if port is None:
                raise RuntimeError("every monitor of this camera is in use (%d) -- close one and try again" % len(cap.mon_ports))
            if claim is not None:
                claim["port"] = port
            return ["-f", "mpegts", "-i", "udp://127.0.0.1:%d?fifo_size=1000000&overrun_nonfatal=1" % port]
        port = cap.ports.get(role if role in DEVICE_ROLES else "pub") if cap else 0
        if port:   # 0.21.30: the previous reader of this port may still be dying -- give it up to 3 s
            for _ in range(30):
                if _udp_free(port):
                    break
                time.sleep(0.1)
        return ["-f", "mpegts", "-i", "udp://127.0.0.1:%d?fifo_size=1000000&overrun_nonfatal=1" % port]
    if is_hostmedia(url):   # 0.21.26: a media file on this host, looped at real time
        return ["-re", "-stream_loop", "-1", "-i", hostmedia_path(url) or "missing-media-file"]
    if is_screen(url):   # 0.21.20: Windows Graphics Capture, scaled on the GPU side of the capture, constant 30 fps
        import kastr_screen
        return kastr_screen.capture_input(url)
    if url == TEST_URL:
        return [
            "-re",                                  # emit at real time, not as fast as possible
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
        ]
    low = url.strip().lower()
    if low.startswith(("http://", "https://")):
        # Media over HTTP(S): a direct file or an HLS/DASH manifest. None of
        # the rtsp knobs apply -- and neither
        # -re nor reconnect belongs on a static file: reconnect restarts
        # fought the demuxer's Range seeks (NAL corruption, observed live),
        # and pacing is pointless because the <video> element plays the
        # timestamped output at 1x no matter how fast it arrives. Live
        # manifests keep reconnects for flaky sources; they pace themselves.
        live = low.split("?", 1)[0].endswith((".m3u8", ".mpd"))
        args = []
        if live:
            args += ["-reconnect", "1", "-reconnect_streamed", "1",
                     "-reconnect_delay_max", "5"]
        args += ["-i", url]
        return args
    secure = url.strip().lower().startswith("rtsps://")

    args = [
        # tcp because UDP loses fragments on most corp networks. This is also
        # correct for rtsps: "tls" is NOT a valid value here -- ffmpeg rejects
        # it outright -- the scheme alone tells ffmpeg to wrap the connection.
        "-rtsp_transport", "tcp",
    ]

    if secure:
        # The actual reason rtsps failed: ffmpeg reported
        #   "Peer certificate failed verification"
        # Cameras like UniFi Protect present a self-signed certificate on
        # their rtsps port, and nothing could validate an IP address on a
        # local network anyway. So verification is off by necessity: the
        # stream is still encrypted in transit, the camera is not authenticated.
        args += ["-tls_verify", "0"]

    args += [
        # Fail in ten seconds rather than blocking on connect forever. Without
        # this an unreachable camera produces no bytes AND no stderr, so the
        # page cannot tell "still starting up" from "never coming".
        "-timeout", "10000000",   # 0.13.2: NOT -rw_timeout -- the RTSP demuxer rejects it ("Option rw_timeout not found"), 0.13.1 killed every camera pair with it     # microseconds
        # 0.13.1: -timeout covers the connect; a camera that stops sending
        # mid-stream (rtsp over tcp) needs the read/write timeout too, or the
        # pair hangs silent until the QUIC side notices nothing arrives.
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        # Untouched, so a query string such as ?enableSrtp survives.
        "-i", url,
    ]
    return args


def output_args(url, copy_video, encoder=None, width=None, hvc1=False):
    """Args after the input, for the MONITOR stream (fragmented MP4 to pipe:1).

    copy_video repackages without touching the video (`hvc1` tags an H.265
    copy so the <video> element accepts the fMP4). Otherwise `encoder` says
    how to re-encode it -- 0.9.6: capped at MONITOR_WIDTH and MONITOR_FPS with
    the fastest preset, because this picture only feeds a preview and the
    15 fps mosaic; `width` (legacy) caps lower still when given.
    """
    args = []

    if url != TEST_URL:
        # Video ONLY, deliberately. Bisected on a real camera: with its audio
        # muxed in, the browser's element capture delivers video at ~1 fps;
        # strip the audio and the same stream captures at the full ~30 fps.
        # Resampling did not help (48 kHz was just as slow), so the audio
        # track itself is what throttles capture. Nothing is lost: this stream
        # is the mosaic's source and the local monitor; the camera's audio
        # rides the native publisher's own path (0.9.1) unless the operator
        # turns it off for that feed (0.9.5).
        args += ["-map", "0:v:0"]

    if copy_video:
        # The camera already sends something the <video> element decodes, so
        # repackage rather than re-encode. This is the difference between
        # keeping up with a live feed and falling behind it.
        args += ["-c:v", "copy"]
        if hvc1:
            args += ["-tag:v", "hvc1"]   # 0.9.6: H.265 in fMP4 needs the hvc1 brand for Chrome
    else:
        # -2 keeps the aspect ratio and an even height, which yuv420p requires.
        # out_range=tv is the part that matters: a full-range camera produces
        # frames the browser's H.264 encoder rejects outright, and format=
        # yuv420p alone does NOT convert the range -- it only renames the
        # format. Without this the encoder throws "Encoding error", the
        # library rebuilds it, and viewers get RESET_STREAM and a black frame.
        # 0.9.6: never wider than MONITOR_WIDTH (the mosaic is 720 rows).
        cap = min(int(width), 1920 if is_screen(url) else MONITOR_WIDTH) if width else MONITOR_WIDTH   # 0.21.20: a presenter screen may be 1920 wide
        scale = "scale=w='min(iw,%d)':h=-2:in_range=pc:out_range=tv" % cap
        enc = encoder or "libx264"
        args += ["-vf", encoder_vf(enc, SQUARE_PIXELS + "," + scale + ",format=yuv420p"),   # 0.9.8: square pixels first
                 "-color_range", "tv", "-colorspace", "bt709",
                 "-r", str(MONITOR_FPS)]

        args += ["-c:v", enc]
        if enc == "libx264":
            args += [
                "-preset", "ultrafast",
                "-tune", "zerolatency",
                "-profile:v", "baseline",
                "-pix_fmt", "yuv420p",
                "-crf", "28",
                "-threads", "2",
            ]
        else:
            # Hardware encoders want a target rate rather than a CRF, and
            # their own low-latency switches vary, so keep it to the basics.
            args += ["-b:v", "1500k"]
        args += ["-g", str(MONITOR_FPS * 2)]

    args += [
        "-an",   # see above: bridge output is video-only
        "-f", "mp4",
        # Fragmented + empty moov = playable before the stream ends, which a
        # live feed never does. default_base_moof keeps Chrome's parser happy.
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-frag_duration", "200000",     # 200ms fragments
        "pipe:1",
    ]
    return args

def _darwin_fallback(exe):
    """0.13.1: a Finder-launched .app has a bare PATH -- look where Homebrew
    (Apple Silicon, Intel) installs before giving up on shutil.which."""
    if sys.platform != "darwin":
        return None
    for d in ("/opt/homebrew/bin", "/usr/local/bin"):
        cand = os.path.join(d, exe)
        if os.path.exists(cand):
            return cand
    return None


def find_ffmpeg():
    """Bundled copy first, then PATH.

    The packaged app ships ffmpeg.exe alongside the web files so operators do
    not have to install anything; a dev checkout falls back to PATH.
    """
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.join(sys._MEIPASS, "bin"))
    roots.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin"))
    for root in roots:
        cand = os.path.join(root, exe)
        if os.path.exists(cand):
            # A bundled binary loses its executable bit on some unpack paths.
            _ensure_exec(cand)
            return cand
    return _darwin_fallback(exe) or shutil.which("ffmpeg")


def find_moq():
    """0.9.1: the bundled moq-cli (native MoQ publisher), bundled copy then PATH."""
    exe = "moq.exe" if sys.platform == "win32" else "moq"
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.join(sys._MEIPASS, "bin"))
    roots.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin"))
    for root in roots:
        cand = os.path.join(root, exe)
        if os.path.exists(cand):
            _ensure_exec(cand)
            return cand
    return _darwin_fallback(exe) or shutil.which("moq")


def publish_output_args(copy_video, encoder=None, width=None, audio=True, mux=None, audio_input=0, screen=False):
    """0.9.1: ffmpeg output for the native publisher -- MPEG-TS on stdout with
    audio carried (AAC) unless the operator turned it off for this feed (0.9.5:
    audio=False -> video only, -an), video copied when the camera is already
    H.264 and otherwise encoded once. This replaces the browser's second encode.
    0.21.20: a screen share's sound is a second input (audio_input=1, PCM on stdin) and screens get
    a higher bitrate -- text needs it."""
    args = ["-map", "0:v:0"] + (["-map", "%d:a:0%s" % (audio_input, "" if audio_input else "?")] if audio else [])
    if copy_video:
        args += ["-c:v", "copy"]
    else:
        scale = "scale=%s:-2:in_range=pc:out_range=tv" % (width or "iw")
        enc = encoder or "libx264"
        args += ["-vf", encoder_vf(enc, SQUARE_PIXELS + "," + scale + ",format=yuv420p"), "-color_range", "tv", "-colorspace", "bt709"]   # 0.9.8: square pixels first
        args += ["-c:v", enc]
        if enc == "libx264":
            args += ["-preset", "veryfast", "-tune", "zerolatency", "-profile:v", "main", "-pix_fmt", "yuv420p", "-b:v", "5M" if screen else "3M"]
        else:
            args += ["-b:v", "6M" if screen else "4M"]
        args += ["-g", "60"]
    args += (["-c:a", "aac", "-b:a", "128k", "-ac", "2"] if audio else ["-an"])
    if (mux or PUBLISH_MUX) == "fmp4":
        args += ["-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-"]
    else:
        args += ["-f", "mpegts", "-pes_payload_size", "0", "-"]
    return args


# 0.18.0 (landscape item 5): the thumbnail rendition. A sibling broadcast
# `<leaf>-low.hang` carries the same camera at 640 wide / 15 fps / 400 kb/s (always an
# encode) so rail tiles and grid cells stop pulling the full stream. moq-cli builds the
# catalog, so the pairing is a naming convention the viewer page understands.
LOW_WIDTH = 640
LOW_FPS = 15
LOW_BITRATE = "400k"


def low_broadcast(name):
    """room/host/op/leaf.hang -> room/host/op/leaf-low.hang (idempotent)."""
    n = str(name or "")
    if n.endswith("-low.hang"):
        return n
    return (n[:-5] if n.endswith(".hang") else n) + "-low.hang"


def low_output_args(encoder=None):
    """ffmpeg output for the low rendition: video only, small, cheap, MPEG-TS on stdout."""
    enc = encoder or "libx264"
    scale = "scale=w='min(iw,%d)':h=-2:in_range=pc:out_range=tv" % LOW_WIDTH
    args = ["-map", "0:v:0", "-vf", encoder_vf(enc, SQUARE_PIXELS + "," + scale + ",format=yuv420p"),
            "-color_range", "tv", "-colorspace", "bt709", "-r", str(LOW_FPS), "-c:v", enc]
    if enc == "libx264":
        args += ["-preset", "ultrafast", "-tune", "zerolatency", "-profile:v", "baseline", "-pix_fmt", "yuv420p",
                 "-b:v", LOW_BITRATE, "-maxrate", LOW_BITRATE, "-bufsize", "800k", "-threads", "2"]
    else:
        args += ["-b:v", LOW_BITRATE]
    args += ["-g", str(LOW_FPS * 2), "-an", "-f", "mpegts", "-pes_payload_size", "0", "-"]
    return args


# 0.18.0 (landscape item 8): hooks -- operator commands run on feed events.
# kastr.ini hook_ready / hook_notready / hook_read (or KASTR_HOOK_READY/... in the
# environment for a dev checkout), each a shell command. They run detached with
# KASTR_EVENT, KASTR_BROADCAST, KASTR_FEED_ID, KASTR_RELAY (token-free), KASTR_REASON and
# KASTR_VIEWER set, stdout/stderr discarded, killed after hook_timeout seconds.
HOOK_EVENTS = ("ready", "notready", "read")
HOOK_READY_AFTER_S = 5          # a pair alive this long is "ready"


class Hooks:
    def __init__(self, cmds=None, log=None, timeout=30):
        cmds = cmds or {}
        self.cmds = {e: (str(cmds.get(e) or "").strip() or None) for e in HOOK_EVENTS}
        self.log = log or (lambda m: None)
        try:
            self.timeout = max(1, min(600, int(timeout)))
        except (TypeError, ValueError):
            self.timeout = 30
        self.fired = []          # the last 20 firings {at, event, broadcast, pid|error}

    @classmethod
    def from_env(cls, log=None):
        return cls({e: os.environ.get("KASTR_HOOK_" + e.upper()) for e in HOOK_EVENTS}, log,
                   os.environ.get("KASTR_HOOK_TIMEOUT") or 30)

    def configured(self):
        return {e: bool(c) for e, c in self.cmds.items()}

    def fire(self, event, broadcast="", feed_id="", relay="", reason="", viewer=""):
        cmd = self.cmds.get(event)
        if not cmd:
            return None
        env = dict(os.environ)
        env.update({"KASTR_EVENT": event, "KASTR_BROADCAST": str(broadcast or ""), "KASTR_FEED_ID": str(feed_id or ""),
                    "KASTR_RELAY": re.sub(r"\?jwt=[^&]*", "", str(relay or "")), "KASTR_REASON": str(reason or "")[:200],
                    "KASTR_VIEWER": str(viewer or "")[:120]})
        rec = {"at": time.time(), "event": event, "broadcast": broadcast}
        try:
            proc = subprocess.Popen(cmd, shell=True, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            rec["pid"] = proc.pid
            self.log("hook: %s %s -> pid %d" % (event, broadcast or "-", proc.pid))

            def reap(p=proc):
                try:
                    p.wait(timeout=self.timeout)
                except Exception:
                    try:
                        p.kill()
                        self.log("hook: %s %s pid %d killed after %d s" % (event, broadcast or "-", p.pid, self.timeout))
                    except Exception:
                        pass
            threading.Thread(target=reap, daemon=True).start()
        except Exception as e:
            rec["error"] = str(e)[:160]
            self.log("hook: %s %s failed to start: %s" % (event, broadcast or "-", e))
        self.fired.append(rec)
        del self.fired[:-20]
        return rec


PUBLISH_RETRY_S = [1, 2, 5, 10, 20, 30]


def nudge_bucket(why):
    """0.13.1: which counter a nudge reason lands in -- the page's viewer
    stall ("viewer", "stall*"), the page's no-echo heal ("no-echo"), or a
    plain API/tool call (anything else)."""
    w = str(why or "api").strip().lower()
    if w == "viewer" or w.startswith("stall"):
        return "viewer"
    if w in ("no-echo", "noecho", "no_echo"):
        return "noEcho"
    return "api"


class Publisher:
    """0.9.1: one camera on the relay without the browser -- ffmpeg | moq.

    ffmpeg pulls the feed (copy when H.264, else one hardware/x264 encode)
    and writes MPEG-TS to moq-cli, which publishes `broadcast` on `relay`
    (moq-lite; `?jwt=` in the URL carries a room token). Either process
    exiting restarts the pair on the RTSP retry ladder until stop()."""

    def __init__(self, bridge, feed, broadcast, relay, hevc=False, audio=True, passthrough=None,
                 minter=None, keep=True, ondemand=False, low=False, role="main", label=""):   # 0.12.0 / 0.18.0
        self.bridge = bridge
        self.feed = feed
        self.broadcast = broadcast
        self.relay = relay
        # 0.18.0: role "main" (the camera) or "low" (the thumbnail sibling it owns);
        # an on-demand main pair waits in STANDBY until a viewer asks (Bridge demand loop)
        self.role = role
        self.label = str(label or "")[:80]
        self.wantOndemand = bool(ondemand)   # 0.21.10: what was asked (persisted) ...
        self.wantLow = bool(low)
        self.ondemand = bool(ondemand) and role == "main" and ONDEMAND_ENABLED   # ... and what takes effect
        self.standby = self.ondemand
        self.wantedAt = None        # last time the relay host said a viewer wants it
        self.suspended = False      # 0.21.16: the box's RTSP switch is off -- recorded, nothing runs (Publisher.suspend / resume)
        self.wokeAt = None
        self.lowPub = None
        if low and role == "main" and ONDEMAND_ENABLED:   # 0.21.10: no -low.hang sibling while the switch is off
            self.lowPub = Publisher(bridge, feed, low_broadcast(broadcast), relay, audio=False, minter=minter,
                                    keep=False, role="low")
        self._readyGen = None       # generation that fired the ready hook
        # 0.12.0: publishers that heal. `minter()` -> a fresh relay URL (with
        # ?jwt= on a secured relay, bare on an open one) or None; `keep` marks
        # the feed for republishing after a relaunch (rtsp-feeds.json).
        self.minter = minter
        self.keep = bool(keep)
        self.needsToken = False     # the relay refused our token; parked until a fresh one arrives
        self.lastFailAt = None      # when the last refused pair ended
        self.lastSession = None     # last classified moq line (jwt-free)
        self.sessionFails = 0       # SOFT: severed/closed, moq reconnecting on its own
        self.sessionKills = 0       # HARD: refused / reconnect loop gave up
        self.parked = False
        self.tokenExp = None        # `exp` of the token in self.relay
        self._hard = {}             # generation -> the refusal line that ends it
        self._drains = []           # this generation's stderr readers
        self._mintAt = 0            # last minter() call (one per minute at most)
        self._bareAt = 0            # last bare retry from a park (one per five minutes)
        self._renew = None          # token renewal timer (page-less boxes)
        # 0.9.6: pass the camera through whenever viewers can decode it (the
        # 0.9.2 H.265-only switch widened; `hevc` kept as the old name)
        self.passthrough = bool(passthrough if passthrough is not None else hevc)
        self.hevc = self.passthrough
        self.audio = bool(audio)    # 0.9.5: carry the camera's audio (operator's call, per feed)
        self.codec = None
        self.procs = ()
        self.running = False
        self.stopping = False
        self.restarts = 0
        self.copy = None
        self.errors = []
        self.error = None
        self.since = None
        self.reused = 0             # 0.9.8: publish requests answered by this same pair
        # 0.13.1: who restarted us and what died -- every "random drop" attributed
        self.nudges = {"viewer": 0, "noEcho": 0, "api": 0, "refused": 0}   # 0.21.8: + refused (a viewer report against a fresh pair)
        self.lastNudgeWhy = None
        self.lastNudgeAt = None
        self.lastExit = None        # {code, who: "ffmpeg"|"moq", at, lived} from _watch
        # 0.13.3: attribution that cannot lie -- `restarts` forgets after a good
        # minute, this never does; `lastSessionAt` = the last HARD/SOFT moq line
        self.restartsTotal = 0
        self.lastSessionAt = None
        self._timer = None
        self._lock = threading.Lock()
        self._gen = 0

    def info(self):
        return {"broadcast": self.broadcast,
                "relay": re.sub(r"\?jwt=[^&]*", "?jwt=...", self.relay),
                "running": self.running, "restarts": self.restarts,
                "copy": self.copy, "codec": self.codec, "hevc": self.hevc,
                "passthrough": self.passthrough, "audio": self.audio,
                "sar": ("%d:%d" % tuple(self.feed.sar)) if self.feed.sar else None,   # 0.9.8
                "reused": self.reused,
                "needsToken": self.needsToken, "parked": self.parked,           # 0.12.0
                "lastFailAt": self.lastFailAt, "lastSession": self.lastSession,
                "sessionFails": self.sessionFails, "sessionKills": self.sessionKills,
                "tokenExp": self.tokenExp, "keep": self.keep,
                "nudges": dict(self.nudges), "lastNudgeWhy": self.lastNudgeWhy,   # 0.13.1
                "lastNudgeAt": self.lastNudgeAt, "lastExit": self.lastExit,       # 0.13.1
                "gen": self._gen, "restartsTotal": self.restartsTotal,            # 0.13.3
                "lastSessionAt": self.lastSessionAt,                               # 0.13.3
                "ondemand": self.ondemand, "standby": self.standby,                # 0.18.0
                "wantedAt": self.wantedAt, "role": self.role,
                "low": (self.lowPub.low_info() if self.lowPub else None),
                "lowLive": bool(self.lowPub is not None and self.lowPub.running),   # 0.21.7
                "suspended": bool(self.suspended),                                   # 0.21.16: the box's RTSP switch is off
                "error": self.error, "since": self.since}

    def low_info(self):
        return {"broadcast": self.broadcast, "running": self.running, "restarts": self.restarts,
                "error": self.error, "since": self.since}

    def _args(self):
        ff = self.bridge.ffmpeg
        h264 = self.bridge.sends_h264(self.feed)
        vcodec = (self.feed.vcodec or ("h264" if h264 else "")).lower()
        wide = (self.feed.width or 0) > MAX_WIDTH
        # 0.9.6: one rule (passthrough_ok): copy whenever viewers can decode
        # what the camera sends and the operator allows it; H.264 within the
        # old limits copies regardless; everything else -> one H.264 encode.
        self.copy = passthrough_ok(vcodec, self.feed.width, self.feed.fullrange, self.passthrough, self.feed.sar)
        self.codec = vcodec if self.copy else "h264"
        if self.role == "low":      # 0.18.0: the thumbnail sibling is always a small encode
            self.copy = False
            self.codec = "h264"
        enc = None if self.copy else self.bridge.usable_encoder()
        args = [ff, "-hide_banner", "-loglevel", "error"] + encoder_pre_args(enc) + input_args(self.feed.url, role="low" if self.role == "low" else "pub")
        scr = is_screen(self.feed.url)
        if scr and self.audio and self.role != "low":   # 0.21.20: the computer's sound, PCM on stdin (kastr_screen.Loopback)
            import kastr_screen
            args += kastr_screen.LOOPBACK_INPUT
        if self.role == "low":
            args += low_output_args(encoder=enc)
        else:
            args += publish_output_args(self.copy, encoder=enc, width=MAX_WIDTH if wide else None, audio=self.audio,
                                        audio_input=1 if scr else 0, screen=scr)
        # 0.12.0: `warn` is where moq's reconnect/refusal lines live (the
        # classifier in _drain reads them); --backoff-timeout 10s is moq's
        # measured default made explicit (it exits 1 after that -> _watch);
        # a 15 s QUIC idle timeout (5 s keep-alives) notices a dead relay in
        # 15 s instead of 30. Root options go before the `import` subcommand.
        # 0.16.0 (moq-cli 0.12): --client-connect -> --connect, --client-quic-idle-timeout ->
        # --quic-idle-timeout, and `import --latency-max` -> `import --max-age` (a retention
        # budget: how long relays keep a non-latest group fetchable). Spellings read from
        # `moq --help` / `moq import --help` on 0.12.1, 2026-09-24.
        moq = [self.bridge.moq, "--log-level", "warn", "--backoff-timeout", "10s",
               "--quic-idle-timeout", "15s", "--connect", self.relay,
               "--broadcast", self.broadcast, "import", "--max-age", "5s", PUBLISH_MUX]
        return args, moq

    def start(self):
        with self._lock:
            if self.stopping or self.standby or self.suspended:   # 0.18.0: a standby pair starts only through wake(); 0.21.16: a suspended one only through resume()
                return
            # 0.13.3: whatever timer led here has fired (or was cancelled by the
            # caller); a spent timer left in place would block the next ladder
            # step (_schedule_restart_locked schedules only when none is queued)
            self._timer = None
            # 0.12.0: defensive -- a pair still alive from an older generation
            # (a nudge/retoken racing a queued timer) must not outlive this start
            stale = [p for p in self.procs if p.poll() is None]
            for p in stale:
                try:
                    p.kill()
                    p.wait(timeout=2)   # 0.21.30: gone before the next one binds the same loopback port
                except Exception:
                    pass
                self.bridge._child_ended(p.pid)
            self.procs = ()
            self._gen += 1
            gen = self._gen
            self._hard = {g: r for g, r in self._hard.items() if g >= gen}   # 0.12.0: older verdicts are spent
            ff_args, moq_args = self._args()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ff = None
            try:
                snd = is_screen(self.feed.url) and self.audio and self.role != "low"   # 0.21.20
                ff = subprocess.Popen(ff_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      stdin=subprocess.PIPE if snd else subprocess.DEVNULL,
                                      bufsize=0, creationflags=flags)
                mq = subprocess.Popen(moq_args, stdin=ff.stdout, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, creationflags=flags)
                if snd:
                    import kastr_screen
                    kastr_screen.feed_loopback(ff, exclude_pid=self.bridge.own_pid(), log=self.bridge.log)
            except OSError as e:
                if ff is not None and ff.poll() is None:   # 0.9.8: a moq that failed to start must not leak its ffmpeg
                    try:
                        ff.kill()
                    except OSError:
                        pass
                self.error = "could not start: %s" % e
                self.running = False
                self._schedule_restart_locked()                          # 0.13.3: lock held
                return
            ff.stdout.close()           # moq owns the read end now
            self.procs = (ff, mq)
            # 0.9.8: into the job and the registry -- they die with KASTR now
            self.bridge._child_started(ff, ff_args, [self.feed.url], "ffmpeg")
            self.bridge._child_started(mq, moq_args, [self.broadcast], "moq")
            self.running = True
            self.since = time.time()
            # 0.13.3: one launch.log line per generation (formatted here, written
            # after the lock -- the log may block on I/O)
            start_line = ("rtsp pair %s gen=%d start restarts=%d total=%d copy=%s ffmpeg=%s moq=%s"
                          % (self.broadcast, gen, self.restarts, self.restartsTotal, self.copy, ff.pid, mq.pid))
            self.errors.clear()
            self.error = None
            self.parked = False                                          # 0.12.0
            self.tokenExp = _jwt_exp(_relay_token(self.relay))          # 0.12.0
            drains = [threading.Thread(target=self._drain, args=(ff, "ffmpeg", gen), daemon=True),
                      threading.Thread(target=self._drain, args=(mq, "moq", gen), daemon=True)]
            self._drains = drains
        self.bridge.log(start_line)                                      # 0.13.3
        for t in drains:
            t.start()
        threading.Thread(target=self._watch, args=(gen, ff, mq, drains), daemon=True).start()
        self._arm_renew()                                                # 0.12.0
        if self.role == "main":                                          # 0.18.0: the ready hook after 5 s alive
            rt = threading.Timer(HOOK_READY_AFTER_S, self._ready_check, args=(gen,))
            rt.daemon = True
            rt.start()
        low = self.lowPub
        if low is not None and not low.running and not low.stopping:   # 0.18.0: the thumbnail sibling rides along
            low.relay = self.relay
            low.standby = False
            low.start()

    def _hooks(self):
        return getattr(self.bridge, "hooks", None)

    def _ready_check(self, gen):
        if gen != self._gen or not self.running or self.stopping:
            return
        self._readyGen = gen
        h = self._hooks()
        if h:
            h.fire("ready", self.broadcast, self.feed.id, self.relay, reason="gen %d" % gen)

    def _notready(self, reason):
        if self._readyGen is None:
            return
        self._readyGen = None
        h = self._hooks()
        if h:
            h.fire("notready", self.broadcast, self.feed.id, self.relay, reason=reason)

    # ---- 0.18.0: on-demand standby -------------------------------------------------
    def wake(self, reason="demand", viewer=""):
        """A viewer wants an on-demand pair: leave standby and start it (and its low sibling)."""
        with self._lock:
            if self.stopping or not self.standby or self.suspended:   # 0.21.16: the demand loop cannot wake a switched-off camera (no 'woken' line, no read hook, standby kept for resume)
                return False
            self.standby = False
            self.wokeAt = time.time()
        self.bridge.log("rtsp: on-demand %s woken (%s)" % (self.broadcast, reason))
        h = self._hooks()
        if h:
            h.fire("read", self.broadcast, self.feed.id, self.relay, reason=reason, viewer=viewer)
        self.start()
        return True

    def sleep(self, reason="idle"):
        """Back to standby: stop the processes but keep the publisher (and its settings)."""
        with self._lock:
            if self.stopping or self.standby or not self.ondemand:
                return False
            self.standby = True
            self._gen += 1
            t, self._timer = self._timer, None
            r, self._renew = self._renew, None
            procs = self.procs
        for x in (t, r):
            if x:
                x.cancel()
        self.parked = False
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
            self.bridge._child_ended(p.pid)
        self.running = False
        self.bridge.log("rtsp: on-demand %s back to standby (%s)" % (self.broadcast, reason))
        self._notready("standby: " + reason)
        # 0.21.7: the low copy STAYS on the air in standby -- a viewer's click shows the picture at once (the tile
        # lives on the low copy) and the full pair replaces it when it is up. Cost per on-demand camera: one RTSP
        # pull and a 640p / 15 fps / ~400 kb/s encode. stop() still ends both.
        return True

    # ---- 0.21.16: the box's RTSP switch ------------------------------------------
    def suspend(self, reason="operator"):
        """Stop the processes and every timer, keep the publisher and its settings. Unlike sleep()
        this is unconditional (on-demand or not) and start() stays refused until resume(): the
        ladder, a park retry, a renew, a re-token, a nudge and a wake all land on the gate."""
        with self._lock:
            if self.stopping:
                return False
            was = self.running
            self.suspended = True
            self._gen += 1
            t, self._timer = self._timer, None
            r, self._renew = self._renew, None
            procs = self.procs
        for x in (t, r):
            if x:
                x.cancel()
        self.parked = False
        _end_pair(procs, self.bridge._child_ended)   # 0.21.16: ffmpeg first -- viewers lose the member broadcasts at once, not after the relay's idle timeout
        self.running = False
        self._notready("suspended: " + reason)
        if self.lowPub is not None:
            self.lowPub.suspend(reason)
        return was

    def resume(self, reason="operator"):
        """The switch is back on: a plain pair starts now; an on-demand pair returns to standby
        (Bridge.resume re-arms the demand loop and its low copy, the 0.18.0 shape)."""
        with self._lock:
            if self.stopping or not self.suspended:
                return False
            self.suspended = False
            t, self._timer = self._timer, None
        if t:
            t.cancel()
        if self.lowPub is not None:
            self.lowPub.suspended = False
        if self.ondemand:
            self.standby = True
            self.wokeAt = None
            return True
        self.start()
        return True

    def _halt(self):
        """Stop the processes of a sibling without marking it stopping for good."""
        with self._lock:
            self._gen += 1
            t, self._timer = self._timer, None
            r, self._renew = self._renew, None
            procs = self.procs
        for x in (t, r):
            if x:
                x.cancel()
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
            self.bridge._child_ended(p.pid)
        self.running = False

    def _drain(self, proc, tag, gen=0):
        try:
            for line in proc.stderr:
                text = line.decode("utf-8", "replace").strip()
                if text:
                    text = _redact(re.sub(r"\x1b\[[0-9;]*m", "", text))   # 0.12.0: never a token
                    text = _redact_url(text)     # 0.13.3: ffmpeg prints the camera URL, credentials and all, on a connect error
                    self.errors.append(tag + ": " + text[-200:])
                    del self.errors[:-8]                                 # 0.13.1: was 4 -- the ffmpeg reason survives
                    self.error = " / ".join(self.errors)
                    if tag == "moq":
                        self._classify(gen, text)                        # 0.12.0
        except Exception:
            pass

    def _classify(self, gen, text):
        """0.12.0: what moq said about its relay session. A HARD line (refused
        token, reconnect loop gave up) is this generation's verdict -- _watch
        parks the pair instead of restarting it; SOFT lines are only counted."""
        if HARD_RE.search(text):
            if gen not in self._hard:
                self._hard[gen] = text[-160:]
                self.sessionKills += 1
            self.lastSession = text[-160:]
            self.lastSessionAt = time.time()                             # 0.13.3
        elif SOFT_RE.search(text):
            self.sessionFails += 1
            self.lastSession = text[-160:]
            self.lastSessionAt = time.time()                             # 0.13.3

    def _watch(self, gen, ff, mq, drains=()):
        # whichever ends first ends the pair
        while ff.poll() is None and mq.poll() is None:
            time.sleep(0.5)
            if self.stopping or gen != self._gen:
                return
        # 0.13.1: who ended the pair (poll() = its exit code), before the
        # survivor is killed below
        rc = ff.poll()
        if rc is not None:
            who, code = "ffmpeg", rc
        else:
            who, code = "moq", mq.poll()
        for p in (ff, mq):
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
            self.bridge._child_ended(p.pid)   # 0.9.8
        # 0.12.0: stderr EOF arrives with the exit -- let the readers finish so
        # this generation's verdict (HARD refusal or not) is in before deciding
        for t in drains:
            try:
                t.join(1.0)
            except Exception:
                pass
        decision = None                 # 0.13.3: "park" | "ladder" | None, decided under the lock
        with self._lock:
            if gen != self._gen:
                return
            self.running = False
            lived = time.time() - (self.since or time.time())
            self.lastExit = {"code": code, "who": who, "at": time.time(), "lived": round(lived, 1)}   # 0.13.1
            # 0.13.3: the generation's obituary for launch.log -- with the ladder
            # position BEFORE the good-minute reset below (written after the lock)
            exit_line = ("rtsp pair %s gen=%d exit who=%s code=%s lived=%.1fs restarts=%d sessionFails=%d sessionKills=%d last=%s"
                         % (self.broadcast, gen, who, code, lived, self.restarts, self.sessionFails, self.sessionKills,
                            (self.errors[-1] if self.errors else "")[:160]))
            if lived > 60:
                self.restarts = 0       # it was working; forget the past
            hard = self._hard.pop(gen, None)                              # 0.12.0
            if hard:
                self.needsToken = True
                self.lastFailAt = time.time()
            # 0.13.3: hard/ladder decided while the lock is held -- a nudge or
            # retoken racing this exit either moved _gen first (we returned above)
            # or finds our timer to cancel; no second pair can slip in between
            if not self.stopping:
                if hard:
                    decision = "park"   # 0.12.0: the same URL cannot help; wait for a fresh token
                else:
                    decision = "ladder"
                    self._schedule_restart_locked()
        self.bridge.log(exit_line)
        self._notready("exit %s code %s" % (who, code))                  # 0.18.0
        if decision == "park":
            self._park()                # logs and may mint: never under the lock

    def _schedule_restart_locked(self):
        """0.13.3: queue the next ladder step. The caller holds self._lock
        (threading.Lock is not reentrant -- never call this without it). One
        tick at a time: a queued ladder/park timer or a stopping pair -> no-op."""
        if self.stopping or self._timer is not None:
            return
        wait = PUBLISH_RETRY_S[min(self.restarts, len(PUBLISH_RETRY_S) - 1)]
        self.restarts += 1
        self.restartsTotal += 1                                           # 0.13.3
        t = threading.Timer(wait, self.start)
        t.daemon = True
        self._timer = t
        t.start()

    def nudge(self, why="api"):
        """A viewer says the stream is frozen: restart the pair now.
        0.13.1: `why` (viewer / stall* / no-echo / api) is counted and kept."""
        if self.standby or self.suspended:   # 0.18.0: nothing runs; a viewer's demand wakes it instead; 0.21.16: nor while the box's RTSP switch is off
            return
        bucket = nudge_bucket(why)
        if bucket == "viewer" and self.running and self.since and time.time() - self.since < 60:
            # 0.21.8: the 0.13.3 evidence rule on the server side too -- a viewer's stall report restarts nothing that came up
            # in the last minute (the page's gate no longer sends one for a running pair; older pages still might)
            self.nudges["refused"] = self.nudges.get("refused", 0) + 1
            self.lastNudgeWhy = ("refused:" + str(why or ""))[:32]
            self.lastNudgeAt = time.time()
            self.bridge.log("rtsp nudge refused %s why=%s -- the pair is %d s into gen %d (a viewer's report is not evidence)"
                            % (self.broadcast, why, int(time.time() - self.since), self._gen))
            return
        self.nudges[bucket] += 1
        self.lastNudgeWhy = str(why or "api")[:32]
        self.lastNudgeAt = time.time()
        with self._lock:
            t, self._timer = self._timer, None      # 0.12.0: a queued ladder/park tick must not double-start
            self._gen += 1
            procs = self.procs
        if t:
            t.cancel()
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
        self.running = False
        if not self.stopping:
            self.restarts += 1
            self.restartsTotal += 1                                       # 0.13.3
            self.start()

    # ---- 0.12.0: publishers that heal -----------------------------------
    # Parked = the relay refused our token (HARD), so restarting with the same
    # URL only hammers the camera and the relay. A parked pair does nothing
    # but: ask the minter for a fresh token (at most once a minute) and, when
    # that yields nothing, retry the old URL once every five minutes in case
    # the relay reopened. A page re-posting /api/rtsp/publish with a new
    # token (Bridge.publish -> retoken) ends the park at once.
    def _park(self):
        self.parked = True
        self._bareAt = time.time()      # the first bare retry is five minutes out, not now
        self.bridge.log("rtsp: publisher %s refused by the relay (%s) -- parked until a fresh token arrives"
                        % (self.broadcast, self.lastSession))
        self._park_tick()

    def _park_tick(self):
        if self.suspended:          # 0.21.16: a park decided by _watch just before suspend() must not tick (no minting, no bare retry, no restarts bump)
            return
        if self.stopping or not self.parked:
            return
        now = time.time()
        url = None
        if self.minter and now - self._mintAt >= 60:
            self._mintAt = now
            try:
                url = self.minter()
            except Exception as e:
                self.bridge.log("rtsp: publisher %s: token request failed: %s" % (self.broadcast, e))
            if url:
                self.retoken(url)
                return
        if now - self._bareAt >= 300:
            self._bareAt = now
            with self._lock:
                self.parked = False
            self.restarts += 1
            self.start()                # bounded bare retry with the old URL
            return
        with self._lock:
            if self.stopping or not self.parked:
                return
            t = threading.Timer(15, self._park_tick)
            t.daemon = True
            self._timer = t
            t.start()

    def retoken(self, relay):
        """A fresh relay URL (new token): move the pair onto it now."""
        relay = (relay or "").strip()
        if not relay or self.stopping:
            return
        if self.lowPub is not None:                                      # 0.18.0
            self.lowPub.relay = relay
        if self.standby:                                                 # 0.18.0: remember it for the next wake
            self.relay = relay
            self.needsToken = False
            self.parked = False
            return
        with self._lock:
            t, self._timer = self._timer, None
            self.relay = relay
            self.needsToken = False
            self.parked = False
            self._gen += 1
            procs = self.procs
        if t:
            t.cancel()
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
            self.bridge._child_ended(p.pid)
        self.running = False
        self.start()

    def _arm_renew(self):
        """Page-less boxes: renew the room token 15 minutes before it ends,
        through the minter. A page that re-posts meanwhile makes it a no-op."""
        with self._lock:
            t, self._renew = self._renew, None
        if t:
            t.cancel()
        if self.stopping or self.suspended or not self.minter or not self.tokenExp:   # 0.21.16: a suspend() landing between start()'s lock and this call leaves no renewal timer behind
            return
        t = threading.Timer(max(30, self.tokenExp - time.time() - 900), self._renew_tick)
        t.daemon = True
        with self._lock:
            self._renew = t
        t.start()

    def _renew_tick(self):
        if self.stopping:
            return
        exp = _jwt_exp(_relay_token(self.relay))
        if exp and exp - time.time() > 900:
            self.tokenExp = exp         # the page re-posted a fresh token meanwhile
            self._arm_renew()
            return
        url = None
        now = time.time()
        if self.minter and now - self._mintAt >= 60:
            self._mintAt = now
            try:
                url = self.minter()
            except Exception as e:
                self.bridge.log("rtsp: publisher %s: token renewal failed: %s" % (self.broadcast, e))
        if url and _relay_token(url) != _relay_token(self.relay):
            self.bridge.log("rtsp: publisher %s: room token renewed" % self.broadcast)
            self.retoken(url)           # start() re-arms from the new token
            return
        with self._lock:
            if self.stopping:
                return
            t = threading.Timer(60, self._renew_tick)
            t.daemon = True
            self._renew = t
            t.start()

    def stop(self):
        self.stopping = True
        with self._lock:
            self._gen += 1
            t, self._timer = self._timer, None
            r, self._renew = self._renew, None      # 0.12.0
            procs = self.procs
        if t:
            t.cancel()
        if r:
            r.cancel()
        self.parked = False
        _end_pair(procs, self.bridge._child_ended)   # 0.9.8; 0.21.16: ffmpeg first -- moq ends its session on EOF, the relay unannounces at once
        self.running = False
        self._notready("stopped")                                        # 0.18.0
        if self.lowPub is not None:
            self.lowPub.stop()


def _end_pair(procs, ended, grace=1.0):
    """0.21.16: end an ffmpeg|moq pair ffmpeg FIRST. moq reads the encoded stream from ffmpeg's stdout: with ffmpeg
    gone it sees EOF, closes its session and the relay withdraws the broadcast at once. Killing moq outright left the
    broadcast announced until the relay's idle timeout (~20 s measured), and viewers kept a dead tile that long.
    moq gets `grace` seconds, then it is killed like before. `ended(pid)` is Bridge._child_ended."""
    procs = list(procs or ())
    for p in procs[:1]:
        if p.poll() is None:
            try:
                p.kill()
                p.wait(timeout=1)   # 0.21.30: its input (a loopback port, a camera) is free when the next pair starts
            except Exception:
                pass
    deadline = time.time() + grace
    for p in procs[1:]:
        if p.poll() is None:
            try:
                p.wait(timeout=max(0.05, deadline - time.time()))
            except Exception:
                pass
        if p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass
    for p in procs:
        ended(p.pid)


def _ensure_exec(path):
    """Make sure a bundled helper is executable (no-op on Windows)."""
    if sys.platform == "win32":
        return
    try:
        import stat
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


class Feed:
    def __init__(self, feed_id, url, source_url=None):
        self.id = feed_id
        self.url = url                    # what ffmpeg pulls (post-resolve)
        self.source_url = source_url or url   # what the operator typed
        # One ffmpeg per open reader, not one per feed. A <video> element is
        # free to re-request its src -- Chrome does, routinely -- and holding a
        # single `proc` meant the second request overwrote the first, orphaning
        # a running child and leaving `running` reporting on a process nobody
        # was reading. That made this endpoint lie about feeds that were fine.
        self.procs = set()
        self.error = None
        self.errors = []
        self.h264 = None        # set by the first codec probe
        self.vcodec = None      # 0.9.2: the codec name itself ("h264", "hevc", ...)
        self.acodec = None      # 0.9.5: audio codec from the probe; "" = the camera has no audio track; None = not probed
        self.width = None       # source frame size, from the same probe
        self.height = None
        self.fullrange = None   # full-range source: must be converted
        self.sar = None         # 0.9.8: (num, den) sample aspect ratio from the probe; None = square/unknown
        self.probe_failed_at = None   # 0.12.0: when a codec probe could not tell (re-asked after PROBE_RETRY_S)

    def info(self):
        return {
            "id": self.id,
            "url": self.source_url,       # the operator's URL, not the resolved one
            "path": f"/rtsp/{self.id}",
            "running": any(p.poll() is None for p in list(self.procs)),
            "error": self.error,
            "acodec": self.acodec,        # 0.9.5
            "sar": ("%d:%d" % tuple(self.sar)) if self.sar else None,   # 0.9.8
        }


class Bridge:
    """Owns the set of RTSP feeds and their ffmpeg children."""

    def __init__(self, state_dir=None, log=None, host_slug=None):
        self._feeds = {}
        self._removed = []        # 0.21.0: [{url, at}] the operator closed -- restore() and adopt leave them alone
        self._next = 1
        # 0.13.0: this machine's host slug (kastr_serve.host_slug -- set by the
        # caller, this module cannot import kastr_serve); the minter scopes the
        # publishers' tokens to it. None -> wide (0.12-shaped) tokens.
        self.host_slug = host_slug
        self._lock = threading.Lock()
        self.ffmpeg = find_ffmpeg()
        self.moq = find_moq()            # 0.9.1: native publishing when present
        self._pubs = {}                  # feed id -> Publisher
        # 0.18.0: operator hooks (the launcher replaces these with kastr.ini's) and the
        # on-demand loop. `web_base_for(relay_url)` -> the relay host's KASTR base URL
        # (kastr_serve.make_bridge injects it); the demand loop asks it who is wanted.
        self.hooks = Hooks.from_env(log)
        self.web_base_for = None
        self._feed_locks = {}
        self._od_thread = None
        self._od_said = {}
        self.suspended = False  # 0.21.16: the box's RTSP switch (rtsp-feeds.json `suspended`; _load_session below reads it)
        self._encoder = None    # cached hardware-encoder choice
        self._probed = {}       # url -> (h264, width, height)
        self.encoder_note = None  # which one, for the feed list
        # 0.9.8: children die with KASTR -- see _make_job / sweep_orphans
        self.state_dir = state_dir
        self.log = log or print
        self._job = app_job(self.log)
        self._children = {}              # pid -> record, mirrored to rtsp-children-<pid>.json
        self._children_lock = threading.Lock()
        self._media = set()              # 0.14.0: plain argv children (spawn_media), killed at shutdown
        # 0.12.0: the room the feeds belong to (+ its codes) and the feed list,
        # mirrored to rtsp-feeds.json so a relaunch can republish them
        self._persist_lock = threading.Lock()
        self._session = {"room": "", "access": "", "roomCode": "", "relay": ""}
        self._load_session()
        if self.suspended:   # 0.21.16
            self.log("rtsp: publishing is SUSPENDED on this box (rtsp-feeds.json suspended=true) -- cameras are recorded, none starts until the switch is turned on")
        self.started_at = time.time()
        self.swept = 0
        try:
            self.swept = self.sweep_orphans()
        except Exception as e:
            self.log("rtsp: orphan sweep failed: %s" % e)
        try:
            self.swept += self.legacy_sweep()     # 0.9.10: leftovers from older versions, by path + parent
        except Exception as e:
            self.log("rtsp: legacy sweep failed: %s" % e)

    # ---- child lifetime (0.9.8) -----------------------------------------
    def _children_file(self, pid=None):
        if not self.state_dir:
            return None
        return os.path.join(self.state_dir, "rtsp-children-%d.json" % (pid or os.getpid()))

    def _write_children(self):
        path = self._children_file()
        if not path:
            return
        # One writer at a time: publishers start from several threads at once,
        # and two of them sharing one .tmp name collided on Windows ("Permission
        # denied" on the second open, "Access is denied" on the replace).
        with self._children_lock:
            recs = list(self._children.values())
            try:
                if not recs:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    return
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = "%s.%d.tmp" % (path, threading.get_ident())
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"owner": os.getpid(), "ownerStarted": self.started_at, "children": recs}, f)
                # 0.9.10: a scanner (Defender, the indexer) may hold the freshly
                # written file for a moment and the swap fails with "Access is
                # denied". Retry briefly, then write the tiny file in place -- the
                # next start tolerates an unreadable registry, an unwritten one it cannot.
                swapped = False
                for attempt in range(10):
                    try:
                        os.replace(tmp, path)
                        swapped = True
                        break
                    except PermissionError:
                        time.sleep(0.02 * (attempt + 1))
                if not swapped:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump({"owner": os.getpid(), "ownerStarted": self.started_at, "children": recs}, f)
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            except Exception as e:
                self.log("rtsp: could not write the child registry: %s" % e)

    def _child_started(self, proc, argv, sig, tag):
        """A child is ours: into the job (Windows) and the on-disk registry."""
        _job_assign(self._job, proc, self.log)
        try:
            rec = {"pid": proc.pid, "exe": argv[0] if argv else "", "sig": [str(x) for x in (sig or [])],
                   "started": time.time(), "tag": tag}
            with self._children_lock:
                self._children[proc.pid] = rec
        except Exception:
            return
        self._write_children()

    def _child_ended(self, pid):
        with self._children_lock:
            gone = self._children.pop(pid, None) is not None
        if gone:
            self._write_children()

    def registry(self):
        """Every rtsp-children-*.json in the state dir (for --diagnose)."""
        out = []
        if not self.state_dir or not os.path.isdir(self.state_dir):
            return out
        for fn in sorted(os.listdir(self.state_dir)):
            if fn.startswith("rtsp-children-") and fn.endswith(".json"):
                try:
                    with open(os.path.join(self.state_dir, fn), encoding="utf-8") as f:
                        out.append((fn, json.load(f)))
                except Exception as e:
                    out.append((fn, {"error": str(e)}))
        return out

    def helper_dirs(self):
        dirs = list(helper_roots())
        for p in (self.ffmpeg, self.moq):
            if p:
                dirs.append(os.path.dirname(p))
        seen, out = set(), []
        for d in dirs:
            k = os.path.normcase(os.path.realpath(d))
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out

    def legacy_sweep(self):
        """0.9.10: end bundled helpers whose parent KASTR is gone -- publisher
        pairs left by a pre-0.9.8 run, orphaned monitors, probes, a moq-relay
        holding port 4443. A second live KASTR (or the dev harness) keeps its
        helpers: their parent is alive and KASTR-like."""
        rows = helper_orphans(self.helper_dirs())
        counts = {}
        swept = 0
        for r in rows:
            if _kill_pid(r["pid"]):
                swept += 1
                stem = os.path.splitext(r["name"] or "")[0].lower()
                counts[stem] = counts.get(stem, 0) + 1
        if swept:
            self.log("rtsp: swept %d helper process(es) left by earlier KASTR runs (%s)" % (
                swept, ", ".join("%s x%d" % (k, v) for k, v in sorted(counts.items()))))
        return swept

    def sweep_orphans(self):
        """Kill the recorded children of every KASTR that is no longer running."""
        swept = 0
        # a registry write cut short by a hard exit leaves its .tmp behind
        if self.state_dir and os.path.isdir(self.state_dir):
            for fn in os.listdir(self.state_dir):
                if fn.startswith("rtsp-children-") and fn.endswith(".tmp"):
                    try:
                        os.remove(os.path.join(self.state_dir, fn))
                    except OSError:
                        pass
        for fn, doc in self.registry():
            path = os.path.join(self.state_dir, fn)
            try:
                owner = int(doc.get("owner") or fn[len("rtsp-children-"):-len(".json")])
            except (TypeError, ValueError):
                owner = 0
            if owner == os.getpid():
                continue
            if owner and _pid_alive(owner):
                # the owner may be another live KASTR (different build on another
                # port) -- or a reused PID. Its start time decides.
                alive = True
                try:
                    _, created, _ = _pid_image(owner)
                    if created is not None and doc.get("ownerStarted") and abs(created - float(doc["ownerStarted"])) > 5:
                        alive = False
                except Exception:
                    pass
                if alive:
                    continue
            for rec in doc.get("children") or []:
                try:
                    if _pid_matches(rec) and _kill_pid(rec["pid"]):
                        swept += 1
                except Exception:
                    continue
            try:
                os.remove(path)
            except OSError:
                pass
            self.log("rtsp: swept %d orphaned publisher process(es) left by KASTR pid %s" % (swept, owner))
        return swept

    def _hostmedia_ready(self, url):
        """0.21.26: media://<id> -> its file in <state>/hostmedia, copied there from the upload (<state>/media) once."""
        if not self.state_dir:
            return False
        HOSTMEDIA_DIR[0] = os.path.join(self.state_dir, "hostmedia")
        if hostmedia_path(url):
            return True
        mid = str(url)[len(MEDIA_PREFIX):].strip().lower()
        if not re.match(r"^[0-9a-f]{32}$", mid):
            return False
        src_dir = os.path.join(self.state_dir, "media")
        try:
            names = sorted(os.listdir(src_dir))
        except OSError:
            return False
        for fn in names:
            if fn.startswith(mid + ".") and re.match(r"^[0-9a-f]{32}\.[a-z0-9]{1,5}$", fn):
                import shutil
                os.makedirs(HOSTMEDIA_DIR[0], exist_ok=True)
                shutil.copy2(os.path.join(src_dir, fn), os.path.join(HOSTMEDIA_DIR[0], fn))
                return True
        return False

    def add(self, url):
        url = (url or "").strip()
        if self.state_dir and HOSTMEDIA_DIR[0] is None:
            HOSTMEDIA_DIR[0] = os.path.join(self.state_dir, "hostmedia")
        if not url:
            raise ValueError("no url given")
        self._removed = [r for r in self._removed if r.get("url") != url]   # 0.21.0: adding again is an explicit act
        # Only ever hand ffmpeg a stream URL, never a local path or shell text.
        # (Popen is given an argv list, so there is no shell to inject into, but
        # a file:// or local path would still let a page read arbitrary files.)
        if is_screen(url):   # 0.21.20: a native screen / window share -- validated and resolved by kastr_screen
            import kastr_screen
            kastr_screen.check_url(url)
        elif is_device(url):   # 0.21.26: a camera on this computer, captured once by the bridge
            if not device_name(url):
                raise ValueError("no camera name given")
            if not self.ffmpeg:
                raise ValueError("ffmpeg is not available here")
            if url not in DEVICES:
                cap = DEVICES[url] = DeviceCapture(self.ffmpeg, url, self.log)
                cap.start()
                time.sleep(1.5)   # the first packets reach the loopback ports before a reader opens them
        elif is_rtmp_in(url):   # 0.21.29: an RTMP ingest -- listen on its port for a device to push
            port, key = rtmp_parts(url)
            if not port:
                raise ValueError("bad RTMP ingest (port %d-%d and a key of 6-40 letters or digits)" % (RTMP_PORTS[0], RTMP_PORTS[-1]))
            if not self.ffmpeg:
                raise ValueError("ffmpeg is not available here")
            if url not in DEVICES:
                if port in rtmp_ports_in_use():
                    raise ValueError("RTMP port %d is already in use by another ingest" % port)
                cap = DEVICES[url] = DeviceCapture(self.ffmpeg, url, self.log)
                cap.start()
                self.log("rtsp: RTMP ingest listening on port %d" % port)
        elif is_hostmedia(url):   # 0.21.26: a media file uploaded to this host -- kept in <state>/hostmedia
            if not self._hostmedia_ready(url):
                raise ValueError("that media file is not on this computer (upload it again)")
        elif url != TEST_URL and not url.lower().startswith(
                ("rtsp://", "rtsps://", "http://", "https://")):
            raise ValueError("url must start with rtsp://, rtsps://, http:// or https://")
        # 0.9.3: a video PAGE (YouTube etc.) is refused with a clear reason;
        # direct media URLs, manifests and unknown hosts go to ffmpeg verbatim.
        source = url
        low = url.lower()
        if url != TEST_URL and low.startswith(("http://", "https://")):
            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if (not (parsed.path or "").lower().endswith(MEDIA_EXTS)
                    and any(h in host for h in PAGE_SITES)):
                raise ValueError("video pages (YouTube, Vimeo, Twitch...) are not supported -- "
                                 "use a direct media URL (.mp4, .m3u8...) or an RTSP camera")
        with self._lock:
            feed = Feed(self._next, url, source_url=source)
            self._feeds[feed.id] = feed
            self._next += 1
        if is_screen(url):   # 0.21.20: a red border + a Stop sharing bar around what is shared (never in the capture)
            import kastr_screen
            fid = feed.id
            kastr_screen.overlay_start(fid, url, on_stop=lambda: (self.log("screen: Stop sharing on the bar"), self.remove(fid)))
        return feed

    def remove(self, feed_id):
        self.unpublish(feed_id, persist=False)   # 0.12.0: one write, below
        with self._lock:
            feed = self._feeds.pop(int(feed_id), None)
        if feed and (is_device(feed.url) or is_rtmp_in(feed.url)):   # 0.21.26: the camera is free again; 0.21.29: the RTMP port too
            cap = DEVICES.pop(feed.url, None)
            if cap:
                cap.stop()
        if feed and is_hostmedia(feed.url):   # 0.21.26: its kept copy goes with it
            p = hostmedia_path(feed.url)
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass
        if feed and is_screen(feed.url):   # 0.21.20
            import kastr_screen
            kastr_screen.overlay_stop(feed.id)
        if feed:
            self.kill(feed)
            # 0.21.0: remember the closed URL -- a relaunch restore or a page adopt must not bring it back
            # (field report: "my KASTR keeps trying to use an RTSP feed that I keep closing out")
            url = getattr(feed, "source_url", None) or getattr(feed, "url", None)
            if url:
                self._removed = [r for r in self._removed if r.get("url") != url] + [{"url": url, "at": int(time.time())}]
                self._removed = self._removed[-50:]
        self.persist_feeds()                     # 0.12.0
        return bool(feed)

    def removed_urls(self):
        return [r["url"] for r in self._removed]

    # ---- native publishing (0.9.1) --------------------------------------
    def publish(self, feed_id, broadcast, relay, hevc=False, audio=True, passthrough=None, force=False, keep=None,
                ondemand=False, low=False, label=""):   # 0.12.0: keep; 0.18.0: ondemand, low, label
        # 0.18.0: one publish at a time per feed -- two quick option toggles on the page sent two
        # requests that raced, and the older one could land last
        with self._lock:
            fl = self._feed_locks.setdefault(int(feed_id), threading.Lock())
        with fl:
            return self._publish(feed_id, broadcast, relay, hevc, audio, passthrough, force, keep, ondemand, low, label)

    def _publish(self, feed_id, broadcast, relay, hevc, audio, passthrough, force, keep, ondemand, low, label):
        feed = self.get(feed_id)
        if not feed:
            raise ValueError("no such feed")
        if not self.moq:
            raise RuntimeError("moq-cli not available")
        rl = (relay or "").strip().lower()   # 0.18.0: was `low`, which shadowed the low-rendition flag
        if not rl.startswith(("http://", "https://", "ws://", "wss://")):
            raise ValueError("relay must be an http(s) or ws(s) url")
        if not re.match(r"^[A-Za-z0-9._~:@+\-]+(/[A-Za-z0-9._~:@+\-]+)*$", broadcast or ""):
            raise ValueError("bad broadcast name")
        # 0.9.8: the same request twice is one publisher, not a restart. A page
        # that reloads (or adopts feeds the server already runs) asks for what
        # is already on air; answering with the running pair keeps viewers'
        # pictures up. Only the token part of the relay URL may differ.
        want_pt = bool(passthrough if passthrough is not None else hevc)
        cur = self._pubs.get(int(feed_id))
        if (cur is not None and not force and not cur.stopping
                and cur.broadcast == broadcast
                and _relay_key(cur.relay) == _relay_key(relay)
                and cur.passthrough == want_pt and cur.audio == bool(audio)
                and (not ONDEMAND_ENABLED or (cur.ondemand == bool(ondemand) and (cur.lowPub is not None) == bool(low)))):   # 0.18.0; 0.21.10: flags that have no effect never restart a pair
            # 0.12.0: evidence-gated re-token. A reload/rejoin mints a new token
            # but must NOT restart a healthy pair (the 0.9.8 promise). A pair the
            # relay refused, one that is down, one that failed within the last
            # minute or one whose token ends within 15 minutes takes it now.
            new_tok, old_tok = _relay_token(relay), _relay_token(cur.relay)
            now = time.time()
            if new_tok != old_tok and (not cur.running or cur.needsToken
                                       or (cur.lastFailAt and now - cur.lastFailAt < 60)
                                       or (cur.tokenExp and cur.tokenExp - now < 900)):
                cur.retoken(relay)
            else:
                cur.relay = relay.strip()      # the ladder's next start carries the live token
            if keep is not None and bool(keep) != cur.keep:
                cur.keep = bool(keep)
                self.persist_feeds()
            if label and label != cur.label:                             # 0.18.0: a renamed feed
                cur.label = str(label)[:80]
            cur.reused += 1
            return cur
        self.unpublish(feed_id, persist=False)   # 0.12.0: the new pair is persisted below
        pub = Publisher(self, feed, broadcast, relay.strip(), hevc=bool(hevc), audio=bool(audio),
                        passthrough=passthrough,
                        minter=self._minter_for(feed, broadcast, relay),        # 0.12.0
                        keep=(True if keep is None else bool(keep)),
                        ondemand=bool(ondemand), low=bool(low), label=label)    # 0.18.0
        with self._lock:
            self._pubs[int(feed_id)] = pub
        if (pub.wantOndemand or pub.wantLow) and not ONDEMAND_ENABLED:   # 0.21.10
            self.log("rtsp: %s asked for on demand/low -- ignored (ondemand = off; kastr.ini ondemand = on or KASTR_ONDEMAND=1 allows it)" % broadcast)
        pub.suspended = bool(self.suspended)   # 0.21.16: born while the switch is off -> recorded, not started
        if pub.suspended:
            self.log("rtsp: %s recorded while publishing is suspended -- not started" % broadcast)
        elif pub.ondemand:
            self.log("rtsp: %s published on demand -- standby until a viewer asks" % broadcast)
            self._od_ensure()
            self._low_standby(pub)   # 0.21.7: click-to-picture -- the low copy runs while the full pair waits
        else:
            pub.start()
        self.persist_feeds()                     # 0.12.0
        return pub

    def _low_standby(self, pub):
        """0.21.7: start an on-demand pair's low copy while the full pair is in standby (Publisher.start does the same
        when the full pair wakes; sleep() leaves it running)."""
        low = getattr(pub, "lowPub", None)
        if low is None or low.running or low.stopping:
            return
        try:
            low.relay = pub.relay
            low.standby = False
            low.start()
            self.log("rtsp: %s low copy on the air in standby (click-to-picture)" % pub.broadcast)
        except Exception as e:
            self.log("rtsp: %s low copy did not start: %s" % (pub.broadcast, e))

    # ---- 0.18.0: the on-demand loop -------------------------------------------------
    OD_POLL_S = 5
    OD_IDLE_S = 60

    def _od_ensure(self):
        with self._lock:
            if self._od_thread is not None and self._od_thread.is_alive():
                return
            t = threading.Thread(target=self._od_loop, daemon=True, name="kastr-ondemand")
            self._od_thread = t
        t.start()

    def _od_loop(self):
        while True:
            pubs = [p for p in list(self._pubs.values()) if p.ondemand and not p.stopping]
            if not pubs:
                with self._lock:
                    self._od_thread = None
                return
            try:
                self.od_tick(pubs)
            except Exception as e:
                self.log("rtsp: on-demand tick failed: %s" % e)
            time.sleep(self.OD_POLL_S)

    def od_tick(self, pubs, now=None, post=None):
        """One demand round: tell each relay host which on-demand feeds exist, learn which are
        wanted, wake/sleep accordingly. `post(url, body) -> dict|None` is injectable (tests)."""
        now = now or time.time()
        post = post or self._od_post
        groups = {}
        for p in pubs:
            groups.setdefault(_relay_key(p.relay), []).append(p)
        for key, ps in groups.items():
            base = None
            try:
                base = self.web_base_for(key) if callable(self.web_base_for) else None
            except Exception:
                base = None
            wanted = None
            if base:
                body = {"token": _relay_token(ps[0].relay) or "",
                        "feeds": [{"broadcast": p.broadcast, "label": p.label or p.broadcast.rsplit("/", 1)[-1][:-5],
                                   "live": bool(p.running), "low": (p.lowPub.broadcast if p.lowPub else None)} for p in ps]}
                d = post(base.rstrip("/") + "/api/ondemand/sync", body)
                if isinstance(d, dict) and isinstance(d.get("wanted"), dict):
                    wanted = d["wanted"]
            for p in ps:
                if wanted is not None and p.broadcast in wanted:
                    try:
                        age = max(0.0, float(wanted[p.broadcast]))
                    except (TypeError, ValueError):
                        age = None
                    if age is not None:
                        p.wantedAt = max(p.wantedAt or 0, now - age)
                recent = p.wantedAt is not None and now - p.wantedAt < self.OD_IDLE_S
                if p.standby and recent:
                    p.wake("viewer demand")
                elif not p.standby and not recent and now - (p.wokeAt or 0) >= self.OD_IDLE_S:
                    p.sleep("no viewer for %d s" % self.OD_IDLE_S)

    def _od_post(self, url, body):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=4) as r:
                return json.loads(r.read().decode("utf-8", "replace") or "{}")
        except Exception as e:
            last = self._od_said.get(url, 0)
            if time.time() - last > 600:
                self._od_said[url] = time.time()
                self.log("rtsp: on-demand sync with %s failed: %s" % (re.sub(r"\?.*", "", url), str(e)[:120]))
            return None

    def unpublish(self, feed_id, persist=True):   # 0.12.0: persist
        with self._lock:
            pub = self._pubs.pop(int(feed_id), None)
        if pub:
            pub.stop()
            if persist:
                self.persist_feeds()
        if is_screen(getattr(pub.feed, "url", "") if pub else ""):   # 0.21.20: the red border goes with the share
            import kastr_screen
            kastr_screen.overlay_stop(int(feed_id))
        return bool(pub)

    # ---- 0.12.0: feed + session memory (rtsp-feeds.json) ------------------
    def _feeds_file(self):
        return os.path.join(self.state_dir, "rtsp-feeds.json") if self.state_dir else None

    def _read_feeds_file(self):
        path = self._feeds_file()
        if not path:
            return {}
        try:
            with open(path, encoding="utf-8-sig") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _load_session(self):
        d = self._read_feeds_file()
        if d:
            self._session = {"room": str(d.get("room") or "").strip().lower(),
                             "access": str(d.get("access") or ""),
                             "roomCode": str(d.get("roomCode") or ""),
                             "relay": _relay_key(d.get("relay") or "")}
            self.suspended = d.get("suspended") is True   # 0.21.16: the switch survives a relaunch
            rem = d.get("removed")   # 0.21.0
            self._removed = [{"url": str(r.get("url")), "at": int(r.get("at") or 0)} for r in (rem or [])
                             if isinstance(r, dict) and r.get("url")][-50:]

    def _feed_records(self):
        out = []
        for pub in list(self._pubs.values()):
            if pub.stopping:
                continue
            if is_screen(pub.feed.source_url):   # 0.21.26 (Kenton): a screen / window / tab share comes back after a relaunch
                ident = getattr(pub.feed, "screen_ident", None)
                if ident is None:
                    try:
                        import kastr_screen
                        ident = pub.feed.screen_ident = kastr_screen.identity(pub.feed.source_url)
                    except Exception:
                        ident = None
                out.append({"url": pub.feed.source_url, "broadcast": pub.broadcast, "audio": bool(pub.audio),
                            "keep": True, "label": pub.label, "screen": ident or {},
                            "addedBy": getattr(pub.feed, "added_by", "") or "", "room": getattr(pub.feed, "room", "") or ""})
                continue
            out.append({"url": pub.feed.source_url, "broadcast": pub.broadcast,
                        "audio": bool(pub.audio), "passthrough": bool(pub.passthrough), "keep": bool(pub.keep),
                        "ondemand": bool(pub.wantOndemand), "low": bool(pub.wantLow), "label": pub.label,   # 0.18.0; 0.21.10: what was ASKED -- preserved while the switch is off
                        "addedBy": getattr(pub.feed, "added_by", "") or "", "room": getattr(pub.feed, "room", "") or ""})   # 0.21.2: a web client's feed
        return out

    def remote_add(self, url, room, label, op):
        """0.21.2: a web client (publisher token, verified by the caller) adds an RTSP camera that THIS host
        pulls, hardware-transcodes and publishes into `room` under <room>/<host>/<op>/<leaf>.hang -- the adder's
        op, so People files it under them. Needs the box's saved publisher code (its own room session) to mint
        the host's token for that room. -> feed.info() + publish, or raises ValueError with the reason."""
        if is_host_feed(url):   # 0.21.26: a camera or file on this computer -- only from the computer itself
            raise ValueError("a camera or media file on the host is added from the host itself")
        if is_screen(url):   # 0.21.20: a screen is shared only from the computer it shows -- never by a web client
            raise ValueError("a screen share starts only on the computer whose screen it is")
        room = str(room or "").strip().lower()
        op = re.sub(r"[^a-z0-9-]+", "-", str(op or "").lower()).strip("-")[:40] or "web"
        if not re.match(r"^[a-z0-9][a-z0-9-]{0,63}$", room):
            raise ValueError("bad room")
        ses = self._session
        if not ses.get("relay") or not ses.get("access"):
            raise ValueError("this host has no publisher code saved -- join a room from the host's KASTR once")
        enc = self.usable_encoder()
        if not enc or enc == "libx264":
            raise ValueError("this host has no hardware encoder")
        label = str(label or "").strip()[:40]
        leaf = re.sub(r"[^a-z0-9-]+", "-", (label or _rtsp_leaf(url)).lower()).strip("-")[:32] or "cam"
        status, tok_url, detail = mint_member(ses["relay"], room, ses.get("access", ""), "", host=self.host_slug)
        if status not in ("token", "open"):
            raise ValueError("the relay did not mint a token for room %s: %s (%s)" % (room, status, detail))
        feed = self.add(url)
        feed.added_by = op
        feed.room = room
        broadcast = "%s/%s/%s/%s.hang" % (room, self.host_slug, op, leaf)
        n = 2
        while any(p.broadcast == broadcast and p.feed is not feed for p in self._pubs.values()):
            broadcast = "%s/%s/%s/%s-%d.hang" % (room, self.host_slug, op, leaf, n); n += 1
        try:
            self.publish(feed.id, broadcast, tok_url, keep=True, label=label or _rtsp_leaf(url))
        except Exception:
            self.remove(feed.id)
            raise
        self.log("rtsp: web client %s added %s -> %s (hardware %s)" % (op, _redact_url(url), broadcast, enc))
        d = feed.info()
        d["publish"] = self.publication(feed.id)
        d["url"] = _redact_url(d.get("url"))
        return d

    def persist_feeds(self):
        """Write room + codes + the feeds on air. Atomic (tmp + replace), owner-only
        on POSIX (the access code is in it). Never called from shutdown(): the file
        must survive a relaunch so restore() can republish."""
        path = self._feeds_file()
        if not path:
            return False
        s = self._session
        relay = _relay_key(s.get("relay", ""))
        if not relay:                   # no session posted yet: the relay the pairs are on (token stripped)
            for pub in list(self._pubs.values()):
                if not pub.stopping:
                    relay = _relay_key(pub.relay)
                    break
        doc = {"room": s.get("room", ""), "access": s.get("access", ""), "roomCode": s.get("roomCode", ""),
               "relay": relay, "feeds": self._feed_records(), "at": time.time(),
               "removed": self._removed[-50:],   # 0.21.0: closed URLs stay closed across relaunches
               "suspended": bool(self.suspended)}   # 0.21.16: the box's RTSP switch -- a relaunch honours it
        with self._persist_lock:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = "%s.%d.tmp" % (path, threading.get_ident())
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(doc, f)
                if os.name != "nt":
                    os.chmod(tmp, 0o600)
                for attempt in range(10):       # a scanner may hold the file for a moment (see _write_children)
                    try:
                        os.replace(tmp, path)
                        break
                    except PermissionError:
                        if attempt == 9:
                            raise
                        time.sleep(0.02 * (attempt + 1))
                return True
            except Exception as e:
                self.log("rtsp: could not write the feed list: %s" % e)
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                return False

    def set_keep(self, feed_id, keep):
        pub = self._pubs.get(int(feed_id))
        if not pub:
            return False
        pub.keep = bool(keep)
        self.persist_feeds()
        return True

    def set_session(self, room, access="", room_code="", relay=""):
        """The page's room + access code (leaving = room ""). Publishers born
        before the session was known get their minter now."""
        self._session = {"room": str(room or "").strip().lower(), "access": str(access or ""),
                         "roomCode": str(room_code or ""), "relay": _relay_key(relay)}
        if self._session["room"]:
            for pub in list(self._pubs.values()):
                if pub.minter is None:
                    pub.minter = self._minter_for(pub.feed, pub.broadcast, pub.relay)
        self.persist_feeds()

    def session_public(self):
        """What the page may see: room, whether a code is saved, relay, the
        persisted feeds (credentials redacted) -- NEVER the codes."""
        s = self._session
        doc = self._read_feeds_file()
        feeds = doc.get("feeds") if isinstance(doc.get("feeds"), list) else None
        if feeds is None:
            feeds = self._feed_records()
        out = {"room": s.get("room", ""), "hasAccess": bool(s.get("access")), "relay": s.get("relay", ""),
               "feeds": [{"broadcast": str(f.get("broadcast") or ""), "keep": bool(f.get("keep", True)),
                          "url": _redact_url(str(f.get("url") or ""))} for f in feeds if isinstance(f, dict)]}
        out["suspended"] = bool(self.suspended)   # 0.21.16: the gate's hint can say the feeds are kept but switched off
        if doc.get("restoreError"):
            out["restoreError"] = str(doc["restoreError"])
        return out

    def session_seed(self):
        """0.14.0: the rescue seed -- what a browser profile that lost its
        storage needs to come back as this box, keyed like the page's
        localStorage: kastr.lastjoin, kastr.rtsp.persist, kastr.rtsp.history
        (each a JSON string, or None when there is nothing to seed).

        Feed URLs travel unredacted (they go loopback-only to the page that
        added them); the room's codes NEVER do -- lastjoin carries code ""
        and access "" (standing rule: access codes never leave the state file
        and are never echoed)."""
        doc = self._read_feeds_file()
        s = self._session
        room = str(doc.get("room") or s.get("room") or "").strip().lower()
        relay = _relay_key(doc.get("relay") or s.get("relay") or "")
        feeds = doc.get("feeds") if isinstance(doc.get("feeds"), list) else None
        if feeds is None:
            feeds = self._feed_records()
        persist, history = [], []
        for f in feeds:
            if not isinstance(f, dict):
                continue
            url = str(f.get("url") or "").strip()
            if not url or url.startswith("test://"):
                continue
            if url not in history:
                history.append(url)                 # rememberRtsp: every url added, newest first, 15 max
            if f.get("keep") is False or any(p["url"] == url for p in persist):
                continue
            persist.append({"url": url, "label": _seed_label(str(f.get("broadcast") or ""), url)})
        out = {"kastr.lastjoin": None, "kastr.rtsp.persist": None, "kastr.rtsp.history": None}
        if room:
            out["kastr.lastjoin"] = json.dumps({"room": room, "code": "", "access": "", "relay": relay,
                                                "micOn": False, "vidOn": False})
        if persist:
            out["kastr.rtsp.persist"] = json.dumps(persist)
        if history:
            out["kastr.rtsp.history"] = json.dumps(list(reversed(history))[:15])
        return out

    def _minter_for(self, feed, broadcast, relay=""):
        """A fresh room token for one publisher via the relay's minter, from
        the session (room + access code). None when no room is known. The
        callable returns the tokened URL ("token"), the bare URL ("open") or
        None (refused / down), logging each new refusal reason once."""
        if not self._session.get("room"):
            return None
        fid = feed.id
        last = [None]

        def mint():
            ses = self._session
            if not ses.get("room"):
                return None
            cur = self._pubs.get(fid)
            base = ses.get("relay") or _relay_key(cur.relay if cur is not None else relay)
            room = getattr(feed, "room", "") or ses["room"]   # 0.21.2: a web client's feed lives in ITS room
            status, url, detail = mint_member(base, room, ses.get("access", ""), ses.get("roomCode", "") if room == ses["room"] else "",
                                              host=self.host_slug)     # 0.13.0
            # 0.13.2: "open" because the minter did not answer is not a licence to go bare: a publisher
            # that had a token keeps waiting for one (a secured relay severs a bare dial with code=6).
            if status == "open" and "no minter" in str(detail) and cur is not None and "jwt=" in str(cur.relay or ""):
                status, detail = "down", "minter not answering (keeping the token)"
            if status in ("token", "open"):
                last[0] = None
                return url
            why = "%s (%s)" % (status, detail)
            if why != last[0]:
                last[0] = why
                self.log("rtsp: publisher %s could not get a token for room %s: %s" % (broadcast, ses["room"], why))
            return None
        return mint

    def _feed_by_source(self, url):
        for f in list(self._feeds.values()):
            if f.source_url == url:
                return f
        return None

    def restore(self, mint=None, log=None):
        """Republish the persisted feeds (keep=true) into the saved room at
        launch. `mint()` -> the relay URL to publish on (?jwt= on a secured
        relay, bare on an open one) or None; the caller has already waited for
        the relay to answer. Publishes run in parallel (each may probe its
        camera for up to PROBE_TIMEOUT). Returns how many came back."""
        log = log or self.log
        doc = self._read_feeds_file()
        room = str(doc.get("room") or "").strip().lower()
        gone = {str(r.get("url")) for r in (doc.get("removed") or []) if isinstance(r, dict) and r.get("url")}   # 0.21.0
        feeds = [f for f in (doc.get("feeds") or [])
                 if isinstance(f, dict) and f.get("url") and f.get("keep", True) and str(f.get("url")) not in gone]
        if not room or not feeds:
            return 0
        self._session = {"room": room, "access": str(doc.get("access") or ""),
                         "roomCode": str(doc.get("roomCode") or ""), "relay": _relay_key(doc.get("relay") or "")}
        url = None
        try:
            url = mint() if mint else (self._session["relay"] or None)
        except Exception as e:
            log("rtsp restore: minting a token failed: %s" % e)
        if not url:
            log("rtsp restore: no relay url for room %s -- %d feed(s) not republished" % (room, len(feeds)))
            return 0
        done = [0]
        lock = threading.Lock()

        def one(rec):
            try:
                if is_screen(rec.get("url") or ""):   # 0.21.26: still there? (a closed window / tab is dropped, not retried)
                    import kastr_screen
                    now_url = kastr_screen.relocate(rec["url"], rec.get("screen"))
                    if not now_url:
                        what = (rec.get("screen") or {}).get("title") or rec.get("label") or rec["url"]
                        log("rtsp restore: %s share '%s' is no longer there -- dropped" % ((rec.get("screen") or {}).get("kind") or "screen", what))
                        return
                    if now_url != rec["url"]:
                        log("rtsp restore: %s found again as %s" % (rec["url"], now_url))
                    rec = dict(rec, url=now_url)
                feed = self._feed_by_source(rec["url"]) or self.add(rec["url"])
                rurl = url
                if rec.get("room") and rec.get("room") != room:   # 0.21.2: a web client's feed in another room
                    feed.added_by = str(rec.get("addedBy") or ""); feed.room = str(rec.get("room"))
                    st, u2, det = mint_member(self._session["relay"], rec["room"], self._session.get("access", ""), "", host=self.host_slug)
                    if st not in ("token", "open"):
                        raise RuntimeError("no token for room %s: %s (%s)" % (rec["room"], st, det))
                    rurl = u2
                self.publish(feed.id, rec.get("broadcast") or ("cam%d" % feed.id), rurl,
                             audio=(rec.get("audio") is not False), passthrough=bool(rec.get("passthrough")), keep=True,
                             ondemand=bool(rec.get("ondemand")), low=bool(rec.get("low")), label=str(rec.get("label") or ""))   # 0.18.0
                with lock:
                    done[0] += 1
            except Exception as e:
                log("rtsp restore: %s -> %s failed: %s" % (_redact_url(str(rec.get("url"))), rec.get("broadcast"), e))
        threads = [threading.Thread(target=one, args=(r,), daemon=True) for r in feeds]
        for t in threads:
            t.start()
        deadline = time.time() + 30
        for t in threads:
            t.join(max(0.1, deadline - time.time()))
        log("rtsp: %s %d persisted feed(s) into room %s" % ("recorded (publishing suspended)" if self.suspended else "republished", done[0], room))   # 0.21.16
        self.persist_feeds()
        return done[0]

    def nudge(self, feed_id, why="api"):
        pub = self._pubs.get(int(feed_id))
        if pub:
            if getattr(pub, "suspended", False):   # 0.21.16: a viewer/no-echo report against a switched-off camera is not news -- no log line, no restart
                return False
            # 0.13.1: one line per restart request, counters as they stood
            self.log("rtsp nudge %s why=%s restarts=%d sessionFails=%d sessionKills=%d"
                     % (pub.broadcast, why, pub.restarts, pub.sessionFails, pub.sessionKills))
            pub.nudge(why)
        return bool(pub)

    def publication(self, feed_id):
        pub = self._pubs.get(int(feed_id))
        return pub.info() if pub else None

    def get(self, feed_id):
        return self._feeds.get(int(feed_id))

    def list(self, redact=False):
        """0.13.3: `redact` strips camera credentials from every URL (and the
        stderr tails that may quote one) -- for a page on ANOTHER machine, which
        never needed them; the box's own page keeps the raw URL it keys its
        per-URL settings by."""
        out = []
        for f in self._feeds.values():
            d = f.info()
            d["publish"] = self.publication(f.id)   # 0.9.1
            d["addedBy"] = getattr(f, "added_by", "") or ""   # 0.21.2: a web client's camera (empty = the box's own)
            if redact:
                d["url"] = _redact_url(d.get("url"))
                if isinstance(d.get("error"), str):
                    d["error"] = _redact_url(d["error"])
                pub = d.get("publish")
                if isinstance(pub, dict):
                    for k in ("relay", "error", "lastSession"):
                        if isinstance(pub.get(k), str):
                            pub[k] = _redact_url(pub[k])
            out.append(d)
        return out

    def kill(self, feed):
        """Stop every reader's ffmpeg for this feed."""
        for p in list(feed.procs):
            self.release(feed, p)

    def release(self, feed, proc):
        """Stop one reader's ffmpeg, leaving the feed's other readers alone."""
        feed.procs.discard(proc)
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    # ---- 0.21.16: the box's RTSP switch -----------------------------------------------
    def suspend(self, who="operator"):
        """Stop publishing EVERY camera this box owns -- pairs, low copies and the owner's monitors -- and keep
        every record: feeds, publishers, rtsp-feeds.json, the page's rows and grids. start() refuses until
        resume(); a publish request meanwhile is recorded, not started. Not a watchdog: nothing here flips
        the switch by itself -- only /api/rtsp/suspend (page, Relay page) or the hub's `rtsp` command."""
        with self._lock:
            if self.suspended:
                return {"ok": True, "suspended": True, "stopped": 0, "monitors": 0, "records": len(self._pubs)}
            self.suspended = True
            pubs = list(self._pubs.values())
            feeds = list(self._feeds.values())
        stopped = sum(1 for p in pubs if p.suspend(who))
        mons = 0
        for f in feeds:
            mons += len(f.procs)
            self.kill(f)                      # the owner's monitors; the page stops re-attaching while suspended
        self.persist_feeds()
        self.log("rtsp: publishing SUSPENDED by %s -- %d pair(s) stopped, %d monitor(s) released, %d record(s) kept"
                 % (who, stopped, mons, len(pubs)))
        return {"ok": True, "suspended": True, "stopped": stopped, "monitors": mons, "records": len(pubs)}

    def resume(self, who="operator"):
        """The switch is back on: every recorded pair starts again (an on-demand one returns to standby). The starts
        run in parallel and are joined for at most 30 s, like restore(): start() probes a camera nobody has probed
        yet (a feed recorded while the switch was off) for up to PROBE_TIMEOUT under the publisher's own lock."""
        with self._lock:
            if not self.suspended:
                return {"ok": True, "suspended": False, "started": 0, "records": len(self._pubs)}
            self.suspended = False
            pubs = list(self._pubs.values())
        done = []

        def one(p):
            try:
                if p.resume(who):
                    done.append(p.broadcast)
                    if p.ondemand:               # 0.18.0 shape: standby + demand loop + low copy (inert while ONDEMAND_ENABLED is off)
                        self._od_ensure()
                        self._low_standby(p)
            except Exception as e:
                self.log("rtsp: resuming %s failed: %s" % (p.broadcast, e))
        threads = [threading.Thread(target=one, args=(p,), daemon=True, name="kastr-rtsp-resume") for p in pubs]
        for t in threads:
            t.start()
        deadline = time.time() + 30
        for t in threads:
            t.join(max(0.1, deadline - time.time()))
        self.persist_feeds()
        self.log("rtsp: publishing RESUMED by %s -- %d of %d pair(s) starting" % (who, len(done), len(pubs)))
        return {"ok": True, "suspended": False, "started": len(done), "records": len(pubs)}

    def shutdown(self):
        # 0.9.8: explicit kills as before; the job (shared with the relay, which
        # gets its own graceful stop right after this) closes with the process
        # and reaps anything these loops missed.
        for fid in list(self._pubs):
            self.unpublish(fid, persist=False)   # 0.12.0: rtsp-feeds.json stays as it is -- restore() reads it next launch
        for feed in list(self._feeds.values()):
            self.kill(feed)
        for proc in list(self._media):   # 0.14.0: the player's ffmpeg children
            self.release_media(proc)
        with self._children_lock:
            self._children.clear()
        self._write_children()           # removes our registry file

    def own_pid(self):
        """0.21.20: the process tree whose sound a screen share leaves out -- this host (its browser is a child)."""
        return os.getpid()

    def usable_encoder(self):
        """First encoder from ENCODERS that actually works here.

        Validated against a local test pattern rather than trusted from
        "ffmpeg -encoders": a laptop can list h264_nvenc and still fail to
        initialise it, which would otherwise produce a feed that never
        delivers a byte.
        """
        if self._encoder is not None:
            return self._encoder

        listed = set()
        try:
            out = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            listed = {name for name in ENCODERS if name in (out.stdout or "")}
        except Exception:
            pass

        for name in ENCODERS:
            if name not in listed and name != "libx264":
                continue
            cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error"] + encoder_pre_args(name) + [
                "-f", "lavfi", "-i", "testsrc2=size=3840x2160:rate=30:duration=0.2",
                "-vf", encoder_vf(name, "scale=%d:-2,format=yuv420p" % MAX_WIDTH),
                "-c:v", name,
            ]
            if name != "libx264":
                cmd += ["-b:v", "4M"]
            cmd += ["-f", "null", "-"]
            try:
                done = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if done.returncode == 0:
                    self._encoder = name
                    # Remembered so the choice is visible in the feed list
                    # rather than only in a console this app may not have.
                    self.encoder_note = name
                    return name
            except Exception:
                continue

        self._encoder = "libx264"
        return self._encoder

    def sends_h264(self, feed):
        """Is this feed already H.264? Probed once, then remembered.

        Worth a second on first connect: copying an H.264 camera runs at
        1.15x real time where re-encoding it managed 0.30x, and anything
        under 1.0x can never keep up with a live stream.
        """
        if getattr(feed, "h264", None) is not None:
            # 0.12.0: a probe that could not tell (camera off when a restored
            # feed came back) is believed for PROBE_RETRY_S, then asked again --
            # not for the rest of the run, which encoded copyable cameras.
            failed = getattr(feed, "probe_failed_at", None)
            if not failed or time.time() - failed < PROBE_RETRY_S:
                return feed.h264
            feed.h264 = None
        if feed.url == TEST_URL:
            feed.h264 = False           # lavfi is raw; it has to be encoded
            return False
        if is_rtmp_in(feed.url):        # 0.21.29: what a device pushes over RTMP is H.264 (+ AAC) -- copied
            feed.h264, feed.vcodec, feed.fullrange, feed.sar = True, "h264", False, None
            feed.width = feed.height = None
            return True
        if is_device(feed.url):         # 0.21.26: our own capture -- H.264 baseline, copied by every reader
            feed.h264, feed.vcodec, feed.fullrange, feed.sar = True, "h264", False, None
            feed.width, feed.height = 1280, 720
            return True
        if is_hostmedia(feed.url):      # 0.21.26: a looped file restarts its timestamps -- always encoded
            feed.h264, feed.vcodec, feed.fullrange, feed.sar = False, "file", False, None
            feed.width = feed.height = None
            return False
        if is_screen(feed.url):         # 0.21.20: a capture is raw too -- encoded, never copied
            import kastr_screen
            feed.h264, feed.vcodec, feed.fullrange, feed.sar = False, "rawvideo", False, None
            feed.width, feed.height = kastr_screen.capture_size(feed.url)
            return False

        # Keyed by url on the bridge, so a reconnect -- which builds a new feed
        # object -- does not pay for the probe again. Same camera, same answer.
        cached = self._probed.get(feed.url)
        if cached is not None:
            feed.h264, feed.width, feed.height, feed.fullrange = cached[:4]
            feed.vcodec = cached[4] if len(cached) > 4 else ("h264" if feed.h264 else None)
            feed.acodec = cached[5] if len(cached) > 5 else None   # 0.9.5
            feed.sar = cached[6] if len(cached) > 6 else None      # 0.9.8
            return feed.h264

        # -c copy so it never decodes, and read only until it names the
        # stream. Waiting for the whole command took 12.6s on a 4K camera;
        # the codec line arrives about 2.9s in.
        cmd = ([self.ffmpeg, "-hide_banner"] + input_args(feed.url)
               + ["-c", "copy", "-f", "null", "-"])
        proc = None
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _job_assign(self._job, proc, self.log)   # 0.9.8: a probe cut short by a quit dies with us too
            deadline = time.monotonic() + PROBE_TIMEOUT
            seen_video = False
            for line in proc.stderr:
                # 0.9.5: the audio stream line (before or after the video one)
                # tells the page whether "Send audio" has anything to send.
                aud = re.search(r"Stream #\d+:\d+.*?: Audio: (\w+)", line)
                if aud:
                    feed.acodec = aud.group(1).lower()
                    if seen_video:
                        break
                    continue
                if seen_video:
                    # past the input streams: the output/mapping section starts
                    if line.startswith("Output #") or "Stream mapping" in line or "Press [q]" in line:
                        break
                    if time.monotonic() > deadline:
                        break
                    continue
                found = re.search(r"Stream #\d+:\d+.*?: Video: (\w+)", line)
                if found:
                    feed.vcodec = found.group(1).lower()   # 0.9.2
                    feed.h264 = feed.vcodec == "h264"
                    # Same line carries the frame size, e.g. 3840x2160.
                    size = re.search(r"[ ,](\d{2,5})x(\d{2,5})[ ,]", line)
                    if size:
                        feed.width = int(size.group(1))
                        feed.height = int(size.group(2))
                    # ...and the colour range. Full range reads as yuvj420p or
                    # an explicit "(pc,". The browser's encoder refuses those.
                    feed.fullrange = bool(re.search(r"yuvj\d|\(pc[,)]", line))
                    # 0.9.8: "[SAR 1:1 DAR 16:9]" -- non-square pixels must be encoded
                    sar = re.search(r"SAR (\d+):(\d+)", line)
                    feed.sar = (int(sar.group(1)), int(sar.group(2))) if sar else None
                    seen_video = True      # keep reading a little for the audio line
                    continue
                if time.monotonic() > deadline:
                    break
        except Exception:
            pass
        finally:
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
        if feed.h264 is None:
            # Could not tell. Re-encoding works for anything, so prefer being
            # slow-but-correct over fast-but-maybe-undecodable.
            feed.h264 = False
            feed.probe_failed_at = time.time()   # 0.12.0: tentative -- not cached on the bridge either
        else:
            feed.probe_failed_at = None          # 0.12.0
            if feed.acodec is None:
                feed.acodec = ""       # 0.9.5: probed, and the camera has no audio track
            self._probed[feed.url] = (feed.h264, feed.width, feed.height,
                                      feed.fullrange, feed.vcodec, feed.acodec, feed.sar)
        return feed.h264

    def monitor_plan(self, feed, transcode=False, passthrough=False):
        """(copy?, hvc1?) for the monitor stream -- the publisher's rule, plus
        the page's `transcode=1` override for a copy its <video> could not play."""
        h264 = self.sends_h264(feed)
        vcodec = (feed.vcodec or ("h264" if h264 else "")).lower()
        copy = (not transcode) and passthrough_ok(vcodec, feed.width, feed.fullrange, passthrough, feed.sar)
        return copy, copy and vcodec in ("hevc", "h265")

    def monitor_codec(self, feed, transcode=False, passthrough=False):
        """What the monitor stream carries (0.9.7): the camera's own codec when
        copied, H.264 when encoded. The page opens its MediaSource with it."""
        copy, _ = self.monitor_plan(feed, transcode, passthrough)
        vc = (feed.vcodec or "h264").lower()
        return (vc if copy else "h264"), copy

    def spawn(self, feed, transcode=False, passthrough=False):
        """Start ffmpeg for this feed's monitor stream and return the process."""
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found")
        head = [self.ffmpeg, "-hide_banner", "-loglevel", "error"]
        copy, hvc1 = self.monitor_plan(feed, transcode, passthrough)
        claim = {}   # 0.21.30: the monitor slot this ffmpeg reads (camera / RTMP ingest captures)
        if copy:
            args = head + input_args(feed.url, role="mon", claim=claim) + output_args(feed.url, True, hvc1=hvc1)
        else:
            # 0.9.6: small and fast -- see output_args
            enc = self.usable_encoder()
            args = head + encoder_pre_args(enc) + input_args(feed.url, role="mon", claim=claim) + output_args(feed.url, False, encoder=enc,
                                                                       width=1920 if getattr(feed, "presenter", False) else None)   # 0.21.20: presenter mode composites this picture
        # Windows: keep the console window from flashing up for each feed.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, creationflags=flags,
        )
        _job_assign(self._job, proc, self.log)   # 0.9.8: dies with KASTR (its pipe would end it anyway)
        if claim.get("port") and DEVICES.get(feed.url):
            DEVICES[feed.url].attach(claim["port"], proc)
        feed.procs.add(proc)
        # Clear the tail as well as the summary: clearing only `error` let the
        # drain thread rebuild it from lines the PREVIOUS child left behind, so
        # a fresh attempt reported the last attempt's dying words.
        feed.errors.clear()
        feed.error = None

        # Drain stderr so a chatty ffmpeg can't block on a full pipe, and keep
        # the last line to report back as the feed's error.
        def drain():
            try:
                for line in proc.stderr:
                    text = line.decode("utf-8", "replace").strip()
                    if text:
                        # Keep a short tail, not just the last line: a TLS or
                        # auth failure explains itself a line or two earlier.
                        feed.errors.append(text)
                        del feed.errors[:-4]
                        feed.error = " / ".join(feed.errors)
            except Exception:
                pass

        threading.Thread(target=drain, daemon=True).start()
        return proc

    # ---- 0.14.0: media child processes (the player's ffmpeg/ffprobe) ------
    def spawn_media(self, argv, tag="media", nice=False):
        """A plain argv child -- no Feed. Registered like every other child
        (job object + rtsp-children-<pid>.json, so sweep_orphans reaps it
        after a crash). stdout is the caller's to read; stderr is drained so
        a chatty ffmpeg never blocks on a full pipe, its last 4 non-empty
        lines kept on proc.kastr_errors.
        0.16.0: `nice` runs the child below normal priority -- a media transcode
        must never starve the browser's own encoder (the viewers' picture)."""
        argv = [str(a) for a in argv]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kw = {}
        if nice:
            if sys.platform == "win32":
                flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            else:
                kw["preexec_fn"] = lambda: os.nice(10)
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                bufsize=0, creationflags=flags, **kw)
        proc.kastr_errors = []
        self._child_started(proc, argv, [argv[-1]] if len(argv) > 1 else [], tag)   # job + registry
        with self._children_lock:
            self._media.add(proc)

        def drain():
            try:
                for line in proc.stderr:
                    text = line.decode("utf-8", "replace").strip()
                    if text:
                        proc.kastr_errors.append(text)
                        del proc.kastr_errors[:-4]
            except Exception:
                pass
            # stderr closed = the child is gone (ffmpeg holds it to the end): out of
            # the registry even when nobody calls release_media (a conversion that
            # simply finished). EOF lands a beat before the exit is visible, so reap.
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            try:
                if proc.poll() is not None:
                    self.release_media(proc)
            except Exception:
                pass

        threading.Thread(target=drain, daemon=True).start()
        return proc

    def release_media(self, proc):
        """Kill (if alive) and unregister one spawn_media child. Best-effort."""
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
        except OSError:
            pass
        with self._children_lock:
            self._media.discard(proc)
        self._child_ended(proc.pid)


def handle_api(handler, bridge, path):
    """Serve the /api/rtsp/* endpoints. Returns True if it handled the request."""
    if not path.startswith("/api/rtsp"):
        return False

    def reply(obj, code=200):
        body = json.dumps(obj).encode()
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    def from_loopback():
        # 0.9.1: the page on this machine reaches us as 127.0.0.1/localhost;
        # anything else (LAN IP, phone over HTTPS, a remote page) is foreign.
        # 0.17.0: the request class -- Host AND peer AND Origin (a typed Host
        # header is not an identity). Imported here: kastr_relay imports us.
        import kastr_relay
        return kastr_relay.is_local(handler)

    def remote_claims(room, jwt):
        """0.21.2: a web client's member token (kastr_serve's handler verifies it; None outside kastr_serve).
        -> (claims, error_reply) -- claims when the token covers `room` and the relay here is secured."""
        fn = getattr(handler, "_room_claims", None)
        if not callable(fn):
            return None, ({"error": "feed changes only from the machine itself"}, 403)
        import kastr_relay
        relay_srv = getattr(handler, "kastr_relay_srv", None)
        if relay_srv is None or not getattr(relay_srv, "secured", False):
            return None, ({"error": "web clients may add cameras only through a relay that requires access codes"}, 403)
        err = fn(room, jwt)
        if err is not None:
            return None, ({"error": err[1]}, err[0])
        claims = getattr(handler, "_claims", None)
        if kastr_relay.claims_role(claims) not in ("publisher", "admin", "relay"):
            return None, ({"error": "the publisher access code is needed to add a camera"}, 403)
        return claims, None

    def bearer():
        h = str(handler.headers.get("Authorization") or "")
        return h[7:].strip() if h.lower().startswith("bearer ") else ""

    if path == "/api/rtsp/list":
        if not from_loopback():
            # 0.21.2: a web client with a publisher token sees the room's host-published feeds (redacted) + whether it may add
            q = dict(kv.split("=", 1) if "=" in kv else (kv, "") for kv in getattr(handler, "path", "").partition("?")[2].split("&") if kv)
            room = q.get("room", "")
            jwt = bearer() or q.get("jwt", "")
            if room and jwt:
                claims, err = remote_claims(room, jwt)
                if claims is not None:
                    import kastr_relay
                    me = ""
                    try:
                        _r, me_host = kastr_relay.claims_identity(claims)
                        me = str(me_host or "")
                    except Exception:
                        pass
                    rows = [f for f in bridge.list(redact=True) if str((f.get("publish") or {}).get("broadcast") or "").startswith(room + "/")]
                    enc = bridge.usable_encoder()
                    reply({"feeds": rows, "ffmpeg": bool(bridge.ffmpeg), "ffmpegPath": "", "moq": bool(bridge.moq), "remote": True,
                           "viaHost": True, "canAdd": bool(enc and enc != "libx264"), "hwEncoder": enc, "me": me})
                    return True
            # 0.17.0: a web client has no bridge here -- the page hides its RTSP paths
            reply({"feeds": [], "ffmpeg": False, "ffmpegPath": "", "moq": False, "remote": True})
            return True
        hk = getattr(bridge, "hooks", None)
        reply({"feeds": bridge.list(redact=False),
               "ffmpeg": bool(bridge.ffmpeg),
               "ffmpegPath": bridge.ffmpeg or "",
               "moq": bool(bridge.moq),                       # 0.9.1: native publishing available
               "hooks": (hk.configured() if hk else {}),       # 0.18.0: which hooks are set (never the commands)
               "hookLog": (list(hk.fired) if hk else []),
               "suspended": bool(getattr(bridge, "suspended", False))})   # 0.21.16: the box's RTSP switch
        return True

    if path in ("/api/rtsp/publish", "/api/rtsp/unpublish", "/api/rtsp/nudge", "/api/rtsp/suspend",   # 0.21.16: suspend
                "/api/rtsp/keep", "/api/rtsp/persist", "/api/rtsp/note"):   # 0.12.0: keep, persist; 0.21.5: note
        # 0.9.1: local pages only -- these start processes and name relays
        if not from_loopback():
            reply({"error": "publishing is controlled from the machine itself"}, 403)
            return True
        if path == "/api/rtsp/persist" and getattr(handler, "command", "POST") != "POST":   # 0.12.0: GET = read-back
            reply(bridge.session_public())
            return True
        try:
            n = int(handler.headers.get("Content-Length") or 0)
            payload = json.loads(handler.rfile.read(n) or b"{}")
        except Exception:
            reply({"error": "bad json"}, 400)
            return True
        try:
            if path == "/api/rtsp/publish":
                had_pubs = bool(getattr(bridge, "_pubs", None))   # 0.21.16: the first camera record -> the hub's Cameras column
                pub = bridge.publish(payload.get("id"), payload.get("broadcast"), payload.get("relay"),
                                     hevc=bool(payload.get("hevc")),   # 0.9.2 (old name)
                                     audio=(payload.get("audio") is not False),   # 0.9.5: default on
                                     passthrough=bool(payload.get("passthrough", payload.get("hevc"))),   # 0.9.6
                                     force=bool(payload.get("force")),   # 0.9.8: otherwise the same request keeps the running pair
                                     keep=payload.get("keep"),           # 0.12.0: None = leave as is (new pair: on)
                                     ondemand=bool(payload.get("ondemand")), low=bool(payload.get("low")),   # 0.18.0
                                     label=str(payload.get("label") or ""))
                if not had_pubs:   # 0.21.16: a spoke re-registers now -- the hub's spokes table learns it HAS cameras (and their switch) at once, not at the 10-min tick
                    try:
                        getattr(handler, "kastr_relay_srv", None).spoke_sync_soon()
                    except Exception:
                        pass
                reply(pub.info())
            elif path == "/api/rtsp/unpublish":
                ok_un = bridge.unpublish(payload.get("id"))
                if not getattr(bridge, "_pubs", None):   # 0.21.16: the last camera record went -- the hub's column says so now
                    try:
                        getattr(handler, "kastr_relay_srv", None).spoke_sync_soon()
                    except Exception:
                        pass
                reply({"ok": ok_un})
            elif path == "/api/rtsp/keep":                                # 0.12.0
                reply({"ok": bridge.set_keep(payload.get("id"), payload.get("keep"))})
            elif path == "/api/rtsp/persist":                             # 0.12.0: the page's room + access code
                room = str(payload.get("room") or "").strip().lower()
                if not re.match(r"^[a-z0-9-]{0,32}$", room):
                    raise ValueError("bad room name")
                relay = str(payload.get("relay") or "").strip()
                if relay and not relay.lower().startswith(("http://", "https://")):
                    raise ValueError("relay must be an http(s) url")
                bridge.set_session(room, payload.get("access"), payload.get("roomCode"), relay)
                reply(bridge.session_public())
            elif path == "/api/rtsp/suspend":                             # 0.21.16: the box's RTSP switch -- {suspend: bool, who?}; {} = read-back
                if payload.get("suspend") is None:
                    reply({"ok": True, "suspended": bool(getattr(bridge, "suspended", False))})
                else:
                    who = re.sub(r"[^A-Za-z0-9 ._#:-]+", "", str(payload.get("who") or "operator")).strip()[:24] or "operator"
                    res = bridge.suspend(who) if payload.get("suspend") else bridge.resume(who)
                    try:   # the hub's spokes table (Cameras column) follows a local flip now, not at the next registration
                        getattr(handler, "kastr_relay_srv", None).spoke_sync_soon()
                    except Exception:
                        pass
                    reply(res)
            elif path == "/api/rtsp/note":                                # 0.21.5: the page's grid events -> launch.log
                text = re.sub(r"\s+", " ", str(payload.get("text") or "")).strip()[:240]
                if text:
                    bridge.log("page: " + text)
                reply({"ok": bool(text)})
            else:
                why = str(payload.get("why") or "api").strip()[:32] or "api"   # 0.13.1
                reply({"ok": bridge.nudge(payload.get("id"), why)})
        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            reply({"error": str(e)}, 400)
        return True

    if path in ("/api/rtsp/add", "/api/rtsp/remove"):
        try:
            n = int(handler.headers.get("Content-Length") or 0)
            payload = json.loads(handler.rfile.read(n) or b"{}")
        except Exception:
            reply({"error": "bad json"}, 400)
            return True
        if not from_loopback():
            # 0.21.2: a WEB CLIENT adds a camera that THIS host pulls -- publisher token for the room, hardware encoder
            room = str(payload.get("room") or "")
            jwt = bearer() or str(payload.get("jwt") or "")
            claims, err = remote_claims(room, jwt)
            if claims is None:
                reply(*err)
                return True
            import kastr_relay
            op = ""
            try:
                op = str(kastr_relay.claims_identity(claims)[1] or "")   # the web device's host id -- People keys on op; use the name the page sends
            except Exception:
                pass
            who = re.sub(r"[^a-z0-9-]+", "-", str(payload.get("op") or op or "web").lower()).strip("-")[:40] or "web"
            try:
                if path == "/api/rtsp/add":
                    if not bridge.ffmpeg:
                        reply({"error": "ffmpeg not available on the host"}, 503)
                        return True
                    reply(bridge.remote_add(payload.get("url"), room, payload.get("label"), who))
                else:
                    feed = bridge.get(payload.get("id"))
                    if feed is None:
                        reply({"error": "no such feed"}, 404)
                        return True
                    if getattr(feed, "added_by", "") != who and not kastr_relay.claims_admin(claims, room):
                        reply({"error": "only the person who added this camera (or an admin) can remove it"}, 403)
                        return True
                    reply({"ok": bridge.remove(feed.id)})
            except (ValueError, KeyError, TypeError) as e:
                reply({"error": str(e)}, 400)
            return True
        try:
            if path == "/api/rtsp/add":
                if not bridge.ffmpeg:
                    reply({"error": "ffmpeg not available"}, 503)
                    return True
                feed = bridge.add(payload.get("url"))
                if is_screen(feed.url) and payload.get("presenter"):   # 0.21.20: the page composites it -- a 1920-wide monitor, no native pair
                    feed.presenter = True
                reply(feed.info())
            else:
                reply({"ok": bridge.remove(payload.get("id"))})
        except (ValueError, KeyError, TypeError) as e:
            reply({"error": str(e)}, 400)
        return True

    reply({"error": "unknown endpoint"}, 404)
    return True


def parse_stream_path(path):
    """/rtsp/<id>[?pt=1][&transcode=1] -> (id, transcode, passthrough). 0.9.6:
    the page says whether copying is allowed (pt) and whether a copy failed to
    play in its <video> (transcode)."""
    base, _, query = path.partition("?")
    flags = {kv.split("=", 1)[0]: kv.split("=", 1)[1] if "=" in kv else "1" for kv in query.split("&") if kv}
    return base.rsplit("/", 1)[-1], flags.get("transcode") == "1", flags.get("pt") == "1"


_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_WS_SAID = [False]


def _ws_frame(payload, opcode=0x2):
    """0.21.10: one unmasked server->client WebSocket frame (FIN set)."""
    n = len(payload)
    if n < 126:
        head = bytes([0x80 | opcode, n])
    elif n < 65536:
        head = bytes([0x80 | opcode, 126]) + n.to_bytes(2, "big")
    else:
        head = bytes([0x80 | opcode, 127]) + n.to_bytes(8, "big")
    return head + payload


def _ws_watch(conn, alive):
    """0.21.10: answer the browser's close and ping frames on a monitor socket. A detached monitor
    sends a close frame and Chromium then waits up to 60 s for ours before dropping TCP; without
    this the pump would keep an ffmpeg child busy that long. recv only after select says readable,
    so the pump's SEND_TIMEOUT never trips here."""
    import select
    import socket
    try:
        while alive[0]:
            r, _, _ = select.select([conn], [], [], 1.0)
            if not r:
                continue
            data = conn.recv(4096)
            if not data:
                break
            op = data[0] & 0x0F
            if op == 0x8:
                try:
                    conn.sendall(bytes([0x88, 0x00]))
                except OSError:
                    pass
                break
            if op == 0x9:
                try:
                    conn.sendall(bytes([0x8A, 0x00]))
                except OSError:
                    pass
    except (OSError, ValueError):
        pass
    if alive[0]:
        alive[0] = False
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

def handle_stream(handler, bridge, path):
    """Serve GET /rtsp/<id> as an endless fragmented MP4."""
    if not path.startswith("/rtsp/"):
        return False
    import kastr_relay
    if not kastr_relay.is_local(handler):   # 0.17.0: the monitor is the owner page's
        handler.send_error(403, "feed monitors only for the machine itself")
        return True
    feed_id, transcode, passthrough = parse_stream_path(path)
    try:
        feed = bridge.get(feed_id)
    except ValueError:
        feed = None
    if not feed:
        handler.send_error(404, "no such feed")
        return True
    if getattr(bridge, "suspended", False):   # 0.21.16: no monitor decode while the box's RTSP switch is off (the page does not retry meanwhile)
        handler.send_error(503, "RTSP publishing is suspended on this box")
        return True

    # 0.21.11: the monitor follows the camera's publisher. The page sends pt=1 only when its own localStorage
    # switch is on; a box whose pairs were restored with passthrough=true (the operator's choice, persisted) was
    # re-encoding every monitor -- five software 4K H.265 decodes on one relay box. A copied monitor the page
    # cannot decode still falls back to transcode=1 on its own (monitorBroken), so this only ever removes work.
    if not passthrough and not transcode:
        pub = getattr(bridge, "_pubs", {}).get(feed.id)
        if pub is not None and getattr(pub, "passthrough", False) and getattr(pub, "copy", False):
            passthrough = True
            if not getattr(feed, "_mon_pt_said", False):
                feed._mon_pt_said = True
                bridge.log("rtsp monitor: feed %s follows its publisher's passthrough (copy, %s)" % (feed.id, getattr(pub, "codec", None) or "?"))

    try:
        proc = bridge.spawn(feed, transcode=transcode, passthrough=passthrough)
    except RuntimeError as e:
        handler.send_error(503, str(e))
        return True

    codec, copied = bridge.monitor_codec(feed, transcode, passthrough)
    # 0.21.10: the page asks for the monitor over a WebSocket when it can. Chromium allows six
    # concurrent HTTP/1.1 connections per host and every monitor held one for as long as the camera
    # streamed, so the seventh camera -- and every fetch the page made after it -- waited in the
    # browser's queue until a stream closed. WebSockets sit outside that pool. Same bytes, framed.
    ws_key = (handler.headers.get("Sec-WebSocket-Key") or "").strip()
    ws = bool(ws_key) and (handler.headers.get("Upgrade") or "").strip().lower() == "websocket"
    if ws:
        import base64
        import hashlib
        accept = base64.b64encode(hashlib.sha1((ws_key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
        try:
            handler.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                                 "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode("ascii"))
            handler.wfile.write(_ws_frame(json.dumps({"codec": codec, "copy": copied}).encode("utf-8"), 0x1))
        except (BrokenPipeError, ConnectionResetError, OSError):
            bridge.release(feed, proc)
            return True
        if not _WS_SAID[0]:
            _WS_SAID[0] = True
            bridge.log("rtsp monitor: streaming over WebSocket (outside the browser's six-connection cap)")
    else:
        handler.send_response(200)
        handler.send_header("Content-Type", "video/mp4")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-KASTR-Codec", codec)          # 0.9.7: the page's MSE player needs it up front
        handler.send_header("X-KASTR-Copy", "1" if copied else "0")
        # No Content-Length: the stream is open-ended, so the connection staying
        # open IS the framing.
        handler.end_headers()

    # Set AFTER the headers so it governs only the pump (the request itself
    # was fully read before dispatch). socket.timeout is an OSError, so the
    # except below already catches it, and this server speaks HTTP/1.0 with
    # connection-close framing, so the timeout cannot leak into another
    # request. The page-side live-edge keeper is what makes 15s safe: a
    # healthy reader is never more than ~3s behind, so only a genuinely
    # wedged one goes quiet this long.
    handler.connection.settimeout(SEND_TIMEOUT)

    alive = [True]
    if ws:
        threading.Thread(target=_ws_watch, args=(handler.connection, alive), daemon=True).start()
    try:
        while True:
            chunk = proc.stdout.read(16384)
            if not chunk:
                break
            handler.wfile.write(_ws_frame(chunk) if ws else chunk)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass          # viewer navigated away
    finally:
        alive[0] = False
        # Only this reader's child -- another connection to the same feed may
        # still be streaming.
        bridge.release(feed, proc)
    return True
