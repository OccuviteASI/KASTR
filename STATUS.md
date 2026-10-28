# Timers branch status (paused 2026-10-28 15:50, before Kenton left)

Target release: **0.21.94**. The code comments still say "0.21.93"; change them when this ships.
Not merged into main. No VERSION bump. Not pushed.

## Commits

| Commit | What |
|---|---|
| ac85b97 | Slice 1: disappearing messages in Messages |
| 02bee83 | Slice 2: send later in Messages |
| 3fa063b | Slice 3: view once in Messages |
| 295fd7d | Slice 4: Room Chat store and routes |
| 9de550b | Slice 4: Room Chat page UI |
| b60e594 | Lab rig hooks |
| (this WIP commit) | Spoke proxy fix, rig hooks, this file |

The spoke proxy fix: before it, a spoke turned the hub's view-once "already opened" (410) into 502. Now that 410 passes through. A hub's "room closed" 410 still becomes 502. There is a unit test for both cases.

At this WIP commit, `test_release_0_21_9*.py` gives 623 tests OK (3 skipped). Both full suites (Windows and WSL) have not been re-run since 35f60bf. They are still to do.

## Lab

The lab runs on loopback only, using headless Chrome with `/api/screen` blocked:
- Hub: KASTR on 9320, relay on 5010, minter on 5011.
- Standby: KASTR on 9322, relay on 5015, minter on 5016.
- Relays use TCP 5010-5018, paired with the UDP 5010-5019 range.
- In the lab only, the standby runs with `LAB_NOT_OWN=localhost`. Without it, the standby counts the hub's loopback address as its own and answers Room Chat from its replica.

The scripts are in the session scratchpad, folder `t93lab`: `lab.py`, `run.py`, `cdp2.py`, `serve.py`. The lab is DOWN and its ports are free.

### Slices 1-3 (Messages): lab done (15:11 run)

- Setup about 1.8 s per person. A plain message is delivered in 1.0 s.
- **Disappearing messages:**
  - When Alice changes the conversation default, Bob sees the system line in 1.5 s ("Alice Lab set disappearing messages to 1 minute"). The "Off" line arrives in 4.0 s.
  - A per-message override kept its own timer.
  - An unread message expires at the 7-day cap. Once read, it expires 60.3 s after the read.
  - The standby has a copy within 2.5 s.
  - After it expires, the message is gone from:

    | Where | Time after expiry |
    |---|---|
    | Alice's page | 1.3 s |
    | Hub message and attachment | 2.3 s |
    | Bob's page | 3.3 s |
    | Standby | 7.8 s |

  - Both people's IndexedDB lose the text and the picture blob. A message without a timer is kept.
  - Offline device: one message expired while Bob was off. The hub deleted it, and when Bob came back it was in neither his IndexedDB nor his page.
- **Send later:**
  - Alice sees "Scheduled for 3:14 PM" in 0.5 s. Change time, cancel and send now all work.
  - Send now reaches Bob in 0.5 s. The standby holds the waiting messages within 2.0 s.
  - With Alice's computer off, Bob got the messages 6.0 s and 3.1 s after their release times.
  - Nothing arrived early. The cancelled message never arrived.
- **View once:**
  - Bob first gets a stub with no text and no file, within 2.0 s. It opens in 0.25 s.
  - Right-click, drag, copy and Ctrl+S are blocked.
  - Opening it a second time shows nothing; the label reads "Opened". Alice sees "Opened" in 0.5 s.
  - The hub and standby delete it 301 s after opening. That 300 s window exists so the attachment can be fetched.
- One runner bug made the view-once timer-menu check record nothing: a no-argument JS function was never called. The helper is now fixed, but the check has not been re-run.

### Slice 4 (Room Chat): applied, lab mostly done (15:36 run 3)

**Applied:** store, routes, beat, standby scrub, page UI, rig hooks and the proxy fix.

**Lab results:**
- **Room default:** the system line shows on Bob in 0.5 s and messages are delivered in 0.5 s. A message expires 59.4 s after it is sent and carries the "1m" badge.
  - Gone from Bob's page 1.3 s after expiry, and from Alice's page, the hub and the standby 4.9 s after.
  - The hub JSONL keeps a `del` tombstone and the original line is scrubbed.
  - A 0.21.92 read gets stub text instead of the message.
- **View once:**
  - Bob's stub arrives in 2.5 s. An old client reads "a view-once message -- update KASTR to see it".
  - After opening, the label is "Opened". If the person who posted it tries to open it, they get 403.
  - Opening it again on the same device gave 502. This was the proxy bug, now fixed; it needs a re-run to show 410.
  - The picture never attached, because of the same no-argument runner bug (fixed, now waits for the upload). So the "viewer shows the picture" check is still open.
- **Send later:** right-click Send, then "Send later…". The picker shows local time with the zone name, and the message shows "Scheduled for Wed, Oct 28, 3:39 PM". It was never shown early. With Alice off, Bob got it 5.3 s after its release time.
- **Per-message timer:** in run 3 Bob did not have the message when the next one landed. Two isolated repros, including a send 1 s apart, showed it delivered to both people with the right expiry. The runner now records lateness and whether Bob's host has it.

### Next steps

1. `python lab.py up`, then `python run.py chat`. Check the view-once 410, the picture viewer and the per-message timer diagnostics.
2. `python run.py msg failover`. Failover has not been run yet: kill the hub, the standby promotes after about 300 s, and the standby releases a scheduled message.
3. Run both full suites:
   - Windows: `python -m unittest discover -s tests -q`
   - WSL: `wsl.exe -u root ... /root/.venvs/kastr/bin/python3 -m unittest discover -s tests -q`
4. Rename the "0.21.93" comments to 0.21.94 if the coordinator wants that. Merge main when asked.

## Honest limits

- **Screenshots:** view once can't stop a screenshot or a phone camera. The hint says so.
- **Old clients (0.21.92 and earlier):**
  - They get a stub line instead of a timed or view-once message.
  - They never see a scheduled message early.
  - An old standby does not scrub deleted lines, so update the fleet together.
- **Clocks:** timers follow the hub's clock. Pages correct for their own skew from the hub.
- **View once in Messages:** the hub keeps it for 300 s after the last reader opens it.
- **View once in Room Chat:** it is once per device. The hub keeps the line until the 7-day cap so other devices can still open it once.
- **Room Chat timers** start at send, because a room has no read receipts.
- **Scheduled messages:** the control tokens for a scheduled message (edit, cancel, send now) stay in the sender's localStorage.
- **Token print:** during debugging, one log grep printed local-lab tokens (24 h tokens, local lab only) to tool output. The lab logs have since been scrubbed.

## Field checklist for Kenton (after 0.21.94 installs on two machines plus the standby)

- [ ] **Messages:** set a 5-minute default; the other person sees the system line.
  - [ ] Unread messages stay.
  - [ ] After reading, the message is gone about 5 minutes later on both sides and after a restart.
- [ ] **Per-message timer:** gives the clock badge. A plain message after it stays.
- [ ] **Send later:**
  - [ ] Right-click Send, schedule for +3 minutes, close KASTR, and check it arrives on time.
  - [ ] Edit the time, cancel, and Send now.
- [ ] **View once photo:** opens once, then shows "Opened". The sender sees "Opened".
  - [ ] Right-click, drag and save are blocked.
- [ ] **Room Chat:** room default, per-message timer, view once (a second open on the same device says "Already opened on this device") and Send later.
- [ ] **Standby:** with the hub off for more than 5 minutes, a scheduled message is still delivered.

## Draft release notes (0.21.94)

- **Disappearing messages:**
  - Pick a timer for a conversation or a room (5 minutes to 30 days, or your own) or for one message.
  - In Messages the countdown starts when each person reads the message, and nothing lasts longer than 7 days unread.
  - Deleted messages are really gone: from the hub, the standby and every device.
- **Send later:**
  - Right-click (or long-press) Send to pick a time.
  - KASTR sends it even if your computer is off.
  - You can change the time, cancel it or send it now.
- **View once:**
  - A message or photo that opens once, then shows "Opened".
  - KASTR blocks saving and copying, but people can still take a screenshot.
- **Room Chat** gets all three. Timers there start when the message is sent.
