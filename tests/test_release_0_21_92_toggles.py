# -*- coding: utf-8 -*-
"""v0.21.92 TOGGLES, NOT CHECKBOXES (Kenton 2026-10-28: "the check box should be a toggle. This should always be this way for
all check boxes unless told differently"). Every on/off input KASTR's pages show -- static markup, markup built in JS strings,
and inputs made with createElement -- sits in the house switch: <span|label class="switch [sm]"><input type="checkbox"><i></i>.
The scan covers the root *.html pages, the root kastr*.py modules (inline pages) and assets/*.js. ALLOW stays empty unless
Kenton asks for a real checkbox somewhere (each entry: file, a snippet of the line, one-line reason)."""
import glob, os, re, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (file basename, a substring of the checkbox's line, reason) -- keep it EMPTY unless truly needed
ALLOW = []

MARKUP = re.compile(r"""<input\b[^<>]*?\btype\s*=\s*\\?["']?checkbox""", re.I)
PROP = re.compile(r"""\b([A-Za-z_$][\w$]*)\.type\s*=\s*["']checkbox["']""")
ATTR = re.compile(r"""\b([A-Za-z_$][\w$]*)\.setAttribute\(\s*["']type["']\s*,\s*["']checkbox["']""")
OBJ = re.compile(r"""\btype\s*:\s*["']checkbox["']""")
# the opening tag right before a switch's input (string concatenation between them is ignored)
OPENER = re.compile(r"""<(?:span|label)\b[^<>]*\bclass\s*=\s*\\?["'][^"'\\]*\bswitch\b[^<>]*>\s*$""", re.I)
CONCAT = re.compile(r"""\\?["']\s*\+\s*(?://[^\n]*\n\s*)?\\?["']""")
HELPERS = ("switchOf",)   # assets/kastr-pres.js: wraps an input in <span class="switch sm"> + <i>


def sources():
    out = sorted(glob.glob(os.path.join(HERE, "*.html")))
    out += sorted(p for p in glob.glob(os.path.join(HERE, "kastr*.py")))
    out += sorted(glob.glob(os.path.join(HERE, "assets", "*.js")))
    return out


def read(p):
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def line_of(text, i):
    a = text.rfind("\n", 0, i) + 1
    b = text.find("\n", i)
    return text[a:b if b >= 0 else len(text)]


def markup_ok(text, i):
    before = CONCAT.sub("", text[max(0, i - 400):i])
    return bool(OPENER.search(before))


def element_ok(text, i, var):
    """var = an input made in JS: it must go into a wrapper whose class is "switch ...", next to an <i> (or a switch helper)."""
    lo, hi = max(0, i - 2500), min(len(text), i + 2500)
    win = text[lo:hi]
    v = re.escape(var)
    if any(re.search(r"\b%s\(\s*%s\s*\)" % (h, v), win) for h in HELPERS):
        return True
    for m in re.finditer(r"\b([A-Za-z_$][\w$]*)\.append\(\s*%s\s*,\s*(?:document\.createElement|mkEl)\(\s*[\"']i[\"']\s*\)\s*\)" % v, win):
        w = re.escape(m.group(1))
        if re.search(r"\b%s\.className\s*=\s*[\"']switch\b" % w, win) or \
           re.search(r"\b%s\s*=\s*mkEl\(\s*[\"'](?:span|label)[\"']\s*,\s*[\"']switch\b" % w, win):
            return True
    return False


def bare_checkboxes(text):
    """[(offset, line)] of every checkbox input not inside a .switch wrapper."""
    bad = []
    for m in MARKUP.finditer(text):
        if not markup_ok(text, m.start()):
            bad.append((m.start(), line_of(text, m.start())))
    for rx in (PROP, ATTR):
        for m in rx.finditer(text):
            if not element_ok(text, m.start(), m.group(1)):
                bad.append((m.start(), line_of(text, m.start())))
    for m in OBJ.finditer(text):   # {type: "checkbox"} -- no such builder in KASTR; flag it so a new one is looked at
        bad.append((m.start(), line_of(text, m.start())))
    return bad


def allowed(path, line):
    return any(os.path.basename(path) == f and s in line for f, s, _ in ALLOW)


class TestTogglesNotCheckboxes(unittest.TestCase):
    def test_allowlist_has_reasons(self):
        for f, s, why in ALLOW:
            self.assertTrue(f and s and why.strip(), (f, s))

    def test_every_checkbox_is_a_switch(self):
        found, problems = 0, []
        for p in sources():
            t = read(p)
            found += len(MARKUP.findall(t)) + len(PROP.findall(t)) + len(ATTR.findall(t))
            for off, line in bare_checkboxes(t):
                if not allowed(p, line):
                    problems.append("%s:%d: %s" % (os.path.basename(p), t.count("\n", 0, off) + 1, line.strip()[:160]))
        self.assertGreater(found, 40, "the scan found almost no checkboxes -- is it looking in the right place?")
        self.assertEqual(problems, [], "bare checkboxes (wrap each in <span class=\"switch sm\"><input type=\"checkbox\"><i></i></span>):\n"
                         + "\n".join(problems))

    def test_scanner_catches_bare_ones(self):
        self.assertTrue(bare_checkboxes('<label><input type="checkbox" id="x"> Hi</label>'))
        self.assertTrue(bare_checkboxes("h += '<label><input type=\\'checkbox\\'> Hi</label>';"))
        self.assertTrue(bare_checkboxes('const cb = document.createElement("input"); cb.type = "checkbox"; lab.append(cb, "Hi");'))
        self.assertTrue(bare_checkboxes('const cb = el("input"); cb.setAttribute("type", "checkbox"); row.appendChild(cb);'))
        self.assertFalse(bare_checkboxes('<label class="asi-sw"><span class="switch sm"><input type="checkbox" id="x"><i></i></span><span>Hi</span></label>'))
        self.assertFalse(bare_checkboxes("x = '<label class=\"switch sm\">' +\n  '<input type=\"checkbox\"><i></i></label>';"))
        self.assertFalse(bare_checkboxes('const sw = document.createElement("span"); sw.className = "switch sm";\n'
                                         'const cb = document.createElement("input"); cb.type = "checkbox"; sw.append(cb, document.createElement("i"));'))
        self.assertFalse(bare_checkboxes('const s = mkEl("span", "switch sm"); const si = mkEl("input"); si.type = "checkbox"; s.append(si, mkEl("i"));'))
        self.assertFalse(bare_checkboxes('row.querySelector("input[type=checkbox]")'))   # a selector, not an input

    def test_pages_with_switches_have_the_css(self):
        css = read(os.path.join(HERE, "assets", "asi-brand.css"))
        for rule in (".switch {", ".switch input {", ".switch i {", ".switch input:checked + i", ".switch.sm {", ".switch input:focus-visible + i"):
            self.assertIn(rule, css)
        for p in sorted(glob.glob(os.path.join(HERE, "*.html"))):
            t = read(p)
            if re.search(r"""class\s*=\s*\\?["'][^"']*\bswitch\b""", t):
                self.assertTrue("/assets/asi-brand.css" in t or ".switch {" in t, os.path.basename(p) + " shows switches without their CSS")

    def test_0_21_92_conversions(self):
        t = read(os.path.join(HERE, "moq-watch-lite.html"))
        # the streams x rooms table: a LABEL.switch per cell (no row label around it, so a span would not toggle)
        self.assertIn('const sw = document.createElement("label"); sw.className = "switch sm";', t)
        self.assertIn("td.appendChild(sw); tr.appendChild(td);", t)
        self.assertNotIn(".xstab input {", t)
        # My room people: Can arrange
        self.assertIn('lab.append(csw, document.createTextNode("Can arrange"));', t)
        # the grid editor's Share with this room
        self.assertIn('sl.append(ssw, o.share.label || "Share with this room");', t)


if __name__ == "__main__":
    unittest.main()
