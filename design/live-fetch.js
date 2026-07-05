/* ============================================================
   live-fetch.js — live-data overlay, loaded AFTER console.js by
   the router's /board/{page} routes (never by the raw package).
   A later `function fetchJSON` declaration overrides the mock one
   in console.js; endpoints the router serves come from the live
   API, everything else stays on window.MOCK. See design/DESIGN.md
   (2026-07-04 deviations).
   ============================================================ */

const LIVE = new Set([
  "/v1/metrics/hero", "/v1/metrics/slo", "/v1/pools", "/v1/incidents",
  "/v1/releases/active", "/v1/learning/policy-eval", "/v1/manage/options",
  "/v1/releases/timeline", "/v1/placement/feed"
]);
/* The board reads the feed as an array; the live SSE stream stays at
   /v1/placement/feed — the board uses its snapshot lens instead. */
const LIVE_PATH_MAP = { "/v1/placement/feed": "/v1/placement/feed/snapshot" };

async function fetchJSON(path) {
  if (!LIVE.has(path)) return structuredClone(window.MOCK[path]);
  try {
    const resp = await fetch(LIVE_PATH_MAP[path] || path);
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return await resp.json();
  } catch (e) {
    markFallback();
    return structuredClone(window.MOCK[path]);
  }
}

/* Served at /board/{page}: point the shared nav tabs at the live routes. */
TABS.forEach(t => { t[1] = "/board/" + t[1].replace(".html", ""); });

document.body.dataset.live = "true";

function markFallback() {
  if (document.getElementById("data-source-note")) return;
  const note = document.createElement("div");
  note.id = "data-source-note";
  note.className = "caption";
  note.style.position = "fixed";
  note.style.bottom = "8px";
  note.style.right = "12px";
  note.textContent = "some panels: sample data (endpoint pending)";
  document.body.appendChild(note);
}
