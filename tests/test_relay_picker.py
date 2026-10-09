# -*- coding: utf-8 -*-
"""v0.21.33 (Kenton): relay names in the pickers (address on hover, the dot says online/offline), a relay address typed
loosely gets http:// and :4443 (a typed port or a full URL is kept), no list of code kinds on the join card, and a grid
preview whose picture stopped while data kept arriving restarts."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay  # noqa: E402


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class RelayAddress(unittest.TestCase):
    def test_server_rule(self):
        n = kastr_relay.normalize_relay_url
        self.assertEqual(n("10.0.2.14"), "http://10.0.2.14:4443")
        self.assertEqual(n("10.0.2.14:4444"), "http://10.0.2.14:4444")          # never :4443 added to a typed port
        self.assertEqual(n("http://10.0.2.14"), "http://10.0.2.14:4443")
        self.assertEqual(n("http://10.0.2.14:4443"), "http://10.0.2.14:4443")   # the full URL as typed
        self.assertEqual(n("https://kastr.madlabs.app/relay"), "https://kastr.madlabs.app/relay")
        self.assertEqual(n("kastr.madlabs.app/relay"), "https://kastr.madlabs.app/relay")
        self.assertEqual(n("[::1]:5000"), "http://[::1]:5000")
        self.assertEqual(n(""), "")

    def test_every_entry_uses_it(self):
        p, b = _read("moq-watch-lite.html"), _read("assets/asi-brand.js")
        self.assertIn("u = relayAddr(u);   // 0.21.33", p)
        self.assertIn("u = relayAddr(u);   // 0.21.33", b)
        self.assertIn("url = normalize_relay_url(payload.get(\"url\") or \"\")", _read("kastr_relay.py"))


class RelayNames(unittest.TestCase):
    def test_auth_beacon_names_the_relay(self):
        a = kastr_relay.AuthService.__new__(kastr_relay.AuthService)
        d = tempfile.mkdtemp()
        a.store = type("S", (), {"state_dir": d})()
        self.assertEqual(a.relay_name(), "")
        with open(os.path.join(d, "relay-name.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "mendon-rtsp"}, f)
        self.assertEqual(a.relay_name(), "mendon-rtsp")
        self.assertIn('"name": svc.relay_name() or None})', _read("kastr_relay.py"))

    def test_pickers_show_names_and_dots(self):
        p, b = _read("moq-watch-lite.html"), _read("assets/asi-brand.js")
        self.assertIn("opt(mark(u) + (relayNameOf(u) || relayLabel(u)) + word(u), u)", p)
        self.assertIn('const word = () => "";', p)                         # no "online"/"offline" words
        self.assertIn("txt.textContent = (relayNameOf(u) || u.replace(", b)
        self.assertIn('if (r?.name) relayNameSet(url, r.name);', p)
        self.assertIn('out["name"] = nm.strip()[:32]', _read("kastr_serve.py"))

    def test_no_code_kinds_on_the_join_card(self):
        self.assertNotIn("viewer, publisher or admin code", _read("moq-watch-lite.html"))


class FrozenPreview(unittest.TestCase):
    def test_decoded_frames_decide(self):
        p = _read("moq-watch-lite.html")
        self.assertIn("const MONITOR_NOFRAME_MS = 12000;", p)
        self.assertIn("try { tf = v.getVideoPlaybackQuality?.().totalVideoFrames; } catch {}", p)
        self.assertIn('if (recent.length >= 2 && !slot.monitorTranscode) { monitorBroken(slot, "the picture froze again while data kept arriving"); return info; }', p)
        self.assertIn('(document.visibilityState === "visible" || now - monAnyFrameAt < 5000)', p)   # a hidden page is not one frozen camera


if __name__ == "__main__":
    unittest.main()
