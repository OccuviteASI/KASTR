# -*- coding: utf-8 -*-
"""0.21.92 MEETING TEMPLATES, phase 1 ("by hand") -- the hub's template store, its deck store and the planner.

Kenton (2026-10-23 design review; 2026-10-27: "Having these options to setup the room how I want with whatever presenter options
are available"): a TEMPLATE is a saved snapshot of how a room is set up, in optional SECTIONS --
  layout    Layout & view: the room board (pins, spotlights and their order, grid layouts, room grids, split cameras) and
            whether the room starts on the spotlight or the gallery.
  streams   Streams & cameras: the cameras the board pulls in and how (pinned / in a grid / spotlit / split). Box cameras are
            kept by ORIGIN (the path without its room), library streams by their library path. With the section off, a template
            applies only what belongs to the room itself.
  pres      Presentation & roles: deck + starting slide (the deck lives on the hub, below), presenters (main), backstage and their
            per-presenter "Can control my mic and camera", audience muted / Ask to speak, the presenter mode and the Reporter
            background. People are kept by NAME. (Phase 1 keeps the shape; the presentation wiring follows the co-presenter work.)
  settings  Room settings: locked (the room code's salted digest ONLY -- never a code), kept open, view lock, group.
  invites   people to invite (by name, their last device as a hint), an invite link made FRESH at apply (no secret kept),
            people with access (My room).
  view      My view (personal templates only): this device's own grid layouts, pins, pinned panels, gallery / speaker -- applied
            on the applying device by its page; the hub only keeps it.
Never saved: live cameras / mics / shares, a box's own grid geometry / "Show in rooms" / encoders, recordings, chat, bans,
remote-control permissions.

WHO (kastr_relay.AuthService checks, this module stores): room templates -- everyone in the room sees and previews them; room
admins (the admin code, the room's creator with its roomKey) save / edit / delete. Personal templates belong to a PERSON (name +
My room code, the identity messaging uses) and follow them to any relay. Applying layout + streams: publishers (only admins while
the view is locked); settings and invites: room admins (My room: its owner). Every item is re-checked against the applier's own
rights at apply -- a template never carries power.

STORAGE: the hub keeps templates.json under <state>/templates (20 per room, 20 per person, 32 KB each) and carries it in the
records bundle (AuthStore.export_bundle) -- so hand-over, the standby's replica and the hand-back move it like the stream
library. DECKS live beside it (<state>/templates/decks/<deck>/), ENCRYPTED AT REST: every file is AES-256-GCM under its deck's
own key, and that key is kept wrapped (AES-GCM) under the hub's deck master key (<state>/templates/deck.key, never in a bundle).
The page may also hand the hub its own deck key (`pageKey`, escrowed wrapped the same way) so the files it uploads may be its own
ciphertext. Deck keys never ride the bundle: a box that copies decks (the new hub after a hand-over, the standby, the main hub at
a hand-back) asks for them over the federation channel and wraps them under its OWN master key at once.

WHO CAN DECRYPT A DECK: (1) the hub's KASTR (it holds the master key file), and anyone holding a copy of the hub's whole state
folder -- the master key and the decks together; (2) the people the hub serves it to -- the room's publishers and admins for a
room template (anyone who could present there), the owner for a personal template; (3) the relays a deck request passes through
(a spoke forwards its page's request and sees the reply), (4) the standby / a new hub after they copied it. NOT: a copy of the
decks folder alone (a backup, a stolen disk image without the key file), viewers, invite-link guests, other rooms.
"""
import base64
import copy
import hashlib
import hmac
import json
import os
import re
import shutil
import threading
import time

TPL_ROOM_MAX = 20                  # templates per room
TPL_PERSON_MAX = 20                # personal templates per person
TPL_BYTES_MAX = 32 * 1024          # one template (JSON), decks apart
VIEW_BYTES_MAX = 16 * 1024         # the My view section of a personal template
SECTIONS = ("layout", "streams", "pres", "settings", "invites", "view")
ROOM_SECTIONS = ("layout", "streams", "pres", "settings", "invites")
NAME_MAX, NOTE_MAX = 60, 300
TID_RE = re.compile(r"^t[0-9a-f]{12}$")
DID_RE = re.compile(r"^d[0-9a-f]{16}$")
UID_RE = re.compile(r"^u[0-9a-f]{12}$")
HOST_RE = re.compile(r"^[a-z0-9-]{1,32}-[0-9a-f]{4}$")
SLUG_RE = re.compile(r"^[a-z0-9-]{1,32}$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}(\.[A-Za-z0-9]{1,8})?$")
INVITE_TTLS = (3600, 86400, 604800)
INVITE_PEOPLE_MAX = 30
CAMS_MAX = 64
PRES_PEOPLE_MAX = 8
PRES_MODES = ("content", "standout", "side", "reporter")
START_MODES = ("", "gallery", "spotlight")
VIEW_MODES = ("", "gallery", "speaker")
UNDO_KEEP_S = 600                  # an apply can be undone this long (by the device that applied it)
GONE_KEEP_S = 30 * 86400           # a deleted template's tombstone (a hand-back never brings it back)

DECK_MAX = 300 * 1024 * 1024       # one deck (every file)
DECK_SCOPE_MAX = 1024 ** 3         # every deck of one room / one person
DECK_TOTAL_MAX = 8 * 1024 ** 3     # every deck on the hub
DECK_FILE_MAX = 64 * 1024 * 1024   # one file of a deck
DECK_FILES_MAX = 1200
DECK_UPLOAD_TTL = 6 * 3600         # an upload never finished is dropped after this
READ_TTL = 900                     # a deck read grant (rt=) lasts this long
DECK_AAD = b"kastr-tpl-deck-v1|"


def _now():
    return time.time()


def txt(v, n):
    """Plain text: no control characters, trimmed, at most n characters."""
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(v if v is not None else "")).strip()
    return s[:n]


def name_disp(v):
    return " ".join(str(v or "").split())[:48]


def name_key(v):
    """A person's key -- the same as My room's (kastr_relay.personal_key) and messaging's (kastr_msg.name_key)."""
    return name_disp(v).lower()


def _kr():
    import kastr_relay
    return kastr_relay


def stream_ok(path):
    try:
        return _kr().board_stream_ok(path)
    except Exception:
        return False


def origin_of(path):
    """A stream's ORIGIN: its path without the room (box cameras are saved by origin -- the same box camera in another room,
    or moved into the library, is the same camera)."""
    parts = str(path or "").split("/", 1)
    return parts[1] if len(parts) == 2 else ""


def room_of(path):
    return str(path or "").split("/", 1)[0]


def _b(v):
    return bool(v) and v is not False


def _int(v, lo, hi, dflt=0):
    try:
        x = int(v)
    except (TypeError, ValueError):
        return dflt
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------------------------------------------------
# sections: clean copies (a stored, mirrored, bundled or posted template goes through these)

def clean_layout(v):
    """The room board part -> {pins, spots, spotOrder, grids, customGrids, split, start} (kastr_relay.board_clean rules and
    caps; who / when dropped)."""
    v = v if isinstance(v, dict) else {}
    kr = _kr()
    spots = v.get("spots") if isinstance(v.get("spots"), list) else []
    spots = [{"target": (s.get("target") if isinstance(s, dict) else s), "ts": 0} for s in spots]
    b = kr.board_clean(dict(v, spots=spots))
    out = {"pins": [{"path": p["path"], "from": p["from"], "label": p.get("label") or "", "kind": p.get("kind") or "other"}
                    for p in b["pins"]],
           "spots": [s["target"] for s in b["spots"]],
           "spotOrder": list(b.get("spotOrder") or []),
           "grids": {gp: {k: g[k] for k in ("rects", "gap", "hidden", "slots", "sens")} for gp, g in (b.get("grids") or {}).items()},
           "customGrids": {gid: {k: g[k] for k in ("name", "slots", "gap", "sens")} for gid, g in (b.get("customGrids") or {}).items()},
           "split": list(b.get("split") or []),
           "start": v.get("start") if v.get("start") in START_MODES else ""}
    return out


def layout_paths(lay):
    """Every stream path a layout names (pins, spotlights, their order, grids and their cameras, room grids' cameras, splits)."""
    out = []

    def add(p):
        if p and p not in out:
            out.append(p)
    for p in lay.get("pins") or []:
        add(p.get("path"))
    for t in lay.get("spots") or []:
        add(t)
    for t in lay.get("spotOrder") or []:
        add(t)
    for gp, g in (lay.get("grids") or {}).items():
        add(gp)
        for mp in (g.get("rects") or {}):
            add(mp)
        for mp in g.get("hidden") or []:
            add(mp)
        for s in g.get("slots") or []:
            for mp in s.get("cams") or []:
                add(mp)
    for g in (lay.get("customGrids") or {}).values():
        for s in g.get("slots") or []:
            for mp in s.get("cams") or []:
                add(mp)
    for mp in lay.get("split") or []:
        add(mp)
    return out


def snap_streams(lay, room):
    """Streams & cameras from a layout: one row per camera / stream the board uses, with how it is used."""
    kr = _kr()
    rows = {}

    def row(p, how, label=""):
        if not stream_ok(p) or p.split("/")[1:2] == [kr.BOARD_CGRID_HOST]:
            return
        r = rows.get(p)
        if r is None:
            if len(rows) >= CAMS_MAX:
                return
            frm = room_of(p)
            r = rows[p] = {"path": p, "origin": origin_of(p), "from": frm, "lib": frm == kr.LIB_ROOT, "label": "",
                           "kind": "camera", "how": []}
        if label and not r["label"]:
            r["label"] = txt(label, 80)
        if how not in r["how"]:
            r["how"].append(how)
    for p in lay.get("pins") or []:
        row(p["path"], "pin", p.get("label"))
        if rows.get(p["path"]):
            rows[p["path"]]["kind"] = p.get("kind") or "other"
    for t in lay.get("spots") or []:
        row(t, "spot")
    for gp, g in (lay.get("grids") or {}).items():
        row(gp, "grid")
        if rows.get(gp):
            rows[gp]["kind"] = "grid"
    for g in (lay.get("customGrids") or {}).values():
        for s in g.get("slots") or []:
            for mp in s.get("cams") or []:
                row(mp, "cgrid")
    for mp in lay.get("split") or []:
        row(mp, "split")
    out = []
    for r in rows.values():
        if not r["label"]:
            r["label"] = r["path"].rsplit("/", 1)[-1][:-5][:80]
        r["foreign"] = r["from"] != room
        out.append(r)
    return {"cams": out}


def clean_streams(v):
    v = v if isinstance(v, dict) else {}
    out = []
    for c in (v.get("cams") if isinstance(v.get("cams"), list) else [])[:CAMS_MAX]:
        if not isinstance(c, dict) or not stream_ok(c.get("path")):
            continue
        p = str(c["path"])
        how = [h for h in (c.get("how") if isinstance(c.get("how"), list) else []) if h in ("pin", "spot", "grid", "cgrid", "split")]
        out.append({"path": p, "origin": origin_of(p), "from": room_of(p), "lib": room_of(p) == "lib",
                    "label": txt(c.get("label"), 80), "kind": txt(c.get("kind"), 16) or "camera", "how": how,
                    "foreign": _b(c.get("foreign"))})
    return {"cams": out}


def clean_settings(v):
    v = v if isinstance(v, dict) else {}
    out = {"locked": _b(v.get("locked")), "keep": _b(v.get("keep")), "viewLock": _b(v.get("viewLock")),
           "group": None, "groupName": txt(v.get("groupName"), 48)}
    salt, hsh = str(v.get("salt") or ""), str(v.get("hash") or "")
    if out["locked"] and re.match(r"^[0-9a-f]{8,64}$", salt) and re.match(r"^[0-9a-f]{64}$", hsh):
        out["salt"], out["hash"] = salt, hsh     # the room code's salted digest (as the room record keeps it) -- never a code
    elif out["locked"]:
        out["locked"] = False                    # "locked" without the digest cannot be applied
    g = v.get("group")
    if g not in (None, "") and SLUG_RE.match(str(g)):
        out["group"] = str(g)
    return out


def _people(v, cap):
    out, seen = [], set()
    for x in (v if isinstance(v, list) else [])[:cap * 2]:
        if isinstance(x, str):
            x = {"name": x}
        if not isinstance(x, dict):
            continue
        nm, host = name_disp(x.get("name")), str(x.get("host") or "")
        key = name_key(nm) or host
        if not key or key in seen:
            continue
        seen.add(key)
        r = {"name": nm}
        if HOST_RE.match(host):
            r["host"] = host
        if not nm and not r.get("host"):
            continue
        out.append(r)
        if len(out) >= cap:
            break
    return out


def clean_invites(v):
    v = v if isinstance(v, dict) else {}
    link = v.get("link") if isinstance(v.get("link"), dict) else None
    ttl = _int((link or {}).get("ttl"), 0, 10 ** 7, 0)
    return {"people": _people(v.get("people"), INVITE_PEOPLE_MAX),
            "link": {"ttl": ttl} if link is not None and ttl in INVITE_TTLS else None,
            "access": _people(v.get("access"), INVITE_PEOPLE_MAX)}


def clean_pres(v):
    """The PRESENTATION section's saved shape (phase 1 keeps it; the presentation code reads it once co-presenters land)."""
    v = v if isinstance(v, dict) else {}
    d = v.get("deck") if isinstance(v.get("deck"), dict) else None
    deck = None
    if d and DID_RE.match(str(d.get("id") or "")):
        deck = {"id": str(d["id"]), "name": txt(d.get("name"), 120) or "Deck", "slides": _int(d.get("slides"), 0, 2000),
                "start": _int(d.get("start"), 0, 1999), "kind": d.get("kind") if d.get("kind") in ("pptx", "pdf") else "pptx",
                "size": _int(d.get("size"), 0, DECK_MAX)}
    pres_names = []
    presenters = []
    for x in (v.get("presenters") if isinstance(v.get("presenters"), list) else [])[:PRES_PEOPLE_MAX * 2]:
        if isinstance(x, str):
            x = {"name": x}
        nm = name_disp((x or {}).get("name")) if isinstance(x, dict) else ""
        if nm and name_key(nm) not in pres_names:
            pres_names.append(name_key(nm))
            presenters.append({"name": nm, "main": _b(x.get("main"))})
        if len(presenters) >= PRES_PEOPLE_MAX:
            break
    if presenters and not any(p["main"] for p in presenters):
        presenters[0]["main"] = True
    seen_main = False
    for p in presenters:                         # one main presenter
        if p["main"] and seen_main:
            p["main"] = False
        seen_main = seen_main or p["main"]
    backstage = []
    for x in (v.get("backstage") if isinstance(v.get("backstage"), list) else [])[:PRES_PEOPLE_MAX * 2]:
        if isinstance(x, str):
            x = {"name": x}
        if not isinstance(x, dict):
            continue
        nm = name_disp(x.get("name"))
        if not nm or name_key(nm) in pres_names or any(name_key(b["name"]) == name_key(nm) for b in backstage):
            continue
        ctl = []
        for c in (x.get("control") if isinstance(x.get("control"), list) else [])[:PRES_PEOPLE_MAX]:
            if name_key(c) in pres_names and name_disp(c) not in ctl:
                ctl.append(name_disp(c))         # "Can control my mic and camera" -- set by each presenter (by name)
        backstage.append({"name": nm, "control": ctl})
        if len(backstage) >= PRES_PEOPLE_MAX:
            break
    aud = v.get("audience") if isinstance(v.get("audience"), dict) else {}
    return {"deck": deck, "presenters": presenters, "backstage": backstage,
            "audience": {"muted": aud.get("muted") is not False, "ask": aud.get("ask") is not False},
            "mode": v.get("mode") if v.get("mode") in PRES_MODES else "standout",
            "reporterBg": txt(v.get("reporterBg"), 60)}


def _jsonable_small(v, cap):
    try:
        s = json.dumps(v, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    return v if len(s) <= cap else None


def clean_view(v):
    """My view (a personal template): this device's own arrangement, kept as the page sent it (size-capped, shapes checked)."""
    v = v if isinstance(v, dict) else {}
    grids = {}
    for k, g in (v.get("grids") if isinstance(v.get("grids"), dict) else {}).items():
        if isinstance(g, dict) and re.match(r"^[A-Za-z0-9._/~-]{1,200}$", str(k)) and len(grids) < 16:
            g2 = _jsonable_small(g, 6000)
            if g2 is not None:
                grids[str(k)] = g2
    pins = [str(p) for p in (v.get("pins") if isinstance(v.get("pins"), list) else []) if stream_ok(p)][:9]
    dock = [str(x) for x in (v.get("dock") if isinstance(v.get("dock"), list) else []) if re.match(r"^[a-z]{2,12}$", str(x))][:8]
    cgrids = {}
    for k, g in (v.get("cgrids") if isinstance(v.get("cgrids"), dict) else {}).items():
        if isinstance(g, dict) and re.match(r"^[a-z0-9][a-z0-9-]{0,23}$", str(k)) and len(cgrids) < 8:
            g2 = _jsonable_small(g, 6000)
            if g2 is not None:
                cgrids[str(k)] = g2
    out = {"grids": grids, "pins": pins, "dock": dock, "cgrids": cgrids, "mode": v.get("mode") if v.get("mode") in VIEW_MODES else ""}
    while len(json.dumps(out)) > VIEW_BYTES_MAX and (out["grids"] or out["cgrids"]):
        (out["grids"] or out["cgrids"]).popitem()
    return out


CLEANERS = {"layout": clean_layout, "streams": clean_streams, "pres": clean_pres, "settings": clean_settings,
            "invites": clean_invites, "view": clean_view}


def clean_template(d, scope=None):
    """A whole template -> (clean copy, None) | (None, why). `scope` "room" | "me" (None: the record's own)."""
    d = d if isinstance(d, dict) else {}
    scope = scope or d.get("scope")
    if scope not in ("room", "me"):
        return None, "a template is for this room or just you"
    tid = str(d.get("id") or "")
    if not TID_RE.match(tid):
        return None, "bad template id"
    name = txt(d.get("name"), NAME_MAX)
    if not name:
        return None, "give the template a name"
    out = {"id": tid, "scope": scope, "name": name, "note": txt(d.get("note"), NOTE_MAX), "by": txt(d.get("by"), 64),
           "at": _int(d.get("at"), 0, 1 << 40), "upd": _int(d.get("upd"), 0, 1 << 40), "rev": _int(d.get("rev"), 0, 1 << 30)}
    if scope == "room":
        if not SLUG_RE.match(str(d.get("room") or "")):
            return None, "which room?"
        out["room"] = str(d["room"])
    else:
        ok = name_key(d.get("owner") or d.get("ownerName"))
        if not ok:
            return None, "whose template?"
        out["owner"], out["ownerName"] = ok, name_disp(d.get("ownerName") or d.get("owner"))
        if SLUG_RE.match(str(d.get("room") or "")):
            out["room"] = str(d["room"])         # the room it was saved from (its own feeds follow the room it is applied to)
    on = d.get("on") if isinstance(d.get("on"), dict) else {}
    secs = SECTIONS if scope == "me" else ROOM_SECTIONS
    out["on"] = {}
    for s in secs:
        if s in d and d[s] is not None:
            out[s] = CLEANERS[s](d[s])
            out["on"][s] = on.get(s) is not False
    if not out["on"]:
        return None, "pick at least one section"
    if len(json.dumps(out, separators=(",", ":"))) > TPL_BYTES_MAX:
        return None, "this template is larger than %d KB -- leave a section out" % (TPL_BYTES_MAX // 1024)
    return out, None


def public(t, room_admin=False):
    """What a page sees of a template: never the room code's digest; counts for the lists and dialogs."""
    t = copy.deepcopy(t)
    st = t.get("settings")
    if isinstance(st, dict):
        st.pop("salt", None)
        st.pop("hash", None)
    t["counts"] = counts(t)
    return t


def counts(t):
    """Live counts of each section (the Save dialog, the lists, the preview's header)."""
    out = {}
    lay = t.get("layout")
    if isinstance(lay, dict):
        out["layout"] = {"pins": len(lay.get("pins") or []), "spots": len(lay.get("spots") or []),
                         "grids": len(lay.get("grids") or {}), "cgrids": len(lay.get("customGrids") or {}),
                         "split": len(lay.get("split") or []), "start": lay.get("start") or ""}
    stm = t.get("streams")
    if isinstance(stm, dict):
        cams = stm.get("cams") or []
        out["streams"] = {"cams": len(cams), "foreign": sum(1 for c in cams if c.get("foreign") and not c.get("lib")),
                          "lib": sum(1 for c in cams if c.get("lib")), "grids": sum(1 for c in cams if c.get("kind") == "grid")}
    st = t.get("settings")
    if isinstance(st, dict):
        out["settings"] = {"locked": bool(st.get("locked")), "keep": bool(st.get("keep")), "viewLock": bool(st.get("viewLock")),
                           "group": st.get("groupName") or st.get("group") or ""}
    inv = t.get("invites")
    if isinstance(inv, dict):
        out["invites"] = {"people": len(inv.get("people") or []), "link": bool(inv.get("link")), "access": len(inv.get("access") or [])}
    pr = t.get("pres")
    if isinstance(pr, dict):
        out["pres"] = {"deck": bool(pr.get("deck")), "slides": (pr.get("deck") or {}).get("slides") or 0,
                       "presenters": len(pr.get("presenters") or []), "backstage": len(pr.get("backstage") or []),
                       "mode": pr.get("mode") or ""}
    vw = t.get("view")
    if isinstance(vw, dict):
        out["view"] = {"grids": len(vw.get("grids") or {}), "pins": len(vw.get("pins") or []), "dock": len(vw.get("dock") or []),
                       "mode": vw.get("mode") or ""}
    return out


# ---------------------------------------------------------------------------------------------------------------------
# the planner: a template + the room's board now -> the board ops that make it so (Replace or Merge), and back (Undo)

def map_path(p, src, room, streams_on=True, choices=None):
    """One saved path -> the path to use in room `room` (None: left out). The missing-camera choice first (drop / swap to
    another stream / keep), then the source room's own feeds follow to `room` (the same origin there); with Streams & cameras
    off a stream from another room or the library is left out."""
    p = str(p or "")
    c = (choices or {}).get(p) if isinstance(choices, dict) else None
    if isinstance(c, dict):
        if c.get("act") == "drop":
            return None
        if c.get("act") == "swap" and stream_ok(c.get("to")):
            return str(c["to"]) if (streams_on or room_of(c["to"]) == room) else None
    frm = room_of(p)
    if frm == src and src and room != src:
        p = room + "/" + origin_of(p)
        frm = room
    if not streams_on and frm != room:
        return None
    return p


def cam_rows(t, src, room, streams_on=True, choices=None):
    """The cameras / streams a template uses -> [{path (as saved), to (as applied, or None), label, how, kind}]."""
    kr = _kr()
    rows = {}
    for c in ((t.get("streams") or {}).get("cams") or []):
        rows[c["path"]] = {"path": c["path"], "label": c.get("label") or "", "how": list(c.get("how") or []), "kind": c.get("kind") or ""}
    for p in layout_paths(t.get("layout") or {}):
        if p not in rows and stream_ok(p) and p.split("/")[1:2] != [kr.BOARD_CGRID_HOST] and len(rows) < CAMS_MAX * 2:
            rows[p] = {"path": p, "label": p.rsplit("/", 1)[-1][:-5], "how": [], "kind": ""}
    out = []
    for r in rows.values():
        r["to"] = map_path(r["path"], src, room, streams_on, choices)
        out.append(r)
    return out


def map_layout(lay, src, room, streams_on=True, choices=None):
    """A template's layout for room `room` (map_path for every path it names) -> (layout, dropped paths)."""
    kr = _kr()
    dropped = []

    def m(p):
        return map_path(p, src, room, streams_on, choices)

    def mm(p):
        q = m(p)
        if q is None and p not in dropped:
            dropped.append(p)
        return q
    out = {"pins": [], "spots": [], "spotOrder": [], "grids": {}, "customGrids": {}, "split": [], "start": lay.get("start") or ""}
    for p in lay.get("pins") or []:
        q = mm(p["path"])
        if q and not any(x["path"] == q for x in out["pins"]):
            out["pins"].append({"path": q, "from": room_of(q), "label": p.get("label") or "", "kind": p.get("kind") or "other"})
    for t in lay.get("spots") or []:
        q = mm(t)
        if q and q not in out["spots"]:
            out["spots"].append(q)
    for t in lay.get("spotOrder") or []:
        q = m(t)
        if q and q not in out["spotOrder"]:
            out["spotOrder"].append(q)
    for gp, g in (lay.get("grids") or {}).items():
        q = mm(gp)
        if not q:
            continue
        rects = {}
        for mp, u in (g.get("rects") or {}).items():
            mq = m(mp)
            if mq and kr.board_same_room(q, mq):
                rects[mq] = u
        hidden = [x for x in (m(mp) for mp in g.get("hidden") or []) if x and kr.board_same_room(q, x)]
        slots = []
        for s in g.get("slots") or []:
            cams = [x for x in (m(mp) for mp in s.get("cams") or []) if x and kr.board_same_room(q, x)]
            slots.append(dict(s, cams=cams))
        if rects or hidden or any(s["cams"] for s in slots):
            out["grids"][q] = {"rects": rects, "gap": g.get("gap", 2), "hidden": hidden, "slots": slots, "sens": g.get("sens") or "medium"}
    for gid, g in (lay.get("customGrids") or {}).items():
        slots = []
        for s in g.get("slots") or []:
            cams = [x for x in (mm(mp) for mp in s.get("cams") or []) if x]
            slots.append(dict(s, cams=cams))
        if any(s["cams"] for s in slots):
            out["customGrids"][gid] = dict(g, slots=slots)
        elif gid not in dropped:
            dropped.append("grid:" + gid)
    for mp in lay.get("split") or []:
        q = mm(mp)
        if q and q not in out["split"]:
            out["split"].append(q)
    if src and room != src:   # a room grid's tile path names its room
        old = "%s/%s/" % (src, kr.BOARD_CGRID_HOST)
        fix = lambda t: (room + t[len(src):]) if t.startswith(old) else t
        out["spots"] = [fix(t) for t in out["spots"]]
        out["spotOrder"] = [fix(t) for t in out["spotOrder"]]
    return out, dropped


def _cur(board):
    b = board if isinstance(board, dict) else {}
    return {"pins": {p["path"]: p for p in b.get("pins") or [] if isinstance(p, dict) and p.get("path")},
            "spots": {s["target"]: s for s in b.get("spots") or [] if isinstance(s, dict) and s.get("target")},
            "spotOrder": list(b.get("spotOrder") or []), "grids": dict(b.get("grids") or {}),
            "customGrids": dict(b.get("customGrids") or {}), "split": list(b.get("split") or [])}


def _gsig(g):
    g = g or {}
    return json.dumps({"rects": g.get("rects") or {}, "gap": int(g.get("gap", 2) or 0), "slots": g.get("slots") or [],
                       "sens": g.get("sens") or "medium"}, sort_keys=True)


def _csig(g):
    g = g or {}
    return json.dumps({k: g.get(k) for k in ("name", "slots", "gap", "sens")}, sort_keys=True)


def plan_ops(target, board, mode="replace", now_ms=None):
    """-> [(op, item)] in the order to run them (removals first, pins before what needs them, spotlights last)."""
    now_ms = int(_now() * 1000) if now_ms is None else now_ms
    rep = mode == "replace"
    c = _cur(board)
    ops = []
    tpins = {p["path"]: p for p in target.get("pins") or []}
    tspots = list(target.get("spots") or [])
    tgrids = target.get("grids") or {}
    tcg = target.get("customGrids") or {}
    tsplit = list(target.get("split") or [])
    if rep:
        for t in c["spots"]:
            if t not in tspots:
                ops.append(("unspot", {"target": t}))
        for gid in c["customGrids"]:
            if gid not in tcg:
                ops.append(("cgridDel", {"id": gid}))
        for mp in c["split"]:
            if mp not in tsplit:
                ops.append(("unsplit", {"path": mp}))
        for gp in c["grids"]:
            if gp not in tgrids:
                ops.append(("gridReset", {"path": gp}))
        for p in c["pins"]:
            if p not in tpins:
                ops.append(("unpin", {"path": p}))
    for p, it in tpins.items():
        cur = c["pins"].get(p)
        if cur is None or (rep and it.get("label") and cur.get("label") != it.get("label")):
            ops.append(("pin", {"path": p, "from": it["from"], "label": it.get("label") or "", "kind": it.get("kind") or "other"}))
    for gid, g in tcg.items():
        cur = c["customGrids"].get(gid)
        if cur is None or (rep and _csig(cur) != _csig(g)):
            ops.append(("cgrid", {"id": gid, "grid": {k: g.get(k) for k in ("name", "slots", "gap", "sens")}}))
    for gp, g in tgrids.items():
        cur = c["grids"].get(gp)
        if cur is not None and not rep:
            continue
        has_layout = bool(g.get("rects")) or any(s.get("cams") for s in g.get("slots") or [])
        if has_layout and (cur is None or _gsig(cur) != _gsig(g)):
            ops.append(("grid", {"path": gp, "rects": dict(g.get("rects") or {}), "gap": int(g.get("gap", 2) or 0),
                                 "slots": list(g.get("slots") or []), "sens": g.get("sens") or "medium"}))
        elif not has_layout and cur is not None and (cur.get("rects") or cur.get("slots")) and rep:
            ops.append(("gridReset", {"path": gp}))
            cur = None
        ch = set((cur or {}).get("hidden") or [])
        for mp in g.get("hidden") or []:
            if mp not in ch:
                ops.append(("gridHide", {"path": gp, "member": mp}))
        if rep:
            for mp in ch:
                if mp not in (g.get("hidden") or []):
                    ops.append(("gridShow", {"path": gp, "member": mp}))
    for mp in tsplit:
        if mp not in c["split"]:
            ops.append(("split", {"path": mp}))
    i = 0
    for t in tspots:
        if t not in c["spots"]:
            i += 1
            ops.append(("spot", {"target": t, "ts": now_ms + i}))
    order = list(target.get("spotOrder") or [])
    if rep:
        if order != c["spotOrder"] and (order or c["spotOrder"]):
            ops.append(("spotOrder", {"targets": order}))
    elif order and not c["spotOrder"]:
        ops.append(("spotOrder", {"targets": order}))
    return ops


def board_keys(board):
    """Each item of a board under a key of its own -> {key: value} (what Undo compares)."""
    c = _cur(board)
    out = {}
    for p, it in c["pins"].items():
        out["pin:" + p] = {"path": p, "from": it.get("from") or room_of(p), "label": it.get("label") or "", "kind": it.get("kind") or "other"}
    for t, s in c["spots"].items():
        out["spot:" + t] = {"target": t, "ts": int(s.get("ts") or 0)}
    for gp, g in c["grids"].items():
        out["grid:" + gp] = {k: g.get(k) for k in ("rects", "gap", "hidden", "slots", "sens")}
    for gid, g in c["customGrids"].items():
        out["cgrid:" + gid] = {k: g.get(k) for k in ("name", "slots", "gap", "sens")}
    for mp in c["split"]:
        out["split:" + mp] = True
    if c["spotOrder"]:
        out["order"] = list(c["spotOrder"])
    return out


def board_from_keys(keys):
    b = {"pins": [], "spots": [], "grids": {}, "customGrids": {}, "split": [], "spotOrder": []}
    for k, v in keys.items():
        kind, _, rest = k.partition(":")
        if kind == "pin":
            b["pins"].append(v)
        elif kind == "spot":
            b["spots"].append(v)
        elif kind == "grid":
            b["grids"][rest] = v
        elif kind == "cgrid":
            b["customGrids"][rest] = v
        elif kind == "split":
            b["split"].append(rest)
        elif kind == "order":
            b["spotOrder"] = list(v)
    return b


def undo_ops(before, after, now):
    """The ops that put back what an apply changed (`before` / `after`: the board around the apply; `now`: the board at undo).
    Only the items the apply changed are touched -- later changes by others to other items stay."""
    kb, ka, kn = board_keys(before), board_keys(after), board_keys(now)
    changed = {k for k in set(kb) | set(ka) if json.dumps(kb.get(k), sort_keys=True) != json.dumps(ka.get(k), sort_keys=True)}
    if not changed:
        return []
    want = board_from_keys({k: v for k, v in kb.items() if k in changed})
    have = board_from_keys({k: v for k, v in kn.items() if k in changed})
    if "order" in changed and "order" not in kb:
        want["spotOrder"] = []
    ops = plan_ops(dict(want, spots=[s["target"] for s in want["spots"]]), have, "replace")
    ts = {s["target"]: s["ts"] for s in want["spots"]}
    for op, it in ops:   # a spotlight comes back with its own time (older votes keep their order)
        if op == "spot" and ts.get(it["target"]):
            it["ts"] = ts[it["target"]]
    return ops


def summarize(ops, labels=None):
    """Board ops -> the preview's words: {"pins+": 3, "pins-": 2, "spots": [...], ...}."""
    labels = labels or {}
    s = {"pins+": 0, "pins-": 0, "spots+": 0, "spots-": 0, "grids": 0, "cgrids+": 0, "cgrids-": 0, "split+": 0, "split-": 0,
         "order": False, "hidden": 0}
    for op, it in ops:
        if op == "pin":
            s["pins+"] += 1
        elif op == "unpin":
            s["pins-"] += 1
        elif op == "spot":
            s["spots+"] += 1
        elif op == "unspot":
            s["spots-"] += 1
        elif op in ("grid", "gridReset"):
            s["grids"] += 1
        elif op in ("gridHide", "gridShow"):
            s["hidden"] += 1
        elif op == "cgrid":
            s["cgrids+"] += 1
        elif op == "cgridDel":
            s["cgrids-"] += 1
        elif op == "split":
            s["split+"] += 1
        elif op == "unsplit":
            s["split-"] += 1
        elif op == "spotOrder":
            s["order"] = True
    return s


def leaf(p):
    s = str(p or "").rsplit("/", 1)[-1]
    return s[:-5] if s.endswith(".hang") else s


def op_words(op, it, labels=None):
    """One board op in words (the preview's list and the skipped-item notes)."""
    labels = labels or {}
    L = lambda p: labels.get(p) or leaf(p)
    p = it.get("path") or it.get("target") or ""
    if op == "pin":
        return "Pin %s%s" % (it.get("label") or L(p), (" (from %s)" % it["from"]) if it.get("from") and it["from"] != room_of(p) else "")
    if op == "unpin":
        return "Unpin " + L(p)
    if op == "spot":
        return "Spotlight " + L(p)
    if op == "unspot":
        return "Remove the spotlight on " + L(p)
    if op == "grid":
        return "Grid layout of " + L(p)
    if op == "gridReset":
        return "Grid layout of %s back to the box's own" % L(p)
    if op == "gridHide":
        return "Hide %s in %s" % (L(it.get("member")), L(p))
    if op == "gridShow":
        return "Show %s in %s again" % (L(it.get("member")), L(p))
    if op == "split":
        return "Show %s on its own" % L(p)
    if op == "unsplit":
        return "Put %s back in its grid" % L(p)
    if op == "cgrid":
        return "Room grid \"%s\"" % ((it.get("grid") or {}).get("name") or it.get("id"))
    if op == "cgridDel":
        return "Remove room grid %s" % it.get("id")
    if op == "spotOrder":
        return "Spotlight order"
    return op


# ---------------------------------------------------------------------------------------------------------------------
# the store

def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except Exception:
        return None


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, separators=(",", ":"))
    _replace(tmp, path)


def _replace(src, dst):
    for i in range(10):   # Windows: a scanner or indexer may hold the old file a moment (Access is denied)
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == 9:
                raise
            time.sleep(0.05 * (i + 1))


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


class TemplateBook:
    """<state>/templates/templates.json: {rooms: {slug: {tid: template}}, people: {nk: {tid: template}}, gone: {tid: at},
    decks: {did: meta}}; decks/<did>/<file> (AES-GCM under the deck's key); deck.key (the master key, 32 bytes)."""

    def __init__(self, state_dir=None, log=None):
        self.state_dir = state_dir or os.getcwd()
        self.dir = os.path.join(self.state_dir, "templates")
        self.log = log or (lambda m: None)
        self.lock = threading.RLock()
        self.rooms, self.people, self.gone, self.decks = {}, {}, {}, {}
        self.on_save = None        # AuthStore: a save moves the store's version (the standby's replica copies the bundle)
        self.n = 0
        self._mk = None
        self._read_secret = os.urandom(32)
        d = _load(self._path())
        if isinstance(d, dict):
            self._import_locked(d, replace=True)

    # ---- persistence -------------------------------------------------------------------------------------------------
    def _path(self):
        return os.path.join(self.dir, "templates.json")

    def ver(self):
        return self.n

    def _doc_locked(self):
        return {"rooms": self.rooms, "people": self.people, "gone": self.gone,
                "decks": {k: {x: y for x, y in v.items()} for k, v in self.decks.items()}}

    def _save_locked(self):
        os.makedirs(self.dir, exist_ok=True)
        _save(self._path(), self._doc_locked())
        self.n += 1
        cb = self.on_save
        if callable(cb):
            try:
                cb()
            except Exception:
                pass

    def _import_locked(self, d, replace=False):
        n = 0
        if replace:
            self.rooms, self.people, self.gone, self.decks = {}, {}, {}, {}
        for tid, at in (d.get("gone") if isinstance(d.get("gone"), dict) else {}).items():
            if TID_RE.match(str(tid)):
                self.gone[str(tid)] = max(int(self.gone.get(str(tid)) or 0), _int(at, 0, 1 << 40))
        for scope, src in (("room", d.get("rooms")), ("me", d.get("people"))):
            for key, tpls in (src.items() if isinstance(src, dict) else []):
                for tid, t in (tpls.items() if isinstance(tpls, dict) else []):
                    if str(tid) in self.gone:
                        continue
                    c, why = clean_template(dict(t, id=tid), scope) if isinstance(t, dict) else (None, "bad")
                    if c is None:
                        continue
                    k = c["room"] if scope == "room" else c["owner"]
                    shelf = (self.rooms if scope == "room" else self.people).setdefault(k, {})
                    mine = shelf.get(tid)
                    if mine is None or (c.get("upd") or 0) > (mine.get("upd") or 0) or replace:
                        shelf[tid] = c
                        n += 1
        for did, m in (d.get("decks") if isinstance(d.get("decks"), dict) else {}).items():
            m2 = self._deck_meta_clean(did, m)
            if m2 and (did not in self.decks or replace or m2.get("upd", 0) > self.decks[did].get("upd", 0)):
                keep = self.decks.get(did) or {}
                if keep.get("wk") and not m2.get("wk"):
                    m2["wk"], m2["wiv"] = keep["wk"], keep.get("wiv")
                    if keep.get("pk"):
                        m2["pk"], m2["piv"] = keep["pk"], keep.get("piv")
                self.decks[did] = m2
        return n

    @staticmethod
    def _deck_meta_clean(did, m):
        if not DID_RE.match(str(did)) or not isinstance(m, dict):
            return None
        files = {}
        for fn, f in (m.get("files") if isinstance(m.get("files"), dict) else {}).items():
            if FILE_RE.match(str(fn)) and isinstance(f, dict) and len(files) < DECK_FILES_MAX:
                files[str(fn)] = {"size": _int(f.get("size"), 0, DECK_FILE_MAX), "h": str(f.get("h") or "")[:64]}
        out = {"id": str(did), "tpl": str(m.get("tpl") or "") if TID_RE.match(str(m.get("tpl") or "")) else "",
               "scope": m.get("scope") if m.get("scope") in ("room", "me") else "room", "key": txt(m.get("key"), 64),
               "name": txt(m.get("name"), 120), "kind": m.get("kind") if m.get("kind") in ("pptx", "pdf") else "pptx",
               "slides": _int(m.get("slides"), 0, 2000), "size": _int(m.get("size"), 0, DECK_MAX), "files": files,
               "done": _b(m.get("done")), "at": _int(m.get("at"), 0, 1 << 40), "upd": _int(m.get("upd"), 0, 1 << 40),
               "by": txt(m.get("by"), 64), "utok": str(m.get("utok") or "")[:64]}
        for k in ("wk", "wiv", "pk", "piv"):   # the deck key (and the page's key) wrapped under THIS hub's master key -- never bundled
            if isinstance(m.get(k), str) and re.match(r"^[A-Za-z0-9+/=]{8,200}$", m[k]):
                out[k] = m[k]
        return out

    # ---- the bundle (hand-over, the standby's replica, the hand-back) -------------------------------------------------
    def export(self):
        """Templates + deck metadata, never a deck key (wrapped or not) and never an upload token."""
        with self.lock:
            d = json.loads(json.dumps(self._doc_locked()))
        for m in d["decks"].values():
            for k in ("wk", "wiv", "pk", "piv", "utok"):
                m.pop(k, None)
        return d

    def import_(self, b):
        """A new hub takes the old hub's templates (its own stay where the old hub had none)."""
        if not isinstance(b, dict):
            return 0
        with self.lock:
            n = self._import_locked(b)
            self._save_locked()
        return n

    def merge(self, b):
        """A hand-back: newer edits win, deletions stick (tombstones), decks made there are added."""
        if not isinstance(b, dict):
            return 0
        with self.lock:
            n = self._import_locked(b)
            for tid in list(self.gone):
                self._drop_locked(tid, tomb=False)
            self._sweep_locked()
            self._save_locked()
        return n

    # ---- templates ---------------------------------------------------------------------------------------------------
    def _shelf(self, scope, key):
        return (self.rooms if scope == "room" else self.people).get(key) or {}

    def list(self, scope, key):
        with self.lock:
            return sorted((copy.deepcopy(t) for t in self._shelf(scope, key).values()), key=lambda t: (-(t.get("upd") or 0), t["name"].lower()))

    def get(self, tid):
        with self.lock:
            for shelf in list(self.rooms.values()) + list(self.people.values()):
                if tid in shelf:
                    return copy.deepcopy(shelf[tid])
        return None

    def put(self, t, new=False):
        """Save a clean template -> (template, None, 200) | (None, why, code). A new one gets an id and its shelf's cap."""
        t = dict(t)
        now = int(_now())
        with self.lock:
            if new:
                for _ in range(8):
                    t["id"] = "t" + os.urandom(6).hex()
                    if self.get(t["id"]) is None and t["id"] not in self.gone:
                        break
                t["at"] = now
            t["upd"] = max(now, int(t.get("upd") or 0) + (0 if new else 1))
            t["rev"] = int(t.get("rev") or 0) + 1
            c, why = clean_template(t)
            if c is None:
                return None, why, 400
            key = c["room"] if c["scope"] == "room" else c["owner"]
            shelf = (self.rooms if c["scope"] == "room" else self.people).setdefault(key, {})
            if new and len(shelf) >= (TPL_ROOM_MAX if c["scope"] == "room" else TPL_PERSON_MAX):
                if not shelf:
                    (self.rooms if c["scope"] == "room" else self.people).pop(key, None)
                return None, ("this room already has %d templates -- delete one first" % TPL_ROOM_MAX if c["scope"] == "room"
                              else "you already have %d templates -- delete one first" % TPL_PERSON_MAX), 409
            if not new and c["id"] not in shelf:
                return None, "no such template", 404
            shelf[c["id"]] = c
            self._save_locked()
            return copy.deepcopy(c), None, 200

    def _drop_locked(self, tid, tomb=True):
        hit = None
        for book in (self.rooms, self.people):
            for key in list(book):
                if tid in book[key]:
                    hit = book[key].pop(tid)
                    if not book[key]:
                        book.pop(key, None)
        for did in [d for d, m in self.decks.items() if m.get("tpl") == tid]:
            self._deck_rm_locked(did)
        if tomb:
            self.gone[tid] = int(_now())
        return hit

    def delete(self, tid):
        with self.lock:
            hit = self._drop_locked(tid)
            self._save_locked()
        return hit

    def rename_room(self, old, new):
        """A renamed room keeps its templates (and its own feeds in them follow: they are mapped at apply)."""
        with self.lock:
            shelf = self.rooms.pop(old, None)
            if not shelf:
                return 0
            for t in shelf.values():
                t["room"] = new
            self.rooms.setdefault(new, {}).update(shelf)
            self._save_locked()
            return len(shelf)

    def rename_person(self, old, new, disp=""):
        """0.21.91 renames: a person who changed their name keeps their personal templates (and their decks)."""
        old, new = name_key(old), name_key(new)
        if not old or not new or old == new:
            return 0
        with self.lock:
            shelf = self.people.pop(old, None)
            if not shelf:
                return 0
            for t in shelf.values():
                t["owner"], t["ownerName"] = new, name_disp(disp) or t.get("ownerName") or new
            self.people.setdefault(new, {}).update(shelf)
            for m in self.decks.values():
                if m.get("scope") == "me" and m.get("key") == old:
                    m["key"] = new
            self._save_locked()
            return len(shelf)

    def _sweep_locked(self, now=None):
        now = _now() if now is None else now
        for tid in [k for k, at in self.gone.items() if now - at > GONE_KEEP_S]:
            self.gone.pop(tid, None)
        for did, m in list(self.decks.items()):
            if not m.get("done") and now - (m.get("at") or 0) > DECK_UPLOAD_TTL:
                self._deck_rm_locked(did)     # an upload never finished
            elif m.get("tpl") and self.get(m["tpl"]) is None and m["tpl"] in self.gone:
                self._deck_rm_locked(did)

    def sweep(self, now=None):
        with self.lock:
            self._sweep_locked(now)

    # ---- decks (encrypted at rest) -----------------------------------------------------------------------------------
    def crypto_ok(self):
        return _aesgcm() is not None

    def _master(self):
        if self._mk is not None:
            return self._mk
        p = os.path.join(self.dir, "deck.key")
        try:
            with open(p, "rb") as f:
                k = f.read()
            if len(k) == 32:
                self._mk = k
                return k
        except OSError:
            pass
        os.makedirs(self.dir, exist_ok=True)
        k = os.urandom(32)
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(k)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        _replace(tmp, p)
        self._mk = k
        return k

    def _wrap(self, did, raw, what=b"k"):
        A = _aesgcm()
        iv = os.urandom(12)
        ct = A(self._master()).encrypt(iv, raw, DECK_AAD + what + b"|" + did.encode())
        return base64.b64encode(ct).decode(), base64.b64encode(iv).decode()

    def _unwrap(self, did, wk, wiv, what=b"k"):
        A = _aesgcm()
        return A(self._master()).decrypt(base64.b64decode(wiv), base64.b64decode(wk), DECK_AAD + what + b"|" + did.encode())

    def _deck_dir(self, did):
        return os.path.join(self.dir, "decks", did)

    def _deck_rm_locked(self, did):
        self.decks.pop(did, None)
        shutil.rmtree(self._deck_dir(did), ignore_errors=True)

    def _used(self, scope=None, key=None):
        return sum(int(m.get("size") or 0) for m in self.decks.values()
                   if scope is None or (m.get("scope") == scope and m.get("key") == key))

    def deck_new(self, tpl, name, kind, slides, size, by="", page_key=None):
        """A new deck for template `tpl` -> ({deck, utok}, None, 200) | (None, why, code). The template's earlier deck goes
        when this one is finished (deck_done)."""
        if not self.crypto_ok():
            return None, "this hub cannot keep decks (its KASTR has no cryptography package)", 501
        size = _int(size, 0, 1 << 40)
        if size <= 0 or size > DECK_MAX:
            return None, "a deck is at most %d MB" % (DECK_MAX // (1024 * 1024)), 413
        with self.lock:
            t = self.get(tpl)
            if t is None:
                return None, "no such template", 404
            scope = t["scope"]
            key = t["room"] if scope == "room" else t["owner"]
            old = [d for d, m in self.decks.items() if m.get("tpl") == tpl]
            if self._used(scope, key) - sum(self.decks[d].get("size") or 0 for d in old) + size > DECK_SCOPE_MAX:
                return None, ("this room's decks already take %d MB -- delete a template with a deck first" if scope == "room"
                              else "your decks already take %d MB -- delete a template with a deck first") % (DECK_SCOPE_MAX // (1024 * 1024)), 413
            if self._used() + size > DECK_TOTAL_MAX:
                return None, "the hub's deck store is full", 507
            did = "d" + os.urandom(8).hex()
            k = os.urandom(32)
            wk, wiv = self._wrap(did, k)
            utok = os.urandom(16).hex()
            m = {"id": did, "tpl": tpl, "scope": scope, "key": key, "name": txt(name, 120) or "Deck",
                 "kind": kind if kind in ("pptx", "pdf") else "pptx", "slides": _int(slides, 0, 2000), "size": 0, "want": size,
                 "files": {}, "done": False, "at": int(_now()), "upd": int(_now()), "by": txt(by, 64), "utok": utok, "wk": wk, "wiv": wiv}
            if isinstance(page_key, str) and re.match(r"^[A-Za-z0-9+/=_-]{16,200}$", page_key):
                m["pk"], m["piv"] = self._wrap(did, page_key.encode(), b"p")
            self.decks[did] = m
            self._save_locked()
            return {"deck": did, "utok": utok}, None, 200

    def deck_put(self, did, utok, fname, data):
        """One file of a deck being uploaded (any bytes -- the page's own ciphertext, typically) -> (reply, code)."""
        with self.lock:
            m = self.decks.get(str(did))
            if m is None or m.get("done") or not utok or not hmac.compare_digest(str(m.get("utok") or ""), str(utok)):
                return {"ok": False, "error": "no such deck upload"}, 404
            if not FILE_RE.match(str(fname or "")):
                return {"ok": False, "error": "bad file name"}, 400
            if len(data) > DECK_FILE_MAX:
                return {"ok": False, "error": "one file of a deck is at most %d MB" % (DECK_FILE_MAX // (1024 * 1024))}, 413
            prev = (m["files"].get(fname) or {}).get("size") or 0
            if m["size"] - prev + len(data) > DECK_MAX or len(m["files"]) >= DECK_FILES_MAX and fname not in m["files"]:
                return {"ok": False, "error": "a deck is at most %d MB" % (DECK_MAX // (1024 * 1024))}, 413
            k = self._unwrap(did, m["wk"], m["wiv"])
            iv = os.urandom(12)
            ct = _aesgcm()(k).encrypt(iv, bytes(data), DECK_AAD + did.encode() + b"|" + fname.encode())
            os.makedirs(self._deck_dir(did), exist_ok=True)
            p = os.path.join(self._deck_dir(did), fname)
            with open(p + ".tmp", "wb") as f:
                f.write(iv + ct)
            _replace(p + ".tmp", p)
            m["files"][fname] = {"size": len(data), "h": hashlib.sha256(iv + ct).hexdigest()[:32]}
            m["size"] = sum(f["size"] for f in m["files"].values())
            m["upd"] = int(_now())
            self._save_locked()
            return {"ok": True, "deck": did, "file": fname, "size": len(data), "total": m["size"]}, 200

    def deck_done(self, did, utok):
        """The upload is complete: the template names this deck; its earlier deck goes."""
        with self.lock:
            m = self.decks.get(str(did))
            if m is None or not utok or not hmac.compare_digest(str(m.get("utok") or ""), str(utok)):
                return None, "no such deck upload", 404
            if not m["files"]:
                return None, "the deck has no files yet", 409
            m["done"], m["utok"], m["upd"] = True, "", int(_now())
            m.pop("want", None)
            for d2 in [d for d, x in self.decks.items() if x.get("tpl") == m["tpl"] and d != did]:
                self._deck_rm_locked(d2)
            self._save_locked()
            return dict((k, v) for k, v in m.items() if k not in ("wk", "wiv", "pk", "piv", "utok")), None

    def deck_of(self, tpl):
        with self.lock:
            for m in self.decks.values():
                if m.get("tpl") == tpl and m.get("done"):
                    return {k: copy.deepcopy(v) for k, v in m.items() if k not in ("wk", "wiv", "pk", "piv", "utok")}
        return None

    def deck_drop(self, tpl):
        with self.lock:
            hit = [d for d, m in self.decks.items() if m.get("tpl") == tpl]
            for d in hit:
                self._deck_rm_locked(d)
            if hit:
                self._save_locked()
            return len(hit)

    def read_grant(self, did, who, now=None):
        """A short-lived read grant for one deck (rt=), checked without the person's token (a spoke forwards the GET)."""
        exp = int((_now() if now is None else now) + READ_TTL)
        msg = ("%s|%s|%d" % (did, who, exp)).encode()
        return "%s.%d.%s" % (who, exp, hmac.new(self._read_secret, msg, hashlib.sha256).hexdigest()[:40])

    def read_ok(self, did, rt, now=None):
        try:
            who, exp, sig = str(rt).rsplit(".", 2)
            exp = int(exp)
        except (ValueError, TypeError):
            return False
        if exp < (_now() if now is None else now):
            return False
        msg = ("%s|%s|%d" % (did, who, exp)).encode()
        return hmac.compare_digest(sig, hmac.new(self._read_secret, msg, hashlib.sha256).hexdigest()[:40])

    def deck_page_key(self, did):
        with self.lock:
            m = self.decks.get(did)
            if not m or not m.get("pk"):
                return None
            return self._unwrap(did, m["pk"], m["piv"], b"p").decode()

    def deck_file(self, did, fname):
        """A deck's file, decrypted (the page's bytes as uploaded) -> bytes | None."""
        with self.lock:
            m = self.decks.get(str(did))
            if not m or not m.get("done") or fname not in (m.get("files") or {}) or not m.get("wk"):
                return None
            k = self._unwrap(did, m["wk"], m["wiv"])
        raw = self.deck_raw(did, fname)
        if raw is None or len(raw) < 28:
            return None
        try:
            return _aesgcm()(k).decrypt(raw[:12], raw[12:], DECK_AAD + did.encode() + b"|" + fname.encode())
        except Exception:
            return None

    def deck_raw(self, did, fname):
        """The file as kept (iv + ciphertext) -- what a copying hub takes."""
        if not DID_RE.match(str(did)) or not FILE_RE.match(str(fname)):
            return None
        try:
            with open(os.path.join(self._deck_dir(did), fname), "rb") as f:
                return f.read()
        except OSError:
            return None

    def deck_raw_store(self, did, fname, data):
        with self.lock:
            m = self.decks.get(did)
            if not m or fname not in m.get("files", {}):
                return False
            if hashlib.sha256(data).hexdigest()[:32] != m["files"][fname].get("h"):
                return False
            os.makedirs(self._deck_dir(did), exist_ok=True)
            p = os.path.join(self._deck_dir(did), fname)
            with open(p + ".tmp", "wb") as f:
                f.write(data)
            _replace(p + ".tmp", p)
            return True

    def keys_export(self, dids):
        """The deck keys a copying hub asks for (over the federation channel only) -> {did: {k, p?}} (raw, base64)."""
        out = {}
        with self.lock:
            for did in dids if isinstance(dids, list) else []:
                m = self.decks.get(str(did))
                if not m or not m.get("wk"):
                    continue
                r = {"k": base64.b64encode(self._unwrap(did, m["wk"], m["wiv"])).decode()}
                if m.get("pk"):
                    r["p"] = base64.b64encode(self._unwrap(did, m["pk"], m["piv"], b"p")).decode()
                out[did] = r
        return out

    def keys_take(self, keys):
        """Keys from the hub copied from -> wrapped under THIS hub's master key at once. -> how many."""
        n = 0
        if not isinstance(keys, dict) or not self.crypto_ok():
            return 0
        with self.lock:
            for did, r in keys.items():
                m = self.decks.get(str(did))
                if not m or not isinstance(r, dict) or m.get("wk"):
                    continue
                try:
                    k = base64.b64decode(str(r.get("k") or ""))
                    if len(k) != 32:
                        continue
                    m["wk"], m["wiv"] = self._wrap(did, k)
                    if r.get("p"):
                        m["pk"], m["piv"] = self._wrap(did, base64.b64decode(r["p"]), b"p")
                    n += 1
                except Exception:
                    continue
            if n:
                self._save_locked()
        return n

    def missing(self):
        """What a copying hub still needs -> {"keys": [did], "files": [(did, file)]} (finished decks only)."""
        keys, files = [], []
        with self.lock:
            for did, m in self.decks.items():
                if not m.get("done"):
                    continue
                if not m.get("wk"):
                    keys.append(did)
                for fn, f in (m.get("files") or {}).items():
                    p = os.path.join(self._deck_dir(did), fn)
                    try:
                        ok = os.path.getsize(p) == f.get("size", -1) + 28
                    except OSError:
                        ok = False
                    if not ok:
                        files.append((did, fn))
        return {"keys": keys, "files": files}


def deck_sync(book, keys_fn, file_fn, log=None, deadline=3600.0, sleep=time.sleep):
    """Copy what `book` misses of its decks from another hub: the keys (keys_fn([did]) -> {did: {k, p}}) and the files as kept
    there (file_fn(did, file) -> bytes | None). -> {"keys": n, "files": n, "missing": n}."""
    log = log or (lambda m: None)
    t0 = _now()
    got_k = got_f = 0
    tries = 0
    while True:
        miss = book.missing()
        if miss["keys"]:
            try:
                got_k += book.keys_take(keys_fn(miss["keys"]) or {})
            except Exception as e:
                log("templates: deck keys not copied: %s" % str(e)[:120])
        for did, fn in miss["files"]:
            if _now() - t0 > deadline:
                break
            try:
                data = file_fn(did, fn)
            except Exception:
                data = None
            if data is not None and book.deck_raw_store(did, fn, data):
                got_f += 1
        left = book.missing()
        n = len(left["keys"]) + len(left["files"])
        if not n or _now() - t0 > deadline or tries >= 3:
            if got_k or got_f or n:
                log("templates: decks copied -- %d key(s), %d file(s), %d still missing" % (got_k, got_f, n))
            return {"keys": got_k, "files": got_f, "missing": n}
        tries += 1
        sleep(min(30, 5 * tries))


class UndoBook:
    """The last applies, for Undo (memory only, UNDO_KEEP_S): uid -> {room, host, at, before, after, settings, links, access}."""

    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}

    def put(self, rec):
        uid = "u" + os.urandom(6).hex()
        with self.lock:
            now = _now()
            for k in [k for k, v in self.items.items() if now - v["at"] > UNDO_KEEP_S]:
                self.items.pop(k, None)
            self.items[uid] = dict(rec, at=now)
        return uid

    def take(self, uid, host):
        with self.lock:
            r = self.items.get(str(uid))
            if not r or _now() - r["at"] > UNDO_KEEP_S:
                return None, "this apply can no longer be undone"
            if r.get("host") != host:
                return None, "only the device that applied it can undo it"
            self.items.pop(str(uid), None)
            return r, None
