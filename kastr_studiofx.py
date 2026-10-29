"""Windows Studio Effects background blur for KASTR's camera (0.21.94).

Kenton (2026-10-28): "Can KASTR read the Windows Studio effects for the blur and background options? Instead of using the
built in person detection?"

What this does -- and only this:
  * READS, per camera, whether its driver offers KSPROPERTY_CAMERACONTROL_EXTENDED_BACKGROUNDSEGMENTATION (the Windows Studio
    Effects / NPU camera drivers do; most webcams do not) and which of its flags it supports: BLUR (1), MASK (2, a per-frame
    person mask in the frame metadata) and SHALLOWFOCUS (4, the stronger "portrait" blur, only together with BLUR);
  * when the person switches "Use Windows Studio Effects blur" on, SETS the BLUR flag on that camera (keeping whatever MASK bit
    the driver already had) and REMEMBERS the flags it found; switching off -- or KASTR closing, or KASTR dying -- puts the
    remembered flags back.
Normal user rights only: Media Foundation's IMFExtendedCameraController on the camera's own media source (the documented
user-mode route; no driver, no service, no elevation, nothing installed). Windows 11 22H2 or later; elsewhere nothing is
offered.

Crash isolation: the Media Foundation calls go through raw COM vtables (ctypes), and one wrong slot would take the process
down -- so they never run inside KASTR itself. A small helper process (this module, started as `kastr --studiofx-helper`
when frozen, `python kastr_studiofx.py --studiofx-helper` from source) does them and talks line-delimited JSON over its
stdin / stdout. The helper HOLDS the camera's media source open while blur is on (whether the driver keeps a setting after
its source closes is driver-specific), and when its stdin closes -- KASTR quit or crashed -- it restores the flags and exits.

KASTR_STUDIOFX_READONLY=1 (labs, tests) makes every set a refusal: capabilities can be read, nothing is changed."""
import ctypes
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

WINDOWS = os.name == "nt"
HELPER_FLAG = "--studiofx-helper"

# KSCAMERA_EXTENDEDPROP_BACKGROUNDSEGMENTATION_* (ksmedia.h)
FLAG_OFF = 0x0
FLAG_BLUR = 0x1
FLAG_MASK = 0x2
FLAG_SHALLOWFOCUS = 0x4
PROP_BACKGROUNDSEGMENTATION = 41            # KSPROPERTY_CAMERACONTROL_EXTENDED_BACKGROUNDSEGMENTATION
FILTER_SCOPE = 0xFFFFFFFF                   # MF_CAPTURE_ENGINE_MEDIASOURCE / KSCAMERA_EXTENDEDPROP_FILTERSCOPE

LIST_TTL_S = 30.0                           # the server's cached camera list
REPLY_TIMEOUT_S = 20.0                      # a frozen onefile helper unpacks itself first (a few seconds)


def readonly():
    return os.environ.get("KASTR_STUDIOFX_READONLY", "").strip() not in ("", "0", "false", "no")


def cam_id(link):
    """A stable, short id for a camera that is not its raw device path (the path carries a serial on some cameras)."""
    return hashlib.sha1(str(link or "").lower().encode("utf-8")).hexdigest()[:12]


def vid_pid(link):
    """'04f2:b7e0' from a device path like \\\\?\\usb#vid_04f2&pid_b7e0&mi_00#... -- the pair Chrome puts in a camera's label."""
    m = re.search(r"vid_([0-9a-f]{4}).*?pid_([0-9a-f]{4})", str(link or ""), re.I)
    return ("%s:%s" % (m.group(1), m.group(2))).lower() if m else ""


def caps_dict(caps):
    caps = int(caps or 0)
    return {"blur": bool(caps & FLAG_BLUR), "mask": bool(caps & FLAG_MASK), "shallow": bool(caps & FLAG_SHALLOWFOCUS)}


def blur_flags(cur, caps, on, shallow=False):
    """The flags to write: BLUR (+ SHALLOWFOCUS when asked and offered) on or off; every other bit (MASK) kept as found."""
    f = int(cur or 0) & ~(FLAG_BLUR | FLAG_SHALLOWFOCUS)
    if on:
        f |= FLAG_BLUR
        if shallow and (int(caps or 0) & FLAG_SHALLOWFOCUS):
            f |= FLAG_SHALLOWFOCUS
    return f


# ---------------------------------------------------------------------------------------------------------------------
# Media Foundation through ctypes (Windows only; used inside the helper process)
# ---------------------------------------------------------------------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, s):
        s = s.strip("{}")
        a, b, c, d, e = s.split("-")
        tail = bytes.fromhex(d + e)
        return cls(int(a, 16), int(b, 16), int(c, 16), (ctypes.c_ubyte * 8)(*tail))


IID_IMFMediaSource = GUID.parse("279A808D-AEC7-40C8-9C6B-A6B492C78A66")
IID_IMFGetService = GUID.parse("FA993888-4383-415A-A930-DD472A8CF6F7")
IID_IMFExtendedCameraController = GUID.parse("B91EBFEE-CA03-4AF4-8A82-A31752F4A0FC")
GUID_NULL = GUID()
MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE = GUID.parse("c60ac5fe-252a-478f-a0ef-bc8fa5f7cad3")
MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID = GUID.parse("8ac3587a-4ae7-42d8-99e0-0a6013eef90f")
MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME = GUID.parse("60d0e559-52f8-4fa2-bbce-acdb34a8ec01")
MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK = GUID.parse("58f0aad8-22bf-4f8a-bb3d-d2c4978c6e2f")
MF_VERSION = 0x20070
MFSTARTUP_FULL = 0
COINIT_MULTITHREADED = 0
RPC_E_CHANGED_MODE = -2147417850            # 0x80010106: COM already up in another mode -- fine

# vtable slots (mfidl.h / mfobjects.h; IUnknown is 0-2)
V_QI, V_RELEASE = 0, 2
V_ATTR_SETGUID = 24                         # IMFAttributes::SetGUID
V_ATTR_GETALLOCATEDSTRING = 13              # IMFAttributes::GetAllocatedString
V_ACT_ACTIVATEOBJECT = 33                   # IMFActivate (IMFAttributes 3-32, then ActivateObject, ShutdownObject, DetachObject)
V_ACT_SHUTDOWNOBJECT = 34
V_SRC_SHUTDOWN = 12                         # IMFMediaSource (IMFMediaEventGenerator 3-6, GetCharacteristics 7, ..., Shutdown 12)
V_GS_GETSERVICE = 3                         # IMFGetService::GetService
V_CTL_GETCONTROL = 3                        # IMFExtendedCameraController::GetExtendedCameraControl
V_CC_GETCAPABILITIES = 3                    # IMFExtendedCameraControl: GetCapabilities, SetFlags, GetFlags, LockPayload,
V_CC_SETFLAGS = 4                           #   UnlockPayload, CommitSettings
V_CC_GETFLAGS = 5
V_CC_COMMIT = 8

HRESULT = ctypes.c_long
_FN = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


class ComError(OSError):
    def __init__(self, what, hr):
        super().__init__("%s failed (0x%08X)" % (what, hr & 0xFFFFFFFF))
        self.hr = hr & 0xFFFFFFFF


def vcall(ptr, idx, restype, argtypes, *args):
    """Call slot `idx` of the COM object at address `ptr` (a this-call through its vtable)."""
    vtbl = ctypes.cast(ctypes.c_void_p(ptr), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = _FN(restype, ctypes.c_void_p, *argtypes)(vtbl[idx])
    return fn(ctypes.c_void_p(ptr), *args)


def hcall(what, ptr, idx, argtypes, *args):
    hr = vcall(ptr, idx, HRESULT, argtypes, *args)
    if hr < 0:
        raise ComError(what, hr)
    return hr


def release(ptr):
    if ptr:
        try:
            vcall(ptr, V_RELEASE, ctypes.c_ulong, [])
        except Exception:
            pass


class ExtControl:
    """IMFExtendedCameraControl for BACKGROUNDSEGMENTATION, reached from an IMFMediaSource. Owns its references."""

    def __init__(self, source_ptr):
        self.ctl = self.cc = None
        gs = ctypes.c_void_p()
        hcall("QueryInterface(IMFGetService)", source_ptr, V_QI, [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
              ctypes.byref(IID_IMFGetService), ctypes.byref(gs))
        try:
            ctl = ctypes.c_void_p()
            hcall("GetService(IMFExtendedCameraController)", gs.value, V_GS_GETSERVICE,
                  [ctypes.POINTER(GUID), ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
                  ctypes.byref(GUID_NULL), ctypes.byref(IID_IMFExtendedCameraController), ctypes.byref(ctl))
            self.ctl = ctl.value
        finally:
            release(gs.value)
        cc = ctypes.c_void_p()
        try:
            hcall("GetExtendedCameraControl(BACKGROUNDSEGMENTATION)", self.ctl, V_CTL_GETCONTROL,
                  [ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)],
                  FILTER_SCOPE, PROP_BACKGROUNDSEGMENTATION, ctypes.byref(cc))
        except Exception:
            release(self.ctl)
            self.ctl = None
            raise
        self.cc = cc.value

    def caps(self):
        return int(vcall(self.cc, V_CC_GETCAPABILITIES, ctypes.c_ulonglong, []))

    def flags(self):
        return int(vcall(self.cc, V_CC_GETFLAGS, ctypes.c_ulonglong, []))

    def set(self, flags):
        hcall("SetFlags", self.cc, V_CC_SETFLAGS, [ctypes.c_ulonglong], ctypes.c_ulonglong(int(flags)))
        hcall("CommitSettings", self.cc, V_CC_COMMIT, [])

    def close(self):
        release(self.cc)
        release(self.ctl)
        self.cc = self.ctl = None


class MFCamera:
    """One opened camera: its media source (activated, not streaming) + the segmentation control (None: not offered)."""

    def __init__(self, activate, name, link):
        self.name, self.link, self.activate, self.src, self.ctl, self.error = name, link, activate, None, None, ""
        src = ctypes.c_void_p()
        hcall("ActivateObject(IMFMediaSource)", activate, V_ACT_ACTIVATEOBJECT,
              [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(IID_IMFMediaSource), ctypes.byref(src))
        self.src = src.value
        try:
            self.ctl = ExtControl(self.src)
        except ComError as e:
            self.error = str(e)

    def close(self):
        if self.ctl:
            self.ctl.close()
            self.ctl = None
        if self.src:
            try:
                hcall("Shutdown", self.src, V_SRC_SHUTDOWN, [])
            except Exception:
                pass
            release(self.src)
            self.src = None
        if self.activate:
            try:
                hcall("ShutdownObject", self.activate, V_ACT_SHUTDOWNOBJECT, [])
            except Exception:
                pass


class MFBackend:
    """The real thing (helper process only). enumerate() -> [(name, link, activate_ptr)]; the caller releases what it keeps."""

    def __init__(self):
        self.ole32 = ctypes.WinDLL("ole32")
        self.mfplat = ctypes.WinDLL("mfplat")
        self.mf = ctypes.WinDLL("mf")
        hr = self.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        if hr < 0 and hr != RPC_E_CHANGED_MODE:
            raise ComError("CoInitializeEx", hr)
        hr = self.mfplat.MFStartup(MF_VERSION, MFSTARTUP_FULL)
        if hr < 0:
            raise ComError("MFStartup", hr)
        self.ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

    def _string(self, act, key):
        p, n = ctypes.c_wchar_p(), ctypes.c_uint32()
        try:
            hcall("GetAllocatedString", act, V_ATTR_GETALLOCATEDSTRING,
                  [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(ctypes.c_uint32)],
                  ctypes.byref(key), ctypes.byref(p), ctypes.byref(n))
        except ComError:
            return ""
        s = p.value or ""
        self.ole32.CoTaskMemFree(ctypes.cast(p, ctypes.c_void_p))
        return s

    def enumerate(self):
        attrs = ctypes.c_void_p()
        hr = self.mfplat.MFCreateAttributes(ctypes.byref(attrs), 1)
        if hr < 0:
            raise ComError("MFCreateAttributes", hr)
        try:
            hcall("SetGUID", attrs.value, V_ATTR_SETGUID, [ctypes.POINTER(GUID), ctypes.POINTER(GUID)],
                  ctypes.byref(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE), ctypes.byref(MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID))
            arr, count = ctypes.POINTER(ctypes.c_void_p)(), ctypes.c_uint32()
            hr = self.mf.MFEnumDeviceSources(attrs, ctypes.byref(arr), ctypes.byref(count))
            if hr < 0:
                raise ComError("MFEnumDeviceSources", hr)
        finally:
            release(attrs.value)
        out = []
        for i in range(count.value):
            act = arr[i]
            out.append((self._string(act, MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME),
                        self._string(act, MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK), act))
        if arr:
            self.ole32.CoTaskMemFree(ctypes.cast(arr, ctypes.c_void_p))
        return out

    def open(self, name, link, act):
        return MFCamera(act, name, link)

    def drop(self, act):
        release(act)

    def close(self):
        try:
            self.mfplat.MFShutdown()
        except Exception:
            pass


class FakeBackend:
    """In-memory cameras for tests and labs: {"name", "link", "caps", "flags"} dicts; `writes` records every set."""

    class _Ctl:
        def __init__(self, cam, writes):
            self.cam, self.writes = cam, writes

        def caps(self):
            return self.cam["caps"]

        def flags(self):
            return self.cam["flags"]

        def set(self, flags):
            self.writes.append((self.cam["link"], int(flags)))
            self.cam["flags"] = int(flags) & (self.cam["caps"] | FLAG_OFF)

    class _Cam:
        def __init__(self, cam, writes):
            self.name, self.link, self.error = cam["name"], cam["link"], ""
            self.ctl = FakeBackend._Ctl(cam, writes) if cam.get("caps") else None
            if not self.ctl:
                self.error = "GetExtendedCameraControl(BACKGROUNDSEGMENTATION) failed (0x80070490)"
            self.closed = False

        def close(self):
            self.closed = True

    def __init__(self, cams=None):
        self.cams = [dict(c) for c in (cams or [])]
        self.writes, self.opened = [], 0

    def enumerate(self):
        return [(c["name"], c["link"], c) for c in self.cams]

    def open(self, name, link, act):
        self.opened += 1
        return FakeBackend._Cam(act, self.writes)

    def drop(self, act):
        pass

    def close(self):
        pass


# ---------------------------------------------------------------------------------------------------------------------
# The helper: list / set / restore, one JSON command per line
# ---------------------------------------------------------------------------------------------------------------------
class Helper:
    def __init__(self, backend, ro=None):
        self.be = backend
        self.ro = readonly() if ro is None else bool(ro)
        self.held = {}          # id -> {"cam": opened camera, "prev": flags found, "name"}

    def list(self):
        out = []
        for name, link, act in self.be.enumerate():
            cid = cam_id(link)
            row = {"id": cid, "name": name, "vidpid": vid_pid(link), "blur": False, "mask": False, "shallow": False,
                   "flags": 0, "held": cid in self.held}
            try:
                h = self.held.get(cid)
                cam = h["cam"] if h else self.be.open(name, link, act)
                try:
                    if cam.ctl:
                        caps = cam.ctl.caps()
                        row.update(caps_dict(caps))
                        row["flags"] = cam.ctl.flags()
                    else:
                        row["why"] = cam.error or "not offered"
                finally:
                    if not h:
                        cam.close()
            except Exception as e:
                row["why"] = str(e)[:160]
            finally:
                self.be.drop(act)         # a held camera keeps its own (earlier) activation object
            row["on"] = bool(row["flags"] & FLAG_BLUR)
            out.append(row)
        return out

    def set(self, cid, on, shallow=False):
        if self.ro:
            return {"ok": False, "why": "read-only (KASTR_STUDIOFX_READONLY)"}
        h = self.held.get(cid)
        if not on:
            if not h:
                return {"ok": True, "on": False, "changed": False}
            return self._restore(cid)
        if not h:
            why = "no such camera"
            for name, link, act in self.be.enumerate():
                if h or cam_id(link) != cid:
                    self.be.drop(act)
                    continue
                try:
                    cam = self.be.open(name, link, act)
                except Exception as e:
                    why = str(e)[:160]
                    self.be.drop(act)
                    continue
                if not cam.ctl:
                    why = cam.error or "not offered"
                    cam.close()
                    self.be.drop(act)
                    continue
                h = self.held[cid] = {"cam": cam, "prev": cam.ctl.flags(), "name": name, "act": act}
            if not h:
                return {"ok": False, "why": why}
        cam = h["cam"]
        caps = cam.ctl.caps()
        if not caps & FLAG_BLUR:
            self._restore(cid)
            return {"ok": False, "why": "this camera does not offer blur"}
        want = blur_flags(cam.ctl.flags(), caps, True, shallow)
        try:
            cam.ctl.set(want)
        except Exception as e:
            self._restore(cid)
            return {"ok": False, "why": str(e)[:160]}
        now = cam.ctl.flags()
        return {"ok": bool(now & FLAG_BLUR), "on": bool(now & FLAG_BLUR), "flags": now, "changed": True,
                **({} if now & FLAG_BLUR else {"why": "the driver did not keep the blur flag"})}

    def _restore(self, cid):
        h = self.held.pop(cid, None)
        if not h:
            return {"ok": True, "on": False, "changed": False}
        res = {"ok": True, "on": False, "changed": True}
        try:
            h["cam"].ctl.set(h["prev"])
            res["on"] = bool(h["cam"].ctl.flags() & FLAG_BLUR)
        except Exception as e:
            res = {"ok": False, "why": "could not put the camera back: " + str(e)[:160]}
        finally:
            try:
                h["cam"].close()
            finally:
                self.be.drop(h.get("act"))
        return res

    def restore_all(self):
        for cid in list(self.held):
            self._restore(cid)

    def handle(self, cmd):
        op = (cmd or {}).get("op")
        if op == "list":
            return {"ok": True, "cams": self.list(), "readonly": self.ro}
        if op == "set":
            return self.set(str(cmd.get("id") or ""), bool(cmd.get("on")), bool(cmd.get("shallow")))
        if op == "restore":
            self.restore_all()
            return {"ok": True}
        return {"ok": False, "why": "unknown op"}


def _std_streams():
    """The helper's stdin / stdout as binary files -- from the OS handles, because a frozen --noconsole KASTR has no
    sys.stdin / sys.stdout of its own even when the parent hands it pipes."""
    if WINDOWS:
        import msvcrt
        k32 = ctypes.WinDLL("kernel32")
        k32.GetStdHandle.restype = ctypes.c_void_p
        hin, hout = k32.GetStdHandle(-10), k32.GetStdHandle(-11)
        if hin in (None, 0, ctypes.c_void_p(-1).value) or hout in (None, 0, ctypes.c_void_p(-1).value):
            return None, None
        return (os.fdopen(msvcrt.open_osfhandle(hin, os.O_RDONLY), "rb"),
                os.fdopen(msvcrt.open_osfhandle(hout, 0), "wb"))
    return sys.stdin.buffer, sys.stdout.buffer


def helper_main(backend=None, fin=None, fout=None):
    """The helper process: answer one JSON line per command; at EOF (KASTR closed the pipe, quit or crashed) put every
    camera back and exit."""
    if fin is None or fout is None:
        fin, fout = _std_streams()
        if fin is None:
            return 2
    try:
        be = backend or MFBackend()
    except Exception as e:
        fout.write((json.dumps({"ok": False, "why": "Media Foundation: " + str(e)[:160]}) + "\n").encode("utf-8"))
        fout.flush()
        return 1
    h = Helper(be)
    fout.write((json.dumps({"ok": True, "hello": 1, "readonly": h.ro}) + "\n").encode("utf-8"))
    fout.flush()
    try:
        for raw in fin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                cmd = json.loads(raw.decode("utf-8"))
            except ValueError:
                cmd = {}
            if cmd.get("op") == "quit":
                break
            try:
                res = h.handle(cmd)
            except Exception as e:
                res = {"ok": False, "why": str(e)[:200]}
            fout.write((json.dumps(res) + "\n").encode("utf-8"))
            fout.flush()
    finally:
        h.restore_all()
        be.close()
    return 0


# ---------------------------------------------------------------------------------------------------------------------
# KASTR's side: the helper process, started on demand, one request at a time
# ---------------------------------------------------------------------------------------------------------------------
def helper_argv():
    if getattr(sys, "frozen", False):
        return [sys.executable, HELPER_FLAG]
    return [sys.executable, os.path.abspath(__file__), HELPER_FLAG]


class StudioFx:
    """The server's handle on Studio Effects. `local` (a Helper) runs in-process -- tests only; otherwise a helper process.
    A helper that dies twice is not started again this run (a broken driver must not cost a crash loop)."""

    def __init__(self, local=None, argv=None, log=None):
        self.local, self.argv, self.log = local, argv, log or (lambda m: None)
        self.lock = threading.Lock()
        self.proc, self.q, self.deaths = None, None, 0
        self.cache, self.cache_at, self.held = None, 0.0, set()
        self.last_error = ""

    @staticmethod
    def supported():
        if not WINDOWS:
            return False
        try:
            return sys.getwindowsversion().build >= 22621     # Windows 11 22H2 (the DDI's minimum)
        except Exception:
            return False

    def _start(self):
        if self.proc and self.proc.poll() is None:
            return True
        if self.deaths >= 2:
            return False
        env = dict(os.environ)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.proc = subprocess.Popen(self.argv or helper_argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, env=env, creationflags=flags)
        except OSError as e:
            self.last_error = "could not start the helper: %s" % e
            self.deaths += 1
            return False
        self.q = queue.Queue()
        proc, q = self.proc, self.q

        def pump():
            try:
                for line in proc.stdout:
                    q.put(line)
            except Exception:
                pass
            try:
                proc.stdout.close()
            except Exception:
                pass
            q.put(None)
        threading.Thread(target=pump, name="studiofx-pump", daemon=True).start()
        hello = self._read(REPLY_TIMEOUT_S)
        if not hello or not hello.get("ok"):
            self.last_error = (hello or {}).get("why") or "the helper did not start"
            self._stop(dead=True)
            return False
        return True

    def _read(self, timeout):
        try:
            line = self.q.get(timeout=timeout)
        except queue.Empty:
            return None
        if line is None:
            return None
        try:
            return json.loads(line.decode("utf-8"))
        except ValueError:
            return None

    def _stop(self, dead=False):
        p, self.proc = self.proc, None
        if dead:
            self.deaths += 1
            self.held.clear()
        if not p:
            return
        try:
            p.stdin.close()               # EOF: the helper restores every camera it holds, then exits
        except Exception:
            pass
        try:
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    def _ask(self, cmd):
        if self.local is not None:
            return self.local.handle(cmd)
        if not self._start():
            return {"ok": False, "why": self.last_error or "unavailable"}
        try:
            self.proc.stdin.write((json.dumps(cmd) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except Exception:
            self._stop(dead=True)
            return {"ok": False, "why": "the helper stopped"}
        res = self._read(REPLY_TIMEOUT_S)
        if res is None:
            self.last_error = "the helper stopped answering"
            self.log("studiofx: " + self.last_error)
            self._stop(dead=True)
            return {"ok": False, "why": self.last_error}
        return res

    def cameras(self, fresh=False):
        """[{id, name, vidpid, blur, mask, shallow, flags, on, held}] -- cached LIST_TTL_S; [] where not supported."""
        with self.lock:
            if self.local is None and not self.supported():
                return {"ok": True, "supported": False, "cams": []}
            if not fresh and self.cache is not None and time.time() - self.cache_at < LIST_TTL_S:
                return self.cache
            res = self._ask({"op": "list"})
            if res.get("ok"):
                res = {"ok": True, "supported": True, "cams": res.get("cams") or [], "readonly": bool(res.get("readonly"))}
                self.cache, self.cache_at = res, time.time()
            else:
                res = {"ok": False, "supported": True, "cams": [], "why": res.get("why")}
            if self.local is None and not self.held:
                self._stop()              # nothing held: no idle helper hanging around
            return res

    def set(self, cid, on, shallow=False):
        with self.lock:
            if self.local is None and not self.supported():
                return {"ok": False, "why": "needs Windows 11 22H2 or later"}
            res = self._ask({"op": "set", "id": cid, "on": bool(on), "shallow": bool(shallow)})
            if res.get("ok") and on:
                self.held.add(cid)
            elif not on:
                self.held.discard(cid)
            self.cache = None
            if self.local is None and not self.held:
                self._stop()
            return res

    def close(self):
        with self.lock:
            if self.local is not None:
                self.local.restore_all()
                return
            self.held.clear()
            self._stop()


if __name__ == "__main__" and HELPER_FLAG in sys.argv[1:]:
    sys.exit(helper_main())
