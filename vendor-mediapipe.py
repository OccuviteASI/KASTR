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

Models (Apache-2.0, see assets/mediapipe/LICENSE.txt):
    selfie_segmenter.tflite            general 256x256 model   -> quality "balanced" (0.8.2 default)
    selfie_segmenter_landscape.tflite  144x256 landscape model -> quality "best" (0.15.0)
"""
import hashlib
import json
import os
import sys
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
RUNTIME = ["vision_bundle.mjs", os.path.join("wasm", "vision_wasm_internal.js"), os.path.join("wasm", "vision_wasm_internal.wasm")]


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
    runtime = {}
    for rel in RUNTIME:
        p = os.path.join(DEST, rel)
        if os.path.exists(p):
            runtime[rel.replace(os.sep, "/")] = {"sha256": sha256(p), "bytes": os.path.getsize(p)}
        else:
            print(f"  runtime file missing: {rel}")
    if check:
        print("RESULT:", "OK" if not bad else "PROBLEMS")
        return 1 if bad else 0
    if bad:
        print("manifest NOT written (mismatch); nothing else changed")
        return 1
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"source": "https://storage.googleapis.com/mediapipe-models/ (Google MediaPipe, Apache-2.0)",
                   "license": "LICENSE.txt", "models": models, "runtime": runtime}, f, indent=2)
        f.write("\n")
    print("wrote", MANIFEST)
    if not os.path.exists(LICENSE):
        print("NOTE: LICENSE.txt is missing next to the manifest (Apache-2.0 text expected)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
