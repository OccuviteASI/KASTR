# -*- coding: utf-8 -*-
"""0.21.91 GIF SEARCH. Kenton: "I would like to add gif search options as well to the chat/messages."

GIPHY through the hub: Kenton's key is pasted on the hub's Relay page and stays on the hub (never in a reply, a log, a diag
report or a page); a page asks the relay it uses with a member token of a room, a spoke forwards to the hub, the hub asks
GIPHY with rating=pg-13 and proxies the pictures too (GIPHY never sees a person's address). Not an open proxy: the hub builds
every GIPHY URL from a term, an offset or a GIF id and a fixed rendition allow-list. A light per-token rate limit and short
caches. Messages send a picked GIF as an encrypted attachment; Room Chat as a normal attachment.

Every test runs against a MOCK GIPHY on 127.0.0.1 (KASTR_GIPHY_BASE) -- never api.giphy.com -- and a random lab key."""
import json
import os
import secrets
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
import kastr_gif as kg  # noqa: E402
import kastr_relay as kr  # noqa: E402


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


# ---- a small animated GIF (no imaging library): 4 colours, LZW with a clear code every 2 pixels (3-bit codes throughout) ----
def make_gif(w, h, frames=6, palette=((0x1e, 0x88, 0xe5), (0xff, 0xb3, 0x00), (0xe5, 0x39, 0x35), (0x43, 0xa0, 0x47)), step=7):
    def lzw(px):
        codes = []
        for i in range(0, len(px), 2):
            codes.append(4)
            codes.extend(px[i:i + 2])
        codes.append(5)
        out, acc, n = bytearray(), 0, 0
        for c in codes:
            acc |= c << n
            n += 3
            while n >= 8:
                out.append(acc & 255)
                acc >>= 8
                n -= 8
        if n:
            out.append(acc & 255)
        blocks = bytearray()
        for i in range(0, len(out), 255):
            chunk = out[i:i + 255]
            blocks.append(len(chunk))
            blocks += chunk
        return bytes(blocks) + b"\x00"

    b = bytearray(b"GIF89a" + w.to_bytes(2, "little") + h.to_bytes(2, "little") + bytes([0x91, 0, 0]))
    for c in palette:
        b += bytes(c)
    b += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    for k in range(frames):
        px = [((x + y + k * step) // 9) % 4 for y in range(h) for x in range(w)]
        b += b"\x21\xf9\x04\x00" + (10).to_bytes(2, "little") + b"\x00\x00"
        b += b"\x2c\x00\x00\x00\x00" + w.to_bytes(2, "little") + h.to_bytes(2, "little") + b"\x00\x02" + lzw(px)
    return bytes(b + b"\x3b")


PALETTES = [((0x1e, 0x88, 0xe5), (0xff, 0xb3, 0x00), (0xe5, 0x39, 0x35), (0x43, 0xa0, 0x47)),
            ((0x8e, 0x24, 0xaa), (0x00, 0xac, 0xc1), (0xff, 0xff, 0xff), (0x21, 0x21, 0x21)),
            ((0xf4, 0x51, 0x1e), (0xfd, 0xd8, 0x35), (0x6d, 0x4c, 0x41), (0x00, 0x89, 0x7b))]


class MockGiphy:
    """GIPHY's API + media hosts as far as KASTR uses them, on 127.0.0.1. Records every request."""

    def __init__(self, frames=2, port=0):
        self.calls = []
        self.frames = frames
        self.gifs = {}
        mk = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                mk.calls.append((u.path, q, dict(self.headers)))
                if u.path.startswith("/media/"):
                    parts = u.path.split("/")
                    gid, fn = parts[2], parts[3]
                    data = mk.gif(gid, fn)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/gif")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if not u.path.startswith("/v1/gifs"):
                    return self.reply({"message": "not found"}, 404)
                if q.get("api_key") != mk.key:
                    return self.reply({"message": "Unauthorized: key " + str(q.get("api_key"))}, 401)
                tail = u.path[len("/v1/gifs"):]
                if tail in ("/search", "/trending"):
                    term = q.get("q", "")
                    if term == "busy":
                        return self.reply({"message": "rate limited"}, 429)
                    off, lim = int(q.get("offset", 0)), int(q.get("limit", 25))
                    total = 60
                    data = [mk.item("%s%d" % ("t" if tail == "/trending" else "s" + "".join(c for c in term if c.isalnum())[:8], off + i))
                            for i in range(lim) if off + i < total]
                    if term == "edge":
                        data = [mk.item("goodone1"), mk.item("evilhost1", host="https://evil.example"), mk.item("rrated1", rating="r"),
                                mk.item("nosuch/../x")]
                    return self.reply({"data": data, "pagination": {"total_count": total, "count": len(data), "offset": off}})
                gid = tail.strip("/")
                if gid.startswith("s") or gid.startswith("t") or gid == "goodone1":
                    return self.reply({"data": mk.item(gid)})
                return self.reply({"message": "not found"}, 404)

            def reply(self, obj, code=200):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.key = secrets.token_hex(16)    # a random lab key -- never printed
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def gif(self, gid, fn):
        k = (gid, fn)
        if k not in self.gifs:
            n = sum(map(ord, gid))
            w, h = (100, 75) if fn == "100w.gif" else (200, 150)
            self.gifs[k] = make_gif(w, h, frames=self.frames, palette=PALETTES[n % len(PALETTES)], step=3 + n % 9)
        return self.gifs[k]

    def item(self, gid, host=None, rating="g"):
        base = host or self.base
        r = lambda fn, w, h: {"url": "%s/media/%s/%s?cid=abc&rid=%s&ct=g" % (base, gid, fn, fn), "width": str(w), "height": str(h), "size": "4000"}  # noqa: E731
        return {"id": gid, "title": "Mock GIF %s" % gid, "rating": rating,
                "images": {"fixed_width_small": r("100w.gif", 100, 75), "fixed_width": r("200w.gif", 200, 150),
                           "downsized": r("giphy-downsized.gif", 200, 150), "original": r("giphy.gif", 480, 360)}}

    def api_calls(self):
        return [c for c in self.calls if c[0].startswith("/v1/")]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def store(d):
    st = kr.AuthStore(d)
    st.set_codes(viewer="view-1", publisher="pub-1", admin="adm-1")
    return st


def tok(svc, room, host, code="pub-1", extra=None):
    o, c = svc.token(dict({"room": room, "code": code, "host": host}, **(extra or {})), "10.0.0.7")
    assert c == 200, (c, o)
    return o["tokens"]["member"]


def http(base, path, bearer=None):
    req = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + bearer} if bearer else {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


class Base(unittest.TestCase):
    def setUp(self):
        self.giphy = MockGiphy()
        self.env = mock.patch.dict(os.environ, {"KASTR_GIPHY_BASE": self.giphy.base})
        self.env.start()
        self.dirs = []
        self.logs = []

    def tearDown(self):
        self.env.stop()
        self.giphy.close()
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def tmp(self):
        d = tempfile.mkdtemp(prefix="kastr-gif-")
        self.dirs.append(d)
        return d

    def no_key_in(self, blob):
        b = blob if isinstance(blob, (bytes, bytearray)) else json.dumps(blob, default=str).encode()
        self.assertNotIn(self.giphy.key.encode(), b)


class Allowlist(unittest.TestCase):
    def test_media_urls_only_from_giphy(self):
        with mock.patch.dict(os.environ, {"KASTR_GIPHY_BASE": ""}):
            self.assertEqual(kg.api_base(), "https://api.giphy.com/v1/gifs")
            self.assertEqual(kg.media_ok("https://media2.giphy.com/media/v1.Y2lk/abc123/100w.gif?cid=1&rid=100w.gif"),
                             "https://media2.giphy.com/media/v1.Y2lk/abc123/100w.gif")
            self.assertTrue(kg.media_ok("https://i.giphy.com/abc123.webp"))
            for bad in ("http://media.giphy.com/media/abc/100w.gif", "https://media.giphy.com.evil.example/media/abc/100w.gif",
                        "https://evil.example/media/abc/100w.gif", "https://media.giphy.com:8443/media/abc/100w.gif",
                        "https://media.giphy.com/media/../../etc/passwd.gif", "https://media.giphy.com/media/abc/x.php",
                        "file:///etc/passwd", "javascript:alert(1)", "", None):
                self.assertEqual(kg.media_ok(bad), "", bad)
        # a lab mock: loopback only, and then only that origin
        with mock.patch.dict(os.environ, {"KASTR_GIPHY_BASE": "http://10.0.0.5:9000"}):
            self.assertEqual(kg.api_base(), "https://api.giphy.com/v1/gifs")
        with mock.patch.dict(os.environ, {"KASTR_GIPHY_BASE": "http://127.0.0.1:9000"}):
            self.assertEqual(kg.api_base(), "http://127.0.0.1:9000/v1/gifs")
            self.assertTrue(kg.media_ok("http://127.0.0.1:9000/media/abc/100w.gif"))
            self.assertEqual(kg.media_ok("http://127.0.0.1:9001/media/abc/100w.gif"), "")
            self.assertEqual(kg.media_ok("https://media.giphy.com/media/abc/100w.gif"), "")

    def test_renditions_and_terms(self):
        self.assertEqual(sorted(kg.RENDITIONS), ["p", "s"])
        self.assertEqual(kg.RENDITIONS["s"][0], "downsized")
        self.assertLessEqual(kg.SIZE_MAX["s"], 3 * 1024 * 1024)
        self.assertEqual(kg.RATING, "pg-13")
        self.assertEqual(kg.clean_q("  cats \n  dogs "), "cats dogs")
        self.assertEqual(len(kg.clean_q("x" * 500)), kg.Q_MAX)
        self.assertEqual(kg.clean_offset("-5"), 0)
        self.assertEqual(kg.clean_offset("99999"), kg.OFFSET_MAX)
        self.assertEqual(kg.clean_offset("abc"), 0)
        self.assertTrue(kg.gif_magic(make_gif(4, 4, frames=1)))
        self.assertFalse(kg.gif_magic(b"<html>"))


class Hub(Base):
    """A hub (or a lone relay): the key, the switch, search, pictures, who may ask."""

    def setUp(self):
        super().setUp()
        self.dir = self.tmp()
        self.svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store(self.dir), log=self.logs.append)
        self.base = "http://127.0.0.1:%d" % self.svc.httpd.server_address[1]
        self.member = tok(self.svc, "tremonton", "kentonpc-1a2b")

    def tearDown(self):
        self.svc.close()
        super().tearDown()

    def on(self):
        o, c = self.svc.gif_operator({"key": self.giphy.key})
        self.assertEqual(c, 200, o)
        return o

    def test_off_until_a_key_is_saved(self):
        c, raw, _ = http(self.base, "/api/gif/status", self.member)
        self.assertEqual((c, json.loads(raw)), (200, {"ok": True, "on": False}))
        c, raw, _ = http(self.base, "/api/gif/search?q=cats", self.member)
        self.assertEqual((c, json.loads(raw).get("off")), (404, True))
        self.assertEqual(self.giphy.calls, [])
        self.assertEqual(self.svc.gif_operator({"on": True})[1], 400)          # no key yet
        self.assertEqual(self.svc.gif_operator({"key": "not a key!"})[1], 400)
        o = self.on()
        self.assertEqual((o["set"], o["on"], o["active"], o["ends"]), (True, True, True, self.giphy.key[-4:]))
        self.no_key_in(o)
        self.assertEqual(json.loads(http(self.base, "/api/gif/status", self.member)[1])["on"], True)
        o, c = self.svc.gif_operator({"on": False})
        self.assertEqual((c, o["active"], o["set"]), (200, False, True))
        self.assertEqual(json.loads(http(self.base, "/api/gif/status", self.member)[1])["on"], False)
        o, c = self.svc.gif_operator({"remove": True})
        self.assertEqual((c, o["set"], o["ends"]), (200, False, ""))
        # the key is kept on the hub's disk (its own file), and only there
        self.on()
        with open(os.path.join(self.dir, kg.CONF_NAME), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["key"], self.giphy.key)

    def test_search_trending_rating_and_cache(self):
        self.on()
        c, raw, hdrs = http(self.base, "/api/gif/search", self.member)       # nothing typed: trending
        d = json.loads(raw)
        self.assertEqual((c, len(d["items"]), d["next"]), (200, kg.PAGE, kg.PAGE))
        self.assertEqual(set(d["items"][0]), {"id", "w", "h", "t"})           # ids and sizes -- never a URL
        self.assertNotIn("http", raw.decode())
        self.no_key_in(raw)
        self.no_key_in(json.dumps(hdrs).encode())
        c, raw, _ = http(self.base, "/api/gif/search?q=happy%20cats&offset=24", self.member)
        d = json.loads(raw)
        self.assertEqual((c, d["items"][0]["id"], d["next"]), (200, "shappycat24", 48))
        api = self.giphy.api_calls()
        self.assertEqual([p for p, _q, _h in api], ["/v1/gifs/trending", "/v1/gifs/search"])
        for _p, q, h in api:
            self.assertEqual(q["rating"], "pg-13")                                # Kenton: PG-13
            self.assertEqual(q["api_key"], self.giphy.key)                         # the key goes to GIPHY only
            self.assertNotIn("X-Forwarded-For", h)
        self.assertEqual(api[1][1]["q"], "happy cats")
        # the same search again comes from the hub's cache
        http(self.base, "/api/gif/search?q=happy%20cats&offset=24", self.member)
        self.assertEqual(len(self.giphy.api_calls()), 2)
        # the last page says so
        d = json.loads(http(self.base, "/api/gif/search?q=happy%20cats&offset=48", self.member)[1])
        self.assertIsNone(d["next"])

    def test_pictures_are_proxied(self):
        self.on()
        d = json.loads(http(self.base, "/api/gif/search?q=cats", self.member)[1])
        gid = d["items"][0]["id"]
        c, raw, hdrs = http(self.base, "/api/gif/media/%s?r=p" % gid, self.member)
        self.assertEqual((c, raw, hdrs["Content-Type"]), (200, self.giphy.gif(gid, "100w.gif"), "image/gif"))
        c, raw, hdrs = http(self.base, "/api/gif/media/%s?r=s" % gid, self.member)
        self.assertEqual((c, raw), (200, self.giphy.gif(gid, "giphy-downsized.gif")))   # the "downsized" copy is the one sent
        media = [x for x in self.giphy.calls if x[0].startswith("/media/")]
        self.assertEqual([p for p, _q, _h in media], ["/media/%s/100w.gif" % gid, "/media/%s/giphy-downsized.gif" % gid])
        for _p, q, h in media:
            self.assertEqual(q, {})                                                # no key, no tracking ids, no client address
            self.assertNotIn("X-Forwarded-For", h)
        # cached: a second ask does not go to GIPHY
        http(self.base, "/api/gif/media/%s?r=p" % gid, self.member)
        self.assertEqual(len([x for x in self.giphy.calls if x[0].startswith("/media/")]), 2)
        # an id the hub has not seen in a result: looked up by id at GIPHY's API (GIPHY answers the URL), then fetched
        c, raw, _ = http(self.base, "/api/gif/media/s99?r=p", self.member)
        self.assertEqual((c, raw), (200, self.giphy.gif("s99", "100w.gif")))
        self.assertEqual(self.giphy.api_calls()[-1][0], "/v1/gifs/s99")

    def test_not_an_open_proxy(self):
        self.on()
        d = json.loads(http(self.base, "/api/gif/search?q=edge", self.member)[1])
        self.assertEqual([x["id"] for x in d["items"]], ["goodone1"])           # another host's URL, an R rating, a bad id: dropped
        before = len(self.giphy.calls)
        for path in ("/api/gif/media/evilhost1?r=p",                              # its URL was not GIPHY's media host
                     "/api/gif/media/goodone1?r=original",                         # not on the allow-list
                     "/api/gif/media/goodone1",
                     "/api/gif/media/..%2F..%2Fetc?r=p",
                     "/api/gif/media/https%3A%2F%2Fevil.example%2Fx.gif?r=p",
                     "/api/gif/media/goodone1?r=p&url=https://evil.example/x.gif",
                     "/api/gif/fetch?url=https://evil.example/x.gif",
                     "/api/gif/media/?r=p"):
            c, raw, _ = http(self.base, path, self.member)
            if "url=https://evil.example/x.gif" in path and path.startswith("/api/gif/media/goodone1"):
                self.assertEqual(c, 200)                                           # the page's url= is ignored ...
                self.assertEqual(raw, self.giphy.gif("goodone1", "100w.gif"))      # ... the hub's own URL for the id is used
                continue
            self.assertIn(c, (400, 404), path)
        self.assertFalse(any(p.startswith("/media/evilhost1") for p, _q, _h in self.giphy.calls[before:]))   # (and never evil.example)
        self.assertFalse(any(p.endswith("giphy.gif") for p, _q, _h in self.giphy.calls))   # never the original (large) copy

    def test_who_may_ask(self):
        self.on()
        for bearer in (None, "garbage", self.member + "x"):
            c, raw, _ = http(self.base, "/api/gif/search?q=cats", bearer)
            self.assertEqual(c, 403, bearer and bearer[:6])
            c, _raw, _ = http(self.base, "/api/gif/media/s1?r=p", bearer)
            self.assertEqual(c, 403)
        lobby = tok(self.svc, kr.LOBBY_SLUG, "lobbypc-5555")
        self.assertEqual(http(self.base, "/api/gif/search?q=cats", lobby)[0], 403)   # the Lobby: no
        self.assertEqual(http(self.base, "/api/gif/status", lobby)[0], 403)
        self.assertEqual(self.giphy.calls, [])
        self.assertEqual(http(self.base, "/api/gif/search?q=cats", self.member)[0], 200)

    def test_rate_limit_per_token(self):
        self.on()
        other = tok(self.svc, "tremonton", "hankpc-3c4d")
        with mock.patch.dict(kg.RATE, {"search": (3, 60.0), "media": (2, 60.0)}):
            codes = [http(self.base, "/api/gif/search?q=c%d" % i, self.member)[0] for i in range(4)]
            self.assertEqual(codes, [200, 200, 200, 429])
            c, raw, hdrs = http(self.base, "/api/gif/search?q=c9", self.member)
            self.assertEqual(c, 429)
            self.assertTrue(int(hdrs.get("Retry-After") or 0) >= 1)
            self.assertEqual(http(self.base, "/api/gif/search?q=c1", other)[0], 200)   # another token has its own allowance
            codes = [http(self.base, "/api/gif/media/s1?r=p", self.member)[0] for _ in range(3)]
            self.assertEqual(codes, [200, 200, 429])

    def test_giphy_errors_never_carry_the_key(self):
        self.on()
        c, raw, _ = http(self.base, "/api/gif/search?q=busy", self.member)
        self.assertEqual(c, 503)
        self.assertIn("hourly limit", json.loads(raw)["error"])
        # a refused key: GIPHY's answer (which echoes it here) is never passed on
        self.svc._gifs().key = "A" * 32
        self.svc._gifs().searches.clear()
        c, raw, _ = http(self.base, "/api/gif/search?q=other", self.member)
        self.assertEqual(c, 503)
        self.assertIn("refused the key", json.loads(raw)["error"])
        self.assertNotIn(b"AAAAAAAA", raw)
        v = self.svc.gif_operator_view()[0]
        self.assertIn("refused the key", v["last"]["error"])
        self.assertNotIn("AAAAAAAA", json.dumps(v["last"]))
        self.svc._gifs().key = self.giphy.key
        # GIPHY unreachable
        with mock.patch.dict(os.environ, {"KASTR_GIPHY_BASE": "http://127.0.0.1:9"}):
            self.svc._gifs().searches.clear()
            c, raw, _ = http(self.base, "/api/gif/search?q=dark", self.member)
            self.assertEqual(c, 503)
        for line in self.logs:
            self.assertNotIn(self.giphy.key, line)
            self.assertNotIn("A" * 32, line)
        self.assertTrue(any("GIF search" in ln for ln in self.logs))


class Federation(Base):
    """A spoke's pages: the spoke checks the token and rate-limits, the hub holds the key and asks GIPHY."""

    def setUp(self):
        super().setUp()
        self.hub_key = os.urandom(32)
        self.hdir, self.sdir = self.tmp(), self.tmp()
        self.hub = kr.AuthService("127.0.0.1", 0, self.hub_key, 4443, store(self.hdir), log=self.logs.append)
        self.hbase = ["http://127.0.0.1:%d" % self.hub.httpd.server_address[1]]
        self.fed = kr._mint(self.hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600, node="south"))
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(self.sdir), log=self.logs.append,
                                    hub=lambda: self.hbase[0], fed_token=lambda: self.fed)
        self.sbase = "http://127.0.0.1:%d" % self.spoke.httpd.server_address[1]
        self.member = tok(self.spoke, "tremonton", "kentonpc-1a2b")

    def tearDown(self):
        for s in (self.hub, self.spoke):
            s.close()
        super().tearDown()

    def test_spoke_forwards_to_the_hub(self):
        self.assertTrue(self.spoke._p_spoke())
        self.assertEqual(json.loads(http(self.sbase, "/api/gif/status", self.member)[1])["on"], False)
        self.assertEqual(self.spoke.gif_operator({"key": self.giphy.key})[1], 409)   # the key is set on the hub only
        self.assertTrue(self.spoke.gif_operator_view()[0]["spoke"])
        self.assertFalse(os.path.exists(os.path.join(self.sdir, kg.CONF_NAME)))
        self.hub.gif_operator({"key": self.giphy.key})
        self.spoke.__dict__.pop("_gif_st", None)
        self.assertEqual(json.loads(http(self.sbase, "/api/gif/status", self.member)[1])["on"], True)
        c, raw, _ = http(self.sbase, "/api/gif/search?q=dogs", self.member)
        d = json.loads(raw)
        self.assertEqual((c, d["items"][0]["id"]), (200, "sdogs0"))
        self.no_key_in(raw)
        gid = d["items"][3]["id"]
        c, raw, hdrs = http(self.sbase, "/api/gif/media/%s?r=s" % gid, self.member)
        self.assertEqual((c, raw, hdrs["Content-Type"]), (200, self.giphy.gif(gid, "giphy-downsized.gif"), "image/gif"))
        self.assertEqual(self.giphy.api_calls()[0][1]["rating"], "pg-13")
        # the spoke never holds the key; the hub's federation answers never carry it
        self.assertIsNone(kg.for_dir(self.sdir).key or None)
        # the hub refuses a spoke's GIF call without the federation token, and a member token at the hub is checked as usual
        self.assertEqual(self.hub.rooms_fed({"op": "gif", "what": "search", "q": "x"}, None)[1], 403)
        self.assertEqual(http(self.hbase[0], "/api/gif/media/%s?r=s" % gid, "nope")[0], 403)
        # the spoke's own token check: anonymous and the Lobby are refused before the hub is asked
        n = len(self.giphy.calls)
        self.assertEqual(http(self.sbase, "/api/gif/search?q=cats", None)[0], 403)
        self.assertEqual(http(self.sbase, "/api/gif/search?q=cats", tok(self.spoke, kr.LOBBY_SLUG, "lobbypc-5555"))[0], 403)
        self.assertEqual(len(self.giphy.calls), n)
        # the hub away: a clear 503
        self.hbase[0] = "http://127.0.0.1:9"
        c, raw, _ = http(self.sbase, "/api/gif/search?q=never", self.member)
        self.assertEqual((c, json.loads(raw).get("hubDown")), (503, True))
        for line in self.logs:
            self.assertNotIn(self.giphy.key, line)

    def test_the_hub_limits_each_spoke_device(self):
        self.hub.gif_operator({"key": self.giphy.key})
        with mock.patch.dict(kg.RATE, {"search": (2, 60.0)}):
            body = {"op": "gif", "what": "search", "q": "x", "who": "kentonpc-1a2b"}
            codes = [self.hub.rooms_fed(dict(body, q="x%d" % i), "Bearer " + self.fed)[1] for i in range(3)]
            self.assertEqual(codes, [200, 200, 429])
            self.assertEqual(self.hub.rooms_fed(dict(body, who="hankpc-3c4d"), "Bearer " + self.fed)[1], 200)

    def test_an_older_hub(self):
        orig = self.hub.rooms_fed
        self.hub.gif_operator({"key": self.giphy.key})
        self.spoke._hub_fed = lambda body, timeout=6: ({"ok": False, "error": "bad room"}, 400)
        self.assertEqual(json.loads(http(self.sbase, "/api/gif/status", self.member)[1])["on"], False)
        c, raw, _ = http(self.sbase, "/api/gif/search?q=x", self.member)
        self.assertEqual((c, json.loads(raw).get("off")), (404, True))
        self.assertTrue(callable(orig))


class ThroughKastrServe(Base):
    """A page asks its own KASTR (a box that runs no relay): kastr_serve passes /api/gif/* on to the relay's minter (here a
    spoke, which asks the hub) with the member token -- and the key never shows in /api/diag."""

    def setUp(self):
        super().setUp()
        import kastr_serve
        self.ks = kastr_serve
        hub_key = os.urandom(32)
        self.hub = kr.AuthService("127.0.0.1", 0, hub_key, 4443, store(self.tmp()), log=self.logs.append)
        fed = kr._mint(hub_key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 3600))
        hb = "http://127.0.0.1:%d" % self.hub.httpd.server_address[1]
        self.spoke = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4453, store(self.tmp()), log=self.logs.append,
                                    hub=lambda: hb, fed_token=lambda: fed)
        self.hub.gif_operator({"key": self.giphy.key})
        mport = self.spoke.httpd.server_address[1]
        self.tmpd = self.tmp()
        self.p_ini = mock.patch.object(kastr_serve, "_ini_file", lambda: os.path.join(self.tmpd, "kastr.ini"))
        self.p_ini.start()
        self.srv = kastr_serve.make_server(HERE, "127.0.0.1", 0, quiet=True, relay="https://127.0.0.1:%d" % (mport - 1))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.web = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.member = tok(self.spoke, "tremonton", "kentonpc-1a2b")

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.p_ini.stop()
        self.hub.close()
        self.spoke.close()
        super().tearDown()

    def test_page_to_its_kastr_to_the_spoke_to_the_hub(self):
        c, raw, _ = http(self.web, "/api/gif/status", self.member)
        self.assertEqual((c, json.loads(raw)["on"]), (200, True))
        c, raw, _ = http(self.web, "/api/gif/search?q=birds", self.member)
        d = json.loads(raw)
        self.assertEqual((c, d["items"][0]["id"]), (200, "sbirds0"))
        gid = d["items"][1]["id"]
        c, raw, hdrs = http(self.web, "/api/gif/media/%s?r=p" % gid, self.member)
        self.assertEqual((c, raw, hdrs["Content-Type"]), (200, self.giphy.gif(gid, "100w.gif"), "image/gif"))
        self.assertEqual(http(self.web, "/api/gif/search?q=birds", None)[0], 403)
        # a page's diag report, then /api/diag: no key anywhere
        req = urllib.request.Request(self.web + "/api/diag", data=json.dumps({"page": "lab", "gif": {"on": True}}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10).close()
        c, raw, _ = http(self.web, "/api/diag")
        self.assertEqual(c, 200)
        self.no_key_in(raw)
        for line in self.logs:
            self.assertNotIn(self.giphy.key, line)


class RelayPage(Base):
    """POST/GET /api/relay/gif: this machine only (GUARDED_POSTS), never the key back."""

    class FakeHandler:
        def __init__(self, body=None, method="POST"):
            raw = json.dumps(body or {}).encode()
            self.command = method
            self.headers = {"Content-Length": str(len(raw)), "Host": "127.0.0.1:8000"}
            self.client_address = ("127.0.0.1", 50000)
            self.rfile = __import__("io").BytesIO(raw)
            self.wfile = __import__("io").BytesIO()
            self.code = None
            self.path = "/api/relay/gif"

        def send_response(self, code):
            self.code = code

        def send_header(self, k, v):
            pass

        def end_headers(self):
            pass

        def body(self):
            return json.loads(self.wfile.getvalue().decode())

    def test_set_view_and_guard(self):
        self.assertIn("/api/relay/gif", kr.GUARDED_POSTS)
        d = self.tmp()
        svc = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, store(d), log=self.logs.append)
        try:
            relay = types.SimpleNamespace(auth=svc, state_dir=d)
            saved = kr._local_only
            try:
                kr._local_only = lambda h: True
                h = self.FakeHandler({"key": self.giphy.key})
                self.assertTrue(kr.handle_api(h, relay, "/api/relay/gif"))
                self.assertEqual(h.code, 200)
                self.no_key_in(h.wfile.getvalue())
                self.assertEqual(h.body()["ends"], self.giphy.key[-4:])
                h = self.FakeHandler(method="GET")
                kr.handle_api(h, relay, "/api/relay/gif")
                self.assertEqual((h.code, h.body()["active"], h.body()["hub"]), (200, True, True))
                self.no_key_in(h.wfile.getvalue())
                kr._local_only = lambda h: False                       # another machine (or a tunnel): refused
                h = self.FakeHandler({"remove": True})
                kr.handle_api(h, relay, "/api/relay/gif")
                self.assertEqual(h.code, 403)
                h = self.FakeHandler(method="GET")
                kr.handle_api(h, relay, "/api/relay/gif")
                self.assertEqual(h.code, 403)
                self.assertTrue(svc._gifs().active())
                # no secured relay on this machine: the key can still be kept (the card says GIF search needs access codes)
                kr._local_only = lambda h: True
                d2 = self.tmp()
                h = self.FakeHandler(method="GET")
                kr.handle_api(h, types.SimpleNamespace(auth=None, state_dir=d2), "/api/relay/gif")
                self.assertEqual((h.code, h.body()["secured"], h.body()["set"]), (200, False, False))
            finally:
                kr._local_only = saved
        finally:
            svc.close()
        for line in self.logs:
            self.assertNotIn(self.giphy.key, line)


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = _read("moq-watch-lite.html")
        cls.msg = _read(os.path.join("assets", "kastr-msg.js"))
        cls.gif = _read(os.path.join("assets", "kastr-gif.js"))
        cls.relay = _read("relay.html")
        cls.serve = _read("kastr_serve.py")

    def test_the_picker(self):
        g = self.gif
        self.assertIn("window.__gif = {", g)
        self.assertIn('"/api/gif/status"', g)
        self.assertIn('"/api/gif/search?q="', g)
        self.assertIn('"/api/gif/media/"', g)
        self.assertIn('authorization: "Bearer " + t', g)          # the member token in a header, never in a URL
        self.assertNotIn("giphy.com", g)                            # a page never names GIPHY's hosts
        self.assertIn("Powered by GIPHY", g)
        self.assertIn('if (e.key === "Escape" && open())', g)
        self.assertIn("IntersectionObserver", g)                    # previews load as they scroll into view; more at the bottom
        self.assertIn("setTimeout(() => run(", g)                   # debounced search

    def test_messages_composer(self):
        m = self.msg
        self.assertIn('<button type="button" class="mgif" title="GIF" hidden>GIF</button>', m)
        self.assertIn('<div class="mgifgrid kgif" hidden></div>', m)
        self.assertIn("window.__gif?.mount(", m)
        self.assertIn("send(conv, \"\", [file])", m)                # an encrypted attachment like a pasted picture
        i = m.index('class="memo"'); j = m.index('class="mgif"', i); k = m.index('class="mattach"', j)
        self.assertTrue(i < j < k)

    def test_room_chat_composer(self):
        p = self.page
        self.assertIn('<button type="button" id="chatGifBtn" class="cbtn cgif" title="GIF" hidden>GIF</button>', p)
        self.assertIn('<div id="chatGif" class="kgif" hidden></div>', p)
        self.assertIn("async function chatSendGif(file)", p)
        self.assertIn('fetch(chatUrl("/api/chat/" + chatRoom + "/files")', p[p.index("async function chatSendGif"):])
        self.assertIn("over = over && Array.isArray(over.files) ? over : null;", p)   # the Send button's click event is not a GIF
        self.assertIn('<script type="module" src="/assets/kastr-gif.js"></script>', p)
        self.assertLess(p.index('src="/assets/kastr-gif.js"'), p.index('src="/assets/kastr-msg.js"'))
        self.assertIn("window.__kgif = {", p)
        self.assertIn(".kgif {", p)

    def test_relay_page_card(self):
        r = self.relay
        self.assertIn('id="gifPanel"', r)
        self.assertIn('<input type="password" id="gifKey"', r)
        self.assertIn("100 searches an hour", r)
        self.assertIn('fetch("/api/relay/gif"', r)
        self.assertNotIn("gifKey\").value = d", r)                  # the key is never put back into the field

    def test_serve_and_build(self):
        self.assertIn('if path.startswith("/api/gif/"):', self.serve)
        self.assertIn('out.append("/assets/kastr-gif.js")', self.serve)
        self.assertIn('"--hidden-import", "kastr_gif"', _read("build.py"))

    def test_line_endings(self):
        for name, crlf in (("moq-watch-lite.html", True), ("relay.html", True), ("kastr_serve.py", True), ("kastr_relay.py", False),
                           ("kastr_gif.py", False), (os.path.join("assets", "kastr-msg.js"), False), (os.path.join("assets", "kastr-gif.js"), False)):
            with open(os.path.join(HERE, name), "rb") as f:
                raw = f.read()
            if crlf:
                self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)
            else:
                self.assertNotIn(b"\r\n", raw, name)


if __name__ == "__main__":
    unittest.main()
