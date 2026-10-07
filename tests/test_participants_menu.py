import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class TileMenu(unittest.TestCase):
    """0.21.23 (Kenton, Teams screenshot): Mute participant / Pin for me / Spotlight for everyone with glyphs, no
    'Fit to frame', and the same menu on a right-click."""

    def setUp(self):
        self.page = _read("moq-watch-lite.html")

    def test_teams_names_and_glyphs(self):
        p = self.page
        self.assertIn('{ value: "mute", icon: muted ? "mic" : "micOff",', p)
        self.assertIn('content ? "share" : "participant"', p)
        self.assertIn('icon: "pin", label: pinned ? "Unpin" : "Pin for me"', p)
        self.assertIn('icon: "spotlight", label: lit ? "Stop spotlighting" : "Spotlight for everyone"', p)
        self.assertNotIn("Fit to frame", p)
        self.assertNotIn('label: "Spotlight for me"', p)
        for g in ("    pin: '", "    spotlight: '", "    search: '"):
            self.assertIn(g, p)

    def test_menu_draws_icons(self):
        p = self.page
        self.assertIn('const withIcons = items.some((it) => it.icon);', p)
        self.assertIn('if (it.icon) ic.innerHTML = icon(it.icon);', p)

    def test_right_click_opens_the_same_menu(self):
        p = self.page
        self.assertIn('pane.addEventListener("contextmenu", (e) => {   // 0.21.23 (Kenton): right-click on a user window', p)
        self.assertIn("openTileMenu(pointAnchor(e.clientX, e.clientY));", p)
        self.assertIn('pchev.addEventListener("click", (e) => { e.stopPropagation(); openTileMenu(pchev); });', p)


class Participants(unittest.TestCase):
    def setUp(self):
        self.page = _read("moq-watch-lite.html")

    def test_panel_shape(self):
        p = self.page
        for needle in ('<span>Participants</span>', 'id="pplSearch"', 'id="pplInvite"', 'id="pplMuteAll"',
                       '<span>In this room (<span id="pplCount">0</span>)</span>', 'id="pplRows"', '<summary>Streams and volume</summary>'):
            self.assertIn(needle, p)

    def test_mute_all_is_admin_only(self):
        self.assertIn('ppl.mute.hidden = authRole !== "admin"', self.page)
        self.assertIn('window.__adminSend?.({ op: "mute", target: n });', self.page)

    def test_search_filters_names(self):
        self.assertIn("const shown = q ? list.filter((p) => p.name.toLowerCase().includes(q)) : list;", self.page)

    def test_invite_link_opens_the_room(self):
        p = self.page
        self.assertIn('"/moq-watch-lite.html?room=" + encodeURIComponent(CHANNEL)', p)
        self.assertIn('new URLSearchParams(location.search).get("room")', p)
        self.assertIn("they still need the access code", p)

    def test_row_menu_reuses_the_tile_menu(self):
        self.assertIn("pane.__openMenu = openTileMenu;", self.page)
        self.assertIn("if (pane?.__openMenu) { pane.__openMenu(anchor); return true; }", self.page)

    def test_repainted_when_open(self):
        self.assertIn("try { paintParticipants(); } catch {}   // 0.21.23", self.page)
        self.assertIn('() => paintParticipants(true));   // 0.21.23', self.page)


class RelayPage(unittest.TestCase):
    def setUp(self):
        self.page = _read("relay.html")

    def test_same_site_section_removed(self):
        for gone in ('id="lanOn"', "Join same-site relays automatically", "paintLan", 'id="lanSecret"'):
            self.assertNotIn(gone, self.page)
        self.assertIn('id="mdnsAdv"', self.page)   # the discovery switch stays

    def test_hub_toggle_hides_spoke_fields(self):
        p = self.page
        self.assertIn('id="fedHub"', p)
        i, j = p.index('<div id="fedSpoke">'), p.index('id="fedClear"')
        for f in ('id="fedUrl"', 'id="fedCode"', 'id="fedMaster"'):
            k = p.index(f)
            self.assertTrue(i < k < j, f)
        self.assertIn('$("fedSpoke").hidden = on;', p)


class HubFlag(unittest.TestCase):
    def setUp(self):
        import kastr_relay
        self.kr = kastr_relay
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _relay(self):
        r = self.kr.Relay.__new__(self.kr.Relay)
        r.state_dir = self.dir
        r.log = lambda *a: None
        r._restart = mock.Mock(return_value=True)
        return r

    def test_hub_flag_round_trip_without_restart(self):
        r = self._relay()
        self.assertIsNone(r.cluster_config()["hub"])
        out = r.set_cluster({"hub": True})
        self.assertTrue(out["hub"])
        self.assertFalse(out["restarted"])
        r._restart.assert_not_called()
        self.assertTrue(r.cluster_config()["hub"])
        with open(os.path.join(self.dir, "relay-cluster.json"), encoding="utf-8") as f:
            self.assertTrue(json.load(f)["hub"])

    def test_becoming_the_hub_leaves_the_old_hub(self):
        r = self._relay()
        r.set_cluster({"connect": "https://10.0.0.5:4443", "code": "x"})
        r._restart.reset_mock()
        out = r.set_cluster({"hub": True})
        self.assertEqual(out["connect"], "")
        self.assertTrue(out["restarted"])   # the relay stops dialling the old hub
        self.assertTrue(r._cluster_raw()["code"])   # the code is kept


class ListenerLadder(unittest.TestCase):
    """0.21.23 (Kenton: audio drops out on slow internet): video off the stage pauses before any audio suffers."""

    def setUp(self):
        self.page = _read("moq-watch-lite.html")

    def test_trouble_counts_only_after_the_delay_widened(self):
        p = self.page
        self.assertIn('if (why === "late" && !(window.__audioDelay?.extra > 0)) return;', p)
        self.assertIn('try { congestTrouble("late"); } catch {}', p)
        self.assertIn('if (k === "audio") try { congestTrouble("skip"); } catch {}', p)

    def test_the_stage_and_audio_are_never_shed(self):
        p = self.page
        self.assertIn("if (!lvl || onStage) return false;", p)
        self.assertIn('return lvl >= 2 || (tileClasses.get(name) ?? pathClass(name)) === "person";', p)
        self.assertIn("|| !!t.noCatalog || t.shed;", p)   # a shed tile = face + no video subscription; audio is volume-driven

    def test_steps_back_down_and_can_be_switched_off(self):
        p = self.page
        self.assertIn("if (!c.level || now - c.lastTroubleAt < 120000 || now - c.lastStepAt < 120000) return;", p)
        self.assertIn('id="congestToggle"', p)
        self.assertIn('localStorage.getItem("kastr.congest") === "off"', p)
        self.assertIn("congest: (() => {", p)   # /api/diag


class GridAndMore(unittest.TestCase):
    def setUp(self):
        self.page = _read("moq-watch-lite.html")

    def test_grid_cells_on_whole_pixels_with_a_border(self):
        p = self.page
        self.assertIn("const x = Math.round(r.x), y = Math.round(r.y), cw = Math.round(r.x + r.w) - x, ch = Math.round(r.y + r.h) - y;", p)
        self.assertIn('g.cx.strokeStyle = "#000"; g.cx.lineWidth = B; g.cx.strokeRect(x + B / 2, y + B / 2, cw - B, ch - B);', p)

    def test_more_menu(self):
        p = self.page
        for gone in ("optSettings", "optMobile", "mobilePop", "drawQr", 'id="optEnc"', 'id="optAud"', 'id="optVideo"', 'id="optAudio"', 'id="optChat"'):
            self.assertNotIn(gone, p)
        self.assertIn('id="optAbout"', p)
        self.assertIn('class="opt phoneonly" id="optFiles"', p)   # phones keep Files in More
        self.assertIn('getElementById("camMore")', p)   # video output still opens from the camera menu
        self.assertIn('getElementById("micMore")', p)   # audio output from the mic menu


if __name__ == "__main__":
    unittest.main()
