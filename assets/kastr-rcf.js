// 0.21.92 (Kenton: file transfer in the private sessions "the same as room remote control") -- the 0.21.83 files-and-pictures
// module, MOVED here from moq-watch-lite.html (not forked): the room page (remote control of a share), rcx.html (an admin's
// private view) and rcx-agent.html (the machine's helper) all run it. Each gives create(env) its own plumbing:
//   env.enabled()            this page may run a files session (a KASTR page with remote control)
//   env.open(alive)          -> {st, data}: producers (set / bytes / sync / stop) of MY fo.json + fq.json and of MY fd chunks
//   env.conn()               the MoQ connection their tracks come in on (a new one = subscribe again)
//   env.peer(s)              -> {st, data} paths of THEIR fo/fq and fd broadcasts (null: not known yet)
//   env.subJson(conn, path, track, cb)   a JSON snapshot subscription ({close})
//   env.request(org, path, ms)           origin.request -> {bc, close} | null
//   env.isCtl(c), env.point(t, x, y), env.inPic(p)   the controller's shared screen (paste / drop)
//   env.log(t), env.toast(t, ms, level), env.sleep(ms), env.root?(), env.needs?
// Everything else -- the offers (fo.json), the pulled window of chunks (fq.json), AES-GCM under the grant's key (fk), the card
// #kRcFiles -- is exactly the 0.21.83 code; see the long comment above "0.21.83 FILES AND PICTURES" in moq-watch-lite.html.
(function () {
  "use strict";
  const RCF_WIN_BYTES = 8 * 1048576, RCF_RESEND_MS = 2500, RCF_PRIO = 30, RCF_TICK_MS = 600, RCF_Q_MS = 60, RCF_STALL_MS = 45000, RCF_NOTE_MS = 15000;
  const RCF_CS = 524288, RCF_AUTO = 100 * 1048576, RCF_MAGIC = 0x4B524631;   // "KRF1"; a dropped file's chunks: 512 KB (kastr_rcfiles.CHUNK)
  const RCF_FK_RE = /^[A-Za-z0-9_-]{43}$/, RCF_OID_RE = /^[0-9a-f]{16}$/;
  const rcfHex = (n) => Array.from(crypto.getRandomValues(new Uint8Array(n)), (b) => b.toString(16).padStart(2, "0")).join("");
  const rcfB64 = (u8) => btoa(String.fromCharCode(...u8)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const rcfUnB64 = (s) => Uint8Array.from(atob(String(s).replace(/-/g, "+").replace(/_/g, "/") + "="), (ch) => ch.charCodeAt(0));
  const rcfNewKey = () => rcfB64(crypto.getRandomValues(new Uint8Array(32)));
  function rcfSize(n) {
    n = Number(n) || 0;
    const u = ["bytes", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1024 && i < 4) { n /= 1024; i++; }
    return i ? (n < 10 ? n.toFixed(1) : String(Math.round(n))) + " " + u[i] : n + (n === 1 ? " byte" : " bytes");
  }
  function rcfDescribe(pub) {   // "report.docx" / "the folder Photos" / "3 files" / "a picture"
    if (pub.kind === "image") return "a picture";
    if (pub.name) return String(pub.name).slice(0, 120);
    const tops = (pub.items || []).filter((it) => !String(it.p).includes("/"));
    const nf = (pub.items || []).filter((it) => !it.d).length;
    if (tops.length === 1) return (tops[0].d ? "the folder " : "") + tops[0].p;
    return nf + " file" + (nf === 1 ? "" : "s");
  }
  function rcfIv(oid, c) {   // 8 bytes of the offer's id + the chunk number: never twice under one key
    const iv = new Uint8Array(12);
    for (let i = 0; i < 8; i++) iv[i] = parseInt(oid.substr(i * 2, 2), 16) || 0;
    new DataView(iv.buffer).setUint32(8, c >>> 0);
    return iv;
  }
  function rcfPlan(o) {   // the chunk layout of an offer (kastr_rcfiles.chunk_plan, the same numbering on both sides)
    const cs = Number(o.pub.cs) || RCF_CS;
    o.starts = []; let n = 0;
    for (const it of o.pub.items) { o.starts.push(n); if (!it.d) n += Math.ceil((Number(it.n) || 0) / cs); }
    o.N = n; o.cs = cs;
  }
  function rcfChunkAt(o, c) {
    let lo = 0, hi = o.starts.length - 1, i = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (o.starts[m] <= c) { i = m; lo = m + 1; } else hi = m - 1; }
    while (i >= 0 && (o.pub.items[i].d || !Number(o.pub.items[i].n))) i--;
    if (i < 0) return null;
    const n = Number(o.pub.items[i].n), off = (c - o.starts[i]) * o.cs;
    return off >= 0 && off < n ? [i, off, Math.min(o.cs, n - off)] : null;
  }
  async function rcfLocal(body) {   // this computer's KASTR (kastr_rcfiles)
    try {
      const r = await fetch("/api/rcfiles", { method: "POST", headers: { "content-type": "application/json", "x-kastr-rc": "1" }, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      return { ...d, http: r.status, ok: r.ok && d.ok !== false };
    } catch (e) { return { ok: false, error: String(e?.message || e) }; }
  }
  // 0.21.92: "recv" and "done" are safe to send twice (kastr_rcfiles answers the transfer it already has), so a request that
  // got NO answer at all ("Failed to fetch": a dropped local connection -- seen once in the lab at the end of a 20 MB copy)
  // is sent again twice before the transfer counts as failed
  async function rcfLocalAgain(body) {
    let d = await rcfLocal(body);
    for (let i = 0; i < 2 && !d.ok && d.http === undefined; i++) {
      await new Promise((r) => setTimeout(r, 400 + 600 * i));
      d = await rcfLocal(body);
    }
    return d;
  }
function create(env) {   // one per page; the body keeps the page's two-space indent (the code moved verbatim)
  const log = (t) => { try { env.log(t); } catch {} };
  const rcToast = (t, ms, level) => { try { env.toast(t, ms, level); } catch {} };
  const sleepMs = (ms) => (env.sleep ? env.sleep(ms) : new Promise((r) => setTimeout(r, ms)));
  const rcPoint = (t, x, y) => env.point(t, x, y), rcIn = (p) => env.inPic(p);
  let rcf = null;
  const rcfNotes = [];   // [{k, t, level, at}] -- they outlive the session (the "received" note stays a while)
  function rcfNote(k, t, level) {
    const i = rcfNotes.findIndex((n) => n.k === k);
    if (i >= 0) rcfNotes.splice(i, 1);
    rcfNotes.push({ k, t, level: level || "ok", at: Date.now() });
    while (rcfNotes.length > 4) rcfNotes.shift();
    rcfPaint();
  }
  // ---- the session
  function rcfStart(role, x) {
    if (!env.enabled()) return;
    rcfStop("restart");
    const s = rcf = { role, rcid: x.rcid, room: x.room, peerHost: role === "ctl" ? x.to : x.from, peerPeer: role === "ctl" ? x.toPeer : x.peer,
                      name: String(x.name || "Someone"), fk: RCF_FK_RE.test(String(x.fk || "")) ? String(x.fk) : "", key: null, caps: null, on: false,
                      offers: new Map(), clipOid: "", theirs: new Map(), getQ: [], rx: null, rxDone: [], cancelled: [], errs: [],
                      peerFo: null, peerFq: null, peerFqAt: 0, peerEnc: false, pump: [], pumping: false, conn: null, fqAt: 0, beginAt: 0, at: Date.now() };
    const io = env.open(() => rcf === s);   // fo.json + fq.json out (state), fd out (the chunks, RCF_PRIO, maxAge 3 s)
    s.st = io.st; s.data = io.data;
    rcfFo(s); rcfFq(s);
    s.st.sync(); s.data.sync();
    rcfSubs(s);
    (async () => {
      if (s.fk) { try { s.key = await crypto.subtle.importKey("raw", rcfUnB64(s.fk), "AES-GCM", false, ["encrypt", "decrypt"]); } catch { s.key = null; } }
      await rcfBegin(s);
    })();
    s.tick = setInterval(() => rcfTick(s), RCF_TICK_MS);
  }
  async function rcfBegin(s) {
    if (rcf !== s || s.beginBusy) return;
    s.beginBusy = true; s.beginAt = Date.now();
    const d = await rcfLocal({ op: "begin", rcid: s.rcid, role: s.role, name: s.name });
    s.beginBusy = false;
    if (rcf !== s) return;
    s.caps = d.caps || s.caps; s.on = !!d.ok;
    if (d.http === 404) s.old = true;   // a KASTR without kastr_rcfiles: never asked again
    if (!d.ok) log("Remote control files: " + (d.error || "not available here"));
    rcfFo(s); rcfFq(s); rcfPaint();
  }
  function rcfStop(why) {
    const s = rcf;
    if (!s) return;
    rcf = null;
    clearInterval(s.tick); clearTimeout(s.fqT);
    for (const k of ["subFo", "subFq", "subFd"]) { try { s[k]?.close(); } catch {} }
    try { s.st.set("fo.json", { rcid: s.rcid, v: 1, on: false, offers: [], end: 1, t: Date.now() }); } catch {}
    setTimeout(() => { try { s.st.stop(); s.data.stop(); } catch {} }, 1200);
    if (s.pasteRes) { try { s.pasteRes(); } catch {} }
    if (s.rx) rcfNote("rx-" + s.rx.oid, "Stopped receiving " + rcfDescribe(s.rx.e.pub) + " \u2014 remote control ended", "warn");
    rcfLocal({ op: "end", rcid: s.rcid, why: String(why || "stopped").slice(0, 20) });
    rcfPaint();
  }
  function rcfSubs(s) {
    for (const k of ["subFo", "subFq", "subFd"]) { try { s[k]?.close(); } catch {} s[k] = null; }
    const conn = s.conn = env.conn();
    const pp = conn ? env.peer(s) : null;   // {st: their fo/fq broadcast, data: their fd broadcast}
    if (!pp) return;
    s.subFo = env.subJson(conn, pp.st, "fo.json", (v) => rcfPeerFo(s, v));
    s.subFq = env.subJson(conn, pp.st, "fq.json", (v) => rcfPeerFq(s, v));
    s.subFd = rcfDataSub(s, conn, pp.data);
  }
  function rcfDataSub(s, conn, path) {   // their chunks: every group, in the order they come
    const h = { closed: false, sub: null, n: 0 };
    (async () => {
      let backoff = 500;
      while (!h.closed && rcf === s) {
        let req = null;
        try {
          const org = conn.origin?.peek?.();
          if (!org) throw new Error("not connected");
          req = await env.request(org, path, 8000);
          if (!req) throw new Error("not routable");
          const sub = h.sub = req.bc.track("fd").subscribe({ priority: RCF_PRIO, maxAge: 3000 });
          backoff = 500;
          for (;;) {
            const g = await sub.recvGroup();
            if (!g || h.closed) break;
            g.readFrame().then((f) => { if (f && f.payload) { h.n++; rcfData(s, f.payload); } }, () => {}).finally(() => { try { g.close(); } catch {} });
          }
        } catch {}
        try { h.sub?.close(); } catch {}
        try { req?.close(); } catch {}
        if (h.closed || rcf !== s) break;
        await sleepMs(backoff);
        backoff = Math.min(4000, backoff * 2);
      }
    })();
    return { close() { h.closed = true; try { h.sub?.close(); } catch {} }, get n() { return h.n; } };
  }
  function rcfFo(s) {   // fo.json: what I offer now (my clipboard's copy, a drop), what I cancelled, what I could not read
    const offers = [...s.offers.values()].filter((o) => o.live && !o.final).slice(-3).map((o) => o.pub);
    s.st.set("fo.json", { rcid: s.rcid, v: 1, on: s.on, enc: !!s.key, caps: s.caps ? { max: s.caps.max, auto: s.caps.auto } : null,
                          offers, cancel: s.cancelled.slice(-8), errs: s.errs.slice(-4), t: Date.now() });
  }
  function rcfFq(s) {   // fq.json: the chunks I want of theirs (a window) + my progress + how my last transfers ended
    const x = s.rx;
    s.st.set("fq.json", { rcid: s.rcid, v: 1, on: s.on, enc: !!s.key,
                          x: x ? { oid: x.oid, want: [...x.want].sort((a, b) => a - b), got: x.ngot, N: x.N, bytes: x.bytes, total: x.total, files: x.files, nfiles: x.nfiles } : null,
                          done: s.rxDone.slice(-6), t: Date.now() });
    s.fqAt = Date.now();
  }
  function rcfFqSoon(s) {
    if (s.fqT) return;
    s.fqT = setTimeout(() => { s.fqT = 0; if (rcf === s) rcfFq(s); }, Math.max(0, RCF_Q_MS - (Date.now() - s.fqAt)));
  }
  async function rcfTick(s) {
    if (rcf !== s) { clearInterval(s.tick); return; }
    { const cn = env.conn(); if (cn && s.conn !== cn) rcfSubs(s); }
    s.st.sync(); s.data.sync();
    if (!s.on && !s.old && !s.beginBusy && Date.now() - s.beginAt > 4000) rcfBegin(s);
    if (s.rx && Date.now() - s.fqAt > 500) rcfFq(s);   // the want list again: whatever got lost is asked for again
    if (s.rx && Date.now() - s.rx.last > RCF_STALL_MS) rcfRxEnd(s, "fail", "nothing arrived for " + Math.round(RCF_STALL_MS / 1000) + " s");
    if (s.pasteWait && Date.now() - s.pasteWait.at > 8000 && !(s.peerFq?.x?.oid === s.pasteWait.oid)) {   // they never started on it
      const r = s.pasteRes; s.pasteWait = null; s.pasteRes = null; r?.();
    }
    if (s.on && !s.ticking) {
      s.ticking = true;
      try {
        const d = await rcfLocal({ op: "renew", rcid: s.rcid });
        if (rcf === s && d.ok) rcfMine(s, d);
        else if (rcf === s && d.http === 409) { s.on = false; rcfFo(s); }
      } finally { s.ticking = false; }
    }
    rcfPaint();
  }
  // ---- what I copied (my KASTR's offer) -> fo.json
  function rcfMine(s, d) {
    const off = d.offer;
    if (off && RCF_OID_RE.test(String(off.oid || "")) && off.oid !== s.clipOid) {
      s.clipOid = off.oid;
      for (const o of s.offers.values()) if (o.src === "kastr" && o.live && !o.prog) o.live = false;   // an older copy nobody is taking
      const o = { pub: off, src: "kastr", sent: new Map(), queued: new Set(), bytes: 0, live: true, at: Date.now() };
      rcfPlan(o);
      s.offers.set(off.oid, o);
      while (s.offers.size > 8) s.offers.delete(s.offers.keys().next().value);
      rcfFo(s);
      log("Remote control files: offering " + rcfDescribe(off) + " (" + rcfSize(off.total) + ")");
      if (off.over) rcfNote("of-" + off.oid, rcfDescribe(off) + " (" + rcfSize(off.total) + ") is over the " + rcfSize(s.caps?.max) + " limit for one transfer \u2014 it stays here", "warn");
      else if (off.skipped?.links) rcfNote("of-" + off.oid, "Left out " + off.skipped.links + " shortcut link" + (off.skipped.links === 1 ? "" : "s") + " (links are never followed)", "info");
    } else if (!off && s.clipOid) {
      const o = s.offers.get(s.clipOid);
      if (o && !o.prog) o.live = false;
      s.clipOid = "";
      rcfFo(s);
    }
  }
  // ---- their offers -> fetch (at once, on "Get them", or on the controller's paste)
  function rcfPeerFo(s, v) {
    if (rcf !== s || !v || v.rcid !== s.rcid) return;
    s.peerFo = v;
    const x = s.rx;
    if (x && Array.isArray(v.cancel) && v.cancel.includes(x.oid)) rcfRxEnd(s, "cancel", s.name + " cancelled it");
    const er = x && Array.isArray(v.errs) ? v.errs.find((e) => e && e.oid === x?.oid) : null;
    if (er && s.rx) rcfRxEnd(s, "fail", String(er.why || "their side could not read it"));
    const listed = new Set();
    for (const pub of (Array.isArray(v.offers) ? v.offers : []).slice(0, 4)) {
      if (!pub || !RCF_OID_RE.test(String(pub.oid || "")) || !Array.isArray(pub.items)) continue;
      listed.add(pub.oid);
      let e = s.theirs.get(pub.oid);
      if (!e) {
        e = { pub, state: "new", at: Date.now() };
        s.theirs.set(pub.oid, e);
        if (pub.kind === "drop" && s.role !== "sharer") { e.state = "skip"; continue; }
        const auto = Number(s.caps?.auto ?? RCF_AUTO);
        if (pub.over) { e.state = "over"; rcfNote("th-" + pub.oid, s.name + " copied " + rcfDescribe(pub) + " (" + rcfSize(pub.total) + ") \u2014 over the limit for one transfer", "warn"); }
        else if (pub.kind === "drop" || pub.kind === "image" || pub.total <= auto || pub.get) rcfQueue(s, pub.oid);
        else { e.state = "wait"; log("Remote control files: " + s.name + " copied " + rcfDescribe(pub) + " (" + rcfSize(pub.total) + ") -- waits for Get them / a paste"); }
      } else if (pub.get && e.state === "wait") rcfQueue(s, pub.oid);   // the controller pasted on my screen: take it now
    }
    for (const [oid, e] of s.theirs) if ((e.state === "wait" || e.state === "over") && !listed.has(oid)) s.theirs.delete(oid);   // copied over since
    while (s.theirs.size > 12) s.theirs.delete(s.theirs.keys().next().value);
    rcfPaint();
  }
  function rcfQueue(s, oid) {
    const e = s.theirs.get(oid);
    if (!e || e.state === "get" || e.state === "queued" || e.state === "done") return;
    e.state = "queued";
    s.getQ.push(oid);
    rcfNextGet(s);
  }
  function rcfNextGet(s) {
    if (rcf !== s || s.rx || s.getBusy) return;
    while (s.getQ.length) {
      const oid = s.getQ.shift(), e = s.theirs.get(oid);
      if (e && e.state === "queued") { rcfGet(s, oid); return; }
    }
  }
  async function rcfGet(s, oid) {
    const e = s.theirs.get(oid);
    if (!e) return;
    if (!s.on) { e.state = "fail"; rcfNote("rx-" + oid, "This KASTR can\u2019t take files from " + s.name + (s.old ? " (it is older than 0.21.83)" : ""), "warn"); return; }
    e.state = "get"; s.getBusy = true;
    const d = await rcfLocalAgain({ op: "recv", rcid: s.rcid, offer: { ...e.pub, by: s.name }, pt: e.pub.kind === "drop" ? e.pub.pt : undefined });
    s.getBusy = false;
    if (rcf !== s) return;
    if (!d.ok) {
      e.state = "fail";
      s.rxDone.push({ oid, state: "fail", why: String(d.error || "").slice(0, 160) });
      rcfFq(s);
      rcfNote("rx-" + oid, "Couldn\u2019t take " + rcfDescribe(e.pub) + " from " + s.name + ": " + (d.error || "no answer from KASTR"), "warn");
      rcfNextGet(s);
      return;
    }
    const need = [];
    for (const [a, b] of (Array.isArray(d.need) ? d.need : [])) for (let c = a; c < b; c++) need.push(c);
    const p = d.progress || {};
    const x = s.rx = { oid, e, need, ni: 0, want: new Set(), got: new Set(), inflight: new Set(), ngot: 0, N: need.length, bytes: 0, total: Number(p.total) || Number(e.pub.total) || 0,
                       files: 0, nfiles: Number(p.nfiles) || Number(e.pub.files) || 0, t0: Date.now(), last: Date.now(), posts: 0, q: [], win: Math.max(4, Math.min(64, Math.ceil((Number(window.__rcfWinBytes) || RCF_WIN_BYTES) / (Number(e.pub.cs) || RCF_CS)))) };
    log("Remote control files: receiving " + rcfDescribe(e.pub) + " (" + rcfSize(x.total) + ") from " + s.name);
    if (p.state === "done" || !need.length) { if (p.state === "done") rcfRxFinish(s, x, p); else rcfRxDone(s, x); return; }
    rcfFill(s);
    rcfFq(s);
    rcfPaint();
  }
  function rcfFill(s) {
    const x = s.rx;
    if (!x) return;
    while (x.want.size < x.win && x.ni < x.need.length) { const c = x.need[x.ni++]; if (!x.got.has(c)) x.want.add(c); }
  }
  async function rcfData(s, u8) {   // one chunk of theirs
    if (rcf !== s || !(u8 instanceof Uint8Array) || u8.length < 8) return;
    const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
    if (dv.getUint32(0) !== RCF_MAGIC) return;
    const hl = dv.getUint32(4);
    if (hl > 512 || 8 + hl > u8.length) return;
    let h;
    try { h = JSON.parse(new TextDecoder().decode(u8.subarray(8, 8 + hl))); } catch { return; }
    const x = s.rx;
    if (!x || !h || h.o !== x.oid || !Number.isInteger(h.c) || x.got.has(h.c) || x.inflight.has(h.c) || !x.want.has(h.c)) return;
    let body = u8.subarray(8 + hl);
    x.inflight.add(h.c);
    if (h.e) {
      if (!s.key) { x.inflight.delete(h.c); rcfRxEnd(s, "fail", "it came encrypted and this side has no key"); return; }
      try { body = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: rcfIv(h.o, h.c), additionalData: new TextEncoder().encode(h.o + ":" + h.c) }, s.key, body)); }
      catch { x.inflight.delete(h.c); return; }   // damaged: it is asked for again
    }
    if (s.rx !== x) return;
    x.q.push([h.c, body]);
    rcfPost(s, x);
  }
  function rcfPost(s, x) {   // into my KASTR, three at a time
    while (x.posts < 3 && x.q.length) {
      const [c, body] = x.q.shift();
      x.posts++;
      fetch("/api/rcfiles/put?rcid=" + s.rcid + "&oid=" + x.oid + "&c=" + c, { method: "POST", headers: { "x-kastr-rc": "1", "content-type": "application/octet-stream" }, body })
        .then((r) => r.json().catch(() => ({})).then((d) => [r.status, d]))
        .then(([code, d]) => {
          x.posts--; x.inflight.delete(c);
          if (s.rx !== x) return;
          if (code === 200 && d.ok) {
            if (!x.got.has(c)) { x.got.add(c); x.ngot++; x.bytes += body.length; }
            x.want.delete(c);
            x.files = Number(d.progress?.files) || x.files;
            x.last = Date.now();
            rcfFill(s); rcfFqSoon(s); rcfPaintSoon();
            if (x.ngot >= x.N) rcfRxDone(s, x);
          } else if (code === 404 || code === 409 || code === 422) { rcfRxEnd(s, "fail", d.error || ("HTTP " + code)); return; }
          rcfPost(s, x);
        }, () => { x.posts--; x.inflight.delete(c); if (s.rx === x) rcfPost(s, x); });
    }
  }
  async function rcfRxDone(s, x) {
    if (x.finishing) return;
    x.finishing = true;
    const d = await rcfLocalAgain({ op: "done", rcid: s.rcid, oid: x.oid });
    if (rcf !== s || s.rx !== x) return;
    if (!d.ok) { rcfRxEnd(s, "fail", d.error || "it could not be finished"); return; }
    rcfRxFinish(s, x, d.progress || {});
  }
  function rcfRxFinish(s, x, p) {
    const r = p.result || {}, e = x.e;
    s.rx = null; e.state = "done";
    const ms = Math.max(1, Date.now() - x.t0);
    s.rxDone.push({ oid: x.oid, state: "done", n: Number(r.n) || 0, bytes: Number(r.bytes) || 0, placed: String(r.placed || ""), ms });
    rcfFq(s);
    const n = Number(r.n) || 0, what = e.pub.kind === "image" ? "a picture" : (n === 1 && e.pub.files === 1 ? rcfDescribe(e.pub) : n + " file" + (n === 1 ? "" : "s"));
    const txt = (e.pub.kind === "drop" ? "Received " + what + " (" + rcfSize(r.bytes) + ") " + s.name + " dropped \u2014 " : "Received " + what + " (" + rcfSize(r.bytes) + ") from " + s.name + " \u2014 ") + (r.note || "done");
    rcfNote("rx-" + x.oid, txt, r.placed === "failed" ? "warn" : "ok");
    rcToast(txt, 7000, r.placed === "failed" ? "warn" : "event");
    log("Remote control files: " + txt + " [" + (Math.round((Number(r.bytes) || 0) / ms / 1048.576 * 10) / 10) + " MB/s, " + (ms / 1000).toFixed(1) + " s]");
    rcfNextGet(s);
    rcfPaint();
  }
  function rcfRxEnd(s, state, why) {   // cancel / fail: the partial copy goes (kastr_rcfiles deletes it)
    const x = s.rx;
    if (!x) return;
    s.rx = null; x.e.state = state;
    rcfLocal({ op: "cancel", rcid: s.rcid, oid: x.oid });
    s.rxDone.push({ oid: x.oid, state, why: String(why || "").slice(0, 160) });
    rcfFq(s);
    rcfNote("rx-" + x.oid, (state === "cancel" ? "Cancelled " : "Couldn\u2019t receive ") + rcfDescribe(x.e.pub) + " from " + s.name + (why ? " \u2014 " + why : ""), state === "cancel" ? "info" : "warn");
    log("Remote control files: " + state + " receiving " + rcfDescribe(x.e.pub) + (why ? " (" + why + ")" : ""));
    rcfNextGet(s);
    rcfPaint();
  }
  // ---- their requests for MY offers -> chunks
  function rcfPeerFq(s, v) {
    if (rcf !== s || !v || v.rcid !== s.rcid) return;
    s.peerFq = v; s.peerFqAt = Date.now(); s.peerEnc = !!v.enc;
    const x = v.x, now = Date.now();
    if (x && s.offers.has(x.oid)) {
      const o = s.offers.get(x.oid);
      if (!o.final) {
        if (!o.prog) log("Remote control files: " + s.name + " is taking " + rcfDescribe(o.pub) + " (" + rcfSize(o.pub.total) + ")");
        o.prog = x;
        for (const c of (Array.isArray(x.want) ? x.want : []).slice(0, 64)) {
          if (!Number.isInteger(c) || c < 0 || c >= o.N || o.queued.has(c)) continue;
          const at = o.sent.get(c);
          if (at && now - at < RCF_RESEND_MS) continue;
          o.queued.add(c);
          s.pump.push([o, c]);
        }
        rcfPump(s);
      }
    }
    for (const dn of (Array.isArray(v.done) ? v.done : [])) {
      const o = dn && s.offers.get(dn.oid);
      if (!o || o.final) continue;
      o.final = String(dn.state || "done"); o.prog = null;
      rcfLocal({ op: "sent", rcid: s.rcid, oid: dn.oid, state: o.final, who: s.name });
      const what = rcfDescribe(o.pub) + " (" + rcfSize(o.pub.total) + ")";
      if (o.final === "done") {
        const t = s.role === "sharer" ? s.name + " copied " + what + " from your computer" : s.name + " has " + what + (o.src === "drop" ? " \u2014 dropped on their screen" : "");
        rcfNote("tx-" + dn.oid, t, "ok");
        rcToast(t + ".", 7000);
      } else rcfNote("tx-" + dn.oid, s.name + (o.final === "cancel" ? " cancelled " : " couldn\u2019t take ") + what + (dn.why ? " \u2014 " + dn.why : ""), o.final === "cancel" ? "info" : "warn");
      if (o.src === "drop") o.files = null;   // let go of the dropped files
      rcfFo(s);
      if (s.pasteWait?.oid === dn.oid) { const r = s.pasteRes; s.pasteWait = null; s.pasteRes = null; r?.(); }
    }
    rcfPaint();
  }
  async function rcfPump(s) {   // one chunk at a time: read (my KASTR, or the dropped File), seal, publish
    if (s.pumping) return;
    s.pumping = true;
    try {
      while (rcf === s && s.pump.length) {
        const [o, c] = s.pump.shift();
        o.queued.delete(c);
        if (o.final) continue;
        let data;
        try { data = await rcfRead(s, o, c); }
        catch (err) {
          const why = String(err?.message || err).slice(0, 160);
          if (!s.errs.some((x) => x.oid === o.pub.oid)) { s.errs.push({ oid: o.pub.oid, why }); rcfFo(s); }
          o.final = "fail";
          rcfNote("tx-" + o.pub.oid, "Couldn\u2019t send " + rcfDescribe(o.pub) + ": " + why, "warn");
          continue;
        }
        if (rcf !== s) break;
        const hdr = { o: o.pub.oid, c, n: data.length };
        let body = data;
        if (s.key && s.peerEnc) {
          body = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: rcfIv(o.pub.oid, c), additionalData: new TextEncoder().encode(o.pub.oid + ":" + c) }, s.key, data));
          hdr.e = 1;
        }
        const hb = new TextEncoder().encode(JSON.stringify(hdr));
        const fr = new Uint8Array(8 + hb.length + body.length);
        const dv = new DataView(fr.buffer);
        dv.setUint32(0, RCF_MAGIC); dv.setUint32(4, hb.length);
        fr.set(hb, 8); fr.set(body, 8 + hb.length);
        s.data.sync();
        if (!s.data.bytes("fd", fr)) continue;   // not connected yet: their next want list asks again
        if (!o.sent.has(c)) o.bytes += data.length;
        o.sent.set(c, Date.now());
      }
    } finally { s.pumping = false; }
  }
  async function rcfRead(s, o, c) {
    if (o.src === "drop") {
      const at = rcfChunkAt(o, c), f = at && o.files ? o.files[at[0]] : null;
      if (!f) throw new Error("that file is gone");
      return new Uint8Array(await f.slice(at[1], at[1] + at[2]).arrayBuffer());
    }
    const r = await fetch("/api/rcfiles/chunk?rcid=" + s.rcid + "&oid=" + o.pub.oid + "&c=" + c, { headers: { "x-kastr-rc": "1" }, cache: "no-store" });
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.error || ("HTTP " + r.status)); }
    return new Uint8Array(await r.arrayBuffer());
  }
  function rcfTxCancel(s, oid) {
    const o = s.offers.get(oid);
    if (!o || o.final) return;
    o.final = "cancel"; o.prog = null;
    s.cancelled.push(oid);
    s.pump = s.pump.filter(([oo]) => oo !== o);
    rcfFo(s);
    rcfNote("tx-" + oid, "Stopped sending " + rcfDescribe(o.pub), "info");
  }
  // ---- the controller's Ctrl+V on the shared screen: my copied files / picture get there first (the keys wait)
  function rcfPaste(c) {
    const s = rcf;
    if (!s || s.role !== "ctl" || !s.on || !env.isCtl(c)) return Promise.resolve();
    return (async () => {
      const d = await rcfLocal({ op: "renew", rcid: s.rcid, now: true });   // a copy made a moment ago counts
      if (rcf !== s) return;
      if (d.ok) rcfMine(s, d);
      const o = s.clipOid ? s.offers.get(s.clipOid) : null;
      if (!o || o.pub.over || o.final === "done") return;
      for (let i = 0; i < 30 && !s.peerFqAt && rcf === s; i++) await sleepMs(100);   // their side's files session (an older KASTR has none)
      if (rcf !== s || !s.peerFq?.on) return;
      if ((s.peerFq.done || []).some((x) => x && x.oid === o.pub.oid && x.state === "done")) return;
      o.pub = { ...o.pub, get: 1 };
      rcfFo(s);
      s.pasteWait = { oid: o.pub.oid, at: Date.now() };
      rcfPaint();
      await new Promise((res) => { s.pasteRes = res; });
    })();
  }
  // ---- a drop from my desktop onto the shared screen
  function rcfDragOver(c, e) {
    if (!rcf || rcf.role !== "ctl" || !env.isCtl(c) || !e.dataTransfer || ![...(e.dataTransfer.types || [])].includes("Files")) return;
    e.preventDefault(); e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
    c.cap.classList.add("rcfdrag");
    clearTimeout(c.dragT);
    c.dragT = setTimeout(() => c.cap?.classList.remove("rcfdrag"), 400);
  }
  async function rcfCollect(dt) {   // files + folders (webkitGetAsEntry) -> [{p, f} | {p, d: 1}]; read before the event ends
    const out = [];
    const entries = [...(dt.items || [])].filter((i) => i.kind === "file").map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null));
    const plain = [...(dt.files || [])];
    if (entries.length && entries.every(Boolean)) {
      const walk = async (en, base, depth) => {
        if (out.length >= 10000 || depth > 32) return;
        const rel = base ? base + "/" + en.name : en.name;
        if (en.isFile) { const f = await new Promise((res) => en.file(res, () => res(null))); if (f) out.push({ p: rel, f }); return; }
        if (!en.isDirectory) return;
        out.push({ p: rel, d: 1 });
        const rd = en.createReader();
        for (;;) {
          const batch = await new Promise((res) => rd.readEntries(res, () => res([])));
          if (!batch.length) break;
          for (const k of batch) await walk(k, rel, depth + 1);
        }
      };
      for (const en of entries) await walk(en, "", 0);
      return out;
    }
    for (const f of plain) out.push({ p: f.name, f });
    return out;
  }
  async function rcfDropOn(c, t, e) {
    const s = rcf;
    if (!s || s.role !== "ctl" || !env.isCtl(c) || !e.dataTransfer) return;
    e.preventDefault(); e.stopPropagation();
    c.cap.classList.remove("rcfdrag");
    const p = rcPoint(t, e.clientX, e.clientY);
    const got = rcfCollect(e.dataTransfer);   // synchronously first: the DataTransfer empties when the event ends
    if (!rcIn(p)) { rcToast("Drop it on " + c.name + "\u2019s screen.", 4000); return; }
    if (!s.on || !s.peerFq?.on) { rcToast(c.name + "\u2019s KASTR can\u2019t take files (it needs " + (env.needs || "0.21.83") + " or newer).", 6000, "warn"); return; }
    const list = await got;
    if (!list.length || rcf !== s) return;
    const items = [], files = [];
    for (const it of list) {
      items.push(it.d ? { p: it.p, n: 0, d: 1, t: 0 } : { p: it.p, n: it.f.size, d: 0, t: Math.floor((it.f.lastModified || Date.now()) / 1000) });
      files.push(it.d ? null : it.f);
    }
    const total = items.reduce((a, it) => a + (it.d ? 0 : it.n), 0), nf = items.filter((it) => !it.d).length;
    const max = Number(s.peerFo?.caps?.max) || Number(s.caps?.max) || 2048 * 1048576;
    if (total > max) { rcToast("That is " + rcfSize(total) + " \u2014 over the " + rcfSize(max) + " limit for one transfer.", 6000, "warn"); return; }
    const pub = { oid: rcfHex(8), kind: "drop", cs: RCF_CS, items, total, files: nf, dirs: items.length - nf, pt: [p.x, p.y], at: Date.now() };
    pub.name = rcfDescribe({ ...pub, name: "" });
    const o = { pub, src: "drop", files, sent: new Map(), queued: new Set(), bytes: 0, live: true, at: Date.now() };
    rcfPlan(o);
    s.offers.set(pub.oid, o);
    rcfFo(s);
    log("Remote control files: dropped " + pub.name + " (" + rcfSize(total) + ") on " + c.name + "\u2019s screen at " + p.x.toFixed(3) + ", " + p.y.toFixed(3));
    rcToast("Sending " + pub.name + " (" + rcfSize(total) + ") to " + c.name + "\u2026", 4000);
    rcfPaint();
  }
  // ---- the card: transfers going on, "Get them", the notes
  let rcfPaintT = 0;
  const rcfPaintSoon = () => { if (!rcfPaintT) rcfPaintT = setTimeout(() => { rcfPaintT = 0; rcfPaint(); }, 150); };
  function rcfRows() {
    const s = rcf, rows = [], now = Date.now();
    if (s) {
      const x = s.rx;
      if (x) {
        const pct = x.total ? Math.min(100, Math.floor(x.bytes * 100 / x.total)) : (x.N ? Math.floor(x.ngot * 100 / x.N) : 0);
        rows.push({ k: "rx", pct, b: ["rxcancel", "Cancel"],
                    t: "Receiving " + rcfDescribe(x.e.pub) + " from " + s.name + " \u2014 " + (x.nfiles > 1 ? x.files + " of " + x.nfiles + " files, " : "") + rcfSize(x.bytes) + " of " + rcfSize(x.total) + " (" + pct + "%)" });
      }
      for (const [oid, e] of s.theirs) if (e.state === "wait") rows.push({ k: "get-" + oid, b: ["get:" + oid, "Get " + (e.pub.files === 1 && !e.pub.dirs ? "it" : "them")], t: s.name + " copied " + rcfDescribe(e.pub) + " (" + rcfSize(e.pub.total) + ")" });
      for (const o of s.offers.values()) {
        if (!o.prog || o.final) continue;
        const pr = o.prog, pct = pr.total ? Math.min(100, Math.floor((Number(pr.bytes) || 0) * 100 / pr.total)) : 0;
        const who = s.role === "sharer" ? s.name + " is copying " + rcfDescribe(o.pub) + " from your computer" : "Sending " + rcfDescribe(o.pub) + " to " + s.name;
        rows.push({ k: "tx-" + o.pub.oid, pct, b: ["txcancel:" + o.pub.oid, "Cancel"],
                    t: who + " \u2014 " + (pr.nfiles > 1 ? (Number(pr.files) || 0) + " of " + pr.nfiles + " files, " : "") + rcfSize(pr.bytes) + " of " + rcfSize(pr.total) + " (" + pct + "%)" });
      }
      if (s.pasteWait && !rows.some((r) => r.k === "tx-" + s.pasteWait.oid)) rows.push({ k: "paste", t: "Your paste goes as soon as " + s.name + " has the files\u2026", b: ["pastego", "Paste without them"] });
    }
    for (const n of rcfNotes) if (now - n.at < RCF_NOTE_MS && !rows.some((r) => r.k === n.k)) rows.push({ k: n.k, t: n.t, level: n.level, b: ["close:" + n.k, "\u00d7"] });
    return rows;
  }
  function rcfPaint() {
    const rows = rcfRows();
    let el = document.getElementById("kRcFiles");
    if (!rows.length) { if (el) el.hidden = true; return; }
    if (!el) {
      el = document.createElement("div"); el.id = "kRcFiles"; el.hidden = true;
      el.setAttribute("role", "status"); el.setAttribute("aria-live", "polite");
      el.addEventListener("click", (ev) => {
        const b = ev.target.closest("button[data-a]");
        if (!b) return;
        ev.stopPropagation();
        rcfAction(b.dataset.a);
      });
      (env.root ? env.root() : document.body).appendChild(el);
    }
    // rows are kept by key and updated in place: a progress repaint (several a second) never replaces the Cancel button
    // under the pointer (lab v02183: a click on a rebuilt row landed on a detached button)
    const keep = new Map([...el.children].map((n) => [n.dataset.k, n]));
    let prev = null;
    for (const r of rows) {
      let row = keep.get(r.k);
      keep.delete(r.k);
      if (!row) { row = document.createElement("div"); row.dataset.k = r.k; const t0 = document.createElement("span"); t0.className = "t"; row.appendChild(t0); }
      const cls = "rcfrow" + (r.level ? " " + r.level : "");
      if (row.className !== cls) row.className = cls;
      const t = row.querySelector(".t");
      if (t.textContent !== r.t) t.textContent = r.t;
      let bar = row.querySelector(".bar");
      if (r.pct !== undefined) {
        if (!bar) { bar = document.createElement("span"); bar.className = "bar"; bar.appendChild(document.createElement("i")); row.insertBefore(bar, t.nextSibling); }
        bar.firstChild.style.width = r.pct + "%";
      } else if (bar) bar.remove();
      let btn = row.querySelector("button");
      if (r.b) {
        if (!btn) { btn = document.createElement("button"); btn.type = "button"; row.appendChild(btn); }
        if (btn.dataset.a !== r.b[0]) btn.dataset.a = r.b[0];
        if (btn.textContent !== r.b[1]) btn.textContent = r.b[1];
        btn.title = r.b[1] === "\u00d7" ? "Close" : "";
      } else if (btn) btn.remove();
      const at = prev ? prev.nextSibling : el.firstChild;
      if (row !== at) el.insertBefore(row, at);
      prev = row;
    }
    for (const n of keep.values()) n.remove();
    el.hidden = false;
  }
  function rcfAction(a) {
    const s = rcf;
    if (a.startsWith("close:")) { const i = rcfNotes.findIndex((n) => n.k === a.slice(6)); if (i >= 0) rcfNotes.splice(i, 1); rcfPaint(); return; }
    if (!s) return;
    if (a === "rxcancel") rcfRxEnd(s, "cancel", "");
    else if (a.startsWith("get:")) rcfQueue(s, a.slice(4));
    else if (a.startsWith("txcancel:")) rcfTxCancel(s, a.slice(9));
    else if (a === "pastego" && s.pasteRes) { const r = s.pasteRes; s.pasteWait = null; s.pasteRes = null; r(); }
    rcfPaint();
  }
  setInterval(() => { if (rcfNotes.length || rcf) rcfPaint(); }, 1000);   // notes fade out
  const rig = {   // rig (the lab: window.__rcf) -- never the bytes, never the key
    state: () => {
      const s = rcf;
      return { notes: rcfNotes.map((n) => [n.k, n.t, n.level]), rows: rcfRows().map((r) => [r.k, r.t, r.pct ?? null]),
               s: s && { role: s.role, rcid: s.rcid, on: s.on, enc: !!s.key, peerEnc: s.peerEnc, peerOn: !!s.peerFq?.on, clipOid: s.clipOid,
                         offers: [...s.offers.values()].map((o) => ({ oid: o.pub.oid, kind: o.pub.kind, name: o.pub.name, total: o.pub.total, live: !!o.live, final: o.final || "", sentBytes: o.bytes, prog: o.prog ? { bytes: o.prog.bytes, got: o.prog.got, N: o.prog.N } : null })),
                         theirs: [...s.theirs].map(([k, e]) => [k, e.state, e.pub.kind, e.pub.name, e.pub.total]),
                         rx: s.rx && { oid: s.rx.oid, ngot: s.rx.ngot, N: s.rx.N, bytes: s.rx.bytes, total: s.rx.total, files: s.rx.files, nfiles: s.rx.nfiles, ms: Date.now() - s.rx.t0 },
                         rxDone: s.rxDone.slice(), pasteWait: s.pasteWait, fd: s.subFd?.n || 0 } };
    },
    get: (oid) => { if (rcf) rcfQueue(rcf, oid); }, cancel: () => { if (rcf) rcfRxEnd(rcf, "cancel", ""); }, action: rcfAction, size: rcfSize,
  };
  return {
    start: rcfStart, stop: rcfStop, paste: rcfPaste, dragOver: rcfDragOver, dropOn: rcfDropOn,
    paint: rcfPaint, action: rcfAction, rows: rcfRows, cur: () => rcf, rig,
  };
}
  window.KastrRcf = { create, newKey: rcfNewKey, FK_RE: RCF_FK_RE, PRIO: RCF_PRIO, size: rcfSize, describe: rcfDescribe };
})();
