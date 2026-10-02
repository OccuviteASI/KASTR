"""0.21.15: no effects warning for a camera that is off on purpose (moq-watch-lite.html, Part 39 item 6).

Run: python -m unittest discover -s tests   (build.py runs it before every build)

The repo has no JS unit runner (the browser console is the page's syntax arbiter), so this test reads the page
source and pins the SHAPE of the fix, which is what a later edit is most likely to undo by accident:

  - camOff(slot) (videoPaused or autoPaused camera, never RTSP) gates loopWanted, so applyFx stops the loop and
    never arms while the camera is off on purpose;
  - both pause sites (control channel, Sources-row button) call stopBlur BEFORE publish.invisible flips, and an
    explicit resume clears the 0.8.6 auto-pause and re-applies via applyFx for effects, stamp and upright alike;
  - the 0.8.6 auto-pause stops the loop before invisible = true and the unmute path re-applies;
  - armFxOnTrack's poll stands down ("armOff") when the camera is paused mid-wait, before the 30 s give-up;
  - the 30 s give-up for an ON camera goes through fxNoTrack, which names the case, treats a stale saved
    deviceId as a note (not a cause), probes for any camera when the saved one is gone, nudges once, and guards
    slots.has || camOff before every toast;
  - non-ASCII glyphs in the new JS strings are escape sequences (\\u2014), never literal characters;
  - window.__fxArms() and the /api/diag slot `fx` block exist for the rig.

KASTR_ROOT (env) points the test at another checkout; the default is the repo root above tests/.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
ROOT = os.environ.get("KASTR_ROOT", HERE)
PAGE = os.path.join(ROOT, "moq-watch-lite.html")
EOL = "\r\n"


def load():
    with open(PAGE, encoding="utf-8", newline="") as f:
        return f.read()


def func_span(text, header):
    """The source of a 2-space-indented function: from its header line to the first `\\r\\n  }\\r\\n` after it."""
    i = text.index(header)
    j = text.index(EOL + "  }" + EOL, i) + len(EOL + "  }")
    return text[i:j]


def code_only(js):
    """Strip comments and string literals (roughly) so brace/paren counting sees only code."""
    lines = [ln for ln in js.split(EOL) if not ln.lstrip().startswith("//")]
    s = EOL.join(lines)
    s = re.sub(r'"(?:\\.|[^"\\\r\n])*"', '""', s)
    s = re.sub(r"'(?:\\.|[^'\\\r\n])*'", "''", s)
    s = re.sub(r"`(?:\\.|[^`\\])*`", "``", s)
    s = re.sub(r"//[^\r\n]*", "", s)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return s


class FxPausedToastTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = load()

    def test_page_is_crlf_only(self):
        s = self.page
        self.assertEqual(s.count("\n") - s.count(EOL), 0, "moq-watch-lite.html must stay CRLF with no bare LF")

    def test_camoff_gates_loopwanted(self):
        s = self.page
        self.assertEqual(s.count("  const camOff = (slot) =>"), 1)
        cam = s[s.index("  const camOff = (slot) =>"):]
        cam = cam[:cam.index(EOL)]
        for must in ('slot.entry.kind === "camera"', "!slot.rtsp", "slot.entry.videoPaused", "slot.autoPaused"):
            self.assertIn(must, cam)
        self.assertEqual(s.count("  const loopWanted = (slot, fx) => !camOff(slot) && (fxActive(fx) || stampOnly(slot) || uprightOnly(slot));"), 1)
        self.assertNotIn("  const loopWanted = (slot, fx) => fxActive(fx) ||", s, "the old ungated loopWanted is back")
        # the gate is consulted by applyFx (stop + never arm), the arm's poll, fxNoTrack, __fxArms and /api/diag
        self.assertGreaterEqual(s.count("camOff("), 7)

    def test_both_pause_sites_stop_the_loop_and_resume_clears_autopause(self):
        s = self.page
        new = ('{ const sl = slots.get(a.id); if (sl && !sl.rtsp && a.kind === "camera") { if (a.videoPaused) stopBlur(sl); '
               'else { sl.autoPaused = false; setTimeout(() => { try { applyFx(sl); } catch {} }, 400); } } }')
        self.assertEqual(s.count(new), 2, "control-channel toggle + Sources-row button")
        self.assertNotIn("if (!a.videoPaused && (a.fx || a.blur))", s, "the 0.15.0 fx/blur-only resume is back")
        for head in ("          a.videoPaused = !!m.set.videoPaused;", "          a.videoPaused = !a.videoPaused;"):
            self.assertEqual(s.count(head), 1, head)
            tail = s[s.index(head):s.index(head) + 2500]
            # stopBlur must run while the raw track is still live: before invisible flips on the library element
            self.assertLess(tail.index("stopBlur(sl)"), tail.index("slot.publish.invisible = a.videoPaused;"), head)

    def test_autopause_stops_loop_before_invisible_and_unmute_reapplies(self):
        s = self.page
        mute = s[s.index("        slot.autoPaused = true;"):]
        mute = mute[:mute.index("announce(); refreshUi();")]
        self.assertLess(mute.index("stopBlur(slot);"), mute.index("slot.publish.invisible = true;"))
        unmute = s[s.index("        slot.autoPaused = false;"):]
        unmute = unmute[:unmute.index("announce(); refreshUi();")]
        self.assertIn("if (!slot.entry.videoPaused) setTimeout(() => { try { applyFx(slot); } catch {} }, 400);", unmute)

    def test_arm_stands_down_when_paused_midwait_and_gives_up_through_fxnotrack(self):
        s = self.page
        arm = func_span(s, "  function armFxOnTrack(slot) {")
        self.assertIn("if (camOff(slot)) {", arm)
        self.assertLess(arm.index("if (camOff(slot)) {"), arm.index("performance.now() - t0 > 30000"),
                        "the pause check must precede the 30 s give-up")
        self.assertIn('["armOff", slot.entry.id]', arm)
        self.assertIn("fxNoTrack(slot).catch(() => {});", arm)
        self.assertNotIn('fxFailOnce(slot, "the camera produced no video track")', s, "the blind 30 s toast is back")
        # the stand-down releases the subscribe seam and the poll timer like the give-up does
        off = arm[arm.index("if (camOff(slot)) {"):arm.index("performance.now() - t0 > 30000")]
        self.assertIn("slot.fxArm();", off)
        self.assertIn("slot.fxArm = null; slot.fxArmT = 0;", off)
        self.assertIn("return;", off)

    def test_fxnotrack_is_hoisted_balanced_and_guarded(self):
        s = self.page
        self.assertEqual(s.count("  async function fxNoTrack(slot) {"), 1)
        fn = func_span(s, "  async function fxNoTrack(slot) {")
        # same module scope as its caller and as fxFailOnce (a function declaration, hoisted)
        self.assertLess(s.index("  async function fxNoTrack(slot) {"), s.index("  function fxFailOnce(slot, why) {"))
        code = code_only(fn)
        self.assertEqual(code.count("{"), code.count("}"), "brace balance in fxNoTrack")
        self.assertEqual(code.count("("), code.count(")"), "paren balance in fxNoTrack")
        self.assertEqual(code.count("["), code.count("]"), "bracket balance in fxNoTrack")
        # removed-or-paused guard after the probe AND before the toast on the signal path
        self.assertGreaterEqual(fn.count("if (!slots.has(slot.entry.id) || camOff(slot)) return;"), 2)
        self.assertLess(fn.rindex("if (!slots.has(slot.entry.id) || camOff(slot)) return;"), fn.index("fxFailOnce(slot, text);"))
        self.assertEqual(fn.count("fxFailOnce(slot, text);"), 1)
        # the one-shot nudge flips the library's enable gate true -> false and re-arms through applyFx
        self.assertEqual(fn.count("slot.fxNudged = true;"), 1)
        nudge = fn[fn.index("slot.fxNudged = true;"):]
        self.assertLess(nudge.index("slot.publish.invisible = true;"), nudge.index("slot.publish.invisible = false;"))
        self.assertIn("applyFx(slot).catch(() => {});", nudge)
        self.assertIn('["noTrack", slot.entry.id', fn)
        # the comment block above the header records the library's real retry count (LIMIT=3, refuses when > LIMIT)
        preamble = s[max(0, s.index("  async function fxNoTrack(slot) {") - 1500):s.index("  async function fxNoTrack(slot) {")]
        self.assertIn("four fast attempts", preamble, "the library makes four getUserMedia attempts, not three")

    def test_fxnotrack_names_each_case_and_treats_stale_as_a_note(self):
        fn = func_span(self.page, "  async function fxNoTrack(slot) {")
        for case in ("camera permission is not granted", "no camera is connected",
                     "the publisher holds the camera but its track never reached the encoder",
                     "another app holds the camera (or its driver failed)", "camera permission was refused",
                     "the camera is gone", "the camera opens but the publisher never took its track", "reason unknown"):
            self.assertEqual(fn.count('"' + case + '"'), 1, case)
        self.assertIn('note = " (the saved camera was not found \\u2014 pick it again under Camera)"', fn)
        self.assertNotIn('why = "the saved camera is gone', fn, "a stale saved id is not a cause: the library opens any camera")
        # the probe asks for ANY camera when the saved id is not in `available` (exact on a stale id would misreport)
        self.assertIn("getUserMedia({ video: want && !stale ? { deviceId: { exact: want } } : true })", fn)
        self.assertIn("const stale = !!want && Array.isArray(avail) && avail.length > 0 && !avail.some((d) => d.deviceId === want);", fn)
        for sig in ("dev?.out?.permission?.peek?.()", "dev?.out?.available?.peek?.()", "dev?.out?.active?.peek?.()"):
            self.assertIn(sig, fn)

    def test_non_ascii_written_as_escapes(self):
        s = self.page
        fn = func_span(s, "  async function fxNoTrack(slot) {")
        self.assertGreaterEqual(fn.count("\\u2014"), 3)
        for blob_name, blob in (("fxNoTrack", fn), ("armFxOnTrack", func_span(s, "  function armFxOnTrack(slot) {"))):
            bad = sorted({ch for ch in blob if ord(ch) > 127})
            self.assertEqual(bad, [], "%s carries literal non-ASCII glyphs %r -- write escapes" % (blob_name, bad))
        for head in ("          a.videoPaused = !!m.set.videoPaused;", "          a.videoPaused = !a.videoPaused;"):
            blk = s[s.index(head):s.index(head) + 1400]
            self.assertEqual(sorted({ch for ch in blk if ord(ch) > 127}), [], head)

    def test_nudge_resets_when_a_track_lands(self):
        s = self.page
        self.assertEqual(s.count("    slot.fxFailed = null; slot.fxNudged = false;"), 1)
        fx = func_span(s, "  async function applyFx(slot) {")
        self.assertIn("slot.fxFailed = null; slot.fxNudged = false;", fx)
        self.assertLess(fx.index("slot.fxFailed = null; slot.fxNudged = false;"), fx.index("startBlurLoop(slot, raw, seg"))

    def test_rig_and_diag_surfaces(self):
        s = self.page
        self.assertEqual(s.count("  window.__fxArms = () => [...slots.values()].filter((s) => s.entry.kind === \"camera\" && !s.rtsp)"), 1)
        arms = s[s.index("  window.__fxArms = "):]
        arms = arms[:arms.index("}));") + 4]
        for field in ("camOff: camOff(s)", "paused: !!s.entry.videoPaused", "autoPaused: !!s.autoPaused", "invisible: !!s.publish?.invisible",
                      "loop: !!s.blur", "armed: !!s.fxArm", "failed: s.fxFailed || null", "nudged: !!s.fxNudged"):
            self.assertIn(field, arms)
        diag = "        fx: { camOff: camOff(s), autoPaused: !!s.autoPaused, invisible: !!s.publish?.invisible, loop: !!s.blur, armed: !!s.fxArm, failed: s.fxFailed || null, nudged: !!s.fxNudged },"
        self.assertEqual(s.count(diag), 1)
        # it sits in the non-RTSP branch of the per-slot publisher block, right under the pause flag it explains
        self.assertEqual(s.count("        muted: s.publish.muted, videoPaused: !!s.entry.videoPaused," + EOL + diag), 1)


if __name__ == "__main__":
    unittest.main()
