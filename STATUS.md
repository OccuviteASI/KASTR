# Meeting templates (0.21.92), status

Branch `worktree-agent-aebb334153aab631a`. Main is merged in (head after c1d4a20). Not merged into main, no VERSION bump, nothing pushed.

## Done

All of it is built: the hub store, the encrypted deck store, preview / apply / undo, spoke forwarding, the page UI and the presentation section.

**Files**
- `kastr_templates.py`: the store, the deck store and the planner.
- `kastr_relay.py`: `templates_api`, `_tpl_hub`, `_tpl_run`, `_tpl_undo_run`, the deck routes, `rooms_fed` op `tpl`, and deck copying for hand-over, standby and hand-back.
- `kastr_serve.py`: proxy routes.
- `build.py`: hidden import for `kastr_templates`.
- `moq-watch-lite.html`: small hooks plus the `window.__ktpl` bridge.
- `assets/kastr-templates.js`: the whole UI.
- `assets/kastr-pres.js`: two hooks only.
  - `startFromFile(file, opts)` reads `opts` from `arguments[1]` and applies `tplPreset` before the first publish.
  - `window.__pres.tplSnap()`.

**Kenton's decisions, as built**
- **Template decks:** they open only for the template's named presenters and backstage (proven by name + My room code) and for room admins. Named viewers are allowed.
- **Renames:** a rename rewrites the person in every template's presenters, backstage and control lists; `personal_unrename` reverses it. If a template still holds the old name, the hub's 90-day rename alias still lets the person open the deck.
- **Presentation section:** "Ready, with a Start button".
  - Save keeps the deck as the file it came from on the hub, encrypted at rest, in 16 MB parts. It also keeps the slide, presenters (the main one marked), backstage with each person's control list, Audience muted, the mode (`sbs` = Side-by-side) and the Reporter background.
  - Apply tells the main presenter's device on its people beat (inbox item `tplpres`; spokes get it through the long-poll). Their page loads the deck and shows the Ready bar.
  - Start presenting starts the deck on its slide with its mode, background and audience rule, gives the people who are here their roles, and names who is absent.
  - Slide videos travel inside the stored .pptx: when the deck starts, it converts again and its videos go to the deck store the usual way (lab-proven).

**Tests:** `tests/test_release_0_21_92_templates.py` has 28 tests. On head a3f5ade: Windows 1942 OK, WSL 1942 OK.

**Lab:** the scripts are in `scratchpad\v02192\templates\`. They use ports 8881–8883 and relays 4861/4871/4881.
- `lab.py up | down`
- `pw_templates.py`: the full flow.
- `pw_pres.py`: the presentation section.
- `pw_pres_video.py`: slide videos.

Screenshots (29) are in `docs/review-0.21.92-templates/` (not committed) and copied to `scratchpad\v02192\templates\shots\`.

## Left / open

- **Ask to speak:** the saved "Ask to speak" flag is kept but not applied, because kastr-pres.js has no switch to turn raising hands off. Kenton to decide whether one is wanted.
- **Co-presenters' control lists:** each presenter sets their own "Can control my mic and camera" on their own page. Start only applies the main presenter's list; a co-presenter's list from the template is not applied on their page.
- **Update from this room:** it re-takes layout, streams and settings, but not the live presentation. To re-take a presentation, save a new template while presenting.
- **Not proven:**
  - a real hand-over, standby or hand-back with decks (unit tests only);
  - a real VPN fleet;
  - very large decks (more than 16 MB, several parts);
  - the green "live" camera chip in a page.
- **Lab workaround:** after the 0.21.91 set-up card, an admin's page sometimes lands in My room (the main-room feature). The lab helper `pw_templates.person` rejoins the intended room.

## How to resume

1. `git merge main` in this worktree.
2. Run both suites:
   - Windows: `python -m unittest discover -s tests -q`
   - WSL: `wsl -u root`, then `~/.venvs/kastr/bin/python3 -m unittest discover -s tests -q` in the worktree.
3. For the lab: `cd scratchpad\v02192\templates; python lab.py up`, then `..\..\v0170\pw\Scripts\python.exe pw_pres.py` (or `pw_templates.py`, `pw_pres_video.py`), then `python lab.py down`.
4. The lab needs these gitignored files copied into the worktree from the main checkout: `bin/moq-relay.exe`, `assets/vendor/pdfjs/*.mjs`, and the NPU/MediaPipe models (for `test_npu_fx`).
