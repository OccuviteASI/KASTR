// 0.21.88 (Kenton: "I would like to add a private messaging feature. Ability to message people privately whether
// online/offline. If offline, send it when back online. Ability to setup group messages. These messages are not tied to any
// rooms." + "If a user connects with the same name and enters the same 'my room' password, then they should be able to access
// the previous messages."): PRIVATE MESSAGES -- the page half (the hub half is kastr_msg.py).
//
// WHO: a person = a name with a My room. Their ONE identity key pair (ECDH P-256) lives on the hub wrapped under
// PBKDF2-SHA256(My room code, salt, 600000) + AES-GCM; this page fetches the wrap after proving name + code, opens it here and
// keeps the private key NON-EXTRACTABLE in IndexedDB. The code itself is what this device already remembers for My room
// (kastr.personal.<relay host>) or what the person types once.
// WHAT THE HUB SEES: names, group membership, timestamps, sizes -- never a message, a file, the private key or the key the code
// derives. A message = AES-GCM(K, body) with K wrapped for every reader PERSON (and me: my other devices) under
// HKDF(ECDH(my key, their key), salt = message id, "kastr-msg-wrap-v1|<sender key id>|<reader key id>").
// DELIVERY: the hub keeps ciphertext 90 days; this page pulls (since its cursor, acking what it kept), at once when its people
// beat says so (window.__msg.ping), and every 30 s. History stays here too (IndexedDB, trimmed at 90 days).
(() => {
  "use strict";
  // 0.21.91: the page's bridge may come a moment AFTER this module runs (module scripts do not wait for each other once one is
  // awaiting) -- wait for it instead of giving up (a page with no Messages at all, seen in the lab now and then)
  let boots = 0;
  const boot = () => { if (window.__msg) return; if (!window.__kmsg) { if (++boots < 600) setTimeout(boot, 100); return; } main(); };
  boot();
  function main() {
  const K = window.__kmsg;   // the page's bridge (moq-watch-lite.html)
  const subtle = (window.crypto && window.crypto.subtle) || null;
  const enc = new TextEncoder(), dec = new TextDecoder();
  const ITER = 600000;            // PBKDF2-SHA256 iterations (OWASP 2023); the hub refuses fewer
  const KEEP_MS = 90 * 86400000;  // Kenton: history kept 90 days
  const FILE_MAX = 25 * 1024 * 1024;
  const POLL_MS = 30000;
  const IMG_TYPES = /^image\/(png|jpe?g|gif|webp|bmp)$/i;
  const trace = [];
  const T = (ev, o) => { trace.push(Object.assign({ t: Date.now(), ev }, o || {})); if (trace.length > 300) trace.splice(0, 100); };
  const b64 = (u8) => { let s = ""; const a = new Uint8Array(u8); for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode.apply(null, a.subarray(i, i + 0x8000)); return btoa(s); };
  const unb64 = (s) => Uint8Array.from(atob(String(s || "")), (c) => c.charCodeAt(0));
  const rnd = (n) => crypto.getRandomValues(new Uint8Array(n));
  const rid = () => b64(rnd(12)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const nameDisp = (s) => String(s || "").trim().split(/\s+/).join(" ").slice(0, 48);
  const nameKey = (s) => nameDisp(s).toLowerCase();
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const toast = (m, ms, level, action) => { try { window.__toast?.(m, ms || 5000, { level: level || "event", action }); } catch {} };
  const hex = (u8) => [...new Uint8Array(u8)].map((x) => x.toString(16).padStart(2, "0")).join("");

  // ---- crypto ---------------------------------------------------------------------------------------------------------
  async function codeKey(code, salt, iter) {
    const base = await subtle.importKey("raw", enc.encode(code), "PBKDF2", false, ["deriveKey"]);
    return subtle.deriveKey({ name: "PBKDF2", salt, iterations: iter, hash: "SHA-256" }, base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  }
  const kidOf = async (pubRaw) => hex(await subtle.digest("SHA-256", pubRaw)).slice(0, 16);
  async function makeIdentity(nk, code) {
    const kp = await subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);   // extractable ONCE: to wrap it
    const pk8 = new Uint8Array(await subtle.exportKey("pkcs8", kp.privateKey));
    const pub = new Uint8Array(await subtle.exportKey("raw", kp.publicKey));
    const salt = rnd(16), iv = rnd(12);
    const wk = await codeKey(code, salt, ITER);
    const wrapped = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv, additionalData: enc.encode("kastr-msg-id-v1|" + nk) }, wk, pk8));
    const priv = await subtle.importKey("pkcs8", pk8, { name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);   // the copy kept: non-extractable
    pk8.fill(0);
    return { priv, pub: b64(pub), kid: await kidOf(pub), wrapped: b64(wrapped), iv: b64(iv), salt: b64(salt), iter: ITER };
  }
  async function openWrap(per, code) {   // -> the PKCS#8 bytes (callers import or re-wrap them, then wipe)
    const wk = await codeKey(code, unb64(per.salt), Number(per.iter) || ITER);
    return new Uint8Array(await subtle.decrypt({ name: "AES-GCM", iv: unb64(per.iv), additionalData: enc.encode("kastr-msg-id-v1|" + per.nk) }, wk, unb64(per.wrapped)));
  }
  async function rewrap(pk8, nk, code) {
    const salt = rnd(16), iv = rnd(12);
    const wk = await codeKey(code, salt, ITER);
    const wrapped = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv, additionalData: enc.encode("kastr-msg-id-v1|" + nk) }, wk, pk8));
    return { wrapped: b64(wrapped), iv: b64(iv), salt: b64(salt), iter: ITER };
  }
  async function pairKey(priv, theirPub, cid, skid, rkid) {
    const pk = await subtle.importKey("raw", unb64(theirPub), { name: "ECDH", namedCurve: "P-256" }, false, []);
    const bits = await subtle.deriveBits({ name: "ECDH", public: pk }, priv, 256);
    const hk = await subtle.importKey("raw", bits, "HKDF", false, ["deriveKey"]);
    return subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: enc.encode(cid), info: enc.encode("kastr-msg-wrap-v1|" + skid + "|" + rkid) },
      hk, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  }
  async function aesKey(raw, uses) { return subtle.importKey("raw", raw, "AES-GCM", false, uses); }

  // ---- IndexedDB: my identity (a non-extractable CryptoKey), my copy of the history, the outbox, decrypted pictures -------
  let dbP = null;
  function db() {
    if (!dbP) dbP = new Promise((res, rej) => {
      const r = indexedDB.open("kastr-msg", 1);
      r.onupgradeneeded = () => {
        const d = r.result;
        d.createObjectStore("ids", { keyPath: "k" });
        d.createObjectStore("msgs", { keyPath: "k" }).createIndex("by", "by");
        d.createObjectStore("meta", { keyPath: "k" });
        d.createObjectStore("outbox", { keyPath: "cid" });
        d.createObjectStore("blobs", { keyPath: "fid" });
      };
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    return dbP;
  }
  async function tx(store, mode, fn) {
    const d = await db();
    return new Promise((res, rej) => {
      const t = d.transaction(store, mode), s = t.objectStore(store);
      let out;
      Promise.resolve(fn(s)).then((v) => { out = v; });
      t.oncomplete = () => res(out);
      t.onerror = () => rej(t.error);
      t.onabort = () => rej(t.error);
    });
  }
  const req = (r) => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  const idbGet = (store, k) => tx(store, "readonly", (s) => req(s.get(k)));
  const idbPut = (store, v) => tx(store, "readwrite", (s) => { s.put(v); });
  const idbDel = (store, k) => tx(store, "readwrite", (s) => { s.delete(k); });
  const idbAll = (store, index, key) => tx(store, "readonly", (s) => req(index ? s.index(index).getAll(key) : s.getAll()));

  // ---- state ----------------------------------------------------------------------------------------------------------
  const S = {
    state: "off", why: "", fleet: "", nk: "", name: "", id: null, kid: "", cur: 0, top: 0,
    recs: new Map(),       // "seq:<n>" | "cid:<id>" (mine, not yet back from the hub) -> a message
    groups: new Map(), reads: {}, open: "", keys: new Map(), lastPing: 0, busy: false, histDone: false, devices: 0,
    view: "list", picker: null, filter: "", people: [], peopleAt: 0, ticks: {}, codeMin: 8, hubDown: false, settings: false,
  };
  const by = () => S.fleet + "|" + S.nk;
  const renameMap = new Map();   // 0.21.91: old name key -> {key, name} (people who changed their name)
  const convOf = (r) => (r.gid ? "g:" + r.gid : "p:" + (r.mine ? r.to : r.from));
  const meName = () => nameDisp(K.personal()?.name || K.me());

  // ---- the hub (through this page's relay host) --------------------------------------------------------------------------
  async function api(body, ms) {
    const base = K.base(), tok = K.token();
    if (!base || !tok) return { ok: false, status: 0, error: "not joined" };
    const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), ms || 25000);
    try {
      const r = await fetch(base + "/api/msg", { method: "POST", headers: { "content-type": "application/json", authorization: "Bearer " + tok },
        body: JSON.stringify(body), signal: ctl.signal, cache: "no-store" });
      const d = await r.json().catch(() => ({}));
      if (r.status === 404 && !d.ok && !d.error) return { ok: false, status: 404, old: true, error: "this relay’s KASTR is older than 0.21.88" };
      return Object.assign({}, d, { ok: r.ok && d.ok !== false, status: r.status });
    } catch (e) { return { ok: false, status: 0, net: true, error: String(e?.message || e) }; }
    finally { clearTimeout(t); }
  }
  async function fileUp(blob) {
    const base = K.base(), tok = K.token();
    const r = await fetch(base + "/api/msg/file?as=" + encodeURIComponent(S.name), { method: "POST",
      headers: { "content-type": "application/octet-stream", authorization: "Bearer " + tok }, body: blob });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.fid) throw Object.assign(new Error(d.error || ("HTTP " + r.status)), { status: r.status });
    return d.fid;
  }
  async function fileDown(fid) {
    const r = await fetch(K.base() + "/api/msg/file?id=" + encodeURIComponent(fid), { headers: { authorization: "Bearer " + K.token() }, cache: "no-store" });
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.error || ("HTTP " + r.status)); }
    return new Uint8Array(await r.arrayBuffer());
  }

  // ---- set-up: who am I here, is this device unlocked ------------------------------------------------------------------
  function setState(st, why) {
    if (S.state === st && S.why === (why || "")) return;
    S.state = st; S.why = why || "";
    T("state", { st, why });
    paint();
  }
  let initBusy = false, initAgain = false;
  async function init(force) {
    if (!subtle || !window.indexedDB) { setState("nocrypto"); return; }
    if (!K.allowed()) { if (S.state !== "off") { S.state = "off"; S.id = null; } paintBtn(); return; }
    if (initBusy) { initAgain = true; return; }
    const name = meName(), nk = nameKey(name);
    if (!nk) { setState("noname"); return; }
    if (!force && S.state === "ready" && S.nk === nk) return;
    initBusy = true;
    try {
      if (S.nk !== nk) { S.recs.clear(); S.groups.clear(); S.reads = {}; S.cur = 0; S.open = ""; S.histDone = false; S.keys.clear(); }
      S.name = name; S.nk = nk;
      const st = await api({ op: "status", name });
      if (!st.ok) {
        if (st.old) { setState("old"); return; }
        if (st.status === 503 || st.net) { S.hubDown = true; setState(S.id ? "ready" : "down", st.error); return; }
        setState("error", st.error); return;
      }
      S.hubDown = false;
      S.fleet = String(st.fleet || ""); S.codeMin = Number(st.codeMin) || 8;
      const mv = (st.renamed || {})[nk];
      if (mv && mv.key && mv.key !== nk) { initBusy = false; await selfRenamed(nk, mv.key, mv.name || mv.key); return; }   // 0.21.91: renamed on another device
      const local = await idbGet("ids", by()).catch(() => null);
      if (st.blocked) { if (local) await idbDel("ids", by()).catch(() => {}); S.id = null; setState("blocked"); return; }
      if (local && st.has && st.unlocked && local.kid === st.kid) { await ready(local); return; }
      if (local && (!st.has || local.kid !== st.kid)) { await idbDel("ids", by()).catch(() => {}); }
      if (!st.myRoom) { S.id = null; setState("noroom"); return; }
      const p = K.personal();
      if (p && nameKey(p.name) === nk && p.code) { await unlock(p.code, true); return; }
      S.id = null;
      setState("needcode");
    } finally {
      initBusy = false;
      if (initAgain) { initAgain = false; setTimeout(() => init(), 50); }
    }
  }
  // name + My room code -> the identity (made here the first time)
  async function unlock(code, auto, newCode) {
    setState("unlocking");
    const u = await api({ op: "unlock", name: S.name, code });
    if (!u.ok) {
      if (u.wrong) { setState("needcode", auto ? "This device’s saved My room code did not work — enter it again." : "Wrong My room code."); return false; }
      if (u.blocked) { setState("blocked"); return false; }
      if (u.status === 429) { setState("needcode", u.error || "Too many attempts — wait a little."); return false; }
      if (u.status === 503 || u.net) { S.hubDown = true; setState("down", u.error); return false; }
      setState("error", u.error); return false;
    }
    S.fleet = String(u.fleet || S.fleet);
    if (u.setup) {
      const use = newCode || code;
      if (use.length < S.codeMin) { S.pendingCode = code; setState("short"); return false; }
      const id = await makeIdentity(S.nk, use);
      const s = await api({ op: "setup", name: S.name, code, newCode: newCode || undefined, pub: id.pub, wrapped: id.wrapped, iv: id.iv, salt: id.salt, iter: id.iter });
      if (!s.ok) {
        if (s.exists) return unlock(code, auto);
        if (s.short) { S.pendingCode = code; setState("short"); return false; }
        setState("error", s.error); return false;
      }
      if (newCode) K.savePersonalCode?.(newCode);
      const rec = { k: by(), fleet: S.fleet, nk: S.nk, name: S.name, kid: id.kid, pub: id.pub, priv: id.priv, at: Date.now() };
      await idbPut("ids", rec);
      T("setup", { kid: id.kid });
      await ready(rec);
      return true;
    }
    const per = u.person;
    let pk8 = null;
    try { pk8 = await openWrap(per, code); }
    catch { S.rekey = per; S.rekeyCode = code; setState("rekey"); return false; }   // My room's code changed without a re-wrap (an admin reset it)
    const priv = await subtle.importKey("pkcs8", pk8, { name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
    pk8.fill(0);
    const rec = { k: by(), fleet: S.fleet, nk: S.nk, name: per.name || S.name, kid: per.kid, pub: per.pub, priv, at: Date.now() };
    await idbPut("ids", rec);
    T("unlocked", { kid: per.kid });
    await ready(rec);
    return true;
  }
  async function ready(rec) {
    S.id = rec; S.kid = rec.kid;
    const cur = await idbGet("meta", "cur|" + by()).catch(() => null);
    S.cur = Number(cur?.v) || 0;
    S.histDone = S.cur > 0;
    const g = await idbGet("meta", "groups|" + by()).catch(() => null);
    if (Array.isArray(g?.v)) for (const x of g.v) S.groups.set(x.gid, x);
    const rd = await idbGet("meta", "reads|" + by()).catch(() => null);
    if (rd?.v) S.reads = rd.v;
    await loadLocal();
    setState("ready");
    pull();
    outboxRetry();
  }
  async function loadLocal() {
    const cut = Date.now() - KEEP_MS;
    const rows = await idbAll("msgs", "by", by()).catch(() => []);
    for (const r of rows) {
      if (r.at * 1000 < cut) { idbDel("msgs", r.k).catch(() => {}); continue; }
      S.recs.set("seq:" + r.seq, r);
    }
    const ob = await idbAll("outbox").catch(() => []);
    for (const o of ob) if (o.by === by()) S.recs.set("cid:" + o.cid, Object.assign({}, o.rec, { waiting: true, outbox: o }));
  }

  // ---- pull --------------------------------------------------------------------------------------------------------------
  let pullAgain = false;
  async function pull() {
    if (S.state !== "ready" || !K.allowed()) return;
    if (S.busy) { pullAgain = true; return; }
    S.busy = true;
    let fresh = [];
    try {
      for (let round = 0; round < 30; round++) {
        const d = await api({ op: "pull", as: [S.name], since: S.cur, ack: S.cur });
        if (!d.ok) {
          if (d.status === 503 || d.net) { if (!S.hubDown) { S.hubDown = true; paint(); } }
          break;
        }
        if (S.hubDown) { S.hubDown = false; paint(); outboxRetry(); }
        if ((d.locked || []).includes(S.nk)) { await lockedOut(); return; }
        if (d.fleet && d.fleet !== S.fleet) break;
        const mv = (d.renamed || {})[S.nk];   // 0.21.91: I changed my name on another device -- this copy moves over first
        if (mv && mv.key && mv.key !== S.nk) { S.busy = false; await selfRenamed(S.nk, mv.key, mv.name || mv.key); return; }
        applyRenames(d.renames || []);   // 0.21.91: someone else did -- my copy of our conversation follows
        S.top = Number(d.top) || S.top;
        for (const g of d.groups || []) S.groups.set(g.gid, g);
        idbPut("meta", { k: "groups|" + by(), v: [...S.groups.values()] }).catch(() => {});
        const rd = (d.reads || {})[S.nk];
        if (rd && JSON.stringify(rd) !== JSON.stringify(S.reads)) { S.reads = Object.assign({}, S.reads, rd); idbPut("meta", { k: "reads|" + by(), v: S.reads }).catch(() => {}); }
        for (const m of d.msgs || []) {
          const r = await openMsg(m, d.keys || {});
          if (r) {
            if (r.cid) for (const [k, x] of S.recs) if (x.seq && x.seq !== r.seq && x.cid === r.cid && x.from === r.from) { S.recs.delete(k); idbDel("msgs", x.k).catch(() => {}); }   // renumbered by a hub hand-back
            S.recs.set("seq:" + r.seq, r);
            if (r.mine && r.cid && S.recs.has("cid:" + r.cid)) { S.recs.delete("cid:" + r.cid); idbDel("outbox", r.cid).catch(() => {}); }
            idbPut("msgs", r).catch(() => {});
            fresh.push(r);
          }
          S.cur = Math.max(S.cur, Number(m.seq) || 0);
        }
        idbPut("meta", { k: "cur|" + by(), v: S.cur }).catch(() => {});
        notes((d.notes || {})[S.nk] || []);
        if (!d.more) break;
      }
      if (fresh.length) {
        await api({ op: "pull", as: [S.name], since: S.cur, ack: S.cur });   // ack at once (the sender's "delivered")
        arrived(fresh);
      }
    } finally {
      S.busy = false;
      paint();
      if (pullAgain) { pullAgain = false; setTimeout(pull, 100); }
    }
  }
  async function openMsg(m, keys) {
    const base = { k: by() + "|" + m.seq, by: by(), seq: Number(m.seq), at: Number(m.at), cid: m.cid || "", from: m.from, fromName: m.fromName || m.from,
                   gid: m.gid || "", to: m.to || "", toName: m.toName || "", kind: m.kind || "msg" };
    base.mine = base.from === S.nk;
    if (m.kind === "sys") return Object.assign(base, { sys: m.sys || {} });
    const w = (m.wraps || {})[S.kid];
    const sk = keys[m.fromKid];
    if (!w || !sk) return Object.assign(base, { locked: true });
    try {
      const kk = await pairKey(S.id.priv, sk.pub, m.cid, m.fromKid, S.kid);
      const raw = new Uint8Array(await subtle.decrypt({ name: "AES-GCM", iv: unb64(w.iv) }, kk, unb64(w.w)));
      const ck = await aesKey(raw, ["decrypt"]);
      raw.fill(0);
      const body = JSON.parse(dec.decode(await subtle.decrypt({ name: "AES-GCM", iv: unb64(m.iv), additionalData: enc.encode("kastr-msg-v1|" + m.cid) }, ck, unb64(m.ct))));
      return Object.assign(base, { text: String(body.t || ""), files: Array.isArray(body.files) ? body.files.slice(0, 10) : [] });
    } catch (e) {
      T("decrypt-fail", { seq: m.seq, e: String(e?.message || e) });
      return Object.assign(base, { bad: true });
    }
  }
  async function lockedOut() {
    await idbDel("ids", by()).catch(() => {});
    S.id = null;
    setState("blocked");
  }
  function notes(list) {
    let seen = {};
    try { seen = JSON.parse(localStorage.getItem("kastr.msg.notes") || "{}"); } catch {}
    let changed = false;
    for (const n of list) {
      if (!n?.id || seen[n.id]) continue;
      seen[n.id] = Date.now(); changed = true;
      if (n.host === K.host()) continue;
      const when = Date.now() - Number(n.at) * 1000 < 86400000;
      if (!when) continue;
      const what = n.kind === "removed" ? "An admin removed the device “" + n.host + "” from your messages"
        : n.kind === "replaced" ? "Your messaging key was replaced on “" + n.host + "” — this device must unlock again"
        : "A new device (“" + n.host + "”) unlocked your messages with your My room code";
      toast(what + ". If that wasn’t you, change your My room code (Messages → settings) and tell an admin.", 12000, "warn");
      S.lastNote = { what, at: n.at, host: n.host };
      if (n.kind === "replaced") init(true);
    }
    if (changed) { for (const k of Object.keys(seen)) if (Date.now() - seen[k] > 60 * 86400000) delete seen[k]; try { localStorage.setItem("kastr.msg.notes", JSON.stringify(seen)); } catch {} }
  }
  function arrived(fresh) {
    const first = !S.histDone;
    S.histDone = true;
    if (first) return;   // a new device's first pull is history, not news
    const news = fresh.filter((r) => !r.mine && r.kind === "msg" && Date.now() - r.at * 1000 < 10 * 60000);
    if (!news.length) return;
    const r = news[news.length - 1];
    const conv = convOf(r);
    const viewing = panelShown() && S.open === conv && document.visibilityState === "visible";
    if (viewing) { markRead(conv); return; }
    const g = r.gid ? S.groups.get(r.gid) : null;
    const who = r.fromName + (g ? " in " + g.name : "");
    const what = r.text ? r.text.slice(0, 120) : (r.files || []).length ? (IMG_TYPES.test(r.files[0].type || "") ? "a picture" : "a file") : "a message";
    toast(who + ": " + what, 7000, "event", { label: "Open", fn: () => openConv(conv) });
    chime();
    if (document.visibilityState !== "visible" && "Notification" in window && Notification.permission === "granted") {
      try {
        const n = new Notification("KASTR — " + who, { body: what, tag: "kastr-msg-" + conv, silent: false });
        n.onclick = () => { try { window.focus(); } catch {} openConv(conv); n.close(); };
      } catch {}
    }
  }
  function chime() {
    try {
      const ac = new (window.AudioContext || window.webkitAudioContext)();
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = "sine"; o.frequency.value = 880; g.gain.value = 0.0001;
      o.connect(g); g.connect(ac.destination);
      const t = ac.currentTime;
      g.gain.exponentialRampToValueAtTime(0.06, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
      o.frequency.setValueAtTime(880, t); o.frequency.setValueAtTime(1320, t + 0.12);
      o.start(t); o.stop(t + 0.4);
      setTimeout(() => ac.close().catch(() => {}), 800);
    } catch {}
  }

  // ---- keys + send ---------------------------------------------------------------------------------------------------------
  async function keysFor(names, force) {
    const want = [...new Set(names.map(nameKey).filter(Boolean))];
    const miss = want.filter((n) => force || !S.keys.has(n) || Date.now() - S.keys.get(n).at > 60000);
    if (miss.length) {
      const d = await api({ op: "keys", names: miss });
      if (!d.ok) throw Object.assign(new Error(d.error || "keys"), { net: d.net || d.status === 503 });
      for (const n of miss) {   // 0.21.91: a name someone changed away from answers with their new name's key
        const mv = (d.renamed || {})[n];
        if (mv?.key) { renameMap.set(n, { key: mv.key, name: mv.name }); }
        S.keys.set(n, { row: (d.keys || {})[n] || (mv?.key ? (d.keys || {})[mv.key] : null) || null, at: Date.now() });
      }
    }
    const out = {};
    for (const n of want) out[n] = S.keys.get(n)?.row || null;
    return out;
  }
  function readersOf(conv) {
    if (conv.startsWith("g:")) return [...(S.groups.get(conv.slice(2))?.members || [])];
    return [conv.slice(2), S.nk];
  }
  async function seal(conv, cid, body) {
    const keys = await keysFor(readersOf(conv));
    const Kraw = rnd(32), iv = rnd(12);
    const ck = await aesKey(Kraw, ["encrypt"]);
    const ct = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv, additionalData: enc.encode("kastr-msg-v1|" + cid) }, ck, enc.encode(JSON.stringify(body))));
    const wraps = {};
    for (const row of Object.values(keys)) {
      if (!row) continue;
      const kk = await pairKey(S.id.priv, row.pub, cid, S.kid, row.kid);
      const wiv = rnd(12);
      wraps[row.kid] = { iv: b64(wiv), w: b64(new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv: wiv }, kk, Kraw))) };
    }
    Kraw.fill(0);
    return { iv: b64(iv), ct: b64(ct), wraps, missing: Object.entries(keys).filter(([, v]) => !v).map(([k]) => k) };
  }
  async function send(conv, text, files) {
    text = String(text || "").slice(0, 20000);
    files = (files || []).slice(0, 10);
    if (!text.trim() && !files.length) return;
    { const mv = conv.startsWith("p:") ? renameMap.get(conv.slice(2)) : null; if (mv?.key) conv = "p:" + mv.key; }   // 0.21.91: to their new name
    const cid = rid();
    const rec = { k: "cid:" + cid, by: by(), cid, at: Math.floor(Date.now() / 1000), from: S.nk, fromName: S.name, mine: true, kind: "msg", text,
                  files: files.map((f) => ({ name: f.name || "file", type: f.type || "", size: f.size, local: URL.createObjectURL(f) })),
                  gid: conv.startsWith("g:") ? conv.slice(2) : "", to: conv.startsWith("p:") ? conv.slice(2) : "", sending: true };
    S.recs.set(rec.k, rec);
    paint();
    const ob = { cid, by: by(), conv, text, files, rec: Object.assign({}, rec, { files: rec.files.map(({ local, ...x }) => x) }) };
    idbPut("outbox", ob).catch(() => {});
    rec.outbox = ob;
    await deliver(rec, ob);
  }
  async function deliver(rec, ob) {
    rec.sending = true; rec.waiting = false; rec.err = "";
    paint();
    try {
      const metas = [];
      for (let i = 0; i < ob.files.length; i++) {
        const f = ob.files[i];
        if (f.size > FILE_MAX) throw Object.assign(new Error("“" + (f.name || "file") + "” is over 25 MB"), { fatal: true });
        if (ob.metas?.[i]) { metas.push(ob.metas[i]); continue; }
        const raw = new Uint8Array(await f.arrayBuffer());
        const fk = rnd(32), fiv = rnd(12);
        const ct = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv: fiv }, await aesKey(fk, ["encrypt"]), raw));
        const fid = await fileUp(new Blob([ct]));
        const meta = { fid, name: String(f.name || "file").slice(0, 120), type: String(f.type || "").slice(0, 80), size: raw.length, k: b64(fk), iv: b64(fiv) };
        metas.push(meta);
        if (raw.length <= 8 * 1024 * 1024) idbPut("blobs", { fid, by: by(), at: Date.now(), blob: new Blob([raw], { type: meta.type }) }).catch(() => {});
        ob.metas = metas.slice();
        idbPut("outbox", ob).catch(() => {});
      }
      const body = { v: 1, t: ob.text, files: metas };
      let sealed = await seal(ob.conv, ob.cid, body);
      if (ob.conv.startsWith("p:") && sealed.missing.includes(ob.conv.slice(2))) throw Object.assign(new Error(convTitle(ob.conv) + " hasn’t set up messages yet"), { fatal: true });
      const send1 = (s) => api({ op: "send", as: S.name, cid: ob.cid, iv: s.iv, ct: s.ct, wraps: s.wraps, files: metas.map((m) => m.fid),
                                 gid: ob.conv.startsWith("g:") ? ob.conv.slice(2) : undefined, to: ob.conv.startsWith("p:") ? ob.conv.slice(2) : undefined });
      let d = await send1(sealed);
      if (!d.ok && d.status === 409 && d.stale) { await keysFor(readersOf(ob.conv), true); sealed = await seal(ob.conv, ob.cid, body); d = await send1(sealed); }
      if (!d.ok) {
        if (d.status === 503 || d.net || d.status === 429) throw Object.assign(new Error(d.error || "the hub is unreachable"), { retry: true });
        throw Object.assign(new Error(d.error || ("HTTP " + d.status)), { fatal: true });
      }
      rec.sending = false; rec.seq = d.seq;
      T("sent", { cid: ob.cid, seq: d.seq });
      pull();
    } catch (e) {
      rec.sending = false;
      if (e.fatal) { rec.err = String(e.message || e); idbDel("outbox", ob.cid).catch(() => {}); }
      else { rec.waiting = true; rec.err = ""; S.hubDown = S.hubDown || !!e.retry || e.status === 503 || !e.status; clearTimeout(obTimer); obTimer = setTimeout(outboxRetry, 10000); }
      T("send-fail", { cid: ob.cid, e: String(e?.message || e) });
    }
    paint();
  }
  let obTimer = 0;
  function outboxRetry() {
    clearTimeout(obTimer);
    const waiting = [...S.recs.values()].filter((r) => r.waiting && r.outbox && r.by === by());
    if (!waiting.length || S.state !== "ready") return;
    (async () => { for (const r of waiting) await deliver(r, r.outbox); })();
    obTimer = setTimeout(outboxRetry, 15000);
  }

  // ---- reads + ticks -------------------------------------------------------------------------------------------------------
  const unreadOf = (conv) => [...S.recs.values()].filter((r) => r.seq && !r.mine && r.kind === "msg" && convOf(r) === conv && r.seq > (Number(S.reads[conv]) || 0)).length;
  let readT = 0;
  function markRead(conv) {
    const last = Math.max(0, ...[...S.recs.values()].filter((r) => r.seq && convOf(r) === conv).map((r) => r.seq));
    if (!last || last <= (Number(S.reads[conv]) || 0)) return;
    S.reads[conv] = last;
    idbPut("meta", { k: "reads|" + by(), v: S.reads }).catch(() => {});
    clearTimeout(readT);
    readT = setTimeout(() => api({ op: "read", as: S.name, conv, seq: last }), 400);
    paintBtn();
  }
  async function ticks() {
    if (S.state !== "ready" || !S.open.startsWith("p:") || !panelShown()) return;
    const d = await api({ op: "ticks", as: S.name, names: [S.open.slice(2)] });
    if (d.ok) { const t = (d.ticks || {})[S.open.slice(2)]; if (t && JSON.stringify(t) !== JSON.stringify(S.ticks[S.open])) { S.ticks[S.open] = t; paintConv(); } }
  }

  // ---- the panel ---------------------------------------------------------------------------------------------------------
  const panel = K.panel(), btn = K.btn();
  const body = panel.querySelector("#msgBody");
  const panelShown = () => !panel.hidden && !panel.classList.contains("folded");
  function convTitle(conv) {
    if (conv.startsWith("g:")) return S.groups.get(conv.slice(2))?.name || "Group";
    const nk = conv.slice(2);
    for (const r of S.recs.values()) {
      if (!r.mine && r.from === nk && r.fromName) return r.fromName;
      if (r.mine && r.to === nk && r.toName) return r.toName;
    }
    const p = S.people.find((x) => nameKey(x.name) === nk);
    return p?.name || S.keys.get(nk)?.row?.name || nk.replace(/\b\w/g, (c) => c.toUpperCase());
  }
  function convs() {
    const m = new Map();
    for (const r of S.recs.values()) {
      if (r.by !== by()) continue;
      const c = convOf(r);
      if (c.startsWith("g:")) { const g = S.groups.get(r.gid); if (!g || g.deleted || !(g.members || []).includes(S.nk)) continue; }
      const x = m.get(c) || { conv: c, last: null, at: 0 };
      const ord = (q) => (q.seq ? q.seq : 1e15 + q.at);   // a message still on its way is the newest
      if (!x.last || ord(r) >= ord(x.last)) { x.last = r; x.at = r.at; }
      m.set(c, x);
    }
    for (const g of S.groups.values()) if (!g.deleted && (g.members || []).includes(S.nk) && !m.has("g:" + g.gid)) m.set("g:" + g.gid, { conv: "g:" + g.gid, last: null, at: g.at });
    if (S.open && !m.has(S.open) && S.open.startsWith("p:")) m.set(S.open, { conv: S.open, last: null, at: Date.now() / 1000 });
    return [...m.values()].map((x) => Object.assign(x, { title: convTitle(x.conv), unread: unreadOf(x.conv) })).sort((a, b) => b.at - a.at);
  }
  function totalUnread() { return convs().reduce((n, c) => n + c.unread, 0); }
  function paintBtn() {
    const on = K.allowed() && S.state !== "off";
    btn.hidden = !on;
    const b = btn.querySelector(".bdg");
    if (!b) return;
    const n = S.state === "ready" ? totalUnread() : 0;
    const was = b.hidden ? 0 : Number(b.textContent) || 0;
    b.hidden = n === 0;
    b.textContent = n > 99 ? "99+" : String(n);
    if (n > was) { b.classList.remove("pulse"); void b.offsetWidth; b.classList.add("pulse"); }
    btn.title = "Messages" + (n ? " — " + n + " unread" : "");
  }
  const fmtTime = (s) => { const d = new Date(s * 1000), now = new Date(); return d.toDateString() === now.toDateString() ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : Date.now() - d < 6 * 86400000 ? d.toLocaleDateString([], { weekday: "short" }) : d.toLocaleDateString([], { month: "short", day: "numeric" }); };
  const fmtDay = (s) => { const d = new Date(s * 1000), now = new Date(); if (d.toDateString() === now.toDateString()) return "Today";
    const y = new Date(now); y.setDate(now.getDate() - 1); if (d.toDateString() === y.toDateString()) return "Yesterday";
    return d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" }); };
  const fmtSize = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : n >= 1024 ? Math.round(n / 1024) + " KB" : n + " B");
  function avatar(name, key, small) {
    const d = document.createElement("div");
    d.className = "mav" + (small ? " sm" : "");
    d.style.setProperty("--ring", K.color(key || nameKey(name)));
    d.textContent = K.initials(name);
    if (!String(key || "").startsWith("g:")) { try { K.photo?.(d, name); } catch {} }   // 0.21.90: their photo over the initials
    return d;
  }
  function preview(r) {
    if (!r) return "";
    if (r.kind === "sys") return sysText(r);
    if (r.locked) return "Sent before this key was made";
    if (r.bad) return "Could not be opened";
    const who = r.mine ? "You: " : r.gid ? r.fromName.split(" ")[0] + ": " : "";
    if (r.text) return who + r.text.replace(/\s+/g, " ").slice(0, 80);
    const f = (r.files || [])[0];
    return f ? who + (IMG_TYPES.test(f.type || "") ? "Picture" : f.name) : "";
  }
  function sysText(r) {
    const s = r.sys || {}, who = r.mine ? "You" : r.fromName, names = (s.names || []).join(", ");
    return s.ev === "create" ? who + " made the group “" + (s.name || "") + "”" + (names ? " with " + names : "")
      : s.ev === "add" ? who + " added " + names : s.ev === "remove" ? who + " removed " + names
      : s.ev === "leave" ? who + " left" : s.ev === "rename" ? who + " renamed the group “" + (s.name || "") + "”"
      : s.ev === "renamed" ? (s.from || who) + " is now " + (s.name || who) : who + " changed the group";   // 0.21.91: a person's new name
  }

  let wide = false;
  try { new ResizeObserver(() => { const w = panel.clientWidth >= 560; if (w !== wide) { wide = w; paint(); } }).observe(panel); } catch {}
  function paint() {
    paintBtn();
    if (panel.hidden) return;
    panel.classList.toggle("mwide", wide);
    panel.classList.toggle("mconv", !!S.open && S.view === "conv");
    const st = S.state;
    if (st !== "ready") { paintSetup(); return; }
    if (!body.querySelector(".mlist")) {
      body.dataset.view = "";
      body.innerHTML = '<div class="mlist"><div class="mlhead"><label class="msearch"><input type="search" placeholder="Search" autocomplete="off" spellcheck="false"></label>'
        + '<button type="button" class="mnew" title="New message or group">' + K.icon("plusc") + '<span>New</span></button><button type="button" class="mgear" title="Messages settings">' + K.icon("more") + '</button></div>'
        + '<div class="mbanner" hidden></div><div class="mrows" role="listbox" aria-label="Conversations"></div></div>'
        + '<div class="mconvpane"></div>';
      const q = body.querySelector(".msearch input");
      q.value = S.filter;
      q.addEventListener("input", () => { S.filter = q.value; paintList(); });
      body.querySelector(".mnew").addEventListener("click", (e) => { e.stopPropagation(); openPicker("new"); });
      body.querySelector(".mgear").addEventListener("click", (e) => { e.stopPropagation(); S.settings = !S.settings; S.picker = null; paintList(); });
    }
    paintList();
    paintConv();
  }
  function bannerHtml() {
    const out = [];
    if (S.hubDown) out.push('<div class="mwarn">The hub is unreachable — new messages wait there; yours are sent when it is back.</div>');
    if ("Notification" in window && Notification.permission === "default" && localStorage.getItem("kastr.msg.notifAsk") !== "no")
      out.push('<div class="mnote">Show a desktop notification when a message arrives while KASTR is minimised? <span class="mrow2"><button type="button" class="mprim" data-a="notif-on">Turn on</button><button type="button" class="mghost" data-a="notif-no">Not now</button></span></div>');
    return out.join("");
  }
  function paintList() {
    const list = body.querySelector(".mrows");
    if (!list) return;
    const ban = body.querySelector(".mbanner");
    const bh = bannerHtml();
    ban.hidden = !bh; if (ban.__h !== bh) { ban.innerHTML = bh; ban.__h = bh; }
    for (const b of ban.querySelectorAll("button[data-a]")) b.onclick = (e) => { e.stopPropagation(); bannerAct(b.dataset.a); };
    if (S.settings) { paintSettings(list); return; }
    if (S.picker) { paintPicker(list); return; }
    const f = S.filter.trim().toLowerCase();
    const rows = convs().filter((c) => !f || c.title.toLowerCase().includes(f) || [...S.recs.values()].some((r) => convOf(r) === c.conv && (r.text || "").toLowerCase().includes(f)));
    const els = rows.map((c) => {
      const row = document.createElement("div");
      row.className = "mrow" + (c.conv === S.open ? " on" : "") + (c.unread ? " unread" : "");
      row.setAttribute("role", "option"); row.tabIndex = 0; row.dataset.conv = c.conv;
      const g = c.conv.startsWith("g:");
      const av = avatar(c.title, g ? c.conv : c.conv.slice(2));
      if (g) av.classList.add("grp");
      const mid = document.createElement("div"); mid.className = "mmid";
      mid.innerHTML = '<div class="mt"><span class="mn"></span><span class="mtime"></span></div><div class="mp"><span class="mprev"></span><span class="mun"></span></div>';
      mid.querySelector(".mn").textContent = c.title;
      mid.querySelector(".mtime").textContent = c.last ? fmtTime(c.last.at) : "";
      mid.querySelector(".mprev").textContent = c.last ? preview(c.last) : g ? (S.groups.get(c.conv.slice(2))?.members || []).length + " people" : "";
      const un = mid.querySelector(".mun"); un.textContent = c.unread ? String(c.unread) : ""; un.hidden = !c.unread;
      row.append(av, mid);
      const go = () => openConv(c.conv);
      row.addEventListener("click", (e) => { e.stopPropagation(); go(); });
      row.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
      return row;
    });
    if (!els.length) {
      const e = document.createElement("div"); e.className = "mempty";
      e.textContent = f ? "Nothing matches “" + S.filter.trim() + "”." : "No messages yet. Press New to write to someone — they get it even if they are offline.";
      els.push(e);
    }
    list.replaceChildren(...els);
  }
  function bannerAct(a) {
    if (a === "notif-on") { try { Notification.requestPermission().then(() => paint()); } catch {} }
    if (a === "notif-no") { try { localStorage.setItem("kastr.msg.notifAsk", "no"); } catch {} paint(); }
  }

  // ---- the set-up states ---------------------------------------------------------------------------------------------------
  function paintSetup() {
    const st = S.state;
    const t = {
      off: ["Messages", "Join a room to use messages."],
      nocrypto: ["Messages", "This browser cannot keep messages private (no WebCrypto / IndexedDB here)."],
      noname: ["Messages", "Set your name first (Profile)."],
      old: ["Messages need an update", "This relay’s KASTR is older than 0.21.88 — update the relay host (and the hub) to use messages."],
      error: ["Messages", "Messages could not start: " + (S.why || "unknown error")],
      down: ["The hub is unreachable", "Messages live on the hub. KASTR keeps trying."],
      unlocking: ["Opening your messages…", "Checking your My room code and opening your key on this device."],
      blocked: ["This device was removed", "An admin removed this device from " + (S.name || "your") + "’s messages. Ask an admin to allow it again."],
      noroom: ["Set up messages", "Messages use your name and your My room code: anyone who knows them can read your messages on any device, so pick a code only you know (at least " + S.codeMin + " characters)."],
      needcode: ["Unlock your messages", "Enter your My room code to read your messages on this device — the same name and code on any device show all your messages (90 days)."],
      short: ["Pick a longer code", "Your My room code is shorter than " + S.codeMin + " characters. Messages need a longer one (it protects your key on the hub); this also becomes your My room code."],
      rekey: ["Your key needs the old code", "Your messages key was locked with an earlier My room code (an admin may have reset it). Enter that earlier code to keep your history — or start fresh (messages from before cannot be read again)."],
    }[st] || ["Messages", ""];
    const id = "mset-" + st + "-" + (S.why || "");
    if (body.dataset.view === id) return;
    body.dataset.view = id;
    let html = '<div class="msetup"><div class="mico">' + K.icon("msg") + '</div><h3></h3><p class="mtxt"></p>';
    if (S.why && st !== "error") html += '<p class="merr"></p>';
    if (st === "noroom") html += '<button type="button" class="mprim" data-a="room">Set up My room</button>';
    if (st === "needcode" || st === "rekey") html += '<input class="mcode" type="password" autocomplete="current-password" placeholder="' + (st === "rekey" ? "Earlier My room code" : "My room code") + '"><button type="button" class="mprim" data-a="unlock">Unlock</button>';
    if (st === "rekey") html += '<button type="button" class="mghost" data-a="fresh">Start fresh</button>';
    if (st === "short") html += '<input class="mnew1" type="password" autocomplete="new-password" placeholder="New code (at least ' + S.codeMin + ' characters)"><input class="mnew2" type="password" autocomplete="new-password" placeholder="The new code again"><button type="button" class="mprim" data-a="short">Use this code</button>';
    if (st === "down" || st === "error") html += '<button type="button" class="mghost" data-a="retry">Try again</button>';
    html += "</div>";
    body.innerHTML = html;
    body.querySelector("h3").textContent = t[0];
    body.querySelector(".mtxt").textContent = t[1];
    const err = body.querySelector(".merr"); if (err) err.textContent = S.why;
    const say = (m) => { let e = body.querySelector(".merr"); if (!e) { e = document.createElement("p"); e.className = "merr"; body.querySelector(".msetup").appendChild(e); } e.textContent = m; };
    for (const b of body.querySelectorAll("button[data-a]")) b.addEventListener("click", async (e) => {
      e.stopPropagation();
      const a = b.dataset.a;
      if (a === "room") { K.personalDialog("make", "Messages use this name and code — pick a code of at least " + S.codeMin + " characters that only you know."); return; }
      if (a === "retry") { body.dataset.view = ""; init(true); return; }
      if (a === "unlock") {
        const code = body.querySelector(".mcode").value;
        if (!code) return;
        b.disabled = true; say("Opening…");
        if (st === "rekey") { await rekeyWith(code); b.disabled = false; return; }
        body.dataset.view = "";
        const ok = await unlock(code, false);
        if (ok) K.rememberCode?.(S.name, code);
        return;
      }
      if (a === "fresh") {
        if (!(await K.confirm({ title: "Start fresh", message: "Make a new messages key for " + S.name + "?", detail: "Messages sent to you before cannot be read again on any device. Your other devices must unlock again.", ok: "Start fresh", danger: true }))) return;
        const code = body.querySelector(".mcode").value || K.personal()?.code || "";
        if (!code) { say("Enter your current My room code first."); return; }
        const id = await makeIdentity(S.nk, code);
        const d = await api({ op: "setup", replace: true, name: S.name, code, pub: id.pub, wrapped: id.wrapped, iv: id.iv, salt: id.salt, iter: id.iter });
        if (!d.ok) { say(d.error || "Refused."); return; }
        const rec = { k: by(), fleet: S.fleet, nk: S.nk, name: S.name, kid: id.kid, pub: id.pub, priv: id.priv, at: Date.now() };
        await idbPut("ids", rec); body.dataset.view = ""; await ready(rec);
        return;
      }
      if (a === "short") {
        const n1 = body.querySelector(".mnew1").value, n2 = body.querySelector(".mnew2").value;
        if (n1.length < S.codeMin) { say("At least " + S.codeMin + " characters."); return; }
        if (n1 !== n2) { say("The two codes do not match."); return; }
        const old = S.pendingCode || K.personal()?.code || "";
        if (!old) { say("Enter your current My room code in My room first."); return; }
        b.disabled = true; say("Setting up…");
        body.dataset.view = "";
        await unlock(old, false, n1);
      }
    });
    const inp = body.querySelector(".mcode, .mnew2");
    if (inp) inp.addEventListener("keydown", (e) => { if (e.key === "Enter") body.querySelector(".mprim")?.click(); e.stopPropagation(); });
    for (const i of body.querySelectorAll("input")) i.addEventListener("keydown", (e) => e.stopPropagation());
  }
  async function rekeyWith(oldCode) {
    const cur = K.personal()?.code || S.rekeyCode || "";
    try {
      const pk8 = await openWrap(S.rekey, oldCode);
      if (!cur) throw new Error("enter your current My room code in My room first");
      const w = await rewrap(pk8, S.nk, cur);
      const d = await api(Object.assign({ op: "recode", name: S.name, code: cur, newCode: cur }, w));
      pk8.fill(0);
      if (!d.ok) throw new Error(d.error || "refused");
      body.dataset.view = "";
      await unlock(cur, false);
    } catch (e) { S.why = "That code does not open your key" + (e?.message && !/operation/i.test(e.message) ? " (" + e.message + ")" : "") + "."; body.dataset.view = ""; paint(); }
  }

  // ---- settings: change code, notifications, forget this device -------------------------------------------------------------
  function paintSettings(list) {
    const box = document.createElement("div");
    box.className = "msettings";
    box.innerHTML = '<div class="mshead"><button type="button" class="mback" title="Back">' + K.icon("sbChev") + '</button><span>Messages settings</span></div>'
      + '<p class="mhint">You are <b></b>. Any device with your name and My room code reads your messages (90 days).</p>'
      + '<h4>Change My room code</h4><input class="mo" type="password" autocomplete="current-password" placeholder="Current code">'
      + '<input class="mn1" type="password" autocomplete="new-password" placeholder="New code (at least ' + S.codeMin + ')"><input class="mn2" type="password" autocomplete="new-password" placeholder="New code again">'
      + '<button type="button" class="mprim" data-a="recode">Change code</button><p class="merr"></p>'
      // 0.21.91 (Kenton: "this should be a toggle and not a checkbox"): the house switch, like People's Online only
      + '<h4>On this device</h4><label class="mchk"><span class="switch sm"><input type="checkbox" class="mnotif"><i></i></span><span>Desktop notifications while KASTR is minimised</span></label>'
      + '<button type="button" class="mghost" data-a="forget">Forget messages on this device</button>';
    box.querySelector("b").textContent = S.name;
    const say = (m) => { box.querySelector(".merr").textContent = m; };
    const nb = box.querySelector(".mnotif");
    nb.checked = "Notification" in window && Notification.permission === "granted" && localStorage.getItem("kastr.msg.notifOff") !== "1";
    nb.disabled = !("Notification" in window) || Notification.permission === "denied";
    nb.addEventListener("change", async () => {
      if (nb.checked && Notification.permission !== "granted") { const p = await Notification.requestPermission().catch(() => "denied"); nb.checked = p === "granted"; }
      try { localStorage.setItem("kastr.msg.notifOff", nb.checked ? "0" : "1"); } catch {}
    });
    for (const i of box.querySelectorAll("input")) i.addEventListener("keydown", (e) => e.stopPropagation());
    box.querySelector(".mback").addEventListener("click", (e) => { e.stopPropagation(); S.settings = false; paintList(); });
    box.querySelector('[data-a="recode"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      const o = box.querySelector(".mo").value, n1 = box.querySelector(".mn1").value, n2 = box.querySelector(".mn2").value;
      if (n1.length < S.codeMin) return say("At least " + S.codeMin + " characters.");
      if (n1 !== n2) return say("The two new codes do not match.");
      say("Changing…");
      const u = await api({ op: "unlock", name: S.name, code: o });
      if (!u.ok) return say(u.wrong ? "The current code is wrong." : (u.error || "Refused."));
      try {
        const pk8 = await openWrap(u.person, o);
        const w = await rewrap(pk8, S.nk, n1);
        pk8.fill(0);
        const d = await api(Object.assign({ op: "recode", name: S.name, code: o, newCode: n1 }, w));
        if (!d.ok) return say(d.error || "Refused.");
        K.savePersonalCode?.(n1);
        say("Done — My room and your messages now use the new code.");
        for (const i of box.querySelectorAll("input[type=password]")) i.value = "";
      } catch (err) { say("Could not change it: " + (err?.message || err)); }
    });
    box.querySelector('[data-a="forget"]').addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!(await K.confirm({ title: "Forget messages here", message: "Remove your messages key and history from this device?", detail: "Nothing is lost on the hub: enter your My room code again to read them here.", ok: "Forget", danger: true }))) return;
      await idbDel("ids", by()).catch(() => {});
      for (const r of [...S.recs.values()]) if (r.by === by()) idbDel("msgs", r.k).catch(() => {});
      await idbDel("meta", "cur|" + by()).catch(() => {});
      S.recs.clear(); S.id = null; S.settings = false; S.cur = 0;
      setState("needcode");
    });
    list.replaceChildren(box);
  }

  // ---- the people picker (New message / New group / Add people) ----------------------------------------------------------
  async function loadPeople() {
    const rows = await K.people().catch(() => []);
    S.people = rows;
    S.peopleAt = Date.now();
    const names = rows.map((r) => r.name).filter(Boolean).slice(0, 300);
    if (names.length) await keysFor(names).catch(() => {});
    if (S.picker) paintList();
  }
  function openPicker(mode, gid) {
    S.picker = { mode, gid: gid || "", sel: new Set(), q: "", name: "" };
    S.settings = false;
    S.view = "list";
    if (!wide) S.open = mode === "add" ? S.open : "";
    paint();
    loadPeople();
  }
  function paintPicker(list) {
    const pk = S.picker;
    const box = document.createElement("div");
    box.className = "mpicker";
    const title = pk.mode === "add" ? "Add people to “" + (S.groups.get(pk.gid)?.name || "the group") + "”" : pk.mode === "group" ? "New group" : "New message";
    box.innerHTML = '<div class="mshead"><button type="button" class="mback" title="Back">' + K.icon("sbChev") + '</button><span></span></div>'
      + (pk.mode === "new" ? '<button type="button" class="mghost mgrp">' + K.icon("people") + ' New group</button>' : "")
      + (pk.mode === "group" ? '<input class="mgname" maxlength="40" placeholder="Group name">' : "")
      + '<label class="msearch"><input type="search" class="mpq" placeholder="Search people" autocomplete="off" spellcheck="false"></label><div class="mppl"></div>'
      + (pk.mode !== "new" ? '<button type="button" class="mprim mgo" disabled></button>' : "") + '<p class="merr"></p>';
    box.querySelector(".mshead span").textContent = title;
    const q = box.querySelector(".mpq"); q.value = pk.q;
    const nameIn = box.querySelector(".mgname"); if (nameIn) nameIn.value = pk.name;
    const g = pk.gid ? S.groups.get(pk.gid) : null;
    const paintRows = () => {
      const f = q.value.trim().toLowerCase();
      const seen = new Set();
      const rows = [];
      for (const p of S.people) {
        const k = nameKey(p.name);
        if (!k || k === S.nk || seen.has(k)) continue;
        if (g && (g.members || []).includes(k)) continue;
        seen.add(k);
        if (f && !p.name.toLowerCase().includes(f)) continue;
        rows.push(p);
      }
      const els = rows.map((p) => {
        const k = nameKey(p.name), has = !!S.keys.get(k)?.row;
        const row = document.createElement("div");
        row.className = "mprow" + (has ? "" : " nokey") + (pk.sel.has(k) ? " sel" : "");
        row.append(avatar(p.name, k, true));
        const t = document.createElement("div"); t.className = "mmid";
        t.innerHTML = '<div class="mn"></div><div class="mprev"></div>';
        t.querySelector(".mn").textContent = p.name;
        t.querySelector(".mprev").textContent = !has ? "Hasn’t set up messages yet" : p.online ? "Online" : p.at ? "Last seen " + fmtTime(p.at) : "";
        row.appendChild(t);
        if (pk.mode !== "new") { const c = document.createElement("span"); c.className = "mtick"; c.textContent = pk.sel.has(k) ? "✓" : ""; row.appendChild(c); }
        row.title = has ? p.name : p.name + " hasn’t set up messages yet (they need a My room and to open Messages once)";
        row.addEventListener("click", (e) => {
          e.stopPropagation();
          if (!has) return;
          if (pk.mode === "new") { S.picker = null; openConv("p:" + k); return; }
          if (pk.sel.has(k)) pk.sel.delete(k); else pk.sel.add(k);
          paintRows(); goPaint();
        });
        return row;
      });
      if (!els.length) { const e = document.createElement("div"); e.className = "mempty"; e.textContent = S.peopleAt ? "Nobody to show." : "Loading people…"; els.push(e); }
      box.querySelector(".mppl").replaceChildren(...els);
    };
    const go = box.querySelector(".mgo");
    const goPaint = () => { if (!go) return; go.disabled = !pk.sel.size || (pk.mode === "group" && !(nameIn.value.trim())); go.textContent = pk.mode === "add" ? "Add " + pk.sel.size : "Create group (" + (pk.sel.size + 1) + " people)"; };
    q.addEventListener("input", () => { pk.q = q.value; paintRows(); });
    q.addEventListener("keydown", (e) => e.stopPropagation());
    if (nameIn) { nameIn.addEventListener("input", () => { pk.name = nameIn.value; goPaint(); }); nameIn.addEventListener("keydown", (e) => e.stopPropagation()); }
    box.querySelector(".mback").addEventListener("click", (e) => { e.stopPropagation(); S.picker = null; paint(); });
    box.querySelector(".mgrp")?.addEventListener("click", (e) => { e.stopPropagation(); pk.mode = "group"; paintList(); });
    if (go) go.addEventListener("click", async (e) => {
      e.stopPropagation();
      go.disabled = true;
      const names = [...pk.sel].map((k) => S.people.find((p) => nameKey(p.name) === k)?.name || k);
      const d = pk.mode === "add" ? await api({ op: "gadd", as: S.name, gid: pk.gid, members: names })
        : await api({ op: "gcreate", as: S.name, name: nameIn.value.trim(), members: names });
      if (!d.ok) { box.querySelector(".merr").textContent = d.error || "Refused."; go.disabled = false; return; }
      if (d.group) S.groups.set(d.group.gid, d.group);
      S.keys.clear();
      const gid = d.gid || pk.gid;
      S.picker = null;
      await pull();
      openConv("g:" + gid);
    });
    list.replaceChildren(box);
    paintRows(); goPaint();
  }

  // ---- one conversation ------------------------------------------------------------------------------------------------------
  function openConv(conv) {
    if (!conv) return;
    K.openPanel();
    S.open = conv; S.view = "conv"; S.picker = null; S.settings = false;
    body.dataset.view = "";
    paint();
    markRead(conv);
    ticks();
    setTimeout(() => body.querySelector(".mcin")?.focus(), 60);
  }
  const blobUrls = new Map();
  async function fileUrl(f) {
    if (f.local) return f.local;
    if (blobUrls.has(f.fid)) return blobUrls.get(f.fid);
    const p = (async () => {
      const kept = await idbGet("blobs", f.fid).catch(() => null);
      let blob = kept?.blob;
      if (!blob) {
        const ct = await fileDown(f.fid);
        const raw = new Uint8Array(await subtle.decrypt({ name: "AES-GCM", iv: unb64(f.iv) }, await aesKey(unb64(f.k), ["decrypt"]), ct));
        blob = new Blob([raw], { type: f.type || "application/octet-stream" });
        if (raw.length <= 8 * 1024 * 1024) idbPut("blobs", { fid: f.fid, by: by(), at: Date.now(), blob }).catch(() => {});
      }
      return URL.createObjectURL(blob);
    })();
    blobUrls.set(f.fid, p);
    try { return await p; } catch (e) { blobUrls.delete(f.fid); throw e; }
  }
  function paintConv() {
    const pane = body.querySelector(".mconvpane");
    if (!pane) return;
    const conv = S.open;
    if (!conv) { pane.innerHTML = '<div class="mempty mbig">' + K.icon("msg") + "<p>Pick a conversation, or press New.</p></div>"; pane.dataset.conv = ""; return; }
    const g = conv.startsWith("g:") ? S.groups.get(conv.slice(2)) : null;
    const nk = conv.startsWith("p:") ? conv.slice(2) : "";
    const keyRow = nk ? S.keys.get(nk)?.row : null;
    if (pane.dataset.conv !== conv) {
      pane.dataset.conv = conv;
      pane.innerHTML = '<div class="mchead"><button type="button" class="mback" title="All conversations">' + K.icon("sbChev") + '</button><div class="mctitle"><div class="mn"></div><div class="mprev"></div></div><button type="button" class="mcmenu" title="Group options" hidden>' + K.icon("more") + "</button></div>"
        + '<div class="mlog" aria-live="polite"></div><div class="mnokey" hidden></div><div class="matt" hidden></div>'
        + '<div class="mcomp"><button type="button" class="mattach" title="Attach a picture or file (up to 25 MB, end-to-end encrypted)">' + K.icon("clip") + '</button>'
        + '<textarea class="mcin" rows="1" placeholder="Write a message" title="Enter sends, Shift+Enter starts a new line"></textarea><button type="button" class="msend" title="Send">' + K.icon("send") + "</button></div>"
        + '<input type="file" class="mfilein" multiple hidden>';
      const ta = pane.querySelector(".mcin"), fi = pane.querySelector(".mfilein");
      pane.__files = [];
      const sendNow = () => {
        const t = ta.value, fs = pane.__files.slice();
        if (!t.trim() && !fs.length) return;
        ta.value = ""; pane.__files = []; paintAtt(pane); grow(ta);
        send(conv, t, fs);
      };
      ta.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendNow(); } });
      ta.addEventListener("input", () => grow(ta));
      ta.addEventListener("paste", (e) => {
        const fs = [...(e.clipboardData?.files || [])];
        if (!fs.length) return;
        e.preventDefault();
        addFiles(pane, fs.map((f, i) => (f.name && f.name !== "image.png" ? f : new File([f], "pasted-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + (i ? "-" + i : "") + "." + ((f.type.split("/")[1] || "png").replace("jpeg", "jpg")), { type: f.type }))));
      });
      pane.addEventListener("dragover", (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { e.preventDefault(); pane.classList.add("mdrag"); } });
      pane.addEventListener("dragleave", () => pane.classList.remove("mdrag"));
      pane.addEventListener("drop", (e) => { pane.classList.remove("mdrag"); const fs = [...(e.dataTransfer?.files || [])]; if (fs.length) { e.preventDefault(); addFiles(pane, fs); } });
      pane.querySelector(".msend").addEventListener("click", (e) => { e.stopPropagation(); sendNow(); });
      pane.querySelector(".mattach").addEventListener("click", (e) => { e.stopPropagation(); fi.click(); });
      fi.addEventListener("change", () => { addFiles(pane, [...fi.files]); fi.value = ""; });
      pane.querySelector(".mback").addEventListener("click", (e) => { e.stopPropagation(); S.view = "list"; if (!wide) S.open = ""; paint(); });
      pane.querySelector(".mcmenu").addEventListener("click", (e) => { e.stopPropagation(); groupMenu(e.currentTarget); });
    }
    pane.querySelector(".mctitle .mn").textContent = convTitle(conv);
    pane.querySelector(".mctitle .mprev").textContent = g ? (g.members || []).map((m) => (m === S.nk ? "You" : (g.names || {})[m] || m)).join(", ")
      : keyRow ? (keyRow.devices > 1 ? "Messages reach " + keyRow.devices + " of their devices" : "End-to-end encrypted") : "";
    pane.querySelector(".mcmenu").hidden = !g;
    const nokey = pane.querySelector(".mnokey");
    const cant = !!nk && S.keys.has(nk) && !keyRow;
    nokey.hidden = !cant;
    nokey.textContent = cant ? convTitle(conv) + " hasn’t set up messages yet — they can once they have a My room and open Messages." : "";
    pane.querySelector(".mcomp").classList.toggle("off", cant);
    if (nk && !S.keys.has(nk)) keysFor([nk]).then(() => paintConv()).catch(() => {});
    // the log
    const log = pane.querySelector(".mlog");
    const recs = [...S.recs.values()].filter((r) => r.by === by() && convOf(r) === conv).sort((a, b) => (a.seq || 1e15) - (b.seq || 1e15) || a.at - b.at);
    const read = Number(S.reads[conv]) || 0;
    const tk = S.ticks[conv] || null;
    const sig = JSON.stringify([recs.map((r) => [r.k, r.seq, !!r.sending, !!r.waiting, r.err || ""]), read, tk]);
    if (log.__sig === sig) return;
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.__sig = sig;
    const els = [];
    let day = "", prev = null, newMark = false;
    for (const r of recs) {
      const d = fmtDay(r.at);
      if (d !== day) { const x = document.createElement("div"); x.className = "mday"; x.textContent = d; els.push(x); day = d; prev = null; }
      if (!newMark && !r.mine && r.seq && r.seq > (log.__readAtOpen ?? read) && r.kind === "msg") { const x = document.createElement("div"); x.className = "mnewmark"; x.textContent = "New"; els.push(x); newMark = true; }
      if (r.kind === "sys") { const x = document.createElement("div"); x.className = "msys"; x.textContent = sysText(r); els.push(x); prev = null; continue; }
      const cont = prev && prev.from === r.from && r.at - prev.at < 300;
      const b = document.createElement("div");
      b.className = "mb" + (r.mine ? " mine" : "") + (cont ? " cont" : "");
      if (g && !r.mine && !cont) { const w = document.createElement("div"); w.className = "mwho"; w.textContent = r.fromName; w.style.setProperty("--pc", K.color(r.from)); b.appendChild(w); }
      const bub = document.createElement("div"); bub.className = "mbub";
      if (r.locked) { bub.classList.add("mlock"); bub.textContent = "Sent before this key was made — it cannot be opened here."; }
      else if (r.bad) { bub.classList.add("mlock"); bub.textContent = "This message could not be opened."; }
      else {
        for (const f of r.files || []) bub.appendChild(fileEl(f));
        if (r.text) { const t = document.createElement("div"); t.className = "mtxt"; t.textContent = r.text; linkify(t); bub.appendChild(t); }
      }
      const meta = document.createElement("div"); meta.className = "mmeta";
      meta.textContent = new Date(r.at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      if (r.mine) {
        const s = document.createElement("span"); s.className = "mst";
        if (r.err) { s.textContent = " ⚠ Not sent: " + r.err; s.classList.add("bad"); }
        else if (r.waiting) s.textContent = " ⏲ Waiting for the hub";
        else if (r.sending || !r.seq) s.textContent = " …";
        else if (tk && tk.r >= r.seq) { s.textContent = " ✓✓"; s.classList.add("read"); s.title = "Read"; }
        else if (tk && tk.d >= r.seq) { s.textContent = " ✓✓"; s.title = "Delivered"; }
        else { s.textContent = " ✓"; s.title = "Sent — waiting on the hub until they are online"; }
        meta.appendChild(s);
      }
      bub.appendChild(meta);
      b.appendChild(bub);
      els.push(b);
      prev = r;
    }
    if (!recs.length) { const e = document.createElement("div"); e.className = "mempty"; e.textContent = g ? "Say hello to the group." : "No messages yet. They are end-to-end encrypted: only you and " + convTitle(conv) + " can read them."; els.push(e); }
    log.replaceChildren(...els);
    if (atBottom || !log.__opened) { log.scrollTop = log.scrollHeight; log.__opened = true; log.__readAtOpen = read; }
    if (panelShown() && document.visibilityState === "visible") markRead(conv);
  }
  function linkify(el) {
    const t = el.textContent;
    if (!/https?:\/\//.test(t)) return;
    el.textContent = "";
    for (const part of t.split(/(https?:\/\/[^\s<>"']+)/g)) {
      if (/^https?:\/\//.test(part)) { const a = document.createElement("a"); a.href = part; a.textContent = part; a.target = "_blank"; a.rel = "noopener noreferrer"; el.appendChild(a); }
      else el.appendChild(document.createTextNode(part));
    }
  }
  function fileEl(f) {
    const img = IMG_TYPES.test(f.type || "");
    const w = document.createElement("div");
    w.className = img ? "mimg" : "mfile";
    if (img) {
      const i = document.createElement("img"); i.alt = f.name || "picture"; i.loading = "lazy";
      w.appendChild(i);
      w.classList.add("loading");
      fileUrl(f).then((u) => { i.src = u; w.classList.remove("loading"); }).catch((e) => { w.classList.remove("loading"); w.classList.add("mfail"); w.textContent = "Picture unavailable (" + (e?.message || e) + ")"; });
      i.addEventListener("click", (e) => { e.stopPropagation(); if (i.src) window.open(i.src, "_blank", "noopener"); });
    } else {
      w.innerHTML = K.icon("files") + '<span class="mfn"></span><span class="mfs"></span>';
      w.querySelector(".mfn").textContent = f.name || "file";
      w.querySelector(".mfs").textContent = f.size ? fmtSize(f.size) : "";
      w.title = "Download (decrypted on this device)";
      w.addEventListener("click", async (e) => {
        e.stopPropagation();
        try { const u = await fileUrl(f); const a = document.createElement("a"); a.href = u; a.download = f.name || "file"; document.body.appendChild(a); a.click(); a.remove(); }
        catch (err) { toast("Could not open the file: " + (err?.message || err), 5000, "warn"); }
      });
    }
    return w;
  }
  function addFiles(pane, fs) {
    for (const f of fs) {
      if (f.size > FILE_MAX) { toast("“" + f.name + "” is over 25 MB", 5000, "warn"); continue; }
      if (pane.__files.length < 10) pane.__files.push(f);
    }
    paintAtt(pane);
    pane.querySelector(".mcin")?.focus();
  }
  function paintAtt(pane) {
    const box = pane.querySelector(".matt");
    box.hidden = !pane.__files.length;
    box.replaceChildren(...pane.__files.map((f, i) => {
      const c = document.createElement("div"); c.className = "mca";
      if (IMG_TYPES.test(f.type)) { const im = document.createElement("img"); im.src = URL.createObjectURL(f); c.appendChild(im); }
      const n = document.createElement("span"); n.textContent = f.name + " · " + fmtSize(f.size); c.appendChild(n);
      const x = document.createElement("button"); x.type = "button"; x.textContent = "✕"; x.title = "Remove";
      x.addEventListener("click", (e) => { e.stopPropagation(); pane.__files.splice(i, 1); paintAtt(pane); });
      c.appendChild(x);
      return c;
    }));
  }
  const grow = (ta) => { ta.style.height = "auto"; ta.style.height = Math.min(120, ta.scrollHeight) + "px"; };
  async function groupMenu(anchor) {
    const g = S.groups.get(S.open.slice(2));
    if (!g) return;
    const mine = g.creator === S.nk;
    const items = [{ value: "add", label: "Add people…" }];
    if (mine) items.push({ value: "rename", label: "Rename…" });
    if (mine) for (const m of g.members || []) if (m !== S.nk) items.push({ value: "rm|" + m, label: "Remove " + ((g.names || {})[m] || m) });
    items.push({ value: "leave", label: "Leave the group" });
    if (mine) items.push({ value: "delete", label: "Delete the group" });
    K.menu(anchor, items, async (v) => {
      let d = null;
      if (v === "add") return openPicker("add", g.gid);
      if (v === "rename") {
        const n = await K.confirm({ title: "Rename the group", message: "A new name for “" + g.name + "”", ok: "Rename", input: { value: g.name, placeholder: "Group name" },
          check: (s) => (String(s || "").trim() ? "" : "Type a name.") });
        if (!n) return;
        d = await api({ op: "grename", as: S.name, gid: g.gid, name: String(n).trim() });
      } else if (v.startsWith("rm|")) {
        const m = v.slice(3);
        if (!(await K.confirm({ title: "Remove from the group", message: "Remove " + ((g.names || {})[m] || m) + " from “" + g.name + "”?", detail: "They keep what they already received; they get nothing new.", ok: "Remove", danger: true }))) return;
        d = await api({ op: "gremove", as: S.name, gid: g.gid, member: m });
      } else if (v === "leave") {
        if (!(await K.confirm({ title: "Leave the group", message: "Leave “" + g.name + "”?", detail: "You keep what you already received on your devices.", ok: "Leave", danger: true }))) return;
        d = await api({ op: "gleave", as: S.name, gid: g.gid });
        if (d.ok) { S.open = ""; S.view = "list"; }
      } else if (v === "delete") {
        if (!(await K.confirm({ title: "Delete the group", message: "Delete “" + g.name + "” for everyone?", detail: "Its messages leave the hub at once (devices keep their own copies).", ok: "Delete", danger: true }))) return;
        d = await api({ op: "gdelete", as: S.name, gid: g.gid });
        if (d.ok) { S.open = ""; S.view = "list"; }
      }
      if (d && !d.ok) toast("Could not do that: " + (d.error || d.status), 5000, "warn");
      if (d?.group) S.groups.set(d.group.gid, d.group);
      S.keys.clear();
      pull();
    });
  }

  // ---- admins: a person's messaging devices (People menu) ---------------------------------------------------------------
  async function adminDevices(name, anchor) {
    const d = await api({ op: "devices", name });
    if (!d.ok) { toast("Messaging devices: " + (d.error || d.status), 5000, "warn"); return; }
    if (!d.has) { await K.confirm({ title: "Messaging devices", message: name + " hasn’t set up messages.", ok: "OK", noCancel: true }); return; }
    const items = [{ cap: name + "’s messaging devices" }];
    for (const r of d.devices) items.push({ value: (r.blocked ? "allow|" : "rm|") + r.host, label: (r.blocked ? "Allow again: " : "Remove: ") + r.host + (r.at ? " (" + fmtTime(r.at) + ")" : ""),
      tip: r.blocked ? "Removed by an admin — it may unlock again with name + code" : "Stops this device reading new messages; it cannot unlock again until allowed" });
    K.menu(anchor || K.btn(), items, async (v) => {
      const [a, host] = [v.split("|")[0], v.split("|").slice(1).join("|")];
      if (a === "rm" && !(await K.confirm({ title: "Remove a messaging device", message: "Remove “" + host + "” from " + name + "’s messages?",
        detail: "It reads nothing new and cannot unlock again until an admin allows it. " + name + "’s other devices are told.", ok: "Remove", danger: true }))) return;
      const o = await api({ op: a === "rm" ? "devremove" : "devallow", name, host });
      toast(o.ok ? (a === "rm" ? "Removed " + host + " from " + name + "’s messages" : host + " may unlock " + name + "’s messages again") : "Refused: " + (o.error || o.status), 5000, o.ok ? "event" : "warn");
    });
  }

  // ---- 0.21.91 (Kenton: when someone who already has a My room changes their name, MOVE EVERYTHING to the new name) ----------
  // POST /api/msg {op: "rename", name, newName, code, wrapped, iv, salt, iter}: the code proves it; this device opens the hub's
  // wrap of the messages key with the code (its AES-GCM additional data is "kastr-msg-id-v1|<OLD name key>") and wraps the
  // same key again with the same code under "kastr-msg-id-v1|<NEW name key>" (a fresh salt and iv) -- the key itself and its
  // id do not change, so every message still opens. The hub moves My room (same room), the messages store, the photo and
  // keeps the old name pointing at the new one for 90 days. Here: My room's record on this device, the profile name, and my
  // copy of the history (IndexedDB) move to the new name; other devices of mine hear it on their next status / pull.
  async function renameMe(newName, code) {
    newName = nameDisp(newName).slice(0, 40);
    const oldName = S.name, oldNk = S.nk, newNk = nameKey(newName);
    if (!newNk) return { ok: false, error: "Enter the new name." };
    if (newName === oldName) return { ok: true, same: true, name: newName };
    const u = await api({ op: "unlock", name: oldName, code });
    if (!u.ok) return { ok: false, wrong: !!u.wrong, error: u.wrong ? "That isn\u2019t your My room code." : (u.error || "Refused.") };
    const body = { op: "rename", name: oldName, newName, code };
    if (u.person) {
      let pk8 = null;
      try { pk8 = await openWrap(u.person, code); } catch { return { ok: false, error: "Your messages key does not open with that code." }; }
      Object.assign(body, await rewrap(pk8, newNk, code));
      pk8.fill(0);
    }
    const d = await api(body);
    if (!d.ok) return { ok: false, taken: !!d.taken, wrong: !!d.wrong, error: d.error || "Refused." };
    T("renamed", { from: oldNk, to: d.key || newNk });
    await selfRenamed(oldNk, d.key || newNk, d.name || newName, code);
    return { ok: true, name: d.name || newName };
  }
  let selfMoving = false;
  async function selfRenamed(oldNk, newNk, newName, code) {
    if (selfMoving) return;
    selfMoving = true;
    try {
      const p = K.personal();
      if (p && nameKey(p.name) === oldNk) K.savePersonalName?.(newName);       // My room's record on this device (same room)
      else if (!p && code) await K.roomOpen?.(newName, code);                   // (a device that had none: My room on its rail now)
      if (nameKey(K.me()) === oldNk) K.setProfileName?.(newName);              // the name this device shows everyone
      if (S.fleet) await migrateLocal(oldNk, newNk, newName).catch((e) => T("migrate-fail", { e: String(e?.message || e) }));
      S.recs.clear(); S.groups.clear(); S.reads = {}; S.keys.clear(); S.cur = 0; S.open = S.open === "p:" + oldNk ? "" : S.open;
      S.id = null; S.nk = ""; S.state = "init";
      toast("You are now \u201c" + newName + "\u201d for My room and messages", 6000, "event");
    } finally { selfMoving = false; }
    setTimeout(() => init(true), 50);
  }
  async function migrateLocal(oldNk, newNk, newName) {
    const ob = S.fleet + "|" + oldNk, nb = S.fleet + "|" + newNk;
    const id = await idbGet("ids", ob).catch(() => null);
    if (id) { await idbPut("ids", Object.assign({}, id, { k: nb, nk: newNk, name: newName })); await idbDel("ids", ob); }
    for (const m of ["cur", "reads", "groups"]) {
      const v = await idbGet("meta", m + "|" + ob).catch(() => null);
      if (!v) continue;
      let val = v.v;
      if (m === "reads" && val) { const r = {}; for (const [k, x] of Object.entries(val)) r[k === "p:" + oldNk ? "p:" + newNk : k] = x; val = r; }
      await idbPut("meta", { k: m + "|" + nb, v: val });
      await idbDel("meta", m + "|" + ob);
    }
    for (const r of await idbAll("msgs", "by", ob).catch(() => [])) {
      const n = Object.assign({}, r, { by: nb, k: nb + "|" + r.seq });
      if (n.from === oldNk) { n.from = newNk; n.fromName = newName; }
      if (n.to === oldNk) { n.to = newNk; n.toName = newName; }
      n.mine = n.from === newNk;
      await idbPut("msgs", n);
      await idbDel("msgs", r.k);
    }
    for (const o of await idbAll("outbox").catch(() => [])) if (o.by === ob) await idbPut("outbox", Object.assign({}, o, { by: nb }));
  }
  const renamesDone = new Set();
  function applyRenames(list) {
    for (const r of list) {
      const o = String(r?.from || ""), n = String(r?.to || "");
      if (!o || !n || o === n || o === S.nk || renamesDone.has(o + ">" + n)) continue;
      renamesDone.add(o + ">" + n);
      renameMap.set(o, { key: n, name: r.name || n });
      let moved = 0;
      for (const rec of S.recs.values()) {
        let c = false;
        if (rec.from === o) { rec.from = n; rec.fromName = r.name || n; c = true; }
        if (rec.to === o) { rec.to = n; rec.toName = r.name || n; c = true; }
        if (c) { moved++; if (rec.seq) idbPut("msgs", rec).catch(() => {}); }
      }
      if (S.reads["p:" + o] !== undefined) {
        S.reads["p:" + n] = Math.max(Number(S.reads["p:" + n]) || 0, Number(S.reads["p:" + o]) || 0);
        delete S.reads["p:" + o];
        idbPut("meta", { k: "reads|" + by(), v: S.reads }).catch(() => {});
      }
      if (S.open === "p:" + o) S.open = "p:" + n;
      if (S.ticks["p:" + o]) { S.ticks["p:" + n] = S.ticks["p:" + o]; delete S.ticks["p:" + o]; }
      S.keys.delete(o);
      if (moved) T("rename-applied", { from: o, to: n, moved });
    }
  }
  // The Profile saved a new name: unlocked -> "Rename your My room and messages to <new>?" (or keep the old name for My room);
  // the card up for my own My room (short code / earlier code) -> the card's rename, with the new name filled in.
  async function nameChanged(before, after) {
    after = nameDisp(after).slice(0, 40);
    if (!K.allowed() || !nameKey(after) || nameKey(after) === S.nk || !S.nk) return;
    if (S.state === "ready") {
      const old = S.name;
      const v = await K.confirm({ title: "Rename your My room and messages?", message: "Rename your My room and messages to \u201c" + after + "\u201d?",
        detail: "Your My room, your messages (with their history) and your photo move to the new name, and everyone sees it. The old name keeps pointing to you for 90 days. Confirm with your My room code.",
        ok: "Rename", cancel: "Keep using " + old + " for My room", input: { masked: true, placeholder: "My room code" },
        check: async (code) => { if (!code) return "Enter your My room code."; const r = await renameMe(after, code); return r.ok ? "" : r.error; } });
      T("profile-rename", { done: v !== false });
      return;
    }
    if (S.state === "short" || S.state === "rekey") { gateSub = "rename"; gateSubName = after; gateKey = ""; setTimeout(gateTick, 0); return; }
    setTimeout(() => init(true), 50);
  }

  // ---- 0.21.89 (Kenton: "On launch, have people set their 'my room' and messages up if they haven't already" -- REQUIRED) ----
  // One card over the whole page once a PERSON has joined a room with an access code (never a camera box, a relay-only machine,
  // a viewer-only display, the Lobby, an invite-link or My room guest -- K.allowed() + K.person()) and Messages need a step
  // here: no My room yet (make it: name + code twice), a My room under this name but not unlocked here (it is them on another
  // device -- or someone else's name: enter its code or change the name), a code shorter than 8 (pick a longer one), a key
  // locked with an earlier code. No "Not now". It waits for the join gate, a question, the Profile, My room's own dialog. It
  // NEVER blocks when Messages cannot be reached (the hub away, a relay older than 0.21.88, no WebCrypto here, an admin removed
  // this device): a quiet line says so, and the card comes when the hub answers again (the 30 s check). The code is never kept
  // anywhere new -- My room remembers it on this device exactly as the My room dialog does (kastr.personal.<relay host>).
  const GATE_STATES = new Set(["noroom", "needcode", "short", "rekey"]);
  const QUIET = { down: "My room and messages will be set up when the hub is reachable",
                  error: "My room and messages will be set up when the hub is reachable",
                  old: "My room and messages will be set up when this relay runs KASTR 0.21.88 or later" };
  let gateEl = null, gateKey = "", gateBusy = false, gateShownAt = 0;
  let gateSub = null, gateSubName = "";   // 0.21.91: "rename" (My room is theirs: everything moves) | "choice" (the unlock card: mine, or another name)
  const gateOn = () => !!gateEl && !gateEl.hidden;
  function gateWanted() {
    if (!K.allowed() || !(K.person?.() ?? false)) return false;
    return GATE_STATES.has(S.state) || (gateOn() && (S.state === "unlocking" || S.state === "init" || gateBusy || !!gateSub));
  }
  function gateBar() {
    let bar = document.getElementById("kSetupBar");
    const why = K.allowed() && (K.person?.() ?? false) ? QUIET[S.state] || "" : "";
    if (!why) { if (bar) bar.hidden = true; return; }
    if (!bar) { bar = document.createElement("div"); bar.id = "kSetupBar"; bar.setAttribute("role", "status"); document.body.appendChild(bar); }
    bar.textContent = why;
    bar.title = why + (S.why ? " (" + S.why + ")" : "");
    bar.hidden = gateOn();
  }
  function gateTick() {
    gateBar();
    if (!gateWanted()) { if (gateOn()) gateClose(); return; }
    if (!gateOn() && K.busyUI?.()) return;   // the join gate, a question, the Profile, My room's dialog first
    gatePaint();
  }
  function gateClose() {
    if (!gateEl) return;
    gateEl.hidden = true; gateKey = "";
    T("gate-close", { st: S.state });
    if (S.state === "ready") toast("My room and messages are set up \u2014 My room is the first card in your rooms list", 6000, "event");
    gateBar();
  }
  function gateBuild() {
    const el = document.createElement("div");
    el.id = "kSetup"; el.hidden = true;
    el.setAttribute("role", "dialog"); el.setAttribute("aria-modal", "true"); el.setAttribute("aria-labelledby", "ksTitle");
    el.innerHTML = '<div class="popcard ksetup"><div class="body">'
      + '<div class="ksico">' + K.icon("msg") + '</div><h3 id="ksTitle"></h3><p class="kslead"></p>'
      + '<div class="ksname"><span class="lbl">Name</span><b class="ksn"></b><button type="button" class="kslink" data-a="name">Change name</button></div>'
      + '<label class="ksf" data-f="nn" hidden><span>New name</span><input type="text" class="ksnn" maxlength="40" autocomplete="name" spellcheck="false"></label>'
      + '<label class="ksf" data-f="old"><span>Current My room code</span><input type="password" class="kso" autocomplete="current-password"></label>'
      + '<label class="ksf" data-f="c1"><span class="ksc1l">My room code</span><input type="password" class="ksc1" autocomplete="new-password"></label>'
      + '<label class="ksf" data-f="c2"><span>The same code again</span><input type="password" class="ksc2" autocomplete="new-password"></label>'
      + '<p class="kshint"></p><p class="kserr" role="alert"></p>'
      + '<div class="ksbtns"><button type="button" class="mghost" data-a="back" hidden>Back</button><button type="button" class="mghost" data-a="other" hidden>Use a different name</button>'
      + '<button type="button" class="mghost" data-a="fresh" hidden>Start fresh</button><button type="button" class="mprim" data-a="go"></button></div>'
      + '<p class="ksforgot">Forgot your code? A fleet admin can reset your My room \u2014 your message history would be lost.</p>'
      + '<div class="ksmic" hidden><span>Your microphone is on</span><button type="button" class="mghost" data-a="mute">Mute</button></div>'
      + "</div></div>";
    el.addEventListener("click", (e) => e.stopPropagation());   // a click on the card never reaches the page (or closes a panel)
    el.addEventListener("keydown", (e) => {
      e.stopPropagation();   // the page's shortcuts stay quiet while it asks
      if (e.key === "Enter" && e.target?.tagName === "INPUT") { e.preventDefault(); gateGo(); }
      if (e.key === "Escape") e.preventDefault();   // required: Esc does not dismiss it
    });
    el.querySelector('[data-a="go"]').addEventListener("click", () => gateGo());
    el.querySelector('[data-a="fresh"]').addEventListener("click", () => gateFresh());
    el.querySelector('[data-a="mute"]').addEventListener("click", () => { try { K.mic?.().mute?.(); } catch {} setTimeout(gateMic, 300); });
    const toProfile = () => {
      el.hidden = true; gateKey = ""; gateSub = null;
      T("gate-name", {});
      K.profile?.(() => { S.state = "init"; setTimeout(() => init(true).then(gateTick), 50); });   // a new name: asked again from the start
    };
    el.querySelector('[data-a="name"]').addEventListener("click", () => {
      // 0.21.91: My room is theirs (a short code, an earlier code) -> rename it; the unlock card may be someone else's name ->
      // ask; a brand-new person -> the Profile, as before
      const st = S.state;
      if (st === "short" || st === "rekey") { gateSub = "rename"; gateSubName = ""; }
      else if (st === "needcode") gateSub = "choice";
      else return toProfile();
      gateKey = ""; T("gate-sub", { sub: gateSub }); gatePaint();
    });
    el.querySelector('[data-a="other"]').addEventListener("click", () => toProfile());
    el.querySelector('[data-a="back"]').addEventListener("click", () => { gateSub = null; gateKey = ""; gatePaint(); });
    document.body.appendChild(el);
    return el;
  }
  function gateMic() {
    if (!gateEl) return;
    const m = K.mic?.() || {};
    gateEl.querySelector(".ksmic").hidden = !m.live;
  }
  function gatePaint() {
    if (!gateEl) gateEl = gateBuild();
    const st = gateSub || (gateBusy || S.state === "unlocking" || S.state === "init" ? (gateEl.dataset.st || S.state) : S.state);
    const key = st + "|" + S.name;
    const q = (sel) => gateEl.querySelector(sel);
    const err = q(".kserr");
    if (gateKey !== key) {
      gateKey = key;
      gateEl.dataset.st = st;
      const min = S.codeMin || 8;
      const t = {
        noroom: ["Set up My room and messages", "KASTR keeps your own room (My room) and your private messages under your name and a code only you know. Pick it once \u2014 the same name and code open both on any device.", "Set up"],
        needcode: ["Unlock your messages", "\u201c" + S.name + "\u201d already has a My room on this hub. If it\u2019s yours, enter your My room code to unlock your messages on this device. If it isn\u2019t you, change your name.", "Unlock"],
        short: ["Pick a longer My room code", "Pick a longer My room code to turn on messages. It becomes your My room code everywhere \u2014 your other devices ask for it once.", "Use this code"],
        rekey: ["Enter your earlier My room code", "Your messages key was locked with an earlier My room code (an admin may have reset it). Enter that earlier code to keep your history \u2014 or start fresh (older messages cannot be read again).", "Unlock"],
        rename: ["Rename My room and messages", "Your My room, your messages (with their history) and your photo move to the new name, and everyone sees it. The old name keeps pointing to you for 90 days. Confirm with your My room code.", "Rename"],
        choice: ["Change name", "Is \u201c" + S.name + "\u201d your own My room, set up on another device? Rename it \u2014 everything moves to the new name. If it isn\u2019t yours, use a different name.", "It\u2019s mine \u2014 rename it"],
      }[st] || ["Set up My room and messages", "", "Continue"];
      q("#ksTitle").textContent = t[0];
      q(".kslead").textContent = t[1];
      q('[data-a="go"]').textContent = t[2];
      q(".ksn").textContent = S.name || "\u2014";
      const needOld = st === "short" && !(S.pendingCode || K.personal()?.code);
      q('[data-f="old"]').hidden = !needOld;
      q('[data-f="nn"]').hidden = st !== "rename";
      q('[data-f="c1"]').hidden = st === "choice";
      q('[data-f="c2"]').hidden = !(st === "noroom" || st === "short");
      q('[data-a="name"]').hidden = st === "rename" || st === "choice";
      q('[data-a="back"]').hidden = !(st === "rename" || st === "choice");
      q('[data-a="other"]').hidden = st !== "choice";
      q(".ksc1l").textContent = st === "short" ? "New My room code" : st === "rekey" ? "Earlier My room code" : st === "rename" ? "Your My room code" : "My room code";
      q(".ksc1").autocomplete = st === "noroom" || st === "short" ? "new-password" : "current-password";
      q(".kshint").textContent = st === "noroom" || st === "short" ? "At least " + min + " characters \u2014 it opens My room and your messages on any device, so pick one only you know." : "";
      q(".kshint").hidden = !q(".kshint").textContent;
      q('[data-a="fresh"]').hidden = st !== "rekey";
      q(".ksforgot").hidden = st === "noroom";
      for (const i of gateEl.querySelectorAll("input")) { i.value = ""; i.classList.remove("bad"); }
      if (st === "rename") q(".ksnn").value = gateSubName || "";
      err.textContent = S.why && !["noroom", "rename", "choice"].includes(st) ? S.why : "";
      gateEl.hidden = false;
      gateShownAt = Date.now();
      T("gate-show", { st });
      const first = [...gateEl.querySelectorAll("label.ksf:not([hidden]) input")].find((i) => !i.value);
      setTimeout(() => { try { first?.focus(); } catch {} }, 30);
    }
    gateEl.hidden = false;
    q('[data-a="go"]').disabled = gateBusy;
    gateMic();
    gateBar();
  }
  function gateSay(msg, bad) {
    if (!gateEl) return;
    gateEl.querySelector(".kserr").textContent = msg || "";
    for (const i of gateEl.querySelectorAll("input")) i.classList.toggle("bad", !!bad && bad.includes(i.className.split(" ")[0]));
    const b = bad && gateEl.querySelector("input." + bad[0]);
    if (b) { try { b.focus(); b.select(); } catch {} }
  }
  async function gateGo() {
    if (!gateEl || gateBusy) return;
    const st = gateEl.dataset.st, min = S.codeMin || 8;
    const q = (sel) => gateEl.querySelector(sel);
    const c1 = q(".ksc1").value, c2 = q(".ksc2").value, old = q(".kso").value;
    if (st === "choice") { gateSub = "rename"; gateSubName = ""; gateKey = ""; gatePaint(); return; }   // 0.21.91
    if (st === "rename" && !nameKey(q(".ksnn").value)) return gateSay("Enter the new name.", ["ksnn"]);
    if (!c1) return gateSay("Enter " + (st === "short" ? "a new" : st === "rekey" ? "your earlier" : "your") + " My room code.", ["ksc1"]);
    if ((st === "noroom" || st === "short") && c1.length < min) return gateSay("Too short \u2014 a My room code has at least " + min + " characters.", ["ksc1"]);
    if ((st === "noroom" || st === "short") && c1 !== c2) return gateSay("The two codes don\u2019t match.", ["ksc2"]);
    if (st === "short" && !q('[data-f="old"]').hidden && !old) return gateSay("Enter your current My room code.", ["kso"]);
    gateBusy = true; gateSay(st === "noroom" ? "Setting up\u2026" : "Opening\u2026");
    q('[data-a="go"]').disabled = true;
    const t0 = Date.now();
    try {
      if (st === "noroom") {
        const d = await K.roomMake(S.name, c1);
        if (!d.ok) {
          if (d.wrong) { S.state = "needcode"; S.why = ""; gateKey = ""; gateBusy = false; gatePaint(); gateSay("\u201c" + S.name + "\u201d already has a My room with another code \u2014 enter its code if it\u2019s yours, or change your name.", ["ksc1"]); return; }
          gateSay(d.status === 429 || /too many/i.test(d.error || "") ? (d.error || "Too many attempts \u2014 wait a little.") : "My room could not be made: " + (d.error || "refused"));
          return;
        }
        const ok = await unlock(c1, false);
        if (!ok) { gateSay(S.why || "Messages could not be set up."); return; }
      } else if (st === "needcode") {
        const ok = await unlock(c1, false);
        if (!ok) {
          if (S.state === "short") return;   // their code works, but messages need a longer one: the next card
          gateSay(/Wrong/.test(S.why) ? "That isn\u2019t the My room code of \u201c" + S.name + "\u201d. If this name isn\u2019t yours, change your name." : (S.why || "Could not unlock."), ["ksc1"]);
          return;
        }
        if (!K.personal()) await K.roomOpen(S.name, c1);   // My room on this device's rail too (as the My room dialog would)
      } else if (st === "short") {
        const cur = S.pendingCode || K.personal()?.code || old;
        const ok = await unlock(cur, false, c1);
        if (!ok) { gateSay(S.state === "needcode" ? "The current code is wrong." : (S.why || "Could not change the code."), ["kso"]); return; }
        if (!K.personal()) await K.roomOpen(S.name, c1);
      } else if (st === "rename") {   // 0.21.91: everything moves; then the card carries on under the new name
        const r = await renameMe(q(".ksnn").value, c1);
        if (!r.ok) { gateSay(r.error || "Could not rename.", r.wrong ? ["ksc1"] : ["ksnn"]); return; }
        gateSub = null; gateSubName = ""; gateKey = "";
      } else if (st === "rekey") {
        S.why = "";
        await rekeyWith(c1);
        if (S.state !== "ready") { gateSay(S.why || "That code does not open your key.", ["ksc1"]); return; }
      }
      T("gate-done", { st, ms: Date.now() - t0 });
    } catch (e) {
      gateSay("Something went wrong: " + (e?.message || e));
    } finally {
      gateBusy = false;
      if (gateEl) q('[data-a="go"]').disabled = false;
      setTimeout(gateTick, 0);
    }
  }
  async function gateFresh() {
    if (!(await K.confirm({ title: "Start fresh", message: "Make a new messages key for " + S.name + "?",
      detail: "Messages sent to you before cannot be read again on any device. Your other devices must unlock again.", ok: "Start fresh", danger: true }))) return;
    const code = K.personal()?.code || S.rekeyCode || "";
    if (!code) { gateSay("Enter your current My room code in My room first."); return; }
    gateBusy = true;
    try {
      const id = await makeIdentity(S.nk, code);
      const d = await api({ op: "setup", replace: true, name: S.name, code, pub: id.pub, wrapped: id.wrapped, iv: id.iv, salt: id.salt, iter: id.iter });
      if (!d.ok) { gateSay(d.error || "Refused."); return; }
      const rec = { k: by(), fleet: S.fleet, nk: S.nk, name: S.name, kid: id.kid, pub: id.pub, priv: id.priv, at: Date.now() };
      await idbPut("ids", rec);
      await ready(rec);
    } finally { gateBusy = false; setTimeout(gateTick, 0); }
  }
  setInterval(gateTick, 1000);
  window.addEventListener("kastr:auth", () => setTimeout(gateTick, 1500));

  // ---- wiring -----------------------------------------------------------------------------------------------------------------
  window.__msg = {
    opened: (quiet) => { body.dataset.view = ""; if (S.state === "off" || S.state === "error" || S.state === "down") init(true); else init(); paint(); pull(); if (!S.peopleAt || Date.now() - S.peopleAt > 60000) loadPeople(); if (S.open) { markRead(S.open); ticks(); } },
    closed: () => {},
    ping: (seq) => { seq = Number(seq) || 0; if (seq > S.lastPing) { S.lastPing = seq; if (S.state === "ready") pull(); else if (S.state === "blocked" || S.state === "needcode") init(true); } },
    auth: () => setTimeout(() => init(), 300),
    openWith: (name) => { if (!K.allowed()) { toast("Join a room (with an access code) to send messages", 4000, "info"); return; } init().then(() => openConv("p:" + nameKey(name))); },
    adminDevices,
    photos: () => { if (!panel.hidden && S.state === "ready") { paintList(); } },   // 0.21.90: the photo index moved
    unread: () => (S.state === "ready" ? totalUnread() : 0),
    // rig hooks
    state: () => ({ state: S.state, why: S.why, fleet: S.fleet, name: S.name, kid: S.kid, cur: S.cur, open: S.open, hubDown: S.hubDown, n: S.recs.size,
      convs: convs().map((c) => ({ conv: c.conv, title: c.title, unread: c.unread, last: preview(c.last) })), groups: [...S.groups.values()].map((g) => ({ gid: g.gid, name: g.name, members: g.members })) }),
    msgs: (conv) => [...S.recs.values()].filter((r) => !conv || convOf(r) === conv).sort((a, b) => (a.seq || 1e15) - (b.seq || 1e15))
      .map((r) => ({ seq: r.seq, from: r.fromName, mine: r.mine, text: r.text, files: (r.files || []).map((f) => ({ name: f.name, type: f.type, size: f.size })), sys: r.sys ? sysText(r) : "", locked: !!r.locked, bad: !!r.bad, waiting: !!r.waiting, err: r.err || "" })),
    send: (conv, text, files) => send(conv, text, files), pull, init, open: openConv, unlock: (code) => unlock(code, false), picker: openPicker, trace,
    fileUrl: (seq, i) => { const r = S.recs.get("seq:" + seq); return r && r.files?.[i] ? fileUrl(r.files[i]) : null; },
    people: () => S.people,
    keys: (names, force) => keysFor(names, force),
    nameChanged: (before, after) => nameChanged(before, after),   // 0.21.91: the Profile saved a new name
    rename: (newName, code) => renameMe(newName, code),           // 0.21.91 (rig)
    forgetRenames: () => { renameMap.clear(); renamesDone.clear(); S.keys.clear(); },   // 0.21.91 (rig: play an outdated device)
    gate: () => ({ shown: gateOn(), sub: gateSub || "", st: gateEl?.dataset.st || "", busy: gateBusy, wanted: gateWanted(), bar: (() => { const b = document.getElementById("kSetupBar"); return b && !b.hidden ? b.textContent : ""; })(),
      err: gateEl?.querySelector(".kserr")?.textContent || "", shownAt: gateShownAt }),   // 0.21.89 rig
  };
  setInterval(() => { if (S.state === "ready") { pull(); ticks(); } else if (K.allowed() && ["off", "down", "noroom"].includes(S.state)) init(); else paintBtn(); }, POLL_MS);
  setInterval(() => { if (panelShown() && S.open) ticks(); paintBtn(); }, 8000);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && panelShown() && S.open) markRead(S.open); });
  window.addEventListener("kastr:auth", () => setTimeout(() => init(), 400));
  window.addEventListener("kastr:personal", () => setTimeout(() => init(true), 200));
  setTimeout(() => init(), 1500);
  }
})();
