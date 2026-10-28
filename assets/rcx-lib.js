// 0.21.83 (D) (Kenton: "allow remote control with the admin permissions on a relay/hub/camera box ... opt-in only"): the MoQ
// plumbing of a fleet admin's PRIVATE remote session -- rcx.html (the admin's view) and rcx-agent.html (the machine's headless
// helper) each hold ONE connection with a session token that covers only ~rcx/<sid>/...: one broadcast of JSON tracks out
// (the newest value is all that matters: top priority, short retention, a value written again on reconnect), snapshots in.
import { Net, Signals } from "https://esm.sh/@moq/watch";
import { Snapshot } from "https://esm.sh/@moq/json";

export { Net, Signals };

export function connect(url) {
  return new Net.Connection({ url: new Signals.Signal(new URL(url)), enabled: true });
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// origin.request(path) -> a consumer once the relay routes it (the 0.16.0 adapter of the app page)
export async function requestBroadcast(org, path, waitMs = 8000) {
  const h = org.request(Net.Path.from(String(path)));
  const t0 = performance.now();
  while (performance.now() - t0 < waitMs) {
    const bc = h.active?.peek?.();
    if (bc) return { bc, close: () => { try { h.close(); } catch {} } };
    if (h.unroutable?.peek?.()) break;
    await sleep(50);
  }
  try { h.close(); } catch {}
  return null;
}

// a broadcast of JSON tracks: set(name, value) writes it now and again after every reconnect
// 0.21.92: + opts.tracks[name] = {priority, maxAge} per track, and bytes(name, u8): one binary frame in a group of its own
// (the files' chunks, kastr-rcf.js -- never kept, never written again)
export function producer(conn, path, names, opts = {}) {
  const tracks = {}, latest = {};
  let ups = 0, writes = 0;
  const effects = new Signals.Effect();
  effects.run((e) => {
    const org = e.get(conn.origin);
    if (!org) return;
    let bp;
    try { bp = org.createBroadcast(Net.Path.from(path)); } catch { return; }
    e.cleanup(() => { try { bp.close(); } catch {} for (const k of Object.keys(tracks)) delete tracks[k]; });
    for (const n of names) { const o = opts.tracks?.[n] || opts; try { tracks[n] = bp.createTrack(n, { priority: o.priority ?? 255, maxAge: o.maxAge ?? 2000 }); } catch {} }
    // group sequences never go backwards on a resumed broadcast (see the app page's stateProducer): one empty group first
    const seq = Date.now() - 1790000000000;
    for (const t of Object.values(tracks)) { try { const g = new Net.Group.Producer(seq); t.writeGroup(g); g.close(); } catch {} }
    for (const [n, v] of Object.entries(latest)) { try { tracks[n]?.writeJson(v); } catch {} }
    try { bp.announce?.(); } catch {}
    ups++;
  });
  return {
    set(n, v) { latest[n] = v; const t = tracks[n]; if (t) { try { t.writeJson(v); writes++; } catch {} } },
    again(n) { const t = tracks[n]; if (t && n in latest) { try { t.writeJson(latest[n]); } catch {} } },   // a heartbeat
    bytes(n, u8) {
      const t = tracks[n]; if (!t) return false;
      try { const g = t.appendGroup(); g.writeFrame({ payload: u8, timestamp: Net.Time.Timestamp.now() }); g.close(); } catch {}
      return true;
    },
    get live() { return Object.keys(tracks).length > 0; },
    get ups() { return ups; },
    get writes() { return writes; },
    close() { try { effects.close(); } catch {} },
  };
}

// a JSON track, newest value first; re-subscribes when the broadcast goes, and when nothing arrived for `staleMs`
export function subscribe(conn, path, track, onValue, opts = {}) {
  const h = { closed: false, n: 0, at: 0, err: "", resubs: 0, sub: null };
  const staleMs = opts.staleMs ?? 6000;
  (async () => {
    let backoff = 400;
    while (!h.closed) {
      let sub = null, req = null, watchT = null;
      try {
        const org = conn.origin?.peek?.();
        if (!org) throw new Error("not connected");
        req = await requestBroadcast(org, path, 8000);
        if (!req) throw new Error("not routable yet");
        sub = req.bc.track(track).subscribe({ priority: opts.priority ?? 255, maxAge: 0 });
        h.sub = sub;
        const arm = () => { clearTimeout(watchT); watchT = setTimeout(() => { h.err = "stale"; try { sub.close(); } catch {} }, staleMs); };
        arm();
        const sn = new Snapshot.Consumer({ track: sub });
        for (;;) {
          const v = await sn.next();
          if (v === undefined || h.closed) break;
          backoff = 400; h.n++; h.at = Date.now(); arm();
          try { onValue(v); } catch (e) { console.warn("rcx", track, e); }
        }
      } catch (e) { h.err = String(e?.message || e); }
      clearTimeout(watchT);
      try { sub?.close(); } catch {}
      try { req?.close(); } catch {}
      if (h.closed) break;
      h.resubs++;
      await sleep(backoff);
      backoff = Math.min(3000, backoff * 2);
    }
  })();
  h.close = () => { h.closed = true; try { h.sub?.close(); } catch {} };
  return h;
}

// with a token: the relay URL the session dials
export function withJwt(url, tok) {
  const u = String(url || "").trim();
  return u + (u.includes("?") ? "&" : "?") + "jwt=" + encodeURIComponent(tok);
}
