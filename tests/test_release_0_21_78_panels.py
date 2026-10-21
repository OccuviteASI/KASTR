# -*- coding: utf-8 -*-
"""v0.21.78 part B (Kenton 2026-10-21):
1. "When clicking a drop down menu, if there is room below it, there shouldn't be a scroll bar, it should just show the whole
   list." -- one sizing helper (dropFit) for every dropdown: full height when it fits below its button, else the side with more
   room, capped there.
2. "When clicking on the people, view, files, chat, and share menus, don't collapse them until clicking outside of them or
   clicking on another menu item, or clicking on the same menu item." -- window blur is no longer an outside click; the
   confirm popup, the chat attach picker and View / Files / Share picks no longer close the panel.
3. "Allow user to pin people, view, files, chat, share to the right side of the right rail instead of always being a drop down
   menu item." -- the pinned column (#kDock): stacked sections, resizable, per device, not on phones.
4. "We don't need to show the time counting up on a room until a person is in the room, not just camera boxes."

Run: python -m unittest discover -s tests
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page():
    with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8", newline="") as f:
        return f.read()


def between(p, a, b):
    i = p.index(a)
    return p[i:p.index(b, i)]


class DropdownsFit(unittest.TestCase):
    def setUp(self):
        self.p = page()

    def test_one_helper(self):
        body = between(self.p, "  function dropFit(el, r, gap = 6, pad = 8) {", "  window.__dropFit = dropFit;")
        self.assertIn('el.style.maxHeight = "none";', body)                     # measure the whole list
        self.assertIn("const down = h <= below || below >= above;", body)       # below when it fits (or has more room)
        self.assertIn('el.style.maxHeight = room + "px";', body)                # capped only to the room it has
        self.assertEqual(self.p.count("function dropFit("), 1)

    def test_every_dropdown_uses_it(self):
        self.assertIn("dropFit(pop, b);", between(self.p, "  function placePop(pop, btn) {", "  function registerPop("))
        self.assertIn("return dropFit(menu, r, 4);", self.p)                    # #mineMenu + the room menus (menuTopFor)
        self.assertIn("dropFit(chatPanel, bar);", self.p)
        self.assertEqual(self.p.count("dropFit(pop, a);   // 0.21.78: the whole list when it fits below"), 2)   # #xsPop, #wrPop
        self.assertIn("dropFit(pop, r);   // 0.21.78: one sizing rule for every dropdown", self.p)              # grid layouts
        # the fixed 600 px cap no longer decides: placePop no longer sets top without a height
        self.assertNotIn('pop.style.top = Math.round(b.bottom + 6) + "px";', self.p)

    def test_phone_sheets_drop_the_inline_height(self):
        self.assertIn('if (isPhone()) { pop.style.top = ""; pop.style.left = ""; pop.style.maxHeight = ""; return; }', self.p)
        self.assertIn('if (isPhone()) { menu.style.left = ""; menu.style.top = ""; menu.style.maxHeight = ""; return; }', self.p)


class PanelsStayOpen(unittest.TestCase):
    def setUp(self):
        self.p = page()

    def test_blur_is_not_an_outside_click(self):
        blur = between(self.p, '  window.addEventListener("blur", () => {', "  // 0.8.9: open a file picker WITHOUT")
        self.assertIn('if (document.activeElement?.tagName !== "IFRAME") return; closeAllPops(); closeMineMenu();', blur)
        self.assertIn('window.top.document.addEventListener("pointerdown", () => { closeAllPops(); closeMineMenu(); }, true);', blur)

    def test_confirm_never_reaches_the_page(self):
        body = between(self.p, "  function kastrConfirm(o) {", "  window.__confirm = kastrConfirm;")
        self.assertIn('el.addEventListener("click", (e) => e.stopPropagation());', body)

    def test_chat_attach_goes_through_pickfile(self):
        self.assertIn('document.getElementById("chatFileBtn").addEventListener("click", () => window.__pickFile(chatFileInp));', self.p)
        self.assertNotIn("() => chatFileInp.click()", self.p)

    def test_view_picks_keep_view_open(self):
        view = between(self.p, '  document.getElementById("viewGallery").addEventListener', "  // hide-me follows newly started camera panes too")
        self.assertEqual(view.count("closeAllPops()"), 1)                           # Full screen only
        self.assertIn('document.getElementById("viewFull").addEventListener("click", () => {\r\n    closeAllPops();', view)

    def test_files_upload_and_share_picks_keep_them_open(self):
        self.assertIn('document.getElementById("filesUpload").addEventListener("click", () => { window.__pickFile(document.getElementById("shareFile")); });', self.p)
        self.assertEqual(self.p.count('document.querySelector("#sharePop .close")?.click()'), 1)   # only "Background effects" (opens the camera menu)


class PinnedColumn(unittest.TestCase):
    def setUp(self):
        self.p = page()

    def test_markup(self):
        self.assertIn('<div id="stagerow">\r\n<div id="stagewrap" class="asi-dark">', self.p)
        self.assertIn('<aside id="kDock" hidden aria-label="Pinned panels"><div id="kDockGrip" role="separator"', self.p)
        self.assertIn("  #stagerow > #stagewrap { flex:1; min-width:0; }", self.p)    # the stage shrinks, never covered
        self.assertIn("#kDock > .docked { position:relative !important;", self.p)
        self.assertIn("flex:var(--fl, 1) 1 0px;", self.p)                           # sections share the height by weight
        self.assertIn("#kDock > .docked.folded > :not(.head) { display:none !important; }", self.p)
        self.assertIn("    .head > .kpin, #kDock { display:none !important; }   /* 0.21.78: no pinned column on a phone */", self.p)
        self.assertIn("#kDockGrip:focus-visible, .kdsplit:focus-visible { outline:2px solid var(--asi-blue);", self.p)

    def test_the_five_panels(self):
        self.assertIn('const DOCK_KEY = "kastr.dock", DOCK_ORDER = ["people", "view", "files", "chat", "share"];', self.p)
        for k in ("people:", "view:", "files:", "chat:", "share:"):
            self.assertIn("    " + k + " { pop: ", self.p)
        self.assertIn("const want = isPhone() ? [] : DOCK_ORDER.filter((k) => dockSt.pins.includes(k));", self.p)
        self.assertIn("try { dockApply(); } catch {}   // 0.21.78: a phone-sized window has no pinned column", self.p)

    def test_saved_per_device_with_try(self):
        self.assertIn('try {\r\n    const o = JSON.parse(localStorage.getItem(DOCK_KEY) || "null");', self.p)
        self.assertIn("const dockSave = () => { try { localStorage.setItem(DOCK_KEY, JSON.stringify(dockSt)); } catch {} };", self.p)

    def test_a_pinned_panel_is_no_dropdown(self):
        reg = between(self.p, "  function registerPop(pop, btn, onOpen) {", "    pagePops.push(entry);")
        self.assertIn('isOpen: () => !pop.hidden && !pop.classList.contains("docked")', reg)
        self.assertIn('close: () => { if (pop.classList.contains("docked")) return;', reg)
        self.assertIn('if (pop.classList.contains("docked")) { dockBtnClick(pop); return; }', reg)
        self.assertIn('if (sharePop.classList.contains("docked")) { dockBtnClick(sharePop); return; }', self.p)
        self.assertIn('if (sharePop.classList.contains("docked")) return;   // 0.21.78: a pinned Share stays', self.p)
        self.assertIn('chatEntry.close = () => { if (chatPanel.classList.contains("docked")) return; orig(); chatClosedHooks(); };', self.p)
        self.assertIn('if (!pp.classList.contains("docked")) pp.hidden = true;', self.p)   # Leave keeps a pinned People

    def test_resizing(self):
        self.assertIn('s.setAttribute("role", "separator"); s.setAttribute("aria-orientation", "horizontal");', self.p)
        self.assertIn('if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;', self.p)
        self.assertIn('if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;', self.p)
        self.assertIn("const fa = +((wA + wB) * nA / (hA + hB)).toFixed(4)", self.p)

    def test_pinned_chat_takes_no_focus(self):
        self.assertIn("function chatOpened(quiet) {", self.p)
        self.assertIn("if (!quiet) chatInput.focus();", self.p)
        self.assertIn('chat: { pop: chatPanel, btn: chatBtn, name: "Chat", fl: 1.4, show: (user) => chatOpened(!user)', self.p)

    def test_pinned_share_refreshes_only_while_hovered(self):
        self.assertIn("window.__shareIdle = () => { clearInterval(shTimer); shTimer = null; };", self.p)
        self.assertIn('sharePop.addEventListener("pointerleave", () => { if (isDocked(sharePop)) dockShareLive(false); });', self.p)

    def test_unpin_icon(self):
        self.assertIn("    unpin: '<path d=", self.p)


class PeopleTimers(unittest.TestCase):
    def setUp(self):
        self.p = page()

    def test_boxes_start_no_timer(self):
        rooms = between(self.p, "  function deriveRooms() {", "  function lastJoin() {")
        hidden = between(rooms, "      if (presenceHidden(p.who)) {", "        continue;")
        self.assertNotIn("r.since", hidden)
        self.assertEqual(rooms.count("if (p.ts && (!r.since || p.ts < r.since)) r.since = p.ts;"), 1)   # the people branch only
        self.assertIn("if (p.ts && !presenceHidden(w)) sinceTs.set(key, p.ts); else sinceTs.delete(key);", self.p)

    def test_no_timer_shown_until_a_person(self):
        self.assertIn('t.hidden = !rec.since; t.textContent = rec.since ? "\\u23F1 " + fmtHm(Date.now() - rec.since) : "";', self.p)
        self.assertIn('t.hidden = !card.__since; t.textContent = card.__since ? "\\u23F1 " + fmtHm(now - card.__since) : "";', self.p)
        self.assertNotIn('"\\u23F1 \\u2014"', self.p)


if __name__ == "__main__":
    unittest.main()
