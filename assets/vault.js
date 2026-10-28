// KASTR 0.21.92 -- the codes this browser keeps are WRAPPED (Kenton: "fix the plain text passcodes").
//
// localStorage and sessionStorage sit on disk in the browser profile. Every key that holds a code or a token is
// kept there only as "kv1:<base64url(iv | AES-GCM ciphertext)>", under a NON-EXTRACTABLE AES-GCM key that lives in
// this origin's IndexedDB ("kastr-vault") -- the pattern the Messages identity key uses. The page itself still
// reads and writes plain values: this classic script (loaded right after prefs.js, before the page's modules)
// wraps Storage.prototype so that
//
//   getItem  returns the opened value from memory (opened once at start, `__kastrVault.ready`; the page's
//            modules `await` it before their first read). A value that cannot be opened (another origin's key,
//            a wiped IndexedDB) reads as null -- "not saved": the page asks for it again, nothing breaks.
//   setItem  keeps the plain value in memory and writes only the wrapped form (prefs.js underneath mirrors that
//            wrapped form to prefs.json -- never the plain one).
//   first load: plain values left by 0.21.91 are wrapped in place (the plain copy is gone).
//
// The conditional keys (camera / relay address history) are wrapped only while they carry a credential. A
// browser with no WebCrypto (plain http on a LAN address) cannot wrap: its localStorage codes are then kept in
// memory only (asked again on the next visit) and sessionStorage (this tab only) works as before.
// A 0.21.91 page finds no plain value and asks for the code once.
(function () {
  "use strict";
  var proto = window.Storage && window.Storage.prototype;
  if (!proto || proto.__kastrVault) return;
  var ls = null, ss = null;
  try { ls = window.localStorage; } catch (e) {}
  try { ss = window.sessionStorage; } catch (e) {}
  var PFX = "kv1:";
  var LOCAL = /^kastr\.(lastjoin|live|personal\.(?!people$).+)$/;                 // always wrapped
  var LOCAL_IF = /^kastr\.(rtsp\.(persist|history)|relay\.history)$/;              // wrapped while they carry a credential
  var SESSION = /^kastr\.(rejoin|watchcodes|invite|access|auth\..+)$/;            // this tab's codes and tokens
  var CRED = /(:\/\/[^\/\s@"]+@|[?&;#](jwt|token|access|code|key|apikey|api_key|secret|password|passwd|pwd|pass|auth|invite|sig|i)=[^&\s"]|\bki-[0-9a-f]{8}-|\beyJ[A-Za-z0-9_-]{6,}\.)/i;
  var subtle = (window.isSecureContext && window.crypto && window.crypto.subtle) ? window.crypto.subtle : null;
  var oGet = proto.getItem, oSet = proto.setItem, oRem = proto.removeItem;   // prefs.js's mirror wrappers underneath
  var enc = new TextEncoder(), dec = new TextDecoder();
  var cache = { l: new Map(), s: new Map() };
  var seq = {};
  var bad = new Set();   // wrapped values that would not open (not retried)
  var opened = false;

  function area(st) { return st && st === ls ? "l" : st && st === ss ? "s" : ""; }
  function named(a, k) { return a === "l" ? (LOCAL.test(k) || LOCAL_IF.test(k)) : a === "s" ? SESSION.test(k) : false; }
  function wants(a, k, v) {
    if (a === "l") return LOCAL.test(k) || (LOCAL_IF.test(k) && v != null && CRED.test(String(v)));
    return a === "s" && SESSION.test(k);
  }
  function st(a) { return a === "l" ? ls : ss; }
  function b64(u8) { var s = ""; for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]); return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
  function unb64(s) { s = String(s).replace(/-/g, "+").replace(/_/g, "/"); while (s.length % 4) s += "="; var b = atob(s), u = new Uint8Array(b.length); for (var i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; }
  function aad(a, k) { return enc.encode("kastr-vault-v1|" + a + "|" + k); }   // a wrapped value opens only under its own key name

  // ---- the key: made once per origin, non-extractable, kept in IndexedDB --------------------------------------------
  var keyP = null;
  function idb(fn) {
    return new Promise(function (res, rej) {
      var r;
      try { r = indexedDB.open("kastr-vault", 1); } catch (e) { rej(e); return; }
      r.onupgradeneeded = function () { r.result.createObjectStore("keys"); };
      r.onerror = function () { rej(r.error); };
      r.onblocked = function () { rej(new Error("blocked")); };
      r.onsuccess = function () { var db = r.result; fn(db).then(function (v) { db.close(); res(v); }, function (e) { db.close(); rej(e); }); };
    });
  }
  function txGet(db) {
    return new Promise(function (res, rej) {
      var t = db.transaction("keys", "readonly"), q = t.objectStore("keys").get("k1");
      q.onsuccess = function () { res(q.result || null); };
      q.onerror = function () { rej(q.error); };
    });
  }
  function txPutIfAbsent(db, nk) {   // one readwrite transaction: two tabs starting together end up with ONE key
    return new Promise(function (res, rej) {
      var t = db.transaction("keys", "readwrite"), s = t.objectStore("keys"), chosen = nk;
      var q = s.get("k1");
      q.onsuccess = function () { if (q.result) chosen = q.result; else s.put(nk, "k1"); };
      t.oncomplete = function () { res(chosen); };
      t.onerror = function () { rej(t.error); };
    });
  }
  function getKey() {
    if (keyP) return keyP;
    if (!subtle || !window.indexedDB) return (keyP = Promise.resolve(null));
    keyP = idb(function (db) {
      return txGet(db).then(function (k) {
        if (k) return k;
        return subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]).then(function (nk) { return txPutIfAbsent(db, nk); });
      });
    }).catch(function () { return null; });
    return keyP;
  }
  function wrap(key, a, k, v) {
    var iv = crypto.getRandomValues(new Uint8Array(12));
    return subtle.encrypt({ name: "AES-GCM", iv: iv, additionalData: aad(a, k) }, key, enc.encode(v)).then(function (ct) {
      var c = new Uint8Array(ct), out = new Uint8Array(12 + c.length);
      out.set(iv, 0); out.set(c, 12);
      return PFX + b64(out);
    });
  }
  function unwrap(key, a, k, w) {
    var u = unb64(String(w).slice(PFX.length));
    return subtle.decrypt({ name: "AES-GCM", iv: u.slice(0, 12), additionalData: aad(a, k) }, key, u.slice(12)).then(function (p) { return dec.decode(p); });
  }

  // ---- writes: plain in memory, wrapped on disk -------------------------------------------------------------------
  function persist(a, k, v) {
    var s = st(a), id = a + "|" + k, n = (seq[id] = (seq[id] || 0) + 1);
    if (!wants(a, k, v)) { oSet.call(s, k, v); return; }   // a history with no credential in it: as before
    return getKey().then(function (key) {
      if (seq[id] !== n) return;
      if (!key) {   // no WebCrypto here: never on disk in the clear
        if (a === "s") oSet.call(s, k, v); else { try { if (oGet.call(s, k) !== null) oRem.call(s, k); } catch (e) {} }
        return;
      }
      return wrap(key, a, k, v).then(function (w) { if (seq[id] === n) oSet.call(s, k, w); });
    }).catch(function () {});
  }
  function refresh(a, k, raw) {   // another tab wrote it: opened in the background (the old value serves meanwhile)
    return getKey().then(function (key) {
      if (!key) return;
      return unwrap(key, a, k, raw).then(function (p) { if (oGet.call(st(a), k) === raw) cache[a].set(k, p); }, function () { bad.add(raw); cache[a].delete(k); });
    }).catch(function () {});
  }

  proto.getItem = function (k) {
    var a = area(this);
    k = String(k);
    if (!a || !named(a, k)) return oGet.apply(this, arguments);
    if (cache[a].has(k)) return cache[a].get(k);
    var raw = oGet.call(this, k);
    if (!opened || raw === null) return raw;          // before the start-up open: the raw value (presence checks only)
    if (raw.indexOf(PFX) === 0) { if (!bad.has(raw)) refresh(a, k, raw); return null; }   // not opened (yet): "not saved"
    if (!wants(a, k, raw)) return raw;                 // a history with no credential in it: as before
    cache[a].set(k, raw);                              // a plain value that arrived later (an older page, a seed): wrapped now
    persist(a, k, raw);
    return raw;
  };
  proto.setItem = function (k, v) {
    var a = area(this);
    k = String(k);
    if (!a || !named(a, k)) return oSet.apply(this, arguments);
    v = String(v);
    cache[a].set(k, v);
    persist(a, k, v);
  };
  proto.removeItem = function (k) {
    var a = area(this);
    k = String(k);
    if (a && named(a, k)) { cache[a].delete(k); seq[a + "|" + k] = (seq[a + "|" + k] || 0) + 1; }
    return oRem.apply(this, arguments);
  };
  try { Object.defineProperty(proto, "__kastrVault", { value: true, configurable: true }); } catch (e) { proto.__kastrVault = true; }

  addEventListener("storage", function (e) {
    if (!e || e.storageArea !== ls || !e.key || !named("l", e.key)) return;
    if (e.newValue === null) { cache.l.delete(e.key); return; }
    if (e.newValue.indexOf(PFX) === 0) refresh("l", e.key, e.newValue);
    else cache.l.set(e.key, e.newValue);
  });

  // ---- start: open every wrapped value, wrap every plain one ------------------------------------------------------
  function start() {
    return getKey().then(function (key) {
      var jobs = [];
      ["l", "s"].forEach(function (a) {
        var s = st(a);
        if (!s) return;
        var names = [];
        try { for (var i = 0; i < s.length; i++) { var k = s.key(i); if (k && named(a, k)) names.push(k); } } catch (e) { return; }
        names.forEach(function (k) {
          var raw = oGet.call(s, k);
          if (raw === null || cache[a].has(k)) return;
          if (raw.indexOf(PFX) === 0) {
            if (!key) return;   // no key here: reads as not saved, the wrapped copy is left alone
            jobs.push(unwrap(key, a, k, raw).then(function (p) { if (!cache[a].has(k)) cache[a].set(k, p); },
              function () { try { if (oGet.call(s, k) === raw) oRem.call(s, k); } catch (e) {} }));   // not ours: gone, asked again
          } else if (wants(a, k, raw)) {
            cache[a].set(k, raw);       // 0.21.91 left it plain: wrapped now (or, with no WebCrypto, taken off the disk)
            if (wants(a, k, raw)) jobs.push(persist(a, k, raw));
          }
        });
      });
      return Promise.all(jobs);
    }).catch(function () {}).then(function () { opened = true; });
  }
  var ready = Promise.race([start(), new Promise(function (r) { setTimeout(r, 4000); })]).then(function () { opened = true; return !!subtle; });
  window.__kastrVault = { ready: ready, wrapped: function (v) { return typeof v === "string" && v.indexOf(PFX) === 0; } };
})();
