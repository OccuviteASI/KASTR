#!/usr/bin/env python3
"""0.21.84 (prototype): vendor Mozilla's pdf.js into assets/vendor/pdfjs for Share > Presentation (PDF decks).

The presenter's page draws each PDF page into a picture with pdf.js (Apache-2.0); nothing else in KASTR reads PDFs.
The page never touches a CDN: it imports /assets/vendor/pdfjs/pdf.mjs and runs /assets/vendor/pdfjs/pdf.worker.mjs.
Without these two files the Presentation picker still takes PowerPoint decks and says PDFs need this step.

NOT YET APPROVED -- nothing in the repo runs this script and the folder is git-ignored. Two sources:

    python vendor-pdfjs.py --pin            fetch pdfjs-dist PINNED_VERSION's tarball from registry.npmjs.org (~6 MB
                                            download, ~3.3 MB unpacked for the two files), check npm's sha512 integrity,
                                            print the sha256 of both files to pin in FILES below, then write them
    python vendor-pdfjs.py                  the same, but refuses unless FILES carries the pins
    python vendor-pdfjs.py --from-firefox <omni.ja>
                                            LAB ONLY: copy the two files out of a Firefox install's omni.ja (Firefox
                                            ships pdf.js as its PDF viewer -- the same Mozilla code, MOZCENTRAL build);
                                            used for the 0.21.84 prototype lab, never for a release
    python vendor-pdfjs.py --check          verify only (exit 1 when a file is missing or does not match its pin)
"""
import base64
import hashlib
import io
import json
import os
import sys
import tarfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, "assets", "vendor", "pdfjs")
MANIFEST = os.path.join(DEST, "manifest.json")
PINNED_VERSION = ""   # chosen at approval time (the prototype lab ran pdf.js 6.3.72): the newest pdfjs-dist the bundled Chrome runs
FILES = {   # package-relative path -> sha256 (filled in by --pin, reviewed, committed)
    "build/pdf.min.mjs": None,
    "build/pdf.worker.min.mjs": None,
}
OUT_NAMES = {"build/pdf.min.mjs": "pdf.mjs", "build/pdf.worker.min.mjs": "pdf.worker.mjs"}
FIREFOX_NAMES = {"chrome/pdfjs/content/build/pdf.mjs": "pdf.mjs", "chrome/pdfjs/content/build/pdf.worker.mjs": "pdf.worker.mjs"}
LICENSE = """pdf.js -- Copyright Mozilla Foundation. Licensed under the Apache License, Version 2.0
(http://www.apache.org/licenses/LICENSE-2.0). Unmodified files from %s.
"""


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def write(files, source):
    os.makedirs(DEST, exist_ok=True)
    man = {"source": source, "files": {}}
    for name, data in files.items():
        p = os.path.join(DEST, name)
        with open(p + ".part", "wb") as f:
            f.write(data)
        os.replace(p + ".part", p)
        man["files"][name] = {"sha256": sha256(data), "bytes": len(data)}
        print("  %s  %s  %d bytes" % (name, sha256(data), len(data)))
    with open(os.path.join(DEST, "LICENSE.txt"), "w", encoding="utf-8") as f:
        f.write(LICENSE % source)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)


def from_firefox(omni):
    z = zipfile.ZipFile(omni)
    out = {}
    for src, dst in FIREFOX_NAMES.items():
        out[dst] = z.read(src)
    head = out["pdf.mjs"][:600].decode("utf-8", "replace")
    ver = head.split("pdfjsVersion = ")[1].split()[0] if "pdfjsVersion = " in head else "?"
    write(out, "Firefox omni.ja (%s), pdf.js %s -- LAB ONLY" % (os.path.basename(os.path.dirname(omni)), ver))


def from_npm(pin):
    if not PINNED_VERSION:
        raise SystemExit("PINNED_VERSION is not set yet -- pick the pdfjs-dist version at approval time")
    meta_url = "https://registry.npmjs.org/pdfjs-dist/" + PINNED_VERSION
    with urllib.request.urlopen(urllib.request.Request(meta_url, headers={"User-Agent": "KASTR vendor-pdfjs"}), timeout=60) as r:
        meta = json.loads(r.read())
    url, integ = meta["dist"]["tarball"], meta["dist"]["integrity"]
    assert url.startswith("https://registry.npmjs.org/"), url
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "KASTR vendor-pdfjs"}), timeout=300) as r:
        tgz = r.read()
    algo, _, want = integ.partition("-")
    if base64.b64encode(hashlib.new(algo, tgz).digest()).decode() != want:
        raise SystemExit("pdfjs-dist %s: tarball integrity mismatch -- nothing written" % PINNED_VERSION)
    out = {}
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
        for rel, dst in OUT_NAMES.items():
            data = tf.extractfile("package/" + rel).read()
            if FILES.get(rel) and sha256(data) != FILES[rel]:
                raise SystemExit("%s does not match its pin -- nothing written" % rel)
            if not FILES.get(rel) and not pin:
                raise SystemExit("%s has no sha256 pin yet: run with --pin, review, commit the pins" % rel)
            out[dst] = data
    write(out, "npm pdfjs-dist %s (%s)" % (PINNED_VERSION, integ))


def check():
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError):
        print("no assets/vendor/pdfjs/manifest.json")
        return 1
    bad = 0
    for name, info in man.get("files", {}).items():
        try:
            with open(os.path.join(DEST, name), "rb") as f:
                ok = sha256(f.read()) == info.get("sha256")
        except OSError:
            ok = False
        print(("ok   " if ok else "BAD  ") + name)
        bad += 0 if ok else 1
    return 1 if bad else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--check" in a:
        sys.exit(check())
    if "--from-firefox" in a:
        from_firefox(a[a.index("--from-firefox") + 1])
    else:
        from_npm("--pin" in a)
