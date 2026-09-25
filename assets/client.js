/* 0.17.0: who this page is running for, decided before anything else loads.
 *
 * KASTR serves the same pages to its own app window (class "app") and to any
 * browser on another device that opens the relay host's web port (class "web":
 * phones, tablets, laptops without the executable). The server substitutes the
 * class as it serves (__KASTR_CLIENT__, like the hostname), so every module and
 * the masthead read one synchronous fact instead of racing a fetch. What the
 * browser can do is measured here too: WebCodecs, camera/mic and crypto.subtle
 * exist only in a secure context (https, or http on localhost), so a plain
 * http://<lan-ip> page is a lobby -- rooms, People, chat, admin -- not a viewer.
 *
 * A web device is its own MoQ host: the slug `web-<8 hex>-<4 hex>` (HOST_RE
 * shape) comes from a per-browser id kept in localStorage, so two devices
 * served by one relay host never share broadcast paths or token scopes.
 *
 * Classic script on purpose: it runs during parsing, before the deferred
 * module graph and asi-brand.js, and installs the one polyfill the vendored
 * MoQ library needs on older engines (Promise.withResolvers).
 */
(function () {
  var RAW = "__KASTR_CLIENT__";
  var loopback = /^(localhost|127\.0\.0\.1|\[::1\]|::1)$/.test(location.hostname);
  var cls = (RAW === "web" || RAW === "app") ? RAW : (loopback ? "app" : "web");
  if (location.protocol === "file:") cls = "app";

  var ua = navigator.userAgent || "";
  var browser = /firefox/i.test(ua) ? "firefox"
    : (/safari/i.test(ua) && !/chrome|chromium|crios|edg/i.test(ua)) ? "webkit"
    : "chromium";
  var ios = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  var secure = window.isSecureContext === true;
  var mobile = false;
  try { mobile = matchMedia("(hover: none) and (pointer: coarse)").matches; } catch (e) {}

  function hex(n) {
    var b = new Uint8Array(n), out = "";
    try { crypto.getRandomValues(b); } catch (e) { for (var i = 0; i < n; i++) b[i] = Math.floor(Math.random() * 256); }
    for (var j = 0; j < n; j++) out += (b[j] < 16 ? "0" : "") + b[j].toString(16);
    return out;
  }
  var deviceId = "";
  try {
    deviceId = localStorage.getItem("kastr.device") || "";
    if (!/^[0-9a-f]{12}$/.test(deviceId)) { deviceId = hex(6); localStorage.setItem("kastr.device", deviceId); }
  } catch (e) {
    try {
      deviceId = sessionStorage.getItem("kastr.device") || "";
      if (!/^[0-9a-f]{12}$/.test(deviceId)) { deviceId = hex(6); sessionStorage.setItem("kastr.device", deviceId); }
    } catch (e2) { deviceId = hex(6); }
  }

  var client = {
    class: cls,
    secure: secure,
    media: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
    webcodecs: typeof VideoDecoder === "function",
    displayCapture: !!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia),
    // informational: @moq/net decides for real (WebKit/iOS and Firefox < 153 dial WebSocket)
    transport: (typeof WebTransport === "function" && browser !== "webkit" && !ios) ? "wt" : "ws",
    browser: browser,
    ios: ios,
    mobile: mobile,
    deviceId: deviceId,
    host: cls === "web" ? ("web-" + deviceId.slice(0, 8) + "-" + deviceId.slice(8, 12)) : null,
  };
  try { Object.freeze(client); } catch (e) {}
  window.__kastrClient = client;
  window.__client = client;                       // rig alias
  window.__caps = function () { var o = {}; for (var k in client) o[k] = client[k]; return o; };

  // Needed by the vendored @moq/net, qmux, signals, watch player and web-socket-stream,
  // which load as modules after this script (Chrome 119+/Safari 17.4+/Firefox 121+ have it).
  if (typeof Promise.withResolvers !== "function") {
    Promise.withResolvers = function () {
      var resolve, reject;
      var promise = new this(function (a, b) { resolve = a; reject = b; });
      return { promise: promise, resolve: resolve, reject: reject };
    };
  }

  try {
    var h = document.documentElement;
    h.classList.add("client-" + cls, secure ? "ctx-secure" : "ctx-insecure");
    if (!client.webcodecs) h.classList.add("no-webcodecs");
  } catch (e) {}
})();
