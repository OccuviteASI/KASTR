# STATUS: worktree-agent-abfa7f9b7bd05cee8 (0.21.92 items: sign-in start, record test, My room split brain)

Base: main 4f39018 (v0.21.91). Not merged, VERSION not bumped, not pushed.

## 1. Start KASTR at sign-in, for everyone: DONE (unit-tested; Windows field check pending)
- Profile menu (next to Main room): switch "Start KASTR when I sign in to this computer", plus "Start minimized" (shown only while the first is on). These use the main page's own `<label class="switch"><input type="checkbox"><i></i></label>` markup. Hidden on web/remote pages and dev checkouts. The Relay page switch (#bootrun) stays, and the two re-read each other on focus/visibility.
- Off by default; existing Run keys are left alone. Turning the main switch off removes the key; toggling it keeps the minimized choice (STATE_DIR/autorun.json).
- With Start minimized on, the Run value / .desktop Exec carries `--minimized`. kastr.py strips it from argv once (START_MINIMIZED) and shows the window minimized with SetWindowPlacement (SW_SHOWMINNOACTIVE + WPF_RESTORETOMAXIMIZED), so a taskbar restore comes back maximized and the maximize logic does not fight it. It still connects and joins the main room. A hand launch has no flag and opens normally.
- Downgrade guard: an older build's registration never carries the flag. A sign-in start that finds the same build already running exits 0.
- Linux: X11 iconifies (kastr_x11.iconify_pid). Wayland cannot minimize another app's window, so it opens normally and a note is logged.
- Tests: tests/test_release_0_21_92_autorun.py (21 tests). They use mocked winreg and a temp HOME and never touch the real HKCU Run key. They pass on Windows and WSL. The minimize was also checked in a real browser on a hidden desktop: the window stayed iconic and restored maximized after about 0.7–1 s.

Windows field check (Kenton):
1. In Profile, turn on "Start KASTR when I sign in to this computer", then "Start minimized".
2. Sign out and back in. KASTR should be in the taskbar, minimized, and joined to the main room.
3. Click it. It should restore maximized if it was maximized before.
4. Start KASTR by hand. It should open normally.
5. On the Relay page, the switch should agree with Profile.
6. Turn the main switch off. Check in your own regedit that HKCU\...\Run\KASTR is gone (tools see a virtualized HKCU).

## 2. Flaky record-formats test: FIXED (test robustness; the server was not at fault)
- WinError 10060 is a loopback connect time-out under load (SYN dropped / TIME_WAIT churn). The server is not to blame: conversion runs on its own thread, the backlog is 128, and the client is sequential.
- The test now retries the connect up to 4 times on a fresh client port, polls jobs every 0.4 s and forgets finished jobs.
- Proof: 10/10 OK while the full WSL suite ran in parallel, plus 30+10+30 earlier loops with no failures.

## 3. "already has a My room with another code" right after Set up: REPRODUCED + FIXED
- Root cause: relayHostBase() (moq-watch-lite.html) returned location.origin whenever the relay was on this machine, even when ANOTHER KASTR runs that relay. My room went to the page's own KASTR's local store, while Messages went to the relay/hub (authBase). Set up made My room in the wrong store, Messages said "Wrong My room code", and the next Set up said "already has a My room with another code".
- Fix: on the same machine, the relay's /api/auth `web` port (authWeb) wins when it is not the page's own port. It is trusted only while authWebFor === authBase(); IS_WEB pages and relays that never said keep the old rule.
- Test: tests/test_release_0_21_92_relayhost.py has markers plus a 7-row table run under node (skipped without node). The table was proven ALL OK in headless CfT.
- Did NOT reproduce, as expected, on a hub+spoke lab: a brand-new name; a name used before; a renamed person (old name held, 409); two quick Set up clicks or concurrent creates; spoke+hub at once.
- Field note: an orphan My room may still sit in the local store of Kenton's non-hub KASTR. After the fix it is ignored.

## Docs
RELEASES.md "v0.21.92 (in progress)", REQUIREMENTS.md R-15, ARCHITECTURE.md (autorun row + new relayHostBase row).
