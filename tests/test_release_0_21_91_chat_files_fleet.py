# -*- coding: utf-8 -*-
"""0.21.91: Room Chat pictures across relays (the coordinator's follow-up to the GIF lab, where a GIF posted on a spoke showed
as a broken picture on the hub).

Finding: that lab ran the hub and the spoke on ONE machine and the spoke dialled its hub as "localhost" -- one of the spoke's
own names -- so the spoke took itself for the hub (_chat_hub: "the hub is this KASTR -- answering chat locally") and kept the
picture in its own store. With the hub on another machine (simulated in the lab by taking "localhost" out of the spoke's own
names) every KASTR forwards chat and its attachments to the hub's KASTR (0.12.0 design), and a hub page, a spoke page and a
second spoke's page all open every picture with their own room token (lab matrix: 9 of 9 = 200, bytes equal).

These tests pin that contract: a spoke checks the member token with ITS key, then forwards the upload and the download to the
hub's KASTR with its federation token (the size cap is the hub's); the hub serves a federation caller and refuses a member token
it did not mint. No code change was needed."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_serve  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"lab picture bytes" * 40


def member(key, room, host="ginapc-1a2b"):
    now = int(time.time())
    return kr._mint(key, {"root": "", "get": room, "put": [room + "/" + host, "~state/%s/%s" % (room, host)], "iat": now, "exp": now + 3600})


def fed(key):
    now = int(time.time())
    return kr._mint(key, dict(kr.FEDERATION_CLAIMS, iat=now, exp=now + 3600))


def call(base, path, data=None, headers=None, method=None):
    r = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"), headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=20) as f:
            return f.status, f.read(), dict(f.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def fake_relay(state_dir, cluster, fed_active=None):
    return types.SimpleNamespace(
        state_dir=state_dir, secured=True, running=lambda: True, _cluster_raw=lambda: cluster, _fed_active=fed_active,
        relay_name=lambda: "lab-relay", store=types.SimpleNamespace(room=lambda r: None, is_closed=lambda r: False), log=lambda m: None)


class FakeHubKastr:
    """The hub's KASTR web port as far as a spoke's chat proxy uses it; records every call."""

    def __init__(self):
        self.calls, self.files = [], {}
        hub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                hub.calls.append(("POST", self.path, dict(self.headers), body))
                fid = "%032x" % (len(hub.files) + 1)
                hub.files[fid] = body
                self._send(200, json.dumps({"id": fid, "size": len(body), "type": "image/png"}).encode())

            def do_GET(self):
                hub.calls.append(("GET", self.path, dict(self.headers), b""))
                fid = urllib.parse.urlsplit(self.path).path.rsplit("/", 1)[-1]
                if fid in hub.files:
                    return self._send(200, hub.files[fid], "image/png")
                self._send(404, b'{"error": "no such file"}')

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kastr-chatfleet-")
        self.patches = [mock.patch.object(kastr_serve, "CHAT", None),
                        mock.patch.object(kastr_serve, "_ini_file", lambda: os.path.join(self.tmp, "kastr.ini"))]
        for p in self.patches:
            p.start()
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.shutdown()
            s.server_close()
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def serve(self, relay_srv, relay_url):
        srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True, relay=relay_url, relay_srv=relay_srv)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.servers.append(srv)
        return "http://127.0.0.1:%d" % srv.server_address[1]


class SpokeForwardsToTheHub(Base):
    def setUp(self):
        super().setUp()
        self.hub = FakeHubKastr()
        sd = os.path.join(self.tmp, "spoke")
        os.makedirs(sd)
        _p, self.key = kr._ensure_jwk(sd)
        self.fed = "lab-federation-token"
        # the hub is ANOTHER machine: none of this spoke's own names (the lab's "localhost" mistake is the opposite case)
        self.patches.append(mock.patch.object(kastr_serve, "_own_hosts", lambda: {"spoke.lab.test"}))
        self.patches[-1].start()
        cluster = {"connect": "https://127.0.0.1:4443", "code": "", "webStored": self.hub.port, "hub": False}
        self.base = self.serve(fake_relay(sd, cluster, self.fed), "http://spoke.lab.test:4453")

    def tearDown(self):
        self.hub.close()
        super().tearDown()

    def test_upload_and_download_go_to_the_hub(self):
        tok = member(self.key, "yard")
        c, raw, _ = call(self.base, "/api/chat/yard/files?jwt=" + urllib.parse.quote(tok), PNG,
                         {"Content-Type": "image/png", "X-Kastr-Name": "pasted.png", "X-Kastr-Op": "gina"})
        self.assertEqual(c, 200, raw[:200])
        fid = json.loads(raw)["id"]
        method, path, hdrs, body = self.hub.calls[-1]
        self.assertEqual((method, urllib.parse.urlsplit(path).path, body), ("POST", "/api/chat/yard/files", PNG))
        self.assertEqual(hdrs.get("Authorization"), "Bearer " + self.fed)        # the spoke's federation token, not the member's
        self.assertEqual(hdrs.get("X-Kastr-Name"), "pasted.png")
        self.assertTrue(hdrs.get("X-Kastr-Via"))
        # the download: every reader on this spoke gets the hub's copy with their own token
        c, raw, h = call(self.base, "/api/chat/yard/files/%s?jwt=%s" % (fid, urllib.parse.quote(member(self.key, "yard", "hankpc-3c4d"))))
        self.assertEqual((c, raw), (200, PNG))
        self.assertEqual(self.hub.calls[-1][2].get("Authorization"), "Bearer " + self.fed)

    def test_the_spoke_checks_the_token_first(self):
        n = len(self.hub.calls)
        for q in ("", "?jwt=" + urllib.parse.quote(member(self.key, "elsewhere")), "?jwt=" + urllib.parse.quote(member(os.urandom(32), "yard"))):
            c, _raw, _ = call(self.base, "/api/chat/yard/files" + q, PNG, {"Content-Type": "image/png"})
            self.assertIn(c, (401, 403), q[:12])
            c, _raw, _ = call(self.base, "/api/chat/yard/files/%032x%s" % (1, q))
            self.assertIn(c, (401, 403))
        self.assertEqual(len(self.hub.calls), n)                                    # the hub never asked
        self.assertEqual(call(self.base, "/api/chat/yard/files/../../x?jwt=" + urllib.parse.quote(member(self.key, "yard")))[0], 404)


class TheHubServesItsSpokes(Base):
    def setUp(self):
        super().setUp()
        hd = os.path.join(self.tmp, "hub")
        os.makedirs(hd)
        _p, self.key = kr._ensure_jwk(hd)
        self.base = self.serve(fake_relay(hd, {"connect": "", "code": "", "hub": True}), "http://127.0.0.1:4443")

    def test_federation_caller_and_own_members(self):
        h = {"Authorization": "Bearer " + fed(self.key), "Content-Type": "image/png", "X-Kastr-Name": "from-spoke.png", "X-Kastr-Via": "south"}
        c, raw, _ = call(self.base, "/api/chat/yard/files", PNG, h)
        self.assertEqual(c, 200, raw[:200])
        fid = json.loads(raw)["id"]
        # a hub member opens the spoke member's picture with the hub's own room token
        c, raw, hd = call(self.base, "/api/chat/yard/files/%s?jwt=%s" % (fid, urllib.parse.quote(member(self.key, "yard"))))
        self.assertEqual((c, raw, hd.get("Content-Type")), (200, PNG, "image/png"))
        # another spoke reading for its member (federation token)
        self.assertEqual(call(self.base, "/api/chat/yard/files/" + fid, headers={"Authorization": "Bearer " + fed(self.key)})[:2], (200, PNG))
        # refused: a member token another minter signed, a federation token of another fleet, another room's token, no token
        self.assertEqual(call(self.base, "/api/chat/yard/files/%s?jwt=%s" % (fid, urllib.parse.quote(member(os.urandom(32), "yard"))))[0], 403)
        self.assertEqual(call(self.base, "/api/chat/yard/files/" + fid, headers={"Authorization": "Bearer " + fed(os.urandom(32))})[0], 403)
        self.assertEqual(call(self.base, "/api/chat/yard/files/%s?jwt=%s" % (fid, urllib.parse.quote(member(self.key, "other"))))[0], 401)
        self.assertEqual(call(self.base, "/api/chat/yard/files/" + fid)[0], 401)
        # a file of one room is not served under another room's name
        self.assertEqual(call(self.base, "/api/chat/other/files/%s?jwt=%s" % (fid, urllib.parse.quote(member(self.key, "other"))))[0], 404)


if __name__ == "__main__":
    unittest.main()
