/* ============================================================
   recording-data.js — the DEFAULT data source for the console.
   Plays site/session-recording.json (a real captured session on
   live Baseten infra) frame-accurately through the MockAPI
   interface. Not mock (real recorded values); not live (no
   backend) — a recording of a real incident at true speed.

   ?api=<router-url> overrides this with the live source
   (live-data.js is loaded instead by the page in that case).
   ============================================================ */
(function () {
  "use strict";

  const STATES = ["HEALTHY", "DEGRADING", "LIVE_INCIDENT", "REPLAY"];
  let rec = null, playing = false, clock = 0, startWall = 0;
  let boardState = "HEALTHY";
  const stateSubs = new Set();
  const feedSubs = new Set();

  const load = fetch("session-recording.json")
    .then((r) => r.json())
    .then((d) => { rec = d; });

  /* current recording time: paused until the incident is triggered so the
     console opens on a calm HEALTHY board, then plays through in real time. */
  function now() {
    return playing ? clock + (performance.now() - startWall) / 1000 : clock;
  }

  /* newest poll frame at or before time t */
  function pollAt(t) {
    if (!rec) return null;
    let hit = null;
    for (const f of rec.frames) {
      if (f.kind !== "poll") continue;
      if (f.t <= t) hit = f; else break;
    }
    return hit || rec.frames.find((f) => f.kind === "poll");
  }

  function deriveState(frame) {
    const incs = (frame && frame.incidents) || [];
    let s = "HEALTHY";
    if (incs.some((i) => i.live)) s = "LIVE_INCIDENT";
    else if ((frame && frame.pools ? frame.pools.pools : []).some(
      (p) => p.status && p.status !== "steady" && p.status !== "ok")) s = "DEGRADING";
    if (s !== boardState) {
      boardState = s;
      stateSubs.forEach((cb) => cb(boardState, { replay: true }));
    }
  }

  /* emit any feed items between two times to the live subscribers */
  let feedCursor = 0;
  function pumpFeed(t) {
    if (!rec) return;
    const items = rec.frames.filter((f) => f.kind === "feed");
    while (feedCursor < items.length && items[feedCursor].t <= t) {
      const it = items[feedCursor++].item;
      feedSubs.forEach((cb) => cb({
        req: it.req, wl_tier: it.tier, replica: it.pool,
        reason: it.reason, ttft_ms: it.ttft_ms || 0,
        decide_ms: it.decide_ms || 0,
      }));
    }
  }

  setInterval(() => { const t = now(); deriveState(pollAt(t)); pumpFeed(t); }, 250);

  const clone = (x) => JSON.parse(JSON.stringify(x));
  const field = async (key, fallback) => {
    await load;
    const f = pollAt(now());
    return f && f[key] != null ? clone(f[key]) : fallback;
  };

  window.MockAPI = {
    getHero: () => field("hero", {}),
    getSLO: () => field("slo", { pools: [] }),
    getPools: () => field("pools", { pools: [] }),
    getIncidents: () => field("incidents", []),
    getReleases: () => field("releases", {}),
    getLearningEpisodes: () => field("episodes", []),
    getDeployTimeline: async () => { await load; return clone(rec.deploy_timeline); },

    subscribeFeed(cb) { feedSubs.add(cb); return () => feedSubs.delete(cb); },

    getState: () => boardState,
    isReplay: () => true,
    subscribeState(cb) {
      stateSubs.add(cb); cb(boardState, { replay: true });
      return () => stateSubs.delete(cb);
    },

    /* "inject chaos" = play the recorded incident. Jump to 5s before the
       first live incident so playback opens on a brief calm shot and the
       incident fires within seconds (skips dead pre-roll). */
    async injectChaos() {
      await load;
      const firstInc = rec.frames.find(
        (f) => f.kind === "poll" && (f.incidents || []).some((i) => i.live));
      const start = firstInc ? Math.max(0, firstInc.t - 5) : 0;
      clock = start; feedCursor = rec.frames.filter(
        (f) => f.kind === "feed" && f.t <= start).length;
      startWall = performance.now(); playing = true;
    },
    async startReplay() { return this.injectChaos(); },

    /* recording metadata for the console's provenance line */
    async recordingMeta() { await load; return { recorded_at: rec.recorded_at,
      source: rec.source, duration_s: rec.duration_s }; },

    STATES,
  };
})();
