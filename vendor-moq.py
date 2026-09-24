#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vendor-moq.py -- mirror the MoQ web library from esm.sh into assets/vendor/esm.

Why (0.8.13): moq-watch-lite.html imported @moq/watch and @moq/publish from
https://esm.sh at RUN time, unpinned. On 2026-09-09 upstream published new
versions that esm.sh could not build, and every installed KASTR opened to a
dead Join gate -- the app's media library simply never arrived. The app must
not depend on a CDN, and it must run the library version we tested.

What this does: for each pinned entry it fetches the esm.sh module, follows the
wrapper's `export * from "/@moq/x@ver/es2022/x.mjs"` and every absolute
`/...?target=es2022` import recursively (semver-range URLs such as
`/@moq/hang@^0.4.2` resolve to ONE concrete file via esm.sh's X-Esm-Path),
saves each file under assets/vendor/esm/ and rewrites the absolute imports to
relative paths. The page maps the original https://esm.sh/... specifiers onto
these files with an import map, so the source lines never change and a
checkout without the vendor folder still works against esm.sh for development.

Usage:  python vendor-moq.py            (skips when the manifest matches the pins)
        python vendor-moq.py --force    (re-mirror)
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from urllib.parse import urlsplit
import posixpath

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "vendor", "esm")
MANIFEST = os.path.join(OUT, "manifest.json")
BASE = "https://esm.sh"
TARGET = "es2022"

# The entries the page imports (specifier -> pinned esm.sh path).
# 0.16.0: the 2026-09-23 train -- @moq/watch 0.6.0 / @moq/publish 0.5.0 /
# @moq/hang 0.5.0 / @moq/net 0.4.0 / @moq/json 0.4.0 (moq-relay 0.15). Breaking:
# Connection.Reload hides `established` (publish/consume through `origin`),
# publish Broadcast takes {origin} not {connection}, <moq-watch> `latency` is
# gone (`delay` + `buffer`), hang catalog `timeline` -> root `archive`/`clock`.
# Pre-0.16 the page ran the 4-8 Sept 2026 versions (watch 0.5.3, publish 0.4.6).
PINS = {
    "https://esm.sh/@moq/watch":            "/@moq/watch@0.6.0",
    "https://esm.sh/@moq/watch/element":    "/@moq/watch@0.6.0/element",
    "https://esm.sh/@moq/publish":          "/@moq/publish@0.5.0",
    "https://esm.sh/@moq/publish/element":  "/@moq/publish@0.5.0/element",
    "https://esm.sh/qrcode-generator@1.4.4": "/qrcode-generator@1.4.4",
    # 0.13.0: the page reads/writes JSON state tracks (Snapshot/Window). 0.16.0:
    # the same range hang/watch request (^0.4.0), so the page shares the one
    # vendored @moq/json module instance with the library.
    "https://esm.sh/@moq/json":             "/@moq/json@^0.4.0",
}

# 0.16.0: relative sibling chunks ("./name-hash.mjs") inside a vendored bundle
REL_RE = re.compile(r"(?<=[\"'])(\./[A-Za-z0-9_.-]+\.mjs)(?=[\"'])")
IMPORT_RE = re.compile(
    r'(?P<pre>\b(?:import|export)\s*(?:[^;"\'`]*?\bfrom\s*)?|\bimport\s*\(\s*)'
    r'(?P<q>["\'])(?P<path>/[^"\']+)(?P=q)')


def fetch(url, tries=4):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KASTR-vendor/1"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read(), dict(r.headers)
        except Exception as e:      # noqa: BLE001 -- retried, then reported
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit("vendor-moq: could not fetch %s (%s)" % (url, last))


def local_name(path):
    """/@moq/hang@^0.4.2?target=es2022 -> @moq/hang@^0.4.2.target-es2022.mjs
    /@moq/hang@0.4.3/es2022/hang.mjs   -> @moq/hang@0.4.3/es2022/hang.mjs"""
    u = urlsplit(path)
    p = u.path.lstrip("/")
    if u.query:
        p += "." + u.query.replace("=", "-").replace("&", ".")
    if not p.endswith((".mjs", ".js", ".css", ".json", ".wasm")):
        p += ".mjs"
    return p


def rel(from_name, to_name):
    d = os.path.dirname(from_name)
    r = os.path.relpath(to_name, d if d else ".").replace(os.sep, "/")
    return r if r.startswith(".") else "./" + r


def mirror(force=False):
    want = {"pins": PINS, "target": TARGET}
    if not force and os.path.exists(MANIFEST):
        try:
            with open(MANIFEST, encoding="utf-8") as f:
                have = json.load(f)
            if have.get("pins") == PINS and have.get("target") == TARGET and all(
                    os.path.exists(os.path.join(OUT, fn)) for fn in have.get("files", {})):
                print("vendor-moq: assets/vendor/esm is current (%d files)" % len(have["files"]))
                return 0
        except Exception:
            pass
    os.makedirs(OUT, exist_ok=True)
    queue = []
    for spec, path in PINS.items():
        p = path + ("&" if "?" in path else "?") + "target=" + TARGET
        queue.append(p)
    seen = {}          # request path -> local file name
    files = {}         # local name -> sha256
    resolved = {}
    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        name = local_name(path)
        seen[path] = name
        body, headers = fetch(BASE + path)
        text = body.decode("utf-8")
        esm_path = headers.get("X-Esm-Path") or headers.get("x-esm-path")
        if esm_path:
            resolved[path] = esm_path
        # rewrite absolute imports
        def sub(m):
            tgt = m.group("path")
            if tgt not in seen and tgt not in queue:
                queue.append(tgt)
            return m.group("pre") + m.group("q") + rel(name, local_name(tgt)) + m.group("q")
        text2 = IMPORT_RE.sub(sub, text)
        # 0.16.0: the 0.5/0.6 bundles reference their sibling chunks RELATIVELY
        # ("./video-<hash>.mjs" -- a static import, a dynamic import() or a worker
        # URL). They resolve against the vendored file's own folder, so they need
        # no rewrite -- but they must be fetched, from the same esm.sh folder.
        base_dir = posixpath.dirname(urlsplit(esm_path or path).path)
        for relref in set(REL_RE.findall(text2)):
            tgt = posixpath.normpath(posixpath.join(base_dir, relref))
            if not tgt.startswith("/"):
                tgt = "/" + tgt
            if tgt not in seen and tgt not in queue:
                queue.append(tgt)
        if re.search(r'["\'`]https?://esm\.sh', text2):
            # a stray absolute URL in code would defeat the purpose: refuse
            # (the leading `/* esm.sh - ... */` banner comment is fine)
            raise SystemExit("vendor-moq: %s still references esm.sh after rewrite" % path)
        dest = os.path.join(OUT, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="\n") as f:
            f.write(text2)
        files[name] = hashlib.sha256(text2.encode("utf-8")).hexdigest()
        print("  %-64s %7d B" % (name, len(text2)))
    # final audit: no absolute /@ imports left anywhere
    for name in files:
        with open(os.path.join(OUT, name), encoding="utf-8") as f:
            if re.search(r'from\s*["\']/@|import\s*["\']/@|import\(\s*["\']/@', f.read()):
                raise SystemExit("vendor-moq: %s keeps an absolute import" % name)
    entries = {spec: local_name(path + ("&" if "?" in path else "?") + "target=" + TARGET)
               for spec, path in PINS.items()}
    manifest = {
        "pins": PINS, "target": TARGET, "entries": entries, "resolved": resolved,
        "files": files, "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": BASE,
    }
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    # 0.16.0: prune what the new manifest no longer lists (a bump used to leave the
    # old @moq/*@x.y.z trees behind, shipped in every build).
    keep = {str(k).replace(os.sep, "/") for k in files} | {"manifest.json"}
    pruned = 0
    for root, dirs, fns in os.walk(OUT, topdown=False):
        for fn in fns:
            full = os.path.join(root, fn)
            relp = os.path.relpath(full, OUT).replace(os.sep, "/")   # (not `rel`: that is the module-level helper `sub` closes over)
            if relp not in keep:
                os.remove(full)
                pruned += 1
                print("  pruned %s" % relp)
        if root != OUT and not os.listdir(root):
            try:
                os.rmdir(root)
            except OSError:
                pass   # an empty folder Windows still holds open is harmless
    print("vendor-moq: %d files -> %s (%d pruned)" % (len(files), os.path.relpath(OUT, HERE), pruned))
    return 0


def importmap():
    """The import map the page needs, as JSON text (used by the page patch)."""
    with open(MANIFEST, encoding="utf-8") as f:
        man = json.load(f)
    return json.dumps({"imports": {k: "/assets/vendor/esm/" + v for k, v in man["entries"].items()}}, indent=1)


if __name__ == "__main__":
    if "--importmap" in sys.argv:
        print(importmap())
        sys.exit(0)
    sys.exit(mirror(force="--force" in sys.argv))
