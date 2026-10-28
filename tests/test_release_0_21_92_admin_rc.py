# -*- coding: utf-8 -*-
"""v0.21.92 ADMIN REMOTE CONTROL FROM A PERSON'S MENU. Kenton (2026-10-27): "As an admin logged in, I need an option when right
clicking a user to request remote control, or take control if it's already allowed in the permissions."

His decisions, proven here (loopback only, NO real input, NO capture, NO screen listing: the injector is kastr_rc's recording
MockBackend, the bridge a fake, the monitors and the desktop stubbed):
  * admin-code holders only: the relay refuses a publisher's / viewer's / stranger's ask; the page shows the item to admins only;
  * the ask's note reaches ONLY the person's device (its beat), with the one-time claim key the admin never sees;
  * Allow (with the monitor the person picked) / Deny / no answer (the hub's 60 s and the person's own prompt) / withdrawn;
  * the PRIVATE path: the 0.21.83 ~rcx session (no room token covers it), the private capture, the pill's ask wording;
  * a person's computer is never the opt-in's: an unticked agent does not end an allowed ask;
  * opted-in machines keep "Take control" (Machines...' start, no prompt);
  * the audit on both sides (who, whom, when, how long, allowed or denied), a spoke's long-poll copy of the note;
  * the page / session view / Relay page / server wiring."""
import io
import json
import os
import sys
import tempfile
import time
import types
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_rcadmin as ra  # noqa: E402
import kastr_rc as rc  # noqa: E402

PERSON, ADM, PUBH, VIEW, OTHER = "pat-1a2b", "kenton-aa11", "pub-bb22", "vic-cc33", "olga-dd44"


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return f.read()


def covers(patterns, path):
    for p in patterns:
        if p == "**" or p == path or (p.endswith("/**") and path.startswith(p[:-3] + "/")):
            return True
    return False


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeHandler:
    def __init__(self, method, path, body=None, peer="127.0.0.1", headers=None):
        self.command, self.path = method, path
        raw = json.dumps(body).encode() if body is not None else b""
        self.headers = {"Host": "127.0.0.1:8791", "Content-Length": str(len(raw))}
        self.headers.update(headers or {})
        self.client_address = (peer, 50000)
        self.rfile, self.wfile = io.BytesIO(raw), io.BytesIO()
        self.code, self.sent = None, {}
        self.server = types.SimpleNamespace(server_address=("127.0.0.1", 8791))

    def send_response(self, code):
        self.code = code

    def send_header(self, k, v):
        self.sent[k] = v

    def end_headers(self):
        pass

    def json(self):
        return json.loads(self.wfile.getvalue() or b"{}")


class FakeBridge:
    def __init__(self):
        self.feeds, self.pubs, self.removed, self.next = {}, {}, [], 70
        self.rc = None

    def add_private(self, url, tag):
        f = types.SimpleNamespace(id=self.next, url=url, private=tag)
        self.feeds[f.id] = f
        self.next += 1
        return f

    def publish(self, fid, broadcast, relay, audio=True, keep=None, label=""):
        p = types.SimpleNamespace(broadcast=broadcast, relay=relay, audio=audio, keep=keep, minter=None, suspended=False, started=0)
        p.start = lambda p=p: setattr(p, "started", p.started + 1)
        self.pubs[fid] = p
        return p

    def retarget(self, fid, url):
        self.feeds[fid].url = url
        self.rc.share_gone(fid, "retarget")

    def remove_private(self, fid):
        self.removed.append(fid)
        self.feeds.pop(fid, None)
        self.pubs.pop(fid, None)


class FakeProc:
    killed = False

    def kill(self):
        self.killed = True


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        st = kr.AuthStore(self.dir)
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1", federation="fed-1")
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)

    def tearDown(self):
        self.svc.close()

    def tok(self, host, code):
        o, c = self.svc.token({"room": "alpha", "code": code, "host": host}, "10.0.0.7")
        assert c == 200, o
        return o["tokens"]["member"]

    def admin(self, op, bearer=None, **kw):
        return self.svc.rcx_admin_api(dict({"op": op, "by": "Kenton"}, **kw), "Bearer " + (bearer or self.tok(ADM, "adm-1")), "10.0.0.5")

    def ask(self, node=PERSON, **kw):
        return self.admin("ask", node=node, name="Pat", **kw)

    def inbox(self, host, code="view-1"):
        o, c = self.svc.people_api({"op": "beat"}, "Bearer " + self.tok(host, code), "10.0.0.8")
        assert c == 200, o
        return [x for x in o["inbox"] if x.get("kind") == "rcx"]


# ---- admins only; the note goes to the person's device only ----------------------------------------------------------------
class AdminOnly(Base):
    def test_publishers_viewers_and_strangers_cannot_ask(self):
        for code, host in (("pub-1", PUBH), ("view-1", VIEW)):
            o, c = self.admin("ask", bearer=self.tok(host, code), node=PERSON, name="Pat")
            self.assertEqual(c, 403, (code, o))
            self.assertIn("fleet admins only", o["error"])
        self.assertEqual(self.svc.rcx_admin_api({"op": "ask", "node": PERSON}, None, "x")[1], 403)
        self.assertEqual(self.inbox(PERSON), [])   # nothing reached the person

    def test_the_ask_reaches_only_the_person_and_the_claim_key_never_the_admin(self):
        d, c = self.ask()
        self.assertEqual(c, 200, d)
        self.assertTrue(d["ask"])
        self.assertNotIn("_note", d)
        self.assertNotIn("ck", json.dumps(d))
        self.assertEqual(self.inbox(OTHER), [])
        self.assertEqual(self.inbox(ADM, "adm-1"), [])
        got = self.inbox(PERSON)
        self.assertEqual(len(got), 1)
        it = got[0]
        self.assertEqual((it["sid"], it["by"], it["from"]), (d["sid"], "Kenton", ADM))
        self.assertRegex(it["ck"], r"^[0-9a-f]{32}$")
        self.assertNotIn(it["ck"], json.dumps(d))
        self.assertEqual(self.inbox(PERSON), [])   # taken once
        # the admin's own token for this session only (the 0.21.83 private paths)
        p = ra.paths(d["sid"])
        claims = kr.verify_token(d["token"], self.svc.key)
        self.assertEqual((claims["put"], claims["get"]), ([p["admin"]], [p["machine"], p["screen"]]))

    def test_bad_asks(self):
        self.assertEqual(self.ask(node="not a host")[1], 400)
        self.assertEqual(self.ask(node=ADM)[1], 400)   # my own computer
        d, c = self.ask()
        o, c = self.ask()
        self.assertEqual((c, o["why"]), (409, "busy"))   # one ask per device at a time

    def test_an_unknown_op_names_ask(self):   # the page reads an older hub's "op is ..." answer as "update the hub"
        d, c = self.svc._rcx_admin_hub({"op": "nonsense"}, {"host": ADM})
        self.assertEqual(c, 400)
        self.assertIn("ask", d["error"])


# ---- the person's KASTR ---------------------------------------------------------------------------------------------------
class PersonBase(Base):
    def setUp(self):
        super().setUp()
        self.sd = tempfile.mkdtemp()   # never opted in: a person's own computer
        self.bridge = FakeBridge()
        self.backend = rc.MockBackend(rects={"screen://monitor/0": {"x": 0, "y": 0, "w": 1280, "h": 720},
                                             "screen://monitor/1": {"x": 1280, "y": 0, "w": 1280, "h": 720},
                                             "screen://monitor/99": {"x": 0, "y": 0, "w": 2560, "h": 720}})
        self.ui = types.SimpleNamespace(shown=[], cleared=[], show=lambda *a, **k: self.ui.shown.append(a), clear=lambda f: self.ui.cleared.append(f), rect=lambda f: None)
        self.rc = rc.RemoteControl(backend=self.backend, share_info=self.info, caps=(True, "", "mock"), ui=self.ui, monitor=False)
        self.bridge.rc = self.rc
        self.procs = []
        self.saved = (ra.desktop_state, ra.list_monitors, ra.is_elevated)
        ra.desktop_state = lambda: {"ok": True, "why": ""}
        ra.list_monitors = lambda: [{"index": 0, "name": "Left", "width": 1280, "height": 720, "primary": False},
                                    {"index": 1, "name": "Right", "width": 1280, "height": 720, "primary": True}]
        ra.is_elevated = lambda: False
        self.agent = ra.Agent(self.sd, bridge=self.bridge, relay_url=lambda: "http://hub.lan:4443", log=lambda m: None, node=PERSON,
                              web_port=lambda: 8791, info=lambda: {"operator": "Pat", "mode": "full"}, http=self.http,
                              launch=self.launch, rc=self.rc)

    def tearDown(self):
        ra.desktop_state, ra.list_monitors, ra.is_elevated = self.saved
        self.agent._stop.set()
        super().tearDown()

    def info(self, fid):
        f = self.bridge.feeds.get(int(fid))
        return {"url": f.url, "live": int(fid) in self.bridge.pubs, "paused": False} if f else None

    def http(self, url, body, timeout):
        self.assertTrue(url.startswith("http://hub.lan:4444/api/rcx/"), url)
        return self.svc.rcx_machine(url.rsplit("/", 1)[1], json.loads(json.dumps(body)), "10.0.0.9")

    def launch(self, sid, pk):
        p = FakeProc()
        self.procs.append((sid, pk, p))
        return p

    def wait(self, fn, limit=5.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < limit:
            v = fn()
            if v:
                return v
            time.sleep(0.05)
        self.fail("timed out")

    def asked(self):
        d, c = self.ask()
        self.assertEqual(c, 200, d)
        it = self.inbox(PERSON)[0]
        return d, it

    def status(self, sid):
        return self.admin("status", sid=sid)[0]


class AllowDenyTimeout(PersonBase):
    def test_allow_opens_the_private_capture_of_the_picked_monitor_with_control(self):
        d, it = self.asked()
        self.assertEqual((self.status(d["sid"])["state"], self.status(d["sid"])["ask"]), ("pending", True))
        info = self.agent.ask_info()
        self.assertEqual([m["index"] for m in info["monitors"]], [0, 1])
        o, c = self.agent.answer_ask(it["sid"], it["ck"], "allow", monitor=0, by=it["by"])
        self.assertEqual(c, 200, o)
        s = self.agent.session
        self.assertEqual((s["state"], s["ask"], s["admin"]), ("live", True, "Kenton"))
        fid = s["feed"]
        self.assertEqual(self.bridge.feeds[fid].url, "screen://monitor/0")   # the person's pick, not the main one
        self.assertEqual(self.bridge.feeds[fid].private, d["sid"])
        pub = self.bridge.pubs[fid]
        p = ra.paths(d["sid"])
        self.assertEqual((pub.broadcast, pub.audio, pub.keep), (p["screen"], False, False))
        tok = pub.relay.split("jwt=", 1)[1]
        self.assertEqual(kr.verify_token(tok, self.svc.key)["put"], [p["machine"], p["screen"]])
        g = self.rc.grant
        self.assertEqual((g["controller"], g["name"]), (ADM, "Kenton"))
        self.assertEqual(g["bar"], "Kenton is controlling this screen — Stop control (Ctrl+Alt+Space)")
        self.assertEqual(self.ui.shown[-1][3], g["bar"])
        st = self.status(d["sid"])
        self.assertEqual((st["state"], st["ask"]), ("live", True))
        self.assertEqual(self.agent.ask_info(monitors=False)["session"]["sid"], d["sid"])
        # the admin's input lands; nobody else's
        self.assertEqual(self.rc.inject(s["rcid"], ADM, [{"t": "d", "b": 0, "x": 0.5, "y": 0.5}, {"t": "u", "b": 0, "x": 0.5, "y": 0.5}])[1], 200)
        self.assertEqual(self.rc.inject(s["rcid"], PUBH, [{"t": "m", "x": 0.1, "y": 0.1}])[1], 403)
        # the opt-in being off on this computer never ends an allowed ask
        self.agent.tick()
        self.assertIsNotNone(self.agent.session)
        # a second ask while it runs: busy
        o, c = self.ask()
        self.assertEqual((c, o["why"]), (409, "busy"))

    def test_deny(self):
        d, it = self.asked()
        o, c = self.agent.answer_ask(it["sid"], it["ck"], "deny", by="Kenton")
        self.assertEqual(c, 200, o)
        st = self.status(d["sid"])
        self.assertEqual((st["state"], st["why"]), ("ended", "denied"))
        self.assertIsNone(self.agent.session)
        self.assertEqual(self.bridge.feeds, {})   # nothing was captured
        o, c = self.agent.answer_ask(it["sid"], it["ck"], "allow")   # a late Allow
        self.assertEqual(c, 410, o)

    def test_no_answer_at_the_hub_and_from_the_prompt(self):
        clock = Clock(time.time())
        self.svc._rcx().clock = clock
        d, it = self.asked()
        clock.t += ra.ASK_S - 5
        self.assertEqual(self.status(d["sid"])["state"], "pending")   # an ask waits longer than a Machines... start
        clock.t += 6
        st = self.status(d["sid"])
        self.assertEqual((st["state"], st["why"]), ("ended", "noanswer"))
        clock.t = time.time()
        self.svc._rcx().rates.clear()
        d2, it2 = self.asked()
        o, c = self.agent.answer_ask(it2["sid"], it2["ck"], "timeout", by="Kenton")
        self.assertEqual(c, 200)
        self.assertEqual(self.status(d2["sid"])["why"], "noanswer")

    def test_a_withdrawn_ask_closes_the_prompt_and_refuses_a_late_allow(self):
        d, it = self.asked()
        o, c = self.admin("stop", sid=d["sid"])
        self.assertEqual(c, 200, o)
        self.assertNotIn("_cancel", o)
        got = self.inbox(PERSON)
        self.assertEqual([(x.get("x"), x["sid"]) for x in got], [("cancel", d["sid"])])
        self.assertNotIn("ck", got[0])
        self.assertEqual(self.agent.answer_ask(it["sid"], it["ck"], "allow")[1], 410)

    def test_the_claim_key_is_checked(self):
        d, it = self.asked()
        bad = "0" * 32 if it["ck"] != "0" * 32 else "1" * 32
        self.assertEqual(self.agent.answer_ask(it["sid"], bad, "allow")[1], 409)
        self.assertIsNone(self.agent.session)
        ts = int(time.time())
        o, c = self.svc.rcx_machine("claim", {"node": OTHER, "sid": it["sid"], "ts": ts, "mac": ra.mac(it["ck"], "claim", it["sid"], OTHER, ts)}, "x")
        self.assertEqual(c, 401)   # another device with the right key
        self.assertEqual(self.status(d["sid"])["state"], "pending")
        for bad_in in (("x", it["ck"]), (it["sid"], "zz"), (it["sid"], it["ck"], "maybe")):
            self.assertEqual(self.agent.answer_ask(*bad_in)[1] if len(bad_in) == 3 else self.agent.answer_ask(bad_in[0], bad_in[1], "allow")[1], 400)

    def test_the_admin_stops_it_and_the_person_hears_it_on_the_next_beat(self):
        d, it = self.asked()
        self.agent.answer_ask(it["sid"], it["ck"], "allow", monitor=1)
        self.assertEqual(self.agent.ask_beat_once(d["sid"]), "live")
        self.admin("stop", sid=d["sid"])
        self.assertEqual(self.agent.ask_beat_once(d["sid"]), "ended")
        self.assertIsNone(self.agent.session)
        self.assertIsNone(self.rc.grant)
        self.assertTrue(self.procs[0][2].killed)
        self.assertEqual(ra.audit_sessions(self.sd)[0]["why"], "admin")

    def test_ctrl_alt_space_and_the_pages_stop(self):
        d, it = self.asked()
        self.agent.answer_ask(it["sid"], it["ck"], "allow", monitor=99)
        self.assertEqual(self.bridge.feeds[self.agent.session["feed"]].url, "screen://monitor/99")   # All monitors
        self.rc.hotkey()
        self.wait(lambda: self.agent.session is None)
        st = self.status(d["sid"])
        self.assertEqual((st["state"], st["why"]), ("ended", "hotkey"))
        self.assertTrue(self.svc._rcx_is_dead(d["sid"]))
        self.svc._rcx().rates.clear()
        d2, it2 = self.asked()
        self.agent.answer_ask(it2["sid"], it2["ck"], "allow")
        self.assertEqual(self.agent.answer_ask(it2["sid"], "0" * 32, "stop")[1], 404)   # only the ask it allowed
        o, c = self.agent.answer_ask(it2["sid"], it2["ck"], "stop")
        self.assertEqual(c, 200, o)
        self.assertEqual(self.status(d2["sid"])["why"], "bar")

    def test_a_person_gone_quiet_ends_lost(self):
        clock = Clock(time.time())
        reg = self.svc._rcx()
        reg.clock = clock
        d, it = self.asked()
        self.agent.clock = clock
        self.agent.answer_ask(it["sid"], it["ck"], "allow")
        clock.t += ra.LOST_S - 10
        self.assertEqual(self.agent.ask_beat_once(d["sid"]), "live")   # a beat keeps it
        clock.t += ra.LOST_S - 10
        self.assertEqual(self.status(d["sid"])["state"], "live")
        clock.t += 30
        self.assertEqual(self.status(d["sid"])["why"], "lost")

    def test_busy_and_no_desktop_are_said(self):
        d, it = self.asked()
        ra.desktop_state = lambda: {"ok": False, "why": "locked"}
        o, c = self.agent.answer_ask(it["sid"], it["ck"], "allow")
        self.assertEqual((c, o["why"]), (409, "desktop"))
        self.assertEqual(self.status(d["sid"])["why"], "desktop")


# ---- the private path, Take control, the audit, a spoke's copy -------------------------------------------------------------
class PrivateAndTake(PersonBase):
    def test_no_room_token_covers_the_ask_session(self):
        d, it = self.asked()
        p = ra.paths(d["sid"])
        for code, host in (("adm-1", ADM), ("pub-1", PUBH), ("view-1", VIEW), ("view-1", PERSON)):
            g = kr.claims_to_grant(kr.verify_token(self.tok(host, code), self.svc.key))
            for path in p.values():
                self.assertFalse(covers(g["subscribe"], path) or covers(g["publish"], path), (code, path))

    def test_opted_in_machines_still_take_control_without_a_prompt(self):
        ra.set_optin(self.sd, True)
        key = ra.load_settings(self.sd)["key"]
        self.agent.tick()   # enroll
        self.agent.tick()   # listed
        m = self.admin("machines")[0]["machines"]
        self.assertEqual([x["node"] for x in m], [PERSON])   # the page reads this list: "Take control"
        d, c = self.admin("start", node=PERSON)
        self.assertEqual(c, 200, d)
        self.agent.tick()
        self.wait(lambda: self.agent.session and self.agent.session.get("state") == "live")
        self.assertFalse(self.agent.session["ask"])
        self.assertIn("(fleet admin) is controlling this machine", self.rc.grant["bar"])
        self.assertTrue(key)

    def test_the_audit_on_both_sides(self):
        d, it = self.asked()
        self.agent.answer_ask(it["sid"], it["ck"], "deny", by="Kenton")
        self.svc._rcx().rates.clear()
        d2, it2 = self.asked()
        self.agent.answer_ask(it2["sid"], it2["ck"], "allow", by="Kenton")
        self.agent.end_session(it2["sid"], "bar")
        hub = self.admin("sessions")[0]["sessions"]
        self.assertEqual([(r["sid"], r["ask"], r["state"], r["why"]) for r in hub[:2]],
                         [(d2["sid"], True, "ended", "bar"), (d["sid"], True, "ended", "denied")])
        self.assertEqual((hub[0]["answer"], hub[0]["admin"], hub[0]["machine"], hub[0]["node"]), ("allowed", "Kenton", "Pat", PERSON))
        self.assertEqual(hub[1]["answer"], "denied")
        self.assertIsNotNone(hub[0]["start"])
        self.assertGreaterEqual(hub[0]["dur"], 0)
        loc = ra.audit_sessions(self.sd)
        self.assertEqual([(r["sid"], r["kind"], r["why"]) for r in loc], [(d2["sid"], "ask", "bar"), (d["sid"], "ask", "denied")])
        self.assertEqual(loc[1]["admin"], "Kenton")

    def test_a_spoke_carries_the_note_and_drops_forged_ones(self):
        d, it = self.asked()
        feed = self.svc.personal_feed()
        self.assertTrue(any(x["to"] == PERSON and x["item"]["kind"] == "rcx" for x in feed["inbox"]))
        st2 = kr.AuthStore(tempfile.mkdtemp())
        st2.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st2)
        try:
            spoke.personal_mirror_apply({"personal": feed})
            spoke.personal_mirror_apply({"personal": feed})   # the same long-poll answer again: once
            got = [x for x in spoke._p_inbox_take(PERSON, time.time()) if x.get("kind") == "rcx"]
            self.assertEqual([(x["sid"], x["ck"]) for x in got], [(it["sid"], it["ck"])])
            bad = {"open": [], "rooms": {}, "away": {}, "inbox": [{"seq": 9, "to": PERSON, "item": {"kind": "rcx", "sid": "x", "ck": it["ck"], "from": ADM, "exp": 1}}]}
            spoke.personal_mirror_apply({"personal": bad})
            self.assertEqual([x for x in spoke._p_inbox_take(PERSON, time.time()) if x.get("kind") == "rcx"], [])
        finally:
            spoke.close()
        self.assertIsNone(kr.rcx_item_clean({"kind": "rcx", "sid": "a" * 32, "from": ADM}))   # no claim key, no exp
        self.assertEqual(kr.rcx_item_clean({"kind": "rcx", "sid": "a" * 32, "from": ADM, "x": "cancel", "ck": "b" * 32})["id"], "rcx-x-" + "a" * 32)
        self.assertNotIn("ck", kr.rcx_item_clean({"kind": "rcx", "sid": "a" * 32, "from": ADM, "x": "cancel", "ck": "b" * 32}))

    def test_a_spoke_vouches_for_its_admin(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, st, hub=lambda: "http://hub.lan:4444", fed_token=lambda: "fed")
        self.addCleanup(spoke.close)
        fed = "Bearer " + kr._mint(self.svc.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))
        spoke._hub_post = lambda path, body, timeout=8: self.svc.rcx_fed(json.loads(json.dumps(body)), fed, "10.1.1.1")
        o, c = spoke.token({"room": "alpha", "code": "adm-1", "host": ADM}, "10.2.0.5")
        d, c = spoke.rcx_admin_api({"op": "ask", "node": PERSON, "name": "Pat", "by": "Kenton"}, "Bearer " + o["tokens"]["member"], "10.2.0.5")
        self.assertEqual(c, 200, d)
        self.assertIsNotNone(kr.verify_token(d["token"], spoke.key))
        self.assertNotIn("ck", json.dumps(d))
        self.assertEqual(self.inbox(PERSON)[0]["sid"], d["sid"])
        o, c = spoke.token({"room": "alpha", "code": "pub-1", "host": PUBH}, "10.2.0.6")
        self.assertEqual(spoke.rcx_admin_api({"op": "ask", "node": PERSON}, "Bearer " + o["tokens"]["member"], "x")[1], 403)


# ---- the loopback API on the person's computer -------------------------------------------------------------------------------
class LocalApi(PersonBase):
    def setUp(self):
        super().setUp()
        self._a = ra._AGENT[0]
        ra._AGENT[0] = self.agent

    def tearDown(self):
        ra._AGENT[0] = self._a
        super().tearDown()

    def test_this_computers_own_page_only(self):
        h = FakeHandler("GET", "/api/rcadmin/ask")
        ra.handle_api(h, self.sd)
        self.assertEqual(h.code, 200)
        self.assertEqual([m["name"] for m in h.json()["monitors"]], ["Left", "Right"])
        h = FakeHandler("GET", "/api/rcadmin/ask?probe=1")
        ra.handle_api(h, self.sd)
        self.assertEqual((h.json()["monitors"], h.json()["desktop"]["ok"]), ([], True))   # the 30 s probe lists no screen
        d, it = self.asked()
        body = {"sid": it["sid"], "ck": it["ck"], "answer": "deny", "by": "Kenton"}
        for peer, hdr in (("10.0.0.66", {"X-KASTR-RC": "1"}), ("127.0.0.1", {"X-KASTR-RC": "1", "Origin": "http://evil.example"}),
                          ("127.0.0.1", {})):
            h = FakeHandler("POST", "/api/rcadmin/ask", body, peer=peer, headers=hdr)
            ra.handle_api(h, self.sd)
            self.assertEqual(h.code, 403, (peer, hdr))
        self.assertEqual(self.status(d["sid"])["state"], "pending")
        h = FakeHandler("POST", "/api/rcadmin/ask", body, headers={"X-KASTR-RC": "1"})
        ra.handle_api(h, self.sd)
        self.assertEqual(h.code, 200, h.json())
        self.assertEqual(self.status(d["sid"])["why"], "denied")


# ---- 0.21.92 files in the private sessions (Kenton: "the same as room remote control") ----------------------------------------
class FilesInPrivate(unittest.TestCase):
    """The 0.21.83 module runs in the private pages (moved to assets/kastr-rcf.js, not forked); the machine's helper is
    headless, so its card goes to the person's red bar through this computer's KASTR (show / ask)."""

    def setUp(self):
        import shutil
        import kastr_rcfiles as rf
        self.rf, self.tmp = rf, tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.clock = Clock(1000.0)
        self.grant = {"rcid": "rcx0123abcd", "url": "screen://monitor/0"}
        self.f = rf.Files(clip=rf.MockClip(), ini=lambda k: None, clock=self.clock, rc_get=lambda: types.SimpleNamespace(grant=self.grant),
                          root=os.path.join(self.tmp, "r"))
        self.addCleanup(self.f.shutdown)

    def call(self, **p):
        return self.rf._dispatch(self.f, p)

    def test_the_sharer_needs_the_private_sessions_grant(self):
        d, code = self.call(op="begin", rcid="otherrcid99", role="sharer")
        self.assertEqual(code, 403)
        d, code = self.call(op="begin", rcid="rcx0123abcd", role="sharer", name="Kenton")
        self.assertEqual(code, 200, d)

    def test_show_and_ask_carry_the_card_and_the_persons_cancel(self):
        self.call(op="begin", rcid="rcx0123abcd", role="sharer", name="Kenton")
        oid = "0123456789abcdef"
        rows = [{"k": "tx-" + oid, "t": "Kenton is copying 3 files from your computer — 1 of 3 files, 12 MB of 50 MB (24%)", "pct": 24, "b": ["txcancel:" + oid, "Cancel"]},
                {"k": "evil", "t": "x", "b": ["javascript:alert(1)", "Run"], "level": "<b>"}, "not a row", {"k": "", "t": "no key"}]
        d, code = self.call(op="show", rcid="rcx0123abcd", rows=rows)
        self.assertEqual((code, d["asks"]), (200, []))
        st = self.f.status()
        self.assertEqual([r["k"] for r in st["show"]], ["tx-" + oid, "evil"])
        self.assertEqual(st["show"][0]["b"], ["txcancel:" + oid, "Cancel"])
        self.assertNotIn("b", st["show"][1])          # only the module's own actions
        self.assertEqual(st["show"][1]["level"], "")
        # the person's Cancel (their red bar) -> the helper page's next show picks it up, once
        for bad in ("txcancel:XYZ", "rm -rf", "get:" + oid + ";x", ""):
            self.assertEqual(self.call(op="ask", rcid="rcx0123abcd", a=bad)[1], 400, bad)
        self.assertEqual(self.call(op="ask", rcid="rcx0123abcd", a="txcancel:" + oid)[1], 200)
        self.assertEqual(self.call(op="ask", rcid="rcx0123abcd", a="txcancel:" + oid)[1], 200)   # twice = once
        self.assertEqual(self.call(op="ask", rcid="wrongrcid1", a="rxcancel")[1], 409)
        d, _ = self.call(op="show", rcid="rcx0123abcd", rows=[])
        self.assertEqual(d["asks"], ["txcancel:" + oid])
        self.assertEqual(self.call(op="show", rcid="rcx0123abcd", rows=[])[0]["asks"], [])
        # stale rows are not shown (the helper page posts every second)
        self.call(op="show", rcid="rcx0123abcd", rows=rows[:1])
        self.clock.t += self.rf.SHOW_S + 1
        self.assertEqual(self.f.status()["show"], [])
        # the session's end: nothing to show, asks refused
        self.call(op="end", rcid="rcx0123abcd")
        self.assertEqual(self.call(op="show", rcid="rcx0123abcd", rows=rows)[1], 409)
        self.assertIn("show | ask", self.call(op="nope")[0]["error"])

    def test_the_module_moved_not_forked(self):
        mod, page = read("assets/kastr-rcf.js"), read("moq-watch-lite.html")
        self.assertTrue(all(ord(ch) < 128 for ch in mod))
        self.assertNotIn("\r\n", mod)
        self.assertIn("window.KastrRcf = { create,", mod)
        self.assertNotIn("function rcfPlan(", page)   # one copy of the code: the asset's
        for p in ("moq-watch-lite.html", "rcx.html", "rcx-agent.html"):
            self.assertIn('<script src="/assets/kastr-rcf.js"></script>', read(p), p)
        self.assertIn('out.append("/assets/kastr-rcf.js")', read("kastr_serve.py"))

    def test_recv_and_done_are_sent_again_when_nothing_answered(self):
        mod = read("assets/kastr-rcf.js")
        f = mod[mod.index("  async function rcfLocalAgain(body) {"):mod.index("function create(env) {")]
        self.assertIn("!d.ok && d.http === undefined", f)   # only a request that got no answer at all -- never an HTTP error
        self.assertIn("i < 2", f)
        self.assertIn('await rcfLocalAgain({ op: "recv",', mod)
        self.assertIn('await rcfLocalAgain({ op: "done",', mod)
        self.assertEqual(mod.count("rcfLocalAgain("), 3)   # cancel / renew / begin stay single
        # ... and the server side answers a repeat with the transfer it already has
        rc = read("kastr_rcfiles.py")
        self.assertIn('if oid in s.incoming and s.incoming[oid].state in ("get", "done"):', rc)
        self.assertIn('if inc.state == "done":\n                return {"ok": True, "progress": inc.progress()}, 200', rc)

    def test_the_agent_and_the_view(self):
        a = read("rcx-agent.html")
        for needle in ('const FK = window.KastrRcf ? KastrRcf.newKey() : "";', "machine: s.machine, fk: FK || undefined };",
                       '["st.json", "ptr.json", "src.json", "fo.json", "fq.json", "fd"]', 'tracks: { fd: { priority: window.KastrRcf ? KastrRcf.PRIO : 30, maxAge: 3000 } }',
                       "peer: () => ({ st: s.paths.admin, data: s.paths.admin }),", 'RCF?.start("sharer", { rcid: RCID, name: s.admin, fk: FK });',
                       "try { RCF?.stop(g.ended); } catch {}", 'post("/api/rcfiles", { op: "show", rcid: RCID, rows });',
                       "if (RCF_ASK_RE.test(String(a))) RCF.action(String(a));", 'out.again("fo.json"); out.again("fq.json");'):
            self.assertIn(needle, a, needle)
        v = read("rcx.html")
        for needle in ('["in.json", "ctl.json", "fo.json", "fq.json", "fd"]', "peer: () => (S ? { st: S.paths.machine, data: S.paths.machine } : null),",
                       'RCF.start("ctl", { rcid: S.rcid, name: mName(), fk: c.st.fk });', "if (!KastrRcf.FK_RE.test(String(c.st.fk || \"\")))",
                       "try { RCF.stop(c.ended); } catch {}", 'cap.addEventListener("drop", rcfDrop);', "RCF.paste(c).then(() => { fDone = true; go(); }",
                       "isCtl: (x) => x === c && !c.ended", 'needs: "0.21.92"', "#kRcFiles { position:fixed;", "#cap.rcfdrag {",
                       'fetch("/api/rcfiles", { cache: "no-store" })'):
            self.assertIn(needle, v, needle)
        self.assertNotIn("\r\n", a)
        self.assertNotIn("\r\n", v)

    def test_the_persons_bar_and_the_allow_prompt(self):
        s = read("moq-watch-lite.html")
        self.assertIn("and can copy files and pictures to and from this computer while in control; you can stop any time", s)
        for needle in ("async function rcxFilesPoll()", 'body: JSON.stringify({ op: "ask", rcid: el.dataset.rcid, a: b.dataset.a })',
                       "#kRcxFiles { position:fixed;", "if (rcxBarCur || rcxfLive || rcxfN % 5 === 0) rcxFilesPoll();"):
            self.assertIn(needle, s, needle)


class BoxTileAndMyRoom(unittest.TestCase):
    def test_take_control_of_a_box_on_its_tiles(self):
        s = read("moq-watch-lite.html")
        f = s[s.index("  function rcaTileItem(name, extra) {"):s.index("  function rcaTilePick(name) {")]
        self.assertIn("if (!rcxIsAdmin() || wrRoomOf(name)) return null;", f)   # fleet admins only: hidden for everyone else
        self.assertIn("rcaMach.get(host)", f)                                       # only a box that opted in (Machines...' list)
        self.assertIn('label: "Take control of " + rcxName(m)', f)
        self.assertIn("disabled: true, why: rcxStatus(m).text", f)
        self.assertIn("{ const bi = rcaTileItem(name, extra); if (bi) items.push(bi); }", s)
        self.assertIn('if (v === "boxtake") { rcaTilePick(name); return; }', s)
        self.assertIn("if (m) rcxControl(m);", s)                                   # exactly Machines...' private start
        # "boxtake" is handled before the "rc" prefix of room remote control
        self.assertLess(s.index('if (v === "boxtake") { rcaTilePick(name); return; }'), s.index('if (String(v).startsWith("rc")) { rcMenuPick(name, v); return; }'))

    def test_my_room_people_can_be_asked(self):
        # no public state (My room is private): the item stays active; the hub says "no answer" after 60 s
        s = read("moq-watch-lite.html")
        self.assertIn('return { ask: true, unsure: true };', s)
        self.assertIn('p.room && p.room !== "~private" ? p.room : CHANNEL', s)
        self.assertEqual(ra.ASK_S, 60)


# ---- the page, the session view, the Relay page, the server ------------------------------------------------------------------
class Wiring(unittest.TestCase):
    def test_page(self):
        s = read("moq-watch-lite.html")
        for needle in ("function rcaWrap(r, p)", "const r = rcaWrap(personInviteItems0(p), p);", '"Request remote control…"', '"Take control"',
                       "if (!p || p.me || !rcxIsAdmin()) return r;", "rcxControl(s.take)", 'rcxCall({ op: "ask", node: host, name: who })',
                       'else if (it?.kind === "rcx") rcxAskArrive(it);', 'id = "kRcxAsk"', '"All monitors"', "(Ctrl+Alt+Space or Stop control)",
                       'fetch("/api/rcadmin/ask"', '"x-kastr-rc": "1"', "pubModel.rca = v", "rca: v.rca === 1 ? 1", "...rcaOffline(x)",
                       'b.classList.add("dis")', " declined your remote control request.", " didn’t answer your remote control request.",
                       "window.__rca = {", "#kRcxAsk .rxmon", "#mineMenu .mi.dis"):
            self.assertIn(needle, s, needle)
        self.assertEqual(s.count("\r\n"), s.count("\n"))   # CRLF kept

    def test_session_view_and_relay_page(self):
        v = read("rcx.html")
        for needle in ('S.kind === "ask"', 'denied: "they declined"', " declined your remote control request."):
            self.assertIn(needle, v)
        self.assertNotIn("\r\n", v)
        r = read("relay.html")
        self.assertIn('denied: "they declined"', r)
        self.assertIn("(admin, asked)", r)

    def test_the_x11_pill_event_buffer_is_an_array_again(self):
        # lab find: 0.21.87's maximize union was named XEvent and shadowed `XEvent = c_long * 24` -- the X11 control bar's
        # event loop (xev[0]) raised on its first event, so the Linux red pill never drew
        import ctypes
        import kastr_x11
        self.assertTrue(issubclass(kastr_x11.XEvent, ctypes.Array))
        self.assertEqual(kastr_x11.XEvent()[0] & 0xFFFFFFFF, 0)
        self.assertEqual(ctypes.sizeof(kastr_x11.XClientEventU), ctypes.sizeof(kastr_x11.XEvent))

    def test_server(self):
        s = read("kastr_serve.py")
        self.assertEqual(s.count('"/api/rcadmin/ask"'), 2)
        self.assertNotIn("\r\n", read("kastr_rcadmin.py"))
        self.assertNotIn("\r\n", read("kastr_relay.py"))


if __name__ == "__main__":
    unittest.main()
