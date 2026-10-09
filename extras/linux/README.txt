KASTR for Linux (x86-64)
========================

From a terminal:

  chmod +x KASTR
  ./KASTR

From the GUI: run `sh install.sh` once -- it puts KASTR in your
applications menu (with its icon), launching the binary from this folder.
Double-clicking the raw binary in Files does nothing; GNOME refuses to run
binaries by design, and the launcher is the Linux answer to that.

Self-contained: the web UI, ffmpeg (RTSP ingest), moq-relay (relay hosting),
moq (native RTSP publishing) and the browser engine itself are all in this
folder. Nothing to install.

On a person's desktop the window opens in your default browser when it is
Chromium-based (Chrome, Chromium, Edge, Brave, Vivaldi, Opera), with your own
profile, so you can share your browser tabs. Otherwise -- and always on relay,
hub, spoke, Publisher and Viewer boxes and on machines that share cameras --
it is KASTR's own bundled Chromium (browser/, a pinned Chrome for Testing with
its own profile), so no system browser is needed. `browser = bundled` in
kastr.ini always uses the bundled one. If some tool
unpacked this folder without execute permissions, KASTR restores them on
launch and install.sh does too. Should the bundled browser fail to start
(missing desktop libraries -- install.sh lists them), KASTR retries without
its sandbox, then tries a system Chrome/Chromium/Edge, and only then shows a
dialog with the reason and the URL. Firefox cannot run KASTR: the window
relies on --app/--user-data-dir, WebCodecs and WebTransport.

Ubuntu's default Chromium is a snap, and snap confinement denies it access
to hidden folders in your home directory -- so with a snap browser, KASTR
keeps its browser profile (saved name, rooms, window size) under
~/snap/chromium/common/kastr-profile instead. The launch output and
--diagnose show which profile is in use. A .deb Chrome/Chromium is
preferred automatically when both are installed.

Running as root (common on robot/industrial boxes) is handled: Chromium
refuses its sandbox as root (crbug.com/638180), so KASTR passes
--no-sandbox automatically in that case. The window only loads KASTR's own
local pages.

Headless machines (no $DISPLAY / $WAYLAND_DISPLAY -- servers, SSH sessions,
root shells without the desktop's environment) are handled too: KASTR
serves without a window and prints the URLs. To reach the UI from another
computer, start it with:
  ./KASTR --host 0.0.0.0
and open http://<this-machine's-ip>:8000 there.

  ./KASTR --no-browser --port 8000     serve only, open the URL yourself
  ./KASTR --relay http://host:4443     point at a different relay
  ./KASTR --diagnose /tmp/kastr.txt    write resolved paths and config, then exit

kastr.ini next to the binary overrides the defaults; see the comments in it.

Built and tested on Ubuntu 26.04 (glibc 2.43). It is dynamically linked against
glibc, so a much older distro may refuse it -- rebuild there with:
  python3 fetch-helpers.py && python3 build.py
