/* ============================================================
   live-data.js — the LIVE twin of mock-data.js.
   Implements the exact MockAPI interface over the router's real
   endpoints (same origin: this file is served by the router at
   /demoboard). Board state derives from telemetry; injectChaos
   performs REAL fault injection and drives real traffic so the
   incident agent has samples to detect.
   ============================================================ */
(function () {
  "use strict";

  const j = (url) => fetch(url).then((r) => r.json());
  const STATES = ["HEALTHY", "DEGRADING", "LIVE_INCIDENT", "REPLAY"];
  let boardState = "HEALTHY";
  const stateSubs = new Set();

  function setState(s) {
    if (s === boardState) return;
    boardState = s;
    stateSubs.forEach((cb) => cb(boardState, { replay: false }));
  }

  /* ---- state derivation: incidents + pool health, polled ---- */
  async function deriveState() {
    try {
      const [incidents, pools] = await Promise.all([
        j("/v1/incidents"), j("/v1/pools"),
      ]);
      if (incidents.some((i) => i.live)) return setState("LIVE_INCIDENT");
      if ((pools.pools || []).some((p) => p.status && p.status !== "steady" && p.status !== "ok"))
        return setState("DEGRADING");
      setState("HEALTHY");
    } catch (e) { /* router restarting — keep last state */ }
  }
  setInterval(deriveState, 2000);
  deriveState();

  /* ---- demo load runs SERVER-SIDE (/v1/dev/load): background tabs
     throttle JS timers to ~1/min, which starves breach detection ---- */
  function driveLoad(seconds) {
    fetch("/v1/dev/load", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "qwen3-8b", rps: 1.5, seconds }),
    }).catch(() => {});
  }

  /* ---- REAL chaos: one fire-and-forget call; the whole inject ->
     detect -> clear sequence runs SERVER-SIDE (a throttled background
     tab can't reliably drive a multi-step sequence) ---- */
  async function injectChaos() {
    await fetch("/v1/dev/drill", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "qwen3-8b", latency_ms: 600 }),
    }).catch(() => {});
  }

  /* ---- SSE placement feed; adapt live names to board names ---- */
  function subscribeFeed(cb) {
    const es = new EventSource("/v1/placement/feed");
    es.onmessage = (ev) => {
      try {
        const it = JSON.parse(ev.data);
        cb({ req: it.req, wl_tier: it.tier, replica: it.pool,
             reason: it.reason, ttft_ms: it.ttft_ms || 0,
             decide_ms: it.decide_ms || 0 });
      } catch (e) { /* keepalive */ }
    };
    driveLoad(20);                    /* board opens with real traffic */
    return () => es.close();
  }

  window.MockAPI = {
    getHero: () => j("/v1/metrics/hero"),
    getSLO: () => j("/v1/metrics/slo").then((s) => ({
      pools: (s.pools || []).map((p) => ({
        ...p,
        ttft: { ...p.ttft, hist: p.ttft?.hist || { edges: [0, 1], counts: [0] } },
        tpot: { ...p.tpot, hist: p.tpot?.hist || { edges: [0, 1], counts: [0] } },
      })),
    })),
    getPools: () => j("/v1/pools"),
    getIncidents: () => j("/v1/incidents"),
    getReleases: () => j("/v1/releases/active"),
    getLearningEpisodes: () => j("/v1/learning/episodes"),
    getDeployTimeline: () => j("/demo-assets/deploy-timeline.json"),
    subscribeFeed,
    getState: () => boardState,
    isReplay: () => false,
    subscribeState(cb) {
      stateSubs.add(cb); cb(boardState, { replay: false });
      return () => stateSubs.delete(cb);
    },
    injectChaos,
    startReplay() { window.location.href = "/replay/"; },
    STATES,
  };
})();
