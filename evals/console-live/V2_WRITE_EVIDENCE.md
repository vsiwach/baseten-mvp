# console-live v2 evidence — opt-in manage actions on the public console (2026-07-05)

User-directed pivot: the read-only console gained gated write actions
(activate / deactivate / autoscaling / promote), a last-7d window, and
visibility of ALL onboarded deployments per model.

## Write-path design (security-critique-v2.md: PASS, 27 live probes)
- Separate POST-only serverless function api/baseten-write.js; closed
  4-action map; strict id regex; autoscaling payload = exactly the 5 numeric
  fields, finite/non-negative; other actions reject any payload.
- Confirm proof: the request must carry x-confirm-mutation equal to the exact
  mutation string the modal displayed; the server recomputes and compares
  (mismatch → 428). Unicode/whitespace/case/duplicate-header/JSON-key-order
  bypass attempts all rejected in the audit.
- No cookies + no CORS headers → cross-origin CSRF structurally impossible;
  the caller's own key (memory-only, header-only) is the sole authority.
- UI: writes OFF by default; amber "WRITES ENABLED" chip + banner swap; one
  mutation at a time; one confirm modal showing the exact API call + an
  honest consequence line (billing, cold start, dropped in-flight, rollback);
  post-accept polling to the expected state. Offline DOM harness: 20/20
  (console-live/test/write_flow_test.mjs).

## Real lifecycle THROUGH the new path (UTC, 2026-07-05; local server)
| time | step | result |
|---|---|---|
| 16:06:31 | POST /api/baseten-write activate qvm1v4e (confirm header matched) | 200 {"success": true} |
| 16:09:50 | read-proxy poll | ACTIVE, 1 replica (~3.3 min cold start) |
| 16:10:xx | 7 streaming inferences (deploy/baseten/mcp/live_infer_test.py) | 7/7 HTTP 200, warm TTFT 298–380 ms |
| 16:10:5x | POST /api/baseten-write deactivate (confirm matched) | 200 {"success": true} |
| 16:11:14 | read-proxy verify | **INACTIVE, 0 replicas** |
Server log: zero key material (grep count 0). Spend ≈ 4.7 min T4 ≈ $0.07.

## Public host verification (https://baseten-reliability-console.vercel.app, post-deploy)
- Page serves v2 (write toggle present).
- /api/baseten-write on the live host: GET → 405; POST without key → 400;
  non-allowlisted action → 403; confirm mismatch → 428; well-formed with a
  fake key → Baseten's own 403 PERMISSION_DENIED passed through verbatim.
- Read path unchanged: real models still render.

## Honesty boundary (unchanged, restated in README + UI)
Deployment-level operations only. No traffic-level drain/self-heal from this
console — the deactivate consequence line says in-flight requests can drop
and points at the control-plane demo. KV-aware graceful migration is the
router's job (in progress as its own feature).
