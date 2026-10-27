# -*- coding: utf-8 -*-
"""v0.21.91 PASSCODE RESET (Kenton: "Yes, in People + hub Relay page"). An admin-code holder (People: a person's menu) or the hub's
operator (Relay page: the My rooms card) gives someone's My room a TEMPORARY passcode, or removes it. The hub marks the record
`mustChange` (any later code change clears it): the temporary code opens nothing -- no My room token, no Messages key -- until
the person picks their own (POST /api/rooms/personal {op: "change"}); their messages key then asks for the previous passcode.
{op: "list"} gives admins the names with a My room (never a code, a hash or a slug); every reset / remove is audited with who
did it (never a code). Loopback sockets only (ephemeral ports), no outside network."""
import base64, io, json, os, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

JANE_OLD = "jane-own-code-1"
TEMP = "abc-def-ghk"
JANE_NEW = "jane-new-code-2"


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def _read(rel):
    with io.open(os.path.join(HERE, rel), encoding="utf-8", newline="") as f:
        return f.read()


def _file(path):
    with open(path, "rb") as f:
        return f.read()


def member(svc, room, host, code):
    o, c = svc.token({"room": room, "code": code, "host": host}, "10.0.0.7")
    assert c == 200, o
    return o["tokens"]["member"]


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.st = store(self.dir)
        self.lo = kr.Lockout()
        o, c = self.op({"op": "create", "name": "Jane Doe", "code": JANE_OLD, "access": "view-1"})
        assert c == 200, o
        self.slug = o["slug"]

    def op(self, body, peer="10.0.0.5", **kw):
        return kr.personal_op(self.st, body, peer, None, self.lo, **kw)

    def test_reset_sets_must_change_and_their_own_code_clears_it(self):
        self.assertEqual(self.op({"op": "reset", "name": "Jane Doe", "code": TEMP})[1], 403)          # not an admin
        o, c = self.op({"op": "reset", "name": "jane doe", "code": TEMP}, admin=True, who={"name": "Kenton", "host": "kentonpc-1a2b"})
        self.assertEqual((c, o["mustChange"], o["cleared"]), (200, True, False), o)
        self.assertNotIn(TEMP, json.dumps(o))
        self.assertTrue(self.st.personal_must("Jane Doe"))
        o, c = self.op({"op": "open", "name": "Jane Doe", "code": TEMP})
        self.assertEqual((c, o.get("mustChange"), o["slug"]), (200, True, self.slug))                  # opens -- and says so
        # pick their own: the temporary one proves it; not the temporary one again; at least 8
        self.assertEqual(self.op({"op": "change", "name": "Jane Doe", "code": "wrong-code", "newCode": JANE_NEW})[0].get("wrong"), True)
        self.assertEqual(self.op({"op": "change", "name": "Jane Doe", "code": TEMP, "newCode": TEMP})[1], 400)
        self.assertEqual(self.op({"op": "change", "name": "Jane Doe", "code": TEMP, "newCode": "short"})[1], 400)
        o, c = self.op({"op": "change", "name": "Jane Doe", "code": TEMP, "newCode": JANE_NEW}, peer="10.0.0.6")
        self.assertEqual((c, o["slug"]), (200, self.slug), o)
        self.assertFalse(self.st.personal_must("Jane Doe"))
        self.assertEqual(self.op({"op": "open", "name": "Jane Doe", "code": TEMP}, peer="10.0.0.9")[1], 403)
        o, c = self.op({"op": "open", "name": "Jane Doe", "code": JANE_NEW}, peer="10.0.0.9")
        self.assertEqual((c, "mustChange" in o), (200, False))
        # ANY code change clears it (Messages' recode / setup go through personal_reset without the flag)
        self.op({"op": "reset", "name": "Jane Doe", "code": TEMP}, admin=True)
        self.assertTrue(self.st.personal_must("Jane Doe"))
        self.st.personal_reset("Jane Doe", JANE_NEW)
        self.assertFalse(self.st.personal_must("Jane Doe"))
        # survives a restart; the file never holds a code
        self.op({"op": "reset", "name": "Jane Doe", "code": TEMP}, admin=True)
        self.assertTrue(kr.AuthStore(self.dir).personal_must("Jane Doe"))
        raw = _file(os.path.join(self.dir, "relay-auth.json")).decode("utf-8")
        for code in (TEMP, JANE_OLD, JANE_NEW):
            self.assertNotIn(code, raw)

    def test_list_names_only_and_admin_only(self):
        self.op({"op": "create", "name": "Kris Price", "code": "kris-code-123", "access": "view-1"})
        self.assertEqual(self.op({"op": "list"})[1], 403)
        self.op({"op": "reset", "name": "Kris Price", "code": TEMP}, admin=True)
        o, c = self.op({"op": "list"}, admin=True)
        self.assertEqual(c, 200, o)
        self.assertEqual([r["name"] for r in o["people"]], ["Jane Doe", "Kris Price"])
        self.assertEqual([r["mustChange"] for r in o["people"]], [False, True])
        self.assertEqual(set(o["people"][0]), {"name", "used", "made", "mustChange"})
        blob = json.dumps(o)
        rec = self.st.room(self.slug)
        for secret in (TEMP, JANE_OLD, "kris-code-123", self.slug, rec["hash"], rec["salt"], rec["roomKey"]):
            self.assertNotIn(secret, blob)

    def test_audit_never_holds_a_code(self):
        self.op({"op": "reset", "name": "Jane Doe", "code": TEMP}, admin=True, who={"name": "Kenton", "host": "kentonpc-1a2b", "relay": "hub"})
        self.op({"op": "reset", "name": "Jane Doe"}, admin=True, who={"name": "relay operator"})
        self.assertIsNone(self.st.room(self.slug))                                                     # removed
        self.assertEqual(self.op({"op": "reset", "name": "Jane Doe"}, admin=True)[1], 404)             # nothing more to remove
        au = self.op({"op": "list"}, admin=True)[0]["audit"]
        self.assertEqual([(a["op"], a["name"], a["by"]) for a in au], [("remove", "Jane Doe", "relay operator"), ("reset", "Jane Doe", "Kenton")])
        self.assertEqual((au[1]["host"], au[1]["relay"]), ("kentonpc-1a2b", "hub"))
        self.assertTrue(all(abs(a["at"] - time.time()) < 60 for a in au))
        raw = _file(os.path.join(self.dir, "relay-auth.json")).decode("utf-8")
        self.assertIn('"personalAudit"', raw)
        self.assertNotIn(TEMP, raw)
        self.assertNotIn(TEMP, json.dumps(au))
        self.assertEqual(len(kr.AuthStore(self.dir).personal_audit_view(50)), 2)                       # kept across a restart


class Service(unittest.TestCase):
    """The temporary code opens no My room token and no Messages key until they pick their own."""

    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        o, c = kr.personal_op(self.svc.store, {"op": "create", "name": "Jane Doe", "code": JANE_OLD, "access": "pub-1"}, "10.0.0.5")
        assert c == 200, o
        self.slug = o["slug"]

    def tearDown(self):
        self.svc.close()

    def test_mint_and_messages_wait_for_their_own_code(self):
        kr.personal_op(self.svc.store, {"op": "reset", "name": "Jane Doe", "code": TEMP}, admin=True)
        o, c = self.svc.token({"room": self.slug, "code": "pub-1", "host": "janepc-1a2b", "roomCode": TEMP}, "10.0.0.7")
        self.assertEqual((c, o.get("mustChange")), (403, True), o)
        self.assertNotIn("tokens", o)
        m = self.svc._msgr()
        o, c = m.api({"op": "unlock", "name": "Jane Doe", "code": TEMP}, "janepc-1a2b")
        self.assertEqual((c, o.get("mustChange")), (409, True), o)
        o, c = m.api({"op": "unlock", "name": "Jane Doe", "code": "not-her-code"}, "janepc-1a2b")
        self.assertEqual((c, o.get("wrong")), (403, True))                                              # a wrong code is still just wrong
        kr.personal_op(self.svc.store, {"op": "change", "name": "Jane Doe", "code": TEMP, "newCode": JANE_NEW}, "10.0.0.5")
        o, c = self.svc.token({"room": self.slug, "code": "pub-1", "host": "janepc-1a2b", "roomCode": JANE_NEW}, "10.0.0.7")
        self.assertEqual(c, 200, o)
        self.assertTrue(self.svc.store.personal_list()[0]["used"] > 0)                                 # "last used"
        o, c = m.api({"op": "unlock", "name": "Jane Doe", "code": JANE_NEW}, "janepc-1a2b")
        self.assertEqual(c, 200, o)


class Federation(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        kr.personal_op(self.hub.store, {"op": "create", "name": "Jane Doe", "code": JANE_OLD, "access": "pub-1"}, "10.0.0.5")

    def tearDown(self):
        self.hub.close()

    def fed_op(self, body, vouch=None, who=None):
        p = {"op": "personal", "body": body, "peer": "10.0.0.5", "vouch": vouch}
        if who:
            p["who"] = who
        return self.hub.rooms_fed(p, "Bearer " + self.fed)

    def test_hub_takes_the_spokes_admin_vouch_and_who(self):
        self.assertEqual(self.fed_op({"op": "list"}, vouch="member")[1], 403)
        self.assertEqual(self.fed_op({"op": "reset", "name": "Jane Doe", "code": TEMP}, vouch="member",
                                     who={"name": "Mallory"})[1], 403)
        o, c = self.fed_op({"op": "reset", "name": "Jane Doe", "code": TEMP}, vouch="admin",
                           who={"name": "Kenton", "host": "kentonpc-1a2b", "relay": "spoke-a"})
        self.assertEqual(c, 200, o)
        o, c = self.fed_op({"op": "list"}, vouch="admin")
        self.assertEqual((c, o["people"][0]["mustChange"]), (200, True))
        self.assertEqual((o["audit"][0]["by"], o["audit"][0]["relay"]), ("Kenton", "spoke-a"))
        # the person's own change needs no vouch (the temporary code proves it); a wrong guess says `wrong` (the spoke counts it)
        self.assertEqual(self.fed_op({"op": "change", "name": "Jane Doe", "code": "nope-nope", "newCode": JANE_NEW})[0].get("wrong"), True)
        self.assertEqual(self.fed_op({"op": "change", "name": "Jane Doe", "code": TEMP, "newCode": JANE_NEW})[1], 200)
        self.assertFalse(self.hub.store.personal_must("Jane Doe"))


class _FakeRelay:
    """What kastr_serve reads off its in-process relay: the store, the minter (tokens, names), a spoke's hub call."""

    def __init__(self, svc, state_dir, key, hub=None, fed=None):
        self.store, self.auth, self.state_dir, self.secured, self.port = svc.store, svc, state_dir, True, 4443
        self.logs = []
        self.log = self.logs.append
        with open(os.path.join(state_dir, "auth.jwk"), "w", encoding="utf-8") as f:
            json.dump({"k": base64.urlsafe_b64encode(key).decode().rstrip("=")}, f)
        self._hub, self._fed = hub, fed
        self.hub_rooms_call = self._call if hub else None

    def _hub_minter_url(self):
        return self._hub

    def _cluster_raw(self):
        return {}

    def _call(self, body, timeout=6):
        req = urllib.request.Request(self._hub + "/api/rooms/fed", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._fed})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode() or "{}"), r.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read().decode() or "{}"), e.code

    def spoke_sync_soon(self):
        pass


class ThroughKastrServe(unittest.TestCase):
    """POST /api/rooms/personal at a KASTR: the loopback operator, an admin's member token, a non-admin; a spoke forwards."""

    def setUp(self):
        import kastr_serve
        self.ks = kastr_serve
        self.tmpd = tempfile.mkdtemp()
        self.p_ini = mock.patch.object(kastr_serve, "_ini_file", lambda: os.path.join(self.tmpd, "kastr.ini"))
        self.p_ini.start()
        self.hub_key, self.spoke_key = os.urandom(32), os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        self.spoke = kr.AuthService("127.0.0.1", 0, self.spoke_key, 4453, store())
        kr.personal_op(self.hub.store, {"op": "create", "name": "Jane Doe", "code": JANE_OLD, "access": "pub-1"}, "10.0.0.5")
        fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.hub_rs = _FakeRelay(self.hub, tempfile.mkdtemp(), self.hub_key)
        self.srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True, relay_srv=self.hub_rs)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.web = "http://127.0.0.1:%d" % self.srv.server_address[1]
        hub_minter = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.spoke_rs = _FakeRelay(self.spoke, tempfile.mkdtemp(), self.spoke_key, hub=hub_minter, fed=fed)
        self.srv2 = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True, relay_srv=self.spoke_rs)
        threading.Thread(target=self.srv2.serve_forever, daemon=True).start()
        self.web2 = "http://127.0.0.1:%d" % self.srv2.server_address[1]

    def tearDown(self):
        for s in (self.srv, self.srv2):
            s.shutdown()
            s.server_close()
        self.p_ini.stop()
        self.hub.close()
        self.spoke.close()

    def post(self, base, body, tok=None, peer="10.0.0.%d"):
        h = {"Content-Type": "application/json"}
        if tok:
            h["Authorization"] = "Bearer " + tok
        req = urllib.request.Request(base + "/api/rooms/personal", data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode()), r.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read().decode() or "{}"), e.code

    def test_operator_admin_and_non_admin(self):
        o, c = self.post(self.web, {"op": "list", "by": "Kenton"})                                      # loopback = the operator
        self.assertEqual((c, [r["name"] for r in o["people"]], o.get("spoke")), (200, ["Jane Doe"], None), o)
        with mock.patch.object(kr, "is_local", lambda h: False):                                        # a page on another device
            self.assertEqual(self.post(self.web, {"op": "list"})[1], 403)
            viewer = member(self.hub, "alpha", "bobpc-1a2b", "view-1")
            self.assertEqual(self.post(self.web, {"op": "list"}, viewer)[1], 403)
            self.assertEqual(self.post(self.web, {"op": "reset", "name": "Jane Doe", "code": TEMP}, viewer)[1], 403)
            self.assertFalse(self.hub.store.personal_must("Jane Doe"))
            admin = member(self.hub, "alpha", "kentonpc-1a2b", "adm-1")
            o, c = self.post(self.web, {"op": "reset", "name": "Jane Doe", "code": TEMP, "by": "Kenton"}, admin)
            self.assertEqual((c, o["mustChange"]), (200, True), o)
        o, c = self.post(self.web, {"op": "reset", "name": "Nobody Here", "code": TEMP})
        self.assertEqual(c, 404, o)
        au = self.hub.store.personal_audit_view(5)
        self.assertEqual((au[0]["by"], au[0]["host"]), ("Kenton", "kentonpc-1a2b"))
        self.post(self.web, {"op": "reset", "name": "Jane Doe", "by": "Kenton"})                        # the operator removes it
        au = self.hub.store.personal_audit_view(5)
        self.assertEqual((au[0]["op"], au[0]["by"]), ("remove", "relay operator (Kenton)"))
        for line in self.hub_rs.logs + [json.dumps(au)]:
            self.assertNotIn(TEMP, line)

    def test_spoke_forwards_to_the_hub(self):
        with mock.patch.object(kr, "is_local", lambda h: False):
            viewer = member(self.spoke, "alpha", "bobpc-1a2b", "view-1")
            self.assertEqual(self.post(self.web2, {"op": "reset", "name": "Jane Doe", "code": TEMP}, viewer)[1], 403)
            admin = member(self.spoke, "alpha", "kentonpc-1a2b", "adm-1")
            o, c = self.post(self.web2, {"op": "list"}, admin)
            self.assertEqual((c, o["spoke"], [r["name"] for r in o["people"]]), (200, True, ["Jane Doe"]), o)
            o, c = self.post(self.web2, {"op": "reset", "name": "Jane Doe", "code": TEMP, "by": "Kenton"}, admin)
            self.assertEqual(c, 200, o)
        self.assertTrue(self.hub.store.personal_must("Jane Doe"))                                       # at the hub
        self.assertEqual(self.spoke.store.personal_count(), 0)                                         # the hub alone holds it
        au = self.hub.store.personal_audit_view(5)[0]
        self.assertEqual((au["by"], au["host"], au["op"]), ("Kenton", "kentonpc-1a2b", "reset"))
        # Jane, on the spoke: the temporary code opens -- and says pick your own; her own change goes to the hub
        o, c = self.post(self.web2, {"op": "open", "name": "Jane Doe", "code": TEMP})
        self.assertEqual((c, o.get("mustChange")), (200, True), o)
        o, c = self.post(self.web2, {"op": "change", "name": "Jane Doe", "code": TEMP, "newCode": JANE_NEW})
        self.assertEqual(c, 200, o)
        self.assertFalse(self.hub.store.personal_must("Jane Doe"))
        # the Relay page on a spoke: the operator's list says "spoke" (the card shows "on the hub")
        o, c = self.post(self.web2, {"op": "list"})
        self.assertEqual((c, o.get("spoke")), (200, True))


class UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = _read("moq-watch-lite.html")
        cls.msg = _read(os.path.join("assets", "kastr-msg.js"))
        cls.dlg = _read(os.path.join("assets", "kastr-pmreset.js"))
        cls.relay = _read("relay.html")
        cls.serve = _read("kastr_serve.py")

    def test_people_menus(self):
        p = self.page
        self.assertIn('<script src="/assets/kastr-pmreset.js"></script>', p)
        self.assertIn('label: "Reset My room passcode\\u2026 (admin)"', p)
        self.assertIn('if (pmr.names && !pmr.names.has(pmrKey(p.name))) return [];', p)          # only people with a My room (when known)
        self.assertIn('const d = await pmrPost({ op: "list" });', p)
        self.assertIn('return { items: [...r.items, { sep: true }, ...a], pick: (v) => (v === "pinv-pmr" ? pmrOpen(p.name) : r.pick(v)) };', p)
        self.assertIn('const adm = [...eoMsgAdmin(x), ...pmrItems(x)];', p)                       # offline rows (All people)
        self.assertIn('if (authSecured && authTokens?.member) headers.authorization = "Bearer " + authTokens.member;   // the admin grant proves it', p)

    def test_must_change_flows(self):
        p, m = self.page, self.msg
        self.assertIn('if (d.mustChange) {   // 0.21.91 passcode reset', p)
        self.assertIn('const d = await personalApi({ op: "change", name: t.name, code: t.code, newCode: n1 });', p)
        self.assertIn("roomChange: async (name, code, newCode) =>", p)
        self.assertIn("if (/pick your own passcode/i.test(m)) {", p)
        self.assertIn('if (u.mustChange) { S.pendingCode = code; setState("mustchange"); return false; }', m)
        self.assertIn('"rekey", "mustchange"]', m)
        self.assertIn("const d = await K.roomChange(S.name, tmp, c1);", m)
        self.assertIn("An admin reset your My room passcode. Enter your previous passcode to keep your message history, or start fresh.", m)

    def test_dialog_and_relay_page(self):
        d, r = self.dlg, self.relay
        for t in ("Their pinned feeds, spotlights and layouts stay.", "pick their own passcode", "<b>old</b> passcode",
                  "Remove their My room&hellip;", 'data-a="gen"', 'data-a="copy"', "crypto.getRandomValues"):
            self.assertIn(t, d)
        self.assertNotIn("localStorage", d)                                                       # a code is kept nowhere
        self.assertNotIn("console.", d)
        self.assertIn('<section class="panel" id="pmrPanel" hidden>', r)
        self.assertIn('<script src="/assets/kastr-pmreset.js"></script>', r)
        self.assertIn('try { d = await pmrPost({ op: "list" }); }', r)
        self.assertIn('$("pmrSpoke").hidden = !d.spoke;', r)
        self.assertIn('out.append("/assets/kastr-pmreset.js")', self.serve)

    def test_generated_code_is_readable(self):
        self.assertIn('const ALPHA = "abcdefghjkmnpqrstuvwxyz23456789";', self.dlg)
        self.assertIn('return out.slice(0, 3).join("") + "-" + out.slice(3, 6).join("") + "-" + out.slice(6, 9).join("");', self.dlg)

    def test_line_endings(self):
        for name, crlf in (("moq-watch-lite.html", True), ("relay.html", True), ("kastr_serve.py", True), ("kastr_relay.py", False),
                           ("kastr_msg.py", False), (os.path.join("assets", "kastr-msg.js"), False), (os.path.join("assets", "kastr-pmreset.js"), False)):
            raw = _file(os.path.join(HERE, name))
            if crlf:
                self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)
            else:
                self.assertNotIn(b"\r\n", raw, name)


if __name__ == "__main__":
    unittest.main()
