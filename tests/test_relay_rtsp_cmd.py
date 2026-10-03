"""0.21.16: the hub's `rtsp` command -- a hub operator turns a spoke's own cameras off or on.

Run: python -m unittest discover -s tests   (build.py's exact invocation, before every build)

The command rides the bans long-poll command list like closeRoom / wake (a LIST: two flips between two polls both
arrive), the spoke registers its switch state ("on" | "off" | None), the hub's /api/relay/spokes rows carry it, the
spoke's Relay._hub_cmd("rtsp") reaches the Bridge through kastr_serve.RTSP_BRIDGE, and POST /api/relay/spokes/rtsp is a
guarded (loopback-only) control. No network, no sockets: AuthService and Relay are built with __new__ and the few
attributes the code paths read.
"""
import io
import json
import os
import sys
import threading
import types
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_relay  # noqa: E402
import kastr_serve  # noqa: E402


def auth_stub():
    a = kastr_relay.AuthService.__new__(kastr_relay.AuthService)
    a.lock = threading.Lock()
    a.cmd = {"seq": 0, "update": None, "closeRoom": [], "rtsp": []}
    a.spokes = {}
    a.lines = []
    a.log = a.lines.append
    a._save_spokes = lambda: None
    a._bearer_relay = lambda bearer: {"role": "relay"} if bearer else None
    a.bans = types.SimpleNamespace(poke=lambda: None, snapshot=lambda: (3, []), wait_change=lambda v, w: None,
                                   active=lambda: [])
    return a


class HubCommand(unittest.TestCase):
    def test_raise_cmd_rtsp_is_a_list(self):
        a = auth_stub()
        r1 = a.raise_cmd("rtsp", {"spoke": "south", "suspend": True})
        r2 = a.raise_cmd("rtsp", {"spoke": "south", "suspend": False})
        self.assertEqual([c["seq"] for c in a.cmd["rtsp"]], [r1["seq"], r2["seq"]])
        self.assertLess(r1["seq"], r2["seq"])
        self.assertEqual([c["suspend"] for c in a.cmd["rtsp"]], [True, False])
        body, code = a.bans_for_spoke("Bearer x")
        self.assertEqual(code, 200)
        self.assertEqual(len(body["cmd"]["rtsp"]), 2)
        self.assertEqual(body["cmd"]["seq"], r2["seq"])
        self.assertEqual(a.bans_for_spoke("")[1], 403)

    def test_register_spoke_carries_the_switch(self):
        a = auth_stub()
        obj, code = a.register_spoke({"name": "South Ridge", "version": "0.21.16", "rtsp": "off"}, "10.0.0.5", "Bearer x")
        self.assertEqual(code, 200)
        self.assertEqual(a.spokes["spoke:south-ridge"]["rtsp"], "off")
        a.register_spoke({"name": "mendon", "version": "0.21.16", "rtsp": "bogus"}, "10.0.0.6", "Bearer x")
        self.assertIsNone(a.spokes["spoke:mendon"]["rtsp"])      # whitelisted values only
        rows = {r["name"]: r for r in a.spokes_public()}
        self.assertEqual(rows["south-ridge"]["rtsp"], "off")
        self.assertIsNone(rows["mendon"]["rtsp"])


class SpokeSide(unittest.TestCase):
    def setUp(self):
        self.saved = kastr_serve.RTSP_BRIDGE[0]
        self.calls = []
        test = self

        class FakeBridge:
            def suspend(self, who):
                test.calls.append(("off", who))
                return {"ok": True, "suspended": True}

            def resume(self, who):
                test.calls.append(("on", who))
                return {"ok": True, "suspended": False}
        kastr_serve.RTSP_BRIDGE[0] = FakeBridge()
        self.r = kastr_relay.Relay.__new__(kastr_relay.Relay)
        self.lines, self.syncs = [], []
        self.r.relay_name = lambda: "south"
        self.r.log = self.lines.append
        self.r.spoke_sync_soon = lambda: self.syncs.append(1)

    def tearDown(self):
        kastr_serve.RTSP_BRIDGE[0] = self.saved

    def test_hub_cmd_rtsp_reaches_the_bridge_by_name(self):
        self.r._hub_cmd("rtsp", {"seq": 7, "spoke": "south", "suspend": True})
        self.assertEqual(self.calls, [("off", "hub command #7")])
        self.assertEqual(self.syncs, [1])                         # re-registers at once
        self.r._hub_cmd("rtsp", {"seq": 8, "spoke": "mendon", "suspend": False})
        self.assertEqual(len(self.calls), 1)                      # another spoke's camera switch
        self.r._hub_cmd("rtsp", {"seq": 9, "spoke": "*", "suspend": False})
        self.assertEqual(self.calls[-1], ("on", "hub command #9"))
        self.assertTrue(any("hub switched this box's RTSP off" in ln for ln in self.lines))

    def test_hub_cmd_rtsp_without_a_bridge_says_so(self):
        kastr_serve.RTSP_BRIDGE[0] = None
        self.r._hub_cmd("rtsp", {"seq": 3, "spoke": "south", "suspend": True})
        self.assertEqual(self.calls, [])
        self.assertTrue(any("no bridge on this box" in ln for ln in self.lines))


class FakeHandler:
    def __init__(self, body):
        raw = json.dumps(body).encode()
        self.command = "POST"
        self.headers = {"Content-Length": str(len(raw)), "Host": "127.0.0.1:8000"}
        self.client_address = ("127.0.0.1", 50000)
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.code = None

    def send_response(self, code):
        self.code = code

    def send_header(self, k, v):
        pass

    def end_headers(self):
        pass

    def body(self):
        return json.loads(self.wfile.getvalue().decode())


class HubRoute(unittest.TestCase):
    def setUp(self):
        self.saved = kastr_relay._local_only

    def tearDown(self):
        kastr_relay._local_only = self.saved

    def test_spokes_rtsp_route(self):
        self.assertIn("/api/relay/spokes/rtsp", kastr_relay.GUARDED_POSTS)
        kastr_relay._local_only = lambda h: True
        a = auth_stub()
        relay = types.SimpleNamespace(auth=a)
        h = FakeHandler({"spoke": "south", "suspend": True})
        self.assertTrue(kastr_relay.handle_api(h, relay, "/api/relay/spokes/rtsp"))
        self.assertEqual(h.code, 200)
        self.assertEqual(h.body()["suspend"], True)
        self.assertEqual(a.cmd["rtsp"][-1]["spoke"], "south")
        h = FakeHandler({"suspend": True})
        kastr_relay.handle_api(h, relay, "/api/relay/spokes/rtsp")
        self.assertEqual(h.code, 400)                             # spoke required
        h = FakeHandler({"spoke": "south", "suspend": True})
        kastr_relay.handle_api(h, types.SimpleNamespace(auth=None), "/api/relay/spokes/rtsp")
        self.assertEqual(h.code, 400)                             # an open relay has no command channel
        kastr_relay._local_only = lambda h: False
        h = FakeHandler({"spoke": "south", "suspend": True})
        kastr_relay.handle_api(h, relay, "/api/relay/spokes/rtsp")
        self.assertEqual(h.code, 403)                             # loopback only
        self.assertEqual(len(a.cmd["rtsp"]), 1)


if __name__ == "__main__":
    unittest.main()
