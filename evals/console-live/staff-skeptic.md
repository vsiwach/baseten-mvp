# STAFF-SKEPTIC verdict — Phase 2 / console-live (2026-07-04)

## Verdict: PASS (after one fix, verified, + known limits documented)

Reviewed: `console-live/` (index.html ~530 lines, api/baseten.js, server.js,
tokens.css, README.md, vercel.json) against docs/JD.md and
evals/console-live/PHASE2_EVIDENCE.md. All probes ran against the live local
server on :4173 with fake keys only.

## JD lines actually demonstrated (vs claimed)

- **Demonstrated:** "how customers configure and observe them" (JD 10-12) — the
  observe half, end to end: real management-API data, per-deployment
  autoscaling posture (min/max replica, scale-to-zero state, active replicas),
  SLO verdicts with provenance footnotes on every number. JD 26-29 (F7 console,
  cost/perf framing): the scale-to-zero vs warm-replica cost tradeoff is the
  literal subject of the recommendation rules. JD 15-18: autoscaling/cold-start
  *observability* only.
- **Not demonstrated, and honestly disclaimed:** routing, failover, MTTR
  reduction (JD 20-23, 28). The fixed UI banner (index.html:116-118) and README
  "Observe vs control boundary" section state that autonomous mitigation
  requires the router in the request path and point to the recorded demo. The
  observe-vs-control boundary is stated in both UI and README and the app's
  behavior matches it: the proxy is GET-only with a 3-path allowlist
  (api/baseten.js:12-16,35) — it *cannot* mutate.

## Ranked objections

1. **[TOP — FIXED, verified] min_replica=1 recommended from garbage samples.**
   Pre-fix rule (index.html:295-297): `(RED||AMBER) && flagged && minReplica===0`
   → because `coldStartFlag` returns true for ANY n<20 (index.html:271), the
   console recommended paying for a warm replica on a scale-to-zero deployment
   whose 19 requests had p99 = 55ms ("steady p95 is 50.0ms but p99 hits
   55.0ms" — reproduced with the page's real inline functions), and on the
   actual live-evidence card it rendered "steady p95 is 107140ms" — calling a
   107-second p95 "steady" while citing it as grounds for an autoscaling
   change. In front of a staff panel, for a JD about cold starts, that one
   card sinks the demo.
   **Fix applied and verified:** the rule now requires the genuine cold-start
   signature (stz enabled AND p95 ≤ interactive budget AND p99 > budget); a
   new branch routes cold-dominated/low-sample windows (flagged, p95 over
   budget or absent) to "widen the window or send steady traffic before tuning
   autoscaling." Re-ran the extraction harness: live-evidence numbers → widen-
   window advice; 19 fast requests → "Healthy — no action"; textbook signature
   (p95 600ms / p99 9000ms, n=200) → min_replica=1 correctly. Inline JS
   re-parsed clean; live server serves the patched file.

2. **[Documented as known limit] Refresh fan-out does not survive fleet scale.**
   Each refresh = `1 + M + 2P` API calls (index.html:448-470): models list,
   per-model deployments, SUMMARY + SERIES per production deployment. The
   evidence records a 429 from TWO back-to-back refreshes on a 2-model
   workspace. At 10 models/10 prod deployments a refresh is ~31 calls; at 100
   models ~301 — a single refresh rate-limits, and 60s auto-refresh becomes a
   pause/retrip loop. Mitigations present are real but partial: concurrency
   cap 4 (`mapLimit`), Retry-After honored via a global `pausedUntil` gate that
   also fails fast for in-flight calls (no retry storm — good). Missing:
   cross-refresh caching of the (slow-changing) model/deployment lists,
   incremental loading, jitter. Now stated in README "Known limits": a
   fleet-scale version needs a server-side aggregator, not a browser fanning
   out per card. For the stated segment (dedicated customer, handful of prod
   deployments) the current design gives value, not noise.

3. **Full grid teardown on every refresh** (index.html:456-457,
   `cards.innerHTML = ''` before any fetch): a 429 mid-refresh leaves the
   remaining cards as inline errors and the previously rendered good numbers
   are gone — no stale-while-revalidate. Annoying at 2 models, data loss at
   scale. Documented in Known limits.

4. **`coldStartFlag` conflates low-sample with cold-start** in one boolean
   (index.html:268-274). The verdict side handles it honestly (AMBER + the
   "verdict uses p95" annotation), but this conflation caused objection #1.
   Acceptable now that the recommendation branch distinguishes the two.

5. **No pagination handling on `/v1/models`** (index.html:453-454) — if the
   management API pages the model list, models beyond page one silently
   vanish from a "fleet" console. Untestable with a 2-model workspace; flag
   for the next live session.

6. **Vercel vs local gaps — checked, minor.** `req.query` shape: server.js:23-28
   emulates Vercel's string-or-array semantics; the proxy handles both
   (`[].concat(q.metrics)`, `typeof` guards) and the frontend only ever sends
   one `metrics` value. No streaming used; responses buffered. CommonJS default
   export is the supported Vercel Node signature. One real edge: upstream
   `TIMEOUT_MS` (api/baseten.js:10) is 10s, equal to Vercel Hobby's default
   maxDuration — a slow upstream can get the function killed by the platform
   (HTML 504) instead of returning the proxy's JSON 504; the frontend handles
   any !ok status generically, so it degrades to a correct-but-uglier inline
   error. Recommend 8s if it ever matters.

7. **Budgets (500/800ms) are hard-coded constants** (index.html:148-149), not
   API-sourced. For a BYO-key console there is no API that supplies per-model
   SLOs; every card prints the budget it was judged against, and README now
   labels them illustrative defaults. Accepted deviation, logged.

## Demo-ware probes that came back clean

- Proxy rejection paths verified live with fake keys: POST→405, missing/short
  key→400, non-allowlisted path→403, `models/../../secrets`→403 (anchored
  regexes), static-file traversal contained (`/../CLAUDE.md`→404; `%2e%2e` is
  WHATWG dot-segment normalization inside ROOT, not an escape). Injected
  query params (`limit=999`) are stripped — upstream saw a clean request.
- No key material in logs (code path: method+path+status only; non-allowlisted
  paths logged as `(rejected)` so hostile paths don't pollute logs either).
- Numbers trace to endpoints: every card footnotes the exact GET + mode +
  window + metric name, and labels latency "end-to-end response time … not
  TTFT". The evidence's live values (n=19, p99 112.308s) match the rendered
  card. No fabricated values found; the no-traffic state renders honestly.
- tokens.css is byte-identical to demo/tokens.css (diff clean); all chip/num
  classes used by the page exist in it.
- Segmentation coherent: cards are production deployments only
  (`dep.is_production === true`, index.html:462); Model-API-only users get an
  explicit empty state, not fake data.
- Reproducibility: `node console-live/server.js` → paste key. No deps, no
  build step. Clone-to-own-deployments in well under 5 minutes; README
  commands are accurate as written.

## 100x analysis (summary)

State is per-browser-tab (fine for a BYO-key tool — nothing server-side to
shard), but the hot path is the browser itself fanning out O(models +
2×deployments) upstream calls per refresh with no cache; the observed 429 at
n=2 models means the architecture is already at its ceiling, not near it. The
backoff design fails safe (global pause, fail-fast, Retry-After respected —
no thundering herd, nothing pages at 3am; the failure mode is a stale console
with a visible banner). The honest scaling story — now in the README — is
that this is the right shape for a dedicated customer with ≤~10 prod
deployments, and the fleet version is a server-side aggregator behind the
same UI.

## Files touched by this review

- `console-live/index.html` — recommendation rule fix (verified against
  extracted real functions, before/after harness in scratchpad).
- `console-live/README.md` — new "Known limits" section (objections 2, 3, 7).
- This verdict.
