# Security critique — Phase 1 (mcp-deploy), API-key handling

Auditor: security-critique agent. Date: 2026-07-04. Scope: BASETEN_API_KEY must
never be logged, persisted, committed, or sent anywhere except Baseten
(api.baseten.co / model-*.api.baseten.co; docs MCP unauthenticated).

## Verdict: PASS

## What was audited
1. `evals/mcp-deploy/PHASE1_EVIDENCE.md` + the four raw artifacts in
   `benchmarks/raw/` (live_mcp_activation_20260704-191318.csv,
   live_mcp_metrics_summary_20260704-191352.json,
   live_mcp_metrics_summary_20260704-191613.json,
   live_mcp_metrics_series_20260704-191550.json) — grepped for Baseten-key
   shapes, long base64/hex strings, Authorization/Api-Key/Bearer values.
   Result: no token material. Only hits are the literal words "Bearer" /
   "BASETEN_API_KEY" in prose, metric names, and URL/file-path fragments.
   CSV contents verified line-by-line: timing fields only, no auth data.
2. Scratchpad MCP client (`mcp_client.py`): key read via
   `os.environ["BASETEN_API_KEY"]` only; attached as a Bearer header only when
   targeting `https://api.baseten.co/mcp`; the docs server
   (`https://docs.baseten.co/mcp`) gets `auth=None`; the key is never printed,
   logged, or written. Scratchpad inference script (`live_infer_test.py`): key
   from env only; sent as `Api-Key` header only to
   `https://model-3ydn1e43.api.baseten.co/environments/production/predict`;
   output CSV schema (ts, req_id, label, http_status, ttft_ms, total_ms,
   chunks, error) contains no auth fields; exception strings captured in
   `error` cannot contain request headers. All other scratchpad outputs
   (mcp_tools.json, metrics_*.json) swept for 40+-char token-shaped strings —
   every match is an MCP tool/schema/metric identifier, not a credential.
3. Repo working tree (`git status` / `git diff`): tracked diff is empty; the
   only new files are the four raw artifacts, `evals/mcp-deploy/`, and
   `console-live/` — all grepped, no key material. `console-live/api/baseten.js`
   references Authorization/Api-Key but is a read-only allowlisted proxy: it
   forwards a client-supplied `x-baseten-api-key` header to
   `https://api.baseten.co/v1/` only, never logs the key (logs path+status;
   non-allowlisted paths log as "(rejected)"), never puts the key in a query
   string. No `.env` files anywhere in the tree; no hardcoded keys in tracked
   files.

## Accepted risk (not a finding)
- MCP registration persists the key in `~/.claude.json` as an
  `Authorization: Bearer kHB…` header (only first 3 chars observed during
  audit; value length 48 incl. "Bearer " prefix). File permissions verified
  `-rw------- vikramsiwach` (0600, user-only). This is standard user-scope MCP
  configuration and is accepted per the audit brief.

## Notes / recommendations (non-blocking)
- `mcp_client.py` prints full `tools/call` results to stdout. No Baseten MCP
  tool observed returns secrets, but if one ever did (e.g. a future
  key-management tool) the output would echo it. Consider a redaction pass on
  tool output before printing if the client outlives Phase 1.
- `console-live/api/baseten.js` implies the browser will hold the user's API
  key (it supplies `x-baseten-api-key`). The proxy itself leaks nothing, but
  Phase 2 should document where the browser stores that key (memory vs
  localStorage) and prefer memory-only.
- Provenance nit (not security): PHASE1_EVIDENCE.md cites
  `live_mcp_metrics_summary_20260704-191603.json` and
  `live_mcp_metrics_series_20260704-191540.json`; the files on disk are
  `…191613.json` and `…191550.json`. Filenames in the doc should be corrected
  so the slo-auditor's trace succeeds.
