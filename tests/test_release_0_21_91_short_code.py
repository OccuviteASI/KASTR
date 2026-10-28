# -*- coding: utf-8 -*-
"""v0.21.91 URGENT: an existing SHORT My room passcode. Kenton: "If a user already has a short password set and they login, it
asks them to login to 'my room' but it hasn't had them change the password yet, so they aren't able to login with the old
password and can't change to the new password. Thus making it so they can't login."

Root cause: on a device without My room the My room card opens its dialog in "Make" (name + passcode twice), and Make refused
any passcode under 8 characters BEFORE asking the hub -- so a person whose My room was made before 0.21.89 (4-7 characters) could
never type their own passcode there, and never reached "Pick a longer My room code". Now a passcode under 8 can only be an
EXISTING room's, so it opens it (typed once); the hub still makes NEW rooms with 8 or more; Messages then ask for a longer one
with the old passcode remembered (never typed twice), and the new one becomes My room's on every device.

Every path that takes a My room passcode accepts an existing short one: the hub's open / create-of-an-existing-room / token,
Messages' unlock (-> "Pick a longer"), the setup card's unlock step, the fleet take-over (open), the dialog's Open and Make."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

SHORT = "abcd"
NEW = "a-longer-0191"


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class Hub(unittest.TestCase):
    def setUp(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)
        o, c = kr.personal_op(st, {"op": "create", "name": "Sam Short", "code": "temp-long-1", "access": "pub-1"}, "10.0.0.5")
        assert c == 200, o
        self.slug = o["slug"]
        st.personal_reset("Sam Short", SHORT)                  # made before 0.21.89 (4 characters were allowed then)
        self.st = st

    def tearDown(self):
        self.svc.close()

    def op(self, body):
        return kr.personal_op(self.st, dict(body, access="pub-1"), "10.0.0.5")

    def test_the_short_passcode_opens_everywhere_on_the_hub(self):
        self.assertEqual(self.op({"op": "open", "name": "Sam Short", "code": SHORT})[1], 200)
        o, c = self.op({"op": "create", "name": "Sam Short", "code": SHORT})   # Make with the room's own passcode = it opens
        self.assertEqual((c, o.get("created"), o.get("slug")), (200, False, self.slug))
        o, c = self.op({"op": "create", "name": "Nina New", "code": "short1"})  # a NEW room still needs 8
        self.assertEqual((c, o.get("short")), (400, True))
        # My room's own token (the room code) with the short passcode
        o, c = self.svc.token({"room": self.slug, "code": "pub-1", "roomCode": SHORT, "host": "sampc-3c4d"}, "10.0.0.7")
        self.assertEqual(c, 200, o)

    def test_messages_take_the_short_passcode_then_a_longer_one(self):
        tok = self.svc.token({"room": "beta", "code": "pub-1", "host": "sampc-3c4d"}, "10.0.0.7")[0]["tokens"]["member"]
        api = lambda b: self.svc.msg_api(b, "Bearer " + tok, "10.0.0.7")   # noqa: E731
        o, c = api({"op": "status", "name": "Sam Short"})
        self.assertEqual((c, o["myRoom"], o["has"]), (200, True, False))
        o, c = api({"op": "unlock", "name": "Sam Short", "code": SHORT})   # -> the page's "Pick a longer My room code"
        self.assertEqual((c, o.get("setup")), (200, True))
        o, c = api({"op": "setup", "name": "Sam Short", "code": SHORT, "pub": "x", "wrapped": "x", "iv": "x", "salt": "x", "iter": 600000})
        self.assertEqual((c, o.get("short")), (400, True))                 # the short passcode never guards a key
        self.assertIsNotNone(self.st.personal_check("Sam Short", SHORT)[0])   # ... and still opens My room meanwhile


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html")
        cls.js = _read(os.path.join("assets", "kastr-msg.js"))

    def test_the_dialog_opens_with_a_short_passcode(self):
        p = self.p
        h = p[p.index('q(".pmok").onclick = async () => {'):p.index('q(".pmok").onclick = async () => {') + 3000]
        self.assertIn('if (code.length < 4) { say("A personal code has at least 4 characters.", true);', h)
        self.assertIn('const op = mode === "make" && code.length >= 8 ? "create" : "open";', h)
        self.assertIn('if (op === "create" && code !== q(".pmcode2").value)', h)          # typed once when it opens
        self.assertIn("const d = await personalApi({ op, name, code, access: authAccessCode || undefined });", h)
        self.assertNotIn("code.length < cmin", h)
        self.assertIn('if (!mode) mode = p ? "have" : "make";', p)                         # (why: the card opens Make)

    def test_messages_go_to_pick_a_longer_code(self):
        js = self.js
        self.assertIn('if (use.length < S.codeMin) { S.pendingCode = code; setState("short"); return false; }', js)
        self.assertIn("const needOld = st === \"short\" && !(S.pendingCode || K.personal()?.code);", js)   # never typed twice
        self.assertIn('if ((st === "noroom" || st === "short" || st === "mustchange") && c1.length < min)', js)   # the unlock step checks no length
        self.assertIn('window.addEventListener("kastr:personal", () => setTimeout(() => init(true), 200));', js)
        # the fleet take-over opens with the remembered passcode (no length rule)
        a = self.p[self.p.index("async function personalAdopt(f, h)"):self.p.index("async function personalAdopt(f, h)") + 2400]
        self.assertIn('personalApi({ op: "open", name: c.r.name, code: c.r.code })', a)


if __name__ == "__main__":
    unittest.main()
