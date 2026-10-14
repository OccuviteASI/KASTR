"""0.21.64: every HTTP request KASTR makes says it is KASTR.

Cloudflare (the web portal's tunnel, kastr.madlabs.app) answers Python's default client identity "Python-urllib/3.x"
with 403 / error 1010, so a desktop KASTR reaching its hub through the tunnel could not read the hub's version (the
0.21.61 "Update now" button never appeared -- Kenton, 2026-10-14) and every other server-side call through the tunnel
(update checks and downloads, hub calls) met the same wall. Importing this module once makes urllib's default identity
"KASTR/<version>" for every request that does not set its own (urlopen with or without a context, Request objects alike).
"""
import os
import sys
import urllib.request

_UA = [None]


def user_agent():
    if _UA[0] is None:
        ver = ""
        for base in (getattr(sys, "_MEIPASS", ""), os.path.dirname(os.path.abspath(__file__))):
            try:
                with open(os.path.join(base, "VERSION"), encoding="utf-8") as f:
                    ver = f.read().strip()
                    break
            except OSError:
                continue
        _UA[0] = "KASTR/%s (+https://github.com/OccuviteASI/KASTR)" % (ver or "0")
    return _UA[0]


if not getattr(urllib.request.OpenerDirector, "_kastr_ua", False):
    _orig_init = urllib.request.OpenerDirector.__init__

    def _init(self, *a, **k):
        _orig_init(self, *a, **k)
        self.addheaders = [(h, v) for h, v in self.addheaders if h.lower() != "user-agent"] + [("User-agent", user_agent())]

    urllib.request.OpenerDirector.__init__ = _init
    urllib.request.OpenerDirector._kastr_ua = True
