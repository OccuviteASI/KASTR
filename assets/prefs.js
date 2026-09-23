// KASTR 0.14.0 -- prefs mirror shim.
//
// The desktop app serves the page from loopback, and Chrome's localStorage for
// that origin dies with the browser profile (a reinstall, a profile wipe, a
// port change). This classic script runs BEFORE the boot script's first
// localStorage.getItem and mirrors the operator's KASTR keys to the server's
// prefs file (/api/prefs), both ways:
//
//   seed     GET /api/prefs (synchronous, so the page boots with the values)
//            -> every whitelisted key the server has and this origin lacks is
//            written into localStorage. Existing origin data always wins, and
//            seeding never POSTs.
//   backfill a fresh server file (no items) is filled from the keys this origin
//            already holds.
//   mirror   Storage.prototype.setItem / removeItem on window.localStorage
//            queue whitelisted writes (250 ms coalesce) and flush them with
//            sendBeacon to POST /api/prefs {set: {key: value|null}}.
//
// Access codes never reach the file: kastr.lastjoin is redacted (access, code
// -> "") before it is queued. clear() is not mirrored. Phones and LAN viewers
// (any non-loopback host) keep plain localStorage: the shim returns at once.
// An old server or a dev harness without /api/prefs is a silent no-op.
(function () {
  "use strict";
  if (!/^(127\.0\.0\.1|localhost|\[::1\])$/.test(location.hostname)) return;
  var ls;
  try { ls = window.localStorage; if (!ls) return; } catch (e) { return; }

  var WL = /^kastr\.(lastjoin|rtsp\.|grid\.|profile$|sidebar|mic\.|volume$|relay\.history$|channels\.mine$|channel$|operator\.name$|publishOnly$|rail\.w$|watch\.)/;
  var ENDPOINT = "/api/prefs";

  // ---- seed (synchronous: the boot script reads localStorage a few lines later)
  var items = null;
  try {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", ENDPOINT, false);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.send(null);
    if (xhr.status !== 200) return;
    var data = JSON.parse(xhr.responseText || "null");
    if (!data || typeof data !== "object" || Array.isArray(data)) return;
    items = (data.items && typeof data.items === "object" && !Array.isArray(data.items)) ? data.items : data;
  } catch (e) {
    return;   // no endpoint, no network, bad JSON: plain localStorage, as before
  }

  var seeded = 0;
  var serverKeys = Object.keys(items).filter(function (k) { return WL.test(k); });
  for (var i = 0; i < serverKeys.length; i++) {
    var k = serverKeys[i];
    var v = items[k];
    if (v === null || v === undefined) continue;
    if (typeof v !== "string") { try { v = JSON.stringify(v); } catch (e) { continue; } }
    try {
      if (ls.getItem(k) === null) { ls.setItem(k, v); seeded++; }   // before the wrap: seeding never POSTs
    } catch (e) {}
  }

  // ---- mirror queue
  var pending = {};
  var pendingN = 0;
  var timer = null;

  function redact(key, value) {
    if (key !== "kastr.lastjoin" || value === null) return value;
    try {
      var o = JSON.parse(value);
      if (!o || typeof o !== "object") return value;
      if ("access" in o) o.access = "";
      if ("code" in o) o.code = "";
      return JSON.stringify(o);
    } catch (e) {
      return undefined;   // unparseable: never forward something that might hold a code
    }
  }

  function queue(key, value) {
    var v = redact(key, value);
    if (v === undefined) return;
    pending[key] = v;
    pendingN++;
    if (!timer) timer = setTimeout(flush, 250);
  }

  function flush() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!pendingN) return false;
    var body = JSON.stringify({ set: pending });
    pending = {};
    pendingN = 0;
    var sent = false;
    try {
      if (navigator.sendBeacon) sent = navigator.sendBeacon(ENDPOINT, new Blob([body], { type: "application/json" }));
    } catch (e) { sent = false; }
    if (!sent) {
      try { fetch(ENDPOINT, { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body: body }).catch(function () {}); } catch (e) {}
    }
    return true;
  }

  // ---- backfill: a fresh server file learns what this origin already knows.
  // "Fresh" = the server had no prefs.json (it answered with its rescue seed,
  // `seed: true`, or with nothing) -- not "no items": a seed IS items.
  var fresh = false;
  try { fresh = !!(data && data.seed) || Object.keys(items).length === 0; } catch (e) { fresh = true; }
  if (fresh) {
    try {
      for (var j = 0; j < ls.length; j++) {
        var bk = ls.key(j);
        if (bk && WL.test(bk)) queue(bk, ls.getItem(bk));
      }
    } catch (e) {}
  }

  // ---- wrap (localStorage only; sessionStorage and other Storage objects pass through)
  var proto = window.Storage && window.Storage.prototype;
  if (proto && !proto.__kastrPrefsWrapped) {
    var origSet = proto.setItem, origRemove = proto.removeItem;
    proto.setItem = function (key, value) {
      var r = origSet.apply(this, arguments);
      if (this === ls && WL.test(String(key))) queue(String(key), String(value));
      return r;
    };
    proto.removeItem = function (key) {
      var r = origRemove.apply(this, arguments);
      if (this === ls && WL.test(String(key))) queue(String(key), null);
      return r;
    };
    try { Object.defineProperty(proto, "__kastrPrefsWrapped", { value: true, configurable: true }); } catch (e) { proto.__kastrPrefsWrapped = true; }
  }
  window.addEventListener("pagehide", function () { flush(); });

  window.__prefs = {
    seeded: seeded,
    keys: function () {
      var out = [];
      try { for (var n = 0; n < ls.length; n++) { var kk = ls.key(n); if (kk && WL.test(kk)) out.push(kk); } } catch (e) {}
      return out;
    },
    flush: flush
  };
  if (seeded > 0) console.info("[prefs] seeded " + seeded + " keys from the server");
})();
