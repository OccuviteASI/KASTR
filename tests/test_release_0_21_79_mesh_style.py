# -*- coding: utf-8 -*-
"""0.21.79 (Kenton: "I want the mesh map to be more colorful and expressive"): the relay mesh map on the hub's Relay page,
restyled. Each relay has a colour of its own (the hub ASI blue, the standby violet, each spoke a hue from its name, kept
clear of the red / amber that mean trouble), traffic runs along the links as dots one lane each way (a canvas under the
relays, one requestAnimationFrame loop, no DOM writes per frame), relays carry load rings and a glow, health keeps colour
AND pattern AND a mark, both themes have their own tokens, reduced motion stops everything moving, and the elements are
kept from refresh to refresh so values ease instead of being redrawn. Static checks like the other relay.html tests; the
look itself was checked with screenshots against a mock hub (scratchpad v02179/MESH)."""
import os, re, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page():
    with open(os.path.join(HERE, "relay.html"), "rb") as f:
        raw = f.read()
    return raw, raw.decode("utf-8")


def block(s, start, end):
    i = s.index(start)
    return s[i:s.index(end, i)]


def rule(css, selector):
    """The declarations of the rule that starts with exactly this selector."""
    i = css.index(selector + " {")
    return css[i:css.index("}", i)]


def tokens(decl):
    return dict(re.findall(r"(--mesh-[a-z]+):\s*([^;]+);", decl))


class MeshStyle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.s = page()
        cls.css = block(cls.s, "  #linksBox { --mesh-l:", "</style>")
        cls.js = block(cls.s, "const mesh = {", "paintMesh(); setInterval(paintMesh, 5000);")

    def test_crlf_and_no_escapes(self):
        self.assertEqual(self.raw.count(b"\n"), self.raw.count(b"\r\n"))   # relay.html stays CRLF
        self.assertNotIn(chr(92), self.js)                                  # the mesh code is written without escapes

    def test_theme_tokens_both_themes(self):
        dark = tokens(rule(self.css, "  #linksBox"))
        light = tokens(rule(self.css, '  :root[data-theme="light"] #linksBox'))
        used = set(re.findall(r"var\((--mesh-[a-z]+)", self.css + block(self.s, '<div class="meshlegend"', "</div>")))
        self.assertTrue(used, "the map draws with its tokens")
        for t in used:
            self.assertIn(t, dark, t + " is defined for the dark themes")
        for t in ("--mesh-l", "--mesh-c", "--mesh-fl", "--mesh-fc", "--mesh-pl", "--mesh-pc", "--mesh-ml", "--mesh-mc", "--mesh-cl", "--mesh-cc",
                  "--mesh-down", "--mesh-warn", "--mesh-ground", "--mesh-grid", "--mesh-glow", "--mesh-track"):
            self.assertIn(t, light, t + " has its own light-theme value")
            self.assertNotEqual(dark[t], light[t], t + " differs between the themes")
        # a relay's colour is lighter on the dark ground and darker on white (text-grade contrast both ways)
        self.assertGreater(float(dark["--mesh-l"]), float(light["--mesh-l"]))
        self.assertLess(float(dark["--mesh-fl"]), 0.5)
        self.assertGreater(float(light["--mesh-fl"]), 0.85)
        self.assertIn(':root[data-palette="contrast"] #linksBox', self.css)   # the high-contrast palette brightens it
        # the ground follows the palette (surface-2), with a soft grid and glow
        self.assertIn("var(--surface-2", dark["--mesh-ground"])
        self.assertIn("var(--mesh-glow)", rule(self.css, "  .meshwrap"))
        self.assertIn("var(--mesh-grid)", rule(self.css, "  .meshwrap"))
        # the canvas reads the tokens (it cannot use var()) and again on a theme switch
        self.assertIn('getPropertyValue("--mesh-pl")', self.js)
        self.assertIn('attributeFilter: ["data-theme", "data-palette", "style"]', self.js)

    def test_state_is_pattern_and_mark_not_colour_alone(self):
        pats = {}
        for st, colour in (("warn", "var(--mesh-warn)"), ("down", "var(--mesh-down)"), ("off", "var(--mesh-off)"), ("none", "var(--mesh-off)"), ("wait", "var(--mesh-off)")):
            r = rule(self.css, "  .meshwrap .mstat.st-" + st)
            self.assertIn("stroke:" + colour, r, st)
            m = re.search(r"stroke-dasharray:([0-9. ]+);", r)
            self.assertTrue(m, st + " has a dash pattern")
            pats[st] = m.group(1).strip()
        self.assertEqual(len(set(pats.values())), len(pats), pats)   # every state its own pattern
        self.assertIn("animation:meshpulse", rule(self.css, "  .meshwrap .mstat.st-down"))      # down pulses
        self.assertIn("animation:meshshimmer", rule(self.css, "  .meshwrap .mstat.st-warn"))    # slow / flapping shimmers
        # and a mark at the link's middle: ! for slow / flapping, x for down; an up-arrow badge on a relay that needs an update
        self.assertIn('e.badgeT.textContent = o.st === "warn" ? "!" : "×"', self.js)
        self.assertIn('o.badge === "upd" ? "↑"', self.js)
        self.assertIn('badge: n.needsUpdate ? "upd"', self.js)
        # a healthy link's colour is the relays' own; a troubled one fades it so the state colour reads alone
        self.assertIn(".meshwrap .medge.st-warn, .meshwrap .medge.st-down { opacity:.16; }", self.css)
        self.assertIn(".meshwrap .medge.st-off, .meshwrap .medge.st-wait, .meshwrap .medge.st-none { opacity:0; }", self.css)

    def test_relay_colours(self):
        hues = [int(x) for x in re.search(r"const MESH_HUES = \[([0-9, ]+)\];", self.js).group(1).split(",")]
        self.assertGreaterEqual(len(hues), 10)
        self.assertEqual(len(set(hues)), len(hues))
        for h in hues:   # OKLCH: never red (~25) or amber (~75), the hub's blue (237) or the standby's violet (300)
            self.assertFalse(h <= 45 or 55 <= h <= 115 or 225 <= h <= 250 or 290 <= h <= 310 or h >= 350, h)
        for a, b in zip(hues, hues[1:]):   # the next free hue is far from the last
            self.assertGreaterEqual(min(abs(a - b), 360 - abs(a - b)), 30, (a, b))
        self.assertIn('if (s.role === "hub") return 237;', self.js)
        self.assertIn('if (s.role === "standby") return 300;', self.js)
        self.assertIn("mesh.hues = meshHues(d.nodes);", self.s)              # the same colours zoomed and not
        self.assertIn("const MESH_KIND_HUE = { person: 158, box: 322, viewer: 268 };", self.js)
        # a link is a gradient between its two relays' colours; a client is drawn by kind with its own shape
        self.assertIn("e.stops.forEach((s, i) => s.style.setProperty(\"--h\", i < 2 ? o.ha : o.hb));", self.js)
        self.assertIn('{ box: "rect", viewer: "diamond" }[n.c.kind] || "circle"', self.js)

    def test_traffic_and_load(self):
        # one loop: every requestAnimationFrame in the mesh code runs meshFrame
        self.assertEqual(set(re.findall(r"requestAnimationFrame\((\w+)\)", self.js)), {"meshFrame"})
        flow = block(self.js, "  function meshFlow(ts) {", "  function meshTokens() {")
        self.assertNotIn("setAttribute", flow)   # the dots move without touching the DOM ...
        self.assertNotIn(".style", flow)
        self.assertIn("meshPaintFlow();", flow)  # ... on the canvas
        paint = block(self.js, "  function meshPaintFlow() {", "  function meshKick() {")
        self.assertIn("ctx.lineTo", paint)
        # speed, size and spacing from the bitrate; each way its own lane in the sender's colour; an idle link draws no dots
        self.assertIn("L.vt = Math.min(140, 16 + 14 * g)", self.js)
        self.assertIn("on = !!(o.live && f && f.bps > 20000)", self.js)
        self.assertIn('lanes: [{ bps: dir("fwd"), from, hue: from === l.a ? ha : hb }, { bps: dir("back"), from: to, hue: to === l.a ? ha : hb }]', self.js)
        # thicker when busier; a relay's rings fill like meters (in / out, local / links); a busy relay glows
        self.assertIn("Math.min(8, 1.7 * meshLog(bw))", self.js)
        self.assertIn("[[L?.total?.in, L?.local?.in], [L?.total?.out, L?.local?.out]]", self.js)
        self.assertIn("v.glow.style.opacity = L ? (0.1 + 0.8 * f).toFixed(2)", self.js)

    def test_reduced_motion(self):
        rm = self.css[self.css.index("@media (prefers-reduced-motion: reduce) { .meshwrap"):]
        for s in (".meshwrap .mstat", ".meshwrap .mbadge", ".meshlegend *", "animation:none !important", ".meshwrap .marrow.on { display:inline; }"):
            self.assertIn(s, rm, s)
        self.assertIn("if (!els || reduceMotion() || document.hidden) { mesh.flowT = 0; return false; }", self.js)   # the dots stand still
        self.assertIn("if (rm) { L.a = L.on ? 0.95 : 0; L.o = 0; }", self.js)
        self.assertIn("if (!mesh.raf && !reduceMotion() && !document.hidden", self.js)
        self.assertIn("label: live && bw >= (rm ? 20000 : 50000) ? fmtBps(bw)", self.js)   # the rates as labels instead
        # nothing on the map animates every frame for decoration: the health marks are stepped (an SVG repaints whole)
        for name in ("meshshimmer", "meshpulse", "meshflicker"):
            for m in re.finditer(r"animation:[^;]*" + name + r" [0-9.]+s ([a-z(0-9)-]+)", self.css):
                self.assertTrue(m.group(1).startswith("steps("), m.group(0))
        self.assertNotIn("meshspin", self.css)
        self.assertNotIn("meshbreathe", self.css)

    def test_legend(self):
        lg = block(self.s, '<div class="meshlegend" id="meshLegend"', "</div>")
        for s in ("direct link, in its two relays' colours", "hub / standby link (last resort)", "traffic, one lane each way", "slow or flapping", ">down<",
                  "off / not linked (click for why)", "rings = load", "needs update", "person", "box", "web viewer", 'class="zonly"'):
            self.assertIn(s, lg, s)
        self.assertIn('#linksBox.zoomed .meshlegend .zonly { display:inline-flex; }', self.css)   # the client kinds while zoomed
        self.assertIn('$("linksBox").classList.toggle("zoomed", !!(mesh.zoom && d.zoom));', self.js)

    def test_kept_elements_and_what_worked(self):
        # the elements are kept (keyed) from refresh to refresh, so a change eases (CSS transitions) instead of a redraw
        self.assertIn("let e = P.edges.get(id);", self.js)
        self.assertIn("const v = meshNodeGet(P, n.id, \"circle\");", self.js)
        self.assertIn("transition:stroke-width .8s ease, opacity .6s ease;", self.css)
        self.assertIn("transition:stroke-dasharray .9s ease, stroke-dashoffset .9s ease;", self.css)
        # still there: hover tooltips (now edged in the relay's colour), the hovered one survives a refresh, click / drag /
        # Re-arrange / zoom / Escape, the Links table (with each relay's colour)
        for s in ("meshTip(ev, e.tip(), e.hue)", "meshTip(ev, v.tip(), v.hue)", "if (l) t.innerHTML = meshTipHtml(l);", 'e.hit.addEventListener("click"',
                  "mesh.drag = { id: v.id, moved: false", 'id="meshArrange"', "meshZoomIn(dr.id);", 'e.key === "Escape"', "meshDot(l.a) + esc(l.aName"):
            self.assertIn(s, self.s, s)
        # the three layers: links under, the dots' canvas, the relays and hit areas on top (#meshSvg keeps the pointer)
        self.assertIn('mesh.cv = document.createElement("canvas")', self.js)
        self.assertIn('$("meshWrap").insertBefore(mesh.bg, $("meshSvg"));', self.js)
        self.assertIn(".meshwrap #meshSvg { position:relative; z-index:1; }", self.css)



class ZoomedRelayClickGoesBack(unittest.TestCase):
    # 0.21.82 (Kenton: "when you click on that same relay again it should go back a level")
    def test_center_click_zooms_out(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay.html"), encoding="utf-8", newline="") as f:
            p = f.read()
        i = p.index("const meshDrop = () => {")
        body = p[i:p.index("$(\"meshSvg\").addEventListener(\"pointerup\", meshDrop);", i)]
        self.assertIn('if (dr.id === "r:" + mesh.zoom) { meshZoomOut(); return; }', body)
        self.assertLess(body.index("if (dr.moved) { meshRun(0.3); return; }"), body.index('if (dr.id === "r:" + mesh.zoom)'))   # a drag of it never zooms out
        self.assertIn("click it to go back to the full mesh", p)

if __name__ == "__main__":
    unittest.main()
