# learning/ — the agent's experience, recorded for an RL loop

Every incident the agent works becomes one JSONL **episode**. This directory
is the training substrate: today it powers offline analysis; the goal is a
closed loop that *tunes the agent's policy from its own operational history*.

## Episode schema (one JSON object per line)

| field | meaning |
|---|---|
| `episode_id`, `recorded_at`, `source` | identity + provenance (`live-incident` or `backfill:<file>`) |
| `policy` | the `AgentConfig` active during the episode — breach threshold, min samples, probe interval/SLO, probes-to-reinstate, cooldown, escalation threshold |
| `context` | model, pool, topology facts |
| `fault` | injected fault parameters when the episode came from a drill (scenario, latency_ms, error_rate) |
| `trajectory` | the action sequence from the incident ledger (detect → quarantine → probes → reinstate → resolve) |
| `probes` | each verification probe: pass/fail + measured ms |
| `outcome` | resolved?, MTTR, detection lag, quarantined?, escalated?, probe stats |
| `reward` | shaped scalar + its decomposition (auditable, see below) |

## Reward (deliberately simple, fully auditable)

```
reward = resolved_bonus (+10 resolved / −30 unresolved)
       + mttr_penalty   (−1 per second of MTTR)
       + escalation_penalty (−5 if a human was paged)
```

Every term is visible in the episode so reward changes are diffable. Known
future shaping: user-visible errors during the incident, spill-pool cost
delta, probe traffic spent.

## How episodes are produced

- **Live**: `services/router/router_app/learning.py` — the incident agent
  appends to `episodes/live.jsonl` on every resolve (`LEARNING_DIR` to
  relocate, `LEARNING_DIR=off` to disable). Recording can never raise into
  the serving path.
- **Backfill**: `python3 learning/build_episodes.py` regenerates
  `episodes/backfill.jsonl` from the committed evidence
  (`benchmarks/raw/chaos_drills.csv` + the devboard incident snapshots) —
  the real 2026-07-02/03 sessions, including the agent-off control runs
  (reward −30: that's what the baseline is worth).

## The intended RL loop (roadmap)

1. **Collect** — drills + organic incidents accumulate episodes (done).
2. **Offline policy evaluation** — replay episodes against candidate
   `AgentConfig` variants: would a lower breach threshold have detected
   sooner without flapping? Would fewer probes-to-reinstate have cut MTTR
   without reinstating a sick pool? The pure `IncidentAgentLogic` core is
   clock-injected and I/O-free precisely so trajectories can be re-simulated.
3. **Search** — start with a bandit over the config's ~7 scalars (the reward
   is dense and episodes are cheap to generate via `tools/chaos.py drill`).
4. **Shadow** — run the candidate policy's decisions side-by-side on live
   telemetry without executing them; compare chosen actions.
5. **Promote** — gate on the same eval agents that gate features
   (evals/): SLO-auditor traces the numbers, chaos-agent attacks the new
   policy, staff-skeptic reviews the diff.

The invariant throughout: the *allowlist never grows by learning*. The loop
tunes when/how-fast the agent acts — never what it is allowed to do.
