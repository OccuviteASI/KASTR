# boxout-0.21.96 -- "For Relays/Camera boxes, I would like them to not be able to directly connect to rooms"

Kenton, 2026-10-30: "they connect to their 'My room' or no room at all, and their shares just go to the library or whatever
rooms they tell them to." His answers: the rule covers camera boxes AND the KASTR app on relay/hub machines; a box already in a
real room moves out on the update and keeps listing its cameras back into that room; grid layouts, composites, board pins
and library listing keep working.

## Which machines (kastr_serve.boxout_state)
- **"box"**: mode publisher or publisher-relay (every camera box).
- **"relay"**: mode relay, OR its relay running now, OR relay autostart on (relay-autostart.json or kastr.ini
  relay_autostart). This is the same test as kastr.hosts_relay, the 0.21.85 "relay machine" rule.
- **Never**: mode viewer (a display exists to watch rooms), and a person's everyday KASTR (mode full) that runs no relay.
  Web clients of a relay host, the presentation recorder and remote pages never get the flag, because /api/instance only
  sends `boxout` to a local caller.
- Kenton's own app on 127.0.0.1:8001 was not read. His everyday KASTR stays a person unless it runs a relay itself. If he
  starts a relay there (Relay page Start, or autostart), it becomes a relay machine. The 30 s poll then moves the page to
  No room.

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
- One camera only. Two test://pattern feeds share one URL, and restore matches feeds by URL (existing behaviour).

## Doubts / defaults for Kenton
1. A relay running on any machine (even a manual Start on a laptop) makes that KASTR a relay machine. This follows the 0.21.85
   hosts_relay rule.
2. Viewer mode is exempt.
3. A viewer who was watching during the update keeps the old tile ("waiting for keyframe") until the relay drops the old
   connection. The camera then shows as a new tile (library path), not in the old tile's place. Spotlight on the old tile does
   not follow; pins and grids do (libAka).
4. Locked-room codes for page-owned listings are carried in memory only (never stored). After a page reload, a locked room's
   listing needs its code again. Server-owned camera listings keep the code in the sealed feeds file.
5. The rtsp-feeds.json `boxout` record is dropped the next time the bridge rewrites the file. launch.log and /api/diag keep it.
6. kastr.ini relay_autostart is read from the ini next to the code (ini_get), as elsewhere.
7. A box that was in the Lobby moves to No room without listing back into the Lobby.
