# Known issues (internal — distinct from docs/FRICTION_LOG.md, which is Baseten platform friction)

## 1. Incident-agent detection degrades on a long-lived sim stack (filed 2026-07-05)

**Observed (2026-07-04, Phase B corpus generation):** running
`tools/chaos.py drill --suite` repeatedly against ONE `scripts/run_local_stack.sh`
stack, detection latency climbed monotonically across suites — runs 1–4:
detect 15–118 s, all resolved (MTTR 8.1 s); run 5: combo unresolved; run 6:
errors+combo unresolved; runs 7–8: NOTHING detected, all drills unresolved.
Fresh-stack reruns detected in 4.5–67 s consistently (5 clean suites).
Corroborating anomaly: one aged-stack tape has `detected_s = -3.388`
(detection apparently BEFORE injection), i.e. the agent opened on residual
breach state from a previous drill — stale window/case state is implicated.

**Hypotheses (unresolved):**
(a) router/agent state aging across ~12+ drills on one process — metrics
window, case/cooldown bookkeeping, or health-poller state accumulating in a
way that suppresses or mistimes detection;
(b) CPU contention — a parallel dev agent ran test suites and a browser smoke
on the same machine during the degraded runs, and the drill detection path is
timing-sensitive.

**Impact:** corpus generation must restart the stack per suite (done for the
committed corpus; the degraded runs left 9 unresolved rows in
benchmarks/raw/chaos_drills.csv — unresolved incidents record no tapes and
are excluded by construction, while the 4 degraded-run incidents that still
resolved are taped and included, labeled in the Phase B evidence). If (a) is
real, a long-running production router could suffer the same drift.

**Next step:** reproduce on an idle machine — 8 back-to-back suites, one
stack, no other load; if degradation reproduces, bisect agent/runner state
(metrics window growth, `cases`/`cooldown_until` accumulation, health poller)
per suite; if it does not, attribute to CPU contention and document a
quiet-machine requirement for drill benchmarks.
