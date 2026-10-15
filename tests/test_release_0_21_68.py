"""v0.21.68: the Relay page's Pull test shows the moq tool's last line without terminal colour codes.

Run: python -m unittest discover -s tests
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PullTestText(unittest.TestCase):
    def test_colour_codes_stripped(self):
        with open(os.path.join(HERE, "kastr_relay.py"), encoding="utf-8") as f:
            src = f.read()
        i = src.index("# 0.21.68: no terminal colour codes")
        line = src[src.rindex(chr(10), 0, i):i]
        pat = re.search(r're\.sub\(r"(.*?)", ""', line).group(1)
        self.assertNotIn(chr(27), line)
        raw = chr(27) + "[2m2026-10-15T02:34:59Z" + chr(27) + "[0m " + chr(27) + "[32m INFO" + chr(27) + "[0m subscribe started"
        self.assertEqual(re.sub(pat, "", raw), "2026-10-15T02:34:59Z  INFO subscribe started")

class AccentInk(unittest.TestCase):
    """0.21.68 (Kenton: the "You're here" pill unreadable on a yellow accent): text on the accent = black or white by contrast."""
    def test_wired(self):
        rd = lambda f: open(os.path.join(HERE, f), encoding="utf-8").read()
        css, js, p, r = rd("assets/asi-brand.css"), rd("assets/asi-brand.js"), rd("moq-watch-lite.html"), rd("relay.html")
        self.assertIn("--on-accent:     #06121a;", css)
        self.assertIn('st.setProperty("--on-accent", accentInk(c));', js)
        self.assertIn('st.removeProperty("--on-accent");', js)
        self.assertIn('document.documentElement.style.setProperty("--on-accent",', p.split("</script>", 1)[0])
        self.assertIn(".sbcard.cur .sbtag.here { display:inline-block; background:var(--asi-blue); color:var(--on-accent); }", p)
        self.assertIn(".sbcard.cur .rb { border-color:var(--asi-blue); background:var(--asi-blue); color:var(--on-accent);", p)
        for src in (p, r):   # no rule paints fixed white / dark text on the accent any more
            for line in src.splitlines():
                if re.search(r"background:var\(--asi-blue\)(?![-\w])", line):
                    self.assertIsNone(re.search(r"(?<![-\w])color:(#06121a|#fff)\b", line), line.strip()[:120])

    def test_ink_choice(self):
        js = open(os.path.join(HERE, "assets/asi-brand.js"), encoding="utf-8").read()
        self.assertIn('return (L + 0.05) / (Ld + 0.05) >= 1.05 / (L + 0.05) ? "#06121a" : "#ffffff";', js)

        def ink(h):   # the same rule in Python
            ch = lambda i: (lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)(int(h[i:i + 2], 16) / 255)
            L = 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5)
            return "#06121a" if (L + 0.05) / 0.0558 >= 1.05 / (L + 0.05) else "#ffffff"
        self.assertEqual(ink("#e5ff00"), "#06121a")   # Kenton's yellow
        self.assertEqual(ink("#009fda"), "#06121a")   # ASI blue
        self.assertEqual(ink("#1a237e"), "#ffffff")
        self.assertEqual(ink("#c62828"), "#ffffff")

class TokenRetry(unittest.TestCase):
    """0.21.68 (Kenton: "Could not join aoz-6: Failed to fetch" -- joined on a later try): a network failure of the token
    request is tried again twice (1.5 s, 3 s); refusals are not retried."""
    def test_wired(self):
        p = open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8").read()
        body = p[p.index("  async function authMint(room, access, roomCode) {"):p.index("    authTokens = d.tokens;")]
        self.assertIn("for (let attempt = 0; ; attempt++) {", body)
        self.assertIn("if (attempt >= 2) throw new Error(", body)
        self.assertIn("await new Promise((res) => setTimeout(res, 1500 * (attempt + 1)));", body)
        self.assertIn('if (!r.ok || !d.ok) throw new Error(d.error || ("token refused (" + r.status + ")"));', body)   # refusals: no retry


if __name__ == "__main__":
    unittest.main()
