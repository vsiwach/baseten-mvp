/* ============================================================
   mock-data.js — mirrors the real API contract EXACTLY.
   Integration: replace window.MOCK-backed fetchers with real
   endpoints; field names and shapes are 1:1.
   One documented extension: pools[] carry `tier` + `slo` so the
   SLO of record renders from data (never hard-coded). See DESIGN.md.
   ============================================================ */

window.MOCK = {

  /* GET /v1/metrics/hero */
  "/v1/metrics/hero": {
    tpot_p99_ms: 48.2,
    tpot_slo_ms: 60,
    tpot_delta_pct: -3.1,
    cost_per_mtok_usd: 0.418,
    cost_delta_pct: -1.8,
    mttr_s: 42,
    mttr_delta_pct: -22.0,
    spark: {
      tpot: [51.4,50.2,49.8,52.1,50.6,49.3,48.9,50.1,49.6,48.4,49.0,48.7,47.9,48.5,49.2,48.8,48.1,47.6,48.3,48.9,48.6,48.0,47.8,48.2],
      cost: [0.44,0.437,0.441,0.435,0.432,0.436,0.430,0.428,0.431,0.427,0.425,0.428,0.424,0.422,0.425,0.421,0.423,0.420,0.419,0.421,0.418,0.420,0.417,0.418]
    }
  },

  /* GET /v1/metrics/slo
     `tier` + `slo` are the one proposed contract addition (see DESIGN.md). */
  "/v1/metrics/slo": {
    pools: [
      {
        id: "voice-a100-us-east",
        tier: "voice",
        slo: { ttft_p99_ms: 500, tpot_p99_ms: 60 },
        health: 0.99, status: "ok",
        ttft: { p50: 118, p95: 212, p99: 348,
          hist: { edges: [0,100,200,300,400,500,700,1000], counts: [412,933,481,122,38,9,2] } },
        tpot: { p50: 31.2, p95: 44.8, p99: 51.6,
          hist: { edges: [0,20,30,40,50,60,80,120], counts: [188,842,611,297,54,5,0] } }
      },
      {
        id: "interactive-h100-us-east",
        tier: "interactive",
        slo: { ttft_p99_ms: 800, tpot_p99_ms: 60 },
        health: 0.97, status: "ok",
        ttft: { p50: 236, p95: 512, p99: 91240,
          hist: { edges: [0,200,400,600,800,1200,60000,120000], counts: [4,6,2,1,0,0,1] } },
        tpot: { p50: 34.6, p95: 47.1, p99: 55.3,
          hist: { edges: [0,20,30,40,50,60,80,120], counts: [96,510,388,164,41,3,0] } }
      },
      {
        id: "batch-a100-us-west",
        tier: "interactive",
        slo: { ttft_p99_ms: 800, tpot_p99_ms: 60 },
        health: 0.96, status: "ok",
        ttft: { p50: 342, p95: 688, p99: 774,
          hist: { edges: [0,200,400,600,800,1200,60000,120000], counts: [201,588,402,196,44,0,0] } },
        tpot: { p50: 38.9, p95: 52.4, p99: 58.8,
          hist: { edges: [0,20,30,40,50,60,80,120], counts: [61,388,472,301,118,12,0] } }
      }
    ]
  },

  /* GET /v1/pools */
  "/v1/pools": {
    pools: [
      { id: "voice-a100-us-east",       status: "ok",   util_pct: 64, gpus: 8,  region: "us-east-1" },
      { id: "interactive-h100-us-east", status: "ok",   util_pct: 71, gpus: 4,  region: "us-east-1" },
      { id: "batch-a100-us-west",       status: "ok",   util_pct: 88, gpus: 12, region: "us-west-2" }
    ]
  },

  /* GET /v1/placement/feed (SSE) — replayed rows */
  "/v1/placement/feed": [
    { req: "req_8f31c2", tier: "voice",       pool: "voice-a100-us-east",       reason: "affinity: warm KV",         ttft_ms: 121, decide_ms: 0.8 },
    { req: "req_8f31d9", tier: "interactive", pool: "interactive-h100-us-east", reason: "least-loaded",              ttft_ms: 244, decide_ms: 0.6 },
    { req: "req_8f31e4", tier: "voice",       pool: "voice-a100-us-east",       reason: "affinity: warm KV",         ttft_ms: 109, decide_ms: 0.7 },
    { req: "req_8f31f0", tier: "interactive", pool: "batch-a100-us-west",       reason: "spill: primary saturated",  ttft_ms: 391, decide_ms: 1.2 },
    { req: "req_8f3202", tier: "voice",       pool: "voice-a100-us-east",       reason: "least-loaded",              ttft_ms: 133, decide_ms: 0.5 },
    { req: "req_8f3211", tier: "interactive", pool: "interactive-h100-us-east", reason: "affinity: warm KV",         ttft_ms: 228, decide_ms: 0.6 },
    { req: "req_8f321c", tier: "voice",       pool: "voice-a100-us-east",       reason: "affinity: warm KV",         ttft_ms: 115, decide_ms: 0.9 },
    { req: "req_8f322e", tier: "interactive", pool: "interactive-h100-us-east", reason: "least-loaded",              ttft_ms: 251, decide_ms: 0.7 },
    { req: "req_8f3240", tier: "voice",       pool: "voice-a100-us-east",       reason: "affinity: warm KV",         ttft_ms: 104, decide_ms: 0.6 },
    { req: "req_8f3252", tier: "interactive", pool: "batch-a100-us-west",       reason: "spill: primary saturated",  ttft_ms: 402, decide_ms: 1.1 },
    { req: "req_8f3266", tier: "voice",       pool: "voice-a100-us-east",       reason: "least-loaded",              ttft_ms: 127, decide_ms: 0.5 },
    { req: "req_8f3278", tier: "interactive", pool: "interactive-h100-us-east", reason: "affinity: warm KV",         ttft_ms: 236, decide_ms: 0.8 }
  ],

  /* GET /v1/incidents */
  "/v1/incidents": [
    {
      id: "inc_20260701_04",
      title: "TPOT breach on batch-a100-us-west (driver fault, GPU 7)",
      live: false,
      mttr_s: 42,
      agent: "reliability-agent v0.9",
      phase_ms: { detect: 4200, diagnose: 11800, resolve: 26000 },
      actions: [
        { t: "+0.0s",  kind: "detect",   text: "breach_rate 0.087 > 0.05 on batch-a100-us-west (window 60s, n=412)" },
        { t: "+4.2s",  kind: "probe",    text: "probe gpu-7: TPOT 214ms (slo 60ms) — FAIL" },
        { t: "+9.1s",  kind: "probe",    text: "probe gpu-3: TPOT 41ms — pass; fault isolated to gpu-7" },
        { t: "+16.0s", kind: "diagnose", text: "xid 79 in dmesg on gpu-7: fallen off the bus" },
        { t: "+16.2s", kind: "act",      text: "cordon gpu-7; drain 3 sessions (graceful, KV migrated)" },
        { t: "+38.4s", kind: "act",      text: "probe gpu-7 replacement: TPOT 39ms — pass ×3" },
        { t: "+42.0s", kind: "resolve",  text: "reinstated; breach_rate 0.00; incident closed" }
      ],
      postmortem_url: "#postmortem-inc_20260701_04"
    }
  ],

  /* GET /v1/releases/active */
  "/v1/releases/active": {
    version: "v2026.07.02-rc3",
    strategy: "canary 5% → 50% → 100%",
    model: "qwen3-235b-a22b-fp8"
  },

  /* GET /v1/learning/policy-eval */
  "/v1/learning/policy-eval": {
    default_config: {
      breach_rate_threshold: 0.05,
      min_samples: 200,
      probe_interval_s: 30,
      probes_to_reinstate: 3,
      cooldown_s: 300,
      probe_slo_ms: 60,
      escalate_after_failures: 5
    },
    proposed_config: {
      breach_rate_threshold: 0.032,
      min_samples: 120,
      probe_interval_s: 18,
      probes_to_reinstate: 3,
      cooldown_s: 240,
      probe_slo_ms: 60,
      escalate_after_failures: 4
    },
    holdout: {
      default:  { mttr_p50: 61.0, escalations: 9, probes: 1240 },
      proposed: { mttr_p50: 42.5, escalations: 7, probes: 1615 }
    },
    reward_curve: [-1.42,-1.31,-1.18,-1.02,-0.94,-0.81,-0.72,-0.66,-0.58,-0.49,-0.44,-0.41,-0.36,-0.34,-0.31,-0.29,-0.28,-0.26,-0.25,-0.25]
  },

  /* MANAGE — shapes designed per brief (no contract endpoint yet) */
  "/v1/manage/options": {
    pools: [
      {
        id: "batch-a100-us-west",
        status: "warn",
        risk: "util 88%; TPOT p95 trending +9% over 6h; 2 spill placements in last 5m",
        options: [
          {
            kind: "fleet",
            label: "Fleet upgrade — add 4× A100",
            consequence_text: "Capacity +33%. Cost +$11.80/h while attached. No latency impact during scale-up; new GPUs take traffic after warm-up (~4 min).",
            mutation_preview: "POST /v1/pools/batch-a100-us-west/scale\n{ \"add_gpus\": 4, \"warmup\": true }"
          },
          {
            kind: "model",
            label: "Model upgrade — switch to fp8 build",
            consequence_text: "TPOT −18% expected. Requires rolling restart: p99 TTFT degrades up to +400ms during KV re-warm (~9 min). No cost change.",
            mutation_preview: "POST /v1/pools/batch-a100-us-west/model\n{ \"model\": \"qwen3-235b-a22b-fp8\", \"rollout\": \"rolling\" }"
          },
          {
            kind: "spill",
            label: "Enable spill to us-east interactive pool",
            consequence_text: "Absorbs overflow now. Spilled requests pay +60–90ms TTFT (cross-region) and lose KV affinity. Cost +$0.021/Mtok on spilled traffic only.",
            mutation_preview: "POST /v1/pools/batch-a100-us-west/spill\n{ \"target\": \"interactive-h100-us-east\", \"max_pct\": 20 }"
          }
        ],
        drain: {
          modes: ["graceful", "immediate"],
          steps: {
            graceful: [
              "Stop new placements to affected GPUs",
              "Migrate KV caches for 14 active sessions (est 90s)",
              "Wait for in-flight decode to finish (max 120s)",
              "Cordon and detach"
            ],
            immediate: [
              "Stop new placements to affected GPUs",
              "Abort 14 active sessions (clients see errors)",
              "Cordon and detach now"
            ]
          }
        }
      }
    ]
  },

  /* DEPLOY — timeline shape designed per brief (only /v1/releases/active is in contract) */
  "/v1/releases/timeline": {
    version: "v2026.07.02-rc3",
    model: "qwen3-235b-a22b-fp8",
    strategy: "canary 5% → 50% → 100%",
    tier_target: "interactive",
    attempts: [
      { n: 1, at: "2026-07-02 09:14 UTC", stage: "canary 5%",  outcome: "rolled_back",
        note: "TPOT p99 62.4ms > slo 60ms on canary after 8 min; auto-rollback (policy: breach_rate 0.061 > 0.05)" },
      { n: 2, at: "2026-07-02 11:02 UTC", stage: "canary 5%",  outcome: "passed",
        note: "kv-cache preallocation fix; TPOT p99 54.1ms over 30 min, breach_rate 0.004" },
      { n: 3, at: "2026-07-02 11:40 UTC", stage: "canary 50%", outcome: "passed",
        note: "held 45 min; TPOT p99 55.0ms; cost/Mtok $0.421 (−1.4% vs prior)" },
      { n: 4, at: "2026-07-02 12:31 UTC", stage: "100% live",  outcome: "live",
        note: "full fleet; guardrail probes green ×12; prior build kept warm 24h for instant rollback" }
    ]
  },

  /* ROADMAP — product findings (static content) */
  "/v1/roadmap": [
    { rank: 1, title: "Cold-start outliers dominate interactive p99",
      finding: "1 cold start in a 14-sample window renders TTFT p99 meaningless (91.2s). Percentiles need cold-start exclusion plus a separate cold-start SLI.",
      impact: "high", effort: "medium", status: "proposed" },
    { rank: 2, title: "KV-aware drain should be the default",
      finding: "Graceful drain migrated all 14 sessions in the July 1 incident with zero client errors; immediate drain would have errored all of them.",
      impact: "high", effort: "low", status: "in review" },
    { rank: 3, title: "Promote learned probe policy",
      finding: "Held-out eval shows MTTR p50 −30% (61.0s → 42.5s) for +30% probe volume. Governed promote is ready; needs one approver.",
      impact: "high", effort: "low", status: "ready" },
    { rank: 4, title: "Spill placements need a budget",
      finding: "Spill saves availability but silently charges +60–90ms TTFT. Cap spill at a per-tier percentage and surface it in the placement feed.",
      impact: "medium", effort: "medium", status: "proposed" },
    { rank: 5, title: "Replay mode for postmortems",
      finding: "Recorded traces (placement feed + incident transcript) replayed against the same board make postmortems self-serve.",
      impact: "medium", effort: "high", status: "proposed" }
  ]
};
