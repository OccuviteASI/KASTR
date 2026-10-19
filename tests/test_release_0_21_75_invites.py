# -*- coding: utf-8 -*-
"""v0.21.75 room invite links (Kenton: "ANYONE in the room can copy an invite link; it works 24 h by default (1 h / 24 h /
7 days); the room's creator or an admin can revoke links; the link opens the installed KASTR app if present, otherwise the
host's web page; the person joining needs NO access code and NO room code" -- a publisher, never an admin).

The hub makes `ki-<id>-<secret>` and keeps only sha256(secret) (relay-auth.json, export/merge bundles); /api/token
{room, invite, host} redeems it (a spoke asks the hub, caches a good answer 30 s, fails CLOSED when the hub is dark); a
wrong link counts in the lockout; revoked ids ride the bans long-poll to the spokes. kastr.py registers kastr:// and takes
--invite / a bare kastr:// argument out of argv; kastr_serve holds the hand-off once for 2 minutes."""
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1", "admin": "adm-1"}
BS = chr(92)


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def store(codes=CODES):
    st = kr.AuthStore(tempfile.mkdtemp())
    if codes:
        st.set_codes(**codes)
    return st


def member(svc, room, code="view-1", host="kenton-ab12", peer="10.0.0.1"):
    o, c = svc.token({"room": room, "code": code, "host": host}, peer)
    assert c == 200, o
    return "Bearer " + o["tokens"]["member"]


class Store(unittest.TestCase):
    def setUp(self):
        self.st = store()

    def test_shape_and_digest_only_storage(self):
        row, tok, code = self.st.invite_create("yard", 86400, "Kenton")
        self.assertEqual(code, 200)
        m = kr.INVITE_RE.match(tok)
        self.assertIsNotNone(m, tok)
        self.assertEqual(m.group(1), row["id"])
        self.assertEqual(len(m.group(2)), 32)                      # 192 bits, base64url
        self.assertEqual(row["exp"] - row["created"], 86400)
        with open(os.path.join(self.st.state_dir, "relay-auth.json"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn(m.group(2), text)
        rec = json.loads(text)["invites"][row["id"]]
        self.assertEqual(rec["digest"], hashlib.sha256(m.group(2).encode()).hexdigest())
        for r in self.st.invites_public("yard"):
            self.assertFalse({"digest", "hosts", "token"} & set(r))

    def test_ttls_lobby_and_names(self):
        self.assertEqual(kr.invite_ttl(None), 86400)
        for t in (3600, 86400, 604800):
            self.assertEqual(self.st.invite_create("yard", t)[2], 200)
        self.assertEqual(self.st.invite_create("yard", 7200)[2], 400)
        self.assertEqual(self.st.invite_create("yard", "x")[2], 400)
        self.assertEqual(self.st.invite_create("main", 3600)[2], 403)
        self.assertEqual(self.st.invite_create("Bad Room", 3600)[2], 400)

    def test_check_expire_revoke(self):
        row, tok, _ = self.st.invite_create("yard", 3600)
        self.assertEqual(self.st.invite_check(tok)[0], "ok")
        self.assertEqual(self.st.invite_check(tok[:-1] + ("A" if tok[-1] != "A" else "B"))[0], "wrong")
        self.assertEqual(self.st.invite_check("ki-zz")[0], "wrong")
        self.assertEqual(self.st.invite_check("")[0], "wrong")
        with self.st.lock:
            self.st.invites[row["id"]]["exp"] = int(time.time()) - 1
        self.assertEqual(self.st.invite_check(tok)[0], "expired")
        self.assertEqual(self.st.invites_public("yard"), [])
        row2, tok2, _ = self.st.invite_create("yard", 3600)
        self.assertEqual(self.st.invite_revoke("yard", row2["id"]), (1, True))
        self.assertEqual(self.st.invite_check(tok2)[0], "revoked")
        self.assertIn(row2["id"], self.st.invites_revoked_ids())
        self.assertEqual(self.st.invite_revoke("yard", "deadbeef"), (0, False))

    def test_uses_count_distinct_members(self):
        row, tok, _ = self.st.invite_create("yard", 3600)
        for h in ("guest-aa11", "guest-aa11", "other-bb22"):
            self.st.invite_check(tok, use=True, host=h)
        self.assertEqual(self.st.invites_public("yard")[0]["uses"], 2)

    def test_cap_per_room(self):
        for _ in range(kr.INVITES_PER_ROOM):
            self.assertEqual(self.st.invite_create("yard", 3600)[2], 200)
        row, why, code = self.st.invite_create("yard", 3600)
        self.assertEqual((row, code), (None, 409))
        self.assertIn("revoke", why)
        self.assertEqual(self.st.invite_create("dock", 3600)[2], 200)   # per room
        self.st.invite_revoke("yard", None)
        self.assertEqual(self.st.invite_create("yard", 3600)[2], 200)

    def test_restart_and_hand_over(self):
        row, tok, _ = self.st.invite_create("yard", 3600)
        self.assertEqual(kr.AuthStore(self.st.state_dir).invite_check(tok)[0], "ok")
        other = store(None)
        other.import_bundle(self.st.export_bundle())
        self.assertEqual(other.invite_check(tok)[0], "ok")
        self.st.invite_revoke("yard", row["id"])
        other.merge_bundle(self.st.export_bundle())
        self.assertEqual(other.invite_check(tok)[0], "revoked")

    def test_rename_moves_and_close_revokes(self):
        self.st.touch_room("yard", "kenton")
        _, tok, _ = self.st.invite_create("yard", 3600)
        self.assertEqual(self.st.rename_room("yard", "yard-2"), (None, 200))
        self.assertEqual(self.st.invite_check(tok)[1]["room"], "yard-2")
        self.st.close_room("yard-2")
        self.assertEqual(self.st.invite_check(tok)[0], "revoked")


class OnTheHub(unittest.TestCase):
    def setUp(self):
        self.key = os.urandom(32)
        self.svc = kr.AuthService("127.0.0.1", 0, self.key, 4443, store())
        self.svc.store.touch_room("yard", "kenton")

    def tearDown(self):
        self.svc.close()

    def make(self, ttl=86400, who="view-1"):
        o, c = self.svc.invite_create_api({"room": "yard", "ttl": ttl, "by": "Kenton"}, member(self.svc, "yard", who), "10.0.0.1")
        self.assertEqual(c, 200, o)
        return o

    def test_any_member_makes_a_link(self):
        o = self.make()                                  # a VIEWER code's member -- "anyone in the room"
        self.assertTrue(kr.INVITE_RE.match(o["token"]))
        self.assertEqual(o["room"], "yard")
        self.assertEqual(self.svc.store.invites_public("yard")[0]["by"], "Kenton")

    def test_create_refusals(self):
        tok = member(self.svc, "yard")
        self.assertEqual(self.svc.invite_create_api({"room": "yard"}, None, "10.0.0.1")[1], 403)            # no member token
        self.assertEqual(self.svc.invite_create_api({"room": "dock"}, tok, "10.0.0.1")[1], 403)             # another room's token
        self.assertEqual(self.svc.invite_create_api({"room": "yard", "ttl": 60}, tok, "10.0.0.1")[1], 400)  # 1 h / 24 h / 7 days only
        lobby = member(self.svc, "main")
        self.assertEqual(self.svc.invite_create_api({"room": "main"}, lobby, "10.0.0.1")[1], 403)
        fed = "Bearer " + kr._mint(self.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 60))
        self.assertEqual(self.svc.invite_create_api({"room": "yard"}, fed, "10.0.0.1")[1], 403)            # not a member token
        self.svc.bans.add({"room": "yard", "host": "kenton-ab12", "target": "yard/kenton-ab12", "by": "admin",
                           "at": time.time(), "until": time.time() + 600})
        self.assertEqual(self.svc.invite_create_api({"room": "yard"}, tok, "10.0.0.1")[1], 403)             # removed by an admin

    def test_redeem_needs_no_codes(self):
        o = self.make()
        r, c = self.svc.token({"room": "yard", "invite": o["token"], "host": "guest-cd34"}, "10.0.0.9")
        self.assertEqual(c, 200, r)
        self.assertEqual(r["role"], "publisher")                         # never an admin
        self.assertEqual(r["invite"]["id"], o["id"])
        cl = kr.verify_token(r["tokens"]["member"], self.key)
        self.assertEqual(cl["inv"], o["id"])
        self.assertEqual(cl["get"], "yard")
        self.assertIn("yard/guest-cd34", cl["put"])
        self.assertNotIn("yard/" + kr.ADMIN_KIND, cl["put"])
        self.assertEqual(self.svc.store.invites_public("yard")[0]["uses"], 1)

    def test_redeem_into_a_locked_room(self):
        salt = "00112233aabbccdd"
        h = hashlib.sha256((salt + "gate").encode()).hexdigest()
        kr.register_room(self.svc.store, {"slug": "secret", "salt": salt, "hash": h, "access": "pub-1"}, "10.0.0.1")
        o, c = self.svc.token({"room": "secret", "code": "pub-1", "roomCode": "gate", "host": "kenton-ab12"}, "10.0.0.1")
        self.assertEqual(c, 200, o)
        inv, c = self.svc.invite_create_api({"room": "secret"}, "Bearer " + o["tokens"]["member"], "10.0.0.1")
        self.assertEqual(c, 200, inv)
        r, c = self.svc.token({"room": "secret", "invite": inv["token"], "host": "guest-cd34"}, "10.0.0.8")
        self.assertEqual(c, 200, r)                                      # no access code, no room code

    def test_wrong_links_count_toward_the_lockout(self):
        o = self.make()
        bad = o["token"][:-4] + "AAAA"
        codes = [self.svc.token({"room": "yard", "invite": bad, "host": "guest-cd34"}, "10.9.9.9")[1] for _ in range(5)]
        self.assertEqual(codes[:4], [403] * 4)
        self.assertEqual(codes[4], 429)
        r, c = self.svc.token({"room": "yard", "invite": o["token"], "host": "guest-cd34"}, "10.9.9.9")
        self.assertEqual(c, 429, r)                                       # locked out, even with the good link

    def test_other_room_expired_revoked_not_counted(self):
        o = self.make(ttl=3600)
        r, c = self.svc.token({"room": "dock", "invite": o["token"], "host": "guest-cd34"}, "10.7.7.7")
        self.assertEqual((c, r.get("invite")), (403, "room"), r)
        self.svc.store.invite_revoke("yard", o["id"])
        for _ in range(6):
            r, c = self.svc.token({"room": "yard", "invite": o["token"], "host": "guest-cd34"}, "10.7.7.7")
            self.assertEqual((c, r.get("invite")), (403, "revoked"), r)
        o2 = self.make(ttl=3600)
        with self.svc.store.lock:
            self.svc.store.invites[o2["id"]]["exp"] = int(time.time()) - 5
        r, c = self.svc.token({"room": "yard", "invite": o2["token"], "host": "guest-cd34"}, "10.7.7.7")
        self.assertEqual((c, r.get("invite")), (403, "expired"), r)
        self.assertNotIn("10.7.7.7", self.svc.lockout._fails)

    def test_bans_still_apply(self):
        o = self.make()
        self.svc.bans.add({"room": "yard", "host": "guest-cd34", "target": "yard/guest-cd34", "by": "kenton",
                           "at": time.time(), "until": time.time() + 600})
        r, c = self.svc.token({"room": "yard", "invite": o["token"], "host": "guest-cd34"}, "10.0.0.9")
        self.assertEqual(c, 403, r)
        self.assertIn("removed", r["error"])

    def test_manage_creator_admin_others(self):
        o = self.make()
        rk = self.svc.store.room("yard")["roomKey"]
        viewer = member(self.svc, "yard", host="viewer-ee55")
        self.assertEqual(self.svc.invite_manage_api("list", {"room": "yard"}, viewer, "10.0.0.2")[1], 403)
        self.assertEqual(self.svc.invite_manage_api("list", {"room": "yard", "roomKey": "nope"}, viewer, "10.0.0.2")[1], 403)
        d, c = self.svc.invite_manage_api("list", {"room": "yard", "roomKey": rk}, None, "10.0.0.2")   # the creator
        self.assertEqual(c, 200, d)
        self.assertEqual([r["id"] for r in d["invites"]], [o["id"]])
        self.assertNotIn(o["token"], json.dumps(d))
        admin = member(self.svc, "dock", code="adm-1", host="boss-ff66")   # an admin token for ANY room
        d, c = self.svc.invite_manage_api("revoke", {"room": "yard", "id": o["id"]}, admin, "10.0.0.3")
        self.assertEqual((c, d["revoked"]), (200, 1), d)
        self.assertEqual(self.svc.invite_manage_api("revoke", {"room": "yard", "id": "0badf00d"}, admin, "10.0.0.3")[1], 404)
        self.make(); self.make()
        d, c = self.svc.invite_manage_api("revoke", {"room": "yard", "all": True}, None, "127.0.0.1")   # the relay operator
        self.assertEqual((c, d["revoked"], d["invites"]), (200, 2, []), d)

    def test_over_http(self):
        port = self.svc.httpd.server_address[1]
        tok = member(self.svc, "yard")

        def call(path, body=None, auth=None):
            req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method="POST" if body is not None else "GET",
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers=dict({"Content-Type": "application/json"}, **({"Authorization": auth} if auth else {})))
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return json.loads(r.read()), r.status
            except urllib.error.HTTPError as e:
                return json.loads(e.read() or b"{}"), e.code
        d, c = call("/api/invite", {"room": "yard", "ttl": 604800}, tok)
        self.assertEqual(c, 200, d)
        r, c = call("/api/token", {"room": "yard", "invite": d["token"], "host": "guest-cd34"})
        self.assertEqual((c, r["role"]), (200, "publisher"), r)
        lst, c = call("/api/invites?room=yard", None, tok)
        self.assertEqual(c, 200, lst)                   # the test peer is loopback: the relay operator
        rv, c = call("/api/invite/revoke", {"room": "yard", "all": True}, tok)
        self.assertEqual((c, rv["revoked"]), (200, 1), rv)


class OnASpoke(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke_key = os.urandom(32)
        self.spoke = kr.AuthService("127.0.0.1", 0, self.spoke_key, 4453, store(), hub=lambda: base, fed_token=lambda: self.fed)
        self.hub.store.touch_room("north", "kenton")

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def make_on_spoke(self):
        o, c = self.spoke.invite_create_api({"room": "north", "ttl": 3600, "by": "Kenton"}, member(self.spoke, "north"), "10.2.2.2")
        self.assertEqual(c, 200, o)
        return o

    def test_made_at_the_hub_redeemed_on_the_spoke(self):
        o = self.make_on_spoke()
        self.assertEqual(self.spoke.store.invites, {})                    # the hub keeps the links
        self.assertEqual(self.hub.store.invites_public("north")[0]["id"], o["id"])
        r, c = self.spoke.token({"room": "north", "invite": o["token"], "host": "guest-cd34"}, "10.3.3.3")
        self.assertEqual(c, 200, r)
        cl = kr.verify_token(r["tokens"]["member"], self.spoke_key)       # a token for the relay the guest uses
        self.assertEqual((cl["get"], cl["inv"]), ("north", o["id"]))
        self.assertEqual(self.hub.store.invites_public("north")[0]["uses"], 1)

    def test_a_good_answer_is_cached_30_s(self):
        o = self.make_on_spoke()
        calls = []
        real = self.spoke._hub_fed

        def spy(body, timeout=6):
            calls.append(body.get("op"))
            return real(body, timeout)
        with mock.patch.object(self.spoke, "_hub_fed", side_effect=spy):
            for _ in range(3):
                self.assertEqual(self.spoke.token({"room": "north", "invite": o["token"], "host": "guest-cd34"}, "10.3.3.3")[1], 200)
        self.assertEqual(calls.count("inviteCheck"), 1)
        self.assertNotIn(o["token"], json.dumps({k: list(v) for k, v in self.spoke._inv_cache.items()}))

    def test_dead_hub_fails_closed(self):
        o = self.make_on_spoke()
        with mock.patch.object(self.spoke, "_hub_fed", return_value=None):
            r, c = self.spoke.token({"room": "north", "invite": o["token"], "host": "guest-cd34"}, "10.5.5.5")
            self.assertEqual(c, 503, r)
            self.assertTrue(r.get("hubDown"))
            r, c = self.spoke.invite_create_api({"room": "north"}, member(self.spoke, "north", host="x-0001"), "10.5.5.5")
            self.assertEqual(c, 503, r)
        self.assertNotIn("10.5.5.5", self.spoke.lockout._fails)

    def test_wrong_link_counted_on_the_spoke(self):
        o = self.make_on_spoke()
        r, c = self.spoke.token({"room": "north", "invite": o["token"][:-4] + "BBBB", "host": "guest-cd34"}, "10.6.6.6")
        self.assertEqual(c, 403, r)
        self.assertEqual(self.spoke.lockout._fails["10.6.6.6"]["n"], 1)   # counted where the guest is

    def test_revocation_reaches_the_spoke(self):
        o = self.make_on_spoke()
        self.assertEqual(self.spoke.token({"room": "north", "invite": o["token"], "host": "guest-cd34"}, "10.3.3.3")[1], 200)
        self.assertTrue(self.spoke._inv_cache)
        rk = self.hub.store.room("north")["roomKey"]
        d, c = self.spoke.invite_manage_api("revoke", {"room": "north", "id": o["id"], "roomKey": rk}, None, "10.2.2.2")
        self.assertEqual((c, d.get("revoked")), (200, 1), d)
        d, c = self.hub.bans_for_spoke("Bearer " + self.fed)
        self.assertIn(o["id"], d["invRevoked"])
        self.assertEqual(self.spoke.invite_revoked_apply(d), 1)
        self.assertEqual(self.spoke._inv_cache, {})
        r, c = self.spoke.token({"room": "north", "invite": o["token"], "host": "guest-cd34"}, "10.3.3.3")
        self.assertEqual((c, r.get("invite")), (403, "revoked"), r)

    def test_spoke_manage_vouches_for_its_admins_only(self):
        o = self.make_on_spoke()
        viewer = member(self.spoke, "north", host="viewer-ee55")
        self.assertEqual(self.spoke.invite_manage_api("list", {"room": "north"}, viewer, "10.2.2.9")[1], 403)
        admin = member(self.spoke, "north", code="adm-1", host="boss-ff66")
        d, c = self.spoke.invite_manage_api("list", {"room": "north"}, admin, "10.2.2.9")
        self.assertEqual(c, 200, d)
        self.assertEqual([r["id"] for r in d["invites"]], [o["id"]])

    def test_rooms_fed_ops(self):
        self.assertEqual(self.hub.rooms_fed({"op": "inviteCheck", "token": "x"}, None)[1], 403)             # federation token
        bearer = "Bearer " + self.fed
        self.assertEqual(self.hub.rooms_fed({"op": "invite", "room": "north"}, bearer)[1], 403)            # vouch member
        d, c = self.hub.rooms_fed({"op": "invite", "vouch": "member", "room": "north", "ttl": 3600, "by": "x"}, bearer)
        self.assertEqual(c, 200, d)
        d2, c = self.hub.rooms_fed({"op": "inviteCheck", "token": d["token"], "room": "north", "host": "g-0001"}, bearer)
        self.assertEqual((c, d2["invite"]["id"]), (200, d["id"]))
        d3, c = self.hub.rooms_fed({"op": "inviteCheck", "token": d["token"][:-2] + "zz"}, bearer)
        self.assertEqual((c, d3["verdict"]), (403, "wrong"))
        self.assertEqual(self.hub.rooms_fed({"op": "inviteList", "room": "north"}, bearer)[1], 403)        # no roomKey, no admin
        self.assertEqual(self.hub.rooms_fed({"op": "inviteList", "room": "north", "vouch": "admin"}, bearer)[1], 200)
        self.assertEqual(self.hub.rooms_fed({"op": "inviteRevoke", "room": "main", "vouch": "admin", "all": True}, bearer)[1], 400)


class AppHandOff(unittest.TestCase):
    URL = "kastr://join?i=ki-0123abcd-" + "A" * 32 + "&room=yard&relay=http%3A%2F%2F10.0.0.5%3A4443"

    def test_argv(self):
        import kastr
        inv, rest = kastr.split_invite_argv(["--relay", "http://x:4443", self.URL, "--port", "8001"])
        self.assertEqual((inv, rest), (self.URL, ["--relay", "http://x:4443", "--port", "8001"]))
        self.assertEqual(kastr.split_invite_argv(["--invite", self.URL, "--no-update"]), (self.URL, ["--no-update"]))
        self.assertEqual(kastr.split_invite_argv(["--invite=" + self.URL]), (self.URL, []))
        self.assertEqual(kastr.split_invite_argv(["KASTR://join?i=1"])[0], "KASTR://join?i=1")
        self.assertEqual(kastr.split_invite_argv(["--mode", "viewer"]), (None, ["--mode", "viewer"]))
        args = kastr.build_parser({}).parse_args(["--invite", self.URL])
        self.assertEqual(args.invite, self.URL)

    def test_scheme_registration(self):
        import kastr
        src = _read("kastr.py")
        self.assertIn('cmd = \'"%s" --invite "%%1"\' % exe', src)
        self.assertIn('winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")', src)
        self.assertIn("register_url_protocol()                       # 0.21.75", src)
        self.assertIn("sys.argv[1:] = _rest", src)                     # an update relaunch never replays the invite
        self.assertIn('hand_invite_to(squatter["url"], args.invite)', src)
        with mock.patch.object(kastr, "FROZEN", False):
            self.assertFalse(kastr.register_url_protocol())             # a source checkout never registers

    def test_parse_and_pending_once(self):
        import kastr_serve as ks
        inv = ks.invite_parse(self.URL)
        self.assertEqual(inv, {"token": "ki-0123abcd-" + "A" * 32, "room": "yard", "relay": "http://10.0.0.5:4443"})
        self.assertEqual(ks.invite_parse("https://host:8443/join#i=ki-0123abcd-" + "A" * 32 + "&room=yard")["relay"], "")
        self.assertIsNone(ks.invite_parse("kastr://join?i=nope&room=yard"))
        self.assertIsNone(ks.invite_parse("kastr://join?i=ki-0123abcd-" + "A" * 32 + "&room=main"))
        self.assertEqual(ks.invite_parse(self.URL.replace("http%3A%2F%2F10.0.0.5%3A4443", "javascript:alert(1)"))["relay"], "")
        self.assertTrue(ks.invite_pending_set(self.URL))
        self.assertEqual(ks.invite_pending_take()["room"], "yard")
        self.assertIsNone(ks.invite_pending_take())                    # consume-once
        self.assertTrue(ks.invite_pending_set(self.URL))
        ks.INVITE_PENDING[0]["at"] -= ks.INVITE_PENDING_S + 1
        self.assertIsNone(ks.invite_pending_take())                    # 2 min life
        self.assertFalse(ks.invite_pending_set("kastr://nothing"))

    def test_serve_wiring(self):
        src = _read("kastr_serve.py")
        self.assertIn('"/api/invite", "/api/invite/revoke", "/api/invites",  # 0.21.75', src)
        self.assertIn('"/api/invites"):                                                        # 0.21.75', src)
        self.assertIn('if path in ("/join", "/join.html"):', src)
        self.assertIn('if path0 == "/api/invite/pending":', src)
        self.assertIn('return self._deny("invite hand-off")', src)
        self.assertIn('"join.html",', _read("build.py"))

    def test_join_page(self):
        j = _read("join.html")
        self.assertIn('var app = "kastr://join?i=" + encodeURIComponent(tok)', j)
        self.assertIn('var web = "/moq-watch-lite.html#invite=" + encodeURIComponent(tok)', j)
        self.assertIn("setTimeout(offerWeb, 1500);", j)
        self.assertIn('window.addEventListener("load", function () { setTimeout(tryApp, 50); });', j)
        self.assertIn("history.replaceState(null, \"\", location.pathname);", j)
        self.assertIn('if (phone) {', j)
        self.assertIn('"__KASTR_WEB_PAGE__" !== "off"', j)
        self.assertIn("the theme before the first paint", j)


class Page(unittest.TestCase):
    def setUp(self):
        self.p = _read("moq-watch-lite.html")

    def test_share_invite_popover(self):
        p = self.p
        self.assertIn('<button type="button" role="radio" data-ttl="86400" class="on">24 hours</button>', p)
        self.assertIn('data-ttl="3600">1 hour</button>', p)
        self.assertIn('data-ttl="604800">7 days</button>', p)
        self.assertIn('const r = await fetch(base + "/api/invite", { method: "POST", headers: { "content-type": "application/json", authorization: "Bearer " + authTokens.member },', p)
        self.assertIn('window.__toast?.("Invite link copied ' + BS + 'u2014 " + say, 5000, { level: "event" });', p)
        self.assertIn('const say = "works for " + (INVITE_TTL_TEXT[ttl]', p)
        self.assertIn('return base + "/join#i=" + encodeURIComponent(token) + "&room=" + encodeURIComponent(slug) + "&relay="', p)

    def test_room_settings_invite_links(self):
        p = self.p
        self.assertIn('<div class="rsrow rsinv" hidden><span class="lbl">Invite links</span>', p)
        self.assertIn('const d = await rsInvCall("/api/invites", { room: slug });', p)
        self.assertIn('const d = await rsInvCall("/api/invite/revoke", { room: slug, ...body });', p)
        self.assertIn("rsInvLoad();   // 0.21.75", p)

    def test_invite_mode_gate(self):
        p = self.p
        self.assertIn('const it = hp.get("invite");', p)
        self.assertIn('history.replaceState(null, "", location.pathname + location.search);', p)
        self.assertIn('const INVITE_KEY = "kastr.invite";', p)
        self.assertIn('<div id="joinInvHead"><h2>You&rsquo;re invited to <span id="joinInvRoom"></span></h2>', p)
        self.assertIn("#joinGate.inv #joinAccessRow, #joinGate.inv #joinPwdRow", p)
        self.assertIn("if (inv && (!rejoinRec || channelSlug(rejoinRec.room) === inv.room)) {", p)
        self.assertIn("invite: invTok }),   // 0.21.75", p)
        # never into kastr.lastjoin's codes: the room code is cleared and the invite is a separate session key
        self.assertIn('joinEls.joinPwd.value = "";   // a room code typed for another room never rides along', p)
        self.assertNotIn("lastjoin\", JSON.stringify({ room: slug, invite", p)

    def test_app_hand_off(self):
        p = self.p
        self.assertIn('await fetch("/api/invite/pending", { cache: "no-store" })', p)
        self.assertIn('if (sw) await gateRelayApply(inv.relay, { keepCodes: true });', p)
        self.assertIn("setInterval(invitePendingPoll, 4000);", p)


if __name__ == "__main__":
    unittest.main()
