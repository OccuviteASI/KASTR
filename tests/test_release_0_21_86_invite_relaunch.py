# -*- coding: utf-8 -*-
"""0.21.86 (Kenton: a coworker's invite link "opened the app and then took him straight to the lobby"): the app updated itself
right after the click; the relaunch had no invite (it rides argv once) and the update's resume rejoined the Lobby. Now the
invite survives a relaunch for INVITE_PENDING_S, and on the page a link the person just opened beats a silent rejoin."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_serve as ks  # noqa: E402

TOK = "ki-0a1b2c3d-" + "A" * 40
LINK = "kastr://join?i=%s&room=me-404d1b43f3b8&relay=https%%3A%%2F%%2Fkastr.madlabs.app%%2Frelay" % TOK


class Relaunch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr-inv-")
        self.f = os.path.join(self.tmp, "invite-pending.json")
        ks.INVITE_PENDING[0] = None
        ks.INVITE_FILE[0] = None

    def tearDown(self):
        ks.INVITE_PENDING[0] = None
        ks.INVITE_FILE[0] = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_invite_taken_before_an_update_is_offered_again(self):
        self.assertFalse(ks.invite_pending_restore(self.f))          # first start: nothing
        self.assertTrue(ks.invite_pending_set(LINK))
        self.assertTrue(os.path.exists(self.f))
        got = ks.invite_pending_take()
        self.assertEqual((got["token"], got["room"], got["relay"]), (TOK, "me-404d1b43f3b8", "https://kastr.madlabs.app/relay"))
        self.assertIsNone(ks.invite_pending_take())                   # once per process
        # the update relaunch: a new process
        ks.INVITE_PENDING[0] = None
        self.assertTrue(ks.invite_pending_restore(self.f))
        self.assertEqual(ks.invite_pending_take(), got)

    def test_an_old_one_is_dropped(self):
        ks.INVITE_FILE[0] = self.f
        ks.invite_pending_set(LINK)
        ks.INVITE_PENDING[0] = None
        self.assertFalse(ks.invite_pending_restore(self.f, now=time.time() + ks.INVITE_PENDING_S + 5))
        self.assertFalse(os.path.exists(self.f))
        self.assertIsNone(ks.invite_pending_take())

    def test_junk_is_ignored(self):
        with open(self.f, "w", encoding="utf-8") as fh:
            json.dump({"token": "nope", "room": "x", "at": time.time()}, fh)
        self.assertFalse(ks.invite_pending_restore(self.f))
        with open(self.f, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        self.assertFalse(ks.invite_pending_restore(self.f))


class Page(unittest.TestCase):
    def test_a_link_beats_a_silent_rejoin(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            p = f.read()
        self.assertIn("      rejoinRec = null;\n      try { sessionStorage.removeItem(\"kastr.rejoin\"); } catch {}\n      inviteSet({ token: inv.token, room, at: Date.now() });", p)
        self.assertIn('if (joinState === "joined" && CHANNEL !== room) leaveMeeting();', p)
        self.assertIn("if (CHANNEL !== channelSlug(t.room)) return;   // 0.21.86: an invite link took this rejoin elsewhere", p)
        with open(os.path.join(HERE, "kastr.py"), encoding="utf-8") as f:
            self.assertIn('kastr_serve.invite_pending_restore(os.path.join(state_dir(), "invite-pending.json"))', f.read())


if __name__ == "__main__":
    unittest.main()
