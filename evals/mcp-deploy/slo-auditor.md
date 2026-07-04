# SLO-AUDITOR — mcp-deploy Phase 1 (paper audit, 2026-07-04)

## Verdict: PASS (re-audit after fixes; initial audit was FAIL — history below)

Scope: paper audit of raw-file provenance only. No activation, no inference, no
network, per audit constraints. All values regenerated from the committed raw
files with python3/csv.

## Audit history
- Audit #1 (19:17 local file state): FAIL on three findings — F1 dead cited
  filenames, F2 lifecycle timeline with no committed artifact, F3 two timeline
  call-times contradicted by the raw files' own window epochs.
- Audit #2 (this document): all three findings fixed and re-verified. The four
  numeric raw files are byte-identical to audit #1 (same sizes/mtimes:
  CSV 428 B @15:13, summary-191352 2092 B @15:13, summary-191613 2212 B @15:16,
  series-191550 8603 B @15:15), so the numeric cross-validation from audit #1
  stands unchanged.

## Regenerated vs displayed (unchanged from audit #1 — all EXACT)

Raw files:
- benchmarks/raw/live_mcp_activation_20260704-191318.csv
- benchmarks/raw/live_mcp_metrics_summary_20260704-191352.json
- benchmarks/raw/live_mcp_metrics_summary_20260704-191613.json
- benchmarks/raw/live_mcp_metrics_series_20260704-191550.json
- benchmarks/raw/live_mcp_lifecycle_20260704.log (new, audit #2)

| Claim (PHASE1_EVIDENCE.md) | Regenerated from raw | Match |
|---|---|---|
| 7 requests, 7/7 HTTP 200 | CSV: 7 rows, all status 200 | EXACT |
| live-0 TTFT 778.8 ms / total 2559.9 ms | CSV row live-0 | EXACT |
| live-1..6 TTFT 300.1–312.4 ms | CSV min 300.1 / max 312.4 | EXACT |
| live-1..6 totals 2029–2077 ms | CSV min 2029.4 / max 2077.2 | EXACT |
| 50 chunks each | CSV: 50 × 7 | EXACT |
| replicas avg 0.647 | 191613.json: 0.6470588235294118 | EXACT (3 dp) |
| requests_total 7.0 | 191613.json | EXACT |
| e2e p50 1.801 / p90 1.973 / p95 2.064 / p99 2.136 / avg 1.885 s | 191613.json: 1.801 / 1.9734 / 2.0637 / 2.13594 / 1.88546 | EXACT (3 dp) |
| SUMMARY #1 counter 0.0, histogram all null | 191352.json | EXACT |
| SUMMARY windows 15 min; SERIES 20 min step 30 s, 41 buckets | window epochs | EXACT |
| SERIES buckets [2.0, 5.0] = 7 = counter 7.0 = CSV 7 | three-way match | EXACT |
| Spend 3.7 min × ~$0.90/hr ≈ $0.06 | 220 s × $0.90/hr = $0.055; rate → deploy/LIVE_SETUP.md ($0.01504/min) | OK |
| ~114 s activation→ready | 19:10:54 → 19:12:48 (lifecycle log) = 114 s | EXACT |
| prior TTFT p50 ~333 ms | README.md line 71 (context only) | Traced |

Tolerance applied: none needed — counts exact, quantiles/averages exact at the
displayed precision from the same raw files (paper audit; no re-run noise).

## Re-verification of the three FAIL findings

F1 (dead filenames) — FIXED. PHASE1_EVIDENCE.md now cites
`live_mcp_metrics_summary_20260704-191613.json`,
`live_mcp_metrics_series_20260704-191550.json`, and the lag-window capture
`live_mcp_metrics_summary_20260704-191352.json`. All three exist and contain
exactly the attributed values (re-checked).

F2 (lifecycle provenance) — FIXED. New artifact
`benchmarks/raw/live_mcp_lifecycle_20260704.log` covers every previously
unbacked number:
- Readiness poll log: 9 entries 19:11:13 → 19:12:48 ACTIVE 1; inter-poll
  deltas regenerate as [12,12,12,12,12,12,11,12] s — consistent with the
  stated ~12 s cadence, and 19:10:54 → 19:12:48 recomputes to exactly 114 s.
- Activate/deactivate results (`{"success": true}`) with date -u stamps
  19:10:54Z / 19:16:16Z; teardown verify 19:16:28 INACTIVE 0. These are the
  spend-window endpoints, so the $0.06 estimate now has a committed source.
- Before-state: 3 + 4 = 7 deployments across both models, all INACTIVE/FAILED
  with 0 replicas — backs the "all 7 deployments INACTIVE" claim.
- Full 88-name tools/list dump: exactly 88 names, and all 88 appear in the
  committed snapshot `deploy/baseten/mcp/mcp_tools_snapshot_20260704.json`
  (88 unique tool entries; contains activate_environment,
  deactivate_environment, promote_to_environment, get_deployment,
  get_deployment_metrics; the get_deployment_metrics inputSchema contains
  CURRENT/SUMMARY/SERIES, start/end_epoch_millis, and the three default
  metric names — backing the "MCP surface facts" section verbatim). No
  key-material strings found in the snapshot.
- Method files committed: `deploy/baseten/mcp/mcp_client.py` (JSON-RPC
  initialize → tools/list → tools/call over streamable HTTP, key from env
  only, never printed — matches the doc's Deviation note) and
  `deploy/baseten/mcp/live_infer_test.py` (writes exactly the CSV columns
  ts,req_id,label,http_status,ttft_ms,total_ms,chunks,error; live-0 labeled
  warmup — matches the committed CSV).
Caveat (stated, not disqualifying): the log's own header says it was
assembled post-hoc from session-captured outputs; it is not a byte-verbatim
machine transcript. Everywhere it overlaps an independent artifact it is
corroborated (ACTIVE 19:12:48 precedes first CSV request 19:13:21.5; replicas
gauge nonzero in both summary windows; SUMMARY #1 call time matches its
window epoch), and nothing contradicts it.

F3 (call-time contradictions) — FIXED. SUMMARY #1 is now listed at 19:13:50
with its window (18:58:50→19:13:50) taken from the file's epochs — matches
1783191530920/1783192430920 exactly. SUMMARY #2 is described by its window end
19:15:45 (matches 1783192545516) with the 19:16:13 file-copy time explained by
the 90 s-delayed background job. SERIES is marked "ran concurrently with
SUMMARY #2, saved 19:15:50" with no ordering claim beyond the epochs — the
prior false ordering assertion is gone.

## Residual observations (non-blocking)
1. Lifecycle log line "SERIES window 18:55:32→~19:15:4x": the file's end
   epoch is 19:15:32.703 (start + exactly 20 min). The "~19:15:4x" conflates
   call/save time with window end. The evidence doc itself does not repeat
   this; cosmetic fix suggested in the log only.
2. Replica-gauge averages (0.4 over 18:58:50→19:13:50; 0.647 = 11/17 over
   19:00:45→19:15:45) are higher than a simple time-average would give for a
   replica active from 19:12:48 — consistent with Baseten averaging only over
   reported samples. The doc quotes the file values verbatim, which is
   correct; the semantics are the platform's, not the doc's claim.
3. SERIES counter increments (2.0 @ bucket 19:13:32, 5.0 @ 19:14:02) are
   right-shifted ~30–60 s relative to CSV completion times — ingestion/rate-
   window attribution. Doc only claims the sum (7), which is exact.

## SLO check
No SLO thresholds asserted in this Phase 1 doc; voice-tier SLO (<500 ms TTFT /
<60 ms TPOT) appears only as README context and is not hard-coded in any UI
touched by this phase. N/A.

## Commands run (audit #2 additions)
```
python3: re-list benchmarks/raw mcp files; confirm sizes/mtimes of the four
  numeric files unchanged from audit #1
python3: parse lifecycle log poll lines → deltas [12,12,12,12,12,12,11,12] s;
  19:10:54→19:12:48 = 114 s; before-state 3+4 = 7
python3: json.load mcp_tools_snapshot_20260704.json → 88 unique tool names;
  set-diff vs the log's 88-name dump → empty; schema keys (SUMMARY/SERIES/
  CURRENT, start/end_epoch_millis, 3 default metric names) present; regex
  scan for key material → none
Read: deploy/baseten/mcp/mcp_client.py, live_infer_test.py → method matches
  doc's Deviation note and CSV schema
```

## Bottom line
Every displayed number now traces to a committed raw artifact and regenerates
exactly: the serving CSV, both SUMMARY captures, the SERIES capture, and the
new lifecycle transcript cross-corroborate with zero numeric discrepancies.
The only epistemic caveat is that the lifecycle log is an assembled (redacted)
transcript rather than a verbatim capture — corroborated at every overlap
point and contradicted nowhere. PASS.
