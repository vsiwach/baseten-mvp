"""Episode recording — incident ledger -> RL episode projection."""

import json

from router_app.incident_agent import AgentConfig
from router_app.learning import episode_from_incident, record, reward

INCIDENT = {
    "id": "INC-0007", "title": "baseten-l4 breaching serving SLO — 50%",
    "ts": 1783000000.0, "live": False, "mttr_s": 8.8, "agent": True,
    "phase_ms": {"detect": 0.0, "diagnose": 0.0, "resolve": 8800.0},
    "actions": [
        "detected SLO breach rate 50% over 6 requests on baseten-l4",
        "quarantined baseten-l4; traffic spills to healthy pools",
        "probe failed (531ms)",
        "probe passed (364ms)",
        "probe passed (352ms)",
        "reinstated baseten-l4 — 2 consecutive probes within SLO",
    ],
}


def test_episode_projection_parses_probes_and_outcome():
    ep = episode_from_incident(INCIDENT, AgentConfig(), {"model": "qwen3-8b"})
    assert ep["probes"] == [{"ok": False, "ms": 531},
                            {"ok": True, "ms": 364},
                            {"ok": True, "ms": 352}]
    assert ep["outcome"]["resolved"] is True
    assert ep["outcome"]["quarantined"] is True
    assert ep["outcome"]["escalated"] is False
    assert ep["policy"]["probes_to_reinstate"] == 2


def test_reward_is_auditable_and_penalizes_failure():
    good = reward({"resolved": True, "mttr_s": 8.8, "escalated": False})
    assert good["total"] == round(10.0 - 8.8, 2)
    bad = reward({"resolved": False, "mttr_s": None, "escalated": True})
    assert bad["total"] == -35.0
    assert set(good["shaping"]) == {"resolved_bonus", "mttr_penalty",
                                    "escalation_penalty"}


def test_record_appends_jsonl_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_DIR", str(tmp_path))
    path = record(INCIDENT, AgentConfig(), {"model": "qwen3-8b"})
    assert path is not None and path.exists()
    ep = json.loads(path.read_text().splitlines()[0])
    assert ep["source"] == "live-incident"
    # disabled mode
    monkeypatch.setenv("LEARNING_DIR", "off")
    assert record(INCIDENT, AgentConfig(), {}) is None
    # malformed incident must not raise into the agent loop
    monkeypatch.setenv("LEARNING_DIR", str(tmp_path))
    assert record(None, AgentConfig(), {}) is None
