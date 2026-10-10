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
        self.assertIn('if (kind === "~grid") { gridAccept(path, active); return; }', body)
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
        self.assertIn('if (!wrRoomOf(name)) items.push({ value: lit ? "unspot" : "all"', p)
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
        self.assertIn("const wrCan = (rec) => !!rec && joinState === \"joined\" && rec.slug !== CHANNEL && !isPublisherMode() && !publishOnly;", p)


if __name__ == "__main__":
    unittest.main()
