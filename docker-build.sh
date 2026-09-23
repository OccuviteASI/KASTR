#!/bin/bash
# Build the KASTR container image from the WSL-built Linux binary (0.13.1).
#
#   ./docker-build.sh                          -> kastr:<VERSION> + kastr:latest
#   ./docker-build.sh --push ghcr.io/<you>/kastr   also retag as that name and push
#
# Run it on the machine that built dist/linux (WSL: the repo is under
# /mnt/c/...), AFTER `python build.py --keep-version --publish` there, so
# dist/linux/BUILT_VERSION == VERSION and dist/updates/windows/KASTR.exe is
# fresh. It refuses a stale dist/linux rather than baking an old binary into
# an image tagged with the new version.                       (see DOCKER.md)
set -euo pipefail
cd "$(dirname "$0")"

strip() { tr -d '\r\n ' | sed 's/^\xEF\xBB\xBF//'; }
VER="$(strip < VERSION)"
[ -f dist/linux/BUILT_VERSION ] || { echo "dist/linux/BUILT_VERSION is missing -- build the Linux binary first (python build.py --keep-version --publish on WSL)." >&2; exit 1; }
BUILT="$(strip < dist/linux/BUILT_VERSION)"
if [ "$BUILT" != "$VER" ]; then
  echo "refusing: dist/linux/BUILT_VERSION says v$BUILT but VERSION is v$VER." >&2
  echo "          Rebuild the Linux binary (python build.py --keep-version --publish) first." >&2
  exit 1
fi
[ -f dist/linux/KASTR ] || { echo "dist/linux/KASTR is missing." >&2; exit 1; }
if [ ! -f dist/updates/windows/KASTR.exe ]; then
  echo "note: dist/updates/windows/KASTR.exe is missing -- the image will not offer Windows clients an update (build.py --publish writes it)." >&2
fi
if [ -f dist/updates/latest.json ] && ! grep -q "\"version\": \"$VER\"" dist/updates/latest.json; then
  echo "note: dist/updates/latest.json is not at v$VER -- the feed copied into the image may be stale (python build.py --publish-only)." >&2
fi
command -v docker >/dev/null 2>&1 || { echo "docker is not installed here (on WSL: install Docker Engine, or Docker Desktop with WSL integration)." >&2; exit 1; }

echo "Building kastr:$VER from dist/linux/KASTR ($(stat -c %s dist/linux/KASTR) bytes, sha256 $(sha256sum dist/linux/KASTR | cut -c1-12)...)"
docker build -t "kastr:$VER" -t kastr:latest .

if [ "${1:-}" = "--push" ]; then
  NAME="${2:-}"
  [ -n "$NAME" ] || { echo "--push needs a registry/name, e.g. --push ghcr.io/<you>/kastr" >&2; exit 1; }
  docker tag "kastr:$VER" "$NAME:$VER"
  docker tag kastr:latest "$NAME:latest"
  docker push "$NAME:$VER"
  docker push "$NAME:latest"
  echo "Pushed $NAME:$VER and $NAME:latest -- on the box: docker compose pull && docker compose up -d"
elif [ -n "${1:-}" ]; then
  echo "unknown argument: $1 (only --push <registry/name> is accepted)" >&2
  exit 1
fi
echo "Done: kastr:$VER, kastr:latest.  Run:  docker compose up -d   (KASTR_IMAGE=kastr:$VER)"
