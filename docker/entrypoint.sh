#!/bin/bash
# KASTR container entrypoint (0.13.1).
#
# The image ships a KASTR binary under /opt/kastr; the container RUNS the
# copy under /data/app (a volume), because KASTR updates itself in place --
# update_from swaps sys.executable, then relaunch_self exits 75 under
# KASTR_CONTAINER=1 instead of spawning -- and an update that lived in the
# image layer would vanish with the next container. So:
#
#   seed      /data/app/KASTR from the image when it is missing, or when the
#             image's BUILT_VERSION is NEWER than the version last seeded
#             (IMAGE_VERSION marker). An in-app update that moved /data/app
#             ahead of the image survives a restart of the SAME image; a
#             newer pulled image wins over an older self-update.
#   kastr.ini written ONCE from the environment (KASTR_MODE, KASTR_RELAY,
#             KASTR_UPDATE) -- the Relay page's /api/mode edits this same
#             file afterwards, so the env is a first-run default, not a
#             setting that overrides the UI on every start.
#   loop      run KASTR --no-browser --port $KASTR_PORT; exit code 75 means
#             "relaunch me" -> restart on /data/app/KASTR with
#             KASTR_UPDATED=1 (the launcher then sweeps .old-* files and
#             skips one update check); any other code ends the container
#             (compose `restart: unless-stopped` brings it back).
set -u

# KASTR_IMAGE_DIR / KASTR_APP_DIR exist for running this script outside a
# container (the release smoke exercises the seed + exit-75 loop with a stub
# binary); inside the image they are the defaults.
IMG="${KASTR_IMAGE_DIR:-/opt/kastr}"
APP="${KASTR_APP_DIR:-/data/app}"
STATE="${KASTR_STATE_DIR:-/data/state}"
PORT="${KASTR_PORT:-8000}"
export KASTR_CONTAINER="${KASTR_CONTAINER:-1}"
export KASTR_STATE_DIR="$STATE"
mkdir -p "$APP" "$STATE"

log() { echo "[kastr-entrypoint] $*"; }

# newer A B -> true when version A sorts after version B (0.13.1 > 0.13.0,
# 0.9.10 > 0.9.9; `sort -V` gets the numeric parts right).
newer() {
  [ -n "$1" ] && [ "$1" != "$2" ] && \
    [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -n 1)" = "$1" ]
}

img_ver="$(tr -d '\r\n ' < "$IMG/BUILT_VERSION" 2>/dev/null || true)"
had_ver="$(tr -d '\r\n ' < "$APP/IMAGE_VERSION" 2>/dev/null || true)"

if [ ! -x "$APP/KASTR" ] || [ -z "$had_ver" ] || newer "$img_ver" "$had_ver"; then
  log "seeding $APP from the image (v${img_ver:-?}; volume had v${had_ver:-none})"
  # write beside and rename: a container killed mid-copy must not leave a
  # truncated binary standing in for the app.
  install -m 0755 "$IMG/KASTR" "$APP/KASTR.new"
  mv -f "$APP/KASTR.new" "$APP/KASTR"
  rm -f "$APP"/KASTR.old-* 2>/dev/null || true
  if [ -d "$IMG/updates" ] && [ -n "$(ls -A "$IMG/updates" 2>/dev/null)" ]; then
    mkdir -p "$APP/updates"
    cp -a "$IMG/updates/." "$APP/updates/"
    log "fleet feed refreshed: $(find "$APP/updates" -type f ! -name latest.json | sed "s|$APP/||" | tr '\n' ' ')"
  fi
  printf '%s\n' "$img_ver" > "$APP/IMAGE_VERSION"
else
  log "keeping $APP/KASTR (volume seeded from v$had_ver, image is v${img_ver:-?})"
fi

if [ ! -f "$APP/kastr.ini" ]; then
  log "writing $APP/kastr.ini (mode=${KASTR_MODE:-relay} relay=${KASTR_RELAY:-http://127.0.0.1:4443} update=${KASTR_UPDATE:-on})"
  cat > "$APP/kastr.ini" <<EOF
; KASTR container config -- written once by /entrypoint.sh from the
; environment (KASTR_MODE, KASTR_RELAY, KASTR_UPDATE) on first start.
; The Relay page (/api/mode) edits this same file; edit it by hand or delete
; it to have the entrypoint rewrite it from the environment on next start.
[streamer]

; viewer | publisher | relay | publisher-relay (relay autostarts the bundled
; moq-relay on 4443 and boots to the Relay page).
mode = ${KASTR_MODE:-relay}

; Relay the pages point at; the version authority for self-updates when it
; is another machine (a hub). http://127.0.0.1:4443 = this box hosts it.
relay = ${KASTR_RELAY:-http://127.0.0.1:4443}

; Bind every interface -- the UI is reached from other machines, and the
; HEALTHCHECK hits 127.0.0.1.
host = 0.0.0.0

; on: follow the hub's KASTR version (in-app update -> exit 75 -> restart
; here on the new binary). off: only `docker compose pull` updates this box.
update = ${KASTR_UPDATE:-on}
EOF
fi

pid=""
term() {
  log "signal received -- stopping KASTR (pid ${pid:-?})"
  [ -n "$pid" ] && kill -TERM "$pid" 2>/dev/null
}
trap term TERM INT

while :; do
  log "starting $APP/KASTR --no-browser --port $PORT $*"
  "$APP/KASTR" --no-browser --port "$PORT" "$@" &
  pid=$!
  wait "$pid"
  code=$?
  if [ "$code" -gt 128 ]; then
    # wait was interrupted by our trap; let the child finish and take ITS code
    wait "$pid"
    code=$?
  fi
  if [ "$code" -eq 75 ]; then
    log "KASTR exited 75 (relaunch requested: update or mode change) -- restarting on $APP/KASTR"
    export KASTR_UPDATED=1
    continue
  fi
  log "KASTR exited $code"
  exit "$code"
done
