# 0.21.94 -- live feeds in a presentation (branch feeds-0.21.94)

Kenton (2026-10-28): "am I able to add other shares to the presentation? Such as another camera feed or a grid? I would
like this for presenters to use and backstage to be able to control."

Based on main d3af295 (v0.21.93). Not merged, not pushed, VERSION not bumped.

## What changed

- **assets/kastr-pres.js** (LF)
  - The owner's `pres` record gains `lf` {p, k, n, g?, by, at}, `fs` (the feed's .hang paths), `lfc: 1` (this owner can
    show feeds) and `lfo` {n, at, why: "offline"} (the last feed that went offline). k = `s` camera / share, `g` box grid
    picture, `c` custom or saved grid (`g` = up to 16 slots in 24 units, at most 16 cameras, optional cycle), `l` library
    stream. `lfClean` checks every feed (kind, path shape, no `-low`, no `..`, bounded grid).
  - `feedSet` (owner) shows / switches / ends a feed and bumps `ver`. Presenters and backstage people who are not the
    owner send `presCtl {lf}` (or `{lf: {off: 1}}`) WITHOUT `to` (`sendFeedIntent`); the owner's `applyOp` handles it
    before the slide-move check. Last writer wins.
  - Presenter view: a **Live feed** panel (search box; groups Yours / Cameras & shares / Grids / My grids / Stream
    library), a purple **LIVE FEED: <name>** mark, a "Room sees: <name>" chip over the slide, **Back to slides** in the
    panel and the bottom bar. Backstage sees the same controls. An offline note stays in the panel.
  - Drawing: `drawFeed` paints the feed into the slide rectangle on the presentation tile's overlay canvas, under the
    presenter camera layer, so Content / Standout / Side-by-side / Reporter composite over it exactly as over a slide.
    The presenter view and the "What the room sees" preview draw it too.
  - `feedSync` tells the page which streams to keep (`__presFeedWant(paths, shares, hear)`); `feedWatch` (owner, every
    700 ms) falls back to the slide when all the feed's streams are gone.
  - `adopt` keeps `lf` through a hand-over / take-over. `tplSnap` never includes it.
  - Rig: `__pres.feed(src)`, `__pres.sources()`, `__pres.feedState()`; `__pres.next()/back()` from a feed = Back to slides.
- **moq-watch-lite.html** (CRLF): feed streams join `cgWarm` (decode off-stage), are `hiddenChild` (no tile of their own),
  ride at priority 190 (presentation on my stage) / 150, play the full rendition (with odWake), are exempt from odPulse /
  odQuick, are heard while the presentation is on my stage (`isAudible`), and a library feed is subscribed through the
  library connection (`libSync`, kind "pres"). Hooks: `__presFeedWant`, `__presFeedWanted`, `__presFeedSources`,
  `__presFeedState`, `__presFeedAvail`, `__presFeedLabel`, `__presOwnFrame` (my own camera / share without a tile).
- **tests/test_release_0_21_94_live_feeds.py**: 18 tests (structure + the feed helpers in the bundled Chromium).
- **REQUIREMENTS.md** (Added in 0.21.94) and **ARCHITECTURE.md** (Since 0.21.16 bullet).
- Older tests whose exact-string anchors moved (same intent, new form): test_release_0_21_76, _0_21_80_two_pointers,
  _0_21_89_presenter_modes, _0_21_91_blackout.

## Tests

- Windows `python -m unittest discover -s tests -q`: 2283 tests OK (7 skipped).
- WSL (`wsl.exe -u root ... /root/.venvs/kastr/bin/python3 -m unittest discover -s tests -q`): 2283 tests OK (10 skipped).
- The new file's Chromium tests run when Playwright is installed (they pass in the lab venv; the plain Windows Python skips them).
- Flaky and not from this branch: `test_release_0_21_92_admin_rc ... test_the_ask_reaches_only_the_person_and_the_claim_key_never_the_admin`
  failed once on Windows (`assertNotIn("ck", json.dumps(d))` matched "ck" inside a random id) and passed on the rerun.

## Decisions

- **Take over the slide** (Kenton's decision). The record still carries the slide underneath, so nothing about the slide
  store changes.
- **Next / Back while a feed is live = Back to slides at the SAME slide** (also a clicker, and the strip's live slide).
  Reason: the room was looking at the feed, not the slide, so the first press should bring the room back to where it
  was, not skip a slide nobody saw. A click in the strip on ANOTHER slide, Home / End, or an older backstage's Next
  (which can only send a slide number) = end the feed AND move.
- **Black / White cover the feed and keep it**; turning the blank off shows the feed again. Feed streams stay subscribed
  through a blank so it comes back at once.
- **Requests carry no `to`**: a 0.21.93 owner ignores them (it acts on `to` only), so an old owner never moves a slide
  by mistake. A newer backstage only offers "Show" when the owner says `lfc`; "Back to slides" is always offered.
- **Offline**: a feed's stream is down after 3 s without a picture (or no picture within 20 s of showing it). When all
  are down the owner goes back to the slide for everyone and records `lfo`; presenters and backstage get a note.
- **Templates never carry a live feed.**
- **A shown feed shows even if that camera would be hidden**: it rides the 0.21.92 `fs` show set of `__presAudHide`.

## Lab (headless Chromium, own lab: boxes 9360-9362, secured relay UDP/TCP 5030-5033; fake cameras, mic off,
## /api/screen/** blocked, KASTR_PRES_POWERPOINT=0)

People: Alice presenter (relay host's KASTR), Cara co-presenter + Bob backstage (second KASTR), Dan audience with a
camera + Vic viewer (third KASTR). Standout mode, "Audience can see each other" OFF, Record ON. Two full runs; second run:

| Step | Result |
|---|---|
| Alice shows Dan's camera -> Vic's picture | 23 ms after the owner applied it (24 ms on Dan's page, 48 ms on Bob's backstage view). Dan's camera was already known to Vic's page (parked), so this is the warm case. |
| Library stream (`lib/...`) shown -> Vic's picture | 643 ms (cold: a new subscription through the library connection) |
| Bob (backstage) switches to Cara's camera | owner applied 10 ms after Bob's request; Vic's picture 45 ms after the request; record `by` = Bob |
| Cara (co-presenter) Back to slides | owner applied 9 ms; Vic's slide 21 ms; Vic's page drops the feed subscription (wanted list empty; Dan's camera back to hidden, priority 120) |
| Next from a feed | stays on slide 1, feed off (the decision above) |
| Hand-over Alice -> Cara, then Alice's page drops | Cara takes over the record in 8.4 s (the existing take-over timing) with the feed still on; Vic sees the feed on Cara's new presentation share 11.2 s after Alice dropped |
| Dan's page drops while his camera is the feed | owner falls back after 7.6 s ("offline"); Vic on the slide 7.7 s after; Bob and Cara get the note; `lfo` in the record |
| Audience with "Audience can see each other" off | Vic is anonymous audience; Dan's camera is in the show set only while it is the feed |
| Recorder (kastr_presrec on the relay host) | MP4 1920x1080 30 fps + AAC, 82 s. Frames show Dan's camera with Alice's Standout cut-out, the library stream, Cara's camera after the hand-over, and the slide after the fallback |

Page errors: none in any of the five pages (warnings only).

## Honest limits

- **Client-enforced.** Who may switch the feed is checked by the owner's page, like slide moves. What a page can actually
  read is decided by the relay's grants: a viewer without access to a stream gets "Not available here" in the slide's place.
- **The owner's own room tile shows the slide**; the presenter view and every other page show the feed.
- **Custom grids:** motion cycling is drawn as time cycling. **Box grids** show the box's own grid layout.
- **Guests** (invite link / My room) see a library feed only when that stream is pinned to the room board: their library
  token covers only board / listed lib paths. Cameras from other rooms ("My grids") show "Not available here" to people
  without access to that room.
- **Recorder:** in the lab it recorded camera and library feeds (same machine as the relay). Its token is the relay
  host's; a library / other-room feed on a real fleet is not verified. Recording the feed's AUDIO is not verified.
- **Offline fallback takes ~7.5 s** (the relay's end-of-stream notice ~4.5 s + the 3 s grace); meanwhile the room sees
  the last picture or "Connecting...".
- **Hand-over gap:** the recording is black for the ~8 s the take-over takes (existing behaviour, not new).
- **Old clients (0.21.93 and older)** keep seeing the current slide (not the feed); an old audience page with "Audience
  can see each other" off shows the feed's camera as an ordinary tile beside the presentation (it is in `fs`). An old
  backstage's Next ends the feed and moves one slide.
- The first lab number (23 ms) is warm; on a real fleet expect the cold number (library: 0.6 s) or more.

## Kenton's field checklist

1. Start a presentation, open the presenter view: the **Live feed** panel lists your camera, the room's cameras and
   shares, grids, My grids and the Stream library. Search filters it.
2. Show a room camera: the room sees it in the slide's place with your camera in Standout / Side-by-side / Reporter;
   "LIVE FEED" shows on your view and backstage.
3. From backstage, switch to another camera, then to a grid, then a library stream. Each switch reaches the room.
4. Press Next: back to the slides at the same slide. Show the feed again and click another slide in the strip: the room
   is on that slide and the feed is off.
5. Black / White while a feed is live: the room is blank; off again: the feed is back.
6. Hand over to a co-presenter while a feed is live: the feed stays.
7. Turn off the camera that is the feed: within ~8 s the room is back on the slide; presenters and backstage get the note.
8. With "Audience can see each other" off, an audience member still sees the shown camera.
9. Record on: the recording shows the feed with the presenter camera.
10. A 0.21.93 viewer in the room keeps seeing the slide.
11. An invite-link guest: a library feed shows only if that stream is pinned to the room board.

## Draft RELEASES.md section

### 0.21.94 -- live feeds in a presentation

Kenton: "am I able to add other shares to the presentation? Such as another camera feed or a grid? I would like this
for presenters to use and backstage to be able to control."

- **Show a live feed instead of the slide.** In the presenter view, the new Live feed panel lists the room's cameras and
  shares, grids, your saved grids and the stream library. Pick one and the whole room sees it in the slide's place until
  you press **Back to slides**. Your camera and your mode (Standout, Side-by-side, Reporter) stay on top of it, just like
  over a slide.
- **Backstage can switch it too.** Every presenter and every backstage person can show, switch or end the feed.
- **Next takes you back to the slides** at the slide you were on. Clicking another slide ends the feed and goes there.
  Black and White still cover everything.
- **If the feed goes offline**, the room goes back to the slides within a few seconds and presenters and backstage get a
  note.
- **It is recorded** with the rest of the presentation, and it stays on through a hand-over.
- The audience still sees only the presentation; the shown camera appears even when "Audience can see each other" is off.
- Older KASTRs keep seeing the slide.
