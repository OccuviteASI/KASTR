"""0.21.94 -- Auto = "Fastest that fits" (Kenton, 2026-10-29).

With both the NPU and the GPU available for MODNet, the camera starts on the first that runs, then both are timed warm
(matReach: up MAT_SIZES while a size stays within MAT_BUDGET_MS) and the device that reaches the larger input takes over;
the same size goes to the NPU (less power). It re-decides only under load (over 1.6x the budget for 25 mattes in a row),
never within MAT_HOLD_MS of the last change, and never back to a device it left. /api/diag fxEngine.pick says why.

The behaviour runs the page's MODNet block exactly as shipped in the bundled Chromium (headless, a local page on a
9343-9349 port) against a fake onnxruntime whose sessions sleep a set time per device and size -- no WebNN, no model,
no camera. Windows only; the string checks run everywhere."""
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tests"))
from test_release_0_21_94_fx import PAGE, block, _chrome   # noqa: E402

MAT_JS = block(PAGE, "  const MAT_MIN_MS = 40;", "  window.__fxEngine = () => {")


class Strings(unittest.TestCase):
    def test_auto_races_two_devices_forced_ones_grow(self):
        self.assertIn('const order = proc === "npu" ? ["npu"] : proc === "gpu" ? ["gpu"] : proc === "standard" ? [] : ["npu", "gpu"];', MAT_JS)
        self.assertIn("if (order.length > 1) matRace(b, gen); else matGrow(b);", MAT_JS)
        self.assertIn("const MAT_HOLD_MS = 30000;", MAT_JS)
        self.assertIn('for (const dev of ["npu", "gpu"]) {', block(MAT_JS, "  async function matRace(b, gen) {", "  function matDrop(dev) {"))

    def test_tie_goes_to_the_npu(self):
        c = block(MAT_JS, "  function matChoose(reach, portrait) {", "  async function matRace(b, gen) {")
        self.assertIn('if (n.idx >= g.idx) {', c)
        self.assertIn('"both reach " + nm(n.idx) + " within " + MAT_BUDGET_MS + " ms; the NPU uses less power"', c)

    def test_under_load_only_with_hold_and_never_back(self):
        self.assertIn("if (b.matMs > MAT_BUDGET_MS * 1.6) { if (++b.matOver > 25) matUnderLoad(b); } else b.matOver = 0;", MAT_JS)
        u = block(MAT_JS, "  function matUnderLoad(b) {", "  async function matMove(b, dev, idx) {")
        self.assertIn("performance.now() < (b.matHoldUntil || 0)", u)
        mv = block(MAT_JS, "  async function matMove(b, dev, idx) {", "  // 0.21.94: which person-mask engine")
        self.assertIn("b.matLeft = { ...(b.matLeft || {}), [got ? from.dev : dev]: true };", mv)
        self.assertIn("b.matHoldUntil = performance.now() + matHoldMs();", mv)
        self.assertIn("b.matHoldUntil = performance.now() + matHoldMs();", block(MAT_JS, "  function matShrink(b) {", "  // ---- 0.21.94 \"Fastest that fits\""))

    def test_timing_holds_this_loops_mattes(self):
        self.assertIn("if (b.matBusy || b.matHush || now - b.lastSegAt < MAT_MIN_MS) return;", MAT_JS)
        t = block(MAT_JS, "  async function matTime(b, m) {", "  async function matReach(b, dev, portrait) {")
        self.assertIn("for (let k = 0; k < 3; k++)", t)
        self.assertIn("} finally { b.matHush--; }", t)

    def test_diag_says_why(self):
        info = block(MAT_JS, "  function fxEngineInfo(b) {", "  function fxEngineNote(b, why) {")
        self.assertIn("const base = { webnn: !!navigator.ml, pick, post: b.postStats || null,", info)
        self.assertIn('fxEngineNote(b, "picked: " + pick.why);', MAT_JS)


FAKE_ORT = b"""
export const env = { wasm: {}, logLevel: "error" };
export class Tensor { constructor(type, data, dims) { this.type = type; this.data = data; this.dims = dims; } }
export const InferenceSession = { async create(url, o) {
  const dev = o.executionProviders[0].deviceType, d = o.freeDimensionOverrides, key = dev + "|" + d.width + "x" + d.height;
  const sim = globalThis.__sim;
  if (!(key in sim.ms)) throw new Error("no " + key);
  sim.built.push(key);
  const n = d.width * d.height;
  return { inputNames: ["input"], outputNames: ["output"],
    async run() { await new Promise((r) => setTimeout(r, sim.ms[key] * (sim.mul[dev] || 1))); return { output: { data: new Float32Array(n) } }; },
    release() { sim.released.push(key); } };
} };
"""

CASES = r"""
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
Object.defineProperty(navigator, "ml", { value: {}, configurable: true });
const IS_WEB2 = false, slots = new Map(), segCache = {}, segInfo = {}, NOTES = [];
function nativePost(u, o) { NOTES.push(o.text); }
async function ensureSegmenter() { return null; }
function fxNeedsMask() { return true; }
function make() {
__MAT_JS__
  return { pickMatte, matTick, matChoose, matLoadChoice, fxEngineInfo, matSess, matSlow };
}
async function start(ms, hold) {
  globalThis.__sim = { ms, mul: {}, built: [], released: [] };
  window.__fxMatHoldMs = hold;
  const F = make(), cv = document.createElement("canvas");
  cv.width = 640; cv.height = 360;
  const b = { alive: true, proc: "auto", matGen: 0, video: { videoWidth: 640, videoHeight: 360 }, fx: {}, lastSegAt: 0, segN: 0 };
  await F.pickMatte(b);
  const startDev = b.mat ? b.mat.dev : null;
  for (let k = 0; k < 800 && !(b.matPick && b.matPick.dev); k++) await sleep(10);
  return { F, b, cv, startDev };
}
let T = 0;
async function drive(s, n, stop) {
  for (let k = 0; k < n && !(stop && stop()); k++) {
    T += 1000;
    s.F.matTick(s.b, s.cv, 640, 360, performance.now() + T, () => {});
    await sleep(1);
    for (let j = 0; j < 2000 && (s.b.matBusy || s.b.matMoving || s.b.matHush); j++) await sleep(2);
  }
}
const at = (b) => (b.mat ? b.mat.dev + " " + b.mat.mw + "x" + b.mat.mh : "none");
const R = {};
(async () => {
  try {
    // pure
    const F0 = make();
    R.load = {
      bigDown: F0.matLoadChoice({ dev: "gpu", idx: 2 }, { npu: { idx: 0 } }, {}),
      move: F0.matLoadChoice({ dev: "gpu", idx: 1 }, { npu: { idx: 0 } }, {}),
      left: F0.matLoadChoice({ dev: "npu", idx: 0 }, { gpu: { idx: 1 } }, { gpu: true }),
      floor: F0.matLoadChoice({ dev: "gpu", idx: 0 }, null, {}),
      forced: F0.matLoadChoice({ dev: "gpu", idx: 1 }, null, {}),
      otherNone: F0.matLoadChoice({ dev: "gpu", idx: 1 }, { npu: { idx: -1 } }, {}),
    };
    const r = (idx, ms) => ({ idx, floor: 0, ms });
    R.choose = {
      tie: F0.matChoose({ npu: r(1, {}), gpu: r(1, {}) }, false),
      gpu: F0.matChoose({ npu: r(0, {}), gpu: r(2, {}) }, false),
      npu: F0.matChoose({ npu: r(2, {}), gpu: r(1, {}) }, false),
      gpuNpuNone: F0.matChoose({ npu: r(-1, { "512x288": 62 }), gpu: r(0, {}) }, false),
      neither: F0.matChoose({ npu: r(-1, { "512x288": 62 }), gpu: r(-1, { "512x288": 45 }) }, false),
      neitherTie: F0.matChoose({ npu: r(-1, { "512x288": 50 }), gpu: r(-1, { "512x288": 50 }) }, false),
      onlyGpu: F0.matChoose({ npu: null, gpu: r(1, {}) }, false),
      none: F0.matChoose({ npu: null, gpu: null }, false),
      portrait: F0.matChoose({ npu: r(0, {}), gpu: r(1, {}) }, true),
    };
    // the race, as shipped, against the fake runtime
    let s = await start({ "npu|512x288": 24, "npu|704x384": 60, "gpu|512x288": 6, "gpu|704x384": 16, "gpu|896x512": 55 }, 0);
    await sleep(1800);
    R.gpuWins = { start: s.startDev, at: at(s.b), pick: s.F.fxEngineInfo(s.b).pick, released: __sim.released.slice(), notes: NOTES.slice() };
    // under load: the GPU turns slow -> the NPU at the size it reached; then the NPU turns slow too -> stays (never back)
    __sim.mul.gpu = 6;
    await drive(s, 120, () => s.b.mat.dev === "npu");
    R.moved = { at: at(s.b), left: Object.keys(s.b.matLeft || {}), moves: (s.b.matPick.moves || []).slice(), why: s.b.matPick.why };
    __sim.mul.gpu = 1; __sim.mul.npu = 5;
    await drive(s, 60);
    R.stayed = { at: at(s.b), moves: s.b.matPick.moves.length };
    s.b.alive = false;

    s = await start({ "npu|512x288": 10, "npu|704x384": 18, "npu|896x512": 70, "gpu|512x288": 5, "gpu|704x384": 10, "gpu|896x512": 60 }, 0);
    R.tie = { at: at(s.b), why: s.b.matPick.why };
    s.b.alive = false;

    s = await start({ "npu|512x288": 8, "npu|704x384": 12, "npu|896x512": 18, "gpu|512x288": 10, "gpu|704x384": 55 }, 0);
    R.npuWins = { at: at(s.b), why: s.b.matPick.why };
    s.b.alive = false;

    s = await start({ "gpu|512x288": 6, "gpu|704x384": 14, "gpu|896x512": 60 }, 0);
    R.onlyGpu = { start: s.startDev, at: at(s.b), why: s.b.matPick.why };
    s.b.alive = false;

    s = await start({ "npu|512x288": 70, "gpu|512x288": 45 }, 0);
    R.neither = { at: at(s.b), why: s.b.matPick.why };
    s.b.alive = false;

    // the hold: a busy GPU inside the hold time changes nothing
    s = await start({ "npu|512x288": 24, "npu|704x384": 60, "gpu|512x288": 6, "gpu|704x384": 16, "gpu|896x512": 55 }, 60000);
    __sim.mul.gpu = 6;
    await drive(s, 45);
    R.held = { at: at(s.b), moves: s.b.matPick.moves.length, holdS: s.F.fxEngineInfo(s.b).pick.holdS, over: s.b.matMs > 34 * 1.6 };
    s.b.alive = false;
  } catch (e) { R.error = String(e && e.stack || e); }
  fetch("/r", { method: "POST", body: JSON.stringify(R) });
})();
"""


@unittest.skipUnless(sys.platform == "win32" and _chrome(), "the bundled Chromium (Windows)")
class FitsInChromium(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        page = ("<!doctype html><meta charset=utf-8><script type=module>\n" + CASES.replace("__MAT_JS__", MAT_JS) + "\n</script>").encode()
        got, done = [], threading.Event()

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                p = self.path.split("?", 1)[0]
                if p.startswith("/api/screen"):
                    body, ct, code = b"", "text/plain", 403
                elif p == "/assets/npu/ort.min.mjs":
                    body, ct, code = FAKE_ORT, "text/javascript", 200
                elif p == "/":
                    body, ct, code = page, "text/html", 200
                else:
                    body, ct, code = b"", "text/plain", 404
                self.send_response(code)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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
            done.wait(150)
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

    def test_load_choice(self):
        L = self.R["load"]
        self.assertEqual(L["bigDown"], {"shrink": True})          # a step down still beats the NPU's size
        self.assertEqual(L["move"], {"move": "npu", "idx": 0})    # the NPU reaches the step-down size: move, free the busy GPU
        self.assertIsNone(L["left"])                              # never back to a device it left
        self.assertIsNone(L["floor"])
        self.assertEqual(L["forced"], {"shrink": True})           # one device: the 0.21.94 step-down
        self.assertEqual(L["otherNone"], {"shrink": True})

    def test_choose(self):
        C = self.R["choose"]
        self.assertEqual(C["tie"]["dev"], "npu")
        self.assertIn("the NPU uses less power", C["tie"]["why"])
        self.assertEqual(C["gpu"]["dev"], "gpu")
        self.assertEqual(C["gpu"]["why"], "the GPU reaches 896x512 within 34 ms, the NPU only 512x288")
        self.assertEqual(C["npu"]["dev"], "npu")
        self.assertEqual(C["gpuNpuNone"]["why"], "the GPU reaches 512x288 within 34 ms, the NPU nothing within 34 ms (62 ms at 512x288)")
        self.assertEqual(C["neither"]["dev"], "gpu")
        self.assertIn("neither fits 34 ms", C["neither"]["why"])
        self.assertEqual(C["neitherTie"]["dev"], "npu")
        self.assertEqual(C["onlyGpu"]["dev"], "gpu")
        self.assertIsNone(C["none"])
        self.assertIn("384x704", C["portrait"]["why"])

    def test_gpu_reaches_further_and_takes_over(self):
        g = self.R["gpuWins"]
        self.assertEqual(g["start"], "npu")              # the camera starts on the first that runs
        self.assertEqual(g["at"], "gpu 704x384")
        p = g["pick"]
        self.assertEqual(p["dev"], "gpu")
        self.assertEqual(p["why"], "the GPU reaches 704x384 within 34 ms, the NPU only 512x288")
        self.assertEqual((p["reach"]["npu"]["idx"], p["reach"]["gpu"]["idx"]), (0, 1))
        self.assertIn("704x384", p["reach"]["npu"]["ms"])       # the NPU's 704 was timed and found slow
        self.assertIn("npu|704x384", g["released"])            # ... and let go
        self.assertIn("gpu|896x512", g["released"])
        self.assertIn("npu|512x288", g["released"])            # the loser's floor goes once nothing runs on it
        self.assertNotIn("gpu|704x384", g["released"])
        self.assertTrue(any("picked: the GPU reaches 704x384" in n for n in g["notes"]))

    def test_load_moves_once_and_never_back(self):
        m = self.R["moved"]
        self.assertEqual(m["at"], "npu 512x288")
        self.assertEqual(m["left"], ["gpu"])
        self.assertEqual(len(m["moves"]), 1)
        self.assertIn("the GPU turned slow under load", m["why"])
        s = self.R["stayed"]
        self.assertEqual(s["at"], "npu 512x288")      # the NPU slow too, the GPU fine again: still no flip back
        self.assertEqual(s["moves"], 1)

    def test_same_size_goes_to_the_npu(self):
        self.assertEqual(self.R["tie"]["at"], "npu 704x384")
        self.assertIn("both reach 704x384", self.R["tie"]["why"])

    def test_npu_reaching_further_wins(self):
        self.assertEqual(self.R["npuWins"]["at"], "npu 896x512")

    def test_only_one_device(self):
        o = self.R["onlyGpu"]
        self.assertEqual((o["start"], o["at"]), ("gpu", "gpu 704x384"))
        self.assertTrue(o["why"].startswith("only the GPU runs MODNet here"))

    def test_neither_fits_the_faster_one(self):
        self.assertEqual(self.R["neither"]["at"], "gpu 512x288")
        self.assertIn("the GPU is faster", self.R["neither"]["why"])

    def test_hold_time(self):
        h = self.R["held"]
        self.assertTrue(h["over"])                    # it really was over the line ...
        self.assertEqual((h["at"], h["moves"]), ("gpu 704x384", 0))   # ... and nothing changed inside the hold
        self.assertGreater(h["holdS"], 0)


if __name__ == "__main__":
    unittest.main()
