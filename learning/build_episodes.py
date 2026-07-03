#!/usr/bin/env python3
"""Backfill learning episodes from committed evidence — never synthesize.

Two honest sources, each marked with its provenance:
  1. benchmarks/raw/chaos_drills.csv        (drill runner's summary rows:
     fault parameters + detection/quarantine timings + MTTR)
  2. benchmarks/raw/devboard-*/incidents.json (the incident ledger: action
     trajectory + probe results, from the live 2026-07-02/03 sessions)

    python3 learning/build_episodes.py
"""
import csv
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "router"))

from router_app.incident_agent import AgentConfig  # noqa: E402
from router_app.learning import episode_from_incident, reward  # noqa: E402

RAW = REPO / "benchmarks" / "raw"
OUT = REPO / "learning" / "episodes" / "backfill.jsonl"


def drill_episodes() -> list[dict]:
    out = []
    with open(RAW / "chaos_drills.csv") as f:
        for r in csv.DictReader(f):
            resolved = r["resolved"] == "True"
            outcome = {
                "resolved": resolved,
                "mttr_s": float(r["mttr_s"]) if r["mttr_s"] else None,
                "detected_s": float(r["detected_s"]) if r["detected_s"] else None,
                "quarantined": bool(r["quarantined_s"]),
                "escalated": False,
                "requests": int(r["requests"] or 0),
                "request_errors": int(r["request_errors"] or 0),
            }
            out.append({
                "episode_id": f"ep-drill-{r['stamp']}-{r['scenario']}",
                "source": f"backfill:chaos_drills.csv:{r['stamp']}",
                "policy": {"note": "AgentConfig defaults of that commit"},
                "context": {"model": r["model"], "pool": r["pool"],
                            "agent_enabled": r["agent"] != ""},
                "fault": {"injected": True, "scenario": r["scenario"],
                          "latency_ms": float(r["latency_ms"] or 0),
                          "error_rate": float(r["error_rate"] or 0)},
                "outcome": outcome,
                "reward": reward(outcome),
            })
    return out


def incident_episodes() -> list[dict]:
    out = []
    cfg = AgentConfig()
    for snap in sorted(RAW.glob("devboard-*/incidents.json")):
        day = re.search(r"devboard-(\d+)", str(snap)).group(1)
        for inc in json.loads(snap.read_text()):
            if inc.get("live"):
                continue
            ep = episode_from_incident(inc, cfg, {"snapshot_day": day})
            ep["episode_id"] = f"ep-{day}-{inc['id'].lower()}"
            ep["source"] = f"backfill:{snap.relative_to(REPO)}"
            out.append(ep)
    return out


if __name__ == "__main__":
    episodes = drill_episodes() + incident_episodes()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        for ep in episodes:
            f.write(json.dumps(ep) + "\n")
    resolved = sum(1 for e in episodes if e["outcome"]["resolved"])
    print(f"wrote {OUT.relative_to(REPO)}: {len(episodes)} episodes "
          f"({resolved} resolved, {len(episodes) - resolved} unresolved)")
