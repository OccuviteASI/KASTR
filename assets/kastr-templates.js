// 0.21.92 (Kenton, 2026-10-23 design review; 2026-10-27: "Having these options to setup the room how I want with whatever presenter
// options are available"): MEETING TEMPLATES, phase 1 "by hand" -- the page half (the hub half is kastr_templates.py; the relay
// a page calls checks its token and a spoke forwards to the hub).
//
// A TEMPLATE is a saved snapshot of how a room is set up, in sections: Layout & view (the room board + whether it starts on the
// spotlight or the gallery), Streams & cameras (what the board pulls in from other rooms and the library), Presentation & roles
// (deck, slide, presenters + backstage, audience rule, mode: "Ready, with a Start button" for the main presenter), Room settings (the code's DIGEST only -- the hub
// takes it from the room record, never from a page), Invites (people by name, an invite link made fresh at apply, My room's
// people with access) and -- personal templates only -- My view (this device's own grid layouts, pins, panels, gallery).
// WHERE: More > Templates... ("This room" and "Mine"), Room settings' Templates row, a room card's right-click "Apply template...",
// the My room dialog. WHO: everyone in the room sees and previews this room's templates; room admins save / edit / delete; publishers
// apply layout and streams (admins only while the view is locked); settings and invites need a room admin. Every item is
// re-checked at the hub against the applier's own rights -- skipped items come back with a reason. NEVER on a relay without
// access codes (Kenton). Undo: the toast after an apply (10 minutes, the device that applied it).
(() => {
  "use strict";
  if (window.__tplUI) return;
  const K = window.__ktpl;   // the page's bridge (moq-watch-lite.html)
  if (!K) return;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const toast = (m, ms, level, action) => { try { window.__toast?.(m, ms || 5000, { level: level || "event", action }); } catch {} };
  const plural = (n, one, many) => n + " " + (n === 1 ? one : (many || one + "s"));
  const SEC = { layout: "Layout & view", streams: "Streams & cameras", pres: "Presentation & roles", settings: "Room settings", invites: "Invites", view: "My view" };
  const SEC_ORDER = ["layout", "streams", "pres", "settings", "invites", "view"];
  const TTL = { 3600: "1-hour", 86400: "24-hour", 604800: "7-day" };
  const available = () => { try { return K.secured() && K.joined() && !K.guest(); } catch { return false; } };   // never on an open relay
  const trace = [];
  const T = (ev, o) => { trace.push(Object.assign({ t: Date.now(), ev }, o || {})); if (trace.length > 200) trace.splice(0, 50); };
  const ago = (s) => { const d = Math.max(0, Date.now() / 1000 - Number(s || 0)); return d < 90 ? "just now" : d < 5400 ? Math.round(d / 60) + " min ago" : d < 129600 ? Math.round(d / 3600) + " h ago" : Math.round(d / 86400) + " days ago"; };

  // ---- the look (scoped to these dialogs) ----------------------------------------------------------------------------------
  const css = document.createElement("style");
  css.id = "kTplCss";
  css.textContent = `
  .kt-scrim { position:fixed; inset:0; z-index:139; background:rgba(3,5,10,.62); display:flex; align-items:center; justify-content:center; padding:16px; }
  .kt-scrim[hidden] { display:none; }
  .kt-scrim.kt-top { z-index:141; }
  .kt-scrim .popcard.ktdlg { position:static; width:min(560px, calc(100vw - 32px)); max-height:calc(100dvh - 32px); display:flex; flex-direction:column; animation:kcIn .14s ease-out; }
  .ktdlg .body { padding:12px 16px 6px; overflow-y:auto; display:flex; flex-direction:column; gap:12px; font-size:12.5px; color:var(--text-dim); }
  .ktdlg .lbl { font-size:11px; color:var(--text-dim); text-transform:uppercase; letter-spacing:.06em; }
  .ktdlg .hint { margin:0; font-size:11.5px; line-height:1.45; color:var(--text-mute); }
  .ktdlg .msg { margin:0; min-height:16px; font-size:12px; color:var(--text-dim); }
  .ktdlg .msg.err { color:var(--asi-red); }
  .ktdlg .foot { display:flex; align-items:center; gap:8px; padding:10px 16px 14px; flex-wrap:wrap; }
  .ktdlg .foot .sp { flex:1; }
  .ktdlg button.ghost, .ktbox button.ghost { background:transparent; border:1px solid var(--line); color:var(--text-dim); font-weight:500; }
  .ktdlg button.ghost:hover, .ktbox button.ghost:hover { border-color:var(--asi-blue); color:var(--text); background:transparent; }
  .ktdlg button.danger { background:transparent; border:1px solid var(--asi-red); color:var(--asi-red); }
  .ktdlg input[type=text], .ktdlg textarea, .ktdlg select { background:var(--surface-2); border:1px solid var(--line); color:var(--text); border-radius:6px; padding:6px 8px; font:inherit; font-size:13px; min-width:0; }
  .ktdlg textarea { resize:vertical; min-height:38px; }
  .ktdlg input:focus, .ktdlg textarea:focus, .ktdlg select:focus { outline:none; border-color:var(--asi-blue); }
  .ktdlg input.masked { -webkit-text-security:disc; }
  .ktdlg .field { display:flex; flex-direction:column; gap:5px; }
  .ktdlg .row2 { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .ktdlg .row2 > input, .ktdlg .row2 > select { flex:1; }
  .kttabs { display:flex; gap:6px; }
  .kttab { flex:1; background:transparent; border:1px solid var(--line); color:var(--text-dim); font-weight:500; }
  .kttab.on { border-color:var(--asi-blue); color:var(--text); background:color-mix(in srgb, var(--asi-blue) 16%, var(--surface)); }
  .ktlist { display:flex; flex-direction:column; gap:6px; }
  .ktrow { display:flex; gap:10px; align-items:flex-start; background:var(--surface-2); border:1px solid var(--line); border-radius:8px; padding:9px 10px; }
  .ktrow .ktm { flex:1; min-width:0; display:flex; flex-direction:column; gap:2px; }
  .ktrow .ktn { color:var(--text); font-weight:600; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .ktrow .ktnote { color:var(--text-dim); font-size:12px; }
  .ktrow .ktc { color:var(--text-mute); font-size:11.5px; line-height:1.45; }
  .ktrow .ktb { display:flex; gap:6px; flex:none; align-items:center; }
  .ktrow .ktb button { height:28px; padding:0 10px; font-size:12px; }
  .ktrow .ktb .more { width:28px; padding:0; }
  .ktbadge { display:inline-block; font-size:10.5px; padding:0 6px; border-radius:9px; border:1px solid var(--line); color:var(--text-dim); margin-left:6px; vertical-align:1px; font-weight:500; }
  .ktempty { margin:0; font-size:12.5px; color:var(--text-mute); padding:10px 2px; line-height:1.5; }
  .ktsecs { display:flex; flex-direction:column; gap:6px; }
  .ktsec { display:flex; gap:10px; align-items:flex-start; border:1px solid var(--line); border-radius:8px; padding:8px 10px; background:var(--surface-2); }
  .ktsec.off { opacity:.55; }
  .ktsec > .switch { margin-top:1px; }
  .ktsw { display:inline-flex; flex-direction:row; align-items:center; gap:6px; font-size:11.5px; color:var(--text-dim); cursor:pointer; user-select:none; padding:2px 8px 2px 2px; }
  .ktsw.on { color:var(--text); }
  .ktsw.dim { opacity:.45; cursor:default; }
  .ktsec .ktsm { flex:1; min-width:0; display:flex; flex-direction:column; gap:3px; }
  .ktsec .ktst { color:var(--text); font-weight:600; font-size:12.5px; }
  .ktsec .ktsc { color:var(--text-dim); font-size:12px; line-height:1.45; }
  .ktsec .ktsx { display:flex; gap:6px; flex-wrap:wrap; align-items:center; margin-top:3px; }
  .ktchip { display:inline-flex; align-items:center; gap:4px; font-size:11.5px; padding:2px 8px; border-radius:12px; border:1px solid var(--line); color:var(--text-dim); background:var(--surface); cursor:pointer; user-select:none; }
  .ktchip.on { border-color:var(--asi-blue); color:var(--text); background:color-mix(in srgb, var(--asi-blue) 18%, var(--surface)); }
  .ktchip .x { color:var(--text-mute); font-weight:700; }
  .ktseg { display:inline-flex; border:1px solid var(--line); border-radius:7px; overflow:hidden; }
  .ktseg button { background:transparent; color:var(--text-dim); border:0; border-radius:0; height:28px; padding:0 12px; font-weight:500; }
  .ktseg button.on { background:var(--asi-blue); color:var(--on-accent, #fff); }
  .ktprev { display:flex; flex-direction:column; gap:8px; border:1px solid var(--line); border-radius:8px; padding:10px; background:var(--surface-2); }
  .ktprev .ktsum { color:var(--text); font-size:13px; line-height:1.5; }
  .ktprev ul { margin:0; padding-left:18px; display:flex; flex-direction:column; gap:2px; font-size:12px; }
  .ktcams { display:flex; flex-direction:column; gap:4px; }
  .ktcam { display:flex; gap:8px; align-items:center; font-size:12px; }
  .ktcam .nm { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--text); }
  .ktcam select { font-size:12px; padding:3px 6px; max-width:48%; }
  .ktstat { font-size:10.5px; padding:1px 7px; border-radius:9px; border:1px solid var(--line); white-space:nowrap; }
  .ktstat.live { border-color:var(--asi-green, #2fbf71); color:var(--asi-green, #2fbf71); }
  .ktstat.offline { border-color:var(--asi-amber); color:var(--asi-amber); }
  .ktstat.missing { border-color:var(--asi-red); color:var(--asi-red); }
  .ktstat.moved { border-color:var(--asi-blue); color:var(--asi-blue); }
  .ktstat.out { color:var(--text-mute); }
  .ktnotes { border-left:3px solid var(--asi-amber); padding:4px 0 4px 10px; display:flex; flex-direction:column; gap:3px; font-size:12px; }
  .ktnotes b { color:var(--text); font-weight:600; }
  .ktbox { display:flex; flex-direction:column; gap:6px; }
  .ktbox .ktline { display:flex; align-items:center; gap:8px; font-size:12.5px; color:var(--text); background:var(--surface-2); border:1px solid var(--line); border-radius:6px; padding:5px 6px 5px 10px; }
  .ktbox .ktline span { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .ktbox .ktline button { height:26px; padding:0 10px; font-size:12px; }
  .ktbox .ktacts { display:flex; gap:6px; flex-wrap:wrap; }
  .ktitems { display:flex; flex-wrap:wrap; gap:5px; }
  details.ktdet summary { cursor:pointer; color:var(--text-dim); font-size:12px; }
  @media (max-width:640px) {
    .kt-scrim { padding:0; align-items:stretch; }
    .kt-scrim .popcard.ktdlg { width:100vw; max-height:100dvh; height:100dvh; border-radius:0; }
    .ktrow { flex-direction:column; }
    .ktrow .ktb { align-self:stretch; justify-content:flex-end; }
  }`;
  document.head.appendChild(css);

  // ---- the hub, through this page's relay --------------------------------------------------------------------------------
  let mineStale = false;   // the remembered My room code was refused -- ask for it instead of sending it again
  let mineCode = "";       // a code typed in this session (memory only; never stored by this module)
  function ident() {
    const p = K.personal();
    const name = String(p?.name || K.me() || "").trim();
    const code = mineCode || (mineStale ? "" : String(p?.code || ""));
    return name && code ? { pname: name, pcode: code } : null;
  }
  async function call(body, slug, mine) {
    const base = K.base();
    if (!base) return { ok: false, error: "No relay to talk to." };
    slug = slug || K.room();
    let tok = "";
    try { tok = await K.tokenFor(slug); } catch (e) { return { ok: false, error: "Could not open " + K.title(slug) + ": " + (e?.message || e) }; }
    if (!tok) return { ok: false, error: "Join a room first." };
    const b = { ...body, by: K.me() || undefined, roomKey: K.roomKey(slug) };
    if (mine) { const id = ident(); if (id) Object.assign(b, id); }
    T("call", { op: body.op, slug, mine: !!mine });
    try {
      const r = await fetch(base + "/api/templates", { method: "POST", headers: { "content-type": "application/json", authorization: "Bearer " + tok }, body: JSON.stringify(b) });
      const d = await r.json().catch(() => ({}));
      if ((r.status === 404 || r.status === 503) && !d.ok && !d.hubDown && !/template/i.test(String(d.error || ""))) return { ok: false, old: true, error: "This relay has no templates (an older KASTR, or a relay without access codes)." };
      if (d.wrong) { mineStale = true; mineCode = ""; }
      if (r.ok) return { ...d, ok: d.ok !== false };
      return { ...d, ok: false, status: r.status, error: String(d.error || ("HTTP " + r.status)).replace(/ -- /g, " — ") };
    } catch (e) { return { ok: false, error: String(e?.message || e) }; }
  }
  const pathRoom = (p) => String(p || "").split("/", 1)[0];
  function roomsOf(t) {   // the rooms a template's streams come from (proof tokens: "I can see that room")
    const out = new Set();
    for (const c of t?.streams?.cams || []) out.add(pathRoom(c.path));
    const lay = t?.layout || {};
    for (const p of lay.pins || []) out.add(pathRoom(p.path));
    for (const x of [...(lay.spots || []), ...(lay.split || []), ...Object.keys(lay.grids || {})]) out.add(pathRoom(x));
    for (const g of Object.values(lay.customGrids || {})) for (const s of g.slots || []) for (const c of s.cams || []) out.add(pathRoom(c));
    if (t?.scope === "room" && t.room) out.add(t.room);
    out.delete("lib");
    return [...out].filter((r) => r && (!K.isPersonal(r) || r === K.personal()?.slug));
  }
  async function proofs(t, target) {
    const out = {};
    await Promise.all(roomsOf(t).filter((r) => r !== target).slice(0, 16).map(async (r) => { try { const tk = await K.tokenFor(r); if (tk) out[r] = tk; } catch {} }));
    return out;
  }

  // ---- words -----------------------------------------------------------------------------------------------------------
  function words(sec, c) {
    c = c || {};
    const list = (a) => a.filter(Boolean).join(", ");
    if (sec === "layout") return list([c.pins && plural(c.pins, "pin"), c.spots && plural(c.spots, "spotlight"), c.grids && plural(c.grids, "grid layout"),
      c.cgrids && plural(c.cgrids, "room grid"), c.split && plural(c.split, "split camera"), c.start && ("starts on the " + c.start)]) || "nothing pinned or spotlit";
    if (sec === "streams") return c.cams ? plural(c.cams, "camera") + (c.foreign || c.lib ? " (" + list([c.foreign && c.foreign + " from other rooms", c.lib && c.lib + " from the library"]) + ")" : "") : "no cameras";
    if (sec === "settings") return list([c.locked ? "locked" : "unlocked", c.keep && "kept open", c.viewLock && "view locked", c.group && ("group " + c.group)]);
    if (sec === "invites") return list([c.people && plural(c.people, "person", "people") + " to invite", c.link && "an invite link", c.access && plural(c.access, "person", "people") + " with access"]) || "nobody";
    if (sec === "pres") return list([c.deck ? "a deck" + (c.slides ? " (" + plural(c.slides, "slide") + ")" : "") : "", c.presenters && plural(c.presenters, "presenter"), c.backstage && plural(c.backstage, "backstage person", "backstage people"), c.mode && (MODE_WORD[c.mode] || c.mode)]) || "presenter options";
    if (sec === "view") return list([c.grids && plural(c.grids, "grid layout"), c.pins && plural(c.pins, "pin"), c.dock && plural(c.dock, "pinned panel"), c.mode && c.mode]) || "your own view";
    return "";
  }
  const countsLine = (t) => SEC_ORDER.filter((s) => t?.on?.[s] !== undefined).map((s) => (t.on[s] ? "" : "(off) ") + SEC[s] + ": " + words(s, t.counts?.[s])).join(" · ");

  // ---- local counts for the Save dialog (live: what the room has now) --------------------------------------------------
  async function boardOf(slug) {
    if (slug === K.room()) { const b = K.board(); if (b) return b; }
    try {
      const tok = await K.tokenFor(slug);
      const r = await fetch(K.base() + "/api/rooms/board?room=" + encodeURIComponent(slug), { headers: { authorization: "Bearer " + tok }, cache: "no-store" });
      const d = await r.json();
      return d?.ok ? d : { pins: [], spots: [], grids: {}, split: [], customGrids: {} };
    } catch { return { pins: [], spots: [], grids: {}, split: [], customGrids: {} }; }
  }
  function boardCounts(b, slug) {
    const cams = new Map();
    const add = (p, how) => { p = String(p || ""); if (!p.endsWith(".hang") || p.split("/")[1] === "cgrid-0000") return; const x = cams.get(p) || { p, how: new Set() }; x.how.add(how); cams.set(p, x); };
    for (const p of b.pins || []) add(p.path, "pin");
    for (const s of b.spots || []) add(s.target, "spot");
    for (const gp of Object.keys(b.grids || {})) add(gp, "grid");
    for (const g of Object.values(b.customGrids || {})) for (const s of g.slots || []) for (const c of s.cams || []) add(c, "cgrid");
    for (const m of b.split || []) add(m, "split");
    const all = [...cams.values()];
    return {
      layout: { pins: (b.pins || []).length, spots: (b.spots || []).length, grids: Object.keys(b.grids || {}).length, cgrids: Object.keys(b.customGrids || {}).length, split: (b.split || []).length },
      streams: { cams: all.length, foreign: all.filter((x) => pathRoom(x.p) !== slug && pathRoom(x.p) !== "lib").length, lib: all.filter((x) => pathRoom(x.p) === "lib").length },
    };
  }

  // ---- shared dialog shell ---------------------------------------------------------------------------------------------
  function shell(id, title, top) {
    const el = document.createElement("div");
    el.id = id; el.className = "kt-scrim" + (top ? " kt-top" : ""); el.hidden = true;
    el.innerHTML = '<div class="popcard ktdlg" role="dialog" aria-modal="true"><div class="head"><span class="ttl">' + esc(title) + '</span><span class="sp"></span><button type="button" class="close" title="Close">✕</button></div>'
      + '<div class="body"></div><div class="foot"></div></div>';
    document.body.appendChild(el);
    const close = () => { el.hidden = true; document.removeEventListener("keydown", el.__key, true); try { el.__onclose?.(); } catch {} };
    el.__close = close;
    el.__key = (e) => {
      if (e.key === "Escape") { if (document.getElementById("kConfirm") && !document.getElementById("kConfirm").hidden) return; e.preventDefault(); e.stopPropagation(); close(); }
      else if (e.key !== "Tab" && el.contains(e.target)) e.stopPropagation();   // the page's shortcuts stay quiet while typing here
    };
    el.querySelector(".close").onclick = close;
    el.addEventListener("click", (e) => { if (e.target === el) close(); });
    el.__open = () => { el.hidden = false; document.addEventListener("keydown", el.__key, true); };
    el.__body = el.querySelector(".body"); el.__foot = el.querySelector(".foot"); el.__title = el.querySelector(".ttl");
    return el;
  }
  const btn = (text, cls, fn) => { const b = document.createElement("button"); b.type = "button"; if (cls) b.className = cls; b.textContent = text; if (fn) b.onclick = fn; return b; };
  const div = (cls, html) => { const d = document.createElement("div"); if (cls) d.className = cls; if (html != null) d.innerHTML = html; return d; };

  // ======================================================================================================================
  // THE LIST: More > Templates... -- "This room" and "Mine"
  // ======================================================================================================================
  let listEl = null;
  const L = { slug: "", tab: "room", d: null, busy: false };
  async function openList(slug, tab) {
    if (!available()) { toast("Templates need a relay with access codes — join a room there first.", 5000, "warn"); return; }
    K.closePops();
    if (!listEl) listEl = shell("kTpl", "Templates");
    L.slug = slug || K.room(); L.tab = tab || "room"; L.d = null;
    listEl.__open();
    paintList();
    await loadList();
  }
  async function loadList() {
    L.busy = true; paintList();
    L.d = await call({ op: "list" }, L.slug, true);
    L.busy = false;
    T("list", { ok: L.d.ok, n: (L.d.templates || []).length, mine: L.d.mine ? L.d.mine.length : null });
    paintList();
  }
  function tplRow(t, d, slug) {
    const row = div("ktrow");
    const deck = t.deckFile ? '<span class="ktbadge">deck</span>' : "";
    row.innerHTML = '<div class="ktm"><span class="ktn">' + esc(t.name) + deck + '</span>' + (t.note ? '<span class="ktnote">' + esc(t.note) + '</span>' : "")
      + '<span class="ktc">' + esc(countsLine(t)) + '</span><span class="ktc">' + esc((t.by ? "by " + t.by + " · " : "") + "updated " + ago(t.upd || t.at)) + '</span></div><div class="ktb"></div>';
    const b = row.querySelector(".ktb");
    const canApply = !!d?.can?.apply || t.scope === "me";
    b.append(btn(canApply ? "Preview & apply…" : "Preview…", canApply ? "" : "ghost", () => openApply(t, slug)));
    const edits = t.scope === "me" ? true : !!d?.can?.save;
    if (edits) {
      const m = btn("⋯", "ghost more");
      m.title = "Edit, update from the room, delete";
      m.onclick = () => K.menu(m, [{ value: "edit", label: "Edit…" }, { value: "resnap", label: "Update from this room" }, { sep: true }, { value: "del", label: "Delete…" }],
        (v) => { if (v === "edit") openEdit(t, slug); else if (v === "resnap") resnap(t, slug); else if (v === "del") del(t, slug); });
      b.append(m);
    }
    return row;
  }
  function paintList() {
    if (!listEl) return;
    const d = L.d;
    listEl.__title.textContent = "Templates — " + K.title(L.slug);
    const body = listEl.__body, foot = listEl.__foot;
    body.replaceChildren(); foot.replaceChildren();
    const tabs = div("kttabs");
    for (const [k, t] of [["room", "This room"], ["mine", "Mine"]]) {
      const b = btn(t, "kttab" + (L.tab === k ? " on" : ""), () => { L.tab = k; paintList(); });
      b.dataset.tab = k;
      tabs.append(b);
    }
    body.append(tabs);
    const list = div("ktlist");
    body.append(list);
    const msg = document.createElement("p"); msg.className = "msg";
    if (L.busy && !d) { msg.textContent = "Loading…"; body.append(msg); }
    else if (d && !d.ok && !d.templates) { msg.textContent = d.error || "Could not load the templates."; msg.classList.add("err"); body.append(msg); }
    if (L.tab === "room") {
      const rows = d?.templates || [];
      if (d && d.personal) list.append(div("ktempty", "My room keeps personal templates only — see <b>Mine</b>."));
      else if (d && !rows.length && !L.busy) list.append(div("ktempty", "No templates for " + esc(K.title(L.slug)) + " yet. " + (d.can?.save ? "Save how it is set up now with <b>Save this room as a template…</b>" : "A room admin (the admin code or the room’s creator) saves them; everyone here can look at them and preview them.")));
      for (const t of rows) list.append(tplRow(t, d, L.slug));
      if (d?.ok && !d.can?.apply && rows.length) body.append(div("hint", "You can look at these and preview them. Applying one needs the publisher code" + (d.viewLock ? " (an admin, while the view is locked)" : "") + "."));
      if (d?.can?.save) foot.append(btn("Save this room as a template…", "", () => openSave(L.slug, "room")));
    } else {
      if (d && d.mine === null) list.append(mineGate(() => loadList()));
      for (const t of d?.mine || []) list.append(tplRow(t, d, L.slug));
      if (d?.mine && !d.mine.length) list.append(div("ktempty", "No templates of your own yet. Save a room’s set-up — with your own view — under <b>Just me</b>; it follows you to any device (your name and My room code)."));
      if (d?.mine) foot.append(btn("Save as my template…", "", () => openSave(L.slug, "me")));
    }
    foot.append(div("sp"), btn("Close", "ghost", () => listEl.__close()));
  }
  function mineGate(done) {   // name + My room code -> this session may open my templates (the code is only held in memory here)
    const box = div("ktbox");
    const p = K.personal();
    box.innerHTML = '<p class="hint">Your templates follow you to any device, under your name and your <b>My room</b> code.' + (p ? "" : " You have no My room on this device yet.") + '</p>'
      + '<div class="row2"><input type="text" class="ktpn" maxlength="48" placeholder="Your name" aria-label="Your name"><input type="text" class="ktpc masked" placeholder="My room code" aria-label="My room code" autocomplete="off"></div>'
      + '<div class="ktacts"></div><p class="msg"></p>';
    box.querySelector(".ktpn").value = String(p?.name || K.me() || "");
    const go = async () => {
      const name = box.querySelector(".ktpn").value.trim(), code = box.querySelector(".ktpc").value;
      if (!name || !code) { box.querySelector(".msg").textContent = "Your name and your My room code."; return; }
      mineCode = code; mineStale = false;
      try { localStorage.setItem("kastr.operator.name", localStorage.getItem("kastr.operator.name") || name); } catch {}
      const d = await call({ op: "list", pname: name, pcode: code }, L.slug, false);
      if (d.mine) { L.d = d; paintList(); done?.(); return; }
      mineCode = "";
      box.querySelector(".msg").textContent = d.error || "Refused."; box.querySelector(".msg").classList.add("err");
    };
    box.querySelector(".ktpc").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
    box.querySelector(".ktacts").append(btn("Open my templates", "", go), ...(p ? [] : [btn("Make My room…", "ghost", () => { listEl?.__close(); K.myRoomDialog(); })]));
    return box;
  }
  async function del(t, slug) {
    if (!(await K.confirm({ title: "Delete template", message: "Delete “" + t.name + "”?", detail: t.deckFile ? "Its deck is deleted from the hub too." : "Nothing in the room changes.", ok: "Delete", danger: true }))) return;
    const d = await call({ op: "delete", id: t.id }, slug, t.scope === "me");
    if (!d.ok) { toast("Templates: " + d.error, 6000, "warn"); return; }
    toast("Deleted “" + t.name + "”", 3000);
    refreshAll();
  }
  async function resnap(t, slug) {
    const ps = slug === K.room() && t.on?.pres !== false ? presSnap() : null;   // a deck I run here now: its presentation is taken again too
    if (!(await K.confirm({ title: "Update template", message: "Update “" + t.name + "” from " + K.title(slug) + " as it is now?",
      detail: ps ? "Its layout, streams, room settings and presentation (“" + ps.name + "”, its slide, roles and audience rules) are taken again; its name, note and invites stay."
        : "Its layout, streams and room settings are taken again; its name, note, invites and presentation stay.", ok: "Update" }))) return;
    const body = { op: "update", id: t.id, resnap: true, start: K.start() };
    if (ps) { body.pres = presFromSnap(ps); body.add = ["pres"]; }
    const d = await call(body, slug, t.scope === "me");
    if (!d.ok) { toast("Templates: " + d.error, 6000, "warn"); return; }
    if (ps && ps.file) {
      const up = await deckUpload(d.template || t, ps, slug, null);
      if (!up.ok) { toast("Updated, but the deck was not kept: " + (up.error || "refused"), 7000, "warn"); refreshAll(); return; }
    }
    T("resnap", { id: t.id, pres: !!ps, deck: !!(ps && ps.file) });
    toast("Updated “" + t.name + "” from " + K.title(slug), 3000);
    refreshAll();
  }
  function refreshAll() {
    if (listEl && !listEl.hidden) loadList();
    if (rsBox?.isConnected) roomSettings(rsBox, rsSlug);
    if (pmBox?.isConnected) myRoom(pmBox, true);
  }

  // ======================================================================================================================
  // 0.21.92 (Kenton): every on/off option is a toggle switch, never a plain checkbox or a lit chip.
  // The outer label gives the words + switch one click target; the span.switch is the page's own markup.
  const sw = (text, on, change, o = {}) => {
    const l = document.createElement("label"); l.className = "ktsw" + (on ? " on" : "") + (o.dim ? " dim" : "");
    l.innerHTML = '<span class="switch sm"><input type="checkbox"><i></i></span><span></span>';
    l.lastChild.textContent = text; if (o.title) l.title = o.title;
    const cb = l.querySelector("input"); cb.checked = !!on; cb.disabled = !!o.disabled; cb.setAttribute("aria-label", text);
    if (o.sec) { cb.dataset.sec = o.sec; l.dataset.sec = o.sec; }
    cb.onchange = () => { const v = change(cb.checked); if (v === false) { cb.checked = !cb.checked; return; } l.classList.toggle("on", cb.checked); };
    return l;
  };
  const SWITCH = '<label class="switch sm"><input type="checkbox"><i></i></label>';
  // SAVE: name, note, This room / Just me, a switch per section with live counts
  // ======================================================================================================================
  let saveEl = null;
  const S = { slug: "", scope: "room", on: {}, people: new Map(), link: 0, start: "spotlight", counts: null, view: null, access: true, rec: null };
  async function openSave(slug, scope) {
    if (!available()) return;
    K.closePops();
    if (!saveEl) saveEl = shell("kTplSave", "Save as a template", true);
    S.slug = slug || K.room(); S.scope = scope || "room"; S.people = new Map(); S.link = 0; S.start = K.start(); S.access = true;
    S.on = { layout: true, streams: true, pres: !!presSnap(), settings: true, invites: false, view: true };
    S.counts = null; S.view = K.view.snap(); S.rec = K.roomRec(S.slug);
    saveEl.__title.textContent = "Save " + K.title(S.slug) + " as a template";
    paintSave();
    saveEl.__open();
    try { saveEl.querySelector(".ktname").focus(); } catch {}
    const b = await boardOf(S.slug);
    S.counts = boardCounts(b, S.slug);
    paintSave(true);
  }
  function viewCounts(v) { return { grids: Object.keys(v?.grids || {}).length, pins: (v?.pins || []).length, dock: (v?.dock || []).length, mode: v?.mode || "" }; }
  function paintSave(keepFields) {
    const body = saveEl.__body, foot = saveEl.__foot;
    const name = keepFields ? saveEl.querySelector(".ktname")?.value || "" : "", note = keepFields ? saveEl.querySelector(".ktnote")?.value || "" : "";
    body.replaceChildren(); foot.replaceChildren();
    const personalRoom = K.isPersonal(S.slug);
    if (personalRoom) S.scope = "me";
    body.append(div("field", '<span class="lbl">Name</span><input type="text" class="ktname" maxlength="60" placeholder="e.g. Monday ops briefing" aria-label="Template name">'),
      div("field", '<span class="lbl">Note</span><textarea class="ktnote" maxlength="300" rows="2" placeholder="What it is for (optional)" aria-label="Note"></textarea>'));
    body.querySelector(".ktname").value = name; body.querySelector(".ktnote").value = note;
    const who = div("field", '<span class="lbl">Save for</span>');
    const seg = div("ktseg");
    for (const [k, t] of [["room", "This room"], ["me", "Just me"]]) {
      const b = btn(t, S.scope === k ? "on" : "", () => { S.scope = k; paintSave(true); });
      b.dataset.scope = k;
      if (k === "room" && (personalRoom || !canSaveRoom())) { b.disabled = true; b.title = personalRoom ? "My room keeps personal templates only" : "Only a room admin (the admin code or the room's creator) saves this room's templates"; }
      seg.append(b);
    }
    who.append(seg, div("hint", S.scope === "room" ? "Everyone in " + esc(K.title(S.slug)) + " sees it; room admins edit it." : "Only you see it — on any device, under your name and My room code. It can also keep your own view of the room."));
    body.append(who);
    const c = S.counts, rec = S.rec;
    const secs = div("ktsecs");
    const sec = (k, text, extra, disabled, why) => {
      const r = div("ktsec" + (S.on[k] && !disabled ? "" : " off"));
      r.innerHTML = SWITCH + '<div class="ktsm"><span class="ktst">' + esc(SEC[k]) + '</span><span class="ktsc">' + esc(text) + '</span>' + (why ? '<span class="hint">' + esc(why) + '</span>' : "") + '</div>';
      const cb = r.querySelector("input"); cb.setAttribute("aria-label", SEC[k]);
      cb.checked = !!S.on[k] && !disabled; cb.disabled = !!disabled; cb.dataset.sec = k;
      cb.onchange = () => { S.on[k] = cb.checked; r.classList.toggle("off", !cb.checked); };
      if (extra) r.querySelector(".ktsm").append(extra);
      secs.append(r);
    };
    const startSel = div("ktsx", '<span class="hint">Starts on</span>');
    const ss = document.createElement("select"); ss.innerHTML = '<option value="spotlight">the spotlight</option><option value="gallery">the gallery</option>'; ss.value = S.start; ss.onchange = () => { S.start = ss.value; };
    startSel.append(ss);
    sec("layout", c ? words("layout", c.layout) : "Counting…", startSel);
    sec("streams", c ? words("streams", c.streams) : "Counting…", null, false, "Box cameras are kept by the box and camera, library streams by their library name — so a camera that moved is still found.");
    S.pres = presSnap();
    sec("pres", S.pres ? presSnapWords(S.pres) : "Deck and starting slide, presenters and backstage, audience rules, presenter mode", null, !S.pres,
      S.pres ? "The deck is kept on the hub (encrypted) as the file it came from; applying the template gets it ready for the main presenter, who presses Start presenting."
        : "Present a deck here first (Share ▸ Presentation) — then its deck, slide, roles, audience rule and mode can be kept.");    if (!personalRoom) sec("settings", words("settings", { locked: rec.locked, keep: rec.keep, viewLock: rec.viewLock, group: rec.groupName || rec.group }), null, false, rec.locked ? "The room’s code is kept only as the hub keeps it (a salted digest) — never the code." : "");
    // invites: the people here now (switch on to invite them next time), an invite link made fresh at apply, My room's people with access
    const inv = div("ktsx");
    const here = K.peopleHere();
    for (const p of here) { if (!S.people.has(p.name.toLowerCase()) && S.people.__init !== true) S.people.set(p.name.toLowerCase(), { ...p, on: false }); }
    S.people.__init = true;
    for (const [k, p] of S.people) {
      inv.append(sw(p.name, p.on, (v) => { p.on = v; paintInvCount(); }, { title: "Invite " + p.name + " when this template is applied" }));
    }
    const add = btn("Add someone…", "ghost");
    add.style.height = "24px"; add.style.fontSize = "11.5px";
    add.onclick = async () => {
      const all = await K.people().catch(() => []);
      const items = all.filter((x) => !S.people.has(String(x.name).toLowerCase())).slice(0, 40).map((x) => ({ value: x.name, label: x.name + (x.online ? "" : " (offline)") }));
      if (!items.length) { toast("Nobody else to add.", 2500); return; }
      K.menu(add, items, (v) => { S.people.set(String(v).toLowerCase(), { name: v, host: "", on: true }); paintSave(true); });
    };
    inv.append(add);
    const ls = document.createElement("select");
    ls.innerHTML = '<option value="0">No invite link</option><option value="3600">An invite link for 1 hour</option><option value="86400">An invite link for 24 hours</option><option value="604800">An invite link for 7 days</option>';
    ls.value = String(S.link); ls.onchange = () => { S.link = Number(ls.value) || 0; paintInvCount(); };
    const invx = div("ktsx"); invx.append(ls);
    const invWrap = document.createElement("div"); invWrap.append(inv, invx);
    const invText = () => words("invites", { people: [...S.people.values()].filter((p) => p.on).length, link: !!S.link, access: personalRoom && S.access ? 1 : 0 }).replace(/^1 person with access$/, "the people with access");
    sec("invites", invText(), invWrap, false, "Invites are sent, and a fresh link is made, each time the template is applied (no link is kept).");
    function paintInvCount() { const t = secs.querySelector('[data-sec="invites"]')?.closest(".ktsec")?.querySelector(".ktsc"); if (t) t.textContent = invText(); }
    if (S.scope === "me") sec("view", words("view", viewCounts(S.view)), null, false, "Your own grid layouts, pins, pinned panels and gallery / speaker — put back on the device that applies it.");
    body.append(div("field", '<span class="lbl">Sections</span>'), secs);
    if (S.scope === "me" && !ident()) {
      const g = div("ktbox", '<p class="hint">Your templates are kept under your name and My room code.</p><div class="row2"><input type="text" class="ktpc masked" placeholder="My room code" aria-label="My room code" autocomplete="off"></div>');
      body.append(g);
    }
    const msg = document.createElement("p"); msg.className = "msg"; msg.setAttribute("role", "status"); body.append(msg);
    saveEl.__say = (t, bad) => { msg.textContent = t || ""; msg.classList.toggle("err", !!bad); };
    foot.append(div("sp"), btn("Cancel", "ghost", () => saveEl.__close()), btn("Save template", "ktgo", doSave));
  }
  function canSaveRoom() { const r = K.settingsRole(S.slug); return r === "creator" || r === "admin" || r === "operator"; }
  async function doSave() {
    const name = saveEl.querySelector(".ktname").value.trim();
    if (!name) { saveEl.__say("Give the template a name.", true); saveEl.querySelector(".ktname").focus(); return; }
    const pc = saveEl.querySelector(".ktpc");
    if (pc && pc.value) { mineCode = pc.value; mineStale = false; }
    const sections = Object.keys(S.on).filter((k) => S.on[k] && (k !== "pres" || !!S.pres) && (k !== "view" || S.scope === "me") && (k !== "settings" || !K.isPersonal(S.slug)));
    if (!sections.length) { saveEl.__say("Pick at least one section.", true); return; }
    const body = { op: "save", scope: S.scope, name, note: saveEl.querySelector(".ktnote").value.trim(), sections, start: S.start,
      invites: { people: [...S.people.values()].filter((p) => p.on).map((p) => ({ name: p.name, host: p.host || undefined })), link: S.link ? { ttl: S.link } : null },
      view: S.scope === "me" ? S.view : undefined, withAccess: S.access };
    const pres = sections.includes("pres") ? S.pres : null;
    if (pres) body.pres = presFromSnap(pres);
    saveEl.__say("Saving…");
    const go = saveEl.querySelector(".ktgo"); go.disabled = true;
    const d = await call(body, S.slug, S.scope === "me");
    if (!d.ok) { go.disabled = false; saveEl.__say(d.error || "Refused.", true); return; }
    if (pres && pres.file) {   // the deck goes to the hub's deck store (encrypted there) as the file it came from
      const up = await deckUpload(d.template, pres, S.slug, (pct) => saveEl.__say("Keeping the deck on the hub… " + pct + "%"));
      if (!up.ok) { go.disabled = false; saveEl.__say("Saved, but the deck was not kept: " + (up.error || "refused") + " — try Update from this room while presenting.", true); refreshAll(); return; }
      d.template = up.template || d.template;
    }
    go.disabled = false;
    saveEl.__close();
    T("saved", { id: d.template?.id, scope: S.scope, sections, deck: !!(pres && pres.file) });
    toast("Saved “" + name + "” — " + countsLine(d.template), 5000);
    refreshAll();
  }

  // ======================================================================================================================
  // PRESENTATION & ROLES (Kenton 2026-10-27: "Ready, with a Start button"): Save keeps the deck this page presents (the file it
  // came from, on the hub, encrypted at rest), its slide, presenters (main) and backstage with each one's "Can control my mic and
  // camera", "Audience muted", the presenter mode and the Reporter background. Apply gets it READY for the main presenter: their
  // page loads the deck and shows "Start presenting"; nothing goes live until they press it. Then the deck starts on its slide
  // with its mode, backdrop and audience rule, the people who are here get their roles, and the absent ones are named.
  // ======================================================================================================================
  const PART = 16 * 1024 * 1024;
  const presSnap = () => { try { const s = window.__pres?.tplSnap?.(); return s && s.n ? s : null; } catch { return null; } };
  const MODE_WORD = { content: "Content only", standout: "Standout", sbs: "Side-by-side", reporter: "Reporter" };
  // 0.21.91's two audience switches: "Audience muted" and (while muted) "Ask to speak"
  const audWords = (a) => (a && a.muted === false ? "audience may talk" : "audience muted" + (a && a.ask === false ? ", no asking" : ", Ask to speak on"));
  function presSnapWords(s) {
    const others = s.ps.filter((x) => !x.main).map((x) => x.name);
    return "“" + s.name + "” (" + plural(s.n, "slide") + ", from slide " + (s.idx + 1) + ")" + (s.file ? "" : " — roles only (this deck was handed to you)")
      + " · " + (others.length ? "presenters: you, " + others.join(", ") : "you present") + (s.bs.length ? " · backstage: " + s.bs.map((b) => b.name).join(", ") : "")
      + " · " + (MODE_WORD[s.cm] || s.cm) + " · " + audWords({ muted: !!s.am, ask: s.ask !== 0 });
  }
  function presFromSnap(s) {
    return { presenters: s.ps.map((x) => ({ name: x.name, main: !!x.main })), backstage: s.bs.map((b) => ({ name: b.name, control: b.control || [] })),
      audience: { muted: !!s.am, ask: s.ask !== 0 }, mode: s.cm, reporterBg: s.rbg || "", deck: { start: s.idx || 0 }, opts: { ...(s.o || {}) } };
  }
  // the deck-wide options (one table in kastr-pres.js: window.__pres.tplOpts); this list is only for a page without it
  const OPTS_FALLBACK = [{ key: "am", sw: true, text: "Audience muted", def: 1, needs: "" }, { key: "ask", sw: true, text: "Ask to speak", def: 1, needs: "am" }];
  const optRows = () => { try { const r = window.__pres?.tplOpts?.(); if (Array.isArray(r) && r.length) return r; } catch {} return OPTS_FALLBACK; };
  function presOpt(P, key, def) {   // a template's value for one option: opts first, then the named fields older templates have
    const o = P.opts || {};
    if (Object.prototype.hasOwnProperty.call(o, key)) return o[key];
    if (key === "am") return P.audience?.muted === false ? 0 : 1;
    if (key === "ask") return P.audience?.ask === false ? 0 : 1;
    if (key === "cm") return P.mode;
    if (key === "rbg") return P.reporterBg || undefined;
    return def;
  }
  function presOptSet(P, key, v) {   // keeps the named fields in step (the Ready line and older pages read them)
    P.opts = { ...(P.opts || {}), [key]: v };
    if (key === "am") P.audience = { ...(P.audience || {}), muted: !!v };
    if (key === "ask") P.audience = { ...(P.audience || {}), ask: !!v };
    if (key === "cm") P.mode = v;
    if (key === "rbg") P.reporterBg = v;
  }
  async function deckUpload(t, s, slug, prog) {
    const f = s.file, size = f.size || 0;
    const nd = await call({ op: "deckNew", id: t.id, name: s.name || f.name, kind: s.kind === "pdf" ? "pdf" : "pptx", slides: s.n, size }, slug, t.scope === "me");
    if (!nd.ok) return nd;
    const parts = Math.max(1, Math.ceil(size / PART));
    for (let i = 0; i < parts; i++) {
      const fn = "part." + String(i).padStart(3, "0");
      let ok = false, err = "";
      for (let tries = 0; tries < 3 && !ok; tries++) {
        try {
          const r = await fetch(K.base() + "/api/templates/deck?d=" + nd.deck + "&f=" + fn + "&ut=" + nd.utok, { method: "POST", headers: { "content-type": "application/octet-stream" }, body: f.slice(i * PART, (i + 1) * PART) });
          const j = await r.json().catch(() => ({}));
          ok = r.ok && j.ok; err = j.error || ("HTTP " + r.status);
        } catch (e) { err = String(e?.message || e); }
      }
      if (!ok) return { ok: false, error: err };
      prog?.(Math.round(((i + 1) / parts) * 100));
    }
    const dd = await call({ op: "deckDone", id: t.id, deck: nd.deck, utok: nd.utok, start: s.idx || 0 }, slug, t.scope === "me");
    T("deck-up", { ok: dd.ok, parts, size });
    return dd;
  }
  // ---- ready: the main presenter's page ----------------------------------------------------------------------------------
  let readyEl = null;
  const R = { tid: "", room: "", t: null, file: null, busy: false, err: "", by: "" };
  function readyBuild() {
    const el = document.createElement("div");
    el.id = "kTplReady"; el.hidden = true; el.setAttribute("role", "status");
    el.innerHTML = '<div class="ktr-t"><b class="ktr-n"></b><span class="ktr-d"></span><span class="ktr-e"></span></div>'
      + '<div class="ktr-code" hidden><input type="text" class="masked" placeholder="My room code" aria-label="My room code" autocomplete="off"><button type="button" class="ktr-load">Load</button></div>'
      + '<button type="button" class="ktr-go">Start presenting</button><button type="button" class="ghost ktr-no" title="Not now">Not now</button>';
    document.body.appendChild(el);
    el.querySelector(".ktr-no").onclick = () => { el.hidden = true; R.file = null; T("ready-dismissed", {}); };
    el.querySelector(".ktr-go").onclick = () => presStart();
    el.querySelector(".ktr-load").onclick = () => { const c = el.querySelector(".ktr-code input").value; if (c) { mineCode = c; mineStale = false; } readyLoad(); };
    return el;
  }
  css.textContent += `
  #kTplReady { position:fixed; left:50%; bottom:84px; transform:translateX(-50%); z-index:88; display:flex; gap:10px; align-items:center; flex-wrap:wrap;
    max-width:calc(100vw - 24px); background:var(--surface); color:var(--text); border:1px solid var(--asi-blue); border-radius:12px; padding:10px 12px 10px 16px;
    box-shadow:0 12px 32px rgba(0,0,0,.5); font-size:13px; }
  #kTplReady[hidden] { display:none; }
  #kTplReady .ktr-t { display:flex; flex-direction:column; gap:2px; min-width:200px; max-width:520px; flex:1; }
  #kTplReady .ktr-d { color:var(--text-dim); font-size:12px; line-height:1.45; }
  #kTplReady .ktr-e { color:var(--asi-amber); font-size:12px; }
  #kTplReady .ktr-e:empty { display:none; }
  #kTplReady .ktr-code { display:flex; gap:6px; }
  #kTplReady .ktr-code[hidden] { display:none; }
  #kTplReady input { background:var(--surface-2); border:1px solid var(--line); color:var(--text); border-radius:6px; padding:5px 8px; font:inherit; width:150px; }
  #kTplReady input.masked { -webkit-text-security:disc; }
  #kTplReady button { height:32px; padding:0 14px; }
  #kTplReady .ghost { background:transparent; border:1px solid var(--line); color:var(--text-dim); }
  @media (max-width:640px) { #kTplReady { bottom:72px; left:12px; right:12px; transform:none; } }`;
  function readyPaint() {
    if (!readyEl) return;
    const t = R.t, p = t?.pres || {};
    const main = (p.presenters || []).find((x) => x.main);
    const here = new Set((window.__presPeople?.()?.people || []).map((x) => String(x.name || "").trim().toLowerCase()));
    here.add(String(K.me() || "").trim().toLowerCase());
    const others = (p.presenters || []).filter((x) => !x.main).map((x) => x.name), bs = (p.backstage || []).map((b) => b.name);
    const away = [...others, ...bs].filter((n) => !here.has(String(n).trim().toLowerCase()));
    readyEl.querySelector(".ktr-n").textContent = "“" + (t?.name || "Template") + "” is ready" + (main ? " for " + main.name : "");
    readyEl.querySelector(".ktr-d").textContent = (p.deck ? "“" + p.deck.name + "” from slide " + ((p.deck.start || 0) + 1) : "No deck") + " · " + (MODE_WORD[p.mode] || p.mode || "Standout")
      + " · " + audWords(p.audience) + (others.length ? " · with " + others.join(", ") : "") + (bs.length ? " · backstage: " + bs.join(", ") : "")
      + ". Nothing is shown until you press Start presenting.";
    readyEl.querySelector(".ktr-e").textContent = R.err || (away.length ? "Not here yet: " + away.join(", ") + " — they get their role when they join; or add them later." : "");
    const go = readyEl.querySelector(".ktr-go");
    go.disabled = R.busy || !R.file;
    go.textContent = R.busy ? "Starting…" : !R.file ? "Loading the deck…" : "Start presenting";
  }
  async function readyShow(tid, room, by) {
    if (!readyEl) readyEl = readyBuild();
    R.tid = tid; R.room = room; R.t = null; R.file = null; R.err = ""; R.busy = false; R.by = by || "";
    readyEl.hidden = false;
    readyEl.querySelector(".ktr-code").hidden = true;
    readyPaint();
    const g = await call({ op: "get", id: tid }, room, true);
    if (!g.ok) { R.err = g.error || "Could not read the template."; readyPaint(); return; }
    R.t = g.template;
    T("ready", { tid, room });
    readyPaint();
    await readyLoad();
  }
  async function readyLoad() {   // the deck from the hub's store -> a File in this page (nothing is published yet)
    const t = R.t;
    if (!t || !t.pres?.deck) { R.err = t ? "This template keeps no deck — share one with Share ▸ Presentation." : R.err; readyPaint(); return; }
    R.err = ""; readyPaint();
    const t0 = performance.now();
    const o = await call({ op: "deckOpen", id: t.id }, R.room, true);
    if (!o.ok) {
      R.err = o.error || "The deck did not open.";
      if (o.locked || o.wrong || o.named === false) readyEl.querySelector(".ktr-code").hidden = false;
      readyPaint(); return;
    }
    readyEl.querySelector(".ktr-code").hidden = true;
    const blobs = [];
    for (const fn of (o.files || []).filter((f) => /^part\.\d{3}$/.test(f)).sort()) {
      const r = await fetch(K.base() + "/api/templates/deck?d=" + o.deck.id + "&f=" + fn + "&rt=" + encodeURIComponent(o.rt), { cache: "no-store" }).catch(() => null);
      if (!r || !r.ok) { R.err = "The deck could not be loaded from the hub (" + (r ? r.status : "no answer") + ")."; readyPaint(); return; }
      blobs.push(await r.blob());
    }
    const nm = String(o.deck.name || "deck") + (/\.(pptx|pdf|ppsx|potx|pptm|ppsm)$/i.test(o.deck.name || "") ? "" : (o.deck.kind === "pdf" ? ".pdf" : ".pptx"));
    R.file = new File(blobs, nm, { type: o.deck.kind === "pdf" ? "application/pdf" : "application/vnd.openxmlformats-officedocument.presentationml.presentation" });
    T("ready-loaded", { size: R.file.size, ms: Math.round(performance.now() - t0) });
    readyPaint();
  }
  async function presStart() {
    const t = R.t, p = t?.pres || {};
    if (!R.file || R.busy || !window.__pres?.startFromFile) return;
    R.busy = true; readyPaint();
    const t0 = performance.now();
    const deck = p.deck || {};
    await window.__pres.startFromFile(R.file, { idx: Number(deck.start) || 0, cm: p.mode, rbg: p.reporterBg, am: p.audience?.muted === false ? 0 : 1, ask: p.audience?.ask === false ? 0 : 1, o: p.opts || {}, tpl: t.id });
    const st = window.__pres.state?.();
    if (!st?.mine) { R.busy = false; R.err = "The presentation did not start."; readyPaint(); return; }
    // the people who are here get their roles (by name); "Can control my mic and camera" -- mine, as the template says
    const people = (window.__presPeople?.()?.people || []).map((x) => ({ pk: x.host + "/" + (x.op || x.peer), name: String(x.name || "") }));
    const pkOf = (n) => people.find((x) => x.name.trim().toLowerCase() === String(n || "").trim().toLowerCase())?.pk || "";
    const me = String(K.me() || "").trim().toLowerCase();
    const missing = [], refused = [], waiting = [];
    // the ONE seam to the presenter role code: someone here gets the role by their person key; someone who is NOT here is handed
    // over as the template has them (name as kept, keyed by the name key) when the role code can hold a role for an absent person
    // (0.21.92: invite + the role waits until they join) -- else they are named as not here
    const giveRole = (x, r) => {
      const pk = pkOf(x.name);
      if (pk) return window.__pres.role(pk, r) ? "ok" : "refused";
      const later = window.__pres.roleAbsent || window.__pres.roleByName;
      if (typeof later === "function") { try { if (later(String(x.name), r, { key: String(x.name).trim().toLowerCase(), control: x.control || [], from: "template" })) return "waiting"; } catch {} }
      return "missing";
    };
    const tally = (x, r) => { const w = giveRole(x, r); if (w === "missing") missing.push(x.name); else if (w === "refused") refused.push(x.name); else if (w === "waiting") waiting.push(x.name); return w; };
    for (const x of (p.presenters || []).filter((x) => !x.main)) tally(x, "p");
    for (const b of p.backstage || []) {
      if (tally(b, "b") !== "ok") continue;
      window.__pres.allow(pkOf(b.name), (b.control || []).some((c) => String(c).trim().toLowerCase() === me));
    }
    // 0.21.91: co-presenters have the same powers and their OWN "Can control my mic and camera" -- the template's lists for them go
    // to their devices (the hub's people beat); their page sets its own switches once they are a presenter of this deck
    const cos = (p.presenters || []).filter((x) => !x.main && !refused.includes(x.name));   // absent ones too: their device hears it when they come
    if (cos.length && (p.backstage || []).length) call({ op: "presCo", id: t.id, deck: st.mine.id, to: Object.fromEntries(cos.map((x) => [x.name, (pkOf(x.name) || "").split("/")[0]]).filter((e) => e[1])) }, R.room, true).then((d) => T("pres-co", { ok: !!d.ok, told: d.told || 0 })).catch(() => {});
    R.busy = false; readyEl.hidden = true; R.file = null;
    T("pres-started", { ms: Math.round(performance.now() - t0), missing: missing.length, refused: refused.length });
    window.__tplPres = { tid: t.id, at: Date.now(), missing, refused, waiting, ms: Math.round(performance.now() - t0) };   // rig
    toast("Presenting “" + (deck.name || "the deck") + "” from slide " + ((Number(deck.start) || 0) + 1)
      + (waiting.length ? " — invited, their role waits for them: " + waiting.join(", ") : "")
      + (missing.length ? " — not here: " + missing.join(", ") + " (add them from the presenter view when they come)" : "")
      + (refused.length ? " — " + refused.join(", ") + " could not take a role (an older KASTR?)" : ""), 9000, missing.length || refused.length ? "warn" : "event");
  }
  // ---- a co-presenter's page: the template's "Can control my mic and camera" for ME (names I do not allow), once, per person
  const CO = new Map();   // deck id -> {deny:Set(name key), done:Set, until}
  let coTimer = 0;
  function presCo(it) {
    if (!it || !it.deck || it.room !== K.room() || !Array.isArray(it.deny)) return;
    CO.set(String(it.deck), { deny: new Set(it.deny.map((n) => String(n).trim().toLowerCase())), done: new Set(), until: Date.now() + 10 * 60000, by: String(it.owner || "") });
    T("co-note", { deck: it.deck, n: it.deny.length });
    coTick();
  }
  function coTick() {
    clearTimeout(coTimer);
    for (const [id, c] of CO) {
      if (Date.now() > c.until || c.done.size >= c.deny.size) { CO.delete(id); continue; }
      let r = null; try { r = window.__pres?.tplCo?.(id, [...c.deny].filter((n) => !c.done.has(n))); } catch {}
      for (const n of (r && r.set) || []) c.done.add(n);
      if (r && r.set && r.set.length) T("co-applied", { deck: id, n: r.set.length });
    }
    if (CO.size) coTimer = setTimeout(coTick, 1000);
  }
  function presTo(t) {   // the main presenter's device as this page sees them (People), for the hub to tell it
    const main = (t?.pres?.presenters || []).find((x) => x.main);
    if (!main) return undefined;
    const x = (window.__presPeople?.()?.people || []).find((y) => String(y.name || "").trim().toLowerCase() === String(main.name).trim().toLowerCase());
    return x ? { name: main.name, host: x.host } : undefined;
  }
  function seenRoles(t) {   // "Create a new room for this": the template's named people as this page sees them now -> [{name, host}]
    const want = new Set([...(t.pres?.presenters || []), ...(t.pres?.backstage || [])].map((x) => String(x?.name || "").trim().toLowerCase()).filter(Boolean));
    const out = [];
    for (const x of window.__presPeople?.()?.people || []) {
      const n = String(x.name || "").trim().toLowerCase();
      if (want.has(n) && x.host && !out.some((y) => y.name.toLowerCase() === n)) out.push({ name: String(x.name), host: String(x.host) });
    }
    return out.slice(0, 24);
  }
  // ---- 0.21.92 (Kenton: "...having it create a room for it, close the room after the presenter ends the meeting."): End in a room a
  // template made. kastr-pres.js's End button calls window.__pres.onEnd (its ONE hook) -- only End; hand over, take over, Leave and a
  // dropped connection never do. Here: ask, then (once the presentation has ended) the hub closes the room -- only one it marked as
  // made by this run, only for that run's presenters, the room's creator and admins.
  async function presEndHook() {
    const slug = K.room();
    if (!slug) return true;
    if (!K.roomRec(slug).tplClose && typeof K.roomsFresh === "function") {   // my copy of the room records is up to 30 s old: ask once (1.5 s at most)
      try { await Promise.race([K.roomsFresh(), new Promise((r) => setTimeout(r, 1500))]); } catch {}
    }
    if (!K.roomRec(slug).tplClose) return true;
    const yes = await K.confirm({ title: "End the presentation", message: "End the presentation and close " + K.title(slug) + " for everyone?",
      detail: "A template made this room for the presentation. Everyone goes back to their main room and its invite links stop working.", ok: "End and close", danger: true });
    if (!yes) return false;
    return () => closeTplRoom(slug);
  }
  async function closeTplRoom(slug) {
    const d = await call({ op: "presEnd" }, slug, true);
    T("tplroom-end", { ok: !!d.ok, slug, kept: !!d.kept });
    window.__tplRoomEnd = { slug, ok: !!d.ok, error: d.ok ? "" : String(d.error || ""), at: Date.now() };   // rig
    if (d.ok) { K.closed(slug); return; }
    toast("The presentation ended; " + K.title(slug) + " stays open — " + (d.error || "the hub refused"), 8000, "warn");
  }
  const hookEnd = () => { const P = window.__pres; if (!P || typeof P !== "object") return false; if (P.onEnd !== presEndHook) P.onEnd = presEndHook; return true; };
  if (!hookEnd()) { let n = 0; const iv = setInterval(() => { if (hookEnd() || ++n > 240) clearInterval(iv); }, 500); }
  let readyLater = null, readyLaterTimer = 0;   // ready for me in ANOTHER room: shown when I go there (30 min)
  function presReady(it) {   // a template's presentation is ready for me (the hub told my device on my people beat)
    if (!it || !it.tid) return;
    if (it.room !== K.room()) {
      readyLater = { tid: String(it.tid), room: String(it.room), by: String(it.by || ""), until: Date.now() + 30 * 60000 };
      T("ready-later", { room: it.room });
      clearInterval(readyLaterTimer);
      readyLaterTimer = setInterval(() => {
        const w = readyLater;
        if (!w || Date.now() > w.until) { readyLater = null; clearInterval(readyLaterTimer); return; }
        if (K.room() === w.room) { readyLater = null; clearInterval(readyLaterTimer); readyShow(w.tid, w.room, w.by); }
      }, 1500);
      return;
    }
    readyLater = null;
    readyShow(String(it.tid), String(it.room), String(it.by || ""));
  }

  // ======================================================================================================================
  // APPLY: pick the room, Replace or Merge, the sections; the preview says what changes; then Undo in the toast
  // ======================================================================================================================
  let applyEl = null;
  const A = { t: null, slug: "", mode: "replace", on: {}, choices: {}, d: null, seq: 0 };
  async function openApply(t, slug) {
    if (!available()) return;
    if (!applyEl) applyEl = shell("kTplApply", "Apply a template", true);
    A.t = t; A.slug = slug || K.room(); A.mode = "replace"; A.choices = {}; A.d = null;
    A.on = { ...(t.on || {}) };
    paintApply();
    applyEl.__open();
    await preview();
  }
  async function preview() {
    const seq = ++A.seq;
    A.busy = true; paintApply();
    const body = { op: "preview", id: A.t.id, mode: A.mode, on: A.on, choices: A.choices, live: A.slug === K.room() ? K.live() : [], tokens: await proofs(A.t, A.slug) };
    const d = await call(body, A.slug, A.t.scope === "me");
    if (seq !== A.seq) return;
    A.busy = false; A.d = d;
    T("preview", { ok: d.ok, changes: d.changes, notes: (d.notes || []).length });
    paintApply();
  }
  function previewLine(d) {
    const c = d.changes || {}, parts = [];
    if (c["pins+"]) parts.push("+" + plural(c["pins+"], "pin"));
    if (c["pins-"]) parts.push("−" + plural(c["pins-"], "pin"));
    if (c["spots+"] || c["spots-"]) parts.push("spotlight → " + ((d.spotsAfter || []).length ? d.spotsAfter.join(" + ") : "none"));
    if (c.grids) parts.push(plural(c.grids, "grid layout") + " set");
    if (c.hidden) parts.push(plural(c.hidden, "grid camera") + " hidden / shown");
    if (c["cgrids+"]) parts.push("+" + plural(c["cgrids+"], "room grid"));
    if (c["cgrids-"]) parts.push("−" + plural(c["cgrids-"], "room grid"));
    if (c["split+"] || c["split-"]) parts.push(plural((c["split+"] || 0) + (c["split-"] || 0), "camera") + " split / put back");
    if (c.order && !(c["spots+"] || c["spots-"])) parts.push("spotlight order");
    for (const s of d.settings || []) parts.push(s.words);
    const iv = d.invites || {};
    if (iv.people?.length) parts.push("invites " + plural(iv.people.length, "person", "people"));
    if (iv.link) parts.push("makes a " + (TTL[iv.link.ttl] || "") + " invite link");
    if (iv.access?.length) parts.push("gives " + plural(iv.access.length, "person", "people") + " access");
    const n = (st) => (d.cams || []).filter((x) => x.status === st).length;
    if (n("offline")) parts.push(plural(n("offline"), "camera") + " offline");
    if (n("missing")) parts.push(plural(n("missing"), "camera") + " not found");
    if (n("moved")) parts.push(plural(n("moved"), "camera") + " moved");
    if (d.view) parts.push("your own view on this device");
    if (d.pres && d.presFor) parts.push("gets “" + (d.pres.deck?.name || "the presentation") + "” ready for " + (d.presFor.me ? "you" : d.presFor.name) + " (nothing is shown until Start presenting)");
    return parts.join(", ") || "No changes — " + K.title(d.room) + " already looks like this.";
  }
  function camRow(x) {
    const r = div("ktcam");
    const st = x.status === "left out" ? "out" : x.status;
    const label = x.label || K.label(x.to || x.path);
    const where = x.status === "moved" && x.found ? " — now " + (pathRoom(x.found) === "lib" ? "in the library" : "in " + K.title(pathRoom(x.found))) : "";
    r.innerHTML = '<span class="nm" title="' + esc(x.path) + '">' + esc(label) + esc(where) + '</span><span class="ktstat ' + st + '">' + esc({ live: "live", offline: "offline", missing: "not found", moved: "moved", "left out": "left out" }[x.status] || x.status) + '</span>';
    const ch = A.choices[x.path];
    if (x.status !== "live" || ch) {
      const sel = document.createElement("select");
      sel.setAttribute("aria-label", "What to do with " + label);
      const opts = [["keep", "Keep it"], ["drop", "Leave it out"]];
      if (x.status === "offline") sel.title = "Kept: it shows again when it is back";
      if (x.found) opts.push(["found", "Use it where it is now"]);
      opts.push(["swap", "Use another stream…"]);
      sel.innerHTML = opts.map(([v, t]) => '<option value="' + v + '">' + esc(t) + '</option>').join("") + (ch?.act === "swap" ? '<option value="cur">' + esc("→ " + K.label(ch.to)) + '</option>' : "");
      sel.value = !ch ? "keep" : ch.act === "drop" ? "drop" : ch.act === "swap" ? (ch.to === x.found ? "found" : "cur") : "keep";
      sel.onchange = () => {
        const v = sel.value;
        if (v === "keep") delete A.choices[x.path];
        else if (v === "drop") A.choices[x.path] = { act: "drop" };
        else if (v === "found") A.choices[x.path] = { act: "swap", to: x.found };
        else if (v === "swap") { pickStream(sel, x); return; }
        preview();
      };
      r.append(sel);
    }
    return r;
  }
  function pickStream(anchor, x) {
    const items = [];
    if (A.slug === K.room()) for (const p of K.live()) if (!p.split("/")[1]?.startsWith("cgrid")) items.push({ value: p, label: K.label(p) + " (here, live)" });
    for (const e of K.lib()) if (e.live) items.push({ value: e.path, label: e.label + " (library" + (e.site ? ", " + e.site : "") + ")" });
    if (!items.length) { toast("No live streams to pick from here.", 3000); preview(); return; }
    K.menu(anchor, items.slice(0, 60), (v) => { A.choices[x.path] = { act: "swap", to: String(v) }; preview(); });
  }
  function paintApply() {
    const t = A.t, d = A.d;
    const body = applyEl.__body, foot = applyEl.__foot;
    applyEl.__title.textContent = "Apply “" + t.name + "”";
    body.replaceChildren(); foot.replaceChildren();
    body.append(div("hint", esc(countsLine(t))));
    const target = div("field", '<span class="lbl">Room</span>');
    const rs = document.createElement("select"); rs.setAttribute("aria-label", "Room to apply it to");
    const rooms = K.rooms(); const p = K.personal();
    const opts = [...rooms]; if (p?.slug && !opts.some((r) => r.slug === p.slug)) opts.unshift({ slug: p.slug, title: K.title(p.slug) });
    if (A.slug !== NEW && !opts.some((r) => r.slug === A.slug)) opts.unshift({ slug: A.slug, title: K.title(A.slug) });
    const canNew = !!t.pres && t.on?.pres !== undefined && typeof K.createRoom === "function";   // 0.21.92: "Create a new room for this"
    rs.innerHTML = opts.map((r) => '<option value="' + esc(r.slug) + '">' + esc(r.title + (r.slug === K.room() ? " (this room)" : "")) + '</option>').join("")
      + (canNew ? '<option value="' + NEW + '">+ Create a new room for this…</option>' : "");
    rs.value = A.slug; rs.onchange = () => {
      if (rs.value === NEW) { A.slug = NEW; A.mode = "replace"; A.choices = {}; A.d = null; if (!A.newName) A.newName = newRoomName(t); if (A.newClose === undefined) A.newClose = t.pres?.closeOnEnd !== false; paintApply(); return; }
      A.slug = rs.value; A.choices = {}; preview();
    };
    target.append(rs);
    body.append(target);
    if (A.slug === NEW) { paintApplyNew(t, body, foot, secsOf(t)); return; }
    const mode = div("field", '<span class="lbl">How</span>');
    const seg = div("ktseg");
    for (const [k, txt] of [["replace", "Replace"], ["merge", "Merge"]]) { const b = btn(txt, A.mode === k ? "on" : "", () => { A.mode = k; preview(); }); b.dataset.mode = k; seg.append(b); }
    mode.append(seg, div("hint", A.mode === "replace" ? "The room ends up as the template says (for the sections switched on): pins, spotlights and grids it does not have are removed." : "Only what the room lacks is added; everything it has now stays."));
    body.append(mode);
    body.append(div("field", '<span class="lbl">Sections</span>'), secsOf(t, preview));
    const pv = div("ktprev");
    if (!d || A.busy) pv.append(div("ktsum", A.busy && d ? esc(previewLine(d)) + " …" : "Working out what changes…"));
    else if (!d.ok) pv.append(div("ktsum", '<span style="color:var(--asi-red)">' + esc(d.error || "Refused.") + '</span>'));
    else {
      pv.append(div("ktsum", esc(previewLine(d))));
      if ((d.ops || []).length || (d.settings || []).length) {
        const det = document.createElement("details"); det.className = "ktdet";
        det.innerHTML = '<summary>The ' + plural((d.ops || []).length + (d.settings || []).length, "change") + '</summary>';
        const ul = document.createElement("ul");
        for (const o of d.ops || []) { const li = document.createElement("li"); li.textContent = o.words; ul.append(li); }
        for (const s of d.settings || []) { const li = document.createElement("li"); li.textContent = "Room settings: " + s.words; ul.append(li); }
        det.append(ul); pv.append(det);
      }
      const cams = (d.cams || []).filter((x) => x.status !== "left out" || A.choices[x.path]);
      if (cams.length) { const box = div("ktcams"); box.append(div("lbl", "Cameras and streams")); for (const x of cams.slice(0, 40)) box.append(camRow(x)); pv.append(box); }
      if (d.pres) pv.append(div("hint", "Presentation & roles: " + esc(words("pres", { deck: !!d.pres.deck, slides: d.pres.deck?.slides, presenters: (d.pres.presenters || []).length, backstage: (d.pres.backstage || []).length, mode: MODE_WORD[d.pres.mode] || d.pres.mode })) + (d.presFor ? " — ready for " + (d.presFor.me ? "you" : d.presFor.name) + ": the deck loads and " + (d.presFor.me ? "you see" : "they see") + " Start presenting; nothing is shown until it is pressed." : ".")));
      if ((d.notes || []).length) {
        const nb = div("ktnotes", '<span class="lbl">Skipped</span>');
        for (const n of d.notes) nb.append(div("", "<b>" + esc(n.what) + "</b> — " + esc(n.why)));
        pv.append(nb);
      }
    }
    body.append(pv);
    const msg = document.createElement("p"); msg.className = "msg"; msg.setAttribute("role", "status"); body.append(msg);
    applyEl.__say = (s, bad) => { msg.textContent = s || ""; msg.classList.toggle("err", !!bad); };
    const go = btn("Apply", "ktgo", doApply);
    const may = !!(d?.can && (d.can.layout || d.can.settings || d.can.invites)) || !!d?.view;
    go.disabled = !d?.ok || A.busy || !may;
    if (d?.ok && !may) body.append(div("hint", "You can look at it. Applying needs the publisher code" + (d.can && !d.can.layout ? " (an admin while the view is locked)" : "") + "."));
    foot.append(div("sp"), btn("Cancel", "ghost", () => applyEl.__close()), go);
  }
  const NEW = "__new";   // 0.21.92: the room picker's "Create a new room for this"
  function secsOf(t, again) {   // the template's sections as switches (this apply only)
    const secs = div("ktitems");
    for (const k of SEC_ORDER) {
      if (t.on?.[k] === undefined) continue;
      secs.append(sw(SEC[k], A.on[k], (v) => { if (!t.on[k]) { toast(SEC[k] + " is switched off in this template (Edit to switch it on).", 3500); return false; } A.on[k] = v; again?.(); },
        { sec: k, title: words(k, t.counts?.[k]), dim: !t.on[k] }));
    }
    return secs;
  }
  function newRoomName(t) {   // the template's name; the date added when that name is taken (and a number when that is too)
    const base = String(t.name || "Presentation").trim() || "Presentation";
    if (!K.taken(base)) return base;
    const d = new Date(), day = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    let b = base;
    while (b.length > 1 && K.slugOf(b).length + 1 + day.length > 32) b = b.slice(0, -1).trim();
    let nm = b + " " + day;
    for (let i = 2; K.taken(nm) && i < 30; i++) nm = b + " " + day + " " + i;
    return nm;
  }
  function paintApplyNew(t, body, foot, secs) {   // "Create a new room for this": no preview -- the room is empty until KASTR makes it
    const nf = div("field", '<span class="lbl">New room name</span>');
    const ni = document.createElement("input"); ni.type = "text"; ni.maxLength = 40; ni.value = A.newName || ""; ni.setAttribute("aria-label", "New room name"); ni.className = "ktnewname";
    const why = div("hint");
    const check = () => {
      const nm = ni.value.trim(); A.newName = nm;
      const taken = nm && K.taken(nm);
      why.textContent = !nm ? "Name the room." : taken ? "A room named “" + K.slugOf(nm) + "” already exists — pick another name." : "The room: “" + K.slugOf(nm) + "”.";
      why.style.color = !nm || taken ? "var(--asi-red)" : "";
      const go = foot.querySelector(".ktgo"); if (go) go.disabled = !nm || taken;
    };
    ni.oninput = check;
    nf.append(ni, why);
    body.append(nf);
    const cl = sw("Close the room when the presentation ends", A.newClose !== false, (v) => { A.newClose = !!v; },
      { title: "End (any presenter) closes the room for everyone: they go back to their main room. Hand over, Take over and Leave never close it." });
    cl.classList.add("ktclose");
    body.append(div("field", '<span class="lbl">When it ends</span>'), cl);
    body.append(div("field", '<span class="lbl">Sections</span>'), secs);
    body.append(div("ktprev", '<div class="ktsum">' + esc("KASTR creates the room, moves you in and applies “" + t.name + "” there: layout, streams, settings, presentation and roles. Its presenters and backstage are invited; their roles wait for them there. Nothing is shown until Start presenting.") + '</div>'));
    const msg = document.createElement("p"); msg.className = "msg"; msg.setAttribute("role", "status"); body.append(msg);
    applyEl.__say = (s, bad) => { msg.textContent = s || ""; msg.classList.toggle("err", !!bad); };
    const go = btn("Create room and apply", "ktgo", doApplyNew);
    foot.append(div("sp"), btn("Cancel", "ghost", () => applyEl.__close()), go);
    check();
    setTimeout(() => { try { ni.focus(); ni.select(); } catch {} }, 0);
  }
  async function doApplyNew() {
    const t = A.t, name = String(A.newName || "").trim();
    const go = applyEl.querySelector(".ktgo");
    if (!name || K.taken(name)) return;
    go.disabled = true; applyEl.__say("Creating “" + name + "”…");
    const t0 = performance.now();
    const tokens = await proofs(t, "");   // "I can see the template's room" -- from the room I am in now, before I leave it
    const seen = seenRoles(t);           // the devices I see its presenters and backstage on here (the invite goes there)
    const c = await K.createRoom(name);
    T("tplroom-created", { ok: !!c.ok, slug: c.slug || "", ms: Math.round(performance.now() - t0) });
    if (!c.ok) { applyEl.__say(c.error || "The room was not created.", true); go.disabled = false; return; }
    const slug = c.slug, close = A.newClose !== false, on = { ...A.on };
    applyEl.__close();
    toast("Created " + K.title(slug) + " — moving you in…", 4000);
    try { await K.go(slug); } catch {}
    const until = Date.now() + 25000;
    while (Date.now() < until && !(K.room() === slug && K.joined() && K.token())) await new Promise((r) => setTimeout(r, 250));
    if (K.room() !== slug || !K.joined()) { toast("Created " + K.title(slug) + ", but KASTR could not move you in — go there and apply “" + t.name + "”.", 9000, "warn"); return; }
    const mk = await call({ op: "room", id: t.id, close, tokens }, slug, t.scope === "me");
    T("tplroom-marked", { ok: !!mk.ok, close: !!mk.close });
    if (!mk.ok) toast("“" + t.name + "”: " + K.title(slug) + " stays open after the presentation — " + (mk.error || "the hub did not mark it"), 8000, "warn");
    const d = await call({ op: "apply", id: t.id, mode: "replace", on, choices: {}, live: [], tokens, here: slug, presTo: presTo(t), run: mk.ok ? mk.run : undefined, people: seen }, slug, t.scope === "me");
    T("applied", { ok: d.ok, ms: Math.round(performance.now() - t0), done: d.done, notes: (d.notes || []).length, fresh: 1 });
    window.__tplRoom = { slug, run: !!mk.ok, close: !!(mk.ok && mk.close), ms: Math.round(performance.now() - t0) };   // rig (no token)
    if (!d.ok) { toast("Created " + K.title(slug) + ", but “" + t.name + "” was not applied: " + (d.error || "refused"), 9000, "warn"); return; }
    applied(t, slug, d);
  }
  async function doApply() {
    const t = A.t, slug = A.slug;
    applyEl.__say("Applying…");
    applyEl.querySelector(".ktgo").disabled = true;
    const t0 = performance.now();
    const d = await call({ op: "apply", id: t.id, mode: A.mode, on: A.on, choices: A.choices, live: slug === K.room() ? K.live() : [], tokens: await proofs(t, slug), here: K.room(), presTo: presTo(t) }, slug, t.scope === "me");
    T("applied", { ok: d.ok, ms: Math.round(performance.now() - t0), done: d.done, notes: (d.notes || []).length });
    if (!d.ok) { applyEl.__say(d.error || "Refused.", true); applyEl.querySelector(".ktgo").disabled = false; return; }
    applyEl.__close();
    applied(t, slug, d);
  }
  async function applied(t, slug, d) {   // after an apply: the view, the toast with Undo, the link, the presentation's Ready
    let mine = 0;
    if (d.view && slug === K.room()) { try { mine = K.view.apply(d.view); } catch {} }
    K.refresh();
    const n = (d.done?.layout || 0) + (d.done?.settings || 0) + (d.done?.invites || 0) + (d.done?.access || 0) + (d.done?.link ? 1 : 0);
    const skipped = (d.notes || []).length;
    window.__tplLast = { undo: d.undo, room: slug, id: t.id, at: Date.now(), done: d.done, sent: d.sent || [], link: !!d.link, notes: (d.notes || []).length };   // rig (no token)
    const presWord = d.pres && d.presFor ? (n ? ", " : "") + "presentation ready for " + (d.presFor.me ? "you" : d.presFor.name) : "";
    toast("Applied “" + t.name + "” to " + K.title(slug) + " — " + (n || !presWord ? plural(n, "change") : "") + presWord + (mine ? " + your view" : "") + (skipped ? ", " + skipped + " skipped" : ""), 20000, skipped ? "warn" : "event",
      d.undo ? { label: "Undo", fn: () => undo(d.undo, slug, t.name) } : undefined);
    if (d.link?.token) {
      const link = await K.inviteLink(d.link.token, slug).catch(() => "");
      if (link) toast("A fresh " + (TTL[d.link.ttl] || "") + " invite link for " + K.title(slug) + " is ready.", 20000, "event", { label: "Copy link", fn: () => { try { navigator.clipboard.writeText(link); toast("Invite link copied", 2500); } catch {} } });
    }
    if (d.pres && d.presFor) {   // "Ready, with a Start button": here when I am the main presenter, else on their page
      window.__tplLast.presFor = { name: d.presFor.name, me: !!d.presFor.me, told: !!d.presFor.told };
      if (d.presFor.me && slug === K.room()) readyShow(t.id, slug, K.me());
      else if (d.presFor.me) toast("“" + t.name + "”: the presentation is ready for you in " + K.title(slug) + " — go there and press Start presenting.", 8000);
      else if (!d.presFor.told) toast("“" + t.name + "”: " + d.presFor.name + " is not on KASTR right now — the presentation is ready for them when they apply it again.", 8000, "warn");
    }
    refreshAll();
  }
  async function undo(uid, slug, name) {
    const d = await call({ op: "undo", undo: uid }, slug);
    T("undo", { ok: d.ok, layout: d.layout, settings: d.settings });
    if (!d.ok) { toast("Undo: " + (d.error || "refused"), 6000, "warn"); return; }
    K.refresh();
    toast("Undone — " + K.title(slug) + " is back as it was before “" + name + "”" + (d.links ? " (its invite links stop working; invites already sent stay)" : ""), 5000);
  }

  // ======================================================================================================================
  // EDIT: rename, note, sections on / off, remove single items, invitees, settings switches
  // ======================================================================================================================
  let editEl = null;
  const E = { t: null, slug: "", lay: null, inv: null, on: {}, set: null };
  function openEdit(t, slug) {
    if (!editEl) editEl = shell("kTplEdit", "Edit template", true);
    E.t = t; E.slug = slug; E.on = { ...(t.on || {}) };
    E.lay = t.layout ? JSON.parse(JSON.stringify(t.layout)) : null;
    E.inv = t.invites ? JSON.parse(JSON.stringify(t.invites)) : null;
    E.set = t.settings ? { ...t.settings } : null;
    E.pres = t.pres ? JSON.parse(JSON.stringify(t.pres)) : null;
    paintEdit();
    editEl.__open();
  }
  function paintEdit() {
    const t = E.t, body = editEl.__body, foot = editEl.__foot;
    const keep = { name: editEl.querySelector(".ktname")?.value, note: editEl.querySelector(".ktnote")?.value };
    body.replaceChildren(); foot.replaceChildren();
    editEl.__title.textContent = "Edit “" + t.name + "”";
    body.append(div("field", '<span class="lbl">Name</span><input type="text" class="ktname" maxlength="60" aria-label="Template name">'),
      div("field", '<span class="lbl">Note</span><textarea class="ktnote" maxlength="300" rows="2" aria-label="Note"></textarea>'));
    body.querySelector(".ktname").value = keep.name ?? t.name; body.querySelector(".ktnote").value = keep.note ?? (t.note || "");
    const secs = div("ktsecs");
    const label = (p) => { const pin = (t.layout?.pins || []).find((x) => x.path === p); return pin?.label || K.label(p); };
    for (const k of SEC_ORDER) {
      if (t.on?.[k] === undefined) continue;
      const r = div("ktsec" + (E.on[k] ? "" : " off"));
      r.innerHTML = SWITCH + '<div class="ktsm"><span class="ktst">' + esc(SEC[k]) + '</span><span class="ktsc">' + esc(words(k, t.counts?.[k])) + '</span></div>';
      const cb = r.querySelector("input"); cb.setAttribute("aria-label", SEC[k]); cb.dataset.sec = k; cb.checked = !!E.on[k]; cb.onchange = () => { E.on[k] = cb.checked; r.classList.toggle("off", !cb.checked); };
      const sm = r.querySelector(".ktsm");
      if (k === "layout" && E.lay) {
        const items = div("ktitems");
        const chip = (text, rm) => { const c = div("ktchip", esc(text) + ' <span class="x" aria-hidden="true">×</span>'); c.title = "Remove from the template"; c.onclick = () => { rm(); paintEdit(); }; items.append(c); };
        for (const p of E.lay.pins || []) chip("Pin: " + label(p.path), () => { E.lay.pins = E.lay.pins.filter((x) => x.path !== p.path); });
        for (const s of E.lay.spots || []) chip("Spotlight: " + label(s), () => { E.lay.spots = E.lay.spots.filter((x) => x !== s); E.lay.spotOrder = (E.lay.spotOrder || []).filter((x) => x !== s); });
        for (const gp of Object.keys(E.lay.grids || {})) chip("Grid layout: " + label(gp), () => { delete E.lay.grids[gp]; });
        for (const [gid, g] of Object.entries(E.lay.customGrids || {})) chip("Room grid: " + (g.name || gid), () => { delete E.lay.customGrids[gid]; });
        for (const m of E.lay.split || []) chip("Split: " + label(m), () => { E.lay.split = E.lay.split.filter((x) => x !== m); });
        if (items.childElementCount) sm.append(items);
      }
      if (k === "invites" && E.inv) {
        const items = div("ktitems");
        for (const p of E.inv.people || []) { const c = div("ktchip on", esc(p.name) + ' <span class="x" aria-hidden="true">×</span>'); c.onclick = () => { E.inv.people = E.inv.people.filter((x) => x !== p); paintEdit(); }; items.append(c); }
        const add = btn("Add someone…", "ghost"); add.style.height = "24px"; add.style.fontSize = "11.5px";
        add.onclick = async () => {
          const all = await K.people().catch(() => []);
          const have = new Set((E.inv.people || []).map((x) => String(x.name).toLowerCase()));
          const list = all.filter((x) => !have.has(String(x.name).toLowerCase())).slice(0, 40).map((x) => ({ value: x.name, label: x.name }));
          if (list.length) K.menu(add, list, (v) => { (E.inv.people = E.inv.people || []).push({ name: v }); paintEdit(); });
        };
        items.append(add);
        const ls = document.createElement("select");
        ls.innerHTML = '<option value="0">No invite link</option><option value="3600">An invite link for 1 hour</option><option value="86400">An invite link for 24 hours</option><option value="604800">An invite link for 7 days</option>';
        ls.value = String(E.inv.link?.ttl || 0); ls.onchange = () => { const v = Number(ls.value) || 0; E.inv.link = v ? { ttl: v } : null; };
        items.append(ls);
        sm.append(items);
      }
      if (k === "pres" && E.pres) {   // roles: who presents (main first), who is backstage; the mode, the audience rule, the start slide
        const P = E.pres, items = div("ktitems");
        P.presenters = P.presenters || []; P.backstage = P.backstage || [];
        for (const x of P.presenters) {
          const c = div("ktchip on", esc((x.main ? "★ " : "") + x.name) + ' <span class="x" aria-hidden="true">×</span>');
          c.title = x.main ? "The main presenter (sees Start presenting)" : "A presenter — click to remove";
          c.onclick = () => { P.presenters = P.presenters.filter((y) => y !== x); if (x.main && P.presenters[0]) P.presenters[0].main = true; for (const b of P.backstage) b.control = (b.control || []).filter((n) => n !== x.name); paintEdit(); };
          items.append(c);
        }
        for (const b of P.backstage) {
          const c = div("ktchip", esc("Backstage: " + b.name) + ' <span class="x" aria-hidden="true">×</span>');
          c.onclick = () => { P.backstage = P.backstage.filter((y) => y !== b); paintEdit(); };
          items.append(c);
          // 0.21.91 roles: each presenter's own "Can control my mic and camera" switch for this backstage person
          for (const x of P.presenters) {
            const has = (b.control || []).includes(x.name);
            items.append(sw(b.name + " can control " + x.name + "’s mic and camera", has, (v) => {
              b.control = (b.control || []).filter((n) => n !== x.name); if (v) b.control.push(x.name);
            }, { title: "The same switch " + x.name + " has in Presenters/Backstage while presenting" }));
          }
        }
        const addP = (as) => async (e) => {
          const all = await K.people().catch(() => []);
          const have = new Set([...P.presenters, ...P.backstage].map((x) => String(x.name).toLowerCase()));
          const list = all.filter((x) => !have.has(String(x.name).toLowerCase())).slice(0, 40).map((x) => ({ value: x.name, label: x.name }));
          if (!list.length) return;
          K.menu(e.currentTarget, list, (v) => {
            if (as === "p") { P.presenters.push({ name: v, main: !P.presenters.length }); for (const b of P.backstage) (b.control = b.control || []).push(v); }
            else P.backstage.push({ name: v, control: P.presenters.map((x) => x.name) });
            paintEdit();
          });
        };
        const ap = btn("Add presenter…", "ghost"), ab = btn("Add backstage…", "ghost");
        for (const b of [ap, ab]) { b.style.height = "24px"; b.style.fontSize = "11.5px"; }
        ap.onclick = addP("p"); ab.onclick = addP("b");
        // someone who is not online: a typed name (kept as typed; the role waits for them when the template is used)
        const tn = document.createElement("input"); tn.type = "text"; tn.maxLength = 40; tn.placeholder = "or type a name"; tn.className = "kttyped";
        tn.setAttribute("aria-label", "A name to add (someone not online)"); tn.style.width = "130px";
        const addTyped = (as) => () => {
          const v = tn.value.trim().replace(/\s+/g, " ");
          if (!v || [...P.presenters, ...P.backstage].some((x) => String(x.name).trim().toLowerCase() === v.toLowerCase())) return;
          if (as === "p") { P.presenters.push({ name: v, main: !P.presenters.length }); for (const b of P.backstage) (b.control = b.control || []).push(v); }
          else P.backstage.push({ name: v, control: P.presenters.map((x) => x.name) });
          paintEdit();
        };
        const tp = btn("+ Presenter", "ghost", addTyped("p")), tb = btn("+ Backstage", "ghost", addTyped("b"));
        for (const b of [tp, tb]) { b.style.height = "24px"; b.style.fontSize = "11.5px"; }
        items.append(ap, ab, tn, tp, tb);
        const ms = document.createElement("select");
        ms.innerHTML = Object.entries(MODE_WORD).map(([v, w]) => '<option value="' + v + '">' + esc(w) + '</option>').join("");
        ms.value = presOpt(P, "cm", "standout") || "standout"; ms.onchange = () => { presOptSet(P, "cm", ms.value); };
        items.append(ms);
        for (const o of optRows().filter((x) => x.sw)) {   // every on/off option of the presenter view, from the one table
          const off = o.needs && !presOpt(P, o.needs, 1);   // e.g. Ask to speak only while the audience is muted
          const on = !off && !!presOpt(P, o.key, o.def);
          items.append(sw(o.text || o.key, on, (v) => { presOptSet(P, o.key, v ? 1 : 0); paintEdit(); },
            { disabled: !!off, dim: !!off, title: off ? "Only while “" + (optRows().find((x) => x.key === o.needs)?.text || o.needs) + "” is on." : "" }));
        }
        // 0.21.92 (Kenton): a room this template creates for itself (Apply > Create a new room for this) closes when a presenter ends it
        items.append(sw("Close the room when the presentation ends", P.closeOnEnd !== false, (v) => { P.closeOnEnd = !!v; },
          { title: "Only for a room the template creates (Apply ▸ Create a new room for this). A room that existed before is never closed." }));
        if (P.deck) {
          const si = document.createElement("input"); si.type = "number"; si.min = "1"; si.max = String(P.deck.slides || 1); si.value = String((P.deck.start || 0) + 1);
          si.style.width = "64px"; si.title = "Start on slide"; si.setAttribute("aria-label", "Start on slide");
          si.onchange = () => { P.deck.start = Math.max(0, Math.min((P.deck.slides || 1) - 1, (Number(si.value) || 1) - 1)); };
          items.append(div("hint", "Start on slide"), si);
        }
        sm.append(items);
      }
      if (k === "settings" && E.set) {
        const items = div("ktitems");
        const tog = (key, text, onlyOff) => items.append(sw(text, E.set[key], (v) => { if (onlyOff && v) { toast("A lock is taken from the room itself — use “Update from this room” after locking it.", 4500); return false; } E.set[key] = v; paintEdit(); }));
        tog("locked", "Locked", true); tog("keep", "Kept open"); tog("viewLock", "View locked");
        sm.append(items);
      }
      secs.append(r);
    }
    body.append(div("field", '<span class="lbl">Sections</span>'), secs);
    const msg = document.createElement("p"); msg.className = "msg"; body.append(msg);
    editEl.__say = (s, bad) => { msg.textContent = s || ""; msg.classList.toggle("err", !!bad); };
    foot.append(btn("Update from this room", "ghost", () => { editEl.__close(); resnap(t, E.slug); }), div("sp"), btn("Cancel", "ghost", () => editEl.__close()), btn("Save changes", "ktgo", doEdit));
  }
  async function doEdit() {
    const t = E.t;
    const body = { op: "update", id: t.id, name: editEl.querySelector(".ktname").value.trim(), note: editEl.querySelector(".ktnote").value.trim(), on: E.on };
    if (!body.name) { editEl.__say("Give the template a name.", true); return; }
    if (E.lay) body.layout = E.lay;
    if (E.inv) body.invites = E.inv;
    if (E.set) body.settings = { locked: !!E.set.locked, keep: !!E.set.keep, viewLock: !!E.set.viewLock };
    if (E.pres) body.pres = E.pres;
    editEl.__say("Saving…");
    const d = await call(body, E.slug, t.scope === "me");
    if (!d.ok) { editEl.__say(d.error || "Refused.", true); return; }
    editEl.__close();
    toast("Saved “" + body.name + "”", 3000);
    refreshAll();
  }

  // ======================================================================================================================
  // Room settings' Templates row, the My room dialog, the room card's right-click, More > Templates...
  // ======================================================================================================================
  let rsBox = null, rsSlug = "";
  async function roomSettings(row, slug) {
    rsBox = row; rsSlug = slug;
    if (!row) return;
    const box = row.querySelector(".rstplbox") || row;
    row.hidden = !available() || slug === K.lobby() || K.isPersonal(slug);
    if (row.hidden) return;
    box.className = "rstplbox ktbox";
    box.replaceChildren(div("hint", "Loading…"));
    const d = await call({ op: "list" }, slug);
    if (rsBox !== row || rsSlug !== slug) return;
    box.replaceChildren();
    if (!d.ok) { box.append(div("hint", esc(d.error || "Could not load the templates."))); return; }
    for (const t of (d.templates || []).slice(0, 5)) {
      const l = div("ktline", "<span>" + esc(t.name) + "</span>");
      l.title = countsLine(t);
      l.append(btn(d.can?.apply ? "Apply…" : "Preview…", "ghost", () => openApply(t, slug)));
      box.append(l);
    }
    if (!(d.templates || []).length) box.append(div("hint", "No templates yet — save how this room is set up now (pins, spotlights, grids, its lock and keep, who to invite) to put it back later or reuse it."));
    const acts = div("ktacts");
    if (d.can?.save) acts.append(btn("Save this room as a template…", "", () => openSave(slug, "room")));
    acts.append(btn((d.templates || []).length > 5 ? "All " + d.templates.length + " templates…" : "Templates…", "ghost", () => openList(slug, "room")));
    box.append(acts);
  }
  let pmBox = null;
  async function myRoom(row, have) {
    pmBox = row;
    if (!row) return;
    const box = row.querySelector(".pmtplbox") || row;
    row.hidden = !available() || !have;
    if (row.hidden) return;
    box.className = "pmtplbox ktbox";
    box.replaceChildren(div("hint", "Loading…"));
    const d = await call({ op: "list" }, K.room(), true);
    if (pmBox !== row) return;
    box.replaceChildren();
    if (!d.mine) { box.append(div("hint", esc(d.mineError || d.error || "Open them from More ▸ Templates… with your My room code."))); return; }
    const mySlug = K.personal()?.slug;
    for (const t of d.mine.slice(0, 6)) {
      const l = div("ktline", "<span>" + esc(t.name) + "</span>");
      l.title = countsLine(t);
      l.append(btn(K.room() === mySlug ? "Apply here…" : "Apply…", "ghost", () => { document.getElementById("kMyRoom")?.__close?.(); openApply(t, K.room() === mySlug ? mySlug : K.room()); }));
      box.append(l);
    }
    if (!d.mine.length) box.append(div("hint", "None yet. Save a room as a template under <b>Just me</b> (More ▸ Templates…) — it follows you to any device."));
    const acts = div("ktacts");
    acts.append(btn("My templates…", "ghost", () => { document.getElementById("kMyRoom")?.__close?.(); openList(K.room(), "mine"); }));
    box.append(acts);
  }
  const canApplyTo = (slug) => available() && !!slug && slug !== K.lobby();
  function applyTo(slug) { openList(slug, K.isPersonal(slug) ? "mine" : "room"); }
  const opt = document.getElementById("optTpl");
  if (opt) {
    opt.addEventListener("click", () => openList(K.room(), K.isPersonal(K.room()) ? "mine" : "room"));
    const paint = () => { const on = available(); if (opt.hidden === on) opt.hidden = !on; };
    paint();
    setInterval(paint, 1500);
  }
  window.__tplUI = {
    open: openList, save: openSave, apply: openApply, edit: openEdit, roomSettings, myRoom, canApplyTo, applyTo, available,
    presReady, presCo, coState: () => [...CO].map(([id, c]) => ({ id, deny: c.deny.size, done: c.done.size })), ready: readyShow, presStart, presState: () => ({ tid: R.tid, loaded: !!R.file, size: R.file ? R.file.size : 0, busy: R.busy, err: R.err, shown: !!readyEl && !readyEl.hidden }),   // 0.21.92: presentation & roles
    state: () => ({ list: L.d ? { ok: L.d.ok, n: (L.d.templates || []).length, mine: L.d.mine ? L.d.mine.length : null, can: L.d.can } : null,
      apply: A.d ? { ok: A.d.ok, changes: A.d.changes, notes: A.d.notes, cams: A.d.cams, settings: A.d.settings, invites: A.d.invites } : null, trace: trace.slice(-40) }),
  };
})();
