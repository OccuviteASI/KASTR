# -*- coding: utf-8 -*-
"""v0.21.80 TWO POINTERS + FASTER REMOTE CONTROL. Kenton (2026-10-22): "I would like to have a mouse with a name of the person
controlling it, rather than them controlling my own mouse. Allow both mice at the same time and show my mouse with my name for
the viewers. Instead of my mouse taking over their remote control." -- and "I would like remote control to be faster if
possible. There is a bit of delay."

What is proven here (NO real input anywhere, no window created, no screen captured):
  * the controller's pointer window: its styles (layered, click-through, topmost, tool, no-activate), the capture exclusion,
    the colour key, the arrow + name tag geometry -- from the spec PointerOverlay creates it with; the X11 twin's shape;
  * the Windows message construction for a click / wheel / key at the controller's pointer (PostMessage: message ids, client
    lParam, MK_ flags, XBUTTON words, double-clicks, WM_KEYDOWN lParam bits) -- PostMessage itself is never called;
  * the post-vs-warp decision per window class / framework host / DPI; the warp's save + restore (the sharer's own moves kept)
    and the hook's hold-back of a physical press during a warp; a warp never starts while the sharer holds a button (queued
    until their release, dropped after WARP_WAIT_S), and a physical press during a controller's warp-drag ends it;
  * local input no longer pauses remote input;
  * the pointer samples (normalised, on/off the surface, nothing while still) and the loopback WebSocket (RFC 6455 handshake,
    masked frames, input in, pointers out at most PTR_HZ a second) end to end over a socket pair;
  * the viewers' pointer mapping (letterbox / crop / zoom) and the video-delay alignment, mirrored from the page;
  * the capture without the real cursor and the low-latency encode ONLY while someone controls the share (Bridge.rc_mode,
    Publisher args, the encoder options' test-encode gate) -- opt-in (KASTR_RC_SHARE_MODE=1): its restart froze the
    controller's picture 14 s+ in the lab, so by default the sharer's cursor stays in the picture and viewers draw only
    their NAME beside it -- and the controller's own player budget / priority only while controlling."""
import json
import os
import socket
import sys
import threading
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_rc as rc  # noqa: E402
import kastr_overlay as ko  # noqa: E402
import kastr_x11 as x11  # noqa: E402

B = "bob-bb22"
WIN_URL, MON_URL = "screen://window/4242", "screen://monitor/1"
WRECT = {"x": 100, "y": 50, "w": 640, "h": 400}


class _P(str):
    def __repr__(self):
        return '<page>'


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return _P(f.read())


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeUI:
    def __init__(self):
        self.shown, self.cleared = [], []

    def show(self, feed, url, mode, label, buttons, on_button, rect_fn=None):
        self.shown.append((feed, mode, label))
        return True

    def clear(self, feed):
        self.cleared.append(feed)

    def rect(self, feed):
        return None


def make(mode="post", share_mode=None):
    clock = Clock()
    b = rc.MockBackend(rects={WIN_URL: dict(WRECT)})
    b.mode = mode
    share = {7: {"url": WIN_URL, "live": True, "paused": False}}
    r = rc.RemoteControl(backend=b, share_info=lambda fid: share.get(int(fid)), clock=clock, caps=(True, "", "mock"),
                         ui=FakeUI(), monitor=False, share_mode=share_mode)
    o, c = r.start("abcdefgh1234", B, "Bob", 7, "alpha/alice-aa11/alice/w.hang", "#e5533d")
    assert c == 200, o
    return r, b, clock


def kinds(b, k):
    return [e for e in b.events if e[0] == k]


# ---- the controller's pointer window ------------------------------------------------------------------------------------
class PointerWindow(unittest.TestCase):
    def test_styles_and_capture_exclusion(self):
        s = ko.pointer_spec()
        self.assertEqual(s["ex"], 0x80000 | 0x20 | 0x8 | 0x80 | 0x08000000)   # LAYERED | TRANSPARENT | TOPMOST | TOOLWINDOW | NOACTIVATE
        self.assertEqual(s["style"], 0x80000000)                              # WS_POPUP
        self.assertEqual(s["affinity"], 0x11)                                 # WDA_EXCLUDEFROMCAPTURE
        self.assertEqual((s["lwa"], s["key"]), (0x1, 0xFF00FF))               # LWA_COLORKEY, magenta
        src = read("kastr_overlay.py")
        for anchor in ('h = CreateWindowExW(spec["ex"], CLASS_NAME, "KASTR pointer", spec["style"]',
                       'SetLayeredWindowAttributes(h, spec["key"], 0, spec["lwa"])',
                       'self.affinity_ok = bool(SetWindowDisplayAffinity(h, spec["affinity"]))'):
            self.assertEqual(src.count(anchor), 1, anchor)
        # click-through and never activated, even if a click reached it
        i = src.index("class PointerOverlay:")
        body = src[i:src.index("# ---------------------------------------------------------------- demo")]
        self.assertIn("if msg == WM_NCHITTEST:\r\n            return HTTRANSPARENT", body)
        self.assertIn("if msg == WM_MOUSEACTIVATE:\r\n            return MA_NOACTIVATE", body)
        self.assertIn("SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOOWNERZORDER", body)

    def test_geometry_and_colours(self):
        g = ko.pointer_geometry("Bob Control", 96)
        self.assertEqual(g["hot"], (1, 1))
        self.assertEqual(g["arrow"][0], (1, 1))                    # the tip is the hotspot
        tx, ty, tw, th = g["tag"]
        self.assertTrue(tx > 1 and ty > 15 and tw >= 7 * len("Bob Control") and g["w"] >= tx + tw and g["h"] >= ty + th)
        g2 = ko.pointer_geometry("Bob Control", 144)
        self.assertGreater(g2["w"], g["w"])
        self.assertGreater(ko.pointer_geometry("A much longer name here", 96)["w"], g["w"])
        self.assertEqual(ko.hex_colorref("#e5533d"), 0x3D53E5)     # COLORREF is 0x00BBGGRR
        self.assertEqual(ko.hex_colorref("nope"), 0xDA9F00)
        self.assertNotEqual(ko.hex_colorref("#ff00ff"), ko.POINTER_KEY)   # never the key colour
        self.assertEqual(ko.ink_colorref(ko.hex_colorref("#ffffff")), 0)
        self.assertEqual(ko.ink_colorref(ko.hex_colorref("#0f2235")), 0xFFFFFF)

    def test_not_on_this_platform_without_windows(self):
        if not ko.AVAILABLE:
            self.assertFalse(ko.PointerOverlay("Bob").start())

    def test_x11_twin(self):
        self.assertEqual(x11.ARROW, ko.POINTER_ARROW)
        spans = x11.polygon_spans(x11.ARROW)
        ys = sorted({y for y, _, _ in spans})
        self.assertEqual((ys[0], ys[-1]), (0, 22))
        for y, l, r in spans:
            self.assertTrue(0 <= l < r <= 15, (y, l, r))
        self.assertEqual([s for s in spans if s[0] == 10][0][1], 0)   # the left edge is the shaft
        W, H, (tx, ty, tw, th) = x11.pointer_layout("Bob Control")
        self.assertTrue(W >= tx + tw and H >= ty + th and ty > 15)
        self.assertEqual((x11.ink_for(0xFFFFFF), x11.ink_for(0x0F2235)), (0, 0xFFFFFF))
        src = read("kastr_x11.py")
        self.assertIn("ext.XShapeCombineRectangles(d.dpy, win, 2, 0, 0, None, 0, 0, 0)          # ShapeInput: nothing -- clicks fall through", src)
        self.assertIn("sa.override_redirect = 1", src[src.index("class PointerWin"):])
        # a window share: the arrow is the shared window's own child (x11grab -window_id captures it as drawn, never as a hole)
        self.assertIn("win = x.XCreateWindow(d.dpy, parent, -100, -100, W, H", src)
        self.assertIn('parent=s[1] if s and s[0] != "monitor" else None)', read("kastr_rc.py"))
        self.assertIn('title.startswith(("KASTR control", "KASTR pointer"))', src)   # never offered as a window to share


# ---- Windows messages at the controller's pointer (constructed, never posted) -------------------------------------------
class WinMessages(unittest.TestCase):
    def test_lparam(self):
        self.assertEqual(rc.make_lparam(10, 20), (20 << 16) | 10)
        self.assertEqual(rc.make_lparam(-5, -1), 0xFFFFFFFB)     # signed 16-bit halves
        self.assertEqual(rc.make_lparam(70000, 3), (3 << 16) | (70000 & 0xFFFF))

    def test_buttons(self):
        lp = rc.make_lparam(30, 40)
        self.assertEqual(rc.win_post_button(0, True, 30, 40, set()), [(0x200, 0, lp), (0x201, 0x1, lp)])   # move first, then the press
        self.assertEqual(rc.win_post_button(0, False, 30, 40, {0}), [(0x202, 0, lp)])                     # its own button is not in a release
        self.assertEqual(rc.win_post_button(2, True, 30, 40, {0})[1], (0x204, 0x1 | 0x2, lp))              # right while left is held
        self.assertEqual(rc.win_post_button(1, True, 30, 40, set())[1], (0x207, 0x10, lp))                 # middle
        self.assertEqual(rc.win_post_button(3, True, 30, 40, set())[1], (0x20B, (1 << 16) | 0x20, lp))     # XBUTTON1 in the high word
        self.assertEqual(rc.win_post_button(4, False, 30, 40, {4})[0], (0x20C, 2 << 16, lp))               # XBUTTON2 release
        self.assertEqual(rc.win_post_button(0, True, 30, 40, set(), ("shift", "ctrl"))[1], (0x201, 0x1 | 0x4 | 0x8, lp))
        self.assertEqual(rc.win_post_button(0, True, 30, 40, set(), dbl=True)[1][0], 0x203)                # WM_LBUTTONDBLCLK
        self.assertEqual(rc.win_post_move(5, 6, {0}), (0x200, 0x1, rc.make_lparam(5, 6)))

    def test_wheel_is_screen_coordinates_and_signed(self):
        m, wp, lp = rc.win_post_wheel(1, False, 1500, -20)
        self.assertEqual((m, wp >> 16, wp & 0xFFFF, lp), (0x20A, (-120) & 0xFFFF, 0, rc.make_lparam(1500, -20)))   # down = toward the user
        m, wp, lp = rc.win_post_wheel(2, True, 0, 0, {0})
        self.assertEqual((m, wp >> 16, wp & 0xFFFF), (0x20E, 240, 0x1))

    def test_key_lparam(self):
        self.assertEqual(rc.win_key_lparam(0x1E, 0, True), 0x001E0001)
        self.assertEqual(rc.win_key_lparam(0x1E, 0, False), 0x001E0001 | 0xC0000000)   # previous state + transition
        self.assertEqual(rc.win_key_lparam(0x4B, 1, True), 0x014B0001)                   # extended (an arrow key)

    def test_double_click(self):
        prev = (10.0, 0, 77, 30, 40)
        self.assertTrue(rc.is_dblclick(prev, 10.3, 0, 77, 32, 41))
        self.assertFalse(rc.is_dblclick(prev, 10.6, 0, 77, 30, 40))       # too late
        self.assertFalse(rc.is_dblclick(prev, 10.1, 2, 77, 30, 40))       # another button
        self.assertFalse(rc.is_dblclick(prev, 10.1, 0, 78, 30, 40))       # another window
        self.assertFalse(rc.is_dblclick(prev, 10.1, 0, 77, 40, 40))       # moved
        self.assertFalse(rc.is_dblclick(None, 10.1, 0, 77, 30, 40))

    def test_post_or_warp(self):
        self.assertEqual(rc.click_plan("Edit", "Notepad", 2, 96, 96), ("post", ""))
        self.assertEqual(rc.click_plan("Button", "#32770", 0, 96, 96), ("post", ""))              # unaware but 100 %: same pixels
        self.assertEqual(rc.click_plan("Edit", "#32770", 0, 96, 144), ("warp", "dpi"))            # DPI-virtualised: client coords scaled
        self.assertEqual(rc.click_plan("Edit", "#32770", 1, 144, 144), ("post", ""))              # system-aware at the monitor's DPI
        self.assertEqual(rc.click_plan("WindowsForms10.BUTTON.app.0.141b42a_r6_ad1", "WindowsForms10.Window.8.app.0", 2, 96, 96)[0], "post")
        self.assertEqual(rc.click_plan("AfxWnd140u", "AfxFrameOrView140u", 2, 96, 96)[0], "post")
        for cls in ("Chrome_RenderWidgetHostHWND", "Chrome_WidgetWin_1", "MozillaWindowClass", "HwndWrapper[App;;1]",
                    "Windows.UI.Core.CoreWindow", "DirectUIHWND", "Qt5152QWindowIcon", "SDL_app", "UnityWndClass", "#32768",
                    "ConsoleWindowClass", "_WwG", "SomethingUnknown", ""):
            self.assertEqual(rc.click_plan(cls, "Whatever", 2, 96, 96)[0], "warp", cls)
        self.assertEqual(rc.click_plan("Edit", "Chrome_WidgetWin_1", 2, 96, 96), ("warp", "host"))   # a classic child of a browser host

    def test_hook_button_map(self):
        self.assertEqual([rc.ll_button(m, 0) for m in (0x201, 0x202, 0x204, 0x205, 0x207, 0x208)],
                         [("down", 0), ("up", 0), ("down", 2), ("up", 2), ("down", 1), ("up", 1)])
        self.assertEqual(rc.ll_button(0x20B, 1 << 16), ("down", 3))
        self.assertEqual(rc.ll_button(0x20C, 2 << 16), ("up", 4))
        self.assertIsNone(rc.ll_button(0x200, 0))        # a move
        self.assertIsNone(rc.ll_button(0x20A, 0))        # the wheel
        self.assertFalse(rc.ll_mouse_physical(0, rc.REPLAY_MAGIC))   # a replayed sharer click is not reported twice
        src = read("kastr_rc.py")
        self.assertIn("swallow = self.warp is not None and self.warp.physical(*hit)   # recorded BEFORE the report runs", src)

    def test_nothing_injects_but_the_backends(self):
        src = read("kastr_rc.py")
        self.assertEqual(src.count(".SendInput("), 1)
        self.assertEqual(src.count(".PostMessageW("), 1)   # WinBackend._post only
        for banned in ("keybd_event", "mouse_event(", "SetCursorPos", "SendMessage"):
            self.assertNotIn(banned, src)


# ---- the warp: save / restore, the sharer's drag ------------------------------------------------------------------------
class Warp(unittest.TestCase):
    def test_restore_point_keeps_the_sharers_own_moves(self):
        vs = (0, 0, 1920, 1080)
        self.assertEqual(rc.restore_point((500, 500), (100, 100), (100, 100), vs), (500, 500))
        self.assertEqual(rc.restore_point((500, 500), (100, 100), (112, 95), vs), (512, 495))
        self.assertEqual(rc.restore_point((5, 5), (100, 100), (50, 50), vs), (0, 0))          # kept on the desktop
        self.assertEqual(rc.restore_point((-100, 10), (0, 0), (0, 0), (-1920, 0, 3840, 1080)), (-100, 10))
        self.assertEqual(rc.restore_point((7, 8), (1, 1), None, vs), (7, 8))

    def test_warp_state_holds_back_a_physical_press(self):
        w = rc.WarpState()
        self.assertFalse(w.physical("down", 0))      # no warp: never held back
        w.begin((500, 500), (100, 100))
        w.moved((120, 100))
        self.assertTrue(w.physical("down", 0))       # during the warp: held back ...
        self.assertTrue(w.physical("up", 0))         # ... and its release too
        self.assertFalse(w.physical("up", 2))        # a release of something never held back passes
        self.assertEqual(w.end((125, 101), (0, 0, 1920, 1080)), (505, 501))
        self.assertIsNone(w.end((0, 0), (0, 0, 1920, 1080)))
        self.assertEqual(w.take(), [("down", 0), ("up", 0)])   # replayed, in order, where the sharer is
        self.assertFalse(w.physical("up", 0))        # nothing pending any more

    def test_warp_click_batch(self):
        batch = rc.win_warp_click(None, (960, 540), 0, True, (0, 0, 1920, 1080))
        self.assertEqual([i.u.mi.dwFlags for i in batch], [0x0001 | 0x8000 | 0x4000, 0x0002])
        self.assertEqual((batch[0].u.mi.dx, batch[0].u.mi.dy), rc.win_absolute(960, 540, (0, 0, 1920, 1080)))
        self.assertEqual({i.u.mi.dwExtraInfo for i in batch}, {rc.MAGIC})

    def test_never_while_the_sharer_drags(self):
        r, b, clock = make("warp")
        r.local_input("down", 0)                                   # the sharer holds their left button (their own drag)
        st, _ = r.inject("abcdefgh1234", B, [{"t": "d", "b": 0, "x": 0.5, "y": 0.5}, {"t": "m", "x": 0.6, "y": 0.5},
                                              {"t": "u", "b": 0, "x": 0.6, "y": 0.5}, {"t": "w", "n": 1, "x": 0.5, "y": 0.5}])
        self.assertEqual(kinds(b, "button") + kinds(b, "wheel"), [])
        self.assertEqual((st["blocked"], st["queued"]), ("drag", 3))      # the press, its release, the wheel
        self.assertIn(("pointer", 484, 250, True), kinds(b, "pointer"))   # their arrow still follows them
        r.local_input("up", 0)                                     # the sharer lets go: the queue runs, in order
        for _ in range(50):
            if kinds(b, "wheel"):
                break
            time.sleep(0.02)
        self.assertEqual(kinds(b, "button"), [("button", 0, True, 420, 250, "warp"), ("button", 0, False, 484, 250, "warp")])
        self.assertEqual(kinds(b, "drag"), [])                     # the queued press had not happened: its release carries the move
        self.assertEqual(kinds(b, "wheel"), [("wheel", 1.0, False, "warp")])
        self.assertEqual(r.status("abcdefgh1234")["queued"], 0)
        self.assertEqual(r.status("abcdefgh1234")["blocked"], "")

    def test_queue_gives_up(self):
        r, b, clock = make("warp")
        r.local_input("down", 0)
        r.inject("abcdefgh1234", B, [{"t": "d", "b": 0, "x": 0.5, "y": 0.5}, {"t": "u", "b": 0, "x": 0.5, "y": 0.5}])
        clock.t += rc.WARP_WAIT_S + 1
        r.check()                                                  # the watch loop: still held -> the old clicks go
        self.assertEqual((len(r.wq), kinds(b, "button")), (0, []))
        self.assertGreaterEqual(r.stats["dropped"], 2)

    def test_a_missed_release_is_forgotten(self):
        r, b, clock = make("warp")
        r.local_input("down", 2)
        clock.t += rc.PHYS_STALE_S + 1
        r.inject("abcdefgh1234", B, [{"t": "d", "b": 0, "x": 0.5, "y": 0.5}])
        self.assertEqual(kinds(b, "button"), [("button", 0, True, 420, 250, "warp")])

    def test_posted_clicks_never_wait(self):
        r, b, clock = make("post")
        r.local_input("down", 0)                                   # a posted click never touches the cursor
        r.inject("abcdefgh1234", B, [{"t": "d", "b": 0, "x": 0.5, "y": 0.5}, {"t": "u", "b": 0, "x": 0.5, "y": 0.5}])
        self.assertEqual(kinds(b, "button"), [("button", 0, True, 420, 250, "post"), ("button", 0, False, 420, 250, "post")])
        self.assertEqual(r.stats["post"], 1)

    def test_a_physical_press_ends_the_controllers_warp_drag(self):
        r, b, clock = make("warp")
        r.inject("abcdefgh1234", B, [{"t": "d", "b": 0, "x": 0.5, "y": 0.5}])
        self.assertEqual(r.held_buttons, {0: "warp"})
        r.local_input("down", 2)                                   # the sharer clicks while the controller drags
        for _ in range(50):
            if not r.held_buttons:
                break
            time.sleep(0.02)
        self.assertEqual(r.held_buttons, {})
        self.assertEqual(kinds(b, "button")[-1], ("button", 0, False, None, None, "warp"))

    def test_mpx_is_its_own_pointer(self):
        r, b, clock = make("mpx")
        r.local_input("down", 0)                                   # a second X pointer never waits for the sharer
        r.inject("abcdefgh1234", B, [{"t": "d", "b": 0, "x": 0.5, "y": 0.5}, {"t": "m", "x": 0.25, "y": 0.5}, {"t": "u", "b": 0, "x": 0.25, "y": 0.5}])
        self.assertEqual(kinds(b, "drag"), [("drag", 260, 250, "mpx")])
        self.assertEqual(len(kinds(b, "button")), 2)


# ---- two pointers: moves, local input, keys -----------------------------------------------------------------------------
class TwoPointers(unittest.TestCase):
    def test_moves_move_only_the_controllers_pointer(self):
        r, b, clock = make("warp")
        self.assertEqual(b.ctl[0], ("start", WIN_URL, "Bob", "#e5533d"))   # the arrow is up, in their colour, with their name
        r.inject("abcdefgh1234", B, [{"t": "m", "x": 0.5, "y": 0.5}, {"t": "m", "x": 2, "y": -1}])
        self.assertEqual([e[0] for e in b.events], ["pointer", "pointer"])  # nothing else: the sharer's cursor never moves
        self.assertEqual(b.events[-1], ("pointer", 739, 50, True))          # clamped onto the surface
        r.inject("abcdefgh1234", B, [{"t": "m", "o": 1}])                   # their mouse left the picture
        self.assertEqual(b.events[-1], ("pointer", 0, 0, False))
        r.end("abcdefgh1234", "released")
        self.assertEqual(b.ctl[-1], ("end",))

    def test_local_input_never_pauses(self):
        r, b, clock = make("post")
        self.assertEqual((rc.LOCAL_HOLD, r.paused()), (0.0, False))
        for kind in ("move", "key", "down", "up"):
            r.local_input(kind, 0 if kind in ("down", "up") else None)
        st, _ = r.inject("abcdefgh1234", B, [{"t": "d", "b": 0, "x": 0.5, "y": 0.5}, {"t": "k", "c": "KeyA", "d": 1}])
        self.assertEqual((st["paused"], st["pauseLeft"]), (False, 0))
        self.assertEqual([e[0] for e in b.events if e[0] != "pointer"], ["button", "key"])
        self.assertEqual(r.caps()["hold"], 0.0)
        self.assertTrue(r.caps()["pointers"])

    def test_keys_route(self):
        r, b, clock = make("post")
        b.focus, b.post_keys = False, True                      # the shared window is behind: its classic control gets posted keys
        r.inject("abcdefgh1234", B, [{"t": "k", "c": "ShiftLeft", "d": 1}, {"t": "k", "c": "KeyA", "d": 1}, {"t": "k", "c": "KeyA", "d": 0}])
        self.assertEqual(kinds(b, "key"), [("key", "ShiftLeft", True, "post"), ("key", "KeyA", True, "post"), ("key", "KeyA", False, "post")])
        self.assertEqual(r._mods(), ("shift",))
        b.post_keys = False                                     # neither in front nor a classic control: "click inside first"
        st, _ = r.inject("abcdefgh1234", B, [{"t": "k", "c": "KeyB", "d": 1}])
        self.assertEqual(st["blocked"], "focus")
        r.end("abcdefgh1234", "released")                       # held keys let go on the route they went down
        self.assertEqual(kinds(b, "key")[-1], ("key", "ShiftLeft", False, "post"))


# ---- the pointer samples + the loopback WebSocket -----------------------------------------------------------------------
class Samples(unittest.TestCase):
    def test_to_norm(self):
        self.assertEqual(rc.to_norm((100, 50), WRECT), [0.0008, 0.0013, 1])
        self.assertEqual(rc.to_norm((420, 250), WRECT), [0.5008, 0.5012, 1])
        self.assertEqual(rc.to_norm((99, 250), WRECT)[2], 0)   # off the surface
        self.assertIsNone(rc.to_norm(None, WRECT))

    def test_sample_only_when_something_moved(self):
        r, b, clock = make("post")
        b.cursor = (420, 250)
        s = r.ptr_sample()
        self.assertEqual((s["s"], s["c"], s["cap"]), ([0.5008, 0.5012, 1], [0, 0, 0], 0))   # the controller has not moved yet
        self.assertIsNone(r.ptr_sample())                        # still: nothing
        r.inject("abcdefgh1234", B, [{"t": "m", "x": 0.25, "y": 0.75}])
        s = r.ptr_sample()
        self.assertEqual(s["c"], rc.to_norm((260, 350), WRECT))
        b.cursor = (900, 900)                                    # the sharer's own pointer left the shared window
        self.assertEqual(r.ptr_sample()["s"][2], 0)
        self.assertIsNotNone(r.ptr_sample(force=True))
        self.assertIn("ptr", r.renew("abcdefgh1234"))            # the HTTP fallback carries it
        b.pointer_in_capture = True                              # X11: the arrow is in the picture
        self.assertEqual(r.ptr_sample(force=True)["cap"], 1)
        self.assertEqual(rc.PTR_HZ, 30)

    def test_ws_primitives(self):
        self.assertEqual(rc.ws_accept("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")   # RFC 6455's example
        self.assertEqual(rc.ws_frame(b"hi"), b"\x81\x02hi")
        self.assertEqual(rc.ws_frame(b"x" * 300)[:4], b"\x81\x7e\x01\x2c")
        mask = b"\x01\x02\x03\x04"
        data = b'{"a":1}'
        frame = bytes([0x81, 0x80 | len(data)]) + mask + bytes(c ^ mask[i & 3] for i, c in enumerate(data))
        frames, rest = rc.ws_parse(frame + frame[:3])
        self.assertEqual((frames, rest), ([(True, 1, data)], frame[:3]))

    def test_websocket_end_to_end(self):
        import kastr_relay as kr
        r, b, clock = make("post")
        r.clock = time.monotonic
        g = r.grant
        g["lease"] = time.monotonic() + 60
        srv, cli = socket.socketpair()

        class H:
            command, path = "GET", "/api/rc/ws"
            headers = {"Upgrade": "websocket", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==", "Origin": "http://127.0.0.1:8001"}
            connection = srv
            close_connection = False

            def send_error(self, c):
                raise AssertionError(c)
        old_local, old_rc = kr.is_local, rc._RC
        kr.is_local = lambda h: True
        rc._RC = r

        class Bridge:
            _pubs = {7: types.SimpleNamespace(paused=False, broadcast="alpha/x/w.hang")}

            def get(self, fid):
                return types.SimpleNamespace(url=WIN_URL) if int(fid) == 7 else None
        th = threading.Thread(target=rc.handle_ws, args=(H(), Bridge()), daemon=True)
        try:
            th.start()
            cli.settimeout(3)
            head = b""
            while b"\r\n\r\n" not in head:
                head += cli.recv(1)
            self.assertIn(b"101 Switching Protocols", head)
            self.assertIn(b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", head)

            def send(obj):
                data = json.dumps(obj).encode()
                m = b"\x11\x22\x33\x44"
                cli.sendall(bytes([0x81, 0x80 | 126]) + len(data).to_bytes(2, "big") + m + bytes(c ^ m[i & 3] for i, c in enumerate(data)))
            buf = b""

            def recv():
                nonlocal buf
                while True:
                    fr, buf = rc.ws_parse(buf)
                    if fr:
                        out = [json.loads(p) for _, _, p in fr]
                        return out
                    buf += cli.recv(65536)
            send({"op": "input", "rcid": "abcdefgh1234", "src": B, "ev": [{"t": "m", "x": 0.5, "y": 0.5}, {"t": "d", "b": 0, "x": 0.5, "y": 0.5}], "n": 7})
            got, t0 = [], time.time()
            moved = lambda m: "ptr" in m and m["ptr"]["c"][2] == 1
            while time.time() - t0 < 2 and not (any(m.get("re") == "input" for m in got) and any(moved(m) for m in got)):
                got += recv()
            rep = next(m for m in got if m.get("re") == "input")
            self.assertEqual((rep["code"], rep["n"], rep["active"]), (200, 7, True))   # the page's number comes back (its latency echo)
            ptr = next(m for m in got if moved(m))
            self.assertEqual((ptr["rcid"], ptr["ptr"]["c"][:2]), ("abcdefgh1234", [0.5008, 0.5012]))
            self.assertEqual(kinds(b, "button"), [("button", 0, True, 420, 250, "post")])
            # pointers stream at most PTR_HZ a second while one moves -- and nothing while both stand still
            seen, t0 = 0, time.time()
            while time.time() - t0 < 0.5:
                b.cursor = (100 + int((time.time() - t0) * 1000), 60)
                cli.settimeout(0.05)
                try:
                    seen += sum(1 for m in recv() if "ptr" in m)
                except socket.timeout:
                    pass
            self.assertTrue(5 <= seen <= rc.PTR_HZ * 0.5 + 3, seen)
            cli.settimeout(0.3)
            time.sleep(0.15)
            try:
                while True:
                    recv()
            except socket.timeout:
                pass
            with self.assertRaises(socket.timeout):
                recv()
            cli.sendall(bytes([0x88, 0x80]) + b"\x00\x00\x00\x00")   # close
            th.join(2)
            self.assertFalse(th.is_alive())
        finally:
            kr.is_local, rc._RC = old_local, old_rc
            srv.close()
            cli.close()

    def test_ws_guard(self):
        import kastr_relay as kr
        old = kr.is_local
        kr.is_local = lambda h: True
        try:
            errs = []

            class H:
                command, path = "GET", "/api/rc/ws"
                headers = {"Upgrade": "websocket", "Sec-WebSocket-Key": "x", "Origin": "https://evil.example"}

                def send_error(self, c):
                    errs.append(c)
            rc.handle_ws(H(), None)
            self.assertEqual(errs, [403])
        finally:
            kr.is_local = old
        self.assertEqual(read("kastr_serve.py").count("return kastr_rc.handle_ws(self, bridge, _note)"), 1)


# ---- the viewers' pointers (mirrors of the page's formulas) ---------------------------------------------------------------
def client_of(u, v, el, pane, cw, ch, Bw, Bh, cover):
    """The page's rcClientOf, mirrored."""
    if not (0 <= u <= 1 and 0 <= v <= 1):
        return None
    sc = (max if cover else min)(Bw / cw, Bh / ch)
    ox, oy = (Bw - cw * sc) / 2, (Bh - ch * sc) / 2
    x = el["left"] + (ox + u * cw * sc) * el["width"] / Bw - pane["left"]
    y = el["top"] + (oy + v * ch * sc) * el["height"] / Bh - pane["top"]
    return None if x < 0 or y < 0 or x > pane["width"] or y > pane["height"] else (round(x, 3), round(y, 3))


def delay_of(delay, buffer):
    """The page's rcPtrDelay, mirrored."""
    import re
    n = lambda s: int(re.match(r"^\d+", s).group(0)) if re.match(r"^\d+", s or "") else 0
    return 100 + (0 if delay == "instant" else n(delay) + n(buffer))


def pick(q, now, offset, L):
    """The page's rcPtrPick, mirrored: q = [(t fleet ms, at local ms)]."""
    fleet = now + offset
    last = q[-1]
    clock_ok = last[0] > 0 and -1500 < fleet - last[0] < 15000
    want = fleet - L if clock_ok else now - max(0, L - 30)
    p = q[0]
    for s in q:
        if (s[0] if clock_ok else s[1]) <= want:
            p = s
        else:
            break
    return p


class ViewerPointers(unittest.TestCase):
    def test_mapping_letterbox_crop_zoom(self):
        pane = {"left": 10, "top": 20, "width": 800, "height": 600}
        el = {"left": 10, "top": 20, "width": 800, "height": 600}
        # a 1920x1080 share letterboxed (contain) into 800x600: 75 px bars above and below
        self.assertEqual(client_of(0.5, 0.5, el, pane, 1920, 1080, 800, 600, False), (400.0, 300.0))
        self.assertEqual(client_of(0, 0, el, pane, 1920, 1080, 800, 600, False), (0.0, 75.0))
        self.assertEqual(client_of(1, 1, el, pane, 1920, 1080, 800, 600, False), (800.0, 525.0))
        # cover (a rail tile) crops 1/8 of the width each side: a pointer there is out of sight
        self.assertIsNone(client_of(0.05, 0.5, el, pane, 1920, 1080, 800, 600, True))
        self.assertEqual(client_of(0.5, 0.5, el, pane, 1920, 1080, 800, 600, True), (400.0, 300.0))
        # zoomed 2x about the centre (the element's box grows; the pane clips)
        zoom = {"left": -390, "top": -280, "width": 1600, "height": 1200}
        self.assertEqual(client_of(0.5, 0.5, zoom, pane, 1920, 1080, 800, 600, False), (400.0, 300.0))
        self.assertIsNone(client_of(0.1, 0.5, zoom, pane, 1920, 1080, 800, 600, False))
        self.assertIsNone(client_of(1.2, 0.5, el, pane, 1920, 1080, 800, 600, False))   # off the picture
        # ... and it is the inverse of rcMapPoint (the controller's own mapping, 0.21.79)
        def map_point(cx, cy, r, Bw, Bh, cw, ch, cover):
            sc = (max if cover else min)(Bw / cw, Bh / ch)
            ox, oy = (Bw - cw * sc) / 2, (Bh - ch * sc) / 2
            lx, ly = (cx - r["left"]) * Bw / r["width"], (cy - r["top"]) * Bh / r["height"]
            return round((lx - ox) / (cw * sc), 5), round((ly - oy) / (ch * sc), 5)
        x, y = client_of(0.3, 0.7, zoom, pane, 1920, 1080, 800, 600, False)
        self.assertEqual(map_point(x + pane["left"], y + pane["top"], zoom, 800, 600, 1920, 1080, False), (0.3, 0.7))
        p = read("moq-watch-lite.html")
        self.assertIn("const x = r.left + (ox + u * cw * sc) * r.width / Bw - pr.left, y = r.top + (oy + v * ch * sc) * r.height / Bh - pr.top;", p)
        self.assertIn("return x < 0 || y < 0 || x > pr.width || y > pr.height ? null : [x, y];", p)

    def test_video_delay_alignment(self):
        self.assertEqual(delay_of("150ms", "400ms"), 650)   # the spotlight budget: the picture is ~650 ms behind the sharer
        self.assertEqual(delay_of("instant", "0ms"), 100)   # the controller's own tile
        self.assertEqual(delay_of("30ms", "60ms"), 190)
        q = [(10_000, 50_000), (10_100, 50_100), (10_400, 50_400), (10_650, 50_650)]
        # clocks agree (fleet time): at 10 700 with a 650 ms budget the picture shows 10 050 -> the first sample
        self.assertEqual(pick(q, 10_700, 0, 650), q[0])
        self.assertEqual(pick(q, 11_060, 0, 650), q[2])     # the picture shows 10 410
        self.assertEqual(pick(q, 10_700, 0, 100), q[2])     # an instant player: almost the newest (10 600 -> 10 400)
        # clocks disagree (the sharer's stamp is hours off): the same budget after each sample ARRIVED
        q2 = [(1, 50_000), (2, 50_100), (3, 50_400)]
        self.assertEqual(pick(q2, 51_100, 0, 650), q2[2])
        self.assertEqual(pick(q2, 50_700, 0, 650), q2[0])   # arrived at or before 50 080 -> the 50 000 one ...
        p = read("moq-watch-lite.html")
        for anchor in ('return RC_PTR_V0 + (d === "instant" ? 0 : (parseInt(d, 10) || 0) + (parseInt(b, 10) || 0));',
                       "const clockOk = last.t > 0 && fleet - last.t > -1500 && fleet - last.t < 15000;",
                       "const want = clockOk ? fleet - L : Date.now() - Math.max(0, L - 30);",
                       "const RC_PRIO = 255, RC_PTR_V0 = 100, RC_PTR_KEEP_MS = 3000;"):
            self.assertEqual(p.count(anchor), 1, anchor)

    def test_who_draws_what(self):
        p = read("moq-watch-lite.html")
        # only while the share is controlled (c), the sharer's arrow + the controller's -- never the controller's own on their own
        # screen, never one the capture already shows (cap)
        self.assertIn("rcGrant && rcGrant.share === s.path ? { c: 1 } : {}, ptListFields(s.path)));", p)   # 0.21.83: + the pointer fields
        self.assertIn("for (const x of list) if (x.c && tiles.has(x.p)) want.set(x.p, pp[0] + \"/\" + pp[1] + \"/~rc/\" + pp[3]);", p)
        self.assertIn("if (!p || !p.on || (k === \"c\" && (p.cap || rcCtl?.share === share))) continue;", p)
        self.assertIn('h.sub = stateSubscribe(connection, path, "ptr.json", "snapshot", (v) => rcPtrArrive(share, h, v), RC_PRIO);', p)
        # the sharer publishes both, tagged with names and colours
        self.assertIn('p: [{ k: "s", n: (myOpName() || "Sharer").slice(0, 28), c: rcMyColor(), x: ptr.s[0], y: ptr.s[1], on: ptr.s[2] ? 1 : 0, cap: ptr.scap ? 1 : 0 },', p)
        self.assertIn('{ k: "c", n: String(g.name).slice(0, 28), c: g.ctlColor, x: ptr.c[0], y: ptr.c[1], on: ptr.c[2] ? 1 : 0, cap: ptr.cap ? 1 : 0 }] });', p)
        self.assertIn('color: ctlColor });', p)
        self.assertIn('["in.json", "st.json", "ptr.json", "pts.json"], { priority: RC_PRIO, maxAge: 2000 }', p)   # 0.21.83: + pts.json (pointer mode)
        # Kenton's words on the prompt
        self.assertIn("with their own pointer and their name on your screen.", p)   # 0.21.83: the prompt also names file transfer
        self.assertIn("Your mouse and keyboard keep working at the same time.", p)


# ---- the capture + encode while controlled -------------------------------------------------------------------------------
class ShareMode(unittest.TestCase):
    def test_capture_cursor_only_outside_control(self):
        import kastr_screen
        rect = {"rect": {"x": 0, "y": 0, "w": 1280, "h": 720}}
        with mock.patch.object(kastr_screen, "LINUX", True), mock.patch.dict(os.environ, {"DISPLAY": ":99"}), \
                mock.patch.object(kastr_screen, "_resolve", return_value=rect):
            self.assertIn("-draw_mouse", kastr_screen.capture_input("screen://window/5"))
            a = kastr_screen.capture_input("screen://window/5")
            self.assertEqual(a[a.index("-draw_mouse") + 1], "1")
            a = kastr_screen.capture_input("screen://window/5", cursor=False)
            self.assertEqual(a[a.index("-draw_mouse") + 1], "0")
            a = kastr_screen.capture_input("screen://monitor/1", cursor=False, fps=60)
            self.assertEqual((a[a.index("-draw_mouse") + 1], a[a.index("-framerate") + 1]), ("0", "60"))
        # Windows (gfxcapture): built, never run -- the repaint kick (it nudges the real cursor) is stubbed
        src = {"hmonitor": 1, "rect": {"x": 0, "y": 0, "w": 1920, "h": 1080}, "width": 1920, "height": 1080}
        with mock.patch.object(kastr_screen, "LINUX", False), mock.patch.object(kastr_screen, "_kick_soon", lambda u: None), \
                mock.patch.object(kastr_screen, "_resolve", return_value=src):
            on = kastr_screen.capture_input("screen://monitor/1")[-1]
            off = kastr_screen.capture_input("screen://monitor/1", cursor=False)[-1]
        self.assertIn("capture_cursor=1", on)
        self.assertIn("capture_cursor=0", off)
        self.assertNotIn("capture_cursor=1", off)

    def _pub(self, rcmode, enc="libx264"):
        import kastr_rtsp
        seen = []
        bridge = types.SimpleNamespace(ffmpeg="ffmpeg", moq="moq", sends_h264=lambda f: False, usable_encoder=lambda: enc,
                                       rc_lowlat=lambda e: list(kastr_rtsp.RC_LOWLAT.get(e, [])), _od_ensure=lambda: None)
        feed = kastr_rtsp.Feed(7, "screen://window/2097153")
        pub = kastr_rtsp.Publisher(bridge, feed, "alpha/h-aa11/me/w.hang", "http://relay:4443", audio=False, keep=False)
        pub.rcmode = rcmode
        import kastr_screen
        with mock.patch.object(kastr_screen, "capture_input", lambda url, **kw: seen.append(kw) or ["-f", "lavfi", "-i", "cap"]):
            ff, moq = pub._args()
        return ff, seen

    def test_publisher_args_only_while_controlled(self):
        import kastr_rtsp
        ff, seen = self._pub(False)
        self.assertEqual(seen, [{}])
        for a in ("-flush_packets", "-maxrate", "-bufsize"):
            self.assertNotIn(a, ff)
        ff, seen = self._pub(True)
        self.assertEqual(seen, [{"cursor": False, "fps": __import__("kastr_screen").RC_FPS}])
        self.assertEqual(ff[ff.index("-maxrate") + 1], "5M")
        self.assertEqual(ff[ff.index("-flush_packets") + 1], "1")
        self.assertLess(ff.index("-flush_packets"), ff.index("-f", ff.index("-flush_packets")))
        ff, _ = self._pub(True, "h264_nvenc")
        for a in ("-tune", "ull", "-zerolatency", "-bf"):
            self.assertIn(a, ff)
        self.assertEqual(kastr_rtsp.publish_output_args(False, encoder="h264_mf", audio=False, screen=True, lowlat=[])[-7:-5], ["-flush_packets", "1"])

    def test_bridge_rc_mode(self):
        import kastr_rtsp
        nudges, logs = [], []
        pub = types.SimpleNamespace(feed=types.SimpleNamespace(url="screen://window/9"), rcmode=False, copy=False, broadcast="a/b/c.hang",
                                    nudge=lambda why: nudges.append(why))
        cam = types.SimpleNamespace(feed=types.SimpleNamespace(url="rtsp://cam/1"), rcmode=False, copy=False, broadcast="a/b/d.hang", nudge=nudges.append)
        me = types.SimpleNamespace(_pubs={3: pub, 4: cam}, rc_lowlat=lambda e: [], usable_encoder=lambda: "libx264", log=logs.append)
        self.assertTrue(kastr_rtsp.Bridge.rc_mode(me, 3, True))
        self.assertFalse(kastr_rtsp.Bridge.rc_mode(me, 3, True))        # already
        self.assertFalse(kastr_rtsp.Bridge.rc_mode(me, 4, True))        # a camera is never a controlled share
        self.assertFalse(kastr_rtsp.Bridge.rc_mode(me, 99, True))
        self.assertTrue(kastr_rtsp.Bridge.rc_mode(me, 3, False))
        self.assertEqual((nudges, pub.rcmode), (["rc-on", "rc-off"], False))

    def test_low_latency_options_are_test_encoded_once(self):
        import kastr_rtsp
        calls = []
        me = types.SimpleNamespace(ffmpeg="ffmpeg", log=lambda m: None)
        with mock.patch.object(kastr_rtsp.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or types.SimpleNamespace(returncode=1)):
            self.assertEqual(kastr_rtsp.Bridge.rc_lowlat(me, "h264_amf"), [])        # refused: the normal encode stays
            self.assertEqual(kastr_rtsp.Bridge.rc_lowlat(me, "h264_amf"), [])
        self.assertEqual(len(calls), 1)
        self.assertIn("ultralowlatency", calls[0])
        self.assertIn("-f", calls[0])
        with mock.patch.object(kastr_rtsp.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(returncode=0)):
            self.assertEqual(kastr_rtsp.Bridge.rc_lowlat(me, "libx264"), kastr_rtsp.RC_LOWLAT["libx264"])

    def test_control_switches_the_share_mode(self):
        calls = []
        r, b, clock = make("post", share_mode=lambda fid, on: calls.append((fid, on)))
        for _ in range(50):
            if calls:
                break
            time.sleep(0.02)
        r.end("abcdefgh1234", "released")
        for _ in range(50):
            if len(calls) == 2:
                break
            time.sleep(0.02)
        self.assertEqual(calls, [(7, True), (7, False)])
        self.assertIsNone(rc.bridge_mode(None))
        seen = []
        br = types.SimpleNamespace(rc_mode=lambda f, o: seen.append((f, o)))
        with mock.patch.dict(os.environ, {"KASTR_RC_SHARE_MODE": ""}):
            self.assertIsNone(rc.bridge_mode(br))           # OFF by default: the restart froze the controller's picture 14 s+ (lab)
        with mock.patch.dict(os.environ, {"KASTR_RC_SHARE_MODE": "1"}):
            rc.bridge_mode(br)("7", 1)
        self.assertEqual(seen, [(7, True)])

    def test_cursor_in_the_picture_gets_only_a_name(self):
        r, b, clock = make("post")                          # no share_mode: the sharer's cursor stays in the capture
        self.assertEqual(r.ptr_sample(force=True)["scap"], 1)
        r2, b2, _ = make("post", share_mode=lambda f, o: None)
        self.assertEqual(r2.ptr_sample(force=True)["scap"], 0)
        p = read("moq-watch-lite.html")
        self.assertIn('on: ptr.s[2] ? 1 : 0, cap: ptr.scap ? 1 : 0 },', p)
        self.assertIn('el.classList.toggle("tagonly", k === "s" && !!p.cap);', p)
        self.assertIn(".pane .rcptr.tagonly svg { visibility:hidden; }", p)

    def test_controller_player_only_while_controlling(self):
        p = read("moq-watch-lite.html")
        self.assertIn('const RC_TUNE = { video: { delay: "instant", buffer: "0ms" }, audio: { delay: "30ms", buffer: "60ms" } };', p)
        self.assertIn('const cls = rcSh && rcSh === name ? "rc"', p)
        self.assertIn('const tn = cls === "rc" ? (t.hasAudio === false ? RC_TUNE.video : RC_TUNE.audio) : tuningFor(cls);', p)
        self.assertIn('const prio = Math.max(cls === "rc" ? 250 : isSelected ? 190', p)
        self.assertIn('window.__rcCtlShare = () => (rcCtl ? rcCtl.share : "");', p)
        # re-tuned when control starts and when it ends
        i, j = p.index("function rcAllowArrive("), p.index("function rcCtlSub(")
        self.assertIn("try { applyState(); } catch {}", p[i:j])
        i, j = p.index("function rcCtlEnd("), p.index("// ---- the sharer")
        self.assertIn("try { applyState(); } catch {}", p[i:j])
        # the input's way: leading-edge moves, a WebSocket to the sharer's own KASTR, top priority both ways
        self.assertIn("if (!c.mvT) { const w = 16 - (performance.now() - c.mvAt); if (w <= 0) rcFlushMove(c);", p)
        self.assertIn('ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/api/rc/ws");', p)
        self.assertIn('"in.json", "snapshot", (v) => rcInArrive(g, v), RC_PRIO)', p)
        self.assertIn('"st.json", "snapshot", (v) => rcStArrive(c, v), RC_PRIO)', p)



class NoTooltipWhileControlling(unittest.TestCase):
    # 0.21.83 (Kenton: hovering the screen he controls popped up a grey box explaining it)
    def test_capture_layer_has_no_title(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "moq-watch-lite.html"), encoding="utf-8", newline="") as f:
            p = f.read()
        i = p.index("  function rcCapAttach(c, t) {")
        body = p[i:p.index("t.pane.appendChild(cap);", i)]
        self.assertNotIn(".title", body)
        self.assertIn('cap.setAttribute("aria-label", "Controlling "', body)

if __name__ == "__main__":
    unittest.main()
