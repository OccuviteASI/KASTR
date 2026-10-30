# 0.21.95 stats.html themes: status

Branch `stats-0.21.95` (based on 599965b = v0.21.94). Not merged, not pushed.

## What changed
- **stats.html** now has one colour source: `<style id="kastrStatsTheme">`. It sits after the Tailwind build and asi-brand.css, and before asi-brand.js.
  - Every Tailwind neutral/white colour that the page and the stats bundle use (`--color-neutral-200..950`, `--color-white`) now points at the app's theme tokens (`--bg`, `--surface`, `--line`, `--text`, `--text-dim`, `--text-mute`). So Dark, Light, Midnight, Slate, Warm, High contrast and Custom all apply.
  - The Tailwind data colours (emerald/sky/amber/red) get darker values in light themes. Dark keeps Tailwind's own values.
  - The selected node card and the input focus ring use the accent (`--color-emerald-600` points at `--asi-blue`).
  - The SVG chart colours the bundle writes as attributes (`#34d399` egress, `#38bdf8` ingress, `#404040` axis) are overridden in CSS for stroke and gradient stop-color. Dark is unchanged; light uses darker green and blue.
  - Also covered: card surfaces, borders, placeholders, the highlight.js `<code>` chip in the header, and the prose links at the bottom ("Go Live.").
  - The bundle `assets/stats-1j1isRcX.js` is untouched.
- The lock card's inline colours (the "Show stats" button and the error text) moved to the `.st-go` and `.st-err` classes. The button uses the accent and `--on-accent`.
- `assets/prefs.js` now loads on stats.html, so a browser on this machine that has never opened the main page still gets the app's theme and accent. It loads after client.js and before vault.js, so the downgrade order is kept.
- Following the app's theme: the shared head snippet (unchanged) reads `localStorage kastr.theme` before first paint. asi-brand.js's storage listeners switch theme and accent live when they change in another tab.
- No on/off controls exist on the page, so no switches were needed. The page has 0 checkboxes and the bundle creates none.

## Tests
- New: `tests/test_release_0_21_95_stats_theme.py`, 9 tests. It checks:
  - the token block's position
  - no colour literals or inline colour styles outside the token block
  - every Tailwind colour utility in stats.html and the bundle is mapped
  - the accent is wired
  - every SVG hex in the bundle is overridden with var()
  - light data colours pass WCAG contrast on the light and warm grounds (4.5:1 for text, 3:1 for the amber/red dots)
  - the theme-follow wiring and prefs.js order
  - the bundle is still vendored as-is
  - no checkbox outside `.switch`
  - It caught one real issue: the light amber dot was 2.8:1, now `#b45309`.
- `python -m unittest discover -s tests -q`: 2398 tests ran. The only failure is `test_npu_fx`, which fails in worktrees only because the untracked model files are missing. After a later one-line CSS tweak, the theme-related tests (95_stats_theme, 72_themes, theme, 92_toggles, 92_downgrade, 92_room_name_audit) were re-run: 48 OK.

## Lab verification
- Lab: `C:\kastr-scratch\v02195\stats\lab`
  - moq-relay on UDP 5042 / TCP 9391 with stats on, node `lab95-hub`
  - two ffmpeg test-pattern publishers and two CLI viewers
  - the worktree's kastr_serve on 9380, with `/api/screen/**` refused
  - No camera or mic was used.
- The Playwright Edge rig (`pw_stats_themes.py`) ran against live data (about 5 Mbps egress). It checks the WCAG contrast of every visible text node:
  - 0 low-contrast entries in dark, light, midnight, slate, warm, contrast, custom-light, light-accent-yellow, dark-accent-pink, and on the lock card in light and dark.
  - The BEFORE page in light had 13 failures at 1.12:1.
  - Live switch test: setting the theme or accent in a second tab updates the first tab.
- Screenshots in `C:\kastr-scratch\v02195\stats\shots\`:
  - stats-dark, stats-light, stats-midnight, stats-slate, stats-warm, stats-contrast, stats-custom-light, stats-light-accent-yellow, stats-dark-accent-pink, stats-lock-light, stats-lock-dark
  - BEFORE-stats-dark, BEFORE-stats-light, BEFORE-stats-midnight
  - report.json

## Known limits
- In dark themes the data colours (green/sky/amber/red) keep Tailwind's own shades. They are not tied to the theme tokens.
- The ASI masthead stays navy in every theme, by design (same as the other pages).
- Before first paint, the accent comes from asi-brand.js (a module), not from the head snippet. A custom accent can show the default blue for a frame on a cold load. Same as the other pages.
- The secured-relay lock card was shot by unhiding it on the open lab relay, not on a real secured relay.
- The dark look shifted slightly. Surfaces now carry the navy tint of the app's tokens instead of Tailwind's pure neutral greys, and the selected node card uses the accent (blue) instead of emerald.
- If the bundle is re-vendored with new colour classes or SVG hexes, `test_every_tailwind_colour_the_page_and_bundle_use_is_mapped` and `test_bundle_svg_colours_are_overridden` will fail until they are mapped.
