# -*- coding: utf-8 -*-
"""v0.21.65, Kenton 2026-10-14 -- six more asks, plus (m):
(g) the rooms rail opens / closes from an expand-collapse tab on its own edge (the topbar's hamburger is gone);
(h) Room settings after the fact (creator or admin, right-click): lock / code / unlock, keep open, RENAME (everything moves,
    people follow), group;
(i) any video on the main stage zooms (people's cameras too), double-click toggles 2x;
(j) every webcam of this computer is a SHARED CAMERA from Share > Webcam (Linux: capture nodes only, named, by-id paths);
(k) More > "Ask before changing rooms" (default on);
(l) the rooms rail shows a person's menu only when there is one;
(m) "Lock the view": only the creator or an admin changes the room board; members' spotlight votes are ignored and the
    "for everyone" items are hidden from them."""
import hashlib, io, json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_rtsp  # noqa: E402
import kastr_chat  # noqa: E402

SALT = "00112233aabbccdd"
HOST = "box-1a2b"
CAM = "yard/box-1a2b/kenton/camera.hang"


def h(code, salt=SALT):
    return hashlib.sha256((salt + code).encode()).hexdigest()


def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def read(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def mint(svc, room, code="pub-1", host=HOST):
    o, c = svc.token({"room": room, "code": code, "host": host}, "10.0.0.7")
    assert c == 200, o
    return o["tokens"]["member"]


class RoomSettings(unittest.TestCase):
    def setUp(self):
        self.st = store()
        o, c = kr.register_room(self.st, {"slug": "yard", "plain": True, "creator": "Kenton"}, "10.0.0.1")
        self.assertEqual(c, 200, o)
        self.key = o["roomKey"]

    def op(self, body, admin=False, xs=None):
        return kr.room_settings(self.st, dict({"slug": "yard"}, **body), admin=admin, xs=xs)

    def test_only_the_creator_or_an_admin(self):
        o, c = self.op({"op": "keep", "keep": True})
        self.assertEqual(c, 403, o)
        o, c = self.op({"op": "keep", "keep": True, "roomKey": "not-the-key"})
        self.assertEqual(c, 403, o)
        o, c = self.op({"op": "keep", "keep": True, "roomKey": self.key})
        self.assertEqual(c, 200, o)
        self.assertTrue(self.st.room("yard")["persistent"])
        o, c = self.op({"op": "keep", "keep": False}, admin=True)
        self.assertEqual(c, 200, o)
        self.assertFalse(self.st.room("yard")["persistent"])
        self.assertTrue(self.st.room("yard")["plain"])

    def test_the_lobby_has_no_settings(self):
        o, c = kr.room_settings(self.st, {"slug": "main", "op": "rename", "to": "x"}, admin=True)
        self.assertEqual(c, 403, o)
        o, c = kr.room_settings(self.st, {"slug": "main", "op": "lock", "salt": SALT, "hash": h("x")}, admin=True)
        self.assertEqual(c, 403, o)

    def test_lock_change_code_unlock(self):
        o, c = self.op({"op": "code", "salt": SALT, "hash": h("a"), "roomKey": self.key})
        self.assertEqual(c, 409, o)                      # not locked yet
        o, c = self.op({"op": "lock", "salt": SALT, "hash": h("a"), "roomKey": self.key})
        self.assertEqual(c, 200, o)
        self.assertTrue(o["room"]["locked"])
        self.assertTrue(kr._room_code_ok(self.st.room("yard"), "a"))
        o, c = self.op({"op": "code", "salt": SALT, "hash": h("b")}, admin=True)
        self.assertEqual(c, 200, o)
        self.assertTrue(kr._room_code_ok(self.st.room("yard"), "b"))
        o, c = self.op({"op": "unlock", "roomKey": self.key})
        self.assertEqual(c, 200, o)
        rec = self.st.room("yard")
        self.assertFalse(rec.get("hash"))
        self.assertTrue(rec.get("plain"))
        o, c = self.op({"op": "lock", "salt": "zz", "hash": "nope"}, admin=True)
        self.assertEqual(c, 400, o)

    def test_the_holders_heartbeat_never_puts_an_old_lock_back(self):
        o, c = kr.register_room(self.st, {"slug": "gate", "salt": SALT, "hash": h("old"), "access": "pub-1"}, "10.0.0.1")
        key = o["roomKey"]
        kr.room_settings(self.st, {"slug": "gate", "op": "unlock", "roomKey": key})
        o, c = kr.register_room(self.st, {"slug": "gate", "salt": SALT, "hash": h("old"), "roomKey": key, "persistent": False}, "10.0.0.1")
        self.assertEqual(c, 200, o)
        self.assertFalse(self.st.room("gate").get("hash"))   # the creator's page still sends its create-time lock

    def test_keep_off_releases_a_room_kept_by_its_board(self):
        self.st.board_apply("yard", "spot", kr.board_item("spot", {"target": CAM})[0])
        self.assertEqual(self.st.room("yard").get("keptBy"), "board")
        row = [r for r in self.st.rooms_public() if r["slug"] == "yard"][0]
        self.assertEqual(row.get("keptBy"), "board")
        o, c = self.op({"op": "keep", "keep": False, "roomKey": self.key})
        self.assertEqual(c, 200, o)
        rec = self.st.room("yard")
        self.assertFalse(rec["persistent"])
        self.assertNotIn("keptBy", rec)
        self.assertEqual(len(self.st.board("yard")["spots"]), 1)   # the board stays until the room goes

    def test_group(self):
        gid = self.st.group_set(None, "Sites")
        o, c = self.op({"op": "group", "group": gid})
        self.assertEqual(c, 403, o)
        o, c = self.op({"op": "group", "group": gid, "roomKey": self.key})
        self.assertEqual(c, 200, o)
        self.assertIn("yard", self.st.groups_public()[gid]["rooms"])
        o, c = self.op({"op": "group", "group": None}, admin=True)
        self.assertEqual(c, 200, o)
        self.assertNotIn("yard", self.st.groups_public()[gid]["rooms"])

    def test_rename_moves_everything_and_leaves_a_redirect(self):
        gid = self.st.group_set(None, "Sites")
        self.st.group_assign("yard", gid)
        self.st.board_apply("yard", "pin", kr.board_item("pin", {"path": "other/box-1a2b/x/camera.hang", "label": "X"})[0])
        self.st.board_apply("yard", "spot", kr.board_item("spot", {"target": CAM})[0])
        self.st.board_apply("yard", "split", kr.board_item("split", {"path": CAM})[0])
        xs = kr.XShareRegistry()
        xs.apply("other/box-1a2b/x/screen.hang", "other", ["yard"], "Screen")      # listed INTO yard
        xs.apply(CAM, "yard", ["other"], "Cam")                                    # yard's stream listed elsewhere
        moved = []
        with mock.patch.object(kr, "ROOM_RENAME_HOOK", [lambda a, b: moved.append((a, b))]):
            o, c = self.op({"op": "rename", "to": "front-gate"}, xs=xs)
            self.assertEqual(c, 403, o)
            o, c = self.op({"op": "rename", "to": "front-gate", "roomKey": self.key}, xs=xs)
        self.assertEqual(c, 200, o)
        self.assertEqual(o["slug"], "front-gate")
        self.assertEqual(moved, [("yard", "front-gate")])                          # the chat store moved it
        self.assertIsNone(self.st.room("yard"))
        rec = self.st.room("front-gate")
        self.assertEqual(rec["roomKey"], self.key)                                 # its creator keeps it
        b = self.st.board("front-gate")
        self.assertEqual([s["target"] for s in b["spots"]], ["front-gate/box-1a2b/kenton/camera.hang"])
        self.assertEqual(b["split"], ["front-gate/box-1a2b/kenton/camera.hang"])
        self.assertEqual([p["path"] for p in b["pins"]], ["other/box-1a2b/x/camera.hang"])   # another room's feed stays
        self.assertEqual(self.st.groups_public()[gid]["rooms"], ["front-gate"])
        self.assertEqual(self.st.renamed_public(), {"yard": "front-gate"})
        self.assertEqual(self.st.board("yard").get("renamed"), "front-gate")       # pages still in yard follow
        self.assertEqual(self.st.boards_public()["yard"].get("renamed"), "front-gate")
        keys = set(xs.items)
        self.assertIn(("other/box-1a2b/x/screen.hang", "front-gate"), keys)
        self.assertIn(("front-gate/box-1a2b/kenton/camera.hang", "other"), keys)
        # a late page in the old name never re-makes it; a deliberate create does (and drops the redirect)
        self.assertFalse(self.st.touch_room("yard"))
        self.assertIsNone(self.st.room("yard"))
        b, code, err = self.st.board_apply("yard", "spot", kr.board_item("spot", {"target": "yard/box-1a2b/k/camera.hang"})[0])
        self.assertEqual(code, 409, err)
        again = kr.AuthStore(self.st.state_dir)                                     # survives a restart
        self.assertEqual(again.renamed_public(), {"yard": "front-gate"})
        o, c = kr.register_room(self.st, {"slug": "yard", "persistent": True, "access": "pub-1"}, "10.0.0.2")
        self.assertEqual(c, 200, o)
        self.assertEqual(self.st.renamed_public(), {})

    def test_rename_refuses_a_taken_or_bad_name(self):
        self.st.touch_room("taken")
        for to, want in (("taken", 409), ("main", 400), ("Bad Name!", 400), ("yard", 400)):
            o, c = self.op({"op": "rename", "to": to}, admin=True)
            self.assertEqual(c, want, (to, o))

    def test_view_lock_refuses_members_but_not_the_creator_or_an_admin(self):
        o, c = self.op({"op": "viewlock", "locked": True, "roomKey": self.key})
        self.assertEqual(c, 200, o)
        self.assertTrue(o["room"]["viewLock"])
        self.assertTrue(self.st.board("yard")["lock"])
        self.assertTrue(self.st.boards_public()["yard"]["lock"])                  # spokes copy the lock with the boards
        item = kr.board_item("spot", {"target": CAM})[0]
        b, code, err = self.st.board_apply("yard", "spot", item)
        self.assertEqual((code, err), (403, kr.VIEW_LOCKED_TEXT))
        b, code, err = self.st.board_apply("yard", "spot", item, room_key=self.key)
        self.assertEqual(code, 200, err)
        b, code, err = self.st.board_apply("yard", "unspot", {"target": CAM}, boss=True)
        self.assertEqual(code, 200, err)
        o, c = kr.board_open("POST", self.st, {"room": "yard", "op": "spot", "target": CAM})   # an open relay: the roomKey
        self.assertEqual(c, 403, o)
        o, c = kr.board_open("POST", self.st, {"room": "yard", "op": "spot", "target": CAM, "roomKey": self.key})
        self.assertEqual(c, 200, o)
        self.assertTrue(kr.board_open("GET", self.st, room="yard")[0]["lock"])
        o, c = self.op({"op": "viewlock", "locked": False}, admin=True)
        self.assertEqual(c, 200, o)
        b, code, err = self.st.board_apply("yard", "unspot", {"target": CAM})
        self.assertEqual(code, 200, err)


class Service(unittest.TestCase):
    """The minter: members' board changes in a locked view; the hub's rooms_fed op "settings" (what a spoke forwards)."""

    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: base, fed_token=lambda: self.fed)
        o, c = kr.register_room(self.hub.store, {"slug": "yard", "plain": True}, "10.0.0.1")
        self.key = o["roomKey"]

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def test_settings_through_the_hub_need_the_key_or_an_admin_vouch(self):
        fed = "Bearer " + self.fed
        body = {"slug": "yard", "op": "viewlock", "locked": True}
        self.assertEqual(self.hub.rooms_fed({"op": "settings", "body": body}, None)[1], 403)   # federation token first
        o, c = self.hub.rooms_fed({"op": "settings", "body": body}, fed)
        self.assertEqual(c, 403, o)
        o, c = self.hub.rooms_fed({"op": "settings", "body": body, "vouch": "admin"}, fed)
        self.assertEqual(c, 200, o)
        o, c = self.hub.rooms_fed({"op": "settings", "body": dict(body, locked=False, roomKey=self.key)}, fed)
        self.assertEqual(c, 200, o)
        o, c = self.hub.rooms_fed({"op": "settings", "body": {"slug": "yard", "op": "rename", "to": "gate-2", "roomKey": self.key}}, fed)
        self.assertEqual(c, 200, o)
        o, c = self.hub.rooms_fed({"op": "list"}, fed)
        self.assertEqual(o["renamed"], {"yard": "gate-2"})
        self.assertIn("gate-2", [r["slug"] for r in o["rooms"]])

    def test_locked_view_at_the_minter(self):
        kr.room_settings(self.hub.store, {"slug": "yard", "op": "viewlock", "locked": True}, admin=True)
        member = mint(self.hub, "yard")
        o, c = self.hub.board_post({"room": "yard", "op": "spot", "target": CAM}, "Bearer " + member, "10.0.0.7")
        self.assertEqual(c, 403, o)
        self.assertIn("locked", o["error"])
        o, c = self.hub.board_post({"room": "yard", "op": "spot", "target": CAM, "roomKey": self.key}, "Bearer " + member, "10.0.0.7")
        self.assertEqual(c, 200, o)                                       # the creator (its key)
        admin = mint(self.hub, "yard", code="adm-1", host="box-2c3d")
        o, c = self.hub.board_post({"room": "yard", "op": "unspot", "target": CAM}, "Bearer " + admin, "10.0.0.8")
        self.assertEqual(c, 200, o)                                       # an admin
        o, c = self.hub.board_get("yard", "Bearer " + member)
        self.assertTrue(o["lock"])

    def test_locked_view_through_a_spoke(self):
        kr.room_settings(self.hub.store, {"slug": "yard", "op": "viewlock", "locked": True}, admin=True)
        member = mint(self.spoke, "yard")
        o, c = self.spoke.board_post({"room": "yard", "op": "spot", "target": CAM}, "Bearer " + member, "10.0.0.7")
        self.assertEqual(c, 403, o)
        admin = mint(self.spoke, "yard", code="adm-1", host="box-2c3d")
        o, c = self.spoke.board_post({"room": "yard", "op": "spot", "target": CAM}, "Bearer " + admin, "10.0.0.8")
        self.assertEqual(c, 200, o)
        o, c = self.spoke.board_post({"room": "yard", "op": "unspot", "target": CAM, "roomKey": self.key}, "Bearer " + member, "10.0.0.7")
        self.assertEqual(c, 200, o)

    def test_admin_tokens_prove_admin_for_any_room(self):
        key = self.hub.key
        admin = kr.verify_token(mint(self.hub, "other", code="adm-1"), key)
        self.assertTrue(kr.claims_admin_any(admin))
        self.assertFalse(kr.claims_admin_any(kr.verify_token(mint(self.hub, "other"), key)))
        lobby = self.hub.token({"room": "main", "code": "adm-1", "host": HOST}, "10.0.0.7")[0]["tokens"]["member"]
        self.assertTrue(kr.claims_admin_any(kr.verify_token(lobby, key)))
        lobby_pub = self.hub.token({"room": "main", "code": "pub-1", "host": HOST}, "10.0.0.7")[0]["tokens"]["member"]
        self.assertFalse(kr.claims_admin_any(kr.verify_token(lobby_pub, key)))
        self.assertFalse(kr.claims_admin_any(kr.verify_token(self.fed, key)))


class ChatRename(unittest.TestCase):
    def test_history_and_attachments_move(self):
        d = tempfile.mkdtemp()
        files = os.path.join(d, "shared")
        os.makedirs(files)
        cs = kastr_chat.ChatStore(d, files_dir=files)
        cs.append("yard", "kenton", "Kenton", "hello")
        cs.mark_keep("yard", True)
        with open(os.path.join(files, "abc.json"), "w", encoding="utf-8") as f:
            json.dump({"kind": "chat", "room": "yard", "name": "a.png"}, f)
        self.assertTrue(cs.rename_room("yard", "front-gate"))
        self.assertEqual([m["text"] for m in cs.read("front-gate")], ["hello"])
        self.assertEqual(cs.read("yard"), [])
        self.assertTrue(cs.is_kept("front-gate"))
        with open(os.path.join(files, "abc.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["room"], "front-gate")

    def test_serve_wires_the_hook_and_the_route(self):
        s = read("kastr_serve.py")
        self.assertIn("kastr_relay.ROOM_RENAME_HOOK[0] = _room_rename_hook", s)
        self.assertIn('if path == "/api/rooms/settings":', s)
        self.assertIn('body = {"op": "settings", "body": p, "vouch": "admin" if self._settings_admin() else None}', s)
        self.assertIn('"renamed": store.renamed_public()', s)
        self.assertIn('"renamed": hub_obj.get("renamed") or {}', s)


class Webcams(unittest.TestCase):
    def test_dshow_both_styles_and_twins(self):
        new = '[dshow @ 01] "HD Webcam" (video)\n[dshow @ 01]   Alternative name "@device_pnp_x"\n[dshow @ 01] "Mic" (audio)\n[dshow @ 01] "HD Webcam" (video)\n'
        self.assertEqual(kastr_rtsp._dshow_names(new), ["HD Webcam", "HD Webcam #2"])
        old = ('[dshow @ 01] DirectShow video devices (some may be both video and audio devices)\n[dshow @ 01]  "Integrated Camera"\n'
               '[dshow @ 01]     Alternative name "@device_pnp_y"\n[dshow @ 01] DirectShow audio devices\n[dshow @ 01]  "Microphone"\n')
        self.assertEqual(kastr_rtsp._dshow_names(old), ["Integrated Camera"])

    def test_the_second_twin_opens_by_number(self):
        with mock.patch.object(kastr_rtsp.sys, "platform", "win32"):
            a = kastr_rtsp.DeviceCapture("ffmpeg", "device://video/" + "HD%20Webcam%20%232").args()
        self.assertIn("-video_device_number", a)
        self.assertEqual(a[a.index("-video_device_number") + 1], "1")
        self.assertIn("video=HD Webcam", a)

    def test_linux_capture_nodes_named_by_id_and_permissions(self):
        root = tempfile.mkdtemp()
        dev, sysd = os.path.join(root, "dev"), os.path.join(root, "sys")
        os.makedirs(os.path.join(dev, "v4l", "by-id"))
        for n, name, idx in (("video0", "HD Pro Webcam C920", "0"), ("video1", "HD Pro Webcam C920", "1"),
                             ("video2", "USB2.0 HD UVC WebCam", "0"), ("video3", "USB2.0 HD UVC WebCam", "1"), ("video10", "bcm2835-codec", "0")):
            open(os.path.join(dev, n), "w").close()
            os.makedirs(os.path.join(sysd, n))
            with open(os.path.join(sysd, n, "name"), "w") as f:
                f.write(name + "\n")
            with open(os.path.join(sysd, n, "index"), "w") as f:
                f.write(idx + "\n")
        link = os.path.join(dev, "v4l", "by-id", "usb-046d_C920-video-index0")
        caps = {"video0": True, "video1": False, "video10": False}

        def fake_caps(path):
            b = os.path.basename(path)
            if b in ("video2", "video3"):
                raise PermissionError(13, "Permission denied")
            return caps[b]
        real = os.path.realpath
        with mock.patch.object(kastr_rtsp.os.path, "realpath", lambda p: real(os.path.join(dev, "video0")) if p == link else real(p)):
            open(link, "w").close()
            rows, note = kastr_rtsp._linux_cameras(dev, sysd, caps=fake_caps)
        self.assertEqual([r["name"] for r in rows], ["HD Pro Webcam C920", "USB2.0 HD UVC WebCam"])   # metadata / codec nodes left out
        self.assertEqual(rows[0]["id"], link)                                                     # stable across re-plugs
        self.assertIn("video", rows[1]["error"])                                                  # says why it cannot open
        self.assertEqual(note, "")
        rows, note = kastr_rtsp._linux_cameras(os.path.join(root, "nothing"), sysd, caps=fake_caps)
        self.assertEqual(rows, [])
        self.assertIn("No camera", note)

    def test_serve_answers_names_and_notes(self):
        s = read("kastr_serve.py")
        self.assertIn('cams, note = kastr_rtsp.list_cameras(', s)
        self.assertIn('"cams": cams, "note": note', s)


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = read("moq-watch-lite.html")

    def test_g_edge_tab(self):
        p = self.p
        self.assertIn('id="sbEdge" class="sbedge" title="Collapse rooms"', p)
        self.assertNotIn('id="roomsBtn"', p)
        self.assertIn('const t = open ? "Collapse rooms" : "Expand rooms";', p)
        self.assertIn("new MutationObserver(paint).observe(document.body, { attributes: true, attributeFilter: [\"class\"] })", p)
        self.assertIn(".sbedge { right:-27px; width:26px;", p)   # phones: the drawer's handle

    def test_h_room_settings_wiring(self):
        p = self.p
        self.assertIn('if (roomSettingsRole(r)) items.push(', p)
        self.assertIn('else if (v === "rsettings") openRoomSettings(rec);', p)
        self.assertIn('fetch(base + "/api/rooms/settings"', p)
        for op in ('op: "rename", to', 'op: "unlock"', 'op: was ? "code" : "lock"', 'op: "keep", keep: on', 'op: "viewlock", locked: on', 'op: "group", group: g'):
            self.assertIn(op, p)
        self.assertIn("if (authSecured && authRole === \"admin\") return \"admin\";", p)
        self.assertIn("function roomRenamedFollow(old, to)", p)
        self.assertIn("if (joinState === \"joined\" && roomsRenamed[CHANNEL]) roomRenamedFollow(CHANNEL, String(roomsRenamed[CHANNEL]));", p)
        self.assertIn("if (d && d.ok && d.room === CHANNEL && d.renamed) { roomRenamedFollow(CHANNEL, String(d.renamed)); return; }", p)
        self.assertIn("if (!isPublisherMode() && !opts?.follow) {", p)    # following a rename keeps mic and camera as they are

    def test_i_people_cameras_zoom(self):
        p = self.p
        self.assertIn('t.pane.classList.toggle("zoomable", shown && isSelected && !gridMode && !selfSpotEl);', p)
        self.assertIn('armView(pane, () => tile.canvas, () => !gridMode && name === selectedName && !selfSpotEl && pane.classList.contains("mainstage"));', p)
        self.assertIn('if (pane.classList.contains("zoomable") && !gridMeta.has(name) && !tile.cg) {', p)   # a double-click is not two clicks
        self.assertIn("clearTimeout(pane.__clickT); pane.__clickT = null;", p)

    def test_j_webcam_section(self):
        p = self.p
        self.assertIn('<h2 id="shCamHead">Webcam</h2>', p)
        self.assertIn('addRtsp(webcamUrl(cam.id), { label: cam.name, keep: true, gridId: "none" })', p)
        self.assertIn("removeSource(face.id);", p)   # the toolbar camera lets the webcam go first
        self.assertIn("Webcams are shared as shared cameras from the KASTR desktop app", p)

    def test_k_ask_before_changing_rooms(self):
        p = self.p
        self.assertIn('id="optAskRoom"', p)
        self.assertIn('localStorage.getItem("kastr.askRoomSwitch") !== "off"', p)
        self.assertIn("if (!isPublisherMode() && (ask || needCode)) {", p)

    def test_l_rail_menu_only_when_there_is_one(self):
        p = self.p
        self.assertIn("return participantList().find((p) => p.key === key && participantHasMenu(p)) || null;", p)
        self.assertIn("return !!(p.viewer && authRole === \"admin\");", p)

    def test_m_view_lock_hides_and_ignores(self):
        p = self.p
        self.assertIn("&& !viewLockedForMe();   // 0.21.65 (m)", p)          # boardCan: pin / arrange / remove / split for everyone
        self.assertIn("for (const [k, arr] of spotVotes) { if (vl && k !== \"~board\") continue;", p)
        self.assertIn("if (!vl) for (const arr of spotOffs.values())", p)
        self.assertIn("if ((!wrSrc || wrBring) && !viewLockedForMe()) items.push(", p)
        self.assertIn("const spotItem = viewLockedForMe() ? null :", p)
        self.assertIn("...(window.__viewLockedForMe?.() ? [] : [gLit ?", p)
        self.assertIn('vl.className = "rbvl"', p)


if __name__ == "__main__":
    unittest.main()
