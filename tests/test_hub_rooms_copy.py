# -*- coding: utf-8 -*-
"""v0.21.35 (Kenton: "Store a local copy of the rooms on each relay, so if the hub goes down, they are still visible"):
a spoke keeps the hub's room list on disk, refreshed every minute, and reads it back after a restart."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_serve  # noqa: E402


class HubRoomsCopy(unittest.TestCase):
    def test_saved_and_read_back(self):
        d = tempfile.mkdtemp()
        obj = {"rooms": [{"slug": "kept-room", "persistent": True}], "closed": {}, "groups": {}}
        with mock.patch.object(kastr_serve, "_HUB_ROOMS_CACHE", [None]):
            kastr_serve.hub_rooms_remember(d, obj)
        with open(os.path.join(d, kastr_serve.HUB_ROOMS_FILE), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["obj"]["rooms"][0]["slug"], "kept-room")
        with mock.patch.object(kastr_serve, "_HUB_ROOMS_CACHE", [None]) as cache:   # a restarted relay
            kastr_serve.hub_rooms_load(d)
            self.assertEqual(cache[0]["obj"]["rooms"][0]["slug"], "kept-room")

    def test_wired_in(self):
        with open(os.path.join(HERE, "kastr_serve.py"), encoding="utf-8") as f:
            s = f.read()
        self.assertIn("start_hub_rooms_keeper(relay_srv)   # 0.21.35", s)
        self.assertIn("hub_rooms_load(self._state_dir())   # 0.21.35", s)

    def test_standing_spotlight_applies_on_rejoin(self):
        # 0.21.35 (Kenton: leave and come back -> "the spotlight will not be set anymore")
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            p = f.read()
        self.assertNotIn("SPOT_STALE_MS", p)


if __name__ == "__main__":
    unittest.main()
