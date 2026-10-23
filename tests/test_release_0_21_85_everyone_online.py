# -*- coding: utf-8 -*-
"""v0.21.85 EVERYONE ONLINE. Kenton: "Add an option to see all people online in the people drop-down."

The People panel gets an "Everyone online" view next to "This room" (the default): people AND guests in any room of the fleet,
viewers included, never camera boxes or relays; each with the room they are in (or the Lobby) -- a private room (a My room
the viewer may not enter, a box's own room) reads "a private room", never its name; a click goes there by the rail's own path
(code / lock prompts) or says why not; the rail's right-click menu (Invite to <this room> / My room); admins also get the
0.21.73 Restart / Move; search, counts, live.

Public rooms announce their people on the public ~presence / ~state prefixes the rail already reads fleet-wide. A personal room
says nothing in public (0.21.75), so its pages' beats say where they are: the hub keeps the fleet's table (its own pages, its
spokes' pwhere / pbeat) and POST /api/people {op: "online"} names a personal room only to someone allowed in it. An admin's
Restart / Move goes through POST /api/people {op: "cmd"} to the relay the person's app checks in to. Loopback sockets only."""
import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

OWNER, GUEST, CAROL, EVE, BOXH, ADM = "kenton-ab12", "bob-cd34", "carol-1f2e", "eve-ef56", "box-9a8b", "admin-7c6d"


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def tok(svc, room, host=OWNER, code="pub-1", room_code=None, invite=None):
    body = {"room": room, "code": code, "host": host}
    if room_code is not None:
        body["roomCode"] = room_code
    if invite is not None:
        body["invite"] = invite
    o, c = svc.token(body, "10.0.0.7")
    assert c == 200, (c, o)
    return o["tokens"]["member"]


def people(svc, t, body):
    return svc.people_api(body, "Bearer " + t, "10.0.0.7")


def beat(svc, t, name, mode="full"):
    o, c = people(svc, t, {"op": "beat", "name": name, "mode": mode})
    assert c == 200, o
    return o


def online(svc, t):
    o, c = people(svc, t, {"op": "online"})
    assert c == 200, o
    return o


def wait_for(fn, limit=5.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    return fn()


class Hub(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        o, c = kr.personal_op(self.svc.store, {"op": "create", "name": "Kenton", "code": "abcd1234", "access": "pub-1"}, "10.0.0.5")
        assert c == 200, o
        self.slug = o["slug"]
        self.own = tok(self.svc, self.slug, room_code="abcd1234")
        for h, n in ((GUEST, "Bob"), (CAROL, "Carol")):
            o, c = people(self.svc, self.own, {"op": "share", "to": h, "name": n, "on": True})
            assert c == 200, o
        beat(self.svc, self.own, "Kenton")                       # the owner is in: guests may come
        self.bob = tok(self.svc, self.slug, host=GUEST)
        beat(self.svc, self.bob, "Bob")
        self.eve = tok(self.svc, "alpha", host=EVE)               # a stranger in a public room
        self.carol = tok(self.svc, "beta", host=CAROL)            # shared with, but elsewhere now

    def tearDown(self):
        self.svc.close()

    def test_a_private_room_is_never_named_to_a_stranger(self):
        o = online(self.svc, self.eve)
        rows = {r["host"]: r for r in o["rows"]}
        self.assertEqual(set(rows), {OWNER, GUEST})
        for r in rows.values():
            self.assertTrue(r["private"])
            self.assertNotIn("room", r)
            self.assertNotIn("owner", r)
            self.assertNotIn("guest", r)
        self.assertEqual((rows[OWNER]["name"], rows[GUEST]["name"]), ("Kenton", "Bob"))
        blob = json.dumps(o)
        self.assertNotIn(self.slug, blob)                         # the slug appears nowhere in a stranger's answer
        self.assertNotIn("relays", o)                             # admins only
        self.assertNotIn("apps", o)

    def test_allowed_people_see_the_room(self):
        for t in (self.bob, self.own, self.carol):                # in it / its owner / shared with this device
            rows = {r["host"]: r for r in online(self.svc, t)["rows"]}
            self.assertEqual(rows[GUEST]["room"], self.slug)
            self.assertEqual(rows[GUEST]["owner"], "Kenton")
            self.assertTrue(rows[GUEST]["guest"])
            self.assertFalse(rows[OWNER]["guest"])
            self.assertNotIn("private", rows[OWNER])

    def test_boxes_moves_leaves_and_silence(self):
        self.assertEqual(people(self.svc, self.own, {"op": "share", "to": BOXH, "name": "Box", "on": True})[1], 200)
        bt = tok(self.svc, self.slug, host=BOXH)
        beat(self.svc, bt, "Gate box", mode="publisher")         # an unattended box is not a person
        hosts = {r["host"] for r in online(self.svc, self.eve)["rows"]}
        self.assertEqual(hosts, {OWNER, GUEST})
        # Bob goes to a public room: his personal-room row goes at once (his public presence lists him there)
        beat(self.svc, tok(self.svc, "alpha", host=GUEST), "Bob")
        self.assertEqual({r["host"] for r in online(self.svc, self.eve)["rows"]}, {OWNER})
        # the owner leaves: gone; silence: every row ages out
        beat(self.svc, self.bob, "Bob")
        people(self.svc, self.own, {"op": "leave"})
        self.assertEqual(online(self.svc, self.eve)["rows"], [])  # the room closed -> its guests' rows go too
        beat(self.svc, self.own, "Kenton")
        later = time.time() + kr.PWHERE_KEEP + 1
        self.assertEqual(self.svc._p_online_rows(EVE, "alpha", later), [])

    def test_since_is_the_join_time_in_that_room(self):
        r0 = {r["host"]: r for r in online(self.svc, self.bob)["rows"]}[GUEST]["since"]
        time.sleep(1.1)
        beat(self.svc, self.bob, "Bob")
        self.assertEqual({r["host"]: r for r in online(self.svc, self.bob)["rows"]}[GUEST]["since"], r0)

    def test_admin_cmd(self):
        adm = tok(self.svc, "alpha", host=ADM, code="adm-1")
        o, c = people(self.svc, self.eve, {"op": "cmd", "to": GUEST, "kind": "restart"})
        self.assertEqual(c, 403, o)                               # a publisher is not an admin
        o, c = people(self.svc, adm, {"op": "cmd", "to": GUEST, "kind": "restart"})
        self.assertEqual(c, 409, o)                               # Bob's KASTR never checked in
        self.assertEqual(self.svc.client_checkin({"node": GUEST, "version": "0.21.85", "name": "Bob"}, "10.0.0.8")[1], 200)
        o, c = people(self.svc, adm, {"op": "cmd", "to": GUEST, "kind": "restart", "by": "Admin"})
        self.assertEqual((c, o["kind"]), (200, "restart"), o)
        self.assertEqual(self.svc.clients[GUEST]["cmd"]["kind"], "restart")
        self.assertEqual(people(self.svc, adm, {"op": "cmd", "to": GUEST, "kind": "move"})[1], 400)   # where to?
        o, c = people(self.svc, adm, {"op": "cmd", "to": GUEST, "kind": "move", "dest": "10.0.2.14"})
        self.assertEqual((c, o["dest"]), (200, "http://10.0.2.14:4443"), o)
        self.assertEqual(self.svc.clients[GUEST]["cmd"]["to"], "http://10.0.2.14:4443")
        self.assertEqual(people(self.svc, adm, {"op": "cmd", "to": ADM, "kind": "restart"})[1], 400)  # that is you
        self.assertEqual(people(self.svc, adm, {"op": "cmd", "to": GUEST, "kind": "zap"})[1], 400)
        # a user on a spoke: the hub's command list carries it (as the Relay page's Users table does)
        self.svc.spokes["spoke:mendon"] = {"name": "mendon", "at": int(time.time()), "clients": kr.clean_clients(
            [{"node": CAROL, "checkin": True, "at": int(time.time()), "kind": "app"}])}
        o, c = people(self.svc, adm, {"op": "cmd", "to": CAROL, "kind": "restart"})
        self.assertEqual((c, o["relay"]), (200, "mendon"), o)
        self.assertEqual(self.svc.cmd["clientCmd"][-1]["node"], CAROL)
        # the admin's online answer: the Move choices and who checks in
        o = online(self.svc, adm)
        self.assertEqual(o["apps"], sorted([GUEST, CAROL]))
        self.assertEqual([r["name"] for r in o["relays"]], ["hub", "mendon"])

    def test_lobby_admin_counts_and_rate(self):
        ladm = tok(self.svc, "main", host=ADM, code="adm-1")      # the Lobby's admin token says so with adm
        self.svc.client_checkin({"node": EVE, "version": "0.21.85"}, "10.0.0.9")
        codes = [people(self.svc, ladm, {"op": "cmd", "to": EVE, "kind": "restart"})[1] for _ in range(kr.PINVITE_RATE[0] + 1)]
        self.assertEqual(codes[:kr.PINVITE_RATE[0]], [200] * kr.PINVITE_RATE[0])
        self.assertEqual(codes[-1], 429)

    def test_a_token_is_required(self):
        self.assertEqual(self.svc.people_api({"op": "online"}, None, "10.0.0.7")[1], 403)
        self.assertEqual(self.svc.people_api({"op": "cmd", "to": GUEST, "kind": "restart"}, None, "10.0.0.7")[1], 403)


class Federation(unittest.TestCase):
    """Guests and owners on a spoke reach the hub's table; a spoke's page asks the hub; a dark hub leaves the spoke its own."""

    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        self.base = ["http://127.0.0.1:%d" % self.hub.httpd.server_address[1]]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: self.base[0], fed_token=lambda: self.fed)
        o, c = self.hub.rooms_fed({"op": "personal", "body": {"op": "create", "name": "Kenton", "code": "abcd1234"}, "vouch": "member"},
                                  "Bearer " + self.fed)
        assert c == 200, o
        self.slug = o["slug"]

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def poll(self):
        return self.spoke.personal_mirror_apply(self.hub.bans_for_spoke("Bearer " + self.fed)[0])

    def test_owner_and_guest_on_a_spoke(self):
        own = tok(self.spoke, self.slug, room_code="abcd1234")
        self.assertEqual(people(self.spoke, own, {"op": "share", "to": GUEST, "name": "Bob", "on": True})[1], 200)
        beat(self.spoke, own, "Kenton")                           # pbeat carries the name to the hub
        self.assertEqual(self.hub._pl().where[OWNER]["name"], "Kenton")
        self.poll()
        bob = tok(self.spoke, self.slug, host=GUEST)
        beat(self.spoke, bob, "Bob")                              # a guest's beat: pwhere to the hub (a thread)
        self.assertTrue(wait_for(lambda: GUEST in self.hub._pl().where))
        self.assertTrue(self.hub._pl().where[GUEST]["guest"])
        # a stranger on the hub sees two people in a private room
        eve = tok(self.hub, "alpha", host=EVE)
        rows = online(self.hub, eve)["rows"]
        self.assertEqual(sorted((r["host"], r.get("private")) for r in rows), [(GUEST, True), (OWNER, True)])
        # Bob's own page on the spoke asks the hub: he sees the room
        rows = {r["host"]: r for r in online(self.spoke, bob)["rows"]}
        self.assertEqual((rows[OWNER]["room"], rows[OWNER]["owner"]), (self.slug, "Kenton"))
        # a stranger on the spoke: private, and the slug nowhere
        e2 = tok(self.spoke, "beta", host=CAROL)
        o = online(self.spoke, e2)
        self.assertNotIn(self.slug, json.dumps(o))
        self.assertNotIn("hubDown", o)
        # Bob moves to a public room on the spoke: the hub forgets him
        beat(self.spoke, tok(self.spoke, "beta", host=GUEST), "Bob")
        self.assertTrue(wait_for(lambda: GUEST not in self.hub._pl().where))
        # the hub goes dark: the spoke answers from its own pages (and says so)
        beat(self.spoke, own, "Kenton")
        self.base[0] = "http://127.0.0.1:9"
        time.sleep(kr.PONLINE_CACHE + 0.1)
        o = online(self.spoke, e2)
        self.assertTrue(o["hubDown"])
        self.assertEqual([(r["host"], r.get("private")) for r in o["rows"]], [(OWNER, True)])
        self.assertNotIn(self.slug, json.dumps(o))

    def test_admin_cmd_from_a_spoke_reaches_an_app_on_the_hub(self):
        adm = tok(self.spoke, "beta", host=ADM, code="adm-1")
        self.hub.client_checkin({"node": EVE, "version": "0.21.85"}, "10.0.0.9")
        o, c = people(self.spoke, adm, {"op": "cmd", "to": EVE, "kind": "restart"})
        self.assertEqual(c, 200, o)
        self.assertEqual(self.hub.clients[EVE]["cmd"]["kind"], "restart")
        self.spoke.client_checkin({"node": CAROL, "version": "0.21.85"}, "10.0.0.10")   # an app of the spoke's own: here
        o, c = people(self.spoke, adm, {"op": "cmd", "to": CAROL, "kind": "move", "dest": "https://10.0.2.14:4443"})
        self.assertEqual(c, 200, o)
        self.assertEqual(self.spoke.clients[CAROL]["cmd"]["to"], "https://10.0.2.14:4443")
        o = online(self.spoke, adm)
        self.assertIn(EVE, o["apps"])
        self.assertEqual(o["relays"][0]["name"], "hub")
        self.base[0] = "http://127.0.0.1:9"
        o, c = people(self.spoke, adm, {"op": "cmd", "to": EVE, "kind": "restart"})
        self.assertEqual((c, o.get("hubDown")), (503, True), o)

    def test_hub_side_validation(self):
        b = "Bearer " + self.fed
        self.assertEqual(self.hub.rooms_fed({"op": "pwhere", "slug": "alpha", "host": GUEST}, b)[1], 400)    # personal rooms only
        self.assertEqual(self.hub.rooms_fed({"op": "pwhere", "slug": self.slug, "host": "nope"}, b)[1], 400)
        self.assertEqual(self.hub.rooms_fed({"op": "pcmd", "vouch": "member", "to": EVE, "kind": "restart"}, b)[1], 403)
        self.assertEqual(self.hub.rooms_fed({"op": "ponline", "host": EVE, "room": "alpha"}, "Bearer nope")[1], 403)
        o, c = self.hub.rooms_fed({"op": "ponline", "host": EVE, "room": "alpha"}, b)
        self.assertEqual((c, o["rows"]), (200, []))
        self.assertNotIn("relays", o)


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _read("moq-watch-lite.html")
        start = cls.p.index("  // ---- 0.21.85 (Kenton: \"Add an option to see all people online in the people drop-down\") -- EVERYONE ONLINE")
        cls.eo = cls.p[start:cls.p.index("  // ---- remote RTSP grid: expand one cell (0.8.8)")]

    def test_two_views_this_room_first(self):
        p = self.p
        self.assertIn('<button type="button" role="tab" id="pplTabRoom" class="on" aria-selected="true" aria-controls="pplRows">This room</button>', p)
        self.assertIn('<button type="button" role="tab" id="pplTabAll" aria-selected="false" aria-controls="pplAll"', p)
        self.assertIn('<div id="pplAll" hidden role="tabpanel" aria-labelledby="pplTabAll">', p)
        self.assertIn('const eo = { view: "room",', self.eo)                 # the default every launch (never remembered)
        self.assertNotIn("localStorage", self.eo.split("function eoBuild")[0])
        # the room view's parts go while Everyone online is on; the search box is shared
        self.assertIn("#peoplePanel.allview .pplsec, #peoplePanel.allview #pplRows, #peoplePanel.allview #pplEmpty, #peoplePanel.allview #pplStreams,", p)
        self.assertIn('ppl.search.placeholder = eoOn() ? "Search everyone online" : "Search participants";', self.eo)
        self.assertIn("try { eoPaint(force); } catch (e) { console.warn(\"KASTR: Everyone online:\", e); }   // 0.21.85", p)   # paintParticipants
        self.assertIn("try { eoPaint(); } catch {}   // 0.21.85: Everyone online is live", p)                          # roomsChanged

    def test_who_is_listed(self):
        e = self.eo
        # public rooms: the rail's own presence, boxes and relays left out, never a personal room from there
        self.assertIn("if (!w || !alive(p) || presenceHidden(w) || !ROOM_RE.test(p.slug) || isPersonalSlug(p.slug)) continue;", e)
        self.assertIn("if (isHomeRoom(p.slug) && !(joined && p.slug === CHANNEL)) x.priv = true;", e)   # a box's own room is private
        # personal rooms: only what the relay host answers; a row without a personal slug stays private
        self.assertIn('const room = !s.private && isPersonalSlug(String(s.room || "")) ? String(s.room) : "";', e)
        self.assertIn('title: x.priv ? "In a private room" : roomTitle(x.room) };', e)
        self.assertIn('body: JSON.stringify({ op: "online" }), signal: ctl.signal });', e)
        self.assertIn("setInterval(() => { if (eoOn() && !ppl.panel.hidden) eoFetch(); }, EO_POLL_MS);", e)   # only while it is open
        self.assertIn("const EO_POLL_MS = 4000, EO_STALE_MS = 15000;", e)
        # the Lobby shows no names (0.21.60)
        self.assertIn("const groups = joined && !lobby ? eoBuild() : [];", e)
        self.assertIn("Nobody sees names in the Lobby", e)
        # the beat says the page's mode, so a box in a personal room is no person either
        self.assertIn('body: JSON.stringify({ op: "beat", name: myOpName(), mode: (() => { try { return String(window.__pageMode?.() || ""); } catch { return ""; } })() }) });', self.p)

    def test_go_by_the_rails_path(self):
        e = self.eo
        self.assertIn("sbCardClick(card, rec);   // the rail's own path", e)
        self.assertIn("if (personalGet()?.slug === g.slug) personalEnter(); else personalGuestEnter(g.slug); return;", e)
        self.assertIn('if (g.priv) return { can: false, why: "A private room ', e)
        self.assertIn("if (authSecured && !authAccessCode && inviteGet()?.room !== g.slug", e)   # an invite link opens its room only
        self.assertIn("b.disabled = !g.go.can; b.title = g.go.can ?", e)

    def test_the_rails_menu_plus_admin_actions(self):
        e, p = self.eo, self.p
        self.assertIn("return participantMenu(p, anchor);", e)                    # the rail's / People rows' menu
        self.assertIn('if (p.more?.items?.length) items.push(...(items.length ? [{ sep: true }] : []), ...p.more.items);', p)
        self.assertIn('return { items, pick: (v) => (String(v).startsWith("pinv-eo") ? p.more?.pick?.(v) : personInvite(p, host, v === "pinv-mine" ? mine.slug : CHANNEL)) };', p)
        self.assertIn('if (!authSecured || authRole !== "admin" || x.me || !x.host || x.host === HOSTNAME1 || x.host.startsWith("web-")) return [];', e)
        self.assertIn('{ value: "pinv-eo-restart", label: "Restart their KASTR (admin)"', e)
        self.assertIn('{ value: "pinv-eo-move", label: "Move to another relay', e)
        self.assertIn('body: JSON.stringify({ op: "cmd", to: x.host, kind, dest: dest || undefined, by: myOpName() || undefined }) });', e)
        # another room's watcher is never "Remove from the room" (that is my room's admin kick)
        self.assertIn("viewer: !x.priv && x.room === CHANNEL && !x.pub", e)

    def test_a_failed_board_poll_keeps_the_board(self):
        self.assertIn("    if (!d) return;   // 0.21.85 (lab: a dark hub)", self.p)


class Serve(unittest.TestCase):
    def test_same_endpoint_through_the_web_port(self):
        self.assertIn('"/api/people",                                       # 0.21.78: beats, person invites, My room shared', _read("kastr_serve.py"))
        r = _read("kastr_relay.py")
        self.assertIn('"pwhere", "ponline", "pcmd")', r)
        self.assertIn('return self._p_online(host, room, claims_admin_any(claims), now)', r)


if __name__ == "__main__":
    unittest.main()
