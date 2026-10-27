// 0.21.91 (Kenton: "I would like to add gif search options as well to the chat/messages."): THE GIF PICKER -- one picker for
// Room Chat (moq-watch-lite.html) and Messages (assets/kastr-msg.js). GIPHY through the hub: the page asks the relay it uses
// (window.__kgif: its base + this room's member token, in a header -- never in a URL); a spoke forwards to the hub, the hub
// holds Kenton's GIPHY key and proxies the previews too, so GIPHY never sees anyone's address. The page never names a URL:
// it asks for a search term / an offset / a GIF id and a rendition ("p" the small preview, "s" the copy that is sent).
// The GIF button shows only while the hub has a key and GIF search is switched on (GET /api/gif/status).
// A pick is fetched once through the hub and handed to the composer's send(file): Messages encrypts it like a pasted picture,
// Room Chat uploads it as a normal attachment.
(() => {
  "use strict";
  if (window.__gif) return;
  const STATUS_MS = 60000, RETRY_MS = 30000, DEBOUNCE_MS = 350, PREVIEW_PAR = 4, PREVIEW_KEEP = 240;
  const B = () => window.__kgif || null;
  const toast = (m, ms, level) => { try { window.__toast?.(m, ms || 5000, { level: level || "warn" }); } catch {} };
  let on = false, onFor = "", onAt = 0, checking = null;
  const mounts = new Set();
  const trace = [];
  const T = (ev, o) => { trace.push(Object.assign({ t: Date.now(), ev }, o || {})); if (trace.length > 200) trace.splice(0, 80); };

  async function call(path) {
    const b = B(), base = b?.base?.(), t = b?.token?.();
    if (!base || !t) throw Object.assign(new Error("join a room first"), { status: 0 });
    return fetch(base + path, { headers: { authorization: "Bearer " + t }, cache: "no-store" });
  }
  async function why(r) {
    const d = await r.json().catch(() => ({}));
    if (d.off) { onAt = 0; check(true); }
    return d.error || ("HTTP " + r.status);
  }

  // ---- is GIF search on for this page? -------------------------------------------------------------------------------------
  function check(force) {
    const b = B();
    let ok = false, key = "";
    try { ok = !!b?.ok?.(); key = ok ? b.base() + "|" + b.token() : ""; } catch { ok = false; }
    if (!ok) { setOn(false, ""); return Promise.resolve(); }
    if (!force && key === onFor && Date.now() - onAt < STATUS_MS) return Promise.resolve();
    if (checking) return checking;
    checking = (async () => {
      let v = false, failed = false;
      try {
        const r = await call("/api/gif/status");
        const d = await r.json().catch(() => ({}));
        v = r.ok && d.on === true;
        failed = !r.ok && r.status >= 500;
      } catch { failed = true; }
      onAt = failed ? Date.now() - STATUS_MS + RETRY_MS : Date.now();
      setOn(v, key);
      T("status", { on: v, failed });
      checking = null;
    })();
    return checking;
  }
  function setOn(v, key) {
    onFor = key;
    on = !!v;
    for (const m of mounts) m.paint();
  }
  setInterval(() => check(false), 15000);

  // ---- previews: fetched through the hub with the token, shown as blob: URLs (a few at a time, as they scroll into view) --
  const previews = new Map();   // id -> blob: URL
  const queue = [];
  let running = 0;
  function preview(id, img) {
    const u = previews.get(id);
    if (u) { img.src = u; return; }
    queue.push({ id, img });
    pump();
  }
  function pump() {
    while (running < PREVIEW_PAR && queue.length) {
      const { id, img } = queue.shift();
      if (!img.isConnected) continue;
      running++;
      (async () => {
        try {
          const r = await call("/api/gif/media/" + encodeURIComponent(id) + "?r=p");
          if (!r.ok) throw new Error(await why(r));
          const url = URL.createObjectURL(await r.blob());
          previews.set(id, url);
          if (previews.size > PREVIEW_KEEP) { const [k, v] = previews.entries().next().value; previews.delete(k); URL.revokeObjectURL(v); }
          img.src = url;
        } catch (e) { img.closest("button")?.classList.add("bad"); T("preview-fail", { id, e: String(e?.message || e) }); }
        finally { running--; pump(); }
      })();
    }
  }

  // ---- one composer's picker ---------------------------------------------------------------------------------------------
  // o = { root, btn, panel, input, emoji: { btn, panel }, send: async (file, item) => {} }
  function mount(o) {
    if (!o || !o.btn || !o.panel || o.btn.__gifMounted) return null;
    o.btn.__gifMounted = true;
    const panel = o.panel;
    panel.innerHTML = '<div class="kgtop"><input type="search" class="kgq" placeholder="Search GIPHY" aria-label="Search GIFs" autocomplete="off" spellcheck="false" maxlength="50">'
      + '<span class="kgby" title="GIF search by GIPHY (through this fleet’s hub)">Powered by GIPHY</span></div>'
      + '<div class="kgscroll"><div class="kggrid" role="list"></div><div class="kgend"></div></div><div class="kgmsg" aria-live="polite"></div>';
    const q = panel.querySelector(".kgq"), grid = panel.querySelector(".kggrid"), scroller = panel.querySelector(".kgscroll"),
      end = panel.querySelector(".kgend"), msgEl = panel.querySelector(".kgmsg");
    let gen = 0, next = null, loading = false, busy = false, term = null, timer = 0;
    const msg = (t, err) => { msgEl.textContent = t || ""; msgEl.classList.toggle("err", !!err); };
    const open = () => !panel.hidden;
    const seen = new IntersectionObserver((es) => {
      for (const e of es) if (e.isIntersecting) { seen.unobserve(e.target); preview(e.target.dataset.id, e.target.querySelector("img")); }
    }, { root: scroller, rootMargin: "120px 0px" });
    const more = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) load(false); }, { root: scroller, rootMargin: "160px 0px" });
    more.observe(end);

    function tile(it) {
      const b = document.createElement("button");
      b.type = "button"; b.dataset.id = it.id; b.setAttribute("role", "listitem");
      b.title = it.t ? it.t + " — click to send" : "Click to send";
      const im = document.createElement("img"); im.alt = it.t || "GIF"; im.decoding = "async";
      b.appendChild(im);
      b.addEventListener("click", (e) => { e.stopPropagation(); pick(it, b); });
      seen.observe(b);
      return b;
    }
    async function load(fresh) {
      if (loading || (!fresh && next == null)) return;
      const my = gen, off = fresh ? 0 : next;
      loading = true;
      if (fresh) msg(term ? "Searching…" : "Loading trending GIFs…");
      try {
        const r = await call("/api/gif/search?q=" + encodeURIComponent(term || "") + "&offset=" + off);
        if (my !== gen) return;
        if (!r.ok) { msg(await why(r), true); next = null; return; }
        const d = await r.json();
        const items = Array.isArray(d.items) ? d.items : [];
        grid.append(...items.map(tile));
        next = d.next ?? null;
        msg(grid.children.length ? "" : (term ? "No GIFs found for “" + term + "”." : "No GIFs right now."));
      } catch (e) { if (my === gen) { msg("GIF search did not answer — " + (e?.message || e), true); next = null; } }
      finally { if (my === gen) loading = false; }
      if (my === gen && next != null && scroller.scrollHeight <= scroller.clientHeight + 40) load(false);   // fill a tall panel
    }
    function run(t) {
      t = String(t || "").trim().split(/\s+/).join(" ").slice(0, 50);
      if (t === term && grid.children.length) return;
      term = t; gen++; next = null; loading = false;
      grid.replaceChildren(); scroller.scrollTop = 0;
      load(true);
    }
    async function pick(it, b) {
      if (busy) return;
      busy = true; b.classList.add("busy"); panel.classList.add("sending");
      msg("Sending GIF…");
      T("pick", { id: it.id });
      try {
        const r = await call("/api/gif/media/" + encodeURIComponent(it.id) + "?r=s");
        if (!r.ok) throw new Error(await why(r));
        const blob = await r.blob();
        const type = /^image\/(gif|webp)$/.test(blob.type) ? blob.type : "image/gif";
        const base = String(it.t || "").replace(/\s+GIF\b.*$/i, "").replace(/[^A-Za-z0-9 _-]+/g, "").trim().replace(/\s+/g, "-").slice(0, 40) || "giphy";
        const file = new File([blob], base + (type === "image/webp" ? ".webp" : ".gif"), { type });
        await o.send(file, it);
        msg("");
        show(false);
      } catch (e) {
        const t = "GIF not sent — " + (e?.message || e);
        msg(t, true);
        toast(t, 6000, "warn");
        T("send-fail", { id: it.id, e: String(e?.message || e) });
      } finally { busy = false; b.classList.remove("busy"); panel.classList.remove("sending"); }
    }
    function show(v) {
      if (v && !on) return;
      panel.hidden = !v;
      o.btn.classList.toggle("on", v);
      if (v) {
        if (o.emoji?.panel && !o.emoji.panel.hidden) { o.emoji.panel.hidden = true; o.emoji.btn?.classList.remove("on"); }   // one of the two at a time
        if (term === null) run("");
        setTimeout(() => q.focus(), 0);
      } else if (panel.contains(document.activeElement)) { o.input?.focus(); }
    }
    o.btn.addEventListener("click", (e) => { e.stopPropagation(); show(panel.hidden); });
    o.emoji?.btn?.addEventListener("click", () => { if (open()) show(false); });
    q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => run(q.value), DEBOUNCE_MS); });
    q.addEventListener("keydown", (e) => {
      e.stopPropagation();   // page shortcuts never see what is typed here
      if (e.key === "Enter") { e.preventDefault(); clearTimeout(timer); run(q.value); }
      if (e.key === "Escape") { e.preventDefault(); show(false); }
    });
    (o.root || panel).addEventListener("keydown", (e) => {
      if (e.key === "Escape" && open()) { e.preventDefault(); e.stopPropagation(); show(false); }
    }, true);
    const m = {
      paint() {
        if (!o.btn.isConnected) { mounts.delete(m); seen.disconnect(); more.disconnect(); return; }   // its composer was rebuilt
        o.btn.hidden = !on;
        if (!on && open()) show(false);
      },
      open: () => show(true), close: () => show(false), shown: open,
    };
    mounts.add(m);
    m.paint();
    check(false);
    return m;
  }

  window.__gif = {
    mount,
    on: () => on,
    check: () => check(true),
    trace: () => trace.slice(),
  };
  try { window.__gifChatMount?.(); } catch (e) { T("chat-mount-fail", { e: String(e?.message || e) }); }   // Room Chat (the page's own module ran first)
  check(false);
})();
