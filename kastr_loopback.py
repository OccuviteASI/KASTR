"""System-audio capture for KASTR "Include sound" -- pure ctypes, no dependency.

Windows 10 2004+ (build 19041+) PROCESS LOOPBACK: activate the virtual device
"VAD\\Process_Loopback" with AUDIOCLIENT_ACTIVATION_PARAMS in
PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE so everything the machine
plays is captured EXCEPT the given process and its descendants (KASTR's own
browser tree -> no echo of the other participants).

  python loopback.py --seconds 3 --exclude-pid 1234 --out test.wav
  python loopback.py --exclude-pid 1234 --stdout | ffmpeg -f s16le -ar 48000 -ac 2 -i pipe:0 ...
  python loopback.py --exclude-pid 1234 --tcp 47000      (ffmpeg -i tcp://127.0.0.1:47000)
  python loopback.py --endpoint ...                     (plain endpoint loopback, for comparison)
  python loopback.py --include-pid 1234 ...             (only that process tree)

Output is raw interleaved PCM, 48 kHz stereo, s16le (default) or f32le
(--format f32). The stream is CONTINUOUS: when the system is silent WASAPI
delivers no packets, so the writer pads with zeros on the wall clock and drops
samples if it ever runs ahead -- ffmpeg sees a steady real-time stream.

Library use (what KASTR would import):
    cap = LoopbackCapture(exclude_pid=os.getpid())
    cap.start(sink=lambda pcm_bytes: proc.stdin.write(pcm_bytes))
    ...
    cap.stop()
"""
import argparse
import ctypes
import math
import os
import socket
import struct
import sys
import threading
import time
import uuid
from array import array
from ctypes import (POINTER, WINFUNCTYPE, Structure, byref, c_int, c_long,
                    c_longlong, c_ubyte, c_uint, c_uint32, c_uint64, c_ulong,
                    c_ushort, c_void_p, c_wchar_p)
from ctypes import wintypes as wt

if sys.platform != "win32":
    raise SystemExit("loopback.py: Windows only")

ole32 = ctypes.OleDLL("ole32")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
HRESULT = ctypes.HRESULT  # restype that raises OSError on failure codes

# ---------------------------------------------------------------- constants
S_OK = 0
E_NOINTERFACE = c_long(0x80004002).value
CLSCTX_ALL = 0x17
COINIT_MULTITHREADED = 0x0
RPC_E_CHANGED_MODE = c_long(0x80010106).value

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY = 0x1
AUDCLNT_BUFFERFLAGS_SILENT = 0x2

AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE = 1
VT_BLOB = 65
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"

WAVE_FORMAT_PCM = 1
WAVE_FORMAT_IEEE_FLOAT = 3
WAIT_OBJECT_0 = 0
eRender, eConsole = 0, 0


class GUID(Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", c_ubyte * 8)]


def guid(s):
    return GUID.from_buffer_copy(uuid.UUID(s).bytes_le)


IID_IUnknown = guid("00000000-0000-0000-C000-000000000046")
IID_IAgileObject = guid("94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90")
IID_IActivateAudioInterfaceCompletionHandler = guid("41D949AB-9862-444A-80F6-C261334DA5EB")
IID_IAudioClient = guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2")
IID_IAudioCaptureClient = guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317")
CLSID_MMDeviceEnumerator = guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = guid("A95664D2-9614-4F35-A746-DE8DB63617E6")


class WAVEFORMATEX(Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", wt.WORD), ("nChannels", wt.WORD),
                ("nSamplesPerSec", wt.DWORD), ("nAvgBytesPerSec", wt.DWORD),
                ("nBlockAlign", wt.WORD), ("wBitsPerSample", wt.WORD),
                ("cbSize", wt.WORD)]


class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(Structure):
    _fields_ = [("TargetProcessId", wt.DWORD), ("ProcessLoopbackMode", c_int)]


class AUDIOCLIENT_ACTIVATION_PARAMS(Structure):
    _fields_ = [("ActivationType", c_int),
                ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS)]


class BLOB(Structure):
    _fields_ = [("cbSize", c_ulong), ("pBlobData", c_void_p)]


class PROPVARIANT(Structure):  # only the VT_BLOB arm is needed (24 bytes on x64)
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort),
                ("r3", c_ushort), ("blob", BLOB)]


# ------------------------------------------------------- tiny COM helpers
def vcall(ptr, index, *argtypes):
    """Return a bound callable for vtable slot `index` of COM pointer `ptr`."""
    vtbl = ctypes.cast(c_void_p(ptr), POINTER(POINTER(c_void_p))).contents
    fn = WINFUNCTYPE(HRESULT, c_void_p, *argtypes)(vtbl[index])
    return lambda *a: fn(ptr, *a)


def com_release(ptr):
    if ptr:
        vtbl = ctypes.cast(c_void_p(ptr), POINTER(POINTER(c_void_p))).contents
        WINFUNCTYPE(c_ulong, c_void_p)(vtbl[2])(ptr)


def com_qi(ptr, iid):
    out = c_void_p()
    vcall(ptr, 0, POINTER(GUID), POINTER(c_void_p))(byref(iid), byref(out))
    return out.value


def _guid_eq(a, b):
    return bytes(a) == bytes(b)


# IActivateAudioInterfaceCompletionHandler implemented in ctypes. It must be
# agile (IAgileObject) -- ActivateCompleted arrives on an MTA worker thread.
_QI = WINFUNCTYPE(c_long, c_void_p, POINTER(GUID), POINTER(c_void_p))
_ADDREF = WINFUNCTYPE(c_ulong, c_void_p)
_RELEASE = WINFUNCTYPE(c_ulong, c_void_p)
_COMPLETED = WINFUNCTYPE(c_long, c_void_p, c_void_p)


class _HandlerVtbl(Structure):
    _fields_ = [("QueryInterface", _QI), ("AddRef", _ADDREF),
                ("Release", _RELEASE), ("ActivateCompleted", _COMPLETED)]


class _HandlerObj(Structure):
    _fields_ = [("lpVtbl", POINTER(_HandlerVtbl))]


_KEEPALIVE = []  # handlers live for the process (COM may Release late)


class _CompletionHandler:
    def __init__(self):
        self.done = threading.Event()
        self.hr = None
        self.unk = None
        self._refs = 1

        def qi(this, riid, ppv):
            r = riid.contents
            if (_guid_eq(r, IID_IUnknown) or _guid_eq(r, IID_IAgileObject)
                    or _guid_eq(r, IID_IActivateAudioInterfaceCompletionHandler)):
                ppv[0] = this
                self._refs += 1
                return S_OK
            ppv[0] = None
            return E_NOINTERFACE

        def addref(this):
            self._refs += 1
            return self._refs

        def release(this):
            self._refs -= 1
            return max(self._refs, 1)  # memory is owned by Python (_KEEPALIVE)

        def completed(this, op):
            try:
                hr = c_long()
                unk = c_void_p()
                # IActivateAudioInterfaceAsyncOperation::GetActivateResult = slot 3
                vtbl = ctypes.cast(c_void_p(op), POINTER(POINTER(c_void_p))).contents
                WINFUNCTYPE(c_long, c_void_p, POINTER(c_long), POINTER(c_void_p))(
                    vtbl[3])(op, byref(hr), byref(unk))
                self.hr, self.unk = hr.value, unk.value
            except Exception as e:  # never let an exception cross the COM boundary
                self.hr = -1
                self.err = e
            finally:
                self.done.set()
            return S_OK

        self._fns = (_QI(qi), _ADDREF(addref), _RELEASE(release), _COMPLETED(completed))
        self.vtbl = _HandlerVtbl(*self._fns)
        self.obj = _HandlerObj(ctypes.pointer(self.vtbl))
        _KEEPALIVE.append(self)

    @property
    def ptr(self):
        return ctypes.addressof(self.obj)


def _co_init():
    try:
        ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    except OSError as e:
        if e.winerror != RPC_E_CHANGED_MODE:
            raise


def activate_process_loopback(pid, exclude=True, timeout=5.0):
    """Return an IAudioClient pointer on the process-loopback virtual device."""
    mmdevapi = ctypes.OleDLL("mmdevapi")
    fn = mmdevapi.ActivateAudioInterfaceAsync
    fn.argtypes = [c_wchar_p, POINTER(GUID), POINTER(PROPVARIANT), c_void_p, POINTER(c_void_p)]
    params = AUDIOCLIENT_ACTIVATION_PARAMS(
        AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK,
        AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(
            pid, PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE if exclude
            else PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE))
    pv = PROPVARIANT()
    pv.vt = VT_BLOB
    pv.blob.cbSize = ctypes.sizeof(params)
    pv.blob.pBlobData = ctypes.addressof(params)
    handler = _CompletionHandler()
    op = c_void_p()
    try:
        fn(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, byref(IID_IAudioClient), byref(pv),
           handler.ptr, byref(op))
    except AttributeError:
        raise RuntimeError("ActivateAudioInterfaceAsync missing (needs Windows 10 2004+)")
    if not handler.done.wait(timeout):
        raise RuntimeError("process-loopback activation timed out")
    com_release(op.value)
    if handler.hr != 0 or not handler.unk:
        raise OSError(handler.hr, "process-loopback activation failed hr=0x%08X"
                      % (handler.hr & 0xFFFFFFFF))
    client = com_qi(handler.unk, IID_IAudioClient)
    com_release(handler.unk)
    return client


def activate_endpoint_loopback():
    """Return an IAudioClient pointer on the default render endpoint."""
    enum = c_void_p()
    ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                           byref(IID_IMMDeviceEnumerator), byref(enum))
    dev = c_void_p()
    # IMMDeviceEnumerator::GetDefaultAudioEndpoint = slot 4
    vcall(enum.value, 4, c_int, c_int, POINTER(c_void_p))(eRender, eConsole, byref(dev))
    client = c_void_p()
    # IMMDevice::Activate = slot 3
    vcall(dev.value, 3, POINTER(GUID), wt.DWORD, c_void_p, POINTER(c_void_p))(
        byref(IID_IAudioClient), CLSCTX_ALL, None, byref(client))
    com_release(dev.value)
    com_release(enum.value)
    return client.value


# ------------------------------------------------------------- the capture
class LoopbackCapture:
    """Capture system audio as continuous interleaved PCM.

    exclude_pid  -> process loopback, everything EXCEPT that process tree
    include_pid  -> process loopback, ONLY that process tree
    neither      -> endpoint loopback of the default render device (echo-prone)
    """

    def __init__(self, exclude_pid=None, include_pid=None, rate=48000, channels=2,
                 fmt="s16", buffer_ms=20, pad=True):
        self.exclude_pid, self.include_pid = exclude_pid, include_pid
        self.rate, self.channels, self.fmt = rate, channels, fmt
        self.bits = 16 if fmt == "s16" else 32
        self.block = channels * self.bits // 8
        self.buffer_ms, self.pad = buffer_ms, pad
        self._thread = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self.error = None
        self.stats = dict(packets=0, frames=0, silent_packets=0, discontinuities=0,
                          padded_frames=0, dropped_frames=0, lat_sum=0.0, lat_max=0.0,
                          lat_n=0, buffer_frames=0, mode="")

    def _mode(self):
        if self.exclude_pid is not None:
            return "process-exclude"
        if self.include_pid is not None:
            return "process-include"
        return "endpoint"

    def start(self, sink):
        self.sink = sink
        self._thread = threading.Thread(target=self._run, name="loopback", daemon=True)
        self._thread.start()
        self._ready.wait(6)
        if self.error:
            raise self.error

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(3)

    def _run(self):
        client = cap = evt = None
        try:
            _co_init()
            mode = self.stats["mode"] = self._mode()
            if mode == "process-exclude":
                client = activate_process_loopback(self.exclude_pid, exclude=True)
            elif mode == "process-include":
                client = activate_process_loopback(self.include_pid, exclude=False)
            else:
                client = activate_endpoint_loopback()
            wfx = WAVEFORMATEX(
                WAVE_FORMAT_PCM if self.fmt == "s16" else WAVE_FORMAT_IEEE_FLOAT,
                self.channels, self.rate, self.rate * self.block, self.block, self.bits, 0)
            flags = (AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
                     | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
                     | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY)
            # IAudioClient: 3 Initialize, 4 GetBufferSize, 10 Start, 11 Stop,
            #               13 SetEventHandle, 14 GetService
            vcall(client, 3, c_int, wt.DWORD, c_longlong, c_longlong,
                  POINTER(WAVEFORMATEX), c_void_p)(
                AUDCLNT_SHAREMODE_SHARED, flags, self.buffer_ms * 10000, 0, byref(wfx), None)
            nbuf = c_uint32()
            vcall(client, 4, POINTER(c_uint32))(byref(nbuf))
            self.stats["buffer_frames"] = nbuf.value
            evt = kernel32.CreateEventW(None, False, False, None)
            vcall(client, 13, wt.HANDLE)(evt)
            capp = c_void_p()
            vcall(client, 14, POINTER(GUID), POINTER(c_void_p))(
                byref(IID_IAudioCaptureClient), byref(capp))
            cap = capp.value
            get_next = vcall(cap, 5, POINTER(c_uint32))
            get_buf = vcall(cap, 3, POINTER(c_void_p), POINTER(c_uint32), POINTER(wt.DWORD),
                            POINTER(c_uint64), POINTER(c_uint64))
            rel_buf = vcall(cap, 4, c_uint32)
            vcall(client, 10)()
        except Exception as e:  # report to start()
            self.error = e
            self._ready.set()
            self._cleanup(client, cap, evt)
            return
        self._ready.set()

        qpf = wt.LARGE_INTEGER()
        kernel32.QueryPerformanceFrequency(byref(qpf))
        qpc = wt.LARGE_INTEGER()
        n = c_uint32()
        data = c_void_p()
        frames = c_uint32()
        bflags = wt.DWORD()
        devpos = c_uint64()
        qpcpos = c_uint64()
        st = self.stats
        t0 = time.perf_counter()
        out_frames = 0
        lead = int(self.rate * 0.010)      # keep pads 10 ms behind the clock
        pad_after = int(self.rate * 0.030)  # pad only when >30 ms behind
        drop_after = int(self.rate * 0.150)  # drop when >150 ms ahead
        try:
            while not self._stop.is_set():
                kernel32.WaitForSingleObject(evt, 20)
                while True:
                    get_next(byref(n))
                    if n.value == 0:
                        break
                    get_buf(byref(data), byref(frames), byref(bflags), byref(devpos),
                            byref(qpcpos))
                    f = frames.value
                    if bflags.value & AUDCLNT_BUFFERFLAGS_SILENT:
                        chunk = bytes(f * self.block)
                        st["silent_packets"] += 1
                    else:
                        chunk = ctypes.string_at(data, f * self.block)
                    if bflags.value & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY:
                        st["discontinuities"] += 1
                    rel_buf(f)
                    if qpcpos.value:
                        kernel32.QueryPerformanceCounter(byref(qpc))
                        now100 = qpc.value * 10_000_000 // qpf.value
                        lat = (now100 - qpcpos.value) / 10_000.0  # ms
                        if 0 <= lat < 5000:
                            st["lat_sum"] += lat
                            st["lat_n"] += 1
                            st["lat_max"] = max(st["lat_max"], lat)
                    st["packets"] += 1
                    st["frames"] += f
                    if self.pad:
                        expected = int((time.perf_counter() - t0) * self.rate)
                        ahead = out_frames + f - expected
                        if ahead > drop_after:  # clock says we are ahead: trim
                            cut = min(f, ahead - drop_after // 2)
                            chunk = chunk[cut * self.block:]
                            st["dropped_frames"] += cut
                            f -= cut
                    if f:
                        self.sink(chunk)
                        out_frames += f
                if self.pad:
                    expected = int((time.perf_counter() - t0) * self.rate)
                    behind = expected - out_frames
                    if behind > pad_after:
                        z = behind - lead
                        self.sink(bytes(z * self.block))
                        out_frames += z
                        st["padded_frames"] += z
        except (BrokenPipeError, ConnectionError, OSError) as e:
            if not self._stop.is_set():
                self.error = e
        finally:
            try:
                vcall(client, 11)()
            except OSError:
                pass
            self._cleanup(client, cap, evt)

    @staticmethod
    def _cleanup(client, cap, evt):
        com_release(cap)
        com_release(client)
        if evt:
            kernel32.CloseHandle(evt)


# ------------------------------------------------------------------- CLI
def wav_header(nbytes, rate, ch, bits, flt):
    tag = WAVE_FORMAT_IEEE_FLOAT if flt else WAVE_FORMAT_PCM
    block = ch * bits // 8
    return (b"RIFF" + struct.pack("<I", 36 + nbytes) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, tag, ch, rate, rate * block, block, bits)
            + b"data" + struct.pack("<I", nbytes))


def rms_dbfs(pcm, fmt):
    a = array("h" if fmt == "s16" else "f")
    a.frombytes(pcm[: len(pcm) - len(pcm) % a.itemsize])
    if not a:
        return float("-inf"), 0.0
    full = 32768.0 if fmt == "s16" else 1.0
    s = math.fsum(x * x for x in a) / len(a)
    peak = max(abs(x) for x in a) / full
    r = math.sqrt(s) / full
    return (20 * math.log10(r) if r > 0 else float("-inf")), peak


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--exclude-pid", type=int, help="capture all audio except this process tree")
    g.add_argument("--include-pid", type=int, help="capture only this process tree")
    g.add_argument("--endpoint", action="store_true", help="plain default-endpoint loopback")
    ap.add_argument("--seconds", type=float, default=0, help="stop after N s (0 = until killed)")
    ap.add_argument("--format", choices=("s16", "f32"), default="s16")
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--channels", type=int, default=2)
    ap.add_argument("--buffer-ms", type=int, default=20)
    ap.add_argument("--no-pad", action="store_true", help="do not pad silence on the clock")
    o = ap.add_mutually_exclusive_group()
    o.add_argument("--out", help="write a WAV file")
    o.add_argument("--stdout", action="store_true", help="raw PCM to stdout")
    o.add_argument("--tcp", type=int, metavar="PORT", help="serve raw PCM on 127.0.0.1:PORT")
    ap.add_argument("--stats", action="store_true", help="print stats + RMS to stderr")
    a = ap.parse_args()
    if not (a.exclude_pid or a.include_pid or a.endpoint):
        a.exclude_pid = os.getpid()  # sensible default: everything but ourselves

    cap = LoopbackCapture(exclude_pid=a.exclude_pid, include_pid=a.include_pid,
                          rate=a.rate, channels=a.channels, fmt=a.format,
                          buffer_ms=a.buffer_ms, pad=not a.no_pad)
    collected = bytearray()
    conn = None
    if a.stdout:
        out = sys.stdout.buffer
        def sink(b):
            out.write(b)
            out.flush()
    elif a.tcp:
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", a.tcp))
        srv.listen(1)
        print("loopback: waiting for a reader on tcp://127.0.0.1:%d" % a.tcp, file=sys.stderr)
        conn, _ = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sink = conn.sendall
    else:
        sink = collected.extend

    c0, w0 = time.process_time(), time.perf_counter()
    cap.start(sink)
    try:
        while cap._thread.is_alive():
            if a.seconds and time.perf_counter() - w0 >= a.seconds:
                break
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    cap.stop()
    wall, cpu = time.perf_counter() - w0, time.process_time() - c0
    if conn:
        conn.close()
    if a.out:
        with open(a.out, "wb") as f:
            f.write(wav_header(len(collected), a.rate, a.channels, cap.bits, a.format == "f32"))
            f.write(collected)
    if a.stats or a.out:
        st = cap.stats
        lat = st["lat_sum"] / st["lat_n"] if st["lat_n"] else float("nan")
        msg = ("loopback: mode=%s wall=%.2fs cpu=%.1f%% buffer=%d frames packets=%d "
               "frames=%d silent=%d disc=%d padded=%d dropped=%d api_latency avg=%.1fms max=%.1fms"
               % (st["mode"], wall, 100 * cpu / wall, st["buffer_frames"], st["packets"],
                  st["frames"], st["silent_packets"], st["discontinuities"],
                  st["padded_frames"], st["dropped_frames"], lat, st["lat_max"]))
        if collected:
            db, peak = rms_dbfs(bytes(collected), a.format)
            msg += " rms=%.1fdBFS peak=%.4f bytes=%d" % (db, peak, len(collected))
        print(msg, file=sys.stderr)
    if cap.error and (a.stdout or a.tcp) and (
            isinstance(cap.error, ConnectionError)
            or (isinstance(cap.error, OSError) and getattr(cap.error, "winerror", None) is None)):
        print("loopback: reader closed", file=sys.stderr)  # normal end of a stream
        sys.stderr.flush()
        os._exit(0)  # skip the interpreter's flush of a dead stdout pipe
    elif cap.error:
        print("loopback: error: %r" % (cap.error,), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
