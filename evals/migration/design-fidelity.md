# Design-fidelity verdict — KV-affinity graceful migration UI

**Date:** 2026-07-05 · **Baseline:** commit `8aad9e2` · **Reviewer:** design-fidelity critique agent

## VERDICT: PASS

The design/ package remains the pixel source of truth. Every hunk in the four
touched design files is either data wiring through the existing `fetchJSON`
seam or is covered by dated deviations #14–15 in `design/DESIGN.md`. The
protected files (`tokens.css`, `shell.css`, `console.js`) are byte-identical
to `8aad9e2`. No unlogged visual change found.

## 1. Hunk classification (git diff 8aad9e2..HEAD)

### design/tokens.css, design/shell.css, design/console.js
**UNTOUCHED** — `git diff --quiet 8aad9e2 -- design/tokens.css design/shell.css design/console.js` exits clean. ✅

### design/live-fetch.js (1 hunk)
- Adds `"/v1/migrations/current"` to the `LIVE` set → **data wiring** (also
  named explicitly in deviation #15). ✅

### design/mock-data.js (1 hunk)
- Adds `"/v1/migrations/current": { state: "idle" }` mock key → **data
  wiring** (named in deviation #15; keeps the operate strip and manage modal
  quiescent in mock mode). ✅

### design/manage.html (4 hunks)
1. Boot fetch widened to `Promise.all([/v1/manage/options, /v1/pools,
   /v1/releases/active])` → **data wiring**; both new paths exist as
   mock-data.js keys, so the standalone mock package still boots. ✅
2. Live drain block (`startMigration`, 3 s poll of `/v1/migrations/current`
   into the confirm modal, progress bar, live-prefixes/in-flight/TTL
   counters, `Abort migration` button, mock-mode fallback caption) →
   **deviation #14**, matches the logged text point-for-point (source = the
   at-risk pool, target = first other pool from `/v1/pools`, model from
   `/v1/releases/active`, no key header, "mock mode — live drain
   unavailable" caption). New markup uses only package classes
   (`label`, `caption`, `num`, `btn`) and existing tokens (`--accent`,
   `--bg-inset`, `--fs-caption`, `--fs-label`, `--text-secondary`). ✅
3. `openConfirm` disarms `confirm-go` until the router reports `drained`;
   successful write POSTs `/v1/migrations/{id}/complete` → **deviation #14**
   ("gated write enabled ONLY when the migration reports drained … a
   successful write completes the migration"). ✅
4. Cancel/Escape/backdrop routed through `closeModal()` which aborts an
   in-flight migration → **deviation #14** ("Cancel/Escape/backdrop abort …
   the router is never left mid-migration"). ✅

### design/operate.html (2 hunks)
1. Migration progress strip below the hero, `display:none` by default →
   **deviation #15**. Composition audit: classes `card`, `pill`, `caption`,
   `num`, `dot` — all defined in the untouched `shell.css` (lines 108, 136,
   133, 25, 66); inline-style tokens `--s-2`, `--s-4`, `--bg-inset`,
   `--accent` — all defined in the untouched `tokens.css`. Inline style
   attributes are the package's established idiom (pre-existing sections use
   them). **No new classes, no new colors.** ✅
2. `pollMigration()` — 3 s poll through the `fetchJSON` seam, renders only
   for `migrating|drained`, hides otherwise (mock's `idle` keeps it hidden)
   → **deviation #15** / data wiring. ✅

### design/DESIGN.md (1 hunk)
- New section "Deviations — 2026-07-05 (KV-affinity graceful migration)"
  containing entries **#14** and **#15**, both dated 2026-07-05 via the
  section header, both describing exactly the diffs above. #14's
  "supersedes deviation 5" claim checks out: deviation 5 (KV-aware weighted
  drain `[roadmap]`) exists at DESIGN.md:152 and the drain is now `[built]`.
  #15's feed claim is implemented server-side in
  `services/router/router_app/devboard.py::feed_item` (migration_* → rows
  with req = migration id, pool = `source→target`, reason = event kind),
  matching the logged wording. ✅

**Unlogged visual changes: NONE.**

## 2. Serve check (port 8197 only)

Served via `cd services/router && INCIDENT_AGENT=0 python3 -m uvicorn
router_app.main:app --port 8197`; killed after checks. `/healthz` 200.

- **/board/manage** — 200. Served HTML is byte-identical to
  `design/manage.html` except the pre-existing serving seam (asset paths →
  `/board-assets/`, `live-fetch.js` injection, `data-live="true"`). Drain
  flow renders with the package's own components: `role="radiogroup"`
  (Drain style: graceful/immediate) present, confirm modal
  (`modal-backdrop`) present, mutate language present (`btn-mutate btn` on
  `confirm-go` with the `writes` chip). ✅
- **/board/operate** — 200, same seam-only delta (plus pre-existing
  `policy.html` → `/board/policy` link rewrite). Static breakage check:
  both inline scripts pass `node --check` (syntax clean); every
  `getElementById` target exists in the served HTML (the only dynamic one,
  `mig-abort`, is injected by `migStatusHTML` before it is wired); all five
  endpoints the pages fetch (`/v1/manage/options`, `/v1/pools`,
  `/v1/releases/active`, `/v1/migrations/current`,
  `/v1/placement/feed/snapshot`) return 200 JSON. No errors in server log. ✅
- **Standalone mock design/manage.html** — fallback path intact:
  `fetchJSON` resolves from `window.MOCK`, which now contains all three
  boot keys (`/v1/manage/options`, `/v1/pools`, `/v1/releases/active`), so
  the page renders; the raw `fetch("/v1/migrations", …)` in `startMigration`
  fails without a router, is caught, and — because `data-live` is unset —
  falls back to immediate-enable with the honest "mock mode — live drain
  unavailable, write not gated on DRAINED" caption. ✅

## 3. Progress strip class audit

Uses **existing package classes only**: `card`, `pill` (+ `data-status`
warn/ok states), `dot`, `caption`, `num`. Colors exclusively via existing
tokens (`--accent`, `--bg-inset`). No new CSS rules, no hex/oklch literals,
no new classes introduced anywhere in the diff. ✅

## Notes (non-blocking)

- manage.html's migration poll uses raw `fetch` for `/v1/migrations/current`
  instead of the `fetchJSON` seam (operate.html uses the seam). Deliberate —
  the drain flow is live-only by design and the mock fallback is the catch
  branch — but it is the one read in the package that bypasses the seam.
- A mid-poll network failure inside the `setInterval` callback would surface
  as an unhandled rejection (cosmetic console noise, not a render break).
