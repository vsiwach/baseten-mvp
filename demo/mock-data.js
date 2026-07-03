/* ============================================================
   mock-data.js — the ONLY place mock data lives.
   Every getter mirrors a real endpoint shape EXACTLY.
   Integration: replace each MockAPI.get* body with a real
   fetch(...) and MockAPI.subscribeFeed with a real EventSource.
   The simulation below only exists so the mockup moves; it
   never adds fields that are not in the contract.
   ============================================================ */
(function () {
  "use strict";

  /* ---------------- Board state machine ----------------
     HEALTHY -> (injectChaos) DEGRADING -> LIVE_INCIDENT -> HEALTHY
     REPLAY runs the identical script from recorded traces. */
  const STATES = ["HEALTHY", "DEGRADING", "LIVE_INCIDENT", "REPLAY"];
  let boardState = "HEALTHY";
  let replayActive = false;
  const stateSubs = new Set();

  function setState(s) {
    boardState = s;
    stateSubs.forEach((cb) => cb(boardState, { replay: replayActive }));
  }

  /* ---------------- Baseline captures (real values) -------------- */
  const SPARK_N = 40;
  const baseSpark = (base, jitter) =>
    Array.from({ length: SPARK_N }, () => +(base + (Math.random() - 0.5) * jitter).toFixed(2));

  const hero = {
    tpot_p99_ms: 34.8,
    tpot_slo_ms: 60,
    tpot_delta_pct: -6.2,
    cost_per_mtok_usd: 2.17,
    cost_delta_pct: -27,
    mttr_s: 8.8,
    mttr_delta_pct: -98.9,
    spark: { tpot: baseSpark(34.8, 4), cost: baseSpark(2.17, 0.14) },
  };

  const mkHist = (edges, counts) => ({ edges, counts });

  const slo = {
    pools: [
      {
        id: "baseten-l4",
        health: 100,
        status: "ok",
        ttft: {
          p50: 349.8, p95: 460.1, p99: 484.7,
          hist: mkHist([250, 300, 350, 400, 450, 500, 550], [4, 18, 26, 14, 6, 2]),
        },
        tpot: {
          p50: 28.6, p95: 31.6, p99: 34.0,
          hist: mkHist([24, 27, 30, 33, 36, 39], [9, 24, 21, 8, 2]),
        },
      },
      {
        id: "model-api",
        health: 100,
        status: "ok",
        ttft: {
          p50: 402.5, p95: 468.9, p99: 491.3,
          hist: mkHist([300, 350, 400, 450, 500, 550], [8, 22, 24, 9, 3]),
        },
        tpot: {
          p50: 31.2, p95: 36.4, p99: 41.7,
          hist: mkHist([27, 30, 33, 36, 39, 42], [12, 22, 15, 7, 3]),
        },
      },
    ],
  };

  const pools = {
    pools: [
      { id: "baseten-l4", status: "steady", util_pct: 61 },
      { id: "model-api", status: "steady", util_pct: 34 },
    ],
  };

  const releases = { model: "qwen3-8b-awq", stage: "prod", last_rollback: null };

  /* Resolved incident (real capture). A live one is cloned from this
     during the chaos / replay script. */
  const resolvedIncident = {
    id: "INC-0001",
    title: "baseten-l4 breaching serving SLO \u2014 50% of recent requests",
    ts: "2026-07-03T17:42:11Z",
    live: false,
    mttr_s: 8.8,
    agent: true,
    phase_ms: { detect: 1200, diagnose: 2100, resolve: 5500 },
    actions: [
      "detected SLO breach rate 50% over 6 requests on baseten-l4",
      "quarantined baseten-l4; traffic spills to healthy pools",
      "probe failed (531ms)",
      "probe passed (364ms)",
      "probe passed (352ms)",
      "reinstated baseten-l4 \u2014 2 consecutive probes within SLO",
    ],
    postmortem_url: "/postmortems/INC-0001",
  };
  let incidents = [resolvedIncident];
  let liveIncident = null;

  /* ---------------- Learning episodes (contract shape) ------------ */
  const episodes = [
    {
      episode_id: "EP-0001",
      source: "INC-0001",
      policy: {
        breach_rate_threshold: 0.5,
        probe_interval_s: 3,
        probes_to_reinstate: 2,
        probe_slo_ms: 500,
        escalate_after_failures: 5,
      },
      probes: [
        { ok: false, ms: 531 },
        { ok: true, ms: 364 },
        { ok: true, ms: 352 },
      ],
      outcome: { resolved: true, mttr_s: 8.8, quarantined: true, escalated: false },
      reward: {
        total: 1.2,
        shaping: { resolved_bonus: 10, mttr_penalty: -8.8, escalation_penalty: 0 },
      },
    },
  ];

  /* ---------------- Deploy timeline (act 1, static JSON) ----------
     Shape: {attempt, ts, outcome, stage, error, diagnosis,
             citation:{title,url}, duration_s}
     PLACEHOLDER content — replace with the real 6-attempt JSON
     from the repo before the demo. */
  const deployTimeline = {
    model: "Qwen3-8B-AWQ",
    target: "dedicated T4 \u00b7 custom Truss \u00b7 vLLM",
    attempts: [
      {
        attempt: 1, ts: "16:02", outcome: "failed", stage: "truss push",
        error: "config validation: unsupported python_version in config.yaml",
        diagnosis: "Agent: Truss config schema pins supported runtimes; py312 not accepted for this base image \u2014 set py311.",
        citation: { title: "Truss config reference", url: "https://docs.baseten.co/truss/reference/config" },
        duration_s: 41,
      },
      {
        attempt: 2, ts: "16:11", outcome: "failed", stage: "image build",
        error: "pip resolution conflict: vllm requires torch pinned below installed version",
        diagnosis: "Agent: base image ships newer torch; pin vllm + torch pair per docs compatibility matrix.",
        citation: { title: "Custom model dependencies", url: "https://docs.baseten.co/deploy/guides/custom-model" },
        duration_s: 388,
      },
      {
        attempt: 3, ts: "16:24", outcome: "failed", stage: "model load",
        error: "AWQ marlin kernel requires compute capability >= 8.0 (T4 is sm_75)",
        diagnosis: "Agent: T4 can't run marlin; force quantization=awq (gemm kernels) in vLLM engine args.",
        citation: { title: "GPU instance types", url: "https://docs.baseten.co/deploy/reference/instances" },
        duration_s: 512,
      },
      {
        attempt: 4, ts: "16:41", outcome: "failed", stage: "model load",
        error: "CUDA out of memory allocating KV cache (16GB T4)",
        diagnosis: "Agent: default max_model_len oversizes KV cache on 16GB; reduce max_model_len and gpu_memory_utilization.",
        citation: { title: "vLLM engine configuration", url: "https://docs.baseten.co/deploy/guides/vllm" },
        duration_s: 496,
      },
      {
        attempt: 5, ts: "16:58", outcome: "failed", stage: "health check",
        error: "readiness probe timed out before weights finished loading",
        diagnosis: "Agent: cold load exceeds default readiness window; raise health-check timeout in resources config.",
        citation: { title: "Health checks & readiness", url: "https://docs.baseten.co/deploy/reference/health-checks" },
        duration_s: 611,
      },
      {
        attempt: 6, ts: "17:15", outcome: "failed", stage: "invoke",
        error: "424 FAILED_DEPENDENCY on first /predict \u2014 request schema mismatch",
        diagnosis: "Agent: Truss predict expects wrapped input; align client payload with model_input schema.",
        citation: { title: "Calling your model", url: "https://docs.baseten.co/invoke/quickstart" },
        duration_s: 187,
      },
      {
        attempt: 7, ts: "17:29", outcome: "live", stage: "live",
        error: null,
        diagnosis: "Agent: deployment healthy \u2014 first token 349ms, streaming stable on dedicated T4.",
        citation: { title: "Deployment statuses", url: "https://docs.baseten.co/deploy/reference/statuses" },
        duration_s: 344,
      },
    ],
  };

  /* ================= Placement feed simulation ================= */
  const feedSubs = new Set();
  let reqCounter = 143;
  let feedTimer = null;

  const TIERS = ["realtime", "realtime", "realtime", "batch"];
  function nextFeedItem() {
    reqCounter += 1;
    const tier = TIERS[Math.floor(Math.random() * TIERS.length)];
    let replica, reason, ttftBase;
    const l4Down = boardState === "LIVE_INCIDENT" || (replayActive && boardState === "LIVE_INCIDENT");
    if (l4Down) {
      replica = "model-api-spill";
      reason = "quarantine_spill";
      ttftBase = 405;
    } else if (boardState === "DEGRADING" && Math.random() < 0.5) {
      replica = "baseten-l4";
      reason = "affinity_place";
      ttftBase = 640; // degraded pool
    } else if (tier === "batch") {
      replica = "model-api";
      reason = "cost_place";
      ttftBase = 402;
    } else {
      replica = "baseten-l4";
      reason = "affinity_place";
      ttftBase = 350;
    }
    return {
      req: "#" + String(reqCounter).padStart(4, "0"),
      wl_tier: tier,
      replica,
      reason,
      ttft_ms: +(ttftBase + (Math.random() - 0.4) * 40).toFixed(1),
      decide_ms: +(0.2 + Math.random() * 0.4).toFixed(2),
    };
  }

  function startFeed() {
    if (feedTimer) return;
    const tick = () => {
      const item = nextFeedItem();
      feedSubs.forEach((cb) => cb(item));
      feedTimer = setTimeout(tick, 700 + Math.random() * 900);
    };
    feedTimer = setTimeout(tick, 400);
  }

  /* ================= Chaos / replay script =================
     Timings mirror the real INC-0001 trace:
     degrading ~4s -> incident 0s detect .. 8.8s resolved. */
  let scriptRunning = false;
  let incidentStartedAt = null;

  function runIncidentScript({ replay }) {
    if (scriptRunning) return;
    scriptRunning = true;
    replayActive = !!replay;
    const l4slo = slo.pools[0];
    const l4pool = pools.pools[0];

    /* Phase A: degradation visible in telemetry */
    setState(replay ? "REPLAY" : "DEGRADING");
    if (replay) setTimeout(() => setState("DEGRADING"), 10);
    l4slo.status = "warn"; l4slo.health = 72;
    l4slo.ttft.p50 = 583.4; l4slo.ttft.p95 = 741.2; l4slo.ttft.p99 = 802.6;
    l4slo.tpot.p99 = 47.3;
    l4pool.status = "warn"; l4pool.util_pct = 78;
    hero.tpot_p99_ms = 47.3;

    /* Phase B: incident opens after breach threshold is hit (~4s) */
    setTimeout(() => {
      incidentStartedAt = performance.now();
      liveIncident = {
        ...resolvedIncident,
        id: replay ? "INC-0001" : "INC-0002",
        ts: new Date().toISOString(),
        live: true,
        mttr_s: 0,
        actions: [],
      };
      incidents = [liveIncident, ...incidents.filter((i) => i.id !== liveIncident.id)];
      l4slo.status = "breach"; l4slo.health = 41;
      l4pool.status = "warn"; l4pool.util_pct = 12; // quarantined shortly after
      setState("LIVE_INCIDENT");

      /* Action transcript lands on the real trace offsets (ms) */
      const script = [
        [1200, resolvedIncident.actions[0]],
        [2400, resolvedIncident.actions[1]],
        [3300, resolvedIncident.actions[2]],
        [5600, resolvedIncident.actions[3]],
        [7900, resolvedIncident.actions[4]],
        [8800, resolvedIncident.actions[5]],
      ];
      script.forEach(([ms, action]) => {
        setTimeout(() => {
          if (liveIncident) liveIncident.actions.push(action);
        }, ms);
      });

      /* Resolution at 8.8s */
      setTimeout(() => {
        liveIncident.live = false;
        liveIncident.mttr_s = 8.8;
        liveIncident = null;
        incidentStartedAt = null;
        l4slo.status = "ok"; l4slo.health = 100;
        l4slo.ttft.p50 = 349.8; l4slo.ttft.p95 = 460.1; l4slo.ttft.p99 = 484.7;
        l4slo.tpot.p99 = 34.0;
        l4pool.status = "steady"; l4pool.util_pct = 61;
        hero.tpot_p99_ms = 34.8;
        if (!replay && !episodes.some((e) => e.source === "INC-0002")) {
          episodes.unshift({ ...episodes[episodes.length - 1], episode_id: "EP-0002", source: "INC-0002" });
        }
        replayActive = false;
        scriptRunning = false;
        setState("HEALTHY");
      }, 8800);
    }, 4000);
  }

  /* ================= Public API (mirrors endpoints) ============= */
  window.MockAPI = {
    /* GET /v1/metrics/hero */
    getHero: async () => JSON.parse(JSON.stringify(hero)),
    /* GET /v1/metrics/slo */
    getSLO: async () => JSON.parse(JSON.stringify(slo)),
    /* GET /v1/pools */
    getPools: async () => JSON.parse(JSON.stringify(pools)),
    /* GET /v1/incidents */
    getIncidents: async () =>
      incidents.map((i) => ({
        ...i,
        actions: [...i.actions],
        /* live mttr counts up client-side from ts; we surface elapsed here */
        mttr_s: i.live && incidentStartedAt
          ? +((performance.now() - incidentStartedAt) / 1000).toFixed(1)
          : i.mttr_s,
      })),
    /* GET /v1/releases/active */
    getReleases: async () => ({ ...releases }),
    /* GET /v1/learning/episodes */
    getLearningEpisodes: async () => JSON.parse(JSON.stringify(episodes)),
    /* static deploy timeline JSON (act 1) */
    getDeployTimeline: async () => JSON.parse(JSON.stringify(deployTimeline)),

    /* GET /v1/placement/feed (SSE) */
    subscribeFeed(cb) { feedSubs.add(cb); startFeed(); return () => feedSubs.delete(cb); },

    /* Board state (derived from telemetry in the real system) */
    getState: () => boardState,
    isReplay: () => replayActive,
    subscribeState(cb) { stateSubs.add(cb); cb(boardState, { replay: replayActive }); return () => stateSubs.delete(cb); },

    /* POST /v1/dev/chaos — REAL fault injection in integration */
    injectChaos() { runIncidentScript({ replay: false }); },
    /* Replay playback of recorded traces (repo ships them) */
    startReplay() { runIncidentScript({ replay: true }); },

    STATES,
  };
})();
