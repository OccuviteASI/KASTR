# -*- coding: utf-8 -*-
"""v0.21.84 integration -- the stream library's page and server, reconciled (the page builder's ten assumptions against the
real endpoints), plus the integration fixes: GET /api/library names the answering relay's node and site (the hub's site
names ride the long-poll to the spokes), the panel's `since` is the version of its last WHOLE list (a paths= answer never
stands for it), and the Relay page finds the hub's own Links row by its node.

Run: python -m unittest discover -s tests"""
import base64
import os
import re
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1", "admin": "adm-1", "federation": "fed-1"}
HOST = "yard-0001"
P1 = "lib/yard-0001/yard/gate.hang"
P2 = "lib/yard-0001/yard/dock.hang"
JPEG = bytes((0xFF, 0xD8, 0xFF, 0xE0)) + b"still" * 20


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def store():
    st = kr.AuthStore(tempfile.mkdtemp())
    st.set_codes(**CODES)
    return st


def member(s, room, code="pub-1", host="kenton-ab12", room_code=None):
    body = {"room": room, "code": code, "host": host}
    if room_code:
        body["roomCode"] = room_code
    r, c = s.token(body, "10.0.0.1")
    assert c == 200, r
    return r["tokens"]["member"]


def libtok(s, host=HOST):
    r, c = s.token({"library": True, "code": "pub-1", "host": host}, "10.0.0.9")
    assert c == 200, r
    return "Bearer " + r["tokens"]["member"]


def beat(s, tok, rows, **kw):
    s._lib_reg().beats.clear()
    return s.library_post(dict({"rows": rows}, **kw), tok, "10.0.0.9")


def row(path=P1, **kw):
    return dict({"path": path, "label": "Gate", "kind": "rtsp", "state": "live", "low": True, "res": "1280x720"}, **kw)


PAGE = _read("moq-watch-lite.html")
RELAY_PAGE = _read("relay.html")


def lib_block():
    return PAGE.split("// ==== 0.21.84 (Kenton: \"a fleet-wide library of available streams: every camera box", 1)[1]


class LoneRelay(unittest.TestCase):
    def setUp(self):
        self.s = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        self.tok = libtok(self.s)
        beat(self.s, self.tok, [row(), row(P2, state="asleep")], stills={P1: base64.b64encode(JPEG).decode()})

    def tearDown(self):
        self.s.close()

    # (1) the member token as a Bearer header -- or ?jwt= -- on the catalogue, the still and the viewer token
    def test_1_bearer_or_jwt(self):
        s, m = self.s, member(self.s, "yard", "view-1")
        for bearer, jwt in (("Bearer " + m, None), (None, m)):
            d, c = s.library_get({}, bearer, jwt, "10.0.0.1")
            self.assertEqual((c, len(d["rows"])), (200, 2), d)
            img, c = s.library_still({"path": P1}, bearer, jwt, "10.0.0.1")
            self.assertEqual((c, img), (200, JPEG))
        o, c = s.library_token_api({}, "Bearer " + m, "10.0.0.1")
        self.assertEqual(c, 200, o)
        for bearer, jwt in (("Bearer " + o["token"], None), (None, o["token"])):   # the library viewer token reads both too
            self.assertEqual(s.library_get({}, bearer, jwt, "10.0.0.1")[1], 200)
            self.assertEqual(s.library_still({"path": P1}, bearer, jwt, "10.0.0.1")[1], 200)
        self.assertEqual(s.library_get({}, None, None, "10.0.0.1")[1], 403)       # no token from another machine
        # the page sends a header (never the URL: logs); the web port's proxy forwards it to the minter
        self.assertIn('return t ? { authorization: "Bearer " + t } : {};', lib_block())
        self.assertIn('hdrs["Authorization"] = self.headers.get("Authorization")', _read("kastr_serve.py"))

    # (2) the catalogue names the answering relay's node and site; the page takes them
    def test_2_site_and_node(self):
        s = self.s
        d, c = s.library_get({}, "Bearer " + member(s, "yard"), None, "10.0.0.1")
        node = kr._machine_node() or "relay"
        self.assertEqual(d["node"], node)
        self.assertEqual(d["site"], s._lib_book().site_of(node))
        self.assertEqual(d["site"], [r for r in d["rows"] if r["path"] == P1][0]["site"])
        s.library_admin_api({"op": "site", "node": node, "site": "Mendon"}, None, "127.0.0.1")
        d = s.library_get({"since": d["ver"]}, "Bearer " + member(s, "yard"), None, "10.0.0.1")[0]
        self.assertEqual(d["site"], "Mendon")
        self.assertFalse(d.get("same"))                                           # a site name moves the version
        self.assertIn("if (d.site) libMeta.site = String(d.site);", lib_block())
        self.assertIn("if (d.node) libMeta.node = String(d.node);", lib_block())

    # (3) no per-row kbps and no link figures: the cost hint estimates from the copy it would pull
    def test_3_cost_hint_estimates(self):
        d = self.s.library_get({}, "Bearer " + member(self.s, "yard"), None, "10.0.0.1")[0]
        self.assertNotIn("links", d)
        self.assertFalse(any("kbps" in r for r in d["rows"]))
        blk = lib_block()
        self.assertIn("if (e.low) return Number(e.lowKbps) || 400;", blk)                   # the -low copy a grid cell takes
        self.assertIn('return h >= 2000 ? 12000 : h >= 1000 ? 4000 : h >= 700 ? 2000 : 1500;', blk)   # else from res
        self.assertIn('const link = l && (l.mbps || l.cap) ?', blk)                         # a link claim only when a figure exists

    # (4) row fields; a since= answer is the whole list; paths= carries `missing` and `alias`
    def test_4_rows(self):
        s, m = self.s, "Bearer " + member(self.s, "yard")
        d = s.library_get({}, m, None, "10.0.0.1")[0]
        r = [x for x in d["rows"] if x["path"] == P1][0]
        for k in ("path", "host", "node", "site", "label", "kind", "by", "box", "low", "res", "state", "since", "seen", "online",
                  "reach", "stillV", "aka", "usedIn"):
            self.assertIn(k, r, k)
        self.assertTrue(r["online"] and r["reach"] and r["stillV"])
        self.assertNotIn("delta", d)                                                # whole, so the page replaces its list
        s.library_admin_api({"op": "label", "path": P1, "label": "North"}, None, "127.0.0.1")
        s.library_admin_api({"op": "hide", "path": P2}, None, "127.0.0.1")
        d2 = s.library_get({"since": d["ver"]}, m, None, "10.0.0.1")[0]
        self.assertEqual([x["path"] for x in d2["rows"]], [P1])                     # the whole list again (P2 hidden: absent)
        self.assertTrue(d2["rows"][0]["edited"])
        d3 = s.library_get({"paths": P1 + "," + P2}, m, None, "10.0.0.1")[0]
        self.assertEqual(([x["path"] for x in d3["rows"]], d3["missing"]), ([P1], [P2]))
        self.assertIn("const whole = !!full && !asked && d.delta !== true && d.full !== false;", lib_block())
        self.assertIn("for (const p of Array.isArray(d.missing) ? d.missing : []) libCat.delete(String(p));", lib_block())

    # (4, the integration fix) the panel's since= is the version of its last WHOLE list
    def test_4_page_since_is_the_whole_lists_version(self):
        blk = lib_block()
        self.assertIn("const since = full && libMeta.fullAt ? libMeta.fullVer ?? 0 : 0;", blk)
        self.assertIn("if (whole) { libMeta.fullAt = Date.now(); libMeta.fullVer = d.ver ?? null; }", blk)
        self.assertIn("if (!asked && d.ver != null && d.ver === libMeta.ver", blk)
        self.assertEqual(blk.count("libMeta.fullVer = "), 1)

    # (5) stills: fetched again after 5 minutes (the server's still may change without stillV moving)
    def test_5_stills_refetched(self):
        self.assertIn("c.v === e.stillV && Date.now() - (c.at || 0) < 300000", lib_block())

    # (6) the library connection: relay URL + lib=1 + jwt=<library viewer token>; the relay grants lib/** to it
    def test_6_library_session(self):
        s = self.s
        o = s.library_token_api({}, "Bearer " + member(s, "yard", "view-1"), "10.0.0.1")[0]
        g, c = s.session({"event": "connect", "id": "l1", "query": "lib=1&jwt=" + o["token"]}, "127.0.0.1")
        self.assertEqual(c, 200, g)
        self.assertIn("lib/**", g["subscribe"])
        self.assertEqual(g["publish"], [])
        self.assertIn('return u + (u.includes("?") ? "&" : "?") + "lib=1" + (libConn.token ? "&jwt=" + encodeURIComponent(libConn.token) : "");', lib_block())

    # (7) demand for a library stream names room lib; the library viewer token covers it, a member token falls back
    def test_7_demand(self):
        s = self.s
        o = s.library_token_api({}, "Bearer " + member(s, "yard", "view-1"), "10.0.0.1")[0]
        self.assertTrue(kr.claims_cover(kr.verify_token(o["token"], s.key), kr.LIB_ROOT))
        self.assertFalse(kr.claims_cover(kr.verify_token(member(s, "yard"), s.key), kr.LIB_ROOT))
        sv = _read("kastr_serve.py").split('if path == "/api/ondemand/demand":', 1)[1][:1200]
        self.assertIn('bad = self._room_claims("", str(p.get("jwt") or ""))', sv)          # any member token of this relay
        self.assertIn("const room = isLibPath(broadcast) ? LIB_ROOT", PAGE)
        self.assertIn("(isLibPath(broadcast) && libConn.token) ||", PAGE)

    # (8) My room: a pin from the library with the owner's personal token, no proof
    def test_8_my_room(self):
        s = self.s
        o, c = kr.personal_op(s.store, {"op": "create", "name": "K", "code": "abcd1234", "access": "pub-1"}, "10.0.0.5")
        self.assertEqual(c, 200, o)
        slug = o["slug"]
        own = member(s, slug, host="kenton-ab12", room_code="abcd1234")
        d, c = s.board_post({"room": slug, "op": "pin", "path": P1, "from": "lib", "label": "Gate", "kind": "rtsp"}, "Bearer " + own, "10.0.0.7")
        self.assertEqual(c, 200, d)
        self.assertEqual(d["pins"][0], dict(d["pins"][0], path=P1, **{"from": "lib"}))
        # a viewer-code owner too (My room's owner arranges it whatever their role)
        vown = member(s, slug, code="view-1", host="watch-9f9f", room_code="abcd1234")
        self.assertEqual(s.board_post({"room": slug, "op": "pin", "path": P2, "from": "lib"}, "Bearer " + vown, "10.0.0.7")[1], 200)
        self.assertIn('const body = { room: p.slug, op: "pin", path, from: LIB_ROOT,', lib_block())

    # (9) a box camera's library state: feeds[].publish.library (L) and feeds[].lib (the switch); the picker sends a boolean
    def test_9_box_fields(self):
        rt = _read("kastr_rtsp.py")
        self.assertIn('"library": self._library_info(),', rt)
        self.assertIn('"lib": self.lib,', rt)
        self.assertIn("library: f.publish?.library ?? null, lib: f.lib ?? null", PAGE)
        self.assertIn("body: JSON.stringify({ id, on: !!on })", lib_block())

    # (10) the Relay page's card and the Links join
    def test_10_relay_page(self):
        out, c = self.s.library_operator_view()
        for k in ("hub", "on", "switch", "why", "preflight", "entries", "sites", "minVersion", "conflicts"):
            self.assertIn(k, out, k)
        node = kr._machine_node() or "relay"
        self.assertIn(node, out["sites"])                                         # keyed by node: the hub's Links row has node = this id
        self.assertEqual(set(out["sites"][node]), {"site", "set", "name", "default"})
        self.assertIn('const m = mn.find((x) => x.id === node || x.node === node) || mn.find((x) => x.name === node || x.name === s?.name) || {};', RELAY_PAGE)
        self.assertIn('"node": _machine_node(), "name": me_name', _read("kastr_relay.py"))


class LabFixes(unittest.TestCase):
    # lab (a): a device-local grid / pin with a camera's OLD path follows its alias without the panel ever opening
    def test_old_local_paths_asked_by_name(self):
        blk = lib_block()
        self.assertIn("const old = full ? [] : libOldRefs();", blk)
        self.assertIn("const ask = [...used, ...old];", blk)
        fn = blk.split("function libOldRefs() {", 1)[1].split("\n  }\n", 1)[0]
        self.assertIn("cgMine()", fn)
        self.assertIn('"kastr.pins." + sbRelayHost()', fn)
        self.assertIn("if (now - (libOldAsked.get(p) || 0) < 600000) continue;", fn)   # each at most every 10 minutes
        self.assertIn("isLibPath(p)", fn)

    # lab (c): an opened pin wakes its camera at once (not on odQuick's next 3 s round)
    def test_opened_pin_wakes_at_once(self):
        fn = lib_block().split("async function libSync() {", 1)[1].split("\n  }\n", 1)[0]
        self.assertIn('if (why !== "grid") setTimeout(() => { const t = tiles.get(p); if (t && libTiles.has(p) && !hasPicture(t) && !parkedStreams.has(p) && libWakeable(p)) { t.odAt = Date.now(); odWake(p); } }, 250);', fn)

    # lab (a): the hub names its own site before its first publisher, and its Links card lists it
    def test_hub_site_before_publishing(self):
        s = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        try:
            s.relay_name = lambda: "yard-relay"
            node = kr._machine_node() or "relay"
            self.assertEqual(s._lib_site(), "yard")
            out, _c = s.library_operator_view()
            self.assertEqual(out["sites"][node]["site"], "yard")
            self.assertFalse(out["sites"][node]["set"])
        finally:
            s.close()


class HubAndSpokeSites(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: base, fed_token=lambda: self.fed)

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def poll(self):
        d, c = self.hub.bans_for_spoke("Bearer " + self.fed, lib_since=self.spoke._lib_mirror().get("ver") or "0")
        self.assertEqual(c, 200, d)
        self.spoke.library_mirror_apply(d)
        return d

    def test_spoke_says_the_hub_s_name_for_itself(self):
        node = kr._machine_node() or "relay"    # (one machine: the same node id; the lab sets KASTR_NODE per KASTR)
        self.poll()
        tok = libtok(self.spoke)
        beat(self.spoke, tok, [row()])
        d = self.spoke.library_get({}, "Bearer " + member(self.spoke, "yard"), None, "10.0.0.1")[0]
        self.assertEqual(d["node"], node)
        self.assertEqual(d["site"], kr.lib_site_default(self.spoke._lib_name(), node))     # before the hub named it
        self.assertEqual(d["rows"][0]["site"], d["site"])
        self.hub.library_admin_api({"op": "site", "node": node, "site": "South Field"}, None, "127.0.0.1")
        lp = self.poll()
        self.assertEqual(lp["library"]["sites"][node], "South Field")
        d = self.spoke.library_get({}, "Bearer " + member(self.spoke, "yard"), None, "10.0.0.1")[0]
        self.assertEqual((d["site"], d["rows"][0]["site"]), ("South Field", "South Field"))   # a new local row too
        # a spoke restarted (the hub dark) keeps the names from hub-library.json
        sp2 = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4454, kr.AuthStore(self.spoke.store.state_dir),
                             hub=lambda: "http://127.0.0.1:9", fed_token=lambda: self.fed)
        try:
            self.assertEqual(sp2._lib_site(node), "South Field")
        finally:
            sp2.close()

    def test_older_spoke_payload_unchanged(self):
        d0, _c = self.hub.bans_for_spoke("Bearer " + self.fed)
        self.assertNotIn("libraryVer", d0)


class Endings(unittest.TestCase):
    def test_line_endings(self):
        for f, crlf in (("moq-watch-lite.html", True), ("relay.html", True), ("kastr_relay.py", False)):
            with open(os.path.join(HERE, f), "rb") as fh:
                b = fh.read()
            n = b.count(b"\r\n")
            if crlf:
                self.assertEqual(b.count(b"\n"), n, f)
            else:
                self.assertEqual(n, 0, f)


if __name__ == "__main__":
    unittest.main()
