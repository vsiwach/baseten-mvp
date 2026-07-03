"""Episode recording — the substrate a future RL loop trains on.

Every incident the agent works becomes one JSONL episode: the policy
parameters that were active, what was observed, the action trajectory
(parsed from the authoritative incident ledger), and a shaped reward.
Nothing is synthesized: an episode is a projection of a real incident.

The intended loop (see learning/README.md):
  episodes -> offline policy evaluation -> parameter search over
  AgentConfig (thresholds, probe cadence, escalation) -> shadow policy on
  drills -> promote. Reward today is deliberately simple and auditable.

Recording is on by default and writes to learning/episodes/live.jsonl at
the repo root (override with LEARNING_DIR; disable with LEARNING_DIR=off).
"""

import json
import os
import re
import time
from dataclasses import asdict
from pathlib import Path

_PROBE = re.compile(r"probe (passed|failed) \((\d+)ms\)")


def _default_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "learning" / "episodes"


def episodes_path() -> Path | None:
    configured = os.environ.get("LEARNING_DIR")
    if configured == "off":
        return None
    base = Path(configured) if configured else _default_dir()
    return base / "live.jsonl"


def reward(outcome: dict) -> dict:
    """Auditable shaping: resolution is worth a fixed bonus, every second of
    MTTR costs one point, an escalation costs the human it paged."""
    shaping = {
        "resolved_bonus": 10.0 if outcome["resolved"] else -30.0,
        "mttr_penalty": -float(outcome.get("mttr_s") or 0.0),
        "escalation_penalty": -5.0 if outcome.get("escalated") else 0.0,
    }
    return {"total": round(sum(shaping.values()), 2), "shaping": shaping}


def episode_from_incident(incident: dict, config, context: dict) -> dict:
    """Project a resolved incident (IncidentStore public shape) + the active
    AgentConfig into one training episode."""
    actions = incident.get("actions", [])
    probes = [{"ok": m.group(1) == "passed", "ms": int(m.group(2))}
              for a in actions for m in [_PROBE.search(a)] if m]
    escalated = any("escalat" in a for a in actions)
    quarantined = any("quarantined" in a for a in actions)
    outcome = {
        "resolved": not incident.get("live", False),
        "mttr_s": incident.get("mttr_s"),
        "quarantined": quarantined,
        "escalated": escalated,
        "probes_run": len(probes),
        "probes_failed": sum(1 for p in probes if not p["ok"]),
    }
    return {
        "episode_id": f"ep-{incident['id'].lower()}-{int(incident.get('ts', 0))}",
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "live-incident",
        "policy": asdict(config),
        "context": context,
        "incident": {"id": incident["id"], "title": incident["title"],
                     "agent": incident.get("agent"),
                     "phase_ms": incident.get("phase_ms")},
        "trajectory": actions,
        "probes": probes,
        "outcome": outcome,
        "reward": reward(outcome),
    }


def record(incident: dict, config, context: dict) -> Path | None:
    """Append one episode; never raise into the agent loop."""
    path = episodes_path()
    if path is None or incident is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(
                episode_from_incident(incident, config, context)) + "\n")
        return path
    except Exception:  # noqa: BLE001 — learning must never break serving
        return None
