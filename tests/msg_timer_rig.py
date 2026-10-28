# -*- coding: utf-8 -*-
"""0.21.93: a small rig for the hub's message timers -- kastr_msg.Messenger straight (no relay, no crypto: the hub never
opens a message, so a body is any base64 and a wrap any 40-80 base64 characters). Not a test module itself."""
import base64
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import kastr_msg as km  # noqa: E402

T0 = 1_800_000_000.0


def b64(n):
    return base64.b64encode(os.urandom(n)).decode()


def host(name, i=1):
    return "%s-%04x" % (name.lower(), i)


class Hub:
    """A Messenger with people already set up (name -> its devices); `api(name, op, ..., dev=1, now=)`."""

    def __init__(self, names=("ada", "bob", "cy"), d=None):
        self.dir = d or tempfile.mkdtemp()
        self.pings = []
        self.m = km.Messenger(self.dir, check_code=lambda n, c: True, has_room=lambda n: True,
                              ping=lambda hosts, seq: self.pings.append((tuple(hosts), seq)))
        self.kid = {}
        for n in names:
            self.person(n)

    def person(self, n, dev=1, now=T0):
        pub = base64.b64encode(b"\x04" + os.urandom(64)).decode()
        o, c = self.m.api({"op": "setup", "name": n, "code": "code-%s-123" % n, "pub": pub, "wrapped": b64(80), "iv": b64(12),
                           "salt": b64(16), "iter": km.MSG_PBKDF2_MIN}, host(n, dev), now=now)
        assert c == 200, (c, o)
        self.kid[km.name_key(n)] = o["kid"]

    def api(self, who, op, dev=1, now=T0, **kw):
        body = dict(kw, op=op)
        body["as"] = who
        return self.m.api(body, host(who, dev), now=now)

    def send(self, who, to=None, gid=None, now=T0, cid=None, readers=None, files=None, **kw):
        names = readers or ([who, to] if to else [])
        if gid:
            names = self.m.groups[gid]["members"]
        wraps = {self.kid[km.name_key(n)]: {"iv": b64(12), "w": b64(48)} for n in names}
        cid = cid or base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("=")
        body = dict(dict(cid=cid, iv=b64(12), ct=b64(64), wraps=wraps, tv=1), **kw)
        if to:
            body["to"] = to
        if gid:
            body["gid"] = gid
        if files:
            body["files"] = files
        o, c = self.api(who, "send", now=now, **body)
        return o, c, cid

    def upload(self, who, data=b"x" * 100, now=T0):
        o, c = self.m.file_put(data, host(who), who, now=now)
        assert c == 200, (c, o)
        return o["fid"]

    def pull(self, who, dev=1, now=T0, since=0, tv=1):
        o, c = self.api(who, "pull", dev=dev, now=now, since=since, ack=0, **({"tv": 1} if tv else {}))
        assert c == 200, (c, o)
        return o

    def read(self, who, conv, seq, now, tv=1):
        return self.api(who, "read", now=now, conv=conv, seq=seq, **({"tv": 1} if tv else {}))

    def group(self, who, members, now=T0):
        o, c = self.api(who, "gcreate", now=now, name="Crew", members=members)
        assert c == 200, (c, o)
        return o["gid"]
