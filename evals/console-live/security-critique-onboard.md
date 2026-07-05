# Security critique — onboarding UI (host-map refactor + onboard.html + index.html planner)

Date: 2026-07-05 (re-verified same day after fixes) · Auditor: security-critique agent (blocking gate before Vercel deploy)
Scope: `console-live/api/baseten.js` host-map refactor, new `console-live/onboard.html`,
`console-live/index.html` fleet planner, `console-live/data/*.json`, write proxy untouched-check,
live probes on `PORT=4178 node server.js` (fake key `dummykey1234` only; server killed after; port verified free).

## VERDICT: PASS

The first pass (earlier today) returned FAIL with two MEDIUM blockers and two LOW notes.
All four are now fixed in source and re-verified live. No key exposure, no storage of the key,
no third-party requests, no cross-host smuggling, prototype-pollution guard verified live,
write proxy untouched (0-line diff), offline suites re-run by this auditor: **38/38** and
**20/20** assertions pass; `node --check` clean on `api/baseten.js`, `api/baseten-write.js`,
`server.js`.

---

## Re-verification of the four findings (fixed)

### F1 · was MEDIUM · api/baseten.js — upstream mid-response abort hang → FIXED, live-verified

Fix confirmed in source (api/baseten.js, response callback): a `done` flag set on `'end'`, plus

```js
upRes.on('close', () => {
  if (done || res.headersSent) return;
  console.log(`GET ${logTarget} -> 502 (upstream closed mid-response)`);
  sendJson(res, 502, { error: 'upstream closed mid-response' });
});
```

Live re-run of the original 3/3 hang repro on :4178 (`?host=inference&path=models`, fake key):

| attempt | before fix | after fix |
|---|---|---|
| 1 | HTTP 000 (hang ≥15 s, no log line) | upstream 502 completed → **passed through in 0.29 s** |
| 2 | HTTP 000 | **502 `upstream closed mid-response` in 0.12 s** (close guard fired) |
| 3 | HTTP 000 | **502 `upstream closed mid-response` in 0.19 s** |

Server log shows the new line format (`GET inference:models -> 502 (upstream closed
mid-response)`), and `grep -c dummykey` on the log = 0 — key still never logged, including on
the new path. Residual note (upstream quirk, not a proxy flaw): inference.baseten.co aborts the
body of its 403 bad-key responses to Node clients, so a bad key on `host=inference` surfaces as
502 rather than a 401/403 passthrough; onboard.html surfaces the error and falls back to the
snapshot, which is the designed behavior. No hang, no cost amplification remains.

### F2 · was MEDIUM (latent XSS) · index.html renderPlanner — FIXED

The two previously-unescaped artifact fields now render through numeric coercion with null
guards (index.html:885):

```js
${o.requests != null ? Number(o.requests) : '—'} req / ${o.window_hours != null ? Number(o.window_hours) : '—'}h window
```

`Number()` returns a primitive number (`NaN` for hostile strings/objects), so markup injection
is impossible on these fields. All other artifact-derived strings in the renderer remain
`esc()`-wrapped as before. The `renderPlanner(rl-policy)` fixture test passes (part of 38/38).

### F3 · was LOW · index.html — chipClass prototype-chain lookup → FIXED

index.html:884 now reads
`Object.prototype.hasOwnProperty.call(chipClass, s.verdict) ? chipClass[s.verdict] : 'chip-warn'`
— `constructor`/`__proto__` verdict values can no longer resolve through the prototype chain.

### F4 · was LOW · onboard.html — raw catalog slug in copy-paste snippets → FIXED

onboard.html:573-577: `safeSlug()` gates every slug interpolated into the curl/python snippets:

```js
function safeSlug(slug) {
  return /^[A-Za-z0-9._\/-]{1,128}$/.test(slug) ? slug : 'INVALID_MODEL_SLUG';
}
function snippets(rawSlug) {
  const slug = safeSlug(rawSlug);
  ...
```

The charset excludes `'`, `"`, backslash, whitespace, and `$` — quote-breakout in the copied
shell/python command is closed. (The `#snippetSlug` header still shows the raw slug, but via
`textContent` — display-only, no DOM or copy-paste risk.)

## Remaining INFO items (non-blocking, unchanged)

- **F5 · INFO** — `buildPrompt` (onboard.html:773) still embeds the raw `chosenModel().slug`,
  live SKU name, and user HF repo in the agent handoff prompt: a prompt-injection surface into a
  billing-capable agent. Mitigations: no key in the prompt (verified), prompt pins "nothing that
  bills without my yes", the Claude Code tab shell-escapes via `shellSingleQuote`, and the prompt
  is rendered with `textContent`. Note `safeSlug` is scoped to `snippets()` and does NOT cover
  `buildPrompt` — acceptable as INFO, but extending `safeSlug` there would be cheap.
- **F6 · INFO (accepted deviation)** — mgmt allowlist is not byte-identical to the previously
  audited version: `^instance_type_prices$` added (api/baseten.js:24) for the planner and
  onboard leg 2. Read-only public pricing endpoint; same `Api-Key` scheme, same default-host log
  format, `PASS_PARAMS` behavior unchanged, `?path=secrets` still 403 (re-verified live).

---

## Checklist evidence (first pass, still valid; regressions re-run after fixes)

**1. Host map (api/baseten.js)** — default host `mgmt` preserves prior behavior except F6: same
three original path regexes, same `Api-Key` scheme, same `GET <path> -> <status>` / `(rejected)`
logging (no key ever logged). `inference` admits ONLY `^models$` with `Bearer` — verified by a
recording tap on `https.request`: `url=https://inference.baseten.co/v1/models`,
`Authorization: Bearer dummykey1234`. Prototype-pollution guard
(`typeof === 'string'` + `Object.prototype.hasOwnProperty.call(UPSTREAMS, hostName)`) verified
live: `__proto__`, `constructor`, `hasOwnProperty`, `bogus`, and repeated `host` params
(array → non-string) all → **400 unknown host** (re-verified after fix for `__proto__`/`bogus`).
Cross-host smuggling: `host=inference&path=models/../instance_type_prices` → 403;
`path=models%2F..%2Fchat%2Fcompletions` → 403 (anchored full-match regexes evaluated before URL
construction; allowed charsets exclude `/..`, `?`, `#`). Params passthrough gated on
`hostName === 'mgmt'` — inference receives zero caller params. Key travels only in the
`Authorization` header, never in query, never logged. **Write proxy untouched: 0-line diff**
(`git diff HEAD -- console-live/api/baseten-write.js`, re-checked after fixes).

**2. onboard.html** — key held in closure `apiKey` only; `grep localStorage|sessionStorage|
document.cookie|indexedDB` across console-live: **zero hits**. Input is `type=password`,
`autocomplete=off`, cleared on submit. Key sent solely via relative `fetch('/api/baseten?...')`
header; snapshot fetch carries no key header. No third-party requests (only external URL in
index.html is a pre-existing GitHub `href` — navigation only). `globalThis.__onboard` /
`__planner` test hooks expose no path to the key. Generated agent prompt contains no key
(snapshot-tested); snippet tabs use `$BASETEN_API_KEY` / `os.environ["BASETEN_API_KEY"]`
placeholders only. All catalog-derived strings hitting `innerHTML` escaped (`esc()` on name,
slug, features, math rows, SKU names, gpu labels); numeric cells `Number()`-coerced and
`isFinite`-filtered in `normalizeLive`; error/banner strings use `textContent`. F4 fixed.

**3. index.html planner** — instance prices fetched only via the same-origin proxy
(`api('instance_type_prices')`); static planner inputs via same-origin `/data/*.json`. Both
snapshot files inspected end-to-end: public model pricing + measured latency baselines only,
**no secrets**. Deep link uses `CSS.escape()`. `renderPlanner` now escapes/coerces every
artifact-derived field (F2, F3 fixed) — treating the future RL artifact file as untrusted input
holds.

**4. Live probes on :4178** (fake key; server killed after each session; `lsof -i :4178` = 0):

| probe | expect | first pass | after fixes |
|---|---|---|---|
| `?host=inference&path=models` + fake key | Bearer upstream, prompt error passthrough | Bearer ✓ via tap; **HANG** | **502 in <0.3 s** ×3 ✓ |
| `?host=inference&path=instance_type_prices` | 403 | 403 ✓ | (unchanged code path) |
| `?host=bogus&path=models` | 400 | 400 ✓ | 400 ✓ |
| `?host=__proto__` / `constructor` / `hasOwnProperty` | 400 | 400 ×3 ✓ | 400 ✓ (`__proto__` re-run) |
| repeated `host` param | 400 | 400 ✓ | — |
| `?path=models` (default-host regression) | mgmt passthrough | 403 `PERMISSION_DENIED` ✓ | 403 ✓ |
| `?path=instance_type_prices` | mgmt passthrough | 403 `PERMISSION_DENIED` ✓ | — |
| `?path=secrets` | 403 | 403 ✓ | 403 ✓ |
| no key / POST | 400 / 405 | ✓ / ✓ | — |

**5. git diff console-live/ for key material** — no key-like strings in the tracked diff or the
untracked `onboard.html`, `data/`, `test/onboard_flow_test.mjs`; only the header name,
`$BASETEN_API_KEY` placeholders, and the test's `dummykey1234`.

**6. Suites & syntax (post-fix)** — `node test/onboard_flow_test.mjs`: **38/38 PASS**
(includes proxy host-map unit probes, crossover parity, prompt snapshot, both planner fixtures,
snapshot-fallback path). `node test/write_flow_test.mjs`: **20/20 PASS**. `node --check` clean
on all three JS entry points.

## Ship decision

PASS — clear to deploy to the public Vercel app. Optional hardening for a later pass:
extend `safeSlug` to `buildPrompt` (F5).
