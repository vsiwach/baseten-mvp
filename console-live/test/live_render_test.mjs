// live_render_test.mjs — runs the real console-live inline JS against the
// live proxy on :4173 with a stub DOM, then asserts on rendered card text.
// The API key comes from process.env.BASETEN_API_KEY and is never printed;
// all output is scrubbed against it as a second line of defense.
import fs from 'node:fs';

const KEY = process.env.BASETEN_API_KEY;
if (!KEY) { console.error('BASETEN_API_KEY not set in env'); process.exit(1); }

// ---- output scrubbing: nothing key-like ever reaches stdout ----
const rawLog = console.log.bind(console);
const scrub = (s) => String(s).split(KEY).join('[key-redacted]');
console.log = (...args) => rawLog(...args.map(scrub));

// ---- minimal DOM stub ----
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
  appendChild(c) { this.children.push(c); return c; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  focus() {}
}
const registry = new Map();
const $ = (id) => { if (!registry.has(id)) registry.set(id, new FakeEl()); return registry.get(id); };
globalThis.document = { getElementById: $, createElement: (tag) => new FakeEl(tag) };

// ---- fetch shim: page uses relative URLs; Node fetch needs absolute ----
const realFetch = globalThis.fetch;
// Target host: CONSOLE_URL env overrides (e.g. the deployed Vercel URL);
// defaults to the local runner.
const BASE = process.env.CONSOLE_URL || 'http://localhost:4173';
globalThis.fetch = (url, opts) => realFetch(BASE + url, opts);

// ---- load and run the real page script ----
const html = fs.readFileSync(
  new URL('../index.html', import.meta.url), 'utf8');
const code = html.match(/<script>\n([\s\S]*?)<\/script>/)[1];
(0, eval)(code);

// ---- helpers ----
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const strip = (h) => h.replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&').replace(/&#39;/g, "'")
  .replace(/\s+/g, ' ').trim();

async function settle(label) {
  const status = $('statusTxt'), connectErr = $('connectErr'), panel = $('connectPanel');
  for (let i = 0; i < 450; i++) { // up to 90s
    if (status.textContent.startsWith('updated')) return true;
    if (!panel.hidden && connectErr.textContent) {
      throw new Error(`${label}: disconnected — ${connectErr.textContent}`);
    }
    // refresh() no-oped (429 pause guard): statusTxt never left ''
    if (i === 10 && status.textContent === '') return false;
    await sleep(200);
  }
  throw new Error(`${label}: timed out waiting for refresh to settle`);
}

// Drive refresh like a patient user: if the page pauses on a 429 or renders
// per-card rate-limit errors, wait out Retry-After and click Refresh again.
async function refreshUntilClean(label, trigger) {
  for (let attempt = 1; attempt <= 8; attempt++) {
    $('statusTxt').textContent = '';
    trigger();
    const ran = await settle(label);
    if (ran) {
      const limited = $('cards').children.some((c) =>
        c.querySelector('.body').innerHTML.includes('rate limited'));
      if (!limited) return;
      console.log(`[${label}] per-card rate limit on attempt ${attempt} — waiting 35s`);
    } else {
      console.log(`[${label}] refresh paused by rate limit on attempt ${attempt} — waiting 35s`);
    }
    await sleep(35000);
    trigger = () => $('refreshBtn').listeners.click();
  }
  throw new Error(`${label}: still rate limited after retries`);
}

function snapshotCards(label) {
  const notice = $('notice');
  console.log(`\n================ ${label} ================`);
  if (!notice.hidden && notice.textContent) console.log(`[notice] ${notice.textContent}`);
  if (!$('empty').hidden) console.log(`[empty-state] ${$('empty').textContent || '(default)'}`);
  const cards = $('cards').children.map((card) => {
    const head = strip(card.innerHTML);
    const body = strip(card.querySelector('.body').innerHTML);
    const foot = strip(card.querySelector('.foot').innerHTML);
    const chips = [...card.querySelector('.body').innerHTML
      .matchAll(/class="chip (chip-[a-z]+)"[^>]*>(?:<span class="dot"><\/span>)?([^<]*)/g)]
      .map((m) => `${m[1]}:${m[2].trim()}`);
    return { head, body, foot, chips };
  });
  cards.forEach((c, i) => {
    console.log(`--- card ${i + 1} ---`);
    console.log(`  head: ${c.head}`);
    console.log(`  body: ${c.body}`);
    console.log(`  chips: ${c.chips.join(' | ') || '(none)'}`);
    console.log(`  foot: ${c.foot}`);
  });
  return cards;
}

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
}

// ---- drive the page exactly as a paste + click would ----
await refreshUntilClean('1h window', () => {
  $('keyInput').value = KEY;
  $('connectForm').listeners.submit({ preventDefault() {} });
});
const cards1h = snapshotCards('DEFAULT 1h WINDOW');

// cool down before the second burst of API calls, then switch to 6h
console.log('\n[cooling down 60s before switching window, to stay under the API rate limit]');
await sleep(60000);
await refreshUntilClean('6h window',
  () => $('windowSel').listeners.change({ target: { value: '6' } }));
const cards6h = snapshotCards('6h WINDOW');

// ---- assertions (6h view) ----
console.log('\n================ ASSERTIONS ================');
const all6h = cards6h.map((c) => c.head + ' ' + c.body).join('\n');
const qwen = cards6h.find((c) => c.head.includes('qwen3-8b-vllm'));

check('qwen3-8b-vllm card exists', !!qwen);
check('no card for non-production deployment q86yjdy', !all6h.includes('q86yjdy'));
if (qwen) {
  check('instance contains T4', /T4/.test(qwen.head), qwen.head.match(/\S*T4\S*/)?.[0] || 'not found');
  check('status INACTIVE', qwen.head.includes('INACTIVE'));

  // Live metrics drift with the rolling window, so assertions are structural:
  // either real numbers render coherently, or the honest no-traffic state does.
  const noTraffic = /No requests in this window \(metrics can lag/.test(qwen.body);
  const nMatch = qwen.body.match(/requests\s+(\d+)/);
  const n = nMatch ? Number(nMatch[1]) : null;
  const p99Match = qwen.body.match(/p99\s+([\d.]+)ms/);
  const p99ms = p99Match ? Number(p99Match[1]) : null;
  check('renders request count or the no-traffic state',
    noTraffic || (n !== null && n >= 0), noTraffic ? 'no-traffic state' : `n=${n}`);
  check('renders numeric p99 or the no-traffic state',
    noTraffic || (p99ms !== null && p99ms > 0),
    noTraffic ? 'no-traffic state' : `p99=${p99ms}ms`);
  if (!noTraffic && n !== null) {
    const flagged = /p99 likely includes cold start \/ low sample \(n=\d+\)/.test(qwen.body);
    check('low-sample annotation present iff n<20 or p99>>p50',
      n >= 20 || flagged, `n=${n}, flagged=${flagged}`);
    const interactive = qwen.chips.find((c) => c.includes('interactive'));
    check('interactive verdict chip renders (AMBER when flagged, never bare RED on flagged data)',
      !!interactive && (!flagged || !interactive.startsWith('chip-bad')),
      interactive ?? 'no interactive chip');
  }
}

// ---- 1h window: report faithfully whichever state rendered ----
const qwen1h = cards1h.find((c) => c.head.includes('qwen3-8b-vllm'));
const noTraffic1h = qwen1h ? /No requests in this window \(metrics can lag/.test(qwen1h.body) : false;
console.log(`\n[1h report] qwen card ${qwen1h ? 'present' : 'ABSENT'}; ` +
  (noTraffic1h ? 'rendered the "no requests in window (metrics can lag 1–3 min)" state.'
               : `rendered metrics/other state: "${qwen1h?.body.slice(0, 160) ?? ''}"`));

const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} assertions passed`);
process.exit(failed ? 1 : 0);
