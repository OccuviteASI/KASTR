"""0.21.91 (Kenton: "I would like to add gif search options as well to the chat/messages."): GIF SEARCH THROUGH THE HUB.

Kenton's decisions: GIPHY; HIS key, pasted on the hub's Relay page, kept here on the hub and never handed to a page, a log, a
diag report or a test; every call goes through the hub (a page asks the relay it uses, a spoke forwards to the hub), so
GIPHY never sees a person's address; rating PG-13.

NOT AN OPEN PROXY: the hub builds every GIPHY request itself -- the API from a search term / an offset / a GIF id, the
pictures from the rendition URLs GIPHY's own API answered for that id (looked up again by id when they are not cached),
for a fixed allow-list of renditions, and only on GIPHY's media hosts. A page never names a URL.

The relay (kastr_relay.AuthService.gif_*) checks who asks (a member token of a room, or a spoke's federation token) and
rate-limits; this module keeps the key, talks to GIPHY and caches answers (search 5 minutes, pictures 15 minutes).
"""
import collections
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import kastr_ua  # noqa: F401  -- "KASTR/<version>" as the user agent
except Exception:  # pragma: no cover
    pass
import kastr_secret   # 0.21.92: the key is kept sealed (DPAPI / the owner-only key file), never in plain text

CONF_NAME = "gif-search.json"
KEY_RE = re.compile(r"^[A-Za-z0-9]{16,64}$")
ID_RE = re.compile(r"^[A-Za-z0-9]{1,48}$")
RATING = "pg-13"                     # Kenton: PG-13
RATINGS_OK = ("g", "pg", "pg-13")
PAGE = 24                            # GIFs per page of results
OFFSET_MAX = 480                     # how far "load more" goes
Q_MAX = 50
# the renditions a page may ask for -- "p": the small animated preview in the grid; "s": the copy that is sent (GIPHY's
# "downsized" is under 2 MB; a larger one falls back to the 200 px wide copy)
RENDITIONS = {"p": ("fixed_width_small", "fixed_width"), "s": ("downsized", "fixed_width")}
SIZE_MAX = {"p": 1536 * 1024, "s": 3 * 1024 * 1024}
SEARCH_TTL = 300
MEDIA_TTL = 900
MEDIA_CACHE_BYTES = 48 * 1024 * 1024
IDS_MAX = 4000
SEARCH_CACHE_MAX = 300
# per asker (a member token at the relay it calls; a spoke's device at the hub)
RATE = {"search": (30, 60.0), "media": (300, 60.0)}
API_TIMEOUT = 8
MEDIA_TIMEOUT = 15
GIPHY_API = "https://api.giphy.com/v1/gifs"
MEDIA_HOST_RE = re.compile(r"^(media\d{0,2}|i)\.giphy\.com$")
MEDIA_PATH_RE = re.compile(r"^/[A-Za-z0-9._/=-]{1,200}\.(gif|webp)$")


def _lab_base():
    """A lab / test mock of GIPHY (KASTR_GIPHY_BASE=http://127.0.0.1:<port>) -- loopback only, never a real host."""
    b = str(os.environ.get("KASTR_GIPHY_BASE") or "").strip().rstrip("/")
    return b if re.match(r"^http://(127\.0\.0\.1|localhost)(:\d{1,5})?$", b) else ""


def api_base():
    b = _lab_base()
    return (b + "/v1/gifs") if b else GIPHY_API


def media_ok(url):
    """Is this one of GIPHY's picture URLs (as GIPHY's API answered it)? -> the URL to fetch (no query), else ""."""
    try:
        u = urllib.parse.urlsplit(str(url or ""))
    except ValueError:
        return ""
    if ".." in u.path or not MEDIA_PATH_RE.match(u.path or ""):
        return ""
    lab = _lab_base()
    if lab:
        if (u.scheme + "://" + u.netloc).lower() != lab.lower():
            return ""
    elif u.scheme != "https" or u.port not in (None, 443) or not MEDIA_HOST_RE.match((u.hostname or "").lower()):
        return ""
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))


def gif_magic(data):
    return bool(data) and (data[:6] in (b"GIF87a", b"GIF89a") or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


def clean_q(q):
    return " ".join(str(q or "").split())[:Q_MAX]


def clean_offset(v):
    try:
        n = int(str(v or "0").strip() or 0)
    except ValueError:
        return 0
    return max(0, min(OFFSET_MAX, n))


class Rate:
    """A sliding-window limit per asker."""

    def __init__(self):
        self.lock = threading.Lock()
        self.hits = {}

    def allow(self, who, kind, now=None):
        n, per = RATE[kind]
        now = time.time() if now is None else now
        k = kind + "|" + str(who)
        with self.lock:
            q = self.hits.get(k)
            if q is None:
                q = self.hits[k] = collections.deque()
            while q and now - q[0] > per:
                q.popleft()
            if len(q) >= n:
                return False, int(per - (now - q[0])) + 1
            q.append(now)
            if len(self.hits) > 5000:
                for kk in [kk for kk, v in self.hits.items() if not v or now - v[-1] > per]:
                    self.hits.pop(kk, None)
            return True, 0


class GifSearch:
    """The hub's GIPHY client: the key (gif-search.json in the state folder), the on/off switch, the caches."""

    def __init__(self, state_dir, log=None):
        self.dir = state_dir or os.getcwd()
        self.log = log or (lambda m: None)
        self.lock = threading.Lock()
        self.key, self.on, self.at = "", False, 0
        self.last = {"ok": None, "at": 0, "error": ""}
        self.searches = collections.OrderedDict()     # (kind, q, offset) -> (at, reply)
        self.ids = collections.OrderedDict()          # gif id -> {"p": url, "s": url}
        self.media = collections.OrderedDict()        # (id, r) -> (at, bytes, ctype)
        self.media_bytes = 0
        self.rate = Rate()
        self._load()

    # ---- the key and the switch (the hub's Relay page) -----------------------------------------------------------------
    def _path(self):
        return os.path.join(self.dir, CONF_NAME)

    def _load(self):
        try:
            with open(self._path(), encoding="utf-8-sig") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return
        d = kastr_secret.open_doc(self._path(), raw)   # 0.21.92: the sealed key opened (an old plain one still reads)
        if isinstance(d, dict):
            k = str(d.get("key") or "")
            self.key = k if KEY_RE.match(k) else ""
            self.on = d.get("on") is True
            try:
                self.at = int(d.get("at") or 0)
            except (TypeError, ValueError):
                self.at = 0

    def _save(self):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._path() + ".%d.tmp" % os.getpid()
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(kastr_secret.seal_doc(self._path(), {"key": self.key, "on": self.on, "at": self.at}), f)   # 0.21.92
        os.replace(tmp, self._path())
        try:
            os.chmod(self._path(), 0o600)
        except OSError:
            pass

    def active(self):
        with self.lock:
            return bool(self.key) and self.on

    def view(self):
        """What the Relay page shows -- never the key (its last four characters at most)."""
        with self.lock:
            return {"set": bool(self.key), "ends": self.key[-4:] if self.key else "", "on": self.on,
                    "active": bool(self.key) and self.on, "at": self.at, "last": dict(self.last)}

    def configure(self, p):
        """{key} | {remove: true} | {on: bool} -> (view, 200) | (error, 400). Never logs or answers the key."""
        p = p if isinstance(p, dict) else {}
        with self.lock:
            if p.get("remove") is True:
                self.key, self.on = "", False
                what = "removed"
            elif "key" in p:
                k = str(p.get("key") or "").strip()
                if not KEY_RE.match(k):
                    return {"ok": False, "error": "that is not a GIPHY API key (16-64 letters and digits)"}, 400
                self.key = k
                if "on" not in p:
                    self.on = True          # a new key switches GIF search on (the switch turns it off again)
                what = "saved"
            else:
                what = ""
            if isinstance(p.get("on"), bool):
                if p["on"] and not self.key:
                    return {"ok": False, "error": "paste a GIPHY API key first"}, 400
                self.on = p["on"]
                what = what or ("switched on" if self.on else "switched off")
            if not what:
                return {"ok": False, "error": "nothing to change"}, 400
            self.at = int(time.time())
            self.searches.clear()
            self.last = {"ok": None, "at": 0, "error": ""}
            try:
                self._save()
            except OSError as e:
                return {"ok": False, "error": "could not save: %s" % str(e)[:120]}, 500
        self.log("relay auth: GIF search (GIPHY) %s" % what)
        return dict(self.view(), ok=True), 200

    # ---- GIPHY --------------------------------------------------------------------------------------------------------
    def _scrub(self, s):
        s = str(s or "")
        k = self.key
        return s.replace(k, "...") if k else s

    def _open(self, url, timeout):
        if _lab_base():
            return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=timeout)
        return urllib.request.urlopen(url, timeout=timeout)

    def _api(self, path, params):
        """-> (dict, None) | (None, (error reply, code)). The key rides the query of this one request only."""
        with self.lock:
            key = self.key
        if not key:
            return None, ({"ok": False, "off": True, "error": "GIF search is off on this fleet"}, 404)
        url = api_base() + path + "?" + urllib.parse.urlencode(dict(params, api_key=key))
        try:
            with self._open(url, API_TIMEOUT) as r:
                raw = r.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("GIPHY's answer was too large")
            d = json.loads(raw.decode("utf-8", "replace") or "{}")
            if not isinstance(d, dict):
                raise ValueError("GIPHY answered oddly")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                err = ("GIPHY refused the key -- check it on the hub's Relay page", 503)
            elif e.code == 429:
                err = ("GIF search is busy (GIPHY's hourly limit) -- try again later", 503)
            elif e.code == 404:
                err = ("no such GIF", 404)
            else:
                err = ("GIPHY answered %d" % e.code, 502)
            self._note(False, err[0])
            return None, ({"ok": False, "error": err[0]}, err[1])
        except Exception as e:
            msg = self._scrub(getattr(e, "reason", None) or e)[:120]
            self._note(False, "GIPHY did not answer: " + msg)
            return None, ({"ok": False, "error": "GIPHY did not answer -- try again shortly"}, 503)
        self._note(True, "")
        return d, None

    def _note(self, ok, err):
        with self.lock:
            self.last = {"ok": ok, "at": int(time.time()), "error": self._scrub(err)[:160]}
        if not ok:
            self.log("relay auth: GIF search: %s" % self._scrub(err)[:160])

    def _remember(self, it):
        """One GIPHY result -> the page's row {id, w, h, t}, and its rendition URLs kept by id (None: not usable)."""
        if not isinstance(it, dict):
            return None
        gid = str(it.get("id") or "")
        if not ID_RE.match(gid) or str(it.get("rating") or "pg-13").lower() not in RATINGS_OK:
            return None
        imgs = it.get("images") if isinstance(it.get("images"), dict) else {}
        urls = {}
        for r, names in RENDITIONS.items():
            for nm in names:
                im = imgs.get(nm) if isinstance(imgs.get(nm), dict) else {}
                u = media_ok(im.get("url"))
                try:
                    size = int(im.get("size") or 0)
                except (TypeError, ValueError):
                    size = 0
                if u and size <= SIZE_MAX[r]:
                    urls[r] = u
                    if r == "p":
                        try:
                            urls["w"], urls["h"] = int(im.get("width") or 0), int(im.get("height") or 0)
                        except (TypeError, ValueError):
                            urls["w"] = urls["h"] = 0
                    break
        if "p" not in urls or "s" not in urls:
            return None
        with self.lock:
            self.ids[gid] = urls
            self.ids.move_to_end(gid)
            while len(self.ids) > IDS_MAX:
                self.ids.popitem(last=False)
        return {"id": gid, "w": urls.get("w") or 100, "h": urls.get("h") or 100, "t": str(it.get("title") or "")[:80]}

    def search(self, q, offset, now=None):
        """Search (q) or trending (no q) -> ({ok, items, next}, 200) | (error, code)."""
        now = time.time() if now is None else now
        if not self.active():
            return {"ok": False, "off": True, "error": "GIF search is off on this fleet"}, 404
        q, offset = clean_q(q), clean_offset(offset)
        ck = (q.lower(), offset)
        with self.lock:
            hit = self.searches.get(ck)
            if hit and now - hit[0] < SEARCH_TTL:
                return dict(hit[1]), 200
        params = {"limit": PAGE, "offset": offset, "rating": RATING}
        if q:
            params.update(q=q, lang="en")
        d, err = self._api("/search" if q else "/trending", params)
        if err:
            return err
        rows = [x for x in (self._remember(it) for it in (d.get("data") or [])[:PAGE * 2] if isinstance(d.get("data"), list)) if x]
        pg = d.get("pagination") if isinstance(d.get("pagination"), dict) else {}
        try:
            got, total = int(pg.get("count") or len(d.get("data") or [])), int(pg.get("total_count") or 0)
        except (TypeError, ValueError):
            got, total = len(rows), 0
        nxt = offset + got
        more = got > 0 and nxt <= OFFSET_MAX and (not total or nxt < total)
        out = {"ok": True, "items": rows, "next": nxt if more else None}
        with self.lock:
            self.searches[ck] = (now, out)
            while len(self.searches) > SEARCH_CACHE_MAX:
                self.searches.popitem(last=False)
        return dict(out), 200

    def _urls_of(self, gid):
        with self.lock:
            u = self.ids.get(gid)
        if u:
            return u, None
        d, err = self._api("/" + gid, {"rating": RATING})   # the id only -- GIPHY answers its own URLs
        if err:
            return None, err
        row = self._remember(d.get("data"))
        if not row or row["id"] != gid:
            return None, ({"ok": False, "error": "no such GIF"}, 404)
        with self.lock:
            return self.ids.get(gid), None

    def media_get(self, gid, r, now=None):
        """-> (bytes, content type, 200) | (error reply, None, code). `r` from the allow-list only."""
        now = time.time() if now is None else now
        gid, r = str(gid or ""), str(r or "")
        if not ID_RE.match(gid) or r not in RENDITIONS:
            return {"ok": False, "error": "no such GIF"}, None, 400
        if not self.active():
            return {"ok": False, "off": True, "error": "GIF search is off on this fleet"}, None, 404
        ck = (gid, r)
        with self.lock:
            hit = self.media.get(ck)
            if hit and now - hit[0] < MEDIA_TTL:
                self.media.move_to_end(ck)
                return hit[1], hit[2], 200
        urls, err = self._urls_of(gid)
        if err:
            return err[0], None, err[1]
        url = media_ok((urls or {}).get(r))
        if not url:
            return {"ok": False, "error": "no such GIF"}, None, 404
        try:
            with self._open(url, MEDIA_TIMEOUT) as resp:     # no key, no cookie, no client address: the hub asks
                data = resp.read(SIZE_MAX[r] + 1)
        except urllib.error.HTTPError as e:
            return {"ok": False, "error": "GIPHY answered %d for that GIF" % e.code}, None, 502
        except Exception:
            return {"ok": False, "error": "GIPHY did not send that GIF -- try again shortly"}, None, 503
        if len(data) > SIZE_MAX[r]:
            return {"ok": False, "error": "that GIF is too large to send"}, None, 413
        if not gif_magic(data):
            return {"ok": False, "error": "GIPHY sent something that is not a GIF"}, None, 502
        ctype = "image/gif" if data[:3] == b"GIF" else "image/webp"
        with self.lock:
            old = self.media.pop(ck, None)
            if old:
                self.media_bytes -= len(old[1])
            self.media[ck] = (now, data, ctype)
            self.media_bytes += len(data)
            while self.media_bytes > MEDIA_CACHE_BYTES and self.media:
                _k, v = self.media.popitem(last=False)
                self.media_bytes -= len(v[1])
        return data, ctype, 200


_ONE = {}
_ONE_LOCK = threading.Lock()


def for_dir(state_dir, log=None):
    """One GifSearch per state folder (the relay's minter and its Relay page share it)."""
    k = os.path.abspath(state_dir or os.getcwd())
    with _ONE_LOCK:
        g = _ONE.get(k)
        if g is None:
            g = _ONE[k] = GifSearch(k, log)
        return g
