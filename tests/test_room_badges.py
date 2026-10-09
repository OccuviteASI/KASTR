# -*- coding: utf-8 -*-
"""v0.21.36 (Kenton: "another symbol on the circle of a room to denote that there is an active video stream. Maybe a play
icon in the bottom right of the circle"): presence carries how many of a member's sources send video; a room with any
(or a box's RTSP feeds / grids) shows a play badge bottom-right; the lock moved to the top-left."""
import os
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class RoomBadges(unittest.TestCase):
    def test_video_count_published_and_read(self):
        p = _read("moq-watch-lite.html")
        self.assertIn('case "video": pubModel.video = Math.max(0, Number(value) || 0); break;', p)
        self.assertIn('if (!x.live || x.enabled === false || !x.name || x.videoPaused) continue;', p)   # a camera switched off is not video (0.21.40: onAirCount)
        self.assertIn("video: Number.isFinite(v.video) ? v.video : undefined, airv: v.airv === 1", p)
        self.assertIn('(p.who.video ?? (p.who.publishing?.length || 0)) > 0 || (p.who.rtspPaths?.length && p.who.rtsp !== "off")', p)

    def test_badge_places(self):
        p = _read("moq-watch-lite.html")
        self.assertIn(".rb .pl { position:absolute; bottom:-3px; right:-3px;", p)
        self.assertIn(".rb .lk { position:absolute; top:-3px; left:-3px;", p)
        self.assertIn('pl.className = "pl"; pl.innerHTML = icon("play");', p)


class GridOnAir(unittest.TestCase):
    """0.21.36 (Kenton: "Ability to stop all of the cameras in a grid with 1 toggle")."""

    def test_one_switch_per_grid(self):
        p = _read("moq-watch-lite.html")
        self.assertIn("function setGridOnAir(gid, on) {", p)
        self.assertIn('swi.addEventListener("change", () => setGridOnAir(gid, swi.checked));', p)
        self.assertIn('items.push({ value: "camsoff", label: "Turn off all cameras in this grid" });', p)
        self.assertIn("if (running) { on ? startSlot(a) : stopSlot(a.id); }", p)


if __name__ == "__main__":
    unittest.main()
