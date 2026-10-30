"""0.21.96 (Kenton 2026-10-30: "I want the ability to lock a share in the shared sources, and when stopping sharing, they stay
there and can be started again. Per share option." -- and on the details: "My share list, I restart."). A share's Lock switch
(its row in Share and its options menu): a LOCKED share that is stopped stays in my Share list as a stopped row with Start, stays
in the stream library as "Not streaming", survives a restart (kastr.share.locked, mirrored to this device's prefs.json -- no
codes, no tokens, no camera addresses), and Start brings it back under the SAME stream name, so pins, grids and spotlights
reconnect. Screens / windows / tabs never capture by themselves: the browser's picker, or the exact native source, or a pick.
Unlocked shares behave exactly as before. Camera feeds (RTSP, webcams, host files, RTMP) keep "Keep after restart" instead."""
import importlib
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def fn(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i + len(start))]


class LockedShares(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = read("moq-watch-lite.html")

    def once(self, needle):
        self.assertEqual(self.s.count(needle), 1, needle[:100])

    # ---- what can be locked
    def test_lockable_kinds(self):
        body = fn(self.s, "function lockable(a) {", "function lockKind(a)")
        self.assertIn("if (!a || a.presCanvas || a.presVideo) return false;", body)   # not presentations, not slide videos
        self.assertIn("return a.kind === SCREEN || a.kind === FILE || (a.kind === RTSP && !IS_WEB2 && isScreenUrl(a.url));", body)
        self.assertNotIn('"camera"', body)   # the toolbar camera and camera feeds are not lockable (Keep after restart)

    def test_lock_kinds_are_declarations(self):   # lockLoad runs at boot, before a const arrow further down would exist
        self.once("function lockKind(a) {")
        self.once("function lockNewK() {")
        i = self.s.index("parked.push(...lockLoad());")
        self.assertLess(i, self.s.index("function lockLoad() {"))

    # ---- the switches (toggles, never tick boxes)
    def test_row_switch(self):
        body = fn(self.s, "if (lockable(a)) {   // 0.21.96: Lock this share", "lbl.title = a.label;")
        self.assertIn('lw.innerHTML = \'<span class="switch sm"><input type="checkbox"><i></i></span> <span>Lock</span>\';', body)
        self.assertIn('li.addEventListener("change", () => lockSet(a.id, li.checked, false));', body)

    def test_menu_switch(self):
        self.once('if (slk) items.push({ value: "slock", label: "Lock this share", sw: !!window.__shareLock.get(ref.id),')
        self.once('window.__shareLock?.set?.(ref.id, !window.__shareLock?.get?.(ref.id), true);')
        body = fn(self.s, 'if (typeof it.sw === "boolean") {', "b.title = it.tip || it.label;")
        self.assertIn('msw.className = "switch sm misw";', body)
        self.assertIn('msw.append(msi, document.createElement("i"));', body)
        self.assertIn('b.setAttribute("role", "menuitemcheckbox");', body)
        self.assertIn("ref.peer === window.__publisher?.peer", fn(self.s, "const slk = ", ";"))   # mine only

    # ---- Stop keeps it; the stopped row
    def test_remove_parks_a_locked_share(self):
        body = fn(self.s, "function removeSource(id, forget) {", "renderPickers();")
        self.assertIn("if (going.locked && lockable(going) && !forget) parkShare(going);", body)
        self.assertLess(body.index("parkShare(going)"), body.index("stopSlot(id);"))   # the record is taken while the slot is still there
        self.assertIn("if (going.locked) lockSave();", body)

    def test_stopped_row(self):
        body = fn(self.s, "for (const rec of parked) {\n      const row", "let remoteCount = 0;")
        self.assertIn('row.className = "camrow parked";', body)
        self.assertIn('<span class="badge stopped">stopped</span>', body)
        self.assertIn('<span class="switch sm"><input type="checkbox" checked><i></i></span>', body)
        self.assertIn('<button class="start" type="button">Start</button>', body)
        self.assertIn('st.addEventListener("click", () => { lockStart(rec.k); });', body)
        self.assertIn('lk.addEventListener("change", () => { if (!lk.checked) lockForget(rec.k, true); });', body)
        self.assertIn("Same stream name, so pins, grids and spotlights reconnect.", body)
        self.assertIn("+ parked.length;", fn(self.s, "const localN = ", "\n"))

    def test_a_locked_file_that_ends_parks(self):
        self.once("if (entry.locked) { removeSource(entry.id); return; }   // 0.21.96")

    # ---- persisted per device, nothing secret
    def test_store_key_and_whitelist(self):
        self.once('const LOCK_KEY = "kastr.share.locked", LOCK_MAX = 24;')
        load = fn(self.s, "function lockLoad() {", "let lockSaved = null;")
        self.assertIn('["screen", "native", "presenter", "file"].includes(r.kind)', load)
        self.assertIn(r"/^[^/\s]+\/(?:[^/\s]+\/)?[^/\s]+\.hang$/.test(name)", load)
        self.assertIn("rec.url = isScreenUrl(r.url) ? String(r.url).slice(0, 120) : \"\";", load)   # screen:// only, never a camera address
        spec = fn(self.s, "function lockSpec(a) {", "function lockLoad() {")
        self.assertIn('rec.url = isScreenUrl(a.url) ? String(a.url).slice(0, 120) : "";', spec)
        for bad in ("access", "token", "roomCode", "password", "a.code"):
            self.assertNotIn(bad, spec)
            self.assertNotIn(bad, load)
        fields = set(re.findall(r"rec\.([a-zA-Z]+) =", spec + load))
        self.assertLessEqual(fields, {"kind", "url", "audio", "exe", "presenter", "surface", "sound", "fileName", "shareH", "loop", "gain", "lib"})

    def test_never_started_by_itself(self):
        self.once("parked.push(...lockLoad());   // 0.21.96: my locked shares from the last session -- listed stopped, never started by themselves")
        boot = self.s[self.s.index("parked.push(...lockLoad());"):self.s.index("parked.push(...lockLoad());") + 200]
        self.assertNotIn("lockStart", boot)

    def test_live_locked_record_kept_current(self):
        self.once("setInterval(() => { if (added.some((a) => a.locked)) { try { lockSave(); } catch {} } }, 10000);")
        self.once('document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden" && added.some((a) => a.locked)) { try { lockSave(); } catch {} } });')

    def test_prefs_mirror_allows_it(self):
        self.assertIn("|camfx$|share\\.locked$|toasts\\.|", read(os.path.join("assets", "prefs.js")))
        self.assertIn('|watch\\.|camfx$|share\\.locked$|toasts\\.|rooms\\.groups\\.|mainroom$|view\\.hideMine$"', read("kastr_serve.py"))
        sys.path.insert(0, ROOT)
        ks = importlib.import_module("kastr_serve")
        self.assertTrue(ks.PREFS_ALLOW.match("kastr.share.locked"))
        self.assertFalse(ks.PREFS_ALLOW.match("kastr.share.lockedX"))

    # ---- Start: the same name; the browser / the exact source / a pick -- never a capture nobody chose
    def test_start_screen_asks_the_browser(self):
        body = fn(self.s, "async function lockStart(k) {", 'if (rec.kind === "file") {')
        code = " ".join(line.split("//")[0] for line in body.splitlines())   # comments may say "awaited"
        self.assertNotIn("await ", code)   # the click stays the gesture getDisplayMedia needs
        self.assertIn("addSource(SCREEN, null, rec.label || \"Screen\", { surface: rec.surface || undefined, name, label: rec.label || \"Screen\", askSound: !!rec.sound, micMuted: !rec.sound });", body)
        self.assertIn("const name = lockName(rec.name);", body)
        self.assertIn("stream = await displayAsk(slot.entry.surface, slot.entry.askSound);", self.s)

    def test_start_file(self):
        body = fn(self.s, 'if (rec.kind === "file") {', "rec.starting = true;")
        self.assertIn("if (f) return shareMediaFile(f, lockFileOpts(rec, name, f));", body)
        self.assertIn("pendingFileRestart = rec.k;", body)
        self.assertIn("window.__pickFile ? window.__pickFile(fileInput) : fileInput.click();", body)
        self.once("return shareMediaFile(picked, pr ? lockFileOpts(pr, lockName(pr.name), picked) : null);")

    def test_start_native_exact_source_or_a_pick(self):
        plan = fn(self.s, "function lockPlan(rec, d) {", "function shRestartPaint()")
        self.assertIn('if (!rec?.url || !d || !d.ok) return "pick";', plan)
        self.assertIn("shareKey(s) === rec.url", plan)
        self.assertIn('if (rec.exe ? prog !== String(rec.exe).toLowerCase() : String(src.title || "") !== String(rec.label || "")) return "pick";', plan)
        body = fn(self.s, "rec.starting = true; renderSources();", 'document.getElementById("shRestartCancel")')
        self.assertIn('if (lockPlan(rec, d) === "start") {', body)
        self.assertIn("shRestart = rec.k; shRestartPaint();", body)   # gone: Share asks
        self.assertIn('<p id="shRestartNote" hidden>', self.s)
        self.once("const rr = shRestartTake();   // 0.21.96: Start on a stopped locked share -> this pick comes back under its name")
        self.once("const rr = shSwap == null ? shRestartTake() : null;")

    def test_claim_by_name(self):
        self.once("lockClaim(entry);   // 0.21.96")
        body = fn(self.s, "function lockClaim(e) {", "function lockForget(")
        self.assertIn("parked.findIndex((r) => r.name === n || lockName(r.name) === n)", body)
        self.assertIn("e.locked = true;", body)

    def test_taken_names_hold_a_stopped_share_name(self):   # nothing else takes its name while it is stopped
        body = fn(self.s, "function takenNames(", "\n  }")
        self.assertIn("parked", body)

    # ---- the stream library keeps it as not streaming
    def test_library_dark_row(self):
        body = fn(self.s, "async function libShSync(force) {", "if (!rows.length && !LIBSH.posted) return;")
        self.assertIn("if (ok) for (const rec of parked) {", body)
        self.assertIn('kind: rec.kind === "file" ? "media" : "screen", state: "dark", audio: false', body)
        self.assertIn("if (!(rec.lib ?? !!LIBSH.here) || rows.some((x) => x.path === p)) continue;", body)


if __name__ == "__main__":
    unittest.main()
