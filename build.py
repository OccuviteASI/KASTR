#!/usr/bin/env python3
"""Build KASTR for the platform you run this on.

    python build.py                      unsigned, takes the next version
    python build.py --keep-version       rebuild the SAME version as last time
    python build.py --sign <thumbprint>  Windows only: sign from the cert store
    python build.py --publish-only       no compile: rebuild the update feed from
                                         every dist/<plat> already at VERSION

PyInstaller cannot cross-compile: a macOS app must be built on macOS and a Linux
binary on Linux. Run this script on each target.

    Windows   dist/windows/KASTR.exe
    macOS     dist/macos/KASTR.app   (plus dist/macos/KASTR, the raw binary --
              the archive and the feed use the copy INSIDE the bundle,
              KASTR.app/Contents/MacOS/KASTR, published as updates/macos/KASTR)
    Linux     dist/linux/KASTR

0.13.1: the Mac has its own tree (build-mac.sh), so a release is assembled
where all three platform folders sit together: build Windows and WSL as usual,
copy dist/macos/ (and its archive zip) back from the Mac, then
`python build.py --publish-only` here regenerates dist/updates/, latest.json
and the co-located feeds from whichever dist/<plat> carry BUILT_VERSION ==
VERSION. The Docker image (docker-build.sh) wraps dist/linux/KASTR as built.

Every successful build also writes dist/archive/vX.Y.Z/KASTR-<platform>-vX.Y.Z.zip,
one zip per platform folder built for that version (0.9.8). Only the version
just built is kept -- older version folders and the old combined
"KASTR (vX.Y.Z).zip" files are removed; use --discard <version> to retire a
build that turned out broken.

Shipping one release on two platforms means running this twice from the same
tree: the FIRST run takes the next version number, and the SECOND passes
--keep-version so it joins that same release instead of starting another one.

Native helpers (ffmpeg for RTSP, moq-relay for hosting a relay, moq-cli for
publishing RTSP feeds natively) are bundled from bin/ when present. They are
platform-specific binaries, so each platform needs its own copies -- see
fetch-helpers.py, which downloads the right ones. The pinned Chrome for Testing
(browser.json) is staged beside the binary as dist/<plat>/browser and pruned to
what a KASTR window uses (kastr_browser.prune).
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kastr_browser   # noqa: E402 -- 0.9.0 bundled browser: pin, staging, prune, executables
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"

NAME = "KASTR"
PAGES = [
    "index.html", "app.html", "moq-watch-lite.html",
    "stats.html", "relay.html",
    "watch.html", "manifest.webmanifest",   # 0.17.0: the fMP4 fallback player + the PWA manifest
]
HELPERS = [
    ("ffmpeg", "RTSP ingest"),
    ("moq-relay", "relay hosting"),
    ("moq", "native RTSP publishing"),   # 0.9.1: moq-cli
]

VERSION_FILE = os.path.join(HERE, "VERSION")
RELEASES_FILE = os.path.join(HERE, "RELEASES.md")
BUILT_MARKER = "BUILT_VERSION"

# Each platform gets its own folder so the three builds can sit side by side
# without overwriting one another.
PLATFORM_DIR = "windows" if WINDOWS else ("macos" if MACOS else "linux")
DIST = os.path.join(HERE, "dist", PLATFORM_DIR)
DIST_ROOT = os.path.join(HERE, "dist")
ARCHIVE = os.path.join(DIST_ROOT, "archive")

# Platform folders that make up a release, in the order they go into the zip.
PLATFORMS = ("windows", "macos", "linux")

# A binary moved aside because it was still running. Excluded from archives.
STALE_PREFIX = NAME + ".old-"

# 0.9.8: only the release just built stays in dist/archive (one folder per
# version, one zip per platform). Broken builds go with --discard.


def read_version():
    """The version of the last successful build.

    Deliberately fatal rather than defaulting. A silent fallback here would
    name the archive after a release that already exists and overwrite it,
    and dist/archive is the only copy -- there is no repository behind it.
    """
    try:
        # utf-8-sig: PowerShell writes a BOM, and strip() does not remove
        # U+FEFF, so a hand edit would otherwise poison the archive name.
        with open(VERSION_FILE, encoding="utf-8-sig") as f:
            v = f.read().strip()
    except OSError as e:
        sys.exit("cannot read %s (%s) -- it records the last built version, so a build cannot number itself without it." % (VERSION_FILE, e))
    if not v:
        sys.exit("%s is empty -- it should hold the last built version, e.g. 0.5.4"
                 % VERSION_FILE)
    return v

def ensure_release_notes(version):
    """Warn, and stub, if this version has no entry.

    An undocumented build should be obvious rather than silent, so a missing
    entry is inserted as a placeholder for you to fill in, not skipped.
    """
    header = "## v%s" % version
    try:
        with open(RELEASES_FILE, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = "# KASTR release notes" + chr(10)
    # Line-anchored: '## v0.5' is a substring of '## v0.5.5', so a plain
    # containment test would find the wrong release and skip the warning.
    # 0.10.0: a titled heading ("## v0.9.10 -- what changed") counts too --
    # the exact-match test stubbed every titled entry twice.
    def _is_entry(ln):
        t = ln.strip()
        return t == header or t.startswith(header + " ")
    if any(_is_entry(ln) for ln in text.split(chr(10))):
        return True

    stub = (header + chr(10) + chr(10)
            + "- No release notes were written for this build." + chr(10) + chr(10))
    # Insert above the newest existing entry, keeping newest-first order.
    at = text.find("## v")
    text = (text[:at] + stub + text[at:]) if at != -1 else (text + chr(10) + stub)
    try:
        with open(RELEASES_FILE, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
    print("WARNING: no release notes for v%s -- a placeholder was added to "
          "RELEASES.md" % version)
    return False


def sweep_stale(dist):
    """Delete binaries moved aside by earlier builds, once nothing holds them."""
    if not os.path.isdir(dist):
        return
    for fn in os.listdir(dist):
        if not fn.startswith(STALE_PREFIX):
            continue
        try:
            os.remove(os.path.join(dist, fn))
        except OSError:
            pass        # still running; next build will get it


def free_target(out):
    """Make room for a new binary even if the old one is running.

    Windows refuses to delete a running .exe but happily renames it, and the
    running process keeps working from the renamed image. Without this a
    forgotten KASTR window fails the whole build.
    """
    if not os.path.exists(out):
        return
    try:
        with open(out, "ab"):
            pass
        return          # not locked -- let PyInstaller replace it as usual,
                        # so a failed compile still leaves the old binary
    except OSError:
        pass
    aside = os.path.join(os.path.dirname(out),
                         "%s%d%s" % (STALE_PREFIX, int(time.time()),
                                     os.path.splitext(out)[1]))
    try:
        os.rename(out, aside)
        print("NOTE: %s is still running -- moved it to %s; it will be removed "
              "on a later build." % (os.path.basename(out), os.path.basename(aside)))
    except OSError as e:
        sys.exit("cannot replace %s (%s). Close %s and build again." % (out, e, NAME))


# What a release is expected to contain, per platform. Used both to decide
# whether a folder is worth archiving and to flag drift in what gets shipped.
PLATFORM_BINARY = {
    "windows": NAME + ".exe",
    "linux": NAME,
    "macos": NAME + ".app",
}

# 0.13.1: the FILE the update feed hands out, relative to dist/<plat>. On
# macOS that is the executable inside the bundle -- PLATFORM_BINARY["macos"]
# is a directory, and `--publish` used to shutil.copyfile() it (IsADirectory-
# Error). It lands in updates/<plat>/<basename>, so macos -> updates/macos/
# KASTR, which is what kastr_serve._update_platforms already looks for and
# what update_from swaps over sys.executable inside the bundle.
PLATFORM_UPDATE_BINARY = {
    "windows": NAME + ".exe",
    "linux": NAME,
    "macos": os.path.join(NAME + ".app", "Contents", "MacOS", NAME),
}

# latest.json / /api/update/manifest key per platform folder (sys.platform names).
PLATFORM_API_KEY = {"windows": "win32", "linux": "linux", "macos": "darwin"}


def folder_version(folder):
    """What BUILT_VERSION in this folder says, or None if it does not say."""
    try:
        with open(os.path.join(folder, BUILT_MARKER), encoding="utf-8-sig") as f:
            return f.read().strip() or None
    except OSError:
        return None


def archivable(plat, version, root=None):
    """Is dist/<plat> part of THIS release? Returns (ok, reason_if_not).

    `root` replaces dist/ (0.13.1: so the publish helpers can be exercised
    against a scratch tree); the default is the real one."""
    folder = os.path.join(root or DIST_ROOT, plat)
    if not os.path.isdir(folder):
        return False, None                      # not built here; say nothing

    got = folder_version(folder)
    if got is None:
        return False, "no %s marker, so its provenance is unknown" % BUILT_MARKER
    if got != version:
        return False, "%s says v%s, archiving v%s" % (BUILT_MARKER, got, version)

    # A matching marker is not enough: free_target renames a locked binary
    # aside, so a folder can carry the right marker and no executable.
    binary = os.path.join(folder, PLATFORM_BINARY[plat])
    if not os.path.exists(binary):
        return False, "no %s in it" % PLATFORM_BINARY[plat]
    # 0.13.1: and on macOS the bundle must actually hold its executable --
    # that copy is what ships in the feed.
    feed_bin = os.path.join(folder, PLATFORM_UPDATE_BINARY[plat])
    if not os.path.isfile(feed_bin):
        return False, "no %s in it" % PLATFORM_UPDATE_BINARY[plat].replace(os.sep, "/")
    return True, None


def zip_entry(z, full, arcname):
    """Add one file with stable metadata.

    z.write() inherits the host byte and mode from whichever machine is
    zipping, so the Linux binary came out executable or not depending on
    which platform was built last. State it explicitly instead.
    """
    import zipfile

    st = os.stat(full)
    zi = zipfile.ZipInfo(arcname, date_time=time.localtime(st.st_mtime)[:6])
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.create_system = 3                        # always claim POSIX
    base = os.path.basename(arcname)
    # 0.9.3: the bundled browser's executables too. Stored 0644, an unpacked
    # linux/browser/chrome could not start and the app opened in Firefox.
    runnable = (base in PLATFORM_BINARY.values() or '/Contents/MacOS/' in arcname
                or base.endswith(".sh")
                or ("/browser/" in arcname and base in kastr_browser.EXECUTABLES)
                # 0.13.1: anything the build host already marked executable
                # (the .app's Frameworks/ dylibs and helper tools on the Mac)
                # keeps 0755; Windows has no exec bit, so the list rules there.
                or (not WINDOWS and bool(st.st_mode & 0o111)))
    zi.external_attr = (0o755 if runnable else 0o644) << 16
    with open(full, "rb") as f:
        z.writestr(zi, f.read())


def archive_dir(version):
    """dist/archive/v<version> -- the one folder a release's zips live in (0.9.8)."""
    return os.path.join(ARCHIVE, "v%s" % version)


def archive_name(plat, version):
    return "%s-%s-v%s.zip" % (NAME, plat, version)


def archive_current(version):
    """Zip each platform folder belonging to this version into its own file
    under dist/archive/v<version>/ (0.9.8: one zip per platform, so a Windows
    box can grab windows/ without the 300 MB Linux browser, and vice versa).

    The build host always (re)writes the zip for the platform it just built;
    another platform's folder is zipped too when it carries this version and
    has no zip yet, so the second build of a release completes the set
    without redoing the first one. Arcnames keep the <plat>/ root, so an
    unpacked zip still yields windows/KASTR.exe or linux/KASTR.
    """
    import zipfile

    out_dir = archive_dir(version)
    os.makedirs(out_dir, exist_ok=True)
    have = []
    counts = {}

    def blew_up(err):
        # os.walk swallows scandir failures by default, which would silently
        # produce a partial bundle (an unreadable .app subtree, say).
        raise err

    for plat in PLATFORMS:
        ok, why = archivable(plat, version)
        if not ok:
            if why:
                print("  skipping dist/%s: %s" % (plat, why))
            continue
        have.append(plat)
        zip_path = os.path.join(out_dir, archive_name(plat, version))
        if plat != PLATFORM_DIR and os.path.exists(zip_path):
            counts[plat] = None                 # the other host zipped it already
            continue
        # Build beside the target and swap, so an interrupted run cannot leave
        # a half-written zip standing in for a release.
        tmp = zip_path + ".part"
        n = 0
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                folder = os.path.join(DIST_ROOT, plat)
                for root, dirs, files in os.walk(folder, onerror=blew_up):
                    dirs.sort()
                    # 0.9.0: the fleet-feed browser zips (updates/browser/*.zip,
                    # ~200 MB each) and browser.old-* leftovers stay out of the
                    # release archive; the browser/ folder itself ships.
                    if os.path.basename(root) == "updates":
                        dirs[:] = [d for d in dirs if d != "browser"]
                    if root == folder:
                        dirs[:] = [d for d in dirs if not d.startswith("browser.old-")]
                    # 0.8.6: the co-located update feed (dist/<plat>/updates,
                    # the OTHER platform's binary) ships INSIDE the zip -- one
                    # archive is a complete, fleet-serving deployment.
                    for fn in sorted(files):
                        if fn.startswith(STALE_PREFIX):
                            continue    # a binary still held by a running app
                        # 0.13.1: PyInstaller --onefile --windowed leaves a
                        # loose dist/macos/KASTR beside KASTR.app, byte-for-
                        # byte the bundle's Contents/MacOS/KASTR. The zip
                        # carries the bundle tree only (100 MB saved).
                        if plat == "macos" and root == folder and fn == NAME:
                            continue
                        full = os.path.join(root, fn)
                        arc = os.path.relpath(full, DIST_ROOT).replace(os.sep, '/')
                        zip_entry(z, full, arc)
                        n += 1
            os.replace(tmp, zip_path)
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            sys.exit("could not write the release archive (%s)" % e)
        counts[plat] = n

    if not have:
        sys.exit("nothing to archive for v%s -- no platform folder carries a matching %s and its binary." % (version, BUILT_MARKER))
    return out_dir, have, counts


def check_release_contents(have):
    """Flag drift in what actually ships, without pretending to fix it.

    build.py deposits a binary and a marker; kastr.ini and README.txt are
    placed by hand. Silently publishing whatever happens to be sitting in the
    folder is how the two shipped kastr.ini files came to disagree.
    """
    expected = {"kastr.ini", BUILT_MARKER}
    for plat in have:
        folder = os.path.join(DIST_ROOT, plat)
        names = {f for f in os.listdir(folder)
                 if not f.startswith(STALE_PREFIX)}
        missing = expected - names
        if missing:
            print("  note: dist/%s has no %s" % (plat, ", ".join(sorted(missing))))
    # 0.13.1: the Docker image wraps dist/linux/KASTR, so a fresh Linux
    # binary means a stale image until docker-build.sh runs. Information only.
    if "linux" in have and os.path.exists(os.path.join(HERE, "Dockerfile")):
        print("  note: dist/linux changed -- rebuild the container image with "
              "./docker-build.sh (see DOCKER.md)")

def version_key(v):
    """Sort 0.5.10 after 0.5.9, which a plain string sort gets wrong."""
    out = []
    for part in v.split("."):
        try:
            out.append((0, int(part)))
        except ValueError:
            out.append((1, part))       # a tag like 0.5.6-rc1 sorts after
    return out


def archived_versions():
    """Every version present in dist/archive -> the paths that make it up.

    0.9.8 layout: a folder v<version>/ holding one zip per platform. The older
    combined "KASTR (v0.9.7).zip" (and the even older per-platform
    "KASTR (v0.5.2) linux.zip") are recognised so they age out too. Anything
    else in dist/archive (notes, hand-placed files) is never touched.
    """
    found = {}
    if not os.path.isdir(ARCHIVE):
        return found
    for fn in os.listdir(ARCHIVE):
        full = os.path.join(ARCHIVE, fn)
        if os.path.isdir(full) and fn.startswith("v") and fn[1:2].isdigit():
            found.setdefault(fn[1:], []).append(full)
            continue
        if not fn.startswith(NAME + " (v") or not fn.endswith(".zip"):
            continue
        try:
            ver = fn.split(" (v", 1)[1].split(")", 1)[0]
        except IndexError:
            continue
        found.setdefault(ver, []).append(full)
    return found


def drop_version(ver, why):
    """Delete every archive file or folder for one version."""
    import shutil
    gone = 0
    for path in archived_versions().get(ver, []):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            print("  removed %s (%s)" % (os.path.basename(path), why))
            gone += 1
        except OSError as e:
            print("  WARNING: could not remove %s (%s)" % (os.path.basename(path), e))
    return gone


def prune_archives(protect=None):
    """0.9.8: keep ONE version in dist/archive -- the release just built
    (`protect`), or the newest present when retiring a build -- and delete the
    rest, old combined zips included. There is no repository behind dist/
    archive, so this is the deliberate trade: the current release is always
    there, history is not (requested 2026-09-16)."""
    versions = sorted(archived_versions(), key=version_key, reverse=True)
    if not versions:
        return
    keep = protect if protect in versions else versions[0]
    for ver in versions:
        if ver == keep:
            continue
        drop_version(ver, "keeping only v%s" % keep)

def bump_version(cur):
    # 0.5 -> 0.5.1 -> 0.5.2 ...  Only the last component moves: the major and
    # minor are yours to set by editing VERSION; the build counts compiles.
    parts = cur.split(".")
    if len(parts) < 3:
        parts = parts + ["1"]
    else:
        try:
            parts[-1] = str(int(parts[-1]) + 1)
        except ValueError:
            parts.append("1")
    return ".".join(parts)


def helper_name(stem):
    return stem + ".exe" if WINDOWS else stem


def _sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def publish_feed(version, have, root=None):
    """Fleet update feed (0.8.1): <root>/updates/<plat>/<binary> + latest.json.

    A KASTR instance serves this folder when it sits next to its binary;
    kastr_serve hashes lazily, so latest.json here is informational. 0.13.1:
    factored out of main() so --publish-only can run it without a compile,
    and the file copied is PLATFORM_UPDATE_BINARY (macos -> the executable
    inside the bundle, published as updates/macos/KASTR). `root` replaces
    dist/ for a scratch run. Returns the updates/ folder."""
    import json
    import shutil
    root = root or DIST_ROOT
    upd = os.path.join(root, "updates")
    manifest = {"app": NAME, "version": version, "platforms": {}}
    for plat in have:
        src = os.path.join(root, plat, PLATFORM_UPDATE_BINARY[plat])
        if not os.path.isfile(src):
            continue
        dstdir = os.path.join(upd, plat)
        os.makedirs(dstdir, exist_ok=True)
        dst = os.path.join(dstdir, os.path.basename(PLATFORM_UPDATE_BINARY[plat]))
        shutil.copyfile(src, dst)
        if plat != "windows":
            os.chmod(dst, 0o755)
        manifest["platforms"][PLATFORM_API_KEY[plat]] = {"size": os.path.getsize(dst),
                                                         "sha256": _sha256_file(dst)}
    # 0.13.1: a platform folder that is NOT part of this release leaves its
    # previous binary in updates/ -- say so, because the co-location below
    # would ship it beside the fresh ones and a hub serves whatever it holds.
    for plat in PLATFORMS:
        if plat in have:
            continue
        stale = os.path.join(upd, plat, os.path.basename(PLATFORM_UPDATE_BINARY[plat]))
        if os.path.exists(stale):
            print("  WARNING: %s is from an earlier build (dist/%s is not at v%s) "
                  "-- delete it or rebuild that platform" % (
                      os.path.relpath(stale, root).replace(os.sep, "/"), plat, version))
    os.makedirs(upd, exist_ok=True)
    with open(os.path.join(upd, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print("Published update feed -> %s (%s)" % (upd, ", ".join(sorted(manifest["platforms"]))))
    return upd


def colocate_feeds(upd, root=None, browser=True):
    """0.8.4: co-locate the feed INSIDE each app folder so a deployed app is
    a turnkey relay -- kastr_serve serves updates/<sub>/ next to the binary
    (the running platform comes from sys.executable). After the normal
    Windows-then-Linux release, both dist/<plat>/updates carry both fresh
    binaries. The archive step skips this updates/ subfolder so release zips
    do not balloon. 0.13.1: macos joins (dist/<plat>/updates/macos/KASTR,
    and dist/macos/updates/{windows,linux}/ for a Mac hub); `browser=False`
    skips the Chrome zips (scratch runs -- ensure_zip may download 200 MB)."""
    import shutil
    root = root or DIST_ROOT
    for plat in PLATFORMS:
        folder = os.path.join(root, plat)
        if not os.path.isdir(folder):
            continue
        dstroot = os.path.join(folder, "updates")
        for sub in PLATFORMS:
            if sub == plat:
                continue    # own platform is served from sys.executable, not updates/
            fn = os.path.basename(PLATFORM_UPDATE_BINARY[sub])
            srcbin = os.path.join(upd, sub, fn)
            if not os.path.exists(srcbin):
                continue
            subdir = os.path.join(dstroot, sub)
            os.makedirs(subdir, exist_ok=True)
            cp = os.path.join(subdir, fn)
            shutil.copyfile(srcbin, cp)
            if sub != "windows":
                os.chmod(cp, 0o755)
        # 0.9.0: both platforms' browser zips beside the binary, so a KASTR
        # that serves the fleet can hand out the browser folder too
        # (/api/update/browser). From the cache; downloaded when missing.
        if browser:
            try:
                pin = kastr_browser.load_pin()
                bdir = os.path.join(dstroot, "browser")
                os.makedirs(bdir, exist_ok=True)
                for bp in kastr_browser.PLATFORMS:
                    zf = kastr_browser.ensure_zip(bp, pin, log=print)
                    cp = os.path.join(bdir, "chrome-%s.zip" % pin["platforms"][bp]["key"])
                    if not (os.path.exists(cp) and os.path.getsize(cp) == os.path.getsize(zf)):
                        shutil.copyfile(zf, cp)
                with open(os.path.join(bdir, "VERSION"), "w", encoding="utf-8", newline=chr(10)) as f:
                    f.write(pin["version"] + chr(10))
            except Exception as e:
                print("  browser feed for dist/%s NOT refreshed: %s" % (plat, e))
        if os.path.isdir(dstroot):
            print("  co-located update feed -> dist/%s/updates" % plat)


def release_folders(version, root=None, log=print):
    """Which dist/<plat> carry THIS version (marker + binary), in PLATFORMS
    order; the reasons the others do not are printed."""
    have = []
    for plat in PLATFORMS:
        ok, why = archivable(plat, version, root)
        if ok:
            have.append(plat)
        elif why:
            log("  skipping dist/%s: %s" % (plat, why))
    return have


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sign", metavar="THUMBPRINT",
                    help="Windows only: sign with this certificate from the store")
    ap.add_argument("--keep-version", action="store_true",
                    help="rebuild the SAME version as the last build instead "
                         "of taking the next one -- use for the second "
                         "platform of a release")
    ap.add_argument("--discard", metavar="VERSION",
                    help="delete a build that turned out broken and exit")
    ap.add_argument("--publish", action="store_true",
                    help="also refresh dist/updates/ (per-platform binaries + "
                         "latest.json) -- copy that folder next to the relay "
                         "host's KASTR so the fleet can update from it")
    ap.add_argument("--publish-only", action="store_true",
                    help="no compile, no archive: regenerate dist/updates/, "
                         "latest.json and the co-located feeds from every "
                         "dist/<plat> whose BUILT_VERSION equals VERSION -- "
                         "run on the machine where all platform folders sit "
                         "together (after copying dist/macos back from the Mac)")
    args = ap.parse_args()

    # Fail on an impossible flag in a second rather than after a full build.
    if args.sign and not WINDOWS:
        sys.exit("--sign is Windows-only; use codesign on macOS.")

    if args.discard:
        # Retiring a bad build is not a build; do it and stop.
        if not drop_version(args.discard, "discarded as broken"):
            sys.exit("no archive for v%s" % args.discard)
        prune_archives()
        return 0

    if args.publish_only:
        # 0.13.1: assemble the feed from what is already built. VERSION is the
        # release (set by hand, built with --keep-version everywhere); the
        # folders that carry it are the release, the others are named and
        # left out. Nothing is compiled, staged or archived, and VERSION is
        # not touched.
        version = read_version()
        print("Version %s (--publish-only)" % version)
        have = release_folders(version)
        if not have:
            sys.exit("nothing to publish for v%s -- no dist/<plat> carries a matching %s and its binary." % (version, BUILT_MARKER))
        check_release_contents(have)
        upd = publish_feed(version, have)
        colocate_feeds(upd)
        print("\nPublished v%s from dist/%s." % (version, ", dist/".join(have)))
        return 0

    # PyInstaller uses ; on Windows and : elsewhere to split --add-data.
    sep = ";" if WINDOWS else ":"
    os.makedirs(DIST, exist_ok=True)
    # VERSION records the LAST build, so a new one takes the next number and
    # the second platform of a release repeats it.
    last = read_version()
    version = last if args.keep_version else bump_version(last)
    print("Version %s" % version)
    ensure_release_notes(version)

    # 0.8.13: the MoQ web library ships inside the app. Mirror it (pinned) if
    # the vendor folder is missing, and refuse to build a release without it --
    # a page that imports from esm.sh at run time is one CDN hiccup from dead.
    vendor_manifest = os.path.join(HERE, "assets", "vendor", "esm", "manifest.json")
    if not os.path.exists(vendor_manifest):
        subprocess.run([sys.executable, os.path.join(HERE, "vendor-moq.py")], check=False)
    if not os.path.exists(vendor_manifest):
        sys.exit("assets/vendor/esm/manifest.json is missing -- run vendor-moq.py (needs network once)")
    # 0.13.1: the RNNoise worklet the page loads for background-noise removal (vendor-noise.py)
    if not os.path.exists(os.path.join(HERE, "assets", "noise", "manifest.json")):
        sys.exit("assets/noise/manifest.json is missing -- run vendor-noise.py (needs network once)")
    add_data = [os.path.join(HERE, "assets") + sep + os.path.join("site", "assets")]

    # Ship the version beside the pages so the frozen app can read it back.
    # Generated rather than copied from VERSION: that file records the LAST
    # build and is not updated until this one succeeds, so shipping it
    # verbatim stamps the app with the previous number.
    stamp_dir = os.path.join(os.environ.get("TEMP") or "/tmp", "kastr-build")
    os.makedirs(stamp_dir, exist_ok=True)
    stamp = os.path.join(stamp_dir, "VERSION")
    with open(stamp, "w", encoding="utf-8", newline=chr(10)) as f:
        f.write(version + chr(10))
    add_data.append(stamp + sep + "site")
    if os.path.exists(RELEASES_FILE):
        add_data.append(RELEASES_FILE + sep + "site")
    for page in PAGES:
        src = os.path.join(HERE, page)
        if not os.path.exists(src):
            sys.exit("missing page: " + page)
        add_data.append(src + sep + "site")

    for stem, why in HELPERS:
        path = os.path.join(HERE, "bin", helper_name(stem))
        if os.path.exists(path):
            add_data.append(path + sep + "bin")
            print("Bundling %s (%.0f MB)" % (helper_name(stem),
                                             os.path.getsize(path) / 1e6))
        else:
            print("WARNING: bin/%s missing -- building WITHOUT %s."
                  % (helper_name(stem), why))
            print("         Run: python fetch-helpers.py")

    out = os.path.join(DIST, NAME + (".exe" if WINDOWS else ""))
    before = os.path.getmtime(out) if os.path.exists(out) else 0

    # Build scratch outside the tree: this folder used to be synced by OneDrive on the
    # Windows box, and the sync client intermittently locks PyInstaller's work
    # files, which fails the build midway.
    work = os.path.join(os.environ.get("TEMP") or "/tmp", "kastr-build")

    # 0.8.9: the local CA needs the cryptography package in the build env
    try:
        import cryptography  # noqa: F401
    except ImportError:
        sys.exit("build: the 'cryptography' package is missing in this Python -- "
                 "pip install cryptography (both build environments) and rerun")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--hidden-import", "cryptography",
        "--hidden-import", "kastr_tls",
        "--noconfirm", "--clean", "--onefile", "--noconsole",
        "--name", NAME,
        "--distpath", DIST,
        "--workpath", work,
        "--specpath", work,
        "--paths", HERE,
        "--exclude-module", "tkinter",
        "--exclude-module", "PIL",
        "--exclude-module", "unittest",
        # 0.9.3: the video-page resolver is gone -- yt-dlp was ~1,000 modules
        # and 5 MB of the exe (plus sqlite3) for a feature the field never used.
        "--exclude-module", "yt_dlp",
    ]

    icon = os.path.join(HERE, "icons", "asi-icon.ico")     # 0.9.3: icons/ -- not shipped inside site/assets
    if WINDOWS and os.path.exists(icon):
        cmd += ["--icon", icon]
    icns = os.path.join(HERE, "icons", "asi-icon.icns")
    if MACOS and os.path.exists(icns):
        cmd += ["--icon", icns]
    if MACOS:
        # Build a .app too, and declare the camera/mic usage strings macOS
        # requires -- without them the OS kills the capture prompt outright.
        cmd += [
            "--windowed",
            "--osx-bundle-identifier", "com.asirobots.kastr",
        ]

    for d in add_data:
        cmd += ["--add-data", d]
    cmd.append(os.path.join(HERE, "kastr.py"))

    sweep_stale(DIST)
    free_target(out)

    print("Building %s for %s ..." % (NAME, sys.platform))
    code = subprocess.call(cmd)

    # Verify rather than trust: a stale binary from a previous run would
    # otherwise make a failed build look successful.
    if code != 0:
        sys.exit("PyInstaller exited %d -- build FAILED (anything in dist/ is stale)" % code)
    if not os.path.exists(out):
        sys.exit("build produced no binary at " + out)
    if os.path.getmtime(out) <= before:
        sys.exit("binary was not rewritten -- build FAILED, dist/ holds a stale build")

    print("\nCompiled: %s  v%s  (%.1f MB, %s)"
          % (out, version, os.path.getsize(out) / (1024 * 1024),
             time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(out)))))

    # Record what this folder holds. Fatal if it cannot be written: the
    # archive decides what to pack from this marker, and a marker that lies
    # is worse than none. newline= keeps Windows from writing CRLF, so the
    # two platforms' markers compare equal.
    try:
        with open(os.path.join(DIST, BUILT_MARKER), "w",
                  encoding="utf-8", newline=chr(10)) as f:
            f.write(version + chr(10))
    except OSError as e:
        sys.exit("built, but could not record %s (%s)" % (BUILT_MARKER, e))

    # 0.9.0: the bundled browser. dist/<plat>/browser holds the pinned Chrome
    # for Testing (browser.json); the zip comes from the cache or is downloaded.
    if PLATFORM_DIR in ("windows", "linux"):
        pin = kastr_browser.load_pin()
        try:
            kastr_browser.stage(DIST, PLATFORM_DIR, pin, log=print)
        except Exception as e:
            sys.exit("could not stage the bundled browser (%s) -- run fetch-helpers.py first" % e)
        kastr_browser.sweep_old(DIST)

    # Finish the artifact BEFORE archiving it. Signing and the macOS plist
    # patch rewrite the binary in place, and the zip is the copy people
    # redistribute -- archiving first shipped an unsigned exe and a bundle
    # with no camera or microphone usage strings.
    if MACOS:
        app = os.path.join(DIST, NAME + ".app")
        if os.path.exists(app):
            patch_plist(app)
            print("Bundle: %s" % app)
        print("NOTE: unsigned .app files are quarantined by Gatekeeper. Either")
        print("      codesign/notarize it, or on each machine run:")
        print("      xattr -dr com.apple.quarantine '%s'" % app)
    elif not WINDOWS:
        os.chmod(out, 0o755)

    if args.sign:
        sign(out, args.sign)                    # exits non-zero on failure
    elif WINDOWS:
        print("Unsigned. SmartScreen will warn on first run elsewhere.")

    zip_dir, have, counts = archive_current(version)
    check_release_contents(have)
    print("Archived v%s -> %s" % (version, zip_dir))
    print("  %s" % ", ".join(
        "%s %s" % (p, ("%d files" % counts[p]) if counts[p] is not None else "already zipped")
        for p in have))

    if args.publish:
        # Fleet update feed + co-located copies (0.13.1: see publish_feed /
        # colocate_feeds -- the same code --publish-only runs without a build).
        colocate_feeds(publish_feed(version, have))
    prune_archives(protect=version)

    # Last of all, and only now that the release is on disk: record that this
    # version exists, so the next build takes the number after it.
    if args.keep_version:
        print("VERSION stays at %s (--keep-version)" % version)
    else:
        try:
            with open(VERSION_FILE, "w", encoding="utf-8", newline=chr(10)) as f:
                f.write(version + chr(10))
        except OSError as e:
            sys.exit("archived v%s, but could not update %s (%s) -- fix it before building again or the next build will overwrite this release."
                     % (version, VERSION_FILE, e))

    print("\nBuilt v%s. Next build will be v%s (or --keep-version to join this one)."
          % (version, bump_version(version)))

# macOS refuses camera and microphone access outright unless the bundle
# declares why it wants them -- the prompt never appears and capture just fails.
# PyInstaller does not add these, so stamp them in after the build.
PLIST_KEYS = {
    "NSCameraUsageDescription":
        "KASTR publishes video from the cameras you select.",
    "NSMicrophoneUsageDescription":
        "KASTR publishes audio from the microphone you select.",
    "NSLocalNetworkUsageDescription":
        "KASTR connects to a MoQ relay on your local network, and can host one.",
    "CFBundleDisplayName": NAME,
}


def patch_plist(app):
    """Add the usage-description keys macOS requires to the built bundle."""
    plist = os.path.join(app, "Contents", "Info.plist")
    if not os.path.exists(plist):
        print("WARNING: no Info.plist at %s" % plist)
        return
    try:
        import plistlib
        with open(plist, "rb") as f:
            data = plistlib.load(f)
        added = [k for k in PLIST_KEYS if k not in data]
        data.update(PLIST_KEYS)
        # A high-DPI bundle also wants this, or the window renders soft.
        data.setdefault("NSHighResolutionCapable", True)
        with open(plist, "wb") as f:
            plistlib.dump(data, f)
        print("Info.plist: added %s" % (", ".join(added) if added else "nothing new"))
    except Exception as e:
        print("WARNING: could not patch Info.plist (%s)" % e)


def sign(exe, thumbprint):
    ps = (
        "$c = @('Cert:\\CurrentUser\\My','Cert:\\LocalMachine\\My') | "
        "ForEach-Object { Get-ChildItem $_ -ErrorAction SilentlyContinue } | "
        "Where-Object { $_.Thumbprint -eq '%s' } | Select-Object -First 1; "
        "if (-not $c) { throw 'certificate not found' }; "
        "Set-AuthenticodeSignature -FilePath '%s' -Certificate $c "
        "-HashAlgorithm SHA256 -TimestampServer http://timestamp.digicert.com "
        "-IncludeChain All | Out-Null; "
        "$s = Get-AuthenticodeSignature '%s'; "
        "if (-not $s.SignerCertificate) { throw 'signing produced no signature' }; "
        "Write-Host \"Signature: $($s.Status)  signer $($s.SignerCertificate.Subject)\"; "
        "if (-not $s.TimeStamperCertificate) { Write-Warning 'not timestamped' }"
        % (thumbprint.replace(" ", ""), exe, exe)
    )
    if subprocess.call(["powershell", "-NoProfile", "-Command", ps]) != 0:
        sys.exit("signing FAILED")


if __name__ == "__main__":
    main()
