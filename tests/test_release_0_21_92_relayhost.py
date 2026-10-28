"""0.21.92 item 3 (a non-hub KASTR answered "already has a My room with another code" right after Set up with a brand-new
name). Reproduced on a lab of three KASTRs on one machine: hub, spoke, and a SECOND KASTR on the spoke's machine whose page
used the spoke's relay. relayHostBase() said "same machine" and sent My room (and chat) to the page's OWN KASTR -- a store
nobody else reads -- while Messages asked the relay (the hub): Set up made My room in the wrong store, Messages then said
"Wrong My room code", and the next Set up there (another device, the same name) said "already has a My room with another
code" although the hub had none. Now the relay's /api/auth web port (the KASTR that runs that relay) wins on the same
machine when it is not the page's own.

The page's own relayHostBase runs under node (skipped without node), with authWeb / authWebFor / authBase stubbed.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(HERE, "moq-watch-lite.html")


def page_text():
    with open(PAGE, encoding="utf-8", newline="") as f:
        return f.read()


def func_source(text, name):
    m = re.search(r"\n  function %s\([^)]*\) \{" % re.escape(name), text)
    if not m:
        return None
    depth, j = 0, m.end() - 1
    while j < len(text):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[m.start() + 1:j + 1]
        j += 1
    return None


# (page origin, relay url, authWeb, the relay whose /api/auth said it, IS_WEB) -> the base My room / chat go to
CASES = [
    # the usual app: this KASTR runs the relay -> its own origin
    ("http://127.0.0.1:8000", "https://localhost:4443", 8000, "http://localhost:4444", False, "http://127.0.0.1:8000"),
    # a second KASTR on the relay's machine (the lab's 9183 page on the spoke's relay, the spoke's KASTR on 9182)
    ("http://127.0.0.1:9183", "http://localhost:4944", 9182, "http://localhost:4945", False, "http://127.0.0.1:9182"),
    ("http://localhost:8001", "https://127.0.0.1:4443", 8000, "http://127.0.0.1:4444", False, "http://localhost:8000"),
    # the relay never said (an older relay): as before
    ("http://127.0.0.1:9183", "http://localhost:4944", 0, "", False, "http://127.0.0.1:9183"),
    # authWeb came from ANOTHER relay (the page is switching relays): as before, until this relay answers
    ("http://127.0.0.1:9183", "http://localhost:4944", 9182, "http://otherbox:4444", False, "http://127.0.0.1:9183"),
    # another machine: its web port, as before
    ("http://127.0.0.1:8000", "https://10.1.2.3:4443", 8010, "http://10.1.2.3:4444", False, "http://10.1.2.3:8010"),
    # a web page (served by the relay host's KASTR): its origin, as before
    ("http://127.0.0.1:9183", "http://localhost:4944", 9182, "http://127.0.0.1:9183", True, "http://127.0.0.1:9183"),
]


class RelayHostBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = page_text()

    def test_markers(self):
        self.assertEqual(self.text.count("let authWebFor = \"\";"), 1)
        self.assertEqual(self.text.count("authWebFor = base;"), 1)
        src = func_source(self.text, "relayHostBase")
        self.assertIn("authWebFor === authBase()", src)
        self.assertIn("!IS_WEB", src)
        # My room goes through relayHostBase (the Messages card's create / open / change, and the My room dialog)
        i = self.text.index("async function personalApi(body) {")
        self.assertIn("const base = relayHostBase() || chatBase();", self.text[i:i + 200])

    def test_table(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        src = func_source(self.text, "relayHostBase")
        self.assertTrue(src)
        js = "\n".join([
            "const cases = %s;" % json.dumps(CASES),
            "const out = [];",
            "for (const [origin, relay, web, webFor, isWeb] of cases) {",
            "  const u = new URL(origin);",
            "  const location = { origin: u.origin, hostname: u.hostname, port: u.port, protocol: u.protocol };",
            "  const urlInput = { value: relay };",
            "  const IS_WEB = isWeb, authWeb = web, authWebFor = webFor;",
            "  const isWebRelay = () => false;",
            "  const authBase = () => { const r = new URL(relay); return 'http://' + r.hostname + ':' + (Number(r.port || 443) + 1); };",
            "  const window = { __auth: { web: web, https: 8443 } };",
            "  out.push(eval('(' + %s + ')')());" % json.dumps(src.replace("function relayHostBase()", "function ()")),
            "}",
            "process.stdout.write(JSON.stringify(out));",
        ])
        r = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [c[5] for c in CASES])


if __name__ == "__main__":
    unittest.main()
