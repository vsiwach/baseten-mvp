# console-live — read-only Baseten fleet observer

**Live:** https://baseten-reliability-console.vercel.app — paste your Baseten
API key (it stays in your browser's memory; the proxy forwards it per-request
to api.baseten.co and never stores or logs it).

## Ship it

One click (imports this repo; set **Root Directory = `console-live`** when
prompted; you auth once in your own browser):

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/vsiwach/baseten-mvp&root-directory=console-live&project-name=baseten-reliability-console)

Or from a terminal: `cd console-live && vercel login && vercel --prod`

Run locally (no account, one command): `node console-live/server.js`
→ open http://localhost:4173 and paste your key.

A single-page console that connects to a real Baseten workspace with your API
key and shows, per production deployment: status, replicas, scale-to-zero
state, end-to-end latency percentiles vs voice (500ms) / interactive (800ms)
budgets, traffic volume + error split, cold-start detection, and exactly one
advisory recommendation per card. Every number is footnoted with the API call
it came from.

## Observe vs control boundary

This console is **observe-only**. It calls three GET endpoints of the Baseten
management API (`/v1/models`, `.../deployments`, `.../metrics`) and never
mutates anything. Recommendations are advisory text. Autonomous mitigation
(quarantine, spill, self-heal) requires a router in the request path — that
half lives in the recorded control-plane demo
([site-console/](../site-console/), live MTTR 8.8–9.2 s drills replayed from
real traces), not here. How the two layers relate to Baseten's own MCP+skill
toolkit: [docs/COMPETITIVE_LANDSCAPE.md](../docs/COMPETITIVE_LANDSCAPE.md).

## Run locally

```sh
node console-live/server.js        # http://localhost:4173 (PORT env overrides)
```

No build step, no npm deps. Paste your API key into the page; it is held in a
JS closure only.

## Deploy to Vercel

```sh
cd console-live && vercel deploy   # then `vercel --prod`
```

Vercel serves `index.html`/`tokens.css` statically and mounts
`api/baseten.js` as a serverless function at `/api/baseten`.

## Known limits (read before pointing this at a big fleet)

- **Refresh fan-out.** Each refresh issues `1 + M + 2P` API calls (models list,
  per-model deployment list, SUMMARY + SERIES metrics per production
  deployment). Two back-to-back refreshes on a 2-model workspace already drew a
  429 from the beta metrics endpoint (observed live). The client caps
  concurrency at 4 and honors `Retry-After` by pausing all polling, but there is
  no cross-refresh caching or incremental loading — at ~100 models a single
  refresh would be hundreds of calls and will rate-limit. A fleet-scale version
  needs a server-side aggregator/cache, not a browser fanning out per card.
- **A 429 mid-refresh aborts the remaining cards** (they show an inline error)
  and the grid is redrawn from scratch on every refresh, so previously loaded
  numbers are not kept as stale-while-refreshing.
- **Recommendations are heuristics** on two metrics over one window. The
  min_replica=1 advice requires the cold-start signature (steady p95 within the
  interactive budget, p99 above it, scale-to-zero enabled); cold-start-dominated
  or low-sample windows get "widen the window" instead of an autoscaling change.
- **Latency is end-to-end response time** (includes full token generation), not
  TTFT; the voice/interactive budgets are illustrative defaults, not per-model
  SLOs.

## Security notes

- The API key is pasted into a password field and kept in a closure variable —
  never in localStorage/sessionStorage/cookies, never in a query string.
- The browser sends it to the proxy as an `x-baseten-api-key` header; the
  proxy forwards it upstream as `Authorization: Api-Key …` and never logs,
  stores, or echoes it (logs are method + path + status only).
- The proxy allowlists exactly three GET path shapes and four query params;
  everything else is rejected (405/400/403). Upstream 401/429 (with
  `Retry-After`) pass through so the UI can react.
