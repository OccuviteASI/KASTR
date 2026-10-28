"""0.21.93 item 4 -- the heal path for a screen / window share whose PICTURE stops while its SOUND keeps playing (field:
Kordale's My room, Support Laptop watching through an invite link, ~5 times in 45 min; Pause + Resume cured it each time).

  viewer   the picture stops while the sound arrives: re-subscribe at 6 s; still stalled 6 s later -> report to the owner
           (room.json `stalled`, kind "video"), again every 15 s; never for a shed / parked / hidden / unwatched tile, a hidden
           page or a silent tile (a paused share's card has no sound). One line per step, captions + track clocks in diag.
  path     room.json on <room>/<host>/~member/<peer> -- written in My room too (only the PUBLIC state is off there), and an
           invite-link / My room guest's token puts <room>/<guest host>, which covers it; the owner subscribes the room.
  owner    nudgeFromViewer(path, "video") on a native screen share -> POST /api/rtsp/heal -> Publisher.heal: one heal per 30 s,
           6 per 10 min; the moq import alone first (ffmpeg kept), the whole pair when an import restart in the last 120 s
           did not bring the picture back. Pause + Resume = Bridge.pause -> Publisher.nudge("pause") then nudge("resume"):
           two FULL pair restarts (ffmpeg + moq each time).

The viewer's step function runs in the bundled Chromium when Playwright is installed (skipped otherwise; the string checks always
run). The import-only vs full-pair checks run a real ffmpeg (lavfi test source, no screen) through the real pump into stand-in
moq processes. Nothing here captures, lists or touches a real screen."""
import os
import re
import subprocess
import sys
import threading
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_rtsp    # noqa: E402


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


PAGE = _read("moq-watch-lite.html")
RTSP = _read("kastr_rtsp.py")


def _js_fn(p, head):
    i = p.index(head)
    return p[i:p.index("\n  }\n", i) + 4]


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


def _ffmpeg():
    try:
        ff = kastr_rtsp.find_ffmpeg()
    except Exception:
        ff = None
    if ff and os.path.exists(ff):
        return ff
    d = HERE
    for _ in range(4):
        d = os.path.dirname(d)
        c = os.path.join(d, "bin", "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


# ---- the viewer ---------------------------------------------------------------------------------------------------------

VIEWER_JS = "\n".join([
    PAGE[PAGE.index("  const VSTALL_ARM_MS"):PAGE.index("\n", PAGE.index("  const VSTALL_ARM_MS"))],
    _js_fn(PAGE, "  function vstallStep(st, s) {"),
    _js_fn(PAGE, "  function vstallExempt(name, t) {"),
])

# drive vstallStep with a 1 s tick: frames/bytes from callbacks of the time
RUN = """(plan) => {
  const st = { vf: 0, vAt: 0, vb: 0, vbAt: 0, ab: 0, aAt: 0, had: false, since: 0, resubAt: 0, reportAt: 0, reports: 0, resubs: 0 };
  let vf = 0, vb = 0, ab = 0; const out = [];
  for (let s = 0; s <= plan.until; s++) {
    const now = 100000 + s * 1000;
    const seg = plan.segs.find((g) => s >= g.from && s < g.to) || {};
    if (seg.reset) { vf = 0; vb = 0; ab = 0; }
    if (seg.video) { vf += 30; vb += 50000; }
    if (seg.vbytes) vb += 50000;
    if (seg.audio !== false) ab += 4000;
    const r = vstallStep(st, { now, vFrames: vf, vBytes: vb, aBytes: ab, exempt: seg.exempt || "" });
    const keys = Object.keys(r).filter((k) => r[k] !== undefined && r[k] !== false);
    if (keys.length) out.push([s, r]);
  }
  return out;
}"""


class ViewerStrings(unittest.TestCase):
    def test_thresholds(self):
        self.assertIn("const VSTALL_ARM_MS = 2000, VSTALL_RESUB_MS = 6000, VSTALL_REPORT_MS = 6000, VSTALL_REREPORT_MS = 15000, "
                      "VSTALL_AUDIO_MS = 3000, VSTALL_MAX_REPORTS = 6;", PAGE)

    def test_every_tile_every_tick_and_the_old_checks_step_aside(self):
        self.assertIn('      if (t.cg) continue;   // 0.21.66 (e): drawn here, nothing to starve\n'
                      '      try { vstallTick(name, t, nowMs); } catch (e) { console.warn("KASTR: video-stall check", e); }   // 0.21.93', PAGE)
        self.assertIn('if (!t.vs?.since && (!t.frozenResubAt || nowMs - t.frozenResubAt > 30000)) { t.frozenResubAt = nowMs; resubscribe(name, "Picture stopped"); }', PAGE)
        self.assertIn("nowMs - t.starveSince > 5000 && !t.vs?.since) stallReport(name, nowMs);", PAGE)

    def test_exemptions(self):
        body = _js_fn(PAGE, "  function vstallExempt(name, t) {")
        for x in ('=== "never") return "parked"', 'if (t.shed) return "shed (weak connection)"', 'return "no video"',
                  'if (!isWatched(name)) return "unwatched"', 'return "hidden"', 'document.visibilityState === "hidden") return "page hidden"'):
            self.assertIn(x, body)

    def test_steps_log_and_report_with_the_kind(self):
        body = _js_fn(PAGE, "  function vstallTick(name, t, nowMs) {")
        self.assertIn('resubscribe(name, "Picture stopped while the sound plays");', body)
        self.assertIn('const into = !wrRoomOf(name);', body)
        self.assertIn('window.__stallAnnounce?.set?.(name, "video")', body)
        self.assertIn('window.__stallAnnounce?.clear?.(name)', body)
        self.assertIn('picture back after', body)
        self.assertIn('caption \\u201c" + vstallCaption(t)', body)
        self.assertIn('"video frame " + ago(st.vAt) + " ago (" + st.vf + "), video bytes " + ago(st.vbAt) + " ago, sound bytes " + ago(st.aAt) + " ago"', body)
        # one line per step: the status bar and, on the app, launch.log through the bridge
        note = _js_fn(PAGE, "  function vstallNote(line) {")
        self.assertIn('fetch("/api/rtsp/note"', note)
        self.assertIn('(window.__kastrClient?.class || "app") !== "web"', note)

    def test_diag(self):
        self.assertIn("vstall: (() => { try { return window.__vstall(); } catch { return null; } })(),", PAGE)
        self.assertIn("window.__vstall = () => ({ ...vstallTotals, recent: vstallLog.map((x) => ({ ...x })),", PAGE)


@unittest.skipUnless(_chrome(), "no Chromium for the viewer's step function")
class ViewerDetection(unittest.TestCase):
    """The page's own vstallStep / vstallExempt in Chromium."""

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            raise unittest.SkipTest("no Playwright")
        cls._pw = sync_playwright().start()
        cls._br = cls._pw.chromium.launch(executable_path=_chrome(), headless=True)
        cls._pg = cls._br.new_page()
        cls._pg.set_content("<!doctype html><script>let isWatched = (n) => n !== 'unwatched';\n" + VIEWER_JS + "\n"
                            "window.vstallStep = vstallStep; window.vstallExempt = vstallExempt;</script>")

    @classmethod
    def tearDownClass(cls):
        cls._br.close()
        cls._pw.stop()

    def run_plan(self, segs, until):
        return [(s, r) for s, r in self._pg.evaluate(RUN, {"segs": segs, "until": until})]

    def test_the_page_scripts_compile(self):
        # every inline script parsed (not run) by Chromium; a module's static imports are dropped and its body wrapped in an
        # async function, so top-level await still parses
        bad = []
        for m in re.finditer(r"<script([^>]*)>([\s\S]*?)</script>", PAGE):
            attrs, code = m.group(1), m.group(2)
            if "src=" in attrs or "importmap" in attrs or not code.strip():
                continue
            if "module" in attrs:
                code = re.sub(r"^\s*import\b[^\n]*$", "", code, flags=re.M)
            err = self._pg.evaluate("""(c) => { try { new Function('"use strict"; return async () => {\\n' + c + '\\n}'); return ""; }
                                                catch (e) { return String(e); } }""", code)
            if err:
                bad.append((PAGE[:m.start()].count("\n") + 1, err))
        self.assertEqual(bad, [])

    def test_a_steady_tile_does_nothing(self):
        self.assertEqual(self.run_plan([{"from": 0, "to": 99, "video": True}], 60), [])

    def test_stall_with_sound_resubscribes_then_reports_then_heals(self):
        out = self.run_plan([{"from": 0, "to": 10, "video": True}, {"from": 10, "to": 40}, {"from": 40, "to": 99, "video": True}], 50)
        # frames last grew at s=9: armed at 11 (2 s), re-subscribed at 15 (6 s), reported at 21 (6 s later), again at 36 (+15 s,
        # with a fresh look), healed at 40 (31 s after the last frame)
        self.assertEqual([(s, sorted(k for k in r)) for s, r in out],
                         [(11, ["start"]), (15, ["resub"]), (21, ["report"]), (36, ["report", "resub"]), (40, ["end", "ms", "reports", "resubs"])])
        end = out[-1][1]
        self.assertEqual((end["end"], end["ms"], end["resubs"], end["reports"]), ("healed", 31000, 2, 2))

    def test_frames_back_after_the_resubscribe_never_reports(self):
        out = self.run_plan([{"from": 0, "to": 10, "video": True}, {"from": 10, "to": 17}, {"from": 17, "to": 99, "video": True, "reset": False}], 30)
        self.assertEqual([s for s, r in out if r.get("report")], [])
        self.assertEqual(out[-1][1]["end"], "healed")

    def test_counters_starting_over_after_the_resubscribe(self):
        out = self.run_plan([{"from": 0, "to": 10, "video": True}, {"from": 10, "to": 16}, {"from": 16, "to": 17, "reset": True},
                             {"from": 17, "to": 18}, {"from": 18, "to": 99, "video": True}], 30)
        self.assertEqual(out[-1][1]["end"], "healed")   # the drop to 0 is no progress; the climb from 0 is

    def test_silent_tile_is_never_armed(self):
        # a paused share: the card has no sound -- and a share that stopped altogether is the general stall check's case
        self.assertEqual(self.run_plan([{"from": 0, "to": 10, "video": True}, {"from": 10, "to": 61, "audio": False}], 60), [])

    def test_the_sound_stopping_mid_stall_ends_it(self):
        out = self.run_plan([{"from": 0, "to": 10, "video": True}, {"from": 10, "to": 25}, {"from": 25, "to": 60, "audio": False}], 60)
        self.assertEqual([s for s, r in out if r.get("report")], [21])
        self.assertEqual([r.get("end") for s, r in out if r.get("end")], ["silent"])

    def test_never_had_a_picture_is_not_this_check(self):
        self.assertEqual(self.run_plan([{"from": 0, "to": 60}], 60), [])

    def test_video_bytes_still_arriving_but_no_frame_is_a_stall(self):
        out = self.run_plan([{"from": 0, "to": 10, "video": True}, {"from": 10, "to": 30, "vbytes": True}], 30)
        self.assertEqual([s for s, r in out if r.get("resub")], [15])

    def test_exempt_tiles(self):
        for why in ("shed (weak connection)", "parked", "hidden", "unwatched", "page hidden"):
            out = self.run_plan([{"from": 0, "to": 10, "video": True}, {"from": 10, "to": 60, "exempt": why}], 60)
            self.assertEqual(out, [], why)

    def test_an_exemption_mid_stall_ends_it(self):
        out = self.run_plan([{"from": 0, "to": 10, "video": True}, {"from": 10, "to": 25}, {"from": 25, "to": 60, "exempt": "shed (weak connection)"}], 60)
        self.assertEqual([s for s, r in out if r.get("report")], [21])
        self.assertEqual(out[-1][1]["end"], "exempt")
        self.assertEqual(out[-1][1]["why"], "shed (weak connection)")

    def test_gives_up_after_six_reports(self):
        out = self.run_plan([{"from": 0, "to": 10, "video": True}, {"from": 10, "to": 400}], 400)
        self.assertEqual(len([1 for s, r in out if r.get("report")]), 6)
        self.assertEqual([r["end"] for s, r in out if r.get("end")], ["gave up"])   # and quiet after it until a frame lands

    def test_vstall_exempt_reads_the_tile(self):
        js = """([vis, shed, hasVideo, shown, name, hidden]) => {
          if (hidden) Object.defineProperty(document, 'visibilityState', { get: () => 'hidden', configurable: true });
          else Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
          const t = { watch: { getAttribute: () => vis }, shed, hasVideo, fb: null, noDecode: null,
                      pane: { classList: { contains: () => shown }, style: { display: '' } } };
          return vstallExempt(name, t); }"""
        cases = [(("auto", False, True, True, "a", False), ""), (("never", False, True, True, "a", False), "parked"),
                 (("auto", True, True, True, "a", False), "shed (weak connection)"), (("auto", False, False, True, "a", False), "no video"),
                 (("auto", False, True, False, "a", False), "hidden"), (("auto", False, True, True, "unwatched", False), "unwatched"),
                 (("auto", False, True, True, "a", True), "page hidden")]
        for args, want in cases:
            self.assertEqual(self._pg.evaluate(js, list(args)), want, args)


# ---- the report path (My room, invite-link guests) ----------------------------------------------------------------------

class ReportPath(unittest.TestCase):
    def test_room_json_carries_the_kind(self):
        self.assertIn('const stallAnn = keyedAnnouncer("~stalled", { state: (key, p) => window.__state.set("stalled", { path: key, on: p != null, '
                      'kind: p != null && String(p).includes("#") ? String(p).split("#").pop() : "" }) });', PAGE)
        self.assertIn('set: (path, kind) => stallAnn.set(path, kind ? path + "#" + kind : path)', PAGE)
        self.assertIn('Object.assign({ path: String(value.path), at: now, n: 1 }, kind ? { kind } : {})', PAGE)
        self.assertIn('if (kind) cur.kind = kind; else delete cur.kind;', PAGE)

    def test_room_json_is_written_in_my_room(self):
        # only the PUBLIC state is off in My room; the member broadcast (room.json) is not gated by isPersonalSlug
        self.assertIn('const pubState = stateProducer(() => (isPersonalSlug(CHANNEL) ? "" : "~state/"', PAGE)
        self.assertIn('const roomState = stateProducer(() => CHANNEL + "/" + HOSTNAME1 + "/~member/" + statePeer(), ["room.json", "chat.json", "pt.json"]', PAGE)

    def test_the_owner_reads_it_and_passes_kind_and_reporter(self):
        self.assertIn('if (String(path).split("/").filter(Boolean)[2] === "~member") { memberAccept(String(path), entry.active); continue; }', PAGE)
        self.assertIn('try { window.__publisher?.nudge?.(st.path, String(st.kind || ""), path); } catch {}', PAGE)
        body = _js_fn(PAGE, "  function stalledAccept(path, active) {")   # the older announce path keeps working, with the kind
        self.assertIn('const kind = target.includes("#") ? target.split("#").pop() : "";', body)
        self.assertIn("window.__publisher?.nudge?.(target, kind)", body)

    def test_guest_tokens_put_their_member_broadcast(self):
        import tempfile
        import kastr_relay as kr
        st = kr.AuthStore(tempfile.mkdtemp())
        st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
        svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)
        try:
            o, c = kr.personal_op(svc.store, {"op": "create", "name": "Kordale", "code": "abcd1234", "access": "pub-1"}, "10.0.0.5")
            self.assertEqual(c, 200, o)
            slug = o["slug"]
            o, c = svc.token({"room": slug, "code": "pub-1", "host": "kordale-ab12", "roomCode": "abcd1234"}, "10.0.0.7")
            self.assertEqual(c, 200, o)
            own = o["tokens"]["member"]
            o, c = svc.invite_create_api({"room": slug, "ttl": 3600}, "Bearer " + own, "10.0.0.7")
            self.assertEqual(c, 200, o)
            link = o["token"]
            svc.people_api({"op": "beat"}, "Bearer " + own, "10.0.0.7")   # the owner is in
            o, c = svc.token({"room": slug, "code": "", "host": "support-cd34", "invite": link}, "10.0.0.9")
            self.assertEqual(c, 200, o)
            cl = kr.verify_token(o["tokens"]["member"], svc.key)
            grant = kr.claims_to_grant(cl)
            member = slug + "/support-cd34/~member/p1"
            self.assertTrue(any(member == p or member.startswith(p.rstrip("/") + "/") for p in grant["publish"]), grant)
            owner = kr.claims_to_grant(kr.verify_token(own, svc.key))
            self.assertTrue(any(member.startswith(p.rstrip("/") + "/") for p in owner["subscribe"] if p), owner)
        finally:
            svc.close()


# ---- the owner ----------------------------------------------------------------------------------------------------------

class OwnerPage(unittest.TestCase):
    def test_video_reports_on_a_native_screen_share_go_to_the_heal(self):
        body = _js_fn(PAGE, "  function nudgeFromViewer(fullPath, kind, from) {")
        i = body.index('if (kind === "video") {')
        self.assertLess(i, body.index("if (slot.lastNudge && now - slot.lastNudge < 8000) return;"))   # before the old gates
        self.assertIn("if (vs && isScreenShare(vs.entry)) { healFromViewer(vs, fullPath, from); return; }", body)
        heal = _js_fn(PAGE, "  function healFromViewer(slot, fullPath, from) {")
        self.assertIn('nativePost("/api/rtsp/heal", { id: slot.entry.feedId, why: "viewer-video" })', heal)
        self.assertIn('if (now - (slot.healPostAt || 0) < 5000) return "dup";', heal)
        self.assertIn("slot.entry.sharePaused", heal)
        self.assertIn('"pair " + name + ": video stall reported by " + who', heal)

    def test_route(self):
        self.assertIn('"/api/rtsp/heal",                                            # 0.21.93: a viewer\'s video stall', RTSP)
        self.assertIn('reply(bridge.heal(payload.get("id"), str(payload.get("why") or "viewer-video").strip()[:32]))', RTSP)

    def test_pause_resume_is_two_full_pair_restarts(self):
        body = RTSP[RTSP.index("    def pause(self, feed_id, on):"):]
        body = body[:body.index("\n    def ", 10)]
        self.assertIn('pub.nudge("pause" if on else "resume")', body)


def _pub(url="screen://window/42", role="main", paused=False):
    logs = []
    bridge = types.SimpleNamespace(_child_ended=lambda pid: None, _child_started=lambda *a: None, log=logs.append,
                                   _lib_list_pump=lambda pub: False, moq="moq", own_pid=lambda: os.getpid())
    pub = kastr_rtsp.Publisher(bridge, types.SimpleNamespace(url=url, sar=None, id=1), "room/h/screen.hang", "http://r/",
                               audio=False, role=role)
    pub.running = True
    pub.since = 1000.0
    pub.paused = paused
    return pub, logs


class OwnerRateLimit(unittest.TestCase):
    def setUp(self):
        self.pub, self.logs = _pub()
        self.imports = []
        self.pairs = []
        self.pub.restart_import = lambda why="": self.imports.append(why) or True
        self.pub._heal_pair = lambda: self.pairs.append(1)
        self.started = []
        self.th = mock.patch.object(kastr_rtsp.threading, "Thread",
                                    side_effect=lambda **kw: types.SimpleNamespace(start=lambda: (self.started.append(kw["name"]), kw["target"]())))
        self.th.start()

    def tearDown(self):
        self.th.stop()

    def heal(self, t):
        return self.pub.heal("viewer-video", now=t)["did"]

    def test_import_first_then_the_pair_then_import_again(self):
        self.assertEqual(self.heal(1000), "import")
        self.assertEqual(self.heal(1010), "limited")          # one per 30 s
        self.assertEqual(self.heal(1035), "pair")             # a fresh report within 120 s of an import restart
        self.assertEqual(self.heal(1100), "import")           # after a pair restart, the cheap step again
        self.assertEqual((len(self.imports), len(self.pairs)), (2, 1))
        self.assertEqual(self.pub.heals, {"import": 2, "pair": 1, "limited": 1, "refused": 0})
        self.assertTrue(any("rtsp heal room/h/screen.hang step=import why=viewer-video" in m and "moq import only, ffmpeg kept" in m for m in self.logs), self.logs)
        self.assertTrue(any("step=pair" in m and "the import restart 35 s ago did not help -- full pair restart" in m for m in self.logs), self.logs)
        self.assertTrue(any("rtsp heal room/h/screen.hang limited why=viewer-video -- healed 10 s ago (one per 30 s)" in m for m in self.logs), self.logs)

    def test_an_import_restart_long_ago_starts_over_at_import(self):
        self.assertEqual(self.heal(1000), "import")
        self.assertEqual(self.heal(1000 + kastr_rtsp.HEAL_ESCALATE_S + 1), "import")

    def test_six_per_ten_minutes(self):
        did = [self.heal(1000 + i * 31) for i in range(8)]
        self.assertEqual(did.count("limited"), 2)
        self.assertEqual(did[6:], ["limited", "limited"])
        self.assertTrue(any("6 heals in the last 10 min (at most 6)" in m for m in self.logs), self.logs)
        self.assertEqual(self.heal(1000 + 601), "import")      # the window moves on (the first heal left it)

    def test_refusals(self):
        for kw, why in (({"paused": True}, "paused"), ({"url": "rtsp://cam/1"}, "not a screen share"), ({"role": "low"}, "not a screen share")):
            pub, logs = _pub(**kw)
            r = pub.heal("viewer-video", now=1000)
            self.assertEqual(r["did"], "refused")
            self.assertIn(why, r["reason"])
            self.assertTrue(any("rtsp heal" in m and "refused" in m for m in logs), logs)
        pub, logs = _pub()
        pub.running = False
        self.assertEqual(pub.heal("viewer-video", now=1000)["did"], "refused")

    def test_no_pump_goes_straight_to_the_pair(self):
        self.pub.restart_import = lambda why="": False
        self.assertEqual(self.heal(1000), "pair")

    def test_the_bridge_and_info(self):
        b = types.SimpleNamespace(_pubs={1: self.pub})
        self.assertEqual(kastr_rtsp.Bridge.heal(b, 1)["did"], "import")
        self.assertEqual(kastr_rtsp.Bridge.heal(b, 9)["did"], "refused")
        with mock.patch.object(self.pub, "_library_info", return_value=None), mock.patch.object(self.pub, "_listed_info", return_value=None):
            info = self.pub.info()
        self.assertEqual(info["heals"]["import"], 1)
        self.assertEqual(info["lastHeal"]["step"], "import")
        self.assertIn("importRestarts", info)

    def test_the_viewer_bucket_refusal_does_not_apply(self):
        # a full pair restart from the heal is "heal" (api bucket) -- the 60 s viewer-report refusal is for older pages' nudges
        self.assertEqual(kastr_rtsp.nudge_bucket("heal"), "api")


# a stand-in for `moq import`: copies stdin to a file; with "wedge" it never reads
FAKE_MOQ = r"""
import sys, time
import os
out = open(sys.argv[1] + "." + str(os.getpid()), "wb")
if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):   # a one-shot marker: the first moq wedges, its replacement does not
    os.remove(sys.argv[2])
    while True:
        time.sleep(1)
while True:
    b = sys.stdin.buffer.read1(65536) if hasattr(sys.stdin.buffer, "read1") else sys.stdin.buffer.read(65536)
    if not b:
        break
    out.write(b)
    out.flush()
out.close()
"""


@unittest.skipUnless(_ffmpeg(), "no ffmpeg")
class ImportVersusPair(unittest.TestCase):
    """Real ffmpeg (lavfi, ~real time, MPEG-TS) -> the real pump -> stand-in moq processes; the real start / restart_import /
    heal / _watch."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.n = 0
        self.wedge_first = False
        self.pub, self.logs = _pub()
        self.pub.bridge.log = lambda m: self.logs.append(m)
        self.procs = []
        self.pub.bridge._child_started = lambda p, *a: self.procs.append(p)
        pub = self.pub

        def args():
            self.n += 1
            ff = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-progress", "pipe:2", "-stats_period", "0.5", "-re",
                  "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                  "-c:v", "mpeg2video", "-g", "15", "-c:a", "mp2", "-f", "mpegts", "-pat_period", "0.1", "pipe:1"]
            return ff, self._moq_argv()

        pub._args = args
        pub.running = False
        self.p1 = mock.patch.object(kastr_rtsp, "SCREEN_STALL_S", 0)
        self.p1.start()

    def _moq_argv(self):
        self.n += 1
        path = os.path.join(self.dir, "moq-%d.ts" % self.n)
        marker = os.path.join(self.dir, "wedge-once")
        if self.wedge_first and self.n <= 2:
            open(marker, "w").close()
        # the base interpreter: a venv's python.exe on Windows is a launcher whose child has another pid
        return [getattr(sys, "_base_executable", None) or sys.executable, "-c", FAKE_MOQ, path, marker]

    def tearDown(self):
        self.pub.stop()
        self.p1.stop()
        for p in self.procs:
            try:
                p.kill()
            except OSError:
                pass
            p.wait(timeout=5)
        time.sleep(0.3)   # the drain / pump threads see EOF
        for p in self.procs:
            for f in (p.stdin, p.stdout, p.stderr):
                try:
                    f and f.close()
                except OSError:
                    pass

    def wait(self, cond, t=15):
        t0 = time.time()
        while time.time() - t0 < t:
            if cond():
                return True
            time.sleep(0.1)
        return False

    def outfile(self, p):
        return p.args[3] + "." + str(p.pid)

    def size(self, p):
        try:
            return os.path.getsize(self.outfile(p))
        except OSError:
            return 0

    def test_import_restart_keeps_ffmpeg_and_starts_at_a_pat_then_the_pair(self):
        pub = self.pub
        pub.start()
        self.assertTrue(pub.pumped)                                 # every screen share's main pair passes the pump now
        ff, mq1 = pub.procs
        gen = pub._gen
        self.assertTrue(self.wait(lambda: self.size(mq1) > 20000), "no bytes reached the first moq")
        self.assertEqual(pub.heal("viewer-video", now=5000)["did"], "import")
        self.assertTrue(self.wait(lambda: pub.procs[1] is not mq1 and pub._reimp is None), "the import never restarted")
        mq2 = pub.procs[1]
        self.assertIs(pub.procs[0], ff)                             # ffmpeg kept
        self.assertIsNone(ff.poll())
        self.assertEqual(pub._gen, gen)                             # the same generation
        self.assertEqual(mq1.wait(timeout=5), 0)                    # the old moq got EOF and ended by itself
        self.assertTrue(self.wait(lambda: self.size(mq2) > 20000), "no bytes reached the new moq")
        with open(self.outfile(mq2), "rb") as f:
            head = f.read(4)
        self.assertEqual(head[0], 0x47)
        self.assertTrue(head[1] & 0x40 and ((head[1] & 0x1F) << 8 | head[2]) == 0, head)   # a PAT first: the tables before the media
        time.sleep(1.5)
        self.assertTrue(pub.running)                                # the watcher did not end the pair on the old moq's exit
        self.assertEqual(pub.importRestarts, 1)
        line = [m for m in self.logs if m.startswith("rtsp import restart")]
        self.assertTrue(line and "old moq %d closed" % mq1.pid in line[0] and "ffmpeg %d kept" % ff.pid in line[0], self.logs)
        # a second report 35 s on: the import restart did not help -> the whole pair
        self.assertEqual(pub.heal("viewer-video", now=5035)["did"], "pair")
        self.assertTrue(self.wait(lambda: pub._gen > gen and pub.running and pub.procs and pub.procs[0] is not ff), "no pair restart")
        self.assertIsNotNone(ff.poll())
        ff2, mq3 = pub.procs
        self.assertTrue(self.wait(lambda: self.size(mq3) > 20000), "no bytes after the pair restart")
        self.assertEqual(pub.nudges["api"], 1)

    def test_a_wedged_moq_is_killed_and_replaced(self):
        self.wedge_first = True
        pub = self.pub
        pub.start()
        ff, mq1 = pub.procs
        time.sleep(3)                                               # the pump fills its pipe and blocks on the wedged moq
        t0 = time.time()
        self.assertEqual(pub.heal("viewer-video", now=5000)["did"], "import")
        self.assertTrue(self.wait(lambda: pub.procs[1] is not mq1 and pub._reimp is None), "the import never restarted")
        took = time.time() - t0
        mq2 = pub.procs[1]
        self.assertIsNotNone(mq1.poll())
        self.assertTrue(self.wait(lambda: self.size(mq2) > 20000), "no bytes reached the new moq")
        self.assertIs(pub.procs[0], ff)
        self.assertLess(took, kastr_rtsp.HEAL_SWAP_WAIT_S + 4)
        self.assertTrue(any("old moq %d killed" % mq1.pid in m for m in self.logs), self.logs)


if __name__ == "__main__":
    unittest.main()
