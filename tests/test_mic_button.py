"""0.21.41: the microphone's own mute button (Windows endpoint mute + WebHID telephony headsets) drives KASTR's mic.

Run: python -m unittest discover -s tests
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kastr_micmute   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class Host(unittest.TestCase):
    def test_other_platforms_say_unsupported(self):
        with mock.patch.object(kastr_micmute, "WINDOWS", False):
            self.assertEqual(kastr_micmute.snapshot()["supported"], False)

    def test_only_reads_never_sets(self):
        src = _read("kastr_micmute.py")
        self.assertIn("_call(vol, 15,", src)          # GetMute
        self.assertNotIn("_call(vol, 14,", src)       # SetMute is never called

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_reads_this_machine(self):
        import ctypes
        kastr_micmute._ole32.CoInitializeEx(None, 0)
        eps = kastr_micmute.read_endpoints()
        for e in eps:
            self.assertIsInstance(e["muted"], bool)
            self.assertIsInstance(e["name"], str)

    def test_local_only_route(self):
        src = _read("kastr_serve.py")
        i = src.index('if path == "/api/mic/hwmute":')
        self.assertIn('return self._deny("microphone state")', src[i:i + 300])
        self.assertIn('"--hidden-import", "kastr_micmute"', _read("build.py"))


class Page(unittest.TestCase):
    def test_follows_edges_and_never_unmutes_on_first_look(self):
        p = _read("moq-watch-lite.html")
        body = p[p.index("  async function hwMuteTick() {"):p.index("  setInterval(hwMuteTick, 1000);")]
        self.assertIn("if (ep.muted) setMicFromDevice(true, ep.name + \" is muted\");", body)
        self.assertIn("if (was !== key) setMicFromDevice(ep.muted, ep.name);", body)
        self.assertIn('id="hwFollowToggle"', p)

    def test_headset_button_toggles_and_lights_follow(self):
        p = _read("moq-watch-lite.html")
        self.assertIn("const HID_TEL = 0x0B, HID_LED = 0x08, U_MUTE = 0x2F, U_HOOK = 0x20, L_MUTE = 0x09, L_OFFHOOK = 0x17;", p)
        self.assertIn("if (b && !hid.lastBit) {", p)
        self.assertIn("try { hidSync(); } catch {}   // 0.21.41: the headset's mute light", p)
        self.assertIn('navigator.hid.requestDevice({ filters: [{ usagePage: HID_TEL }] })', p)

    def test_mic_menu_switches_lead(self):
        p = _read("moq-watch-lite.html")
        self.assertIn('<div class="sw"><label class="switch"><input type="checkbox" id="nsToggle"><i></i></label>', p)


if __name__ == "__main__":
    unittest.main()
