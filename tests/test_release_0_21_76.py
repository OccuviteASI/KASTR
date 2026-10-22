# -*- coding: utf-8 -*-
"""v0.21.76 (Kenton 2026-10-20: streaming quality ahead of 0.22, "keep what matters on a thin link"):
- per-tile subscription priority (lab: moq-relay 0.17 honours subscriber priority on the viewer leg and the spoke -> hub
  leg; with equal priorities the first subscription wins) -- a `priority` attribute on <moq-watch> (vendored-library patch);
- the grid composite joins the library's bandwidth allocator with a 600 kbps floor;
- streams shown in other rooms are listed only while they really stream (Kenton: "they never go away when nothing is
  streamed, they always show connecting") -- tested in test_release_0_21_75_boxrooms.OnAirOnly / OnAirRule.

Run: python -m unittest discover -s tests
"""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = os.path.join(HERE, "assets", "vendor", "esm", "@moq")


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


class Priority(unittest.TestCase):
    def test_vendored_player(self):
        el = read(V, "watch@0.6.2", "es2022", "element.mjs")
        self.assertIn('"catalog-format","captions","priority"]', el)
        self.assertIn("/* KASTR-PATCH: watch-priority-element */", el)
        pl = read(V, "watch@0.6.2", "es2022", "player-DqpNnBDT.mjs")
        self.assertIn("/* KASTR-PATCH: watch-priority */", pl)
        self.assertIn("i.update({priority:K(n),maxAge:n.get(e.maxAge)})", pl)     # a change is sent live
        self.assertIn("kastrPriority:e.in.priority,kastrBias:5,priority:b.PRIORITY.audio", pl)   # audio just above its video
        self.assertIn("subscribe({priority:255})", pl)                            # the catalog first
        self.assertIn("priority:b.PRIORITY.audio,maxAge:this.kastrAudioMaxAge", pl)   # audio-maxage-floor untouched

    def test_page_ranks_every_tile(self):
        p = read(HERE, "moq-watch-lite.html")
        self.assertIn('isSelected ? 190 : cls === "grid" ? 180 : isContentPath(name) ? 150 : 120;', p)   # 0.21.80: + 250 for the share I remote-control first
        self.assertIn('watch.setAttribute("priority", isContentPath(name) ? "150" : "120");', p)


class GridFloor(unittest.TestCase):
    def test_floor(self):
        enc = read(V, "publish@0.5.2", "es2022", "encoder-CjcsUSCu.mjs")
        self.assertIn("/* KASTR-PATCH: publish-bitrate-floor */n!=null&&(i=Math.max(Math.min(i,n),Math.min(i,this.kastrMinBitrate||0)))", enc)
        p = read(HERE, "moq-watch-lite.html")
        self.assertIn("const GRID_FLOOR_BPS = 600e3;", p)
        self.assertIn('new Video.Encoder("video", { enabled: true, broadcast, capture, bandwidth: connection.bandwidth });', p)
        self.assertIn("encoder.kastrMinBitrate = GRID_FLOOR_BPS;", p)


if __name__ == "__main__":
    unittest.main()
