"""0.21.40: More > Deafen -- all incoming sound off and my mic muted in one switch.

Run: python -m unittest discover -s tests
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _page():
    with open(os.path.join(ROOT, "moq-watch-lite.html"), encoding="utf-8") as f:
        return f.read()


class Deafen(unittest.TestCase):
    def test_in_the_more_menu_and_on_d(self):
        p = _page()
        self.assertIn('<button class="opt" id="optDeafen" type="button"', p)
        more = p[p.index('<div id="optPop"'):p.index('<div id="optPop"') + 3000]
        self.assertIn('id="optDeafen"', more)
        self.assertIn('else if (e.key === "d" || e.key === "D") { setDeafen(!deafened); }', p)
        self.assertIn("<kbd>D</kbd>", p)

    def test_mutes_sound_and_mic_and_restores_only_a_mic_that_was_on(self):
        p = _page()
        body = p[p.index("  function setDeafen(on) {"):p.index("  window.__deafen = ")]
        self.assertIn("deafMicWas = src ? !src.micMuted : joinMicOn;", body)
        self.assertIn("manualMute = true;", body)
        self.assertIn("if (src) setMic(true);", body)
        self.assertIn("if (deafMicWas) { if (src) setMic(false);", body)

    def test_unmuting_the_mic_or_sound_ends_it(self):
        p = _page()
        self.assertIn("if (deafened) { const wasOn = deafMicWas; setDeafen(false); if (wasOn) return; }", p)
        self.assertIn("if (deafened && !manualMute) { deafened = false; deafMicWas = null; try { window.__state?.set?.(\"deaf\", false); }", p)


    def test_the_room_sees_it(self):
        p = _page()
        self.assertIn('try { window.__state?.set?.("deaf", deafened); } catch {}', p)
        self.assertIn('case "deaf": if (value) pubModel.deaf = 1; else delete pubModel.deaf; break;', p)
        self.assertIn("deaf: v.deaf === 1 } });", p)
        self.assertIn('t.pane.classList.toggle("deaf", df)', p)
        self.assertIn('if (p.deaf) { mic.innerHTML = icon("earOff");', p)
        self.assertIn("#stage .pane.deaf .mchip .earOff, #stage .pubpane.deaf .mchip .earOff { display:block; }", p)


if __name__ == "__main__":
    unittest.main()
