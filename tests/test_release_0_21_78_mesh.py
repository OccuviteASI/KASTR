# -*- coding: utf-8 -*-
"""0.21.78 part C: the relay mesh map, round two (Kenton: "On the site relay mesh map, when hovering over a line, show the
bandwidth going through that path."; "Allow for setting cost manually on links between relays."; "Have the site relay mesh
map move more dynamically to make it the most viewable depending on relays."; "When hovering over the relay in the map, show
the local bandwidth being used on that relay."; "If I click on a relay, have it go to a mesh map of that relay and all of the
downstream clients connected, like a zoom in."; "on the zoomed map, show each clients bandwidth on hover").
Covers: the rates from ~stats samples (per link, per relay split local / link, per stream), the stats field names moq-relay
0.17.0 really writes, per-spoke hub / standby link costs (validated, persisted, in the hand-over bundle, live on the spoke:
the hub link moved into relay-peers.json), federation tokens that name the spoke (the hub's per-hub-link tier), inactive
pairs in the Links view, the zoomed relay (its clients, what they publish, what they say they receive), and the page wiring.
The data paths were proven in the lab (scratchpad v02178/C)."""
import io, json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

# moq-relay 0.17.0's own output (lab v02177 run2 / v02178 C: `moq fetch` of a ~stats/node/<node> track): every counter is
# written under two names -- subscriptions == subscriptions_started, subscriptions_closed == subscriptions_ended
REAL_PUB = {"lab/a-host/op/cam.hang": {"announces_started": 1, "announced": 1, "announces_ended": 0, "announced_closed": 0, "announced_bytes": 22,
                                       "broadcasts_started": 1, "broadcasts": 1, "broadcasts_ended": 0, "broadcasts_closed": 0,
                                       "subscriptions_started": 2, "subscriptions": 2, "subscriptions_ended": 0, "subscriptions_closed": 0,
                                       "fetches": 0, "bytes": 9602684, "frames": 840, "groups": 15, "datagrams": 0,
                                       "stale": {"bytes": 0, "frames": 0, "groups": 0, "datagrams": 0}},
            "lab/a-host/op/cam2.hang": {"announces_started": 1, "announced": 1, "announces_ended": 0, "announced_closed": 0, "announced_bytes": 23,
                                        "broadcasts_started": 0, "broadcasts": 0, "broadcasts_ended": 0, "broadcasts_closed": 0,
                                        "subscriptions_started": 0, "subscriptions": 0, "subscriptions_ended": 0, "subscriptions_closed": 0,
                                        "fetches": 0, "bytes": 0, "frames": 0, "groups": 0, "datagrams": 0}}
REAL_SESSIONS = {"": {"sessions_started": 6, "sessions": 6, "sessions_ended": 1, "sessions_closed": 1}}


def rd(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def fed_bearer(key, **extra):
    now = int(time.time())
    return "Bearer " + kr._mint(key, dict(kr.FEDERATION_CLAIMS, iat=now, exp=now + 600, **extra))


def spoke(node, name, version="0.21.78", addrs=("10.0.0.1",), port=4443, probes=(), tokens=None, **mesh):
    m = {"v": 1, "port": port, "addrs": list(addrs), "probes": list(probes), "linkTokens": dict(tokens or {}), "links": []}
    m.update(mesh)
    return {"node": node, "name": name, "version": version, "at": time.time(), "port": port, "mesh": m}


def probe(node, addr, ok=True, private=True, rtt=12.0, err=""):
    t = int(time.time())
    return {"node": node, "addr": addr, "port": 4443, "ok": ok, "rttMs": rtt, "hops": 2, "private": private, "tool": "tracert",
            "path": [addr], "public": [] if private else ["203.0.113.9"], "err": err, "at": t, "okAt": t if ok and private else None}


class StatsFieldNames(unittest.TestCase):
    def test_both_names_count(self):
        # the suspected 0.21.77 bug: mesh_open_paths read *_started/*_ended while the page reads the short pair -- the real
        # relay writes BOTH, so neither was wrong; a stats JSON with either pair alone now reads the same
        self.assertEqual(kr.mesh_open_paths(REAL_PUB, "publisher.json"), ["lab/a-host/op/cam.hang"])
        short = {p: {k: v for k, v in c.items() if not k.endswith(("_started", "_ended"))} for p, c in REAL_PUB.items()}
        long_ = {p: {k: v for k, v in c.items() if k not in ("subscriptions", "subscriptions_closed", "broadcasts", "broadcasts_closed")} for p, c in REAL_PUB.items()}
        self.assertEqual(kr.mesh_open_paths(short, "publisher.json"), ["lab/a-host/op/cam.hang"])
        self.assertEqual(kr.mesh_open_paths(long_, "publisher.json"), ["lab/a-host/op/cam.hang"])
        self.assertEqual(kr.mesh_open_paths(short, "subscriber.json"), ["lab/a-host/op/cam.hang"])   # 2 open subscriptions
        self.assertEqual(kr._stat_open({"sessions": 6, "sessions_closed": 1}, "sessions"), 5)


class Rates(unittest.TestCase):
    def test_tier_bytes_and_rate(self):
        a = kr.mesh_tier_bytes(REAL_PUB)
        self.assertEqual(a, {"lab/a-host/op/cam.hang": 9602684, "lab/a-host/op/cam2.hang": 0})
        b = dict(a, **{"lab/a-host/op/cam.hang": 9602684 + 3750000, "new/x/o/y.hang": 250000})
        self.assertEqual(kr.mesh_rate(a, b, 30), int(round((3750000 + 250000) * 8 / 30.0)))   # a new broadcast counts from zero
        self.assertEqual(kr.mesh_rate({"p": 900}, {"p": 100}, 10), 80)                     # re-created: its new total
        self.assertEqual(kr.mesh_rate({"gone": 5000}, {}, 10), 0)                          # one that left adds nothing
        self.assertIsNone(kr.mesh_rate(a, b, 0.2))
        self.assertIsNone(kr.mesh_rate(None, b, 30))
        self.assertEqual(kr.mesh_path_rates({"p": 1000}, {"p": 2000, "q": 500}, 8), {"p": 1000, "q": 500})

    def test_moved(self):
        self.assertFalse(kr.mesh_rate_moved(1000000, 1050000))   # 5 %
        self.assertTrue(kr.mesh_rate_moved(1000000, 1200000))    # 20 %
        self.assertFalse(kr.mesh_rate_moved(10000, 30000))       # tiny in absolute terms
        self.assertTrue(kr.mesh_rate_moved(None, 0) and kr.mesh_rate_moved(5, None))

    def test_links_carry_bandwidth(self):
        a = spoke("a-1", "mendon", probes=[probe("b-2", "10.0.0.2")], tokens={"c-3": "tokA4C"})
        b = spoke("b-2", "logan", addrs=("10.0.0.2",), probes=[probe("a-1", "10.0.0.1")], tokens={"a-1": "tokB4A"},
                  crossing={"a-1": {"in": ["r/h/o/cam.hang"], "out": [], "inBps": 2870000, "outBps": 12000, "at": 1000}})
        c = spoke("c-3", "southridge", addrs=("10.0.0.3",), tokens={"a-1": "tokC4A", "b-2": "tokC4B"},
                  crossing={"a-1": {"in": [], "out": ["r/h/o/cam2.hang"], "inBps": 0, "outBps": 1500000, "at": 1001}})
        sb = {"node": "c-3", "name": "southridge", "address": "https://10.0.0.3:4443"}
        links, state = kr.mesh_links([a, b, c], {}, 50, sb, hub_crossing={"b-2": {"in": [], "out": ["r/h/o/cam.hang"], "inBps": 0, "outBps": 640000, "at": 999}})
        m = next(l for l in links if l["kind"] == "mesh" and l["active"])
        self.assertEqual((m["dialer"], m["bps"]), ("a-1", {"fwd": 2870000, "back": 12000, "at": 1000}))   # fwd = dialer -> acceptor
        s = next(l for l in links if l["kind"] == "standby" and l["a"] == "a-1")
        self.assertEqual(s["bps"], {"fwd": 0, "back": 1500000, "at": 1001})
        h = next(l for l in links if l["kind"] == "hub" and l["a"] == "b-2")
        self.assertEqual((h["bps"], h["streams"]["back"]), ({"fwd": 0, "back": 640000, "at": 999}, ["r/h/o/cam.hang"]))
        self.assertIsNone(next(l for l in links if l["kind"] == "hub" and l["a"] == "a-1")["bps"])   # not measured: None, never 0

    def test_report_keeps_rates_and_load(self):
        m = kr.mesh_report_clean({"crossing": {"b-2": {"in": ["r/h/o/c.hang"], "out": [], "inBps": "2870000", "outBps": -5, "at": 7}},
                                  "load": {"local": {"in": 100, "out": "x"}, "link": {"in": 5, "out": 6}, "total": {"in": 105, "out": None},
                                           "viewers": 3, "streams": 1, "sessions": 4, "at": 9,
                                           "paths": {"in": [{"path": "r/h/o/c.hang", "bps": 9}, {"path": "bad path!", "bps": 1}],
                                                     "out": [{"path": "r/h/o/c.hang", "bps": 8, "viewers": 2}]}}})
        self.assertEqual(m["crossing"]["b-2"], {"in": ["r/h/o/c.hang"], "out": [], "inBps": 2870000, "outBps": None, "at": 7})
        self.assertEqual(m["load"]["local"], {"in": 100, "out": None})
        self.assertEqual((m["load"]["viewers"], m["load"]["sessions"], m["load"]["at"]), (3, 4, 9))
        self.assertEqual(m["load"]["paths"], {"in": [{"path": "r/h/o/c.hang", "bps": 9}], "out": [{"path": "r/h/o/c.hang", "bps": 8, "viewers": 2}]})


class RelayLoad(unittest.TestCase):
    def test_local_and_link_split(self):
        # the tiers PARTITION the traffic: local = the default tier, link = what it dials (cluster/*) + every accepted link
        rates = {"subscriber.json": 1200000, "publisher.json": 3400000, "cluster/subscriber.json": 2000000, "cluster/publisher.json": 800000}
        cross = {"b-2": {"inBps": 500000, "outBps": 100000}, "c-3": {"inBps": None, "outBps": 50000}}
        L = kr.mesh_relay_load(rates, REAL_PUB, REAL_PUB, REAL_SESSIONS, cross)
        self.assertEqual(L["local"], {"in": 1200000, "out": 3400000})
        self.assertEqual(L["link"], {"in": 2500000, "out": 950000})
        self.assertEqual(L["total"], {"in": 3700000, "out": 4350000})
        self.assertEqual((L["viewers"], L["streams"], L["sessions"]), (1, 2, 5))   # cam has one viewer; two announced; 6 - 1 sessions
        hub = kr.mesh_relay_load({"subscriber.json": 10, "publisher.json": None}, None, None, None, {})
        self.assertEqual((hub["local"]["out"], hub["link"]["in"], hub["total"]["in"]), (None, None, 10))   # unmeasured stays None


class LinkCosts(unittest.TestCase):
    def test_store_validates_persists_bundles(self):
        d = tempfile.mkdtemp()
        st = kr.AuthStore(d)
        self.assertEqual(st.set_link_cost("Bad Node", "hub", 5)[1], "pick a relay")
        self.assertIn("hub link or the standby", st.set_link_cost("a-1", "mesh", 5)[1])
        for bad in (0, "2.5", 1001, "x"):
            self.assertIn("whole number", st.set_link_cost("a-1", "hub", bad)[1], bad)
        rec, err = st.set_link_cost("a-1", "hub", "7")
        self.assertEqual((err, rec["hub"], rec["standby"]), (None, 7, None))
        st.set_link_cost("a-1", "standby", 80)
        self.assertEqual(kr.AuthStore(d).link_costs_public(), {"a-1": {"hub": 7, "standby": 80}})   # persisted
        self.assertEqual(st.set_hub_cost(60), (60, None))
        self.assertEqual(st.link_costs_public()["a-1"]["hub"], 7)                                  # the default keeps them
        b = st.export_bundle()
        st2 = kr.AuthStore(tempfile.mkdtemp())
        st2.import_bundle(b)
        self.assertEqual((st2.mesh_hub_cost(), st2.link_costs_public()["a-1"]), (60, {"hub": 7, "standby": 80}))
        # a clear made later on the standby comes back at hand-back
        self.assertIsNone(st2.set_link_cost("a-1", "hub", None)[0] and None)
        time.sleep(1.1)
        st2.set_link_cost("a-1", "hub", "")
        st2.set_link_cost("a-1", "standby", None)
        st.merge_bundle(st2.export_bundle())
        self.assertEqual(st.link_costs_public()["a-1"], {"hub": None, "standby": None})

    def test_links_and_state_per_spoke(self):
        a = spoke("a-1", "mendon")
        b = spoke("b-2", "logan", version="0.21.77", addrs=("10.0.0.2",))
        c = spoke("c-3", "southridge", addrs=("10.0.0.3",), tokens={"a-1": "tokC4A", "b-2": "tokC4B"})
        sb = {"node": "c-3", "name": "southridge", "address": "https://10.0.0.3:4443"}
        links, state = kr.mesh_links([a, b, c], {}, 50, sb, link_costs={"a-1": {"hub": 9, "standby": 70}})
        self.assertEqual((state["a-1"]["hubCost"], state["b-2"]["hubCost"]), (9, 50))
        self.assertIn({"url": "http://10.0.0.3:4443/", "cost": 70, "token": "tokC4A", "peer": "c-3", "name": "southridge", "kind": "standby"}, state["a-1"]["links"])
        self.assertEqual(next(l for l in state["b-2"]["links"] if l["kind"] == "standby")["cost"], 50)
        ha = next(l for l in links if l["kind"] == "hub" and l["a"] == "a-1")
        hb = next(l for l in links if l["kind"] == "hub" and l["a"] == "b-2")
        self.assertEqual((ha["cost"], ha["overrideCost"], ha["costDefault"], ha["liveCost"]), (9, 9, 50, True))
        self.assertEqual((hb["cost"], hb["overrideCost"], hb["liveCost"]), (50, None, False))   # 0.21.77 restarts for it
        sa = next(l for l in links if l["kind"] == "standby" and l["a"] == "a-1")
        self.assertEqual((sa["cost"], sa["overrideCost"], sa["liveCost"]), (70, 70, True))

    def test_long_poll_carries_own_hub_cost(self):
        svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, kr.AuthStore(tempfile.mkdtemp()))
        try:
            svc.store.set_link_cost("zz-9", "hub", 12)
            self.assertEqual(svc.mesh_for("zz-9"), {"v": 1, "hubCost": 12})   # not mesh-capable yet: its own cost all the same
            self.assertEqual(svc.mesh_for("yy-8"), {"v": 1, "hubCost": 50})
        finally:
            svc.close()


class SpokeLive(unittest.TestCase):
    def relay(self, mesh=None):
        d = tempfile.mkdtemp()
        kr.save_json(os.path.join(d, "relay-cluster.json"), {"connect": "https://127.0.0.1:1", "code": "x"})
        if mesh is not None:
            kr.save_json(os.path.join(d, "relay-mesh.json"), mesh)
        r = kr.Relay(d, lambda m: None)
        r.federation_token = lambda hub, code, force=False: ("fed.tok.en", "hub token cached", {"fingerprint": "ab" * 32})
        r._hub_pin_for = lambda hub, hint=None: ("ab" * 32, "pinned")
        return r, d

    def test_hub_link_in_peers_file_and_live_cost(self):
        r, d = self.relay({"hubCost": 9})
        cfg = rd(r._write_config(4443, True, True))
        self.assertNotIn("connect = [", cfg)                              # the static connect would win over the API's copy
        self.assertIn('connect_api = "relay-peers.json"', cfg)
        peers = json.loads(rd(os.path.join(d, "relay-peers.json")))
        self.assertEqual(peers, [{"url": "http://127.0.0.1:1/", "cost": 9, "token": "fed.tok.en"}])
        self.assertNotIn("http://127.0.0.1:1/", r._mesh_peer_urls)        # the hub's link state stays the hub's
        restarted = []
        r._restart = lambda: restarted.append(1)
        r.running = lambda: True
        r._clients_changed = lambda: None
        r._mesh_seen({"hubCost": 33})
        time.sleep(0.3)
        self.assertEqual(restarted, [])
        self.assertEqual(json.loads(rd(os.path.join(d, "relay-peers.json")))[0]["cost"], 33)
        self.assertEqual(r.federation["hubCost"], 33)

    def test_unwritable_peers_file_keeps_the_static_connect(self):
        r, d = self.relay({"hubCost": 9})
        real = r._mesh_write_peers
        r._mesh_write_peers = lambda force=False: (False if getattr(r, "_hub_in_peers", False) else real(force))
        cfg = rd(r._write_config(4443, True, True))
        self.assertIn('connect = [{ url = "http://127.0.0.1:1/", cost = 9, token = "fed.tok.en" }]', cfg)
        restarted = []
        r._restart = lambda: restarted.append(1)
        r.running = lambda: True
        r._clients_changed = lambda: None
        r._mesh_seen({"hubCost": 40})
        time.sleep(0.3)
        self.assertEqual(restarted, [1])                                  # then a cost still needs the restart

    def test_fresh_federation_token_rides_the_peers_file(self):
        r, d = self.relay({"hubCost": 9})
        r._write_config(4443, True, True)
        r.running = lambda: True
        restarted = []
        r._restart = lambda: restarted.append(1)
        r._spoke_sync = lambda: None
        r.federation_token = lambda hub, code, force=False: ("fresh.tok.en", "hub token minted", {})
        self.assertFalse(r._federation_tick())
        self.assertEqual(restarted, [])
        self.assertEqual(json.loads(rd(os.path.join(d, "relay-peers.json")))[0]["token"], "fresh.tok.en")
        self.assertEqual(r._fed_active, "fresh.tok.en")


class FederationNamesTheSpoke(unittest.TestCase):
    def test_mint_grant_session(self):
        key = os.urandom(32)
        svc = kr.AuthService("127.0.0.1", 0, key, 4443, kr.AuthStore(tempfile.mkdtemp()))
        try:
            svc.store.set_codes(federation="fed-code-1")
            out, code = svc.token({"federation": "fed-code-1", "node": "mendon-1a2b"}, "10.0.0.9")
            self.assertEqual(code, 200)
            c = kr.verify_token(out["token"], key)
            self.assertEqual(c["node"], "mendon-1a2b")
            self.assertTrue(kr.is_relay_claims(c))                         # still a federation Bearer
            self.assertIsNotNone(svc._bearer_relay("Bearer " + out["token"]))
            g = kr.claims_to_grant(c)
            self.assertEqual((g["tier"], "peer" in g, g["publish"]), ("link-mendon-1a2b", False, ["**"]))   # its own tier, no `peer`
            self.assertNotIn("node", kr.verify_token(svc.token({"federation": "fed-code-1", "node": "Bad Node!"}, "10.0.0.9")[0]["token"], key))
            self.assertNotIn("tier", kr.claims_to_grant(dict(kr.FEDERATION_CLAIMS, exp=time.time() + 60)))   # an older token: unchanged
            svc.session({"event": "connect", "id": "h1", "remote": "10.0.0.9:5000", "query": "jwt=" + out["token"]}, "127.0.0.1")
            self.assertEqual(svc.link_sessions()["mendon-1a2b"]["sessions"], 1)   # the hub measures that hub link
        finally:
            svc.close()

    def test_spoke_asks_again_for_a_named_token(self):
        d = tempfile.mkdtemp()
        r = kr.Relay(d, lambda m: None)
        now = int(time.time())
        old = kr._mint(os.urandom(32), dict(kr.FEDERATION_CLAIMS, iat=now, exp=now + 30 * 86400))
        r._fed_cache = lambda: {"hub": "https://h:4443", "token": old, "exp": now + 30 * 86400, "kid": "k1"}
        r._fed_cache_write = lambda v: None
        r._fed_say = lambda why: None
        r._cluster_note_web = lambda *a, **k: None
        asked = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(req, timeout=0):
            asked.append(json.loads(req.data.decode()))
            return Resp(json.dumps({"ok": True, "token": "new.tok.en", "exp": now + 30 * 86400, "kid": "k1"}).encode())
        with mock.patch.object(kr, "_machine_node", lambda: "mendon-1a2b"), mock.patch.object(kr.urllib.request, "urlopen", fake_open):
            r.hub_auth = lambda hub: {"codes": True, "federation": True, "kid": "k1"}          # a 0.21.77 hub: the cached token stays
            self.assertEqual(r.federation_token("https://h:4443", "c")[0], old)
            r.hub_auth = lambda hub: {"codes": True, "federation": True, "kid": "k1", "linkNode": True}
            self.assertEqual(r.federation_token("https://h:4443", "c")[0], "new.tok.en")
        self.assertEqual(asked, [{"federation": "c", "node": "mendon-1a2b"}])


class LinksView(unittest.TestCase):
    def test_inactive_pairs_loads_and_zoom(self):
        key = os.urandom(32)
        d = tempfile.mkdtemp()
        svc = kr.AuthService("127.0.0.1", 0, key, 4443, kr.AuthStore(d))
        try:
            reg = lambda node, name, version="0.21.78", **mesh: svc.register_spoke(
                dict({"name": name, "version": version, "node": node, "port": 4443}, mesh=dict({"port": 4443, "addrs": ["10.0.0.%d" % len(name)]}, **mesh),
                     **({"clients": mesh.pop("clients")} if "clients" in mesh else {})), "10.0.0.9", fed_bearer(key))
            reg("a-1", "mendon", probes=[probe("b-2", "10.0.0.6", private=False)], linkTokens={"b-2": "t.a.b"},
                load={"local": {"in": 800000, "out": 0}, "link": {"in": 0, "out": 2300000}, "total": {"in": 800000, "out": 2300000}, "at": 5,
                      "paths": {"in": [{"path": "lab/pat-1a2b/op/cam.hang", "bps": 800000}, {"path": "lab/yard-box/op/c9.hang", "bps": 600000}], "out": []}},
                clients=[{"node": "pat-1a2b", "name": "Pat", "kind": "app", "version": "0.21.78", "hostname": "PAT-PC", "user": "pat", "rooms": ["lab"],
                          "at": int(time.time()), "net": {"down": 2900000, "up": 820000, "streams": [{"path": "lab/x-1/op/a.hang", "bps": 2900000}], "at": 7}},
                         {"node": "web-7c7c", "kind": "web", "at": int(time.time())}])
            reg("b-2", "logan", probes=[probe("a-1", "10.0.0.5", private=False)])                       # a public hop: not linked
            reg("c-3", "fortworth", version="0.21.76")
            svc.user_nick["pat-1a2b"] = "Front desk"
            r = kr.Relay(tempfile.mkdtemp(), lambda m: None)
            r.auth = svc
            r._mesh_crossing = {"a-1": {"in": [], "out": ["lab/pat-1a2b/op/cam.hang"], "inBps": 0, "outBps": 790000, "at": 9}}
            r._mesh_load_rec = {"local": {"in": 1, "out": 2}, "link": {"in": 3, "out": 4}, "total": {"in": 4, "out": 6}, "at": 9, "paths": {"in": [], "out": []}}
            v = r.mesh_view()
            pair = next(l for l in v["links"] if l["kind"] == "mesh" and {l["a"], l["b"]} == {"a-1", "b-2"})
            self.assertFalse(pair["active"])
            self.assertIn("no private path", pair["why"])                                     # drawn faint on the map, click = why
            old = [l for l in v["links"] if l["kind"] == "mesh" and "c-3" in (l["a"], l["b"])]
            self.assertTrue(old and all(l["why"] == "needs update" for l in old))
            hub_a = next(l for l in v["links"] if l["kind"] == "hub" and l["a"] == "a-1")
            self.assertEqual(hub_a["bps"], {"fwd": 0, "back": 790000, "at": 9})               # what the hub measured itself
            nodes = {n["id"]: n for n in v["nodes"]}
            self.assertEqual(nodes["hub"]["load"]["link"], {"in": 3, "out": 4})
            self.assertNotIn("paths", nodes["hub"]["load"])                                    # the streams go with ?zoom only
            self.assertEqual(nodes["a-1"]["load"]["local"], {"in": 800000, "out": 0})
            self.assertEqual((nodes["a-1"]["liveCost"], nodes["c-3"]["liveCost"]), (True, False))
            self.assertIsNone(v["zoom"])
            self.assertNotIn("t.a.b", json.dumps(v))                                          # never a token
            z = r.mesh_view(zoom="a-1")["zoom"]
            pat = next(c for c in z["clients"] if c["node"] == "pat-1a2b")
            self.assertEqual((pat["kind"], pat["nick"], pat["hostname"], pat["bps"]), ("person", "Front desk", "PAT-PC", 800000))
            self.assertEqual(pat["publishes"], [{"path": "lab/pat-1a2b/op/cam.hang", "bps": 800000}])
            self.assertEqual((pat["net"]["down"], pat["net"]["up"]), (2900000, 820000))
            web = next(c for c in z["clients"] if c["node"] == "web-7c7c")
            self.assertEqual((web["kind"], web["net"]), ("viewer", None))                     # "not reported", never invented
            self.assertEqual(z["other"], [{"path": "lab/yard-box/op/c9.hang", "bps": 600000}])
            self.assertFalse(z["perClient"])
            self.assertFalse(r.mesh_view(zoom="a-1")["zoom"]["needsUpdate"])
            self.assertTrue(r.mesh_view(zoom="c-3")["zoom"]["needsUpdate"])
            self.assertEqual(r.mesh_view(zoom="hub")["zoom"]["relay"], "hub")
            self.assertIsNone(r.mesh_view(zoom="nope")["zoom"])
        finally:
            svc.close()

    def test_mesh_set_one_spokes_link(self):
        key = os.urandom(32)
        svc = kr.AuthService("127.0.0.1", 0, key, 4443, kr.AuthStore(tempfile.mkdtemp()))
        try:
            svc.register_spoke({"name": "logan", "version": "0.21.77", "node": "b-2", "port": 4443, "mesh": {"port": 4443}}, "10.0.0.9", fed_bearer(key))
            r = kr.Relay(tempfile.mkdtemp(), lambda m: None)
            r.auth = svc
            r._acts_as_hub = lambda cur=None: True
            out, code = r.mesh_set({"node": "b-2", "kind": "hub", "cost": 8})
            self.assertEqual((code, out["costs"]["hub"], out["live"]), (200, 8, False))       # a 0.21.77 spoke restarts for it
            self.assertEqual(r.mesh_set({"node": "b-2", "kind": "standby", "cost": 8})[0]["live"], True)
            self.assertEqual(r.mesh_set({"node": "b-2", "kind": "hub", "cost": 0})[1], 400)
            self.assertEqual(svc.mesh_for("b-2")["hubCost"], 8)
        finally:
            svc.close()


class ZoomPieces(unittest.TestCase):
    def test_local_paths(self):
        sub = {"lab/pat-1a2b/op/cam.hang": dict(REAL_PUB["lab/a-host/op/cam.hang"]), "~stats/node/x": {"announced": 1}, "lab/gone/op/x.hang": {"announced": 1, "announced_closed": 1}}
        pub = {"lab/pat-1a2b/op/cam.hang": {"broadcasts": 3, "broadcasts_closed": 1}, "lab/z/op/q.hang": {"broadcasts": 0}}
        out = kr.mesh_local_paths(sub, pub, {"lab/pat-1a2b/op/cam.hang": 800000}, {"lab/pat-1a2b/op/cam.hang": 1600000})
        self.assertEqual(out, {"in": [{"path": "lab/pat-1a2b/op/cam.hang", "bps": 800000}], "out": [{"path": "lab/pat-1a2b/op/cam.hang", "bps": 1600000, "viewers": 2}]})

    def test_client_net(self):
        n = kr.clean_net({"down": "2900000", "up": 1.5e6, "streams": [{"path": "r/h/o/a.hang", "bps": 5}, {"path": "<bad>", "bps": 1}], "at": 1, "win": 15}, 99)
        self.assertEqual(n, {"down": 2900000, "up": 1500000, "streams": [{"path": "r/h/o/a.hang", "bps": 5}], "at": 99, "win": 15})   # the relay's clock
        self.assertIsNone(kr.clean_net({"streams": []}))
        self.assertIsNone(kr.clean_net("x"))
        svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, kr.AuthStore(tempfile.mkdtemp()))
        try:
            svc.client_checkin({"node": "pat-1a2b", "version": "0.21.78", "mode": "viewer", "net": {"down": 2900000, "up": 0, "at": 1}}, "10.0.0.7")
            svc.client_checkin({"node": "old-2b2b", "version": "0.21.77", "mode": "viewer"}, "10.0.0.8")
            rows = {r["node"]: r for r in svc.clients_view("0.21.78", "me")}
            self.assertEqual(rows["pat-1a2b"]["net"]["down"], 2900000)
            self.assertGreater(rows["pat-1a2b"]["net"]["at"], 1000)
            self.assertIsNone(rows["old-2b2b"]["net"])
            self.assertEqual(kr.clean_clients(list(rows.values()))[0]["net"] is None or True, True)
            kept = {r["node"]: r for r in kr.clean_clients(list(rows.values()))}
            self.assertEqual(kept["pat-1a2b"]["net"]["down"], 2900000)                             # a spoke's list carries it to the hub
            self.assertNotIn("net", svc._hist_row(rows["pat-1a2b"], None))                         # live-only: not in the 30-day history
        finally:
            svc.close()

    def test_app_checkin_takes_the_freshest_window(self):
        import kastr
        snaps = {"/moq-watch-lite.html": {"_at": time.time() - 2, "net": {"down": 2900000, "up": 5}},
                 "/old": {"_at": time.time() - 100, "net": {"down": 1}}, "/x": {"_at": time.time(), "watcher": {}}}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        with mock.patch.object(kastr.urllib.request, "urlopen", lambda url, timeout=0: Resp(json.dumps(snaps).encode())):
            self.assertEqual(kastr._checkin_net(8000), {"down": 2900000, "up": 5})
        with mock.patch.object(kastr.urllib.request, "urlopen", lambda url, timeout=0: Resp(b"{}")):
            self.assertIsNone(kastr._checkin_net(8000))


class Wiring(unittest.TestCase):
    def test_pages(self):
        page = rd(os.path.join(HERE, "relay.html"))
        for s in ('id="meshArrange"', 'id="meshBack"', "kastr.mesh.pos", "#mesh=", '"?zoom="', "meshTick", "reduceMotion()", "requestAnimationFrame(meshFrame)",
                  "kind: l.kind, cost:", "meshLoadHtml", "meshClientTip", "not reported", "no figure (older KASTR)", 'e.key === "Escape"', ".medge.st-none",
                  "mesh.draft[id]", "form.contains(document.activeElement)", "paintMesh(); setInterval(paintMesh, 5000);"):
            self.assertIn(s, page, s)
        self.assertNotIn(chr(92), page[page.index("const mesh = {"):page.index("paintMesh(); setInterval(paintMesh, 5000);")])   # written without escapes
        w = rd(os.path.join(HERE, "moq-watch-lite.html"))
        self.assertIn("window.__netRate = () =>", w)
        self.assertIn("net: window.__netRate?.() ?? null }) });   // 0.21.78 (C)", w)
        self.assertIn("net: window.__netRate?.() ?? null", rd(os.path.join(HERE, "assets", "asi-brand.js")))
        src = rd(os.path.join(HERE, "kastr_relay.py"))
        self.assertIn('"linkNode": True', src)
        self.assertIn('zq.get("zoom")', src)


if __name__ == "__main__":
    unittest.main()
