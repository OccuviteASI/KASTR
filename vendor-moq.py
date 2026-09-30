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

# 0.21.7: KASTR's edits to the vendored library. Exact-string anchors, each replaced exactly once; the replacement carries
# a /* KASTR-PATCH: <id> */ marker so a file that already has it is left alone (idempotent). mirror() re-applies them after
# every fetch and records post-patch shas + the ids in the manifest; build.py runs `--check`; tests/test_vendor_patch.py
# asserts marker, replacement, anchor gone and sha == manifest.
PATCHES = [
    {"id": "audio-maxage-floor",
     "file": "@moq/watch@0.6.0/es2022/player-DiUmUis6.mjs",
     "why": ("hang's container drops the oldest buffered group when the buffered span exceeds maxAge = delay + buffer; "
             "every 20 ms Opus packet is its own group and legacy audio frames carry no duration, so one skip registered "
             "as a discontinuity: the worklet ring was flushed, the shared sync clock and the decoder reset -- the clipping "
             "every KASTR 0.21.6 viewer heard ('skipping slow group: track=audio' climbing). A 1 s floor on the AUDIO "
             "consumer's maxAge (video keeps the library's budget) turns a late packet into a small gap."),
     "edits": [
        ('#g(t){if(!t.get(this.in.enabled)||t.get(this.sync.in.delay)==="instant")return;let e=t.get(this.source.in.broadcast);if(!e)return;',
         '#g(t){if(!t.get(this.in.enabled)||t.get(this.sync.in.delay)==="instant")return;/* KASTR-PATCH: audio-maxage-floor */this.kastrAudioMaxAge=new u(Math.max(Number(this.sync.out.maxAge.peek())||0,1e3));let e=t.get(this.source.in.broadcast);if(!e)return;'),
        ('priority:w.PRIORITY.audio,maxAge:this.sync.out.maxAge',
         'priority:w.PRIORITY.audio,maxAge:this.kastrAudioMaxAge'),
        ('r=new b.Consumer(e,{format:s,maxAge:this.sync.out.maxAge})',
         'r=new b.Consumer(e,{format:s,maxAge:this.kastrAudioMaxAge})'),
        ('c=new b.Consumer(e,{format:new b.Cmaf.Format(s),maxAge:this.sync.out.maxAge})',
         'c=new b.Consumer(e,{format:new b.Cmaf.Format(s),maxAge:this.kastrAudioMaxAge})'),
     ]},
]


def _sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def patch(check=False, update_manifest=True, quiet=False):
    """Apply PATCHES (check=True: only verify). -> number of files changed. SystemExit on a missing anchor, an anchor
    that occurs more than once, or (check) an unpatched file / a manifest sha that does not match the file."""
    changed = 0
    man = None
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            man = json.load(f)
    for pt in PATCHES:
        path = os.path.join(OUT, *pt["file"].split("/"))
        if not os.path.exists(path):
            raise SystemExit("vendor-moq: %s is missing -- run vendor-moq.py" % pt["file"])
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
        marker = "/* KASTR-PATCH: %s */" % pt["id"]
        applied = marker in text
        if applied:
            for a, b in pt["edits"]:
                if text.count(b) != 1 or a in text:
                    raise SystemExit("vendor-moq: %s carries the %s marker but not its edits (%r)" % (pt["file"], pt["id"], b[:60]))
        elif check:
            raise SystemExit("vendor-moq: %s is NOT patched (%s) -- run vendor-moq.py --patch" % (pt["file"], pt["id"]))
        else:
            for a, b in pt["edits"]:
                n = text.count(a)
                if n != 1:
                    raise SystemExit("vendor-moq: %s anchor x%d in %s: %r" % (pt["id"], n, pt["file"], a[:70]))
                text = text.replace(a, b)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            changed += 1
            if not quiet:
                print("  patched %s (%s)" % (pt["file"], pt["id"]))
        if check and isinstance(man, dict):
            want = (man.get("files") or {}).get(pt["file"])
            have = _sha_file(path)
            if want != have:
                raise SystemExit("vendor-moq: manifest sha for %s is stale (run vendor-moq.py --patch)" % pt["file"])
            if pt["id"] not in (man.get("patches") or []):
                raise SystemExit("vendor-moq: manifest does not list patch %s" % pt["id"])
    if not check and update_manifest and isinstance(man, dict):
        files = man.get("files") or {}
        for pt in PATCHES:
            files[pt["file"]] = _sha_file(os.path.join(OUT, *pt["file"].split("/")))
        man["files"] = files
        man["patches"] = [pt["id"] for pt in PATCHES]
        with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
            json.dump(man, f, indent=1, sort_keys=True)
    if not quiet:
        print("vendor-moq: %d patch(es) %s" % (len(PATCHES), "verified" if check else ("applied" if changed else "already in place")))
    return changed


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
    # 0.21.7: KASTR's own edits, then the shas of what is actually on disk (post-patch)
    patch(update_manifest=False, quiet=True)
    for name in list(files):
        files[name] = _sha_file(os.path.join(OUT, name))
    entries = {spec: local_name(path + ("&" if "?" in path else "?") + "target=" + TARGET)
               for spec, path in PINS.items()}
    manifest = {
        "pins": PINS, "target": TARGET, "entries": entries, "resolved": resolved,
        "files": files, "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": BASE, "patches": [pt["id"] for pt in PATCHES],
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
    if "--patch" in sys.argv:      # 0.21.7: (re)apply KASTR's edits to the vendored files + record their shas
        patch(check=False)
        sys.exit(0)
    if "--check" in sys.argv:      # 0.21.7: build.py -- every patch in place, manifest shas current
        patch(check=True)
        sys.exit(0)
    sys.exit(mirror(force="--force" in sys.argv))
