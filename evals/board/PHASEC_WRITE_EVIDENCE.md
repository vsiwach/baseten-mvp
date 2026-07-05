# Phase C evidence — gated write acceptance test (2026-07-04)

The ONE real mutation the mission requires: an autoscaling PATCH against a
real Baseten deployment through the full gated path, then reverted.

Target: model 3ydn1e43 (qwen3-8b-vllm), deployment qvm1v4e — INACTIVE with
0 replicas throughout (autoscaling-settings changes do not activate replicas;
zero spend).

## Timeline (UTC epoch seconds from the audit events; router on :8199 with CONSOLE_ALLOW_WRITES=1)
| step | result |
|---|---|
| baseline read (management API) | max_replica=1, min=0, INACTIVE, 0 replicas |
| GET /v1/writes/token (op=autoscaling, body_sha256 of {"max_replica":2}) | 200, ttl 120 s |
| POST /v1/writes/baseten (token flow) | 200; upstream Baseten 200 "ACCEPTED" |
| immediate token REUSE | **403 "token already used"** |
| verify read | **max_replica=2**, still INACTIVE, 0 replicas |
| second token + revert POST ({"max_replica":1}) | 200; upstream 200 ACCEPTED |
| verify read | **max_replica=1**, min=0, INACTIVE, **0 replicas** |

## Audit trail (router /v1/events, seq 1-6)
baseten_write_requested → baseten_write_executed (op, ids, PATCH path, body
{"max_replica":2}, status 200) → baseten_write_requested →
baseten_write_denied ("token already used") → (revert pair). No key material
in any event (body fields are autoscaling integers by allowlist construction).

## Gate-off behavior
- Unit-tested: all /v1/writes/* → 403 {"error":"writes disabled"} unless
  CONSOLE_ALLOW_WRITES=1 (services/router/tests/test_writes.py).
- Browser smoke (dev run): manage confirm modal rendered the 403 verbatim.
- Note: the long-running corpus-stack router on :8090 returns 404 (not 403)
  for /v1/writes/* — that process was started before this code existed and
  has no writes routes loaded at all; not a gate bypass. The gate-off 403 is
  the behavior of the current code, verified by tests.

## Write-surface properties (verified by tests + this run)
- OFF by default; env-gated per request.
- Closed allowlist: exactly {autoscaling PATCH, activate, deactivate,
  promote}; autoscaling body keys ⊆ the 5 numeric fields; ids regex-bound.
- Confirm-token: HMAC(secret, op|model|dep|body_sha|ts), 120 s ttl,
  single-use, constant-time compare, recomputed over the actual POSTed body
  (tamper → 403).
- BASETEN_API_KEY read from env inside the transport; never logged; requests
  go only to https://api.baseten.co/v1.
- console-live (public Vercel app) has NO write path — router-only by design
  (dated deviation in design/DESIGN.md).
