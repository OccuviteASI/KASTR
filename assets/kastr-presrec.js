// 0.21.92 H (Kenton, 2026-10-28: "Add a toggle for recording the presentation also."): Record the presentation.
//
// Two halves in one file (the page loads it after kastr-pres.js):
//  * THE RECORDER -- this page IS the relay host's own headless recorder (kastr_presrec.py starts it on
//    http://presrec.localhost:<web port>/, a web client by its Host, watch-only on the relay: never in People). It follows the
//    deck's record (the newest owner after a hand-over), keeps that presentation tile in its spotlight, composes the tile as the
//    audience sees it (the share's picture + kastr-pres.js's slide / video / camera layers) at 30 fps, mixes what the audience
//    hears (the slide videos, the presenters, the people let talk -- each tile's own audio root, tapped in parallel, gain 0 for a
//    microphone kastr-pres.js keeps silent) and MediaRecorder's it in 2 s pieces back to the relay host.
//  * THE SWITCH -- presenters and backstage: "Record" in the presenter view's top bar (a switch, with the time it has run), a
//    "Recordings" panel (download, delete), the "Recording saved" card after End, a meeting template's `rec` key. The relay
//    host (/api/presrec) is the truth; the owner's room.json `pres` record carries `rec` so every presenter's switch follows.
//    The audience is never told.
(() => {
  "use strict";
  const IS_REC = location.hostname === "presrec.localhost";
  let RC = null;
  try { RC = JSON.parse(sessionStorage.getItem("kastr.presrec") || "null"); } catch {}
  if (IS_REC) { if (RC && /^[0-9a-f]{16}$/.test(String(RC.rid || ""))) recorder(RC); return; }
  switcher();

  // =====================================================================================================================
  // the recorder page (headless, on the relay host)
  // =====================================================================================================================
  function recorder(R) {
    const W = 1920, H = 1080, PIECE_MS = 2000;
    const PERSON_CAM = /^camera(-\d+)?\.hang$/;
    const st = { part: Number(R.part) || 1, joined: false, share: "", og: 0, rec: false, sent: 0, bytes: 0, queue: 0, stop: false, done: false,
                 mime: "", taps: 0, heard: [], err: "", drawn: 0, t0: 0, paneW: 0, paneH: 0, joinedAt: 0, seenAt: 0, absent: false };
    // THE GATE: the deck's room is only what its creator claimed (/api/pres/new asks nobody), and this page is let into that
    // room without its code -- so it shows and hears NOTHING unless a member of the room is publishing this deck's live record
    // (whoever can do that can watch and hear the room anyway). Never seen in the room / gone for long -> the recording ends.
    const ABSENT_FIRST_MS = 90000, ABSENT_LOST_MS = 180000;
    window.__presrecPage = { state: () => ({ ...st, deck: R.deck }) };   // rig (read-only)
    const api = (what, qs) => "/api/presrec/" + R.rid + "/" + what + "?k=" + encodeURIComponent(R.key) + (qs || "");
    // nothing here is ever seen; the setup card and the like stay out of the way of the stage's layout
    try { const css = document.createElement("style"); css.textContent = "#kSetup, #kSetupBar { display:none !important; }"; document.head.appendChild(css); } catch {}
    try { localStorage.setItem("kastr.operator.name", "Recorder"); } catch {}
    // never a person: the "Everyone online" beats, Messages and profile photos are not even asked for (the relay host refuses
    // them for this watch-only token anyway -- this keeps the recorder out of the hub's lists and its logs quiet)
    const NOT_ME = /\/api\/(people|msg|avatar|chat)(\/|$|\?)/;
    try {
      const f0 = window.fetch.bind(window);
      window.fetch = function (u, o) {
        const s = String(u && u.url ? u.url : u);
        if (NOT_ME.test(s) && String((o && o.method) || (u && u.method) || "GET").toUpperCase() !== "GET")
          return Promise.resolve(new Response('{"error":"the recorder is not a person"}', { status: 403, headers: { "Content-Type": "application/json" } }));
        return f0(u, o);
      };
      const b0 = navigator.sendBeacon && navigator.sendBeacon.bind(navigator);
      if (b0) navigator.sendBeacon = (u, d) => (NOT_ME.test(String(u)) ? true : b0(u, d));
    } catch {}

    // ---- the deck's record (fed by the page's member states, through kastr-pres.js's own seam) ----
    const recs = new Map();   // member path -> that member's pres record of THIS deck
    const wrapMember = () => {
      const f = window.__presMember;
      if (typeof f !== "function" || f.__presrec) return;
      const g = function (path, v) {
        try { if (v && v.pres && typeof v.pres === "object" && v.pres.id === R.deck) recs.set(String(path), v.pres); else recs.delete(String(path)); } catch {}
        return f.apply(this, arguments);
      };
      g.__presrec = true;
      window.__presMember = g;
    };
    wrapMember();
    const cur = () => {
      let best = null;
      for (const r of recs.values()) if (!best || (Number(r.og) || 1) > (Number(best.og) || 1) || ((Number(r.og) || 1) === (Number(best.og) || 1) && (Number(r.ver) || 0) > (Number(best.ver) || 0))) best = r;
      return best;
    };

    // ---- the picture ----
    const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
    const cx = cv.getContext("2d", { alpha: false });
    const tileOf = (p) => { try { return window.__switcher?.tiles?.get(p) || null; } catch { return null; } };
    function draw() {
      cx.fillStyle = "#000"; cx.fillRect(0, 0, W, H);
      const t = st.share ? tileOf(st.share) : null;
      if (!t || !t.pane) return;
      const p = t.pane, r = p.getBoundingClientRect();
      if (r.width < 4 || r.height < 4) return;
      st.paneW = Math.round(r.width); st.paneH = Math.round(r.height);
      const sc = Math.min(W / r.width, H / r.height), pw = r.width * sc, ph = r.height * sc, ox = (W - pw) / 2, oy = (H - ph) / 2;
      const src = p.querySelector("canvas:not(.eq):not(.presov):not(.presvid):not(.prescam), video");
      const iw = src ? (src.videoWidth || src.width || 0) : 0, ih = src ? (src.videoHeight || src.height || 0) : 0;
      if (iw && ih) {
        const s2 = Math.min(pw / iw, ph / ih), dw = iw * s2, dh = ih * s2;
        try { cx.drawImage(src, ox + (pw - dw) / 2, oy + (ph - dh) / 2, dw, dh); } catch {}
      }
      for (const c of p.querySelectorAll("canvas.presov, canvas.presvid, canvas.prescam")) {   // each is the pane's size
        if (c.width > 2 && c.isConnected) { try { cx.drawImage(c, ox, oy, pw, ph); } catch {} }
      }
      st.drawn++;
    }

    // ---- the sound: what the audience hears ----
    let actx = null, dest = null;
    const taps = new Map();   // tile name -> {root, d, src, g}
    function heard(r) {
      const out = new Set();
      if (!r) return out;   // the gate: no live record of this deck in the room -> silence
      for (const v of (r && Array.isArray(r.vids) ? r.vids : [])) if (v && v.p) out.add(String(v.p));   // slide videos + sound clips
      let classes = {};
      try { classes = window.__switcher.state().classes || {}; } catch {}
      for (const name of (window.__switcher?.tiles?.keys() || [])) {
        const seg = String(name).split("/");
        if (seg.length !== 4 || seg[0] !== R.room || !PERSON_CAM.test(seg[3]) || classes[name] === "box") continue;
        let quiet = false;
        try { quiet = !!window.__presTalk?.silent?.(name); } catch {}
        if (!quiet) out.add(String(name));
      }
      return out;
    }
    function tapTick() {
      if (!actx) return;
      const want = heard(cur());
      st.heard = [...want];
      const tiles = window.__switcher?.tiles;
      if (!tiles) return;
      for (const [name, t] of tiles) {
        let root = null;
        try { root = t.meterRoot || t.watch?.audio?.out?.root?.peek?.() || null; } catch {}
        let tp = taps.get(name);
        if (tp && tp.root !== root) { try { tp.root.disconnect(tp.d); } catch {} try { tp.src.disconnect(); } catch {} taps.delete(name); tp = null; }
        if (!tp && root && want.has(name)) {
          try {
            const d = root.context.createMediaStreamDestination();
            root.connect(d);   // in parallel with the page's own volume -- its gain is never touched
            const src = actx.createMediaStreamSource(d.stream), g = actx.createGain();
            g.gain.value = 0;
            src.connect(g).connect(dest);
            tp = { root, d, src, g };
            taps.set(name, tp);
          } catch {}
        }
        if (tp) { try { tp.g.gain.setTargetAtTime(want.has(name) ? 1 : 0, actx.currentTime, 0.03); } catch {} }
      }
      for (const [name, tp] of [...taps]) if (!tiles.has(name)) { try { tp.root.disconnect(tp.d); } catch {} try { tp.src.disconnect(); } catch {} taps.delete(name); }
      st.taps = taps.size;
    }

    // ---- follow the deck: its share in my spotlight ----
    function follow() {
      wrapMember();
      const r = cur();
      if (r) { st.share = String(r.share || ""); st.og = Number(r.og) || 1; st.seenAt = Date.now(); }
      else st.share = "";   // the gate: black while no live record of this deck is in the room (a hand-over's gap too)
      const sw = window.__switcher;
      if (st.share && sw && sw.tiles.has(st.share)) {
        let sel = "";
        try { sel = sw.state().selected || ""; } catch {}
        if (sel !== st.share) { try { sw.select(st.share); } catch {} }
      }
      try { st.joined = !!window.__presPeople?.()?.joined; } catch {}
      if (st.joined && !st.joinedAt) st.joinedAt = Date.now();
      const t = Date.now();
      if (st.joinedAt && !st.stop && ((!st.seenAt && t - st.joinedAt > ABSENT_FIRST_MS) || (st.seenAt && t - st.seenAt > ABSENT_LOST_MS))) { st.absent = true; stopRec(); }
    }

    // ---- the pieces ----
    let mr = null, chain = Promise.resolve(), seq = 0;
    function post(blob, ms) {
      const s = seq++;
      st.queue++;
      chain = chain.then(async () => {
        for (let k = 0; k < 6; k++) {
          try {
            const r = await fetch(api("chunk", "&p=" + st.part + "&s=" + s + "&t=" + Math.round(ms)), { method: "POST", body: blob });
            const j = await r.json().catch(() => ({}));
            if (r.ok) { st.sent++; st.bytes += blob.size; if (j.stop) stopRec(); return; }
            if (r.status === 403 || (r.status === 409 && j.stop)) { stopRec(); return; }
            if (r.status === 409) return;   // out of step: dropped (the server keeps what it has)
          } catch {}
          await new Promise((res) => setTimeout(res, 500 * (k + 1)));
        }
      }).finally(() => { st.queue--; });
      return chain;
    }
    function startRec() {
      if (mr || st.stop) return;
      try {
        actx = new AudioContext({ sampleRate: 48000 });
        dest = actx.createMediaStreamDestination();
        try { actx.resume(); } catch {}
      } catch (e) { st.err = "audio: " + e; }
      const stream = cv.captureStream(30);
      if (dest) for (const a of dest.stream.getAudioTracks()) stream.addTrack(a);
      // the stage recorder's list (0.21.81): MP4 = H.264 High + AAC first (a quick remux on the relay host), Opus where AAC is missing
      const mimes = ["video/mp4;codecs=avc1.640028,mp4a.40.2", "video/mp4;codecs=avc1.42E01E,mp4a.40.2", "video/mp4;codecs=avc1.640028,opus",
        "video/mp4", "video/webm;codecs=vp9,opus", "video/webm"];
      st.mime = mimes.find((m) => { try { return MediaRecorder.isTypeSupported(m); } catch { return false; } }) || "";
      try { mr = new MediaRecorder(stream, st.mime ? { mimeType: st.mime, videoBitsPerSecond: 5000000, audioBitsPerSecond: 160000 } : { videoBitsPerSecond: 5000000 }); }
      catch (e) { st.err = "recorder: " + e; return; }
      st.t0 = Date.now();
      mr.ondataavailable = (e) => { if (e.data && e.data.size) post(e.data, Date.now() - st.t0); };
      mr.onstop = () => { chain.then(() => fetch(api("done", "&p=" + st.part + (st.absent ? "&x=absent" : "")), { method: "POST" })).catch(() => {}).then(() => { st.done = true; }); };
      mr.start(PIECE_MS);
      st.rec = true;
      try { sessionStorage.setItem("kastr.presrec.started", String(st.part)); } catch {}
    }
    function stopRec() {
      if (st.stop) return;
      st.stop = true;
      try { if (mr && mr.state !== "inactive") mr.stop(); else fetch(api("done", "&p=" + st.part + (st.absent ? "&x=absent" : "")), { method: "POST" }).catch(() => {}); } catch {}
    }

    // a reload of this tab (an update, a crash) starts a new part: a second header in one part file would spoil it
    (async () => {
      let started = "";
      try { started = sessionStorage.getItem("kastr.presrec.started") || ""; } catch {}
      if (started && Number(started) === st.part) {
        try { const j = await (await fetch(api("next", "&p=" + st.part), { method: "POST" })).json(); if (j.part) st.part = Number(j.part); if (j.stop) st.stop = true; } catch {}
        try { R.part = st.part; sessionStorage.setItem("kastr.presrec", JSON.stringify(R)); } catch {}
      }
    })();

    setInterval(draw, 33);
    setInterval(() => {
      follow();
      if (st.joined && st.seenAt && !mr && !st.stop) startRec();
      tapTick();
    }, 1000);
    setInterval(async () => {
      try {
        const j = await (await fetch(api("hello"))).json();
        if (j.stop || (j.part && Number(j.part) !== st.part)) stopRec();
      } catch {}
    }, 3000);
  }

  // =====================================================================================================================
  // the switch (presenters + backstage), the Recordings panel, the card after End, the template key
  // =====================================================================================================================
  function switcher() {
    const POLL_MS = 4000, LIST_KEY = "kastr.presrec.decks", LIST_MAX = 40, LIST_DAYS = 60;
    const S = { d: null, st: null, got: 0, busy: false, gone: false, warned: "", want: 0, last: null, endFor: null, el: null, panel: null };
    window.__presrec = {   // rig + templates
      state: () => ({ deck: S.d ? { id: S.d.id, role: S.d.role, own: S.d.own } : null, st: S.st, want: S.want, gone: S.gone }),
      set: (on) => setRec(on !== false),
      list: () => listNow(),
    };
    const deck = () => { try { return window.__pres?.recDeck?.() || null; } catch { return null; } };
    const toast = (m, ms) => { try { window.__toast?.(m, ms || 6000, { level: "event" }); } catch {} };
    const q = (d) => "?deck=" + encodeURIComponent(d.id) + "&k=" + encodeURIComponent(d.k);
    const fmt = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)), h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = s % 60;
                          return (h ? h + ":" + String(m).padStart(2, "0") : String(m)) + ":" + String(x).padStart(2, "0"); };
    const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

    // ---- the decks this device presented / was backstage for (their Recordings stay reachable after End) ----
    function decksGet() {
      try {
        const a = JSON.parse(localStorage.getItem(LIST_KEY) || "[]");
        const cut = Date.now() - LIST_DAYS * 864e5;
        return Array.isArray(a) ? a.filter((x) => x && x.b && x.d && x.k && (x.at || 0) > cut) : [];
      } catch { return []; }
    }
    function decksRemember(d) {
      const a = decksGet().filter((x) => !(x.d === d.id && x.b === d.base));
      a.unshift({ b: d.base, d: d.id, k: d.k, n: String(d.name || "").slice(0, 120), at: Date.now() });
      try { localStorage.setItem(LIST_KEY, JSON.stringify(a.slice(0, LIST_MAX))); } catch {}
    }

    // ---- the relay host's state ----
    async function poll() {
      const d = S.d;
      if (!d) return;
      try {
        const r = await fetch(d.base + "/api/presrec/state" + q(d), { cache: "no-store" });
        if (r.status === 404 || r.status === 405 || r.status === 503) { S.gone = true; S.st = null; paint(); return; }   // an older relay host
        const j = await r.json();
        if (S.d && S.d.id === d.id) { S.st = r.ok ? j : { on: false, err: j.error || String(r.status) }; S.got = Date.now(); S.gone = false; }
      } catch { /* the relay host is unreachable for a moment: keep what was shown */ }
      warnOnce();
      mirror();
      paint();
    }
    function warnOnce() {
      const w = S.st && S.st.warn;
      if (w && w !== S.warned) { S.warned = w; toast("Recording: " + w, 9000, "warn"); }
    }
    async function setRec(on) {
      const d = S.d || deck();
      if (!d || S.busy) return false;
      S.busy = true; paint();
      try {
        const r = await fetch(d.base + "/api/presrec/" + (on ? "start" : "stop") + q(d), { method: "POST", body: JSON.stringify({ name: d.name || "", by: myName() }) });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) { toast("The presentation cannot be recorded: " + (j.error || r.status), 9000, "warn"); }
        else { S.st = j; S.got = Date.now(); if (on) decksRemember(d); }
      } catch (e) { toast("The relay host could not be reached to " + (on ? "start" : "stop") + " the recording.", 7000, "warn"); }
      S.busy = false;
      mirror(); paint();
      if (S.panel && S.panel.open) listNow();
      return !!(S.st && S.st.on === on);
    }
    const myName = () => { try { return String(window.__publisher?.state?.()?.operator || localStorage.getItem("kastr.operator.name") || "").trim().slice(0, 60); } catch { return ""; } };

    // ---- room.json: the owner's `pres` record carries `rec` (every presenter's and backstage person's switch follows) ----
    let rawPres = null, wrappedState = null;
    function wrapState() {
      const s = window.__state;
      if (!s || typeof s.set !== "function" || s === wrappedState) return;
      const orig = s.set;
      s.set = function (field, value) {
        if (field === "pres") { rawPres = value; value = withRec(value); }
        return orig.call(this, field, value);
      };
      s.set.__orig = orig;
      wrappedState = s;
    }
    function withRec(v) {
      if (!v || typeof v !== "object" || !v.id || !S.d || !S.d.own || S.d.id !== v.id || !S.st || S.gone) return v;
      return { ...v, rec: S.st.on ? { on: 1, id: String(S.st.id || "") } : { on: 0 } };
    }
    let mirrored = "";
    function mirror() {
      if (!S.d || !S.d.own || !rawPres || rawPres.id !== S.d.id || !wrappedState) return;
      const sig = S.st ? (S.st.on ? "1:" + S.st.id : "0") : "";
      if (sig === mirrored) return;
      mirrored = sig;
      try { wrappedState.set("pres", rawPres); } catch {}
    }

    // ---- the presenter view: the switch in its top bar, the Recordings panel ----
    const CSS = `
  #presView .kprec { display:inline-flex; align-items:center; gap:6px; flex:none; font-size:12.5px; color:#cfe3f3; margin-right:6px; }
  #presView .kprec[hidden] { display:none; }
  #presView .kprec label.kprsw { display:inline-flex; align-items:center; gap:6px; cursor:pointer; user-select:none; }
  #presView .kprec .kprt { font-variant-numeric:tabular-nums; color:#ff8a8a; min-width:0; }
  #presView .kprec .kprt:empty { display:none; }
  #presView .kprec .kprt::before { content:"●"; margin-right:4px; font-size:10px; vertical-align:1px; }
  #presView .kprec.warn .kprt { color:#ffcf7a; }
  #presView .kprec.off label.kprsw { opacity:.6; cursor:default; }
  #presView .kprl { display:grid; gap:4px; }
  #presView .kprr { display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding:4px 6px; border-radius:6px; background:#121d2a; font-size:12.5px; }
  #presView .kprr .kn { flex:1; min-width:120px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#cfe3f3; }
  #presView .kprr .km { color:#8aa0b5; font-size:12px; }
  #presView .kprr a, #presView .kprr button, #kprDone a, #kprDone button { background:#0b5c86; color:#fff; border:0; border-radius:5px; padding:2px 9px; font:inherit; font-size:12px; cursor:pointer; text-decoration:none; }
  #presView .kprr button.del { background:#3a2020; color:#ffd7d7; }
  #presView .kprw { color:#ffcf7a; font-size:12px; padding:2px 6px; }
  #presView .kprnone { color:#6b7d8f; font-size:12px; padding:2px 6px; }
  #kprDone { position:fixed; right:16px; bottom:16px; z-index:90; display:flex; gap:8px; align-items:center; flex-wrap:wrap; max-width:min(460px, calc(100vw - 32px));
    background:#0f1722; color:#cfe3f3; border:1px solid #1f2a36; border-radius:10px; padding:10px 12px; font:13px 'Segoe UI', system-ui, sans-serif; box-shadow:0 8px 24px rgba(0,0,0,.45); }
  #kprDone .kt { flex:1 1 100%; }
  #kprDone button.x { background:transparent; color:#8aa0b5; border:1px solid #2a3a4a; }`;
    let built = false;
    function build() {
      const pv = document.getElementById("presView");
      if (!pv) return false;
      const ph = pv.querySelector(".ph"), panels = pv.querySelector(".panels");
      if (!ph || !panels) return false;
      if (!built) { const st = document.createElement("style"); st.id = "presRecCss"; st.textContent = CSS; document.head.appendChild(st); built = true; }
      if (!ph.querySelector(".kprec")) {
        const el = document.createElement("span");
        el.className = "kprec"; el.hidden = true;
        el.innerHTML = `<label class="kprsw" title="Record the presentation on the relay host: the live slide and the presenter's camera as the room sees them, with its sound. The audience is not told."><span class="switch sm"><input type="checkbox" aria-label="Record the presentation"><i></i></span><span>Record</span></label><span class="kprt" title="How long it has recorded"></span>`;
        el.querySelector("input").addEventListener("change", (e) => { const on = e.target.checked; e.target.checked = !on; setRec(on); });
        const tm = ph.querySelector(".timer");
        ph.insertBefore(el, tm || null);
        S.el = el;
      }
      if (!panels.querySelector('details.pnl[data-k="rec"]')) {
        const d = document.createElement("details");
        d.className = "pnl"; d.dataset.k = "rec";
        d.innerHTML = `<summary><span class="pnt">Recordings</span><span class="pv"></span></summary><div class="pbody"><div class="kprl"></div></div>`;
        d.addEventListener("toggle", () => { if (d.open) listNow(); });
        panels.appendChild(d);
        S.panel = d;
      }
      return true;
    }
    function paint() {
      if (!build()) return;
      const el = S.el, d = S.d;
      el.hidden = !d || S.gone;
      if (S.panel) S.panel.hidden = !d || S.gone;
      if (!d || S.gone) return;
      const st = S.st || {};
      const inp = el.querySelector("input");
      inp.checked = !!st.on;
      inp.disabled = S.busy || (!st.on && st.can === false);
      el.classList.toggle("off", inp.disabled);
      el.classList.toggle("warn", !!st.warn);
      const lab = el.querySelector("label");
      lab.title = !st.on && st.can === false && st.why ? "Recording is not possible: " + st.why
        : st.warn ? st.warn : "Record the presentation on the relay host: the live slide and the presenter's camera as the room sees them, with its sound. The audience is not told.";
      const t = el.querySelector(".kprt");
      const txt = st.on ? fmt((Number(st.el) || 0) + (Date.now() - (S.got || Date.now()))) : "";
      if (t.textContent !== txt) t.textContent = txt;
      if (S.panel) {
        const pvv = S.panel.querySelector(".pv");
        const v = st.on ? "Recording " + txt : (S.last && S.last.n ? S.last.n + " saved" : "");
        if (pvv.textContent !== v) pvv.textContent = v;
      }
    }

    // ---- the Recordings list (the relay host of the deck on show; every deck of mine there, + an admin's bearer) ----
    function bearer() {
      try { const h = window.__auth?.bearer?.() || {}; const a = String(h.authorization || ""); return a.startsWith("Bearer ") ? a.slice(7) : ""; } catch { return ""; }
    }
    async function listAt(base, room) {
      const keys = decksGet().filter((x) => x.b === base).map((x) => ({ d: x.d, k: x.k }));
      const d = S.d;
      if (d && d.base === base && !keys.some((x) => x.d === d.id)) keys.unshift({ d: d.id, k: d.k });
      const r = await fetch(base + "/api/presrec/list", { method: "POST", body: JSON.stringify({ keys, room: room || "", bearer: bearer() }) });
      if (!r.ok) throw new Error(String(r.status));
      return (await r.json()).recordings || [];
    }
    async function listNow() {
      const d = S.d;
      if (!d || !S.panel) return [];
      const box = S.panel.querySelector(".kprl");
      let list = [];
      try { list = await listAt(d.base, d.room); }
      catch { box.innerHTML = `<div class="kprnone">The relay host cannot list the recordings just now.</div>`; return []; }
      S.last = { n: list.filter((x) => x.state === "done").length };
      const rows = list.map((x) => {
        const dur = (x.parts || []).reduce((a, p) => a + (Number(p.ms) || 0), 0);
        const when = x.at ? new Date(x.at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "";
        const mb = (Number(x.size) || 0) / 1048576;
        const meta = [when, dur ? fmt(dur) : "", mb ? (mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : Math.max(1, Math.round(mb)) + " MB") : ""].filter(Boolean).join(" · ");
        const dl = x.state === "rec" ? `<span class="km">recording…</span>`
          : (x.parts || []).map((p) => `<a href="${esc(d.base + "/api/presrec/" + x.id + "/" + p.n + ".mp4?k=" + encodeURIComponent(x.dk))}" download title="Download${(x.parts.length > 1) ? " part " + p.n : ""}">${x.parts.length > 1 ? "Part " + p.n : "Download"}</a>`).join("");
        const del = x.del && x.state !== "rec" ? `<button type="button" class="del" data-id="${esc(x.id)}" data-d="${esc(x.deck)}" title="Delete this recording from the relay host (for everyone)">Delete</button>` : "";
        const w = x.warn ? `<div class="kprw">${esc(x.warn)}</div>` : "";
        return `<div class="kprr"><span class="kn" title="${esc(x.name)}">${esc(x.name)}</span><span class="km">${esc(meta)}</span>${dl}${del}${w}</div>`;
      });
      const warn = S.st && S.st.warn ? `<div class="kprw">${esc(S.st.warn)}</div>` : "";
      box.innerHTML = warn + (rows.join("") || `<div class="kprnone">No recordings yet. Switch on Record in the top bar.</div>`);
      for (const b of box.querySelectorAll("button.del")) b.addEventListener("click", () => delRec(b.dataset.id, b.dataset.d));
      paint();
      return list;
    }
    async function delRec(id, did) {
      const d = S.d;
      if (!d || !confirm("Delete this recording from the relay host? Nobody can download it after this.")) return;
      const keys = decksGet().filter((x) => x.b === d.base && x.d === did).map((x) => ({ d: x.d, k: x.k }));
      if (did === d.id) keys.unshift({ d: d.id, k: d.k });
      try {
        const r = await fetch(d.base + "/api/presrec/" + id + "/delete", { method: "POST", body: JSON.stringify({ keys, bearer: bearer() }) });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) toast(j.error || "The recording could not be deleted.", 7000, "warn");
      } catch { toast("The relay host could not be reached.", 6000, "warn"); }
      listNow();
    }

    // ---- after End: "Recording saved" with its download ----
    async function endCard(d) {
      for (let k = 0; k < 45; k++) {
        await new Promise((r) => setTimeout(r, 2000));
        let list = [];
        try { list = await listAt(d.base, d.room); } catch { continue; }
        const mine = list.filter((x) => x.deck === d.id);
        if (!mine.length) { if (k > 10) return; continue; }
        if (mine.some((x) => x.state === "rec")) continue;
        const x = mine[0];
        let c = document.getElementById("kprDone");
        if (c) c.remove();
        c = document.createElement("div"); c.id = "kprDone"; c.setAttribute("role", "status");
        const links = (x.parts || []).map((p) => `<a href="${esc(d.base + "/api/presrec/" + x.id + "/" + p.n + ".mp4?k=" + encodeURIComponent(x.dk))}" download>${x.parts.length > 1 ? "Part " + p.n : "Download"}</a>`).join("");
        c.innerHTML = `<span class="kt">Recording of “${esc(x.name)}” saved on the relay host${links ? "" : " (nothing was recorded)"}.</span>${links}<button type="button" class="x">Close</button>`;
        c.querySelector(".x").addEventListener("click", () => c.remove());
        document.body.appendChild(c);
        return;
      }
    }

    // ---- meeting templates: `rec` rides the presentation toggles (audSnap / audApply), startFromFile(file, {rec: 1}) ----
    function wrapTemplates() {
      const P = window.__pres;
      if (!P || P.__presrec) return;
      P.__presrec = true;
      const snap0 = P.audSnap;
      if (typeof snap0 === "function") P.audSnap = function () { const s = snap0.apply(this, arguments); return s && S.d ? { ...s, rec: S.st && S.st.on ? 1 : 0 } : s; };
      const apply0 = P.audApply;
      P.audApply = function (s) {
        const out = typeof apply0 === "function" ? apply0.apply(this, arguments) : null;
        if (s && typeof s === "object" && "rec" in s) {
          const on = s.rec === true || Number(s.rec) === 1;
          if (S.d) { setRec(on); if (out && typeof out === "object") out.rec = true; else return { rec: true }; }
          else if (on) S.want = Date.now();   // the deck is not up yet: it starts when the presentation does
        }
        return out;
      };
      const start0 = P.startFromFile;
      if (typeof start0 === "function") P.startFromFile = function (file, opts) {
        if (opts && (opts.rec === true || Number(opts.rec) === 1)) S.want = Date.now();
        return start0.apply(this, arguments);
      };
    }

    // ---- the loop ----
    let pollT = 0;
    setInterval(() => {
      wrapState(); wrapTemplates();
      const d = deck();
      const prev = S.d;
      if (!d) {
        if (prev && S.st && S.st.on) endCard(prev);   // End (or my role went): the card once the file is finished
        if (prev) { S.d = null; S.st = null; S.gone = false; mirrored = ""; paint(); }
        return;
      }
      const changed = !prev || prev.id !== d.id || prev.k !== d.k;
      S.d = d;
      if (changed) { S.st = null; S.gone = false; mirrored = ""; decksRemember(d); pollT = 0; }
      // someone else switched it: the owner's record says so before my next poll
      if (!d.own && d.rec && S.st && !!d.rec.on !== !!S.st.on) pollT = 0;
      if (Date.now() - pollT > POLL_MS) {
        pollT = Date.now();
        poll().then(() => {
          if (S.want && S.d && S.st && !S.st.on && !S.busy) {
            if (Date.now() - S.want < 180000 && S.st.can !== false) setRec(true);
            S.want = 0;
          }
        });
      }
      paint();
    }, 1000);
  }
})();
