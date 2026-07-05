# SLO-AUDITOR verdict — KV-migration (evals/migration/EVIDENCE.md)

**Verdict: PASS** (audited 2026-07-05, local recomputation only — no network, no keys, per task scope)

## Commands run

```
python3 <independent recompute script>   # csv.DictReader over the raw per-request CSVs;
                                         # reimplemented cohort logic from scratch, incl.
                                         # the repo's nearest-rank _pctl percentile
cat benchmarks/raw/migration_drills.csv
cat benchmarks/raw/migration_timeline_{graceful_20260705-141129,immediate_20260705-141351}.csv
awk -F, 'NR>1{print $10}' benchmarks/raw/migration_graceful_20260705-135629.csv | sort | uniq -c   # run-1 token spot check
awk -F, '$6=="migration_target"{print $5}' <both final CSVs> | sort | uniq -c                       # steer target check
cd services/router && python3 -m pytest tests -q                # 174 passed
cd services/router && python3 -m pytest tests/test_migration.py -q   # 25 passed
```

Cohort definition applied (matches tools/chaos.py `_migrate_record`, lines ~550–570):
sessions with ≥1 warmup-phase request served by `baseten-l4` (source); live = phases
`during` + `drained`; percentiles = repo's nearest-rank `_pctl`; TTFT = client_ttft_ms.
No session appeared on both replicas during warmup in either run, so the cohort is
unambiguous.

## Regenerated vs displayed

| metric | displayed (EVIDENCE.md / migration_drills.csv) | regenerated | match |
|---|---|---|---|
| graceful cohort sessions | 5 | 5 (sids 3,5,6,9,10) | exact |
| graceful mid-conv re-prefills | 0 | 0 | exact |
| graceful cohort TTFT p95 | 70.2 ms | 70.2 ms | exact |
| graceful hit TTFT p50 | 51.3 ms | 51.3 ms | exact |
| graceful miss TTFT p50 | — (none) | no cohort-live misses | exact |
| graceful drained_s | 105.7 s (CSV 105.71) | 105.71 s (timeline CSV) | exact (0.1 s display rounding) |
| graceful cohort on source | 100% | 174/174 on baseten-l4, all `affinity_warm` | exact |
| graceful requests / errors | 441 / 1 | 441 / 1 | exact |
| graceful re_prefill / new_first (drills.csv) | 5 / 2 | 5 / 2 | exact |
| graceful after-probes missed | 12/12 | 12 probes, 12 miss | exact |
| immediate cohort sessions | 6 | 6 (sids 0,3,5,6,9,10) | exact |
| immediate mid-conv re-prefills | 6 (every session) | 6, exactly 1 per session | exact |
| immediate cohort TTFT p95 | 293.3 ms (4.2×) | 293.3 ms; 293.3/70.2 = 4.18 | exact |
| immediate hit TTFT p50 | 56.1 ms | 56.1 ms | exact |
| immediate forced-miss TTFT p50 | 293.3 ms (5.2× a hit) | 293.3 ms; /56.1 = 5.23 | exact |
| immediate drained_s | 21.1 s (CSV 21.14) | 21.14 s (timeline CSV) | exact |
| immediate cohort forced to target | 98% | 54/55 = 98.2% | exact |
| immediate requests / errors | 201 / 0 | 201 / 0 | exact |
| drain trade "~5× longer" | ~5× | 105.71 / 21.14 = 5.00× | exact |

Tolerance: none needed — everything was recomputed from the same committed CSVs the
claims cite, so counts, percentiles, and dollar-free ratios matched exactly; only
display rounding (0.1 ms / 0.1 s / one-decimal ratios) applies.

## Code-vs-summary checks
- tools/chaos.py cohort logic computes exactly what EVIDENCE.md says: `src_homed`
  = warmup rows on `args.source`; cohort live = during+drained; re-prefill split
  (`re_prefill_count` vs `new_session_first_prefills`) present as described.
  My independent reimplementation reproduced every drills.csv column.
- policy.py Layer-0 pre-filter (lines ~114–177): steers only when the migration
  is active AND `not kvstate.holds(migration.source, prefix)` AND
  `takes_target(prefix)` (deterministic hash-weighted ramp) — warm-KV exemption
  as claimed; route reasons `migration_target` / `affinity_warm` emitted.
- migration.py: pure state machine MIGRATING→DRAINED→COMPLETED, abort from any
  active state, `MigrationConflict` (→409) on double-start and on complete from
  any state but DRAINED; immediate-mode quarantine side effect explicitly kept in
  main.py. Matches EVIDENCE.md mechanism bullets.
- All 191 `migration_target`-steered graceful rows and all 91 immediate rows
  landed on vllm-l4 (the target); timeline `routed target_new=191` matches.
- Tests: 174 router suite green; test_migration.py = 25 tests, all pass.

## Iteration-note check
- Superseded runs exist on disk: 135629/135849 (run 1), 140132/140355 (run 2).
- Run-1 spot check: prompt_tokens = 35/36 across 445 rows — consistent with the
  claimed 32-token prefix (+ "turn N" suffix). Run 2 already at 515/516.
- Nit (not a finding against any number): the evidence glob
  `migration_*_20260705-1356*/1401*/1403*` does not cover the run-1 immediate
  file `migration_immediate_20260705-135849.csv`, which nonetheless exists and
  is kept. Also, migration_drills.csv contains only the two final rows (the
  pre-counter-split summary rows are gone); the raw per-request CSVs for the
  superseded runs are what remain, which is what the note claims.

## Unreproducible claims found
None. Every displayed number traced to a committed CSV and recomputed exactly.

## Scope
Sim-stack relative deltas only, as the evidence itself scopes ("Cannot claim"
section is accurate). Live-pool confirmation not run (no network/keys — per
task). Voice-tier SLO thresholds not implicated by this feature's evidence;
no hard-coded SLO numbers appear in the migration surfaces audited.
