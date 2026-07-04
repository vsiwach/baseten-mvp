# Phase 1 evidence — Baseten MCP-driven deploy lifecycle (2026-07-04)

Claim (scoped precisely): **Baseten's hosted MCP server (api.baseten.co/mcp)
supports the full dedicated-deployment lifecycle** — activate → readiness poll →
metrics → deactivate — and the deployment served real traffic. The baseten
skill is installed and loaded in the Claude Code session that drove this, but
because the MCP was driven through a minimal JSON-RPC client (see Deviation),
the skill's contribution is not independently observable here; this evidence
does NOT claim "the skill natively drove the deploy".

Descope (PM decision, recorded): a second small model via
`deploy_model_from_library` was skipped — the lifecycle was proven end-to-end
on one model, and remaining session budget was reserved for Phase 2's live
verification window.

## Reproduce (fresh operator, ~10 min, ~$0.10)
1. `export BASETEN_API_KEY=<management-permission key>` (env only, never print).
2. `python3 deploy/baseten/mcp/mcp_client.py list-tools` — 88 tools
   (snapshot: deploy/baseten/mcp/mcp_tools_snapshot_20260704.json).
3. `python3 deploy/baseten/mcp/mcp_client.py call activate_environment '{"model_id":"3ydn1e43","env_name":"production"}'`
4. Poll: `python3 deploy/baseten/mcp/mcp_client.py call get_deployment '{"model_id":"3ydn1e43","deployment_id":"qvm1v4e"}'` until ACTIVE (~2 min).
5. `python3 deploy/baseten/mcp/live_infer_test.py benchmarks/raw/live_mcp_activation_<ts>.csv`
6. Metrics (wait ~2 min for ingestion): `... call get_deployment_metrics '{"model_id":"3ydn1e43","deployment_id":"qvm1v4e","get_deployment_metrics_request_v1":{"mode":"SUMMARY"}}'`
7. TEARDOWN: `... call deactivate_environment '{"model_id":"3ydn1e43","env_name":"production"}'`, re-poll until INACTIVE/0.

## Setup facts
- Baseten skill installed via `npx skills add basetenlabs/baseten-skills`
  (present at ~/.claude/skills/baseten, loaded in the Claude Code session).
- Both hosted MCP servers registered in Claude Code user scope and health-checked:
  `baseten` (https://api.baseten.co/mcp, Bearer auth) — ✓ Connected;
  `baseten_docs` (https://docs.baseten.co/mcp) — ✓ Connected.
- Deviation (honest): the agent drove the hosted MCP server over the MCP
  streamable-HTTP protocol directly from the Claude Code session (minimal
  JSON-RPC client, initialize → tools/list → tools/call), because a nested
  headless `claude -p` could not authenticate (the CLI keychain OAuth token
  expired; refresh requires interactive `claude login`). Same hosted MCP
  server, same tools, same auth; only the client plumbing differs.
- Auth: BASETEN_API_KEY env var only; every command output was redacted
  (`sed s/$KEY/***/`); no key material in logs, files, or this doc.

## MCP surface facts (from tools/list, 88 tools)
- Deployment lifecycle on the MCP is ENVIRONMENT-level: `activate_environment`,
  `deactivate_environment`, `promote_to_environment` (+ pause/cancel/roll-forward).
  There is no deployment-level activate/deactivate tool (those exist only in the
  REST management API used by deploy/baseten/manage.py).
- `get_deployment_metrics` request schema (authoritative, from the tool's
  inputSchema): mode = CURRENT | SUMMARY | SERIES; start/end_epoch_millis
  (window ≤ 7 days, default last hour); optional metrics[] name filter.
  Defaults: baseten_replicas_active (GAUGE), baseten_inference_requests_total
  (COUNTER, label_sets by status), baseten_end_to_end_response_time_seconds
  (HISTOGRAM, label_sets quantile 0.5/0.9/0.95/0.99 + stat avg).

## Lifecycle timeline (all times UTC, 2026-07-04)
Raw transcript artifact for this table (poll logs, call results, 88-tool dump,
before/after workspace state): benchmarks/raw/live_mcp_lifecycle_20260704.log.
| time | action | via | result |
|---|---|---|---|
| 19:10:54 | `activate_environment` model 3ydn1e43 (qwen3-8b-vllm) env `production` | MCP | `{"success": true}` |
| 19:11:13–19:12:36 | poll `get_deployment` qvm1v4e | MCP | DEPLOYING, 0 replicas |
| 19:12:48 | poll `get_deployment` | MCP | **ACTIVE, 1 replica** (~114 s activation→ready; BDN weights cache path) |
| 19:13:18 | 7 real streaming inference requests | HTTPS model endpoint | 7/7 HTTP 200 → benchmarks/raw/live_mcp_activation_20260704-191318.csv |
| 19:13:50 | `get_deployment_metrics` SUMMARY #1 (window 18:58:50→19:13:50, from the file's epochs) | MCP | ingestion lag observed: counter 0.0, histogram all null → benchmarks/raw/live_mcp_metrics_summary_20260704-191352.json |
| ~19:15:45 | `get_deployment_metrics` SUMMARY #2 (window 19:00:45→19:15:45; fetched by a 90 s-delayed background job, file copied 19:16:13) | MCP | replicas avg 0.647; **requests_total 7.0**; e2e p50 1.801 s / p90 1.973 / p95 2.064 / p99 2.136 / avg 1.885 → benchmarks/raw/live_mcp_metrics_summary_20260704-191613.json |
| ~19:15:4x | `get_deployment_metrics` SERIES (20-min window, step 30 s; saved 19:15:50, ran concurrently with SUMMARY #2) | MCP | counter buckets [2.0, 5.0] = exactly 7 → benchmarks/raw/live_mcp_metrics_series_20260704-191550.json |
| 19:16:16 | `deactivate_environment` | MCP | `{"success": true}` |
| 19:16:28 | poll `get_deployment` | MCP | **INACTIVE, 0 replicas** — teardown verified |

## Serving measurements (CSV: live_mcp_activation_20260704-191318.csv)
- Endpoint: `https://model-3ydn1e43.api.baseten.co/environments/production/predict`,
  streaming (OpenAI-style SSE lines from the truss model).
- live-0 (first request after ACTIVE): TTFT 778.8 ms, total 2559.9 ms.
- live-1..6 (warm): TTFT 300.1–312.4 ms; totals 2029–2077 ms; 50 chunks each.
  Consistent with the repo's prior measurement (TTFT p50 ~333 ms on this config).

## Cross-validation (provenance chain)
- Requests sent (ground truth, CSV): 7 → MCP SUMMARY counter: 7.0 → MCP SERIES
  bucket sum: 2.0 + 5.0 = 7. Exact match, zero fabrication.
- Measured totals 2.03–2.56 s bracket the MCP histogram (p50 1.80 s, p99 2.14 s;
  server-side excludes some client/network overhead). e2e metric includes full
  generation time — it is NOT TTFT.
- Metrics ingestion lag: real data appeared between the 19:14 and 19:15 SUMMARY
  calls, ~1–3 min after traffic. Consoles must treat all-null histograms as
  "no data yet", not an error (feeds Phase 2).

## Spend
- Active replica window 19:12:48→19:16:28 ≈ 3.7 min of T4x8x32 (~$0.90/hr)
  ≈ **$0.06**, plus ~2 min deploy spin-up. Well under the $5 session cap.
- Post-teardown state: all 7 deployments across both workspace models INACTIVE
  with 0 active replicas (verified at 19:16:28; also verified before start).

## Recorded for Phase 2
- model_id 3ydn1e43 (qwen3-8b-vllm), deployment qvm1v4e (deployment-3,
  production), instance T4x8x32 — 1 T4 GPU 16 GiB VRAM, autoscaling
  min 0 / max 1, scale_down_delay 900 s.
