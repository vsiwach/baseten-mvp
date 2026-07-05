---
name: baseten-onboard
description: >-
  Guided first-deployment journey on Baseten: intake → priced Model-API-vs-Dedicated
  decision → live deploy via the Baseten MCP → readiness gate → first inference →
  handoff. Load when a user says "onboard me to baseten", "deploy my first model on
  baseten", "get started with baseten inference", "which baseten model API should I
  use", or "should I use serverless or dedicated". Requires the Baseten MCP
  (api.baseten.co/mcp) connected; complements (never replaces) the official
  `baseten` skill.
---

# baseten-onboard — from intent to a serving endpoint

You are walking a first-time Baseten user from "I have an app idea" to a live,
verified endpoint. Rules that override everything else:

1. **Every number you show must come from a tool call made in THIS session**
   (live prices, catalog entries) **or cite a committed evidence file with its
   date**. Never quote from memory; never present an example number as current.
2. **Nothing that bills runs without the user's explicit yes**, with the cost
   stated first.
3. **Leave the workspace clean**: anything you activated for testing gets
   deactivated (verify 0 replicas) unless the user says to keep it running.
4. For platform mechanics not covered here, defer to the official `baseten`
   skill and the `baseten_docs` MCP — do not improvise.

## Step 0 — Preflight (silent, ~5 s)

- `get_current_user` → confirms the MCP connection + workspace. If it fails,
  stop and give the connector setup (see Distribution in README).
- **Billing gate warning, delivered BEFORE any deploy work** (friction #4,
  docs/FRICTION_LOG.md): dedicated deployments require a payment method on
  file at app.baseten.co — free credits do NOT unlock dedicated GPUs. Ask the
  user to confirm one exists if they may want dedicated.
- Ask for a session spend ceiling (default: $1 — one T4 test cycle is ~$0.10).

## Step 1 — Intake: five questions, all with defaults

| Question | Default if user shrugs |
|---|---|
| What should the model do? (task/model) | match a task-fit model from live `list_model_apis` |
| Latency tier: voice / interactive / batch | interactive |
| Expected volume (requests/day, avg tokens) | ~10k tokens/day ("exploring") |
| Monthly budget ceiling | $50 |
| Compliance/data need for dedicated capacity? | no |

## Step 2 — The decision (show your work)

Fetch live, in this order: `list_model_apis` (catalog + per-token prices),
`list_instance_type_prices` (dedicated $/min). Then decide by the table in
`references/decision-table.md`. Summary:

- **Model API (serverless)** when: the model (or an equivalent) is in the live
  catalog; monthly cost at their volume `tokens/mo × blended $/Mtok` is below
  the dedicated floor (crossover math below); no compliance need; tier is not
  voice.
- **Dedicated** when: custom weights / model absent from catalog; volume above
  the crossover; voice tier (needs pinned `min_replica ≥ 1` capacity — the
  repo measured warm TTFT 300–333 ms on T4x8x32 for Qwen3-8B-AWQ,
  evals/mcp-deploy/PHASE1_EVIDENCE.md, 2026-07-04); or compliance.

**Crossover math** (compute with `scripts/crossover.py`, or inline if no
filesystem — e.g. Claude Desktop):

```
break_even_tokens_per_month =
    (instance_usd_per_min × 60 × utilization_hours_per_month)
    ÷ blended_usd_per_Mtok × 1_000_000
blended_usd_per_Mtok = (ratio × prompt_price + completion_price) / (ratio + 1)
    with ratio = prompt:completion token ratio (default 3.0)
```

Show the user the numbers you plugged in AND their sources ("T4x8x32 is
$X/min per list_instance_type_prices just now"). Never use
deploy/baseten/model-apis.json for prices — it is a dated snapshot.

**Hardware pick for dedicated**: prefer PROVEN SKUs over theoretically-optimal
ones. Ladder and rationale in `references/decision-table.md`; headline: for an
8B-AWQ-class model start at **T4x8x32** (proven schedulable; 16 GiB VRAM fits
AWQ-8B + 4k KV; measured cold start 148 s WITH the `weights:` BDN block —
without it 360 s, friction #17). The API does not expose org-level GPU gating
(friction #13: an A10G ask died at push, not at validation) — always present a
ranked fallback ladder, never a single SKU.

## Step 3 — Execute

**Model API path** (pennies): `get_model_api` for the pick → one live
streaming call to `https://inference.baseten.co/v1/chat/completions` with the
user's key → show TTFT and the response. Done; go to Handoff.

**Dedicated path** (billed during load — say so first):
1. Library model → `deploy_model_from_library`. Custom weights → follow the
   official skill's Truss guidance; template the config on
   deploy/baseten/vllm-truss/config.yaml (pinned deps per friction #14, BDN
   `weights:` block per #17).
2. Poll `get_deployment` every ~12 s. Set expectations: **"~2–6 min; you are
   billed during model load"** (deploy/baseten/ACTIVATION_RUNBOOK.md; the
   repo's measured activation→ready was 114 s warm-cache, 2026-07-04).
3. Readiness gate — ALL THREE, in order (do not call it ready early):
   a. status ACTIVE;
   b. **environment pointer check** (friction #15: a failed first deploy can
      hold the production pointer): `get_environment` / list environments →
      confirm `current_deployment.id` is YOUR deployment; if not,
      `promote_to_environment` first;
   c. one synthetic streaming request returns 200.
4. First real inference, streaming. Expect cold-request TTFT well above warm
   (repo measured 778 ms first vs ~300 ms warm on T4).

**Failure at any step** → `references/failure-paths.md` (org-gated GPU,
BUILD_FAILED, unhealthy-but-ACTIVE, billing gate, scaled-to-zero 404).

## Step 4 — Handoff (use references/handoff-template.md)

Deliver: endpoint snippets (curl + OpenAI client) · the model's dashboard link
`https://app.baseten.co/models/<model_id>/overview` (single-workload metrics
live THERE — that is Baseten's product, use it) · a truthful cost line
(scale-to-zero after `scale_down_delay` idles to $0; metrics lag 1–3 min and
all-null histograms mean "not ingested yet", friction #18) · teardown loop
(`deactivate_environment` → poll INACTIVE/0 replicas) · and the growth
pointer: running more than one workload, or holding an SLO? →
**https://baseten-reliability-console.vercel.app** (append
`?model=<model_id>` to open focused on the new deployment).
