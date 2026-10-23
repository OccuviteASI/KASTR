#!/usr/bin/env python3
"""0.21.84: vendor Mozilla's pdf.js into assets/vendor/pdfjs for Share > Presentation (PDF decks).

The presenter's page draws each PDF page into a slide picture with pdf.js; nothing else in KASTR reads PDFs. The page
never touches a CDN: it imports /assets/vendor/pdfjs/pdf.min.mjs and runs /assets/vendor/pdfjs/pdf.worker.min.mjs.

Approved by Kenton 2026-10-23: pdfjs-dist 6.4.299 (Apache-2.0) from registry.npmjs.org. Only the two minified build
files are kept (the rest of the 8.5 MB tarball -- source maps, the unminified builds, the viewer, types -- is never
written). Like assets/npu and assets/mediapipe: the two files are git-ignored, manifest.json + LICENSE.txt are tracked,
and build.py verifies size + sha256 of every pinned file before a build and runs this script when one is missing or
corrupt. Network: registry.npmjs.org only; the tarball is checked against npm's published sha512 integrity before
anything is unpacked, and each kept file against its sha256 pin below.

    python vendor-pdfjs.py           fetch what is missing or corrupt, verify, write the manifest
    python vendor-pdfjs.py --check   verify only (exit 1 on a missing or mismatching file)
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
DEST = os.path.join(HERE, "assets", "vendor", "pdfjs")
MANIFEST = os.path.join(DEST, "manifest.json")
LICENSE = os.path.join(DEST, "LICENSE.txt")
PKG = {
    "package": "pdfjs-dist",
    "version": "6.4.299",
    "license": "Apache-2.0",
    "url": "https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.4.299.tgz",
    # npm's dist.integrity for that version (registry.npmjs.org/pdfjs-dist/6.4.299, read 2026-10-23)
    "integrity": "sha512-AVl138zALtfaAPvADulE0PZThbYzCBS79nL4pOSL/6Sm/4AH5A21BD9VHt97OlCuzJuCpmeZtAtkinisF4Vb1g==",
}
# the files kept (package path -> name here) and their pins
FILES = {
    "build/pdf.min.mjs": ("pdf.min.mjs", "57456c8e0c81e46be31174b499ef77f2b9f5ee46d04412ba627320a36755d4c2", 458904),
    "build/pdf.worker.min.mjs": ("pdf.worker.min.mjs", "9536359f1b8367850d485731ca1d5e45c159a7b7a0912325e539937aa21ceb18", 1264342),
}
LICENSE_PIN = ("LICENSE", "0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594")


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def _file_ok(name, pin, size):
    p = os.path.join(DEST, name)
    try:
        if os.path.getsize(p) != size:
            return False
        with open(p, "rb") as f:
            return sha256(f.read()) == pin
    except OSError:
        return False


def stale():
    return [rel for rel, (name, pin, size) in FILES.items() if not _file_ok(name, pin, size)]


def fetch(rels):
    url = PKG["url"]
    assert url.startswith("https://registry.npmjs.org/"), url
    print("  GET " + url)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "KASTR vendor-pdfjs"}), timeout=300) as r:
        tgz = r.read()
    algo, _, want = PKG["integrity"].partition("-")
    if base64.b64encode(hashlib.new(algo, tgz).digest()).decode() != want:
        raise SystemExit("%s %s: tarball integrity mismatch -- nothing written" % (PKG["package"], PKG["version"]))
    os.makedirs(DEST, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
        out = {}
        for rel in rels:
            name, pin, size = FILES[rel]
            data = tf.extractfile("package/" + rel).read()
            if sha256(data) != pin or len(data) != size:
                raise SystemExit("%s in the tarball does not match its pin -- nothing written" % rel)
            out[name] = data
        if not os.path.exists(LICENSE):
            lic = tf.extractfile("package/" + LICENSE_PIN[0]).read()
            if sha256(lic) == LICENSE_PIN[1]:
                out["LICENSE.txt"] = lic
    for name, data in out.items():   # the rest of the tarball is never written
        p = os.path.join(DEST, name)
        with open(p + ".part", "wb") as f:
            f.write(data)
        os.replace(p + ".part", p)
        print("  %s written (%s bytes)" % (name, format(len(data), ",")))


def write_manifest():
    man = {"source": "%s %s from registry.npmjs.org (Mozilla pdf.js, %s)" % (PKG["package"], PKG["version"], PKG["license"]),
           "license": "LICENSE.txt",
           "runtime": {name: {"sha256": pin, "bytes": size} for (name, pin, size) in FILES.values()},
           "runtime_source": PKG}
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, indent=2)
        f.write("\n")


def main(argv):
    check = "--check" in argv[1:]
    bad = stale()
    if check:
        for rel in FILES:
            print(("BAD  " if rel in bad else "ok   ") + FILES[rel][0])
        return 1 if bad else 0
    if bad:
        fetch(bad)
        bad = stale()
        if bad:
            print("still wrong after the fetch: " + ", ".join(bad))
            return 1
    write_manifest()
    for name, pin, size in FILES.values():
        print("  %-20s %10s bytes  sha256 %s" % (name, format(size, ","), pin))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
