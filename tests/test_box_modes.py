import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class BoxModes(unittest.TestCase):
    """0.21.24 (Kenton): field fixes for publisher boxes, the federation field and the iPhone camera."""

    def setUp(self):
        self.page = _read("moq-watch-lite.html")
        self.relay = _read("relay.html")

    def test_mode_switch_reachable_in_every_mode(self):
        p = self.page
        self.assertIn('id="optMode"', p)
        self.assertIn('if (app?.show && PAGE_MODE !== "viewer" && PAGE_MODE !== "publisher") { try { app.show("relay"); return; } catch {} }', p)
        self.assertIn('window.top.location.href = "/relay.html#modeSel"', p)
        self.assertIn('"joinRelayRow", "optMode"]', p)   # never on a web client (the mode is the host's business)
        self.assertIn('if (location.hash === "#modeSel")', self.relay)

    def test_publisher_box_shows_detected_devices(self):
        p = self.page
        self.assertIn("if (isPublisherMode() && CLIENT.secure && CLIENT.media) boxDevicesShow();", p)
        self.assertIn('has = { cam: devs.some((d) => d.kind === "videoinput"), mic: devs.some((d) => d.kind === "audioinput") }', p)
        self.assertIn('navigator.mediaDevices.addEventListener("devicechange", () => boxDevicesShow())', p)

    def test_unsaved_hub_url_survives_refresh(self):
        r = self.relay
        self.assertIn('document.activeElement !== $("fedUrl") && !$("fedUrl").dataset.dirty) $("fedUrl").value', r)
        self.assertIn('if (!$("fedUrl").dataset.dirty) $("fedUrl").value = c.connect', r)
        self.assertIn("Not saved yet", r)
        self.assertIn('delete $("fedUrl").dataset.dirty;   // 0.21.24', r)

    def test_webkit_always_draws_upright(self):
        p = self.page
        self.assertIn('settle(true, "webkit");', p)
        self.assertNotIn('settle(!fl.worker, "worker")', p)   # newer iOS has the processor in workers: never "not needed" on WebKit


class NotTheHub(unittest.TestCase):
    """0.21.24 (Kenton: the old hub listed every spoke 'as if still connected', hub switch off)."""

    def _auth(self, hub_flag):
        import tempfile, threading, time
        import kastr_relay
        a = kastr_relay.AuthService.__new__(kastr_relay.AuthService)
        a.lock = threading.Lock()
        a.log = lambda *x: None
        a._spokes_path = os.path.join(tempfile.mkdtemp(), "relay-spokes.json")
        a.cmd = {"seq": 0}
        now = int(time.time())
        a.spokes = {"spoke:fresh": {"at": now - 60, "name": "fresh"}, "spoke:old": {"at": now - 7200, "name": "old"}}
        a.is_hub = lambda: hub_flag
        a._bearer_relay = lambda bearer: True
        return a

    def test_stale_spokes_hidden_and_counted(self):
        a = self._auth(None)
        self.assertEqual([r["name"] for r in a.spokes_public()], ["fresh"])
        self.assertEqual(a.spokes_stale(), 1)
        self.assertEqual(len(a.spokes_public(stale=True)), 2)

    def test_switched_off_refuses_hub_duties(self):
        a = self._auth(False)
        self.assertTrue(a.not_hub())
        out, code = a.register_spoke({"name": "logan"}, peer="10.0.0.9", bearer="Bearer x")
        self.assertEqual(code, 403)
        self.assertIn("not a hub", out["error"])
        out, code = a.bans_for_spoke("Bearer x")
        self.assertEqual(code, 403)
        a.forget_spokes()
        self.assertEqual(a.spokes_public(stale=True), [])

    def test_never_said_keeps_working(self):
        self.assertFalse(self._auth(None).not_hub())
        self.assertFalse(self._auth(True).not_hub())

    def test_go_live_has_no_footer(self):
        self.assertIn("  footer.asi-footer { display:none !important; }   /* 0.21.24", _read("moq-watch-lite.html"))


class RoomsOnTheHub(unittest.TestCase):
    """0.21.27 (Kenton): no Rooms column in the spokes table; the Rooms panel only where rooms live (hub / standalone)."""

    def test_relay_page(self):
        r = _read("relay.html")
        self.assertNotIn("<th>Rooms</th>", r)
        self.assertNotIn('"</td><td>" + roomsCell(r) + "</td>', r)
        self.assertIn("const isSpoke = !!(lastStatus && lastStatus.cluster && lastStatus.cluster.connect && lastStatus.cluster.hub !== true);", r)
        self.assertIn('if (s.cluster && s.cluster.connect && s.cluster.hub !== true) $("roomsPanel").hidden = true;', r)


class JoinGate(unittest.TestCase):
    def test_scrim_covers_the_whole_page(self):
        # 0.21.28 (Kenton: "the shadow in the back doesn't cover the whole screen")
        p = _read("moq-watch-lite.html")
        self.assertNotIn("#joinGate { left:calc(var(--sbw) + 26px); }", p)
        self.assertIn("#joinGate { z-index:67; }", p)

    def test_profile_card_never_scrolls_sideways(self):
        self.assertIn("#profilePop .prow input { width:100%; min-width:0; box-sizing:border-box; }", _read("moq-watch-lite.html"))


if __name__ == "__main__":
    unittest.main()
