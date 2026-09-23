#!/usr/bin/env python3
"""Vendor the RNNoise AudioWorklet KASTR uses for background-noise removal.

Why (0.13.1): the page must not load code from a CDN at run time (the 2026-09-09
esm.sh outage, and COEP require-corp refuses cross-origin assets without CORP), and
`vendor-moq.py` is a text-only import rewriter that cannot carry a .wasm. This script
fetches ONE npm tarball, checks its registry integrity, and drops the four files the
page needs under assets/noise/ (served same-origin; build.py ships the whole assets
tree). Nothing else from the package (Speex, NoiseGate, GTCRN) is vendored.

Package: @sapphi-red/web-noise-suppressor (MIT) -- RNNoise (xiph/rnnoise, BSD-3-Clause)
compiled to WebAssembly with an AudioWorklet processor around it.

Usage: python vendor-noise.py [--force]
"""
import base64, hashlib, io, json, os, sys, tarfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "noise")
MANIFEST = os.path.join(OUT, "manifest.json")
PKG = "@sapphi-red/web-noise-suppressor"
VERSION = "0.4.1"
REGISTRY = "https://registry.npmjs.org/"
# package path inside the tarball -> local file name
FILES = {
    "package/dist/index.js":                    "web-noise-suppressor.mjs",
    "package/dist/rnnoise/workletProcessor.js": "rnnoiseWorklet.js",
    "package/dist/rnnoise.wasm":                "rnnoise.wasm",
    "package/dist/rnnoise_simd.wasm":           "rnnoise_simd.wasm",
    "package/LICENSE":                          "LICENSE.txt",
}
RNNOISE_NOTICE = """

----------------------------------------------------------------------
rnnoise.wasm / rnnoise_simd.wasm are RNNoise (https://github.com/xiph/rnnoise),
Copyright (c) 2017 Mozilla, 2003-2004 Mark Borgerding, licensed BSD-3-Clause,
compiled to WebAssembly by @sapphi-red/web-noise-suppressor %s (MIT, above).
Vendored into KASTR by vendor-noise.py; no modifications.
""" % VERSION


def fetch(url, tries=4):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KASTR-vendor/1"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:      # noqa: BLE001 -- retried, then reported
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit("vendor-noise: could not fetch %s (%s)" % (url, last))


def main():
    force = "--force" in sys.argv
    if os.path.exists(MANIFEST) and not force:
        try:
            have = json.load(open(MANIFEST, encoding="utf-8"))
            if have.get("version") == VERSION and all(
                    os.path.exists(os.path.join(OUT, n)) and
                    hashlib.sha256(open(os.path.join(OUT, n), "rb").read()).hexdigest() == h
                    for n, h in have.get("files", {}).items()):
                print("vendor-noise: %s@%s already vendored (--force to refetch)" % (PKG, VERSION))
                return 0
        except Exception:
            pass
    meta = json.loads(fetch(REGISTRY + PKG + "/" + VERSION).decode("utf-8"))
    dist = meta["dist"]
    body = fetch(dist["tarball"])
    algo, want = dist["integrity"].split("-", 1)
    got = base64.b64encode(hashlib.new(algo, body).digest()).decode("ascii")
    if got != want:
        raise SystemExit("vendor-noise: tarball integrity mismatch (%s: %s != %s)" % (algo, got, want))
    os.makedirs(OUT, exist_ok=True)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
        members = {m.name: m for m in tar.getmembers()}
        for src, name in FILES.items():
            m = members.get(src)
            if m is None:
                raise SystemExit("vendor-noise: %s missing from the tarball" % src)
            data = tar.extractfile(m).read()
            if name == "LICENSE.txt":
                data = data.decode("utf-8").rstrip() + RNNOISE_NOTICE
                data = data.encode("utf-8")
            with open(os.path.join(OUT, name), "wb") as f:
                f.write(data)
            files[name] = hashlib.sha256(data).hexdigest()
            print("  %-28s %8d B" % (name, len(data)))
    manifest = {"package": PKG, "version": VERSION, "license": meta.get("license", "MIT"),
                "integrity": dist["integrity"], "files": files,
                "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": REGISTRY}
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    print("vendor-noise: %d files -> %s" % (len(files), os.path.relpath(OUT, HERE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
