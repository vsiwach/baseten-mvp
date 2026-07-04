# Phase 2 evidence — console-live: BYO-key Reliability Console (2026-07-04)

Deliverable: `console-live/` — Vercel-deployable, bring-your-own-key web console
that reads REAL metrics from a user's Baseten dedicated deployments and shows
SLO posture + one grounded recommendation per production deployment. READ-ONLY.

## What was built (all in console-live/, no build step, no deps)
| file | lines | role |
|---|---|---|
| index.html | ~527 | markup + CSS + all frontend JS inline |
| tokens.css | 120 | verbatim copy of demo/tokens.css (mission-control aesthetic) |
| api/baseten.js | 76 | Vercel Node serverless proxy, stdlib-only |
| server.js | 37 | local runner (`node server.js`, port 4173), same handler as Vercel |
| vercel.json | 3 | minimal |
| README.md | ~45 | boundary statement, run/deploy, security notes |

## Security design (BLOCKING gate criteria)
- Key pasted in browser, held in a JS closure variable only — no
  localStorage/sessionStorage/cookies; wiped on rejection/disconnect.
- Proxy: GET-only (405 otherwise); key from `x-baseten-api-key` header, format
  `^[A-Za-z0-9._-]{10,200}$` (400 otherwise); forwarded ONLY to
  `https://api.baseten.co/v1/...` as `Authorization: Api-Key`; path allowlist of
  exactly 3 GET shapes (models / model deployments / deployment metrics;
  403 otherwise); only `mode|start_epoch_millis|end_epoch_millis|metrics`
  query params copied; URL built via `new URL` + `URLSearchParams` (no string
  concat of user input); logs contain method+path+status ONLY.
- Verified live: server log grep for key material → 0 hits after full test run.

## Offline verification (fake key `dummykey1234` only)
- `node --check` on all JS: pass. POST→405; non-allowlisted path→403; missing
  key→400; path traversal (`/../CLAUDE.md`)→404; real upstream passthrough of
  Baseten's 403 PERMISSION_DENIED for a fake key (live fact: Baseten answers a
  bad key with 403, not 401 — frontend treats both as key-rejected).

## Live verification (real key from env; key never in any transcript/log)
Local server on :4173, real Baseten workspace (2 models, 7 deployments):
1. Proxy chain (curl): GET models → both real models; GET deployments →
   qvm1v4e INACTIVE 0 replicas prod / w52yvzr / q86yjdy DEPLOY_FAILED;
   GET metrics SUMMARY 6h → real values `[[0.0931], [19.0],
   [20.25, 100.68, 107.14, 112.308, 35.358]]` (counter 19 requests; e2e
   quantiles in seconds — a cold-start-dominated window, the exact GOTCHA
   scenario from the mission brief). Raw capture committed (fetched through
   the console proxy itself):
   benchmarks/raw/live_console_metrics_summary6h_20260704-193731.json.
2. Full-page render test (live_render_test.mjs, scratchpad): loads the page's
   REAL inline JS, stubs only the DOM, uses real fetch → local proxy → real
   API; key injected via the page's own paste path from env. 8/8 assertions
   PASS:
   - qwen3-8b-vllm card exists; instance T4x8x32; status INACTIVE
   - non-production q86yjdy correctly absent (production-only cards)
   - 6h window: 19 requests; p99 112.308s; cold-start/low-sample annotation
     "p99 likely includes cold start / low sample (n=19) — verdict uses p95";
     verdict AMBER (not a bare scary RED) for both voice + interactive tiers
   - recommendation grounded in the real numbers (min_replica=1, cites p95/p99)
   - 1h window: qwen card n=7 p50 1801ms / p99 2136ms (the Phase 1 traffic),
     AMBER low-sample; qwen3-8b-pool card (genuinely 0 requests) renders the
     "no requests in window (metrics can lag 1–3 min)" state → BOTH the
     with-data and no-data states verified against live reality.
3. Bug found by the live test and fixed (1 line): the no-traffic branch passed
   `verdict:'AMBER', flagged:true` into recommend(), firing the min_replica
   rule with em-dash placeholders; now `verdict:null, flagged:false` → falls
   through to "widen the window or send traffic". Re-verified live.
4. Operational finding: two back-to-back full refreshes trip a 429 on the
   metrics endpoint (beta). Page behavior per design: banner "polling paused",
   per-card inline error, other cards unaffected. Recorded as friction.

## Honesty / positioning (verified present in UI + README)
- Fixed banner: read-only observer; recommendations advisory; autonomous
  mitigation (quarantine/spill/self-heal) requires a router in the request
  path — links to the recorded control-plane demo.
- Every number footnoted with its source endpoint + mode + window; the latency
  metric is labeled "end-to-end response time" with a note that it includes
  full generation time (it is NOT TTFT).
- Segment: for dedicated-inference customers (metrics exist per dedicated
  deployment); Model-API-only users see an empty-but-honest console.

## Deploy
`cd console-live && vercel login && vercel --prod` (README). No env vars, no
server-side key storage; the proxy is same-origin with the static frontend,
which is what makes the browser→Baseten path possible at all (Baseten's API
has no CORS).
