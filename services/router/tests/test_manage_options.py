"""manage_options.build — pure builder over injected snapshots. The output
must match the design package's '/v1/manage/options' shape and every number
must trace to an injected snapshot (real ids, real prices, measured cold
start), never a fabricated value."""

import json
from pathlib import Path

from router_app import manage_options
from router_app.metrics import MetricsWindow

REPO = Path(__file__).resolve().parents[3]

REPLICAS = [
    {"id": "baseten-l4", "provider": "baseten-l4",
     "url": "http://pool-baseten:8080",
     "model_id": "3ydn1e43", "deployment_id": "qvm1v4e"},
    {"id": "model-api-spill", "provider": "baseten-model-api",
     "url": "http://pool-model-api-a:8080"},
]
REGISTRY_ENTRY = {"tier": "interactive", "max_replicas": 2}
PLACEMENT = {"pools": [{"id": "baseten-l4"}], "compliance": {}}


def _samples(now, tpots, replica="baseten-l4"):
    """Time-ordered Sample list via a real MetricsWindow (injected clock)."""
    t = {"v": now - len(tpots)}

    def clock():
        t["v"] += 1.0
        return t["v"]

    win = MetricsWindow(clock=clock)
    for tp in tpots:
        win.record(model="qwen3-8b", replica=replica, provider="baseten-l4",
                   ttft_ms=100.0, tpot_ms=tp, prompt_tokens=10,
                   completion_tokens=10, est_cost_usd=0.0001,
                   ttft_slo_met=True, tpot_slo_met=True)
    return win.window(3600.0, now + 1)


def _build(now=1000.0, samples=(), events=(), pools=(), catalog=None,
           timeline=None):
    return manage_options.build(
        pools=list(pools) or [{"id": "baseten-l4", "status": "warn",
                               "util_pct": 88.0}],
        samples=list(samples), replicas=REPLICAS,
        registry_entry=REGISTRY_ENTRY, events=list(events),
        placement=PLACEMENT, catalog=catalog, timeline=timeline, now=now)


def test_package_shape_and_only_managed_pools():
    out = _build()
    assert set(out) == {"pools"}
    assert [p["id"] for p in out["pools"]] == ["baseten-l4"]  # no ids → no card
    pool = out["pools"][0]
    assert set(pool) >= {"id", "status", "risk", "options", "drain"}
    assert [o["kind"] for o in pool["options"]] == ["fleet", "model", "spill"]
    for o in pool["options"]:
        assert set(o) >= {"kind", "label", "consequence_text",
                          "mutation_preview"}
    assert pool["drain"]["modes"] == ["graceful", "immediate"]
    assert set(pool["drain"]["steps"]) == {"graceful", "immediate"}


def test_fleet_option_uses_real_ids_price_and_cold_start():
    fleet = _build()["pools"][0]["options"][0]
    assert ("PATCH /v1/models/3ydn1e43/deployments/qvm1v4e/"
            "autoscaling_settings") in fleet["mutation_preview"]
    assert json.loads(fleet["mutation_preview"].split("\n", 1)[1]) == {
        "max_replica": 3}  # registry max_replicas 2 → +1
    assert "$0.90" in fleet["consequence_text"]
    assert "148" in fleet["consequence_text"]
    assert "FRICTION_LOG.md #17" in fleet["consequence_text"]


def test_model_option_cites_timeline_durations_else_estimate():
    timeline = json.loads(
        (REPO / "demo" / "deploy-timeline.json").read_text())
    model = _build(timeline=timeline)["pools"][0]["options"][1]
    assert model["mutation_preview"] == \
        "POST /v1/models/3ydn1e43/deployments/qvm1v4e/promote"
    assert "344 s" in model["consequence_text"]        # real recorded value
    without = _build(timeline=None)["pools"][0]["options"][1]
    assert "estimate" in without["consequence_text"]


def test_spill_option_is_noop_default_and_cites_catalog_price():
    catalog = json.loads(
        (REPO / "deploy" / "baseten" / "model-apis.json").read_text())
    spill = _build(catalog=catalog)["pools"][0]["options"][2]
    assert spill["no_op"] is True
    assert "no-op" in spill["label"].lower()
    # mux default = cheapest completion price → openai/gpt-oss-120b
    assert "openai/gpt-oss-120b" in spill["consequence_text"]
    assert "$0.1/M prompt" in spill["consequence_text"]
    assert "$0.5/M completion" in spill["consequence_text"]
    # the preview body IS the current placement policy (re-applying = no-op)
    body = json.loads(spill["mutation_preview"].split("\n", 1)[1])
    assert body == PLACEMENT


def test_drain_steps_labeled_built_vs_roadmap():
    drain = _build()["pools"][0]["drain"]
    graceful, immediate = drain["steps"]["graceful"], \
        drain["steps"]["immediate"]
    assert all(s.startswith(("[built]", "[roadmap]")) for s in graceful)
    built = [s for s in graceful if s.startswith("[built]")]
    # the KV-aware graceful migration + weighted ramp are BUILT now
    assert len(built) == 2
    assert "KV-aware graceful migration" in built[0]
    assert "/v1/migrations" in built[0]
    assert "weighted ramp" in built[1]
    roadmap = [s for s in graceful if s.startswith("[roadmap]")]
    assert roadmap and "proactive KV transfer" in roadmap[0]
    assert len(immediate) == 1 and immediate[0].startswith("[built]")
    assert "re-prefill storm" in immediate[0]


def test_risk_line_is_real_util_trend_and_spills():
    now = 1000.0
    # rising TPOT: first half p95 ~40, second half ~60 → +50%
    samples = _samples(now, [40.0] * 6 + [60.0] * 6)
    events = [
        {"kind": "route", "replica": "model-api-spill", "ts": now - 10},
        {"kind": "route", "replica": "model-api-spill", "ts": now - 20},
        {"kind": "route", "replica": "baseten-l4", "ts": now - 5},
        {"kind": "route", "replica": "model-api-spill", "ts": now - 900},
    ]
    risk = _build(now=now, samples=samples, events=events,
                  pools=[{"id": "baseten-l4", "status": "warn",
                          "util_pct": 88.0}])["pools"][0]["risk"]
    assert risk.startswith("util 88%")
    assert "+50%" in risk
    assert "2 spill placements in last 5m" in risk


def test_risk_line_honest_when_no_samples():
    risk = _build(samples=[], events=[])["pools"][0]["risk"]
    assert "n/a" in risk
    assert "0 spill placements" in risk
