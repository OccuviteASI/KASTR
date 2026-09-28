/* KASTR service worker (0.20.0) -- the offline shell for BROWSER clients (class "web", https).
 *
 * What it does: keeps the app shell (the page, the masthead, the vendored MoQ library, icons)
 * in one cache named after the KASTR version that served it, so an installed KASTR opens at
 * once and still renders when the relay host is unreachable -- the page then says so.
 * What it never touches: /api/*, /relay (the media pipe), /ca.crt, anything with a query
 * string, other origins, and non-GET requests. Those always go to the network as before.
 *
 * Served with substitution like every .js file: __KASTR_VERSION__ is the version and
 * __KASTR_PRECACHE__ the list the server computed (assets/vendor/esm/*, icons, the shell).
 * A new KASTR build serves a new worker; its activate step drops the older caches, and the
 * masthead's version poll already reloads the page.
 */
const VERSION = "__KASTR_VERSION__";
const CACHE = "kastr-" + (/^[0-9][0-9.]*(-dev)?$/.test(VERSION) ? VERSION : "dev");
const PRECACHE = __KASTR_PRECACHE__;

const SHELL_HTML = ["/moq-watch-lite.html", "/index.html", "/watch.html"];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // one by one: a missing optional file must not fail the whole install
    for (const url of PRECACHE) {
      try {
        const r = await fetch(url, { cache: "no-store" });
        if (r.ok) await cache.put(url, r);
      } catch (e) {}
    }
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
        if (r.ok) { const c = await caches.open(CACHE); c.put(req, r.clone()); }
        return r;
      } catch (e) {
        const c = await caches.open(CACHE);
        return (await c.match(req)) || (await c.match("/moq-watch-lite.html")) || Response.error();
      }
    })());
    return;
  }
  // assets: cache first, then network (and remember it -- mediapipe, noise, scenes on first use)
  event.respondWith((async () => {
    const c = await caches.open(CACHE);
    const hit = await c.match(req);
    if (hit) return hit;
    const r = await fetch(req);
    if (r.ok) c.put(req, r.clone());
    return r;
  })());
});
