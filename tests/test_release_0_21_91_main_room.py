# -*- coding: utf-8 -*-
"""v0.21.91 THE MAIN ROOM. Kenton: "Regular people with the Publisher code should start in their 'My room' instead of the lobby.
The lobby should be for those that hit leave in a room or guests, only showing the rooms they're entitled to as a guest. Guests
should only see the lobby and the room they were invited to. The leave button should leave the room, but not logout of KASTR. It
should put them in the lobby instead. There should be an option in the profile menu that lets them choose their preferred main
room. Either Lobby or My room. When joining KASTR or leaving a room, it should go to that preferred room." + "Leave should not
be available in the Lobby."

Decided: Main room = My room (default) or the Lobby (Profile, this device: kastr.mainroom, mirrored to the machine's prefs file);
everyone but a guest (publisher, admin and viewer codes); a launch that knows the name and codes skips the Join room page (it
stays for the first time, a relay switch, a refused / missing code, no My room yet); resume-after-update, the silent rejoin, an
invite link and ?room= still win; Leave goes to the main room (the Lobby when already there) and never logs out; boxes, relay-only
machines and viewer displays are unchanged. Guests: the Lobby and the invited room only -- the page's lists AND the relay host's
room list for a guest's token; a guest who leaves waits in the Lobby (the link mints a presence-only Lobby token) with Join again."""
import os
import re
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

CODES = {"viewer": "view-1", "publisher": "pub-1", "admin": "adm-1"}


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def store(codes=CODES):
    st = kr.AuthStore(tempfile.mkdtemp())
    if codes:
        st.set_codes(**codes)
    return st


def member(svc, room, code="pub-1", host="kenton-ab12", peer="10.0.0.1"):
    o, c = svc.token({"room": room, "code": code, "host": host}, peer)
    assert c == 200, o
    return "Bearer " + o["tokens"]["member"]


def body(src, start, n=6000):
    i = src.index(start)
    return src[i:i + n]


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html")

    def test_the_preference(self):
        p = self.p
        self.assertIn('const MAIN_ROOM_KEY = "kastr.mainroom";', p)
        self.assertIn('const mainPref = () => { try { return localStorage.getItem(MAIN_ROOM_KEY) === "lobby" ? "lobby" : "mine"; } catch { return "mine"; } };', p)
        # the Profile row: My room / Lobby, at once, never for a box, relay-only machine, viewer display or a guest
        self.assertIn('<div class="mainrow" id="profMainRow"><span class="hclbl">Main room</span>', p)
        self.assertIn('<input type="radio" name="profMain" value="mine">My room</label>', p)
        self.assertIn('<input type="radio" name="profMain" value="lobby">Lobby</label>', p)
        self.assertIn("can = !isPublisherMode() && !isViewerMode() && PAGE_MODE !== \"relay\" && !inviteGuest();", p)
        self.assertIn("for (const r of document.querySelectorAll('#profMainRow input[name=\"profMain\"]')) r.addEventListener(\"change\", () => {", p)
        # it survives a browser-profile wipe like the other operator keys (the machine's prefs file)
        self.assertIn("mainroom$", _read(os.path.join("assets", "prefs.js")))

    def test_who_has_a_main_room(self):
        p = self.p
        self.assertIn('const mainPerson = () => !isPublisherMode() && !isViewerMode() && PAGE_MODE !== "relay";', p)
        t = body(p, "function mainTarget(from) {", 600)
        self.assertIn("if (inviteGuest()) return { slug: LOBBY, code: \"\" };", t)
        self.assertIn('if (mainPref() === "mine" && p && from !== p.slug) return { slug: p.slug, code: p.code, personal: true };', t)
        self.assertIn("return { slug: LOBBY, code: \"\" };", t)

    def test_launch_order(self):
        p = self.p
        m = body(p, "async function mainLaunch() {", 5000)
        order = ['if (!mainPerson()) return gate(', 'if (ticket?.room) return gate("a rejoin")', 'if (inviteGet()) return gate("an invite link")',
                 'return gate("a room link")', 'return gate("the first launch here")', 'return gate("no name yet")',
                 "await Promise.race([relayPickDone, mainSleep(8000)]);", "if (await resumeCheck())", "await invitePendingPoll();",
                 'gate("another relay than the last join\'s")', 'gate("no access code saved for this relay")', 'gate("no My room on this device yet")',
                 'const t = { room: tgt.slug, code: tgt.code, access, synthetic: true, main: true, name, micOn: false, vidOn: false };']
        at = [m.index(x) for x in order]
        self.assertEqual(at, sorted(at), "the launch checks run in this order")
        self.assertIn("else mainLaunch();   // 0.21.91", p)
        # resume-after-update says whether it took over (and works under the launch's note)
        self.assertIn("function resumeCheck() {   // 0.21.91: -> a promise of \"it took over\"", p)
        self.assertIn("(joinEls.joinGate.hidden && !mainCovering())", p)
        # the main-room ticket keeps the Join room page away; a failure shows it with the reason
        self.assertIn("joinEls.joinGate.hidden = !!saved.main;", p)
        self.assertIn('if (saved.main && joinState === "prejoin") mainLaunchFailed(saved);', p)
        # the page's own markup never paints the Join room page on such a launch
        self.assertIn('if (l.getItem("kastr.lastjoin") && (l.getItem("kastr.profile") || l.getItem("kastr.operator.name")) && !/[?&]room=/.test(location.search)', p)
        self.assertIn('&& !/invite=/.test(location.hash) && !s.getItem("kastr.invite") && !s.getItem("kastr.rejoin")) g.hidden = true;', p)
        # the Join room page has no close X and no Escape (0.21.89) -- still
        self.assertIn("// 0.21.89 (Kenton: \"remove the x in the corner of the Join room page\", then \"remove escape too\"): the gate is no", p)

    def test_join_room_page_offers_my_room(self):
        p = self.p
        self.assertIn('if (mineOpt) sel.insertBefore(new Option("My room", "__mine"), sel.firstChild);', p)
        self.assertIn('} else if (joinEls.joinChanSel.value === "__mine") {   // 0.21.91: My room, with the code this device keeps for it', p)
        self.assertIn("if (await withinMs(authMint(slug, joinEls.joinAccess.value, pwd), 15000) === JOIN_TIMEOUT)", p)
        self.assertIn("My room did not open with the code this device remembered", p)

    def test_landing_in_my_room_after_setup(self):
        p = self.p
        self.assertIn('mainLand = mainPerson() && !inv && !inviteGuest() && authSecured && mainPref() === "mine" && !personalGet() && !isPersonalSlug(slug);', p)
        t = body(p, "let mainLand = false, mainLandAsked = false;", 2000)
        self.assertIn('if (shown("kSetup") || shown("kMyRoom") || shown("kConfirm") || shown("profilePop")) return;   // the set-up finishes first', t)
        self.assertIn("switchRoom({ slug: p.slug, personal: true }, p.code);", t)
        self.assertIn("personalDialog();", t)   # the Lobby has no Messages card -- My room's own dialog asks there

    def test_leave_goes_to_the_main_room(self):
        p = self.p
        self.assertIn('joinEls.leaveBtn.addEventListener("click", () => { leaveToMain(); });', p)
        self.assertNotIn('joinEls.leaveBtn.addEventListener("click", leaveMeeting);', p)
        t = body(p, "async function leaveToMain() {", 2200)
        self.assertIn("if (!mainPerson()) { leaveMeeting(); return; }", t)   # boxes: the Join room page as before
        self.assertIn("if (CHANNEL === LOBBY) return;", t)
        self.assertIn("window.__publisher?.dropShares?.()", t)
        self.assertIn("await switchRoom(tgt.personal ? { slug: tgt.slug, personal: true } : lobbyRec(), tgt.code);", t)
        self.assertIn('if (joinState === "joined" && CHANNEL === from && tgt.slug !== LOBBY) await switchRoom(lobbyRec(), "");', t)
        self.assertIn("leaveMeeting(); return; }", t)   # only when even the Lobby refused
        # dropShares keeps the camera, a box's RTSP feeds and a slide's video
        self.assertIn('dropShares: () => { let n = 0; for (const a of [...added]) { if (a.kind === "camera" || a.kind === RTSP || a.presVideo) continue; removeSource(a.id); n++; } return n; },', p)
        # forced exits (a kick, a closed room, the guest's ended session, an invite across relays) still take the Join room page,
        # and a person's access code stays for the next launch
        lm = body(p, "function leaveMeeting() {", 2500)
        self.assertIn("if (lj && lj.access && mainPerson()) localStorage.setItem(\"kastr.lastjoin\", JSON.stringify({ room: \"\", code: \"\", access: lj.access, relay: lj.relay || \"\" }));", lm)
        self.assertIn("gateShow();", lm)
        self.assertIn("try { personalLeaveSend(false); } catch {}   // 0.21.78: the owner leaving My room", lm)
        self.assertIn("try { leaveMeeting(); } catch {}", body(p, "function personalEnded(room, info) {", 1200))   # End their session -> the ended screen

    def test_sign_out_is_in_more(self):
        p = self.p
        self.assertIn('<button class="opt" id="optSignOut" type="button" hidden', p)
        s = body(p, 'document.getElementById("optSignOut").addEventListener("click", async () => {', 1200)
        self.assertIn("try { leaveMeeting(); } catch {}", s)                       # the Join room page
        self.assertIn('try { localStorage.removeItem("kastr.lastjoin"); } catch {}', s)   # the next launch asks for a code
        self.assertIn('on = joinState === "joined" && mainPerson();', p)           # a person's KASTR in a room (a box keeps its Leave)

    def test_no_leave_in_the_lobby(self):
        p = self.p
        self.assertIn("#topbar #leaveBtn[hidden] { display:none !important; }", p)
        self.assertIn("try { joinEls.leaveBtn.hidden = joinState !== \"joined\" || (on && !isPublisherMode()); } catch {}", p)
        self.assertIn('joinEls.leaveBtn.hidden = joinState !== "joined" || (readChannel() === LOBBY && !isPublisherMode());   // 0.21.91: no Leave in the Lobby', p)
        self.assertIn("try { paintLobby(); } catch {}   // 0.21.91: no Leave in the Lobby -- at once", p)

    def test_invite_while_in_a_room(self):
        p = self.p
        t = body(p, "async function inviteArrive(inv) {", 5000)
        # every joined page holds a session ticket (the 0.21.86 'silent' branch) -- both branches go straight to the room
        self.assertIn('if (joinState === "joined" && CHANNEL !== room && sameRelay && mainPerson()) await inviteSwitch();   // 0.21.91: Leave never logs out', t)
        self.assertIn('if (joinState === "joined" && !silent && mainPerson() && sameRelay) {', t)
        self.assertIn("await switchRoom(lastChannelList.find((r) => r.slug === room) || { slug: room, personal: isPersonalSlug(room) }, \"\");", t)
        self.assertLess(t.index("await inviteSwitch();   // 0.21.91"), t.index('if (joinState === "joined" && CHANNEL !== room) leaveMeeting();'))
        # the 0.21.86 silent-rejoin rule is untouched
        self.assertIn('if (joinState === "joined" && CHANNEL !== room) leaveMeeting();', t)

    def test_guests_see_the_lobby_and_their_room(self):
        p = self.p
        g = body(p, "function inviteGuest() {", 500)
        self.assertIn('if (joinState === "joined") return authSecured && authCodes && !authAccessCode;', g)
        self.assertIn("return !!inviteGet() && !authAccessCode && !lastJoin()?.access;", g)
        self.assertIn("lastChannelList = guestRooms(deriveRooms());", p)
        self.assertIn("return list.filter((r) => r.slug === LOBBY || (!!inv && r.slug === inv.room));", p)
        self.assertIn("if (inviteGuest()) { host.hidden = true; return; }   // 0.21.91: a guest has no My room", p)
        # the relay host is asked with the guest's token (it answers their room alone)
        self.assertIn('const gh = inviteGuest() && authSecured && authTokens?.member ? { authorization: "Bearer " + authTokens.member } : undefined;', p)
        # a guest's Lobby mint carries the link
        self.assertIn("const invTok = inv && (inv.room === room || (room === LOBBY && !String(access ?? \"\"))) ? inv.token : undefined;", p)
        # the guest's Lobby: the invited room + Join again
        self.assertIn('<button type="button" class="lbjoin">Join again</button>', p)
        self.assertIn("async function lobbyGuestJoin() {", p)
        self.assertIn("Your invite link has ended \\u2014 ask the person who invited you for a new one.", p)


class GuestLobby(unittest.TestCase):
    """The minter: an invite link also opens the Lobby for its guest (presence only; the token says which room it waits for)."""

    def setUp(self):
        self.key = os.urandom(32)
        self.svc = kr.AuthService("127.0.0.1", 0, self.key, 4443, store())
        self.svc.store.touch_room("yard", "kenton")
        self.svc.store.touch_room("dock", "kenton")
        o, c = self.svc.invite_create_api({"room": "yard", "ttl": 3600, "by": "Kenton"}, member(self.svc, "yard"), "10.0.0.1")
        assert c == 200, o
        self.inv = o

    def tearDown(self):
        self.svc.close()

    def test_the_lobby_with_the_link(self):
        r, c = self.svc.token({"room": "main", "invite": self.inv["token"], "host": "guest-cd34"}, "10.0.0.9")
        self.assertEqual(c, 200, r)
        self.assertTrue(r["lobby"])
        self.assertEqual(r["invite"]["room"], "yard")
        cl = kr.verify_token(r["tokens"]["member"], self.key)
        self.assertEqual(cl["lobby"], 1)
        self.assertEqual((cl["inv"], cl["ir"], cl["get"]), (self.inv["id"], "yard", "main"))
        self.assertNotIn("adm", cl)
        self.assertTrue(all(x.startswith((kr.STATE_PREFIX + "/main/", kr.PRESENCE_KIND + "/main")) for x in cl["put"]), cl["put"])   # presence only

    def test_never_another_room(self):
        r, c = self.svc.token({"room": "dock", "invite": self.inv["token"], "host": "guest-cd34"}, "10.0.0.9")
        self.assertEqual(c, 403)
        self.assertEqual(r.get("invite"), "room")

    def test_the_lobby_without_a_code_or_link_is_refused(self):
        r, c = self.svc.token({"room": "main", "code": "", "host": "guest-cd34"}, "10.0.0.9")
        self.assertNotEqual(c, 200)

    def test_a_dead_link_opens_nothing(self):
        r, c = self.svc.token({"room": "main", "invite": "ki-0000aaaa-" + "x" * 40, "host": "guest-cd34"}, "10.0.0.9")
        self.assertNotEqual(c, 200)


class GuestList(unittest.TestCase):
    """What the relay host lists for a guest's token: their room alone (no other rooms, groups or renames)."""

    def test_guest_rooms(self):
        self.assertIsNone(kr.guest_rooms(None))
        self.assertIsNone(kr.guest_rooms({"get": "yard", "put": []}))                       # a member with an access code
        self.assertIsNone(kr.guest_rooms({"lobby": 1, "get": "main"}))                      # someone in the Lobby with a code
        self.assertEqual(kr.guest_rooms({"get": "yard", "inv": "0123abcd"}), {"yard"})
        self.assertEqual(kr.guest_rooms({"lobby": 1, "get": "main", "inv": "0123abcd", "ir": "yard"}), {"yard"})
        self.assertEqual(kr.guest_rooms({"get": "me-0123456789ab", "pg": 1}), {"me-0123456789ab"})
        self.assertIsNone(kr.guest_rooms(dict(kr.FEDERATION_CLAIMS, inv="x")))            # a relay is never a guest

    def test_rooms_for_guest(self):
        obj = {"rooms": [{"slug": "yard"}, {"slug": "dock"}, {"slug": "ops"}], "closed": {"old": 1, "yard": 2},
               "groups": {"g1": {"name": "Site", "rooms": ["dock"]}}, "renamed": {"a": "b"}}
        out = kr.rooms_for_guest(obj, {"yard"})
        self.assertEqual([r["slug"] for r in out["rooms"]], ["yard"])
        self.assertEqual(out["closed"], {"yard": 2})
        self.assertEqual((out["groups"], out["renamed"], out["guest"]), ({}, {}, True))
        self.assertEqual(len(obj["rooms"]), 3)   # the original is untouched

    def test_the_minter_list(self):
        svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        try:
            svc.store.touch_room("yard", "kenton")
            src = _read("kastr_relay.py")
            self.assertIn('g = guest_rooms(svc._member_claims(self.headers.get("Authorization")))   # 0.21.91: a guest sees their room only', src)
            srv = _read("kastr_serve.py")
            self.assertIn("return self._json_cors(200, self._rooms_guest_cut({\"rooms\": store.rooms_public(), \"closed\": store.closed_public(),", srv)
            self.assertEqual(srv.count("self._rooms_guest_cut(self._rooms_merge("), 2)   # a spoke's answer (the hub's list) too
            self.assertIn("def _rooms_guest_cut(self, obj):", srv)
            # the method sits outside _rooms_api (it once swallowed the rest of that handler)
            i = srv.index("def _rooms_guest_cut(self, obj):")
            self.assertLess(i, srv.index("def _rooms_api(self, method, path, qs):"))
        finally:
            svc.close()


if __name__ == "__main__":
    unittest.main()
