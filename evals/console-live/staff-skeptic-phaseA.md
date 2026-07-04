# STAFF-SKEPTIC verdict — Phase A / console-live public deploy (2026-07-04)

## Verdict: PASS (after one fix to the evidence file, verified)

Scope: does https://baseten-reliability-console.vercel.app render REAL data via
the documented flow, and is `evals/console-live/PHASEA_DEPLOY_EVIDENCE.md`
honest? All my probes used fake keys only.

## What I verified live against the public URL (fake keys)

| probe | result |
|---|---|
| GET / | 200; **sha256 of served index.html identical to committed `console-live/index.html`** (a8f9ded1…) |
| GET /tokens.css | 200; sha256 identical to committed file (245e10dd…) |
| POST /api/baseten?path=models | 405 `method not allowed` |
| GET ?path=secrets (fake key) | 403 `path not allowlisted` |
| GET ?path=models/..%2f..%2fsecrets | 403 (anchored regex holds under encoding) |
| GET ?path=models, no key | 400 |
| GET ?path=models, fake key | **403 `{"code":"PERMISSION_DENIED"}` — Baseten's own body**, proving the proxy forwarded MY header key to api.baseten.co. A hidden server-side key would have returned 200 here. This is the strongest live evidence that the "NO env vars / key-per-request" claim is true. |
| /server.js, /README.md | 404 (`.vercelignore` effective) |

Conclusion: the public page is byte-identical to the audited, committed code
(so every Phase 2 finding — allowlist at `api/baseten.js:12-16`, no key
logging, provenance footnotes — applies verbatim to the deployment), and the
data path really is browser → /api/baseten → api.baseten.co with the caller's
key. The evidence's real-key check (200 → the two real model IDs) is
consistent with this flow and with the committed raw captures.

## Question 1 — is "6/8 with 2 stale assertions" legitimate?

**The mechanism is legitimate; the evidence's narration of it was wrong.**
Reconstructed from committed artifacts:

- Asserted constants (19 req, p99 112.308s) = the committed 6h capture
  `benchmarks/raw/live_console_metrics_summary6h_20260704-193731.json`,
  window 2026-07-04 13:37:31Z → 19:37:31Z. Same day — **not "yesterday"**.
- Only 7 of the 19 are the 19:13Z session
  (`live_mcp_activation_20260704-191318.csv`; SERIES capture shows 2+5 in the
  19:13:32/19:14:02 buckets and zero from 18:55Z on). The other 12 — which must
  include the ~112s cold-start samples, since all 19:13 requests were ~2s —
  are earlier same-day live traffic with **no committed timestamps**.
- The render test ran ~22:1xZ, not ~20:1xZ (deploy commits 21:39Z/22:10Z,
  `.vercel` mtime 22:14Z, evidence mtime 22:18Z). So the 6h window slid ~2.6h
  to ~[16:1xZ, 22:1xZ]; "14 of 19" needs exactly 5 of the 12 uncommitted
  requests to predate ~16:1xZ. Plausible, internally consistent, not provable.
- Two corroborations the author didn't even point at: (a) the 1h window's
  no-traffic render is only possible after ~20:14Z (deployment deactivated
  19:16:16Z per the lifecycle log) — it pins the test time and contradicts the
  naive "window slid ~1h so all 19 should remain" reading; (b) p99 moving only
  112.308→111.696s means the slow cold-start samples stayed in-window, exactly
  what dropping 5 of the oldest-but-not-slowest samples looks like. Fabricated
  numbers would have passed 8/8; these fail in the one way live data fails.

**Under a naive reading of the timeline the count is impossible** (19 requests
at 19:13Z cannot age out of a 6h window by 20:1xZ); it only becomes consistent
once you know 12 of the 19 predate the committed session. The evidence said
"5 of yesterday's 19 aged out" — wrong date, no decomposition, and it would
have collapsed under exactly this interrogation.

## Question 2 — cold-start annotation + AMBER on the live render

Verified against the served (hash-identical) code, not just claims:
- `coldStartFlag` (index.html:270-276): n=14 < 20 → flagged=true.
- `verdictFor` (index.html:279-284): eff=p95 (107.14s) is over both budgets,
  but `flagged` → **AMBER**, not RED — matches the evidence.
- Annotation (index.html:418): "p99 likely includes cold start / low sample
  (n=14) — verdict uses p95" — matches the evidence's wording.
- 1h no-traffic state (index.html:383): "No requests in this window…" —
  correct given deactivation at 19:16:16Z.
- Budgets 500/800ms remain hard-coded illustrative defaults — already an
  accepted, README-documented deviation (Phase 2 objection #7); no Baseten API
  supplies per-model SLOs for a BYO-key console.

## Ranked objections

1. **[TOP — FIXED, verified] Evidence misdated and numerically unanchored.**
   "Stale assertion constants from yesterday's session" / "5 of yesterday's 19
   aged out" is factually wrong (same-day capture, 2.6h window slide) and the
   live values (14, 111.696s) plus the test harness `live_render_public.mjs`
   exist nowhere in the repo — the 6/8 result is unreproducible prose. For an
   evidence file whose whole job is provenance, a wrong date is the crack a
   panel pries open. **Fix applied:** appended a dated Correction section to
   PHASEA_DEPLOY_EVIDENCE.md with the verified decomposition (7 @ 19:13Z + 12
   earlier uncommitted; test ~22:1xZ; the 1h-window corroboration) and an
   explicit statement of the unreproducibility gap. Verified in place.
2. **Uncommitted harness/output** (subsumed into #1's fix as a stated gap).
   Independently mitigated by this review: I re-verified the deployment flow
   and the render logic against the hash-identical served code with fake keys.
3. **Bare `vercel.json` (`{"version":2}`)** — no CSP/X-Frame-Options on a page
   that handles a pasted API key, no explicit `maxDuration` (Phase 2 #6 noted
   TIMEOUT_MS 10s == Hobby default; platform may kill the function before the
   proxy's JSON 504). Low severity — key is in a closure, page is
   dependency-free, frontend tolerates any !ok — but a public deployment
   should set frame-denial headers. Recommend before wider sharing.
4. **Nothing pins the deployment to a commit.** Today's hash match is a
   point-in-time check; `vercel deploy` from a working tree can drift from
   git. A deploy-from-CI (or recording the deployment's source hash in
   evidence) closes it. Minor for a demo.
5. **"NO env vars (`vercel env ls` empty)" is asserted, not artifact-backed**
   — but behaviorally corroborated by the fake-key PERMISSION_DENIED
   passthrough (a server-side key would mask it). Accept.

## 100x analysis

Unchanged from Phase 2 (the deployment is the same audited code): the browser
fan-out (`1 + M + 2P` calls/refresh, 429 observed at n=2 models) is the
ceiling, documented in README Known limits; backoff fails safe (global
`pausedUntil`, Retry-After honored, no retry storm). What the Vercel hop adds:
the proxy is stateless and serverless (scales horizontally for free; per-user
keys mean no shared upstream quota to exhaust — each key rate-limits itself),
logs stay method+path+status (nothing sensitive at scale), and the 3am page
risk is confined to Vercel platform 504s that render as inline card errors
with the numbers' provenance intact. Nothing here pages anyone; the failure
mode is a visibly stale console.

## JD lines demonstrated (Phase A increment)

Same as Phase 2 (JD 10-12 observe-half, JD 26-29 cost/perf console; routing/
failover honestly disclaimed) — plus Phase A makes "how customers … observe"
real for an outside user: public URL, BYO key, zero server-side secrets,
clone-to-own-deployments path in the README. It does not demonstrate any new
JD line; it makes an already-demonstrated one shippable.
