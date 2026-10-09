# -*- coding: utf-8 -*-
"""v0.21.36 (Kenton: "auto selecting a relay based on hops ... auto connect to the nearest private IP ... only select the
Public IP when no private IP relay can be found"; decided: hops, then time; every launch). Also the gallery fits the stage
and centres only its last row."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_serve  # noqa: E402


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class Nearest(unittest.TestCase):
    def rank(self, table):
        # table: url -> (ip, online, hops, ms)
        probe = lambda u: {"online": table[u][1], "ms": table[u][3]}
        hops = lambda ip: next(v[2] for v in table.values() if v[0] == ip)
        resolve = lambda h: next(v[0] for k, v in table.items() if h in k)
        return [r["url"] for r in kastr_serve.rank_relays(list(table), probe=probe, hops=hops, resolve=resolve)]

    def test_private_by_hops_then_time(self):
        t = {"http://10.0.0.9:4443": ("10.0.0.9", True, 3, 20),
             "http://10.1.0.9:4443": ("10.1.0.9", True, 1, 90),
             "http://10.2.0.9:4443": ("10.2.0.9", True, 1, 40),
             "http://relay.example.com:4443": ("52.20.1.9", True, 0, 5)}
        self.assertEqual(self.rank(t)[:3], ["http://10.2.0.9:4443", "http://10.1.0.9:4443", "http://10.0.0.9:4443"])
        self.assertEqual(self.rank(t)[3], "http://relay.example.com:4443")   # public last while a private one answers

    def test_unknown_hops_after_known_and_offline_last(self):
        t = {"http://10.0.0.1:4443": ("10.0.0.1", True, None, 5),
             "http://10.0.0.2:4443": ("10.0.0.2", True, 4, 300),
             "http://10.0.0.3:4443": ("10.0.0.3", False, None, None)}
        self.assertEqual(self.rank(t), ["http://10.0.0.2:4443", "http://10.0.0.1:4443", "http://10.0.0.3:4443"])

    def test_public_when_no_private_answers(self):
        t = {"http://10.0.0.3:4443": ("10.0.0.3", False, None, None),
             "http://relay.example.com:4443": ("52.20.1.9", True, 6, 50)}
        self.assertEqual(self.rank(t)[0], "http://relay.example.com:4443")

    def test_private_ranges(self):
        for ip in ("10.1.2.3", "172.16.0.1", "192.168.1.1", "100.64.1.1", "127.0.0.1"):
            self.assertTrue(kastr_serve._is_private_ip(ip), ip)
        self.assertFalse(kastr_serve._is_private_ip("8.8.8.8"))

    def test_page_picks_at_launch_but_not_on_boxes(self):
        p = _read("moq-watch-lite.html")
        self.assertIn('if (IS_WEB || !gateIsLoopback() || !["full", "viewer"].includes(PAGE_MODE)) return null;', p)
        self.assertIn('sessionStorage.getItem("kastr.rejoin") || sessionStorage.getItem("kastr.autopicked")', p)
        self.assertIn("relayAutoPick().then((u) => { if (!u) return relayFailover(\"launch\"); })", p)


class GalleryFits(unittest.TestCase):
    def test_counts_what_is_shown(self):
        p = _read("moq-watch-lite.html")
        self.assertIn("if (cells.length && cells.length !== collagePlan.n) collageSize(cells.length);", p)
        self.assertIn(".sort((a, b) => a.o - b.o || a.i - b.i).map((x) => x.el);", p)
        self.assertIn("tw = Math.max(isPhone() ? 140 : 60,", p)


if __name__ == "__main__":
    unittest.main()
