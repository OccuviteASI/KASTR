"""0.21.22: relay discovery on the LAN (kastr_mdns), the probe, failover rules, and the page bits that ride along.

Run: python -m unittest tests.test_lan_discovery
"""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import kastr_mdns   # noqa: E402


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class Wire(unittest.TestCase):
    def test_answer_round_trip(self):
        a = kastr_mdns.Advertiser(lambda: None)
        inf = {"name": "Hub (KASTR)", "host": "hub", "port": 8000, "ips": ["10.0.0.5"],
               "txt": {"v": "0.21.22", "rp": "4443", "sec": "1", "fp": "ab" * 32}}
        mid, flags, qs, rrs = kastr_mdns.parse(a._answer(inf))
        self.assertTrue(flags & 0x8000)
        kinds = {rt for _, rt, _, _, _ in rrs}
        self.assertEqual(kinds, {kastr_mdns.T_PTR, kastr_mdns.T_SRV, kastr_mdns.T_TXT, kastr_mdns.T_A})
        txt = [d for n, rt, d, _, _ in rrs if rt == kastr_mdns.T_TXT][0]
        self.assertIn(b"rp=4443", txt)

    def test_never_advertises_a_secret(self):
        src = _read("kastr_serve.py")
        i = src.index("def _mdns_info(relay_srv, web_port):")
        body = src[i:i + 1400]
        for bad in ("code", "token", "secret", "jwt", "access"):
            self.assertNotIn('"%s"' % bad, body)

    def test_compressed_names_decode(self):
        name = kastr_mdns._enc_name("_kastr._tcp.local")
        buf = b"\x00" * 12 + name + b"\xc0\x0c"   # a pointer back to offset 12
        self.assertEqual(kastr_mdns._dec_name(buf, 12 + len(name))[0], "_kastr._tcp.local")


class Host(unittest.TestCase):
    def test_probe_offline_and_bad(self):
        import kastr_serve
        self.assertFalse(kastr_serve.probe_relay("http://127.0.0.1:9", timeout=0.5)["online"])
        self.assertFalse(kastr_serve.probe_relay("file:///etc/passwd")["online"])

    def test_routes_are_local_only(self):
        src = _read("kastr_serve.py")
        i = src.index("def _lan_api(self, path, method):")
        self.assertIn("if not self._local():", src[i:i + 900])


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html")

    def test_switches_only_to_known_relays_with_the_same_certificate(self):
        p = self.p
        self.assertIn("if (r.online && (!fps[u] || !r.fp || fps[u] === r.fp)) { pick = ", p)
        self.assertIn("if (!f.fp || !knownFps.has(f.fp)) continue;", p)   # a LAN find counts only with a remembered certificate
        self.assertIn('if (trigger === "launch") {', p)
        self.assertIn('action: { label: "Switch to " + pick.name', p)          # mid-session = an offer

    def test_failover_is_desktop_only(self):
        self.assertIn('if (failoverBusy || IS_WEB || !gateIsLoopback() || PAGE_MODE === "relay") return null;', self.p)

    def test_own_preview_pinned_to_the_bottom(self):
        self.assertIn("el.style.gridRow = String(railRows - ownRows + 1 + i);", self.p)

    def test_window_list_collapsed_until_clicked(self):
        p = self.p
        self.assertIn("let shWinOpen = false;", p)
        self.assertIn("if (shWinOpen) shPaintList($(\"shWindows\"), d.windows || []);", p)

    def test_no_muted_badge_on_rtsp(self):
        p = self.p
        self.assertIn("#stage .pane.rtsptile .mchip { display:none !important; }", p)
        self.assertIn('case "rtspPaths":', p)

    def test_catalog_watchdog(self):
        # 0.21.22: a tile whose catalog never came shows the face (not black) and re-subscribes at 12 / 30 / 90 s;
        # "watching" must not read `visible` -- the face view parks the video and would clear the flag again
        p = self.p
        self.assertIn("const audioOnly = t.hasVideo === false || !!t.noDecode || !!t.noCatalog", p)   # 0.21.23 adds || t.shed
        self.assertIn("const due = [12000, 30000, 90000][t.catResubs || 0];", p)
        self.assertIn('const watching = isWatched(name) && !t.fb && t.pane.classList.contains("shown") && t.pane.style.display !== "none";', p)

    def test_relay_page_advertise_switch(self):
        r = _read("relay.html")
        self.assertIn('id="mdnsAdv"', r)
        self.assertIn('fetch("/api/lan/advertise"', r)


if __name__ == "__main__":
    unittest.main()
