package app.kastr.probe;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.text.InputType;
import android.util.DisplayMetrics;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.webkit.JavascriptInterface;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * KASTR probe: one screen, usable by touch and by a TV remote / D-pad. Run checks -> report on screen (+ QR), Save,
 * Copy, and "Open a KASTR page" to try a real room in the same WebView. Display-only build: no camera or microphone.
 */
public final class MainActivity extends Activity {

    static final String PROBE_HOST = "appassets.androidplatform.net";
    static final String PROBE_URL = "https://" + PROBE_HOST + "/probe.html";
    private static final long CHECK_TIMEOUT_MS = 150_000;

    private final Handler ui = new Handler(Looper.getMainLooper());

    private LinearLayout header;
    private LinearLayout kastrBar;
    private TextView kastrUrl;
    private TextView status;
    private TextView keyLine;
    private EditText hostField;
    private Button runBtn;
    private ScrollView reportScroll;
    private TextView reportView;
    private FrameLayout content;
    private WebView web;
    private ImageView qrView;

    // check state
    private boolean running;
    private int runId;
    private JSONObject nativePart;
    private JSONObject jsBasic;
    private JSONObject jsFull;
    private final List<String> jsErrors = new ArrayList<>();
    private JSONObject hostPart;
    private boolean hostPending;
    private long startedAt;

    // results
    private JSONObject report;
    private String reportText = "";
    private String compact = "";

    // keys and KASTR page
    private String lastKey = "none yet";
    private final LinkedHashSet<String> keysSeen = new LinkedHashSet<>();
    private boolean kastrMode;
    private final JSONObject kastrPage = new JSONObject();

    static final String VERSION = BuildInfo.VERSION;

    // ================= lifecycle =================
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        buildUi();
        reportView.setText("KASTR probe " + VERSION + "  (" + stamp(System.currentTimeMillis()) + ")\n\n"
            + "This is a test app, not KASTR. It checks whether this device can run the KASTR page.\n\n"
            + "Press  Run checks  (OK on the remote, or tap it).\n"
            + "Optional: type a relay host address first (https://<host>) to also test reaching it.\n"
            + "Then Save report or Copy report, or photograph the QR code, and send it back.\n\n"
            + "camera / mic: not checked (display-only build)");
        runBtn.requestFocus();
    }

    @Override
    protected void onDestroy() {
        ui.removeCallbacksAndMessages(null);
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }

    // ================= UI =================
    private int dp(float v) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics()));
    }

    private static final int BG = 0xFF10151C;
    private static final int ACCENT = 0xFF2F80ED;

    private Drawable focusable(int fill, int pressed) {
        StateListDrawable s = new StateListDrawable();
        GradientDrawable focused = new GradientDrawable();
        focused.setColor(ACCENT);
        focused.setCornerRadius(dp(10));
        focused.setStroke(dp(5), Color.WHITE);
        GradientDrawable press = new GradientDrawable();
        press.setColor(pressed);
        press.setCornerRadius(dp(10));
        press.setStroke(dp(5), Color.WHITE);
        GradientDrawable normal = new GradientDrawable();
        normal.setColor(fill);
        normal.setCornerRadius(dp(10));
        normal.setStroke(dp(2), 0xFF3A4A60);
        s.addState(new int[] {android.R.attr.state_pressed}, press);
        s.addState(new int[] {android.R.attr.state_focused}, focused);
        s.addState(new int[] {}, normal);
        return s;
    }

    private Button button(String label, View.OnClickListener l) {
        Button btn = new Button(this);
        btn.setText(label);
        btn.setAllCaps(false);
        btn.setTextColor(Color.WHITE);
        btn.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        btn.setTypeface(Typeface.DEFAULT_BOLD);
        btn.setBackground(focusable(0xFF253041, 0xFF1B5BB0));
        btn.setPadding(dp(22), dp(12), dp(22), dp(12));
        btn.setMinHeight(dp(64));
        btn.setFocusable(true);
        btn.setOnClickListener(l);
        if (Build.VERSION.SDK_INT >= 21) btn.setStateListAnimator(null);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, 0, dp(14), 0);
        btn.setLayoutParams(lp);
        return btn;
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.setPadding(dp(20), dp(14), dp(20), dp(14));

        header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);

        TextView title = new TextView(this);
        title.setText("KASTR probe " + VERSION);
        title.setTextColor(Color.WHITE);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 26);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        header.addView(title);

        keyLine = new TextView(this);
        keyLine.setTextColor(0xFFB8C7DA);
        keyLine.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
        keyLine.setText("Last key: none yet (press a remote / D-pad key to test it)");
        header.addView(keyLine);

        HorizontalScrollView hs = new HorizontalScrollView(this);
        hs.setFocusable(false);
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, dp(10), 0, dp(10));
        runBtn = button("Run checks", v -> runChecks());
        row.addView(runBtn);
        row.addView(button("Open a KASTR page", v -> openKastr()));
        row.addView(button("Save report", v -> saveReport()));
        row.addView(button("Copy report", v -> copyReport()));
        row.addView(button("QR code", v -> showQr()));
        hs.addView(row);
        header.addView(hs);

        LinearLayout hostRow = new LinearLayout(this);
        hostRow.setOrientation(LinearLayout.HORIZONTAL);
        hostRow.setGravity(Gravity.CENTER_VERTICAL);
        TextView hl = new TextView(this);
        hl.setText("Relay host: ");
        hl.setTextColor(Color.WHITE);
        hl.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        hostRow.addView(hl);
        hostField = new EditText(this);
        hostField.setHint("https://<host>");
        hostField.setText("");
        hostField.setSingleLine(true);
        hostField.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        hostField.setImeOptions(EditorInfo.IME_ACTION_GO);
        hostField.setTextColor(Color.WHITE);
        hostField.setHintTextColor(0xFF7A8BA3);
        hostField.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        hostField.setBackground(focusable(0xFF1A222D, 0xFF1A222D));
        hostField.setPadding(dp(16), dp(10), dp(16), dp(10));
        hostField.setOnEditorActionListener((v, actionId, ev) -> {
            if (actionId == EditorInfo.IME_ACTION_GO || actionId == EditorInfo.IME_ACTION_DONE
                || (actionId == EditorInfo.IME_NULL && ev != null && ev.getAction() == KeyEvent.ACTION_DOWN)) {
                openKastr();
                return true;
            }
            return false;
        });
        hostRow.addView(hostField, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        header.addView(hostRow);

        status = new TextView(this);
        status.setTextColor(0xFFFFD27F);
        status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        status.setPadding(0, dp(6), 0, dp(6));
        header.addView(status);
        root.addView(header);

        kastrBar = new LinearLayout(this);
        kastrBar.setOrientation(LinearLayout.HORIZONTAL);
        kastrBar.setGravity(Gravity.CENTER_VERTICAL);
        kastrBar.setPadding(0, 0, 0, dp(8));
        kastrBar.addView(button("Back to report", v -> closeKastr()));
        kastrUrl = new TextView(this);
        kastrUrl.setTextColor(0xFFB8C7DA);
        kastrUrl.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        kastrBar.addView(kastrUrl);
        kastrBar.setVisibility(View.GONE);
        root.addView(kastrBar);

        content = new FrameLayout(this);
        reportScroll = new ScrollView(this);
        reportScroll.setFocusable(true);
        reportScroll.setBackground(focusable(0xFF161D27, 0xFF161D27));
        reportScroll.setPadding(dp(14), dp(10), dp(14), dp(10));
        reportView = new TextView(this);
        reportView.setTextColor(0xFFE8EEF6);
        reportView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 19);
        reportView.setTypeface(Typeface.MONOSPACE);
        reportView.setTextIsSelectable(false);
        reportScroll.addView(reportView);
        content.addView(reportScroll, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        qrView = new ImageView(this);
        qrView.setBackgroundColor(Color.WHITE);
        qrView.setScaleType(ImageView.ScaleType.CENTER);
        qrView.setFocusable(true);
        qrView.setVisibility(View.GONE);
        qrView.setOnClickListener(v -> hideQr());
        content.addView(qrView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        root.addView(content, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(root);
        createWebView();
    }

    private void createWebView() {
        if (web != null) {
            content.removeView(web);
            web.destroy();
        }
        web = new WebView(this);
        web.setBackgroundColor(BG);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setSupportZoom(false);
        WebView.setWebContentsDebuggingEnabled(true);   // chrome://inspect over adb helps when a room does not work
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new WebChromeClient());   // no onPermissionRequest: camera / mic requests are refused
        web.setVisibility(View.GONE);
        content.addView(web, 0, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private void showView(View v) {
        reportScroll.setVisibility(v == reportScroll ? View.VISIBLE : View.GONE);
        web.setVisibility(v == web ? View.VISIBLE : View.GONE);
        qrView.setVisibility(v == qrView ? View.VISIBLE : View.GONE);
    }

    private void say(String s) {
        status.setText(s);
    }

    // ================= keys =================
    private static boolean isConfirm(int k) {
        return k == KeyEvent.KEYCODE_DPAD_CENTER || k == KeyEvent.KEYCODE_ENTER || k == KeyEvent.KEYCODE_NUMPAD_ENTER
            || k == KeyEvent.KEYCODE_BUTTON_A;
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        int k = e.getKeyCode();
        if (e.getAction() == KeyEvent.ACTION_DOWN && e.getRepeatCount() == 0) {
            String name = KeyEvent.keyCodeToString(k);
            String dev = e.getDevice() != null ? e.getDevice().getName() : "unknown device";
            lastKey = k + " " + name + " (from " + dev + ")";
            if (keysSeen.size() < 60) keysSeen.add(name);
            keyLine.setText("Last key: " + lastKey);
        }
        if (k == KeyEvent.KEYCODE_BACK) {
            if (qrView.getVisibility() == View.VISIBLE || kastrMode) {
                if (e.getAction() == KeyEvent.ACTION_UP) handleBack();
                return true;
            }
        }
        if (qrView.getVisibility() == View.VISIBLE && isConfirm(k)) {
            if (e.getAction() == KeyEvent.ACTION_UP) hideQr();
            return true;
        }
        View f = getCurrentFocus();
        if (isConfirm(k) && f instanceof Button) {
            // OK / Enter always activates the focused button, once, on release
            if (e.getAction() == KeyEvent.ACTION_UP && !e.isCanceled()) f.performClick();
            return true;
        }
        return super.dispatchKeyEvent(e);
    }

    @Override
    public void onBackPressed() {
        if (!handleBack()) super.onBackPressed();
    }

    private boolean handleBack() {
        if (qrView.getVisibility() == View.VISIBLE) {
            hideQr();
            return true;
        }
        if (kastrMode) {
            closeKastr();
            return true;
        }
        return false;
    }

    // ================= checks =================
    private void runChecks() {
        if (kastrMode) closeKastr();
        if (running) {
            say("Checks are already running...");
            return;
        }
        running = true;
        runId++;
        final int myRun = runId;
        startedAt = System.currentTimeMillis();
        jsBasic = null;
        jsFull = null;
        jsErrors.clear();
        hostPart = null;
        say("Running checks... (about 30-90 s; the browser engine checks run in the panel below)");
        try {
            nativePart = new JSONObject();
            nativePart.put("device", NativeChecks.device(this));
            nativePart.put("launcher", NativeChecks.launcher(this));
            nativePart.put("webView", NativeChecks.webView(this));
            nativePart.put("network", NativeChecks.network(this));
        } catch (Exception ex) {
            jsErrors.add("native checks: " + ex.getClass().getSimpleName() + " " + ex.getMessage());
        }
        final String origin = NativeChecks.origin(hostField.getText().toString());
        hostPending = origin != null;
        if (origin != null) {
            new Thread(() -> {
                JSONObject r = NativeChecks.hostReach(origin);
                ui.post(() -> {
                    if (myRun != runId) return;
                    hostPart = r;
                    hostPending = false;
                    maybeFinish();
                });
            }, "probe-host").start();
        }
        web.removeJavascriptInterface("KastrProbe");
        web.addJavascriptInterface(new Bridge(myRun), "KastrProbe");
        showView(web);
        web.loadUrl(PROBE_URL);
        ui.postDelayed(() -> {
            if (running && myRun == runId) {
                jsErrors.add("browser checks did not finish within " + (CHECK_TIMEOUT_MS / 1000) + " s");
                hostPending = false;
                finishChecks(true);
            }
        }, CHECK_TIMEOUT_MS);
    }

    /** Called from the probe page (a binder thread); everything is handed to the UI thread. */
    private final class Bridge {
        private final int run;

        Bridge(int run) {
            this.run = run;
        }

        @JavascriptInterface
        public void basic(String json) {
            ui.post(() -> {
                if (run != runId || !running) return;
                try {
                    jsBasic = new JSONObject(json);
                } catch (Exception e) {
                    jsErrors.add("basic result unreadable");
                }
            });
        }

        @JavascriptInterface
        public void full(String json) {
            ui.post(() -> {
                if (run != runId || !running) return;
                try {
                    jsFull = new JSONObject(json);
                } catch (Exception e) {
                    jsErrors.add("full result unreadable");
                }
                maybeFinish();
            });
        }

        @JavascriptInterface
        public void progress(String what) {
            ui.post(() -> {
                if (run == runId && running) say("Running checks: " + NativeChecks.clip(what, 60) + " ...");
            });
        }

        @JavascriptInterface
        public void error(String msg) {
            ui.post(() -> {
                if (run != runId || !running) return;
                jsErrors.add("page: " + NativeChecks.clip(msg, 200));
                // an engine that cannot parse part 2 never sends "full": finish with part 1 after a moment
                if (msg != null && msg.contains("SyntaxError")) ui.postDelayed(() -> {
                    if (running && run == runId && jsFull == null) finishChecks(true);
                }, 2000);
            });
        }
    }

    private void maybeFinish() {
        if (running && jsFull != null && !hostPending) finishChecks(false);
    }

    private void finishChecks(boolean partial) {
        if (!running) return;
        running = false;
        web.removeJavascriptInterface("KastrProbe");
        web.loadUrl("about:blank");
        try {
            report = Report.build(this, nativePart, jsBasic, jsFull, jsErrors, hostPart, lastKey, new ArrayList<>(keysSeen),
                kastrPage, startedAt, partial);
            reportText = Report.text(report);
            compact = Report.compact(report);
        } catch (Exception ex) {
            reportText = "Report failed: " + ex;
            compact = "{\"p\":\"" + VERSION + "\",\"err\":\"report\"}";
        }
        reportView.setText(reportText);
        showView(reportScroll);
        reportScroll.scrollTo(0, 0);
        say(partial ? "Checks finished with gaps (see Problems). Save / Copy / QR code to send it." : "Checks done. Save report, Copy report or QR code to send it.");
        runBtn.requestFocus();
    }

    // ================= KASTR page =================
    private void openKastr() {
        String origin = NativeChecks.origin(hostField.getText().toString());
        if (origin == null) {
            say("Type a relay host address first, e.g. https://<host> (the KASTR on a relay host machine).");
            hostField.requestFocus();
            return;
        }
        if (running) {
            say("Wait for the checks to finish first.");
            return;
        }
        String url = origin + "/moq-watch-lite.html";
        kastrMode = true;
        try {
            kastrPage.put("url", url);
            kastrPage.put("openedAt", stamp(System.currentTimeMillis()));
            kastrPage.put("loaded", false);
            kastrPage.remove("error");
            kastrPage.remove("httpError");
            kastrPage.remove("sslError");
            kastrPage.remove("renderer");
        } catch (Exception ignored) {
            // JSON put of strings cannot fail
        }
        web.removeJavascriptInterface("KastrProbe");
        header.setVisibility(View.GONE);
        kastrBar.setVisibility(View.VISIBLE);
        kastrUrl.setText("  " + url + "   (Back returns to the report)");
        showView(web);
        web.loadUrl(url);
        web.requestFocus();
    }

    private void closeKastr() {
        kastrMode = false;
        web.loadUrl("about:blank");
        header.setVisibility(View.VISIBLE);
        kastrBar.setVisibility(View.GONE);
        showView(reportScroll);
        if (report != null) {
            try {
                report.put("kastrPage", new JSONObject(kastrPage.toString()));
                reportText = Report.text(report);
                compact = Report.compact(report);
                reportView.setText(reportText);
            } catch (Exception ignored) {
                // keep the previous text
            }
        } else {
            reportView.setText("KASTR page: " + kastrPage.toString() + "\n\nRun checks for the full report.");
        }
        say("Back from the KASTR page.");
        runBtn.requestFocus();
    }

    private static String noQuery(String url) {
        if (url == null) return "";
        int q = url.indexOf('?');
        int h = url.indexOf('#');
        int cut = q < 0 ? h : (h < 0 ? q : Math.min(q, h));
        return cut < 0 ? url : url.substring(0, cut);
    }

    private final class Client extends WebViewClient {
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
            Uri u = req.getUrl();
            if (!PROBE_HOST.equals(u.getHost())) return null;
            Map<String, String> hdr = new HashMap<>();
            hdr.put("Cache-Control", "no-store");
            if ("/probe.html".equals(u.getPath())) {
                try {
                    InputStream in = getAssets().open("probe.html");
                    return new WebResourceResponse("text/html", "utf-8", 200, "OK", hdr, in);
                } catch (Exception e) {
                    return null;
                }
            }
            return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found", hdr,
                new java.io.ByteArrayInputStream(new byte[0]));
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            return false;   // stay in this WebView
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            if (kastrMode && url != null && url.startsWith("http")) {
                try {
                    kastrPage.put("loaded", true);
                    kastrPage.put("finalUrl", noQuery(url));
                    kastrPage.put("title", NativeChecks.clip(view.getTitle(), 80));
                } catch (Exception ignored) {
                    // nothing
                }
            }
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
            if (kastrMode && req.isForMainFrame()) {
                try {
                    kastrPage.put("error", err.getErrorCode() + " " + err.getDescription());
                } catch (Exception ignored) {
                    // nothing
                }
                say("KASTR page did not load: " + err.getDescription());
            }
        }

        @Override
        public void onReceivedHttpError(WebView view, WebResourceRequest req, WebResourceResponse resp) {
            if (kastrMode && req.isForMainFrame()) {
                try {
                    kastrPage.put("httpError", resp.getStatusCode() + " " + resp.getReasonPhrase());
                } catch (Exception ignored) {
                    // nothing
                }
            }
        }

        @Override
        public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            String why = sslName(error.getPrimaryError());
            try {
                kastrPage.put("sslError", why);
            } catch (Exception ignored) {
                // nothing
            }
            if (!kastrMode) {
                handler.cancel();
                return;
            }
            new AlertDialog.Builder(MainActivity.this)
                .setTitle("Certificate problem")
                .setMessage("The relay host's certificate is not trusted here (" + why + ").\n\n"
                    + "Continue anyway, for this test only?")
                .setPositiveButton("Continue", (d, w) -> {
                    try {
                        kastrPage.put("sslError", why + " (continued anyway)");
                    } catch (Exception ignored) {
                        // nothing
                    }
                    handler.proceed();
                })
                .setNegativeButton("Cancel", (d, w) -> handler.cancel())
                .setOnCancelListener(d -> handler.cancel())
                .show();
        }

        @Override
        public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            boolean crashed = Build.VERSION.SDK_INT >= 26 && detail.didCrash();
            try {
                kastrPage.put("renderer", crashed ? "crashed" : "killed (low memory?)");
            } catch (Exception ignored) {
                // nothing
            }
            if (running) jsErrors.add("WebView renderer " + (crashed ? "crashed" : "was killed"));
            ui.post(() -> {
                createWebView();
                if (running) finishChecks(true);
                else if (kastrMode) closeKastr();
            });
            return true;
        }
    }

    private static String sslName(int e) {
        switch (e) {
            case SslError.SSL_NOTYETVALID: return "not yet valid";
            case SslError.SSL_EXPIRED: return "expired";
            case SslError.SSL_IDMISMATCH: return "name mismatch";
            case SslError.SSL_UNTRUSTED: return "untrusted issuer (self-signed?)";
            case SslError.SSL_DATE_INVALID: return "date invalid";
            default: return "invalid";
        }
    }

    // ================= save / copy / QR =================
    private boolean haveReport() {
        if (report == null) {
            say("Run checks first.");
            return false;
        }
        return true;
    }

    private void saveReport() {
        if (!haveReport()) return;
        String base = "kastr-probe-" + new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date());
        String json;
        try {
            json = report.toString(2);
        } catch (Exception e) {
            json = report.toString();
        }
        List<String> where = new ArrayList<>();
        // 1. the app's own external files folder (no permission needed)
        File dir = getExternalFilesDir(null);
        if (dir != null) {
            try {
                write(new File(dir, base + ".json"), json);
                write(new File(dir, base + ".txt"), reportText);
                where.add(new File(dir, base + ".json").getAbsolutePath() + " (+ .txt)");
            } catch (Exception e) {
                where.add("app folder failed: " + e.getClass().getSimpleName());
            }
        }
        // 2. Downloads
        if (Build.VERSION.SDK_INT >= 29) {
            try {
                saveToDownloads(base + ".json", "application/json", json);
                saveToDownloads(base + ".txt", "text/plain", reportText);
                where.add("Download/KASTR probe/" + base + ".json (+ .txt)");
            } catch (Exception e) {
                where.add("Downloads failed: " + e.getClass().getSimpleName());
            }
        } else {
            try {
                File dl = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "KASTR probe");
                if (!dl.isDirectory() && !dl.mkdirs()) throw new java.io.IOException("cannot make folder");
                write(new File(dl, base + ".json"), json);
                write(new File(dl, base + ".txt"), reportText);
                where.add(new File(dl, base + ".json").getAbsolutePath() + " (+ .txt)");
            } catch (Exception e) {
                where.add("Downloads not written (Android " + Build.VERSION.RELEASE
                    + " needs a storage permission this probe does not ask for; use the app folder above)");
            }
        }
        String msg = "Saved: " + NativeChecks.join(where, "  |  ");
        say(msg);
        reportView.setText(msg + "\n\n" + reportText);
        reportScroll.scrollTo(0, 0);
        Toast.makeText(this, "Report saved", Toast.LENGTH_SHORT).show();
    }

    private static void write(File f, String s) throws Exception {
        try (FileOutputStream o = new FileOutputStream(f)) {
            o.write(s.getBytes(StandardCharsets.UTF_8));
        }
    }

    private void saveToDownloads(String name, String mime, String body) throws Exception {
        ContentResolver cr = getContentResolver();
        ContentValues cv = new ContentValues();
        cv.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
        cv.put(MediaStore.MediaColumns.MIME_TYPE, mime);
        cv.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/KASTR probe");
        Uri u = cr.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
        if (u == null) throw new java.io.IOException("insert failed");
        try (OutputStream o = cr.openOutputStream(u)) {
            if (o == null) throw new java.io.IOException("no stream");
            o.write(body.getBytes(StandardCharsets.UTF_8));
        }
    }

    private void copyReport() {
        if (!haveReport()) return;
        ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (cm == null) {
            say("No clipboard on this device.");
            return;
        }
        cm.setPrimaryClip(ClipData.newPlainText("KASTR probe report", reportText + "\n\n" + report.toString()));
        say("Report copied to the clipboard (text + JSON).");
    }

    private void showQr() {
        if (!haveReport()) return;
        byte[] data = compact.getBytes(StandardCharsets.UTF_8);
        QrCode q;
        try {
            q = QrCode.encodeBytes(data, 'L');
        } catch (IllegalArgumentException e) {
            say("Report too long for a QR code; use Save or Copy.");
            return;
        }
        DisplayMetrics dm = getResources().getDisplayMetrics();
        int avail = Math.min(content.getWidth() > 0 ? content.getWidth() : dm.widthPixels,
            content.getHeight() > 0 ? content.getHeight() : dm.heightPixels);
        int border = 4;
        int scale = Math.max(1, avail / (q.size + border * 2));
        int px = (q.size + border * 2) * scale;
        int[] pixels = new int[px * px];
        for (int y = 0; y < px; y++) {
            int my = y / scale - border;
            for (int x = 0; x < px; x++) {
                int mx = x / scale - border;
                pixels[y * px + x] = q.get(mx, my) ? Color.BLACK : Color.WHITE;
            }
        }
        Bitmap bmp = Bitmap.createBitmap(pixels, px, px, Bitmap.Config.ARGB_8888);
        qrView.setImageBitmap(bmp);
        showView(qrView);
        qrView.requestFocus();
        say("QR code: version " + q.version + ", " + data.length + " bytes. OK, Back or tap closes it.");
    }

    private void hideQr() {
        showView(kastrMode ? web : reportScroll);
        runBtn.requestFocus();
    }

    // ================= helpers =================
    static String stamp(long ms) {
        return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss Z", Locale.US).format(new Date(ms));
    }

    static List<String> sorted(JSONArray a) {
        List<String> l = new ArrayList<>();
        if (a != null) for (int i = 0; i < a.length(); i++) l.add(a.optString(i));
        Collections.sort(l);
        return l;
    }
}
