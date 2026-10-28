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
// CO-PRESENTERS (0.21.91): the presenter view has two sections, Presenters and Backstage. Added presenters get K and the deck's
//              write token (both wrapped to their own key, `ps[].w` / `ps[].t`) and the same powers as the main presenter
//              (slides, notes, modes, people, End) -- their requests ride presCtl like backstage's, applied by the OWNER page (the
//              page that publishes `pres`). Hand-over on the spot: `pres.cur` is the presenter presenting now; their camera /
//              cut-out is the one in the slide (each presenter's page publishes its own cut-out only while it is their turn, and
//              its own camera state in room.json `presCo`). The OWNER role passes on: when the owner's record goes (they left or
//              dropped) and the store still holds the deck, the next present presenter re-publishes the deck as owner
//              (`og` + 1); a returning old owner sees the newer record and steps down. Backstage's mic / camera control is per
//              presenter, per backstage person (`presCo.al`), checked on the TARGET presenter's own page. See "CO-PRESENTERS".
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
  const remote = new Map();   // member path -> {pres, ctl, pk, co}
  let pkPublished = "";
  window.__presMember = (path, v) => {
    const me = meDbg().room;
    if (!path || path === me) return;
    if (!v) { remote.delete(path); schedule(); return; }
    const cur = remote.get(path) || {};
    const next = { pres: v.pres && typeof v.pres === "object" ? v.pres : null, ctl: v.presCtl && typeof v.presCtl === "object" ? v.presCtl : null,
                   pk: typeof v.presPk === "string" ? v.presPk : "", co: v.presCo && typeof v.presCo === "object" ? v.presCo : null };   // 0.21.91: + presCo
    remote.set(path, next);
    if (next.co && next.co.end) endSeen(String(next.co.end), path);   // 0.21.91: a presenter ended it (before any hand-over starts)
    if (next.co && next.co.rel) relSeen.set(String(next.co.rel), Date.now());   // 0.21.91: its owner handed it over (left on purpose)
    if (next.ctl) ctlArrived(path, next.ctl);   // 0.21.91: the owner applies intents; any presenter applies mic / camera requests to itself
    if (mine && next.pk !== (cur.pk || "")) rewrapSoon();
    if (next.pres) T("seen", { id: next.pres.id, idx: next.pres.idx, ver: next.pres.ver, who: path });
    if (mine && next.co && personOfPath(path) === mine.cur) { try { modeTick(); } catch {} }   // 0.21.91: the presenter presenting now changed something: the room hears at once
    schedule();
  };
  async function ensurePk() {   // publish my public key once a presentation exists in my room (or I present)
    if (!subtle) return;
    const any = !!mine || [...remote.values()].some((r) => r.pres);
    if (!any) return;
    const k = await myKeys();
    if (pkPublished !== k.pub) { pkPublished = k.pub; stateSet("presPk", k.pub); }
    coPublish();   // 0.21.91: "this KASTR can co-present" (+ my presenter state)
  }
  // 0.21.91: one deck, one record -- the newest owner's (a hand-over re-publishes the same deck id with og + 1 from another page;
  // for a moment the old owner's may still be there). Ties: the lower person key.
  function recBetter(a, b) {   // a newer than b?
    const ga = Number(a.og) || 1, gb = Number(b.og) || 1;
    if (ga !== gb) return ga > gb;
    return String(a.own || "") < String(b.own || "");
  }
  function deckRecs() {   // deck id -> {rec, path}: the winning record of each deck in my room
    const out = new Map();
    for (const [path, r] of remote) {
      const rec = r.pres;
      if (!rec || !rec.id) continue;
      const cur = out.get(rec.id);
      if (!cur || recBetter(rec, cur.rec)) out.set(rec.id, { rec, path });
    }
    return out;
  }
  const coOf = (pk) => { for (const [p, r] of remote) if (r.co && personOfPath(p) === pk) return r.co; return null; };   // a person's presCo
  const pathOfPerson = (pk) => { for (const p of remote.keys()) if (personOfPath(p) === pk) return p; return ""; };
  const canCo = (pk) => { const co = coOf(pk); return !!(co && Number(co.cap) >= 2); };   // their KASTR can co-present (0.21.91+)
  const hereNow = (pk) => pk === myPerson() || !!pathOfPerson(pk);
  // 0.21.91: in the room by its presence (state.json beats, with the room's grace) -- a second, independent sign of life
  const inPresence = (pk) => (ctx()?.people || []).some((x) => x.host + "/" + (x.op || x.peer) === pk);
  const relSeen = new Map();   // deck id -> when its owner said it handed the deck over

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
      // 0.21.91: the presenters (me first), the ownership generation, the presenter presenting now
      ps: [{ p: myPerson(), name: nameOfPerson(myPerson()), w: "", t: "", pkUsed: "" }], og: 1, cur: myPerson(), rt: deck.rtoken || "",
    };
    T("start", { id: mine.id, n: mine.n, kind: mine.kind });
    modeInit(mine);   // 0.21.89: Standout when my camera is on, else Content only
    audienceInit(mine);   // 0.21.91: the audience is muted while I present (until a presenter turns it off)
    askPreset(mine, arguments[1]);   // 0.21.91: a meeting template's audience.ask (startFromFile(file, opts): opts.ask === 0 -> off)
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
    uploadVideos(m).catch((e) => console.warn("KASTR pres: slide videos to the store", e));   // 0.21.91: they go with the deck
  }
  async function uploadNotes() {
    if (!mine) return;
    const body = enc.encode(JSON.stringify({ v: mine.nv, notes: mine.notes }));
    const ct = await seal(mine.notesKey, body);
    await fetch(mine.base + "/api/pres/" + mine.id + "/notes.bin?token=" + mine.token, { method: "POST", body: ct }).catch(() => {});
  }
  async function stillFor(deckId, i) {   // a bitmap of slide i for whoever may open it
    if (mine && deckId === mine.id && mine.adopted) {   // 0.21.91: a deck handed over to me -- its slides come from the store
      const m = mine;
      return cacheGet(deckId + "/" + i, () => bitmapFromCipher(baseFor({ base: m.base }), deckId, i, m.keys[i], m.rt));
    }
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
      idx: mine.idx, ver: mine.ver, by: mine.by, blank: mine.blank || "", k: mine.blank ? "" : b64(kIdx), t0: mine.t0, pk: mine.pk,   // 0.21.91: no key under a blank
      share: mine.share?.path || "", nv: mine.nv, rt: mine.rtEnc,
      bs: [...mine.bs.entries()].map(([p, b]) => ({ p, n: b.name || "", w: b.w || "" })),
      // 0.21.87: the live slide's videos -- their stream, their spot (fractions of the slide) and how far they are
      vids: [...mine.vids.values()].filter((e) => e.path && e.i === mine.idx).map((e) => ({ v: e.v, p: e.path, i: e.i, x: +e.sv.x.toFixed(5), y: +e.sv.y.toFixed(5),
        w: +e.sv.w.toFixed(5), h: +e.sv.h.toFixed(5), pl: e.pl, t: +e.t.toFixed(2), at: e.at, d: +e.d.toFixed(2), st: e.st, auto: !!e.sv.auto, k: e.sv.kind === "audio" ? "a" : "v" })),   // 0.21.88: k = "a" -- a sound clip: heard, never drawn
      ...modeFields(),   // 0.21.89: the presenter mode, my camera / cut-out, backstage's mic + camera control
      // 0.21.91: co-presenters -- the owner (this page's person), the ownership generation, every presenter (main first) with
      // K and the store's write token wrapped to their own key, the presenter presenting now and their name
      own: myPerson(), og: mine.og, cur: mine.cur, cn: nameOfPerson(mine.cur), vs: mine.vs || 0,   // vs: slide videos kept in the store (0.21.91)
      ps: mine.ps.map((x) => ({ p: x.p, n: x.name || nameOfPerson(x.p), w: x.w || "", t: x.t || "" })),
      ...audFields(),   // 0.21.91: am (audience muted), lt (let talk), hx (hands lowered by a presenter)
    });
    T("publish", { id: mine.id, idx: mine.idx, ver: mine.ver, who: mine.by });
  }
  // 0.21.91 (Kenton: "If I use the black/white out option, I want to still see the preview myself, and only hide it for the room.
  // It should stay persistent until I turn it off, not just for that 1 slide."): `blank` undefined = keep the room's Black / White
  // across moves (Next / Back / a click in the strip); only the Black / White buttons change it. While the room sees a blank, the
  // store is not told the slide underneath and the record carries no slide key: a viewer cannot open what the room does not see.
  function goTo(i, by, blank) {
    if (!mine) return;
    const ni = clampI(i, mine.n);
    const nb = blank === undefined ? mine.blank : (blank || null);
    if (ni === mine.idx && nb === mine.blank) return;
    mine.idx = ni; mine.blank = nb; mine.ver++; mine.by = by || myPerson();
    if (!mine.up[ni]) mine.want.unshift(ni);
    drawShare();
    view.paint();
    // 0.21.84 (Kenton: "Viewers: LIVE SLIDE ONLY"): the store learns the live slide first (it serves viewers nothing
    // else), then the room hears of the move; moves are told to the store in order, the room gets the newest
    const m = mine, seq = ++m.pubSeq;
    const tell = () => { m.told = Math.max(m.told, seq); if (mine === m && seq === m.pubSeq) publish(); };
    if (nb || ni === m.liveIdx) tell();   // blanked: the room sees nothing of the slide (the store keeps the slide it last showed)
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
  // 0.21.91: an intent is the requester's last few requests (presCtl.q, oldest first; an older KASTR sends one, at the top
  // level) -- applied in order, each once (seq), so a quick second request never hides the first
  function ctlOps(ctl) {
    const q = Array.isArray(ctl.q) && ctl.q.length ? ctl.q.filter((o) => o && typeof o === "object" && Number.isFinite(o.seq)) : [ctl];
    return q.slice(-8).sort((a, b) => a.seq - b.seq);
  }
  function applyIntent(path, ctl) {
    const who = personOfPath(path), me = myPerson();
    const isB = mine.bs.has(who), isP = who !== me && mine.ps.some((x) => x.p === who);
    if (!isB && !isP) return;   // only the backstage people and the presenters
    const last = mine.lastSeq.get(who) || 0;
    let top = last;
    for (const o of ctlOps(ctl)) {
      if (!(o.seq > last) || o.id !== mine.id) continue;
      top = Math.max(top, o.seq);
      try { applyOp(o, who, isP); } catch (e) { console.warn("KASTR pres: intent", e); }
      if (!mine) return;   // it ended the presentation
    }
    mine.lastSeq.set(who, top);
  }
  function applyOp(ctl, who, isP) {
    if (ctl.pp && typeof ctl.pp === "object") { if (isP) presOp(ctl.pp, who); else T("drop", { id: mine.id, who, why: "not a presenter" }); return; }   // 0.21.91
    if (ctl.cm !== undefined) { if (!modeOk(ctl.cm)) { T("drop", { id: mine.id, who }); return; } T("mode-apply", { id: mine.id, who: ctl.cm, by: who }); setMode(ctl.cm, who); return; }   // 0.21.89: a mode
    if (ctl.av && typeof ctl.av === "object") { if (!ctl.av.to || ctl.av.to === myPerson()) avApply(who, ctl.av.op, ctl.seq); return; }   // my mic / camera (0.21.91: a request to another presenter is theirs)
    if (ctl.vid && typeof ctl.vid === "object") { applyVidOp(ctl.vid, who); return; }   // 0.21.87: Play / Pause / seek of the live slide's video
    if (ctl.to === undefined) return;
    if (ctl.bv !== mine.ver && mine.by !== who) { T("drop", { id: mine.id, idx: ctl.to, ver: mine.ver, who }); return; }   // somebody else moved first
    T("apply", { id: mine.id, idx: ctl.to, ver: mine.ver + 1, who });
    goTo(ctl.to, who, ctl.blank);   // 0.21.91: undefined = the room's blank stays
  }
  let rewrapT = null;
  function rewrapSoon() { clearTimeout(rewrapT); rewrapT = setTimeout(rewrap, 50); }
  async function rewrap() {   // K for every backstage person and presenter whose KASTR published a key (+ the write token for presenters)
    if (!mine) return;
    const m = mine, me = myPerson();
    let changed = false;
    const one = async (who, b, pres) => {
      const path = [...remote.keys()].find((p) => personOfPath(p) === who && remote.get(p)?.pk);
      const pk = path ? remote.get(path).pk : "";
      if (!pk) { if (b.w) { b.w = ""; b.t = ""; b.pkUsed = ""; changed = true; } return; }
      if (b.pkUsed === pk && b.w && (!pres || b.t)) return;
      const wk = await wrapKey(pk, m.id + "/" + who);
      b.w = b64(await seal(wk, m.K)); b.pkUsed = pk; changed = true;
      b.t = pres ? b64(await seal(await hkdf(wk, "write"), enc.encode(m.token))) : "";   // 0.21.91: a presenter can run the deck on
    };
    for (const [who, b] of m.bs) await one(who, b, false);
    for (const x of m.ps) if (x.p !== me) await one(x.p, x, true);
    if (mine !== m) return;
    if (changed) { publish(); view.paint(); }
  }
  // 0.21.91: who is a presenter / backstage (one or the other, never both). The page that runs the deck stays a presenter.
  function setRole(who, r, by) {
    const m = mine, me = myPerson();
    if (!m || !who || typeof who !== "string" || who.length > 160) return false;
    if (who === me && r !== "p") return false;
    const i = m.ps.findIndex((x) => x.p === who);
    if (r === "p") {
      if (i >= 0) return true;
      if (!canCo(who)) return false;   // their KASTR cannot co-present (0.21.90 or older, or not open)
      m.bs.delete(who);
      m.ps.push({ p: who, name: nameOfPerson(who), w: "", t: "", pkUsed: "" });
    } else if (r === "b") {
      if (i >= 0) m.ps.splice(i, 1);
      if (!m.bs.has(who)) m.bs.set(who, { name: nameOfPerson(who), w: "", pkUsed: "" });
    } else {
      if (i >= 0) m.ps.splice(i, 1);
      m.bs.delete(who);
    }
    if (m.cur !== me && !m.ps.some((x) => x.p === m.cur)) m.cur = me;   // the one presenting now left the presenters: back to me
    publish(); rewrap(); view.paint(); modeTick();
    T("role", { id: m.id, who, r: r || "-", by: by || me });
    return true;
  }
  function setBackstage(who, on) { return setRole(who, on ? "b" : "", myPerson()); }
  function setCur(who, by) {   // 0.21.91: "Now presenting" / "Take over"
    const m = mine;
    if (!m || !m.ps.some((x) => x.p === who)) return false;
    if (who !== myPerson() && !canCo(who)) return false;
    if (m.cur === who) return true;
    m.cur = who; m.curGoneAt = 0; m.curBy = by || myPerson(); m.curAt = Date.now();
    T("cur", { id: m.id, who, by: m.curBy });
    modeTick(); publish(); view.paint();
    return true;
  }
  function presOp(pp, who) {   // 0.21.91: a co-presenter's request -- the same powers as mine
    const m = mine, name = nameOfPerson(who);
    switch (pp.op) {
      case "role": setRole(String(pp.p || ""), pp.r === "p" ? "p" : pp.r === "b" ? "b" : "", who); return;
      case "cur": setCur(String(pp.p || ""), who); return;
      case "rbg": if (rbgOk(pp.v)) { m.rbg = pp.v; T("rbg", { id: m.id, who: pp.v, by: who }); modeTick(); } return;
      case "end": T("end-by", { id: m.id, who }); endMine("ended by " + name); toast("“" + m.name + "” was ended by " + name + ".", 6000); return;
      case "note": {
        const i = Number(pp.i);
        if (!Number.isInteger(i) || i < 0 || i >= m.n || typeof pp.c !== "string" || pp.c.length > 40000) return;
        unseal(m.notesKey, unb64(pp.c)).then((u8) => {
          if (mine !== m) return;
          m.notes[i] = dec.decode(u8).slice(0, 20000); m.nv++;
          T("note", { id: m.id, idx: i, who });
          uploadNotes().then(() => publish());
          view.paint();
        }).catch((e) => console.warn("KASTR pres: a note that does not open", e));
        return;
      }
      default: if (!audienceOp(pp, who)) T("drop", { id: m.id, who, why: "op " + pp.op });
    }
  }
  let audienceOp = () => false;   // (audience mute: below)
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
  let endMark = null;   // 0.21.91: {id, at} -- "I ended this deck" (presCo.end), so no co-presenter takes it over
  let relMark = null;   // 0.21.91: {id, at} -- "I handed this deck over" (presCo.rel): a co-presenter takes it at once
  function endMine(why, keep) {   // keep (0.21.91): hand the deck over -- the store keeps it, a co-presenter runs it on
    const m = mine;
    if (!m) return;
    for (const k of [...m.vids.keys()]) stopVid(m, k, "end");   // 0.21.87
    modeEnd(m);   // 0.21.89: the cut-out stops with the presentation
    mine = null;
    clearInterval(m.keep);
    try { if (m.share) window.__presShare.stop(m.share.id); } catch {}
    if (keep) relMark = { id: m.id, at: Date.now() };
    if (!keep) {   // the store first (a co-presenter that looks finds it gone), then the room
      endMark = { id: m.id, at: Date.now() };
      try { navigator.sendBeacon(m.base + "/api/pres/" + m.id + "/end?token=" + m.token, new Blob([])); } catch {}
    }
    stateSet("pres", null);
    coPublish();
    try { m.src?.close(); } catch {}
    for (const k of [...stillCache.keys()]) if (k.startsWith(m.id + "/")) stillCache.delete(k);
    T(keep ? "release" : "end", { id: m.id, why });
    view.paint();
  }
  // 0.21.91: a co-presenter who can run the deck on (holds K + the write token, is here, can co-present)
  const coReady = (m) => !!m && m.ps.some((x) => x.p !== myPerson() && x.w && x.t && hereNow(x.p) && canCo(x.p));
  function leaveMine(why) {   // I leave (the page goes, I left the room): hand over when a co-presenter can take it, else end it
    if (!mine) return false;
    const keep = coReady(mine);
    endMine(why, keep);
    return keep;
  }
  window.addEventListener("pagehide", () => { if (mine) leaveMine("pagehide"); });
  window.__presLeaving = () => { if (mine) leaveMine("left the room"); };   // 0.21.91: the page's Leave / room switch, before its share stops

  // ---- 0.21.87: videos on slides (the presenter) --------------------------------------------------------------------------
  // Kenton: "This powerpoint has a video in it, it doesn't appear to be working and I need that to be able to function inside
  // of KASTR." Decided "Play it on the slide" + "Follow the deck": while a slide with an embedded video is live, this page
  // streams the video into the room exactly like Share > Media file (window.__presVideo: the same player, converter, encoder
  // and announce) and every page draws that stream in the video's spot on the slide, with its sound. It starts by itself when
  // the deck says "Start: Automatically", otherwise it waits for Play from the presenter or a backstage person. The slide
  // change stops it; back on the slide it waits again on its poster. Nothing of it is published before its slide is live.
  function vidList(m, i) { return (((m.src && m.src.videos) || [])[i] || []).filter((v) => v.id); }   // 0.21.91: a handed-over deck has no videos here
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
    {   // 0.21.91: a deck handed over -- the video picks up where the room left it (time, playing)
      const rv = (m.resumeVids || []).find((x) => x && x.v === sv.id && x.i === i);
      if (rv) {
        m.resumeVids = m.resumeVids.filter((x) => x !== rv);
        const at = Number(rv.at) || Date.now(), t = Math.max(0, (Number(rv.t) || 0) + (rv.pl ? Math.max(0, Date.now() - at) / 1000 : 0));
        const go = () => { if (e.gone || mine !== m) return; vidCtl(e, "seek", t); if (rv.pl) vidCtl(e, "play"); };
        setTimeout(go, 400); setTimeout(() => { const s = window.__presVideo?.state(e.shareId); if (s && Math.abs(s.t - t) > 2) go(); }, 1800);
        T("vid-resume", { id: m.id, idx: i, who: sv.id, t: +t.toFixed(1), pl: !!rv.pl });
      }
    }
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
  // 0.21.91 (Kenton: "When presenter changes, the slides should stay. The new presenter is only there for their own audio/video. So
  // the slides should continue working. Video in the slides should also still work."): a hand-over on the spot changes only whose
  // camera is in the slide -- the owner's page keeps the deck AND its videos. For an owner that leaves or drops, the deck's slide
  // videos are in the store too: encrypted like the slides (HKDF(K, "video/<k>")), with a manifest (where each sits on its slide,
  // auto / delay / loop / volume; HKDF(K, "videos")), read only with the deck's read token. A presenter who takes the deck over
  // plays them from there, from where the room was. One video at most 200 MB (the store refuses more; that one then stays with
  // the first owner).
  const VID_STORE_MAX = 200 * 1024 * 1024;
  async function uploadVideos(m) {
    const per = (m.src && m.src.videos) || [];
    const ids = [...new Set(per.flat().filter((v) => v && v.id).map((v) => v.id))];
    if (!ids.length || !m.src.videoFile) return;
    const files = {};
    let old = false;
    for (const id of ids) {
      if (mine !== m) return;
      let f = null; try { f = await m.src.videoFile(id); } catch {}
      if (!f) continue;
      if (f.size > VID_STORE_MAX) { T("vid-store-skip", { id: m.id, who: id, why: "size " + f.size }); continue; }
      const ct = await seal(await hkdf(m.K, "video/" + id), new Uint8Array(await f.arrayBuffer()));
      let r = null;
      try { r = await fetch(m.base + "/api/pres/" + m.id + "/" + id + ".bin?token=" + m.token, { method: "POST", body: ct }); } catch {}
      if (!r || !r.ok) { T("vid-store-fail", { id: m.id, who: id, why: r ? r.status : "net" }); if (r && r.status === 404) { old = true; break; } continue; }   // 404: a relay host older than 0.21.91
      files[id] = { name: String(f.name || id).slice(0, 120), type: String(f.type || "video/mp4").slice(0, 60), size: f.size };
    }
    if (old || mine !== m || !Object.keys(files).length) return;
    const man = { v: 1, per, files };
    const r = await fetch(m.base + "/api/pres/" + m.id + "/videos.bin?token=" + m.token, { method: "POST", body: await seal(await hkdf(m.K, "videos"), enc.encode(JSON.stringify(man))) }).catch(() => null);
    if (!r || !r.ok || mine !== m) return;
    m.vs = Object.keys(files).length;
    T("vid-store", { id: m.id, n: m.vs });
    publishVid();
  }
  async function storedVideos(m, rt) {   // a deck handed over to me: its videos from the store -> a src the video code knows
    const buf = await fetchBlob(baseFor({ base: m.base }), m.id, "videos.bin", 3, rt);
    const man = JSON.parse(dec.decode(await unseal(await hkdf(m.K, "videos"), buf)));
    const got = new Map();
    return {
      videos: Array.isArray(man.per) ? man.per : [],
      videoFile: (id) => {
        const meta = man.files && man.files[id];
        if (!meta) return Promise.resolve(null);
        if (!got.has(id)) got.set(id, (async () => {
          const t0 = Date.now();
          const b = await fetchBlob(baseFor({ base: m.base }), m.id, id + ".bin", 3, rt);
          const u8 = await unseal(await hkdf(m.K, "video/" + id), b);
          T("vid-load", { id: m.id, who: id, ms: Date.now() - t0, bytes: u8.length });
          return new File([u8], meta.name || id, { type: meta.type || "video/mp4" });
        })().catch((e) => { got.delete(id); console.warn("KASTR pres: a stored slide video", e); return null; }));
        return got.get(id);
      },
      close() {},
    };
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
  const ORPHAN_MS = 30000;   // 0.21.91: how long a deck whose record went stays waiting for a hand-over
  const HANDOVER_MS = 1500;  // 0.21.91: the record gone this long (+ 2 s per presenter before me) -> I run the deck on
  async function syncBackstage() {
    const me = myPerson();
    const live = new Set();
    const recs = deckRecs();
    for (const [id, { rec, path }] of recs) {
      if (mine && mine.id === id) continue;   // mine (a newer owner elsewhere is handled by the demotion check)
      const mineP = rec.own !== me ? (rec.ps || []).find((b) => b.p === me) : null;   // 0.21.91: an added presenter
      const mineB = mineP || (rec.bs || []).find((b) => b.p === me);
      if (!mineB) continue;
      live.add(id);
      let bk = backstage.get(id);
      if (!bk) { bk = { rec, path, K: null, keys: null, notes: null, nv: 0, w: "" }; backstage.set(id, bk); T("bs-seen", { id }); }
      const wasPr = !!bk.pr;
      bk.rec = rec; bk.path = path; bk.pr = !!mineP; bk.seenAt = Date.now(); bk.orphan = false;
      if (mineB.w && (mineB.w !== bk.w || rec.pk !== bk.pkFrom) && subtle) {
        try {
          const wk = await wrapKey(rec.pk, rec.id + "/" + me);
          bk.K = await unseal(wk, unb64(mineB.w));
          bk.keys = await Promise.all(Array.from({ length: rec.n }, (_, i) => hkdf(bk.K, "slide/" + i)));
          bk.notesKey = await hkdf(bk.K, "notes");
          bk.rt = rec.rt ? dec.decode(await unseal(await hkdf(bk.K, "read"), unb64(rec.rt))) : "";
          bk.wt = mineP && mineP.t ? dec.decode(await unseal(await hkdf(wk, "write"), unb64(mineP.t))) : "";   // 0.21.91: the write token
          bk.w = mineB.w; bk.pkFrom = rec.pk;
          T(mineP ? "co-key" : "bs-key", { id });
          if (!bk.toasted || wasPr !== !!mineP) {
            bk.toasted = true;
            const by = nameOfPerson(rec.own || personOfPath(path));
            toast(mineP ? by + " made you a presenter of “" + rec.name + "”. Open the presenter view from the pill at the top."
                        : by + " made you backstage for “" + rec.name + "”. Open the presenter view from the pill at the top.", 9000);
          }
          view.offer();
        } catch (e) { console.warn("KASTR pres: unwrap failed", e); }
      }
      if (!mineP) bk.wt = "";
      if (bk.K && rec.nv !== bk.nv) {
        bk.nv = rec.nv;
        fetchBlob(baseFor(rec), rec.id, "notes.bin", 10, bk.rt).then((buf) => unseal(bk.notesKey, buf)).then((u8) => { bk.notes = JSON.parse(dec.decode(u8)).notes || []; T("bs-notes", { id: rec.id }); view.paint(); }).catch((e) => console.warn("KASTR pres: notes", e));
      }
    }
    for (const [id, bk] of [...backstage]) {
      if (live.has(id)) continue;
      // 0.21.91: still in the room but I am no longer in it -> gone now; the record itself gone -> wait for a hand-over
      if (recs.has(id) || bk.ended || (mine && mine.id === id) || !bk.K || Date.now() - (bk.seenAt || 0) > ORPHAN_MS) { backstage.delete(id); T("bs-gone", { id }); view.paint(); continue; }
      if (!bk.orphan) { bk.orphan = true; T("orphan", { id }); view.paint(); }
    }
  }
  function endSeen(id, path) {   // 0.21.91: a presenter of this deck says it ended -- nobody takes it over
    const bk = backstage.get(id);
    if (!bk) return;
    const who = personOfPath(path), rec = bk.rec || {};
    if (who !== rec.own && !(rec.ps || []).some((x) => x.p === who)) return;   // only its presenters may say so
    bk.ended = true; backstage.delete(id); T("bs-gone", { id, why: "ended" }); view.paint();
  }
  // 0.21.91: my requests -- presCtl carries the newest at the top level (what older KASTRs read) and my last few in q
  const ctlQ = [];
  function ctlSend(o) {
    ctlSeq++;
    const op = Object.assign({ seq: ctlSeq, at: Date.now() }, o);
    ctlQ.push(op); while (ctlQ.length > 6) ctlQ.shift();
    stateSet("presCtl", Object.assign({}, op, { q: ctlQ.filter((x) => x.id === op.id) }));
    return op;
  }
  function sendIntent(deckId, to, blank) {
    const bk = backstage.get(deckId);
    if (!bk) return;
    const o = { id: deckId, bv: bk.rec.ver, to: clampI(to, bk.rec.n) };
    if (blank !== undefined) o.blank = blank || null;
    const ctl = ctlSend(o);
    bk.opt = ctl.to; bk.optBlank = blank === undefined ? null : blank; bk.optAt = Date.now(); bk.optVer = bk.rec.ver;
    T("intent", { id: deckId, idx: ctl.to, ver: ctl.bv });
    view.paint();
  }
  function sendVidIntent(deckId, vr, op, t) {   // 0.21.87: backstage Play / Pause / seek of the live slide's video (vr = its entry in pres.vids)
    const bk = backstage.get(deckId);
    if (!bk || !vr) return;
    const o = { id: deckId, bv: bk.rec.ver, to: bk.rec.idx, vid: { v: vr.v, i: vr.i, op } };
    if (t != null) o.vid.t = +Number(t).toFixed(2);
    ctlSend(o);
    T("vid-intent", { id: deckId, idx: vr.i, ver: o.bv, who: op });
  }
  function sendPresOp(deckId, pp) {   // 0.21.91: a co-presenter's request to the owner page (people, now presenting, notes, Reporter, End)
    const bk = backstage.get(deckId);
    if (!bk || !bk.pr) return false;
    ctlSend({ id: deckId, bv: bk.rec.ver, to: bk.rec.idx, pp });
    T("pp-intent", { id: deckId, who: pp.op });
    return true;
  }

  // viewers (and backstage): the sharp live slide over the share's tile
  const overlays = new Map();   // share path -> {cv, key, rec}
  let viewerFetches = [];        // rig: every slide this page fetched as a viewer
  function syncOverlays() {
    const tiles = window.__switcher?.tiles;
    const want = new Map();
    for (const { rec } of deckRecs().values()) if (rec.share) want.set(rec.share, rec);   // 0.21.91: one record per deck (a hand-over: the newest owner's)
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
  #presView .pb { flex:1; min-height:0; display:grid; grid-template-columns: minmax(0, var(--lcol, 3fr)) 10px minmax(280px, var(--rcol, 2fr)); gap:4px; padding:10px 12px; }
  #presView .vdiv, #presView .hdiv { background:transparent; border-radius:4px; touch-action:none; outline:none; }
  #presView .vdiv { cursor:col-resize; margin:30px 0; background:linear-gradient(90deg, transparent 4px, #1f2a36 4px, #1f2a36 6px, transparent 6px); }
  #presView .hdiv { cursor:row-resize; flex:none; height:10px; background:linear-gradient(180deg, transparent 4px, #1f2a36 4px, #1f2a36 6px, transparent 6px); }
  #presView .vdiv:hover, #presView .vdiv:focus-visible, #presView .vdiv.drag { background:linear-gradient(90deg, transparent 3px, #1592d1 3px, #1592d1 7px, transparent 7px); }
  #presView .hdiv:hover, #presView .hdiv:focus-visible, #presView .hdiv.drag { background:linear-gradient(180deg, transparent 3px, #1592d1 3px, #1592d1 7px, transparent 7px); }
  #presView .panels { flex:none; max-height:var(--ptop, 42%); overflow:auto; display:flex; flex-direction:row; flex-wrap:wrap; gap:4px; align-items:flex-start; }
  #presView details.pnl { border:1px solid #1f2a36; border-radius:6px; background:#0f1722; flex:1 1 150px; min-width:0; }
  #presView details.pnl[open] { flex-basis:100%; order:-1; }   /* closed panels share one row; an open one takes the width */
  #presView details.pnl > summary { list-style:none; cursor:pointer; display:flex; gap:8px; align-items:center; padding:5px 10px; font-size:12px;
    letter-spacing:.05em; text-transform:uppercase; color:#8aa0b5; user-select:none; }
  #presView details.pnl > summary::-webkit-details-marker { display:none; }
  #presView details.pnl > summary::before { content:"▸"; font-size:11px; transition:transform .12s; }
  #presView details.pnl[open] > summary::before { transform:rotate(90deg); }
  #presView details.pnl > summary .pnt { flex:none; }
  #presView details.pnl > summary .pv { flex:1; min-width:0; text-transform:none; letter-spacing:0; color:#cfe3f3; font-size:12.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-align:right; }
  #presView details.pnl.attn > summary { color:#ffcf7a; }
  #presView details.pnl.attn > summary .pv { color:#ffcf7a; font-weight:600; }
  #presView details.pnl .pbody { padding:0 8px 8px; }
  #presView details.pnl .pbody .modebox, #presView details.pnl .pbody .pplbox { border:0; padding:0; background:transparent; }
  #presView details.pnl .pbody .modebox .mhead { display:none; }   /* the panel's own title says it */
  #presView .nrow { flex:none; }
  #presView .nxt { flex:none; display:flex; flex-direction:row; align-items:center; gap:6px; cursor:default; }
  #presView .nxt canvas { width:84px; aspect-ratio:16/9; background:#000; border-radius:3px; box-shadow:0 0 0 1px #1592d1; }
  #presView .nxt .nxl { font-size:11px; color:#8aa0b5; white-space:nowrap; }
  #presView.nostrip .strip { display:none; }
  #presView .ph .stripbtn { padding:4px 10px; font-size:12.5px; }
  #presView.nostrip .ph .stripbtn { opacity:.6; }
  #presView .cur { display:flex; flex-direction:column; min-height:0; gap:8px; }
  #presView .cap { font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:#8aa0b5; display:flex; gap:8px; align-items:center; }
  #presView .cap .live { color:#fff; background:#c62828; padding:1px 7px; border-radius:4px; letter-spacing:.08em; }
  #presView .curwrap { flex:1; min-height:0; position:relative; display:flex; align-items:center; justify-content:center; }
  #presView .cur canvas { display:block; background:#000; border-radius:6px; box-shadow:0 0 0 2px #c62828; }
  #presView .ctl { display:flex; gap:10px; align-items:center; justify-content:center; flex-wrap:wrap; }
  #presView .ctl .num { font-size:18px; font-variant-numeric:tabular-nums; min-width:110px; text-align:center; }
  #presView .side { display:flex; flex-direction:column; gap:6px; min-height:0; overflow:hidden; }
  #presView .notes { flex:1; min-height:120px; overflow:auto; background:#0f1722; border:1px solid #1f2a36; border-radius:6px; padding:10px 14px;
    white-space:pre-wrap; font-size:var(--pnfs, 20px); line-height:1.45; user-select:text; -webkit-user-select:text; }
  #presView .notes.empty { color:#6b7d8f; font-style:italic; }
  #presView textarea.notes { resize:none; color:#e6edf3; font-family:inherit; }
  #presView .nrow { display:flex; gap:6px; align-items:center; }
  #presView .nrow .ncap { display:block; flex:1; }
  #presView .pplbox { border:1px solid #1f2a36; border-radius:6px; padding:8px 10px; background:#0f1722; display:grid; gap:8px; }
  #presView .psec .cap { margin-bottom:4px; }
  #presView .psec .cap .sp { flex:1; }
  #presView .psec .cap button { text-transform:none; letter-spacing:0; font-size:12px; padding:3px 9px; }
  #presView .psec .rows { display:grid; gap:4px; }
  #presView .psec .empty { font-size:12px; color:#6b7d8f; }
  #presView .prow { display:flex; align-items:center; gap:7px; min-height:30px; padding:2px 6px; border-radius:6px; background:#131d29; font-size:13px; flex-wrap:wrap; }
  #presView .prow.now { box-shadow: inset 0 0 0 1px #c62828; }
  #presView .prow .pav { width:24px; height:24px; border-radius:50%; flex:none; display:inline-flex; align-items:center; justify-content:center; overflow:hidden;
    font-size:10px; font-weight:600; color:#fff; background:#2c3b4b; position:relative; }
  #presView .prow .pav img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
  #presView .prow .dot { width:8px; height:8px; border-radius:50%; flex:none; background:#5b6b7b; }
  #presView .prow .dot.ready { background:#2fbf71; }
  #presView .prow .dot.wait { background:#e0a92e; }
  #presView .prow .pn { flex:1; min-width:70px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  #presView .prow .pn .you { color:#8aa0b5; }
  #presView .prow .tag { font-size:11px; padding:1px 7px; border-radius:999px; background:#c62828; color:#fff; white-space:nowrap; }
  #presView .prow .tag.own { background:#1d3a52; color:#8fd3ff; }
  #presView .prow button { padding:2px 8px; font-size:12px; }
  #presView .prow button.x { padding:2px 7px; color:#ffb4b4; }
  #presView .prow label.allow { display:inline-flex; flex-direction:row; gap:5px; align-items:center; font-size:12px; color:#cfe3f3; cursor:pointer; white-space:nowrap; margin:0; }
  #presView .prow label.allow input { margin:0; width:auto; height:auto; }
  #presView .prow label.allow.ro { cursor:default; opacity:.8; }
  #presView .ph .nowp { font-size:12px; padding:2px 9px; border-radius:999px; background:#3a1414; color:#ffb4b4; white-space:nowrap; }
  #presView .ph .nowp:empty { display:none; }
  #presView .ppick { position:absolute; inset:0; z-index:5; background:rgba(4,8,12,.6); display:flex; align-items:center; justify-content:center; }
  #presView .ppick[hidden] { display:none; }
  #presView .ppick .pk { width:min(440px, 94vw); max-height:min(560px, 86vh); display:flex; flex-direction:column; background:#0f1722; border:1px solid #2c3b4b;
    border-radius:10px; box-shadow:0 12px 40px rgba(0,0,0,.55); }
  #presView .ppick .pkh { display:flex; gap:8px; align-items:center; padding:10px 12px; border-bottom:1px solid #1f2a36; }
  #presView .ppick .pkh b { flex:1; font-size:15px; }
  #presView .ppick input[type=search] { margin:10px 12px 6px; padding:7px 10px; border-radius:6px; border:1px solid #2c3b4b; background:#0b1118; color:#e6edf3; font:inherit; }
  #presView .ppick .pkl { overflow:auto; padding:4px 8px 10px; display:grid; gap:4px; }
  #presView .ppick .pkr { display:flex; align-items:center; gap:9px; padding:6px 8px; border-radius:6px; background:#131d29; border:1px solid transparent; cursor:pointer; text-align:left; width:100%; justify-content:flex-start; }
  #presView .ppick .pkr:hover:not(:disabled) { border-color:#1592d1; }
  #presView .ppick .pkr:disabled { opacity:.5; cursor:not-allowed; }
  #presView .ppick .pkr .pav { width:30px; height:30px; border-radius:50%; flex:none; display:inline-flex; align-items:center; justify-content:center; overflow:hidden; font-size:11px; font-weight:600; color:#fff; background:#2c3b4b; position:relative; }
  #presView .ppick .pkr .pav img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
  #presView .ppick .pkr .pkn { flex:1; display:flex; flex-direction:column; white-space:normal; }
  #presView .ppick .pkr .pkn small { color:#8aa0b5; font-size:11px; }
  #presView .ppick .none { color:#6b7d8f; padding:10px; font-size:13px; }
  #presView .strip { display:flex; gap:6px; overflow-x:auto; padding:5px 12px 6px; border-top:1px solid #1f2a36; background:#0f1722; flex:none; }
  #presView .strip .th { flex:none; width:88px; cursor:pointer; text-align:center; font-size:10px; color:#8aa0b5; line-height:1.2; }
  #presView .strip .th canvas { width:88px; height:50px; display:block; background:#000; border-radius:3px; border:2px solid transparent; }
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
  #presView .rsee { position:absolute; top:8px; left:50%; transform:translateX(-50%); z-index:2; pointer-events:none; font-size:14px; font-weight:600;
    padding:4px 12px; border-radius:999px; background:#000; color:#fff; border:1px solid #fff; box-shadow:0 2px 10px rgba(0,0,0,.6); }
  #presView .rsee:empty { display:none; }
  #presView .rsee[data-k="white"] { background:#fff; color:#000; border-color:#000; }
  #presView .ctl button.blk.on { background:#000; border-color:#fff; color:#fff; }
  #presView .ctl button.wht.on { background:#fff; border-color:#000; color:#000; }
  #presView .vbar { display:none; gap:10px; align-items:center; justify-content:center; flex-wrap:wrap; }
  #presView .vbar.show { display:flex; }
  #presView .vbar input[type=range] { width:min(420px, 40vw); }
  #presView .vbar .vtime { font-variant-numeric:tabular-nums; color:#8aa0b5; min-width:96px; }
  #presView .vbar .vnote { color:#ffcf7a; font-size:13px; }
  @media (max-width: 760px) {
    #presView .pb { grid-template-columns: 1fr; overflow:auto; }
    #presView .vdiv, #presView .hdiv { display:none; }
    #presView .pb { display:flex; flex-direction:column; }   /* a phone: one column that scrolls -- slide, controls, notes, panels */
    #presView .pb > .cur, #presView .pb > .side { flex:none; min-height:auto; }
    #presView .side { overflow:visible; }
    #presView .nrow { flex-wrap:wrap; }
    #presView .nrow .ncap { order:5; flex-basis:100%; }
    #presView .panels { order:3; max-height:none; }
    #presView .notes { min-height:40vh; }
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
        <div class="ph"><span class="ttl"></span><span class="role"></span><span class="nowp" title="The presenter presenting now -- their camera is the one in the slide"></span><span class="sp"></span>
          <span class="timer" title="Time since the presentation started"></span><span class="clock"></span>
          <button type="button" class="stripbtn" title="Show or hide the slides along the bottom (remembered on this device)">Slides</button>
          <button type="button" class="hide" title="Back to the room (the presentation keeps going; Esc)">Back to room</button>
          <button type="button" class="end" title="End the presentation for everyone">End</button></div>
        <div class="prep"></div>
        <div class="pb">
          <div class="cur"><div class="cap"><span class="live">LIVE</span><span class="who"></span></div><div class="curwrap"><canvas class="curcv"></canvas><canvas class="vidcv"></canvas><span class="rsee" title="Black / White hides the slide for the room only -- you still see it. It stays on across slide changes until you turn it off."></span></div>
            <div class="ctl"><button type="button" class="big back" title="Previous slide (Left, PageUp, Backspace)">◀ Back</button>
              <span class="num"></span><button type="button" class="big next" title="Next slide (Right, PageDown, Space)">Next ▶</button>
              <button type="button" class="blk" title="Black screen for everyone (B or .)">Black</button><button type="button" class="wht" title="White screen for everyone (W or ,)">White</button></div>
            <div class="vbar"><button type="button" class="vplay" title="Play or pause the video on this slide for everyone">▶ Play video</button>
              <input type="range" class="vseek" min="0" max="1000" value="0" title="The video's position (everyone)"><span class="vtime"></span><span class="vnote"></span></div></div>
          <div class="vdiv" role="separator" aria-orientation="vertical" tabindex="0" title="Drag: a bigger slide or wider notes (remembered on this device; arrow keys too)"></div>
          <div class="side">
            <div class="panels">
              <details class="pnl" data-k="mode"><summary><span class="pnt">Mode</span><span class="pv"></span></summary><div class="pbody pmode"></div></details>
              <details class="pnl" data-k="av"><summary><span class="pnt">Mic &amp; audience</span><span class="pv"></span></summary><div class="pbody pav"></div></details>
              <details class="pnl" data-k="ppl"><summary><span class="pnt">People</span><span class="pv"></span></summary><div class="pbody">
            <div class="pplbox"><div class="psec psp"><div class="cap">Presenters<span class="sp"></span><button type="button" class="addp" title="Make someone in the room a presenter: the same powers as you, and their camera in the slide while it is their turn">Add presenter</button></div><div class="rows"></div></div>
              <div class="psec psb"><div class="cap">Backstage — see the notes and what is next, can move the slides<span class="sp"></span><button type="button" class="addb" title="Make someone in the room backstage">Add backstage</button></div><div class="rows"></div></div></div></div></details>
            </div>
            <div class="hdiv" role="separator" aria-orientation="horizontal" tabindex="0" title="Drag: more room for the notes (remembered on this device; arrow keys too)"></div>
            <div class="nrow"><div class="nxt" title="The next slide"><canvas class="n1"></canvas><span class="nxl"></span></div>
              <span class="cap ncap">Notes — only you<span class="bsn"></span> can see these</span>
              <button type="button" class="fsm" title="Smaller notes (remembered on this device)">A−</button><button type="button" class="fsp" title="Larger notes (remembered on this device)">A+</button>
              <button type="button" class="edit" title="Write or change the notes for this slide">Edit</button></div>
            <div class="notes"></div>
          </div>
        </div>
        <div class="strip"></div>
        <div class="ppick" hidden><div class="pk"><div class="pkh"><b class="pkt"></b><button type="button" class="pkx">Close</button></div><input type="search" class="pks" placeholder="Search people in the room" aria-label="Search people"><div class="pkl"></div></div></div>`;
      document.body.appendChild(root);
      modeUiBuild(root);   // 0.21.89: the presenter-mode picker + preview (+ backstage's mic / camera)
      pill = document.createElement("div"); pill.id = "presPill";
      pill.innerHTML = `<span class="pt"></span><button type="button">Presenter view</button>`;
      document.body.appendChild(pill);
      pill.querySelector("button").addEventListener("click", () => { hidden = false; open({ deck: pillDeck() }); });
      $(".hide").addEventListener("click", () => { hidden = true; close(); });
      $(".end").addEventListener("click", () => { endPress(); });
      $(".addp").addEventListener("click", () => openPicker("p"));   // 0.21.91
      $(".addb").addEventListener("click", () => openPicker("b"));
      $(".pkx").addEventListener("click", () => closePicker());
      $(".pks").addEventListener("input", () => paintPicker());
      $(".ppick").addEventListener("click", (e) => { if (e.target === $(".ppick")) closePicker(); });
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
      layoutBuild();   // 0.21.91
      new ResizeObserver(() => paint()).observe(root);
    }
    // 0.21.91: the layout, remembered on this device (kastr.pres.layout): the slide column's share, the panels' height (the notes take
    // the rest), the strip on / off, which panels are open (all closed at first -- one opens by itself when it needs attention)
    let LY = {};
    try { LY = JSON.parse(localStorage.getItem("kastr.pres.layout") || "{}") || {}; } catch {}
    const lySave = () => { try { localStorage.setItem("kastr.pres.layout", JSON.stringify(LY)); } catch {} };
    function layoutApply() {
      if (!root) return;
      // Kenton: a short window (under ~800 px) gives the notes the width -- the slide column shrinks (unless this device dragged it)
      const f = Math.max(0.3, Math.min(0.78, Number(LY.col) || (window.innerHeight < 740 ? 0.4 : window.innerHeight < 800 ? 0.46 : 0.6)));
      root.style.setProperty("--lcol", f.toFixed(3) + "fr"); root.style.setProperty("--rcol", (1 - f).toFixed(3) + "fr");
      if (Number(LY.top) > 0) root.style.setProperty("--ptop", Math.round(LY.top) + "px"); else root.style.removeProperty("--ptop");
      // the strip: on unless this device hid it -- by default off on a short window (under 900 px tall) where the notes need the room
      root.classList.toggle("nostrip", LY.nostrip === undefined ? window.innerHeight < 900 : !!LY.nostrip);
    }
    function dragLine(el, onMove, onKey) {
      el.addEventListener("pointerdown", (e) => {
        e.preventDefault(); el.setPointerCapture(e.pointerId); el.classList.add("drag");
        const mv = (ev) => { onMove(ev); layoutApply(); };
        const up = () => { el.classList.remove("drag"); el.removeEventListener("pointermove", mv); el.removeEventListener("pointerup", up); el.removeEventListener("pointercancel", up); lySave(); paint(); };
        el.addEventListener("pointermove", mv); el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
      });
      el.addEventListener("keydown", (e) => { const d = onKey(e.key); if (d) { e.preventDefault(); e.stopPropagation(); layoutApply(); lySave(); paint(); } });
    }
    function layoutBuild() {
      layoutApply();
      dragLine($(".vdiv"), (e) => { const r = $(".pb").getBoundingClientRect(); LY.col = Math.max(0.3, Math.min(0.78, (e.clientX - r.left) / Math.max(1, r.width))); },
        (k) => { const c = Number(LY.col) || 0.6; if (k === "ArrowLeft") { LY.col = Math.max(0.3, c - 0.02); return true; } if (k === "ArrowRight") { LY.col = Math.min(0.78, c + 0.02); return true; } return false; });
      dragLine($(".hdiv"), (e) => { const r = $(".panels").getBoundingClientRect(), s = $(".side").getBoundingClientRect(); LY.top = Math.max(28, Math.min(s.height - 160, e.clientY - r.top)); },
        (k) => { const t = Number(LY.top) || $(".panels").getBoundingClientRect().height; if (k === "ArrowUp") { LY.top = Math.max(28, t - 20); return true; } if (k === "ArrowDown") { LY.top = t + 20; return true; } return false; });
      $(".stripbtn").addEventListener("click", () => { LY.nostrip = !root.classList.contains("nostrip"); layoutApply(); lySave(); paint(); });
      window.addEventListener("resize", () => { if (LY.nostrip === undefined || !LY.col) layoutApply(); });
      for (const d of root.querySelectorAll("details.pnl")) {
        d.open = !!(LY.open && LY.open[d.dataset.k]);
        d.addEventListener("toggle", () => { LY.open = Object.assign({}, LY.open, { [d.dataset.k]: d.open }); if (!d.dataset.auto) lySave(); delete d.dataset.auto; paint(); });
      }
    }
    function panelInfo(v, M) {   // each panel's one-line summary (they are closed) and whether one needs attention
      const pnl = (k) => root.querySelector('details.pnl[data-k="' + k + '"]');
      const set = (k, text, attn) => {
        const d = pnl(k); if (!d) return;
        const pv = d.querySelector(".pv");
        if (pv.textContent !== text) pv.textContent = text;
        const was = d.classList.contains("attn");
        d.classList.toggle("attn", !!attn);
        if (attn && !was && !d.open) { d.dataset.auto = "1"; d.open = true; }   // it needs attention: open by itself (not remembered)
      };
      const mv = modeView();
      if (mv) {
        const why = mui && mui.why ? mui.why.textContent : "";
        set("mode", MODE_NAME[mv.cm] + (mv.eff !== mv.cm ? " · the room sees the slide only" : "") + (M && M.ps.length > 1 ? " · " + (mv.turn ? "you present" : mv.cn + " presents") : ""), !!why);
        pnl("mode").hidden = !(mv.role === "presenter" || mv.has);
      }
      const ex = panelAvInfo(v);
      set("av", ex.text, ex.attn);
      set("ppl", M ? M.ps.length + (M.ps.length === 1 ? " presenter" : " presenters") + " · " + M.bs.length + " backstage" : "", false);
    }
    function setFs(v) { fs = Math.max(12, Math.min(48, v)); root.style.setProperty("--pnfs", fs + "px"); try { localStorage.setItem("kastr.pres.notesSize", String(fs)); } catch {} }
    function deck() {   // {role, rec-like view} for the deck on show
      if (mine && deckId === mine.id) return { role: "presenter", id: mine.id, name: mine.name, n: mine.n, idx: mine.idx, blank: mine.blank, t0: mine.t0, notes: mine.notes, by: mine.by, ver: mine.ver, ar: mine.ar };
      const bk = backstage.get(deckId);
      if (!bk) return null;
      const opt = bk.opt != null && Date.now() - bk.optAt < 1500 && bk.rec.ver === bk.optVer;
      return { role: bk.pr ? "copresenter" : "backstage", id: bk.rec.id, name: bk.rec.name, n: bk.rec.n, idx: opt ? bk.opt : bk.rec.idx, blank: opt ? bk.optBlank : (bk.rec.blank || null),
               t0: bk.rec.t0, notes: bk.notes, by: bk.rec.by, ver: bk.rec.ver, ar: bk.rec.ar, presenter: nameOfPerson(bk.rec.own || personOfPath(bk.path)), ready: !!bk.keys,
               orphan: !!bk.orphan };   // 0.21.91: + a co-presenter; orphan = its owner went, a hand-over is on its way
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
      if (show) { const b = backstage.get(id); pill.querySelector(".pt").textContent = mine ? "You are presenting “" + mine.name + "”" : (b?.pr ? "You co-present “" : "Backstage for “") + (b?.rec.name || "") + "”"; }
    }
    function step(d) {   // 0.21.91: a move keeps the room's Black / White
      const v = deck(); if (!v) return;
      const to = clampI(v.idx + d, v.n);
      if (v.role === "presenter") goTo(to, myPerson());
      else sendIntent(v.id, to);
    }
    function goto(i) {
      const v = deck(); if (!v) return;
      if (v.role === "presenter") goTo(i, myPerson()); else sendIntent(v.id, i);
    }
    function blank(kind) {
      const v = deck(); if (!v) return;
      const nb = v.blank === kind ? null : kind;
      if (v.role === "presenter") goTo(v.idx, myPerson(), nb); else sendIntent(v.id, v.idx, nb);
    }
    function toggleEdit() {
      const v = deck();
      if (!v || (v.role !== "presenter" && v.role !== "copresenter")) return;   // 0.21.91: + an added presenter
      const own = v.role === "presenter", bk = own ? null : backstage.get(v.id);
      const notes = own ? mine.notes : (bk && bk.notes);
      if (!notes) return;
      const box = $(".notes");
      if (!editing) {
        editing = true;
        const ta = document.createElement("textarea"); ta.className = "notes"; ta.value = notes[v.idx] || "";
        ta.dataset.idx = String(v.idx);
        box.replaceWith(ta); ta.focus(); $(".edit").textContent = "Save";
      } else {
        const ta = root.querySelector("textarea.notes");
        const i = Number(ta.dataset.idx), text = ta.value.slice(0, 20000);
        if (own) { mine.notes[i] = text; mine.nv++; uploadNotes().then(() => publish()); }
        else if (bk && bk.notesKey) {   // the owner page stores it: sealed with the notes key, so the room never reads it
          bk.notes[i] = text;
          seal(bk.notesKey, enc.encode(text)).then((ct) => sendPresOp(v.id, { op: "note", i, c: b64(ct) }));
        }
        const d = document.createElement("div"); d.className = "notes"; ta.replaceWith(d);
        editing = false; $(".edit").textContent = "Edit"; paintAll();
      }
    }
    function endPress() {   // 0.21.91: any presenter ends it for everyone
      const v = deck();
      if (v && v.role === "presenter" && mine) endMine("ended");
      else if (v && v.role === "copresenter") {
        const bk = backstage.get(v.id), id = v.id;
        sendPresOp(id, { op: "end" });
        setTimeout(() => {   // the owner did not answer (it is going away?): the store forgets the deck -- nobody takes it over
          const b = backstage.get(id);
          if (!b || !b.wt) return;
          endMark = { id, at: Date.now() }; coPublish();
          fetch(baseFor(b.rec) + "/api/pres/" + id + "/end?token=" + encodeURIComponent(b.wt), { method: "POST" }).catch(() => {});
          T("end-self", { id });
        }, 3000);
        void bk;
      }
      close();
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
        const linked = (((mine.src && mine.src.videos) || [])[mine.idx] || []).find((x) => x.linked);
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
        items = es.filter((e) => e.st && e.shareId != null && e.sv.kind !== "audio").map((e) => ({ x: e.sv.x, y: e.sv.y, w: e.sv.w, h: e.sv.h, src: window.__presVideo?.frame(e.shareId) || null }));
      } else {
        const rec = backstage.get(v.id)?.rec;
        const rs = rec && rec.idx === v.idx ? (rec.vids || []).filter((x) => x.i === rec.idx) : [];
        any = rs.length > 0;
        items = rs.filter((x) => x.st && x.k !== "a").map((x) => ({ x: x.x, y: x.y, w: x.w, h: x.h, src: window.__presVidFrame?.(x.p) || null }));
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
      const P = v.role === "presenter" || v.role === "copresenter";   // 0.21.91: an added presenter has the same powers
      const M = pplModel(v);
      role.textContent = v.role === "presenter" ? (M && M.ps.length > 1 ? "Presenter" : "You are presenting") : v.role === "copresenter" ? "Co-presenter" : "Backstage for " + v.presenter;
      role.classList.toggle("bs", v.role === "backstage");
      $(".nowp").textContent = v.orphan ? "Handing over…" : M && M.ps.length > 1 ? "Now presenting: " + (M.cur === myPerson() ? "you" : nameOfPerson(M.cur)) : "";
      $(".end").style.display = P ? "" : "none";
      $(".edit").style.display = P || editing ? "" : "none";
      $(".num").textContent = "Slide " + (v.idx + 1) + " of " + v.n;
      $(".who").textContent = v.ver > 1 && v.by && v.by !== myPerson() ? "moved by " + nameOfPerson(v.by) : "";
      $(".blk").classList.toggle("on", v.blank === "black");
      $(".wht").classList.toggle("on", v.blank === "white");
      {   // who else reads the notes
        const others = M ? [...M.ps, ...M.bs].map((x) => x.p).filter((p) => p !== myPerson()).map(nameOfPerson) : [];
        $(".bsn").textContent = others.length ? " and " + others.join(", ") : "";
      }
      if (!editing) {
        const nb = $(".notes");
        const txt = v.notes ? (v.notes[v.idx] || "") : null;
        nb.textContent = txt == null ? "Opening the notes…" : txt || (P ? "No notes for this slide — Edit to add some (only the presenters and backstage see them)." : "No notes for this slide.");
        nb.classList.toggle("empty", !txt);
      }
      paintPeople(v, M);   // 0.21.91: Presenters + Backstage (read-only for backstage)
      panelInfo(v, M);   // 0.21.91: the panels' summaries; one that needs attention opens
      {   // the live slide as large as its box allows, in the deck's own shape
        const wrap = $(".curwrap"), cv = $(".curcv"), r = wrap.getBoundingClientRect();
        const ar = v.ar || 16 / 9, narrow = window.matchMedia("(max-width: 760px)").matches;
        const w = Math.max(40, narrow ? r.width : Math.min(r.width, r.height * ar)), h = w / ar;
        cv.style.width = Math.floor(w) + "px"; cv.style.height = Math.floor(h) + "px";
        for (const c of root.querySelectorAll(".nxt canvas")) c.style.aspectRatio = String(ar);
        $(".nxl").textContent = v.idx + 1 < v.n ? "Next: " + (v.idx + 2) : "End of the deck";
      }
      {   // 0.21.91: the room sees Black / White -- this view keeps the slide, marked
        const rs = $(".rsee");
        rs.textContent = v.blank === "black" ? "Room sees: Black" : v.blank === "white" ? "Room sees: White" : "";
        rs.dataset.k = v.blank || "";
      }
      const cvs = [[$(".curcv"), v.idx, null], [$(".n1"), v.idx + 1, null]];   // 0.21.91: one small next slide
      for (const [cv, i, bl] of cvs) {
        fitCanvas(cv);
        if (i >= v.n) { drawContain(cv, null, null, i === v.n ? "End of the deck" : ""); continue; }
        if (v.role !== "presenter" && !v.ready) { drawContain(cv, null, null, "Waiting for the key…"); continue; }
        stillFor(v.id, i).then((b) => { if (seq !== paintSeq) return; drawContain(cv, b, bl, ""); if (cv === cvs[0][0]) T("paint", { id: v.id, idx: i, ver: seq, who: "view" }); })
          .catch(() => drawContain(cv, null, null, "Slide " + (i + 1) + "…"));
      }
      paintStrip();
      paintVid();   // 0.21.87
      modeUiPaint();   // 0.21.89
      vidLoop();
    }
    function paintAll() { paint(); }
    // ---- 0.21.91 (Kenton: "The Backstage selector should be reworked"): two sections, Presenters (the main presenter first) and
    // Backstage, each with a ready dot and a remove x, an Add button that opens a people picker, a move between the sections, and on
    // each backstage row the viewing presenter's OWN "Can control my mic and camera" for that person. Read-only for backstage.
    function pplModel(v) {
      const me = myPerson();
      if (!v) return null;
      if (v.role === "presenter") {
        return { own: me, cur: mine.cur, edit: true, mePres: true,
                 ps: mine.ps.map((x) => ({ p: x.p, n: x.name || nameOfPerson(x.p), ready: x.p === me || !!(x.w && x.t) })),
                 bs: [...mine.bs].map(([p, b]) => ({ p, n: b.name || nameOfPerson(p), ready: !!b.w })) };
      }
      const bk = backstage.get(v.id), rec = bk && bk.rec;
      if (!rec) return null;
      const own = rec.own || personOfPath(bk.path);
      const ps = (Array.isArray(rec.ps) && rec.ps.length ? rec.ps : [{ p: own, n: "" }]).map((x) => ({ p: x.p, n: x.n || nameOfPerson(x.p), ready: x.p === own || !!(x.w && x.t) }));
      return { own, cur: rec.cur || own, edit: v.role === "copresenter", mePres: v.role === "copresenter", old: !(Array.isArray(rec.ps) && rec.ps.length),
               ps, bs: (rec.bs || []).map((x) => ({ p: x.p, n: x.n || nameOfPerson(x.p), ready: !!x.w })) };
    }
    function roleAct(who, r) {   // add / move / remove (the owner page applies it)
      const v = deck();
      if (!v) return false;
      if (v.role === "presenter") return setRole(who, r, myPerson());
      if (v.role === "copresenter") return sendPresOp(v.id, { op: "role", p: who, r });
      return false;
    }
    function curAct(who) {   // "Now presenting: <name>" / "Take over"
      const v = deck();
      if (!v) return false;
      if (v.role === "presenter") return setCur(who, myPerson());
      if (v.role === "copresenter") { const ok = sendPresOp(v.id, { op: "cur", p: who }); const bk = backstage.get(v.id); if (bk) { bk.optCur = who; bk.optCurAt = Date.now(); } paint(); return ok; }
      return false;
    }
    function allowAct(who, on) {   // MY setting for this backstage person
      if (!presentingDeck()) return false;
      if (on) self.al.add(who); else self.al.delete(who);
      self.alSeen.add(who);
      T("allow", { who, on: on ? 1 : 0 });
      modeTick(); coPublish();
      if (mine) publish();
      paint();
      return true;
    }
    function personAvatar(el, pk, name) {
      const K = window.__kmsg;
      el.textContent = K?.initials ? K.initials(name) : String(name || "?").slice(0, 2).toUpperCase();
      try { const c = K?.color?.(String(pk).split("/")[1] || pk); if (c) el.style.background = c; } catch {}
      try { K?.photo?.(el, name); } catch {}
    }
    function btn(cls, text, title, fn) {
      const b = document.createElement("button"); b.type = "button"; b.className = cls; b.textContent = text; if (title) b.title = title;
      b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
      return b;
    }
    function paintPeople(v, M) {
      const box = $(".pplbox");
      if (!M) { box.style.display = "none"; return; }
      box.style.display = "";
      const me = myPerson();
      const first = (n) => String(n || "").split(/\s+/)[0] || n;
      const curOpt = (() => { const bk = v.role === "copresenter" ? backstage.get(v.id) : null; return bk && bk.optCur && Date.now() - bk.optCurAt < 1500 ? bk.optCur : null; })();
      const cur = curOpt || M.cur;
      $(".addp").style.display = M.edit ? "" : "none";
      $(".addb").style.display = M.edit ? "" : "none";
      const rowsP = M.ps.map((x) => {
        const here = hereNow(x.p);
        const row = document.createElement("div"); row.className = "prow" + (x.p === cur ? " now" : ""); row.dataset.who = x.p; row.dataset.kind = "p";
        const av = document.createElement("span"); av.className = "pav"; personAvatar(av, x.p, x.n);
        const dot = document.createElement("span"); dot.className = "dot" + (!here ? "" : x.ready ? " ready" : " wait");
        dot.title = !here ? x.n + " is not in the room" : x.ready ? "Ready" : "Getting the slides' key…";
        const nm = document.createElement("span"); nm.className = "pn"; nm.textContent = x.n;
        if (x.p === me) { const y = document.createElement("span"); y.className = "you"; y.textContent = " (you)"; nm.appendChild(y); }
        row.append(av, dot, nm);
        if (x.p === M.own && M.ps.length > 1) { const t = document.createElement("span"); t.className = "tag own"; t.textContent = "runs the deck"; t.title = "The presentation runs from " + (x.p === me ? "your" : x.n + "'s") + " KASTR (if it leaves, the next presenter takes over)"; row.append(t); }
        if (x.p === cur) { const t = document.createElement("span"); t.className = "tag"; t.textContent = "Presenting now"; row.append(t); }
        else if (M.edit && here && x.ready && !M.old) {
          if (x.p === me) row.append(btn("takeover", "Take over", "Present now: your camera goes into the slide", () => curAct(x.p)));
          else row.append(btn("nowbtn", "Hand over to " + first(x.n), x.n + " presents now: their camera goes into the slide (the slides and their videos go on as they are)", () => curAct(x.p)));
        }
        if (M.edit && x.p !== M.own) {
          row.append(btn("mv", "→ Backstage", "Make " + x.n + " backstage instead", () => roleAct(x.p, "b")));
          row.append(btn("x", "×", x.p === me ? "Stop being a presenter" : "Remove " + x.n + " from the presenters", () => roleAct(x.p, "")));
        }
        return row;
      });
      const rowsB = M.bs.map((x) => {
        const here = hereNow(x.p);
        const row = document.createElement("div"); row.className = "prow"; row.dataset.who = x.p; row.dataset.kind = "b";
        const av = document.createElement("span"); av.className = "pav"; personAvatar(av, x.p, x.n);
        const dot = document.createElement("span"); dot.className = "dot" + (!here ? "" : x.ready ? " ready" : " wait");
        dot.title = !here ? x.n + " is not in the room" : x.ready ? "Ready" : "Getting the slides' key…";
        const nm = document.createElement("span"); nm.className = "pn"; nm.textContent = x.n;
        if (x.p === me) { const y = document.createElement("span"); y.className = "you"; y.textContent = " (you)"; nm.appendChild(y); }
        row.append(av, dot, nm);
        if (M.mePres) {   // MY setting for this person (each presenter has their own)
          const lab = document.createElement("label"); lab.className = "allow";
          lab.title = "Your own setting: " + x.n + " may mute / unmute your mic and pause / resume your video (other presenters decide for themselves)";
          const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = self.al.has(x.p); cb.dataset.who = x.p;
          cb.addEventListener("change", () => allowAct(x.p, cb.checked));
          lab.append(cb, document.createTextNode("Can control my mic and camera"));
          row.append(lab);
        }
        if (M.edit) {
          if (canCo(x.p)) row.append(btn("mv", "→ Presenter", "Make " + x.n + " a presenter instead", () => roleAct(x.p, "p")));
          row.append(btn("x", "×", "Remove " + x.n + " from backstage", () => roleAct(x.p, "")));
        }
        return row;
      });
      const empty = (t) => { const e = document.createElement("div"); e.className = "empty"; e.textContent = t; return e; };
      const pr = $(".psp .rows"), br = $(".psb .rows");
      const sigOf = (els) => els.map((e) => e.outerHTML + "|" + [...e.querySelectorAll("input")].map((i) => (i.checked ? 1 : 0)).join("")).join("\n");
      const nextP = rowsP.length ? rowsP : [empty("Nobody yet")];
      const nextB = rowsB.length ? rowsB : [empty(M.edit ? "Nobody backstage — Add backstage to give someone the notes and the slides" : "Nobody")];
      const sp = sigOf(nextP), sb = sigOf(nextB);
      if (pr.dataset.sig !== sp) { pr.dataset.sig = sp; pr.replaceChildren(...nextP); }
      if (br.dataset.sig !== sb) { br.dataset.sig = sb; br.replaceChildren(...nextB); }
      if (!$(".ppick").hidden) paintPicker();
    }
    // the people picker: people in the room (photo + name), searchable; whose KASTR cannot do it is listed greyed with why
    let pickKind = "p";
    function openPicker(kind) {
      pickKind = kind === "b" ? "b" : "p";
      $(".pkt").textContent = pickKind === "p" ? "Add presenter" : "Add backstage";
      $(".pks").value = "";
      $(".ppick").hidden = false;
      paintPicker();
      setTimeout(() => { try { $(".pks").focus(); } catch {} }, 0);
      T("picker", { who: pickKind });
    }
    function closePicker() { if (root) $(".ppick").hidden = true; }
    function paintPicker() {
      const v = deck(), M = pplModel(v);
      if (!M || !M.edit) { closePicker(); return; }
      const me = myPerson(), q = $(".pks").value.trim().toLowerCase();
      const inP = new Set(M.ps.map((x) => x.p)), inB = new Set(M.bs.map((x) => x.p));
      const seen = new Set(), rows = [];
      for (const p of (ctx()?.people || [])) {
        const who = p.host + "/" + (p.op || p.peer);
        if (who === me || seen.has(who)) continue;
        seen.add(who);
        if (pickKind === "p" ? inP.has(who) : inB.has(who)) continue;
        const name = p.name || p.op || p.host;
        if (q && !name.toLowerCase().includes(q)) continue;
        const hasPk = [...remote.entries()].some(([k, r]) => personOfPath(k) === who && r.pk);
        let why = "";
        if (pickKind === "p" && !canCo(who)) why = hasPk ? "Their KASTR is older than 0.21.91 — it cannot co-present (backstage works)" : "Their KASTR is older (or not open) — it cannot present";
        else if (pickKind === "b" && !hasPk) why = "Their KASTR is older than 0.21.84 (or not open) — it cannot be backstage";
        const b = document.createElement("button"); b.type = "button"; b.className = "pkr"; b.dataset.who = who; b.disabled = !!why;
        const av = document.createElement("span"); av.className = "pav"; personAvatar(av, who, name);
        const nm = document.createElement("span"); nm.className = "pkn"; nm.append(document.createTextNode(name));
        const sm = document.createElement("small");
        sm.textContent = why || (pickKind === "p" && inB.has(who) ? "Backstage now — becomes a presenter" : pickKind === "b" && inP.has(who) ? "A presenter now — becomes backstage" : p.mode === "viewer" ? "Watching" : "In the room");
        nm.append(sm);
        b.append(av, nm);
        b.title = why || (pickKind === "p" ? "Make " + name + " a presenter" : "Make " + name + " backstage");
        b.addEventListener("click", () => { if (roleAct(who, pickKind)) closePicker(); });
        rows.push(b);
      }
      if (!rows.length) { const e = document.createElement("div"); e.className = "none"; e.textContent = q ? "Nobody by that name in the room." : "Nobody else in the room to add."; rows.push(e); }
      $(".pkl").replaceChildren(...rows);
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
        const ready = v.role === "presenter" ? (mine.adopted || !!mine.blobs[i]) : !!v.ready;   // 0.21.91: a handed-over deck reads the store
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
             paintVid: () => paintVid(), drawVid: () => drawVid(), vidPress: (op, t) => vidPress(op, t),   // 0.21.87
             people: () => pplModel(deck()), picker: (k) => openPicker(k), pickerClose: () => closePicker(), role: (w, r) => roleAct(w, r), now: (w) => curAct(w),   // 0.21.91
             end: () => endPress(), allow: (w, on) => allowAct(w, !!on) };
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
    const fk = mode + "/" + rec.ar + "/" + (rec.cn || "") + "/" + (src ? (src.kind === "cut" ? "c" + (unp ? unp.n : 0) : "b" + (src.img.timestamp ?? Math.random())) : "none/" + (rec.cam || ""));
    if (!resized && fk === o.camFk) return true;
    o.camFk = fk;
    g.clearRect(0, 0, W, H);
    const L = presLayout(mode, W, H, rec.ar, src ? src.ar : 16 / 9, !!(src && src.kind === "cut"));
    const n = drawCam(g, L, src, W, H, camLabel(rec));
    o.tagged = n && multiPres(rec) ? drawTag(g, L, rec.cn, W, H) : "";   // 0.21.91: the presenter presenting now, by name
    const key = rec.id + "/" + mode + "/" + (src ? src.kind : "") + "/" + (rec.cam || "") + "/" + (rec.cut || "");
    if (n && o.camPainted !== key) { o.camPainted = key; T("cam-paint", { id: rec.id, idx: rec.idx, who: "overlay", mode, kind: src.kind, cur: rec.cur || "", cam: rec.cam || "", cut: rec.cut || "" }); }
    o.camKind = src ? src.kind : ""; o.camN = (o.camN || 0) + n;
    return true;
  }
  const slideRectFn = (rec) => (W, H) => presLayout(modeOf(rec), W, H, rec.ar, 16 / 9, true).slide;
  // 0.21.91: a deck with more than one presenter names the one presenting now on the camera layer (a small tag at their picture)
  const multiPres = (rec) => !!(rec && Array.isArray(rec.ps) && rec.ps.length > 1);
  function drawTag(g, L, name, W, H) {
    if (!L.cam || !name) return "";
    const r = L.cam, clip = L.clip || { x: 0, y: 0, w: W, h: H };
    const fs = Math.max(10, Math.min(20, Math.round(Math.min(W, H) * 0.028)));
    g.save();
    g.font = "600 " + fs + "px 'Segoe UI', system-ui, sans-serif";
    const tw = g.measureText(name).width, ph = Math.round(fs * 0.45), h = fs + ph * 2 / 1.4, w = tw + ph * 2;
    const left = L.kind === "cut" ? r.x + r.w * 0.18 : r.x + Math.max(4, r.w * 0.04);
    const bottom = Math.min(r.y + r.h, clip.y + clip.h, H) - Math.max(4, fs * 0.5);
    const x = Math.max(clip.x + 4, Math.min(left, clip.x + clip.w - w - 4)), y = bottom - h;
    g.beginPath(); if (g.roundRect) g.roundRect(x, y, w, h, h / 2); else g.rect(x, y, w, h);
    g.fillStyle = "rgba(10,16,24,0.78)"; g.fill();
    g.fillStyle = "#ffffff"; g.textAlign = "left"; g.textBaseline = "middle";
    g.fillText(name, x + ph, y + h / 2 + 1);
    g.restore();
    return name;
  }
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
    // backstage: the preview in my presenter view draws the same pictures; 0.21.91: so does mine when another presenter presents
    if (mine && mine.ms && mine.cur !== myPerson() && cutMode(mine.ms.eff) && mine.ms.cut && !cuts.includes(mine.ms.cut)) cuts.push(mine.ms.cut);
    const hs = hide.sort().join("|"), cs = cuts.sort().join("|");
    if (hs !== hideSig) { hideSig = hs; try { window.__presCamHide?.(hide); } catch {} T("cam-hide", { who: hs }); }
    if (cs !== cutSig) { cutSig = cs; try { window.__presCutWant?.(cuts); } catch {} T("cut-want", { who: cs }); }
  }

  // ---- the presenter: the chosen mode, the camera, the cut-out, backstage's mic / camera control ------------------------------
  // 0.21.91 (Kenton: "allow them to show their camera instead of the main presenters camera while they are presenting their part of
  // the slides" + "Backstage can control my mic and camera should be an option per backstage person"): every PRESENTER's page (the
  // owner's and each added presenter's) keeps its OWN camera / cut-out / mic state here (`self`) and publishes it in its room.json
  // `presCo` {cap, id, al, cam, cut, nocut, live, av, ack}. Its cut-out runs only while it is that presenter's turn (pres.cur) in
  // Standout / Reporter with the camera on (and it encodes only while somebody subscribes). The OWNER copies the camera fields of
  // the presenter presenting now into `pres` (cam / cut / cme / nocut / cwhy) -- one record, so a hand-over swaps the person in one
  // step, and older KASTRs follow it too. Mic / camera requests are answered by the TARGET presenter's own page: the requester must
  // be backstage in the deck, that presenter must allow that person (`al`, ON for each newly added backstage person), the deck live.
  const CAP = 2;   // presCo.cap: 2 = this KASTR can co-present (0.21.91)
  const self = { id: "", al: new Set(), alSeen: new Set(), bp: false, bpAt: 0, note: null, ack: null, avSeq: new Map(),
                 ms: { cutOn: false, cam: "", cut: "", nocut: "", live: false, mic: "none", camSt: "off", hw: false, turn: false } };
  let coSig = "";
  function presentingDeck() {   // the deck I present (its owner, or an added presenter) -> {id, owner, rec?, bk?} | null
    if (mine) return { id: mine.id, owner: true };
    for (const bk of backstage.values()) if (bk.pr && bk.K && !bk.ended) return { id: bk.rec.id, owner: false, rec: bk.rec, bk };
    return null;
  }
  function deckBs(pd) { return pd.owner ? [...mine.bs.keys()] : (pd.rec.bs || []).map((b) => b.p); }
  function coPublish() {
    if (!pkPublished) return;   // nothing to say until a presentation is in my room
    const pd = presentingDeck(), s = self.ms;
    const o = { cap: CAP };
    if (pd) {
      o.id = pd.id; o.al = [...self.al]; o.cam = s.cam; o.cut = s.cut; o.nocut = s.nocut; o.live = s.live ? 1 : 0;
      o.av = { m: s.mic, c: s.camSt, bp: self.bp ? 1 : 0, n: self.note ? self.note.t : "", na: self.note ? self.note.at : 0, nb: self.note ? self.note.by : "" };
      if (self.ack) o.ack = self.ack;
    }
    if (endMark && Date.now() - endMark.at < 60000) o.end = endMark.id;
    if (relMark && Date.now() - relMark.at < 60000) o.rel = relMark.id;
    Object.assign(o, coExtra());
    const sig = JSON.stringify(o);
    if (sig === coSig) return;
    coSig = sig;
    stateSet("presCo", o);
  }
  let coExtra = () => ({});   // (audience mute: my raised hand)
  function camNow() { try { return window.__presCut?.camInfo?.() || null; } catch { return null; } }
  function selfTick() {   // my own camera / cut-out / mic as a presenter of a deck (owner or added)
    const pd = presentingDeck(), s = self.ms, C = window.__presCut;
    if (!pd || pd.id !== self.id) {
      if (s.cutOn) { s.cutOn = false; try { C?.stop(); } catch {} T("cut-stop", { id: self.id, who: "self" }); }
      self.id = pd ? pd.id : ""; self.al.clear(); self.alSeen.clear(); self.bp = false; self.note = null; self.ack = null; self.avSeq.clear();
      Object.assign(s, { cam: "", cut: "", nocut: "", live: false, turn: false });
    }
    if (!pd) { coPublish(); return; }
    const bs = deckBs(pd);   // Kenton: a newly added backstage person may control my mic + camera until I say otherwise
    for (const p of bs) if (!self.alSeen.has(p)) { self.alSeen.add(p); self.al.add(p); }
    for (const p of [...self.alSeen]) if (!bs.includes(p)) { self.alSeen.delete(p); self.al.delete(p); }
    const ci = camNow();
    let av = null; try { av = window.__presAV?.state?.() || null; } catch {}
    const live = !!(ci && ci.live);
    if (self.bp && (!ci || (live && Date.now() - self.bpAt > 4000))) self.bp = false;   // the camera is back (whoever resumed it), or gone
    const cm = pd.owner ? mine.cm : (modeOk(pd.rec.cm) ? pd.rec.cm : "content");
    const cur = pd.owner ? mine.cur : (pd.rec.cur || pd.rec.own || "");
    s.turn = cur === myPerson();
    const wantCut = s.turn && live && cutMode(cm) && !!C && ci.canCut !== false && !(pd.bk && pd.bk.orphan);
    if (wantCut && !s.cutOn) { s.cutOn = true; try { C.start(); } catch (e) { console.warn("KASTR pres: cut-out", e); } T("cut-start", { id: pd.id }); }
    if (!wantCut && s.cutOn) { s.cutOn = false; try { C.stop(); } catch {} T("cut-stop", { id: pd.id }); }
    let cs = null; try { cs = s.cutOn ? C.state() : null; } catch {}
    s.live = live;
    s.cam = live ? ci.path : "";
    s.cut = cs && cs.ready ? cs.path : "";
    s.nocut = ci && ci.canCut === false ? (ci.why || "this computer cannot cut you out of your background") : !C ? "this KASTR cannot" : "";
    s.mic = av ? av.mic : "none";
    s.camSt = !ci ? "off" : ci.live ? "on" : self.bp ? "paused" : "off";
    s.hw = !!(av && av.hw);
    coPublish();
  }
  function modeInit(m) {
    const ci = camNow();
    m.cm = ci && ci.live ? "standout" : "content";   // Kenton: Standout when the camera is on, else Content only
    m.rbg = RBG_DEFAULT;   // Reporter's backdrop: the first ASI background
    m.ms = { eff: "content", cam: "", cut: "", nocut: "", why: "", sig: "" };   // what the room is shown: the presenter presenting now
    T("mode", { id: m.id, who: m.cm, why: "start" });
    modeTick();
  }
  function modeFields() {
    const m = mine;
    if (!m || !m.ms) return {};
    const s = m.ms, o = self.ms;
    return { cm: m.cm, cme: s.eff, cam: s.cam, cut: s.cut, nocut: s.nocut, cwhy: s.why, rbg: m.rbg || RBG_DEFAULT,
             // av / ack: MY mic + camera (what a 0.21.89/0.21.90 backstage page reads; 0.21.91 pages read each presenter's presCo)
             av: { m: o.mic, c: o.camSt, bp: !!self.bp, ok: self.al.size > 0, n: self.note ? self.note.t : "", na: self.note ? self.note.at : 0, nb: self.note ? self.note.by : "" },
             ack: self.ack || null };
  }
  function modeTick() {
    selfTick();
    const m = mine;
    if (!m || !m.ms) return;
    const s = m.ms, me = myPerson();
    if (m.cur !== me) {   // the presenter presenting now: gone (or no longer a presenter) for 4 s -> back to me
      const ok = m.ps.some((x) => x.p === m.cur) && hereNow(m.cur) && canCo(m.cur);
      if (ok) m.curGoneAt = 0;
      else if (!m.curGoneAt) m.curGoneAt = Date.now();
      else if (Date.now() - m.curGoneAt > 4000) { T("cur-back", { id: m.id, who: m.cur }); m.cur = me; m.curGoneAt = 0; }
    }
    const co = m.cur === me ? null : coOf(m.cur);
    const src = m.cur === me ? self.ms : co && co.id === m.id ? co : {};
    const live = !!src.live;
    s.eff = live ? m.cm : "content";
    s.cam = live ? String(src.cam || "") : "";
    s.cut = live && cutMode(m.cm) ? String(src.cut || "") : "";
    s.nocut = String(src.nocut || "");
    const bp = m.cur === me ? self.bp : !!(src.av && src.av.bp);
    s.why = live ? "" : bp ? "bs" : "off";
    const sig = JSON.stringify([m.cm, m.rbg, m.cur, s.eff, s.cam, s.cut, s.nocut, s.why, self.ms.mic, self.ms.camSt, self.bp, self.al.size > 0, self.note && self.note.at, self.ack && self.ack.s, m.ps.length, modeSigExtra()]);
    if (sig !== s.sig) {
      const first = !s.sig;
      s.sig = sig;
      if (!first) { T("mode-pub", { id: m.id, who: s.eff, cur: m.cur }); publishVid(); }
      try { view.paint(); } catch {}
    }
  }
  let modeSigExtra = () => "";   // (audience mute)
  setInterval(() => { try { modeTick(); } catch (e) { console.warn("KASTR pres: modes", e); } }, 300);
  function modeEnd(m) {
    if (self.ms.cutOn) { self.ms.cutOn = false; try { window.__presCut?.stop(); } catch {} }
    try { window.__presCut?.camVideoStop?.(); } catch {}
  }
  function setMode(cm, by) {   // a presenter's own choice, or an accepted backstage / co-presenter one
    const m = mine;
    if (!m || !modeOk(cm) || !m.ms) return false;
    m.modeBy = by || myPerson();
    if (m.cm === cm) return true;
    m.cm = cm;
    T("mode", { id: m.id, who: cm, by: m.modeBy });
    modeTick();
    return true;
  }
  function avNotice(text, by) {
    self.note = { t: text, at: Date.now(), by };
    presNote(text, 6000, "event");   // the presenter view's notice line -- or a toast on the main page when the view is closed
  }
  function avApply(who, op, seq) {   // a backstage person's mic / camera request TO ME -- checked here, on my own page
    const pd = presentingDeck();
    const name = nameOfPerson(who), me = nameOfPerson(myPerson());
    const answer = (ok, why) => { self.ack = { p: who, s: seq, ok, why: why || "" }; T(ok ? "av-apply" : "av-deny", { id: pd && pd.id, who: op, by: who, why }); modeTick(); };
    if (!pd) return answer(false, "the presentation is over");
    if (!deckBs(pd).includes(who)) return answer(false, name + " is not backstage");
    if (!["mute", "unmute", "pause", "resume"].includes(op)) return answer(false, "not a mic or camera request");
    if (!self.al.has(who)) return answer(false, me + " hasn't allowed you to control their mic and camera");
    const AV = window.__presAV;
    if (!AV) return answer(false, "this KASTR cannot");
    if (op === "mute" || op === "unmute") {
      const r = AV.mic(op === "mute");
      if (!r || !r.ok) return answer(false, (r && r.why) || "the microphone is not available");
      if (!r.noop) avNotice((op === "mute" ? "Muted by " : "Unmuted by ") + name, who);
      return answer(true);
    }
    const ci = camNow();
    if (!ci) return answer(false, me + "'s camera is off");
    if (op === "pause") {
      if (!ci.live) return answer(true);   // already not sending a picture: nothing to do
      const r = AV.cam(true);
      if (!r || !r.ok) return answer(false, (r && r.why) || "the camera did not pause");
      self.bp = true; self.bpAt = Date.now();
      if (!r.noop) avNotice("Video paused by " + name, who);
      return answer(true);
    }
    if (ci.live) return answer(true);   // resume: already on
    if (!self.bp) return answer(false, me + "'s camera is off");   // backstage resumes only what backstage paused
    const r = AV.cam(false);
    if (!r || !r.ok) return answer(false, (r && r.why) || "the camera did not resume");
    self.bp = false;
    if (!r.noop) avNotice("Video resumed by " + name, who);
    return answer(true);
  }
  // 0.21.91: requests that reach a presenter who is not the owner -- mic / camera requests addressed to me
  function ctlArrived(path, ctl) {
    if (mine && ctl.id === mine.id) { applyIntent(path, ctl); return; }
    const pd = presentingDeck();
    if (!pd || pd.id !== ctl.id) return;
    const who = personOfPath(path), me = myPerson();
    const first = !self.avSeq.has(who), last = self.avSeq.get(who) || 0;
    let top = last;
    for (const o of ctlOps(ctl)) {
      if (!(o.seq > last) || o.id !== pd.id) continue;
      top = Math.max(top, o.seq);
      if (first && Math.abs(Date.now() - (Number(o.at) || 0)) > 15000) continue;   // an old request I never saw: not now
      if (o.av && typeof o.av === "object" && o.av.to === me) avApply(who, o.av.op, o.seq);
    }
    self.avSeq.set(who, top);
  }
  // backstage / co-presenters: the requests (presCtl, like Next / Back)
  function sendModeIntent(deckId, cm) {
    const bk = backstage.get(deckId);
    if (!bk || !modeOk(cm) || !bk.rec.cm) return false;   // a presenter without modes (older KASTR): never asked
    ctlSend({ id: deckId, bv: bk.rec.ver, to: bk.rec.idx, cm });
    bk.optCm = cm; bk.optCmAt = Date.now();
    T("mode-intent", { id: deckId, who: cm });
    return true;
  }
  function sendAvIntent(deckId, op, to) {   // 0.21.91: to = the presenter whose mic / camera (default: the one presenting now)
    const bk = backstage.get(deckId);
    if (!bk || !["mute", "unmute", "pause", "resume"].includes(op)) return false;
    const rec = bk.rec, co = Array.isArray(rec.ps) && rec.ps.length;
    const tgt = to || rec.cur || rec.own || personOfPath(bk.path);
    if (!co && !rec.av) return false;   // an older presenter without mic / camera control
    const av = { op };
    if (co) av.to = tgt;   // an older owner reads {op} as "mine"
    const ctl = ctlSend({ id: deckId, bv: rec.ver, to: rec.idx, av });
    bk.avAsk = bk.lastAsk = { op, seq: ctl.seq, at: Date.now(), to: co ? tgt : "" };
    T("av-intent", { id: deckId, who: op, to: av.to || "" });
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
  #presView .avrow { grid-column:1 / -1; display:flex; flex-wrap:wrap; gap:8px; align-items:center; font-size:13px; }
  #presView .avrow:empty { display:none; }
  #presView .avsw { display:inline-flex; flex-direction:row; gap:6px; align-items:center; cursor:pointer; white-space:nowrap; font-size:13px; color:#e6edf3; margin:0; }
  #presView .avsw input { display:inline-block; width:auto; height:auto; margin:0; flex:none; }
  #presView .avnote { color:#8fd3ff; }
  #presView .avwhy { color:#ffcf7a; flex-basis:100%; }
  #presView .avwhy:empty { display:none; }
  #presView .avrow button.off { background:#5c1d1d; border-color:#8a2b2b; }
  #presView .avrow button:disabled { opacity:.5; cursor:not-allowed; }
  #presView .avto { display:inline-flex; flex-wrap:wrap; gap:4px; align-items:center; flex-basis:100%; }
  #presView .avto .avtol { color:#8aa0b5; font-size:12px; }
  #presView .avto button { padding:2px 9px; font-size:12px; border-radius:999px; }
  #presView .avto button.on { background:#0b5c86; border-color:#1592d1; }
  #presView .avto button.no { opacity:.6; text-decoration:line-through; }
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
    const side = root.querySelector(".pmode") || root.querySelector(".side");   // 0.21.91: in the "Presenter mode" panel
    if (!side) return;
    side.insertBefore(box, side.firstChild);
    mui = { box, pv: box.querySelector(".pvcv"), why: box.querySelector(".mwhy"), av: box.querySelector(".avrow"), btns: [...box.querySelectorAll(".modes button")], avSig: "", pvAt: 0, still: { key: "", bmp: null } };
    { const pav = root.querySelector(".pav"); if (pav) pav.appendChild(mui.av); }   // 0.21.91: mic, camera + audience in their own panel
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
    const me = myPerson();
    if (v.role === "presenter") {
      const s = mine.ms || {};
      return { v, role: "presenter", cm: mine.cm, rbg: mine.rbg, eff: s.eff || "content", why: s.why, nocut: s.nocut, cutOn: !!s.cut, rec: null,
               cur: mine.cur, turn: mine.cur === me, cn: nameOfPerson(mine.cur), roomCam: { cam: s.cam, cut: s.cut } };
    }
    const bk = backstage.get(v.id);
    const rec = bk && bk.rec;
    if (!rec) return null;
    const opt = bk.optCm && Date.now() - bk.optCmAt < 1500 && rec.cm !== bk.optCm ? bk.optCm : null;
    const cur = rec.cur || rec.own || personOfPath(bk.path);
    return { v, role: v.role, cm: opt || rec.cm || "content", rbg: rec.rbg, eff: modeOf(rec), why: rec.cwhy || "", nocut: rec.nocut || "", av: rec.av || null, cutOn: !!rec.cut, rec, bk, has: !!rec.cm,
             cur, turn: v.role === "copresenter" && cur === me, cn: rec.cn || nameOfPerson(cur) };
  }
  function modeUiPaint() {
    if (!mui) return;
    const mv = modeView();
    mui.box.style.display = mv && (mv.role === "presenter" || mv.has) ? "" : "none";
    if (!mv) return;
    const P = mv.role !== "backstage";
    mui.rbgs.style.display = P && mv.cm === "reporter" ? "" : "none";   // Kenton: the presenters pick, shown in Reporter
    for (const b of mui.rbgs.children) b.classList.toggle("on", b.dataset.rbg === (mv.rbg || RBG_DEFAULT));
    for (const b of mui.btns) { b.classList.toggle("on", b.dataset.mode === mv.cm); b.classList.toggle("eff", b.dataset.mode === mv.eff && mv.eff !== mv.cm); }
    const who = mv.turn ? "" : mv.cn;   // 0.21.91: the presenter presenting now
    let why = "";
    if (mv.cm !== "content" && mv.eff === "content") {
      if (mv.why === "bs") { const av = mv.turn ? modeFields().av : (mv.rec && mv.rec.av) || null; why = (av && av.nb ? "Video paused by " + nameOfPerson(av.nb) : "Video paused by backstage") + " — showing the slide only"; }
      else why = (mv.turn ? "Camera off" : who + "'s camera is off") + " — showing the slide only";
    } else if (cutMode(mv.eff) && mv.nocut) {
      why = (mv.turn ? "Your camera cannot be cut out here (" + mv.nocut + ")" : who + "'s camera cannot be cut out") + " — the room sees it in a box";
    }
    if (mui.why.textContent !== why) mui.why.textContent = why;
    paintAvRow(mv);
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
  // 0.21.91: a backstage person's mic / camera target -- the presenter presenting now unless they picked another
  function avTargets(mv) {
    const rec = mv.rec, me = myPerson();
    const ps = Array.isArray(rec.ps) && rec.ps.length ? rec.ps.map((x) => x.p) : [rec.own || personOfPath(mv.bk.path)];
    return ps.filter((p) => p !== me).map((p) => {
      const co = coOf(p), old = !(Array.isArray(rec.ps) && rec.ps.length);
      const av = co && co.id === rec.id ? co.av : old ? rec.av : null;
      const ack = co && co.id === rec.id ? co.ack : old ? rec.ack : null;
      const allowed = old ? !!(rec.av && rec.av.ok) : !!(co && co.id === rec.id && Array.isArray(co.al) && co.al.includes(me));
      return { p, name: nameOfPerson(p), av, ack, allowed, here: hereNow(p) && (old || !!co) };
    });
  }
  function paintAvRow(mv) {
    const row = mui.av;
    if (mv.role !== "backstage") {   // a presenter: MY mic + camera (each backstage person's control is a toggle on their row)
      const av = modeFields().av || { m: self.ms.mic, c: self.ms.camSt, n: self.note ? self.note.t : "", na: self.note ? self.note.at : 0 };
      const sig = "p|" + (av.n || "") + "|" + Math.floor((Date.now() - (av.na || 0)) / 10000) + "|" + av.m + "|" + av.c + "|" + avExtraSig();
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
      avExtra(row);
      if (av.n) { const n = document.createElement("span"); n.className = "avnote"; n.textContent = av.n + " · " + ago(av.na); row.append(n); }
      return;
    }
    if (!mv.rec.av && !(Array.isArray(mv.rec.ps) && mv.rec.ps.length)) { if (mui.avSig !== "none") { mui.avSig = "none"; row.replaceChildren(); } return; }
    const ts = avTargets(mv);
    let to = mui.avTo && ts.some((t) => t.p === mui.avTo) ? mui.avTo : null;
    if (!to) to = (ts.find((t) => t.p === mv.cur) || ts[0] || {}).p || "";
    const t = ts.find((x) => x.p === to) || { name: "", av: null, allowed: false };
    const av = t.av || {};
    const ask = mv.bk.avAsk && Date.now() - mv.bk.avAsk.at < 4000 && (!mv.bk.avAsk.to || mv.bk.avAsk.to === to) ? mv.bk.avAsk : null;
    const ack = t.ack && t.ack.p === myPerson() ? t.ack : null;
    const lastAck = ack && mv.bk.lastAsk && ack.s === mv.bk.lastAsk.seq && (!mv.bk.lastAsk.to || mv.bk.lastAsk.to === to) ? ack : null;
    const sig = "b|" + JSON.stringify([ts.map((x) => [x.p, x.allowed, x.here, x.av]), to, mv.cur, ask && ask.seq, lastAck && [lastAck.s, lastAck.ok, lastAck.why]]);
    if (sig === mui.avSig) return;
    mui.avSig = sig;
    row.replaceChildren();
    if (ts.length > 1) {   // whose mic / camera: the presenter presenting now first chosen
      const pick = document.createElement("span"); pick.className = "avto";
      const lab = document.createElement("span"); lab.className = "avtol"; lab.textContent = "Control:";
      pick.append(lab);
      for (const x of ts) {
        const b = document.createElement("button"); b.type = "button"; b.className = "avtob" + (x.p === to ? " on" : "") + (x.allowed ? "" : " no");
        b.dataset.who = x.p;
        b.textContent = x.name + (x.p === mv.cur ? " · now" : "");
        b.title = x.allowed ? "Control " + x.name + "'s mic and camera" : x.name + " hasn't allowed you to control their mic and camera";
        b.addEventListener("click", () => { mui.avTo = x.p; mui.avSig = ""; T("av-target", { who: x.p }); modeUiPaint(); });
        pick.append(b);
      }
      row.append(pick);
    }
    const who = t.name, off = !t.allowed, offWhy = who + " hasn't allowed you to control their mic and camera";
    const mic = document.createElement("button"); mic.type = "button"; mic.className = "avmic";
    const micOn = av.m === "on";
    mic.textContent = !t.av ? "Mic —" : av.m === "none" ? "No microphone" : micOn ? "Mic on · Mute" : "Mic muted · Unmute";
    mic.classList.toggle("off", av.m === "muted");
    mic.disabled = off || !t.av || av.m === "none" || (ask && /mute/.test(ask.op) && !lastAck);
    mic.title = off ? offWhy : av.m === "none" ? who + " has no microphone on" : micOn ? "Mute " + who + "'s microphone (straight away)" : "Unmute " + who + "'s microphone (straight away)";
    mic.addEventListener("click", () => window.__pres.av(micOn ? "mute" : "unmute", to));
    const cam = document.createElement("button"); cam.type = "button"; cam.className = "avcam";
    cam.textContent = !t.av ? "Video —" : av.c === "on" ? "Video on · Pause" : av.c === "paused" ? "Video paused · Resume" : "Camera off";
    cam.classList.toggle("off", av.c !== "on");
    cam.disabled = off || !t.av || av.c === "off" || (ask && /pause|resume/.test(ask.op) && !lastAck);
    cam.title = off ? offWhy : av.c === "off" ? who + "'s camera is off" : av.c === "on" ? "Pause " + who + "'s video (the room sees the slide only while it is their turn)" : "Resume " + who + "'s video";
    cam.addEventListener("click", () => window.__pres.av(av.c === "on" ? "pause" : "resume", to));
    row.append(mic, cam);
    const why = document.createElement("span"); why.className = "avwhy";
    why.textContent = off ? offWhy : lastAck && !lastAck.ok ? "Not done: " + lastAck.why : av.c === "off" ? who + "'s camera is off" : "";
    row.append(why);
  }
  let avExtra = () => {}, avExtraSig = () => "";   // (audience mute: the switch + raised hands)
  // the preview: the same composition the room's tiles draw, small, ~12 a second, while the presenter view is open
  function modeUiFrame() {
    if (!mui || !view.isOpen()) return false;
    const mv = modeView();
    if (!mv || mui.box.style.display === "none") return false;
    if (!mui.box.closest("details")?.open) { if (performance.now() - (mui.paintAt || 0) > 1000) { mui.paintAt = performance.now(); modeUiPaint(); } return true; }   // 0.21.91: no preview while its panel is closed
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
    drawLaid(cv, mui.still.bmp, roomBlank(mv), mv.eff, ar, "", mv.rbg);
    const g = cv.getContext("2d");
    // the slide's video in its spot (moved with the slide)
    let items = [];
    if (!roomBlank(mv)) {
      if (mv.role === "presenter") items = [...mine.vids.values()].filter((e) => e.i === mine.idx && e.st && e.shareId != null && e.sv.kind !== "audio").map((e) => ({ x: e.sv.x, y: e.sv.y, w: e.sv.w, h: e.sv.h, src: window.__presVideo?.frame(e.shareId) || null }));
      else if (mv.rec.idx === v.idx) items = (mv.rec.vids || []).filter((x) => x.i === mv.rec.idx && x.st && x.k !== "a").map((x) => ({ x: x.x, y: x.y, w: x.w, h: x.h, src: window.__presVidFrame?.(x.p) || null }));
    }
    if (items.length) { const R = presLayout(mv.eff, W, H, ar, 16 / 9, true).slide; for (const it of items) if (it.src) { try { g.drawImage(it.src, R.x + it.x * R.w, R.y + it.y * R.h, it.w * R.w, it.h * R.h); } catch {} } }
    if (mv.eff !== "content") {
      let src = null;
      if (mv.turn) {   // it is MY turn: my own picture, straight from this page
        const P = window.__presCut;
        const p = cutMode(mv.eff) && self.ms.cut ? P?.person?.() : null;
        if (p) src = { kind: "cut", img: p.img, ar: p.ar, mirror: p.mirror };
        else { const vid = P?.camVideo?.(); if (vid) src = { kind: "box", img: vid, iw: vid.videoWidth, ih: vid.videoHeight, ar: vid.videoWidth / vid.videoHeight }; }
      } else src = camSourceFor(mv.rec || mv.roomCam, mv.eff);   // another presenter's: what the room gets
      const L = presLayout(mv.eff, W, H, ar, src ? src.ar : 16 / 9, !!(src && src.kind === "cut"));
      const n = drawCam(g, L, src, W, H, "Camera starting…");
      if (n && multiPres(mv.rec || mine)) drawTag(g, L, mv.cn, W, H);
      if (n && mui.pvKey !== key + "/" + mv.eff + "/" + mv.cur) { mui.pvKey = key + "/" + mv.eff + "/" + mv.cur; T("pv-paint", { id: v.id, who: mv.role, mode: mv.eff, kind: src && src.kind, cur: mv.cur }); }
    }
    return true;
  }
  let roomBlank = (mv) => mv.v.blank;   // (blackout: what the ROOM sees)
  function modeState() {
    const m = mine;
    return {
      mine: m && m.ms ? { cm: m.cm, eff: m.ms.eff, cam: m.ms.cam, cut: m.ms.cut, nocut: m.ms.nocut, why: m.ms.why, mic: self.ms.mic, camSt: self.ms.camSt, avOk: self.al.size > 0, avBp: self.bp,
                          note: self.note, ack: self.ack, cur: m.cur, og: m.og, cutState: (() => { try { return window.__presCut?.state?.() || null; } catch { return null; } })() } : null,
      self: { id: self.id, al: [...self.al], turn: !!self.ms.turn, cam: self.ms.cam, cut: self.ms.cut, live: self.ms.live, cutOn: self.ms.cutOn, bp: self.bp, ack: self.ack, note: self.note },   // 0.21.91
      tiles: [...overlays.entries()].map(([p, o]) => ({ path: p, mode: modeOf(o.rec), cm: o.rec.cm || null, rbg: o.rec.rbg || null, rbgLoaded: !!(o.rec.rbg && rbgImgs.get(o.rec.rbg)?.ok), cam: o.rec.cam || "", cut: o.rec.cut || "", kind: o.camKind || "", n: o.camN || 0,
                                                        av: o.rec.av || null, ack: o.rec.ack || null, cur: o.rec.cur || "", cn: o.rec.cn || "", tag: o.tagged || "" })),
      hide: hideSig ? hideSig.split("|") : [], cuts: cutSig ? cutSig.split("|") : [], unpacked: unp && !unp.failed ? unp.n : 0,
      ui: mui ? { shown: mui.box.style.display !== "none", on: (mui.btns.find((b) => b.classList.contains("on")) || {}).dataset?.mode || "", why: mui.why.textContent,
                  av: mui.av.textContent, avTo: mui.avTo || "", buttons: [...mui.av.querySelectorAll("button")].map((b) => ({ c: b.className, t: b.textContent, d: b.disabled, title: b.title })) } : null,
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
    if (mine) {   // the presentation belongs to its room and its share: leaving either ends it (0.21.91: or hands it over)
      const c = ctx();
      if (!c || !c.joined || c.channel !== mine.room) { const kept = leaveMine("left the room"); toast(kept ? "You left the room — the presentation goes on with the other presenters." : "The presentation ended (you left the room).", 5000); }
      else if (mine.share && mine.share.id != null && window.__presShare && window.__presShare.alive && !window.__presShare.alive(mine.share.id)) { endMine("share stopped"); toast("The presentation ended (its share was stopped).", 5000); }
    }
    try { ownership(); } catch (e) { console.warn("KASTR pres: hand-over", e); }
  }, 700);
  // ---- 0.21.91: the OWNER role passes on ----------------------------------------------------------------------------------------
  // Kenton: "Work out ... what happens to the deck if the MAIN presenter leaves or drops while added presenters remain." The deck is
  // the store's (encrypted, on the relay host) plus the record one page publishes. Every added presenter holds K (every slide and
  // the notes, through the read token) and the store's write token, so any of them can publish the record, tell the store the
  // live slide and share it. When the owner's record is gone -- it handed the deck over (presCo.rel: at once), or it vanished AND the
  // owner left the room's presence (a drop: after the room's grace) -- plus 2 s for each present presenter before me in the list,
  // and the owner did not END it (presCo.end; the store still serves the deck), the first present presenter publishes
  // the same deck id with og + 1: the same slide, mode, people and presenter presenting now. A returning old owner (a network blip)
  // sees a record of its deck with a higher og and steps down to a co-presenter. Nothing new reaches viewers: the record carries
  // the live slide's key only, as before. A handed-over deck has no slide videos (the files were only on the first owner's page).
  function ownership() {
    const me = myPerson();
    if (mine) {   // a newer owner of my deck (I was away): I step down
      for (const r of remote.values()) {
        const rec = r.pres;
        if (rec && rec.id === mine.id && recBetter(rec, { og: mine.og, own: me })) { T("demote", { id: mine.id, og: rec.og, who: rec.own }); endMine("a newer owner", true); presNote("“" + rec.name + "” is now run from " + nameOfPerson(rec.own) + "'s KASTR — you are still a presenter.", 8000, "event"); schedule(); break; }
      }
      return;
    }
    const now = Date.now();
    for (const bk of backstage.values()) {
      if (!bk.orphan || bk.adopting || bk.ended || !bk.pr || !bk.K || !bk.wt || !bk.rec) continue;
      const rec = bk.rec;
      const order = (rec.ps || []).map((x) => x.p).filter((p) => p !== rec.own && (p === me || (canCo(p) && hereNow(p))));
      const rank = order.indexOf(me);
      if (rank < 0) continue;
      // the owner handed it over (left on purpose): at once; else only once the owner is gone from the room's PRESENCE too
      // (a gap in its room.json alone -- a re-subscribe -- never moves the deck)
      const released = relSeen.has(rec.id);
      if (!released && inPresence(rec.own)) continue;
      if (now - (bk.seenAt || 0) < (released ? 300 : HANDOVER_MS) + rank * 2000) continue;
      bk.adopting = true;
      adopt(bk).catch((e) => console.warn("KASTR pres: take over", e)).finally(() => { bk.adopting = false; });
    }
  }
  async function adopt(bk) {
    const rec = bk.rec, me = myPerson(), c = ctx();
    if (mine || !c || !c.joined) return;
    const t0 = Date.now();
    let r = null;
    try { r = await fetch(baseFor(rec) + "/api/pres/" + rec.id + "/notes.bin?rt=" + encodeURIComponent(bk.rt || ""), { cache: "no-store" }); } catch { return; }   // the relay host away: try again
    if (r.status === 404 || r.status === 403) { bk.ended = true; backstage.delete(rec.id); T("bs-gone", { id: rec.id, why: "store" }); view.paint(); return; }   // ended
    if (!r.ok) return;
    if (backstage.get(rec.id) !== bk || !bk.orphan || mine) return;   // the record came back meanwhile (or someone else took it)
    for (const x of remote.values()) if (x.pres && x.pres.id === rec.id) return;
    const meK = await myKeys();
    const base = rec.base;
    const idx = clampI(rec.idx, rec.n);
    let lr = null;
    try { lr = await fetch(base + "/api/pres/" + rec.id + "/live?token=" + encodeURIComponent(bk.wt) + "&i=" + idx, { method: "POST" }); } catch {}
    if (!lr || !lr.ok) { T("adopt-fail", { id: rec.id, why: lr ? lr.status : "net" }); return; }
    if (mine || backstage.get(rec.id) !== bk) return;
    const m = {
      id: rec.id, token: bk.wt, rtEnc: rec.rt || "", rt: bk.rt || "", liveIdx: idx, liveChain: Promise.resolve(), via: "handed over", base, room: c.channel, name: rec.name, kind: rec.kind,
      n: rec.n, ar: Number(rec.ar) || 16 / 9, src: null, adopted: true, K: bk.K, keys: bk.keys, notesKey: bk.notesKey, notes: (bk.notes || []).slice(), nv: Number(rec.nv) || 1,
      blobs: new Array(rec.n).fill(null), up: new Array(rec.n).fill(true), busy: [], rendering: null, want: [],
      idx, ver: (Number(rec.ver) || 1) + 1, by: me, blank: rec.blank || null, t0: rec.t0, bs: new Map(), lastSeq: new Map(), share: null, pk: meK.pub,
      warnings: [], startedMs: 0, pubSeq: 0, told: 0, vids: new Map(),
      ps: (rec.ps || []).map((x) => ({ p: x.p, name: x.n || nameOfPerson(x.p), w: "", t: "", pkUsed: "" })), og: (Number(rec.og) || 1) + 1,
      cur: rec.cur && rec.cur !== rec.own && hereNow(rec.cur) ? rec.cur : me,
    };
    for (const b of rec.bs || []) if (b && b.p) m.bs.set(b.p, { name: b.n || nameOfPerson(b.p), w: "", pkUsed: "" });
    if (!m.ps.some((x) => x.p === me)) m.ps.push({ p: me, name: nameOfPerson(me), w: "", t: "", pkUsed: "" });
    for (const [p, x] of remote) if (x.ctl) {   // the requests already made were for the old owner: not again
      const who = personOfPath(p);
      for (const o of ctlOps(x.ctl)) if (o.id === m.id) m.lastSeq.set(who, Math.max(m.lastSeq.get(who) || 0, o.seq));
    }
    m.cm = modeOk(rec.cm) ? rec.cm : "content";
    m.rbg = rbgOk(rec.rbg) ? rec.rbg : RBG_DEFAULT;
    m.ms = { eff: "content", cam: "", cut: "", nocut: "", why: "", sig: "" };
    adoptExtra(m, rec);
    m.vs = Number(rec.vs) || 0;
    m.resumeVids = Array.isArray(rec.vids) ? rec.vids.slice(0, 8) : [];
    backstage.delete(rec.id);
    mine = m;
    T("adopt", { id: m.id, og: m.og, from: rec.own, ms: Date.now() - t0, gone: Date.now() - (bk.seenAt || 0) });
    modeTick();
    startShare();
    publish();
    rewrap();
    presNote(nameOfPerson(rec.own) + " left — “" + m.name + "” now runs from your KASTR. The room still sees slide " + (idx + 1) + ".", 9000, "event");
    view.paint();
    if (m.vs) storedVideos(m, bk.rt).then((src) => { if (mine !== m) return; m.src = src; T("vid-src", { id: m.id, n: m.vs }); syncVideos(); view.paint(); })
      .catch((e) => console.warn("KASTR pres: the deck's videos", e));
  }
  let adoptExtra = () => {};   // (audience mute)
  window.addEventListener("resize", () => { for (const o of overlays.values()) o.key = ""; schedule(); });

  // ---- 0.21.91: AUDIENCE MUTE ----------------------------------------------------------------------------------------------------
  // Kenton: "By default when presenting, everyone else should be muted and not able to unmute themselves unless they are added as a
  // presenter." Decided: only PRESENTERS talk while a presentation is live -- the audience AND backstage are muted and cannot
  // unmute (backstage still runs slides, notes and mic / camera control). The record carries it, so late joiners obey:
  //   am  1 = "Audience muted" (ON when a presentation starts; any presenter turns it off for Q&A and back on)
  //   lt  the people a presenter let talk (a raised hand -> "Let <name> talk"): they MAY unmute (never forced) until they lower
  //       their hand / Done, a presenter mutes them again, or the presentation ends
  //   hx  [[person, hand at]]: hands a presenter dismissed (or took the talk back from) -- that page lowers its hand
  // A raised hand is one small field on the asker's own page: presCo.hand {id, at} (at most one change a second and a half).
  // Enforced on BOTH sides: (a) my own page mutes its mic through the real path (__presAV.mic -> micMuted + sendControl +
  // renderMine) and the page refuses to unmute it (the Mic button, the microphone's own mute key, a control message); (b) EVERY
  // 0.21.91 page plays a PERSON'S MIC at gain 0 (its volume path -- the warm floor, never `muted`, never a disconnect) unless that
  // person may talk now, so an older KASTR or a modified page that ignores the lock is not heard here. A person's mic = the audio
  // of a person's camera stream in my room: <room>/<host>/<op>/camera(-n).hang of a page that is not a box (publisher / relay
  // mode). Boxes, RTSP cameras, media files, screen shares, slide videos and sound clips keep their sound.
  const talk = { locked: "", was: null, unlockMic: null, active: false, allowed: new Set(), boxes: new Set(), sig: "", handAt: 0, lastHand: 0, freeBy: "" };
  let handState = null;   // my raised hand {id, at}
  coExtra = () => (handState ? { hand: handState } : {});
  function liveDecks() {   // every presentation live in my room, as its record says (mine first)
    const out = [];
    if (mine) out.push({ id: mine.id, am: mine.am ? 1 : 0, ask: mine.ask === 0 ? 0 : 1, own: myPerson(), ps: mine.ps.map((x) => x.p), lt: [...(mine.lt || [])], hx: [...(mine.hx || new Map())], cn: nameOfPerson(mine.cur) });
    for (const { rec } of deckRecs().values()) {
      if (mine && rec.id === mine.id) continue;
      out.push({ id: rec.id, am: Number(rec.am) ? 1 : 0, ask: rec.ask === undefined || Number(rec.ask) ? 1 : 0, own: rec.own || "", ps: Array.isArray(rec.ps) ? rec.ps.map((x) => x.p) : [], lt: Array.isArray(rec.lt) ? rec.lt.map(String) : [],
                 hx: Array.isArray(rec.hx) ? rec.hx : [], cn: rec.cn || nameOfPerson(rec.own || "") , old: !Array.isArray(rec.ps) });
    }
    return out;
  }
  const mayTalk = (d, who) => !d.am || who === d.own || d.ps.includes(who) || d.lt.includes(who);
  function lockReason(ds) {
    const me = myPerson();
    for (const d of ds) if (!d.old && d.am && !mayTalk(d, me)) return "Muted while " + d.cn + " presents";
    return "";
  }
  const PERSON_CAM = /^camera(-\d+)?\.hang$/;
  function silent(path) {   // a person's mic that may not be heard now (this page plays it at gain 0)
    if (!talk.active) return false;
    const p = String(path || "").split("/");
    if (p.length !== 4 || !PERSON_CAM.test(p[3])) return false;
    const c = ctx();
    if (!c || p[0] !== c.channel) return false;
    const key = (p[1] + "/" + p[2]).toLowerCase();
    return !talk.allowed.has(key) && !talk.boxes.has(key);
  }
  function talkTick() {
    const ds = liveDecks().filter((d) => !d.old);
    const me = myPerson();
    // who may be heard: in every deck with the audience muted, its presenters + the people let talk (and boxes, always)
    const muting = ds.filter((d) => d.am);
    const allowed = new Set();
    for (const d of muting) for (const p of [d.own, ...d.ps, ...d.lt]) if (p) allowed.add(String(p).toLowerCase());
    const boxes = new Set();
    for (const p of (ctx()?.people || [])) if (/^(publisher|publisher-relay|relay)$/.test(p.mode)) boxes.add((p.host + "/" + (p.op || p.peer)).toLowerCase());
    // a deck where I am the audience but let talk does not lock me -- yet another deck with its audience muted does
    const lk = lockReason(muting);
    const AV = window.__presAV;
    let st = null; try { st = AV?.state?.() || null; } catch {}
    const micOn = !!(st && st.mic === "on");
    let changed = false;
    if (lk) {
      if (!talk.locked) { talk.locked = lk; if (talk.was === null) talk.was = micOn; changed = true; T("talk-lock", { who: lk }); }
      else if (talk.locked !== lk) { talk.locked = lk; changed = true; }
      if (micOn) { try { AV.mic(true); } catch {} T("talk-mute", { who: me }); }   // the real path: micMuted + sendControl + renderMine
    } else if (talk.locked) {
      talk.locked = ""; talk.unlockMic = micOn; changed = true; T("talk-free", { who: me });
    }
    if (!lk && talk.was !== null && ds.length && talk.unlockMic !== null && micOn !== talk.unlockMic) talk.was = null;   // they took the mic themselves
    if (!ds.length && talk.was !== null) {   // the presentation is over: my mic as it was before it
      const was = talk.was;
      talk.was = null; talk.unlockMic = null;
      if (was && !micOn) { try { AV?.mic(false); } catch {} }
      T("talk-restore", { who: was ? "on" : "off" });
      changed = true;
    }
    // my hand: lowered when the deck is gone, the audience is not muted any more, or a presenter dismissed it / took the talk back
    if (handState) {
      const d = ds.find((x) => x.id === handState.id);
      const dismissed = d && d.hx.some((h) => Array.isArray(h) && h[0] === me && Number(h[1]) === handState.at);
      if (!d || !d.am || !d.ask || dismissed) { if (dismissed) toast("A presenter lowered your hand.", 5000); else if (d && d.am && !d.ask) toast("The presenters turned Ask to speak off — your hand is down.", 5000); handState = null; T("hand-down", { why: !d ? "gone" : !d.am ? "unmuted" : !d.ask ? "ask off" : "dismissed" }); changed = true; coPublish(); }
    }
    const sig = JSON.stringify([!!muting.length, [...allowed].sort(), [...boxes].sort(), talk.locked]);
    if (sig !== talk.sig) { talk.sig = sig; talk.active = !!muting.length; talk.allowed = allowed; talk.boxes = boxes; changed = true; }
    if (changed) { try { window.__presTalkChanged?.(); } catch {} paintTalkPill(); try { view.paint(); } catch {} }
    else paintTalkPill();
  }
  setInterval(() => { try { talkTick(); } catch (e) { console.warn("KASTR pres: audience", e); } }, 300);
  function raiseHand(on) {   // the audience's "Ask to speak" / Lower hand / Done
    const now = Date.now();
    if (now - talk.lastHand < 1500) return false;   // cheap: at most one change a second and a half
    const d = liveDecks().find((x) => !x.old && x.am && !mayTalk(x, myPerson())) || (handState && liveDecks().find((x) => x.id === handState.id));
    if (on) { if (!d || handState || !d.ask) return false; handState = { id: d.id, at: now }; }   // 0.21.91: not while Ask to speak is off
    else { if (!handState) return false; handState = null; }
    talk.lastHand = now;
    T(on ? "hand-up" : "hand-down", { id: d && d.id, why: "me" });
    ensurePk(); coPublish(); paintTalkPill();
    return true;
  }
  // the owner page: the switch, the hands, who may talk
  function audienceInit(m) { m.am = 1; m.ask = 1; m.lt = new Set(); m.hx = new Map(); }
  // ask: 0 = "Ask to speak" off (Kenton) -- no raised hands: the pill offers none, raised ones go down, new ones are refused here
  // and on every page that reads the record; absent (an older owner) = on
  function audFields() { const m = mine; return m && m.lt ? { am: m.am ? 1 : 0, ask: m.ask === 0 ? 0 : 1, lt: [...m.lt], hx: [...m.hx].slice(-24) } : {}; }
  function askPreset(m, o) { if (o && typeof o === "object" && (o.ask === 0 || o.ask === false || (o.audience && (o.audience.ask === 0 || o.audience.ask === false)))) m.ask = 0; }
  function setAsk(v, by) {
    const m = mine;
    if (!m || !m.lt) return false;
    const nv = v ? 1 : 0;
    if ((m.ask === 0 ? 0 : 1) === nv) return true;
    m.ask = nv;
    if (!nv) { for (const p of [...m.lt]) { m.lt.delete(p); } for (const h of hands(m.id)) m.hx.set(h.p, h.at); }   // every hand down, nobody let talk any more
    T("ask", { id: m.id, who: nv ? "on" : "off", by: by || myPerson() });
    publish(); talkTick(); view.paint();
    return true;
  }
  function askAct(v) {
    const v0 = view.deck();
    if (!v0) return false;
    if (v0.role === "presenter") return setAsk(v, myPerson());
    if (v0.role === "copresenter") return sendPresOp(v0.id, { op: "ask", v: v ? 1 : 0 });
    return false;
  }
  function handOf(p) { const co = coOf(p); return co && co.hand && mine && co.hand.id === mine.id ? Number(co.hand.at) || 0 : 0; }
  function setAm(v, by) {
    const m = mine;
    if (!m || !m.lt) return false;
    const nv = v ? 1 : 0;
    if (m.am === nv) return true;
    m.am = nv;
    if (nv) m.lt.clear();   // muted again: whoever was let talk asks again
    T("am", { id: m.id, who: nv ? "on" : "off", by: by || myPerson() });
    publish(); modeTick(); talkTick(); view.paint();
    return true;
  }
  function setTalk(p, v, by) {   // "Let <name> talk" (v) / "Dismiss" or "Mute again" (!v)
    const m = mine;
    if (!m || !m.lt || typeof p !== "string" || !p) return false;
    if (v) { if (!handOf(p) || m.ask === 0) return false; m.lt.add(p); m.hx.delete(p); }
    else { m.lt.delete(p); const at = handOf(p); if (at) m.hx.set(p, at); }
    T(v ? "let-talk" : "no-talk", { id: m.id, who: p, by: by || myPerson() });
    publish(); talkTick(); view.paint();
    return true;
  }
  audienceOp = (pp, who) => {   // a co-presenter's request (presOp)
    if (pp.op === "am") return setAm(!!pp.v, who) || true;
    if (pp.op === "ask") return setAsk(!!pp.v, who) || true;
    if (pp.op === "lt") return setTalk(String(pp.p || ""), !!pp.v, who) || true;
    return false;
  };
  adoptExtra = (m, rec) => { m.am = rec.am === undefined ? 1 : Number(rec.am) ? 1 : 0; m.ask = rec.ask === undefined || Number(rec.ask) ? 1 : 0; m.lt = new Set(Array.isArray(rec.lt) ? rec.lt.map(String) : []); m.hx = new Map(Array.isArray(rec.hx) ? rec.hx.filter((h) => Array.isArray(h)).map((h) => [String(h[0]), Number(h[1]) || 0]) : []); };
  function audiencePrune() {   // the owner: someone let talk lowered their hand (Done) -> no longer let talk
    const m = mine;
    if (!m || !m.lt) return;
    let ch = false;
    for (const p of [...m.lt]) if (!handOf(p)) { m.lt.delete(p); ch = true; T("talk-done", { id: m.id, who: p }); }
    for (const [p, at] of [...m.hx]) if (handOf(p) !== at && Date.now() - at > 600000) { m.hx.delete(p); ch = true; }
    if (ch) { publish(); talkTick(); view.paint(); }
  }
  setInterval(() => { try { audiencePrune(); } catch {} }, 700);
  function hands(deckId) {   // the raised hands in the room for this deck: [{p, name, at, talking}]
    const out = [];
    const d = liveDecks().find((x) => x.id === deckId);
    if (!d || !d.ask) return out;   // 0.21.91: Ask to speak off -- a raised hand (an older or a modified page) is not listed
    for (const [path, r] of remote) {
      const h = r.co && r.co.hand;
      if (!h || h.id !== deckId) continue;
      const p = personOfPath(path);
      if (d.hx.some((x) => Array.isArray(x) && x[0] === p && Number(x[1]) === Number(h.at))) continue;
      out.push({ p, name: nameOfPerson(p), at: Number(h.at) || 0, talking: d.lt.includes(p) });
    }
    return out.sort((a, b) => a.at - b.at);
  }
  function panelAvInfo(v) {   // 0.21.91 layout: the "Mic, camera & audience" panel's one line; raised hands need attention
    if (!v) return { text: "", attn: false };
    const d = liveDecks().find((x) => x.id === v.id);
    const hs = d && d.am ? hands(v.id).filter((h) => !h.talking) : [];
    const parts = [];
    if (v.role !== "backstage") parts.push(self.ms.mic === "on" ? "Mic on" : self.ms.mic === "muted" ? "Mic muted" : "No mic");
    if (d && !d.old) parts.push(d.am ? "Audience muted" + (d.ask ? "" : " · no asking") : "Audience may talk");
    if (hs.length) parts.push(hs.length + (hs.length === 1 ? " hand up" : " hands up"));
    if (v.role === "backstage" && talk.locked) parts.push("you are muted");
    return { text: parts.join(" · "), attn: hs.length > 0 && v.role !== "backstage" };
  }
  function amAct(v) {   // the presenter view's "Audience muted" switch (owner: directly; an added presenter: asks the owner)
    const v0 = view.deck();
    if (!v0) return false;
    if (v0.role === "presenter") return setAm(v, myPerson());
    if (v0.role === "copresenter") return sendPresOp(v0.id, { op: "am", v: v ? 1 : 0 });
    return false;
  }
  function talkAct(p, v) {
    const v0 = view.deck();
    if (!v0) return false;
    if (v0.role === "presenter") return setTalk(p, v, myPerson());
    if (v0.role === "copresenter") return sendPresOp(v0.id, { op: "lt", p, v: v ? 1 : 0 });
    return false;
  }
  avExtraSig = () => {
    const v = view.deck();
    if (!v) return "";
    const d = liveDecks().find((x) => x.id === v.id);
    return JSON.stringify([d && d.am, d && d.ask, hands(v.id).map((h) => [h.p, h.talking])]);
  };
  avExtra = (row) => {   // the presenters: "Audience muted" + the raised hands
    const v = view.deck();
    const d = v && liveDecks().find((x) => x.id === v.id);
    if (!d || d.old) return;
    const box = document.createElement("div"); box.className = "audbox";
    const lab = document.createElement("label"); lab.className = "avsw audsw";
    lab.title = "On: only the presenters can talk -- everyone else is muted and cannot unmute (they can ask to speak). Off: everyone may unmute themselves (Q&A).";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.className = "amsw"; cb.checked = !!d.am;
    cb.addEventListener("change", () => amAct(cb.checked));
    lab.append(cb, document.createTextNode("Audience muted"));
    box.append(lab);
    {   // 0.21.91 (Kenton): "Ask to speak" -- on: muted people can raise a hand; off: no hands at all
      const al = document.createElement("label"); al.className = "avsw audsw asklab";
      al.title = "On: people who are muted can raise a hand and a presenter can let them talk. Off: no raised hands (any raised one goes down).";
      const ac = document.createElement("input"); ac.type = "checkbox"; ac.className = "asksw"; ac.checked = !!d.ask;
      ac.addEventListener("change", () => askAct(ac.checked));
      al.append(ac, document.createTextNode("Ask to speak"));
      box.append(al);
    }
    const hs = hands(v.id);
    if (d.am && hs.length) {
      const list = document.createElement("div"); list.className = "hands";
      for (const h of hs) {
        const r = document.createElement("div"); r.className = "hand" + (h.talking ? " talking" : ""); r.dataset.who = h.p;
        const n = document.createElement("span"); n.className = "hn"; n.textContent = (h.talking ? "Talking: " : "Hand up: ") + h.name;
        r.append(n);
        if (!h.talking) {
          const a = document.createElement("button"); a.type = "button"; a.className = "letb"; a.textContent = "Let " + String(h.name).split(/\s+/)[0] + " talk";
          a.title = h.name + " may unmute until they click Done, you mute them again, or the presentation ends";
          a.addEventListener("click", () => talkAct(h.p, true));
          const x = document.createElement("button"); x.type = "button"; x.className = "disb"; x.textContent = "Dismiss";
          x.addEventListener("click", () => talkAct(h.p, false));
          r.append(a, x);
        } else {
          const x = document.createElement("button"); x.type = "button"; x.className = "disb"; x.textContent = "Mute again";
          x.addEventListener("click", () => talkAct(h.p, false));
          r.append(x);
        }
        list.append(r);
      }
      box.append(list);
    } else if (d.am) {
      const n = document.createElement("span"); n.className = "hn none"; n.textContent = "No hands raised";
      box.append(n);
    }
    row.append(box);
  };
  // the audience's pill: the lock, Ask to speak / Lower hand, "you may talk" / Done
  let talkPill = null;
  function paintTalkPill() {
    const ds = liveDecks().filter((x) => !x.old);
    const me = myPerson();
    const d = handState ? ds.find((x) => x.id === handState.id) : null;
    const letMe = d && d.am && d.lt.includes(me);
    const show = (!!talk.locked || !!handState) && !document.body.classList.contains("viewonly");   // a watching-only code has no mic to ask for
    if (!talkPill) {
      if (!show) return;
      talkPill = document.createElement("div"); talkPill.id = "presTalk"; talkPill.setAttribute("role", "status");
      talkPill.innerHTML = '<span class="tt"></span><button type="button" class="tb"></button>';
      talkPill.querySelector(".tb").addEventListener("click", () => raiseHand(!handState));
      document.body.appendChild(talkPill);
    }
    talkPill.classList.toggle("show", show);
    if (!show) return;
    const txt = letMe ? "You may talk now — unmute when you are ready" : talk.locked + (handState ? " · your hand is up" : "");
    const b = letMe ? "Done" : handState ? "Lower hand" : "Ask to speak";
    const t = talkPill.querySelector(".tt"), bb = talkPill.querySelector(".tb");
    { const dk = ds.find((x) => x.am && !mayTalk(x, me)); bb.hidden = !letMe && !handState && !!dk && !dk.ask; }   // 0.21.91: Ask to speak off -- no button
    if (t.textContent !== txt) t.textContent = txt;
    if (bb.textContent !== b) bb.textContent = b;
    bb.title = letMe ? "Lower your hand -- you are muted again" : handState ? "Lower your hand" : "Raise your hand: the presenters can let you talk";
    talkPill.classList.toggle("free", !!letMe);
    talkPill.classList.toggle("withpill", !!document.querySelector("#presPill.show"));
  }
  const TALK_CSS = `
  #presTalk { position:fixed; bottom:16px; left:50%; transform:translateX(-50%); z-index:84; display:none; gap:10px; align-items:center;
    background:#2a1414; color:#ffd7d7; border:1px solid #6b2a2a; border-radius:999px; padding:5px 6px 5px 14px; font:13px 'Segoe UI', system-ui, sans-serif;
    box-shadow:0 6px 20px rgba(0,0,0,.45); max-width:calc(100vw - 24px); }
  #presTalk.show { display:flex; }
  #presTalk.free { background:#0f2a1a; color:#c8f5d8; border-color:#2a6b45; }
  #presTalk button[hidden] { display:none; }
  #presTalk .tt { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  #presTalk button { background:#0b5c86; color:#fff; border:0; border-radius:999px; padding:5px 12px; cursor:pointer; font:inherit; white-space:nowrap; }
  #presView .audbox { flex-basis:100%; display:flex; flex-direction:column; gap:6px; border-top:1px solid #1f2a36; padding-top:6px; }
  #presView .hands { display:grid; gap:4px; }
  #presView .hand { display:flex; gap:6px; align-items:center; flex-wrap:wrap; padding:3px 6px; border-radius:6px; background:#2a2110; color:#ffcf7a; }
  #presView .hand.talking { background:#0f2a1a; color:#c8f5d8; }
  #presView .hand .hn { flex:1; min-width:90px; }
  #presView .hn.none { color:#6b7d8f; font-size:12px; }
  #presView .hand button { padding:2px 8px; font-size:12px; }
  body:has(#presView.show) #presTalk { top:6px; bottom:auto; z-index:86; padding:3px 4px 3px 12px; font-size:12px; max-width:min(560px, 46vw); }   /* in the presenter view: in its top bar, over nothing */
  body:has(#presView.show) #presTalk button { padding:3px 10px; }
  #topMicBtn.talklock { position:relative; }
  #topMicBtn .tlk { position:absolute; top:3px; right:5px; display:inline-flex; color:#f5b942; pointer-events:none; }
  #topMicBtn .tlk svg, #topMicBtn .tlk .icon { width:12px; height:12px; }`;
  (() => { const st = document.createElement("style"); st.id = "presTalkCss"; st.textContent = TALK_CSS; document.head.appendChild(st); })();
  modeSigExtra = () => JSON.stringify(audFields());
  window.__presTalk = {
    lock: () => talk.locked,                 // "" or why my mic is locked ("Muted while Ada presents")
    silent: (path) => silent(path),          // a person's mic that may not be heard here now (gain 0)
    hand: (on) => raiseHand(on !== false),   // rig + the pill
    ask: (on) => askAct(on !== false),   // rig: the presenter view's "Ask to speak" switch
    state: () => ({ locked: talk.locked, was: talk.was, active: talk.active, allowed: [...talk.allowed], boxes: [...talk.boxes], hand: handState,
                    decks: liveDecks().map((d) => ({ id: d.id, am: d.am, ask: d.ask, lt: d.lt, hx: d.hx, old: !!d.old })) }),
  };

  window.__pres = {
    startFromFile,
    audSnap: () => (mine && mine.lt ? { am: mine.am ? 1 : 0, ask: mine.ask === 0 ? 0 : 1 } : null),   // 0.21.91: for a meeting template's tplSnap (audience.ask)
    end: () => endMine("api"),
    go: (i) => { const v = view.deck(); if (!v) return false; if (v.role === "presenter") goTo(i, myPerson()); else sendIntent(v.id, i); return true; },   // a viewer has no deck here: false (0.21.91: the blank stays)
    blank: (kind) => { const v = view.deck(); if (!v) return false; const nb = kind === "black" || kind === "white" ? kind : null; if (v.role === "presenter") goTo(v.idx, myPerson(), nb); else sendIntent(v.id, v.idx, nb); return true; },   // 0.21.91 rig
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
    av: (op, to) => { const bk = [...backstage.values()].find((b) => b.keys && !b.pr); return bk ? sendAvIntent(bk.rec.id, op, to) : false; },   // 0.21.91: to = which presenter (default: presenting now)
    // 0.21.91: my own "Can control my mic and camera" for one backstage person (each presenter decides for themselves)
    allow: (who, on) => { const v = view.deck(); return v && v.role !== "backstage" ? view.allow(who, on) : false; },
    reporterBg: (id) => {   // the presenters
      if (!rbgOk(id)) return false;
      if (mine && mine.ms) { mine.rbg = id; T("rbg", { id: mine.id, who: id }); modeTick(); return true; }
      const bk = [...backstage.values()].find((b) => b.keys && b.pr);
      return bk ? sendPresOp(bk.rec.id, { op: "rbg", v: id }) : false;
    },
    role: (who, r) => view.role(who, r), now: (who) => view.now(who), people: () => view.people(), picker: (k) => view.picker(k),   // 0.21.91
    endAll: () => view.end(),
    reporterBgs: () => REPORTER_BGS.map((b) => b[0]),
    modes: () => modeState(),
    layout: presLayout,   // rig: the geometry alone
    trace,
    state: () => ({
      me: myPerson(),
      mine: mine ? { id: mine.id, name: mine.name, kind: mine.kind, via: mine.via, n: mine.n, idx: mine.idx, ver: mine.ver, by: mine.by, blank: mine.blank, og: mine.og, cur: mine.cur, adopted: !!mine.adopted,
                     ps: mine.ps.map((x) => ({ p: x.p, ready: !!(x.w && x.t) })),
                     up: mine.up.filter(Boolean).length, share: mine.share?.path || "", shareId: mine.share ? mine.share.id : null, bs: [...mine.bs.entries()].map(([p, b]) => ({ p, ready: !!b.w })),
                     startedMs: mine.startedMs, warnings: mine.warnings } : null,
      backstage: [...backstage.values()].map((b) => ({ id: b.rec.id, idx: b.rec.idx, ver: b.rec.ver, key: !!b.keys, rt: !!b.rt, notes: b.notes ? b.notes.length : null, pr: !!b.pr, wt: !!b.wt, orphan: !!b.orphan, cur: b.rec.cur || "", og: b.rec.og || 1 })),
      viewerHeld: [...overlays.values()].filter((o) => o.vKey).map((o) => o.vKey),   // what a viewer keeps: the live slide only
      seen: [...remote.entries()].filter(([, r]) => r.pres).map(([p, r]) => ({ path: p, id: r.pres.id, idx: r.pres.idx, ver: r.pres.ver, bs: (r.pres.bs || []).map((b) => b.p), ps: (r.pres.ps || []).map((b) => b.p), og: r.pres.og || 1, cur: r.pres.cur || "", own: r.pres.own || "", blank: r.pres.blank || "", key: !!r.pres.k, am: r.pres.am,
                                                                                vids: (r.pres.vids || []).map((x) => ({ i: x.i, p: x.p, pl: x.pl, st: x.st, t: x.t })) })),
      overlays: [...overlays.entries()].map(([p, o]) => ({ path: p, key: o.key, w: o.cv.width, h: o.cv.height })),
      viewerFetches: viewerFetches.slice(),
      view: view.isOpen() ? (view.deck() || {}).role || "preparing" : "",
      pk: !!pkPublished,
      // 0.21.87: the presenter's slide videos; what each tile drew of a slide's video
      vids: mine ? [...mine.vids.values()].map((e) => ({ k: e.k, i: e.i, v: e.v, auto: !!e.sv.auto, shareId: e.shareId, path: e.path, pl: e.pl, st: e.st, t: e.t, err: e.err })) : [],
      deckVideos: mine ? ((mine.src && mine.src.videos) || []).map((l) => l.map((v) => (v.id ? v.id + (v.kind === "audio" ? ":audio" : "") : "linked:" + v.linked))) : null,
      vidDrawn: [...overlays.entries()].map(([p, o]) => ({ path: p, drawn: o.vDrawn || 0, last: o.vLast || 0, painted: o.vPainted || null })),
    }),
    __drawSlide: drawSlide,   // rig: render a scene slide without a room
  };
})();
