"""v0.21.68: the Relay page's Pull test shows the moq tool's last line without terminal colour codes.

Run: python -m unittest discover -s tests
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PullTestText(unittest.TestCase):
    def test_colour_codes_stripped(self):
        with open(os.path.join(HERE, "kastr_relay.py"), encoding="utf-8") as f:
            src = f.read()
        i = src.index("# 0.21.68: no terminal colour codes")
        line = src[src.rindex(chr(10), 0, i):i]
        pat = re.search(r're\.sub\(r"(.*?)", ""', line).group(1)
        self.assertNotIn(chr(27), line)
        raw = chr(27) + "[2m2026-10-15T02:34:59Z" + chr(27) + "[0m " + chr(27) + "[32m INFO" + chr(27) + "[0m subscribe started"
        self.assertEqual(re.sub(pat, "", raw), "2026-10-15T02:34:59Z  INFO subscribe started")

class AccentInk(unittest.TestCase):
    """0.21.68 (Kenton: the "You're here" pill unreadable on a yellow accent): text on the accent = black or white by contrast."""
    def test_wired(self):
        rd = lambda f: open(os.path.join(HERE, f), encoding="utf-8").read()
        css, js, p, r = rd("assets/asi-brand.css"), rd("assets/asi-brand.js"), rd("moq-watch-lite.html"), rd("relay.html")
        self.assertIn("--on-accent:     #06121a;", css)
        self.assertIn('st.setProperty("--on-accent", accentInk(c));', js)
        self.assertIn('st.removeProperty("--on-accent");', js)
        self.assertIn('document.documentElement.style.setProperty("--on-accent",', p.split("</script>", 1)[0])
        self.assertIn(".sbcard.cur .sbtag.here { display:inline-block; background:var(--asi-blue); color:var(--on-accent); }", p)
        self.assertIn(".sbcard.cur .rb { border-color:var(--asi-blue); background:var(--asi-blue); color:var(--on-accent);", p)
        for src in (p, r):   # no rule paints fixed white / dark text on the accent any more
            for line in src.splitlines():
                if re.search(r"background:var\(--asi-blue\)(?![-\w])", line):
                    self.assertIsNone(re.search(r"(?<![-\w])color:(#06121a|#fff)\b", line), line.strip()[:120])

    def test_ink_choice(self):
        js = open(os.path.join(HERE, "assets/asi-brand.js"), encoding="utf-8").read()
        self.assertIn('return (L + 0.05) / (Ld + 0.05) >= 1.05 / (L + 0.05) ? "#06121a" : "#ffffff";', js)

        def ink(h):   # the same rule in Python
            ch = lambda i: (lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)(int(h[i:i + 2], 16) / 255)
            L = 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5)
            return "#06121a" if (L + 0.05) / 0.0558 >= 1.05 / (L + 0.05) else "#ffffff"
        self.assertEqual(ink("#e5ff00"), "#06121a")   # Kenton's yellow
        self.assertEqual(ink("#009fda"), "#06121a")   # ASI blue
        self.assertEqual(ink("#1a237e"), "#ffffff")
        self.assertEqual(ink("#c62828"), "#ffffff")

class TokenRetry(unittest.TestCase):
    """0.21.68 (Kenton: "Could not join aoz-6: Failed to fetch" -- joined on a later try): a network failure of the token
    request is tried again twice (1.5 s, 3 s); refusals are not retried."""
    def test_wired(self):
        p = open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8").read()
        body = p[p.index("  async function authMint(room, access, roomCode) {"):p.index("    authTokens = d.tokens;")]
        self.assertIn("for (let attempt = 0; ; attempt++) {", body)
        self.assertIn("if (attempt >= 2) throw new Error(", body)
        self.assertIn("await new Promise((res) => setTimeout(res, 1500 * (attempt + 1)));", body)
        self.assertIn('if (!r.ok || !d.ok) throw new Error(d.error || ("token refused (" + r.status + ")"));', body)   # refusals: no retry

class UsersOldLine(unittest.TestCase):
    def test_hidden_when_none(self):
        r = open(os.path.join(HERE, "relay.html"), encoding="utf-8").read()
        self.assertIn('oldBox.closest("label").style.display = nOld ? "" : "none";', r)
        self.assertNotIn('" (none)"', r)


import json, sys, tempfile, time   # noqa: E402
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402


class UserHistory(unittest.TestCase):
    """0.21.68 (Kenton: "The user section should store any past users persistent through reboots/upgrades. Keeping a full
    history of all devices that have connected in the past 30 days")."""
    def svc(self, d):
        st = kr.AuthStore(d)
        st.set_codes(viewer="view-1", publisher="pub-1")
        return kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)

    def test_survives_a_restart_with_spoke_users_and_offline_rows(self):
        d = tempfile.mkdtemp()
        s = self.svc(d)
        try:
            s.client_checkin({"node": "deskpc-1a2b", "version": "0.21.66", "mode": "full", "platform": "win32", "name": "Kenton Jeffery"}, "10.0.0.9")
            tok = kr._mint(s.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))
            s.register_spoke({"name": "mendon-relay", "version": "0.21.67", "clients": [
                {"node": "yardbox-9f9f", "name": "Yard", "version": "0.21.67", "mode": "publisher-relay", "kind": "box", "checkin": True, "at": int(time.time()), "rooms": ["mendon"]}]},
                "10.0.0.2", "Bearer " + tok)
            rows = {r["node"]: r for r in s.fleet_clients("hub", "0.21.67")}
            self.assertEqual(set(rows), {"deskpc-1a2b", "yardbox-9f9f"})
            self.assertTrue(os.path.isfile(os.path.join(d, "relay-users.json")))
        finally:
            s.close()
        s2 = self.svc(d)   # a restart / upgrade: nobody is connected yet
        try:
            self.assertEqual(set(s2.user_hist), {"deskpc-1a2b", "yardbox-9f9f"})
            rows = {r["node"]: r for r in s2.fleet_clients("hub", "0.21.68")}
            self.assertTrue(rows["deskpc-1a2b"]["offline"])
            self.assertEqual(rows["deskpc-1a2b"]["name"], "Kenton Jeffery")
            self.assertEqual(rows["deskpc-1a2b"]["relay"], "hub")
            self.assertEqual((rows["yardbox-9f9f"]["relay"], rows["yardbox-9f9f"]["kind"]), ("mendon-relay", "box"))
            # the spoke's last registration is still fresh (relay-spokes.json): its box stays a live row
            self.assertFalse(rows["yardbox-9f9f"].get("offline"))
            # back online: a live row again (not offline), first-seen kept
            first = s2.user_hist["deskpc-1a2b"]["first"]
            s2.client_checkin({"node": "deskpc-1a2b", "version": "0.21.68", "mode": "full", "platform": "win32", "name": "Kenton Jeffery"}, "10.0.0.9")
            rows = {r["node"]: r for r in s2.fleet_clients("hub", "0.21.68")}
            self.assertFalse(rows["deskpc-1a2b"].get("offline"))
            self.assertEqual(s2.user_hist["deskpc-1a2b"]["first"], first)
        finally:
            s2.close()

    def test_forgotten_after_30_days(self):
        d = tempfile.mkdtemp()
        old = int(time.time()) - 31 * 86400
        with open(os.path.join(d, "relay-users.json"), "w", encoding="utf-8") as f:
            json.dump({"me": "hub", "users": {"gone-1a2b": {"name": "Gone", "at": old, "first": old},
                                              "recent-1a2b": {"name": "Recent", "at": int(time.time()) - 5 * 86400}}}, f)
        s = self.svc(d)
        try:
            self.assertEqual(set(s.user_hist), {"recent-1a2b"})
        finally:
            s.close()

    def test_page(self):
        r = open(os.path.join(HERE, "relay.html"), encoding="utf-8").read()
        self.assertIn("const behind = (r) => !r.offline && r.kind !== \"web\" && r.checkin", r)
        self.assertIn("'<tr class=\"offl\" title=\"Offline", r)
        self.assertIn('" offline (last 30 days)"', r)


class AdminGroups(unittest.TestCase):
    """0.21.68 (Kenton: "I'm not able to group the rooms because I can't create a group name"): an admin manages room groups
    from any desk (before: only a page on the relay box itself); names are typed in KASTR's own box."""
    def test_server(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        o, c = kr.group_op(st, {"op": "create", "name": "Sites"}, operator=False)
        self.assertEqual(c, 403)
        o, c = kr.group_op(st, {"op": "create", "name": "Sites"}, operator=True)
        self.assertEqual(c, 200, o)
        serve = open(os.path.join(HERE, "kastr_serve.py"), encoding="utf-8").read()
        self.assertIn("obj, code = kastr_relay.group_op(store, p, operator=self._settings_admin(), log=log)", serve)
        self.assertIn('body = {"op": "group", "body": p, "vouch": "admin" if self._settings_admin() else None}', serve)
        relay = open(os.path.join(HERE, "kastr_relay.py"), encoding="utf-8").read()
        self.assertIn('return group_op(self.store, body, operator=p.get("vouch") == "admin", log=self.log)', relay)

    def test_page(self):
        p = open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8").read()
        self.assertIn('const canManageGroups = () => isRelayOperator() || (authSecured && authRole === "admin");', p)
        self.assertIn('if (canManageGroups()) items.push({ value: "__new", label: "New group' + chr(92) + 'u2026" });', p)
        self.assertIn('...(canManageGroups() ? [new Option("New group' + chr(92) + 'u2026", "__new")] : [])', p)
        self.assertIn('headers.authorization = "Bearer " + authTokens.member;   // 0.21.68: an admin', p)
        self.assertNotIn('prompt("Name the new group:"', p)
        self.assertNotIn('prompt("Rename group:"', p)


if __name__ == "__main__":
    unittest.main()
