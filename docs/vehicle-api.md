# KASTR vehicle API: share a vehicle's cameras without a room code

Since 0.21.63 a vehicle can create a KASTR room and publish its cameras into it with one HTTP POST and the `moq`
command-line tool. It does not need a room code or an access code: it uses its own **vehicle key**.

The vehicle only makes outbound connections. That covers a cellular link behind NAT: an HTTP POST to the relay's
token service (TCP, relay port + 1, normally 4444) and QUIC to the relay (UDP 4443, the same port spokes use).

## 1. Get a vehicle key (once per vehicle)

On the **hub's** Relay page, open the **Vehicles** card, type the vehicle's name (for example `Vehicle 12`) and press
**Add vehicle**. The key appears **once**:

```
kv-3f9a01bc-<32 characters>
```

Copy it into the vehicle's configuration. The hub keeps only a hash of it, so it cannot be shown again. If it is
lost, **Revoke** or **Delete** the vehicle and add it again. A key can:

- create a room (a plain room, with no code) or join an existing one, and
- publish under its own path in that room.

A key cannot watch anything and has no admin rights. Keys are made on the hub only; every relay federated with the hub
accepts them, because a spoke asks the hub.

The relay must be **secured** (Relay page, Server, *Require access codes*), because the token service runs only then.

## 2. Ask for a token

Send the POST to the relay the vehicle will publish to (the hub, or the spoke nearest the vehicle):

```bash
curl -s -X POST http://RELAY-ADDRESS:4444/api/vehicle \
  -H "Content-Type: application/json" \
  -d '{"key":"kv-3f9a01bc-<secret>","room":"vehicle-12"}'
```

Request body:

| field      | required | meaning |
|------------|----------|---------|
| `key`      | yes      | the vehicle key |
| `room`     | yes      | room name: lowercase letters, digits and `-`, at most 32 (not `main`, the Lobby) |
| `name`     | no       | display name for this call (defaults to the name the key was made with) |
| `roomCode` | no       | needed only to publish into a room someone else **locked** |

If the room does not exist, it is created. If it exists and is not locked, the vehicle joins it.

Reply (`200`):

```json
{
  "ok": true,
  "room": "vehicle-12",
  "host": "vehicle-12-3f9a",
  "name": "Vehicle 12",
  "op": "vehicle",
  "prefix": "vehicle-12/vehicle-12-3f9a/vehicle/",
  "relay": "http://RELAY-ADDRESS:4443/",
  "jwt": "<token>",
  "connect": "http://RELAY-ADDRESS:4443/?jwt=<token>",
  "exp": 1760400000,
  "refreshEvery": 300,
  "roomTtl": 600,
  "created": true
}
```

- `connect` is the URL to give `moq --connect`. It uses `http://` on purpose: `moq` first fetches the relay's
  self-signed certificate fingerprint over HTTP on that port, then publishes over QUIC.
- `prefix` is where this vehicle may publish. Every camera is one broadcast under it, named
  `<prefix><camera>.hang`, for example `vehicle-12/vehicle-12-3f9a/vehicle/front.hang`. The relay rejects anything
  outside the prefix.
- `host` is derived from the vehicle's name plus the first four characters of its key id. It stays the same on every
  call, so the vehicle shows in KASTR as one participant.
- `exp` is when the token expires (Unix seconds, 24 hours after the call).
- `created` is `true` when this call created the room.

When KASTR reaches the relay through a Cloudflare Tunnel or another web proxy (one HTTPS name, no QUIC), POST to
`https://NAME/api/vehicle` instead. The reply's `relay` is then `https://NAME/relay`, the web relay that carries media
over WebSocket.

## 3. Publish each camera

Run one `ffmpeg | moq` pair per camera, fed from the camera's RTSP stream. This is the same command KASTR's own camera
publisher runs:

```bash
CONNECT='<connect from the reply>'
PREFIX='<prefix from the reply>'

ffmpeg -hide_banner -loglevel error \
  -rtsp_transport tcp -timeout 10000000 -fflags nobuffer -flags low_delay \
  -i "rtsp://CAMERA-ADDRESS/stream" \
  -map 0:v:0 -map "0:a:0?" -c:v copy -c:a aac -b:a 128k -ac 2 \
  -f mpegts -pes_payload_size 0 - \
| moq --log-level warn --backoff-timeout 10s --quic-idle-timeout 15s \
    --connect "$CONNECT" \
    --broadcast "${PREFIX}front.hang" \
    import --max-age 5s ts
```

- Use `moq` 0.14 (moq-cli; KASTR bundles the same build).
- `-c:v copy` passes H.264 through without re-encoding. For a camera that sends H.265, or one with non-square pixels,
  encode instead: `-c:v libx264 -preset veryfast -tune zerolatency -profile:v main -pix_fmt yuv420p -b:v 3M -g 60`.
- No audio: replace `-map "0:a:0?" -c:a aac -b:a 128k -ac 2` with `-an`.
- `rtsps://` cameras with self-signed certificates: add `-tls_verify 0` before `-i`.
- Give each camera its own name (`front.hang`, `rear.hang`, `cab.hang`, ...). Viewers see one tile per camera under
  the vehicle's name.

## 4. Keep the room open (refresh every 5 minutes)

A vehicle's room is a plain room: it **closes 10 minutes after its last use**. Each POST to `/api/vehicle` counts as
a use, so:

- **POST again every 5 minutes** (`refreshEvery`) with the same key and room, while the cameras are running.
- The token lasts 24 hours. You do **not** need to restart `moq` after each refresh. Keep publishing with the token
  you have, and restart the `moq` processes with the new `connect` only when the old token is close to `exp` (for
  example, less than an hour left). The relay also gives a running session an hour of grace after `exp`.
- If the vehicle stops calling, the room closes about 10 minutes later and drops out of everyone's room list.
  Publishing again later creates it again.

Every KASTR viewer in the room sees the cameras as soon as `moq` connects.

## Errors

| status | `error` | meaning / what to do |
|--------|---------|----------------------|
| 400 | `bad room name ...` | room is not lowercase letters, digits and `-` (at most 32) |
| 403 | `a vehicle key is required ...` | no `key` in the body |
| 403 | `wrong vehicle key` | the key is not one of the hub's keys. **Counts toward the lockout**, like a wrong access code |
| 403 | `this vehicle key was revoked` | revoked on the hub's Relay page: ask for a new key. Does not count toward the lockout |
| 403 | `the Lobby takes no publishers` | `main` is the Lobby: use another room name |
| 403 | `this room is locked -- send its room code as roomCode` | someone locked the room: send `roomCode`, or use another name |
| 403 | `wrong room code` | the `roomCode` is wrong (counts toward the lockout) |
| 403 | `removed from this room by an admin` | an admin removed this vehicle from the room; `until` says when that ends |
| 429 | `too many attempts -- try again in N s` | 5 wrong keys or codes within a minute from this address. Wait `retryAfter` seconds (30 s at first, doubling up to 10 min) |
| 503 | `the hub could not be asked ...` / `the hub is unreachable ...` (`hubDown: true`) | a spoke cannot reach its hub. Keep publishing with the token you already have and try again in a minute |
| 503 | `this relay has no access codes ...` | the relay is not secured (see step 1) |

`moq` itself retries a lost connection for 10 seconds (`--backoff-timeout 10s`) and then exits. Run it under a
supervisor that restarts it, and refresh the token first if the old one is near `exp`.

## Security notes

- The key is the vehicle's credential. Keep it out of logs and URLs. KASTR never logs it and stores only a salted
  PBKDF2 hash.
- A token from `/api/vehicle` can publish only under its own `prefix` in the room, plus the vehicle's presence (so
  room lists count it). It cannot subscribe to the room.
- Revoking a key stops new tokens straight away. A token already issued keeps working until it expires (at most a
  day). To cut a vehicle off at once, remove it from the room as an admin, or rotate the relay's keys on the Relay
  page.
