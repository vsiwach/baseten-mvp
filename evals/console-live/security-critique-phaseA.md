# Security critique — Phase A public deploy (console-live on Vercel)

**Date:** 2026-07-04
**Target:** https://baseten-reliability-console.vercel.app (live host, probed over network)
**Proxy under test:** `console-live/api/baseten.js` (audited clean pre-deploy at f6f76fe; re-read and re-probed here)
**Probe discipline:** only fake keys (`dummykey1234`) used. Real `BASETEN_API_KEY` / `VERCEL_TOKEN` never read or sent.

## VERDICT: PASS

## 1. Live proxy guard re-probe (all as designed)

| probe | expected | observed |
|---|---|---|
| `POST /api/baseten?path=models` | 405 | **405** |
| `GET ?path=secrets` (fake key) | 403 proxy reject | **403** `{"error":"path not allowlisted"}` |
| `GET ?path=models/x/logs` | 403 | **403** proxy body |
| `GET ?path=models/../../training` | 403 | **403** proxy body |
| `GET ?path=models%2F..%2F..%2Ftraining` (%2F-encoded traversal) | 403 | **403** proxy body |
| `GET ?path=https://evil.example.com/steal` (absolute-URL smuggle) | 403 | **403** proxy body |
| `GET ?path=//evil.example.com/steal` (protocol-relative) | 403 | **403** proxy body |
| `GET ?path=models` no key | 400 | **400** `missing or malformed x-baseten-api-key header` |
| key with spaces / 5-char key | 400 | **400** (KEY_RE `^[A-Za-z0-9._-]{10,200}$` enforced) |
| `GET ?path=models` fake key | Baseten 403 passthrough | **403** `{"code":"PERMISSION_DENIED","message":"Authorization error"}` |
| `GET ?path=models/abc123/deployments` fake key | Baseten 403 passthrough | **403** same Baseten body |

Rejection ordering ("before any upstream call") is corroborated three ways:
(a) code order in `api/baseten.js` — method check, key check, allowlist check
all `return` before `https.request` is constructed; (b) reject bodies are the
proxy's own JSON, distinct from Baseten's `PERMISSION_DENIED` shape; (c) reject
latency ~0.13s vs ~0.46s for the round trip to api.baseten.co.

**Headers:** rejects and passthroughs both return only benign headers
(`server: Vercel`, `x-vercel-cache`, `x-vercel-id`, HSTS, `cache-control:
public, max-age=0, must-revalidate`, content-type/length). No key echo, no
upstream URL leak, no `x-powered-by`, no set-cookie.

## 2. Static exposure (all clean)

| path | result |
|---|---|
| `/server.js`, `/README.md` | **404** (`.vercelignore` working) |
| `/api/baseten.js` | **400 from the function** — Vercel routes the `.js` path to the handler; source is NOT served |
| `/api/baseten.js.map` | 404 (no source maps) |
| `/api/`, `/api` | 404 text/plain (no directory listing) |
| `/.vercel/project.json`, `/.vercel/README.txt` | 404 |
| `/.vercelignore`, `/.gitignore`, `/vercel.json`, `/package.json`, `/.git/config`, `/.env` | 404 |
| `/`, `/index.html`, `/tokens.css` | 200 (the intended surface) |

## 3. Local repo hygiene (all clean)

- `git status --short`: only 3 untracked files — `console-live/.gitignore`
  (single line: `.vercel`), `console-live/.vercelignore` (`server.js`,
  `README.md`), and the evidence doc. `git diff` and `git diff --cached` both
  empty — nothing staged.
- `console-live/.vercel/` is untracked and gitignored; `project.json` contains
  only `projectId`/`orgId`/`projectName` — no token material.
- Grep of `console-live/` and the evidence doc for 40+ char token-like strings:
  only prose ("...incl. token generation...") and a benchmark filename. No
  key/token strings anywhere.

## 4. Vercel project env vars (evidence-based, not independently verified)

`PHASEA_DEPLOY_EVIDENCE.md` line 11 states `vercel env ls` was empty — no
env vars on the project, consistent with the design (key arrives per-request
in `x-baseten-api-key`, never server-side). I did not run the vercel CLI
(would require `VERCEL_TOKEN`, which this critique is forbidden to touch), so
this item is **accepted on evidence, not re-verified**. The architecture makes
it low-risk regardless: the proxy code reads no `process.env` at all.

## Notes / non-blocking observations

1. `Cache-Control: public, max-age=0, must-revalidate` on API responses is
   safe (nothing may be served stale, and Vercel's CDN doesn't key on request
   headers for functions anyway), but `no-store` on `/api/baseten` responses
   would be belt-and-suspenders against any future intermediary cache.
2. The user's real key transits browser → Vercel function → Baseten. The
   function never logs it (`logPath` logs only the path, key only placed in
   the upstream `Authorization` header); this remains the accepted trust
   tradeoff of the proxy design, unchanged from the pre-deploy audit.
3. During this critique the evidence file grew 39→44 lines (another session
   elaborating the render-test explanation). Content change is explanatory
   only; no security impact.
