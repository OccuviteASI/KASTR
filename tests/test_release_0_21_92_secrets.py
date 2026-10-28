# -*- coding: utf-8 -*-
"""v0.21.92 (Kenton: "fix the plain text passcodes"): NO SECRET IN PLAIN TEXT AT REST.

Every flow that stores a code runs in a lab state folder (the box's My room + locked-room shares, an admin reset, an invite,
the GIF key, an RTSP camera with a password, the remote-control keys, the hub link / standby / mesh tokens, the hand-over
copy, messages, presentations, shared files). Then EVERY byte of the folder (and launch.log) is scanned for every code
and token: none may appear. The 0.21.91 files (and their .bak copies) are rewritten sealed on the first start, a box
restarted with no window still re-shares into a locked room, My room still unlocks, the hand-over still carries the room
keys (to the standby's memory; sealed on its disk).

Run: python -m unittest discover -s tests
No network, no processes, no window: minters / posts are injected, Popen refuses.
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kastr_secret as ks  # noqa: E402
import kastr_relay as kr  # noqa: E402
import kastr_rtsp  # noqa: E402
import kastr_serve  # noqa: E402
import kastr_gif  # noqa: E402
import kastr_rcadmin  # noqa: E402
import kastr_chat  # noqa: E402
import kastr_pres  # noqa: E402
import kastr  # noqa: E402
from test_release_0_21_75_boxrooms import Sandbox, FakeRelay, jwt, RELAY, HOME, PATH1  # noqa: E402

# lab-only values (never a real code)
FLEET = {"viewer": "labView-7Q2w", "publisher": "labPub-9X4z", "admin": "labAdm-3K8v"}
MYROOM = "janeMyRoom-K7P"
MYROOM2 = "janeNewRoom-M3Q"
TEMP = "tmpReset-4R2x"
LOCKED = "lockCode-Z5y"
CAMPW = "camPassW0rd9"
CAMURL = "rtsp://admin:%s@10.9.8.7:554/s1" % CAMPW
GIPHY = "GiphyLabKey0123456789abcd"
FEDCODE = "labFedCode-H8u"
FEDTOK = "eyJhbGciOiJIUzI1NiJ9.eyJmZWQiOnRydWV9.labFedTokSig"
SBSECRET = "ab" * 16
LINKTOK = "eyJhbGciOiJIUzI1NiJ9.eyJsaW5rIjp0cnVlfQ.labLinkSig"
RCXKEY = "cd" * 32
SALT = "s" * 16


def scan(root, secrets):
    """-> [(file, secret-name)] for every plain secret found in any file under root."""
    hits = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            try:
                with open(p, "rb") as fh:
                    raw = fh.read()
            except OSError:
                continue
            for name, s in secrets.items():
                if s and s.encode("utf-8") in raw:
                    hits.append((os.path.relpath(p, root), name))
    return hits


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kastr092-")
        ks.forget_all()
        ks.configure(self.dir)

    def tearDown(self):
        ks.forget_all()
        ks.configure(None)
        shutil.rmtree(self.dir, ignore_errors=True)


class Primitives(Base):
    def test_seal_open_and_old_plain(self):
        p = os.path.join(self.dir, "x.json")
        v = ks.seal(MYROOM, p)
        self.assertTrue(v.startswith("ksec1:"))
        self.assertNotIn(MYROOM, v)
        ks.forget_all()                                   # a fresh process: no cache
        self.assertEqual(ks.unseal(v, p), MYROOM)
        self.assertEqual(ks.unseal("old-plain-code", p), "old-plain-code")   # a 0.21.91 value still reads
        self.assertEqual(ks.seal(v, p), v)                # never sealed twice
        self.assertIn(ks.seal("", p), ("",))

    def test_key_file_store_is_owner_only_and_tamper_proof(self):
        with mock.patch.dict(os.environ, {"KASTR_SECRET_STORE": "file"}):
            ks.forget_all()
            self.assertEqual(ks.configure(self.dir), "file")
            p = os.path.join(self.dir, "x.json")
            v = ks.seal(LOCKED, p)
            self.assertTrue(v.startswith("ksec1:kf:"))
            self.assertTrue(os.path.isfile(os.path.join(self.dir, "secret.key")))
            if os.name != "nt":
                self.assertEqual(os.stat(os.path.join(self.dir, "secret.key")).st_mode & 0o777, 0o600)
            ks.forget_all()
            self.assertEqual(ks.unseal(v, p), LOCKED)
            bad = v[:-3] + ("A" if v[-3] != "A" else "B") + v[-2:]
            ks.forget_all()
            self.assertIsNone(ks.unseal(bad, p))          # changed -> not opened
            other = tempfile.mkdtemp()
            try:
                ks.forget_all()
                ks.configure(other)
                self.assertIsNone(ks.unseal(v, os.path.join(other, "x.json")))   # another key -> not opened (logged once)
            finally:
                shutil.rmtree(other, ignore_errors=True)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_windows_uses_dpapi(self):
        with mock.patch.dict(os.environ, {"KASTR_SECRET_STORE": "auto"}):
            ks.forget_all()
            self.assertEqual(ks.configure(self.dir), "dpapi")
            v = ks.seal(MYROOM, os.path.join(self.dir, "x.json"))
            self.assertTrue(v.startswith("ksec1:dp:"))
            self.assertFalse(os.path.exists(os.path.join(self.dir, "secret.key")))   # no key file on Windows
            ks.forget_all()
            self.assertEqual(ks.unseal(v), MYROOM)

    def test_mask(self):
        ks.remember(MYROOM)
        tok = "ki-0123abcd-" + "Z" * 40
        line = ("joined %s code=%s rtsp://admin:%s@cam/x?jwt=eyJabcdefgh.eyJijklmnop.sig {\"roomCode\": \"%s\"} Bearer abcdefghijk %s"
                % (CAMURL, LOCKED, CAMPW, LOCKED, tok)) + " " + MYROOM
        out = ks.mask(line)
        for s in (CAMPW, LOCKED, MYROOM, tok, "eyJabcdefgh.eyJijklmnop", "abcdefghijk"):
            self.assertNotIn(s, out)
        self.assertIn("rtsp://***@10.9.8.7", out)
        self.assertEqual(ks.mask("port 4443 at 12:30:01"), "port 4443 at 12:30:01")   # short digits are left alone
        self.assertNotIn(LOCKED, kr.redact_log('"code": "%s" ' % LOCKED))

    def test_digest_matches(self):
        d = ks.digest("tok-1")
        self.assertTrue(ks.digest_matches(d, "tok-1"))
        self.assertFalse(ks.digest_matches(d, "tok-2"))
        self.assertTrue(ks.digest_matches("tok-1", "tok-1"))      # a 0.21.91 plain token still works
        self.assertFalse(ks.digest_matches(d, ""))

    def test_child_registry_keeps_a_camera_password_as_a_digest(self):
        rec = {"pid": os.getpid(), "exe": "", "sig": [ks.digest(CAMURL)], "started": time.time()}
        with mock.patch.object(kastr_rtsp, "_pid_alive", lambda pid: True), \
                mock.patch.object(kastr_rtsp, "_pid_image", lambda pid: (None, None, ["ffmpeg", "-i", CAMURL, "-f", "mpegts", "-"])):
            self.assertTrue(kastr_rtsp._pid_matches(rec))
            self.assertFalse(kastr_rtsp._pid_matches(dict(rec, sig=[ks.digest(CAMURL + "x")])))
        src = open(os.path.join(HERE, "kastr_rtsp.py"), encoding="utf-8").read()
        self.assertIn('"sig": [kastr_secret.digest(str(x)) if kastr_secret.has_creds(str(x)) else str(x)', src)


class Flows(Sandbox):
    """Every flow in one lab state folder, then the scan."""

    def setUp(self):
        super().setUp()
        self.dir = self.tmp.name
        ks.forget_all()
        ks.configure(self.dir)
        self.secrets = dict(FLEET, myroom=MYROOM, myroom2=MYROOM2, temp=TEMP, locked=LOCKED, campw=CAMPW, giphy=GIPHY,
                            fedcode=FEDCODE, fedtok=FEDTOK, sbsecret=SBSECRET, linktok=LINKTOK, rcxkey=RCXKEY)
        self.notes = []
        self._sd = mock.patch.object(kastr, "state_dir", lambda: self.dir)
        self._sd.start()

    def tearDown(self):
        self._sd.stop()
        kastr_serve.INVITE_FILE[0] = None
        kastr_serve.INVITE_PENDING[0] = None
        ks.forget_all()
        ks.configure(None)
        super().tearDown()

    def log(self, m):
        self.notes.append(str(m))
        kastr.note(m)                         # launch.log in the lab folder, as the launcher writes it

    def test_every_flow_leaves_no_plain_secret_on_disk(self):
        d = self.dir
        # ---- the hub: fleet codes, My room, an admin reset, a locked room, an invite
        st = kr.AuthStore(d, self.log)
        st.set_codes(**FLEET)
        o, c = kr.personal_op(st, {"op": "create", "name": "Jane Doe", "code": MYROOM, "access": FLEET["publisher"]}, "10.0.0.5", log=self.log)
        self.assertEqual(c, 200, o)
        slug = o["slug"]
        svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st, log=self.log)
        try:
            o, c = svc.token({"room": slug, "code": FLEET["publisher"], "host": "janepc-1a2b", "roomCode": MYROOM}, "10.0.0.7")
            self.assertEqual(c, 200, o)
            self.secrets["member"] = o["tokens"]["member"]
            self.log("joined My room with %s" % (RELAY + "/?jwt=" + o["tokens"]["member"]))
            o, c = kr.personal_op(st, {"op": "reset", "name": "Jane Doe", "code": TEMP}, "10.0.0.5", admin=True, log=self.log)
            self.assertEqual(c, 200, o)
            o, c = kr.personal_op(st, {"op": "change", "name": "Jane Doe", "code": TEMP, "newCode": MYROOM2}, "10.0.0.5", log=self.log)
            self.assertEqual(c, 200, o)
            o, c = svc._msgr().api({"op": "unlock", "name": "Jane Doe", "code": MYROOM2}, "janepc-1a2b")   # My room still unlocks
            self.assertEqual(c, 200, o)
        finally:
            svc.close()
        h = hashlib.sha256((SALT + LOCKED).encode()).hexdigest()
        o, c = kr.register_room(st, {"slug": "lockd", "salt": SALT, "hash": h, "access": FLEET["publisher"], "persistent": True}, "10.0.0.1")
        self.assertEqual(c, 200, o)
        self.secrets["roomkey"] = o["roomKey"]
        row, itok, c = st.invite_create("lockd", 3600, by="Kenton")
        self.assertEqual(c, 200, itok)
        self.secrets["invite"] = itok
        kastr_serve.invite_pending_restore(os.path.join(d, "invite-pending.json"))
        self.assertTrue(kastr_serve.invite_pending_set("kastr://join?i=%s&room=lockd" % itok))
        self.log("invite opened: kastr://join?i=%s&room=lockd" % itok)
        st._save()
        st._save()                            # twice: relay-auth.json.bak exists (sealed)
        # ---- the hub link, the standby, the mesh links, the hand-over copy (all through save_json)
        kr.save_json(os.path.join(d, "relay-cluster.json"), {"connect": "https://10.0.0.2:4443", "code": FEDCODE,
                                                            "standby": {"node": "sb", "secret": SBSECRET}})
        kr.save_json(os.path.join(d, "relay-cluster.json"), {"connect": "https://10.0.0.2:4443", "code": FEDCODE,
                                                            "standbyOf": {"main": "x", "secret": SBSECRET}})
        kr.save_json(os.path.join(d, "relay-federation.json"), {"hub": "https://10.0.0.2:4443", "token": FEDTOK, "exp": 9e9}, backup=False)
        kr.save_json(os.path.join(d, "relay-mesh.json"), {"links": [{"url": "https://10.0.0.3:4443", "cost": 1, "token": LINKTOK}]}, backup=False)
        kr.save_json(os.path.join(d, "relay-link.json"), {"kid": "k", "tokens": {"nodeb": {"token": LINKTOK, "exp": 9e9}}}, backup=False)
        bundle = st.export_bundle()
        self.assertEqual(bundle["rooms"]["lockd"]["roomKey"], self.secrets["roomkey"])   # the hand-over carries the key (memory)
        kr.save_json(os.path.join(d, "hub-replica.json"), {"store": bundle, "storeVer": 1}, backup=False)
        # ---- the GIF key, the remote-control keys
        g = kastr_gif.GifSearch(d, log=self.log)
        self.assertEqual(g.configure({"key": GIPHY})[1], 200)
        s = kastr_rcadmin.set_optin(d, True, log=self.log)
        self.secrets["rcadmin"] = s["key"]
        hub = kastr_rcadmin.HubRegistry(d, log=self.log)
        with hub.cv:
            hub.machines["labpc-1a2b"] = {"node": "labpc-1a2b", "key": RCXKEY, "kid": kastr_rcadmin.kid_of(RCXKEY), "at": time.time()}
            hub._save_locked()
        # ---- messages, presentations, shared files on the hub
        chat = kastr_chat.ChatStore(d)
        m = chat.append("lockd", "kenton", "Kenton", "hello")
        self.secrets["chattok"] = m["token"]
        pres = kastr_pres.Store(d)
        did, ptok, prtok = pres.create("lockd", "Deck", 3)
        self.secrets.update(prestok=ptok, presrtok=prtok)
        # ---- the box: My room session + a camera with a password, shared into the locked room
        self.relay = FakeRelay(locked={"lockd": LOCKED})
        kastr_rtsp.mint_member = self.relay.mint
        b = kastr_rtsp.Bridge(state_dir=d, log=self.log, host_slug="yard-0001")
        b.moq = "moq"
        b._xs_post = self.relay.post
        b._xs_ensure = lambda: None
        b.set_session(HOME, FLEET["publisher"], MYROOM2, RELAY)
        feed = b.add(CAMURL)
        b.publish(feed.id, PATH1, RELAY + "/?jwt=" + jwt(HOME), audio=False, keep=True, label="Gate Cam")
        r = b.set_xs(feed.id, ["lockd"], {"lockd": LOCKED})
        self.assertEqual(r["xsState"]["lockd"], "ok")
        b.persist_feeds()
        kastr_serve.prefs_merge(os.path.join(d, "prefs.json"), {"kastr.rtsp.history": json.dumps([CAMURL]),
                                                                "kastr.lastjoin": json.dumps({"room": "lockd", "code": LOCKED, "access": FLEET["publisher"]})})
        self.log("rtsp: added %s with access %s / room code %s" % (CAMURL, FLEET["publisher"], MYROOM2))
        # ---- /api/diag: masked
        diag = ks.mask(json.dumps({"page": "x", "join": {"code": LOCKED, "access": FLEET["publisher"], "src": CAMURL}}))
        for name, sec in self.secrets.items():
            self.assertNotIn(sec, diag, name)
        # ---- THE SCAN: the whole folder, launch.log included
        self.assertTrue(os.path.isfile(os.path.join(d, "launch.log")))
        self.assertTrue(os.path.isfile(os.path.join(d, "relay-auth.json.bak")))
        hits = scan(d, self.secrets)
        self.assertEqual(hits, [], "plain secrets on disk: %r" % hits)
        # ---- and everything still reads back (a restart)
        ks.forget_all()
        ks.configure(d)
        st2 = kr.AuthStore(d, self.log)
        self.assertEqual(st2.rooms["lockd"]["roomKey"], self.secrets["roomkey"])
        self.assertTrue(st2.check("publisher", FLEET["publisher"]))
        cl, _ = kr.load_json(os.path.join(d, "relay-cluster.json"))
        self.assertEqual((cl["code"], cl["standbyOf"]["secret"]), (FEDCODE, SBSECRET))
        self.assertEqual(kr.load_json(os.path.join(d, "relay-federation.json"))[0]["token"], FEDTOK)
        self.assertEqual(kr.load_json(os.path.join(d, "relay-mesh.json"))[0]["links"][0]["token"], LINKTOK)
        self.assertEqual(kr.load_json(os.path.join(d, "relay-link.json"))[0]["tokens"]["nodeb"]["token"], LINKTOK)
        rep = kr.load_json(os.path.join(d, "hub-replica.json"))[0]
        self.assertEqual(rep["store"]["rooms"]["lockd"]["roomKey"], self.secrets["roomkey"])
        self.assertEqual(kastr_gif.GifSearch(d).key, GIPHY)
        self.assertEqual(kastr_rcadmin.load_settings(d)["key"], self.secrets["rcadmin"])
        self.assertEqual(kastr_rcadmin.HubRegistry(d).machines["labpc-1a2b"]["key"], RCXKEY)
        kastr_serve.INVITE_PENDING[0] = None
        self.assertTrue(kastr_serve.invite_pending_restore(os.path.join(d, "invite-pending.json")))
        self.assertEqual(kastr_serve.invite_pending_take()["token"], self.secrets["invite"])
        items = kastr_serve.prefs_load(os.path.join(d, "prefs.json"))
        self.assertEqual(json.loads(items["kastr.rtsp.history"]), [CAMURL])
        self.assertTrue(chat.delete("lockd", m["id"], m["token"]))                      # the poster's token still deletes
        self.assertEqual(kastr_pres.Store(d).set_live(did, ptok, 1), 200)               # the presenter's token still works
        self.assertEqual(kastr_pres.Store(d).readable(did, "s0.bin", prtok), (True, True))
        self.assertEqual(kastr_pres.Store(d).set_live(did, "nope", 1), 403)
        # ---- the hand-over: the standby takes the bundle and the creator's roomKey heartbeat still holds the room
        sb_dir = tempfile.mkdtemp()
        try:
            sb = kr.AuthStore(sb_dir)
            sb.import_bundle(rep["store"])
            sb._save()
            o, c = kr.register_room(sb, {"slug": "lockd", "salt": SALT, "hash": h, "roomKey": self.secrets["roomkey"]}, "10.0.0.1")
            self.assertEqual(c, 200, o)
            self.assertEqual(scan(sb_dir, {"roomkey": self.secrets["roomkey"]}), [])
        finally:
            shutil.rmtree(sb_dir, ignore_errors=True)

    def test_box_restarted_with_no_window_reshares_into_the_locked_room(self):
        d = self.dir
        self.relay = FakeRelay(locked={"lockd": LOCKED})
        kastr_rtsp.mint_member = self.relay.mint
        b = self.bridge(session=False)
        b.set_session(HOME, FLEET["publisher"], MYROOM, RELAY)
        feed = b.add(CAMURL)
        b.publish(feed.id, PATH1, RELAY + "/?jwt=" + jwt(HOME), audio=False, keep=True, label="Gate Cam")
        self.assertEqual(b.set_xs(feed.id, ["lockd"], {"lockd": LOCKED})["xsState"]["lockd"], "ok")
        b.persist_feeds()
        self.assertEqual(scan(d, {"locked": LOCKED, "myroom": MYROOM, "pub": FLEET["publisher"], "campw": CAMPW}), [])
        # the restart: a new process (no caches), no page, no session posted
        ks.forget_all()
        ks.configure(d)
        self.relay.mints.clear()
        b2 = self.bridge(session=False)
        self.assertEqual(b2.restore(mint=lambda: RELAY + "/?jwt=" + jwt(HOME)), 1)
        f2 = list(b2._feeds.values())[0]
        self.assertEqual(f2.source_url, CAMURL)
        self.assertEqual(f2.xs_codes, {"lockd": LOCKED})
        self.assertEqual((b2._session["access"], b2._session["roomCode"]), (FLEET["publisher"], MYROOM))
        out = self.tick(b2)
        self.assertEqual(out[PATH1], {"lockd": "ok"})
        self.assertIn(("lockd", FLEET["publisher"], LOCKED), self.relay.mints)
        # kastr.py's own reader (feeds_restore) gets the plain codes too
        with open(os.path.join(d, "rtsp-feeds.json"), encoding="utf-8") as f:
            raw = json.load(f)
        self.assertTrue(ks.is_sealed(raw["access"]) and ks.is_sealed(raw["roomCode"]))
        doc = ks.open_doc(os.path.join(d, "rtsp-feeds.json"), raw)
        self.assertEqual((doc["access"], doc["roomCode"], doc["feeds"][0]["url"]), (FLEET["publisher"], MYROOM, CAMURL))


class Migration(Base):
    """The first start of 0.21.92 rewrites the 0.21.91 plain files -- and their .bak copies -- sealed."""

    def plain(self, name, doc):
        p = os.path.join(self.dir, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        return p

    def test_old_plain_files_are_rewritten_sealed(self):
        feeds = {"room": "lockd", "access": FLEET["publisher"], "roomCode": MYROOM, "relay": RELAY,
                 "feeds": [{"url": CAMURL, "keep": True, "xs": ["lockd"], "xsCodes": {"lockd": LOCKED}},
                           {"url": "rtsp://10.0.0.5/plain", "keep": True}],
                 "removed": [{"url": "rtsp://u:%s@h/1" % CAMPW, "at": 1}]}
        self.plain("rtsp-feeds.json", feeds)
        self.plain("rtsp-feeds.json.4242.tmp", feeds)                         # a crash mid-write left one
        auth = {"rooms": {"lockd": {"salt": SALT, "hash": "h", "roomKey": "ef" * 16, "at": 1}}}
        self.plain("relay-auth.json", auth)
        self.plain("relay-auth.json.bak", auth)
        self.plain("relay-auth.corrupt-17.json", auth)
        self.plain("relay-cluster.json", {"connect": "https://h:4443", "code": FEDCODE, "standby": {"secret": SBSECRET}})
        self.plain("relay-cluster.json.bak", {"connect": "https://h:4443", "code": FEDCODE})
        self.plain("relay-federation.json", {"hub": "https://h", "token": FEDTOK})
        self.plain("relay-mesh.json", {"links": [{"url": "https://h", "token": LINKTOK}]})
        self.plain("relay-link.json", {"tokens": {"n": {"token": LINKTOK}}})
        self.plain("hub-replica.json", {"store": auth})
        self.plain("gif-search.json", {"key": GIPHY, "on": True})
        self.plain("rcadmin.json", {"on": True, "key": RCXKEY})
        self.plain("rcadmin.json.tmp", {"on": True, "key": RCXKEY})
        self.plain("relay-rcx.json", {"machines": {"labpc-1a2b": {"key": RCXKEY, "at": time.time()}}})
        itok = "ki-0123abcd-" + "Q" * 40
        self.plain("invite-pending.json", {"token": itok, "room": "lockd", "relay": "", "at": time.time()})
        self.plain("prefs.json", {"v": 1, "items": {"kastr.rtsp.history": json.dumps([CAMURL]), "kastr.theme": "dark"}})
        self.plain("window.json", {"x": 1})                                    # not a secret file: left alone
        secrets = {"pub": FLEET["publisher"], "myroom": MYROOM, "locked": LOCKED, "campw": CAMPW, "roomkey": "ef" * 16,
                   "fedcode": FEDCODE, "sb": SBSECRET, "fedtok": FEDTOK, "link": LINKTOK, "giphy": GIPHY, "rcx": RCXKEY, "invite": itok}
        self.assertNotEqual(scan(self.dir, secrets), [])
        done = ks.migrate_state(self.dir, log=lambda m: None)
        self.assertIn("rtsp-feeds.json", done)
        self.assertIn("relay-auth.json.bak", done)
        self.assertIn("rtsp-feeds.json.4242.tmp (removed)", done)
        self.assertNotIn("window.json", done)
        self.assertEqual(scan(self.dir, secrets), [])
        self.assertEqual(ks.migrate_state(self.dir), [])                     # the second start: nothing left to do
        # the readers get the plain values back
        ks.forget_all()
        ks.configure(self.dir)
        with open(os.path.join(self.dir, "rtsp-feeds.json"), encoding="utf-8") as f:
            raw = json.load(f)
        self.assertEqual(raw["feeds"][1]["url"], "rtsp://10.0.0.5/plain")       # a URL without a password stays readable
        self.assertEqual(ks.open_doc(os.path.join(self.dir, "rtsp-feeds.json"), raw), feeds)
        self.assertEqual(kr.load_json(os.path.join(self.dir, "relay-auth.json.bak"))[0], auth)
        self.assertEqual(kr.load_json(os.path.join(self.dir, "relay-cluster.json"))[0]["code"], FEDCODE)
        self.assertEqual(kastr_gif.GifSearch(self.dir).key, GIPHY)
        self.assertEqual(kastr_rcadmin.load_settings(self.dir)["key"], RCXKEY)
        self.assertEqual(kastr_serve.prefs_load(os.path.join(self.dir, "prefs.json"))["kastr.theme"], "dark")

    def test_old_plain_pres_decks_keep_only_digests(self):
        root = os.path.join(self.dir, "pres", "a" * 32)
        os.makedirs(root)
        with open(os.path.join(root, "meta.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "a" * 32, "token": "b" * 32, "rtoken": "c" * 32, "live": 0, "at": int(time.time())}, f)
        st = kastr_pres.Store(self.dir)
        self.assertEqual(scan(self.dir, {"t": "b" * 32, "r": "c" * 32}), [])
        self.assertEqual(st.set_live("a" * 32, "b" * 32, 1), 200)

    def test_launcher_migrates_at_start(self):
        src = open(os.path.join(HERE, "kastr.py"), encoding="utf-8").read()
        self.assertIn("kastr_secret.migrate_state(state_dir(), log=note)", src)
        self.assertIn("kastr_secret.mask(str(msg).rstrip())", src)          # launch.log masked
        self.assertIn('"--hidden-import", "kastr_secret"', open(os.path.join(HERE, "build.py"), encoding="utf-8").read())


class LineEndings(unittest.TestCase):
    def test_line_endings(self):
        for name, crlf in (("kastr_secret.py", False), ("kastr_relay.py", False), ("kastr_gif.py", False),
                           ("kastr_rcadmin.py", False), ("kastr_chat.py", False), ("kastr_pres.py", False),
                           ("kastr_rtsp.py", True), ("kastr.py", True), ("kastr_serve.py", True), ("build.py", True),
                           ("tests/test_release_0_21_92_secrets.py", False)):
            with open(os.path.join(HERE, name), "rb") as f:
                raw = f.read()
            n_crlf = raw.count(b"\r\n")
            n_lf = raw.count(b"\n") - n_crlf
            if crlf:
                self.assertEqual(n_lf, 0, name)
            else:
                self.assertEqual(n_crlf, 0, name)


if __name__ == "__main__":
    unittest.main()
