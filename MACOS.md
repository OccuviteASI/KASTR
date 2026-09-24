# KASTR on macOS (Apple Silicon)

*0.13.1.* KASTR builds on a Mac with `./build-mac.sh` into
`dist/macos/KASTR.app`, Macs join the fleet update feed as `updates/macos/
KASTR` (`latest.json` key `darwin`), and the feed is assembled on the Windows
box with `python build.py --publish-only`. **Intel Macs are unsupported**: the
MoQ project publishes `aarch64-apple-darwin` builds of `moq-relay` 0.15.1 and
`moq-cli` 0.12.1 (0.16.0 pins) and no `x86_64` ones, so an Intel build would have no relay
and no RTSP publisher; `build-mac.sh` refuses on anything but `arm64`.

## 1. Prerequisites

| What | Why | How |
|---|---|---|
| Apple Silicon Mac, macOS 13 or newer | the helpers are arm64 Mach-O; WebTransport needs a current Chrome | -- |
| Xcode Command Line Tools | `codesign`, compilers for wheels | `xcode-select --install` |
| Python 3.11+ | the launcher is Python; `python3 --version` | Homebrew `brew install python@3.12` or python.org |
| Google Chrome (or Chromium/Edge) | the app window. Chrome for Testing is bundled on Windows/Linux only (`browser.json`); the Mac uses the **system** Chrome | https://www.google.com/chrome/ |
| ffmpeg (optional, for RTSP cameras) | until a static arm64 build is pinned in `fetch-helpers.py` (`FFMPEG_MAC`), nothing is bundled and KASTR uses the one on PATH / `/opt/homebrew/bin` | `brew install ffmpeg` |

`fetch-helpers.py` downloads `bin/moq-relay` and `bin/moq` (sha256-pinned from
the releases' `SHA256SUMS`: relay `4ac8e7e5…7fd18`, cli `486e9e99…4465`) and
prints the `brew install ffmpeg` hint.

## 2. Get the tree onto the Mac

Copy the KASTR folder (the sources, `assets/`, `icons/`, `browser.json`,
`VERSION`, `RELEASES.md`; `dist/` and `bin/` are not needed -- `bin/` is
platform-specific and gets fetched) to the Mac, e.g. a zip from Windows or a
share. `VERSION` must already say the release being built (it is set by hand
on Windows; the Mac builds with `--keep-version` and never bumps it).

## 3. Build

```bash
cd KASTR
chmod +x build-mac.sh          # once, if the copy lost the mode
./build-mac.sh                 # helpers + venv + PyInstaller
./build-mac.sh --no-fetch      # bin/ already populated
```

What it does: refuses unless `uname -s`=Darwin and `uname -m`=arm64, checks
`xcode-select -p`, creates/reuses `.venv-mac`, `pip install -U pip pyinstaller
cryptography`, `python fetch-helpers.py`, then `python build.py --keep-version`
(extra flags pass through). Output:

```
dist/macos/KASTR.app                              the app (PyInstaller onefile, --windowed)
dist/macos/KASTR                                  the same executable, loose (PyInstaller leaves it; the zip skips it)
dist/macos/BUILT_VERSION
dist/archive/v<VERSION>/KASTR-macos-v<VERSION>.zip the bundle tree, executables 0755
```

`build.py` stamps `Info.plist` with the camera / microphone / local-network
usage strings and `NSHighResolutionCapable`. The Mac does **not** run
`--publish` (see §6).

`kastr.ini` goes in **`KASTR.app/Contents/MacOS/`**, next to the executable
(that is `app_dir()` inside a bundle); the working directory is checked too.
A copy in `dist/macos/` beside the `.app` is not read by the app.

## 4. First run (un-notarized)

The bundle is not signed with a Developer ID and not notarized, so Gatekeeper
blocks the first launch:

- right-click `KASTR.app` -> **Open** -> **Open** (or System Settings ->
  Privacy & Security -> **Open Anyway** after the first refusal), or
- `xattr -dr com.apple.quarantine dist/macos/KASTR.app` once.

Apple Silicon refuses to run unsigned Mach-O at all; PyInstaller ad-hoc signs
what it builds, and the in-app updater re-signs (`codesign --force --sign -`)
the executable it swaps in. If macOS says the app "is damaged", the quarantine
flag is the cause (`xattr` above).

Permissions:

- **Camera and microphone** prompts belong to **Chrome** (the page runs in
  the system Chrome): allow them there, and in System Settings -> Privacy &
  Security -> Camera / Microphone check Google Chrome.
- **Local Network** prompt belongs to KASTR (its relay/helpers talk to the
  LAN): allow it. Denying it silently breaks LAN relays and RTSP cameras.
- The firewall step (Windows netsh / Linux ufw) does not exist on the Mac;
  the macOS application firewall asks per binary when enabled.

Where things are:

| | |
|---|---|
| launcher log | `~/Library/Application Support/ASI/KASTR/launch.log` |
| state (relay-auth, rtsp-feeds, update-check.json, TLS CA) | `~/Library/Application Support/ASI/KASTR/` |
| browser profile | `~/Library/Application Support/ASI/KASTR/browser-profile` (system Chrome, own profile) |
| config | `KASTR.app/Contents/MacOS/kastr.ini` |
| from a terminal | `dist/macos/KASTR.app/Contents/MacOS/KASTR --no-browser --port 8000`, `--diagnose /tmp/kastr.txt` |

## 5. Smoke checklist (first run on a Mac)

1. App opens in Chrome as an app window; `/api/instance` says `platform:
   "darwin"`, version = VERSION.
2. Join a room on the Windows hub's relay; camera + mic prompts appear in
   Chrome; the Mac is seen from Windows.
3. Relay page -> Start relay: `bin/moq-relay` runs (Local Network prompt);
   a Windows KASTR pointed at `http://<mac>:4443` joins.
4. RTSP: with `brew install ffmpeg`, add a camera; the feed publishes via
   `bin/moq` (`launch.log` shows the pair).
5. Update: point `relay =` at a hub running a *different* version that
   already has `updates/macos/KASTR` -> within a minute `launch.log` shows
   `updating v… -> v…`, the app relaunches, `/api/instance` reports the hub's
   version. (Downgrade the same way to repeat.)

## 6. Release ritual with a Mac

The feed must be assembled where **all three** platform folders are present,
and the Mac has its own tree -- hence `--publish-only`:

1. **Windows**: set `VERSION` by hand, `python build.py --keep-version
   --publish` (builds `dist/windows`, refreshes `dist/updates`).
2. **WSL**: `python build.py --keep-version --publish` (adds `dist/linux`,
   both feeds now carry Windows + Linux). Then `./docker-build.sh` (DOCKER.md).
3. **Mac**: `./build-mac.sh` -> `dist/macos/KASTR.app` +
   `dist/archive/v<V>/KASTR-macos-v<V>.zip`.
4. Copy `dist/macos/` (at least `KASTR.app`, `BUILT_VERSION`, `kastr.ini`)
   and the macos zip back into the Windows tree (`dist/macos/`,
   `dist/archive/v<V>/`).
5. **Windows**: `python build.py --publish-only` -- no compile; every
   `dist/<plat>` whose `BUILT_VERSION` == `VERSION` goes into
   `dist/updates/<plat>/` + `latest.json` (`win32`, `linux`, `darwin`), and
   each `dist/<plat>/updates/` gets the other two binaries (a Mac hub serves
   Windows + Linux clients; the Windows hub now serves Macs). A folder at
   another version is named and skipped; a stale `dist/updates/<plat>` file
   left from an earlier release is warned about.
6. Hash check (the feed hands out exactly the file inside the bundle):

   ```bash
   # on the Mac, or WSL over /mnt/c
   shasum -a 256 dist/updates/macos/KASTR dist/macos/KASTR.app/Contents/MacOS/KASTR
   stat -f %z dist/updates/macos/KASTR            # macOS;  stat -c %s on Linux
   python -c "import json;print(json.load(open('dist/updates/latest.json'))['platforms']['darwin'])"
   curl -s http://<hub>:8000/api/update/manifest | python -m json.tool     # platforms.darwin: same size + sha256
   ```

   (PowerShell: `Get-FileHash dist\updates\macos\KASTR -Algorithm SHA256`,
   `(Get-Item dist\updates\macos\KASTR).Length`.)
7. Copy `dist/updates/` next to the hub's KASTR (or the hub is the Windows
   tree itself); Macs update on their next launch / hourly check.

The Mac steps gate the `darwin` entry of the feed, not the release: without
them steps 1-2 ship Windows + Linux exactly as before.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `build-mac.sh` refuses: `Refusing to build on x86_64` | Intel Mac -- unsupported (no arm64-only helpers would run) |
| `xcode-select: note: no developer tools were found` | `xcode-select --install`, then re-run |
| `moq-relay: FAILED (SHA-256 mismatch ...)` | the upstream asset changed under the pin; re-read the release's `SHA256SUMS` and update `MOQ_SHA` / `MOQ_CLI` in `fetch-helpers.py` |
| `ffmpeg: not downloaded on darwin` | expected until `FFMPEG_MAC` is pinned; `brew install ffmpeg` |
| the app bounces once and quits | run `dist/macos/KASTR.app/Contents/MacOS/KASTR` from Terminal and read the traceback / `launch.log` |
| "KASTR is damaged and can't be opened" | quarantine: `xattr -dr com.apple.quarantine dist/macos/KASTR.app` |
| no camera prompt | it is Chrome's prompt; check Chrome's site permission for `127.0.0.1:8000` and the system Camera pane |
| `--publish-only` says `skipping dist/macos: BUILT_VERSION says v…` | the Mac built another version than `VERSION` on Windows; rebuild on the Mac after syncing `VERSION` |
| `--publish-only` says `no KASTR.app/Contents/MacOS/KASTR in it` | the copy back lost the bundle's executable (or copied only the loose `dist/macos/KASTR`); copy the whole `.app` |
| updater: `has no darwin binary to offer` | the hub's `updates/macos/KASTR` is missing -- steps 4-5 not done, or `dist/updates` not copied to the hub |
