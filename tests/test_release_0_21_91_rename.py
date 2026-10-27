# -*- coding: utf-8 -*-
"""v0.21.91 A REAL RENAME. Kenton: when someone who already has a My room changes their name, MOVE EVERYTHING to the new name --
their My room (same room, new owner name), messages with history, their photo, All people / People; others see the new name. It
needs the current My room code.

POST /api/msg {op: "rename", name, newName, code, wrapped, iv, salt, iter} (a spoke forwards it like every messages call): the code
is checked against the current name; the new name must be free (no My room, no messaging person, not a name someone changed away
from lately); My room keeps its slug (AuthStore.personal_rename) and the hub keeps an ALIAS old -> new for 90 days -- anything still
addressed to the old name reaches the new one, nobody else takes the old name meanwhile. The messages store moves the person record
(the private key RE-WRAPPED by the device under the new name: the wrap's AES-GCM additional data is the name key), groups, read
marks, cursors, notes, attachments, the photo and every message, and writes "<old> is now <new>" into each conversation."""
import os
import struct
import sys
import tempfile
import time
import unittest
import zlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))
import kastr_msg as km  # noqa: E402
import kastr_relay as kr  # noqa: E402
import test_release_0_21_88_messages as M  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

KRIS, ADA, BOB, SAM = M.KRIS_CODE, M.ADA_CODE, M.BOB_CODE, "abcd"
b64, unb64 = M.b64, M.unb64


def png(color=(200, 30, 30)):
    raw = b"\x00" + bytes(color)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)   # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def rename(dev, old, new, code, rewrap=True):
    """The page's rename: open the hub's wrap with the code (additional data = the OLD name key), wrap the same key again under
    the NEW name key with the same code, then ask."""
    body = {"op": "rename", "name": old, "newName": new, "code": code}
    if rewrap:
        u, c = dev.api({"op": "unlock", "name": old, "code": code})
        per = u.get("person")
        if per:
            wk = M.wrap_key(code, unb64(per["salt"]), per["iter"])
            pk8 = AESGCM(wk).decrypt(unb64(per["iv"]), unb64(per["wrapped"]), ("kastr-msg-id-v1|" + per["nk"]).encode())
            salt, iv = os.urandom(16), os.urandom(12)
            wrapped = AESGCM(M.wrap_key(code, salt, M.ITER)).encrypt(iv, pk8, ("kastr-msg-id-v1|" + km.name_key(new)).encode())
            body.update(wrapped=b64(wrapped), iv=b64(iv), salt=b64(salt), iter=M.ITER)
    o, c = dev.api(body)
    if c == 200:   # the device moves its own copy under the new name
        k = dev.keys.pop(km.name_key(old), None)
        if k:
            dev.keys[km.name_key(new)] = k
    return o, c


class Rename(M.Base):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, M.store(self.dir))
        for n, c in (("Kris Price", KRIS), ("Ada", ADA), ("Bob", BOB), ("Sam Short", "sam-long-0191")):
            self.mkroom(self.svc, n, c)
        self.svc.store.personal_reset("Sam Short", SAM)        # a My room from before 0.21.89 (no messages yet)
        self.slug = self.svc.store.personal_check("Kris Price", KRIS)[0]
        self.kris = M.Device(self.svc, "kris-desk-1a2b")
        self.ada = M.Device(self.svc, "ada-laptop-3c4d", room="beta")
        self.bob = M.Device(self.svc, "web-b0b0b0b0-5e6f", room="gamma")
        for d, n, c in ((self.kris, "Kris Price", KRIS), (self.ada, "Ada", ADA), (self.bob, "Bob", BOB)):
            d.unlock(n, c)
        self.kris.send("Kris Price", {"t": "hello Ada"}, to="Ada")
        self.ada.send("Ada", {"t": "hi Kris"}, to="Kris Price")
        o, c = self.kris.api({"op": "gcreate", "as": "Kris Price", "name": "Crew", "members": ["Ada", "Bob"]})
        self.gid = o["gid"]
        self.kris.pull(["Kris Price"])
        self.kris.send("Kris Price", {"t": "crew note"}, gid=self.gid)
        self.ada.pull(["Ada"]); self.ada.pull(["Ada"])
        self.kris.pull(["Kris Price"]); self.kris.pull(["Kris Price"])
        self.kris.api({"op": "read", "as": "Kris Price", "conv": "p:ada", "seq": 2})
        self.ada.api({"op": "read", "as": "Ada", "conv": "p:kris price", "seq": 1})
        self.pic = png()
        o, c = self.svc._msgr().photo_set("Kris Price", self.pic, "kris-desk-1a2b")
        assert c == 200, o
        self.kid = self.kris.keys["kris price"]["kid"]

    def tearDown(self):
        self.svc.close()

    def test_everything_moves(self):
        o, c = rename(self.kris, "Kris Price", "Kris P", KRIS)
        self.assertEqual((c, o["name"], o["old"]), (200, "Kris P", "Kris Price"), o)
        st, m = self.svc.store, self.svc._msgr()
        # My room: the same room, the new owner name; the old name points at the new one for 90 days
        self.assertEqual(st.personal_check("Kris P", KRIS)[0], self.slug)
        self.assertIsNone(st.personal_check("Kris Price", KRIS)[0])
        self.assertEqual(st.personal_info(self.slug)["owner"], "Kris P")
        a = st.personal_alias("kris price")
        self.assertEqual((a["to"], a["name"]), ("kris p", "Kris P"))
        self.assertAlmostEqual(a["until"] - a["at"], kr.PERSONAL_ALIAS_TTL, delta=2)
        # messages: the person (same key id), groups, reads, cursors, the photo, every message
        self.assertNotIn("kris price", m.persons)
        self.assertEqual(m.persons["kris p"]["kid"], self.kid)
        self.assertEqual(m.groups[self.gid]["members"][0], "kris p")
        self.assertEqual(m.groups[self.gid]["creator"], "kris p")
        self.assertEqual(m.reads["kris p"]["p:ada"], 2)
        self.assertIn("p:kris p", m.reads["ada"])
        self.assertTrue(all("kris price" not in (e.get("who") or []) and e.get("from") != "kris price" and e.get("to") != "kris price"
                            for e in m.msgs.values()))
        self.assertEqual(m.photos["kris p"]["h"], km.photo_hash(self.pic))
        self.assertNotIn("kris price", m.photos)
        self.assertIn("Kris P", [r["n"] for r in m.photo_index()["list"]])
        # Ada pulls: the rename (to move her copy), a line "Kris Price is now Kris P" in the 1:1 and in the group
        got, d = self.ada.pull(["Ada"])
        self.assertIn({"from": "kris price", "to": "kris p", "name": "Kris P"}, [{k: r[k] for k in ("from", "to", "name")} for r in d["renames"]])
        lines = [(g.get("gid"), g["sys"]) for g in got if g.get("sys")]
        self.assertIn((None, {"ev": "renamed", "from": "Kris Price", "name": "Kris P"}), lines)
        self.assertIn((self.gid, {"ev": "renamed", "from": "Kris Price", "name": "Kris P"}), lines)
        # a new device of Ada's reads the whole 1:1 history, now with Kris P
        tab = M.Device(self.svc, "web-ada00000-1234", room="beta")
        tab.unlock("Ada", ADA)
        hist = [(g["from"], g["body"]["t"]) for g in tab.pull(["Ada"])[0] if g.get("body")]
        self.assertIn(("Kris P", "hello Ada"), hist)
        self.assertIn(("Ada", "hi Kris"), hist)
        # Kris on a new device: the NEW name + the same code opens the key (wrapped again under the new name)
        k2 = M.Device(self.svc, "kris-laptop-2b2b")
        o, c = k2.unlock("Kris P", KRIS)
        self.assertEqual((c, k2.keys["kris p"]["kid"]), (200, self.kid))
        self.assertEqual([g["body"]["t"] for g in k2.pull(["Kris P"])[0] if g.get("body")], ["hello Ada", "hi Kris", "crew note"])
        # the old name on an outdated device still unlocks -- and is told about the rename
        k3 = M.Device(self.svc, "kris-old-3c3c")
        o, c = k3.api({"op": "unlock", "name": "Kris Price", "code": KRIS})
        self.assertEqual((c, o["renamed"]["kris price"]["name"]), (200, "Kris P"))
        # nothing of the plaintext or the code on the hub
        m.flush()
        blob = self.all_bytes(os.path.join(self.dir, "messages"))
        self.assertNotIn(b"hello Ada", blob)
        self.assertNotIn(KRIS.encode(), blob)

    def test_an_outdated_device_reaches_the_new_name(self):
        rename(self.kris, "Kris Price", "Kris P", KRIS)
        o, c = self.ada.send("Ada", {"t": "sent to the old name"}, to="Kris Price")   # keys + send by the old name
        self.assertEqual(c, 200, o)
        self.assertEqual(o["renamed"]["kris price"]["key"], "kris p")
        got = [g["body"]["t"] for g in self.kris.pull(["Kris P"])[0] if g.get("body")]
        self.assertIn("sent to the old name", got)
        # Kris's own outdated device acts as the old name: it is him
        o, c = self.kris.api({"op": "read", "as": "Kris Price", "conv": "p:ada", "seq": 5})
        self.assertEqual(c, 200)
        o, c = self.kris.api({"op": "pull", "as": ["Kris Price"], "since": 0})
        self.assertEqual((c, o["renamed"]["kris price"]["key"]), (200, "kris p"))

    def test_the_old_name_is_held_and_taken_names_refused(self):
        rename(self.kris, "Kris Price", "Kris P", KRIS)
        o, c = kr.personal_op(self.svc.store, {"op": "create", "name": "Kris Price", "code": "someone-else-1", "access": "pub-1"}, "10.0.0.9")
        self.assertEqual((c, o.get("held")), (409, True))
        # the old name still opens Kris's My room (90 days) and says so
        o, c = kr.personal_op(self.svc.store, {"op": "open", "name": "Kris Price", "code": KRIS}, "10.0.0.9")
        self.assertEqual((c, o["name"], o.get("renamed")), (200, "Kris P", True))
        # a name with a My room / a messaging person / held for someone else: refused, nothing moves
        o, c = rename(self.bob, "Bob", "Ada", BOB)
        self.assertEqual((c, o.get("taken")), (409, True))
        o, c = rename(self.bob, "Bob", "Kris Price", BOB)
        self.assertEqual((c, o.get("held")), (409, True))
        self.assertIn("bob", self.svc._msgr().persons)
        self.assertIsNotNone(self.svc.store.personal_check("Bob", BOB)[0])
        # a wrong code: refused (and counted)
        o, c = rename(self.bob, "Bob", "Robert", "not-bobs-code", rewrap=False)
        self.assertEqual((c, o.get("wrong")), (403, True))
        # no re-wrapped key: refused (the device must wrap it under the new name)
        o, c = rename(self.bob, "Bob", "Robert", BOB, rewrap=False)
        self.assertEqual((c, o.get("rewrap")), (400, True))
        # back to his own old name: allowed (it was his)
        o, c = rename(self.kris, "Kris P", "Kris Price", KRIS)
        self.assertEqual(c, 200, o)
        self.assertIsNone(self.svc.store.personal_alias("kris price"))
        self.assertEqual(self.svc.store.personal_alias("kris p")["to"], "kris price")

    def test_a_person_without_messages_renames_their_my_room(self):
        sam = M.Device(self.svc, "sam-pc-0101")
        o, c = rename(sam, "Sam Short", "Sam S", SAM, rewrap=False)
        self.assertEqual(c, 200, o)
        self.assertIsNotNone(self.svc.store.personal_check("Sam S", SAM)[0])     # the short code still opens it (8 when changed)

    def test_all_people_shows_only_the_new_name(self):
        now = int(time.time())
        self.svc._hist_note([{"node": "kris-desk-1a2b", "name": "Kris Price", "mode": "full", "at": now - 60, "checkin": True}])
        rename(self.kris, "Kris Price", "Kris P", KRIS)
        names = [r["name"] for r in self.svc._p_all_rows()]
        self.assertIn("Kris P", names)
        self.assertNotIn("Kris Price", names)

    def test_the_hub_hand_over_carries_the_rename(self):
        old_copy = self.svc._msgr().export(0)                              # a copy taken BEFORE the rename (a stale standby)
        rename(self.kris, "Kris Price", "Kris P", KRIS)
        new = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, M.store())
        try:
            m2 = new._msgr()
            m2.merge(old_copy)
            self.assertIn("kris price", m2.persons)
            new.store.import_bundle(self.svc.store.export_bundle())        # the records carry the alias
            self.assertEqual(new.store.personal_alias("kris price")["to"], "kris p")
            m2.merge(self.svc._msgr().export(0))
            self.assertNotIn("kris price", m2.persons)
            self.assertEqual(m2.persons["kris p"]["wrapped"], self.svc._msgr().persons["kris p"]["wrapped"])
            self.assertFalse(any(e.get("from") == "kris price" for e in m2.msgs.values()))
            # a merge of the stale copy again changes nothing back
            m2.merge(old_copy)
            self.assertNotIn("kris price", m2.persons)
            # hand-back: merge_bundle carries the alias too
            third = M.store()
            third.merge_bundle(self.svc.store.export_bundle())
            self.assertEqual(third.personal_alias("kris price")["name"], "Kris P")
        finally:
            new.close()

    def test_through_a_spoke(self):
        hub_key = os.urandom(32)
        hub = kr.AuthService("127.0.0.1", 0, hub_key, 4443, M.store())
        base = ["http://127.0.0.1:%d" % hub.httpd.server_address[1]]
        fed = kr._mint(hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, M.store(), hub=lambda: base[0], fed_token=lambda: fed)
        try:
            hub.rooms_fed({"op": "personal", "body": {"op": "create", "name": "Kris Price", "code": KRIS}, "vouch": "member"}, "Bearer " + fed)
            k = M.Device(spoke, "kris-desk-1a2b")
            self.assertEqual(k.unlock("Kris Price", KRIS)[1], 200)
            o, c = rename(k, "Kris Price", "Kris P", KRIS)
            self.assertEqual(c, 200, o)
            self.assertIn("kris p", hub._msgr().persons)
            thief = M.Device(spoke, "thief-pc-0bad")
            for i in range(6):
                o, c = thief.api({"op": "rename", "name": "Kris P", "newName": "Mine", "code": "guess-%d" % i})
            self.assertEqual(c, 429)                                       # the spoke's lockout counts wrong codes
        finally:
            hub.close()
            spoke.close()


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "assets", "kastr-msg.js"), encoding="utf-8") as f:
            cls.js = f.read()
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            cls.page = f.read()

    def test_the_page_renames(self):
        js = self.js
        self.assertIn('op: "rename"', js)
        self.assertIn('"kastr-msg-id-v1|" + nk', js)                       # the wrap's additional data stays the name key
        self.assertIn("async function renameMe(", js)
        self.assertIn("async function migrateLocal(", js)                  # my own copy moves to the new name
        self.assertIn("function applyRenames(", js)                        # other people's copies follow
        self.assertIn('s.ev === "renamed"', js)
        self.assertIn("Rename your My room and messages to", js)
        self.assertIn("window.__msg?.nameChanged?.(", self.page)          # the Profile asks
        self.assertIn("setProfileName:", self.page)


if __name__ == "__main__":
    unittest.main()
