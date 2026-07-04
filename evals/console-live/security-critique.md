# Security Critique — console-live (Phase 2, BLOCKING gate)

**Verdict: PASS** (with one Low-severity defense-in-depth recommendation; no blocking findings)

Scope audited: the user's `BASETEN_API_KEY` must never be logged, persisted server-side,
echoed, or sent anywhere except `api.baseten.co`; proxy paths strictly allowlisted; no
injection vectors. Files reviewed line-by-line: `api/baseten.js`, `index.html`, `server.js`,
`README.md`, `tokens.css`, `vercel.json`. Live server on `localhost:4173` probed with FAKE
keys only (`dummykey…`); the real environment key was ignored throughout.

---

## 1. Proxy — `api/baseten.js`

**PASS.** GET-only, hardcoded upstream, closed allowlist, key never logged/echoed.

- **GET-only** (L35): non-GET → 405. Probe #1 (POST) → 405. ✓
- **Key validation** (L11, L36–39): `KEY_RE = /^[A-Za-z0-9._-]{10,200}$/`, anchored `^…$`.
  JS `$` (no `m` flag) does NOT match before a trailing newline (unlike Python), so a
  `key\nevil` header is rejected. Probe #3 (short key) → 400; probe #19 (newline key) → 400. ✓
- **Upstream host hardcoded** (L9): `https://api.baseten.co/v1/`. `path` is only ever
  concatenated onto this base (L42); it is never used to build a host. Absolute-URL and
  protocol-relative injection attempts (`new URL(base + path)`) stay under the base because
  the allowlist regexes reject anything containing `:`, `/`-prefix, or `.`. Probe #11
  (`https://evil.com/steal`) → 403; #12 (`//evil.com/steal`) → 403. ✓
- **Allowlist exactness** (L12–16): three anchored regexes; segments restricted to
  `[A-Za-z0-9_-]+` (no `.`, `/`, `%`, `\`). Bypass attempts all rejected with 403 and none
  reached upstream:
  - path traversal `models/../../training` (#5) → 403; nested-segment traversal (#6) → 403
  - URL-encoded slash `%2F..%2F..` (#7) → 403 (Node decodes query before regex; decoded
    string still contains `/` and `..` which the char-class rejects)
  - null byte `models%00/..` (#9) → 403; backslash (#10) → 403; CRLF `%0d%0a` (#17) → 403
  - encoded `?` smuggling `models%3Ffoo` (#14) → 403; trailing slash `models/` (#20) → 403;
    dotdot in metrics segment (#18) → 403
  - a genuinely allowlisted shape (`models/abc/deployments`, #8) DID forward and returned
    Baseten's own `403 PERMISSION_DENIED` for the fake key — confirming forwarding works and
    upstream rejects the bad key.
- **Query-param handling** (L17, L43–50): only `mode`, `start_epoch_millis`,
  `end_epoch_millis` are copied, and `metrics` only when `path.endsWith('/metrics')`. Values
  go through `URLSearchParams` (auto-encoded) into the query string — they cannot escape into
  the path. Unknown params (`evilparam`, `authorization`) are dropped (#16). `metrics` array
  smuggling `metrics=../../evil` (#15) lands only as an encoded query value, harmless. ✓
- **Duplicate `path` params** (#13) → 403: Vercel/`server.js` turn repeats into an array;
  L27 `typeof q.path === 'string'` is false for arrays → `path=''` → rejected. ✓
- **Key never logged/echoed** (L31, L60, L72): all three `console.log` lines print only
  `method / path / status`. The key lives solely in the upstream `Authorization: Api-Key …`
  header object (L54), never logged. Error responses (L32, L73) send only fixed strings
  (`{error:'…'}`); the upstream body passed through (L64) is Baseten's response, which does
  not contain the request key. The `upReq.on('error')` handler (L69–73) logs `502/504` and a
  generic message — a Node socket error message cannot contain the auth header. ✓
- **Timeout path** (L68): `setTimeout(10000)` → `destroy(new Error('upstream timeout'))` →
  error handler emits 504 with a generic body, no key. `res.headersSent` guard (L70) prevents
  double-send. ✓

## 2. Page JS — `index.html`

**PASS** for key handling; one **LOW** defense-in-depth note on innerHTML.

- **Storage** (L142): `let apiKey = null` inside an IIFE closure. Grep for
  `localStorage|sessionStorage|document.cookie|indexedDB|caches|sendBeacon` → **zero hits**
  across all files. Key never persisted client-side. ✓
- **Transport** (L157–163): key sent only as `x-baseten-api-key` header to same-origin
  `/api/baseten`; query string built via `URLSearchParams({path})` — key never in URL. ✓
- **Wipe on 401/403/disconnect** (L164–170, L476–497): upstream 401, and 403 remapped to 401
  when body is `PERMISSION_DENIED`, both route to `disconnect()` (L477) which sets
  `apiKey = null` (L486). Disconnect button (L515) same. ✓
- **No third-party requests** (L1–527, tokens.css): the only network call is `fetch('/api/…')`
  (same-origin). No CDN `<script>`/`<link>`, no web fonts, no analytics, no `@import`/external
  `url()` in `tokens.css`. Grep confirms no external URLs. ✓
- **innerHTML / XSS** (L342, L368, L377, L406, L443): all **string** fields sourced from the
  Baseten API — `model.name`, `model.id`, `dep.id`, `dep.name`, `dep.status`,
  `dep.instance_type_name`, and the composed `reco` string — are passed through `esc()`
  (L311–312, escapes `& < > " '`) before interpolation. `statusChip`/`chipClass` map into a
  fixed CSS-class set. The XSS vector flagged in the brief (attacker-influenced model/
  deployment names in a shared workspace) is **closed** — those are escaped. Verified each
  template literal individually.

## 3. Static server — `server.js`

**PASS.** Traversal blocked: L31 `!file.startsWith(ROOT + path.sep)` after `path.join`
normalizes `..`. Probes: `/../../../../etc/passwd` → 404; encoded `%2e%2e%2f` → 404; directory
`/api` → 404. No key logging (only L37 startup banner). `server.js` itself is served (200) but
contains no secret — the key is supplied at runtime and never written to any served file. ✓

## 4. README

**PASS.** Claims match code: key in a JS closure only (matches L142), never
localStorage/cookie/query (matches), sent as `x-baseten-api-key` and forwarded as
`Api-Key …` (L54), logs are method+path+status only (L31/60/72), three GET path shapes + four
query params allowlisted (L12–17 — README says "four query params"; code passes `mode`,
`start_epoch_millis`, `end_epoch_millis` plus the conditional `metrics` = four, accurate).
401/429 with `Retry-After` pass through (L63, L171–176). ✓

---

## Findings

### LOW-1 — Numeric API fields interpolated into innerHTML without escaping (defense-in-depth)
`index.html` L351 `${dep.active_replica_count ?? '—'}`, L353
`${st0.min_replica ?? '—'}–${st0.max_replica ?? '—'}` interpolate raw upstream JSON values
into `innerHTML` without `esc()` or numeric coercion. These are conventionally numbers, so
this is not exploitable against a well-behaved `api.baseten.co` (HTTPS-authenticated, values
server-validated as ints). But since the stated threat model includes "attacker-influenced if
a workspace is shared," a JSON response returning one of these as a string containing markup
would inject into the page holding the key. Contrast with all string fields, which ARE
escaped. Not blocking.

**Suggested fix (do not apply here):** coerce/escape these three interpolations, e.g.
`${esc(dep.active_replica_count ?? '—')}`, `${esc(st0.min_replica ?? '—')}`,
`${esc(st0.max_replica ?? '—')}` — or wrap in `Number(...)` with a `?? '—'` fallback. Same for
the computed numerics if strict, though `n`, `err4`, `err5`, `replicasAvg` are locally derived
via arithmetic and cannot be strings.

## Conclusion
No key ever reaches a log, disk, query string, third party, or any host other than
`api.baseten.co`. The proxy allowlist withstood every traversal/encoding/smuggling/absolute-URL
bypass attempt (probes #1–#20, all rejected pre-forward). The XSS surface on the key-bearing
page is escaped for all string fields. The gate **PASSES**; LOW-1 is an optional hardening.
