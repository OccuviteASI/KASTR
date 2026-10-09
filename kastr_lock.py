"""0.21.41: is this computer's session locked? (Kenton: "Sharing should stop when a computer is locked, and shouldn't
reconnect automatically.")

Windows: WTSQuerySessionInformation(WTSSessionInfoEx) -> SessionFlags (WTS_SESSIONSTATE_LOCK = 0 on Windows 10/11).
Linux: `loginctl show-session <id> -p LockedHint` (systemd-logind; the desktop sets it when the screen locks).
Anything else, or a failure: None (unknown -- the page then never stops a share on our say-so).
Standard library only.
"""
import ctypes
import os
import subprocess
import sys
import time

_cache = {"at": 0.0, "locked": None}
CACHE_S = 1.0


def _windows_locked():
    from ctypes import wintypes
    wts = ctypes.WinDLL("wtsapi32")
    WTS_CURRENT_SERVER_HANDLE = None
    WTS_CURRENT_SESSION = 0xFFFFFFFF
    WTSSessionInfoEx = 25

    class WTSINFOEX_LEVEL1(ctypes.Structure):
        _fields_ = [("SessionId", wintypes.ULONG), ("SessionState", ctypes.c_int), ("SessionFlags", wintypes.LONG)]   # the rest is not read

    class WTSINFOEX(ctypes.Structure):
        # the union holds LARGE_INTEGERs, so it is 8-byte aligned: Data starts at offset 8, not 4
        _fields_ = [("Level", wintypes.DWORD), ("pad", wintypes.DWORD), ("Data", WTSINFOEX_LEVEL1)]

    buf = ctypes.c_void_p()
    size = wintypes.DWORD()
    fn = wts.WTSQuerySessionInformationW
    fn.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    fn.restype = wintypes.BOOL
    if not fn(WTS_CURRENT_SERVER_HANDLE, WTS_CURRENT_SESSION, WTSSessionInfoEx, ctypes.byref(buf), ctypes.byref(size)):
        return None
    try:
        info = ctypes.cast(buf, ctypes.POINTER(WTSINFOEX)).contents
        if info.Level != 1:
            return None
        flags = info.Data.SessionFlags
        if flags == 0:      # WTS_SESSIONSTATE_LOCK
            return True
        if flags == 1:      # WTS_SESSIONSTATE_UNLOCK
            return False
        return None         # WTS_SESSIONSTATE_UNKNOWN
    finally:
        wts.WTSFreeMemory(buf)


def _linux_locked():
    sid = os.environ.get("XDG_SESSION_ID") or ""
    args = ["loginctl", "show-session"] + ([sid] if sid else []) + ["-p", "LockedHint", "--value"]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    v = (r.stdout or "").strip().lower()
    return True if v == "yes" else False if v == "no" else None


def locked():
    """True / False, or None when this platform or session cannot tell."""
    now = time.monotonic()
    if now - _cache["at"] < CACHE_S:
        return _cache["locked"]
    try:
        if sys.platform == "win32":
            v = _windows_locked()
        elif sys.platform.startswith("linux"):
            v = _linux_locked()
        else:
            v = None
    except Exception:
        v = None
    _cache.update(at=now, locked=v)
    return v
