# -*- coding: utf-8 -*-
"""v0.21.17: KASTR's control paths live under '~' (moq-relay >= 0.15.3 and @moq/net >= 0.4.2 hide every '.'-led path
segment from listings and browser announces -- measured 2026-10-05). These tests pin the rename on every side: the minter's
grants, role and identity classification ('~' only since 0.21.40 -- pre-0.21.17 tokens are long expired), the relay's
stats prefix (and no LAN mesh block since 0.21.40), the HTTP side doors, and the pages (no '.'-spelled control kind may
come back)."""
import io, os, re, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

KINDS = "state|presence|channels|talking|chat|stats|since|stalled|spotlight|recording|mediactl|avatar|files|grid|media|admin|member"
DOT_KIND = re.compile(r"""(["'`/])\.(%s)\b""" % KINDS)


def read(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return f.read()


class Constants(unittest.TestCase):
    def test_namespace_is_tilde(self):
        self.assertEqual(kr.NS, "~")
        self.assertEqual(kr.STATE_PREFIX, "~state")
        self.assertEqual(kr.ADMIN_KIND, "~admin")
        self.assertEqual(kr.STATS_KIND, "~stats")
        self.assertEqual(kr.CHANNELS_KIND, "~channels")
        self.assertEqual(kr.MEMBER_SEG, "~member")
        self.assertEqual(kr.SINCE_KIND, "~since")

    def test_every_kind_is_in_the_namespace(self):
        for k in kr.VIEWER_KINDS + kr.MEMBER_KINDS + kr.PUBLIC_KINDS:
            self.assertTrue(k.startswith(kr.NS), k)
            self.assertFalse(k.startswith("."), k)

    def test_public_patterns_cover_the_new_kinds(self):
        pats = kr.public_patterns()
        for k in ("~channels", "~stats", "~presence", "~talking", "~chat", "~state"):
            self.assertTrue(any(p == k or p.startswith(k + "/") for p in pats), (k, pats))
        self.assertFalse(any(p.startswith(".") for p in pats), pats)


class Roles(unittest.TestCase):
    def test_viewer_token_is_a_viewer(self):
        new = {"put": ["~state/r/h-1a2b", "r/h-1a2b/~member", "r/~since", "~presence/r"], "get": "r"}
        self.assertEqual(kr.claims_role(new), "viewer")

    def test_publisher_token_is_a_publisher(self):
        self.assertEqual(kr.claims_role({"put": ["r/h-1a2b", "~state/r/h-1a2b", "r/~since", "~presence/r"]}), "publisher")

    def test_viewer_wide_token_stays_viewer(self):
        wide_viewer = {"get": "r", "put": ["r/" + k for k in kr.VIEWER_KINDS] + [k + "/r" for k in kr.MEMBER_KINDS]}
        self.assertEqual(kr.claims_role(wide_viewer), "viewer")

    def test_identity(self):
        self.assertEqual(kr.claims_identity({"get": "r", "put": ["~state/r/abc-1a2b"]}), ("r", "abc-1a2b"))
        self.assertEqual(kr.claims_identity({"get": "r", "put": [".state/r/abc-1a2b"]}), ("r", None))   # the old '.' spelling is gone
        self.assertEqual(kr.claims_identity({"get": "r", "put": ["~state/other/abc-1a2b"]}), ("r", None))

    def test_admin_claim(self):
        self.assertTrue(kr.claims_admin({"put": ["r/~admin"]}, "r"))
        self.assertFalse(kr.claims_admin({"put": ["r/.admin"]}, "r"))


class Minter(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4999, kr.AuthStore(self.d))

    def test_member_tokens_put_only_tilde_paths(self):
        obj, code = self.svc.token({"room": "lab", "host": "box-1a2b", "roomCode": ""}, peer="127.0.0.1")
        self.assertEqual(code, 200, obj)
        self.assertEqual(obj.get("ns"), "~")
        claims = kr.verify_token(obj["tokens"]["member"], self.svc.key, time.time())
        puts = kr._patterns(claims["put"])
        self.assertTrue(puts, claims)
        for p in puts:
            self.assertNotIn("/.", "/" + p, p)
        self.assertTrue(any(p.startswith("~state/lab/box-1a2b") for p in puts), puts)
        reg = kr.verify_token(obj["tokens"]["registry"], self.svc.key, time.time())
        self.assertEqual(kr._patterns(reg["put"])[0], "~channels/lab")


class RelayConfig(unittest.TestCase):
    def test_stats_prefix_written(self):
        d = tempfile.mkdtemp()
        r = kr.Relay(d, lambda m: None)
        path = r._write_config(4999, False, False)
        with open(path, encoding="utf-8") as f:
            cfg = f.read()
        self.assertIn('prefix = "~stats"', cfg)

    def test_stale_lan_mesh_state_is_ignored(self):
        # 0.21.40: the LAN mesh is gone. A box that had it on (a "lan" block in relay-auth.json, a lan.secret file)
        # must load, write a relay.toml without [cluster.lan], drop the secret file, and save without the block.
        import json
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "relay-auth.json"), "w", encoding="utf-8") as f:
            json.dump({"lan": {"enabled": True, "secret": "ab" * 32, "at": 1}, "rooms": {}}, f)
        with open(os.path.join(d, "lan.secret"), "w", encoding="utf-8") as f:
            f.write("ab" * 32)
        r = kr.Relay(d, lambda m: None)
        path = r._write_config(4999, True, True)
        with open(path, encoding="utf-8") as f:
            cfg = f.read()
        self.assertNotIn("cluster.lan", cfg)
        self.assertFalse(os.path.exists(os.path.join(d, "lan.secret")))
        self.assertNotIn("lan", r.status())
        st = kr.AuthStore(d)
        st.set_codes(viewer="v1")
        with open(os.path.join(d, "relay-auth.json"), encoding="utf-8") as f:
            self.assertNotIn("lan", json.load(f))


class Pages(unittest.TestCase):
    def test_no_dot_spelled_control_kinds(self):
        for name in ("moq-watch-lite.html", "relay.html"):
            s = read(name)
            hits = [m.group(0) for m in DOT_KIND.finditer(s)]
            self.assertEqual(hits, [], (name, hits[:10]))

    def test_token_cache_requires_the_namespace(self):
        s = read("moq-watch-lite.html")
        self.assertIn('saved.ns === "~"', s)
        self.assertIn("ns: authNs", s)

    def test_side_doors_refuse_both_namespaces(self):
        s = read("kastr_serve.py")
        self.assertEqual(s.count('segs[0].startswith((".", kastr_relay.NS))'), 2)
        self.assertIn('b.startswith((".", "~"))', read("kastr_archive.py"))

    def test_stats_bundle_is_retargeted_at_serve_time(self):
        s = read("kastr_serve.py")
        self.assertIn('(b"`.stats/node`"', s)
        bundle = [f for f in os.listdir(os.path.join(HERE, "assets")) if f.startswith("stats-") and f.endswith(".js")]
        self.assertTrue(bundle)
        b = read(os.path.join("assets", bundle[0]))
        self.assertEqual(b.count("`.stats/node`"), 1)
        self.assertEqual(b.count("d=e=>e.startsWith(`.`)"), 1)


if __name__ == "__main__":
    unittest.main()
