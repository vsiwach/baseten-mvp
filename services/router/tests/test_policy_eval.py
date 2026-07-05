"""Offline policy evaluation: replay determinism, grid-search winner,
exclusion accounting, and the /v1/learning/policy-eval endpoint."""

import importlib.util
import json
from pathlib import Path

from router_app.incident_agent import AgentConfig
from router_app.replay import replay

REPO = Path(__file__).resolve().parents[3]


def _load_evaluate():
    spec = importlib.util.spec_from_file_location(
        "evaluate", REPO / "learning" / "evaluate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


evaluate = _load_evaluate()


def make_tape(pool="pool-a", other="pool-b", inject_t=4.0, clear_t=12.0,
              n_ticks=10, interval=2.0, breach=0.9):
    """Synthetic ~10-tick tape: fault injected at t=4, cleared mid-way."""
    ticks = []
    for i in range(n_ticks):
        t = i * interval
        faulted = inject_t <= t < clear_t
        ticks.append({
            "t": t, "healthy_pools": 2,
            "signals": [
                {"pool_id": pool, "url": "http://a:8080", "usable": True,
                 "healthz_ok": True,
                 "breach_rate": breach if faulted else 0.0, "samples": 8},
                {"pool_id": other, "url": "http://b:8080", "usable": True,
                 "healthz_ok": True, "breach_rate": 0.0, "samples": 8},
            ],
        })
    return {
        "clock": "monotonic-relative",
        "anchor_utc": "2026-07-03T10:00:00Z",
        "tick_interval_s": interval,
        "fault": {"pool_id": pool, "injected_at": inject_t,
                  "cleared_at": clear_t, "kind": "latency"},
        "ticks": ticks,
        "probes": [
            {"t": 8.0, "pool_id": pool, "ok": False, "latency_ms": 2600.0},
            {"t": 14.0, "pool_id": pool, "ok": True, "latency_ms": 120.0},
        ],
    }


def _train_episodes(n):
    """n synthetic taped episodes whose ids all hash into the train split."""
    out = []
    i = 0
    while len(out) < n:
        eid = f"ep-synth-{i}"
        i += 1
        if evaluate.split(eid) != "train":
            continue
        out.append({"episode_id": eid,
                    "tape": make_tape(clear_t=10.0 + 2.0 * len(out))})
    return out


# ---- (a) replay determinism -------------------------------------------------

def test_replay_is_deterministic():
    tape = make_tape()
    cfg = AgentConfig()
    r1 = replay(tape, cfg)
    r2 = replay(tape, cfg)
    assert r1 == r2
    assert r1["resolved"] is True
    assert r1["mttr_s"] is not None and r1["mttr_s"] > 0
    assert r1["detected_s"] is not None


def test_replay_differs_across_configs():
    tape = make_tape()
    fast = replay(tape, AgentConfig(probe_interval_s=1.0))
    slow = replay(tape, AgentConfig(probe_interval_s=6.0))
    assert fast["probes_run"] != slow["probes_run"]


# ---- (b) grid-search winner >= default on train -----------------------------

def test_winner_at_least_matches_default_on_train():
    episodes = _train_episodes(3)
    report = evaluate.run_eval(episodes)
    curve = report["reward_curve"]
    assert len(curve) == 81
    default_swept = {k: getattr(AgentConfig(), k) for k in evaluate.SWEPT}
    default_mean = next(c["train_reward_mean"] for c in curve
                        if c["config"] == default_swept)
    assert curve[0]["train_reward_mean"] >= default_mean
    # the proposed config is the top-of-curve candidate
    proposed_swept = {k: report["proposed_config"][k]
                      for k in evaluate.SWEPT}
    assert proposed_swept == curve[0]["config"]


# ---- (c) exclusion accounting -----------------------------------------------

def test_untaped_episodes_are_counted_and_excluded():
    episodes = _train_episodes(3) + [
        {"episode_id": "ep-untaped-1", "outcome": {"resolved": True}},
        {"episode_id": "ep-untaped-2", "tape": None},
    ]
    report = evaluate.run_eval(episodes)
    assert report["episodes_total"] == 5
    assert report["episodes_taped"] == 3
    assert report["episodes_excluded"] == 2


def test_zero_taped_corpus_reports_zeros_with_caveat():
    report = evaluate.run_eval(
        [{"episode_id": "ep-untaped-1", "outcome": {"resolved": True}}])
    assert report["episodes_taped"] == 0
    assert report["holdout"]["episodes"] == 0
    assert report["reward_curve"] == []
    assert report["proposed_config"] == report["default_config"]
    assert any("no taped episodes" in c for c in report["caveats"])


# ---- (d) endpoint -----------------------------------------------------------

def test_policy_eval_endpoint_missing_file(router_client, tmp_path,
                                           monkeypatch):
    monkeypatch.setenv("POLICY_EVAL_PATH", str(tmp_path / "nope.json"))
    assert router_client.get("/v1/learning/policy-eval").json() == {
        "available": False}


def test_policy_eval_endpoint_passthrough(router_client, tmp_path,
                                          monkeypatch):
    """Phase C: the default response is the board-shaped adapter; the raw
    Phase-B artifact stays readable at ?raw=1."""
    payload = {"episodes_taped": 3, "holdout": {"episodes": 1}}
    path = tmp_path / "policy-eval.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("POLICY_EVAL_PATH", str(path))
    body = router_client.get("/v1/learning/policy-eval?raw=1").json()
    assert body["available"] is True
    assert body["episodes_taped"] == 3
    assert body["holdout"] == {"episodes": 1}
    shaped = router_client.get("/v1/learning/policy-eval").json()
    assert shaped["available"] is True
    assert shaped["episodes_taped"] == 3
    assert set(shaped["holdout"]) == {"default", "proposed"}
