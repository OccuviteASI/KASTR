# -*- coding: utf-8 -*-
"""0.21.54: the Relay page's Users table sorts by any column (Kenton: "Sort Users on relay server page alphabetically. Or
allow for sorting by any column") and a failing grid camera leaves the grid on its 3rd attempt (Kenton: "still sometimes
showing up beyond 5 attempts. Lets set it to 3 attempts before it drops from the grid"). Rigs: scratchpad
v02154/pw_usersort.py, v02154/pw_evict3.py."""
import io, os, re, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with io.open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class UsersSort(unittest.TestCase):
    def setUp(self):
        self.page = read("relay.html")

    def test_every_column_sorts_and_name_is_the_default(self):
        cols = re.findall(r'\{ key: "(\w+)", label: "([^"]+)"', self.page)
        self.assertEqual([c[1] for c in cols], ["Name", "Machine", "Kind", "Room", "Relay", "KASTR", "Last seen"])
        self.assertIn('return { key: "name", dir: "asc" };', self.page)
        self.assertIn('localStorage.setItem("kastr.relay.usersSort"', self.page)

    def test_natural_order_empty_last_and_reversible(self):
        self.assertIn('{ sensitivity: "base", numeric: true }', self.page)          # Box 2 before Box 10, any case
        self.assertIn("if (ea !== eb) return ea ? 1 : -1;", self.page)               # empty values last either way
        self.assertIn('dir: srt.key === k && srt.dir !== "desc" ? "desc" : "asc"', self.page)
        self.assertIn('aria-sort="', self.page)

    def test_restarting_users_sort_with_the_rest(self):
        self.assertIn('if (cell) items.push({ r: { name: p.label, node: k.slice(5), kind: "app", relay: p.relay },', self.page)


class GridEvict(unittest.TestCase):
    def test_three_attempts(self):
        page = read("moq-watch-lite.html")
        self.assertIn("const GRID_EVICT_AFTER = 3, GRID_READMIT_LIVED_S = 5;", page)
        self.assertIn("monAttempts >= GRID_EVICT_AFTER && !pubHealthy", page)
        self.assertNotIn("> GRID_EVICT_AFTER", page)

    def test_a_running_pair_must_be_streaming_to_vouch_for_its_camera(self):
        page = read("moq-watch-lite.html")
        self.assertIn("&& (!native || (pi.flowingAt && nowS - pi.flowingAt < 30)));", page)


if __name__ == "__main__":
    unittest.main()
