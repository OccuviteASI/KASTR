# -*- coding: utf-8 -*-
"""v0.21.83 POINTER MODE. Kenton (2026-10-23): "On the remote control, I would like to make it so there is a view-only mode where
the user is able to see my mouse, as well as whoever else they allow to share, and lets them move their mouse around with their
name and when they click it makes a little sonar thing around the mouse click to show everyone where it was clicked. This will
help with sharing a screen and collaborating on a document, etc."

What is proven here (NO real input anywhere, no window created, no screen captured):
  * the relay's pointer notes (pask / pallow / pdeny / pstop): anyone in the room may ask (viewers too), only the sharer
    answers, the sharer or the pointing person stops, rate limits + the cool-down after a no, and a pointer request's id is
    never answered (or asked) as a CONTROL grant;
  * the sonar's timing and geometry (three staggered rings, the dot, the name, RIPPLE_S), the annulus spans an X11 window is
    shaped to, the window layout -- and the page's CSS sonar matching them;
  * the Windows ripple window: the pointer window's styles (layered, click-through, topmost, tool, no-activate, excluded from
    capture) and where it is put -- run against a FAKE kastr_overlay (nothing is created); the X11 twin's shape and parent;
  * kastr_point.PointMode with a recording board: pointers mapped onto the shared surface, the full set each time (missing =
    taken off), each click drawn once, the lease, the share stopping / pausing / re-pointing; the sharer's own pointer + clicks
    sampled (inside the surface only, never during a controller's warp-click), their own sonar on "Show my clicks";
  * NOTHING IS INJECTED: every pointer-mode op leaves the injector's backend untouched, and kastr_point has no way to press,
    move or type; the loopback WebSocket carries pt-* ops in and the sharer's own samples out;
  * the page: who may point (pv / pe / pa / pb in the room's list), the transport (pt.json on the pointing person's member
    broadcast -> the sharer -> ONE pts.json for every viewer), the prompt's words, the menus, and the viewers' alignment of a
    sonar with the picture (mirrored)."""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_point as kp  # noqa: E402
import kastr_rc as rc  # noqa: E402
import kastr_relay as kr  # noqa: E402

A, B, C, V = "alice-aa11", "bob-bb22", "carol-cc33", "vic-dd44"   # A shares; B publishes; C, V view
SHARE = "alpha/%s/alice/screen.hang" % A
WIN_URL = "screen://window/4242"
WRECT = {"x": 100, "y": 50, "w": 641, "h": 401}


class _P(str):
    def __repr__(self):
        return "<page>"


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return _P(f.read())


# ---- the relay's pointer notes -------------------------------------------------------------------------------------------
class RelayBase(unittest.TestCase):
    def setUp(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)

    def tearDown(self):
        self.svc.close()

    def tok(self, host, code="pub-1", room="alpha"):
        o, c = self.svc.token({"room": room, "code": code, "host": host}, "10.0.0.7")
        assert c == 200, o
        return o["tokens"]["member"]

    def rc(self, t, **body):
        return self.svc.people_api(dict({"op": "rc"}, **body), "Bearer " + t, "10.0.0.7")

    def pask(self, t, rcid="ptask001", to=A, share=SHARE, **kw):
        return self.rc(t, kind="pask", to=to, share=share, id=rcid, peer="P-v1", by="Vic", label="Screen 1", **kw)

    def inbox(self, t):
        o, c = self.svc.people_api({"op": "beat"}, "Bearer " + t, "10.0.0.7")
        assert c == 200, o
        return [x for x in o["inbox"] if x.get("kind") == "rc"]


class RelayPointerNotes(RelayBase):
    def test_a_viewer_may_ask_to_point(self):
        ta, tv = self.tok(A), self.tok(V, "view-1")
        o, c = self.pask(tv)
        self.assertEqual((c, o["ok"], o["id"]), (200, True, "ptask001"))
        it = self.inbox(ta)[0]
        self.assertEqual((it["rc"], it["rcid"], it["from"], it["share"], it["by"], it["peer"]), ("pask", "ptask001", V, SHARE, "Vic", "P-v1"))
        self.assertEqual(it["id"], "rc-pask-ptask001-" + V)
        o, c = self.rc(tv, kind="ask", to=A, share=SHARE, id="ctl00001", peer="P-v1")   # ... but never to CONTROL
        self.assertEqual(c, 403)
        self.assertIn("only publishers and admins", o["error"])

    def test_only_the_sharer_answers_and_either_side_stops(self):
        ta, tv, tc = self.tok(A), self.tok(V, "view-1"), self.tok(C, "view-1")
        self.assertEqual(self.pask(tv)[1], 200)
        o, c = self.rc(tc, kind="pallow", to=V, share=SHARE, id="ptask001")
        self.assertEqual((c, o["error"]), (403, "only the person sharing answers"))
        o, c = self.rc(tv, kind="pallow", to=A, share=SHARE, id="ptask001")   # the asker cannot allow itself either
        self.assertEqual(c, 403)
        self.assertEqual(self.rc(ta, kind="pallow", to=V, share=SHARE, id="ptask001", peer="P-alice")[1], 200)
        self.assertEqual([(x["rc"], x["from"], x["peer"]) for x in self.inbox(tv)], [("pallow", A, "P-alice")])
        o, c = self.rc(tc, kind="pstop", to=V, share=SHARE, id="ptstop01")    # a third party takes nobody's pointer off
        self.assertEqual((c, o["error"]), (403, "only the sharer or the pointing person stops a pointer"))
        self.assertEqual(self.rc(ta, kind="pstop", to=V, share=SHARE, id="ptstop02", why="removed")[1], 200)
        self.assertEqual(self.rc(tv, kind="pstop", to=A, share=SHARE, id="ptstop03", peer="P-v1", why="released")[1], 200)
        self.assertEqual([(x["rc"], x["why"]) for x in self.inbox(tv)], [("pstop", "removed")])
        self.assertEqual([(x["rc"], x["why"], x["peer"]) for x in self.inbox(ta)], [("pask", "", "P-v1"), ("pstop", "released", "P-v1")])

    def test_ask_goes_to_the_owner_and_stays_in_the_room(self):
        o, c = self.pask(self.tok(V, "view-1"), to=C)
        self.assertEqual((c, o["error"]), (400, "ask the person whose share it is"))
        o, c = self.pask(self.tok(V, "view-1", room="beta"))
        self.assertEqual((c, o["error"]), (403, "that share is not in your room"))
        o, c = self.pask(self.tok(V, "view-1", room="main"))   # the Lobby
        self.assertEqual(c, 403)

    def test_a_pointer_request_never_becomes_control(self):
        ta, tb = self.tok(A), self.tok(B)
        self.assertEqual(self.pask(tb, rcid="ptgrant1")[1], 200)
        o, c = self.rc(ta, kind="allow", to=B, share=SHARE, id="ptgrant1", peer="P-alice")   # the sharer's page answers it as control
        self.assertEqual(c, 409)
        self.assertIn("pointer request", o["error"])
        o, c = self.rc(tb, kind="ask", to=A, share=SHARE, id="ptgrant1", peer="P-b")          # nor re-used as a control ask
        self.assertEqual(c, 409)
        self.assertEqual(self.rc(ta, kind="pallow", to=B, share=SHARE, id="ptgrant1")[1], 200)
        self.assertEqual([x["rc"] for x in self.inbox(tb)], ["pallow"])
        # control keeps its own ids, asks and Allow
        self.assertEqual(self.rc(tb, kind="ask", to=A, share=SHARE, id="ctlgrant", peer="P-b")[1], 200)
        self.assertEqual(self.rc(ta, kind="allow", to=B, share=SHARE, id="ctlgrant", peer="P-alice")[1], 200)

    def test_rates_and_the_cool_down(self):
        tv, ta = self.tok(V, "view-1"), self.tok(A)
        for i in range(kr.PT_ASK_RATE[0]):
            self.assertEqual(self.pask(tv, rcid="ptrate%02d" % i)[1], 200)
        o, c = self.pask(tv, rcid="ptrate99")
        self.assertEqual(c, 429)
        self.assertIn("too many pointer requests", o["error"])
        # control's own rate is untouched by pointer asks
        self.assertEqual(self.rc(self.tok(B), kind="ask", to=A, share=SHARE, id="ctlrate1", peer="P-b")[1], 200)
        tc = self.tok(C, "view-1")
        self.assertEqual(self.pask(tc, rcid="ptcool01")[1], 200)
        self.assertEqual(self.rc(ta, kind="pdeny", to=C, share=SHARE, id="ptcool01", why="no")[1], 200)
        o, c = self.pask(tc, rcid="ptcool02")
        self.assertEqual(c, 429)
        self.assertIn("they said no", o["error"])

    def test_clean(self):
        for k in kr.PT_KINDS:
            it = kr.rc_item_clean({"kind": "rc", "rc": k, "rcid": "abcdefgh", "room": "alpha", "share": SHARE, "from": V, "why": "removed"})
            self.assertEqual((it["rc"], it["why"]), (k, "removed"))
        self.assertIsNone(kr.rc_item_clean({"kind": "rc", "rc": "pinject", "rcid": "abcdefgh", "room": "alpha", "share": SHARE, "from": V}))
        self.assertEqual(kr.PT_KINDS, ("pask", "pallow", "pdeny", "pstop"))
        self.assertEqual(kr.RC_KINDS, ("ask", "allow", "deny", "stop"))   # control's own kinds are unchanged


# ---- the sonar: timing + geometry ----------------------------------------------------------------------------------------
class Sonar(unittest.TestCase):
    def test_rings(self):
        self.assertEqual(kp.ripple_rings(0), [(kp.RIPPLE_R0, 3)])
        self.assertEqual(kp.ripple_rings(-0.01), [])
        self.assertEqual(kp.ripple_rings(kp.RIPPLE_S), [])
        self.assertEqual(len(kp.ripple_rings(0.33)), 3)                    # all three at once mid-way
        self.assertEqual(len(kp.ripple_rings(0.79)), 1)                    # the last one alone at the end
        self.assertAlmostEqual(2 * kp.RIPPLE_STAGGER_S + kp.RIPPLE_GROW_S, kp.RIPPLE_S)
        prev = 0
        for i in range(1, 48):                                             # the first ring grows, thinning, never shrinks
            r = kp.ripple_rings(i / 100.0)[0]
            self.assertGreaterEqual(r[0], prev)
            prev = r[0]
        self.assertLessEqual(max(r for r, _ in kp.ripple_rings(0.47)), kp.RIPPLE_R)
        self.assertGreater(kp.ripple_rings(0.1)[0][1], kp.ripple_rings(0.45)[0][1])
        self.assertEqual(kp.ripple_rings(0.2, 2.0)[0][0], 2 * kp.ripple_rings(0.2)[0][0] - (1 if kp.ripple_rings(0.2, 2.0)[0][0] % 2 else 0))
        self.assertGreater(kp.ripple_dot(0), 0)
        self.assertEqual(kp.ripple_dot(kp.RIPPLE_DOT_S), 0)

    def test_layout_holds_rings_and_name(self):
        for s in (1.0, 1.5, 2.0):
            lay = kp.ripple_layout("Bob Pointer", s)
            R = max(r + w for t in range(80) for r, w in kp.ripple_rings(t / 100.0, s))
            self.assertTrue(lay["cx"] - R >= 0 and lay["cx"] + R < lay["w"] and lay["cy"] + R < lay["h"], (s, lay, R))
            tx, ty, tw, th = lay["tag"]
            self.assertTrue(tx >= 0 and tx + tw < lay["w"] and ty >= 0 and ty + th < lay["cy"] - R + 1, (s, lay, R))   # above the rings
            self.assertLessEqual(abs(tx + tw / 2.0 - lay["cx"]), 1)                                                   # centred on the click
        self.assertGreater(kp.ripple_layout("A much longer name")["w"], kp.ripple_layout("Al")["w"])
        self.assertEqual(kp.ripple_layout("")["tag"][2], 0)                # no name: no tag
        self.assertGreater(kp.ripple_layout("A name far wider than the rings")["w"], 2 * kp.ripple_layout("")["cx"] + 1)
        self.assertIn(".pane .ptsonar .nm { position:absolute; left:0; top:-52px; transform:translateX(-50%);", read("moq-watch-lite.html"))

    def test_annulus_spans(self):
        cx, cy, r, w = 30, 30, 20, 3
        spans = kp.ring_spans(cx, cy, r, w)
        for y, a, b in spans:
            self.assertLess(a, b)
            for x in range(a, b):
                d = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
                self.assertTrue(r - w / 2.0 - 0.75 <= d <= r + w / 2.0 + 0.75, (x, y, d))
        rows = {y for y, _, _ in spans}
        self.assertEqual((min(rows), max(rows)), (cy - r - 1, cy + r))
        mid = [s for s in spans if s[0] == cy]
        self.assertEqual(len(mid), 2)                                      # a ring, not a disc: two pieces across the middle
        self.assertEqual(len([s for s in kp.ring_spans(cx, cy, 5, 0) if s[0] == cy]), 1)   # w 0: a disc

    def test_frame(self):
        lay = kp.ripple_layout("Bob", 1.0)
        f = kp.ripple_frame(0.1, lay)
        self.assertTrue(f["outer"] and f["inner"] and f["tag"])
        self.assertGreater(sum(b - a for _, a, b in f["outer"]), sum(b - a for _, a, b in f["inner"]))   # the white edge
        self.assertIsNone(kp.ripple_frame(0.75, lay)["tag"])               # the name goes first
        self.assertIsNone(kp.ripple_frame(kp.RIPPLE_S, lay))
        for y, a, b in f["outer"]:
            self.assertTrue(0 <= y < lay["h"] and 0 <= a < b <= lay["w"])

    def test_page_sonar_matches(self):
        p = read("moq-watch-lite.html")
        self.assertIn("animation:ptRing .48s cubic-bezier(.25,.7,.35,1) both;", p)   # RIPPLE_GROW_S
        self.assertIn(".pane .ptsonar i:nth-child(2) { animation-delay:.16s; }", p)   # RIPPLE_STAGGER_S
        self.assertIn(".pane .ptsonar i:nth-child(3) { animation-delay:.32s; }", p)
        self.assertIn("@keyframes ptRing { from { width:8px; height:8px; border-width:3px; opacity:.95; } to { width:60px; height:60px; border-width:1px; opacity:.05; } }", p)   # 2 x RIPPLE_R0 -> 2 x RIPPLE_R
        self.assertIn("PT_SONAR_MS = 800", p)
        self.assertEqual((kp.RIPPLE_GROW_S, kp.RIPPLE_STAGGER_S, kp.RIPPLE_S, kp.RIPPLE_R0, kp.RIPPLE_R), (0.48, 0.16, 0.8, 4, 30))
        self.assertIn("el.innerHTML = '<i></i><i></i><i></i><b></b><span class=\"nm\"></span>';", p)


# ---- the windows that draw on the sharer's screen ------------------------------------------------------------------------
class FakeKo(types.SimpleNamespace):
    """A stand-in for kastr_overlay's Win32 bindings: records the calls, creates nothing."""

    def __init__(self):
        import kastr_overlay as real
        super().__init__(AVAILABLE=True, pointer_spec=real.pointer_spec, hex_colorref=real.hex_colorref, ink_colorref=real.ink_colorref,
                         calls=[], _INSTANCES={}, CLASS_NAME="KastrShareOverlay", HWND_TOPMOST=-1,
                         SWP_NOSIZE=0x1, SWP_NOACTIVATE=0x10, SWP_SHOWWINDOW=0x40, SWP_NOOWNERZORDER=0x200,
                         WM_NCHITTEST=0x84, HTTRANSPARENT=-1, WM_MOUSEACTIVATE=0x21, MA_NOACTIVATE=3, WM_ERASEBKGND=0x14,
                         WM_CLOSE=0x10, WM_PAINT=0x0F, WM_TIMER=0x113, WM_APP_STOP=0x8001, MonitorFromPoint=None,
                         wt=types.SimpleNamespace(POINT=lambda x, y: (x, y)))
        self.n = 1000

    def __getattr__(self, name):   # any other binding: record it
        def fn(*a):
            self.calls.append((name,) + a)
            if name == "CreateWindowExW":
                self.n += 1
                return self.n
            return 1
        return fn

    def _dpi_of(self, hmon):
        return 144


class Windows(unittest.TestCase):
    def test_ripple_window_styles_and_place(self):
        ko = FakeKo()
        with mock.patch.dict(sys.modules, {"kastr_overlay": ko}):
            w = kp.WinRipples()
            w._host = 999
            w.add(500, 300, "Bob", "#e5533d")
            self.assertEqual(ko.calls[-1], ("PostMessageW", 999, kp.WM_APP_RIPPLE, 0, 0))   # only a post to its own host window
            self.assertEqual(w._handle("host", 999, kp.WM_APP_RIPPLE, 0, 0), 0)
            cw = [c for c in ko.calls if c[0] == "CreateWindowExW"]
            self.assertEqual(len(cw), 1)
            lay = kp.ripple_layout("Bob", 1.5)
            spec = ko.pointer_spec()
            self.assertEqual(cw[0][1:9], (spec["ex"], "KastrShareOverlay", "KASTR pointer ripple", spec["style"], 500 - lay["cx"], 300 - lay["cy"], lay["w"], lay["h"]))
            self.assertEqual(spec["ex"], 0x80000 | 0x20 | 0x8 | 0x80 | 0x08000000)   # LAYERED | TRANSPARENT | TOPMOST | TOOLWINDOW | NOACTIVATE
            h = ko.n
            self.assertIn(("SetLayeredWindowAttributes", h, spec["key"], 0, spec["lwa"]), ko.calls)
            self.assertIn(("SetWindowDisplayAffinity", h, 0x11), ko.calls)            # WDA_EXCLUDEFROMCAPTURE
            sp = [c for c in ko.calls if c[0] == "SetWindowPos"][0]
            self.assertEqual(sp[2:5], (-1, 500 - lay["cx"], 300 - lay["cy"]))         # HWND_TOPMOST, the rings round the click
            self.assertTrue(sp[7] & 0x10)                                              # SWP_NOACTIVATE
            self.assertIn(("SetTimer", 999, kp.RIPPLE_TIMER, 16, None), ko.calls)
            self.assertEqual(ko._INSTANCES[h], (w, "ripple"))
            # click-through, never activated
            self.assertEqual(w._handle("ripple", h, 0x84, 0, 0), -1)
            self.assertEqual(w._handle("ripple", h, 0x21, 0, 0), 3)
            # gone after RIPPLE_S, and the timer stops with the last one
            w._live[h]["t0"] -= kp.RIPPLE_S + 0.01
            w._handle("host", 999, 0x113, 0, 0)
            self.assertIn(("DestroyWindow", h), ko.calls)
            self.assertIn(("KillTimer", 999, kp.RIPPLE_TIMER), ko.calls)
            self.assertEqual(w._live, {})

    def test_never_on_this_platform_without_windows(self):
        import kastr_overlay
        if not kastr_overlay.AVAILABLE:
            self.assertFalse(kp.WinRipples().start())

    def test_sources(self):
        src = read("kastr_point.py")
        self.assertIn('ko.CreateWindowExW(spec["ex"], ko.CLASS_NAME, "KASTR pointer ripple", spec["style"]', src)
        self.assertIn('ko.SetLayeredWindowAttributes(h, spec["key"], 0, spec["lwa"])', src)
        self.assertIn('ko.SetWindowDisplayAffinity(h, spec["affinity"])', src)
        self.assertIn("ko.PointerOverlay(name, color)", src)      # a pointing person's arrow = the 0.21.80 controller's arrow
        # X11: input shape empty, override-redirect, the shared window's child for a window share, never listed as a window to share
        self.assertIn("shape(win, [], 2)   # ShapeInput: nothing -- clicks fall through", src)
        self.assertIn("sa.override_redirect = 1", src[src.index("class X11Ripples"):])
        self.assertIn('x.XStoreName(d.dpy, win, b"KASTR pointer ripple")', src)
        self.assertIn('title.startswith(("KASTR control", "KASTR pointer"))', read("kastr_x11.py"))
        with mock.patch.dict(sys.modules, {"kastr_x11": types.SimpleNamespace()}):
            self.assertEqual(kp.X11Board("screen://window/77").parent, 77)
            self.assertIsNone(kp.X11Board("screen://monitor/1").parent)
        self.assertTrue(kp.X11Board.in_capture)
        self.assertFalse(kp.WinBoard.in_capture)
        self.assertIn('"--hidden-import", "kastr_point"', read("build.py"))


# ---- pointer mode on the sharer's computer --------------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Cursor:
    def __init__(self):
        self.pos, self.down = (0, 0), set()

    def __call__(self):
        return self.pos, set(self.down)


def make(info=None):
    clock = Clock()
    b = rc.MockBackend(rects={WIN_URL: dict(WRECT)})
    share = {7: dict(info or {"url": WIN_URL, "live": True, "paused": False})}
    r = rc.RemoteControl(backend=b, share_info=lambda fid: share.get(int(fid)), clock=clock, caps=(True, "", "mock"), monitor=False)
    boards = []

    def factory(url):
        boards.append(kp.MockBoard(url))
        return boards[-1]
    cur = Cursor()
    pm = kp.PointMode(r, board_factory=factory, cursor=cur, clock=clock)
    pm._loop = lambda: None   # the sampler runs by hand here
    return pm, r, b, boards, cur, clock, share


class Mode(unittest.TestCase):
    def test_on_draw_off(self):
        pm, r, b, boards, cur, clock, share = make()
        o, c = pm.on(7, SHARE, True, "Alice", "#123456")
        self.assertEqual((c, o["cap"], o["feed"], o["scap"]), (200, 0, 7, 1))
        bd = boards[0]
        o, c = pm.draw(7, [{"id": "vic-dd44/P-v1", "n": "Vic", "c": "#e5533d", "x": 0.5, "y": 0.5, "on": 1},
                           {"id": "carol-cc33/P-c1", "n": "Carol", "c": "#00ff00", "x": 2, "y": 0.5, "on": 1}], [])
        self.assertEqual((c, o["pointers"]), (200, 2))
        self.assertIn(("ptr", "vic-dd44/P-v1", "Vic", "#e5533d", 420, 250, True), bd.events)
        self.assertIn(("ptr", "carol-cc33/P-c1", "Carol", "#00ff00", 0, 0, False), bd.events)   # off the picture: hidden
        n = len(bd.events)
        pm.draw(7, [{"id": "vic-dd44/P-v1", "n": "Vic", "c": "#e5533d", "x": 0.5, "y": 0.5, "on": 1},
                    {"id": "carol-cc33/P-c1", "n": "Carol", "c": "#00ff00", "x": 2, "y": 0.5, "on": 1}], [])
        self.assertEqual(len(bd.events), n)                                 # nothing moved: nothing redrawn
        # a click: one sonar where it was, in their colour, with their name -- once
        rip = [{"id": "vic-dd44/P-v1:3", "n": "Vic", "c": "#e5533d", "x": 0.25, "y": 1}]
        o, c = pm.draw(7, [{"id": "vic-dd44/P-v1", "n": "Vic", "c": "#e5533d", "x": 0.25, "y": 1, "on": 1}], rip)
        self.assertEqual(o["ripples"], 1)
        self.assertIn(("ripple", 260, 450, "Vic", "#e5533d"), bd.events)
        self.assertIn(("drop", "carol-cc33/P-c1"), bd.events)               # missing from the set: taken off the screen
        self.assertEqual(pm.draw(7, [], rip)[0]["ripples"], 0)              # the same click again: not drawn twice
        self.assertIn(("drop", "vic-dd44/P-v1"), bd.events)
        pm.off(7)
        self.assertTrue(bd.stopped)
        self.assertEqual(pm.draw(7, [], [])[1], 409)
        self.assertEqual(b.events, [])                                      # NOTHING reached the injector

    def test_cap_and_clean(self):
        pm, r, b, boards, cur, clock, share = make()
        pm.board_factory = lambda url: types.SimpleNamespace(in_capture=True, stop=lambda: None)
        self.assertEqual(pm.on(7, SHARE)[0]["cap"], 1)                       # X11: the pointers are in the picture
        many = [{"id": "h%02d-aaaa/P" % i, "n": "<b>" * 20, "c": "red", "x": 0.1, "y": 0.1, "on": 1} for i in range(30)]
        cl = kp.clean_pointers(many + [{"id": "bad id!", "x": 0, "y": 0}])
        self.assertEqual(len(cl), kp.PT_MAX)
        self.assertEqual((len(cl[0]["n"]), cl[0]["c"]), (28, "#009fda"))
        self.assertEqual(kp.clean_ripples([{"id": "x:1", "x": 1.5, "y": 0}, {"id": "x:2", "x": 0.5, "y": 0.5}])[0]["id"], "x:2")

    def test_lease_and_the_share(self):
        pm, r, b, boards, cur, clock, share = make()
        pm.on(7, SHARE)
        clock.t += kp.PT_LEASE_S - 1
        pm.draw(7, [], [])                                                  # a draw renews the lease too
        clock.t += kp.PT_LEASE_S - 1
        self.assertEqual(pm.check(), [])
        clock.t += 2
        self.assertEqual(pm.check(), [(7, "timeout")])
        self.assertTrue(boards[0].stopped)
        pm.on(7, SHARE)
        share[7]["paused"] = True
        self.assertEqual(pm.check(), [(7, "paused")])
        self.assertEqual(pm.on(7, SHARE)[1], 409)                           # a pause card takes no pointers
        share[7]["paused"] = False
        pm.on(7, SHARE)
        share[7]["url"] = "screen://window/9999"
        self.assertEqual(pm.check(), [(7, "retarget")])
        share[7]["url"] = WIN_URL
        pm.on(7, SHARE)
        rc.share_gone(7, "share") if rc._RC is None else None
        pm.share_gone(7, "share")
        self.assertEqual(pm.status()["ended"]["7"], "share")
        share[7]["live"] = False
        self.assertEqual(pm.on(7, SHARE)[1], 409)
        self.assertEqual(pm.on("x", SHARE)[1], 400)
        self.assertEqual(b.events, [])

    def test_only_native_shares(self):
        pm, r, b, boards, cur, clock, share = make({"url": "rtsp://cam/1", "live": True, "paused": False})
        self.assertEqual(pm.on(7, SHARE)[1], 409)

    def test_the_sharers_own_pointer_and_clicks(self):
        pm, r, b, boards, cur, clock, share = make()
        pm.on(7, SHARE, True, "Alice", "#123456")
        bd = boards[0]
        cur.pos = (420, 250)
        uv = kp.to_uv((420, 250), WRECT)
        self.assertEqual(uv, [0.4992, 0.4988, 1])
        pm.poll()
        self.assertEqual(pm.take(), {"7": {"s": uv, "k": [], "cap": 0}})
        pm.poll()
        self.assertIsNone(pm.take())                                        # still: nothing
        cur.down = {0}
        pm.poll()                                                           # a press inside the surface: a click + my own sonar
        self.assertEqual(pm.take()["7"]["k"], [[0.4992, 0.4988, 0]])
        self.assertEqual(bd.events[-1], ("ripple", 420, 250, "Alice", "#123456"))
        pm.poll()                                                           # held: not a second click
        self.assertIsNone(pm.take())
        cur.down = set()
        pm.poll()
        cur.pos, cur.down = (5, 5), {2}                                     # a click OUTSIDE the shared window: none
        pm.poll()
        self.assertEqual(pm.take()["7"], {"s": [0.0, 0.0, 0], "k": [], "cap": 0})
        cur.down = set()
        pm.poll()
        pm.on(7, SHARE, False, "Alice", "#123456")                         # "Show my clicks" off: the click travels, no sonar here
        cur.pos, cur.down = (260, 150), {0}
        n = len(bd.events)
        pm.poll()
        self.assertEqual(pm.take()["7"]["k"], [kp.to_uv((260, 150), WRECT)[:2] + [0]])
        self.assertEqual(len(bd.events), n)
        cur.down = set()
        pm.poll()
        b.warp = rc.WarpState()
        b.warp.begin((0, 0), (300, 300))                                    # a controller's warp-click borrows the cursor
        cur.down = {0}
        pm.poll()
        self.assertIsNone(pm.take())
        self.assertEqual([e for e in b.events if e[0] != "pointer"], [])   # read, never moved

    def test_no_overlay_on_wayland_viewers_draw(self):
        fake = types.SimpleNamespace(available=lambda: (False, "wayland"))
        with mock.patch.object(kp, "LINUX", True), mock.patch.object(kp, "WINDOWS", False), mock.patch.dict(sys.modules, {"kastr_x11": fake}), mock.patch.dict(os.environ, {"KASTR_RC_MOCK": ""}):
            bd = kp.make_board("screen://monitor/1")
            self.assertIsInstance(bd, kp.NullBoard)
            self.assertFalse(bd.in_capture)                                 # nothing on the sharer's screen: every viewer draws them
            fake.available = lambda: (False, "no-xtest")                    # drawing needs X11, not XTest
            with mock.patch.object(kp, "X11Board", lambda url, log=None: "x11"):
                self.assertEqual(kp.make_board("screen://monitor/1"), "x11")
        pm, r, b, boards, cur, clock, share = make()
        pm.board_factory = lambda url: kp.NullBoard(url)
        o, c = pm.on(7, SHARE)
        self.assertEqual((c, o["cap"], o["overlay"]), (200, 0, False))

    def test_physical_presses_however_short(self):
        # X11: the raw-event monitor's presses (a click shorter than a sample, never an XTEST device) are the clicks
        pm, r, b, boards, cur, clock, share = make()
        pm.on(7, SHARE, True, "Alice", "#123456")
        raw = []
        pm._cursor = lambda: ((420, 250), set(), [raw.pop(0) for _ in range(len(raw))])
        pm.poll()
        pm.take()
        raw += [0, 2]                                                       # two presses between two samples; nothing held now
        pm.poll()
        self.assertEqual(pm.take()["7"]["k"], [[0.4992, 0.4988, 0], [0.4992, 0.4988, 2]])
        self.assertEqual([e[0] for e in boards[0].events].count("ripple"), 2)
        pm.poll()
        self.assertIsNone(pm.take())
        src = read("kastr_point.py")
        self.assertIn("m = kx.RawMonitor(self._on_raw, None, display)", src)
        self.assertIn("if self.u32.GetAsyncKeyState(vk) & 0x8001:", src)

    def test_the_sampler_thread_ends_with_the_last_mode(self):
        pm, r, b, boards, cur, clock, share = make()
        del pm._loop
        pm.clock = time.monotonic
        pm.on(7, SHARE)
        th = pm._th
        self.assertTrue(th.is_alive())
        cur.pos = (420, 250)
        for _ in range(50):
            if pm.take() is not None:
                break
            time.sleep(0.02)
        pm.off()
        th.join(2)
        self.assertFalse(th.is_alive())


class NothingInjected(unittest.TestCase):
    def test_no_input_path(self):
        src = read("kastr_point.py")
        for banned in ("SendInput", "keybd_event", "mouse_event", "SetCursorPos", "XTestFake", "SendMessage", ".inject(", ".button(",
                       ".key(", "XWarpPointer", "Mpx(", "Injector("):
            self.assertNotIn(banned, src)
        self.assertEqual(src.count("PostMessageW("), 2)                     # both to its OWN hidden window
        self.assertIn("ko.PostMessageW(h, WM_APP_RIPPLE, 0, 0)", src)
        self.assertIn("ko.PostMessageW(h, ko.WM_APP_STOP, 0, 0)", src)
        self.assertEqual(src.count("h = self._host"), 2)
        self.assertEqual(read("kastr_rc.py").count(".SendInput("), 1)      # the injector's one call site is unchanged

    def test_pt_ops_never_reach_inject(self):
        pm, r, b, boards, cur, clock, share = make()
        old = kp._PM
        kp._PM = pm
        try:
            with mock.patch.object(r, "inject", side_effect=AssertionError("pointer mode injected")):
                o, c = rc._dispatch(r, {"op": "pt-on", "feed": 7, "share": SHARE, "own": True, "name": "Alice"})
                self.assertEqual(c, 200, o)
                o, c = rc._dispatch(r, {"op": "pt-draw", "feed": 7, "p": [{"id": "v/P", "n": "Vic", "x": 0.5, "y": 0.5, "on": 1}],
                                        "r": [{"id": "v/P:1", "n": "Vic", "x": 0.5, "y": 0.5}], "ev": [{"t": "d", "b": 0, "x": 0.5, "y": 0.5}]})
                self.assertEqual((c, o["ripples"]), (200, 1))
                self.assertEqual(rc._dispatch(r, {"op": "pt-status"})[0]["feeds"]["7"]["pointers"], 1)
                self.assertEqual(rc._dispatch(r, {"op": "pt-inject"})[1], 400)
                self.assertEqual(rc._dispatch(r, {"op": "pt-off", "feed": 7})[1], 200)
            self.assertEqual(b.events, [])
            self.assertIsNone(r.grant)                                      # no control grant came of it
            self.assertTrue(r.caps()["point"])
        finally:
            kp._PM = old

    def test_websocket_carries_pointer_mode(self):
        pm, r, b, boards, cur, clock, share = make()
        old_pm, old_rc, old_local = kp._PM, rc._RC, kr.is_local
        kp._PM, rc._RC = pm, r
        kr.is_local = lambda h: True
        srv, cli = socket.socketpair()

        class H:
            command, path = "GET", "/api/rc/ws"
            headers = {"Upgrade": "websocket", "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==", "Origin": "http://127.0.0.1:8001"}
            connection = srv
            close_connection = False

            def send_error(self, c):
                raise AssertionError(c)
        class Bridge:   # bridge_info: feed 7 is a live native window share
            _pubs = {7: types.SimpleNamespace(paused=False, broadcast=SHARE)}

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
            buf = b""

            def send(obj):
                data = json.dumps(obj).encode()
                m = b"\x11\x22\x33\x44"
                cli.sendall(bytes([0x81, 0x80 | 126]) + len(data).to_bytes(2, "big") + m + bytes(c ^ m[i & 3] for i, c in enumerate(data)))

            def recv_until(pred, limit=3.0):
                nonlocal buf
                t0 = time.time()
                while time.time() - t0 < limit:
                    fr, buf = rc.ws_parse(buf)
                    for _, _, p in fr:
                        d = json.loads(p)
                        if pred(d):
                            return d
                    try:
                        buf += cli.recv(65536)
                    except socket.timeout:
                        pass
                return None
            send({"op": "pt-on", "feed": 7, "share": SHARE, "own": True, "name": "Alice", "color": "#123456"})
            rep = recv_until(lambda d: d.get("re") == "pt-on")
            self.assertEqual((rep["code"], rep["feed"]), (200, 7))
            cur.pos, cur.down = (420, 250), {0}
            pm.poll()                                                       # the sampler's beat (by hand here)
            got = recv_until(lambda d: "pt" in d)
            self.assertEqual(got["pt"]["7"]["k"], [[0.4992, 0.4988, 0]])
            send({"op": "pt-draw", "feed": 7, "p": [{"id": "v/P", "n": "Vic", "c": "#e5533d", "x": 0.5, "y": 0.5, "on": 1}], "r": []})
            self.assertEqual(recv_until(lambda d: d.get("re") == "pt-draw")["pointers"], 1)
            cli.sendall(bytes([0x88, 0x80]) + b"\x00\x00\x00\x00")
            th.join(2)
            self.assertFalse(th.is_alive())
            self.assertEqual(b.events, [])
        finally:
            kp._PM, rc._RC, kr.is_local = old_pm, old_rc, old_local
            srv.close()
            cli.close()


# ---- the page ------------------------------------------------------------------------------------------------------------
def may_point(x, me, opt_out=False, note_age=None):
    """The page's ptMayPoint, mirrored (x = the share's entry in its sharer's room.json rc list)."""
    if not x or not x.get("pv") or opt_out:
        return False
    if me in (x.get("pb") or []):
        return False
    return bool(x.get("pe")) or me in (x.get("pa") or []) or (note_age is not None and note_age < 8000)


def sonar_due(r_t, L, fleet, now, arrived, on_clock):
    """The page's ptPaint: a click shows when the picture shows its moment (fleet clock), or L after it arrived."""
    return r_t + L <= fleet if on_clock else arrived + max(0, L - 30) <= now


class Page(unittest.TestCase):
    def test_who_may_point(self):
        me = "vic-dd44/P-v1"
        self.assertFalse(may_point({"p": SHARE}, me))                                       # an older sharer: no pointing
        self.assertFalse(may_point({"pv": 1}, me))                                          # nobody allowed yet
        self.assertTrue(may_point({"pv": 1, "pa": [me]}, me))                               # asked and allowed
        self.assertTrue(may_point({"pv": 1, "pe": 1}, me))                                  # Let everyone point
        self.assertFalse(may_point({"pv": 1, "pe": 1, "pb": [me]}, me))                     # ... taken off by the sharer
        self.assertFalse(may_point({"pv": 1, "pe": 1}, me, opt_out=True))                   # ... I stopped myself
        self.assertTrue(may_point({"pv": 1}, me, note_age=500))                             # the allow note, before room.json says so
        self.assertFalse(may_point({"pv": 1}, me, note_age=9000))
        p = read("moq-watch-lite.html")
        self.assertIn("return !!x.pe || (Array.isArray(x.pa) && x.pa.includes(me)) || (ptNote.has(name) && Date.now() - ptNote.get(name) < PT_GRACE_MS);", p)
        self.assertIn("PT_GRACE_MS = 8000", p)
        self.assertIn('return Object.assign({ pv: 1 }, m && m.on ? { pt: 1 } : {}, m && m.everyone ? { pe: 1 } : {},', p)
        self.assertIn("const ptCanAsk = () => joinState === \"joined\" && CHANNEL !== LOBBY && authSecured && !!authTokens?.member && !pbOld;   // anyone in the room (viewers too)", p)

    def test_transport(self):
        p = read("moq-watch-lite.html")
        # the pointing person: pt.json on their OWN member broadcast, top priority, short retention
        self.assertIn('["room.json", "chat.json", "pt.json"], { tracks: { "pt.json": { priority: 255, maxAge: 2000 } } });', p)
        self.assertIn("const o = opts?.tracks?.[name] || opts; try { tracks[name] = bp.createTrack(name, { priority: o?.priority ?? STATE_PRIORITY, maxAge: o?.maxAge ?? STATE_LAT_MS }); } catch {} }", p)
        self.assertIn('roomState.set("pt.json", { v: 1, s: ptMe.share, t: f, x: ptMe.x, y: ptMe.y, on: ptMe.on && ptMayPoint(ptMe.share) ? 1 : 0, k: ptMe.k, n:', p)
        self.assertIn('case "pt": {       // 0.21.83: the shares I point on (their sharer subscribes to my pt.json)', p)
        # the sharer: one subscription per allowed person (PT_MAX), drawn by its KASTR, republished as ONE pts.json
        self.assertIn('h.sub = stateSubscribe(connection, mp, "pt.json", "snapshot", (v) => ptPtrArrive(m, h, v), RC_PRIO);', p)
        self.assertIn("for (const [, key, mp] of rows.slice(0, PT_MAX)) want.set(key, mp);", p)
        self.assertIn('ptLocal({ op: "pt-draw", feed: m.feed,', p)
        self.assertIn('try { rcState().set("pts.json", { v: 1, t: f, s }); } catch {}', p)
        self.assertIn('(rcCtl || rcGrant || ptAnyOn()) && joinState === "joined"', p)
        self.assertIn("ptWantApply(path, v.pt);     // 0.21.83: the shares they point on", p)
        self.assertIn("ptWant.delete(path);     // 0.21.83", p)
        # every viewer: the sharer alone
        self.assertIn('h.sub = stateSubscribe(connection, path, "pts.json", "snapshot", (v) => ptViewArrive(h, v), RC_PRIO);', p)
        self.assertIn('if (list.some((x) => x.pt && tiles.has(x.p))) want.add(pp[0] + "/" + pp[1] + "/~rc/" + pp[3]);', p)
        # what the viewers draw: never my own mouse, never one already in the picture, the sharer's name beside their cursor
        self.assertIn("if (!self && (cap || (p.h === HOSTNAME1 && p.pe === me))) continue;   // in the picture already (X11) / my own mouse", p)
        self.assertIn("if (self && rcPtrs.has(share)) continue;   // remote control draws the sharer's pointer itself (ptr.json)", p)
        self.assertIn('el.classList.toggle("tagonly", self && !!p.cap);', p)
        self.assertIn("if ((r.h === HOSTNAME1 && r.pe === me) || se.cap) { h.shown.add(id); continue; }", p)
        self.assertIn("const due = onClock ? Number(r.t) + L <= fleet : smp.at + Math.max(0, L - 30) <= now;", p)
        self.assertIn("const L = rcPtrDelay(t), pk = rcPtrPick(h, L);", p)
        # the notes
        self.assertIn('if (/^p(ask|allow|deny|stop)$/.test(String(it.rc))) { ptArrive(it); return; }   // 0.21.83: pointer mode', p)
        self.assertIn('rcSend({ kind: "pask", to: x.host, share: name, id: rcid, peer: statePeer(),', p)

    def test_sonar_alignment(self):
        # a click that reached the sharer's screen at fleet 10 000 shows on a tile 650 ms behind at 10 650, not before
        self.assertFalse(sonar_due(10_000, 650, 10_600, 0, 0, True))
        self.assertTrue(sonar_due(10_000, 650, 10_650, 0, 0, True))
        self.assertTrue(sonar_due(10_000, 100, 10_150, 0, 0, True))          # an instant player: almost at once
        self.assertFalse(sonar_due(1, 650, 0, 50_500, 50_000, False))        # clocks disagree: L - 30 after it arrived
        self.assertTrue(sonar_due(1, 650, 0, 50_620, 50_000, False))

    def test_words_and_menus(self):
        p = read("moq-watch-lite.html")
        self.assertIn('" asks to point on " + (mine.surface === "screen" ? "your screen" : "your window") + ". They can\\u2019t click or type on your computer.";   // Kenton\'s words', p)
        self.assertIn('<button type="button" class="ghost ptno">Deny</button><button type="button" class="ghost ptall">Let everyone point</button><button type="button" class="ptyes">Allow</button>', p)
        self.assertIn('{ const pi = ptMenuItem(name); if (pi) items.push(pi); }   // 0.21.83: Point on this screen (anyone in the room)', p)
        self.assertIn('if (String(v).startsWith("pnt")) { ptMenuPick(name, v); return; }   // 0.21.83: pointer mode', p)
        self.assertIn('for (const it of ptShareItems(CHANNEL + "/" + hangName(ref.name))) items.push(it);', p)
        self.assertIn('ptShareMenuPick(CHANNEL + "/" + hangName(ref.name), v);', p)
        self.assertIn('sw: !!(m?.everyone), label: "Let everyone point"', p)   # 0.21.96: switches, not tick glyphs
        self.assertIn('own.append(ptSw(m.own), "Show my clicks");', p)
        self.assertIn('b.innerHTML = icon("mouse") + "<span>Point</span>";', p)
        self.assertIn("#stage .pane.ptable.mainstage .pptbtn { display:inline-flex; }", p)
        self.assertIn('const ptOwnPref = () => { try { return localStorage.getItem("kastr.pt.own") !== "0"; } catch { return true; } };', p)   # my clicks: on by default
        # a phone's tap is a sonar too; a click on the tile's own buttons is not
        self.assertIn('if (!may() || (e.pointerType === "mouse" && e.button !== 0)) return;', p)
        self.assertIn('if (e.target?.closest?.("button, a, input, select, textarea, .pchev, .prcbtn, .pptbtn, .menu, .popcard")) return;', p)
        self.assertEqual(p.count("\r\n"), p.count("\n"))                    # still CRLF

    def test_limits_match(self):
        p = read("moq-watch-lite.html")
        self.assertIn("const PT_MAX = 12, PT_HZ_MS = 33,", p)
        self.assertEqual((kp.PT_MAX, kp.PT_HZ), (12, 30))
        self.assertIn("PT_ON_MS = 2000", p)
        self.assertLess(2000 * 3, kp.PT_LEASE_S * 1000)                     # three missed renewals before the lease lapses


if __name__ == "__main__":
    unittest.main()
