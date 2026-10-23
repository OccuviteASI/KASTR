"""0.21.83 (part A'): the share pill and the controller's notice during remote control.

Kenton (2026-10-23):
1. "When remote controlling, I am unable to see the red sharing pill at the top, so when I try to click in that space it doesn't
   work to click on the things behind the pill" -- a controller's press / wheel / drag on the pill's area is no longer dropped:
   the pill turns click-through (Windows: WS_EX_TRANSPARENT on the now LAYERED pill; X11: an empty input shape) from just before
   that input until PASS_HOLD_S after the last of it, so it reaches the window behind.
2. "The pill should be smaller also" -- 28 px tall at 96 dpi (was 40), 11 px text, tighter padding, shorter labels; JUST ABOVE a
   shared window when its monitor has room there, else inside its top edge (kastr_overlay.pill_place); the X11 bar 24 px.
3. "... have that as well as stop sharing, to close out the share and control at the same time." -- while controlled the pill
   has Stop control AND Stop sharing (control ends first, then the share).
5. "The pop-up saying it was admin wasn't easy to notice ... and it didn't stay very long." -- the sharer publishes the rect of the
   administrator window under the controller's pointer (st.json admin.r, normalised); the controller's view pins an amber badge
   on it while their pointer is over it, and the banner turns amber; the sharer's pill shows a short note.
6. A faint outline + "their KASTR bar" where the pill sits in the controller's view (st.json bar).

Windows parts are tested WITHOUT any window: pure geometry / flags / routing, the injector with the mock backend, and the
pill rendered into a memory bitmap (never on a screen)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import kastr_overlay as ko  # noqa: E402
import kastr_rc as rc  # noqa: E402

A, B = "alice-aa11", "bob-bb22"
WIN_URL, MON_URL = "screen://window/4242", "screen://monitor/0"
WRECT = {"x": 100, "y": 50, "w": 640, "h": 400}
MRECT = {"x": 0, "y": 0, "w": 1920, "h": 1080}


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeUI:
    """The pill as kastr_rc sees it: show / clear / rect + 0.21.83 passthrough / stop_share."""

    def __init__(self, rect=None, stops=True):
        self.shown, self.cleared, self.bar, self.passes, self.stopped = [], [], rect, [], []
        self.stops = stops

    def show(self, feed, url, mode, label, buttons, on_button, rect_fn=None):
        self.shown.append((feed, mode, label, [k for k, _ in buttons], [t for _, t in buttons]))
        self.on_button = on_button
        return True

    def clear(self, feed):
        self.cleared.append(feed)

    def rect(self, feed):
        return self.bar

    def passthrough(self, feed, on):
        self.passes.append((feed, bool(on)))
        return True

    def stop_share(self, feed):
        self.stopped.append(feed)
        return self.stops


def make(mode="post", bar=None, stops=True, url=WIN_URL, feed=7):
    clock = Clock()
    b = rc.MockBackend(rects={WIN_URL: dict(WRECT), MON_URL: dict(MRECT)})
    b.mode = mode
    share = {7: {"url": WIN_URL, "live": True, "paused": False}, 8: {"url": MON_URL, "live": True, "paused": False}}
    ui = FakeUI(bar, stops)
    r = rc.RemoteControl(backend=b, share_info=lambda fid: share.get(int(fid)), clock=clock, caps=(True, "", "mock"), ui=ui, monitor=False)
    o, c = r.start("abcdefgh1234", B, "Bob", feed, "alpha/%s/alice/w.hang" % A, "#e5533d")
    assert c == 200, o
    return r, b, ui, clock, share


def kinds(b, k):
    return [e for e in b.events if e[0] == k]


def put(r, events):
    return r.inject("abcdefgh1234", B, events)


BAR = {"x": 300, "y": 56, "w": 200, "h": 28}
ON_BAR = ((350 - 100) / 640, (60 - 50) / 400)     # a point on the pill, inside the shared window


# ---- 1. click-through on the pill's area ----------------------------------------------------------------------------------
class ClickThrough(unittest.TestCase):
    def test_a_press_on_the_pill_reaches_the_window_behind(self):
        r, b, ui, clock, _ = make("warp", BAR)
        put(r, [{"t": "d", "b": 0, "x": ON_BAR[0], "y": ON_BAR[1]}])
        self.assertEqual(kinds(b, "button"), [("button", 0, True, 350, 60, "warp")])
        self.assertEqual(ui.passes, [(7, True)])           # click-through BEFORE the warp-click is injected
        self.assertEqual((r.stats["bar"], r.stats["outside"]), (1, 0))

    def test_it_stays_click_through_while_the_button_is_held_and_a_moment_after(self):
        r, b, ui, clock, _ = make("warp", BAR)
        put(r, [{"t": "d", "b": 0, "x": ON_BAR[0], "y": ON_BAR[1]}])
        clock.t += 5
        r.check()                                          # held (a drag): never turned back while the warp holds the button
        self.assertEqual(ui.passes, [(7, True)])
        put(r, [{"t": "m", "x": ON_BAR[0] + 0.01, "y": ON_BAR[1]}, {"t": "u", "b": 0, "x": ON_BAR[0] + 0.01, "y": ON_BAR[1]}])
        r.check()                                          # released just now: still within PASS_HOLD_S
        self.assertEqual(ui.passes, [(7, True)])
        clock.t += rc.PASS_HOLD_S + 0.01
        r.check()
        self.assertEqual(ui.passes, [(7, True), (7, False)])

    def test_a_wheel_on_the_pill_goes_through_too(self):
        r, b, ui, clock, _ = make("warp", BAR)
        put(r, [{"t": "w", "n": 2, "x": ON_BAR[0], "y": ON_BAR[1]}])
        self.assertEqual(kinds(b, "wheel"), [("wheel", 2, False, "warp")])
        self.assertEqual(ui.passes, [(7, True)])

    def test_input_beside_the_pill_leaves_it_alone(self):
        r, b, ui, clock, _ = make("warp", BAR)
        put(r, [{"t": "d", "b": 0, "x": 0.5, "y": 0.8}, {"t": "u", "b": 0, "x": 0.5, "y": 0.8}])
        self.assertEqual((len(kinds(b, "button")), ui.passes), (2, []))

    def test_control_ending_makes_the_pill_clickable_again(self):
        r, b, ui, clock, _ = make("warp", BAR)
        put(r, [{"t": "d", "b": 0, "x": ON_BAR[0], "y": ON_BAR[1]}])
        r.end(None, "bar")
        self.assertEqual(ui.passes, [(7, True), (7, False)])
        self.assertEqual(ui.cleared, [7])

    def test_a_ui_without_passthrough_still_injects(self):
        class OldUI(FakeUI):
            passthrough = None
        clock = Clock()
        b = rc.MockBackend(rects={WIN_URL: dict(WRECT)})
        ui = OldUI(BAR)
        r = rc.RemoteControl(backend=b, share_info=lambda fid: {"url": WIN_URL, "live": True, "paused": False}, clock=clock,
                             caps=(True, "", "mock"), ui=ui, monitor=False)
        r.start("abcdefgh1234", B, "Bob", 7, "alpha/%s/alice/w.hang" % A)
        put(r, [{"t": "d", "b": 0, "x": ON_BAR[0], "y": ON_BAR[1]}])
        self.assertEqual(len(kinds(b, "button")), 1)

    def test_the_drop_is_gone_from_the_source(self):
        src = read("kastr_rc.py")
        self.assertNotIn("KASTR's own bar is not the controller's to click", src)
        self.assertIn("self._bar_pass(g[\"feed\"])", src)

    def test_exstyle_flag(self):
        ex = ko.PILL_EX
        self.assertEqual(ex & 0x80000, 0x80000)            # layered: WS_EX_TRANSPARENT then makes it click-through
        self.assertEqual(ex & ko.PASS_BIT, 0)               # clickable by default
        on = ko.passthrough_exstyle(ex, True)
        self.assertEqual(on, ex | 0x20)
        self.assertEqual(ko.passthrough_exstyle(on, False), ex)
        self.assertEqual(ko.passthrough_exstyle(ex, False), ex)

    def test_overlay_api_without_a_window(self):
        ov = ko.ShareOverlay()
        self.assertFalse(ov.set_passthrough(True))          # no pill up: nothing to do
        self.assertFalse(ov.passthrough)
        seen = []
        ov.on_stop = lambda: seen.append(1)
        self.assertTrue(ov.request_stop())
        self.assertFalse(ov.request_stop())                 # once per share
        for _ in range(50):
            if seen:
                break
            import time
            time.sleep(0.02)
        self.assertEqual(seen, [1])

    def test_kastr_screen_helpers(self):
        import kastr_screen
        self.assertFalse(kastr_screen.overlay_passthrough(999999, True))
        self.assertFalse(kastr_screen.overlay_request_stop(999999))
        src = read("kastr_screen.py")
        self.assertIn("return bool(ov.set_passthrough(on)) if ov is not None else False", src)

    def test_x11_bar_passthrough_source(self):
        src = read("kastr_x11.py")
        self.assertIn("ext.XShapeCombineRectangles(d.dpy, win, 2, 0, 0, None, 0, 0, 0)", src)
        self.assertIn("ext.XShapeCombineMask(d.dpy, win, 2, 0, 0, 0, 0)", src)
        self.assertIn("elif t == BUTTON_PRESS and not self._pass_now:", src)
        import kastr_x11
        bar = kastr_x11.Bar(lambda: None, lambda k: None)
        self.assertFalse(bar.passthrough(True))             # not started: nothing to do
        self.assertEqual(bar.H, 24)


# ---- 2. a smaller pill, above the window when there is room ---------------------------------------------------------------
class Pill(unittest.TestCase):
    def test_metrics_at_96_and_144_dpi(self):
        m = ko.pill_metrics(96)
        self.assertEqual((m["h"], m["font"], m["btn_h"]), (28, 11, 20))
        m = ko.pill_metrics(144)
        self.assertEqual((m["h"], m["font"], m["btn_h"]), (42, 16, 30))

    def test_layout(self):
        lay = ko.pill_layout(100, [60, 70], 96)
        self.assertEqual(lay["H"], 28)
        (a0, at, a1, ab), (b0, bt, b1, bb) = lay["btns"]
        self.assertEqual((at, ab, bt, bb), (4, 24, 4, 24))   # 20 px buttons, centred
        self.assertEqual((a1 - a0, b1 - b0), (60 + 18, 70 + 18))
        self.assertEqual(b0 - a1, 5)
        self.assertEqual(lay["W"] - b1, 4)
        self.assertEqual(lay["text"][0], 10 + 6 + 6)
        old_h = 40                                           # 0.21.79-0.21.82
        self.assertLess(lay["H"], old_h)

    def test_placed_above_a_window_when_the_monitor_has_room(self):
        work = (0, 0, 1920, 1040)
        x, y, where = ko.pill_place((400, 300, 1200, 900), 4, (220, 28), work, 96, "window")
        self.assertEqual((x, y, where), (800 - 110, 300 - 28 - 4, "above"))

    def test_inside_a_window_at_the_top_of_the_screen(self):
        work = (0, 0, 1920, 1040)
        x, y, where = ko.pill_place((400, 10, 1200, 900), 4, (220, 28), work, 96, "window")
        self.assertEqual((y, where), (10 + 4 + 4, "inside"))

    def test_inside_a_screen_share(self):
        work = (0, 0, 1920, 1040)
        x, y, where = ko.pill_place((0, 0, 1920, 1080), 4, (220, 28), work, 96, "monitor")
        self.assertEqual((x, y, where), (960 - 110, 8, "inside"))

    def test_drag_offset_kept_on_the_work_area(self):
        work = (0, 0, 1920, 1040)
        x, y, _w = ko.pill_place((400, 300, 1200, 900), 4, (220, 28), work, 96, "window", drag=(5000, -5000))
        self.assertEqual((x, y), (1920 - 220, 0))

    def test_shorter_labels(self):
        self.assertEqual(ko.LABELS, {"window": "Sharing a window", "screen": "Sharing your screen", "tab": "Sharing a tab"})
        self.assertEqual(rc.bar_label("Bob"), "Bob has control (Ctrl+Alt+Space)")
        self.assertTrue(rc.bar_label("Bob", True).startswith("Bob has control "))
        self.assertTrue(rc.bar_label("Bob", True).endswith("admin window blocks clicks"))

    @unittest.skipUnless(ko.AVAILABLE, "Windows GDI")
    def test_rendered_offscreen(self):
        W, H, raw, btns = ko.render_pill("control", rc.bar_label("Bob"), rc.CTL_BUTTONS, "window", 96)
        self.assertEqual(H, 28)
        self.assertEqual(len(raw), W * H * 4)
        self.assertEqual([k for k, _ in btns], ["stop", "share-stop"])
        W2, H2, _raw, b2 = ko.render_pill("share", None, None, "window", 96)
        self.assertEqual((H2, [k for k, _ in b2]), (28, ["share-stop"]))

    def test_source_uses_the_pure_helpers(self):
        src = read("kastr_overlay.py")
        self.assertIn("dx, dy, _w0 = pill_place(outer, t, (w, h), work, self._bar_dpi, kind)", src)
        self.assertIn("lay = pill_layout(label_w, tws, dpi)", src)
        self.assertIn("BAR_EX = PILL_EX", src)
        self.assertIn("SetLayeredWindowAttributes(h, 0, 255, LWA_ALPHA)   # 0.21.83: the pill is layered too (fully opaque)", src)
        self.assertIn("if k and not injected:                  # 0.21.79: the controller cannot press KASTR's own buttons", src)


# ---- 3. Stop control + Stop sharing --------------------------------------------------------------------------------------
class StopBoth(unittest.TestCase):
    def test_both_buttons_while_controlled(self):
        r, b, ui, clock, _ = make()
        self.assertEqual(ui.shown[-1][1:], ("control", "Bob has control (Ctrl+Alt+Space)", ["stop", "share-stop"], ["Stop control", "Stop sharing"]))

    def test_stop_control_keeps_the_share(self):
        r, b, ui, clock, _ = make()
        ui.on_button("stop")
        self.assertEqual((r.status()["ended"], ui.stopped), ("bar", []))

    def test_stop_sharing_ends_control_then_the_share(self):
        r, b, ui, clock, _ = make()
        order = []
        ui.clear = lambda feed: order.append(("clear", feed, r.grant is None))
        ui.stop_share = lambda feed: (order.append(("stop", feed, r.grant is None)), True)[1]
        put(r, [{"t": "k", "c": "ShiftLeft", "d": 1}])     # something held: let go first
        ui.on_button("share-stop")
        self.assertEqual(order, [("clear", 7, True), ("stop", 7, True)])
        self.assertEqual(r.status()["ended"], "share")
        self.assertIn(("key", "ShiftLeft", False, "send"), b.events)

    def test_stop_sharing_falls_back_to_share_stop(self):   # X11: the bar has no share of its own to stop
        r, b, ui, clock, _ = make(stops=False)
        seen = []
        r.share_stop = lambda feed: seen.append(feed)
        ui.on_button("share-stop")
        self.assertEqual((ui.stopped, seen), ([7], [7]))

    def test_bridge_stop(self):
        class Bridge:
            removed = []

            def remove(self, fid):
                self.removed.append(fid)
        br = Bridge()
        rc.bridge_stop(br)("12")
        self.assertEqual(br.removed, [12])
        self.assertIsNone(rc.bridge_stop(None))
        r = rc.RemoteControl(caps=(True, "", "mock"), ui=FakeUI(), monitor=False)
        self.assertIs(rc._wire(r, br), r)
        self.assertIsNotNone(r.share_stop)
        self.assertEqual(read("kastr_rc.py").count("rc = _wire(get(bridge_info(bridge), log, bridge_mode(bridge)), bridge)"), 2)

    def test_overlay_routes_stop_sharing_through_kastr_rc_while_controlled(self):
        self.assertEqual(ko.pill_route("share-stop", "share", False), "stop")
        self.assertEqual(ko.pill_route("share-stop", "control", True), "button")   # control ends first (kastr_rc.stop_both)
        self.assertEqual(ko.pill_route("share-stop", "control", False), "stop")
        self.assertEqual(ko.pill_route("stop", "control", True), "button")
        self.assertEqual(ko.pill_route("allow", "prompt", True), "button")
        self.assertIsNone(ko.pill_route("stop", "control", False))
        self.assertEqual(ko.pill_button_style("share-stop", True), "ghost")   # grey on the red control pill
        self.assertEqual(ko.pill_button_style("share-stop", False), "btn")
        self.assertEqual(ko.pill_button_style("stop", True), "white")

    def test_x11_bar_draws_both(self):
        import kastr_x11
        bar = kastr_x11.Bar(lambda: None, lambda k: None)
        bar.set(rc.bar_label("Bob"), rc.CTL_BUTTONS)
        W, hits = bar._layout()
        self.assertEqual([h[0] for h in hits], ["stop", "share-stop"])
        self.assertTrue(all(h[3] == 3 and h[5] == 18 for h in hits))
        self.assertLess(W, 7 * len(bar.label) + 2 * 120)


# ---- 5 / 6. the controller's notice on an administrator window; where the pill sits ----------------------------------------
class AdminNotice(unittest.TestCase):
    ADMIN = {"x": 300, "y": 150, "w": 200, "h": 100}       # inside WRECT (100, 50, 640 x 400)

    def test_norm_rect(self):
        self.assertEqual(rc.norm_rect(self.ADMIN, WRECT), [0.3125, 0.25, 0.625, 0.5])
        self.assertEqual(rc.norm_rect({"x": 0, "y": 0, "w": 200, "h": 100}, WRECT), [0.0, 0.0, 0.1562, 0.125])   # clipped
        self.assertIsNone(rc.norm_rect({"x": 900, "y": 0, "w": 10, "h": 10}, WRECT))
        self.assertIsNone(rc.norm_rect(None, WRECT))

    def test_published_while_the_pointer_is_over_it(self):
        r, b, ui, clock, _ = make()
        b.admin = dict(self.ADMIN)
        st, _c = put(r, [{"t": "m", "x": 0.4, "y": 0.4}])
        self.assertEqual(st["admin"], {"r": [0.3125, 0.25, 0.625, 0.5], "why": "elevated"})
        b.admin = None
        clock.t += 0.5
        st, _c = put(r, [{"t": "m", "x": 0.9, "y": 0.9}])
        self.assertIsNotNone(st["admin"])                    # kept ADMIN_KEEP_S (no flicker on a quick pass)
        clock.t += rc.ADMIN_KEEP_S + 0.1
        st, _c = put(r, [{"t": "m", "x": 0.91, "y": 0.9}])
        self.assertIsNone(st["admin"])

    def test_checks_are_throttled(self):
        r, b, ui, clock, _ = make()
        calls = []
        b.admin_rect = lambda url, px, py: calls.append((px, py))
        put(r, [{"t": "m", "x": 0.1 + i / 100, "y": 0.5} for i in range(20)])
        self.assertEqual(len(calls), 1)
        clock.t += 1.0 / rc.ADMIN_HZ + 0.01
        put(r, [{"t": "m", "x": 0.5, "y": 0.5}])
        self.assertEqual(len(calls), 2)

    def test_a_blocked_click_pins_it_and_the_sharer_pill_notes_it(self):
        r, b, ui, clock, _ = make()
        b.blocked_why = "elevated"
        b.admin = dict(self.ADMIN)
        st, _c = put(r, [{"t": "d", "b": 0, "x": 0.4, "y": 0.4}])
        self.assertEqual((st["blocked"], st["admin"]["r"]), ("elevated", [0.3125, 0.25, 0.625, 0.5]))
        self.assertEqual(kinds(b, "button"), [])             # Windows blocks it: nothing injected (and nothing else tried)
        r.check()
        self.assertEqual(ui.shown[-1][2], rc.bar_label("Bob", True))
        b.admin = None
        clock.t += rc.ADMIN_NOTE_S + 0.1
        r.check()
        self.assertEqual(ui.shown[-1][2], rc.bar_label("Bob"))

    def test_the_pill_rect_goes_to_the_controller(self):
        r, b, ui, clock, _ = make(bar=dict(BAR))
        st = r.status("abcdefgh1234")
        self.assertEqual(st["bar"], [0.3125, 0.015, 0.625, 0.085])
        self.assertNotIn("barCap", st)
        ui.bar = {"x": 300, "y": 10, "w": 200, "h": 28}      # above the window: not in the picture
        self.assertIsNone(r.status("abcdefgh1234")["bar"])

    def test_backends(self):
        self.assertIsNone(rc.MockBackend().admin_rect(WIN_URL, 1, 1))
        self.assertTrue(hasattr(rc.WinBackend, "admin_rect"))
        self.assertTrue(hasattr(rc.X11Backend, "admin_rect"))
        src = read("kastr_rc.py")
        self.assertIn('ok = dwm.DwmGetWindowAttribute(ctypes.c_void_p(h), 9, ctypes.byref(r), ctypes.sizeof(r)) == 0   # DWMWA_EXTENDED_FRAME_BOUNDS', src)

    def test_page(self):
        p = read("moq-watch-lite.html")
        self.assertIn("admin: d.admin || null, bar: d.bar || null, barCap: d.barCap ? 1 : 0 };", p)
        self.assertIn("const j = JSON.stringify([st.paused, st.blocked, st.clip?.n, st.admin, st.bar]);", p)
        self.assertEqual(p.count("function rcAdminPaint(c) {"), 1)
        self.assertIn("c.lastP = p; rcAdminPaint(c);", p)
        self.assertIn('const box = ar ? rcRectBox(t, ar) : null, over = !!box && rcInR(c.lastP, ar);', p)
        self.assertIn('el.classList.toggle("amber", !st.paused && (st.blocked === "elevated" || !!c.overAdmin));', p)
        self.assertIn('rcShape(c, "rcbarghost", "<span>their KASTR bar</span>")', p)
        self.assertIn("#kRcCtl.amber {", p)
        self.assertIn('.pane .rcadmin[hidden], .pane .rcadmbox[hidden], .pane .rcbarghost[hidden] { display:none; }', p)
        B = chr(92)
        self.assertIn('"Admin window ' + B + 'u2014 clicks and typing are blocked by Windows. Minimize, move, resize and close need KASTR to run as administrator on " + c.name + "' + B + 'u2019s computer."', p)


if __name__ == "__main__":
    unittest.main()
