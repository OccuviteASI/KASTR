#!/bin/sh
# Registers KASTR in this user's applications menu, so it launches from the
# GUI (GNOME's file manager refuses to run raw binaries by design -- a
# .desktop launcher is the Linux way to double-click an app).
#
#   sh install.sh        then find KASTR in the applications grid
#
# Nothing is copied: the launcher points at the binary right here, so keep
# this folder where it is (or run install.sh again after moving it).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$HERE/KASTR"
# 0.9.0: KASTR ships its own Chromium in browser/. It needs the usual desktop
# shared libraries; say which are missing rather than failing silently later.
# 0.9.3: the exec bits are restored here too (a zip unpacked by some tools
# loses them; KASTR also fixes them itself on every launch).
if [ -x "$HERE/browser/chrome" ] || [ -f "$HERE/browser/chrome" ]; then
  chmod +x "$HERE/browser/chrome" "$HERE/browser/chrome_crashpad_handler" "$HERE/browser/chrome_sandbox" "$HERE/browser/chrome-wrapper" 2>/dev/null || true
  if command -v ldd >/dev/null 2>&1; then
    MISSING="$(ldd "$HERE/browser/chrome" 2>/dev/null | awk '/not found/ {print $1}' | sort -u | tr '\n' ' ')"
    if [ -n "$MISSING" ]; then
      echo "The bundled browser needs libraries this system lacks: $MISSING"
      echo "On Debian/Ubuntu:  sudo apt install libnss3 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 libgbm1 libgtk-3-0 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libasound2 libpango-1.0-0 libcairo2"
      echo "(KASTR falls back to a system Chrome/Chromium until then.)"
    else
      echo "Bundled browser: OK (browser/chrome $(cat "$HERE/browser/VERSION" 2>/dev/null))"
    fi
  fi
fi
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
cat > "$APPS/kastr.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=KASTR
Comment=Kenton's ASI Streaming Tool with Relay
Exec=$HERE/KASTR
Icon=$HERE/kastr.svg
Terminal=false
Categories=AudioVideo;Network;
EOF
chmod +x "$APPS/kastr.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" || true
echo "Installed: KASTR is in your applications menu (log out/in if it doesn't appear)."
echo "CLI works as always:  $HERE/KASTR"
