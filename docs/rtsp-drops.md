# Diagnosing an RTSP feed that "drops"

A native camera feed is an `ffmpeg | moq` pair supervised by KASTR. Every path that can restart
or kill that pair is attributable since 0.13.1. When a feed drops, collect three things on the
camera box and, if a viewer saw it, one on the viewer:

1. **On the box** (PowerShell, next to the running KASTR):

   ```bash
   .\KASTR.exe --diagnose drop.txt
   ```

   `drop.txt` has one `rtsp publish` line per feed:
   `running restarts sessionFails sessionKills nudges=viewer:N/noEcho:N/api:N lastNudgeWhy lastExit=<who> code <c> after <lived> s parked lastSession gen=N total=N since=…`,
   plus `instance`, `viewing` (feeds pulled by pages on this box) and `chatHub`.

2. **The launcher log**: `%LOCALAPPDATA%\ASI\KASTR\launch.log` (Linux: `~/.local/share/ASI/KASTR/launch.log`,
   Docker: `/data/state/launch.log`). Look for `rtsp nudge <broadcast> why=... restarts=... sessionFails=... sessionKills=...`
   and the `rtsp restore` / `relaunching` lines around the time of the drop.

3. **`/api/rtsp/list`** from the box itself (loopback only): `curl http://127.0.0.1:8000/api/rtsp/list`.

4. **On the viewer** that saw the drop: View › Log, copy the lines around the time (stall reports say
   "reported ... stalled"; hidden-tab teardown says "Hidden for 60 s").

Since 0.13.3 the launch.log also carries one line per pair generation: `rtsp pair <broadcast> gen=N start …` and
`… exit who= code= lived= restarts= sessionFails= sessionKills= last=<last stderr line>` — the timeline of every drop.
`restarts` forgets after 60 healthy seconds; `restartsTotal` and `gen` do not. `--diagnose` no longer needs `--port`.

## Reading the counters

| Pattern | Meaning | Row in ARCHITECTURE's restart table |
|---|---|---|
| `sessionKills` climbing, `parked: true`, `lastSession` says unauthorized / expired | the relay refused the token; the pair parks and re-mints | 2–5 |
| `sessionFails` climbing, `restarts` low, `lastSession` "session severed/closed" | relay bounce; moq reconnects by itself, viewers lose picture for the gap | soft |
| `restarts` climbing, `lastExit.who = ffmpeg`, `error` shows ffmpeg text | the camera side dropped the RTSP session (no `-reconnect` exists for RTSP; each hiccup is a pair restart) | 1 |
| `nudges.viewer` climbing | viewers reported the feed frozen (stall reports) | 8 |
| `nudges.noEcho` climbing | the relay stopped listing the path twice in a row while the pair was up (0.13.1 evidence rule) | 9 |
| `nudges.api` | a hand or the page's Keep/republish path | 6–7 |
| Share row says `offline — removed from grid (attempt N); retrying` | 0.14.0: `restarts` passed 5 with the pair down; the camera left the grid (seat kept) and returns ~5 s after the pair publishes again | eviction |
| nothing climbs, viewers still lose it | look at the viewer: a tab hidden > 60 s drops non-selected tiles until shown; a publisher-mode box never creates viewer tiles | viewer-side |

0.15.0: a feed belongs to one grid (`gridId`, Share-row picker); eviction and re-admission are per grid, and `__gridStates()` lists every grid's members/evicted. `restarts` resets to 0 after a pair has lived 60 s; `sessionFails` / `sessionKills` / `nudges` never reset.
