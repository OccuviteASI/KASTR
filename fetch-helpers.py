#!/usr/bin/env python3
"""Download the native helpers KASTR bundles, for the platform you run this on.

    python fetch-helpers.py

Fetches into bin/:
    ffmpeg      RTSP ingest (the browser cannot open RTSP itself)
    moq-relay   so this machine can host a MoQ relay
    moq         moq-cli, the native RTSP publisher (ffmpeg | moq import ts)
and, into a cache outside the tree (~200 MB per platform), the pinned Chrome
for Testing zip named in browser.json, which build.py stages into
dist/<plat>/browser (`--browser-all` fetches both platforms' zips).

All are platform-specific, so run this once on each machine you build on.
ffmpeg on macOS is NOT downloaded until FFMPEG_MAC (below) is pinned -- nobody
publishes a static macOS build the ffmpeg project will vouch for, and silently
pulling a random third-party binary is worse than telling you to install it.
Until then the script prints the one-line install command instead, and KASTR
falls back to ffmpeg on PATH. Linux x86_64 does get a download -- see
FFMPEG_LINUX below for which build and why that one.

macOS is Apple Silicon only (0.13.1): moq-relay and moq-cli publish an
aarch64-apple-darwin tarball and no x86_64 one, so an Intel Mac gets neither
helper and build-mac.sh refuses to build there.
"""
import hashlib
import io
import json
import os
import platform
import stat
import sys
import tarfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "bin")
STAMP = os.path.join(BIN, ".versions.json")   # 0.16.0: {"moq-relay": "0.15.1", "moq": "0.12.1"} per stem
FORCE = "--force" in sys.argv


def _stamp_read():
    try:
        with open(STAMP, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _stamp_write(name, version):
    d = _stamp_read()
    d[name] = version
    tmp = STAMP + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, sort_keys=True)
    os.replace(tmp, STAMP)


def _current(dest, name, want):
    """0.16.0: present AND stamped with the wanted version. A bump used to be a
    silent no-op ("already present, skipping") until bin/ was cleared by hand."""
    if FORCE or not os.path.exists(dest):
        return False
    have = _stamp_read().get(name)
    if have == want:
        return True
    print("%s: %s present, fetching %s" % (name, have or "unstamped build", want))
    return False

# 0.16.0: 0.15.1 (2026-09-24) -- the relay no longer verifies JWTs itself: an
# auth server ([auth] url, KASTR's token service) answers once per session;
# [server]->[listen], [client]->[connect], [cluster] linger gone, [cluster.lan]
# mDNS, [internal] /metrics. SHA256SUMS of both releases read 2026-09-24.
# 0.11.0: 0.14.18 (2026-09-17) -- credentials no longer logged in relay URLs.
MOQ_VERSION = "0.15.1"
MOQ_BASE = ("https://github.com/moq-dev/moq/releases/download/"
            "moq-relay-v%s/" % MOQ_VERSION)

# asset per platform+arch; sha256 from the release's SHA256SUMS where pinned.
# 0.13.1: darwin/arm64 pinned (SHA256SUMS of moq-relay-v0.14.18, read
# 2026-09-21); the ("darwin", "x86_64") alias to the arm64 tarball is gone --
# a Rosetta-run relay was never tested and Intel Macs are unsupported.
MOQ_ASSETS = {
    ("win32", "x86_64"):  "moq-relay-v%s-x86_64-pc-windows-msvc.zip" % MOQ_VERSION,
    ("darwin", "arm64"):  "moq-relay-v%s-aarch64-apple-darwin.tar.gz" % MOQ_VERSION,
    ("linux", "x86_64"):  "moq-relay-v%s-x86_64-unknown-linux-gnu.tar.gz" % MOQ_VERSION,
    ("linux", "aarch64"): "moq-relay-v%s-aarch64-unknown-linux-gnu.tar.gz" % MOQ_VERSION,
}
MOQ_SHA = {
    ("win32", "x86_64"): "e1868718afda70292e5577cb61f22d2846dd9a1d7a9243d2b8354b4183bad4d3",
    ("darwin", "arm64"): "65de25197ab38a0ffdcb3b9864bfbcc1db1f94762cb08f5c7cdcd687195ce535",
    ("linux", "x86_64"): "d99db66dc987b77f2f5a304f2c07176cd1c50ad76e562378c9028274bdc565c7",
    ("linux", "aarch64"): "a2f32526ee9288e10aa711ea9d5a29c5798b17b46714ddd8aa90c5d1d5a3105d",   # 0.16.0: pinned too
}

# 0.9.1: moq-cli -- the native MoQ publisher (ffmpeg | moq import ts). Same
# project and release train as the relay; pinned with its sha256.
# 0.13.1: darwin/arm64 added (SHA256SUMS of moq-cli-v0.11.2, read 2026-09-21).
MOQ_CLI_VERSION = "0.12.1"   # 0.16.0: --connect / --max-age / import verb (see kastr_rtsp.Publisher._args)
MOQ_CLI_BASE = "https://github.com/moq-dev/moq/releases/download/moq-cli-v%s/" % MOQ_CLI_VERSION
MOQ_CLI = {
    ("win32", "x86_64"): ("moq-cli-v%s-x86_64-pc-windows-msvc.zip" % MOQ_CLI_VERSION,
                          "07c818b50c42876ee4bfa1be1a94cc75e5928c0b359d7f35a76f8055606b16f6"),
    ("darwin", "arm64"): ("moq-cli-v%s-aarch64-apple-darwin.tar.gz" % MOQ_CLI_VERSION,
                          "392a26e1ab19d58aaca457fad1e8df9676a572c73a460eed3e8beaa449384966"),
    ("linux", "x86_64"): ("moq-cli-v%s-x86_64-unknown-linux-gnu.tar.gz" % MOQ_CLI_VERSION,
                          "56c016de43847ef1990c82001cbf4174f09450994154813c73bb9cd02cb6302b"),
}

FFMPEG_WIN = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# 0.13.1: macOS (Apple Silicon) ffmpeg -- a placeholder until Kenton pins one.
# Homebrew's ffmpeg is dylib-linked into /opt/homebrew and cannot be copied
# into the bundle, and a Finder-launched .app has a bare PATH, so a bundled
# STATIC arm64 build is the only way RTSP works out of the box on a Mac.
#
# To pin one: download a static arm64 ffmpeg ONCE by hand (evermeet.cx's
# builds, or a static build you compiled yourself), check that
#   file ffmpeg          says "Mach-O 64-bit executable arm64"
#   otool -L ffmpeg      lists only /usr/lib and /System frameworks
# then take `shasum -a 256 <archive>` and replace None with a dict shaped like
# FFMPEG_LINUX minus "tag":
#   FFMPEG_MAC = {"url": "https://.../ffmpeg-<ver>-arm64.zip",
#                 "sha256": "<64 hex chars>"}
# The zip or tarball must contain a file named `ffmpeg`. While this is None
# the script prints the `brew install ffmpeg` hint and KASTR uses the ffmpeg
# it finds on PATH (kastr_rtsp looks in /opt/homebrew/bin too).
FFMPEG_MAC = None

# Linux gets BtbN's static build: the only Linux static provider ffmpeg.org
# itself links to, and the same project behind one of the two Windows sets it
# lists. (johnvansickle.com, the other name people reach for, is no longer
# linked from ffmpeg.org, and its newest release is 7.0.2 from August 2024.)
#
# Pinned to a dated autobuild rather than the floating "latest" tag, and the
# SHA-256 is checked on arrival: every machine that builds KASTR then gets a
# byte-identical ffmpeg, and an upstream artifact that changed under us fails
# the fetch instead of quietly shipping inside a release.
#
# The gpl variant is required rather than preferred -- kastr_rtsp.py encodes
# with libx264, which the lgpl builds leave out.
#
# BtbN keeps one build per month for two years, so this pin eventually 404s.
# When it does, pick a current month-end tag from the releases page and update
# all three fields together; the fetch prints those instructions on failure.
FFMPEG_LINUX_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
FFMPEG_LINUX = {   # 0.8.13: 9.0.1 (release/9.0), matching the Windows essentials build
    "tag": "autobuild-2026-09-09-14-51",
    "asset": "ffmpeg-n9.0.1-27-g9b0578816c-linux64-gpl-9.0.tar.xz",
    "sha256": "899208a8c705cfeea45199377a5926908ec78dbe002de488df8fbdc7425aafd1",
}


def arch():
    m = platform.machine().lower()
    if m in ("amd64", "x86_64"):
        return "x86_64"
    if m in ("arm64", "aarch64"):
        return "arm64" if sys.platform == "darwin" else "aarch64"
    return m


def plat():
    return "win32" if sys.platform == "win32" else (
        "darwin" if sys.platform == "darwin" else "linux")


def download(url):
    print("  downloading %s" % url)
    req = urllib.request.Request(url, headers={"User-Agent": "kastr-fetch"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def verify(blob, want):
    """Refuse an archive whose bytes are not the ones we pinned."""
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise RuntimeError("SHA-256 mismatch -- expected %s, got %s. Refusing "
                           "to unpack it." % (want, got))
    print("  sha256 %s ok" % got[:12])


def make_exec(path):
    if sys.platform == "win32":
        return
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def extract(blob, name, dest):
    """Pull one file out of a zip or tarball, wherever it sits inside."""
    if blob[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            member = next((m for m in z.namelist()
                           if os.path.basename(m) == name), None)
            if not member:
                return False
            with z.open(member) as src, open(dest, "wb") as out:
                out.write(src.read())
    else:
        # 0.13.1: regular files only. The darwin tarballs carry the binary
        # bare (`moq`, `moq-relay`) or under a folder; a macOS-made tar can
        # also hold `._moq` AppleDouble entries, whose basename differs, and
        # a directory entry that happens to share the name must not match.
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as t:
            member = next((m for m in t.getmembers()
                           if m.isfile() and os.path.basename(m.name) == name), None)
            if not member:
                return False
            with t.extractfile(member) as src, open(dest, "wb") as out:
                out.write(src.read())
    make_exec(dest)
    return True


def main():
    os.makedirs(BIN, exist_ok=True)
    p, a = plat(), arch()
    exe = ".exe" if p == "win32" else ""
    print("Fetching helpers for %s/%s into %s" % (p, a, BIN))

    if p == "darwin" and a != "arm64":
        print("NOTE: Intel Macs are unsupported (0.13.1) -- moq-relay and moq-cli "
              "publish only an aarch64-apple-darwin build, so neither helper "
              "will be fetched here and build-mac.sh refuses to build.")

    # ---- moq-relay -------------------------------------------------------
    dest = os.path.join(BIN, "moq-relay" + exe)
    asset = MOQ_ASSETS.get((p, a))
    if not asset:
        print("moq-relay: no published build for %s/%s -- skipping "
              "(relay hosting will be unavailable)." % (p, a))
    elif _current(dest, "moq-relay", MOQ_VERSION):
        print("moq-relay: %s present, skipping" % MOQ_VERSION)
    else:
        try:
            blob = download(MOQ_BASE + asset)
            if (p, a) in MOQ_SHA:
                verify(blob, MOQ_SHA[(p, a)])
            if extract(blob, "moq-relay" + exe, dest):
                _stamp_write("moq-relay", MOQ_VERSION)
                print("moq-relay: %.0f MB -> %s" % (os.path.getsize(dest) / 1e6, dest))
            else:
                print("moq-relay: binary not found inside the archive")
        except Exception as e:
            print("moq-relay: FAILED (%s)" % e)

    # ---- moq-cli (0.9.1) -------------------------------------------------
    dest = os.path.join(BIN, "moq" + exe)
    pin = MOQ_CLI.get((p, a))
    if not pin:
        print("moq-cli: no published build for %s/%s -- RTSP feeds cannot be published without it." % (p, a))
    elif _current(dest, "moq", MOQ_CLI_VERSION):
        print("moq-cli: %s present, skipping" % MOQ_CLI_VERSION)
    else:
        try:
            blob = download(MOQ_CLI_BASE + pin[0])
            verify(blob, pin[1])
            if extract(blob, "moq" + exe, dest):
                _stamp_write("moq", MOQ_CLI_VERSION)
                print("moq-cli: %.0f MB -> %s" % (os.path.getsize(dest) / 1e6, dest))
            else:
                print("moq-cli: binary not found inside the archive")
        except Exception as e:
            print("moq-cli: FAILED (%s)" % e)

    # ---- ffmpeg ----------------------------------------------------------
    dest = os.path.join(BIN, "ffmpeg" + exe)
    if os.path.exists(dest):
        print("ffmpeg: already present, skipping")
    elif p == "win32":
        try:
            if extract(download(FFMPEG_WIN), "ffmpeg.exe", dest):
                print("ffmpeg: %.0f MB -> %s" % (os.path.getsize(dest) / 1e6, dest))
            else:
                print("ffmpeg: binary not found inside the archive")
        except Exception as e:
            print("ffmpeg: FAILED (%s)" % e)
    elif p == "linux" and a == "x86_64":
        try:
            blob = download(FFMPEG_LINUX_BASE + FFMPEG_LINUX["tag"] + "/"
                            + FFMPEG_LINUX["asset"])
            verify(blob, FFMPEG_LINUX["sha256"])
            if extract(blob, "ffmpeg", dest):
                print("ffmpeg: %.0f MB -> %s" % (os.path.getsize(dest) / 1e6, dest))
            else:
                print("ffmpeg: binary not found inside the archive")
        except Exception as e:
            print("ffmpeg: FAILED (%s)" % e)
            print("        If the pinned build has aged out of BtbN's two-year")
            print("        retention, pick a current month-end tag from")
            print("        https://github.com/BtbN/FFmpeg-Builds/releases and")
            print("        update FFMPEG_LINUX at the top of this script.")
    elif p == "darwin" and a == "arm64" and FFMPEG_MAC:
        # 0.13.1: only once FFMPEG_MAC is pinned (see the comment above it).
        try:
            blob = download(FFMPEG_MAC["url"])
            verify(blob, FFMPEG_MAC["sha256"])
            if extract(blob, "ffmpeg", dest):
                print("ffmpeg: %.0f MB -> %s" % (os.path.getsize(dest) / 1e6, dest))
            else:
                print("ffmpeg: binary not found inside the archive")
        except Exception as e:
            print("ffmpeg: FAILED (%s)" % e)
            print("        Re-check FFMPEG_MAC at the top of this script (url + sha256).")
    else:
        how = ("brew install ffmpeg" if p == "darwin"
               else "sudo apt install ffmpeg   # or your distro's equivalent")
        print("ffmpeg: not downloaded on %s -- install it and it will be picked "
              "up from PATH,\n        or copy a static build to %s\n        %s"
              % (p, dest, how))
        if p == "darwin":
            print("        (to bundle it instead, pin FFMPEG_MAC at the top of this script)")

    # ---- browser (0.9.0) ---------------------------------------------------
    # The Chromium the app window runs in (Chrome for Testing, pinned in
    # browser.json). Downloaded into a cache OUTSIDE the tree (~200 MB);
    # build.py stages it into dist/<plat>/browser. `--browser-all` also fetches
    # the other platform's zip so --publish can co-locate both for the fleet.
    try:
        import kastr_browser
        pin = kastr_browser.load_pin()
        plats = list(kastr_browser.PLATFORMS) if "--browser-all" in sys.argv else [kastr_browser.platform_name()]
        for bp in plats:
            if bp not in kastr_browser.PLATFORMS:
                print("browser: no bundled browser for %s (system browser is used there)" % bp)
                continue
            zf = kastr_browser.ensure_zip(bp, pin, log=print)
            print("browser: Chrome for Testing %s for %s -> %s" % (pin["version"], bp, zf))
    except Exception as e:
        print("browser: FAILED (%s) -- build.py will retry the download" % e)

    print("\nDone. Now run: python build.py")


if __name__ == "__main__":
    main()
