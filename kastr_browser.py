# -*- coding: utf-8 -*-
"""kastr_browser.py -- the Chromium KASTR ships with (0.9.0).

KASTR's app window needs a Chromium engine (WebCodecs, WebTransport,
MediaStreamTrackProcessor, getDisplayMedia). Until 0.9.0 it borrowed whatever
Chrome or Edge the machine had: a moving target that auto-updated under the
app, held its profile hostage when a launch was force-killed, and simply was
not there on a fresh box. Now a pinned Google "Chrome for Testing" build lives
in `browser/` next to the KASTR binary, with its own profile.

Shared by build.py / fetch-helpers.py (download, verify, stage into dist) and
kastr.py (find it, keep it current from the fleet authority, migrate the old
profile's settings). Everything here is best-effort and loud in the log; the
launcher falls back to a system browser when the bundled one is unusable.
"""
import hashlib
import json
import os
import shutil
import stat
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PIN_FILE = os.path.join(HERE, "browser.json")
VERSION_FILE = "VERSION"            # inside browser/: the pinned version staged there
PLATFORMS = ("windows", "linux")    # the two KASTR ships; macOS keeps the system browser
API_KEY = {"windows": "win32", "linux": "linux"}   # sys.platform names used by the update feed

# 0.9.3: files that must be executable on Linux. The release zip and a bare
# unzip both lose modes -- unpacked 0644, chrome cannot start and the app fell
# back to the OS default browser (Firefox, which cannot run KASTR). build.py's
# zip_entry marks these 0755 in the archive and prepare() chmods them on launch.
EXECUTABLES = ("chrome", "chrome.exe", "chrome_sandbox", "chrome_crashpad_handler",
               "chrome-wrapper", "xdg-mime", "xdg-settings")

# 0.9.3: what a KASTR window never uses, per platform, deleted after every
# extraction (build staging, fleet update) and once on launch for an install
# that predates the list. locales/ keeps en-US.pak only (the launcher passes
# --lang=en-US). Roughly 90 MB (Windows) / 70 MB (Linux) per install.
PRUNE_TAG = "pruned 1"        # second line of browser/VERSION; bump it to re-prune every install
PRUNE = {
    "windows": ("setup.exe", "elevated_tracing_service.exe", "elevation_service.exe",
                "chrome_pwa_launcher.exe", "notification_helper.exe", "chrome_proxy.exe",
                "dxcompiler.dll", "dxil.dll", "hyphen-data", "IwaKeyDistribution", "debug.log"),
    "linux": ("WidevineCdm", "hyphen-data", "MEIPreload", "xdg-mime", "xdg-settings",
              "product_logo_48.png", "rpm.deps", "deb.deps"),
}
KEEP_LOCALES = ("en-US.pak",)


def platform_name():
    return "windows" if sys.platform == "win32" else ("macos" if sys.platform == "darwin" else "linux")


def load_pin(path=PIN_FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cache_dir():
    """Where downloaded zips live -- outside the source tree."""
    env = os.environ.get("KASTR_BROWSER_CACHE")
    if env:
        return env
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "ASI", "kastr-build", "browser")
    return os.path.join(os.path.expanduser("~"), ".cache", "kastr-build", "browser")


def zip_path(plat, pin):
    return os.path.join(cache_dir(), "zips", "chrome-%s-%s.zip" % (pin["platforms"][plat]["key"], pin["version"]))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_zip(plat, pin, download=True, log=print):
    """The pinned zip for `plat`, verified. Downloads it into the cache when missing."""
    info = pin["platforms"][plat]
    dest = zip_path(plat, pin)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) == info["size"] and sha256_file(dest) == info["sha256"]:
        return dest
    if not download:
        raise FileNotFoundError("browser zip for %s not in cache (%s)" % (plat, dest))
    log("  downloading Chrome for Testing %s (%s, %.0f MB)" % (pin["version"], plat, info["size"] / 1e6))
    tmp = dest + ".part"
    req = urllib.request.Request(info["url"], headers={"User-Agent": "kastr-fetch"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != info["sha256"] or os.path.getsize(tmp) != info["size"]:
        os.remove(tmp)
        raise RuntimeError("Chrome for Testing %s download for %s did not match browser.json (sha256/size)" % (pin["version"], plat))
    os.replace(tmp, dest)
    return dest


def extract_zip(zip_file, dest_dir, plat, pin, log=print):
    """Unpack chrome-<key>/... into dest_dir (root folder stripped), restoring
    the Unix modes zipfile drops, and stamp VERSION. dest_dir is replaced."""
    info = pin["platforms"][plat]
    root = info["root"] + "/"
    tmp = dest_dir + ".new"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    with zipfile.ZipFile(zip_file) as z:
        for zi in z.infolist():
            if not zi.filename.startswith(root) or zi.filename == root:
                continue
            rel = zi.filename[len(root):]
            if not rel or ".." in rel.split("/"):
                continue
            target = os.path.join(tmp, *rel.split("/"))
            if zi.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(zi) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            mode = (zi.external_attr >> 16) & 0o7777
            if mode and sys.platform != "win32":
                try:
                    os.chmod(target, mode)
                except OSError:
                    pass
    if sys.platform != "win32":
        ensure_exec(tmp)        # belt and braces: executable whatever the zip said
    with open(os.path.join(tmp, VERSION_FILE), "w", encoding="utf-8", newline="\n") as f:
        f.write(pin["version"] + "\n")
    prune(tmp, plat, log=log)   # 0.9.3
    swap_in(dest_dir, tmp)
    ensure_windows_acl(dest_dir, log=log)
    log("  browser %s -> %s" % (pin["version"], dest_dir))
    return dest_dir


def ensure_windows_acl(browser_dir, log=print):
    """Windows: Chrome's sandboxed processes (network service, renderers) run
    in AppContainers, and a bare unzip leaves the folder without the ACL
    entries the installer would add -- the browser window opens but logs
    "Sandbox cannot access executable" and never loads a page (seen 2026-09-10
    with the first bundled build). Grant ALL APPLICATION PACKAGES and ALL
    RESTRICTED APPLICATION PACKAGES read+execute when missing. Owner-level
    change, no elevation. Checked every launch: ACLs do not travel in a zip."""
    if sys.platform != "win32":
        return True
    import subprocess
    exe = os.path.join(browser_dir, "chrome.exe")
    if not os.path.exists(exe):
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(["icacls", exe], capture_output=True, text=True, timeout=30, creationflags=flags)
        if "ALL APPLICATION PACKAGES" in (r.stdout or "") and "ALL RESTRICTED APPLICATION PACKAGES" in (r.stdout or ""):
            return True
        r = subprocess.run(["icacls", browser_dir, "/grant", "*S-1-15-2-1:(OI)(CI)(RX)",
                            "*S-1-15-2-2:(OI)(CI)(RX)", "/T", "/Q"],
                           capture_output=True, text=True, timeout=180, creationflags=flags)
        ok = r.returncode == 0
        log("browser: sandbox ACL %s on %s%s" % ("granted" if ok else "NOT granted", browser_dir,
                                                  "" if ok else " -- " + (r.stderr or r.stdout or "").strip()[:200]))
        return ok
    except Exception as e:
        log("browser: sandbox ACL check failed (%s)" % e)
        return False


def ensure_exec(browser_dir):
    """POSIX: set the exec bits on the browser's executables (0.9.3)."""
    if sys.platform == "win32":
        return
    for name in EXECUTABLES:
        p = os.path.join(browser_dir, name)
        if not os.path.exists(p):
            continue
        try:
            st = os.stat(p)
            if not st.st_mode & stat.S_IXUSR:
                os.chmod(p, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass


def prune(browser_dir, plat, log=print):
    """Delete the parts of Chrome for Testing a KASTR window never uses (0.9.3)
    and mark browser/VERSION so it is not repeated. Idempotent, best-effort;
    returns bytes freed. The marker is written only when nothing failed, so a
    file held open by a running browser is retried on the next launch."""
    freed = 0
    failed = 0

    def size_of(p):
        if os.path.isdir(p) and not os.path.islink(p):
            return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(p) for f in fs)
        return os.path.getsize(p)

    def zap(p):
        nonlocal freed, failed
        try:
            n = size_of(p)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            freed += n
        except OSError:
            failed += 1

    for name in PRUNE.get(plat, ()):
        p = os.path.join(browser_dir, name)
        if os.path.lexists(p):
            zap(p)
    loc = os.path.join(browser_dir, "locales")
    if os.path.isdir(loc):
        for fn in os.listdir(loc):
            if fn not in KEEP_LOCALES:
                zap(os.path.join(loc, fn))
    ver = installed_version(browser_dir)
    if ver and not failed:
        try:
            with open(os.path.join(browser_dir, VERSION_FILE), "w", encoding="utf-8", newline="\n") as f:
                f.write(ver + "\n" + PRUNE_TAG + "\n")
        except OSError:
            pass
    if freed or failed:
        log("  browser: pruned %.0f MB of unused Chrome (%s)%s"
            % (freed / 1e6, plat, "" if not failed else " -- %d item(s) still held; retried next launch" % failed))
    return freed


def is_pruned(browser_dir):
    try:
        with open(os.path.join(browser_dir, VERSION_FILE), encoding="utf-8") as f:
            lines = [ln.strip() for ln in f.read().splitlines()]
        return len(lines) > 1 and lines[1] == PRUNE_TAG
    except OSError:
        return False


def prepare(app_dir, log=print):
    """Everything the bundled browser needs before a launch; returns its path or None.

    0.9.3: on POSIX the executables are chmod +x'd and VERIFIED -- a browser
    that cannot be executed is reported and skipped (system browser next),
    instead of Popen failing and the launcher opening the OS default browser.
    An unpruned folder (an install that predates the list) is pruned here."""
    exe = bundled_exe(app_dir)
    if not exe:
        return None
    bdir = os.path.dirname(exe)
    if sys.platform == "win32":
        ensure_windows_acl(bdir, log=log)
    else:
        ensure_exec(bdir)
        if not os.access(exe, os.X_OK):
            log("browser: %s is not executable and could not be made so -- using a system browser" % exe)
            return None
    if not is_pruned(bdir):
        prune(bdir, platform_name(), log=log)
    return exe


def swap_in(dest_dir, new_dir):
    """browser -> browser.old-<ts>, browser.new -> browser. The .old folder is
    swept later (a running browser may still hold files in it)."""
    if os.path.isdir(dest_dir):
        aside = dest_dir + ".old-%d" % int(time.time())
        os.rename(dest_dir, aside)
    os.rename(new_dir, dest_dir)


def sweep_old(app_dir):
    """Delete browser.old-* folders left by earlier swaps (best-effort)."""
    try:
        names = os.listdir(app_dir)
    except OSError:
        return
    for fn in names:
        if fn.startswith("browser.old-"):
            shutil.rmtree(os.path.join(app_dir, fn), ignore_errors=True)


def installed_version(browser_dir):
    """First line of browser/VERSION (the second, when present, is the 0.9.3 prune marker)."""
    try:
        with open(os.path.join(browser_dir, VERSION_FILE), encoding="utf-8") as f:
            return (f.read().splitlines() or [""])[0].strip() or None
    except OSError:
        return None


def bundled_exe(app_dir, plat=None):
    """Path of the bundled browser binary next to the app, or None."""
    plat = plat or platform_name()
    exe = {"windows": "chrome.exe", "linux": "chrome"}.get(plat)
    if not exe:
        return None
    p = os.path.join(app_dir, "browser", exe)
    return p if os.path.exists(p) else None


def is_bundled(browser_path, app_dir):
    try:
        return os.path.normcase(os.path.abspath(browser_path)).startswith(
            os.path.normcase(os.path.abspath(os.path.join(app_dir, "browser"))) + os.sep)
    except Exception:
        return False


def stage(dist_dir, plat, pin, log=print, download=True):
    """dist/<plat>/browser holds the pinned version (extract from the cache when not)."""
    browser_dir = os.path.join(dist_dir, "browser")
    if installed_version(browser_dir) == pin["version"] and bundled_exe(dist_dir, plat):
        log("  browser %s already staged in %s" % (pin["version"], browser_dir))
        if not is_pruned(browser_dir):
            prune(browser_dir, plat, log=log)   # 0.9.3: a folder staged before the prune list
        return browser_dir
    zf = ensure_zip(plat, pin, download=download, log=log)
    return extract_zip(zf, browser_dir, plat, pin, log=log)


def migrate_profile(old_profile, new_profile, log=print):
    """First launch of the bundled browser: carry the page's localStorage (name,
    rooms, relay history, layout choices) over from the profile the system
    browser used. Only that -- the rest of a profile is engine-version bound."""
    src = os.path.join(old_profile, "Default", "Local Storage")
    if not os.path.isdir(src):
        return False
    dst = os.path.join(new_profile, "Default", "Local Storage")
    if os.path.exists(dst):
        return False
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copytree(src, dst)
        log("browser profile: carried localStorage over from %s" % old_profile)
        return True
    except Exception as e:
        log("browser profile: could not carry localStorage over (%s)" % e)
        return False


def fetch_update(base, app_dir, plat, note, timeout=60):
    """Fleet update of the browser folder (0.9.0): ask the authority's manifest
    for its browser version; when ours differs (or is missing), download that
    zip from /api/update/browser?platform=, verify, unpack, swap. Never raises."""
    try:
        with urllib.request.urlopen(base + "/api/update/manifest", timeout=5) as r:
            man = json.load(r)
    except Exception as e:
        note("browser update: manifest fetch failed from %s (%s)" % (base, e))
        return "unreachable"
    b = man.get("browser") or {}
    theirs = str(b.get("version") or "")
    info = (b.get("platforms") or {}).get(API_KEY.get(plat, plat))
    mine = installed_version(os.path.join(app_dir, "browser"))
    if not theirs or not info:
        note("browser update: the authority offers no browser for %s" % plat)
        return "none"
    if theirs == mine:
        return "current"
    note("browser update: %s -> %s from %s" % (mine or "none", theirs, base))
    tmp = os.path.join(app_dir, "browser.download.zip")
    try:
        h = hashlib.sha256()
        got = 0
        total = int(info.get("size") or 0)
        with urllib.request.urlopen(base + "/api/update/browser?platform=" + API_KEY.get(plat, plat),
                                    timeout=timeout) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                f.write(chunk)
                got += len(chunk)
        if h.hexdigest() != info.get("sha256") or (total and got != total):
            raise RuntimeError("browser zip did not match the manifest (sha256/size)")
        # the zip's root folder name comes from the manifest ("chrome-win64" etc.)
        pin = {"version": theirs, "platforms": {plat: {"root": info.get("root") or ("chrome-win64" if plat == "windows" else "chrome-linux64"),
                                                       "exe": "chrome.exe" if plat == "windows" else "chrome"}}}
        extract_zip(tmp, os.path.join(app_dir, "browser"), plat, pin, log=note)
        note("browser update: now %s" % theirs)
        return "updated"
    except Exception as e:
        note("browser update: FAILED (%s) -- keeping %s" % (e, mine or "the system browser"))
        return "failed"
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
