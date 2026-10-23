# -*- coding: utf-8 -*-
"""0.21.83: the "relay-role cluster sessions timing out every ~10 s (spoke -> hub)" seen in the 0.21.80 grid lab.
Lab v02183/E (two real KASTRs in WSL namespaces, moq-relay 0.17.0, moq 0.14.0): those sessions were never the hub link --
the hub link stayed one connection for the whole run. They were KASTR's own ~stats reads (_mesh_cross_tick, 0.21.78: every
tick, five tracks on a spoke): `moq fetch` reads one group in ~0.1 s and exits without a QUIC CONNECTION_CLOSE, so the relay
held each session to its 10 s idle timeout ("timed out" / "closed") and the 0.21.15 probe filter (< 5 s) let them into the
log as `relay session: end ... role=relay 10 s`. Fix: the fetch advertises a 2 s idle timeout (QUIC takes the smaller side's),
and its token is marked `probe` so its end is counted, never logged, whatever its length."""
import os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402


def _dur(v):
    return float(v[:-2]) / 1000.0 if v.endswith("ms") else float(v[:-1])


class FetchArgs(unittest.TestCase):
    def test_short_idle_timeout_before_the_subcommand(self):
        a = kr.mesh_fetch_args("moq", "http://127.0.0.1:4443/?jwt=x", "~stats/node/n", "publisher.json")
        self.assertEqual(a[0], "moq")
        self.assertEqual(a[-2:], ["fetch", "publisher.json"])
        i, k = a.index("--quic-idle-timeout"), a.index("--quic-keep-alive")
        f = a.index("fetch")
        self.assertTrue(i < f and k < f)                                  # root options go before the subcommand
        idle, keep = _dur(a[i + 1]), _dur(a[k + 1])
        self.assertLessEqual(idle, 4.0)                                   # under the 0.21.15 probe filter's 5 s
        self.assertLess(keep, idle)                                       # a slow fetch is kept alive, never idled out
        self.assertEqual(a[a.index("--broadcast") + 1], "~stats/node/n")


class ProbeToken(unittest.TestCase):
    def test_probe_claims_are_the_relay_shape(self):
        c = dict(kr.STATS_PROBE_CLAIMS, exp=time.time() + 60)
        self.assertTrue(kr.is_relay_claims(c))
        self.assertTrue(kr.is_probe_claims(c))
        self.assertEqual(kr.claims_role(c), "relay")
        g = kr.claims_to_grant(c)
        self.assertEqual((g["publish"], g["subscribe"]), (["**"], ["**"]))
        self.assertNotIn("tier", g)                                       # not a hub link (no node), not a mesh link
        self.assertFalse(kr.is_probe_claims(dict(kr.FEDERATION_CLAIMS, exp=time.time() + 60)))   # a spoke's hub link is not
        self.assertFalse(kr.is_probe_claims({"root": "x", "probe": "stats"}))


class SessionEnds(unittest.TestCase):
    def setUp(self):
        self.key = os.urandom(32)
        self.lines = []
        self.svc = kr.AuthService("127.0.0.1", 0, self.key, 4443, kr.AuthStore(tempfile.mkdtemp()), log=self.lines.append)

    def tearDown(self):
        self.svc.close()

    def _session(self, sid, claims, remote, dur):
        now = int(time.time())
        tok = kr._mint(self.key, dict(claims, iat=now, exp=now + 120))
        g, code = self.svc.session({"event": "connect", "id": sid, "remote": remote, "query": "jwt=" + tok}, "127.0.0.1")
        self.assertEqual(code, 200)
        self.svc.session({"event": "end", "id": sid, "remote": remote, "duration": dur, "bytes": {"sent": 7000, "received": 3700},
                          "reason": "transport: connection error: timed out"}, "127.0.0.1")

    def test_a_stats_read_is_counted_not_logged_however_long(self):
        self._session("p1", kr.STATS_PROBE_CLAIMS, "127.0.0.1:50001", 10.01)   # the field shape: held to the idle timeout
        self._session("p2", kr.STATS_PROBE_CLAIMS, "127.0.0.1:50002", 2.0)     # the 0.21.83 shape
        self.assertFalse([l for l in self.lines if "relay session: end" in l])
        self.assertEqual(self.svc.probe_ends, 2)

    def test_other_relay_sessions_still_logged(self):
        self._session("h1", kr.FEDERATION_CLAIMS, "127.0.0.1:50003", 10.0)    # unmarked loopback relay session past 5 s
        self._session("h2", kr.STATS_PROBE_CLAIMS, "10.0.0.9:50004", 10.0)    # a probe-marked token from elsewhere: logged
        ends = [l for l in self.lines if "relay session: end" in l]
        self.assertEqual(len(ends), 2)
        self.assertTrue(all("role=relay" in l for l in ends))
        self.assertEqual(self.svc.probe_ends, 0)

    def test_short_unmarked_loopback_probe_still_counted(self):
        self._session("r1", kr.FEDERATION_CLAIMS, "127.0.0.1:50005", 1.5)     # the Relay page's probe (0.21.15)
        self.assertEqual(self.svc.probe_ends, 1)
        self.assertFalse([l for l in self.lines if "relay session: end" in l])


class CrossTickUsesThem(unittest.TestCase):
    def test_every_fetch_is_short_and_marked(self):
        d = tempfile.mkdtemp()
        r = kr.Relay(d, lambda m: None)
        key = os.urandom(32)
        svc = kr.AuthService("127.0.0.1", 0, key, 4443, kr.AuthStore(tempfile.mkdtemp()))
        try:
            r.auth, r.port, r.secured, r._stats_node, r._hub_dial = svc, 4443, True, "box-1a2b", "http://10.0.0.1:4443/"
            calls = []

            def run(args, **kw):
                calls.append(args)
                return mock.Mock(stdout=b"{}", returncode=0)
            with mock.patch.object(kr.subprocess, "run", side_effect=run), \
                    mock.patch.object(kr.kastr_rtsp, "find_moq", return_value="moq"):
                r._mesh_cross_tick()
            self.assertEqual(len(calls), len(kr.MESH_LOAD_TRACKS) + len(kr.MESH_DIAL_TRACKS))   # a spoke: five tracks
            for a in calls:
                self.assertIn("--quic-idle-timeout", a)
                url = a[a.index("--connect") + 1]
                c = kr.verify_token(url.split("jwt=", 1)[1], key)
                self.assertTrue(kr.is_probe_claims(c))
                self.assertLessEqual(c["exp"] - c["iat"], 300)
        finally:
            svc.close()


class Tree(unittest.TestCase):
    def test_line_endings(self):
        with open(os.path.join(HERE, "kastr_relay.py"), "rb") as f:
            b = f.read()
        self.assertEqual(b.count(b"\r\n"), 0)

    def test_relay_toml_quic_block_unchanged(self):
        # 0.21.83 changes no relay.toml key: the hub link keeps moq-relay's defaults (keep_alive 3 s < idle_timeout 10 s),
        # which held it up for the whole lab -- only the fetch (a client option) shortens its own sessions
        with open(os.path.join(HERE, "kastr_relay.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('"stream_receive_window = 262144"', src)
        self.assertNotIn('"idle_timeout', src)


if __name__ == "__main__":
    unittest.main()
