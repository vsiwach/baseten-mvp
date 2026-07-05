# STAFF-SKEPTIC verdict — Phase B: offline serving-RL policy eval

**Verdict: PASS** (re-review 2026-07-05, after remediation of the same-day
FAIL; original findings preserved in the appendix for the record).

Reviewed: `evals/policy-eval/PHASEB_EVIDENCE.md`,
`services/router/router_app/replay.py`, `learning/evaluate.py`,
`services/router/router_app/incident_agent.py`,
`services/router/router_app/learning.py`, `learning/policy-eval.json`,
`docs/KNOWN_ISSUES.md`, `services/router/tests/test_policy_eval.py`, corpus
`learning/episodes/*.jsonl` (110 episodes, 25 taped).

## Remediation verification (all three checked against the files, not the claim)

1. **Sharpened caveats — VERIFIED.** `learning/evaluate.py` CAVEATS now
   carries, and the regenerated `learning/policy-eval.json` (10 caveats)
   renders: (a) "IMPROVEMENT IS PARTLY BY CONSTRUCTION … post-detection MTTR
   reduces to probe_interval_s x probes_to_reinstate for ANY corpus — faster
   probing always wins here, and this eval cannot price the costs of
   aggressive probing (probe load, flapping, premature reinstatement)";
   (b) reward() open-anchored / detection-latency-unpriced disclosure —
   correctly disclosed rather than altered, since reuse-verbatim is itself
   part of the eval's integrity story; (c) escalate_after_failures inert
   (ties across that grid dimension). I re-ran `run_eval()` over the
   committed episodes: **reproduces the artifact byte-identically**, holdout
   numbers unchanged (8.05 / 2.005) — the remediation changed the framing,
   not the data. Correct.
2. **Follow-up actually filed — VERIFIED.** `docs/KNOWN_ISSUES.md` #1 exists
   (filed 2026-07-05) with the full degradation timeline (runs 1–4 detect
   15–118 s → runs 7–8 nothing detected), the `detected_s = -3.388` causal
   anomaly this review found (correctly interpreted as stale window/case
   state), both hypotheses, corpus impact, and a concrete repro/bisect next
   step (8 back-to-back suites on an idle machine, then bisect
   metrics-window / `cases` / `cooldown_until` / poller state). Correction to
   my original verdict: FRICTION_LOG.md has 19 entries, not 17 — my count was
   wrong; and KNOWN_ISSUES (internal) is the right home for this, not
   platform friction.
3. **Evidence corrected per auditor — VERIFIED.** Corpus composition now
   states 12 clean-run + 4 degraded-run-but-resolved (3 in holdout) + 9
   fresh-stack; the "5 unresolved" claim is replaced with 9 unresolved CSV
   rows / no-tape-by-construction; the ep-inc-0016 harness-timeout-vs-agent-
   resolve mismatch is explained with both records true at their timestamps.

Test suite re-run: **149 passed**.

## Why PASS now
My gate: the TOP objection must be fixed or documented as a known limit. The
top objection — the 8.05→2.005 holdout delta is arithmetic of the binary
oracle, with zero per-episode variance, and the eval cannot price aggressive
probing — is now documented loudly, in the machine-readable artifact itself,
in exactly the words a staff interviewer would need to see (`evaluate.py`
caveat (a); PHASEB_EVIDENCE.md Result section). Objection #2 (reward's
open-anchored late-detection bias corrupting the breach_rate_threshold curve
ranking) is disclosed. Objection #3 (unfiled anomaly + causally impossible
tape) is filed with a bisect plan. The claim's stated value — "the honest
counterfactual harness + the corpus, not the delta itself" — is now the
defensible one, and it is genuinely defensible: the recorder → tape →
deterministic pure replay → gated proposal pipeline with a closed action
allowlist is real engineering, reproduces byte-identically, and is
unit-tested.

## Residual nits (non-blocking; fix opportunistically)
- **5-vs-9 inconsistency:** `docs/KNOWN_ISSUES.md` #1 Impact still says "the
  5 unresolved-drill episodes carry no tapes" while the corrected evidence
  says 9 unresolved rows. One of the two is stale.
- The PHASEB_EVIDENCE headline paragraph (lines 3–8) still leads with the
  raw delta; the by-construction framing lives in the Result section and
  caveats. Fine on a one-page doc — but any external deck/interview slide
  must lead with "faster probing wins by construction; the deliverable is
  the harness."
- `design/policy.html:15` copy "RL-learned probe/reinstate policy" still
  overclaims a grid search (design mock only; the live devboard has no such
  copy).
- Recorder scaling nits stand as known limits: 120-tick deque truncates
  >4 min pre-open history; `_tape_probes` unbounded for a never-resolving
  escalated case; per-pool `chaos_windows` consume mislabels overlapping
  incidents on one pool.

## JD lines actually demonstrated (vs claimed)
- **Demonstrated:** "measurable decline in MTTR through self-serve incident
  management" — as evidence-grade tooling: off-policy replay harness,
  deterministic pure decision core, auditable reward, allowlist invariant,
  and honest failure disclosure (the corpus-anomaly write-up is itself the
  strongest staff signal in this feature). "Everything observable" is met:
  the artifact, endpoint adapter, and caveats are first-class.
- **Not demonstrated (and no longer claimed):** that the proposed config
  improves the live cost/perf frontier. That requires the shadow-run on
  fresh drills with flapping/partial-degradation scenarios — correctly
  gated as the stated next step.

## Allowlist invariant — CONFIRMED (unchanged)
`replay.py` constructs no effect dicts; every op comes from
`IncidentAgentLogic.step()`/`record_probe()` (`replay.py:125–148`).
`evaluate.py` sweeps only the fixed `SWEPT` tuple of `AgentConfig` scalars;
`AgentConfig` (`incident_agent.py:53–64`) contains only the 7 scalars — there
is no field through which the action set could grow. Default-in-grid
assertion present (`evaluate.py:131–133`).

## 100x analysis (unchanged)
The eval scales: 81 × 13 = 1053 replays of a pure O(ticks × pools) function,
embarrassingly parallel. The grid does not (7 params × 3 = 2187 and
exponential beyond) — the README's bandit roadmap is the right answer.
What breaks at 100x is upstream: single-process in-memory flight recorder and
`chaos_windows` (overlap mislabeling, truncation), episodes-as-JSONL with
embedded tapes becoming an unindexed multi-GB append file, and — the one cost
this eval prices at zero, now said so in the artifact — a fleet-wide 1 s
probe interval during a correlated regional event is a synchronized probe
storm against already-sick pools. The shadow-run gate covers this before any
promotion.

---

## Appendix — original findings (2026-07-05 FAIL, retained for the record)

1. **(TOP) Tautological holdout:** empirical replay of all 25 tapes showed
   MTTR 8.037–8.078 s (default) / 2.001–2.010 s (proposed) with zero
   dependence on fault kind, magnitude, or duration (0.5–147.6 s); under
   `replay.py:145` (`ok = t >= cleared`) no replayed probe ever fails, so the
   delta is probe arithmetic for any corpus. Exact reward ties across
   `escalate_after_failures` confirmed the 81-grid is effectively 27, with 9
   informative cells. → **Remediated: documented in artifact caveat (a).**
2. **Reward rewards late detection:** `reward()` charges −1/s of
   open-anchored MTTR while `detected_s` goes unused, which is why
   breach 0.3 ranks below 0.5 in the committed curve. → **Remediated:
   disclosed in caveat (b).**
3. **Corpus integrity:** one train tape with `detected_s = -3.388`
   (detection before injection — residual state from a prior drill), and the
   evidence claimed a follow-up was "filed" when none existed.
   → **Remediated: docs/KNOWN_ISSUES.md #1, incorporating the anomaly.**
4. **Vacuous holdout distribution:** same generator, 3 scenario families,
   all 25 tapes recorded under one policy. → Stands as a documented limit;
   honest next validation = shadow-run + flap/partial/probe-fail drills +
   split by scenario family, per the evidence's own next steps.
5. **Minor:** recorder scaling nits, replay's frozen synthetic-tick samples
   (covered by the cooldown/min_samples caveat), design-mock "RL-learned"
   copy. → Stand as nits above.
