"""0.21.84: the STREAM LIBRARY, the page side (moq-watch-lite.html + relay.html).

Kenton (2026-10-23): "a fleet-wide library of available streams -- every camera box ... can publish once to one shared library;
anyone in any room browses it and pulls streams in as tiles, spotlights or grids" (design + decisions: v02184 DESIGN.md; the
server's API.md is the contract for every endpoint named here).

Static checks of the wiring: the Streams panel (a 0.21.78 panel: registerPop, stays open, pins to the right column, a full-screen
sheet on a phone), the capability gate (/api/auth library: 1 = this relay AND its hub), the ONE library connection (tileUrl hands it
to lib/ paths only; its announce watch runs only while the panel is open), browsing never wakes a camera (a peek is for a LIVE row;
Preview sends one demand), the honest state cards, the permission greys, the builder's Library group, the alias rewrite of
device-local references, the box picker's library switch and the hub's Relay page card.

Run: python -m unittest discover -s tests
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def _raw(name):
    with open(os.path.join(ROOT, name), "rb") as f:
        return f.read()


def _fn(p, head):   # a function from its head line to the first closing brace at the same indent
    i = p.index(head)
    ind = head[:len(head) - len(head.lstrip())]
    return p[i:p.index("\n" + ind + "}", i) + len(ind) + 2]


_ESC = re.compile(chr(92) * 2 + "u([0-9a-fA-F]{4})")   # the page writes non-ASCII as escapes; these checks read the characters


def _dec(s):
    return _ESC.sub(lambda m: chr(int(m.group(1), 16)), s)


P_RAW = _read("moq-watch-lite.html")
P = _dec(P_RAW)
R = _dec(_read("relay.html"))
_I = P.index("  // ==== 0.21.84 (Kenton: \"a fleet-wide library of available streams")
LIB = P[_I:P.index("</script>", _I)]   # THE STREAM LIBRARY: the end of module 1


class LineEndings(unittest.TestCase):
    def test_both_pages_stay_crlf(self):
        for name in ("moq-watch-lite.html", "relay.html"):
            b = _raw(name)
            self.assertGreater(b.count(b"\r\n"), 1000, name)
            self.assertEqual(b.count(b"\n") - b.count(b"\r\n"), 0, name + " has a lone LF")


class Escapes(unittest.TestCase):
    def test_the_library_block_is_ascii(self):
        i = P_RAW.index("  // ==== 0.21.84 (Kenton:")
        block = P_RAW[i:P_RAW.index("</script>", i)]
        self.assertTrue(all(ord(ch) < 128 for ch in block))


class PanelWiring(unittest.TestCase):
    def test_toolbar_button_beside_chat(self):
        a = P.index('<button id="chatBtn"')
        b = P.index('<button id="libBtn"')
        self.assertLess(a, b)
        self.assertLess(b, P.index('<button id="optBtn"'))
        self.assertIn('id="libBtn" class="toggle tb" type="button"', P)
        self.assertIn('libBtn.innerHTML = tbHtml("library", "Streams");', LIB)
        self.assertIn("ICONS.library = ", LIB)

    def test_the_panel_is_a_0_21_78_panel(self):
        self.assertIn('<aside id="libPanel" class="popcard" hidden', P)
        self.assertIn('<div class="head"><span>Streams</span>', P)   # its head: the dock adds collapse + pin before the X
        self.assertIn("const libEntry = registerPop(libPanel, libBtn, () => libOpened());", LIB)
        self.assertIn('libEntry.close = () => { if (libPanel.classList.contains("docked")) return; orig(); libClosed(); };', LIB)   # a pinned Streams stays
        self.assertIn('DOCK_ORDER.splice(DOCK_ORDER.indexOf("share"), 0, "streams");', P)
        self.assertIn('streams: { pop: document.getElementById("libPanel"), btn: document.getElementById("libBtn"), name: "Streams"', P)
        # the splice runs before the saved pins are read (dockSt filters by DOCK_ORDER)
        self.assertLess(P.index('DOCK_ORDER.splice(DOCK_ORDER.indexOf("share"), 0, "streams");'), P.index('const o = JSON.parse(localStorage.getItem(DOCK_KEY) || "null");'))

    def test_phone_full_screen_sheet(self):
        css = P[P.index("/* ==== 0.21.84"):P.index("</style>", P.index("/* ==== 0.21.84"))]
        self.assertIn("@media (max-width: 720px), (max-height: 500px)", css)
        self.assertIn("height:100dvh !important; max-height:100dvh !important;", css)
        # after the generic phone sheet rules (they would cap it at 80dvh)
        self.assertGreater(P.index("/* ==== 0.21.84"), P.index(".popcard, #sharePop, #peoplePanel, #mineMenu { top:auto !important; bottom:0;"))

    def test_grouped_virtualized_filtered(self):
        b = _fn(LIB, "  function libBuildItems() {")
        for k in ('t: "site"', 't: "box"', 't: "row"', "libStatePass(e, libUi)", "libQueryPass(e, libUi.q)", "libUi.kinds", "libUi.site"):
            self.assertIn(k, b)
        r = _fn(LIB, "  function libRender() {")
        self.assertIn("while (a < b)", r)          # the first visible item by binary search
        self.assertIn("tops[i] < hi", r)           # only what is on screen (+ a margin) exists
        self.assertIn("el.remove(); libUi.els.delete(k);", r)
        self.assertIn('["live", "Live now"', LIB)
        for kind in ('"camera", "Cameras"', '"grid", "Grids"', '"screen", "Screens"', '"phone", "Phones"', '"vehicle", "Vehicles"', '"media", "Media"'):
            self.assertIn(kind, LIB)
        self.assertIn('new Option("All sites (" + total + ")", "")', LIB)   # the Site dropdown with counts
        self.assertIn('id="libOffline"', P)
        self.assertIn('<option value="recent">Most recently live</option>', P)
        sp = _fn(LIB, "  function libStatePass(e, ui) {")
        self.assertIn('return !(ui.live && st === "dark");', sp)   # Live now keeps the asleep cameras
        self.assertIn('if (st === "offline" || st === "site") return !!ui.offline;', sp)
        q = _fn(LIB, "  function libQueryPass(e, q) {")
        self.assertIn("e.label + \" \" + e.box + \" \" + e.site + \" \" + e.by", q)   # label, box, site, the publisher's name

    def test_stills_only_for_rows_on_screen(self):
        s = _fn(LIB, "  function libStillsLoad() {")
        self.assertIn("for (const [k, el] of libUi.els)", s)   # the rendered rows only
        self.assertIn("libStillN >= 6", s)
        self.assertIn('"/api/library/still?path="', LIB)

    def test_in_this_room_and_used_in(self):
        self.assertIn('tag("In this room", "here"', LIB)
        self.assertIn('tag("Used in " + e.usedIn', LIB)

    def test_row_actions_and_drag(self):
        a = _fn(LIB, "  function libActItems(e) {")
        for v in ('v: "add"', 'v: "spot"', 'v: "grid"', 'v: "my"', 'v: "me"', '"Add to this room"', '"Spotlight for everyone"', '"Add to a grid ›"', '"Add to My room"', '"Watch here, just me"'):
            self.assertIn(v, a)
        self.assertIn('ev.dataTransfer.setData(LIB_DND, e.path)', LIB)
        self.assertIn('stageWrap.addEventListener("drop"', LIB)
        d = _fn(LIB, "  function libDropOnStage(p) {")
        self.assertIn("if (!why) { libBoardPin(p, true); return; }", d)
        self.assertIn("libMeSet(p, true)", d)   # where I may not add: on my screen only

    def test_empty_room_and_tile_menu(self):
        self.assertIn('<button id="libEmptyCta" type="button" hidden', P)
        self.assertIn("Add streams from the library", P)
        self.assertIn("    try { libEmptyPaint(); } catch {}   // 0.21.84: an empty room offers the library", P)
        self.assertIn("        if (isLibPath(name)) libTileItems(name, items);", P)
        self.assertIn('          if (String(v).startsWith("lib:")) { libTileMenuPick(name, v); return; }', P)
        t = _fn(LIB, "  function libTileItems(name, items) {")
        self.assertIn('cap: "From the library · "', t)
        self.assertIn('label: "Remove from this room"', t)
        self.assertIn('label: "Open in the library"', t)
        for v in ('"astop"', '"amute"', '"akick"', '"rpin"'):   # the room / admin rows that do not apply go
            self.assertIn(v, t)


class Gating(unittest.TestCase):
    def test_capability_from_auth(self):
        self.assertIn("      libCapsTake(d);   // 0.21.84", _fn(P, "  async function authDetect() {"))
        c = LIB[LIB.index("    caps(d) {"):LIB.index("    async token() {")]
        self.assertIn("const on = d?.library === 1 || d?.library === true;", c)
        self.assertIn("relay: on, hub: on", c)   # library: 1 already means this relay AND its hub
        self.assertIn("function libOn() { return !!(libCaps.relay && libCaps.hub && !libCaps.off && !libCaps.killed); }", LIB)
        g = _fn(LIB, "  function libGate() {")
        self.assertIn("libBtn.hidden = !on;", g)
        self.assertIn("on = libOn() && !isPublisherMode() && !publishOnly;", g)

    def test_fleet_switch_off_hides_the_panel(self):
        t = _fn(LIB, "  function libTake(d, full, asked, since) {")
        self.assertIn("const off = d.on === false || d.enabled === false;", t)
        self.assertIn("libCaps.killed = true", t)


class LibraryConnection(unittest.TestCase):
    def test_tile_url_only_for_lib_paths(self):
        b = _fn(P, "  function tileUrl(name) {")
        self.assertTrue(b.split("\n")[1].strip().startswith("if (isLibPath(name)) return libUrl();"))
        u = _fn(LIB, "  function libUrl() {")
        self.assertIn('"lib=1"', u)
        self.assertIn("libConn.token", u)
        self.assertNotIn("authTokens", u)   # never the room token
        self.assertIn('const isLibPath = (p) => String(p || "").startsWith(LIB_ROOT + "/");', P)
        self.assertIn('const LIB_ROOT = "lib";', P)

    def test_viewer_token_and_guest_reminting(self):
        t = LIB[LIB.index("    async token() {"):LIB.index("    async list(since, paths) {")]
        self.assertIn('"/api/library/token"', t)
        self.assertIn("...this.auth()", t)   # Bearer = my member token, a header (never the URL)
        self.assertIn('scope: String(d.scope || "all")', t)
        self.assertIn('libConn.scope === "room"', _fn(LIB, "  function libBoardChanged() {"))
        self.assertIn("libMintKey()", _fn(LIB, "  async function libTokenEnsure(force) {"))

    def test_announce_watch_only_while_open(self):
        a = _fn(LIB, "  function libAnnStart() {")
        self.assertIn("Net.Path.Pattern?.subtree?.(Net.Path.from(LIB_ROOT))", a)   # the pattern: lib/** only
        self.assertIn("new Net.Connection({ url: new Signals.Signal(url), enabled: true })", a)
        self.assertIn("libUi.open", a)   # its redial only while open
        self.assertIn("libAnnStart()", _fn(LIB, "  function libOpened(quiet) {"))
        self.assertIn("libAnnStop();", _fn(LIB, "  function libClosed() {"))
        callers = [m.start() for m in re.finditer(r"libAnnStart\(\)", LIB)]
        self.assertLessEqual(len(callers), 4)   # libOpened, libRetoken (if open), its own redial (if open), the definition's name
        self.assertIn("if (libConn.conn) { libAnnStop(); if (libUi.open) libAnnStart(); }", LIB)

    def test_room_connections_untouched(self):
        # the room's own connection and its tiles keep their URL; nothing library-related is granted to them
        self.assertIn("const u = withToken(urlInput.value.trim());", _fn(P, "  function tileUrl(name) {"))
        self.assertNotIn("lib=1", _fn(P, "  function withToken(urlStr, role) {"))

    def test_board_adds_from_lib_without_proof(self):
        self.assertIn("    if (isLibPath(path)) return libBoardPin(path, on, quiet);", P)
        b = _fn(LIB, "  async function libBoardPin(path, on, quiet) {")
        self.assertIn('boardPost("pin", { path, from: LIB_ROOT, label, kind:', b)
        self.assertNotIn("tokens", b)
        self.assertIn(".filter((r) => r !== CHANNEL && r !== LIB_ROOT);", P)   # a room grid's library camera needs no proof
        m = _fn(LIB, "  async function libPersonalPin(path) {")
        self.assertIn("from: LIB_ROOT", m)
        self.assertIn('"/api/rooms/board"', m)

    def test_compat_listings_skipped_real_ones_kept(self):
        x = _fn(P, "  async function xsPoll() {")
        self.assertIn("|| it.lib === true) continue;", x)
        self.assertNotIn("|| isLibPath(p)) continue;", x)   # a box's Show-in-rooms listing FROM the library is a real tile
        self.assertIn("!libTiles.has(p)) scheduleRemoveTile(p);", x)


class NeverWakeOnBrowse(unittest.TestCase):
    def test_peek_only_for_live_rows(self):
        s = _fn(LIB, "  function libPeekShow(e, row, woke) {")
        self.assertIn('if (!woke && libStateOf(e) !== "live") return;', s)
        self.assertIn('w.setAttribute("name", e.low || e.path);', s)   # its -low copy when offered
        self.assertIn('w.setAttribute("url", libUrl());', s)          # on the library connection
        self.assertNotIn("odDemand", s)
        self.assertNotIn("odWake", s)

    def test_one_demand_only_from_preview(self):
        self.assertEqual(LIB.count("odDemand("), 1)
        self.assertEqual(LIB.count("odWake("), 1)   # 0.21.84 integration: only an OPENED pin / "just me" tile (libSync), never browsing
        self.assertIn("odWake(p)", _fn(LIB, "  async function libSync() {"))
        self.assertIn('if (why !== "grid") setTimeout(', _fn(LIB, "  async function libSync() {"))
        pv = _fn(LIB, "  function libPreview(e, row) {")
        self.assertIn("odDemand(e.path);", pv)
        self.assertIn("libPeekShow(e, row, true);", pv)
        # the hover / press-and-hold paths go to the peek, never a demand
        self.assertIn("libPeekArm(e, row)", LIB)
        self.assertNotIn("odDemand", _fn(LIB, "  function libPeekArm(e, row) {"))

    def test_encode_only_while_watched_covers_library_tiles(self):
        q = _fn(P, "  function odQuick() {")
        self.assertIn("if (!(xsTiles.has(name) || libTiles.has(name)) || parkedStreams.has(name) || t.cg) continue;", q)
        self.assertIn("if (libTiles.has(name) && !libWakeable(name)) continue;", q)
        u = _fn(P, "  function odPulse() {")
        self.assertIn("if (libTiles.has(name) && !parkedStreams.has(name)) {", u)   # a library tile watched here keeps its camera awake
        self.assertIn('if (libWakeable(name) && ((t.watch.getAttribute("visible") || "never") !== "never" || t.fb?.dataset.src)) odDemand(name);', u)
        d = _fn(P, "  function odDemand(broadcast) {")
        self.assertIn("const room = isLibPath(broadcast) ? LIB_ROOT :", d)


class HonestStates(unittest.TestCase):
    def test_states_from_the_row(self):
        s = _fn(LIB, "  function libStateOf(e) {")
        for k in ('if (!e || e.gone) return "gone";', 'if (e.unreachable) return "site";', 'if (e.offline) return "offline";'):
            self.assertIn(k, s)
        n = _fn(LIB, "  function libNorm(x) {")
        self.assertIn("unreachable: x.reach === false, offline: x.online === false, gone: !!x.gone", n)

    def test_cards_and_never_connecting(self):
        c = _fn(LIB, "  function libTileCard(p, t, pic) {")
        for txt in ('title: "Asleep", detail: "Starts when opened, 1–2 s"', 'title: "Not streaming"', '"No picture since "', '" · the box is online"',
                    'title: "Box offline"', 'title: "Site unreachable", detail: "List from "', 'title: "No longer in the library"'):
            self.assertIn(txt, c)
        self.assertNotIn("onnecting", c)
        self.assertIn("t.faceCap.textContent = t.libCap ? t.libCap : t.noDecode ?", P)   # the face's caption follows the card
        self.assertIn('mt ? (isLibPath(k) ? libSpotText(k) : "Connecting', P)          # a grid spot too
        self.assertIn('{ live: "Live", asleep: "Asleep", dark: "Not streaming", offline: "Offline", site: "Unreachable" }[st]', LIB)   # the panel's rows

    def test_hub_unreachable_banner(self):
        self.assertIn('"List from " + libHm(libMeta.listAt || libMeta.at) + ": the hub is unreachable', LIB)
        self.assertIn("libMeta.hubOk = !d.hubDown", LIB)


class PermissionGreys(unittest.TestCase):
    def test_reasons(self):
        w = _fn(LIB, "  function libAddWhy() {")
        for k in ("viewLockedForMe()", 'authRole === "viewer"', "authPersonal && isPersonalSlug(CHANNEL)", "boardCan()", "The view is locked"):
            self.assertIn(k, w)
        a = _fn(LIB, "  function libActItems(e) {")
        self.assertIn('t: "Watch here, just me", d: "On this device only; nothing is added to the room", why: joined ? "" : "Join a room first"', a)   # viewers too
        o = _fn(LIB, "  function libActOpen(e, anchor, page) {")
        self.assertIn("if (it.why) { b.disabled = true;", o)
        self.assertIn("const sub = it.why || it.d;", o)   # the reason shows under the greyed item
        self.assertIn('if (!boardCan()) { if (!quiet) window.__toast?.(libAddWhy()', _fn(LIB, "  async function libBoardPin(path, on, quiet) {"))


class BuilderLibraryGroup(unittest.TestCase):
    def test_cg_edit_hands_the_library(self):
        e = _fn(P, "  function cgEdit(name, isNew) {")
        self.assertIn("library: libBuilderSrc(),", e)
        self.assertIn('layout: isNew ? "n" + Math.max(1, t.cgDraft.slots.length) : "custom"', e)

    def test_editor_group_search_site_cost(self):
        self.assertIn("if (o.library) { try { list.appendChild(paintLib(f)); }", P)
        g = _fn(P, "      function paintLib(f) {")
        for k in ('mkEl("span", "", "Library")', 'new Option("All sites", "")', "U.site = sel.value", "m.slice(0, 60)", "camDrag(e, { kind: \"cam\", key: s.key"):
            self.assertIn(k, g)
        self.assertIn('o.library?.label?.(k) || "Camera (offline)"', P)
        self.assertIn("c.paintCost = () =>", P)
        h = _fn(LIB, "  function libCostHint(slots) {")
        self.assertIn('" from " + site + ", about " + mbps(x.kbps)', h)
        self.assertIn("libMeta.links?.[site]", h)

    def test_build_a_grid_from_these(self):
        self.assertIn("function cgNew() {", P)   # (still offered as before)
        self.assertIn("cgNewSeed?.length ? gb.preset(Math.min(gb.PRESET_MAX, cgNewSeed.length)) : gb.preset(4)", P)
        f = _fn(LIB, "  function cgNewFrom(keys) {")
        self.assertIn("try { cgNew(); } finally { cgNewSeed = null; }", f)
        self.assertIn('id="libBuild" class="primary" hidden', P)
        self.assertIn("setTimeout(() => cgNewFrom(keys), 0);", LIB)

    def test_grid_library_cameras_get_hidden_tiles(self):
        self.assertIn('    if (isLibPath(n)) return libTiles.get(n)?.why === "grid";', P)
        s = _fn(LIB, "  async function libSync() {")
        self.assertIn('for (const k of cgCams) if (isLibPath(k) && !want.has(k)) want.set(k, "grid");', s)
        self.assertIn('if (isLibPath(p?.path)) want.set(String(p.path), "pin");', s)
        self.assertIn('for (const p of libMeList()) if (!want.has(p)) want.set(p, "me");', s)


class AliasRewrite(unittest.TestCase):
    def test_device_local_keys_follow_aka(self):
        r = _fn(LIB, "  function libAkaRewrite(map) {")
        for k in ('"kastr.mygrids." + rel', '"kastr.cghide." + rel', '"kastr.pins." + rel', "ENABLED_KEY", "PARKED_KEY", "XS_PATHS_KEY()", '"kastr.libme." + rel'):
            self.assertIn(k, r)
        self.assertIn("cghMem = null; pinsKeyLoaded = \"\";", r)   # the in-memory copies follow
        self.assertIn("try { libAkaTake(); }", _fn(LIB, "  function libTake(d, full, asked, since) {"))
        n = _fn(LIB, "  function libNorm(x) {")
        self.assertIn("...(x.alias ? [x.alias] : [])", n)   # a paths= answer's alias is an old path too


class BoxPublishing(unittest.TestCase):
    def test_picker_switch_for_box_cameras(self):
        self.assertIn("    if (srv && libOn()) list.prepend(libPickerRow(srv, label));", _fn(P, "  function openXsPicker(path, anchor, opts) {"))
        r = _fn(LIB, "  function libPickerRow(srv, label) {")
        self.assertIn('"In the stream library: everyone on the fleet can add it"', r)
        self.assertIn("libApi.boxSet(srv.id, cb.checked)", r)
        self.assertIn('"/api/rtsp/library"', LIB)
        self.assertIn("library: f.publish?.library ?? null, lib: f.lib ?? null", P)   # L from /api/rtsp/list

    def test_no_room_option_relabelled(self):
        self.assertIn('if (isPublisherMode() && libOn()) sel.options[sel.options.length - 1].text = "No room: share cameras to the stream library (and any rooms I pick)";', P)


class RelayPage(unittest.TestCase):
    def test_card_switch_and_preflight(self):
        self.assertIn('<section class="panel" id="libAdmPanel" hidden>', R)
        self.assertIn('id="libFleetOn"', R)
        self.assertIn("const r = await libAdmOp({ on });", R)   # POST /api/relay/library {on}
        self.assertIn('fetch("/api/relay/library", { cache: "no-store" })', R)
        self.assertIn("the library's reserved name. Rename that room", R)
        self.assertIn('id="libPre"', R)

    def test_admin_hide_label_site(self):
        self.assertIn('libAdmOp({ op: hidden ? "unhide" : "hide", path })', R)
        self.assertIn('libAdmOp({ op: "label", path, label: v.trim().slice(0, 80) })', R)
        self.assertIn('libAdmOp({ op: "site", node: n.node, site: inp.value.trim().slice(0, 48) })', R)
        self.assertIn('<details id="libSitesBox" hidden>', R)
        self.assertLess(R.index('id="linksBox"'), R.index('id="libSitesBox"'))   # on the Links card
        self.assertLess(R.index('id="libSitesBox"'), R.index('id="usersBox"'))

    def test_min_version_badge(self):
        self.assertIn('const LIB_MIN_VERSION = "0.21.84";', R)
        self.assertIn(">needs update</span>", R)
        self.assertIn("libVerLt(n.version, min)", R)

    def test_box_master_switch(self):
        self.assertIn('id="libBoxOn"', R)
        self.assertIn("JSON.stringify({ master: sw.checked })", R)


if __name__ == "__main__":
    unittest.main()
