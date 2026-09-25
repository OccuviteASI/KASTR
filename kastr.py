#!/usr/bin/env python3
"""KASTR -- desktop launcher.

Serves the bundled pages on loopback with the COOP/COEP isolation they need,
then opens them in a chromeless Chromium window so it behaves like a native
app. No Electron: Chrome/Edge is already installed on these machines, and
`--app=` gives a real app window without shipping a second browser.

Closing the window stops the server and exits.

Also supervises the bundled helpers: ffmpeg for RTSP ingest, and moq-relay so
this machine can host a relay itself (see the Relay page).

Config, in precedence order:
  1. command line     KASTR.exe --relay http://10.0.0.5:4443
  2. kastr.ini         next to the .exe, [streamer] relay = ...
  3. built-in default kastr_serve.DEFAULT_RELAY
"""
import argparse
import configparser
import hashlib
import json
import re
import signal
import os
import shutil
import subprocess
import sys
import threading
import stat
import time
import urllib.request

import kastr_serve
import kastr_rtsp   # 0.18.0: hooks

APP_NAME = "KASTR"  # Kenton's ASI Streaming Tool with Relay
FROZEN = getattr(sys, "frozen", False)


def site_root():
    """Where the web files live: unpacked temp dir when frozen, else here."""
    if FROZEN:
        return os.path.join(sys._MEIPASS, "site")
    return os.path.dirname(os.path.abspath(__file__))


def app_dir():
    """Folder holding the .exe -- where a sysadmin drops kastr.ini."""
    return os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))


def config_paths():
    """Where kastr.ini may live, in priority order.

    Next to the executable is the documented spot, but a shortcut can launch
    the app with any working directory, and people reasonably expect a config
    file sitting beside the shortcut target to win. Checking both costs
    nothing and avoids a silently-ignored config file.
    """
    seen, out = set(), []
    for d in (app_dir(), os.getcwd()):
        p = os.path.join(d, "kastr.ini")
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


def state_base():
    """Per-user application-data root, following each platform's convention."""
    if WINDOWS:
        return os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    if MACOS:
        return os.path.expanduser("~/Library/Application Support")
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def state_dir():
    # 0.13.1: KASTR_STATE_DIR (Docker: /data/state) beats the platform default
    override = (os.environ.get("KASTR_STATE_DIR") or "").strip()
    if override:
        d = os.path.abspath(override)
    else:
        d = os.path.join(state_base(), "ASI", "KASTR")
    os.makedirs(d, exist_ok=True)
    return d


def _has_profile(path):
    """A Chrome profile directory that has actually been used before."""
    return os.path.exists(os.path.join(path, "Default", "Preferences"))


# Every name this app has shipped under, newest first. The browser profile
# holds the camera/microphone permission the operator already granted, so a
# rename must not orphan it. Renaming the directory is unreliable (Windows
# refuses while any handle is open, and a swallowed failure silently costs the
# permission), so instead keep using whichever generation actually has state.
LEGACY_STATE_NAMES = ("KAST", "MoQStreamer")


def browser_is_snap(path):
    """Snap-confined browsers cannot read dot-directories in $HOME, so a
    profile under ~/.local/share is silently unusable -- Chromium falls
    back to an ephemeral profile and localStorage (the operator name,
    rooms, sizes) dies with every run. Seen on Ubuntu, whose default
    chromium is a snap and whose /usr/bin/chromium is a snap wrapper."""
    if WINDOWS or MACOS or not path:
        return False
    try:
        real = os.path.realpath(path)
    except OSError:
        real = path
    if "/snap/" in path or "/snap/" in real:
        return True
    base = os.path.basename(path)
    return base.startswith("chromium") and os.path.exists("/snap/bin/chromium")


def legacy_profile_dir():
    """The profile a system browser used (any generation), or None."""
    current = os.path.join(state_dir(), "browser-profile")
    if _has_profile(current):
        return current
    for name in LEGACY_STATE_NAMES:
        legacy = os.path.join(state_base(), "ASI", name, "browser-profile")
        if _has_profile(legacy):
            return legacy
    return None


def profile_dir(browser=None):
    """Which browser profile to launch against."""
    if browser_is_snap(browser):
        d = os.path.expanduser("~/snap/chromium/common/kastr-profile")
        os.makedirs(d, exist_ok=True)
        return d
    # 0.9.0: the bundled browser gets its OWN profile. A pinned engine will be
    # older than an auto-updated system Chrome sooner or later, and Chrome
    # refuses a profile written by a newer version -- so never share one. The
    # page's settings (localStorage) are carried over once, nothing else.
    try:
        import kastr_browser
        if browser and kastr_browser.is_bundled(browser, app_dir()):
            d = os.path.join(state_dir(), "browser-profile-bundled")
            if not _has_profile(d):
                old = legacy_profile_dir()
                if old:
                    kastr_browser.migrate_profile(old, d, log=print)
            os.makedirs(d, exist_ok=True)
            return d
    except Exception:
        pass
    current = os.path.join(state_dir(), "browser-profile")
    if _has_profile(current):
        return current
    base = state_base()
    for name in LEGACY_STATE_NAMES:
        legacy = os.path.join(base, "ASI", name, "browser-profile")
        if _has_profile(legacy):
            return legacy
    return current


# Set when anything asks KASTR to stop: a signal, a dialog being dismissed,
# or the window going away. Every wait in this file is bounded by it.
STOP = threading.Event()


def alert_async(msg, seconds=0.0):
    """alert() on a daemon thread, waited on for at most `seconds`.

    alert() itself blocks until someone clicks OK, which is fine when that is
    the whole point and fatal on an exit path. The thread is a daemon, so the
    dialog dies with the process instead of holding it open.
    """
    shown = [None]

    def run():
        shown[0] = alert(msg)
    t = threading.Thread(target=run, daemon=True)
    t.shown = shown          # 0.9.3: False when no dialog helper exists on this box
    t.start()
    if seconds:
        t.join(seconds)
    return t


def alert_until_stop(msg):
    """Show a notice and serve until either it is dismissed or the page stops.

    Replaces `alert(...); return 0`, which made a modal dialog the only way to
    end the process. The dialog is still the obvious way out, but the served
    page going away now works too, so a forgotten dialog cannot strand KASTR.
    """
    t = alert_async(msg)
    while t.is_alive() and not STOP.wait(1.0):
        pass
    if getattr(t, "shown", [True])[0] is False:
        # 0.9.3: nothing was shown (no zenity/kdialog/xmessage, or the display
        # is unusable), so nothing can be dismissed. Keep serving until Ctrl+C,
        # SIGTERM or the page's own heartbeat ends things.
        note("no dialog could be shown; serving until stopped")
        while not STOP.wait(1.0):
            pass


def alert(msg):
    """Show a message box. The app is windowed, so stderr goes nowhere."""
    try:
        if WINDOWS:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x10)
            return True
        if MACOS:
            # osascript is always present; escape quotes for AppleScript.
            body = msg.replace(chr(34), chr(92) + chr(34))
            subprocess.run(
                ["osascript", "-e",
                 'display dialog "%s" with title "%s" buttons {"OK"} '
                 'with icon caution' % (body, APP_NAME)],
                check=False, timeout=120)
            return True
        # Linux: try the common dialog helpers, then give up to stderr.
        for cmd in (["zenity", "--error", "--title", APP_NAME, "--text", msg],
                    ["kdialog", "--title", APP_NAME, "--error", msg],
                    ["xmessage", "-center", msg]):
            try:
                subprocess.run(cmd, check=False, timeout=120)
                return True
            except (OSError, subprocess.SubprocessError):
                continue
    except Exception:
        pass
    # A windowed build has no stderr at all; there is nowhere left to say it.
    if sys.stderr is not None:
        try:
            sys.stderr.write(msg + chr(10))
        except Exception:
            pass
    return False


def read_ini():
    for path in config_paths():
        if not os.path.exists(path):
            continue
        cp = configparser.ConfigParser()
        try:
            # utf-8-sig so a BOM-prefixed file (what most Windows editors and
            # PowerShell's Set-Content produce) still parses.
            cp.read(path, encoding="utf-8-sig")
        except Exception:
            continue
        if cp.has_section("streamer"):
            return dict(cp["streamer"]), path
    return {}, None


BROWSER_PREF = "bundled"   # kastr.ini `browser = bundled|system|<path>` (0.9.0)


def bundled_browser():
    """The Chromium KASTR ships in browser/ next to the binary (0.9.0), unless
    kastr.ini says otherwise. A path in the ini names a specific browser."""
    pref = (BROWSER_PREF or "bundled").strip()
    if pref.lower() == "system":
        return None
    if pref.lower() not in ("bundled", ""):
        return pref if os.path.exists(pref) else None
    try:
        import kastr_browser
        return kastr_browser.prepare(app_dir(), log=note)   # finds it AND fixes the sandbox ACL
    except Exception:
        return None


def find_browser(system_only=False):
    """Locate a Chromium browser. Returns a path or None.

    Chromium specifically, not just any browser: the app window depends on
    --app= and --user-data-dir, and the WebCodecs/WebTransport stack the pages
    need is only complete in Chromium. Firefox and Safari are not candidates.

    0.9.0: the bundled browser wins; the system ones below are the fallback.
    0.9.3: system_only=True skips the bundled one (launch() falls back to it).
    """
    if not system_only:
        b = bundled_browser()
        if b:
            return b
    if WINDOWS:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
        ]
    elif MACOS:
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser(
                "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
            "/usr/bin/microsoft-edge", "/usr/bin/brave-browser",
            # chromium last: on Ubuntu these are snap-confined (the
            # profile then lives under ~/snap/chromium/common).
            "/usr/bin/chromium", "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]
    found = next((p for p in candidates if os.path.exists(p)), None)
    if found:
        return found
    # Anything on PATH, for distros and installs that put it elsewhere.
    for name in ("google-chrome", "google-chrome-stable", "microsoft-edge",
                 "brave-browser", "chromium", "chromium-browser"):
        which = shutil.which(name)
        if which:
            return which
    return None


def window_file():
    """Where the window geometry the page reports is kept."""
    return os.path.join(state_dir(), "window.json")


def window_args():
    """Chrome flags to put the window back where it was.

    The browser does not restore an --app window's bounds from the profile,
    which v0.5.18 assumed it would -- so every launch came up at some default
    size. The page reports its own geometry instead and this hands it back.

    Maximized is restored as a state, not as a rectangle: the bounds of a
    maximized window restored literally give you an almost-maximized one that
    no longer snaps or follows a monitor change.
    """
    try:
        with open(window_file(), encoding="utf-8") as f:
            geom = json.load(f)
    except (OSError, ValueError):
        # Never opened before: start maximized, which is the useful default
        # for a wall of video feeds.
        return ["--start-maximized"]

    if geom.get("maximized"):
        return ["--start-maximized"]

    try:
        x, y = int(geom["x"]), int(geom["y"])
        w, h = int(geom["w"]), int(geom["h"])
    except (KeyError, TypeError, ValueError):
        return ["--start-maximized"]

    # A window recorded on a monitor that is no longer there would open off
    # screen, so refuse anything implausible rather than lose the window.
    if w < 320 or h < 240 or w > 20000 or h > 20000:
        return ["--start-maximized"]

    return [
        "--window-position=%d,%d" % (x, y),
        "--window-size=%d,%d" % (w, h),
    ]

LAUNCH_LOG_MAX = 256 * 1024


def note(msg):
    """0.8.13: the launcher's own log -- state_dir/launch.log (rotates once at
    256 KB). A --noconsole build has no stdout, so every startup fact that was
    print()ed vanished; now print() lands here too (see the shim below)."""
    try:
        p = os.path.join(state_dir(), "launch.log")
        try:
            if os.path.getsize(p) > LAUNCH_LOG_MAX:
                os.replace(p, p + ".1")
        except OSError:
            pass
        with open(p, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg).rstrip() + chr(10))
    except Exception:
        pass


_print = print


def print(*args, **kwargs):   # noqa: A001 -- deliberate: every launcher print is logged
    try:
        note(" ".join(str(a) for a in args))
    except Exception:
        pass
    try:
        _print(*args, **kwargs)
    except Exception:
        pass


def update_note(status, detail=""):
    note("update-check: %s -- %s" % (status, detail))
    _update_note(status, detail)
    return status        # 0.15.0: check_update returns it (main decides whether to mirror)


def _update_note(status, detail=""):
    """0.8.3: the updater used to fail in perfect silence -- probe timeouts
    were bare returns and the few prints go nowhere in a --noconsole build
    (the field report was a tester's 0.8.1 that "just didn't update").
    Every outcome now lands in state_dir; /api/instance surfaces it and the
    Relay page shows it, so an unreachable version authority is VISIBLE."""
    try:
        with open(os.path.join(state_dir(), "update-check.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"status": status, "detail": detail,
                       "version": kastr_serve.read_version(),
                       "at": int(time.time())}, f)
    except Exception:
        pass


def _probe_authority(base):
    """The KASTR instance at `base`, or None (writes the note itself)."""
    import urllib.request
    try:
        with urllib.request.urlopen(base + "/api/instance", timeout=2) as r:
            inst = json.load(r)
    except Exception:
        # THE field failure: the relay host's KASTR web port is unreachable
        # (KASTR not running there, host not 0.0.0.0, or the "KASTR web"
        # firewall rule missing) -- clients cannot match versions.
        update_note("unreachable", base)
        return None
    if inst.get("app") != "KASTR":
        update_note("skipped", "no KASTR answering at " + base)
        return None
    return inst


def update_from(base, theirs, mine, relaunch_delay_ms=800, before_exit=None):
    """Download, verify, swap and relaunch as the authority's version.

    Returns only on failure (which launches/keeps the current version).
    `before_exit` is the runtime path (0.8.6): tear the live server down --
    children, browser -- so the relaunch finds its ports free."""
    import urllib.request
    try:
        with urllib.request.urlopen(base + "/api/update/manifest", timeout=5) as r:
            man = json.load(r)
    except Exception:
        update_note("failed", "manifest fetch failed from " + base)
        return "failed"
    plat = ("win32" if WINDOWS else "darwin" if MACOS else "linux")
    info = (man.get("platforms") or {}).get(plat)
    if not info:
        print(f"{APP_NAME}: relay host runs v{theirs} but has no {plat} binary to offer; "
              f"staying on v{mine}", flush=True)
        update_note("no-binary", f"relay host runs v{theirs} but offers no "
                    f"{plat} binary; staying on v{mine}")
        return "no-binary"
    target = sys.executable
    tmp = target + ".new"
    print(f"{APP_NAME}: updating v{mine} -> v{theirs} from {base} ...", flush=True)
    update_note("updating", f"v{mine} -> v{theirs} from {base}")
    aside = None
    try:
        import hashlib
        h = hashlib.sha256()
        # 0.8.13: 60 s per socket operation (a stalled download raises instead
        # of hanging for 10 minutes per read), and progress in the note so
        # /api/instance and the Relay page can show "updating 42%".
        total = int(info.get("size") or 0)
        got = last_mark = 0
        with urllib.request.urlopen(base + "/api/update/binary?platform=" + plat,
                                    timeout=60) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                f.write(chunk)
                got += len(chunk)
                if total and got - last_mark >= (8 << 20):
                    last_mark = got
                    update_note("updating", f"v{mine} -> v{theirs} from {base} ({got * 100 // total}%)")
        if h.hexdigest() != info.get("sha256"):
            raise RuntimeError("checksum mismatch")
        if os.path.getsize(tmp) != int(info.get("size") or 0):
            raise RuntimeError("size mismatch")
        # The running image keeps working from the renamed file (both
        # platforms); the .old- prefix is what build.py already sweeps.
        aside = os.path.join(os.path.dirname(target),
                             "KASTR.old-%d%s" % (int(time.time()),
                                                 ".exe" if WINDOWS else ""))
        os.rename(target, aside)
        # 0.8.7: the placement must never leave the folder without KASTR.
        # Antivirus / OneDrive hold a fresh file for a moment (field report:
        # only a KASTR.old-<ts>.exe remained) -- retry, then ROLL BACK.
        placed = False
        for _attempt in range(6):
            try:
                os.replace(tmp, target)
                placed = True
                break
            except OSError:
                time.sleep(0.4)
        if not placed:
            os.rename(aside, target)
            aside = None
            raise RuntimeError("could not place the new binary (file locked?) -- kept the current version")
        if not WINDOWS:
            try:
                os.chmod(target, 0o755)
            except OSError:
                pass
            if MACOS:
                # 0.13.1: Apple Silicon refuses an unsigned Mach-O -- an ad-hoc
                # signature is enough for a self-swapped binary. Best effort.
                try:
                    cs = subprocess.run(["codesign", "--force", "--sign", "-", target],
                                        capture_output=True, timeout=60)
                    if cs.returncode != 0:
                        note("update: codesign failed (%d): %s" % (
                            cs.returncode, (cs.stderr or b"").decode("utf-8", "replace").strip()[-200:]))
                except Exception as e:
                    note("update: codesign unavailable: %s" % e)
        print(f"{APP_NAME}: relaunching as v{theirs}", flush=True)
    except Exception as e:
        # 0.8.7: whatever failed, KASTR.exe must exist afterwards.
        try:
            if aside and os.path.exists(aside) and not os.path.exists(target):
                os.rename(aside, target)
        except OSError:
            pass
        try:
            os.remove(tmp)
        except OSError:
            pass
        print(f"{APP_NAME}: update failed ({e}); launching v{mine} as-is", flush=True)
        update_note("failed", f"{e} -- launched v{mine} as-is")
        return "failed"
    # 0.16.0: the swap succeeded -- the new binary is in place. The relaunch is
    # judged on its own: a spawn failure used to fall into the except above and
    # read "update failed ... launched as-is" while the new exe sat on disk.
    try:
        ok = relaunch_self(relaunch_delay_ms, before_exit, reason="update")
    except Exception as e:
        ok = False
        note("relaunch: spawn failed -- %s" % e)
    if ok is False:
        update_note("relaunch-failed", f"v{theirs} is installed but KASTR could not restart "
                    f"itself -- start KASTR again to run it; this window still runs v{mine}")
        try:
            alert_async(f"KASTR downloaded v{theirs} but could not restart itself.\n\n"
                        f"Close KASTR and start it again to run v{theirs}.\n"
                        f"Until then this window keeps running v{mine}.")
        except Exception:
            pass
        return "relaunch-failed"
    return "updating"


_EXIT_OVERRIDE = [None]    # 0.13.1: teardown's exit code when a relaunch must end with 75 (container)
RELAUNCH_PORT_HINT = [0]   # 0.16.0: the port a launch-time relaunch will bind (HTTP_PORT is not set yet then)


def _shell_execute_alive(target, args, wait_s):
    """0.16.0: launch `target args` through the Windows shell (ShellExecuteExW, the
    path every double-click uses -- no PowerShell, outside any ambient job) and
    report whether the process is still alive after `wait_s`. None = could not
    even be started."""
    import ctypes
    from ctypes import wintypes
    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NO_CONSOLE = 0x00008000
    SEE_MASK_FLAG_NO_UI = 0x00000400   # 0.18.0: never the shell's own error box (it blocked the retry loop)

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE | SEE_MASK_FLAG_NO_UI
    info.lpVerb = "open"
    info.lpFile = target
    info.lpParameters = subprocess.list2cmdline(args) if args else None
    info.lpDirectory = os.path.dirname(target) or None
    info.nShow = 1
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        note("relaunch: shell launch refused (error %d)" % ctypes.get_last_error())
        return None
    h = info.hProcess
    if not h:
        return True     # started, but the shell gave us no handle to watch -- assume alive
    WAIT_TIMEOUT = 0x102
    alive = k32.WaitForSingleObject(h, int(wait_s * 1000)) == WAIT_TIMEOUT
    k32.CloseHandle(h)
    return alive


def spawn_successor(target, args, env, flags, delay_s, budget_s=30.0, escalate_after_s=10.0, settle_s=4.0):
    """0.16.0: start the just-swapped executable and make sure it STAYS up.

    Field record (launch.log.1, 2026-09-16): the swap fought Defender/OneDrive's
    scan lock for 11 s, then one hidden PowerShell Start-Process fired against
    the still-locked file, failed silently (stderr was DEVNULL) and KASTR was
    simply gone. Earlier, a direct Popen twice left "a bootloader with no
    child" (the same scan). So: wait the AV beat, spawn, watch the child for
    `settle_s` (a bootloader that lost its child exits within a second or two),
    respawn while the budget lasts, after `escalate_after_s` switch to the
    shell's own launch path, and tell the caller honestly whether a successor
    is running. Never a blind exit."""
    time.sleep(max(0.3, delay_s))
    t0 = time.monotonic()
    attempt = 0
    said = set()
    while time.monotonic() - t0 < budget_s:
        attempt += 1
        if time.monotonic() - t0 >= escalate_after_s:
            try:
                alive = _shell_execute_alive(target, args, settle_s)
            except Exception as e:   # 0.18.0: an exception here ended the whole window at 10 s
                key = "shell:" + type(e).__name__
                if key not in said:
                    said.add(key)
                    note("relaunch: shell launch raised (%s: %s) -- retrying while the file settles" % (type(e).__name__, e))
                alive = None
            if alive:
                note("relaunch: successor started through the shell (attempt %d)" % attempt)
                return True
            if alive is False:
                note("relaunch: shell-started successor exited at once (attempt %d) -- retrying" % attempt)
            time.sleep(1.0)
            continue
        try:
            p = subprocess.Popen([target] + args, env=env, close_fds=True, creationflags=flags,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        except Exception as e:   # 0.18.0: OSError and anything else -- keep retrying inside the budget
            key = type(e).__name__
            if key not in said:
                said.add(key)
                note("relaunch: spawn refused (%s: %s) -- retrying while the file settles" % (key, e))
            time.sleep(0.5)
            continue
        t1 = time.monotonic()
        while time.monotonic() - t1 < settle_s:
            if p.poll() is not None:
                break
            time.sleep(0.25)
        if p.poll() is None:
            note("relaunch: successor pid %d up for %.0f s (attempt %d)" % (p.pid, settle_s, attempt))
            return True
        note("relaunch: successor pid %d exited at once (code %s, attempt %d) -- respawning" % (p.pid, p.returncode, attempt))
        time.sleep(1.0)
    return False


def _call_before_exit(fn, code):
    """0.13.1: run a before_exit hook, handing it `code` when it takes one
    (main's _before_exit(grace, code)); a bare lambda gets no argument."""
    by_name = positional = False
    try:
        import inspect
        for prm in inspect.signature(fn).parameters.values():
            if prm.name == "code" and prm.kind in (prm.POSITIONAL_OR_KEYWORD, prm.KEYWORD_ONLY):
                by_name = True
            elif prm.kind in (prm.POSITIONAL_ONLY, prm.POSITIONAL_OR_KEYWORD, prm.VAR_POSITIONAL):
                positional = True
    except (TypeError, ValueError):
        pass
    if by_name and code:
        fn(code=code)          # main's _before_exit(grace=3.0, code=0)
    elif positional and code:
        fn(code)
    else:
        fn()


def relaunch_self(delay_ms=800, before_exit=None, argv=None, reason="update"):
    """0.8.9: start a fresh copy of this executable after `delay_ms`, then end
    this process (through `before_exit`, the runtime teardown, when given).

    Factored out of update_from so the Relay page's "Apply & relaunch" can
    reuse the exact machinery the self-update proved: a DETACHED shell that
    outlives us, PyInstaller's stage variables scrubbed, and env for the child:
    KASTR_RELAUNCH=1 + KASTR_RELAUNCH_PID/PORT always (0.13.1: the child waits
    for us to be GONE -- await_predecessor -- instead of taking the hand-off
    branch against our still-answering server), KASTR_UPDATED=1 only for
    reason "update" (10 s profile wait, .old-* sweeps, no update check).
    `argv` replaces sys.argv[1:] when given (the mode switch drops
    --relay-only so kastr.ini decides). `reason` is "update" or "mode".

    KASTR_CONTAINER=1 (Docker): nothing is spawned -- the entrypoint loop
    restarts the binary when we exit 75.

    0.16.0: returns False (and keeps this process running) when an "update"
    relaunch could not get a successor up; otherwise never returns."""
    target = sys.executable
    args = list(sys.argv[1:] if argv is None else argv)
    note("relaunching (%s) %s %s" % (reason, target, " ".join(args)))
    if os.environ.get("KASTR_CONTAINER") == "1":
        note("relaunch: container -- exiting 75 for the supervisor loop instead of spawning")
        _EXIT_OVERRIDE[0] = 75
        if before_exit:
            try:
                _call_before_exit(before_exit, 75)   # runtime path: teardown() -- ends the process with 75
            except Exception:
                pass
        time.sleep(0.3)
        os._exit(75)
    # Strip PyInstaller's internal vars: a bootloader inheriting the
    # updater's _PYI*/_MEI* environment believes it is the already-
    # extracted CHILD stage and hangs childless (observed live, twice).
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("_MEI", "_PYI"))}
    env.pop("KASTR_UPDATED", None)
    if reason == "update":
        env["KASTR_UPDATED"] = "1"
    env["KASTR_RELAUNCH"] = "1"
    env["KASTR_RELAUNCH_PID"] = str(os.getpid())
    env["KASTR_RELAUNCH_PORT"] = str(kastr_serve.HTTP_PORT or RELAUNCH_PORT_HINT[0] or "")   # 0.16.0: launch-time hint
    delay_s = max(0.3, delay_ms / 1000.0)
    if WINDOWS:
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0))
        if reason == "update":
            # 0.16.0: the hidden PowerShell Start-Process hop (0.8.8) fired once,
            # against a file Defender/OneDrive still held, with its error sent to
            # DEVNULL -- "it updates but doesn't restart" (launch.log.1, 2026-09-16).
            # Now: spawn, verify the child stays up, retry, escalate to the shell's
            # own launch path, and REPORT failure instead of exiting blind.
            if not spawn_successor(target, args, env, flags, delay_s):
                note("relaunch: successor never came up -- staying on this version")
                return False
        else:
            # 0.13.1: a mode switch runs the SAME, long-present exe -- no AV
            # beat needed; the child itself waits for us (await_predecessor).
            cmd = [target] + args
            try:
                subprocess.Popen(cmd, env=env, close_fds=True, creationflags=flags,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except OSError:
                # a job that forbids breakaway raises ERROR_ACCESS_DENIED
                note("relaunch: breakaway refused (ambient job) -- child may die with us")
                subprocess.Popen(cmd, env=env, close_fds=True,
                                 creationflags=flags & ~getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0),
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["sh", "-c", 'trap "" HUP; sleep %s; exec "$0" "$@"' % delay_s,
                          target] + args, env=env, close_fds=True,
                         start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    if before_exit:
        try:
            before_exit()          # runtime path: teardown() -- ends the process
        except Exception:
            pass
    time.sleep(0.3)
    os._exit(0)


def _pid_dead(pid):
    """0.13.1: has that process ended? Windows: OpenProcess(SYNCHRONIZE) and a
    zero wait -- signalled = exited; ERROR_INVALID_PARAMETER = no such pid;
    any other refusal (access denied) = alive. POSIX: kill 0."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return True
    if WINDOWS:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0
        ERROR_INVALID_PARAMETER = 87
        h = k32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return ctypes.get_last_error() == ERROR_INVALID_PARAMETER
        try:
            return k32.WaitForSingleObject(h, 0) == WAIT_OBJECT_0
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def await_predecessor(port, timeout_s=20.0):
    """0.13.1: the child side of relaunch_self. With KASTR_RELAUNCH=1 in the
    environment, wait (250 ms polls, up to 20 s) until nobody answers
    /api/instance on the port as the predecessor AND that pid is dead -- so a
    mode switch never finds its own parent still serving and takes the
    hand-off branch (the 0.12 relaunch that "never came back in relay mode").
    Pops the three keys so ffmpeg/moq children never inherit them. Returns
    True when this launch IS a relaunch (whatever the outcome), else False."""
    if os.environ.pop("KASTR_RELAUNCH", None) != "1":
        os.environ.pop("KASTR_RELAUNCH_PID", None)
        os.environ.pop("KASTR_RELAUNCH_PORT", None)
        return False
    pred = os.environ.pop("KASTR_RELAUNCH_PID", "")
    pport = os.environ.pop("KASTR_RELAUNCH_PORT", "")
    try:
        pred_pid = int(pred)
    except ValueError:
        pred_pid = 0
    try:
        check_port = int(pport) or int(port)
    except (TypeError, ValueError):
        check_port = int(port)
    t0 = time.monotonic()
    while True:
        inst = whoever_is_on(check_port)
        gone = inst is None or str(inst.get("pid")) != str(pred_pid)
        dead = _pid_dead(pred_pid)
        if gone and dead:
            note("relaunch: predecessor pid %s gone after %.1f s" % (pred_pid, time.monotonic() - t0))
            return True
        if time.monotonic() - t0 >= timeout_s:
            note("relaunch: predecessor pid %s still %s after %d s -- continuing"
                 % (pred_pid, "alive" if not dead else "answering on port %d" % check_port, int(timeout_s)))
            return True
        time.sleep(0.25)


def mode_relaunch_argv():
    """argv for a relaunch after a mode switch: the ini decides the mode, so
    --relay-only / --mode (0.12.0) and any pinned page must not ride along."""
    out = []
    skip = False
    for a in sys.argv[1:]:
        if skip:
            skip = False
            continue
        if a == "--relay-only":
            continue
        if a == "--mode":   # 0.12.0
            skip = True
            continue
        if a.startswith("--mode="):   # 0.12.0
            continue
        if a == "--page":
            skip = True
            continue
        if a.startswith("--page="):
            continue
        out.append(a)
    return out


def effective_mode(cli_mode, relay_only_flag, ini):
    """0.12.0: the operating mode this launch runs -> (mode, relay_only, solo).

    --mode beats kastr.ini `mode = ...`; --relay-only (= relay) beats --mode;
    absent or unknown = "full", the 0.11 client -- no default may turn a laptop
    into a publisher box. relay_only (bind 0.0.0.0, relay autostart on the LAN,
    firewall rules) covers BOTH relay modes; solo (the window IS the Relay
    page) only `relay` -- a publisher-relay box runs the normal app page."""
    ini_mode = str(ini.get("mode", "")).strip().lower()
    mode = cli_mode or (ini_mode if ini_mode in kastr_serve.MODES else "full")
    if relay_only_flag:
        if cli_mode and cli_mode != "relay":
            print(f"{APP_NAME}: --relay-only overrides --mode {cli_mode}", flush=True)
        mode = "relay"
    return mode, mode in ("relay", "publisher-relay"), mode == "relay"


def sweep_old_binaries():
    """0.8.7: delete KASTR.old-* left beside the executable by earlier
    self-updates. build.py sweeps its dist folder, but a field machine that
    updates itself never runs build.py -- every update left ~100 MB behind
    (and a failed swap left the operator launching the .old file)."""
    if not getattr(sys, "frozen", False):
        return
    d = os.path.dirname(sys.executable)
    me = os.path.basename(sys.executable)
    try:
        names = os.listdir(d)
    except OSError:
        return
    for fn in names:
        if fn.startswith("KASTR.old-") and fn != me:
            try:
                os.remove(os.path.join(d, fn))
            except OSError:
                pass            # still held by a dying process; next launch


def federation_master(sd=None):
    """0.11.0: (hub host | None, master) from relay-cluster.json -- the relay this
    machine's relay dials, and whether its KASTR is our update authority."""
    try:
        from urllib.parse import urlparse
        with open(os.path.join(sd or state_dir(), "relay-cluster.json"), encoding="utf-8-sig") as f:
            d = json.load(f)
        hub = str(d.get("connect") or "").strip()
        if not hub:
            return None, False
        if not hub.lower().startswith(("http://", "https://")):
            hub = "https://" + hub
        return (urlparse(hub).hostname or None), bool(d.get("master", True))
    except Exception:
        return None, False


def update_authority(relay_url, ini, sd=None):
    """-> (host | None, why). The federation master (the hub's KASTR) when this
    relay dials a hub and follows it; otherwise the relay URL's host (0.8.1)."""
    from urllib.parse import urlparse
    hub, master = federation_master(sd)
    if hub and master and hub not in ("127.0.0.1", "localhost", "::1"):
        return hub, "federation master"
    try:
        return urlparse(relay_url).hostname, "relay host"
    except Exception:
        return None, "relay host"


def update_port_for(host, ini):
    """0.15.0: the web port of the KASTR at `host` (the update feed lives there):
    an explicit `update_port` in kastr.ini wins, then the port LEARNED for that
    host (hub-web.json / the learner -> kastr_serve.HUB_WEB), then 8000."""
    try:
        if ini is not None and "update_port" in ini and str(ini.get("update_port")).strip():
            return int(ini.get("update_port"))
    except (TypeError, ValueError):
        pass
    return kastr_serve.hub_web_for(host, 8000)


def authority_base(host, ini, relay_url=None, sd=None):
    """0.19.0: the update authority's web base URL: an explicit kastr.ini update_port
    wins, then a web relay's origin (https://name/relay -> https://name), then the
    learned base / port (kastr_serve.hub_web_base), then :8000."""
    import kastr_relay
    h = ("[" + host + "]") if ":" in str(host) else str(host)
    try:
        if ini is not None and "update_port" in ini and str(ini.get("update_port")).strip():
            return "http://%s:%d" % (h, int(ini.get("update_port")))
    except (TypeError, ValueError):
        pass
    try:
        ru = _authority_relay_url(host, relay_url, sd) if relay_url else None
        if ru and kastr_relay.is_web_relay(ru):
            return kastr_relay.web_origin(ru)
    except Exception:
        pass
    return kastr_serve.hub_web_base(host, 8000) or "http://%s:8000" % h


def load_hub_web(sd=None):
    """0.15.0: hub-web.json -> kastr_serve.HUB_WEB (what earlier launches learned)."""
    import kastr_relay
    n = 0
    for host, rec in kastr_relay.hub_web_load(sd or state_dir()).items():
        kastr_serve.HUB_WEB[host] = {"web": rec["web"], "https": rec.get("https"), "base": rec.get("base")}   # 0.19.0: + base
        n += 1
    return n


def _authority_relay_url(host, relay_url, sd=None):
    """The relay URL whose host is `host`: the stored hub link when it names that
    host (federation master), else the relay URL this KASTR uses."""
    try:
        from urllib.parse import urlparse
        with open(os.path.join(sd or state_dir(), "relay-cluster.json"), encoding="utf-8-sig") as f:
            hub = str(json.load(f).get("connect") or "").strip()
        if hub and not hub.lower().startswith(("http://", "https://")):
            hub = "https://" + hub
        if hub and (urlparse(hub).hostname or "").lower() == str(host).lower():
            return hub
    except Exception:
        pass
    return relay_url


_HUB_WEB_SAID = {}         # host -> web port last announced in launch.log


def learn_hub_web(relay_url, ini, once=False, budget=3.0):
    """0.15.0: learn the web port of the KASTR this box follows (the update
    authority: federation master or relay host) BEFORE anything dials it ->
    the learned {web, https, via} or None. Loopback / unparsable: nothing to
    learn. Remembered in hub-web.json + kastr_serve.HUB_WEB; one launch.log
    line per change. `once` = the launch-time call (logged as such)."""
    host, _why = update_authority(relay_url, ini)
    if not host or host in ("127.0.0.1", "localhost", "::1"):
        return None
    return learn_hub_web_host(host, relay_url, ini, once=once, budget=budget)


def learn_hub_web_host(host, relay_url, ini, once=False, budget=3.0):
    """0.16.0: the host-directed half of learn_hub_web -- a relay SWITCH names a
    host the launch-time learner never saw, and its update check dialled 8000
    (the Agg hub pins 8001). `relay_url` is the hint for the minter's /api/auth."""
    import kastr_relay
    if not host or host in ("127.0.0.1", "localhost", "::1"):
        return None
    host = str(host).lower()
    cands = [kastr_serve.HUB_WEB.get(host, {}).get("web")]
    try:
        if ini is not None and "update_port" in ini:
            cands.append(int(ini.get("update_port")))
    except (TypeError, ValueError):
        pass
    found = kastr_relay.probe_hub_web(_authority_relay_url(host, relay_url),
                                      candidates=[c for c in cands if c], budget=budget)
    if not found:
        if once and host not in _HUB_WEB_SAID:
            note("hub web port: %s did not answer within %.0f s -- using %d for now"
                 % (host, budget, update_port_for(host, ini)))
        return None
    try:
        changed = kastr_relay.hub_web_note(state_dir(), host, found["web"], found.get("https"), found.get("base"))
    except Exception as e:
        changed = False
        note("hub web port: could not write hub-web.json: %s" % e)
    kastr_serve.HUB_WEB[host] = {"web": found["web"], "https": found.get("https"), "base": found.get("base")}   # 0.19.0
    if changed or _HUB_WEB_SAID.get(host) != found["web"]:
        _HUB_WEB_SAID[host] = found["web"]
        note("hub web port %d learned for %s (%s%s)" % (found["web"], host, found["via"],
                                                        " at launch" if once else ""))
    return found


def start_update_sweeper(check, every=3600, label="federation master: hourly check"):
    """0.11.0: hourly version match against the federation master (kastr_serve.
    start_media_sweeper idiom). The first tick waits a full period -- the
    launch-time check just ran. 0.15.0: `every`/`label` make it the generic
    repeating timer (the 5-minute hub web learner rides it too)."""
    def tick():
        try:
            check()
        except Exception as e:
            note("%s failed: %s" % (label, e))
        t = threading.Timer(every, tick)
        t.daemon = True
        t.start()
    t = threading.Timer(every, tick)
    t.daemon = True
    t.start()
    return t


# ---- update feed mirror (0.15.0) ---------------------------------------------
# Kenton's decision: a box that hosts a relay ALWAYS mirrors the update feed --
# the other platforms' binaries and both browser zips -- from its own authority
# (the hub, or the relay host it follows), so every relay box is a complete
# turnkey feed for the clients dialled into it (kastr_serve._update_platforms /
# _browser_feed serve <exe dir>/updates/...). Off with `update_mirror = off`.

MIRROR_PLATFORMS = {"win32": ("windows", "KASTR.exe"), "linux": ("linux", "KASTR"),
                    "darwin": ("macos", "KASTR")}        # = kastr_serve._update_platforms
MIRROR_BROWSER_KEYS = {"win32": "win64", "linux": "linux64"}   # = kastr_serve._browser_feed
_MIRROR_HASHES = {}        # path -> (mtime, size, sha256): hash lazily, once per file version
_MIRROR_SAID = [False]     # the "mirroring N files" line, once per process
_MIRROR_BUSY = threading.Lock()


def own_platform():
    return "win32" if WINDOWS else "darwin" if MACOS else "linux"


def hosts_relay(relay=None, sd=None):
    """Does THIS box host a relay? Running now, a relay mode, or autostart on."""
    try:
        if relay is not None and relay.running():
            return True
    except Exception:
        pass
    if kastr_serve.MODE in ("relay", "publisher-relay"):
        return True
    try:
        with open(os.path.join(sd or state_dir(), "relay-autostart.json"), encoding="utf-8-sig") as f:
            return bool(json.load(f).get("enabled"))
    except Exception:
        return False


def file_sha256(path):
    """sha256 of `path` (None when missing), cached by mtime+size."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    c = _MIRROR_HASHES.get(path)
    if c and c[0] == st.st_mtime and c[1] == st.st_size:
        return c[2]
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    _MIRROR_HASHES[path] = (st.st_mtime, st.st_size, h.hexdigest())
    return h.hexdigest()


def _mirror_one(url, target, sha, size):
    """Download url -> target.part, verify sha256 + size, os.replace into place.
    Raises on any failure (the .part is removed)."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = target + ".part"
    h = hashlib.sha256()
    got = 0
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                f.write(chunk)
                got += len(chunk)
        if h.hexdigest() != sha:
            raise RuntimeError("checksum mismatch")
        if size and got != int(size):
            raise RuntimeError("size mismatch (%d of %d bytes)" % (got, int(size)))
        os.replace(part, target)
    except Exception:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    if not target.endswith((".exe", ".zip")):
        try:
            os.chmod(target, 0o755)
        except OSError:
            pass
    _MIRROR_HASHES.pop(target, None)


def mirror_feeds(base, ini, relay=None, app_root=None, sd=None):
    """Mirror the update feed at `base` (http://host:port) into <app dir>/updates/
    -> {"mirrored": [paths], "skipped": n, "failed": [(label, why)]}, or None when
    it does not apply (source checkout without KASTR_MIRROR_DEV=1, update_mirror
    off, or this box hosts no relay). Own-platform binary excluded (served from
    sys.executable); browser zips for every platform the feed offers; a file
    whose sha256 already matches is left alone; failures logged, never fatal."""
    if not FROZEN and os.environ.get("KASTR_MIRROR_DEV") != "1":
        return None
    if str((ini or {}).get("update_mirror", "true")).strip().lower() in ("off", "false", "0", "no"):
        return None
    if not hosts_relay(relay, sd):
        return None
    if not _MIRROR_BUSY.acquire(blocking=False):
        return None           # a previous run is still downloading
    try:
        try:
            with urllib.request.urlopen(base + "/api/update/manifest", timeout=5) as r:
                man = json.load(r)
        except Exception as e:
            note("update mirror: manifest fetch failed from %s (%s)" % (base, e))
            return {"mirrored": [], "skipped": 0, "failed": [("manifest", str(e))]}
        if not isinstance(man, dict) or man.get("app") != "KASTR":
            return {"mirrored": [], "skipped": 0, "failed": [("manifest", "no KASTR feed at " + base)]}
        root = app_root or app_dir()
        plan = []
        for plat, info in (man.get("platforms") or {}).items():
            if plat == own_platform() or plat not in MIRROR_PLATFORMS or not isinstance(info, dict):
                continue
            sub, fn = MIRROR_PLATFORMS[plat]
            plan.append(("%s binary" % plat, base + "/api/update/binary?platform=" + plat,
                         os.path.join(root, "updates", sub, fn), info))
        br = man.get("browser") if isinstance(man.get("browser"), dict) else {}
        for plat, info in (br.get("platforms") or {}).items():
            if not isinstance(info, dict):
                continue
            rootname = str(info.get("root") or "")
            key = rootname[len("chrome-"):] if rootname.startswith("chrome-") else MIRROR_BROWSER_KEYS.get(plat)
            if not key or not re.match(r"^[a-z0-9]{1,16}$", key):
                continue
            plan.append(("%s browser" % plat, base + "/api/update/browser?platform=" + plat,
                         os.path.join(root, "updates", "browser", "chrome-%s.zip" % key), info))
        todo, skipped = [], 0
        for label, url, target, info in plan:
            sha = str(info.get("sha256") or "")
            if not sha:
                continue
            if file_sha256(target) == sha:
                skipped += 1
            else:
                todo.append((label, url, target, info))
        out = {"mirrored": [], "skipped": skipped, "failed": []}
        if todo and not _MIRROR_SAID[0]:
            _MIRROR_SAID[0] = True
            mb = sum(int(i.get("size") or 0) for _l, _u, _t, i in todo) // (1 << 20)
            note("update mirror: mirroring %d files (~%d MB) from %s" % (len(todo), mb, base))
        for label, url, target, info in todo:
            try:
                _mirror_one(url, target, str(info.get("sha256") or ""), info.get("size"))
                out["mirrored"].append(target)
                note("update mirror: %s -> %s" % (label, target))
            except Exception as e:
                out["failed"].append((label, str(e)))
                note("update mirror: %s NOT mirrored (%s)" % (label, e))
        # the browser feed's VERSION beside the zips (kastr_serve._browser_feed reads it)
        bver = str(br.get("version") or "").strip()
        if bver and br.get("platforms") and not out["failed"]:
            vf = os.path.join(root, "updates", "browser", "VERSION")
            try:
                with open(vf, encoding="utf-8") as f:
                    cur = f.read().strip()
            except OSError:
                cur = None
            if cur != bver:
                try:
                    os.makedirs(os.path.dirname(vf), exist_ok=True)
                    with open(vf + ".tmp", "w", encoding="utf-8", newline=chr(10)) as f:
                        f.write(bver + chr(10))
                    os.replace(vf + ".tmp", vf)
                    out["mirrored"].append(vf)
                except OSError as e:
                    out["failed"].append(("browser VERSION", str(e)))
        return out
    finally:
        _MIRROR_BUSY.release()


def mirror_after_update(relay_url, ini, status, relay=None):
    """Kick mirror_feeds off-thread once the version match settled (current /
    updated -- or dev, which mirror_feeds itself gates). Authority = the same
    host check_update used, on the port learned for it."""
    if status not in ("current", "updated", "dev"):
        return None
    host, _why = update_authority(relay_url, ini)
    if not host or host in ("127.0.0.1", "localhost", "::1"):
        return None
    base = authority_base(host, ini, relay_url)   # 0.19.0: a web relay's origin too

    def go():
        try:
            mirror_feeds(base, ini, relay=relay)
        except Exception as e:
            note("update mirror: failed (%s)" % e)
    t = threading.Thread(target=go, daemon=True, name="kastr-mirror")
    t.start()
    return t


def browser_update(relay_url, ini):
    """0.9.0: keep the bundled browser folder matched to the fleet authority's
    (same probe as check_update; silent skip everywhere it does not apply)."""
    if not getattr(sys, "frozen", False):
        return
    if str(ini.get("update", "")).lower() in ("off", "false", "0", "no"):
        return
    if str(ini.get("browser", "bundled")).strip().lower() not in ("bundled", ""):
        return                                    # a system/explicit browser: nothing to update
    host, _why = update_authority(relay_url, ini)   # 0.11.0: the federation master when there is one
    if not host or host in ("127.0.0.1", "localhost", "::1"):
        return
    try:
        import kastr_browser
        base = authority_base(host, ini, relay_url)   # 0.15.0: the learned hub web port; 0.19.0: or a web relay's origin
        kastr_browser.sweep_old(app_dir())
        kastr_browser.fetch_update(base, app_dir(), kastr_browser.platform_name(), note)
    except Exception as e:
        note("browser update: skipped (%s)" % e)


def check_update(relay_url, ini):
    """Match this client to the relay host's KASTR version (0.8.1).

    The KASTR instance on the relay-server machine is the fleet's source of
    truth: at launch, ask it what version it runs; if different (upgrades
    AND downgrades -- "match client to server"), pull our platform's binary
    from it, verify the checksum, swap via the rename-aside trick, and
    relaunch. Any failure means launching the current version normally."""
    # 0.15.0: returns the outcome (update_note's status) so main can mirror the feed
    if not getattr(sys, "frozen", False):
        return update_note("dev", "source checkouts never self-update")
    if os.environ.get("KASTR_UPDATED") == "1":
        return update_note("updated", "updated and relaunched as v"
                           + kastr_serve.read_version())   # the relaunch itself; never loop
    if str(ini.get("update", "")).lower() in ("off", "false", "0", "no"):
        return update_note("off", "update = off in kastr.ini")
    host, why = update_authority(relay_url, ini)   # 0.11.0: a spoke follows its hub's KASTR
    if not host:
        return update_note("skipped", "relay URL unparsable: " + str(relay_url))
    if host in ("127.0.0.1", "localhost", "::1"):
        return update_note("authority", "the relay is on this machine -- "
                           "it IS the fleet's version authority")
    if why == "federation master":
        note("update-check: following the federation master " + host)
    base = authority_base(host, ini, relay_url)   # 0.15.0: ini update_port > learned hub web port > 8000; 0.19.0: web relay origin
    inst = _probe_authority(base)
    if inst is None:
        return "unreachable"
    theirs = str(inst.get("version") or "")
    mine = kastr_serve.read_version()
    if not theirs or theirs == mine or "-dev" in theirs:
        return update_note("current", f"relay host runs v{theirs or '?'}; "
                           f"staying on v{mine}")
    return update_from(base, theirs, mine)


def runtime_update(host, port, before_exit):
    """0.8.6: the same match, on demand -- a relay switch or the "Check for
    updates" button. A NEW relay may be a new version authority; waiting for
    the next launch left a tester on 0.8.1 for days."""
    if not getattr(sys, "frozen", False):
        update_note("dev", "source checkouts never self-update")
        return {"status": "dev"}
    try:
        if str(kastr_serve.ini_get("update") or "").lower() in ("off", "false", "0", "no"):
            update_note("off", "update = off in kastr.ini")
            return {"status": "off"}
    except Exception:
        pass
    if not host or host in ("127.0.0.1", "localhost", "::1"):
        update_note("authority", "the relay is on this machine -- "
                    "it IS the fleet's version authority")
        return {"status": "authority"}
    base = port if (isinstance(port, str) and "://" in port) else f"http://{host}:{port}"   # 0.19.0: callers pass a base
    update_note("checking", base)
    inst = _probe_authority(base)
    if inst is None:
        return {"status": "unreachable", "detail": base}
    theirs = str(inst.get("version") or "")
    mine = kastr_serve.read_version()
    if not theirs or theirs == mine or "-dev" in theirs:
        update_note("current", f"relay host runs v{theirs or '?'}; "
                    f"staying on v{mine}")
        return {"status": "current", "theirs": theirs}
    st = update_from(base, theirs, mine, relaunch_delay_ms=7000,   # 0.8.8: window close budget first
                     before_exit=before_exit)
    return {"status": st or "updating", "theirs": theirs}

_ACTIVE_PROFILE = None     # what launch() actually used; supervise reads it
LAUNCH_ERROR = [None]      # 0.9.3: why the last launch() returned None (log + dialog)
# 0.9.3: a bundled browser that exits NON-ZERO this fast never opened a window
# (sandbox refused, shared library missing, display unusable). A zero exit this
# fast is a hand-off to a browser already holding the profile -- supervise's job.
BUNDLED_PROBE_S = 4.0


def _is_bundled(browser):
    try:
        import kastr_browser
        return kastr_browser.is_bundled(browser, app_dir())
    except Exception:
        return False


def _is_root():
    return sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0


def sandbox_unusable(browser):
    """0.9.3, Linux, not root: can Chrome's sandbox start here at all?

    Ubuntu 23.10+ denies unprivileged user namespaces to unconfined programs
    (kernel.apparmor_restrict_unprivileged_userns=1; Google's own .deb ships an
    AppArmor profile, an unzipped Chrome for Testing has none), and the
    unzipped chrome_sandbox helper is not SUID root -- so Chrome dies with
    "No usable sandbox!" before any window appears. Returns (True, why) when
    --no-sandbox is the only way the window opens. The window only ever loads
    KASTR's own local pages, so that is the intended escape hatch."""
    if not sys.platform.startswith("linux") or _is_root():
        return False, ""
    try:
        st = os.stat(os.path.join(os.path.dirname(browser), "chrome_sandbox"))
        if st.st_mode & stat.S_ISUID and st.st_uid == 0:
            return False, ""             # the SUID helper works regardless of userns policy
    except OSError:
        pass
    for path, bad in (("/proc/sys/kernel/apparmor_restrict_unprivileged_userns", "1"),
                      ("/proc/sys/kernel/unprivileged_userns_clone", "0")):
        try:
            with open(path, encoding="utf-8") as f:
                if f.read().strip() == bad:
                    return True, "%s=%s" % (os.path.basename(path), bad)
        except OSError:
            continue
    return False, ""


def _stderr_tail(path):
    """The last non-empty line the browser wrote (why it died), or ""."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4000))
            data = f.read()
        lines = [ln.strip() for ln in data.decode("utf-8", "replace").splitlines() if ln.strip()]
        return lines[-1][:240] if lines else ""
    except OSError:
        return ""


def _start(args, errlog):
    """Popen with the browser's stderr kept in a file (0.9.3): a --noconsole
    build has no console, and Chrome's last line is the one reason a failed
    launch can show. Best-effort -- without the file it starts as before."""
    fh = None
    try:
        fh = open(errlog, "wb")
    except OSError:
        fh = None
    try:
        return subprocess.Popen(args, stderr=fh, stdin=subprocess.DEVNULL)
    finally:
        if fh is not None:
            fh.close()


def browser_args(browser, url, page, no_sandbox=False):
    """The command line for one browser attempt (0.9.3: split out of launch()).

    A dedicated profile directory is deliberate. Launching into the user's
    normal profile hands the URL to an already-running browser and exits
    immediately, so there would be no process to wait on -- and the window
    would arrive as a tab rather than an app window.
    """
    profile = profile_dir(browser)
    global _ACTIVE_PROFILE
    _ACTIVE_PROFILE = profile
    print(f"browser: {browser}", flush=True)   # 0.9.0: which engine actually opened
    print(f"browser profile: {profile}", flush=True)
    # Per-launch cache-buster (0.8.1): a unique top-document URL means the
    # browser can never serve a stale shell from BFCache/disk after an
    # update ("launches with a stale app" field report).
    buster = ("&" if "?" in page else "?") + "launch=" + str(int(time.time()))
    args = [
        browser,
        f"--app={url}{page}{buster}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        # Control-room default: don't make an operator click the page before
        # audio will play. The pages' own diagnostics call out a suspended
        # AudioContext as the usual cause of "video fine, no sound".
        "--autoplay-policy=no-user-gesture-required",
        # Keep running at full speed when the window is behind something or
        # minimised. Publishing an RTSP source captures a <video> element, and
        # a throttled page only paints about once a second -- measured 30 fps
        # in front against 0.24 fps behind, which looks like a frozen stream to
        # everybody watching.
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]
    # 0.9.2: Chrome for Testing shows a permanent "only for automated testing"
    # infobar; Chromium skips it (and the unsupported-flags warning) when the
    # process runs as a GPU test harness. Bundled engine only.
    if _is_bundled(browser):
        args.append("--test-type=gpu")
        args.append("--lang=en-US")   # 0.9.3: the bundled browser ships en-US only (locales pruned)

    # 0.8.3: hardware video on Linux. Chromium ships VA-API acceleration OFF
    # there, so the library's prefer-hardware encoder probe fails and every
    # robot box silently encodes (and decodes) in software. Windows has
    # hardware video on by default and gets no extra flags.
    if sys.platform.startswith("linux"):
        args.append("--enable-features=VaapiVideoDecoder,VaapiVideoEncoder,"
                    "VaapiVideoDecodeLinuxGL,VaapiIgnoreDriverChecks")
        args.append("--ignore-gpu-blocklist")

    # Chromium refuses to start its sandbox as root (crbug.com/638180) and
    # exits before any window appears -- seen live on an Ubuntu box driven
    # as root, which is normal on robot/industrial machines. The window only
    # loads this app's own localhost pages, so dropping the sandbox there is
    # the intended escape hatch, not a shortcut.
    if _is_root():
        print("running as root: passing --no-sandbox to the browser (crbug.com/638180)")
        args.append("--no-sandbox")
    elif no_sandbox:
        args.append("--no-sandbox")   # 0.9.3: see sandbox_unusable() / the retry in launch()

    # Geometry the page reported last time, or maximized on a first run.
    args += window_args()
    return args


def launch(browser, url, page):
    """Open the app window and return the process, or None when no Chromium
    could be started -- LAUNCH_ERROR[0] then says why, for the dialog.

    0.9.3: the bundled browser gets up to three tries -- as is; with
    --no-sandbox (Linux, not root: outright when sandbox_unusable() says the
    sandbox cannot start here, otherwise as a retry when the first attempt
    died); then a system Chromium -- and a bundled browser that exits non-zero
    within BUNDLED_PROBE_S counts as died. The hand-off to the OS default
    browser is gone: Firefox (what the Linux box that reported this opened)
    cannot run KASTR, and opening it there only made a failure look like success.
    """
    LAUNCH_ERROR[0] = None
    attempts = [(browser, False, None)]
    if _is_bundled(browser):
        bad, why = sandbox_unusable(browser)
        if bad:
            attempts = [(browser, True, "the sandbox cannot start here (%s): --no-sandbox" % why)]
        elif sys.platform.startswith("linux") and not _is_root():
            attempts.append((browser, True, "retrying with --no-sandbox"))
        system = find_browser(system_only=True)
        if system:
            attempts.append((system, False, "falling back to the system browser"))
    reasons = []
    errlog = os.path.join(state_dir(), "browser-stderr.log")
    for cand, no_sandbox, label in attempts:
        if label:
            note("browser: " + label)
        args = browser_args(cand, url, page, no_sandbox=no_sandbox)
        try:
            proc = _start(args, errlog)
        except OSError as e:
            reasons.append("%s: %s" % (os.path.basename(cand), e))
            note("browser: could not start %s (%s)" % (cand, e))
            continue
        if not _is_bundled(cand):
            return proc                  # system browsers keep the old contract: supervise judges them
        code = None
        t0 = time.monotonic()
        while time.monotonic() - t0 < BUNDLED_PROBE_S:
            code = proc.poll()
            if code is not None:
                break
            time.sleep(0.2)
        if code is None or code == 0:
            return proc
        tail = _stderr_tail(errlog)
        reasons.append("%s exited with code %s%s" % (os.path.basename(cand), code, (" -- " + tail) if tail else ""))
        note("browser: " + reasons[-1])
    LAUNCH_ERROR[0] = "; ".join(reasons) or "no browser could be started"
    return None


def no_window_message(url, reason):
    """0.9.3: the one dialog for 'KASTR runs, but nothing can show it'."""
    nl = chr(10)
    return (APP_NAME + " is running at:" + nl + url + nl + nl
            + "but no Chromium browser could be started: " + reason + "." + nl + nl
            + "Open that address in Chrome or Chromium (Firefox cannot run " + APP_NAME
            + "). Close this message, or the page, to stop the server.")


# How long to keep serving after the last page heartbeat. Generous, because
# browsers throttle timers hard in a background or minimised window.
HEARTBEAT_GRACE = 150.0
# How long to wait for the FIRST heartbeat before giving up on a window ever
# appearing. Covers a cold browser start.
STARTUP_GRACE = 60.0
# A browser process that exits faster than this never really owned a window;
# it handed the URL to an instance already holding the profile.
HANDOFF_WINDOW = 10.0


def browser_gone(profile):
    """True only when the browser holding this profile has definitely exited.

    Deliberately one-directional. Chrome deletes its lockfile on exit, so
    "absent" is solid evidence the window is gone and shutdown can stop waiting
    out the heartbeat grace. Anything else returns False -- the lock belongs to
    the profile rather than to our window, so a present lock is not proof that
    OUR window is still open, and treating it that way would hang shutdown
    behind somebody else's browser.
    """
    if MACOS or not WINDOWS:
        # Chrome leaves a SingletonLock symlink whose target is host-pid.
        link = os.path.join(profile, "SingletonLock")
        try:
            target = os.readlink(link)
        except OSError:
            return not os.path.lexists(link)
        try:
            pid = int(str(target).rsplit("-", 1)[-1])
        except (ValueError, IndexError):
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True             # stale symlink, the browser is gone
        except OSError:
            return False            # exists but not ours to signal
        return False
    return not os.path.exists(os.path.join(profile, "lockfile"))


def _browser_pids_for(profile):
    """0.8.8: the browser processes holding our profile, without psutil.

    Chrome hands a second launch to the instance already holding the profile,
    so the Popen we track may be long gone while the real window lives on in
    a process nobody handed us. The command line names the profile dir; the
    --type= children are renderers/GPU and die with the browser process."""
    needle = "--user-data-dir=" + profile
    pids = []
    if WINDOWS:
        esc = needle.replace("'", "''").replace("[", "`[").replace("]", "`]").replace("*", "`*")
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' or Name='msedge.exe'\" | "
              "Where-Object { $_.CommandLine -like '*%s*' -and $_.CommandLine -notlike '*--type=*' } | "
              "Select-Object -ExpandProperty ProcessId" % esc)
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=10,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            pids = [int(x) for x in out.split() if x.strip().isdigit()]
        except Exception:
            pass
    else:
        try:
            tgt = os.readlink(os.path.join(profile, "SingletonLock"))
            pids.append(int(str(tgt).rsplit("-", 1)[-1]))
        except Exception:
            pass
        if os.path.isdir("/proc"):
            for d in os.listdir("/proc"):
                if not d.isdigit():
                    continue
                try:
                    with open("/proc/%s/cmdline" % d, "rb") as f:
                        cmd = f.read()
                except OSError:
                    continue
                if needle.encode() in cmd and b"--type=" not in cmd:
                    pids.append(int(d))
    return sorted(set(pids))


def close_app_window(profile, proc, grace=3.0):
    """0.8.8: close the app window for real before a self-update relaunch.

    Layer 1 is cooperative: the heartbeat answers 205 and the page closes
    itself. Layer 2 insists: the tracked Popen, then every browser process
    whose command line carries our profile directory."""
    try:
        kastr_serve.CLOSING[0] = True
    except Exception:
        pass
    t0 = time.monotonic()
    while time.monotonic() - t0 < grace and not browser_gone(profile):
        time.sleep(0.25)
    if browser_gone(profile):
        return True
    stop_child(proc, 2)
    pids = _browser_pids_for(profile)
    for pid in pids:
        try:
            if WINDOWS:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                               timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    t0 = time.monotonic()
    while time.monotonic() - t0 < 3.0 and not browser_gone(profile):
        if not _browser_pids_for(profile):
            break
        time.sleep(0.25)
    if not WINDOWS:
        for pid in _browser_pids_for(profile):
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
    return browser_gone(profile) or not _browser_pids_for(profile)


def stop_child(proc, grace):
    """Ask a child to stop, then insist. Never blocks longer than grace + 3s."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(grace)
    except Exception:
        try:
            proc.kill()
            proc.wait(3)
        except Exception:
            pass


_EXTRA_SERVERS = []        # 0.8.9: the https listener, closed with the main server
_TEARDOWN = threading.Lock()
_TORN = [False]


def teardown(server, proc=None, code=0):
    """The only way out. Idempotent, bounded, and it always ends the process.

    Order matters: ffmpeg first (killing it releases the streaming threads that
    would otherwise hold the server), then moq-relay, which has real shutdown
    work to do, then the HTTP server, then whatever browser we started if it
    somehow outlived us.
    """
    with _TEARDOWN:
        if _TORN[0]:
            return
        _TORN[0] = True

    # If anything below wedges, leave anyway. Timer is NOT a daemon by default
    # and a non-daemon one would itself keep the interpreter alive.
    watchdog = threading.Timer(8.0, lambda: os._exit(3))
    watchdog.daemon = True
    watchdog.start()

    # Everything here is best-effort. The one guarantee this function makes
    # is the os._exit in the finally: an exception in the cleanup must not
    # be able to leave a half-torn-down KASTR holding its port.
    try:
        try:
            os.remove(os.path.join(state_dir(), "http-port"))   # 0.13.3: nobody is on that port any more
        except OSError:
            pass
        for stop in ("rtsp", "relay"):
            target = getattr(server, stop, None)
            try:
                if stop == "rtsp" and target is not None:
                    target.shutdown()
                elif target is not None:
                    target.stop()
            except Exception:
                pass

        try:
            t = threading.Thread(target=server.shutdown, daemon=True)
            t.start()
            t.join(2.0)
        except Exception:
            pass

        for extra in list(_EXTRA_SERVERS):
            try:
                extra.shutdown()
                extra.server_close()
            except Exception:
                pass
        stop_child(proc, 3)

        # A windowed build has no stdio: these are None, not files.
        for stream in (sys.stdout, sys.stderr):
            try:
                if stream is not None:
                    stream.flush()
            except Exception:
                pass
    except Exception:
        pass
    finally:
        os._exit(_EXIT_OVERRIDE[0] if _EXIT_OVERRIDE[0] is not None else code)   # 0.13.1


def watch_parent():
    """Frozen onefile runs as bootloader + child; do not outlive the bootloader.

    Killing the parent used to leave the child holding the port -- which is how
    a stale KASTR came to block a rebuild of its own .exe.
    """
    if not getattr(sys, "frozen", False):
        return
    ppid = os.getppid()

    def wait_windows():
        # NOT os.kill(ppid, 0): on Windows that is TerminateProcess, so the
        # 'probe' would kill the very parent it is watching.
        import ctypes

        SYNCHRONIZE = 0x00100000
        INFINITE = 0xFFFFFFFF
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(SYNCHRONIZE, False, ppid)
        if not handle:
            return                  # already gone, or not ours to watch
        try:
            # Blocks until the bootloader exits. Holding the handle keeps the
            # kernel object alive, so a recycled pid cannot alias it.
            k32.WaitForSingleObject(handle, INFINITE)
        finally:
            k32.CloseHandle(handle)
        STOP.set()

    def wait_posix():
        # Reparenting to init is the signal the parent has gone.
        while not STOP.is_set():
            if os.getppid() != ppid:
                break
            time.sleep(1.0)
        STOP.set()

    threading.Thread(target=wait_windows if WINDOWS else wait_posix,
                     daemon=True).start()


def whoever_is_on(port):
    """Identity of whatever KASTR is serving on this port, or None.

    Two instances cannot share one browser profile: the second launch hands
    its URL to the browser already holding the profile and the process it
    spawned exits at once. So a launch that finds ITSELF already running
    should just show that window.

    But it has to be the same build. This used to be a bare POST to the page
    heartbeat, which any copy answers identically -- so a checkout running
    from source captured the launch of the frozen app and the user got a
    different version than the one they started. Ask who is there instead.
    """
    url = "http://127.0.0.1:%d" % port
    try:
        with urllib.request.urlopen(url + "/api/instance", timeout=1.5) as r:
            if r.status != 200:
                return None
            info = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(info, dict) or info.get("app") != "KASTR":
        return None
    info["url"] = url
    return info


def same_build(info):
    """Is that instance this very build?"""
    return (info
            and info.get("version") == kastr_serve.read_version()
            and bool(info.get("frozen")) == bool(getattr(sys, "frozen", False)))


def port_is_free(port, host):
    """0.14.0: one bind probe -- could this process bind that port right now?

    POSIX: with SO_REUSEADDR, as the server itself binds (a lingering
    TIME_WAIT must not read as busy). Windows: WITHOUT it -- there
    SO_REUSEADDR lets the probe bind over any listener that also set it
    (every Python HTTP server does), so the old probe called a port a dev
    server held "free"; a plain bind answers truthfully, and Windows never
    refuses a bind over TIME_WAIT alone (measured 2026-09-23).
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if not WINDOWS:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, int(port)))
            return True
        except OSError:
            return False


def free_port(start, host):
    """First port in start..start+39 that nothing is listening on, or None
    when the whole range is busy (0.14.0: it used to hand back `start`)."""
    for port in range(start, start + 40):
        if port_is_free(port, host):
            return port
    return None


# 0.14.0: the same HTTP port every launch. The page's localStorage (profile,
# rooms, kept feeds, seats) is origin-scoped -- http://127.0.0.1:<port> -- so a
# box where 8000 belongs to another program, which bind_free answered with a
# fresh OS port per launch, forgot everything at every start (Southridge:
# 8000 held by System pid 4). The port this box settles on is remembered in
# state_dir/port.json (never removed; http-port stays the live-instance file)
# and reused for as long as the operator has not pinned one.
PORT_MEMORY = "port.json"


def _port_memory_read():
    try:
        with open(os.path.join(state_dir(), PORT_MEMORY), encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def port_remembered(host, wanted):
    """The port this box moved to earlier, when port.json was written for the
    same host and the same wanted port; else None."""
    d = _port_memory_read()
    try:
        if str(d.get("host")) != str(host) or int(d.get("wanted")) != int(wanted):
            return None
        port = int(d.get("port"))
    except Exception:
        return None
    return port if 1024 <= port <= 65535 else None


def port_pinned():
    """0.14.0 F: the port the operator chose on the Relay page (port.json
    `pinned: true`), else None. Beats kastr.ini; only --port beats it."""
    d = _port_memory_read()
    try:
        if not d.get("pinned"):
            return None
        port = int(d.get("port"))
    except Exception:
        return None
    return port if 1024 <= port <= 65535 else None


def port_remember(port, host, wanted, pinned=None):
    """Write port.json (tmp + replace). Best-effort; never removed. Keeps an
    existing `pinned` flag unless told otherwise."""
    try:
        cur = _port_memory_read()
        path = os.path.join(state_dir(), PORT_MEMORY)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"port": int(port), "host": str(host), "wanted": int(wanted), "at": time.time(),
                       "pinned": bool(cur.get("pinned")) if pinned is None else bool(pinned)}, f)
        os.replace(tmp, path)
        return True
    except Exception as e:
        note("could not write %s: %s" % (PORT_MEMORY, e))
        return False


def port_memory_text():
    """--diagnose: 'port N (wanted W[, pinned])' from port.json, or 'none'."""
    d = _port_memory_read()
    try:
        return "port %s (wanted %s%s)" % (int(d.get("port")), int(d.get("wanted")), ", pinned" if d.get("pinned") else "")
    except Exception:
        return "none"


def port_explicit(ini, argv=None):
    """Did the operator pin the port (kastr.ini `port =` other than the default
    8000, or --port on the command line)? A pinned port is never traded for a
    remembered one."""
    # kastr.ini ships with `port = 8000` in its template on every box, so 8000 there is
    # the default, not a pin (0.14.0): only another value pins the port.
    if isinstance(ini, dict) and "port" in ini:
        try:
            if int(str(ini.get("port")).strip()) != 8000:
                return True
        except (TypeError, ValueError):
            return True
    for a in (sys.argv[1:] if argv is None else argv):
        if a == "--port" or a.startswith("--port="):
            return True
    return False


def resolve_sticky_port(args, ini):
    """The launch-time decision before anyone looks at the port: follow
    port.json when nothing pins the port. Mutates args.port; returns
    (explicit, ephemeral) for the caller's bookkeeping."""
    explicit = port_explicit(ini)
    ephemeral = int(args.port) == 0
    # 0.14.0 F: a port pinned on the Relay page beats kastr.ini; only --port beats it
    pinned = None if (ephemeral or port_explicit({}, argv=None)) else port_pinned()
    if pinned:
        if pinned != args.port:
            note("port %d: the operator pinned %d on the Relay page (port.json) -- using it" % (args.port, pinned))
            args.port = pinned
        return True, ephemeral
    if not explicit and not ephemeral:
        sticky = port_remembered(args.host, args.port)
        if sticky and sticky != args.port:
            note("port %d: this box moved to %d earlier (port.json) -- staying there so the app keeps its browser storage"
                 % (args.port, sticky))
            args.port = sticky
    return explicit, ephemeral


def choose_bind_port(port, host, squatter):
    """The port to bind, decided HERE rather than by a bind-and-fall-back:
    `port` when it is 0 (asked for), already re-chosen for a KASTR squatter,
    or free; else the first free one after it (8000 -> 8001..8040, remembered
    by the caller); else 0 with a warning."""
    port = int(port)
    if port == 0 or squatter or port_is_free(port, host):
        return port
    start = 8001 if port == 8000 else port + 1
    moved = free_port(start, host)
    if moved:
        note("port %d is held by another program -- using %d (remembered in %s)" % (port, moved, PORT_MEMORY))
        return moved
    note("ports %d..%d all busy -- letting the OS pick (browser storage will not persist across launches)"
         % (port, start + 39))
    return 0


def supervise(proc, server):
    """Keep serving until the app window is really gone.

    proc.wait() alone is wrong. When a browser is already running with our
    profile it takes the URL and the process we spawned exits within seconds --
    which looked exactly like "the user closed the window", so the server tore
    itself down and the launch silently did nothing.

    So: a browser process that lived a while and then exited IS the window
    closing, and we return at once. A process that dies almost immediately was
    a hand-off, and the page's own heartbeat becomes the signal instead.
    """
    alive = getattr(server, "alive_ref", None)
    started = time.monotonic()
    profile = _ACTIVE_PROFILE or profile_dir()
    fell_back = False
    died_at = None

    while not STOP.is_set():
        time.sleep(0.5)
        if proc.poll() is None:
            continue                       # our browser is still running
        if died_at is None:
            died_at = time.monotonic()
            note("browser process exited after %.1fs" % (died_at - started))

        last = alive[0] if alive else 0.0

        if fell_back:
            # Serving without a window: the browser we launched could not
            # keep one open. If a page shows up later (the URL opened by
            # hand), its heartbeat re-enters the normal lifecycle below;
            # otherwise run until Ctrl+C / SIGTERM.
            if last and time.monotonic() - last > HEARTBEAT_GRACE:
                return
            continue

        # The browser died fast without ever heartbeating. On Windows that is
        # a hand-off to an existing browser holding the profile; on Linux it
        # is usually a display the process cannot USE even though $DISPLAY is
        # set -- root vs the session's Xauthority ("Authorization required,
        # but no authorization protocol specified", seen in the field),
        # Wayland-only sessions, snap confinement. Chrome never creates the
        # profile lock in that case, so browser_gone says so within a second.
        # Fall back to serving instead of tearing the server down under the
        # very URL the errors tell the user to open.
        if not WINDOWS and not last and browser_gone(profile):
            fell_back = True
            hint = ""
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                hint = ("\nRunning as root inside a desktop session usually "
                        "cannot open the display: run KASTR as the logged-in "
                        "user instead, or use --host 0.0.0.0 and open the "
                        "URL from another machine.")
            print(f"{APP_NAME}: the browser exited before opening a window. "
                  f"Still serving at http://127.0.0.1:{server.server_address[1]}"
                  + hint, flush=True)
            continue

        # 0.8.13: judged by how long the browser LIVED, not by how long we have
        # been supervising -- the old test returned at the 10 s mark in every
        # hand-off case too, which tore the server down under a window that
        # had just loaded, and made the dialog below unreachable.
        if died_at - started > HANDOFF_WINDOW:
            note("window closed (browser lived %.0fs)" % (died_at - started))
            return                         # long-lived process exited: real close

        if last:
            if time.monotonic() - last > HEARTBEAT_GRACE:
                note("page heartbeat stopped; exiting")
                return                     # page stopped pinging: really closed
        elif time.monotonic() - started > STARTUP_GRACE:
            nl = chr(10) + chr(10)
            note("no window: browser exited at once and no page ever pinged")
            alert_async(
                APP_NAME + " could not open its window." + nl
                + "This usually means a browser is already running with the "
                + APP_NAME + " profile. Close any existing " + APP_NAME
                + " window and try again, or open this address in a browser:" + nl
                + "http://127.0.0.1:%d" % server.server_address[1]
            )
            if WINDOWS:
                time.sleep(1.5)            # let the dialog appear before teardown
                return
            fell_back = True               # POSIX: stay up behind that URL



class GuiArgumentParser(argparse.ArgumentParser):
    """argparse that reports through a message box.

    Built with --noconsole, so the process has no stderr: the stock error path
    writes into the void and then exits, which looks like the app silently
    hanging or doing nothing. Surface it instead.
    """

    def error(self, message):
        alert(f"Bad command line:\n\n{message}\n\n{self.format_usage()}")
        sys.exit(2)

    def exit(self, status=0, message=None):
        if message:
            alert(message)
        sys.exit(status)


def build_parser(ini):
    """0.12.0: the launcher's command line, factored out of main() so a test can
    build it against a given ini dict (the defaults come from the ini)."""
    ap = GuiArgumentParser(add_help=True)
    ap.add_argument("--diagnose", metavar="FILE", default=None,
                    help="write resolved paths and effective config to FILE, then exit "
                         "(the app is windowed, so stdout goes nowhere)")
    ap.add_argument("--relay", default=None,
                    help="relay URL; default: last used (relay-use.json), "
                         "then kastr.ini, then the built-in")
    ap.add_argument("--port", type=int, default=int(ini.get("port", 8000)))
    ap.add_argument("--host", default=ini.get("host", "127.0.0.1"))
    ap.add_argument("--coep", choices=kastr_serve.COEP_MODES,
                    default=ini.get("coep", kastr_serve.COEP_MODES[0]))
    ap.add_argument("--page", default=ini.get("page", "/app.html"),
                    help="page to open, e.g. /moq-watch-lite.html")
    ap.add_argument("--no-browser", action="store_true",
                    help="serve only; don't open a window")
    ap.add_argument("--no-update", action="store_true",
                    help="skip the launch-time version match against the relay host")
    ap.add_argument("--relay-only", action="store_true",
                    help="relay-box mode: boot straight into the Relay Server "
                         "page and autostart the relay (also: mode = relay in kastr.ini)")
    # 0.12.0: four operating modes; absent = full (the 0.11 client). --relay-only
    # is the old spelling of --mode relay and wins when both are given.
    ap.add_argument("--mode", choices=kastr_serve.MODES, default=None,
                    help="operating mode: full (default) | viewer | publisher | relay | "
                         "publisher-relay (also: mode = ... in kastr.ini)")
    return ap


def main():
    ini, ini_path = read_ini()
    args = build_parser(ini).parse_args()   # 0.12.0: parser factored out (testable)

    # 0.8.3: the relay the user last pointed the app at wins over the ini
    # default -- "set it to the last used address on relaunch". An explicit
    # --relay flag still beats everything.
    if args.relay is None:
        last = None
        try:
            # utf-8-sig: BOM-tolerant, same as read_ini -- a hand-edited or
            # PowerShell-written file must not silently fall back to the ini.
            with open(os.path.join(state_dir(), "relay-use.json"),
                      encoding="utf-8-sig") as f:
                last = str(json.load(f).get("url") or "").strip() or None
        except Exception:
            pass
        args.relay = last or ini.get("relay", kastr_serve.DEFAULT_RELAY)

    # Relay-box mode (0.8.2): the machine exists to host the relay. Same
    # binary -- the fleet updater still applies -- but the window IS the
    # Relay page and the relay comes up on its own.
    # 0.12.0: four operating modes (see effective_mode). relay_only feeds the
    # five relay-box branches below unchanged for BOTH relay modes; only solo
    # (mode = relay) makes the window the Relay page.
    mode, relay_only, solo = effective_mode(args.mode, args.relay_only, ini)
    kastr_serve.MODE = mode   # 0.12.0: /api/instance + /api/mode report it
    if solo:
        args.page = "/relay.html?solo=1"
    if relay_only:
        # 0.8.3 relay-only booted to the Relay page but stayed on loopback --
        # so nobody could reach it and the fleet couldn't update from it. A
        # relay box exists to serve the LAN: bind all interfaces unless the
        # operator pinned a specific host in the ini. (The relay's own moq
        # bind and the firewall are handled at relay_autostart below.)
        if args.host in ("127.0.0.1", "localhost", "::1"):
            args.host = "0.0.0.0"

    root = site_root()

    global BROWSER_PREF
    BROWSER_PREF = str(ini.get("browser", "bundled") or "bundled")   # 0.9.0

    if args.diagnose:
        lines = [
            f"{APP_NAME} diagnostics",
            f"version        : {kastr_serve.read_version()}",
            f"frozen         : {FROZEN}",
            f"sys.executable : {sys.executable}",
            f"app_dir        : {app_dir()}",
            f"cwd            : {os.getcwd()}",
            f"site_root      : {root}",
            f"index.html     : {os.path.exists(os.path.join(root, 'index.html'))}",
            f"ini searched   : {config_paths()}",
            f"ini used       : {ini_path}",
            f"ini values     : {ini}",
            f"browser profile: {profile_dir(find_browser())}",
            f"effective relay: {args.relay}",
            f"effective port : {args.port}  host {args.host}  coep {args.coep}",
            f"effective mode : {mode}",   # 0.12.0
            f"browser        : {find_browser()}",
            f"browser pref   : {BROWSER_PREF}  bundled={bundled_browser()}",
        ]
        # 0.9.10: what the child registry holds and what the legacy sweep would end (list only)
        try:
            _kr = kastr_serve.kastr_rtsp
            lines.append("rtsp registry  : " + ("; ".join(_kr.registry_files(state_dir())) or "none"))
            orphans = _kr.helper_orphans(_kr.helper_roots())
            lines.append("helper orphans : " + ("; ".join("%s pid %s (%s)" % (o["name"], o["pid"], o["why"]) for o in orphans) or "none"))
        except Exception as e:
            lines.append(f"rtsp registry  : unavailable ({e})")
        # 0.13.0: what the running instance (if any) says about the pages on this
        # box -- feeds pulled (F2) and whether its chat origin is the shared store (F1)
        # 0.13.3: the running instance need not be on --port: the launcher writes
        # the port it bound to state_dir/http-port (removed at teardown), so a
        # plain `KASTR --diagnose out.txt` finds it too
        ports = [args.port]
        file_port = None
        try:
            with open(os.path.join(state_dir(), "http-port"), encoding="utf-8") as f:
                file_port = int((f.read() or "").strip())
        except (OSError, ValueError):
            file_port = None
        if file_port and file_port not in ports:
            ports.append(file_port)
        inst, inst_port = None, None
        for p in ports:
            try:
                inst = whoever_is_on(p)
            except Exception:
                inst = None
            if inst:
                inst_port = p
                break
        lines.append("http-port file : %s" % (file_port if file_port else "none"))
        lines.append("port memory    : %s" % port_memory_text())   # 0.14.0: state_dir/port.json
        if not inst:
            lines.append("instance       : none answering on port(s) %s" % ", ".join(str(p) for p in ports))
            lines.append("viewing        : unknown (no running instance)")
            lines.append("chatHub        : unknown (no running instance)")
        else:
            lines.append(f"instance       : {inst.get('url')}  version {inst.get('version')}  pid {inst.get('pid')}  mode {inst.get('mode')}"
                         + (" (port from http-port file)" if inst_port == file_port and inst_port != args.port else ""))
            v = inst.get("viewing")
            if isinstance(v, dict):
                lines.append(f"viewing        : {v.get('n')} feed(s) pulled by pages on this box ({v.get('ageS')} s ago)")
            else:
                lines.append("viewing        : unknown (no page reporting in the last 30 s)")
            ch = inst.get("chatHub")
            lines.append("chatHub        : " + ("yes -- chat on this origin is the fleet's shared store" if ch is True
                                                else "no -- chat here would be a private store" if ch is False
                                                else "unknown (pre-0.13 instance)"))
            # 0.13.1: the RTSP drop recipe -- every publisher's counters in one line each
            try:
                with urllib.request.urlopen(inst["url"] + "/api/rtsp/list", timeout=3) as r:
                    feeds = (json.loads(r.read().decode("utf-8", "replace")) or {}).get("feeds") or []
                pubs = [f for f in feeds if isinstance(f, dict) and f.get("publish")]
                if not pubs:
                    lines.append("rtsp publish   : none (%d feed(s) added, nothing published)" % len(feeds))
                for f in pubs:
                    p = f.get("publish") or {}
                    nd = p.get("nudges") or {}
                    le = p.get("lastExit") or {}
                    since = p.get("since")
                    lines.append("rtsp publish   : %s running=%s restarts=%s sessionFails=%s sessionKills=%s "
                                 "nudges=viewer:%s/noEcho:%s/api:%s lastNudgeWhy=%s lastExit=%s parked=%s lastSession=%s "
                                 "gen=%s total=%s since=%s"                     # 0.13.3: the generation timeline
                                 % (p.get("broadcast"), p.get("running"), p.get("restarts"),
                                    p.get("sessionFails"), p.get("sessionKills"),
                                    nd.get("viewer", 0), nd.get("noEcho", 0), nd.get("api", 0),
                                    p.get("lastNudgeWhy"),
                                    ("%s code %s after %s s" % (le.get("who"), le.get("code"), le.get("lived"))) if le else None,
                                    p.get("parked"), p.get("lastSession"),
                                    p.get("gen"), p.get("restartsTotal"),
                                    (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since)) if isinstance(since, (int, float)) else None)))
            except Exception as e:
                lines.append("rtsp publish   : unavailable (%s)" % e)
        with open(args.diagnose, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return 0

    # 0.13.1: a relaunched child waits for its parent to be gone before it
    # looks at the port (see relaunch_self / await_predecessor).
    relaunched = await_predecessor(args.port)
    updated = os.environ.get("KASTR_UPDATED") == "1"

    if not os.path.exists(os.path.join(root, "index.html")):
        alert(f"Web files are missing.\n\nExpected index.html in:\n{root}")
        return 1

    # 0.15.0: learn the hub's web port BEFORE the version match dials it -- what
    # earlier launches learned (hub-web.json) first, then a bounded probe (the
    # minter's /api/auth, else /api/instance on the stored/ini/8000.. ports).
    # Unconditional (not gated by --no-update: chat and peer lookups need it
    # too) and never longer than the probe budget.
    try:
        load_hub_web()
        learn_hub_web(args.relay, ini, once=True)
    except Exception as e:
        note("hub web port: learner skipped (%s)" % e)

    # Fleet version match (0.8.1): before anything binds or launches, adopt
    # the relay host's KASTR version if it differs. May not return (swaps
    # the binary and relaunches).
    try:   # 0.16.0: a launch-time relaunch tells its child which port to watch
        RELAUNCH_PORT_HINT[0] = int(args.port or 0) or int(_port_memory_read().get("port") or 0)
    except Exception:
        RELAUNCH_PORT_HINT[0] = 0
    if not args.no_update:
        upd = check_update(args.relay, ini)
        # 0.15.0: a relay box mirrors the authority's feed once the match settled
        mirror_after_update(args.relay, ini, upd)
    else:
        update_note("off", "--no-update flag")
    sweep_old_binaries()   # 0.8.7
    if updated:
        # 0.8.8: the old image may still be exiting -- retry later, from HERE,
        # so the .old file is gone after the relaunch, not at the next start.
        for _delay in (10, 60):
            _t = threading.Timer(_delay, sweep_old_binaries)
            _t.daemon = True
            _t.start()

    # Someone already on our port? Who it is decides what to do.
    #
    #   this same build   -> show its window; a second server here could never
    #                        open one anyway, because the browser profile is
    #                        already held by that instance.
    #   a different build -> stand aside and use another port. It used to
    #                        capture the launch, so double-clicking a 0.5.13 exe
    #                        while a source checkout served 8000 showed
    #                        0.5.13-dev -- the wrong program, silently.
    # 0.9.0: the bundled browser follows the fleet authority like the binary
    # does (after check_update, so a relaunch-as-new-version does it once).
    if not args.no_update and not args.no_browser and not solo:   # 0.12.0: a publisher-relay box runs the app page, so its browser follows the fleet too
        browser_update(args.relay, ini)

    # 0.14.0: the same port every launch -- see PORT_MEMORY. Decided before
    # the squatter check, so a running KASTR is looked for where this box lives.
    explicit, ephemeral = resolve_sticky_port(args, ini)

    squatter = whoever_is_on(args.port)
    if squatter and relaunched:
        # 0.13.1: our predecessor (or something else) still answers after the
        # relaunch wait -- never hand the window to it; take the next port.
        note("relaunch: KASTR %s (pid %s) still answers on port %d -- not handing over"
             % (squatter.get("version"), squatter.get("pid"), args.port))
    if squatter and same_build(squatter) and not args.no_browser and not relaunched:
        browser = find_browser()
        note("KASTR %s already on port %d (pid %s): handing the window over"
             % (squatter.get("version"), args.port, squatter.get("pid")))
        if browser:
            launch(browser, squatter["url"], args.page)
        else:
            note("no browser to hand the window to; the running instance is at " + squatter["url"])
        # 0.8.13: did the running instance actually get a window? Its page's
        # heartbeat age says so (/api/instance aliveAge). Before this the
        # launcher exited in silence whether or not anything appeared.
        ok = False
        for _ in range(16):
            time.sleep(0.5)
            inst = whoever_is_on(args.port)
            age = inst.get("aliveAge") if inst else None
            if age is not None and age < 4.0:
                ok = True
                break
        note("hand-off %s" % ("succeeded (window is pinging)" if ok else "FAILED: no heartbeat"))
        if not ok:
            alert_async(APP_NAME + " is already running (pid %s) but its window did not answer."
                        % squatter.get("pid") + chr(10) + chr(10)
                        + "Open " + squatter["url"] + " in a browser, or close the other "
                        + APP_NAME + " and start it again.", seconds=20.0)
        return 0
    if squatter:
        moved = free_port(args.port + 1, args.host) or 0   # 0.14.0: None = the range is full -> the OS picks
        print("port %d is held by KASTR %s%s -- using %s instead"
              % (args.port, squatter.get("version", "?"),
                 "" if squatter.get("frozen") else " (from source)", moved or "an OS-picked port"),
              flush=True)
        args.port = moved

    # 0.14.0: the port is chosen here (probe + memory), not by bind_free's
    # bind-then-fall-to-0 -- that fall-back is what cost the browser storage.
    bind_port = choose_bind_port(args.port, args.host, squatter)
    # 0.19.0: kastr.ini single_port = true -> every remote page dials this machine's /relay
    kastr_serve.SINGLE_PORT = str(ini.get("single_port") or "").strip().lower() in ("1", "true", "yes", "on")
    if kastr_serve.SINGLE_PORT:
        note("single_port: remote pages use this web port for media (/relay, WebSocket)")
    try:   # 0.18.0: host recording retention (kastr.ini archive_hours, default 24)
        kastr_serve.ARCHIVE_HOURS = float(ini.get("archive_hours") or 24)
    except (TypeError, ValueError):
        kastr_serve.ARCHIVE_HOURS = 24
    server_kw = dict(coep=args.coep, relay=args.relay, quiet=True,
                     bridge=kastr_serve.make_bridge(state_dir=state_dir(), log=note,   # 0.9.8
                                                    hostname=None),   # 0.13.0: = make_server's hostname
                     relay_srv=kastr_serve.make_relay(state_dir(), note),   # 0.10.0: relay events reach launch.log
                     window_file=window_file())
    # 0.18.0: operator hooks from kastr.ini (hook_ready / hook_notready / hook_read / hook_timeout)
    if any(ini.get(k) for k in ("hook_ready", "hook_notready", "hook_read")):
        try:
            server_kw["bridge"].hooks = kastr_rtsp.Hooks({e: ini.get("hook_" + e) for e in kastr_rtsp.HOOK_EVENTS},
                                                         note, ini.get("hook_timeout") or 30)
            note("hooks: %s set" % ", ".join(e for e in kastr_rtsp.HOOK_EVENTS if ini.get("hook_" + e)))
        except Exception as e:
            note("hooks: not set (%s)" % e)
    try:
        try:
            server = kastr_serve.make_server(root, args.host, bind_port, **server_kw)
        except OSError as e:
            if bind_port == 0:
                raise
            # the probe said free a moment ago and something took it since: the
            # one fall-back bind_free used to make, now logged
            note("port %d: bind failed after a free probe (%s) -- letting the OS pick" % (bind_port, e))
            server = kastr_serve.make_server(root, args.host, 0, **server_kw)
    except OSError as e:
        alert(f"Could not start the local server.\n\n{e}")
        return 1

    port = server.server_address[1]
    args.port = port   # 0.14.0: the LAN URLs printed further down read it
    if not explicit and not ephemeral and not squatter and port:
        port_remember(port, args.host, int(ini.get("port", 8000)))   # 0.14.0: next launch comes back here
    url = f"http://127.0.0.1:{port}"
    # 0.13.3: the live port on disk -- `--diagnose` (and a field tool) finds the
    # running instance without being told --port; teardown removes it
    try:
        with open(os.path.join(state_dir(), "http-port"), "w", encoding="utf-8") as f:
            f.write(str(port))
    except OSError as e:
        note("could not write http-port: %s" % e)
    # 0.8.10: shared-file storage and LAN naming no longer need a hosted relay
    kastr_serve.STATE_DIR = state_dir()
    kastr_serve.HTTP_PORT = port
    import kastr_relay as _kr_web      # main() imports kastr_relay locally further down, so bind the name here too
    _kr_web.WEB_PORT = port              # 0.14.0 F: the token service advertises it on /api/auth
    kastr_serve.LAN_OK = args.host not in ("127.0.0.1", "localhost", "::1")
    kastr_serve.start_media_sweeper(state_dir())   # 0.8.13: converted media has a shelf life
    note("serving %s (host %s, relay %s, version %s)" % (url, args.host, args.relay, kastr_serve.read_version()))

    # 0.8.9: phones. When the web host is reachable from the LAN, also serve
    # the same site over HTTPS with a certificate from this install's own CA
    # (kastr_tls); the relay gets the same leaf for its wss listener. Off with
    # `https = off` in kastr.ini.
    tls_server = None
    if (args.host not in ("127.0.0.1", "localhost", "::1")
            and str(ini.get("https", "")).lower() not in ("off", "false", "0", "no")):
        try:
            import kastr_tls
            import kastr_relay as _kr
            # 0.17.0: the operator's certificate (kastr.ini tls_cert/tls_key) when given,
            # else the local CA; tls_hostname / web_names / <hostname>.local join the SANs
            tls = kastr_tls.resolve(state_dir(), _kr.local_ips(), ini, note)
            if tls:
                https_port = int(ini.get("https_port", 8443))
                relay_obj = getattr(server, "relay", None)
                if relay_obj is not None:
                    relay_obj.tls = tls
                tls_server = kastr_serve.make_tls_server(
                    root, args.host, https_port, tls, coep=args.coep, quiet=True,
                    bridge=server.rtsp, relay_srv=relay_obj,
                    relay_ref=server.relay_ref, alive_ref=server.alive_ref,
                    window_file=window_file())
                threading.Thread(target=tls_server.serve_forever, daemon=True).start()
                kastr_serve.HTTPS_INFO.update(port=tls_server.server_address[1],
                                              fingerprint=tls["fingerprint"],
                                              ca=tls["ca_crt"], names=tls["names"],
                                              trust=tls.get("source") or "local-ca", hostname=tls.get("hostname"),
                                              expires=tls.get("expires"), error=None)   # 0.17.0
                _EXTRA_SERVERS.append(tls_server)
                _kr._FIREWALL_HTTPS_PORT = tls_server.server_address[1]
                _kr.HTTPS_PORT = tls_server.server_address[1]     # 0.15.0: /api/auth advertises it
                print(f"{APP_NAME}: https on {args.host}:{tls_server.server_address[1]} "
                      f"({tls.get('source', 'local-ca')} {tls['fingerprint'][:12]}...)", flush=True)
                note("tls: https on :%d (%s%s, expires %s)" % (tls_server.server_address[1], tls.get("source") or "local-ca",
                                                                 (" for " + tls["hostname"]) if tls.get("hostname") else "", tls.get("expires") or "?"))
                dl = kastr_tls.days_left(tls)
                if dl is not None and dl <= 14:
                    note("tls: certificate expires in %d days" % dl)

                # 0.17.0: ONE daily check, no watcher -- a swapped operator certificate (certbot,
                # win-acme write into the tls_* paths) or a new LAN address is picked up within a day:
                # the https listener reloads its chain, the relay restarts once for its wss listener.
                def _tls_tick(_tls=[tls], _srv=tls_server, _relay=relay_obj):
                    new = kastr_tls.resolve(state_dir(), _kr.local_ips(), read_ini(), note)
                    if not new:
                        return
                    dl2 = kastr_tls.days_left(new)
                    if dl2 is not None and dl2 <= 14:
                        note("tls: certificate expires in %d days" % dl2)
                    if new.get("stamp") == _tls[0].get("stamp"):
                        return
                    kastr_serve.reload_tls(_srv, new)
                    kastr_serve.HTTPS_INFO.update(fingerprint=new["fingerprint"], ca=new["ca_crt"], names=new["names"],
                                                  trust=new.get("source") or "local-ca", hostname=new.get("hostname"),
                                                  expires=new.get("expires"))
                    _tls[0] = new
                    note("tls: certificate changed (%s, expires %s) -- https reloaded%s"
                         % (new.get("source") or "local-ca", new.get("expires") or "?",
                            ", relay restarting for its wss listener" if (_relay is not None and _relay.running()) else ""))
                    if _relay is not None:
                        _relay.tls = new
                        if _relay.running():
                            try:
                                _relay.restart()
                            except Exception as e:
                                note("tls: relay restart after certificate change failed: %s" % e)
                start_update_sweeper(_tls_tick, every=86400, label="tls: daily certificate check")
        except Exception as e:
            print(f"{APP_NAME}: https listener not started: {e}", flush=True)
            kastr_serve.HTTPS_INFO["error"] = str(e)[:200]   # 0.17.0: the Relay page shows why 8443 is down

    # 0.8.6: on-demand fleet update (relay switch / "Check for updates"). The
    # hook tears the live server down before the relaunch so the ports are
    # free for the new version; the browser window closes with it.
    proc_ref = [None]
    # 0.15.0: the feed port is resolved per host when needed (update_port_for:
    # ini update_port > learned hub web port > 8000), no longer fixed at launch
    # 0.8.8: close the window FIRST (cooperatively, then by force), then the
    # server -- the relaunch must find no window holding the profile.
    # 0.13.1: `grace` = the cooperative window-close budget (a mode switch
    # needs less than an update), `code` = the exit code (75 in a container).
    def _before_exit(grace=3.0, code=0):
        try:
            close_app_window(_ACTIVE_PROFILE or profile_dir(browser), proc_ref[0], grace=grace)
        except Exception:
            pass
        teardown(server, proc_ref[0], code)
    def _current_relay():
        try:
            return (getattr(server, "relay_ref", None) or [None])[0] or args.relay
        except Exception:
            return args.relay

    def _update_hook(host):
        # 0.16.0: a switched-to relay's web port is learned BEFORE the check dials it
        try:
            learn_hub_web_host(host, _current_relay(), ini)
        except Exception as e:
            note("hub web port: learner skipped for %s (%s)" % (host, e))
        return runtime_update(host, authority_base(host, ini, _current_relay()), before_exit=_before_exit)   # 0.19.0
    kastr_serve.UPDATE_HOOK = _update_hook
    # 0.8.9: the Relay page's "Apply & relaunch" (relay-only mode switch).
    # 0.13.1: reason "mode" -- direct spawn, no KASTR_UPDATED, the child waits for us.
    kastr_serve.RELAUNCH_HOOK = lambda: relaunch_self(500, lambda code=0: _before_exit(1.5, code),
                                                      argv=mode_relaunch_argv(), reason="mode")
    # 0.9.8: POST /api/quit ends KASTR the same way closing the window does
    def _quit_hook():
        note("stop requested via /api/quit")
        STOP.set()
    kastr_serve.QUIT_HOOK = _quit_hook
    # 0.11.0: a spoke relay's KASTR keeps matching the federation master hourly
    # (relay-host boxes never relaunch otherwise); clients still match their
    # relay host at launch.
    # 0.15.0: the same tick keeps a relay box's mirrored feed current (hourly,
    # a manifest GET + hash compare when nothing changed).
    def _federation_update():
        hub, master = federation_master()
        st = "current"
        if hub and master and hub not in ("127.0.0.1", "localhost", "::1"):
            note("federation master: hourly version match against %s" % hub)
            st = (runtime_update(hub, authority_base(hub, ini, args.relay), before_exit=_before_exit) or {}).get("status")   # 0.19.0
        mirror_after_update(args.relay, ini, st, relay=getattr(server, "relay", None))
    if not args.no_update:
        start_update_sweeper(_federation_update)
    # 0.15.0: re-learn the hub's web port every 5 minutes (a hub relaunched on
    # another port is followed without a restart here)
    start_update_sweeper(lambda: learn_hub_web(_current_relay(), ini), every=300, label="hub web port: learner")   # 0.16.0: the CURRENT relay

    threading.Thread(target=server.serve_forever, daemon=True).start()

    # Relay autostart (0.8.0): the Relay page's checkbox writes
    # relay-autostart.json; the ini key relay_autostart=true is the hand-
    # edited fallback. On a thread -- Relay.start blocks up to ~6s and the
    # window should not wait for it.
    def relay_autostart():
        import kastr_relay
        r = getattr(server, "relay", None)
        if not r:
            return
        cfg = r.autostart_config()
        if (not cfg.get("enabled") and not relay_only
                and str(ini.get("relay_autostart", "")).lower() not in ("1", "true", "yes")):
            return
        rport = cfg.get("port") or 4443
        # A relay-only box exists to serve the LAN, so the moq-relay binds all
        # interfaces regardless of the saved checkbox (0.8.4); a normal
        # autostart honours the operator's lan choice.
        lan = True if relay_only else bool(cfg.get("lan"))
        try:
            r.start(rport, lan, bool(cfg.get("secured")))
            print(f"{APP_NAME}: relay autostarted on port {rport}"
                  f"{' (LAN)' if lan else ''}", flush=True)
        except Exception as e:
            print(f"{APP_NAME}: relay autostart failed: {e}", flush=True)
        # 0.8.4: make the box reachable so the fleet can update from it --
        # check first, prompt (once) only when a rule is actually missing.
        # Windows raises one UAC prompt; Linux uses pkexec on a desktop or
        # prints a sudo line on a headless robot box.
        if relay_only:
            try:
                if not kastr_relay.firewall_status().get("present"):
                    kastr_relay._FIREWALL_WEB_PORT = port
                    kastr_relay._FIREWALL_DIR = state_dir()
                    kastr_relay.add_firewall_rules(rport)
            except Exception as e:
                print(f"{APP_NAME}: firewall setup skipped: {e}", flush=True)
    threading.Thread(target=relay_autostart, daemon=True).start()

    # 0.12.0: publishers that heal -- the feeds the last run left on air come
    # back into their room without a page. rtsp-feeds.json (Bridge.persist_feeds)
    # holds room + access code + feeds; wait for the relay (own autostart or a
    # remote one) to answer, mint a room token from the saved code, republish.
    def feeds_restore():
        try:
            if str(ini.get("mode", "")).strip().lower() == "viewer":
                return
            bridge = getattr(server, "rtsp", None)
            if bridge is None:
                return
            _kr = kastr_serve.kastr_rtsp
            path = os.path.join(state_dir(), "rtsp-feeds.json")
            try:
                with open(path, encoding="utf-8-sig") as f:
                    doc = json.load(f)
            except Exception:
                return
            if not isinstance(doc, dict):
                return
            room = str(doc.get("room") or "").strip().lower()
            feeds = [x for x in (doc.get("feeds") or []) if isinstance(x, dict) and x.get("url") and x.get("keep", True)]
            if not room or not feeds:
                return
            access = str(doc.get("access") or "")
            room_code = str(doc.get("roomCode") or "")
            relay = str(doc.get("relay") or "").strip() or _kr._relay_key(args.relay)
            status, url, detail = "down", None, "not tried"
            deadline = time.time() + 60
            # 0.13.2: "open" with "no minter" four seconds after OUR relay started means the token
            # service is still coming up, not that the relay is open -- Southridge republished five
            # feeds bare into its own secured relay and every pair parked on "unauthorized". While the
            # hosted relay reports secured, keep waiting for a real answer (token / refused).
            def _own_secured():
                try:
                    rs = getattr(server, "relay", None)
                    st = rs.status() if rs else {}
                    return bool(st.get("running")) and bool(st.get("secured")) and _kr._relay_key(relay) == _kr._relay_key(str(st.get("url") or ""))
                except Exception:
                    return False
            while True:
                status, url, detail = _kr.mint_member(relay, room, access, room_code, host=getattr(bridge, "host_slug", None))   # 0.13.0: identity-scoped token
                if status == "open" and "no minter" in str(detail) and _own_secured() and time.time() < deadline:
                    status, detail = "down", "own secured relay: minter not answering yet"
                if status != "down" or STOP.is_set() or time.time() >= deadline:
                    break
                time.sleep(1.0)
            if status == "refused":
                note("rtsp restore: the relay refused the saved access code for room %s -- feeds stay parked until someone joins" % room)
                try:
                    with open(path, encoding="utf-8-sig") as f:
                        doc = json.load(f)
                    doc["restoreError"] = "the relay refused the saved access code (%s)" % detail
                    tmp = path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(doc, f)
                    os.replace(tmp, path)
                except Exception:
                    pass
                return
            if status == "down":
                note("rtsp restore: relay %s did not answer within 60 s (%s) -- %d feed(s) not republished" % (relay, detail, len(feeds)))
                return

            def mint():
                st, u, _d = _kr.mint_member(relay, room, access, room_code, host=getattr(bridge, "host_slug", None))
                return u if st in ("open", "token") else None
            n = bridge.restore(mint=mint, log=note)
            note("rtsp restore: %d of %d persisted feed(s) republished into room %s (relay %s, %s)" % (n, len(feeds), room, relay, status))
        except Exception as e:
            note("rtsp restore failed: %s" % e)
    threading.Thread(target=feeds_restore, daemon=True).start()

    # From here on the server owns child processes, so every exit must go
    # through teardown() -- including the ones that are not returns at all.
    proc = None

    def request_stop(signum, _frame):
        STOP.set()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, request_stop)
            except (ValueError, OSError):
                pass        # not deliverable here; the watchdog still covers us

    watch_parent()

    try:
        if args.no_browser:
            print(f"{APP_NAME} serving {root}\n  {url}  relay {args.relay}\nCtrl+C to stop.", flush=True)
            while not STOP.wait(1.0):
                pass
            return 0

        # Headless Linux (robot boxes, SSH sessions, root shells without the
        # desktop's environment): Chromium starts and immediately dies with
        # "Missing X server or $DISPLAY", and a window that never heartbeats
        # would take the server down with it. Serve without a window instead
        # -- on such a machine the UI is meant to be opened from elsewhere.
        if (sys.platform.startswith("linux")
                and not os.environ.get("DISPLAY")
                and not os.environ.get("WAYLAND_DISPLAY")):
            print(f"{APP_NAME}: no display on this machine (no $DISPLAY / "
                  "$WAYLAND_DISPLAY) -- serving without a window.", flush=True)
            if args.host in ("127.0.0.1", "localhost"):
                print("Bound to 127.0.0.1, so only this machine can reach the "
                      "UI. To use it from another computer, restart with:\n"
                      "  ./KASTR --host 0.0.0.0\n"
                      "(or set host in kastr.ini).", flush=True)
                print(f"  {url}  relay {args.relay}", flush=True)
            else:
                import kastr_relay
                print("Open the UI from another machine:", flush=True)
                for ip in kastr_relay.local_ips():
                    print(f"  http://{ip}:{args.port}", flush=True)
                print(f"  relay {args.relay}", flush=True)
            print("Ctrl+C to stop.", flush=True)
            while not STOP.wait(1.0):
                pass
            return 0

        browser = find_browser()
        if not browser:
            # 0.9.3: say so and stay up. (This used to hand the URL to the OS
            # default browser, which cannot run KASTR.)
            note("no browser: the bundled one is missing or unusable and no system Chromium was found")
            alert_until_stop(no_window_message(
                url, "the bundled browser is missing or unusable and no Chrome, Chromium or Edge was found"))
            return 0

        if updated or relaunched:   # 0.13.1: a mode switch too (cheap when the window already closed)
            # 0.8.8: a relaunch must not hand its URL to the OLD window (Chrome
            # would, if it still held the profile): wait for it to go, then
            # insist once.
            _prof = profile_dir(browser)
            _t0 = time.monotonic()
            while time.monotonic() - _t0 < 10.0 and not browser_gone(_prof):
                time.sleep(0.25)
            if not browser_gone(_prof):
                try:
                    if not _browser_pids_for(_prof):
                        # 0.8.13: nobody holds the profile -- the lock is the
                        # leftover of a hard-killed browser. Remove it, or every
                        # relaunch burns the full 10 s wait forever.
                        os.remove(os.path.join(_prof, "lockfile"))
                        note("removed stale browser-profile lockfile")
                    else:
                        close_app_window(_prof, None, grace=0.5)
                except Exception:
                    pass
            # 0.8.13: CLOSING addressed the OLD window. Left set, the new
            # window's first heartbeat got 205 and it closed itself -- the app
            # "never fully opened" after an update.
            kastr_serve.CLOSING[0] = False
        proc = launch(browser, url, args.page)
        proc_ref[0] = proc
        if proc is None:
            alert_until_stop(no_window_message(url, LAUNCH_ERROR[0] or "the browser exited at once"))
            return 0

        supervise(proc, server)
        return 0
    finally:
        # Ends the process. Nothing after this runs, which is the point:
        # a half-torn-down KASTR holding its port is what this exists to stop.
        teardown(server, proc)


if __name__ == "__main__":
    sys.exit(main())
