"""0.21.15: Part 39 item 7b + P12a / P12c -- structural checks on moq-watch-lite.html (the page is not executable here).

Run: python -m unittest discover -s tests -t .   (build.py runs it before every build)

The remote-grid cell click shows the composite's cell zoomed at once, decodes the camera OFF-STAGE (visible="always"
needs no canvas) and swaps on its first decoded frame; a never-painted shown tile gets a notice and one re-subscribe;
decodeSupported probes the full rendition config; page Broadcasts carry maxAge 5000 like the native pairs. These tests
pin every anchor of the change, the skeptic's amended positions (fallback guards, the tick placement before the
bytes-advance continue, the element maxAge before `url`, all seven abandon paths, the hidden-window clock hold, the
rail-hidden "never" branch yielding to keepWarm) and the two library facts the change rests on (`import --max-age 5s`,
hang's 30 s default). No network, no processes.
"""
import os
import sys
import unittest

HERE = os.environ.get("KASTR_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
PAGE = os.path.join(HERE, "moq-watch-lite.html")
RTSP = os.path.join(HERE, "kastr_rtsp.py")
CONTAINER = os.path.join(HERE, "assets", "vendor", "esm", "@moq", "hang@0.5.2", "es2022", "container.mjs")


def read(p):
    with open(p, "r", encoding="utf-8", newline="") as f:
        return f.read()


class CellOpen(unittest.TestCase):
    def setUp(self):
        self.page = read(PAGE)

    def once(self, s):
        self.assertEqual(self.page.count(s), 1, s)

    def block(self):
        """The inserted cold-open block: from gridOpenStart to the end of paintNeverPainted."""
        p = self.page
        i = p.index("const GRID_OPEN_POLL_MS = 200")
        j = p.index("function paintNeverPainted(name, t, nowMs, bytes) {")
        k = p.index("\n  }", j)   # the function's closing brace (two-space indent)
        return p[i:k]

    def test_page_is_crlf_throughout(self):
        crlf = self.page.count("\r\n")
        self.assertGreater(crlf, 0)
        self.assertEqual(self.page.count("\n") - crlf, 0, "bare LF in moq-watch-lite.html")

    def test_cold_open_machine_present_once(self):
        for s in ("let gridOpen = null;", "function gridOpenStart(gp, idx, fp) {", "function gridOpenBytes(o) {",
                  "function gridOpenTick() {", "function gridOpenEnd(swap) {", "function gridOpenText() {",
                  "function paintNeverPainted(name, t, nowMs, bytes) {", "window.__cellOpen = ", "window.__tilePicture = ",
                  "const GRID_PARKED_WARM = true;",
                  "const GRID_OPEN_POLL_MS = 200, GRID_OPEN_NODATA_MS = 15000, GRID_OPEN_GIVEUP_MS = 90000;",
                  "const NEVER_PAINTED_MS = 8000, NEVER_PAINTED_RESUB_MS = 20000;"):
            self.once(s)

    def test_block_is_in_the_watch_module_and_ascii(self):
        # module 1 (watch) holds tiles/applyState/the tick; the block must sit after window.__gridWake and before the
        # publish module's own script. Glyphs are JS escapes (— ...), never literal characters.
        p = self.page
        i = p.index("window.__gridWake = () => gridWake;")
        j = p.index("function gridOpenStart(gp, idx, fp) {")
        k = p.index('from "https://esm.sh/@moq/publish"')
        self.assertLess(i, j)
        self.assertLess(j, k)
        b = self.block()
        bad = sorted({ch for ch in b if ord(ch) > 127})
        self.assertEqual(bad, [], "literal non-ASCII in the cold-open block: %r" % bad)
        for esc in ("\\u2014", "\\u2026", "\\u2019", "\\u23f3"):
            self.assertIn(esc, b)

    def test_fallback_clients_take_the_old_path(self):
        # no WebCodecs = a <video> fallback tile with no video.out.frame: neither the cold open nor the notice may wait on it
        self.once("if (!t || t.fb || !CLIENT.webcodecs || !isWatched(fp)) return false;")
        self.once("const never = shown && !t.fb && CLIENT.webcodecs && since !== undefined")

    def test_never_predicate_has_no_frame_count_clause(self):
        # frameCount may not reset on a never->always cycle; hasPicture alone is 'the pane is black right now'
        b = self.block()
        i = b.index("const never = ")
        j = b.index("\n", i)
        line = b[i:j]
        self.assertIn("!hasPicture(t)", line)
        self.assertNotIn("lastFrames", line)
        self.assertNotIn("frameCount", line)
        self.assertIn('(t.watch.getAttribute("visible") || "never") !== "never"', line)

    def test_click_enters_cold_open_before_select(self):
        i = self.page.index("if (gridOpenStart(name, idx, fp)) return;")
        j = self.page.index("select(fp); return;", i)
        self.assertLess(i, j)
        self.assertLess(j - i, 400)   # the very next statement in the 0.21.7 block
        # the on-demand wake path joins it too
        self.once("setTimeout(() => { if (tiles.has(name) && !gridOpenStart(gp, idx, name)) select(name); }, 0);")
        self.once("const gp = gridWake.gp, idx = gridWake.idx;")

    def test_keep_warm_governs_visible(self):
        self.once('const wantVisible = (!shown && !keepWarm) ? "never"')
        self.once(': (isSelected || keepWarm) ? "always"')
        self.once("const keepWarm = (gridOpen && gridOpen.path === name) || (GRID_PARKED_WARM && gridParked(name));")
        self.assertNotIn('const wantVisible = !shown ? "never"', self.page)
        # the rail-hidden branch holds every hiddenChild (the parked composite, the off-stage camera child: applyState adds
        # them to railHiddenNames) and sits BEFORE "always" -- it must yield to keepWarm or the camera never subscribes
        self.once(': (!gridMode && railHiddenNames.has(name) && !keepWarm) ? "never"')
        self.assertNotIn(': (!gridMode && railHiddenNames.has(name)) ? "never"', self.page)
        # document.hidden still wins: its branch sits between the two keepWarm branches, after the rail-hidden one
        p = self.page
        i = p.index('const wantVisible = (!shown && !keepWarm) ? "never"')
        r = p.index(': (!gridMode && railHiddenNames.has(name) && !keepWarm) ? "never"', i)
        h = p.index('(document.hidden && !window.__rigVisible) ? "never"', i)
        j = p.index(': (isSelected || keepWarm) ? "always"', i)
        self.assertLess(i, r)
        self.assertLess(r, h)
        self.assertLess(h, j)
        # every "never" branch between the two keepWarm lines is either neutral to keepWarm (audio-only, hidden window,
        # fullscreen) or carries the !keepWarm guard -- no other rail/display gate may sit in that span
        span = p[i:j]
        self.assertEqual(span.count("railHiddenNames.has(name)"), 1)

    def test_visible_since_is_written_where_visible_is(self):
        p = self.page
        self.once('t.visibleSince = wantVisible === "never" ? undefined : performance.now();')
        i = p.index('t.watch.setAttribute("visible", wantVisible);')
        j = p.index("t.visibleSince = ")
        self.assertLess(i, j)
        self.assertLess(j - i, 200)

    def test_badge_painter_covers_both_waits(self):
        self.once("const w = gridWake || gridOpen;")
        self.once("const t = tiles.get(w.gp), meta = gridMeta.get(w.gp);")
        self.once("[w.idx];")
        self.once("if (gridZoom && gridZoom.name === w.gp && gridZoom.idx === w.idx)")
        self.once("const text = w === gridWake ? (gridWake.low ?")
        self.once("el.innerHTML = '<span>\\u23f3 ' + text + '</span>';")
        self.assertNotIn("[gridWake.idx]", self.page)   # every cell lookup in paintGridWait follows the live wait
        self.assertNotIn("tiles.get(gridWake.gp)", self.page)
        self.once("#stage .pane .pwait {")
        # the CSS sits right after the 0.21.2 badge rule, i.e. before the phone blocks that must stay last
        i = self.page.index("#stage .pane .gwait {")
        j = self.page.index("#stage .pane .pwait {")
        self.assertLess(i, j)
        self.assertLess(j - i, 600)

    def test_never_painted_runs_before_the_bytes_advance_continue(self):
        p = self.page
        i = p.index("try { stalled = el.video?.out?.stalled?.peek?.() === true; } catch {}")
        j = p.index("paintNeverPainted(name, t, nowMs, bytes);")
        k = p.index("if (bytes > (t.lastStarveBytes ?? 0) && !stalled) {")
        self.assertLess(i, j)
        self.assertLess(j, k)
        self.assertEqual(p.count("paintNeverPainted(name, t, nowMs, bytes);"), 1)
        # both early continues drop a stale notice
        self.assertEqual(p.count("paintNeverPainted(name, t, nowMs, 0); continue; }"), 2)
        self.once('if (el.getAttribute("visible") === "never") { t.starveSince = nowMs; t.framesSince = nowMs; paintNeverPainted(name, t, nowMs, 0); continue; }')
        self.once("if (t.hasVideo === false) { t.starveSince = nowMs; t.framesSince = nowMs; paintNeverPainted(name, t, nowMs, 0); continue; }")
        # and the design's original (skipped) position is NOT used
        s = p.index("stallReport(name, nowMs);")
        self.assertLess(j, s)

    def test_cold_open_is_abandoned_on_every_exit(self):
        p = self.page
        # start, tick (moved on), tick (give-up), Gallery pill, cell click, zoom label, dblclick
        self.assertEqual(p.count("gridOpenEnd(false);"), 7)
        self.once('stageBack.addEventListener("click", (e) => { e.stopPropagation(); gridOpenEnd(false);')
        self.once("if (viewZoomed(tile.canvas)) { gridOpenEnd(false); gridZoom = null; viewReset(tile.canvas); fitMainstage(lastRail.rows); return; }")
        self.once("if (c && viewZoomed(c)) { gridOpenEnd(false); gridZoom = null; viewReset(c); fitMainstage(lastRail.rows); }")
        self.once("if (viewZoomed(c)) { gridOpenEnd(false); gridZoom = null; viewReset(c); } else viewZoomAt(c, 2, e.clientX, e.clientY);")
        # the swap path ends it too, then selects the camera
        self.once("gridOpenEnd(true); select(o.path); return;")
        # a room change kills the poll before the per-room facts are reset
        self.once("if (gridOpen) { clearInterval(gridOpen.timer); gridOpen = null; }")
        i = p.index("if (gridOpen) { clearInterval(gridOpen.timer); gridOpen = null; }")
        j = p.index("gridMeta.clear(); gridChildOf.clear(); gridZoom = null;")
        self.assertLess(i, j)
        self.assertLess(j - i, 300)

    def test_tick_holds_the_clock_while_hidden_and_retries_once(self):
        self.once("if (document.hidden && !window.__rigVisible) { o.at += GRID_OPEN_POLL_MS; return; }")
        self.once('if (o.bytes <= 0 && !o.retried && now - o.at > GRID_OPEN_NODATA_MS) { o.retried = true; resubscribe(o.path, "No data from the relay"); }')
        self.once('if (bytes <= 0 && !t.coldResub && nowMs - since > NEVER_PAINTED_RESUB_MS) { t.coldResub = true; resubscribe(name, "No data from the relay"); }')
        b = self.block()
        # the hidden hold comes before any bytes/picture judgement in the tick
        i = b.index("function gridOpenTick() {")
        h = b.index("if (document.hidden && !window.__rigVisible)", i)
        g = b.index("gridOpenBytes(o);", h)
        self.assertLess(h, g)

    def test_status_log_lines_for_the_field(self):
        b = self.block()
        self.assertIn('log("Opening " + shortLabel(fp) + " \\u2014 waiting for its first frame");', b)
        self.assertIn('log("Opened " + shortLabel(o.path) + " after "', b)
        self.assertIn('log("Could not open " + shortLabel(o.path) + " \\u2014 " + why);', b)
        self.assertIn('window.__toast?.("That camera did not start \\u2014 " + why + ".", 6000, { level: "warn" });', b)


class DecodeProbe(unittest.TestCase):
    def setUp(self):
        self.page = read(PAGE)

    def test_full_config_probe(self):
        page = self.page
        self.assertEqual(page.count('import { Net, Signals, Video as WatchVideo } from "https://esm.sh/@moq/watch";'), 1)
        self.assertNotIn('import { Net, Signals } from "https://esm.sh/@moq/watch";', page)
        self.assertEqual(page.count("function decodeSupported(rend) {"), 1)
        self.assertNotIn("function decodeSupported(codec) {", page)
        self.assertEqual(page.count("WatchVideo?.Decoder?.supported"), 1)
        self.assertEqual(page.count("full({ ...r })"), 1)   # a copy: the probe rewrites codec on avc3 -> avc1
        self.assertEqual(page.count("Promise.all(rends.map((r) => decodeSupported(r)))"), 1)
        self.assertNotIn("Promise.all(codecs.map((c) => decodeSupported(c)))", page)
        self.assertEqual(page.count("const rends = Object.values(cat.video.renditions).filter((r) => r && !r.broadcast && r.codec);"), 1)
        self.assertEqual(page.count("const codecs = rends.map((r) => r.codec);"), 1)
        # cache key = codec|description|container.kind; unknown -> true (never hide on a guess)
        self.assertEqual(page.count('const key = String(r.codec || "") + "|" + String(r.description || "") + "|" + String(r.container?.kind || "");'), 1)
        self.assertEqual(page.count(".catch(() => { decodeCache.set(key, true); return true; });"), 1)

    def test_probe_lives_in_the_watch_module(self):
        page = self.page
        i = page.index('import { Net, Signals, Video as WatchVideo } from "https://esm.sh/@moq/watch";')
        j = page.index("function decodeSupported(rend) {")
        k = page.index('from "https://esm.sh/@moq/publish"')
        self.assertLess(i, j)
        self.assertLess(j, k)

    def test_vendored_probe_still_exists(self):
        # watch.mjs exports `Video` with Decoder; the player's Decoder carries `static supported`
        watch = read(os.path.join(HERE, "assets", "vendor", "esm", "@moq", "watch@0.6.2", "es2022", "watch.mjs"))
        self.assertIn(" as Video}", watch)
        player = read(os.path.join(HERE, "assets", "vendor", "esm", "@moq", "watch@0.6.2", "es2022", "player-DqpNnBDT.mjs"))
        self.assertIn("static supported=", player)
        self.assertIn('t.codec.startsWith("avc3.")', player)


class MaxAge(unittest.TestCase):
    def test_page_broadcasts_match_the_native_pairs(self):
        page = read(PAGE)
        self.assertEqual(page.count("maxAge: 5000,"), 1)                                   # rebuildRtspMoq (RTSP slots + grid composite)
        self.assertEqual(page.count("publish.broadcast?.in?.maxAge?.set?.(5000)"), 1)      # <moq-publish> graphs
        self.assertIn('"import", "--max-age", "5s"', read(RTSP))                         # the native pairs (kastr_rtsp.py)
        # maxAge sits inside rebuildRtspMoq's Broadcast options, next to its name
        i = page.index("name: Net.Path.from(chanPath(ensureHang(slot.entry.name))),")
        j = page.index("maxAge: 5000,")
        self.assertLess(i, j)
        self.assertLess(j - i, 300)
        # the element set sits between createElement("moq-publish") and its url attribute: no track exists yet, none is re-created
        i = page.index("publish.broadcast?.in?.maxAge?.set?.(5000)")
        self.assertLess(page.index('const publish = document.createElement("moq-publish");'), i)
        self.assertLess(i, page.index('\n    publish.setAttribute("url", authUrl(urlInput.value.trim()));'))

    def test_vendored_default_is_still_thirty_seconds(self):
        # the reason P12a exists; if the library changes this, revisit the page value
        c = read(CONTAINER)
        self.assertIn("k.Milli(3e4)", c)
        self.assertRegex(c, r"maxAge:[a-z]\.maxAge\?\?")   # 0.21.17: hang 0.5.2 renamed the minified local

    def test_publish_element_builds_its_broadcast_in_the_constructor(self):
        # the amended P12a position rests on this: connectedCallback only enables the connection
        el = read(os.path.join(HERE, "assets", "vendor", "esm", "@moq", "publish@0.5.2", "es2022", "element.mjs"))
        self.assertIn("this.broadcast=new ", el)
        self.assertIn("connectedCallback(){this.#a.set(!0)}", el)
        enc = read(os.path.join(HERE, "assets", "vendor", "esm", "@moq", "publish@0.5.2", "es2022", "encoder-CjcsUSCu.mjs"))
        self.assertIn("maxAge:j(t?.maxAge)", enc)
        self.assertIn("o.get(this.in.maxAge)", enc)


if __name__ == "__main__":
    unittest.main()
