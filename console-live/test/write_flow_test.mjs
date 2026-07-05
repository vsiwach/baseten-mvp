// write_flow_test.mjs — OFFLINE test of the v2 write flow. Runs the real
// inline JS with a stub DOM and a fully stubbed fetch (fixtures + captured
// writes). Uses a fake key only; no network, no real workspace.
//   node console-live/test/write_flow_test.mjs
import fs from 'node:fs';

const FAKE_KEY = 'dummykey1234';

// ---- minimal DOM stub (same shape as live_render_test.mjs) ----
class FakeEl {
  constructor(tag = 'div') {
    this.tag = tag; this.className = ''; this.children = [];
    this._innerHTML = ''; this.subs = new Map(); this.listeners = {};
    this.hidden = false; this.value = ''; this.textContent = ''; this.checked = false;
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

// ---- fetch stub: GET fixtures, POST captured ----
const FIXTURES = {
  models: { models: [{ id: 'm1', name: 'demo-model' }] },
  'models/m1/deployments': {
    deployments: [
      { id: 'd1', name: 'deployment-1', status: 'INACTIVE', is_production: true,
        active_replica_count: 0, instance_type_name: 'T4x8x32',
        autoscaling_settings: { min_replica: 0, max_replica: 1 } },
      { id: 'd2', name: 'deployment-2', status: 'ACTIVE', is_production: false,
        active_replica_count: 1, instance_type_name: 'T4x8x32',
        autoscaling_settings: { min_replica: 1, max_replica: 2 } },
      { id: 'd3', name: 'deployment-3', status: 'BUILD_FAILED', is_production: false,
        active_replica_count: 0 },
    ],
  },
};
const writes = [];
globalThis.fetch = async (url, opts = {}) => {
  if (url === '/api/baseten-write') {
    writes.push({ url, opts });
    return new Response('{"code": "PERMISSION_DENIED", "message": "Authorization error"}',
      { status: 403, headers: { 'Content-Type': 'application/json' } });
  }
  const path = new URLSearchParams(url.split('?')[1]).get('path');
  const body = FIXTURES[path] ??
    (path.endsWith('/metrics') ? { metric_descriptors: [], metric_values: [] } : null);
  if (!body) return new Response('{"error":"not found"}', { status: 404 });
  return new Response(JSON.stringify(body), { status: 200 });
};

// ---- load and run the real page script ----
const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
(0, eval)(html.match(/<script>\n([\s\S]*?)<\/script>/)[1]);
// the real markup ships <div id="modal" hidden>; mirror that initial state
$('modal').hidden = true;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail = '') {
  results.push(ok);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
}
const clickEvent = (btn) => ({ target: { closest: (sel) => sel === 'button[data-action]' ? btn : null } });

// ---- connect (fake key) and settle ----
$('keyInput').value = FAKE_KEY;
$('connectForm').listeners.submit({ preventDefault() {} });
for (let i = 0; i < 50 && !$('statusTxt').textContent.startsWith('updated'); i++) await sleep(100);
check('refresh settled against fixtures', $('statusTxt').textContent.startsWith('updated'));

const card = $('cards').children[0];
check('production card rendered with manage controls', !!card &&
  card.innerHTML.includes('data-action="activate"') && card.innerHTML.includes('data-dep="d1"'));
check('other deployments list: d2 row with Promote', card.innerHTML.includes('data-action="promote"')
  && card.innerHTML.includes('data-dep="d2"'));
check('failed row d3: note, no activate/promote buttons',
  card.innerHTML.includes('fix the failed build first') &&
  !card.innerHTML.includes('data-dep="d3"'));
check('write footnote line present', card.innerHTML.includes(
  'writes · POST /api/baseten-write → api.baseten.co (your key, this browser only)'));

// ---- writes OFF: click must be a no-op ----
const activateBtn = { dataset: { action: 'activate', model: 'm1', dep: 'd1' },
  disabled: false, closest: () => null };
$('cards').listeners.click(clickEvent(activateBtn));
check('manage click ignored while writes are OFF', $('modal').hidden === true);

// ---- toggle writes on ----
$('writesChk').listeners.change({ target: { checked: true } });
check('mode chip flips to amber WRITES ENABLED', $('modeChip').className === 'chip chip-warn' &&
  $('modeChip').innerHTML.includes('WRITES ENABLED — actions mutate your workspace'));
check('banner switches to write-mode text', $('modeBanner').innerHTML.includes(
  'every mutation requires an explicit confirm showing the exact API call'));
check('cards container gains writes-on class', $('cards').className === 'grid writes-on');

// ---- activate flow: modal content ----
$('cards').listeners.click(clickEvent(activateBtn));
const MUT = 'POST /models/m1/deployments/d1/activate';
check('modal opens on Activate', $('modal').hidden === false);
check('modal shows the exact mutation string', $('modalMutation').textContent === MUT,
  JSON.stringify($('modalMutation').textContent));
check('modal shows the activate consequence line', $('modalConsequence').textContent ===
  'Starts billing while replicas are active (T4 ≈ $0.90/hr each). Cold start typically 2–6 min before READY.');

// ---- confirm: request headers/body + 403 surfaced verbatim ----
await $('modalConfirm').listeners.click();
check('exactly one write request fired', writes.length === 1);
const w = writes[0];
check('x-confirm-mutation header equals the displayed string',
  w.opts.headers['x-confirm-mutation'] === MUT);
check('x-baseten-api-key header carries the in-memory key',
  w.opts.headers['x-baseten-api-key'] === FAKE_KEY);
check('POST body matches {action, model_id, deployment_id}',
  w.opts.method === 'POST' && w.opts.body ===
  JSON.stringify({ action: 'activate', model_id: 'm1', deployment_id: 'd1' }));
check('403 rendered verbatim in the modal, modal stays open',
  $('modal').hidden === false && $('modalError').hidden === false &&
  $('modalError').textContent ===
  'HTTP 403: {"code": "PERMISSION_DENIED", "message": "Authorization error"}',
  JSON.stringify($('modalError').textContent));
$('modalCancel').listeners.click();
check('cancel closes the modal', $('modal').hidden === true);

// ---- autoscaling flow: changed fields only, payload in mutation string ----
const manageBox = new FakeEl();
manageBox.querySelector('.min-inp').value = '1';   // changed (was 0)
manageBox.querySelector('.max-inp').value = '1';   // unchanged
const autoBtn = { dataset: { action: 'autoscaling', model: 'm1', dep: 'd1', min: '0', max: '1' },
  disabled: false, closest: (sel) => sel === '.manage' ? manageBox : null };
$('cards').listeners.click(clickEvent(autoBtn));
check('autoscaling mutation string includes only changed fields',
  $('modalMutation').textContent ===
  'PATCH /models/m1/deployments/d1/autoscaling_settings {"min_replica":1}',
  JSON.stringify($('modalMutation').textContent));
check('autoscaling consequence cites old→new', $('modalConsequence').textContent.includes(
  'Applies min_replica 0→1;'));
$('modalCancel').listeners.click();

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} assertions passed`);
process.exit(failed ? 1 : 0);
