package app.kastr.probe;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.UiModeManager;
import android.app.admin.DevicePolicyManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.InstallSourceInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.content.res.Configuration;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkInfo;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.InputDevice;
import android.webkit.WebSettings;
import android.webkit.WebView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.URL;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

/** The Android-side checks. Everything here only reads; nothing is changed on the device. */
final class NativeChecks {

    private NativeChecks() {}

    // ---------------- device ----------------
    static JSONObject device(Activity a) throws Exception {
        JSONObject o = new JSONObject();
        o.put("manufacturer", Build.MANUFACTURER);
        o.put("brand", Build.BRAND);
        o.put("model", Build.MODEL);
        o.put("device", Build.DEVICE);
        o.put("product", Build.PRODUCT);
        o.put("hardware", Build.HARDWARE);
        o.put("board", Build.BOARD);
        o.put("buildId", Build.DISPLAY);
        o.put("android", Build.VERSION.RELEASE);
        o.put("sdkInt", Build.VERSION.SDK_INT);
        o.put("securityPatch", Build.VERSION.SDK_INT >= 23 ? Build.VERSION.SECURITY_PATCH : "n/a (Android < 6)");
        JSONArray abis = new JSONArray();
        for (String s : Build.SUPPORTED_ABIS) abis.put(s);
        o.put("abis", abis);
        o.put("cpuCores", Runtime.getRuntime().availableProcessors());
        ActivityManager am = (ActivityManager) a.getSystemService(Context.ACTIVITY_SERVICE);
        if (am != null) {
            ActivityManager.MemoryInfo mi = new ActivityManager.MemoryInfo();
            am.getMemoryInfo(mi);
            o.put("ramMB", mi.totalMem / (1024 * 1024));
            o.put("lowRamDevice", am.isLowRamDevice());
        }

        // screen
        JSONObject scr = new JSONObject();
        Display d = a.getWindowManager().getDefaultDisplay();
        DisplayMetrics dm = new DisplayMetrics();
        d.getRealMetrics(dm);
        scr.put("widthPx", dm.widthPixels);
        scr.put("heightPx", dm.heightPixels);
        scr.put("densityDpi", dm.densityDpi);
        scr.put("density", dm.density);
        scr.put("widthDp", Math.round(dm.widthPixels / dm.density));
        scr.put("heightDp", Math.round(dm.heightPixels / dm.density));
        scr.put("refreshHz", round1(d.getRefreshRate()));
        if (Build.VERSION.SDK_INT >= 23) {
            JSONArray modes = new JSONArray();
            for (Display.Mode m : d.getSupportedModes()) {
                modes.put(m.getPhysicalWidth() + "x" + m.getPhysicalHeight() + "@" + round1(m.getRefreshRate()));
            }
            scr.put("modes", modes);
            Display.Mode cur = d.getMode();
            scr.put("currentMode", cur.getPhysicalWidth() + "x" + cur.getPhysicalHeight() + "@" + round1(cur.getRefreshRate()));
        }
        Display.HdrCapabilities hdr = d.getHdrCapabilities();
        JSONArray hdrTypes = new JSONArray();
        if (hdr != null) {
            for (int t : hdr.getSupportedHdrTypes()) hdrTypes.put(hdrName(t));
        }
        scr.put("hdr", hdrTypes);
        o.put("screen", scr);

        // input
        PackageManager pm = a.getPackageManager();
        JSONObject in = new JSONObject();
        in.put("touchscreenFeature", pm.hasSystemFeature(PackageManager.FEATURE_TOUCHSCREEN));
        in.put("fakeTouchFeature", pm.hasSystemFeature(PackageManager.FEATURE_FAKETOUCH));
        in.put("leanbackFeature", pm.hasSystemFeature(PackageManager.FEATURE_LEANBACK));
        in.put("touchscreenConfig", touchName(a.getResources().getConfiguration().touchscreen));
        in.put("navigationConfig", navName(a.getResources().getConfiguration().navigation));
        boolean touchDevice = false;
        JSONArray devs = new JSONArray();
        for (int id : InputDevice.getDeviceIds()) {
            InputDevice dev = InputDevice.getDevice(id);
            if (dev == null) continue;
            int s = dev.getSources();
            List<String> kinds = new ArrayList<>();
            if ((s & InputDevice.SOURCE_TOUCHSCREEN) == InputDevice.SOURCE_TOUCHSCREEN) { kinds.add("touchscreen"); touchDevice = true; }
            if ((s & InputDevice.SOURCE_DPAD) == InputDevice.SOURCE_DPAD) kinds.add("dpad");
            if ((s & InputDevice.SOURCE_KEYBOARD) == InputDevice.SOURCE_KEYBOARD) kinds.add("keys");
            if ((s & InputDevice.SOURCE_MOUSE) == InputDevice.SOURCE_MOUSE) kinds.add("mouse");
            if ((s & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD) kinds.add("gamepad");
            if ((s & InputDevice.SOURCE_TOUCHPAD) == InputDevice.SOURCE_TOUCHPAD) kinds.add("touchpad");
            if (dev.isVirtual()) kinds.add("virtual");
            devs.put(dev.getName() + " [" + join(kinds, ",") + "] " + String.format(Locale.US, "%04x:%04x", dev.getVendorId(), dev.getProductId()));
        }
        in.put("touchscreenDeviceFound", touchDevice);
        in.put("devices", devs);
        o.put("input", in);

        UiModeManager um = (UiModeManager) a.getSystemService(Context.UI_MODE_SERVICE);
        int mode = um != null ? um.getCurrentModeType() : -1;
        o.put("uiMode", uiModeName(mode));
        o.put("isTv", mode == Configuration.UI_MODE_TYPE_TELEVISION);
        return o;
    }

    // ---------------- launcher / kiosk context ----------------
    static JSONObject launcher(Context c) throws Exception {
        JSONObject o = new JSONObject();
        PackageManager pm = c.getPackageManager();
        String me = c.getPackageName();
        Intent home = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME);
        ResolveInfo def = pm.resolveActivity(home, PackageManager.MATCH_DEFAULT_ONLY);
        String defPkg = def != null && def.activityInfo != null ? def.activityInfo.packageName : null;
        if ("android".equals(defPkg)) defPkg = "none set (Android shows a chooser)";
        o.put("defaultHome", defPkg == null ? "unknown" : defPkg);
        o.put("thisAppIsDefaultHome", me.equals(defPkg));
        JSONArray homes = new JSONArray();
        for (ResolveInfo ri : pm.queryIntentActivities(home, 0)) homes.put(ri.activityInfo.packageName);
        o.put("homeApps", homes);

        List<String> hits = new ArrayList<>();
        List<ApplicationInfo> apps = pm.getInstalledApplications(0);
        for (ApplicationInfo ai : apps) {
            String n = ai.packageName.toLowerCase(Locale.US);
            if (n.contains("teams") || n.contains("yealink") || n.contains("zoom")) hits.add(ai.packageName);
        }
        Collections.sort(hits);
        o.put("teamsYealinkZoomPackages", new JSONArray(hits));
        o.put("visiblePackageCount", apps.size());
        if (Build.VERSION.SDK_INT >= 30) {
            o.put("packageVisibilityNote", "Android 11+: only apps with a launcher, TV-launcher or home entry are visible to this probe");
        }
        o.put("installer", installer(pm, me));

        if (Build.VERSION.SDK_INT >= 23) {
            ActivityManager am = (ActivityManager) c.getSystemService(Context.ACTIVITY_SERVICE);
            if (am != null) {
                int lt = am.getLockTaskModeState();
                o.put("lockTaskMode", lt == ActivityManager.LOCK_TASK_MODE_NONE ? "none" : lt == ActivityManager.LOCK_TASK_MODE_LOCKED ? "locked (kiosk)" : "pinned");
            }
            DevicePolicyManager dpm = (DevicePolicyManager) c.getSystemService(Context.DEVICE_POLICY_SERVICE);
            if (dpm != null) o.put("lockTaskPermittedForThisApp", dpm.isLockTaskPermitted(me));
            o.put("canDrawOverlays", Settings.canDrawOverlays(c));
            PowerManager pw = (PowerManager) c.getSystemService(Context.POWER_SERVICE);
            if (pw != null) o.put("ignoringBatteryOptimizations", pw.isIgnoringBatteryOptimizations(me));
        }
        SharedPreferences p = c.getSharedPreferences(BootReceiver.PREFS, Context.MODE_PRIVATE);
        long boot = p.getLong("boot_seen_at", 0);
        JSONObject b = new JSONObject();
        b.put("fired", boot != 0);
        b.put("bootSeenAt", boot == 0 ? "not seen yet (restart the device once after the first launch)" : MainActivity.stamp(boot));
        b.put("count", p.getInt("boot_count", 0));
        o.put("bootReceiver", b);
        return o;
    }

    private static String installer(PackageManager pm, String pkg) {
        try {
            String who;
            if (Build.VERSION.SDK_INT >= 30) {
                InstallSourceInfo si = pm.getInstallSourceInfo(pkg);
                who = si.getInstallingPackageName();
                String init = si.getInitiatingPackageName();
                if (init != null && !init.equals(who)) who = who + " (started by " + init + ")";
            } else {
                who = pm.getInstallerPackageName(pkg);
            }
            return who == null ? "none recorded (adb or a file installer that does not say)" : who;
        } catch (Exception e) {
            return "unknown (" + e.getClass().getSimpleName() + ")";
        }
    }

    // ---------------- WebView package ----------------
    static JSONObject webView(Context c) throws Exception {
        JSONObject o = new JSONObject();
        PackageInfo pi = null;
        if (Build.VERSION.SDK_INT >= 26) {
            pi = WebView.getCurrentWebViewPackage();
            o.put("source", "WebView.getCurrentWebViewPackage()");
        } else {
            for (String n : new String[] {"com.google.android.webview", "com.android.webview", "com.android.chrome"}) {
                try {
                    pi = c.getPackageManager().getPackageInfo(n, 0);
                    o.put("source", "installed package (Android < 8 has no getCurrentWebViewPackage)");
                    break;
                } catch (PackageManager.NameNotFoundException ignored) {
                    // try the next
                }
            }
        }
        o.put("package", pi == null ? "unknown" : pi.packageName);
        o.put("versionName", pi == null ? "unknown" : pi.versionName);
        try {
            o.put("defaultUserAgent", WebSettings.getDefaultUserAgent(c));
        } catch (Exception e) {
            o.put("defaultUserAgent", "error " + e.getClass().getSimpleName());
        }
        return o;
    }

    // ---------------- network ----------------
    @SuppressWarnings("deprecation")
    static JSONObject network(Context c) throws Exception {
        JSONObject o = new JSONObject();
        ConnectivityManager cm = (ConnectivityManager) c.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) {
            o.put("active", "no connectivity service");
            return o;
        }
        Network n = cm.getActiveNetwork();
        if (n == null) {
            o.put("active", "none (offline)");
            return o;
        }
        NetworkCapabilities nc = cm.getNetworkCapabilities(n);
        List<String> t = new ArrayList<>();
        if (nc != null) {
            if (nc.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) t.add("ethernet");
            if (nc.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) t.add("wifi");
            if (nc.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) t.add("cellular");
            if (nc.hasTransport(NetworkCapabilities.TRANSPORT_BLUETOOTH)) t.add("bluetooth");
            if (nc.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) t.add("vpn");
            o.put("validated", nc.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED));
            o.put("notMetered", nc.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED));
            o.put("downKbps", nc.getLinkDownstreamBandwidthKbps());
            o.put("upKbps", nc.getLinkUpstreamBandwidthKbps());
        }
        NetworkInfo ni = cm.getNetworkInfo(n);
        if (t.isEmpty() && ni != null) t.add(ni.getTypeName());
        o.put("active", t.isEmpty() ? "unknown" : join(t, "+"));
        LinkProperties lp = cm.getLinkProperties(n);
        if (lp != null) {
            o.put("interface", lp.getInterfaceName());
            o.put("dnsServerCount", lp.getDnsServers().size());
            if (Build.VERSION.SDK_INT >= 28) o.put("privateDns", lp.isPrivateDnsActive() ? "on" : "off");
        }
        return o;
    }

    /** Turns what the person typed into an https origin, or null when it is not usable. */
    static String origin(String typed) {
        if (typed == null) return null;
        String s = typed.trim();
        if (s.isEmpty()) return null;
        if (!s.contains("://")) s = "https://" + s;
        try {
            URL u = new URL(s);
            if (u.getHost() == null || u.getHost().isEmpty()) return null;
            String proto = u.getProtocol().toLowerCase(Locale.US);
            if (!proto.equals("https") && !proto.equals("http")) return null;
            return proto + "://" + u.getHost() + (u.getPort() > 0 ? ":" + u.getPort() : "");
        } catch (Exception e) {
            return null;
        }
    }

    /** DNS + HTTPS reach to the typed host. Runs on a worker thread. */
    static JSONObject hostReach(String origin) {
        JSONObject o = new JSONObject();
        try {
            o.put("origin", origin);
            URL u = new URL(origin + "/moq-watch-lite.html");
            long t0 = System.nanoTime();
            try {
                InetAddress[] addrs = InetAddress.getAllByName(u.getHost());
                JSONArray a = new JSONArray();
                for (int i = 0; i < addrs.length && i < 4; i++) a.put(addrs[i].getHostAddress());
                o.put("dns", "ok");
                o.put("addresses", a);
            } catch (Exception e) {
                o.put("dns", "failed " + e.getClass().getSimpleName());
            }
            o.put("dnsMs", (System.nanoTime() - t0) / 1000000);
            long t1 = System.nanoTime();
            HttpURLConnection h = null;
            try {
                h = (HttpURLConnection) u.openConnection();
                h.setConnectTimeout(8000);
                h.setReadTimeout(8000);
                h.setInstanceFollowRedirects(false);
                h.setRequestProperty("Cache-Control", "no-cache");
                int code = h.getResponseCode();
                o.put("https", "HTTP " + code);
                o.put("page", code == 200 ? "moq-watch-lite.html served" : "status " + code);
                String ct = h.getContentType();
                if (ct != null) o.put("contentType", ct);
                String alt = h.getHeaderField("alt-svc");
                if (alt != null) o.put("altSvc", alt.length() > 80 ? alt.substring(0, 80) : alt);
                InputStream is = code < 400 ? h.getInputStream() : h.getErrorStream();
                if (is != null) {
                    byte[] buf = new byte[8192];
                    long total = 0;
                    int r;
                    while ((r = is.read(buf)) > 0 && total < 4_000_000) total += r;
                    is.close();
                    o.put("bytes", total);
                }
            } catch (Exception e) {
                o.put("https", "failed " + e.getClass().getSimpleName() + ": " + clip(e.getMessage(), 140));
            } finally {
                if (h != null) h.disconnect();
            }
            o.put("httpsMs", (System.nanoTime() - t1) / 1000000);
            o.put("note", "this is TCP HTTPS only; WebTransport needs UDP 443 too, which only the KASTR page itself proves");
        } catch (Exception e) {
            try {
                o.put("error", e.getClass().getSimpleName());
            } catch (Exception ignored) {
                // nothing more to say
            }
        }
        return o;
    }

    // ---------------- helpers ----------------
    static String clip(String s, int n) {
        if (s == null) return "";
        return s.length() > n ? s.substring(0, n) + "..." : s;
    }

    static String join(List<String> l, String sep) {
        StringBuilder sb = new StringBuilder();
        for (String s : l) {
            if (sb.length() > 0) sb.append(sep);
            sb.append(s);
        }
        return sb.toString();
    }

    private static double round1(float f) {
        return Math.round(f * 10) / 10.0;
    }

    private static String hdrName(int t) {
        switch (t) {
            case Display.HdrCapabilities.HDR_TYPE_DOLBY_VISION: return "Dolby Vision";
            case Display.HdrCapabilities.HDR_TYPE_HDR10: return "HDR10";
            case Display.HdrCapabilities.HDR_TYPE_HLG: return "HLG";
            case 4: return "HDR10+";
            default: return "type " + t;
        }
    }

    private static String uiModeName(int m) {
        switch (m) {
            case Configuration.UI_MODE_TYPE_NORMAL: return "normal";
            case Configuration.UI_MODE_TYPE_DESK: return "desk";
            case Configuration.UI_MODE_TYPE_CAR: return "car";
            case Configuration.UI_MODE_TYPE_TELEVISION: return "television";
            case Configuration.UI_MODE_TYPE_APPLIANCE: return "appliance";
            case Configuration.UI_MODE_TYPE_WATCH: return "watch";
            case 7: return "vr";
            default: return "unknown " + m;
        }
    }

    private static String touchName(int t) {
        switch (t) {
            case Configuration.TOUCHSCREEN_NOTOUCH: return "no touch";
            case Configuration.TOUCHSCREEN_FINGER: return "finger";
            default: return "undefined";
        }
    }

    private static String navName(int n) {
        switch (n) {
            case Configuration.NAVIGATION_NONAV: return "none";
            case Configuration.NAVIGATION_DPAD: return "dpad";
            case Configuration.NAVIGATION_TRACKBALL: return "trackball";
            case Configuration.NAVIGATION_WHEEL: return "wheel";
            default: return "undefined";
        }
    }
}
