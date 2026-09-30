"""0.21.7: the vendored @moq/watch player carries KASTR's edits (vendor-moq.py PATCHES) -- marker present, every
replacement exactly once, every anchor gone, manifest sha == the file, manifest lists the patch id.
Run: python tests/test_vendor_patch.py  (or python -m unittest tests.test_vendor_patch)"""
import hashlib
import importlib.util
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vendor_moq", os.path.join(HERE, "vendor-moq.py"))
vendor_moq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vendor_moq)


class VendorPatchTest(unittest.TestCase):
    def test_patches_applied(self):
        with open(vendor_moq.MANIFEST, encoding="utf-8") as f:
            man = json.load(f)
        self.assertTrue(vendor_moq.PATCHES, "no patches declared")
        for pt in vendor_moq.PATCHES:
            path = os.path.join(vendor_moq.OUT, *pt["file"].split("/"))
            self.assertTrue(os.path.exists(path), pt["file"])
            with open(path, encoding="utf-8", newline="") as f:
                text = f.read()
            self.assertIn("/* KASTR-PATCH: %s */" % pt["id"], text)
            for a, b in pt["edits"]:
                self.assertEqual(text.count(b), 1, b[:60])
                self.assertNotIn(a, text, a[:60])
            with open(path, "rb") as f:
                sha = hashlib.sha256(f.read()).hexdigest()
            self.assertEqual(man["files"].get(pt["file"]), sha, "manifest sha stale for " + pt["file"])
            self.assertIn(pt["id"], man.get("patches") or [])

    def test_check_mode_passes(self):
        self.assertEqual(vendor_moq.patch(check=True, quiet=True), 0)

    def test_audio_floor_uses_signal_class(self):
        # the floor must be a Signal (the subscribe helper calls .peek() on maxAge) -- `u` is the Signal import
        path = os.path.join(vendor_moq.OUT, "@moq", "watch@0.6.0", "es2022", "player-DiUmUis6.mjs")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Signal as u", text[:1500])
        self.assertIn("this.kastrAudioMaxAge=new u(Math.max(", text)
        self.assertEqual(text.count("maxAge:this.kastrAudioMaxAge"), 3)
        # video keeps the library's budget
        self.assertGreaterEqual(text.count("maxAge:this.sync.out.maxAge"), 3)


if __name__ == "__main__":
    unittest.main()
