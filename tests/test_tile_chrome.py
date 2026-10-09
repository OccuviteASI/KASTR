# -*- coding: utf-8 -*-
"""v0.21.37 (Kenton, field round): tile buttons that never overlap and always carry their icons, mute / camera-off marks
that fade with the rest of the chrome, a stuck tile that names its relay as a relay, a latency that is never shown below
zero (one fleet clock: the hub's), relay boxes that start with web clients off, and a grid's Audio / Pass through on the
grid's header in the Share menu."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_serve  # noqa: E402


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class TileChrome(unittest.TestCase):
    def setUp(self):
        self.p = _read("moq-watch-lite.html")

    def test_buttons(self):
        self.assertIn(".pchev.pfs { right:calc(10px + var(--pw)); }", self.p)
        self.assertIn(".pchev.pfill { right:calc(14px + 2 * var(--pw)); }", self.p)
        self.assertIn('b.innerHTML = icon(cls === "pfs" ? "fullscreen" : "fillwin");', self.p)

    def test_marks_fade(self):
        self.assertIn("#stagewrap.idle #stage .mchip, #stagewrap.idle #stage .vchip {", self.p)
        self.assertIn('if (e.pointerType === "mouse" && !idleBusy()) { clearTimeout(idleT); stageWrap.classList.add("idle"); }', self.p)

    def test_stuck_caption(self):
        self.assertIn('"waiting on relay " + (memberVia(personKeyOf(name)) || "?")', self.p)
        self.assertNotIn('"no stream from " + (memberVia', self.p)

    def test_latency_never_negative(self):
        self.assertIn('(lat < 0 ? "latency: clocks out of step" : "latency " + lat + " ms")', self.p)
        self.assertIn('+ (Number(d.hubOff) || 0);', self.p)
        self.assertIn('"hubOff": HUB_CLOCK.get("off") or 0,', _read("kastr_serve.py"))

    def test_grid_header_switches(self):
        self.assertIn(".gridgroup .camrow .aud, .gridgroup .camrow .pt { display:none !important; }", self.p)
        self.assertIn('const audSw = ggSwitch("Audio",', self.p)
        self.assertIn('const ptSw = ptMembers.length ? ggSwitch("Pass through",', self.p)


class RelayWebDefault(unittest.TestCase):
    def test_becoming_a_relay_turns_web_clients_off(self):
        ini = {}
        with mock.patch.object(kastr_serve, "ini_get", side_effect=lambda k: ini.get(k)), \
                mock.patch.object(kastr_serve, "ini_set", side_effect=lambda k, v: ini.__setitem__(k, v) if v is not None else ini.pop(k, None)), \
                mock.patch.object(kastr_serve, "_WEB_PAGE_OFF", [None]), \
                mock.patch.object(kastr_serve, "mode_state", return_value={}):
            kastr_serve.mode_set("relay")
            self.assertEqual(ini.get("web_page"), "off")
            ini.pop("web_page")
            kastr_serve.mode_set("publisher-relay")   # relay -> relay: the operator's choice stands
            self.assertNotIn("web_page", ini)


if __name__ == "__main__":
    unittest.main()
