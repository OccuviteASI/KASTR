"""0.21.52 (field, Mendon: a camera's ffmpeg exited every 10.5 s with code 183 and the log line showed the moq tool's
message): the exit line names the exiting process's own reason; common ffmpeg codes are said in words."""
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import kastr_rtsp as kr  # noqa: E402


class ExitReason(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(kr.ffmpeg_exit_reason(183), "invalid data from the camera")          # Linux: low byte
        self.assertEqual(kr.ffmpeg_exit_reason(3199971767), "invalid data from the camera")   # Windows: 32 bits
        self.assertEqual(kr.ffmpeg_exit_reason(146), "the camera timed out")
        self.assertEqual(kr.ffmpeg_exit_reason(1), "")
        self.assertEqual(kr.ffmpeg_exit_reason(None), "")

    def test_exit_line_prefers_the_exiting_process(self):
        src = open(os.path.join(ROOT, "kastr_rtsp.py"), encoding="utf-8").read()
        self.assertIn('mine = [e for e in self.errors if e.startswith(who + ":")]', src)
        self.assertIn('self.lastExit["reason"] = why', src)


if __name__ == "__main__":
    unittest.main()
