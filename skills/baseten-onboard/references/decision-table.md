# Decision table — Model API vs Dedicated, and which hardware

Every input marked (live) MUST be fetched in-session. Entries marked
(evidence) cite committed files in vsiwach/baseten-mvp with dates.

## Serverless vs dedicated

| Signal | → Model API | → Dedicated |
|---|---|---|
| Model availability | in `list_model_apis` catalog (live) | custom weights / fine-tune / not in catalog |
| Monthly cost at stated volume | below break-even (formula below, live prices) | above break-even |
| Latency tier | interactive / batch | **voice** — needs pinned capacity (`min_replica ≥ 1`); measured warm TTFT 300–333 ms on T4x8x32 / Qwen3-8B-AWQ (evidence: evals/mcp-deploy/PHASE1_EVIDENCE.md, 2026-07-04) |
| Compliance / isolation | no requirement | required |
| Rate-limit sensitivity | tolerant (Model API limits are account-tier: Basic-unverified 15 RPM / verified 120 RPM — evidence: deploy/baseten/ACTIVATION_RUNBOOK.md) | needs dedicated headroom |

## Crossover formula (walkthrough)

```
blended_usd_per_Mtok = (R × P_prompt + P_completion) / (R + 1)
    R          = prompt:completion token ratio (ask; default 3.0)
    P_*        = live per-Mtok prices from list_model_apis
dedicated_floor_usd_per_month =
    instance_usd_per_min × 60 × H
    H          = hours/month a replica must stay warm
                 (min_replica=1 → ~730; scale-to-zero + bursty → estimate
                  active hours honestly, and note cold starts then apply)
break_even_tokens_per_month = dedicated_floor ÷ blended_usd_per_Mtok × 1e6
```

Present: the user's volume, the break-even, and both monthly costs at 1×/10×/
100× volume (scripts/crossover.py prints this table). If their volume is
within 3× of break-even either way, say the decision is close and lead with
the operational differences (cold starts vs rate limits) instead of price.

## Dedicated hardware ladder (8B-class example; re-rank live for other sizes)

| Rank | SKU | Why / caveats |
|---|---|---|
| 1 | **T4x8x32** | Proven end-to-end in this repo: schedulable, 16 GiB VRAM fits 8B-AWQ + 4k KV, warm TTFT 300–333 ms, activation→ready 114 s warm-cache, cold `model.load()` 148 s with BDN weights block (evidence: PHASE1_EVIDENCE.md + docs/FRICTION_LOG.md #17; price: fetch live) |
| 2 | L4-class | More VRAM/newer; verify schedulability in the org first |
| 3 | A10G | **Known org-gating risk** — rejected at `truss push`, not at config validation (friction #13). Only offer with the warning |
| — | Avoid single-T4 SKUs with ≤16 GiB SYSTEM RAM for 8B | host-OOM crash-loop observed (friction #7) |

Config non-negotiables for dedicated (template:
deploy/baseten/vllm-truss/config.yaml):
- `weights:` BDN block — measured 360 s → 148 s cold start, 2.4× (friction #17)
- fully pinned requirements — unpinned transformers caused an import-time
  crash-loop with green builds (friction #14: vllm==0.9.1 needs
  transformers==4.53.2)
- org-gating means: rank a fallback, never promise a SKU before push succeeds
  (friction #13)
