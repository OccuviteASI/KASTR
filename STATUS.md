# Agent J -- KASTR probe APK (0.21.92) -- STATUS

A small Android **test app** (not KASTR) for the Yealink MeetingBar A25 / A50 + MeetingDisplay and the MeetingBoard 86
Pro. It tells us whether the real KASTR Android app can work there. **Display-only build** (Kenton's IT, 2026-10-28):
no camera or microphone permissions and no camera / mic checks; the report says
"camera / mic: not checked (display-only build)".

## What's built

- Source: `android/probe/` (AndroidManifest.xml, res/, assets/probe.html, src/, test/QrCodeTest.java, build.sh),
  `android/README.md`, `tests/test_release_0_21_92_android_probe.py`. Plain Java, no libraries, no Gradle.
- APK: `dist/android/kastr-probe-0.21.92.apk` (not in git)
  - size **49,748 bytes**
  - sha256 **32fd927bccd94fd9c6e3fab6048316036bb078d597d5e054de0d4f59bab37a57**
  - package `app.kastr.probe`, versionCode 2192, versionName 0.21.92, minSdk 24 (Android 7), targetSdk 34
  - signed v1 + v2 with a local TEST key (cert SHA-256 `7abd3cad89edc2cb12305766f17d5cba936b8b857fb601a24c586a45394ec7c4`)
  - each rebuild changes the sha256 (zip timestamps); the signing key stays the same
- Permissions: INTERNET, ACCESS_NETWORK_STATE, RECEIVE_BOOT_COMPLETED. Launchers: LAUNCHER + LEANBACK_LAUNCHER with a
  banner. touchscreen and leanback `required="false"`.

## What it checks (Run checks)

- **Summary / verdict** first: WebTransport, H.264 / HEVC decode at 1080p and 4K (default / hardware / software), real
  decode, Opus decode, AudioWorklet, secure context, WebView version.
- **Device:** manufacturer / model / device / product / brand / hardware, Android version + SDK_INT, security patch,
  ABIs, RAM, cores; screen pixels, dp, density, refresh rate, display modes, HDR types; touch feature + input devices
  (touchscreen / dpad / keys / mouse, vendor:product id); UiModeManager mode (TV?); last key pressed (code, name,
  input device) and every key seen.
- **Launcher / kiosk:** default home app, whether the probe is home, all home apps, installed packages whose names
  contain teams / yealink / zoom (names only; on Android 11+ only apps with a launcher / home entry are visible), who
  installed the probe, lock-task (kiosk) state, lock task permitted, draw-over-apps, battery-optimisation exemption,
  boot receiver ("boot seen at <time>", count).
- **WebView:** package + versionName (getCurrentWebViewPackage on Android 8+, known package names before), default
  user agent, navigator.userAgent.
- **Inside the WebView** (page served by the app at an https origin, so a secure context like the KASTR page):
  - WebTransport: typeof, then a real construct to `https://127.0.0.1:9` -- "works" = it tried and failed with a
    WebTransportError; also reports construct errors / timeouts with the error class;
  - typeof VideoEncoder / VideoDecoder / AudioEncoder / AudioDecoder / VideoFrame / ...;
  - `VideoDecoder.isConfigSupported` with no preference, `prefer-hardware` and `prefer-software`: H.264 42E01E /
    42E01F (720p, 1080p), 4D401F (1080p), 640028 (720p, 1080p, 4K), 640033 (4K); HEVC hvc1/hev1 L93 (720p, 1080p),
    L120 (1080p), L153 (4K); VP8; VP9 (1080p, 4K); AV1 (1080p, 4K). The codec strings include the ones
    moq-watch-lite.html uses;
  - `VideoEncoder.isConfigSupported` (default + prefer-hardware) for H.264 / HEVC / VP8 / VP9 / AV1;
  - a real decode: 30 frames encoded in the page then decoded (H.264 and HEVC, 1080p and 4K, prefer-hardware and
    no-preference) -- frames out and ms per frame; skipped where the device cannot encode that codec;
  - Opus decode / encode (mono, stereo), AAC decode;
  - OffscreenCanvas, WebGL2 (+ GPU name), AudioWorklet (module loaded + node made), MediaStreamTrackProcessor /
    Generator, crypto.subtle (SHA-256 + AES-GCM), IndexedDB, localStorage, secure context, canPlayType, wake lock.
- **Network:** active network (ethernet / wifi / ...), validated, metered, interface, DNS server count, private DNS;
  and, only when a host is typed, DNS + HTTPS GET of `<host>/moq-watch-lite.html` (status, time, alt-svc).
- **Last KASTR page** (after Open a KASTR page): URL (no query string), loaded or not, HTTP / TLS / renderer errors.

Other buttons: **Open a KASTR page** (field starts empty; loads `<host>/moq-watch-lite.html` in the same WebView;
Back or "Back to report" returns; a certificate problem asks before continuing), **Save report** (JSON + text to the
app's folder, plus Download/KASTR probe/ on Android 10+), **Copy report**, **QR code** (our own encoder, a compact form
of the report; OK / Back / tap closes it). Big focusable buttons with a white focus ring; OK / Enter activates.

## How to build

    wsl -u root -e bash android/probe/build.sh

Toolchain in WSL (see android/README.md for the URLs, sizes and sha256s): openjdk-17-jdk-headless 17.0.20.1
(apt), `/opt/android-sdk/build-tools-34/android-14/`, `/opt/android-sdk/platform-34/android-34/android.jar`.
Nothing else was downloaded. Test key: `C:\kastr-scratch\android\probe-test.keystore` + `probe-test.pass` (outside
the repo, made by the first build, password never printed). NOTE: WSL's /mnt/c mount has no Linux permissions, so
the `chmod 600` on the password file does not stick there (it shows 0777); the file is only protected by Windows
permissions on C:\kastr-scratch.

## Offline checks done (no device, no emulator)

- `zipalign -c -p 4`: ok. `apksigner verify --min-sdk-version 18`: v1 true, v2 true.
- `aapt2 dump badging`: package / versions / sdk levels / 3 permissions / application banner + icon / launchable +
  leanback-launchable activity / touchscreen + leanback not required.
- QR encoder: `test/QrCodeTest.java` on the desktop JVM (runs in every build): published Reed-Solomon vector, format
  and version bits, capacity and alignment tables, and 46 round trips through an independent reader (unmask, zig-zag,
  de-interleave, RS syndromes, byte-mode parse).
- probe.html run in desktop Chromium 152 with a stub bridge: all parts complete (WebTransport "works", decode matrix,
  real decode 30/30 frames at 1080p and 4K, audio, features).
- `python -m unittest tests.test_release_0_21_92_android_probe`: 14 tests OK (includes a real build into a temp
  folder with a throwaway key).

## Not verified (needs a device)

- That it installs and opens on the Yealink units at all (Teams Rooms devices may block third-party apps or hide
  them from the launcher), and how it looks / navigates with their remote and touch panel.
- Android-side Java behaviour in general: no Android runtime was available, so the native checks, report text, Save
  (MediaStore), Copy, QR display, key handling and the KASTR page view are compiled and dex'd but never run.
- Whether `LEANBACK_LAUNCHER` / the banner is used by Yealink's launcher.
- The boot receiver: Android only delivers BOOT_COMPLETED after the app has been opened once; restart the device
  after the first run, then Run checks again.

## How Kenton installs it

Kenton's IT confirmed they **can upload an APK to the TV (MeetingDisplay / MeetingBoard) and to the sound bar
(MeetingBar)**. Use that path first.

1. **Yealink Device Manager / YMCS (IT's upload):** upload `kastr-probe-0.21.92.apk` as an app for the device and push
   it. (The exact YMCS menu names are IT's; not written here because I have not seen them.)
2. **adb** (if developer options / USB or network debugging is on for the unit):

       adb connect <device-ip>:5555        (network) -- or plug in USB
       adb install -r kastr-probe-0.21.92.apk
       adb shell monkey -p app.kastr.probe 1      (opens it if the launcher does not show it)

   Getting the report back over adb: `adb shell ls /sdcard/Android/data/app.kastr.probe/files/` then
   `adb pull /sdcard/Android/data/app.kastr.probe/files/<name>.json`.
3. **USB stick + a file manager on the unit**, if the unit has one and allows installing unknown apps.

Unknowns: the A-series bars may need to be switched out of Teams mode (Yealink's "Android mode" or a developer /
debug setting) before third-party apps can run or show a launcher icon -- I don't know the menu path; IT or Yealink's
docs will. If the app installs but has no icon, `adb shell monkey -p app.kastr.probe 1` or YMCS's "open app" (if it
has one) starts it.

## What to send back

1. On each unit: (optional) press a few remote / touch-panel keys, type a relay host into "Relay host" (any KASTR relay
   host you would normally use; leave it empty to skip the reach test), press **Run checks** and wait for "Checks
   done" (30-90 s).
2. **Save report** (or **Copy report**), and send the `kastr-probe-<time>.json` (+ `.txt`) files. If getting files off
   the unit is hard, press **QR code** and photograph it (it holds a compact summary), or photograph the report's
   SUMMARY section.
3. Optional: **Open a KASTR page**, try a real room, note whether video plays, press Back, then Save report again (it
   adds "Last KASTR page").
4. Tell me the device model and whether it was in Teams mode or Android mode.

## Git

Branch work only (merged main first, no VERSION bump, nothing pushed). The APK, keystore and SDK are not committed;
`dist/` was already in .gitignore.
