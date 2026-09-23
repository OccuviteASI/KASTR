# KASTR in a container (headless Linux box)

*0.13.1.* A `Dockerfile`, `docker-compose.yml`, `docker-build.sh` and
`docker/entrypoint.sh` turn the WSL-built Linux binary into an image for a
headless relay or publisher box -- a robot's Linux PC, a VM in a rack, a cloud
host -- that keeps itself current over the internet, either by following its
hub's KASTR version (the same in-app update every desktop runs) or by pulling
a newer image.

## What the image is

The image **wraps `dist/linux/KASTR` as built** -- nothing is compiled in
Docker and no network is used at build time. One Linux artifact per release,
byte-identical (same sha256) to the one in the fleet feed and the release zip.
Base image `ubuntu:26.04`: the binary is built on Ubuntu 26.04 and is
dynamically linked against its glibc 2.43, so an older base refuses to run
it. Runtime packages: `ca-certificates`, `curl` (healthcheck), `tzdata`.

Inside the image:

| Path | What |
|---|---|
| `/opt/kastr/KASTR` | the Linux binary (ffmpeg, moq, moq-relay, the web UI inside) |
| `/opt/kastr/BUILT_VERSION` | the version it carries |
| `/opt/kastr/updates/windows/KASTR.exe`, `updates/macos/KASTR`, `latest.json` | the other platforms' binaries, so a container that is somebody's hub can update Windows and Mac clients too (present when `dist/updates` existed at build time; the Linux copy and the Chrome zips are left out, see `.dockerignore`) |
| `/entrypoint.sh` | seeds the volume and runs the relaunch loop (below) |
| `/data` (volume) | `app/` the RUNNING binary + `kastr.ini` + feed; `state/` the launcher's state |

Environment baked in: `KASTR_CONTAINER=1` (a requested relaunch exits with
code 75 instead of spawning a child), `KASTR_STATE_DIR=/data/state` (the
launcher's state directory), `KASTR_PORT=8000`.

## Prerequisites

- **A Linux host** with Docker Engine (or Podman with the compose plugin).
  `docker-compose.yml` uses `network_mode: host`, which is what a relay
  needs -- QUIC on UDP 4443 unmangled, the box's real LAN IPs advertised,
  4444/4445/8000/8443 alongside -- and Docker Desktop on Windows/macOS puts
  "host" inside its own VM, so those work for a build and a smoke, not for a
  relay people connect to.
- **To build:** the machine that produced `dist/linux` (WSL Ubuntu 26.04 with
  Docker Engine installed, or Docker Desktop with WSL integration). The repo
  is reachable there as `/mnt/c/Users/KentonJeffery/Claude/KASTR`.
- A registry account (GHCR or Docker Hub) only if boxes should update by
  `docker compose pull`; the in-app path needs none.

## Build

1. On WSL, the normal Linux build of the release: `python build.py
   --keep-version --publish` (VERSION set by hand first; Windows built
   before it, so `dist/updates/windows/KASTR.exe` is fresh).
2. Then, still on WSL:

   ```bash
   ./docker-build.sh                              # -> kastr:<VERSION>, kastr:latest
   ./docker-build.sh --push ghcr.io/<you>/kastr   # also retag + push both tags
   ```

   The script refuses when `dist/linux/BUILT_VERSION` is not `VERSION`
   (an old binary must not get the new tag) and notes a missing or stale
   `dist/updates`. Build context is tiny: `.dockerignore` lets only
   `dist/linux/KASTR`, `dist/linux/BUILT_VERSION`, `dist/updates/{windows,
   macos,latest.json}` and `docker/` through.

`build.py` itself prints a reminder after every Linux build that the image is
now stale (`check_release_contents`).

## Run

```bash
docker compose up -d                                       # kastr:local
KASTR_IMAGE=ghcr.io/<you>/kastr:0.13.1 docker compose up -d
docker compose logs -f
```

or without compose (smoke on any Docker, bridge networking is fine for the
web UI only):

```bash
docker run --rm -e KASTR_MODE=viewer -p 18000:8000 kastr:0.13.1
curl -s http://127.0.0.1:18000/api/instance      # {"app": "KASTR", "version": ..., "platform": "linux", ...}
```

Extra arguments after the image name go to KASTR (`docker run --rm
kastr:0.13.1 --diagnose /dev/stdout`).

### Environment (first-run defaults)

| Variable | Default | Goes to |
|---|---|---|
| `KASTR_MODE` | `relay` | `mode =` in `kastr.ini`: `viewer`, `publisher`, `relay`, `publisher-relay`. `relay` autostarts the bundled moq-relay on 4443 |
| `KASTR_RELAY` | `http://127.0.0.1:4443` | `relay =` -- the relay the pages use and, when it is another machine, the version authority the box follows |
| `KASTR_PORT` | `8000` | `--port` of the web UI (also the healthcheck) |
| `KASTR_UPDATE` | `on` | `update =`: `off` disables the in-app update (registry pulls only) |
| `KASTR_IMAGE` | `kastr:local` | compose only: which image to run |
| `TZ` | `UTC` | log timestamps |

`KASTR_MODE`, `KASTR_RELAY` and `KASTR_UPDATE` are written into
`/data/app/kastr.ini` **once**, on the first start with an empty volume. After
that the Relay page (`/api/mode`, `/api/ini`) edits that same file, exactly as
on a desktop; changing the compose environment does nothing until you delete
`kastr.ini` in the volume (or edit it: `docker compose exec kastr vi
/data/app/kastr.ini`, then `docker compose restart`). `host = 0.0.0.0` is
always written.

### Ports (host networking = the box's own ports)

| Port | Use |
|---|---|
| 8000/tcp | web UI + API (`/api/instance`, `/api/update/*`) |
| 8443/tcp | HTTPS UI for phones (`[web.https]`, when enabled) |
| 4443/udp + tcp | moq-relay: QUIC (WebTransport) and its TCP/WebSocket fallback |
| 4444/tcp | token minter (secured relays) |
| 4445/tcp | wss relay listener |

### Volume

`kastr-data:/data` holds everything that must outlive the container:

```
/data/app/KASTR          the binary that RUNS (seeded from the image, replaced by in-app updates)
/data/app/IMAGE_VERSION  version of the image that last seeded it
/data/app/kastr.ini      the config (written once, then owned by the UI)
/data/app/updates/       feed for other platforms (copied from the image)
/data/state/             launch.log, update-check.json, relay-auth.json, rtsp-feeds.json, TLS CA, ...
```

Delete the volume (`docker compose down -v`) for a factory reset.

## Updates over the internet -- two paths

**(a) In-app, following the hub.** With `KASTR_RELAY` pointing at another
machine's relay, the container's KASTR does what every desktop does: it asks
that host's `/api/instance` at launch and hourly, downloads
`/api/update/binary` when the versions differ, verifies size + sha256 against
`/api/update/manifest`, swaps `/data/app/KASTR` (the old one is renamed
`KASTR.old-<ts>`) and asks to relaunch. Under `KASTR_CONTAINER=1` that
relaunch is **exit code 75**; the entrypoint loop sees it and starts
`/data/app/KASTR` again with `KASTR_UPDATED=1` (sweeps `.old-*`, skips one
update check). Nothing is pulled, no downtime beyond the restart, and the
binary lives in the volume so `docker compose restart` keeps it. Log lines:
`KASTR: updating v0.13.0 -> v0.13.1 from http://hub:8000 ...` then
`[kastr-entrypoint] KASTR exited 75 (relaunch requested ...)`.

Two consequences worth knowing: a `docker compose pull` of an OLDER image does
not roll the box back (the entrypoint only re-seeds when the image is NEWER
than `IMAGE_VERSION`), and a newer image always wins over the volume's copy
(re-seed), after which the in-app check catches up again if the hub is newer
still.

**(b) Registry pull.** Build and push a new image per release
(`./docker-build.sh --push <registry/name>`), and on the box:

```bash
docker compose pull && docker compose up -d
```

The entrypoint compares the image's `BUILT_VERSION` with the volume's
`IMAGE_VERSION` (`sort -V`), re-seeds `/data/app/KASTR` and the feed when the
image is newer, and writes the new marker. `kastr.ini` and `/data/state` are
untouched. This is the path for a box that is itself the hub (its relay is
`127.0.0.1`, so nobody is its authority) or that has `KASTR_UPDATE=off`.

The release ritual therefore ends with: Windows build -> WSL build
(`--keep-version --publish`) -> [Mac build + `--publish-only`, see MACOS.md]
-> `./docker-build.sh --push ...` on WSL -> `docker compose pull && docker
compose up -d` on hubs; spokes follow their hub by themselves.

## Troubleshooting

| Symptom | Look at |
|---|---|
| `docker compose ps` shows `unhealthy` | the healthcheck is `curl -fsS http://127.0.0.1:$KASTR_PORT/api/instance \| grep '"app": "KASTR"'`; `docker compose logs` for a bind error (`host` port taken? another KASTR on the box?) |
| container restarts in a loop | `docker compose logs --tail 200`: the entrypoint prints the exit code; the launcher's own log is `/data/state/launch.log` (`docker compose exec kastr tail -50 /data/state/launch.log`) |
| `[kastr-entrypoint] KASTR exited 75` repeats forever | the binary keeps asking to relaunch -- check `/data/state/update-check.json` and `launch.log`; `KASTR_UPDATE=off` + delete `kastr.ini` to stop the update path while diagnosing |
| the box never picks up the hub's version | `relay =` in `/data/app/kastr.ini` must name the hub (not 127.0.0.1); `curl http://<hub>:8000/api/update/manifest` from the box must list `linux`; `/data/state/update-check.json` holds the last verdict |
| `docker compose pull` did not change the binary | the pulled image is not newer than `IMAGE_VERSION`; see the log line `keeping /data/app/KASTR (...)` |
| no camera/browser | expected: the container is headless (`--no-browser`); open `http://<box>:8000` from a desktop Chrome |
| the binary aborts with a glibc error | the image base is wrong (must be `ubuntu:26.04`, matching the WSL build host) |
| `network_mode: host` warnings on Docker Desktop | build and smoke there, run on a Linux host |

Test the entrypoint logic without Docker: `KASTR_IMAGE_DIR=... KASTR_APP_DIR=...
KASTR_STATE_DIR=... docker/entrypoint.sh` runs against any directories, with
a stub `KASTR` script standing in for the binary (the release smoke does).

## Not done / deferred

- A `builder` stage compiling inside Docker (needs a `build.py --bare` that
  skips browser staging and the archive); the WSL binary is the release
  artifact, so the image wraps it instead.
- Chrome for Testing zips in the image (`/api/update/browser`): excluded to
  keep the image ~250 MB; remove the `dist/updates/browser` line from
  `.dockerignore` for a hub that must hand desktops a browser update.
- No CI: the repo is not under git; images are built and pushed by hand.
