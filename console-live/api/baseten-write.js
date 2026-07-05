// api/baseten-write.js — gated write proxy to the Baseten management API.
// Vercel Node serverless handler, stdlib only. POST-only, closed allowlist of
// four mutations (activate / deactivate / promote / autoscaling), executed
// with the caller's own key. The key travels in a header and is never
// logged, stored, or echoed. Writes are UI-gated: the request must carry an
// x-confirm-mutation header that equals the exact upstream mutation string
// shown in the confirm dialog — the server recomputes and compares, so a
// request that skipped the dialog's preview cannot claim to be confirmed.
'use strict';

const https = require('https');

const UPSTREAM_BASE = 'https://api.baseten.co/v1';
const TIMEOUT_MS = 30000;
const KEY_RE = /^[A-Za-z0-9._-]{10,200}$/;
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const AUTOSCALING_FIELDS = new Set([
  'min_replica', 'max_replica', 'autoscaling_window',
  'concurrency_target', 'scale_down_delay',
]);
const ACTIONS = {
  activate: { method: 'POST', suffix: 'activate' },
  deactivate: { method: 'POST', suffix: 'deactivate' },
  promote: { method: 'POST', suffix: 'promote' },
  autoscaling: { method: 'PATCH', suffix: 'autoscaling_settings' },
};

function sendJson(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(body));
}

function readBody(req) {
  // Vercel parses JSON bodies into req.body; the local runner passes a
  // pre-parsed object the same way. Fall back to raw string parse.
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body === 'string' && req.body) {
    try { return JSON.parse(req.body); } catch { return null; }
  }
  return null;
}

module.exports = (req, res) => {
  const reject = (status, error, label) => {
    console.log(`WRITE ${label || '(rejected)'} -> ${status}`);
    sendJson(res, status, { error });
  };

  if (req.method !== 'POST') return reject(405, 'method not allowed');
  const key = req.headers['x-baseten-api-key'];
  if (typeof key !== 'string' || !KEY_RE.test(key)) {
    return reject(400, 'missing or malformed x-baseten-api-key header');
  }

  const body = readBody(req);
  if (!body) return reject(400, 'JSON body required');
  const { action, model_id: modelId, deployment_id: deploymentId } = body;
  const spec = ACTIONS[action];
  if (!spec) return reject(403, 'action not allowlisted');
  if (typeof modelId !== 'string' || !ID_RE.test(modelId) ||
      typeof deploymentId !== 'string' || !ID_RE.test(deploymentId)) {
    return reject(400, 'malformed model_id or deployment_id');
  }

  let payload = {};
  if (action === 'autoscaling') {
    const raw = body.payload;
    if (!raw || typeof raw !== 'object' || Array.isArray(raw) ||
        Object.keys(raw).length === 0) {
      return reject(400, 'autoscaling requires a non-empty payload');
    }
    for (const [k, v] of Object.entries(raw)) {
      if (!AUTOSCALING_FIELDS.has(k)) return reject(403, `field not allowlisted: ${k}`);
      if (typeof v !== 'number' || !Number.isFinite(v) || v < 0 || v > 100000) {
        return reject(400, `field must be a finite non-negative number: ${k}`);
      }
    }
    payload = raw;
  } else if (body.payload !== undefined &&
             Object.keys(body.payload || {}).length > 0) {
    return reject(400, `${action} takes no payload`);
  }

  const upstreamPath =
    `/models/${modelId}/deployments/${deploymentId}/${spec.suffix}`;
  // The confirm proof: the dialog shows exactly this string; the client
  // echoes it back. Mismatch means the user never saw this mutation.
  const mutation = `${spec.method} ${upstreamPath}` +
    (action === 'autoscaling' ? ` ${JSON.stringify(payload)}` : '');
  if (req.headers['x-confirm-mutation'] !== mutation) {
    return reject(428, 'confirm header does not match the exact mutation');
  }

  const label = `${action} ${modelId}/${deploymentId}`;
  const data = Buffer.from(JSON.stringify(payload));
  const upReq = https.request(
    UPSTREAM_BASE + upstreamPath,
    {
      method: spec.method,
      headers: {
        Authorization: `Api-Key ${key}`,
        'Content-Type': 'application/json',
        'Content-Length': data.length,
        Accept: 'application/json',
      },
    },
    (upRes) => {
      let out = '';
      upRes.setEncoding('utf8');
      upRes.on('data', (chunk) => { out += chunk; });
      upRes.on('end', () => {
        console.log(`WRITE ${label} -> ${upRes.statusCode}`);
        res.statusCode = upRes.statusCode;
        res.setHeader('Content-Type', upRes.headers['content-type'] || 'application/json');
        if (upRes.headers['retry-after']) res.setHeader('Retry-After', upRes.headers['retry-after']);
        res.end(out);
      });
    }
  );
  upReq.setTimeout(TIMEOUT_MS, () => upReq.destroy(new Error('upstream timeout')));
  upReq.on('error', (err) => {
    if (res.headersSent) return;
    const timedOut = /timeout/i.test(err.message);
    console.log(`WRITE ${label} -> ${timedOut ? 504 : 502}`);
    sendJson(res, timedOut ? 504 : 502, { error: timedOut ? 'upstream timeout' : 'upstream unreachable' });
  });
  upReq.end(data);
};
