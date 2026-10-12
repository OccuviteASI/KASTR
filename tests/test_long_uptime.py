# -*- coding: utf-8 -*-
"""0.21.58 (field: "sites get stale if they are connected too long ... I had to restart 2 sites after the weekend" -- Linux
boxes, auth server refusals, cameras / grid not showing, frozen pictures). Kenton chose a 1-hour grace on re-checks and no
nightly restart. Covers: the grace hour, pairs renewing the token they RUN with, a parked pair never re-dialling an
expired token, the minter after the page left its room, the relay supervisor, the operator token's day, the log reader."""
import io, os, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_relay as kr  # noqa: E402
import kastr_rtsp as rt  # noqa: E402


def tok(key, exp, **claims):
    return kr._mint(key, dict({"root": "", "get": "main", "put": ["main"], "iat": int(exp) - 86400, "exp": int(exp)}, **claims))


class Grace(unittest.TestCase):
    def setUp(self):
        self.s = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, kr.AuthStore(tempfile.mkdtemp()))

    def tearDown(self):
        self.s.close()

    def ask(self, ev, t, sid="s1"):
        return self.s.session({"event": ev, "id": sid, "remote": "127.0.0.1:5000", "path": "/main", "query": "jwt=" + t}, "127.0.0.1")

    def test_a_recheck_keeps_a_token_that_ran_out_minutes_ago(self):
        o, c = self.ask("revalidate", tok(self.s.key, time.time() - 600))
        self.assertEqual(c, 200, o)
        self.assertEqual(getattr(self.s, "graced", 0), 1)

    def test_not_past_the_hour(self):
        self.assertEqual(self.ask("revalidate", tok(self.s.key, time.time() - kr.TOKEN_GRACE_S - 60))[1], 403)

    def test_a_new_connection_needs_a_live_token(self):
        self.assertEqual(self.ask("connect", tok(self.s.key, time.time() - 600))[1], 403)

    def test_another_key_or_a_revoked_session_gets_nothing(self):
        self.assertEqual(self.ask("revalidate", tok(os.urandom(32), time.time() - 600))[1], 403)
        self.ask("connect", tok(self.s.key, time.time() + 3600), sid="s2")
        self.s._sessions["s2"]["revoked"] = True
        self.assertEqual(self.ask("revalidate", tok(self.s.key, time.time() - 600), sid="s2")[1], 403)

    def test_token_exp_signed(self):
        t = tok(self.s.key, 1234567890)
        self.assertEqual(kr.token_exp_signed(t, self.s.key), 1234567890)
        self.assertIsNone(kr.token_exp_signed(t, os.urandom(32)))


def url_with(key, exp):
    return "https://127.0.0.1:4443/?jwt=" + tok(key, exp)


class PairRenewal(unittest.TestCase):
    """A Publisher without processes: only the renewal decisions."""
    def pub(self, run_exp, live_exp):
        key = os.urandom(32)
        p = rt.Publisher.__new__(rt.Publisher)
        p.stopping = False
        p.broadcast = "main/box-1a2b/rtsp-1.hang"
        p.bridge = type("B", (), {"log": staticmethod(lambda *a: None)})()
        p.runToken = rt._relay_token(url_with(key, run_exp))
        p.relay = url_with(key, live_exp)
        p.tokenExp = run_exp
        p.minter = None
        p._mintAt = 0
        p._lock = threading.Lock()
        p.calls = []
        p.retoken = lambda u: p.calls.append(("retoken", u))
        p._arm_renew = lambda: p.calls.append(("arm",))
        return p

    def test_a_fresher_posted_token_is_moved_onto_before_the_old_one_ends(self):
        now = time.time()
        p = self.pub(now + 600, now + 86400)            # running on a token with 10 min left; the page posted a day's
        p._renew_tick()
        self.assertEqual(p.calls[0][0], "retoken")       # 0.21.57 re-armed here and the relay cut it later

    def test_the_running_token_decides(self):
        now = time.time()
        p = self.pub(now + 7200, now + 7200)
        p._renew_tick()
        self.assertEqual(p.calls, [("arm",)])

    def test_sources(self):
        with io.open(os.path.join(HERE, "kastr_rtsp.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("self.runToken = _relay_token(self.relay)", src)
        self.assertIn("if now - self._bareAt >= 300 and not (live_exp and live_exp <= now):", src)   # no bare retry on an expired token


class MinterAfterLeave(unittest.TestCase):
    def test_the_last_room_still_mints(self):
        br = rt.Bridge.__new__(rt.Bridge)
        br._session = {"room": "main", "access": "c", "roomCode": "", "relay": "https://127.0.0.1:4443"}
        br._last_session = dict(br._session)
        br._pubs = {}
        br.host_slug = "box-1a2b"
        br.log = lambda *a: None
        asked = []
        old = rt.mint_member
        rt.mint_member = lambda base, room, access, code, host=None: (asked.append((base, room)), ("token", base + "/?jwt=x", ""))[1]
        try:
            feed = type("F", (), {"id": 1, "room": ""})()
            mint = br._minter_for(feed, "main/box-1a2b/rtsp-1.hang", "https://127.0.0.1:4443")
            br._session = {"room": "", "access": "", "roomCode": "", "relay": ""}   # the page left
            self.assertEqual(mint(), "https://127.0.0.1:4443/?jwt=x")
            self.assertEqual(asked, [("https://127.0.0.1:4443", "main")])
        finally:
            rt.mint_member = old


class Supervisor(unittest.TestCase):
    def test_an_unexpected_exit_restarts_the_relay(self):
        r = kr.Relay(tempfile.mkdtemp(), log=lambda *a: None)

        class P:
            returncode = 9
            def wait(self, timeout=None): return 9
            def poll(self): return 9
        p = P()
        r.proc = p
        r.port, r.bind_all, r.secured = 4443, False, False
        starts = []
        r._stop_locked = lambda: setattr(r, "proc", None)
        r._start_locked = lambda port, lan, sec: starts.append((port, lan, sec))
        timers = []
        old = kr.threading.Timer
        kr.threading.Timer = lambda d, fn, *a, **k: type("T", (), {"start": lambda self: timers.append((d, fn)), "daemon": True})()
        try:
            r._supervise(p)
            self.assertEqual(timers[0][0], 5)            # first exit: back in 5 s
            timers[0][1]()
            self.assertEqual(starts, [(4443, False, False)])
        finally:
            kr.threading.Timer = old

    def test_a_deliberate_stop_is_left_alone(self):
        r = kr.Relay(tempfile.mkdtemp(), log=lambda *a: None)
        p = type("P", (), {"wait": lambda self, timeout=None: 0})()
        r.proc = None                                     # stop() cleared it first
        r._supervise(p)
        self.assertFalse(getattr(r, "_crashes", []))

    def test_sources(self):
        with io.open(os.path.join(HERE, "kastr_relay.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('text=True, encoding="utf-8", errors="replace"', src)   # no decode error can end the reader
        self.assertIn("exp = now + (86400 if not slug else 3600)", src)        # recordings no longer cut hourly
        with io.open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("mainUrlSig.set(fresh);", page)


if __name__ == "__main__":
    unittest.main()
