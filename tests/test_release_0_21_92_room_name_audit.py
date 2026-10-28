# -*- coding: utf-8 -*-
"""v0.21.92 ROOM NAMES NEED AN ACCESS CODE -- the endpoint audit. Kenton: "Room names must not be visible to anyone without a fleet
access code". Every endpoint and MoQ path that takes or reveals a room name was called with no token as a remote caller (lab
v02192/roomcode audit.py); what still leaked after 0.21.91, and is closed here:
  * GET /api/relay/rooms (the Relay page's list: every room, closed room and group) -> the relay machine only
  * GET /api/files and /api/files?room= (file names and who shared them) -> a member token of that room on a secured relay
    (still a 200 with an empty list: an older page keeps choosing the store); every room's files -> the machine only
  * POST /api/rooms/touch made any name a room and said so ("created": an existence oracle) -> a touch without a member token of
    the room keeps a live room alive and makes none (a spoke forwards it with `only`; the hub honours it)
  * /api/relay/status logRemote (relay log lines name rooms) and /api/instance adminMoved (the room an admin moved a machine to)
    -> not for remote callers
  * the minter's GET /api/rooms and KASTR's /api/rooms/list answered the relay machine's loopback without a token -- a page on that
    machine that had not checked the relay yet read the list once -> no token, no rooms, loopback too (the Relay page reads
    /api/relay/rooms); the page also waits for authDetect before it reads the room store
  * an OPEN relay (no access codes) lists its rooms to all again (0.21.91 cut it to nothing for remote callers by mistake)
  * stats.html: the relay's ~stats name every room, so the page asks for an access code (or reuses a saved one) and the stats
    bundle's connection carries a browse token
Also: a rooms-connection token switch closed its announcement readers before the connection ("announcements are closed", noise)."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_serve  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1", "admin": "adm-1"}
REMOTE = {"X-Forwarded-For": "203.0.113.9"}   # from loopback: forwarded, so never "the machine itself"


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def store(state_dir=None, codes=CODES):
    st = kr.AuthStore(state_dir or tempfile.mkdtemp())
    if codes:
        st.set_codes(**codes)
    return st


def member(key, room, host="ginapc-1a2b"):
    now = int(time.time())
    return kr._mint(key, {"root": "", "get": room, "put": [room + "/" + host, "~state/%s/%s" % (room, host)], "iat": now, "exp": now + 3600})


def call(base, path, body=None, headers=None, raw=None, method=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"), headers=h)
    try:
        with urllib.request.urlopen(r, timeout=20) as f:
            return f.status, f.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class RelaySide(unittest.TestCase):
    def test_touch_without_create_never_makes_a_room(self):
        st = store()
        self.assertFalse(st.touch_room("zebraops", "Pat", create=False))
        self.assertIsNone(st.room("zebraops"))
        self.assertTrue(st.touch_room("zebraops", "Pat"))            # a member's touch makes it
        with st.lock:
            st.rooms["zebraops"]["at"] = time.time() - 60
        self.assertFalse(st.touch_room("zebraops", create=False))    # ... and an old page keeps it alive
        self.assertGreater(st.rooms["zebraops"]["at"], time.time() - 5)

    def test_the_hub_honours_only(self):
        key = os.urandom(32)
        hub = kr.AuthService("127.0.0.1", 0, key, 4443, store())
        try:
            fed = "Bearer " + kr._mint(key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
            o, c = hub.rooms_fed({"op": "touch", "slug": "zebraops", "only": True}, fed)
            self.assertEqual((c, o), (200, {"ok": True}))               # no "created": never says whether a name exists
            self.assertIsNone(hub.store.room("zebraops"))
            o, c = hub.rooms_fed({"op": "touch", "slug": "zebraops"}, fed)
            self.assertTrue(o["created"])
        finally:
            hub.close()

    def test_public_status_and_relay_rooms(self):
        self.assertIn("logRemote", kr.Relay.PUBLIC_STATUS_DROP)
        r = _read("kastr_relay.py")
        self.assertIn('    if not local and handler.command in ("GET", "HEAD"):\n', r)
        self.assertNotIn('not path.startswith("/api/relay/rooms")', r)
        self.assertIn("                    g = guest_rooms(c)\n                    if c is None:\n", r)     # the minter's /api/rooms: loopback too
        self.assertNotIn("if c is None and self._peer() not in LOOPBACK_PEERS:", r)


def fake_relay(state_dir, st, secured=True, key=None):
    auth = None
    if secured and key is not None:
        auth = types.SimpleNamespace(_member_claims=lambda h: kr.verify_token(str(h or "")[7:], key) if str(h or "").startswith("Bearer ") else None)
    return types.SimpleNamespace(state_dir=state_dir, secured=secured, running=lambda: True, _cluster_raw=lambda: {"hub": True},
                                 relay_name=lambda: "lab-relay", store=st, auth=auth, log=lambda m: None, spoke_sync_soon=lambda: None)


class Base(unittest.TestCase):
    secured = True

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr-0192-")
        self.patches = [mock.patch.object(kastr_serve, "CHAT", None),
                        mock.patch.object(kastr_serve, "_ini_file", lambda: os.path.join(self.tmp, "kastr.ini"))]
        for p in self.patches:
            p.start()
        sd = os.path.join(self.tmp, "relay")
        os.makedirs(sd)
        _p, self.key = kr._ensure_jwk(sd)
        self.st = store(sd)
        self.st.touch_room("zebraops", "Patzebra Lab")
        self.srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True, relay="http://127.0.0.1:4443",
                                           relay_srv=fake_relay(sd, self.st, self.secured, self.key))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bearer(self, room):
        return {"Authorization": "Bearer " + member(self.key, room)}

    def upload(self):
        c, b = call(self.base, "/api/files", raw=b"zebra file body", headers={"Content-Type": "application/octet-stream",
                    "X-Kastr-Name": "zebranotes.txt", "X-Kastr-Room": "zebraops", "X-Kastr-Owner": "Patzebra Lab"})
        self.assertIn(c, (200, 201), b[:200])


class SecuredRelay(Base):
    def test_rooms_list_needs_a_token_loopback_too(self):
        for h in (REMOTE, {}):
            c, b = call(self.base, "/api/rooms/list", headers=h)
            d = json.loads(b)
            self.assertEqual((c, d["rooms"], d.get("needCode")), (200, [], True))
            self.assertNotIn(b"zebraops", b)
        c, b = call(self.base, "/api/rooms/list", headers=dict(REMOTE, **self.bearer("lobbyish")))
        self.assertIn("zebraops", [r["slug"] for r in json.loads(b)["rooms"]])

    def test_files_need_the_rooms_token(self):
        self.upload()
        for path, h in (("/api/files?room=zebraops", REMOTE), ("/api/files", REMOTE),
                        ("/api/files?room=zebraops", dict(REMOTE, **self.bearer("other"))),
                        ("/api/files", dict(REMOTE, **self.bearer("zebraops")))):
            c, b = call(self.base, path, headers=h)
            self.assertEqual(c, 200, path)                                 # an older page still picks this store
            self.assertEqual(json.loads(b), {"files": [], "needToken": True}, path)
            self.assertNotIn(b"zebranotes", b)
        c, b = call(self.base, "/api/files?room=zebraops", headers=dict(REMOTE, **self.bearer("zebraops")))
        self.assertEqual([f["name"] for f in json.loads(b)["files"]], ["zebranotes.txt"])
        self.assertNotIn("token", json.loads(b)["files"][0])
        c, b = call(self.base, "/api/files")                                 # the machine itself: every room's
        self.assertIn(b"zebranotes", b)

    def test_a_touch_without_a_token_makes_no_room(self):
        c, b = call(self.base, "/api/rooms/touch", {"slug": "newroom", "creator": "Eve"}, headers=REMOTE)
        self.assertEqual((c, json.loads(b)), (200, {"ok": True}))
        self.assertIsNone(self.st.room("newroom"))
        c, b = call(self.base, "/api/rooms/touch", {"slug": "zebraops"}, headers=REMOTE)
        self.assertEqual(json.loads(b), {"ok": True})                       # the same answer for a live room
        c, b = call(self.base, "/api/rooms/touch", {"slug": "newroom"}, headers=dict(REMOTE, **self.bearer("other")))
        self.assertIsNone(self.st.room("newroom"))                          # another room's token makes nothing either
        c, b = call(self.base, "/api/rooms/touch", {"slug": "newroom"}, headers=dict(REMOTE, **self.bearer("newroom")))
        self.assertEqual(json.loads(b), {"ok": True, "created": True})
        self.assertIsNotNone(self.st.room("newroom"))
        c, b = call(self.base, "/api/rooms/touch", {"slug": "fromhere"})     # the machine itself
        self.assertTrue(json.loads(b)["created"])

    def test_stats_ride_a_browse_token(self):
        c, b = call(self.base, "/assets/stats-1j1isRcX.js")
        self.assertEqual(c, 200)
        self.assertIn(b"m=new i(new URL(window.__kastrTok?window.__kastrTok(a):a))", b)
        self.assertIn(b"m.set(new URL(window.__kastrTok?window.__kastrTok(D.value.trim()):D.value.trim()))", b)
        self.assertIn(b"D.value=String(m.peek()?.toString()??a).replace(/[?&]jwt=[^&]*/,``)", b)   # the box never shows the token
        self.assertIn(b"`~stats/node`", b)
        c, b = call(self.base, "/stats.html")
        s = b.decode("utf-8")
        self.assertIn('var RELAY = "http://127.0.0.1:4443";', s)            # substituted like the bundle
        self.assertLess(s.index("window.__kastrTok = function (u) {"), s.index('src="/assets/stats-1j1isRcX.js"'))
        self.assertIn('if (tok && x.origin === origin) x.searchParams.set("jwt", tok);   // never to a relay typed in by hand', s)
        self.assertIn('body: JSON.stringify({ browse: true, code: c }) })', s)
        self.assertIn('sessionStorage.setItem(KEY, JSON.stringify({ token: tok, exp: exp }))', s)   # the token only, never the code
        self.assertNotIn("localStorage.setItem", s)
        self.assertIn('<input id="kastrLockCode" type="password"', s)
        self.assertIn("Wrong access code for this relay.", s)
        self.assertIn('if (!d || !d.secured) return;   // an open relay: its stats are open', s)


class OpenRelay(Base):
    secured = False

    def test_an_open_relay_lists_its_rooms(self):
        c, b = call(self.base, "/api/rooms/list", headers=REMOTE)
        self.assertIn("zebraops", [r["slug"] for r in json.loads(b)["rooms"]])
        c, b = call(self.base, "/api/rooms/touch", {"slug": "openroom"}, headers=REMOTE)
        self.assertTrue(json.loads(b)["created"])
        self.upload()
        c, b = call(self.base, "/api/files?room=zebraops", headers=REMOTE)
        self.assertIn(b"zebranotes", b)
        c, b = call(self.base, "/api/files", headers=REMOTE)                # every room's files: the machine's own
        self.assertNotIn(b"zebranotes", b)


class ServeSource(unittest.TestCase):
    def test_instance_and_spoke_forward(self):
        s = _read("kastr_serve.py").replace("\r\n", "\n")
        self.assertIn('"adminMoved"):   # 0.21.92: the room an admin moved this machine to', s)
        self.assertIn('body["only"] = True   # 0.21.92: no member token here -- the hub keeps a live room alive, makes none', s)
        self.assertIn('if path == "/api/rooms/touch" and body.get("only"):\n                obj = {"ok": bool(obj.get("ok", code == 200))}', s)


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html").replace("\r\n", "\n")

    def test_the_store_waits_for_the_relay_check(self):
        p = self.p
        i = p.index("async function roomsMinterPoll() {")
        self.assertLess(p.index("if (authChecked !== authBase()) return;", i), p.index("if (authSecured && !roomsToken()) return;", i))
        d = p[p.index("async function authDetect() {"):]
        d = d[:d.index("// A token for this relay origin survives reloads within the tab.")]
        self.assertIn('authSecured = false;\n    authChecked = "";   // 0.21.92', d)
        self.assertIn("    } catch {}\n    authChecked = base;", d)              # an open relay without /api/auth counts as asked

    def test_files_and_touch_carry_the_member_token(self):
        p = self.p
        self.assertIn('return (authSecured && authTokens?.member) ? { authorization: "Bearer " + authTokens.member } : {};', p)
        self.assertEqual(p.count("/api/files?room=\" + encodeURIComponent("), 2)
        self.assertIn('{ cache: "no-store", headers: authBearer() }).then((r) => r.json())', p)
        self.assertIn('{ cache: "no-store", signal: ctl.signal, headers: authBearer() });', p)
        self.assertIn('headers: { "content-type": "application/json", ...(window.__auth?.bearer?.() || {}) },', p)
        self.assertIn("    bearer: authBearer,   // 0.21.92", p)

    def test_the_rooms_connection_closes_before_its_readers(self):
        r = self.p[self.p.index("  function roomsRebuild() {"):]
        r = r[:1200]
        self.assertLess(r.index("if (roomsConn) { try { roomsConn.close(); } catch {} roomsConn = null; }"),
                        r.index("setTimeout(() => { for (const a of oldAnns) { try { a.close?.(); } catch {} } }, 0);"))
        self.assertNotIn("for (const a of roomsAnns) { try { a.close?.(); } catch {} }", r)


if __name__ == "__main__":
    unittest.main()
