"""Phase C board integration: /board/{page} serving + asset allowlist, the
policy-eval adapter, governed promote validation, the deploy-timeline
adapter (real artifact, no invented fields), tier+slo on /v1/metrics/slo,
and the placement feed snapshot."""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


# ---- /board/{page} + /board-assets/{name} --------------------------------

def test_board_operate_rewrites_assets_and_injects_live_fetch(router_client):
    r = router_client.get("/board/operate")
    assert r.status_code == 200
    html = r.text
    assert 'href="/board-assets/tokens.css"' in html
    assert 'href="/board-assets/shell.css"' in html
    assert 'src="/board-assets/console.js"' in html
    assert 'src="/board-assets/mock-data.js"' in html
    # live-fetch loads AFTER console.js so its fetchJSON wins
    assert ('<script src="/board-assets/console.js"></script>\n'
            '<script src="/board-assets/live-fetch.js"></script>') in html
    # no relative package paths survive
    assert 'href="tokens.css"' not in html
    assert 'src="console.js"' not in html
    # in-page relative links point at the live routes
    assert 'href="policy.html"' not in html


def test_all_board_pages_serve(router_client):
    for page in ("operate", "deploy", "policy", "manage", "roadmap"):
        assert router_client.get(f"/board/{page}").status_code == 200
    assert router_client.get("/board/nope").status_code == 404


def test_board_assets_allowlist(router_client):
    for name, ctype in (("tokens.css", "text/css"),
                        ("shell.css", "text/css"),
                        ("console.js", "application/javascript"),
                        ("mock-data.js", "application/javascript"),
                        ("live-fetch.js", "application/javascript")):
        r = router_client.get(f"/board-assets/{name}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(ctype)
    assert router_client.get("/board-assets/../CLAUDE.md").status_code in \
        (404, 400)
    assert router_client.get("/board-assets/evil.js").status_code == 404


# ---- policy-eval adapter ---------------------------------------------------

PHASE_B_EVAL = {
    "generated_at": "2026-07-04T10:00:00Z",
    "corpus_sha256": "abc123",
    "default_config": {"breach_rate_threshold": 0.5},
    "proposed_config": {"breach_rate_threshold": 0.3},
    "holdout": {
        "episodes": 4,
        "mttr_default_s": 61.0, "mttr_proposed_s": 42.5,
        "unresolved_default": 1, "unresolved_proposed": 0,
        "escalations_default": 9, "escalations_proposed": 7,
        "probes_default": 1240, "probes_proposed": 1615,
    },
    "reward_curve": [{"config": {"a": 1}, "train_reward_mean": -1.4},
                     {"config": {"a": 2}, "train_reward_mean": -0.8}],
    "episodes_total": 10, "episodes_taped": 6, "episodes_excluded": 4,
    "caveats": ["sim-sourced drills only"],
}


def test_policy_eval_adapter_shapes_phase_b_file(router_client, tmp_path,
                                                 monkeypatch):
    path = tmp_path / "policy-eval.json"
    path.write_text(json.dumps(PHASE_B_EVAL))
    monkeypatch.setenv("POLICY_EVAL_PATH", str(path))
    body = router_client.get("/v1/learning/policy-eval").json()
    assert body["available"] is True
    assert body["generated_at"] == "2026-07-04T10:00:00Z"
    assert body["corpus_sha256"] == "abc123"
    assert body["holdout"]["default"] == {
        "mttr_mean_s": 61.0, "escalations": 9, "probes": 1240,
        "unresolved": 1}
    assert body["holdout"]["proposed"] == {
        "mttr_mean_s": 42.5, "escalations": 7, "probes": 1615,
        "unresolved": 0}
    assert body["reward_curve"] == [-1.4, -0.8]     # file order
    assert body["episodes_total"] == 10
    assert body["episodes_taped"] == 6
    assert body["episodes_excluded"] == 4
    assert body["caveats"] == ["sim-sourced drills only"]
    # raw passthrough unchanged
    raw = router_client.get("/v1/learning/policy-eval?raw=1").json()
    assert raw["holdout"]["mttr_default_s"] == 61.0


# ---- governed promote -------------------------------------------------------

GOOD_CONFIG = {
    "breach_rate_threshold": 0.3, "min_samples": 4, "probe_interval_s": 2.0,
    "probes_to_reinstate": 2, "cooldown_s": 30.0, "probe_slo_ms": 500.0,
    "escalate_after_failures": 5,
}


@pytest.fixture()
def pending_path(tmp_path, monkeypatch):
    path = tmp_path / "pending-policy.json"
    monkeypatch.setenv("PENDING_POLICY_PATH", str(path))
    return path


def test_promote_writes_pending_and_awaits_approver(router_client,
                                                    pending_path):
    r = router_client.post("/v1/learning/policy/promote",
                           json={"config": GOOD_CONFIG, "approver": "human"})
    assert r.status_code == 200
    assert r.json() == {"status": "awaiting_approver"}
    record = json.loads(pending_path.read_text())
    assert record["config"] == GOOD_CONFIG
    assert record["status"] == "awaiting_approver"
    assert record["proposed_at"]
    assert router_client.get("/v1/learning/policy/pending").json() == record
    assert router_client.state.events.kinds().get(
        "policy_promote_proposed") == 1


def test_promote_rejects_extra_missing_and_non_numeric(router_client,
                                                       pending_path):
    extra = dict(GOOD_CONFIG, surprise=1)
    assert router_client.post("/v1/learning/policy/promote",
                              json={"config": extra}).status_code == 400
    missing = {k: v for k, v in GOOD_CONFIG.items()
               if k != "cooldown_s"}
    assert router_client.post("/v1/learning/policy/promote",
                              json={"config": missing}).status_code == 400
    stringy = dict(GOOD_CONFIG, probe_interval_s="fast")
    assert router_client.post("/v1/learning/policy/promote",
                              json={"config": stringy}).status_code == 400
    assert not pending_path.exists()   # nothing recorded on rejection
    assert router_client.get("/v1/learning/policy/pending").json() == {
        "status": "none"}


# ---- deploy-timeline adapter ------------------------------------------------

def test_timeline_adapter_maps_real_artifact_without_invention(router_client):
    artifact = json.loads((REPO / "demo" / "deploy-timeline.json").read_text())
    body = router_client.get("/v1/releases/timeline").json()
    assert body["model"] == artifact["model"]           # "Qwen3-8B-AWQ"
    # fields the artifact never recorded are null + declared in `source`
    assert body["version"] is None
    assert body["strategy"] is None
    assert body["tier_target"] is None
    assert "not recorded" in body["source"]
    assert len(body["attempts"]) == len(artifact["attempts"])
    first, last = body["attempts"][0], body["attempts"][-1]
    assert first == {
        "n": 1, "at": "16:02", "stage": "truss push", "outcome": "failed",
        "note": (artifact["attempts"][0]["error"] + " — "
                 + artifact["attempts"][0]["diagnosis"])}
    assert last["outcome"] == "live"
    assert last["n"] == 7


# ---- tier + slo on /v1/metrics/slo -----------------------------------------

@pytest.fixture()
def llm_client(tmp_path, monkeypatch):
    """App whose devboard model is an LLM pool (no live backends needed —
    shape-level test; background threads off)."""
    from starlette.testclient import TestClient
    from router_app.main import get_app

    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "backends:\n"
        "  qwen3-8b:\n"
        "    tier: interactive\n"
        "    target: gpu\n"
        "    engine: vllm\n"
        "    max_replicas: 2\n")
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "tiers:\n"
        "  interactive: {max_latency_ms: 1000, prefer: lowest_latency,"
        " ttft_ms: 800, tpot_ms: 60}\n"
        "cost_table: {baseten-l4: 1.05, baseten-model-api: 3.0}\n"
        "cache: {enabled: false}\n"
        "affinity: {enabled: true, prefix_tokens: 32, capacity: 8}\n"
        "endpoints:\n"
        "  qwen3-8b:\n"
        "    - id: baseten-l4\n"
        "      provider: baseten-l4\n"
        "      url: http://pool-baseten:8080\n"
        "      model_id: 3ydn1e43\n"
        "      deployment_id: qvm1v4e\n"
        "    - id: model-api-spill\n"
        "      provider: baseten-model-api\n"
        "      url: http://pool-model-api-a:8080\n")
    monkeypatch.setenv("ROUTER_QUEUE_DIR", str(tmp_path / "queue"))
    app = get_app(registry, policy, start_background=False)
    with TestClient(app) as client:
        client.state = app.state.router_state
        yield client


def test_slo_payload_carries_tier_and_slo_per_pool(llm_client):
    pools = llm_client.get("/v1/metrics/slo").json()["pools"]
    assert [p["id"] for p in pools] == ["baseten-l4", "model-api-spill"]
    for p in pools:
        assert p["tier"] == "interactive"               # from the registry
        assert p["slo"] == {"ttft_p99_ms": 800,
                            "tpot_p99_ms": 60}          # from tier rules


def test_manage_options_endpoint_uses_registry_ids(llm_client):
    pools = llm_client.get("/v1/manage/options").json()["pools"]
    assert [p["id"] for p in pools] == ["baseten-l4"]
    fleet = pools[0]["options"][0]
    assert "/models/3ydn1e43/deployments/qvm1v4e/" in \
        fleet["mutation_preview"]


# ---- placement feed snapshot ------------------------------------------------

def test_feed_snapshot_returns_array_of_recent_routes(llm_client):
    state = llm_client.state
    for i in range(40):
        state.events.emit("route", model="qwen3-8b", replica="baseten-l4",
                          provider="baseten-l4", cache_hit=False,
                          reason="affinity_place", ttft_ms=100.0 + i,
                          tpot_ms=30.0, req=f"#{i:04d}", wl_tier="interactive",
                          tag=None, decide_ms=0.5,
                          iso_ts="2026-07-04T00:00:00Z")
    body = llm_client.get("/v1/placement/feed/snapshot").json()
    assert isinstance(body, list)
    assert len(body) == 30                       # last 30 of 40
    assert body[-1]["req"] == "#0039"
    assert set(body[0]) >= {"req", "tier", "pool", "reason", "ttft_ms",
                            "decide_ms"}


def test_feed_snapshot_empty_when_no_traffic(router_client):
    assert router_client.get("/v1/placement/feed/snapshot").json() == []
