/* ============================================================
   console.js — shared shell render + helpers.
   fetchJSON() is the single integration seam: swap the MOCK
   lookup for a real fetch() and every screen works unchanged.
   ============================================================ */

/* ---- Integration seam ---- */
async function fetchJSON(path) {
  // Real integration: return (await fetch(path)).json();
  return structuredClone(window.MOCK[path]);
}

/* ---- Formatting ---- */
const fmt = {
  ms(v) {
    if (v >= 10000) return (v / 1000).toFixed(1) + "s";
    if (v >= 1000) return (v / 1000).toFixed(2) + "s";
    return (Math.round(v * 10) / 10) + "ms";
  },
  s(v) { return v + "s"; },
  usd(v) { return "$" + v.toFixed(3); },
  pct(v) { return (v > 0 ? "+" : "") + v.toFixed(1) + "%"; },
  n(v) { return v.toLocaleString("en-US"); }
};

function histN(hist) { return hist.counts.reduce((a, b) => a + b, 0); }

/* Cold-start / low-sample qualifier: a p99 is "qualified" (amber, not red)
   when the sample is small or the tail sits in an outlier bucket far beyond
   the bulk of the distribution. */
function p99Qualifier(metric) {
  const n = histN(metric.hist);
  const flags = [];
  if (n < 50) flags.push("low sample (n=" + n + ")");
  if (metric.p99 > metric.p95 * 20) flags.push("includes cold start");
  return flags.length ? flags.join(" · ") : null;
}

/* ---- Board state (derived from telemetry, honest) ---- */
function deriveState(incidents, sloPools, replay) {
  if (replay) return "REPLAY";
  if (incidents.some(i => i.live)) return "LIVE INCIDENT";
  if (sloPools.some(p => p.status === "bad")) return "LIVE INCIDENT";
  if (sloPools.some(p => p.status === "warn")) return "DEGRADING";
  return "HEALTHY";
}

/* ---- Shared shell ---- */
const TABS = [
  ["Operate", "operate.html"],
  ["Deploy", "deploy.html"],
  ["Policy", "policy.html"],
  ["Manage", "manage.html"],
  ["Roadmap", "roadmap.html"]
];

async function renderShell(activeTab) {
  const [incidents, slo, release] = await Promise.all([
    fetchJSON("/v1/incidents"),
    fetchJSON("/v1/metrics/slo"),
    fetchJSON("/v1/releases/active")
  ]);
  const state = deriveState(incidents, slo.pools, false);

  const header = document.createElement("header");
  header.className = "topbar";
  header.innerHTML =
    '<span class="brand"><span class="mark" aria-hidden="true"></span>Reliability console</span>' +
    '<span class="workload" title="Workload">wkld: dedicated-inference / prod</span>' +
    '<span class="spacer"></span>' +
    '<span class="release">release ' + esc(release.version) + '</span>' +
    '<span class="state-chip" data-state="' + state + '" role="status">' +
      '<span class="dot" aria-hidden="true"></span>' + state.toLowerCase() + '</span>';

  const nav = document.createElement("nav");
  nav.className = "tabs";
  nav.setAttribute("aria-label", "Console sections");
  nav.innerHTML = TABS.map(([label, href]) =>
    '<a href="' + href + '"' + (label === activeTab ? ' aria-current="page"' : '') + '>' + label + '</a>'
  ).join("");

  document.body.prepend(nav);
  document.body.prepend(header);
  return { state, release };
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ---- SVG charts (inline, no libs) ---- */

/* Thin sparkline */
function sparkline(values, { w = 160, h = 36, stroke = "var(--accent)" } = {}) {
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) =>
    (i / (values.length - 1) * (w - 2) + 1).toFixed(1) + "," +
    ((1 - (v - min) / span) * (h - 6) + 3).toFixed(1)
  ).join(" ");
  return '<svg viewBox="0 0 ' + w + " " + h + '" width="' + w + '" height="' + h + '" role="img" aria-label="trend">' +
    '<polyline points="' + pts + '" fill="none" stroke="' + stroke + '" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>';
}

/* Histogram (small multiple) with optional SLO marker */
function histogram(hist, { w = 220, h = 44, slo = null, color = "var(--text-faint)" } = {}) {
  const counts = hist.counts, edges = hist.edges;
  const max = Math.max(...counts, 1);
  const bw = (w - (counts.length - 1) * 2) / counts.length;
  let bars = "";
  counts.forEach((c, i) => {
    const bh = Math.max(c / max * (h - 4), c > 0 ? 2 : 0.5);
    bars += '<rect x="' + (i * (bw + 2)).toFixed(1) + '" y="' + (h - bh).toFixed(1) +
      '" width="' + bw.toFixed(1) + '" height="' + bh.toFixed(1) + '" rx="1" fill="' + color + '"/>';
  });
  let marker = "";
  if (slo != null) {
    const lastEdge = edges[edges.length - 1];
    const x = Math.min(slo / lastEdge, 1) * w;
    marker = '<line x1="' + x.toFixed(1) + '" y1="0" x2="' + x.toFixed(1) + '" y2="' + h +
      '" stroke="var(--warn)" stroke-width="1" stroke-dasharray="2 3"/>';
  }
  return '<svg viewBox="0 0 ' + w + " " + h + '" width="' + w + '" height="' + h + '" role="img" aria-label="latency distribution">' + bars + marker + "</svg>";
}

/* Line chart for reward curve */
function lineChart(values, { w = 420, h = 120, stroke = "var(--accent)" } = {}) {
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) =>
    (i / (values.length - 1) * (w - 8) + 4).toFixed(1) + "," +
    ((1 - (v - min) / span) * (h - 16) + 8).toFixed(1)
  ).join(" ");
  return '<svg viewBox="0 0 ' + w + " " + h + '" width="100%" role="img" aria-label="reward curve" style="display:block">' +
    '<line x1="4" y1="' + (h - 8) + '" x2="' + (w - 4) + '" y2="' + (h - 8) + '" stroke="var(--border)" stroke-width="1"/>' +
    '<polyline points="' + pts + '" fill="none" stroke="' + stroke + '" stroke-width="1.5" stroke-linejoin="round"/></svg>';
}

/* Percentile dot row: p50/p95/p99 as mono values with series colors */
function pctlRow(metric, sloMs) {
  const q = p99Qualifier(metric);
  const p99Bad = !q && sloMs != null && metric.p99 > sloMs;
  return '<div style="display:flex; gap:14px; align-items:baseline">' +
    pctlVal("p50", metric.p50, "var(--p50)") +
    pctlVal("p95", metric.p95, "var(--p95)") +
    pctlVal("p99", metric.p99, q ? "var(--warn-text)" : (p99Bad ? "var(--bad-text)" : "var(--p99)")) +
    "</div>" +
    (q ? '<div class="qualifier" style="margin-top:6px">' + esc(q) + "</div>" : "");
}
function pctlVal(name, v, color) {
  return '<span style="display:inline-flex; flex-direction:column; gap:1px">' +
    '<span class="caption" style="color:' + color + '; font-family:var(--font-mono)">' + name + "</span>" +
    '<span class="num" style="font-size:var(--fs-md)">' + fmt.ms(v) + "</span></span>";
}

/* Delta chip: negative = improvement (green) for latency/cost/mttr */
function deltaChip(pct) {
  const good = pct <= 0;
  const color = good ? "var(--accent-strong)" : "var(--warn-text)";
  const arrow = pct <= 0 ? "▾" : "▴";
  return '<span class="num" style="font-size:var(--fs-label); color:' + color + '">' + arrow + " " + fmt.pct(pct) + "</span>";
}
