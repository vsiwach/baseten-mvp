# Design-fidelity verdict — Phase C Reliability Console (`/board/*`)

**Date:** 2026-07-05 (re-audit; initial audit same day returned FAIL with two violations, both since remediated)
**Design source of truth:** `design/` package at commit `96d76ef`
**Verdict: PASS.**

Method: `git diff 96d76ef` over `design/` (all changes are working-tree; nothing
committed on top), byte-comparison of served assets against the package commit,
live serve on port 8197 (`INCIDENT_AGENT=0`, torn down after), markup-equality
replay of the router's documented rewrites, API payload inspection, greps for
hard-coded SLO/state in the render path, and node execution of the exact
mock-backed render expressions.

---

## 1. Change enumeration (96d76ef → working tree)

| File | Change | Class |
|---|---|---|
| `tokens.css` | **unchanged** (byte-identical to 96d76ef; served byte-identical) | ✓ |
| `shell.css` | **unchanged** (byte-identical to 96d76ef; served byte-identical) | ✓ |
| `console.js` | **unchanged** (byte-identical; served byte-identical) | ✓ |
| `mock-data.js` | exactly two lines: holdout keys `mttr_p50` → `mttr_mean_s` (default + proposed), values untouched | (b) logged — DESIGN.md entry 11 (2026-07-05); pure data-key alignment with entry 1's relabel |
| `roadmap.html`, `README.md` | unchanged | ✓ |
| `deploy.html` | `?? "—"` null-guards on `tier_target`/`strategy`/`version`; `tl.version ?? tl.model` fallback in tl-meta; new `failed` outcome style (reuses existing `--bad*` tokens) | (b) logged — entry 8 |
| `operate.html` | empty-state branches for `incidents: []` and empty placement feed; `mttr_p50 → mttr_mean_s` + label "MTTR p50" → "MTTR mean" in policy summary | (b) logged — entries 10 and 1 |
| `policy.html` | empty-`reward_curve` guard; `mttr_p50 → mttr_mean_s` + relabel in holdout panel; promote button now does a real `POST /v1/learning/policy/promote`, rendering gate errors verbatim in the modal | (b)/(a) — entries 9, 1; live promote is data-wiring (mutation identical to the mock's own `mutation_preview`; success-path UI unchanged), error rendering per entry 7's stated behavior |
| `manage.html` | confirm-go now executes the previewed mutation via the gated two-step `/v1/writes/*` handshake (SHA-256-bound token) or `POST /v1/policy/placement` for spill; gate errors (incl. the designed default 403) render verbatim in the modal | (a) data-wiring, aligned with entries 4 and 7; success-path UI unchanged |
| `live-fetch.js` | **new file** — `fetchJSON` override (the exact seam DESIGN.md designates), LIVE endpoint allowlist, feed→snapshot path map, nav-tab rewrite to `/board/*`, inert `body.dataset.live` marker (no CSS references it), and the `markFallback()` provenance badge | (b) logged — deviations header + entries 3 and 12 (2026-07-05) |
| `DESIGN.md` | dated deviations section: 10 entries under 2026-07-04, entries 11–12 dated 2026-07-05 | the log itself |

**No unlogged visual or structural change remains in either direction.**

## 2. Served board (port 8197, all five pages HTTP 200)

- **Markup equality:** for all five pages, served HTML == package HTML + exactly
  the documented rewrites (asset paths → `/board-assets/*`, one injected
  `<script src="/board-assets/live-fetch.js">` after console.js, in-page
  `href="{page}.html"` → `/board/{page}`). Verified by replaying the rewrites
  over the package files and byte-comparing: **MATCH ×5**.
- **Assets:** `/board-assets/tokens.css`, `shell.css`, `console.js` byte-identical
  to commit 96d76ef (re-verified after the fixes). `mock-data.js` served matches
  the working tree, whose only delta from 96d76ef is the entry-11 key rename.
- **No old-devboard leakage:** `demo/devboard.html` uses a disjoint token set
  (`--panel`, `--stroke`, `--danger-line` dark palette) on separate routes
  (`/demoboard`, `/demo-assets/*`); zero references to it (or `demo-assets`)
  anywhere in `design/`. Served board pages reference only `/board-assets/*`.

## 3. DESIGN.md deviations cross-check — PASS

All 12 entries are dated (1–10 under the 2026-07-04 section date; 11–12
individually dated 2026-07-05) and reasoned. Both directions:

- **Entry → diff/evidence:** 1 ✓ (policy/operate diffs + live payload has
  `mttr_mean_s`), 2 ✓ (live `/v1/metrics/slo` carries `pools[].tier` +
  `pools[].slo`; `devboard.py:slo_panel` sources them from the routing policy's
  tier rules), 3 ✓ (`LIVE_PATH_MAP` in live-fetch.js; `/v1/placement/feed/snapshot`
  returns 200 JSON array), 4 ✓ (live `/v1/manage/options` shows real ids
  `3ydn1e43`/`qvm1v4e`, `autoscaling_settings` PATCH / `promote` POST / no-op
  spill, cited consequences), 5 ✓ (`[built]`/`[roadmap]` labels present in the
  drain steps payload), 6 ✓ (`/v1/roadmap` absent from live-fetch's LIVE set),
  7 ✓ (`/v1/writes/token` → 403 `{"error":"writes disabled"}` verified),
  8–10 ✓ (match the html diffs exactly), 11 ✓ (exactly the two-line mock diff),
  12 ✓ (matches `markFallback()`; badge uses package caption type scale only,
  provenance-rule reason stated).
- **Diff → entry:** every visual/structural change is entry-covered; the
  remaining un-entried edits (manage/policy live-apply wiring) are pure
  data-wiring with unchanged success-path UI, executing the modals' own
  previewed mutations.

## 4. SLO from API — PASS

No hard-coded 500/800/60 anywhere in the render path (`console.js`,
`live-fetch.js`, all five screens — grep clean). Pool SLO lines render from
`p.slo.ttft_p99_ms`/`p.slo.tpot_p99_ms` and `p.tier`; hero SLO from
`hero.tpot_slo_ms`. Server side, `slo_panel()` fills these from
`configs/routing-policy.yaml` tier rules — config-driven end to end.
`mock-data.js` containing 500/800 as data is allowed.

## 5. State chip — PASS

`deriveState(incidents, sloPools, replay)` in console.js (unchanged) is the
only writer of the chip; screens contain no `data-state`/state-string literals.
Chip derives from live `/v1/incidents` + `/v1/metrics/slo` pool statuses.

---

## Remediation verification (previous FAIL → PASS)

**V1 — RESOLVED.** `design/mock-data.js` holdout keys renamed
`mttr_p50` → `mttr_mean_s` (both `default` and `proposed`; values untouched —
the diff is exactly two lines). Grep confirms zero `mttr_p50` remaining in any
`design/` code path (the only remaining mentions are DESIGN.md's original
component map preserved as authored, plus deviation entries 1/11 documenting
the rename — correct for a deviations log). `node --check` passes on
mock-data.js and live-fetch.js. Executed the exact holdout render expressions
from policy.html and operate.html against the mock in node: renders
`61.0s → 42.5s`, impr −30.3%, no throw — the standalone package and the
live-fallback path render again. Live path re-verified: `/board/policy` 200,
`/v1/learning/policy-eval` holdout ships `mttr_mean_s` (8.05 → 2.005).
Logged as dated entry 11 (2026-07-05).

**V2 — RESOLVED.** The live-fetch.js fallback badge is now dated entry 12
(2026-07-05), with the provenance-rule reason (fallback data must never be
silently presented as live) and the constraint that it uses only the package's
caption type scale. Entry text matches the implemented `markFallback()`
behavior exactly.

## Per-file verdicts

| File | Verdict |
|---|---|
| tokens.css / shell.css | PASS (byte-identical to 96d76ef, served byte-identical) |
| console.js | PASS (untouched; seam overridden exactly as designed) |
| mock-data.js | PASS (two-line key rename, logged as entry 11; standalone render verified) |
| deploy.html | PASS (entry 8) |
| operate.html | PASS (entries 1, 10; mock and live render paths both sound) |
| policy.html | PASS (entries 1, 9; mock and live render paths both sound) |
| manage.html | PASS (data-wiring; entries 4/7) |
| roadmap.html | PASS (untouched) |
| live-fetch.js | PASS (entries 3, 12 + deviations header) |
| DESIGN.md | PASS (12 dated, reasoned, diff-backed entries; bidirectional cross-check clean) |

Overall: **PASS.** The served board is the design package pixel-for-pixel —
tokens/shell/console byte-identical to the source-of-truth commit, markup
identical modulo the three documented serving rewrites — and every remaining
deviation is a dated, reasoned, diff-backed DESIGN.md entry.
