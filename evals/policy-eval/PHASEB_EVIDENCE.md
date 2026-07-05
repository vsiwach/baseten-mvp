# Phase B evidence — offline policy evaluation from recorded incidents (2026-07-04)

Claim (scoped): under SIM chaos drills with binary, pool-local faults, replaying
recorded observation tapes through the REAL IncidentAgentLogic shows the
proposed config (probe_interval_s 3→1, probes_to_reinstate 2→1) cuts held-out
mean MTTR **8.05 s → 2.005 s** with 0 unresolved and 0 escalations on both
sides and half the probes. This is an off-policy replay against a
policy-independent fault oracle, not a live A/B; caveats are in the artifact.

## What was built (committed this phase)
- Recorder: IncidentAgentRunner keeps a 120-tick flight recorder; on resolve it
  attaches a tape (per-tick PoolSignals from open−30 s, probe outcomes, fault
  window from the /v1/dev/chaos handler's inject/clear timestamps) to the
  episode. Live incidents (no chaos window) stay untaped, labeled.
- services/router/router_app/replay.py: pure replay(tape, AgentConfig) —
  candidate observes reconstructed signals; probes answered by the fault
  oracle (ok iff t ≥ cleared_at); only IncidentAgentLogic emits actions;
  no wall clock, no randomness, pools sorted (deterministic).
- learning/evaluate.py: 81-candidate grid over 4 of the 7 scalars (3 fixed at
  defaults, stated), sha256-based 70/30 split, reward() imported verbatim from
  router_app.learning, winner-vs-default reported on HOLDOUT only, untaped
  episodes excluded AND counted. Output: learning/policy-eval.json.
- GET /v1/learning/policy-eval: package-shaped adapter (+ ?raw=1 passthrough).
- Tests: 149 total router suite (123 → +26 with Phase C; Phase B added
  replay determinism, winner≥default-on-train, exclusion accounting,
  endpoint, recorder-hook tests).

## Corpus (all sim; source labeled per episode)
- 25 taped episodes from `tools/chaos.py drill --suite` (latency/errors/combo
  × varied magnitudes 1500–3500 ms / 0.5–0.9 error rate) against
  scripts/run_local_stack.sh. Composition (per the auditor's independent
  count): 12 from the long-lived stack's clean runs 1–4, 4 from its degraded
  runs 5–6 (episodes that still resolved and taped; 3 of these land in
  holdout), and 9 from the 3 fresh-stack suites. One episode (ep-inc-0016) is
  taped/resolved while its chaos_drills.csv row says unresolved — the drill
  harness hit its --timeout-s and recorded the drill as failed, then the
  agent resolved the incident after the harness gave up; both records are
  true at their own timestamps.
- Split 13 train / 12 holdout (deterministic by episode_id hash).
- episodes_total 110, taped 25, excluded 85 (38 backfill + 47 pre-tape live —
  counted, never faked).
- corpus_sha256 in the artifact pins the exact episode set.

## Result (learning/policy-eval.json, generated_at derived from tape data)
- default:  breach 0.5, min_samples 4, probe_interval 3 s, reinstate 2,
  cooldown 30 s, probe_slo 500 ms, escalate_after 5
- proposed: probe_interval_s 1.0, probes_to_reinstate 1 (rest unchanged)
- holdout (12 eps): MTTR mean 8.05 s → 2.005 s; unresolved 0/0;
  escalations 0/0; probes 24 → 12.
- Mechanism (explainable, not magic): with the binary oracle, MTTR after
  detection ≈ probe_interval × probes_to_reinstate + resolve bookkeeping;
  the winner probes sooner and reinstates on the first pass.
- 10 caveats in the artifact, including three added at the skeptic's demand:
  (a) the improvement is PARTLY BY CONSTRUCTION — under the binary oracle no
  replayed probe ever fails after fault-clear, so post-detection MTTR reduces
  to probe_interval × probes_to_reinstate for any corpus, and the eval cannot
  price aggressive probing's costs (probe load, flapping, premature
  reinstatement); (b) reward() is open-anchored (detection latency unpriced —
  reused verbatim from the agent's own shaping, disclosed not altered);
  (c) escalate_after_failures is inert in this corpus (no probe failures →
  ties across that grid dimension). Plus: sim-only, binary oracle,
  breach-hold heuristic, no spill modeling, cooldown/min_samples unexercised,
  taped probe magnitudes, and the flap-robustness warning because the
  proposal LOWERS probes_to_reinstate (shadow-run before adopting).

## Corpus-generation anomaly (recorded honestly)
On a single long-lived sim stack, drill detection degraded across successive
suites (run 1–4 detect 15–118 s → runs 7–8 no detection at all, drills
unresolved). Fresh-stack reruns detected in 4.5–67 s consistently. Two
plausible causes, unresolved: (a) router/agent state aging across ~12+ drills
on one process, (b) CPU contention — a parallel dev agent ran test suites and
a browser smoke on this machine during the degraded runs. The final corpus
composition is as stated above: 12 episodes from the long-lived stack's clean
runs 1–4, 4 degraded-run-but-resolved episodes, 9 from fresh-stack suites.
Follow-up filed in docs/KNOWN_ISSUES.md #1 (including
the aged-stack tape showing a causally impossible detected_s = −3.388, which
implicates stale agent/window state). The degraded runs produced 9 unresolved
drill rows in chaos_drills.csv; unresolved incidents never resolve, so they
record no tapes and are excluded by construction (the 4 degraded-run episodes
that DID resolve are taped and included, labeled above).

## Constraint held
Learning tunes WHEN/HOW-FAST (7 scalars only); the action allowlist
(quarantine/probe/reinstate/resolve/escalate) is untouched — replay.py emits
no actions itself; only IncidentAgentLogic does.
