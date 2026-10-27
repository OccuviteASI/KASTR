"""0.21.91 (Kenton: "The KASTR window isn't starting as maximized, just as expanded most of the way"): the page's size guess
missed a maximized window at 200 % scale; on Windows the server asks the window itself (IsZoomed) before saving."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import kastr_serve  # noqa: E402


class WindowZoomed(unittest.TestCase):
    def test_bad_input_is_not_maximized(self):
        self.assertFalse(kastr_serve.native_kastr_zoomed(None))
        self.assertFalse(kastr_serve.native_kastr_zoomed({"w": 0, "h": 0}) and sys.platform != "win32")

    def test_wired_into_the_save(self):
        with open(os.path.join(ROOT, "kastr_serve.py"), encoding="utf-8") as f:
            s = f.read()
        self.assertIn('if geom.get("maximized") is not True and native_kastr_zoomed(geom):', s)
        self.assertIn('geom["maximized"] = True', s)
        i = s.index("def native_kastr_zoomed(geom):")
        body = s[i:i + 2600]
        for need in ("u.IsZoomed(h)", 'cls.value.startswith("Chrome_WidgetWin")', '"KASTR" not in t.value', "GetDpiForWindow(h)",
                     "<= 40"):
            self.assertIn(need, body)


if __name__ == "__main__":
    unittest.main()
