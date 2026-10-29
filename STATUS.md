# Timers + latest-only marks: branch status (2026-10-29)

**Target: 0.21.94.** Main (v0.21.93, d3af295) is merged in. Not merged into main, no VERSION bump, nothing pushed.

## Commits (newest first)

| Commit | What |
|---|---|
| 7b4160d | Message marks on the latest message only; the timers' tags and test files renamed to 0.21.94 |
| 34897c8 | Merge main (v0.21.93) |
| a7c87dd | Spoke proxy passes the view-once 410; lab rig hooks |
| b60e594 | Lab rig hooks |
| 9de550b, 295fd7d | Slice 4: Room Chat timers (page UI; store and routes) |
| 3fa063b | Slice 3: view once in Messages |
| 02bee83 | Slice 2: send later in Messages |
| ac85b97 | Slice 1: disappearing messages in Messages |

## State of each item

| Item | State |
|---|---|
| 1. Disappearing messages (Messages) | Done, lab passed |
| 2. Send later (Messages) | Done, lab passed, including the standby releasing it with the hub down |
| 3. View once (Messages) | Done, lab passed |
| 4. Room Chat timers, send later, view once | Done, lab passed |
| 5. Marks on the latest message only | Done, lab passed with screenshots |

## Tests

**Windows full suite, run on 7b4160d's code:** 2323 tests. Only the known `test_npu_fx` failure; 11 skipped.

**WSL full suite** (`wsl.exe -u root ... unittest discover`):
- **Final run, on a quiet machine with the lab down:** 2323 tests. Only the known `test_npu_fx` failure; 10 skipped.
- An earlier run also failed main's `test_release_0_21_93_video_stall` `StuckCaptureReal`. That run shared the machine with the lab and the Windows suite. The test passes on its own (14 OK) and in the final run, so it is load-sensitive, not broken by this branch.

**New and changed tests:**
- `tests/test_release_0_21_94_latest_marks.py`: the rule as a case table. The lab runs the same table through the page's own `window.__msgLatestMarks`, and all 12 cases match.
- `tests/test_release_0_21_93_receipts.py` now checks the new wording.
- The timer tests are now `test_release_0_21_94_{msg_disappearing,msg_send_later,msg_view_once,room_chat_timers}.py`.
- The spoke-proxy 410 test is `SpokeProxy` in the Room Chat timers file.

## Lab (2026-10-29, clean state, loopback only)

**Setup:**
- Hub: KASTR 9320, relay 5010, minter 5011.
- Standby: KASTR 9322, relay 5015, minter 5016.
- Relays use TCP 5010-5018, paired with UDP 5010-5019.
- Headless Chrome for Testing, with `/api/screen` blocked.
- Alice is on the hub and Bob on the standby.
- In the lab only, the standby runs with `LAB_NOT_OWN=localhost`. Otherwise it counts the hub's loopback address as its own and answers Room Chat from its copy.

The lab scripts are in the session scratchpad, folder `t93lab`. Screenshots are in `t93lab\shots`.

### Messages: slices 1-3 (08:49 run)

**Disappearing messages**
- Delivery took 2.0 s.
- Changing the default showed a line on Bob's side in 4.5 s; turning it off, in 4.0 s.
- An unread message expires at the 7-day cap. Once read, it expires 59.7 s after the read. Alice's copy picks up the read time in 6.5 s.
- After it expires, it is gone from:

  | Where | Time after expiry |
  |---|---|
  | Hub (message and attachment) | 4.4 s |
  | Alice's page | 5.9 s |
  | Bob's page | 7.4 s |
  | Standby | 12.4 s |

- Both people's IndexedDB lose the text and the picture blob. A message without a timer is kept.
- **Offline device:** a message expired while Bob's computer was off. It was in his IndexedDB before he went off; the hub deleted it; when he came back (5.8 s), it was in neither his IndexedDB nor his page.

**Send later**
- Alice sees "Scheduled for 8:53 AM" in 0.5 s. Change time, cancel and send now all work.
- Send now reaches Bob in 0.5 s. The standby holds the waiting messages within 1.5 s.
- With Alice's computer off, Bob got the messages 8.2 s and 9.3 s after their release times.
- Nothing arrived early. The cancelled one never arrived.

**View once**
- The timer menu shows View once with the screenshot hint. This is now checked; the runner bug from yesterday is fixed.
- Bob's stub (no text, no file) arrives in 6.0 s. The viewer opens in 5.0 s with the text and the picture.
- Right-click, drag, copy and Ctrl+S are blocked.
- Opening it a second time shows nothing; the label is "View once · Photo · Opened". Alice sees "Opened".
- The hub deleted it 303 s after it was opened and the standby 7 s later. Bob's IndexedDB keeps nothing.

### Room Chat: slice 4 (08:59 run)

**Room default timer**
- The line shows on Bob's side in 0.5 s. Messages are delivered in 1.0 s and expire 60.5 s after they are sent, with the "1m" badge.
- The standby copy updates in 1.0 s. A 0.21.93-style read gets "a disappearing message -- update KASTR to see it".
- After expiry: hub 0.0 s, Alice's page 1.0 s, standby 2.0 s, Bob's page 3.5 s.
- A per-message timer works the same way. The plain message after it is kept.

**Per-message timer arriving late (it recurred, cause found)**
- A timed message reached Bob a moment after the plain message sent 1 s later. It was in the next check, under 0.5 s late.
- The cause is by design: a timed message never rides the room's live track, because it would stay in that track's replay. Other pages get a poke and fetch it from the store. A plain message comes inline on the live track, so it can show first.
- The messages are still listed in order.

**View once**
- The picture uploads in 0.25 s. Bob's stub (Photo) arrives in 2.5 s, and an old client reads "a view-once message -- update KASTR to see it".
- The viewer opens with the text and the picture. Afterwards the label is "Opened".
- **Opening it again on the same device through the spoke now returns 410** (the proxy fix), and the page says "Already opened on this device". The person who posted it gets 403.

**Send later**
- Right-click Send, then "Send later…". The picker shows "(America/Denver)".
- It was scheduled in 0.5 s and was not shown to Bob early.
- With Alice's computer off, Bob got it 9.2 s after the release time. When Alice came back she saw it as sent.

### Marks on the latest message only (09:07 run)

| Step | What Alice sees |
|---|---|
| Bob reading | Only her newest message (K1) has a mark, the eye, after 7.0 s |
| Bob looking elsewhere, she sends K2 and K3 | The eye on K1 and the filled check on K3; K2 has none (6.0 s). Screenshot `k2_alice_newest_delivered_older_read.png` |
| Bob looks again | Only K3, with the eye (6.0 s). Screenshot `k3_alice_newest_read.png` |

- Hovering K2's time, which has no mark, shows "Sent 9:07 AM · Delivered 9:07 AM · Read 9:07 AM".
- **A disappearing last-read message:**
  - K4 (1 minute) is read, then K5 is delivered: the eye is on K4 and the check on K5.
  - K4 went 4.1 s after its timer ended. The eye moved back to K3 with K5 still delivered. Screenshot `k5_alice_eye_moved_back.png`.
- Groups (no receipts: "sent", newest only) are covered by the unit cases, not the lab.

### Failover (scheduled message released by the standby)

**Passed (09:25 run).**
- Alice scheduled a message 7.5 minutes ahead. The standby held it as waiting in 1.0 s.
- Alice's computer went off and the hub was stopped. The standby promoted itself 315.9 s later (the 300 s rule plus its check interval).
- The promoted standby released the message 2.7 s after its release time. That time is taken from when the message file was written.
- Bob's page, connected to the standby, then showed it.
- Nothing came early. The hub was still down, so this was the standby on its own.

**Runner mistake, fixed.** The runner first reported "Bob got it 131 s before the release time". That was wrong: it had matched the same text from the invalid first attempt, which the hub sent when the lab restarted. The standby's record showed the real message still waiting until its time. The failover message text now includes its release time, so a rerun can't match an older copy.

The first attempt was invalid. The lab's "kill the hub" step matched any process connected to the hub's ports, so it also killed the standby. That is fixed (it now kills only the listeners), and the failover was re-run.

## Honest limits

- **Screenshots:** view once can't stop a screenshot or a phone camera. The hint says so.
- **Old clients (0.21.93 and earlier):**
  - They show a "please update" line instead of a timed or view-once message.
  - They never see a scheduled message early.
  - Their own marks stay on every message.
  - An old standby does not remove deleted lines, so update the hub, the standby and all computers together.
- **Clocks:** timers follow the hub's clock, and pages correct for their own skew. Release times show in each viewer's time zone.
- **View once in Messages** is kept for 300 s after the last reader opens it, so the picture can load. **In Room Chat** it is once per device: the line stays on the hub until the 7-day cap so other devices can still open it once.
- **Room Chat timers** start at send (rooms have no read receipts).
- **A timed Room Chat message** can show a moment after a plain one sent right after it (see above).
- **Scheduled messages:** the control tokens (edit, cancel, send now) stay in the sender's localStorage. On another device the sender can't change the scheduled message.
- **Lab only:** `LAB_NOT_OWN=localhost` on the standby, and Bob's "not looking" is the Messages panel folded.
- **Yesterday's slip:** one log search printed local-lab tokens (24-hour tokens, local lab only) to tool output. The lab logs were scrubbed, and greps are masked since then.

## Field checklist for Kenton (0.21.94 on two machines plus the standby)

- [ ] **Messages:** set a 5-minute default; the other person sees the line.
  - [ ] Unread messages stay.
  - [ ] After reading, the message is gone about 5 minutes later on both sides and after a restart.
- [ ] **Per-message timer:** the clock button gives one message a timer. A plain message after it stays.
- [ ] **Send later:**
  - [ ] Right-click Send, schedule +3 minutes, close KASTR, and check it arrives on time.
  - [ ] Change the time, cancel, and Send now.
- [ ] **View once photo:** opens once, then shows "Opened". The sender sees "Opened".
  - [ ] Right-click, drag and save are blocked.
- [ ] **Marks:**
  - [ ] Send 3 messages while the other person is away: only the newest has a check, and the eye stays on your last read one.
  - [ ] When they read, only the newest has the eye.
  - [ ] Hover an older message's time to see sent, delivered and read times.
- [ ] **Room Chat:** room default, per-message timer, view once (a second open says "Already opened on this device"), and Send later with the computer off.
- [ ] **Standby:** with the hub off for more than 5 minutes, a scheduled message still goes out.

## Draft RELEASES.md section

## v0.21.94 — Disappearing messages, send later, view once, and marks on the latest message only

**Disappearing messages (Messages and Room Chat).**
- Pick a timer for a whole conversation or room from its menu: 5 minutes, 1 hour, 8 hours, 24 hours, 7 days, 30 days, or your own length (1 minute to 90 days). Anyone in the conversation can change it, and everyone sees a line saying who changed it.
- The clock button beside the message box sets a timer for the next message only. A message with a timer shows a small clock with the time left.
- **In Messages the countdown starts when each person reads the message.** An unread message never lasts longer than 7 days. Your own copy follows the same rule.
- **In Room Chat the countdown starts when the message is sent**, because a room has no read receipts.
- **Gone means gone:** the hub, the standby hub, every device's saved copy and the pictures and files with it. A device that was off removes them the next time it connects.

**Send later (Messages and Room Chat).**
- Right-click Send (or hold it on a touch screen) and pick **Send later…**. Times are in your own time zone.
- The hub keeps the message sealed and sends it at that time, even if your computer is off. It keeps working if the hub switches to the standby.
- Until then you see "Scheduled for <time>" and can change the time, cancel it, or send it now.

**View once (Messages and Room Chat).**
- Pick **View once** on the clock button. The message or photo opens once for each person (in Room Chat, once on each device), then shows "Opened". You see "Opened" when they have opened it.
- KASTR blocks save, copy, drag and right-click on it. **They can still take a screenshot.**
- The hub deletes it after it is opened (in Messages, 5 minutes after the last person opens it, so the picture can finish loading), or after 7 days.

**Message marks on the latest message only (Kenton: "I don't need to show the seen/read/sent icon for all messages, just for the latest message. It's implied that the previous messages have been read if the last one has been. Keep showing the previous message as read until the last message shows read.").**
- In a conversation, only your newest message shows its mark (sending, sent, delivered or read).
- Until they have read the newest one, the eye stays on the last message of yours they did read, so at most two marks show. Once they read the newest, only it shows the eye.
- A message that failed to send still says "Not sent" on every message it applies to.
- Groups show "sent" on the newest message only.
- Hover the time on any of your messages to see when it was sent, delivered and read.

**Older KASTR (0.21.93 and earlier).** It never shows a scheduled message early. Instead of a disappearing or view-once message it shows a line asking to update KASTR. Update the hub, the standby and every computer together: an old standby does not remove deleted messages.
