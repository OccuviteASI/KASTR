"""0.21.94 -- cleaner background effects (Kenton, 2026-10-28: "Can KASTR read the Windows Studio effects for the blur and
background options? Instead of using the built in person detection? I would like to clean up the detection so it's cleaner.
Do we need to do more training?").

  fx-post   the person mask's clean-up, shared by the camera effects and the presenter cut-out: confident regions joined
            8-way, the best one kept (the chair / door frame / someone behind you dropped), hysteresis in time, the reach
            (MODNet only), small holes filled, the alpha ramp. No training.
  fx-gl     the renderer's guided filter refines the edge against the frame's COLOUR (was luma), radius 12.
  MODNet    input grows 512x288 -> 704x384 -> 896x512 where the device runs it within MAT_BUDGET_MS (timed warm in the page).
  diag      which engine, its input size and ms per frame: /api/diag (publisher slot fxEngine), __fxEngine, launch.log.
  Studio    "Use Windows Studio Effects blur": shown only when the chosen camera's driver offers
            KSPROPERTY_CAMERACONTROL_EXTENDED_BACKGROUNDSEGMENTATION; a helper process sets / restores it through
            IMFExtendedCameraController (user rights). Here: a fake backend, fake COM vtables, the helper process over pipes
            with a fake backend. Nothing here opens, reads or changes a real camera.

fxPostMask runs in the bundled Chromium (headless, a local page on a 9343-9349 port) on Windows; skipped elsewhere."""
import ctypes
import http.server
import io
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_studiofx as sfx   # noqa: E402


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


PAGE = _read("moq-watch-lite.html")
SERVE = _read("kastr_serve.py")


def block(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


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


POST_JS = block(PAGE, "  // ==== fx-post:begin", "  // ==== fx-post:end ====")
GL_JS = block(PAGE, "  // ==== fx-gl:begin", "  // ==== fx-gl:end ====")


# ---- the page -----------------------------------------------------------------------------------------------------------
class PostStrings(unittest.TestCase):
    def test_one_clean_up_for_the_loop_and_the_cut_out(self):
        self.assertEqual(PAGE.count("  // ==== fx-post:begin (0.21.94) ===="), 1)
        self.assertIn("seg: { core: 0.5, lo: 0.35, reach: 0, a0: 0.15, a1: 0.85, hole: 0.02 }", POST_JS)
        self.assertIn("mat: { core: 0.5, lo: 0.15, reach: 0.03, a0: 0.03, a1: 0.97, hole: 0.02 }", POST_JS)
        self.assertIn("function fxPostMask(conf, w, h, P, S, out, stride = 4, off = 3) {", POST_JS)
        self.assertIn("b.postStats = fxPostMask(conf, mw, mh, b.matte ? FX_POST.mat : FX_POST.seg, b.post || (b.post = {}), data);", PAGE)
        self.assertIn("fxPostMask(c.conf, mw, mh, FX_POST.seg, c.post || (c.post = {}), c.img.data);", PAGE)
        self.assertNotIn("function mainSubjectMask(", PAGE)        # 0.8.6's pick lives on inside fxPostMask
        self.assertNotIn("(c - 0.15) * 364)", PAGE)               # the old per-call ramps are gone
        # pure: no DOM, no page state (the lab runs this block as shipped)
        for x in ("document.", "window.", "slots", "b.fx"):
            self.assertNotIn(x, POST_JS)

    def test_the_reach_is_bounded_and_never_seeds_the_next_frame(self):
        self.assertIn("if (bestId && P.reach > 0 && lo < core) {", POST_JS)
        self.assertIn("for (let i = 0; i < qn; i++) prev[i] = bestId && lab[i] === bestId ? 1 : 0;", POST_JS)
        self.assertLess(POST_JS.index("prev[i] = bestId"), POST_JS.index("let grown = 0;"))

    def test_temporal_smoothing_is_unchanged(self):
        self.assertIn("const k = b.matte ? 0.3 : 0.6;", PAGE)
        self.assertIn("for (let i = 0; i < n; i++) p[i] = p[i] * k + cur[i] * (1 - k);", PAGE)
        self.assertIn("for (let i = 0; i < n; i++) c.conf[i] = c.conf[i] * 0.5 + cur[i] * 0.5;", PAGE)


class GlStrings(unittest.TestCase):
    def test_colour_guided_filter(self):
        self.assertEqual(PAGE.count("  // ==== fx-gl:begin ===="), 1)
        self.assertIn("const FX_GUIDE = { color: true, r: 12, eps: 1e-3, half: true };", GL_JS)
        self.assertIn("function createFxGL() {", GL_JS)
        self.assertEqual(PAGE.count("function createFxGL() {"), 1)
        # the 0.21.21 renderer's contract (test_npu_fx) holds
        self.assertIn('if (!gl || !gl.getExtension("EXT_color_buffer_float")) return null;', GL_JS)
        self.assertIn("o = vec4(texture(F, f).rgb * w, w);", GL_JS)
        self.assertIn("vec3 bg = bw.a > 0.002 ? bw.rgb / bw.a : c;", GL_JS)


class ModnetSizes(unittest.TestCase):
    def test_sizes_budget_and_the_ladder(self):
        self.assertIn("const MAT_SIZES = [[512, 288], [704, 384], [896, 512]];", PAGE)
        self.assertIn("const MAT_BUDGET_MS = 34;", PAGE)
        self.assertIn('const order = proc === "npu" ? ["npu"] : proc === "gpu" ? ["gpu"] : proc === "standard" ? [] : ["npu", "gpu"];', PAGE)
        self.assertIn("m.warmMs = Math.round(performance.now() - t1);", PAGE)
        self.assertIn('const key = b.mat.dev + "|" + b.mat.mw + "x" + b.mat.mh, m = matSess[key];', PAGE)
        self.assertNotIn('(b.mat.portrait ? "288x512" : "512x288")', PAGE)

    def test_grow_keeps_only_a_size_within_budget(self):
        g = block(PAGE, "  async function matGrow(b) {", "  function matShrink(b) {")
        self.assertIn("if (!(m.warmMs <= MAT_BUDGET_MS)) {", g)
        self.assertIn("matSlow[key] = m.warmMs || -1; delete matSess[key];", g)
        self.assertIn("m.sess.release?.()", g)
        self.assertIn("if (!b.alive || b.mat !== mat) return;", g)
        self.assertIn("Number.isInteger(window.__fxMatSize)", g)   # the rig pins a size
        # "Fastest that fits" (test_release_0_21_94_fastest_fits): under load it re-decides -- the other device or a step down
        self.assertIn("if (b.matMs > MAT_BUDGET_MS * 1.6) { if (++b.matOver > 25) matUnderLoad(b); } else b.matOver = 0;", PAGE)
        self.assertIn("if (c?.move) matMove(b, c.move, c.idx); else if (c?.shrink) matShrink(b);", PAGE)


class EngineDiag(unittest.TestCase):
    def test_engine_in_diag_and_launch_log(self):
        info = block(PAGE, "  function fxEngineInfo(b) {", "  function fxEngineNote(b, why) {")
        for x in ('engine: "modnet", device: b.mat.dev, input: b.mat.mw + "x" + b.mat.mh, ms: Math.round(b.matMs || 0)',
                  'engine: b.seg ? "mediapipe" : "loading"', "ms: Math.round(b.segMs || 0)", "webnn: !!navigator.ml",
                  "post: b.postStats || null", "backgroundBlur"):
            self.assertIn(x, info)
        self.assertIn('        fxEngine: fxEngineInfo(s.blur), fxStudio: !!window.__studioFxOn?.(fxSlotTrack(s)?.label || ""),', PAGE)
        self.assertIn("failed: { ...matFailed }, info: fxEngineInfo(b) };", PAGE)
        note = block(PAGE, "  function fxEngineNote(b, why) {", "  window.__fxEngine = () => {")
        self.assertIn("if (IS_WEB2 || !b || b.preview) return;", note)
        self.assertIn('nativePost("/api/rtsp/note", { text: "page: camera effects: "', note)
        self.assertIn("b.segMs = b.segMs ? b.segMs * 0.8 + ms * 0.2 : ms;", PAGE)
        self.assertIn("b.preview = !!slot.preview;", PAGE)

    def test_server_diag_carries_studio_state_masked(self):
        d = block(SERVE, "        def _diag_get(self):", "        def _update_check(self):")
        self.assertIn('out["_studiofx"] = studiofx_state()', d)
        self.assertIn("kastr_secret.mask(json.dumps(out", d)


class StudioPage(unittest.TestCase):
    def test_switch_is_a_toggle_hidden_until_offered(self):
        self.assertIn('<div class="sw" id="fxStudioRow" hidden><label class="switch"', PAGE)
        self.assertIn('<input type="checkbox" id="fxStudio"><i></i></label><span>Use Windows Studio Effects blur', PAGE)
        paint = block(PAGE, "  function studioFxPaint() {", "\n  }\n")
        self.assertIn("if (IS_WEB) { row.hidden = true; return; }", paint)
        self.assertIn("row.hidden = !c;", paint)

    def test_bag_carries_the_choice(self):
        self.assertIn("studio: !!s.studio,", PAGE)
        self.assertIn("studio: !!fx.studio,", PAGE)
        self.assertIn('mirror: !!camFx.mirror, studio: !!camFx.studio, proc: camFx.proc || "auto" });', PAGE)
        self.assertEqual(PAGE.count('             proc: "auto" };'), 2)

    def test_kastr_blur_stands_down_only_for_blur_on_a_held_camera(self):
        self.assertIn('const fxStudioOn = (fx, track) => !!fx?.studio && fx.bg?.mode === "blur"', PAGE)
        self.assertIn('const fxStudioEff = (fx, track) => (fxStudioOn(fx, track) ? { ...fx, bg: { mode: "none", url: "" } } : fx);', PAGE)
        self.assertIn("const want = () => fxStudioEff(slot.entry.fx ||", PAGE)
        self.assertIn("fx = fxStudioEff(fx, raw);", PAGE)
        self.assertIn("fx = fxStudioEff(fx, pv.raw);", PAGE)

    def test_sync_holds_one_camera_and_lets_go_of_the_rest(self):
        s = block(PAGE, "  function studioFxSync() {", "  window.__studioFxOn = ")
        self.assertIn("if (IS_WEB || (!camFx?.studio && !studioFx.held.size)) return studioFx.chain;", s)
        self.assertIn('const want = !!camFx.studio && camFx.bg?.mode === "blur";', s)
        self.assertIn("await studioFxPost(id, false); studioFx.held.delete(id);", s)
        self.assertIn("if (changed) { pushCamFx();", s)
        self.assertIn("studioFxSync();   // 0.21.94: the driver blur follows the bag", PAGE)
        self.assertIn("studioFxSync(); studioFxPaint();   // 0.21.94: the held Studio Effects blur follows the chosen camera", PAGE)

    def test_label_match(self):
        m = block(PAGE, "  const studioMatch = (label) => {", "  function studioCamLabel() {")
        self.assertIn('low.includes("(" + String(c.vidpid).toLowerCase() + ")")', m)
        self.assertIn('L === c.name || L.startsWith(c.name + " (")', m)


class StudioServer(unittest.TestCase):
    def test_routes_are_local_only(self):
        for verb in ("POST", "GET"):
            i = SERVE.index('            if path == "/api/camfx/studio":', SERVE.index("def do_%s" % verb) if ("def do_%s" % verb) in SERVE else 0)
            body = SERVE[i:i + 900]
            self.assertIn("if not self._local():", body[:300])
            self.assertIn('return self._deny("camera settings")', body[:400])
        self.assertEqual(SERVE.count('if path == "/api/camfx/studio":'), 2)

    def test_lazy_and_closed_at_exit(self):
        f = block(SERVE, "def studiofx():", "def studiofx_state():")
        self.assertIn("import kastr_studiofx", f)
        self.assertIn("atexit.register(fx.close)", f)

    def test_helper_entry_and_build(self):
        k = _read("kastr.py")
        self.assertIn('if sys.argv[1:2] == ["--studiofx-helper"]:', k)
        self.assertLess(k.index('if sys.argv[1:2] == ["--studiofx-helper"]:'), k.index("def main():") + 200)
        self.assertIn('"--hidden-import", "kastr_studiofx",', _read("build.py"))


# ---- kastr_studiofx -----------------------------------------------------------------------------------------------------
CAMS = [
    {"name": "Integrated Webcam", "link": r"\\?\display#int3480#4&1f2a&0&uid13424#{e5323777-f976-4f5b-9b55-b94699c46e44}\camera",
     "caps": sfx.FLAG_BLUR | sfx.FLAG_MASK | sfx.FLAG_SHALLOWFOCUS, "flags": sfx.FLAG_MASK},
    {"name": "HD Webcam", "link": r"\\?\usb#vid_0C45&pid_6713&mi_00#7&2a&0&0000#{e5323777-f976-4f5b-9b55-b94699c46e44}\global",
     "caps": 0, "flags": 0},
]


class StudioPure(unittest.TestCase):
    def test_flags(self):
        self.assertEqual(sfx.blur_flags(sfx.FLAG_MASK, 7, True), sfx.FLAG_MASK | sfx.FLAG_BLUR)       # MASK kept
        self.assertEqual(sfx.blur_flags(sfx.FLAG_MASK | sfx.FLAG_BLUR, 7, False), sfx.FLAG_MASK)
        self.assertEqual(sfx.blur_flags(0, 7, True, shallow=True), sfx.FLAG_BLUR | sfx.FLAG_SHALLOWFOCUS)
        self.assertEqual(sfx.blur_flags(0, sfx.FLAG_BLUR, True, shallow=True), sfx.FLAG_BLUR)          # not offered: not set
        self.assertEqual(sfx.caps_dict(3), {"blur": True, "mask": True, "shallow": False})

    def test_ids(self):
        self.assertEqual(sfx.vid_pid(CAMS[1]["link"]), "0c45:6713")
        self.assertEqual(sfx.vid_pid(CAMS[0]["link"]), "")
        self.assertEqual(sfx.cam_id(CAMS[0]["link"]), sfx.cam_id(CAMS[0]["link"].upper()))
        self.assertEqual(len(sfx.cam_id("x")), 12)
        self.assertNotIn("uid13424", sfx.cam_id(CAMS[0]["link"]))

    def test_vtable_slots_match_the_sdk_headers(self):
        # mfobjects.h / mfidl.h: IUnknown 0-2; IMFAttributes GetAllocatedString 13, SetGUID 24 (32 methods to CopyAllItems);
        # IMFActivate ActivateObject 33, ShutdownObject 34; IMFMediaSource Shutdown 12; IMFGetService::GetService 3;
        # IMFExtendedCameraController::GetExtendedCameraControl 3; IMFExtendedCameraControl GetCapabilities 3, SetFlags 4,
        # GetFlags 5, LockPayload 6, UnlockPayload 7, CommitSettings 8
        self.assertEqual((sfx.V_QI, sfx.V_RELEASE, sfx.V_ATTR_GETALLOCATEDSTRING, sfx.V_ATTR_SETGUID), (0, 2, 13, 24))
        self.assertEqual((sfx.V_ACT_ACTIVATEOBJECT, sfx.V_ACT_SHUTDOWNOBJECT, sfx.V_SRC_SHUTDOWN), (33, 34, 12))
        self.assertEqual((sfx.V_GS_GETSERVICE, sfx.V_CTL_GETCONTROL), (3, 3))
        self.assertEqual((sfx.V_CC_GETCAPABILITIES, sfx.V_CC_SETFLAGS, sfx.V_CC_GETFLAGS, sfx.V_CC_COMMIT), (3, 4, 5, 8))
        self.assertEqual(sfx.PROP_BACKGROUNDSEGMENTATION, 41)
        self.assertEqual(sfx.FILTER_SCOPE, 0xFFFFFFFF)


class StudioHelper(unittest.TestCase):
    def setUp(self):
        self.be = sfx.FakeBackend(CAMS)
        self.h = sfx.Helper(self.be, ro=False)
        self.ids = [sfx.cam_id(c["link"]) for c in CAMS]

    def test_list_reads_without_writing(self):
        rows = self.h.list()
        self.assertEqual([r["name"] for r in rows], ["Integrated Webcam", "HD Webcam"])
        self.assertTrue(rows[0]["blur"] and rows[0]["mask"] and rows[0]["shallow"])
        self.assertFalse(rows[0]["on"])
        self.assertFalse(rows[1]["blur"])
        self.assertIn("why", rows[1])
        self.assertEqual(rows[1]["vidpid"], "0c45:6713")
        self.assertEqual(self.be.writes, [])
        for r in rows:
            self.assertNotIn("link", r)            # the raw device path never leaves the helper

    def test_set_holds_then_restores_what_it_found(self):
        r = self.h.set(self.ids[0], True)
        self.assertTrue(r["ok"] and r["on"])
        self.assertEqual(self.be.cams[0]["flags"], sfx.FLAG_MASK | sfx.FLAG_BLUR)
        self.assertIn(self.ids[0], self.h.held)
        self.assertTrue(self.h.list()[0]["held"])
        r = self.h.set(self.ids[0], False)
        self.assertTrue(r["ok"] and not r["on"] and r["changed"])
        self.assertEqual(self.be.cams[0]["flags"], sfx.FLAG_MASK)
        self.assertEqual(self.h.held, {})

    def test_refusals(self):
        self.assertFalse(self.h.set(self.ids[1], True)["ok"])        # no blur on that camera
        self.assertFalse(self.h.set("nope", True)["ok"])
        self.assertEqual(self.be.writes, [])
        ro = sfx.Helper(sfx.FakeBackend(CAMS), ro=True)
        self.assertIn("read-only", ro.set(self.ids[0], True)["why"])
        with mock.patch.dict(os.environ, {"KASTR_STUDIOFX_READONLY": "1"}):
            self.assertTrue(sfx.Helper(sfx.FakeBackend(CAMS)).ro)

    def test_restore_all_and_handle(self):
        self.h.handle({"op": "set", "id": self.ids[0], "on": True})
        self.assertEqual(self.h.handle({"op": "restore"}), {"ok": True})
        self.assertEqual(self.be.cams[0]["flags"], sfx.FLAG_MASK)
        self.assertEqual(self.h.handle({"op": "x"})["ok"], False)

    def test_helper_main_restores_at_eof(self):
        fin = io.BytesIO(b'{"op":"list"}\n{"op":"set","id":"%s","on":true}\n' % self.ids[0].encode())
        fout = io.BytesIO()
        with mock.patch.dict(os.environ, {"KASTR_STUDIOFX_READONLY": ""}):
            self.assertEqual(sfx.helper_main(self.be, fin, fout), 0)
        lines = [json.loads(x) for x in fout.getvalue().decode().splitlines()]
        self.assertEqual(lines[0]["hello"], 1)
        self.assertEqual(len(lines[1]["cams"]), 2)
        self.assertTrue(lines[2]["on"])
        self.assertEqual(self.be.cams[0]["flags"], sfx.FLAG_MASK)        # EOF: put back
        self.assertEqual(self.be.writes[-1], (CAMS[0]["link"], sfx.FLAG_MASK))

    def test_studiofx_in_process(self):
        fx = sfx.StudioFx(local=self.h)
        c = fx.cameras()
        self.assertTrue(c["supported"])
        self.assertEqual(len(c["cams"]), 2)
        self.assertTrue(fx.set(self.ids[0], True)["ok"])
        self.assertEqual(fx.held, {self.ids[0]})
        fx.close()
        self.assertEqual(self.be.cams[0]["flags"], sfx.FLAG_MASK)


HELPER_SRC = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import kastr_studiofx as k
be = k.FakeBackend(json.loads(sys.argv[2]))
rc = k.helper_main(be)
with open(sys.argv[3], "w") as f:
    json.dump({"rc": rc, "writes": be.writes, "flags": [c["flags"] for c in be.cams]}, f)
'''


class StudioProcess(unittest.TestCase):
    """The real pipe plumbing: a helper process (a fake backend) started, asked, and closed -- it restores at EOF."""

    def test_set_then_close_restores(self):
        d = tempfile.mkdtemp()
        try:
            res = os.path.join(d, "res.json")
            argv = [sys.executable, "-c", HELPER_SRC, HERE, json.dumps(CAMS), res]
            with mock.patch.object(sfx.StudioFx, "supported", staticmethod(lambda: True)), \
                    mock.patch.dict(os.environ, {"KASTR_STUDIOFX_READONLY": ""}):
                fx = sfx.StudioFx(argv=argv)
                c = fx.cameras()
                self.assertTrue(c["ok"], c)
                self.assertIsNone(fx.proc)                  # nothing held: no idle helper
                cid = c["cams"][0]["id"]
                self.assertTrue(fx.set(cid, True)["ok"])
                self.assertIsNotNone(fx.proc)               # held: the helper stays
                fx.close()
            with open(res) as f:
                out = json.load(f)
            self.assertEqual(out["rc"], 0)
            self.assertEqual(out["flags"][0], sfx.FLAG_MASK)                      # put back at EOF
            self.assertEqual([w[1] for w in out["writes"]], [sfx.FLAG_MASK | sfx.FLAG_BLUR, sfx.FLAG_MASK])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_helper_that_dies_is_not_restarted_forever(self):
        argv = [sys.executable, "-c", "import sys; sys.exit(3)"]
        with mock.patch.object(sfx.StudioFx, "supported", staticmethod(lambda: True)):
            fx = sfx.StudioFx(argv=argv)
            for _ in range(4):
                self.assertFalse(fx.cameras(fresh=True)["ok"])
            self.assertEqual(fx.deaths, 2)


class FakeCom(unittest.TestCase):
    """ExtControl over hand-built COM objects (ctypes vtables): the right slot, the right arguments, released at the end."""

    def test_ext_control_walk(self):
        P = ctypes.c_void_p
        FN = sfx._FN
        log, keep = [], []

        def obj(slots):
            n = max(slots) + 1
            vt = (P * n)()
            for i, f in slots.items():
                vt[i] = ctypes.cast(f, P)
            o = (P * 1)(ctypes.cast(vt, P))
            keep.extend([vt, o] + list(slots.values()))
            return ctypes.addressof(o)

        rel = lambda name: FN(ctypes.c_ulong, P)(lambda this: log.append(("release", name)) or 0)
        state = {"flags": sfx.FLAG_MASK}
        cc = obj({2: rel("cc"),
                  3: FN(ctypes.c_ulonglong, P)(lambda this: 7),
                  4: FN(sfx.HRESULT, P, ctypes.c_ulonglong)(lambda this, f: log.append(("set", f)) or state.update(flags=f) or 0),
                  5: FN(ctypes.c_ulonglong, P)(lambda this: state["flags"]),
                  8: FN(sfx.HRESULT, P)(lambda this: log.append(("commit",)) or 0)})

        def get_control(this, scope, prop, ppv):
            log.append(("control", scope, prop))
            ctypes.cast(ppv, ctypes.POINTER(P))[0] = cc
            return 0
        ctl = obj({2: rel("ctl"), 3: FN(sfx.HRESULT, P, ctypes.c_ulong, ctypes.c_ulong, P)(get_control)})

        def get_service(this, svc, riid, ppv):
            g = ctypes.cast(riid, ctypes.POINTER(sfx.GUID))[0]
            log.append(("service", bytes(g) == bytes(sfx.IID_IMFExtendedCameraController)))
            ctypes.cast(ppv, ctypes.POINTER(P))[0] = ctl
            return 0
        gs = obj({2: rel("gs"), 3: FN(sfx.HRESULT, P, P, P, P)(get_service)})

        def qi(this, riid, ppv):
            g = ctypes.cast(riid, ctypes.POINTER(sfx.GUID))[0]
            if bytes(g) != bytes(sfx.IID_IMFGetService):
                return -2147467262   # E_NOINTERFACE
            ctypes.cast(ppv, ctypes.POINTER(P))[0] = gs
            return 0
        src = obj({0: FN(sfx.HRESULT, P, P, P)(qi), 2: rel("src")})

        c = sfx.ExtControl(src)
        self.assertEqual(log[:3], [("service", True), ("release", "gs"), ("control", 0xFFFFFFFF, 41)])
        self.assertEqual(c.caps(), 7)
        self.assertEqual(c.flags(), sfx.FLAG_MASK)
        c.set(sfx.FLAG_MASK | sfx.FLAG_BLUR)
        self.assertEqual(log[-2:], [("set", 3), ("commit",)])
        self.assertEqual(c.flags(), 3)
        c.close()
        self.assertEqual(log[-2:], [("release", "cc"), ("release", "ctl")])

    def test_hresult_failure_raises(self):
        P = ctypes.c_void_p
        f = sfx._FN(sfx.HRESULT, P)(lambda this: -2147024891)   # E_ACCESSDENIED
        vt = (P * 4)(); vt[3] = ctypes.cast(f, P)
        o = (P * 1)(ctypes.cast(vt, P))
        with self.assertRaises(sfx.ComError) as cm:
            sfx.hcall("x", ctypes.addressof(o), 3, [])
        self.assertEqual(cm.exception.hr, 0x80070005)


# ---- fxPostMask in Chromium ---------------------------------------------------------------------------------------------
POST_CASES = r"""
const W = 320, H = 180;
const grid = (f) => { const c = new Float32Array(W * H); for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) c[y * W + x] = f(x, y); return c; };
const run = (conf, P, S) => { const out = new Uint8ClampedArray(W * H * 4); const st = fxPostMask(conf, W, H, P, S || {}, out); return { a: (x, y) => out[(y * W + x) * 4 + 3], st }; };
const body = (x, y) => x >= 120 && x < 200 && y >= 40;
const R = {};
{ // a stray blob (a chair) dropped, the person kept
  const r = run(grid((x, y) => body(x, y) ? 0.95 : (x >= 10 && x < 40 && y >= 10 && y < 40) ? 0.9 : 0.02), FX_POST.seg);
  R.stray = { person: r.a(160, 100), chair: r.a(25, 25), dropped: r.st.dropped, regions: r.st.regions };
}
{ // a hole inside the person (a dark shirt patch) filled; a big gap is not a hole
  const r = run(grid((x, y) => body(x, y) && !(x >= 150 && x < 156 && y >= 90 && y < 96) ? 0.95 : 0.02), FX_POST.seg);
  R.hole = { inside: r.a(152, 92), holes: r.st.holes };
}
{ // an arm that touches the body only corner-to-corner (8-way) stays the person
  const r = run(grid((x, y) => body(x, y) || (x >= 100 && x < 120 && y >= 20 && y < 40) ? 0.95 : 0.02), FX_POST.seg);
  R.diag = { arm: r.a(110, 30), regions: r.st.regions };
}
{ // the reach: a half-sure hand next to the body -- MODNet keeps it, MediaPipe (reach 0) does not past the rim
  const f = (x, y) => body(x, y) ? 0.95 : (x >= 200 && x < 206 && y >= 60 && y < 70) ? 0.4 : 0.0;
  const m = run(grid(f), FX_POST.mat), s = run(grid(f), FX_POST.seg);
  R.reach = { mat: m.a(204, 65), seg: s.a(204, 65), segRim: s.a(200, 65), grown: m.st.grown };
}
{ // hysteresis: 0.45 holds where the person was last frame, and is nothing on its own
  const S = {};
  run(grid((x, y) => body(x, y) ? 0.95 : 0.02), FX_POST.seg, S);
  const held = run(grid((x, y) => body(x, y) ? (x < 130 ? 0.45 : 0.95) : 0.02), FX_POST.seg, S);
  const fresh = run(grid((x, y) => body(x, y) ? (x < 130 ? 0.45 : 0.95) : 0.02), FX_POST.seg, {});
  R.hyst = { held: held.a(124, 100), fresh: fresh.a(124, 100) };
}
{ // nobody: nothing kept
  const r = run(grid(() => 0.3), FX_POST.seg);
  R.empty = { a: r.a(160, 90), area: r.st.area };
}
{ // a bigger mask is read on a coarse copy (cells <= 320 x 180) and still drops the stray
  const w = 640, h = 360, c = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) c[y * w + x] = (x >= 240 && x < 400 && y >= 80) ? 0.95 : (x < 40 && y < 40) ? 0.9 : 0;
  const out = new Uint8ClampedArray(w * h * 4), st = fxPostMask(c, w, h, FX_POST.mat, {}, out);
  R.big = { cells: st.cells, person: out[(200 * w + 320) * 4 + 3], stray: out[(20 * w + 20) * 4 + 3] };
}
R;
"""


@unittest.skipUnless(sys.platform == "win32" and _chrome(), "the bundled Chromium (Windows)")
class PostInChromium(unittest.TestCase):
    """fxPostMask exactly as shipped, run in headless Chromium against hand-made confidence grids."""

    @classmethod
    def setUpClass(cls):
        page = ("<!doctype html><meta charset=utf-8><script>(function(){\n" + POST_JS + "\n"
                "let R; try { R = (() => {" + POST_CASES.replace("\nR;\n", "\nreturn R;\n") + "})(); } catch (e) { R = { error: String(e) }; }\n"
                "fetch('/r', { method: 'POST', body: JSON.stringify(R) });\n})();</script>").encode()
        got, done = [], threading.Event()

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)

            def do_POST(self):
                got.append(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                self.send_response(204)
                self.end_headers()
                done.set()

        srv = None
        for port in range(9343, 9350):   # the effects lab's own ports
            try:
                srv = socketserver.TCPServer(("127.0.0.1", port), H)
                break
            except OSError:
                continue
        if srv is None:
            raise unittest.SkipTest("no free lab port")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        prof = tempfile.mkdtemp()
        proc = subprocess.Popen([_chrome(), "--headless=new", "--user-data-dir=" + prof, "--no-first-run", "--disable-extensions",
                                 "--mute-audio", "http://127.0.0.1:%d/" % srv.server_address[1]],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            done.wait(60)
        finally:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
            srv.shutdown()
            srv.server_close()
            shutil.rmtree(prof, ignore_errors=True)
        if not got:
            raise unittest.SkipTest("Chromium did not answer")
        cls.R = json.loads(got[0])

    def test_no_error(self):
        self.assertNotIn("error", self.R)

    def test_stray_dropped(self):
        r = self.R["stray"]
        self.assertEqual(r["person"], 255)
        self.assertEqual(r["chair"], 0)
        self.assertEqual((r["regions"], r["dropped"]), (2, 1))

    def test_hole_filled(self):
        self.assertEqual(self.R["hole"], {"inside": 255, "holes": 1})

    def test_corner_joined_arm_kept(self):
        self.assertEqual(self.R["diag"]["regions"], 1)
        self.assertEqual(self.R["diag"]["arm"], 255)

    def test_reach_only_for_modnet(self):
        r = self.R["reach"]
        self.assertGreater(r["mat"], 90)          # (0.4 - 0.03) / 0.94 of 255
        self.assertEqual(r["seg"], 0)
        self.assertGreater(r["grown"], 0)

    def test_hysteresis(self):
        self.assertGreater(self.R["hyst"]["held"], 100)
        self.assertGreater(self.R["hyst"]["held"], self.R["hyst"]["fresh"])

    def test_nobody(self):
        self.assertEqual(self.R["empty"], {"a": 0, "area": 0})

    def test_big_mask(self):
        big = self.R["big"]
        self.assertEqual((big["cells"], big["stray"]), ("320x180", 0))
        self.assertGreaterEqual(big["person"], 245)        # MODNet's ramp: 0.95 -> (0.95 - 0.03) / 0.94


if __name__ == "__main__":
    unittest.main()
