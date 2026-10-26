# -*- coding: utf-8 -*-
"""v0.21.88 PRIVATE MESSAGES. Kenton: "I would like to add a private messaging feature. Ability to message people privately
whether online/offline. If offline, send it when back online. Ability to setup group messages. These messages are not tied to
any rooms." + "If a user connects with the same name and enters the same 'my room' password, then they should be able to access
the previous messages."

A person = a name with a My room. One identity key pair per person (ECDH P-256); its private key is kept on the hub WRAPPED
under PBKDF2(My room code) -- any device that proves name + My room code gets the wrap and opens it locally. Messages are
encrypted once (AES-GCM) and the key is wrapped for every reader PERSON (sender included) with ECDH + HKDF. The hub stores
ciphertext only, 90 days; devices pull + ack; a ping rides the people beat. Groups: hub-visible membership, bodies end to end.

The tests below play the BROWSER with Python's `cryptography` -- the same construction the page builds in WebCrypto
(assets/kastr-msg.js) -- and drive kastr_relay.AuthService in-process (a hub; a spoke + hub over loopback sockets)."""
import base64
import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_msg as km  # noqa: E402
import kastr_relay as kr  # noqa: E402
from cryptography.exceptions import InvalidTag  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # noqa: E402
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: E402

ITER = km.MSG_PBKDF2_MIN
b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
unb64 = base64.b64decode
KRIS_CODE, ADA_CODE, BOB_CODE = "kris-code-2026", "ada-secret-99", "bob-pass-1234"


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def tok(svc, room, host, code="pub-1"):
    o, c = svc.token({"room": room, "code": code, "host": host}, "10.0.0.7")
    assert c == 200, (c, o)
    return o["tokens"]["member"]


def wrap_key(code, salt, it):
    return PBKDF2HMAC(hashes.SHA256(), 32, salt, it).derive(code.encode())


def kid_of(pub_raw):
    import hashlib
    return hashlib.sha256(pub_raw).hexdigest()[:16]


class Device:
    """One browser profile: its member token (a room of the fleet), the identities it unlocked (name key -> private key)."""

    def __init__(self, svc, host, room="alpha", code="pub-1"):
        self.svc, self.host = svc, host
        self.tok = tok(svc, room, host, code)
        self.keys = {}     # nk -> {priv, kid, pub}
        self.store = {}    # seq -> decrypted message
        self.cur = 0
        self.peer = "10.1.%d.%d" % (hash(host) % 200, len(host))

    def api(self, body):
        return self.svc.msg_api(body, "Bearer " + self.tok, self.peer)

    # ---- the page's unlock: unlock -> (setup) -> keep the key ----------------------------------------------------------
    def unlock(self, name, code, setup_ok=True, new_code=None):
        o, c = self.api({"op": "unlock", "name": name, "code": code})
        if c != 200:
            return o, c
        if o.get("setup"):
            if not setup_ok:
                return o, c
            priv = ec.generate_private_key(ec.SECP256R1())
            pub = priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
            pk8 = priv.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            salt, iv = os.urandom(16), os.urandom(12)
            nk = km.name_key(name)
            wrapped = AESGCM(wrap_key(new_code or code, salt, ITER)).encrypt(iv, pk8, ("kastr-msg-id-v1|" + nk).encode())
            o2, c2 = self.api({"op": "setup", "name": name, "code": code, "newCode": new_code, "pub": b64(pub), "wrapped": b64(wrapped),
                               "iv": b64(iv), "salt": b64(salt), "iter": ITER})
            if c2 != 200:
                return o2, c2
            self.keys[nk] = {"priv": priv, "kid": kid_of(pub), "pub": pub, "pk8": pk8, "wk": wrap_key(new_code or code, salt, ITER)}
            return o2, c2
        per = o["person"]
        wk = wrap_key(code, unb64(per["salt"]), per["iter"])
        pk8 = AESGCM(wk).decrypt(unb64(per["iv"]), unb64(per["wrapped"]), ("kastr-msg-id-v1|" + per["nk"]).encode())
        priv = serialization.load_der_private_key(pk8, None)
        self.keys[per["nk"]] = {"priv": priv, "kid": per["kid"], "pub": unb64(per["pub"]), "pk8": pk8, "wk": wk}
        return o, c

    # ---- send / pull --------------------------------------------------------------------------------------------------
    def _kk(self, me, their_pub, cid, skid, rkid):
        bits = me.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), their_pub))
        return HKDF(hashes.SHA256(), 32, cid.encode(), ("kastr-msg-wrap-v1|%s|%s" % (skid, rkid)).encode()).derive(bits)

    def send(self, as_name, body, to=None, gid=None, files=None, cid=None):
        nk = km.name_key(as_name)
        me = self.keys[nk]
        cid = cid or b64(os.urandom(12)).replace("+", "-").replace("/", "_").rstrip("=")
        if gid:
            names = [g for g in self.groups_seen.get(gid, {}).get("members", [])] if hasattr(self, "groups_seen") else []
        else:
            names = [to, as_name]
        ko, kc = self.api({"op": "keys", "names": names})
        assert kc == 200, ko
        K, iv = os.urandom(32), os.urandom(12)
        ct = AESGCM(K).encrypt(iv, json.dumps(body).encode(), ("kastr-msg-v1|" + cid).encode())
        wraps = {}
        for rk, row in ko["keys"].items():
            if not row:
                continue
            kk = self._kk(me["priv"], unb64(row["pub"]), cid, me["kid"], row["kid"])
            wiv = os.urandom(12)
            wraps[row["kid"]] = {"iv": b64(wiv), "w": b64(AESGCM(kk).encrypt(wiv, K, None))}
        req = {"op": "send", "as": as_name, "cid": cid, "iv": b64(iv), "ct": b64(ct), "wraps": wraps, "files": files or []}
        if gid:
            req["gid"] = gid
        else:
            req["to"] = to
        return self.api(req)

    def pull(self, names, since=None):
        o, c = self.api({"op": "pull", "as": names, "since": self.cur if since is None else since, "ack": self.cur})
        assert c == 200, o
        self.groups_seen = {g["gid"]: g for g in o["groups"]}
        got = []
        for m in o["msgs"]:
            self.cur = max(self.cur, m["seq"])
            if m.get("kind") == "sys":
                self.store[m["seq"]] = {"sys": m["sys"], "gid": m.get("gid")}
                got.append(self.store[m["seq"]])
                continue
            out = None
            for nk, me in self.keys.items():
                w = (m.get("wraps") or {}).get(me["kid"])
                if not w:
                    continue
                spub = unb64(o["keys"][m["fromKid"]]["pub"])
                kk = self._kk(me["priv"], spub, m["cid"], m["fromKid"], me["kid"])
                K = AESGCM(kk).decrypt(unb64(w["iv"]), unb64(w["w"]), None)
                out = json.loads(AESGCM(K).decrypt(unb64(m["iv"]), unb64(m["ct"]), ("kastr-msg-v1|" + m["cid"]).encode()))
                break
            rec = {"seq": m["seq"], "from": m["fromName"], "body": out, "gid": m.get("gid"), "to": m.get("to")}
            self.store[m["seq"]] = rec
            got.append(rec)
        if o.get("more"):
            got += self.pull(names)[0]
        return got, o


class Base(unittest.TestCase):
    def mkroom(self, svc, name, code):
        o, c = kr.personal_op(svc.store, {"op": "create", "name": name, "code": code, "access": "pub-1"}, "10.0.0.5")
        assert c == 200, o
        return o["slug"]

    def all_bytes(self, root):
        out = b""
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                with open(os.path.join(dp, fn), "rb") as f:
                    out += f.read()
        return out


class Hub(Base):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store(self.dir))
        for n, c in (("Kris Price", KRIS_CODE), ("Ada", ADA_CODE), ("Bob", BOB_CODE), ("Short Code", "abcd")):
            self.mkroom(self.svc, n, c)
        self.kris = Device(self.svc, "kris-desk-1a2b")
        self.ada = Device(self.svc, "ada-laptop-3c4d", room="beta")
        self.bob = Device(self.svc, "web-b0b0b0b0-5e6f", room="gamma")

    def tearDown(self):
        self.svc.close()

    def test_status_setup_and_the_minimum_code(self):
        o, c = self.kris.api({"op": "status", "name": "Kris Price"})
        self.assertEqual((c, o["has"], o["myRoom"], o["unlocked"]), (200, False, True, False))
        o, c = self.kris.api({"op": "status", "name": "Nobody Here"})
        self.assertFalse(o["myRoom"])
        o, c = self.kris.unlock("Kris Price", KRIS_CODE)
        self.assertEqual(c, 200, o)
        o, c = self.kris.api({"op": "status", "name": "kris  PRICE"})          # by name, case and spaces aside
        self.assertTrue(o["has"] and o["unlocked"])
        # a 4-character My room code is too weak to guard a key the hub holds: messages ask for a longer one ...
        d = Device(self.svc, "short-pc-0001")
        o, c = d.unlock("Short Code", "abcd")
        self.assertEqual((c, o.get("short")), (400, True))
        # ... and setting up with a new, longer code changes My room's code too
        o, c = d.unlock("Short Code", "abcd", new_code="a-longer-code")
        self.assertEqual(c, 200, o)
        self.assertTrue(o["recoded"])
        self.assertIsNone(self.svc.store.personal_check("Short Code", "abcd")[0])
        self.assertIsNotNone(self.svc.store.personal_check("Short Code", "a-longer-code")[0])
        # a second setup for the same person is refused (unlock it instead)
        o, c = self.kris.api({"op": "setup", "name": "Kris Price", "code": KRIS_CODE, "pub": "x", "wrapped": "x", "iv": "x", "salt": "x", "iter": ITER})
        self.assertEqual((c, o.get("exists")), (409, True))

    def test_a_wrong_code_neither_unlocks_nor_unwraps(self):
        self.kris.unlock("Kris Price", KRIS_CODE)
        d = Device(self.svc, "thief-pc-0bad")
        o, c = d.api({"op": "unlock", "name": "Kris Price", "code": "kris-code-2025"})
        self.assertEqual((c, o.get("wrong")), (403, True))
        self.assertNotIn("person", o)
        # whoever holds the hub's copy cannot open it with a wrong guess either (AES-GCM refuses)
        per = self.svc._msgr().persons["kris price"]
        with self.assertRaises(InvalidTag):
            AESGCM(wrap_key("kris-code-2025", unb64(per["salt"]), per["iter"])).decrypt(unb64(per["iv"]), unb64(per["wrapped"]),
                                                                                       b"kastr-msg-id-v1|kris price")
        # five wrong codes lock the caller out (the relay's lockout), the right one then waits too
        for _ in range(6):
            o, c = d.api({"op": "unlock", "name": "Kris Price", "code": "guess-%d" % _})
        self.assertEqual(c, 429)
        o, c = d.api({"op": "unlock", "name": "Kris Price", "code": KRIS_CODE})
        self.assertEqual(c, 429)

    def test_offline_delivery_and_a_second_device_reads_the_history(self):
        self.kris.unlock("Kris Price", KRIS_CODE)
        self.ada.unlock("Ada", ADA_CODE)
        # Ada is offline (her page does not pull); Kris writes twice
        for t in ("Are you on site tomorrow?", "Bring the 4K camera"):
            o, c = self.kris.send("Kris Price", {"t": t}, to="Ada")
            self.assertEqual(c, 200, o)
        # Ada comes back: both arrive, decrypted, in order
        got, _ = self.ada.pull(["Ada"])
        self.assertEqual([g["body"]["t"] for g in got], ["Are you on site tomorrow?", "Bring the 4K camera"])
        self.assertEqual({g["from"] for g in got}, {"Kris Price"})
        # Ada's beat had said "pull" (the ping)
        o, c = self.svc.people_api({"op": "beat", "name": "Ada"}, "Bearer " + self.ada.tok, "10.0.0.9")
        self.assertGreater(o.get("msg", 0), 0)
        # a NEW device (Kris on his phone, web page) with name + My room code reads everything, sent messages included
        phone = Device(self.svc, "web-c0ffee00-77aa", room="delta")
        o, c = phone.unlock("Kris Price", KRIS_CODE)
        self.assertEqual(c, 200, o)
        self.assertEqual(phone.keys["kris price"]["kid"], self.kris.keys["kris price"]["kid"])   # the same identity
        got, o = phone.pull(["Kris Price"])
        self.assertEqual([g["body"]["t"] for g in got], ["Are you on site tomorrow?", "Bring the 4K camera"])
        # Kris's first device hears about the new one ("a new device unlocked your messages")
        _, o = self.kris.pull(["Kris Price"])
        self.assertEqual([(n["host"], n["kind"]) for n in o["notes"]["kris price"]], [("web-c0ffee00-77aa", "device")])
        # Ada answers; both of Kris's devices get it
        self.ada.send("Ada", {"t": "Yes, 7am"}, to="Kris Price")
        self.assertEqual([g["body"]["t"] for g in self.kris.pull(["Kris Price"])[0]], ["Yes, 7am"])
        self.assertEqual([g["body"]["t"] for g in phone.pull(["Kris Price"])[0]], ["Yes, 7am"])

    def test_the_hub_never_holds_plaintext_or_the_private_key(self):
        self.kris.unlock("Kris Price", KRIS_CODE)
        self.ada.unlock("Ada", ADA_CODE)
        secret = "the gate code is 4471 -- burn after reading"
        pic = os.urandom(2000) + b"PNG-PLAINTEXT-MARKER" + os.urandom(2000)
        fk, fiv = os.urandom(32), os.urandom(12)
        o, c = self.svc.msg_file_post(AESGCM(fk).encrypt(fiv, pic, None), {"as": ["Kris Price"]}, "Bearer " + self.kris.tok)
        self.assertEqual(c, 200, o)
        o, c = self.kris.send("Kris Price", {"t": secret, "files": [{"fid": o["fid"], "name": "gate.png", "type": "image/png",
                                                                     "k": b64(fk), "iv": b64(fiv), "size": len(pic)}]}, to="Ada",
                              files=[o["fid"]])
        self.assertEqual(c, 200, o)
        self.svc._msgr().flush()
        blob = self.all_bytes(self.dir)
        self.assertNotIn(secret.encode(), blob)
        self.assertNotIn(b"PNG-PLAINTEXT-MARKER", blob)
        for dev, code in ((self.kris, KRIS_CODE), (self.ada, ADA_CODE)):
            for k in dev.keys.values():
                self.assertNotIn(k["pk8"], blob)                     # the private key (PKCS#8 DER)
                self.assertNotIn(b64(k["pk8"]).encode(), blob)
                self.assertNotIn(k["wk"], blob)                      # the code-derived wrapping key
                self.assertNotIn(b64(k["wk"]).encode(), blob)
            self.assertNotIn(code.encode(), blob)                    # nor the My room code itself
        # yet Ada reads both
        got, _ = self.ada.pull(["Ada"])
        self.assertEqual(got[0]["body"]["t"], secret)
        f = got[0]["body"]["files"][0]
        data, code = self.svc.msg_file_get({"id": [f["fid"]]}, "Bearer " + self.ada.tok)
        self.assertEqual(code, 200)
        self.assertEqual(AESGCM(unb64(f["k"])).decrypt(unb64(f["iv"]), data, None), pic)
        # someone who is not a reader gets nothing
        self.bob.unlock("Bob", BOB_CODE)
        self.assertEqual(self.svc.msg_file_get({"id": [f["fid"]]}, "Bearer " + self.bob.tok)[1], 403)
        self.assertEqual(self.bob.pull(["Bob"])[0], [])

    def test_groups(self):
        for d, n, c in ((self.kris, "Kris Price", KRIS_CODE), (self.ada, "Ada", ADA_CODE), (self.bob, "Bob", BOB_CODE)):
            d.unlock(n, c)
        o, c = self.kris.api({"op": "gcreate", "as": "Kris Price", "name": "Site crew", "members": ["Ada", "Bob"]})
        self.assertEqual(c, 200, o)
        gid = o["gid"]
        self.kris.pull(["Kris Price"])
        o, c = self.kris.send("Kris Price", {"t": "Crew: 7am at the gate"}, gid=gid)
        self.assertEqual(c, 200, o)
        for d, n in ((self.ada, "Ada"), (self.bob, "Bob")):
            got, o = d.pull([n])
            self.assertEqual([g["body"]["t"] for g in got if g.get("body")], ["Crew: 7am at the gate"])
            self.assertEqual(o["groups"][0]["name"], "Site crew")
            self.assertEqual(got[0]["sys"]["ev"], "create")
        # only the creator renames / removes; a member may add; anyone may leave
        self.assertEqual(self.ada.api({"op": "grename", "as": "Ada", "gid": gid, "name": "x"})[1], 403)
        self.assertEqual(self.ada.api({"op": "gremove", "as": "Ada", "gid": gid, "member": "Bob"})[1], 403)
        self.mkroom(self.svc, "Cy", "cy-code-1234")
        cy = Device(self.svc, "cy-pc-0c0c")
        cy.unlock("Cy", "cy-code-1234")
        o, c = self.ada.api({"op": "gadd", "as": "Ada", "gid": gid, "members": ["Cy"]})
        self.assertEqual(c, 200, o)
        got, _ = cy.pull(["Cy"])
        self.assertEqual([g["body"] for g in got if "body" in g], [])          # nothing from before Cy joined (no key for Cy)
        self.assertEqual([g["sys"]["ev"] for g in got if "sys" in g], ["add"])
        self.ada.pull(["Ada"])
        self.ada.send("Ada", {"t": "Welcome Cy"}, gid=gid)
        self.assertEqual([g["body"]["t"] for g in cy.pull(["Cy"])[0] if g.get("body")], ["Welcome Cy"])
        self.bob.pull(["Bob"])                                       # Bob reads what he had, then leaves
        self.assertEqual(self.bob.api({"op": "gleave", "as": "Bob", "gid": gid})[1], 200)
        self.kris.pull(["Kris Price"])
        o, c = self.kris.send("Kris Price", {"t": "Bob left"}, gid=gid)
        self.assertEqual(c, 200, o)
        self.assertEqual([g for g in self.bob.pull(["Bob"])[0] if g.get("body")], [])   # gone: no more
        o, c = self.bob.send("Bob", {"t": "still here?"}, gid=gid)
        self.assertEqual(c, 403)
        self.assertEqual(self.kris.api({"op": "grename", "as": "Kris Price", "gid": gid, "name": "Gate crew"})[1], 200)
        self.assertEqual(self.ada.api({"op": "gdelete", "as": "Ada", "gid": gid})[1], 403)
        self.assertEqual(self.kris.api({"op": "gdelete", "as": "Kris Price", "gid": gid})[1], 200)
        self.assertFalse(any(e.get("gid") == gid for e in self.svc._msgr().msgs.values()))
        _, o = self.ada.pull(["Ada"])
        self.assertTrue([g for g in o["groups"] if g["gid"] == gid][0]["deleted"])
        # a group of people without a messaging key is refused (they are greyed in the page)
        o, c = self.kris.api({"op": "gcreate", "as": "Kris Price", "name": "y", "members": ["Nobody Here"]})
        self.assertEqual((c, o.get("nokey")), (409, ["Nobody Here"]))

    def test_ninety_days(self):
        self.kris.unlock("Kris Price", KRIS_CODE)
        self.ada.unlock("Ada", ADA_CODE)
        o, c = self.svc.msg_file_post(b"x" * 100, {"as": ["Kris Price"]}, "Bearer " + self.kris.tok)
        fid = o["fid"]
        self.kris.send("Kris Price", {"t": "old"}, to="Ada", files=[fid])
        m = self.svc._msgr()
        self.assertEqual(len(m.msgs), 1)
        n = m.sweep(time.time() + km.MSG_KEEP_S - 3600)
        self.assertEqual(n, (0, 0))
        n = m.sweep(time.time() + km.MSG_KEEP_S + 60)
        self.assertEqual(n, (1, 1))
        self.assertEqual(os.listdir(os.path.join(self.dir, "messages", "m")), [])
        self.assertEqual(os.listdir(os.path.join(self.dir, "messages", "f")), [])
        # an upload no message took is gone after an hour
        o, c = self.svc.msg_file_post(b"y" * 10, {"as": ["Kris Price"]}, "Bearer " + self.kris.tok)
        self.assertEqual(m.sweep(time.time() + 3700), (0, 1))
        # a restart keeps the store (and forgets nothing younger than 90 days)
        self.kris.send("Kris Price", {"t": "new"}, to="Ada")
        m.flush()
        m2 = km.Messenger(self.dir)
        self.assertEqual(len(m2.msgs), 1)
        self.assertIn("kris price", m2.persons)

    def test_changing_the_code_rewraps_the_key(self):
        self.kris.unlock("Kris Price", KRIS_CODE)
        self.ada.unlock("Ada", ADA_CODE)
        self.ada.send("Ada", {"t": "before the change"}, to="Kris Price")
        k = self.kris.keys["kris price"]
        new = "kris-new-code-77"
        salt, iv = os.urandom(16), os.urandom(12)
        wrapped = AESGCM(wrap_key(new, salt, ITER)).encrypt(iv, k["pk8"], b"kastr-msg-id-v1|kris price")
        o, c = self.kris.api({"op": "recode", "name": "Kris Price", "code": KRIS_CODE, "newCode": new, "wrapped": b64(wrapped),
                              "iv": b64(iv), "salt": b64(salt), "iter": ITER})
        self.assertEqual(c, 200, o)
        self.assertTrue(o["rewrapped"])
        # My room follows; the old code opens nothing
        self.assertIsNotNone(self.svc.store.personal_check("Kris Price", new)[0])
        self.assertIsNone(self.svc.store.personal_check("Kris Price", KRIS_CODE)[0])
        d = Device(self.svc, "kris-laptop-2b2b")
        self.assertEqual(d.unlock("Kris Price", KRIS_CODE)[1], 403)
        o, c = d.unlock("Kris Price", new)
        self.assertEqual(c, 200, o)
        self.assertEqual(d.keys["kris price"]["kid"], k["kid"])
        self.assertEqual([g["body"]["t"] for g in d.pull(["Kris Price"])[0]], ["before the change"])
        # recode needs the old code
        o, c = d.api({"op": "recode", "name": "Kris Price", "code": "nope-nope-nope", "newCode": "zzzzzzzzzz", "wrapped": b64(wrapped),
                      "iv": b64(iv), "salt": b64(salt), "iter": ITER})
        self.assertEqual((c, o.get("wrong")), (403, True))

    def test_admin_removes_a_device(self):
        self.kris.unlock("Kris Price", KRIS_CODE)
        rogue = Device(self.svc, "rogue-pc-0bad")
        rogue.unlock("Kris Price", KRIS_CODE)
        self.assertEqual(self.ada.api({"op": "devices", "name": "Kris Price"})[1], 403)   # not an admin
        adm = Device(self.svc, "admin-pc-7c6d", code="adm-1")
        o, c = adm.api({"op": "devices", "name": "Kris Price"})
        self.assertEqual({r["host"] for r in o["devices"]}, {"kris-desk-1a2b", "rogue-pc-0bad"})
        self.assertEqual(adm.api({"op": "devremove", "name": "Kris Price", "host": "rogue-pc-0bad"})[1], 200)
        _, o = rogue.pull(["Kris Price"])
        self.assertEqual(o["locked"], ["kris price"])
        o, c = rogue.unlock("Kris Price", KRIS_CODE)
        self.assertEqual((c, o.get("blocked")), (403, True))
        _, o = self.kris.pull(["Kris Price"])
        self.assertIn(("rogue-pc-0bad", "removed"), [(n["host"], n["kind"]) for n in o["notes"]["kris price"]])
        self.assertEqual(adm.api({"op": "devallow", "name": "Kris Price", "host": "rogue-pc-0bad"})[1], 200)
        self.assertEqual(rogue.unlock("Kris Price", KRIS_CODE)[1], 200)

    def test_lobby_and_invite_guests_cannot_message(self):
        lob = tok(self.svc, "main", "lobby-pc-1111")
        o, c = self.svc.msg_api({"op": "status", "name": "Kris Price"}, "Bearer " + lob, "10.0.0.3")
        self.assertEqual(c, 403)
        self.assertEqual(self.svc.msg_api({"op": "status"}, "", "10.0.0.3")[1], 403)

    def test_reads_ticks_and_the_ping(self):
        self.kris.unlock("Kris Price", KRIS_CODE)
        self.ada.unlock("Ada", ADA_CODE)
        o, c = self.kris.send("Kris Price", {"t": "hi"}, to="Ada")
        seq = o["seq"]
        o, c = self.kris.api({"op": "ticks", "as": "Kris Price", "names": ["Ada"]})
        self.assertEqual(o["ticks"]["ada"], {"d": 0, "r": 0})
        self.ada.pull(["Ada"])
        self.ada.pull(["Ada"])                                       # the ack rides the next pull
        self.assertEqual(self.ada.api({"op": "read", "as": "Ada", "conv": "p:kris price", "seq": seq})[1], 200)
        o, c = self.kris.api({"op": "ticks", "as": "Kris Price", "names": ["Ada"]})
        self.assertEqual(o["ticks"]["ada"], {"d": seq, "r": seq})
        # Ada's other device learns the read mark on its next pull
        tab = Device(self.svc, "web-ada00000-1234", room="beta")
        tab.unlock("Ada", ADA_CODE)
        _, o = tab.pull(["Ada"])
        self.assertEqual(o["reads"]["ada"], {"p:kris price": seq})
        # someone who never unlocked Ada cannot act as Ada
        self.assertEqual(self.bob.api({"op": "read", "as": "Ada", "conv": "p:kris price", "seq": seq})[1], 403)
        self.assertEqual(self.bob.api({"op": "send", "as": "Ada", "to": "Kris Price", "cid": "abcdefgh12",
                                                     "iv": b64(os.urandom(12)), "ct": b64(b"x" * 40), "wraps": {}})[1], 403)

    def test_a_stale_key_list_is_refused(self):
        self.kris.unlock("Kris Price", KRIS_CODE)
        self.ada.unlock("Ada", ADA_CODE)
        o, c = self.kris.api({"op": "send", "as": "Kris Price", "to": "Ada", "cid": "abcdefgh12", "iv": b64(os.urandom(12)),
                              "ct": b64(os.urandom(40)), "wraps": {}})
        self.assertEqual(c, 409)
        self.assertEqual(sorted(o["stale"]), ["Ada", "Kris Price"])
        o, c = self.kris.send("Kris Price", {"t": "x"}, to="Nobody Here")
        self.assertEqual((c, o.get("nokey")), (409, True))


class Federation(Base):
    """A page on a spoke: everything goes to the hub; the spoke counts wrong codes; the ping comes back on the long-poll."""

    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hdir = tempfile.mkdtemp()
        self.sdir = tempfile.mkdtemp()
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store(self.hdir))
        self.base = ["http://127.0.0.1:%d" % self.hub.httpd.server_address[1]]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(self.sdir), hub=lambda: self.base[0], fed_token=lambda: self.fed)
        for n, c in (("Kris Price", KRIS_CODE), ("Ada", ADA_CODE)):
            o, cc = self.hub.rooms_fed({"op": "personal", "body": {"op": "create", "name": n, "code": c}, "vouch": "member"}, "Bearer " + self.fed)
            assert cc == 200, o

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def test_spoke_pages_message_through_the_hub(self):
        kris = Device(self.spoke, "kris-desk-1a2b")                 # Kris's page is on the spoke
        ada = Device(self.hub, "ada-laptop-3c4d", room="beta")      # Ada's on the hub
        o, c = kris.unlock("Kris Price", KRIS_CODE)
        self.assertEqual(c, 200, o)
        ada.unlock("Ada", ADA_CODE)
        self.assertIn("kris price", self.hub._msgr().persons)
        self.assertNotIn("_messenger", self.spoke.__dict__)          # nothing is kept on the spoke
        # a picture through the spoke (raw ciphertext forwarded to the hub)
        pic = os.urandom(300000)
        fk, fiv = os.urandom(32), os.urandom(12)
        o, c = self.spoke.msg_file_post(AESGCM(fk).encrypt(fiv, pic, None), {"as": ["Kris Price"]}, "Bearer " + kris.tok)
        self.assertEqual(c, 200, o)
        fid = o["fid"]
        o, c = kris.send("Kris Price", {"t": "photo of the gate", "files": [{"fid": fid, "k": b64(fk), "iv": b64(fiv)}]}, to="Ada", files=[fid])
        self.assertEqual(c, 200, o)
        got, _ = ada.pull(["Ada"])
        self.assertEqual(got[0]["body"]["t"], "photo of the gate")
        data, code = self.hub.msg_file_get({"id": [fid]}, "Bearer " + ada.tok)
        self.assertEqual(AESGCM(fk).decrypt(fiv, data, None), pic)
        # Ada answers; Kris's spoke hears the ping on the long-poll and his beat there says "pull"
        ada.send("Ada", {"t": "got it"}, to="Kris Price")
        self.spoke.personal_mirror_apply(self.hub.bans_for_spoke("Bearer " + self.fed)[0])
        o, c = self.spoke.people_api({"op": "beat", "name": "Kris Price"}, "Bearer " + kris.tok, "10.0.0.9")
        self.assertGreater(o.get("msg", 0), 0)
        self.assertEqual([g["body"]["t"] for g in kris.pull(["Kris Price"])[0]], ["photo of the gate", "got it"])
        # a picture fetched through the spoke
        data, code = self.spoke.msg_file_get({"id": [fid]}, "Bearer " + kris.tok)
        self.assertEqual((code, AESGCM(fk).decrypt(fiv, data, None) == pic), (200, True))
        # wrong codes count at the spoke (where the person is)
        thief = Device(self.spoke, "thief-pc-0bad")
        for i in range(6):
            o, c = thief.api({"op": "unlock", "name": "Ada", "code": "guess-%d" % i})
        self.assertEqual(c, 429)
        # the hub goes dark: the page hears it (and its message waits in its outbox)
        self.base[0] = "http://127.0.0.1:9"
        o, c = kris.api({"op": "pull", "as": ["Kris Price"], "since": 0})
        self.assertEqual((c, o.get("hubDown")), (503, True))


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = _read("moq-watch-lite.html")
        cls.js = _read(os.path.join("assets", "kastr-msg.js"))
        cls.serve = _read("kastr_serve.py")

    def test_wiring(self):
        self.assertIn('id="msgBtn"', self.page)
        self.assertIn('id="msgPanel"', self.page)
        self.assertIn('<script type="module" src="/assets/kastr-msg.js"></script>', self.page)
        self.assertIn('"/api/msg", "/api/msg/file"', self.serve)
        self.assertIn('"/assets/kastr-msg.js"', self.serve)
        self.assertIn("msg: { pop: document.getElementById(\"msgPanel\")", self.page)   # pins like the other panels

    def test_crypto_construction(self):
        js = self.js
        self.assertIn("PBKDF2", js)
        self.assertIn("600000", js)
        self.assertIn('"kastr-msg-id-v1|"', js)
        self.assertIn('"kastr-msg-v1|"', js)
        self.assertIn('"kastr-msg-wrap-v1|"', js)
        self.assertIn('namedCurve: "P-256"', js)
        self.assertIn("indexedDB", js)
        # the private key is imported NON-extractable before it is kept
        self.assertRegex(js, r'importKey\("pkcs8", [^)]*, false, \["deriveBits"\]\)')
        self.assertNotIn("localStorage.setItem(\"kastr.msg.key", js)

    def test_guests_and_the_lobby_get_no_button(self):
        self.assertIn("body.inlobby #msgBtn", self.page)
        self.assertIn("const msgAllowed = () =>", self.page)
        self.assertIn("!authGuest && !(inviteGet() && !authAccessCode)", self.page)   # never an invite-link / My room guest
        self.assertIn("K.allowed()", self.js)


if __name__ == "__main__":
    unittest.main()
