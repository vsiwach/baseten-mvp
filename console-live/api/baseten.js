// api/baseten.js — read-only proxy to the Baseten APIs.
// Vercel Node serverless handler, stdlib only. Forwards a closed allowlist
// of GET paths to a closed map of upstream hosts. The API key travels in a
// header and is never logged, stored, echoed, or placed in a query string.
//
// Hosts (selected by optional ?host=, default 'mgmt' — existing callers that
// send no host param behave exactly as before):
//   mgmt      → api.baseten.co/v1        (Authorization: Api-Key <key>)
//   inference → inference.baseten.co/v1  (Authorization: Bearer <key>)
'use strict';

const https = require('https');

const TIMEOUT_MS = 10000;
const KEY_RE = /^[A-Za-z0-9._-]{10,200}$/;
const UPSTREAMS = {
  mgmt: {
    base: 'https://api.baseten.co/v1/',
    scheme: 'Api-Key',
    allow: [
      /^models$/,
      /^models\/[A-Za-z0-9_-]+\/deployments$/,
      /^models\/[A-Za-z0-9_-]+\/deployments\/[A-Za-z0-9_-]+\/metrics$/,
      /^instance_type_prices$/,
    ],
  },
  inference: {
    base: 'https://inference.baseten.co/v1/',
    scheme: 'Bearer',
    allow: [/^models$/],
  },
};
const PASS_PARAMS = ['mode', 'start_epoch_millis', 'end_epoch_millis'];

function sendJson(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(body));
}

module.exports = (req, res) => {
  const q = req.query || {};
  const path = typeof q.path === 'string' ? q.path : '';
  const hostName = q.host === undefined ? 'mgmt' : q.host;
  // hasOwnProperty guard: '__proto__'/'constructor' must not resolve a host.
  const up = typeof hostName === 'string' &&
    Object.prototype.hasOwnProperty.call(UPSTREAMS, hostName)
    ? UPSTREAMS[hostName] : null;
  const allowlisted = !!up && up.allow.some((re) => re.test(path));
  // Log lines stay byte-identical for the default host; prefixed otherwise.
  const logTarget = hostName === 'mgmt' ? path : `${String(hostName)}:${path}`;
  const logPath = allowlisted ? logTarget : '(rejected)';
  const reject = (status, error) => {
    console.log(`${req.method} ${logPath} -> ${status}`);
    sendJson(res, status, { error });
  };

  if (req.method !== 'GET') return reject(405, 'method not allowed');
  const key = req.headers['x-baseten-api-key'];
  if (typeof key !== 'string' || !KEY_RE.test(key)) {
    return reject(400, 'missing or malformed x-baseten-api-key header');
  }
  if (!up) return reject(400, 'unknown host');
  if (!allowlisted) return reject(403, 'path not allowlisted');

  const upstream = new URL(up.base + path);
  if (hostName === 'mgmt') {
    for (const name of PASS_PARAMS) {
      if (typeof q[name] === 'string') upstream.searchParams.set(name, q[name]);
    }
    if (path.endsWith('/metrics') && q.metrics !== undefined) {
      for (const m of [].concat(q.metrics)) {
        upstream.searchParams.append('metrics', String(m));
      }
    }
  }

  const upReq = https.request(
    upstream,
    { method: 'GET', headers: { Authorization: `${up.scheme} ${key}`, Accept: 'application/json' } },
    (upRes) => {
      let body = '';
      let done = false;
      upRes.setEncoding('utf8');
      upRes.on('data', (chunk) => { body += chunk; });
      upRes.on('end', () => {
        done = true;
        console.log(`GET ${logTarget} -> ${upRes.statusCode}`);
        res.statusCode = upRes.statusCode;
        res.setHeader('Content-Type', upRes.headers['content-type'] || 'application/json');
        if (upRes.headers['retry-after']) res.setHeader('Retry-After', upRes.headers['retry-after']);
        res.end(body);
      });
      // Some upstreams abort error-response bodies without a proper end
      // (observed on inference.baseten.co 403s) — without this the
      // serverless function hangs until the platform kills it.
      upRes.on('close', () => {
        if (done || res.headersSent) return;
        console.log(`GET ${logTarget} -> 502 (upstream closed mid-response)`);
        sendJson(res, 502, { error: 'upstream closed mid-response' });
      });
    }
  );
  upReq.setTimeout(TIMEOUT_MS, () => upReq.destroy(new Error('upstream timeout')));
  upReq.on('error', (err) => {
    if (res.headersSent) return;
    const timedOut = /timeout/i.test(err.message);
    console.log(`GET ${logTarget} -> ${timedOut ? 504 : 502}`);
    sendJson(res, timedOut ? 504 : 502, { error: timedOut ? 'upstream timeout' : 'upstream unreachable' });
  });
  upReq.end();
};
