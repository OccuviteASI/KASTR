"""0.21.15: every brand `.switch` in the pages must live inside a <label>.

assets/asi-brand.css hides a switch's <input> (opacity 0, 0x0 -- `.switch input`); only a <label>'s activation
behaviour forwards a click on the <i> face to it. 0.21.0 rendered the Share-content row's On-air switch as a
<span class="switch sm"> with no label around it and the row could never be unchecked by mouse (Part 39 item 1,
moq-watch-lite.html renderSources). This guard reads both pages as text -- plain HTML, HTML strings inside JS, and
switches built with document.createElement -- and names every switch that has no <label> open around it.

Run: python -m unittest discover -s tests   (build.py runs it before every build)
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ("moq-watch-lite.html", "relay.html")
SWITCH_MARKUP = re.compile(r'<(\w+) class="switch')          # HTML, or an HTML string inside JS (innerHTML / template)
SWITCH_JS = re.compile(r'className\s*=\s*"switch')           # a switch built with createElement + className
WINDOW = 4                                                   # lines above the switch that may hold its <label>


def unlabelled_switches(text, name):
    """Every switch in `text` (one page) with no <label> open just before it: 'name:line: text' per offender.

    Wrapped means: a `<label` is still open in the window (the WINDOW lines above plus the same line up to the switch)
    -- the last `<label` comes after the last `</label>` -- or the enclosing element was built with
    document.createElement("label") in that window. A `<label class="switch">` is a label itself."""
    lines = text.split("\n")
    bad = []
    for i, line in enumerate(lines):
        hits = [m for m in SWITCH_MARKUP.finditer(line) if m.group(1) != "label"]
        hits += list(SWITCH_JS.finditer(line))
        for m in hits:
            window = "\n".join(lines[max(0, i - WINDOW):i]) + "\n" + line[:m.start()]
            if window.rfind("<label") > window.rfind("</label>") or 'createElement("label")' in window:
                continue
            bad.append("%s:%d: %s" % (name, i + 1, line.strip()[:120]))
    return bad


class SwitchesAreLabels(unittest.TestCase):
    def check(self, name):
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('class="switch', text, name + " carries no switches at all -- the markup moved?")
        bad = unlabelled_switches(text, name)
        self.assertEqual(bad, [], "switches outside a <label> (unclickable: asi-brand.css hides the input):\n" + "\n".join(bad))

    def test_watch_page(self):
        self.check("moq-watch-lite.html")

    def test_relay_page(self):
        self.check("relay.html")


class RuleItself(unittest.TestCase):
    """The rule on synthetic snippets, so a change to the rule is caught before it is run over the pages."""

    def test_flags_the_0_21_0_span(self):
        text = ('row.innerHTML =\n'
                '  \'<div class="top"><span class="switch sm" title="On air"><input type="checkbox"><i></i></span>\' +\n')
        self.assertEqual(len(unlabelled_switches(text, "p")), 1)

    def test_accepts_the_label_fix(self):
        text = ('row.innerHTML =\n'
                '  \'<div class="top"><label class="switch sm" title="On air"><input type="checkbox"><i></i></label>\' +\n'
                '  \'<label class="aud"><span class="switch sm"><input type="checkbox"><i></i></span> <span>Audio</span></label>\' +\n')
        self.assertEqual(unlabelled_switches(text, "p"), [])

    def test_accepts_a_label_opened_on_a_previous_line(self):
        text = ('<label class="f" id="a"><input type="text"></label>\n'
                '<label class="f asi-sw" id="joinKeepRow" hidden>\n'
                '  <span class="switch sm"><input type="checkbox" id="joinKeep"><i></i></span><span>Keep</span>\n'
                '</label>\n')
        self.assertEqual(unlabelled_switches(text, "p"), [])

    def test_a_closed_label_does_not_cover_the_next_switch(self):
        text = ('<label class="f asi-sw"><span class="switch"><input type="checkbox"><i></i></span><span>x</span></label>\n'
                '<div><span class="switch"><input type="checkbox"><i></i></span></div>\n')
        self.assertEqual(len(unlabelled_switches(text, "p")), 1)

    def test_js_built_switch_inside_a_created_label(self):
        text = ('const keepRow = document.createElement("label");\n'
                'keepRow.className = "pwkeep";\n'
                'const keepInp = document.createElement("input");\n'
                'const keepSw = document.createElement("span"); keepSw.className = "switch sm";\n')
        self.assertEqual(unlabelled_switches(text, "p"), [])

    def test_js_built_switch_inside_a_created_span_is_flagged(self):
        text = ('const wrap = document.createElement("span");\n'
                'const sw = document.createElement("span"); sw.className = "switch sm";\n')
        self.assertEqual(len(unlabelled_switches(text, "p")), 1)


if __name__ == "__main__":
    unittest.main()
