# -*- coding: utf-8 -*-
"""v0.21.96 SCHEDULED MEETINGS (Kenton 2026-10-28: "templates to also be setup to configure a webmeeting, like a teams meeting.
Where I can schedule it for a weekly/daily meeting, or just a 1 time meeting"; 2026-10-30: "add scheduled meetings to the next
update"). The store, the recurrence rules (time zone NAME + local wall time, so a weekly 09:00 stays 09:00 across a daylight-saving
change), the calendar file, and the hub's side: hidden meeting rooms minted only for the invited inside a window, guests by link,
"Requires the host to join", the template applied by the first invitee in. Loopback only, no outside network."""
import calendar, datetime as dt, hashlib, json, os, re, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_meetings as M  # noqa: E402
import kastr_relay as kr  # noqa: E402
import kastr_tz as tz  # noqa: E402

DEN = "America/Denver"
MYCODE = "kenton-myroom-1"     # lab values (only their digests are ever stored)
ADACODE = "ada-myroom-0001"
BOBCODE = "bob-myroom-0002"
SALT = "00112233aabbccdd"
CODE = "Gate-Code-42"


def utc(*a):
    return calendar.timegm(dt.datetime(*a).timetuple())


def meeting(**kw):
    m = {"id": "m0123456789ab", "title": "Stand-up", "room": "mt-0123456789ab", "org": {"name": "Kenton Jeffery"}, "tz": DEN,
         "start": "2026-10-29T09:00", "dur": 30, "freq": "once"}
    m.update(kw)
    c, why = M.clean_meeting(m)
    assert c is not None, why
    return c


def wall_in(zone, ts):
    """The local wall time string (minute precision) at UTC epoch ts in `zone`."""
    return M.wall_str(tz.to_local(zone, ts)[0])


class TimeZones(unittest.TestCase):
    def test_denver_dst_both_ways(self):
        self.assertEqual(tz.to_utc(DEN, dt.datetime(2026, 10, 29, 9, 0)), utc(2026, 10, 29, 15, 0))   # MDT (UTC-6)
        self.assertEqual(tz.to_utc(DEN, dt.datetime(2026, 11, 5, 9, 0)), utc(2026, 11, 5, 16, 0))     # MST (UTC-7)
        self.assertEqual(tz.offset(DEN, utc(2026, 7, 1)), -6 * 3600)
        self.assertEqual(tz.offset(DEN, utc(2026, 12, 1)), -7 * 3600)

    def test_gap_and_fold(self):
        # 2027-03-14 02:30 does not exist in Denver: read with the offset before the gap (lands at 03:30 MDT)
        self.assertEqual(tz.to_utc(DEN, dt.datetime(2027, 3, 14, 2, 30)), utc(2027, 3, 14, 9, 30))
        # 2026-11-01 01:30 happens twice: the first (MDT)
        self.assertEqual(tz.to_utc(DEN, dt.datetime(2026, 11, 1, 1, 30)), utc(2026, 11, 1, 7, 30))

    def test_southern_and_no_dst(self):
        self.assertEqual(tz.offset("Australia/Sydney", utc(2026, 1, 15)), 11 * 3600)
        self.assertEqual(tz.offset("Australia/Sydney", utc(2026, 7, 15)), 10 * 3600)
        self.assertEqual(tz.offset("Asia/Kolkata", utc(2026, 7, 15)), 19800)
        self.assertEqual(tz.offset("UTC", utc(2026, 7, 15)), 0)
        self.assertTrue(tz.known(DEN))
        self.assertFalse(tz.known("Mars/Olympus"))

    def test_vtimezone(self):
        v = tz.vtimezone(DEN)
        self.assertIn("TZID:America/Denver", v)
        self.assertIn("RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", v)
        self.assertIn("RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", v)
        self.assertIn("TZOFFSETTO:-0600", v)
        self.assertIsNone(tz.vtimezone("Mars/Olympus"))


class Recurrence(unittest.TestCase):
    def test_clean_rules(self):
        self.assertEqual(M.clean_meeting(dict(meeting(), title=" "))[1], "give the meeting a title")
        self.assertEqual(M.clean_meeting(dict(meeting(), tz="Nowhere/Here"))[1], "unknown time zone")
        self.assertEqual(M.clean_meeting(dict(meeting(), start="2026-13-01T09:00"))[1], "pick a start date and time")
        w = meeting(freq="weekly")
        self.assertEqual(w["days"], [3])                     # a weekly meeting with no day: the start's day (Thursday)
        self.assertEqual(meeting(freq="daily", days=[1, 2])["days"], [])
        self.assertEqual(meeting(dur=1)["dur"], M.DUR_MIN)
        self.assertEqual(meeting(dur=10000)["dur"], M.DUR_MAX)
        self.assertEqual(M.clean_meeting(dict(meeting(freq="weekly"), until="2026-10-01"))[1], "the repeat ends before the first meeting")
        org = meeting(people=["Kenton Jeffery", "Ada", {"name": " ada "}, {"name": "Bob", "pres": True}])
        self.assertEqual([(p["name"], p["pres"]) for p in org["people"]], [("Ada", False), ("Bob", True)])   # the organizer is not a guest of their own
        self.assertEqual(M.role_of(org, "kenton jeffery"), "org")
        self.assertEqual(M.role_of(org, "bob"), "pres")
        self.assertEqual(M.role_of(org, "ada"), "in")
        self.assertEqual(M.role_of(org, "carlo"), "")

    def test_weekly_across_dst_keeps_the_wall_time(self):
        m = meeting(freq="weekly", days=[3])
        occ = M.occurrences(m, utc(2026, 10, 28), utc(2026, 11, 13))
        self.assertEqual([o["local"] for o in occ], ["2026-10-29T09:00", "2026-11-05T09:00", "2026-11-12T09:00"])
        self.assertEqual(occ[0]["start"], utc(2026, 10, 29, 15, 0))
        self.assertEqual(occ[1]["start"], utc(2026, 11, 5, 16, 0))     # an hour later in UTC: still 09:00 in Denver
        self.assertEqual(occ[1]["end"] - occ[1]["start"], 30 * 60)

    def test_daily_until_and_weekdays(self):
        m = meeting(freq="daily", until="2026-11-02")
        self.assertEqual(len(M.occurrences(m, utc(2026, 10, 1), utc(2026, 12, 1))), 5)
        w = meeting(freq="weekly", days=[0, 2, 4], start="2026-11-02T08:00")   # Mon, Wed, Fri
        keys = [o["key"][:10] for o in M.occurrences(w, utc(2026, 11, 1), utc(2026, 11, 9))]
        self.assertEqual(keys, ["2026-11-02", "2026-11-04", "2026-11-06"])
        self.assertIsNone(M.last_end(meeting(freq="weekly")))
        self.assertEqual(M.last_end(m), utc(2026, 11, 2, 16, 30))

    def test_one_occurrence_moved_or_cancelled(self):
        m = meeting(freq="weekly", ex={"2026-11-05T09:00": {"start": "2026-11-06T10:00", "title": "Moved"},
                                       "2026-11-12T09:00": {"cancel": 1}, "2026-11-13T09:00": {"cancel": 1}})
        occ = M.occurrences(m, utc(2026, 10, 28), utc(2026, 11, 20))
        self.assertEqual([(o["key"], o["local"], o["title"]) for o in occ],
                         [("2026-10-29T09:00", "2026-10-29T09:00", "Stand-up"), ("2026-11-05T09:00", "2026-11-06T10:00", "Moved"),
                          ("2026-11-19T09:00", "2026-11-19T09:00", "Stand-up")])
        self.assertTrue(M.has_original(m, "2026-11-12T09:00"))
        self.assertFalse(M.has_original(m, "2026-11-13T09:00"))      # not a Thursday: never an occurrence
        with_c = M.occurrences(m, utc(2026, 11, 10), utc(2026, 11, 14), cancelled=True)
        self.assertTrue(with_c[0]["cancelled"])
        far = M.clean_ex({"2026-11-05T09:00": {"start": "2027-03-01T09:00"}})
        self.assertNotIn("2026-11-05T09:00", far)                   # a move over 31 days is dropped

    def test_window_early_live_and_overrun(self):
        m = meeting()
        s = utc(2026, 10, 29, 15, 0)
        self.assertEqual(M.next_occ(m, s - 3 * 3600)["state"], "later")
        self.assertEqual(M.next_occ(m, s - 1800)["state"], "soon")
        self.assertIsNone(M.window(m, s - M.EARLY_S - 1))
        self.assertIsNotNone(M.window(m, s - M.EARLY_S + 1))           # opens 10 minutes before
        self.assertIsNotNone(M.window(m, s + 29 * 60))
        self.assertIsNone(M.window(m, s + 31 * 60))                     # over and nobody in
        self.assertIsNotNone(M.window(m, s + 31 * 60, live=True))       # still going: open while someone is in
        self.assertIsNone(M.window(m, s + 30 * 60 + M.OVERRUN_S + 1, live=True))   # but never days later
        self.assertFalse(M.series_over(m, s + 30 * 60))
        self.assertTrue(M.series_over(m, s + 30 * 60 + M.EMPTY_S + 1))
        done = dict(m, done={"2026-10-29T09:00": s + 600})
        self.assertIsNone(M.window(done, s + 700, live=True))           # ended with End: never reopens
        self.assertIsNone(M.next_occ(dict(m, cancelled=1), s))
        # a weekly meeting's next one after this week's ended
        w = meeting(freq="weekly")
        self.assertEqual(M.next_occ(w, s + 3600)["key"], "2026-11-05T09:00")


class Calendar(unittest.TestCase):
    def test_ics_series(self):
        m = meeting(freq="weekly", days=[3], until="2026-12-31", note="Agenda; notes, etc.",
                    ex={"2026-11-12T09:00": {"cancel": 1}, "2026-11-19T09:00": {"start": "2026-11-19T10:00"}})
        t = M.ics(m, utc(2026, 10, 1), join_url="https://kastr.example/join#meet=m0123456789ab", host_name="KASTR")
        self.assertTrue(t.endswith("\r\n"))
        self.assertNotIn("\n", t.replace("\r\n", ""))
        self.assertTrue(all(len(x.encode("utf-8")) <= 75 for x in t.split("\r\n")))
        flat = t.replace("\r\n ", "")
        self.assertIn("BEGIN:VTIMEZONE", flat)
        self.assertIn("DTSTART;TZID=America/Denver:20261029T090000", flat)
        self.assertIn("RRULE:FREQ=WEEKLY;BYDAY=TH;UNTIL=20270101T065900Z", flat)
        self.assertIn("EXDATE;TZID=America/Denver:20261112T090000", flat)
        self.assertIn("RECURRENCE-ID;TZID=America/Denver:20261119T090000", flat)
        self.assertIn("DTSTART;TZID=America/Denver:20261119T100000", flat)
        self.assertIn("DESCRIPTION:Agenda\\; notes\\, etc.", flat)
        self.assertIn("UID:m0123456789ab@kastr", flat)
        self.assertIn("METHOD:PUBLISH", flat)
        self.assertIn("URL:https://kastr.example/join#meet=m0123456789ab", flat)
        self.assertEqual(M.ics_name(m), "Stand-up.ics")

    def test_ics_cancel_and_utc_fallback(self):
        m = meeting(cancelled=1, seq=4)
        t = M.ics(m, utc(2026, 10, 1)).replace("\r\n ", "")
        self.assertIn("METHOD:CANCEL", t)
        self.assertIn("STATUS:CANCELLED", t)
        self.assertIn("SEQUENCE:4", t)
        # a zone whose rule iCalendar cannot say (no bundled rule) -> UTC times
        orig = tz.vtimezone
        try:
            tz.vtimezone = lambda name: None
            u = M.ics(meeting(), utc(2026, 10, 1)).replace("\r\n ", "")
        finally:
            tz.vtimezone = orig
        self.assertIn("DTSTART:20261029T150000Z", u)
        self.assertNotIn("VTIMEZONE", u)


class Book(unittest.TestCase):
    def test_put_caps_ids_and_files(self):
        d = tempfile.mkdtemp()
        b = M.MeetingBook(d)
        saved = []
        b.on_save = lambda: saved.append(1)
        m = dict(meeting(), id="", room="")
        c, why, code = b.put(m, new=True)
        self.assertIsNone(why)
        self.assertRegex(c["id"], M.MID_RE)
        self.assertTrue(M.is_room(c["room"]) and c["own"])
        self.assertEqual(c["seq"], 0)
        c2, _w, _c = b.put(dict(c, title="Stand-up (new time)"))
        self.assertEqual(c2["seq"], 1)
        self.assertGreater(c2["upd"], 0)
        self.assertEqual(len(saved), 2)
        again = M.MeetingBook(d)                                        # persisted
        self.assertEqual(again.get(c["id"])["title"], "Stand-up (new time)")
        with open(os.path.join(d, "meetings", "meetings.json"), encoding="utf-8") as f:
            self.assertNotIn("ki-", f.read())                           # never a link token
        self.assertEqual(b.by_room(c["room"])["id"], c["id"])
        self.assertTrue(b.mark_done(c["id"], "2026-10-29T09:00"))
        self.assertFalse(b.mark_done(c["id"], "2026-10-29T09:00"))

    def test_bundle_merge_tombstones_and_done(self):
        a, b = M.MeetingBook(tempfile.mkdtemp()), M.MeetingBook(tempfile.mkdtemp())
        x, _w, _c = a.put(dict(meeting(), id="", room=""), new=True)
        y, _w, _c = a.put(dict(meeting(title="Retro"), id="", room=""), new=True)
        self.assertEqual(b.import_(a.export()), 2)
        b.mark_done(x["id"], "2026-10-29T09:00")
        b.delete(y["id"])
        z, _w, _c = b.put(dict(b.get(x["id"]), title="Stand-up!"))
        a.merge(b.export())                                             # the hand-back
        self.assertIsNone(a.get(y["id"]))                               # a deletion sticks
        self.assertEqual(a.get(x["id"])["title"], "Stand-up!")
        self.assertIn("2026-10-29T09:00", a.get(x["id"])["done"])
        a.merge({"meetings": {y["id"]: y}})                             # an old copy never brings it back
        self.assertIsNone(a.get(y["id"]))

    def test_sweep_and_renames(self):
        b = M.MeetingBook(tempfile.mkdtemp())
        old, _w, _c = b.put(dict(meeting(start="2026-01-05T09:00"), id="", room=""), new=True)
        can, _w, _c = b.put(dict(meeting(start="2027-01-05T09:00"), id="", room="", cancelled=utc(2026, 9, 1)), new=True)
        keep, _w, _c = b.put(dict(meeting(freq="weekly", room="beta", people=["Ada"]), id=""), new=True)
        gone = b.sweep(utc(2026, 10, 1))
        self.assertEqual(sorted(g["id"] for g in gone), sorted([old["id"], can["id"]]))
        self.assertEqual([m["id"] for m in b.all()], [keep["id"]])
        self.assertFalse(keep["own"])
        b.rename_person("ada", "ada l", "Ada L")
        b.rename_person("kenton jeffery", "kenton j", "Kenton J")
        k = b.get(keep["id"])
        self.assertEqual(k["people"][0]["name"], "Ada L")
        self.assertEqual(k["org"], {"nk": "kenton j", "name": "Kenton J"})
        b.rename_room("beta", "gamma")
        self.assertEqual(b.get(keep["id"])["room"], "gamma")

    def test_caps(self):
        b = M.MeetingBook(tempfile.mkdtemp())
        orig = M.PER_PERSON_MAX
        try:
            M.PER_PERSON_MAX = 2
            for _ in range(2):
                self.assertIsNone(b.put(dict(meeting(), id="", room=""), new=True)[1])
            self.assertEqual(b.put(dict(meeting(), id="", room=""), new=True)[2], 409)
        finally:
            M.PER_PERSON_MAX = orig

    def test_derived_secrets(self):
        k = os.urandom(32)
        s1, s2 = M.link_secret(k, "m0123456789ab", 0), M.link_secret(k, "m0123456789ab", 1)
        self.assertEqual(len(s1), 32)
        self.assertNotEqual(s1, s2)
        self.assertEqual(s1, M.link_secret(k, "m0123456789ab", 0))
        self.assertRegex(M.link_id(k, "m0123456789ab", 0), r"^[0-9a-f]{8}$")
        self.assertRegex(M.ics_key(k, "m0123456789ab", 0), r"^[0-9a-f]{32}$")
        self.assertNotEqual(M.ics_key(k, "m0123456789ab", 0), M.ics_key(os.urandom(32), "m0123456789ab", 0))


# ---- the hub -------------------------------------------------------------------------------------------------------------

def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


class Hub(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store(self.dir))
        self.st = self.svc.store
        for name, code in (("Kenton Jeffery", MYCODE), ("Ada Lovelace", ADACODE), ("Bob Ross", BOBCODE)):
            o, c = kr.personal_op(self.st, {"op": "create", "name": name, "code": code, "access": "pub-1"}, "10.0.0.5")
            assert c == 200, o
        self.lobby = self.mint("main", "kenton-pc-1a2b")
        self.ada_lobby = self.mint("main", "ada-pc-0a0a")
        self.carlo_lobby = self.mint("main", "carlo-pc-3c4d")

    def tearDown(self):
        self.svc.close()

    def mint(self, room, host, code="pub-1", **kw):
        o, c = self.svc.token(dict({"room": room, "code": code, "host": host}, **kw), "10.0.0.7")
        assert c == 200, o
        return o["tokens"]["member"]

    def api(self, body, tok=None, peer="10.0.0.7"):
        return self.svc.meetings_api(body, "Bearer " + (tok or self.lobby), peer)

    def me(self, who="k"):
        return {"k": {"pname": "Kenton Jeffery", "pcode": MYCODE}, "a": {"pname": "Ada Lovelace", "pcode": ADACODE},
                "b": {"pname": "Bob Ross", "pcode": BOBCODE}}[who]

    def schedule(self, start_in=180, **kw):
        """A meeting starting `start_in` seconds from now (Denver wall time), organized by Kenton."""
        start = wall_in(DEN, time.time() + start_in)
        d = dict({"title": "Ops sync", "tz": DEN, "start": start, "dur": 30, "freq": "once",
                  "people": [{"name": "Ada Lovelace"}, {"name": "Bob Ross", "pres": True}]}, **kw)
        o, c = self.api(dict(self.me(), op="save", meeting=d))
        self.assertEqual(c, 200, o)
        return o["meeting"]

    def join(self, m, host, who=None, **kw):
        body = dict({"room": m["room"], "host": host}, **kw)
        if who:
            body["meet"] = self.me(who)
        return self.svc.token(body, "10.0.0.8")

    # ---- scheduling + the list
    def test_schedule_one_time_and_list_only_invited(self):
        m = self.schedule()
        self.assertTrue(M.is_room(m["room"]))
        self.assertEqual(m["role"], "org")
        self.assertTrue(m["manage"])
        self.assertEqual(m["next"]["state"], "open")
        rec = self.st.room(m["room"])
        self.assertEqual(rec["meeting"], m["id"])
        self.assertTrue(rec["persistent"])
        # hidden: never in the rooms list, never a kept room, never in the codes status; its chat is kept
        self.assertNotIn(m["room"], [r["slug"] for r in self.st.rooms_public()])
        self.assertNotIn(m["room"], self.st.kept_slugs())
        self.assertIn(m["room"], self.st.chat_kept_slugs())
        self.assertNotIn(m["room"], [s for s in self.st.room_slugs() if not kr.is_personal(s) and not kr.is_meet_room(s)])   # Relay.codes_status's filter
        # Ada (invited) sees it; Carlo (not invited) does not; a wrong code is refused and counted
        lst, c = self.api(dict(self.me("a"), op="list"), self.ada_lobby)
        self.assertEqual(c, 200)
        self.assertEqual([(x["id"], x["role"], x["manage"]) for x in lst["meetings"]], [(m["id"], "in", False)])
        lst, c = self.api({"op": "list", "pname": "Carlo", "pcode": "nope-nope-1"}, self.carlo_lobby, peer="10.0.0.9")
        self.assertEqual(c, 403)
        lst, c = self.api({"op": "list"}, self.carlo_lobby)
        self.assertEqual((c, lst["meetings"]), (200, []))
        self.assertFalse(lst["can"]["own"])
        # a fleet admin does not see another person's own-room meeting unless invited
        adm = self.mint("main", "boss-pc-9999", code="adm-1")
        lst, c = self.api({"op": "list"}, adm)
        self.assertEqual(lst["meetings"], [])

    def test_weekly_dst_and_past_one_time_refused(self):
        o, c = self.api(dict(self.me(), op="save", meeting={"title": "Weekly", "tz": DEN, "start": "2027-10-28T09:00", "dur": 45,
                                                             "freq": "weekly", "days": [3], "people": ["Ada Lovelace"]}))
        self.assertEqual(c, 200, o)
        mid = o["meeting"]["id"]
        m = self.st.meetbook.get(mid)
        occ = M.occurrences(m, utc(2027, 10, 27), utc(2027, 11, 12))
        # 2027: daylight saving ends Sunday Nov 7 -> Nov 4 is still MDT (15:00Z), Nov 11 is MST (16:00Z); 09:00 local throughout
        self.assertEqual([o["start"] for o in occ], [utc(2027, 10, 28, 15), utc(2027, 11, 4, 15), utc(2027, 11, 11, 16)])
        self.assertEqual({o["local"][11:] for o in occ}, {"09:00"})
        o, c = self.api(dict(self.me(), op="save", meeting={"title": "Old", "tz": DEN, "start": "2020-01-01T09:00", "freq": "once"}))
        self.assertEqual(c, 400)
        self.assertIn("passed", o["error"])
        o, c = self.api({"op": "save", "meeting": {"title": "Who", "tz": DEN, "start": "2027-01-01T09:00"}})
        self.assertEqual(c, 403)

    # ---- joining
    def test_invited_join_at_start_with_the_template_lease(self):
        m = self.schedule(tpl="")
        o, c = self.join(m, "ada-pc-0a0a", "a")
        self.assertEqual(c, 200, o)
        self.assertEqual(o["meet"]["role"], "in")
        self.assertNotIn("registry", o["tokens"])                      # hidden: no registry record, no public announce
        cl = kr.verify_token(o["tokens"]["member"], self.svc.key)
        self.assertEqual(cl["get"], m["room"])
        self.assertEqual(cl["put"], [m["room"] + "/ada-pc-0a0a"])
        self.assertEqual(cl["mt"], m["id"])
        self.assertFalse(kr.claims_admin_any(cl))
        self.assertEqual(kr.claims_identity(cl), (m["room"], "ada-pc-0a0a"))
        self.assertLessEqual(o["exp"], int(time.time()) + kr.TOKEN_TTL)
        # not invited / no name / wrong code
        o, c = self.svc.token({"room": m["room"], "host": "carlo-pc-3c4d", "meet": {"pname": "Carlo", "pcode": "whatever-1"}}, "10.0.0.9")
        self.assertEqual(c, 403)
        o, c = self.svc.token({"room": m["room"], "host": "carlo-pc-3c4d", "code": "pub-1"}, "10.0.0.9")
        self.assertEqual((c, o["meet"]["verdict"]), (403, "who"))     # an access code is not an invitation
        o, c = self.svc.token({"room": m["room"], "host": "carlo-pc-3c4d", "meet": {"pname": "Ada Lovelace", "pcode": "wrong-wrong"}},
                              "10.0.0.9")
        self.assertEqual((c, o["meet"]["verdict"]), (403, "wrong"))

    def test_template_lease_first_invitee_applies_once(self):
        tb = self.st.tplbook
        t, why, code = tb.put({"id": "t000000000000", "scope": "me", "owner": "kenton jeffery", "ownerName": "Kenton Jeffery",
                               "room": "x", "name": "Standup layout", "view": {"mode": "grid"}}, new=True)
        self.assertIsNone(why, why)
        m = self.schedule(tpl=t["id"])
        o1, c1 = self.join(m, "ada-pc-0a0a", "a")
        self.assertEqual(c1, 200, o1)
        self.assertEqual(o1["meet"].get("apply"), t["id"])
        o2, c2 = self.join(m, "bob-pc-0b0b", "b")
        self.assertNotIn("apply", o2["meet"])                          # the lease is Ada's
        tok = o1["tokens"]["member"]
        # Ada (not the template's owner) may read and apply it in the meeting's room while she holds the lease
        g, c = self.svc.templates_api({"op": "get", "id": t["id"]}, "Bearer " + tok, "10.0.0.8")
        self.assertEqual(c, 200, g)
        g, c = self.svc.templates_api({"op": "get", "id": t["id"]}, "Bearer " + o2["tokens"]["member"], "10.0.0.8")
        self.assertEqual(c, 403)
        a, c = self.svc.templates_api({"op": "apply", "id": t["id"]}, "Bearer " + tok, "10.0.0.8")
        self.assertEqual(c, 200, a)
        o3, _c = self.join(m, "ada-pc-0a0a", "a")
        self.assertNotIn("apply", o3["meet"])                          # applied: never again this occurrence

    def test_early_and_over(self):
        m = self.schedule(start_in=7200)
        o, c = self.join(m, "ada-pc-0a0a", "a")
        self.assertEqual((c, o["meet"]["verdict"]), (403, "early"))
        self.assertEqual(o["meet"]["next"]["opens"], o["meet"]["next"]["start"] - M.EARLY_S)

    def test_host_required_lobby(self):
        m = self.schedule(host=True)
        o, c = self.join(m, "ada-pc-0a0a", "a")
        self.assertEqual((c, o["meet"]["verdict"]), (403, "wait"))
        o, c = self.join(m, "kenton-pc-1a2b", "k")                    # the organizer arrives
        self.assertEqual(c, 200, o)
        b, c = self.api({"op": "beat"}, o["tokens"]["member"])
        self.assertEqual(c, 200, b)
        self.assertTrue(b["live"]["hostIn"])
        o, c = self.join(m, "ada-pc-0a0a", "a")
        self.assertEqual(c, 200, o)
        # a presenter counts as the host too
        m2 = self.schedule(host=True, title="Second")
        ob, c = self.join(m2, "bob-pc-0b0b", "b")
        self.assertEqual(c, 200, ob)

    def test_guest_link(self):
        m = self.schedule(guests=True)
        org = self.join(m, "kenton-pc-1a2b", "k")[0]["tokens"]["member"]
        lk, c = self.api({"op": "link", "id": m["id"]}, org)
        self.assertEqual(c, 200, lk)
        tok = lk["token"]
        self.assertRegex(tok, kr.INVITE_RE)
        self.assertEqual(self.api({"op": "link", "id": m["id"]}, org)[0]["token"], tok)   # the same link every copy
        with open(os.path.join(self.dir, "meetings", "meetings.json"), encoding="utf-8") as f:
            self.assertNotIn(tok.split("-")[2], f.read())               # never stored
        o, c = self.svc.token({"room": m["room"], "host": "guest-pc-5e5e", "invite": tok}, "10.0.0.20")
        self.assertEqual(c, 200, o)
        self.assertTrue(o["guest"])
        cl = kr.verify_token(o["tokens"]["member"], self.svc.key)
        self.assertEqual(cl["inv"], lk["token"].split("-")[1])
        # Ada (invited, not a presenter) cannot copy the guest link; a meeting without guests has none
        ada = self.join(m, "ada-pc-0a0a", "a")[0]["tokens"]["member"]
        self.assertEqual(self.api({"op": "link", "id": m["id"]}, ada)[1], 403)
        m2 = self.schedule(title="No guests")
        self.assertEqual(self.api(dict(self.me(), op="link", id=m2["id"]))[1], 409)
        # guests switched off: the link stops
        d = dict(self.st.meetbook.get(m["id"]), guests=False)
        o, c = self.api(dict(self.me(), op="save", meeting={k: d[k] for k in ("id", "title", "tz", "start", "dur", "freq", "people", "guests")}))
        self.assertEqual(c, 200, o)
        o, c = self.svc.token({"room": m["room"], "host": "guest-pc-5e5e", "invite": tok}, "10.0.0.20")
        self.assertEqual(c, 403)

    def test_ics_and_calendar_link(self):
        m = self.schedule()
        o, c = self.api(dict(self.me("a"), op="ics", id=m["id"], joinUrl="https://kastr.example/join#meet=" + m["id"]), self.ada_lobby)
        self.assertEqual(c, 200, o)
        self.assertIn("BEGIN:VCALENDAR", o["text"])
        self.assertEqual(o["name"], "Ops-sync.ics")
        o, c = self.api(dict(self.me("a"), op="ics", id=m["id"], joinUrl="javascript:alert(1)"), self.ada_lobby)
        self.assertNotIn("javascript", o["text"])
        lk, c = self.api(dict(self.me("a"), op="icsLink", id=m["id"]), self.ada_lobby)
        self.assertEqual(c, 200)
        q = dict(x.split("=") for x in lk["path"].split("?")[1].split("&"))
        body, code, name = self.svc.meetings_ics_get({"m": [q["m"]], "k": [q["k"]]})
        self.assertEqual(code, 200)
        self.assertIn(b"UID:%s@kastr" % m["id"].encode(), body)
        self.assertEqual(self.svc.meetings_ics_get({"m": [q["m"]], "k": ["0" * 32]})[1], 404)
        # Carlo (not invited) gets nothing
        self.assertEqual(self.api({"op": "ics", "id": m["id"]}, self.carlo_lobby)[1], 403)

    def test_occurrence_edit_and_cancel_series(self):
        o, c = self.api(dict(self.me(), op="save", meeting={"title": "Weekly", "tz": DEN, "start": "2027-10-28T09:00",
                                                             "freq": "weekly", "people": ["Ada Lovelace"]}))
        m = o["meeting"]
        o, c = self.api(dict(self.me(), op="occ", id=m["id"], key="2027-11-04T09:00", cancel=True))
        self.assertEqual(c, 200, o)
        self.assertEqual(o["meeting"]["ex"], {"2027-11-04T09:00": {"cancel": 1}})
        self.assertEqual(self.api(dict(self.me(), op="occ", id=m["id"], key="2027-11-05T09:00", cancel=True))[1], 400)
        o, c = self.api(dict(self.me(), op="occ", id=m["id"], key="2027-11-11T09:00", start="2027-11-11T11:00", title="Later"))
        self.assertEqual(c, 200, o)
        self.assertEqual(self.api(dict(self.me("a"), op="occ", id=m["id"], key="2027-11-18T09:00", cancel=True), self.ada_lobby)[1], 403)
        o, c = self.api(dict(self.me(), op="cancel", id=m["id"]))
        self.assertEqual(c, 200, o)
        self.assertTrue(o["meeting"]["cancelled"])
        self.assertIsNone(self.st.room(m["room"]))                     # its own room is gone
        lst, _c = self.api(dict(self.me("a"), op="list"), self.ada_lobby)
        self.assertTrue(lst["meetings"][0]["cancelled"])               # invitees still see it was cancelled
        ics, _c = self.api(dict(self.me("a"), op="ics", id=m["id"]), self.ada_lobby)
        self.assertIn("METHOD:CANCEL", ics["text"])
        o, c = self.join(m, "ada-pc-0a0a", "a")
        self.assertEqual((c, o["meet"]["verdict"]), (403, "cancelled"))
        self.assertEqual(self.api(dict(self.me(), op="delete", id=m["id"]))[1], 200)
        self.assertEqual(self.api(dict(self.me(), op="get", id=m["id"]))[1], 404)

    def test_end_closes_a_one_time_room(self):
        m = self.schedule()
        tok = self.join(m, "bob-pc-0b0b", "b")[0]["tokens"]["member"]  # a presenter
        ada = self.join(m, "ada-pc-0a0a", "a")[0]["tokens"]["member"]
        self.assertEqual(self.api({"op": "end", "id": m["id"]}, ada)[1], 403)
        o, c = self.api({"op": "end", "id": m["id"]}, tok)
        self.assertEqual(c, 200, o)
        self.assertTrue(o["closed"])
        self.assertIsNone(self.st.room(m["room"]))
        o, c = self.join(m, "ada-pc-0a0a", "a")
        self.assertEqual((c, o["meet"]["verdict"]), (403, "over"))

    def test_existing_room_meeting(self):
        o, c = kr.register_room(self.st, {"slug": "beta", "salt": SALT, "hash": hashlib.sha256((SALT + CODE).encode()).hexdigest(),
                                          "access": "pub-1", "persistent": True, "creator": "Kenton"}, "10.0.0.1")
        self.assertEqual(c, 200, o)
        pub = self.mint("beta", "carlo-pc-3c4d", roomCode=CODE)
        adm = self.mint("beta", "boss-pc-9999", code="adm-1", roomCode=CODE)
        start = wall_in(DEN, time.time() + 120)
        d = {"title": "Beta review", "tz": DEN, "start": start, "room": "beta", "people": ["Ada Lovelace"]}
        self.assertEqual(self.api(dict(self.me(), op="save", meeting=d), pub)[1], 403)   # not beta's admin
        o, c = self.api(dict(self.me(), op="save", meeting=d), adm)
        self.assertEqual(c, 200, o)
        m = o["meeting"]
        self.assertFalse(m["own"])
        # Ada gets in with no code for the meeting's window; Carlo (not invited) still needs the code
        o, c = self.svc.token({"room": "beta", "host": "ada-pc-0a0a", "meet": dict(self.me("a"), id=m["id"])}, "10.0.0.8")
        self.assertEqual(c, 200, o)
        cl = kr.verify_token(o["tokens"]["member"], self.svc.key)
        self.assertEqual(cl["mt"], m["id"])
        self.assertIn("registry", o["tokens"])                          # a visible room: as anyone who joined it
        o, c = self.svc.token({"room": "beta", "host": "carlo-pc-3c4d", "meet": {"id": m["id"], "pname": "Carlo", "pcode": "zzzz-zzzz"}},
                              "10.0.0.9")
        self.assertEqual(c, 403)
        # beta's admin sees the meeting held in beta
        lst, c = self.api({"op": "list"}, adm)
        self.assertEqual([x["id"] for x in lst["meetings"]], [m["id"]])
        self.assertTrue(lst["meetings"][0]["manage"])

    def test_bundle_carries_meetings_and_reserved_names(self):
        m = self.schedule()
        b = self.st.export_bundle()
        self.assertIn(m["id"], b["meetings"]["meetings"])
        other = store()
        other.import_bundle(b)
        self.assertEqual(other.meetbook.get(m["id"])["title"], "Ops sync")
        self.assertTrue(kr.personal_reserved("mt-anything"))
        o, c = kr.register_room(self.st, {"slug": "mt-0123456789ab", "access": "pub-1"}, "10.0.0.1")
        self.assertEqual(c, 403)
        self.assertFalse(self.st.touch_room("mt-0123456789ab"))

    def test_tick_closes_an_ended_one_time_room(self):
        m = self.schedule()
        rec = self.st.meetbook.get(m["id"])
        later = M.occurrence(rec, rec["start"])["end"] + M.EMPTY_S + 5
        self.assertEqual(self.svc.meet_tick(later), 1)
        self.assertIsNone(self.st.room(m["room"]))


class Page(unittest.TestCase):
    """The page half: assets/kastr-meetings.js through the page's bridge (window.__kmeet)."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(HERE, "moq-watch-lite.html"), "rb") as f:
            cls.raw = f.read()
        cls.page = cls.raw.decode("utf-8")
        with open(os.path.join(HERE, "assets", "kastr-meetings.js"), encoding="utf-8") as f:
            cls.js = f.read()

    def test_line_endings(self):
        self.assertEqual(self.raw.count(b"\n"), self.raw.count(b"\r\n"))   # the page stays CRLF
        self.assertNotIn("\r", self.js)                                    # the asset stays LF

    def test_script_and_bridge(self):
        self.assertIn('<script type="module" src="/assets/kastr-meetings.js"></script>', self.page)
        self.assertIn("window.__kmeet", self.page)
        self.assertIn("isHiddenSlug", self.page)
        self.assertIn("MEET_RE", self.page)

    def test_switches_never_checkboxes(self):
        self.assertNotIn('type="checkbox"', self.js)
        self.assertNotIn("type='checkbox'", self.js)
        self.assertIn('w.className = "switch sm"', self.js)   # the house switch (span.switch + input + <i>), see test_release_0_21_92_toggles
        self.assertIn('w.append(cb, document.createElement("i"))', self.js)

    def test_confirms_ask_above_the_meetings_dialogs(self):   # lab: "Cancel meeting" asked behind its own details dialog
        self.assertNotIn("K.confirm({", self.js)
        self.assertIn('document.querySelectorAll(".kt-scrim.kt-top:not([hidden]), .kmlobby:not([hidden])")', self.js)
        self.assertIn(".kt-scrim.kt-top.km-under, .kmlobby.km-under { z-index:139; }", self.js)

    def test_never_a_token_in_storage(self):
        for m in re.finditer(r"localStorage\.setItem\(([^;]+)\)", self.js):
            self.assertNotRegex(m.group(1), r"token|pcode|invite")


if __name__ == "__main__":
    unittest.main()
