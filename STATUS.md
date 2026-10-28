# 0.21.92 presentation work -- status (branch worktree-agent-a5b84d6fc8627d16a, base 4f39018 = v0.21.91)

Not merged, VERSION not bumped, not pushed. Lab-proven only (headless Chromium on lab ports 9200-9203); field tests are Kenton's.

## What changed

1. **Bigger next slide** (`assets/kastr-pres.js` nxtApply): starts at half the live slide's width (`NX_DEF = 0.5`, range 0.2-1),
   its corner grip drags it (arrow keys too; double-click = back to half), the size is kept per device (`kastr.pres.layout` `nx`,
   synced by prefs.js / kastr_serve.py). The notes keep about three lines (`notesMin = max(90, fs*1.45*3+22)`); the 0.21.91
   short-window rule stays.
2. **Add anyone as presenter or backstage** (picker: people in the room, then everyone online on the fleet, then any typed name).
   Someone not in the room gets an invite with the role (`kastr_relay.py` role invites "p"/"b": prompt "Presenter invitation" /
   "Backstage invitation", Join / Ignore; Join enters even a locked room without the code). The role waits (record `pend`) and is
   applied when they arrive (name keys + rename aliases from kastr-msg.js `renamed`). Rows show invited / waiting / not here yet.
   Removing a waiting role withdraws its invite (`pirevoke`). Waiting roles are handed on with the deck (hand-over / adoption).
3. **Switches**: every on/off in the presenter view is a `.switch sm` toggle.
4. **Audience sees only the presentation's cameras** while it is live (page `presAudHidden`, fed by `window.__presAudHide` from
   kastr-pres.js audView every 400 ms): hidden tiles are unsubscribed (`visible="never"`); presenters + backstage see everyone.
5. **"Audience can see each other"** switch (record `see`, ON by default; absent = on): OFF hides other audience members' cameras
   from audience pages everywhere (rail, stage, custom grids -- not kept warm) and Room Chat names them "Audience member".
   People lists do not change.
6. **Templates hooks** (`window.__pres`):
   - `audSnap()` -> `{am, ask, see}` (Audience muted / Ask to speak / Audience can see each other; 1 = on), or null.
   - `audApply(snap)` -> `{am|ask|see: done}` (presenter / co-presenter only).
   - `rolesSnap()` -> `{presenters: [{name, main, here}], backstage: [{name, control: [presenter names], here}]}` -- includes
     waiting people (`here: false`); names come from the deck's own kept names (a departed owner shows "Alice Lab", not "alice-lab").
   - `rolesApply(snap)` -> `{ok, waiting, refused}`: here = role now, not here = waiting role (+ invite).
   - `roleAbsent(name, r, {control})` -- a waiting role by name; `control` false = this presenter's mic/camera control pre-denied
     (`preDenied`).
   - Template audience `{muted, ask, see}` is accepted by `audPreset` at presentation start (`see === 0`, `am === 0`).
7. **Fixes found on the way**:
   - Shrinking slides on an added presenter (`curFit`: the slide is placed in its box and never sizes it; 20x paint() stability test).
   - `awayFrom`: a deck belongs to its room -- going to another room forgets it (no take-over from the Lobby that later ENDED it).
   - `mainroom$` added to the server prefs whitelist (kastr_serve.py) so the preferred main room survives a prefs sync.

## Merge with main 4e6dfd4 (meeting templates) -- conflicts resolved

- `assets/kastr-pres.js`, one conflict at `window.__pres` (both sides added template hooks). Kept BOTH: main's `tplSnap`,
  `tplOpts`, `tplCo`, `onEnd` and my `audSnap` / `audApply` / `rolesSnap` / `rolesApply` / `roleAbsent`. Main's inline
  `audSnap: () => ({am, ask})` was dropped in favour of mine, which returns the same keys plus `see` (tplSnap calls it).
- Auto-merged, checked by hand: startFromFile runs main's `tplPreset` then my `askPreset` + `audPreset`; B's `endPress()` hook
  (`window.__pres.onEnd`, then `endNow()`) is kept unchanged.
- Added after the merge:
  - `TPL_OPTS` row `{ key: "see", sw: 1, text: "Audience can see each other", def: 1 }`, so templates save it and the editor shows it.
  - `tplSnap` now also keeps the people a role still waits for (not here yet) by name: presenters `{name, main: false}`, backstage
    `{name, control}`. Saving a template while someone is invited keeps them.
- Template apply = kastr-templates.js presStart -> `startFromFile(file, {idx, cm, am, ask, o, tpl})`, then for anyone not here
  `roleAbsent(name, r, {key, control, from})`. That is the same invite + waiting-role flow as the picker's typed name. Lab
  (pw_tpl.py): `o.see = 0` -> the record has see 0 and audience Erin is anon at once; `roleAbsent` for Bob (online elsewhere)
  -> prompt 3.3 s, presenter 1.8 s after Join; `roleAbsent` for Dan (offline, control [Alice]) -> waiting in rolesSnap + tplSnap;
  Dan launches -> prompt 9.9 s, backstage 11.9 s after launch, Alice's control of his mic + camera on.

## Record fields added

`see` (0/1), `pend` (waiting roles: `{k, n, h, r, inv}`), `fs` (THE HOOK for 0.21.93 live feeds: stream paths the owner shows,
audience pages show + subscribe them, up to 16 `.hang` paths), `g` (an invite-link guest's page: it adds people from the room only).

## Guest decision

An invite-link guest can be given a role in that room only, and a guest presenter cannot add outside people (no fleet list, no typed
names; the owner drops a `pend` from a guest page).

## Security -- honest limits

- Camera hiding and chat anonymising are **client-enforced**: the relay still serves every stream to a modified page.
- `/api/chat` transcripts keep real names; server-side anonymising was not cheap (the chat server holds room tokens only and cannot
  read the presentation record).
- Names for waiting roles are self-declared (name match), like the rest of KASTR before SSO.
- **Old 0.21.91 clients show everything** (they read none of it).

## Lab results (scratchpad v02192/lab)

- Audience view (pw_aud.py): Standout/Side-by-side -> audience pages show only the presenter (others hidden + `never`); Content only
  -> no cameras; within one 400 ms poll. See OFF -> anon in 0.11 s, a custom grid leaves the other audience member out (not
  warm), chat "Audience member" on audience pages only. Hand-over keeps `see: 0`. End -> everything back in 0.23 s.
- Roles (pw_roles.py, locked room): invite prompt 3-5 s, Join into the locked room 0.21 s with no code, role 1.5-1.8 s after
  arrival; offline typed name gets the role 5.9 s after launching KASTR; withdraw 0.2 s; waiting role survives a hand-over.
- Next slide (pw_next.py): 1280x720 next/live 0.5 (notes 5 lines); 1920x1080 0.5; 1025x579 0.42 (notes 4.1 lines).

## Open

- Field tests (real fleet, real PowerPoint is not involved: `KASTR_PRES_POWERPOINT=0` in the lab).
- Cosmetic: a grid spot of a hidden audience member reads "Hidden for you".
- The "invite withdrawn" toast text on the invited page was not captured by the lab selector (the withdraw itself was proven).
- Tests: test_release_0_21_92_next_slide, _paint_stable, _role_invites, _audience_view (+ updated 0.21.85/89/91 pins).
