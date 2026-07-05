"""Gated Baseten writes (/v1/writes/*): off-by-default 403; two-step confirm
token bound to the exact mutation; closed 4-op allowlist; tamper/expiry/reuse
rejection; injectable transport (no network, no keys, per CLAUDE.md rule 4)."""

import pytest

from router_app import writes as writes_mod


@pytest.fixture()
def fake_transport(monkeypatch):
    """Records every upstream call; never touches the network."""
    calls = []

    def transport(method, path, body):
        calls.append({"method": method, "path": path, "body": body})
        return 200, {"ok": True}

    monkeypatch.setattr(writes_mod, "transport", transport)
    return calls


def _token(client, op, model_id="3ydn1e43", deployment_id="qvm1v4e",
           body=None):
    return client.get(
        "/v1/writes/token", params={
            "op": op, "model_id": model_id, "deployment_id": deployment_id,
            "body_sha256": writes_mod.body_sha256(body)})


def _write(client, op, body=None, token=None, ts=None,
           model_id="3ydn1e43", deployment_id="qvm1v4e"):
    return client.post("/v1/writes/baseten", json={
        "op": op, "model_id": model_id, "deployment_id": deployment_id,
        "body": body or {}, "token": token, "ts": ts})


# ---- gate --------------------------------------------------------------

def test_gate_off_denies_token_and_write(router_client, monkeypatch):
    monkeypatch.delenv("CONSOLE_ALLOW_WRITES", raising=False)
    r = _token(router_client, "autoscaling", body={"max_replica": 3})
    assert r.status_code == 403
    assert r.json() == {"error": "writes disabled"}
    r = _write(router_client, "autoscaling", body={"max_replica": 3},
               token="x", ts=0)
    assert r.status_code == 403
    assert r.json() == {"error": "writes disabled"}


# ---- happy path ---------------------------------------------------------

def test_token_roundtrip_hits_transport_with_exact_call(
        router_client, monkeypatch, fake_transport):
    monkeypatch.setenv("CONSOLE_ALLOW_WRITES", "1")
    body = {"max_replica": 3}
    tok = _token(router_client, "autoscaling", body=body).json()
    assert tok["ttl_s"] == 120
    r = _write(router_client, "autoscaling", body=body,
               token=tok["token"], ts=tok["ts"])
    assert r.status_code == 200
    assert r.json() == {"upstream_status": 200, "body": {"ok": True}}
    assert fake_transport == [{
        "method": "PATCH",
        "path": "/models/3ydn1e43/deployments/qvm1v4e/autoscaling_settings",
        "body": {"max_replica": 3}}]
    kinds = router_client.state.events.kinds()
    assert kinds.get("baseten_write_requested") == 1
    assert kinds.get("baseten_write_executed") == 1


def test_promote_sends_empty_body(router_client, monkeypatch, fake_transport):
    monkeypatch.setenv("CONSOLE_ALLOW_WRITES", "1")
    tok = _token(router_client, "promote").json()
    r = _write(router_client, "promote", token=tok["token"], ts=tok["ts"])
    assert r.status_code == 200
    assert fake_transport[-1]["method"] == "POST"
    assert fake_transport[-1]["path"] == \
        "/models/3ydn1e43/deployments/qvm1v4e/promote"


# ---- allowlist ----------------------------------------------------------

def test_fifth_op_rejected(router_client, monkeypatch, fake_transport):
    monkeypatch.setenv("CONSOLE_ALLOW_WRITES", "1")
    assert _token(router_client, "logs").status_code == 403
    r = _write(router_client, "logs", token="x", ts=0)
    assert r.status_code == 403
    assert "allowlist" in r.json()["error"]
    assert fake_transport == []


def test_bad_ids_and_bad_body_keys_rejected(router_client, monkeypatch,
                                            fake_transport):
    monkeypatch.setenv("CONSOLE_ALLOW_WRITES", "1")
    r = _write(router_client, "autoscaling", body={"max_replica": 3},
               token="x", ts=0, model_id="../evil")
    assert r.status_code == 403
    tok = _token(router_client, "autoscaling",
                 body={"replicas": 9}).json()
    r = _write(router_client, "autoscaling", body={"replicas": 9},
               token=tok["token"], ts=tok["ts"])
    assert r.status_code == 403
    assert "not allowed" in r.json()["error"]
    r = _write(router_client, "autoscaling", body={"max_replica": "three"},
               token="x", ts=0)
    assert r.status_code == 403
    assert fake_transport == []


# ---- token binding -------------------------------------------------------

def test_body_tamper_rejected(router_client, monkeypatch, fake_transport):
    monkeypatch.setenv("CONSOLE_ALLOW_WRITES", "1")
    tok = _token(router_client, "autoscaling",
                 body={"max_replica": 3}).json()
    r = _write(router_client, "autoscaling", body={"max_replica": 30},
               token=tok["token"], ts=tok["ts"])
    assert r.status_code == 403
    assert "token" in r.json()["error"]
    assert fake_transport == []
    assert router_client.state.events.kinds().get(
        "baseten_write_denied", 0) >= 1


def test_expired_ts_rejected(router_client, monkeypatch, fake_transport):
    monkeypatch.setenv("CONSOLE_ALLOW_WRITES", "1")
    import time
    old_ts = int(time.time()) - 121
    token = writes_mod.mint("promote", "3ydn1e43", "qvm1v4e",
                            writes_mod.body_sha256({}), old_ts)
    r = _write(router_client, "promote", token=token, ts=old_ts)
    assert r.status_code == 403
    assert "expired" in r.json()["error"]
    assert fake_transport == []


def test_token_reuse_rejected(router_client, monkeypatch, fake_transport):
    monkeypatch.setenv("CONSOLE_ALLOW_WRITES", "1")
    tok = _token(router_client, "activate").json()
    assert _write(router_client, "activate", token=tok["token"],
                  ts=tok["ts"]).status_code == 200
    r = _write(router_client, "activate", token=tok["token"], ts=tok["ts"])
    assert r.status_code == 403
    assert "already used" in r.json()["error"]
    assert len(fake_transport) == 1
