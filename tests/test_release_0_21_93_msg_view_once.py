# -*- coding: utf-8 -*-
"""v0.21.93 VIEW ONCE in Messages (Kenton 2026-10-27/28): a message (usually a picture) that opens ONCE for each person it
was sent to and then shows "Opened"; no save, copy or download in the page (best effort -- the hint says "They can still take
a screenshot"); the hub deletes it once each reader opened it, or at the 7-day cap. Pages older than 0.21.93 never get the
content (a line telling them to update)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from msg_timer_rig import T0, Hub, HERE, km  # noqa: E402


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def mine(pull, cid):
    return [m for m in pull["msgs"] if m.get("cid") == cid]


class HubViewOnce(unittest.TestCase):
    def test_a_stub_until_opened_once(self):
        h = Hub()
        fid = h.upload("ada")
        o, c, cid = h.send("ada", to="bob", vo=1, files=[fid], now=T0)
        self.assertEqual(c, 200, o)
        seq = o["seq"]
        m = mine(h.pull("bob", now=T0 + 5), cid)[0]
        for k in ("iv", "ct", "files", "wraps"):
            self.assertNotIn(k, m, "the pull never carries a view-once body")
        self.assertEqual((m["vo"], m["nf"], m["opened"]), (1, 1, 0))
        self.assertIsNone(h.m.file_get(fid, "bob-0001", now=T0 + 5)[0], "no attachment before it is opened")
        o, c = h.api("ada", "vopen", seq=seq, now=T0 + 6)
        self.assertEqual(c, 403, "the sender does not open it")
        o, c = h.api("bob", "vopen", seq=seq, now=T0 + 10)
        self.assertEqual(c, 200, o)
        self.assertTrue(o["ct"] and o["iv"] and o["files"] == [fid] and list(o["wraps"]) == [h.kid["bob"]] and o["pub"])
        self.assertIsNotNone(h.m.file_get(fid, "bob-0001", now=T0 + 20)[0], "its picture, just after opening")
        self.assertIsNone(h.m.file_get(fid, "bob-0001", now=T0 + 10 + km.VO_OPEN_S + 1)[0], "and not later")
        # once: a second click (or bob's other device) gets "Opened"
        o, c = h.api("bob", "vopen", seq=seq, now=T0 + 30)
        self.assertEqual((c, o["opened"]), (410, int(T0 + 10)))
        self.assertEqual(mine(h.pull("bob", now=T0 + 31), cid)[0]["opened"], int(T0 + 10))
        sm = mine(h.pull("ada", now=T0 + 31), cid)[0]
        self.assertEqual((sm["opn"], sm["of"]), (1, 1), "the sender sees it was opened")

    def test_the_hub_deletes_it_after_the_open(self):
        h = Hub()
        fid = h.upload("ada")
        o, c, cid = h.send("ada", to="bob", vo=1, files=[fid], now=T0)
        seq = o["seq"]
        h.api("bob", "vopen", seq=seq, now=T0 + 100)
        self.assertEqual(h.m.tick(T0 + 100 + km.VO_OPEN_S - 1)["expired"], 0, "kept while its picture is on screen")
        self.assertIn(h.m.uid_of(h.m.msgs[seq]), h.pull("bob", now=T0 + 101)["tm"])
        self.assertEqual(h.m.tick(T0 + 100 + km.VO_OPEN_S + 1)["expired"], 1)
        self.assertNotIn(seq, h.m.msgs)
        self.assertNotIn(fid, h.m.files, "its attachment too")
        self.assertFalse(os.path.exists(h.m._file_path(fid)))
        for who in ("ada", "bob"):
            p = h.pull(who, now=T0 + 400)
            self.assertEqual(mine(p, cid), [])
            self.assertEqual(p["tm"], {}, "every device purges it (a page drops what is not in tm)")

    def test_a_group_waits_for_every_reader_or_the_cap(self):
        h = Hub()
        gid = h.group("ada", ["bob", "cy"])
        o, c, cid = h.send("ada", gid=gid, vo=1, now=T0)
        seq = o["seq"]
        h.api("bob", "vopen", seq=seq, now=T0 + 10)
        self.assertEqual(h.m.tick(T0 + 10 + km.VO_OPEN_S + 1)["expired"], 0, "cy has not opened it")
        self.assertEqual(mine(h.pull("bob", now=T0 + 400), cid), [], "gone for bob already")
        self.assertEqual(len(mine(h.pull("cy", now=T0 + 400), cid)), 1)
        self.assertEqual(h.m.tick(T0 + km.TIMER_CAP_S + 1)["expired"], 1, "the cap")
        self.assertEqual(h.api("cy", "vopen", seq=seq, now=T0 + km.TIMER_CAP_S + 2)[1], 404)

    def test_old_pages_never_get_the_content(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", vo=1, now=T0)
        p = h.pull("bob", now=T0 + 1, tv=0)
        line = [m for m in p["msgs"] if m.get("seq") == o["seq"]][0]
        self.assertEqual(line["kind"], "sys")
        self.assertNotIn("ct", line)
        self.assertIn("update KASTR", line["sys"]["names"][0])

    def test_opened_survives_a_switch_to_the_standby(self):
        h = Hub()
        o, c, cid = h.send("ada", to="bob", vo=1, now=T0)
        h.api("bob", "vopen", seq=o["seq"], now=T0 + 10)
        sb = km.Messenger(h.dir + "-standby", check_code=lambda n, c: True, has_room=lambda n: True)
        km.catch_up(sb, lambda s, v: h.m.export(s, v), None, files=False)
        o2, c2 = sb.api({"op": "vopen", "as": "bob", "seq": o["seq"]}, "bob-0001", now=T0 + 20)
        self.assertEqual(c2, 410, "it does not open a second time on the standby")
        self.assertEqual(sb.tick(T0 + 10 + km.VO_OPEN_S + 1)["expired"], 1)


class PageViewOnce(unittest.TestCase):
    JS = _read("assets/kastr-msg.js")

    def test_page(self):
        js = self.JS
        self.assertIn('op: "vopen"', js)
        self.assertIn("View once", js)
        self.assertIn("They can still take a screenshot", js)
        self.assertIn("Opened", js)
        self.assertIn("vo: ob.vo ? 1 : undefined", js)

    def test_never_kept_or_downloaded(self):
        js = self.JS
        i = js.index("function voView(")
        body = js[i:js.index("\n  }\n", i)]
        for bad in ('idbPut("blobs"', "download", "window.open"):
            self.assertNotIn(bad, body, "the view-once viewer must not " + bad)
        self.assertIn("contextmenu", body)
        self.assertIn("dragstart", body)


if __name__ == "__main__":
    unittest.main()
