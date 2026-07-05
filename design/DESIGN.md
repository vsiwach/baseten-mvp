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

## Deviations — 2026-07-04 (Phase C live integration)

The package is now served live by the router at `/board/{page}` with
`live-fetch.js` layered over `console.js` (no restyling; `fetchJSON` is the
seam, exactly as designed). Deviations from the original mock contract:

1. **`mttr_p50` → `mttr_mean_s`, label "MTTR p50" → "MTTR mean"**
   (policy.html holdout panel + operate.html policy summary). The Phase-B
   offline eval reports MTTR *means* over the holdout replay set, not p50s
   — the board must not relabel a mean as a percentile.
2. **`pools[].tier` + `pools[].slo` shipped** on `/v1/metrics/slo` (the one
   contract addition already proposed above) — values come from the routing
   policy's tier rules, config-driven, never hard-coded.
3. **Placement feed is a snapshot, not SSE, on the board**: `live-fetch.js`
   maps `/v1/placement/feed` → `/v1/placement/feed/snapshot` (last 30
   decisions from the same event ring the SSE feed tails). The SSE endpoint
   is unchanged for the devboard.
4. **Real mutation previews** in `/v1/manage/options`: the mock's
   illustrative `/v1/pools/*` mutations are replaced by the real Baseten
   management-API calls with real ids (model `3ydn1e43`, deployment
   `qvm1v4e`) — fleet = `autoscaling_settings` PATCH, model = `promote`
   POST, spill = re-`POST /v1/policy/placement` (the no-op default choice).
   Consequences cite measured sources ($0.90/hr T4; 148 s cold start per
   docs/FRICTION_LOG.md #17; $/Mtok per deploy/baseten/model-apis.json).
5. **Drain steps labeled `[built]` / `[roadmap]`**: built = sticky
   placement exclusion + in-flight-count wait (`POST /v1/pools/{id}/drain`);
   the mock's "migrate KV caches" weighted, KV-aware drain wording remains
   as a `[roadmap]` step — it is not implemented and is not claimed to be.
6. **`/v1/roadmap` stays the authored mock** (static product findings, per
   the original contract note).
7. **Writes are router-only** (not console-live) and **off by default**:
   every `/v1/writes/*` returns 403 `{"error":"writes disabled"}` unless
   `CONSOLE_ALLOW_WRITES=1`. The confirm modals render that 403 verbatim —
   the visible refusal IS the designed default state, not an error state.
8. **deploy.html**: added a `failed` outcome style (the real recorded
   timeline has `failed` attempts, not `rolled_back`) and `?? "—"` guards
   for `version`/`strategy`/`tier_target`, which the recorded artifact
   never captured (the adapter returns null rather than inventing them).
9. **policy.html**: empty-`reward_curve` guard ("no reward curve in this
   corpus yet") and zero-MTTR guard — the live corpus has no taped episodes
   yet and must render honestly instead of crashing.
10. **operate.html**: honest empty states for live systems with no history —
    "No incidents recorded on this workload yet" when `/v1/incidents` is
    `[]` (the mock always had one) and "no placement decisions recorded
    yet" when the feed snapshot is empty. Showing the mock's incident on a
    healthy live board would be fabricated data.
11. **mock-data.js** (2026-07-05): policy-eval holdout keys renamed
    `mttr_p50` → `mttr_mean_s` to match deviation #1's relabel — the screens
    read the new key, so the mock (standalone package and live-fallback path)
    must ship it or the script throws mid-render.
12. **live-fetch.js fallback badge** (2026-07-05): when a live endpoint
    fails and a panel falls back to mock data, a fixed caption
    "some panels: sample data (endpoint pending)" is appended to the body.
    Not a package component; added so fallback data is never silently
    presented as live (provenance rule). Uses the package's caption type
    scale only.

## Deviation — 2026-07-05 (STAFF-SKEPTIC Phase C gate)

13. **Spill card copy corrected**: the spill option no longer claims
    "placement already spills overflow". With prefix affinity enabled the
    Model-API replica is a consistent-hash *peer* of the dedicated pool
    (`policy.py` rings over all candidates), so it takes a hash share of new
    prefixes in steady state — off-pool placement is not overflow-only, and
    the risk line's "spill placements" counts all off-pool placements
    (steady-state hash share + quarantine/capacity spill alike). The card now
    says so, and labels overflow-only spill (dedicated-first with per-token
    fallback) as roadmap. Also noted: the spill card's no-op mutation preview
    re-POSTs the placement policy, but the spill behavior itself comes from
    the endpoint list (a replica without a `pool` key bypasses placement
    filtering), not from that policy document.

## Deviations — 2026-07-05 (KV-affinity graceful migration)

14. **Manage drain flow is LIVE** (manage.html): the drain radio's Apply
    flow now starts a real KV-affinity migration — `POST /v1/migrations`
    (router-local fetch, no key header; source = the at-risk pool, target =
    the first other pool from `/v1/pools`, model from
    `/v1/releases/active`) — and polls `/v1/migrations/current` every 3 s
    INTO the confirm modal: live prefixes remaining, in-flight, TTL horizon
    and a progress bar, with an **Abort migration** button. The gated write
    (promote/autoscaling through the existing two-step handshake) is
    enabled ONLY when the migration reports `drained`, and a successful
    write completes the migration (`POST /v1/migrations/{id}/complete`).
    Cancel/Escape/backdrop abort an in-flight migration so the router is
    never left mid-migration. In the standalone mock package (no router)
    the migration POST fails and the modal falls back to the previous
    immediate-enable behavior with an honest "mock mode — live drain
    unavailable" caption. This supersedes deviation 5: the KV-aware
    weighted drain is now `[built]` in `/v1/manage/options` (with the
    weighted ramp); only proactive KV transfer before detach remains
    `[roadmap]`.

15. **Migration visibility on Operate** (operate.html + mock-data.js +
    live-fetch.js + the feed): a thin migration progress strip below the
    hero — existing `card`/`pill`/`caption`/`num` classes and token colors
    only — polls `/v1/migrations/current` every 3 s and renders only while
    a migration is active (source → target, mode, live prefixes, in-flight,
    TTL horizon, routed counters, progress bar). `migration_*` lifecycle
    events are mapped into placement-feed rows (req = migration id,
    pool = `source→target`, reason = the event kind), so the drain
    narrative appears inline in the feed. mock-data.js gains a
    `"/v1/migrations/current": {state: "idle"}` key and live-fetch.js adds
    the path to its LIVE set, so both screens keep reading through the
    `fetchJSON` seam in both modes.
