# -*- coding: utf-8 -*-
"""v0.21.92: the sealed state folder survives a DOWNGRADE, and the codes the BROWSER keeps are wrapped.

KASTR swaps itself to its relay host's version, older ones included. A 0.21.91 build would read every "ksec1:..." value
as the code itself, so right before a verified swap to a build older than 0.21.92 the folder is written back in the plain
form that build reads (a failed download or a placement that fails leaves it sealed); the next 0.21.92+ start seals it
again. The hub hand-over travels as plain JSON in memory, so a 0.21.92 hub and a 0.21.91 standby (either way round)
still hand over.

The page side: assets/vault.js keeps the codes in localStorage / sessionStorage only as "kv1:..." (AES-GCM under a
non-extractable key in IndexedDB); the prefs mirror and the server keep that wrapped form as it is.

Run: python -m unittest discover -s tests
No network, no processes, no window: the download and the relaunch are mocked.
"""
import hashlib
import io
import json
import os
import re
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
import kastr_serve  # noqa: E402
import kastr  # noqa: E402

# lab-only values (never a real code)
PUB = "labPub-9X4z"
MYROOM = "janeMyRoom-K7P"
LOCKED = "lockCode-Z5y"
CAMPW = "camPassW0rd9"
CAMURL = "rtsp://admin:%s@10.9.8.7:554/s1" % CAMPW
CAMPW2 = "camPassN3w77"
CAMURL2 = "rtsp://admin:%s@10.9.8.8:554/s1" % CAMPW2
FEDCODE = "labFedCode-H8u"
SBSECRET = "ab" * 16
ROOMKEY = "ef" * 16
GIPHY = "GiphyLabKey0123456789abcd"
SALT = "s" * 16
SECRETS = {"pub": PUB, "myroom": MYROOM, "locked": LOCKED, "campw": CAMPW, "fedcode": FEDCODE, "sb": SBSECRET,
           "roomkey": ROOMKEY, "giphy": GIPHY}


def scan(root, secrets):
    hits = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            try:
                with open(os.path.join(dp, f), "rb") as fh:
                    raw = fh.read()
            except OSError:
                continue
            for name, s in secrets.items():
                if s and s.encode("utf-8") in raw:
                    hits.append((os.path.relpath(os.path.join(dp, f), root), name))
    return sorted(set(hits))


def plain_files(d):
    """What a 0.21.91 folder holds (all plain)."""
    docs = {
        "rtsp-feeds.json": {"room": "lockd", "access": PUB, "roomCode": MYROOM, "relay": "https://10.0.0.2:4443",
                            "feeds": [{"url": CAMURL, "keep": True, "xs": ["lockd"], "xsCodes": {"lockd": LOCKED}}]},
        "relay-auth.json": {"rooms": {"lockd": {"salt": SALT, "hash": "h", "roomKey": ROOMKEY, "at": 1}}},
        "relay-auth.json.bak": {"rooms": {"lockd": {"salt": SALT, "hash": "h", "roomKey": ROOMKEY, "at": 1}}},
        "relay-cluster.json": {"connect": "https://10.0.0.2:4443", "code": FEDCODE, "standby": {"node": "sb", "secret": SBSECRET}},
        "gif-search.json": {"key": GIPHY, "on": True},
        "window.json": {"x": 1},
    }
    for name, doc in docs.items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(doc, f)
    return docs


def text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def raw(d, name):
    """A 0.21.91 reader: the JSON as it is on disk, nothing opened."""
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return json.load(f)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kastr092d-")
        ks.forget_all()
        ks.configure(self.dir)

    def tearDown(self):
        ks.forget_all()
        ks.configure(None)
        shutil.rmtree(self.dir, ignore_errors=True)


class Versions(unittest.TestCase):
    def test_which_builds_read_sealed_values(self):
        for v in ("0.21.92", "v0.21.92", "0.21.100", "0.22.0", "1.0.0", "", None, "dev"):
            self.assertTrue(ks.reads_sealed(v), v)          # unknown -> the folder stays sealed
        for v in ("0.21.91", "v0.21.91", "0.21.9", "0.20.99", "0.8.13"):
            self.assertFalse(ks.reads_sealed(v), v)


class RoundTrip(Base):
    """seal (0.21.92 start) -> downgrade (unseal) -> 0.21.91 runs (raw reads, plain writes) -> upgrade (seal again)."""

    def test_seal_downgrade_unseal_upgrade_seal(self):
        docs = plain_files(self.dir)
        # 0.21.92 starts: sealed
        self.assertIn("rtsp-feeds.json", ks.migrate_state(self.dir))
        self.assertEqual(scan(self.dir, SECRETS), [])
        # the swap to 0.21.91: back in the plain form
        notes = []
        done = ks.unseal_state(self.dir, log=notes.append)
        self.assertEqual(set(done), {"rtsp-feeds.json", "relay-auth.json", "relay-auth.json.bak", "relay-cluster.json", "gif-search.json"})
        self.assertTrue(ks.plain_mode())
        self.assertTrue(any("older than 0.21.92" in n for n in notes), notes)
        for n in notes:
            for s in SECRETS.values():
                self.assertNotIn(s, n)                         # the log names files, never a code
        for name, doc in docs.items():
            self.assertEqual(raw(self.dir, name), doc, name)   # exactly what 0.21.91 wrote
        self.assertNotIn("ksec1:", json.dumps([raw(self.dir, n) for n in docs]))
        # this process keeps running until teardown: its writes stay plain (the older build reads them)
        p = os.path.join(self.dir, "relay-cluster.json")
        ks.write_json(p, dict(docs["relay-cluster.json"], at=2))
        self.assertEqual(raw(self.dir, "relay-cluster.json")["code"], FEDCODE)
        self.assertFalse(ks.needs_migration(p, raw(self.dir, "relay-cluster.json")))
        kr.save_json(os.path.join(self.dir, "relay-auth.json"), docs["relay-auth.json"])
        self.assertEqual(raw(self.dir, "relay-auth.json")["rooms"]["lockd"]["roomKey"], ROOMKEY)
        # 0.21.91 runs (a new process): it reads the codes as they are and writes plain -- a new camera, say
        feeds = raw(self.dir, "rtsp-feeds.json")
        self.assertEqual((feeds["access"], feeds["roomCode"], feeds["feeds"][0]["xsCodes"]["lockd"]), (PUB, MYROOM, LOCKED))
        feeds["feeds"].append({"url": CAMURL2, "keep": True})
        with open(os.path.join(self.dir, "rtsp-feeds.json"), "w", encoding="utf-8") as f:
            json.dump(feeds, f)
        # the upgrade: a fresh 0.21.92 process seals everything again, the new camera's password too
        ks.forget_all()
        ks.configure(self.dir)
        self.assertFalse(ks.plain_mode())
        self.assertIn("rtsp-feeds.json", ks.migrate_state(self.dir))
        allsec = dict(SECRETS, campw2=CAMPW2)
        self.assertEqual(scan(self.dir, allsec), [])
        # ... and every value is intact
        ks.forget_all()
        ks.configure(self.dir)
        p = os.path.join(self.dir, "rtsp-feeds.json")
        got = ks.open_doc(p, raw(self.dir, "rtsp-feeds.json"))
        self.assertEqual([x["url"] for x in got["feeds"]], [CAMURL, CAMURL2])
        self.assertEqual((got["access"], got["roomCode"]), (PUB, MYROOM))
        self.assertEqual(kr.load_json(os.path.join(self.dir, "relay-auth.json"))[0]["rooms"]["lockd"]["roomKey"], ROOMKEY)
        self.assertEqual(kr.load_json(os.path.join(self.dir, "relay-cluster.json"))[0]["code"], FEDCODE)

    def test_reseal_when_the_older_build_was_not_placed(self):
        plain_files(self.dir)
        ks.migrate_state(self.dir)
        ks.unseal_state(self.dir)
        self.assertNotEqual(scan(self.dir, SECRETS), [])
        ks.reseal_state(self.dir)
        self.assertFalse(ks.plain_mode())
        self.assertEqual(scan(self.dir, SECRETS), [])
        ks.write_json(os.path.join(self.dir, "gif-search.json"), {"key": GIPHY, "on": True})   # sealing again
        self.assertEqual(scan(self.dir, {"g": GIPHY}), [])


class FakeResp(io.BytesIO):
    pass


class SwapToOlder(Base):
    """kastr.update_from with the download and the relaunch mocked: the folder is plain only when an older build is
    actually placed."""

    def setUp(self):
        super().setUp()
        self.bin = tempfile.mkdtemp(prefix="kastr092b-")
        self.exe = os.path.join(self.bin, "KASTR.exe" if kastr.WINDOWS else "KASTR")
        with open(self.exe, "wb") as f:
            f.write(b"current build")
        self.payload = b"the older build " * 64
        self.at_relaunch = None
        plain_files(self.dir)
        ks.migrate_state(self.dir)
        self.assertEqual(scan(self.dir, SECRETS), [])
        self.patches = [mock.patch.object(kastr, "state_dir", lambda: self.dir),
                        mock.patch.object(kastr, "exe_path", lambda: self.exe),
                        mock.patch.object(kastr, "_takeover_enabled", lambda: False),
                        mock.patch.object(kastr, "autorun_for_version", lambda theirs: ""),   # never the real sign-in entry
                        mock.patch.object(kastr, "alert_async", lambda *a, **k: None),
                        mock.patch.object(kastr, "relaunch_self", self.relaunch)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.bin, ignore_errors=True)
        super().tearDown()

    def relaunch(self, delay_ms=800, before_exit=None, argv=None, reason="update"):
        self.at_relaunch = scan(self.dir, SECRETS)
        with open(self.exe, "rb") as f:
            self.placed = f.read()
        return True

    def urlopen(self, sha=None, size=None):
        payload = self.payload
        man = {"platforms": {p: {"version": self.theirs, "sha256": sha or hashlib.sha256(payload).hexdigest(),
                                 "size": len(payload) if size is None else size} for p in ("win32", "linux", "darwin")}}

        def fake(url, timeout=None):
            if url.endswith("/api/update/manifest"):
                return FakeResp(json.dumps(man).encode())
            if "/api/update/binary" in url:
                return FakeResp(payload)
            raise AssertionError(url)
        return mock.patch("urllib.request.urlopen", side_effect=fake)

    def run_update(self, theirs, **kw):
        self.theirs = theirs
        with self.urlopen(**kw):
            return kastr.update_from("http://10.0.0.2:8001", theirs, "0.21.92", relaunch_delay_ms=0)

    def test_swap_to_0_21_91_puts_the_folder_back_in_the_plain_form(self):
        self.assertEqual(self.run_update("0.21.91"), "updating")
        self.assertEqual(self.placed, self.payload)                       # the older build is in place
        names = {n for n, _s in self.at_relaunch}
        self.assertTrue({"rtsp-feeds.json", "relay-auth.json", "relay-cluster.json", "gif-search.json"} <= names, self.at_relaunch)
        self.assertEqual(raw(self.dir, "rtsp-feeds.json")["roomCode"], MYROOM)   # what 0.21.91 reads
        self.assertTrue(ks.plain_mode())                                  # teardown's writes stay plain too
        log = text(os.path.join(self.dir, "launch.log"))
        self.assertIn("older than 0.21.92", log)
        for s in SECRETS.values():
            self.assertNotIn(s, log)

    def test_swap_to_a_newer_build_keeps_the_folder_sealed(self):
        for v in ("0.21.92", "0.21.93", "0.22.0"):
            for fn in os.listdir(self.bin):                              # the last run's KASTR.old-<second> copy
                os.remove(os.path.join(self.bin, fn))
            with open(self.exe, "wb") as f:
                f.write(b"current build")
            self.assertEqual(self.run_update(v), "updating", v)
            self.assertEqual(self.at_relaunch, [], v)
            self.assertFalse(ks.plain_mode())

    def test_a_download_that_fails_verification_leaves_the_folder_sealed(self):
        self.assertEqual(self.run_update("0.21.91", sha="0" * 64), "failed")
        self.assertIsNone(self.at_relaunch)
        self.assertEqual(scan(self.dir, SECRETS), [])
        self.assertFalse(ks.plain_mode())
        self.assertEqual(self.run_update("0.21.91", size=3), "failed")    # size mismatch
        self.assertEqual(scan(self.dir, SECRETS), [])
        with open(self.exe, "rb") as f:
            self.assertEqual(f.read(), b"current build")

    def test_a_placement_that_fails_seals_again(self):
        real_replace = os.replace

        def locked(src, dst, *a, **k):
            if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(self.exe)):
                raise PermissionError("locked")
            return real_replace(src, dst, *a, **k)
        with mock.patch.object(kastr.time, "sleep", lambda s: None), mock.patch("os.replace", side_effect=locked):
            self.assertEqual(self.run_update("0.21.91"), "failed")
        self.assertIsNone(self.at_relaunch)
        with open(self.exe, "rb") as f:
            self.assertEqual(f.read(), b"current build")                   # rolled back: this version runs on
        self.assertFalse(ks.plain_mode())
        self.assertEqual(scan(self.dir, SECRETS), [])                      # ... sealed again
        log = text(os.path.join(self.dir, "launch.log"))
        self.assertIn("sealed again", log)

    def test_the_unseal_sits_after_the_checks_and_before_any_swap(self):
        src = text(os.path.join(HERE, "kastr.py"))
        body = src[src.index("def update_from("):src.index("_EXIT_OVERRIDE = [None]")]
        i_size = body.index('raise RuntimeError("size mismatch")')
        i_unseal = body.index("plain_for_older = secrets_for_swap(theirs, mine)")
        i_helper = body.index("swap_via_helper_windows(tmp, target")
        i_take = body.index("takeover_spawn(newexe")
        self.assertTrue(i_size < i_unseal < i_helper < i_take)
        self.assertIn("secrets_swap_failed(theirs)", body[body.index("except Exception as e:"):])


class HandOver(Base):
    """0.21.92 hub <-> 0.21.91 standby: the bundle is plain JSON over the wire either way round."""

    def store(self, d):
        st = kr.AuthStore(d)
        st.set_codes(viewer="labView-7Q2w", publisher=PUB, admin="labAdm-3K8v")
        h = hashlib.sha256((SALT + LOCKED).encode()).hexdigest()
        o, c = kr.register_room(st, {"slug": "lockd", "salt": SALT, "hash": h, "access": PUB, "persistent": True}, "10.0.0.1")
        self.assertEqual(c, 200, o)
        return st, o["roomKey"], h

    def test_a_0_21_92_hub_hands_over_to_a_0_21_91_standby(self):
        st, key, _h = self.store(self.dir)
        self.assertEqual(scan(self.dir, {"k": key}), [])                   # sealed on the hub's disk
        wire = json.loads(json.dumps({"store": st.export_bundle(), "storeVer": st.ver}))   # /api/hub/replica's answer
        self.assertNotIn("ksec1:", json.dumps(wire))                       # nothing a 0.21.91 standby cannot read
        self.assertEqual(wire["store"]["rooms"]["lockd"]["roomKey"], key)
        self.assertTrue(all("salt" in v and "hash" in v for v in wire["store"]["codes"].values() if v))

    def test_a_0_21_91_hub_hands_over_to_a_0_21_92_standby_and_back(self):
        old_dir = tempfile.mkdtemp(prefix="kastr091-")
        try:
            # a 0.21.91 hub: its records are plain on its disk and on the wire
            ks.forget_all()
            ks.configure(old_dir)
            st, key, h = self.store(old_dir)
            ks.unseal_state(old_dir)                                        # ... as 0.21.91 left them
            ks.forget_all()
            wire = json.loads(json.dumps({"store": st.export_bundle(), "storeVer": 3}))
            # the 0.21.92 standby keeps its copy sealed, takes over, and the room's creator still holds the room
            ks.configure(self.dir)
            kr.save_json(os.path.join(self.dir, "hub-replica.json"), wire, backup=False)
            self.assertEqual(scan(self.dir, {"k": key}), [])
            sb = kr.AuthStore(self.dir)
            sb.import_bundle(kr.load_json(os.path.join(self.dir, "hub-replica.json"))[0]["store"])
            sb._save()
            self.assertEqual(scan(self.dir, {"k": key}), [])
            o, c = kr.register_room(sb, {"slug": "lockd", "salt": SALT, "hash": h, "roomKey": key}, "10.0.0.1")
            self.assertEqual(c, 200, o)
            self.assertTrue(sb.check("publisher", PUB))
            # the hand-BACK to the 0.21.91 hub: plain JSON again
            back = json.loads(json.dumps(sb.export_bundle()))
            self.assertNotIn("ksec1:", json.dumps(back))
            self.assertEqual(back["rooms"]["lockd"]["roomKey"], key)
            # a 0.21.91-written replica file (plain) still reads on a 0.21.92 standby
            with open(os.path.join(self.dir, "hub-replica.json"), "w", encoding="utf-8") as f:
                json.dump(wire, f)
            self.assertEqual(kr.load_json(os.path.join(self.dir, "hub-replica.json"))[0]["store"]["rooms"]["lockd"]["roomKey"], key)
        finally:
            shutil.rmtree(old_dir, ignore_errors=True)


class BrowserVault(unittest.TestCase):
    """The page wiring (static: no browser here -- the lab drives a real one)."""

    def read(self, name):
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            return f.read()

    def test_vault_loads_after_prefs_and_before_the_page_modules(self):
        page = self.read("moq-watch-lite.html")
        i_prefs = page.index('<script src="/assets/prefs.js"></script>')
        i_vault = page.index('<script src="/assets/vault.js"></script>')
        i_mod = page.index('<script type="module">')
        self.assertTrue(i_prefs < i_vault < i_mod)
        self.assertEqual(page.count("await window.__kastrVault?.ready;"), 2)
        for name in ("app.html", "index.html", "relay.html", "stats.html"):
            self.assertIn('<script src="/assets/vault.js"></script>', self.read(name), name)
        stats = self.read("stats.html")
        self.assertIn("window.__kastrVault.ready", stats)
        self.assertLess(stats.index("/assets/vault.js"), stats.index('localStorage.getItem("kastr.lastjoin")'))
        app = self.read("app.html")
        self.assertLess(app.index("/assets/prefs.js"), app.index("/assets/vault.js"))
        self.assertIn('"/assets/vault.js"', self.read("kastr_serve.py"))   # precached

    def test_vault_covers_every_code_and_token_key(self):
        js = self.read("assets/vault.js")
        rx = {}
        for name in ("LOCAL", "LOCAL_IF", "SESSION"):
            m = re.search(r"var %s = /(.+?)/;" % name, js)
            self.assertTrue(m, name)
            rx[name] = re.compile(m.group(1))
        for k in ("kastr.lastjoin", "kastr.live", "kastr.personal.10.0.0.2", "kastr.personal.f.0123456789abcdef"):
            self.assertTrue(rx["LOCAL"].match(k), k)
        for k in ("kastr.personal.people", "kastr.theme", "kastr.lastjoin.x", "kastr.fleet.h"):
            self.assertFalse(rx["LOCAL"].match(k), k)
        for k in ("kastr.rtsp.history", "kastr.rtsp.persist", "kastr.relay.history"):
            self.assertTrue(rx["LOCAL_IF"].match(k), k)
        for k in ("kastr.rejoin", "kastr.watchcodes", "kastr.invite", "kastr.access", "kastr.auth.http://h:4443",
                  "kastr.browse.http://h:4443", "kastr.stats.browse.http://h:4443"):
            self.assertTrue(rx["SESSION"].match(k), k)
        self.assertFalse(rx["SESSION"].match("kastr.spotlit"))
        self.assertIn('generateKey({ name: "AES-GCM", length: 256 }, false', js)   # non-extractable
        self.assertIn('indexedDB.open("kastr-vault"', js)

    def test_the_mirror_and_the_server_keep_the_wrapped_form(self):
        w = "kv1:" + "A" * 40 + "_-x"
        self.assertEqual(kastr_serve._prefs_clean_value("kastr.lastjoin", w), w)
        self.assertEqual(kastr_serve.prefs_filter({"kastr.lastjoin": w}).get("kastr.lastjoin"), w)
        plain = json.dumps({"room": "lockd", "code": LOCKED, "access": PUB})
        self.assertNotIn(LOCKED, kastr_serve._prefs_clean_value("kastr.lastjoin", plain) or "")   # the old scrub still holds
        self.assertIn(r"if (/^kv1:[A-Za-z0-9_-]+$/.test(value)) return value;", self.read("assets/prefs.js"))

    def test_line_endings(self):
        for name, crlf in (("assets/vault.js", False), ("assets/prefs.js", False), ("assets/asi-brand.js", True),
                           ("moq-watch-lite.html", True), ("stats.html", True), ("app.html", True), ("index.html", True),
                           ("relay.html", True), ("kastr.py", True), ("kastr_serve.py", True), ("kastr_secret.py", False),
                           ("tests/test_release_0_21_92_downgrade.py", False)):
            with open(os.path.join(HERE, name), "rb") as f:
                data = f.read()
            n_crlf = data.count(b"\r\n")
            n_lf = data.count(b"\n") - n_crlf
            self.assertEqual(n_lf if crlf else n_crlf, 0, name)


if __name__ == "__main__":
    unittest.main()
