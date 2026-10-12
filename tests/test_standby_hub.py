# -*- coding: utf-8 -*-
"""0.21.53: the standby hub (Kenton: a "Make standby" button on a spoke's row; it takes over when it has lost the main hub
for 2 minutes and a spoke agrees, or alone after 5; locked rooms stay locked while the hub is down; automatic failback).
Covers the pieces that need no network: relay-cluster.json keeps the new keys, the replica long-poll, the code check
against a copied record, hand-back merging, chat merging, the hub's pick, and the Relay page wiring. The full
fail-over / fail-back runs in the three-relay lab (scratchpad v02153/lab_standby.py)."""
import io, json, os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_chat  # noqa: E402


def fed_bearer(key):
    return "Bearer " + kr._mint(key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))


class ClusterKeys(unittest.TestCase):
    def test_extra_keys_survive_and_cluster_note_needs_no_restart(self):
        r = kr.Relay(tempfile.mkdtemp())
        kr.save_json(r._cluster_file(), {"connect": "https://hub:4443", "code": "x", "rehomed": {"hub": "https://new:4443"}})
        self.assertEqual(r._cluster_raw().get("rehomed"), {"hub": "https://new:4443"})   # 0.21.25's key was dropped before
        restarted = []
        r._restart = lambda: restarted.append(1)
        r.cluster_note(standby={"name": "b", "node": "b-1", "address": "https://b:4443"}, failover={"from": "x", "at": 1})
        c = r._cluster_raw()
        self.assertEqual((c["standby"]["name"], c["failover"]["at"], c["connect"], c["code"]), ("b", 1, "https://hub:4443", "x"))
        r.cluster_note(failover=None)
        self.assertNotIn("failover", r._cluster_raw())
        r.set_cluster({"master": False})                          # an ordinary save keeps them too
        self.assertEqual(r._cluster_raw()["standby"]["node"], "b-1")
        self.assertFalse(restarted)

    def test_unknown_keys_are_still_dropped(self):
        r = kr.Relay(tempfile.mkdtemp())
        kr.save_json(r._cluster_file(), {"connect": "", "junk": 1})
        self.assertNotIn("junk", r._cluster_raw())


class Replica(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.st = kr.AuthStore(self.dir)
        self.st.set_codes(federation="fed-code-1")
        self.s = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, self.st)
        self.sb = {"name": "b", "node": "standby-0001", "address": "https://b:4443", "secret": "s3cret"}
        self.s.standby_info = lambda: self.sb
        os.makedirs(os.path.join(self.dir, "chat"))
        with open(os.path.join(self.dir, "chat", "main.jsonl"), "w", encoding="utf-8", newline="") as f:
            f.write('{"id":1,"text":"a"}\n{"id":2,"text":"b"}\n{"id":3,"tex')   # the last line is still being written

    def tearDown(self):
        self.s.close()

    def test_only_the_named_standby_with_a_federation_token(self):
        self.assertEqual(self.s.replica({"node": "standby-0001"}, "Bearer nope")[1], 403)
        self.assertEqual(self.s.replica({"node": "someone-else"}, fed_bearer(self.s.key))[1], 403)
        self.s.standby_info = lambda: None
        self.assertEqual(self.s.replica({"node": "standby-0001"}, fed_bearer(self.s.key))[1], 403)

    def test_first_pull_then_deltas(self):
        o, c = self.s.replica({"node": "standby-0001"}, fed_bearer(self.s.key))
        self.assertEqual(c, 200)
        self.assertEqual(o["secret"], "s3cret")
        self.assertIn("federation", o["store"]["codes"])
        self.assertNotIn("fed-code-1", json.dumps(o))             # hashes only
        self.assertEqual(o["chat"]["main"]["text"].count("\n"), 2)  # whole lines only
        off = o["chat"]["main"]["to"]
        # nothing moved -> no store, no chat (wait 0 = answer at once)
        o2, _ = self.s.replica({"node": "standby-0001", "since": {"store": o["storeVer"], "bans": o["bansVer"]}, "chat": {"main": off}}, fed_bearer(self.s.key))
        self.assertNotIn("store", o2)
        self.assertEqual(o2["chat"], {})
        # the line completes, a code changes
        with open(os.path.join(self.dir, "chat", "main.jsonl"), "a", encoding="utf-8", newline="") as f:
            f.write('t":"c"}\n')
        self.st.set_codes(viewer="v-2")
        o3, _ = self.s.replica({"node": "standby-0001", "since": {"store": o["storeVer"], "bans": o["bansVer"]}, "chat": {"main": off}}, fed_bearer(self.s.key))
        self.assertIn("store", o3)
        self.assertEqual(o3["chat"]["main"]["from"], off)
        self.assertEqual(o3["chat"]["main"]["text"], '{"id":3,"text":"c"}\n')

    def test_a_deleted_transcript_is_reported_gone(self):
        o, _ = self.s.replica({"node": "standby-0001", "chat": {"old-room": 50}}, fed_bearer(self.s.key))
        self.assertEqual(o["chatGone"], ["old-room"])

    def test_versions_carry_the_boot(self):
        o, _ = self.s.replica({"node": "standby-0001"}, fed_bearer(self.s.key))
        self.assertTrue(o["storeVer"].startswith("%d." % kr.BOOT_AT))   # a restarted hub never matches an old copy by accident

    def test_the_long_poll_reply_names_the_standby_without_its_secret(self):
        self.assertEqual(self.s.standby_public(), {"name": "b", "node": "standby-0001", "address": "https://b:4443", "web": None})


class Codes(unittest.TestCase):
    def test_a_copied_record_checks_the_code(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(federation="fed-code-1")
        rec = st.export_bundle()["codes"]["federation"]
        self.assertTrue(kr.check_code_record(rec, "fed-code-1"))
        self.assertFalse(kr.check_code_record(rec, "fed-code-2"))
        self.assertFalse(kr.check_code_record(None, "fed-code-1"))
        self.assertFalse(kr.check_code_record(rec, ""))

    def test_handback_signature(self):
        self.assertEqual(kr.standby_sig("k", 100), kr.standby_sig("k", 100))
        self.assertNotEqual(kr.standby_sig("k", 100), kr.standby_sig("k", 101))
        self.assertNotEqual(kr.standby_sig("k", 100), kr.standby_sig("j", 100))


class HandBack(unittest.TestCase):
    def test_merge_bundle(self):
        main = kr.AuthStore(tempfile.mkdtemp())
        main.rooms["kept"] = {"slug": "kept", "at": 100, "keep": True}
        main.rooms["old"] = {"slug": "old", "at": 100}
        main.set_codes(viewer="v-1")
        at_main = main.codes_at.get("viewer")
        b = {"rooms": {"kept": {"slug": "kept", "at": 50, "keep": False},       # older there -> mine stays
                       "new": {"slug": "new", "at": 200},                       # created on the standby
                       "BAD SLUG": {"at": 999}},
             "closed": {"old": int(time.time())},                               # closed there
             "groups": {"g1": {"name": "Site"}},
             "codes": {"viewer": {"salt": "00", "hash": "11", "iter": 1}}, "codesAt": {"viewer": (at_main or 0) + 10}}
        n = main.merge_bundle(b)
        self.assertEqual(main.rooms["kept"]["keep"], True)
        self.assertIn("new", main.rooms)
        self.assertNotIn("BAD SLUG", main.rooms)
        self.assertNotIn("old", main.rooms)
        self.assertEqual(main.groups["g1"]["name"], "Site")
        self.assertEqual(main.codes["viewer"]["hash"], "11")
        self.assertEqual((n["rooms"], n["closed"], n["codes"]), (1, 1, 1))

    def test_an_older_code_change_does_not_win(self):
        main = kr.AuthStore(tempfile.mkdtemp())
        main.set_codes(viewer="v-1")
        before = dict(main.codes["viewer"])
        main.merge_bundle({"codes": {"viewer": {"salt": "00", "hash": "11"}}, "codesAt": {"viewer": 1}})
        self.assertEqual(main.codes["viewer"], before)


class ChatMerge(unittest.TestCase):
    def test_merge_in_adds_only_new_lines_and_rereads_ids(self):
        cs = kastr_chat.ChatStore(tempfile.mkdtemp())
        cs.append("main", "op1", "A", "hello")
        with io.open(cs._path("main"), encoding="utf-8") as f:
            have = f.read()
        new = json.dumps({"id": 50, "ts": 1, "op": "op2", "name": "B", "text": "from the standby"})
        self.assertEqual(cs.merge_in("main", have + new + "\n", keep=True), 1)
        self.assertEqual(cs.merge_in("main", have + new + "\n"), 0)                # twice = nothing new
        self.assertTrue(os.path.exists(cs._keep_path("main")))
        m = cs.append("main", "op1", "A", "after")
        self.assertGreater(int(m["id"] if isinstance(m, dict) else m), 50)      # the counter saw the merged id


class Pick(unittest.TestCase):
    def setUp(self):
        self.r = kr.Relay(tempfile.mkdtemp())
        self.r._restart = lambda: False
        self.r.hub_auth = lambda hub: None   # no network in unit tests (Make standby probes the address)
        st = kr.AuthStore(self.r.state_dir)
        self.r.auth = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)
        self.r.auth.spokes["k1"] = {"name": "southridge", "node": "sr-0001", "minter": "http://10.0.5.2:4444", "peer": "10.0.5.2",
                                    "port": 4443, "web": 8001, "at": time.time()}
        self.r.auth.spokes["k2"] = {"name": "oldbox", "minter": "http://10.0.6.2:4444", "at": time.time()}

    def tearDown(self):
        self.r.auth.close()

    def test_only_a_hub_picks(self):
        self.assertEqual(self.r.make_standby({"name": "southridge"})[1], 409)

    def test_pick_derive_address_keep_secret_clear(self):
        kr.save_json(self.r._cluster_file(), {"hub": True})
        o, c = self.r.make_standby({"name": "southridge"})
        self.assertEqual(c, 200)
        self.assertEqual(o["standby"]["address"], kr._normalize_hub("https://10.0.5.2:4443"))
        self.assertNotIn("secret", o["standby"])
        sec = self.r._cluster_raw()["standby"]["secret"]
        self.assertEqual(len(sec), 32)
        self.r.make_standby({"name": "southridge", "address": "10.0.5.9:4443"})
        self.assertEqual(self.r._cluster_raw()["standby"]["secret"], sec)          # the same box keeps its secret
        self.assertEqual(self.r.make_standby({"name": "oldbox"})[1], 409)          # too old to know its machine id
        self.assertEqual(self.r.make_standby({"name": "nobody"})[1], 409)
        self.assertEqual(self.r.standby_view()["name"], "southridge")
        self.r.make_standby({"clear": True})
        self.assertNotIn("standby", self.r._cluster_raw())

    def test_candidates_and_a_chosen_address(self):   # 0.21.54 (Kenton: choose the address)
        self.r.auth.spokes["k1"]["ips"] = ["10.0.5.2", "192.168.50.7"]
        self.r.auth.spokes["k1"]["peer"] = "203.0.113.9"
        c = kr.standby_candidates(self.r.auth.spokes["k1"])
        self.assertEqual([x["address"] for x in c], ["https://10.0.5.2:4443", "https://192.168.50.7:4443", "https://203.0.113.9:4443"])
        self.assertIn("standbyAddrs", self.r.auth.spokes_public()[0])
        kr.save_json(self.r._cluster_file(), {"hub": True})
        self.r.hub_auth = lambda hub: None                          # nobody answers there
        o, c = self.r.make_standby({"name": "southridge", "address": "192.168.50.7"})
        self.assertEqual((c, o["standby"]["address"], o["reach"]), (200, kr._normalize_hub("https://192.168.50.7:4443"), False))   # the spoke's port added
        self.r.hub_auth = lambda hub: {"app": "KASTR"}
        o, _ = self.r.make_standby({"name": "southridge", "address": "https://192.168.50.7:5443"})
        self.assertEqual((o["standby"]["address"], o["reach"]), (kr._normalize_hub("https://192.168.50.7:5443"), True))
        self.assertEqual(self.r.make_standby({"name": "southridge", "address": "not an address!"})[1], 400)

    def test_the_public_address_is_offered(self):   # 0.21.54 (Kenton: "check whatsmyip and suggest that")
        v = {"peer": "10.9.9.9", "port": 4573, "node": "x", "ips": ["10.9.9.9"], "publicIp": "198.51.100.4"}
        c = kr.standby_candidates(v)
        self.assertEqual([x["address"] for x in c], ["https://10.9.9.9:4573", "https://198.51.100.4:4573"])
        self.assertIn("port forward", c[1]["why"])

    def test_public_ip_lookup_falls_through_and_caches(self):
        import threading, urllib.request
        calls, done = [], threading.Event()

        class R:
            def __init__(self, body): self.body = body
            def read(self, n=-1): return self.body
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake(req, timeout=0):
            calls.append(req.full_url)
            if "ipify" in req.full_url:
                raise OSError("down")
            return R(b"198.51.100.4\n")
        old, saved = urllib.request.urlopen, dict(kr._PUBLIC_IP)
        urllib.request.urlopen = fake
        try:
            kr._PUBLIC_IP.update({"ip": "", "at": 0.0, "busy": False})
            self.assertIn(kr.public_ip(done.set), ("", "198.51.100.4"))   # the first call starts the lookup (in the background)
            self.assertTrue(done.wait(5))                              # a new address -> the spoke re-registers
            self.assertEqual(kr.public_ip(), "198.51.100.4")
            self.assertEqual(len(calls), 2)                            # ipify failed, the next service answered
            kr.public_ip(); time.sleep(0.2)
            self.assertEqual(len(calls), 2)                            # cached for 6 hours
        finally:
            urllib.request.urlopen = old
            kr._PUBLIC_IP.clear(); kr._PUBLIC_IP.update(saved)

    def test_a_spoke_without_lan_offers_the_address_the_hub_sees(self):
        v = {"peer": "10.9.9.9", "port": 4573, "node": "x"}
        self.assertEqual(kr.standby_candidates(v), [{"address": "https://10.9.9.9:4573", "why": "as this hub sees it"}])

    def test_a_promoted_standby_advertises_no_standby(self):
        kr.save_json(self.r._cluster_file(), {"hub": True, "promoted": {"at": 1}, "standby": {"name": "me", "address": "https://me:4443"}})
        self.r.auth.standby_info = lambda: (None if self.r._cluster_raw().get("promoted") else self.r._cluster_raw().get("standby"))
        self.assertIsNone(self.r.auth.standby_public())
        self.assertEqual(self.r.standby_view()["role"], "promoted")


class Wiring(unittest.TestCase):
    def test_sources(self):
        src = io.open(os.path.join(HERE, "kastr_relay.py"), encoding="utf-8").read()
        for needle in ('"/api/relay/standby")', 'path == "/api/hub/replica"', '"/api/hub/failover", "/api/hub/handback"',
                       'path == "/api/hub/standby"', "self._failover_watch_start()", "FAILOVER_AFTER_S = 120", "STANDBY_ALONE_S = 300",
                       '"standby": self.standby_public()', "self.hub_ok_at = time.time()", '"port": self.port, "web": web'):
            self.assertIn(needle, src)
        # locked rooms stay locked: the saved copy of the hub's rooms is consulted after a restart
        self.assertIn("_ks._HUB_ROOMS_CACHE[0]", src)
        page = io.open(os.path.join(HERE, "relay.html"), encoding="utf-8").read()
        for needle in ('id="standbyState"', "function paintStandby(", 'class=\\"ghost spsb\\"', '"/api/relay/standby"',
                       "function agoText(sec)", '" min " + String(t % 60).padStart(2, "0") + " s ago"'):
            self.assertIn(needle, page)



class ViewOnlyName(unittest.TestCase):
    def test_the_watchers_name_hides_like_a_publishers(self):
        with io.open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("#stage.spot .pane.vtile .vonly .vn { max-width:0;", page)                 # folded unless the pointer is on it
        self.assertIn("#stage.spot .pane.vtile:hover .vonly .vn", page)
        self.assertIn("#stagewrap.idle #stage.spot .pane.vtile .vonly .vn { max-width:0 !important;", page)   # mouse resting
        self.assertIn("#stagewrap.idle #stage.spot .pane .label", page)                          # the publishers' rule it mirrors

if __name__ == "__main__":
    unittest.main()
