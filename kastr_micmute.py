"""0.21.41: the microphones' own mute, as Windows sees it (Kenton: "auto detect when a mic has unmuted and unmute in KASTR?
Certain microphones announce this to windows and it works on Teams").

A headset or USB microphone with a mute switch (and a laptop's mic-mute key) usually flips the Windows capture endpoint's
mute (IAudioEndpointVolume). This module only READS it -- never sets it -- for every active capture endpoint, by name, plus
which one is the default communications microphone. The page asks GET /api/mic/hwmute and follows a change on the mic it
uses. Standard library only (ctypes COM); on other platforms `snapshot()` reports `supported: false`.
"""
import ctypes
import sys
import threading
import time

WINDOWS = sys.platform == "win32"

_lock = threading.Lock()
_state = {"supported": WINDOWS, "endpoints": [], "at": 0.0, "error": None}
_wanted_at = [0.0]
_thread = [None]
POLL_S = 0.5
IDLE_STOP_S = 30.0   # the poller stops when no page asked for this long


if WINDOWS:
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        def __init__(self, text):
            super().__init__()
            import uuid
            u = uuid.UUID(text)
            self.Data1, self.Data2, self.Data3 = u.fields[0], u.fields[1], u.fields[2]
            for i, b in enumerate(u.bytes[8:]):
                self.Data4[i] = b

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.USHORT), ("r2", wintypes.USHORT), ("r3", wintypes.USHORT),
                    ("val", ctypes.c_void_p), ("pad", ctypes.c_void_p)]

    CLSID_MMDeviceEnumerator = GUID("BCDE0395-E52F-467C-8E3D-C4579291692E")
    IID_IMMDeviceEnumerator = GUID("A95664D2-9614-4F35-A746-DE8DB63617E6")
    IID_IAudioEndpointVolume = GUID("5CDF2C82-841E-4546-9722-0CF74078229A")
    PKEY_Device_FriendlyName = PROPERTYKEY(GUID("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)
    CLSCTX_ALL = 23
    E_CAPTURE, ROLE_COMMUNICATIONS, DEVICE_STATE_ACTIVE, STGM_READ, VT_LPWSTR = 1, 2, 1, 0, 31

    _ole32 = ctypes.OleDLL("ole32")

    def _call(obj, index, restype, argtypes, *args):
        """Call vtable slot `index` of COM object pointer `obj`."""
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
        return fn(obj, *args)

    def _release(obj):
        if obj:
            try:
                _call(obj, 2, wintypes.ULONG, [])
            except Exception:
                pass

    def _endpoint_id(dev):
        p = ctypes.c_wchar_p()
        if _call(dev, 5, ctypes.HRESULT, [ctypes.POINTER(ctypes.c_wchar_p)], ctypes.byref(p)) != 0 and not p.value:
            return ""
        val = p.value or ""
        try:
            _ole32.CoTaskMemFree(p)
        except Exception:
            pass
        return val

    def _friendly_name(dev):
        store = ctypes.c_void_p()
        _call(dev, 4, ctypes.HRESULT, [wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)], STGM_READ, ctypes.byref(store))
        try:
            pv = PROPVARIANT()
            _call(store, 5, ctypes.HRESULT, [ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)],
                  ctypes.byref(PKEY_Device_FriendlyName), ctypes.byref(pv))
            name = ctypes.wstring_at(pv.val) if pv.vt == VT_LPWSTR and pv.val else ""
            try:
                ctypes.oledll.ole32.PropVariantClear(ctypes.byref(pv))
            except Exception:
                pass
            return name
        finally:
            _release(store)

    def _muted(dev):
        vol = ctypes.c_void_p()
        _call(dev, 3, ctypes.HRESULT, [ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
              ctypes.byref(IID_IAudioEndpointVolume), CLSCTX_ALL, None, ctypes.byref(vol))
        try:
            m = wintypes.BOOL()
            _call(vol, 15, ctypes.HRESULT, [ctypes.POINTER(wintypes.BOOL)], ctypes.byref(m))   # IAudioEndpointVolume::GetMute
            return bool(m.value)
        finally:
            _release(vol)

    def read_endpoints():
        """[{name, id, muted, default}] for every active capture endpoint. Call on a COM-initialised thread."""
        enum = ctypes.c_void_p()
        _ole32.CoCreateInstance(ctypes.byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                                ctypes.byref(IID_IMMDeviceEnumerator), ctypes.byref(enum))
        out = []
        try:
            default_id = ""
            d = ctypes.c_void_p()
            try:
                _call(enum, 4, ctypes.HRESULT, [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)],
                      E_CAPTURE, ROLE_COMMUNICATIONS, ctypes.byref(d))
                default_id = _endpoint_id(d)
            except OSError:
                pass   # no capture device at all
            finally:
                _release(d)
            coll = ctypes.c_void_p()
            _call(enum, 3, ctypes.HRESULT, [ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)],
                  E_CAPTURE, DEVICE_STATE_ACTIVE, ctypes.byref(coll))
            try:
                n = wintypes.UINT()
                _call(coll, 3, ctypes.HRESULT, [ctypes.POINTER(wintypes.UINT)], ctypes.byref(n))
                for i in range(n.value):
                    dev = ctypes.c_void_p()
                    _call(coll, 4, ctypes.HRESULT, [wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)], i, ctypes.byref(dev))
                    try:
                        eid = _endpoint_id(dev)
                        out.append({"name": _friendly_name(dev), "id": eid, "muted": _muted(dev), "default": eid == default_id})
                    except OSError:
                        pass
                    finally:
                        _release(dev)
            finally:
                _release(coll)
        finally:
            _release(enum)
        return out


def _poller():
    if WINDOWS:
        try:
            _ole32.CoInitializeEx(None, 0)   # COINIT_MULTITHREADED
        except OSError:
            pass
    try:
        while time.monotonic() - _wanted_at[0] < IDLE_STOP_S:
            try:
                eps = read_endpoints()
                with _lock:
                    _state.update(endpoints=eps, at=time.time(), error=None)
            except Exception as e:   # never take the server down over a sound driver
                with _lock:
                    _state.update(error=str(e)[:200], at=time.time())
            time.sleep(POLL_S)
    finally:
        _thread[0] = None
        if WINDOWS:
            try:
                _ole32.CoUninitialize()
            except Exception:
                pass


def snapshot():
    """What the page reads: {supported, endpoints:[{name, muted, default}], at, error}. Starts the poller on demand."""
    if not WINDOWS:
        return {"supported": False, "endpoints": [], "at": 0, "error": None}
    _wanted_at[0] = time.monotonic()
    if _thread[0] is None:
        t = threading.Thread(target=_poller, name="kastr-micmute", daemon=True)
        _thread[0] = t
        t.start()
    with _lock:
        return {"supported": True, "at": _state["at"], "error": _state["error"],
                "endpoints": [{"name": e["name"], "muted": e["muted"], "default": e["default"]} for e in _state["endpoints"]]}
