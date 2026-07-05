# SLO-AUDITOR verdict — Phase B (policy-eval)

**Verdict: PASS** (all displayed numbers reproduced byte-identically from replayed
tapes across two independent audit runs; the artifact was regenerated after the
first audit to add 3 skeptic-demanded caveats — numbers unchanged, re-diffed
byte-identical; two minor stale-wording nits remain, listed at the end)

First audit: 2026-07-04 (initial artifact, 7 caveats). Re-audit: 2026-07-05
(current artifact, 10 caveats — caveats array is the ONLY change; verified).
Evidence: `evals/policy-eval/PHASEB_EVIDENCE.md`. Artifact:
`learning/policy-eval.json`. All commands run locally, no network, no keys.

## 1. Headline reproduction (byte-identical, twice)

```
python3 learning/evaluate.py --out <scratch>/policy-eval-audit.json   # audit 1
python3 learning/evaluate.py --out <scratch>/policy-eval-audit2.json  # re-audit
cmp <scratch>/policy-eval-audit2.json learning/policy-eval.json       # BYTE-IDENTICAL
```

Both runs regenerated the committed `learning/policy-eval.json` **byte-for-byte**
(`cmp` clean on the current 10-caveat artifact), including
`generated_at: 2026-07-04T23:46:12Z` (derived from tape data via `_generated_at()`
= max anchor_utc + last tick, not wall clock — proven by identical reruns on two
different days) and `corpus_sha256: 2e0930f4...45162b9c` (independently recomputed
from sorted taped episode_ids — matches; unchanged across regeneration since the
episode set is untouched).

| metric | displayed | regenerated | tolerance |
|---|---|---|---|
| holdout MTTR default (s) | 8.05 | 8.05 | exact (deterministic replay) |
| holdout MTTR proposed (s) | 2.005 | 2.005 | exact |
| split train/holdout | 13/12 | 13/12 | exact |
| episodes total/taped/excluded | 110/25/85 | 110/25/85 | exact |
| probes default/proposed | 24/12 | 24/12 | exact |
| unresolved, escalations | 0/0, 0/0 | 0/0, 0/0 | exact |
| reward curve entries | 81 | 81 (all unique configs) | exact |
| caveats | 10 | 10 (incl. 3 skeptic additions) | exact |

Tolerance applied: **zero** — replay.py is a pure function (no wall clock, no
randomness, sorted pools), so run-to-run noise is not a valid excuse here and none
was needed.

## 2. Independent counts

- `wc -l`: backfill.jsonl 38 + live.jsonl 72 = 110 lines, 110 parse as JSON.
- Taped (tape + fault.cleared_at + nonempty ticks): 25, **all** in live.jsonl.
- Excluded 85 = 38 backfill + 47 untaped live. Matches the evidence exactly.
- Zero "partial" tapes (tape present but unusable): 0.
- Code path confirms no untaped episode contributes: `run_eval` filters
  `is_taped` before split; untaped episodes only appear in the
  total/excluded counters. The 47 untaped live episodes all have
  `recorded_at <= 2026-07-04T17:01:41Z`, i.e. **before** the drill corpus window
  (22:36Z–23:46Z) — they could not have leaked in.

## 3. Hand replays (all 12 holdout episodes, direct calls to replay())

Called `replay(ep["tape"], AgentConfig())` and
`replay(ep["tape"], AgentConfig(probe_interval_s=1.0, probes_to_reinstate=1))`
directly for every holdout episode (covers latency, errors, combo kinds).
Per-episode default MTTRs 8.037–8.065 s, proposed 2.001–2.009 s. Recomputed means
myself: **8.05 / 2.005**, probes 24/12, unresolved 0/0, escalations 0/0 — identical
to the artifact. Consistent with the stated mechanism
(probe_interval × probes_to_reinstate + bookkeeping) — which the new caveat #3
now correctly flags as "improvement partly by construction" under the binary
oracle.

## 4. Reward + grid integrity

- `reward()` is imported in evaluate.py line 32: `from router_app.learning import reward`;
  the only `def reward` in the codebase is `services/router/router_app/learning.py:39`
  (resolved +10 / unresolved −30, −1/s MTTR, −5 escalation). Not reimplemented.
- Default config `{0.5, 3.0, 2, 5}` appears in the 81-entry curve at rank 27
  (train_reward_mean 1.948); winner rank 1 at 7.841. `run_eval` asserts the default
  is in the grid.
- New caveats #4 (reward is open-anchored, detection latency unpriced) and #5
  (escalate_after_failures inert → grid ties) match what I observed in the curve
  (three-way ties across escalate_after values).

## 5. Split rule

Recomputed `int(sha256(episode_id).hexdigest(),16) % 10 < 7` for all 25 ids →
13 train / 12 holdout, matching. Spot examples: ep-inc-0001-1783204602 (h%10=7,
holdout), ep-inc-0003-1783204814 (7, holdout), ep-inc-0013-1783206080 (7, holdout) —
all agree with the membership the artifact used.

## 6. Tests

`cd services/router && python3 -m pytest tests -q` → **149 passed** (20.6 s),
matching the evidence's claimed suite size.

## 7. CSV cross-check (benchmarks/raw/chaos_drills.csv)

65 rows total; 33 on 2026-07-04 (24 resolved + 9 unresolved). Mapping tape fault
injection UTC (anchor_utc + injected_at − t0, local = UTC−4) to CSV stamps:

- First-batch taped eps 0001–0015 map 1:1 to resolved stamps 183556–190723
  (stamp ≈ 4 s before injection); ep-0016 maps to 190807 (see below).
- The 9 fresh-stack taped eps (23:34–23:45Z) map 1:1 to the 9 resolved stamps
  193409–194547.
- The 9 unresolved 07-04 rows (190448–192903) back the degraded-run story;
  runs 7–8 (191351–192903) have blank detected_s = "no detection at all", as
  claimed. Detection ranges match ("15–118 s" ≈ CSV 17–118 s runs 1–4;
  "4.5–67 s" fresh ≈ CSV 4.53–67.39 s).

## Findings from audit 1 — RESOLVED in the corrected evidence (verified 2026-07-05)

1. ~~Corpus composition overstated as fresh-only~~ — evidence now states the true
   composition: 12 clean runs 1–4 + 4 degraded-run-resolved (3 in holdout) + 9
   fresh-stack. Matches my independent mapping exactly.
2. ~~"5 unresolved-drill episodes" count~~ — evidence now says 9 unresolved CSV
   rows, no tapes, excluded by construction. Matches.
3. ~~ep-inc-0016 CSV-unresolved vs taped-resolved~~ — now explained (drill harness
   `--timeout-s` gave up at det 151.62 s; agent resolved after; both records true
   at their timestamps). Consistent with my replay (detected 147.2 s).
4. Degradation follow-up filed as `docs/KNOWN_ISSUES.md` #1. Its new forensic
   claim — an aged-stack tape with causally impossible `detected_s = −3.388` —
   **verified by direct replay**: ep-inc-0015-1783206443 (train, degraded run 6)
   replays to detected_s = −3.388 under the default config.

## Remaining nits (stale wording only, no metric impact)

- `PHASEB_EVIDENCE.md` anomaly paragraph still contains the old sentence "The
  final corpus therefore uses suites from fresh stacks (runs 1–4 of the first
  batch + 3 fresh-stack suites)", which contradicts the corrected composition
  stated both above it and in its own closing sentence ("the 4 degraded-run
  episodes that DID resolve are taped and included"). Delete or reword.
- `docs/KNOWN_ISSUES.md` #1 Impact still says "the 5 unresolved-drill episodes
  carry no tapes" — the stale count; should be 9 unresolved drill rows (which
  produce zero episodes, since episodes record on resolve).

## Constraint check

replay.py emits no action types itself — all ops come from
`IncidentAgentLogic.step`/`record_probe`; the swept parameters are 4 of the 7
AgentConfig scalars with the other 3 pinned at defaults, as documented. The
`/v1/learning/policy-eval` endpoint (main.py:894) reads the same artifact file and
`devboard.policy_eval_shape` is a pure field mapping (verified: no synthesized
values; `?raw=1` passthrough present).
