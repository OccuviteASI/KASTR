/* Injects the shared ASI masthead into any page that includes this script.
 *
 * Done in JS rather than copy-pasted markup so the three upstream demo pages
 * (watch/publish/stats), whose bodies are owned by prebuilt bundles, get the
 * same header without editing their structure. Add to a page with:
 *   <link rel="stylesheet" href="/assets/asi-brand.css">
 *   <script type="module" src="/assets/asi-brand.js"></script>
 */

// 0.13.0: "Relay server" left the nav -- it is reached from the Relay ▾ popover
// ("Relay server settings…"), and the app shell creates its tab link on demand.
const NAV = [
  { href: "/app.html", label: "App", app: true },   // 0.17.0: the shell is the host window's; web clients get Go Live only
  { href: "/moq-watch-lite.html", label: "Go Live" },
];

// Relay stats are no longer a nav entry -- they hang off the relay badge on the
// right, which is where you are already looking when you wonder about the relay.
const STATS_PAGE = "/stats.html";

// The build has http://localhost:4443 baked in; kastr-serve.py rewrites it to the
// real relay as it serves. Reading it from this file means the header shows
// whatever the server substituted, with no second place to keep in sync.
const RELAY = "http://localhost:4443";

// Substituted as the page is served, like the relay above. Falls back when the
// page is opened by something that does not substitute.
const RAW_VERSION = "__KASTR_VERSION__";
const VERSION = /^[0-9][0-9.]*(-dev)?$/.test(RAW_VERSION) ? RAW_VERSION : "dev";

// 0.17.0: the client class (assets/client.js): "web" = a browser on another device
// that opened this relay host's web port. A web client has no host controls here
// (relay switching, updates, window geometry, heartbeat) and follows the host's
// version by reloading.
const CLIENT = window.__kastrClient ?? null;
const IS_WEB = CLIENT?.class === "web";

// 0.12.0: the operating mode this KASTR boots as (full | viewer | publisher |
// relay | publisher-relay), from /api/instance -- the launcher sets it, so one
// fetch at start is the truth (the badge's 5 s poll re-applies it anyway).
// Exported for the pages, embedded ones too (they never build a masthead):
// window.__kastrMode is the string once known, window.__kastrModeReady a
// promise of it. body.asi-viewer lets a page's CSS react to a viewer box.
let MODE = "full";
const modeHooks = [];   // masthead painters registered by build()
function applyMode(m) {
  MODE = (typeof m === "string" && m) ? m : "full";
  window.__kastrMode = MODE;
  try { document.body.classList.toggle("asi-viewer", MODE === "viewer"); } catch {}
  for (const h of modeHooks) { try { h(MODE); } catch {} }
}
window.__kastrModeReady = fetch("/api/instance", { cache: "no-store" })
  .then((r) => r.json())
  .then((inst) => { applyMode(inst.mode); return MODE; })
  .catch(() => { applyMode("full"); return MODE; });

function build() {
  // ?embed=1 -- the page is framed by the app shell or the Watch page's Share
  // panel, both of which supply the masthead. Injecting a second one would
  // waste vertical space and give the window two competing nav bars.
  if (new URLSearchParams(location.search).get("embed")) {
    document.body.classList.add("asi-embed");
    return;
  }

  const here = location.pathname.replace(/\/index\.html$/, "/");
  const onRelayPage = /\/relay\.html$/.test(here);   // 0.13.0: the popover's settings entry hides here

  const header = document.createElement("header");
  header.className = "asi-header";

  // The official lockup (assets/asi-logo.svg), in its reverse variant so the
  // navy wordmark stays legible on the navy masthead.
  const mark = document.createElement("a");
  mark.className = "asi-mark";
  // 0.7.0: the logo is identity, not a link -- About lives in the
  // Options menu on Go Live.
  mark.title = "KASTR";
  mark.innerHTML =
    '<img src="/assets/asi-logo-dark.svg" alt="ASI — Autonomous Solutions" width="81" height="36">' +
    '<span class="tag">Autonomous<br>Solutions</span>';

  const product = document.createElement("span");
  product.className = "asi-product";
  product.innerHTML = '<b>KASTR</b> <button type="button" class="ver" '
    + 'title="What changed in this build">v' + VERSION + "</button>";
  product.title = "Kenton's ASI Streaming Tool with Relay — version " + VERSION;

  const nav = document.createElement("nav");
  nav.className = "asi-nav";
  for (const item of NAV.filter((n) => !(n.app && IS_WEB))) {
    const a = document.createElement("a");
    a.href = item.href;
    a.textContent = item.label;
    if (item.href === here || (item.href !== "/" && here.endsWith(item.href))) a.className = "on";
    nav.appendChild(a);
  }

  // The relay badge doubles as the way in to the relay's live stats.
  const relay = document.createElement("button");
  relay.type = "button";
  relay.className = "asi-relay";
  relayBadgeEl = relay;
  // Painted from a variable, not the constant: the constant is whatever the
  // server substituted when THIS document was served, and the app shell's
  // top document is served once per launch. The poll below moves it.
  let currentRelay = webRelayFix(RELAY);   // 0.19.0: a tunnel that rewrote Host handed out localhost
  let popHeadEl = null;   // 0.12.0: the popover's title, set once the popover exists
  const relayHostText = () => currentRelay.replace(/^https?:\/\//, "");
  const paintRelay = () => {
    // 0.12.0: the badge reads "Relay <caret>" in every mode; the address moved
    // into its title and the popover head. The health light stays.
    relay.innerHTML = '<span class="hdot" hidden></span>Relay <span class="caret">\u25be</span>';
    relay.title = `Relay: ${currentRelay}\nClick for live relay stats`;
    if (popHeadEl) popHeadEl.textContent = "Relay stats \u2014 " + relayHostText();
    paintHealthDot();   // innerHTML above replaced the dot; restamp now
  };
  paintRelay();

  // The stats page is embedded rather than reimplemented: it already reads the
  // relay's .stats broadcast, and duplicating that here would be a second thing
  // to keep correct.
  const pop = document.createElement("div");
  pop.className = "asi-relaypop";
  pop.hidden = true;
  pop.innerHTML =
    '<div class="head"><span class="ptitle">Relay stats</span>' +
    '<a href="' + STATS_PAGE + '" target="_blank" rel="noopener">Open full page \u2197</a>' +
    '<button type="button" class="close" title="Close">\u2715</button></div>' +
    // 0.6.8: the badge is also where the relay gets CHANGED -- the pages'
    // own relay buttons are retired. Server first (owns the substituted
    // value), then every live page that exposes __kastrSetRelay.
    '<div class="rrow">relay <input class="rurl" type="text" spellcheck="false">' +
    '<button type="button" class="rgo">Connect</button></div>' +
    '<div class="rhist"></div>' +
    '<div class="rhost">Relay host: \u2026</div>' +
    '<div class="frame"></div>' +
    // 0.13.0: the Relay server page lost its nav entry; this is its way in.
    // Hidden by paintMode on viewer and publisher boxes (no relay of their
    // own to configure) and on the Relay page itself. Styled inline: the
    // stylesheet has no rule for it and the look is the .rhost line's.
    '<div class="rset" style="flex:none;padding:4px 10px 8px;border-top:1px solid var(--line)">' +
    '<button type="button" class="rsetbtn" style="background:transparent;border:1px solid var(--line);' +
    'color:var(--text-dim);border-radius:4px;padding:4px 9px;font-size:11px;cursor:pointer;height:auto"' +
    ' title="Start, stop and configure the relay this KASTR hosts">Relay server settings\u2026</button></div>';
  popHeadEl = pop.querySelector(".ptitle");
  paintRelay();   // 0.12.0: "Relay stats — <host>" now that the head exists
  // 0.8.6: which KASTR version the relay HOST machine runs (via the server
  // proxy -- the page can't cross-origin fetch it under COEP).
  const paintRelayHost = async () => {
    const el = pop.querySelector(".rhost");
    if (!el) return;
    let host = "";
    try { host = new URL(currentRelay).hostname; } catch {}
    if (!host) { el.textContent = "Relay host: \u2014"; return; }
    try {
      const i = await fetch("/api/peer/instance?host=" + encodeURIComponent(host) + "&relay=" + encodeURIComponent(currentRelay || ""), { cache: "no-store" }).then((r) => r.json());   // 0.19.0: a web relay is asked at its origin
      el.textContent = i.version ? "Relay host: KASTR v" + i.version + (i.version !== VERSION ? "  (this machine: v" + VERSION + ")" : "")
        : "Relay host: no KASTR web at " + host + ":8000 \u2014 not an update source";
    } catch { el.textContent = "Relay host: unknown"; }
  };
  setInterval(() => { if (!pop.hidden) paintRelayHost(); }, 10000);

  // 0.8.3: relay address history -- every address ever connected to comes
  // back as a datalist suggestion (MRU, capped; shared with the pages via
  // localStorage since everything is same-origin).
  const HIST_KEY = "kastr.relay.history";
  const relayHist = () => {
    try { return JSON.parse(localStorage.getItem(HIST_KEY) || "[]").filter(Boolean); }
    catch { return []; }
  };
  const relayHistAdd = (u) => {
    try {
      const h = relayHist().filter((x) => x !== u);
      h.unshift(u);
      localStorage.setItem(HIST_KEY, JSON.stringify(h.slice(0, 5)));   // 0.8.7: last 5
    } catch {}
  };
  // 0.8.7: the last 5 relays as a visible list -- live Available / Not
  // available dot per entry (the same reachability probe the badge uses),
  // click a row to put it in the field, Connect to switch.
  const histStatus = new Map();   // url -> true | false | null
  const probeOne = async (u) => {
    try {
      const ctl = new AbortController();
      const t = setTimeout(() => ctl.abort(), 2500);
      const r = await fetch(relayProbeUrl(u), { cache: "no-store", signal: ctl.signal });   // 0.19.0
      clearTimeout(t);
      histStatus.set(u, !!r.ok);
    } catch { histStatus.set(u, false); }
    paintRelayHist(false);
  };
  const paintRelayHist = (probe = true) => {
    const box = pop.querySelector(".rhist");
    if (!box) return;
    const list = relayHist().slice(0, 5);
    box.replaceChildren(...list.map((u) => {
      const row = document.createElement("div");
      row.className = "rh" + (u === currentRelay ? " cur" : "");
      const dot = document.createElement("span");
      const st = histStatus.get(u);
      dot.className = "rdot " + (st === true ? "ok" : st === false ? "bad" : "");
      dot.title = st === true ? "Available" : st === false ? "Not available" : "Checking\u2026";
      const txt = document.createElement("span");
      txt.className = "rurlt";
      txt.textContent = u.replace(/^https?:\/\//, "") + (u === currentRelay ? "  (current)" : "");
      const stt = document.createElement("span");
      stt.className = "rst";
      stt.textContent = st === true ? "Available" : st === false ? "Not available" : "\u2026";
      row.append(dot, txt, stt);
      row.title = "Click to put " + u + " in the relay field";
      row.addEventListener("click", (e) => { e.stopPropagation(); pop.querySelector(".rurl").value = u; });
      return row;
    }));
    if (probe) for (const u of list) probeOne(u);
  };
  setInterval(() => { if (!pop.hidden) paintRelayHist(true); }, 10000);

  let loaded = false;
  const closePop = () => { pop.hidden = true; relay.classList.remove("open"); };
  const openPop = () => {
    if (!loaded) {
      // Lazy: don't open a second connection to the relay on every page load.
      const f = document.createElement("iframe");
      f.src = STATS_PAGE + "?embed=1";
      f.setAttribute("allow", "autoplay");
      pop.querySelector(".frame").appendChild(f);
      loaded = true;
    }
    pop.querySelector(".rurl").value = currentRelay;
    paintRelayHist();   // fresh MRU list every open (0.8.3)
    paintRelayHost();   // 0.8.6
    pop.hidden = false;
    relay.classList.add("open");
  };
  relay.addEventListener("click", (e) => {
    e.stopPropagation();
    pop.hidden ? openPop() : closePop();
  });
  pop.addEventListener("click", (e) => {
    if (e.target.classList.contains("close")) closePop();
    else e.stopPropagation();
  });
  // 0.12.0: a viewer box cannot change the relay -- the address row and the
  // history leave the popover (health light + stats frame stay) and Go Live
  // reads "Join a room". Publisher boxes keep the row: an operator arms the
  // box once. Idempotent; runs now and again when the mode arrives. The label
  // is swapped in the text node so the shell's dot/close spans survive.
  const paintMode = (m) => {
    const viewer = m === "viewer";
    for (const a of nav.querySelectorAll('a[href="/moq-watch-lite.html"]')) {
      for (const n of a.childNodes) {
        if (n.nodeType === 3 && n.nodeValue.trim()) n.nodeValue = viewer ? "Join a room" : "Go Live";
      }
    }
    for (const sel of [".rrow", ".rhist"]) {
      const el = pop.querySelector(sel);
      if (el) el.style.display = (viewer || IS_WEB) ? "none" : "";   // the stylesheet's display:flex beats [hidden]; 0.17.0: web clients cannot switch the host's relay
    }
    // 0.13.0: "Relay server settings…" -- a viewer box has no relay to run and
    // a publisher box is armed once from the address row above; only full,
    // relay and publisher-relay boxes host a relay worth configuring. Also
    // pointless on the Relay page itself (the ?solo=1 relay-only boot too).
    const rset = pop.querySelector(".rset");
    if (rset) rset.style.display = (viewer || m === "publisher" || onRelayPage || IS_WEB) ? "none" : "";   // 0.17.0: + web clients
  };
  modeHooks.push(paintMode);
  paintMode(MODE);
  pop.querySelector(".rsetbtn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    closePop();
    // In the app shell the Relay page is a tab (the shell creates its nav link
    // on demand); on a standalone page it is simply the next page.
    if (typeof window.__app?.show === "function") window.__app.show("relay");
    else location.href = "/relay.html";
  });

  // 0.13.0: ONE relay switch, shared by the Connect button and any framed page
  // that reaches up with window.top.__kastrConnectRelay(u) (the Go Live gate's
  // Relay field). Server first (it owns the substituted value), then history,
  // then every live page that exposes __kastrSetRelay, then the badge.
  // Resolves { ok: true, url } with the normalised URL, or { ok: false, error }
  // -- notably when the server refuses the switch off-loopback (403: the relay
  // control plane answers the machine itself only), which the button used to
  // swallow in silence.
  const connectRelay = async (raw) => {
    if (MODE === "viewer") return { ok: false, error: "viewer" };   // 0.12.0: no relay changes from a viewer box
    let u = String(raw ?? "").trim();
    if (!u) return { ok: false, error: "empty" };
    if (!/^https?:\/\//.test(u)) u = (location.protocol === "https:" ? "https://" : "http://") + u;   // 0.8.9
    let res = null;
    try {
      res = await fetch("/api/relay/use", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: u }) });
    } catch {}   // no answer at all: the page-side switch still happens, as before
    if (res && !res.ok) {
      let detail = "";
      try { detail = (await res.json()).error || ""; } catch {}
      const error = res.status === 403 ? "Relay switching is only allowed from this machine"
        : "Relay switch refused (HTTP " + res.status + (detail ? ": " + detail : "") + ")";
      brandToast(error);
      return { ok: false, error };
    }
    relayHistAdd(u);   // MRU history for the datalist (0.8.3)
    const wins = [window];
    for (const f of document.querySelectorAll("#frames iframe")) wins.push(f.contentWindow);
    for (const w of wins) { try { w.__kastrSetRelay?.(u); } catch {} }
    currentRelay = u;
    paintRelay();
    paintRelayHost();
    pop.querySelector(".rurl").value = u;   // by assignment only -- never a synthetic change event
    if (!pop.hidden) paintRelayHist(false);   // the "(current)" marker moves
    // 0.8.6: a different relay may be a different version authority.
    window.__kastrCheckUpdate?.(hostOf(u)).then((r) => { if (r && r.status !== "current") brandToast(r.text); });
    const f = pop.querySelector("iframe");
    if (f) f.src = f.src;
    return { ok: true, url: u };
  };
  window.__kastrConnectRelay = connectRelay;   // top document only: build() returned early for embed=1
  pop.querySelector(".rgo").addEventListener("click", () => {
    const u = pop.querySelector(".rurl").value.trim();
    if (!u) return;
    connectRelay(u);
  });
  document.addEventListener("click", () => { if (!pop.hidden) closePop(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePop(); });

  // Follow runtime repoints (the Relay page's "use this relay"). The relay
  // baked into this document froze at serve time, and nothing ever reloads
  // the app shell's top document -- so ask the server, which owns the live
  // value, on the heartbeat's own 5s cadence. Embedded pages never get
  // here: build() returned before the badge existed.
  setInterval(async () => {
    try {
      const res = await fetch("/api/instance", { cache: "no-store" });
      if (!res.ok) return;
      const inst = await res.json();
      // 0.17.0: a web client runs the relay host's build -- when the host updates, reload
      if (IS_WEB && inst.version && VERSION !== "dev" && inst.version !== VERSION && !window.__kastrReloading) {
        window.__kastrReloading = true;
        try { brandToast("KASTR on the host updated to v" + inst.version + " \u2014 reloading"); } catch {}
        setTimeout(() => { try { location.reload(); } catch {} }, 2500);
        return;
      }
      if (inst.mode) applyMode(inst.mode);   // 0.12.0: same poll carries the mode
      if (!inst.relay || webRelayFix(inst.relay) === currentRelay) return;
      currentRelay = webRelayFix(inst.relay);   // 0.19.0
      paintRelay();
      // The stats popover's iframe was substituted against the OLD relay
      // when it was first opened; re-navigating it fetches fresh bytes
      // (rewritten pages are no-store). Never opened: nothing to do, the
      // first open is fresh anyway.
      const f = pop.querySelector("iframe");
      if (f) f.src = f.src;
    } catch {}
  }, 5000);

  // Release notes, behind the version number. Lazy, and parsed with a
  // deliberately tiny markdown subset -- headings, bullets, bold, code -- so it
  // stays a plain file anyone can edit rather than needing a build step.
  const notesPop = document.createElement("div");
  notesPop.className = "asi-notespop";
  notesPop.hidden = true;
  notesPop.innerHTML =
    '<div class="head"><span>Release notes</span>'
    + '<button type="button" class="upd" title="Compare with the KASTR on the relay host and update if it differs">Check for updates</button>'
    + '<span class="updst"></span>'
    + '<button type="button" class="close" title="Close">✕</button></div>'
    + '<div class="body">Loading…</div>';

  if (IS_WEB) { notesPop.querySelector(".upd")?.remove(); notesPop.querySelector(".updst")?.remove(); }   // 0.17.0: no host update from a web client
  const closeNotes = () => { notesPop.hidden = true; };
  notesPop.addEventListener("click", (e) => {   // 0.15.1: previous versions fold
    const b = e.target.closest(".prevbtn"); if (!b) return;
    const prev = notesPop.querySelector(".prev"); if (!prev) return;
    prev.hidden = !prev.hidden;
    b.textContent = prev.hidden ? "Show previous versions (" + b.dataset.n + ")" : "Hide previous versions";
  });
  let notesLoaded = false;

  async function openNotes() {
    notesPop.hidden = false;
    if (notesLoaded) return;
    notesLoaded = true;
    const body = notesPop.querySelector(".body");
    try {
      const res = await fetch("/RELEASES.md", { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      body.innerHTML = renderNotes(await res.text(), VERSION);
    } catch (e) {
      notesLoaded = false;   // let a failure be retried
      body.textContent = "Could not load release notes (" + (e.message || e) + ").";
    }
  }

  function esc(t) {
    return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // 0.15.1: only the running build's notes are shown; everything older sits behind
  // "Show previous versions". A heading is "## vX.Y.Z — title", so the match is on
  // the version token, not the whole line (a dev build with no exact match shows
  // the newest section as current).
  function renderNotes(md, current) {
    const sections = [];   // [{ title, lines[] }] in file order (newest first)
    let cur = null;
    for (const raw of md.split(/\r?\n/)) {
      const h2 = raw.trim().match(/^##\s+(.*)$/);
      if (h2) { cur = { title: h2[1].trim(), lines: [] }; sections.push(cur); continue; }
      if (cur) cur.lines.push(raw);
    }
    if (!sections.length) return renderBlock(md.split(/\r?\n/));
    const want = "v" + String(current || "").replace(/-dev$/, "");
    let idx = sections.findIndex((sec) => sec.title.split(/[\s—-]/)[0] === want);   // "v0.15.1 -- title" -> first token
    if (idx < 0) idx = 0;
    const one = (sec, isCur) =>
      '<h3' + (isCur ? ' class="cur"' : '') + '>' + esc(sec.title)
      + (isCur ? ' <span class="tag">this build</span>' : '') + '</h3>' + renderBlock(sec.lines);
    const rest = sections.filter((_, i) => i !== idx);
    let html = one(sections[idx], true);
    if (rest.length) {
      html += '<button type="button" class="prevbtn" data-n="' + rest.length + '">Show previous versions (' + rest.length + ')</button>'
        + '<div class="prev" hidden>' + rest.map((sec) => one(sec, false)).join("") + '</div>';
    }
    return html;
  }

  function renderBlock(lines) {
    const out = [];
    let open = null;   // 'li' or 'p' -- what a wrapped line continues
    let inList = false;

    const closeList = () => {
      if (inList) { out.push("</ul>"); inList = false; }
    };

    for (const raw of lines) {
      const line = raw.trim();

      if (!line) { open = null; closeList(); continue; }

      const bullet = line.match(/^[-*]\s+(.*)$/);
      if (bullet) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push("<li>" + inline(bullet[1]) + "</li>");
        open = "li";
        continue;
      }

      // The file's own title would just repeat the popover heading.
      if (/^#\s+/.test(line)) { closeList(); open = null; continue; }

      // A wrapped line: RELEASES.md is hand-wrapped at ~80 columns, so a plain
      // line under a bullet or paragraph is the rest of that sentence, not a
      // new block. Sew it back onto whatever is still open.
      if (open) {
        const i = out.length - 1;
        const tag = open === "li" ? "</li>" : "</p>";
        out[i] = out[i].slice(0, -tag.length) + " " + inline(line) + tag;
        continue;
      }

      closeList();
      out.push("<p>" + inline(line) + "</p>");
      open = "p";
    }

    closeList();
    return out.join("");
  }

  function inline(t) {
    return esc(t)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  }

  const verBtn = product.querySelector(".ver");
  verBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    notesPop.hidden ? openNotes() : closeNotes();
  });
  notesPop.addEventListener("click", (e) => {
    if (e.target.classList.contains("close")) closeNotes();
    else e.stopPropagation();
  });
  document.addEventListener("click", () => { if (!notesPop.hidden) closeNotes(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeNotes(); });
  // Clicks that land inside an iframe (the shell's page area, the stats
  // frame) never reach this document -- but they move focus, and blur is
  // the one signal that crosses the boundary (0.6.9).
  window.addEventListener("blur", () => { closePop(); closeNotes(); });

  header.append(mark, product, nav, relay);
  document.body.prepend(header);
  document.body.appendChild(pop);
  document.body.appendChild(notesPop);

  // 0.8.6: on-demand fleet update -- POST the check, follow update-check.json
  // through /api/instance, report. Shared by the Release-notes button, About,
  // and the relay Connect button (a NEW relay may be a new authority).
  const brandToast = (msg, ms = 6000) => {
    let t = document.getElementById("asiToast");
    if (!t) { t = document.createElement("div"); t.id = "asiToast"; document.body.appendChild(t); }
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(brandToast._t);
    brandToast._t = setTimeout(() => t.classList.remove("show"), ms);
  };
  const hostOf = (u) => { try { return new URL(u).hostname; } catch { return ""; } };
  window.__kastrCheckUpdate = async (host) => {
    if (IS_WEB) return { status: "web", text: "Updates are installed on the KASTR that hosts the relay; this page follows it." };   // 0.17.0
    const h = host || hostOf(currentRelay);
    const t0 = Date.now() / 1000 - 2;
    let r;
    try {
      r = await fetch("/api/update/check", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ host: h }) }).then((x) => x.json());
    } catch (e) { return { status: "error", text: "Check failed: " + (e.message || e) }; }
    if (r.status === "dev") return { status: "dev", text: "Dev checkout \u2014 no self-update." };
    if (r.error) return { status: "error", text: r.error };
    let u = null;
    for (let i = 0; i < 15; i++) {
      await new Promise((res) => setTimeout(res, 1000));
      try {
        const inst = await fetch("/api/instance", { cache: "no-store" }).then((x) => x.json());
        u = inst.updateCheck;
        if (u && u.at >= t0 && u.status !== "checking") break;
      } catch {
        setTimeout(() => { try { window.close(); } catch {} }, 400);   // 0.8.8
        return { status: "updating", text: "Updating \u2014 KASTR is restarting." };
      }
    }
    const text = !u ? "No result."
      : u.status === "current" ? "Up to date (v" + VERSION + ")."
      : u.status === "unreachable" ? "Relay host " + (u.detail || h) + " unreachable \u2014 no update source there."
      : u.status === "authority" ? "This machine is the version authority."
      : u.status === "updating" ? "Updating \u2014 KASTR will restart."
      : u.status === "checking" ? "Still checking\u2026"
      : (u.status + (u.detail ? " \u2014 " + u.detail : ""));
    return { status: u?.status || "unknown", text };
  };
  {
    const updBtn = notesPop.querySelector(".upd"), updSt = notesPop.querySelector(".updst");
    updBtn?.addEventListener("click", async (e) => {
      e.stopPropagation();
      updSt.textContent = "Checking\u2026";
      const r = await window.__kastrCheckUpdate();
      updSt.textContent = r.text;
    });
  }

  if (!document.querySelector("link[rel~='icon']")) {
    const link = document.createElement("link");
    link.rel = "icon";
    link.type = "image/svg+xml";
    link.href = "/assets/asi-favicon.svg";
    document.head.appendChild(link);
  }
}

// ---- relay health light (0.6.7) --------------------------------------------
// Green when the page's MoQ connection is up, yellow while connecting or
// briefly down (Reload auto-retries), red once the relay has been
// unreachable for more than 15 seconds. Pages without a connection
// (__relayHealth absent) keep the neutral badge; the app shell installs
// __relayHealthProxy to mirror its switcher frame's light. Runs at module
// level on purpose: embedded frames (no masthead) still compute the
// tri-state, which is exactly what the shell's proxy reads.
let relayBadgeEl = null;   // set by build(); embedded pages never have one
let relayTri = null;       // "ok" | "warn" | "bad" | null
let relayDownSince = null;
function paintHealthDot() {
  const d = relayBadgeEl?.querySelector?.(".hdot");
  if (!d) return;
  d.hidden = relayTri === null;
  d.classList.toggle("ok", relayTri === "ok");
  d.classList.toggle("warn", relayTri === "warn");
  d.classList.toggle("bad", relayTri === "bad");
  d.title = relayTri === "ok" ? "Relay connected"
    : relayTri === "warn" ? "Connecting to the relay\u2026"
    : relayTri === "bad" ? "Relay unreachable for more than 15s" : "";
}
// 0.7.8: a document with no MoQ connection AND no live proxy (the Relay
// page; the shell with no Go Live tab) probes the in-use relay over HTTP
// instead of sitting on an eternally neutral badge. "Reachable" is what
// such a page can honestly claim -- same 15s red rule as the real light.
// A CORS fetch, not no-cors: these pages are cross-origin isolated
// (COEP require-corp), which rejects opaque responses outright. The
// relay serves CORS on /certificate.sha256 -- the WebTransport library
// fetches it from these same pages.
let reach = { relay: null, lastOk: 0, started: 0 };
// 0.19.0: a WEB RELAY (https://name/relay) is reached through its KASTR's web port: probe the
// origin's /api/instance, and a loopback spelling handed out behind a tunnel means "this origin".
function isLoopHost(h) { return /^(localhost|127\.0\.0\.1|\[::1\])$/.test(h); }   // hoisted: used above this line
function webRelayFix(u) {
  try {
    const x = new URL(u);
    if (/^\/relay\/?$/.test(x.pathname) && isLoopHost(x.hostname) && !isLoopHost(location.hostname)) return location.origin + "/relay";
  } catch {}
  return u;
}
function relayProbeUrl(u) {
  try { const x = new URL(u); if (/^\/relay\/?$/.test(x.pathname)) return x.origin + "/api/instance"; } catch {}
  return String(u || "").replace(/\/+$/, "") + "/certificate.sha256";
}
async function probeRelayReachable() {
  if (typeof window.__relayHealth === "function") return;   // real signal exists
  let relay = null;
  try {
    const inst = await fetch("/api/instance", { cache: "no-store" }).then((r) => r.json());
    relay = inst.relay ? webRelayFix(inst.relay) : null;   // 0.19.0
  } catch {}
  if (!relay) return;
  if (reach.relay !== relay) reach = { relay, lastOk: 0, started: Date.now() };
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 2000);
    const r = await fetch(relayProbeUrl(relay),   // 0.19.0: a web relay answers at its origin
      { cache: "no-store", signal: ctl.signal });
    clearTimeout(t);
    if (r.ok) reach.lastOk = Date.now();
  } catch {}
}
setInterval(probeRelayReachable, 5000);
probeRelayReachable();

function computeRelayHealth() {
  let tri = null;
  if (typeof window.__relayHealth === "function") {
    let s = "disconnected";
    try { s = window.__relayHealth() || "disconnected"; } catch {}
    if (s === "connected") { relayDownSince = null; tri = "ok"; }
    else {
      if (relayDownSince === null) relayDownSince = Date.now();
      tri = Date.now() - relayDownSince > 15000 ? "bad" : "warn";
    }
  } else if (typeof window.__relayHealthProxy === "function") {
    relayDownSince = null;
    try { tri = window.__relayHealthProxy() ?? null; } catch { tri = null; }
  } else {
    relayDownSince = null;
  }
  if (tri === null && reach.started) {
    // Reachability fallback: green while responses arrive, red after 15s
    // of silence, yellow in between (including the very first checks).
    const since = reach.lastOk || reach.started;
    tri = reach.lastOk && Date.now() - reach.lastOk < 12000 ? "ok"
        : Date.now() - since > 15000 ? "bad" : "warn";
  }
  relayTri = tri;
  paintHealthDot();
}
window.__relayHealthTri = () => relayTri;
setInterval(computeRelayHealth, 2000);
computeRelayHealth();

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", build, { once: true });
} else {
  build();
}

// Tell the launcher this window is still open. It cannot trust the browser
// process it spawned: Chrome hands the URL to an instance already holding the
// profile and the spawned process exits immediately, which is indistinguishable
// from the operator closing the window. Pinging from the page is unambiguous and
// behaves the same on Windows, macOS and Linux.
//
// Only the top document pings, so the shell's iframes don't multiply it.
// Report what this page is doing to its own server, so a fault can be read
// instead of guessed at from the outside. Local only: the same loopback
// server that served this page, and nothing is stored on disk.
setInterval(() => {
  if (IS_WEB) return;   // 0.17.0: diagnostics are the host window's (the server refuses them anyway)
  let snap;
  try {
    snap = {
      page: location.pathname + location.search,
      version: VERSION,
      visibility: document.visibilityState,
      publisher: window.__publisher?.state?.() ?? null,
      watcher: window.__switcher?.state?.() ?? null,
    };
    if (!snap.publisher && !snap.watcher) return;   // nothing to say
    fetch("/api/diag", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(snap),
      keepalive: true,
    }).catch(() => {});
  } catch {}
}, 3000);

// Remember where this window is, because the browser does not restore an
// app window's bounds. Reported on change so the launcher can put it back.
if (window.top === window && !IS_WEB) {   // 0.17.0: a phone's geometry is not the host window's
  let lastGeom = "";
  const reportGeometry = () => {
    try {
      // Maximized is a state, not a size: restoring the literal bounds of a
      // maximized window gives you an almost-maximized one.
      const maximized =
        Math.abs(window.outerWidth - screen.availWidth) < 24 &&
        Math.abs(window.outerHeight - screen.availHeight) < 24;
      const geom = {
        x: window.screenX, y: window.screenY,
        w: window.outerWidth, h: window.outerHeight,
        maximized,
      };
      const key = JSON.stringify(geom);
      if (key === lastGeom) return;
      lastGeom = key;
      fetch("/api/window", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: key,
        keepalive: true,
      }).catch(() => {});
    } catch {}
  };
  addEventListener("resize", reportGeometry);
  setInterval(reportGeometry, 2000);      // catches moves, which have no event
  reportGeometry();
}

if (window.top === window && !IS_WEB) {   // 0.17.0: a web client must not keep a closed KASTR alive (nor be closed by its 205)
  const beat = () => {
    // keepalive so a ping in flight during teardown still lands.
    // 0.8.8: 205 = the launcher is relaunching for an update -- close this
    // window ourselves (the honest way; the launcher insists if we cannot).
    fetch("/api/alive", { method: "POST", cache: "no-store", keepalive: true })
      .then((r) => { if (r.status === 205) { try { window.close(); } catch {} } })
      .catch(() => {});
  };
  beat();
  setInterval(beat, 5000);
  // Background windows get their timers throttled hard, so also ping whenever
  // the window is touched or refocused.
  document.addEventListener("visibilitychange", () => { if (!document.hidden) beat(); });
}
