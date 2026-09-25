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
    parser.add_argument("--tls", type=int, nargs="?", const=8443, default=None,
                        help="0.17.0: also serve https on this port with the local CA (kastr_tls), like the launcher")
    args = parser.parse_args()
    kastr_serve.MODE = args.mode   # 0.12.0: what /api/instance + /api/mode report

    bridge = kastr_serve.make_bridge(state_dir=os.path.join(ROOT, ".kast"), log=print,   # 0.9.8
                                     hostname=None)   # 0.13.0: = make_server's hostname (both default)
    relay_srv = kastr_serve.make_relay(os.path.join(ROOT, ".kast"), print)
    server = kastr_serve.make_server(ROOT, args.host, args.port, args.coep, args.relay,
                                   bridge=bridge, relay_srv=relay_srv)
    # 0.9.8: POST /api/quit stops the harness through its finally (children too)
    kastr_serve.QUIT_HOOK = lambda: threading.Thread(target=server.shutdown, daemon=True).start()
    kastr_serve.HTTP_PORT = server.server_address[1]
    kastr_serve.LAN_OK = args.host not in ("127.0.0.1", "localhost", "::1")   # 0.17.0: like the launcher
    if args.tls:
        # 0.17.0: the web-client rig -- https with the local CA, mirroring kastr.py's listener
        import kastr_tls, kastr_relay
        tls = kastr_tls.ensure(os.path.join(ROOT, ".kast"), kastr_relay.local_ips())
        relay_srv.tls = tls
        tls_server = kastr_serve.make_tls_server(ROOT, args.host, args.tls, tls, coep=args.coep, quiet=True,
                                                 bridge=bridge, relay_srv=relay_srv,
                                                 relay_ref=server.relay_ref, alive_ref=server.alive_ref)
        threading.Thread(target=tls_server.serve_forever, daemon=True).start()
        kastr_serve.HTTPS_INFO.update(port=tls_server.server_address[1], fingerprint=tls["fingerprint"],
                                      ca=tls["ca_crt"], names=tls["names"])
        kastr_relay.HTTPS_PORT = tls_server.server_address[1]
        print(f"https    on {args.host}:{tls_server.server_address[1]} (CA {tls['fingerprint'][:12]}...)", flush=True)

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
