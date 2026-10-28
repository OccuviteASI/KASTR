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

## Downgrade to an older build (follow-up)

- `kastr.update_from` checks the download's checksum and size first. Only then, right before the swap, it calls
  `secrets_for_swap(theirs, mine)`: when the target is older than 0.21.92 (`kastr_secret.reads_sealed`), it runs
  `unseal_state()` so the state folder holds plain values that the older build can read. 0.21.92 or newer, or an
  unparseable version, stays sealed.
- A failed download, checksum or size leaves the state sealed, because nothing was unsealed yet.
- If placing the new binary fails, `secrets_swap_failed(theirs)` reseals the state (the current build keeps running).
- If the relaunch fails after the older binary is in place, the state stays plain, because that older binary is what
  starts next.
- When 0.21.92 runs again, `migrate_state()` seals everything once more.
- Digests can't be reversed: chat delete tokens, presentation and shared-file tokens written by 0.21.92 stay digests.
  After a downgrade those few items can't be deleted or controlled from their old links. The codes themselves all
  come back plain.
- Hub hand-over is version-neutral: `export_bundle()` is plain JSON in memory, sent over TLS, and each side stores it
  its own way. A lab with the real 0.21.91 code (4f39018) passed both ways:
  - 0.21.92 hub to 0.21.91 standby: the key is plain on the old standby's disk, as before;
  - 0.21.91 hub to 0.21.92 standby: the key is sealed;
  - in both directions the take-over heartbeat returns 200, a wrong key gets 409, codes check, and the hand-back and
    hub restart are OK.

## Browser storage (follow-up): `assets/vault.js`

- Loaded right after prefs.js or client.js on moq-watch-lite.html, app.html, index.html, relay.html and stats.html.
  It wraps `Storage.prototype` getItem/setItem/removeItem for the code-bearing keys.
- Each value is stored as `kv1:<b64url(iv|ciphertext)>`. The cipher is AES-GCM 256 under a non-extractable CryptoKey
  in IndexedDB (`kastr-vault` / `keys` / `k1`). The AAD is `kastr-vault-v1|<local|session>|<key name>`, so a value
  opens only under its own name.
- Keys covered:
  - localStorage, always: `kastr.lastjoin` (the saved access code; stats.html mints its browse token from it),
    `kastr.live` and `kastr.personal.*` (the My room code; `kastr.personal.people` is excluded).
  - localStorage, only while they carry a credential: `kastr.rtsp.persist`, `kastr.rtsp.history` and
    `kastr.relay.history`.
  - sessionStorage: `kastr.rejoin`, `kastr.watchcodes`, `kastr.invite`, `kastr.access`, `kastr.auth.*`,
    `kastr.browse.*` and stats.html's `kastr.stats.browse.*`.
- On load, every wrapped value is opened into memory once (`__kastrVault.ready`; the pages' modules await it), so
  reads stay synchronous. Plain values left by 0.21.91 are wrapped in place, and the plain copy is removed.
- prefs.js mirrors only the wrapped form to prefs.json, and the server stores a `kv1:` lastjoin as it is (already
  wrapped, and only this browser profile holds its key). A value that can't be unwrapped counts as "not saved".
- The straight-in launch, the Messages unlock and stats.html need no extra prompt.
- Known costs:
  - A 0.21.91 page (after a downgrade) can't read `kv1:` values, so it asks for the code once.
  - An insecure context (plain http on a LAN address, with no WebCrypto) keeps localStorage codes in memory only, so
    those web viewers are asked for the code on each visit. sessionStorage there works as before.
  - After a Chrome profile wipe or a web-port change (a new origin, so a new IndexedDB key), the wrapped mirror can't
    be opened: the code is asked once, and camera history that carried credentials is lost.
- `STATE_DIR/autorun.json` (the Profile menu's start-at-sign-in state, from main) holds no secrets and needs no seal.
- Browser lab (127.0.0.1:9161, relay 4931, lab codes only; /api/screen refused with 403):
  - App origin: plain 0.21.91 values migrated to `kv1:`; straight into the Lobby, then into My room with
    mainroom=mine; Messages "ready" with no prompt.
  - App restart (server restarted, new tab session): straight back into My room, Messages ready, all keys `kv1:`.
    prefs.json holds only the wrapped lastjoin, and a byte scan of the state folder finds no lab code.
  - stats.html with the saved code opens straight away (lock hidden, connected), and its browse token is wrapped.
  - Web viewer (http://web.localhost:9161, a secure context): plain lastjoin migrated, straight into the Lobby
    (about 2.3 s), the same again after a server restart, and stats.html opens straight away there too.
- Tests: `tests/test_release_0_21_92_downgrade.py` (14 tests). They cover version gating, the round trip (seal,
  downgrade, 0.21.91 write, upgrade, seal again), the swap to an older build with a mocked download (sealed on a
  checksum or size mismatch, resealed on a placement failure, plain at relaunch), the hand-over both ways, and static
  vault checks (script order, awaits, key coverage, the server and mirror keeping `kv1:`, line endings).

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
  - After the follow-ups and `git merge main` (rooms need a code, start at sign-in): Windows 2032 tests and WSL 2032
    tests; on both, only test_npu_fx fails (ignored).

## Not changed (and why)

- `relay.toml`, `relay-peers.json`, `auth.jwk` and `tls/*.key` stay plain because moq-relay and the TLS servers read
  them. They are made owner-only on Linux; on Windows the per-user state folder ACL covers them.
- Room-lock records keep the page's single-round `sha256(salt+code)`, because the page computes it. A slow hash
  (PBKDF2 or scrypt) would need a page and protocol change; recommended for 0.22 with SSO.
- Old `chat/*.jsonl` lines keep their plain delete tokens, because rewriting them would break the replica byte
  offsets. New lines store digests.
- Values in transit (the hand-over bundle and roomKey heartbeats) travel plain inside TLS. Each machine seals its
  own copy, because DPAPI blobs can't move between machines.
- Downgrade by hand (copying an old exe over the new one, without the updater) skips `unseal_state()`. 0.21.91
  would then read `ksec1:` strings as if they were the codes, so the codes must be entered again.
