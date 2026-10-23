# -*- coding: utf-8 -*-
"""v0.21.79 REMOTE CONTROL. Kenton (2026-10-22): "I want to add the capability to request remote control when someone is
sharing their desktop and a prompt to allow that user to take control of your machine. Local input always overrides remote
input." Decided: mouse + keyboard + clipboard text on a NATIVE screen / window / tab share of the KASTR app; only publishers
and admins of that room may ask (the relay enforces it); the sharer clicks Allow every time; a grant lasts until it is stopped
(Stop control, Ctrl+Alt+Space, the share stopping or pausing, either side leaving or going quiet ~10 s); physical input on the
sharer's computer held remote input off for ~3 s -- until 0.21.80 (two pointers: the controller's moves move only their own
arrow, local input never pauses remote input -- tests/test_release_0_21_80_two_pointers.py; the expectations below follow).

What is proven here (loopback, no network, NO real input anywhere):
  * the relay's notes (kastr_relay.rc_send): role check, sender in the share's room, ask -> the share's owner, only the sharer
    answers, either side stops, rate limits + the cool-down after a "no", spoke -> hub -> spokes delivery, stale notes;
  * the injector (kastr_rc.RemoteControl on the recording MockBackend): grant lifecycle, refusals (no grant, wrong id, wrong
    source, share gone / paused / re-pointed, busy), the lease, coordinates (normalised -> the surface's pixels, clipped,
    outside dropped, KASTR's own bar never clicked, a covered window raised), the local-input hold timing, held keys released,
    clipboard caps and "never outside a grant";
  * Windows SendInput ENCODING only (INPUT structs, scan codes, absolute virtual-desktop coordinates) -- SendInput is never
    called; the low-level hooks' physical / injected decisions and the Ctrl+Alt+Space tracker as pure functions;
  * the loopback API's guards (local only, same origin, the custom header), the bar's buttons, the page and build wiring.
Real XTest injection + XInput2 local override run in the WSL lab against a virtual X server (scratchpad v02179/RC)."""
import ctypes
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_rc as rc  # noqa: E402
import kastr_x11 as x11  # noqa: E402

A, B, C, V = "alice-aa11", "bob-bb22", "carol-cc33", "vic-dd44"   # A shares; B and C publish; V views
SHARE = "alpha/%s/alice/screen.hang" % A


def page():
    with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8", newline="") as f:
        return f.read()


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return f.read()


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

    def ask(self, t, rcid="abcdef12", to=A, share=SHARE, **kw):
        return self.rc(t, kind="ask", to=to, share=share, id=rcid, peer="P-x1", by="Bob", label="Screen 1", **kw)

    def inbox(self, t):
        o, c = self.svc.people_api({"op": "beat"}, "Bearer " + t, "10.0.0.7")
        assert c == 200, o
        return [x for x in o["inbox"] if x.get("kind") == "rc"]


class RelayRoles(RelayBase):
    def test_publisher_asks_and_the_sharer_gets_it(self):
        ta, tb = self.tok(A), self.tok(B)
        o, c = self.ask(tb)
        self.assertEqual((c, o["ok"], o["id"]), (200, True, "abcdef12"))
        got = self.inbox(ta)
        self.assertEqual(len(got), 1)
        it = got[0]
        self.assertEqual((it["rc"], it["rcid"], it["from"], it["share"], it["room"], it["by"], it["peer"], it["surface"]),
                         ("ask", "abcdef12", B, SHARE, "alpha", "Bob", "P-x1", "screen"))
        self.assertEqual(self.inbox(ta), [])           # taken once
        self.assertEqual(self.inbox(tb), [])           # nothing for the asker

    def test_viewer_never_asks(self):
        o, c = self.ask(self.tok(V, "view-1"))
        self.assertEqual(c, 403)
        self.assertIn("only publishers and admins", o["error"])
        self.assertEqual(self.inbox(self.tok(A)), [])

    def test_admin_may_ask(self):
        o, c = self.ask(self.tok(C, "adm-1"))
        self.assertEqual(c, 200, o)
        self.assertTrue(kr.rc_can_ask(kr.verify_token(self.tok(C, "adm-1"), self.svc.key), "alpha", C))

    def test_rc_can_ask_claims(self):
        cl = lambda t: kr.verify_token(t, self.svc.key)
        self.assertTrue(kr.rc_can_ask(cl(self.tok(B)), "alpha", B))
        self.assertFalse(kr.rc_can_ask(cl(self.tok(V, "view-1")), "alpha", V))
        self.assertFalse(kr.rc_can_ask(cl(self.tok(B)), "beta", B))       # a publisher of alpha is nobody in beta
        self.assertFalse(kr.rc_can_ask(cl(self.tok(B, room="main")), "main", B))   # never the Lobby
        self.assertFalse(kr.rc_can_ask({"put": ["alpha/" + B]}, "alpha", ""))

    def test_sender_must_be_in_the_share_room(self):
        tb_beta = self.tok(B, room="beta")
        o, c = self.ask(tb_beta)                      # a token for beta asking about alpha's share
        self.assertEqual(c, 403)
        self.assertEqual(o["error"], "that share is not in your room")
        o, c = self.ask(self.tok(B, room="main"))     # the Lobby
        self.assertEqual(c, 403)

    def test_ask_goes_to_the_owner_of_the_share(self):
        o, c = self.ask(self.tok(B), to=C)            # C does not own alice's share
        self.assertEqual(c, 400)
        self.assertEqual(o["error"], "ask the person whose share it is")
        o, c = self.ask(self.tok(B), share="alpha/%s/x.mp4" % A)
        self.assertEqual(c, 400)                      # not a share path
        o, c = self.ask(self.tok(B), rcid="X!")
        self.assertEqual(c, 400)
        o, c = self.ask(self.tok(A), to=A)            # not yourself
        self.assertEqual(c, 400)

    def test_only_the_sharer_answers_and_either_side_stops(self):
        ta, tb, tc = self.tok(A), self.tok(B), self.tok(C)
        self.assertEqual(self.ask(tb)[1], 200)
        o, c = self.rc(tc, kind="allow", to=B, share=SHARE, id="abcdef12")   # C forges an allow for alice's share
        self.assertEqual(c, 403)
        self.assertEqual(o["error"], "only the person sharing answers")
        o, c = self.rc(ta, kind="allow", to=B, share=SHARE, id="abcdef12", peer="P-alice")
        self.assertEqual(c, 200, o)
        got = self.inbox(tb)
        self.assertEqual([(x["rc"], x["from"], x["peer"]) for x in got], [("allow", A, "P-alice")])
        o, c = self.rc(tc, kind="stop", to=B, share=SHARE, id="abcdef12")    # a third party cannot stop it either
        self.assertEqual(c, 403)
        self.assertEqual(self.rc(tb, kind="stop", to=A, share=SHARE, id="abcdef12", why="released")[1], 200)
        self.assertEqual(self.rc(ta, kind="stop", to=B, share=SHARE, id="abcdef12", why="bar")[1], 200)
        self.assertEqual([(x["rc"], x["why"]) for x in self.inbox(ta)], [("ask", ""), ("stop", "released")])
        self.assertEqual([(x["rc"], x["why"]) for x in self.inbox(tb)], [("stop", "bar")])

    def test_unknown_why_is_dropped(self):
        ta, tb = self.tok(A), self.tok(B)
        self.assertEqual(self.rc(ta, kind="deny", to=B, share=SHARE, id="abcdef12", why="<script>")[1], 200)
        self.assertEqual(self.inbox(tb)[0]["why"], "")

    def test_viewer_cannot_answer_or_ask_by_forging_the_body(self):
        tv = self.tok(V, "view-1")
        # a viewer claims to be someone else in the body: the host comes from the token only
        o, c = self.rc(tv, kind="ask", to=A, share=SHARE, id="abcdef12", **{"from": B})
        self.assertEqual(c, 403)
        o, c = self.rc(tv, kind="allow", to=B, share=SHARE, id="abcdef12")
        self.assertEqual(c, 403)


class RelayRates(RelayBase):
    def test_three_asks_a_minute_per_pair(self):
        tb = self.tok(B)
        for i in range(3):
            self.assertEqual(self.ask(tb, rcid="abcdef1%d" % i)[1], 200)
        o, c = self.ask(tb, rcid="abcdef19")
        self.assertEqual(c, 429)
        self.assertTrue(o["retryAfter"] > 0)
        # a minute later the pair may ask again
        pl = self.svc._pl()
        pl.rcrate = {k: [t - 61 for t in v] for k, v in pl.rcrate.items()}
        self.assertEqual(self.ask(tb, rcid="abcdef20")[1], 200)

    def test_ten_asks_a_minute_in_all(self):
        tb = self.tok(B)
        others = ["p%d-%04x" % (i, i) for i in range(12)]
        n = 0
        for i, h in enumerate(others):
            o, c = self.ask(tb, rcid="abcdef%02d" % i, to=h, share="alpha/%s/x/screen.hang" % h)
            if c == 200:
                n += 1
            else:
                self.assertEqual(c, 429)
        self.assertEqual(n, kr.RC_ASK_RATE_ALL[0])

    def test_a_no_holds_the_asker_off(self):
        ta, tb = self.tok(A), self.tok(B)
        self.assertEqual(self.ask(tb)[1], 200)
        self.assertEqual(self.rc(ta, kind="deny", to=B, share=SHARE, id="abcdef12", why="no")[1], 200)
        o, c = self.ask(tb, rcid="abcdef13")
        self.assertEqual(c, 429)
        self.assertIn("they said no", o["error"])
        pl = self.svc._pl()
        pl.rcdeny = {k: v - kr.RC_DENY_COOL - 1 for k, v in pl.rcdeny.items()}
        self.assertEqual(self.ask(tb, rcid="abcdef14")[1], 200)
        self.assertEqual(self.svc.personal_sweep(), [])   # the sweep forgets old rates without trouble

    def test_stale_notes_are_not_shown(self):
        ta, tb = self.tok(A), self.tok(B)
        self.assertEqual(self.ask(tb)[1], 200)
        later = time.time() + kr.RC_INBOX_TTL + 1
        self.assertEqual([x for x in self.svc._p_inbox_take(A, later) if x.get("kind") == "rc"], [])


class RelayFleet(RelayBase):
    def test_hub_takes_a_spoke_note_and_hands_it_to_every_spoke(self):
        item = {"kind": "rc", "rc": "ask", "rcid": "abcdef12", "room": "alpha", "share": SHARE, "from": B, "peer": "P-x1", "by": "Bob"}
        o, c = self.svc._p_fed("prc", {"op": "prc", "vouch": "publisher", "to": A, "item": item})
        self.assertEqual(c, 403)                      # the spoke must vouch for a member
        o, c = self.svc._p_fed("prc", {"op": "prc", "vouch": "member", "to": A, "item": dict(item, share="beta/%s/x.hang" % A)})
        self.assertEqual(c, 400)                      # the share's room is not the note's room
        o, c = self.svc._p_fed("prc", {"op": "prc", "vouch": "member", "to": A, "item": item})
        self.assertEqual(c, 200, o)
        self.assertEqual([x["rc"] for x in self.inbox(self.tok(A))], ["ask"])   # the hub's own pages
        feed = self.svc.personal_feed()
        self.assertTrue(any(x["to"] == A and x["item"]["kind"] == "rc" for x in feed["inbox"]))
        # a spoke applies the hub's long-poll: the note waits there for alice's next beat, once
        st2 = kr.AuthStore(tempfile.mkdtemp())
        st2.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st2)
        try:
            spoke.personal_mirror_apply({"personal": feed})
            spoke.personal_mirror_apply({"personal": feed})   # the same long-poll answer again: not twice
            got = [x for x in spoke._p_inbox_take(A, time.time()) if x.get("kind") == "rc"]
            self.assertEqual([(x["rc"], x["from"], x["share"]) for x in got], [("ask", B, SHARE)])
            # a forged item in a long-poll answer is dropped
            bad = {"open": [], "rooms": {}, "away": {}, "inbox": [{"seq": 9, "to": A, "item": dict(item, rcid="zzzzzzz!", rc="allow")}]}
            spoke.personal_mirror_apply({"personal": bad})
            self.assertEqual([x for x in spoke._p_inbox_take(A, time.time()) if x.get("kind") == "rc"], [])
        finally:
            spoke.close()

    def test_spoke_forwards_with_its_vouch(self):
        calls = []
        self.svc._p_spoke = lambda: True
        self.svc._hub_fed = lambda body, timeout=6: (calls.append(body) or ({"ok": True}, 200))
        o, c = self.ask(self.tok(B))
        self.assertEqual((c, o["ok"], o["id"]), (200, True, "abcdef12"))
        self.assertEqual((calls[0]["op"], calls[0]["vouch"], calls[0]["to"], calls[0]["item"]["from"], calls[0]["item"]["rc"]),
                         ("prc", "member", A, B, "ask"))
        self.svc._hub_fed = lambda body, timeout=6: ({"ok": False, "error": "bad room"}, 400)   # a hub older than 0.21.79
        o, c = self.ask(self.tok(B), rcid="abcdef13")
        self.assertEqual(c, 501)
        self.svc._hub_fed = lambda body, timeout=6: None
        o, c = self.ask(self.tok(B), rcid="abcdef14")
        self.assertEqual((c, o.get("hubDown")), (503, True))

    def test_rc_item_clean(self):
        ok = {"kind": "rc", "rc": "stop", "rcid": "abcdef12", "room": "alpha", "share": SHARE, "from": B, "why": "bar", "by": "<b>Bob</b>"}
        c = kr.rc_item_clean(ok)
        self.assertEqual((c["id"], c["by"], c["why"]), ("rc-stop-abcdef12-" + B, "bBob/b", "bar"))
        for bad in (dict(ok, rc="grant"), dict(ok, room="beta"), dict(ok, **{"from": "x"}), dict(ok, share="alpha/" + A + "/a.mp4"),
                    dict(ok, peer="bad peer!"), dict(ok, kind="invite"), "x"):
            self.assertIsNone(kr.rc_item_clean(bad), bad)


# ---- the injector ---------------------------------------------------------------------------------------------------------
WIN_URL, MON_URL = "screen://window/4242", "screen://monitor/1"
WRECT, MRECT = {"x": 100, "y": 50, "w": 640, "h": 400}, {"x": -1920, "y": 0, "w": 1920, "h": 1080}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeUI:
    def __init__(self, rect=None):
        self.shown, self.cleared, self.bar = [], [], rect

    def show(self, feed, url, mode, label, buttons, on_button, rect_fn=None):
        self.shown.append((feed, mode, label, [k for k, _ in buttons]))
        self.on_button = on_button
        return True

    def clear(self, feed):
        self.cleared.append(feed)

    def rect(self, feed):
        return self.bar


class Injector(unittest.TestCase):
    RCID = "abcdefgh1234"

    def setUp(self):
        self.clock = Clock()
        self.b = rc.MockBackend(rects={WIN_URL: dict(WRECT), MON_URL: dict(MRECT)})
        self.share = {7: {"url": WIN_URL, "live": True, "paused": False}, 8: {"url": MON_URL, "live": True, "paused": False}}
        self.ui = FakeUI()
        self.r = rc.RemoteControl(backend=self.b, share_info=lambda fid: self.share.get(int(fid)), clock=self.clock,
                                  caps=(True, "", "mock"), ui=self.ui, monitor=False)

    def grant(self, feed=7, rcid=None, src=B):
        o, c = self.r.start(rcid or self.RCID, src, "Bob", feed, "alpha/%s/alice/w.hang" % A)
        self.assertEqual(c, 200, o)
        return o

    def put(self, events, rcid=None, src=B):
        return self.r.inject(rcid or self.RCID, src, events)

    def ev(self, kind):
        return [e for e in self.b.events if e[0] == kind]

    def test_refuses_without_a_grant(self):
        st, c = self.put([{"t": "d", "b": 0, "x": 0.5, "y": 0.5}])
        self.assertEqual((c, st["ok"], st["error"]), (403, False, "no grant"))
        self.assertEqual(self.b.events, [])

    def test_refuses_a_wrong_grant_or_source(self):
        self.grant()
        self.assertEqual(self.put([{"t": "m", "x": 0.5, "y": 0.5}], rcid="zzzzzzzz9999")[1], 403)
        st, c = self.put([{"t": "m", "x": 0.5, "y": 0.5}], src=C)
        self.assertEqual((c, st["error"]), (403, "not the controller this grant is for"))
        self.assertEqual(self.b.events, [])
        self.assertEqual(self.put([{"t": "m", "x": 0.5, "y": 0.5}])[1], 200)
        self.assertEqual(self.b.events, [("pointer", 420, 250, True)])   # 0.21.80: the controller's own arrow

    def test_grant_needs_a_live_native_share(self):
        o, c = self.r.start(self.RCID, B, "Bob", 99)
        self.assertEqual((c, o["why"]), (409, "share"))
        self.share[7]["paused"] = True
        o, c = self.r.start(self.RCID, B, "Bob", 7)
        self.assertEqual((c, o["why"]), (409, "paused"))
        self.share[7] = {"url": "rtsp://cam/1", "live": True, "paused": False}
        self.assertEqual(self.r.start(self.RCID, B, "Bob", 7)[1], 409)
        self.assertEqual(self.r.start("bad", B, "Bob", 8)[1], 400)
        self.assertEqual(self.r.start(self.RCID, "not a host", "Bob", 8)[1], 400)
        r2 = rc.RemoteControl(backend=self.b, share_info=lambda fid: self.share.get(int(fid)), caps=(False, "wayland", "x11"), ui=self.ui, monitor=False)
        o, c = r2.start(self.RCID, B, "Bob", 8)
        self.assertEqual((c, o["why"]), (409, "wayland"))

    def test_one_controller_at_a_time(self):
        self.grant()
        o, c = self.r.start("zzzzzzzz9999", C, "Carol", 8)
        self.assertEqual((c, o["why"]), (409, "busy"))
        self.assertEqual(self.r.start(self.RCID, B, "Bob", 7)[1], 200)   # the same grant again is fine

    def test_lifecycle_bar_and_end(self):
        self.grant()
        # 0.21.83: a shorter label, and Stop sharing beside Stop control (tests/test_release_0_21_83_pill_admin.py)
        self.assertEqual(self.ui.shown[-1][1:], ("control", "Bob has control (Ctrl+Alt+Space)", ["stop", "share-stop"]))
        st = self.r.status(self.RCID)
        self.assertEqual((st["active"], st["controller"], st["paused"]), (True, B, False))
        self.ui.on_button("stop")                      # the share's bar
        st = self.r.status(self.RCID)
        self.assertEqual((st["active"], st["ended"]), (False, "bar"))
        self.assertEqual(self.ui.cleared, [7])
        self.assertEqual(self.put([{"t": "m", "x": 0.5, "y": 0.5}])[1], 403)

    def test_hotkey_ends_it(self):
        self.grant()
        self.r.hotkey()
        self.assertEqual(self.r.status(self.RCID)["ended"], "hotkey")

    def test_lease_lapses(self):
        self.grant()
        self.clock.t += rc.LEASE_S - 1
        self.assertIsNone(self.r.check())
        self.r.renew(self.RCID)                        # the page renews every second
        self.clock.t += rc.LEASE_S - 1
        self.assertIsNone(self.r.check())
        self.clock.t += 2
        self.assertEqual(self.r.check(), "timeout")
        self.assertEqual(self.r.status(self.RCID)["ended"], "timeout")

    def test_input_renews_the_lease(self):
        self.grant()
        self.clock.t += rc.LEASE_S - 1
        self.put([{"t": "hb"}])
        self.clock.t += rc.LEASE_S - 1
        self.assertIsNone(self.r.check())

    def test_share_stops_pauses_or_moves(self):
        for why, change in (("share", lambda s: s.update(live=False)), ("paused", lambda s: s.update(paused=True)),
                            ("retarget", lambda s: s.update(url="screen://window/5555"))):
            self.share[7] = {"url": WIN_URL, "live": True, "paused": False}
            self.grant()
            change(self.share[7])
            self.assertEqual(self.r.check(), why)
            self.assertEqual(self.r.status(self.RCID)["ended"], why)
        self.share[7] = {"url": WIN_URL, "live": True, "paused": False}
        self.grant()
        self.share[7]["live"] = False                  # input arriving after the share went: refused, the grant ends
        st, c = self.put([{"t": "d", "b": 0, "x": 0.5, "y": 0.5}])
        self.assertEqual(c, 409)
        self.assertEqual(self.r.status(self.RCID)["ended"], "share")
        self.assertEqual(self.ev("button"), [])
        self.share[7]["live"] = True
        self.grant()
        rc._RC = self.r
        try:
            rc.share_gone(7, "paused")                 # what kastr_rtsp's Bridge calls
        finally:
            rc._RC = None
        self.assertEqual(self.r.status(self.RCID)["ended"], "paused")

    def test_coordinates_clip_and_drop(self):
        self.grant()
        self.put([{"t": "m", "x": 0, "y": 0}, {"t": "m", "x": 1, "y": 1}, {"t": "m", "x": 1.7, "y": -3}, {"t": "m", "x": "nan", "y": 0.5}])
        self.assertEqual(self.ev("pointer"), [("pointer", 100, 50, True), ("pointer", 739, 449, True), ("pointer", 739, 50, True)])
        self.put([{"t": "d", "b": 0, "x": 1.2, "y": 0.5}, {"t": "w", "n": 1, "x": -0.1, "y": 0.5}])   # outside the window: dropped
        self.assertEqual((self.ev("button"), self.ev("wheel")), ([], []))
        self.assertEqual(self.r.stats["outside"], 2)
        self.put([{"t": "d", "b": 2, "x": 0.25, "y": 0.75}, {"t": "u", "b": 2, "x": 1.4, "y": 0.75}])   # a release always lets go
        self.assertEqual(self.ev("button"), [("button", 2, True, 260, 350, "post"), ("button", 2, False, 739, 350, "post")])
        self.put([{"t": "u", "b": 0, "x": 0.5, "y": 0.5}, {"t": "d", "b": 9, "x": 0.5, "y": 0.5}])     # never pressed / no such button
        self.assertEqual(len(self.ev("button")), 2)
        self.put([{"t": "w", "n": 2.4, "h": -1, "x": 0.5, "y": 0.5}])
        self.assertEqual(self.ev("wheel"), [("wheel", 2.4, False, "post"), ("wheel", -1.0, True, "post")])

    def test_monitor_with_a_negative_origin(self):
        self.grant(feed=8)
        self.put([{"t": "m", "x": 0.5, "y": 0.5}, {"t": "d", "b": 0, "x": 0, "y": 1}])
        self.assertEqual((self.ev("pointer")[0], self.ev("button")[0]), (("pointer", -960, 540, True), ("button", 0, True, -1920, 1079, "post")))

    def test_never_clicks_kastr_bar(self):
        # 0.21.83 (Kenton: "... when I try to click in that space it doesn't work to click on the things behind the pill"): a
        # press on the pill's rect is no longer dropped -- it goes to the window BEHIND the pill (the pill turns click-through
        # first; KASTR's own buttons still ignore injected presses: kastr_overlay)
        self.ui.bar = {"x": 300, "y": 56, "w": 200, "h": 30}
        self.grant()
        self.put([{"t": "d", "b": 0, "x": (350 - 100) / 640, "y": (60 - 50) / 400}])
        self.assertEqual(self.ev("button"), [("button", 0, True, 350, 60, "post")])
        self.assertEqual(self.r.stats["bar"], 1)

    def test_covered_window_is_raised_or_the_click_dropped(self):
        self.grant()
        self.b.on_top = False
        self.put([{"t": "d", "b": 0, "x": 0.5, "y": 0.5}, {"t": "u", "b": 0, "x": 0.5, "y": 0.5}])   # 0.21.80: a POSTED click reaches a covered window as it is
        self.assertEqual((self.b.raised, len(self.ev("button"))), ([], 2))
        self.b.events.clear()
        self.b.mode = "warp"                           # a warp-click needs the window in front
        self.put([{"t": "d", "b": 0, "x": 0.5, "y": 0.5}])
        self.assertEqual((self.b.raised, self.ev("button")), ([WIN_URL], []))
        self.b.on_top = True
        self.put([{"t": "d", "b": 0, "x": 0.5, "y": 0.5}, {"t": "u", "b": 0, "x": 0.5, "y": 0.5}])
        self.assertEqual(len(self.ev("button")), 2)

    def test_keys_go_only_to_the_shared_window(self):
        self.grant()
        self.b.focus = False
        st, _ = self.put([{"t": "k", "c": "KeyA", "d": 1}])
        self.assertEqual((self.ev("key"), st["blocked"]), ([], "focus"))
        self.b.focus = True
        self.put([{"t": "k", "c": "KeyA", "d": 1}, {"t": "k", "c": "KeyA", "d": 0}, {"t": "k", "c": "KeyB", "d": 0}, {"t": "k", "c": "Hyper", "d": 1}])
        self.assertEqual(self.ev("key"), [("key", "KeyA", True, "send"), ("key", "KeyA", False, "send")])

    def test_elevated_and_secure_are_reported(self):
        self.grant()
        for why in ("elevated", "secure"):
            self.b.blocked_why = why
            st, _ = self.put([{"t": "d", "b": 0, "x": 0.5, "y": 0.5}, {"t": "k", "c": "KeyA", "d": 1}])
            self.assertEqual(st["blocked"], why)
        self.assertEqual((self.ev("button"), self.ev("key")), ([], []))
        self.b.blocked_why = ""
        st, _ = self.put([{"t": "m", "x": 0.5, "y": 0.5}])
        self.assertEqual(st["blocked"], "")

    def test_local_input_holds_remote_off(self):
        # 0.21.80 (Kenton: "Allow both mice at the same time ... Instead of my mouse taking over their remote control"): the
        # 0.21.79 3 s hold is gone -- the person at the keyboard and the controller work at once
        self.grant()
        self.r.local_input("mouse")
        self.clock.t += 1.0
        st, _ = self.put([{"t": "d", "b": 0, "x": 0.5, "y": 0.5}, {"t": "k", "c": "KeyA", "d": 1}])
        self.assertEqual((st["paused"], st["pauseLeft"]), (False, 0))
        self.assertEqual([e[0] for e in self.b.events], ["pointer", "button", "key"])
        self.assertEqual(self.r.stats["paused"], 0)

    def test_local_input_lets_go_of_held_keys(self):
        self.grant()
        self.put([{"t": "k", "c": "ShiftLeft", "d": 1}, {"t": "d", "b": 0, "x": 0.5, "y": 0.5}])
        self.r._release_locked()                       # (0.21.80: local input no longer lets go of them -- control ending does)
        self.assertEqual(self.b.events[-2:], [("key", "ShiftLeft", False, "send"), ("button", 0, False, None, None, "post")])
        self.assertEqual((self.r.held_keys, self.r.held_buttons), ({}, {}))

    def test_end_lets_go_of_held_keys(self):
        self.grant()
        self.put([{"t": "k", "c": "ControlLeft", "d": 1}, {"t": "d", "b": 2, "x": 0.5, "y": 0.5}])
        self.r.end(self.RCID, "released")
        self.assertEqual(self.b.events[-2:], [("key", "ControlLeft", False, "send"), ("button", 2, False, None, None, "post")])

    def test_clipboard_caps_and_grant_only(self):
        st, c = self.put([{"t": "clip", "text": "before"}])
        self.assertEqual(c, 403)
        self.assertEqual(self.b.clip, "")              # never outside a grant
        self.b.clip = "secret from before control"
        self.b.clip_n = 5
        self.grant()
        self.assertIsNone(self.r.renew(self.RCID)["clip"])   # the clipboard as it was never travels
        self.put([{"t": "clip", "text": "x" * rc.CLIP_MAX}])
        self.assertEqual(len(self.b.clip), rc.CLIP_MAX)
        self.put([{"t": "clip", "text": "y" * (rc.CLIP_MAX + 1)}])
        self.assertEqual(len(self.b.clip), rc.CLIP_MAX)     # too big: not set
        self.put([{"t": "clip", "text": "\u00e9" * (rc.CLIP_MAX // 2 + 1)}])   # the cap is bytes (UTF-8), not characters
        self.assertEqual(self.b.clip, "x" * rc.CLIP_MAX)
        self.assertIsNone(self.r.renew(self.RCID)["clip"])   # what the controller set is not echoed back
        self.b.clip, self.b.clip_n = "copied on the sharer", self.b.clip_n + 1
        st = self.r.renew(self.RCID)
        self.assertEqual(st["clip"], {"n": 1, "text": "copied on the sharer"})
        self.b.clip, self.b.clip_n = "z" * (rc.CLIP_MAX + 5), self.b.clip_n + 1
        self.assertEqual(self.r.renew(self.RCID)["clip"], {"n": 2, "skipped": rc.CLIP_MAX + 5})
        self.r.end(self.RCID, "stopped")
        self.assertNotIn("clip", self.r.status(self.RCID))
        self.assertEqual(rc.clip_ok("a" * rc.CLIP_MAX), (True, rc.CLIP_MAX))

    def test_prompt_and_answer(self):
        o, c = self.r.prompt(self.RCID, 7, "Bob", "window \u2018Notes\u2019")
        self.assertEqual(c, 200)
        self.assertEqual(self.ui.shown[-1], (7, "prompt", "Bob asks to control your window \u2018Notes\u2019", ["deny", "allow"]))
        self.assertIsNone(self.r.status(self.RCID)["answer"])
        self.ui.on_button("allow")
        self.assertEqual(self.r.status(self.RCID)["answer"], "allow")
        self.ui.on_button("deny")                      # the first answer stands
        self.assertEqual(self.r.status(self.RCID)["answer"], "allow")
        self.r.prompt_end(self.RCID)
        self.assertIsNone(self.r.status(self.RCID)["answer"])
        self.assertEqual(self.r.prompt(self.RCID, 99, "Bob", "screen")[1], 409)


# ---- pure helpers: coordinates, Windows encoding, hooks --------------------------------------------------------------------
class Helpers(unittest.TestCase):
    def test_norm_point(self):
        r = {"x": 100, "y": 50, "w": 640, "h": 400}
        self.assertEqual(rc.norm_point(0, 0, r, False), (100, 50))
        self.assertEqual(rc.norm_point(1, 1, r, False), (739, 449))
        self.assertEqual(rc.norm_point(0.5, 0.5, r, False), (420, 250))
        self.assertIsNone(rc.norm_point(1.01, 0.5, r, False))
        self.assertEqual(rc.norm_point(1.01, -2, r, True), (739, 50))
        self.assertIsNone(rc.norm_point(float("inf"), 0.5, r, True))
        self.assertIsNone(rc.norm_point(0.5, 0.5, {"x": 0, "y": 0, "w": 0, "h": 10}, True))
        self.assertIsNone(rc.norm_point(None, 0.5, r, True))

    def test_win_absolute(self):
        vs = (-1920, 0, 3840, 1080)                    # two screens, the left one at a negative origin
        self.assertEqual(rc.win_absolute(-1920, 0, vs), (0, 0))
        self.assertEqual(rc.win_absolute(1919, 1079, vs), (65535, 65535))
        self.assertEqual(rc.win_absolute(0, 540, vs), (round(1920 * 65535 / 3839), round(540 * 65535 / 1079)))
        self.assertEqual(rc.win_absolute(-5000, 9999, vs), (0, 65535))   # clamped

    def test_input_struct_layout(self):
        ptr = ctypes.sizeof(ctypes.c_void_p)
        self.assertEqual(ctypes.sizeof(rc.INPUT), 40 if ptr == 8 else 28)   # what SendInput's cbSize must be
        self.assertEqual(ctypes.sizeof(rc.MOUSEINPUT), 32 if ptr == 8 else 24)
        self.assertEqual(ctypes.sizeof(rc.KEYBDINPUT), 24 if ptr == 8 else 16)

    def test_mouse_encoding(self):
        i = rc.win_move(0, 540, (-1920, 0, 3840, 1080))
        self.assertEqual((i.type, i.u.mi.dx, i.u.mi.dy, i.u.mi.dwFlags, i.u.mi.dwExtraInfo),
                         (0, 32776, 32798, 0x0001 | 0x8000 | 0x4000, rc.MAGIC))
        self.assertEqual((rc.win_button(0, True).u.mi.dwFlags, rc.win_button(0, False).u.mi.dwFlags), (0x2, 0x4))
        self.assertEqual((rc.win_button(2, True).u.mi.dwFlags, rc.win_button(1, False).u.mi.dwFlags), (0x8, 0x40))
        x1 = rc.win_button(3, True).u.mi
        self.assertEqual((x1.dwFlags, x1.mouseData), (0x80, 1))
        self.assertEqual(rc.win_button(4, False).u.mi.mouseData, 2)
        w = rc.win_wheel(1).u.mi                       # one notch DOWN (browser +) = -120 (Windows: away from the user is +)
        self.assertEqual((w.dwFlags, ctypes.c_int32(w.mouseData).value), (0x800, -120))
        self.assertEqual(ctypes.c_int32(rc.win_wheel(-2).u.mi.mouseData).value, 240)
        h = rc.win_wheel(1, True).u.mi
        self.assertEqual((h.dwFlags, ctypes.c_int32(h.mouseData).value), (0x1000, 120))

    def test_key_encoding(self):
        a = rc.win_key("KeyA", True)
        self.assertEqual((a.type, a.u.ki.wVk, a.u.ki.wScan, a.u.ki.dwFlags, a.u.ki.dwExtraInfo), (1, 0, 0x1E, 0x8, rc.MAGIC))
        self.assertEqual(rc.win_key("KeyA", False).u.ki.dwFlags, 0x8 | 0x2)
        up = rc.win_key("ArrowUp", True).u.ki
        self.assertEqual((up.wScan, up.dwFlags), (0x48, 0x8 | 0x1))   # an extended (E0) key
        self.assertEqual(rc.win_key("ControlRight", False).u.ki.dwFlags, 0x8 | 0x1 | 0x2)
        self.assertEqual(rc.win_key("Numpad8", True).u.ki.dwFlags, 0x8)   # the keypad's 8 is NOT the extended arrow
        self.assertIsNone(rc.win_key("Hyper", True))
        for code, sc in (("Escape", 0x01), ("Digit1", 0x02), ("Digit0", 0x0B), ("KeyQ", 0x10), ("KeyM", 0x32), ("Enter", 0x1C),
                         ("Space", 0x39), ("F1", 0x3B), ("F10", 0x44), ("F12", 0x58), ("MetaLeft", 0x5B)):
            self.assertEqual(rc.KEYS[code][0], sc, code)

    def test_key_table(self):
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            self.assertEqual(rc.KEYS["Key" + c][2], c.lower())
        for d in "0123456789":
            self.assertEqual(rc.KEYS["Digit" + d][2], d)
        pairs = [(v[0], v[1]) for v in rc.KEYS.values()]
        self.assertEqual(len(pairs), len(set(pairs)))  # one scan code (+E0) per key
        self.assertEqual(rc.KEYS["PageUp"][2], "Prior")
        self.assertEqual(rc.BUTTONS[2][3], 3)          # the browser's right button is X11 button 3

    def test_no_send_anywhere_but_flush(self):
        src = read("kastr_rc.py")
        self.assertEqual(src.count(".SendInput("), 1)  # WinBackend.flush only
        for banned in ("keybd_event", "mouse_event(", "SetCursorPos"):
            self.assertNotIn(banned, src)

    def test_hook_decisions(self):
        self.assertTrue(rc.ll_mouse_physical(0, 0))
        self.assertFalse(rc.ll_mouse_physical(0x1, 0))     # LLMHF_INJECTED
        self.assertFalse(rc.ll_mouse_physical(0x2, 0))     # LLMHF_LOWER_IL_INJECTED
        self.assertFalse(rc.ll_mouse_physical(0, rc.MAGIC))
        self.assertTrue(rc.ll_key_physical(0x80, 0))       # LLKHF_UP is not "injected"
        self.assertFalse(rc.ll_key_physical(0x10, 0))      # LLKHF_INJECTED
        self.assertFalse(rc.ll_key_physical(0x02, 0))
        h = rc.HotkeyState()
        self.assertFalse(h.feed(0xA2, True))               # left Ctrl
        self.assertFalse(h.feed(0x20, True))               # Ctrl+Space is not it
        self.assertFalse(h.feed(0x20, False))
        self.assertFalse(h.feed(0xA5, True))               # right Alt
        self.assertTrue(h.feed(0x20, True))                # Ctrl+Alt+Space
        h.feed(0xA2, False)
        self.assertFalse(h.feed(0x20, True))

    def test_surface_of(self):
        self.assertEqual(rc.surface_of("screen://monitor/2"), ("monitor", 2))
        self.assertEqual(rc.surface_of("screen://window/123456"), ("window", 123456))
        self.assertEqual(rc.surface_of("screen://tab/77/3"), ("tab", 77))
        self.assertIsNone(rc.surface_of("rtsp://cam"))

    def test_session_kind(self):
        self.assertEqual(x11.session_kind({"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}), "wayland")
        self.assertEqual(x11.session_kind({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}), "wayland")
        self.assertEqual(x11.session_kind({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}), "x11")
        self.assertEqual(x11.session_kind({"DISPLAY": ":99"}), "x11")
        self.assertEqual(x11.session_kind({}), "none")

    def test_platform_caps_mock_switch(self):
        old = os.environ.get("KASTR_RC_MOCK")
        os.environ["KASTR_RC_MOCK"] = "1"
        try:
            self.assertEqual(rc.platform_caps(), (True, "", "mock"))
            self.assertIsInstance(rc.make_backend(), rc.MockBackend)
        finally:
            if old is None:
                os.environ.pop("KASTR_RC_MOCK", None)
            else:
                os.environ["KASTR_RC_MOCK"] = old


# ---- the loopback API ---------------------------------------------------------------------------------------------------
class FakeHandler:
    def __init__(self, command, path, body=None, headers=None):
        self.command, self.path = command, path
        raw = json.dumps(body).encode() if body is not None else b""
        self.headers = dict({"Content-Length": str(len(raw))}, **(headers or {}))
        self.rfile, self.wfile = io.BytesIO(raw), io.BytesIO()
        self.code = None

    def send_response(self, c):
        self.code = c

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass

    def reply(self):
        return json.loads(self.wfile.getvalue() or b"{}")


class Api(unittest.TestCase):
    def setUp(self):
        self._local = kr.is_local
        kr.is_local = lambda h: getattr(h, "_is_local", True)
        rc._RC = rc.RemoteControl(backend=rc.MockBackend(rects={WIN_URL: WRECT}), caps=(True, "", "mock"), ui=FakeUI(), monitor=False)

    def tearDown(self):
        kr.is_local = self._local
        rc._RC = None

    def call(self, command, body=None, headers=None, local=True, path="/api/rc"):
        h = FakeHandler(command, path, body, headers)
        h._is_local = local

        class Feed:
            url = WIN_URL

        class Pub:
            paused = False
            broadcast = "alpha/x/w.hang"

        class Bridge:
            _pubs = {7: Pub()}

            def get(self, fid):
                return Feed() if int(fid) == 7 else None
        rc.handle_api(h, Bridge())
        return h.code, h.reply()

    def test_guards(self):
        self.assertEqual(self.call("GET", local=False)[0], 403)
        self.assertEqual(self.call("GET", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.call("GET", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        code, d = self.call("POST", {"op": "grant", "rcid": "abcdefgh1234", "controller": B, "feed": 7})
        self.assertEqual((code, d["error"]), (403, "missing X-KASTR-RC"))
        code, d = self.call("GET", headers={"Origin": "http://127.0.0.1:8001"})
        self.assertEqual((code, d["caps"]["available"], d["active"]), (200, True, False))

    def test_grant_input_end_over_http(self):
        H = {"X-KASTR-RC": "1", "Origin": "http://localhost:8001"}
        code, d = self.call("POST", {"op": "grant", "rcid": "abcdefgh1234", "controller": B, "name": "Bob", "feed": 7}, H)
        self.assertEqual((code, d["ok"], d["status"]["active"]), (200, True, True))
        code, d = self.call("POST", {"op": "input", "rcid": "abcdefgh1234", "src": B, "ev": [{"t": "m", "x": 0.5, "y": 0.5}]}, H)
        self.assertEqual((code, d["active"]), (200, True))
        self.assertEqual(rc._RC.backend.events, [("pointer", 420, 250, True)])   # 0.21.80: the controller's own arrow
        code, d = self.call("POST", {"op": "end", "rcid": "abcdefgh1234", "why": "stopped"}, H)
        self.assertEqual((code, d["ended"]), (200, "stopped"))
        code, d = self.call("POST", {"op": "input", "rcid": "abcdefgh1234", "src": B, "ev": [{"t": "m", "x": 0.5, "y": 0.5}]}, H)
        self.assertEqual(code, 403)
        self.assertEqual(self.call("POST", {"op": "nope"}, H)[0], 400)

    def test_bridge_info(self):
        class Feed:
            url = "rtsp://camera/1"

        class Bridge:
            _pubs = {}

            def get(self, fid):
                return Feed()
        self.assertIsNone(rc.bridge_info(Bridge())(3))   # a camera is never controllable


# ---- wiring: the bar, the bridge, the server, the page, the build ---------------------------------------------------------
class Wiring(unittest.TestCase):
    def test_overlay_buttons(self):
        import kastr_overlay as ko
        self.assertEqual(ko.INJECT_MAGIC, rc.MAGIC)
        ov = ko.ShareOverlay()
        ov._btns = [("deny", "Deny", (100, 6, 160, 34)), ("allow", "Allow", (168, 6, 230, 34))]
        self.assertEqual((ov._in_btn(120, 20), ov._in_btn(200, 20), ov._in_btn(164, 20)), ("deny", "allow", None))
        if not ko.AVAILABLE:
            self.assertFalse(ov.set_mode("control", "x", [("stop", "Stop control")]))
        self.assertIsNone(ov.bar_rect())
        src = read("kastr_overlay.py")
        self.assertIn("if k and not injected:                  # 0.21.79: the controller cannot press KASTR's own buttons", src)

    def test_bridge_tells_remote_control(self):
        import kastr_rtsp
        seen = []

        class M:
            @staticmethod
            def share_gone(fid, why):
                seen.append((fid, why))
        old = sys.modules.get("kastr_rc")
        sys.modules["kastr_rc"] = M
        try:
            kastr_rtsp._rc_gone("12", "paused")
        finally:
            sys.modules["kastr_rc"] = old
        self.assertEqual(seen, [(12, "paused")])
        src = read("kastr_rtsp.py")
        for anchor in ('_rc_gone(feed_id, "paused")', '_rc_gone(fid, "retarget")', '_rc_gone(feed_id, "share")'):
            self.assertEqual(src.count(anchor), 1, anchor)

    def test_server_routes(self):
        src = read("kastr_serve.py")
        self.assertEqual(src.count("return kastr_rc.handle_api(self, bridge, _note)"), 2)   # GET + POST

    def test_build_bundles_the_modules(self):
        self.assertIn('"--hidden-import", "kastr_rc", "--hidden-import", "kastr_x11"', read("build.py"))

    def test_page(self):
        p = page()
        # the menu item: publishers and admins only, native shares others list, never mine, never another room's
        self.assertIn('const rcCanAsk = () => joinState === "joined" && CHANNEL !== LOBBY && authSecured && !!authTokens?.member && (authRole === "publisher" || authRole === "admin") && !pbOld;', p)
        self.assertIn("{ const ri = rcMenuItem(name); if (ri) items.push(ri); }", p)
        self.assertIn('if (String(v).startsWith("rc")) { rcMenuPick(name, v); return; }', p)
        # the controller's input under its OWN host; the sharer's state likewise
        self.assertIn('CHANNEL + "/" + HOSTNAME1 + "/~rc/" + statePeer()', p)
        self.assertIn('stateSubscribe(connection, g.room + "/" + g.from + "/~rc/" + g.peer, "in.json", "snapshot"', p)
        # only native screen / window / tab shares are listed (RTSP entries made by the native picker)
        self.assertIn("window.__rcMine = () => added.filter((a) => a.kind === RTSP && a.screen && a.name && a.feedId != null && isScreenUrl(a.url))", p)
        # the notes go through the relay (it checks the role); the injector through the loopback API with its header
        self.assertIn('JSON.stringify({ op: "rc", ...body })', p)
        self.assertIn('"x-kastr-rc": "1"', p)
        # Kenton's words
        self.assertIn('" asks to control " + what + ". They\\u2019ll be able to use your mouse, keyboard and clipboard, and copy files to and from your computer \\u2014 with their own pointer and their name on your screen."', p)   # 0.21.80; 0.21.83: + files
        self.assertIn('c.name + " is using their mouse \\u2014 paused"', p)
        self.assertIn('" \\u2014 Stop control (Ctrl+Alt+Space)"', p)
        # hold Esc for a second; Keyboard Lock in full screen; never an old click twice
        self.assertIn("c.escT = setTimeout(() => { if (rcCtl === c) rcCtlEnd(\"released\", false); }, 1000);", p)
        self.assertIn("navigator.keyboard?.lock?.()", p)
        self.assertIn("let evs = v.ev.filter((e) => e && Number(e.s) > g.lastSeq);", p)
        self.assertEqual(p.count("function rcMapPoint("), 1)
        # an "~rc" broadcast never becomes a tile (not .hang)
        self.assertIn('if (!path.endsWith(".hang")) continue; // skip internal .stats etc.', p)

    def test_map_point_formula(self):
        # the page's rcMapPoint, mirrored: a 1920x1080 picture letterboxed (contain) into an 800x600 box, then zoomed 2x
        def mp(cx, cy, r, Bw, Bh, cw, ch, cover):
            sc = (max if cover else min)(Bw / cw, Bh / ch)
            ox, oy = (Bw - cw * sc) / 2, (Bh - ch * sc) / 2
            lx, ly = (cx - r["left"]) * Bw / r["width"], (cy - r["top"]) * Bh / r["height"]
            return round((lx - ox) / (cw * sc), 5), round((ly - oy) / (ch * sc), 5)
        box = {"left": 0, "top": 0, "width": 800, "height": 600}
        self.assertEqual(mp(400, 300, box, 800, 600, 1920, 1080, False), (0.5, 0.5))
        self.assertEqual(mp(0, 75, box, 800, 600, 1920, 1080, False), (0.0, 0.0))        # the letterbox's top edge
        self.assertTrue(mp(0, 10, box, 800, 600, 1920, 1080, False)[1] < 0)              # in the bar above the picture
        zoom = {"left": -400, "top": -300, "width": 1600, "height": 1200}                 # transform scale(2) about the centre
        self.assertEqual(mp(400, 300, zoom, 800, 600, 1920, 1080, False), (0.5, 0.5))
        self.assertEqual(mp(0, 75, zoom, 800, 600, 1920, 1080, False), (0.25, 0.25))
        self.assertEqual(mp(400, 300, box, 800, 600, 1920, 1080, True), (0.5, 0.5))       # cover crops the sides
        self.assertEqual(mp(0, 0, box, 800, 600, 1920, 1080, True)[0], 0.125)              # 1/8 of the width is cut off each side
        p = page()
        self.assertIn("const sc = (cover ? Math.max : Math.min)(Bw / cw, Bh / ch), ox = (Bw - cw * sc) / 2, oy = (Bh - ch * sc) / 2;", p)
        self.assertIn("const lx = (cx - r.left) * Bw / r.width, ly = (cy - r.top) * Bh / r.height;", p)


class LinuxCapture(unittest.TestCase):
    """Remote control on Linux needs a NATIVE share there: x11grab (the bundled static ffmpeg has it), never on Wayland."""

    def test_capture_args(self):
        from unittest import mock
        import kastr_screen
        rect = {"rect": {"x": 1280, "y": 0, "w": 1921, "h": 1081}}
        with mock.patch.object(kastr_screen, "LINUX", True), mock.patch.dict(os.environ, {"DISPLAY": ":99"}), \
                mock.patch.object(kastr_screen, "_resolve", return_value=rect):
            self.assertEqual(kastr_screen.capture_input("screen://monitor/2"),
                             ["-f", "x11grab", "-framerate", "30", "-draw_mouse", "1", "-video_size", "1920x1080", "-i", ":99+1280,0"])
            self.assertEqual(kastr_screen.capture_input("screen://window/2097153"),
                             ["-f", "x11grab", "-framerate", "30", "-draw_mouse", "1", "-window_id", "2097153", "-i", ":99"])
        with mock.patch.object(kastr_screen, "LINUX", True), mock.patch.object(kastr_screen, "linux_available", return_value=True):
            with self.assertRaises(ValueError):
                kastr_screen.check_url("screen://tab/5/1")   # one tab natively is Windows-only

    def test_wayland_and_opt_out_keep_the_browser_picker(self):
        from unittest import mock
        import kastr_screen
        with mock.patch.object(kastr_screen, "LINUX", True), mock.patch.dict(os.environ, {"KASTR_NATIVE_SCREEN": "0"}):
            self.assertFalse(kastr_screen.linux_available())
        with mock.patch.object(kastr_screen, "LINUX", True), mock.patch.object(x11, "session_kind", return_value="wayland"):
            self.assertFalse(kastr_screen.linux_available())

    def test_even_width_and_no_linux_screen_sound(self):
        import kastr_rtsp
        args = kastr_rtsp.publish_output_args(False, encoder="libx264", audio=False, screen=True)
        self.assertIn("scale=trunc(iw/2)*2:-2", args[args.index("-vf") + 1])   # an X11 window may be odd-wide
        cam = kastr_rtsp.publish_output_args(False, encoder="libx264", audio=False)
        self.assertIn("scale=iw:-2", cam[cam.index("-vf") + 1])
        self.assertIn('if self.audio and is_screen(getattr(feed, "url", "")) and sys.platform != "win32":', read("kastr_rtsp.py"))


@unittest.skipUnless(os.environ.get("KASTR_RC_XLAB") and sys.platform.startswith("linux"), "the virtual-X lab only (KASTR_RC_XLAB=:99)")
class XLab(unittest.TestCase):
    """Real XTest against the lab's Xephyr display (never a real desktop): KASTR_RC_XLAB=:99 DISPLAY=:99."""

    def test_list_and_rect(self):
        self.assertEqual(os.environ.get("DISPLAY"), os.environ["KASTR_RC_XLAB"])
        self.assertEqual(x11.available(), (True, ""))
        self.assertTrue(x11.list_monitors())
        wins = x11.list_windows()
        self.assertTrue(any(w["title"] == "RC Test App" for w in wins), wins)



class LinuxBrowserPicker(unittest.TestCase):
    # 0.21.79 (Kenton chose Linux native X11 sharing ON by default; its shares carry no sound): the browser's picker stays one
    # click away on Linux, where the native list replaces the Screen / Window tiles
    def test_link(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "moq-watch-lite.html"), encoding="utf-8", newline="") as f:
            p = f.read()
        self.assertIn('id="shBrowserPick" hidden', p)
        self.assertIn('$("shBrowserPick").hidden = !(native && /Linux/.test(navigator.userAgent) && !/Android/.test(navigator.userAgent));', p)
        self.assertIn('$("shBrowserPick").addEventListener("click", () => { shareSurface("monitor"); window.__shareChosen?.(); });', p)

if __name__ == "__main__":
    unittest.main()
