"""0.21.40: the shipped templates are tracked (extras/<plat>/), the Windows ffmpeg is pinned, and the large vendored
binaries are verified by sha256 instead of living in git. No network, no build: everything runs on scratch trees.

Run: python -m unittest tests.test_release_extras
"""
import configparser
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build            # noqa: E402
import kastr_release    # noqa: E402

EXTRAS = os.path.join(ROOT, "extras")


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, fn))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _quiet():
    return contextlib.redirect_stdout(io.StringIO())


class Templates(unittest.TestCase):
    """extras/<plat>/ holds exactly what kastr_release.EXTRAS says each platform ships."""

    def test_every_listed_template_is_tracked(self):
        for plat in ("windows", "linux"):
            names = kastr_release.EXTRAS[build.PLATFORM_API_KEY[plat]]
            self.assertEqual(sorted(build.template_files(plat)), sorted(names), plat)

    def test_kastr_ini_templates_parse_and_carry_defaults(self):
        for plat in ("windows", "linux"):
            cp = configparser.ConfigParser()
            cp.read(os.path.join(EXTRAS, plat, "kastr.ini"), encoding="utf-8-sig")
            self.assertTrue(cp.has_section("streamer"), plat)
            s = cp["streamer"]
            self.assertEqual(s.get("port"), "8000", plat)   # kastr.port_explicit relies on the template's 8000
            self.assertEqual(s.get("page"), "/app.html", plat)
            self.assertNotIn("mode", s, plat)               # a template never pins a mode
            self.assertNotIn("ondemand", s, plat)

    def test_linux_templates_are_lf_and_install_sh_is_a_shell_script(self):
        for name in os.listdir(os.path.join(EXTRAS, "linux")):
            self.assertNotIn(b"\r\n", _read(os.path.join(EXTRAS, "linux", name)), name)
        self.assertTrue(_read(os.path.join(EXTRAS, "linux", "install.sh")).startswith(b"#!/bin/sh\n"))

    def test_gitattributes_keeps_linux_templates_lf(self):
        with open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8") as f:
            self.assertIn("extras/linux/* text eol=lf", f.read())


class Scratch(unittest.TestCase):
    """A scratch dist/ + extras/ tree."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr-extras-")
        self.dist = os.path.join(self.tmp, "dist")
        self.tpl = os.path.join(self.tmp, "extras")
        _write(os.path.join(self.tpl, "windows", "kastr.ini"), "[streamer]\nport = 8000\n; TEMPLATE-WIN\n")
        _write(os.path.join(self.tpl, "linux", "kastr.ini"), "[streamer]\nport = 8000\n; TEMPLATE-LINUX\n")
        _write(os.path.join(self.tpl, "linux", "README.txt"), "README TEMPLATE\n")
        _write(os.path.join(self.tpl, "linux", "install.sh"), "#!/bin/sh\necho template\n")
        _write(os.path.join(self.tpl, "linux", "kastr.svg"), "<svg/>\n")
        self.edited = "[streamer]\nrelay = http://operator.example:4443\nmode = relay\n"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plat_folder(self, plat, version="9.9.9"):
        folder = os.path.join(self.dist, plat)
        _write(os.path.join(folder, build.PLATFORM_UPDATE_BINARY[plat]), b"binary")
        _write(os.path.join(folder, build.BUILT_MARKER), version + "\n")
        return folder


class StageTemplates(Scratch):
    def test_seeds_kastr_ini_only_when_absent(self):
        folder = os.path.join(self.dist, "windows")
        with _quiet():
            self.assertEqual(build.stage_templates("windows", folder, self.tpl), ["kastr.ini"])
        self.assertIn(b"TEMPLATE-WIN", _read(os.path.join(folder, "kastr.ini")))

    def test_never_overwrites_the_live_config(self):
        folder = os.path.join(self.dist, "windows")
        _write(os.path.join(folder, "kastr.ini"), self.edited)
        with _quiet():
            self.assertEqual(build.stage_templates("windows", folder, self.tpl), [])
        self.assertEqual(_read(os.path.join(folder, "kastr.ini")), self.edited.encode())

    def test_refreshes_shipped_only_files_that_differ(self):
        folder = os.path.join(self.dist, "linux")
        _write(os.path.join(folder, "kastr.ini"), self.edited)
        _write(os.path.join(folder, "README.txt"), "stale readme\n")
        shutil.copyfile(os.path.join(self.tpl, "linux", "kastr.svg"), os.path.join(folder, "kastr.svg"))
        with _quiet():
            wrote = build.stage_templates("linux", folder, self.tpl)
        self.assertEqual(sorted(wrote), ["README.txt", "install.sh"])   # svg identical, kastr.ini live
        self.assertEqual(_read(os.path.join(folder, "README.txt")), b"README TEMPLATE\n")
        self.assertEqual(_read(os.path.join(folder, "kastr.ini")), self.edited.encode())


class ReleaseZip(Scratch):
    def test_zip_carries_the_template_not_the_hosts_edited_ini(self):
        folder = self._plat_folder("windows")
        _write(os.path.join(folder, "kastr.ini"), self.edited)
        _write(os.path.join(folder, "updates", "linux", "extras", "kastr.ini"), "stale feed copy\n")
        out = os.path.join(self.tmp, "w.zip")
        with _quiet():
            n = build.write_platform_zip("windows", "9.9.9", out, root=self.dist, templates=self.tpl)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            self.assertEqual(n, len(names))
            self.assertIn(b"TEMPLATE-WIN", z.read("windows/kastr.ini"))
            self.assertIn(b"TEMPLATE-LINUX", z.read("windows/updates/linux/extras/kastr.ini"))
            self.assertNotIn(b"operator.example", b"".join(z.read(x) for x in names))
        self.assertEqual(_read(os.path.join(folder, "kastr.ini")), self.edited.encode())   # dist untouched

    def test_zip_adds_templates_the_folder_lacks_with_exec_bit_on_install_sh(self):
        self._plat_folder("linux")
        out = os.path.join(self.tmp, "l.zip")
        with _quiet():
            build.write_platform_zip("linux", "9.9.9", out, root=self.dist, templates=self.tpl)
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
            for name in ("kastr.ini", "README.txt", "install.sh", "kastr.svg", "KASTR", build.BUILT_MARKER):
                self.assertIn("linux/" + name, names)
            self.assertEqual((z.getinfo("linux/install.sh").external_attr >> 16) & 0o777, 0o755)
            self.assertEqual((z.getinfo("linux/README.txt").external_attr >> 16) & 0o111, 0)
            self.assertNotIn("linux/updates/windows/extras/kastr.ini", names)   # no updates/ folder -> none invented


class PublishFeed(Scratch):
    def test_feed_extras_come_from_the_templates(self):
        for plat in ("windows", "linux"):
            self._plat_folder(plat)
            _write(os.path.join(self.dist, plat, "kastr.ini"), self.edited)
        with _quiet():
            upd = build.publish_feed("9.9.9", ["windows", "linux"], root=self.dist, templates=self.tpl)
        self.assertIn(b"TEMPLATE-WIN", _read(os.path.join(upd, "windows", "extras", "kastr.ini")))
        self.assertIn(b"TEMPLATE-LINUX", _read(os.path.join(upd, "linux", "extras", "kastr.ini")))
        self.assertEqual(_read(os.path.join(upd, "linux", "extras", "install.sh")), b"#!/bin/sh\necho template\n")
        with open(os.path.join(upd, "latest.json"), encoding="utf-8") as f:
            man = json.load(f)
        self.assertEqual(sorted(man["platforms"]["linux"]["extras"]), ["README.txt", "install.sh", "kastr.ini", "kastr.svg"])
        self.assertEqual(man["platforms"]["win32"]["extras"], ["kastr.ini"])

    def test_host_assembler_finds_the_published_templates(self):
        self._plat_folder("linux")
        with _quiet():
            upd = build.publish_feed("9.9.9", ["linux"], root=self.dist, templates=self.tpl)
        got = kastr_release.extras_manifest(os.path.dirname(upd), "linux")
        self.assertEqual(sorted(got), ["README.txt", "install.sh", "kastr.ini", "kastr.svg"])
        self.assertEqual(got["kastr.ini"]["sha256"],
                         hashlib.sha256(_read(os.path.join(self.tpl, "linux", "kastr.ini"))).hexdigest())


class FfmpegPin(unittest.TestCase):
    def test_windows_ffmpeg_is_pinned_and_verified(self):
        fh = _load("fetch_helpers", "fetch-helpers.py")
        pin = fh.FFMPEG_WIN
        self.assertIsInstance(pin, dict)
        self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("/%s/" % pin["version"], pin["url"])
        self.assertIn("ffmpeg-%s-essentials_build.zip" % pin["version"], pin["url"])
        self.assertNotIn("release-essentials", pin["url"])   # the floating URL is gone
        with open(os.path.join(ROOT, "fetch-helpers.py"), encoding="utf-8") as f:
            self.assertIn('verify(blob, FFMPEG_WIN["sha256"])', f.read())


class Vendored(unittest.TestCase):
    """build.verify_vendored / ensure_vendored on scratch manifests shaped like assets/npu and assets/mediapipe."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr-vendored-")
        self.blobs = {"runtime.wasm": b"\0asm" + b"x" * 64, "model.onnx": b"onnx" * 32,
                      "wasm/inner.wasm": b"\0asm" + b"y" * 32, "seg.tflite": b"tfl3" * 8}
        for rel, data in self.blobs.items():
            _write(os.path.join(self.tmp, "npu" if rel in ("runtime.wasm", "model.onnx") else "mp", *rel.split("/")), data)

        def rec(rel):
            return {"sha256": hashlib.sha256(self.blobs[rel]).hexdigest(), "bytes": len(self.blobs[rel])}
        self.npu = os.path.join(self.tmp, "npu", "manifest.json")
        _write(self.npu, json.dumps({"runtime": {"files": {"runtime.wasm": rec("runtime.wasm")}},
                                     "model": dict(rec("model.onnx"), name="model.onnx")}))
        self.mp = os.path.join(self.tmp, "mp", "manifest.json")
        _write(self.mp, json.dumps({"models": {"seg.tflite": dict(rec("seg.tflite"), url="https://x")},
                                    "runtime": {"wasm/inner.wasm": rec("wasm/inner.wasm")},
                                    "runtime_source": {"package": "p", "version": "1"}}))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_intact_tree_passes(self):
        self.assertEqual(len(build.vendored_files(self.npu)), 2)
        self.assertEqual(len(build.vendored_files(self.mp)), 2)   # runtime_source is not a file
        self.assertEqual(build.verify_vendored(self.npu), [])
        self.assertEqual(build.verify_vendored(self.mp), [])

    def test_missing_file_is_flagged(self):
        os.remove(os.path.join(self.tmp, "npu", "model.onnx"))
        bad = build.verify_vendored(self.npu)
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad[0].startswith("missing:"), bad)

    def test_corrupt_file_of_the_right_size_is_flagged(self):
        p = os.path.join(self.tmp, "mp", "wasm", "inner.wasm")
        data = bytearray(_read(p))
        data[-1] ^= 0xFF
        _write(p, bytes(data))
        bad = build.verify_vendored(self.mp)
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad[0].startswith("sha256 mismatch:"), bad)

    def test_truncated_file_is_flagged(self):
        _write(os.path.join(self.tmp, "npu", "runtime.wasm"), b"\0asm")
        self.assertTrue(build.verify_vendored(self.npu)[0].startswith("wrong size:"))

    def test_missing_manifest_is_flagged(self):
        self.assertTrue(build.verify_vendored(os.path.join(self.tmp, "nope", "manifest.json")))

    def test_ensure_runs_the_vendor_script_only_when_needed_and_fails_if_it_cannot_repair(self):
        ran = []
        with _quiet():
            build.ensure_vendored(vendored=[(self.npu, "vendor-npu.py"), (self.mp, "vendor-mediapipe.py")], run=ran.append)
        self.assertEqual(ran, [])
        os.remove(os.path.join(self.tmp, "mp", "seg.tflite"))

        def repair(script):
            ran.append(script)
            _write(os.path.join(self.tmp, "mp", "seg.tflite"), self.blobs["seg.tflite"])
        with _quiet():
            build.ensure_vendored(vendored=[(self.npu, "vendor-npu.py"), (self.mp, "vendor-mediapipe.py")], run=repair)
        self.assertEqual(ran, ["vendor-mediapipe.py"])
        os.remove(os.path.join(self.tmp, "npu", "runtime.wasm"))
        with _quiet(), self.assertRaises(SystemExit):
            build.ensure_vendored(vendored=[(self.npu, "vendor-npu.py")], run=lambda s: None)

    def test_every_untracked_binary_is_pinned_by_a_manifest(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
            ignored = [ln.strip().lstrip("/") for ln in f if re.match(r"^/?assets/(npu|mediapipe)/", ln.strip())]
        self.assertTrue(ignored)
        pinned = {os.path.relpath(p, ROOT).replace(os.sep, "/") for m, _ in build.VENDORED for p, _, _ in build.vendored_files(m)}
        for rel in ignored:
            self.assertIn(rel, pinned)


if __name__ == "__main__":
    unittest.main()
