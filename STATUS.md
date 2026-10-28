# 0.21.92 H -- Record the presentation

Kenton, 2026-10-28: "Add a toggle for recording the presentation also."

Branch `worktree-agent-aa0e2f9e242a93197`. Main (4e6dfd4, the templates) is merged in. VERSION is not bumped and nothing is pushed.

## Done

- **The switch.** A "Record" toggle (`span.switch.sm` inside a `<label>`) sits in the presenter view's header, next to the timer. Any presenter (the owner and co-presenters) or backstage person can turn it on or off.
  - While it is on, it shows a small elapsed time (`0:26`), counted on the relay host's clock, so every presenter sees the same time.
  - The audience sees nothing: no notice, no flag. The room record the audience reads carries `rec {on, id}` only inside the owner's `pres` record. An older client ignores that field, and the audience UI never reads it.
- **What is recorded.** Exactly what the audience sees and hears:
  - the live slide plus the presenter's camera in the room's current mode (Content, Standout, Side-by-side or Reporter, cut-out included);
  - slide videos and their sound;
  - the presenters' microphones;
  - people a presenter let talk through Ask to speak.

  It never records the notes, the next slide, the presenter view or audience cameras. Output is 1920x1080 at 30 fps, H.264 High plus AAC 48 kHz stereo at 160 kbit/s, in MP4.
- **Where it runs.** On the relay host that holds the deck, a headless browser (`presrec.localhost`) joins the deck's room. It uses a watch-only token that announces nothing, so it is never in People and never in the room's state.
  - It follows the deck's newest owner (`og`), so it keeps going through hand-over, Take over and the main presenter dropping.
- **End.**
  - End finishes the file. Presenters and backstage get a "Recording saved" card with Download links.
  - The file is also listed under **Recordings** in the presenter view (a collapsible panel, refreshed from the relay host).
  - A fresh Start after End makes a new file.
- **Template-made rooms (B's `endPress` hook).** When End also closes the room, the room closes only after the relay host reports the file finished. `__presrec.endWait(id)` polls the list for up to 30 s.
  - Measured: the room closed 2.7 s after End, and the file was already `done`.
- **Templates.**
  - `rec` is a row in `TPL_OPTS`: `{key:"rec", sw:1, text:"Record the presentation", def:0}`.
  - Save as a template records whether it was recording.
  - When a template applies it, `m.recWant` is set, and Record switches on as the presentation starts. End stops it as usual.
  - The old `audSnap`/`startFromFile` wraps are gone; `TPL_OPTS` is the only path.
- **Download rights.**
  - Presenters (the deck's write token) can see, download and delete.
  - Backstage (the read token) can see and download.
  - Admins can see, download and delete everything. An admin is an admin token, or the relay host's own machine (`is_local`).
  - Nobody else gets anything. Downloads use a per-recording key (`dk`), and nothing can be downloaded while it is still recording.
- **Security gate (found in the lab).** The deck's room is only the creator's claim, so a made-up deck naming someone else's room could have been used to listen in. Two guards close this:
  - The recorder records nothing until it sees a member of that room publishing this deck's live record.
  - If the deck is never seen within 90 s, or is lost for 180 s, the recording ends itself (`absent`) and no file is kept.

  Lab result: 0 bytes recorded while Alice's camera and mic were live; it ended at 95 s and the folder was removed.
- **Main's "no plain-text passcodes at rest" change (b0134a7).** Deck meta now keeps `sha256:` digests. `kastr_presrec` compares tokens against the digest (and still accepts an old deck's plain token). A recording's own meta keeps only digests.

## Design and reasoning

### Which relay records
The relay host that holds the deck records: the `/api/pres` store the presenter uploaded to, which is also where the deck's End lands.

- A hand-over keeps the same deck on the same host, so one recorder covers the whole presentation and the file sits next to the deck.
- No presenter's machine has to stay up.

### Why a headless page and not ffmpeg on the tracks
The share track carries only the slide. The mode layout, the cut-out matte, slide videos and Ask-to-speak audio are composed in the page (kastr-pres.js layers). Re-implementing them in ffmpeg would drift from what the audience actually sees.

The recorder reuses `moq-watch-lite.html` and draws:

- the share tile;
- `canvas.presov`, `presvid` and `prescam`, onto a 1920x1080 canvas at 30 fps.

It mixes parallel taps of each heard tile (gain 1 for the deck's videos and for speaking presenters / Ask-to-speak people, 0 for everyone else), then records with MediaRecorder in 2 s pieces POSTed to the host.

The browser is the bundled Chrome for Testing, started with `--headless=new --mute-audio`. It dies with KASTR (job object). It never starts under tests.

### Storage
Each recording lives in `<state>/presrec/<rid>/`:

- `meta.json`;
- `part<n>.rec` while recording;
- `<n>.mp4` after End (ffmpeg `-c copy -movflags +faststart`; if ffmpeg fails, the raw fragmented MP4 is kept).

The file name for download is "<deck name> <date time>[ part n].mp4".

### Size and disk caps, and the warning
- 8 GB per recording (all parts together). It stops there and the file is kept.
- It stops when free disk space drops below 2 GB. Start is refused (507) below 4 GB free.
- 100 GB for all kept recordings together. Past that, no new recording starts (507, "delete some first").
- At most 3 recordings at once per relay host (429).
- Presenters see a warning in the switch tooltip/toast:
  - from 80 % of the 8 GB cap;
  - when free space is under twice the floor;
  - and the reason when a cap stops it ("Recording stopped: ...").
- Each cap can be changed with an environment variable: `KASTR_PRESREC_MAX_GB`, `KASTR_PRESREC_FREE_GB`, `KASTR_PRESREC_TOTAL_GB`.
- Measured output is about 0.2-0.6 Mbit/s for slides plus camera, roughly 100-270 MB per hour, so 8 GB is many hours.

### Retention
Recordings are kept until a presenter of the deck or an admin deletes them. Nothing expires. The tokens are kept as SHA-256, so the file stays reachable after the deck folder is gone at End.

### Restart mid-recording
The file so far is kept and recording continues into part 2, 3, ...

- **Relay host restart.** `resume()` at start picks up every `state:"rec"` recording whose deck still exists and launches the next part. If the deck has gone, the recording is just finished (`why: restart`).
- **Recorder crash or stall.** No piece for 30 s (75 s before the first piece, extended while the page says hello) means a new recorder and a new part.
  - Relaunches are capped at 4 per 120 s, with a warning.
- **Recorder page reload.** `/next` starts a new part, because a second MP4 header in one part would spoil the file.
- End then gives "Part 1, Part 2, ..." links.
- Measured:
  - after the recorder browser was killed, part 2 started 1.1-2.1 s later;
  - the new boot takes about 6-7 s, so the recording has a gap of that length.

### What older clients see
- A 0.21.91 presenter or backstage page has no switch.
- The `rec` field in the owner's `pres` record is ignored by older pages.
- The recorder is not in People on any version, because its token announces nothing.
- A presentation recorded from a 0.21.92 page while a 0.21.91 co-presenter presents still records. The recorder follows the deck record, which both versions publish.

### room.json `pres`
- The owner's page adds `rec: {on:1, id:<rid>}` or `{on:0}` to its `pres` record by wrapping `__state.set`.
- Co-presenters and backstage re-poll `/api/presrec/state` when it changes, so they see the switch flip in about 0.8-1.2 s rather than at the 4 s poll.
- The relay host's `/api/presrec/state` is the truth. The room record is only the nudge.

## Measurements (lab, one Windows box, 1080p)

| What | Result |
|---|---|
| CPU | the recorder page costs ~44 % of one core watching, ~63 % recording |
| Switch on (owner) | 0.12 s |
| Co-presenter / backstage see it on | 0.0-0.8 s / 0.85-1.24 s |
| First bytes after the switch | 6.7-7.4 s (boot plus join); the file starts about 7 s after the switch |
| Template `rec` (TPL_OPTS path) to recording | 4.5 s after `startFromFile(f, {o:{rec:1}})` |
| Main presenter dropped to co-presenter owning | 8-9 s; the recording carries on, and the picture is black in the gap, as it is for the audience |
| End to "Recording saved" card | 3.1-5.2 s |
| End with a template room close | close ran 2.7 s after End, file `done` |
| A 64 s run | 3.5 MB, H.264 High 1920x1080 29.97 fps + AAC 48 kHz stereo 160 kbit/s |
| Recorder killed | part 2 1.1 s later, both parts play |
| Gate (made-up deck naming a live room) | 0 bytes, ended itself at 95 s, nothing kept |

## Tests

`tests/test_release_0_21_92_presrec.py` has 38 tests. The browser launch is always stubbed. The tests cover:

- who may switch (presenter yes, backstage yes, audience no; digest and old plain tokens);
- start, stop and state through the API routes;
- surviving hand-over and the main presenter dropping;
- End finishing the file, including its last-piece wait;
- a fresh Start making a new file;
- stall, crash and reload going into new parts;
- restart resume;
- the boot hello keep-alive and the relaunch cap;
- absent;
- the disk floor, size cap and warning, total cap, live cap, and an open or stopped relay;
- listing, download and delete rights, including admin and per-room admin, no file while live, and kept until deleted;
- digests only at rest;
- the relay's grant giving a watch-only token (puts only `~presrec/<room>`), and a spent or wrong grant;
- the recorder-only routes (Host `presrec.localhost` from loopback only);
- the page checks: the toggle markup with no bare checkboxes, the `TPL_OPTS` `rec` row, `endPress` waiting before `after()`, the marked blocks, the room record carrying only `{on,id}`, and line endings.

Suite results:

- After merging main at 0039ef3 (F's presentation work):
  - Windows `python -m unittest discover -s tests -q`: 2168 tests run, 6 skipped. Only `test_npu_fx` fails, which is known and ignored.
  - WSL (`wsl.exe -u root --cd <worktree> -e ~/.venvs/kastr/bin/python3 -m unittest discover -s tests -q`, run through PowerShell; the bash form was refused by the isolation guard): 2168 tests run, 9 skipped. Only `test_npu_fx` fails.
  - The lab E2E and the gate test both passed again on the merged code. Merging also hit one conflict, in the `TPL_OPTS` table: F's `see` row and my `rec` row. I kept both.
- One more failure, `test_release_0_21_84_presentation` `test_share_row_and_script`, was caused by my tag's position. I moved the tag and that test now passes. The lab re-check afterwards also passed: template start in 3.5 s, part 2 1.0 s after the kill, room closed after the file was `done`.

## Regions touched in shared files

| File | Region |
|---|---|
| `assets/kastr-pres.js` (LF) | `TPL_OPTS`: one `rec` row, marked (~L671-673) |
| `assets/kastr-pres.js` | `endPress()` hook branch: wait for `__presrec.endWait` before `after()`, marked (~L1823-1828) |
| `assets/kastr-pres.js` | `window.__pres.recDeck` block after `window.__pres = {...}`, marked (~L3781-3790) |
| `moq-watch-lite.html` (CRLF) | one `<script type="module" src="/assets/kastr-presrec.js">` tag just BEFORE the kastr-pres.js tag (~L33976); 0.21.84's test keeps kastr-pres.js last before `</body>`, and presrec reads `__pres` only lazily |
| `kastr_serve.py` (CRLF) | precache line (L77) |
| `kastr_serve.py` | `_web_relay_for` (the recorder dials this host's relay, ~L1926) |
| `kastr_serve.py` | `_auth_proxy` (the recorder mints at this machine's relay, ~L3536) |
| `kastr_serve.py` | POST dispatch (~L4199) |
| `kastr_serve.py` | GET dispatch (~L5323) |
| `kastr_serve.py` | startup (~L5713) |
| `kastr_relay.py` (LF) | `AuthService.token`: the `admit "ka-..."` block after `box_guest` (~L7254-7270) |
| `kastr_pres.py` (LF) | the End route calls `kastr_presrec.deck_ended` (~L1830) |
| New files | `kastr_presrec.py` and `assets/kastr-presrec.js` (LF), plus the test file |

## Left / decisions for Kenton

1. **Docker relay image.** It has no browser, so the switch shows "the relay host has no browser to record with". Should the image gain Chromium (~300 MB), or are Docker hosts simply recording-free?
2. **Open relays refuse to record.** A relay with no access codes would show the recorder to everyone, so recording needs codes. Is that OK?
3. **Admin download UI.** When an admin presents or is backstage, the Recordings panel lists every recording of that room, not only the current deck's. The server side lets an admin list, download and delete everything, but there is no separate admin page yet. Should there be a list on the Relay page?
4. **The relay host's own machine counts as admin** (`is_local`), the same rule as elsewhere.
5. **Start latency and gaps.**
   - The file starts about 7 s after the switch while the headless page boots and joins.
   - A relay-host restart or recorder crash leaves a gap of about 6-7 s between parts.
   - During a main-presenter drop, the recording is black, as the audience sees it.
6. **Lab ports.** I used TCP 9220-9239 and UDP 4960-4969. The lab relay on 4960 also used TCP 4960-4962.

## Windows field checklist (Kenton)

1. Relay host with access codes. Present a deck in a room and switch on Record in the presenter view. Check:
   - the elapsed time counts;
   - a co-presenter and a backstage person see it on within about 1 s;
   - an audience member sees nothing.
2. Change modes (Content, Standout, Side-by-side, Reporter) and play a slide video. Let an audience member talk through Ask to speak. Check that a muted audience member is not heard in the file.
3. Hand over to a co-presenter, then close the main presenter's KASTR. The recording carries on; its elapsed time keeps counting.
4. Press End. The "Recording saved" card appears for presenters and backstage. Download plays in Windows Media Player / VLC: slide plus camera, sound, about 30 fps.
5. Start again after End: a second, separate file appears under Recordings.
6. Restart the relay host's KASTR mid-recording. At End there are two parts.
7. A template with "Record the presentation" on: recording starts with the presentation. End in a template-made room: the room closes and the file is still saved.
8. An audience member's page shows no Recordings panel, and its People list has no "Recorder".
