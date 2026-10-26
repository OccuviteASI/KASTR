# -*- coding: utf-8 -*-
"""v0.21.88 (Kenton, 2026-10-26: "Share > Media file 5-7 s picture freeze = YES, FIX IT NEXT at the source").

The cause (lab 2026-10-26, 3 of 12 plain Media file starts froze 4.8-6.4 s, each with exactly one viewer error
"group timestamp is below the live edge" and one publisher "publish error ... track=video error=remote error: 0"):
when the publisher's video encoder closes -- a demand flap or a reconfigure, the encoder effect's cleanup calls the
producer's cut() with no end -- @moq/hang's producer finished the open group with a GUESSED end (the last frame + the last
frame interval) and wrote it into the video track as the group's end marker. The next encoder's first keyframe can be
earlier than that guess (the interval before it was long: the first still frame, a paused second, timer jitter); the
player's consumer then sees a newer group below its live edge, closes the video track for good and the publisher, with
nobody subscribed, opens an encoder again only when its catalog next changes (~6 s).

The fix (vendor-moq.py PATCHES `group-end-no-guess`): a group finished without a known end ends at its last frame. The
player's own guard stays as it is. After: 26 of 26 lab starts with the worst picture gap 451 ms, no edge error, no publish
error; slide videos 12 of 12 visits without a stall, so 0.21.87's 1.5 s re-subscribe guard is gone."""
import hashlib
import importlib.util
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("vendor_moq", os.path.join(HERE, "vendor-moq.py"))
vendor_moq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vendor_moq)
CONTAINER = os.path.join(vendor_moq.OUT, "@moq", "hang@0.5.2", "es2022", "container.mjs")


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


class GroupEndNoGuess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = read(CONTAINER)
        cls.pt = next(p for p in vendor_moq.PATCHES if p["id"] == "group-end-no-guess")

    def test_declared_on_the_hang_container(self):
        self.assertEqual(self.pt["file"], "@moq/hang@0.5.2/es2022/container.mjs")
        self.assertEqual(self.pt["edits"], [("e??=this.#i!==void 0&&this.#o!==void 0?this.#i+this.#o:void 0",
                                             "/* KASTR-PATCH: group-end-no-guess */e??=this.#i")])

    def test_applied_once_guess_gone(self):
        self.assertEqual(self.js.count("/* KASTR-PATCH: group-end-no-guess */e??=this.#i"), 1)
        self.assertNotIn("this.#i+this.#o", self.js)   # no end past the last frame anywhere in the producer

    def test_the_finish_path_uses_it(self):
        # the producer's group finish: endpoint -> finishGroup (the video end marker) -> timeline end
        i = self.js.index("/* KASTR-PATCH: group-end-no-guess */")
        tail = self.js[i:i + 260]
        self.assertIn("this.#a.finishGroup(this.#t,this.#e?void 0:e)", tail)
        # cut() still writes its marker at the live edge (the largest frame timestamp), never a guess
        self.assertIn("cut(e){this.#d(e),this.#o=void 0;let t=e??this.#s;", self.js)

    def test_player_guard_untouched(self):
        # the consumer keeps refusing a newer group below its live edge -- the fix is that the publisher never builds one
        self.assertEqual(self.js.count('new Error("group timestamp is below the live edge")'), 2)

    def test_manifest_and_check(self):
        with open(vendor_moq.MANIFEST, encoding="utf-8") as f:
            man = json.load(f)
        self.assertIn("group-end-no-guess", man["patches"])
        with open(CONTAINER, "rb") as f:
            self.assertEqual(man["files"]["@moq/hang@0.5.2/es2022/container.mjs"], hashlib.sha256(f.read()).hexdigest())
        self.assertEqual(vendor_moq.patch(check=True, quiet=True), 0)

    def test_publish_uses_this_container(self):
        enc = read(os.path.join(vendor_moq.OUT, "@moq", "publish@0.5.2", "es2022", "encoder-CjcsUSCu.mjs"))
        self.assertIn("new Je.Legacy.Producer(", enc)   # the encoder's producer is the patched one
        self.assertRegex(enc, r'i\.cleanup\(\(\)=>\{e\.closed\.peek\(\)===void 0&&s\.cut\(\)\}\)')   # the endless cut that hit the guess


class GuardRemoved(unittest.TestCase):
    def test_no_resubscribe_guard(self):
        self.assertNotIn("__presVidKick", read(os.path.join(HERE, "moq-watch-lite.html")))
        js = read(os.path.join(HERE, "assets", "kastr-pres.js"))
        self.assertNotIn("vidWatchdog", js)
        self.assertNotIn("vid-kick", js)


if __name__ == "__main__":
    unittest.main()
