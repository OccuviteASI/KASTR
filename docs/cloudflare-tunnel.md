# KASTR through Cloudflare Tunnel (one name, one port)

Since 0.19.0 everything KASTR does can travel through the relay host's web port, so one Cloudflare Tunnel
hostname is enough: the page, the API, chat, files, recordings, updates, and the video itself.

## How it works

- The relay host's KASTR web port (8000 by default) answers `/relay` with a WebSocket pipe to its own relay.
- A relay address whose path is `/relay` (for example `https://kastr.example.com/relay`) is a **web relay**. Its
  KASTR API is that URL's origin, and its media rides WebSocket through the same port.
- A browser that reaches KASTR through a proxy (cloudflared adds `Cf-Connecting-IP`, `X-Forwarded-For`, ...) is
  handed `https://<the name it used>/relay` automatically.
- Anything that arrived through a proxy is treated as another device, even if the tunnel rewrites Host to
  `localhost`. Lockouts, bans and logs use the visitor's address (`Cf-Connecting-IP`), not the tunnel's.
- On the LAN nothing changes: direct QUIC on the relay port stays the fast path.

## Set it up

On the relay host (the machine that runs the relay):

1. Start the relay on the Relay page. It can stay bound to this machine only; the tunnel reaches it through the
   web port.
2. Install `cloudflared` and create a named tunnel:

   ```bash
   cloudflared tunnel login
   cloudflared tunnel create kastr
   cloudflared tunnel route dns kastr kastr.example.com
   ```

3. Point it at KASTR's http web port (`~/.cloudflared/config.yml`):

   ```yaml
   tunnel: kastr
   credentials-file: /path/to/<tunnel-id>.json
   ingress:
     - hostname: kastr.example.com
       service: http://localhost:8000
     - service: http_status:404
   ```

4. Run it: `cloudflared tunnel run kastr` (or install it as a service).

For a quick test without a domain: `cloudflared tunnel --url http://localhost:8000` prints a temporary
`https://<random>.trycloudflare.com` name.

The Relay page's "One port (Cloudflare Tunnel)" card shows the origin to give cloudflared, the addresses to hand
out, the last proxied visitor and the number of live relay pipes.

## Use it

| Who | Address |
|---|---|
| Browsers (phones, tablets, laptops) | `https://kastr.example.com/` |
| KASTR apps on other machines (relay address) | `https://kastr.example.com/relay` |
| RTSP cameras published from other machines | the same relay address |
| A spoke relay federating to this hub (Relay page, Federation) | `https://kastr.example.com/relay` + the federation code |
| Self-update of those apps | automatic: the update authority is the web relay's origin |

Browsers get the full client (camera, microphone, all video) because Cloudflare serves the name over https.

## Limits

- **WebSocket only.** A tunnel carries no UDP, so there is no QUIC/WebTransport through it. Expect a little more
  delay than on the LAN, and head-of-line blocking on a lossy link.
- **The hub cannot call a spoke behind a tunnel or NAT.** Since 0.20.0 the spoke holds one request at the hub
  instead, so a kick reaches it in about a second; since 0.21.0 the same held request carries the hub's "Update
  spokes now" command (Relay page, Federation card).
- **Cloudflare Access** in front of the name blocks the native clients (KASTR apps, the moq CLI inside KASTR, spoke
  relays), which cannot do the Access login. Use a bypass policy for the paths KASTR needs, or a service token.
- **Bandwidth.** Every viewer's video crosses the tunnel. Check your Cloudflare plan's terms for sustained video.
- Another reverse proxy that sends no forwarded headers: set `single_port = true` in kastr.ini so every remote page
  is handed the `/relay` address.

## Access codes matter here

An open relay (no access codes) trusts "the LAN". Through a tunnel that is everyone on the internet: anyone with the
name can list cameras, read chat, pull recordings and watch. Since 0.20.0 KASTR says so on the Relay page's One-port
card, in the launch log, and on every browser visitor's gate, but it does not refuse. Set viewer, publisher and admin
codes on the Relay page **and start the relay with "Require access codes"** — saved codes alone leave the relay open
(the room-code service only runs on a secured relay).

## Kicks and spokes behind a tunnel

A spoke registers with the hub only when its own relay runs **secured** (access codes required) and holds a hub
federation token. Since 0.21.5 a spoke that cannot register says why in launch.log and on its Relay page ("not registering
with the hub: this relay runs open …"); media still flows over the cluster link either way, but hub commands, ban fan-out
and the hub's spokes table need the registration.

Since 0.20.0 a spoke keeps one request held at the hub for ban changes, so a kick on the hub reaches a spoke behind a
tunnel or NAT in about a second (measured 0–2 s on the rig), and a ban cleared on the hub is lifted on the spokes.

## A browser stuck on an old build

Browser clients keep an offline shell in a service worker (since 0.20.0). A phone that visited during 0.20.0–0.21.3
could keep showing that build's masthead and version after the host updated, reloading every few seconds
("KASTR on the host updated to … — reloading"): the old worker served the old masthead script from its cache, and
its replacement never finished installing. Since 0.21.4 the host stamps every response with `X-KASTR-Version`, a
worker that sees a newer version stands aside, and the page purges a worker that still serves an old masthead. A
stuck browser heals on its first visit once the host runs 0.21.4. To clear one by hand before that: on an iPhone,
Settings → Safari → Advanced → Website Data → delete the host's entry; on a desktop browser, clear site data for the
host (application storage, not just the cache).

## Cloudflare and error pages

Cloudflare replaces an origin's 502/504 with its own text page. KASTR 0.20.0 never answers 502 (503 passes through),
and an open relay answers its room-code endpoints with a 200 "open" shape instead of an error, so `watch.html` and
the page behave the same behind Cloudflare as on the LAN.

## Bursts from a looping client (0.21.8)

Every viewer session appearing and vanishing together on the tunnel host's relay stats, with a spike of a few
hundred Mbit/s every couple of seconds, is a client re-subscribing to everything at once. Two loops can do that from
a web client: the fMP4 fallback player (a browser without WebCodecs, or a codec it cannot play) retrying, and the
library reconnecting a `/relay` WebSocket that keeps dying. Both are bounded now (back-off, a stop, a 429 for a
looping fallback viewer, a 20 s pause after six reconnects in a minute) and both leave a line in the host's
launch.log (`watch: fallback viewer … is looping`, `relay pipe: … short pipes`, `relay auth: … opened N sessions in
60 s`); `/api/relay/health` carries `auth.churn`.

## Through the tunnel in 0.21.7: audio budgets and the download

- A page whose relay is a web relay (`…/relay` — every tunnel page) rides fixed budgets: `delay 150 ms + buffer 800 ms`
  on the spotlit tile, the rail and composites, instead of the library's min-RTT estimate that shrank the budget under
  the jitter. Together with the audio `maxAge` floor in the vendored player (see RELEASES 0.21.7) the clipping heard from
  every tunnel viewer is gone; the latency badge shows `· skips A/V` when the player dropped media in the last 60 s.
- More → Settings → About on a tunnel page lists the Windows and Linux install zips; the host assembles the zip on the
  first click (10–20 s, "Preparing the download on the host…") and the browser downloads `KASTR-<plat>-v<ver>.zip`. The
  tunnel's certificate is trusted, so the download is allowed; a LAN https page without the local CA installed has its
  download blocked by Chromium as insecure — install the CA or use the tunnel page.
- Its Relay dropdown reads "Relay host: KASTR vX — this page follows it" (same origin, no port).
- A viewer on the tunnel page who opens an on-demand camera that lives on another spoke of the same hub sees the low copy
  at once; the demand travels tunnel host → hub → that spoke over the hub's command channel.

## Verified for real (2026-09-30, kastr.madlabs.app, KASTR 0.21.5, SECURED relay)

The half 0.20.0 left open. Access codes required on the relay "kastr-test" behind the tunnel:

- Publisher, viewer and admin joined with their codes and got their roles; both state links connected over the tunnel.
- The viewer listed both members, found the camera, decoded the tile and read the latency stamp; the encoder counted frames.
- Chat crossed through the hub. An admin stop reached the publisher in 0.1 s; an admin kick sent it back to the gate in
  0.2 s while the viewer — behind the same Cloudflare address — stayed joined with its state link up.
- moq CLI publish and subscribe through `https://kastr.madlabs.app/relay` over WebSocket, valid H.264 back.
- Found: an admin's chat delete left the line on every screen in rooms whose chat lives on the window (fixed in 0.21.6).
- A plain-Python client is refused by Cloudflare's browser check (error 1010); curl and browsers pass. Token minting
  needs a real host slug (`web-<8 hex>-<4 hex>`), otherwise "bad host".

## Verified for real (2026-09-28, kastr.madlabs.app, KASTR 0.19.0, open relay)

- Page served through the tunnel is handed `https://kastr.madlabs.app/relay`; `/relay` upgrade → the relay's 101;
  every host control 403; `/api/instance` and `/api/rtsp/list` redacted.
- Edge (Playwright): join, publish a fake camera, view (tile decodes), chat; **glass-to-glass 496–504 ms** measured by
  the latency stamp between two browsers through Cloudflare's edge.
- moq CLI: publish and subscribe through `https://kastr.madlabs.app/relay` over WebSocket, valid H.264 back.
- Found: the relay ran open (`/api/auth` came back as Cloudflare's `error code: 502`), which led to the two fixes above.
  The secured half (admin stop and kick through the tunnel) is verified on the rig's stand-in and waits for the host
  to run with access codes required.

## Verified (2026-09-25, rig)

A local stand-in for cloudflared (one TLS port, cloudflared's headers, Host rewritten to `localhost`): Edge and
Firefox joined, published a camera, watched it, chatted, and an admin stop and kick worked. Native publish and
subscribe with the moq CLI, and a spoke relay federating to the hub (token, media across the link, ban pull), all
used the web port only. Every host control answered 403 through the tunnel, and a wrong-code lockout hit one visitor
only. A real Cloudflare tunnel was not used, because it would publish the build machine.
