"""v0.21.69 (Kenton 2026-10-14: "For the machine name in the user section, can we pull the hostname of the device instead?"):
the Users table shows the computer's own hostname (apps report it), the signed-in OS user, the IP in its own column, and a
nickname given on the hub (kept with the 30-day history).

Run: python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402


def svc(d):
    st = kr.AuthStore(d)
    st.set_codes(viewer="view-1", publisher="pub-1")
    return kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)


class Machine(unittest.TestCase):
    def test_hostname_user_and_nickname(self):
        d = tempfile.mkdtemp()
        s = svc(d)
        try:
            s.client_checkin({"node": "desktop-tc5vjib-27a6", "version": "0.21.69", "mode": "full", "platform": "win32",
                              "name": "Support Laptop", "hostname": "DESKTOP-TC5VJIB", "user": "support"}, "10.0.4.20")
            tok = kr._mint(s.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))
            s.register_spoke({"name": "mendon-relay", "version": "0.21.69", "clients": [
                {"node": "mobius-moq-0361", "name": "Mendon Relay", "hostname": "mobius-moq", "user": "kastr<script>", "kind": "box",
                 "mode": "publisher-relay", "checkin": True, "at": int(time.time())}]}, "10.0.0.2", "Bearer " + tok)
            rows = {r["node"]: r for r in s.fleet_clients("hub", "0.21.69")}
            me = rows["desktop-tc5vjib-27a6"]
            self.assertEqual((me["hostname"], me["user"], me["ip"], me["nick"]), ("DESKTOP-TC5VJIB", "support", "10.0.4.20", ""))
            self.assertEqual(rows["mobius-moq-0361"]["user"], "kastrscript")   # no markup characters survive
            o, c = s.set_nick("desktop-tc5vjib-27a6", "Support laptop (truck 3)")
            self.assertEqual(c, 200, o)
            self.assertEqual(s.set_nick("not a node", "x")[1], 400)
            rows = {r["node"]: r for r in s.fleet_clients("hub", "0.21.69")}
            self.assertEqual(rows["desktop-tc5vjib-27a6"]["nick"], "Support laptop (truck 3)")
        finally:
            s.close()
        s2 = svc(d)   # the nickname and the hostname survive a restart (relay-users.json)
        try:
            rows = {r["node"]: r for r in s2.fleet_clients("hub", "0.21.69")}
            r = rows["desktop-tc5vjib-27a6"]
            self.assertTrue(r["offline"])
            self.assertEqual((r["nick"], r["hostname"], r["user"]), ("Support laptop (truck 3)", "DESKTOP-TC5VJIB", "support"))
            s2.set_nick("desktop-tc5vjib-27a6", "")
            self.assertEqual({x["node"]: x for x in s2.fleet_clients("hub", "0.21.69")}["desktop-tc5vjib-27a6"]["nick"], "")
        finally:
            s2.close()

    def test_app_reports_it(self):
        k = open(os.path.join(HERE, "kastr.py"), encoding="utf-8").read()
        self.assertIn('"hostname": _checkin_hostname(), "user": _checkin_user(),', k)   # 0.21.73: + started
        self.assertIn("return socket.gethostname()[:64]", k)
        self.assertIn("return getpass.getuser()[:32]", k)

    def test_page(self):
        r = open(os.path.join(HERE, "relay.html"), encoding="utf-8").read()
        self.assertIn('{ key: "ip", label: "IP", val: (r) => r.ip || "" },', r)
        self.assertIn('const machineText = (r) => r.nick || (r.kind === "web" && r.platform ? r.platform : (r.hostname || r.node || ""));', r)
        self.assertIn('"</td>" + machineCell(r) + \'<td class="mono">\' + esc(r.ip || ', r)
        self.assertIn('api("/api/relay/users/nick", { node: b.dataset.node, nick: v.trim() })', r)
        relay = open(os.path.join(HERE, "kastr_relay.py"), encoding="utf-8").read()
        self.assertIn('"/api/relay/users/nick",      # 0.21.69', relay)   # guarded: the Relay page on this machine only

    def test_line_endings_kept(self):
        for f in ("kastr_relay.py", "tests/test_release_0_21_68.py"):
            with open(os.path.join(HERE, f), "rb") as fh:
                self.assertNotIn(b"\r\n", fh.read(), f)


if __name__ == "__main__":
    unittest.main()
