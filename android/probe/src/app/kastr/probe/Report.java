package app.kastr.probe;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Iterator;
import java.util.List;
import java.util.Locale;

/** Puts the native + browser-engine results into one report: JSON (saved / copied), readable text, and a compact QR form. */
final class Report {

    private Report() {}

    static JSONObject build(Context c, JSONObject nat, JSONObject basic, JSONObject full, List<String> errors, JSONObject host,
                            String lastKey, List<String> keysSeen, JSONObject kastrPage, long startedAt, boolean partial) throws Exception {
        JSONObject r = new JSONObject();
        r.put("probe", "probe " + MainActivity.VERSION);
        r.put("time", MainActivity.stamp(startedAt));
        r.put("tookSeconds", Math.round((System.currentTimeMillis() - startedAt) / 100.0) / 10.0);
        r.put("complete", !partial && full != null);
        JSONObject n = nat != null ? nat : new JSONObject();
        JSONObject device = n.optJSONObject("device");
        if (device != null) {
            JSONObject keys = new JSONObject();
            keys.put("lastKey", lastKey);
            keys.put("keysSeen", new JSONArray(keysSeen));
            keys.put("note", "press remote / D-pad / touch-panel keys before Run checks to see them here");
            device.put("keys", keys);
        }
        r.put("summary", summary(n, basic, full));
        r.put("device", device);
        r.put("launcher", n.optJSONObject("launcher"));
        JSONObject wv = n.optJSONObject("webView");
        if (wv == null) wv = new JSONObject();
        if (basic != null) wv.put("navigatorUserAgent", basic.optString("userAgent"));
        r.put("webView", wv);
        r.put("browserBasic", basic);
        r.put("browser", full);
        JSONObject net = n.optJSONObject("network");
        if (net == null) net = new JSONObject();
        net.put("relayHost", host != null ? host : new JSONObject().put("checked", "no (no host typed)"));
        r.put("network", net);
        r.put("cameraMic", "not checked (display-only build)");
        if (kastrPage.length() > 0) r.put("kastrPage", new JSONObject(kastrPage.toString()));
        r.put("problems", new JSONArray(errors));
        return r;
    }

    // ---------------- summary ----------------
    private static JSONObject summary(JSONObject nat, JSONObject basic, JSONObject full) throws Exception {
        JSONObject s = new JSONObject();
        String wt;
        JSONObject wto = full != null ? full.optJSONObject("webTransport") : null;
        if (wto != null) wt = wto.optString("verdict", "unknown");
        else if (basic != null) wt = "function".equals(basic.optJSONObject("types") != null ? basic.optJSONObject("types").optString("WebTransport") : "")
            ? "exists (not tried: second check part did not run)" : "absent";
        else wt = "not checked";
        s.put("webTransport", wt);
        JSONArray dec = full != null ? full.optJSONArray("videoDecode") : null;
        s.put("decodeH264_1080p", decodeLine(dec, "avc1", "1080p"));
        s.put("decodeH264_4K", decodeLine(dec, "avc1", "4K"));
        s.put("decodeHEVC_1080p", decodeLine(dec, "hev", "1080p"));
        s.put("decodeHEVC_4K", decodeLine(dec, "hev", "4K"));
        s.put("decodeVP9", decodeLine(dec, "vp09", null));
        s.put("decodeAV1", decodeLine(dec, "av01", null));
        JSONArray rt = full != null ? full.optJSONArray("decodeRoundTrip") : null;
        s.put("realDecode", roundTripLine(rt));
        JSONObject au = full != null ? full.optJSONObject("audio") : null;
        s.put("opusDecode", au != null ? au.optString("opusDecode") : "not checked");
        JSONObject f = full != null ? full.optJSONObject("features") : null;
        s.put("audioWorklet", f != null ? f.optString("audioWorklet") : "not checked");
        s.put("secureContext", basic != null ? String.valueOf(basic.optBoolean("secureContext")) : "not checked");
        JSONObject wv = nat.optJSONObject("webView");
        s.put("webView", wv != null ? wv.optString("package") + " " + wv.optString("versionName") : "unknown");
        s.put("cameraMic", "not checked (display-only build)");
        boolean wtOk = wt.startsWith("works");
        boolean h264 = s.optString("decodeH264_1080p").startsWith("yes");
        boolean opus = "yes".equals(s.optString("opusDecode"));
        String v;
        if (wtOk && h264 && opus) v = "YES - the KASTR page should be able to watch rooms here (try a real room with Open a KASTR page)";
        else if (wt.startsWith("exists") && h264 && opus) v = "MAYBE - WebTransport exists but did not prove itself; try a real room";
        else v = "NO - missing: " + (wtOk || wt.startsWith("exists") ? "" : "WebTransport ") + (h264 ? "" : "H.264 decode ") + (opus ? "" : "Opus decode");
        s.put("verdict", v.trim());
        return s;
    }

    private static boolean match(JSONObject row, String codecPrefix, String size) {
        String codec = row.optString("codec");
        boolean c = codecPrefix.equals("hev") ? (codec.startsWith("hev1") || codec.startsWith("hvc1")) : codec.startsWith(codecPrefix);
        return c && (size == null || size.equals(row.optString("size")));
    }

    private static String decodeLine(JSONArray rows, String codecPrefix, String size) {
        if (rows == null) return "not checked";
        boolean any = false, hw = false, sw = false, seen = false;
        for (int i = 0; i < rows.length(); i++) {
            JSONObject r = rows.optJSONObject(i);
            if (r == null || !match(r, codecPrefix, size)) continue;
            seen = true;
            any |= "yes".equals(r.optString("any"));
            hw |= "yes".equals(r.optString("hw"));
            sw |= "yes".equals(r.optString("sw"));
        }
        if (!seen) return "not checked";
        return (any ? "yes" : "no") + " (hardware: " + (hw ? "yes" : "no") + ", software: " + (sw ? "yes" : "no") + ")";
    }

    private static String roundTripLine(JSONArray rows) {
        if (rows == null) return "not checked";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < rows.length(); i++) {
            JSONObject r = rows.optJSONObject(i);
            if (r == null) continue;
            if (sb.length() > 0) sb.append("; ");
            sb.append(shortCodec(r.optString("codec"))).append(' ').append(r.optString("size")).append(' ')
                .append("prefer-hardware".equals(r.optString("decoderAcceleration")) ? "hw" : "any").append(": ")
                .append(r.optString("result"));
            if (r.has("msPerFrame")) sb.append(' ').append(r.optString("framesOut")).append('/').append(r.optString("framesIn"))
                .append(", ").append(r.optString("msPerFrame")).append(" ms/frame");
        }
        return sb.toString();
    }

    private static String shortCodec(String c) {
        if (c.startsWith("avc1")) return "H.264";
        if (c.startsWith("hvc1") || c.startsWith("hev1")) return "HEVC";
        return c;
    }

    // ---------------- readable text ----------------
    static String text(JSONObject r) {
        StringBuilder sb = new StringBuilder();
        sb.append(r.optString("probe")).append("   ").append(r.optString("time"))
            .append(r.optBoolean("complete") ? "" : "   (INCOMPLETE - see Problems)").append('\n');
        sb.append("camera / mic: not checked (display-only build)\n\n");
        section(sb, "SUMMARY", r.optJSONObject("summary"));
        section(sb, "DEVICE", r.optJSONObject("device"));
        section(sb, "LAUNCHER / KIOSK", r.optJSONObject("launcher"));
        section(sb, "WEBVIEW", r.optJSONObject("webView"));
        JSONObject b = r.optJSONObject("browser");
        if (b != null) {
            section(sb, "WEBTRANSPORT", b.optJSONObject("webTransport"));
            table(sb, "WEBCODECS DECODE  (isConfigSupported: default / prefer-hardware / prefer-software)", b.optJSONArray("videoDecode"), true);
            table(sb, "WEBCODECS ENCODE  (default / prefer-hardware)", b.optJSONArray("videoEncode"), false);
            JSONArray rt = b.optJSONArray("decodeRoundTrip");
            if (rt != null) {
                sb.append("REAL DECODE (30 frames encoded here, then decoded)\n");
                for (int i = 0; i < rt.length(); i++) {
                    JSONObject o = rt.optJSONObject(i);
                    if (o == null) continue;
                    sb.append("  ").append(pad(shortCodec(o.optString("codec")) + " " + o.optString("size"), 18))
                        .append(pad(o.optString("decoderAcceleration"), 17)).append(o.optString("result"));
                    if (o.has("msPerFrame")) sb.append("  ").append(o.optString("framesOut")).append('/').append(o.optString("framesIn"))
                        .append(" frames, ").append(o.optString("msPerFrame")).append(" ms/frame, out ").append(o.optString("out"));
                    sb.append('\n');
                }
                sb.append('\n');
            }
            section(sb, "AUDIO CODECS", b.optJSONObject("audio"));
            section(sb, "OTHER BROWSER FEATURES", b.optJSONObject("features"));
        } else {
            sb.append("BROWSER CHECKS: the full check did not run (see Problems)\n\n");
        }
        JSONObject basic = r.optJSONObject("browserBasic");
        if (basic != null) section(sb, "BROWSER BASICS", basic);
        section(sb, "NETWORK", r.optJSONObject("network"));
        JSONObject kp = r.optJSONObject("kastrPage");
        if (kp != null) section(sb, "LAST KASTR PAGE", kp);
        JSONArray p = r.optJSONArray("problems");
        sb.append("PROBLEMS\n");
        if (p == null || p.length() == 0) sb.append("  none\n");
        else for (int i = 0; i < p.length(); i++) sb.append("  - ").append(p.optString(i)).append('\n');
        return sb.toString();
    }

    private static void section(StringBuilder sb, String title, JSONObject o) {
        sb.append(title).append('\n');
        if (o == null) sb.append("  not checked\n");
        else dump(sb, o, "  ");
        sb.append('\n');
    }

    private static void dump(StringBuilder sb, JSONObject o, String ind) {
        Iterator<String> it = o.keys();
        while (it.hasNext()) {
            String k = it.next();
            if (k.equals("stage")) continue;
            Object v = o.opt(k);
            if (v instanceof JSONObject) {
                sb.append(ind).append(k).append(":\n");
                dump(sb, (JSONObject) v, ind + "  ");
            } else if (v instanceof JSONArray) {
                JSONArray a = (JSONArray) v;
                boolean simple = true;
                for (int i = 0; i < a.length(); i++) if (a.opt(i) instanceof JSONObject) simple = false;
                if (simple) {
                    sb.append(ind).append(k).append(": ");
                    if (a.length() == 0) sb.append("(none)");
                    for (int i = 0; i < a.length(); i++) sb.append(i == 0 ? "" : ", ").append(a.opt(i));
                    sb.append('\n');
                } else {
                    sb.append(ind).append(k).append(":\n");
                    for (int i = 0; i < a.length(); i++) {
                        Object e = a.opt(i);
                        if (e instanceof JSONObject) dump(sb, (JSONObject) e, ind + "  ");
                        else sb.append(ind).append("  ").append(e).append('\n');
                    }
                }
            } else {
                sb.append(ind).append(k).append(": ").append(v).append('\n');
            }
        }
    }

    private static void table(StringBuilder sb, String title, JSONArray rows, boolean decode) {
        sb.append(title).append('\n');
        if (rows == null) {
            sb.append("  not checked\n\n");
            return;
        }
        for (int i = 0; i < rows.length(); i++) {
            JSONObject o = rows.optJSONObject(i);
            if (o == null) continue;
            sb.append("  ").append(pad(o.optString("label"), 22)).append(pad(o.optString("size"), 7))
                .append(pad(o.optString("any"), 5)).append(pad(o.optString("hw"), 5));
            if (decode) sb.append(pad(o.optString("sw"), 5));
            sb.append("  ").append(o.optString("codec")).append('\n');
        }
        sb.append('\n');
    }

    private static String pad(String s, int n) {
        StringBuilder b = new StringBuilder(s);
        while (b.length() < n) b.append(' ');
        if (b.length() == n) return b.toString();
        return b.append(' ').toString();
    }

    // ---------------- compact (QR) ----------------
    static String compact(JSONObject r) throws Exception {
        JSONObject q = new JSONObject();
        q.put("p", MainActivity.VERSION);
        q.put("t", r.optString("time"));
        JSONObject d = r.optJSONObject("device");
        if (d != null) {
            q.put("mf", d.optString("manufacturer"));
            q.put("md", d.optString("model"));
            q.put("dv", d.optString("device"));
            q.put("a", d.optString("android") + "/" + d.optInt("sdkInt"));
            q.put("sp", d.optString("securityPatch"));
            JSONObject s = d.optJSONObject("screen");
            if (s != null) q.put("scr", s.optInt("widthPx") + "x" + s.optInt("heightPx") + "@" + s.optString("refreshHz") + "/" + s.optInt("densityDpi"));
            q.put("ui", d.optString("uiMode"));
            JSONObject in = d.optJSONObject("input");
            if (in != null) q.put("tch", in.optBoolean("touchscreenFeature") ? 1 : 0);
            JSONObject k = d.optJSONObject("keys");
            if (k != null) q.put("key", NativeChecks.clip(k.optString("lastKey"), 40));
        }
        JSONObject l = r.optJSONObject("launcher");
        if (l != null) {
            q.put("home", l.optString("defaultHome"));
            q.put("pk", NativeChecks.clip(join(l.optJSONArray("teamsYealinkZoomPackages")), 220));
            q.put("inst", l.optString("installer"));
            JSONObject b = l.optJSONObject("bootReceiver");
            if (b != null) q.put("boot", b.optBoolean("fired") ? 1 : 0);
        }
        JSONObject w = r.optJSONObject("webView");
        if (w != null) q.put("wv", w.optString("package") + " " + w.optString("versionName"));
        JSONObject s = r.optJSONObject("summary");
        if (s != null) {
            q.put("wt", s.optString("webTransport"));
            q.put("ok", s.optString("verdict").split(" ")[0]);
        }
        JSONObject br = r.optJSONObject("browser");
        if (br != null) {
            // decode codes: <codec>@<size>=<default><hw><sw> with Y/N/-, e.g. 640028@1080p=YYN
            StringBuilder dc = new StringBuilder();
            JSONArray dec = br.optJSONArray("videoDecode");
            if (dec != null) for (int i = 0; i < dec.length(); i++) {
                JSONObject o = dec.optJSONObject(i);
                if (o == null) continue;
                if (dc.length() > 0) dc.append(',');
                dc.append(codecKey(o.optString("codec"))).append('@').append(sz(o.optString("size"))).append('=')
                    .append(yn(o.optString("any"))).append(yn(o.optString("hw"))).append(yn(o.optString("sw")));
            }
            q.put("dec", dc.toString());
            StringBuilder ec = new StringBuilder();
            JSONArray enc = br.optJSONArray("videoEncode");
            if (enc != null) for (int i = 0; i < enc.length(); i++) {
                JSONObject o = enc.optJSONObject(i);
                if (o == null) continue;
                if (ec.length() > 0) ec.append(',');
                ec.append(codecKey(o.optString("codec"))).append('@').append(sz(o.optString("size"))).append('=')
                    .append(yn(o.optString("any"))).append(yn(o.optString("hw")));
            }
            q.put("enc", ec.toString());
            StringBuilder rc = new StringBuilder();
            JSONArray rt = br.optJSONArray("decodeRoundTrip");
            if (rt != null) for (int i = 0; i < rt.length(); i++) {
                JSONObject o = rt.optJSONObject(i);
                if (o == null) continue;
                if (rc.length() > 0) rc.append(',');
                rc.append(codecKey(o.optString("codec"))).append('@').append(sz(o.optString("size"))).append(
                    "prefer-hardware".equals(o.optString("decoderAcceleration")) ? "h" : "a").append('=')
                    .append("ok".equals(o.optString("result")) ? o.optString("msPerFrame") + "ms" : NativeChecks.clip(o.optString("result"), 12));
            }
            q.put("rt", rc.toString());
            JSONObject au = br.optJSONObject("audio");
            if (au != null) q.put("opus", yn(au.optString("opusDecode")) + yn(au.optString("opusEncodeMono")));
            JSONObject f = br.optJSONObject("features");
            if (f != null) {
                q.put("aw", yn(f.optString("audioWorklet")));
                q.put("gl2", yn(f.optString("webgl2")));
                q.put("gpu", NativeChecks.clip(f.optString("gpu"), 40));
            }
        }
        JSONObject n = r.optJSONObject("network");
        if (n != null) {
            q.put("net", n.optString("active"));
            JSONObject h = n.optJSONObject("relayHost");
            if (h != null && h.has("https")) q.put("rh", NativeChecks.clip(h.optString("dns") + "/" + h.optString("https"), 40));
        }
        q.put("cam", "not checked (display-only)");
        return q.toString();
    }

    /** 720p -> 7, 1080p / 1920x1080 -> 10, 4K / 3840x2160 -> 4k (keeps the QR small). */
    private static String sz(String s) {
        if (s.equals("720p") || s.equals("1280x720")) return "7";
        if (s.equals("1080p") || s.equals("1920x1080")) return "10";
        if (s.equals("4K") || s.equals("3840x2160")) return "4k";
        return s;
    }

    private static String codecKey(String c) {
        if (c.startsWith("avc1.")) return c.substring(5);
        if (c.startsWith("hvc1.1.6.") || c.startsWith("hev1.1.6.")) return c.substring(0, 4) + c.substring(9, c.indexOf(".B0") > 0 ? c.indexOf(".B0") : c.length());
        return c;
    }

    private static String yn(String v) {
        if (v == null || v.isEmpty()) return "-";
        String s = v.toLowerCase(Locale.US);
        if (s.startsWith("yes")) return "Y";
        if (s.startsWith("no") || s.startsWith("absent")) return "N";
        return "E";
    }

    private static String join(JSONArray a) {
        if (a == null) return "";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < a.length(); i++) {
            if (i > 0) sb.append(',');
            sb.append(a.optString(i));
        }
        return sb.toString();
    }
}
