# -*- coding: utf-8 -*-
"""v0.21.92 RECORD THE PRESENTATION (Kenton 2026-10-28): a switch for presenters + backstage records what the audience sees
and hears, on the relay host (kastr_presrec: a headless recorder page per recording, parts on restart, caps, Recordings for
presenters / backstage / admins). The recorder browser is ALWAYS a stub here (no browser, no network beyond nothing)."""
import io, json, os, re, shutil, sys, tempfile, time, types, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_presrec as pr  # noqa: E402

DID = "0123456789abcdef0123456789abcdef"
DID2 = "fedcba9876543210fedcba9876543210"
TOK, RTOK = "write-token-lab-1", "read-token-lab-1"     # lab values
ROOM = "lab"
GB = pr.GB


def _digest(v):
    try:
        import kastr_secret
        return kastr_secret.digest(v)
    except Exception:
        return v


def read(rel):
    with open(os.path.join(HERE, rel), "rb") as f:
        return f.read().decode("utf-8")


class Proc:
    def __init__(self):
        self.code = None
        self.killed = False

    def poll(self):
        return self.code

    def kill(self):
        self.killed = True
        self.code = -9

    def wait(self, timeout=None):
        return self.code


class Rig(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.t = [1000.0]
        self.free = [500 * GB]
        self.launched = []
        self.relay = types.SimpleNamespace(running=lambda: True, secured=True, port=4960,
                                           auth=types.SimpleNamespace(key=os.urandom(32)))
        self.deck(DID)
        self.inst = self.make()

    def make(self):
        return pr.PresRec(self.d, relay=self.relay, web_port=9220, ffmpeg=None, launch=self.launch,
                          clock=lambda: self.t[0], free=lambda: self.free[0])

    def launch(self, s, url):
        p = Proc()
        self.launched.append((s.rid, s.part, url, p))
        return p

    def deck(self, did, plain=False, room=ROOM, tok=TOK, rtok=RTOK):
        os.makedirs(os.path.join(self.d, "pres", did), exist_ok=True)
        m = {"id": did, "token": tok if plain else _digest(tok), "rtoken": rtok if plain else _digest(rtok),
             "room": room, "name": "Quarterly"}
        with open(os.path.join(self.d, "pres", did, "meta.json"), "w") as f:
            json.dump(m, f)

    def end_deck(self, did):
        shutil.rmtree(os.path.join(self.d, "pres", did), ignore_errors=True)

    def started(self, did=DID, k=TOK):
        code, st = self.inst.start(did, k, name="Quarterly", by_name="Alice")
        self.assertEqual(code, 200, st)
        return st["id"], self.inst.live[st["id"]]

    def feed(self, s, n=1, size=1000, part=None):
        for _ in range(n):
            code, obj = self.inst.chunk(s.rid, s.key, part or s.part, s.seq, b"x" * size, ms=2000 * (s.seq + 1))
            self.assertEqual(code, 200, obj)
        return obj

    def finish(self):
        self.t[0] += 1
        return self.inst.tick()


class Who(Rig):
    def test_presenter_and_backstage_may_switch_audience_not(self):
        self.assertEqual(self.inst.who(DID, TOK), "presenter")
        self.assertEqual(self.inst.who(DID, RTOK), "backstage")
        for k in ("", "nope", TOK + "x", _digest(TOK)):   # the stored digest itself is no key
            self.assertIsNone(self.inst.who(DID, k), k)
        self.assertEqual(self.inst.start(DID, "nope")[0], 403)
        self.assertEqual(self.inst.stop(DID, "")[0], 403)
        self.assertEqual(self.inst.state(DID, "nope")[0], 403)
        code, st = self.inst.start(DID, RTOK)            # backstage switches it on
        self.assertEqual(code, 200, st)
        self.assertEqual(st["by"], "backstage")
        self.assertEqual(self.inst.stop(DID, RTOK)[0], 200)

    def test_a_0_21_91_deck_with_plain_tokens(self):
        self.deck(DID2, plain=True)
        self.assertEqual(self.inst.who(DID2, TOK), "presenter")
        self.assertEqual(self.inst.who(DID2, RTOK), "backstage")

    def test_bad_deck_ids(self):
        self.assertIsNone(self.inst.who("../pres", TOK))
        self.assertIsNone(self.inst.who("ABC", TOK))


class StartStop(Rig):
    def test_start_state_stop_through_the_api(self):
        rid, s = self.started()
        self.assertEqual(len(self.launched), 1)
        url = self.launched[0][2]
        self.assertTrue(url.startswith("http://presrec.localhost:9220/api/presrec/%s/boot?n=" % rid), url)
        code, again = self.inst.start(DID, RTOK)          # a second switch-on: the same recording, no second recorder
        self.assertEqual(again["id"], rid)
        self.assertEqual(len(self.launched), 1)
        code, st = self.inst.state(DID, RTOK)
        self.assertTrue(st["on"])
        self.assertIn("el", st)
        self.feed(s, 3)
        self.inst.stop(DID, TOK)
        self.assertTrue(s.stopping)
        self.inst.done(rid, s.key, s.part)
        self.assertEqual(self.finish(), 1)
        code, st = self.inst.state(DID, TOK)
        self.assertFalse(st["on"])
        self.assertEqual(st["last"]["state"], "done")
        self.assertEqual(st["last"]["why"], pr.WHY["stop"])
        self.assertTrue(os.path.isfile(os.path.join(self.d, "presrec", rid, "1.mp4")))
        self.assertFalse(os.path.exists(os.path.join(self.d, "presrec", rid, "part1.rec")))
        self.assertTrue(self.launched[0][3].killed)

    def test_fresh_start_after_end_is_a_new_file(self):
        rid1, s = self.started()
        self.feed(s)
        self.inst.deck_ended(DID)
        self.finish()
        rid2, s2 = self.started()
        self.assertNotEqual(rid1, rid2)

    def test_a_switch_off_with_nothing_recorded_leaves_nothing(self):
        rid, s = self.started()
        self.inst.stop(DID, TOK)
        self.t[0] += pr.STOP_WAIT_S                                                  # no last piece comes: closed anyway
        self.finish()
        self.assertFalse(os.path.exists(os.path.join(self.d, "presrec", rid)))

    def test_boot_link_is_one_use_and_keys_the_page(self):
        rid, s = self.started()
        nonce = self.launched[0][2].split("n=")[1]
        html = self.inst.boot(rid, nonce)
        self.assertIn("sessionStorage.setItem('kastr.presrec'", html)
        self.assertIn("moq-watch-lite.html", html)
        self.assertIn(json.dumps(s.key)[1:-1], html)
        self.assertIsNone(self.inst.boot(rid, nonce))
        self.assertIsNone(self.inst.boot(rid, "x"))

    def test_pieces_in_order_for_the_current_part(self):
        rid, s = self.started()
        self.assertEqual(self.inst.chunk(rid, s.key, 1, 1, b"x")[0], 409)        # piece 0 first
        self.assertEqual(self.inst.chunk(rid, "wrong", 1, 0, b"x")[0], 403)
        self.feed(s, 2)
        self.assertEqual(self.inst.chunk(rid, s.key, 7, 2, b"x")[0], 409)        # not this part


class EndAndHandOver(Rig):
    def test_end_finishes_the_file(self):
        rid, s = self.started()
        self.feed(s, 4)
        pr._INST[0] = self.inst
        self.addCleanup(lambda: pr._INST.__setitem__(0, None))
        pr.deck_ended(self.d, DID)                                                  # kastr_pres's End seam
        self.assertTrue(s.stopping)
        self.assertEqual(s.meta["why"], "ended")
        self.inst.done(rid, s.key, s.part)
        self.finish()
        code, lst = self.inst.listing([{"d": DID, "k": RTOK}])
        self.assertEqual([r["state"] for r in lst["recordings"]], ["done"])
        self.assertEqual(lst["recordings"][0]["parts"][0]["bytes"], 4000)

    def test_end_waits_for_the_last_piece_then_gives_up(self):
        rid, s = self.started()
        self.feed(s)
        self.inst.deck_ended(DID)
        self.t[0] += 1
        self.assertEqual(self.inst.tick(), 0)                                       # the recorder's last piece may still come
        self.feed(s)                                                                 # ... it does
        self.t[0] += pr.STOP_WAIT_S + 1
        self.assertEqual(self.inst.tick(), 1)
        self.assertEqual(self.inst._load(rid)["size"], 2000)

    def test_survives_hand_over_and_the_main_presenter_dropping(self):
        # the recording belongs to the deck, not to whoever switched it on: hand-over, Take over and the owner's page going
        # away change nothing on the relay host; the recorder page follows the deck's newest owner (og) in the room
        rid, s = self.started(k=TOK)
        for _ in range(20):
            self.feed(s)
            self.t[0] += 2
            self.inst.tick()
        self.assertIn(rid, self.inst.live)
        self.assertFalse(s.stopping)
        self.assertEqual(len(self.launched), 1)
        self.assertTrue(self.inst.state(DID, RTOK)[1]["on"])                        # backstage still sees it on
        js = read("assets/kastr-presrec.js")
        self.assertRegex(js, r"Number\(r\.og\) \|\| 1\) > \(Number\(best\.og\)")    # the highest owner generation wins

    def test_the_deck_gone_ends_it(self):
        rid, s = self.started()
        self.feed(s)
        self.end_deck(DID)
        self.finish()
        self.assertEqual(s.meta["why"], "gone")


class Parts(Rig):
    def test_a_stalled_or_dead_recorder_carries_on_in_part_2(self):
        rid, s = self.started()
        self.feed(s, 2)
        self.t[0] += pr.STALL_S + 1
        self.inst.tick()
        self.assertEqual(s.part, 2)
        self.assertEqual(len(self.launched), 2)
        self.assertTrue(self.launched[0][3].killed)
        self.feed(s, 1)
        self.launched[1][3].code = 1                                                 # it crashes
        self.t[0] += 1
        self.inst.tick()
        self.assertEqual(s.part, 3)
        self.feed(s, 1)
        self.inst.deck_ended(DID)
        self.inst.done(rid, s.key, s.part)
        self.finish()
        names = sorted(os.listdir(os.path.join(self.d, "presrec", rid)))
        self.assertEqual(names, ["1.mp4", "2.mp4", "3.mp4", "meta.json"])
        p, fname = self.inst.file(rid, 2, self.inst._load(rid)["dk"])
        self.assertTrue(fname.endswith(" part 2.mp4"), fname)

    def test_boot_waits_while_the_page_says_hello(self):
        rid, s = self.started()
        for _ in range(int(pr.BOOT_S / 3) + 10):
            self.t[0] += 3
            self.assertEqual(self.inst.hello(rid, s.key)[0], 200)
            self.inst.tick()
        self.assertEqual(len(self.launched), 1)
        self.t[0] += pr.BOOT_S + 1                                                   # silent: a new recorder
        self.inst.tick()
        self.assertEqual(len(self.launched), 2)

    def test_relaunches_are_capped(self):
        rid, s = self.started()
        for _ in range(10):
            self.launched[-1][3].code = 1
            self.t[0] += 1
            self.inst.tick()
        self.assertLessEqual(len(self.launched), pr.RELAUNCH_MAX)
        self.assertIn("keeps stopping", self.inst.state(DID, TOK)[1].get("warn", ""))

    def test_a_reloaded_page_starts_the_next_part(self):
        rid, s = self.started()
        self.feed(s, 2)
        code, obj = self.inst.next_part(rid, s.key, 1)
        self.assertEqual(obj["part"], 2)
        self.assertEqual(self.inst.chunk(rid, s.key, 1, 2, b"x")[0], 409)

    def test_a_relay_host_restart_resumes_into_part_2(self):
        rid, s = self.started()
        self.feed(s, 3)
        inst2 = self.make()                                                          # KASTR restarted
        inst2.resume()
        self.assertIn(rid, inst2.live)
        self.inst = inst2
        self.inst.tick()
        s2 = inst2.live[rid]
        self.assertEqual(s2.part, 2)
        self.feed(s2, 1)
        inst2.deck_ended(DID)
        inst2.done(rid, s2.key, 2)
        self.finish()
        self.assertEqual([p["n"] for p in inst2._load(rid)["parts"]], [1, 2])

    def test_a_restart_after_the_deck_ended_just_finishes(self):
        rid, s = self.started()
        self.feed(s, 1)
        self.end_deck(DID)
        inst2 = self.make()
        inst2.resume()
        self.assertNotIn(rid, inst2.live)
        m = inst2._load(rid)
        self.assertEqual(m["state"], "done")
        self.assertEqual(m["why"], "restart")


class Absent(Rig):
    def test_never_seen_in_its_room_ends_with_no_file(self):
        rid, s = self.started()
        self.assertEqual(self.inst.done(rid, s.key, s.part, absent=True)[0], 200)
        self.assertEqual(s.meta["why"], "absent")
        self.finish()
        self.assertFalse(os.path.exists(os.path.join(self.d, "presrec", rid)))

    def test_the_page_gate(self):
        js = read("assets/kastr-presrec.js")
        self.assertIn("ABSENT_FIRST_MS = 90000", js)
        self.assertIn("ABSENT_LOST_MS = 180000", js)
        self.assertIn("x=absent", js)
        self.assertIn("v.pres.id === R.deck", js.replace("v && v.pres && ", ""))


class Caps(Rig):
    def test_disk_floor_refuses_and_stops(self):
        self.free[0] = 2 * pr.FREE_FLOOR - 1
        self.assertEqual(self.inst.start(DID, TOK)[0], 507)
        self.free[0] = 2 * pr.FREE_FLOOR
        rid, s = self.started()
        self.free[0] = 2 * pr.FREE_FLOOR - 1
        self.assertIn("disk is nearly full", self.inst.state(DID, TOK)[1].get("warn", ""))   # the warning, before the stop
        self.free[0] = pr.FREE_FLOOR - 1
        self.feed(s)
        self.assertTrue(s.stopping)
        self.assertEqual(s.meta["why"], "disk")
        self.assertIn("disk", s.meta["warn"])

    def test_size_cap_warns_then_stops(self):
        old = pr.MAX_BYTES
        pr.MAX_BYTES = 10000
        self.addCleanup(setattr, pr, "MAX_BYTES", old)
        rid, s = self.started()
        self.feed(s, 8)                                                              # 80 %
        self.assertIn("nearly at its size limit", self.inst.state(DID, TOK)[1].get("warn", ""))
        self.feed(s, 2)
        code, obj = self.inst.chunk(rid, s.key, s.part, s.seq, b"x" * 1000)
        self.assertTrue(obj["stop"])
        self.assertEqual(s.meta["why"], "size")
        self.finish()
        self.assertEqual(self.inst._load(rid)["size"], 10000)                       # the file is kept up to the cap

    def test_total_cap_and_live_cap(self):
        old = pr.TOTAL_MAX
        pr.TOTAL_MAX = 3000
        self.addCleanup(setattr, pr, "TOTAL_MAX", old)
        rid, s = self.started()
        self.feed(s, 3)
        self.inst.deck_ended(DID)
        self.finish()
        self.deck(DID)
        self.assertEqual(self.inst.start(DID, TOK)[0], 507)
        pr.TOTAL_MAX = old
        for i in range(pr.LIVE_MAX):
            did = ("%02d" % i) * 16
            self.deck(did)
            self.assertEqual(self.inst.start(did, TOK)[0], 200)
        self.assertEqual(self.inst.start(DID, TOK)[0], 429)

    def test_unavailable(self):
        self.relay.secured = False
        code, obj = self.inst.start(DID, TOK)
        self.assertEqual(code, 409)
        self.assertIn("access codes", obj["error"])
        self.relay.secured = True
        self.relay.running = lambda: False
        self.assertEqual(self.inst.start(DID, TOK)[0], 409)
        self.assertFalse(self.inst.state(DID, TOK)[1]["can"])


class Rights(Rig):
    def setUp(self):
        super().setUp()
        self.rid, s = self.started()
        self.feed(s, 2)
        self.inst.deck_ended(DID)
        self.inst.done(self.rid, s.key, s.part)
        self.finish()
        self.dk = self.inst._load(self.rid)["dk"]

    def ids(self, keys, admin=False, room=None):
        return [(r["id"], r["del"]) for r in self.inst.listing(keys, admin=admin, room=room)[1]["recordings"]]

    def test_download_only_for_presenters_backstage_admins(self):
        self.assertEqual(self.ids([{"d": DID, "k": TOK}]), [(self.rid, True)])
        self.assertEqual(self.ids([{"d": DID, "k": RTOK}]), [(self.rid, False)])
        self.assertEqual(self.ids([{"d": DID, "k": "nope"}]), [])
        self.assertEqual(self.ids([{"d": DID2, "k": TOK}]), [])
        self.assertEqual(self.ids([]), [])
        self.assertEqual(self.ids([], admin=True), [(self.rid, True)])
        self.assertEqual(self.ids([], admin=True, room="other"), [])
        self.assertEqual(self.ids([], admin=True, room=ROOM), [(self.rid, True)])
        p, fname = self.inst.file(self.rid, 1, self.dk)
        self.assertTrue(os.path.isfile(p))
        self.assertTrue(fname.startswith("Quarterly "), fname)
        self.assertEqual(self.inst.file(self.rid, 1, "wrong"), (None, None))
        self.assertEqual(self.inst.file(self.rid, 1, ""), (None, None))
        self.assertEqual(self.inst.file(self.rid, 9, self.dk), (None, None))

    def test_no_file_while_recording(self):
        self.deck(DID)
        rid, s = self.started()
        self.feed(s)
        dk = self.inst._load(rid)["dk"]
        self.assertEqual(self.inst.file(rid, 1, dk), (None, None))
        self.assertEqual(self.inst.delete(rid, [{"d": DID, "k": TOK}])[0], 409)

    def test_kept_until_deleted_by_a_presenter_or_admin(self):
        self.t[0] += 365 * 86400
        self.inst.tick()
        self.assertTrue(self.ids([], admin=True))
        self.assertEqual(self.inst.delete(self.rid, [{"d": DID, "k": RTOK}])[0], 403)
        self.assertEqual(self.inst.delete(self.rid, [])[0], 403)
        self.assertEqual(self.inst.delete(self.rid, [{"d": DID, "k": TOK}])[0], 200)
        self.assertEqual(self.inst.delete(self.rid, [], admin=True)[0], 404)

    def test_tokens_are_kept_as_digests_only(self):
        with open(os.path.join(self.d, "presrec", self.rid, "meta.json"), encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn(TOK, raw)
        self.assertNotIn(RTOK, raw)


class RecorderToken(Rig):
    def setUp(self):
        super().setUp()
        import kastr_relay as kr
        self.kr = kr
        pr._INST[0] = self.inst
        self.addCleanup(lambda: pr._INST.__setitem__(0, None))
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)
        self.rid, self.s = self.started()

    def admit(self):
        return "ka-%s-%s" % (self.s.gid, self.s.gkey)

    def test_the_grant_mints_a_watch_only_token_that_announces_nothing(self):
        self.assertTrue(pr.admit_ok(self.admit(), ROOM))
        self.assertFalse(pr.admit_ok(self.admit(), "other"))
        self.assertFalse(pr.admit_ok("ka-%s-%s" % (self.s.gid, "x" * 32), ROOM))
        obj, code = self.svc.token({"room": ROOM, "host": "web-1a2b", "admit": self.admit()}, peer="127.0.0.1")
        self.assertEqual(code, 200, obj)
        self.assertEqual(obj["role"], "viewer")
        claims = self.kr.verify_token(obj["tokens"]["member"], self.svc.key, time.time())
        self.assertEqual(claims["put"], ["~presrec/" + ROOM])
        self.assertEqual(claims["get"], ROOM)

    def test_a_wrong_or_spent_grant_is_no_recorder(self):
        obj, code = self.svc.token({"room": ROOM, "host": "web-1a2b", "admit": "ka-%s-%s" % (self.s.gid, "y" * 32)}, peer="127.0.0.1")
        self.assertNotEqual((obj.get("tokens") or {}).get("member") and
                            self.kr.verify_token(obj["tokens"]["member"], self.svc.key, time.time()).get("put"), ["~presrec/" + ROOM])
        self.inst.stop(DID, TOK)
        self.inst.done(self.rid, self.s.key, self.s.part)
        self.finish()
        self.assertFalse(pr.admit_ok(self.admit(), ROOM))


class Handler:
    def __init__(self, path, method="GET", host="127.0.0.1:9220", peer="127.0.0.1", body=b""):
        self.path, self.command = path, method
        self.headers = {"Host": host, "Content-Length": str(len(body))}
        self.client_address = (peer, 5555)
        self.rfile, self.wfile = io.BytesIO(body), io.BytesIO()
        self.code = None

    def send_response(self, c):
        self.code = c

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass

    def json(self):
        return json.loads(self.wfile.getvalue() or b"{}")


class Api(Rig):
    def setUp(self):
        super().setUp()
        pr._INST[0] = self.inst
        self.addCleanup(lambda: pr._INST.__setitem__(0, None))

    def call(self, *a, **kw):
        h = Handler(*a, **kw)
        self.assertTrue(pr.handle_api(h))
        return h

    def test_switch_routes(self):
        self.assertEqual(self.call("/api/presrec/start?deck=%s&k=%s" % (DID, TOK)).code, 405)
        h = self.call("/api/presrec/start?deck=%s&k=%s" % (DID, TOK), "POST", body=b'{"name":"Q","by":"Alice"}')
        self.assertEqual(h.code, 200)
        self.assertTrue(h.json()["on"])
        self.assertEqual(self.call("/api/presrec/state?deck=%s&k=nope" % DID).code, 403)
        self.assertEqual(self.call("/api/presrec/stop?deck=%s&k=%s" % (DID, RTOK), "POST").code, 200)
        self.assertFalse(pr.handle_api(Handler("/api/pres/x")))

    def test_the_recorders_own_calls_need_its_host_on_this_machine(self):
        rid, s = self.started()
        path = "/api/presrec/%s/hello?k=%s" % (rid, s.key)
        self.assertEqual(self.call(path).code, 403)                                            # a normal page
        self.assertEqual(self.call(path, host="presrec.localhost:9220", peer="10.0.0.5").code, 403)   # not this machine
        self.assertEqual(self.call(path, host="presrec.localhost:9220").code, 200)
        h = self.call("/api/presrec/%s/chunk?k=%s&p=1&s=0&t=2000" % (rid, s.key), "POST", host="presrec.localhost:9220", body=b"abc")
        self.assertEqual(h.code, 200)
        self.assertEqual(s.meta["size"], 3)

    def test_no_instance(self):
        pr._INST[0] = None
        self.assertEqual(self.call("/api/presrec/state").code, 503)


class Pages(unittest.TestCase):
    def test_the_switch_is_a_toggle(self):
        js = read("assets/kastr-presrec.js")
        self.assertIn('<label class="kprsw"', js)
        self.assertRegex(js, r'<span class="switch sm"><input type="checkbox" aria-label="Record the presentation"><i></i></span>')
        for m in re.finditer(r'type="checkbox"', js):
            self.assertIn('class="switch', js[max(0, m.start() - 60):m.start()], "a bare checkbox")

    def test_template_row_and_end(self):
        pjs = read("assets/kastr-pres.js")
        i = pjs.index("const TPL_OPTS = [")
        tbl = pjs[i:pjs.index("];", i)]
        self.assertIn('{ key: "rec", sw: 1, text: "Record the presentation", def: 0', tbl)
        self.assertIn("m.recWant = v ? 1 : 0", tbl)
        self.assertIn("want: !!mine.recWant", pjs)
        e = pjs.index("function endPress()")
        body = pjs[e:pjs.index("function endNow()", e)]
        self.assertLess(body.index("__presrec?.endWait?.(v0.id)"), body.index("endNow();"))
        self.assertIn("Promise.resolve(fin)", body)
        js = read("assets/kastr-presrec.js")
        self.assertIn("recOn:", js)
        self.assertIn("endWait:", js)
        self.assertIn("if (d.own && d.want) S.want = Date.now()", js)

    def test_marked_blocks_in_shared_files(self):
        self.assertEqual(read("assets/kastr-pres.js").count("// 0.21.92 H: record the presentation"), 3)
        self.assertIn("0.21.92 H: record the presentation", read("moq-watch-lite.html"))
        self.assertIn("kastr_presrec.deck_ended(state_dir, did)", read("kastr_pres.py"))
        self.assertIn("kastr_presrec.admit_ok(admit_pr, slug)", read("kastr_relay.py"))
        self.assertIn("/assets/kastr-presrec.js", read("kastr_serve.py"))

    def test_the_room_record_carries_only_on_and_id(self):
        js = read("assets/kastr-presrec.js")
        self.assertIn('rec: S.st.on ? { on: 1, id: String(S.st.id || "") } : { on: 0 }', js)

    def test_line_endings(self):
        for rel in ("kastr_presrec.py", "assets/kastr-presrec.js", "assets/kastr-pres.js"):
            with open(os.path.join(HERE, rel), "rb") as f:
                self.assertNotIn(b"\r\n", f.read(), rel)
        with open(os.path.join(HERE, "moq-watch-lite.html"), "rb") as f:
            b = f.read()
        self.assertEqual(b.count(b"\n"), b.count(b"\r\n"))


if __name__ == "__main__":
    unittest.main()
