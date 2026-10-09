#!/usr/bin/env python3
"""Vendor the MediaPipe selfie-segmentation models KASTR ships under assets/mediapipe.

The page never touches a CDN: the WASM runtime (vision_bundle.mjs + wasm/) and the
.tflite models are served from /assets/mediapipe. This script fetches the models
that are missing, verifies every model against the sha256 pins in manifest.json,
and rewrites the manifest with sizes and hashes. Network: storage.googleapis.com
only (the official mediapipe-models bucket).

    python vendor-mediapipe.py            # fetch what is missing, verify, write the manifest
    python vendor-mediapipe.py --repin    # accept new upstream hashes (a "latest" model moved)
    python vendor-mediapipe.py --check    # verify only; exit 1 on a mismatch or a missing file

0.21.40: the WASM runtime is pinned too. wasm/vision_wasm_internal.wasm (9 MB) is no
longer tracked in git (.gitignore); vision_bundle.mjs and wasm/vision_wasm_internal.js
(small) still are. All three come from the npm package @mediapipe/tasks-vision 0.10.14
(matched by sha256 against jsDelivr's file hashes of every published version, 2026-10-09),
whose tarball is checked against npm's published sha512 integrity before anything is
unpacked; each file is then checked against RUNTIME below. A missing or corrupt runtime
file is fetched again (build.py runs this script when its verification fails).
Network for that: registry.npmjs.org only.

Models (Apache-2.0, see assets/mediapipe/LICENSE.txt):
    selfie_segmenter.tflite            general 256x256 model   -> quality "balanced" (0.8.2 default)
    selfie_segmenter_landscape.tflite  144x256 landscape model -> quality "best" (0.15.0)
"""
import base64
import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, "assets", "mediapipe")
MANIFEST = os.path.join(DEST, "manifest.json")
LICENSE = os.path.join(DEST, "LICENSE.txt")
BUCKET = "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
MODELS = {
    "selfie_segmenter.tflite": BUCKET + "selfie_segmenter/float16/latest/selfie_segmenter.tflite",
    "selfie_segmenter_landscape.tflite": BUCKET + "selfie_segmenter_landscape/float16/latest/selfie_segmenter_landscape.tflite",
}
# 0.21.40: the runtime files (package-relative, '/'-separated) -> sha256, and the npm tarball they come from
RUNTIME = {
    "vision_bundle.mjs": "e77f281f9619150d937023c355bae170e9120e3b9e43f1e23a2a7bee07197669",
    "wasm/vision_wasm_internal.js": "9440cf0cc0cea21800e31581ec32aeedcc5fbf9df4509796bbc7d3f99e52ab9c",
    "wasm/vision_wasm_internal.wasm": "f82a8e6c05e08a44cc9f9e7ec5f845935bcbb1b1500ebe8c2f4812fb4e2917dc",
}
RUNTIME_PKG = {
    "package": "@mediapipe/tasks-vision",
    "version": "0.10.14",
    "url": "https://registry.npmjs.org/@mediapipe/tasks-vision/-/tasks-vision-0.10.14.tgz",
    # npm's dist.integrity for that version (registry.npmjs.org/@mediapipe/tasks-vision/0.10.14, read 2026-10-09)
    "integrity": "sha512-vOifgZhkndgybdvoRITzRkIueWWSiCKuEUXXK6Q4FaJsFvRJuwgg++vqFUMlL0Uox62U5aEXFhHxlhV7Ja5e3Q==",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, path):
    assert url.startswith("https://storage.googleapis.com/"), url
    print(f"  GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "KASTR vendor-mediapipe"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path + ".part", "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    os.replace(path + ".part", path)


def _runtime_path(rel):
    return os.path.join(DEST, *rel.split("/"))


def _sha_or_none(path):
    try:
        return sha256(path)
    except OSError:
        return None


def fetch_runtime(stale):
    """0.21.40: (re)write the `stale` runtime files from the pinned npm tarball. Every byte is checked first."""
    url = RUNTIME_PKG["url"]
    assert url.startswith("https://registry.npmjs.org/"), url
    print(f"  GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "KASTR vendor-mediapipe"})
    with urllib.request.urlopen(req, timeout=300) as r:
        tgz = r.read()
    algo, _, want = RUNTIME_PKG["integrity"].partition("-")
    got = base64.b64encode(hashlib.new(algo, tgz).digest()).decode()
    if got != want:
        raise RuntimeError("%s %s tarball integrity mismatch -- nothing unpacked" % (RUNTIME_PKG["package"], RUNTIME_PKG["version"]))
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
        for rel in stale:
            data = tf.extractfile("package/" + rel).read()
            if hashlib.sha256(data).hexdigest() != RUNTIME[rel]:
                raise RuntimeError("%s in the tarball does not match its pin -- not written" % rel)
            p = _runtime_path(rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p + ".part", "wb") as f:
                f.write(data)
            os.replace(p + ".part", p)
            print(f"  {rel} written ({len(data):,d} bytes)")


def main(argv):
    flags = set(argv[1:])
    repin, check = "--repin" in flags, "--check" in flags
    os.makedirs(DEST, exist_ok=True)
    old = {}
    if os.path.exists(MANIFEST):
        try:
            old = json.load(open(MANIFEST, encoding="utf-8")).get("models", {})
        except Exception as e:   # noqa: BLE001
            print("manifest unreadable, rebuilding:", e)
    models, bad = {}, 0
    for name, url in MODELS.items():
        path = os.path.join(DEST, name)
        if not os.path.exists(path):
            if check:
                print(f"MISSING {name}"); bad += 1; continue
            fetch(url, path)
        digest, size = sha256(path), os.path.getsize(path)
        pin = old.get(name, {}).get("sha256")
        state = "new" if not pin else "ok" if pin == digest else "CHANGED"
        if state == "CHANGED" and not repin:
            print(f"MISMATCH {name}: manifest {pin[:16]}.. file {digest[:16]}..  (pass --repin to accept)")
            bad += 1
        print(f"  {name:36s} {size:>9,d} bytes  sha256 {digest}  [{state}]")
        models[name] = {"url": url, "sha256": digest, "bytes": size,
                        "quality": "best" if "landscape" in name else "balanced"}
    # 0.21.40: the runtime is verified against RUNTIME (it used to be recorded as found), and fetched when missing or corrupt
    stale = [rel for rel, pin in RUNTIME.items() if _sha_or_none(_runtime_path(rel)) != pin]
    if stale and not check:
        try:
            fetch_runtime(stale)
        except Exception as e:   # noqa: BLE001
            print("  runtime fetch FAILED:", e)
    runtime = {}
    for rel, pin in RUNTIME.items():
        p = _runtime_path(rel)
        if not os.path.exists(p):
            print(f"  runtime file missing: {rel}"); bad += 1; continue
        digest = sha256(p)
        if digest != pin:
            print(f"MISMATCH {rel}: pinned {pin[:16]}.. file {digest[:16]}.."); bad += 1
        runtime[rel] = {"sha256": digest, "bytes": os.path.getsize(p)}
    if check:
        print("RESULT:", "OK" if not bad else "PROBLEMS")
        return 1 if bad else 0
    if bad:
        print("manifest NOT written (mismatch); nothing else changed")
        return 1
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"source": "https://storage.googleapis.com/mediapipe-models/ (Google MediaPipe, Apache-2.0)",
                   "license": "LICENSE.txt", "models": models, "runtime": runtime,
                   "runtime_source": RUNTIME_PKG}, f, indent=2)
        f.write("\n")
    print("wrote", MANIFEST)
    if not os.path.exists(LICENSE):
        print("NOTE: LICENSE.txt is missing next to the manifest (Apache-2.0 text expected)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
