#!/usr/bin/env python3
"""Vendor the person-matting model + the ONNX Runtime Web build KASTR ships under assets/npu (0.21.21).

The camera's background effects can run MODNet (a portrait matting model) through WebNN -- on the NPU when the
computer has one (Intel AI Boost, AMD XDNA, Qualcomm Hexagon...), else on the GPU -- with ONNX Runtime Web driving
WebNN. Nothing is fetched at run time: the page loads /assets/npu/*. This script downloads the pinned files, verifies
each against its sha256 and writes assets/npu/manifest.json. Network: registry.npmjs.org and huggingface.co only.

    python vendor-npu.py                 # fetch what is missing, verify, write the manifest
    python vendor-npu.py --check         # verify only; exit 1 on a mismatch or a missing file
    python vendor-npu.py --from <dir>    # take ort.tgz / modnet_model_fp16.onnx from a local folder first

0.21.40: ort-wasm-simd-threaded.jsep.wasm (28 MB) and modnet_fp16.onnx (13 MB) are no longer tracked in git
(.gitignore). build.py verifies every file manifest.json lists and runs this script when one is missing or does not
match its sha256 -- a missing OR corrupt file is fetched again, and every download is checked before it is written.

Licences: onnxruntime-web is MIT (Microsoft); MODNet is Apache-2.0 (Zhanghan Ke et al., github.com/ZHKKKe/MODNet;
ONNX export by Xenova on Hugging Face). Both texts are written next to the files.
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(ROOT, "assets", "npu")
ORT_VERSION = "1.30.0"
ORT_URL = "https://registry.npmjs.org/onnxruntime-web/-/onnxruntime-web-%s.tgz" % ORT_VERSION
ORT_TGZ_SHA = "d2228df7e4616bc3348bf504ee888f3bec43789a273f0a63f3e68d203ce3bf71"
ORT_FILES = {   # package/dist/<name> -> sha256. The WebNN execution provider lives in the JSEP build: ort.min.mjs loads
    # ort-wasm-simd-threaded.jsep.* as soon as a session asks for "webnn" (the plain 14 MB build cannot run it)
    "ort.min.mjs": "0ca19c223d563f244908feb26712f40333980b07576328c8b4a04d132bbf34ad",
    "ort-wasm-simd-threaded.jsep.mjs": "709853412fd1ffc34247af1e73569227b5b79629c5ca3f59cc39cf7e500e4947",
    "ort-wasm-simd-threaded.jsep.wasm": "3ad23231b5bd6d9dda55a7f84606315e0bf35b6750c28ee993c987c54cacab0f",
}
# 0.21.40: the model URL names the Hugging Face COMMIT (was resolve/main, which moves); that revision's LFS sha256 of
# onnx/model_fp16.onnx is the pin below (huggingface.co/api/models/Xenova/modnet?blobs=true, read 2026-10-09)
MODEL = {"name": "modnet_fp16.onnx",
         "url": "https://huggingface.co/Xenova/modnet/resolve/fa2fa546052fba4c08921230a26cc69a333fca12/onnx/model_fp16.onnx",
         "sha256": "25f165da9bfd30830a575f1f0490f1acd995975cb349bc02f3d79332e1fe5cf6", "input": [1, 3, 288, 512],
         "note": "fp16 weights, float32 input (x/127.5-1, RGB planar) and output (alpha 0..1)"}
MIT = """MIT License

Copyright (c) Microsoft Corporation.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url, local=None):
    if local and os.path.isfile(local):
        with open(local, "rb") as f:
            return f.read()
    print("fetching", url)
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def _sha_file(path):
    try:
        with open(path, "rb") as f:
            return sha(f.read())
    except OSError:
        return None


def _write(path, data):
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def main():
    check = "--check" in sys.argv
    src = sys.argv[sys.argv.index("--from") + 1] if "--from" in sys.argv else None
    os.makedirs(DEST, exist_ok=True)
    bad = []
    want = dict(ORT_FILES)
    want[MODEL["name"]] = MODEL["sha256"]
    missing = [n for n in want if not os.path.isfile(os.path.join(DEST, n))]
    wrong = [n for n in want if n not in missing and _sha_file(os.path.join(DEST, n)) != want[n]]
    if check:
        if missing:
            print("missing:", missing)
        if wrong:
            print("hash mismatch:", wrong)
        if missing or wrong:
            sys.exit(1)
        print("assets/npu ok"); return
    stale = missing + wrong   # 0.21.40: a corrupt file is fetched again, like a missing one
    if any(n in ORT_FILES for n in stale):
        tgz = fetch(ORT_URL, src and os.path.join(src, "ort.tgz"))
        if sha(tgz) != ORT_TGZ_SHA:
            sys.exit("onnxruntime-web tarball hash mismatch")
        with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
            for n in ORT_FILES:
                if n not in stale:
                    continue
                data = tf.extractfile("package/dist/" + n).read()
                if sha(data) != ORT_FILES[n]:
                    sys.exit("%s in the onnxruntime-web tarball does not match its pin -- not written" % n)
                _write(os.path.join(DEST, n), data)
    if MODEL["name"] in stale:
        data = fetch(MODEL["url"], src and os.path.join(src, "modnet_model_fp16.onnx"))
        if sha(data) != MODEL["sha256"]:
            sys.exit("%s hash mismatch (got %s) -- not written" % (MODEL["name"], sha(data)))
        _write(os.path.join(DEST, MODEL["name"]), data)
    sizes = {}
    for n, h in want.items():
        with open(os.path.join(DEST, n), "rb") as f:
            data = f.read()
        sizes[n] = len(data)
        if sha(data) != h:
            bad.append(n)
    if bad:
        print("hash mismatch:", bad); sys.exit(1)
    with open(os.path.join(DEST, "LICENSE-onnxruntime-web.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("onnxruntime-web %s (https://github.com/microsoft/onnxruntime)\n\n%s" % (ORT_VERSION, MIT))
    apache = os.path.join(ROOT, "assets", "mediapipe", "LICENSE.txt")
    with open(os.path.join(DEST, "LICENSE-modnet.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("MODNet: Trimap-Free Portrait Matting in Real Time (Zhanghan Ke et al.), https://github.com/ZHKKKe/MODNet\n"
                "ONNX export: https://huggingface.co/Xenova/modnet -- Apache License 2.0:\n\n")
        with open(apache, encoding="utf-8") as a:
            f.write(a.read())
    man = {"runtime": {"package": "onnxruntime-web", "version": ORT_VERSION, "url": ORT_URL, "tgz_sha256": ORT_TGZ_SHA,
                       "files": {n: {"sha256": h, "bytes": sizes[n]} for n, h in ORT_FILES.items()}, "license": "LICENSE-onnxruntime-web.txt"},
           "model": {**MODEL, "bytes": sizes[MODEL["name"]], "license": "LICENSE-modnet.txt"}}
    with open(os.path.join(DEST, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, indent=2)
    print("assets/npu ready:", ", ".join("%s %.1f MB" % (n, sizes[n] / 1e6) for n in sizes))


if __name__ == "__main__":
    main()
