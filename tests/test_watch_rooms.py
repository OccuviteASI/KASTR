"""0.21.44: watch extra rooms -- stay in one room, watch others in the same window (muted, labelled, after mine).

Run: python -m unittest discover -s tests
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _page():
    with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


def _js_fn(p, head):
    i = p.index(head)
    return p[i:p.index("\n  }", i) + 4]


class OwnConnection(unittest.TestCase):
    def test_side_token_never_replaces_mine(self):
        p = _page()
        body = _js_fn(p, "  async function wrStart(w, redial) {")
        self.assertIn("wrSetToken(w, await xsTokenFor(w.slug, w.code || \"\"))", body)
        self.assertNotIn("authMint(", body)
        self.assertIn("new Net.Connection({ url: new Signals.Signal(url), enabled: true })", body)
        self.assertIn("announcedUnder(conn, w.slug)", body)

    def test_tiles_ride_the_watched_rooms_token(self):
        p = _page()
        body = _js_fn(p, "  function tileUrl(name) {")
        self.assertIn("if (wr) return wrUrl(watchRooms.get(wr));", body)

    def test_member_state_is_grids_only(self):
        p = _page()
        body = _js_fn(p, "  function wrMemberApply(path, v, h) {")
        self.assertIn("gridApply(", body)
        for other in ("spotVotes", "recApply", "filesApply", "mediaApply", "nudge"):
            self.assertNotIn(other, body)

    def test_entries_skip_room_internals_and_low_copies(self):
        p = _page()
        body = _js_fn(p, "  function wrEntry(w, path, active, me) {")
        self.assertIn('if (kind === "~grid") { gridAccept(path, active); wrSync(w); return; }', body)
        self.assertIn('if (kind.startsWith("~") || !path.endsWith(".hang") || LOW_RE.test(path)) return;', body)


class StaysOutOfMyRoom(unittest.TestCase):
    def test_label_person_key_and_order(self):
        p = _page()
        self.assertIn('return parts[2].toLowerCase() + (wr ? "@" + wr : "");', p)
        self.assertIn('const wrTag = (path) => { const r = wrRoomOf(path); return r ? " (" + r + ")" : ""; };', p)
        self.assertIn("const all = orderedNames0();", p)
        self.assertIn("railOrder(list.filter((n) => !wrRoomOf(n)), true)", p)

    def test_never_steals_the_stage_or_chimes(self):
        p = _page()
        self.assertIn("!isGridChild(n) && !wrRoomOf(n));   // 0.8.12", p)
        self.assertIn("&& !isGridChild(name) && !wrRoomOf(name)) selectedName = name;", p)
        self.assertIn("if (wrRoomOf(path)) return;                      // 0.21.44", p)

    def test_no_room_wide_actions_into_my_room(self):
        p = _page()
        self.assertIn('if ((!wrSrc || wrBring) && !viewLockedForMe()) items.push({ value: lit ? "unspot" : (wrSrc ? "wrall" : "all")', p)   # 0.21.49: a watched source is brought in first
        self.assertIn('if (authRole === "admin" && !mineNames.has(name) && !wrRoomOf(name)) {', p)
        self.assertIn("if (!wrRoomOf(name)) { try { window.__stallAnnounce?.set?.(name); } catch {} }", p)
        self.assertIn("if (isGridChild(n) || wrRoomOf(n)) continue;", p)


class Sound(unittest.TestCase):
    def test_muted_on_first_sight(self):
        p = _page()
        body = _js_fn(p, "  function wrFirstSight(slug, name) {")
        self.assertIn("if (w.sound) mutedStreams.delete(name); else mutedStreams.add(name);", body)
        self.assertIn("{ const wr = wrRoomOf(name); if (wr) wrFirstSight(wr, name); }", p)


class Lifecycle(unittest.TestCase):
    def test_join_switch_and_leave(self):
        p = _page()
        self.assertIn("    wrRestartAll();              // 0.21.44", p)
        self.assertIn("    wrStopAll();   // 0.21.44", p)
        body = _js_fn(p, "  function wrRestartAll() {")
        self.assertIn("if (w.slug === CHANNEL) { wrStop(w); watchRooms.delete(w.slug); wrSave(); continue; }", body)

    def test_codes_stay_in_the_session(self):
        p = _page()
        body = _js_fn(p, "  function wrSave() {")
        self.assertIn("sessionStorage.setItem(\"kastr.watchcodes\"", body)
        self.assertNotRegex(body, r"localStorage\.setItem\([^)]*code")


class RailUi(unittest.TestCase):
    def test_eye_and_right_click(self):
        p = _page()
        self.assertIn('sbw.className = "sbw"; sbw.innerHTML = icon("eye");', p)
        self.assertIn("row.append(rb, head, sbw, spk, sbx);", p)
        self.assertIn("openMineMenu(pointAnchor(e.clientX, e.clientY), items, \"\", (v) => wrCardPick(card, r, v));", p)
        self.assertIn("wrPaintCard(card, rec);   // 0.21.44", p)
        self.assertIn(".sbcard .sbw[hidden] { display:none; }", p)

    def test_box_modes_never_watch(self):
        p = _page()
        self.assertIn("const wrCan = (rec) => !!rec && joinState === \"joined\" && rec.slug !== CHANNEL && !isPublisherMode() && !publishOnly", p)
        self.assertIn("&& CHANNEL !== LOBBY && rec.slug !== LOBBY;", p)   # 0.21.60: never from or of the Lobby


class PickPerSource(unittest.TestCase):
    """0.21.47 (Kenton): only the ticked sources show; new ones are counted; the list belongs to the room I am in."""

    def test_only_ticked_sources_become_tiles(self):
        p = _page()
        body = _js_fn(p, "  function wrEntry(w, path, active, me) {")
        self.assertIn("if (wrWanted(w, path)) { cancelPendingRemoval(path);", body)
        wanted = _js_fn(p, "  function wrWanted(w, p) {")
        self.assertIn("return !!gp && w.pick.has(gp);", wanted)   # a ticked grid brings its cameras (a cell opens full quality)

    def test_new_sources_are_counted_not_shown(self):
        p = _page()
        self.assertIn("const wrNewCount = (w) => wrListable(w).filter((p) => !w.pick.has(p) && !w.known.has(p)).length;", p)
        self.assertIn('c.className = "wcnt";', p)
        self.assertIn('nw.className = "wrnew"; nw.textContent = "new";', p)

    def test_the_list_belongs_to_my_room(self):
        p = _page()
        load = _js_fn(p, "  function wrLoad() {")
        self.assertIn('const k = wrKey() + "|" + CHANNEL;', load)
        self.assertIn("const list = Array.isArray(o[CHANNEL]) ? o[CHANNEL] : [];", load)
        save = _js_fn(p, "  function wrSave() {")
        self.assertIn("o[wrLoadedRoom] = list", save)

    def test_nothing_ticked_means_not_watching(self):
        body = _js_fn(_page(), "  function wrPickerClose() {")
        self.assertIn("if (w && !w.pick.size) wrRemove(w.slug);", body)


class RoomScoped(unittest.TestCase):
    def test_a_listed_share_is_my_rooms_tile(self):
        body = _js_fn(_page(), "  function wrRoomOf(path) {")
        self.assertIn('if (xsTiles.has(String(path))) return "";', body)

    def test_a_spotlight_stays_in_its_room(self):
        p = _page()
        self.assertIn('if (String(v.target).split("/", 1)[0] !== CHANNEL && !xsTiles.has(String(v.target))) return;   // 0.21.47', p)


class ShareRoomsPerShare(unittest.TestCase):
    """0.21.62 (Kenton): no pill row of rooms for every share -- each share (camera included) picks its own rooms."""
    def test_no_pill_row_and_new_shares_ask(self):
        p = _page()
        self.assertNotIn('id="xsRoomsRow"', p)
        body = p[p.index("  async function xsTick() {"):p.index("  // members' side: what is listed into my room")]
        self.assertIn("const r = await xsSetRooms(p, keep, { remember: false });", body)   # remembered rooms come back
        self.assertIn(r"/\/camera(-\d+)?\.hang$/.test(p) || isPublisherMode()", body)   # the camera and a box never ask
        self.assertIn("openXsPicker(p, null, { prompt: true });", body)


if __name__ == "__main__":
    unittest.main()
