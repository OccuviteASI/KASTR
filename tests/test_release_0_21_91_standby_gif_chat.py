# -*- coding: utf-8 -*-
"""0.21.91 follow-ups (the coordinator, after GIF search and the Room Chat attachments check):

1. A spoke forwarding a Room Chat call to the hub keeps the reader's room token (`?jwt=`, X-Kastr-Jwt) to itself -- the hub
   trusts the spoke's federation token. Every other query (since, limit, a delete token) still goes on.
2. The standby hub keeps its OWN GIPHY key (its Relay page shows the card; 0600 on that machine; never sent anywhere -- not in
   the standby copy, not in a hand-over) and uses it only while it acts as the hub. A plain spoke still says "set on the hub".
3. The Room Chat box: an empty box is always its natural size after a send, and a box with text is measured with its borders
   (border-box: scrollHeight alone was 2 px short and showed scroll arrows). The Messages box the same."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))
import kastr_gif as kg  # noqa: E402
import kastr_relay as kr  # noqa: E402
import test_release_0_21_91_chat_files_fleet as cf  # noqa: E402
import test_release_0_21_91_gif_search as gs  # noqa: E402


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class RecordingHub:
    """The hub's KASTR web port: records every forwarded call and answers 200."""

    def __init__(self):
        self.calls = []
        rec = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _any(self):
                n = int(self.headers.get("Content-Length") or 0)
                rec.calls.append((self.command, self.path, dict(self.headers), self.rfile.read(n) if n else b""))
                body = b'{"ok": true, "messages": [], "id": "%s"}' % (b"a" * 32)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_DELETE = _any

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ChatProxyKeepsTheRoomToken(cf.Base):
    def setUp(self):
        super().setUp()
        self.hub = RecordingHub()
        sd = os.path.join(self.tmp, "spoke")
        os.makedirs(sd)
        _p, self.key = kr._ensure_jwk(sd)
        self.patches.append(mock.patch.object(cf.kastr_serve, "_own_hosts", lambda: {"spoke.lab.test"}))
        self.patches[-1].start()
        cluster = {"connect": "https://127.0.0.1:4443", "code": "", "webStored": self.hub.port, "hub": False}
        self.base = self.serve(cf.fake_relay(sd, cluster, "lab-federation-token"), "http://spoke.lab.test:4453")

    def tearDown(self):
        self.hub.close()
        super().tearDown()

    def test_no_room_token_reaches_the_hub(self):
        tok = cf.member(self.key, "yard")
        q = urllib.parse.quote(tok)
        cf.call(self.base, "/api/chat/yard?since=5&jwt=%s&limit=50" % q, headers={"X-Kastr-Jwt": tok})
        cf.call(self.base, "/api/chat/yard/files?jwt=" + q, cf.PNG, {"Content-Type": "image/png", "X-Kastr-Name": "a.png", "X-Kastr-Jwt": tok})
        cf.call(self.base, "/api/chat/yard/files/%s?jwt=%s" % ("b" * 32, q))
        cf.call(self.base, "/api/chat/yard/12?token=deltok123&jwt=" + q, method="DELETE")
        self.assertEqual(len(self.hub.calls), 4)
        paths = [c[1] for c in self.hub.calls]
        self.assertEqual(paths, ["/api/chat/yard?since=5&limit=50", "/api/chat/yard/files", "/api/chat/yard/files/" + "b" * 32,
                                 "/api/chat/yard/12?token=deltok123"])
        for method, path, hdrs, _body in self.hub.calls:
            self.assertNotIn(tok, path)
            self.assertNotIn(tok, json.dumps(hdrs))
            self.assertNotIn("X-Kastr-Jwt", hdrs)
            self.assertEqual(hdrs.get("Authorization"), "Bearer lab-federation-token")
        self.assertEqual(self.hub.calls[1][3], cf.PNG)


class StandbyKeepsItsOwnKey(gs.Base):
    def setUp(self):
        super().setUp()
        self.hub_key = os.urandom(32)
        self.hdir, self.sdir = self.tmp(), self.tmp()
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, gs.store(self.hdir), log=self.logs.append)
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600, node="sb-node"))
        hb = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.acting = [False]
        self.sb = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, gs.store(self.sdir), log=self.logs.append,
                                 hub=lambda: hb, fed_token=lambda: self.fed, is_hub=lambda: self.acting[0])
        self.sbase = "http://127.0.0.1:%d" % self.sb.httpd.server_address[1]
        self.member = gs.tok(self.sb, "tremonton", "kentonpc-1a2b")
        self.role = ["standby"]
        self.relay = types.SimpleNamespace(auth=self.sb, state_dir=self.sdir, standby_view=lambda: {"role": self.role[0]})
        self.saved = kr._local_only
        kr._local_only = lambda h: True

    def tearDown(self):
        kr._local_only = self.saved
        for s in (self.hub, self.sb):
            s.close()
        super().tearDown()

    def page(self, body=None):
        h = gs.RelayPage.FakeHandler(body, "POST" if body is not None else "GET")
        self.assertTrue(kr.handle_api(h, self.relay, "/api/relay/gif"))
        return h.code, h.body(), h.wfile.getvalue()

    def search(self, q):
        self.sb.__dict__.pop("_gif_st", None)
        c, raw, _ = gs.http(self.sbase, "/api/gif/search?q=" + q, self.member)
        return c, json.loads(raw)

    def test_standby_card_key_and_when_it_is_used(self):
        c, v, _ = self.page()
        self.assertEqual((c, v.get("standby"), v.get("acting"), v.get("set"), v.get("spoke")), (200, True, False, False, None))
        c, v, raw = self.page({"key": self.giphy.key})
        self.assertEqual((c, v["set"], v["standby"]), (200, True, True))
        self.no_key_in(raw)
        path = os.path.join(self.sdir, kg.CONF_NAME)
        self.assertTrue(os.path.isfile(path))
        if os.name == "posix":
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        # while the main hub is the hub, the standby's pages ask the main hub -- which has no key: off, though the standby has one
        c, d = self.search("cats")
        self.assertEqual((c, d.get("off")), (404, True))
        self.assertEqual(self.giphy.api_calls(), [])
        # the standby takes over: its own key answers
        self.acting[0] = True
        self.role[0] = "promoted"
        c, d = self.search("cats")
        self.assertEqual((c, d["items"][0]["id"]), (200, "scats0"))
        self.assertEqual(self.giphy.api_calls()[-1][1]["api_key"], self.giphy.key)
        c, v, _ = self.page()
        self.assertEqual((v.get("standby"), v.get("acting"), v.get("hub")), (True, True, True))
        # the main hub is back: the standby is a standby again, its key kept but unused
        self.acting[0] = False
        self.role[0] = "standby"
        n = len(self.giphy.api_calls())
        self.assertEqual(self.search("dogs")[0], 404)
        self.assertEqual(len(self.giphy.api_calls()), n)
        self.assertTrue(kg.for_dir(self.sdir).key)

    def test_a_plain_spoke_still_says_set_on_the_hub(self):
        self.role[0] = "spoke"
        c, v, _ = self.page()
        self.assertEqual((c, v.get("spoke"), v.get("standby")), (200, True, None))
        c, v, _ = self.page({"key": self.giphy.key})
        self.assertEqual(c, 409)
        self.assertFalse(os.path.exists(os.path.join(self.sdir, kg.CONF_NAME)))

    def test_no_key_in_the_standby_copy_or_the_logs(self):
        self.hub.gif_operator({"key": self.giphy.key})
        self.hub.standby_info = lambda: {"node": "sb-node", "name": "standby", "address": "https://10.0.0.9:4443", "secret": "lab-sb-secret"}
        d, c = self.hub.replica({"node": "sb-node", "since": {}, "chat": {}, "wait": 0}, "Bearer " + self.fed)
        self.assertEqual(c, 200, d)
        self.no_key_in(d)
        self.assertNotIn(kg.CONF_NAME, json.dumps(d))
        self.page({"key": self.giphy.key})
        for line in self.logs:
            self.assertNotIn(self.giphy.key, line)

    def test_relay_page_line(self):
        r = _read("relay.html")
        self.assertIn('<p class="hint" id="gifStandby" hidden></p>', r)
        self.assertIn("travels with the standby copy", r)
        self.assertIn("used only while this relay acts as the hub", r)


class ComposerSize(unittest.TestCase):
    def test_room_chat_box(self):
        p = _read("moq-watch-lite.html")
        i = p.index("function chatGrow()")
        body = p[i:i + 400]
        self.assertIn('if (!chatInput.value) { chatInput.style.height = ""; return; }', body)
        self.assertIn("chatInput.scrollHeight + (chatInput.offsetHeight - chatInput.clientHeight)", body)
        self.assertIn("if (!chatInput.offsetWidth) return;", body)
        self.assertIn("new ResizeObserver(() => { const w = chatInput.offsetWidth; if (w && w !== gw) { gw = w; chatGrow(); } }).observe(chatInput);", p)
        self.assertIn('chatInput.value = ""; chatGrow();', p)   # a send ends at the natural size

    def test_messages_box(self):
        m = _read(os.path.join("assets", "kastr-msg.js"))
        self.assertIn('if (!ta.value) { ta.style.height = ""; return; }', m)
        self.assertIn("ta.scrollHeight + (ta.offsetHeight - ta.clientHeight)", m)

    def test_line_endings(self):
        for name, crlf in (("moq-watch-lite.html", True), ("relay.html", True), ("kastr_serve.py", True), ("kastr_relay.py", False),
                           (os.path.join("assets", "kastr-msg.js"), False)):
            with open(os.path.join(HERE, name), "rb") as f:
                raw = f.read()
            if crlf:
                self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)
            else:
                self.assertNotIn(b"\r\n", raw, name)


if __name__ == "__main__":
    unittest.main()
