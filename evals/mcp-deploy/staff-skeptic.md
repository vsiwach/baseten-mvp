# STAFF-SKEPTIC verdict — mcp-deploy Phase 1 (reviewed 2026-07-04, re-reviewed same day after remediation)

## Verdict: PASS

First review returned FAIL (conditional) on reproducibility discipline: the
method lived only in the ephemeral session scratchpad, two evidence citations
pointed at nonexistent filenames, and the headline claim outran what the
JSON-RPC deviation could prove. All blocking items are now remediated and were
re-verified on disk, not taken on faith:

1. **Method committed (top objection — FIXED, verified).**
   `deploy/baseten/mcp/mcp_client.py` and `deploy/baseten/mcp/live_infer_test.py`
   are byte-identical (diff-verified) to the scratchpad originals that produced
   the evidence; `deploy/baseten/mcp/mcp_tools_snapshot_20260704.json` parses,
   contains exactly 88 tools, and includes the lifecycle tools cited
   (activate_environment, deactivate_environment, get_deployment,
   get_deployment_metrics, promote_to_environment). The snapshot also confirms
   the "environment-level only" claim: the only activate/deactivate tools are
   env-level (+ deactivate_chain_deployment for chains).
2. **Claim scoped (FIXED, verified).** PHASE1_EVIDENCE.md:3–9 now claims only
   "Baseten's hosted MCP server supports the full lifecycle" and explicitly
   states the skill's contribution is not independently observable and that the
   evidence does NOT claim the skill natively drove the deploy. This is the
   correct scope for the deviation.
3. **REPRODUCE section (FIXED, verified against schema).** 7 steps at
   PHASE1_EVIDENCE.md:16–24 using the committed files. I checked every argument
   shape against the authoritative inputSchema in the committed snapshot:
   activate/deactivate_environment {model_id, env_name}, get_deployment
   {model_id, deployment_id}, get_deployment_metrics {model_id, deployment_id,
   get_deployment_metrics_request_v1} — all match, including the non-obvious
   `get_deployment_metrics_request_v1` wrapper a fresh operator would never
   guess. A fresh operator with a management key can redo this in ~10 min for
   ~$0.10.
4. **Descope recorded (FIXED).** PHASE1_EVIDENCE.md:11–14 records the
   second-model skip as an explicit PM decision with rationale (lifecycle
   proven end-to-end on one model; budget reserved for Phase 2). Right call —
   see analysis below.
5. **Citations + raw artifact (FIXED, verified).** No references to the dead
   filenames remain (grep clean); the timeline now cites the real files
   (…191613.json, …191550.json) and explains the timestamp offsets (90 s
   delayed background fetch, file copy at 19:16:13 — internally consistent
   with the files' own window epochs). New raw artifact
   `benchmarks/raw/live_mcp_lifecycle_20260704.log` (126 lines) carries the
   poll transcript (12 s cadence, DEPLOYING×8 → ACTIVE at 19:12:48),
   before/after workspace state, and the 88-tool name dump. Grep for key
   material in the log and mcp/ files: clean.

## Data integrity (unchanged from first review — all real)

- CSV epoch timestamps decode to 2026-07-04 19:13:21–19:13:33 UTC, matching
  the claimed timeline exactly.
- Cross-validation holds end to end: 7 requests sent (CSV, ground truth) =
  MCP SUMMARY counter 7.0 = SERIES per-bucket increments 2.0 + 5.0.
- The null-histogram first SUMMARY (…191352.json) genuinely captures the
  1–3 min ingestion lag; "all-null = no data yet, not an error" is a real
  product finding for Phase 2.
- Teardown verified INACTIVE/0 replicas; fleet-wide 0-replica check across
  both workspace models; spend ≈ $0.06.
- live_infer_test.py demonstrably produced the CSV (field schema, prompt
  count, warmup/measured labels all match).

## Condition on "PASS"

Files are verified present in the working tree; per repo flow the git commit
lands at phase end. This PASS assumes the phase commit includes
`deploy/baseten/mcp/` (all three files), `evals/mcp-deploy/PHASE1_EVIDENCE.md`,
and the five raw artifacts (`live_mcp_activation_…csv`, both summaries, the
series, `live_mcp_lifecycle_20260704.log`). If any of those are dropped from
the commit, this reverts to the original FAIL rationale.

## Residual objections (non-blocking, carry to Phase 2)

1. **n=7 caveat.** "e2e p99 2.136 s" (PHASE1_EVIDENCE.md:63) is a percentile
   over 7 requests — fine as cross-validation of the metrics pipeline (its
   actual use), meaningless as a perf claim. Add "n=7, lifecycle proof not a
   latency benchmark" wherever it's reused.
2. **BDN attribution still asserted.** "~114 s activation→ready; BDN weights
   cache path" (PHASE1_EVIDENCE.md:60) — the 114 s is measured; the BDN cause
   is inferred from the prior ~6-min cold start, not evidenced by build/config
   logs. Say "consistent with BDN caching".
3. **Error-path metrics unverified.** Only status=200 label_sets observed on
   the counter; the 4xx/5xx shapes a Phase 2 console must render are untested
   (no error traffic was sent). Deliberately send one 4xx in Phase 2 and
   capture the label_set.
4. **Probe-tool hygiene.** mcp_client.py re-initializes a session per CLI
   invocation (3 RPCs per tool call), keeps only the last SSE `data:` line
   with an `id` (drops notifications), raises bare KeyError on missing
   BASETEN_API_KEY, and has no retry on transient 5xx. Acceptable for a probe;
   must not graduate into automation as-is.

## JD lines actually demonstrated (vs claimed)

- **Demonstrated:** docs/JD.md:11–12 ("how customers configure and observe
  them") — the metrics-schema archaeology (positional histogram label_sets,
  SERIES = per-bucket increments, ≤7-day window, ingestion-lag semantics) is
  real infra-PM work, now reproducible. Plus cost discipline (JD:26–27):
  $0.06 run, pre/post fleet-wide teardown verification.
- **Groundwork only:** self-serve incident management / MTTR (JD:27–28) —
  observe/actuate primitives proven; nothing automated on them yet.
- **Not demonstrated (correctly no longer claimed):** autoscaling, placement,
  routing, failover (JD:15–23).

## 100x analysis (100 models, frequent activations)

- **Polling becomes thundering herd.** Readiness by polling `get_deployment`
  at 12 s cadence (now visible in the lifecycle log) is fine for one model;
  100 models × frequent activations is a constant poll storm against the
  management plane, and the 88-tool surface exposes no webhook/subscription
  primitive. Fleet automation needs jittered backoff and characterization of
  management-API rate limits (assume they exist; cf. the Model API 429
  history).
- **Metrics lag poisons rollout gates.** The 1–3 min ingestion lag means any
  automated activate→verify→proceed gate adds minutes per model and re-polls
  get_deployment_metrics throughout; the ≤7-day window kills historical
  baselining without an export pipeline.
- **Environment-level-only lifecycle splits the control plane.** MCP cannot
  touch a specific deployment; fleets with multiple deployments per model must
  mix MCP + REST management API — two control paths that can disagree is how
  "production env pointing at a corpse" (friction #15) happens at fleet scale.
  The before-state in the lifecycle log (DEPLOY_FAILED / BUILD_FAILED corpses
  parked across both models) is a small live example of the residue.
- **88 tools tax the agent loop.** Per-session schema/context cost and
  tool-disambiguation error rate grow with catalog size; native Claude Code
  driving of this surface remains untested (scoped out honestly).
- **Cost tail dominates at frequency.** scale_down_delay 900 s + ~2 min
  spin-up means each activation cycle pays ≥17 min of replica time; frequent
  activations of 100 models mostly buy idle tails.
- **Single workspace Bearer key.** One env-var key with full lifecycle rights
  (the snapshot even exposes list_api_keys/delete_api_key/upsert_secret);
  100x needs scoped keys, rotation, and audit.

## Was skipping the second model the right PM call?

Yes, and it is now documented (PHASE1_EVIDENCE.md:11–14). A second model
re-executes the identical tool sequence for ~$0.06–0.10, yielding new
information only about concurrent activations and model disambiguation —
better tested deliberately later. Marginal information per dollar was near
zero; blast-radius discipline (one model, fleet-wide teardown verification
across both workspace models) was correct.
