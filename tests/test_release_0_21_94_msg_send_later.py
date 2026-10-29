# -*- coding: utf-8 -*-
"""v0.21.94 SEND LATER in Messages (Kenton 2026-10-27/28): HELD ON THE HUB -- the message is sealed at once, the hub keeps the
sealed copy with a release time (its own clock) and delivers it then even with the sender's computer off; the sender sees
"Scheduled for <time>" and can change the time, cancel or send now; it survives a switch to the standby hub; no page (an
older one neither) sees it before its time."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from msg_timer_rig import T0, Hub, HERE, km  # noqa: E402

H = 3600


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def cids(pull):
    return [m.get("cid") for m in pull["msgs"] if m.get("kind") == "msg"]


class HubSendLater(unittest.TestCase):
    def test_held_then_released_on_the_hubs_clock(self):
        h = Hub()
        fid = h.upload("ada")
        o, c, cid = h.send("ada", to="bob", rel=int(T0 + H), files=[fid], now=T0)
        self.assertEqual(c, 200, o)
        self.assertTrue(o["sched"])
        self.assertEqual(o["rel"], int(T0 + H))
        seq0 = h.m.seq
        # nobody sees it before its time -- not bob (new or old page), not even ada's other devices as a message
        for tv in (1, 0):
            self.assertNotIn(cid, cids(h.pull("bob", now=T0 + 60, tv=tv)))
        self.assertIsNone(h.m.file_get(fid, "bob-0001")[0], "bob cannot fetch its attachment early")
        # ada's pages list it as scheduled (sealed, her wraps only)
        sch = h.pull("ada", now=T0 + 60)["sched"]
        self.assertEqual([(x["cid"], x["rel"], x["sched"]) for x in sch], [(cid, int(T0 + H), 1)])
        self.assertEqual(list(sch[0]["wraps"]), [h.kid["ada"]])
        self.assertEqual(h.m.tick(T0 + H - 1)["released"], 0)
        self.assertEqual(h.m.seq, seq0, "no number until it is released")
        self.assertEqual(h.m.tick(T0 + H)["released"], 1)
        p = h.pull("bob", now=T0 + H + 1)
        m = [x for x in p["msgs"] if x.get("cid") == cid][0]
        self.assertEqual((m["at"], m["rel"]), (int(T0 + H), int(T0 + H)))
        self.assertIsNotNone(h.m.file_get(fid, "bob-0001")[0])
        self.assertEqual(h.pull("ada", now=T0 + H + 1)["sched"], [])
        self.assertEqual(h.m.tick(T0 + H + 5)["released"], 0, "released once")

    def test_change_the_time_cancel_send_now(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", rel=int(T0 + H), now=T0)
        o, c = h.api("ada", "sched", cid=cid, do="time", rel=int(T0 + 2 * H), now=T0 + 10)
        self.assertEqual((c, o["rel"]), (200, int(T0 + 2 * H)))
        self.assertEqual(h.m.tick(T0 + H + 1)["released"], 0)
        self.assertEqual(h.api("ada", "sched", cid=cid, do="time", rel=int(T0 + 5), now=T0 + 10)[1], 400, "not in the past")
        self.assertEqual(h.api("bob", "sched", cid=cid, do="now", now=T0 + 10)[1], 404, "only the sender")
        o, c = h.api("ada", "sched", cid=cid, do="now", now=T0 + 20)
        self.assertEqual((c, o["st"]), (200, "sent"))
        self.assertIn(cid, cids(h.pull("bob", now=T0 + 21)))
        self.assertEqual(h.api("ada", "sched", cid=cid, do="cancel", now=T0 + 30)[1], 409, "already sent")
        # cancel: gone for good, its attachment too
        fid = h.upload("ada")
        o, c, cid2 = h.send("ada", to="bob", rel=int(T0 + H), files=[fid], now=T0 + 40)
        o, c = h.api("ada", "sched", cid=cid2, do="cancel", now=T0 + 50)
        self.assertEqual((c, o["st"]), (200, "gone"))
        self.assertNotIn(fid, h.m.files)
        self.assertEqual(h.m.tick(T0 + 2 * H)["released"], 0)
        self.assertNotIn(cid2, cids(h.pull("bob", now=T0 + 2 * H)))
        # a resend after a lost answer finds the entry instead of making a second one
        o, c, cid3 = h.send("ada", to="bob", rel=int(T0 + H), now=T0 + 60)
        o, c, _ = h.send("ada", to="bob", rel=int(T0 + H), cid=cid3, now=T0 + 61)
        self.assertTrue(o.get("dup") and o.get("sched"))

    def test_range_and_conversation_rules(self):
        h = Hub()
        self.assertEqual(h.send("ada", to="bob", rel=int(T0 + 5), now=T0)[1], 400)
        self.assertEqual(h.send("ada", to="bob", rel=int(T0 + 91 * 86400), now=T0)[1], 400)
        o, c = h.send("ada", to="bob", rel=int(T0 + 5), now=T0)[:2]
        self.assertEqual(o["now"], int(T0), "the hub says its clock (a page with a wrong clock corrects itself)")
        # a group: who reads it is counted at the release -- a member who left gets nothing
        gid = h.group("ada", ["bob", "cy"])
        o, c, cid = h.send("ada", gid=gid, rel=int(T0 + H), now=T0)
        self.assertEqual(c, 200, o)
        self.assertEqual(h.api("cy", "gleave", gid=gid, now=T0 + 10)[1], 200)
        h.m.tick(T0 + H)
        e = [x for x in h.m.msgs.values() if x.get("cid") == cid][0]
        self.assertEqual(sorted(e["who"]), ["ada", "bob"])
        self.assertNotIn(cid, cids(h.pull("cy", now=T0 + H + 1)))
        # a group deleted before the release: dropped, never delivered
        gid2 = h.group("ada", ["bob"])
        o, c, cid2 = h.send("ada", gid=gid2, rel=int(T0 + H), now=T0)
        h.api("ada", "gdelete", gid=gid2, now=T0 + 10)
        h.m.tick(T0 + H)
        self.assertEqual(h.m.sched["m:ada:" + cid2]["st"], "gone")

    def test_disappearing_and_scheduled_together(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", rel=int(T0 + H), ttl=300, now=T0)
        h.m.tick(T0 + H)
        e = [x for x in h.m.msgs.values() if x.get("cid") == cid][0]
        self.assertEqual(e["ttl"], 300)
        self.assertEqual(h.m._exp_for(e, "bob"), T0 + H + km.TIMER_CAP_S, "the cap counts from the release")
        h.read("bob", "p:ada", e["seq"], now=T0 + H + 30)
        self.assertEqual(h.m.tick(T0 + H + 331)["expired"], 1)

    def test_survives_a_switch_to_the_standby(self):
        h = Hub()
        fid = h.upload("ada")
        o, c, cid = h.send("ada", to="bob", rel=int(T0 + H), files=[fid], now=T0)
        sb = km.Messenger(h.dir + "-standby")
        since, mv, tot = km.catch_up(sb, lambda s, v: h.m.export(s, v), lambda f: h.m.file_raw(f), files=True)
        self.assertEqual(sb.sched["m:ada:" + cid]["st"], "wait")
        self.assertTrue(os.path.exists(sb._file_path(fid)), "its attachment is on the standby too")
        # the hub dies; the standby (promoted) releases it on time
        self.assertEqual(sb.tick(T0 + H)["released"], 1)
        e = [x for x in sb.msgs.values() if x.get("cid") == cid][0]
        self.assertEqual(e["files"], [fid])
        # the hub comes back and takes the standby's copy: one message, not two, and it does not release it again
        h.m.merge(sb.export(0, None))
        self.assertEqual(len([x for x in h.m.msgs.values() if x.get("cid") == cid]), 1)
        self.assertEqual(h.m.sched["m:ada:" + cid]["st"], "sent")
        self.assertEqual(h.m.tick(T0 + H + 10)["released"], 0)
        self.assertEqual(len([x for x in h.m.msgs.values() if x.get("cid") == cid]), 1)

    def test_a_change_on_the_hub_reaches_the_standby(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", rel=int(T0 + H), now=T0)
        sb = km.Messenger(h.dir + "-sb")
        since, mv, tot = km.catch_up(sb, lambda s, v: h.m.export(s, v), None, files=False)
        h.api("ada", "sched", cid=cid, do="cancel", now=T0 + 10)
        km.catch_up(sb, lambda s, v: h.m.export(s, v), None, since=since, meta_ver=mv, files=False)
        self.assertEqual(sb.sched["m:ada:" + cid]["st"], "gone")
        self.assertEqual(sb.tick(T0 + H)["released"], 0, "a cancelled message never comes back from the standby")

    def test_restart_keeps_the_schedule(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", rel=int(T0 + H), now=T0)
        h.m.flush()
        m2 = km.Messenger(h.dir)
        self.assertEqual(m2.tick(T0 + H)["released"], 1)


class PageSendLater(unittest.TestCase):
    JS = _read("assets/kastr-msg.js")

    def test_page(self):
        js = self.JS
        self.assertIn("Send later", js)
        self.assertIn("Scheduled for", js)
        self.assertIn('"contextmenu"', js)          # right-click on Send
        self.assertIn('type: "datetime-local"', js)
        for w in ("Change the time", "Send now", "Cancel"):
            self.assertIn(w, js)
        self.assertIn('op: "sched"', js)
        self.assertIn("rel:", js)

    def test_confirm_popup_takes_a_typed_input(self):
        html = _read("moq-watch-lite.html")
        self.assertIn('inp.type = (o.input && o.input.type) || "text"', html)


if __name__ == "__main__":
    unittest.main()
