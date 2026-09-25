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
- **Ban nudges cannot reach a spoke behind a tunnel or NAT.** The spoke pulls the hub's bans on every federation
  tick (about every 10 minutes) and at relay start, so a kick reaches it within that window.
- **Cloudflare Access** in front of the name blocks the native clients (KASTR apps, the moq CLI inside KASTR, spoke
  relays), which cannot do the Access login. Use a bypass policy for the paths KASTR needs, or a service token.
- **Bandwidth.** Every viewer's video crosses the tunnel. Check your Cloudflare plan's terms for sustained video.
- Another reverse proxy that sends no forwarded headers: set `single_port = true` in kastr.ini so every remote page
  is handed the `/relay` address.

## Verified (2026-09-25, rig)

A local stand-in for cloudflared (one TLS port, cloudflared's headers, Host rewritten to `localhost`): Edge and
Firefox joined, published a camera, watched it, chatted, and an admin stop and kick worked. Native publish and
subscribe with the moq CLI, and a spoke relay federating to the hub (token, media across the link, ban pull), all
used the web port only. Every host control answered 403 through the tunnel, and a wrong-code lockout hit one visitor
only. A real Cloudflare tunnel was not used, because it would publish the build machine.
