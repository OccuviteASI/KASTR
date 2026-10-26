# -*- coding: utf-8 -*-
"""v0.21.90 PROFILE PHOTOS THAT ALWAYS LOAD. Kenton: "I'm often getting users that have uploaded a photo showing as a broken link
instead of the photo they uploaded."

0.21.86-0.21.89: each page uploaded its photo to ITS relay host's KASTR and announced the URL as that page saw it --
http://localhost:8000 / 127.0.0.1 on the relay machine itself, a site's private address another site cannot reach, http under
an https page -- and deleted the copy when the page closed or changed room. 0.21.90: the HUB keeps ONE photo per person (the
same name identity as messages and All people; kastr_msg.Messenger.photo_*); beats carry the index {key, name, hash, id} --
never a host; every page loads /api/avatar/<id>?v=<hash> from its OWN KASTR (a spoke serves it from a cache it fills from the
hub); hand-over / standby / hand-back carry the store like the messages; a broken photo shows the initials, never an icon."""
import base64
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import types
import unittest
import zlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_msg as km  # noqa: E402
import kastr_relay as kr  # noqa: E402

b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def png(w, h, salt=b""):
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
    raw = b"".join(b"\x00" + bytes([(x * 7 + y) & 255 for x in range(w * 3)]) for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"tEXt", b"lab\x00" + salt) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def jpeg(w, h):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, h, w, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + sof + b"\xff\xda" + b"\x00" * 20 + b"\xff\xd9"


def webp_vp8x(w, h):
    body = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def tok(svc, room, host, code="pub-1", extra=None):
    o, c = svc.token(dict({"room": room, "code": code, "host": host}, **(extra or {})), "10.0.0.7")
    assert c == 200, (c, o)
    return o["tokens"]["member"]


class Sniff(unittest.TestCase):
    def test_types_and_sizes_from_the_bytes(self):
        self.assertEqual(km.photo_sniff(png(40, 30)), ("image/png", 40, 30))
        self.assertEqual(km.photo_sniff(jpeg(512, 384)), ("image/jpeg", 512, 384))
        self.assertEqual(km.photo_sniff(webp_vp8x(256, 200)), ("image/webp", 256, 200))
        for bad in (b"", b"GIF89a....", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"\xff\xd8\xff" + b"\x00" * 4, b"RIFF\x00\x00\x00\x00WEBPXXXX"):
            self.assertIsNone(km.photo_sniff(bad)[0], bad[:12])

    def test_ids_and_versions(self):
        self.assertTrue(km.PID_RE.match(km.photo_pid("carlo bos")))
        self.assertNotEqual(km.photo_pid("carlo bos"), km.photo_pid("carla bos"))
        self.assertNotIn("carlo", km.photo_pid("carlo bos"))          # a URL never carries the name
        self.assertEqual(km.photo_hash(b"abc"), hashlib.sha256(b"abc").hexdigest()[:16])


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.m = km.Messenger(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_one_photo_per_person_by_name(self):
        p1 = png(64, 64, b"one")
        o, c = self.m.photo_set("  Carlo   Bos ", p1, "carlopc-5e6f")
        self.assertEqual((c, o["h"], o["key"], o["id"]), (200, km.photo_hash(p1), "carlo bos", km.photo_pid("carlo bos")))
        data, ctype, h = self.m.photo_get(pid=km.photo_pid("carlo bos"))
        self.assertEqual((data, ctype, h), (p1, "image/png", km.photo_hash(p1)))
        idx = self.m.photo_index()
        self.assertEqual([(r["k"], r["n"], r["h"]) for r in idx["list"]], [("carlo bos", "Carlo Bos", km.photo_hash(p1))])
        pv1 = idx["pv"]
        # the same name from another device (any case) replaces it -- one per person
        p2 = jpeg(300, 300)
        o, c = self.m.photo_set("carlo bos", p2, "carlolap-1111")
        self.assertEqual(c, 200)
        self.assertEqual(self.m.photo_get(pid=km.photo_pid("carlo bos"))[0], p2)
        self.assertNotEqual(self.m.photo_index()["pv"], pv1)
        self.assertEqual(len(self.m.photo_index()["list"]), 1)
        # it is kept on disk with the store (a restart keeps it)
        self.m.flush()
        again = km.Messenger(self.dir)
        self.assertEqual(again.photo_get(pid=km.photo_pid("carlo bos"))[0], p2)

    def test_limits(self):
        self.assertEqual(self.m.photo_set("Ann", b"GIF89a" + b"\x00" * 100, "annpc-1a2b")[1], 415)
        self.assertEqual(self.m.photo_set("Ann", b"<svg/>", "annpc-1a2b")[1], 415)
        self.assertEqual(self.m.photo_set("Ann", png(600, 100), "annpc-1a2b")[1], 413)       # wider than 512
        self.assertEqual(self.m.photo_set("Ann", png(10, 10) + b"\x00" * km.PHOTO_MAX, "annpc-1a2b")[1], 413)
        self.assertEqual(self.m.photo_set("", png(10, 10), "annpc-1a2b")[1], 400)
        self.assertEqual(self.m.photo_set("Ann", png(10, 10), "not a host")[1], 400)
        for i in range(km.PHOTO_RATE[0]):
            self.m.photo_set("Ann", png(10, 10, str(i).encode()), "annpc-1a2b")
        self.assertEqual(self.m.photo_set("Ann", png(10, 10, b"x"), "annpc-1a2b")[1], 429)

    def test_removal_is_a_tombstone_and_the_bytes_go(self):
        p = png(32, 32)
        self.m.photo_set("Olga", p, "olgapc-7b7b")
        o, c = self.m.photo_remove("Olga", "olgapc-7b7b")
        self.assertEqual((c, o["h"]), (200, ""))
        self.assertIsNone(self.m.photo_get(pid=km.photo_pid("olga")))
        self.assertEqual([(r["k"], r["h"]) for r in self.m.photo_index()["list"]], [("olga", "")])   # devices follow the removal
        path = os.path.join(self.dir, "messages", "p", km.photo_hash(p) + ".bin")
        os.utime(path, (time.time() - 3600, time.time() - 3600))
        self.m.sweep()
        self.assertFalse(os.path.exists(path))
        self.m.sweep(now=time.time() + km.PHOTO_KEEP_GONE_S + 60)              # the tombstone itself is forgotten after 90 days
        self.assertEqual(self.m.photo_index()["list"], [])

    def test_who_may_change_whose_photo(self):
        """Before a person sets up messages, any member device under that name; after, only a device that unlocked them (or the
        device that set the current photo) -- an admin always."""
        self.m.photo_set("Kenton Jeffery", png(20, 20, b"a"), "kentonpc-1a2b")
        self.m.persons["kenton jeffery"] = {"name": "Kenton Jeffery", "devices": {"kentonpc-1a2b": {"at": 1, "first": 1},
                                                                                     "kentonlap-2c2c": {"at": 1, "first": 1}}, "blocked": {}}
        self.assertEqual(self.m.photo_set("Kenton Jeffery", png(20, 20, b"b"), "kentonlap-2c2c")[1], 200)   # his other device
        o, c = self.m.photo_set("Kenton Jeffery", png(20, 20, b"c"), "impostor-9e9e")
        self.assertEqual((c, o.get("locked")), (403, True))
        self.assertEqual(self.m.photo_remove("Kenton Jeffery", "impostor-9e9e")[1], 403)
        self.assertEqual(self.m.photo_remove("Kenton Jeffery", "adminpc-0a0a", admin=True)[1], 200)
        self.m.persons["kenton jeffery"]["blocked"] = {"kentonlap-2c2c": 5}
        self.assertEqual(self.m.photo_set("Kenton Jeffery", png(20, 20, b"d"), "kentonlap-2c2c")[1], 403)   # removed by an admin


class HandOver(unittest.TestCase):
    """The photo store moves with the messages store: hand-over (catch_up), the standby's copy, the hand-back."""

    def setUp(self):
        self.d1, self.d2 = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.m1, self.m2 = km.Messenger(self.d1), km.Messenger(self.d2)
        self.p1, self.p2 = png(48, 48, b"hank"), jpeg(400, 400)
        self.m1.photo_set("Hank Hubb", self.p1, "hubpc-3c4d")
        self.m1.photo_set("Carlo Bos", self.p2, "carlopc-5e6f")
        self.m1.photo_set("Olga", png(16, 16), "olgapc-7b7b")
        self.m1.photo_remove("Olga", "olgapc-7b7b")

    def tearDown(self):
        for d in (self.d1, self.d2):
            shutil.rmtree(d, ignore_errors=True)

    def test_catch_up_copies_the_index_and_the_bytes(self):
        _s, _v, tot = km.catch_up(self.m2, self.m1.export, self.m1.file_raw, deadline=30, sleep=lambda s: None)
        self.assertEqual((tot["photos"], tot["missing"]), (3, 0))
        self.assertEqual(self.m2.photo_index()["pv"], self.m1.photo_index()["pv"])   # pages need not re-read anything
        self.assertEqual(self.m2.photo_get(pid=km.photo_pid("hank hubb"))[0], self.p1)
        self.assertEqual(self.m2.photo_get(pid=km.photo_pid("carlo bos"))[0], self.p2)
        self.assertIsNone(self.m2.photo_get(pid=km.photo_pid("olga")))             # the removal came too
        # idempotent
        _s, _v, again = km.catch_up(self.m2, self.m1.export, self.m1.file_raw, sleep=lambda s: None)
        self.assertEqual((again["photos"], again["bytes"]), (0, 0))

    def test_the_newer_photo_wins_both_ways_and_bytes_are_checked(self):
        km.catch_up(self.m2, self.m1.export, self.m1.file_raw, sleep=lambda s: None)
        time.sleep(1.05)
        p3 = png(64, 64, b"newer on the new hub")
        self.m2.photo_set("Hank Hubb", p3, "hubpc-3c4d")
        self.m2.merge(self.m1.export(0))                                     # a hand-back of the stale copy
        self.assertEqual(self.m2.photo_get(pid=km.photo_pid("hank hubb"))[0], p3)
        self.m1.merge(self.m2.export(0))                                     # the old side takes the newer one
        self.assertEqual(self.m1.missing_files(), ["p-" + km.photo_hash(p3)])
        self.assertFalse(self.m1.file_store("p-" + km.photo_hash(p3), b"not the photo"))   # bytes that do not hash to it
        self.assertFalse(self.m1.file_store("p-" + km.photo_hash(b"x" * 10), b"x" * 10))   # a photo nobody has
        self.assertTrue(self.m1.file_store("p-" + km.photo_hash(p3), p3))
        self.assertEqual(self.m1.photo_get(pid=km.photo_pid("hank hubb"))[0], p3)

    def test_the_standby_endpoint_and_the_hand_back_move_photo_bytes(self):
        hub = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store(self.d1))
        try:
            hub.__dict__["_messenger"] = self.m1
            hub.standby_info = lambda: {"node": "sb-node-01", "name": "standby", "address": "https://10.0.0.9:4443", "secret": "x"}
            fed = kr._mint(hub.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
            base = "http://127.0.0.1:%d" % hub.httpd.server_address[1]
            fake = types.SimpleNamespace(_fed_post=kr.Relay._fed_post, _fed_get_raw=kr.Relay._fed_get_raw)
            export, fetch = kr.Relay._msg_fed_fns(fake, base, fed, "sb-node-01")
            _s, _v, tot = km.catch_up(self.m2, export, fetch, deadline=60, sleep=lambda s: None)
            self.assertEqual((tot["photos"], tot["missing"]), (3, 0))
            self.assertEqual(self.m2.photo_get(pid=km.photo_pid("carlo bos"))[0], self.p2)
            # the hand-back (signed by the main hub) carries photo bytes as "p-<hash>"
            sb = types.SimpleNamespace(auth=hub, _cluster_raw=lambda: {"hub": True, "promoted": {"at": 1, "epoch": 1},
                                                                       "standbyOf": {"secret": "lab-secret-0190"}})
            ts = int(time.time())
            d, c = kr.Relay._standby_api(sb, "handback/msgfile", {"fid": "p-" + km.photo_hash(self.p1), "ts": ts,
                                                                  "sig": kr.standby_sig("lab-secret-0190", ts)})
            self.assertEqual((c, base64.b64decode(d["data"])), (200, self.p1))
        finally:
            hub.close()


class Service(unittest.TestCase):
    """A hub (or a lone relay): the people API and GET /api/avatar/<id>."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store(self.dir))
        self.kenton = tok(self.svc, "tremonton", "kentonpc-1a2b")
        self.hank = tok(self.svc, "tremonton", "hubpc-3c4d")
        self.paul = tok(self.svc, "elsewhere", "paulpc-9a9a")

    def tearDown(self):
        self.svc.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def people(self, body, t):
        return self.svc.people_api(body, "Bearer " + t, "10.0.0.9")

    def get(self, pid, t=None, v=None, trusted=False):
        return self.svc.avatar_get(pid, {"v": [v]} if v else {}, ("Bearer " + t) if t else None, "10.0.0.9", trusted=trusted)

    def test_set_beat_and_get(self):
        p = png(64, 64, b"hank")
        o, c = self.people({"op": "photo", "name": "Hank Hubb", "data": b64(p)}, self.hank)
        self.assertEqual(c, 200, o)
        pid, h = o["id"], o["h"]
        # a 0.21.90 beat ("pv") gets the index; again with that pv: the version only
        o, c = self.people({"op": "beat", "name": "Kenton Jeffery", "pv": ""}, self.kenton)
        self.assertEqual([(r["k"], r["h"], r["id"]) for r in o["photos"]["list"]], [("hank hubb", h, pid)])
        o2, c = self.people({"op": "beat", "name": "Kenton Jeffery", "pv": o["photos"]["pv"]}, self.kenton)
        self.assertEqual(o2["photos"], {"pv": o["photos"]["pv"]})
        # a 0.21.89 page's beat (no pv) is answered as before -- no index
        o3, c = self.people({"op": "beat", "name": "Old Page", "avatar": "http://10.1.2.3:8000/api/files/0123456789abcdef0123456789abcdef"}, self.paul)
        self.assertNotIn("photos", o3)
        # the bytes: a member token of any room; immutable for the right version, revalidated for another
        data, hdrs, c = self.get(pid, self.paul, v=h)
        self.assertEqual((c, data, hdrs["Content-Type"]), (200, p, "image/png"))
        self.assertIn("immutable", hdrs["Cache-Control"])
        data, hdrs, c = self.get(pid, self.paul, v="0" * 16)
        self.assertEqual((c, hdrs["Cache-Control"]), (200, "private, no-cache"))
        self.assertEqual(self.get("f" * 20, self.paul)[2], 404)
        self.assertEqual(self.get("../../etc/passwd", self.paul)[2], 404)

    def test_who_may_see_and_set(self):
        p = png(32, 32)
        self.people({"op": "photo", "name": "Hank Hubb", "data": b64(p)}, self.hank)
        self.people({"op": "photo", "name": "Paul Other", "data": b64(png(30, 30))}, self.paul)
        hpid, ppid = km.photo_pid("hank hubb"), km.photo_pid("paul other")
        self.people({"op": "beat", "name": "Hank Hubb", "pv": ""}, self.hank)       # Hank is in tremonton
        self.people({"op": "beat", "name": "Paul Other", "pv": ""}, self.paul)      # Paul is elsewhere
        self.assertEqual(self.get(hpid)[2], 403)                                       # anonymous: no
        self.assertEqual(self.get(hpid, trusted=True)[2], 200)                         # the relay machine's own page
        lobby = tok(self.svc, kr.LOBBY_SLUG, "lobbypc-5555")
        self.assertEqual(self.get(hpid, lobby)[2], 403)                                # the Lobby: no
        # an invite-link guest of tremonton: the people in tremonton only
        o, c = self.svc.invite_create_api({"room": "tremonton", "ttl": 3600, "by": "lab"}, "Bearer " + self.kenton)
        self.assertEqual(c, 200, o)
        guest = tok(self.svc, "tremonton", "ginapc-4d4d", code="", extra={"invite": o["token"]})
        o, c = self.people({"op": "beat", "name": "Gina Guest", "pv": ""}, guest)
        self.assertEqual([r["k"] for r in o["photos"]["list"]], ["hank hubb"])          # not Paul (not even his name)
        self.assertEqual(self.get(hpid, guest)[2], 200)
        self.assertEqual(self.get(ppid, guest)[2], 403)
        o, c = self.people({"op": "photo", "name": "Gina Guest", "data": b64(png(8, 8))}, guest)
        self.assertEqual(c, 403)                                                       # a guest sets none
        self.assertEqual(self.people({"op": "photo", "name": "Lobby Larry", "data": b64(png(8, 8))}, lobby)[1], 403)
        # Profile removal
        o, c = self.people({"op": "photo", "name": "Hank Hubb", "remove": True}, self.hank)
        self.assertEqual((c, o["h"]), (200, ""))
        self.assertEqual(self.get(hpid, self.paul)[2], 404)
        self.assertEqual(self.people({"op": "photo", "name": "Hank Hubb", "data": "@@@"}, self.hank)[1], 400)


class Federation(unittest.TestCase):
    """A spoke: its pages' photos go to the hub; it serves photos from a cache filled from the hub; the long-poll says when
    the index moved; a guest on the spoke sees the people of their room wherever those beat."""

    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hdir, self.sdir = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store(self.hdir))
        self.base = ["http://127.0.0.1:%d" % self.hub.httpd.server_address[1]]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(self.sdir), hub=lambda: self.base[0], fed_token=lambda: self.fed)

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def test_spoke_and_hub_both_ways(self):
        kenton = tok(self.spoke, "tremonton", "kentonpc-1a2b")    # Kenton's page is on the spoke
        hank = tok(self.hub, "tremonton", "hubpc-3c4d")           # Hank's on the hub (the relay machine itself)
        pk, ph = png(40, 40, b"kenton"), png(50, 50, b"hank")
        o, c = self.spoke.people_api({"op": "photo", "name": "Kenton Jeffery", "data": b64(pk)}, "Bearer " + kenton, "10.0.0.9")
        self.assertEqual(c, 200, o)
        self.assertEqual(self.hub._msgr().photo_get(pid=km.photo_pid("kenton jeffery"))[0], pk)   # kept at the hub
        self.assertFalse(self.spoke._msgr().photos)                                           # never in a spoke's own store
        self.assertTrue(os.path.isfile(os.path.join(self.sdir, "photo-cache", km.photo_hash(pk) + ".bin")))
        self.hub.people_api({"op": "photo", "name": "Hank Hubb", "data": b64(ph)}, "Bearer " + hank, "10.0.0.8")
        # the hub's long-poll carries the index version; the spoke re-reads it at once
        self.spoke.personal_mirror_apply(self.hub.bans_for_spoke("Bearer " + self.fed)[0])
        for _ in range(50):
            pl = self.spoke._pl()
            if pl.photos and any(r["k"] == "hank hubb" for r in pl.photos["list"]):
                break
            time.sleep(0.05)
        o, c = self.spoke.people_api({"op": "beat", "name": "Kenton Jeffery", "pv": ""}, "Bearer " + kenton, "10.0.0.9")
        self.assertEqual(sorted(r["k"] for r in o["photos"]["list"]), ["hank hubb", "kenton jeffery"])
        o, c = self.hub.people_api({"op": "beat", "name": "Hank Hubb", "pv": ""}, "Bearer " + hank, "10.0.0.8")
        self.assertEqual(sorted(r["k"] for r in o["photos"]["list"]), ["hank hubb", "kenton jeffery"])
        # Kenton's spoke serves Hank's photo: fetched from the hub once, then from its cache (even with the hub dark)
        data, hdrs, c = self.spoke.avatar_get(km.photo_pid("hank hubb"), {}, "Bearer " + kenton)
        self.assertEqual((c, data), (200, ph))
        self.base[0] = "http://127.0.0.1:9"
        data, hdrs, c = self.spoke.avatar_get(km.photo_pid("hank hubb"), {"v": [km.photo_hash(ph)]}, "Bearer " + kenton)
        self.assertEqual((c, data), (200, ph))
        self.assertIn("immutable", hdrs["Cache-Control"])
        o, c = self.spoke.people_api({"op": "photo", "name": "Kenton Jeffery", "remove": True}, "Bearer " + kenton, "10.0.0.9")
        self.assertEqual((c, o.get("hubDown")), (503, True))

    def test_a_guest_on_the_spoke_sees_their_rooms_people_on_the_hub(self):
        hank = tok(self.hub, "tremonton", "hubpc-3c4d")
        paul = tok(self.hub, "elsewhere", "paulpc-9a9a")
        for t, n, salt in ((hank, "Hank Hubb", b"h"), (paul, "Paul Other", b"p")):
            self.hub.people_api({"op": "photo", "name": n, "data": b64(png(20, 20, salt))}, "Bearer " + t, "10.0.0.8")
            self.hub.people_api({"op": "beat", "name": n, "pv": ""}, "Bearer " + t, "10.0.0.8")
        member = tok(self.spoke, "tremonton", "kentonpc-1a2b")
        o, c = self.spoke.invite_create_api({"room": "tremonton", "ttl": 3600, "by": "lab"}, "Bearer " + member)
        self.assertEqual(c, 200, o)
        guest = tok(self.spoke, "tremonton", "ginapc-4d4d", code="", extra={"invite": o["token"]})
        o, c = self.spoke.people_api({"op": "beat", "name": "Gina Guest", "pv": ""}, "Bearer " + guest, "10.0.0.9")
        self.assertEqual([r["k"] for r in o["photos"]["list"]], ["hank hubb"])
        self.assertEqual(self.spoke.avatar_get(km.photo_pid("hank hubb"), {}, "Bearer " + guest)[2], 200)
        self.assertEqual(self.spoke.avatar_get(km.photo_pid("paul other"), {}, "Bearer " + guest)[2], 403)
        # the hub learns who beats on the spoke in which room (for its own guests) with the spoke's index refresh
        self.spoke.people_api({"op": "beat", "name": "Kenton Jeffery", "pv": ""}, "Bearer " + member, "10.0.0.9")
        self.spoke._pl().photo_at = 0
        self.spoke._photo_refresh()
        self.assertEqual(self.hub._photo_seen_in("tremonton", {"kenton jeffery", "paul other"}, time.time()), {"kenton jeffery"})

    def test_an_older_hub(self):
        """A hub before 0.21.90 answers an unknown fed op with "bad room": the spoke's pages get no index (initials), a photo
        set says why."""
        self.hub.rooms_fed = lambda p, b: ({"ok": False, "error": "bad room"}, 400)
        orig = self.hub.rooms_fed
        member = tok(self.spoke, "tremonton", "kentonpc-1a2b")
        self.spoke._hub_fed = lambda body, timeout=6: orig(body, None)
        o, c = self.spoke.people_api({"op": "beat", "name": "Kenton Jeffery", "pv": ""}, "Bearer " + member, "10.0.0.9")
        self.assertNotIn("photos", o)
        self.assertTrue(self.spoke._pl().photo_old)
        o, c = self.spoke.people_api({"op": "photo", "name": "Kenton Jeffery", "data": b64(png(8, 8))}, "Bearer " + member, "10.0.0.9")
        self.assertEqual((c, o.get("hubOld")), (501, True))


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = _read("moq-watch-lite.html")
        cls.msg = _read(os.path.join("assets", "kastr-msg.js"))
        cls.serve = _read("kastr_serve.py")

    def test_never_a_host_url_never_a_broken_icon(self):
        p = self.page
        self.assertIn('if (url && !/^(data:image\\/|blob:|kastr-photo:)/.test(url)) url = "";', p)   # a host URL is never drawn
        self.assertIn('img.addEventListener("error", () => { photoBad.add(', p)                      # a failed photo goes ...
        self.assertIn("img.remove(); });   // the initials show, never a broken icon", p)              # ... the initials show
        self.assertIn('img.style.visibility = "hidden"; img.src = src;', p)                            # hidden until it has loaded
        self.assertIn('if (url && photoBad.has(url)) url = "";', p)                                    # never retried this page's life
        self.assertNotIn("avatarUrls.get(x.op) || x.avatar", p)                                       # Everyone online: no record URL
        self.assertIn("const avatarUrls = { get: (k, n) => photoRef(k, n), set() {}, delete() {}, clear() {}", p)

    def test_the_hub_copy_from_the_pages_own_origin(self):
        p = self.page
        self.assertIn('fetch(location.origin + "/api/avatar/" + id + "?v=" + h, { headers: hd })', p)
        self.assertIn('avatar: "", pv: window.__photos?.pv?.() ?? ""', p)                              # the beat names no host
        self.assertIn("window.__photos?.take(d.photos)", p)
        self.assertNotIn('"X-Kastr-Kind": "avatar"', p)                                                # no per-room upload
        self.assertNotIn('keyedAnnouncer("~avatar"', p)                                                # no per-room announce
        self.assertNotIn('addEventListener("pagehide", avatarDrop)', p)                                # nothing deleted on close
        self.assertIn('body: JSON.stringify({ op: "photo", name: myOpName(), ...body })', p)
        self.assertIn("window.__avatarPublish?.({ explicit: true })", p)                               # Profile's Save
        self.assertIn('paintAvatar(av, avatarUrls.get("", x.name));   // 0.21.90: offline people keep their photo', p)
        # the first 0.21.90 launch sends a local photo the hub does not have (migration)
        self.assertIn('else if (L) act = "up";                  // never agreed (the first 0.21.90 launch)', p)

    def test_messages_draw_photos(self):
        self.assertIn('if (!String(key || "").startsWith("g:")) { try { K.photo?.(d, name); } catch {} }', self.msg)
        self.assertIn("photo: (el, name) =>", self.page)
        self.assertIn(".mav img {", self.page)

    def test_serve_routes_the_photo(self):
        s = self.serve
        self.assertIn('if path.startswith("/api/avatar/"):', s)
        self.assertIn("kastr_relay._local_only(self)", s[s.index("def _avatar_get"):s.index("def _probe_codecs")])
        self.assertIn('_p0.startswith("/api/avatar/")', s)                                              # the photo's cache header passes

    def test_line_endings(self):
        for name, crlf in (("moq-watch-lite.html", True), ("kastr_serve.py", True), ("kastr_relay.py", False), ("kastr_msg.py", False),
                           (os.path.join("assets", "kastr-msg.js"), False)):
            with open(os.path.join(HERE, name), "rb") as f:
                raw = f.read()
            if crlf:
                self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)
            else:
                self.assertNotIn(b"\r\n", raw, name)


if __name__ == "__main__":
    unittest.main()
