/* KASTR service worker (0.21.4) -- the offline shell for BROWSER clients (class "web", https).
 *
 * What it does: keeps the app shell (the page, the masthead, the vendored MoQ library, icons)
 * in one cache named after the KASTR version that served it, so an installed KASTR opens at
 * once and still renders when the relay host is unreachable -- the page then says so.
 * What it never touches: /api/*, /relay (the media pipe), /ca.crt, anything with a query
 * string, other origins, and non-GET requests. Those always go to the network as before.
 *
 * Served with substitution like every .js file: __KASTR_VERSION__ is the version and
 * __KASTR_PRECACHE__ the list the server computed (assets/vendor/esm/*, icons, the shell).
 *
 * 0.21.4: a worker that learns the host has moved on -- every response the server sends
 * carries X-KASTR-Version -- is STALE. It stops answering from its cache, passes assets
 * through to the network so the fresh page runs with a fresh shell, and asks the browser to
 * fetch its replacement. Before this, an old worker kept handing the old masthead script (and
 * its baked version) to a new page: an iPhone showed "v0.20.0" under a 0.21.3 host for a week
 * and the masthead's version poll reloaded it forever. The install also runs six fetches at a
 * time and skips files already in this version's cache, so a phone that cut an install short
 * resumes it instead of starting over. The page has its own last resort (the shell check in
 * moq-watch-lite.html): a masthead older than the page drops the worker and its caches once.
 */
const VERSION = "__KASTR_VERSION__";
const KNOWN = /^[0-9][0-9.]*(-dev)?$/.test(VERSION);
const CACHE = "kastr-" + (KNOWN ? VERSION : "dev");
const PRECACHE = __KASTR_PRECACHE__;

const SHELL_HTML = ["/moq-watch-lite.html", "/index.html", "/watch.html"];

let STALE = false;   // 0.21.4: the host answered with a version that is not ours

function noteVersion(r) {
  try {
    const v = r && r.headers && r.headers.get("X-KASTR-Version");
    if (KNOWN && v && v !== VERSION && !STALE) {
      STALE = true;
      self.registration.update().catch(() => {});
    }
  } catch (e) {}
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // 0.21.4: six at a time; a file already in this version's cache is not fetched again (a cut-short
    // install resumes). A missing optional file must not fail the whole install.
    const queue = PRECACHE.slice();
    async function pull() {
      while (queue.length) {
        const url = queue.shift();
        try {
          if (await cache.match(url)) continue;
          const r = await fetch(url, { cache: "no-store" });
          if (r.ok) await cache.put(url, r);
        } catch (e) {}
      }
    }
    await Promise.all([pull(), pull(), pull(), pull(), pull(), pull()]);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const k of await caches.keys()) {
      if (k.startsWith("kastr-") && k !== CACHE) await caches.delete(k);
    }
    await self.clients.claim();
  })());
});

function cacheable(req) {
  if (req.method !== "GET") return false;
  const u = new URL(req.url);
  if (u.origin !== self.location.origin) return false;
  if (u.search) return false;                                   // tokens, ?embed=, ?t= -- never cached
  const p = u.pathname;
  if (p.startsWith("/api/") || p === "/relay" || p.startsWith("/relay/") || p === "/ca.crt" || p === "/sw.js") return false;
  return p.startsWith("/assets/") || SHELL_HTML.includes(p) || p === "/manifest.webmanifest" || p === "/";
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (!cacheable(req)) return;                                  // network, untouched
  const u = new URL(req.url);
  const isPage = req.mode === "navigate" || SHELL_HTML.includes(u.pathname) || u.pathname === "/";
  if (isPage) {
    // network first: the server substitutes identity and relay per request; the cache is
    // the offline fallback only
    event.respondWith((async () => {
      try {
        const r = await fetch(req);
        noteVersion(r);
        if (r.ok && !STALE) { const c = await caches.open(CACHE); c.put(req, r.clone()); }
        return r;
      } catch (e) {
        const c = await caches.open(CACHE);
        return (await c.match(req)) || (await c.match("/moq-watch-lite.html")) || Response.error();
      }
    })());
    return;
  }
  event.respondWith((async () => {
    const c = await caches.open(CACHE);
    if (STALE) {
      // 0.21.4: the host runs a newer build than this worker -- the network's copy matches the page
      try { const r = await fetch(req); noteVersion(r); if (r.ok) return r; } catch (e) {}
      return (await c.match(req)) || Response.error();
    }
    // assets: cache first, then network (and remember it -- mediapipe, noise, scenes on first use)
    const hit = await c.match(req);
    if (hit) return hit;
    const r = await fetch(req);
    noteVersion(r);
    if (r.ok && !STALE) c.put(req, r.clone());
    return r;
  })());
});
