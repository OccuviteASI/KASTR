// 0.21.84 (Kenton: "start exploring using powerpoints, or other documents, directly inside of KASTR ... progress
// forward/backward, but only show the preview for those being casted to ... The person presenting and the 'backstage'
// person controlling need to see the notes/slides upcoming as well as what is live while others only see the
// presentation."): PROTOTYPE of Share > Presentation (mode 1: KASTR renders the deck).
//
// Who does what:
//   PRESENTER  (whoever picked the file) -- the ONE authority. Its page turns the deck into slide pictures (PDF: pdf.js;
//              .pptx: kastr_pres.py's scene drawn here), encrypts slide i with its own key k_i = HKDF(K, "slide/i") and
//              the notes with HKDF(K, "notes"), stores the ciphertext on the relay host (/api/pres), shares the live
//              slide as a normal content share (old KASTRs, phones, web viewers and the recorder see it unchanged) and
//              publishes the live state in its room.json `pres`: deck id, slide index, version, and k_idx -- the key of
//              the LIVE slide only.
//   BACKSTAGE  (people the presenter picks; any 0.21.84 page in the room) -- K arrives wrapped to the person's own
//              ECDH P-256 key (their room.json `presPk`), so only they can open the upcoming slides and the notes.
//              Their Next / Back is an intent in their own room.json `presCtl` that the presenter applies.
//   VIEWERS    -- the share tile, plus a sharp still of the live slide drawn over it: they fetch s<idx>.bin and open it
//              with k_idx. They never fetch the notes and cannot open any slide that has not been live.
// VIDEOS ON SLIDES (0.21.87): an embedded video plays in its spot on the slide while that slide is live -- the presenter
//              streams it like Share > Media file (window.__presVideo), `pres.vids` says where and how far, every page draws
//              the stream over the still; Play / Pause / seek from the presenter or backstage (presCtl.vid), viewers watch.
// PRESENTER MODES (0.21.89): Content only / Standout / Side-by-side / Reporter -- the presenter's camera drawn into the tile (the
//              cut-out for Standout and Reporter comes from the presenter's page, window.__presCut), picked by the presenter or
//              backstage (presCtl.cm); backstage can also mute / unmute the presenter's mic and pause / resume their video
//              (presCtl.av) while the presenter's switch allows it. See "PRESENTER MODES" below.
// Collisions: an intent carries the version it saw (`bv`); the presenter applies it when nobody else moved since
// (bv == ver) or when the last move was the same person's (a fast double Next from one clicker) -- two people pressing
// Next on slide 3 at once land on 4, not 5.
(() => {
  "use strict";
  if (window.__pres) return;
  const STILL_W = 2560;            // slide pictures: 2560 px wide (1440p sharp; the share itself is 1080p)
  const SHARE_W = 1920;
  const SHARE_FPS = 5;             // a static slide: a frame every 200 ms keeps the encoder's keyframes coming for late joiners
  const enc = new TextEncoder(), dec = new TextDecoder();
  const subtle = (window.crypto && window.crypto.subtle) || null;
  const trace = [];                // rig: [{t, ev, id, idx, ver, who}]
  const T = (ev, o) => { trace.push(Object.assign({ t: Date.now(), ev }, o || {})); if (trace.length > 400) trace.splice(0, 100); };
  const toast = (msg, ms, level) => { try { window.__toast?.(msg, ms || 5000, { level: level || "event" }); } catch {} };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b64 = (u8) => { let s = ""; const a = new Uint8Array(u8); for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode.apply(null, a.subarray(i, i + 0x8000)); return btoa(s); };
  const unb64 = (s) => Uint8Array.from(atob(String(s || "")), (c) => c.charCodeAt(0));
  const clampI = (i, n) => Math.max(0, Math.min(n - 1, i | 0));

  // ---- crypto --------------------------------------------------------------------------------------------------------
  async function hkdf(K, info) {
    const base = await subtle.importKey("raw", K, "HKDF", false, ["deriveBits"]);
    return new Uint8Array(await subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt: enc.encode("kastr-pres-v1"), info: enc.encode(info) }, base, 256));
  }
  async function seal(raw, bytes) {
    const k = await subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt"]);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ct = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv }, k, bytes));
    const out = new Uint8Array(12 + ct.length); out.set(iv, 0); out.set(ct, 12); return out;
  }
  async function unseal(raw, buf) {
    const u = new Uint8Array(buf);
    const k = await subtle.importKey("raw", raw, "AES-GCM", false, ["decrypt"]);
    return new Uint8Array(await subtle.decrypt({ name: "AES-GCM", iv: u.subarray(0, 12) }, k, u.subarray(12)));
  }
  let ecdh = null;   // this page's ECDH key pair (private key never leaves WebCrypto)
  async function myKeys() {
    if (!ecdh) {
      const kp = await subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
      ecdh = { kp, pub: b64(await subtle.exportKey("raw", kp.publicKey)) };
    }
    return ecdh;
  }
  async function wrapKey(theirPub, info) {   // -> 32 raw bytes shared by me and the holder of theirPub
    const me = await myKeys();
    const pk = await subtle.importKey("raw", unb64(theirPub), { name: "ECDH", namedCurve: "P-256" }, false, []);
    const bits = new Uint8Array(await subtle.deriveBits({ name: "ECDH", public: pk }, me.kp.privateKey, 256));
    return hkdf(bits, "wrap/" + info);
  }

  // ---- the room, through the page's seams -------------------------------------------------------------------------
  const ctx = () => { try { return window.__presPeople?.() || null; } catch { return null; } };
  const meDbg = () => { try { return window.__state?.debug?.() || {}; } catch { return {}; } };
  function myPerson() {
    const pm = meDbg().pubModel || {};
    return String(pm.host || "") + "/" + String(pm.op || pm.peer || "");
  }
  function personOfPath(path) {   // a member path -> "host/op" via the room's people
    const c = ctx();
    const p = c && (c.people || []).find((x) => x.path === path);
    if (p) return p.host + "/" + (p.op || p.peer);
    const parts = String(path).split("/");
    return (parts[1] || "") + "/" + (parts[3] || "");
  }
  function nameOfPerson(pk) {
    const c = ctx();
    const p = c && (c.people || []).find((x) => x.host + "/" + (x.op || x.peer) === pk);
    return p ? (p.name || p.op || p.host) : pk.split("/").pop();
  }
  function relayBase() { try { return window.__relayHostBase?.() || location.origin; } catch { return location.origin; } }
  const PRIV = /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|127\.|localhost$|\[?::1\]?$)|\.local$/;
  function baseFor(rec) {   // like the files service (0.21.2): a private address is fetched through MY relay host when that one is public
    const b = String(rec.base || "");
    try { const u = new URL(b), mb = new URL(relayBase()); if (PRIV.test(u.hostname) && !PRIV.test(mb.hostname)) return mb.origin; } catch {}
    return b;
  }
  const stateSet = (k, v) => { try { window.__state?.set?.(k, v); } catch {} };

  // ---- what other pages publish (fed by memberApply) ----------------------------------------------------------------
  const remote = new Map();   // member path -> {pres, ctl, pk}
  let pkPublished = "";
  window.__presMember = (path, v) => {
    const me = meDbg().room;
    if (!path || path === me) return;
    if (!v) { remote.delete(path); schedule(); return; }
    const cur = remote.get(path) || {};
    const next = { pres: v.pres && typeof v.pres === "object" ? v.pres : null, ctl: v.presCtl && typeof v.presCtl === "object" ? v.presCtl : null,
                   pk: typeof v.presPk === "string" ? v.presPk : "" };
    remote.set(path, next);
    if (mine && next.ctl && next.ctl.id === mine.id) applyIntent(path, next.ctl);
    if (mine && next.pk !== (cur.pk || "")) rewrapSoon();
    if (next.pres) T("seen", { id: next.pres.id, idx: next.pres.idx, ver: next.pres.ver, who: path });
    schedule();
  };
  async function ensurePk() {   // publish my public key once a presentation exists in my room (or I present)
    if (!subtle) return;
    const any = !!mine || [...remote.values()].some((r) => r.pres);
    if (!any) return;
    const k = await myKeys();
    if (pkPublished !== k.pub) { pkPublished = k.pub; stateSet("presPk", k.pub); }
  }

  // ---- slide pictures ---------------------------------------------------------------------------------------------------
  const stillCache = new Map();   // "<id>/<i>" -> Promise<ImageBitmap>
  function cacheGet(key, make) {
    if (stillCache.has(key)) { const p = stillCache.get(key); stillCache.delete(key); stillCache.set(key, p); return p; }
    const p = make().catch((e) => { stillCache.delete(key); throw e; });
    stillCache.set(key, p);
    while (stillCache.size > 14) { const [k0, p0] = stillCache.entries().next().value; stillCache.delete(k0); p0.then((b) => { try { b.close(); } catch {} }).catch(() => {}); }
    return p;
  }
  async function fetchBlob(base, id, name, tries, rt) {   // rt: the deck's read token (presenter + backstage only)
    for (let a = 0; ; a++) {
      const r = await fetch(base + "/api/pres/" + id + "/" + name + (rt ? "?rt=" + encodeURIComponent(rt) : ""), { cache: name === "notes.bin" || !rt ? "no-store" : "default" });
      if (r.ok) return await r.arrayBuffer();
      if (r.status !== 404 || a >= (tries || 0)) throw new Error("slide " + name + ": " + r.status);
      await sleep(600);
    }
  }
  async function bitmapFromCipher(base, id, i, key, rt) {
    const buf = await fetchBlob(base, id, "s" + i + ".bin", 25, rt);
    const plain = await unseal(key, buf);
    return await createImageBitmap(new Blob([plain], { type: "image/webp" }));
  }

  // ---- drawing helpers -------------------------------------------------------------------------------------------------
  function drawContain(cv, bmp, blank, label) {
    const g = cv.getContext("2d");
    const W = cv.width, H = cv.height;
    g.fillStyle = "#000"; g.fillRect(0, 0, W, H);
    if (blank === "white") { g.fillStyle = "#fff"; g.fillRect(0, 0, W, H); return; }
    if (blank === "black") return;
    if (!bmp) {
      if (label) { g.fillStyle = "#9aa7b4"; g.font = Math.max(11, Math.round(H * 0.06)) + "px 'Segoe UI', system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(label, W / 2, H / 2); }
      return;
    }
    const k = Math.min(W / bmp.width, H / bmp.height), w = bmp.width * k, h = bmp.height * k;
    g.imageSmoothingQuality = "high";
    g.drawImage(bmp, (W - w) / 2, (H - h) / 2, w, h);
  }
  function fitCanvas(cv) {   // a canvas sized to its box in device pixels -- sharp at any tile size
    const r = cv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
    const w = Math.max(2, Math.round(r.width * d)), h = Math.max(2, Math.round(r.height * d));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; return true; }
    return false;
  }

  // ---- .pptx scenes (kastr_pres.py) drawn on a canvas ------------------------------------------------------------------
  const WING = { "§": "■", "Ø": "➢", "ü": "✓", "q": "❑", "v": "❖", "n": "■", "l": "●", "Ÿ": "•", "o": "○", "p": "□", "u": "◆" };
  function geomPath(g, geo, w, h) {
    const p = (geo && geo.prst) || "rect", adj = (geo && geo.adj) || {};
    const m = Math.min(w, h), A = (k, d) => (adj[k] != null ? adj[k] : d) / 100000;
    g.beginPath();
    const poly = (pts) => { g.moveTo(pts[0][0], pts[0][1]); for (let i = 1; i < pts.length; i++) g.lineTo(pts[i][0], pts[i][1]); g.closePath(); };
    switch (p) {
      case "roundRect": case "flowChartAlternateProcess": case "wedgeRoundRectCallout": { const r = m * A("adj", 16667); g.roundRect ? g.roundRect(0, 0, w, h, r) : g.rect(0, 0, w, h); break; }
      case "round2SameRect": { const r = m * A("adj1", 16667); g.roundRect ? g.roundRect(0, 0, w, h, [r, r, 0, 0]) : g.rect(0, 0, w, h); break; }
      case "round1Rect": { const r = m * A("adj", 16667); g.roundRect ? g.roundRect(0, 0, w, h, [0, r, 0, 0]) : g.rect(0, 0, w, h); break; }
      case "snip1Rect": { const s = m * A("adj", 16667); poly([[0, 0], [w - s, 0], [w, s], [w, h], [0, h]]); break; }
      case "ellipse": case "donut": case "flowChartConnector": g.ellipse(w / 2, h / 2, w / 2, h / 2, 0, 0, Math.PI * 2); break;
      case "triangle": poly([[w * A("adj", 50000), 0], [w, h], [0, h]]); break;
      case "rtTriangle": poly([[0, 0], [w, h], [0, h]]); break;
      case "diamond": case "flowChartDecision": poly([[w / 2, 0], [w, h / 2], [w / 2, h], [0, h / 2]]); break;
      case "parallelogram": { const o = m * A("adj", 25000); poly([[o, 0], [w, 0], [w - o, h], [0, h]]); break; }
      case "trapezoid": { const o = m * A("adj", 25000); poly([[o, 0], [w - o, 0], [w, h], [0, h]]); break; }
      case "pentagon": poly([[w / 2, 0], [w, h * 0.38], [w * 0.81, h], [w * 0.19, h], [0, h * 0.38]]); break;
      case "hexagon": { const o = m * A("adj", 25000); poly([[o, 0], [w - o, 0], [w, h / 2], [w - o, h], [o, h], [0, h / 2]]); break; }
      case "octagon": { const o = m * A("adj", 29289); poly([[o, 0], [w - o, 0], [w, o], [w, h - o], [w - o, h], [o, h], [0, h - o], [0, o]]); break; }
      case "homePlate": { const o = m * A("adj", 50000); poly([[0, 0], [w - o, 0], [w, h / 2], [w - o, h], [0, h]]); break; }
      case "chevron": { const o = m * A("adj", 50000); poly([[0, 0], [w - o, 0], [w, h / 2], [w - o, h], [0, h], [o, h / 2]]); break; }
      case "rightArrow": { const t = h * A("adj1", 50000), hl = m * A("adj2", 50000); poly([[0, (h - t) / 2], [w - hl, (h - t) / 2], [w - hl, 0], [w, h / 2], [w - hl, h], [w - hl, (h + t) / 2], [0, (h + t) / 2]]); break; }
      case "leftArrow": { const t = h * A("adj1", 50000), hl = m * A("adj2", 50000); poly([[w, (h - t) / 2], [hl, (h - t) / 2], [hl, 0], [0, h / 2], [hl, h], [hl, (h + t) / 2], [w, (h + t) / 2]]); break; }
      case "upArrow": { const t = w * A("adj1", 50000), hl = m * A("adj2", 50000); poly([[(w - t) / 2, h], [(w - t) / 2, hl], [0, hl], [w / 2, 0], [w, hl], [(w + t) / 2, hl], [(w + t) / 2, h]]); break; }
      case "downArrow": { const t = w * A("adj1", 50000), hl = m * A("adj2", 50000); poly([[(w - t) / 2, 0], [(w - t) / 2, h - hl], [0, h - hl], [w / 2, h], [w, h - hl], [(w + t) / 2, h - hl], [(w + t) / 2, 0]]); break; }
      case "leftRightArrow": { const t = h * A("adj1", 50000), hl = m * A("adj2", 50000); poly([[0, h / 2], [hl, 0], [hl, (h - t) / 2], [w - hl, (h - t) / 2], [w - hl, 0], [w, h / 2], [w - hl, h], [w - hl, (h + t) / 2], [hl, (h + t) / 2], [hl, h]]); break; }
      case "plus": { const o = m * A("adj", 25000); poly([[o, 0], [w - o, 0], [w - o, o], [w, o], [w, h - o], [w - o, h - o], [w - o, h], [o, h], [o, h - o], [0, h - o], [0, o], [o, o]]); break; }
      case "star5": { const pts = []; for (let i = 0; i < 10; i++) { const r = i % 2 ? 0.38 : 1, a = -Math.PI / 2 + i * Math.PI / 5; pts.push([w / 2 + Math.cos(a) * w / 2 * r, h / 2 + Math.sin(a) * h / 2 * r]); } poly(pts); break; }
      case "flowChartTerminator": g.roundRect ? g.roundRect(0, 0, w, h, h / 2) : g.rect(0, 0, w, h); break;
      case "line": case "straightConnector1": case "bentConnector3": case "curvedConnector3": g.moveTo(0, 0); g.lineTo(w, h); return "line";
      case "cust": {
        let any = false;
        for (const pth of geo.paths || []) {
          const sx = pth.w ? w / pth.w : 1, sy = pth.h ? h / pth.h : 1;
          let cx = 0, cy = 0;
          for (const c of pth.d || []) {
            const op = c[0];
            if (op === "M") { g.moveTo(c[1] * sx, c[2] * sy); cx = c[1] * sx; cy = c[2] * sy; }
            else if (op === "L") { g.lineTo(c[1] * sx, c[2] * sy); cx = c[1] * sx; cy = c[2] * sy; }
            else if (op === "C") { g.bezierCurveTo(c[1] * sx, c[2] * sy, c[3] * sx, c[4] * sy, c[5] * sx, c[6] * sy); cx = c[5] * sx; cy = c[6] * sy; }
            else if (op === "Q") { g.quadraticCurveTo(c[1] * sx, c[2] * sy, c[3] * sx, c[4] * sy); cx = c[3] * sx; cy = c[4] * sy; }
            else if (op === "Z") g.closePath();
            else if (op === "A") {   // arcTo: radii wR/hR, start + swing in 60000ths of a degree, from the current point
              const wr = c[1] * sx, hr = c[2] * sy, st = c[3] / 60000 * Math.PI / 180, sw = c[4] / 60000 * Math.PI / 180;
              const ox = cx - wr * Math.cos(st), oy = cy - hr * Math.sin(st);
              g.ellipse(ox, oy, Math.abs(wr), Math.abs(hr), 0, st, st + sw, sw < 0);
              cx = ox + wr * Math.cos(st + sw); cy = oy + hr * Math.sin(st + sw);
            }
            any = true;
          }
        }
        if (!any) g.rect(0, 0, w, h);
        break;
      }
      default: g.rect(0, 0, w, h);
    }
    return "shape";
  }
  function paintFill(g, f, w, h, imgs) {
    if (!f) return false;
    if (f.c) { g.fillStyle = f.c; g.fill(); return true; }
    if (f.g && f.g.stops && f.g.stops.length) {
      let gr;
      if (f.g.radial) gr = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.hypot(w, h) / 2);
      else {
        const a = (f.g.ang || 0) * Math.PI / 180, dx = Math.cos(a), dy = Math.sin(a);
        const half = Math.abs(w / 2 * dx) + Math.abs(h / 2 * dy);
        gr = g.createLinearGradient(w / 2 - dx * half, h / 2 - dy * half, w / 2 + dx * half, h / 2 + dy * half);
      }
      for (const [pos, c] of f.g.stops) { try { gr.addColorStop(Math.max(0, Math.min(1, pos)), c); } catch {} }
      g.fillStyle = gr; g.fill(); return true;
    }
    if (f.img && imgs[f.img]) { g.save(); g.clip(); drawImageCropped(g, imgs[f.img], f.crop, 0, 0, w, h); g.restore(); return true; }
    return false;
  }
  function drawImageCropped(g, img, crop, x, y, w, h) {
    const iw = img.naturalWidth || img.width, ih = img.naturalHeight || img.height;
    if (!iw || !ih) return;
    const c = crop || [0, 0, 0, 0];
    const sx = iw * c[0], sy = ih * c[1], sw = iw * (1 - c[0] - c[2]), sh = ih * (1 - c[1] - c[3]);
    if (sw > 0 && sh > 0) g.drawImage(img, sx, sy, sw, sh, x, y, w, h);
  }
  function fontOf(r, px) {
    const fam = String(r.f || "Calibri").replace(/["]/g, "");
    const bold = r.b || /semibold|bold|black|heavy/i.test(fam) ? (/semibold/i.test(fam) ? 600 : 700) : 400;
    return (r.i ? "italic " : "") + bold + " " + px.toFixed(2) + "px \"" + fam + "\", \"" + fam.replace(/ (Semibold|Light|Bold|Black)$/i, "") + "\", \"Segoe UI\", Calibri, Arial, sans-serif";
  }
  const ROMAN = [[1000, "m"], [900, "cm"], [500, "d"], [400, "cd"], [100, "c"], [90, "xc"], [50, "l"], [40, "xl"], [10, "x"], [9, "ix"], [5, "v"], [4, "iv"], [1, "i"]];
  function autoNum(type, n) {
    let s = String(n);
    if (/^alpha/.test(type)) { s = ""; let k = n; while (k > 0) { k--; s = String.fromCharCode(97 + (k % 26)) + s; k = Math.floor(k / 26); } }
    else if (/^roman/.test(type)) { s = ""; let k = n; for (const [v, r] of ROMAN) while (k >= v) { s += r; k -= v; } }
    if (/Uc/.test(type)) s = s.toUpperCase();
    if (/ParenBoth$/.test(type)) return "(" + s + ")";
    if (/ParenR$/.test(type)) return s + ")";
    if (/Plain$/.test(type)) return s;
    return s + ".";
  }
  function drawText(g, tx, w, h, s) {
    if (!tx || !tx.ps) return;
    const ins = tx.ins || [91440, 45720, 91440, 45720];
    const L = ins[0] * s, Tt = ins[1] * s, W = Math.max(1, w - (ins[0] + ins[2]) * s), H = h - (ins[1] + ins[3]) * s;
    const fs = tx.scale || 1, red = tx.lnRed || 0;
    const lines = [];   // {y0 (relative), h, base, items:[{x, t, font, color, u, s}], bullet}
    let y = 0;
    const counters = {};
    tx.ps.forEach((p, pi) => {
      const runs = (p.rs || []).filter((r) => r.t != null);
      const firstPx = ((runs[0] && runs[0].sz) || p.esz || 1800) / 100 * 12700 * s * fs;
      const spc = (sp, px) => (!sp ? 0 : sp.pts != null ? sp.pts / 100 * 12700 * s * fs : sp.pct * px * 1.2);
      y += spc(p.spcBef, firstPx);
      const ml = (p.ml || 0) * s, ind = (p.ind || 0) * s;
      let bulletTxt = "", bulletFont = "", bulletColor = "";
      if (p.bu) {
        if (p.bu.n) { const lv = p.lvl || 0; counters[lv] = (counters[lv] || (p.bu.start || 1) - 1) + 1; for (const k of Object.keys(counters)) if (+k > lv) delete counters[k]; bulletTxt = autoNum(p.bu.n, counters[lv]); }
        else { bulletTxt = p.bu.c || "•"; if (/wingdings|symbol/i.test(p.bu.f || "")) bulletTxt = WING[bulletTxt] || "•"; }
        const r0 = runs[0] || {};
        bulletFont = fontOf({ f: /wingdings|symbol/i.test(p.bu.f || "") ? "Segoe UI Symbol" : (p.bu.f || r0.f), b: 0 }, firstPx * (p.bu.sz || 1));
        bulletColor = p.bu.col || r0.c || "#000";
      } else if (p.bu === undefined) {
        for (const k of Object.keys(counters)) delete counters[k];
      }
      const startX = p.bu ? ml : Math.max(0, ml + ind);
      const firstX = p.bu ? (ind >= 0 ? ml + ind + (g.font = bulletFont, g.measureText(bulletTxt + " ").width) : ml) : Math.max(0, ml + ind);
      // words with their run style
      const toks = [];
      for (const r of runs) {
        const px = (r.sz || 1800) / 100 * 12700 * s * fs * (r.bl ? 0.7 : 1);
        if (r.br) { toks.push({ br: 1, px }); continue; }
        const parts = String(r.t).split(/(\s+)/);
        for (const part of parts) if (part) toks.push({ t: part, r, px, font: fontOf(r, px) });
      }
      let cur = { items: [], width: 0, px: firstPx, x0: firstX, first: true };
      const flush = () => { lines.push(cur); cur = { items: [], width: 0, px: 0, x0: startX, first: false }; };
      const avail = (ln) => (tx.wrap === false ? 1e9 : W - ln.x0);
      for (const tk of toks) {
        if (tk.br) { cur.px = Math.max(cur.px, tk.px); flush(); continue; }
        g.font = tk.font;
        let tw = g.measureText(tk.t).width;
        const space = /^\s+$/.test(tk.t);
        if (!space && cur.width + tw > avail(cur) && cur.items.some((it) => !/^\s+$/.test(it.t))) {
          while (cur.items.length && /^\s+$/.test(cur.items[cur.items.length - 1].t)) { const it = cur.items.pop(); cur.width -= it.w; }
          flush();
        }
        if (space && !cur.items.length && !cur.first) continue;
        if (!space && tw > avail(cur)) {   // one word wider than the box: break it by characters
          let chunk = "";
          for (const ch of tk.t) {
            const cw = g.measureText(chunk + ch).width;
            if (cur.width + cw > avail(cur) && chunk) { cur.items.push({ t: chunk, w: g.measureText(chunk).width, tk }); cur.px = Math.max(cur.px, tk.px); flush(); chunk = ""; }
            chunk += ch;
          }
          tw = g.measureText(chunk).width;
          cur.items.push({ t: chunk, w: tw, tk }); cur.width += tw; cur.px = Math.max(cur.px, tk.px);
          continue;
        }
        cur.items.push({ t: tk.t, w: tw, tk }); cur.width += tw; cur.px = Math.max(cur.px, tk.px);
      }
      if (!cur.px) cur.px = firstPx;
      lines.push(cur);
      // line heights
      let firstOfPara = true;
      for (const ln of lines) {
        if (ln.done) continue;
        const px = ln.px || firstPx;
        let lh = px * 1.2;
        if (p.lnSpc) lh = p.lnSpc.pts != null ? p.lnSpc.pts / 100 * 12700 * s * fs : px * 1.2 * p.lnSpc.pct;
        lh *= (1 - red);
        ln.y0 = y; ln.h = lh; ln.base = y + lh * 0.8 + (lh - px * 1.2) * 0.1; ln.al = p.al; ln.W = W; ln.done = true;
        if (firstOfPara && p.bu) { ln.bullet = { t: bulletTxt, font: bulletFont, color: bulletColor, x: Math.max(0, ml + ind) }; }
        firstOfPara = false;
        y += lh;
      }
      y += spc(p.spcAft, firstPx);
    });
    const total = y;
    const oy = tx.anchor === "ctr" ? (H - total) / 2 : tx.anchor === "b" ? H - total : 0;
    for (const ln of lines) {
      const used = ln.items.reduce((a, it) => a + it.w, 0);
      let x = ln.x0;
      if (ln.al === "ctr") x = ln.x0 + (W - ln.x0 - used) / 2;
      else if (ln.al === "r") x = W - used;
      const by = Tt + oy + ln.base;
      if (ln.bullet) { g.font = ln.bullet.font; g.fillStyle = ln.bullet.color; g.textBaseline = "alphabetic"; g.textAlign = "left"; g.fillText(ln.bullet.t, L + ln.bullet.x, by); }
      for (const it of ln.items) {
        const r = it.tk.r;
        g.font = it.tk.font; g.fillStyle = r.c || "#000"; g.textBaseline = "alphabetic"; g.textAlign = "left";
        const yy = by - (r.bl ? r.bl * it.tk.px : 0);
        g.fillText(it.t, L + x, yy);
        if ((r.u || r.s) && !/^\s+$/.test(it.t)) { g.fillRect(L + x, r.u ? yy + it.tk.px * 0.1 : yy - it.tk.px * 0.3, it.w, Math.max(1, it.tk.px * 0.06)); }
        x += it.w;
      }
    }
  }
  async function loadSceneImages(scene) {
    const imgs = {};
    await Promise.all(Object.entries(scene.media || {}).map(async ([id, url]) => {
      try { const im = new Image(); im.src = url; await im.decode(); imgs[id] = im; } catch {}
    }));
    return imgs;
  }
  function drawSlide(g, scene, slide, W, H, imgs) {
    const s = W / scene.w;
    g.save();
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = "#fff"; g.fillRect(0, 0, W, H);
    const bg = slide.bg || {};
    g.beginPath(); g.rect(0, 0, W, H);
    paintFill(g, bg.img ? Object.assign({}, bg) : bg, W, H, imgs);
    for (const it of slide.items || []) {
      const x = it.x * s, y = it.y * s, w = Math.max(0.5, it.w * s), h = Math.max(0.5, it.h * s);
      g.save();
      g.translate(x + w / 2, y + h / 2);
      if (it.rot) g.rotate(it.rot * Math.PI / 180);
      g.save();
      g.scale(it.fh ? -1 : 1, it.fv ? -1 : 1);
      g.translate(-w / 2, -h / 2);
      if (it.t === "pic") {
        const kind = geomPath(g, it.geom, w, h);
        g.save(); if (kind === "shape") g.clip();
        if (imgs[it.m]) drawImageCropped(g, imgs[it.m], it.crop, 0, 0, w, h);
        g.restore();
        if (it.ln) { geomPath(g, it.geom, w, h); g.strokeStyle = it.ln.c; g.lineWidth = Math.max(1, it.ln.w * s); g.stroke(); }
      } else if (it.t === "sp") {
        const kind = geomPath(g, it.geom, w, h);
        if (kind === "shape" && it.fill) paintFill(g, it.fill, w, h, imgs);
        if (it.ln) {
          g.strokeStyle = it.ln.c; g.lineWidth = Math.max(1, it.ln.w * s);
          if (it.ln.dash) g.setLineDash([g.lineWidth * 4, g.lineWidth * 3]);
          g.stroke(); g.setLineDash([]);
        }
      } else if (it.t === "tbl") {
        const tw = (it.cols || []).reduce((a, c) => a + c, 0) || it.w, th = (it.rows || []).reduce((a, r) => a + r.h, 0) || it.h;
        const kx = w / (tw * s), ky = Math.max(1, h / (th * s));
        let yy = 0;
        for (const row of it.rows || []) {
          const rh = row.h * s * ky;
          let xx = 0, ci = 0;
          for (const cell of row.cells || []) {
            const span = Math.max(1, cell.span || 1);
            let cw = 0; for (let k = 0; k < span; k++) cw += (it.cols[ci + k] || 0) * s * kx;
            if (!cell.skip) {
              g.beginPath(); g.rect(xx, yy, cw, rh);
              if (cell.fill) { g.fillStyle = cell.fill; g.fill(); }
              g.strokeStyle = "rgba(255,255,255,0.9)"; g.lineWidth = Math.max(1, 12700 * s); g.stroke();
              if (cell.tx) { g.save(); g.translate(xx, yy); drawText(g, cell.tx, cw, rh, s); g.restore(); }
            }
            xx += cell.skip ? (it.cols[ci] || 0) * s * kx : cw; ci += cell.skip ? 1 : span;
          }
          yy += rh;
        }
      }
      g.restore();
      // text: rotated with the shape, never mirrored (PowerPoint keeps a flipped shape's text readable)
      if (it.tx && it.t === "sp") { g.translate(-w / 2, -h / 2); drawText(g, it.tx, w, h, s); }
      g.restore();
    }
    g.restore();
  }

  // ---- sources: PDF (pdf.js) and .pptx (scene) -------------------------------------------------------------------------
  let pdfjsMod = null;
  async function pdfjs() {
    if (pdfjsMod) return pdfjsMod;
    try { pdfjsMod = await import("/assets/vendor/pdfjs/pdf.min.mjs"); }
    catch { throw new Error("PDF decks need pdf.js, which is missing from this KASTR (run vendor-pdfjs.py) -- save the deck as .pptx meanwhile"); }
    pdfjsMod.GlobalWorkerOptions.workerSrc = "/assets/vendor/pdfjs/pdf.worker.min.mjs";
    return pdfjsMod;
  }
  async function openSource(file, onStep) {
    const name = file.name || "deck";
    const ext = (name.split(".").pop() || "").toLowerCase();
    if (ext === "pdf" || file.type === "application/pdf") {
      onStep("Opening the PDF…");
      const lib = await pdfjs();
      const doc = await lib.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
      const p1 = await doc.getPage(1);
      const vp = p1.getViewport({ scale: 1 });
      return {
        kind: "pdf", name, n: doc.numPages, ar: vp.width / vp.height, notes: new Array(doc.numPages).fill(""), warnings: [],
        async render(i) {
          const page = await doc.getPage(i + 1);
          const v0 = page.getViewport({ scale: 1 });
          const v = page.getViewport({ scale: STILL_W / v0.width });
          const cv = document.createElement("canvas"); cv.width = Math.round(v.width); cv.height = Math.round(v.height);
          const g = cv.getContext("2d", { alpha: false }); g.fillStyle = "#fff"; g.fillRect(0, 0, cv.width, cv.height);
          await page.render({ canvasContext: g, viewport: v, canvas: cv }).promise;
          return cv;
        },
        close() { try { doc.destroy(); } catch {} },
      };
    }
    if (["pptx", "ppsx", "potx", "pptm", "ppsm"].includes(ext)) {
      onStep("Reading the slides…");
      let r;
      try { r = await fetch("/api/pres/convert", { method: "POST", headers: { "X-Kastr-Name": encodeURIComponent(name) }, body: file }); }
      catch (e) {   // 0.21.86: was a bare "Failed to fetch" (Kenton) -- the connection to this computer's KASTR broke mid-send
        console.warn("KASTR pres: convert upload failed", e);
        throw new Error("Lost the connection to KASTR while sending " + name + " — if KASTR just updated or restarted, try again");
      }
      const sc = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(sc.error || ("conversion failed (" + r.status + ")"));
      const shown = sc.slides.filter((s) => !s.hidden);
      const vids = deckVideos(sc, shown);   // 0.21.87
      if (sc.kind === "images") {   // PowerPoint drew them (this computer has PowerPoint): exact slides
        let released = false;
        const release = () => { if (released) return; released = true; vids.ready.finally(() => fetch("/api/pres/conv/" + sc.job + "/done", { method: "POST" }).catch(() => {})); };
        return {
          kind: "pptx", via: "powerpoint", name, n: shown.length, ar: sc.w / sc.h, notes: shown.map((s) => s.notes || ""), warnings: sc.warnings || [],
          videos: vids.per, videoFile: vids.file,
          async render(i) {
            const im = new Image(); im.src = shown[i].img; await im.decode();
            const cv = document.createElement("canvas"); cv.width = STILL_W; cv.height = Math.round(STILL_W * sc.h / sc.w);
            cv.getContext("2d", { alpha: false }).drawImage(im, 0, 0, cv.width, cv.height);
            return cv;
          },
          release, close: release,
        };
      }
      const imgs = await loadSceneImages(sc);
      if (sc.job) vids.ready.finally(() => fetch("/api/pres/conv/" + sc.job + "/done", { method: "POST" }).catch(() => {}));   // 0.21.87: the videos are in this page now
      return {
        kind: "pptx", via: "kastr", name, n: shown.length, ar: sc.w / sc.h, notes: shown.map((s) => s.notes || ""), warnings: sc.warnings || [],
        videos: vids.per, videoFile: vids.file,
        async render(i) {
          const cv = document.createElement("canvas"); cv.width = STILL_W; cv.height = Math.round(STILL_W * sc.h / sc.w);
          drawSlide(cv.getContext("2d", { alpha: false }), sc, shown[i], cv.width, cv.height, imgs);
          return cv;
        },
        close() {},
      };
    }
    if (["ppt", "pps", "key", "odp"].includes(ext)) throw new Error("Save this deck as PowerPoint (.pptx) or PDF first — KASTR reads .pptx and PDF");
    if (["doc", "docx", "odt", "rtf"].includes(ext)) throw new Error("Documents: save it as PDF (File › Save as › PDF) and present the PDF — pages show one at a time");
    throw new Error("KASTR presents PowerPoint (.pptx) and PDF files");
  }
  // 0.21.87: the deck's embedded videos -- pulled into this page right after the conversion (never to the relay host's
  // slide store; the converting KASTR drops its copy once they are here). Boxes become fractions of the slide.
  function deckVideos(sc, shown) {
    const files = sc.videos || {}, got = new Map(), ids = Object.keys(files);
    const per = shown.map((s) => (s.videos || []).map((v) => (v.id
      ? { id: v.id, kind: v.kind === "audio" ? "audio" : "video", x: v.x / sc.w, y: v.y / sc.h, w: v.w / sc.w, h: v.h / sc.h, auto: !!v.auto, delay: Math.max(0, Math.min(60000, Number(v.delay) || 0)),
          loop: !!v.loop, vol: v.vol == null ? 1 : Math.max(0, Math.min(1, Number(v.vol))), name: String(v.name || "") }
      : { linked: String(v.linked || "video"), kind: v.kind === "audio" ? "audio" : "video" })));
    const ready = Promise.all(ids.map(async (id) => {
      const f = files[id];
      try {
        const r = await fetch(f.url, { cache: "no-store" });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const b = await r.blob();
        got.set(id, new File([b], f.name || id + (f.ext || ".mp4"), { type: f.type || b.type || "video/mp4" }));
      } catch (e) { console.warn("KASTR pres: video " + id, e); got.set(id, null); }
    }));
    return { per, ready, file: async (id) => { await ready; return got.get(id) || null; } };
  }
  const toWebp = (cv) => new Promise((res, rej) => cv.toBlob((b) => (b ? res(b) : rej(new Error("encode"))), "image/webp", 0.92));

  // ---- the presenter (authority) ------------------------------------------------------------------------------------
  let mine = null;
  async function startFromFile(file) {
    if (!subtle) { toast("Presentations need a secure page (https or this computer's KASTR).", 6000, "warn"); return; }
    if (mine) { toast("You are already presenting " + mine.name + " — end it first.", 5000, "warn"); return; }
    const c = ctx();
    if (!c || !c.joined) { toast("Join a room first, then share a presentation.", 5000, "warn"); return; }
    const t0 = performance.now();
    view.open({ preparing: "Opening " + (file.name || "the deck") + "…" });
    let src;
    try { src = await openSource(file, (msg) => view.prep(msg)); }
    catch (e) { view.close(); toast(String(e.message || e), 8000, "warn"); return; }
    if (!src.n) { view.close(); toast("That deck has no slides to show.", 5000, "warn"); return; }
    const base = relayBase();
    let deck;
    try {
      const r = await fetch(base + "/api/pres/new", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ room: c.channel, name: src.name, n: src.n }) });
      deck = await r.json();
      if (!r.ok || !deck.id) throw new Error(deck.error || r.status);
    } catch (e) { src.close(); view.close(); toast("The relay host cannot hold the slides: " + (e.message || e), 7000, "warn"); return; }
    const K = crypto.getRandomValues(new Uint8Array(32));
    const keys = await Promise.all(Array.from({ length: src.n }, (_, i) => hkdf(K, "slide/" + i)));
    const me = await myKeys();
    const rtEnc = deck.rtoken ? b64(await seal(await hkdf(K, "read"), enc.encode(deck.rtoken))) : "";
    mine = {
      id: deck.id, token: deck.token, rtEnc, liveIdx: 0, liveChain: Promise.resolve(), via: src.via || src.kind, base, room: c.channel, name: src.name, kind: src.kind, n: src.n, ar: src.ar, src, K, keys,
      notesKey: await hkdf(K, "notes"), notes: src.notes.slice(), nv: 1,
      blobs: new Array(src.n).fill(null), up: new Array(src.n).fill(false), busy: [], rendering: null, want: [],
      idx: 0, ver: 1, by: myPerson(), blank: null, t0: Date.now(), bs: new Map(), lastSeq: new Map(), share: null, pk: me.pub,
      warnings: src.warnings || [], startedMs: 0, pubSeq: 0, told: 0, vids: new Map(),   // 0.21.87: + the videos playing on the live slide
    };
    T("start", { id: mine.id, n: mine.n, kind: mine.kind });
    modeInit(mine);   // 0.21.89: Standout when my camera is on, else Content only
    view.prep("Preparing slide 1 of " + mine.n + "…");
    try { await ensureSlide(0); } catch (e) { endMine("prep failed"); toast("Could not prepare the first slide: " + (e.message || e), 7000, "warn"); return; }
    await uploadNotes();
    startShare();
    mine.startedMs = Math.round(performance.now() - t0);
    publish();
    syncVideos();   // 0.21.87: slide 1 may have a video
    ensurePk();
    view.open({ deck: mine.id });
    if (mine.warnings.length) presNote("Some slide content is simplified: " + mine.warnings.slice(0, 2).join("; "), 20000, "warn");   // 0.21.89: never over the picker
    renderRest();
  }
  function ensureSlide(i) {   // render + encrypt + upload slide i (once; callers at the same time share one try)
    const m = mine;
    if (!m || m.up[i]) return Promise.resolve();
    if (!m.busy[i]) m.busy[i] = doSlide(i).finally(() => { m.busy[i] = null; });
    return m.busy[i];
  }
  async function doSlide(i) {
    if (!mine) return;
    if (mine.up[i]) return;
    if (!mine.blobs[i]) {
      const cv = await mine.src.render(i);
      mine.blobs[i] = await toWebp(cv);
      cv.width = cv.height = 1;
    }
    if (!mine.up[i]) {
      const ct = await seal(mine.keys[i], new Uint8Array(await mine.blobs[i].arrayBuffer()));
      const r = await fetch(mine.base + "/api/pres/" + mine.id + "/s" + i + ".bin?token=" + mine.token, { method: "POST", body: ct });
      if (!r.ok) throw new Error("upload " + r.status);
      mine.up[i] = true;
      view.paintStrip();
    }
  }
  async function renderRest() {   // the rest of the deck in the background; a jump renders its slide first
    const m = mine;
    for (;;) {
      if (mine !== m) return;
      let i = m.want.shift();
      if (i == null) { i = m.up.findIndex((u) => !u); if (i < 0) break; }
      try { await ensureSlide(i); } catch (e) { console.warn("KASTR pres: slide " + (i + 1) + " failed", e); await sleep(1000); }
      await sleep(0);
    }
    T("allup", { id: m.id, n: m.n });
    try { m.src.release?.(); } catch {}   // every slide is in memory: PowerPoint's pictures can go
  }
  async function uploadNotes() {
    if (!mine) return;
    const body = enc.encode(JSON.stringify({ v: mine.nv, notes: mine.notes }));
    const ct = await seal(mine.notesKey, body);
    await fetch(mine.base + "/api/pres/" + mine.id + "/notes.bin?token=" + mine.token, { method: "POST", body: ct }).catch(() => {});
  }
  async function stillFor(deckId, i) {   // a bitmap of slide i for whoever may open it
    if (mine && deckId === mine.id) {
      return cacheGet(deckId + "/" + i, async () => {
        if (!mine.blobs[i]) { mine.want.unshift(i); await ensureSlide(i); }
        return createImageBitmap(mine.blobs[i]);
      });
    }
    const bk = backstage.get(deckId);
    if (bk && bk.keys) return cacheGet(deckId + "/" + i, () => bitmapFromCipher(baseFor(bk.rec), deckId, i, bk.keys[i], bk.rt));
    throw new Error("no key for slide " + (i + 1));
  }
  function publish() {
    if (!mine) { stateSet("pres", null); return; }
    const kIdx = mine.keys[mine.idx];
    stateSet("pres", {
      v: 1, id: mine.id, base: mine.base, name: mine.name, kind: mine.kind, n: mine.n, ar: +mine.ar.toFixed(4),
      idx: mine.idx, ver: mine.ver, by: mine.by, blank: mine.blank || "", k: b64(kIdx), t0: mine.t0, pk: mine.pk,
      share: mine.share?.path || "", nv: mine.nv, rt: mine.rtEnc,
      bs: [...mine.bs.entries()].map(([p, b]) => ({ p, n: b.name || "", w: b.w || "" })),
      // 0.21.87: the live slide's videos -- their stream, their spot (fractions of the slide) and how far they are
      vids: [...mine.vids.values()].filter((e) => e.path && e.i === mine.idx).map((e) => ({ v: e.v, p: e.path, i: e.i, x: +e.sv.x.toFixed(5), y: +e.sv.y.toFixed(5),
        w: +e.sv.w.toFixed(5), h: +e.sv.h.toFixed(5), pl: e.pl, t: +e.t.toFixed(2), at: e.at, d: +e.d.toFixed(2), st: e.st, auto: !!e.sv.auto, k: e.sv.kind === "audio" ? "a" : "v" })),   // 0.21.88: k = "a" -- a sound clip: heard, never drawn
      ...modeFields(),   // 0.21.89: the presenter mode, my camera / cut-out, backstage's mic + camera control
    });
    T("publish", { id: mine.id, idx: mine.idx, ver: mine.ver, who: mine.by });
  }
  function goTo(i, by, blank) {
    if (!mine) return;
    const ni = clampI(i, mine.n);
    const nb = blank === undefined ? null : (blank || null);
    if (ni === mine.idx && nb === mine.blank) return;
    mine.idx = ni; mine.blank = nb; mine.ver++; mine.by = by || myPerson();
    if (!mine.up[ni]) mine.want.unshift(ni);
    drawShare();
    view.paint();
    // 0.21.84 (Kenton: "Viewers: LIVE SLIDE ONLY"): the store learns the live slide first (it serves viewers nothing
    // else), then the room hears of the move; moves are told to the store in order, the room gets the newest
    const m = mine, seq = ++m.pubSeq;
    const tell = () => { m.told = Math.max(m.told, seq); if (mine === m && seq === m.pubSeq) publish(); };
    if (ni === m.liveIdx) tell();
    else m.liveChain = m.liveChain.then(() => postLive(m, ni)).then(tell, tell);
    for (const k of [ni + 1, ni + 2]) if (k < mine.n && !mine.up[k]) mine.want.push(k);
    syncVideos();   // 0.21.87: the slide before's video stops; this slide's starts (or waits for Play)
  }
  async function postLive(m, i) {
    const ac = new AbortController(), t = setTimeout(() => ac.abort(), 1500);   // a slow store must not hold the room back long
    try {
      const r = await fetch(m.base + "/api/pres/" + m.id + "/live?token=" + m.token + "&i=" + i, { method: "POST", signal: ac.signal });
      if (r.ok) m.liveIdx = i;
    } catch {} finally { clearTimeout(t); }
  }
  function applyIntent(path, ctl) {
    const who = personOfPath(path);
    const b = mine.bs.get(who);
    if (!b) return;   // only the backstage people the presenter picked
    const last = mine.lastSeq.get(who) || 0;
    if (!(ctl.seq > last)) return;
    mine.lastSeq.set(who, ctl.seq);
    if (ctl.cm !== undefined || (ctl.av && typeof ctl.av === "object")) { applyModeAv(ctl, who); return; }   // 0.21.89: a mode, or my mic / camera
    if (ctl.vid && typeof ctl.vid === "object") { applyVidOp(ctl.vid, who); return; }   // 0.21.87: Play / Pause / seek of the live slide's video
    if (ctl.bv !== mine.ver && mine.by !== who) { T("drop", { id: mine.id, idx: ctl.to, ver: mine.ver, who }); return; }   // somebody else moved first
    T("apply", { id: mine.id, idx: ctl.to, ver: mine.ver + 1, who });
    goTo(ctl.to, who, ctl.blank === undefined ? null : ctl.blank);
  }
  let rewrapT = null;
  function rewrapSoon() { clearTimeout(rewrapT); rewrapT = setTimeout(rewrap, 50); }
  async function rewrap() {   // K for every backstage person whose KASTR published a key
    if (!mine) return;
    let changed = false;
    for (const [who, b] of mine.bs) {
      const path = [...remote.keys()].find((p) => personOfPath(p) === who && remote.get(p)?.pk);
      const pk = path ? remote.get(path).pk : "";
      if (!pk) { if (b.w) { b.w = ""; b.pkUsed = ""; changed = true; } continue; }
      if (b.pkUsed === pk && b.w) continue;
      const wk = await wrapKey(pk, mine.id + "/" + who);
      b.w = b64(await seal(wk, mine.K)); b.pkUsed = pk; changed = true;
    }
    if (changed) { publish(); view.paint(); }
  }
  function setBackstage(who, on) {
    if (!mine || !who) return;
    if (on) mine.bs.set(who, { name: nameOfPerson(who), w: "", pkUsed: "" });
    else mine.bs.delete(who);
    publish(); rewrap(); view.paint();
    T(on ? "bs+" : "bs-", { id: mine.id, who });
  }
  // the share: the live slide as a normal content share (old KASTRs, phones, web, the recorder)
  function startShare() {
    if (!mine || !window.__presShare) return;
    const cv = document.createElement("canvas");
    cv.width = SHARE_W; cv.height = Math.round(SHARE_W / mine.ar / 2) * 2;
    mine.shareCv = cv;
    drawShare();
    try {
      const sh = window.__presShare.start(cv, mine.name, SHARE_FPS);
      mine.share = sh;
      const m = mine;
      m.keep = setInterval(() => {   // a changed pixel = a frame (late joiners get a keyframe); a hidden page pushes it
        if (mine !== m) return;
        const g = cv.getContext("2d"); m.tick = (m.tick || 0) + 1;
        const px = g.getImageData(cv.width - 1, cv.height - 1, 1, 1).data;
        g.fillStyle = "rgb(" + px[0] + "," + px[1] + "," + (px[2] ^ (m.tick & 1)) + ")"; g.fillRect(cv.width - 1, cv.height - 1, 1, 1);
        if (document.visibilityState !== "visible") { try { sh.push(); } catch {} }
        if (!m.share.path) { const p = window.__presShare.path(sh.id); if (p) { m.share.path = p; publish(); } }
      }, 1000 / SHARE_FPS);
    } catch (e) { console.warn("KASTR pres: no share", e); }
  }
  let shareSeq = 0;
  async function drawShare() {
    if (!mine || !mine.shareCv) return;
    const seq = ++shareSeq, m = mine;
    let bmp = null;
    if (!m.blank) { try { bmp = await stillFor(m.id, m.idx); } catch {} }
    if (seq !== shareSeq || mine !== m) return;
    drawContain(m.shareCv, bmp, m.blank, "Slide " + (m.idx + 1));
    if (document.visibilityState !== "visible") { try { m.share?.push(); } catch {} }
  }
  function endMine(why) {
    const m = mine;
    if (!m) return;
    for (const k of [...m.vids.keys()]) stopVid(m, k, "end");   // 0.21.87
    modeEnd(m);   // 0.21.89: the cut-out stops with the presentation
    mine = null;
    clearInterval(m.keep);
    try { if (m.share) window.__presShare.stop(m.share.id); } catch {}
    stateSet("pres", null);
    try { navigator.sendBeacon(m.base + "/api/pres/" + m.id + "/end?token=" + m.token, new Blob([])); } catch {}
    try { m.src.close(); } catch {}
    for (const k of [...stillCache.keys()]) if (k.startsWith(m.id + "/")) stillCache.delete(k);
    T("end", { id: m.id, why });
    view.paint();
  }
  window.addEventListener("pagehide", () => { if (mine) endMine("pagehide"); });

  // ---- 0.21.87: videos on slides (the presenter) --------------------------------------------------------------------------
  // Kenton: "This powerpoint has a video in it, it doesn't appear to be working and I need that to be able to function inside
  // of KASTR." Decided "Play it on the slide" + "Follow the deck": while a slide with an embedded video is live, this page
  // streams the video into the room exactly like Share > Media file (window.__presVideo: the same player, converter, encoder
  // and announce) and every page draws that stream in the video's spot on the slide, with its sound. It starts by itself when
  // the deck says "Start: Automatically", otherwise it waits for Play from the presenter or a backstage person. The slide
  // change stops it; back on the slide it waits again on its poster. Nothing of it is published before its slide is live.
  function vidList(m, i) { return ((m.src.videos || [])[i] || []).filter((v) => v.id); }
  function syncVideos() {
    const m = mine;
    if (!m) return;
    for (const [k, e] of [...m.vids]) if (e.i !== m.idx) stopVid(m, k, "slide changed");
    vidList(m, m.idx).forEach((sv, n) => { const k = m.idx + "/" + n; if (!m.vids.has(k)) startVid(m, k, m.idx, sv); });
  }
  async function startVid(m, k, i, sv) {
    const e = { k, i, v: sv.id, sv, shareId: null, path: "", pl: false, t: 0, at: Date.now(), d: 0, st: false, gone: false, err: "", live0: performance.now() };
    m.vids.set(k, e);
    T("vid-start", { id: m.id, idx: i, who: sv.id, auto: !!sv.auto });
    let file = null;
    try { file = await m.src.videoFile(sv.id); } catch {}
    T("vid-file", { id: m.id, idx: i, who: sv.id, ok: !!file });
    if (e.gone || mine !== m) return;
    if (!file || !window.__presVideo) { e.err = file ? "this KASTR cannot share videos" : "the video could not be read from the deck"; view.paint(); return; }
    let h = null;
    const now = sv.auto && !(sv.delay > 0);   // "Start: Automatically" with a delay starts paused and is played when the delay is up
    try { h = await window.__presVideo.start(file, { label: sv.name || m.name, auto: now, loop: !!sv.loop, vol: sv.vol, audio: sv.kind === "audio" }); }   // + the deck's own volume (PowerPoint's default is 80 %)
    catch (err) { e.err = String(err?.message || err); console.warn("KASTR pres: video", err); }
    if (!h) { view.paint(); return; }
    if (e.gone || mine !== m) { try { window.__presVideo.stop(h.id); } catch {} return; }
    e.shareId = h.id;
    T("vid-share", { id: m.id, idx: i, who: sv.id });
    if (sv.auto && sv.delay > 0) {
      setTimeout(() => { if (!e.gone && mine === m && !e.st) vidCtl(e, "play"); }, Math.max(0, sv.delay - (performance.now() - e.live0)));
    }
    pollVids();
    vidLoop();
  }
  function stopVid(m, k, why) {   // no publish here: the move that stopped it publishes (after the store heard of it)
    const e = m.vids.get(k);
    if (!e) return;
    e.gone = true;
    m.vids.delete(k);
    if (e.shareId != null) { try { window.__presVideo.stop(e.shareId); } catch {} }
    T("vid-stop", { id: m.id, idx: e.i, who: e.v, why });
  }
  function publishVid() {   // a video's state changed: tell the room -- unless a move is still on its way to the store (it publishes then)
    const m = mine;
    if (m && m.told >= m.pubSeq) publish();
  }
  let vidPollT = null;
  function pollVids() { if (!vidPollT) vidPollT = setInterval(vidPoll, 200); }
  function vidPoll() {
    const m = mine;
    if (!m || !m.vids.size) { clearInterval(vidPollT); vidPollT = null; return; }
    let changed = false;
    const now = Date.now();
    for (const e of m.vids.values()) {
      if (e.shareId == null) continue;
      const s = window.__presVideo?.state(e.shareId);
      if (!s) {
        if (!window.__presVideo?.alive(e.shareId)) { e.shareId = null; e.path = ""; e.err = "its share was stopped"; changed = true; }   // removed from its row
        continue;
      }
      if (s.path !== e.path) { e.path = s.path; changed = true; }
      const exp = e.t + (e.pl ? (now - e.at) / 1000 : 0);
      if (s.playing !== e.pl || Math.abs(s.t - exp) > 1 || Math.abs((s.dur || 0) - e.d) > 0.5) { e.pl = s.playing; e.t = s.t; e.at = now; e.d = s.dur || 0; changed = true; }
      if (!e.st && (s.playing || s.t > 0.05)) { e.st = true; changed = true; T("vid-playing", { id: m.id, idx: e.i, who: e.v }); }
    }
    if (changed) { publishVid(); view.paintVid(); }
  }
  function vidCtl(e, op, t) {
    if (!e || e.shareId == null || !window.__presVideo) return false;
    const ok = window.__presVideo.ctl(e.shareId, op, t);
    T("vid-" + op, { id: mine?.id, idx: e.i, who: e.v });
    setTimeout(vidPoll, 60);
    return ok;
  }
  function applyVidOp(op, who) {   // a backstage person's Play / Pause / seek -- only for the video of the slide live NOW
    const e = [...mine.vids.values()].find((x) => x.v === op.v && x.i === op.i && x.i === mine.idx);
    if (!e || !["play", "pause", "seek"].includes(op.op)) { T("drop", { id: mine.id, idx: op.i, ver: mine.ver, who }); return; }
    T("vid-apply", { id: mine.id, idx: e.i, who });
    vidCtl(e, op.op, op.op === "seek" ? Math.max(0, Number(op.t) || 0) : undefined);
  }

  // ---- backstage + viewers -------------------------------------------------------------------------------------------
  const backstage = new Map();   // deck id -> {rec, path, K, keys, notes, nv, seq, opt, optAt}
  let ctlSeq = Math.floor(Date.now() / 1000) % 100000 * 10;
  async function syncBackstage() {
    const me = myPerson();
    const live = new Set();
    for (const [path, r] of remote) {
      const rec = r.pres;
      if (!rec || !rec.id) continue;
      const mineB = (rec.bs || []).find((b) => b.p === me);
      if (!mineB) continue;
      live.add(rec.id);
      let bk = backstage.get(rec.id);
      if (!bk) { bk = { rec, path, K: null, keys: null, notes: null, nv: 0, w: "" }; backstage.set(rec.id, bk); T("bs-seen", { id: rec.id }); }
      bk.rec = rec; bk.path = path;
      if (mineB.w && mineB.w !== bk.w && subtle) {
        try {
          const wk = await wrapKey(rec.pk, rec.id + "/" + me);
          bk.K = await unseal(wk, unb64(mineB.w));
          bk.keys = await Promise.all(Array.from({ length: rec.n }, (_, i) => hkdf(bk.K, "slide/" + i)));
          bk.notesKey = await hkdf(bk.K, "notes");
          bk.rt = rec.rt ? dec.decode(await unseal(await hkdf(bk.K, "read"), unb64(rec.rt))) : "";
          bk.w = mineB.w;
          T("bs-key", { id: rec.id });
          if (!bk.toasted) { bk.toasted = true; toast(nameOfPerson(personOfPath(path)) + " made you backstage for “" + rec.name + "”. Open the presenter view from the pill at the top.", 9000); }
          view.offer();
        } catch (e) { console.warn("KASTR pres: unwrap failed", e); }
      }
      if (bk.K && rec.nv !== bk.nv) {
        bk.nv = rec.nv;
        fetchBlob(baseFor(rec), rec.id, "notes.bin", 10, bk.rt).then((buf) => unseal(bk.notesKey, buf)).then((u8) => { bk.notes = JSON.parse(dec.decode(u8)).notes || []; T("bs-notes", { id: rec.id }); view.paint(); }).catch((e) => console.warn("KASTR pres: notes", e));
      }
    }
    for (const id of [...backstage.keys()]) if (!live.has(id)) { backstage.delete(id); T("bs-gone", { id }); }
  }
  function sendIntent(deckId, to, blank) {
    const bk = backstage.get(deckId);
    if (!bk) return;
    ctlSeq++;
    const ctl = { id: deckId, seq: ctlSeq, bv: bk.rec.ver, to: clampI(to, bk.rec.n), at: Date.now() };
    if (blank !== undefined) ctl.blank = blank || null;
    bk.opt = ctl.to; bk.optBlank = blank === undefined ? null : blank; bk.optAt = Date.now(); bk.optVer = bk.rec.ver;
    stateSet("presCtl", ctl);
    T("intent", { id: deckId, idx: ctl.to, ver: ctl.bv });
    view.paint();
  }
  function sendVidIntent(deckId, vr, op, t) {   // 0.21.87: backstage Play / Pause / seek of the live slide's video (vr = its entry in pres.vids)
    const bk = backstage.get(deckId);
    if (!bk || !vr) return;
    ctlSeq++;
    const ctl = { id: deckId, seq: ctlSeq, bv: bk.rec.ver, to: bk.rec.idx, at: Date.now(), vid: { v: vr.v, i: vr.i, op } };
    if (t != null) ctl.vid.t = +Number(t).toFixed(2);
    stateSet("presCtl", ctl);
    T("vid-intent", { id: deckId, idx: vr.i, ver: ctl.bv, who: op });
  }

  // viewers (and backstage): the sharp live slide over the share's tile
  const overlays = new Map();   // share path -> {cv, key, rec}
  let viewerFetches = [];        // rig: every slide this page fetched as a viewer
  function syncOverlays() {
    const tiles = window.__switcher?.tiles;
    const want = new Map();
    for (const r of remote.values()) if (r.pres && r.pres.share) want.set(r.pres.share, r.pres);
    for (const [path, o] of overlays) {
      const t = tiles && tiles.get(path);
      if (!want.has(path) || !t || !o.cv.isConnected) { try { o.cv.remove(); o.vcv.remove(); o.ccv?.remove(); } catch {} try { o.vBmp?.close(); } catch {} overlays.delete(path); }
    }
    if (!tiles) return;
    for (const [path, rec] of want) {
      const t = tiles.get(path);
      if (!t || !t.pane) continue;
      let o = overlays.get(path);
      if (!o) {
        const cv = document.createElement("canvas");
        cv.className = "presov";
        t.pane.appendChild(cv);
        const vcv = document.createElement("canvas");   // 0.21.87: the slide's video, drawn in its spot over the still
        vcv.className = "presvid";
        t.pane.appendChild(vcv);
        const ccv = document.createElement("canvas");   // 0.21.89: the presenter's camera in the room's presenter mode
        ccv.className = "prescam";
        t.pane.appendChild(ccv);
        o = { cv, vcv, ccv, key: "", rec, vDrawn: 0 };
        overlays.set(path, o);
      }
      o.rec = rec;
      if ((rec.vids || []).length || modeOf(rec) !== "content" || o.ccvOn) vidLoop();   // 0.21.89: + a camera mode
      const key = rec.id + "/" + rec.idx + "/" + (rec.blank || "") + "/" + (fitCanvas(o.cv) ? Math.random() : o.cv.width) + "/" + modeOf(rec) + (modeOf(rec) === "reporter" ? "/" + (rec.rbg || "") : "");
      if (key !== o.key) { o.key = key; paintOverlay(path, o); }
    }
    presCamSync();   // 0.21.89
  }
  async function paintOverlay(path, o) {
    const rec = o.rec, key = o.key;
    let bmp = null;
    if (!rec.blank) {
      const bk = backstage.get(rec.id);
      try {
        if (bk?.keys) bmp = await stillFor(rec.id, rec.idx);
        else {
          // 0.21.84 (Kenton: "Viewers: LIVE SLIDE ONLY"): a viewer holds the live slide and nothing else -- the store
          // serves it only the live slide (uncacheable), and the bitmap of the slide before is dropped right here
          const want = rec.id + "/" + rec.idx;
          if (o.vKey !== want) {
            viewerFetches.push(rec.idx);
            const b = await bitmapFromCipher(baseFor(rec), rec.id, rec.idx, unb64(rec.k));
            if (o.rec.id + "/" + o.rec.idx !== want) { try { b.close(); } catch {} return; }
            try { o.vBmp?.close(); } catch {}
            o.vBmp = b; o.vKey = want;
          }
          bmp = o.vBmp;
        }
      } catch (e) { console.warn("KASTR pres: live slide", e); }
    }
    if (o.key !== key) return;
    drawLaid(o.cv, bmp, rec.blank, modeOf(rec), rec.ar, "", rec.rbg);   // 0.21.89: placed by the room's presenter mode (Content only: as before)
    T("paint", { id: rec.id, idx: rec.idx, ver: rec.ver, who: "overlay", mode: modeOf(rec) });
  }

  // ---- the presenter view (presenter + backstage) ----------------------------------------------------------------------
  const CSS = `
  #presView { position:fixed; inset:0; z-index:85; background:#0b1118; color:#e6edf3; display:none; flex-direction:column;
    font:14px/1.4 'Segoe UI', system-ui, sans-serif; }
  #presView.show { display:flex; }
  #presView .ph { display:flex; align-items:center; gap:12px; padding:8px 14px; border-bottom:1px solid #1f2a36; background:#0f1722; }
  #presView .ph .ttl { font-weight:600; font-size:15px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:40vw; }
  #presView .ph .role { font-size:12px; padding:2px 8px; border-radius:999px; background:#123a52; color:#8fd3ff; }
  #presView .ph .role.bs { background:#3d2a0e; color:#ffcf7a; }
  #presView .ph .sp { flex:1; }
  #presView .ph .clock, #presView .ph .timer { font-variant-numeric:tabular-nums; font-size:15px; }
  #presView .ph .timer { font-size:20px; font-weight:600; color:#fff; }
  #presView button { background:#1a2633; color:#e6edf3; border:1px solid #2c3b4b; border-radius:6px; padding:6px 12px; cursor:pointer; font:inherit;
    height:auto; min-height:0; line-height:1.2; display:inline-flex; align-items:center; justify-content:center; white-space:nowrap; }
  #presView button:hover { background:#223244; }
  #presView button.big { font-size:18px; padding:12px 22px; min-width:120px; }
  #presView button.on { background:#0b5c86; border-color:#1592d1; }
  #presView button.end { background:#5c1d1d; border-color:#8a2b2b; }
  #presView .pb { flex:1; min-height:0; display:grid; grid-template-columns: minmax(0, 3fr) minmax(260px, 2fr); gap:14px; padding:14px; }
  #presView .cur { display:flex; flex-direction:column; min-height:0; gap:8px; }
  #presView .cap { font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:#8aa0b5; display:flex; gap:8px; align-items:center; }
  #presView .cap .live { color:#fff; background:#c62828; padding:1px 7px; border-radius:4px; letter-spacing:.08em; }
  #presView .curwrap { flex:1; min-height:0; position:relative; display:flex; align-items:center; justify-content:center; }
  #presView .cur canvas { display:block; background:#000; border-radius:6px; box-shadow:0 0 0 2px #c62828; }
  #presView .ctl { display:flex; gap:10px; align-items:center; justify-content:center; flex-wrap:wrap; }
  #presView .ctl .num { font-size:18px; font-variant-numeric:tabular-nums; min-width:110px; text-align:center; }
  #presView .side { display:flex; flex-direction:column; gap:10px; min-height:0; }
  #presView .nexts { display:grid; grid-template-columns: 2fr 1fr; gap:8px; }
  #presView .nexts canvas { width:100%; aspect-ratio:16/9; background:#000; border-radius:5px; }
  #presView .notes { flex:1; min-height:80px; overflow:auto; background:#0f1722; border:1px solid #1f2a36; border-radius:6px; padding:10px 14px;
    white-space:pre-wrap; font-size:var(--pnfs, 20px); line-height:1.45; user-select:text; -webkit-user-select:text; }
  #presView .notes.empty { color:#6b7d8f; font-style:italic; }
  #presView textarea.notes { resize:none; color:#e6edf3; font-family:inherit; }
  #presView .nrow { display:flex; gap:6px; align-items:center; }
  #presView .nrow .ncap { display:block; flex:1; }
  #presView .bsbox { border:1px solid #1f2a36; border-radius:6px; padding:8px 10px; background:#0f1722; }
  #presView .bsbox .chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
  #presView .bsbox .chip { display:inline-flex; gap:6px; align-items:center; background:#1a2633; border:1px solid #2c3b4b; border-radius:999px; padding:3px 10px; font-size:13px; }
  #presView .bsbox .chip.off { opacity:.55; }
  #presView .bsbox .chip input { margin:0; }
  #presView .bsbox .chip .st { font-size:11px; color:#8aa0b5; }
  #presView .strip { display:flex; gap:8px; overflow-x:auto; padding:8px 14px 12px; border-top:1px solid #1f2a36; background:#0f1722; }
  #presView .strip .th { flex:none; width:144px; cursor:pointer; text-align:center; font-size:11px; color:#8aa0b5; }
  #presView .strip .th canvas { width:144px; height:81px; display:block; background:#000; border-radius:4px; border:2px solid transparent; }
  #presView .strip .th.cur canvas { border-color:#c62828; }
  #presView .strip .th.next canvas { border-color:#1592d1; }
  #presView .strip .th.wait { opacity:.45; }
  #presView .prep { flex:1; display:flex; align-items:center; justify-content:center; font-size:20px; color:#8aa0b5; }
  #presPill { position:fixed; top:58px; left:50%; transform:translateX(-50%); z-index:84; display:none; gap:8px; align-items:center;
    background:#0f1722; color:#e6edf3; border:1px solid #2c3b4b; border-radius:999px; padding:5px 6px 5px 14px; font:13px 'Segoe UI', system-ui, sans-serif;
    box-shadow:0 6px 20px rgba(0,0,0,.45); }
  #presPill.show { display:flex; }
  #presPill button { background:#0b5c86; color:#fff; border:0; border-radius:999px; padding:5px 12px; cursor:pointer; font:inherit; }
  .pane canvas.presov { position:absolute; inset:0; width:100%; height:100%; z-index:2; pointer-events:none; background:#000; }
  .pane canvas.presvid { position:absolute; inset:0; width:100%; height:100%; z-index:3; pointer-events:none; }
  #presView .cur canvas.vidcv { position:absolute; pointer-events:none; background:transparent; box-shadow:none; border-radius:0; }
  #presView .vbar { display:none; gap:10px; align-items:center; justify-content:center; flex-wrap:wrap; }
  #presView .vbar.show { display:flex; }
  #presView .vbar input[type=range] { width:min(420px, 40vw); }
  #presView .vbar .vtime { font-variant-numeric:tabular-nums; color:#8aa0b5; min-width:96px; }
  #presView .vbar .vnote { color:#ffcf7a; font-size:13px; }
  @media (max-width: 760px) {
    #presView .pb { grid-template-columns: 1fr; overflow:auto; }
    #presView .curwrap { flex:none; }
    #presView .strip { display:none; }
    #presView button.big { flex:1; font-size:22px; padding:16px; }
    #presView .ph { gap:8px; padding:6px 10px; }
    #presView .ph .ttl { max-width:30vw; }
    #presView .ph .clock { display:none; }
    #presView .ctl .num { order:-1; width:100%; }
  }`;
  const view = (() => {
    let root = null, pill = null, deckId = null, prepMsg = "", tickT = null, editing = false, hidden = false;
    let fs = 20; try { fs = Number(localStorage.getItem("kastr.pres.notesSize")) || 20; } catch {}
    const $ = (sel) => root.querySelector(sel);
    function build() {
      if (root) return;
      const st = document.createElement("style"); st.textContent = CSS; document.head.appendChild(st);
      root = document.createElement("div"); root.id = "presView"; root.setAttribute("role", "dialog"); root.setAttribute("aria-label", "Presenter view");
      root.innerHTML = `
        <div class="ph"><span class="ttl"></span><span class="role"></span><span class="sp"></span>
          <span class="timer" title="Time since the presentation started"></span><span class="clock"></span>
          <button type="button" class="hide" title="Back to the room (the presentation keeps going; Esc)">Back to room</button>
          <button type="button" class="end" title="End the presentation for everyone">End</button></div>
        <div class="prep"></div>
        <div class="pb">
          <div class="cur"><div class="cap"><span class="live">LIVE</span><span class="who"></span></div><div class="curwrap"><canvas class="curcv"></canvas><canvas class="vidcv"></canvas></div>
            <div class="ctl"><button type="button" class="big back" title="Previous slide (Left, PageUp, Backspace)">◀ Back</button>
              <span class="num"></span><button type="button" class="big next" title="Next slide (Right, PageDown, Space)">Next ▶</button>
              <button type="button" class="blk" title="Black screen for everyone (B or .)">Black</button><button type="button" class="wht" title="White screen for everyone (W or ,)">White</button></div>
            <div class="vbar"><button type="button" class="vplay" title="Play or pause the video on this slide for everyone">▶ Play video</button>
              <input type="range" class="vseek" min="0" max="1000" value="0" title="The video's position (everyone)"><span class="vtime"></span><span class="vnote"></span></div></div>
          <div class="side"><div class="cap">Next</div><div class="nexts"><canvas class="n1"></canvas><canvas class="n2"></canvas></div>
            <div class="nrow"><span class="cap ncap">Notes — only you<span class="bsn"></span> can see these</span>
              <button type="button" class="fsm" title="Smaller notes">A−</button><button type="button" class="fsp" title="Larger notes">A+</button>
              <button type="button" class="edit" title="Write or change the notes for this slide">Edit</button></div>
            <div class="notes"></div>
            <div class="bsbox"><div class="cap">Backstage — people who see the notes and what is next, and can move the slides</div><div class="chips"></div></div></div>
        </div>
        <div class="strip"></div>`;
      document.body.appendChild(root);
      modeUiBuild(root);   // 0.21.89: the presenter-mode picker + preview (+ backstage's mic / camera)
      pill = document.createElement("div"); pill.id = "presPill";
      pill.innerHTML = `<span class="pt"></span><button type="button">Presenter view</button>`;
      document.body.appendChild(pill);
      pill.querySelector("button").addEventListener("click", () => { hidden = false; open({ deck: pillDeck() }); });
      $(".hide").addEventListener("click", () => { hidden = true; close(); });
      $(".end").addEventListener("click", () => { if (mine && deckId === mine.id) endMine("ended"); close(); });
      $(".next").addEventListener("click", () => step(1));
      $(".back").addEventListener("click", () => step(-1));
      $(".blk").addEventListener("click", () => blank("black"));
      $(".wht").addEventListener("click", () => blank("white"));
      $(".fsm").addEventListener("click", () => setFs(fs - 2));
      $(".fsp").addEventListener("click", () => setFs(fs + 2));
      $(".edit").addEventListener("click", toggleEdit);
      $(".vplay").addEventListener("click", () => vidPress(null));   // 0.21.87: the live slide's video
      $(".vseek").addEventListener("input", () => { $(".vbar").dataset.scrub = "1"; });
      $(".vseek").addEventListener("change", () => { delete $(".vbar").dataset.scrub; const lv = liveVid(); if (lv?.dur) vidPress("seek", Number($(".vseek").value) / 1000 * lv.dur); });
      root.style.setProperty("--pnfs", fs + "px");
      new ResizeObserver(() => paint()).observe(root);
    }
    function setFs(v) { fs = Math.max(12, Math.min(48, v)); root.style.setProperty("--pnfs", fs + "px"); try { localStorage.setItem("kastr.pres.notesSize", String(fs)); } catch {} }
    function deck() {   // {role, rec-like view} for the deck on show
      if (mine && deckId === mine.id) return { role: "presenter", id: mine.id, name: mine.name, n: mine.n, idx: mine.idx, blank: mine.blank, t0: mine.t0, notes: mine.notes, by: mine.by, ver: mine.ver, ar: mine.ar };
      const bk = backstage.get(deckId);
      if (!bk) return null;
      const opt = bk.opt != null && Date.now() - bk.optAt < 1500 && bk.rec.ver === bk.optVer;
      return { role: "backstage", id: bk.rec.id, name: bk.rec.name, n: bk.rec.n, idx: opt ? bk.opt : bk.rec.idx, blank: opt ? bk.optBlank : (bk.rec.blank || null),
               t0: bk.rec.t0, notes: bk.notes, by: bk.rec.by, ver: bk.rec.ver, ar: bk.rec.ar, presenter: nameOfPerson(personOfPath(bk.path)), ready: !!bk.keys };
    }
    function open(o) {
      build();
      if (o.preparing) { deckId = null; prepMsg = o.preparing; }
      else { deckId = o.deck || deckId; prepMsg = ""; }
      hidden = false;
      root.classList.add("show");
      clearInterval(tickT); tickT = setInterval(tick, 500);
      paintAll();
      T("view-open", { id: deckId });
    }
    function prep(msg) { prepMsg = msg; if (root) paintAll(); }
    function close() { if (!root) return; root.classList.remove("show"); clearInterval(tickT); offer(); }
    function isOpen() { return !!root && root.classList.contains("show"); }
    function pillDeck() { if (mine) return mine.id; const f = [...backstage.values()].find((b) => b.keys); return f ? f.rec.id : null; }
    function offer() {   // the pill: presenter / backstage with the view closed
      build();
      const id = pillDeck();
      const show = !!id && !isOpen();
      pill.classList.toggle("show", show);
      if (show) pill.querySelector(".pt").textContent = mine ? "You are presenting “" + mine.name + "”" : "Backstage for “" + (backstage.get(id)?.rec.name || "") + "”";
    }
    function step(d) {
      const v = deck(); if (!v) return;
      const to = clampI(v.idx + d, v.n);
      if (v.role === "presenter") goTo(to, myPerson(), null);
      else sendIntent(v.id, to, null);
    }
    function goto(i) {
      const v = deck(); if (!v) return;
      if (v.role === "presenter") goTo(i, myPerson(), null); else sendIntent(v.id, i, null);
    }
    function blank(kind) {
      const v = deck(); if (!v) return;
      const nb = v.blank === kind ? null : kind;
      if (v.role === "presenter") goTo(v.idx, myPerson(), nb); else sendIntent(v.id, v.idx, nb);
    }
    function toggleEdit() {
      if (!(mine && deckId === mine.id)) return;
      const box = $(".notes");
      if (!editing) {
        editing = true;
        const ta = document.createElement("textarea"); ta.className = "notes"; ta.value = mine.notes[mine.idx] || "";
        ta.dataset.idx = String(mine.idx);
        box.replaceWith(ta); ta.focus(); $(".edit").textContent = "Save";
      } else {
        const ta = root.querySelector("textarea.notes");
        const i = Number(ta.dataset.idx);
        mine.notes[i] = ta.value; mine.nv++;
        uploadNotes().then(() => publish());
        const d = document.createElement("div"); d.className = "notes"; ta.replaceWith(d);
        editing = false; $(".edit").textContent = "Edit"; paintAll();
      }
    }
    function tick() {
      const v = deck();
      if (!v || !root) return;
      const s = Math.max(0, Math.floor((Date.now() - v.t0) / 1000));
      $(".timer").textContent = (s >= 3600 ? Math.floor(s / 3600) + ":" : "") + String(Math.floor(s / 60) % 60).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
      $(".clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      paintVid();
    }
    // ---- 0.21.87: the live slide's video -- Play / Pause / seek for the presenter and backstage, drawn on the live slide
    const fmtT = (s) => { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
    function liveVid() {   // the live slide's video as this page knows it
      const v = deck();
      if (!v) return null;
      if (v.role === "presenter") {
        const e = [...mine.vids.values()].find((x) => x.i === mine.idx);
        const linked = ((mine.src.videos || [])[mine.idx] || []).find((x) => x.linked);
        if (!e) return linked ? { role: v.role, linked: linked.linked, audio: linked.kind === "audio" } : null;
        const s = e.shareId != null ? window.__presVideo?.state(e.shareId) : null;
        return { role: v.role, e, playing: !!s?.playing, t: s ? s.t : 0, dur: s ? s.dur : 0, err: e.err, ready: !!s, audio: e.sv.kind === "audio" };
      }
      const rec = backstage.get(v.id)?.rec;
      const r = rec && rec.idx === v.idx && (rec.vids || []).find((x) => x.i === rec.idx);
      if (!r) return null;
      const t = Math.min(r.d || 1e9, r.t + (r.pl ? Math.max(0, Date.now() - r.at) / 1000 : 0));
      return { role: v.role, r, playing: !!r.pl, t, dur: r.d || 0, ready: true, audio: r.k === "a" };
    }
    function vidPress(op, t) {
      const lv = liveVid();
      if (!lv || lv.linked) return false;
      const o = op || (lv.playing ? "pause" : "play");
      if (lv.role === "presenter") return vidCtl(lv.e, o, t);
      sendVidIntent(deck().id, lv.r, o, t);
      return true;
    }
    function paintVid() {
      if (!root || !isOpen()) return;
      const bar = $(".vbar"), lv = liveVid();
      bar.classList.toggle("show", !!lv);
      if (!lv) return;
      const ctlEls = [$(".vplay"), $(".vseek"), $(".vtime")];
      if (lv.linked) {
        for (const el of ctlEls) el.style.display = "none";
        $(".vnote").textContent = "This slide's " + (lv.audio ? "sound" : "video") + " (" + lv.linked + ") is linked to a file, not embedded in the deck — it cannot play here";
        return;
      }
      for (const el of ctlEls) el.style.display = "";
      $(".vnote").textContent = lv.err ? "Video: " + lv.err : !lv.ready ? "Video: getting ready…" : "";
      $(".vplay").textContent = (lv.playing ? "⏸ Pause " : "▶ Play ") + (lv.audio ? "sound" : "video");   // 0.21.88: + a sound clip
      $(".vplay").disabled = !lv.ready;
      if (!bar.dataset.scrub) $(".vseek").value = lv.dur ? String(Math.round(Math.min(1, lv.t / lv.dur) * 1000)) : "0";
      $(".vtime").textContent = fmtT(lv.t) + " / " + fmtT(lv.dur);
    }
    let vidViewPainted = null;
    function drawVid() {   // the rAF loop's turn for the presenter view's live slide -> true while a video is on it
      if (!root || !isOpen()) return false;
      const v = deck();
      const vc = $(".vidcv"), base = $(".curcv");
      if (!v) { vc.width = vc.width; return false; }
      vc.style.left = base.offsetLeft + "px"; vc.style.top = base.offsetTop + "px";
      vc.style.width = base.offsetWidth + "px"; vc.style.height = base.offsetHeight + "px";
      let items = [], any = false;
      if (v.role === "presenter") {
        const es = [...mine.vids.values()].filter((e) => e.i === mine.idx);
        any = es.length > 0;
        if (!mine.blank) items = es.filter((e) => e.st && e.shareId != null && e.sv.kind !== "audio").map((e) => ({ x: e.sv.x, y: e.sv.y, w: e.sv.w, h: e.sv.h, src: window.__presVideo?.frame(e.shareId) || null }));
      } else {
        const rec = backstage.get(v.id)?.rec;
        const rs = rec && rec.idx === v.idx ? (rec.vids || []).filter((x) => x.i === rec.idx) : [];
        any = rs.length > 0;
        if (!v.blank) items = rs.filter((x) => x.st && x.k !== "a").map((x) => ({ x: x.x, y: x.y, w: x.w, h: x.h, src: window.__presVidFrame?.(x.p) || null }));
      }
      const n = drawVids(vc, v.ar || 16 / 9, items);
      if (n && vidViewPainted !== v.id + "/" + v.idx) { vidViewPainted = v.id + "/" + v.idx; T("vid-paint", { id: v.id, idx: v.idx, who: "view" }); }
      if (!n && !items.length) vidViewPainted = null;
      return any;
    }
    let paintSeq = 0;
    async function paint() {
      offer();
      if (!isOpen()) return;
      const v = deck();
      const seq = ++paintSeq;
      $(".prep").style.display = v ? "none" : "flex";
      $(".pb").style.display = v ? "" : "none";
      $(".strip").style.display = v ? "" : "none";
      if (!v) {
        $(".prep").textContent = prepMsg || (deckId ? "The presentation ended." : "");
        $(".ttl").textContent = prepMsg ? "Preparing the presentation" : "Presentation";
        $(".role").textContent = ""; $(".end").style.display = "none";
        return;
      }
      $(".ttl").textContent = v.name;
      const role = $(".role");
      role.textContent = v.role === "presenter" ? "You are presenting" : "Backstage for " + v.presenter;
      role.classList.toggle("bs", v.role !== "presenter");
      $(".end").style.display = v.role === "presenter" ? "" : "none";
      $(".edit").style.display = v.role === "presenter" && !editing ? "" : (editing ? "" : "none");
      $(".num").textContent = "Slide " + (v.idx + 1) + " of " + v.n;
      $(".who").textContent = v.ver > 1 && v.by && v.by !== myPerson() ? "moved by " + nameOfPerson(v.by) : "";
      $(".blk").classList.toggle("on", v.blank === "black");
      $(".wht").classList.toggle("on", v.blank === "white");
      const bsN = v.role === "presenter" ? [...mine.bs.keys()].map(nameOfPerson) : [];
      $(".bsn").textContent = v.role === "presenter" ? (bsN.length ? " and " + bsN.join(", ") : "") : " and the presenter";
      if (!editing) {
        const nb = $(".notes");
        const txt = v.notes ? (v.notes[v.idx] || "") : null;
        nb.textContent = txt == null ? "Opening the notes…" : txt || (v.role === "presenter" ? "No notes for this slide — Edit to add some (only you and backstage see them)." : "No notes for this slide.");
        nb.classList.toggle("empty", !txt);
      }
      $(".bsbox").style.display = v.role === "presenter" ? "" : "none";
      if (v.role === "presenter") paintBackstage();
      {   // the live slide as large as its box allows, in the deck's own shape
        const wrap = $(".curwrap"), cv = $(".curcv"), r = wrap.getBoundingClientRect();
        const ar = v.ar || 16 / 9, narrow = window.matchMedia("(max-width: 760px)").matches;
        const w = narrow ? r.width : Math.min(r.width, r.height * ar), h = w / ar;
        cv.style.width = Math.floor(w) + "px"; cv.style.height = Math.floor(h) + "px";
        for (const c of root.querySelectorAll(".nexts canvas")) c.style.aspectRatio = String(ar);
      }
      const cvs = [[$(".curcv"), v.idx, v.blank], [$(".n1"), v.idx + 1, null], [$(".n2"), v.idx + 2, null]];
      for (const [cv, i, bl] of cvs) {
        fitCanvas(cv);
        if (i >= v.n) { drawContain(cv, null, null, i === v.n ? "End of the deck" : ""); continue; }
        if (v.role === "backstage" && !v.ready) { drawContain(cv, null, null, "Waiting for the key…"); continue; }
        stillFor(v.id, i).then((b) => { if (seq !== paintSeq) return; drawContain(cv, b, bl, ""); if (cv === cvs[0][0]) T("paint", { id: v.id, idx: i, ver: seq, who: "view" }); })
          .catch(() => drawContain(cv, null, null, "Slide " + (i + 1) + "…"));
      }
      paintStrip();
      paintVid();   // 0.21.87
      modeUiPaint();   // 0.21.89
      vidLoop();
    }
    function paintAll() { paint(); }
    function paintBackstage() {
      const box = $(".bsbox .chips");
      const c = ctx();
      const me = myPerson();
      const people = (c?.people || []).filter((p) => p.host + "/" + (p.op || p.peer) !== me);
      const seen = new Set();
      const chips = [];
      for (const p of people) {
        const who = p.host + "/" + (p.op || p.peer);
        if (seen.has(who)) continue; seen.add(who);
        const path = [...remote.keys()].find((k) => personOfPath(k) === who && remote.get(k)?.pk);
        const capable = !!path;
        const on = mine.bs.has(who);
        const b = mine.bs.get(who);
        const lab = document.createElement("label"); lab.className = "chip" + (capable ? "" : " off");
        lab.title = capable ? (on ? "Backstage: sees the notes and the next slides and can move the slides" : "Make " + (p.name || p.op) + " backstage") : (p.name || p.op || p.host) + "'s KASTR is older than 0.21.84 (or not open) and cannot be backstage";
        const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = on; cb.disabled = !capable && !on; cb.dataset.who = who;
        cb.addEventListener("change", () => setBackstage(who, cb.checked));
        const nm = document.createElement("span"); nm.textContent = p.name || p.op || p.host;
        const stt = document.createElement("span"); stt.className = "st"; stt.textContent = on ? (b?.w ? "✓ ready" : "waiting…") : "";
        lab.append(cb, nm, stt); chips.push(lab);
      }
      if (!chips.length) { const e = document.createElement("span"); e.className = "st"; e.style.color = "#6b7d8f"; e.textContent = "Nobody else is in the room yet."; chips.push(e); }
      const sig = chips.map((c) => c.outerHTML + (c.querySelector("input")?.checked ? "1" : "0")).join("|");
      if (sig === box.dataset.sig) return;
      box.dataset.sig = sig;
      box.replaceChildren(...chips);
    }
    let stripFor = "";
    const thumbDone = new Set();
    function paintStrip() {
      if (!isOpen()) return;
      const v = deck(); if (!v) return;
      const strip = $(".strip");
      if (stripFor !== v.id) {
        stripFor = v.id; thumbDone.clear();
        const els = [];
        for (let i = 0; i < v.n; i++) {
          const d = document.createElement("div"); d.className = "th"; d.dataset.i = String(i);
          const cv = document.createElement("canvas"); cv.width = 288; cv.height = 162;
          const t = document.createElement("div"); t.textContent = String(i + 1);
          d.append(cv, t); d.addEventListener("click", () => goto(i)); els.push(d);
        }
        strip.replaceChildren(...els);
      }
      for (const d of strip.children) {
        const i = Number(d.dataset.i);
        d.classList.toggle("cur", i === v.idx); d.classList.toggle("next", i === v.idx + 1);
        const ready = v.role === "presenter" ? !!mine.blobs[i] : !!v.ready;
        d.classList.toggle("wait", !ready);
        if (ready && !thumbDone.has(v.id + "/" + i)) {
          thumbDone.add(v.id + "/" + i);
          stillFor(v.id, i).then((b) => drawContain(d.firstChild, b, null, "")).catch(() => thumbDone.delete(v.id + "/" + i));
        }
      }
      const cur = strip.children[v.idx];
      if (cur && cur.scrollIntoView && stripFor === v.id && cur.dataset.seen !== "1") { cur.dataset.seen = "1"; }
    }
    function onKey(e) {
      const v = deck();
      if (!v) return;
      const tg = e.target;
      if (tg && (tg.tagName === "INPUT" || tg.tagName === "TEXTAREA" || tg.tagName === "SELECT" || tg.isContentEditable)) return;
      if (tg && tg.tagName === "BUTTON" && (e.key === " " || e.key === "Enter")) return;   // the focused button clicks itself
      const k = e.key;
      const viewOpen = isOpen();
      // clickers send PageDown / PageUp (and B / . for black) -- those work while presenting even with the view closed
      const clicker = k === "PageDown" || k === "PageUp";
      if (!viewOpen && !clicker) return;
      let used = true;
      if (k === "ArrowRight" || k === "ArrowDown" || k === "PageDown" || k === " " || k === "Enter" || k === "n" || k === "N") step(1);
      else if (k === "ArrowLeft" || k === "ArrowUp" || k === "PageUp" || k === "Backspace" || k === "p" || k === "P") step(-1);
      else if (k === "Home") goto(0);
      else if (k === "End") goto(v.n - 1);
      else if (k === "b" || k === "B" || k === ".") blank("black");
      else if (k === "w" || k === "W" || k === ",") blank("white");
      else if (k === "Escape") { hidden = true; close(); }
      else used = false;
      if (used) { e.preventDefault(); e.stopImmediatePropagation(); }
    }
    window.addEventListener("keydown", onKey, true);
    return { open, close, prep, paint: () => paint(), paintStrip: () => paintStrip(), offer: () => offer(), isOpen, deck: () => deck(),
             paintVid: () => paintVid(), drawVid: () => drawVid(), vidPress: (op, t) => vidPress(op, t) };   // 0.21.87
  })();

  // ---- 0.21.87: a slide's video drawn in its spot -- viewers' and backstage's tiles (the hidden stream's newest frame) and
  // the presenter view's live slide; drawn only once it has started (before that the slide's own poster shows) ------------
  let vidRaf = 0;
  function vidLoop() { if (!vidRaf) vidRaf = requestAnimationFrame(vidFrame); }
  function drawVids(cv, ar, items, rectFn) {   // items: {x, y, w, h (fractions of the slide), src} -> how many were drawn
    fitCanvas(cv);
    const g = cv.getContext("2d"), W = cv.width, H = cv.height;
    g.clearRect(0, 0, W, H);
    if (!items.length) return 0;
    const R = rectFn ? rectFn(W, H) : null;   // 0.21.89: the slide's place in the tile's presenter mode
    const sw = R ? R.w : Math.min(W, H * ar), sh = R ? R.h : sw / ar, ox = R ? R.x : (W - sw) / 2, oy = R ? R.y : (H - sh) / 2;
    let n = 0;
    for (const it of items) {
      if (!it.src) continue;
      try { g.drawImage(it.src, ox + it.x * sw, oy + it.y * sh, it.w * sw, it.h * sh); n++; } catch {}
    }
    return n;
  }
  function vidFrame() {
    vidRaf = 0;
    let more = false;
    for (const o of overlays.values()) {
      const rec = o.rec, all = rec.vids || [];
      if (all.length) more = true;
      const live = all.filter((x) => x.i === rec.idx && x.st && x.p && !rec.blank && x.k !== "a");   // a sound clip is heard, not drawn
      const items = live.map((x) => ({ x: x.x, y: x.y, w: x.w, h: x.h, src: window.__presVidFrame?.(x.p) || null }));
      const n = drawVids(o.vcv, rec.ar || 16 / 9, items, slideRectFn(rec));   // 0.21.89: the slide's place in the mode
      if (n) {
        o.vDrawn++; o.vLast = Date.now();
        if (o.vPainted !== rec.id + "/" + rec.idx) { o.vPainted = rec.id + "/" + rec.idx; T("vid-paint", { id: rec.id, idx: rec.idx, who: "overlay" }); }
      } else if (!live.length) o.vPainted = null;
      try { if (camLayer(o)) more = true; } catch (e) { console.warn("KASTR pres: camera layer", e); }   // 0.21.89
    }
    try { if (view.drawVid()) more = true; } catch {}
    try { if (modeUiFrame()) more = true; } catch (e) { console.warn("KASTR pres: mode preview", e); }   // 0.21.89
    if (mine && mine.vids.size) more = true;
    if (more) vidLoop();
  }

  // ---- 0.21.89: PRESENTER MODES -----------------------------------------------------------------------------------------------
  // Kenton: "I would like to add the option to present a power point and also share my video, with options to switch between the
  // different presenter modes. (content only, standout, side-by-side, and reporter)". Decided: the presenter and their backstage
  // people switch (backstage through presCtl, applied only from the people the presenter made backstage); everyone sees the same
  // mode; decks only for now (the layout below is plain geometry, ready for shares later); a deck starts in Standout when the
  // camera is on, else Content only; camera off (or paused) -> Content only until it is back, then the chosen mode again.
  //   Content only  the slide alone (as before)
  //   Standout      the presenter, cut out of their background, in front of the slide's bottom-right corner
  //   Side-by-side  the slide left, the presenter's camera right (a tall tile stacks them)
  //   Reporter      the presenter, cut out, in front of a backdrop; the slide floats over their shoulder, top-left (~58 %)
  // Every page composes its own tile: the sharp still from the store (as before), the slide's video in its spot (moved and scaled
  // with the slide), and the presenter's camera -- their ordinary camera stream (a box), or for Standout / Reporter the cut-out
  // the presenter's page publishes (window.__presCut: colour | mask in one frame), turned back into a transparent person here
  // in WebGL. The presenter's camera tile is not shown a second time beside it (window.__presCamHide). The record (`pres`):
  //   cm   the chosen mode           cme  the mode the room shows (cm, or "content" while the camera is off / paused)
  //   cam  the camera's stream path  cut  the cut-out's path ("" while there is none)   nocut  why there cannot be one
  //   cwhy why the slide shows alone ("off" | "bs": paused by backstage)
  //   av   {m: mic on|muted|none, c: camera on|paused|off, bp: paused by backstage, ok: backstage may control, n / na / nb: the
  //        last backstage change, its time and who}       ack  {p, s, ok, why}: the answer to a backstage request
  // Older KASTRs read none of it: the slide + the presenter's own tile, as before.
  const MODES = ["content", "standout", "sbs", "reporter"];
  const MODE_NAME = { content: "Content only", standout: "Standout", sbs: "Side-by-side", reporter: "Reporter" };
  const MODE_TIP = { content: "The slide alone", standout: "You, cut out of your background, in front of the slide",
                     sbs: "The slide and your camera next to each other", reporter: "You in front of a backdrop, the slide over your shoulder" };
  const modeOk = (m) => MODES.includes(m);
  const modeOf = (rec) => (rec && modeOk(rec.cme) ? rec.cme : "content");   // what the room shows (an older presenter: the slide alone)
  const cutMode = (m) => m === "standout" || m === "reporter";

  // ---- the layout: pure geometry (a tile of W x H px, the slide's shape, the camera picture's shape, a cut-out or a box) -------
  function presLayout(mode, W, H, ar, camAr, cut) {
    ar = ar > 0 ? ar : 16 / 9; camAr = camAr > 0 ? camAr : 16 / 9;
    const contain = (x, y, w, h, a) => { const ww = Math.min(w, h * a), hh = ww / a; return { x: x + (w - ww) / 2, y: y + (h - hh) / 2, w: ww, h: hh }; };
    const L = { mode, slide: contain(0, 0, W, H, ar), cam: null, kind: "", bg: false, under: false, clip: null, radius: 0, stacked: false };
    if (mode === "standout") {
      const s = L.slide;
      if (cut) { const fh = s.h * 0.38, fw = fh * camAr; L.cam = { x: s.x + s.w - fw * 0.78, y: s.y + s.h - fh, w: fw, h: fh }; L.kind = "cut"; L.clip = s; }   // a head-and-shoulders framing -> the person ~25-30 % of the slide's height
      else { const bh = s.h * 0.28, bw = bh * 16 / 9, m = s.h * 0.03; L.cam = { x: s.x + s.w - bw - m, y: s.y + s.h - bh - m, w: bw, h: bh }; L.kind = "box"; L.radius = bh * 0.08; }
    } else if (mode === "sbs") {
      const p = Math.min(W, H) * 0.03, g = p, cA = 3 / 4;
      const side = Math.max(1, Math.min((W - 2 * p - g) / (1 + cA / ar), (H - 2 * p) * ar));
      const stack = Math.max(1, Math.min(W - 2 * p, (H - 2 * p - g) * ar / 1.6));
      if (stack * stack > side * side * 1.25) {   // a tall tile (a phone): the slide on top, the presenter under it
        const sh = stack / ar, ch = sh * 0.6, cw = Math.min(stack, ch * 16 / 9), y0 = (H - (sh + g + ch)) / 2;
        L.slide = { x: (W - stack) / 2, y: y0, w: stack, h: sh };
        L.cam = { x: (W - cw) / 2, y: y0 + sh + g, w: cw, h: ch };
        L.stacked = true;
      } else {
        const sh = side / ar, cw = sh * cA, x0 = (W - (side + g + cw)) / 2, y0 = (H - sh) / 2;
        L.slide = { x: x0, y: y0, w: side, h: sh };
        L.cam = { x: x0 + side + g, y: y0, w: cw, h: sh };
      }
      L.kind = "box"; L.radius = Math.min(L.cam.w, L.cam.h) * 0.05;
    } else if (mode === "reporter") {
      L.bg = true; L.under = true;
      if (H > W * 1.1) {   // a tall tile: the slide across the top, the presenter below it
        const sw = W * 0.9, sh = sw / ar;
        L.slide = { x: (W - sw) / 2, y: H * 0.05, w: sw, h: sh };
        if (cut) { const top = L.slide.y + sh * 0.72, fh = Math.max(1, H - top), fw = fh * camAr; L.cam = { x: (W - fw) / 2, y: H - fh, w: fw, h: fh }; L.kind = "cut"; }
        else { const bw = W * 0.84, bh = bw * 9 / 16; L.cam = { x: (W - bw) / 2, y: Math.min(H - bh - H * 0.04, L.slide.y + sh + H * 0.03), w: bw, h: bh }; L.kind = "box"; L.radius = bh * 0.06; L.under = false; }
      } else {
        const st = contain(0, 0, W, H, 16 / 9), sw = Math.min(st.w * 0.58, st.h * 0.62 * ar);
        L.slide = { x: st.x + st.w * 0.045, y: st.y + st.h * 0.07, w: sw, h: sw / ar };
        if (cut) { const fh = st.h * 0.86, fw = fh * camAr, cx = st.x + st.w * 0.7; L.cam = { x: cx - fw / 2, y: st.y + st.h - fh, w: fw, h: fh }; L.kind = "cut"; }
        else { const bw = st.w * 0.4, bh = bw * 9 / 16; L.cam = { x: st.x + st.w * 0.955 - bw, y: st.y + st.h * 0.93 - bh, w: bw, h: bh }; L.kind = "box"; L.radius = bh * 0.06; }
      }
    }
    return L;
  }
  // Kenton (review of 0.21.89): "Reporter backdrop = an ASI background instead of the navy wall" -- the fourteen built-in ASI
  // backgrounds (assets/bg, as the camera background picker lists them: seven pictures, then seven moving ones drawn by their
  // still). The presenter picks one (`pres.rbg`, an id from this list -- never a URL); every page draws it from its OWN
  // assets. The first is the default. Until the picture has loaded (or for an id this page does not know) the navy wall.
  const REPORTER_BGS = [
    ["elgato-lights", "Elgato lights", "elgato-lights-bg.jpg", "elgato-lights.jpg"],
    ["gray-home-office", "Gray home office", "gray-home-office-bg.jpg", "gray-home-office.jpg"],
    ["light-blue-home-office", "Light blue home office", "light-blue-home-office-bg.jpg", "light-blue-home-office.jpg"],
    ["livingroom-night", "Living room at night", "livingroom-night-bg.jpg", "livingroom-night.jpg"],
    ["office-space", "Office space", "office-space-bg.jpg", "office-space.jpg"],
    ["porch-sunset", "Porch sunset", "porch-sunset-bg.jpg", "porch-sunset.jpg"],
    ["room-morning", "Room in the morning", "room-morning-bg.jpg", "room-morning.jpg"],
    ["clock", "Clock", "clock.jpg", "clock.jpg"],
    ["coffee-shop", "Coffee shop", "coffee-shop.jpg", "coffee-shop.jpg"],
    ["lofi-bedroom", "Lo-fi bedroom", "lofi-bedroom.jpg", "lofi-bedroom.jpg"],
    ["news-room", "News room", "news-room.jpg", "news-room.jpg"],
    ["office", "Office", "office.jpg", "office.jpg"],
    ["rainy-window", "Rainy window", "rainy-window.jpg", "rainy-window.jpg"],
    ["view", "The view", "view.jpg", "view.jpg"],
  ];
  const RBG_DEFAULT = REPORTER_BGS[0][0];
  const rbgOk = (id) => REPORTER_BGS.some((b) => b[0] === id);
  const rbgImgs = new Map();   // id -> {img, ok}
  function rbgImage(id) {
    const b = REPORTER_BGS.find((x) => x[0] === id) || REPORTER_BGS[0];
    let e = rbgImgs.get(b[0]);
    if (!e) {
      e = { img: new Image(), ok: false };
      e.img.decoding = "async";
      e.img.onload = () => { e.ok = true; for (const o of overlays.values()) o.key = ""; T("rbg-loaded", { who: b[0] }); schedule(); };
      e.img.src = "/assets/bg/" + b[2];   // this page's own copy -- never fetched from the presenter
      rbgImgs.set(b[0], e);
    }
    return e.ok && e.img.naturalWidth ? e.img : null;
  }
  function drawBackdrop(g, W, H, rbg) {
    const img = rbgImage(rbg || RBG_DEFAULT);
    if (img) {
      const sc = Math.max(W / img.naturalWidth, H / img.naturalHeight), dw = img.naturalWidth * sc, dh = img.naturalHeight * sc;
      g.imageSmoothingQuality = "high";
      g.drawImage(img, (W - dw) / 2, (H - dh) / 2, dw, dh);
      const sh = g.createLinearGradient(0, 0, 0, H);   // a touch of depth so the slide and the presenter stand off it
      sh.addColorStop(0, "rgba(0,0,0,0.10)"); sh.addColorStop(1, "rgba(0,0,0,0.28)");
      g.fillStyle = sh; g.fillRect(0, 0, W, H);
      return;
    }
    navyBackdrop(g, W, H);
  }
  function navyBackdrop(g, W, H) {   // the stand-in while the picture loads: a deep navy wall with soft light
    const gr = g.createLinearGradient(0, 0, 0, H);
    gr.addColorStop(0, "#13355a"); gr.addColorStop(0.55, "#0b2240"); gr.addColorStop(1, "#06111f");
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    const rg = g.createRadialGradient(W * 0.7, H * 0.45, 0, W * 0.7, H * 0.45, Math.max(W, H) * 0.55);
    rg.addColorStop(0, "rgba(64,150,220,0.38)"); rg.addColorStop(1, "rgba(64,150,220,0)");
    g.fillStyle = rg; g.fillRect(0, 0, W, H);
    g.save(); g.globalAlpha = 0.07; g.fillStyle = "#9fd4ff";
    for (let i = 0; i < 6; i++) { const x = W * (0.08 + i * 0.17); g.beginPath(); g.moveTo(x, 0); g.lineTo(x + W * 0.05, 0); g.lineTo(x - W * 0.1, H); g.lineTo(x - W * 0.15, H); g.closePath(); g.fill(); }
    g.restore();
    g.fillStyle = "rgba(0,0,0,0.28)"; g.fillRect(0, H * 0.86, W, H * 0.14);   // the desk line
  }
  // the still (and backdrop) layer of a tile in a mode; Content only is exactly the old drawing
  function drawLaid(cv, bmp, blank, mode, ar, label, rbg) {
    if (mode === "content") return drawContain(cv, bmp, blank, label || "");
    const g = cv.getContext("2d"), W = cv.width, H = cv.height, L = presLayout(mode, W, H, ar, 16 / 9, true), s = L.slide;
    g.save(); g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = "#000"; g.fillRect(0, 0, W, H);
    if (L.bg) drawBackdrop(g, W, H, rbg);
    g.save();
    if (L.bg) { g.shadowColor = "rgba(0,0,0,0.55)"; g.shadowBlur = Math.max(6, W * 0.02); g.shadowOffsetY = Math.max(2, W * 0.004); }
    g.fillStyle = blank === "white" ? "#fff" : "#000"; g.fillRect(s.x, s.y, s.w, s.h);
    g.restore();
    if (bmp && !blank) { g.imageSmoothingQuality = "high"; g.drawImage(bmp, s.x, s.y, s.w, s.h); }
    else if (!bmp && !blank && label) { g.fillStyle = "#9aa7b4"; g.font = Math.max(11, Math.round(s.h * 0.06)) + "px 'Segoe UI', system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(label, s.x + s.w / 2, s.y + s.h / 2); }
    g.restore();
  }
  function drawBoxCam(g, img, iw, ih, r, rad, mirror) {   // a camera picture cover-cropped into a rounded box
    const a = r.w / r.h, ia = iw / ih;
    let sx = 0, sy = 0, sw = iw, sh = ih;
    if (ia > a) { sw = ih * a; sx = (iw - sw) / 2; } else { sh = iw / a; sy = (ih - sh) / 2; }
    const path = () => { g.beginPath(); if (g.roundRect) g.roundRect(r.x, r.y, r.w, r.h, rad); else g.rect(r.x, r.y, r.w, r.h); };
    g.save(); g.shadowColor = "rgba(0,0,0,0.5)"; g.shadowBlur = Math.max(4, r.h * 0.06); path(); g.fillStyle = "#000"; g.fill(); g.restore();
    g.save(); path(); g.clip();
    if (mirror) { g.translate(r.x * 2 + r.w, 0); g.scale(-1, 1); }
    g.drawImage(img, sx, sy, sw, sh, r.x, r.y, r.w, r.h);
    g.restore();
    g.save(); path(); g.strokeStyle = "rgba(255,255,255,0.75)"; g.lineWidth = Math.max(1, r.h * 0.01); g.stroke(); g.restore();
  }
  // the presenter's picture into a tile's camera layer: src = {kind: "cut" | "box", img, ar, iw, ih} or null (still starting)
  function drawCam(g, L, src, W, H, label) {
    if (!L.cam) return 0;
    g.save();
    if (L.under) { const s = L.slide; g.beginPath(); g.rect(0, 0, W, H); g.rect(s.x, s.y, s.w, s.h); g.clip("evenodd"); }   // the slide floats in front
    if (L.clip) { g.beginPath(); g.rect(L.clip.x, L.clip.y, L.clip.w, L.clip.h); g.clip(); }
    let n = 0;
    if (src && src.kind === "cut" && L.kind === "cut") {
      if (src.mirror) { g.translate(L.cam.x * 2 + L.cam.w, 0); g.scale(-1, 1); }
      g.drawImage(src.img, L.cam.x, L.cam.y, L.cam.w, L.cam.h); n = 1;
    } else if (src && src.kind === "box") { drawBoxCam(g, src.img, src.iw, src.ih, L.cam, L.radius || Math.min(L.cam.w, L.cam.h) * 0.06, !!src.mirror); n = 1; }
    else if (L.kind === "box") {   // the camera is on its way: a quiet placeholder where it will be
      const r = L.cam;
      g.beginPath(); if (g.roundRect) g.roundRect(r.x, r.y, r.w, r.h, L.radius || 8); else g.rect(r.x, r.y, r.w, r.h);
      g.fillStyle = "rgba(20,30,42,0.85)"; g.fill();
      if (label) { g.fillStyle = "#9aa7b4"; g.font = Math.max(10, Math.round(r.h * 0.09)) + "px 'Segoe UI', system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(label, r.x + r.w / 2, r.y + r.h / 2); }
    }
    g.restore();
    return n;
  }
  // ---- the cut-out back into a transparent person (WebGL2: colour = the left half, alpha = the right half's grey) ------------
  function makeUnpacker() {
    const cv = document.createElement("canvas");
    const gl = cv.getContext("webgl2", { premultipliedAlpha: true, alpha: true, preserveDrawingBuffer: true, antialias: false });
    if (!gl) return null;
    const VS = "#version 300 es\nin vec2 p; out vec2 uv; void main(){ uv = p * 0.5 + 0.5; gl_Position = vec4(p, 0., 1.); }";
    const FS = "#version 300 es\nprecision highp float; in vec2 uv; out vec4 o; uniform sampler2D F; uniform float ex;\n"
      + "void main(){ float x = clamp(uv.x * 0.5, ex, 0.5 - ex); float y = 1. - uv.y;\n"
      + "  vec3 c = texture(F, vec2(x, y)).rgb; float a = dot(texture(F, vec2(x + 0.5, y)).rgb, vec3(.299, .587, .114));\n"
      + "  a = smoothstep(0.1, 0.9, a); o = vec4(min(c, vec3(a)), a); }";   // premultiplied (the colour was sent over black)
    const mk = (t, s) => { const sh = gl.createShader(t); gl.shaderSource(sh, s); gl.compileShader(sh); if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh)); return sh; };
    let pr;
    try { pr = gl.createProgram(); gl.attachShader(pr, mk(gl.VERTEX_SHADER, VS)); gl.attachShader(pr, mk(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(pr); if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(pr)); }
    catch (e) { console.warn("KASTR pres: cut-out renderer", e); return null; }
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tex);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
    const loc = gl.getAttribLocation(pr, "p"), uF = gl.getUniformLocation(pr, "F"), uE = gl.getUniformLocation(pr, "ex");
    return {
      cv, last: null, n: 0,
      draw(f, fw, fh) {
        const w = Math.max(1, fw >> 1);
        if (cv.width !== w || cv.height !== fh) { cv.width = w; cv.height = fh; }
        gl.viewport(0, 0, w, fh); gl.useProgram(pr);
        gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
        gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex);
        try { gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, f); } catch { return false; }
        gl.uniform1i(uF, 0); gl.uniform1f(uE, 0.5 / fw);
        gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        this.n++;
        return true;
      },
    };
  }
  let unp = null;
  function unpackCut(f) {
    if (!unp) unp = makeUnpacker() || { failed: true };
    if (unp.failed) return null;
    const fw = f.displayWidth || f.codedWidth || f.width, fh = f.displayHeight || f.codedHeight || f.height;
    if (!fw || !fh) return null;
    if (unp.last !== f) { if (!unp.draw(f, fw, fh)) return null; unp.last = f; }   // one unpack per frame, for every tile that shows it
    return { kind: "cut", img: unp.cv, ar: (fw / 2) / fh };
  }
  // the presenter's picture as this page has it (viewers / backstage): the cut-out for Standout / Reporter while it is coming,
  // else their ordinary camera (a box in the same place -- never nothing while the cut-out starts)
  function camSourceFor(rec, mode) {
    if (cutMode(mode) && rec.cut) {
      let f = null; try { f = window.__presCutFrame?.(rec.cut) || null; } catch {}
      const u = f ? unpackCut(f) : null;
      if (u) return u;
    }
    let f2 = null; try { f2 = rec.cam ? window.__presCamFrame?.(rec.cam) || null : null; } catch {}
    if (!f2) return null;
    const iw = f2.displayWidth || f2.codedWidth || f2.videoWidth || f2.width, ih = f2.displayHeight || f2.codedHeight || f2.videoHeight || f2.height;
    return iw && ih ? { kind: "box", img: f2, iw, ih, ar: iw / ih } : null;
  }
  const camLabel = (rec) => (rec && rec.cme && rec.cme !== "content" ? "Camera starting…" : "");
  // a tile's camera layer, once per animation frame -> true while it shows a camera mode
  function camLayer(o) {
    const rec = o.rec, mode = modeOf(rec);
    if (!o.ccv) return false;
    if (mode === "content") { if (o.ccvOn) { o.ccvOn = false; fitCanvas(o.ccv); o.ccv.getContext("2d").clearRect(0, 0, o.ccv.width, o.ccv.height); o.camPainted = null; } return false; }
    o.ccvOn = true;
    const resized = fitCanvas(o.ccv);
    const g = o.ccv.getContext("2d"), W = o.ccv.width, H = o.ccv.height;
    const src = camSourceFor(rec, mode);
    // a new picture (or a new size / mode) is drawn; the same frame again is not (the loop runs at the display's rate)
    const fk = mode + "/" + rec.ar + "/" + (src ? (src.kind === "cut" ? "c" + (unp ? unp.n : 0) : "b" + (src.img.timestamp ?? Math.random())) : "none/" + (rec.cam || ""));
    if (!resized && fk === o.camFk) return true;
    o.camFk = fk;
    g.clearRect(0, 0, W, H);
    const L = presLayout(mode, W, H, rec.ar, src ? src.ar : 16 / 9, !!(src && src.kind === "cut"));
    const n = drawCam(g, L, src, W, H, camLabel(rec));
    const key = rec.id + "/" + mode + "/" + (src ? src.kind : "");
    if (n && o.camPainted !== key) { o.camPainted = key; T("cam-paint", { id: rec.id, idx: rec.idx, who: "overlay", mode, kind: src.kind }); }
    o.camKind = src ? src.kind : ""; o.camN = (o.camN || 0) + n;
    return true;
  }
  const slideRectFn = (rec) => (W, H) => presLayout(modeOf(rec), W, H, rec.ar, 16 / 9, true).slide;
  // which presenter cameras this page draws inside a presentation tile (not a tile of their own meanwhile) and which cut-outs
  // it subscribes -- only presentations whose tile is here
  let hideSig = "", cutSig = "";
  function presCamSync() {
    const hide = [], cuts = [];
    for (const o of overlays.values()) {
      const r = o.rec, m = modeOf(r);
      if (m === "content" || !r) continue;
      if (r.cam) hide.push(r.cam);
      if (cutMode(m) && r.cut) cuts.push(r.cut);
    }
    // backstage: the preview in my presenter view draws the same pictures
    const hs = hide.sort().join("|"), cs = cuts.sort().join("|");
    if (hs !== hideSig) { hideSig = hs; try { window.__presCamHide?.(hide); } catch {} T("cam-hide", { who: hs }); }
    if (cs !== cutSig) { cutSig = cs; try { window.__presCutWant?.(cuts); } catch {} T("cut-want", { who: cs }); }
  }

  // ---- the presenter: the chosen mode, the camera, the cut-out, backstage's mic / camera control ------------------------------
  function camNow() { try { return window.__presCut?.camInfo?.() || null; } catch { return null; } }
  function modeInit(m) {
    const ci = camNow();
    m.cm = ci && ci.live ? "standout" : "content";   // Kenton: Standout when the camera is on, else Content only
    m.avOk = true; m.avBp = false; m.avNote = null; m.ack = null;
    m.rbg = RBG_DEFAULT;   // Reporter's backdrop: the first ASI background
    m.ms = { eff: "content", cam: "", cut: "", nocut: "", why: "", mic: "none", camSt: "off", cutOn: false, sig: "", by: "" };
    T("mode", { id: m.id, who: m.cm, why: "start" });
    modeTick();
  }
  function modeFields() {
    const m = mine;
    if (!m || !m.ms) return {};
    const s = m.ms;
    return { cm: m.cm, cme: s.eff, cam: s.cam, cut: s.cut, nocut: s.nocut, cwhy: s.why, rbg: m.rbg || RBG_DEFAULT,
             av: { m: s.mic, c: s.camSt, bp: !!m.avBp, ok: !!m.avOk, n: m.avNote ? m.avNote.t : "", na: m.avNote ? m.avNote.at : 0, nb: m.avNote ? m.avNote.by : "" },
             ack: m.ack || null };
  }
  function modeTick() {
    const m = mine;
    if (!m || !m.ms) return;
    const s = m.ms, ci = camNow(), C = window.__presCut;
    let av = null; try { av = window.__presAV?.state?.() || null; } catch {}
    const live = !!(ci && ci.live);
    if (m.avBp && (!ci || (live && Date.now() - (m.avBpAt || 0) > 4000))) m.avBp = false;   // the camera is back (whoever resumed it), or gone (the pause takes a moment to land)
    const eff = live ? m.cm : "content";
    const wantCut = live && cutMode(eff) && !!C && ci.canCut !== false;
    if (wantCut && !s.cutOn) { s.cutOn = true; try { C.start(); } catch (e) { console.warn("KASTR pres: cut-out", e); } T("cut-start", { id: m.id }); }
    if (!wantCut && s.cutOn) { s.cutOn = false; try { C.stop(); } catch {} T("cut-stop", { id: m.id }); }
    let cs = null; try { cs = s.cutOn ? C.state() : null; } catch {}
    s.eff = eff;
    s.cam = live ? ci.path : "";
    s.cut = cs && cs.ready ? cs.path : "";
    s.nocut = ci && ci.canCut === false ? (ci.why || "this computer cannot cut you out of your background") : !C ? "this KASTR cannot" : "";
    s.why = live ? "" : m.avBp ? "bs" : "off";
    s.mic = av ? av.mic : "none";
    s.camSt = !ci ? "off" : ci.live ? "on" : m.avBp ? "paused" : "off";
    s.hw = !!(av && av.hw);
    const sig = JSON.stringify([m.cm, m.rbg, s.eff, s.cam, s.cut, s.nocut, s.why, s.mic, s.camSt, m.avBp, m.avOk, m.avNote && m.avNote.at, m.ack && m.ack.s]);
    if (sig !== s.sig) {
      const first = !s.sig;
      s.sig = sig;
      if (!first) { T("mode-pub", { id: m.id, who: s.eff }); publishVid(); }
      try { view.paint(); } catch {}
    }
  }
  setInterval(() => { try { modeTick(); } catch (e) { console.warn("KASTR pres: modes", e); } }, 300);
  function modeEnd(m) {
    if (!m || !m.ms) return;
    if (m.ms.cutOn) { m.ms.cutOn = false; try { window.__presCut?.stop(); } catch {} }
    try { window.__presCut?.camVideoStop?.(); } catch {}
  }
  function setMode(cm, by) {   // the presenter's own choice, or an accepted backstage one
    const m = mine;
    if (!m || !modeOk(cm) || !m.ms) return false;
    m.modeBy = by || myPerson();
    if (m.cm === cm) return true;
    m.cm = cm;
    T("mode", { id: m.id, who: cm, by: m.modeBy });
    modeTick();
    return true;
  }
  function avNotice(m, text, by) {
    m.avNote = { t: text, at: Date.now(), by };
    presNote(text, 6000, "event");   // the presenter view's notice line -- or a toast on the main page when the view is closed
  }
  function applyModeAv(ctl, who) {   // a backstage person's mode or mic / camera request (applyIntent checked: backstage, newer seq)
    const m = mine;
    const name = nameOfPerson(who);
    if (ctl.cm !== undefined) {
      if (!modeOk(ctl.cm)) { T("drop", { id: m.id, who }); return; }
      T("mode-apply", { id: m.id, who: ctl.cm, by: who });
      setMode(ctl.cm, who);
      return;
    }
    const op = ctl.av && ctl.av.op;
    const answer = (ok, why) => { m.ack = { p: who, s: ctl.seq, ok, why: why || "" }; T(ok ? "av-apply" : "av-deny", { id: m.id, who: op, by: who, why }); modeTick(); };
    if (!["mute", "unmute", "pause", "resume"].includes(op)) return answer(false, "not a mic or camera request");
    if (!m.avOk) return answer(false, nameOfPerson(myPerson()) + " turned off backstage control of their mic and camera");
    const AV = window.__presAV;
    if (!AV) return answer(false, "this KASTR cannot");
    if (op === "mute" || op === "unmute") {
      const r = AV.mic(op === "mute");
      if (!r || !r.ok) return answer(false, (r && r.why) || "the microphone is not available");
      if (!r.noop) avNotice(m, (op === "mute" ? "Muted by " : "Unmuted by ") + name, who);
      return answer(true);
    }
    const ci = camNow();
    const me = nameOfPerson(myPerson());
    if (!ci) return answer(false, me + "'s camera is off");
    if (op === "pause") {
      if (!ci.live) return answer(true);   // already not sending a picture: nothing to do
      const r = AV.cam(true);
      if (!r || !r.ok) return answer(false, (r && r.why) || "the camera did not pause");
      m.avBp = true; m.avBpAt = Date.now();
      if (!r.noop) avNotice(m, "Video paused by " + name, who);
      return answer(true);
    }
    if (ci.live) return answer(true);   // resume: already on
    if (!m.avBp) return answer(false, me + "'s camera is off");   // backstage resumes only what backstage paused
    const r = AV.cam(false);
    if (!r || !r.ok) return answer(false, (r && r.why) || "the camera did not resume");
    m.avBp = false;
    if (!r.noop) avNotice(m, "Video resumed by " + name, who);
    return answer(true);
  }
  // backstage: the requests (presCtl, like Next / Back)
  function sendModeIntent(deckId, cm) {
    const bk = backstage.get(deckId);
    if (!bk || !modeOk(cm) || !bk.rec.cm) return false;   // a presenter without modes (older KASTR): never asked
    ctlSeq++;
    stateSet("presCtl", { id: deckId, seq: ctlSeq, bv: bk.rec.ver, to: bk.rec.idx, at: Date.now(), cm });
    bk.optCm = cm; bk.optCmAt = Date.now();
    T("mode-intent", { id: deckId, who: cm });
    return true;
  }
  function sendAvIntent(deckId, op) {
    const bk = backstage.get(deckId);
    if (!bk || !bk.rec.av || !["mute", "unmute", "pause", "resume"].includes(op)) return false;
    ctlSeq++;
    stateSet("presCtl", { id: deckId, seq: ctlSeq, bv: bk.rec.ver, to: bk.rec.idx, at: Date.now(), av: { op } });
    bk.avAsk = { op, seq: ctlSeq, at: Date.now() };
    T("av-intent", { id: deckId, who: op });
    return true;
  }

  // ---- the presenter view: the mode picker, a live preview of what the room sees, backstage's mic / camera ---------------
  const ICON = {
    content: '<rect x="1" y="1" width="30" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><rect x="5" y="4" width="22" height="12" rx="1" fill="currentColor" opacity=".55"/>',
    standout: '<rect x="1" y="1" width="30" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><rect x="4" y="4" width="18" height="11" rx="1" fill="currentColor" opacity=".45"/><circle cx="25" cy="11" r="2.6" fill="currentColor"/><path d="M20 19c0-3.4 2.2-5.2 5-5.2s5 1.8 5 5.2z" fill="currentColor"/>',
    sbs: '<rect x="1" y="1" width="30" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><rect x="3.5" y="5" width="16" height="10" rx="1" fill="currentColor" opacity=".45"/><rect x="21" y="5" width="7.5" height="10" rx="1.2" fill="currentColor" opacity=".25"/><circle cx="24.75" cy="9" r="1.7" fill="currentColor"/><path d="M21.6 15c0-2.3 1.4-3.4 3.15-3.4s3.15 1.1 3.15 3.4z" fill="currentColor"/>',
    reporter: '<rect x="1" y="1" width="30" height="18" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><rect x="3" y="3" width="14" height="8.5" rx="1" fill="currentColor" opacity=".55"/><circle cx="22" cy="9.5" r="3.2" fill="currentColor"/><path d="M15 19c0-4.6 3.1-6.8 7-6.8s7 2.2 7 6.8z" fill="currentColor"/>',
  };
  const MODE_CSS = `
  .pane canvas.prescam { position:absolute; inset:0; width:100%; height:100%; z-index:3; pointer-events:none; }
  #presView .modebox { border:1px solid #1f2a36; border-radius:6px; padding:8px 10px; background:#0f1722; display:grid; gap:8px;
    grid-template-columns: minmax(0, 1fr) minmax(130px, 220px); align-items:start; }
  #presView .modebox .mhead { grid-column:1 / -1; display:flex; gap:8px; align-items:center; }
  #presView .modebox .modes { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:6px; }
  #presView .modebox .modes button { flex-direction:column; gap:3px; padding:6px 4px; font-size:12px; min-width:0; }
  #presView .modebox .modes button svg { width:40px; height:25px; display:block; color:#8fd3ff; }
  #presView .modebox .modes button.on { background:#0b5c86; border-color:#1592d1; }
  #presView .modebox .modes button.on svg { color:#fff; }
  #presView .modebox .modes button.eff { box-shadow: inset 0 0 0 1px #ffcf7a; }
  #presView .modebox .pvwrap { position:relative; }
  #presView .modebox canvas.pvcv { width:100%; aspect-ratio:16/9; display:block; background:#000; border-radius:4px; box-shadow:0 0 0 1px #2c3b4b; }
  #presView .modebox .pvtag { position:absolute; left:6px; bottom:5px; font-size:10px; letter-spacing:.05em; text-transform:uppercase; color:#cfe3f3;
    background:rgba(0,0,0,.55); padding:1px 6px; border-radius:3px; pointer-events:none; }
  #presView .modebox .mwhy { grid-column:1 / -1; font-size:13px; color:#ffcf7a; min-height:0; }
  #presView .modebox .mwhy:empty { display:none; }
  #presView .modebox .avrow { grid-column:1 / -1; display:flex; flex-wrap:wrap; gap:8px; align-items:center; font-size:13px; }
  #presView .modebox .avrow:empty { display:none; }
  #presView .modebox .avsw { display:inline-flex; flex-direction:row; gap:6px; align-items:center; cursor:pointer; white-space:nowrap; font-size:13px; color:#e6edf3; margin:0; }
  #presView .modebox .avsw input { display:inline-block; width:auto; height:auto; margin:0; flex:none; }
  #presView .modebox .avnote { color:#8fd3ff; }
  #presView .modebox .avwhy { color:#ffcf7a; flex-basis:100%; }
  #presView .modebox .avwhy:empty { display:none; }
  #presView .modebox .avrow button.off { background:#5c1d1d; border-color:#8a2b2b; }
  #presView .modebox .avrow button:disabled { opacity:.5; cursor:not-allowed; }
  #presView .modebox .rbgs { grid-column:1 / -1; display:flex; flex-wrap:wrap; gap:5px; }
  #presView .modebox .rbgs button { padding:0; width:52px; height:30px; border-radius:4px; overflow:hidden; border:2px solid transparent; background:#000; }
  #presView .modebox .rbgs button img { width:100%; height:100%; object-fit:cover; display:block; pointer-events:none; }
  #presView .modebox .rbgs button.on { border-color:#1592d1; }
  #presView .pvnote { display:flex; gap:10px; align-items:center; padding:6px 14px; font-size:13px; background:#2a2110; color:#ffcf7a; border-bottom:1px solid #4a3a18; }
  #presView .pvnote[hidden] { display:none; }
  #presView .pvnote[data-level="event"] { background:#0f2333; color:#8fd3ff; border-bottom-color:#1d3a52; }
  #presView .pvnote .t { flex:1; }
  #presView .pvnote button { padding:2px 8px; font-size:12px; }
  body:has(#presView.show) #kToast { top:56px; bottom:auto; left:14px; transform:none; max-width:min(52vw, 560px); }   /* the room's other toasts: over the live slide's corner, clear of the picker, preview and controls */
  body:has(#presView.show) #kToast.show { transform:none; }
  @media (max-width: 760px) { #presView .modebox { grid-template-columns: 1fr; } #presView .modebox .modes { grid-template-columns:repeat(4, minmax(0, 1fr)); } }`;
  (() => { const st = document.createElement("style"); st.id = "presModeCss"; st.textContent = MODE_CSS; document.head.appendChild(st); })();
  let mui = null;   // the picker's elements (built into the presenter view once)
  function modeUiBuild(root) {
    if (mui || !root) return;
    const box = document.createElement("div"); box.className = "modebox";
    box.innerHTML = `<div class="mhead cap">Presenter mode — everyone sees the same</div>
      <div class="modes">${MODES.map((k) => `<button type="button" data-mode="${k}" title="${MODE_TIP[k]}"><svg viewBox="0 0 32 20" aria-hidden="true">${ICON[k]}</svg><span>${MODE_NAME[k]}</span></button>`).join("")}</div>
      <div class="pvwrap"><canvas class="pvcv"></canvas><span class="pvtag">What the room sees</span></div>
      <div class="rbgs" title="Reporter's backdrop -- everyone sees the same">${REPORTER_BGS.map((b) => `<button type="button" data-rbg="${b[0]}" title="${b[1]}"><img alt="" src="/assets/bg/${b[3]}" loading="lazy"></button>`).join("")}</div>
      <div class="mwhy"></div><div class="avrow"></div>`;
    const side = root.querySelector(".side");
    if (!side) return;
    side.insertBefore(box, side.firstChild);
    mui = { box, pv: box.querySelector(".pvcv"), why: box.querySelector(".mwhy"), av: box.querySelector(".avrow"), btns: [...box.querySelectorAll(".modes button")], avSig: "", pvAt: 0, still: { key: "", bmp: null } };
    for (const b of mui.btns) b.addEventListener("click", () => window.__pres.mode(b.dataset.mode));
    mui.rbgs = box.querySelector(".rbgs");
    for (const b of mui.rbgs.querySelectorAll("button")) b.addEventListener("click", () => window.__pres.reporterBg(b.dataset.rbg));
    // the presenter view's own notice line, under its top bar (deck warnings, backstage's changes): it never covers the picker
    mui.note = document.createElement("div"); mui.note.className = "pvnote"; mui.note.hidden = true;
    const ph = root.querySelector(".ph");
    if (ph) ph.after(mui.note);
  }
  // what the presenter view's deck shows in modes: {role, rec-like, chosen, eff}
  function modeView() {
    const v = view.deck();
    if (!v) return null;
    if (v.role === "presenter") {
      const s = mine.ms || {};
      return { v, role: "presenter", cm: mine.cm, rbg: mine.rbg, eff: s.eff || "content", why: s.why, nocut: s.nocut, av: modeFields().av, cutOn: !!s.cut, rec: null };
    }
    const bk = backstage.get(v.id);
    const rec = bk && bk.rec;
    if (!rec) return null;
    const opt = bk.optCm && Date.now() - bk.optCmAt < 1500 && rec.cm !== bk.optCm ? bk.optCm : null;
    return { v, role: "backstage", cm: opt || rec.cm || "content", rbg: rec.rbg, eff: modeOf(rec), why: rec.cwhy || "", nocut: rec.nocut || "", av: rec.av || null, cutOn: !!rec.cut, rec, bk, has: !!rec.cm };
  }
  function modeUiPaint() {
    if (!mui) return;
    const mv = modeView();
    mui.box.style.display = mv && (mv.role === "presenter" || mv.has) ? "" : "none";
    if (!mv) return;
    mui.rbgs.style.display = mv.role === "presenter" && mv.cm === "reporter" ? "" : "none";   // Kenton: the presenter picks, shown in Reporter
    for (const b of mui.rbgs.children) b.classList.toggle("on", b.dataset.rbg === (mv.rbg || RBG_DEFAULT));
    for (const b of mui.btns) { b.classList.toggle("on", b.dataset.mode === mv.cm); b.classList.toggle("eff", b.dataset.mode === mv.eff && mv.eff !== mv.cm); }
    const who = mv.role === "presenter" ? "" : nameOfPerson(personOfPath(mv.bk.path));
    let why = "";
    if (mv.cm !== "content" && mv.eff === "content") {
      if (mv.why === "bs") why = (mv.av && mv.av.nb ? "Video paused by " + nameOfPerson(mv.av.nb) : "Video paused by backstage") + " — showing the slide only";
      else why = (mv.role === "presenter" ? "Camera off" : who + "'s camera is off") + " — showing the slide only";
    } else if (cutMode(mv.eff) && mv.nocut) {
      why = (mv.role === "presenter" ? "Your camera cannot be cut out here (" + mv.nocut + ")" : who + "'s camera cannot be cut out") + " — the room sees it in a box";
    }
    if (mui.why.textContent !== why) mui.why.textContent = why;
    paintAvRow(mv, who);
  }
  let noteT = 0;
  function presNote(msg, ms, level) {   // the presenter view's notice line while it is open (never on top of its controls), else a toast
    if (!(mui && mui.note && view.isOpen())) { toast(msg, ms, level); return; }
    const n = mui.note;
    n.dataset.level = level || "event";
    n.replaceChildren();
    const t = document.createElement("span"); t.className = "t"; t.textContent = msg;
    const x = document.createElement("button"); x.type = "button"; x.textContent = "OK"; x.title = "Hide this notice";
    x.addEventListener("click", () => { n.hidden = true; });
    n.append(t, x); n.hidden = false;
    clearTimeout(noteT); noteT = setTimeout(() => { n.hidden = true; }, ms || 8000);
    T("note", { who: level || "event" });
  }
  const ago = (at) => { const s = Math.max(0, Math.round((Date.now() - at) / 1000)); return s < 60 ? s + " s ago" : Math.round(s / 60) + " min ago"; };
  function paintAvRow(mv, who) {
    const row = mui.av, av = mv.av || {};
    if (mv.role === "presenter") {
      const sig = "p|" + (mine.avOk ? 1 : 0) + "|" + (av.n || "") + "|" + Math.floor((Date.now() - (av.na || 0)) / 10000) + "|" + av.m + "|" + av.c;
      if (sig === mui.avSig) return;
      mui.avSig = sig;
      row.replaceChildren();
      // my own mic + camera, here too (the presenter view covers the room's toolbar): they press the toolbar's own buttons
      const tb = (id) => () => { try { document.getElementById(id)?.click(); } catch {} setTimeout(modeTick, 50); };
      const pm = document.createElement("button"); pm.type = "button"; pm.className = "pmic" + (av.m === "on" ? "" : " off");
      pm.textContent = av.m === "on" ? "Mic on" : av.m === "muted" ? "Mic muted" : "No mic"; pm.title = "Your microphone (the same as Mic in the room's toolbar)";
      pm.addEventListener("click", tb("topMicBtn"));
      const pc = document.createElement("button"); pc.type = "button"; pc.className = "pcam" + (av.c === "on" ? "" : " off");
      pc.textContent = av.c === "on" ? "Camera on" : "Camera off"; pc.title = "Your camera (the same as Camera in the room's toolbar)";
      pc.addEventListener("click", tb("topCamBtn"));
      row.append(pm, pc);
      const lab = document.createElement("label"); lab.className = "avsw"; lab.title = "Your backstage people can mute / unmute your mic and pause / resume your video (this presentation only)";
      const cb = document.createElement("input"); cb.type = "checkbox"; cb.className = "avok"; cb.checked = !!mine.avOk;
      cb.addEventListener("change", () => window.__pres.avSwitch(cb.checked));
      lab.append(cb, document.createTextNode("Backstage can control my mic and camera"));
      row.append(lab);
      if (av.n) { const n = document.createElement("span"); n.className = "avnote"; n.textContent = av.n + " · " + ago(av.na); row.append(n); }
      return;
    }
    if (!mv.av) { if (mui.avSig !== "none") { mui.avSig = "none"; row.replaceChildren(); } return; }
    const ask = mv.bk.avAsk && Date.now() - mv.bk.avAsk.at < 4000 ? mv.bk.avAsk : null;
    const ack = mv.rec.ack && mv.rec.ack.p === myPerson() ? mv.rec.ack : null;
    const lastAck = ack && mv.bk.avAsk && ack.s === mv.bk.avAsk.seq ? ack : null;
    const sig = "b|" + JSON.stringify([av, ask && ask.seq, lastAck && [lastAck.s, lastAck.ok, lastAck.why], who]);
    if (sig === mui.avSig) return;
    mui.avSig = sig;
    row.replaceChildren();
    const off = !av.ok, offWhy = who + " turned off backstage control of their mic and camera";
    const mic = document.createElement("button"); mic.type = "button"; mic.className = "avmic";
    const micOn = av.m === "on";
    mic.textContent = av.m === "none" ? "No microphone" : micOn ? "Mic on · Mute" : "Mic muted · Unmute";
    mic.classList.toggle("off", av.m === "muted");
    mic.disabled = off || av.m === "none" || (ask && /mute/.test(ask.op) && !lastAck);
    mic.title = off ? offWhy : av.m === "none" ? who + " has no microphone on" : micOn ? "Mute " + who + "'s microphone (straight away)" : "Unmute " + who + "'s microphone (straight away)";
    mic.addEventListener("click", () => window.__pres.av(micOn ? "mute" : "unmute"));
    const cam = document.createElement("button"); cam.type = "button"; cam.className = "avcam";
    cam.textContent = av.c === "on" ? "Video on · Pause" : av.c === "paused" ? "Video paused · Resume" : "Camera off";
    cam.classList.toggle("off", av.c !== "on");
    cam.disabled = off || av.c === "off" || (ask && /pause|resume/.test(ask.op) && !lastAck);
    cam.title = off ? offWhy : av.c === "off" ? who + "'s camera is off" : av.c === "on" ? "Pause " + who + "'s video (the room sees the slide only)" : "Resume " + who + "'s video";
    cam.addEventListener("click", () => window.__pres.av(av.c === "on" ? "pause" : "resume"));
    row.append(mic, cam);
    const why = document.createElement("span"); why.className = "avwhy";
    why.textContent = off ? offWhy : lastAck && !lastAck.ok ? "Not done: " + lastAck.why : av.c === "off" ? who + "'s camera is off" : "";
    row.append(why);
  }
  // the preview: the same composition the room's tiles draw, small, ~12 a second, while the presenter view is open
  function modeUiFrame() {
    if (!mui || !view.isOpen()) return false;
    const mv = modeView();
    if (!mv || mui.box.style.display === "none") return false;
    const now = performance.now();
    if (now - (mui.paintAt || 0) > 1000) { mui.paintAt = now; modeUiPaint(); }   // the notice's age, backstage's buttons
    if (now - mui.pvAt < 80) return true;
    mui.pvAt = now;
    const cv = mui.pv;
    fitCanvas(cv);
    const W = cv.width, H = cv.height, v = mv.v, ar = v.ar || 16 / 9;
    const key = v.id + "/" + v.idx;
    if (mui.still.key !== key) {
      mui.still.key = key; mui.still.bmp = null;
      stillFor(v.id, v.idx).then((b) => { if (mui.still.key === key) mui.still.bmp = b; }).catch(() => {});
    }
    drawLaid(cv, mui.still.bmp, v.blank, mv.eff, ar, "", mv.rbg);
    const g = cv.getContext("2d");
    // the slide's video in its spot (moved with the slide)
    let items = [];
    if (!v.blank) {
      if (mv.role === "presenter") items = [...mine.vids.values()].filter((e) => e.i === mine.idx && e.st && e.shareId != null && e.sv.kind !== "audio").map((e) => ({ x: e.sv.x, y: e.sv.y, w: e.sv.w, h: e.sv.h, src: window.__presVideo?.frame(e.shareId) || null }));
      else if (mv.rec.idx === v.idx) items = (mv.rec.vids || []).filter((x) => x.i === mv.rec.idx && x.st && x.k !== "a").map((x) => ({ x: x.x, y: x.y, w: x.w, h: x.h, src: window.__presVidFrame?.(x.p) || null }));
    }
    if (items.length) { const R = presLayout(mv.eff, W, H, ar, 16 / 9, true).slide; for (const it of items) if (it.src) { try { g.drawImage(it.src, R.x + it.x * R.w, R.y + it.y * R.h, it.w * R.w, it.h * R.h); } catch {} } }
    if (mv.eff !== "content") {
      let src = null;
      if (mv.role === "presenter") {
        const P = window.__presCut;
        const p = cutMode(mv.eff) && mv.cutOn ? P?.person?.() : null;
        if (p) src = { kind: "cut", img: p.img, ar: p.ar, mirror: p.mirror };
        else { const vid = P?.camVideo?.(); if (vid) src = { kind: "box", img: vid, iw: vid.videoWidth, ih: vid.videoHeight, ar: vid.videoWidth / vid.videoHeight }; }
      } else src = camSourceFor(mv.rec, mv.eff);
      const L = presLayout(mv.eff, W, H, ar, src ? src.ar : 16 / 9, !!(src && src.kind === "cut"));
      if (drawCam(g, L, src, W, H, "Camera starting…") && mui.pvKey !== key + "/" + mv.eff) { mui.pvKey = key + "/" + mv.eff; T("pv-paint", { id: v.id, who: mv.role, mode: mv.eff, kind: src && src.kind }); }
    }
    return true;
  }
  function modeState() {
    const m = mine;
    return {
      mine: m && m.ms ? { cm: m.cm, eff: m.ms.eff, cam: m.ms.cam, cut: m.ms.cut, nocut: m.ms.nocut, why: m.ms.why, mic: m.ms.mic, camSt: m.ms.camSt, avOk: m.avOk, avBp: m.avBp,
                          note: m.avNote, ack: m.ack, cutState: (() => { try { return window.__presCut?.state?.() || null; } catch { return null; } })() } : null,
      tiles: [...overlays.entries()].map(([p, o]) => ({ path: p, mode: modeOf(o.rec), cm: o.rec.cm || null, rbg: o.rec.rbg || null, rbgLoaded: !!(o.rec.rbg && rbgImgs.get(o.rec.rbg)?.ok), cam: o.rec.cam || "", cut: o.rec.cut || "", kind: o.camKind || "", n: o.camN || 0,
                                                        av: o.rec.av || null, ack: o.rec.ack || null })),
      hide: hideSig ? hideSig.split("|") : [], cuts: cutSig ? cutSig.split("|") : [], unpacked: unp && !unp.failed ? unp.n : 0,
      ui: mui ? { shown: mui.box.style.display !== "none", on: (mui.btns.find((b) => b.classList.contains("on")) || {}).dataset?.mode || "", why: mui.why.textContent,
                  av: mui.av.textContent, buttons: [...mui.av.querySelectorAll("button")].map((b) => ({ c: b.className, t: b.textContent, d: b.disabled, title: b.title })) } : null,
    };
  }

  // ---- the loop ----------------------------------------------------------------------------------------------------------
  let schedT = null;
  function schedule() { if (schedT) return; schedT = setTimeout(() => { schedT = null; tickAll(); }, 0); }
  async function tickAll() {
    try { await ensurePk(); } catch {}
    try { await syncBackstage(); } catch (e) { console.warn("KASTR pres", e); }
    try { syncOverlays(); } catch (e) { console.warn("KASTR pres", e); }
    try { view.paint(); } catch {}
  }
  setInterval(() => {
    try { syncOverlays(); } catch {}
    try { if (mine) rewrap(); } catch {}
    if (mine) {   // the presentation belongs to its room and its share: leaving either ends it
      const c = ctx();
      if (!c || !c.joined || c.channel !== mine.room) { endMine("left the room"); toast("The presentation ended (you left the room).", 5000); }
      else if (mine.share && mine.share.id != null && window.__presShare && window.__presShare.alive && !window.__presShare.alive(mine.share.id)) { endMine("share stopped"); toast("The presentation ended (its share was stopped).", 5000); }
    }
  }, 700);
  window.addEventListener("resize", () => { for (const o of overlays.values()) o.key = ""; schedule(); });

  window.__pres = {
    startFromFile,
    end: () => endMine("api"),
    go: (i) => { const v = view.deck(); if (!v) return false; if (v.role === "presenter") goTo(i, myPerson(), null); else sendIntent(v.id, i, null); return true; },   // a viewer has no deck here: false
    next: () => { const v = view.deck(); if (v) window.__pres.go(v.idx + 1); },
    back: () => { const v = view.deck(); if (v) window.__pres.go(v.idx - 1); },
    setBackstage,
    open: () => { const id = mine ? mine.id : [...backstage.values()].find((b) => b.keys)?.rec.id; if (!id) return false; view.open({ deck: id }); return true; },
    close: () => view.close(),
    // 0.21.87 rig: what the video bar's Play / Pause / seek do (presenter: directly; backstage: an intent); a viewer: false
    video: (op, t) => {
      if (mine) {
        const e = [...mine.vids.values()].find((x) => x.i === mine.idx);
        if (!e) return false;
        return vidCtl(e, op || (window.__presVideo?.state(e.shareId)?.playing ? "pause" : "play"), t);
      }
      const bk = [...backstage.values()].find((b) => b.keys);
      const r = bk && (bk.rec.vids || []).find((x) => x.i === bk.rec.idx);
      if (!r) return false;
      sendVidIntent(bk.rec.id, r, op || (r.pl ? "pause" : "play"), t);
      return true;
    },
    // 0.21.89: presenter modes (the presenter sets it; backstage asks; a viewer: false) + backstage's mic / camera requests
    mode: (cm) => {
      if (!modeOk(cm)) return false;
      if (mine) return setMode(cm, myPerson());
      const bk = [...backstage.values()].find((b) => b.keys);
      return bk ? sendModeIntent(bk.rec.id, cm) : false;
    },
    av: (op) => { if (mine) return false; const bk = [...backstage.values()].find((b) => b.keys); return bk ? sendAvIntent(bk.rec.id, op) : false; },
    avSwitch: (on) => { if (!mine || !mine.ms) return false; mine.avOk = !!on; T("av-switch", { id: mine.id, who: on ? "on" : "off" }); modeTick(); return true; },
    reporterBg: (id) => { if (!mine || !mine.ms || !rbgOk(id)) return false; mine.rbg = id; T("rbg", { id: mine.id, who: id }); modeTick(); return true; },   // the presenter only
    reporterBgs: () => REPORTER_BGS.map((b) => b[0]),
    modes: () => modeState(),
    layout: presLayout,   // rig: the geometry alone
    trace,
    state: () => ({
      me: myPerson(),
      mine: mine ? { id: mine.id, name: mine.name, kind: mine.kind, via: mine.via, n: mine.n, idx: mine.idx, ver: mine.ver, by: mine.by, blank: mine.blank,
                     up: mine.up.filter(Boolean).length, share: mine.share?.path || "", shareId: mine.share ? mine.share.id : null, bs: [...mine.bs.entries()].map(([p, b]) => ({ p, ready: !!b.w })),
                     startedMs: mine.startedMs, warnings: mine.warnings } : null,
      backstage: [...backstage.values()].map((b) => ({ id: b.rec.id, idx: b.rec.idx, ver: b.rec.ver, key: !!b.keys, rt: !!b.rt, notes: b.notes ? b.notes.length : null })),
      viewerHeld: [...overlays.values()].filter((o) => o.vKey).map((o) => o.vKey),   // what a viewer keeps: the live slide only
      seen: [...remote.entries()].filter(([, r]) => r.pres).map(([p, r]) => ({ path: p, id: r.pres.id, idx: r.pres.idx, ver: r.pres.ver, bs: (r.pres.bs || []).map((b) => b.p),
                                                                                vids: (r.pres.vids || []).map((x) => ({ i: x.i, p: x.p, pl: x.pl, st: x.st, t: x.t })) })),
      overlays: [...overlays.entries()].map(([p, o]) => ({ path: p, key: o.key, w: o.cv.width, h: o.cv.height })),
      viewerFetches: viewerFetches.slice(),
      view: view.isOpen() ? (view.deck() || {}).role || "preparing" : "",
      pk: !!pkPublished,
      // 0.21.87: the presenter's slide videos; what each tile drew of a slide's video
      vids: mine ? [...mine.vids.values()].map((e) => ({ k: e.k, i: e.i, v: e.v, auto: !!e.sv.auto, shareId: e.shareId, path: e.path, pl: e.pl, st: e.st, t: e.t, err: e.err })) : [],
      deckVideos: mine ? (mine.src.videos || []).map((l) => l.map((v) => (v.id ? v.id + (v.kind === "audio" ? ":audio" : "") : "linked:" + v.linked))) : null,
      vidDrawn: [...overlays.entries()].map(([p, o]) => ({ path: p, drawn: o.vDrawn || 0, last: o.vLast || 0, painted: o.vPainted || null })),
    }),
    __drawSlide: drawSlide,   // rig: render a scene slide without a room
  };
})();
