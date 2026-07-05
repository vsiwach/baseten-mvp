# Security critique — console-live v2 (write surface)

**Verdict: PASS** — ship-ready. The new write proxy is fail-closed at every layer probed;
no HIGH or MEDIUM findings. 27 live probes on a local instance (`PORT=4174`, fake key
`dummykey1234` only) plus line-by-line review of `api/baseten-write.js`, `server.js`,
and the `index.html` write flow. No code was edited.

Scope: `console-live/api/baseten-write.js` (new), `server.js` write mount,
`index.html` write flow, CSRF/CORS posture, repo hygiene. Reviewer ran its own
server on port 4174 and killed it after (verified free).

---

## 1. api/baseten-write.js — line-by-line

| Control | Lines | Status |
|---|---|---|
| POST-only | 50 | OK — GET → 405 (probe 1); OPTIONS → 405, no CORS headers (probe 23) |
| Key regex | 15, 51–54 | OK — `typeof === 'string'` first, so duplicate key headers (Node joins with `", "`) fail the regex; missing key → 400 (probe 2) |
| Closed action map | 21–26, 59–60 | OK — object literal, 4 actions only; `ACTIONS[action]` lookup on e.g. `"delete"`, `"__proto__"`-style names yields no own-property spec with these keys… note: `ACTIONS['constructor']` etc. — see finding I-5 below; probed `delete` → 403 (probe 3) |
| id regex | 16, 61–64 | OK — `^[A-Za-z0-9_-]{1,64}$` on both ids; excludes `/ ? # % .` so the interpolated upstream path (85–86) cannot be redirected; traversal probe → 400 (probe 6) |
| Autoscaling payload | 66–79 | OK — object, non-array, non-empty (probes 20, 22); every key in the 5-field set (extra field → 403, probe 16); every value `typeof number` + `Number.isFinite` + `0 ≤ v ≤ 100000` (negative → 400 probe 17, string → 400 probe 18, null → 400 probe 19, `1e21` → 400 probe 26) |
| No payload on other 3 actions | 80–83 | OK — `promote` with payload → 400 (probe 21). Edge: `payload: null` / `payload: 5` / `payload: []` slip past the check but `payload` stays `{}` and is never used for these actions — harmless |
| x-confirm-mutation equality | 89–93 | OK — server recomputes the exact string and does strict `!==`; see §1a |
| Timeout | 14, 121 | OK — 30 s, `destroy(Error('upstream timeout'))` → 504 via the error handler |
| Upstream host hardcoded | 13, 97–98 | OK — `https://api.baseten.co/v1` constant + validated path components; nothing caller-controlled can change host/scheme/query |
| No key in errors/logs | 45–48, 95, 113, 125 | OK — all reject bodies are static strings (one echoes a payload *field name*, see I-4); log lines are `WRITE <label> -> <status>` where label = action + ids, or `(rejected)`. Live log audit: 0 occurrences of the key across 27 requests |

### 1a. Confirm-header bypass attempts — all defeated

The server compares the header against `${method} ${path}` plus, for autoscaling,
` ${JSON.stringify(payload)}` of the **received** payload — i.e. against a
re-serialization of exactly what it will send upstream (line 96 sends
`JSON.stringify(payload)` of the same object). So the proof always describes the
actual upstream mutation, never the attacker's claimed one.

- **Wrong / missing / semantically different confirm** → 428 (probes 7, 8, 11).
- **Case tweak** (`post` vs `POST`) → 428 (probe 10). Header *names* are
  case-insensitive (Node lowercases them; `req.headers['x-confirm-mutation']` is
  correct), header *values* are compared byte-exact.
- **Unicode tricks** (NBSP for space) → 428 (probe 12); strict `!==`, no normalization.
- **Whitespace**: internal whitespace differences → 428 (probe 11). A *trailing*
  space in the header reached upstream (probe 9) — this is Node's HTTP parser
  stripping optional whitespace around header values per RFC 7230 **before** the
  comparison, not an equality bypass: the canonicalized value is byte-identical to
  the mutation string, so the confirmed semantics are unchanged. Not a finding.
- **Array headers**: duplicate `x-confirm-mutation` headers are joined by Node into
  `"a, a"` → 428 (probe 13).
- **JSON key-order determinism** (the subtle one): the client builds the header from
  ITS payload object and sends the body as `JSON.stringify` of the SAME object, so
  wire key order = client insertion order. `JSON.parse` preserves wire order for
  non-integer-like string keys, and `Object.entries`/`JSON.stringify` iterate own
  string keys in insertion order — so the server's re-stringify reproduces the
  client's header byte-for-byte. Verified analytically (node one-liner: match in both
  insertion orders) and live: 2-field payload with matching order passed the confirm
  gate and hit Baseten (403 PERMISSION_DENIED passthrough with the fake key, probe 14);
  the same payload with the header's keys swapped → 428 (probe 15). The only case
  where parse reorders keys — integer-like keys such as `"0"` — is unreachable: such
  keys are rejected by the field allowlist (line 74, → 403) before the confirm check.
- **Duplicate JSON keys in the body** (`{"min_replica":1,"min_replica":2}`):
  `JSON.parse` keeps the last value; the re-stringify is `{"min_replica":2}`, which a
  duplicate-key confirm string can't match → 428 (probe 27). The confirm proof always
  reflects the post-parse payload actually sent upstream.

## 2. CSRF / abuse posture (public static app)

- **No cookies anywhere.** Auth is a per-request custom header sourced from a JS
  closure variable; nothing is stored (no `localStorage`/`sessionStorage`/`document.cookie`
  in the codebase). Classic CSRF is structurally impossible: a cross-origin form/simple
  request cannot set `x-baseten-api-key`, and the handler 400s without it (probe 2).
- **CORS**: neither `api/baseten-write.js` nor `api/baseten.js` nor `server.js` sets any
  `Access-Control-Allow-*` header; there is no OPTIONS handler (OPTIONS → 405 with no
  ACAO, probe 23), and `vercel.json` is `{"version": 2}` — no headers/rewrites that
  could add CORS on Vercel. Cross-origin browsers can neither preflight the custom
  headers nor read responses. Same-origin fetch is the only browser path.
- **Residual risks (accepted, LOW — see finding L-1)**: the endpoint relays with the
  caller's key, so abuse requires possessing a valid key; but the function has no
  rate limit of its own, and a key thief could use it as an anonymizing relay
  (Baseten sees Vercel egress IPs) or burn Vercel invocations.

## 3. index.html write flow

- **Key closure-only** (line 187): `apiKey` lives in the IIFE; input cleared on submit
  (783); wiped on disconnect (755) including the 401-during-polling path (505–508);
  sent only as a header to the same-origin proxies (216, 447). Never rendered, never
  in a URL, never persisted.
- **Writes off by default, gating real**: `writesEnabled = false` (193), flipped only
  by the checkbox (800–803). The `.w-only` CSS hiding is cosmetic; the actual gate is
  in `onManageClick` (531): `!writesEnabled || pendingMutation || btn.disabled` → return.
  Disconnect resets the toggle and re-renders read-only (758–761).
- **One builder, exact display**: `mutationString()` (400–404) is the sole producer of
  the confirm string, mirrors the server's `ACTIONS` table; the modal shows
  `modalCtx.mutation` via `textContent` (424) and `confirmMutation` sends the identical
  `m.mutation` in the header (448) and builds the body from the same `m.payload` object
  (439–440) — display, header, and body cannot diverge. Server recomputation (line 91
  of the proxy) backstops any tampered client.
- **No mutation without Confirm**: the only `fetch('/api/baseten-write')` call site is
  inside `confirmMutation`, wired exclusively to `#modalConfirm` (805). Guarded against
  double-fire by `pendingMutation` (438).
- **Failure paths keep the key**: network error and non-OK responses render into
  `#modalError` via `textContent` (454, 459 — upstream body verbatim, but text-node safe)
  and return; key untouched. Only a 401 wipes it, deliberately.
- **Polling cannot mutate**: `startPolling`/`tick` use `api()` → GET `/api/baseten` only;
  auto-refresh (60 s) calls `refresh()` → GET only; one pending mutation at a time with
  manage buttons disabled while polling (472–474, 492–493).

## 4. server.js write mount

- Exact-path mount (`/api/baseten-write`), body accumulated with a 64 KB cap: a 100 KB
  body gets the socket destroyed mid-stream (curl exit 52, no HTTP response) and the
  server keeps serving (probes 24–25). Fail-closed; see I-2 for the nicety.
- Raw string handed to the handler; `readBody` catches `JSON.parse` failure →
  400 `JSON body required`, no crash (probes 4–5). `server.js` is local-only anyway:
  `.vercelignore` excludes it (and README) from deployment; on Vercel the platform
  parses JSON into `req.body` and enforces its own body limits.

## 5. Live probe matrix (all on :4174, fake key)

| # | Probe | Expected | Got |
|---|---|---|---|
| 1 | GET | 405 | 405 |
| 2 | POST, no key | 400 | 400 |
| 3 | action `delete` | 403 | 403 |
| 4/5 | malformed / empty JSON | 400 | 400 / 400 |
| 6 | `model_id: ../admin` | 400 | 400 |
| 7/8 | missing / wrong confirm | 428 | 428 / 428 |
| 9 | trailing-space confirm | (HTTP OWS-trimmed → match) | upstream 403 passthrough |
| 10/11/12 | case / inner-space / NBSP confirm | 428 | 428 × 3 |
| 13 | duplicate confirm headers | 428 | 428 |
| 14 | 2-field autoscaling, matched confirm | Baseten 403 passthrough | 403 `PERMISSION_DENIED` |
| 15 | same, key order swapped in header | 428 | 428 |
| 16 | extra field `replicas` | 403 | 403 |
| 17/18/19 | −1 / `"1"` / null value | 400 | 400 × 3 |
| 20/22 | empty / array payload | 400 | 400 / 400 |
| 21 | promote with payload | 400 | 400 |
| 23 | OPTIONS preflight | 405, no ACAO | 405, no ACAO |
| 24/25 | 100 KB body; server alive after | dropped; alive | conn dropped; 200 |
| 26 | `min_replica: 1e21` | 400 | 400 |
| 27 | duplicate JSON keys vs confirm | 428 | 428 |

Server log after all 27: `WRITE <label|(rejected)> -> <status>` lines only; grep for the
key: 0 occurrences.

## 6. Repo hygiene

`git diff HEAD -- console-live/` and a full grep of the tree: no key-like strings; the
only "long token" hit is a metric name in a doc string. Tests
(`test/write_flow_test.mjs`) use `dummykey1234` with a fully stubbed fetch — offline.
`.gitignore` excludes `.vercel`; `.vercelignore` keeps `server.js`/README out of the
deployment.

---

## Findings

No HIGH. No MEDIUM. Verdict unaffected by the items below.

**L-1 (LOW) — Unthrottled public relay.** `api/baseten-write.js` (and `api/baseten.js`)
relay any well-formed request carrying any regex-valid key; the function itself has no
rate limiting or origin check. Residual risks: anonymizing relay for a *stolen* key
(Baseten sees Vercel IPs, complicating the victim's log forensics), invocation-cost
abuse, and brute-force key probing laundered through your domain (bounded by Baseten's
own 401/403/429s, which pass through including Retry-After). Optional hardening, not
required for PASS: enable a Vercel WAF rate-limit rule on `/api/baseten-write`, and/or
reject requests whose `Sec-Fetch-Site` header is present and not `same-origin` as cheap
defense-in-depth (browsers send it; curl users are already key-holders).

**I-1 (INFO) — Header OWS trimming.** A confirm header with leading/trailing spaces
matches because Node strips RFC 7230 optional whitespace before the value reaches JS
(probe 9). Byte-exactness holds on the canonicalized value and the mutation semantics
are unchanged — documenting so a future reviewer doesn't mistake it for a bypass.

**I-2 (INFO) — Oversized body drops the socket silently.** `server.js:26` uses
`req.destroy()`, so a >64 KB body yields a connection reset rather than a 413. Correct
and fail-closed; local runner only (not deployed). If ever polished: respond
`413` then destroy.

**I-3 (INFO) — Non-autoscaling payload check is loose but inert.**
`baseten-write.js:80–83`: `payload: null` / numbers / `[]` bypass the "takes no payload"
reject (Object.keys of the `|| {}` fallback), but `payload` remains the unused `{}` for
those actions — no effect upstream. `{"anything":1}` is correctly rejected (probe 21).

**I-4 (INFO) — Reflected field name in one error.** `baseten-write.js:74` echoes the
offending payload key (`field not allowlisted: ${k}`). It is JSON-encoded server-side
and rendered via `textContent` client-side (index.html:459), so no injection; consider
truncating to 64 chars if you ever care about log/response tidiness.

**I-5 (INFO) — Plain-object action map.** `ACTIONS[action]` on a plain object literal:
`action: "constructor"` etc. resolve to inherited properties, but none of
`Object.prototype`'s members have `.method`/`.suffix`, and `spec.method` would be
`undefined` making the confirm string unmatchable anyway; `"delete"` probed → 403.
`Object.create(null)` or a `Map` would make the allowlist self-evidently closed.

**I-6 (INFO) — `noteFor` selector robustness.** index.html:469 interpolates the
deployment id into `querySelector('.note-' + id)` unescaped; an exotic id from the
(authenticated) API could throw a selector SyntaxError. Not attacker-reachable in any
meaningful way (ids used for mutations are re-validated server-side by `ID_RE`);
`CSS.escape()` would silence it.

---
Reviewed 2026-07-05 · local server on :4174 started and killed by the reviewer ·
fake key `dummykey1234` only · no code edited.
