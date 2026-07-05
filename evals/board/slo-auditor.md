# SLO-AUDITOR — Phase C board integration (blocking audit)

Date: 2026-07-05
Scope: every cost/latency/count the NEW board surfaces traces to a real source
or is labeled an estimate. Phase B policy-eval math previously audited PASS —
this audit checks only faithful rendering.

## VERDICT: PASS

Served live for the audit: `INCIDENT_AGENT=0 python3 -m uvicorn
router_app.main:app --port 8195` (cwd services/router; killed after; no other
ports touched; no network, no keys — pools unreachable, which also exercised
the honest-absence paths).

Commands run:
- `curl http://127.0.0.1:8195/v1/manage/options` / `/v1/pools` / `/v1/metrics/slo`
- `curl http://127.0.0.1:8195/v1/learning/policy-eval` and `?raw=1`
- `curl http://127.0.0.1:8195/v1/releases/timeline`
- Python diffs of each payload against `learning/policy-eval.json`,
  `demo/deploy-timeline.json`, `deploy/baseten/model-apis.json`,
  `configs/routing-policy.yaml`, `configs/inference-registry.yaml`.

## 1. MANAGE consequence lines (services/router/router_app/manage_options.py)

| Displayed | Regenerated / source | Match |
|---|---|---|
| "+$0.90/hr per T4 replica while active (Baseten pricing)" | README.md:32 "$0.90/hr while up"; deploy/LIVE_SETUP.md:8 "T4x8x32 ($0.01504/min ≈ $0.90/hr)"; LIVE_SETUP.md:18 `BASETEN_USD_PER_HOUR=0.90` | exact |
| "~148 s measured cold start (docs/FRICTION_LOG.md #17)" | FRICTION_LOG.md #17: measured **148.2 s** (deployment qvm1v4e logs), cited in-string; "~" + integer round of a measured value | exact (rounded, cited) |
| Spill price "openai/gpt-oss-120b at $0.1/M prompt · $0.5/M completion (deploy/baseten/model-apis.json)" | catalog (fetched_at 2026-07-02T19:11:03Z): gpt-oss-120b 0.1/0.5 IS min by usd_per_1m_completion — matches mux.py:153 default-selection rule | exact |
| "final attempt reached live in 344 s; full attempt trail 2579 s across 7 attempts" | deploy-timeline.json: last duration_s=344; 41+388+512+496+611+187+344 = **2579**; 7 attempts | exact |
| "max_replica 2 → 3" | configs/inference-registry.yaml qwen3-8b `max_replicas: 2` | exact |
| drain "timeout 30 s" | matches the real drain endpoint default (`timeout_s: float = Query(default=30.0)`) | exact |

Estimate-labeling paths verified in code: missing timeline → "duration:
estimate — no recorded timeline"; missing catalog → "per-token prices
unavailable (catalog snapshot missing)". Spill card (post staff-skeptic copy)
contains no numeric claim without a source — its only numbers are the cited
catalog prices. Option cards are gated on real Baseten ids
(model_id 3ydn1e43 / deployment_id qvm1v4e from routing-policy.yaml);
pools without ids get no card. No violations.

## 2. Risk lines — live snapshots, honest absence

Served with zero traffic: `"util 0%; TPOT p95 trend n/a (insufficient
samples); 0 spill placements in last 5m"`. util_pct comes from
pools_snapshot (kvstate.pending / affinity capacity), TPOT trend from a
MetricsWindow 900 s slice (None below 6 samples → "n/a", never a number),
spill count from route events over SPILL_WINDOW_S=300 s ("last 5m" label
matches the constant; trend label "15m" matches the 900 s window). No
hard-coded fake fallbacks anywhere in the builder — missing data renders as
n/a / 0-with-empty-state, not invented values.

## 3. POLICY screen binding — /v1/learning/policy-eval

Adapter output vs learning/policy-eval.json (exact-match tolerance — same
file, zero drift allowed):

| Field | File | Served | Match |
|---|---|---|---|
| holdout default mttr_mean_s | 8.05 | 8.05 | exact |
| holdout proposed mttr_mean_s | 2.005 | 2.005 | exact |
| probes default/proposed | 24 / 12 | 24 / 12 | exact |
| escalations, unresolved | 0/0, 0/0 | 0/0, 0/0 | exact |
| reward_curve | 81 entries | 81 floats, file order, values identical | exact |
| episodes total/taped/excluded | 110 / 25 / 85 | 110 / 25 / 85 | exact |
| caveats | 10 | 10, verbatim | exact |
| generated_at, corpus_sha256, configs | — | identical | exact |

`?raw=1` is byte-identical to the file **except one injected key
`"available": true`** (main.py:908). No numeric alteration; note that the
docstring says "untouched", which is slightly inaccurate. Non-blocking.

## 4. Timeline adapter — /v1/releases/timeline

All 7 attempts map 1:1 (n/at/stage/outcome from the artifact; note =
error + " — " + diagnosis, both real strings). version/strategy/tier_target
are **null** and the payload's `source` string states "were not recorded —
null, not invented". Citations are dropped (omission, not invention). No
invented fields.

## 5. SLO lines on operate — /v1/metrics/slo

Served payload: both pools carry `tier: "interactive"`, `slo: {ttft_p99_ms:
800, tpot_p99_ms: 60}` = configs/routing-policy.yaml `interactive:
{ttft_ms: 800, tpot_ms: 60}` (qwen3-8b registry tier = interactive; voice
tier in YAML is realtime 500/60 per mission). devboard.py contains no SLO
constants — values flow through the `tier_rules` parameter from
`state.policy["tiers"]` (YAML); missing rules default to 0 (honest absence).
design/operate.html renders `p.slo.ttft_p99_ms` / `p.slo.tpot_p99_ms` from
the payload, no literals.

## Notes (non-blocking)

1. main.py:978 `metrics_hero`: fallback `tpot_slo = 60` when no board model
   is configured. Coincides with the YAML value and only fires with no model
   context; still a constant in API glue — recommend reading the realtime
   tier default instead.
2. console-live/index.html:150-151 hard-codes `BUDGET_VOICE_MS = 500` /
   `BUDGET_INTERACTIVE_MS = 800`. That is the Phase A standalone console
   (talks to Baseten's public API through a proxy; no router policy endpoint
   available to it), not the Phase C board — out of scope here, but it is a
   hard-coded SLO in UI code and should be fed from config if that console
   ever gains a policy source.
3. design/live-fetch.js falls back to window.MOCK on endpoint failure but
   visibly labels it ("some panels: sample data (endpoint pending)") — honest,
   though the label is board-global, not per-panel.

Tolerance applied: exact match for every value (all sources are committed
files read by the server, not re-measured benchmarks — run-to-run noise does
not apply; 148 vs 148.2 accepted because the string is "~148 s" with the
measured source cited in-line).
