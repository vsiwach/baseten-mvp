# DESIGN.md — Inference Control demo board

Design package for the Baseten router control-plane demo. Two screens
(`devboard.html`, `deploy.html`), shared `tokens.css`, and `mock-data.js`
(the only file containing mock data — replace its fetchers with real ones
at integration time).

---

## 1. Layout system

### devboard.html — single fixed viewport (no scroll)
CSS grid, `100vh`, three rows:

```
┌──────────────────────────────────────────────────────────────┐
│ TOPBAR (52px): brand · nav · release · state chip · switcher │
├────────────────────┬────────────────────┬────────────────────┤
│ HERO (168px): TPOT p99 │ Blended $/Mtok │ MTTR (hero-hero)   │
├──────────┬─────────────────────────┬─────────────────────────┤
│ POOLS    │ PLACEMENT FEED          │ INCIDENT (flex 1.35)    │
│ (330px)  │ (1fr)                   │ LEARNING (flex 1)       │
└──────────┴─────────────────────────┴─────────────────────────┘
```

Tuned for 1512px laptop + external display; KPI numerals are 64px
(`--fs-hero`), incident MTTR 44px mono, minimum text 11px used only for
uppercase micro-labels.

### deploy.html — vertical timeline, scrollable
Centered 1180px column. Numbered failure nodes descend a gradient spine
(gray → green) ending in the LIVE node. Each card: status chip + stage +
timestamp + duration, monospace error block, agent diagnosis line (⬡),
citation pill linking the docs URL.

## 2. Tokens (tokens.css)
- Surfaces: `--bg #0a0e13`, `--panel #10151c`, `--panel-2`, `--panel-3`,
  strokes `--stroke/--stroke-hi`.
- Text: `--text`, `--text-2` (secondary), `--text-3` (labels).
- Accent: cyan `--accent #3fd8e4` (healthy/primary). Status: `--ok` green,
  `--warn` amber, `--danger` red, `--replay` violet.
- Type: system UI stack + system mono (`--font-ui`, `--font-mono`). No font
  files, no CDNs — fully offline.
- Shared primitives: `.panel`, `.chip-*`, `.btn`, `.label`, `.num`
  (tabular-nums mono), `rowIn`/`pulse` keyframes.

## 3. Component → endpoint mapping

### Topbar
| Element | Source |
|---|---|
| Release chip (model, stage, last_rollback) | `GET /v1/releases/active` |
| State chip HEALTHY/DEGRADING/LIVE INCIDENT/REPLAY | derived from telemetry (pool status + live incident + replay flag), never hard-set |
| "Inject chaos" button | `POST /v1/dev/chaos` (real fault injection) |
| "Replay recorded incident" button | replay playback of repo-shipped traces |

Both buttons disable outside HEALTHY so a run can't be double-triggered.

### Hero KPIs — `GET /v1/metrics/hero`
| Widget | Fields |
|---|---|
| TPOT p99 card | `tpot_p99_ms`, `tpot_slo_ms` (footer "voice SLO p99 < Xms" + computed headroom %), `tpot_delta_pct`, `spark.tpot` |
| Blended cost card | `cost_per_mtok_usd`, `cost_delta_pct` (vs single-pool baseline), `spark.cost` |
| MTTR card | `mttr_s`, `mttr_delta_pct`; footer renders the fixed agent-off baseline "never" (product fact, not a metric). During a live incident the card mirrors the live counter from `/v1/incidents` and turns red. |

TPOT value turns `--danger` when `tpot_p99_ms > tpot_slo_ms`.

### Pools panel — `GET /v1/metrics/slo` + `GET /v1/pools`
Per pool card: `id`, `status` chip (ok/warn/breach), `health` bar,
`util_pct` bar (joined by id from /v1/pools), TTFT + TPOT rows each with
`hist` (SVG bars from `edges`/`counts`) and `p50 / p95 / p99` (p99 bold;
red when above SLO).

**TTFT SLO source:** the contract's only 500ms bound is
`policy.probe_slo_ms` in `/v1/learning/episodes`; the pool footer "SLO of
record: TTFT p99 < 500ms" is rendered from that field. If you later add
`ttft_slo_ms` to `/v1/metrics/hero`, switch the read there
(`renderPools()` in devboard.html, `ttftSlo` const).

### Placement feed — `GET /v1/placement/feed` (SSE)
Columns map 1:1: `req`, `wl_tier` (chip; realtime = accent), `replica`
(spill replicas amber), `reason` (verbatim string from router), `ttft_ms`
(red > TTFT SLO), `decide_ms`. Newest row prepends with a slide-in;
capped at 14 rows. **No cost column** — the feed item shape has no cost
field; add `cost_usd` to the contract if you want it.

### Incident panel — `GET /v1/incidents` (index 0 = most recent)
| Element | Fields |
|---|---|
| Title line | `id`, `title` |
| Live/resolved chip | `live` |
| MTTR counter (44px) | `mttr_s` — counts up while `live:true`, freezes at resolution; red while live, then neutral |
| "agent-off baseline: never resolves" | fixed product fact |
| Phase bar detect→diagnose→resolve | `phase_ms.{detect,diagnose,resolve}`; segment widths ∝ duration; fill = elapsed vs cumulative offsets; red fill while live, green when resolved |
| Probe transcript | `actions[]` verbatim; rows prefixed ✓/✕/› by matching "probe passed"/"probe failed" |
| Footer | `agent:true` → "resolved by incident agent" badge; `postmortem_url` link |

While `live:true` the panel gains a red glow and every other panel dims to
72% opacity (`.board.dimmed`) — contained takeover, board stays legible.

### Learning panel — `GET /v1/learning/episodes` (index 0)
- Header: `episode_id`, `source`.
- Policy grid (5 cells): `breach_rate_threshold`, `probe_interval_s`,
  `probes_to_reinstate`, `probe_slo_ms`, `escalate_after_failures`.
- Probe list: `probes[].ok/ms`.
- Reward card: `reward.total` (accent, 24px) +
  `shaping.{resolved_bonus,mttr_penalty,escalation_penalty}` lines.
- Outcome chips: `outcome.{resolved,quarantined,escalated}`.

### deploy.html — static attempt JSON
Shape per attempt: `{attempt, ts, outcome:"failed"|"live", stage, error,
diagnosis, citation:{title,url}, duration_s}`. Rendered verbatim; the mock
attempts in `mock-data.js` are **placeholders — replace with the repo's
real 6-attempt capture** (marked in the file).

## 4. Interaction spec
| Control | What it calls | Effect |
|---|---|---|
| Inject chaos | `POST /v1/dev/chaos` | Real latency/error injection on baseten-l4. Board reacts purely via telemetry polling. |
| Replay recorded incident | replay engine (repo traces) | Identical visuals, state chip shows violet REPLAY prefix throughout. |
| Nav: Live Board / Deploy | page navigation | — |
| postmortem → | opens `postmortem_url` | — |
| Citation pills (deploy) | opens docs URL, new tab | — |

Polling cadence (mock mirrors intended integration): pools 2s, hero 3s,
learning 4s, incidents 250ms (for smooth live MTTR/phase bar), feed = SSE
push.

## 5. Four-state behavior matrix
| Element | HEALTHY | DEGRADING | LIVE INCIDENT | REPLAY |
|---|---|---|---|---|
| State chip | green Healthy | amber Degrading | red Live incident (pulse) | violet Replay · <phase> (pulse) |
| Hero TPOT | white, headroom % | value rises; red if > SLO | red if > SLO | as recorded |
| Hero MTTR | last incident, cyan | unchanged | red, counts live, label "INC-xxxx — resolving" | same, violet chip context |
| Pools | both ok | baseten-l4 warn, health drops, p99 red | baseten-l4 breach, util → ~12 (quarantined) | as recorded |
| Feed | affinity/cost placements | mixed, slow TTFT rows red | all `model-api-spill` / `quarantine_spill` amber | as recorded |
| Incident panel | last resolved, green phases | unchanged | red glow, phases fill live, actions stream in, board dims | identical to live |
| Learning | latest episode | unchanged | unchanged | unchanged |
| Buttons | both enabled | disabled | disabled | disabled |

State is **always derived**: chip = REPLAY if replay flag, else LIVE
INCIDENT if `incidents[0].live`, else DEGRADING if any pool status ≠ ok,
else HEALTHY.

## 6. Integration notes
- All screen code consumes `window.MockAPI` only. Swap each `get*` for a
  real `fetch()` and `subscribeFeed` for an `EventSource` — render code
  reads contract fields verbatim, no reshaping.
- Mock values are cloned per call (`JSON.parse(JSON.stringify(...))`), so
  render code never mutates shared state.
- Nothing else in the package contains data. If it isn't in the contract,
  it isn't on the board.
