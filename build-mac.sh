#!/bin/bash
# One-shot macOS build of KASTR (0.13.1): venv + PyInstaller + the native
# helpers, Apple Silicon only.                                   (see MACOS.md)
#
#   ./build-mac.sh                 fetch helpers (once), build dist/macos/KASTR.app
#   ./build-mac.sh --no-fetch      skip fetch-helpers.py (bin/ already populated)
#   ./build-mac.sh --keep-version  is implied; extra flags go to build.py
#
# The Mac never runs --publish: the update feed is assembled on the Windows
# box with `python build.py --publish-only` once dist/macos/ is copied back
# (the feed needs all three platform folders side by side).
set -euo pipefail
cd "$(dirname "$0")"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "build-mac.sh runs on macOS only (this is $(uname -s)). Use build.py directly elsewhere." >&2
  exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "KASTR for macOS is Apple Silicon only: moq-relay and moq-cli publish no" >&2
  echo "x86_64-apple-darwin build, so an Intel Mac would ship without a relay or" >&2
  echo "RTSP publisher. Refusing to build on $(uname -m)." >&2
  exit 1
fi
if ! xcode-select -p >/dev/null 2>&1; then
  echo "The Xcode Command Line Tools are missing. Run:  xcode-select --install   then re-run this script." >&2
  exit 1
fi

FETCH=1
ARGS=()
for a in "$@"; do
  case "$a" in
    --no-fetch) FETCH=0 ;;
    *) ARGS+=("$a") ;;
  esac
done

PY="${PYTHON:-python3}"
if [ ! -x .venv-mac/bin/python ]; then
  echo "Creating .venv-mac with $PY ($("$PY" --version 2>&1)) ..."
  "$PY" -m venv .venv-mac
fi
# shellcheck disable=SC1091
. .venv-mac/bin/activate
python -m pip install --quiet -U pip pyinstaller cryptography

if [ "$FETCH" = 1 ]; then
  python fetch-helpers.py
else
  echo "Skipping fetch-helpers.py (--no-fetch)"
fi
for h in moq-relay moq; do
  [ -x "bin/$h" ] || echo "WARNING: bin/$h is missing -- the build will ship without it (run without --no-fetch)" >&2
done
if [ ! -x bin/ffmpeg ]; then
  echo "NOTE: bin/ffmpeg is missing -- RTSP feeds will use the ffmpeg on PATH (brew install ffmpeg)." >&2
  echo "      To bundle one, pin FFMPEG_MAC in fetch-helpers.py." >&2
fi

# --keep-version: the Mac joins the release Windows/WSL already numbered
# (VERSION is set by hand); a bare build.py here would take the next number.
python build.py --keep-version ${ARGS[@]+"${ARGS[@]}"}

VER="$(tr -d '\r\n ' < VERSION | sed 's/^\xEF\xBB\xBF//')"
echo
echo "App:      $(pwd)/dist/macos/KASTR.app"
echo "Archive:  $(pwd)/dist/archive/v$VER/KASTR-macos-v$VER.zip"
echo
echo "Next: copy dist/macos/ and that zip back to the Windows tree, then there:"
echo "      python build.py --publish-only        (adds updates/macos/KASTR to the feed)"
