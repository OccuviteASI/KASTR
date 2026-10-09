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

    def test_box_camera_only_when_shared(self):
        # 0.21.31 (Kenton: Southridge "showing up as a person due to it having OBS saying that it has a camera")
        p = self.page
        self.assertIn("const boxQuiet = isPublisherMode() && !joinVidOn && !joinMicOn;", p)
        self.assertIn("if (!isViewerMode() && !boxQuiet && d.permission && d.cameras.length", p)
        self.assertIn("if (isPublisherMode() && !src.videoPaused && src.micMuted && window.__publisher?.removeSource)", p)

    def test_latency_label_clears_the_name(self):
        # 0.21.31 (Kenton: "the latency when shown is covering the muted icon and the window name")
        self.assertIn("#stage .pane .latb { position:absolute; left:6px; top:6px;", self.page)

    def test_dark_camera_stays_out_of_the_grid(self):
        # 0.21.31 (Kenton: offline cameras "pop back up in the grid showing that it is on attempt 200 or 300")
        p = self.page
        self.assertIn("const flowing = !!(pi?.flowingAt && pi.since && pi.flowingAt >= pi.since && nowS - pi.flowingAt < 8);", p)
        self.assertIn("nowS - pi.since >= GRID_READMIT_LIVED_S && flowing)", p)
        r = _read("kastr_rtsp.py")
        self.assertIn('"-progress", "pipe:2", "-stats_period", "2"', r)
        self.assertIn('"flowingAt": self.flowingAt,', r)

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
        self.assertNotIn('<footer class="asi-footer">', _read("moq-watch-lite.html"))   # 0.21.24 hid it; 0.21.40 removed it


class RoomsOnTheHub(unittest.TestCase):
    """0.21.27 (Kenton): no Rooms column in the spokes table; the Rooms panel only where rooms live (hub / standalone)."""

    def test_relay_page(self):
        r = _read("relay.html")
        self.assertNotIn("<th>Rooms</th>", r)
        # 0.21.40: the dropped column's renderer, its chat/close buttons and the close-room call are gone too
        for gone in ("roomsCell", ".sprp", ".sprx", ".sproom", "/api/relay/spokes/close-room"):
            self.assertNotIn(gone, r)
        self.assertIn("const isSpoke = !!(lastStatus && lastStatus.cluster && lastStatus.cluster.connect && lastStatus.cluster.hub !== true);", r)
        self.assertIn('if (s.cluster && s.cluster.connect && s.cluster.hub !== true) $("roomsPanel").hidden = true;', r)


class JoinGate(unittest.TestCase):
    def test_scrim_covers_the_whole_page(self):
        # 0.21.28 (Kenton: "the shadow in the back doesn't cover the whole screen")
        p = _read("moq-watch-lite.html")
        self.assertNotIn("#joinGate { left:calc(var(--sbw) + 26px); }", p)
        self.assertIn("#joinGate { position:fixed; inset:0; z-index:67;", p)

    def test_rooms_in_the_card_not_behind_it(self):
        # 0.21.30 (Kenton: "show the rooms in the launch window, but don't show them in the backdrop on the side")
        p = _read("moq-watch-lite.html")
        self.assertIn("body:has(#joinGate:not([hidden])) #sidebar { visibility:hidden; }", p)
        # 0.21.31 (Kenton: "I still only want 1 showing except when I click the drop-down button"): the dropdown again
        self.assertIn('<select id="joinChanSel" style="flex:1"></select>', p)
        self.assertNotIn("joinRoomList", p)

    def test_relay_picker_says_online_or_offline(self):
        # 0.21.30 (Kenton: "the launch page is no longer showing which relays are online or not")
        p = _read("moq-watch-lite.html")
        self.assertIn("gateRelayProbeAll([...opts, ...lan.map((f) => f.urls[0])]);", p)
        self.assertIn('o.title = u + (st == null ? "" : st.online ? " (online)" : " (offline)");', p)   # 0.21.33: the dot says it; words on hover

    def test_rail_marks_a_kept_room_with_a_symbol(self):
        # 0.21.31 (Kenton: "don't put the always open in the rooms, just put a symbol ... similar to the lock symbol")
        p = _read("moq-watch-lite.html")
        self.assertNotIn('(rec.persistent ? "always open" : "")', p)
        self.assertIn('kp.className = "kp"; kp.innerHTML = icon("keep")', p)
        # 0.21.35 (Kenton: "remove the symbol after the time ... The symbol on the circle should be indicator enough")
        self.assertIn('card.querySelector(".sbflags").innerHTML = "";', p)
        self.assertNotIn('<span title="Stays open when everyone leaves">\' + icon("keep")', p)

    def test_room_timers_without_seconds(self):
        # 0.21.35 (Kenton: "remove the seconds on the room timers")
        p = _read("moq-watch-lite.html")
        self.assertIn('return Math.floor(t / 60) + ":" + String(t % 60).padStart(2, "0");', p)
        self.assertIn('"\\u23F1 " + fmtHm(now - card.__since)', p)
        self.assertIn('(roomSince ? fmtHm(now - roomSince) : "0:00")', p)

    def test_chat_new_only_recent_and_unseen(self):
        # 0.21.35 (Kenton: "Chats should show new chat until seen or for a certain amount of time, not for everyone new to the room")
        p = _read("moq-watch-lite.html")
        self.assertIn("const CHAT_NEW_MS = 15 * 60 * 1000;", p)
        self.assertIn("(m.local ? !m.seenLocal : m.id > chatSeenId) && chatRecent(m) &&", p)
        self.assertIn("m.id > chatSeenAtOpen && chatRecent(m) &&", p)

    def test_profile_card_never_scrolls_sideways(self):
        self.assertIn("#profilePop .prow input { width:100%; min-width:0; box-sizing:border-box; }", _read("moq-watch-lite.html"))


if __name__ == "__main__":
    unittest.main()
