"""0.21.95 (Kenton, field, v0.21.94: "The audio is off a bit when sharing media. It is behind the video by about half a
second."). Two causes, both on the SHARER:
  1. The file's sound went element -> AudioContext -> a MediaStream track -> the library's capture, which stamps each block
     `zero + samples / rate` from a SECOND AudioContext that starts rendering 0.25-0.7 s after its zero. The viewer lines
     sound and picture up by those stamps, so the error went straight to every viewer (the 0.21.9 adaptive audio delay
     widens the delay of BOTH, so it cannot fix a skew). Now a worklet beside the element source hands the library
     timestamped SAMPLES on the element graph's own clock + the picture's measured delay (mediaAudioSource).
  2. Converted files (MSE): fmp4_start renamed every edts to 'free', losing the video's B-frame delay (67 ms) and the AAC
     priming (21 ms) -- the element itself played the picture ~46 ms late. Now each edit list becomes one entry.
Lab (headless Chrome, local relay, flash + 1 kHz beep every 2 s; + = sound late, ms, viewer median):
  plain H.264/AAC  -193 / -253 / -355 -> -7 / +36 / -43;  H.264+AC-3 mkv -356 -> +6 / 0;  HEVC+AC-3 mkv -314 -> +4;
  MPEG-4+MP3 avi -389 -> -47.  Camera + mic unchanged (its path is not touched)."""
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def box(typ, payload):
    return struct.pack(">I4s", 8 + len(payload), typ) + payload


def full(typ, ver, payload):
    return box(typ, struct.pack(">I", ver << 24) + payload)


def mdhd(ts):   # version 0: ctime, mtime, timescale, duration, lang, pre
    return full(b"mdhd", 0, struct.pack(">IIIIHH", 0, 0, ts, 0, 0, 0))


def elst(entries, ver=0):
    body = struct.pack(">I", len(entries))
    for sd, mt in entries:
        body += struct.pack(">QqhH", sd, mt, 1, 0) if ver == 1 else struct.pack(">IihH", sd, mt, 1, 0)
    return full(b"elst", ver, body)


def trak(ts, entries, ver=0):
    return box(b"trak", box(b"tkhd", b"\0" * 84) + box(b"edts", elst(entries, ver)) + box(b"mdia", mdhd(ts) + box(b"hdlr", b"\0" * 24)))


def moov(*traks, mvts=1000):
    mvhd = full(b"mvhd", 0, struct.pack(">IIII", 0, 0, mvts, 0) + b"\0" * 80)
    return box(b"ftyp", b"isom\0\0\0\0") + box(b"moov", mvhd + b"".join(traks))


def read_elsts(buf):
    """[(entry_count, [(seg, media_time)], has_free_in_edts)] per trak, in order"""
    out = []

    def walk(off, end):
        while off + 8 <= end:
            size, typ = struct.unpack(">I4s", buf[off:off + 8])
            yield typ, off + 8, off + size
            off += size

    for t, a, e in walk(0, len(buf)):
        if t != b"moov":
            continue
        for t2, a2, e2 in walk(a, e):
            if t2 != b"trak":
                continue
            for t3, a3, e3 in walk(a2, e2):
                if t3 != b"edts":
                    continue
                kinds = [t4 for t4, _a, _e in walk(a3, e3)]
                for t4, a4, e4 in walk(a3, e3):
                    if t4 == b"elst":
                        v, n = buf[a4], struct.unpack(">I", buf[a4 + 4:a4 + 8])[0]
                        ents, q = [], a4 + 8
                        for _ in range(n):
                            if v == 1:
                                sd, mt = struct.unpack(">Qq", buf[q:q + 16]); q += 20
                            else:
                                sd, mt = struct.unpack(">Ii", buf[q:q + 8]); q += 12
                            ents.append((sd, mt))
                        out.append((n, ents, b"free" in kinds))
    return out


class Fmp4EditLists(unittest.TestCase):
    def setUp(self):
        import kastr_serve
        self.f = kastr_serve.fmp4_start

    def test_no_seek_keeps_each_tracks_media_time(self):
        # what ffmpeg writes at t=0 for a copied H.264 (2 B-frames at 16000) + AAC (priming 1024 at 48000)
        buf = moov(trak(16000, [(4000, 1072)]), trak(48000, [(4000, 1024)]))
        start, out = self.f(buf)
        self.assertEqual(start, 0.0)
        self.assertEqual(len(out), len(buf))
        self.assertEqual([e[1] for e in read_elsts(out)], [[(4000, 1072)], [(4000, 1024)]])
        self.assertNotIn(b"free", out)   # 0.21.0 renamed the edts -> the delays were lost

    def test_seek_folds_the_empty_edit_into_one_entry(self):
        # after a seek to 5 s (empty edits 4.0 s / 3.9467 s in mvhd units 1000 -> 4000 / 3947)
        buf = moov(trak(16000, [(4000, -1), (3000, 1072)]), trak(48000, [(3947, -1), (3000, 0)]))
        start, out = self.f(buf)
        self.assertEqual(len(out), len(buf))   # same size: no re-layout of the head
        # S = max(4.0 - 1072/16000, 3.947 - 0) = 3.947
        self.assertAlmostEqual(start, 3.947, places=3)
        v, a = read_elsts(out)
        self.assertEqual(v[0], 1)
        self.assertEqual(a[0], 1)
        self.assertEqual(v[1], [(3000, round(1072 - (4.0 - 3.947) * 16000))])
        self.assertEqual(a[1], [(3000, 0)])
        self.assertTrue(v[2] and a[2])   # the dropped entry is a 'free' box inside edts

    def test_version1_elst(self):
        buf = moov(trak(16000, [(4000, -1), (3000, 1072)], ver=1), trak(48000, [(4000, -1), (3000, 1024)], ver=1))
        start, out = self.f(buf)
        self.assertAlmostEqual(start, 4.0 - 1024 / 48000.0, places=4)   # the audio's priming is the later start here
        v, a = read_elsts(out)
        self.assertEqual(v[1], [(3000, round(1072 - (4.0 - start) * 16000))])
        self.assertEqual(a[1], [(3000, 0)])

    def test_head_without_edit_list_is_untouched(self):
        buf = box(b"ftyp", b"isom\0\0\0\0") + box(b"moov", full(b"mvhd", 0, struct.pack(">IIII", 0, 0, 1000, 0) + b"\0" * 80))
        self.assertEqual(self.f(buf), (0.0, buf))
        self.assertEqual(self.f(b"\0\0\0\x09moov"), (0.0, b"\0\0\0\x09moov"))   # truncated: never raises


class MediaAudioClock(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "moq-watch-lite.html"), encoding="utf-8") as f:
            self.src = f.read()
        i = self.src.index("function mediaAudioSource(m, src)")
        self.fn = self.src[i:self.src.index("// 0.21.16: the file share's audio gap probe", i)]

    def test_samples_source_with_the_old_track_beside_it(self):
        self.assertIn("registerProcessor('kastr-media-clock'", self.src)
        self.assertIn('return { samples, sampleRate: rate, channelCount: 2, kind: "music", track: m.atrack };', self.fn)
        self.assertIn('new AudioData({ format: "f32-planar"', self.fn)
        # the plain track stays the fallback when the worklet cannot run
        self.assertIn('mediaAudioSource(m, src).then((s) => setAud(s || { track: atrack, kind: "music" }));', self.src)
        self.assertIn('else setAud({ track: atrack, kind: "music" });', self.src)

    def test_stamps_never_go_backward_or_gap(self):
        # a stamp below one already sent closes the viewer's audio track; a gap restarts the encoder and re-times the sound
        self.assertIn("if (want < k.next - MEDIA_ACLOCK_SLACK_MS) { k.trimmed++; return; }", self.fn)
        self.assertIn("put(k.next, z, C, null); k.next += blockMs(z); k.padded++; ts = k.next;", self.fn)
        self.assertIn("} else ts = k.next;", self.fn)
        self.assertIn("MEDIA_ACLOCK_PAD_MAX_MS = 1000", self.src)

    def test_warm_up_then_offset_and_lead(self):
        self.assertIn("if (now - k.t0 < MEDIA_ACLOCK_WARM_MS) return;", self.fn)
        self.assertIn("const want = startMs + k.off + k.lead", self.fn)
        # the picture's delay moves only after MEDIA_LEAD_MOVE_WINS seconds away (each move is a stamp change)
        self.assertIn("if (++k.leadAway >= MEDIA_LEAD_MOVE_WINS) { k.lead = L; k.leadAway = 0; }", self.fn)
        self.assertNotIn("__vlagDbg", self.src)   # lab-only debug is gone

    def test_picture_delay_is_measured_on_the_restamper(self):
        self.assertIn("vtrack.__tagIn = (arrMs, origUs) => mediaDrawOf(m, arrMs, origUs); vtrack.__tagOut = (shownAt, exitMs) => mediaVlagSample(m, shownAt, exitMs);", self.src)
        self.assertIn("if (gen.__tagIn) { try { value.__kastrTag = gen.__tagIn(nowMs, value.timestamp); } catch {} }", self.src)
        self.assertIn("if (gen.__tagOut && fr.__kastrTag !== undefined) { try { gen.__tagOut(fr.__kastrTag, ts / 1000); } catch {} }", self.src)
        self.assertIn("function mediaVlagSample(m, shownAt, exitMs)", self.src)
        self.assertIn("meta.expectedDisplayTime", self.src)

    def test_camera_and_mic_untouched(self):
        # calls keep their latency: only the media share goes through the worklet, the video is never held back
        self.assertEqual(self.src.count('kind: "voice" });'), 4)
        self.assertEqual(self.src.count("mediaAudioSource("), 2)   # its definition + the one call in the media wire()

    def test_debug_shows_the_clock(self):
        self.assertIn("aclock: m.aclock ? { off:", self.src)
        self.assertIn("vlag: m.vlag == null ? null", self.src)


if __name__ == "__main__":
    unittest.main()
