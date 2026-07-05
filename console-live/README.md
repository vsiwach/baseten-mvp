# console-live — Baseten fleet console (read-only by default, opt-in writes)

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

## Onboarding (`onboard.html`) — three legs, one handoff model

`/onboard.html` is the "get started" surface for people who do not have a
fleet yet. Three doors, hash-routed (`#explore`, `#dedicated`, and a link card
back to `/` for fleet operators):

1. **Which Model API should I use?** (`#explore`) — pick a task + latency tier,
   state your volume (requests/day × avg prompt/completion tokens →
   tokens/month), then load the **live** catalog via the proxy
   (`GET /api/baseten?host=inference&path=models`, Bearer auth). Models are
   ranked by a documented keyword/context-length task-fit heuristic, then
   blended price; every row has a "show math" expansion citing the formula,
   the numbers, and the API call with its time. Picking a row reveals curl +
   OpenAI-python snippets (from the baseten-onboard skill's handoff template)
   with the slug pre-filled and the key left as `$BASETEN_API_KEY`.
2. **Graduate to dedicated** (`#dedicated`) — inherits the leg-1 inputs and
   draws the serverless-vs-dedicated crossover: dedicated floor from the
   selected SKU's **live** `GET /v1/instance_type_prices` ($/min × 60 × H),
   serverless from the live blended $/Mtok, break-even + your-volume markers on
   a log-x chart. The JS math is test-pinned to
   `skills/baseten-onboard/scripts/crossover.py`'s self-test vectors. Below it:
   the proven hardware ladder (T4x8x32 first, with evidence citations) and the
   **agent handoff** — this console does not deploy models; deployment is
   executed by your AI agent via the baseten-onboard skill + Baseten MCP. The
   page generates the exact prompt (Claude Desktop and Claude Code tabs) from
   your choices; when the agent finishes it hands back a console deep link
   (`/?model=<model_id>`).
3. **I run a fleet** — the console itself (`/`).

If a live fetch fails, tables fall back to
`data/model-apis-snapshot.json` under a visible banner naming the snapshot's
`fetched_at` and the live error; snapshot and live numbers are never mixed in
one table.

### Fleet planner (index page, `placement-recommendation/v1`)

A collapsible **Fleet planner** panel above the cards compares, per production
deployment: SLO posture (the card's verdict), observed p95/p99 + volume,
dedicated $/mo (live instance price × 730 h × 1 replica, matched by
`instance_type_name`), and Model API $/mo at observed volume (cheapest fit
from the labeled snapshot). The recommendation slot renders the
`placement-recommendation/v1` contract: today `buildPlannerModel` emits kind
`measured-comparison` / status `pending-rl-artifact` ("the placement optimizer
(RL) is a pending feature"); a future RL policy artifact with the same schema
renders with **zero rework** — proved by fixtures in
`test/onboard_flow_test.mjs`. Measured latency evidence comes from
`data/measured-baselines.json` (warm TTFT 300–333 ms, cold load 148.2 s,
activation→ready 114 s — each entry cites its evidence file + date).

## Observe vs control boundary

This console is **observe-only by default**. It calls three GET endpoints of
the Baseten management API (`/v1/models`, `.../deployments`, `.../metrics`).
Recommendations are advisory text. Autonomous mitigation (quarantine, spill,
self-heal) requires a router in the request path — that half lives in the
recorded control-plane demo ([site-console/](../site-console/), live MTTR
8.8–9.2 s drills replayed from real traces), not here. How the two layers
relate to Baseten's own MCP+skill toolkit:
[docs/COMPETITIVE_LANDSCAPE.md](../docs/COMPETITIVE_LANDSCAPE.md).

### Write actions (opt-in)

"Enable write actions" in the header (off by default, in-memory only) reveals
manage controls: activate / deactivate, autoscaling min/max, and promote to
production for non-production deployments. Every mutation goes through one
confirm modal that displays the **exact** upstream call (method + path +
payload) plus an honest consequence line (billing, cold start, dropped
in-flight requests, rollback path). The write proxy (`api/baseten-write.js`,
POST-only, four allowlisted actions) recomputes that mutation string
server-side and rejects with 428 unless the request's `x-confirm-mutation`
header matches it exactly — a request that skipped the dialog cannot claim to
be confirmed. One mutation at a time; after acceptance the console polls the
deployment every 10 s (max 10 min) until it reaches the expected state, then
re-renders that model's card. These are deployment-level operations — there is
still no traffic-level drain or self-heal without a router in the path.

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
- **The fleet planner mixes price provenances in one table** (STAFF-SKEPTIC,
  2026-07-05): dedicated $/mo is live (`GET /v1/instance_type_prices`) while
  Model API $/mo comes from the dated snapshot — a deliberate, per-cell-labeled
  exception to the onboarding page's all-or-nothing rule (there is no snapshot
  for instance prices). A live catalog fetch through the same proxy
  (`host=inference`, any key) would remove the exception; until then the table
  header names the snapshot date.
- **Planner dedicated $/mo assumes exactly 1 replica × 730 h** even when
  `autoscaling_settings.min_replica > 1` is known to the same function — it
  under-quotes HA/voice fleets. The Model API option is the *cheapest blended
  price* in the snapshot, with **no capability matching** against the deployed
  model (a fine-tune has no serverless equivalent at any price). Both
  assumptions are printed in each row's evidence lines; the recommendation slot
  stays `pending-rl-artifact` partly because of them.
- **Instance prices are prefix-matched to `instance_type_name`** — an ambiguous
  SKU-name family could silently cite a neighboring SKU's price; the matched
  name is always printed in the evidence line so it is auditable.

## Security notes

- The API key is pasted into a password field and kept in a closure variable —
  never in localStorage/sessionStorage/cookies, never in a query string.
- The browser sends it to the proxy as an `x-baseten-api-key` header; the
  proxy forwards it upstream as `Authorization: Api-Key …` and never logs,
  stores, or echoes it (logs are method + path + status only).
- The proxy allowlists a closed host map (`mgmt` → api.baseten.co with
  `Api-Key` auth; `inference` → inference.baseten.co with `Bearer` auth, the
  latter admitting only `models`), four mgmt GET path shapes, and four query
  params; everything else is rejected (405/400/403). Upstream 401/429 (with
  `Retry-After`) pass through so the UI can react.
