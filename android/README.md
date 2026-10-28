# KASTR on Android

## probe/ -- the KASTR probe (a test app, not KASTR)

A small APK (about 50 KB) for the Yealink meeting devices (MeetingBar A25 / A50 with MeetingDisplay, MeetingBoard 86 Pro)
and, later, phones and handhelds. It reports whether the real KASTR Android app could work on a device: WebTransport,
WebCodecs (decode first: H.264 / HEVC at 1080p and 4K, default, prefer-hardware and prefer-software, plus a real
encode-then-decode run), the system WebView, launcher / kiosk context, D-pad / remote keys, the boot receiver and the
network. **Display-only build** (Kenton's IT, 2026-10-28): no camera or microphone permissions, and no camera or mic
checks.

Package `app.kastr.probe`, minSdk 24 (Android 7), targetSdk 34 (Android 14). Plain Java, no libraries: the QR code
encoder is our own (`QrCode.java`, desktop-tested by `test/QrCodeTest.java`). The browser checks are
`assets/probe.html`, served by the app itself at `https://appassets.androidplatform.net/probe.html` so the page is a
secure context, like the real KASTR page.

### Build (WSL, as root)

    wsl -u root -e bash android/probe/build.sh

Writes `dist/android/kastr-probe-<version>.apk` (`dist/` is not in git). Steps: QR self-test, `aapt2 compile/link`,
`javac` (Java 8 bytecode against android.jar), `d8`, `zipalign`, `apksigner` (v1 + v2), then `zipalign -c`,
`apksigner verify` and `aapt2 dump badging`.

Toolchain (the only downloads, approved by Kenton on 2026-10-28):

| what | where | from |
|---|---|---|
| JDK 17 | `apt-get install -y openjdk-17-jdk-headless` | Ubuntu archive |
| build-tools r34 | `/opt/android-sdk/build-tools-34/android-14/` | `https://dl.google.com/android/repository/build-tools_r34-linux.zip` (61,224,257 bytes, sha256 `e858c4b60069d0431051b225d384413b1643e1289b00a4825aed347f25bd510f`) |
| android-34 platform | `/opt/android-sdk/platform-34/android-34/android.jar` | `https://dl.google.com/android/repository/platform-34-ext7_r03.zip` (63,180,081 bytes, sha256 `16fdb74c55e59ae3ef52def135aec713508467bd56d7dabcd8c9be31fa8b20f3`) |

Overrides: `ANDROID_SDK`, `BUILD_TOOLS`, `ANDROID_JAR`, `PROBE_KEYSTORE`, `PROBE_OUT`.

### Signing

A local TEST key, outside the repo: `/mnt/c/kastr-scratch/android/probe-test.keystore` (PKCS12, alias `probe`), with
its random password in `probe-test.pass` next to it. build.sh makes both on the first build and never prints the
password. Keep using the same keystore: Android refuses an update signed with a different key (uninstall first if the
key ever changes). This is not a release key.

### Tests

`tests/test_release_0_21_92_android_probe.py`: source tree, manifest (permissions, launchers, no camera / mic),
nothing prefilled, build.sh output path; the real build runs (into a temp folder, throwaway key) only when WSL and the
toolchain are present.
