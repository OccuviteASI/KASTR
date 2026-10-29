"""0.21.94 -- live feeds in a presentation (Kenton: "am I able to add other shares to the presentation? Such as another camera
feed or a grid? I would like this for presenters to use and backstage to be able to control.").

  record   the owner's `pres` carries lf {p, k, n, g?, by, at} (k: s camera/share, g box grid, c custom grid, l library stream),
           fs (the feed's streams -- the 0.21.92 presAudHide show set, so audience pages of any version keep them), lfc 1
           (this owner shows feeds) and lfo {n, at, why} (the last feed that went offline).
  control  every presenter and every backstage person: the owner applies its own; the others send presCtl {lf} WITHOUT `to`,
           so an older owner ignores it. Last writer wins. Next / Back from a feed = the slides again at the SAME slide; a move to
           another slide (strip, Home / End, an older backstage's Next) ends the feed. Black / White cover it and keep it.
  rides    adopt (hand-over / take-over) keeps lf; templates never carry it (tplSnap has no lf).
  page     the feed's streams decode off-stage (cgWarm), never get a tile of their own (hiddenChild), ride at the slide's
           priority (190 on stage / 150), play the full copy, are exempt from the weak-link pulse / quick park, are heard while
           the presentation is on my stage, and a library feed is subscribed through the library connection (libSync).
  offline  the owner's watch (700 ms) gives up on a feed whose streams all went quiet for 3 s (or never showed in 20 s): the
           slides again for everyone + a note to the presenters and backstage.

The pure feed helpers (lfClean / lfPaths / sameFeed) run in the bundled Chromium when Playwright is installed (skipped
otherwise; the string checks always run). Nothing here captures, lists or touches a real screen."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8", newline="") as f:
        return f.read()


PAGE = _read("moq-watch-lite.html")
PRES = _read(os.path.join("assets", "kastr-pres.js"))


def _fn(src, head):
    i = src.index(head)
    return src[i:src.index("\n  }\n", i) + 4]


def _chrome():
    for p in (os.environ.get("KASTR_TEST_CHROME") or "", os.path.join(HERE, "dist", "windows", "browser", "chrome.exe")):
        if p and os.path.isfile(p):
            return p
    d = HERE   # a git worktree: the main checkout's bundled browser
    for _ in range(4):
        d = os.path.dirname(d)
        c = os.path.join(d, "dist", "windows", "browser", "chrome.exe")
        if os.path.isfile(c):
            return c
    return None


class LineEndings(unittest.TestCase):
    def test_page_crlf_pres_lf(self):
        self.assertNotIn("\n", PAGE.replace("\r\n", ""))
        self.assertNotIn("\r", PRES)


class Record(unittest.TestCase):
    def test_publish_carries_the_feed(self):
        self.assertIn("...feedFields(),", _fn(PRES, "function publish("))
        ff = _fn(PRES, "function feedFields(")
        for k in ("lfc: 1", "lf: m.lf ?", "fs: lfPaths(m.lf)", "o.lfo = m.lfo"):
            self.assertIn(k, ff)

    def test_requests_have_no_to_and_the_owner_reads_them_first(self):
        si = _fn(PRES, "function sendFeedIntent(")
        self.assertIn("ctlSend({ id: deckId, bv: bk.rec.ver, lf: clean || { off: 1 } })", si)
        self.assertNotRegex(si, r"ctlSend\(\{[^}]*\bto\s*:")
        ap = _fn(PRES, "function applyOp(")
        self.assertLess(ap.index("ctl.lf !== undefined"), ap.index("if (ctl.to === undefined) return;"))
        self.assertIn("feedSet(null, who)", ap)

    def test_a_move_to_another_slide_ends_the_feed(self):
        g = _fn(PRES, "function goTo(")
        self.assertIn("if (mine.lf && ni !== mine.idx)", g)
        self.assertIn("mine.lf = null", g)

    def test_next_back_from_a_feed_is_the_same_slide(self):
        st = _fn(PRES, "    function step(d)")
        self.assertLess(st.index("if (v.lf) { showFeed(null); return; }"), st.index("clampI(v.idx + d"))
        self.assertIn("if (v.lf && clampI(i, v.n) === v.idx) { showFeed(null); return; }", _fn(PRES, "    function goto(i)"))
        rig = PRES[PRES.index("    next: () =>"):PRES.index("    setBackstage,", PRES.index("    next: () =>"))]
        self.assertEqual(rig.count("if (v && v.lf) return window.__pres.feed(null);"), 2)

    def test_feedset_bumps_the_version_and_notes_offline(self):
        fs = _fn(PRES, "function feedSet(")
        self.assertIn("mine.ver++", fs)
        self.assertIn('why === "offline"', fs)
        self.assertIn("mine.lfo = { n: was.n", fs)

    def test_adopt_keeps_the_feed(self):
        ad = _fn(PRES, "function adopt(")
        self.assertIn("m.lf = lf ? Object.assign({}, lf", ad)
        self.assertLess(ad.index("pendAdopt(m, rec);"), ad.index("m.lf = lf ?"))

    def test_templates_carry_no_feed(self):
        self.assertNotRegex(_fn(PRES, "function tplSnap("), r"\blf\b|\blfo\b|\bfs\b")

    def test_audience_show_set_includes_the_feed(self):
        # the 0.21.92 presAudHide seam: fs paths are shown even with "Audience can see each other" off
        self.assertRegex(PRES, r"for \(const f of \(Array\.isArray\(rec\.fs\) \? rec\.fs : \[\]\)\.slice\(0, 16\)\)[^\n]*show\.add\(f\)")

    def test_offline_watch(self):
        self.assertIn("const LF_GONE_MS = 3000, LF_NEVER_MS = 20000;", PRES)
        fw = _fn(PRES, "function feedWatch(")
        self.assertIn('feedSet(null, mine.lf.by || myPerson(), "offline")', fw)
        self.assertIn("presNote(", fw)
        self.assertIn("setInterval(() => { try { feedWatch(); feedSync(); }", PRES)

    def test_drawing_and_controls(self):
        for k in ("function drawFeed(", "function paintFeed(", 'class="lfmark"', "lfback", 'data-k="feed"',
                  "feed: (src) =>", "sources: ", "feedState: "):
            self.assertIn(k, PRES)


class PageSeams(unittest.TestCase):
    def test_hooks(self):
        for h in ("window.__presFeedWant", "window.__presFeedWanted", "window.__presFeedSources", "window.__presFeedState",
                  "window.__presFeedAvail", "window.__presFeedLabel", "window.__presOwnFrame"):
            self.assertIn(h + " =", PAGE, h)

    def test_subscription_ladder(self):
        self.assertIn("presFeedSet.has(n)", PAGE[PAGE.index("cgWarm.has = (n) =>") - 200:PAGE.index("cgWarm.has = (n) =>") + 200])
        self.assertIn("presFeedSet.has(name) ? (presFeedStage() ? 190 : 150) : 0", PAGE)
        self.assertIn("const feedFull = presFeedSet.has(name);", PAGE)
        self.assertIn("!presFeedSet.has(name)) continue;   // 0.21.94", PAGE)
        self.assertIn("(libTiles.has(name) || presFeedSet.has(name)) && cgWarm.has(name)", PAGE)
        self.assertIn("if (presFeedHear.has(name) && presFeedStage())", PAGE)
        self.assertIn("(presFeedSet.has(name) && (gridMode || name !== selectedName) && !stageMosaicNames.has(name))", PAGE)
        self.assertIn('for (const k of presFeedSet) if (isLibPath(k) && !want.has(k)) want.set(k, "pres");', PAGE)

    def test_guests_see_a_library_feed_only_when_pinned(self):
        av = PAGE[PAGE.index("window.__presFeedAvail ="):PAGE.index("window.__presFeedAvail =") + 900]
        self.assertIn("libGuest() && !boardPinned(p)", av)


@unittest.skipUnless(_chrome(), "no Chromium for the feed helpers")
class Helpers(unittest.TestCase):
    """lfClean / lfPaths / sameFeed as kastr-pres.js has them, in Chromium."""

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            raise unittest.SkipTest("no Playwright")
        i = PRES.index("  const LF_KINDS")
        j = PRES.index("\n", PRES.index("  const sameFeed")) + 1
        cls._pw = sync_playwright().start()
        cls._br = cls._pw.chromium.launch(executable_path=_chrome(), headless=True)
        cls._pg = cls._br.new_page()
        cls._pg.set_content("<!doctype html><script>\n" + PRES[i:j] +
                            "\nwindow.lfClean = lfClean; window.lfPaths = lfPaths; window.sameFeed = sameFeed;</script>")

    @classmethod
    def tearDownClass(cls):
        cls._br.close()
        cls._pw.stop()

    def clean(self, x):
        return self._pg.evaluate("(x) => lfClean(x)", x)

    def test_a_camera(self):
        self.assertEqual(self.clean({"k": "s", "p": "room/box/dan/camera.hang", "n": "  Dan \n cam "}),
                         {"k": "s", "p": "room/box/dan/camera.hang", "n": "Dan cam"})

    def test_bad_feeds(self):
        for x in ({"k": "x", "p": "a/b.hang"}, {"k": "s", "p": "a/../b.hang"}, {"k": "s", "p": "a/b-low.hang"},
                  {"k": "s", "p": "a/b.mp4"}, {"k": "s", "p": "/a/b.hang"}, {"k": "c", "p": "a/b.hang"}, None, "x"):
            self.assertIsNone(self.clean(x), x)

    def test_a_custom_grid_is_bounded(self):
        cams = ["r/b/p%d/camera.hang" % i for i in range(30)]
        g = {"slots": [{"rect": [0, 0, 12, 12], "cams": cams[:20], "cycle": {"mode": "motion", "every": 1}},
                       {"rect": [12, 0, 99, 12], "cams": cams[10:30]}, {"rect": [0, 0, 0, 5], "cams": cams[:2]}], "gap": 3}
        o = self.clean({"k": "c", "p": "r/b/grid.hang", "n": "G", "g": g})
        self.assertEqual(len(o["g"]["slots"]), 2)
        self.assertEqual(o["g"]["slots"][0]["cycle"], {"mode": "motion", "every": 2})
        self.assertEqual(o["g"]["slots"][1]["rect"], [12, 0, 24, 12])
        paths = self._pg.evaluate("(x) => lfPaths(lfClean(x))", {"k": "c", "p": "r/b/grid.hang", "g": g})
        self.assertLessEqual(len(paths), 16)
        self.assertEqual(len(set(paths)), len(paths))

    def test_same_feed(self):
        a = {"k": "s", "p": "r/b/a/camera.hang"}
        self.assertTrue(self._pg.evaluate("([a, b]) => sameFeed(a, b)", [a, dict(a, n="other", by="x")]))
        self.assertFalse(self._pg.evaluate("([a, b]) => sameFeed(a, b)", [a, dict(a, p="r/b/c/camera.hang")]))
        self.assertTrue(self._pg.evaluate("() => sameFeed(null, null)"))


if __name__ == "__main__":
    unittest.main()
