"""KASTR 0.21.7: assemble the full install zip on a running host.

Every installed KASTR already carries what a release zip holds: its own binary, its
own pruned browser folder and, when it serves a fleet, the other platform's binary
and browser zip under updates/ (build.py co-locates them, kastr.mirror_feeds keeps
them current). The release zips themselves were never shipped to installed boxes
(300+ MB each), so a web client had nothing to download. This module rebuilds the
zip build.py would have written -- same entry names, same modes -- from those parts,
caches it under <state>/downloads/ and hands it to /api/update/zip.

The one thing a host must NOT ship is its own edited kastr.ini: the template (and
the Linux extras README.txt / install.sh / kastr.svg) travel in the feed as
updates/<plat>/extras/ (build.py publish_feed + colocate_feeds, mirrored by
kastr.mirror_feeds), and the assembler reads them from there.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import zipfile

import kastr_browser

APP = "KASTR"
# API platform key -> (zip root folder, binary name, browser zip key, browser prune key)
PLATFORMS = {
    "win32": {"dir": "windows", "binary": "KASTR.exe", "bkey": "win64", "prune": "windows"},
    "linux": {"dir": "linux", "binary": "KASTR", "bkey": "linux64", "prune": "linux"},
}
EXTRAS = {
    "win32": ("kastr.ini",),
    "linux": ("kastr.ini", "README.txt", "install.sh", "kastr.svg"),
    "darwin": ("kastr.ini",),
}
EXTRA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ZIP_NAME = "%s-%s-v%s.zip"          # KASTR-windows-v0.21.7.zip (= build.archive_name)
ESTIMATE = {"win32": 390 << 20, "linux": 420 << 20}   # shown before the first assembly

_lock = threading.Lock()
_building = {}                      # plat -> {"at": t, "thread": Thread}
_log = [print]


def set_log(fn):
    _log[0] = fn


def zip_name(plat, version):
    return ZIP_NAME % (APP, PLATFORMS[plat]["dir"], version)


def own_platform():
    return "win32" if sys.platform == "win32" else "darwin" if sys.platform == "darwin" else "linux"


def app_root():
    """The install folder (beside the binary). KASTR_RELEASE_ROOT overrides it for a source checkout's rig."""
    env = os.environ.get("KASTR_RELEASE_ROOT")
    if env and os.path.isdir(env):
        return env
    return os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))


def extras_dir(root, plat):
    return os.path.join(root, "updates", PLATFORMS.get(plat, {}).get("dir", plat), "extras")


def sources(plat, version, root=None, own=None, frozen=None):
    """What this install can assemble a `plat` zip from, or (None, why).

    root: the install folder (beside the binary). own: this box's platform key.
    Returns a dict {binary, binary_version, browser_dir | browser_zip, browser_version,
    extras: {name: path}, others: [(plat, binary, version)]}."""
    root = root or app_root()
    own = own or own_platform()
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    spec = PLATFORMS.get(plat)
    if not spec:
        return None, "no such platform"
    src = {"extras": {}, "others": []}
    if plat == own and frozen:
        src["binary"] = sys.executable
        src["binary_version"] = version
        bdir = os.path.join(root, "browser")
        if not os.path.isfile(os.path.join(bdir, kastr_browser.VERSION_FILE)):
            return None, "no browser folder beside the binary"
        src["browser_dir"] = bdir
        src["browser_version"] = kastr_browser.installed_version(bdir)
    else:
        p = os.path.join(root, "updates", spec["dir"], spec["binary"])
        if not os.path.isfile(p):
            return None, "no %s binary here" % spec["dir"]
        bv = _feed_version(os.path.dirname(p))
        if bv != version:
            return None, "the %s binary here is v%s, not v%s" % (spec["dir"], bv or "?", version)
        src["binary"] = p
        src["binary_version"] = bv
        zp = os.path.join(root, "updates", "browser", "chrome-%s.zip" % spec["bkey"])
        if not os.path.isfile(zp):
            return None, "no %s browser zip here" % spec["dir"]   # status() turns this into a fetch when the pin is bundled
        src["browser_zip"] = zp
        src["browser_version"] = _first_line(os.path.join(root, "updates", "browser", kastr_browser.VERSION_FILE))
    if not src.get("browser_version"):
        return None, "browser version unknown"
    for name in EXTRAS.get(plat, ()):
        p = os.path.join(extras_dir(root, plat), name)
        if os.path.isfile(p):
            src["extras"][name] = p
    if "kastr.ini" not in src["extras"]:
        return None, "no kastr.ini template here (updates/%s/extras -- the host needs a 0.21.7 feed)" % spec["dir"]
    # the other platforms' binaries this release, exactly as build.py ships them inside the zip
    for op, ospec in PLATFORMS.items():
        if op == plat:
            continue
        if op == own and frozen:
            ob, ov = sys.executable, version
        else:
            ob = os.path.join(root, "updates", ospec["dir"], ospec["binary"])
            ov = _feed_version(os.path.dirname(ob)) if os.path.isfile(ob) else None
        if ov == version and os.path.isfile(ob):
            src["others"].append((op, ob, ov))
    return src, None


def _feed_version(folder):
    return (_first_line(os.path.join(folder, "BUILT_VERSION")) or "").strip()


def _first_line(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return (f.read().splitlines() or [""])[0].strip() or None
    except OSError:
        return None


def _runnable(arc, base, mode_bits, plat):
    spec = PLATFORMS[plat]
    return (base in (spec["binary"], "KASTR.exe", "KASTR") or base.endswith(".sh")
            or ("/browser/" in arc and base in kastr_browser.EXECUTABLES)
            or bool(mode_bits & 0o111))


def _entry(z, arc, data, mtime, runnable):
    zi = zipfile.ZipInfo(arc, date_time=time.localtime(mtime)[:6])
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.create_system = 3
    zi.external_attr = (0o755 if runnable else 0o644) << 16
    z.writestr(zi, data)


def _pruned(rel, plat):
    """Would kastr_browser.prune() delete this browser-relative path?"""
    parts = rel.split("/")
    if parts[0] in kastr_browser.PRUNE.get(PLATFORMS[plat]["prune"], ()):
        return True
    if len(parts) == 2 and parts[0] == "locales" and parts[1] not in kastr_browser.KEEP_LOCALES:
        return True
    return False


def assemble(plat, version, src, out_path, log=None):
    """Write the `plat` release zip from `src` (see sources()) to out_path via .part + os.replace.
    Returns the entry count. Entry names keep the <plat>/ root like build.py's archive."""
    log = log or _log[0]
    spec = PLATFORMS[plat]
    top = spec["dir"] + "/"
    tmp = out_path + ".part"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    n = 0
    t0 = time.time()
    now = time.time()
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
            def put(arc, data, mtime=now, mode_bits=0):
                nonlocal n
                _entry(z, arc, data, mtime, _runnable(arc, os.path.basename(arc), mode_bits, plat))
                n += 1

            put(top + "BUILT_VERSION", (version + "\n").encode())
            st = os.stat(src["binary"])
            with open(src["binary"], "rb") as f:
                put(top + spec["binary"], f.read(), st.st_mtime, st.st_mode)
            for name, p in sorted(src["extras"].items()):
                st = os.stat(p)
                with open(p, "rb") as f:
                    put(top + name, f.read(), st.st_mtime, st.st_mode)
            # browser/ -- pruned, VERSION with the prune marker (what an install carries)
            if src.get("browser_dir"):
                bdir = src["browser_dir"]
                for root, dirs, files in os.walk(bdir):
                    dirs.sort()
                    for fn in sorted(files):
                        full = os.path.join(root, fn)
                        rel = os.path.relpath(full, bdir).replace(os.sep, "/")
                        if rel == kastr_browser.VERSION_FILE or _pruned(rel, plat) or fn.startswith("debug.log"):
                            continue
                        st = os.stat(full)
                        with open(full, "rb") as f:
                            put(top + "browser/" + rel, f.read(), st.st_mtime, st.st_mode)
            else:
                broot = "chrome-%s/" % spec["bkey"]
                with zipfile.ZipFile(src["browser_zip"]) as bz:
                    for zi in bz.infolist():
                        if zi.is_dir() or not zi.filename.startswith(broot):
                            continue
                        rel = zi.filename[len(broot):]
                        if not rel or ".." in rel.split("/") or _pruned(rel, plat):
                            continue
                        mode = (zi.external_attr >> 16) & 0o7777
                        put(top + "browser/" + rel, bz.read(zi), time.mktime(zi.date_time + (0, 0, -1)), mode)
            put(top + "browser/" + kastr_browser.VERSION_FILE, (src["browser_version"] + "\n" + kastr_browser.PRUNE_TAG + "\n").encode())
            # updates/<other>/{binary, BUILT_VERSION} + updates/<sub>/extras/* for every platform, like the release zip
            for op, ob, ov in src.get("others", []):
                ospec = PLATFORMS[op]
                st = os.stat(ob)
                with open(ob, "rb") as f:
                    put(top + "updates/%s/%s" % (ospec["dir"], ospec["binary"]), f.read(), st.st_mtime, st.st_mode)
                put(top + "updates/%s/BUILT_VERSION" % ospec["dir"], (ov + "\n").encode())
            root_dir = src.get("root") or app_root()
            for sp in sorted(set(list(PLATFORMS) + ["darwin"])):
                d = extras_dir(root_dir, sp)
                if not os.path.isdir(d):
                    continue
                for fn in sorted(os.listdir(d)):
                    if not EXTRA_RE.match(fn):
                        continue
                    full = os.path.join(d, fn)
                    if not os.path.isfile(full):
                        continue
                    st = os.stat(full)
                    with open(full, "rb") as f:
                        put(top + "updates/%s/extras/%s" % (PLATFORMS.get(sp, {}).get("dir", "macos"), fn), f.read(), st.st_mtime, st.st_mode)
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    _write_sidecar(out_path)
    log("release zip: %s assembled (%d entries, %d MB, %.0f s)" % (os.path.basename(out_path), n, os.path.getsize(out_path) >> 20, time.time() - t0))
    return n


def _write_sidecar(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    st = os.stat(path)
    with open(path + ".sha256", "w", encoding="utf-8", newline="\n") as f:
        json.dump({"sha256": h.hexdigest(), "size": st.st_size, "mtime": st.st_mtime}, f)


def _sidecar_ok(path):
    try:
        with open(path + ".sha256", encoding="utf-8") as f:
            rec = json.load(f)
        st = os.stat(path)
        return rec.get("size") == st.st_size and abs(float(rec.get("mtime") or 0) - st.st_mtime) < 2 and rec
    except (OSError, ValueError):
        return None


def browser_pin():
    """0.21.8: the bundled Chrome for Testing pin (browser.json ships in the frozen app since 0.21.8), or None."""
    try:
        return kastr_browser.load_pin()
    except Exception:
        return None


def _browser_fetchable(plat, why):
    """0.21.8: the only missing part is the other platform's browser zip and the pin says where to get it."""
    spec = PLATFORMS.get(plat)
    if not spec or not why or not why.startswith("no %s browser zip here" % spec["dir"]):
        return False
    pin = browser_pin()
    return bool(pin and (pin.get("platforms") or {}).get(spec["prune"], {}).get("url"))


def fetch_browser_zip(plat, root, log=None):
    """0.21.8: download the pinned Chrome for Testing zip for `plat` (about 200 MB) into <root>/updates/browser/ and
    write its VERSION when missing -- exactly what a hub's co-located feed would have carried. Spokes mirror it from
    the hub afterwards (kastr.mirror_feeds). Returns the zip path; raises on failure."""
    log = log or _log[0]
    spec = PLATFORMS[plat]
    pin = browser_pin()
    if not pin:
        raise RuntimeError("no browser pin bundled")
    bdir = os.path.join(root, "updates", "browser")
    os.makedirs(bdir, exist_ok=True)
    log("release zip: fetching the %s browser (Chrome for Testing %s, %.0f MB) for the %s install zip" % (spec["dir"], pin["version"], pin["platforms"][spec["prune"]]["size"] / 1e6, spec["dir"]))
    src = kastr_browser.ensure_zip(spec["prune"], pin, download=True, log=log)
    dest = os.path.join(bdir, "chrome-%s.zip" % spec["bkey"])
    tmp = dest + ".part"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)
    vf = os.path.join(bdir, kastr_browser.VERSION_FILE)
    if not os.path.isfile(vf):
        with open(vf, "w", encoding="utf-8", newline="\n") as f:
            f.write(pin["version"] + "\n")
    log("release zip: %s browser zip in place (%s)" % (spec["dir"], dest))
    return dest


def status(plat, version, state_dir, root=None, own=None, frozen=None):
    """The manifest's `zip` entry for one platform: {name, can, why, ready, building, size, sha256, estimate, fetch}."""
    spec = PLATFORMS.get(plat)
    if not spec or not state_dir:
        return None
    name = zip_name(plat, version)
    out = {"name": name, "can": False, "why": None, "ready": False, "building": False,
           "size": None, "sha256": None, "estimate": ESTIMATE.get(plat), "fetch": None}
    src, why = sources(plat, version, root=root, own=own, frozen=frozen)
    out["can"] = src is not None
    out["why"] = why
    if src is None and _browser_fetchable(plat, why):   # 0.21.8: assemblable once the host fetches the browser
        out["can"] = True
        out["fetch"] = "browser"
        out["why"] = None
    path = os.path.join(state_dir, "downloads", name)
    rec = _sidecar_ok(path) if os.path.isfile(path) else None
    if rec:
        out["ready"] = True
        out["size"] = rec["size"]
        out["sha256"] = rec["sha256"]
    with _lock:
        b = _building.get(plat)
        out["building"] = bool(b and b["thread"].is_alive())
    return out


def path_for(plat, version, state_dir):
    p = os.path.join(state_dir, "downloads", zip_name(plat, version))
    return p if os.path.isfile(p) and _sidecar_ok(p) else None


def prepare(plat, version, state_dir, root=None, own=None, frozen=None, log=None):
    """Start assembling on a daemon thread (idempotent). Returns the status() dict after the kick."""
    log = log or _log[0]
    src, why = sources(plat, version, root=root, own=own, frozen=frozen)
    need_browser = src is None and _browser_fetchable(plat, why)   # 0.21.8
    if src is None and not need_browser:
        return status(plat, version, state_dir, root=root, own=own, frozen=frozen)
    root_dir = root or app_root()
    if src is not None:
        src["root"] = root_dir
    out_path = os.path.join(state_dir, "downloads", zip_name(plat, version))
    with _lock:
        b = _building.get(plat)
        if not path_for(plat, version, state_dir) and not (b and b["thread"].is_alive()):
            def run():
                try:
                    s2 = src
                    if s2 is None:   # 0.21.8: the other platform's browser first (once), then the parts as usual
                        fetch_browser_zip(plat, root_dir, log=log)
                        s2, why2 = sources(plat, version, root=root, own=own, frozen=frozen)
                        if s2 is None:
                            raise RuntimeError(why2 or "sources missing after the browser fetch")
                        s2["root"] = root_dir
                    _prune_old(os.path.dirname(out_path), version)
                    assemble(plat, version, s2, out_path, log=log)
                except Exception as e:
                    log("release zip: %s NOT assembled (%s)" % (os.path.basename(out_path), e))
                    try:
                        os.remove(out_path + ".part")
                    except OSError:
                        pass
            t = threading.Thread(target=run, name="kastr-release-" + plat, daemon=True)
            _building[plat] = {"at": time.time(), "thread": t}
            log("release zip: assembling %s in the background (%s)" % (os.path.basename(out_path), os.path.dirname(out_path)))
            t.start()
    return status(plat, version, state_dir, root=root, own=own, frozen=frozen)


def _prune_old(folder, version):
    """Drop zips (and sidecars) of other versions -- one release per platform lives in the cache."""
    try:
        names = os.listdir(folder)
    except OSError:
        return
    keep = {zip_name(p, version) for p in PLATFORMS}
    for fn in names:
        base = fn[:-len(".sha256")] if fn.endswith(".sha256") else fn
        if base.startswith(APP + "-") and base.endswith(".zip") and base not in keep:
            try:
                os.remove(os.path.join(folder, fn))
            except OSError:
                pass


def extras_manifest(root, plat):
    """{name: {size, sha256}} of the template files this host can hand out for `plat`."""
    out = {}
    d = extras_dir(root, plat)
    for name in EXTRAS.get(plat, ()):
        p = os.path.join(d, name)
        try:
            st = os.stat(p)
        except OSError:
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        out[name] = {"size": st.st_size, "sha256": h.hexdigest()}
    return out
