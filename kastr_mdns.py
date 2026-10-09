"""mDNS / DNS-SD discovery of KASTR relays on the local network (0.21.22).

A KASTR whose relay is reachable from other machines ADVERTISES it as a `_kastr._tcp.local` service -- discovery data
only: a display name, the web and relay ports, whether access codes are required, the relay's certificate fingerprint
and the KASTR version. No code, token or secret is ever in it (joining still needs the relay's access codes), and it
never joins relays to each other (the old relay LAN mesh was removed in 0.21.40).

A KASTR whose saved relay is offline BROWSES for it (a 1-2 s query). The page decides what to do with the answers:
it switches on its own only to a relay this machine used before whose certificate still matches; anything new is a
one-click suggestion -- a box on the network can advertise anything, so a stranger is never joined automatically.

Standard library only (RFC 6762 / 6763): one responder socket on UDP 5353 (SO_REUSEADDR, shared with Windows' and
moq-relay's own mDNS) joined on every IPv4 interface; browsing uses an ephemeral port, so responders answer it by
unicast (the "legacy" query of RFC 6762 6.7) -- no 5353 bind is needed to discover.
"""
import socket
import struct
import threading
import time

GROUP, PORT = "224.0.0.251", 5353
SERVICE = "_kastr._tcp.local"
TTL = 120
T_A, T_PTR, T_TXT, T_SRV, T_ANY = 1, 12, 16, 33, 255
CLASS_IN, FLUSH = 1, 0x8000


# ---- wire format --------------------------------------------------------------------------------------------------
def _enc_name(name):
    out = b""
    for label in name.strip(".").split("."):
        b = label.encode("utf-8")[:63]
        out += bytes([len(b)]) + b
    return out + b"\x00"


def _dec_name(buf, off, depth=0):
    labels = []
    end = None
    while True:
        if off >= len(buf) or depth > 20:
            raise ValueError("bad name")
        n = buf[off]
        if n == 0:
            off += 1
            break
        if n & 0xC0 == 0xC0:   # compression pointer
            ptr = struct.unpack("!H", buf[off:off + 2])[0] & 0x3FFF
            if end is None:
                end = off + 2
            name, _ = _dec_name(buf, ptr, depth + 1)
            labels.append(name)
            off = end
            return ".".join(x for x in labels if x), end
        labels.append(buf[off + 1:off + 1 + n].decode("utf-8", "replace"))
        off += 1 + n
    return ".".join(labels), (end if end is not None else off)


def _rr(name, rtype, data, ttl=TTL, flush=False):
    return _enc_name(name) + struct.pack("!HHIH", rtype, CLASS_IN | (FLUSH if flush else 0), ttl, len(data)) + data


def _txt(d):
    out = b""
    for k, v in d.items():
        e = ("%s=%s" % (k, v)).encode("utf-8")[:255]
        out += bytes([len(e)]) + e
    return out or b"\x00"


def parse(buf):
    """-> (id, flags, questions[(name, type)], records[(name, type, data_bytes, rdata_offset)])"""
    if len(buf) < 12:
        raise ValueError("short")
    mid, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", buf[:12])
    off, qs, rrs = 12, [], []
    for _ in range(qd):
        name, off = _dec_name(buf, off)
        qt, _qc = struct.unpack("!HH", buf[off:off + 4]); off += 4
        qs.append((name.lower(), qt))
    for _ in range(an + ns + ar):
        name, off = _dec_name(buf, off)
        rt, _rc, _ttl, ln = struct.unpack("!HHIH", buf[off:off + 10]); off += 10
        rrs.append((name, rt, buf[off:off + ln], off, _ttl))
        off += ln
    return mid, flags, qs, rrs


def _local_ipv4():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect((probe, 1)); ips.add(s.getsockname()[0]); s.close()
        except OSError:
            pass
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))


# ---- the responder --------------------------------------------------------------------------------------------------
class Advertiser:
    """info() -> None (say nothing) or {"name", "host", "port", "txt": {...}} -- called on every query, so the answer
    always reflects the relay as it is now (stopped, restarted on another port, switched off)."""

    def __init__(self, info, log=None):
        self.info, self.log = info, (log or (lambda *_: None))
        self._stop = threading.Event()
        self._sock = None
        self._last = None

    def start(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", PORT))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
            joined = 0
            for ip in _local_ipv4() or ["0.0.0.0"]:
                try:
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(GROUP) + socket.inet_aton(ip)); joined += 1
                except OSError:
                    pass
            s.settimeout(1.0)
            self._sock = s
        except OSError as e:
            self.log("mdns: cannot listen on UDP 5353 (%s) -- relays here are not discoverable" % e)
            return False
        threading.Thread(target=self._run, name="mdns", daemon=True).start()
        return True

    def stop(self):
        self._stop.set()
        cur = self._safe_info()
        if cur and self._sock:
            try:
                self._sock.sendto(self._answer(cur, ttl=0), (GROUP, PORT))   # goodbye
            except OSError:
                pass

    def _safe_info(self):
        try:
            return self.info()
        except Exception:
            return None

    def _answer(self, inf, mid=0, questions=b"", qd=0, ttl=TTL):
        inst = "%s.%s" % (inf["name"], SERVICE)
        host = "%s.local" % inf["host"]
        recs = [_rr(SERVICE, T_PTR, _enc_name(inst), ttl),
                _rr(inst, T_SRV, struct.pack("!HHH", 0, 0, int(inf["port"])) + _enc_name(host), ttl, flush=True),
                _rr(inst, T_TXT, _txt(inf["txt"]), ttl, flush=True)]
        for ip in inf.get("ips") or _local_ipv4():
            recs.append(_rr(host, T_A, socket.inet_aton(ip), ttl, flush=True))
        return struct.pack("!HHHHHH", mid, 0x8400, qd, len(recs), 0, 0) + questions + b"".join(recs)

    def _run(self):
        announced_at = 0
        while not self._stop.is_set():
            cur = self._safe_info()
            key = repr(cur)
            now = time.time()
            if cur and (key != self._last or now - announced_at > 60):   # unsolicited announcement on change / each minute
                try:
                    self._sock.sendto(self._answer(cur), (GROUP, PORT)); announced_at = now
                except OSError:
                    pass
            self._last = key   # a relay that stopped simply stops answering; its records expire with their TTL
            try:
                buf, src = self._sock.recvfrom(9000)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                time.sleep(1); continue
            try:
                mid, flags, qs, _ = parse(buf)
            except Exception:
                continue
            if flags & 0x8000 or not cur:   # a response, or nothing to say
                continue
            inst = ("%s.%s" % (cur["name"], SERVICE)).lower()
            if not any(q[0] in (SERVICE.lower(), inst) and q[1] in (T_PTR, T_SRV, T_TXT, T_ANY) for q in qs):
                continue
            try:
                if src[1] != PORT:   # a legacy (one-shot) query: unicast, echo the id and the question
                    qbytes = b"".join(_enc_name(n) + struct.pack("!HH", t, CLASS_IN) for n, t in qs)
                    self._sock.sendto(self._answer(cur, mid, qbytes, len(qs), ttl=10), src)
                else:
                    self._sock.sendto(self._answer(cur), (GROUP, PORT))
            except OSError:
                pass


# ---- the browser ------------------------------------------------------------------------------------------------------
def browse(timeout=1.6):
    """-> [{"name", "host", "port", "ips", "txt"}] -- every KASTR relay that answered within `timeout` seconds."""
    q = struct.pack("!HHHHHH", 0x4B41, 0, 1, 0, 0, 0) + _enc_name(SERVICE) + struct.pack("!HH", T_PTR, CLASS_IN)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.bind(("", 0))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    for ip in _local_ipv4() or ["0.0.0.0"]:   # ask on every interface
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
            s.sendto(q, (GROUP, PORT))
        except OSError:
            pass
    found, srv, txt, addrs = {}, {}, {}, {}
    end = time.time() + timeout
    while time.time() < end:
        s.settimeout(max(0.05, end - time.time()))
        try:
            buf, src = s.recvfrom(9000)
        except (socket.timeout, OSError):
            break
        try:
            _, flags, _, rrs = parse(buf)
        except Exception:
            continue
        for name, rt, data, roff, _ttl in rrs:
            try:
                if rt == T_PTR and name.lower() == SERVICE.lower():
                    inst, _ = _dec_name(buf, roff)
                    found[inst] = {"src": src[0]}
                elif rt == T_SRV:
                    _p, _w, port = struct.unpack("!HHH", data[:6]); target, _ = _dec_name(buf, roff + 6)
                    srv[name] = (target, port)
                elif rt == T_TXT:
                    d, i = {}, 0
                    while i < len(data):
                        n = data[i]; e = data[i + 1:i + 1 + n].decode("utf-8", "replace"); i += 1 + n
                        if "=" in e:
                            k, v = e.split("=", 1); d[k] = v
                    txt[name] = d
                elif rt == T_A and len(data) == 4:
                    addrs.setdefault(name.lower(), set()).add(socket.inet_ntoa(data))
            except Exception:
                continue
    s.close()
    out = []
    for inst, meta in found.items():
        target, port = srv.get(inst, ("", 0))
        ips = sorted(addrs.get(target.lower(), set())) or [meta["src"]]
        if meta["src"] in ips:   # the address it answered from first
            ips.remove(meta["src"]); ips.insert(0, meta["src"])
        out.append({"name": inst[: -len(SERVICE) - 1] if inst.endswith(SERVICE) else inst, "host": target, "port": port,
                    "ips": ips, "txt": txt.get(inst, {})})
    return out
