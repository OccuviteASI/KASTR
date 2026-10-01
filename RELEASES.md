# KASTR release notes

What changed in each build, newest first.

## v0.21.13 — the pacer: a hidden window's frames arrive in batches, and now leave one at a time

**Southridge on 0.21.12, read at the tunnel.** The re-stamp was active (the composite's frames now carried the page's
own clock) and the picture was still frozen: the viewer decoded about one frame every two seconds — the keyframe
cadence — with a stalled buffer. The dev harness reproduced it once the captured frames were held and handed over in
batches: stamped at arrival, a whole batch sits within microseconds, and the publish library keeps one frame per
batch; spread across the frame interval instead, the earlier frames of a batch are stamped in the past and the library
drops them as late. A hidden document does hand its captured frames over in batches, so neither re-stamp could work.

**The fix.** The re-stamp pass is now a pacer: captured frames queue, and a timer releases one per frame interval,
stamped with the wall clock as it leaves. Steady delivery passes with at most one interval of delay; a batch plays out
as continuous video delayed by its own span; a queue longer than two seconds drops its oldest frames.
`window.__restamp` adds `qMax`, `dropped`, `gapMax` and `burstMax` so a box can show whether its capture arrives in
batches.

**Verified on the dev harness (two browsers).** With frames held for 1.5 s and released in batches, the encoder
produced 14.5 fps and a viewer received 14.4 fps of distinct frames, no drops, where 0.21.12 produced 1.2 fps; visible
and spoofed-hidden delivery stayed at 14 to 15 fps. The genuinely hidden case is Southridge's to confirm at the tunnel:
distinct frame timestamps advancing and a buffered range wider than a point.

## v0.21.12 — frames with a frozen clock: every canvas composite re-stamps what it captures

**Southridge on 0.21.11, read at the tunnel and on the box.** The 0.21.11 push worked as built: the composite's encoder
produced frames at 15 fps with the window hidden, and the box's own grid events said `window hidden -- composite frames
pushed by the timer`. The viewers still saw nothing. The probe at the tunnel showed why: the composite's frames arrived at
about 15 fps, in H.264, with every frame carrying the **same timestamp** — the player's buffered range was a single
point — while Mendon's composite arrived with advancing timestamps and played. A frame pushed into a canvas capture from
a hidden document is stamped with the time of the last visible paint, so the pictures were new and the clock was frozen,
and no player advances on a frozen clock. That was also yesterday's "bursts and holes": a visible window for a few
seconds, then frozen frames.

**The fix.** Every canvas composite — the RTSP grid, the camera-effects composite and the file share — now feeds the
encoder through a re-stamping pass: a `MediaStreamTrackProcessor` reads the captured frames, each is re-created with the
wall clock as its timestamp (monotonic, never repeating) and written to a `MediaStreamTrackGenerator` the library
encodes from; the generator reports the capture's settings so the encoder is sized as before. Browsers without those
interfaces keep the plain capture track. `window.__restamp` counts frames in and out and shows the gap between the
capture's clock and the page's.

**Verified on the dev harness (two browsers).** With the pass in place a viewer received 14.0 fps visible, 14.2 fps with
the publisher page told it was hidden, and 14.6 fps restored — identical to the encoder's output — with every frame
re-stamped and none dropped; the capture's clock sat a constant 11 s off the page's, which is why re-stamping is
harmless while visible. The genuinely frozen clock is Southridge's to confirm: the tunnel viewer's distinct frame
timestamps must advance while that window is hidden.

## v0.21.11 — the grid that drew into the dark: a hidden window no longer stops the composite, monitors follow the publisher's passthrough

**From the Southridge box's own diagnostics (2026-10-01, 0.21.10).** The grid composite's encoder had produced zero
frames since launch while the page reported itself hidden; the five camera monitors were healthy, the relay link to Agg
was up with no drops, and the box was registered with the hub. Viewers everywhere saw a frozen or empty grid because
the picture was never produced, not because of the cameras or the link. The grid is drawn by the KASTR window's page
onto a canvas whose capture stream feeds the encoder, and a hidden Chromium document — a minimised window, a locked or
disconnected console, the Go Live tab behind the Relay tab — silences the automatic canvas capture even though the
page's 15 fps timer keeps drawing. The file-share composite had already carried the cure since 0.16.0 (an explicit
`requestFrame()` after each draw); the grid did not.

**The fix.** After every grid draw the page pushes the frame itself whenever the automatic capture is silent: the
document is not visible, or the encoder has not advanced in 1.5 s although the timer is drawing. While visible and
flowing nothing changes. The camera-effects composite gets the same push when its frame clocks fall silent. The grid
notes `window hidden -- composite frames pushed by the timer` and `window visible again` in its event ring (and so in
`/api/diag` and launch.log), and the encoder sampler no longer counts a first reading of zero as "advancing", which had
let a viewer's stall report be dismissed with "grid live here" over an encoder that had never produced a frame.

**Monitors follow the publisher's passthrough.** The same bundle showed every monitor re-encoding — five software 4K
H.265 decodes, about a core each — although the cameras were passed through: the page asks for a copied monitor only
when its own localStorage switch is on, while the pairs had been restored from rtsp-feeds.json with the operator's
persisted `passthrough: true`. The monitor now copies whenever the camera's running publisher copies; a copy the page
cannot decode still falls back to a transcode on its own, so this only ever removes work. launch.log says
`rtsp monitor: feed N follows its publisher's passthrough (copy, hevc)` once per feed.

**Verified on the dev harness (Windows, Edge, two browsers).** A publisher with two test cameras and a viewer on its
grid: 14.3 fps at the encoder and 14.3 fps at the viewer while visible; with the page told it was hidden, 15.2 fps at
both — the explicit pushes do not double the rate when the automatic capture is also running; the grid events show the
hidden and visible transitions. The genuinely hidden case is the field's to confirm: on Southridge,
`/api/diag` → `publisher.grids[0].encoded.frames` must grow while `visibility` is `hidden`.

**On the box until then:** keep the KASTR window restored and its Go Live tab in front; the composite follows that.

## v0.21.10 — full quality always: on-demand pairs and low copies off behind one switch, the monitor outside the six-connection wall

**Kenton (2026-10-01):** "The video streams are better now all around, but not smoothly streaming. Maybe we should just
get rid of the on demand video and go back to full quality always for the time being. I think this may have been the
change that broke it. We also don't need the low quality for thumbnails." And: "This will also get rid of the egress on
the agg server for the announce of 400Kbps."

**Full quality always.** Every published camera runs its full pair from the moment it is published, as before 0.18.0.
No pair sleeps in standby waiting for a viewer, no 640-wide low copy is started, the two per-camera switches ("On
demand", "Low for thumbnails") are gone from the Share panel, a quadrant tap on a grid opens the already-published full
feed, and the demand plumbing (viewer page → relay host `/api/ondemand` → hub → spoke `wake`) goes quiet because nothing
asks and nothing sleeps. Each on-demand camera had cost the publishing box an always-on 640p encode, a third RTSP
session to the camera and wake/sleep churn against it, and every grid viewer pulled its low copy continuously — 400 kb/s
per camera per viewer leaving the hub. A relay pulls a full pair across the cluster link only when a viewer subscribes,
so full-always costs the spoke nothing upstream until someone watches.

**Behind one switch, not deleted.** The code and its tests stay. `ondemand = on` in the kastr.ini beside the exe (or
`KASTR_ONDEMAND=1` in the environment) brings both features back; it is read once at launch and launch.log says which
way it went (`ondemand: off -- every camera publishes its full pair always ...`). The demand travels camera box → relay
host → viewer page, so when it is switched on the key belongs on every KASTR of the fleet. Flags already stored in
rtsp-feeds.json and in the page's own memory are preserved and ignored, not cleared: a camera that asked for on demand
or a low copy is published as a plain full pair and logs `rtsp: <camera> asked for on demand/low -- ignored ...` once,
and the pair-reuse rule ignores those two flags while the switch is off, so a page reload never restarts a healthy
camera over a flag that has no effect. `/api/instance` and `/api/client` carry `ondemand: false`; the page hides the
switches, drops an older spoke's `-low.hang` announces and sends no demand. The 0.21.9 advice to switch On demand and
Low on per Southridge camera is withdrawn. `hook_read` no longer fires for on-demand wakes; it still fires for HLS and
fMP4 fallback viewers.

**The monitor rides a WebSocket — the six-camera wall.** From Mendon: "KASTR isn't letting me add more than 6. If I hit
add, it appears to do nothing. If I close another stream, I get the camera that I added and it shows up once for each
time I hit add." Chromium allows six concurrent HTTP/1.1 connections per host, and every camera's monitor stream on the
box's own page held one of them open for as long as the camera ran, against an embedded server that speaks HTTP/1.0.
Six cameras filled the pool; the seventh Add — and every other request the page made, prefs, the diag post, the feed
poll — waited in the browser's queue until a stream closed, and every queued Add then landed at once. The monitor now
rides a WebSocket, which sits outside that pool; the HTTP pump stays as the fallback for an older host, and the server
answers the browser's close frame so a detached monitor releases its ffmpeg reader at once instead of after Chromium's
60 s close timeout. `/api/diag` shows `monitor.ws` per slot.

**Verified on the dev harness (Windows, Edge).** Eight test-pattern cameras on one page: all eight monitors delivering,
all over WebSocket, the page's own fetch answering in 4 ms after each Add — before the change adds one to five answered
in under 10 ms and the sixth camera's monitor left the page's next fetch unanswered until the renderer gave up. A monitor
socket closed by the page released its ffmpeg reader in 1.5 s. The switch, off: `/api/instance` and `/api/client` say
`ondemand: false`, the Share rows carry no On demand / Low switches, a publish asking for both answers a plain pair
(`ondemand false, standby false, no low sibling`), re-publishing with different flags reuses the pair (gen unchanged),
and rtsp-feeds.json keeps `ondemand: true, low: true`. On (`KASTR_ONDEMAND=1`): the switches are back, the pair sleeps in
standby with its low sibling, and `/api/ondemand` lists it. Four unit tests in `tests/test_ondemand_switch.py` cover the
Publisher, the record and the reuse rule in both states; `build.py` runs the unit tests before every build.

**Rollout.** Hub first, as always — the version match also downgrades, so a 0.21.10 spoke under a 0.21.9 hub would be
put back. A spoke still on 0.21.9 whose cameras were set to On demand stays dark on 0.21.10 pages until it updates,
because those pages send no demand; update such a spoke first, or run the hub with `ondemand = on` for the rollout hour.

## v0.21.9 — audio that adapts to the path, the speaking ring and noise removal back, what a tunnel viewer really sees

**Measured from the tunnel (a web viewer at kastr.madlabs.app, 2026-09-30 afternoon).** Kenton's own camera audio
arrived late 21 times in 40 s on the multi-hop path (app → spoke → hub → tunnel host → browser); every late frame is
20 ms of speech the player drops, and a run of them is the "almost static" heard in a conversation. The Mendon grid
arrived at 15 fps with gaps under 0.2 s over the same last hop; the Southridge grid arrived at 1 to 2 fps in bursts,
with holes of 1 to 9 s — frames come in clusters at the encoder's 15 fps spacing and then nothing, the signature of a
starving or lossy link between Southridge and Agg, not of a slow encoder. The southridge room published only the
composite (no per-camera broadcasts, no on-demand feeds), so a quadrant tap had no full-quality camera to switch to.

**Adaptive audio delay.** A fixed 150 ms delay cannot know the jitter of the hops upstream of the viewer's relay. The
page now listens for the player's own late-frame reports and widens the audio tiles' delay a step at a time while they
keep coming (LAN 150 → 250 → 400 ms; through a web relay 150 → 300 → 450 → 600 ms), stepping back down after two quiet
minutes; each step is one re-tune. On the rig, through a proxy holding the connection 300 to 600 ms every 2 s, the delay
stepped to 600 ms and the late-frame reports stopped completely. `window.__audioDelay` and `state().audioDelay`
(in `/api/diag`) show the steps and the counts.

**The speaking ring and RNNoise were dead since 0.16.0.** The publish library moved the microphone into an
`Audio.Capture` at 0.5.0; the own pane's analyser tap, the noise-removal chain and its watch still read the 0.4 field
and got nothing, so the speaking ring never lit, the mic meter had no live tap, and every microphone went out raw
without the background-noise removal the operator had switched on. All three read the capture now; the analyser's
AudioContext is also resumed on the next gesture (an auto-join creates it suspended). `window.__ownAudio()` shows the
tap, level, context state and denoise state per slot.

**What to check on Southridge** (only that box can tell): `/api/diag` → `publisher.grids[].encoded` frame count and
`encFlatS` (a steady encoder), `/api/relay/health` → `federation.link` drops and re-pins, the relay log for
`cluster peer error`, and the box's CPU while OBS runs; a LinkTest between Southridge and Agg for loss and jitter. To
get full quality from a Southridge camera, publish the cameras as well as the grid ("both"), with On demand and Low
for thumbnails switched on per camera.

## v0.21.8 — the regression hunt: no restarts on a viewer's say-so, a fallback that stops asking, a fixed audio delay, the firewall check in under a second

**What the 0.20.0 → 0.21.x hunt found.** Six readers went over every change in the window and two skeptics
checked each finding; the code of the RTSP pipeline, the vendored player and the relay had not changed. What had
changed was the field: secured relays everywhere, phones and web clients through the tunnel, and a release a day.
Three pre-existing rules were being exercised for the first time, and every one of them turned a viewer's stall
report into a cut for everyone:

- **A native camera's pair restarted on a stall report with no evidence.** The 0.13.3 rule asked the relay whether
  it still listed the camera; a secured relay's listing is empty, so the answer was "no evidence", and the code
  treated that like "not listed" and restarted the pair. One starving remote viewer (a phone, the tunnel, two cluster
  hops) restarted a healthy Mendon or Southridge camera for every viewer every 45 s for as long as it kept reporting,
  and each restart starved more viewers into reporting. Now a running pair with no evidence against it is left
  alone and the report is written to launch.log (`page: pair <name>: viewer stall noted -- no relay evidence`); the
  server refuses a viewer-report restart of any pair that came up in the last minute (`rtsp nudge refused …`).
- **A speaker's camera and mic were torn down on a second stall report.** The camera-slot branch was the one
  report-driven rebuild that never got a gate; every listener lost that person for the seconds it took to re-acquire
  the devices. It nudges the encoder again instead; the encoder's own watchdog rebuilds when the encoder really is
  wedged.
- **The grid's eviction ladder could evict a camera whose pair was fine.** 0.21.5 let a pair vouch for its camera
  only after 60 s of age, and the restarts above kept resetting that clock. A pair vouches by state now: running,
  not in standby, no exit in the last 30 s; a running pair also readmits a monitor-evicted member.
- **Audio's jitter buffer on the LAN was the measured RTT alone (43 to 54 ms).** `delay: "auto"` sizes the audio
  ring from the RTT; `buffer` is only the skip ceiling. Main, rail and grid tiles ride a fixed 150 ms delay everywhere
  now, as web pages already did since 0.21.7.

**The bursts on KASTR-Test and Mendon.** A 250 Mbit/s spike every couple of seconds, with every viewer's session
appearing and vanishing together on the relay's stats, is a client re-subscribing to everything at once: each time,
the relay hands out the latest group of every stream (a full GOP of every camera), and the spoke's cameras are
pulled again over the cluster link. Two loops can do that and both are now bounded and visible: the fMP4 fallback
player (a browser without WebCodecs, or a codec it cannot play) asked again every 2 to 3 s and each ask spawned a
`moq export` child pulling the last 4 s of every track; it backs off now (3, 6, 12, 24, 48 s, capped at 60 s) and
stops after five failed tries with a toast, and the relay host refuses a fallback viewer that starts the same stream
three times in 30 s (429, `watch: fallback viewer <peer> is looping …`). The library's connection reload (1 to 5 s
back-off) re-subscribes every tile per reconnect; the page counts them (`window.__netEvents`, in `/api/diag`),
toasts past three a minute and parks every tile for 20 s past six. The relay host logs `/relay` pipes that lived
under 15 s (`relay pipe: <peer> opened N short pipes in 60 s`), the auth service counts session opens per remote
(`relay auth: <remote> opened N sessions in 60 s`), `/api/relay/health` carries `auth.churn` and the Relay page's
Auth line names the remote; the masthead reloads for a host update at most once per ten minutes. The tell in
KASTR-Test's launch.log is one of those lines; ask for it when the spikes are next seen.

**Also in this release.** The Windows firewall status check reads `netsh` (0.6 s, was 8 s) with the CIM cmdlets
as a fallback; a field host assembles the other platform's install zip by fetching the pinned Chrome for Testing
zip itself (browser.json ships in the app; About says "the host fetches the browser first"); the avatar circle is a
little bigger, its initials size from the circle (one letter 48 %, two 40 %, three 30 % of the diameter) and sit
centred, on remote tiles and on the own pane's standby face alike.

**Not regressions**, checked: the RTSP pipeline's ffmpeg and moq arguments, the vendored player and encoder, the
tile classes and budgets through 0.21.6, the relay configuration and its restart triggers, and the update paths.
Still to prove in the field: which loop KASTR-Test's viewer was in (the log lines above), and Southridge's
launch.log against a blackout.

## v0.21.7 — field fixes round four: the update port, no pane pop-up, download the app, click-to-picture, the spoke grid, audio that does not clip, a firewall prompt that stops

Seven items from the field after 0.21.6, each with its cause.

**The Relay dropdown expected updates on port 8000.** The masthead asked the server to probe the relay host without a
port; the server defaulted to 8000 and never consulted the hub web port every spoke already learns (Agg and Mendon run
their web on 8001), and the failure line was a literal `:8000`. Now the server resolves the base itself (a web relay's
origin, an explicit port, the learned base, the learned port, its hub default, in that order), a probe about this very
machine answers our own instance, and the reply says which base it asked; the line names that. A web client is on the
relay host's own web service, so its dropdown reads "Relay host: KASTR vX — this page follows it" with no port at all.
The Relay page's firewall hint and web-port line follow the server's port too, never the page's.

**A "which server" pop-up stuck on top of every window.** One line set a `title` on every remote pane, grid tile and
collage cell every ten seconds ("via <relay>"); the bundled Chrome drew it as an OS tooltip that outlived focus. The
titles on panes, labels, RTSP rows and grid rows are gone — "via" already lives in People.

**Download the app from the web client.** More → Settings → About lists Windows and Linux with the full install zip
(`KASTR-windows-v0.21.7.zip`, `KASTR-linux-v0.21.7.zip`). The host assembles the zip on the first click from what every
install already carries — its own binary and pruned browser folder, the other platform's mirrored binary and browser
zip, and the templates the feed now carries (`updates/<plat>/extras/`: `kastr.ini` and the Linux `README.txt`,
`install.sh`, `kastr.svg`; a host never ships its own edited `kastr.ini`) — with build.py's entry names and modes,
caches it under the state folder (`downloads/`, one release per platform, a sha sidecar), and streams it with a
`Content-Disposition` name. Routes: `POST /api/update/zip?platform=` prepares, `GET` streams (409 while building), the
manifest carries `zip` and `extras`, `/api/update/extra` hands out a template, binaries and browser zips get download
names. A page whose certificate the browser distrusts (a LAN https page without the local CA installed) has its
download blocked by Chromium itself; a trusted page — the tunnel, the LAN with the CA, plain http — downloads.

**Click-to-picture on an on-demand camera.** The low copy of an on-demand camera stays on the air in standby (one
RTSP pull and a 640p/15 fps encode per camera); viewers get a tile on it at once, under the camera's own name. A click
spotlights the low picture immediately with a "low quality — full starting…" badge and asks for the full pair, which
takes over in place when its announce arrives — no tile is torn down. A quadrant click on a composite whose feed has
no low copy fills the stage with the composite's own cell while the camera starts. Demand now travels the federation
the way bans and room closes do: a relay host that does not know the camera forwards the demand to its hub with the
federation token (`POST /api/ondemand/forward`), the hub pushes a `wake` over its command channel to every spoke, and
the spoke that registers the camera wakes it (Kenton's web client at kastr.madlabs.app → Agg → Southridge). A hub
before 0.21.7 answers 404 and the page says so instead of waiting 90 s. Rail thumbnails on the low copy ask for nothing,
so an idle camera stays asleep until someone actually opens it.

**Southridge's grid for remote viewers.** The likely cause is the cluster link itself: every hub restart mints a new
hub certificate, the spoke re-pins and restarts its relay, and the grid (and its `.member` state) blinks for everyone
downstream. The spoke now reads the link's state off its relay's own log — `relay federation: cluster link to <hub>
up|down (…)` in launch.log, `federation.link {up, since, drops, repins}` in `/api/relay/status` and `/api/relay/health`,
the Relay page's Hub line ("link up 12 m, 3 drops, 1 re-pin, hub sees 2 nodes") — and asks the hub what its relay sees
(`GET /api/spokes/link` → `federation.hubSees`). The owner page's viewer-stall gate reads both: a link that flapped in
the last 60 s is noted, not rebuilt. When the hub is unreachable the stored pin is kept and said once (no restart storm);
composites are a tile class of their own (`grid`, the rail budgets, never `instant`) and get an 8 s removal debounce.
Still owed from the field: Southridge's launch.log with these lines against the next blackout.

**Audio that clipped for everyone.** The library drops the oldest buffered audio group when the buffered span exceeds
`maxAge = delay + buffer`; every 20 ms Opus packet is its own group, legacy audio frames carry no duration, so one
skip registered as a discontinuity — the worklet ring was flushed, the shared sync clock and the decoder reset — and the
budget (200 ms on the rail tile everyone hears; the min-RTT estimate shrinking it further) made skips routine on a
tunnel or a two-hop path (`skipping slow group: track=audio` climbing). Four layers: a 1 s floor on the AUDIO consumer's
`maxAge` in the vendored player (video keeps the library's budget; `vendor-moq.py` now carries `PATCHES`, re-applies
them after every mirror, `--patch`/`--check`, build.py checks, `tests/test_vendor_patch.py`); rail 200 → 400 ms and
fixed web budgets (`delay 150 ms + buffer 800 ms` on main/rail/grid through a web relay — a tunnel, `/relay`); a
tile-class rule that never lands unknown audio on `instant` (which never subscribed audio at all — composites with
sound played silent); and `frameDuration` in ms (the ×1000 failed the library's check and the config was dropped). The
latency badge shows `· skips A/V` for the last 60 s and totals in its title; `window.__slowGroups` counts them.

**The Linux box asked for the firewall on every launch.** `ufw status` was run as the user ("need to be root" →
unknown → pkexec every launch), the web port was set after the check, and a substring match stood in for the ports.
Now the wanted set is computed first, `<state>/firewall-applied.json` remembers what an earlier launch added (or
printed once, headless), the checks are unprivileged and exact (firewalld `--query-port`, ufw's rules file, `ufw status`
as root only), a box with neither tool is told once, Windows joins the port filter so a changed port counts as missing
and each rule is removed before it is re-added (no duplicates). The Relay page names the missing ports.

**Verified.** Unit: the assembler on a scratch root (entry names, modes, prune, `browser/VERSION`, cache, stale sidecar,
old-version prune), peer/instance resolution, the vendored patch, firewall decisions with fake tools, the wake relay's
dedupe and hop rules, the link classifier. Harness rig (Edge): the app's Relay line names the host's version with no
`:8000`; the web client's line follows the host; no `title` on panes or labels; About lists both platforms and the
browser downloaded `KASTR-windows-v<ver>.zip` equal to the manifest's size with the release layout inside; a spoke's
on-demand camera showed on a hub-side viewer as a low tile at once, the truth badge, and the full copy took over 2.6 s
after the click with the spoke logging `hub relayed a viewer's demand … -> woken here`; a hub relay restart wrote
`cluster link … down/up`, `drops`/`repins` climbed and the Relay page said so; a viewer through a proxy holding the
connection 300–600 ms every 2 s heard 65 s with zero audio skips.

## v0.21.6 — a deleted chat line stays deleted

Found on the first secured live test at kastr.madlabs.app (0.21.5): an admin deleted a viewer's line, the host
answered 200, and the line stayed on every screen — the admin's own panel showed it again a moment later. Two causes
in the page's live chat window. A tombstone for someone else's line carries only the store id (the deleter has no
client id for a post that is not theirs), and the window handler dropped any record without a client id before it
looked at the tombstone flag, so no receiver ever removed the line. Then the window replayed the original post and the
deleter's own panel took it back, since nothing remembered that it had been deleted. The handler now honours a
tombstone by store id or by client id, whichever it carries, and every page remembers the ids it has seen deleted so a
replay cannot resurrect them. Verified on the rig: an admin's delete leaves the admin's panel and the viewer's panel
within seconds. Rooms whose chat is kept on the host were already fine, since their history is re-read with the
tombstone applied; this fixes the rooms that only live on the window, which is every room a web client creates.

**The secured half of the live test, done (0.21.5 at kastr.madlabs.app, relay "kastr-test" behind Cloudflare).**
Publisher, viewer and admin joined with their codes and got their roles; both state links connected over the
tunnel; the viewer listed both members, found the camera and decoded the tile and the latency stamp; the encoder
counted frames; chat crossed through the hub; an admin stop reached the publisher in 0.1 s and an admin kick sent it
back to the gate in 0.2 s while the viewer, behind the same Cloudflare address, stayed joined with its state link up.
The moq CLI published and pulled a test pattern through `https://kastr.madlabs.app/relay` over WebSocket as valid
H.264. The one defect it surfaced is the chat tombstone above. Every room the test created was closed afterwards.

## v0.21.5 — the iPhone that fits, an upright camera, a grid that stays up

Kenton's report after 0.21.4: on his iPhone (Safari, iOS 18) "things don't seem to be constrained to the visible
area, it's collapsing some parts and I can't resize", the camera is "always stuck sideways" for him and for every
viewer, the Southridge box's RTSP grid is steady on the box but remote viewers see it "go black, come back for a few
seconds, go black again", a camera that failed more than five times never left the grid, and Southridge never appears
in the hub's spoke table. Four separate causes, one release.

**The phone layout was being undone by source order.** The phone block of the stylesheet came BEFORE the desktop
base rules that use the same selectors, so at equal specificity the desktop rule won: the sidebar stayed a 236 px
column in the page flow, the join gate started beside a rail that is not there, sheets kept desktop widths and `vh`
heights, the drawer showed only bubbles (its "Create room" form landed in a `display:none` box), the 16 px input rule
lost to 11–13 px rules so iOS zoomed into every field and never zoomed back, and `touch-action:none` on every
mainstage meant no pinching back out. The two phone blocks now sit last in the sheet, on purpose and with a comment
saying so. Around that: phone inputs are 16 px (the one `!important` that is warranted), `dvh` twins for every
phone-facing `vh` height, side and top safe-area insets for the notch, `overscroll-behavior:contain` on the sheets and
the stage, a phone always starts with the sidebar collapsed whatever an old session saved, the gallery column is the
full width, a landscape spotlight no longer keeps a 64 px rail-row floor it has no rail for, `touch-action:none` only
where the stage zoom applies (shared content; a camera keeps native scroll and pinch), the sidebar grip hides on
landscape phones too, and a tap on a hidden control while the chrome is idle only wakes the controls instead of
switching the spotlight underneath. Verified in WebKit at iPhone 14 and 15, portrait and landscape.

**The camera was sideways because the vendored publisher loses the frame's orientation on WebKit.** Safari has no
`MediaStreamTrackProcessor`, so the library takes camera frames through its `<video>` polyfill: sensor-oriented
pixels, no rotation in the catalog, sideways for everyone including the phone's own tile. Drawing the `<video>` into a
canvas applies the phone's orientation, and the page already has that loop (the one Rotate, Mirror and the latency
stamp use) — it just never ran with no effect on. A probe (`window.__frameLoop`) now decides: on WebKit without the
processor the light loop runs at 0° for every camera, following the phone as it turns (a new frame size is committed
when two consecutive frames agree; the encoder reconfigures itself). A Rotate saved before 0.21.5 on such a device was
compensating for the sideways picture and is reset once. The portrait constraint swap is skipped there (the loop
already follows the phone). Chromium keeps its raw path; Firefox too (it lacks the processor as well, but its frames
are upright). `localStorage kastr.frameLoop = "1"/"0"` forces either way. With Verbose alerts on, a toast reports
"Camera upright via canvas loop — 720×1280". Also fixed on the way: effects that never started when the camera was
slow to produce its track (the re-arm captured a source that did not exist yet and could never see the track).

**The grid blacked out because any single viewer's stall report rebuilt it.** The grid is composited in the box's
own browser page and published from there; a viewer that starves for five seconds tells the owner, and the owner
closed and re-dialled the grid's connection on every report — at most every 45 s, with no check that anything was
wrong on its side. Single cameras got an evidence check in 0.13.3; the grid never did. One viewer on a weak link cut
the grid for everyone, the cut starved the others into reporting, and the cycle sustained itself while the box's own
canvas never blinked. A report is now a hint: the grid rebuilds only when its own encoder has stopped emitting frames,
its connection is not connected, or its relay no longer lists it — none of which a remote report can cause. Reports are
counted; every decision, build, teardown, relayout, eviction and readmit is a grid event: on the status bar, in
`/api/diag` (`publisher.grids[]`, with encoder stats, connection, last rebuild and reason, stall reports, a ring of
recent events) and in launch.log as `page: grid …` through a loopback `/api/rtsp/note`. A renewed token re-dials the
grids too (one two-second cut instead of the daily gap when the relay closed the old session).

**A dead camera now leaves the grid.** Eviction keyed on the per-camera publisher's restart ladder, but the cell is
drawn from a separate local monitor — so in Grid-only mode, in on-demand standby, or with a camera that accepts TCP and
never streams, the cell said "reconnecting… (attempt N)" forever. The monitor's own ladder evicts too (after the same
five attempts), unless a publisher for that camera has been up for a minute and vouches for it; the cell is readmitted
five seconds after its monitor delivers frames again. The Share row says which ladder removed it.

**An open spoke says so.** A spoke registers with the hub only when its own relay runs secured and holds a hub
federation token; an open relay never registered and never said why, which is how Southridge went missing from the
hub's spoke table. launch.log now carries one line per change of reason ("not registering with the hub: this relay
runs open …", "registered with the hub as <name>"), the Relay page's Federation card and Health line say it too, and a
hub token that could not be cached to disk is kept in memory instead of being re-minted — with a relay restart — on
every ten-minute check.

**Verified on the rig.** WebKit at iPhone 14 / 15 portrait and landscape (gate, join, drawer, sheets, gallery,
landscape spotlight, idle tap) plus an Edge desktop pass unchanged; the upright loop forced in Edge (loop at 0° with
the source's dims, a viewer decodes it, stamp on/off keeps it, rotate 90/0), Firefox and Edge keep the raw path, WebKit's
real probe says the loop is needed; the grid gate (three stall reports and a real `.stalled` announce → no rebuild; a
closed connection → rebuild), `/api/diag` grid entry, monitor-ladder eviction and readmit; an open spoke logs once and a
secured one registers. Both frozen smokes, the frozen two-build update test 0.21.4 → 0.21.5.

## v0.21.4 — the shell that would not update: a stale service worker stands aside

**An iPhone showed "v0.20.0" under a 0.21.3 host for a week, and reloaded forever.** The 0.20.0 service worker
(the offline shell) served everything under `/assets` from its own version's cache, and that included the masthead
script — the file that paints the version and runs the "host updated, reloading" poll. The page itself was fetched
fresh, so the poll saw the host's newer version, said so, reloaded, and got the same old masthead back. A new worker
should have installed on the first visit after the host updated; on that phone it never did (86 files, one at a
time, through the tunnel, and a cut-short install started over from nothing). The server side was fine: the page
and the worker came through Cloudflare fresh and `no-store`. The design let one failed install freeze a browser
for good, and that is what changed.

**Every response now says which build sent it** (`X-KASTR-Version`). A worker that fetches a page and reads a
version other than its own is stale: it stops answering from its cache, passes assets through to the network so
the fresh page runs with an equally fresh shell, and asks the browser to fetch its replacement. The replacement's
install runs six fetches at a time and skips files already in its cache, so a phone that cuts an install short
resumes it. The masthead registers the worker with the HTTP cache out of the way, asks for an update whenever the
tab comes back, reloads **once** when a replacement takes over (and not at all when the page already runs the
host's build, which is what standing aside achieves), and never reloads twice for the same host version.

**The page has a last resort for browsers still holding a pre-0.21.4 worker** — every phone and laptop that visited
during 0.20.0–0.21.3. The page compares the masthead's version with its own; a masthead older than the page can
only mean a stale worker, so the page drops the worker and its caches once and reloads. A second disagreement for
the same build gives up quietly instead of looping. That is how the stuck iPhone heals on its first visit after the
host runs 0.21.4, with nothing to clear by hand.

**Verified on the rig** with one Edge profile against four servers on one origin in turn: 0.21.3 installs its
worker and takes control; 0.21.4 with a worker that cannot install (the stuck case) — the shell check drops the old
worker, the masthead reads 0.21.4, no loop; 0.21.4 proper installs without reloading a first-time page; then 0.21.5
under the 0.21.4 worker — the first load already shows 0.21.5 with no reload at all, the replacement installs and
the old cache goes. Plus the frozen two-build update test (0.21.3 → 0.21.4 through the swap helper) on Windows.

## v0.21.3 — the Windows relaunch, found and fixed; admins on spokes; purge chat; box UI; a readable stamp

**Why Windows relay boxes updated and never came back.** Reproduced on the build machine with two frozen builds
(0.21.1 updating to 0.21.2): the new build started, renamed itself into place, wrote "updated and relaunched" — and
was gone a second later. The cause is PyInstaller's single-file bootloader: it reads the bundled Python archive from
the executable's path lazily, and when the running image is renamed it aborts ("appears to have been moved or
deleted since this application was launched"). The 0.21.0 takeover renamed the new build while it ran; the older
classic path renamed the OLD build while it ran (before it had spawned its successor). Neither can work on Windows.
Now no running image is ever renamed: the updater writes a small helper (`swap-<ts>.cmd` in the state folder),
starts it hidden (its own console, outside KASTR's job) with the scrubbed relaunch environment, and exits; the helper waits for
the old process to be gone, renames `KASTR.exe` → `KASTR.old-<ts>.exe` and `KASTR.new.exe` → `KASTR.exe` (up to
20 s of retries for a scanner's lock), starts `KASTR.exe` at its final path and writes what it did to
`launch.log` — and if the new file could not be placed it puts the old build back and starts that, so the box
always comes back. Verified here: a 0.21.2 box updated from a 0.21.3 authority came back serving 0.21.3 (the
`swap:` line in its launch.log, the old build aside). The takeover stays in the code behind `update_takeover = on`
for experiments only. Linux is unchanged (its relaunch has worked in the field).

**An admin on a spoke could not delete chat.** Chat is forwarded from a spoke to the hub under the spoke's
federation token, and the hub cannot verify a member token the spoke's minter issued — so the admin's delete was a
stranger's. The spoke, which verifies every chat caller anyway, now vouches for its admin (`X-Kastr-Admin: 1`
under its federation bearer); a secured hub honours the vouch only from a federation token it verifies.

**Purge chat from the Relay page.** The rooms table (and each spoke room in the Federation card on a hub) gets
"Purge chat": the transcript and attachments stored on that machine go, the room stays. The relay operator's own
page also sees the delete on every chat line and every shared file (the host already allowed it).

**Unattended boxes have no webcam or microphone controls.** In publisher, publisher-relay and relay modes the
camera/mic toolbar groups, the gate's camera/mic switches and preview, and the audio/video option entries are hidden.

**The latency stamp is readable.** Beside the machine strip the publisher now paints the same clock as text
(`HH:MM:SS.mmm`, relay-host-corrected), and the viewer's badge says "latency 282 ms" instead of a bare number.

**Still to hear from the field:** Southridge did not appear in the hub's spoke table and did not update — a spoke
registers with the hub only when its own relay runs secured (the registration needs the hub's federation token and
its own auth service). Its Relay page Federation card and its launch.log say which it is.

## v0.21.2 — field fixes, round two: boxes, grid quadrants, closing rooms, admins, web cameras

Kenton's second list after 0.21.1 on kastr.madlabs.app, with relay/publisher boxes, on-demand RTSP grids and web
clients through the tunnel.

**An unattended box has no camera tile.** A relay, publisher or publisher-relay box is not a person: since 0.15.0 it
stayed out of People and the counts, but its own webcam still made a tile in the rail. Every viewer now hides that
camera (the box's RTSP feeds and grids are content and still show). The mode travels in the box's presence, so
nothing changes on the box.

**The grid quadrant is the play button.** Clicking a quadrant of an RTSP grid whose feed was on demand (or down)
used to zoom into the composite — low quality, and not the camera. The click now wakes that feed on the relay host,
shows "starting…" over the cell, and opens the feed at full quality the moment its tile exists; in every grid mode,
since the owner announces each member's path. The "On demand" chips disappear for feeds that belong to a grid (the
quadrant does their job); they stay for stand-alone on-demand feeds.

**Nothing leaves its card on the Relay page.** The rooms and spoke tables overflowed a 340 px card by up to 120 px
and the page scrolled sideways, so buttons sat outside their box. Tables scroll inside their card, long addresses
and fingerprints wrap, inputs never exceed the card, and a card is never wider than its column.

**Close a room from the sidebar — and from the hub.** The room's creator, and anyone joined with the admin access
code, sees a ✕ on the room's sidebar card (hover) that closes the room for everyone; the relay operator keeps the
Relay page. The hub's Federation card now lists each spoke's rooms, each with a Close that rides the command channel
to that spoke (it acts within a second and re-registers), so a hub operator closes any room in the federation.

**Admins remove files and chat lines.** An admin-code holder sees a delete on every chat line and a ✕ on every
shared file, not only their own; the relay host accepts the admin's member token for both. Loopback pages (the
operator) could always do this.

**File links through the tunnel.** A web client that shared a file announced it under the host's LAN address (the
page guessed a "reachable" address the way the app window has to), so nobody through the tunnel could download it.
A page reached by any address but loopback now announces the address it was reached by — the tunnel name through
Cloudflare, the LAN https on the LAN — and a viewer whose relay host is public fetches a file announced under a
private address through that host.

**Web clients add RTSP cameras through the host.** A browser has no ffmpeg, but the relay host does: a web client
joined with the publisher code can add a camera address (Share ▸ RTSP feed) and the host pulls it, transcodes it on
its hardware encoder and publishes it into the room under the adding person's name — offered only when the host has
a hardware encoder and its relay requires access codes; the feed is kept across the host's restarts, and only the
person who added it (or an admin) can remove it. A host that has never joined a room with its publisher code says
so instead of adding.

Verified on the rig (Edge): the box camera never becomes a tile; a quadrant click on a down member starts a wake
instead of a zoom; the creator's and the admin's sidebar cards show Close and the creator's click closes the room;
an admin deletes another poster's chat line and another member's file; a web client's file link carries the page's
own origin; the web client's Share menu offers RTSP through the host and an add round-trips; the Relay page keeps
every element inside its card at 1100 and 375 px. HTTP checks: admin close without a key, viewer refused; admin
chat/file deletes from another address; remote RTSP add refused without a token and with a viewer token, accepted
with a publisher token (published under `<room>/<host>/<adder>/`), another publisher cannot remove it, the adder can.

## v0.21.1 — hotfix: a hub never hands out another release's binary

**Mendon "updated" to 0.21.0 and came back as 0.20.0.** The hub at the public name ran 0.21.0 and its manifest said
so, but the Linux file in its `updates/linux/` folder was still the 0.20.0 build: releases are built Windows first,
then Linux, and the Windows zip carried the Linux binary as mirrored at that moment — the previous release's. The
manifest hashes whatever file the hub holds, so the checksum verified, the spoke swapped, relaunched as 0.20.0, saw
0.21.0 on the hub again and would have repeated it every hour. Nothing in the chain carried a per-platform version.

Now every update binary travels with its version (`BUILT_VERSION` beside it, written by `build.py --publish` and by
the hub-to-spoke mirror), the manifest reports a `version` per platform, and a client refuses a binary whose version
is not the one the hub runs — logging *"relay host runs v0.21.1 but its linux binary is v0.21.0; staying on v0.21.0
(the hub's updates/linux/ folder needs the v0.21.1 linux build)"*, shown in amber on the Relay page — instead of
downgrading and looping. A relay box mirroring from its hub skips such a binary the same way. A release zip ships
another platform's co-located binary only when it is the same release, `--publish-only --rezip` rewrites the first
platform's zip once the second is built (part of the release ritual now), and the frozen smokes check that every
platform in the manifest is the release version.

Fixing a hub already holding a stale file: put the right binary in its `updates/<platform>/` folder (a 0.21.1 zip
carries the right ones), or let it re-mirror from its authority; spokes then update on their next check.

## v0.21.0 — the field report: phones, media, relay, fleet

Kenton ran 0.19 and 0.20 through the real tunnel at a public name with phones and other people, and filed 36 items.
This release is every bug and interface fix from that list. Rooms and permissions (waiting room, per-room passcode,
five permission levels, raise hand, kick to the waiting room) are v0.22.0; update hosting on GitHub Releases and a
build guide for every platform are v0.23.0.

**Phones, portrait and landscape.** One phone rule covers both (`max-width: 720px` or `max-height: 500px`), so a
phone held sideways gets the phone layout too. Every popover is a bottom sheet — the share sheet, the People and
chat panels, the camera and microphone menus, and the tile menus behind the chevrons, which used to open off-screen.
Menus that "would not open in portrait" were being closed by the page itself: a phone's address bar fires a resize
and a scroll as a menu opens, and the menu closed on both. Now a height-only resize re-places the open menu and a
phone never closes a menu on scroll. Sheets fit a 375 px tall viewport with one scrolling body.

**Sideways camera.** The Camera menu has Rotate (0°, 90°, 180°, 270°) and Mirror. Rotation alone runs the light
canvas loop (no person segmentation), the output frame swaps its sides for 90° and 270°, backgrounds stay upright,
and the setting is saved and rides the join like the other effects. A phone with Auto resolution asks for a portrait
capture when it is held upright (checked once at start — 0.21.5 corrects the claim that it was re-asked on rotation, and
skips the request where the upright loop already follows the phone); the gate's preview asks for the front camera when
no device is saved.

**Media shares: the scrub that "restarted the file", and the sharer who heard nothing.** The scrub bug had two
causes, both found on the rig with a two-minute file. First, ffmpeg's fragmented-MP4 muxer starts every stream's
clock at zero whatever the seek position was: the real offset only ever lived in an edit list, which MediaSource
ignores — so a seek to 1:30 buffered as 0:00–0:30 and the page's settle step moved the playhead to the start. The
server now reads the real start off the muxer's edit list (`X-KASTR-Start`; it used to carry the requested time,
wrong by up to a GOP for a copied file) and the page places the data there with `timestampOffset`; the copied video
and the re-encoded audio are seeked the same way, so they share one start (the accurate seek had moved the audio to
the exact second and left the video at the keyframe — six seconds of skew on the fixture). Second, a seek orphaned
the previous reader but left its last, half-received fragment queued; it was appended after the buffer was cleared,
the new stream's header followed the torn fragment, and the SourceBuffer raised the "sourcebuffer error" of the
report. The seek now fetches first and clears second (nothing is dropped until the server has answered), flushes
the orphaned bytes, retries a SourceBuffer error once at the same position with a fresh MediaSource, and a re-attach
never ends the share (the old MediaSource's end-of-stream used to fire `ended`, which with loop off ended the share).
A rejected video copy escalates to a transcode again (the page checked 502; the server has said 503 since 0.20).
Rig: seeks to 60, 5, 90, 117 and 0 s land within a keyframe, no restart, no escalation, two seeks back to back
settle on the last one.

The person sharing a file heard nothing because the sharer's monitor was created inside the microphone tap, which
never saw a streamed file's audio track. It now attaches straight from the file's own audio, retries on the next
gesture when autoplay refused, and the media bar has "Hear it myself" (only you) beside "Mute for everyone".

**Media chrome hides itself.** Three seconds without pointer or key input hides the media bar, the file-name bars,
the chevrons, the zoom controls and the Gallery pill; the pointer resting on a control, a control with focus, or a
scrub in progress keeps them; on a phone any tap shows them.

**A resolution picker for every shared file.** After the probe, a small card shows the file (size, codecs, frame
rate, duration, container), warns about unusual files that KASTR will re-encode as they play, and offers "Same as
source" or any rung below it (2160/1440/1080/720/480/360). A web-safe file is scaled in the composite (no server
work); anything else is re-encoded at the chosen height (`&h=`, `X-KASTR-Height`), with a bitrate table for the
hardware encoders and the low ladder one rung below. Web clients get the same card from the browser's own metadata.
The file encoder follows the chosen or source size instead of the camera's cap: a 1080p file share now leaves at
about 2.5 Mb/s (was 1.2).

**The latency stamp is a thin strip in the bottom-right corner.** 48 cells of `max(4, width / 200)` px — about a
quarter of the width from 800 px up, one row tall — with sync cells at both ends, in place of the 0.18 bar across
the top of the picture. Viewers calibrate the cell size from the strip's own sync cells (the decoded picture is the
encoder's size, not the publisher's), sample 3×3 averages against the strip's own levels, and still decode the
0.18–0.20 top-left stamp. A plain camera with the stamp on runs the light canvas loop just to draw it. Rig: the
strip decodes at 1920, 1280, 640, 426 and 320 wide, and a viewer read 282 ms on a file share and the stamp on a plain
camera.

**Spotlight follows the participant.** A spotlight used to be the spotlighter's vote; when they left, everyone's
stage fell back to the gallery. The spotlit participant now mirrors the spotlight into their own room record and
every viewer counts that mirror as a vote, so the spotlight survives the spotlighter leaving and a late joiner lands
on it; the participant re-announces it after a reload within 30 minutes. Another spotlight, the spotlighter's
explicit un-spotlight, the share ending, a room switch or a kick clears it.

**Full screen is the stage.** F, or the full-screen button, puts the whole stage in full screen instead of one tile,
so the RTSP grid, cell clicks, the back pill, chevrons and zoom keep working inside it, and every tile keeps
downloading. **Dead RTSP previews** are gone: the grid owner announces every member's path, which are down and which
are out, in every grid mode, and a viewer never shows a down or evicted member's lingering broadcast as a tile.

**Toasts, switches, small things.** Toasts are a neutral surface with a blue accent; amber for warnings; red only for
errors. Setting toggles (latency stamp, feeds mode, "re-encoding as it plays") are verbose-only. The "a viewer
reported your share frozen" toasts are gone (the nudge and the rebuild stay). Every checkbox on the page and the
Relay page is a switch. The share preview's options button is three dots (it was the same chevron as minimize).
The sidebar's "+" opens the create-room form in a bubble beside a collapsed rail instead of expanding it. The
gate's relay field is a real select (the old datalist filtered to its own value and "did nothing"); choosing an
entry applies at once, "Other…" reveals the address field. Four ASI backgrounds (swoosh, blue motes, light sweep,
horizon) join the scenes.

**Relay: the federation code that vanished after an upgrade.** Five causes, all fixed: the access-code store opened
its file without tolerating a BOM and returned silently on any read error, so the next save wrote every code as
null; every state writer shared one `.tmp` name (a predecessor and its successor, or two threads, interleaved); no
fsync; the hub fingerprint note rewrote the cluster file with the fingerprint alone when its read failed, dropping
the hub address and the code; and the Relay page's Save posted a blank hub address before the field had painted,
which cleared the code. State files now load BOM-tolerant with retries and save through a unique temp name with
fsync and a `.bak`; the code store recovers from the `.bak`, else moves the bad file aside and records LOST (shown in
red on the Relay page, with each code's set date); the fingerprint note merges or refuses; a blank hub address keeps
the code; the page confirms before leaving a hub.

**RTSP feed that kept coming back.** Closing a feed never told the bridge: the page only forgot its own list, the
running pair stayed in the bridge's session file and came back at the next launch or rejoin. Closing now removes it
at the bridge, which keeps a tombstone in `rtsp-feeds.json` so a restore never re-adds a closed address; adding it
again clears the tombstone.

**Windows relaunch after an update.** The shell-escalation path started the new KASTR with no environment, so the
child inherited the frozen loader's variables and became the "bootloader with no child" of the field reports. Both
launch paths scrub the environment; a launched child writes a ready marker as its first act and the parent counts
success only when the marker appears (a silent bootloader is killed and retried); every attempt is logged. Updates
take over in two phases: the new build is downloaded as `KASTR.new.exe` and started FIRST; once it is ready and the
old process has quit, it renames the old file aside and itself into place (finished at the next launch if a file is
locked). `update_takeover = off` in kastr.ini keeps the classic swap. Verified with stub children and on copies; the
frozen two-build test on the dev box is part of the release ritual.

**Update the spokes from the hub.** The hub's Federation card lists the spokes federated to it (name, address,
version, last seen) with "Update spokes now"; the command rides the ban long-poll every spoke already holds at the
hub, so a spoke reacts within a second and relaunches only when its version differs. "Check for updates" on a spoke
asks the federation master, not the LAN relay.

**Relay page.** A responsive card grid (one column on a phone, the log across the bottom), the Server panel split
into Server, Access codes, Startup & mode and Network, the duplicate "allow other machines to update from this one"
switch removed (it fought Web clients over the same setting), the printed firewall command gains the mDNS rule (it
never matched the seven rules the button adds), and the misleading texts fixed (the streams note blamed room codes;
the web-clients hint named a switch that does not exist; the Clear tooltip said three codes; the admin field stayed
filled after a save).

**Not in this release.** Rooms and permissions (v0.22.0); GitHub Releases as the update host and `BUILDING.md`
(v0.23.0); an iPhone pass of the new phone layout waits for the host to run 0.21; the secured-relay half of the
live test (admin stop and kick through the real tunnel) still waits for the host to require access codes.

## v0.20.0 — the tunnel for real, kicks that reach tunneled spokes, an offline shell

**Verified on a real Cloudflare Tunnel.** Kenton's relay host at a public name ran 0.19.0 behind cloudflared. Read-only
probes, then Edge under Playwright: the page was handed `https://<name>/relay`, the WebSocket upgrade got the relay's
101, every host control answered 403, a fake camera published and played, chat crossed, and the latency stamp read
about 0.5 s glass-to-glass through Cloudflare's edge. The moq CLI published and subscribed through the same name over
WebSocket (valid H.264 back). Two defects came out of it, both fixed below.

**An open relay behind a tunnel is public, and KASTR now says so.** With no access codes a relay trusts "the LAN";
through a tunnel that is the whole internet: anyone with the name can list cameras, read chat, pull recordings and
watch. The operator chose to keep it working and be warned: the Relay page's One-port card shows a red line, the
launch log says it once an hour, and every browser visitor sees an amber note on the gate until codes are set.
Setting codes also means starting the relay with "Require access codes" — saved codes alone leave it open.

**Cloudflare swaps origin 502s for its own page.** On an open relay the room-code service does not run, and KASTR
answered 502 for `/api/auth`; Cloudflare replaced that with `error code: 502`, which `watch.html` read as "no KASTR
here". An open relay now answers its own shape with 200 (`secured: false, open: true`), and no KASTR error is a 502
any more (503 passes a tunnel untouched).

**A kick reaches a spoke behind a tunnel or NAT in about a second.** The hub's ban list is versioned, and a spoke
keeps one request held at the hub (`GET /api/bans?since=<ver>&wait=25`) that answers the moment a ban is added or
cleared. Measured on the rig with the spoke federated through a tunnel: 0–2 s from the kick to the spoke's refusal,
against up to 10 minutes before. Un-bans propagate the same way (a ban cleared on the hub's Relay page is lifted on the
spokes), the hub nudges its reachable spokes in parallel, and the 10-minute tick stays as the backstop.

**Browser clients keep an offline shell.** Over https a browser client installs a service worker that caches the app
shell (the page, the masthead, the vendored MoQ library, icons; about 2.5 MB) under the KASTR version that served it.
An installed KASTR opens at once, still renders when the relay host is unreachable and says "Offline" in a toast; rooms,
chat and video need the host and are never served from the cache, nor is anything under `/api/`, the `/relay` pipe or
a request with a query string. A new KASTR build's worker drops the older cache, and the existing version poll reloads
the page. Verified in Edge (registered, 86 files cached, offline boot, API not cached) and Firefox (all but the
"back online" toast, which Firefox does not fire under Playwright's offline switch).

**Firefox was loading the MoQ library from the internet.** The page's import map, which points the library at the
vendored copy, sat below the masthead's module script; Firefox refuses an import map that arrives after a module has
started loading, so every Firefox client fetched `@moq/*` live from esm.sh at whatever version esm.sh served that day.
It passed on 25 September and failed on the 28th, when esm.sh moved to publish 0.5.1 / net 0.4.1: Firefox pages
connected but saw no members and no chat. The map now comes first in the head, and a rig check keeps it there. Edge
and Chrome always honoured the map, so they were never affected.

**Not in this release.** The secured-relay half of the live test (admin stop and kick through the real tunnel) waits
for the host to run with access codes required; an iPhone test of the installed shell; Docker and Mac smokes.

## v0.19.0 — everything on one web port (Cloudflare Tunnel)

**One name, one port.** The relay host's web port now carries the video too: `/relay` on it is a WebSocket pipe to
the relay. So a single Cloudflare Tunnel hostname pointed at `http://localhost:8000` serves the page, the API,
chat, files, recordings, updates and the media. Browsers open `https://<your name>/` and get the full client.
KASTR apps, RTSP cameras on other machines and federated spokes use `https://<your name>/relay` as their relay
address. A relay address ending in `/relay` means "that KASTR's web port carries everything", everywhere KASTR
takes a relay address. On the LAN nothing changes: direct QUIC stays the fast path, and the direct ports keep
working. `docs/cloudflare-tunnel.md` has the recipe. The Relay page has a "One port (Cloudflare Tunnel)" card
with the origin to give cloudflared, the addresses to hand out, the last proxied visitor and the live pipe count.

**Behind a proxy, a visitor is a visitor.** cloudflared connects from 127.0.0.1, and it can rewrite Host to
`localhost`. KASTR used to trust exactly that combination as "the machine itself". Now any request carrying a
proxy's headers (`Cf-Connecting-IP`, `X-Forwarded-For`, ...) is another device. The quit route had its own older
check, and a tunnel with Host rewritten could stop KASTR; it now uses the shared check. Wrong-code lockouts, bans,
chat lockouts and logs count the visitor's address, not the tunnel's. A kick never bans 127.0.0.1, which would
have removed every tunnel visitor.

**Verified on the rig through a local stand-in for cloudflared.** It had one TLS port, cloudflared's headers, and
Host rewritten to localhost. Edge and Firefox joined, published a camera, watched it and chatted. An admin stop and
kick worked, and the other visitor stayed connected. The moq CLI published and subscribed through the tunnel over
WebSocket (valid H.264 back). A spoke federated to the hub through it: token minted, relay linked over WebSocket
after QUIC failed, media crossed the link, and a kick on the hub reached the spoke. Every host control answered
403 through the tunnel. No real Cloudflare tunnel was used, because it would publish the build machine.

**Limits.** A tunnel has no UDP, so media rides WebSocket: a little more delay than QUIC, and head-of-line blocking
on a lossy link. A spoke behind a tunnel cannot be nudged about bans; it pulls them on its federation tick (about
10 minutes). Cloudflare Access in front of the name blocks the native clients unless KASTR's paths bypass it.
Other reverse proxies that send no forwarded headers need `single_port = true` in kastr.ini.

## v0.18.0 — cameras that wake for viewers, cheaper thumbnails, recordings on the relay host

**RTSP cameras can sleep until someone looks.** Each RTSP row has an **On demand** switch (off by default). With it on,
the camera is registered with the relay host but not pulled: viewers see it in an "On demand" row above the stage, a
click wakes it (1.4 s in Firefox and 4.5 s in Edge on the rig from click to tile), and 60 s after the last viewer stops
watching it goes back to sleep. Every watcher keeps it awake: a tile on screen, the relay host's fMP4 or HLS player,
and a recording. The relay's own metrics count no subscribers per broadcast, so demand is KASTR's own signal: the
camera's machine asks the relay host every 5 s which of its cameras are wanted. A grid composite keeps its members on.
Limitation: demand goes to the viewer's relay host, so a camera publishing to a different federated relay does not see
it.

**Thumbnails can pull a small copy.** A second switch, **Low for thumbnails**, publishes a 640-wide, 15 fps, 400 kb/s
copy beside the camera (`<name>-low.hang`, always an encode). Viewers show it on rail and grid tiles and switch to the
full stream when a tile is spotlit; the stats panel says which rendition a tile is on. The low copy sleeps and wakes
with its camera.

**The relay host can record.** The Relay page has a **Record** button per live stream. The host writes one-minute MP4
segments under the state folder's `archive/<stream>/`, keeps them 24 hours (`archive_hours` in kastr.ini) and lists
them on the Relay page with "last 10 min / last hour / all" downloads. Members of a room find that room's recordings
in the Files panel; a download is one MP4 cut from the segments, checked against the member's token like live video.
Recording keeps an on-demand camera awake. Pick a stream while it is live; the pick survives relay restarts.

**Hooks.** `hook_ready`, `hook_notready` and `hook_read` in kastr.ini (or `KASTR_HOOK_*` in the environment) run a
command when a camera has been up 5 s, when it stops, and when a viewer asks for it. The command gets `KASTR_EVENT`,
`KASTR_BROADCAST`, `KASTR_FEED_ID`, `KASTR_RELAY` (without its token), `KASTR_REASON` and `KASTR_VIEWER`, runs
detached, and is killed after `hook_timeout` (30 s). The launch log names the hooks that are set.

**Older iPhones get HLS.** A browser without MediaSource that plays HLS (iPhone before iOS 17) asks the relay host for
`/api/watch/<stream>.m3u8`. The host checks the token, hands out a private playlist address and runs one HLS exporter
per stream, shared by its viewers and stopped 45 s after the last request. A playlist address dies with its token, a
kick, or two minutes unused. Verified with ffmpeg through the proxy (720p H.264); no iPhone was on the rig.

**Glass-to-glass latency on screen.** More ▸ **Latency stamp on my shares** draws a small strip into shared files, RTSP
grids and effected cameras; every viewer decodes it and shows the latency in the stats panel. Measured on the rig:
about 0.5 s in Edge and 1.5 s in Firefox for a shared file. A plain camera without an effect carries no stamp.

**A kick reaches every spoke.** Spokes tell the hub where they answer; a kick on the hub, or one forwarded to it by a
spoke, now nudges every spoke, which pulls the hub's bans with its federation token and applies them. Verified with
two instances: the spoke refused the removed device within five seconds. A removed member is also refused by the
relay host's side doors (on-demand, recordings, HLS).

**Fixed on the way.** Two quick option toggles on an RTSP row could race and lose one (publishes are now serialised per
feed and the page waits 400 ms). `watch.html` retries a transient server error instead of printing the exporter's log,
and keeps the lower-latency MediaSource path on desktop Safari.

**The failed-relaunch path, tested.** The owed negative case ran on the rig: a 0.17.0 client updated from a 0.18.0
authority while the swapped exe was held locked. The swap landed, every restart attempt was refused, the update note
said `relaunch-failed`, the dialog asked for a manual restart, and the old window kept serving 0.17.0. The test also
showed the retry window ending at 10 s instead of 30 s, because the shell launch step raised; and without the "no UI"
flag Windows could put up its own error box. Both are fixed for updates from 0.18.0 on: any launch error is retried
inside the window, and the shell reports a locked file at once (verified from source against a locked exe: started
through the shell 19 s in, once the lock lifted).

**Not in this release.** Per-subscription priority on tiles (the vendored player has none), Let's Encrypt, a service
worker, the Docker and Mac smokes (no Docker or Mac on the build box), and an iPhone test of the HLS path.

## v0.17.0 — open KASTR in any browser: the relay host serves the client

**No executable needed any more.** Point a phone, tablet or laptop browser at the relay host's web address and you get
KASTR — the same page the app shows, served by the relay's own KASTR, so browser clients always run the relay's version
(they reload themselves when the host updates). Over **https** (port 8443) a browser client does everything a full client
does short of the host's own hardware: rooms, People, chat, spotlight, the admin code's Stop / Mute / Remove, and it
publishes its camera, microphone and (on desktop browsers) its screen. Over plain **http** (port 8000) the browser blocks
its camera, microphone and its own decoder, so the page is a lobby with video: rooms, People, chat and admin work, and the
spotlit stream plays through the relay host as fragmented MP4 (one stream at a time). What stays on the host: the RTSP
bridge, media-file transcoding, relay controls, updates, preferences. Each browser is its own device (`web-<id>` host, so
two phones never collide), and a page on another device can no longer keep the host's window alive, move its window,
rename its operator, spawn feeds on it or read its diagnostics — every host control now checks Host, peer and Origin,
not the Host header alone. Chrome/Edge and Firefox were verified end to end on the rig (lobby, https publish + view,
admin stop and remove, chat, PWA manifest); Safari, iPhone and Android are best-effort this release.

**Trust has two doors.** The relay host's KASTR certificate authority still works as before — install `/ca.crt` once per
device (the Phone access card shows the QR and the addresses, now including `<hostname>.local`) — and an operator can
drop a real certificate in instead: `tls_cert`, `tls_key`, optional `tls_chain` and `tls_hostname` in kastr.ini serve
both the web page and the relay's wss listener, with a daily check that picks up a renewed file (certbot / win-acme write
into those paths) and one log line a fortnight before expiry. Automatic Let's Encrypt is not in this release: it needs a
public name and an inbound path the robot-site relays do not have. The Relay page gained a **Web clients** switch that
writes the host and https settings, adds the firewall rules and lists the addresses to open; it also warns when the relay
is bound to the machine only (browser clients need it on the LAN). Installable as an app: `manifest.webmanifest` + icons,
"Add to Home Screen" opens KASTR full-screen (https only).

**A removed member is removed at the relay too.** An admin's Remove used to ask the page to leave; now it also tells the
relay host, which bans that device's identity in that room for an hour (`relay-bans.json`), closes its live sessions at
once (the relay re-validates every session on request — measured: a refused re-validation closes the session within two
seconds) and refuses its re-entry with an honest gate message. A kick on a spoke is forwarded to the hub with the
federation token; other spokes still rely on the page-side announce. The Relay page's Health panel lists removed members
with a Clear button.

**Measured and recorded.** moq CLI 0.12.1 against relay 0.15.1 prints the same session strings 0.11.2 did (`Error:
unauthorized` for a refused token — the pair parks and re-mints; `session closed, reconnecting` on a bounce — it survives),
and a 25 s outage lets the CLI's backoff expire and the pair ladder, never park. The LAN mesh discovered a second relay on
the same box over mDNS within 20 s (`advertising on the LAN … app=kastr`, `dialing LAN cluster peer`, `accepted LAN
peer`). The auth server's revalidate cadence: measured on the rig at about 605 s after connect for every session (the grant's 600 s plus the relay's tick), and the token rides the revalidate request, so a ban lands at connect, at revalidate and at the minter. The pane's per-site sandbox blocks WebSocket
from a LAN-address page, so browser verification moved to real browsers (Playwright: Edge, Firefox, WebKit).

**Not in this release.** HLS for iPhones older than iOS 17 (the CLI can export it; the endpoint waits for 0.18), a
service worker / offline mode, per-subscription priority on viewer tiles, Let's Encrypt, the Docker and Mac smokes (no
Docker or Mac on the build box — the commands are in DOCKER.md / MACOS.md), and the media items from
`docs/moq-landscape.md` (3, 5, 6, 8, 12) which form v0.18.0.

## v0.16.0 — relay stack 0.15, an admin code, a relaunch that comes back, shares that end

**The relay stack moved to moq-relay 0.15.1 / moq 0.12.1, and KASTR now answers the relay's questions.** A 0.15 relay no
longer checks tokens itself: for every session it asks an HTTP auth server (`connect`, `revalidate`, `end`) and gets back
what that session may publish and subscribe to. KASTR's token service on the relay host (relay port + 1) is that server,
and it still verifies the very same tokens the gate has minted since 0.13 -- so a 0.15.1 client, a 0.15.1 native
publisher and a 0.15.1 spoke keep working against a 0.16.0 relay, and the reverse holds too: a 0.16.0 client publishes
and watches through a 0.14.18 relay (both directions rig-proven before this shipped). Roll out hub first:
the Agg hub, then Mendon/Southridge follow within the hour, clients on their next launch. The relay's config is the new
shape (`[listen]`, `[auth] url`, `[connect]`, `[internal]`; the old spellings are gone and a `renamed` line from the relay
now surfaces on the Relay page), the native publisher speaks `--connect` / `--max-age 5s`, and the vendored web library
is `@moq/watch` 0.6 / `@moq/publish` 0.5 / `@moq/net` 0.4 (everything goes through the connection's origin; the state
tracks ride at priority 200 so presence and room state win under congestion). Tiles are tuned per class: the spotlit
tile buffers 400 ms, rail thumbnails 200 ms, grid composites and audio-less grid members run at the live edge.

**One admin code, honoured across the hub's relays.** Beside the viewer and publisher codes the relay operator can set an
admin code (Relay page ▸ Access codes). A client that enters it joins as an admin: every remote tile's menu gains "Stop
sharing", "Mute" and "Remove from room", and the target's page obeys within a second (toast on the target, the removed
page lands on the gate and does not silently rejoin). A spoke with no admin code of its own asks the hub whether the
code is the hub's -- so one code set on the hub works on every federated relay. The Relay page itself can push "Stop" to
any stream on the relay (a relay operator's stop reads "Relay operator stopped your share"). Admin commands travel as
announces under `<room>/.admin/...`, a path only an admin token may publish; a forged command from a publisher or viewer
is dropped by the relay and counted as a refusal on the relay's health panel. Removal is cooperative in 0.16.0 (the page
leaves); server-side session revocation is on the 0.17.0 list.

**Federated relays pin each other's certificates.** A spoke learns the hub's certificate fingerprint from the hub's token
service (or `/certificate.sha256`), writes it into `[connect] tls.fingerprint`, and re-learns it within 30 s when the hub
restarts with a new certificate (the relay's log wording for the mismatch is matched). `tls.insecure` remains only as the
fallback when the hub's web port is unreachable, and the Relay page says which of the two is in force. Same-site relays
can also find each other over mDNS (Relay page ▸ Same-site relays: enable + a shared secret generated on the page; the
firewall gains a UDP 5353 rule -- expect one more firewall prompt on Windows boxes that host a relay).

**Health and metrics.** `GET /api/relay/health` reports the relay (sessions, cluster nodes, internal API), the auth server
(sessions, publishers, grants, refusals, the last refusal), federation (hub, token, pinned/insecure), LAN peers, every
publisher pair (`gen`, `restartsTotal`, `sessionFails`, `sessionKills`) and the helper versions; `GET /api/relay/metrics`
(loopback) is Prometheus text: the relay's own counters plus `kastr_*` gauges. The Relay page shows both in a Health
panel.

**Windows self-update now comes back.** The updater swapped the exe and then fired one blind `Start-Process` at a file
Defender was still scanning; when that failed, the old KASTR kept running with the new exe on disk. The relaunch is now
spawn, verify, retry, escalate: it retries the direct spawn while the file is locked, respawns a child that died at once
("bootloader with no child"), escalates to the shell's own launch path after 10 s, and only exits once the successor is
confirmed. If nothing comes up within 30 s it says so (`relaunch-failed` in `update-check.json`, a dialog) instead of
vanishing. Switching relays checks for updates on the new host's real web port (learned first), never on `:8000`.

**Field fixes.** The grid chevron menu is a body-level popover that clamps to the window and scrolls (it was clipped inside
the pane). Your own camera can be spotlit again: the pane keeps its id through the rebuilds that used to drop the
spotlight, and its menu offers "Spotlight for me" / "for everyone". A GIF background animates (decoded with WebCodecs,
frame by frame; a still first frame only on a browser without `ImageDecoder`). A grid member opened on its own wears its
label ("Kenton — Gate cam"), on the owner's pane and on viewers' tiles.

**Shared files: health readout, a nicer transcode, loop off by default, and paused means paused.** Mikey's file share
hitched while his camera from the same machine was fine: two encoders on one CPU. The server transcode now runs below
normal priority on half the cores, the composite follows the file's own frame rate (a 24 fps film is no longer drawn at
30), the owner's media bar shows a health pill (`24 fps · 1248 kb/s · hw · h264_qsv · 44 s`, amber when the page's encoder
sags, red while buffering), and a sagging encoder asks for the lighter transcode ladder after three seconds instead of
waiting for two rebuffers. Loop is OFF by default; with loop off a share ends at the end of the file (`playing:false`,
then the source is removed, with a "Play again" toast). A paused share stays paused: every path that could restart it
(reopen, buffer tick, retry, control replay) now honours the user's pause, reopens keep the position instead of
restarting at 0, and `__mediaDebug()` lists the last restart causes.

**Not in this release.** Per-subscription priority on viewer tiles (the element does not expose it yet); the native
publisher's hard/soft exit strings were not re-measured against moq 0.12.1 (the 0.11.2 strings are still matched -- if a
dead token ladders instead of parking, that is the place to look); the auth server's `revalidate` cadence has not been
observed on the rig; media items 3, 5, 6, 7, 8, 12 from `docs/moq-landscape.md` are the 0.17.0 plan.

## v0.15.1 — hotfix: shared files publish in H.264 with the hardware encoder

**A shared file was still choppy from a laptop.** Two encoders sit behind a shared file and both were software: the
server-side transcode ran libx264, and the page published the composite with the library's default VP9, which has no
hardware encoder on most laptops. Now the transcode uses the same validated hardware H.264 encoder the RTSP path uses
(NVENC / QSV / AMF / MediaFoundation / VA-API, libx264 superfast otherwise) and drops to a 960-wide / 24 fps ladder after
two rebuffers; the page publishes a shared file as H.264 (`avc1`, hardware preferred) unless the operator picked a codec.
Every viewer decodes H.264 in hardware too. The response carries `X-KASTR-Encoder`; `__mediaDebug()` shows `encoder`,
`lowQ` and the audio path (`actx`, `atrack`, `pubMuted`). The "no audio" report turned out to be the share's own mute
button; the rig confirms audio leaves the owner and arrives at viewers.

**Release notes show the running build.** The version pill's notes open on this build's section only, with
"Show previous versions (N)" folding the history underneath (the "this build" tag now matches headings that carry a
title after the version).

## v0.15.0 — the hub's web port everywhere, groups and grids, quieter alerts, backgrounds that stay

**Chat, rooms, files and updates follow the hub's web port now.** 0.14.0 let a hub pin its web port, but every page still
built its hub URLs from the literal `:8000` (chat poll/send, room list/register, files, avatar), spokes learned the port
only from a secured hub and only inside the federation refresh, plain clients never did, the hub itself could decide it
was a spoke of itself once its own port moved, and the version follow used `kastr.ini update_port` (8000) no matter what.
Now every machine that knows a relay learns that relay host's web (and https) port at launch -- from the token service
(`/api/auth`) or, on an open relay, by asking `/api/instance` on the likely ports -- BEFORE the first update check, then
every five minutes; the result lives in `hub-web.json`, feeds `/api/instance.hubWeb`, the chat proxy, the update follow
(`update_port_for`: an explicit `update_port` still wins) and the page (`window.__auth.web/https`), and a failed chat probe
re-detects the port so a move heals within 30 s. Relay boxes now also **mirror the hub's other-platform binaries and browser
zips** into their `updates/` folder after each update check (about 300 MB once per version; `update_mirror = false` in
kastr.ini opts out), so the machines behind a spoke update to the same version instead of the version the spoke was
installed with.

**Rooms can be grouped.** Groups are defined on the relay (relay-auth.json), managed by the relay operator or the room's
creator, and shown to everyone as collapsible headers in the sidebar (collapsed state is yours). Drag a room onto a group,
or use the room menu's "Move to group…"; operators rename, ungroup or delete from the header. The collapsed sidebar's "+"
now opens the sidebar instead of a hidden form.

**Many RTSP grids, and the grid grew controls.** Each RTSP feed row has a Grid picker; grids are nameable ("Vehicle 7"), keep
their own seats, order and layout, and each is its own tile in the room (grid 1 keeps its old broadcast name, so nothing
existing changes). Hover a cell on the stage to remove that feed (Undo in the toast), spotlight a grid for yourself or for
everyone from its menu, rename a feed's display name without republishing it, and turn on "Show names on grid cells".

**Quieter alerts, a room tone, honest People.** Toasts have levels; the default shows room events and anything that needs a
hand, and hides the informational echoes (View ▸ Verbose alerts brings them back). Switching rooms plays a short two-note
tone. Publisher and relay boxes announce their mode and no longer appear as people in the room.

**Backgrounds that stay, move, and cut out better.** The saved background effect survives a rejoin or a room switch (the
join path never passed it to the camera). Four built-in looping scenes (Drift, Grid, Rain, Aurora), your own GIF or video
as a background (stored locally, never sent to anyone), and a tuned segmenter: GPU delegate with CPU fallback, 15 fps
masks drawn at 30 fps, temporal smoothing and a feathered edge, plus a "Best" quality option using MediaPipe's landscape
model. Everything stays offline.

**Smooth media shares.** A shared file that needs conversion no longer plays from the transcoder's live edge: playback
starts from a four-second cushion, pauses quietly ("Buffering…") when the cushion runs dry and resumes at three seconds,
the transcode is capped at 1280 wide with a faster preset, and viewers keep seeing "playing" through a rebuffer.
Effected cameras (blur, backgrounds) keep moving when the app window is minimised: a timer takes over from the frame
clock the browser stops.

**MoQ landscape.** `docs/moq-landscape.md` records what MediaMTX, MainStreaming/OpenMOQ, moq-dev 0.15, the IETF drafts,
Cloudflare and Meta are doing, with a ranked backlog of twelve realistic improvements. Nothing from it is implemented yet.

## v0.14.0 — the same port every launch, a camera that stays dead leaves the grid, media files stream as they convert, source on GitHub

**A box whose port 8000 is taken forgot everything on every launch.** The app page keeps its memory in the
browser's localStorage, which is scoped to `http://127.0.0.1:<port>`. When 8000 was held by another program
(Southridge: System PID 4) the launcher took an OS-assigned port -- a different one on every launch -- so
every upgrade (and every restart) started with an empty page: no last room, no RTSP history or kept feeds,
no grid seats, no profile. The cameras themselves kept publishing (`rtsp-feeds.json`), only the page forgot.
Now the launcher scans 8001..8040 deterministically and remembers the port it bound in `port.json` in the
state dir, so a box moves once and stays there (`--port`, or a kastr.ini `port` other than the default 8000,
still wins; delete `port.json` to go back to 8000). Belt and braces: the page mirrors its settings to the server (`prefs.json`, loopback
only, `GET/POST /api/prefs`) and seeds an empty origin from that file, so a profile wipe or another port
change no longer costs the operator their setup. Access codes are stripped before mirroring -- the standing
rule that codes never leave the loopback-guarded state files and are never echoed by a GET holds -- so after
an origin loss the gate preselects the room and relay and the code is typed once. A box that already lost
its storage is rescued from `rtsp-feeds.json`: the room, the relay and the kept camera URLs come back.

**A camera that is offline for more than five attempts leaves the grid until it reconnects.** The grid used
to keep a "reconnecting… (attempt N)" cell forever. Now, once the bridge has restarted a pair five times in a
row without it living (about 40 s into a hard outage; the counter resets after a minute of good video, so a
blip never evicts), the owner drops the member from the grid: the mosaic relayouts, viewers' hidden
full-quality tile stays hidden (`out` in the grid geometry), the Share row says "offline — removed from grid
(attempt N); retrying", and the seat is kept so the camera comes back into its old cell about five seconds
after the pair is publishing again. The viewer also stops hiding a feed forever once its grid no longer
lists it (a latent 0.13.x bug).

**Sharing a media file that needs conversion starts in seconds instead of minutes.** The old path uploaded
the whole file, ran ffmpeg to completion into an MP4 (plus a faststart rewrite and, on a copy failure, a
second full pass) and only then started playing. Now the file uploads while it plays: `POST /api/media/upload`
registers it at once, `GET /api/media/<id>/stream?t=` transcodes from any position into fragmented MP4 that
the page feeds through MediaSource with real file timestamps (`-ss` before `-i` + `-copyts`), so the media
bar, seek, loop and the viewers' mirrored bars keep working; a seek or a loop re-opens ffmpeg at the new
position (about a second of gap), a paused share stops reading and ffmpeg idles, one ffmpeg per share is
killed on stop, page close or DELETE, and a rejected video copy escalates once to an H.264 re-encode. Files the
browser plays natively (H.264/VP8/VP9/AV1 with AAC/MP3/Opus/Vorbis/FLAC/PCM) keep the instant no-ffmpeg path.
`/api/media/convert` is gone.

**Choose the web port on a hub or relay, and let everyone find it.** The Relay page gains a "KASTR web port"
field: Set pins the port in `port.json` (applies at the next launch; Apply & relaunch moves at once and the tab
follows to the new port), Clear forgets it. Precedence: `--port` > the pinned port > a kastr.ini `port` other than 8000 > the
remembered port > 8000 (the shipped kastr.ini template says `port = 8000`, which is the default, not a pin). The hub's token service (relay port + 1) now advertises the web port on `GET /api/auth`,
so spokes store it in `relay-cluster.json` (chat forwarding, peer lookups, version follow) and pages use it for
peer lookups instead of assuming 8000.

**Source on GitHub.** The repository `OccuviteASI/KASTR` holds the source (not `dist/` or `bin/`; run
`python fetch-helpers.py` to restore the helper binaries). README.md describes the layout and the build.

## v0.13.3 — a room opens on the grid again, viewer reports stop restarting healthy cameras, two overlay fixes

**Joining a room showed one RTSP feed maximized instead of the grid.** 0.13.0 moved the grid's cell
geometry from a `.grid` announce onto the owner's `room.json` state track. The `.hang` tiles still arrive
synchronously in the announce loop, so the first `applyState` ran before the geometry and the newest
feed — a grid child, but not yet known as one — became the auto-selected "content"; when the geometry
landed, its siblings hid behind the grid, the grid parked and the child stayed maximized, self-sealed by
the content check accepting a grid child. (Re-announcing `.grid` beside the state field was tried and
dropped: the identity-scoped publisher token has no claim on `<room>/.grid`, so the relay silently discards
it -- the viewer must not trust arrival order at all.) Fixes: an automatic pick that turns out to be a grid child is handed back to the grid (`gridSelectionFix`; a
human click on a child is remembered as `manualPick` and left alone); a spotlight older than ten minutes
in `room.json` is history, not an order, and a spotlight on a grid child means the grid; and `connect()`
starts every room in the gallery with nothing carried over.

**A viewer's starvation is a symptom, not an order.** On Southridge three cameras restarted every 40–60 s,
"going around": two of them deliver no video at all, so every viewer starved on them, reported a stall,
and the box dutifully restarted a pair that cannot be helped — forever; the healthy one was restarted
whenever a viewer's own subscription blinked. The viewer-report path now restarts a native pair only with
evidence the pair itself is unwell (an exit or a severed session in the last minute, or the relay no
longer listing the path); a pair the relay lists live is left alone and the report is logged. The same
relay check is shared with the no-echo heal, which additionally stands down while moq is reconnecting
(a severed session leaves both processes alive). Every viewer-driven restart is now counted where it
belongs (`nudges.viewer`; 0.13.1 counted them as `api`), and the box's launch.log gets one line per pair
generation start and exit with the counters read BEFORE the 60-second reset that made a one-minute cadence
look healthy. `/api/rtsp/list` gains `gen`, `restartsTotal`, `lastSessionAt`; `--diagnose` finds the
instance even when port 8000 is taken (the launcher writes its bound port to `http-port` in the state
dir); camera URLs are redacted for non-loopback readers; the ladder timer is armed under the lock (a
nudge could double-restart); a relay URL with and without a trailing slash is the same relay (an adopt
used to tear every pair down once).

**Overlays.** The zoom controls (and the mic/video chips) step above a visible media bar instead of
sitting on the shared file's mute button and volume slider; the owner's media bar sits on the same row as
a remote pane's. The room-name pill no longer reserves 19 px for a hidden speaker icon.

## v0.13.2 — hotfix: RTSP cameras publish again; Enter joins

**Every native RTSP pair died at start on 0.13.1.** The `-rw_timeout` flag added to ffmpeg's RTSP
input in 0.13.1 is not an option the RTSP demuxer accepts: ffmpeg prints `Option rw_timeout not
found`, exits, and the ladder restarts it forever (`restarts: 61`, `lastExit: ffmpeg code
2880417800 after 0.5 s` on Southridge). The rig check that let it through used a refused
connection, which ffmpeg fails before it validates options — a live source rejects the flag on the
first attempt. The flag is gone; `-timeout` stays. Fields from 0.13.1's own instrumentation
(`lastExit`, `error`) named the cause from the box's `/api/rtsp/list` in one read.

**Two guards from the same investigation.** A camera box republishing its kept feeds four seconds
after its own secured relay started could get "no minter" from the token service (still binding),
treat the relay as open, dial bare and park every pair on `code=6 unauthorized`; the restore now
keeps waiting while the hosted relay reports secured, and a parked publisher that held a token
never falls back to a bare URL because the minter blinked.

**Enter joins.** On the launch gate, Enter in the access-code, room-code, new-room-name or name
field presses Join.

## v0.13.1 — a Discord-style room rail, noise removal that works, Mac + Docker, the relay-only relaunch, RTSP drop instrumentation

**The room rail is the whole picture now.** The top-bar banner names the room you are in and
nothing else (hover for the facts, click for Room info); your room sits in the LEFT rail with
the others, marked with a white pill on its left edge and a blue ring, so the rail reads like
Discord's server list. Rooms are alphabetical with `main` pinned on top, and each operator can
drag cards into their own order (mouse or pen; saved per operator name, so two people sharing a
laptop keep separate orders). The expanded pane is resizable from its right edge (180–440 px,
remembered on the machine and restored before the first paint). The 0.13.0 live thumbnails are
GONE — they were a live view of every room's video and cost every publisher uplink and every
lobby downlink; live video is for the tracks in your current room only.

**Background-noise removal is real now.** The 0.8.9 "voice isolation" was a hand-rolled gate
chain that never isolated anything, and Chrome's `voiceIsolation` constraint is listed on every
platform but only acts on a handful of ChromeOS devices. Audio settings now offers two levels of
noise suppression: "Browser built-in (light)" (the browser's own AEC/AGC/NS) and "Background
noise removal (RNNoise)" — the open-source RNNoise neural denoiser (xiph, BSD-3) running in an
AudioWorklet on your machine via the vendored `@sapphi-red/web-noise-suppressor` (MIT,
`assets/noise/`, no CDN), on top of the browser's suppression, mono at 48 kHz, ~40 ms added.
Measured on the rig: white noise at −31 dBFS comes out at −85 dBFS (−54 dB) while a voice-shaped
tone passes within 0.1 dB. If the worklet cannot start on a machine you get a toast and the mode
falls back to the browser's suppression — never a switch that looks on while nothing happens.
"Voice isolation (system)" survives only as a switch that appears when the selected microphone
actually reports the effect back; on today's Windows fleet it does not appear. The mic meter in
the Audio card shows INPUT, not the noise floor: dBFS against a tracked floor, dark until
something exceeds it, and "No input from this microphone" after three silent seconds; the test
tap opens the mic with the same constraints as the live path and, in RNNoise mode, listens after
the denoiser.

**Relay-only "Apply & relaunch" comes back on Windows.** The relaunched child booted while the
old instance still answered `/api/instance`; seeing the same build on the port it took the
hand-off branch and exited, so nothing came back (a `--no-browser` box silently moved to port
8001 instead). The child now knows it is a relaunch (`KASTR_RELAUNCH`, `KASTR_RELAUNCH_PID`),
waits up to 20 s for the predecessor to leave the port and die, never hands off, and the parent
logs `relaunching (mode)` and closes faster; `KASTR_UPDATED` is set for real updates only. The
Relay page shows "Stopping… / Starting…" and follows the new instance.

**RTSP drops: instrumentation first.** Every path that can restart a native camera pair is now
attributable: `/api/rtsp/list` (and `--diagnose <file>`) show `nudges {viewer, noEcho, api}`,
`lastNudgeWhy`, `lastNudgeAt` and `lastExit {who, code, lived}`; every nudge is logged on the
box with its reason and the pair's counters. The page's "no echo" self-heal — which could restart
a healthy publisher whenever the page's own bookkeeping lost the echo — now asks the relay's
`/announced/<room>` first and restarts only after two consecutive misses with the pair up over
60 s (lockout 120 s); a relay that lists the path is logged as bookkeeping, not a drop. ffmpeg's
RTSP input gets `-rw_timeout` beside `-timeout`, and the last 8 stderr lines are kept. When the
next drop happens: `KASTR.exe --diagnose drop.txt` on the box + `launch.log` + the viewer's page
log name the row in ARCHITECTURE's restart table.

**Mac.** `build-mac.sh` + `MACOS.md`: Apple Silicon only (moq-cli/moq-relay publish
`aarch64-apple-darwin` tarballs, pinned by sha256; no Intel builds), ffmpeg via Homebrew until a
static build is pinned in `FFMPEG_MAC`, Homebrew's bin searched by the helpers, the system Chrome
as the window. The update feed gains `darwin`: the feed serves `KASTR.app/Contents/MacOS/KASTR`
as `updates/macos/KASTR`, the client swaps the executable inside the bundle and re-signs it
ad-hoc; `build.py --publish-only` assembles the three-platform feed on the machine that has all
three trees.

**Docker.** `Dockerfile` (ubuntu:26.04 — the WSL binary is glibc 2.43 — plus the WSL-built
`dist/linux/KASTR` and the Windows/macOS feed), `docker/entrypoint.sh`, `docker-compose.yml`
(host networking, `/data` volume, `KASTR_MODE`/`KASTR_RELAY`), `docker-build.sh`, `DOCKER.md`.
The container updates itself over the internet the way the fleet does: the in-app update swaps
the binary on the volume and exits 75, the entrypoint restarts it; a newer pulled image re-seeds
the volume, an older one does not. `KASTR_STATE_DIR` and `KASTR_CONTAINER` are the two new
environment switches.

## v0.13.0 — state as tracks, identity-scoped tokens, chat and previews on the wire, and eight field fixes

**Room state rides JSON tracks now, not announce paths.** Since 0.7 every non-media fact
(presence, speaking, spotlight, recording, stall reports, shared files, avatars, grid
geometry, media control, the chat pulse) was a track-less announce whose PATH carried a
base64 payload, re-dialled on every change. A page now publishes two small broadcasts:
`.state/<room>/<HOST>/<PEER>` (public prefix: `state.json` — who I am, my join time, what
I publish, speaking, typing, my picture — plus a `preview` track) and
`<room>/<HOST>/.member/<PEER>` (behind the room token: `room.json` — spotlight,
recording, stall reports, control pulses, grid geometry, media state, shared files — and
`chat.json`). Values are whole snapshots written with `@moq/json`, so a late joiner reads
the latest state on arrival instead of reconstructing it from announce churn; a change is a
new group on an open connection, not a new dial. Only the room registry (`.channels`) stays
an announce — its lifetime is deliberately decoupled from any member. Step-0 findings that
shaped it (ARCHITECTURE ledger): the producer prunes closed groups after `latencyMax`
(5 s default) so state tracks keep 60 s and a 20 s heartbeat rewrites them; a live
subscriber is not moved onto a resumed broadcast, so consumers re-consume on error or
after 2.5 silent heartbeats; group sequences are seeded from the wall clock so a resumed
broadcast never regresses below what subscribers already saw (which silently drops values
until the heartbeat catches up — the bug the rig found first); the relay serves a cached
group first and then the live one, so every value is applied in order.

**Tokens are scoped to the machine that asked for them.** `/api/token` takes the page's
`host` slug (hostname + MAC hex) and mints `put` claims under it: a publisher gets
`<room>/<HOST>`, `.state/<room>/<HOST>` (+ the one-release compat kinds `<room>/.since`,
`.presence/<room>`); a viewer gets `.state/<room>/<HOST>`, `<room>/<HOST>/.member` and the
same two compat kinds — narrower than the publisher's, so a viewer token still cannot touch
media. The relay drops anything outside those prefixes, so no member can overwrite
another's state by accident, and a leaked viewer token writes four narrow prefixes instead
of a room-wide list. The relay's public list gains `.state`; `/api/auth` says `state:
true`; a token minted before the relay grew state tracks is re-minted. Native RTSP
publishers mint with the same host. A page without a usable host slug gets the 0.12-shaped
wide token; a 0.13 page on a 0.12 relay behaves exactly as 0.12.

**Chat is delivered live over the relay; history stays on the hub.** Each member's
`chat.json` is a 50-record window: a post goes to the hub's store (4 s budget) and then
onto the window with the store's id; when the store does not answer (Agg's KASTR web port
was unreachable from the field while the relay port was fine — "Chat doesn't appear to be
working") the message still goes out live, marked "not saved", and the hint names the
host:port that failed instead of "Failed to fetch". Local (unsaved) ids never move the
history cursor; deletes ride as tombstones; "<name> is typing…" shows while someone types.
The 0.12 `.chat` pulse and polling stay for 0.12 members. A laptop's own KASTR is used
for history only when `/api/instance` says `chatHub: true` (it is the hub or forwards to
one) — never a private empty store.

**Previews.** A publishing page writes a 224 px WebP frame every 2 s (grid canvas, else the
first slot) to its `preview` track — on the public broadcast for an open room, behind the
token for a locked one. The sidebar shows it on the room card and as the collapsed bubble's
picture; subscriptions exist only for the first eight visible cards and stop when the page
is hidden.

**Field items (Kenton, 2026-09-21).** Idle publisher/relay boxes measured: an idle native
publisher into a spoke pulls 0 bytes through the cluster link (the relay subscribes
upstream on demand and cancels when the last reader leaves); the remaining suspect was a
viewer somewhere, so: own panes and Share rows show "N pulling" from the relay's `.stats`
(`subscriptions − subscriptions_closed`), `/api/instance` reports `viewing {n, ageS}` from
the pages' diag snapshots (`null` when no page reports — never a false 0; the Relay page and
`--diagnose` show it), a publisher-mode page never creates viewer tiles, and a tab hidden
for 60 s drops every non-selected tile's subscription (warm audio kept them alive with
`visible=never`) and re-arms them when shown. The left sidebar defaults to collapsed and
the choice persists (set before the module graph loads, so no flash). Opening one feed
from an RTSP grid parks the grid tile (`visible=never`, no pane in the rail, canvas
detached) so only the chosen feed downloads; Gallery/back restores it. People sharing
content are listed first in the rail (screen/file/RTSP/grid, then their cameras, then the
rest) while the collage order is unchanged. The launch gate has a Relay field with the
last five relays (hidden in viewer mode and off-loopback; a refused switch is a toast, not
silence; the access-code row and stale rooms clear on a switch). The Relay Server tab moved
into the Relay ▾ popover ("Relay server settings…", hidden in viewer and publisher modes)
and opens as a tab with a ✕ that disappears when closed.

**Kept for one release, removed in 0.14:** the `.since`/`.presence` compat announces, the
`.talking`/`.chat` publics, the no-host minter branch, the announce parsers.

## v0.12.0 — cameras that heal, a rooms sidebar with a banner for yours, speaking before you join, room chat with attachments, persistent rooms, four machine modes, occupancy timers on every room

**Cameras heal themselves — why the RTSP boxes went dark.** A native camera feed is
`ffmpeg | moq` with the relay URL and its token baked into the command line. When
the relay's signing key rotated (or the codes changed), the relay severed every
session ~30 s later; moq retried the same dead token, gave up after 10 s
("reconnect timed out … unauthorized") and exited; KASTR's retry ladder restarted the
pair with the SAME stale token, forever — `restarts` climbing while nothing reached
the relay. Nothing re-minted, because 0.11.0 stopped auto-joining and an unattended
box had no page joined. Now: moq runs at `--log-level warn` (where the reconnect
lines live), a classifier tags a hard refusal (`unauthorized`, `code=6`, expired /
invalid token), and a refused publisher PARKS instead of hammering the camera — it
asks the minter for a fresh token (once a minute, from the session the page saved),
and restarts the moment one arrives (from the minter or from a page re-posting with
its fresh token). A plain relay outage still walks the ladder. `--backoff-timeout 10s`
and `--client-quic-idle-timeout 15s` are explicit (a dead relay is noticed in 15 s
instead of 30). The reuse path is evidence-gated: a page reload or rejoin mints a
new token but never restarts a healthy pair (the 0.9.8 promise); it restarts only a
pair that is parked, recently refused, or whose token is about to expire.

**Feeds and the session are remembered on the machine.** `rtsp-feeds.json` in the
state dir holds the room, the codes, the relay and every kept feed (written on
operator intents — publish, unpublish, remove, Keep — never on shutdown). At launch
the launcher waits for the relay, mints a member token (or dials an open relay bare)
and republishes the kept feeds with no page open; a refused code is logged and left
for a hand. The gate says "N camera feeds are on air from this machine in room X".
`GET /api/rtsp/persist` never returns the codes.

**Rooms are a subscription, not a scan — why rooms vanished for 15 s.** The 0.11
room list opened a fresh connection every 10 s and armed a 1.5 s deadline before the
dial; on a WAN relay the handshake plus the first announce batch often lost that
race, the scan returned `[main]` and the list collapsed until the next scan. One
anonymous connection now lives for the page's life with permanent consumers on the
public prefixes (`.presence`, `.channels`, `.talking`, and everything on an open
relay). Entries age out 8 s after they go inactive, never while the connection is
down (the list dims instead), and a reconnect re-stamps the grace so the relay's
replay wins before anything is pruned. The relay host's room store is polled every
30 s (last good answer kept), so a kept-but-empty room never blinks.

**A Discord-style sidebar; the current room is a banner.** The ☰ expands and
collapses a left sidebar listing every room but yours (all rooms at the gate): an
initials bubble, the name, a lock, "kept", the people count, an occupancy timer
(`h:mm:ss`, starting when the first member arrives and running while anyone is in —
`main` included), a speaking icon when anyone in there talks, and the members (▲
publisher / ○ viewer, each with its own speaking icon). Collapsed, the cards become
the 0.11 bubble rail; on phones the sidebar is a drawer. Click a room to switch (a
locked one asks for its code inline; at the gate a click preselects it). "Create
room" lives at the bottom with a Keep-this-room box. Your own room moved out of the
list into a top-bar banner: `main · 2 people · ⏱ 0:12:03 · 🔒 · kept · publisher`
(click = Room info). The chip and the bubbles of 0.11 are gone.

**Speaking shows before you join.** A page whose mic is loud for two 250 ms ticks
announces `.talking/<room>/<ts>/<b64 {peer}>` on one persistent connection (toggled
with the broadcast's own `enabled`), and drops it after 2 s of quiet; muted mics never
announce. Others resolve the peer through presence, so nobody can light another
operator's icon. Relays 0.12.0 publish `.talking` in their public list; older secured
relays simply show no icon.

**Room chat.** A Chat button opens a panel docked right (a bottom sheet on phones):
text, emoji (a curated grid plus your system keyboard), pictures inline and files as
rows, Enter sends, Shift+Enter a new line, drag-drop and paste attach. History is a
JSONL file on the relay host's KASTR (`state_dir/chat/<room>.jsonl`, attachments beside
the shared files); a spoke's KASTR proxies to the HUB's, so a federation shares one
history per room name — including `main`. Delivery is a pulse: the poster announces
`.chat/<room>` for 2.5 s and everyone fetches "since my last id"; polls back it up (10 s
open, 60 s closed). Unread badge on the button; "seen" means the panel was open while
the page was visible. Delete your own messages with ✕. Viewers chat too (a member
token's `get` covers the room). A secured relay requires the room token; an open
relay trusts the LAN like shared files.

**Persistent rooms.** A room can be kept (gate "New room…" → Keep this room; the
sidebar's Create form; publisher access code required when the relay has codes). Kept
rooms survive everyone leaving and relay restarts, keep their chat, are listed with
"kept", and are closed by their creator (Room info → Close room…) or the relay
operator (Relay page → Rooms table). Closing deletes the record, the chat and its
attachments and leaves a one-hour tombstone; members learn from the STORE (an
announce only hints) and go back to the lobby — except publisher-mode boxes, which
lose chat and keep publishing. Temporary rooms behave as before.

**Four machine modes.** `kastr.ini` `mode = viewer | publisher | relay |
publisher-relay` (absent = the full client, unchanged), also `--mode`, chosen on the
Relay page (5-way select + Apply & relaunch). Viewer: no Share, camera or mic controls,
no relay address (the "Relay ▾" badge keeps its health light), "Join a room". Publisher:
Publish-only forced, AUTO-JOINS its last room at launch (video on by default; a failed
attempt retries 10 → 60 s, a wrong code waits for a hand) — the exception to 0.11's
no-auto-rejoin rule, because an unattended camera box relaunched by the fleet must
publish with nobody at the keyboard. Relay: boots to the Relay page as before.
Publisher + relay: both. The app shell hides the Relay tab in viewer and publisher
modes; the masthead badge is "Relay ▾" in every mode, with the address inside.

**Also.** `[cluster] linger = "20s"` on federated relays; the Relay page's `@moq/watch`
import is vendored (no esm.sh at run time); a Rooms table on the Relay page; presence
keeps its original join time across re-dials (a solo box's timer no longer resets);
`GET /api/relay/rooms`, `POST /api/relay/rooms/close` (loopback), `GET /api/rooms/list`,
`POST /api/rooms/register`, `POST /api/rooms/close`, `GET|POST /api/chat/<room>`,
`DELETE /api/chat/<room>/<id>`, `POST /api/chat/<room>/files`, `GET /api/chat/<room>/files/<id>`,
`GET|POST /api/rtsp/persist`, `POST /api/rtsp/keep`; `/api/mode` → `{mode, relay, running}`;
`/api/instance.mode`; `/api/auth` gains `talking` and `chat`.

**Deploy order.** The hub (Agg) first — chat lives there — then Mendon, then the fleet.
Set `mode = publisher` on the RTSP boxes so they auto-join and republish.

## v0.11.0 — rooms as bubbles, federation with a code and one update master, an honest "via", room codes back at the gate, no auto-rejoin, relay 0.14.18

**Rooms as bubbles.** Next to the room chip, every room in use on the relay is a
circle: the room's initials, a people count, a lock glyph on locked rooms, a ring on
the one you are in — always visible, like Discord's server list. Click a bubble to
switch (a locked room asks for its code); more than eight rooms fold into "+n". The
☰ keeps the detailed list, now with who is in each room. The chip itself just names
your room again (0.10.0 had made it a second copy of the ☰ menu). Counts work on
secured relays too: every member announces a copy of its presence under a public
`.presence/<room>` prefix, so the list counts people without a token.

**Federation with a code — and why Mendon ↔ Agg broke.** Both relays now require
access codes, and a relay that requires codes refuses every session without a
token, including the other relay's cluster link, which never carried one. A hub now
holds a third relay-wide code, the **federation code** (Access codes block on its
Relay page). A spoke saves the hub URL and that code (Federation panel); at every
relay start it asks the hub's minter for a 30-day relay-to-relay token and dials
with it (`connect = ["https://hub:4443/?jwt=…"]`, the relay's documented form). A
watchdog re-mints and restarts the spoke's relay when the hub rotates its key or
fewer than 7 days remain. A wrong code shows as "hub refused the federation code"
on the spoke's Relay page and as a refusal in the hub's log. Verified with two
relays on one machine: streams both ways, denial on a wrong code, recovery after a
key rotation. Open hubs keep working untokened.

**Federation master = one update point.** A spoke's KASTR now pulls its own
updates from the hub's KASTR — at launch and every hour it matches the hub's version
(up or down), the way clients match their relay host at launch. Relay-host machines
never updated themselves before: their relay is on their own machine, so there was
nobody to ask. Untick "Pull KASTR updates from the hub" to opt out. A relay-only box
relaunching on a version change restarts its relay for about 15 s.

**"via" names the relay a person dialled.** Presence now carries the relay a member
connected to (and its name when that relay's KASTR answers), and People and tile
hints use that first. The old guess read each relay's stats table and took the
first node listing the stream — in a cluster every node lists every forwarded
stream, so it named whichever relay answered first. The Relay page's streams panel
now says "announced into <node>", which is what that table measures.

**Room codes back at the gate.** Rooms persist on the relay since 0.10.0, so an
empty locked room was invisible at the gate: re-creating it via "New room…" with a
new code hit the stored one ("wrong room code"), and locking a new room needed the
publisher code, whose refusal was only logged (the room came up unlocked). The gate
now lists the relay's remembered rooms as locked so their code can be entered; a
locked room is registered before the join so a refusal is shown ("Only the
publisher access code can lock a room." / "That room already exists and is
locked…"); and a publisher re-keys a room by creating it again with the publisher
access code. Pages older than 0.10.0 talking to an older minter get their room code
in the field that minter reads.

**No auto-rejoin at launch.** Launch lands on the Join screen with your last room
preselected and its codes prefilled; you press Join. A reload inside the same
window still rejoins silently.

**Toolchain.** moq-relay 0.14.12 → 0.14.18 (credentials are no longer logged in
relay URLs — relevant now that the federation token rides the cluster URL;
WebSocket sessions end with their credential; moqt-20/21; rustls patch) and the moq
CLI → 0.11.2. The web library stays at @moq/watch 0.5.3 / @moq/publish 0.4.6
(0.5.4 / 0.4.7 exist; not re-vendored in this release).

**Deploy order.** Agg (the hub) first, then set its federation code in the Access
codes block. Then Mendon with Agg's URL, that code and "Pull KASTR updates from the
hub" ticked; Mendon's KASTR then follows Agg's version by itself. The fleet keeps
updating from its relay hosts.

## v0.10.0 — a relay on a public IP admits only code holders; the room chip switches rooms; the Relay page tells the truth about binding

**Access codes (why this is 0.10).** "Require room codes" did start moq-relay
with JWT auth, but as access control it leaked: the minter checked a code only
for a room somebody had registered in an in-memory table (emptied at every relay
restart), `main` could never be registered, so tokens for main and for any
unregistered room minted for free; one code granted publishing and watching
alike; the minter had no rate limit; and the relay's control API answered any
machine. A secured relay now carries two relay-wide **access codes**, set on the
Relay page: a **viewer code** (watch) and a **publisher code** (watch, publish,
create rooms). With codes set, every room including main refuses to mint without
one — the code decides the role, the room decides the paths. A viewer token can
subscribe and announce its presence, stall reports, spotlight votes, recording
notice, media controls and avatar, but carries no publish claim on media; the
relay drops such an announce and keeps the session (verified against the bundled
binaries). Room codes remain an extra per-room lock, and creating a locked room
needs the publisher code. Codes are stored hashed (PBKDF2-SHA256) beside the room
records in `relay-auth.json`, so a relay restart forgets nothing. Five wrong codes
in a minute lock that client out for 30 s, doubling to 10 minutes; refusals and
lockouts are logged. The relay control plane (start, stop, repoint, federation,
name, autostart, firewall, codes, key rotation) answers only the machine that
hosts the relay. A relay secured *without* codes keeps working as before and says
so in red on the Relay page. **Rotate keys** invalidates every outstanding token
at once; pages re-mint with their codes within a minute and publishers reconnect.

**At the gate.** A relay with access codes asks for one — viewer or publisher —
above the room code. Wrong codes say which one was wrong; too many attempts say
how long to wait. The codes ride the rejoin ticket and the last-room memory, so a
restart rejoins silently. A viewer code joins as a viewer: Go live is disabled
with the reason, feeds are not published, the Share panel says so.

**The room chip is the switcher.** Click **Room: main · 3 ▾** in the top bar for
the rooms in use on this relay — a header names the relay; each row shows the
people count (now including members who publish nothing), up-time, a lock glyph,
✓ on the current room; "Create new room…" is at the bottom; the list refreshes
every 5 s while open. Clicking a room switches in place (your shares republish
under the new room), and a switch is remembered like a join. The ☰ still opens
the same menu.

**The bind-all box tells the truth.** "Allow other machines to connect" — and the
port and secured boxes — now show the shape the relay actually runs with, or the
remembered one while it is stopped. They used to stay unticked whatever the relay
did, so a Stop/Start from the page silently dropped a LAN relay to loopback and
the autostart box re-saved "lan: false" from an always-empty checkbox. Starting
the relay also remembers its shape. The printed firewall hint lists all six rules
the button creates (it stopped at four). `[::]` accepts IPv4 on this Windows build
(probed), so the bind is unchanged.

**Not combined yet:** federation with access codes — a clustered relay still
carries no token relay-to-relay.

**Upgrade order.** Deploy 0.10.0 to Mendon (the fleet authority) first, let the
fleet update, then set both codes on the public relay's Relay page. Pages older
than 0.10.0 send only a room code, which a relay with access codes accepts only
when it is that room's own code.

## v0.9.10 — cells keep their places through a restart, audio off until you turn it on, older leftovers swept, publish-only devices

**Cell lock, for real.** The lock flag itself always survived a restart; its
*effect* did not. The remembered cell order was rewritten on every grid pass with
only the cameras present at that instant, so a restore that brings cameras up one
by one erased the others' positions and put late arrivals last; and a seat (what
lets a camera that is still connecting hold a placeholder cell) lived only in
memory and was wiped whenever fewer than two feeds were up — the first second of
every restore. Now the order is **merged** into what is remembered (cameras that
are not up keep their slots; a drag-swap still moves cameras), and seats persist
(`kastr.grid.seats`): a restored camera holds its remembered cell, marked
"connecting…", from the moment it is re-added. Only an explicit switch to
*Separate feeds* or removing a feed gives a seat up.

**Audio is off by default.** A camera's audio is published only when you turn it
on — the box at the top of the Share panel (now unticked and remembered) for new
feeds, the per-row Audio box for existing ones. The per-feed choice stores both
states now, so an explicit "on" survives restarts and re-adds too.

**Leftovers from older versions are swept.** 0.9.8 made children die with KASTR
and reaped the ones a *0.9.8-or-later* run recorded. Publisher pairs left by an
older version (no Job Object, no registry), and any orphaned monitor, probe or
`moq-relay`, were invisible to it. The most likely reading of South Ridge's five
cameras arriving twice (grid plus separate, hitching) after their KASTR restarted
is exactly that: the previous instance's `ffmpeg | moq` pairs kept publishing the
same paths while the new one published them again — two publishers per path and
double the encodes on that box, until stop-and-reshare let the old pairs die. KASTR
now also sweeps by what a helper **is**: at start it lists `ffmpeg`/`moq`/
`moq-relay` processes running from a bundled-helper location (`_MEI…\bin` or this
install's `bin`) whose parent is no longer a live KASTR (or Python) process, and
ends them. A second live KASTR keeps its helpers. Logged as "swept N helper
process(es) left by earlier KASTR runs"; `/api/instance` reports `swept`;
`--diagnose` lists the registry and what the sweep would reap.

**Publish only.** View ▸ *Publish only* makes this device publish without
watching: no tiles, no subscriptions, no decoders, no meters for other people's
streams. Your own camera, feeds and the grid still show and publish; People keeps
its counts (from the room's presence announces), and the owner-side stall nudges
still arrive. Remembered per device; a badge on the View button and a note on the
stage say it is on. Trade-off: with nothing subscribed, other members read as
"watching" in People.

## v0.9.9 — a corrected picture fills the stage without a zoom

Hotfix on 0.9.8's shape correction. Kenton, viewing South Ridge: "not squished
any more, but smaller and not filling the space; zooming fixes it." His viewer
diagnostics (`state().shapes`) showed the cause: two of South Ridge's 4K cameras
are announced by the publisher's `moq import` with a **square** display size
(3840×3840) while the decoder produces 3840×2160 -- a wrong catalog size, not a
pixel-aspect problem -- so the 0.9.8 correction engaged (factor 1.78) and removed
the squeeze. But its transform was computed once, against the pane's shape at
that moment, and only a zoom recomputed it; the pane was reshaped to 16:9 a
moment later and the picture stayed drawn for the old square box.

The correction now follows its box: `fitMainstage` re-applies the transform of
a zoomed or corrected canvas after sizing the pane, `viewApplyAll`/`viewPrune`
and the window-resize handler cover corrected canvases as well as zoomed ones,
and the 1 Hz probe reshapes the pane before drawing for it.

Also in this hotfix: **adoption is limited to the page on the machine itself.**
0.9.8's "adopt what the server runs" ran on every page a KASTR serves, so a
phone or LAN viewer opening the operator's HTTPS page would have listed the
operator's cameras as its own shares and hidden their tiles (found in the rig,
where a second local page did exactly that). Same loopback rule as the server's
publish endpoint. And the shape probe now judges only full-size frames (a rail
tile decoding a 640×352 low rendition of a 1280×720 catalog differs by
coding-size rounding, not shape -- it was being nudged 2 %) with a 3 %
tolerance. Both platforms are rebuilt.

## v0.9.8 — camera publishers live and die with KASTR, and come back as yours

**Restart: your cameras are yours again.** A KASTR that was killed hard (Task
Manager, a crash, the old close script) left its `ffmpeg | moq` publisher pairs
running: the cameras stayed on the relay under your name while the next KASTR
saw them as a stranger's tiles -- no grid, no Share row, no Stop, and re-adding
a camera published to the same path twice. Three layers fix it:

- **Children die with the app.** On Windows every ffmpeg/moq child -- and the bundled
  moq-relay -- joins a Job Object that the OS tears down with the KASTR process,
  however it ends (an orphaned relay used to keep port 4443 and the next start
  failed with "address in use"). On both
  platforms every child is recorded in `rtsp-children-<pid>.json` in the state
  folder, and the next start reaps the recorded processes of a dead KASTR
  (matched by executable and start time, so a reused PID is never someone
  else's process). `--diagnose` lists the registry.
- **A fresh page adopts what the server runs.** After a reload or a closed
  window the bridge still publishes; the page now lists those feeds as its own
  (same feed, same broadcast name, same audio flag), seats them in the grid and
  shows them in the Share tab. The server keeps the running pair when the
  publish request matches (idempotent publish), so nothing drops. "Reconnected
  N camera feeds already running on this machine."
- **Keep after restart is the default.** The box is on for new feeds and
  remembers its last state; a feed's own "Keep after restart" menu item still
  turns it off. Feeds now legitimately come back after a restart -- through the
  page, in the grid, stoppable.
- `POST /api/quit` ends KASTR cleanly from a local tool; `close-kastr.ps1` asks
  that way first and only then kills and sweeps (`moq.exe` and the frozen
  build's `_MEI…\bin` helpers included -- the old sweep matched neither).

**Audio is controllable where the shares are listed.** Every RTSP row on the
Share tab has an **Audio** box (the pane menu's "Send audio" stays; the box at
the top of the panel is the default for new feeds). In Grid-only mode the box
is disabled with a hint -- that mode publishes the mosaic without audio. The box
reads "applying…" until the server confirms. Renaming a native feed republishes
it under the new name (it was a silent no-op).

**The spotlight shows the picture's true shape.** A camera with non-square
pixels (an anamorphic H.264 stream, SAR ≠ 1:1) is never passed through: the
catalog viewers size their picture from carries the coded frame, so a copied
anamorphic stream showed squeezed on every viewer. The probe reads the SAR,
such a camera is converted once, and every encode path now starts by
resampling to square pixels at the display width (`scale=iw*sar:ih,setsar=1`). Viewers also compare the decoded frame's own shape with
the bitmap the catalog sized and correct a mismatch on the fly (`state().
shapes` shows the numbers); a zoomed mosaic cell now shapes the stage to the
cell instead of the whole mosaic. Reproduced in the rig with a 960×1080 SAR 2:1
file: passed through by a pre-fix publisher it arrives as a 960×1080 bitmap
(the decoder reports the same, so a viewer alone cannot tell -- the fix has to
be on the publishing side); converted by 0.9.8 it arrives 1920×1080. (A plain
`setsar=1` was tried first and merely relabelled the squeeze -- the pixels have
to be resampled.) Until the
owning KASTR runs 0.9.8, its anamorphic cameras still look squeezed to everyone.

**Fill-first auto grid.** Rows may hold different cell counts when that draws
more picture: five cameras are two large over three smaller (17 % black instead
of 44 %), three are two over one, six are three over three, ten are 3+3+4. No
cell is smaller than half the biggest, nothing is cropped, partial rows and the
whole block are centred. Drag-swap decides which cameras take the big cells.
Both ends must run 0.9.8 for a viewer's cell click to land on the right camera.

**Housekeeping.** The repo moved out of OneDrive to `C:\Users\KentonJeffery\
Claude\KASTR` (no more clobbered binaries mid-build). `dist/archive` holds one
folder per version with one zip per platform (`v0.9.8/KASTR-windows-v0.9.8.zip`,
`KASTR-linux-v0.9.8.zip`); only the version just built is kept.

Files: `kastr_rtsp.py` (job object, child registry + sweep, idempotent
`Bridge.publish`, SAR probe + `setsar=1`), `kastr_serve.py` (`/api/quit`,
`make_bridge(state_dir, log)`), `kastr.py`, `kastr-serve.py`, `close-kastr.ps1`,
`moq-watch-lite.html` (autoRows, aspect correction, Audio box, adoption, keep
default), `build.py` (archive layout).

## v0.9.7

- **Grid cells stop dropping out.** With four real cameras on passthrough the
  published feeds were rock solid (no restarts), but the owner's preview
  players behind the grid cells were being reconnected about once a minute
  each, and while reconnecting the cell showed "reconnecting…" -- that was the
  "random drops across all my cameras". The preview is now a Media Source
  player the page drives itself: it jumps over timestamp gaps, stays at the
  live edge by seeking inside its own buffer instead of speeding up or
  reconnecting, trims old data, and only reconnects when the camera stream
  really stops delivering. A brief reconnect keeps the last frame in the cell
  instead of flashing a placeholder. The bridge now tells the player which
  codec it is sending, so H.265 passthrough previews open correctly; a preview
  that cannot play at all falls back to a cheap H.264 encode as before.
- **The name strip on grid cells is gone.** It covered the cameras' own
  on-screen information bar. Names remain in the feed menus and on viewers'
  cell labels.

## v0.9.6

- **Fewer encodes per camera -- the fix for feeds dropping out with three or
  more streams.** KASTR's server is threaded and ffmpeg uses every core it is
  given; what starved the small boxes was the *number* of encodes: every
  camera that was not plain H.264 cost two full re-encodes (one for the
  published feed, one for the owner's preview and the grid) plus the relay
  sender. Now:
  - *Pass cameras through untouched* (Share ▸ RTSP) applies to every codec
    viewers can decode -- H.264 and H.265 today, including 4K and full-range
    H.264 that used to be converted -- so a camera costs zero encodes. Cameras
    nobody can decode as-is (MJPEG, MPEG-4) are still converted to H.264, once.
    The old "H.265 only" setting carries over.
  - The preview/grid stream follows the same rule (copied when it can be), and
    when it must be encoded it is now small and fast: 15 frames a second, at
    most 1280 wide, fastest preset -- a fraction of the old cost. If a copied
    stream turns out not to play in the window (H.265 on a machine without
    hardware decode) the preview falls back to a cheap H.264 encode by itself.
  - Linux machines with an Intel or AMD GPU get hardware encoding (VA-API)
    when a conversion is still needed.
- **Adding a camera twice is caught.** Adding an address that is already
  shared asks whether to replace the existing feed; the default keeps things as
  they are. (Two copies of one camera meant two publishers and two previews.)

## v0.9.5

- **The grid is live again.** The mosaic is drawn from each feed's local monitor
  picture, and since native publishing (0.9.1) nothing watched over those
  monitors: one that stalled or fell behind froze or delayed the grid for every
  viewer while the cameras themselves (published by the server) stayed live --
  the "grid isn't updating, the camera I open from it shows something
  different" report. The monitors now keep playing, catch up when they fall
  behind live, and reconnect when they freeze; a reconnecting cell says so
  instead of showing a stale frame. On the viewing side a picture that stops
  moving while data still arrives is now treated as a stall and re-subscribed.
- **Clicking a camera in your own grid opens that camera.** On the stage, a
  cell click now brings up the feed itself, full resolution, in place of the
  grid (click it again, or the "Grid" button, to return); the mosaic drops to
  the rail meanwhile. Wheel and double-click still zoom the mosaic.
- **Per-feed audio.** Each RTSP feed's menu has "Send audio: on/off" (and says
  when the camera has no audio track); the Share panel's "Send the camera's
  audio" sets the default for a feed you add. Off publishes video only. The
  choice is remembered per camera address.
- **Muting a grid mutes its feeds.** On viewers, the grid tile's mute and volume
  now govern the full-quality feeds heard behind it, and the grid tile keeps its
  audio controls whenever its feeds carry audio (they were hidden because the
  mosaic itself is silent, which is why muting it did nothing).

## v0.9.4

- **A camera that drops no longer rearranges anyone's stage.** When an RTSP
  feed in a grid disconnected, every viewer briefly saw that feed pop out of
  the grid as its own tile, the layout reflow around it, sometimes the stage
  jump to it, and then everything snap back when it reconnected. Three causes,
  all fixed:
  - Viewers now *remember* which feeds belong to a grid. A reconnecting member,
    or a grid announce that flickers, no longer un-hides the feed's tile; the
    tile only shows on its own when the grid is really gone (Separate feeds, or
    the grid removed).
  - The grid's geometry announce is only re-sent when it actually changes, and
    it lists a reconnecting member's path just like a live one.
  - A dropped camera no longer restarts its publisher from the page. The local
    monitor picture reconnects on its own ladder (now also when the camera is
    unreachable, which used to leave the monitor dead), the server keeps
    publishing the feed with its own retries, and the grid cell says
    "reconnecting… (attempt N)" instead of freezing on the last frame.
- Smaller fixes on the way: a full-quality feed that leaves the stage hands it
  back to its grid at that cell instead of promoting a sibling feed; the grid
  announce follows a relay change; a browser encoder failure no longer restarts
  RTSP feeds (they never used it); the feed's status line shows the publisher's
  last error while it is down.

## v0.9.3

- **Linux: the window opens in KASTR's own browser again.** The 0.9.x release
  zip stored the bundled browser's executables without execute permission, so
  on Linux `browser/chrome` could not start; KASTR then handed the URL to the
  system default browser (Firefox, which cannot run it) and showed the "close
  this message to stop" dialog. The archive now marks those files executable,
  KASTR restores the permissions itself on every launch, and the hand-off to
  the default browser is gone. If the bundled browser still cannot start, KASTR
  retries without Chrome's sandbox (Ubuntu 23.10+ blocks it for unpackaged
  programs), then tries a system Chrome/Chromium/Edge, and only then shows a
  dialog that says *why* -- with the browser's own last line -- and the address
  to open by hand.
- **Smaller.** The bundled Chrome is pruned to what a KASTR window uses (all
  locales but en-US, the installer/updater helpers, Widevine, DirectX shader
  compiler, hyphenation data: about 90 MB per Windows install, 70 MB on Linux;
  existing installs prune themselves on the next launch). The YouTube/video-page
  resolver (yt-dlp, about 5 MB of the binary plus sqlite3) is gone -- RTSP
  cameras, direct media URLs and HLS/DASH manifests still work; a video page
  is refused with a clear message. The browser-side RTSP publish path
  (captureStream -> WebCodecs), the corner tile-resize grip, the hidden
  Relay/Audio/Order controls, the MKV codec sniffer and other dead code left
  the page (about 440 lines); the unused upstream demo pages, the old Vite
  bundles, the non-SIMD MediaPipe engine, and 35 `.bak` files left the tree.
- **RTSP grid "One big + strip" without the black bars.** The strip is now a
  column on the left with true 16:9 cells, the big feed fills the rest at
  16:9, and the mosaic canvas takes the shape that needs no letterboxing
  (three feeds: 1920x720; four: 1706x720). Two feeds fall back to side by side.

## v0.9.2

- **The "Chrome for Testing is only for automated testing" bar is gone.** The
  bundled browser is started the way Chromium's own test harness starts it,
  which suppresses that infobar (and the unsupported-flags warning).
- **The RTSP feeds mode is always reachable.** *Grid + full-quality feeds*,
  *Grid only*, *Separate feeds* and *Lock cells* now live in **View ▸ RTSP
  feeds** and in every feed's ▾ menu, not only on the mosaic's menu (which does
  not exist while feeds are separate -- that was the "I lost the grid"). A hint
  appears when two or more feeds are set to Separate.
- **Zoom on your own feeds and files.** The stage zoom (wheel about the cursor,
  drag to pan, double-click, − / % / +) works on your own RTSP feed and shared
  file panes when they hold the stage, not only on the mosaic and remote tiles.
- **Optional H.265 pass-through.** Share ▸ RTSP: "Pass H.265 cameras through
  untouched". Off by default. A camera that already emits H.265 is then
  published as-is (roughly 30-50% less bandwidth than H.264, zero encode cost);
  everything else is still converted to H.264. Viewers need hardware HEVC
  decode; a viewer that cannot decode a stream sees "H.265 -- this viewer
  cannot decode it" on that tile instead of a black picture, and still hears it.

## v0.9.1

- **RTSP feeds are published natively -- no second encode, no window
  required.** Until now every camera was decoded and re-encoded inside the
  KASTR window before it reached the relay. KASTR now bundles `moq-cli` (the
  relay project's own publisher) and each feed goes ffmpeg -> moq -> relay
  directly: an H.264 camera is copied untouched (full quality, zero encode
  cost), anything else is encoded once by ffmpeg (hardware when available),
  and camera audio is carried for the first time. The page only monitors the
  feed; a viewer's "frozen" report restarts the pair server-side; a feed that
  dies is retried on the usual ladder. Grid modes work as before: the mosaic
  is still composed in the window, and in *Grid + full-quality feeds* the
  members publish natively. Machines without `moq-cli` fall back to the old
  browser path automatically.
- Why not MediaMTX: it is a protocol router, not an encoder, and its MoQ is
  the IETF draft dialect -- not compatible with KASTR's relay and web library.

## v0.9.0

- **KASTR is self-contained: it ships its own browser.** The app window runs
  in a pinned Google *Chrome for Testing* build (153.0.8010.36) that lives in
  the `browser/` folder next to KASTR, with its own profile. KASTR no longer
  depends on whatever Chrome or Edge a machine has, on that browser
  auto-updating underneath it, or on a stray Chrome window holding the profile
  after a crash. The first launch carries your saved name, rooms and settings
  over from the old profile; the camera and microphone permission is asked
  once again (it belongs to the browser profile).
  On Windows the launcher grants the bundled browser the sandbox file
  permissions Chrome's installer would have set (a bare copy lacks them and
  Chrome then opens a window that never loads).
- **The browser follows the fleet.** Like the binary, the browser folder is
  matched to the relay host's KASTR at launch (`/api/update/browser`), so a
  re-pinned browser reaches every machine; a missing or damaged folder is
  fetched the same way. `kastr.ini`: `browser = bundled` (default), `system`,
  or a path.
- Linux: `install.sh` checks the bundled browser's shared libraries and prints
  the apt line when something is missing. Relay-only boxes never start it.
- Release archives grow by the browser (~150 MB compressed per platform); the
  fleet-feed zips stay out of the archive (`updates/browser/`).

## v0.8.13

- **KASTR no longer loads its media library from the internet.** Until now the
  page imported the MoQ library from esm.sh at every launch, unpinned. On 9 Sept
  a new upstream release appeared and esm.sh could not serve it, so every
  installed KASTR opened to an empty Join box with no rooms. The library
  (`@moq/watch` 0.5.3, `@moq/publish` 0.4.6 -- the versions KASTR was tested
  with) now ships inside the app, pinned. If a module ever fails to start, the
  gate says so and offers Retry instead of sitting there blank.
- **Shared media files: everyone sees the video.** The file player captured its
  canvas at "0 fps", which the encoder turned into a frame rate of 0; hardware
  encoders refused it, so the room heard the file and saw black while the
  sharer's own preview looked fine. The player now captures at 30 fps.
- **Media files start at once after converting.** The converted file used to be
  downloaded whole into the page before playback; it now streams from the local
  server (with seeking) and is freed when the source is removed or after 12 h.
- **Clicking another grid while your own grid is on stage** brings it to the
  stage; it used to zoom inside the rail tile.
- **The launcher explains itself.** A `launch.log` in the KASTR state folder
  records every startup decision (the app has no console); a launch whose window
  never appears now shows a dialog with the address instead of exiting silently;
  a double-click while KASTR is already running verifies that the existing
  window answered; a post-update relaunch no longer closes its own new window;
  a stalled update download gives up after 60 s and keeps the current version.
- **ffmpeg 9.0.1 on Linux** (Windows already shipped 9.0.1). `/api/instance`
  reports the bundled ffmpeg version.
- Fix: the keyframe interval field was applied x1000 (a 33-minute GOP when set).

## v0.8.12

- **RTSP feeds at full quality, with or without the grid.** The composite's
  menu (▾) has a new group, *Publish feeds as*: **Grid + full-quality feeds**
  (default -- the 720p mosaic AND every feed on its own path at its real
  resolution), **Grid only** (one stream, as before) or **Separate feeds**
  (no mosaic at all). Viewers never see the extra paths as tiles: clicking a
  cell of the grid on the main stage now opens that feed itself, full
  quality, downloaded only while it is on the stage; click again (or the
  pill) to return to all feeds.
- **Real zoom and pan on the stage.** Any share on the main stage -- a feed,
  a grid, a screen -- zooms with the **mouse wheel** about the cursor (the
  page itself no longer zooms), pans by dragging, and has − / 100% / +
  buttons in the corner; double-click toggles 2×. Recordings capture what
  the viewer sees.
- **Locked grid cells.** A feed that drops keeps its cell (dimmed,
  "reconnecting…") and comes back in the same place; the arrangement is
  remembered across restarts by feed URL. *Lock cells* in the composite
  menu turns this off (the grid compacts as before).
- **Your own grid in the rail behaves.** A click on it brings it front and
  centre -- a slightly wobbly click used to swap two cells instead and
  swallow the spotlight. Cell swapping and cell zoom only work on the stage.
- **You can see what you share.** A screen or window share shows itself as a
  small live thumbnail in the bottom-right corner (with its menu, and a ▾ to
  collapse it to a pill). Sharing KASTR's own window shows a note instead of
  a hall of mirrors.
- **The side rail pages visibly.** The pager is a proper bar ("‹ Page 1/3 ›
  · 16 more"); the mouse wheel over the rail and PageUp/PageDown flip pages.

## v0.8.11

- **A machine without a camera can share.** Joining without a camera made
  you a viewer, and anything you shared afterwards (RTSP feed, media file,
  screen) sat in "previewing" forever because nothing ever pressed Go live
  for you -- nobody saw it. Any source added while you are in a room now goes
  on air by itself (a name from the Profile is still required).
- **Viewers show up in People.** Members who publish nothing are listed as
  "Name -- watching" and counted in the room chip, so a camera-less machine
  is visible to everyone.
- The ASI swoosh is centred on the compass hub (the small circle), not the
  ring.

## v0.8.10

- **Shared media files: everyone sees the video, and everyone gets
  controls.** KASTR now plays a shared file in its own player and feeds the
  picture and sound to the encoder itself (the library's built-in file
  player rendered nothing to the room -- you heard it, you did not see it).
  Every tile of a shared file carries a bar: **play/pause**, **position
  slider**, **loop**, and your own **mute/volume**; play, pause, seek and
  loop act on the owner's playback for the whole room. The owner's own pane
  has the same bar plus the file's broadcast volume.
- **Files that need converting are detected properly.** Before sharing,
  KASTR asks its bundled ffmpeg what is inside (any MKV, MP4, MOV, AVI,
  TS...): video the browser cannot decode (HEVC, MPEG-4, ...) is re-encoded
  to H.264, audio it cannot decode (AC-3, DTS, ...) to AAC; web-safe files
  are used untouched. The previous "copy the video" path could hand the
  browser an undecodable stream.
- **Uploads show progress and always find a store.** The Files card opens
  with a progress row while a file uploads (and a Retry on failure). If the
  relay host has no file service (older KASTR or unreachable), the file is
  stored on your own machine and announced under your LAN address -- with a
  note when your KASTR is bound to loopback so others cannot reach it yet.
- **Microphone meter works.** The Audio settings meter now reads your live
  mic when it is open and otherwise opens a **test tap** on the selected
  microphone (works before joining and while muted); the talking ring
  re-taps when you unmute or switch microphones instead of giving up after
  15 seconds.
- **Fixes:** radio buttons sit to the left of their labels; the ASI swoosh
  is centred on the compass ring; the breathing animation no longer drifts
  it.

## v0.8.9

- **Use KASTR on a phone.** ⋯ → **Phone access…** shows a QR code and link
  for this machine over **https**, plus a one-time certificate step per phone
  (iPhone: install the profile, then General › About › Certificate Trust
  Settings; Android: Security › Install a certificate › CA certificate). After
  that the phone joins with camera and microphone like any KASTR. The page
  gets a phone layout: icon toolbar, bottom-sheet menus, one scrolling column
  in Gallery, main-stage-only in Speaker view (the bandwidth saver), and a
  "Tap to unmute" pill when the phone blocks audio until you touch it.
  Requires the web host to be reachable on the network (the Relay page's
  "Allow other KASTR machines…" switch or relay-only mode); KASTR then also
  listens on https port 8443 and the relay adds a secure listener on 4445.
  Desktop machines are unchanged (fingerprint-pinned WebTransport).
- **Voice isolation** is selectable and works: Audio settings › Noise
  suppression › *Voice isolation* adds KASTR's own processing to the
  browser's suppression (band-pass, an adaptive gate that trims the hiss
  between words, a leveller). It is conservative by design: a loud fan stays,
  room hiss goes. Falls back to the browser's suppression alone on browsers
  without AudioWorklet.
- **Cleaner settings cards.** Camera ▾ › "More video effects and settings"
  opens a **Video output** card with only the video encoder settings; Mic ▾ ›
  "More audio settings" opens an **Audio output** card with the Opus and
  microphone-processing settings. Both also live under ⋯ › Settings.
- **Relay-only mode applies now.** The Relay page's relay-only checkbox
  gains an **Apply & relaunch KASTR** button that restarts the app in the
  chosen mode immediately.
- **Fixes:** the RTSP **Add** button no longer stays dead when the first
  bridge check raced the server (it re-checks when Share opens) and failures
  now show a toast; the profile picture card stays open while you choose a
  file, so you can drag and zoom right away, and the saved picture is cut
  from the full-quality original (up to 1024 px); the ⓘ next to *Media file*
  is a tooltip, not a click into the file picker; the redundant "Sharing"
  label is gone (the red dot and Stop sharing remain); the Sources list no
  longer lists the camera (the toolbar owns it); the side rail defaults to
  two columns with your own preview spanning the full width, avatar circles
  stay round in small cells, the ASI swoosh is centred, and the name bar
  stays visible in every layout alongside the mute/pause icons; the master
  volume is remembered; **MKV files with AC-3/DTS audio** now play with
  sound — KASTR spots the codec and converts the audio track to AAC with its
  bundled ffmpeg before sharing (video is copied, not re-encoded).

## v0.8.8

- **Teams-style controls.** The top bar is now icon-over-label buttons in
  the Teams order: People · View · Files · More ⋯ | Camera ▾ · Mic ▾ ·
  Share | Leave. Camera and Mic are always there -- on a viewer join they
  add your camera when clicked -- and their chevrons open proper settings
  cards.
- **View menu:** Gallery / Speaker / **Focus on content** (only the main
  stage stays -- everything else stops downloading, the bandwidth saver) /
  Hide me / Full screen.
- **Camera settings card** (Camera ▾): live preview, camera choice,
  Backgrounds (None, Standard blur, ASI navy, Soft mist, or your own
  picture), Adjust brightness, Soft focus, and "More video effects and
  settings" for the encoder page (moved out of the ⋯ menu).
- **Audio settings card** (Mic ▾): speaker choice with the master volume,
  microphone choice with a live level meter, Noise suppression switch, and
  "More audio settings" (also moved out of ⋯).
- **More menu** like Teams: Record, Room info, Files…, Video effects and
  settings, Audio settings, Profile…, Settings ▸ (About & updates, Video
  output), Help. The "Publish only" switch is gone: shared files, screens
  and RTSP feeds are publish-only by nature and never count as people.
- **Share menu** like Teams: "Share content" with an **Include sound**
  switch, **Screen** and **Window** cards (each opens the browser's picker
  on that pane), then RTSP/HTTP feed, **Media file** (with an ⓘ listing the
  supported formats) and **Upload File** (moved here from the room menu).
  Camera and microphone are no longer offered as "sources" -- you cannot
  hide your presence from the room by sharing without a camera.
- **Profile.** ⋯ → Profile…: first name, last name and a picture you can
  zoom and drag inside the circle (or clear). The first launch asks for it
  once; after that KASTR **joins your last room automatically** -- the room
  picker only appears when there is no remembered room or after Leave. The
  profile picture setting moved here from the ⋯ menu.
- **Expand one feed of someone's RTSP grid.** With their grid on the main
  stage, click a cell to fill the stage with that feed; click again for the
  whole grid. A **Gallery** pill takes you back to the gallery.
- **RTSP feeds that survive a restart.** Tick "Keep sharing this feed after
  KASTR restarts" when adding a feed (or "Keep after restart" in the pane
  menu). After the automatic join, the feeds are re-added and go live.
- **Room up-time.** Rooms other than main show how long they have been up
  in the room chip ("Room: ops · 3 · 1h 12m") and in the ☰ rooms list.
- **Updates that really restart.** A runtime update (Check for updates or a
  relay switch, now also from the Relay page's "Point KASTR at this relay")
  closes the app window first -- politely, then by force if the window
  belongs to a browser we did not start -- and relaunches detached from the
  dying process. Leftover `KASTR.old-*` files are swept again 10 s and 60 s
  after the relaunch.
- **Gallery** centres a short last row. Initials are white; the ASI swoosh
  fills more of the circle and the person's colour is the ring. The
  equalizer shows only on audio-only shared content, never on a camera.
- **Files** button in the top bar (badge = files shared) with download
  links, including files shared before you joined.

## v0.8.7

- **Relay history with live status.** The relay popover (top right) now
  lists the last **5** relays you connected to, each with a green
  *Available* / red *Not available* light (re-checked every 10 s while the
  popover is open). Click an entry to put it in the relay field, then
  **Connect**.
- **Updates can no longer strand you on `KASTR.old-...exe`.** If the new
  binary cannot be placed (antivirus / OneDrive holding the file), the swap
  retries and then puts the original back, so `KASTR.exe` always exists.
  Leftover `KASTR.old-*` files from earlier updates are removed at every
  launch.
- **Frozen camera, fixed by the people who see it.** When a viewer's tile
  stops receiving picture for 5 s, their KASTR tells yours; your side
  nudges the encoder (pause/unpause) and, if the viewer still reports it,
  rebuilds that source -- exactly what leaving and rejoining did, per
  source, without you doing anything. You see a small note ("A viewer
  reported your camera frozen -- rebuilt it"). The viewer also re-subscribes
  on its own after 12 s in case the fault is on its side.
- **Recording: name it, choose where it goes.** Stop now opens a small
  dialog: edit the file name, **Save as...** (a real file picker that
  remembers your recordings folder), **Download** (Downloads folder as
  before) or **Discard**.
- **Side rail never squishes.** Your own preview is pinned to the bottom
  of the rail on every page; everyone else pages above it (‹ 1/3 ›).
- **RTSP grid layouts + drag-and-drop.** The composite pane has a layout
  menu (▾): Auto, 2 × 2, One big + strip, Side by side, Stacked --
  remembered. Drag a feed onto another cell to swap them; everyone sees the
  new arrangement.
- **Rename while live.** Changing your name now re-publishes every live
  share under the new name (viewers see the old one go and the new one
  arrive within a few seconds). Previously a shared screen kept the old
  name until it was removed and re-added.
- **Softer join/leave sounds.** A gentle three-note chime up (join) and
  down (leave), quieter and without the abrupt cut.
- **Profile pictures.** ⋯ Options → **Profile picture...** picks a photo
  (downscaled locally). It fills the circle wherever your initials showed
  -- on your own pane and on everyone else's view of you. Without a photo,
  initials sit in an ASI-colored circle over a faint swoosh, each person
  in their own ASI color.
- **Share a file with the room.** ☰ room menu → **Share a file...**
  (up to 500 MB). It is stored on the relay host's KASTR and listed in a
  new **Files** section of the People page for everyone, with a download
  link; it is deleted when you leave the room (or with ✕).
- **Publish only.** ⋯ Options → **Publish only -- don't watch the room**
  for machines that only share (RTSP box, screen source): nothing is
  downloaded or heard. People counts now count **cameras** -- a box that
  only shares RTSP or a screen is a share, not a person.
- **Which relay is someone on?** People groups say "· via <relay name>"
  (the name given to that relay on its Relay page).
- **Grid view name bar.** In the grid, the name stays visible in the same
  bar as the mute/pause chips; only the spotlight side rail keeps the
  hover reveal.
- Relay page attribution ("via" per stream) now actually works -- it was
  feature-detecting a method that this library version keeps elsewhere.

## v0.8.6

- **Record the meeting.** A **Record** button in the top bar captures the
  stage exactly as you see it -- every visible tile at its on-screen size,
  plus everyone's audio and your own -- and saves a `.webm` to your
  Downloads when you press Stop (`KASTR-<room>-<date_time>.webm`). Everyone
  in the room gets a 5-second "Recording started by ..." notice and a red
  REC indicator for as long as anyone records.
- **Updates follow the relay you're on.** Switching relays now checks that
  relay host's KASTR version immediately and updates if it differs (KASTR
  restarts itself). There's also a **Check for updates** button in the
  version popover and in About.
- **Room passcodes stick.** When a room's creator left and came back while
  someone else was still inside, the passcode requirement silently
  vanished. Every member now holds the room's lock record, so it persists
  for as long as anyone is in the room.
- **Shared content fits the stage.** In spotlight view the shared window
  is sized to its own aspect ratio inside the available space: no black
  side bars, no gap at the bottom, and everything shared stays visible.
- **Less bandwidth when it doesn't matter.** Tiles you can't see -- when
  KASTR is minimized or hidden, or another tile is full screen -- stop
  downloading video (audio unaffected). RTSP/HTTP feeds and the grid
  composite now also publish a second, small rendition so a viewer with a
  thumbnail-sized tile pulls ~400 kbps instead of the full stream.
- **Camera freezes.** Two fixes: when your camera stops delivering frames
  (locked screen, another app grabbed it) KASTR now pauses your video for
  viewers instead of leaving them a frozen frame, and resumes with a fresh
  keyframe when frames return. And if the encoder wedges *while someone is
  watching* (frames stop although the camera is live), KASTR nudges it the
  way you did by hand -- pause/unpause -- and rebuilds the source if that
  doesn't take. This never fires on an idle source with no viewers.
- **Background blur** now keeps only *you* sharp: other people in the
  background are blurred with the background. Blur also no longer drops
  off when you switch relays.
- **Audio-only files** show an equalizer that moves with the sound.
- **People page** simplified: Stats and Diagnostics panels are gone, and
  so is the per-stream "hear this stream" selector -- everyone is always
  heard; per-stream mute and volume remain.
- **Relay page**: a new **"Allow other KASTR machines to update from this
  one"** checkbox makes any KASTR an update source without relay-only
  mode (binds the network at next launch + firewall rules now). The relay
  popover shows what KASTR version the relay host runs.
- **"Encoder settings" is now "Video output."**
- **Release zips now include the `updates/` folder**, so one archive is a
  complete deployment that can also serve updates to the other platform.
- Note on connecting without running a relay: it always needs *a* relay.
  When two machines connect "ad hoc", they are both on the same relay
  (yours was pointed at a shared one) -- the Relay page's "Currently used"
  line shows which.

## v0.8.5

- **Grid view tiles your own sources immediately.** Adding or removing one
  of your own sources left the grid laid out for the OLD count for 5-10
  seconds (until the relay happened to echo the stream back), so new tiles
  sat stacked full-width top-over-bottom before snapping into place. The
  page now watches its own-source panes directly and re-lays the grid the
  moment one appears or leaves.

## v0.8.4

- **Grid view no longer stacks your own sources full-width.** When
  multiple RTSP/HTTP feeds merge into the grid composite, the individual
  member tiles are now hidden entirely (the composite IS the view)
  instead of lingering as invisible cells that padded the grid and, on a
  tall window, collapsed it to one full-width column. Grid view now shows
  exactly the one composite tile; removing a feed brings the layout back
  cleanly.
- **Relay-only mode is now truly turnkey — just tick it and relaunch.**
  A relay-only machine (Relay page → "Relay-only machine", or
  `mode = relay` / `--relay-only`) now binds all network interfaces,
  autostarts the relay on the LAN, and adds the firewall rules on first
  run (one Windows admin prompt; Linux uses the desktop's authorization
  or prints a `sudo` line on a headless box). That's everything the
  fleet needs to update from it — the reachability gaps that silently
  blocked updates before are handled automatically now. Every KASTR
  build also ships carrying both platforms' update binaries, so one
  relay machine updates the whole mixed fleet (Windows + Linux) with
  nothing to copy.
- **Your own preview shows the blue talking border now.** The own-tile
  talking ring only ever armed for shared files/screens; a camera's mic
  is managed differently inside the library, so your camera preview
  never lit up. It now taps the camera's mic the same way, so your own
  tile rings blue when you talk, like everyone else's.

## v0.8.3

- **Multiple RTSP/HTTP feeds publish as ONE stream.** Two or more
  RTSP/HTTP sources automatically merge into a single "RTSP Grid"
  share: an auto-adjusting mosaic (grid sizes itself to the feed
  count, each cell labeled) published as one 720p/15fps broadcast —
  one path on the relay instead of N. Drop to a single feed and it
  automatically returns to a normal standalone stream, live, without
  a restart. The grid gets the same relay-truth badge and self-heal
  as everything else.
- **Signal first, quality second.** With encoder settings on Auto,
  KASTR now caps itself at 1080p and 1200 kbps (was: match the
  source, uncapped — a 4K camera would silently try to push a 4K
  encode). Any explicit setting still overrides. The "Negotiated"
  line now also says **· hardware** or **· software** so you can see
  at a glance whether hardware encoding engaged.
- **Hardware acceleration on Linux.** Chromium ships VA-API video
  acceleration off on Linux; KASTR now launches with it enabled, so
  Linux boxes stop silently software-encoding. (Windows already has
  hardware video on by default.)
- **Spotlight stops jumping around.** The stage auto-moves only TO
  shared content (screens/files/RTSP), never to a camera — and once a
  share holds the stage, a second share arriving does NOT steal it.
  When the spotlit share ends, the stage moves to a remaining share
  (or back to the grid if none).
- **Why your tester's 0.8.1 didn't update — and how you'll know next
  time.** The updater failed in total silence (its probe timeout was
  a bare return, and the app has no console). Every launch now
  records the check's outcome, and the Relay page shows it — in red
  when the version authority was unreachable. **Ops note**: the fleet
  updates FROM the machine named in `relay =`; that box must have
  KASTR running, `host = 0.0.0.0` in its kastr.ini, and all four
  firewall rules — the 0.8.2 firewall check will tell you if the
  "KASTR web" rule (the update port) is missing, and the button adds
  it. That missing web-port rule is almost certainly what blocked the
  tester's update.
- **Relay-only mode is a checkbox now** (Relay page → "Relay-only
  machine"): it writes `mode = relay` into kastr.ini for you; the
  next launch boots straight to the Relay page. `--relay-only` still
  works too.
- **Relay address history + sticky relay.** The masthead relay field
  remembers every address you've connected to (dropdown suggestions),
  and the app now REOPENS on the last relay you used — the choice
  survives relaunch instead of reverting to kastr.ini.
- **Join/leave chimes are louder** (nearly 3× the level, longer tail)
  after "difficult to hear".
- **Tile borders are consistent**: no tile wears a standing blue
  border anymore (remote tiles had one, yours didn't). The only
  border highlight is **talking**, and it's now blue instead of
  green.
- **Encoder settings show immediately** — the popover no longer hides
  everything behind a second collapsed "Encoder settings" section;
  the video fields are open on arrival.
- **Sharing your own KASTR tabs is allowed now** (the red border
  marks it). Note on tab sharing: a browser can only list its own
  tabs — that's Chromium, not KASTR. To share a page that's open in
  Chrome/Edge/another app, pick that **window** in the share picker's
  Window pane (the Share panel says this too).

## v0.8.2

- **Mute means silence, everywhere.** Muting a tile now drives its
  volume to exactly zero (the library's documented teardown edge)
  instead of trusting a near-zero floor, the muted tile wears the
  mic-slash chip, and the tile's chevron gains **"Mute (name)
  everywhere"** — one click silences every stream that person publishes
  (the old behavior kept their other streams audible).
- **RTSP/HTTP shares get relay truth and self-healing.** RTSP slots
  were the one publish path with no relay echo: they could badge
  ON AIR while nothing reached other machines (the Linux "RTSP stays
  local" report). They now use the same 8-second discovery-echo test
  (badge flips to NO RELAY within seconds of the relay losing them)
  and the publish self-heal rebuilds a wedged RTSP connection around
  the same ffmpeg feed — verified: relay killed and restarted mid-
  stream, badge NO RELAY → ON AIR, no restart needed.
- **Side rail pages like Teams.** In spotlight view the rail no longer
  shrinks forever: tiles keep a readable size and extras page behind a
  **‹ 1/2 ›** pager at the rail's bottom. Paged-out tiles stop
  downloading video (audio unaffected). The rail is also **resizable**
  — drag its inner edge; past ~300px it becomes **two columns**, and
  the width is remembered.
- **Paused tiles match Teams**: a camera-off chip joins the mic-off
  chip in a bottom-left row (always visible), the "audio only" caption
  is gone (the face is initials + art), and chips never sit under the
  name. Hovering a camera tile shows just the person's name ("Kenton");
  shares keep "Kenton — File" so two shares stay tellable apart.
- **Your tiles lead the grid** (first cell, not last) and stay at the
  bottom of the spotlight rail.
- **Join/leave chimes**: a soft two-note rise when a person joins the
  room, a fall when their last stream leaves. Per person, debounced
  against flaps, silent for the first seconds after connecting and
  under master mute.
- **Background blur** (beta): the camera menu (top-bar chevron) gains
  "Blur background" — person segmentation runs on-device (bundled
  MediaPipe, no internet needed) and publishes the composited video.
  Costs real CPU; off by default, per session.
- **You appear in People**: a "(you)" group tops the list with your own
  streams, and the count includes you ("2 people · 3 streams"). Stats
  and Diagnostics stay hidden until a stream is selected — each row's
  new chevron selects it and opens its stats in one click.
- **Relay-box ergonomics**: the firewall button only appears when rules
  are actually missing (a green "rules are in place" line otherwise —
  and the check covers the web port rule the button adds); a new
  **"Start KASTR when this machine boots"** checkbox (per-user, no
  admin; Windows Run key / Linux autostart entry; installed app only);
  **relay-only mode** (`mode = relay` in kastr.ini or `--relay-only`)
  boots straight to the Relay page with autostart forced and no app
  nav — same binary, so the fleet updater still applies; "Connect to
  it" lists the **LAN address first** (127.0.0.1 never travels).
- **Hub/spoke visibility**: the Federation panel gains a **relay name**
  (it becomes the stats node, so the stats page and stream attribution
  say "garage", not a host slug), the federation URL field stays in
  sync with the server, and on a hub the streams panel labels each
  stream **"· via (spoke)"** when several relays federate.
- **The Go Live tab's disconnect plug is gone** (app shell): the tab
  button only opens/fronts the page; leaving a room lives in the page
  itself, so a mis-click can't hang up a meeting.
- Relay reconnect now also rebuilds a connection stuck in "connecting"
  for 20s (not just one that reports "disconnected"), so field
  machines never sit amber indefinitely.

## v0.8.1

- **The fleet updates itself from the relay host.** At launch, every
  KASTR asks the KASTR instance on its relay's machine what version it
  runs; if different, it downloads that binary, verifies the checksum,
  swaps itself, and relaunches — upgrades AND downgrades ("match client
  to server"). Ops setup, once, on the relay host: set
  `host = 0.0.0.0` in its kastr.ini so clients can reach its web port
  (the firewall button now opens that port too), and build with
  `--publish` (or copy `dist/updates/` next to its binary) so it can
  serve the OTHER platform's binary as well as its own. Opt out per
  machine with `update = off` in kastr.ini or `--no-update`.
- **Relay federation, one field.** The Relay page's new Federation
  panel: paste a hub relay's URL, Save — this relay clusters to it, and
  rooms/streams flow across every federated relay with no client
  changes. The hub machine needs nothing. (LAN certs are trusted
  without verification — the trusted-LAN tradeoff, since KASTR relays
  use throwaway self-signed certs.)
- **The relay stats page finally works** — one missing line: the relay
  never named its stats node, publishing at a path the stats page is
  built to ignore. It now shows a node card with live counters. (The
  stats badge hides on windows narrower than 900px by design.)
- **Teams-parity stage**: names, chevrons and your own labels appear on
  MOUSEOVER only (a NO RELAY warning still forces itself visible);
  Full screen moved into each tile's chevron; a dark mic-slash chip
  bottom-left shows ONLY when that stream is muted; your own preview
  tiles sit at the BOTTOM of the grid; your own paused tile now matches
  the remote standby face exactly (and no longer covers your name —
  that was the "lost overlay" report); the spotlight side rail resizes
  so every tile stays in view.
- **No self-preview of your own screen share** — you're looking at the
  screen already. Instead, starting a screen share pops a small
  always-on-top **mini control window** (mute mic / stop sharing / back
  to KASTR) so you can control the meeting from any app.
- **People is a popover now** — drops down from the People button,
  closes on any outside click — and it counts PEOPLE: one entry per
  name, with that person's streams grouped beneath ("Kenton — 2
  streams").
- **Stuck green rings fixed**: a muted stream's tile could keep its
  talking border forever (muting tears down the audio meter, which
  froze the ring's last state). Rings now clear the moment the meter
  goes away.
- **Room list count**: the current room now counts from live tiles
  (right even on room-code relays); other rooms keep the scan count.
- **Firewall button actually works**: the elevated command was dying in
  PowerShell quoting — it now runs a script file instead (and also
  opens the KASTR web port).
- **Noise suppression toggle** in the top-bar mic menu.
- Cold start: device pickers repaint when the browser announces
  devices, and every launch busts the browser cache ("stale app" fix).
  Relay reconnect after a long outage verified end-to-end (35 s outage
  → green + reconnected without touching anything). The masthead relay
  popover's Apply button is now "Connect".

## v0.8.0

- **Stream from the web.** The RTSP button is now **RTSP/HTTP**: paste a
  direct video URL (mp4/webm/HLS) or a YouTube link — page links resolve
  through a bundled yt-dlp. Caveat: YouTube changes their side now and
  then; if YouTube links stop resolving, a KASTR rebuild with a newer
  resolver fixes it (direct media URLs are unaffected).
- **Relay autostart**: the Relay page gains "Start the relay when KASTR
  launches" — it remembers port/LAN/room-code choices and brings the
  relay up on its own at every launch. (Hand-edit fallback:
  `relay_autostart = true` in kastr.ini.)
- **One-click firewall rules**: an "Add firewall rules" button next to
  the printed commands. Windows shows the admin (UAC) prompt and runs
  the three rules; Linux desktops use pkexec; headless boxes still get
  the commands to run. Only accepted from the machine itself.
- **Rooms live on for 5 minutes after everyone leaves** — the leaver's
  page quietly holds the room's listing, so walking to another machine
  doesn't lose the room. (Closing the app entirely releases it early.)
- **Create new room from the ☰ menu** while already in a room — name +
  optional code, no trip back to the join gate.
- **Audio activity is the border, not a bar**: the VU bars on tiles,
  rows and faces are gone; the green ring is the one signal — and your
  OWN tiles now get the ring too when their audio is live.
- **Hear your own file**: playing a shared file is now audible to you
  locally (it always was to everyone else); its Mute audio also mutes
  your local playback.
- **Paused looks the same everywhere**: your own paused tile shows the
  initials + swoosh standby face, exactly like remote paused tiles, and
  resuming re-keys the encoder so viewers stop seeing a frozen pre-pause
  frame.
- **Every stream window's chevron has "Mute here"** — a local mute for
  that one stream, on remote tiles and your own alike.
- **Names that stick, everywhere**: the install now remembers "Your
  name" server-side, so it survives even browsers that silently lose
  their storage (the Linux report). Any device that lost it gets it
  prefilled from the install.
- **Linux launches the real app now**: the shipped Linux config pointed
  at the plain index page instead of the tabbed shell — which is why the
  Go Live / Relay Server buttons had no connection lights there. Both
  platform configs are regenerated (and now identical).
- **Spotlight side-tiles stop jumping**: the automatic speaker
  enlargement (the 1–3 second zoom every few seconds) is gone; tiles
  hold their size and the ring marks the speaker.
- **RTSP/HTTP shares can hide their preview** ("Hide preview" in the
  chevron — the stream keeps broadcasting; decoding must continue by
  browser design, so this saves screen, not much CPU).
- Empty device pickers now say "No camera detected" / "No microphone
  detected" / "No output devices detected" instead of sitting blank.
  Options menu wording: "Audio Output…". Shared-file labels always read
  "Name — Filename" (a camera-less join used to drop the name from
  every share, for every viewer — fixed).

## v0.7.8

- **Your own streams are now real tiles.** Camera, screen, RTSP and file
  each get their own cell in the grid — same size, same look, same
  bottom "Kenton — Camera" label as everyone else's streams. No more
  one card cramming your streams together (the "stacked full-width /
  stacked full-height" layout bug lived exactly there). Rows now have a
  fixed height too, so nothing can stretch the grid out of shape again.
- **Click yourself to spotlight yourself** — your tiles click exactly
  like remote tiles: click to spotlight, click again for the grid.
- **View button**: "View: Grid" / "View: Spotlight" in the top bar
  switches layouts manually whenever you want.
- **"They can't see me" — fixed at the root.** The watch side always
  healed itself after a relay blip (you kept seeing everyone), but your
  outgoing streams had no heal at all and could stay silently dead
  (they stopped seeing you). Streams now self-heal: live for 20 s with
  a healthy relay and no echo of your stream from it = rebuild,
  automatically. Verified: relay restarted mid-broadcast, streams back
  on air within ~40 s with truthful badges throughout.
- **RTSP streams don't open a window until they're actually
  delivering** — a dead camera no longer opens a black pane — and a
  failure now pops up a notice with the reason (ffmpeg's own words)
  instead of hiding in a badge.
- **The relay light works on every page now.** Pages without their own
  relay connection (the Relay Server page, the shell) probe the in-use
  relay over HTTP: green while it answers, red within ~15 s of it going
  away.
- **"Streams on this relay" unstuck**: the panel now probes the relay
  KASTR is actually pointed at (the shared/external one included), not
  only a locally hosted relay, and names it — "2 streams in 1 room on
  10.10.105.190:4443".
- **Cleaner self view**: the row strip under your streams is gone; each
  share's chevron menu now carries Mute/Unmute audio, Pause/Resume
  video, Stop sharing (and Spotlight for everyone when several shares
  are live). The camera's controls stay in the top bar.

## v0.7.7

- **Chevrons toggle**: clicking the chevron that opened a menu now closes
  it — everywhere (top bar, share overlays, tile overlays, rows).
- **Top-bar mic/camera icons centered** in their buttons.
- **The join gate is dismissible**: a ✕ (and Esc) closes it without
  joining — for machines that only host the relay and never join a
  stream. The masthead relay control is reachable again once the gate is
  closed (this is the "can't click the relay server" report — the gate
  covered the in-page relay badge; the shell's Relay Server tab was never
  blocked). Way back in: the room chip (now "Join a room…") or the ☰
  rooms button reopens the gate. Leave hides while you're not in a room.
- **Camera no longer comes up empty on app start**: the silent rejoin
  could fire before Windows finished enumerating devices, quietly joining
  you as a viewer — a refresh "fixed" it. Joining now waits out that race
  (up to ~3 s) before deciding you have no camera.
- **Room occupancy badges**: the join gate's room list shows how many
  people are already in each room ("main — 2 here", refreshed every 5 s,
  and your in-progress selection survives the refresh); the room chip
  shows a live count while joined ("Room: main · 3"); the ☰ room menu
  shows counts too. Counts publishers (everyone who joined with a
  camera/share); on room-code relays the pre-join counts aren't visible
  to an anonymous scan, so the gate badge is omitted there.
- **The Relay Server page lists the streams flowing through it** —
  refreshed every 5 s, from any machine pointed at that relay. A stream
  badged ON AIR anywhere MUST appear in this list; if it doesn't, that
  device is on a different relay. On room-code relays the anonymous
  probe can only see rooms, and the panel says so.
- **The layout recomputes when the window does.** 0.7.5's fixed-size
  tile cards were computed once and could go stale after a resize —
  tiles frozen at the wrong width stacked full-screen, one on top of the
  other, until the next state change. The stage now relayouts on every
  window/stage resize. Also: when you share while your camera is up,
  your self-view card shows the camera and the share **side by side**
  instead of stacked.
- **Speaker icons replace the ♪ note glyph** everywhere it marked audio
  state (no-audio markers on tiles and rows, the "audio only" face).

**Multiple relays CAN be joined into one federation** (research result,
config-only, nothing to build): the bundled moq-relay 0.14.12 supports
symmetric clustering — a broadcast published to any clustered relay is
visible through every other, with unchanged paths, so rooms and
discovery just work across machines. Minimal LAN recipe: pick one hub
machine (a relay-only box is ideal; start its relay with Allow LAN); on
each OTHER machine add to its relay config:

```toml
[cluster]
connect = ["https://<hub-ip>:4443/"]

[client.tls]
disable_verify = true   # trusted LAN; the relays use throwaway self-signed certs
```

Every relay also needs a unique `[stats] node` name once clustered. The
hub going down pauses federation (local streams keep working) and heals
automatically when it returns. KASTR doesn't yet write these keys into
its generated config — say the word and a "Join relay federation" box on
the Relay page can do it. Note: with "Require room codes", clustering
additionally needs the same auth key on every machine plus a
relay-to-relay token — worth doing as a KASTR feature rather than by
hand.

## v0.7.6

- **The main camera's mic/video buttons live in the top bar**, by the
  Leave button, Teams-style — with their device-pick chevrons. The
  self-view card no longer shows a row for your own camera (its preview
  stays); shared sources keep their rows.
- **Shares wear their menu on the window itself**: screen, RTSP and file
  shares get a chevron overlaid on the video (top-right), with Stop
  sharing — and, when more than one share is live, Spotlight for
  everyone. Other people's shared-content tiles get the same overlay
  chevron with Spotlight for me / Spotlight for everyone.
- **Stop sharing (all) button** next to Share: one click ends every
  screen/RTSP/file share at once. Only visible while sharing.
- **Spotlight for everyone**: choosing it puts that share on every
  connected user's stage (a lightweight room-wide signal; the newest
  choice wins, and it releases when the chooser leaves or stops). A
  single share still spotlights automatically for everyone, as before.
- **Fixed: going live on a room-code relay silently killed every
  publish.** The go-live step rewrote the publish connection's URL
  without its auth token; the relay refused the stream while the badge
  still said "ON AIR". Devices on a secured relay each saw only
  themselves.
- **The ON AIR badge now tells the truth**: it turns "NO RELAY" when the
  relay hasn't actually accepted the stream within ~8 seconds — whatever
  the cause (auth, wrong relay, network). Previously it was impossible
  to tell a dead publish from a live one.
- **See which relay each device is on**: hover the "Room:" chip — its
  tooltip now reads "Room main via http://…". The People panel's stats
  already listed the relay.
- **Cloned machines no longer collide**: broadcast paths embed the
  machine name, and two boxes imaged from the same install (same
  hostname) produced byte-identical paths — colliding on the relay and
  suppressing each other's tiles as "their own", so each device saw only
  itself. The path's host segment now carries a stable per-machine
  suffix (from the network adapter), invisible in the UI.

**If devices in the same room can't see each other after updating:**
on each device, hover the "Room:" chip and confirm every device names
the SAME relay — if one says `127.0.0.1` or an old address, point it at
the right relay via the masthead badge (top right). A pane badging
"NO RELAY" means that device's stream is not reaching the relay it
names. And note "Point KASTR at this relay" hands out `127.0.0.1`
unless "Allow LAN" was checked when the relay started — other devices
need the LAN address.

## v0.7.5

- **Teams-style tile cards.** The grid view now lays everyone out as
  uniform 16:9 cards — video cropped to fill the card, the block of
  cards centered in the stage, and the card size recomputed as
  participants and shared streams come and go. In the focused view the
  side tiles crop the same way; the main picture keeps its full frame,
  so shared screens never lose edges.
- **Your room survives page reloads and tab switches.** Joining a room
  now saves a rejoin ticket for the life of the app window: any reload
  of the Go Live page (including the disconnect plug re-opening it)
  silently rejoins the same room with your saved name, mic/video
  toggles, and room code — re-minting on secured relays. The ticket is
  cleared only by Leave, a deliberate disconnect, or closing the app.
  Switching rooms updates the ticket, and a stale code falls back to
  the normal join gate with “Wrong room code.”
- **The disconnect plug asks before dropping a room.** The plug shares
  the Go Live tab button, so a mis-click could cost the room. Joined =
  “Leave the room and disconnect?” first; OK leaves properly (camera
  released, ticket cleared), Cancel just fronts the tab.
- **Linux: your name (and everything else) finally sticks.** Ubuntu's
  default Chromium is a snap, and snap confinement silently denies the
  browser access to KASTR's profile under `~/.local/share` — so the
  browser ran on a throwaway profile and “Your name”, rooms, and sizes
  vanished every launch. With a snap-confined browser the profile now
  lives at `~/snap/chromium/common/kastr-profile` (a place the snap may
  touch); non-snap browsers are preferred when installed, and both the
  launch log and `--diagnose` name the profile in use.
- **The Relay tab's running-light actually runs.** The red on-air dot
  read status from the Relay tab's page, so it went dark whenever that
  tab was closed — and a throttled background tab could leave it stuck
  on. The shell now asks the server directly: the light follows the
  relay process itself, on every platform, within a couple of seconds.

## v0.7.4

- **The Relay page's firewall hint speaks the server's language**: on a
  Linux-hosted KASTR it now shows the ufw commands instead of PowerShell
  (the page asks /api/instance which OS is serving — the firewall being
  configured is the host's, not the browser's). Both platforms' commands
  now include the room-code port (TCP port+1) alongside the relay port.
- **The self-view's camera/mic menus open upward when needed**: the
  controls moved to the bottom of the preview card in 0.7.0, and the
  menus kept opening downward — off the bottom of the window, looking
  like the chevron did nothing.

## v0.7.3

- **Linux: a browser that cannot open a window no longer takes the
  server with it.** $DISPLAY can be set yet unusable — root inside a
  desktop session hits the X server's “Authorization required, but no
  authorization protocol specified” (plus D-Bus refusals), Wayland-only
  sessions and snap confinement fail the same way — and KASTR waited a
  silent minute, then quietly shut down under the very URL the errors
  said to open. Now: the crash is detected within a second, KASTR says
  it is still serving (with a root-specific hint), and stays up — open
  the printed URL in any browser and the normal window lifecycle takes
  over from its heartbeat. Windows behaviour is unchanged.

## v0.7.2

- **Linux: headless machines serve without a window.** With no $DISPLAY
  or $WAYLAND_DISPLAY (servers, SSH sessions, root shells outside the
  desktop's environment) Chromium exited with “Missing X server” and
  took the server down with it. KASTR now detects the headless case,
  keeps serving, and prints the URLs — including the reminder that
  reaching the UI from another computer needs `--host 0.0.0.0` (or
  host in kastr.ini).
- **Linux: launch from the GUI.** `sh install.sh` (in the linux folder)
  registers KASTR in the applications menu with its icon — GNOME's file
  manager refuses to run raw binaries by design, so the launcher is the
  double-click answer. The CLI works as always.
- **Release archives keep a keepsake per line**: the newest archive of
  each x.y series (0.6.x, 0.7.x, …) now survives pruning alongside the
  usual last five.

## v0.7.1

- **Linux: runs as root.** Chromium refuses to start its sandbox as root
  (crbug.com/638180) and quit before the window appeared — seen on an
  Ubuntu machine driven as root, which is normal on robot/industrial
  boxes. KASTR now detects root on Linux and passes --no-sandbox itself;
  the window only ever loads the app's own local pages. The Linux README
  says so too.

## v0.7.0

Room codes become REAL, and the meeting chrome takes its 0.7 shape.

- **Secured relays.** Hosting a relay gains “Require room codes”: the
  relay then verifies signed tokens on every connection, and a token
  service on relay-port+1 mints them — the room code is the only
  credential (no accounts, no user list). Locked rooms register with
  the minter; a wrong code is refused by the SERVER, not the page, and
  on secured relays the room announce carries only a locked marker —
  no crackable material is published. Open relays are untouched, and
  pages work against both without a setting. Honest limits: open rooms
  are open to anyone who can reach the relay, codes travel over plain
  HTTP on the LAN, and room names/lock status stay listable.
  (Found and fixed on the way: the relay's key loader mangles absolute
  Windows paths, so the key rides a relative path + working directory.)
- **My preview joined the stage**: the top-left cell of the collage, or
  the top of the ladder in the spotlight, with the name and mic/video
  controls attached to its bottom — the top bar carries controls only.
- **Share panel, distilled**: three square buttons (Screen / RTSP /
  File) and the Sources list — Devices, Broadcast and Status left the
  panel (their machinery drives the join flow untouched).
- **An ⋯ Options menu** carries Audio &amp; output, Encoder settings,
  About KASTR (the old home page's identity, now that the ASI logo is
  just a logo) and Help at the bottom. Rooms moved to a ☰ menu beside
  the “Room:” chip. Popovers collapse on any outside click.
- **Room code, not password**: the inputs are masked text fields the
  browser's password manager ignores — no more save-password prompts.
- **Disconnecting Go Live returns to its start page** (the join gate),
  never some other tab.
- **The stuck-red relay light is fixed for joined pages too**: a
  connection dead for 10 s is rebuilt (discovery AND the room's
  registry announce), with a fresh token when secured.
- **Shared streams carry a chevron** with the one action they need —
  stop sharing.

## v0.6.10

Teams-style stage layouts.

- **Collage**: everyone in the room in a uniform best-fit grid that
  recomputes as people join and leave — the stage fills, never scrolls.
  (The 0.6.3 manual tile sizes and corner grips are dormant, not
  deleted.) Drag still reorders.
- **Spotlight**: click a tile — or share anything that is not a camera
  (screen, RTSP, file), which takes it automatically — and that stream
  fills the big left stage while everyone else ladders down the right,
  with the person currently speaking highlighted and enlarged at the
  top of the ladder. Click a ladder tile to swap it into the stage;
  click the stage to go back to the collage. When the shared content
  ends, the collage returns.
- **A green ring means audio is arriving** on that stream, in both
  layouts — fed by the same per-tile meters, so it is decode-truth,
  not a guess. The speaker pick is the loudest recently-active stream,
  held ~1.5 s so the ladder does not flap.

## v0.6.9

The last polish pass before v0.7 access control — and the legacy
publish page is gone for good.

- **Switch rooms from the room chip.** The “Room: …” chip in the bar
  opens a menu of every live room (padlock on the locked ones; the
  password is asked right there). Switching while publishing
  republishes your sources under the new room — devices never blink,
  and viewers in the old room lose you, which is what leaving means.
- **The self-view mute now actually turns red** when muted — a CSS
  specificity bug had been eating the state the video button showed
  fine — and the device chevrons sit flush at the same height as
  their buttons.
- **Quieter chrome**: no red ring on your live pane and no red fill on
  the Share button (being on the page IS being live); the Share dot
  now lights only when you share something beyond your camera (screen,
  RTSP, file). The “Go Live” heading, the Grid-era audio-mode and
  warm-audio buttons, and the People panel’s watch/park controls all
  left the UI (the machinery stays; audio is “all”, warm on, streams
  auto-watch). The People panel section is titled People.
- **Popovers collapse when you click anywhere** — including clicks that
  land in another frame (the page area under a masthead popover, the
  masthead over a page popover): focus loss now closes them all.
- **The People button** renders icon and label on one line, inside its
  border.
- **publish-camera.html is removed** — from the site and from the
  bundle. The Share panel on Go Live has been the whole publish surface
  since 0.6.6; the fallback earned its retirement. (Old builds in
  dist/archive still carry it if ever needed.)

## v0.6.8

A polish pass over the meeting, from a day of using it.

- **The join card acts like Teams now**: a live camera self-preview with
  round mic and camera toggles (both OFF by default — they map straight
  to how you join), a free-form name (the first-name + last-initial
  format is no longer forced), and one Join button. A machine without a
  usable camera joins as a viewer automatically — the separate
  “screen instead” / “without a device” buttons are gone (screen
  sharing lives in the Share panel, any time after joining).
- **Channels are called rooms** everywhere you can see. A room’s
  password is asked for only when the room actually has one, the room
  name field appears only when creating a new room, and an empty room
  is deleted — gone from the picker until someone creates it again.
- **Muted and paused are loud red** on your self-view controls, and the
  device chevrons fused onto their mute/pause buttons — one control.
- **Names, not model numbers**: your preview pane wears just your name
  (no path, no status line); streams label as person + device type
  (“Kenton — Camera”), and the stream rows’ mute uses the same mic
  glyph as the self-view. A paused stream shows the person’s initials
  over the ASI swoosh instead of a “video paused” string.
- **Click a tile to focus it; click again for the grid.** The Grid
  button and the sort dropdown are retired (drag still reorders).
- **Sources preview the moment they are added** — no separate Start
  click (Start remains as the retry for a failed source).
- **The relay moved into the top-right badge**: its popover now changes
  the relay (server-wide, plus every open page follows live) as well as
  showing stats. The toolbar Relay button is gone.
- **Pick your speakers**: the Audio panel gains an output-device
  selector (remembered on this machine), and every microphone picker
  names what “System default” currently is.

## v0.6.7

Meetings. The page is now **Go Live**, and it behaves like one: you join
a channel, you are present in it, you leave it.

- **Join before you watch.** A Teams-style gate collects your name,
  camera and microphone, and the channel; nothing connects until you
  join. Joining with a camera puts you on air **muted, with video
  paused** — deliberate states you flip from the bar's self-view
  controls, so nobody joins hot. “Share a screen instead” and “join
  without a device” are the honest escape hatches (a no-device joiner
  is invisible to others — the roster is the streams).
- **Channels.** Broadcasts live under a channel (room) on the relay;
  discovery only sees the channel you joined. The picker lists live
  channels (plus any you created) and “main” always exists. A channel
  you create can take a password — **advisory in this release**: it
  gates the join screen (salted hash on the relay), not the relay
  itself; real enforcement arrives with v0.7's tokens. Channel changes
  are leave-and-rejoin, never a silent re-aim of a live broadcast.
  The old publish page (and any pre-0.6.7 build) publishes without a
  channel and is therefore invisible to Go Live pages — accepted for
  the legacy fallback's last release.
- **A meeting layout.** Top bar (your streams with live previews, mic/
  camera controls, channel chip, red **Leave**), full-height stage, and
  a **People** panel on the right holding the stream list, stats and
  diagnostics. Leave stops publishing outright — camera released,
  light off — and returns you to the gate.
- **Streams in your channel start watched** (park still remembered per
  stream — an explicit park survives reconnects and reloads), and
  **audio defaults to all streams**: a meeting is heard.
- **The relay badge tells the truth**: green connected, yellow
  connecting, red once the relay has been unreachable for 15 s — and
  it recovers by itself (a stuck connection is rebuilt on observed
  death, never on idleness). The app shell's Go Live tab shows the
  same truth in its dot, and its ✕ became a plug: disconnect when
  open, connect when closed.

## v0.6.6

The Live Streams merge: the Watch page absorbs the publish machinery and
becomes the app's one page.

- **One page for everything.** The publish core — devices, sources,
  encoder settings, RTSP/file/screen, the operator gate, Go live — now
  runs natively inside the (renamed) Live Streams page. The Share panel
  hosts the real controls instead of an embedded copy of the publish
  page. Deliberately a second module script: a failure in the ported
  core degrades the page to watch-only rather than killing it.
- **Full-framerate self-view.** “My streams” shows your local sources as
  live preview panes — the slot’s own canvas, same document, no relay,
  no webp — replacing the publish page’s preview stage outright.
  Previews are simply always on now (the self-view IS the preview); the
  leased thumbnail path remains for other windows on this profile.
- **Live Streams is the default page** the app opens on, and the
  masthead / home page rename with it. The relay field in the Relay
  popover is now the one relay truth for watching AND publishing.
- **The old Publish page stays for one release** as a fallback —
  reachable from the Share panel header and the home page (opens in its
  own window), fully interoperable over the sources channel, byte-frozen
  except for one link label. It goes away once the merge has proven
  itself in the field.
- **Enable devices can no longer look dead.** Field report: the button
  did nothing until an app restart (a wedged permission prompt). It now
  shows “Requesting…” while the prompt is pending and logs a hint if
  the browser hasn’t answered after 10 s.

## v0.6.5

The big Teams-style pass: real icons, a cleaner Watch page, your own
streams in their own pane with live previews and device menus.

- **Real icons, at last.** The first pictograms in KASTR: microphone,
  camera and speaker glyphs with slashed off-states — red for a muted
  mic, amber for paused video (deliberate, not a fault). The mic icon
  carries a Teams-style level fill; today it shows state (a live level
  for your own mic needs a publish-side meter, planned).
- **The Watch toolbar folds away.** The intro text became a Help (?)
  popover with the full key and gesture list; Relay URL + Connect became
  one Relay button (with a note that connecting rebuilds every tile);
  the volume/mute/mode/warm cluster became one Audio button that turns
  red when everything is muted. Opening any panel closes the others.
- **Your own streams leave the grid.** Watching yourself through the
  relay paid twice for a picture you already have. Own broadcasts now
  live only in “My streams” — with small LIVE previews painted by the
  publishing view itself and passed across locally (never through the
  relay), leased only while the pane is visible so idle cost is zero.
  Two honest notes: your own machine no longer reports starvation on
  your own streams (another machine's watcher still does), and a
  same-named broadcast from another machine would be hidden too —
  name collisions were already unsupported.
- **Switch devices from Watch.** Camera rows in My streams grow menus:
  pick which camera feeds that stream (the broadcast keeps its original
  name — renaming live would drop viewers) and which microphone the
  machine uses (persists exactly like the Publish picker).
- **A proper standby face.** Paused or audio-only tiles show the ASI
  swoosh breathing on a navy pool instead of a black rectangle — and it
  respects reduced-motion settings.
- **Publish reorganised around devices.** The camera picker (and Add all
  cameras) moved into Devices above the microphone; the mic now follows
  the cameras — adding a camera while nothing carries the mic attaches
  it, removing the carrier moves it to the next camera with a note.
  Previews are on by default (reversed from 0.5.2 at the requester's
  direction; the Share panel forces them off — its stage is hidden).
  The encoder settings panel folds shut; Auto remains the recommendation.

## v0.6.4

The header tells the truth about the relay, and Watch gets a Teams-style
self-view.

- **The relay badge follows a repoint.** The number in the top right was a
  snapshot taken when the window opened — the server substitutes the relay
  into pages as it serves them, the app shell's own document is served
  once per launch, and “Point KASTR at this relay” changed a value nobody
  was ever told about. Now `/api/instance` carries the live value, the
  badge polls it and updates within ~5 seconds, the stats popover
  re-targets the new relay, and the Relay page's “Currently used” field
  reads the server instead of scraping the badge (it used to show “—”
  forever inside the app). Deliberately unchanged: each page's own Relay
  URL field and any running connections keep their relay until reload,
  and a restart returns to the launch configuration.
- **“My streams” on Watch.** A pane above the stream list shows everything
  this machine's views are publishing — fed by their announcements, so
  even streams you have parked appear — with a live/preview dot and
  per-source mute-mic and pause-video buttons that act on the owning
  view, addressed the same way the existing remote “stop” is. Muting is
  now durable for the session: the effective mute used to be recomputed
  from the mic-target selector on every start and on every retarget, so
  a mute set anywhere else silently reverted. State changes announce
  immediately (the 4-second liveness tick alone was too slow for a
  control surface). RTSP rows show name and state only — that path is
  video-only by design.

## v0.6.3

Audio without video, tiles you can size by hand, and tiles you can grab
anywhere.

- **Pause video, keep the audio.** Every camera, screen and file source row
  now has a `video: on / paused` toggle. It drives the library's own
  “invisible” control: the video encoder stops for every source kind, a
  paused camera is released outright (light off), and the mic — or the
  file's / tab's own audio — keeps publishing. The broadcast stays
  announced and viewers keep the sound without a reconnect; audio
  continues only if the source carries audio (a paused camera that isn't
  the mic target announces an empty catalog). The state survives
  Stop/Start within the session. RTSP rows have no toggle — that path is
  video-only by design.
- **Audio-only streams look deliberate on Watch.** They used to render as a
  black rectangle with a permanent amber “picture: no / recovering” in
  Stats — and posted a false “viewers report receiving nothing” warning to
  the publisher every 30 seconds, because the starvation check counted
  video bytes that legitimately never come. Now: a big level meter with
  “♪ audio only” (or “video paused” when there is no audio either),
  Stats say `video: none (audio only)`, the video pipeline is not enabled
  at all, and the starvation report only fires for broadcasts that
  advertise video. (A broadcast whose catalog never arrives at all — the
  relay fault the report exists for — is still reported.)
- **Size Watch tiles by hand.** Drag the corner grip of any tile: the grid
  is now fine cells and the other tiles flow around whatever size you
  choose (the default tile matches the old size). Sizes are remembered on
  this device; narrowing the window clamps a too-wide tile and widening
  restores it. Exact manual order is approximate around oversized tiles —
  the packing fills gaps by design. Resizing (and now plain window
  resizes, which never did) re-picks the video rendition for the new
  size, and the picker no longer wipes the library's own size and
  bandwidth hints when it pins a rendition by name.
- **Drag tiles from anywhere.** The whole tile is the reorder handle, not
  just the name bar — buttons and the resize grip excepted. Plain clicks
  still select (the drag threshold went from 5 to 6 px, since a big
  surface invites wobblier clicks).

## v0.6.2

RTSP feeds that heal themselves, a Watch page that only downloads what you
ask for, and a mic picker that tells the truth.

- **RTSP feeds no longer freeze after running a while.** The bridge's endless
  stream was never steered toward the live edge: every hiccup left the
  picture a little further behind real time, and once the browser's demuxer
  filled up it stopped reading the connection entirely — wedging ffmpeg in a
  write forever, with every counter still reading “healthy” (`frames=` counts
  encoder output, which keeps climbing while the backlog plays out; nothing
  after a slot wires could ever report a fault). Fixes, all driven by
  observed facts — no silence timers came back (the 0.5.28 rule):
  the picture is held near live by chasing at 2× when it falls more than
  ~3 s behind (measured as wall-clock vs media-clock drift — the stream is
  unseekable, so seeking is never attempted); a feed more than 20 s behind
  reconnects instead (≈2 s back to live); a playhead frozen for 10 s while
  playing restarts the feed; a media error after wiring — previously
  invisible — restarts it; keyframes stopping while frames flow (a
  timestamp fault that blanks new viewers) restarts it; and the bridge now
  times out a reader that stops consuming (15 s), so an abandoned
  connection can no longer wedge ffmpeg — the feed list stops claiming a
  dead feed is running. Stale ffmpeg errors no longer bleed into the next
  attempt's report.
- **Watch subscribes per stream.** Every announced stream is listed, but
  nothing connects until you switch it on — each tile costs its own QUIC
  connection plus catalog even when hidden, so parked streams now cost
  exactly nothing. Click a row (or its ○ toggle) to start one; ● parks it
  again; watch all / park all in the list header. Your choices are
  remembered on this device, a stream that goes away and comes back returns
  subscribed, and arrows / number keys never subscribe on their own.
  (A parked tile keeps its place in the list but can't be drag-reordered
  until it's watching again — its pane isn't on the stage to drag.)
- **The mic picker names the real default.** Chrome's device list carries
  “Default — X” and “Communications — X” pseudo-entries that duplicate real
  microphones — and picking “Default” was a silent no-op (the library strips
  that id from the list it honours). The picker now shows
  “System default — your actual default mic” plus the real devices only,
  auto-selects the default until you choose, remembers what you choose,
  follows plug/unplug live, and says — once — when your saved mic is
  missing and it has fallen back to the default.

## v0.6.1

Audio you can actually control, names on every stream, and a grid you can
arrange.

- **Mute finally mutes -- and stays muted.** Two earlier attempts were built
  on the belief that the library had no volume control. It does: `volume`
  drives a real gain with a smooth ramp, and values just above zero silence
  the sound *without* dropping the stream. Worse, our old workaround -- a
  gain spliced into the audio graph -- ended up wired **in parallel** with
  the library's own path whenever the volume was written, so the sound
  played on at full loudness no matter what the controls said. The splice is
  deleted; every level and mute is now a plain volume write, re-asserted
  once a second so nothing can drift back. Master mute, per-stream mute,
  per-stream levels and the master slider all do exactly what they say.
- **Live level meters.** Every stream row and tile shows a thin meter that
  moves with the sound actually being decoded -- green when you can hear it,
  grey when it is silenced. Streams that carry no audio at all (RTSP
  cameras, by design) show a crossed-out note instead of controls that
  could never do anything. The meters pause while the window is hidden, so
  they cost nothing in the background.
- **Pick your microphone.** The Devices panel now has a microphone selector.
  The choice is remembered on this machine (never travels with the exe),
  applies to every source that carries a mic, and falls back to the system
  default if the remembered mic is unplugged. Switching while live re-opens
  the mic -- a brief blip on that stream's audio.
- **Streams now say who is publishing them.** Going live requires your name
  -- first name and last initial, like "Kenton J" -- asked once and
  remembered. It becomes part of the broadcast name
  (`machine/kenton-j/camera.hang`), and the Watch page shows it as
  "Kenton J -- camera" on every row and tile. Streams from older builds
  keep their old labels. The Share panel asks for (and shares) the same
  name.
- **Arrange the Watch grid your way.** Drag any tile by its name bar to
  reorder -- the list, the row numbers, the digit keys and the arrow keys
  all follow, and the arrangement is remembered on this machine. An Order
  control offers name, person and newest-first sorts; dragging switches
  back to manual with whatever you were looking at as the starting point.
  Reordering never interrupts playback.

## v0.6.0

RTSP cameras now stream at their real frame rate. This closes out the work of
making RTSP ingest genuinely usable, which is why it gets a minor version.

- **Full frame rate for RTSP sources.** The published stream sat at one frame a
  second while the camera delivered 15-30. Bisected with everything else held
  constant -- same page, same encoder, same resolution, hidden and visible, fixed
  and variable timing -- and the culprit was the *audio track* in the bridge's
  output: with the camera's audio muxed in, the browser captures the video at
  ~1 fps; strip the audio and the identical stream captures at the full rate.
  Resampling it did not help, so the track itself is what throttles capture.
  The bridge now delivers video only, and the camera went from 1 to a measured
  **30 fps end to end**, ~4 Mbit/s at 1080p.
- Nothing is lost by dropping that audio: the RTSP publish path has only ever
  built a video broadcast -- the audio track was decoded and then discarded, so
  its only observable effect was breaking the video. Publishing camera audio
  would be a new feature (a separate audio pipeline), not a regression fix.
- The disappearing video-file broadcast reported against v0.5.27 does not
  reproduce on v0.5.28 -- verified running a looping file beside the camera for
  a minute with a live viewer. Consistent with the cause being the restart and
  rename machinery removed in v0.5.28.

## v0.5.28

- **The watchdogs that guessed are gone.** With the software-encoder fallback
  in place the video works, and what was left misbehaving was this machinery
  itself:
  the "broadcast stopped producing" watchdog restarted a healthy stream every
  time its viewers left (encoding is on demand, so frames stopping when nobody
  watches is correct, not death); the relay-name checking renamed sources to
  `-2` on every relaunch, because the previous session's own announcement
  lingers on the relay for a while and cannot be told apart from a rival; and
  the fifteen-second "went quiet" timer was a guess with false alarms.
  All of it is removed. A stream now restarts only on unambiguous signals: the
  camera feed actually ending, or the capture track actually dying. Names are
  only de-duplicated against this app's own sources, never against the relay,
  and nothing renames automatically.
- Verified: a live broadcast left without viewers for over half a minute keeps
  its name and stays on air, and a returning viewer gets the picture back.

## v0.5.27

- **When the hardware video encoder fails, KASTR now switches itself to
  software encoding.** The failure your console has been showing all along --
  `publish error: track=video error=Encoding error` -- is the browser's hardware
  encoder accepting a configuration and then dying on the first real frame. It
  is browser-specific: the same machine encodes fine in one browser and fails in
  another, which is why it never reproduced outside the app. When it happens,
  every viewer gets a reset stream and a black picture while the publisher
  merely looks idle. On the first such failure the app now steers the encoder
  choice to software, restarts the affected sources, says so plainly, and
  remembers the choice for this machine.
- **The name-rotation from v0.5.26 is gone.** It was built on the theory that a
  relay path had gone bad; renamed broadcasts failing identically disproved
  that, and the rotation just produced a parade of dead streams. A viewer
  receiving nothing now produces a status message, not a rename.
- The diagnostics snapshot now includes the encoder configuration actually in
  use (codec, hardware or software), recent library errors, and whether the
  software fallback is active.

## v0.5.26

- **A broadcast whose path has gone dead on the relay now moves itself to a
  fresh name.** A relay can reach a state where one path silently absorbs every
  subscription: watchers get a reset stream and a black picture, and the
  publisher just looks like nobody is watching -- which is also what "nobody is
  watching" looks like, so the publisher alone can never tell. Verified live
  with two independent watchers subscribed to one such path and the publisher's
  encoder never asked for a single frame. And because the stale claim does not
  announce itself, the name-clash guard cannot see it either.
  The one party that can tell is a watcher: subscribed, catalog in hand, and
  nothing arriving. So the Watch page now reports a stream that has delivered
  zero bytes for 25 seconds, and a publisher in the same app that owns the name
  and whose encoder is genuinely idle re-announces under the next suffix --
  the same mechanics as editing the name by hand, so nothing is torn down.
  Renames are throttled, capped at five, and end in a plain message telling you
  to restart the relay if even fresh names deliver nothing.
- This only heals publishers running in this app. A viewer cannot fix a
  publisher on another machine; restarting the relay clears such paths for
  everyone.

## v0.5.25

- **Home page reordered to match the top bar** -- Publish, Watch, Relay server --
  and the "recommended" tags removed.
- **Stops forcing an encoder configuration the browser cannot honour.** v0.5.12
  started pinning RTSP sources to H.264 at 1080p. From that the library computes
  an encode size of 1904x1072, while the frames a camera actually delivers are
  1920x1088 -- and the encoder then fails with "Encoding error", closes itself,
  and every viewer receives a reset stream and a black picture. Left alone, the
  library picks a size that matches the source exactly and it works. Both
  encoder settings are back to Auto; choosing them by hand still works, and is
  now clearly the exception rather than the default.
  Note this is only safe because the bridge now scales oversized cameras down
  before the browser sees them (v0.5.12's other half): Auto was previously
  choosing VP9 at full 4K, which no browser can encode in real time.

## v0.5.24

- **Converts full-range camera video, which the browser's encoder refuses.** The
  app's console gave this away at last:

      publish error: track=video error=Encoding error.
      subscribe error: remote error: 0  (WebTransportError: Received RESET_STREAM)

  The browser rejects the frames, the library rebuilds the encoder, one keyframe
  comes out, and it fails again -- which is why the publisher looked like it was
  managing exactly one frame a second with half of them keyframes, a figure that
  made no sense as a performance measurement. Viewers get a reset stream and a
  black picture, and nothing anywhere reports a fault.
  The cause is colour range. This camera sends FULL-range video (`yuvj420p(pc)`),
  where the built-in test pattern that has always worked is limited-range
  (`yuv420p(tv)`). That is the only property separating the source that works
  from the one that does not. Note that `format=yuv420p`, which the bridge was
  already applying, does NOT convert the range -- it only renames the format,
  which is why an earlier attempt at normalising this achieved nothing. The
  conversion is now explicit, and a full-range source is never passed through
  untouched however convenient copying it would be.

## v0.5.23

- **Fixes a source renaming itself over and over.** A name that clashed was
  renamed by appending `-2`, but the check then ran again on the new name and
  appended another, producing broadcasts called
  `camera-2-2-2-2-2-2-2-2-2-2-2.hang`. Seen live while testing something else.
  The suffix is now replaced rather than stacked, and the check runs once after
  a burst of relay announcements instead of once per announcement.

## v0.5.22

- **Fixes a publisher that keeps capturing but sends nothing.** A camera is
  published by capturing one track from the video element, and the encoder is
  built around that one track. If it ends -- which happens without the video
  element reporting anything -- the encoder is starved: it stays live, keeps
  announcing, and every viewer sees the stream listed and black. The reconnect
  added in v0.5.18 could not see it, because it watches the video element and the
  element was fine. KASTR now watches the track the encoder is actually using,
  and rebuilds when it dies.
- The Publish diagnostics were hiding this. They reported the capture rate by
  asking the video element for a *new* stream each time, which always answers
  30fps -- so a starved encoder looked perfectly healthy. They now report the
  state of the encoder's own track, plus whether its relay connection is
  established.

## v0.5.21

- **Fixes the black picture for good, and it was a name clash all along.** When
  two publishers claim one broadcast name, the newer one wins and the older is
  starved in silence: the relay sends it no subscriptions, so it encodes nothing,
  and every viewer sees the stream listed with a black picture. Nothing reports an
  error at any layer. Worse, being displaced is permanent -- the loser never
  recovers, even after the other publisher goes away.
  The guard added in v0.5.17 asked the relay which names were taken, but that
  answer can take fifteen seconds to arrive, so a source added just after launch
  was named against an empty list and the guard never fired. Now: a source named
  before the relay has answered is re-checked and renamed once it does, and a
  broadcast that is live, capturing happily, has encoded nothing at all, and whose
  name the relay says belongs to someone else, renames itself and republishes
  rather than staying invisible.
- The go-live check no longer counts your own broadcast as a conflict, which
  would have refused to put a stream back on air after stopping it.

## v0.5.20

- **Fixes the window opening small again.** v0.5.18 removed the fixed window
  size on the assumption the browser would restore an app window's position and
  size by itself. It does not, so every launch came up at some default -- worse
  than the fixed size it replaced. KASTR now records where the window is and
  hands it back on the next launch, maximized state included, falling back to
  maximized on a first run or if the saved position no longer fits any monitor.
- **The app can now report what it is doing.** Each page posts a snapshot of its
  own state -- what is publishing, what a viewer is receiving, what the encoder
  has produced -- to its own server, which keeps the latest one. Entirely local:
  the same loopback server that serves the page, nothing written to disk and
  nothing leaving the machine. It exists because several rounds of chasing a
  black picture were spent inferring what a page was doing from the outside,
  when the page already knew.

## v0.5.19

- **A broadcast that dies while its camera is fine now rebuilds itself.** Seen
  side by side on one relay: a broadcast that had been up ten minutes delivered
  nothing to anybody -- black in every viewer, zero bytes -- while a freshly
  published broadcast of the same camera through the same relay played normally.
  The camera was healthy throughout, so the reconnect added in v0.5.18 never
  fired: that watches the camera, and the camera was not what broke. KASTR now
  also watches what the encoder produces, and rebuilds the broadcast if it goes
  quiet for twenty seconds while the camera is still delivering.

## v0.5.18

- **A camera that drops its connection now reconnects.** UniFi cameras
  invalidate their RTSPS session after a while -- ffmpeg reports "the specified
  session has been invalidated" and exits. The video feed then ended *cleanly*,
  and only a hard error was being watched for, so nothing recovered: the source
  still looked present and every viewer went black. The feed ending, or simply
  going quiet for fifteen seconds, now rebuilds the connection, backing off if
  the camera is genuinely gone, and says what it is doing rather than leaving a
  silent gap.
- Reconnecting no longer re-interrogates the camera about its codec, which was
  three seconds of extra dead air each time.
- **The window opens maximized the first time and remembers where you put it
  after that.** Every launch had been pinned to the same size, which overrode
  the position and size the app had remembered, so moving or resizing it never
  stuck.
- **Publishing keeps running while the window is behind something.** Browsers
  throttle a window that is not in front to roughly one frame a second, and
  publishing a camera or file depends on the page being drawn -- measured 30 fps
  in front against 0.24 fps behind. For a tool meant to keep streaming while you
  work in another window, that was the wrong default.

## v0.5.17

- **Fixes the real cause of a stream that lists but plays black.** Two
  publishers can end up on the same broadcast name -- names are built from the
  machine name and the source, so two copies of the app, two people publishing
  the same camera, or one forgotten instance all land on the same one. Nothing
  reports an error: the relay keeps announcing the catalog while delivering no
  media, so a viewer lists the stream, subscribes, and gets a black picture and
  zero bytes. Observed exactly that, then watched it start playing the instant
  the duplicate was renamed away.
  Names were only ever checked against this browser -- its own sources, and the
  Publish page and Share panel comparing notes -- which cannot see a publisher
  in another process or on another machine. KASTR now watches what the relay has
  already announced and treats those names as taken, so adding a source that
  somebody else is already publishing quietly becomes `-2` instead of breaking
  both. If a name is claimed in the gap between adding a source and going live,
  it now says so instead of publishing into a silent conflict.

## v0.5.16

- The Publish page's diagnostics now report the encoder's own output -- frames,
  keyframes, bytes, whether it is running at all, and the rate frames are being
  captured at. Until now a slow or absent stream could only be inferred from
  what a viewer received, which cannot tell "nothing was encoded" apart from
  "nothing arrived". Worth knowing: the encoder deliberately does nothing until
  somebody is watching, because Media over QUIC only produces what is asked for.

## v0.5.15

- **Publishing no longer freezes when you switch tabs.** An RTSP or file source
  is published by capturing a video element, and a browser only produces frames
  from one while it is actually being drawn -- measured on a 1080p camera, 30 fps
  with the page in front and 0.24 fps behind. Switching to Watch to look at what
  you were publishing therefore froze it, which is the one thing anybody would
  do. Inactive tabs are now kept drawn but parked behind the active one instead
  of being taken off screen. Camera and screen sources were never affected: their
  frames come from the capture device, not from anything being drawn.
- **The Watch stats no longer claim frames are decoding when they might not be.**
  The counter labelled "frames decoded" is incremented as each chunk comes off
  the network, before the decoder ever sees it, so it climbs happily while
  nothing decodes -- and the panel then concluded "a blank picture must be a
  rendering problem", which is the opposite of the truth. It now reports "chunks
  received" for what that number is, adds a "picture" row that says whether the
  decoder is actually holding a frame, and says so plainly when chunks arrive
  but no picture does.

## v0.5.14

- **Launching KASTR now runs the copy you launched.** If something was already
  serving on its port, the app assumed it was another copy of itself and simply
  showed that window -- it decided this from a bare heartbeat reply, which any
  version answers identically. So a copy running from a source checkout could
  capture the launch of the real program, and the app reported a `-dev` version
  even though a released build had been started. The check now asks which build
  is there: the same one still gets the window (a second server on one browser
  profile could never open one anyway), and anything else is left alone while
  this build starts on a free port.
- Checking for a running copy no longer counts as a sign of life from it. The
  old check posted to the page heartbeat, so merely looking kept a windowless
  instance alive.

## v0.5.13

- **Fixes a stream showing as present but playing black.** The bandwidth saving
  added in v0.5.2 stops a stream downloading while its tile is scrolled out of
  view -- and it was applying that to the stream you had actually selected. On
  the Watch page the video sits below the fold in a short window, so arriving
  there gave a listed stream, a black pane, and a subscription that was never
  switched on at all. The selected stream is now always downloaded, wherever it
  is on the page. Other tiles in grid view still load lazily, but with a much
  larger margin so scrolling reaches a picture instead of a black square.
- RTSP history keeps the last 15 urls, and the field is labelled "Recently
  used" rather than counting what is in it.

## v0.5.12

- **An RTSP camera now actually plays on the Watch page.** It previewed on
  Publish and arrived as nothing on Watch: the catalog was there, a track and
  config were chosen, no error, and zero bytes. The cause was that an RTSP source
  built its encoder and never applied the encoder settings to it -- so it always
  ran on the library's defaults, which for a 4K camera means VP9 at 3840x2160,
  something no browser can encode in real time. Settings are now applied when the
  encoder is created, and the defaults are H.264 at 1080p rather than "let the
  library decide".
- **Oversized cameras are scaled down before the browser sees them.** A 4K frame
  copied straight through reached the browser fine but left it scaling 8.3
  megapixels per frame, which measured 1.0 fps against 18.3 fps for a 720p
  source. The bridge now does that scaling instead, on the GPU where there is
  one -- measured 25 fps at 1080p from the same 4K camera. Sources already within
  1920 wide are still passed through untouched, at no quality cost.
- **RTSP URLs are remembered.** Recently used ones appear in a list next to the
  field and as type-ahead suggestions, so a long camera URL only has to be
  entered once. There is a Forget button, because these often contain passwords.
- Those URLs are stored **only on the machine that used them**, in this app's own
  browser profile. They are not part of the program: copying KASTR to another
  computer does not carry them across, and nothing is written next to the
  executable.

## v0.5.11

- **RTSPS cameras work.** A `rtsps://` URL sat at "ready" and never went to air.
  ffmpeg's actual complaint was `Peer certificate failed verification` -- cameras
  like UniFi Protect present a self-signed certificate on their RTSPS port, and
  nothing could validate an IP address on a local network anyway. Verification is
  now off for RTSPS: the stream is still encrypted in transit, the camera just
  is not authenticated.
- **Camera video is no longer re-encoded when it does not need to be.** The
  bridge always re-encoded, which on a 4K camera ran at **0.30x real time** -- it
  could never keep up with a live feed at any resolution. Cameras already send
  H.264, so it is now repackaged instead: **1.15x real time** and a seventh of the
  data. A short probe on first connect checks the camera's codec, so anything
  that is not H.264 is still re-encoded as before.
- Cameras with several audio tracks, or none at all, no longer break the bridge.
- **The ON AIR badge no longer blinks to "off" every few seconds.** Rebuilding the
  source list reset each badge to a placeholder that only a later refresh filled
  in, and sharing between views triggered a rebuild every four seconds. The list
  is now only rebuilt when something actually changed, and never left showing a
  placeholder.
- **Sources shared from another view now appear in the right-hand pane**, not just
  in the source list. The tile cannot show the picture -- the video is being
  encoded in the other view and a stream cannot be decoded twice -- so it says
  where it is running instead.
- **"Audio: follows selection" is now a three-way switch**: follows selection,
  all streams, then manual. Hearing everything at once no longer means clicking
  the speaker on every row, and per-stream mute and levels still apply.

## v0.5.10

- **Mute and the volume sliders actually work now.** They have not since v0.5.4,
  and that was my doing. The streaming library turns out to have no volume
  control at all -- its audio pipeline takes a single on/off flag, and what looks
  like a volume setting only feeds that flag: zero means off, any other value
  means on at full loudness, with nothing in between. v0.5.4 stopped writing zero
  (to avoid tearing the audio connection down on every switch), which meant
  nothing was ever quiet again. KASTR now does its own mixing, so levels are real
  levels and a mute is silent while the stream stays connected -- so switching
  still does not drop sound. Where the audio pipeline cannot be reached, mute
  falls back to switching the stream off outright: being genuinely silent matters
  more than staying warm.
- The stats panel now reports which of those two it is using, and can finally
  read the audio state it used to say it "could not read".
- **The Autonomous Solutions logo is the way home**, and the Home button has been
  removed from the top bar since it did the same thing.

## v0.5.9

- **Anything shared from Watch now shows up on the Publish page too**, and the
  other way round. The Share dropdown and the Publish page are two live views of
  the same page, and each only knew about its own sources, so a camera started
  from Watch was invisible on Publish. Each view now announces what it is
  publishing and lists the others' sources alongside its own, marked with where
  they came from. The view that started a source still owns it -- stopping one
  from the other side asks its owner to do it, because only the view that opened
  a capture can close it cleanly.
- **Two views can no longer pick the same broadcast name.** Names were only
  deduplicated within a view, so Watch and Publish could both publish as
  `<machine>/camera.hang` and fight over it on the relay.
- **The Autonomous Solutions logo no longer leaves the app.** It was an ordinary
  link to the home page, so clicking it dropped out of the app shell and loaded
  the home page bare -- no tabs, and everything that was running torn down,
  which read as a different, older app. It now just brings the Home tab forward.
- **Home-page cards switch tabs instead of loading inside the Home tab**, which
  used to nest a second navigation bar inside the app and run the page twice.
- **The home page is no longer served from a stale cache.** A request for `/`
  skipped the no-caching header that every other page gets, so the browser held
  on to an old copy of it -- including across an upgrade. Tab pages are also
  stamped with the build now, so a new version never shows the old one's pages.

## v0.5.8

- **Fixes the version shown in the app being one behind.** v0.5.7 reported
  itself as v0.5.6 in the header and in these notes. When `VERSION` changed to
  mean "the build that shipped", the build kept bundling that file as-is -- and
  it is not updated until after the build succeeds, so each app was stamped with
  the previous number. The version is now generated from the build itself, so it
  cannot drift again.

## v0.5.7

- **Fixes v0.5.6 failing to start.** The new watchdog that stops a half of the
  app outliving the other half used `os.kill(pid, 0)` to ask "is the other half
  still alive?". That is the standard way to ask on Mac and Linux, but on
  Windows it does not ask anything -- it terminates the process. So the
  watchdog killed the very thing it was watching, a second after launch. It now
  waits on a proper process handle instead.

## v0.5.6

- **Fixes a crash on exit in v0.5.5.** Closing the app showed "Unhandled
  exception in script ... AttributeError: 'NoneType' object has no attribute
  'flush'". The Windows app is built as a windowed program and so has no
  console at all -- `sys.stdout` and `sys.stderr` are nothing, not files -- and
  the new shutdown path tried to flush them. Worse, it did that between the
  cleanup and the exit, so the error skipped the exit entirely: the one
  function whose job is to always end the process was the one thing that could
  stop it happening. Shutdown now ends the process from a `finally`, so nothing
  going wrong inside it can prevent the exit, and every write to a console that
  may not exist is guarded.

## v0.5.5

- **Relay stats is no longer a card on the home page.** The relay badge in the
  top right opens the same view from any page, and did it better -- the card
  opened a detached browser tab instead.
- **Closing the window now ends KASTR completely.** It used to be able to keep
  serving in the background, holding its port and its ffmpeg and relay
  processes -- which twice blocked a rebuild of its own .exe. Three causes: the
  "could not open its window" notice was a modal dialog that blocked forever
  behind other windows; shutdown ran on only one of the five ways out of the
  launcher, so quitting any other way left every child running; and nothing
  handled Ctrl+C or a shutdown request. There is now a single teardown that
  every exit goes through -- ffmpeg first, then the relay, then the server --
  each step time-limited, with a watchdog so shutdown itself cannot hang.
  Measured: window closed to fully exited in about a second.
- Shutdown also notices the browser's own profile lock disappearing, so a
  window opened by a second copy of Chrome no longer waits out a 2.5 minute
  timer before the server stops.
- **`VERSION` now names the build that shipped, not the next one.** It reads
  the same number as `BUILT_VERSION` and as the app itself, instead of sitting
  one ahead and looking like a mismatch. Building the second platform of a
  release takes `--keep-version`, which now does what its name suggests.
- **The release archive is written last.** It used to be zipped before code
  signing and before the macOS bundle got its camera and microphone usage
  strings, so the zip -- the copy that actually gets handed to people -- held
  an unsigned executable and a bundle that would have failed to capture,
  while the copy left in `dist/` was fine.
- **The archive only packs what it can vouch for.** A platform folder joins a
  release only if its `BUILT_VERSION` matches and its binary is actually
  there; anything else is named and skipped rather than shipped under a
  version it was not built for. The build prints what went in, per platform.
- **A release archive can grow but not silently shrink.** Rebuilding one
  platform can no longer replace a two-platform release with a one-platform
  one; that now stops the build and says what would have been lost
  (`--allow-shrink` if you mean it).
- Executable bits in the zip no longer depend on which machine zipped it, a
  failed archive no longer leaves a part-written file behind, and a build can
  no longer report success while quietly failing to record its own version.

## v0.5.4

- **Audio controls work again.** The master mute and the per-stream volume
  sliders were both being silently overridden. `@moq/watch` treats a volume of
  exactly 0 as a mute: it forces the element muted and tears down the audio
  subscription, and it then discards the next volume set and substitutes 0.5 of
  its own. Every value is now floored at -80 dB instead of 0 -- inaudible, but
  low enough that nothing is reinterpreted, so a mute stays a mute, a level
  stays where you put it, and the subscription stays warm so switching does not
  drop sound.
- **A mute button on every stream**, next to its level, so one noisy feed can be
  silenced without giving up its place or touching anything else. Sliding a
  muted stream back up unmutes it.
- **Publish is back on the top bar.**
- **Studio is gone.** It was Publish and Watch side by side, which is what the
  Watch page's Share panel now does in one window.
- **Share closes when you click away from it**, rather than only on the X.
  Whatever you put on air keeps running either way.
- **All publish settings** switches to the Publish tab instead of opening a
  second window, so nothing else you have running is disturbed.
- **Linux carries ffmpeg again.** RTSP ingest works on a Linux machine with
  nothing installed on it, the same as Windows. v0.5.3 shipped without it and
  fell back to whatever `ffmpeg` was on PATH.
- The bundled Linux ffmpeg is a static x86_64 GPL build from BtbN, the Linux
  provider ffmpeg.org links to; the GPL variant is required because RTSP ingest
  encodes with libx264. `fetch-helpers.py` pins one dated build and checks its
  SHA-256 before unpacking, so every machine that builds KASTR gets a
  byte-identical binary.
- Builds now archive themselves: one zip per release in `dist/archive/`,
  holding the Windows and Linux folders together, written after the build
  rather than by the next one. A KASTR left running no longer fails the build.

## v0.5.3

- **Share is now its own trimmed view.** The Share dropdown on Watch no longer
  embeds the whole Publish page. Encoder settings, the relay field, the preview
  tiles and the verbose status panel are gone; what is left is pick a source,
  name it, go live. "All publish settings" in the dropdown header still opens
  the full page.
- **Publish removed from the top bar.** It is reachable from the Home page and
  from the Share dropdown.
- Release notes added, viewable from the version in the masthead.

## v0.5.2

- **Watch: per-stream volume.** Every row has its own level, multiplied by the
  master slider, so several streams can be heard at different volumes.
- **Watch: Share dropdown** — publish without leaving the page. It is lazy, and
  closing it does not stop anything already on air.
- **Watch: prefix and latency target removed** from the toolbar; they are fixed
  at "everything" and 500 ms.
- **Bandwidth follows the window.** Grid tiles scrolled out of view stop
  downloading instead of decoding everything at once. When a catalog offers
  several renditions, the one matching the pane size is requested — no effect on
  KASTR's own streams, which publish a single rendition.
- **Publish: previews off by default**, which is what a publishing box wants.
- Version number added, shown in the masthead. Each build archives the previous
  one to `dist/archive/` and Windows builds moved to `dist/windows/`.

## v0.5.1

- **Watch: full screen per stream** — a button on each stream, or `F`. Fixed two
  bugs found while testing: the click's user activation was being discarded, so
  switching straight between full-screened streams was always refused, and the
  failure message was written where a once-a-second refresh immediately erased it.
- **Watch: expandable stats** — codec, resolution, frame rate, frames decoded,
  throughput, audio context state and the raw catalog, matching what the old
  upstream Watch page showed.
- Nav reordered to Publish / Watch / Studio; relay stats moved into the relay
  badge at top right; the app opens on Home.

## v0.5

First numbered build. Everything before this was unversioned.

- **Watch** (was Switcher): grid view by default, multi-source audio, keyboard
  switching, warm-audio gating so switching streams never drops sound.
- **Publish**: any mix of cameras, screen/window/tab, RTSP feeds and local files,
  each its own broadcast named after the machine. Sources can be added and
  removed while on air.
- **Relay**: hosts a MoQ relay on this machine with the bundled `moq-relay`.
- **RTSP ingest** through a bundled ffmpeg, with a built-in test pattern.
- **Studio**: Publish and Watch side by side.
- Tabbed shell so switching pages does not stop what is running.
- Windows and Linux builds, both self-contained.
