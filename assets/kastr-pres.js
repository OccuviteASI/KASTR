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
    view.prep("Preparing slide 1 of " + mine.n + "…");
    try { await ensureSlide(0); } catch (e) { endMine("prep failed"); toast("Could not prepare the first slide: " + (e.message || e), 7000, "warn"); return; }
    await uploadNotes();
    startShare();
    mine.startedMs = Math.round(performance.now() - t0);
    publish();
    syncVideos();   // 0.21.87: slide 1 may have a video
    ensurePk();
    view.open({ deck: mine.id });
    if (mine.warnings.length) toast("Some slide content is simplified: " + mine.warnings.slice(0, 2).join("; "), 9000, "warn");
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
      if (!want.has(path) || !t || !o.cv.isConnected) { try { o.cv.remove(); o.vcv.remove(); } catch {} try { o.vBmp?.close(); } catch {} overlays.delete(path); }
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
        o = { cv, vcv, key: "", rec, vDrawn: 0 };
        overlays.set(path, o);
      }
      o.rec = rec;
      if ((rec.vids || []).length) vidLoop();
      const key = rec.id + "/" + rec.idx + "/" + (rec.blank || "") + "/" + (fitCanvas(o.cv) ? Math.random() : o.cv.width);
      if (key !== o.key) { o.key = key; paintOverlay(path, o); }
    }
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
    drawContain(o.cv, bmp, rec.blank, "");
    T("paint", { id: rec.id, idx: rec.idx, ver: rec.ver, who: "overlay" });
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
  function drawVids(cv, ar, items) {   // items: {x, y, w, h (fractions of the slide), src} -> how many were drawn
    fitCanvas(cv);
    const g = cv.getContext("2d"), W = cv.width, H = cv.height;
    g.clearRect(0, 0, W, H);
    if (!items.length) return 0;
    const sw = Math.min(W, H * ar), sh = sw / ar, ox = (W - sw) / 2, oy = (H - sh) / 2;
    let n = 0;
    for (const it of items) {
      if (!it.src) continue;
      try { g.drawImage(it.src, ox + it.x * sw, oy + it.y * sh, it.w * sw, it.h * sh); n++; } catch {}
    }
    return n;
  }
  // a picture that stops while the presenter says the video plays: ask for the stream afresh (after 1.5 s, at most every 5 s). Lab
  // 2026-10-26: the player sometimes drops a new file share's video track right after it starts ("group timestamp is below
  // the live edge") and the picture froze ~6 s while the sound went on -- an ordinary Share > Media file does the same.
  function vidWatchdog(o, items) {
    const now = performance.now();
    o.vSeen = o.vSeen || new Map();
    for (const it of items) {
      const ts = it.src ? it.src.timestamp : null;
      let s = o.vSeen.get(it.p);
      if (!s) { s = { ts, at: now, kickAt: 0, kicks: 0 }; o.vSeen.set(it.p, s); }
      if (ts !== s.ts) { s.ts = ts; s.at = now; continue; }
      if (it.pl && now - s.at > 1500 && now - s.kickAt > 5000 && window.__presVidKick?.(it.p)) {
        s.kickAt = now; s.kicks++; s.at = now;
        T("vid-kick", { id: o.rec.id, idx: o.rec.idx, who: "overlay" });
      }
    }
    for (const p of [...o.vSeen.keys()]) if (!items.some((it) => it.p === p)) o.vSeen.delete(p);
  }
  function vidFrame() {
    vidRaf = 0;
    let more = false;
    for (const o of overlays.values()) {
      const rec = o.rec, all = rec.vids || [];
      if (all.length) more = true;
      const live = all.filter((x) => x.i === rec.idx && x.st && x.p && !rec.blank && x.k !== "a");   // a sound clip is heard, not drawn
      const items = live.map((x) => ({ x: x.x, y: x.y, w: x.w, h: x.h, p: x.p, pl: x.pl, src: window.__presVidFrame?.(x.p) || null }));
      vidWatchdog(o, items);
      const n = drawVids(o.vcv, rec.ar || 16 / 9, items);
      if (n) {
        o.vDrawn++; o.vLast = Date.now();
        if (o.vPainted !== rec.id + "/" + rec.idx) { o.vPainted = rec.id + "/" + rec.idx; T("vid-paint", { id: rec.id, idx: rec.idx, who: "overlay" }); }
      } else if (!live.length) o.vPainted = null;
    }
    try { if (view.drawVid()) more = true; } catch {}
    if (mine && mine.vids.size) more = true;
    if (more) vidLoop();
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
