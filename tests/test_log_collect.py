# -*- coding: utf-8 -*-
"""0.21.51: logs collected at the hub on request (Kenton: "Could we have the logs all send to the hub to make log
collection easier?" -- on demand; relays + apps + publisher boxes; the last hour or a search). Loopback only."""
import os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402


def svc():
    st = kr.AuthStore(tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1")
    return kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)


def fed(s):
    return "Bearer " + kr._mint(s.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))


class Helpers(unittest.TestCase):
    def test_redaction(self):
        t = kr.redact_log('a jwt=abc.def b "code": "x1" c Bearer zz.yy "token":"t"')
        for secret in ("abc.def", "x1", "zz.yy", '"t"'):
            self.assertNotIn(secret, t)

    def test_last_hour_and_search(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "relay.log")
        old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 7200))
        new = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(p, "w", encoding="utf-8") as f:
            f.write(old + " old mikey/camera\n  old continued\n" + new + " new line\n  new continued\n")
        self.assertEqual(kr.log_slice([p], time.time() - 3600), new + " new line\n  new continued\n")
        self.assertEqual(kr.log_slice([p], 0, "mikey/camera"), old + " old mikey/camera\n")

    def test_cap_keeps_the_newest(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "relay.log")
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(p, "w", encoding="utf-8") as f:
            for i in range(100):
                f.write("%s line %03d\n" % (now, i))
        out = kr.log_slice([p], 0, "", cap=200)
        self.assertIn("line 099", out)
        self.assertNotIn("line 000", out)


class Flow(unittest.TestCase):
    def setUp(self):
        self.s = svc()

    def tearDown(self):
        self.s.close()

    def test_apps_are_told_once_and_their_logs_pass_on(self):
        got = []
        self.s.on_client_logs = got.append
        self.s.client_checkin({"node": "testpc-1a2b", "version": "0.21.51"}, "10.0.0.9")
        self.s.log_ask("20261012-120000-abcd", "", 123)
        o, _ = self.s.client_checkin({"node": "testpc-1a2b", "version": "0.21.51"}, "10.0.0.9")
        self.assertEqual(o["logs"]["id"], "20261012-120000-abcd")
        o, _ = self.s.client_checkin({"node": "testpc-1a2b", "version": "0.21.51"}, "10.0.0.9")
        self.assertNotIn("logs", o)   # told once
        o, c = self.s.client_logs({"id": "20261012-120000-abcd", "node": "testpc-1a2b", "files": {"launch.log": "x jwt=SECRET y"}}, "10.0.0.9")
        self.assertEqual(c, 200, o)
        time.sleep(0.3)
        self.assertEqual(got[0]["node"], "testpc-1a2b")
        self.assertNotIn("SECRET", got[0]["files"]["launch.log"])

    def test_logs_nobody_asked_for_are_refused(self):
        o, c = self.s.client_logs({"id": "20261012-120000-abcd", "node": "testpc-1a2b", "files": {}}, "10.0.0.9")
        self.assertEqual(c, 403)

    def test_hub_stores_a_spokes_upload(self):
        run = self.s.logs_start("mikey")
        o, c = self.s.logs_upload({"id": run["id"], "relay": "mendon-relay", "node": "mendon-box-0361", "kind": "relay", "name": "mendon-relay",
                                   "files": {"relay.log": "mikey/camera jwt=SECRET\n"}}, fed(self.s))
        self.assertEqual(c, 200, o)
        self.assertEqual([(e["relay"], e["kind"]) for e in self.s.log_runs[run["id"]]["entries"]], [("mendon-relay", "relay")])
        d = os.path.join(self.s.store.state_dir, "logs", run["id"])
        f = os.listdir(d)[0]
        self.assertNotIn("SECRET", open(os.path.join(d, f), encoding="utf-8").read())

    def test_upload_needs_the_federation_token(self):
        run = self.s.logs_start("")
        o, c = self.s.logs_upload({"id": run["id"], "files": {}}, "Bearer nope")
        self.assertEqual(c, 403)

    def test_collect_rides_the_command_channel(self):
        rec = self.s.raise_cmd("logs", {"id": "x", "find": "", "since": 1})
        d, c = self.s.bans_for_spoke(fed(self.s), peer="10.0.0.2")
        self.assertEqual([x["seq"] for x in d["cmd"]["logs"]], [rec["seq"]])


class Sources(unittest.TestCase):
    def test_app_sends_its_logs_to_its_relay(self):
        k = open(os.path.join(HERE, "kastr.py"), encoding="utf-8").read()
        self.assertIn('req = urllib.request.Request(base + "/api/clients/logs"', k)
        self.assertIn("threading.Thread(target=send_logs, args=(ask, base, node, mode, inst, port), daemon=True).start()", k)

    def test_web_port_forwards(self):
        self.assertIn('"/api/clients/logs", "/api/logs/upload",             # 0.21.51', open(os.path.join(HERE, "kastr_serve.py"), encoding="utf-8").read())

    def test_relay_page_panel(self):
        r = open(os.path.join(HERE, "relay.html"), encoding="utf-8").read()
        self.assertIn('<div id="logsBox"', r)
        self.assertIn('api("/api/relay/logs/collect", { find })', r)
        self.assertIn('/api/relay/logs/bundle?id=', r)


if __name__ == "__main__":
    unittest.main()
