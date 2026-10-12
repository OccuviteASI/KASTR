"""0.21.52 (field, Mendon: the grid sometimes showed as separate tiles until KASTR was restarted on the box): a grid tile
without geometry for 20 s subscribes its owner's room.json from presence; a remote restart of a spoke from the hub;
a relay's log collection carries its own page's diagnostics."""
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def read(n):
    return open(os.path.join(ROOT, n), encoding="utf-8").read()


class GridRescue(unittest.TestCase):
    def test_rescue_from_presence(self):
        p = read("moq-watch-lite.html")
        self.assertIn("if (!/\/rtsp-grid(-\d+)?\.hang$/.test(name) || gridMeta.has(name))", p)
        self.assertIn('const mp = parts[0] + "/" + parts[1] + "/~member/" + p.who.peer;', p)
        self.assertIn("if (w) wrMemberAccept(w, mp, true); else if (connection) memberAccept(mp, true); else continue;", p)
        self.assertIn("roomState: (() => {", p)

    def test_box_diag_in_collection(self):
        self.assertIn('files["diag.json"] = redact_log(r.read().decode("utf-8", "replace"))[-LOG_FILE_CAP:]', read("kastr_relay.py"))


class RemoteRestart(unittest.TestCase):
    def test_hub_command_and_spoke_handler(self):
        r = read("kastr_relay.py")
        self.assertIn('if path == "/api/relay/spokes/restart":', r)
        self.assertIn('rec = auth.raise_cmd("restart", {"spoke": one})', r)
        self.assertIn('if name == "restart":   # 0.21.52', r)
        self.assertIn('"boot": BOOT_AT}).encode()', r)

    def test_relay_page_spins_until_it_is_back(self):
        h = read("relay.html")
        self.assertIn("if (r.boot && r.boot * 1000 > p.at)", h)
        self.assertIn('class=\\"ghost sprst\\"', h)

    def test_restart_command_reaches_the_spoke(self):
        import tempfile, time
        import kastr_relay as kr
        st = kr.AuthStore(tempfile.mkdtemp())
        s = kr.AuthService("127.0.0.1", 0, os.urandom(32), 4443, st)
        try:
            tok = "Bearer " + kr._mint(s.key, dict(kr.FEDERATION_CLAIMS, iat=int(time.time()), exp=int(time.time()) + 600))
            s.register_spoke({"name": "mendon-relay", "boot": 123}, "10.0.0.2", tok)
            self.assertEqual(s.spokes_public()[0]["boot"], 123)
            rec = s.raise_cmd("restart", {"spoke": "mendon-relay"})
            d, _ = s.bans_for_spoke(tok, peer="10.0.0.2")
            self.assertEqual([(x["seq"], x["spoke"]) for x in d["cmd"]["restart"]], [(rec["seq"], "mendon-relay")])
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()


class AvatarCentred(unittest.TestCase):
    def test_caption_and_meter_hang_below_the_circle(self):
        p = read("moq-watch-lite.html")
        self.assertIn("#stage .pane.audio-only .face > canvas.eq, .pane.audio-only .face > .cap { position:absolute; left:50%; transform:translateX(-50%); margin:0; }", p)
        self.assertIn(".pane.audio-only .face > .cap { top:calc(50% + min(18cqw, 35cqh, 75px) + 40px); }", p)
