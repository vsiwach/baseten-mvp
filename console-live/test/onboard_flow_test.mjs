// onboard_flow_test.mjs — OFFLINE tests for the onboarding surface:
//   1. proxy host map (api/baseten.js): inference host admits only `models`
//      with Bearer auth; mgmt default unchanged (incl. new instance_type_prices,
//      Api-Key auth); unknown host → 400.
//      Auth-scheme assertions use the SIMPLER of the two allowed strategies:
//      unit-importing the handler with a monkey-patched https.request that
//      records the upstream URL + headers (no network, no recording stub
//      server needed). Routing rejections (400/403) are ALSO exercised
//      end-to-end through server.js on port 4177 — those paths never contact
//      an upstream, so a fake key is safe.
//   2. crossover JS === scripts/crossover.py self-test vectors.
//   3. generated-prompt snapshot (fixed inputs → exact text).
//   4. planner renderPlanner with two fixtures: a measured-comparison artifact
//      built by buildPlannerModel, and a synthetic rl-policy artifact —
//      proving the placement-recommendation/v1 contract needs zero rework.
//   5. snapshot-fallback banner path in onboard.html.
// Fake key only; no real workspace is ever contacted.
//   node console-live/test/onboard_flow_test.mjs
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { spawn, spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FAKE_KEY = 'dummykey1234';
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, '..');
const REPO = path.join(ROOT, '..');

const results = [];
function check(name, ok, detail = '') {
  results.push(ok);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ============================================================
// 1a. proxy host map — unit-imported handler, patched https
// ============================================================
const require = createRequire(import.meta.url);
const https = require('node:https');
const proxy = require(path.join(ROOT, 'api', 'baseten.js'));

const upstreamCalls = [];
const origRequest = https.request;
https.request = (url, opts, cb) => {
  upstreamCalls.push({ url: String(url), headers: opts.headers });
  return {
    setTimeout() {}, on() {},
    end() {
      const upRes = {
        statusCode: 200, headers: { 'content-type': 'application/json' },
        setEncoding() {}, _data: null,
        on(ev, fn) {
          if (ev === 'data') this._data = fn;
          if (ev === 'end') { this._data('{"ok":true}'); fn(); }
        },
      };
      cb(upRes);
    },
  };
};

function callProxy(query, { key = FAKE_KEY, method = 'GET' } = {}) {
  const req = { method, query, headers: {} };
  if (key !== null) req.headers['x-baseten-api-key'] = key;
  const res = {
    statusCode: 0, headers: {}, body: '', headersSent: false,
    setHeader(k, v) { this.headers[k] = v; },
    end(b) { this.body = b || ''; },
  };
  proxy(req, res);
  return res;
}

{
  let r = callProxy({ host: 'inference', path: 'models' });
  let up = upstreamCalls.at(-1);
  check('host=inference&path=models proxies to inference.baseten.co/v1/models',
    r.statusCode === 200 && up.url === 'https://inference.baseten.co/v1/models', up.url);
  check('inference host uses the Bearer auth scheme',
    up.headers.Authorization === `Bearer ${FAKE_KEY}`, up.headers.Authorization);

  r = callProxy({ path: 'instance_type_prices' }); // no host param → mgmt default
  up = upstreamCalls.at(-1);
  check('default host admits new instance_type_prices path on api.baseten.co',
    r.statusCode === 200 && up.url === 'https://api.baseten.co/v1/instance_type_prices', up.url);
  check('mgmt host keeps the Api-Key auth scheme',
    up.headers.Authorization === `Api-Key ${FAKE_KEY}`, up.headers.Authorization);

  const before = upstreamCalls.length;
  r = callProxy({ path: 'models/m1/deployments/d1/metrics', mode: 'SUMMARY',
    start_epoch_millis: '1', end_epoch_millis: '2', metrics: ['a', 'b'] });
  up = upstreamCalls.at(-1);
  check('mgmt metrics param passthrough unchanged (mode/start/end/metrics)',
    upstreamCalls.length === before + 1 && up.url ===
    'https://api.baseten.co/v1/models/m1/deployments/d1/metrics?mode=SUMMARY&start_epoch_millis=1&end_epoch_millis=2&metrics=a&metrics=b',
    up.url);

  let n = upstreamCalls.length;
  r = callProxy({ host: 'inference', path: 'instance_type_prices' });
  check('inference host admits ONLY models: instance_type_prices → 403, no upstream call',
    r.statusCode === 403 && upstreamCalls.length === n);

  r = callProxy({ host: 'bogus', path: 'models' });
  check('unknown host → 400', r.statusCode === 400 &&
    JSON.parse(r.body).error === 'unknown host');

  r = callProxy({ host: '__proto__', path: 'models' });
  check('host=__proto__ does not resolve a host (prototype guard) → 400',
    r.statusCode === 400);

  r = callProxy({ host: 'inference', path: 'models' }, { key: null });
  check('missing key still rejected 400 before host handling', r.statusCode === 400);
}
https.request = origRequest;

// ============================================================
// 1b. proxy host map — end-to-end through server.js on :4177
//     (only rejection paths: they never contact an upstream)
// ============================================================
{
  const child = spawn(process.execPath, [path.join(ROOT, 'server.js')],
    { env: { ...process.env, PORT: '4177' }, stdio: 'ignore' });
  try {
    let up = false;
    for (let i = 0; i < 50 && !up; i++) {
      try { await fetch('http://localhost:4177/tokens.css'); up = true; }
      catch { await sleep(100); }
    }
    check('server.js came up on :4177', up);

    let res = await fetch('http://localhost:4177/api/baseten?host=bogus&path=models',
      { headers: { 'x-baseten-api-key': FAKE_KEY } });
    check('server.js: unknown host → 400', res.status === 400);

    res = await fetch('http://localhost:4177/api/baseten?host=inference&path=instance_type_prices',
      { headers: { 'x-baseten-api-key': FAKE_KEY } });
    check('server.js: inference host rejects non-models path → 403', res.status === 403);

    res = await fetch('http://localhost:4177/api/baseten?path=models');
    check('server.js: missing key → 400 (mgmt default intact)', res.status === 400);
  } finally {
    child.kill();
  }
}

// ============================================================
// shared stub DOM (same shape as write_flow_test.mjs)
// ============================================================
class FakeEl {
  constructor(tag = 'div') {
    this.tag = tag; this.className = ''; this.children = [];
    this._innerHTML = ''; this.subs = new Map(); this.listeners = {};
    this.hidden = false; this.value = ''; this.textContent = ''; this.checked = false;
    this.dataset = {};
  }
  set innerHTML(v) { this._innerHTML = v; if (v === '') { this.children = []; this.subs.clear(); } }
  get innerHTML() { return this._innerHTML; }
  querySelector(sel) {
    if (!this.subs.has(sel)) this.subs.set(sel, new FakeEl());
    return this.subs.get(sel);
  }
  querySelectorAll() { return []; }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  focus() {}
}
const registry = new Map();
const $ = (id) => { if (!registry.has(id)) registry.set(id, new FakeEl()); return registry.get(id); };
globalThis.document = { getElementById: $, createElement: (tag) => new FakeEl(tag) };

const scriptOf = (file) =>
  fs.readFileSync(path.join(ROOT, file), 'utf8').match(/<script>\n([\s\S]*?)<\/script>/)[1];

// ============================================================
// 5-prep + 2 + 3. onboard.html — stubbed fetch, then eval
// ============================================================
const snapshotJson = fs.readFileSync(path.join(ROOT, 'data', 'model-apis-snapshot.json'), 'utf8');
globalThis.fetch = async (url) => {
  if (String(url).startsWith('/api/baseten?host=inference&path=models')) {
    return new Response('{"error":"upstream unreachable"}', { status: 502 });
  }
  if (url === '/data/model-apis-snapshot.json') {
    return new Response(snapshotJson, { status: 200 });
  }
  return new Response('{"error":"not stubbed"}', { status: 404 });
};

(0, eval)(scriptOf('onboard.html'));
const ob = globalThis.__onboard;
check('onboard script evaluated against the stub DOM', !!ob);

// ---- 2. crossover JS === crossover.py self-test vectors ----
{
  // Vector straight from scripts/crossover.py --self-test:
  //   0.01 $/min, 100 h, prompt/completion 1.0/1.0 $/Mtok, ratio 3
  //   → blended 1.0, floor 60, break-even 60,000,000 (same tolerances as py)
  const r = ob.crossoverCompute({
    instance_usd_per_min: 0.01, utilization_hours_per_month: 100,
    model_api_usd_per_mtok_prompt: 1.0, model_api_usd_per_mtok_completion: 1.0,
    prompt_completion_ratio: 3.0,
  });
  check('crossover JS blended matches py self-test (1.0 ± 1e-9)',
    Math.abs(r.blended_usd_per_mtok - 1.0) < 1e-9, String(r.blended_usd_per_mtok));
  check('crossover JS floor matches py self-test (60)',
    Math.abs(r.dedicated_floor_usd_per_month - 60) < 1e-9);
  check('crossover JS break-even matches py self-test (60,000,000 ± 1e-3)',
    Math.abs(r.break_even_tokens_per_month - 60_000_000) < 1e-3,
    String(r.break_even_tokens_per_month));
  // and the ratio default (omitted → 3.0), mirroring compute() in py
  const rd = ob.crossoverCompute({
    instance_usd_per_min: 0.01, utilization_hours_per_month: 100,
    model_api_usd_per_mtok_prompt: 1.0, model_api_usd_per_mtok_completion: 1.0,
  });
  check('crossover JS defaults ratio to 3.0 like crossover.py',
    Math.abs(rd.break_even_tokens_per_month - 60_000_000) < 1e-3);
  // prove the py script itself still holds the vector (guards drift)
  const py = spawnSync('python3',
    [path.join(REPO, 'skills', 'baseten-onboard', 'scripts', 'crossover.py'), '--self-test'],
    { encoding: 'utf8' });
  check('scripts/crossover.py --self-test still passes (vector parity source)',
    py.status === 0 && /self-test OK/.test(py.stdout), py.stdout || py.stderr);
}

// ---- 3. generated-prompt snapshot: fixed inputs → exact text ----
{
  const prompt = ob.buildPrompt({
    iso: '2026-07-05T12:00:00.000Z', model: 'openai/gpt-oss-120b',
    customWeights: false, tier: 'interactive', tokensPerMonth: 30000000,
    ratio: 3, sku: 'T4x8x32', budget: 50, session: 1,
  });
  const expected = `Use the baseten-onboard skill to onboard me to a dedicated Baseten deployment.
My choices (from baseten-reliability-console.vercel.app/onboard.html, 2026-07-05T12:00:00.000Z):
- model: openai/gpt-oss-120b  (custom weights: no)
- latency tier: interactive
- expected volume: 30,000,000 tokens/month (prompt:completion ratio 3.0)
- hardware: T4x8x32 preferred; fall back down the proven ladder if org-gated
- monthly budget ceiling: $50; session spend ceiling: $1
Re-fetch all prices live before quoting; nothing that bills without my yes.
When the endpoint is verified, give me the console deep link
(https://baseten-reliability-console.vercel.app/?model=<model_id>).`;
  check('generated prompt matches the exact template snapshot', prompt === expected,
    prompt === expected ? '' : JSON.stringify(prompt));
  const cmd = ob.buildCodeCommand(prompt);
  check('Claude Code tab wraps in single quotes (\'$\' inert in POSIX sh)',
    cmd.startsWith("claude 'npx skills add vsiwach/baseten-mvp -y && Use the baseten-onboard skill") &&
    cmd.endsWith("'") && cmd.includes('$50'));
  check('embedded single quotes are shell-escaped',
    ob.buildCodeCommand("don't") === `claude 'npx skills add vsiwach/baseten-mvp -y && don'\\''t'`);
}

// ---- 5. snapshot-fallback banner path ----
{
  const p = ob.loadCatalog();          // no key yet → key panel appears
  await sleep(20);
  check('lazy key request: key panel revealed by the fetch button path',
    $('keyRow').hidden === false);
  $('keyInput').value = FAKE_KEY;
  $('keyForm').listeners.submit({ preventDefault() {} });
  await p;
  const banner = $('catalogBanner');
  check('snapshot fallback banner visible after live 502', banner.hidden === false);
  check('banner cites the snapshot fetched_at and the live error',
    banner.textContent === 'snapshot from 2026-07-02T19:11:03Z — refresh via the ' +
    'baseten-onboard skill; live fetch failed: HTTP 502 — upstream unreachable',
    JSON.stringify(banner.textContent));
  const cat = ob.getCatalog();
  check('catalog switched to snapshot source (all-or-nothing per table)',
    cat.source === 'snapshot' && cat.rows.length > 0);
  check('table footnote cites the snapshot file, never the live proxy call',
    $('catalogWrap').innerHTML.includes('data/model-apis-snapshot.json') &&
    !$('catalogWrap').innerHTML.includes('via this proxy'));
}

// ============================================================
// 4. planner contract — eval index.html, two fixtures
// ============================================================
(0, eval)(scriptOf('index.html'));
const planner = globalThis.__planner;
check('index.html exposes __planner {buildPlannerModel, renderPlanner}',
  !!planner && typeof planner.buildPlannerModel === 'function' &&
  typeof planner.renderPlanner === 'function');

{
  // fixture 1: measured-comparison artifact BUILT by buildPlannerModel
  const fleetFixture = [{
    model: { id: 'm1', name: 'demo' },
    prod: { id: 'd1', instance_type_name: 'T4x8x32',
      autoscaling_settings: { min_replica: 1, max_replica: 2 } },
    metrics: { summary: { latency: { p95: 400, p99: 500 } }, series: { total: 120 } },
  }];
  const prices = {
    data: { instance_types: [{ instance_type: { name: 'T4x8x32' }, price: 0.01504 }] },
    fetchedAt: new Date('2026-07-05T12:00:00Z'),
  };
  const baselines = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'data', 'measured-baselines.json'), 'utf8')).entries;
  const artifact = planner.buildPlannerModel(
    fleetFixture, prices, JSON.parse(snapshotJson), baselines);
  check('builder emits schema placement-recommendation/v1, kind measured-comparison',
    artifact.schema === 'placement-recommendation/v1' &&
    artifact.source.kind === 'measured-comparison');
  const w = artifact.workloads[0];
  check('workload carries observed metrics + interactive-tier verdict',
    w.observed.p99_ms === 500 && w.observed.requests === 120 &&
    w.slo.tier === 'interactive' && w.slo.verdict === 'GREEN');
  check('recommendation status is pending-rl-artifact',
    w.recommendation.status === 'pending-rl-artifact' && w.recommendation.placement === null);
  // dedicated: 0.01504 × 60 × 730 × 1 = 658.752; model-api: 120 req/1h → 87600
  // req/mo × (750×0.1 + 250×0.5)/1e6 = 17.52 (cheapest snapshot fit gpt-oss-120b)
  const [ded, api] = w.options;
  check('dedicated $/mo = live price × 60 × 730 × 1 replica',
    Math.abs(ded.usd_per_month - 658.752) < 1e-6, String(ded.usd_per_month));
  check('model-api $/mo from cheapest snapshot fit at observed volume',
    api.placement === 'model-api openai/gpt-oss-120b' &&
    Math.abs(api.usd_per_month - 17.52) < 1e-6, String(api.usd_per_month));
  check('dedicated latency evidence cites the measured baselines file',
    JSON.stringify(ded.latency_expected_ms) === '{"warm_ttft":[300,333],"cold_start_s":148.2}' &&
    ded.evidence.some((e) => e.includes('PHASE1_EVIDENCE.md, 2026-07-04')));

  planner.renderPlanner(artifact);
  let html = $('plannerBody').innerHTML;
  check('renderPlanner(measured-comparison): pending slot text rendered',
    html.includes('placement optimizer (RL) is a pending feature'));
  check('renderPlanner: snapshot prices labeled SNAPSHOT with date',
    html.includes('SNAPSHOT 2026-07-02T19:11:03Z'));
  check('renderPlanner: dedicated + model-api options with $/mo',
    html.includes('dedicated T4x8x32') && html.includes('$659/mo') && html.includes('$17.52/mo'));

  // fixture 2: synthetic rl-policy artifact — same contract, filled reco.
  // Zero rework: the renderer never saw this kind before.
  planner.renderPlanner({
    schema: 'placement-recommendation/v1',
    generated_at: '2026-07-05T00:00:00Z',
    source: { kind: 'rl-policy', policy_id: 'ppo-v3' },
    workloads: [{
      model_id: 'm1', deployment_id: 'd1',
      observed: { p95_ms: 410, p99_ms: 520, requests: 1200, window_hours: 24 },
      slo: { tier: 'interactive', budget_ms: 800, verdict: 'GREEN' },
      options: [{ placement: 'dedicated T4x8x32', usd_per_month: 658.75,
        latency_expected_ms: { warm_ttft: [300, 333] }, evidence: ['rl eval run #42'] }],
      recommendation: { placement: 'dedicated T4x8x32', confidence: 0.87,
        rationale: 'utilization 71% sustained; API rate limits binding', status: 'ready' },
    }],
  });
  html = $('plannerBody').innerHTML;
  check('renderPlanner(rl-policy): filled recommendation renders with zero rework',
    html.includes('confidence 0.87') && html.includes('utilization 71% sustained') &&
    html.includes('rl-policy') && !html.includes('pending feature'));
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} assertions passed`);
process.exit(failed ? 1 : 0);
