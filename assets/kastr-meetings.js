// 0.21.96 (Kenton, 2026-10-28: "templates to also be setup to configure a webmeeting, like a teams meeting. Where I can schedule it
// for a weekly/daily meeting, or just a 1 time meeting"; 2026-10-30: "add scheduled meetings to the next update"): SCHEDULED
// MEETINGS -- the page half (the hub half is kastr_meetings.py + AuthService.meetings_api in kastr_relay.py).
//
// A MEETING is one-time, daily or weekly, at a local wall time in a named time zone (a weekly 09:00 stays 09:00 across a daylight-
// saving change). It meets in its OWN hidden room (mt-<12 hex>: never in the rooms list, the hub lets in only its invited people --
// proven by their name + My room code -- and its link guests, from 10 minutes before the start until it empties) or in a room the
// organizer is an admin of. WHERE: More > Meetings... (only the meetings I am invited to: Live now / Coming up), a reminder 5
// minutes before, a Join prompt at the start, an .ics file + a calendar link, a guest link. "Requires the host to join" (off by
// default): invitees wait in a lobby until the organizer or a presenter is in. A template (optional) is applied by the first
// invitee in. The page's bridges: window.__ktpl (the templates' one) and window.__kmeetPage. NEVER on a relay without access codes.
(() => {
  "use strict";
  if (window.__kmeet) return;
  const K = window.__ktpl, P = window.__kmeetPage;
  if (!K || !P) return;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const toast = (m, ms, level, action) => { try { window.__toast?.(m, ms || 5000, { level: level || "event", action }); } catch {} };
  const plural = (n, one, many) => n + " " + (n === 1 ? one : (many || one + "s"));
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const DAYS_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const DURS = [15, 30, 45, 60, 90, 120, 180];
  const MID_RE = /^m[0-9a-f]{12}$/;
  const POLL_MS = 60000, BEAT_MS = 20000, TICK_MS = 5000;
  const available = () => { try { return K.secured() && P.joinedAny() && !K.guest(); } catch { return false; } };
  const trace = [];
  const T = (ev, o) => { trace.push(Object.assign({ t: Date.now(), ev }, o || {})); if (trace.length > 200) trace.splice(0, 50); };
  let skew = 0;   // hub seconds - my seconds (the list's `now`)
  const nowS = () => Date.now() / 1000 + skew;

  // ---- the look (the templates' dialog classes + these) -------------------------------------------------------------------
  const css = document.createElement("style");
  css.id = "kMeetCss";
  css.textContent = `
  .kmsec { font-size:11px; color:var(--text-dim); text-transform:uppercase; letter-spacing:.06em; margin-top:2px; }
  .kmwhen { color:var(--text); font-size:12.5px; }
  .kmlive { display:inline-block; font-size:10.5px; padding:0 7px; border-radius:9px; margin-left:6px; vertical-align:1px; font-weight:600;
            background:color-mix(in srgb, var(--asi-red) 18%, transparent); color:var(--asi-red); border:1px solid var(--asi-red); }
  .kmsoon { border-color:var(--asi-amber); color:var(--asi-amber); background:transparent; }
  .kmcan { text-decoration:line-through; opacity:.7; }
  .kmpeople { display:flex; flex-direction:column; gap:5px; }
  .kmperson { display:flex; align-items:center; gap:8px; background:var(--surface-2); border:1px solid var(--line); border-radius:6px; padding:4px 6px 4px 10px; font-size:12.5px; color:var(--text); }
  .kmperson .nm { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .kmperson button { height:24px; width:24px; padding:0; }
  .kmdays { display:flex; gap:5px; flex-wrap:wrap; }
  .kmgrid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  .kmgrid .field { min-width:0; }
  .kmdl { display:grid; grid-template-columns:auto 1fr; gap:4px 12px; font-size:12.5px; }
  .kmdl dt { color:var(--text-mute); }
  .kmdl dd { margin:0; color:var(--text); min-width:0; overflow-wrap:anywhere; }
  .kmacts { display:flex; gap:6px; flex-wrap:wrap; }
  .kmlobby { position:fixed; inset:0; z-index:142; background:rgba(3,5,10,.72); display:flex; align-items:center; justify-content:center; padding:16px; }
  .kmlobby[hidden] { display:none; }
  .kt-scrim.km-under, .kt-scrim.kt-top.km-under, .kmlobby.km-under { z-index:139; }
  .kmlobby .popcard { position:static; width:min(440px, calc(100vw - 32px)); padding:22px 22px 16px; display:flex; flex-direction:column; gap:10px; text-align:center; }
  .kmlobby .kmlt { font-size:17px; font-weight:600; color:var(--text); }
  .kmlobby .kmls { font-size:13px; color:var(--text-dim); line-height:1.5; }
  .kmlobby .kmlw { font-size:12px; color:var(--text-mute); }
  .kmlobby .kmdots { display:flex; gap:6px; justify-content:center; margin:6px 0; }
  .kmlobby .kmdots i { width:8px; height:8px; border-radius:50%; background:var(--asi-blue); opacity:.3; animation:kmDot 1.2s infinite; }
  .kmlobby .kmdots i:nth-child(2) { animation-delay:.2s; } .kmlobby .kmdots i:nth-child(3) { animation-delay:.4s; }
  @keyframes kmDot { 0%,100% { opacity:.25; } 50% { opacity:1; } }
  .kmlobby .kmlb { display:flex; gap:8px; justify-content:center; margin-top:6px; }
  @media (max-width:640px) { .kmgrid { grid-template-columns:1fr; } }`;
  document.head.appendChild(css);

  // ---- who I am (the hub proves it: my name + My room code) ----------------------------------------------------------------
  let codeTyped = "";     // a My room code typed here this session (memory only; never stored by this module)
  let codeStale = false;  // the remembered code was refused -- ask instead of sending it again
  function ident() {
    const p = K.personal();
    const name = String(p?.name || K.me() || "").trim();
    const code = codeTyped || (codeStale ? "" : String(p?.code || ""));
    return name && code ? { pname: name, pcode: code } : null;
  }
  const READS = new Set(["list", "get", "beat", "ics", "icsLink"]);
  async function call(body) {
    const base = K.base(), tok = K.token();
    if (!base || !tok) return { ok: false, error: "Join a room or the Lobby first." };
    const b = { ...body, by: K.me() || undefined };
    const id = ident(); if (id && !b.pname) Object.assign(b, id);
    if (b.room && !b.roomKey) b.roomKey = K.roomKey(b.room);
    T("call", { op: body.op });
    try {
      const go = () => fetch(base + "/api/meetings", { method: "POST", headers: { "content-type": "application/json", authorization: "Bearer " + tok }, body: JSON.stringify(b) });
      let r;
      // a read that hits a dropped connection (seen in the lab while a room switch reconnects) goes once more; a change never repeats
      try { r = await go(); } catch (e) { if (!READS.has(body.op)) throw e; T("retry", { op: body.op }); await new Promise((ok) => setTimeout(ok, 1200)); r = await go(); }
      const d = await r.json().catch(() => ({}));
      if (r.status === 404 && !d.error) return { ok: false, old: true, error: "This relay has no scheduled meetings (an older KASTR)." };
      if (d.wrong) { codeStale = true; codeTyped = ""; }
      if (r.ok) return { ...d, ok: d.ok !== false };
      return { ...d, ok: false, status: r.status, error: String(d.error || ("HTTP " + r.status)).replace(/ -- /g, " — ") };
    } catch (e) { return { ok: false, error: String(e?.message || e) }; }
  }

  // ---- times ------------------------------------------------------------------------------------------------------------
  const pad = (n) => String(n).padStart(2, "0");
  const myTz = () => P.tz();
  const fmtT = (ts, o) => new Date(ts * 1000).toLocaleTimeString([], Object.assign({ hour: "numeric", minute: "2-digit" }, o || {}));
  function dayWord(ts) {
    const d = new Date(ts * 1000), n = new Date(nowS() * 1000);
    const day = (x) => Math.floor((x.getTime() - x.getTimezoneOffset() * 60000) / 86400000);
    const diff = day(d) - day(n);
    if (diff === 0) return "Today";
    if (diff === 1) return "Tomorrow";
    if (diff > 1 && diff < 7) return d.toLocaleDateString([], { weekday: "long" });
    return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: d.getFullYear() === n.getFullYear() ? undefined : "numeric" });
  }
  function whenLine(m) {
    const o = m.next;
    if (!o) return m.cancelled ? "Cancelled" : "No more meetings";
    let s = dayWord(o.start) + " " + fmtT(o.start) + "–" + fmtT(o.end);
    if (m.tz !== myTz()) s += " (" + o.local.slice(11) + " " + (o.abbr || m.tz) + ")";   // the organizer's own wall time too
    return s;
  }
  function repeatWords(m) {
    if (m.freq === "daily") return "Every day" + (m.until ? " until " + m.until : "");
    if (m.freq === "weekly") {
      const ds = (m.days || []).slice().sort();
      const w = ds.length === 5 && ds.every((d, i) => d === i) ? "every weekday" : "every " + ds.map((d) => DAYS_LONG[d]).join(", ");
      return w.charAt(0).toUpperCase() + w.slice(1) + (m.until ? " until " + m.until : "");
    }
    return "Once";
  }
  const inMin = (s) => { const m = Math.max(0, Math.round(s / 60)); return m < 60 ? plural(m, "minute") : m < 1440 ? plural(Math.round(m / 60), "hour") : plural(Math.round(m / 1440), "day"); };
  function localParts(zone, ts) {   // the wall time of `ts` in `zone` (the browser knows every zone)
    try {
      const f = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
      const o = Object.fromEntries(f.formatToParts(new Date(ts * 1000)).map((x) => [x.type, x.value]));
      return { date: o.year + "-" + o.month + "-" + o.day, time: o.hour + ":" + o.minute };
    } catch { const d = new Date(ts * 1000); return { date: d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()), time: pad(d.getHours()) + ":" + pad(d.getMinutes()) }; }
  }
  const dowOf = (date) => { const d = new Date(date + "T12:00:00Z"); return (d.getUTCDay() + 6) % 7; };   // 0 = Monday (the hub's)
  const roleWord = (r) => ({ org: "You organize it", pres: "You present", in: "You are invited", guest: "Guest" }[r] || "");

  // ---- state -----------------------------------------------------------------------------------------------------------
  const S = { d: null, at: 0, busy: false, first: true };
  const titles = new Map();         // room -> title (a meeting's own room reads its title)
  const intent = new Map();         // room -> meeting id: joining a meeting held in an existing room (this visit)
  let here = null;                  // {room, id, title, role, host, guest, key, end}: the meeting I am in
  const KNOWN_KEY = "kastr.meet.known", NOTE_KEY = "kastr.meet.notes";
  const jget = (k, dflt) => { try { const v = JSON.parse(localStorage.getItem(k) || "null"); return v && typeof v === "object" ? v : dflt; } catch { return dflt; } };
  const jset = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
  const mySaves = new Map();        // id -> seq I saved (my own changes are not news to me)

  function creds(room) {   // what rides a mint (authMint): the person -- a meeting's own room always, an existing room while joining a meeting there
    if (P.isMeet(room)) { const id = ident(); return id ? id : (K.me() ? { pname: K.me() } : undefined); }
    const mid = intent.get(room);
    if (mid) { const id = ident(); return id ? { id: mid, ...id } : undefined; }
    return undefined;
  }
  function minted(room, meet, guest) {
    if (meet && meet.id) {
      if (meet.title) titles.set(room, String(meet.title));
      const fresh = !here || here.room !== room || here.id !== meet.id;
      here = { room, id: String(meet.id), title: String(meet.title || ""), role: String(meet.role || (guest ? "guest" : "")), host: !!meet.host, guest: !!guest,
               key: String(meet.key || ""), end: Number(meet.end) || 0, org: String(meet.org || "") };
      lobbyClose(room);
      T("minted", { room, id: here.id, role: here.role, apply: !!meet.apply, fresh });
      if (fresh) { beatSoon(1500); if (!guest) setTimeout(() => toast("You’re in “" + here.title + "”" + (meet.org ? " — organized by " + meet.org : ""), 4000), 800); }
      if (meet.apply && !guest) autoApply(String(meet.apply), room);
      return;
    }
    if (here && here.room !== room && K.room() !== here.room) { T("left", { room: here.room }); here = null; }   // a side token for another room never ends it
    if (!P.isMeet(room) && !intent.has(room)) lobbyClose();
  }
  async function autoApply(tid, room) {   // the first invitee in applies the meeting's template (the hub's lease names this device)
    const until = Date.now() + 25000;
    while (Date.now() < until && !(K.room() === room && K.joined() && K.token())) await new Promise((r) => setTimeout(r, 300));
    if (K.room() !== room) return;
    await new Promise((r) => setTimeout(r, 1200));   // the room's board and people first
    const ui = P.templates();
    if (!ui?.autoApply) { T("apply", { ok: false, why: "no templates module" }); return; }
    try { const d = await ui.autoApply(tid, room, { meetingRoom: P.isMeet(room) }); T("apply", { ok: !!d?.ok }); } catch (e) { T("apply", { ok: false, why: String(e?.message || e) }); }
  }

  // ---- the beat: I am in the meeting (the hub keeps its window open, the host-required lobby learns the host is in) -----------
  let beatT = null;
  function beatSoon(ms) { clearTimeout(beatT); beatT = setTimeout(beat, ms ?? BEAT_MS); }
  async function beat() {
    if (!here) return;
    if (K.room() !== here.room || !K.joined()) { if (K.room() !== here.room) here = null; else beatSoon(); return; }
    const d = await call({ op: "beat", id: here.id });
    if (!here) return;
    T("beat", { ok: d.ok, n: d.live?.n, ended: !!d.ended });
    if (d.ok && d.ended && !d.none) return ended(d.cancelled ? "cancelled" : "ended");
    if (d.ok && d.none && d.ended) return ended("ended");
    if (d.ok && d.occ?.end) here.end = d.occ.end;
    beatSoon();
  }
  function ended(why) {
    const m = here; here = null;
    if (!m) return;
    T("ended", { room: m.room, why });
    const title = why === "cancelled" ? "Meeting cancelled" : "Meeting ended";
    const msg = "“" + (m.title || "The meeting") + "” " + (why === "cancelled" ? "was cancelled." : "has ended.");
    if (P.isMeet(m.room) && K.room() === m.room) P.leave(title, msg);   // its own room: everyone goes back to their main room
    else toast(msg, 6000);
  }

  // ---- the lobby: early, or waiting for the host -------------------------------------------------------------------------
  let lobbyEl = null, lobbyT = null, lobbyTick = null;
  const L = { room: "", meet: null, retry: null, tries: 0 };
  function refused(room, meet, retry) {
    const v = String(meet?.verdict || "");
    T("refused", { room, v });
    if (meet?.title && P.isMeet(room)) titles.set(room, String(meet.title));
    if (v !== "early" && v !== "wait") {
      lobbyClose();
      if (v === "who" || v === "locked" || v === "wrong") setTimeout(() => openList(null, true), 300);   // say who I am, then Join again
      return false;
    }
    L.room = room; L.meet = meet; L.retry = retry; L.tries++;
    lobbyShow();
    clearTimeout(lobbyT);
    let wait = 10000;
    if (v === "early" && meet.next?.opens) wait = Math.min(60000, Math.max(3000, (meet.next.opens - nowS()) * 1000 + 1500));
    lobbyT = setTimeout(() => { if (!lobbyEl?.hidden && L.room === room) { T("lobby-retry", { room }); try { L.retry?.(); } catch {} } }, wait);
    return true;
  }
  function lobbyShow() {
    if (!lobbyEl) {
      lobbyEl = document.createElement("div");
      lobbyEl.id = "kMeetLobby"; lobbyEl.className = "kmlobby"; lobbyEl.hidden = true;
      lobbyEl.innerHTML = '<div class="popcard" role="dialog" aria-modal="true" aria-labelledby="kmLobT"><div class="kmlt" id="kmLobT"></div><div class="kmls"></div>'
        + '<div class="kmdots" aria-hidden="true"><i></i><i></i><i></i></div><div class="kmlw"></div><div class="kmlb"></div></div>';
      document.body.appendChild(lobbyEl);
      const b = lobbyEl.querySelector(".kmlb");
      const now = document.createElement("button"); now.type = "button"; now.textContent = "Try now"; now.className = "ghost";
      now.onclick = () => { clearTimeout(lobbyT); try { L.retry?.(); } catch {} };
      const out = document.createElement("button"); out.type = "button"; out.textContent = "Leave"; out.className = "ghost";
      out.onclick = () => { T("lobby-leave", { room: L.room }); lobbyClose(); };
      b.append(now, out);
    }
    lobbyPaint();
    lobbyEl.hidden = false;
    clearInterval(lobbyTick); lobbyTick = setInterval(lobbyPaint, 1000);
  }
  function lobbyPaint() {
    if (!lobbyEl) return;
    const m = L.meet || {}, v = m.verdict;
    lobbyEl.querySelector(".kmlt").textContent = m.title || "Meeting";
    const s = lobbyEl.querySelector(".kmls"), w = lobbyEl.querySelector(".kmlw");
    if (v === "wait") {
      s.textContent = "Waiting for " + (m.org || "the host") + " to start the meeting. You’ll be let in as soon as the organizer or a presenter joins.";
      w.textContent = "Checking every few seconds…";
    } else {
      const opens = m.next?.opens || 0, left = opens - nowS();
      s.textContent = "This meeting starts " + (m.next?.start ? dayWord(m.next.start).toLowerCase().replace(/^(mon|tue|wed|thu|fri|sat|sun)/i, (x) => "on " + x) + " at " + fmtT(m.next.start) : "later") + ". Its room opens 10 minutes before.";
      w.textContent = left > 0 ? "Opens in " + (left < 90 ? Math.ceil(left) + " s" : inMin(left)) + " — you’ll go in automatically." : "Opening…";
    }
  }
  function lobbyClose(room) {
    if (!lobbyEl || lobbyEl.hidden) return;
    if (room && L.room && room !== L.room) return;
    lobbyEl.hidden = true; clearTimeout(lobbyT); clearInterval(lobbyTick);
    L.room = ""; L.meet = null; L.retry = null; L.tries = 0;
  }

  // ---- joining a meeting from the list ---------------------------------------------------------------------------------
  async function join(m) {
    T("join", { id: m.id, own: P.isMeet(m.room) });
    if (K.room() === m.room && K.joined()) { toast("You’re in “" + m.title + "” already.", 3000); return; }
    if (m.title) titles.set(m.room, m.title);
    if (!P.isMeet(m.room)) intent.set(m.room, m.id);
    closeAll();
    try { await K.go(m.room); } catch (e) { toast("Could not join “" + m.title + "”: " + (e?.message || e), 6000, "warn"); }
  }

  // ---- shared dialog shell (the templates' classes) --------------------------------------------------------------------
  function shell(id, title, top) {
    const el = document.createElement("div");
    el.id = id; el.className = "kt-scrim" + (top ? " kt-top" : ""); el.hidden = true;
    el.innerHTML = '<div class="popcard ktdlg" role="dialog" aria-modal="true"><div class="head"><span class="ttl">' + esc(title) + '</span><span class="sp"></span><button type="button" class="close" title="Close">✕</button></div>'
      + '<div class="body"></div><div class="foot"></div></div>';
    document.body.appendChild(el);
    const close = () => { el.hidden = true; document.removeEventListener("keydown", el.__key, true); };
    el.__close = close;
    el.__key = (e) => {
      if (e.key === "Escape") { if (document.getElementById("kConfirm") && !document.getElementById("kConfirm").hidden) return; e.preventDefault(); e.stopPropagation(); close(); }
    };
    // the page's shortcuts stay quiet while typing here -- stopped as the key leaves the dialog (bubbling), so the dialog's own
    // fields still get it (a stop in the document's capture phase never reaches them: Enter in "Invite people")
    el.addEventListener("keydown", (e) => { if (e.key !== "Tab" && e.key !== "Escape") e.stopPropagation(); });
    el.querySelector(".close").onclick = close;
    el.addEventListener("click", (e) => { if (e.target === el) close(); });
    el.__open = () => { el.hidden = false; document.addEventListener("keydown", el.__key, true); };
    el.__body = el.querySelector(".body"); el.__foot = el.querySelector(".foot"); el.__title = el.querySelector(".ttl");
    return el;
  }
  const btn = (text, cls, fn) => { const b = document.createElement("button"); b.type = "button"; if (cls) b.className = cls; b.textContent = text; if (fn) b.onclick = fn; return b; };
  const div = (cls, html) => { const d = document.createElement("div"); if (cls) d.className = cls; if (html != null) d.innerHTML = html; return d; };
  // every on/off option is a switch (Kenton): the page's span.switch markup, the words beside it one click target
  const sw = (text, on, change, title) => {
    const l = document.createElement("label"); l.className = "ktsw" + (on ? " on" : "");
    const w = document.createElement("span"); w.className = "switch sm";
    const cb = document.createElement("input"); cb.type = "checkbox";   // the switch's own input (span.switch)
    w.append(cb, document.createElement("i"));
    const t = document.createElement("span"); t.textContent = text; if (title) l.title = title;
    l.append(w, t);
    cb.checked = !!on; cb.setAttribute("aria-label", text);
    cb.onchange = () => { change(cb.checked); l.classList.toggle("on", cb.checked); };
    return l;
  };
  const field = (label, ...kids) => { const f = div("field"); const l = document.createElement("span"); l.className = "lbl"; l.textContent = label; f.append(l, ...kids); return f; };
  const input = (type, value, attrs) => { const i = document.createElement("input"); i.type = type; i.value = value ?? ""; for (const [k, v] of Object.entries(attrs || {})) i.setAttribute(k, v); return i; };
  // a confirm over the meetings' own dialogs: the details / form (kt-top, 141) and the lobby (142) sit above #kConfirm (140), so they
  // step under it meanwhile (else "Cancel meeting" asks behind its own dialog and nothing can be clicked)
  async function ask(o) {
    const up = [...document.querySelectorAll(".kt-scrim.kt-top:not([hidden]), .kmlobby:not([hidden])")];
    up.forEach((e) => e.classList.add("km-under"));
    try { return await K.confirm(o); } finally { up.forEach((e) => e.classList.remove("km-under")); }
  }
  function closeAll() { for (const el of [listEl, formEl, detEl]) el?.__close?.(); }

  // ======================================================================================================================
  // THE LIST: More > Meetings... -- the meetings I am invited to (Live now, Coming up, Cancelled)
  // ======================================================================================================================
  let listEl = null;
  async function openList(_x, gate) {
    if (!available()) { toast("Meetings need a relay with access codes — join a room or the Lobby there first.", 5000, "warn"); return; }
    try { K.closePops(); } catch {}
    if (!listEl) listEl = shell("kMeet", "Meetings");
    listEl.__gate = !!gate;
    listEl.__open();
    paintList();
    await load();
    paintList();
  }
  async function load() {
    S.busy = true;
    const d = await call({ op: "list" });
    S.busy = false;
    if (d.ok) {
      if (d.now) skew = d.now - Date.now() / 1000;
      news(S.d, d);
      S.d = d; S.at = Date.now();
      for (const m of d.meetings || []) titles.set(m.room, m.title);
      T("list", { n: (d.meetings || []).length, me: !!d.me });
    } else if (!S.d || d.wrong) S.d = d;
    if (listEl && !listEl.hidden) paintList();
    if (detEl && !detEl.hidden && D.m) { const m = (S.d?.meetings || []).find((x) => x.id === D.m.id); if (m) { D.m = m; paintDet(); } }
    return d;
  }
  function stateOf(m) {
    if (m.cancelled) return "cancelled";
    if (m.open || m.next?.state === "open" || m.live?.n) return "live";
    return m.next ? "later" : "over";
  }
  function row(m) {
    const st = stateOf(m), o = m.next;
    const r = div("ktrow");
    r.dataset.mid = m.id;
    const badge = st === "live" ? '<span class="kmlive">' + (m.live?.n ? "Live · " + m.live.n : "Open") + "</span>"
      : o && o.start - nowS() < 3600 && o.start > nowS() ? '<span class="kmlive kmsoon">in ' + esc(inMin(o.start - nowS())) + "</span>" : "";
    r.innerHTML = '<div class="ktm"><span class="ktn' + (m.cancelled ? " kmcan" : "") + '">' + esc(m.title) + badge + "</span>"
      + '<span class="kmwhen">' + esc(m.cancelled ? "Cancelled" : whenLine(m)) + "</span>"
      + '<span class="ktc">' + esc([repeatWords(m), m.org ? "organized by " + (m.role === "org" ? "you" : m.org) : "", P.isMeet(m.room) ? "" : "in " + K.title(m.room),
        m.host ? "waits for the host" : ""].filter(Boolean).join(" · ")) + "</span></div><div class=\"ktb\"></div>";
    const b = r.querySelector(".ktb");
    if (st === "live" && !(K.room() === m.room && K.joined())) b.append(btn("Join", "", () => join(m)));
    else if (K.room() === m.room && K.joined() && !m.cancelled) b.append(btn("You’re here", "ghost", () => openDet(m)));
    b.append(btn("Details…", "ghost", () => openDet(m)));
    return r;
  }
  function paintList() {
    if (!listEl) return;
    const d = S.d, body = listEl.__body, foot = listEl.__foot;
    body.replaceChildren(); foot.replaceChildren();
    const cur = (here && K.room() === here.room && K.joined()) ? here : null;   // the meeting I am in: my mint said so, else the list does
    const curM = (d?.meetings || []).find((x) => (cur ? x.id === cur.id : x.room === K.room() && K.joined() && !x.cancelled));
    if (cur || curM) {
      const id = cur?.id || curM.id, title = cur?.title || curM.title;
      const box = div("ktbox");
      const l = div("ktline", "<span>" + esc("You’re in “" + title + "”") + "</span>");
      if (curM) l.append(btn("Details…", "ghost", () => openDet(curM)));
      if (cur?.host || ["org", "pres"].includes(cur?.role || curM?.role) || curM?.manage) l.append(btn("End meeting…", "danger", () => endMeeting(id, title)));
      box.append(l); body.append(box);
    }
    if (S.busy && !d) body.append(div("msg", "Loading…"));
    if (d && !d.ok) body.append(Object.assign(div("msg err"), { textContent: d.error || "Could not load the meetings." }));
    if (d?.ok && (!d.me || listEl.__gate)) body.append(whoGate(d));
    const rows = d?.meetings || [];
    const live = rows.filter((m) => stateOf(m) === "live"), later = rows.filter((m) => stateOf(m) === "later"), can = rows.filter((m) => m.cancelled);
    const sec = (t, list) => { if (!list.length) return; body.append(div("kmsec", esc(t))); const l = div("ktlist"); for (const m of list) l.append(row(m)); body.append(l); };
    sec("Live now", live); sec("Coming up", later); sec("Cancelled", can);
    if (d?.ok && !rows.length) body.append(div("ktempty", d.me ? "No meetings yet. Meetings you are invited to show here — and the ones you schedule." : "Meetings you are invited to show here once KASTR knows who you are."));
    const canSchedule = d?.ok && (d.can?.own || d.can?.room || d.can?.any);
    if (canSchedule) foot.append(btn("Schedule a meeting…", "", () => openForm(null)));
    foot.append(div("sp"), btn("Close", "ghost", () => listEl.__close()));
  }
  function whoGate(d) {   // name + My room code -> who I am this session (the code is held in memory only)
    const box = div("ktbox");
    const p = K.personal();
    box.innerHTML = '<p class="hint">' + (d.mineError ? esc(d.mineError.replace(/ -- /g, " — ")) + " " : "")
      + "Meetings follow you to any device under your name and your <b>My room</b> code — they say who you are when you join one." + (p ? "" : " You have no My room on this device yet.") + "</p>"
      + '<div class="row2"><input type="text" class="kmpn" maxlength="48" placeholder="Your name" aria-label="Your name"><input type="text" class="kmpc masked" placeholder="My room code" aria-label="My room code" autocomplete="off"></div>'
      + '<div class="ktacts"></div><p class="msg"></p>';
    box.querySelector(".kmpn").value = String(p?.name || K.me() || "");
    const go = async () => {
      const name = box.querySelector(".kmpn").value.trim(), code = box.querySelector(".kmpc").value;
      if (!name || !code) { box.querySelector(".msg").textContent = "Your name and your My room code."; return; }
      codeTyped = code; codeStale = false;
      const r = await call({ op: "list", pname: name, pcode: code });
      if (r.ok && r.me) { if (listEl) listEl.__gate = false; S.d = r; paintList(); return; }
      codeTyped = "";
      const msg = box.querySelector(".msg"); msg.textContent = r.mineError || r.error || "Refused."; msg.classList.add("err");
    };
    box.querySelector(".kmpc").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
    box.querySelector(".ktacts").append(btn("Show my meetings", "", go), ...(p ? [] : [btn("Make My room…", "ghost", () => { listEl?.__close(); K.myRoomDialog(); })]));
    return box;
  }

  // ======================================================================================================================
  // DETAILS: when, who, Join, the links, the calendar file; the organizer edits, moves or cancels one, cancels the series
  // ======================================================================================================================
  let detEl = null;
  const D = { m: null };
  function openDet(m) {
    if (!detEl) detEl = shell("kMeetDet", "Meeting", true);
    D.m = m;
    detEl.__open();
    paintDet();
  }
  function paintDet() {
    const m = D.m; if (!m || !detEl) return;
    detEl.__title.textContent = m.title;
    const body = detEl.__body, foot = detEl.__foot;
    body.replaceChildren(); foot.replaceChildren();
    const st = stateOf(m), o = m.next;
    const dl = document.createElement("dl"); dl.className = "kmdl";
    const add = (k, v) => { const a = document.createElement("dt"); a.textContent = k; const b = document.createElement("dd"); b.textContent = v; dl.append(a, b); };
    add("When", m.cancelled ? "Cancelled" : whenLine(m) + (o?.moved ? " (moved)" : ""));
    add("Repeats", repeatWords(m));
    if (m.tz !== myTz()) add("Time zone", m.tz);
    add("Organizer", m.role === "org" ? "You" : m.org);
    add("Where", P.isMeet(m.room) ? "Its own room (only the people invited)" : K.title(m.room));
    add("Invited", (m.people || []).length ? m.people.map((x) => x.name + (x.pres ? " (presenter)" : "")).join(", ") : "Nobody yet");
    const opts = [m.host ? "Waits for the host" : "Opens without the host", m.guests ? "Guests with a link" : "No guests", m.tpl ? "A template is applied at the start" : ""].filter(Boolean);
    add("Options", opts.join(" · "));
    if (m.role) add("You", roleWord(m.role));
    body.append(dl);
    if (m.note) body.append(div("hint", esc(m.note).replace(/\n/g, "<br>")));
    const acts = div("kmacts");
    const isHere = K.room() === m.room && K.joined();
    if (!m.cancelled) {
      if (st === "live" && !isHere) acts.append(btn("Join", "", () => join(m)));
      else if (o && !isHere) { const b = btn("Opens " + dayWord(o.start - 600).toLowerCase() + " " + fmtT(o.start - 600), "ghost"); b.disabled = true; acts.append(b); }
      acts.append(btn("Download .ics", "ghost", () => icsDownload(m)), btn("Copy calendar link", "ghost", () => icsLink(m)));
      if (m.guests && P.isMeet(m.room) && (m.role === "org" || m.role === "pres" || (isHere && here?.host))) acts.append(btn("Copy guest link", "ghost", () => guestLink(m)));
      if (isHere && (m.role === "org" || m.role === "pres" || here?.host)) acts.append(btn("End meeting…", "danger", () => endMeeting(m.id, m.title)));
    }
    body.append(acts);
    if (m.manage && !m.cancelled) {
      const mg = div("kmacts");
      mg.append(btn("Edit the series…", "ghost", () => openForm(m)));
      if (o && m.freq !== "once") mg.append(btn("Move this one…", "ghost", () => moveOne(m)), btn("Cancel this one…", "ghost", () => cancelOne(m)));
      mg.append(btn("Cancel meeting…", "danger", () => cancelSeries(m)));
      body.append(div("kmsec", "Organizer"), mg);
    }
    if (m.manage && m.cancelled) { const mg = div("kmacts"); mg.append(btn("Delete", "danger", () => delMeeting(m))); body.append(mg); }
    const msg = document.createElement("p"); msg.className = "msg"; msg.setAttribute("role", "status"); body.append(msg);
    detEl.__say = (s, bad) => { msg.textContent = s || ""; msg.classList.toggle("err", !!bad); };
    foot.append(div("sp"), btn("Close", "ghost", () => detEl.__close()));
  }
  const joinUrl = (m) => location.origin + location.pathname + "#meet=" + m.id;
  async function icsDownload(m) {
    const d = await call({ op: "ics", id: m.id, joinUrl: joinUrl(m) });
    if (!d.ok) { detEl?.__say(d.error, true); return; }
    const blob = new Blob([d.text], { type: "text/calendar;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = d.name || "meeting.ics";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 30000);
    window.__kmeetLastIcs = { name: a.download, bytes: blob.size, at: Date.now() };   // rig (no secret)
    T("ics", { bytes: blob.size });
    detEl?.__say("Saved " + a.download + " — open it to add the meeting to your calendar.");
  }
  async function icsLink(m) {
    const d = await call({ op: "icsLink", id: m.id });
    if (!d.ok) { detEl?.__say(d.error, true); return; }
    const url = K.base() + d.path;
    let ok = false; try { await navigator.clipboard.writeText(url); ok = true; } catch {}
    T("icsLink", { copied: ok });
    detEl?.__say(ok ? "Calendar link copied — add it to your calendar app as a subscription (it follows changes)." : "Copy failed — try again.", !ok);
  }
  async function guestLink(m) {
    const d = await call({ op: "link", id: m.id });
    if (!d.ok) { detEl?.__say(d.error, true); return; }
    const link = await Promise.resolve().then(() => K.inviteLink(d.token, m.room)).catch(() => "");
    if (!link) { detEl?.__say("No address others can reach yet — turn on 'Allow other machines to connect' on the Relay page.", true); return; }
    let ok = false; try { await navigator.clipboard.writeText(link); ok = true; } catch {}
    T("guestLink", { copied: ok, changed: !!d.changed });
    detEl?.__say(ok ? "Guest link copied — anyone with it joins this meeting while it is open (no code needed)." : "Copy failed — try again.", !ok);
  }
  async function endMeeting(id, title) {
    if (!(await ask({ title: "End meeting", message: "End “" + title + "” for everyone?", detail: "Everyone in it goes back to their main room. The next one in the series opens as scheduled.", ok: "End meeting", danger: true }))) return;
    const d = await call({ op: "end", id });
    T("end", { ok: d.ok, closed: !!d.closed });
    if (!d.ok) { toast("End meeting: " + d.error, 6000, "warn"); return; }
    closeAll();
    if (here && here.id === id) ended("ended");
    else if (P.isMeet(K.room()) && (S.d?.meetings || []).some((x) => x.id === id && x.room === K.room())) P.leave("Meeting ended", "“" + title + "” has ended.");
    load();
  }
  async function moveOne(m) {
    const o = m.next; if (!o) return;
    const box = div("ktbox");
    const di = input("date", o.local.slice(0, 10)), ti = input("time", o.local.slice(11));
    box.append(div("hint", "Move only the meeting of " + esc(dayWord(o.start)) + " (" + esc(o.local.replace("T", " ")) + ", " + esc(m.tz) + "). The rest of the series stays."),
      div("row2"));
    box.lastChild.append(di, ti);
    detEl.__body.prepend(box);
    const save = btn("Move it", "", async () => {
      const d = await call({ op: "occ", id: m.id, key: o.key, start: di.value + "T" + ti.value });
      if (!d.ok) { detEl.__say(d.error, true); return; }
      mySaves.set(m.id, d.meeting.seq);
      D.m = { ...m, ...d.meeting }; paintDet(); load();
      toast("Moved — the invitees see the new time.", 4000);
    });
    box.append(save);
  }
  async function cancelOne(m) {
    const o = m.next; if (!o) return;
    if (!(await ask({ title: "Cancel one meeting", message: "Cancel “" + m.title + "” on " + dayWord(o.start) + " at " + fmtT(o.start) + "?", detail: "Only this one — the series goes on.", ok: "Cancel this one", cancel: "Keep it" }))) return;
    const d = await call({ op: "occ", id: m.id, key: o.key, cancel: true });
    if (!d.ok) { detEl.__say(d.error, true); return; }
    mySaves.set(m.id, d.meeting.seq);
    D.m = { ...m, ...d.meeting }; paintDet(); load();
    toast("Cancelled that one — the invitees see it.", 4000);
  }
  async function cancelSeries(m) {
    if (!(await ask({ title: "Cancel meeting", message: "Cancel “" + m.title + "”" + (m.freq === "once" ? "" : " — every one still to come") + "?",
      detail: "The invitees see it cancelled in Meetings (and a calendar that subscribed drops it). " + (P.isMeet(m.room) ? "Its room closes and its guest link stops." : ""), ok: "Cancel meeting", cancel: "Keep it", danger: true }))) return;
    const d = await call({ op: "cancel", id: m.id });
    T("cancel", { ok: d.ok });
    if (!d.ok) { detEl.__say(d.error, true); return; }
    mySaves.set(m.id, d.meeting.seq);
    D.m = { ...m, ...d.meeting }; paintDet(); load();
    toast("“" + m.title + "” cancelled.", 4000);
  }
  async function delMeeting(m) {
    const d = await call({ op: "delete", id: m.id });
    if (!d.ok) { detEl.__say(d.error, true); return; }
    detEl.__close(); load();
  }

  // ======================================================================================================================
  // THE FORM: schedule a meeting / edit the series
  // ======================================================================================================================
  let formEl = null;
  const F = { m: null, v: null, tpls: null };
  async function openForm(m) {
    if (!formEl) formEl = shell("kMeetForm", "Schedule a meeting", true);
    const start = nowS() + 3600, tz = m?.tz || myTz();
    const lp = localParts(tz, Math.ceil(start / 1800) * 1800);
    F.m = m || null;
    F.v = m ? { title: m.title, note: m.note || "", date: m.start.slice(0, 10), time: m.start.slice(11), dur: m.dur, tz: m.tz, freq: m.freq, days: (m.days || []).slice(), until: m.until || "",
                people: (m.people || []).map((x) => ({ name: x.name, pres: !!x.pres })), host: !!m.host, guests: !!m.guests, tpl: m.tpl || "", room: P.isMeet(m.room) ? "" : m.room }
      : { title: "", note: "", date: lp.date, time: lp.time, dur: 30, tz, freq: "once", days: [], until: "", people: [], host: false, guests: false, tpl: "", room: "" };
    formEl.__title.textContent = m ? "Edit “" + m.title + "”" : "Schedule a meeting";
    formEl.__open();
    paintForm();
    F.tpls = null;
    F.tpls = await templates();
    if (!formEl.hidden) paintForm(true);
  }
  async function templates() {   // the templates I could pick: my own + this room's (the hub checks again at save)
    const base = K.base(), tok = K.token();
    if (!base || !tok || K.room() === K.lobby()) { const id = ident(); if (!id) return []; }
    try {
      const b = { op: "list", ...(ident() || {}) };
      const r = await fetch(base + "/api/templates", { method: "POST", headers: { "content-type": "application/json", authorization: "Bearer " + tok }, body: JSON.stringify(b) });
      const d = await r.json().catch(() => ({}));
      const out = [];
      for (const t of d.mine || []) out.push({ id: t.id, name: t.name + " (mine)" });
      for (const t of d.templates || []) out.push({ id: t.id, name: t.name + " (" + K.title(K.room()) + ")", room: K.room() });
      return out;
    } catch { return []; }
  }
  function paintForm(keepFocus) {
    const v = F.v, body = formEl.__body, foot = formEl.__foot, d = S.d || {};
    const act = document.activeElement, actKey = act?.dataset?.k;
    body.replaceChildren(); foot.replaceChildren();
    const ti = input("text", v.title, { maxlength: "80", placeholder: "Weekly stand-up", "data-k": "title" });
    ti.oninput = () => { v.title = ti.value; };
    body.append(field("Title", ti));
    const grid = div("kmgrid");
    const di = input("date", v.date, { "data-k": "date" }); di.onchange = () => { v.date = di.value; if (v.freq === "weekly" && !v.days.length) v.days = [dowOf(v.date)]; paintForm(true); };
    const tt = input("time", v.time, { "data-k": "time", step: "300" }); tt.onchange = () => { v.time = tt.value; };
    const du = document.createElement("select"); du.dataset.k = "dur";
    for (const n of [...new Set([...DURS, v.dur])].sort((a, b) => a - b)) { const o = document.createElement("option"); o.value = n; o.textContent = n < 60 ? n + " min" : (n / 60) + " h" + (n % 60 ? " " + (n % 60) + " min" : ""); du.append(o); }
    du.value = String(v.dur); du.onchange = () => { v.dur = Number(du.value); };
    const tz = input("text", v.tz, { list: "kmTzList", "data-k": "tz", spellcheck: "false", autocomplete: "off" }); tz.onchange = () => { v.tz = tz.value.trim(); };
    if (!document.getElementById("kmTzList")) {
      const dl = document.createElement("datalist"); dl.id = "kmTzList";
      let zones = []; try { zones = Intl.supportedValuesOf("timeZone"); } catch {}
      for (const z of zones) { const o = document.createElement("option"); o.value = z; dl.append(o); }
      document.body.append(dl);
    }
    grid.append(field("Date", di), field("Start", tt), field("Length", du), field("Time zone", tz));
    body.append(grid);
    // repeats
    const seg = div("ktseg");
    for (const [k, t] of [["once", "Once"], ["daily", "Daily"], ["weekly", "Weekly"]]) {
      const b = btn(t, v.freq === k ? "on" : "", () => { v.freq = k; if (k === "weekly" && !v.days.length) v.days = [dowOf(v.date)]; paintForm(true); });
      b.dataset.freq = k; seg.append(b);
    }
    const rep = field("Repeats", seg);
    if (v.freq === "weekly") {
      const days = div("kmdays");
      DAYS.forEach((t, i) => {
        const c = btn(t, "ktchip" + (v.days.includes(i) ? " on" : ""), () => {
          if (v.days.includes(i)) { if (v.days.length > 1) v.days = v.days.filter((x) => x !== i); } else v.days = [...v.days, i].sort();
          paintForm(true);
        });
        c.setAttribute("aria-pressed", v.days.includes(i) ? "true" : "false"); days.append(c);
      });
      rep.append(days);
    }
    if (v.freq !== "once") {
      const r2 = div("row2");
      const ui = input("date", v.until, { "data-k": "until" }); ui.onchange = () => { v.until = ui.value; };
      ui.hidden = !v.until;
      r2.append(sw("Ends on a date", !!v.until, (on) => { v.until = on ? (v.until || addDays(v.date, 90)) : ""; paintForm(true); }), ui);
      rep.append(r2);
    }
    body.append(rep);
    // where
    const can = d.can || {};
    if (!F.m && (can.room || can.any)) {
      const sel = document.createElement("select"); sel.dataset.k = "room";
      const opt = (val, t) => { const o = document.createElement("option"); o.value = val; o.textContent = t; sel.append(o); };
      opt("", "Its own room — only the people invited");
      const rooms = can.any ? K.rooms() : K.rooms().filter((r) => r.slug === K.room());
      for (const r of rooms) if (!P.isHidden(r.slug)) opt(r.slug, "In " + r.title + (r.slug === K.room() ? " (this room)" : ""));
      sel.value = v.room; sel.onchange = () => { v.room = sel.value; paintForm(true); };
      body.append(field("Where", sel));
    } else if (F.m && v.room) body.append(field("Where", div("hint", "In " + esc(K.title(v.room)))));
    // people
    const pf = field("Invite people");
    const pl = div("kmpeople");
    v.people.forEach((x, i) => {
      const r = div("kmperson");
      const nm = document.createElement("span"); nm.className = "nm"; nm.textContent = x.name;
      r.append(nm, sw("Presenter", x.pres, (on) => { x.pres = on; }, "A presenter can let people in, copy the guest link and end the meeting"), btn("✕", "ghost", () => { v.people.splice(i, 1); paintForm(true); }));
      r.lastChild.title = "Remove " + x.name; r.lastChild.setAttribute("aria-label", "Remove " + x.name);
      pl.append(r);
    });
    const add = div("row2");
    const pi = input("text", "", { list: "kmPeopleList", placeholder: "A name, as they appear in KASTR", maxlength: "48", "data-k": "person", autocomplete: "off" });
    let dl = document.getElementById("kmPeopleList");
    if (!dl) { dl = document.createElement("datalist"); dl.id = "kmPeopleList"; document.body.append(dl); }
    dl.replaceChildren();
    Promise.resolve().then(() => K.people()).then((rows) => {   // who is online + All people (the Messages picker's list)
      for (const x of rows || []) { const n = String(x?.name || x || "").trim(); if (n) { const o = document.createElement("option"); o.value = n; dl.append(o); } }
    }).catch(() => {});
    const addIt = () => {
      const n = pi.value.trim().replace(/\s+/g, " ");
      if (!n) return;
      if (!v.people.some((x) => x.name.toLowerCase() === n.toLowerCase())) v.people.push({ name: n, pres: false });
      paintForm(true);
      setTimeout(() => formEl.querySelector('[data-k="person"]')?.focus(), 0);
    };
    pi.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addIt(); } });
    add.append(pi, btn("Add", "ghost", addIt));
    pf.append(pl, add, div("hint", "Invited people find it in Meetings under their own name (and their My room code); nobody else sees it."));
    body.append(pf);
    // switches
    const sws = div("ktbox");
    sws.append(sw("Requires the host to join", v.host, (on) => { v.host = on; }, "Invitees wait in a lobby until you (or a presenter) join"));
    if (!v.room) sws.append(sw("Guests with a link", v.guests, (on) => { v.guests = on; }, "A link anyone can use to join while the meeting is open — no name or code needed"));
    body.append(field("Options", sws));
    // template
    const ts = document.createElement("select"); ts.dataset.k = "tpl";
    { const o = document.createElement("option"); o.value = ""; o.textContent = "None"; ts.append(o); }
    for (const t of F.tpls || []) { if (t.room && t.room !== (v.room || "") && v.room !== t.room && P.isMeet(K.room())) continue; const o = document.createElement("option"); o.value = t.id; o.textContent = t.name; ts.append(o); }
    if (v.tpl && ![...ts.options].some((o) => o.value === v.tpl)) { const o = document.createElement("option"); o.value = v.tpl; o.textContent = "(the template chosen before)"; ts.append(o); }
    ts.value = v.tpl; ts.onchange = () => { v.tpl = ts.value; };
    body.append(field("Template (optional)", ts, div("hint", F.tpls === null ? "Loading your templates…" : "Applied by the first person in when the meeting opens — layout, cameras, presentation and roles.")));
    const note = document.createElement("textarea"); note.maxLength = 500; note.value = v.note; note.placeholder = "Agenda, notes (optional)"; note.dataset.k = "note";
    note.oninput = () => { v.note = note.value; };
    body.append(field("Note", note));
    const msg = document.createElement("p"); msg.className = "msg"; msg.setAttribute("role", "status"); body.append(msg);
    formEl.__say = (s, bad) => { msg.textContent = s || ""; msg.classList.toggle("err", !!bad); };
    const go = btn(F.m ? "Save changes" : "Schedule", "kmgo", save);
    foot.append(div("sp"), btn("Cancel", "ghost", () => formEl.__close()), go);
    if (keepFocus && actKey) { const el = formEl.querySelector('[data-k="' + actKey + '"]'); if (el) setTimeout(() => el.focus(), 0); }
    else if (!keepFocus) setTimeout(() => ti.focus(), 0);
  }
  function addDays(date, n) { const d = new Date(date + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
  async function save() {
    const v = F.v, go = formEl.querySelector(".kmgo");
    if (!v.title.trim()) { formEl.__say("Give the meeting a title.", true); return; }
    if (!v.date || !v.time) { formEl.__say("Pick a date and a start time.", true); return; }
    if (!ident()) { formEl.__say("KASTR needs to know who you are — your name and My room code (Meetings ▸ Show my meetings).", true); return; }
    const meeting = { title: v.title.trim(), note: v.note.trim(), tz: v.tz || myTz(), start: v.date + "T" + v.time, dur: v.dur, freq: v.freq,
                      days: v.freq === "weekly" ? v.days : [], until: v.freq !== "once" ? v.until : "", people: v.people, host: v.host, guests: !v.room && v.guests, tpl: v.tpl };
    if (F.m) meeting.id = F.m.id; else if (v.room) meeting.room = v.room;
    go.disabled = true; formEl.__say(F.m ? "Saving…" : "Scheduling…");
    const d = await call({ op: "save", meeting, room: v.room || undefined });
    go.disabled = false;
    T("save", { ok: d.ok, edit: !!F.m, freq: v.freq });
    if (!d.ok) { formEl.__say(d.error || "Refused.", true); return; }
    mySaves.set(d.meeting.id, d.meeting.seq);
    titles.set(d.meeting.room, d.meeting.title);
    formEl.__close();
    toast((F.m ? "Saved “" : "Scheduled “") + d.meeting.title + "” — " + whenLine(d.meeting), 5000);
    await load();
    openDet((S.d?.meetings || []).find((x) => x.id === d.meeting.id) || d.meeting);
  }

  // ======================================================================================================================
  // NEWS: invited, changed, cancelled; the reminder 5 minutes before; the Join prompt at the start
  // ======================================================================================================================
  function news(prev, d) {
    const known = jget(KNOWN_KEY, {});
    const first = !Object.keys(known).length && S.first;
    S.first = false;
    const next = {};
    for (const m of d.meetings || []) {
      next[m.id] = m.seq;
      if (first) continue;
      const was = known[m.id];
      if (was === undefined) {
        if (m.role !== "org" && !m.cancelled) toast("You’re invited to “" + m.title + "” — " + whenLine(m), 12000, "event", { label: "Details", fn: () => openDet(m) });
      } else if (m.seq > was && mySaves.get(m.id) !== m.seq) {
        T("news", { id: m.id, kind: m.cancelled ? "cancelled" : "changed" });
        if (m.cancelled) toast("“" + m.title + "” was cancelled by " + m.org + ".", 12000, "warn");
        else toast("“" + m.title + "” changed — " + whenLine(m), 12000, "event", { label: "Details", fn: () => openDet(m) });
      }
    }
    jset(KNOWN_KEY, next);
  }
  function tick() {
    const d = S.d;
    if (!d?.ok || !available()) return;
    const now = nowS(), notes = jget(NOTE_KEY, {});
    let dirty = false;
    for (const m of d.meetings || []) {
      const o = m.next;
      if (!o || m.cancelled || (K.room() === m.room && K.joined())) continue;
      const k = m.id + "|" + o.key;
      if (o.start - now <= (d.limits?.remind || 300) && o.start - now > 30 && !notes[k + "|r"]) {
        notes[k + "|r"] = Math.round(now); dirty = true;
        T("remind", { id: m.id });
        toast("“" + m.title + "” starts in " + inMin(o.start - now) + " (" + fmtT(o.start) + ")", 20000, "event", { label: "Join", fn: () => join(m) });
      }
      if (now >= o.start - 30 && now < o.end && !notes[k + "|j"]) {
        notes[k + "|j"] = Math.round(now); dirty = true;
        T("prompt", { id: m.id });
        ask({ title: "Meeting starting", message: "“" + m.title + "” is starting now.", detail: (m.org ? "Organized by " + (m.role === "org" ? "you" : m.org) + ". " : "") + "Your microphone and camera start off.", ok: "Join now", cancel: "Not now" })
          .then((ok) => { if (ok) join(m); }).catch(() => {});
      }
    }
    if (dirty) {
      for (const k of Object.keys(notes)) if (now - notes[k] > 7 * 86400) delete notes[k];
      jset(NOTE_KEY, notes);
    }
    if (listEl && !listEl.hidden && Date.now() - (S.painted || 0) > 30000) { S.painted = Date.now(); paintList(); }
  }
  let pollT = null;
  async function poll() {
    clearTimeout(pollT);
    try { if (available() && (ident() || S.d?.me)) await load(); } catch {}
    pollT = setTimeout(poll, POLL_MS);
  }
  setTimeout(poll, 4000);
  setInterval(tick, TICK_MS);

  // ---- More > Meetings..., the #meet=<id> link of a calendar entry --------------------------------------------------------
  const opt = document.getElementById("optMeet");
  if (opt) {
    opt.addEventListener("click", () => openList());
    const paint = () => { const on = available(); if (opt.hidden === on) opt.hidden = !on; };
    paint();
    setInterval(paint, 1500);
  }
  {
    let want = "";
    try {
      const hp = new URLSearchParams(String(location.hash || "").replace(/^#/, ""));
      const id = String(hp.get("meet") || "");
      if (MID_RE.test(id)) { want = id; sessionStorage.setItem("kastr.meet.open", id); history.replaceState(null, "", location.pathname + location.search); }
      else want = sessionStorage.getItem("kastr.meet.open") || "";
    } catch {}
    if (MID_RE.test(want)) {
      const until = Date.now() + 120000;
      const t = setInterval(async () => {
        if (Date.now() > until) { clearInterval(t); return; }
        if (!available()) return;
        clearInterval(t);
        try { sessionStorage.removeItem("kastr.meet.open"); } catch {}
        const d = await call({ op: "get", id: want });
        T("deeplink", { ok: d.ok });
        if (d.ok) openDet(d.meeting); else openList(null, !!d.status && d.status === 403);
      }, 1000);
    }
  }

  window.__kmeet = {
    creds, minted, refused, title: (room) => titles.get(room) || "", open: openList, form: openForm, details: openDet, join, load,
    here: () => (here ? { ...here } : null),
    state: () => ({ list: S.d ? { ok: S.d.ok, err: S.d.ok ? "" : String(S.d.error || ""), status: S.d.status || 0, n: (S.d.meetings || []).length, me: S.d.me || null, can: S.d.can || null, ids: (S.d.meetings || []).map((m) => m.id) } : null,
      lobby: lobbyEl && !lobbyEl.hidden ? { room: L.room, verdict: L.meet?.verdict || "", tries: L.tries } : null, here: here ? { room: here.room, id: here.id, role: here.role } : null,
      trace: trace.slice(-60) }),
  };
})();
