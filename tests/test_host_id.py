"""0.21.46 (field, Southridge): the host id stays put across launches, and a camera pair restored under an OLD host
segment is adopted under this machine's host (the relay refuses a path the token does not grant).

Run: python -m unittest discover -s tests
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import kastr_serve  # noqa: E402


class HostId(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old = (kastr_serve.STATE_DIR, kastr_serve._HOST_SUFFIX)
        kastr_serve.STATE_DIR, kastr_serve._HOST_SUFFIX = self.dir, None

    def tearDown(self):
        kastr_serve.STATE_DIR, kastr_serve._HOST_SUFFIX = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def fresh(self, node, macs=()):
        kastr_serve._HOST_SUFFIX = None
        with mock.patch.object(uuid, "getnode", return_value=node), mock.patch.object(kastr_serve, "_machine_macs", return_value=set(macs)):
            return kastr_serve.host_slug("obs-svr")

    def test_first_launch_keeps_the_suffix(self):
        self.assertEqual(self.fresh(0x001122331980), "obs-svr-1980")
        rec = json.load(open(os.path.join(self.dir, "host-id")))
        self.assertEqual((rec["suffix"], rec["mac"]), (0x1980, "001122331980"))

    def test_another_adapter_answering_never_moves_it(self):
        self.fresh(0x001122331980)
        self.assertEqual(self.fresh(0x00aabbcc395f, macs=["001122331980", "00aabbcc395f"]), "obs-svr-1980")

    def test_a_random_node_never_moves_it(self):
        self.fresh(0x001122331980)
        self.assertEqual(self.fresh(0x010000000abc), "obs-svr-1980")   # multicast bit = uuid's random fallback

    def test_a_cloned_image_on_other_hardware_gets_its_own(self):
        self.fresh(0x001122331980)
        self.assertEqual(self.fresh(0x00aabbcc395f, macs=["00aabbcc395f"]), "obs-svr-395f")

    def test_cached_for_the_whole_run(self):
        a = self.fresh(0x001122331980)
        with mock.patch.object(uuid, "getnode", return_value=0x00aabbcc395f):
            self.assertEqual(kastr_serve.host_slug("obs-svr"), a)

    def test_the_bridge_learns_the_state_folder_first(self):
        src = open(os.path.join(ROOT, "kastr_serve.py"), encoding="utf-8").read()
        i = src.index("def make_bridge(")
        body = src[i:src.index("return b", i)]
        self.assertLess(body.index("STATE_DIR = state_dir"), body.index("host_slug=host_slug(hostname)"))


class AdoptUnderThisHost(unittest.TestCase):
    def test_adopt_rewrites_an_old_host_segment(self):
        p = open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8").read()
        i = p.index("window.__rtspAdopt = async () => {")
        body = p[i:p.index("window.__rtspRestore", i)]
        self.assertIn("np[0] !== HOSTNAME", body)
        self.assertIn("np[0] = HOSTNAME;", body)
        self.assertIn("extra.name = np.join(\"/\");", body)


if __name__ == "__main__":
    unittest.main()
