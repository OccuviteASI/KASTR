// 0.21.92 (Kenton, 2026-10-23 design review; 2026-10-27: "Having these options to setup the room how I want with whatever presenter
// options are available"): MEETING TEMPLATES, phase 1 "by hand" -- the page half (the hub half is kastr_templates.py; the relay
// a page calls checks its token and a spoke forwards to the hub).
//
// A TEMPLATE is a saved snapshot of how a room is set up, in sections: Layout & view (the room board + whether it starts on the
// spotlight or the gallery), Streams & cameras (what the board pulls in from other rooms and the library), Presentation & roles
// (its saved shape; starting a presentation from it comes with co-presenters), Room settings (the code's DIGEST only -- the hub
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
  .ktsec input[type=checkbox] { margin-top:2px; accent-color:var(--asi-blue); flex:none; }
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
    if (sec === "pres") return list([c.deck ? "a deck" + (c.slides ? " (" + plural(c.slides, "slide") + ")" : "") : "", c.presenters && plural(c.presenters, "presenter"), c.backstage && plural(c.backstage, "backstage person", "backstage people"), c.mode && c.mode]) || "presenter options";
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
    if (!(await K.confirm({ title: "Update template", message: "Update “" + t.name + "” from " + K.title(slug) + " as it is now?", detail: "Its layout, streams and room settings are taken again; its name, note, invites and presentation stay.", ok: "Update" }))) return;
    const d = await call({ op: "update", id: t.id, resnap: true, start: K.start() }, slug, t.scope === "me");
    if (!d.ok) { toast("Templates: " + d.error, 6000, "warn"); return; }
    toast("Updated “" + t.name + "” from " + K.title(slug), 3000);
    refreshAll();
  }
  function refreshAll() {
    if (listEl && !listEl.hidden) loadList();
    if (rsBox?.isConnected) roomSettings(rsBox, rsSlug);
    if (pmBox?.isConnected) myRoom(pmBox, true);
  }

  // ======================================================================================================================
  // SAVE: name, note, This room / Just me, a checkbox per section with live counts
  // ======================================================================================================================
  let saveEl = null;
  const S = { slug: "", scope: "room", on: {}, people: new Map(), link: 0, start: "spotlight", counts: null, view: null, access: true, rec: null };
  async function openSave(slug, scope) {
    if (!available()) return;
    K.closePops();
    if (!saveEl) saveEl = shell("kTplSave", "Save as a template", true);
    S.slug = slug || K.room(); S.scope = scope || "room"; S.people = new Map(); S.link = 0; S.start = K.start(); S.access = true;
    S.on = { layout: true, streams: true, pres: false, settings: true, invites: false, view: true };
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
      r.innerHTML = '<input type="checkbox" aria-label="' + esc(SEC[k]) + '"><div class="ktsm"><span class="ktst">' + esc(SEC[k]) + '</span><span class="ktsc">' + esc(text) + '</span>' + (why ? '<span class="hint">' + esc(why) + '</span>' : "") + '</div>';
      const cb = r.querySelector("input");
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
    sec("pres", "Deck and starting slide, presenters and backstage, audience muted / Ask to speak, presenter mode", null, true, "Comes with co-presenters (0.21.91) — this version keeps the section's shape only.");
    if (!personalRoom) sec("settings", words("settings", { locked: rec.locked, keep: rec.keep, viewLock: rec.viewLock, group: rec.groupName || rec.group }), null, false, rec.locked ? "The room’s code is kept only as the hub keeps it (a salted digest) — never the code." : "");
    // invites: the people here now (tick to invite them next time), an invite link made fresh at apply, My room's people with access
    const inv = div("ktsx");
    const here = K.peopleHere();
    for (const p of here) { if (!S.people.has(p.name.toLowerCase()) && S.people.__init !== true) S.people.set(p.name.toLowerCase(), { ...p, on: false }); }
    S.people.__init = true;
    for (const [k, p] of S.people) {
      const ch = div("ktchip" + (p.on ? " on" : ""), esc(p.name));
      ch.onclick = () => { p.on = !p.on; ch.classList.toggle("on", p.on); paintInvCount(); };
      inv.append(ch);
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
    const sections = Object.keys(S.on).filter((k) => S.on[k] && (k !== "pres") && (k !== "view" || S.scope === "me") && (k !== "settings" || !K.isPersonal(S.slug)));
    if (!sections.length) { saveEl.__say("Pick at least one section.", true); return; }
    const body = { op: "save", scope: S.scope, name, note: saveEl.querySelector(".ktnote").value.trim(), sections, start: S.start,
      invites: { people: [...S.people.values()].filter((p) => p.on).map((p) => ({ name: p.name, host: p.host || undefined })), link: S.link ? { ttl: S.link } : null },
      view: S.scope === "me" ? S.view : undefined, withAccess: S.access };
    saveEl.__say("Saving…");
    const go = saveEl.querySelector(".ktgo"); go.disabled = true;
    const d = await call(body, S.slug, S.scope === "me");
    go.disabled = false;
    if (!d.ok) { saveEl.__say(d.error || "Refused.", true); return; }
    saveEl.__close();
    T("saved", { id: d.template?.id, scope: S.scope, sections });
    toast("Saved “" + name + "” — " + countsLine(d.template), 5000);
    refreshAll();
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
    if (!opts.some((r) => r.slug === A.slug)) opts.unshift({ slug: A.slug, title: K.title(A.slug) });
    rs.innerHTML = opts.map((r) => '<option value="' + esc(r.slug) + '">' + esc(r.title + (r.slug === K.room() ? " (this room)" : "")) + '</option>').join("");
    rs.value = A.slug; rs.onchange = () => { A.slug = rs.value; A.choices = {}; preview(); };
    target.append(rs);
    body.append(target);
    const mode = div("field", '<span class="lbl">How</span>');
    const seg = div("ktseg");
    for (const [k, txt] of [["replace", "Replace"], ["merge", "Merge"]]) { const b = btn(txt, A.mode === k ? "on" : "", () => { A.mode = k; preview(); }); b.dataset.mode = k; seg.append(b); }
    mode.append(seg, div("hint", A.mode === "replace" ? "The room ends up as the template says (for the sections ticked): pins, spotlights and grids it does not have are removed." : "Only what the room lacks is added; everything it has now stays."));
    body.append(mode);
    const secs = div("ktitems");
    for (const k of SEC_ORDER) {
      if (t.on?.[k] === undefined) continue;
      const ch = div("ktchip" + (A.on[k] ? " on" : ""), esc(SEC[k]));
      ch.dataset.sec = k;
      ch.title = words(k, t.counts?.[k]);
      ch.onclick = () => { if (!t.on[k]) { toast(SEC[k] + " is switched off in this template (Edit to switch it on).", 3500); return; } A.on[k] = !A.on[k]; preview(); };
      secs.append(ch);
    }
    body.append(div("field", '<span class="lbl">Sections</span>'), secs);
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
      if (d.pres) pv.append(div("hint", "Presentation & roles: " + esc(words("pres", { deck: !!d.pres.deck, slides: d.pres.deck?.slides, presenters: (d.pres.presenters || []).length, backstage: (d.pres.backstage || []).length, mode: d.pres.mode })) + " — starting a presentation from a template comes with co-presenters."));
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
  async function doApply() {
    const t = A.t, slug = A.slug;
    applyEl.__say("Applying…");
    applyEl.querySelector(".ktgo").disabled = true;
    const t0 = performance.now();
    const d = await call({ op: "apply", id: t.id, mode: A.mode, on: A.on, choices: A.choices, live: slug === K.room() ? K.live() : [], tokens: await proofs(t, slug) }, slug, t.scope === "me");
    T("applied", { ok: d.ok, ms: Math.round(performance.now() - t0), done: d.done, notes: (d.notes || []).length });
    if (!d.ok) { applyEl.__say(d.error || "Refused.", true); applyEl.querySelector(".ktgo").disabled = false; return; }
    applyEl.__close();
    let mine = 0;
    if (d.view && slug === K.room()) { try { mine = K.view.apply(d.view); } catch {} }
    K.refresh();
    const n = (d.done?.layout || 0) + (d.done?.settings || 0) + (d.done?.invites || 0) + (d.done?.access || 0) + (d.done?.link ? 1 : 0);
    const skipped = (d.notes || []).length;
    window.__tplLast = { undo: d.undo, room: slug, id: t.id, at: Date.now(), done: d.done, sent: d.sent || [], link: !!d.link, notes: (d.notes || []).length };   // rig (no token)
    toast("Applied “" + t.name + "” to " + K.title(slug) + " — " + plural(n, "change") + (mine ? " + your view" : "") + (skipped ? ", " + skipped + " skipped" : ""), 20000, skipped ? "warn" : "event",
      d.undo ? { label: "Undo", fn: () => undo(d.undo, slug, t.name) } : undefined);
    if (d.link?.token) {
      const link = await K.inviteLink(d.link.token, slug).catch(() => "");
      if (link) toast("A fresh " + (TTL[d.link.ttl] || "") + " invite link for " + K.title(slug) + " is ready.", 20000, "event", { label: "Copy link", fn: () => { try { navigator.clipboard.writeText(link); toast("Invite link copied", 2500); } catch {} } });
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
      r.innerHTML = '<input type="checkbox" aria-label="' + esc(SEC[k]) + '"><div class="ktsm"><span class="ktst">' + esc(SEC[k]) + '</span><span class="ktsc">' + esc(words(k, t.counts?.[k])) + '</span></div>';
      const cb = r.querySelector("input"); cb.checked = !!E.on[k]; cb.onchange = () => { E.on[k] = cb.checked; r.classList.toggle("off", !cb.checked); };
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
      if (k === "settings" && E.set) {
        const items = div("ktitems");
        const tog = (key, text, onlyOff) => { const c = div("ktchip" + (E.set[key] ? " on" : ""), esc(text)); c.onclick = () => { if (onlyOff && !E.set[key]) { toast("A lock is taken from the room itself — use “Update from this room” after locking it.", 4500); return; } E.set[key] = !E.set[key]; paintEdit(); }; items.append(c); };
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
    state: () => ({ list: L.d ? { ok: L.d.ok, n: (L.d.templates || []).length, mine: L.d.mine ? L.d.mine.length : null, can: L.d.can } : null,
      apply: A.d ? { ok: A.d.ok, changes: A.d.changes, notes: A.d.notes, cams: A.d.cams, settings: A.d.settings, invites: A.d.invites } : null, trace: trace.slice(-40) }),
  };
})();
