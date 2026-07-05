# STAFF-SKEPTIC — KV-affinity graceful migration

**Verdict: PASS** (2026-07-05; conditional on the Known-limits section now
appended to evals/migration/EVIDENCE.md — top objection documented, direction
of every headline number re-verified from raw CSVs and a live stack).

## What I actually verified (not took on faith)
- **The pre-filter is on the live chat path, not a demo shim.** Traced
  `_select_for_chat` → `select_replica(..., migration=self.migration.active())`
  (services/router/router_app/main.py:163-170 → policy.py:121-128). Live on
  the sim stack (drill overlay, KV_TTL_S=20): warm-on-source prefix stayed
  home (`affinity_warm`, hit), three fresh prefixes all steered
  (`migration_target` on vllm-l4), double-start 409, premature complete 409.
- **Abort restores selection.** Post-abort, fresh prefixes landed on BOTH
  pools again (ring never rebuilt — policy.py:147-151 builds the ring over
  all candidates every call; the steer is a candidate-set filter + stable
  head sort, so deactivation is truly byte-identical for unsteered prefixes).
- **Immediate mode is real.** Warm-on-source prefix forced to target (miss =
  the re-prefill), source pool status flipped to `bad` (sticky poller
  quarantine, main.py:1173-1176), abort lifted it (source served fresh
  prefixes again), drill's cleanup abort does the same (chaos.py:494-498).
- **Complete is gated.** 409 until the router itself observes
  live_prefixes==0 and in_flight==0; drained fired at exactly one TTL (20.1 s)
  after traffic stopped; terminal migration reports `idle`.
- **Numbers trace.** EVIDENCE table == benchmarks/raw/migration_drills.csv
  rows 20260705-141129/-141351; recomputed cohort membership, re-prefill
  counts, and the 98%-forced figure (1/55 cohort-live rows on source)
  directly from the per-request CSVs.
- **Tests:** 25/25 in tests/test_migration.py pass (state machine, steering,
  TTL flip, weight determinism, endpoint 409/404s, quarantine set/clear).
- **UX wiring is live, not mock:** manage.html Apply → POST /v1/migrations,
  3 s polling, write button armed only at `drained`, cancel/backdrop aborts
  (design/manage.html:113-210); operate.html strip polls
  /v1/migrations/current and hides on idle. DESIGN.md deviations #14-15
  logged with dates. Mock fallback is labeled ("write not gated on DRAINED").

## JD lines actually demonstrated (vs claimed)
- "how traffic is routed ... rolling deploys never drop traffic" and F5's
  "traffic-shifting that powers ... warm-ups, drain" — REAL: this is a
  KV-aware drain in the router's actual selection path with a measured
  storm-vs-patience trade, which is precisely the drain conversation.
- "owns capabilities end to end, backend through UX" — REAL: state machine →
  endpoints → gated write in MANAGE → progress strip in OPERATE.
- Cost/perf frontier — PARTIAL: the 5.2× miss-vs-hit ratio is sim economics;
  EVIDENCE's cannot-claim section says so correctly (ratios, not ms).

## Ranked objections
1. **[TOP — now documented] Cohort hygiene in the graceful run.** Cohort is
   implemented as "has a warmup-phase row on the source" (chaos.py:556-557),
   and rows are phase-stamped at COMPLETION (chaos.py:403). Session 0 paid
   the 45 s sim cold start (COLD_START_S=45, run_local_stack.sh), completed
   after the phase flip, and silently vanished from the graceful cohort —
   the real cohort was 6, not 5, and the 5-vs-6 asymmetry in the EVIDENCE
   table was unexplained. Audited: session 0 rode warm on source with zero
   forced misses, so re-prefills stay 0 and every headline direction holds —
   hygiene gap, not cherry-picking. Also explains the run's 1 error and the
   lone "affinity_place on source during migration" row (routed
   pre-migration, recorded post-flip). **Resolution: documented as Known
   limit #1 in EVIDENCE.md (verified).**
2. **Abort doesn't restore pre-existing quarantine** (main.py:1212-1218).
   Immediate abort unconditionally clears the source quarantine — including
   one the incident agent set before the migration. Realistic 3am path:
   agent quarantines a sick pool, operator starts an immediate migration off
   it, aborts (target trouble), sick pool re-enters rotation. The code
   comment claims "an agent-set quarantine is not ours to lift" but nothing
   tracks whose it was. Fix is small: snapshot the flag at start, restore on
   abort. Documented as Known limit #3.
3. **Cohort framing vs a real fleet upgrade.** The two-pool ring homing half
   the sessions on the target is drill-specific; a real target starts empty,
   making all 12 sessions source-homed — same per-session effect, larger
   aggregate storm. Excluding target-homed sessions is legitimate (they
   never migrate in either mode; including them dilutes both equally), and
   the drill cohort UNDERSTATES the gap — conservative. But EVIDENCE didn't
   say this until now (Known limit #2).
4. **"Pool" = one replica.** migration.source/target are replica ids compared
   to candidate `c["id"]` (policy.py:125); a pool of N replicas isn't
   expressible. The drill's two "pools" are each a single sim endpoint.
   Known limit #4.
5. **Immediate-mode attribution.** Forced storm requests carry
   `route_reason=affinity_place` (source excluded by health, not by the
   steer, so `steered` is False) — live-verified. Routed counters and the
   feed undercount the storm in immediate mode. Cosmetic; Known limit #5.
6. **ttl_horizon_s wording.** EVIDENCE says drain is "bounded by session
   length + KV TTL, reported live as ttl_horizon_s" — ttl_horizon_s
   (kvstate.py:45-53) is the instantaneous no-refresh horizon and slides
   forward while sessions refresh; it is not the session-length bound. The
   docstring is honest; the EVIDENCE phrasing slightly conflates them.

## The judge's specific questions
- **Real or theater?** Real. Pre-filter on the live path (traced + exercised),
  drain gate enforced server-side (409 until drained, UI merely reflects it),
  abort restores ring selection and lifts the immediate quarantine
  (both live-verified). The one caveat: DRAINED is a router-belief event
  (kvstate TTL bookkeeping), not engine-confirmed KV emptiness — EVIDENCE's
  cannot-claim covers this.
- **5× trade honest?** Yes — 105.7 s vs 21.1 s is printed, explained
  (session length + TTL vs quarantine + one TTL), and the deferred-not-avoided
  cost (12/12 after-probe misses) is volunteered rather than hidden.
- **Built-vs-roadmap labels?** Truthful. Weighted ramp is built and
  unit-tested for determinism and 50/50 split (test_migration.py:130,223),
  though the drill only ever ran weight=1.0 — ramp is unit-proven, not
  drill-proven. KV transfer is consistently [roadmap]
  (manage_options.py:142-161, EVIDENCE line 56).
- **Iteration note adequate?** Yes — run 1's counter conflation and toy
  prefixes are disclosed and superseded raws kept. It missed the cold-start
  cohort dropout, which Known limit #1 now closes.

## 100x analysis
- **In-process state is the real ceiling.** MigrationManager and KVState live
  in router process memory. Two router instances behind an LB: only the
  instance that took the POST steers; the other keeps ring placement, and
  its traffic refreshes source KV so the drain may never converge. Same for
  kvstate — the whole affinity layer assumes one router.
- **One migration per router serializes fleet upgrades** across all models,
  not just per model (main.py:1138-1139 singleton). Fine at 2 pools;
  a 50-model fleet upgrade becomes a week of sequential drains.
- **O(prefixes) under a lock on the hot path**: cached_prefixes/ttl_horizon_s
  scan every held prefix (kvstate.py:39-53), and _record_chat calls observe()
  per completion (main.py:209-213) — at 100x concurrency that lock and scan
  are contention; observe also emits migration_progress on every count
  change, which at high rps floods the 2000-slot event ring and evicts
  everything else from the feed.
- **Lazy drained check needs a heartbeat**: if traffic to the model stops and
  nobody polls /v1/migrations/current, DRAINED never fires. The UI polls
  every 3 s, so fine as shipped — but an unattended migration (operator
  closes the tab) parks forever in MIGRATING. Not a 3am page (it fails
  safe: steering continues, nothing is drained-and-detached), but worth
  knowing.
- **Drain time scales with the longest session**, and the drill's 90 s
  sessions are friendly; real multi-hour agent sessions make graceful drain
  effectively "wait for TTL after the last turn" — the weighted ramp and an
  eventual max-drain deadline (force-cutover) become necessary, and there is
  deliberately no force flag today (migration.py:155-157).
