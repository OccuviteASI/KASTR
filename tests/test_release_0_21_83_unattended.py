# -*- coding: utf-8 -*-
"""v0.21.83 (D) UNATTENDED REMOTE CONTROL FOR FLEET ADMINS. Kenton (2026-10-23): "I would like to set it up to allow remote
control with the admin permissions on a relay/hub/camera box. This should be opt-in only and a check box in the relay server
page allowing remote control without having to ask." -- "how would I access this from my own KASTR?" -- and: "When remoted in
to an unattended box, allow for switching to different windows/monitors on the device."

What is proven here (loopback only, NO real input, NO capture, NO elevation anywhere -- the injector is kastr_rc's recording
MockBackend, the bridge is a fake or a real Bridge whose screen calls are stubbed):
  * the opt-in is LOCAL ONLY: the checkbox's API answers a loopback request from the machine's own page (no forwarded request,
    no foreign Origin, the custom header) and nothing else; default off; the hub sees it in the machine's polls and has no
    way at all to switch it on;
  * the hub's verification: the machine's key (pinned on first sight, a changed key refused while the old one was heard from
    within the hour), every poll / claim / end HMAC-checked, the clock window, the opt-in, online, a desktop, busy, the rate
    limits; the claim's answer carries the hub's proof the machine checks;
  * fleet admins only: a publisher's / viewer's member token is refused; a spoke vouches for its admin to the hub;
  * the audit log on both sides (who, from where, start, end, duration, why), capped, kept across a hub restart;
  * the private path: session tokens cover ~rcx/<sid>/... only, no room token covers ~rcx, the private feed is never listed,
    saved or remembered as closed; a session that is over is refused at the relay's next re-check;
  * timeouts: an unclaimed Control, a machine gone quiet, the 8-hour limit, the grant's lease on the machine;
  * the agent end to end against an in-process hub: claim, capture, the grant with the admin's pill, the source switch
    (Bridge.retarget, control kept), Ctrl+Alt+Space ends it and both logs say so;
  * All monitors (screen://monitor/99) on both platforms, the page / Relay page / build wiring.
The real thing runs in the WSL lab against a virtual X server (scratchpad v02183/D)."""
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_rcadmin as ra  # noqa: E402
import kastr_rc as rc  # noqa: E402

BOX, ADM, PUBH, VIEW = "box-1a2b", "kenton-aa11", "pat-bb22", "vic-cc33"


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return f.read()


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def covers(patterns, path):
    """The relay's per-segment pattern semantics (kastr_relay._patterns): 'x' and 'x/**'; '**' = everything."""
    for p in patterns:
        if p == "**" or p == path or (p.endswith("/**") and path.startswith(p[:-3] + "/")):
            return True
    return False


def poll_body(key, node=BOX, ts=None, on=True, enroll=False, **kw):
    ts = int(time.time() if ts is None else ts)
    b = {"node": node, "ts": ts, "kid": ra.kid_of(key), "on": on, "wait": 0, "mac": ra.mac(key, "poll", node, ts, "1" if on else "0"),
         "hostname": "BOX-01", "mode": "publisher", "version": "0.21.83", "platform": "linux", "desktop": {"ok": True, "why": ""},
         "monitors": [{"index": 1, "name": "Screen 1", "width": 1280, "height": 720, "primary": True}]}
    if enroll:
        b["key"] = key
    b.update(kw)
    return b


class FakeHandler:
    """Just enough of BaseHTTPRequestHandler for the loopback APIs."""

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


class HubBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        st = kr.AuthStore(self.dir)
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1", federation="fed-1")
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)
        self.key = ra.new_key()

    def tearDown(self):
        self.svc.close()

    def tok(self, host, code):
        o, c = self.svc.token({"room": "alpha", "code": code, "host": host}, "10.0.0.7")
        assert c == 200, o
        return o["tokens"]["member"]

    def enroll(self, **kw):
        o, c = self.svc.rcx_machine("poll", poll_body(self.key, enroll=True, **kw), "10.0.0.9")
        self.assertEqual(c, 200, o)
        return o

    def admin(self, op, bearer=None, **kw):
        return self.svc.rcx_admin_api(dict({"op": op, "by": "Kenton"}, **kw), "Bearer " + (bearer or self.tok(ADM, "adm-1")), "10.0.0.5")

    def claim(self, sid, key=None, node=BOX):
        ts = int(time.time())
        return self.svc.rcx_machine("claim", {"node": node, "sid": sid, "ts": ts, "mac": ra.mac(key or self.key, "claim", sid, node, ts)}, "10.0.0.9")


# ---- the opt-in: this machine only ---------------------------------------------------------------------------------------
class OptInLocalOnly(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._agent = ra._AGENT[0]
        ra._AGENT[0] = None   # no agent: the checkbox's own answer

    def tearDown(self):
        ra._AGENT[0] = self._agent

    def post(self, body, **kw):
        h = FakeHandler("POST", "/api/rcadmin", body, **kw)
        ra.handle_api(h, self.dir)
        return h

    def test_default_is_off(self):
        self.assertEqual(ra.load_settings(self.dir), {"on": False, "key": "", "since": 0})
        h = FakeHandler("GET", "/api/rcadmin")
        ra.handle_api(h, self.dir)
        self.assertEqual((h.code, h.json()["on"]), (200, False))

    def test_the_machines_own_page_switches_it_on_and_off_and_the_key_stays(self):
        h = self.post({"on": True}, headers={"X-KASTR-RC": "1", "Origin": "http://127.0.0.1:8791", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(h.code, 200, h.json())
        s = ra.load_settings(self.dir)
        self.assertTrue(s["on"]) and self.assertRegex(s["key"], r"^[0-9a-f]{64}$")
        key = s["key"]
        self.post({"on": False}, headers={"X-KASTR-RC": "1"})
        s2 = ra.load_settings(self.dir)
        self.assertFalse(s2["on"])
        self.post({"on": True}, headers={"X-KASTR-RC": "1"})
        self.assertEqual(ra.load_settings(self.dir)["key"], key)   # the hub's pin survives unticking and ticking again
        if os.name != "nt":
            self.assertEqual(os.stat(ra.settings_path(self.dir)).st_mode & 0o777, 0o600)

    def test_anyone_else_is_refused(self):
        hdr = {"X-KASTR-RC": "1"}
        cases = [dict(peer="10.0.0.5", headers=hdr),                                             # another machine
                 dict(headers=dict(hdr, **{"X-Forwarded-For": "203.0.113.9"})),                 # through a tunnel / proxy
                 dict(headers=dict(hdr, **{"Cf-Connecting-IP": "203.0.113.9"})),
                 dict(headers=dict(hdr, Origin="https://evil.example")),                       # a foreign page in the local browser
                 dict(headers=dict(hdr, **{"Sec-Fetch-Site": "cross-site"})),
                 dict(headers=dict(hdr, Host="kastr.example.com")),
                 dict(headers={})]                                                              # no custom header (a plain form post)
        for kw in cases:
            h = self.post({"on": True}, **kw)
            self.assertEqual(h.code, 403, kw)
            self.assertFalse(ra.load_settings(self.dir)["on"], kw)

    def test_a_bad_body_changes_nothing(self):
        for body in ({}, {"on": "yes"}, {"on": 1}):
            h = self.post(body, headers={"X-KASTR-RC": "1"})
            self.assertEqual(h.code, 400)
        self.assertFalse(ra.load_settings(self.dir)["on"])

    def test_the_helper_pages_endpoints_are_this_machine_only_too(self):
        for path in ("/api/rcadmin/session?sid=" + "a" * 32 + "&k=x", "/api/rcadmin"):
            h = FakeHandler("GET", path, peer="10.0.0.5")
            ra.handle_api(h, self.dir)
            self.assertEqual(h.code, 403)
        h = FakeHandler("POST", "/api/rcadmin/ctl", {"sid": "a" * 32, "op": "src"}, peer="10.0.0.5", headers={"X-KASTR-RC": "1"})
        ra.handle_api(h, self.dir)
        self.assertEqual(h.code, 403)


class HubCannotSwitchItOn(HubBase):
    def test_no_hub_or_admin_call_turns_a_machine_on(self):
        self.enroll(on=False) if False else None
        o, c = self.svc.rcx_machine("poll", poll_body(self.key, enroll=True, on=False), "10.0.0.9")
        self.assertEqual((c, o.get("on")), (200, False))
        for op in ("optin", "enable", "on", "set"):
            o, c = self.admin(op, node=BOX, on=True)
            self.assertEqual(c, 400, op)
        fed = "Bearer " + kr._mint(self.svc.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))
        for op in ("optin", "enable"):
            o, c = self.svc.rcx_fed({"op": op, "node": BOX, "on": True}, fed)
            self.assertEqual(c, 400)
        o, c = self.admin("machines")
        self.assertEqual((c, o["machines"]), (200, []))   # an opted-OUT machine is not listed
        o, c = self.admin("start", node=BOX)
        self.assertEqual(c, 403)
        self.assertIn("does not allow fleet admins", o["error"])
        self.assertFalse(self.svc._rcx().machines[BOX]["on"])

    def test_the_relay_page_api_offers_only_start_stop_status(self):
        relay = types.SimpleNamespace(auth=self.svc, running=lambda: True, port=4443, status=lambda public=False: {})
        h = FakeHandler("POST", "/api/relay/rcx", {"op": "optin", "node": BOX, "on": True})
        self.assertTrue(kr.handle_api(h, relay, "/api/relay/rcx"))
        self.assertEqual(h.code, 400)
        h = FakeHandler("POST", "/api/relay/rcx", {"op": "start", "node": BOX}, peer="10.0.0.5")
        kr.handle_api(h, relay, "/api/relay/rcx")
        self.assertEqual(h.code, 403)   # GUARDED_POSTS: the hub operator is the machine the hub runs on
        h = FakeHandler("GET", "/api/relay/rcx", peer="10.0.0.5")
        kr.handle_api(h, relay, "/api/relay/rcx")
        self.assertEqual(h.code, 403)


# ---- the hub's verification ------------------------------------------------------------------------------------------------
class HubVerifies(HubBase):
    def test_first_poll_enrolls_the_key_then_every_poll_checks_it(self):
        o, c = self.svc.rcx_machine("poll", poll_body(self.key), "10.0.0.9")
        self.assertEqual((c, o.get("enroll")), (401, True))   # the hub asks for the key once
        self.enroll()
        row = self.svc._rcx().machines[BOX]
        self.assertEqual((row["kid"], row["on"], row["via"], row["ip"]), (ra.kid_of(self.key), True, self.svc._rcx_name(), "10.0.0.9"))
        o, c = self.svc.rcx_machine("poll", poll_body(self.key), "10.0.0.9")   # no key on the wire again
        self.assertEqual(c, 200, o)
        bad = poll_body(self.key)
        bad["mac"] = "0" * 64
        self.assertEqual(self.svc.rcx_machine("poll", bad, "10.0.0.9")[1], 401)
        spoofed = poll_body(ra.new_key())   # someone else's key, same node
        self.assertIn(self.svc.rcx_machine("poll", spoofed, "10.0.0.9")[1], (401, 409))
        self.assertEqual(self.svc.rcx_machine("poll", poll_body(self.key, ts=time.time() - 3600), "10.0.0.9")[1], 401)   # clock

    def test_a_changed_key_is_refused_while_the_pinned_one_is_alive(self):
        self.enroll()
        other = ra.new_key()
        o, c = self.svc.rcx_machine("poll", poll_body(other, enroll=True), "10.0.0.9")
        self.assertEqual((c, o.get("keyConflict")), (409, True))
        reg = self.svc._rcx()
        reg.machines[BOX]["at"] -= ra.KEY_REPIN_S + 5   # the old machine went quiet an hour ago: a reinstall
        o, c = self.svc.rcx_machine("poll", poll_body(other, enroll=True), "10.0.0.9")
        self.assertEqual(c, 200, o)
        self.assertEqual(reg.machines[BOX]["kid"], ra.kid_of(other))

    def test_start_checks_opt_in_online_desktop_busy(self):
        self.enroll()
        o, c = self.admin("start", node=BOX)
        self.assertEqual(c, 200, o)
        sid = o["sid"]
        o2, c2 = self.admin("start", node=BOX)
        self.assertEqual((c2, o2["why"]), (409, "busy"))
        self.admin("stop", sid=sid)
        self.enroll(desktop={"ok": False, "why": "nosession"})
        o, c = self.admin("start", node=BOX)
        self.assertEqual((c, o["why"]), (409, "desktop"))
        self.assertEqual(o["error"], "nobody is signed in on BOX-01")
        self.enroll(busy="Pat")   # someone controls it through a room ask (0.21.79)
        self.assertEqual(self.admin("start", node=BOX)[1], 409)
        self.enroll()
        self.svc._rcx().machines[BOX]["at"] -= ra.ONLINE_S + 1
        o, c = self.admin("start", node=BOX)
        self.assertEqual((c, o["why"]), (409, "offline"))

    def test_rate_limits(self):
        self.enroll()
        for i in range(ra.START_RATE_ADMIN[0]):
            o, c = self.admin("start", node=BOX)
            self.assertEqual(c, 200, o)
            self.admin("stop", sid=o["sid"])
        o, c = self.admin("start", node=BOX)
        self.assertEqual(c, 429)
        self.assertIn("retryAfter", o)

    def test_the_claim_carries_the_hubs_proof_and_the_machines_token(self):
        self.enroll()
        o, c = self.admin("start", node=BOX, monitor=99)
        sid = o["sid"]
        self.assertEqual(o["monitor"], 99)   # All monitors
        ts = int(time.time())
        bad = self.svc.rcx_machine("claim", {"node": BOX, "sid": sid, "ts": ts, "mac": ra.mac(ra.new_key(), "claim", sid, BOX, ts)}, "x")
        self.assertEqual(bad[1], 401)
        d, c = self.claim(sid)
        self.assertEqual(c, 200, d)
        self.assertTrue(ra.mac_ok(self.key, d["check"], "ok", sid, d["rcid"], d["exp"], d["admin"]))   # the machine re-verifies
        self.assertFalse(ra.mac_ok(ra.new_key(), d["check"], "ok", sid, d["rcid"], d["exp"], d["admin"]))
        claims = kr.verify_token(d["token"], self.svc.key)
        p = ra.paths(sid)
        self.assertEqual((claims["put"], claims["get"], claims["rcx"]), ([p["machine"], p["screen"]], [p["admin"]], sid))
        self.assertEqual(claims["exp"], d["exp"])
        self.assertEqual(d["adminHost"], ADM)
        self.assertEqual(d["admin"], "Kenton")
        # someone else's node cannot claim it
        k2 = ra.new_key()
        self.svc.rcx_machine("poll", poll_body(k2, node="other-9f9f", enroll=True), "x")
        self.assertEqual(self.claim(sid, key=k2, node="other-9f9f")[1], 404)

    def test_switching_the_machine_off_ends_its_session(self):
        self.enroll()
        sid = self.admin("start", node=BOX)[0]["sid"]
        self.claim(sid)
        o, c = self.svc.rcx_machine("poll", poll_body(self.key, on=False), "10.0.0.9")
        self.assertEqual(c, 200)
        st = self.admin("status", sid=sid)[0]
        self.assertEqual((st["state"], st["why"]), ("ended", "off"))


# ---- fleet admins only -----------------------------------------------------------------------------------------------------
class AdminOnly(HubBase):
    def test_publishers_viewers_and_strangers_are_refused(self):
        self.enroll()
        for code, host in (("pub-1", PUBH), ("view-1", VIEW)):
            for op in ("machines", "start", "sessions", "stop", "status"):
                o, c = self.admin(op, bearer=self.tok(host, code), node=BOX, sid="a" * 32)
                self.assertEqual(c, 403, (code, op))
                self.assertIn("fleet admins only", o["error"])
        o, c = self.svc.rcx_admin_api({"op": "machines"}, None, "x")
        self.assertEqual(c, 403)
        o, c = self.svc.rcx_admin_api({"op": "machines"}, "Bearer " + kr._mint(os.urandom(32), {"put": "alpha/~admin", "get": "alpha", "exp": int(time.time()) + 60}), "x")
        self.assertEqual(c, 403)   # signed by another key
        o, c = self.admin("machines")
        self.assertEqual(c, 200)
        m = o["machines"][0]
        self.assertEqual((m["node"], m["role"], m["online"], m["hostname"]), (BOX, "Camera box", True, "BOX-01"))
        self.assertNotIn("key", m)
        self.assertNotIn("kid", m)

    def test_a_spoke_vouches_for_its_admin_and_mints_the_admins_token_itself(self):
        self.enroll()
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, st, hub=lambda: "http://hub.lan:4444", fed_token=lambda: "fed")
        self.addCleanup(spoke.close)
        fed = "Bearer " + kr._mint(self.svc.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))
        sent = []

        def hub_post(path, body, timeout=8):
            sent.append((path, json.loads(json.dumps(body))))
            return self.svc.rcx_fed(body, fed, "10.1.1.1")
        spoke._hub_post = hub_post
        o, c = spoke.token({"room": "alpha", "code": "adm-1", "host": ADM}, "10.2.0.5")
        tok = o["tokens"]["member"]
        d, c = spoke.rcx_admin_api({"op": "start", "node": BOX, "by": "Kenton"}, "Bearer " + tok, "10.2.0.5")
        self.assertEqual(c, 200, d)
        self.assertEqual(sent[0][0], "/api/rcx/fed")
        self.assertEqual((sent[0][1]["who"]["host"], sent[0][1]["who"]["kind"]), (ADM, "admin"))
        claims = kr.verify_token(d["token"], spoke.key)   # the spoke's key: the admin's page dials the spoke
        self.assertIsNotNone(claims)
        self.assertIsNone(kr.verify_token(d["token"], self.svc.key))
        p = ra.paths(d["sid"])
        self.assertEqual((claims["put"], claims["get"]), ([p["admin"]], [p["machine"], p["screen"]]))
        row = self.svc._rcx().audit_view()[0]
        self.assertEqual(row["from"], spoke._rcx_name() + " · 10.2.0.5")
        # a spoke's member token with no admin grant is refused at the spoke -- the hub never hears of it
        o, c = spoke.token({"room": "alpha", "code": "pub-1", "host": PUBH}, "10.2.0.6")
        n = len(sent)
        self.assertEqual(spoke.rcx_admin_api({"op": "machines"}, "Bearer " + o["tokens"]["member"], "x")[1], 403)
        self.assertEqual(len(sent), n)

    def test_the_hub_refuses_fed_calls_without_a_federation_token(self):
        o, c = self.svc.rcx_fed({"op": "admin", "req": {"op": "machines"}, "who": {"host": ADM}}, "Bearer " + self.tok(ADM, "adm-1"))
        self.assertEqual(c, 403)

    def test_a_spokes_operator_is_never_the_hubs(self):
        self.enroll()
        fed = "Bearer " + kr._mint(self.svc.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))
        d, c = self.svc.rcx_fed({"op": "admin", "req": {"op": "start", "node": BOX}, "who": {"host": ADM, "kind": "operator", "name": "x"}}, fed)
        self.assertEqual(c, 200)
        self.assertEqual(self.svc._rcx().sessions[d["sid"]]["kind"], "admin")


# ---- audit ------------------------------------------------------------------------------------------------------------------
class Audit(HubBase):
    def test_hub_rows_follow_the_session(self):
        self.enroll()
        sid = self.admin("start", node=BOX)[0]["sid"]
        row = self.admin("sessions")[0]["sessions"][0]
        self.assertEqual((row["state"], row["admin"], row["machine"], row["kind"]), ("pending", "Kenton", "BOX-01", "admin"))
        self.assertEqual(row["from"], self.svc._rcx_name() + " · 10.0.0.5")
        self.claim(sid)
        row = self.admin("sessions")[0]["sessions"][0]
        self.assertEqual(row["state"], "live")
        self.assertIsNotNone(row["start"])
        ts = int(time.time())
        o, c = self.svc.rcx_machine("end", {"node": BOX, "sid": sid, "ts": ts, "why": "hotkey", "mac": ra.mac(self.key, "end", sid, BOX, ts, "hotkey")}, "x")
        self.assertEqual(c, 200, o)
        row = self.admin("sessions")[0]["sessions"][0]
        self.assertEqual((row["state"], row["why"]), ("ended", "hotkey"))
        self.assertIsNotNone(row["end"])
        self.assertGreaterEqual(row["dur"], 0)

    def test_the_table_is_capped_kept_and_a_restart_ends_what_was_live(self):
        clock = Clock()
        reg = ra.HubRegistry(self.dir, clock=clock)
        reg.machines[BOX] = {"node": BOX, "key": self.key, "kid": ra.kid_of(self.key), "on": True, "at": clock.t, "hostname": "BOX-01",
                             "desktop": {"ok": True, "why": ""}, "monitors": []}
        for i in range(ra.AUDIT_MAX + 15):
            o, c = reg.start(BOX, 0, {"host": "a%03d-aa11" % (i % 900), "name": "A%d" % i})
            self.assertEqual(c, 200, o)
            reg.rates.clear()
            if i < ra.AUDIT_MAX + 14:
                reg.stop(o["sid"], {"name": "x"})
        self.assertEqual(len(reg.audit_view()), ra.AUDIT_MAX)
        reg2 = ra.HubRegistry(self.dir, clock=clock)   # the hub restarted
        rows = reg2.audit_view()
        self.assertEqual(len(rows), ra.AUDIT_MAX)
        self.assertEqual((rows[0]["state"], rows[0]["why"]), ("ended", "restart"))
        self.assertIn(BOX, reg2.machines)   # the pinned key survives
        with open(reg.path, encoding="utf-8") as f:
            self.assertNotIn(self.key, f.read())   # 0.21.92: the pinned key is sealed on disk
        self.assertEqual(reg2.machines[BOX]["key"], self.key)

    def test_the_machines_own_log_folds_per_session(self):
        d = tempfile.mkdtemp()
        ra.audit_append(d, {"ev": "start", "sid": "s" * 32, "admin": "Kenton", "from": "hub · 10.0.0.5", "start": 100, "state": "live"})
        ra.audit_append(d, {"ev": "end", "sid": "s" * 32, "end": 160, "dur": 60, "why": "bar", "state": "ended"})
        ra.audit_append(d, {"ev": "start", "sid": "t" * 32, "admin": "Ana", "from": "spoke · 10.0.0.6", "start": 200, "state": "live"})
        rows = ra.audit_sessions(d)
        self.assertEqual([r["sid"][0] for r in rows], ["t", "s"])
        self.assertEqual((rows[1]["admin"], rows[1]["dur"], rows[1]["why"], rows[1]["from"]), ("Kenton", 60, "bar", "hub · 10.0.0.5"))


# ---- the private path ------------------------------------------------------------------------------------------------------
class PrivatePath(HubBase):
    def test_no_room_token_covers_rcx_and_session_tokens_cover_only_their_session(self):
        sid = "ab" * 16
        p = ra.paths(sid)
        for code, host in (("adm-1", ADM), ("pub-1", PUBH), ("view-1", VIEW)):
            g = kr.claims_to_grant(kr.verify_token(self.tok(host, code), self.svc.key))
            for path in p.values():
                self.assertFalse(covers(g["subscribe"], path), (code, path))
                self.assertFalse(covers(g["publish"], path), (code, path))
        self.assertFalse(any(k.startswith(ra.NS) for k in kr.PUBLIC_KINDS))
        now = time.time()
        ga = kr.claims_to_grant(ra.admin_claims(sid, now + 60))
        gm = kr.claims_to_grant(ra.machine_claims(sid, now + 60))
        self.assertTrue(covers(ga["subscribe"], p["screen"]) and covers(ga["subscribe"], p["machine"]) and covers(ga["publish"], p["admin"]))
        self.assertFalse(covers(ga["publish"], p["screen"]) or covers(ga["publish"], p["machine"]))
        self.assertTrue(covers(gm["publish"], p["screen"]) and covers(gm["publish"], p["machine"]) and covers(gm["subscribe"], p["admin"]))
        other = ra.paths("cd" * 16)
        for g in (ga, gm):
            for path in other.values():
                self.assertFalse(covers(g["publish"], path) or covers(g["subscribe"], path))
            for path in ("alpha/x/y.hang", "alpha", "~state/alpha/" + ADM, "~presence/alpha"):
                self.assertFalse(covers(g["publish"], path), path)   # it speaks for nobody in any room
            for path in ("alpha/x/y.hang", "alpha", "alpha/%s/~member/p1" % ADM):
                self.assertFalse(covers(g["subscribe"], path), path)   # and sees no room (only the public kinds every grant has)
        self.assertEqual(kr.claims_role(ra.admin_claims(sid, now + 60)), "viewer")   # never a publisher anywhere
        self.assertFalse(kr.claims_admin_any(ra.admin_claims(sid, now + 60)))
        self.assertEqual(kr.claims_identity(ra.machine_claims(sid, now + 60)), (None, None))

    def test_a_session_that_is_over_is_refused_at_the_next_recheck(self):
        self.enroll()
        d, c = self.admin("start", node=BOX)
        sess = {"event": "connect", "id": "rs1", "remote": "10.0.0.5", "query": "jwt=" + d["token"]}
        g, c = self.svc.session(sess, "127.0.0.1")
        self.assertEqual(c, 200, g)
        self.assertIn(ra.paths(d["sid"])["screen"], g["subscribe"])
        self.admin("stop", sid=d["sid"])
        g, c = self.svc.session(dict(sess, event="revalidate"), "127.0.0.1")
        self.assertEqual(c, 403)
        g, c = self.svc.session({"event": "revalidate", "id": "rs1", "remote": "10.0.0.5"}, "127.0.0.1")   # no query: the stored grant
        self.assertEqual(c, 403)
        g, c = self.svc.session(dict(sess, id="rs2"), "127.0.0.1")   # a new connection with that token
        self.assertEqual((c, g.get("error")), (403, "that remote session is over"))

    def test_the_bridge_never_lists_saves_or_remembers_a_private_capture(self):
        import kastr_rtsp
        import kastr_screen
        saved = (kastr_screen.check_url, kastr_screen.overlay_start, kastr_screen.overlay_stop)
        kastr_screen.check_url = lambda url: None
        kastr_screen.overlay_start = lambda *a, **k: None
        kastr_screen.overlay_stop = lambda *a, **k: None
        try:
            b = kastr_rtsp.Bridge(state_dir=tempfile.mkdtemp())
            f = b.add_private("screen://monitor/1", "ab" * 16)
            self.assertEqual(b.list(), [])
            self.assertIs(b.get(f.id), f)   # the injector's share_info still finds it
            self.assertEqual(b._feed_records(), [])
            b._pubs[f.id] = types.SimpleNamespace(stopping=False, feed=f, broadcast="~rcx/x/s.hang", stop=lambda: None, paused=False, relay="http://hub:4443/?jwt=x")
            self.assertEqual(b._feed_records(), [])
            b.persist_feeds()
            with open(b._feeds_file(), encoding="utf-8") as fh:
                self.assertNotIn("~rcx", fh.read())
            self.assertTrue(b.remove_private(f.id))
            self.assertIsNone(b.get(f.id))
            self.assertEqual(b._removed, [])   # a later share of that screen in a room is not "closed"
            self.assertFalse(b.remove_private(12345))
            with self.assertRaises(ValueError):
                b.add_private("rtsp://cam/1", "x")
        finally:
            kastr_screen.check_url, kastr_screen.overlay_start, kastr_screen.overlay_stop = saved


# ---- timeouts ----------------------------------------------------------------------------------------------------------------
class Timeouts(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.key = ra.new_key()
        self.reg = ra.HubRegistry(None, clock=self.clock)
        self.reg.machines[BOX] = {"node": BOX, "key": self.key, "kid": ra.kid_of(self.key), "on": True, "at": self.clock.t,
                                  "hostname": "BOX-01", "desktop": {"ok": True, "why": ""}, "monitors": []}

    def start(self):
        o, c = self.reg.start(BOX, None, {"host": ADM, "name": "Kenton"})
        self.assertEqual(c, 200, o)
        return o["sid"]

    def test_an_unclaimed_control_ends_no_answer(self):
        sid = self.start()
        self.clock.t += ra.PENDING_S + 1
        st = self.reg.status(sid)[0]
        self.assertEqual((st["state"], st["why"]), ("ended", "noanswer"))
        self.assertIsNone(self.reg.audit_view()[0]["end"])   # it never started: no end time, no duration

    def test_a_machine_gone_quiet_and_the_time_limit(self):
        sid = self.start()
        ts = int(self.clock.t)
        self.assertEqual(self.reg.claim({"node": BOX, "sid": sid, "ts": ts, "mac": ra.mac(self.key, "claim", sid, BOX, ts)})[1], 200)
        self.clock.t += ra.LOST_S + 1
        self.assertEqual(self.reg.status(sid)[0]["why"], "lost")
        self.reg.machines[BOX]["at"] = self.clock.t
        sid2 = self.start()
        ts = int(self.clock.t)
        self.reg.claim({"node": BOX, "sid": sid2, "ts": ts, "mac": ra.mac(self.key, "claim", sid2, BOX, ts)})
        self.clock.t += ra.SESSION_MAX_S + 1
        self.reg.machines[BOX]["at"] = self.clock.t
        self.assertEqual(self.reg.status(sid2)[0]["why"], "limit")

    def test_a_held_poll_wakes_on_a_start(self):
        out = {}
        reg = ra.HubRegistry(None)
        reg.machines[BOX] = dict(self.reg.machines[BOX], at=time.time())

        def poll():
            out["r"] = reg.poll(poll_body(self.key, wait=5), via="hub")
        t = threading.Thread(target=poll)
        t0 = time.monotonic()
        t.start()
        time.sleep(0.3)
        o, c = reg.start(BOX, None, {"host": ADM, "name": "Kenton"})
        t.join(6)
        self.assertLess(time.monotonic() - t0, 3.0)
        self.assertEqual(out["r"][0]["start"][0]["sid"], o["sid"])


# ---- the agent, end to end against an in-process hub ------------------------------------------------------------------------
class FakeBridge:
    def __init__(self):
        self.feeds, self.pubs, self.retargets, self.removed, self.next = {}, {}, [], [], 50
        self.rc = None

    def add_private(self, url, tag):
        f = types.SimpleNamespace(id=self.next, url=url, private=tag)
        self.feeds[f.id] = f
        self.next += 1
        return f

    def publish(self, fid, broadcast, relay, audio=True, keep=None, label=""):
        p = types.SimpleNamespace(broadcast=broadcast, relay=relay, audio=audio, keep=keep, minter=None, suspended=True, started=0, paused=False)
        p.start = lambda p=p: setattr(p, "started", p.started + 1)
        self.pubs[fid] = p
        return p

    def retarget(self, fid, url):   # what Bridge.retarget does to a grant: control was for the old target
        self.feeds[fid].url = url
        self.retargets.append((fid, url))
        self.rc.share_gone(fid, "retarget")

    def remove_private(self, fid):
        self.removed.append(fid)
        self.feeds.pop(fid, None)
        self.pubs.pop(fid, None)


class FakeProc:
    killed = False

    def kill(self):
        self.killed = True


class AgentEndToEnd(HubBase):
    def setUp(self):
        super().setUp()
        self.sd = tempfile.mkdtemp()
        ra.set_optin(self.sd, True)
        self.key = ra.load_settings(self.sd)["key"]
        self.bridge = FakeBridge()
        self.backend = rc.MockBackend(rects={"screen://monitor/1": {"x": 0, "y": 0, "w": 1280, "h": 720},
                                             "screen://window/77": {"x": 100, "y": 100, "w": 640, "h": 400}})
        self.ui = types.SimpleNamespace(shown=[], cleared=[], show=lambda *a, **k: self.ui.shown.append(a), clear=lambda f: self.ui.cleared.append(f), rect=lambda f: None)
        self.rc = rc.RemoteControl(backend=self.backend, share_info=self.info, caps=(True, "", "mock"), ui=self.ui, monitor=False)
        self.bridge.rc = self.rc
        self.procs = []
        self.saved = (ra.POLL_WAIT_S, ra.desktop_state, ra.list_monitors, ra.is_elevated)
        ra.POLL_WAIT_S = 0.2
        ra.desktop_state = lambda: {"ok": True, "why": ""}
        ra.list_monitors = lambda: [{"index": 1, "name": "Screen 1", "width": 1280, "height": 720, "primary": True}]
        ra.is_elevated = lambda: False
        self.agent = ra.Agent(self.sd, bridge=self.bridge, relay_url=lambda: "http://hub.lan:4443", log=lambda m: None, node=BOX,
                              web_port=lambda: 8791, info=lambda: {"operator": "Box", "mode": "publisher"}, http=self.http,
                              launch=self.launch, rc=self.rc)

    def tearDown(self):
        ra.POLL_WAIT_S, ra.desktop_state, ra.list_monitors, ra.is_elevated = self.saved
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

    def live(self):
        self.agent.tick()   # enroll
        self.agent.tick()   # listed
        m = self.admin("machines")[0]["machines"]
        self.assertEqual([x["node"] for x in m], [BOX])
        d, c = self.admin("start", node=BOX)
        self.assertEqual(c, 200, d)
        self.agent.tick()   # the poll carries the start; begin() runs on its own thread
        self.wait(lambda: self.agent.session and self.agent.session.get("state") == "live")
        return d

    def test_control_starts_with_no_prompt_and_the_pill_names_the_admin(self):
        d = self.live()
        sid, s = d["sid"], self.agent.session
        p = ra.paths(sid)
        fid = s["feed"]
        self.assertEqual(self.bridge.feeds[fid].url, "screen://monitor/1")
        self.assertEqual(self.bridge.feeds[fid].private, sid)
        pub = self.bridge.pubs[fid]
        self.assertEqual((pub.broadcast, pub.audio, pub.keep), (p["screen"], False, False))
        self.assertEqual(pub.started, 1)   # the box's camera switch was off: the admin's capture runs anyway
        tok = pub.relay.split("jwt=", 1)[1]
        self.assertTrue(pub.relay.startswith("http://hub.lan:4443/?jwt="))
        self.assertEqual(kr.verify_token(tok, self.svc.key)["put"], [p["machine"], p["screen"]])
        self.assertEqual(pub.minter(), pub.relay)   # never a room token for this path
        g = self.rc.grant
        self.assertEqual((g["rcid"], g["controller"], g["name"], g["feed"]), (s["rcid"], ADM, "Kenton", fid))
        self.assertEqual(g["bar"], "Kenton (fleet admin) is controlling this machine — Stop control (Ctrl+Alt+Space)")
        self.assertEqual(self.ui.shown[-1][3], g["bar"])
        self.assertEqual(self.ui.shown[-1][2], "control")
        self.assertEqual(self.procs[0][:2], (sid, s["pk"]))
        # the helper page gets its session only with the page key
        self.assertEqual(self.agent.page_session(sid, "wrong")[1], 404)
        ps, c = self.agent.page_session(sid, s["pk"])
        self.assertEqual((c, ps["paths"], ps["adminHost"], ps["quiet"]), (200, p, ADM, ra.QUIET_S))
        self.assertEqual(self.admin("status", sid=sid)[0]["state"], "live")
        rows = ra.audit_sessions(self.sd)
        self.assertEqual((rows[0]["sid"], rows[0]["admin"], rows[0]["state"]), (sid, "Kenton", "live"))
        # the admin's input lands (the helper page hands it over exactly like the 0.21.80 sharer page)
        st, c = self.rc.inject(s["rcid"], ADM, [{"t": "d", "b": 0, "x": 0.5, "y": 0.5}, {"t": "u", "b": 0, "x": 0.5, "y": 0.5}])
        self.assertEqual(c, 200, st)
        self.assertEqual([e[:3] for e in self.backend.events if e[0] == "button"], [("button", 0, True), ("button", 0, False)])
        self.assertEqual(self.rc.inject(s["rcid"], PUBH, [{"t": "m", "x": 0.1, "y": 0.1}])[1], 403)   # nobody else's

    def test_switching_sources_keeps_control(self):
        d = self.live()
        s = self.agent.session
        rcid = s["rcid"]
        o, c = self.agent.switch("screen://window/77")
        self.assertEqual(c, 200, o)
        self.assertEqual(self.bridge.retargets, [(s["feed"], "screen://window/77")])
        g = self.rc.grant
        self.assertEqual((g["rcid"], g["url"], g["controller"]), (rcid, "screen://window/77", ADM))   # the same grant id: no new session
        self.assertEqual(self.agent.session["sid"], d["sid"])
        time.sleep(0.8)   # the watcher must not take the switch for an end
        self.assertIsNotNone(self.agent.session)
        for bad in ("screen://tab/1/2", "rtsp://x", "file:///etc/passwd", "screen://monitor/x"):
            self.assertEqual(self.agent.switch(bad)[1], 400)
        o, c = self.agent.switch("screen://monitor/99")   # All monitors
        self.assertEqual(c, 200, o)
        o, c = self.agent.front("screen://window/77")
        self.assertEqual((c, o["front"]), (200, True))
        self.assertEqual(self.backend.raised[-1], "screen://window/77")
        self.backend.focus = False
        o, c = self.agent.front("screen://window/77")
        self.assertEqual((o["ok"], o["front"]), (False, False))   # "Windows refused ..." -- said, not hidden
        self.assertEqual(self.agent.front("screen://monitor/1")[1], 400)

    def test_ctrl_alt_space_ends_it_and_both_logs_say_so(self):
        d = self.live()
        fid = self.agent.session["feed"]
        self.rc.hotkey()
        self.wait(lambda: self.agent.session is None)
        st = self.admin("status", sid=d["sid"])[0]
        self.assertEqual((st["state"], st["why"]), ("ended", "hotkey"))
        self.assertEqual(self.bridge.removed, [fid])
        self.assertTrue(self.procs[0][2].killed)
        rows = ra.audit_sessions(self.sd)
        self.assertEqual((rows[0]["why"], rows[0]["state"]), ("hotkey", "ended"))
        hub = self.admin("sessions")[0]["sessions"][0]
        self.assertEqual((hub["why"], hub["state"]), ("hotkey", "ended"))
        self.assertTrue(self.svc._rcx_is_dead(d["sid"]))   # its tokens are refused at the next re-check

    def test_the_lease_times_out_like_a_normal_grant(self):
        clock = Clock(5000.0)
        self.rc.clock = clock
        d = self.live()
        clock.t += rc.LEASE_S + 1   # the helper page stopped renewing (it closed, or the admin went quiet)
        self.rc.check()
        self.wait(lambda: self.agent.session is None)
        self.assertEqual(self.admin("status", sid=d["sid"])[0]["why"], "timeout")

    def test_the_admin_stops_it(self):
        d = self.live()
        self.admin("stop", sid=d["sid"])
        self.agent.tick()   # the poll carries the stop
        self.assertIsNone(self.agent.session)
        self.assertIsNone(self.rc.grant)
        self.assertEqual(ra.audit_sessions(self.sd)[0]["why"], "admin")

    def test_unticking_ends_a_running_session(self):
        d = self.live()
        ra.set_optin(self.sd, False)
        self.agent.tick()
        self.assertIsNone(self.agent.session)
        st = self.admin("status", sid=d["sid"])[0]
        self.assertEqual((st["state"], st["why"]), ("ended", "off"))
        self.assertEqual(self.admin("machines")[0]["machines"], [])

    def test_a_forged_hub_answer_is_refused(self):
        self.agent.tick(); self.agent.tick()
        d, c = self.admin("start", node=BOX)
        real = self.svc.rcx_machine

        def forged(op, p, peer=""):
            o, code = real(op, p, peer)
            if op == "claim" and code == 200:
                o = dict(o, admin="Mallory")   # a relay in the middle changed who it is for
            return o, code
        self.svc.rcx_machine = forged
        self.agent.tick()
        self.wait(lambda: self.agent.session is None and self.admin("status", sid=d["sid"])[0]["state"] == "ended")
        self.assertIsNone(self.rc.grant)
        self.assertEqual(self.bridge.pubs, {})

    def test_nobody_signed_in(self):
        ra.desktop_state = lambda: {"ok": False, "why": "nosession"}
        self.agent.tick(); self.agent.tick()
        m = self.admin("machines")[0]["machines"][0]
        self.assertEqual(m["desktop"], {"ok": False, "why": "nosession"})
        o, c = self.admin("start", node=BOX)
        self.assertEqual(o["error"], "nobody is signed in on " + m["hostname"])


# ---- All monitors, Windows admin windows, the pages -----------------------------------------------------------------------------
class AllMonitors(unittest.TestCase):
    def test_union_and_capture_args(self):
        import kastr_screen
        import kastr_x11
        self.assertEqual(rc.union_rect([{"x": 0, "y": 0, "w": 1280, "h": 720}, {"x": 1280, "y": 0, "w": 1920, "h": 1080}]),
                         {"x": 0, "y": 0, "w": 3200, "h": 1080})
        mons = [{"index": 1, "rect": {"x": 0, "y": 0, "w": 1280, "h": 720}}, {"index": 2, "rect": {"x": 1280, "y": 0, "w": 1280, "h": 720}}]
        saved = (kastr_screen.LINUX, kastr_screen.WINDOWS, kastr_x11.list_monitors)
        try:
            kastr_screen.LINUX, kastr_screen.WINDOWS = True, False
            kastr_x11.list_monitors = lambda: mons
            self.assertEqual(kastr_screen._resolve("monitor", 99)["rect"], {"x": 0, "y": 0, "w": 2560, "h": 720})
            os.environ.setdefault("DISPLAY", ":99")
            args = kastr_screen.capture_input("screen://monitor/99")
            self.assertEqual(args[args.index("-video_size") + 1], "2560x720")
            self.assertEqual(kastr_screen.capture_size("screen://monitor/99"), (2560, 720))   # raw: the publisher scales it (wide)
            kastr_screen.LINUX, kastr_screen.WINDOWS = False, True
            args = kastr_screen.capture_input("screen://monitor/99", cursor=False, fps=30)
            self.assertEqual(args, ["-f", "gdigrab", "-framerate", "30", "-draw_mouse", "0", "-i", "desktop"])
        finally:
            kastr_screen.LINUX, kastr_screen.WINDOWS, kastr_x11.list_monitors = saved
        self.assertEqual(rc.surface_of("screen://monitor/99"), ("monitor", 99))
        self.assertEqual(ra.ALL_MONITORS, kastr_screen.ALL_MONITORS)
        self.assertEqual(ra.ALL_MONITORS, rc.ALL_MONITORS)

    def test_admin_windows_note(self):
        self.assertEqual(ra.admin_windows("win32", False), "limited")
        self.assertEqual(ra.admin_windows("win32", True), "full")
        self.assertEqual(ra.admin_windows("linux", False), "full")
        src = read("kastr_rcadmin.py")
        for name in ("elevated_install", "elevated_start", "schtasks", "runas"):   # 0.21.83: no elevated helper (part A cancelled it)
            self.assertNotIn(name, src)


class LateAdditions(HubBase):
    """What the WSL lab found (v02183): the switch freeze, the st.json heartbeat, the off notice, the Xlib crash."""

    def test_retarget_ends_the_old_pair_ffmpeg_first_without_a_ladder_restart(self):
        import kastr_rtsp
        order = []

        class P:
            def __init__(self, name, on_kill=None):
                self.name, self.alive, self.pid, self.on_kill = name, True, 100 + len(order), on_kill

            def poll(self):
                return None if self.alive else 0

            def kill(self):
                order.append("kill " + self.name)
                self.alive = False
                if self.on_kill:
                    self.on_kill()

            def wait(self, timeout=None):
                order.append("wait " + self.name + (" (exited)" if not self.alive else ""))
                return 0
        mq = P("moq")
        ff = P("ffmpeg", on_kill=lambda: setattr(mq, "alive", False))   # moq sees EOF and closes its session
        bridge = types.SimpleNamespace(_child_ended=lambda pid: None, log=lambda m: None)
        pub = kastr_rtsp.Publisher(bridge, types.SimpleNamespace(url="screen://monitor/1", sar=None, id=1), "~rcx/x/s.hang", "http://r/", audio=False)
        pub.procs, gen = (ff, mq), pub._gen
        pub._timer = types.SimpleNamespace(cancel=lambda: order.append("timer cancelled"))
        self.assertTrue(pub.quiet())
        self.assertIn("timer cancelled", order)   # a queued ladder tick never starts the old target again
        self.assertEqual([o for o in order if o.startswith("kill")][0], "kill ffmpeg")
        self.assertNotIn("kill moq", order)   # it ended by itself -- the relay withdrew the broadcast at once
        self.assertGreater(pub._gen, gen)    # the old pair's watcher returns without a ladder restart
        self.assertIsNone(pub._timer)
        # Bridge.retarget: quiet first, then the new pair
        import kastr_screen
        saved = (kastr_screen.check_url, kastr_screen.overlay_start, kastr_screen.overlay_stop)
        kastr_screen.check_url = lambda u: None
        kastr_screen.overlay_start = lambda *a, **k: None
        kastr_screen.overlay_stop = lambda *a, **k: None
        try:
            b = kastr_rtsp.Bridge(state_dir=tempfile.mkdtemp())
            f = b.add_private("screen://monitor/1", "ab" * 16)
            calls = []
            b._pubs[f.id] = types.SimpleNamespace(feed=f, broadcast="~rcx/x/s.hang", paused=False, stopping=False, relay="http://r/?jwt=x",
                                                 quiet=lambda: calls.append("quiet"), nudge=lambda why: calls.append("nudge " + why))
            b.retarget(f.id, "screen://monitor/2")
            self.assertEqual(calls, ["quiet", "nudge retarget"])
        finally:
            kastr_screen.check_url, kastr_screen.overlay_start, kastr_screen.overlay_stop = saved

    def test_the_switch_answers_at_once_or_after_the_new_captures_output(self):
        self.assertEqual(ra.SWITCH_WAIT_S, 0)   # the measured default: the player finds the new broadcast by itself
        sd = tempfile.mkdtemp()
        ra.set_optin(sd, True)
        bridge = FakeBridge()
        r = rc.RemoteControl(backend=rc.MockBackend(rects={"screen://monitor/1": {"x": 0, "y": 0, "w": 10, "h": 10},
                                                           "screen://monitor/2": {"x": 10, "y": 0, "w": 10, "h": 10}}),
                             share_info=lambda fid: {"url": bridge.feeds[fid].url, "live": True, "paused": False} if fid in bridge.feeds else None,
                             caps=(True, "", "mock"), ui=None, monitor=False)
        bridge.rc = r
        f = bridge.add_private("screen://monitor/1", "s" * 32)
        pub = bridge.publish(f.id, "~rcx/s/s.hang", "http://r/?jwt=x")
        pub.flowingAt = None
        bridge._pubs = bridge.pubs
        a = ra.Agent(sd, bridge=bridge, rc=r, node=BOX, log=lambda m: None)
        a.session = {"sid": "s" * 32, "state": "live", "feed": f.id, "url": "screen://monitor/1", "rcid": "abcdefgh1234", "adminHost": ADM,
                     "admin": "Kenton", "color": "#009fda", "paths": ra.paths("s" * 32)}
        o, c = a.switch("screen://monitor/2")
        self.assertEqual((c, o["live"]), (200, None))
        saved = ra.SWITCH_WAIT_S
        ra.SWITCH_WAIT_S = 0.6
        try:
            threading.Timer(0.15, lambda: setattr(pub, "flowingAt", time.time())).start()
            o, c = a.switch("screen://monitor/1")
            self.assertEqual((c, o["live"]), (200, True))
            self.assertGreaterEqual(o["ms"], 100)
            o, c = a.switch("screen://monitor/2")   # no output this time: it says so after the wait
            self.assertEqual((c, o["live"]), (200, False))
        finally:
            ra.SWITCH_WAIT_S = saved
        self.assertEqual(r.grant["rcid"], "abcdefgh1234")

    def test_unticking_tells_the_hub_at_once(self):
        sd = tempfile.mkdtemp()
        ra.set_optin(sd, True)
        key = ra.load_settings(sd)["key"]
        self.svc.rcx_machine("poll", poll_body(key, enroll=True), "x")
        self.assertTrue(self.svc._rcx().machines[BOX]["on"])
        a = ra.Agent(sd, relay_url=lambda: "http://hub.lan:4443", node=BOX, log=lambda m: None,
                     http=lambda url, body, t: self.svc.rcx_machine(url.rsplit("/", 1)[1], json.loads(json.dumps(body)), "x"))
        saved = (ra.desktop_state, ra.list_monitors, ra.is_elevated)
        ra.desktop_state, ra.list_monitors, ra.is_elevated = (lambda: {"ok": True, "why": ""}), (lambda: []), (lambda: False)
        try:
            ra.set_optin(sd, False)
            a.tell_off()
            t0 = time.monotonic()
            # tell_off records a.last in its own thread only after the hub answers -- wait for both
            while (self.svc._rcx().machines[BOX]["on"] or (a.last or {}).get("state") != "off") and time.monotonic() - t0 < 3:
                time.sleep(0.05)
        finally:
            ra.desktop_state, ra.list_monitors, ra.is_elevated = saved
        self.assertFalse(self.svc._rcx().machines[BOX]["on"])
        self.assertEqual(a.last["state"], "off")
        self.assertEqual(self.admin("machines")[0]["machines"], [])

    def test_a_new_or_freshly_ticked_machine_hears_listed_at_once(self):
        t0 = time.monotonic()
        o, c = self.svc.rcx_machine("poll", dict(poll_body(self.key, enroll=True), wait=20), "x")
        self.assertEqual(c, 200)
        self.assertLess(time.monotonic() - t0, 2.0)   # never held on the first poll

    def test_display_probes_are_cached_and_one_at_a_time(self):
        n = []

        def slow():
            n.append(threading.get_ident())
            time.sleep(0.05)
            return {"ok": True}
        ra._PROBE.pop("t", None)
        ts = [threading.Thread(target=lambda: ra._cached("t", 5.0, slow)) for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(n), 1)
        self.assertEqual(ra._cached("t", 5.0, slow), {"ok": True})
        self.assertIsNone(ra._cached("boom", 5.0, lambda: 1 / 0))   # a failing probe answers None, never raises

    def test_xlib_is_made_thread_safe_before_its_first_call(self):
        src = read("kastr_x11.py")
        i = src.index("def _x11():")
        body = src[i:src.index("def _xtst():")]
        self.assertLess(body.index("XInitThreads()"), body.index("x.XOpenDisplay.restype"))

    def test_stop_sharing_on_a_private_capture_and_the_pill_wording(self):
        import kastr_rtsp
        import kastr_screen
        saved = (kastr_screen.check_url, kastr_screen.overlay_start, kastr_screen.overlay_stop)
        kastr_screen.check_url = lambda u: None
        kastr_screen.overlay_start = lambda *a, **k: None
        kastr_screen.overlay_stop = lambda *a, **k: None
        try:
            b = kastr_rtsp.Bridge(state_dir=tempfile.mkdtemp())
            f = b.add_private("screen://monitor/1", "ab" * 16)
            self.assertTrue(b.remove(f.id))   # the pill's Stop sharing (share_stop -> Bridge.remove)
            self.assertIsNone(b.get(f.id))
            self.assertEqual(b._removed, [])
        finally:
            kastr_screen.check_url, kastr_screen.overlay_start, kastr_screen.overlay_stop = saved
        shown = []
        ui = types.SimpleNamespace(show=lambda *a, **k: shown.append(a[3]), clear=lambda f: None, rect=lambda f: None)
        r = rc.RemoteControl(backend=rc.MockBackend(rects={"screen://monitor/1": {"x": 0, "y": 0, "w": 10, "h": 10}}),
                             share_info=lambda fid: {"url": "screen://monitor/1", "live": True, "paused": False},
                             caps=(True, "", "mock"), ui=ui, monitor=False)
        o, c = r.start("abcdefgh1234", ADM, "Kenton", 5, "~rcx/x/s.hang", bar=ra.pill_text("Kenton"))
        self.assertEqual(c, 200, o)
        self.assertEqual(shown[-1], "Kenton (fleet admin) is controlling this machine — Stop control (Ctrl+Alt+Space)")
        r.end(None, "bar")
        o, c = r.start("abcdefgh5678", ADM, "Kenton", 5, "alpha/x/s.hang")   # a room grant keeps the A' pill
        self.assertEqual(shown[-1], rc.bar_label("Kenton", False))

    def test_the_helper_page_and_the_view(self):
        a = read("rcx-agent.html")
        self.assertIn("if (!d.re && d.ptr)", a)   # a renew's answer (it carries ptr) reaches stPush -- st.json is the admin's heartbeat
        self.assertLess(a.index("if (!d.re && d.ptr)"), a.index('d.re === "renew"'))
        self.assertIn("ctlQ = ctlQ.then(() => ctlRun(v, n))", a)   # switcher requests one at a time, each answered with its own number
        self.assertIn("srcWrite();   // the switch's answer first", a)
        v = read("rcx.html")
        self.assertIn('c.wurl + "&rs=" + c.rs', v)   # the player's own session: a re-subscribe never touches the JSON tracks
        self.assertIn("[hidden] { display:none !important; }", v)
        self.assertIn('last.op === "src"', v)
        self.assertIn("SW_SELF_MS = 1200", v)


class Wiring(unittest.TestCase):
    def test_page(self):
        p = read("moq-watch-lite.html")
        for s in ('id="optMachines"', 'id="machinesPop"', 'authRole === "admin"', 'window.open("/rcx.html"', '"kastr-rcx-session"',
                  "Minimize, move, resize and close need KASTR to run as administrator on ", "Nobody is signed in on ", 'op: "start"', "window.__kastrMachines"):
            self.assertIn(s, p)
        v = read("rcx.html")
        for s in ('"kastr-rcx-ready"', "e.origin !== location.origin", 'delay="instant"', 'buffer="0ms"', 'priority="255"', '"in.json"', '"ctl.json"',
                  'op: "src"', 'op: "front"', "Switching to ", "stepMon", "PageDown", "All monitors", "Minimize, move, resize and close need KASTR to run as administrator on "):
            self.assertIn(s, v)
        a = read("rcx-agent.html")
        for s in ("/api/rc/ws", "/api/rcadmin/session", "/api/rcadmin/ctl", '"st.json", "ptr.json", "src.json"', "history.replaceState", 'finish("timeout"'):
            self.assertIn(s, a)
        b = read("assets/asi-brand.js")
        self.assertIn("rmachbtn", b)

    def test_relay_page(self):
        r = read("relay.html")
        for s in ('id="rcxOn"', "Let fleet admins control this machine without asking", '"X-KASTR-RC": "1"', "box.disabled = !LOCAL",
                  "Remote sessions", "/api/relay/rcx", "meshRcxBtn(n.node)", "meshRcxBtn(c.node)", "This machine's sessions"):
            self.assertIn(s, r)
        self.assertEqual(r.count("\r\n"), r.count("\n"))

    def test_server_and_build(self):
        import build
        self.assertIn("rcx.html", build.PAGES)
        self.assertIn("rcx-agent.html", build.PAGES)
        self.assertIn('"--hidden-import", "kastr_rcadmin"', read("build.py"))
        s = read("kastr_serve.py")
        for x in ('"/api/rcx/poll"', '"/api/rcadmin/session"', "_rcadmin_start(srv, bridge, relay_srv, relay_ref, hostname)"):
            self.assertIn(x, s)
        self.assertIn("/api/relay/rcx", kr.GUARDED_POSTS)
        self.assertIn("kastr_rcadmin.BROWSER[0]", read("kastr.py"))
        for name in ("kastr_serve.py", "moq-watch-lite.html", "kastr_rtsp.py", "kastr_screen.py", "kastr.py", "build.py"):
            t = read(name)
            self.assertEqual(t.count("\r\n"), t.count("\n"), name)
        for name in ("kastr_relay.py", "kastr_rcadmin.py", "kastr_rc.py"):
            self.assertEqual(read(name).count("\r\n"), 0, name)


if __name__ == "__main__":
    unittest.main()
