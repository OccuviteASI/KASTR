#!/usr/bin/env bash
# KASTR field check (Linux) -- read-only. Run on the box itself (as the user KASTR runs as):
#   bash kastr-field-check.sh
# Collects this KASTR's version, relay + federation + cluster status, relay health, the hub's spoke table and the
# relay / launch log lines about the cluster into one text file in your home folder. Tokens and access codes are blanked.
STATE="${KASTR_STATE_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/ASI/KASTR}"
PORT="${1:-}"   # optional: the KASTR web port when it is not the remembered one
[ -z "$PORT" ] && [ -f "$STATE/http-port" ] && PORT="$(tr -d '[:space:]' < "$STATE/http-port")"
if [ -z "$PORT" ]; then for p in 8000 8001 8002; do curl -s -o /dev/null -m 3 "http://127.0.0.1:$p/api/instance" && { PORT=$p; break; }; done; fi
OUT="$HOME/kastr-field-$(hostname)-$(date +%Y%m%d-%H%M%S).txt"
redact() { sed -E -e 's/(jwt=)[A-Za-z0-9._-]+/\1<redacted>/g' \
  -e 's/("(token|code|access|secret|roomKey|admin|publisher|viewer|federation)"[[:space:]]*:[[:space:]]*)"[^"]*"/\1"<redacted>"/Ig' \
  -e 's/(Bearer[[:space:]]+)[A-Za-z0-9._-]+/\1<redacted>/g'; }
section() { printf '\n===== %s =====\n' "$1" >> "$OUT"; redact >> "$OUT"; }
echo "KASTR field check  $(date -u +%FT%TZ)  host $(hostname)  web port ${PORT:-none}" > "$OUT"
if [ -z "$PORT" ]; then echo "no KASTR answered on this machine (is it running?)" | section error; echo "Wrote $OUT"; exit 1; fi
for ep in /api/instance /api/relay/status /api/relay/cluster /api/relay/health /api/relay/spokes /api/lan/advertise; do
  curl -s -m 15 "http://127.0.0.1:$PORT$ep" | section "$ep"
done
if [ -f "$STATE/launch.log" ]; then
  tail -n 4000 "$STATE/launch.log" | grep -Ei 'cluster|federation|spoke|hub|relay:|rehome|token|session' | tail -n 250 | section "launch.log (cluster / federation lines, last 250)"
else
  echo "not found at $STATE/launch.log" | section launch.log
fi
echo "Wrote $OUT -- send this file."
