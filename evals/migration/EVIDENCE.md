# KV-affinity graceful migration — evidence (2026-07-05)

Claim (scoped): in the real router's placement path, exercised on the sim
stack (relative deltas, modeled economics — see Cannot-claim), a KV-aware
graceful migration moves a workload between pools with **zero
mid-conversation prefill recomputes** for the sessions being migrated, while
an immediate cutover forces **every** migrating session to recompute its
prefix mid-conversation with a ~5× TTFT spike.

## Mechanism (built, tested)
- services/router/router_app/migration.py — pure state machine
  (IDLE→MIGRATING→DRAINED→COMPLETED; abort anytime pre-complete; 409 on
  double-start/premature complete; immediate mode = sticky-quarantine the
  source; abort lifts it).
- policy.py pre-filter: new prefixes steer to target (deterministic weighted
  ramp, default 1.0); prefixes with live KV on the source are exempt — the
  existing warm-affinity layer keeps them home until their KV TTL expires
  (session end = TTL after last request). Route reasons `migration_target` /
  `affinity_warm` on every request.
- Drain accounting from KVState: live prefixes remaining, in-flight,
  ttl_horizon_s, progress_pct. Endpoints: POST /v1/migrations, GET
  /v1/migrations/current, abort, complete (409 unless DRAINED).
- Agent allowlist UNCHANGED — migration is operator-initiated; the
  scale-down/promote after DRAINED goes through the existing gated writes.
- Tests: 174 router suite green (25 new in test_migration.py).

## Drill (tools/chaos.py migrate; final clean run 2026-07-05, quiet machine)
Workload: 12 sessions × 90 s (staggered 1.7 s), 512-token fixed prefix +
varying suffix each, 0.5 rps/session; two-pool overlay
(configs/routing-policy.drill.yaml), sim KV TTL 20 s. Both modes sequential.

Raw: benchmarks/raw/migration_graceful_20260705-141129.csv,
migration_immediate_20260705-141351.csv (+ timeline CSVs + migration_drills.csv
summary — cohort columns computed by the drill itself, reproducible).

**Cohort = sessions homed on the SOURCE at migration start** (the two-pool
ring natively homes the rest on the target; they never migrate and are
excluded from the comparison).

| | graceful | immediate |
|---|---|---|
| cohort sessions | 5 | 6 |
| **mid-conversation re-prefills** | **0** | **6 (every session)** |
| cohort TTFT p95 during migration | **70.2 ms** | **293.3 ms (4.2×)** |
| cache-hit TTFT p50 | 51.3 ms | 56.1 ms |
| forced-miss TTFT p50 | — (none) | **293.3 ms (5.2× a hit)** |
| drained after | 105.7 s (sessions rode out their KV TTL) | 21.1 s (quarantine + one TTL) |
| where cohort requests ran | 100% source until natural expiry | 98% forced to target |

The trade is explicit and honest: graceful takes ~5× longer to drain
(bounded by session length + KV TTL, reported live as ttl_horizon_s) in
exchange for zero mid-conversation disruption; immediate is fast but every
live conversation pays a prefill recompute at once — the re-prefill storm.
Post-migration, graceful sessions that RETURN pay one first-prefill on the
target (12/12 after-probes missed, as expected — deferred, not avoided; KV
is waited out, not transferred; "proactive KV transfer" remains [roadmap]).

## Iteration note (honesty about the measurement itself)
Run 1 (32-token prefixes, naive counter) showed no meaningful difference —
prefill was a rounding error and the counter conflated new-session first
prefills with forced re-prefills, and counted the drill's own after-phase
probes. The counter was split (re_prefill vs new_session_first_prefills),
the cohort restricted to source-homed sessions, and prefixes raised to a
realistic 512 tokens. Superseded raw files from runs 1–2 remain on disk
(migration_*_20260705-135629/135849/140132/140355) — kept, not hidden.

## Surfaces
- MANAGE drain flow is live: Apply → POST /v1/migrations, 3 s progress
  polling in the confirm modal (live prefixes / in-flight / TTL horizon /
  progress) with Abort; the gated write arms only at DRAINED (design/DESIGN.md
  deviations #14–15).
- OPERATE: migration events in the feed + a progress strip while active.

## Can / cannot claim
CAN: the mechanism runs in the real router on the code path live traffic
uses; the deltas above are measured from per-request CSVs with explicit,
inspectable sim economics (prefill/decode split, KV TTL, cache behavior).
CANNOT: absolute GPU latencies (sim-modeled — report ratios, not ms, when
generalizing); real paged-attention eviction dynamics; Baseten dedicated
deployments expose no per-replica KV state, so a live confirmation would
approximate KV drain by router-observed session inactivity (not yet run;
~$0.50 when wanted).

## Known limits (added 2026-07-05, staff-skeptic review — raw-CSV audit + live re-verification)
1. **Cohort membership is "has a warmup-phase row on the source", not
   literally "homed on source at migration start"** (tools/chaos.py:556-557;
   phases are stamped at request COMPLETION, chaos.py:403). In the final
   graceful run, session 0's first request paid the drill overlay's 45 s sim
   cold start (COLD_START_S=45 in run_local_stack.sh) and completed after the
   phase flip, so a 6th source-homed session is silently absent from the
   graceful cohort (5 vs immediate's 6; the immediate run hit warm pools and
   had no dropout). Audited from the raw CSV: session 0 rode warm on the
   source with ZERO forced misses, so including it keeps re-prefills at 0 —
   direction unchanged; the asymmetry is a measurement-hygiene gap, not
   cherry-picking. The same cold start explains the run's 1 recorded error
   (session 1's first request > 60 s client timeout).
2. **Real-fleet framing of the cohort.** The two-pool ring homing ~half the
   sessions on the target is drill-specific. In a real fleet upgrade the
   target starts EMPTY: all sessions are source-homed, per-session effects
   are identical, and the immediate-mode storm is larger (12/12 recomputes at
   once, not 6). The drill cohort therefore understates the graceful-vs-
   immediate gap — conservative.
3. **[FIXED same day]** Abort originally cleared the source quarantine
   unconditionally — including one the incident agent set BEFORE the
   migration, which would have put a sick pool back in rotation. Fixed:
   migration start snapshots the pre-existing flag and abort restores it
   (main.py migration start/abort; regression test
   test_abort_preserves_pre_existing_agent_quarantine; suite now 175).
4. **Granularity and scale.** source/target are single replica ids
   (policy.py:125); one migration slot per router, held in process memory —
   multi-replica pools, concurrent migrations, and multi-instance routers
   are out of scope by design.
5. **Immediate-mode attribution.** Forced storm requests reach the target
   via the ring skipping the quarantined source, so they carry
   `route_reason=affinity_place` (live-verified) — the migration's routed
   counters and feed rows undercount the storm in immediate mode.
