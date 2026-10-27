// 0.21.91 passcode reset (Kenton: "Yes, in People + hub Relay page"): the admin's "Reset My room passcode" dialog -- one copy for
// the app's People menus (an admin-code holder) and the hub's Relay page (the operator). A TEMPORARY passcode (typed twice, or
// Generate: a readable 11-character code shown once with Copy); the person must pick their own at their next unlock. "Remove their
// My room" (asks first) clears it. The caller's `post(body)` sends POST /api/rooms/personal {op: "reset", name, code?, by?} with
// whatever proves it is an admin; the codes typed here go nowhere else (never stored, never logged).
(function () {
  "use strict";
  if (window.KastrPmReset) return;
  const ALPHA = "abcdefghjkmnpqrstuvwxyz23456789";   // no 0/o, 1/l/i
  function gen() {
    const out = [];
    const buf = new Uint8Array(32);
    while (out.length < 9) {
      crypto.getRandomValues(buf);
      for (const b of buf) { if (b < 248 && out.length < 9) out.push(ALPHA[b % ALPHA.length]); }   // 248 = 8 * 31: no bias
    }
    return out.slice(0, 3).join("") + "-" + out.slice(3, 6).join("") + "-" + out.slice(6, 9).join("");
  }
  const CSS = `
  #kPmReset { position:fixed; inset:0; z-index:2147483000; background:rgba(3,5,10,.62); display:flex; align-items:center; justify-content:center; padding:16px; }
  #kPmReset[hidden] { display:none; }
  #kPmReset .kpr { width:min(440px, calc(100vw - 32px)); max-height:calc(100dvh - 32px); overflow:auto; background:var(--surface-1, var(--surface, #101820));
    color:var(--text, #e6edf3); border:1px solid var(--line, #2a3440); border-radius:10px; box-shadow:0 18px 48px rgba(0,0,0,.55); font-size:13px; }
  #kPmReset .kprh { display:flex; align-items:center; gap:8px; padding:12px 16px 4px; font-weight:600; font-size:15px; }
  #kPmReset .kprh .sp { flex:1; }
  #kPmReset .kprx { background:transparent; border:0; color:var(--text-dim, #9aa7b4); font-size:15px; cursor:pointer; padding:2px 6px; }
  #kPmReset .kprb { padding:6px 16px 4px; display:flex; flex-direction:column; gap:10px; }
  #kPmReset p { margin:0; line-height:1.45; }
  #kPmReset ul { margin:0; padding:0 0 0 18px; display:flex; flex-direction:column; gap:4px; color:var(--text-dim, #9aa7b4); font-size:12.5px; line-height:1.4; }
  #kPmReset label { display:flex; flex-direction:column; gap:4px; font-size:11px; color:var(--text-dim, #9aa7b4); text-transform:uppercase; letter-spacing:.06em; }
  #kPmReset input { background:var(--surface-2, #18222c); border:1px solid var(--line, #2a3440); color:var(--text, #e6edf3); border-radius:6px; padding:7px 9px;
    font:inherit; font-size:13px; text-transform:none; letter-spacing:normal; -webkit-text-security:disc; }
  #kPmReset input:focus { outline:none; border-color:var(--asi-blue, #009fda); }
  #kPmReset .kprrow { display:flex; gap:8px; align-items:flex-end; }
  #kPmReset .kprrow label { flex:1; min-width:0; }
  #kPmReset .kprgen { display:flex; flex-direction:column; gap:6px; padding:9px 10px; border:1px solid color-mix(in srgb, var(--asi-blue, #009fda) 55%, transparent);
    border-radius:6px; background:color-mix(in srgb, var(--asi-blue, #009fda) 10%, transparent); }
  #kPmReset .kprgen[hidden] { display:none; }
  #kPmReset .kprgen code { font-family:var(--font-mono, ui-monospace, monospace); font-size:17px; letter-spacing:.06em; user-select:all; }
  #kPmReset .kprgen .r { display:flex; align-items:center; gap:10px; }
  #kPmReset .kprgen .r code { flex:1; }
  #kPmReset .kprmsg { min-height:17px; font-size:12px; color:var(--text-dim, #9aa7b4); }
  #kPmReset .kprmsg.err { color:var(--asi-red, #e5484d); }
  #kPmReset .kprmsg.ok { color:var(--asi-green, #2fb36d); }
  #kPmReset .kprf { display:flex; gap:8px; padding:10px 16px 14px; align-items:center; flex-wrap:wrap; }
  #kPmReset .kprf .sp { flex:1; }
  #kPmReset button.kb { font:inherit; font-size:13px; border-radius:6px; padding:6px 12px; cursor:pointer; border:1px solid var(--asi-blue, #009fda);
    background:var(--asi-blue, #009fda); color:#fff; }
  #kPmReset button.kb.ghost { background:transparent; border-color:var(--line, #2a3440); color:var(--text, #e6edf3); }
  #kPmReset button.kb.danger { background:transparent; border-color:color-mix(in srgb, var(--asi-red, #e5484d) 60%, transparent); color:var(--asi-red, #e5484d); }
  #kPmReset button.kb.dangerfill { background:var(--asi-red, #e5484d); border-color:var(--asi-red, #e5484d); color:#fff; }
  #kPmReset button.kb[hidden], #kPmReset [data-s][hidden] { display:none; }
  #kPmReset button.kb:disabled { opacity:.55; cursor:default; }
  `;
  let el = null, cur = null;
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function build() {
    if (!document.getElementById("kPmResetCss")) {
      const st = document.createElement("style"); st.id = "kPmResetCss"; st.textContent = CSS; document.head.appendChild(st);
    }
    el = document.createElement("div");
    el.id = "kPmReset"; el.hidden = true;
    el.innerHTML = '<div class="kpr" role="dialog" aria-modal="true" aria-labelledby="kprTitle">'
      + '<div class="kprh"><span id="kprTitle">Reset My room passcode</span><span class="sp"></span><button type="button" class="kprx" data-a="close" title="Close">&#10005;</button></div>'
      + '<div class="kprb">'
      + '<div data-s="reset"><p class="kprlead"></p></div>'
      + '<ul data-s="reset"><li>Their pinned feeds, spotlights and layouts stay.</li>'
      + '<li>When they open My room or Messages with it, they are asked to pick their own passcode before going on.</li>'
      + '<li>Their older messages open only with their <b>old</b> passcode &mdash; Messages asks for it, or they start fresh and lose them.</li></ul>'
      + '<div class="kprrow" data-s="reset"><label>Temporary passcode<input class="kpr1" type="text" autocomplete="off" spellcheck="false" maxlength="128" aria-label="Temporary passcode"></label>'
      + '<button type="button" class="kb ghost" data-a="gen" title="Make a readable passcode for you to pass on">Generate</button></div>'
      + '<label data-s="reset">Temporary passcode again<input class="kpr2" type="text" autocomplete="off" spellcheck="false" maxlength="128" aria-label="Temporary passcode again"></label>'
      + '<div class="kprgen" hidden><span>Tell them this passcode yourself &mdash; it is shown once and kept nowhere:</span>'
      + '<div class="r"><code class="kprcode"></code><button type="button" class="kb ghost" data-a="copy">Copy</button></div></div>'
      + '<div data-s="remove" hidden><p class="kprrm"></p></div>'
      + '<p class="kprmsg" role="status"></p></div>'
      + '<div class="kprf"><button type="button" class="kb danger" data-a="remove" data-s="reset">Remove their My room&hellip;</button><span class="sp"></span>'
      + '<button type="button" class="kb ghost" data-a="close">Cancel</button>'
      + '<button type="button" class="kb" data-a="reset" data-s="reset">Reset passcode</button>'
      + '<button type="button" class="kb dangerfill" data-a="rmgo" data-s="remove" hidden>Remove My room</button>'
      + '<button type="button" class="kb" data-a="done" hidden>Done</button></div></div>';
    document.body.appendChild(el);
    el.addEventListener("click", (e) => { if (e.target === el) close(); });
    el.addEventListener("keydown", (e) => {
      e.stopPropagation();   // the page's shortcuts stay quiet while it is up
      if (e.key === "Escape") { e.preventDefault(); close(); }
      else if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); el.querySelector('[data-a="reset"]').click(); }
    });
    for (const b of el.querySelectorAll("button[data-a]")) b.addEventListener("click", (e) => { e.stopPropagation(); act(b.dataset.a, b); });
    for (const i of el.querySelectorAll("input")) i.addEventListener("input", () => { el.querySelector(".kprgen").hidden = true; });
    return el;
  }
  const q = (s) => el.querySelector(s);
  function say(t, kind) { const m = q(".kprmsg"); m.textContent = t || ""; m.className = "kprmsg" + (kind ? " " + kind : ""); }
  function stage(s) {
    for (const x of el.querySelectorAll("[data-s]")) x.hidden = x.dataset.s !== s;
    q('[data-a="done"]').hidden = s !== "done";
    q('.kprf [data-a="close"]').hidden = s === "done";
    q("#kprTitle").textContent = s === "remove" ? "Remove their My room" : "Reset My room passcode";
  }
  function close() {
    if (!el) return;
    el.hidden = true;
    for (const i of el.querySelectorAll("input")) i.value = "";
    q(".kprcode").textContent = ""; q(".kprgen").hidden = true;   // the code leaves the page
    say("");
    const c = cur; cur = null;
    try { c?.onClose?.(); } catch {}
  }
  async function act(a, b) {
    if (!cur) return;
    const name = cur.name;
    if (a === "close" || a === "done") return close();
    if (a === "gen") {
      const c = gen();
      q(".kpr1").value = c; q(".kpr2").value = c;
      q(".kprcode").textContent = c; q(".kprgen").hidden = false;
      say("");
      return;
    }
    if (a === "copy") {
      const t = q(".kprcode").textContent;
      try { await navigator.clipboard.writeText(t); b.textContent = "Copied"; }
      catch { try { const r = document.createRange(); r.selectNodeContents(q(".kprcode")); const s = getSelection(); s.removeAllRanges(); s.addRange(r); b.textContent = "Select + Ctrl+C"; } catch {} }
      setTimeout(() => { b.textContent = "Copy"; }, 1500);
      return;
    }
    if (a === "remove") { stage("remove"); say(""); return; }
    if (a === "reset") {
      if (q('[data-a="reset"]').hidden) return;   // (Enter on another stage)
      const c1 = q(".kpr1").value, c2 = q(".kpr2").value;
      if (c1.length < 8) { say("A passcode has at least 8 characters.", "err"); q(".kpr1").focus(); return; }
      if (c1 !== c2) { say("The two passcodes do not match.", "err"); q(".kpr2").focus(); return; }
      b.disabled = true; say("Resetting…");
      const d = await post({ op: "reset", name, code: c1 });
      b.disabled = false;
      if (!d.ok) { say(errText(d), "err"); return; }
      const shown = !q(".kprgen").hidden;
      q(".kpr1").value = ""; q(".kpr2").value = "";
      stage("done");
      if (shown) q(".kprgen").hidden = false;   // a generated code stays up (with Copy) until Done
      say(name + "’s My room passcode is reset. Give them the temporary passcode; they pick their own when they next open My room.", "ok");
      try { cur.onDone?.("reset", d); } catch {}
      return;
    }
    if (a === "rmgo") {
      b.disabled = true; say("Removing…");
      const d = await post({ op: "reset", name });
      b.disabled = false;
      if (!d.ok) { say(errText(d), "err"); return; }
      stage("done");
      say(name + "’s My room is removed. They make a new one (with a new passcode) the next time they set up My room.", "ok");
      try { cur.onDone?.("remove", d); } catch {}
    }
  }
  function errText(d) {
    if (d.status === 404) return (cur?.name || "They") + " has no My room on this hub.";
    if (d.status === 403) return "Only an admin (the admin access code) or the hub’s operator can do this.";
    return String(d.error || "Refused.").replace(" -- ", " — ");
  }
  async function post(body) {
    try { return Object.assign({ ok: false }, await cur.post(body)); }
    catch (e) { return { ok: false, error: String(e?.message || e) }; }
  }
  // open({name, post: async (body) => ({ok, status, error, ...}), onDone?(op, reply), onClose?()})
  function open(o) {
    if (!el) build();
    cur = o;
    stage("reset");
    q(".kprlead").innerHTML = "Give <b>" + esc(o.name) + "</b> a temporary passcode for My room &mdash; tell it to them yourself.";
    q(".kprrm").innerHTML = "Remove <b>" + esc(o.name) + "</b>&rsquo;s My room? Their pinned feeds, spotlights and layouts go, and the room is gone on every device. "
      + "They make a new My room (with a new passcode) the next time they set it up. Their older messages still open only with their old passcode.";
    for (const i of el.querySelectorAll("input")) i.value = "";
    q(".kprcode").textContent = ""; q(".kprgen").hidden = true;
    say("");
    el.hidden = false;
    if (o.stage === "remove") { stage("remove"); setTimeout(() => { try { q('[data-a="rmgo"]').focus(); } catch {} }, 30); return; }   // the Relay page's Remove
    setTimeout(() => { try { q(".kpr1").focus(); } catch {} }, 30);
  }
  window.KastrPmReset = { open, close, gen, state: () => ({ open: !!el && !el.hidden, name: cur?.name || "", stage: el ? ([...el.querySelectorAll("[data-s]")].find((x) => !x.hidden)?.dataset.s || "done") : "" }) };
})();
