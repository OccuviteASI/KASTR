"""0.21.91: the KASTR web server queues enough connections for a page's burst of ~50 file loads (socketserver's default of 5
refused some of them in labs)."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ListenQueue(unittest.TestCase):
    def test_queue_size(self):
        with open(os.path.join(ROOT, "kastr_serve.py"), encoding="utf-8") as f:
            s = f.read()
        i = s.index("class _Server(ThreadingHTTPServer):")
        self.assertIn("request_queue_size = 128", s[i:i + 400])


if __name__ == "__main__":
    unittest.main()
