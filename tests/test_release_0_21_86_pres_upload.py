"""0.21.86: the same slide uploaded twice at once no longer crashes the presentation store on Windows."""
import io
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import kastr_pres as kp  # noqa: E402


class SlowBody(io.BytesIO):
    """Hands its bytes over in two halves: both uploads hold their half-written file open together, then the one told to
    wait finishes only after the other has landed -- the moment that crashed on Windows."""

    def __init__(self, data, both, after=None):
        super().__init__(data)
        self.both, self.after, self.half = both, after, len(data) // 2

    def read(self, n=-1):
        if self.tell() == 0:
            return super().read(self.half)
        if self.tell() == self.half:
            self.both.wait(5)
            if self.after is not None:
                self.after.wait(5)
        return super().read(n)


class DoubleUpload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr-pres-")
        self.st = kp.Store(self.tmp)
        self.did, self.tok, _ = self.st.create("r", "d", 2)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def leftovers(self):
        return [f for f in os.listdir(os.path.join(self.tmp, "pres", self.did)) if f.endswith(".part")]

    def test_two_uploads_of_one_slide_at_once(self):
        data = b"k" * 200000
        both, first_done, got = threading.Barrier(2), threading.Event(), []

        def up(after, done=None):
            got.append(self.st.put(self.did, self.tok, "s0.bin", SlowBody(data, both, after), len(data)))
            if done:
                done.set()

        ts = [threading.Thread(target=up, args=(None, first_done)), threading.Thread(target=up, args=(first_done,))]
        for t in ts:
            t.start()
        for t in ts:
            t.join(10)
        self.assertEqual(got, [(200, "ok"), (200, "ok")])
        with open(self.st.path(self.did, "s0.bin"), "rb") as f:
            self.assertEqual(f.read(), data)
        self.assertEqual(self.leftovers(), [])

    def test_a_held_slide_is_waited_out(self):
        self.assertEqual(self.st.put(self.did, self.tok, "s0.bin", io.BytesIO(b"a" * 10), 10), (200, "ok"))
        real, calls = os.replace, []

        def busy_twice(src, dst):   # what Windows does while a viewer has the slide open
            calls.append(dst)
            if len(calls) <= 2:
                raise PermissionError(13, "in use")
            return real(src, dst)

        with mock.patch.object(kp.os, "replace", busy_twice), mock.patch.object(kp.time, "sleep"):
            self.assertEqual(self.st.put(self.did, self.tok, "s0.bin", io.BytesIO(b"b" * 10), 10), (200, "ok"))
        self.assertEqual(len(calls), 3)
        with open(self.st.path(self.did, "s0.bin"), "rb") as f:
            self.assertEqual(f.read(), b"b" * 10)
        self.assertEqual(self.leftovers(), [])

    def test_a_slide_that_stays_busy_is_an_answer_not_a_crash(self):
        with mock.patch.object(kp.os, "replace", side_effect=PermissionError(13, "in use")), mock.patch.object(kp.time, "sleep"):
            code, msg = self.st.put(self.did, self.tok, "s1.bin", io.BytesIO(b"c" * 10), 10)
        self.assertEqual(code, 503)
        self.assertIn("busy", msg)
        self.assertIsNone(self.st.path(self.did, "s1.bin"))
        self.assertEqual(self.leftovers(), [])

    def test_short_upload_leaves_nothing(self):
        self.assertEqual(self.st.put(self.did, self.tok, "s1.bin", io.BytesIO(b"xy"), 5)[0], 400)
        self.assertEqual(self.leftovers(), [])


class PageSharesOneUpload(unittest.TestCase):
    def test_callers_at_the_same_time_share_one_try(self):
        with open(os.path.join(ROOT, "assets", "kastr-pres.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("if (!m.busy[i]) m.busy[i] = doSlide(i).finally(", js)
        self.assertIn("busy: [],", js)


if __name__ == "__main__":
    unittest.main()
