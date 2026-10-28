# STATUS: room names need an access code (0.21.92)

Branch `kastr-0.21.92-rooms-need-a-code` (commit `ac92e50`) merged with main v0.21.91 (`4f39018`) in worktree branch
`worktree-agent-ab67109d41dceb84c` (merge `dd53f5b`); the audit fixes below are committed on top. Not merged into main.

## Done (code + tests, lab-proven behind the fence)
- Tokenless relay sessions are admitted but read nothing (`public_grant` -> `~anon` only). The public kinds ride tokens: members all of them, guests (invite link / My room guest / guest in the Lobby) only their own room.
- `POST /api/token {browse: true, code}` mints a BROWSE token for any fleet access code (wrong codes count in the lockout).
- `/api/rooms/list` (KASTR) and the minter's `/api/rooms` answer no rooms without a token (`needCode: true`) -- since 0.21.92 the relay machine's loopback too (the Relay page reads `/api/relay/rooms`). A guest's token sees their room. An OPEN relay (no access codes) lists its rooms to everyone, as before 0.21.91.
- The page's rooms connection and list read carry the browse token (saved code at launch, code typed on the Join room page, code joined with) or a guest's own token. The page reads the room store only after `authDetect` answered for that relay.
- 0.21.92 endpoint audit (lab `scratchpad\v02192\roomcode\lab\audit.py`, `audit_before.json` / `audit_branch0.json` / `audit_after.json`): 308 anonymous remote calls on both KASTRs and both minters, searched for the room, member and file names. Before: 8 leaks; branch before the audit fixes: 3; after: 0. Closed here:
  - `GET /api/relay/rooms` -> the relay machine only (403 remote).
  - `GET /api/files?room=` -> a member token of that room on a secured relay (`Authorization: Bearer`); otherwise `200 {"files": [], "needToken": true}` so older pages still choose the store for uploads. `GET /api/files` (every room) -> the machine only.
  - `POST /api/rooms/touch` without a member token of the room keeps a live room alive, makes none and no longer says `created` (a spoke forwards `only: true`; the hub honours it).
  - `/api/relay/status` drops `logRemote` and `/api/instance` drops `adminMoved` for remote callers.
- `stats.html`: on a secured relay it asks for a fleet access code (or reuses `kastr.lastjoin`'s saved code, or a browse token already in the tab), mints a browse token on its own origin and the stats bundle's connection carries it (serve-time rewrite, the vendored bundle stays byte-identical; the token goes only to the page's own relay; the URL box never shows it). Only the token is kept (sessionStorage). Lab: locked without a code, "Wrong access code" on a wrong one, both nodes in 1.6 s after the code, 1.8 s with a saved code.
- A rooms-connection token switch closes the connection before its announcement readers: no more "announcements are closed" console errors (lab: 0 on join; failover run below).
- Failover (lab `pw_fail.py`, 3 runs each, detect / back in the room): without the change 17.7-18.1 s / 18.9-19.4 s; with it 17.7 s / 18.9 s; with the audit fixes (with2) 17.6-17.8 s / 19.0-20.0 s (CPU 76-99% from other agents' work during that run; detection unchanged), 0 "announcements are closed" lines (24 before the fix, 12 without the change). The earlier 63 s was a lab artifact.
- Tests: `tests/test_release_0_21_91_rooms_need_a_code.py`, `tests/test_release_0_21_92_room_name_audit.py` (behavioural: a real KASTR server on a fake secured / open relay). Windows and WSL: 1983 tests each, all green but the known `test_npu_fx` vendored-assets check (model files not in the tree).

## Pages older than this change (0.21.91 and older; lab `pw_old.py`, `results_old.json`)
An old app on another machine pointed at an updated relay host: the relay health light stays connected and it can join a room, but it sees no rooms on the Join room page (typing the code does not help), only its own room in the rail, and no people in its People panel. Others see it. Decision: NO grace period (it would keep the anonymous reads open). Old apps take the relay host's version at their next launch (fleet update); between launches the Relay page's existing push update ("Ask them first", since 0.21.50) reaches old apps as an "Update KASTR" dialog; web tabs get the new page on reload.

## Open before shipping
- Kenton's field check: stats.html on the hub with and without a saved code; a 0.21.91 app on another machine after the hub updates (push the update from the Relay page).
