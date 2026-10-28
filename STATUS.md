# 0.21.92 I: Remove and Ban... (agent I)

Kenton (2026-10-28): "When in My room, or an admin for other rooms, give an option on people that allows me to kick from
the room. This doesn't kick them for any specific timeframe. This doesn't block them from coming back. Add an option to
ban (timeframe)."

## Done

- **Remove <name> from the room** (every person menu: People rows, tiles; bottom of the menu under a separator).
  - It closes their sessions on the relay host and the hub and every spoke, and sets **no** block.
  - They land in their main room with "Removed from <room> by <name>.".
  - The toast says "They can come back." A 0.21.91 relay host still blocks for an hour, so the toast warns about that.
- **Ban <name>...** (danger styling) opens a dialog.
  - It offers 15 minutes, 1 hour (the default), 24 hours, 7 days or Until I lift it.
  - The choice is a segmented `role=radiogroup` control with arrow keys and Esc. There are no checkboxes.
  - The hub and every relay refuse the person at:
    - token mint;
    - their invite links;
    - in My room, the owner gate and the access list. Re-sharing does not lift a ban.
  - The person sees "You're banned from <room> until <time>." or "... until <name> lifts it.". This shows on the join page, in the room-switch toast, in the heal loop, and on My room's ended screen.
- **Bans list** with a **Lift** button, in Room settings (admins) and My room settings (owner).
  - It shows who, by whom and until when.
  - A Lift reaches every relay at once over the bans long-poll. The lab measured 28-44 ms.
- **Who can use them:**
  - My room: the owner only.
  - Other rooms: `authRole === "admin"`.
  - Nobody can remove themselves. Only a fleet admin can remove or ban a fleet admin (the relay checks hosts it has seen mint with the admin code).
- **Template rooms:** closing a room (`close_room`, including `why="pres"` at End) drops its bans on the hub. Spokes clear on the next long-poll (20 ms in the lab).
- **`/api/kick`** gets `mode` (`remove` | `ban` | `list` | `lift`), `secs`, `forever`, `who`, `host`, `by` and `byOp`.
  - A body **without** `mode` (a 0.21.91 page) keeps the old one-hour block.
  - Spoke to hub, the call is federated as `{remove}` / `{ban}` / `{lift}`. A 0.21.91 hub sees a plain kick, capped at 1 day.

## How old pages tell Remove from Ban

- **Over `~admin`:** the announce is still `{op:"kick", target, nonce, at, by}`, which a 0.21.91 page obeys (checked against 4f39018 adminApply). New fields `rb:1` and `ban:{until, forever, by}` are ignored there; a 0.21.92 page shows the ban text.
- **At the relay:** the new `mode` field. If it is missing, this is a 0.21.91 page, which gets a one-hour kick, exactly as before.
- **A 0.21.92 page on a 0.21.91 relay:** the reply has no `mode`, so the page warns that the old relay keeps them out for an hour (Remove), or that the ban length was not honoured (Ban).

## Ban identity and its limits (honest)

A ban keys on three things:

1. the **device** (KASTR host slug);
2. the **person key** (`op`, the operator slug the page now sends at mint);
3. the **invite ids** that only that device used. Shared links stay usable by others.

Limits:

- A new device plus a new name gets round it. There is no account system until 0.22 SSO.
- A name match can catch a different person who uses the same name.
- Shared invite links are not blocked for other people. Only person invites and links used by that one device are blocked.
- A 0.21.91 hub caps spoke-forwarded bans at 1 day.
- A 0.21.91 spoke refuses by host only, and keeps an earlier until on a re-ban.
- A Lift on a spoke whose hub is 0.21.91 does not stick; lift from the hub.
- A spoke with its own local admin code does not report admin hosts to a 0.21.91 hub (fleet-admin protection there is host-seen only).
- The set of admin hosts (`_adm_seen`) is in memory only. It is rebuilt as admins mint, so right after a relay restart a fleet admin is protected only once they have minted again.
- Remove on a 0.21.91 relay host is a one-hour block. The page warns about this.
- Removing a My room guest on a 0.21.91 relay host does not close their session.
- **Not done:** the standby replica bundle still exports only the six old ban fields. After a standby failover, bans become plain kicks (until honoured, no `forever`, no `op`).

**kastr_secret:** ban rows hold host slugs, operator names, display names and 8-hex invite ids only. They hold no codes, tokens or invite tokens (asserted in tests and the lab), so `relay-bans.json` needs no sealing.

## Tests

- **New:** `tests/test_release_0_21_92_removeban.py`, 22 tests, OK. They cover:
  - rooms: remove; each ban length; lift; self-removal; fleet admin; old kick; invite links; room close;
  - My room: owner-only; guest and access-list bans;
  - hub and spoke, both directions, including a 0.21.91-shaped spoke;
  - the page: CRLF, menu, dialog, wire strings, marked blocks.
- Windows full suite: see the final report. test_npu_fx always fails; ignore it.
- WSL full suite: see the final report.
- JS syntax check of every script block (headless Edge): OK.
- **Page check** (headless Edge, worktree served on 127.0.0.1:9245, `/api/**` blocked):
  - dialog buttons in order, "1 hour" on by default, 0 checkboxes;
  - "7 days" updates the detail, ArrowRight moves to Until I lift it, OK returns `{forever:true}`, Esc returns null;
  - ban texts render;
  - no page errors.
- **Relay lab** (hub 9241, spoke 9251, a real 0.21.91 spoke on 9255 from 4f39018; token services only, HTTP):
  - Remove: sessions closed on hub and spoke (1 ms). The person rejoins 61 ms later; no bans anywhere.
  - 15-minute ban on the hub: the spoke refuses after 3 ms and the 0.21.91 spoke after 20 ms (by host). Lift reaches them after 28 / 40 ms.
  - 7-day ban made on a spoke: the hub refuses after 5 ms and keeps 7.0 days; the 0.21.91 spoke after 1 ms. A spoke Lift reaches them after 28 / 44 ms.
  - Old clients:
    - a 0.21.91 page kick gives a one-hour block;
    - a 0.21.91 spoke's kick: the hub refuses after 48 ms;
    - a 0.21.92 page on a 0.21.91 relay gets a one-hour kick, so the page warns.
  - My room:
    - the owner removes, and the guest's beat says removed; the guest rejoins with the link;
    - the owner bans: refused, even from another device with the same link;
    - another room's admin gets 403, and banning a fleet admin gets 403;
    - Lift lets the person back.
  - Room closed: hub bans 0; spoke cleared after 20 ms.
- **Not run:** a full relay + page lab (moq-relay needs UDP P plus TCP P..P+3, which does not fit the allowed lab ports).

## Touched regions (shared files)

Every region is marked `0.21.92 I: remove / ban`.

**kastr_relay.py** (LF; line numbers approximate):

| Lines | What |
|---|---|
| 3946-3970 | BanList.hit / mark_via (op, invites, forever) |
| 6451 | `store.on_room_gone` hook |
| 6489 | `_removed` / `_adm` init |
| 7257-7285 | admin verify host, token ban check with `op` |
| 7329 | invite ban check |
| 7338, 14108, 14127 | `_hub_admin_ok` with host |
| 7354 | `_adm_note` |
| 7942 | My room guest state banned / removed |
| 8535-8543 | `_p_share` real-Ban guard |
| 11350-11357 | session invite, revalidate-revoked, admin note |
| 12806-13028 | main block: BAN_SECS, `_adm_*`, `_ban_*`, `_removed_*`, `_ban_room_gone`, `_kick_forward` / `_kick_fed` / `_kick_v2` |
| 13058-13075 | kick dispatch |
| 13654, 13695-13696 | `bans_for_spoke` fields, removed, adm |
| 13997-14038 | `pull_hub_bans` removed / adm / replace |
| 14075 | `_forward_ban` mark_via |

**moq-watch-lite.html** (CRLF):

| Line (approx.) | What |
|---|---|
| 1289-1312 | CSS after `#kConfirm` |
| 3942 | `ICONS.ban` |
| 4243 | openMineMenu `danger` |
| 5565, 5592 | personalStateApply / personalEnded |
| 5677, 5778 | msBuild Bans row / msRefresh |
| 9795, 9807 | participantHasMenu / participantMenu |
| 11171 | adminApply ban note |
| 13806, 13848 | tile menu; libTileItems strip list |
| 18232 | authMint `op` + `ban` on error |
| 18635-18818 | helper block (`rb*`, `window.__rb`) |
| 18823 | `__adminKick` object form |
| 18856 | heal loop |
| 20232, 20314, 20414 | rsBuild Bans row, Lift, openRoomSettings |
| 23308 | joinFail |
| 33255 | `__adminSend` |

assets/kastr-pres.js: not touched.

## For Kenton to decide

- Should name-matching bans stay? They catch a second device of the same person, but also anyone else with that name.
- Is Remove on a 0.21.91 relay host (an hour's block, with a warning) acceptable until every relay is on 0.21.92?
- Should the standby replica bundle carry the new ban fields? Not done.

## Windows field checklist (Kenton)

1. In a regular room as admin, right-click a person and check the menu. The bottom shows a separator, "Remove <name> from the room" and a red "Ban <name>...". Your own row has neither.
2. **Remove.** Their window goes to their main room with "Removed from <room> by Kenton." Your toast ends "They can come back." They rejoin at once.
3. **Ban... > 15 minutes.** The dialog has five segmented choices, with 1 hour selected by default and no checkboxes. They land in their main room. Rejoining shows "You're banned from <room> until <time>.".
4. Open **Room settings > Bans**. The ban shows who, by whom and until when. Press **Lift**; within a second or two they can rejoin, on a spoke relay too.
5. **Until I lift it.** The person sees "... until Kenton lifts it.". Their invite link from another browser on the same PC is refused too.
6. **My room** as owner:
   - Remove an invite guest: they get the ended screen "Removed from ...", and the same link lets them back in.
   - Ban the guest: the link is refused.
   - Give a person access, ban them, then share again: they are still refused.
   - **My room settings > Bans > Lift** lets them back.
7. Try to Remove or Ban a fleet admin from a non-fleet-admin page: refused with a clear message.
8. Run a template meeting that creates its own room, ban someone, then End: the ban is gone from every list.
9. A 0.21.91 PC in the room obeys Remove (lands in its main room). Banned, it cannot rejoin until the ban ends or is lifted.
