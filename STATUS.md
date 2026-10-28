# Agent G: toggles, not checkboxes (0.21.92)

Kenton 2026-10-28: "the check box should be a toggle. This should always be this way for all check boxes unless told differently".

## What was converted

I scanned every root `*.html`, every root `kastr*.py` (for inline pages) and `assets/*.js`. That covers static markup, JS string markup and `createElement` inputs. Almost all checkboxes were already switches. The last three bare ones were in moq-watch-lite.html:

| File | Converted | Where |
|---|---|---|
| moq-watch-lite.html | 3 | **Streams x rooms table** (`paintXsTable`): each cell's input now sits in a `<label class="switch sm">`. It has to be a LABEL because no label wraps the cell, and a span would not toggle (see the 0.21.15 note). The old `.xstab input { accent-color… 15px }` rule is replaced by `.xstab .switch { vertical-align:middle; }`. **My room people "Can arrange"** (`msPaintList`): the input is in a `span.switch.sm` inside the existing label. **Grid editor "Share with this room"** (`gridEditor`, `.geshare`): the input is in a `span.switch.sm` inside the existing label. |
| relay.html | 0 | All 16 were already switches. |
| stats.html | 0 | It has no checkboxes. |
| join / index / app / watch / rcx / rcx-agent.html | 0 | They have no checkboxes. |
| kastr_serve.py, kastr.py, kastr_rcadmin.py and the other kastr*.py | 0 | They have no inline checkbox markup, only comments. |
| assets/kastr-pres.js, kastr-msg.js, kastr-templates.js, kastr-presrec.js | 0 | All were already switches (`switchOf()`, `span/label.switch sm`). |

Ids, classes, aria-labels, handlers and checked/disabled state are unchanged. No JS looks these inputs up by structure; I checked `querySelector`, `closest('label')` and `.parentNode`. Every page that shows switches loads `/assets/asi-brand.css`, which defines `.switch` and `.switch.sm` with light and dark tokens and the `:focus-visible` ring. No page needed extra CSS.

After merging main at 8c405e2 (agent I, Remove / Ban): I added no checkboxes. The Ban dialog's "How long" picker is a segmented button group (`role="radiogroup"` with `role="radio"` buttons), which is a choice, not an on/off switch, so I left it alone. The toggles test still passes.

## Exceptions

None. The allowlist in `tests/test_release_0_21_92_toggles.py` is empty.

## Test

`tests/test_release_0_21_92_toggles.py` has 5 tests:
- **The scan:** markup `<input … type="checkbox">` must come right after a `<span|label class="…switch…">` opener, ignoring `' + '` string concatenation. For `x.type = "checkbox"` and `setAttribute("type","checkbox")`, the input must be appended with an `<i>` into a wrapper whose className is `switch…`, or go through `switchOf()`. `{type:"checkbox"}` is always flagged.
- **Self-test:** the scanner flags bare markup, string markup, createElement and setAttribute checkboxes, and passes the real switch patterns and selectors.
- **CSS check:** every page that uses `.switch` has its CSS.
- **Conversion pins:** the three converted spots are checked by name.
- **Proof:** run against the pre-change moq-watch-lite.html, the scanner flags exactly the three lines that were converted.

I updated one existing test minimally: `tests/test_release_0_21_66.py` now asserts the wrapped "Share with this room" form (`ssw`) plus the switch wrapper line.

## Visual check (headless Chrome, lab server on 127.0.0.1:9261, `/api/*` answers 404 and `/api/screen/**` 403)

Screenshots in `C:\Users\KENTON~1\AppData\Local\Temp\claude\C--Users-KentonJeffery-Claude\5342b5da-d8f4-41a9-963e-6bc5eebb097e\scratchpad\g_toggles\shots\`:
- `main-dark.png`, `main-light.png`: the three converted spots, built with the page's own CSS and the exact DOM code. They include a label-click proof: clicking the cell switch, the "Can arrange" label and the "Share with this room" label each toggles its input. Every switch measures 32x18.
- `relay-dark.png`, `relay-light.png`: the Relay page with all switches.
- `stats-dark.png`, `stats-light.png`: the stats page, which has no switches.

Seen in passing, **not caused by this change**: stats.html in the light theme shows grey cards with white text. That page has no light-theme handling of its own, so it is worth a look separately.

## Suites

See the final report. Everything passes except `test_npu_fx`, which is known to fail.
