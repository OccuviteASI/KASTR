# -*- coding: utf-8 -*-
"""v0.21.94 DISAPPEARING MESSAGES in Messages (Kenton 2026-10-27/28): a conversation default (anyone in it changes it, everyone
sees "<who> set disappearing messages to ...") plus a per-message override; the timer starts WHEN EACH PERSON READS IT; a safety
cap deletes it within 7 days even if never read; in a group the hub deletes the ciphertext + attachments once every reader's
timer ran out (or at the cap); deletion is real on every copy (the hub's, the standby's -- tombstones -- and each device's,
which purges what the hub's `tm` no longer lists); pages older than 0.21.94 never get the content."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from msg_timer_rig import T0, Hub, HERE, km  # noqa: E402

H = 3600


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class HubTimers(unittest.TestCase):
    def test_expiry_counts_from_the_read_and_the_cap(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", ttl=H, now=T0)
        self.assertEqual(c, 200, o)
        seq = o["seq"]
        uid = "m:ada:" + cid
        # never read: bob still has it after 6 days, gone at the 7-day cap
        self.assertIn(uid, h.pull("bob", now=T0 + 6 * 86400)["tm"])
        self.assertEqual(h.m.tick(T0 + 6 * 86400)["expired"], 0)
        # read at +1 day: bob's copy goes an hour after HIS read, the sender's an hour after the first read
        h.read("bob", "p:ada", seq, now=T0 + 86400)
        tm = h.pull("bob", now=T0 + 86400 + 10)["tm"]
        self.assertEqual(tm[uid], [int(T0 + 86400 + H), 1])
        self.assertEqual(h.pull("ada", now=T0 + 86400 + 10)["tm"][uid], [int(T0 + 86400 + H), 1])
        self.assertEqual(h.m.tick(T0 + 86400 + H - 1)["expired"], 0)
        p = h.pull("bob", now=T0 + 86400 + H - 1)
        self.assertTrue(any(m.get("cid") == cid for m in p["msgs"]))
        self.assertEqual(h.m.tick(T0 + 86400 + H + 1)["expired"], 1)
        p = h.pull("bob", now=T0 + 86400 + H + 2)
        self.assertNotIn(uid, p["tm"])
        self.assertFalse(any(m.get("cid") == cid for m in p["msgs"]))
        self.assertIn(uid, h.m.gone)
        self.assertFalse(os.path.exists(h.m._msg_path(seq)))

    def test_unread_cap(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", ttl=30 * 86400, now=T0)
        self.assertEqual(h.m.tick(T0 + km.TIMER_CAP_S - 5)["expired"], 0)
        self.assertEqual(h.m.tick(T0 + km.TIMER_CAP_S + 1)["expired"], 1)
        self.assertEqual(km.TIMER_CAP_S, 7 * 86400)

    def test_group_deleted_when_every_reader_is_done_with_attachments(self):
        h = Hub()
        gid = h.group("ada", ["bob", "cy"])
        fid = h.upload("ada")
        o, c, cid = h.send("ada", gid=gid, ttl=300, files=[fid], now=T0)
        self.assertEqual(c, 200, o)
        seq = o["seq"]
        h.read("bob", "g:" + gid, seq, now=T0 + 10)
        self.assertEqual(h.m.tick(T0 + 400)["expired"], 0, "cy has not read it: the hub keeps it")
        # bob's own copy is gone for him (pull skips it) while the hub still keeps it for cy
        self.assertFalse(any(m.get("cid") == cid for m in h.pull("bob", now=T0 + 400)["msgs"]))
        self.assertTrue(any(m.get("cid") == cid for m in h.pull("cy", now=T0 + 400)["msgs"]))
        data, err = h.m.file_get(fid, "cy-0001")
        self.assertIsNone(err)
        h.read("cy", "g:" + gid, seq, now=T0 + 500)
        self.assertEqual(h.m.tick(T0 + 500 + 299)["expired"], 0)
        self.assertEqual(h.m.tick(T0 + 500 + 301)["expired"], 1)
        self.assertNotIn(fid, h.m.files)
        self.assertFalse(os.path.exists(h.m._file_path(fid)))
        self.assertIn(fid, h.m.gonef)

    def test_reads_from_an_old_page_do_not_start_a_timer(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", ttl=H, now=T0)
        h.read("bob", "p:ada", o["seq"], now=T0 + 5, tv=0)
        self.assertEqual(h.pull("bob", now=T0 + 6)["tm"]["m:ada:" + cid][1], 0)
        h.read("bob", "p:ada", o["seq"], now=T0 + 50)   # the same seq again from a 0.21.94 page: the timer starts now
        self.assertEqual(h.pull("bob", now=T0 + 51)["tm"]["m:ada:" + cid], [int(T0 + 50 + H), 1])

    def test_old_pages_never_get_the_content(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", ttl=H, now=T0)
        old = h.pull("bob", now=T0 + 1, tv=0)
        m = [x for x in old["msgs"] if x["seq"] == o["seq"]][0]
        self.assertEqual(m["kind"], "sys")
        self.assertNotIn("ct", m)
        self.assertNotIn("wraps", m)
        self.assertIn("update KASTR", m["sys"]["names"][0])
        self.assertNotIn("tm", old)
        new = h.pull("bob", now=T0 + 1)
        m = [x for x in new["msgs"] if x["seq"] == o["seq"]][0]
        self.assertEqual((m["kind"], m["ttl"]), ("msg", H))
        self.assertIn("ct", m)
        self.assertEqual(new["tv"], km.TIMERS_VER)

    def test_conversation_default_and_old_senders(self):
        h = Hub()
        o, c = h.api("bob", "ctimer", conv="p:ada", s=8 * H, now=T0)
        self.assertEqual(c, 200, o)
        p = h.pull("ada", now=T0 + 1)
        self.assertEqual(p["convt"]["p:bob"]["s"], 8 * H)
        self.assertEqual(h.pull("bob", now=T0 + 1)["convt"]["p:ada"]["s"], 8 * H)
        line = [m for m in p["msgs"] if m["kind"] == "sys"][-1]
        self.assertEqual(line["sys"], {"ev": "timer", "s": 8 * H})
        self.assertEqual(line["fromName"], "bob")
        # an old page sending into it: the hub applies the default (no tv) ...
        o, c, cid = h.send("ada", to="bob", tv=0, now=T0 + 2)
        self.assertEqual(h.m.msgs[o["seq"]].get("ttl"), 8 * H)
        # ... a 0.21.94 page's explicit choice (here: Off for this one message) wins
        o, c, cid = h.send("ada", to="bob", ttl=0, now=T0 + 3)
        self.assertNotIn("ttl", h.m.msgs[o["seq"]])
        # out of range
        self.assertEqual(h.api("bob", "ctimer", conv="p:ada", s=30, now=T0)[1], 400)
        self.assertEqual(h.api("bob", "ctimer", conv="p:ada", s=91 * 86400, now=T0)[1], 400)
        self.assertEqual(h.send("ada", to="bob", ttl=10, now=T0)[1], 400)
        # a group: anyone in it may change it
        gid = h.group("ada", ["bob", "cy"])
        self.assertEqual(h.api("cy", "ctimer", conv="g:" + gid, s=300, now=T0 + 5)[1], 200)
        self.assertEqual(h.pull("ada", now=T0 + 6)["convt"]["g:" + gid]["s"], 300)

    def test_standby_copy_follows_the_tombstone_and_never_resurrects(self):
        h = Hub()
        fid = h.upload("ada")
        o, c, cid = h.send("ada", to="bob", ttl=300, files=[fid], now=T0)
        sb = km.Messenger(h.dir + "-standby")
        since, mv, tot = km.catch_up(sb, lambda s, v: h.m.export(s, v), lambda f: h.m.file_raw(f), files=True)
        self.assertTrue(any(e.get("cid") == cid for e in sb.msgs.values()))
        self.assertTrue(os.path.exists(sb._file_path(fid)))
        h.read("bob", "p:ada", o["seq"], now=T0 + 10)
        h.m.tick(T0 + 400)
        since, mv, tot = km.catch_up(sb, lambda s, v: h.m.export(s, v), lambda f: h.m.file_raw(f), since=since, meta_ver=mv)
        self.assertFalse(any(e.get("cid") == cid for e in sb.msgs.values()), "the standby's copy is deleted too")
        self.assertNotIn(fid, sb.files)
        self.assertFalse(os.path.exists(sb._file_path(fid)))
        # a hand-back the other way (an old copy that still has it) never brings it back
        h2 = km.Messenger(h.dir + "-old")
        h2.merge(dict(h.m.export(0, None), msgs=[]))
        stale = {"v": 1, "fleet": h.m.fleet, "seq": 99, "metaVer": "x", "msgs": [dict(e) for e in sb.msgs.values()], "more": False, "top": 99}
        stale["msgs"].append({"seq": o["seq"], "uid": "m:ada:" + cid, "at": int(T0), "cid": cid, "kind": "msg", "from": "ada", "who": ["ada", "bob"],
                              "ttl": 300, "iv": "A" * 16, "ct": "A" * 40})
        h.m.merge(stale)
        self.assertFalse(any(e.get("cid") == cid for e in h.m.msgs.values()))

    def test_read_state_travels_to_the_standby(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", ttl=H, now=T0)
        h.read("bob", "p:ada", o["seq"], now=T0 + 100)
        sb = km.Messenger(h.dir + "-sb")
        km.catch_up(sb, lambda s, v: h.m.export(s, v), None, files=False)
        e = [x for x in sb.msgs.values() if x.get("cid") == cid][0]
        self.assertEqual(sb._exp_for(e, "bob"), T0 + 100 + H)
        self.assertEqual(sb.tick(T0 + 100 + H + 1)["expired"], 1)   # a promoted standby deletes it on time

    def test_read_times_live_with_the_receipts(self):
        """The from-read timers build on the receipt times (rcpt): a timed-read cursor per conversation ("t|<conv>") beside
        the plain read cursor -- no second read-time store; it moves only for a 0.21.94 page reading a timed message."""
        h = Hub()
        o1, c, cid1 = h.send("ada", to="bob", ttl=0, now=T0)
        h.read("bob", "p:ada", o1["seq"], now=T0 + 5)
        self.assertNotIn("t|p:ada", h.m.rcpt.get("bob") or {}, "no timed message read: the timed cursor stays put")
        self.assertIn("p:ada", h.m.rcpt["bob"])   # the plain receipt (the coordinator's ticks) is there
        o2, c, cid2 = h.send("ada", to="bob", ttl=H, now=T0 + 10)
        h.read("bob", "p:ada", o2["seq"], now=T0 + 20)
        self.assertEqual(h.m.rcpt["bob"]["t|p:ada"], [[o2["seq"], int(T0 + 20)]])
        self.assertFalse(any("rd" in st for st in h.m.tst.values()))
        # a later read of the same conversation does not move the time of the one already read
        h.read("bob", "p:ada", o2["seq"], now=T0 + 500)
        self.assertEqual(h.m._exp_for(h.m.msgs[o2["seq"]], "bob"), T0 + 20 + H)
        self.assertEqual(h.m._exp_for(h.m.msgs[o2["seq"]], "ada"), T0 + 20 + H)   # the sender's copy: the first read

    def test_restart_keeps_timer_state(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", ttl=H, now=T0)
        h.read("bob", "p:ada", o["seq"], now=T0 + 100)
        h.m.flush()
        m2 = km.Messenger(h.dir)
        self.assertIn(o["seq"], m2.tix)
        self.assertEqual(m2.tick(T0 + 100 + H + 1)["expired"], 1)


class PageTimers(unittest.TestCase):
    JS = _read("assets/kastr-msg.js")

    def test_page_sends_tv_and_purges(self):
        js = self.JS
        self.assertIn('op: "pull", as: [S.name], since: S.cur, ack: S.cur, tv: 1', js)
        self.assertRegex(js, r'op: "read", as: S\.name, conv, seq: last, tv: 1')
        self.assertIn("function purgeTimed(", js)
        self.assertIn('idbDel("blobs"', js)   # cached attachment pictures go with the message
        self.assertIn("x: { ttl", js)          # the sealed body carries the timer too

    def test_composer_timer_button_badge_and_menu(self):
        js = self.JS
        self.assertIn('class="mtimer"', js)
        self.assertIn("mclk", js)
        self.assertIn("Disappearing messages", js)
        for lab in ("5 minutes", "1 hour", "8 hours", "24 hours", "7 days", "30 days", "Custom"):
            self.assertIn(lab, js)
        self.assertIn('ev === "timer"', js)   # (every on/off is a switch: tests/test_release_0_21_92_toggles.py)


if __name__ == "__main__":
    unittest.main()
