# -*- coding: utf-8 -*-
"""v0.21.89 LAUNCH SET-UP. Kenton: "On launch, have people set their 'my room' and messages up if they haven't already."
REQUIRED (no "Not now"): once a PERSON has joined a room with an access code, one card over the whole page until My room and
Messages work on this device -- a brand-new person makes My room (name from the profile, the code twice, 8 characters at least),
a name that already has a My room enters its code (it's them on another device -- or someone else's: change the name), a code
shorter than 8 picks a longer one (the 0.21.88 setup-with-a-new-code path), a key locked with an earlier code asks for it.
Never a camera box, a relay-only machine, a viewer-only display, the Lobby, an invite-link or My room guest; never blocking when
Messages cannot be reached (a quiet line instead, asked again once the hub answers). The code is kept nowhere new."""
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class Card(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        js = _read(os.path.join("assets", "kastr-msg.js"))
        cls.js = js
        cls.gate = js[js.index("// ---- 0.21.89 (Kenton: \"On launch"):js.index("// ---- wiring")]
        cls.page = _read("moq-watch-lite.html")

    def test_required_and_which_steps(self):
        g = self.gate
        self.assertIn('const GATE_STATES = new Set(["noroom", "needcode", "short", "rekey"]);', g)
        code = "\n".join(ln for ln in g.splitlines() if not ln.strip().startswith("//"))
        self.assertNotIn("Not now", code)                                    # no way past it
        self.assertIn('if (e.key === "Escape") e.preventDefault();   // required: Esc does not dismiss it', g)
        self.assertNotIn('class="close"', g)                                # no close button on the card
        for title in ("Set up My room and messages", "Unlock your messages", "Pick a longer My room code", "Enter your earlier My room code"):
            self.assertIn(title, g)
        self.assertIn("already has a My room on this hub. If it\\u2019s yours, enter your My room code", g)   # name taken / another device
        self.assertIn("Forgot your code? A fleet admin can reset your My room \\u2014 your message history would be lost.", g)
        self.assertIn('data-a="name">Change name', g)

    def test_never_blocks_when_messages_cannot_be_reached(self):
        g = self.gate
        self.assertIn('down: "My room and messages will be set up when the hub is reachable"', g)
        self.assertIn('error: "My room and messages will be set up when the hub is reachable"', g)
        self.assertIn("old:", g)
        # only those four states block; nocrypto / blocked / down / old / error never do
        for st in ("nocrypto", "blocked", "down", "old", "error"):
            self.assertNotIn('"' + st + '"', g.split("const GATE_STATES")[1].split(";")[0])
        self.assertIn("setInterval(gateTick, 1000);", g)                    # asked again once the hub answers (init every 30 s)

    def test_who_is_asked(self):
        g, p = self.gate, self.page
        self.assertIn("if (!K.allowed() || !(K.person?.() ?? false)) return false;", g)
        self.assertIn('person: () => { try { return kmsgModeKnown && !isPublisherMode() && PAGE_MODE !== "relay" && !isViewerMode(); } catch { return false; } },', p)
        self.assertIn("pageModeReady.then(() => { kmsgModeKnown = true; });", p)
        # msgAllowed (0.21.88): joined, not the Lobby, a secured relay's member token, never a guest
        self.assertIn("const msgAllowed = () => { try { return joinState === \"joined\" && !inLobby() && authSecured && !!authTokens?.member && !authGuest && !(inviteGet() && !authAccessCode); } catch { return false; } };", p)

    def test_waits_for_other_cards_and_keyboard(self):
        g, p = self.gate, self.page
        self.assertIn("if (!gateOn() && K.busyUI?.()) return;", g)
        for part in ('joinState !== "joined"', 'shown("joinGate")', 'shown("kConfirm")', 'shown("profilePop")', 'shown("kMyRoom")', 'shown("kRcAsk")'):
            self.assertIn(part, p)
        self.assertIn('if (e.key === "Enter" && e.target?.tagName === "INPUT") { e.preventDefault(); gateGo(); }', g)
        self.assertIn('const first = [...gateEl.querySelectorAll("label.ksf:not([hidden]) input")].find((i) => !i.value);', g)
        for msg in ("Too short \\u2014 a My room code has at least ", "The two codes don\\u2019t match.", "That isn\\u2019t the My room code of "):
            self.assertIn(msg, g)
        # below the yes/no question and the remote-control prompts (an invite's "Leave and join?" still shows over it)
        self.assertIn("#kSetup { position:fixed; inset:0; z-index:130;", p)
        self.assertIn("#kConfirm { position:fixed; inset:0; z-index:140;", p)

    def test_the_code_is_kept_nowhere_new(self):
        g, p = self.gate, self.page
        self.assertNotIn("localStorage", g)
        self.assertNotIn("sessionStorage", g)
        self.assertNotIn("idbPut(\"meta\"", g)
        # My room is remembered as the My room dialog does (unchanged: slug, name, code under kastr.personal.<relay host>)
        # (0.21.91: under the FLEET's key -- the same record, now with the fleet id beside it)
        self.assertIn('if (k) { if (p) localStorage.setItem(k, JSON.stringify({ slug: p.slug, name: p.name || "", code: p.code, fleet: f || undefined })); else localStorage.removeItem(k); }', p)
        self.assertEqual(p.count("personalSave({ slug: d.slug, name: d.name || name, code });"), 3)   # the dialog + roomMake + roomOpen

    def test_launch_paths_untouched(self):
        p = self.page
        # resume-after-update, the silent rejoin and an invite link run before (the card needs a joined page) -- none of them
        # knows about the card
        for fn in ("function resumeCheck()", "async function inviteArrive(inv)"):
            body = p[p.index(fn):p.index(fn) + 4000]
            self.assertNotIn("kSetup", body)
            self.assertNotIn("__msg", body)
        self.assertNotIn("rejoinRec", self.gate)


class Server(unittest.TestCase):
    """The card's server steps are the 0.21.75 My room create / open and the 0.21.88 messages ops: a name that has a My room
    is never taken over by a create with another code."""

    def test_a_create_never_overwrites_someone_elses_room(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        o, c = kr.personal_op(st, {"op": "create", "name": "Tom Taken", "code": "tom-other-0189", "access": "pub-1"}, "10.0.0.5")
        self.assertEqual(c, 200)
        o, c = kr.personal_op(st, {"op": "create", "name": "tom  taken", "code": "someone-else-1", "access": "pub-1"}, "10.0.0.6")
        self.assertEqual((c, o.get("wrong")), (403, True))
        self.assertIsNotNone(st.personal_check("Tom Taken", "tom-other-0189")[0])
        o, c = kr.personal_op(st, {"op": "create", "name": "Tom Taken", "code": "tom-other-0189", "access": "pub-1"}, "10.0.0.5")
        self.assertEqual((c, o.get("created")), (200, False))           # it's them: the same code opens it


class EightEverywhere(unittest.TestCase):
    """Kenton: "8 everywhere" -- the hub refuses a NEW or CHANGED My room code shorter than 8 on every path (create, a spoke's
    forwarded create, an admin's reset with a code; messages' setup / recode were 8 already); an existing shorter code still
    opens My room, so nobody is locked out until the card asks for a longer one."""

    def setUp(self):
        self.st = kr.AuthStore(tempfile.mkdtemp())
        self.st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")

    def op(self, body, **kw):
        return kr.personal_op(self.st, dict(body, access="pub-1"), "10.0.0.5", **kw)

    def test_create_and_reset(self):
        self.assertEqual(kr.PERSONAL_CODE_NEW_MIN, 8)
        o, c = self.op({"op": "create", "name": "Nina New", "code": "seven77"})
        self.assertEqual((c, o.get("short"), o.get("codeMin")), (400, True, 8))
        self.assertIsNone(self.st.personal_check("Nina New", "seven77")[0])
        o, c = self.op({"op": "create", "name": "Nina New", "code": "eight888"})
        self.assertEqual((c, o.get("created")), (200, True))
        o, c = kr.personal_op(self.st, {"op": "reset", "name": "Nina New", "code": "short"}, "10.0.0.5", admin=True)
        self.assertEqual((c, o.get("short")), (400, True))
        self.assertIsNotNone(self.st.personal_check("Nina New", "eight888")[0])   # unchanged
        o, c = kr.personal_op(self.st, {"op": "reset", "name": "Nina New", "code": "a-new-code"}, "10.0.0.5", admin=True)
        self.assertEqual(c, 200)
        o, c = kr.personal_op(self.st, {"op": "reset", "name": "Nina New"}, "10.0.0.5", admin=True)   # clear (no code): allowed
        self.assertEqual(c, 200)

    def test_an_existing_short_code_still_opens(self):
        self.op({"op": "create", "name": "Sam Short", "code": "sam-long-01"})
        self.st.personal_reset("Sam Short", "abcd")                          # as made before 0.21.89
        o, c = self.op({"op": "open", "name": "Sam Short", "code": "abcd"})
        self.assertEqual(c, 200)
        o, c = self.op({"op": "create", "name": "Sam Short", "code": "abcd"})   # the dialog's Make with its own code: it opens
        self.assertEqual((c, o.get("created")), (200, False))

    def test_a_spoke_forwards_and_the_hub_refuses(self):
        import os
        hub = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, self.st)
        try:
            fed = kr._mint(hub.key, dict(kr.FEDERATION_CLAIMS, iat=1, exp=4102444800))
            o, c = hub.rooms_fed({"op": "personal", "body": {"op": "create", "name": "Spoke Person", "code": "1234567"}, "vouch": "member"}, "Bearer " + fed)
            self.assertEqual((c, o.get("short")), (400, True))
            o, c = hub.rooms_fed({"op": "personal", "body": {"op": "create", "name": "Spoke Person", "code": "12345678"}, "vouch": "member"}, "Bearer " + fed)
            self.assertEqual(c, 200)
        finally:
            hub.close()

    def test_the_old_dialog_says_the_same(self):
        p = _read("moq-watch-lite.html")
        # 0.21.91: a NEW room still needs 8 (Make creates only with 8+); a shorter passcode can only be an existing room's -> it opens
        self.assertIn('const op = mode === "make" && code.length >= 8 ? "create" : "open";', p)
        self.assertIn("Pick a passcode only you know (8 characters or more;", p)
        self.assertNotIn("(4 characters or more)", p)


if __name__ == "__main__":
    unittest.main()
