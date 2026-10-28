# -*- coding: utf-8 -*-
"""v0.21.93 THE WEB ADDRESS FIRST. Kenton: "Lets remove the built-in relay addresses. I would like for KASTR to use the web address
as the relay on the first run, then have the hub distribute the known relays to the clients and have them switch to the best relay.
That way it doesn't have to keep a list of all of the IPs built-in."

Decided: the ONLY built-in relay is the fleet's web address (https://kastr.madlabs.app/relay, through Cloudflare); kastr.ini
`relay =` and --relay still override it. Right after the access code is accepted on the Join room page, the desktop app asks the
hub for its relay list (with the token the code just bought), measures it and moves to the fastest relay of the fleet BEFORE the
room -- bounded to ~3.5 s, otherwise the join carries on on the web address. Never the person's pick, never a web client. The web
address counts as part of the fleet: the hub lists it on its own row. Existing installs keep their saved relay and the 0.21.91
behaviour; the web address is their last resort."""
import glob
import http.client
import os
import re
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_serve as ks  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1", "admin": "adm-1"}
OLD = ("10.10.105.190", "10.13.20.196", "10.126.104.2", "10.11.252.203")


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def body(src, start, n=6000):
    i = src.index(start)
    return src[i:i + n]


def shipped():
    """the files a release carries: the pages, their scripts and styles, the Python app, the ini/README templates"""
    out = glob.glob(os.path.join(HERE, "*.html")) + glob.glob(os.path.join(HERE, "*.py")) + glob.glob(os.path.join(HERE, "*.js"))
    out += glob.glob(os.path.join(HERE, "assets", "*.js")) + glob.glob(os.path.join(HERE, "assets", "*.css"))
    out += [p for p in glob.glob(os.path.join(HERE, "extras", "**", "*"), recursive=True) if os.path.isfile(p)]
    return [p for p in out if not os.path.basename(p).startswith("test_")]


class NoBuiltInList(unittest.TestCase):
    def test_no_private_relay_list_ships(self):
        files = shipped()
        self.assertGreater(len(files), 20)
        for p in files:
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    s = f.read()
            except OSError:
                continue
            for ip in OLD:
                self.assertNotIn(ip, s, "%s still names the built-in relay %s" % (os.path.relpath(p, HERE), ip))
            self.assertNotIn("__KASTR_KNOWN_RELAYS", s, os.path.relpath(p, HERE))
            self.assertNotIn("KNOWN_RELAYS = [", s, os.path.relpath(p, HERE))
            # no list of private relay addresses anywhere (an array of two or more http://<RFC 1918>:port strings)
            self.assertIsNone(re.search(r"\[\s*\"https?://(10|192\.168|172\.(1[6-9]|2\d|3[01]))\.[0-9.]+:\d+\"\s*,\s*\"https?://(10|192\.168|172)\.", s),
                              os.path.relpath(p, HERE))

    def test_ini_templates_leave_the_relay_unset(self):
        for plat in ("windows", "linux"):
            ini = _read(os.path.join("extras", plat, "kastr.ini"))
            self.assertIsNone(re.search(r"(?m)^[ \t]*relay[ \t]*=", ini), plat)   # the built-in web address applies
            self.assertIn("; relay = http://relay.example:4443", ini)


class DefaultRelay(unittest.TestCase):
    def test_the_web_address(self):
        self.assertEqual(ks.WEB_RELAY, "https://kastr.madlabs.app/relay")
        self.assertTrue(kr.is_web_relay(ks.WEB_RELAY))
        with mock.patch.dict(os.environ):
            os.environ.pop("KASTR_DEFAULT_RELAY", None)
            self.assertEqual(ks._default_relay(), ks.WEB_RELAY)
            os.environ["KASTR_DEFAULT_RELAY"] = "http://127.0.0.1:9311/relay"   # a lab's stand-in
            self.assertEqual(ks._default_relay(), "http://127.0.0.1:9311/relay")
            for bad in ("javascript:alert(1)", "http://x y", "relay", "file:///c:/x"):
                os.environ["KASTR_DEFAULT_RELAY"] = bad
                self.assertEqual(ks._default_relay(), ks.WEB_RELAY, bad)
        if not os.environ.get("KASTR_DEFAULT_RELAY"):
            self.assertEqual(ks.DEFAULT_RELAY, ks.WEB_RELAY)

    def test_launchers_fall_back_to_it(self):
        self.assertIn('args.relay = last or ini.get("relay", kastr_serve.DEFAULT_RELAY)', _read("kastr.py"))   # saved > ini > built in
        self.assertIn('parser.add_argument("--relay", default=kastr_serve.DEFAULT_RELAY)', _read("kastr-serve.py"))
        self.assertIn("def make_handler(root, coep=COEP_MODES[0], relay=DEFAULT_RELAY,", _read("kastr_serve.py"))

    def test_pages_get_it_substituted(self):
        srv = ks.make_server(HERE, "127.0.0.1", 0, quiet=True, relay="http://127.0.0.1:4443")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            for page, needle in (("/moq-watch-lite.html", 'const WEB_RELAY = (() => { const v = "%s";' % ks.DEFAULT_RELAY),
                                 ("/assets/asi-brand.js", 'const WEB_RELAY = (() => { const v = "%s";' % ks.DEFAULT_RELAY)):
                c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
                c.request("GET", page)
                r = c.getresponse()
                txt = r.read().decode("utf-8", "replace")
                c.close()
                self.assertEqual(r.status, 200, page)
                self.assertIn(needle, txt, page)
                self.assertNotIn("__KASTR_WEB_RELAY__", txt, page)
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertIn('(WEB_RELAY_TOKEN.encode(), DEFAULT_RELAY.encode()),   # 0.21.93: the first-run / last-resort relay', _read("kastr_serve.py"))


class HubListsItsWebAddress(unittest.TestCase):
    def _svc(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(**CODES)
        svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)
        self.addCleanup(svc.close)
        return svc

    def test_public_relay_url(self):
        with mock.patch.object(ks, "ini_get", return_value="https://kastr.example.com/"):
            self.assertEqual(ks.public_relay_url(), "https://kastr.example.com/relay")
        for bad in (None, "", "http://kastr.example.com", "https://10.0.0.5", "https://kastr.example.com/x"):
            with mock.patch.object(ks, "ini_get", return_value=bad):
                self.assertIsNone(ks.public_relay_url(), bad)
        # a spoke never claims the hub's address (learned with the hub clock) -- only its own kastr.ini public_url
        with mock.patch.object(ks, "ini_get", return_value=None), mock.patch.object(ks, "HUB_PUBLIC", ["https://hub.example.com"]):
            self.assertIsNone(ks.public_relay_url())
        self.assertIs(kr.PUBLIC_RELAY_FN, ks.public_relay_url)

    def test_registry_row_and_fleet_answer(self):
        svc = self._svc()
        svc.store.touch_room("yard", "kenton")
        with mock.patch.object(kr, "local_ips", return_value=["10.0.0.5", "192.168.1.9"]), \
                mock.patch.object(kr, "PUBLIC_RELAY_FN", lambda: "https://kastr.example.com/relay"):
            rows = svc._p_relays()
            self.assertEqual(rows[0]["addrs"][-1], {"address": "https://kastr.example.com/relay", "why": "its public web address"})
            self.assertEqual([a["address"] for a in rows[0]["addrs"][:2]], ["http://10.0.0.5:4443", "http://192.168.1.9:4443"])
            tok = "Bearer " + svc.token({"room": "yard", "code": "view-1", "host": "kenton-ab12"}, "10.0.0.1")[0]["tokens"]["member"]
            d, c = svc.fleet_relays_api(tok)
            self.assertEqual(c, 200)
            self.assertEqual(d["relays"][0]["urls"], ["http://10.0.0.5:4443", "http://192.168.1.9:4443", "https://kastr.example.com/relay"])
            # the same row is what a spoke hands on (rooms_fed relays) and an admin's Move choices offer
        svc.__dict__.pop("_p_relays_c", None)
        with mock.patch.object(kr, "local_ips", return_value=["10.0.0.%d" % i for i in range(1, 12)]), \
                mock.patch.object(kr, "PUBLIC_RELAY_FN", lambda: "https://kastr.example.com/relay"):
            a = svc._p_relays()[0]["addrs"]
            self.assertEqual(len(a), 8)   # still 8 at most -- the web address never pushed off
            self.assertEqual(a[-1]["address"], "https://kastr.example.com/relay")
        svc.__dict__.pop("_p_relays_c", None)
        with mock.patch.object(kr, "local_ips", return_value=["10.0.0.5"]), mock.patch.object(kr, "PUBLIC_RELAY_FN", lambda: None):
            self.assertEqual([x["address"] for x in svc._p_relays()[0]["addrs"]], ["http://10.0.0.5:4443"])   # no public_url: as before
        svc.__dict__.pop("_p_relays_c", None)
        with mock.patch.object(kr, "local_ips", return_value=["10.0.0.5"]), mock.patch.object(kr, "PUBLIC_RELAY_FN", lambda: 1 / 0):
            self.assertEqual(len(svc._p_relays()[0]["addrs"]), 1)   # a broken hook never breaks the list

    def test_web_address_ranks_by_its_measured_time(self):
        """the hub's row: its private address first when it answers (the web address is the way in from outside); a separate
        web relay wins only when it is really faster"""
        def probe(u, timeout=1.5, name=True):
            return {"online": True, "ms": {"http://10.0.0.5:4443": 9, "https://kastr.example.com/relay": 4}.get(u, 50), "fp": ""}
        res = lambda h: "52.1.2.3" if "example" in h else "10.0.0.5"  # noqa: E731
        out = ks.closest_relays([{"name": "hq", "urls": ["http://10.0.0.5:4443", "https://kastr.example.com/relay"], "fleet": True}], probe=probe, resolve=res)
        self.assertEqual(out[0]["url"], "http://10.0.0.5:4443")
        self.assertFalse(ks.closest_relays([{"name": "w", "urls": ["https://kastr.example.com/relay"], "fleet": True}], probe=probe, resolve=lambda h: "10.0.0.9")[0]["private"])
        out = ks.closest_relays([{"name": "w", "urls": ["https://kastr.example.com/relay"], "fleet": True},
                                 {"name": "sp", "urls": ["http://10.1.0.5:4443"], "fleet": True}], probe=probe, resolve=res)
        self.assertEqual([r["name"] for r in out], ["w", "sp"])   # 4 ms vs 50 ms: really faster


class FirstRunMove(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html")
        cls.b = _read("assets/asi-brand.js")

    def test_web_address_is_the_fleets(self):
        p = self.p
        self.assertIn('const WEB_RELAY = (() => { const v = "__KASTR_WEB_RELAY__"; return /^https?:[/][/]/.test(v) ? v : ""; })();', p)
        self.assertIn("const fleetUrlSet = () => new Set([...(fleetCache()?.relays || []).flatMap((r) => r.urls || []), WEB_RELAY].filter(Boolean));", p)
        self.assertIn("const h = relayHostKey(), ours = fleetUrlSet();   // 0.21.93: the hub's list + the web address", p)   # the fleet id carry
        self.assertIn("fleet = fleetUrlSet();   // the hub's registry; 0.21.93: + the web address (the fleet's too)", p)    # mainLaunch
        c = body(p, "function relayCands() {", 1600)
        self.assertLess(c.index("for (const r of fleetCache()?.relays || [])"), c.index("for (const u of [cur, ...hist, WEB_RELAY]) {"))   # cached list, mine, the web address last
        self.assertIn("out.push({ name: relayNameOf(u) || \"\", urls: [u], fleet: true });", c)

    def test_fleet_list_right_after_the_code(self):
        self.assertIn('if (!(joinState === "joined" || (pre && joinState === "joining")) || !authSecured || !authTokens?.member || inviteGuest()) return null;', self.p)
        f = body(self.p, "async function fleetFetch(pre) {", 1400)
        self.assertIn("const base = authBase();", f)   # the web origin for a web relay (that KASTR proxies its minter)
        self.assertIn('headers: { authorization: "Bearer " + authTokens.member }', f)

    def test_join_order(self):
        j = body(self.p, "  async function joinNow() {", 16000)
        mint = j.index("if (await withinMs(authMint(slug, joinEls.joinAccess.value, pwd), 15000) === JOIN_TIMEOUT)")
        move = j.index("try { await relayFirstMove(slug, joinEls.joinAccess.value, pwd); }")
        cam = j.index("const pub = window.__publisher;")
        self.assertLess(mint, move)
        self.assertLess(move, cam)   # before the room (the camera, the publish, joinChannel)
        self.assertIn("if (!rejoinRec && relayFirstCan()) {", j)
        self.assertIn('catch (e) { return joinFail("Could not join: " + String(e?.message || e)); }', j)

    def test_who_moves(self):
        c = body(self.p, "function relayFirstCan() {", 500)
        self.assertIn("if (!relayMoveCan() || relayManual() || inviteGet() || inviteGuest() || !authSecured || !authTokens?.member) return false;", c)
        self.assertIn("return isWebRelay(urlInput.value.trim()) && !sessionStorage.getItem(RELAY_FIRST);", c)   # only on the web address, once
        self.assertIn("const relayMoveCan = () => { try { return mainPerson() && !IS_WEB && gateIsLoopback(); } catch { return false; } };", self.p)

    def test_the_move(self):
        m = body(self.p, "async function relayFirstMove(slug, access, pwd) {", 4200)
        self.assertIn("const RELAY_FIRST_MS = 3500;", self.p)
        self.assertIn("const rows = await withinMs(fleetFetch(true), left());", m)
        self.assertIn("const rk = left() > 0 ? await withinMs(relayRankRun(), left()) : JOIN_TIMEOUT;", m)
        self.assertIn("const best = relayBest(rk);", m)   # online and the fleet's
        self.assertIn('if (best.url === from) return done("the web address is the fastest that answered");', m)
        self.assertIn("await relayApplyAuto(best.url);", m)   # a switch KASTR makes: never RELAY_MANUAL, the codes kept
        self.assertNotIn("relayManualSet(", m)
        self.assertIn("const why = await relayFirstAuth(slug, access, pwd);", m)
        self.assertIn("await relayApplyAuto(from);", m)   # refused there: back to the web address
        self.assertIn("relayAutoMoved = true;", m)
        self.assertLess(m.index("const rows = await"), m.index("await relayApplyAuto(best.url);"))
        a = body(self.p, "async function relayFirstAuth(slug, access, pwd) {", 900)
        self.assertIn("for (let i = 0; i < 30 && authChecked !== base; i++)", a)   # the new relay's /api/auth first
        self.assertIn("if (await withinMs(authMint(slug, access, pwd), 6000) === JOIN_TIMEOUT)", a)
        self.assertIn('fetch("/api/rtsp/note", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }) })', self.p)   # launch.log
        self.assertIn("firstRun: relayFirst, web: WEB_RELAY", self.p)   # the rig / diag record
        # relayApplyAuto keeps the codes and flags the switch as KASTR's own
        r = body(self.p, "async function relayApplyAuto(url) {", 700)
        self.assertIn("relayAutoSwitching = true;", r)
        self.assertIn("await gateRelayApply(url, { keepCodes: true });", r)

    def test_popover_lists_the_hubs_relays(self):
        b = self.b
        self.assertIn('const WEB_RELAY = (() => { const v = "__KASTR_WEB_RELAY__"; return /^https?:[/][/]/.test(v) ? v : ""; })();', b)
        self.assertIn('if (/^https?:[/][/]/.test(u)) out.push({ url: u, name: String(r.name || "").slice(0, 40) });', b)
        self.assertIn('const relayNameOf = (u) => relayNameOfSaved(u) || fname.get(u) || "";', b)
        self.assertIn("const o = new Option(relayNameOf(u) || nm || relayLabel(u), u); o.title = u; opts.push(o);", self.p)


if __name__ == "__main__":
    unittest.main()
