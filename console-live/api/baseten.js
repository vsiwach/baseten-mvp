// api/baseten.js — read-only proxy to the Baseten management API.
// Vercel Node serverless handler, stdlib only. Forwards a closed allowlist
// of GET paths. The API key travels in a header and is never logged,
// stored, echoed, or placed in a query string.
'use strict';

const https = require('https');

const UPSTREAM_BASE = 'https://api.baseten.co/v1/';
const TIMEOUT_MS = 10000;
const KEY_RE = /^[A-Za-z0-9._-]{10,200}$/;
const PATH_ALLOWLIST = [
  /^models$/,
  /^models\/[A-Za-z0-9_-]+\/deployments$/,
  /^models\/[A-Za-z0-9_-]+\/deployments\/[A-Za-z0-9_-]+\/metrics$/,
];
const PASS_PARAMS = ['mode', 'start_epoch_millis', 'end_epoch_millis'];

function sendJson(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(body));
}

module.exports = (req, res) => {
  const q = req.query || {};
  const path = typeof q.path === 'string' ? q.path : '';
  const allowlisted = PATH_ALLOWLIST.some((re) => re.test(path));
  const logPath = allowlisted ? path : '(rejected)';
  const reject = (status, error) => {
    console.log(`${req.method} ${logPath} -> ${status}`);
    sendJson(res, status, { error });
  };

  if (req.method !== 'GET') return reject(405, 'method not allowed');
  const key = req.headers['x-baseten-api-key'];
  if (typeof key !== 'string' || !KEY_RE.test(key)) {
    return reject(400, 'missing or malformed x-baseten-api-key header');
  }
  if (!allowlisted) return reject(403, 'path not allowlisted');

  const upstream = new URL(UPSTREAM_BASE + path);
  for (const name of PASS_PARAMS) {
    if (typeof q[name] === 'string') upstream.searchParams.set(name, q[name]);
  }
  if (path.endsWith('/metrics') && q.metrics !== undefined) {
    for (const m of [].concat(q.metrics)) {
      upstream.searchParams.append('metrics', String(m));
    }
  }

  const upReq = https.request(
    upstream,
    { method: 'GET', headers: { Authorization: `Api-Key ${key}`, Accept: 'application/json' } },
    (upRes) => {
      let body = '';
      upRes.setEncoding('utf8');
      upRes.on('data', (chunk) => { body += chunk; });
      upRes.on('end', () => {
        console.log(`GET ${path} -> ${upRes.statusCode}`);
        res.statusCode = upRes.statusCode;
        res.setHeader('Content-Type', upRes.headers['content-type'] || 'application/json');
        if (upRes.headers['retry-after']) res.setHeader('Retry-After', upRes.headers['retry-after']);
        res.end(body);
      });
    }
  );
  upReq.setTimeout(TIMEOUT_MS, () => upReq.destroy(new Error('upstream timeout')));
  upReq.on('error', (err) => {
    if (res.headersSent) return;
    const timedOut = /timeout/i.test(err.message);
    console.log(`GET ${path} -> ${timedOut ? 504 : 502}`);
    sendJson(res, timedOut ? 504 : 502, { error: timedOut ? 'upstream timeout' : 'upstream unreachable' });
  });
  upReq.end();
};
