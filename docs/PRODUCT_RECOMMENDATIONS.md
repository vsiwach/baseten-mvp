# Product recommendations — prioritized from first-hand findings

Every item below traces to something we hit while building on Baseten
(FRICTION_LOG.md #1–#17) or measured with committed evidence
(benchmarks/raw/). Prioritized for customer impact × frequency × effort,
through the lens of the inference-PM charter: make it 10× easier to reliably
scale and serve models in production.

## P0 — the fast path should be the default path

**1. Auto-enable (or push-time suggest) BDN weight caching for resolvable
sources.** We shipped a truss that downloaded 6.1 GB from HuggingFace on
every cold start; nothing at push or in six deploys hinted otherwise. Adding
the `weights:` block — one stanza — cut `model.load()` from **360s to 148s
(2.4×, measured, friction #17)**. The platform can see the `hf://`-shaped
model id and the long loads; it should propose or default the fix.
*Effort: detection heuristic + one-line push output. Impact: every cold
start of every un-cached model, and those minutes are billed today.*

**2. Make capacity waits first-class deploy state.** Twice we sat in silent
scheduling limbo: 30 min → INACTIVE with no error on a 2×L4 node (friction
 #6), and 13 min of "Creating the Baseten Inference Service" for a T4
(2026-07-03). A user cannot distinguish slow / stuck / doomed. Expose
"waiting for capacity" with queue context and a suggested alternative SKU;
never let a deploy end INACTIVE without a reason.
*Effort: scheduler already knows; it's a surfacing problem. Impact: the
worst trust-destroying moments in the entire funnel.*

**3. Failure diagnostics must exist via API, and earlier.** BUILD_FAILED
with zero API-visible logs (friction #12); a dependency-skew import crash
discovered only at deploy after a green build (friction #14); host-RAM OOM
discoverable only by crash loop (friction #7); org-gated GPU families
rejected only after packaging + upload (friction #13). Fixes, in order of
cheapness: a `failure_reason` field on deployments; import-the-model-class
as a 5-second build step; push-time pre-flight (SKU allowed for this org?
weights fit host RAM? python/quant combo supported?); build logs in the
management API.
*Impact: converts CI-hostile dead ends into self-serve fixes — we lost
roughly a day across these four.*

## P1 — production-grade contracts

**4. Never leave an environment pointing at a corpse.** A failed first
deploy held the production pointer while a newer ACTIVE deployment sat
unrouted; the env URL served `500 "Model is unhealthy"` until a manual
promote (friction #15). Auto-advance (or at minimum warn in push output and
console) when production references a DEPLOY_FAILED deployment and a newer
ACTIVE one exists.

**5. Give Model APIs a real rate-limit contract.** 28/40 requests 429'd at
~1.3 rps with no `Retry-After`, no `X-RateLimit-*` headers, no quota API
(friction #10, per-request CSV committed); limits are account-tier and only
discoverable in the console. Failover targets and SDK backoff logic are
designed around these headers everywhere else in the industry.

**6. Readiness and billing transparency on cold starts.** Billing starts
when a replica is up, not when it serves; warm-up requests return an
undocumented `500 "Model is unhealthy"` (ACTIVATION_RUNBOOK findings). Ship
a documented readiness endpoint/state and label cold-start minutes
distinctly in billing.

## P2 — menu and DX polish

**7. Fix the hardware menu's shape.** Host RAM is fixed per GPU SKU and
16 GiB cannot load an 8B model (friction #7); the only single-L4 option has
the same trap; org-gating is invisible in the instance reference (friction
 #13). Either size RAM independently or annotate the table with "fits up to
~XB parameters" and per-org availability.

**8. Truss onboarding friction pack.** `truss push` should fall back to
`BASETEN_API_KEY` (friction #2); keep a stable `TrussConfig` import path
(#3); first-push default should be a development deployment (#5); the
credits growth email must say a payment method is still required (#4).

**9. Expose model metadata that routing needs.** Our 11-model sweep
(benchmarks/raw/model_api_sweep_*.csv) found a 3.7× TTFT and 6.4× cost
spread, and reasoning models (gpt-oss-120b, deepseek-v4-pro) that consume
small token budgets entirely on thinking. The catalog API should flag
reasoning behavior and minimum sensible max_tokens so latency-tier routing
can avoid foot-guns programmatically.

## The bigger swing (the roadmap conversation)

**10. Self-serve incident management as a platform primitive.** This repo's
incident agent — SLO-breach detection from live telemetry, quarantine,
spill-to-serverless, probe-verified reinstatement — took cross-deployment
MTTR from *unbounded* to **~9 seconds, measured**, using only public
surfaces. Baseten owns the telemetry, the deployments, AND the serverless
spill capacity: a first-party "failover policy" between a customer's
dedicated deployment and Model APIs (or a second deployment) is a
differentiated reliability product no competitor's shape matches — and it is
verbatim the JD's "measurable decline in MTTR through self-serve incident
management."
