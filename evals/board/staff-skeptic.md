# STAFF-SKEPTIC — Phase C (board integration + gated writes)

**Verdict: PASS** (top objection FIXED by reviewer, fix verified; full router
suite 149/149 green after the change). Date: 2026-07-05.

## JD lines actually demonstrated (vs claimed)

- **"how customers configure and observe them" / owns capabilities backend
  through UX** — real. `/v1/manage/options` is built purely from injected
  live snapshots (services/router/router_app/manage_options.py), every
  number traces to a source, and the board renders it via a single seam
  (design/live-fetch.js overriding `fetchJSON`). Verified live on :8196.
- **F5 release engine — drain** — partially. Sticky-quarantine placement
  exclusion + in-flight wait is genuinely built and wired
  (main.py:1086-1120); weighted KV-aware drain is honestly `[roadmap]`.
- **Self-serve incident mgmt / safe writes** — real defense-in-depth:
  env gate checked per request, closed 4-op allowlist, HMAC single-use
  confirm token bound to op|ids|body-hash|ts, key read inside the transport
  (writes.py). Gate-off 403 reproduced live; audit events emitted.
- **Cost/perf frontier** — the consequence lines are provenanced:
  $0.90/hr ⇐ deploy/LIVE_SETUP.md (T4x8x32 $0.01504/min), 148 s ⇐
  docs/FRICTION_LOG.md #17 (148.2 s measured), $/Mtok ⇐
  deploy/baseten/model-apis.json (fetched_at 2026-07-02), promote durations
  ⇐ demo/deploy-timeline.json (344 s final, 2579 s / 7 attempts).

## Judged items

1. **MANAGE consequences** — honest and provenanced (above), EXCEPT the
   spill card's mechanism claim (top objection, below). The no-op part is
   real: the mutation preview re-POSTs the current placement policy
   verbatim. Fleet/model previews carry real management ids (3ydn1e43 /
   qvm1v4e); pools without real ids get no card (manage_options.py:170).
2. **Graceful drain** — REAL, not theater. The quarantine flag makes
   `usable` False (health.py:24-26) and `usable` gates every selection
   path: chat via `select_replica` `is_usable` on both the affinity ring
   membership and fallback (policy.py:113,118,123 — holders/order are built
   from `eligible` only), and legacy predict via `healthy_endpoints`
   (policy.py:50). `kvstate.pending` is a real in-flight counter inc/dec'd
   in try/finally around actual upstream calls (main.py:227/251, 294-347).
   `[built]`/`[roadmap]` labeling is truthful and test-enforced
   (test_manage_options.py::test_drain_steps_labeled_built_vs_roadmap).
   Exercised live on :8196: drain → quarantine + `drain_started`/
   `drain_complete` events, 404 on unknown pool. Gaps ranked below (#2).
3. **Write acceptance evidence** — internally consistent. The 6-event audit
   trail matches the code's emission order exactly (requested→executed,
   reuse: requested→denied, revert: requested→executed; token GETs emit
   nothing on success). max_replica 1→2→1 with INACTIVE/0-replicas
   throughout is coherent (autoscaling PATCH doesn't activate). The
   8090-404-not-403 explanation is sound: a pre-Phase-C process has no
   /v1/writes routes loaded at all — no route, no write path, no bypass;
   the current code's gate-off 403 was verified by tests and reproduced by
   me live. No key material in events (allowlisted numeric body only).
4. **Policy promote** — honest. Endpoint writes
   learning/pending-policy.json `{"status":"awaiting_approver"}`, emits
   `policy_promote_proposed`, never touches the live AgentConfig
   (main.py:917-952; test_board_routes.py:116-145). policy.html's button
   flips to "Promotion requested — awaiting approver". No autonomy
   overclaims found in UI or READMEs; the confirm gating is described as
   human-in-the-loop and is.
5. **100x** — see below.
6. **Built-vs-roadmap labeling** — truthful overall (drain roadmap step,
   `/v1/roadmap` stays authored mock per contract, DESIGN.md deviations
   dated). One copy fix needed (top objection).

## Ranked objections

1. **[TOP — FIXED] Spill card claimed "placement already spills overflow"
   — false mechanism.** With affinity enabled
   (configs/routing-policy.yaml:34), `model-api-spill` is a consistent-hash
   PEER of `baseten-l4` in the qwen3-8b replica set: `select_replica` rings
   over ALL candidates (policy.py:125-138), so a hash share of new prefixes
   lands on the per-token pool in steady state — not only under
   degradation. Consequently `_spill_count`'s "off-pool placement == spill
   (overflow)" docstring was wrong and the risk line's "N spill placements"
   conflates steady-state hash placement with degraded-mode spill. Also the
   no-op preview re-POSTs a placement policy that contains no Model-API
   pool — the spill behavior actually comes from the endpoint entry lacking
   a `pool` key (placement filter bypass), not from that document.
   **Resolution: fixed by reviewer** — manage_options.py consequence text
   and `_spill_count` docstring now state the hash-peer semantics and label
   overflow-only spill as roadmap; dated deviation #11 added to
   design/DESIGN.md. All 149 router tests green after the fix.
2. **Drain endpoint is the one Phase C surface with zero tests and zero
   recorded evidence** (main.py:1086-1120; no hits in tests/ or
   PHASEC_WRITE_EVIDENCE.md — `can_stop_drained` tests cover a one-line
   pure function, not this route). Plus: (a) `kvstate.pending` counts chat
   traffic only — a /v1/predict request in flight is invisible, so graceful
   drain can report "drained" early; (b) there is no un-drain — the sticky
   quarantine is lifted only by the incident agent for its OWN cases or a
   restart; (c) the graceful wait busy-polls a threadpool thread for up to
   300 s. I exercised the endpoint live, which mitigates "theater" but not
   the missing regression coverage.
3. **operate.html feed fabricates liveness** (design/operate.html:206-242):
   it replays a static ≤30-row snapshot of real decisions on a randomized
   900-2300 ms timer, looping (`feed[idx % feed.length]`) — real rows, fake
   cadence, old decisions presented as a continuing stream. Honest fix:
   re-fetch the snapshot per tick or timestamp the rows.
4. **Silent mock fallback in live mode** (design/live-fetch.js:25-28): any
   endpoint failure falls back to `window.MOCK` with one generic corner
   note ("some panels: sample data") — a live board can render fabricated
   numbers per panel without saying which. Not itemized as a dated
   deviation.
5. **Write path is single-process by construction** (writes.py:32-33):
   per-process `os.urandom` HMAC secret + in-memory `_used_tokens` set that
   is never pruned. Behind >1 router replica the confirm handshake fails
   closed (mint on A, verify on B → 403) — safe but product-breaking; the
   set also grows unboundedly (trivial fix: store ts, prune on expiry).
6. **Hard-coded price/cold-start constants** (manage_options.py:18-19):
   $0.90 and 148 s are cited constants, not config (LIVE_SETUP.md already
   defines BASETEN_USD_PER_HOUR). Reprice ⇒ silent drift.
7. **Cosmetic**: manage.html confirm summary says "This mutates
   production." even for the spill no-op card (manage.html:116).

## 100x analysis

- **manage options at 50 pools**: `build()` filters the full
  `metrics.window(900)` per replica → O(pools × samples) with samples
  bounded at 50k, and `window()` copies under a lock per request
  (metrics.py:59-76). Board is fetch-on-load (no polling loop found in
  console.js), so viewer load is one ~9-fetch batch per page view — fine;
  the O(P×S) scan is the first thing to precompute per tick at 100x.
- **Token set growth**: unbounded but slow (gate-on only); prune-on-TTL is
  the fix. The real 100x break is #5's single-process secret.
- **SSE `/v1/placement/feed`** holds a threadpool thread per client with a
  0.25 s sleep loop (main.py:1011-1025); the board deliberately uses the
  snapshot lens instead (DESIGN.md deviation 3) — correct call. Concurrent
  graceful drains similarly hold threads (up to 300 s each) — at fleet
  scale that exhausts the default ~40-thread pool and the board goes
  unresponsive; drain should be async or job-based.
- **All drain/quarantine/pending state is per-process, single-region** — a
  second router replica keeps routing to a "drained" pool. Fine for the
  demo's stated scope; would page someone at 3am in HA.

## Top objection resolution

Fixed and verified: manage_options.py spill copy + `_spill_count` docstring
corrected to hash-peer semantics with overflow-only spill labeled roadmap;
design/DESIGN.md deviation #11 (dated 2026-07-05) records it, including the
preview/mechanism mismatch. `pytest tests/` → 149 passed.

## Live verification (port 8196, INCIDENT_AGENT=0, fake key, gate off)

- `/v1/manage/options` payload matches tests; consequence numbers traced to
  LIVE_SETUP.md, FRICTION_LOG #17, model-apis.json, deploy-timeline.json.
- `/v1/writes/token` and `/v1/writes/baseten` → 403 `writes disabled` with
  `baseten_write_denied` audit events.
- `POST /v1/pools/baseten-l4/drain?mode=graceful` → drained,
  `drain_started`/`drain_complete` events; unknown pool → 404.
- Router killed after the run; :8196 confirmed down.
