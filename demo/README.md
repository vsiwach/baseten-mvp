# Handoff: Inference Control demo board (baseten-mvp)

## Overview
Presentation layer for a live interview demo of the baseten-mvp router
control plane (github.com/vsiwach/baseten-mvp): a live ops board
(`devboard.html`, acts 2–5) and an agent-assisted deploy timeline
(`deploy.html`, act 1). The backend is real; this package is the frontend
to wire against it.

## About the design files — READ THIS FIRST
Unlike a typical handoff, these files are **intended to ship as-is** into
the repo. Hard constraints they already satisfy: vanilla HTML/CSS/JS, no
build step, no CDNs/fonts (offline-capable), one file per screen + shared
`tokens.css`, all mock data isolated in `mock-data.js`.

**Do NOT recreate these in a framework. Do NOT restyle.** The integration
task is exactly one thing: replace the mock data layer with real calls.

## Fidelity
High-fidelity and final. Layout, colors, type scale, copy, and animation
behavior are as intended for the demo. Any visual change is out of scope.

## The integration task
All screen code consumes only `window.MockAPI` (defined in
`mock-data.js`). Replace each member's body; keep signatures identical:

| MockAPI member | Replace with |
|---|---|
| `getHero()` | `fetch('/v1/metrics/hero').then(r => r.json())` |
| `getSLO()` | `GET /v1/metrics/slo` |
| `getPools()` | `GET /v1/pools` |
| `getIncidents()` | `GET /v1/incidents` |
| `getReleases()` | `GET /v1/releases/active` |
| `getLearningEpisodes()` | `GET /v1/learning/episodes` |
| `subscribeFeed(cb)` | `new EventSource('/v1/placement/feed')`; call `cb(JSON.parse(ev.data))` per message; return an unsubscribe fn that closes it |
| `injectChaos()` | `POST /v1/dev/chaos` |
| `startReplay()` | start playback of the repo's recorded traces through the same getters (keep the mock replay engine as the fallback implementation) |
| `getState()` / `subscribeState(cb)` | derive from telemetry, never hard-set: REPLAY if replay active, else LIVE_INCIDENT if `incidents[0].live`, else DEGRADING if any pool `status !== "ok"`, else HEALTHY. Call every subscriber on change. |
| `getDeployTimeline()` | load the real 6-attempt static JSON (repo capture). Mock attempts are marked PLACEHOLDER in `mock-data.js`. |

Rules:
- Response shapes are the contract in DESIGN.md §3 — render code reads
  fields verbatim; do not reshape.
- Live-incident `mttr_s`: the board polls `/v1/incidents` at 250ms and
  renders `mttr_s` directly. If the real endpoint returns a static start
  ts instead of elapsed seconds, compute elapsed in the fetcher, not in
  render code.
- Keep `mock-data.js` loadable as the offline REPLAY fallback (a simple
  flag or query param, e.g. `?mock=1`, choosing which API object to
  install on `window.MockAPI`).

## Screens
- **devboard.html** — single fixed viewport (no scroll, 100vh grid):
  topbar (release chip, derived state chip, chaos/replay buttons) · hero
  KPIs (TPOT p99 vs SLO, blended $/Mtok, MTTR — the emotional core) ·
  pools panel (health/util bars, TTFT/TPOT histograms + p50/p95/p99) ·
  streaming placement feed (14-row cap, newest-first) · incident panel
  (live MTTR counter, detect→diagnose→resolve phase bar, action
  transcript, agent-off "never" baseline, postmortem link) · learning
  panel (RL episode: policy grid, probes, shaped reward).
- **deploy.html** — scrollable vertical timeline: 6 failed attempts →
  LIVE, each with monospace error block, agent diagnosis, docs citation
  pill.

Full component→field mapping, interaction spec, and the 4-state behavior
matrix (HEALTHY / DEGRADING / LIVE INCIDENT / REPLAY) are in
**DESIGN.md** — treat it as the source of truth. Presenter flow and
timings are in **DEMO_SCRIPT.md**.

## Interactions & behavior (summary; details in DESIGN.md §4–5)
- Inject chaos → real `POST /v1/dev/chaos`; board reacts only via
  telemetry. Buttons disabled outside HEALTHY.
- Live incident: incident panel red glow, board dims (`.board.dimmed`),
  MTTR counts up in hero + panel, phase bar fills from `phase_ms`,
  `actions[]` stream in; everything freezes/greens at `live:false`.
- Polling cadence: pools 2s, hero 3s, learning 4s, incidents 250ms,
  feed = SSE push.

## Design tokens
All in `tokens.css` (single source): surfaces `#0a0e13/#10151c/#151b24/
#1a222d`, strokes `#1e2732/#2a3644`, text `#e8eef4/#9aa7b4/#5f6c7a`,
accent cyan `#3fd8e4`, ok `#3fd8a0`, warn `#f0b34e`, danger `#f06355`,
replay `#9d8cff`. System font stacks only. Type scale: hero 64px, big
34px, panel titles 17px, body 14px, micro-labels 11px. Radii 14/10/6px.

## Assets
None. All graphics are inline SVG generated from endpoint data
(sparklines, histograms). No images, icon fonts, or external files.

## Files
- `devboard.html` — live board (acts 2–5), app JS inline at bottom
- `deploy.html` — deploy timeline (act 1)
- `tokens.css` — shared tokens + primitives
- `mock-data.js` — MockAPI + simulation; the ONLY file to modify
- `DESIGN.md` — layout system, endpoint mapping, state matrix
- `DEMO_SCRIPT.md` — presenter storyboard + pre-flight checklist

## Acceptance checklist
- [ ] Board runs against live backend with `mock-data.js` fetchers
      replaced; zero changes to render code or CSS.
- [ ] `?mock=1` (or equivalent) still runs fully offline for REPLAY.
- [ ] Inject chaos triggers real fault injection; incident resolves and
      MTTR freezes at the real value; buttons re-arm on HEALTHY.
- [ ] Deploy timeline renders the repo's real attempt JSON.
- [ ] No displayed value originates outside the contract or replay data.
