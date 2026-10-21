# -*- coding: utf-8 -*-
"""0.21.77: the RELAY MESH (Kenton: "customize the next hop of relays ... I don't want everything to necessarily go through the
hub except the tracks that actually do get seen through it"; "Can we have the relays do a traceroute to check if they go over
a public IP, and if they can reach each other without going to a public IP, they could just mesh to each other"; then: hub +
standby links as last-resort data paths at a high cost, and a visual mesh on the hub's Relay page).
Covers what needs no network: probe classification (tracert / traceroute / tracepath output), the hub's link computation with
overrides, the standby link and version gating, relay.toml (connect object + connect_api + id/node/tier, no pin),
relay-peers.json, per-peer link state off the relay log, the link token (never a federation Bearer), the stats parsing behind
"streams crossing now", and the Relay page wiring. The data paths themselves were proven in the WSL netns lab
(scratchpad v02177/mesh: lab_results.md) and with three harnesses."""
import io, json, os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

TRACERT_PRIVATE = """
Tracing route to 10.20.0.5 over a maximum of 15 hops

  1    <1 ms    <1 ms    <1 ms  192.168.1.1
  2     *        *        *     Request timed out.
  3    11 ms    12 ms    11 ms  10.8.0.1
  4    12 ms    12 ms    13 ms  10.20.0.5

Trace complete.
"""
TRACERT_PUBLIC = """
Tracing route to 10.20.0.5 over a maximum of 15 hops

  1    <1 ms    <1 ms    <1 ms  192.168.1.1
  2     9 ms     8 ms     9 ms  73.25.1.9
  3    20 ms    19 ms    21 ms  10.20.0.5

Trace complete.
"""
TRACEROUTE = """traceroute to 100.70.1.2 (100.70.1.2), 15 hops max, 60 byte packets
 1  172.17.0.1  0.120 ms
 2  * * *
 3  100.64.0.1  4.511 ms 100.64.0.9  4.700 ms
 4  100.70.1.2  5.001 ms
"""
TRACEPATH = """ 1?: [LOCALHOST]                      pmtu 1500
 1:  10.0.0.1                                              0.345ms
 2:  no reply
 3:  10.0.5.2                                              1.020ms reached
     Resume: pmtu 1500 hops 3 back 3
"""


def rd(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def fed_bearer(key):
    now = int(time.time())
    return "Bearer " + kr._mint(key, dict(kr.FEDERATION_CLAIMS, iat=now, exp=now + 600))


class Probe(unittest.TestCase):
    def test_private_ranges(self):
        for ip in ("10.1.2.3", "172.16.0.1", "172.31.255.1", "192.168.50.7", "100.64.0.1", "100.127.255.254", "fd12::1"):
            self.assertTrue(kr.mesh_private(ip), ip)
        for ip in ("8.8.8.8", "172.32.0.1", "100.128.0.1", "169.254.1.1", "2001:db8::1", "nonsense"):
            self.assertFalse(kr.mesh_private(ip), ip)

    def test_tracert_private_path(self):
        hops = kr.parse_trace(TRACERT_PRIVATE)
        self.assertEqual([h["hop"] for h in hops], [1, 2, 3, 4])       # the banner's address is not a hop
        self.assertEqual(hops[1]["ips"], [])                             # "*" -- no answer, never held against it
        self.assertEqual(kr.trace_verdict(hops, "10.20.0.5"), (True, 4, []))

    def test_tracert_public_hop(self):
        priv, n, pub = kr.trace_verdict(kr.parse_trace(TRACERT_PUBLIC), "10.20.0.5")
        self.assertEqual((priv, n, pub), (False, 3, ["73.25.1.9"]))

    def test_traceroute_and_tracepath(self):
        hops = kr.parse_trace(TRACEROUTE)
        self.assertEqual(hops[2]["ips"], ["100.64.0.1", "100.64.0.9"])  # two answers on one hop
        self.assertEqual(kr.trace_verdict(hops, "100.70.1.2")[:2], (True, 4))
        hops = kr.parse_trace(TRACEPATH)
        self.assertEqual([h["hop"] for h in hops], [1, 2, 3])            # [LOCALHOST] and Resume are not hops
        self.assertEqual(kr.trace_verdict(hops, "10.0.5.2")[:2], (True, 3))

    def test_mesh_probe(self):
        dead = kr.mesh_probe("b", "10.0.0.5", 4443, http=lambda ip, port: (False, None, "timeout"), trace=lambda ip: self.fail("no trace"))
        self.assertEqual((dead["ok"], dead["err"], dead["private"]), (False, "timeout", False))
        ok = kr.mesh_probe("b", "10.20.0.5", 4443, http=lambda ip, port: (True, 23.4, ""), trace=lambda ip: ("tracert", TRACERT_PRIVATE))
        self.assertEqual((ok["ok"], ok["rttMs"], ok["hops"], ok["private"], ok["tool"]), (True, 23.4, 4, True, "tracert"))
        self.assertEqual(ok["path"], ["192.168.1.1", "*", "10.8.0.1", "10.20.0.5"])
        pub = kr.mesh_probe("b", "10.20.0.5", 4443, http=lambda ip, port: (True, 30.0, ""), trace=lambda ip: ("tracert", TRACERT_PUBLIC))
        self.assertFalse(pub["private"])
        self.assertEqual(pub["public"], ["73.25.1.9"])
        # no traceroute tool: a private address counts as private, hops from one ping's TTL
        nt = kr.mesh_probe("b", "192.168.9.9", 4443, http=lambda ip, port: (True, 2.0, ""), trace=lambda ip: (None, ""), hops=lambda ip: 2)
        self.assertEqual((nt["private"], nt["hops"], nt["tool"]), (True, 2, "ttl"))

    def test_cost(self):
        self.assertEqual([kr.mesh_cost(x) for x in (0.4, 4, 23, 140)], [1, 1, 3, 15])
        self.assertIsNone(kr.mesh_cost(None))
        self.assertEqual(kr.MESH_HUB_COST_DEFAULT, 50)                   # the hub / standby links: the last resort


def spoke(node, name, version="0.21.77", addrs=("10.0.0.1",), port=4443, probes=(), tokens=None, links=(), at=None, **mesh):
    m = {"v": 1, "port": port, "addrs": list(addrs), "probes": list(probes), "linkTokens": dict(tokens or {}), "links": list(links)}
    m.update(mesh)
    return {"node": node, "name": name, "version": version, "at": time.time() if at is None else at, "port": port, "mesh": m}


def probe(node, addr, ok=True, private=True, rtt=12.0, at=None, ok_at=None, err=""):
    t = int(time.time()) if at is None else at
    return {"node": node, "addr": addr, "port": 4443, "ok": ok, "rttMs": rtt, "hops": 2, "private": private, "tool": "tracert",
            "path": [addr], "public": [], "err": err, "at": t, "okAt": ok_at if ok_at is not None else (t if ok and private else None)}


class Links(unittest.TestCase):
    def setUp(self):
        self.a = spoke("a-1", "mendon", addrs=("10.0.0.1",), probes=[probe("b-2", "10.0.0.2", rtt=23)], tokens={"b-2": "tokA4B"})
        self.b = spoke("b-2", "logan", addrs=("10.0.0.2", "172.20.0.2"), probes=[probe("a-1", "10.0.0.1", rtt=25)], tokens={"a-1": "tokB4A"})

    def test_auto_link_from_a_private_path(self):
        links, state = kr.mesh_links([self.a, self.b])
        row = next(l for l in links if l["kind"] == "mesh")
        # both reached each other privately -> the lower node id dials; its cost is 1 + RTT/10 of ITS probe
        self.assertEqual((row["active"], row["dialer"], row["acceptor"], row["cost"], row["how"]), (True, "a-1", "b-2", 3, "auto"))
        self.assertEqual(state["a-1"]["links"], [{"url": "http://10.0.0.2:4443/", "cost": 3, "token": "tokB4A", "peer": "b-2", "name": "logan", "kind": "mesh"}])
        self.assertEqual(state["b-2"]["links"], [])                       # one dialer per pair
        self.assertEqual(state["a-1"]["mint"], ["b-2"])                   # mint a token for every relay that may dial you
        self.assertEqual(state["a-1"]["candidates"][0]["addrs"], ["10.0.0.2", "172.20.0.2"])
        self.assertEqual(state["a-1"]["hubCost"], 50)
        self.assertNotIn("token", json.dumps(links))                     # the Links card never carries a token
        self.assertNotIn("tokB4A", json.dumps(links))

    def test_only_one_side_reached(self):
        self.a["mesh"]["probes"] = [probe("b-2", "10.0.0.2", ok=False, private=False, err="timeout")]
        links, state = kr.mesh_links([self.a, self.b])
        row = next(l for l in links if l["kind"] == "mesh")
        self.assertEqual(row["dialer"], "b-2")                            # the side that reached it dials
        self.assertEqual(state["b-2"]["links"][0]["token"], "tokA4B")    # with the token the OTHER end minted for it

    def test_public_path_is_no_link_and_timeout_hints_the_firewall(self):
        self.a["mesh"]["probes"] = [probe("b-2", "10.0.0.2", private=False)]
        self.b["mesh"]["probes"] = [probe("a-1", "10.0.0.1", ok=False, private=False, err="timeout")]
        links, state = kr.mesh_links([self.a, self.b])
        row = next(l for l in links if l["kind"] == "mesh")
        self.assertFalse(row["active"])
        self.assertIn("no private path", row["why"])
        self.assertEqual(row["hint"], "blocked? open UDP 4443 and TCP 4443 on mendon")
        self.assertEqual(state["a-1"]["links"] + state["b-2"]["links"], [])

    def test_a_recent_private_path_survives_an_outage(self):
        old = int(time.time()) - 3600
        self.a["mesh"]["probes"] = [probe("b-2", "10.0.0.2", ok=False, private=False, err="timeout", ok_at=old)]
        self.b["mesh"]["probes"] = []
        links, state = kr.mesh_links([self.a, self.b])
        self.assertEqual(len(state["a-1"]["links"]), 1)                   # no flapping while B reboots
        self.a["mesh"]["probes"][0]["okAt"] = int(time.time()) - 2 * 86400
        self.assertEqual(kr.mesh_links([self.a, self.b])[1]["a-1"]["links"], [])

    def test_overrides(self):
        links, state = kr.mesh_links([self.a, self.b], {"a-1|b-2": {"mode": "off"}})
        self.assertEqual(state["a-1"]["links"], [])
        self.assertEqual(next(l for l in links if l["kind"] == "mesh")["why"], "switched off")
        links, state = kr.mesh_links([self.a, self.b], {"a-1|b-2": {"mode": "auto", "cost": 7, "addr": "10.9.9.9"}})
        self.assertEqual((state["a-1"]["links"][0]["cost"], state["a-1"]["links"][0]["url"]), (7, "http://10.9.9.9:4443/"))
        self.assertEqual(next(l for l in links if l["kind"] == "mesh")["how"], "manual")
        # ON with no private path: linked anyway (the side that answered dials)
        self.a["mesh"]["probes"] = [probe("b-2", "10.0.0.2", private=False, rtt=40)]
        self.b["mesh"]["probes"] = []
        links, state = kr.mesh_links([self.a, self.b], {"a-1|b-2": {"mode": "on"}})
        self.assertEqual(state["a-1"]["links"][0]["cost"], 5)
        self.assertTrue(next(l for l in links if l["kind"] == "mesh")["active"])

    def test_preferred_address_is_the_listed_order(self):
        self.a["mesh"]["probes"] = [probe("b-2", "172.20.0.2", rtt=0.5), probe("b-2", "10.0.0.2", rtt=3)]
        links, state = kr.mesh_links([self.a, self.b])
        self.assertEqual(state["a-1"]["links"][0]["url"], "http://10.0.0.2:4443/")   # the 172.x bridge only when nothing else answers

    def test_version_gating(self):
        old = spoke("c-3", "fortworth", version="0.21.76")
        old.pop("mesh")
        links, state = kr.mesh_links([self.a, self.b, old])
        self.assertNotIn("c-3", state)
        self.assertNotIn("c-3", [c["node"] for c in state["a-1"]["candidates"]])
        rows = [l for l in links if "c-3" in (l["a"], l["b"]) and l["kind"] == "mesh"]
        self.assertTrue(rows and all(l["why"] == "needs update" and l["needsUpdate"] == ["fortworth"] for l in rows))
        self.assertFalse(kr.mesh_capable("0.21.76-dev"))
        self.assertTrue(kr.mesh_capable("0.21.77") and kr.mesh_capable("0.22.0"))

    def test_waiting_for_the_token(self):
        self.b["mesh"]["linkTokens"] = {}
        links, state = kr.mesh_links([self.a, self.b])
        self.assertEqual(state["a-1"]["links"], [])
        self.assertIn("link token", next(l for l in links if l["kind"] == "mesh")["why"])

    def test_standby_link_at_the_hub_cost(self):
        c = spoke("c-3", "southridge", addrs=("10.0.0.3",), tokens={"a-1": "tokC4A", "b-2": "tokC4B"})
        sb = {"node": "c-3", "name": "southridge", "address": "https://10.0.0.3:4443"}
        links, state = kr.mesh_links([self.a, self.b, c], {}, 60, sb)
        self.assertIn({"url": "http://10.0.0.3:4443/", "cost": 60, "token": "tokC4A", "peer": "c-3", "name": "southridge", "kind": "standby"},
                      state["a-1"]["links"])
        self.assertEqual([l["kind"] for l in state["c-3"]["links"]], [])  # the standby does not dial itself
        self.assertEqual(state["a-1"]["hubCost"], 60)
        # a direct link between a spoke and the standby replaces its standby link (one session per pair)
        c["mesh"]["probes"] = [probe("a-1", "10.0.0.1", rtt=4)]
        self.a["mesh"]["linkTokens"]["c-3"] = "tokA4C"
        links, state = kr.mesh_links([self.a, self.b, c], {}, 60, sb)
        kinds = [(l["peer"], l["kind"]) for l in state["a-1"]["links"]]
        self.assertNotIn(("c-3", "standby"), kinds)
        self.assertIn(("a-1", "mesh"), [(l["peer"], l["kind"]) for l in state["c-3"]["links"]])
        self.assertEqual(next(l for l in links if l["kind"] == "standby" and l["a"] == "a-1")["why"], "a direct link joins them")


class LinkToken(unittest.TestCase):
    def test_claims_grant_and_not_a_federation_bearer(self):
        key = os.urandom(32)
        c = kr.mesh_link_claims("Mendon-1A2B", now=1000)
        self.assertEqual((c["link"], c["exp"] - c["iat"], c["publish"], c["subscribe"]), ("mendon-1a2b", kr.MESH_LINK_TTL, ["**"], ["**"]))
        self.assertTrue(kr.is_link_claims(c))
        self.assertFalse(kr.is_relay_claims(c))
        self.assertEqual(kr.claims_role(c), "link")
        g = kr.claims_to_grant(c, now=1000)
        self.assertEqual((g["publish"], g["subscribe"], g["peer"], g["tier"]), (["**"], ["**"], True, "link-mendon-1a2b"))
        self.assertNotIn("peer", kr.claims_to_grant(dict(kr.FEDERATION_CLAIMS, exp=2000), now=1000))   # federation: unchanged
        svc = kr.AuthService("127.0.0.1", 0, key, 4443, kr.AuthStore(tempfile.mkdtemp()))
        try:
            tok = kr._mint(key, kr.mesh_link_claims("x", now=int(time.time())))
            self.assertIsNone(svc._bearer_relay("Bearer " + tok))
            self.assertEqual(svc.register_spoke({"name": "x"}, "10.0.0.9", "Bearer " + tok)[1], 403)
            self.assertEqual(svc.bans_for_spoke("Bearer " + tok)[1], 403)
            # the session hook grants it (a link) and remembers the dialer
            st, grant, why = kr.session_grant({"query": "jwt=" + tok}, key)
            self.assertEqual((st, why, grant["tier"]), ("grant", "link", "link-x"))
            obj, code = svc.session({"event": "connect", "id": "s1", "remote": "10.0.0.9:5000", "query": "jwt=" + tok}, "127.0.0.1")
            self.assertEqual(code, 200)
            self.assertEqual(svc.link_sessions()["x"]["sessions"], 1)
            svc.session({"event": "end", "id": "s1"}, "127.0.0.1")
            self.assertEqual(svc.link_sessions(), {})
        finally:
            svc.close()


class HubSide(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.key = os.urandom(32)
        self.svc = kr.AuthService("127.0.0.1", 0, self.key, 4443, kr.AuthStore(self.d))

    def tearDown(self):
        self.svc.close()

    def reg(self, node, name, **mesh):
        body = {"name": name, "version": "0.21.77", "node": node, "port": 4443, "mesh": dict({"port": 4443, "addrs": ["10.0.0.%d" % (len(name))]}, **mesh)}
        return self.svc.register_spoke(body, "10.0.0.9", fed_bearer(self.key))

    def test_register_keeps_the_report_and_the_long_poll_carries_state(self):
        self.assertEqual(self.reg("a-1", "mendon", probes=[probe("b-2", "10.0.0.5")], linkTokens={"b-2": "t.a.b"})[1], 200)
        self.assertEqual(self.reg("b-2", "logan", probes=[probe("a-1", "10.0.0.6")], linkTokens={"a-1": "t.b.a", "bad node!": "x"})[1], 200)
        row = self.svc.spokes["spoke:logan"]
        self.assertEqual(row["mesh"]["linkTokens"], {"a-1": "t.b.a"})
        self.assertNotIn("mesh", json.dumps(self.svc.spokes_public()))   # the spokes table never shows the report
        out, code = self.svc.bans_for_spoke(fed_bearer(self.key), node="a-1")
        self.assertEqual(code, 200)
        self.assertEqual(out["mesh"]["links"][0]["token"], "t.b.a")
        self.assertEqual(out["mesh"]["hubCost"], 50)
        self.assertEqual(self.svc.bans_for_spoke(fed_bearer(self.key), node="zz-9")[0]["mesh"], {"v": 1, "hubCost": 50})

    def test_report_cleaning(self):
        m = kr.mesh_report_clean({"port": "4443", "addrs": ["10.0.0.1", "8.8.8.8", 5], "probes": [{"node": "Bad Node"}, probe("b-2", "10.0.0.2")],
                                  "links": [{"peer": "http://10.0.0.2:4443", "up": True, "since": 5, "drops": 1}],
                                  "crossing": {"b-2": {"in": ["r/h/o/cam.hang", "bad path!"], "out": []}}, "hubLink": {"up": "yes"}})
        self.assertEqual((m["port"], m["addrs"], len(m["probes"])), (4443, ["10.0.0.1"], 1))
        self.assertEqual(m["links"][0]["peer"], "http://10.0.0.2:4443/")
        self.assertEqual(m["crossing"]["b-2"]["in"], ["r/h/o/cam.hang"])
        self.assertIsNone(m["hubLink"]["up"])
        self.assertIsNone(kr.mesh_report_clean("nope"))


class StoreOverrides(unittest.TestCase):
    def test_persist_validate_bundle(self):
        d = tempfile.mkdtemp()
        st = kr.AuthStore(d)
        self.assertEqual(st.link_override("a-1", "a-1")[1], "pick two relays")
        self.assertEqual(st.link_override("a-1", "b-2", mode="sideways")[1], "mode is auto, on or off")
        self.assertIn("whole number", st.link_override("a-1", "b-2", cost="2.5")[1])
        rec, err = st.link_override("b-2", "a-1", mode="off")
        self.assertEqual((err, rec["mode"]), (None, "off"))
        self.assertEqual(list(kr.AuthStore(d).links_public()), ["a-1|b-2"])   # sorted key, persisted
        self.assertEqual(st.link_override("a-1", "b-2", mode="auto", cost=None, addr="")[0], None)   # all automatic = forgotten
        self.assertEqual(kr.AuthStore(d).links_public(), {})
        self.assertEqual(st.set_hub_cost(0)[1] is not None, True)
        self.assertEqual(st.set_hub_cost("70"), (70, None))
        st.link_override("a-1", "b-2", cost=4)
        b = st.export_bundle()
        st2 = kr.AuthStore(tempfile.mkdtemp())
        st2.import_bundle(b)
        self.assertEqual((st2.mesh_hub_cost(), st2.links_public()["a-1|b-2"]["cost"]), (70, 4))
        b["links"]["a-1|b-2"] = dict(b["links"]["a-1|b-2"], cost=9, at=int(time.time()) + 5)
        st.merge_bundle(b)
        self.assertEqual(st.links_public()["a-1|b-2"]["cost"], 9)        # set later on the standby: kept at hand-back


class SpokeConfig(unittest.TestCase):
    def relay(self, mesh=None):
        d = tempfile.mkdtemp()
        kr.save_json(os.path.join(d, "relay-cluster.json"), {"connect": "https://127.0.0.1:1", "code": "x"})
        if mesh is not None:
            kr.save_json(os.path.join(d, "relay-mesh.json"), mesh)
        r = kr.Relay(d, lambda m: None)
        r.federation_token = lambda hub, code, force=False: ("fed.tok.en", "hub token cached", {"fingerprint": "ab" * 32})
        r._hub_pin_for = lambda hub, hint=None: ("ab" * 32, "pinned")
        return r, d

    def test_spoke_relay_toml(self):
        r, d = self.relay({"hubCost": 40, "links": [{"url": "http://10.1.1.2:4443/", "cost": 3, "token": "l.t.k", "peer": "b-2", "name": "logan", "kind": "mesh"}]})
        cfg = rd(r._write_config(4443, True, True))
        self.assertIn('connect = [{ url = "http://127.0.0.1:1/", cost = 40, token = "fed.tok.en" }]', cfg)   # no ?jwt= / ?cost= in the URL
        self.assertIn('connect_api = "relay-peers.json"', cfg)
        self.assertIn('tier = "cluster"', cfg)
        self.assertIn("id = %d" % kr.mesh_cluster_id(kr._machine_node(), 4443), cfg)
        self.assertNotEqual(kr.mesh_cluster_id("m", 4443), kr.mesh_cluster_id("m", 4453))   # two relays on one machine
        self.assertNotIn("tls.fingerprint", cfg)                          # a pin would turn every http:// peer into plain WebSocket
        self.assertNotIn("tls.insecure", cfg)
        self.assertEqual(json.loads(rd(os.path.join(d, "relay-peers.json"))), [{"url": "http://10.1.1.2:4443/", "cost": 3, "token": "l.t.k"}])
        self.assertEqual(r.federation["tls"], "per-dial")
        self.assertTrue(0 < kr.mesh_cluster_id("x") < 2 ** 52)

    def test_hub_and_standalone_toml(self):
        d = tempfile.mkdtemp()
        cfg = rd(kr.Relay(d, lambda m: None)._write_config(4999, False, False))
        self.assertIn("[cluster]\nid = ", cfg)
        self.assertNotIn("connect", cfg)
        self.assertFalse(os.path.exists(os.path.join(d, "relay-peers.json")))

    def test_collapse_fix_on_every_relay(self):
        # 0.21.77 (lab 2026-10-21, both 0.17.0 and 0.17.7): a stream window smaller than a group + a 2 s cache keep a thin
        # link between relays live (two 1080p tracks over 4 Mbit/s held 29.9 fps for 445 s) -- hub, spoke and standalone
        r, _ = self.relay()
        for cfg in (rd(r._write_config(4443, True, True)), rd(kr.Relay(tempfile.mkdtemp(), lambda m: None)._write_config(4999, False, False))):
            self.assertIn("[quic]\nstream_receive_window = 262144\nsend_window = 67108864\n", cfg)
            self.assertIn('[cache]\nduration = "2s"\n', cfg)
            try:
                import tomllib
            except ImportError:
                continue
            t = tomllib.loads(cfg)
            self.assertEqual(t["quic"], {"stream_receive_window": 262144, "send_window": 67108864})
            self.assertEqual(t["cache"], {"duration": "2s"})

    def test_mesh_state_writes_peers_and_restarts_only_for_the_hub_cost(self):
        r, d = self.relay()
        r._write_config(4443, True, True)
        restarted = []
        r._restart = lambda: restarted.append(1)
        r.running = lambda: True
        r._clients_changed = lambda: None
        r._mesh_seen({"hubCost": 50, "candidates": [{"node": "b-2", "name": "logan", "port": 4443, "addrs": ["10.0.0.2", "8.8.8.8"]}], "mint": ["b-2"],
                      "links": [{"url": "http://10.0.0.2:4443/", "cost": 3, "token": "t.b.a", "peer": "b-2", "name": "logan"},
                                {"url": "http://10.0.0.2:4443/", "cost": 9, "token": "t.b.a", "peer": "b-2", "name": "dup"},
                                {"url": "http://127.0.0.1:1/", "cost": 50, "token": "t", "peer": "hub", "name": "the hub itself"},
                                {"url": "ftp://nope/", "cost": 1}]})
        peers = json.loads(rd(os.path.join(d, "relay-peers.json")))
        self.assertEqual(peers, [{"url": "http://10.0.0.2:4443/", "cost": 3, "token": "t.b.a"}])   # one per peer, never the hub's own address
        self.assertEqual(r._mesh_load()["candidates"][0]["addrs"], ["10.0.0.2"])
        self.assertEqual(json.loads(rd(os.path.join(d, "relay-mesh.json")))["hubCost"], 50)
        time.sleep(0.2)
        self.assertEqual(restarted, [])
        r._mesh_seen({"hubCost": 70})
        time.sleep(0.3)
        self.assertEqual(restarted, [1])                                  # the hub link's cost rides the static connect

    def test_link_tokens_minted_per_dialer_and_kept(self):
        r, d = self.relay()

        class A:
            key = os.urandom(32)
        r.auth = A()
        r._mesh = {"mint": ["b-2", "c-3"]}
        t1 = r._mesh_tokens()
        self.assertEqual(sorted(t1), ["b-2", "c-3"])
        self.assertEqual(kr.verify_token(t1["b-2"], A.key)["link"], "b-2")
        self.assertEqual(r._mesh_tokens(), t1)                            # kept, not re-minted every registration


class PeerLinkState(unittest.TestCase):
    def test_lines_per_peer(self):
        r = kr.Relay(tempfile.mkdtemp(), lambda m: None)
        r.federation = {"hub": "https://10.0.0.1:4443"}
        r._hub_dial = "http://10.0.0.1:4443/"
        r._mesh_peer_urls = {"http://10.0.0.2:4443/"}
        r._clients_changed = lambda: None
        hub = []
        r._link_event = lambda up, why: hub.append(up)
        r._link_line("2026-10-21T15:05:20Z  INFO moq_tokio::connection: connected peer=http://10.0.0.2:4443")
        self.assertEqual(r._mesh_peers["http://10.0.0.2:4443/"]["up"], True)
        r._link_line("2026-10-21T15:07:01Z  WARN moq_tokio::connection: session closed, reconnecting peer=http://10.0.0.2:4443")
        st = r._mesh_peers["http://10.0.0.2:4443/"]
        self.assertEqual((st["up"], st["drops"]), (False, 1))
        self.assertEqual(hub, [])                                         # a peer going down is never the hub's link
        r._link_line("WARN moq_tokio::websocket: WebSocket connection failed err=IO error")   # names no peer: /nodes decides
        self.assertEqual(hub, [])
        r._link_line("INFO moq_tokio::connection: connected peer=http://10.0.0.1:4443")
        r._link_line("WARN moq_tokio::connection: session closed, reconnecting peer=http://10.0.0.1:4443")
        self.assertEqual(hub, [True, False])
        r._mesh_peer_urls = set()                                         # no peers: the old rules for the hub
        r._link_line("WARN moq_tokio::websocket: WebSocket connection failed err=IO error")
        self.assertEqual(hub, [True, False, False])


class StreamsCrossing(unittest.TestCase):
    def test_open_paths_from_link_tier_stats(self):
        sub = {"lab/a-host/op/cam.hang": {"subscriptions_started": 4, "subscriptions_ended": 2, "broadcasts_started": 0, "broadcasts_ended": 0, "bytes": 99},
               "lab/a-host/op/cam2.hang": {"subscriptions_started": 2, "subscriptions_ended": 2, "broadcasts_started": 0, "broadcasts_ended": 0},
               "~stats/node/x": {"subscriptions_started": 1, "subscriptions_ended": 0}}
        self.assertEqual(kr.mesh_open_paths(sub, "subscriber.json"), ["lab/a-host/op/cam.hang"])
        pub = {"r/h/o/x.hang": {"subscriptions_started": 0, "subscriptions_ended": 0, "broadcasts_started": 1, "broadcasts_ended": 0}}
        self.assertEqual(kr.mesh_open_paths(pub, "publisher.json"), ["r/h/o/x.hang"])
        self.assertEqual(kr.mesh_open_paths(pub, "subscriber.json"), [])
        self.assertEqual(kr.mesh_open_paths("garbage"), [])


class Wiring(unittest.TestCase):
    def test_relay_page(self):
        page = rd(os.path.join(HERE, "relay.html"))
        for s in ('id="linksBox"', 'id="meshSvg"', 'id="meshHubCost"', 'id="meshTblBox"', '"/api/relay/links"', "prefers-reduced-motion: reduce) { .meshwrap",
                  "kastr.mesh.pos", "paintMesh(); setInterval(paintMesh, 5000);", 'f.tls === "per-dial"'):
            self.assertIn(s, page, s)
        self.assertIn("/api/relay/links", kr.GUARDED_POSTS)
        src = rd(os.path.join(HERE, "kastr_relay.py"))
        self.assertIn('if path == "/api/relay/links":', src)
        self.assertNotIn("_fingerprint_check(", src)                     # a peer's certificate trouble never re-learns the hub pin


if __name__ == "__main__":
    unittest.main()
