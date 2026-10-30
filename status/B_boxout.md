# boxout-0.21.96 -- "For Relays/Camera boxes, I would like them to not be able to directly connect to rooms"

Kenton, 2026-10-30: "they connect to their 'My room' or no room at all, and their shares just go to the library or whatever
rooms they tell them to." His answers: the rule covers camera boxes AND the KASTR app on relay/hub machines; a box already in a
real room moves out on the update and keeps listing its cameras back into that room; grid layouts, composites, board pins
and library listing keep working.

## Which machines (kastr_serve.boxout_state)
- **"box"**: mode publisher or publisher-relay (every camera box).
- **"relay"**: only a relay that is ALWAYS ON -- mode relay, OR relay autostart on (relay-autostart.json enabled, or
  kastr.ini relay_autostart). Kenton (2026-10-30, "Only always-on relays"): a relay started by hand (Relay page Start) does
  NOT count -- that laptop stays a person and can still join rooms. This is narrower than kastr.hosts_relay (which also counts
  a relay merely running).
- **Never**: mode viewer (a display exists to watch rooms), and a person's everyday KASTR (mode full) that runs no relay.
  Web clients of a relay host, the presentation recorder and remote pages never get the flag, because /api/instance only
  sends `boxout` to a local caller.
- Kenton's own app on 127.0.0.1:8001 was not read. His everyday KASTR stays a person unless its relay is always on. Pressing
  Start on the Relay page does not change that. Turning relay autostart on does: the 30 s poll then moves the page to No room.

## What it does
- **Join room page / Change room / rail**: only "No room — this machine only shares into the library and the rooms I pick"
  and "My room" (when this machine keeps one). The heading reads "Join room — No room". Create room is hidden.
  - Invite links, person invites, room cards, switchRoom, a My room guest visit and joinNow to a real room are all refused
    with one line (toast, gate message, and launch.log through /api/rtsp/note "box-out: ...").
- **authMint** (the page's only room-token path) refuses a real room and sends `boxed: true` to the relay's minter.
  - The minter (kastr_relay token()) refuses a boxed mint for a real room, for main, or for another box's home room.
  - It allows the machine's own box-<host> room and its own My room.
  - xs listing tokens (xsTokenFor, the box server's mint_member) never send `boxed`, so Show in rooms keeps working.
  - Nothing changes for a person's KASTR.
- **Box server** (kastr_rtsp handle_api): when boxed, /api/rtsp/publish into a real room and /api/rtsp/persist of a real room
  get 403 with the reason.
- **One-time move on update** (kastr.feeds_boxout in feeds_restore, then kastr_rtsp.boxout_migrate):
  - rtsp-feeds.json in a real room R is rewritten (sealed) to No room (box-<host>).
  - Each camera R/... becomes box-<host>/... with xs += [R], xsCodes[R] = the old room code, and libAka[old path] (pins,
    grids and composites keep resolving).
  - Logged in launch.log and in /api/diag `_boxout.log`.
  - A Lobby ("main") box moves without listing back, because nobody needs a box in the Lobby.
- **Live** (no restart): the page polls /api/instance every 30 s. A machine that becomes boxed while it is in a real room
  switches to No room. Its cameras are carried first: the page's xs saves, plus Bridge._boxout_carry on republish.
- **Restart/Move by an admin**: the resume ticket (kastr.rejoin) and kastr.lastjoin are rewritten to No room before the gate
  reads them. authMint refuses any real room in any case.

- **Swap in place** (Kenton, "Swap in place"): a viewer already in the room when the box updates sees the library stream
  take the old tile's place.
  - The library path lib/<host>/<op>/<leaf>.hang has the same tail as the old <room>/<host>/<op>/<leaf>.hang (the relay's
    lib_alias_ok rule; the catalogue's `aka` wins when the page has it).
  - When the library tile is created (createTile -> tileSwapIn), the old tile is removed AT ONCE, not after the 4 s debounce.
    There is no duplicate tile and no tile left "waiting for keyframe". The old path is never re-created next to it, even
    while the relay still announces it.
  - A LIVE old tile is swapped only when the library path is listed into this room (Show in rooms) or the catalogue names
    the old path as its alias. A person's share of this room that is also in the library keeps its own tile.
  - What follows the camera: my pick (selected tile), my row order, my pins / grids / watch-or-parked memory
    (libAkaRewrite), and every spotlight vote (mine, other members', the room board's) plus the board's arrange order.
    Spotlights and the order follow at read time (akaOf in spotSetNow / spotOrdered), so pages that join later get the same
    stage.
  - The other way round: the hub moves the board's spotlight to the lib/ path before the library tile reaches the page. The
    old tile keeps that spotlight until its library tile comes, so the stage never empties.
  - A tile that already went in the update's gap (a clean stop) is remembered for 5 minutes (tileLeft). Its row order and
    pick come back when the library tile arrives, unless the viewer picked something else since.
  - The catalogue alias may reach the page before the library tile. The old tile stays watched (on the stage) until the
    swap.

## Enforcement -- honest limits
There is no machine identity before 0.22 (SSO).
- The minter check trusts the page's own `boxed` flag. A modified page, or another tool holding the publisher code, can still
  mint a real room.
- The box server's own 403s are local enforcement.
- So this is the page's and the machine's own KASTR rule, not a wall at the relay.

## Lab proof (C:/kastr-scratch/v02196/boxout, ports 9500-9502 + relay 5090; results.json, run2.log, shots/)
- vwbox (a person) is in room boxout-lab. cambox-0960 runs on the OLD tree (main e300b79, mode publisher) and publishes
  boxout-lab/cambox-0960-0669/labop/gate.hang. The viewer sees it.
- The box restarts on this branch:
  - restore: room=box-cambox-0960-0669, 1 feed republished.
  - diag `_boxout.log`: "box-out: this camera box left room boxout-lab for No room (box-cambox-0960-0669) -- 1 camera(s)
    moved, each still shown in boxout-lab".
  - feeds: xs ["boxout-lab"], libAka has the old path.
- **The viewer** gets lib/cambox-0960-0669/labop/gate.hang within 1 s of looking (listed back by the box server). A fresh
  dark-theme viewer sees it playing.
- **Minter** (the box's real host slug):

  | Request | Result |
  | --- | --- |
  | boxed, boxout-lab | 403 |
  | boxed, main | 403 |
  | boxed, its own box-cambox-0960-0669 | 200 |
  | boxed, another box's room | 403 |
  | unflagged, as the box or as a person | 200 |

- **Screenshots, light + dark**: box Join page, refusal on the Join page, invite-link refusal, box in No room, Create room
  refusal, relay machine Join page, viewer before/after.
- Suites (final): Windows 2506 tests -- test_npu_fx (known, worktree) + test_release_0_21_94_fastest_fits npu timing
  (Chromium, under load; passes alone); WSL 2506 tests -- test_npu_fx only. Four older source-assert tests updated for the
  new lines (confirm_popup window, 0.21.75 xsServerPath, 0.21.89 heading, 0.21.91 mainPerson).
- One camera only. Two test://pattern feeds share one URL, and restore matches feeds by URL (existing behaviour).

## Lab proof: swap in place (pw_swap.py -> swap_results.json, swap_run5.log, shots/swap-*)
- rhbox's relay was started by hand: its /api/instance says boxout off (a person, the always-on rule).
- Two cameras in boxout-lab: Yard (rhbox) and Gate (cambox on the OLD tree). The viewer spotlights Gate, then Yard, for
  everyone. Stage on both viewers (light + dark): [Gate, Yard].
- The box is hard-stopped (its recorded PID) and restarted on this branch. Both viewers were sampled every 250 ms:
  - Light viewer (the one who voted): at 9.35 s the old tile went and lib/cambox-0960-0669/labop/gate.hang came in the same
    sample. Never both tiles at once. The stage went straight from [Gate, Yard] to [lib Gate, Yard], with no empty stage
    between. The pick stayed on the camera.
  - Dark viewer: the same at 4.67 s.
  - The old path's later "inactive" did nothing; it was never re-created.
- A viewer that joins after the update gets the same stage [lib Gate, Yard] within 3.2 s.
- No page errors on any of the three pages.
- Earlier runs found two gaps, both fixed:
  - the catalogue alias unwatched the old tile before the library tile came;
  - the hub had already moved the board's spotlight to lib/, so it pointed at a tile not there yet.
- Shots: swap-before-light/dark, swap-after-light/dark, swap-late-joiner-light.
- Suites after both follow-ups: Windows 2566 tests and WSL 2566 tests. The only failure on each is test_npu_fx (known,
  worktree only). Two older source-assert tests were updated for the new lines: test_gallery_onair (select window) and
  test_release_0_21_66 (votes line).

## Doubts / defaults for Kenton
1. Only an always-on relay (mode relay, or relay autostart on) makes a KASTR a relay machine (Kenton, 2026-10-30). A laptop
   whose relay was started by hand stays a person until autostart is turned on or the relay stops.
2. Viewer mode is exempt.
3. Swap in place is done on the viewer's page (no relay or board writes). The room board keeps whatever path the hub gave it;
   pages of 0.21.96 read either path as the camera. A page older than 0.21.96 still shows the old behaviour: it waits for a
   keyframe, then shows a new tile. On a clean stop (not a hard kill) the old tile can go before the library tile comes; the
   spotlight comes back on the library tile when it arrives, and the stage shows the rest meanwhile.
4. Locked-room codes for page-owned listings are carried in memory only (never stored). After a page reload, a locked room's
   listing needs its code again. Server-owned camera listings keep the code in the sealed feeds file.
5. The rtsp-feeds.json `boxout` record is dropped the next time the bridge rewrites the file. launch.log and /api/diag keep it.
6. kastr.ini relay_autostart is read from the ini next to the code (ini_get), as elsewhere.
7. A box that was in the Lobby moves to No room without listing back into the Lobby.
