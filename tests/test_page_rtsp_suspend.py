"""0.21.16: the own-RTSP switch in the pages (moq-watch-lite.html module 2 + View menu, relay.html card + hub column).

Run: python -m unittest discover -s tests   (build.py's exact invocation, before every build)

The switch's page side is inline JS in two large pages, so -- like tests/test_grid_keep_rule.py -- this guards the exact
text a merge could drop: the state and setter, every gate that keeps a switched-off box quiet (syncNative never
unpublishes, no announce, no draw, no monitor ladder, no eviction, no viewer-stall rebuild), the mirrors that keep the
page in step with the server, and the Relay page's card + spokes column. No network, no processes.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return f.read()


def body_of(text, head, lines=3):
    """The `lines` lines that follow the line containing `head` (which must be unique)."""
    rows = text.split("\n")
    idx = [i for i, r in enumerate(rows) if head in r]
    assert len(idx) == 1, (head, len(idx))
    return "\n".join(rows[idx[0] + 1:idx[0] + 1 + lines])


class WatchPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read("moq-watch-lite.html")

    def once(self, s):
        self.assertEqual(self.text.count(s), 1, "expected exactly once: %r" % s)

    def test_state_setter_and_controls(self):
        self.once("let rtspSuspended = false, rtspSwitchAt = 0;")
        self.once("function setRtspSuspended(on, opts) {")
        self.once("window.__rtspSuspend = { get: () => rtspSuspended, set: (on) => setRtspSuspended(on) };")
        self.once('id="rtspSuspendSw"')
        self.once('id="viewRtspOff"')
        self.once('nativePost("/api/rtsp/suspend", { suspend: on, who: "page" })')
        # the state is declared before renderSources (which paints the switch) and inside module 2
        decl = self.text.index("let rtspSuspended = false")
        self.assertLess(decl, self.text.index("  function renderSources() {"))
        self.assertGreater(decl, self.text.index("const IS_WEB2 = CLIENT2.class"))
        self.assertIn("if (IS_WEB2) return;", body_of(self.text, "function setRtspSuspended(on, opts) {", 1))

    def test_gates_keep_a_switched_off_box_quiet(self):
        self.assertIn("if (rtspSuspended) return;", body_of(self.text, "  function syncNative(force) {", 1))
        self.assertIn("if (rtspSuspended) return;", body_of(self.text, "  function drawRtspGrid(g) {", 1))
        self.assertIn("if (rtspSuspended) return;", body_of(self.text, "  function gridEvictionTick() {", 1))
        self.assertIn("if (rtspSuspended) return;", body_of(self.text, "  function nudgeFromViewer(fullPath) {", 1))
        self.assertIn("if (rtspSuspended) return;", body_of(self.text, "    if (entry.retryTimer) return;              // already queued", 1))
        self.once("for (const g of ((live && !rtspSuspended) ? gridsSorted() : [])) {")
        self.once("enabled: live && !(slot.canvas && rtspSuspended),")
        self.once("g.moq?.broadcast?.in?.enabled?.set?.(!rtspSuspended);")
        self.once("if (rtspSuspended && nativeRtsp) {")

    def test_mirrors_and_diag(self):
        self.assertEqual(self.text.count("{ fromServer: true, seed: true }"), 2)   # /api/instance + __rtspAdopt
        self.once("Date.now() - rtspSwitchAt > 4000) setRtspSuspended(d.suspended, { fromServer: true });")
        self.once("      rtspSuspended,   // 0.21.16")
        self.assertIn('text: "suspended"', self.text)
        self.once("gateMsg(d.suspended ?")

    def test_new_lines_are_ascii(self):
        bad = [ln for ln in self.text.split("\n") if "0.21.16" in ln and any(ord(c) > 127 for c in ln)]
        self.assertEqual(bad, [], "write non-ASCII glyphs in JS strings as \\uXXXX escapes")

    def test_presence_says_why_the_cameras_left(self):
        # the publisher side: presence + state.json carry rtsp "off" while suspended, re-announced on every flip
        self.once('...(rtspSuspended ? { rtsp: "off" } : {}) };')
        self.once('if (p.rtsp === "off") pubModel.rtsp = "off"; else delete pubModel.rtsp;')
        self.once("if (window.__sinceAnnounce?.joinedAt?.()) { try { window.__sinceAnnounce.set(); } catch {} }")
        # the viewer side: the lobby reader keeps it, roomsChanged applies it, People shows it
        self.once('rtsp: v.rtsp === "off" ? "off" : "", clk:')   # 0.21.22: + clk, rtspPaths
        self.once("      try { rtspOffApply(); } catch {}")
        self.once("function rtspOffApply() {")
        self.once('<div id="rtspOffRows" hidden')
        # module 1 (it reads roomsPres / CHANNEL / statePeer), before module 2 starts
        self.assertLess(self.text.index("function rtspOffApply() {"), self.text.index("const IS_WEB2 = CLIENT2.class"))
        # quiet: info level, no chime, no toast on first sight (only when a known peer's state flips)
        start = self.text.index("function rtspOffApply() {")
        body = self.text[start:self.text.index("function paintRtspOff() {", start)]
        self.assertIn('{ level: "info" }', body)
        self.assertIn("if (prev && prev.off !== s.off) {", body)
        self.assertNotIn("chime", body.lower())
        self.assertNotIn("removeTile", body)          # the tiles leave the normal way (pairs stop, grid announce withdrawn)


class RelayPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read("relay.html")

    def test_card_and_column(self):
        for s in ('id="camerasPanel"', 'id="rtspOn"', "paintCameras(); setInterval(paintCameras, 10000);",
                  'fetch("/api/rtsp/suspend"', "<th>Cameras</th>", '"/api/relay/spokes/rtsp"', "camCell(r)"):
            self.assertGreaterEqual(self.text.count(s), 1, s)
        self.assertEqual(self.text.count('id="camerasPanel"'), 1)
        # the card lives in the module whose LOCAL constant paintArchive uses (the second one)
        self.assertGreater(self.text.index("async function paintCameras()"), self.text.index("paintArchive(); setInterval(paintArchive, 20000);"))

    def test_new_lines_are_ascii(self):
        bad = [ln for ln in self.text.split("\n") if re.search(r"rtsp|camCell|Cameras", ln) and "0.21.16" in ln
               and any(ord(c) > 127 for c in ln)]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
