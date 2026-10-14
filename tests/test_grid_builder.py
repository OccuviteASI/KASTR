# -*- coding: utf-8 -*-
"""v0.21.65 THE GRID BUILDER (Kenton: "I would like more preset options in a dropdown for camera views in the grid, instead of
just the 1/2 camera big options. ... a method for building the grid with a drag and drop method. This also allows for multiple
cameras being set to the same spot on a grid and cycle between the cameras on motion or a time.") and SPLIT-OUT cameras ("split
streams out of a grid on the viewing side that I can also pin and spotlight to the room that don't affect the original
room/grid that they are in").

- presets "1 Camera" .. "26 Cameras": re-computed here from the page's own table, every spot inside the 24 x 24 units, no
  overlaps, the big spots first;
- the cycle (time / motion hold / no motion keeps the camera on) and the motion detector's numbers, as JS-free Python mirrors
  of the page's pure functions (the page text is asserted so the mirror cannot drift silently);
- the room board: op grid with `slots` (+ `sens`), ops split / unsplit -- validation, caps, auth, the hub/spoke path;
- the page wiring (editor, box, viewers, menus).
Loopback sockets only (ephemeral ports), no outside network.

Run: python -m unittest discover -s tests
"""
import os, re, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402

HOST = "box-1a2b"
GRID = "beta/box-1a2b/kenton/grid-1.hang"
CAM1 = "beta/box-1a2b/kenton/yard.hang"
CAM2 = "beta/box-1a2b/kenton/gate.hang"
CAM3 = "beta/box-1a2b/kenton/dock.hang"
U = 24


def _page():
    with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


PAGE = _page()


def sec(start, end):
    i = PAGE.index(start)
    return PAGE[i:PAGE.index(end, i + len(start))]


# ---------------------------------------------------------------------------------------------------------------- presets
def preset_spec():
    body = re.search(r"const PRESET_SPEC = \{(.*?)\};", PAGE, re.S).group(1)
    return {int(n): tuple(int(v) for v in vs) for n, *vs in re.findall(r"(\d+): \[(\d+), (\d+), (\d+), (\d+)\]", body)}


def preset(n, spec):
    """Python mirror of gridBuilder.preset(n)."""
    if n == 5:
        return [[0, 0, 18, 18], [18, 0, 6, 6], [18, 6, 6, 6], [18, 12, 6, 6], [18, 18, 6, 6]]
    c, r, nb, b = spec[n]
    k = max(c, r)
    s = U // k if U % k == 0 else 0

    def edges(cnt, off):
        return [off + i * s for i in range(cnt + 1)] if s else [int(i * U / cnt + 0.5) for i in range(cnt + 1)]
    xs = edges(c, (U - c * s) // 2 if s else 0)
    ys = edges(r, (U - r * s) // 2 if s else 0)

    def cell(i, j, w, h):
        return [xs[i], ys[j], xs[i + w] - xs[i], ys[j + h] - ys[j]]
    out, used = [], set()
    for q in range(nb):
        out.append(cell(q * b, 0, b, b))
        used |= {(i, j) for i in range(q * b, q * b + b) for j in range(b)}
    for j in range(r):
        for i in range(c):
            if (i, j) not in used:
                out.append(cell(i, j, 1, 1))
    return out[:n]


def overlap(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


class Presets(unittest.TestCase):
    def setUp(self):
        self.spec = preset_spec()

    def test_table_covers_1_to_26(self):
        self.assertEqual(sorted(self.spec), [n for n in range(1, 27) if n != 5])   # 5 is drawn by hand: one big + a column of four
        self.assertIn("if (n === 5) return [[0, 0, 18, 18], [18, 0, 6, 6], [18, 6, 6, 6], [18, 12, 6, 6], [18, 18, 6, 6]];", PAGE)
        self.assertIn('const PRESETS = [...Array(PRESET_MAX)].map((_, i) => ({ id: "n" + (i + 1), n: i + 1, label: (i + 1) + (i ? " Cameras" : " Camera") }));', PAGE)
        self.assertIn("const PRESET_MAX = 26;", PAGE)

    def test_every_preset_fits_and_never_overlaps(self):
        for n in range(1, 27):
            u = preset(n, self.spec)
            self.assertEqual(len(u), n, n)
            for x in u:
                self.assertTrue(all(isinstance(v, int) for v in x), (n, x))
                self.assertTrue(x[2] >= 2 and x[3] >= 2 and x[0] >= 0 and x[1] >= 0 and x[0] + x[2] <= U and x[1] + x[3] <= U, (n, x))
                self.assertTrue(kr.board_unit_ok(x), (n, x))   # the board takes every preset spot as it is
            for i in range(n):
                for j in range(i + 1, n):
                    self.assertFalse(overlap(u[i], u[j]), (n, u[i], u[j]))

    def test_big_spots_first(self):
        for n in range(1, 27):
            areas = [x[2] * x[3] for x in preset(n, self.spec)]
            small = min(areas)
            big = [i for i, a in enumerate(areas) if a > 2 * small]     # 24 / 5 lattices mix 4- and 5-unit small cells
            rest = [i for i, a in enumerate(areas) if a <= 2 * small]
            if big:
                self.assertLess(max(big), min(rest), (n, areas))
            self.assertEqual(areas[0], max(areas), n)

    def test_equal_grids_and_mixes(self):
        for n in (1, 4, 9, 16):
            self.assertEqual(len({x[2] * x[3] for x in preset(n, self.spec)}), 1, n)
        self.assertEqual(preset(2, self.spec), [[0, 6, 12, 12], [12, 6, 12, 12]])               # halves
        self.assertEqual(preset(3, self.spec), [[0, 4, 16, 16], [16, 4, 8, 8], [16, 12, 8, 8]])  # one big left + two right
        self.assertEqual(preset(6, self.spec)[0], [0, 0, 16, 16])
        self.assertEqual(preset(8, self.spec)[0], [0, 0, 18, 18])
        self.assertEqual(preset(10, self.spec)[:2], [[0, 0, 12, 12], [12, 0, 12, 12]])           # two big
        self.assertEqual(sorted({x[2] for x in preset(25, self.spec)}), [4, 5])                  # 24 / 5: 4- and 5-unit cells

    def test_old_templates_stay(self):
        self.assertIn('const GRID_TEMPLATES = [["auto", "Equal"], ["big1", "One big"], ["big2", "Two big"], ["row", "Side by side"], ["column", "Stacked"]];', PAGE)
        ed = sec("  const gridEditor = (() => {", "  window.__gridEditor = gridEditor;")
        self.assertIn('pop.appendChild(mkEl("div", "gepcap", "Fit every camera"));', ed)
        self.assertIn("b.append(presetIcon(gb.preset(p.n)), mkEl(\"span\", \"geplbl\", p.label), tick);", ed)


# ---------------------------------------------------------------------------------------------------------------- the cycle
def cycle(c):
    c = c or {}

    def secs(v, d):
        try:
            x = round(float(v))
        except (TypeError, ValueError):
            return d
        return x if 2 <= x <= 3600 else d
    return {"mode": "time" if c.get("mode") == "time" else "motion", "every": secs(c.get("every"), 10), "hold": secs(c.get("hold"), 15)}


def cycle_tick(st, cams, c, now, mot):
    """Python mirror of gridBuilder.cycleTick (now in ms)."""
    c = cycle(c)
    if not cams:
        st["cur"], st["at"] = None, now
        return None
    if st.get("cur") is None or st["cur"] not in cams:
        st["cur"], st["at"] = cams[0], now
    if len(cams) == 1:
        return st["cur"]
    if c["mode"] == "time":
        if now - st["at"] >= c["every"] * 1000:
            st["cur"], st["at"] = cams[(cams.index(st["cur"]) + 1) % len(cams)], now
        return st["cur"]

    def m(k):
        return (mot(k) if mot else None) or None

    def recent(k):
        x = m(k)
        return bool(x) and (x.get("on") or (x.get("last", 0) > 0 and now - x["last"] < c["hold"] * 1000))
    if recent(st["cur"]):
        return st["cur"]
    best, b_on, b_t = None, False, float("-inf")
    for k in cams:
        if not recent(k):
            continue
        x = m(k)
        on = bool(x.get("on"))
        t = x.get("since", 0) if on else x.get("last", 0)
        if (on and not b_on) or (on == b_on and t > b_t):
            best, b_on, b_t = k, on, t
    if best is not None and best != st["cur"]:
        st["cur"], st["at"] = best, now
    return st["cur"]


class Cycle(unittest.TestCase):
    def test_page_function_is_the_mirror(self):
        f = sec("    function cycleTick(st, cams, c, now, mot) {", "\n    }\n")
        for need in ('if (!cams.length) { st.cur = null; st.at = now; return null; }',
                     'if (st.cur == null || !cams.includes(st.cur)) { st.cur = cams[0]; st.at = now; }',
                     'if (c.mode === "time") {',
                     'if (now - st.at >= c.every * 1000) { st.cur = cams[(cams.indexOf(st.cur) + 1) % cams.length]; st.at = now; }',
                     'const recent = (k) => { const x = m(k); return !!x && (x.on || (x.last > 0 && now - x.last < c.hold * 1000)); };',
                     'if (recent(st.cur)) return st.cur;   // held',
                     'const x = m(k), on = !!x.on, t = on ? (x.since || 0) : (x.last || 0);',
                     'if ((on && !bOn) || (on === bOn && t > bT)) { best = k; bOn = on; bT = t; }',
                     'if (best != null && best !== st.cur) { st.cur = best; st.at = now; }'):
            self.assertIn(need, f)
        self.assertIn("const CYCLE = { mode: \"motion\", every: 10, hold: 15 };", PAGE)   # Kenton's defaults: 10 s / 15 s

    def test_time_every_10_s(self):
        st, cams = {}, ["a", "b", "c"]
        seen = [cycle_tick(st, cams, {"mode": "time"}, t * 1000, None) for t in range(0, 41)]
        self.assertEqual(seen[0], "a")
        self.assertEqual((seen[9], seen[10], seen[19], seen[20], seen[30], seen[40]), ("a", "b", "b", "c", "a", "b"))

    def test_motion_wins_and_is_held(self):
        st, cams, mot = {}, ["a", "b"], {}
        tick = lambda t: cycle_tick(st, cams, {"mode": "motion", "hold": 15}, t, lambda k: mot.get(k))
        self.assertEqual(tick(0), "a")                                    # no motion anywhere: the first, kept
        self.assertEqual(tick(60000), "a")
        mot["b"] = {"on": True, "since": 61000, "last": 61000}
        self.assertEqual(tick(61000), "b")                                # b moves -> b
        mot["a"] = {"on": True, "since": 62000, "last": 62000}
        self.assertEqual(tick(62000), "b")                                # a moves too: b is held while it moves
        mot["b"] = {"on": False, "since": 61000, "last": 63000}
        self.assertEqual(tick(70000), "b")                                # b stopped 7 s ago: still held (hold 15 s)
        self.assertEqual(tick(78100), "a")                                # b's hold is over, a still moves -> a
        mot["a"] = {"on": False, "since": 62000, "last": 79000}
        self.assertEqual(tick(200000), "a")                               # nothing moves any more: a stays on

    def test_latest_motion_wins_when_free(self):
        st, mot = {"cur": "c", "at": 0}, {"a": {"on": False, "last": 5000}, "b": {"on": False, "last": 8000}}
        self.assertEqual(cycle_tick(st, ["a", "b", "c"], {"mode": "motion", "hold": 15}, 10000, lambda k: mot.get(k)), "b")
        mot["a"] = {"on": True, "since": 9000, "last": 10500}
        st = {"cur": "c", "at": 0}
        self.assertEqual(cycle_tick(st, ["a", "b", "c"], {"mode": "motion", "hold": 15}, 10500, lambda k: mot.get(k)), "a")   # moving now beats moved lately

    def test_departures_and_singles(self):
        st = {"cur": "x", "at": 0}
        self.assertEqual(cycle_tick(st, ["a", "b"], {"mode": "time"}, 1000, None), "a")   # the camera on left: the first
        self.assertEqual(cycle_tick(st, ["b"], {"mode": "time"}, 999999, None), "b")
        self.assertIsNone(cycle_tick(st, [], {"mode": "time"}, 0, None))
        self.assertEqual(cycle({"mode": "time", "every": 1, "hold": 99999}), {"mode": "time", "every": 10, "hold": 15})   # out of range: defaults


# ---------------------------------------------------------------------------------------------------------------- motion
FLOOR, THRESH, HITS = 10, {"low": 4, "medium": 2, "high": 1}, 2
W, H = 64, 36


def score(a, b):
    return sum(abs(x - y) for x, y in zip(a, b) if abs(x - y) > FLOOR) / len(a)


def frame(bg=64, sq=None, noise=0, seed=0):
    import random
    rnd = random.Random(seed)
    px = [bg + (rnd.randint(-noise, noise) if noise else 0) for _ in range(W * H)]
    if sq:
        x0, y0, s, v = sq
        for y in range(y0, min(H, y0 + s)):
            for x in range(x0, min(W, x0 + s)):
                px[y * W + x] = v
    return px


class Motion(unittest.TestCase):
    def test_page_numbers(self):
        self.assertIn("const MOTION = { W: 64, H: 36, EVERY_MS: 250, FLOOR: 10, THRESH: { low: 4, medium: 2, high: 1 }, HITS: 2, SETTLE_MS: 1000 };", PAGE)
        f = sec("    function motionScore(a, b) {", "\n    }\n")
        self.assertIn("if (d > MOTION.FLOOR) sum += d;", f)
        self.assertIn("return sum / a.length;", f)
        m = sec("      function sample(key, draw, sens, now, token) {", "\n      }\n")
        for need in ("if (s.token !== token) { s.token = token; s.prev = null; s.hits = 0; s.on = false; s.started = now; }",
                     "if (now - s.at < MOTION.EVERY_MS) return s;",
                     "g[j] = (d[i] * 77 + d[i + 1] * 150 + d[i + 2] * 29) >> 8;",
                     "if (!prev || now - s.started < MOTION.SETTLE_MS) { s.hits = 0; s.on = false; return s; }",
                     "s.hits = s.score > (MOTION.THRESH[sens] || MOTION.THRESH.medium) ? s.hits + 1 : 0;",
                     "s.on = s.hits >= MOTION.HITS;"):
            self.assertIn(need, m)
        self.assertIn('cv = document.createElement("canvas"); cv.width = MOTION.W; cv.height = MOTION.H;', m)   # one shared canvas

    def test_noise_is_not_motion(self):
        a, b = frame(noise=5, seed=1), frame(noise=5, seed=2)   # compression shimmer: +-5 grey levels everywhere (at most 10 apart)
        self.assertEqual(score(a, b), 0)

    def test_a_moving_square(self):
        a = frame(sq=(5, 10, 10, 255))
        b = frame(sq=(15, 10, 10, 255))      # a 10 x 10 white square moved its own width
        s = score(a, b)
        self.assertGreater(s, THRESH["low"])
        small = score(frame(sq=(5, 10, 5, 160)), frame(sq=(8, 10, 5, 160)))   # a small, dim change (5 x 5, 3 px)
        self.assertGreater(small, THRESH["high"])
        self.assertLess(small, THRESH["medium"])   # High sees it, Medium does not

    def test_two_samples_running(self):
        hits, on = 0, []
        for sc in (5, 0, 5, 5, 5, 0):
            hits = hits + 1 if sc > THRESH["medium"] else 0
            on.append(hits >= HITS)
        self.assertEqual(on, [False, False, False, True, True, False])


# ---------------------------------------------------------------------------------------------------------------- the board
def store(d=None):
    st = kr.AuthStore(d or tempfile.mkdtemp())
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def mint(svc, room, host=HOST, code="pub-1"):
    o, c = svc.token({"room": room, "code": code, "host": host}, "10.0.0.7")
    assert c == 200, o
    return o["tokens"]["member"]


def item(op, **kw):
    it, why = kr.board_item(op, dict(kw))
    assert why is None, why
    return it


SLOTS = [{"rect": [0, 6, 12, 12], "cams": [CAM1, CAM2], "cycle": {"mode": "motion", "hold": 5}},
         {"rect": [12, 6, 12, 12], "cams": [CAM3], "cycle": {"mode": "time", "every": 10}},
         {"rect": [0, 0, 4, 4], "cams": []}]


class SlotValidation(unittest.TestCase):
    def test_grid_with_slots(self):
        it, why = kr.board_item("grid", {"path": GRID, "slots": SLOTS, "sens": "high", "gap": 4})
        self.assertIsNone(why)
        self.assertEqual(it["rects"], {})                     # rects may be left out with spots
        self.assertEqual(it["slots"][0], {"rect": [0, 6, 12, 12], "cams": [CAM1, CAM2], "cycle": {"mode": "motion", "every": 10, "hold": 5}})
        self.assertEqual(it["slots"][2]["cams"], [])          # an empty spot is kept
        self.assertEqual(it["sens"], "high")
        ok2 = kr.board_item("grid", {"path": GRID, "rects": {CAM1: [0, 6, 12, 12]}, "slots": SLOTS[:1]})
        self.assertIsNone(ok2[1])

    def test_bad_slots_are_refused(self):
        many = [{"rect": [i % 12 * 2, i // 12 * 2, 2, 2], "cams": []} for i in range(kr.BOARD_SLOTS_MAX + 1)]
        nine = ["beta/box-1a2b/k/c%d.hang" % i for i in range(kr.BOARD_SLOT_CAMS_MAX + 1)]
        bad = [
            [{"rect": [0, 0, 12, 12], "cams": [CAM1]}, {"rect": [6, 6, 12, 12], "cams": [CAM2]}],   # overlap
            [{"rect": [0, 0, 12, 12], "cams": [CAM1]}, {"rect": [12, 0, 12, 12], "cams": [CAM1]}],  # one camera in two spots
            [{"rect": [0, 0, 12, 12], "cams": nine}],                                               # 9 cameras in a spot
            [{"rect": [0, 0, 12, 12], "cams": ["alpha/box-1a2b/k/x.hang"]}],                        # another room's camera
            [{"rect": [0, 0, 12, 12], "cams": ["beta/../x.hang"]}],
            [{"rect": [0, 0, 1, 12], "cams": [CAM1]}],                                              # under 2 x 2
            [{"rect": [0, 0, 12, 12], "cams": [CAM1], "cycle": {"mode": "random"}}],
            [{"rect": [0, 0, 12, 12], "cams": [CAM1], "cycle": {"mode": "time", "every": 1}}],
            [{"rect": [0, 0, 12, 12], "cams": [CAM1], "cycle": {"mode": "motion", "hold": 4000}}],
            [{"rect": [0, 0, 12, 12], "cams": [CAM1], "cycle": {"mode": "time", "every": True}}],
            many,
            {"rect": [0, 0, 4, 4]},                                                                 # not a list
            [],                                                                                     # nothing at all
        ]
        for sl in bad:
            self.assertIsNotNone(kr.board_item("grid", {"path": GRID, "slots": sl})[1], sl if not isinstance(sl, list) or len(sl) < 5 else "many")
        self.assertIsNotNone(kr.board_item("grid", {"path": GRID, "slots": SLOTS, "sens": "max"})[1])

    def test_clean_keeps_good_spots_only(self):
        b = kr.board_clean({"grids": {GRID: {"slots": SLOTS + [{"rect": [0, 0, 30, 2], "cams": []}, {"rect": [12, 6, 2, 2], "cams": []}],
                                             "sens": "loud", "gap": 2}}})
        g = b["grids"][GRID]
        self.assertEqual(len(g["slots"]), 3)                  # the out-of-picture and the overlapping spot dropped
        self.assertEqual(g["sens"], "medium")
        self.assertTrue(kr.board_has(b))
        self.assertIsNone(kr.board_grid_clean(GRID, {"rects": {}, "hidden": [], "slots": []}))


class Store(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.st = store(self.dir)

    def test_slots_saved_and_replaced(self):
        b, code, err = self.st.board_apply("beta", "grid", item("grid", path=GRID, rects={CAM1: [0, 6, 12, 12]}, slots=SLOTS, sens="low", gap=3))
        self.assertEqual((code, err), (200, None))
        g = b["grids"][GRID]
        self.assertEqual((len(g["slots"]), g["sens"], g["gap"]), (3, "low", 3))
        self.assertEqual(kr.AuthStore(self.dir).board("beta")["grids"][GRID]["slots"][0]["cams"], [CAM1, CAM2])   # survives a restart
        b, _, _ = self.st.board_apply("beta", "grid", item("grid", path=GRID, rects={CAM1: [0, 0, 24, 24]}))       # a 0.21.64 page's save
        self.assertEqual(b["grids"][GRID]["slots"], [])                                                            # a whole layout: no spots now
        b, _, _ = self.st.board_apply("beta", "grid", item("grid", path=GRID, slots=SLOTS[:1]))
        self.assertEqual((b["grids"][GRID]["rects"], len(b["grids"][GRID]["slots"])), ({}, 1))                    # spots alone keep the layout
        b, _, _ = self.st.board_apply("beta", "gridReset", item("gridReset", path=GRID))
        self.assertEqual(b["grids"], {})

    def test_split_and_unsplit(self):
        self.st.touch_room("beta")
        b, code, _ = self.st.board_apply("beta", "split", item("split", path=CAM2))
        self.assertEqual((code, b["split"]), (200, [CAM2]))
        self.assertTrue(self.st.room("beta")["persistent"])                    # a board item keeps the room, as pins do
        self.st.board_apply("beta", "split", item("split", path=CAM2))         # twice: once
        self.assertEqual(self.st.board("beta")["split"], [CAM2])
        row = [r for r in self.st.rooms_public() if r["slug"] == "beta"][0]
        self.assertEqual(row["board"], {"pins": 0, "spots": 0, "split": 1})
        self.assertEqual(self.st.board("alpha")["split"], [])                  # other rooms untouched
        b, _, _ = self.st.board_apply("beta", "unsplit", item("unsplit", path=CAM2))
        self.assertEqual(b["split"], [])
        self.assertEqual(self.st.board_apply("main", "split", item("split", path=CAM1))[1], 403)   # not in the Lobby
        self.assertIsNotNone(kr.board_item("split", {"path": "junk"})[1])

    def test_split_cap(self):
        for i in range(kr.BOARD_SPLIT_MAX):
            self.assertEqual(self.st.board_apply("beta", "split", item("split", path="beta/box-1a2b/k/c%d.hang" % i))[1], 200)
        b, code, err = self.st.board_apply("beta", "split", item("split", path=CAM1))
        self.assertEqual(code, 409)
        self.assertIn("on their own", err)
        self.assertEqual(kr.BOARD_SPLIT_MAX, 32)
        self.assertEqual((kr.BOARD_SLOTS_MAX, kr.BOARD_SLOT_CAMS_MAX), (32, 8))


class Service(unittest.TestCase):
    def setUp(self):
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store())
        self.b = mint(self.svc, "beta")

    def tearDown(self):
        self.svc.close()

    def post(self, body, tok=None):
        return self.svc.board_post(body, "Bearer " + (tok or self.b), "10.0.0.7")

    def test_publishers_of_the_room_only(self):
        body = {"room": "beta", "op": "split", "path": CAM1}
        self.assertEqual(self.post(body, tok=mint(self.svc, "beta", host="watch-9f9f", code="view-1"))[1], 403)   # a viewer
        self.assertEqual(self.post(body, tok=mint(self.svc, "alpha"))[1], 403)                                   # another room's token
        self.assertEqual(self.svc.board_post(body, None, "10.0.0.7")[1], 403)
        o, c = self.post(body)
        self.assertEqual((c, o["split"]), (200, [CAM1]))
        g, c = self.svc.board_get("beta", "Bearer " + self.b, None, "10.0.0.8")
        self.assertEqual((c, g["split"]), (200, [CAM1]))
        o, c = self.post({"room": "beta", "op": "grid", "path": GRID, "rects": {}, "slots": SLOTS, "sens": "medium", "gap": 2})
        self.assertEqual((c, len(o["grids"][GRID]["slots"])), (200, 3), o)
        o, c = self.post({"room": "beta", "op": "grid", "path": GRID, "slots": [{"rect": [0, 0, 24, 24], "cams": ["alpha/x/y/z.hang"]}]})
        self.assertEqual(c, 400)
        o, c = self.post({"room": "beta", "op": "unsplit", "path": CAM1})
        self.assertEqual((c, o["split"]), (200, []))

    def test_open_relay(self):
        st = kr.AuthStore(tempfile.mkdtemp())
        o, c = kr.board_open("POST", st, {"room": "beta", "op": "split", "path": CAM3})
        self.assertEqual((c, o["split"]), (200, [CAM3]))
        self.assertEqual(kr.board_open("GET", st, room="beta")[0]["split"], [CAM3])


class Federation(unittest.TestCase):
    def setUp(self):
        self.hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store())
        base = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(), hub=lambda: base, fed_token=lambda: self.fed)
        self.b = mint(self.spoke, "beta")

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()

    def test_spoke_forwards_slots_and_split(self):
        o, c = self.spoke.board_post({"room": "beta", "op": "grid", "path": GRID, "rects": {CAM1: [0, 6, 12, 12]}, "slots": SLOTS, "sens": "high"},
                                     "Bearer " + self.b, "10.0.0.7")
        self.assertEqual(c, 200, o)
        o, c = self.spoke.board_post({"room": "beta", "op": "split", "path": CAM3}, "Bearer " + self.b, "10.0.0.7")
        self.assertEqual((c, o["split"]), (200, [CAM3]), o)
        hub = self.hub.store.board("beta")
        self.assertEqual((len(hub["grids"][GRID]["slots"]), hub["grids"][GRID]["sens"], hub["split"]), (3, "high", [CAM3]))
        payload, _ = self.hub.bans_for_spoke("Bearer " + self.fed)
        self.spoke._board_mirror = {}
        self.spoke.board_mirror_apply(payload)
        g, c = self.spoke.board_get("beta", "Bearer " + self.b, None, "10.0.0.8")
        self.assertEqual((c, g["split"], g["grids"][GRID]["slots"][0]["cams"]), (200, [CAM3], [CAM1, CAM2]))


# ---------------------------------------------------------------------------------------------------------------- the page
class PageWiring(unittest.TestCase):
    def test_editor(self):
        ed = sec("  const gridEditor = (() => {", "  window.__gridEditor = gridEditor;")
        for need in ('el.appendChild(mkEl("span", "geempty", "Drop a camera here"));',
                     'sct.textContent = streams.length + (streams.length === 1 ? " available stream" : " available streams");',
                     'const q = mkEl("input", "gesq"); q.type = "search"; q.placeholder = "Search";',
                     'const ok = mkEl("span", "geok", at >= 0 ? "',                       # the check mark of a placed camera
                     'const head = mkEl("span", "gechip gehead", s.cams.length + " Cameras");',
                     'cy.append(mkEl("span", "gecycl", "Cycles on:"), radio("motion", "Motion"',
                     'const b1 = mkEl("button", "", "Add to this spot (cycle)");',
                     'const b2 = mkEl("button", "ghost", "Replace");',
                     'if (ev.shiftKey) { place(k, to, "add"); return; }',
                     '[s.cams, t.cams] = [t.cams, s.cams]; [s.cycle, t.cycle] = [t.cycle, s.cycle];',   # spot onto spot: swap
                     'if (from >= 0 && !c.slots[from].cams.length) c.slots[from].cams = was;',
                     'try { o.onDone?.(snap(), Number(gr.value), c.sens, { layout: c.layout }); } catch {}',
                     'for (const [v, t] of [["low", "Low"], ["medium", "Medium"], ["high", "High"]])'):
            self.assertIn(need, ed)
        apply = sec("      function applyPreset(n) {", "\n      }\n")
        self.assertIn("for (const s of streams) if (!placed.has(s.key)) groups.push({ cams: [s.key], cycle: gb.cycle() });", apply)
        self.assertIn('changed("n" + n);', apply)

    def test_box(self):
        self.assertIn("custom.__slots = sl; custom.__known = [...known].slice(0, 256); custom.__sens = sens || gridSens(g);", PAGE)
        plan = sec("  function gridPlan(g, ms, W, H) {", "\n  }\n")
        for need in ('gb.motion.sample("box:" + g.id + "|" + k,', "const k = gb.cycleTick(st, avail, s.cycle, now,",
                     "const avail = up.length ? up : present;", "if (known.has(k) || used.has(k)) continue;"):
            self.assertIn(need, plan)
        self.assertIn("g.drawn = plan.drawn; g.pool = plan.pool;", PAGE)
        self.assertIn("if (g.annSig !== sig && live) { g.annSig = sig; try { announceGrid(); } catch {} }", PAGE)
        ann = sec("  function announceGrid(now) {", "\n  }\n")
        self.assertIn("const ms = Array.isArray(g.drawn) ? g.drawn : gridOrdered(g);", ann)
        self.assertIn("more: pool.length ? pool.map((m) => ({ path: chanPath(ensureHang(m.entry.name))", ann)
        self.assertIn("...pool.map((m) => chanPath(ensureHang(m.entry.name)))],", ann)    # older viewers keep them hidden
        self.assertIn("const ms = g.drawn || gridOrdered(g), idx = gridCellAt(g, e);", PAGE)
        self.assertIn("const m = (g.drawn || gridOrdered(g))[g.hoverCell];", PAGE)

    def test_viewers(self):
        self.assertIn("if (e.slots) return vgSlotUnits(gp, meta, e);", PAGE)
        self.assertIn('gb.motion.sample("vg:" + name + "|" + k,', PAGE)
        self.assertIn("const dead = new Set([...out.filter((p) => !morePaths.has(p)), ...down.map((i) => members[i]).filter(Boolean)]);", PAGE)
        rg = sec("  function rgEdit(name) {", "  async function rgHide(gp, mp) {")
        self.assertIn('boardGrid("grid", name, { rects, gap: Math.max(0, Math.min(24, Math.round(Number(gap ?? vgDraft.gap) || 0))), slots: keep, sens: sens || vgDraft.sens })', rg)
        self.assertIn("const vgFirstRects = (slots) =>", PAGE)   # a 0.21.64 page draws each spot's first camera

    def test_split(self):
        self.assertIn("const isGridChild = (name) => gridChildOf.has(name) && !roomSplit.has(name);", PAGE)
        self.assertIn("const gridOwnerOf = (name) => (roomSplit.has(name) ? undefined : gridChildOf.get(name));", PAGE)
        self.assertIn("if (board.room === CHANNEL && CHANNEL !== LOBBY) for (const m of board.split || []) roomSplit.add(String(m));", PAGE)
        self.assertIn('if (isGridChild(n) || roomHid.has(n)) return "gridchild";', PAGE)   # removed from the room wins over split
        self.assertIn('label: sp ? "Back into the grid only" : "Show on its own in this room"', PAGE)
        self.assertIn('items.push({ value: "rgsplit", label: sp ? "Back into the grid only: " + cl : "Show " + cl + " on its own in this room",', PAGE)
        self.assertIn('const d = await boardPost(on ? "split" : "unsplit", { path }, quiet);', PAGE)
        self.assertIn("const newest = content.filter((n) => !roomSplit.has(n)).pop() ?? null;", PAGE)   # never pulls the stage
        for site in ("const gp = gridOwnerOf(name);   // 0.21.65: not a camera split out in this room",
                     "const gp = gridOwnerOf(target);   // 0.21.65: a split camera holds the stage itself",
                     "gridOwnerOf(selectedName) === name"):
            self.assertIn(site, PAGE)

    def test_relay_page_counts_split(self):
        with open(os.path.join(HERE, "relay.html"), encoding="utf-8") as f:
            r = f.read()
        self.assertIn('if (b.split) parts.push(b.split + " split out");', r)

    def test_crlf_and_escapes(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), "rb") as f:
            raw = f.read()
        self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"))
        for start, end in (("  const gridBuilder = (() => {", "  window.__gridEditor = gridEditor;"), ("  function vgStreams(", "  async function rgHide(")):
            self.assertTrue(all(ord(ch) < 128 for ch in sec(start, end)), start)   # the page writes non-ASCII as escapes


if __name__ == "__main__":
    unittest.main()
