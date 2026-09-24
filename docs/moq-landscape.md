# MoQ landscape, September 2026 — what other stacks do that KASTR could use

Read-only research done for v0.15.0 (2026-09-23). Nothing here is implemented yet; the ranked list at the end is the
backlog. Primary sources are linked; two items could not be verified and are marked.

## MediaMTX (bluenviron)

- MoQ is shipping upstream: publish and read over WebTransport (HTTP/3, port 8892) and raw QUIC (8893), negotiating
  IETF drafts 16–19 with the **MSF catalog + LOC container** — the IETF track, not the `hang`/`moq-lite` stack KASTR
  uses. A `moq-cli` push into MediaMTX failed on an unknown message type (moq-dev/moq#3759), so the two are not
  wire-compatible today. https://mediamtx.org/docs/publish/moq-clients · https://mediamtx.org/docs/read/moq
- Protocol matrix in one binary: RTSP, RTMP, SRT, WebRTC (WHIP/WHEP), LL-HLS, MPEG-TS, MoQ; any-to-any; H.265, AV1,
  FLAC, G.711. https://github.com/bluenviron/mediamtx
- **On-demand ingestion**: `sourceOnDemand` / `runOnDemand` pull an RTSP source or spawn a command only when a reader
  appears; `sourceOnDemandStartTimeout` (10 s), `sourceOnDemandCloseAfter` (10 s idle), `runOnDemandRestart`.
  https://mediamtx.org/docs/features/on-demand-publishing
- Twelve lifecycle hooks (`runOnReady/NotReady`, `runOnRead/Unread`, `runOnRecordSegmentCreate/Complete`, …) with
  `MTX_PATH`, `MTX_SOURCE_TYPE`, `MTX_READER_ID`, `MTX_SEGMENT_PATH` in the environment. https://mediamtx.org/docs/features/hooks
- Recording to fMP4/MPEG-TS segments with `recordSegmentDuration` / `recordDeleteAfter`, and a playback server:
  `GET /list?path&start&end` and `GET /get?path&start&duration&format=mp4` serve a time range straight into a `<video>`.
  https://mediamtx.org/docs/features/playback
- Ops: Prometheus `/metrics`, pprof, hot reload, JWT via JWKS with a permissions claim, `maxReaders`, `fallback` path,
  RTSP `rtspTransport: automatic|tcp|udp`, `readTimeout 10s`, `writeQueueSize 512`.
- WINK's production fork lesson: a four-transport fallback (WebTransport raw → WebTransport fMP4/MSE → WebSocket fMP4)
  reached every browser for traffic-camera deployments at 200–300 ms.
  https://www.wink.co/documentation/WINK-MoQ-Implementation-Analysis-2025.php · https://github.com/winkmichael/mediamtx-moq

## MainStreaming

- Joined the **OpenMOQ Software Consortium** (2026-07-31), committing engineers to open-source ingest, relay and playback.
  https://www.opensourceforu.com/2026/07/mainstreaming-joins-openmoq-to-build-open-source-media-over-quic/
- OpenMOQ's relay is **moqx** (moxygen-based, draft-18, `MoQForwarder` fan-out + `MoqxCache`, metrics). https://github.com/openmoq/moqx
- **Not verified**: any MainStreaming-authored IETF draft, blog post, interop result or MoQ product beyond the announcement.

## moq-dev (kixelated) — KASTR's own stack moved

- `moq-relay 0.15.0` + `moq-cli 0.12.0`: **subscriber latency-budget enforcement** and `--latency-max` cache retention,
  WebTransport for browser peers with WebSocket fallback fixes, **mDNS LAN mesh** (`[cluster.lan]` with an optional
  shared secret), certificate-fingerprint peer identity, `--auth-api-mode proxy` (the relay asks an HTTP API per
  session), per-core QUIC workers, `/metrics`, qlog, archive recording objects. (Release dates rendered ambiguously in the
  fetch — verify before pinning.) https://github.com/moq-dev/moq/releases
- `hang` catalog breaking changes: `timeline` → `archive {track, timescale, durationMax, wall, replay?, store?}`, root
  `clock {wall, timescale}`, container kinds `legacy|cmaf|loc`, renditions may point at another `broadcast` (transcoder
  ladders without republishing), `jitter`, stalled-rendition flag, 64-rendition cap, catalog updates as full JSON then
  Merge-Patch. https://github.com/moq-dev/moq/pull/3612 · https://doc.moq.dev/concept/layer/hang
- `moq-lite` knobs: per-subscription **priority 0–255**, group **order** (newest-first live / oldest-first catch-up),
  **max age** on the media timeline (0 = live edge only); no subgroups — one track per SVC layer.
  https://doc.moq.dev/concept/layer/moq-lite
- Clustering: static `connect`, gossip `mesh`, `[cluster.lan]` mDNS; mTLS / JWT / shared token between relays; hop lists
  for loop detection; retry-forever with capped backoff. https://github.com/moq-dev/moq/blob/main/doc/bin/relay/cluster.md

## Standards and the rest

- IETF: `draft-ietf-moq-transport-21` (2026-09-08), IESG submission milestone December 2026; **MSF-01 replaces WARP**,
  **LOC-02**; -21 has FETCH / joining fetch, PUBLISH, SUBSCRIBE_NAMESPACE, REQUEST_UPDATE, TRACK_STATUS, delivery
  timeouts, MAX_CACHE_DURATION — and **no keyframe-request primitive**. https://datatracker.ietf.org/doc/draft-ietf-moq-transport/
- Cloudflare MoQ relays in 330+ cities, provisioning API with separate publish/subscribe JWTs, Durable Objects for origin
  discovery, free beta. https://blog.cloudflare.com/moq-relays/
- Meta: moxygen (C++ relay + cache, 50-scenario conformance suite) and moq-encoder-player (playback-rate latency control,
  `(groupId, objId)` jitter buffer, drop-to-next-keyframe, latency overlay pixel stamping).
  https://github.com/facebookexperimental/moxygen · https://github.com/facebookexperimental/moq-encoder-player
- Interop: eleven vendors at NAB 2026; Safari / iOS 26.4 shipped WebTransport (April 2026).

## Ranked backlog for KASTR

| # | Idea | Why | Effort | Area |
|---|---|---|---|---|
| 1 | Adopt moq-relay 0.15 / moq-cli 0.12 and re-tune `latencyMax` | relay-enforced subscriber latency budgets are the stall/eviction problem KASTR solves client-side; needs the vendored `@moq/*` update for the `timeline→archive` catalog break | M | relay bundle, state tracks, vendored JS |
| 2 | Per-subscription priority + max-age | audio above video, grid cells max-age 0 (live edge), spotlight higher — a cheap latency win under congestion | S | viewer/publisher |
| 3 | On-demand RTSP ingestion (MediaMTX `sourceOnDemand`) | start the ffmpeg→moq pair when the first viewer subscribes, stop after an idle timeout; saves CPU and bandwidth on many-camera rigs | M | RTSP bridge |
| 4 | mDNS LAN mesh for same-site spokes | replaces hand-pasted federation codes on one site; keep hub/spoke JWT for the WAN | M | Relay page, federation |
| 5 | Simulcast ladder via `broadcast`-referencing renditions | publish the cheap 15 fps monitor encode as a rendition; grid cells pick low, spotlight picks full | M | publisher, grid |
| 6 | Recording via hang `archive` + a `/list`/`/get` time-range API | replaces stage-only recording with a host-side segment store the Files panel can fetch by time | L | media, files |
| 7 | WebSocket fMP4 fallback (WINK pattern) | phones/kiosks without WebTransport; KASTR already has `/stream?t=` fMP4 + MSE to reuse | M | phones, HTTPS |
| 8 | Hooks (`runOnReady/NotReady/Read`) | fire a command on feed up/down and viewer join for external alerting | S | RTSP bridge, `--diagnose` |
| 9 | Prometheus `/metrics` passthrough + health dashboard | relay 0.15 counters plus per-pair `gen/restartsTotal` on the Relay page | S | Relay page |
| 10 | `--auth-api-mode proxy` | the relay asks KASTR's `/api/auth` per session instead of pre-minted tokens; central revocation and role-shaped grants | M | auth |
| 11 | Certificate-fingerprint peer identity for spoke↔hub | replaces 30-day tokens between relays | S–M | federation |
| 12 | Latency overlay pixel stamp (Meta) | opt-in glass-to-glass latency measurement in the viewer | S | diagnostics |
