# 0.21.92 -- no plain-text passcodes at rest (branch worktree-agent-af6d0e3779fcf6446)

Base: main 4f39018 (v0.21.91). VERSION not bumped. Not merged, not pushed.

## How it works

- New module `kastr_secret.py`.
  - `seal()` / `unseal()` store a value as `ksec1:dp:...` (Windows DPAPI, current user, no UI) or `ksec1:kf:<kid>:...`
    (other systems: an owner-only 0600 `secret.key` in the state folder, HMAC-SHA256 stream + encrypt-then-MAC).
  - `KASTR_SECRET_STORE=keyring` opts in to the OS keyring (`ksec1:kr:`). It is off by default, so a box that boots
    with a locked keyring still starts. `file` / `dpapi` / `auto` are the other values.
  - A value with no `ksec1:` prefix is an old plain value and reads as-is. A value that can't be opened (another
    machine or account, a missing key, tampering) reads as "not saved", with one log line.
  - `POLICY` names, per file, which JSON fields are sealed. `.bak` / `.corrupt-*` copies follow the same policy.
    Camera URLs and pref values are sealed only when they carry credentials.
  - `digest()` / `digest_matches()` handle tokens that are only compared: chat, presentations, shared files and the
    ffmpeg child registry.
  - `mask()` hides codes and tokens in log lines and diag (URL passwords, `?jwt=`/`&code=`, free-text `code=`, JSON
    fields, Bearer, JWTs, invite tokens, sealed values), plus every value the process has sealed or opened.
  - `migrate_state()` runs once at launcher start. It rewrites the old plain files and their `.bak` copies sealed,
    and removes stale `*.tmp` copies of those files.
- The readers and writers in `kastr_relay` (load_json/save_json), `kastr_rtsp`, `kastr_gif`, `kastr_rcadmin` and
  `kastr_serve` (prefs, invite-pending) seal on write and open on read, so the rest of the code still sees plain values.
- `launch.log`, the media log, the relay's stdout/stderr log and `/api/diag` are masked.

## Tests

- `tests/test_release_0_21_92_secrets.py` covers:
  - every lab flow in one state folder, then a byte scan of the whole folder including launch.log and .bak copies;
  - a box restart with no window that still re-shares into a locked room;
  - My room unlock after an admin reset and a code change;
  - the hand-over to a standby;
  - migration of 0.21.91 files;
  - DPAPI and key-file round trips, tamper and foreign-key cases;
  - masking, the digest-based ffmpeg sig, and line endings.
- Three existing tests that read state files raw now go through `kastr_secret.open_doc` or check the sealed form:
  `test_release_0_21_75_boxrooms` (feeds_doc), `test_release_0_21_83_unattended` (the relay-rcx.json key) and
  `test_release_0_21_91_gif_search` (gif-search.json).
- Results:
  - Windows: 1974 tests; only test_npu_fx fails (ignored). One run hit a transient `[WinError 5]` on
    `os.replace(rcadmin.json.tmp)`; it passed three reruns and the code path is unchanged from 0.21.91.
  - WSL: 1974 tests; only test_npu_fx fails (ignored).

## Not changed (and why)

- `relay.toml`, `relay-peers.json`, `auth.jwk` and `tls/*.key` stay plain because moq-relay and the TLS servers read
  them. They are made owner-only on Linux; on Windows the per-user state folder ACL covers them.
- Room-lock records keep the page's single-round `sha256(salt+code)`, because the page computes it. A slow hash
  (PBKDF2 or scrypt) would need a page and protocol change; recommended for 0.22 with SSO.
- Browser storage in the KASTR Chrome profile still holds plain values: localStorage `kastr.personal.*` (My room
  code) and `kastr.lastjoin`, and sessionStorage. The prefs.json mirror on disk is sealed. A prefs.js shim is needed
  to fix the browser side; that is left for a page-side change.
- Old `chat/*.jsonl` lines keep their plain delete tokens, because rewriting them would break the replica byte
  offsets. New lines store digests.
- Values in transit (the hand-over bundle and roomKey heartbeats) travel plain inside TLS. Each machine seals its
  own copy, because DPAPI blobs can't move between machines.
- Downgrade: 0.21.91 would read `ksec1:` strings as if they were the codes. Going back to 0.21.91 needs the codes
  entered again.
