"""Gated Baseten management writes — the ONLY path from the console to the
Baseten management API (api.baseten.co).

Defense in depth, per the approved Phase C design:
  1. Master gate: every /v1/writes/* request 403s unless the env var
     CONSOLE_ALLOW_WRITES == "1" — checked per request, so unsetting it
     closes the gate on a running router.
  2. CLOSED allowlist of 4 ops (autoscaling, activate, deactivate, promote);
     the op templates below are the only Baseten paths constructible, and
     ids must match ^[A-Za-z0-9_-]{1,64}$.
  3. Two-step confirm token: HMAC-SHA256 over (op, ids, body hash, ts) with
     a per-process os.urandom secret; 120 s TTL; single use. The console
     must fetch a token for the EXACT mutation it previews — any body
     tamper, replay, or stale confirm fails closed.
  4. Transport is injectable (module seam `transport`) — tests use fakes;
     the default reads BASETEN_API_KEY from env INSIDE the call and never
     logs or returns it.
"""

import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.request

API_BASE = "https://api.baseten.co/v1"
TOKEN_TTL_S = 120
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SECRET = os.urandom(32)        # in-memory; tokens die with the process
_used_tokens: set[str] = set()

AUTOSCALING_KEYS = {"min_replica", "max_replica", "autoscaling_window",
                    "concurrency_target", "scale_down_delay"}

# op -> (HTTP method, path template). This dict IS the allowlist.
OPS = {
    "autoscaling": ("PATCH",
                    "/models/{m}/deployments/{d}/autoscaling_settings"),
    "activate": ("POST", "/models/{m}/deployments/{d}/activate"),
    "deactivate": ("POST", "/models/{m}/deployments/{d}/deactivate"),
    "promote": ("POST", "/models/{m}/deployments/{d}/promote"),
}


def gate_open() -> bool:
    return os.environ.get("CONSOLE_ALLOW_WRITES") == "1"


def canonical_body(body: dict | None) -> str:
    """One canonical serialization on both sides of the token handshake
    (the console mirrors this: sorted keys, no whitespace)."""
    return json.dumps(body or {}, sort_keys=True, separators=(",", ":"))


def body_sha256(body: dict | None) -> str:
    return hashlib.sha256(canonical_body(body).encode()).hexdigest()


def mint(op: str, model_id: str, deployment_id: str, body_hash: str,
         ts: int) -> str:
    msg = f"{op}|{model_id}|{deployment_id}|{body_hash}|{ts}"
    return hmac.new(_SECRET, msg.encode(), hashlib.sha256).hexdigest()


def validate_target(op: str, model_id: str, deployment_id: str) -> str | None:
    """Allowlist + id-shape check. Returns an error string or None."""
    if op not in OPS:
        return f"op '{op}' not in allowlist {sorted(OPS)}"
    if not (_ID_RE.match(model_id or "")
            and _ID_RE.match(deployment_id or "")):
        return "model_id/deployment_id must match ^[A-Za-z0-9_-]{1,64}$"
    return None


def validate_body(op: str, body: dict | None) -> str | None:
    if op == "autoscaling":
        if not isinstance(body, dict) or not body:
            return "autoscaling needs a non-empty settings body"
        extra = set(body) - AUTOSCALING_KEYS
        if extra:
            return f"body keys not allowed: {sorted(extra)}"
        bad = [k for k, v in body.items()
               if isinstance(v, bool) or not isinstance(v, (int, float))]
        if bad:
            return f"non-numeric values for: {sorted(bad)}"
    elif body:
        return f"op '{op}' takes an empty body"
    return None


def check_token(token, ts, op: str, model_id: str, deployment_id: str,
                body: dict | None, now: float | None = None) -> str | None:
    """Verify the confirm token for the EXACT mutation. Constant-time
    compare; TTL; single use. Returns an error string or None."""
    now = time.time() if now is None else now
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return "ts must be the integer issued with the token"
    if now - ts > TOKEN_TTL_S:
        return f"token expired ({TOKEN_TTL_S}s TTL) — re-confirm the mutation"
    expected = mint(op, model_id, deployment_id, body_sha256(body), ts)
    if not hmac.compare_digest(str(token or ""), expected):
        return "token does not match this op/ids/body/ts"
    if token in _used_tokens:
        return "token already used — re-confirm the mutation"
    _used_tokens.add(token)
    return None


def urllib_transport(method: str, path: str, body: dict | None):
    """Default transport. The key is read inside the call, sent only as the
    Authorization header, and never logged or returned."""
    key = os.environ.get("BASETEN_API_KEY", "")
    req = urllib.request.Request(
        API_BASE + path,
        data=json.dumps(body).encode() if body else b"{}",
        headers={"Authorization": f"Api-Key {key}",
                 "Content-Type": "application/json"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="replace")[:500]}


transport = urllib_transport    # module seam — tests inject a fake


def execute(op: str, model_id: str, deployment_id: str, body: dict | None):
    """Perform an allowlisted, token-verified op. Returns
    (upstream_status, upstream_body, method, path)."""
    method, tmpl = OPS[op]
    path = tmpl.format(m=model_id, d=deployment_id)
    send = body if op == "autoscaling" else {}
    status, payload = transport(method, path, send)
    return status, payload, method, path
