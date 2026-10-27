# -*- coding: utf-8 -*-
"""v0.21.91 THE CLOSEST RELAY. Kenton: "On launch of KASTR always do a check to find the closest relay and select that. Keep the
dropdown menu so people can choose another relay if needed. If none are online and available, put a note for that to let them
know that there are no available relays." + "Also do a check every hour and move to the nearest relay if there is a closer one."
+ "It doesn't appear to be showing mDNS relays on the join room page."

Decided: every launch measures the fleet's relays (the hub's registry, cached; this machine's own; the ones found on the network)
from this machine's KASTR -- 3 samples, 1.5 s, in parallel, a private address before a public one -- and picks the lowest round
trip OF THE FLEET (a relay of another fleet found on the network is listed "On this network", never picked, never sent codes).
The dropdown: "Closest automatically (now: <relay>, 12 ms)", each relay's ms or "unreachable"; a pick by hand lasts until KASTR
closes (no automatic moves). Nothing online: "No relays are available right now -- KASTR keeps trying" and re-checks (10 s,
20 s, 40 s, then every minute), connecting by itself. A relay dead ~15 s mid-session: the next closest, back in the same room by
the silent rejoin, no moving back this run. Every hour (+ jitter): move only on a clear win (25 % and 10 ms) twice, never while
presenting / backstage / recording / under or giving remote control / sending a file / talking. Boxes, relay-only machines,
viewer displays and web clients keep their relay behaviour."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_serve as ks  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1", "admin": "adm-1"}


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def body(src, start, n=6000):
    i = src.index(start)
    return src[i:i + n]


def fake_probe(table, calls=None):
    """table: url -> list of ms answers (None = no answer), consumed one per sample"""
    seq = {u: list(v) for u, v in table.items()}

    def probe(u, timeout=1.5, name=True):
        if calls is not None:
            calls.append((u, name))
        v = seq.get(u, [None])
        ms = v.pop(0) if v else None
        return {"online": False} if ms is None else {"online": True, "ms": ms, "fp": "ab" * 32, "name": ("n-" + u[-4:]) if name else None}
    return probe


def resolve(h):
    return {"lan-a": "10.0.0.5", "pub-a": "52.1.2.3", "lan-b": "192.168.1.9", "pub-b": "52.9.9.9"}.get(h, "10.0.0.99")


class Ranking(unittest.TestCase):
    def test_lowest_median_rtt_wins(self):
        t = {"http://lan-a:4443": [40, 41, 39], "http://lan-b:4443": [12, 80, 13]}   # b's median 13 despite one 80 ms sample
        out = ks.closest_relays([{"name": "A", "urls": ["http://lan-a:4443"], "fleet": True},
                                 {"name": "B", "urls": ["http://lan-b:4443"], "fleet": True}], probe=fake_probe(t), resolve=resolve)
        self.assertEqual([r["name"] for r in out], ["B", "A"])
        self.assertEqual((out[0]["ms"], out[1]["ms"]), (13, 40))

    def test_private_address_before_public_of_one_relay(self):
        t = {"http://pub-a:4443": [5, 5, 5], "http://lan-a:4443": [20, 20, 20]}
        out = ks.closest_relays([{"name": "A", "urls": ["http://pub-a:4443", "http://lan-a:4443"], "fleet": True}], probe=fake_probe(t), resolve=resolve)
        self.assertEqual(out[0]["url"], "http://lan-a:4443")   # reachable here on the LAN -- the public way in is the fallback
        self.assertTrue(out[0]["private"])
        t = {"http://pub-a:4443": [5, 5, 5], "http://lan-a:4443": [None]}
        out = ks.closest_relays([{"name": "A", "urls": ["http://pub-a:4443", "http://lan-a:4443"], "fleet": True}], probe=fake_probe(t), resolve=resolve)
        self.assertEqual(out[0]["url"], "http://pub-a:4443")
        self.assertEqual(len(out[0]["addrs"]), 2)

    def test_dead_address_is_asked_once_and_samples(self):
        calls = []
        t = {"http://lan-a:4443": [None, 10, 10], "http://lan-b:4443": [30, 31, 29]}
        out = ks.closest_relays([{"name": "A", "urls": ["http://lan-a:4443"], "fleet": True},
                                 {"name": "B", "urls": ["http://lan-b:4443"], "fleet": True}], samples=3, probe=fake_probe(t, calls), resolve=resolve)
        self.assertEqual(sum(1 for u, _ in calls if u.endswith("lan-a:4443")), 1)   # no answer to the first sample: not asked again
        self.assertEqual(sum(1 for u, _ in calls if u.endswith("lan-b:4443")), 3)
        self.assertEqual([n for u, n in calls if u.endswith("lan-b:4443")], [True, False, False])   # the name once
        self.assertEqual([r["online"] for r in out], [True, False])

    def test_fleet_wins_a_tie_and_flags_ride_along(self):
        t = {"http://lan-a:4443": [10, 10, 10], "http://lan-b:4443": [10, 10, 10]}
        out = ks.closest_relays([{"name": "LAN", "urls": ["http://lan-b:4443"], "fleet": False, "lan": True},
                                 {"name": "Fleet", "urls": ["http://lan-a:4443"], "fleet": True}], probe=fake_probe(t), resolve=resolve)
        self.assertEqual(out[0]["name"], "Fleet")
        self.assertEqual((out[1]["fleet"], out[1]["lan"]), (False, True))

    def test_bounds(self):
        many = [{"name": str(i), "urls": ["http://h%d:4443" % i], "fleet": True} for i in range(40)]
        out = ks.closest_relays(many, probe=fake_probe({}), resolve=resolve, samples=1)
        self.assertEqual(len(out), 32)
        self.assertEqual(ks.closest_relays([{"name": "x", "urls": ["ftp://nope"]}, "junk"], probe=fake_probe({}), resolve=resolve), [])
        self.assertEqual(ks._median([3, None, 1, 2]), 2)
        self.assertIsNone(ks._median([]))

    def test_the_route(self):
        s = _read("kastr_serve.py")
        self.assertIn('if path == "/api/lan/closest":   # 0.21.91: the candidate relays by measured round trip (this machine only)', s)
        lan = body(s, "def _lan_api(self, path, method):", 4000)
        self.assertLess(lan.index('return send(403, {"error": "only on the computer itself"})'), lan.index('"/api/lan/closest"'))
        self.assertIn("samples = max(1, min(5, int(body.get(\"samples\") or 3)))", lan)
        self.assertIn("def probe_relay(url, timeout=1.5, name=True):", s)


class FleetRegistry(unittest.TestCase):
    def test_rows(self):
        rows = kr.fleet_relay_rows([{"name": "hub", "addrs": [{"address": "http://10.0.0.5:4443"}, {"address": "https://10.0.0.6:4443"},
                                                             {"address": "https://kastr.example.com/relay"}, {"address": "bogus"}]},
                                    {"name": "", "addrs": [{"address": "http://10.0.0.7:4443"}]}, {"name": "empty", "addrs": []}])
        self.assertEqual(rows, [{"name": "hub", "urls": ["http://10.0.0.5:4443", "http://10.0.0.6:4443", "https://kastr.example.com/relay"]}])

    def _svc(self):
        svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, self._store())
        self.addCleanup(svc.close)
        return svc

    def _store(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(**CODES)
        return st

    def test_members_only(self):
        svc = self._svc()
        svc.store.touch_room("yard", "kenton")
        with mock.patch.object(svc, "_p_relays", return_value=[{"name": "hq", "addrs": [{"address": "http://10.0.0.5:4443"}]}]):
            self.assertEqual(svc.fleet_relays_api(None)[1], 403)
            o, c = svc.token({"room": "yard", "code": "view-1", "host": "kenton-ab12"}, "10.0.0.1")
            d, c = svc.fleet_relays_api("Bearer " + o["tokens"]["member"])   # a viewer code's member: yes
            self.assertEqual(c, 200)
            self.assertEqual(d["relays"], [{"name": "hq", "urls": ["http://10.0.0.5:4443"]}])
            o, c = svc.token({"room": "main", "code": "pub-1", "host": "kenton-ab12"}, "10.0.0.1")
            self.assertEqual(svc.fleet_relays_api("Bearer " + o["tokens"]["member"])[1], 200)   # the Lobby's too
            inv, c = svc.invite_create_api({"room": "yard", "ttl": 3600, "by": "K"}, "Bearer " + svc.token({"room": "yard", "code": "pub-1", "host": "kenton-ab12"}, "10.0.0.1")[0]["tokens"]["member"], "10.0.0.1")
            g, c = svc.token({"room": "yard", "invite": inv["token"], "host": "guest-cd34"}, "10.0.0.9")
            self.assertEqual(svc.fleet_relays_api("Bearer " + g["tokens"]["member"])[1], 403)   # a guest: never the fleet's addresses

    def test_a_spoke_asks_its_hub(self):
        svc = self._svc()
        svc.store.touch_room("yard", "kenton")
        tok = "Bearer " + svc.token({"room": "yard", "code": "pub-1", "host": "kenton-ab12"}, "10.0.0.1")[0]["tokens"]["member"]
        own = [{"name": "tremonton", "addrs": [{"address": "http://10.1.0.5:4443"}]}]
        with mock.patch.object(svc, "_p_spoke", return_value=True), mock.patch.object(svc, "_p_relays", return_value=own):
            with mock.patch.object(svc, "_hub_fed", return_value=({"ok": True, "relays": own + [{"name": "hq", "addrs": [{"address": "http://10.0.0.5:4443"}]}]}, 200)) as hf:
                d, c = svc.fleet_relays_api(tok)
                self.assertEqual(hf.call_args[0][0], {"op": "relays"})
                self.assertEqual([r["name"] for r in d["relays"]], ["tremonton", "hq"])
            with mock.patch.object(svc, "_hub_fed", return_value=None):   # a dark hub: this relay alone, said so
                d, c = svc.fleet_relays_api(tok)
                self.assertEqual((c, d.get("hubDown"), [r["name"] for r in d["relays"]]), (200, True, ["tremonton"]))

    def test_hub_answers_its_spokes(self):
        svc = self._svc()
        fed = "Bearer " + kr._mint(svc.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 60))
        with mock.patch.object(svc, "_p_relays", return_value=[{"name": "hq", "addrs": []}]):
            d, c = svc.rooms_fed({"op": "relays"}, fed)
            self.assertEqual((c, d["relays"]), (200, [{"name": "hq", "addrs": []}]))
            self.assertEqual(svc.rooms_fed({"op": "relays"}, None)[1], 403)

    def test_routes(self):
        r, s = _read("kastr_relay.py"), _read("kastr_serve.py")
        self.assertIn('elif path == "/api/fleet/relays":     # 0.21.91: the fleet\'s relays for a member\'s page (the closest relay)', r)
        self.assertIn('"/api/fleet/relays",                                                    # 0.21.91: the fleet\'s relays (the closest relay)', s)


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html")

    def test_launch_pick_is_the_fleets_closest(self):
        a = body(self.p, "async function relayAutoPick() {", 3200)
        self.assertIn('if (IS_WEB || !gateIsLoopback() || !["full", "viewer"].includes(PAGE_MODE)) return null;', a)   # boxes / relay-only: as before
        self.assertIn("window.__lanFound = await lanDiscover().catch(() => []);", a)
        self.assertIn("const best = relayBest(rk);", a)
        self.assertIn('if (!best) { if (rk) { relayNoneStart("launch"); return false; } return null; }', a)
        self.assertIn("await relayApplyAuto(best.url);", a)
        self.assertIn('"Connected to the closest relay: " + relayDisp(best) + " (" + Math.round(best.ms) + " ms)"', a)
        self.assertIn("const relayBest = (rk) => (rk?.list || []).find((r) => r.online && r.fleet) || null;", self.p)
        self.assertIn('relayAutoPick().then((u) => { if (u === null) return relayFailover("launch"); })', self.p)
        self.assertNotIn('"/api/lan/nearest?"', self.p)

    def test_candidates(self):
        c = body(self.p, "function relayCands() {", 2400)
        self.assertIn("for (const r of fleetCache()?.relays || []) { out.push({ name: r.name, urls: r.urls.slice(0, 8), fleet: true });", c)
        self.assertIn("for (const u of [cur, ...hist, ...(window.__KASTR_KNOWN_RELAYS || [])]) {", c)
        self.assertIn("if (!urls.length || urls.some((u) => fleetUrls.has(u))) continue;   // a fleet relay found on the network: already listed", c)
        self.assertIn("const known = !!f.fp && fps.has(String(f.fp).toLowerCase());", c)
        self.assertIn("out.push({ name: f.name || \"\", urls, fleet: known, lan: !known });", c)
        self.assertIn('const FLEET_KEY = "kastr.fleet.relays";', self.p)
        self.assertIn('fetch(base + "/api/fleet/relays", { cache: "no-store", headers: { authorization: "Bearer " + authTokens.member } })', self.p)
        self.assertIn('if (joinState !== "joined" || !authSecured || !authTokens?.member || inviteGuest()) return null;', self.p)

    def test_dropdown(self):
        p = self.p
        self.assertIn('opts.push(new Option("Closest automatically" + (best ? " (now: " + relayDisp(best) + ", " + Math.round(best.ms) + " ms)" : relayRank ? " (none answers now)" : ""), "__auto"));', p)
        self.assertIn('const ms = (r) => (r.online ? Math.round(r.ms) + " ms" : "unreachable");', p)
        self.assertIn('const o = new Option((r.lan ? "On this network: " : "") + relayDisp(r) + " \\u2014 " + ms(r), r.url);', p)
        self.assertIn('if (sel.value === "__auto") {   // 0.21.91: back to the closest (measured now)', p)
        self.assertIn("relayManualSet(sel.value);   // 0.21.91: the person's own pick lasts until KASTR closes (no automatic moves)", p)
        self.assertIn('const RELAY_MANUAL = "kastr.relay.manual";   // this run\'s own pick (sessionStorage: until KASTR closes)', p)
        self.assertIn("if (!relayAutoSwitching && String(u || \"\").trim() && String(u || \"\").trim() !== urlInput.value.trim()) relayManualSet(String(u).trim());", p)

    def test_nothing_online(self):
        p = self.p
        self.assertIn('relayNoteShow("No relays are available right now \\u2014 KASTR keeps trying");', p)
        self.assertIn("const wait = Math.min(60000, 10000 * Math.pow(2, n.tries));", p)
        self.assertIn("if (joinState === \"prejoin\" && mainInfo.relayDown) { mainInfo.relayDown = false; mainLaunch(); }   // the main room now", p)
        self.assertIn('if (relayNone) { mainInfo.relayDown = true; mainCover(""); return gate("no relays are available (KASTR keeps trying)"); }   // 0.21.91', p)
        self.assertIn("#relayNote { position:fixed;", p)
        # a relay that answers again is a move within the fleet: the saved codes open the main room (no Join room page)
        self.assertIn("if (best.url !== cur) { await relayApplyAuto(best.url); relayAutoMoved = true; }   // within the fleet: the saved codes stay", p)
        self.assertIn("...((fleetCache()?.relays || []).flatMap((r) => r.urls || []))]);   // + the hub's registry", p)
        # the dropdown keeps "Closest automatically" picked unless the person picked a relay by hand
        self.assertIn('if (v) sel.value = auto ? "__auto" : v;', p)
        self.assertIn("gateRelayApply(sel.value, picked && picked.fleet ? { keepCodes: true } : undefined);", p)

    def test_failover(self):
        p = self.p
        self.assertIn("const RELAY_DEAD_MS = 15000;", p)
        self.assertIn("if (!offered && Date.now() - downSince > RELAY_DEAD_MS) { offered = true; (relayMoveCan() ? relayFailMove() : relayFailover(\"session\")).catch(() => {}); }", p)
        self.assertIn("const relayMoveCan = () => { try { return mainPerson() && !IS_WEB && gateIsLoopback(); } catch { return false; } };", p)
        f = body(p, "async function relayFailMove() {", 900)
        self.assertIn("const best = (rk?.list || []).find((r) => r.online && r.fleet && r.url !== cur && !(r.addrs || []).some((a) => a.url === cur));", f)
        self.assertIn('"Moved to " + relayDisp(best) + " \\u2014 " + (relayNameOf(cur) || relayLabel(cur)) + " stopped answering"', f)
        m = body(p, "async function relayMove(best, why, note) {", 900)
        self.assertIn('if (why === "failover") { try { sessionStorage.setItem("kastr.relay.failed", "1"); } catch {} }   // no moving back this run', m)
        self.assertIn("setTimeout(() => location.reload(), 150);", m)   # the silent rejoin brings the room back

    def test_hourly(self):
        p = self.p
        self.assertIn("const relayHr = { period: 3600000, jitter: 300000, confirm: 20000,", p)
        h = body(p, "async function relayHourlyCheck() {", 3000)
        self.assertIn("return { win: b.ms <= c.ms * 0.75 && c.ms - b.ms >= 10, cur: c, best: b };", h)
        self.assertIn("await new Promise((r) => setTimeout(r, relayHr.confirm));   // the second probe: noise does not move anyone", h)
        self.assertIn('relayManual() ? "a relay picked by hand" : failed ? "moved after a relay failed (this run)"', h)
        self.assertIn('"Moved to " + relayDisp(j2.best) + " (closer: " + Math.round(j2.best.ms) + " ms vs " + Math.round(j2.cur.ms) + " ms)"', h)
        b = body(p, "function relayBusy() {", 900)
        for what in ('"presenting"', '"backstage"', '"recording"', '"controlling someone"', '"under remote control"', '"sending a file"', '"talking"'):
            self.assertIn(what, b)
        self.assertIn("(window.__publisher?.talkAgo?.() ?? 1e9) < 10000", b)
        self.assertIn("talkAgo: () => (talkLastLoud ? performance.now() - talkLastLoud : 1e9),", p)
        self.assertIn("pageModeReady.then(() => { if (relayMoveCan()) relayHourlyArm(); });", p)


if __name__ == "__main__":
    unittest.main()
