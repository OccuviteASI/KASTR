#!/bin/bash
# Exercise docker/entrypoint.sh without Docker (0.13.1): a stub KASTR script
# stands in for the binary. Covers first seed, kastr.ini from env, the
# exit-75 relaunch loop with KASTR_UPDATED=1, "keep" when the image is not
# newer, re-seed when it is, and a TERM forwarded to the child.
#
#   bash docker/test-entrypoint.sh          (bash 4+, GNU coreutils; WSL is fine)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
IMG="$T/img"; APP="$T/app"; STATE="$T/state"
mkdir -p "$IMG/updates/windows" "$APP"

# stub binary: logs argv + the env it cares about, exits with the code in
# $APP/next-exit (default 0), sleeping first when $APP/sleep exists.
cat > "$IMG/KASTR" <<'EOF'
#!/bin/bash
d="$(dirname "$0")"
echo "stub: args=[$*] KASTR_UPDATED=${KASTR_UPDATED:-} KASTR_CONTAINER=${KASTR_CONTAINER:-} KASTR_STATE_DIR=${KASTR_STATE_DIR:-}" >> "$d/stub.log"
if [ -f "$d/sleep" ]; then
  trap 'echo "stub: TERM" >> "$d/stub.log"; exit 143' TERM
  sleep 30 & wait $!
fi
code="$(cat "$d/next-exit" 2>/dev/null || echo 0)"
echo 0 > "$d/next-exit"
exit "$code"
EOF
chmod 755 "$IMG/KASTR"
echo "0.13.1" > "$IMG/BUILT_VERSION"
echo "fake exe" > "$IMG/updates/windows/KASTR.exe"

run() { KASTR_IMAGE_DIR="$IMG" KASTR_APP_DIR="$APP" KASTR_STATE_DIR="$STATE" "$@" bash "$HERE/entrypoint.sh"; }
pass() { echo "  ok   $*"; }
fail() { echo "  FAIL $*"; exit 1; }

echo "1. first start: seed + kastr.ini + exit 75 loop"
echo 75 > "$APP/next-exit"       # stub's FIRST run asks to relaunch; second exits 0
set +e; run env KASTR_MODE=publisher KASTR_RELAY=http://hub.example:4443 KASTR_PORT=18000 > "$T/out1.log" 2>&1; code=$?; set -e
[ "$code" -eq 0 ] || fail "entrypoint exit $code (expected 0): $(cat "$T/out1.log")"
[ -x "$APP/KASTR" ] || fail "no seeded binary"
[ "$(cat "$APP/IMAGE_VERSION")" = "0.13.1" ] || fail "IMAGE_VERSION=$(cat "$APP/IMAGE_VERSION")"
[ -f "$APP/updates/windows/KASTR.exe" ] || fail "feed not copied"
grep -q '^mode = publisher$' "$APP/kastr.ini" || fail "mode not from env"
grep -q '^relay = http://hub.example:4443$' "$APP/kastr.ini" || fail "relay not from env"
grep -q '^host = 0.0.0.0$' "$APP/kastr.ini" || fail "host"
grep -q '^update = on$' "$APP/kastr.ini" || fail "update default"
[ "$(grep -c '^stub: args' "$APP/stub.log")" -eq 2 ] || fail "stub ran $(grep -c '^stub: args' "$APP/stub.log") times, expected 2"
sed -n 1p "$APP/stub.log" | grep -q 'args=\[--no-browser --port 18000\] KASTR_UPDATED= KASTR_CONTAINER=1' || fail "first run env: $(sed -n 1p "$APP/stub.log")"
sed -n 2p "$APP/stub.log" | grep -q 'KASTR_UPDATED=1' || fail "second run lacks KASTR_UPDATED=1: $(sed -n 2p "$APP/stub.log")"
grep -q "KASTR_STATE_DIR=$STATE" "$APP/stub.log" || fail "state dir not exported"
grep -q 'exited 75' "$T/out1.log" || fail "no exit-75 log line"
pass "seeded v0.13.1, ini from env, relaunch loop ran twice, KASTR_UPDATED=1 on the second"

echo "2. same image again: keep the volume's binary (simulating an in-app update)"
echo "updated by kastr" >> "$APP/KASTR"; before="$(sha256sum "$APP/KASTR")"
run env KASTR_MODE=viewer > "$T/out2.log" 2>&1
[ "$(sha256sum "$APP/KASTR")" = "$before" ] || fail "binary was re-seeded on an equal image"
grep -q 'keeping' "$T/out2.log" || fail "no keep line: $(cat "$T/out2.log")"
grep -q '^mode = publisher$' "$APP/kastr.ini" || fail "kastr.ini was rewritten from env on a later start"
pass "kept /data/app/KASTR and kastr.ini"

echo "3. older image than the marker: keep"
echo "0.13.0" > "$IMG/BUILT_VERSION"
run > "$T/out3.log" 2>&1
[ "$(sha256sum "$APP/KASTR")" = "$before" ] || fail "older image re-seeded"
pass "older image (0.13.0 < 0.13.1) did not re-seed"

echo "4. newer image: re-seed (0.13.10 > 0.13.1, sort -V)"
echo "0.13.10" > "$IMG/BUILT_VERSION"
run > "$T/out4.log" 2>&1
[ "$(sha256sum "$APP/KASTR")" != "$before" ] || fail "newer image did not re-seed"
[ "$(cat "$APP/IMAGE_VERSION")" = "0.13.10" ] || fail "marker not advanced"
grep -q 'seeding' "$T/out4.log" || fail "no seeding line"
pass "re-seeded from 0.13.10, marker advanced"

echo "5. TERM to the entrypoint reaches the child and the loop ends"
touch "$APP/sleep"
KASTR_IMAGE_DIR="$IMG" KASTR_APP_DIR="$APP" KASTR_STATE_DIR="$STATE" bash "$HERE/entrypoint.sh" > "$T/out5.log" 2>&1 &
ep=$!
sleep 1
kill -TERM "$ep"
set +e; wait "$ep"; code=$?; set -e
[ "$code" -eq 143 ] || fail "entrypoint exit $code after TERM (expected 143): $(cat "$T/out5.log")"
grep -q 'stub: TERM' "$APP/stub.log" || fail "child never saw TERM"
pass "TERM forwarded, exit 143, no lingering loop"

echo "6. extra container args pass through (docker run kastr --diagnose /dev/null)"
rm -f "$APP/sleep"
KASTR_IMAGE_DIR="$IMG" KASTR_APP_DIR="$APP" KASTR_STATE_DIR="$STATE" bash "$HERE/entrypoint.sh" --diagnose /dev/null > /dev/null 2>&1
tail -n 1 "$APP/stub.log" | grep -q 'args=\[--no-browser --port 8000 --diagnose /dev/null\]' || fail "args: $(tail -n 1 "$APP/stub.log")"
pass "argv shape"

echo "ALL ENTRYPOINT CHECKS PASSED"
