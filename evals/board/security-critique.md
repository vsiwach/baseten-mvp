# Security critique — Phase C gated writes + board routes

**Verdict: PASS** (no High/Critical findings; 3 Low/Informational notes, no code
edits required to ship).

Scope: the new write surface (`services/router/router_app/writes.py`,
`/v1/writes/*` and `/v1/learning/policy/promote` in `main.py`), the design board
routes (`/board/*`, `/board-assets/*`), and confirmation that `console-live/`
gained no write path. Method: line-by-line read of the code, adversarial
`TestClient` bypass suite (no network, monkeypatched env + fake transport,
since removed), and a repo-wide masked secret sweep. Evidence claims in
`evals/board/PHASEC_WRITE_EVIDENCE.md` audited against the code below — all
substantiated.

---

## 1. Write surface — `writes.py` + routes (main.py:1217–1277)

Defense-in-depth verified against the code:

- **Master gate** (`gate_open`, writes.py:48; enforced main.py:1232, 1247):
  `CONSOLE_ALLOW_WRITES == "1"` checked **per request** at the top of both the
  token and execute handlers. Default/unset → 403 `{"error":"writes disabled"}`.
  Unsetting the env on a running process closes the gate immediately. PASS.
- **Closed 4-op allowlist** (`OPS`, writes.py:39–45; `validate_target`:68):
  op must be a key of the `OPS` dict; the path template is server-owned, so no
  caller-controlled path segment reaches Baseten except the two ids, which must
  match `^[A-Za-z0-9_-]{1,64}$`. `op=delete_model` / `op=logs` → 403 at both the
  token and execute steps. PASS.
- **Autoscaling body is numeric-only by construction** (`validate_body`:78–91):
  keys must be a subset of the 5 fields `{min_replica, max_replica,
  autoscaling_window, concurrency_target, scale_down_delay}`; values must be
  `int|float` and **explicitly reject `bool`** (`isinstance(v, bool)` guard,
  line 86). Verified by bypass tests — smuggling extra keys, string values
  (`"2; DROP"`), nested objects (`{"$gt":0}`), and booleans are all 403 with
  the transport never called. `activate/deactivate/promote` reject any non-empty
  body (line 89) and send `{}` upstream (execute:139). PASS.
- **HMAC confirm-token** (`mint`:62, `check_token`:94):
  token = `HMAC-SHA256(secret, "op|model|deployment|body_sha256|ts")`.
  - `_SECRET = os.urandom(32)` at import (line 32) — single-process, in-memory,
    dies with the process. See Note A on multi-worker.
  - Binds op, both ids, body hash, and ts — a forged or wrong-key token fails.
  - **Body recomputed server-side**: `check_token` re-hashes the actual POSTed
    `body` (line 105), so tampering the body after minting → 403 (test:
    max_replica 3→30 rejected, transport untouched). PASS.
  - **Constant-time compare**: `hmac.compare_digest` (line 106). PASS.
  - **TTL 120 s** (line 103): expired ts → 403 `"expired"`. PASS.
  - **Single-use**: token added to `_used_tokens` on success (line 110); reuse →
    403 `"already used"` (matches evidence step "immediate token REUSE 403").
    PASS.
- **Upstream host hardcoded** `https://api.baseten.co/v1` (`API_BASE`, line 29);
  no caller input reaches the host. PASS.
- **`BASETEN_API_KEY` read inside the transport** (`urllib_transport`:117), sent
  only as the `Authorization: Api-Key …` header, never returned. No `print`/
  `logging` anywhere in writes.py (grep clean). Audit events
  (`baseten_write_requested`/`_executed`/`_denied`, main.py:1262–1274) carry
  op/ids/status/method/path and — for autoscaling only — the numeric body;
  never the key. Bypass test with `BASETEN_API_KEY=SECRETKEY123456` set
  confirmed the string never appears in the emitted event log. PASS.

## 2. Adversarial bypass suite (TestClient, no network/key)

All rejected with the transport never invoked (unless noted):
no token → 403; forged token → 403; expired ts → 403; future ts (forged, no
secret) → 403 (HMAC binds ts, server only ever mints ts=now — see Note C);
`op=delete_model` → 403 at token+execute; traversal/injection in `model_id`
(`../../evil`, `a/b`, `a b`, 65-char, `m;rm`) → 403; oversized body (1000 keys) →
403 (extra-keys guard); duplicate JSON keys (`max_replica` 2 then 50) → 403
(Python keeps the last value → body hash ≠ token binding). Existing
`tests/test_writes.py` (23 assertions incl. gate-off, roundtrip, tamper,
expiry, reuse, 5th-op, bad ids/keys) passes green.

## 3. Board routes (main.py:711–742)

- `/board/{page}`: page must be in the 5-tuple `(operate, deploy, policy,
  manage, roadmap)` (line 720). Starlette `{page}` never matches `/`, and any
  non-member string → 404. Directly exercised: `../writes`, `..`, `etc/passwd`,
  `../../secrets`, `writes` all DENIED; only exact members read a file. (The one
  bypass-test "failure" for `operate/../manage` was httpx **client-side** path
  normalization to `manage`, a legitimately allowlisted page — the server never
  saw a traversal string.) PASS.
- `/board-assets/{name}`: name must be a key of the 5-entry `_board_assets`
  dict (line 739); traversal (`../main.py`, `writes.py`) → 404. `FileResponse`
  is built from `_design_dir / name` only after the allowlist check. PASS.
- Served HTML contains no secrets: grep of `design/*.html` finds only
  confirm-`token` / CSS-`tokens` references; no `Api-Key`/`BASETEN_API_KEY`/
  bearer material. PASS.

## 4. console-live — no write path (item 4)

`console-live/api/baseten.js` is a **GET-only** read proxy: `if (req.method !==
'GET') return reject(405)` (line 35); a closed 3-regex GET allowlist (models /
deployments / metrics); key taken from the `x-baseten-api-key` header, sent
upstream as `Api-Key`, never logged/stored/echoed (log line prints method +
allowlisted-or-`(rejected)` path only). `server.js` is a static dev server with
no proxy methods. `index.html` holds the key in memory only (`apiKey = null;
// wipe`). No `/v1/writes`, no PATCH/POST/PUT/DELETE forwarding anywhere in
console-live. PASS — matches the evidence's "router-only writes" claim.

## 5. Learning promote (main.py:917–952)

`POST /v1/learning/policy/promote` validates `config` against **exactly** the
7 `AgentConfig` fields (`set(config) != expected` rejects both extra and missing
keys, line 933) and rejects non-numeric / bool values (line 937). It writes only
`{config, proposed_at, status:"awaiting_approver"}` to
`learning/pending-policy.json` (`PENDING_POLICY_PATH` overridable) — **no
hot-apply**; the live `AgentConfig` is untouched (docstring + code confirm).
Bypass tests: extra key → 400, missing key → 400, valid 7-scalar → 200 writing
only the config. PASS.

## 6. Secrets sweep

`git status` + full tracked `git diff` + repo-wide masked grep
(`Api-Key <20+ chars>` / `Bearer …` / `BASETEN_API_KEY=…`) over
`.py/.js/.html/.md/.json/.yaml/.env/.sh`: **no hardcoded key-shaped strings**.
Every key reference is `os.environ` / `process.env` / a request header. No
`.env` or key file staged. PASS.

---

## Findings (all Low / Informational — no fix required to ship)

- **Note A (Low) — single-process HMAC secret.** `_SECRET = os.urandom(32)`
  (writes.py:32) is per-process. Under a multi-worker deploy (e.g. `uvicorn
  --workers >1`) a token minted by worker A won't verify on worker B → spurious
  403s. **Fails closed** (a security *non*-issue), but a correctness footgun.
  *Fix if multi-worker is ever used:* derive the secret from a shared env/KMS
  value, or pin token mint+execute to one worker (sticky session).
- **Note B (Low) — `_used_tokens` grows unbounded.** writes.py:33/110 never
  prunes; expired tokens stay in the set forever. Bounded by the count of
  *successful* writes (human-gated, rare), so not a practical DoS, but it is an
  unbounded in-memory set. *Fix:* store `(token, exp)` and drop entries past TTL,
  or use a TTL cache.
- **Note C (Informational) — no upper bound on `ts`.** `check_token` only
  checks `now - ts > TTL` (line 103); a far-future ts passes the freshness test.
  Not exploitable today (the HMAC binds ts and the server only mints `ts=now`,
  so a future-dated token needs the secret), but if the secret ever leaked, a
  future-dated token would be effectively long-lived. *Optional hardening:*
  reject `ts > now + small_skew`.
- **Design property (Informational, not a finding).** The confirm token is an
  anti-replay/anti-tamper binding, **not** authentication. Real authorization is
  the master gate (`CONSOLE_ALLOW_WRITES`) plus possession of
  `BASETEN_API_KEY`; the router has no per-user authN on `/v1/writes/*`. This is
  consistent with the "trusted operator console on the same trust boundary"
  design and is documented in the evidence file; deploying the router with the
  gate on must therefore remain a trusted-network / operator-only posture.

No code was edited. The ad-hoc bypass test used to gather evidence was removed
after the run.
