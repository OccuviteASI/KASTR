# -*- coding: utf-8 -*-
"""v0.21.92 ANDROID PROBE (Kenton 2026-10-28): a small test APK for the Yealink meeting devices (MeetingBar A25/A50 +
MeetingDisplay, MeetingBoard 86 Pro) that reports whether the real KASTR Android app could work there -- WebTransport,
WebCodecs decode (H.264 / HEVC, 1080p and 4K, prefer-hardware), the WebView, launcher / kiosk context, D-pad keys and
the boot receiver. Display-only build (Kenton's IT, same day): NO camera or microphone permissions or checks.

Source checks always run. The real build (android/probe/build.sh: javac + aapt2 + d8 + zipalign + apksigner) runs only
when WSL / the toolchain is present; it builds into a temp folder with a throwaway keystore, so the real
dist/android APK and its test key are never touched. No network."""
import os, re, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(HERE, "android", "probe")
SRC = os.path.join(PROBE, "src", "app", "kastr", "probe")
SDK_BT = "/opt/android-sdk/build-tools-34/android-14"
SDK_JAR = "/opt/android-sdk/platform-34/android-34/android.jar"


def read(*parts):
    with open(os.path.join(*parts), "rb") as f:
        return f.read().decode("utf-8")


def probe_files():
    out = []
    for root, _dirs, files in os.walk(os.path.join(HERE, "android")):
        for n in files:
            out.append(os.path.join(root, n))
    return out


class SourceTree(unittest.TestCase):
    longMessage = False
    def test_tree_exists(self):
        for rel in ("AndroidManifest.xml", "build.sh", "res/values/strings.xml", "res/values/styles.xml",
                    "res/drawable/banner.xml", "res/drawable/icon.xml", "assets/probe.html", "test/QrCodeTest.java"):
            self.assertTrue(os.path.isfile(os.path.join(PROBE, rel)), rel)
        for n in ("MainActivity", "BootReceiver", "NativeChecks", "Report", "QrCode"):
            self.assertTrue(os.path.isfile(os.path.join(SRC, n + ".java")), n)
        self.assertTrue(os.path.isfile(os.path.join(HERE, "android", "README.md")))

    def test_lf_line_endings(self):
        for p in probe_files():
            with open(p, "rb") as f:
                self.assertNotIn(b"\r\n", f.read(), p)

    def test_no_libraries(self):
        # plain Java + platform APIs only: no AndroidX / Gradle / third-party imports
        for p in probe_files():
            if p.endswith(".java"):
                for m in re.finditer(r"^import\s+([\w.]+)", read(p), re.M):
                    self.assertTrue(m.group(1).startswith(("android.", "java.", "org.json.")), (p, m.group(1)))
        self.assertFalse(any(os.path.basename(p).startswith(("build.gradle", "settings.gradle")) for p in probe_files()))


class Manifest(unittest.TestCase):
    longMessage = False
    @classmethod
    def setUpClass(cls):
        cls.m = read(PROBE, "AndroidManifest.xml")

    def test_permissions(self):
        perms = set(re.findall(r'uses-permission\s+android:name="android\.permission\.(\w+)"', self.m))
        self.assertEqual(perms, {"INTERNET", "ACCESS_NETWORK_STATE", "RECEIVE_BOOT_COMPLETED"})

    def test_display_only_no_camera_or_mic(self):
        for p in ("CAMERA", "RECORD_AUDIO"):
            self.assertNotIn("android.permission." + p, self.m)
        for p in probe_files():
            if p.endswith((".java", ".html")):
                t = read(p)
                self.assertNotIn(".getUserMedia(", t, p)
                self.assertNotIn("void onPermissionRequest", t, p)   # no override: WebView refuses camera / mic
                self.assertNotIn("CameraManager", t, p)
        self.assertIn("not checked (display-only build)", read(SRC, "Report.java"))
        self.assertIn("not checked (display-only build)", read(PROBE, "assets", "probe.html"))

    def test_launchers_and_banner(self):
        self.assertIn('android.intent.category.LAUNCHER"', self.m)
        self.assertIn('android.intent.category.LEANBACK_LAUNCHER"', self.m)
        self.assertRegex(self.m, r'android:banner="@drawable/banner"')
        self.assertRegex(self.m, r'android\.hardware\.touchscreen"\s+android:required="false"')
        self.assertRegex(self.m, r'android\.software\.leanback"\s+android:required="false"')

    def test_sdk_levels(self):
        self.assertIn('android:minSdkVersion="24"', self.m)
        self.assertIn('android:targetSdkVersion="34"', self.m)

    def test_boot_receiver_only_records(self):
        self.assertRegex(self.m, r'(?s)<receiver[^>]+\.BootReceiver.*?android\.intent\.action\.BOOT_COMPLETED')
        br = read(SRC, "BootReceiver.java")
        self.assertIn("boot_seen_at", br)
        for bad in ("startActivity", "startService", "startForegroundService", "Intent(context"):
            self.assertNotIn(bad, br)


class NoPrefill(unittest.TestCase):
    longMessage = False
    ALLOWED_HOSTS = {"appassets.androidplatform.net", "127.0.0.1", "schemas.android.com", "dl.google.com"}

    def test_host_field_starts_empty(self):
        ma = read(SRC, "MainActivity.java")
        self.assertIn('hostField.setText("")', ma)
        self.assertIn('hostField.setHint("https://<host>")', ma)
        self.assertNotIn("SharedPreferences", ma)   # the typed host is never remembered, so never prefilled later

    def test_no_real_hosts_or_codes(self):
        for p in probe_files():
            t = read(p)
            for host in re.findall(r"https?://([A-Za-z0-9.-]+)", t):
                self.assertIn(host, self.ALLOWED_HOSTS, (p, host))
            self.assertIsNone(re.search(r"madlabs|asirobots|kastr\.\w+\.app|trycloudflare", t, re.I), p)
            # no IPv4 addresses other than loopback (relay addresses are never baked in)
            for ip in re.findall(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", t):
                self.assertEqual(ip, "127.0.0.1", (p, ip))
            self.assertIsNone(re.search(r"[?&](code|token|roomCode|invite)=", t), p)


class BuildScript(unittest.TestCase):
    longMessage = False
    @classmethod
    def setUpClass(cls):
        cls.b = read(PROBE, "build.sh")

    def test_writes_dist_android(self):
        self.assertIn('OUTDIR="$REPO/dist/android"', self.b)
        self.assertIn('kastr-probe-$PROBE_VERSION.apk', self.b)
        self.assertIn('PROBE_VERSION="0.21.92"', self.b)

    def test_plain_toolchain_and_signing(self):
        for tool in ("javac", "aapt2", "d8", "zipalign", "apksigner"):
            self.assertIn(tool, self.b)
        self.assertIsNone(re.search(r"^\s*[^#\n]*\bgradlew?\b", self.b, re.M | re.I))   # never runs Gradle
        self.assertIn("--v1-signing-enabled true", self.b)
        self.assertIn("--v2-signing-enabled true", self.b)
        self.assertIn("/mnt/c/kastr-scratch/android/probe-test.keystore", self.b)
        self.assertIn('--ks-pass "file:$PASSFILE"', self.b)   # password from the 0600 file, never on the command line

    def test_dist_ignored(self):
        gi = read(HERE, ".gitignore")
        self.assertTrue(re.search(r"^/?dist/?$", gi, re.M) or "dist/android/" in gi)


def _runner():
    """How to run bash with the Android toolchain: directly on Linux, through WSL (as root) on Windows; or None."""
    if sys.platform.startswith("linux"):
        if shutil.which("javac") and os.path.isfile(SDK_JAR) and os.path.isfile(SDK_BT + "/aapt2"):
            return ["bash", "-c"]
        return None
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        return None
    try:
        r = subprocess.run([wsl, "-u", "root", "-e", "bash", "-c",
                            "command -v javac >/dev/null && test -f %s && test -x %s/aapt2 && echo ok" % (SDK_JAR, SDK_BT)],
                           capture_output=True, timeout=60)
    except Exception:
        return None
    if b"ok" not in r.stdout:
        return None
    return [wsl, "-u", "root", "--cd", HERE, "-e", "bash", "-c"]


class RealBuild(unittest.TestCase):
    longMessage = False
    def test_build_and_verify(self):
        run = _runner()
        if run is None:
            self.skipTest("WSL / JDK / Android build-tools not present")
        tmp = "/tmp/kastr-probe-test-%d" % os.getpid()
        script = ("set -e; rm -rf {t}; mkdir -p {t}; "
                  "PROBE_KEYSTORE={t}/throwaway.keystore PROBE_OUT={t}/probe.apk bash android/probe/build.sh; "
                  "{bt}/aapt2 dump badging {t}/probe.apk; rm -rf {t}").format(t=tmp, bt=SDK_BT)
        if run[0] == "bash":
            script = "cd %s && %s" % (HERE, script)
        r = subprocess.run(run + [script], capture_output=True, timeout=900)
        out = r.stdout.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, out[-3000:] + r.stderr.decode("utf-8", "replace")[-2000:])
        self.assertIn("QrCodeTest OK", out)
        self.assertIn("zipalign: ok", out)
        self.assertIn("Verified using v1 scheme (JAR signing): true", out)
        self.assertIn("Verified using v2 scheme (APK Signature Scheme v2): true", out)
        self.assertIn("package: name='app.kastr.probe' versionCode='2192' versionName='0.21.92'", out)
        self.assertIn("sdkVersion:'24'", out)
        self.assertIn("targetSdkVersion:'34'", out)
        self.assertIn("leanback-launchable-activity: name='app.kastr.probe.MainActivity'", out)
        self.assertNotIn("android.permission.CAMERA", out)
        self.assertNotIn("android.permission.RECORD_AUDIO", out)


if __name__ == "__main__":
    unittest.main()
