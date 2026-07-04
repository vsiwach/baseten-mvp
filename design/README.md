# Handoff: Reliability Console restyle (light infra aesthetic)

## Overview
A visual reskin of an existing per-workload reliability console for
dedicated-inference customers. The current build is a dark "mission-control"
board; this handoff replaces it with a light, calm, developer-infra aesthetic
(warm stone neutrals, muted spruce green accent, monospace data, thin
small-multiple SVG charts). Five tabs: Operate, Deploy, Policy, Manage,
Roadmap, sharing one shell (top bar + tab nav + board-state chip).

This is an **original** aesthetic, not any company's brand tokens.

## About the design files
The bundled files are **design references created in HTML** — working
prototypes showing intended look and behavior. Because the brief was an
import-ready reskin (vanilla HTML/CSS/JS, no build step, no external fonts or
CDNs), they are unusually close to production-usable: your task in the target
codebase is to **recreate/port these designs into the existing board's
environment and component structure** — this is a reskin, so keep the existing
component tree and data bindings, and apply this markup + CSS. Do not rewrite
board logic. If the target board is React/Vue, translate the templates into
the existing components; the CSS transfers as-is.

## Fidelity
**High-fidelity.** Colors, type, spacing, radii, chart treatments, and copy
are final. Recreate pixel-perfectly; all values are tokens in `tokens.css`.

## Files
- `tokens.css` — all design tokens (colors as oklch, type, spacing, radius, shadows, focus ring)
- `shell.css` — shared shell + component library (top bar, tabs, state chip, cards, pills, buttons, tables, code wells, modal, feed animation, responsive rules)
- `console.js` — shell renderer, `fetchJSON()` integration seam, formatters, board-state derivation, inline-SVG chart helpers (sparkline, histogram, line chart, percentile row)
- `mock-data.js` — `window.MOCK` keyed by endpoint path, mirroring the API contract 1:1
- `operate.html`, `deploy.html`, `policy.html`, `manage.html`, `roadmap.html` — the five screens
- `DESIGN.md` — token system, component→endpoint map, board-state behavior, read-only-vs-mutating language, cold-start treatment. **Read this alongside the README; it is the spec of record for data bindings.**

## Integration seam
`fetchJSON(path)` in `console.js` is the single seam: replace its body with
`return (await fetch(path)).json()`. Mock keys are the literal endpoint paths.
One proposed contract addition: `pools[].tier` + `pools[].slo` on
`/v1/metrics/slo` so the SLO of record renders from data (never hard-coded).
`/v1/manage/options` and `/v1/releases/timeline` are designed shapes.

## Screens / views

### Operate (default)
- **Purpose**: live ops board.
- **Layout**: page max-width 1460px, 24px padding. Row 1: hero grid
  `1fr 1fr 1.2fr`, 16px gap. Row 2: `.split` grid `minmax(0,1.7fr) minmax(0,1fr)`.
  Left column: Pools card, Last-incident card. Right: Placement feed, Control
  policy summary. `.split` stacks to one column ≤1180px; hero stacks ≤900px.
- **Hero KPIs**: label (11px uppercase, muted) + delta chip top row; 40px mono
  number (`letter-spacing:-0.02em`), sparkline right-aligned (160×36, 1.5px
  stroke). MTTR card: 56px mono number in accent-strong, accent border, subtle
  accent-bg gradient from bottom — the emotional core, legible from 2 m.
- **Pools**: one row per pool, grid `200px 1fr 1fr`, hairline divider between
  (none on last). Left: status pill, mono pool id (13px, 600), tier/util/health
  caption, SLO-of-record caption. Middle/right: TTFT and TPOT small multiples —
  p50/p95/p99 values (mono 14px) with 11px mono labels colored by series
  (`--p50` blue, `--p95` amber, `--p99` red), histogram (220×44, faint gray
  bars, 1px dashed amber SLO marker).
- **Cold-start treatment**: if histogram n < 50 or p99 > 20×p95, p99 renders
  amber (not red) with an amber mono chip: `includes cold start · low sample (n=…)`.
- **Placement feed**: table, newest row prepended with a 0.25s fade/slide-in,
  max 8 rows, 900–2300ms random cadence; Pause/Resume button (aria-pressed).
  Spill reasons in amber text.
- **Incident card**: title + `MTTR 42s` (16px mono, accent); phase bar — three
  flex segments proportional to `phase_ms` (detect blue / diagnose amber /
  resolve green), 8px tall, 3px radius, captions under each; agent transcript
  in a scrolling `pre.code` well; postmortem link.
- **Policy summary**: `61.0s → 42.5s` mono line with green delta chip, caption,
  link to Policy tab.

### Deploy
- Two-column `.split` (`2fr / 1fr`). Left: vertical timeline `<ol>` — 12px
  outcome-colored dot (filled when live) + 1px connector line; each entry:
  "Attempt n — stage" (14px, 600), outcome pill (rolled back = red,
  passed/live = green), mono timestamp, annotation paragraph (secondary text,
  max 64ch). Right: active-release `<dl>` (mono values) + rollback note.

### Policy
- Two-column `.split` (`1.5fr / 1fr`). Left: config diff table (7 scalars) —
  changed rows tinted `--accent-bg`, proposed value bold, green % change chip,
  "unchanged" caption otherwise; reward-curve card (inline SVG line, 1.5px
  accent stroke, baseline hairline, iteration captions).
- Right: held-out eval card — centered 40px mono `61.0s → 42.5s` with green
  delta, 3-row compare table, trade-off caption; governed-promote card
  (accent border): explainer, ack checkbox gating the button, then confirm
  modal showing the exact mutation JSON; after confirm the button reads
  "Promotion requested — awaiting approver" and disables.

### Manage
- One card per at-risk pool. Head: pool id (mono), status pill, risk line.
- Body: 3 option cards (`repeat(3,1fr)`) — buttons with `aria-pressed`;
  kind label (uppercase 11px), title (14px 600), consequence paragraph
  (secondary), `mutation_preview` verbatim in a `pre.code` well. Selected =
  accent border + accent-bg.
- Footer strip: drain radiogroup (graceful/immediate; immediate carries a red
  "errors clients" pill) + numbered step list that re-renders per mode +
  "Review & apply" mutating button (disabled until an option is selected;
  caption shows "1 mutation staged").
- Confirm modal: plain-language summary, exact mutation in `pre.code`, drain
  plan list. Nothing writes on first click.

### Roadmap
- Single card, findings table: rank (mono muted), title (600), detail
  (secondary, max 56ch), impact word colored (high = accent, medium = amber),
  effort caption, status (ready = green pill, in review = amber pill,
  proposed = caption).

## Interactions & behavior
- **Board-state chip** (top bar, every screen, `role="status"`): derived by
  `deriveState()` — REPLAY flag → gray "replay"; any `incidents[].live` or
  pool `bad` → red "live incident" (pulsing dot, 1.4s); any pool `warn` →
  amber "degrading"; else green "healthy". Never hard-code the state.
- **Read-only vs mutating**: `.btn` outlined = read/navigate; `.btn-mutate`
  solid green + inline `WRITES` badge = mutation; `.btn-danger` solid red.
  Every mutation → confirm modal stating the exact request body. Modals close
  on Escape and backdrop click.
- Tabs: plain links with `aria-current="page"`, 2px accent underline.
- Feed animation and pulse respect `prefers-reduced-motion`.
- Delta chips: ≤0 renders green with ▾ (improvement for latency/cost/MTTR),
  >0 amber with ▴.

## State management
Prototypes are stateless renders from fetched JSON except: feed (paused flag,
row index), policy promote (ack → enabled → requested), manage (selected
option, drain mode, modal open). Map to your framework's local state.

## Design tokens (spec of record: tokens.css)
- Page `oklch(0.977 0.004 85)`; cards `#fff`; inset `oklch(0.962 0.004 85)`;
  border `oklch(0.905 0.006 85)`.
- Text: `oklch(0.245 0.008 70)` / secondary 0.45 / muted 0.60 / faint 0.72.
- Accent `oklch(0.56 0.105 158)` ≈ `#2e8b62`; strong 0.48; bg 0.965; border 0.87.
- warn `oklch(0.62 0.115 75)`, bad `oklch(0.55 0.150 27)`, each with
  bg/border/text companions; percentiles p50 blue 245 / p95 amber 75 /
  p99 red 27 hue at matched L/C.
- Type: system sans stack; system mono for ALL numbers/IDs/latencies/config
  (tabular-nums). Sizes 11/12/13/14/16 + KPI 40/56.
- Spacing 4px scale (4–40); radius 4/6/8/pill; shadows barely-there; focus
  ring = 2px white + 2px accent.

## Assets
None. No images, icon fonts, or external resources; all charts are inline SVG
generated from data. The brand mark in the top bar is a placeholder 18px
accent-colored rounded square — replace with the real product mark.

## Accessibility requirements
Charts `role="img"` + labels; chip `role="status"`; real radiogroups;
`aria-pressed` on toggle/option buttons; Escape closes modals; contrast
≥4.5:1 body text; reduced-motion honored; sentence case; no emoji.
