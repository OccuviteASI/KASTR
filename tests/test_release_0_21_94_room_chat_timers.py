# -*- coding: utf-8 -*-
"""v0.21.94 Room Chat timers (Kenton 2026-10-27/28): disappearing messages, send later and view once in Room Chat too.
The relay host's KASTR keeps them (kastr_chat.ChatStore, the routes in kastr_serve, the beat); a room has no read receipts,
so a timer starts when the message is sent. Deletion is real: the line is scrubbed in place (same length, so the standby's
byte-offset copy stays valid), attachments go, and a standby / hand-over copy never brings a dead line back. Pages older
than 0.21.94 get a line instead of a timed or view-once message and never see a scheduled one early."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_chat  # noqa: E402
from kastr_chat import ChatStore, OLD_STUB, scrub_file  # noqa: E402

T0 = 1_800_000_000.0
ROOM = "ops"


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="kastr-rct-")
        self.files = os.path.join(self.d, "shared")
        os.makedirs(self.files)
        self.s = ChatStore(self.d, files_dir=self.files)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def file(self, n=1, kind="image/png"):
        fid = ("%032x" % (0xabc000 + n))
        with open(os.path.join(self.files, fid), "wb") as f:
            f.write(b"PICTURE-BYTES-%d" % n)
        with open(os.path.join(self.files, fid + ".json"), "w", encoding="utf-8") as f:
            json.dump({"kind": "chat", "room": ROOM, "name": "p.png", "type": kind}, f)
        return {"id": fid, "name": "p.png", "size": 16, "type": kind}

    def meta(self, f):
        with open(os.path.join(self.files, f["id"] + ".json"), encoding="utf-8") as fh:
            return json.load(fh)

    def raw(self):
        with open(self.s._path(ROOM), "rb") as f:
            return f.read()


class Disappearing(Base):
    def test_gone_at_its_time_for_real(self):
        f = self.file()
        keep = self.s.append(ROOM, "bob", "Bob", "stays", now=T0)
        m = self.s.append(ROOM, "ada", "Ada", "SECRET-WORDS", [f], ttl=300, now=T0)
        self.assertEqual(m["exp"], int(T0) + 300)
        self.assertEqual(self.meta(f).get("t"), 1)   # served no-store
        self.assertEqual([x["id"] for x in self.s.read(ROOM, tv=True, now=T0 + 10)], [keep["id"], m["id"]])
        self.assertEqual([x["id"] for x in self.s.read(ROOM, tv=True, now=T0 + 301)], [keep["id"]])   # hidden before the beat
        size = len(self.raw())
        out = self.s.tick(now=T0 + 301)
        self.assertEqual(out["expired"], 1)
        raw = self.raw()
        self.assertNotIn(b"SECRET-WORDS", raw)
        self.assertFalse(os.path.exists(os.path.join(self.files, f["id"])))
        self.assertFalse(os.path.exists(os.path.join(self.files, f["id"] + ".json")))
        # the scrub keeps every earlier byte offset: only the tombstone line was added
        self.assertEqual(len(raw), size + len(raw.split(b"\n")[-2]) + 1)
        self.assertEqual([x["text"] for x in self.s.read(ROOM, tv=True, now=T0 + 400)], ["stays"])

    def test_room_default_applies_and_everyone_sees_a_line(self):
        sysrec = self.s.set_ttl(ROOM, 3600, "ada", "Ada", now=T0)
        self.assertEqual(sysrec["sys"], "ttl")
        self.assertIn("update KASTR", sysrec["text"])   # an older page reads this
        self.assertEqual(self.s.room_ttl(ROOM), 3600)
        self.s.set_ttl(ROOM, 0, "bob", "Bob", now=T0 + 5)
        self.assertEqual(self.s.room_ttl(ROOM), 0)
        with self.assertRaises(ValueError):
            self.s.set_ttl(ROOM, 30, "bob", "Bob")
        with self.assertRaises(ValueError):
            self.s.set_ttl(ROOM, 91 * 86400, "bob", "Bob")

    def test_old_pages_get_a_line_never_the_text(self):
        self.s.append(ROOM, "ada", "Ada", "SECRET", [self.file()], ttl=600, now=T0)
        self.s.append(ROOM, "ada", "Ada", "PICTURE", [self.file(2)], vo=1, dev="dev-ada-0001", now=T0)
        old = self.s.read(ROOM, tv=False, now=T0 + 1)
        self.assertEqual([x["text"] for x in old], [OLD_STUB["ttl"], OLD_STUB["vo"]])
        self.assertTrue(all(x["files"] == [] and "exp" not in x for x in old))
        new = self.s.read(ROOM, tv=True, now=T0 + 1)
        self.assertEqual(new[0]["text"], "SECRET")
        self.assertEqual((new[1]["text"], new[1]["files"], new[1]["nf"]), ("", [], 1))   # view once: a stub
        self.assertNotIn("pw", new[1])

    def test_timer_range(self):
        for bad in (59, 90 * 86400 + 1, "x"):
            with self.assertRaises(ValueError):
                self.s.append(ROOM, "ada", "Ada", "hi", ttl=bad)
        self.assertEqual(self.s.append(ROOM, "ada", "Ada", "hi", ttl=60, now=T0)["exp"], int(T0) + 60)

    def test_delete_scrubs_and_drops_files(self):
        f = self.file()
        m = self.s.append(ROOM, "ada", "Ada", "WORDS-TO-GO", [f], now=T0)
        self.assertTrue(self.s.delete(ROOM, m["id"], m["token"]))
        self.assertNotIn(b"WORDS-TO-GO", self.raw())
        self.assertFalse(os.path.exists(os.path.join(self.files, f["id"])))


class ViewOnce(Base):
    def test_once_per_device(self):
        f = self.file()
        m = self.s.append(ROOM, "ada", "Ada", "LOOK", [f], vo=1, dev="dev-ada-0001", now=T0)
        self.assertEqual(m["exp"], int(T0) + kastr_chat.TIMER_CAP_S)
        self.assertEqual(self.meta(f).get("vo"), 1)
        self.assertEqual(self.s.open_vo(ROOM, m["id"], "dev-ada-0001", now=T0 + 1)[0], 403)   # the poster's own
        self.assertEqual(self.s.open_vo(ROOM, m["id"], "x", now=T0 + 1)[0], 400)
        code, o = self.s.open_vo(ROOM, m["id"], "dev-bob-0001", now=T0 + 2)
        self.assertEqual(code, 200)
        self.assertEqual((o["text"], [x["id"] for x in o["files"]]), ("LOOK", [f["id"]]))
        self.assertTrue(self.s.vo_file_ok(ROOM, f["id"], o["ft"], now=T0 + 3))
        self.assertFalse(self.s.vo_file_ok(ROOM, f["id"], "nope", now=T0 + 3))
        self.assertFalse(self.s.vo_file_ok("other", f["id"], o["ft"], now=T0 + 3))
        self.assertFalse(self.s.vo_file_ok(ROOM, f["id"], o["ft"], now=T0 + 2 + kastr_chat.VO_OPEN_S + 1))   # the ticket's 5 minutes
        code, o2 = self.s.open_vo(ROOM, m["id"], "dev-bob-0001", now=T0 + 4)
        self.assertEqual(code, 410)
        self.assertEqual(o2["opened"], int(T0 + 2))
        self.assertEqual(self.s.open_vo(ROOM, m["id"], "dev-cy-00001", now=T0 + 5)[0], 200)   # another device: its own once
        self.assertEqual(self.s.read(ROOM, tv=True, now=T0 + 6)[0]["opn"], 2)
        self.assertNotIn(b"dev-bob-0001", self.raw())   # only a digest of the device is kept

    def test_gone_at_its_timer(self):
        f = self.file()
        m = self.s.append(ROOM, "ada", "Ada", "LOOK", [f], ttl=600, vo=1, dev="dev-ada-0001", now=T0)
        self.assertEqual(m["exp"], int(T0) + 600)
        self.s.tick(now=T0 + 601)
        self.assertEqual(self.s.open_vo(ROOM, m["id"], "dev-bob-0001", now=T0 + 602)[0], 404)
        self.assertNotIn(b"LOOK", self.raw())
        self.assertFalse(os.path.exists(os.path.join(self.files, f["id"])))


class SendLater(Base):
    def test_held_released_and_never_early(self):
        f = self.file()
        o = self.s.schedule(ROOM, int(T0) + 120, "ada", "Ada", "LATER-TEXT", [f], now=T0)
        self.assertTrue(o["sched"] and o["tk"] and o["dtk"])
        self.assertEqual(self.s.read(ROOM, tv=True, now=T0 + 1), [])
        self.assertEqual(self.s.read(ROOM, tv=False, now=T0 + 1), [])   # an older page neither
        code, g = self.s.sched_op(ROOM, o["sid"], o["tk"], "get", now=T0 + 2)
        self.assertEqual((code, g["state"], g["text"]), (200, "waiting", "LATER-TEXT"))
        self.assertEqual(self.s.sched_op(ROOM, o["sid"], "wrong", "get", now=T0 + 2)[0], 403)
        self.assertEqual(self.s.tick(now=T0 + 60)["released"], 0)
        self.assertEqual(self.s.tick(now=T0 + 121)["released"], 1)
        got = self.s.read(ROOM, tv=True, now=T0 + 122)
        self.assertEqual([x["text"] for x in got], ["LATER-TEXT"])
        code, g = self.s.sched_op(ROOM, o["sid"], o["tk"], "get", now=T0 + 123)
        self.assertEqual((code, g["state"], g["id"]), (200, "sent", got[0]["id"]))
        self.assertTrue(self.s.delete(ROOM, got[0]["id"], o["dtk"]))   # its delete token, handed out up front
        self.assertEqual(self.raw().count(b"LATER-TEXT"), 0)

    def test_time_now_cancel(self):
        o = self.s.schedule(ROOM, int(T0) + 600, "ada", "Ada", "A", now=T0)
        self.assertEqual(self.s.sched_op(ROOM, o["sid"], o["tk"], "time", int(T0) + 5, now=T0)[0], 400)   # too soon
        self.assertEqual(self.s.sched_op(ROOM, o["sid"], o["tk"], "time", int(T0) + 900, now=T0)[0], 200)
        self.assertEqual(self.s.tick(now=T0 + 601)["released"], 0)
        self.assertEqual(self.s.tick(now=T0 + 901)["released"], 1)
        b = self.s.schedule(ROOM, int(T0) + 600, "ada", "Ada", "B", now=T0)
        code, r = self.s.sched_op(ROOM, b["sid"], b["tk"], "now", now=T0 + 10)
        self.assertEqual(code, 200)
        self.assertIn("B", [x["text"] for x in self.s.read(ROOM, tv=True, now=T0 + 11) if x["id"] == r["id"]])
        self.assertEqual(self.s.sched_op(ROOM, b["sid"], b["tk"], "now", now=T0 + 12)[0], 409)
        f = self.file(3)
        c = self.s.schedule(ROOM, int(T0) + 600, "ada", "Ada", "CANCEL-ME", [f], now=T0)
        self.assertEqual(self.s.sched_op(ROOM, c["sid"], c["tk"], "cancel", now=T0 + 13)[0], 200)
        self.assertNotIn(b"CANCEL-ME", self.raw())
        self.assertFalse(os.path.exists(os.path.join(self.files, f["id"])))
        self.assertEqual(self.s.sched_op(ROOM, c["sid"], c["tk"], "get", now=T0 + 14)[1]["state"], "cancelled")
        self.assertEqual(self.s.tick(now=T0 + 700)["released"], 0)

    def test_range_and_timed(self):
        with self.assertRaises(ValueError):
            self.s.schedule(ROOM, int(T0) + 5, "ada", "Ada", "x", now=T0)
        with self.assertRaises(ValueError):
            self.s.schedule(ROOM, int(T0) + 91 * 86400, "ada", "Ada", "x", now=T0)
        o = self.s.schedule(ROOM, int(T0) + 120, "ada", "Ada", "T", ttl=300, now=T0)
        self.s.tick(now=T0 + 130)
        m = self.s.read(ROOM, tv=True, now=T0 + 131)[0]
        self.assertEqual(m["exp"], int(T0 + 130) + 300)   # the timer starts when it goes
        self.assertTrue(o["sid"])


class Standby(Base):
    """The standby keeps a byte-offset copy of each room's file; tombstones scrub it too, and merges never resurrect."""

    def test_replica_scrub_after_tombstone(self):
        m = self.s.append(ROOM, "ada", "Ada", "REPLICA-SECRET", ttl=60, now=T0)
        rep = os.path.join(self.d, "replica.jsonl")
        shutil.copyfile(self.s._path(ROOM), rep)
        off = os.path.getsize(rep)
        self.s.tick(now=T0 + 61)
        with open(self.s._path(ROOM), "rb") as f:
            f.seek(off)
            chunk = f.read()
        self.assertIn(b'"del"', chunk)
        with open(rep, "ab") as f:   # what the standby's copier appends from its offset
            f.write(chunk)
        self.assertGreaterEqual(scrub_file(rep), 1)
        with open(rep, "rb") as f:
            data = f.read()
        self.assertNotIn(b"REPLICA-SECRET", data)
        self.assertEqual(len(data), os.path.getsize(self.s._path(ROOM)))
        self.assertTrue(m["id"])

    def test_merge_never_resurrects(self):
        a = self.s.append(ROOM, "ada", "Ada", "OLD-COPY-TEXT", ttl=60, now=T0)
        with open(self.s._path(ROOM), encoding="utf-8") as f:
            theirs = f.read()                  # another hub's copy from before it went
        self.s.tick(now=T0 + 61)
        self.s.merge_in(ROOM, theirs)
        self.assertNotIn(b"OLD-COPY-TEXT", self.raw())
        self.assertEqual(self.s.read(ROOM, tv=True, now=T0 + 62), [])
        self.assertTrue(a["id"])

    def test_scheduled_survives_a_take_over(self):
        o = self.s.schedule(ROOM, int(T0) + 120, "ada", "Ada", "HELD", now=T0)
        with open(self.s._path(ROOM), encoding="utf-8") as f:
            text = f.read()
        d2 = tempfile.mkdtemp(prefix="kastr-rct-standby-")
        try:
            sb = ChatStore(d2, files_dir=os.path.join(d2, "shared"))
            sb.merge_in(ROOM, text)
            self.assertEqual(sb.read(ROOM, tv=True, now=T0 + 1), [])
            self.assertEqual(sb.tick(now=T0 + 121)["released"], 1)   # the standby sends it at its time
            self.assertEqual([x["text"] for x in sb.read(ROOM, tv=True, now=T0 + 122)], ["HELD"])
            self.assertEqual(sb.sched_op(ROOM, o["sid"], o["tk"], "get", now=T0 + 123)[1]["state"], "sent")
            # hand-back: the main hub's copy (still waiting) merges the standby's -- it is not sent twice
            with open(sb._path(ROOM), encoding="utf-8") as f:
                back = f.read()
            self.s.merge_in(ROOM, back)
            self.assertEqual(self.s.tick(now=T0 + 130)["released"], 0)
            self.assertEqual([x["text"] for x in self.s.read(ROOM, tv=True, now=T0 + 131)], ["HELD"])
            self.assertEqual(self.raw().count(b"HELD"), 1)   # the posted line only; the held copy was scrubbed
        finally:
            shutil.rmtree(d2, ignore_errors=True)


class Wiring(unittest.TestCase):
    def test_serve_routes(self):
        s = _read("kastr_serve.py")
        for needle in ('tv=(qs.get("tv") or [""])[0] == "1"', 'act == "ttl"', 'act == "open"', 'act == "sched"',
                       "store.vo_file_ok(room, fid, ft)", '"no-store" if meta.get("t") or meta.get("vo")', "CHAT_TIMER_BEAT_S = 5",
                       'name="chat-timers"'):
            self.assertIn(needle, s)

    def test_relay_copies_scrub(self):
        r = _read("kastr_relay.py")
        self.assertGreaterEqual(r.count("scrub_file("), 2)

    def test_page(self):
        p = _read("moq-watch-lite.html")
        for needle in ("&limit=200&tv=1", 'id="chatTimerBtn" class="mtimer"', 'id="chatTtlBtn" class="cttl"', 'act: "open"', 'act: "ttl"',
                       'act: "sched"', "They can still take a screenshot", "chatWinPush({ poke: d.id", "if (r.poke)", "Send later…",
                       "Scheduled for ", 'type: "datetime-local"', "if (timed || !window.__state?.enabled)", '"ft=" + encodeURIComponent'):
            self.assertIn(needle, p)
        self.assertNotIn("\n", p.replace("\r\n", ""))   # CRLF kept

    def test_line_endings(self):
        for name in ("kastr_chat.py", "kastr_relay.py"):
            with open(os.path.join(HERE, name), "rb") as f:
                self.assertNotIn(b"\r", f.read())


class SpokeProxy(unittest.TestCase):
    """A spoke forwards Room Chat to the hub: the hub's view-once "already opened" (410) reaches the page as 410
    (the page says "Already opened on this device"), while a hub's "room closed" 410 still turns into 502."""

    def _through(self, code, body):
        import http.server
        import threading
        import kastr_serve as ks

        class Hub(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                out = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        got = []
        req = json.dumps({"act": "open", "id": 1, "dev": "d"}).encode()

        class Fake:
            path = "/api/chat/ops"
            headers = {"Content-Length": str(len(req)), "Content-Type": "application/json"}

            def __init__(self):
                import io
                self.rfile = io.BytesIO(req)

            def _hub_token(self, hub):
                return "", {}

            def _chat_via(self):
                return "spoke-0000"

            def _room_persistent(self, room):
                return False

            def _chat_reply(self, c, obj, headers=None):
                got.append((c, obj))

        try:
            handler = ks.make_handler(HERE, quiet=True).func
            handler._chat_proxy(Fake(), "POST", "ops", {"host": "127.0.0.1", "web": srv.server_address[1]})
        finally:
            srv.shutdown()
            srv.server_close()
        return got

    def test_already_opened_passes(self):
        self.assertEqual(self._through(410, {"error": "already opened", "opened": 1800000000}),
                         [(410, {"error": "already opened", "opened": 1800000000})])

    def test_room_closed_stays_502(self):
        got = self._through(410, {"error": "room closed", "closed": 1800000000})
        self.assertEqual([c for c, _ in got], [502])


if __name__ == "__main__":
    unittest.main()
