#!/usr/bin/env python3
"""Plain CLI server for the MoQ demo pages -- the no-build workflow.

All the actual behaviour (COOP/COEP headers, relay substitution) lives in
kastr_serve.py so this and the packaged app can't drift apart. For a
double-clickable app instead, see kastr.py / build.py.

Usage:
    python kastr-serve.py [port] [--relay URL] [--coep MODE] [--host HOST]

Always serves the folder this script lives in, so it works no matter what the
current working directory is.

--relay  Relay to point the pages at. Defaults to kastr_serve.DEFAULT_RELAY.
         Pass --relay http://localhost:4443 to disable rewriting (no-op).
--coep   Cross-Origin-Embedder-Policy value:
           require-corp   (default) strictest; cross-origin subresources must
                          opt in with a Cross-Origin-Resource-Policy header.
           credentialless Chromium-only, still enables SharedArrayBuffer, but
                          lets no-cors cross-origin fetches through without
                          CORP. Use this if the libav.js worker fails to load
                          from cdn.jsdelivr.net.
--host   Interface to bind. Defaults to 0.0.0.0 so other machines on the
         network can load the UI from this one.
--mode   Operating mode to REPORT (0.12.0): full (default) | viewer | publisher |
         relay | publisher-relay. Sets kastr_serve.MODE, which /api/instance
         and /api/mode carry, so the shell and masthead can be checked in each
         mode from a source checkout. The harness itself never changes
         behaviour with it (no window, no relay-only bind).
"""
import argparse
import os
import threading

import kastr_serve

ROOT = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("port", nargs="?", type=int, default=8000)
    parser.add_argument("--relay", default=kastr_serve.DEFAULT_RELAY)
    parser.add_argument("--coep", choices=kastr_serve.COEP_MODES, default=kastr_serve.COEP_MODES[0])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--mode", choices=kastr_serve.MODES, default="full")   # 0.12.0
    args = parser.parse_args()
    kastr_serve.MODE = args.mode   # 0.12.0: what /api/instance + /api/mode report

    bridge = kastr_serve.make_bridge(state_dir=os.path.join(ROOT, ".kast"), log=print,   # 0.9.8
                                     hostname=None)   # 0.13.0: = make_server's hostname (both default)
    relay_srv = kastr_serve.make_relay(os.path.join(ROOT, ".kast"), print)
    server = kastr_serve.make_server(ROOT, args.host, args.port, args.coep, args.relay,
                                   bridge=bridge, relay_srv=relay_srv)
    # 0.9.8: POST /api/quit stops the harness through its finally (children too)
    kastr_serve.QUIT_HOOK = lambda: threading.Thread(target=server.shutdown, daemon=True).start()

    print(f"Serving {ROOT}")
    print(f"mode     {args.mode}")   # 0.12.0
    print(f"ffmpeg   {bridge.ffmpeg or 'not found -- RTSP ingest disabled'}")
    print(f"relay    {relay_srv.binary or 'not found -- relay hosting disabled'}")
    if args.relay != kastr_serve.BUILTIN_RELAY:
        print(f"Relay    {kastr_serve.BUILTIN_RELAY} -> {args.relay}  (rewritten in .html/.js/.css)")
    else:
        print(f"Relay    {args.relay}  (built-in default, no rewriting)")
    print(
        f"COOP=same-origin COEP={args.coep} on "
        f"http://localhost:{server.server_address[1]}/ (Ctrl+C to stop)",
        flush=True,
    )
    # Relay autostart (0.8.0): same behaviour as the packaged app, so the
    # dev harness can verify it. Start blocks up to ~6s -- thread it.
    def _auto():
        cfg = relay_srv.autostart_config()
        if not cfg.get("enabled"):
            return
        try:
            relay_srv.start(cfg.get("port") or 4443, bool(cfg.get("lan")), bool(cfg.get("secured")))
            print(f"relay autostarted on port {cfg.get('port') or 4443}", flush=True)
        except Exception as e:
            print(f"relay autostart failed: {e}", flush=True)
    threading.Thread(target=_auto, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        # Children outlive the parent on Windows unless told otherwise.
        relay_srv.stop()
        bridge.shutdown()
