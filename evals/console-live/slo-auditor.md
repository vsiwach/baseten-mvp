# SLO-AUDITOR verdict — Phase 2 (console-live)

**VERDICT: PASS**

Audited: `/Users/vikramsiwach/Downloads/baseten-mvp/console-live/` (index.html,
api/baseten.js, server.js, README.md) against
`/Users/vikramsiwach/Downloads/baseten-mvp/evals/console-live/PHASE2_EVIDENCE.md`.
Constraint honored: no real key used; only localhost probes with a fake key.

## Commands run

```sh
# raw-file provenance
wc -l benchmarks/raw/live_mcp_activation_20260704-191318.csv          # 8 (header + 1 warmup + 6 measured)
cat benchmarks/raw/live_mcp_metrics_summary_20260704-191{352,613}.json
cat benchmarks/raw/live_mcp_metrics_series_20260704-191550.json

# regeneration (python3 reimplementation of the page's parseSummary/parseSeries/fmtMs
# and coldStartFlag/verdictFor, applied to the committed JSONs — see table)

# live localhost probes (fake key dummykey12345)
curl -s localhost:4173/ | shasum                                       # 865e5eae… == shasum of index.html on disk
curl -X POST '…/api/baseten?path=models' -H 'x-baseten-api-key: …'     # 405
curl '…/api/baseten?path=models'                                       # 400 missing key
curl '…/api/baseten?path=secrets' -H '…'                               # 403 path not allowlisted
curl 'localhost:4173/../CLAUDE.md'                                     # 404
curl '…/api/baseten?path=models' -H '…fake key…'                       # 403 {"code":"PERMISSION_DENIED"} passthrough
```

## Regenerated vs displayed/claimed

| claim (PHASE2_EVIDENCE.md) | regenerated from committed raw | match |
|---|---|---|
| 1h qwen card: n=7 | SUMMARY json counter = 7.0; SERIES per-bucket sum = 7.0 (2+5); activation CSV = 7 rows (1 warmup + 6 measured) | EXACT |
| 1h p50 1801ms | 1.801 s × 1000 → fmtMs → `1801ms` | EXACT |
| 1h p99 2136ms | 2.13594 s × 1000 → round → `2136ms` | EXACT |
| SERIES semantics: sum, not last−first | committed SERIES: sum = 7; last−first = 0−0 = 0 (would be wrong) | code correct |
| 6h: 19 req, p50/p90/p95/p99/avg = 20.25/100.68/107.14/112.308/35.358 s, replicas 0.0931 | no committed raw capture — internally consistent under the app's own rules: flag fires via n=19<20 (ratio 5.55<8 does NOT fire), eff = p95 = 107140ms, verdicts AMBER/AMBER exactly as evidence asserts | CONSISTENT, not independently reproducible (see note 1) |

Tolerance applied: none needed — counts exact; latency values reproduce to the
displayed millisecond using the page's own ×1000 + `Math.round` path.

## Code verification (frontend JS read line-by-line, index.html:202–429)

1. **SUMMARY counter = window total**: `parseSummary` sums `requests_total`
   values across label_sets from the single SUMMARY row (line 233). Correct.
   (Displayed n actually comes from SERIES, as the card footnote cites.)
2. **SERIES counter = per-bucket increments, summed**: `parseSeries` (247–264)
   sums across buckets, null→0; no last-minus-first anywhere. Verified against
   committed data where last−first would give 0 instead of 7.
3. **Histogram positional mapping**: `labelSets.forEach((ls,i) => vals[i])`;
   quantile 0.5/0.9/0.95/0.99 → p50/p90/p95/p99 via `Math.round(q*100)`;
   `stat:'avg'` → avg; seconds→ms via `v*1000` (line 228). Matches the real
   descriptor shape in the committed JSONs.
4. **No fabricated numbers**: the only numeric literals in the render path are
   SLO budgets (500/800), rule thresholds (8, 5000ms, 20, 5×, 30, 0.8), format
   and sparkline geometry. Loading state = "loading metrics…"; absent values
   render `—` (`fmtMs(null)`); no-traffic state renders an honest branch.
5. **SLO budgets**: `BUDGET_VOICE_MS = 500`, `BUDGET_INTERACTIVE_MS = 800`
   exactly; GREEN boundary `effMs <= 0.8*budget && !flagged && n>=30`; AMBER
   `<= budget || flagged || n<30`; RED otherwise — as documented.
6. **Cold-start/low-sample flag**: (p99/p50 ≥ 8 AND p99 > 5000ms) OR n < 20 OR
   (min_replica === 0 AND p99 > 5×p95) — matches documented rules; when
   flagged, `eff = lat.p95 ?? lat.p99` (switches to p95 as documented).
7. **Provenance footnotes**: every card's `.foot` cites the deployments GET,
   the metrics GET with `SUMMARY · last Nh · baseten_end_to_end_response_time_seconds
   (full response incl. token generation, not TTFT)`, and the `SERIES` traffic
   line — endpoint + mode + window + e2e-not-TTFT caveat all present.
8. **Live probes**: served index.html is byte-identical to the audited file;
   proxy behavior (405/400/403/404, upstream 403 PERMISSION_DENIED passthrough
   for a fake key) matches the evidence doc's offline-verification section.

## Notes (non-blocking)

1. The 6h SUMMARY values quoted in the evidence doc were captured live during
   Phase 2 and are not committed as a raw file; they cannot be regenerated
   offline and a live re-run is blocked by the no-real-key constraint. They are
   fully consistent with the app's rules (flag via n<20, AMBER/AMBER) and with
   the 7 committed Phase 1 requests being a subset of the 19. Since this is a
   live-data app whose displayed numbers are API responses at render time (the
   code path is what guarantees fidelity, and it is verified), this is noted
   rather than failed. Recommend committing the 6h SUMMARY capture for a
   complete trail.
2. The committed "1h" SUMMARY file's actual window is 900,000 ms (15 min), not
   1h; the numbers still match the 1h-card claim exactly because all 7 requests
   fall inside the burst (SERIES confirms zero traffic elsewhere in the window).
3. Cosmetic: the flag text always says "verdict uses p95" but `eff` falls back
   to p99 when p95 is null (edge case; no fake number results).
4. `parseSummary.requestsTotal` is computed but never displayed (n comes from
   SERIES, as cited). Dead-ish code, not a provenance violation.
5. SLO budgets are frontend constants rather than served by a policy API. For
   this BYO-key app there is no policy endpoint to fetch from and the mandate
   fixes the values (500/800, 0.8×); recorded for the future control-plane
   integration where budgets must come from the policy API.
