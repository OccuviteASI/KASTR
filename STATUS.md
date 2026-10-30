# 0.21.96 — Scheduled meetings (branch `meetings-0.21.96`)

Kenton asked for "templates to also be setup to configure a webmeeting, like a teams meeting. Where I can schedule it for a weekly/daily meeting, or just a 1 time meeting" and "add scheduled meetings to the next update".

## What was built

**Hub side**
- `kastr_meetings.py` (new): the meeting model. It covers:
  - one-time, daily or weekly meetings, kept as a local wall time plus a named time zone, so 15:00 stays 15:00 across a DST change;
  - exceptions: one occurrence moved or cancelled;
  - .ics files: VTIMEZONE + RRULE + EXDATE + RECURRENCE-ID, and METHOD:CANCEL when cancelled;
  - who may schedule what;
  - the door verdicts.
- `kastr_tz.py` (new): carries its own zone rules, because Windows Python has no tzdata. It was cross-checked against WSL zoneinfo with 0 mismatches.
- `kastr_relay.py`: adds `POST /api/meetings`. Its ops are list, get, save, occ, cancel, delete, ics, icsLink, link, beat and end.
  - Each series gets one hidden room `mt-<12 hex>`, minted only by `_meet_token`. It has no registry token and no public presence.
  - The room is never in the rooms list. The hub lets in only invited people (name + My room code) and link guests. It opens 10 min before the start and closes once it empties after the end.
  - A refusal carries `meet: {verdict}`. The verdicts are none / cancelled / early / over / wait / notInvited / who / locked / wrong / old / down.
  - There is a template lease, so the first invitee in applies the meeting's template.
  - Meetings ride the hub bundle, so they survive a hand-over or standby.
- `kastr_serve.py`: forwards `/api/meetings` and `/api/meetings/ics` to the hub (with the .ics file name), and keeps a meeting room's chat from one occurrence to the next.
- `build.py`: one hidden import.

**Page side**
- `assets/kastr-meetings.js` (new), opened from More > Meetings… It has:
  - a list showing only the meetings I am invited to or organize (Live now / Coming up / Cancelled);
  - the schedule form. Every on/off option is a `span.switch`;
  - details, with Join, Download .ics, Copy calendar link, Copy guest link, Edit (this occurrence or the series), Cancel (this occurrence or the series), Delete, and End meeting;
  - a reminder toast 5 min before, and a Join prompt at the start;
  - the lobby overlay (early / waiting for the host);
  - news toasts when I am invited, a meeting changes, or it is cancelled;
  - a `#meet=<id>` deep link.
- `moq-watch-lite.html` (CRLF, via an anchored patch script):
  - `mt-` rooms are hidden like My room;
  - the person rides the mint;
  - refusals open the lobby;
  - the `window.__kmeetPage` bridge;
  - the More menu entry.
- `assets/kastr-templates.js`: `autoApply()` applies a meeting's template.

## Defaults (please confirm)
- "Requires the host to join": **off**. When it is on, invitees wait in a lobby until the organizer or a presenter is in.
- "Guests with a link": **off** by default (open question).
- The reminder comes 5 min before. The room opens 10 min early.
- The room closes 2 min after it empties, once the scheduled end has passed. An overrun lasts at most 12 h.
- Cancelled meetings stay listed for 14 days.

## Who can schedule
- Anyone with a My room: their own meetings, in the meeting's own hidden room.
- Room admins: into their rooms.
- Fleet admins: into any room.

## Known limitations
- People in a meeting room don't show in "Everyone online" as being in that room.
- The calendar link changes after a hub hand-over.
- Fleet admins don't see own-room meetings unless they are invited.
- The list is polled every 60 s; there are no inbox notes.
- Guest links work only for meetings in their own room.
- A meeting's room can't be changed after it is created.
- Organizers have no kick powers.
- The memory that a template was applied is lost on a hub restart.
- The Outlook / Entra seam is a stub (planned for 0.22).

## Pre-existing, not fixed here
- `assets/kastr-templates.js` (0.21.92): the dialog shell's capture-phase `stopPropagation` swallows Enter, so Enter in `.ktpc` never fires. Meetings had the same bug, and it is fixed in its own shell.
- `test_standby_hub.ViewOnlyName` and `test_watch_rooms.RoomScoped` already fail at base 02fca01, because their anchors are missing there too.
- `test_npu_fx` fails in worktrees only, because of untracked model files.

## Tests
- `tests/test_release_0_21_96_meetings.py`: 34 tests, all pass.
- Older tests that pinned the exact `isPersonalSlug(...)` / `is_personal(s)` lines now expect `isHiddenSlug(...)` / `is_meet_room(s)`. Each change is marked "0.21.96".

Full suite: `python -m unittest discover -s tests` ran 2454 tests. There are 3 failures, all known: `test_npu_fx` (worktree only), plus `test_standby_hub.ViewOnlyName` and `test_watch_rooms.RoomScoped`, which already fail at base 02fca01.

## Lab (C:\kastr-scratch\v02196\meetings, ports 9440-9443 / relay 5070, a secured local relay)
`pw_meet.py`, run12: **39/39 steps passed**.
- **Scheduling:** M1 one-time through the form, with a template; M2 with host required; M3 weekly; M4 early.
- **The list and who can see what:** Ada's list shows all four. Bob sees none, gets a 403 on `get`, and is refused at the door as notInvited.
- **Lobbies:**
  - Ada waits in the host-required lobby and is let in about 8 s after Kenton joins.
  - End meeting sends Ada back to her main room.
  - In the early lobby Ada goes in by herself when M4 opens.
- **The .ics file:** it downloads, and the API text has the right RRULE, VTIMEZONE and EXDATE.
- **The weekly meeting across the DST change:** the next occurrence is 2026-11-06 15:00 MST, after 2026-10-30 15:00 MDT. That is 7 days + 1 h in UTC.
- **Reminder and Join:** the reminder fires, and so does the Join prompt. Join now takes Ada into M1, and the template is applied by the first invitee in.
- **Guest:** Copy guest link works. A Pixel-7 guest joins through the link, as a guest, with no Meetings menu. The live count is 3 with the host in.
- **Cancelling:** cancelling the M3 series tells Ada. Cancelling M1 while people are in it sends Ada and the guest out. Ada's list shows both cancelled meetings.

**Fixed during the lab**
- "Cancel meeting" and "End meeting" asked behind their own details dialog: kt-top has z-index 141, above #kConfirm at 140. They now use `ask()`, which steps the meetings dialogs and the lobby under the confirm.
- A single read that hit a dropped connection now retries once: list / get / beat / ics. This was seen twice in the lab.
- The scanner-compliant switch builder.
- Enter in the shell.

**Screenshots:** `meetings-*.png` in C:\kastr-scratch\v02196\meetings. They cover:
- the form (light and dark, plus the weekly form);
- the list (light and dark, plus the empty, live and cancelled lists);
- the lobbies: host-required (light and dark) and early (light and dark);
- the details view, the reminder, the Join prompt and the guest's phone.
