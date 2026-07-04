# Reliability Console — design system & integration map

Original light developer-infra aesthetic (not Baseten's brand): warm stone
neutrals, muted spruce green accent, system sans + system mono, thin
small-multiple SVG charts. Vanilla HTML/CSS/JS, no build step, no external
fonts or CDNs.

## Files

| File | Role |
|---|---|
| `tokens.css` | All design tokens (colors, type, spacing, radius, shadows) |
| `shell.css` | Shared shell (top bar, tabs, state chip) + component library |
| `console.js` | Shell render, `fetchJSON()` integration seam, SVG chart helpers, formatters, state derivation |
| `mock-data.js` | `window.MOCK` keyed by endpoint path, mirroring the contract 1:1 |
| `operate/deploy/policy/manage/roadmap.html` | The five screens |

**Integration:** replace the body of `fetchJSON(path)` in `console.js` with a
real `fetch(path)`. Everything else reads through it. The mock keys are the
literal endpoint paths.

## Tokens

- **Neutrals (warm stone, oklch hue ~85):** `--bg-page` (near-white page),
  `--bg-surface` (white cards), `--bg-inset` (wells/table heads), `--border`
  (hairline), `--text` / `--text-secondary` / `--text-muted` / `--text-faint`.
- **Accent:** `--accent` = `oklch(0.56 0.105 158)` (muted spruce, ≈ #2e8b62),
  with `--accent-strong/-bg/-border`. Used for primary/positive/selected.
- **Semantic status:** `--ok` (= accent), `--warn` (muted amber), `--bad`
  (muted red), each with `-bg/-border/-text` companions.
- **Percentile series (shared L/C, hue varies):** `--p50` blue, `--p90` green,
  `--p95` amber, `--p99` red.
- **Type:** `--font-sans` (system stack), `--font-mono` (system mono; ALL
  numbers, IDs, latencies, config values, log lines use `.num`/`.mono` with
  tabular numerals). Sizes `--fs-caption` 11 → `--fs-kpi-xl` 56 (MTTR).
- **Spacing:** 4px scale `--s-1…--s-10`. **Radius:** 4/6/8/pill.

## Board states (derived, never hard-coded)

`deriveState(incidents, sloPools, replay)` in `console.js`:

| State | Condition | Chip |
|---|---|---|
| HEALTHY | no live incident, no warn/bad pools | green |
| DEGRADING | any pool `status:"warn"` | amber |
| LIVE INCIDENT | any incident `live:true` or pool `"bad"` | red, pulsing dot |
| REPLAY | replay flag (recorded trace) | gray, labeled honestly |

The chip lives in the top bar on every screen (`role="status"`).

## Read-only vs mutating visual language

- **Read-only** actions: `.btn` — outlined, white background. Navigation and
  inspection only.
- **Mutating** actions: `.btn-mutate` — solid green, bold, and carry an inline
  `writes` badge. `.btn-danger` (solid red) for destructive drain.
- Every mutation goes through a **confirm modal** that states the exact
  mutation (`mutation_preview` rendered verbatim in `pre.code`) plus the drain
  plan. Nothing writes on first click.
- Mutation previews and config diffs use `pre.code` (inset gray well, mono).

## Cold-start / low-sample treatment

`p99Qualifier(metric)` in `console.js`: if the histogram sample
(`sum(hist.counts)`) < 50, or `p99 > 20 × p95`, the p99 renders in **amber**
(not red) with a `.qualifier` chip: `includes cold start · low sample (n=…)`.
See `interactive-h100-us-east` in the mock (p99 91.2s, n=14).

## Component → endpoint map

### Operate
| Component | Source |
|---|---|
| TPOT p99 KPI + slo line + delta + sparkline | `/v1/metrics/hero` → `tpot_p99_ms`, `tpot_slo_ms`, `tpot_delta_pct`, `spark.tpot` |
| Cost/Mtok KPI + delta + sparkline | `hero.cost_per_mtok_usd`, `cost_delta_pct`, `spark.cost` |
| MTTR KPI (56px, accent) | `hero.mttr_s`, `mttr_delta_pct` |
| Pool small multiples (pills, p50/p95/p99, histograms, SLO dash marker) | `/v1/metrics/slo` → `pools[].{id,tier,slo,health,status,ttft,tpot}` |
| Pool util | `/v1/pools` → `pools[].util_pct` joined on `id` |
| Placement feed (streaming rows, spill reasons amber) | `/v1/placement/feed` → `{req,tier,pool,reason,ttft_ms,decide_ms}` |
| Incident card: phase bar (detect/diagnose/resolve), transcript, MTTR | `/v1/incidents[0]` → `phase_ms`, `actions`, `mttr_s`, `postmortem_url` |
| Policy summary | `/v1/learning/policy-eval` → `holdout.{default,proposed}.mttr_p50` |
| Release in top bar | `/v1/releases/active.version` |

### Deploy
| Timeline (attempts → live, annotated) | `/v1/releases/timeline` (proposed shape) |
| Active release panel | `/v1/releases/active` → `{version,strategy,model}` |

### Policy
| Config diff table (7 scalars, changed rows tinted) | `policy-eval.default_config` vs `proposed_config` |
| Held-out eval (MTTR p50 arrow, escalations, probes, trade-off line) | `policy-eval.holdout` |
| Reward curve | `policy-eval.reward_curve` |
| Governed promote (ack checkbox → confirm modal → "awaiting approver") | writes `proposed_config` |

### Manage
| At-risk pool header + risk line | `/v1/manage/options.pools[]` |
| Three option cards (fleet/model/spill) with consequences + mutation preview | `options[].{kind,label,consequence_text,mutation_preview}` |
| Drain radiogroup + step list (graceful/immediate) | `drain.{modes,steps}` |
| Confirm modal | states exact mutation + drain plan |

### Roadmap
| Findings table | `/v1/roadmap` (static content shape) |

## Contract notes (honest deviations)

1. **`pools[].tier` + `pools[].slo`** added to `/v1/metrics/slo` so the SLO of
   record renders from data (voice p99<500ms/TPOT<60ms, interactive p99<800ms)
   instead of being hard-coded. This is the one proposed contract addition.
2. `/v1/manage/options` and `/v1/releases/timeline` are **designed shapes**
   (the brief asked for them); `/v1/roadmap` is static content.
3. `/v1/pools` carries `gpus`/`region` as display extras under the `…` in the
   contract's pool shape.

## Accessibility

- All charts are `role="img"` with labels; state chip is `role="status"`;
  drain choice is a real radiogroup; tabs use `aria-current="page"`.
- Option cards are buttons with `aria-pressed`; modals close on Escape and
  backdrop click; `prefers-reduced-motion` disables all animation.
- Text contrast ≥ 4.5:1 on all body text; muted colors reserved for
  captions ≥ 11px.

## Scale

Designed against 1512px laptop width (page max 1460px, fluid below). Hero
numbers 40–56px mono; the MTTR figure and incident phase bar are the largest
elements on the board by design.
