# Meeting templates (0.21.92), status

Branch `worktree-agent-aebb334153aab631a`. Main 4f39018 (0.21.91) is merged in. Not merged into main, no VERSION bump, nothing pushed.

## Done

Everything is built:
- the hub store and the encrypted deck store;
- preview, apply and undo;
- spoke forwarding;
- the page UI and the presentation section;
- every presentation toggle that exists in 0.21.91;
- "Create a new room for this" with close-on-End.

**Files**
- `kastr_templates.py`: the store, the deck store and the planner.
- `kastr_relay.py`:
  - `templates_api`, `_tpl_hub`, `_tpl_run`, `_tpl_undo_run`;
  - the deck routes and `rooms_fed` op `tpl`;
  - deck copying for hand-over, standby and hand-back;
  - `_tpl_room_mark`, `_tpl_pres_end`, and `AuthStore.close_room(slug, why)`.
- `kastr_serve.py`: proxy routes. `_rooms_merge` also carries `closedWhy` from the hub.
- `build.py`: hidden import for `kastr_templates`.
- `moq-watch-lite.html`: small hooks, plus the `window.__ktpl` bridge (`roomsFresh`, `closed`). `forcedToMain` has a `forcedBusy` guard, and the original body is now `forcedToMainNow`.
- `assets/kastr-templates.js`: the whole UI.

**Seams into `assets/kastr-pres.js`**
- `startFromFile(file, opts)` reads `opts` from `arguments[1]` and calls `tplPreset` before the first publish (~line 571 / 605).
- `TPL_OPTS` holds the toggle table (~line 621). The export adds `tplSnap`, `tplOpts` and the co-presenter control-list setter (~line 3185).
- Absent people: giveRole hands them to `__pres.roleAbsent` / `roleByName` as they are, keyed by name key. They are never dropped on snapshot or apply.
- **The End hook (the one hook for close-on-End):** `endPress()` (~line 1564) calls `window.__pres.onEnd({id, role})`. The hook may ask first; a `false` result keeps presenting. The original body is now `endNow()`. The export holds `onEnd: null` (~line 3193). `kastr-templates.js` sets it lazily in `hookEnd` (~line 717), through `presEndHook`, because kastr-templates.js loads before kastr-pres.js. Leave (`leaveMine`), pagehide and `__presLeaving` never call it.

**Toggles a template keeps (`TPL_OPTS`)**
- The table is `{key, read, apply}`. Unknown keys are skipped, so templates from older and newer builds both load.
- The editor shows each toggle as a switch (`<span class="switch">`).

| Key | What it keeps |
|---|---|
| `am` | Audience muted |
| `ask` | Ask to speak (applied through the 0.21.91 Ask to speak switch) |
| `see` | Audience can see each other. NOT on this branch yet: no such switch exists in 0.21.91. When the branch that adds it merges, add one `TPL_OPTS` row (~line 627) |
| `cm` | Each backstage person's "Can control my mic and camera", per presenter |
| `rbg` | Reporter background |

- The presenter mode and starting slide are kept beside the table.
- Per-device layout is not template material.

**Kenton's decisions, as built**
- **Template decks:** they open only for:
  - the template's named presenters and backstage, proven by name + My room code;
  - room admins.

  Named viewers are allowed.
- **Renames:** a rename rewrites the person in every template's presenters, backstage and control lists, and `personal_unrename` reverses it. The hub's 90-day rename alias still opens the deck for an old name.
- **Presentation section:** "Ready, with a Start button".
  - Save keeps:
    - the deck as its original file on the hub, encrypted, in 16 MB parts;
    - the slide and the mode;
    - presenters (the main one marked) and backstage, with each person's control list;
    - every toggle above.
  - Apply sends the main presenter's device the inbox item `tplpres`; spokes get it through the long-poll. That page loads the deck and shows the Ready bar.
  - Start presenting:
    - starts the deck on its slide, with its mode, background and toggles;
    - gives the people who are here their roles and names who is absent.
  - Co-presenters' control lists are applied on their own pages through hub op `presCo` (lab: 3.8 s).
  - Slide videos travel inside the stored .pptx and go to the deck store when the deck starts.
  - "Update from this room" re-takes the live presentation as well, when one is running.
- **Create a new room for this / close on End** (Kenton, 2026-10-27):
  - **Creating the room:**
    - Apply's room list offers "+ Create a new room for this…". The name is prefilled with the template name (plus the date if taken) and can be edited.
    - The creator must be allowed to create rooms.
    - KASTR creates the room, moves the starter in and applies everything (lab: 0.45 s).
    - Named presenters and backstage get the usual invite and role prompt. The page passes a `people` hint (`[{name, host}]`, at most 24, only the template's own named people) for devices the hub has not seen, such as a spoke's page.
  - **Marking it:** hub op `room` marks the record `tpl:{id, run, by, close}`. The mark needs the roomKey from creating the room, and a room older than `TPL_ROOM_NEW_S` (600 s) is never marked. A room that existed before therefore can never be closed this way.
  - **The switch:** "Close the room when the presentation ends", ON by default, kept in the template.
  - **Ending:**
    - Only End closes the room, after the confirm "End the presentation and close <room> for everyone?" ("End and close").
    - Only that run's named presenters (proven by name + code), the creator and admins can close it, through hub op `presEnd`.
    - Hand over, Take over, Leave and a dropped connection never close it.
    - The hub closes it like an admin close (`close_room(slug, "pres")`): listed shares are removed, invites are revoked, and `closedWhy` = "pres" goes out with the rooms list.
    - Everyone lands in their main room with the note "The presentation ended and <room> was closed".
    - Older pages are moved out by the normal room-deleted push.
  - **Invite-link guests:** they may use `deckOpen`, `presCo` and `presEnd` (`TPL_GUEST_NAMED_OPS`), and each op checks the proven name. A guest closes only as a named presenter, never as creator or admin. Personal guests (`pg`) can still only look.

**Tests**
- `tests/test_release_0_21_92_templates.py` has 36 tests, including class `TemplateRoom` (create, mark, end, guards, guest presenters, the one-hook source check).
- Windows: 1998 OK (7 skipped). WSL: 1998 OK (5 skipped).

**Lab** (scripts in `scratchpad\v02192\templates\`; hub 9120 / relay 4910, spoke 9121 / relay 4914)
- `pw_tplroom.py` (create a room + End closes it), full pass, 0 page errors:
  - the option shows with no stray entry, the name is prefilled, the close switch is ON, and a taken name is refused;
  - create, move and apply: 0.45 s;
  - Ada (hub) and Carlo (spoke) got invites and joined;
  - Ada's backstage `presEnd` was refused;
  - after hand over, take over and Kenton's Leave, the room was still there;
  - Carlo's End brought the confirm on top. All three got the note in 0.23 s, 0.23 s and 1.24 s and were in their My rooms, and the hub showed the room closed with why "pres".
- `pw_pres2.py` (roles, backstage control, co-presenter lists, Ask to speak off), full pass on run 9.
  - Flake: run 8 failed because Ada's page got no set-up card. Seen once.
- Older scripts: `pw_templates.py`, `pw_pres.py`, `pw_pres_video.py`.
- Screenshots are in `docs/review-0.21.92-templates/` (not committed, like earlier review sets): `apply-create-room-*`, `create-room-invite-dark`, `end-and-close-confirm-dark`, `presentation-ended-room-closed-*`, and others.

## Windows field checklist (Kenton)

1. Save a template while presenting a real .pptx with a co-presenter and a backstage person. In a fresh room, apply it and check:
   - the slide, the mode and the Reporter background;
   - audience muted / Ask to speak;
   - the control lists.
2. Apply with "+ Create a new room for this…":
   - check the prefilled name;
   - check that invites reach a person on a spoke (South Field) as well as a hub person;
   - Start.
3. Hand over and Take over: the room stays. Leave as the main presenter: the room stays.
4. End as a named presenter: confirm "End and close". Everyone moves to their own main room with the note "The presentation ended and <room> was closed".
5. Apply the same template to an existing room and End. That room must stay.

## Not proven / open

- A real VPN fleet.
- A real hand-over, standby or hand-back with decks (unit tests only).
- Very large decks (more than 16 MB, several parts).
- Invites through a real KASTR app check-in path. The lab used the page `people` hint, because headless pages do not check in.
- Pages older than 0.21.92 leaving a closed room through the room-deleted push.
- The green "live" camera chip in a page.
- **Lab workaround:** after the 0.21.91 set-up card, an admin's page sometimes lands in My room. `pw_templates.person` rejoins the intended room.

## How to resume

1. `git merge main` in this worktree.
2. Run both suites:
   - Windows: `python -m unittest discover -s tests -q`
   - WSL: `wsl -u root`, then `~/.venvs/kastr/bin/python3 -m unittest discover -s tests -q` in the worktree.
3. For the lab: `cd scratchpad\v02192\templates; python lab.py up`, then `..\..\v0170\pw\Scripts\python.exe pw_tplroom.py` (or `pw_pres2.py`, `pw_templates.py`, `pw_pres_video.py`), then `python lab.py down`.
4. The lab needs these gitignored files copied into the worktree from the main checkout: `bin/moq-relay.exe`, `assets/vendor/pdfjs/*.mjs`, and the NPU/MediaPipe models (for `test_npu_fx`).
