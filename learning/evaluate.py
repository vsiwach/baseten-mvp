#!/usr/bin/env python3
"""Offline policy evaluation — grid-search AgentConfig over taped episodes.

Loads learning/episodes/*.jsonl, keeps the episodes that carry a replayable
tape (recorded fault window + signal ticks), splits them train/holdout by a
stable hash of episode_id, replays every train tape under an 81-candidate
grid of AgentConfig scalars (router_app/replay.py — the SAME decision core
that runs live), scores each candidate with the auditable reward from
router_app/learning.py, and reports the winner vs the default config on the
holdout set only. Output: learning/policy-eval.json.

Nothing is synthesized: with zero taped episodes the report is written with
zeros and an explicit caveat. stdlib only.

    python3 learning/evaluate.py [--episodes-dir learning/episodes]
                                 [--out learning/policy-eval.json]
"""

import argparse
import hashlib
import itertools
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "router"))

from router_app.incident_agent import AgentConfig  # noqa: E402
from router_app.learning import reward  # noqa: E402
from router_app.replay import replay  # noqa: E402

# The 4 swept scalars; the other 3 AgentConfig scalars (min_samples,
# cooldown_s, probe_slo_ms) stay at their defaults. Nothing else is swept.
SWEPT = ("breach_rate_threshold", "probe_interval_s",
         "probes_to_reinstate", "escalate_after_failures")
GRID = {
    "breach_rate_threshold": [0.3, 0.5, 0.7],
    "probe_interval_s": [1.0, 3.0, 6.0],
    "probes_to_reinstate": [1, 2, 3],
    "escalate_after_failures": [3, 5, 8],
}

CAVEATS = [
    "sim-sourced drills only — no live traffic",
    "binary fault oracle: probe succeeds iff after cleared_at",
    "IMPROVEMENT IS PARTLY BY CONSTRUCTION: under the binary oracle no "
    "replayed probe ever fails after fault-clear, so post-detection MTTR "
    "reduces to probe_interval_s x probes_to_reinstate for ANY corpus — "
    "faster probing always wins here, and this eval cannot price the costs "
    "of aggressive probing (probe load, flapping, premature reinstatement)",
    "reward() is reused verbatim from the agent's own shaping and is "
    "open-anchored (MTTR = resolve - open); detection latency is NOT priced, "
    "so candidates that would detect earlier/later than the tape's opening "
    "are not rewarded/penalized for it",
    "escalate_after_failures is inert in this corpus (no replayed probe "
    "fails, so no escalations occur and its grid dimension produces ties)",
    "breach-rate hold heuristic post-quarantine",
    "no cross-pool spill modeling",
    "cooldown_s and min_samples not exercised by this corpus",
    "probe latencies are taped magnitudes, not remeasured",
]
NO_TAPE_CAVEAT = ("no taped episodes in this corpus yet — all metrics are "
                  "zeros; resolve a chaos-injected incident (via "
                  "/v1/dev/chaos) to record tapes")


def load_episodes(episodes_dir: Path) -> list[dict]:
    out = []
    for f in sorted(episodes_dir.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def is_taped(episode: dict) -> bool:
    """Replayable = has a tape whose fault window is fully known."""
    tape = episode.get("tape")
    return bool(tape
                and tape.get("fault", {}).get("cleared_at") is not None
                and tape.get("ticks"))


def split(episode_id: str) -> str:
    """Stable 70/30 train/holdout split on the episode id."""
    h = int(hashlib.sha256(episode_id.encode()).hexdigest(), 16)
    return "train" if h % 10 < 7 else "holdout"


def grid_candidates(grid: dict | None = None) -> list[AgentConfig]:
    grid = grid or GRID
    keys = list(SWEPT)
    out = []
    for values in itertools.product(*(grid[k] for k in keys)):
        out.append(AgentConfig(**dict(zip(keys, values))))
    return out


def _swept_of(cfg: AgentConfig) -> dict:
    return {k: getattr(cfg, k) for k in SWEPT}


def _holdout_stats(cfg: AgentConfig, episodes: list[dict]) -> dict:
    outs = [replay(ep["tape"], cfg) for ep in episodes]
    resolved = [o for o in outs if o["resolved"]]
    return {
        "mttr_s": round(sum(o["mttr_s"] for o in resolved) / len(resolved), 3)
        if resolved else 0.0,
        "unresolved": len(outs) - len(resolved),
        "escalations": sum(1 for o in outs if o["escalated"]),
        "probes": sum(o["probes_run"] for o in outs),
    }


def _generated_at(taped: list[dict]) -> str | None:
    """Latest instant covered by the corpus — from the tapes, never the
    wall clock: max over tapes of anchor_utc + last tick t."""
    best = None
    for ep in taped:
        tape = ep["tape"]
        anchor = tape.get("anchor_utc")
        if not anchor:
            continue
        dt = (datetime.fromisoformat(anchor.replace("Z", "+00:00"))
              + timedelta(seconds=float(tape["ticks"][-1]["t"])))
        best = dt if best is None or dt > best else best
    if best is None:
        return None
    return best.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_eval(episodes: list[dict], grid: dict | None = None) -> dict:
    """Grid-search core: episodes in, policy-eval report dict out."""
    default = AgentConfig()
    default_swept = _swept_of(default)
    grid = grid or GRID
    for k in SWEPT:            # the default MUST be one of the candidates
        assert default_swept[k] in grid[k], \
            f"default {k}={default_swept[k]} not in grid {grid[k]}"

    taped = [ep for ep in episodes if is_taped(ep)]
    train = [ep for ep in taped if split(ep["episode_id"]) == "train"]
    holdout = [ep for ep in taped if split(ep["episode_id"]) == "holdout"]

    scored: list[tuple[AgentConfig, float]] = []
    if train:
        for cfg in grid_candidates(grid):
            totals = [reward(replay(ep["tape"], cfg))["total"]
                      for ep in train]
            scored.append((cfg, round(sum(totals) / len(totals), 3)))

    def _rank(item):
        cfg, mean = item
        n_diff = sum(1 for k in SWEPT
                     if getattr(cfg, k) != default_swept[k])
        return (-mean, n_diff, tuple(getattr(cfg, k) for k in SWEPT))

    winner = min(scored, key=_rank)[0] if scored else default
    curve = [{"config": _swept_of(cfg), "train_reward_mean": mean}
             for cfg, mean in sorted(scored, key=_rank)]

    if holdout:
        d, p = (_holdout_stats(default, holdout),
                _holdout_stats(winner, holdout))
    else:
        d = p = {"mttr_s": 0.0, "unresolved": 0, "escalations": 0,
                 "probes": 0}
    return {
        "generated_at": _generated_at(taped),
        "corpus_sha256": hashlib.sha256("".join(
            sorted(ep["episode_id"] for ep in taped)).encode()).hexdigest(),
        "default_config": asdict(default),
        "proposed_config": asdict(winner),
        "holdout": {
            "episodes": len(holdout),
            "mttr_default_s": d["mttr_s"],
            "mttr_proposed_s": p["mttr_s"],
            "unresolved_default": d["unresolved"],
            "unresolved_proposed": p["unresolved"],
            "escalations_default": d["escalations"],
            "escalations_proposed": p["escalations"],
            "probes_default": d["probes"],
            "probes_proposed": p["probes"],
        },
        "reward_curve": curve,
        "episodes_total": len(episodes),
        "episodes_taped": len(taped),
        "episodes_excluded": len(episodes) - len(taped),
        "caveats": ([NO_TAPE_CAVEAT] if not taped else [])
        + CAVEATS
        + (
            [
                "proposed probes_to_reinstate is LOWER than default — faster "
                "reinstatement trades away flap-robustness, and the binary "
                "fault oracle cannot model flapping pools; shadow-run on "
                "fresh drills before adopting"
            ]
            if winner.probes_to_reinstate < default.probes_to_reinstate
            else []
        ),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--episodes-dir",
                    default=str(REPO / "learning" / "episodes"))
    ap.add_argument("--out",
                    default=str(REPO / "learning" / "policy-eval.json"))
    args = ap.parse_args(argv)

    episodes = load_episodes(Path(args.episodes_dir))
    report = run_eval(episodes)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")

    n_taped = report["episodes_taped"]
    print(f"episodes: {report['episodes_total']} total, {n_taped} taped, "
          f"{report['episodes_excluded']} excluded (no replayable tape)")
    if n_taped == 0:
        print("0 taped episodes — wrote a zeroed report with an explicit "
              "caveat; nothing to evaluate yet.")
        print(f"wrote {out}")
        return 0
    h = report["holdout"]
    print(f"train/holdout split: "
          f"{n_taped - h['episodes']}/{h['episodes']}")
    print(f"proposed config (train winner over {len(report['reward_curve'])}"
          f" candidates): "
          f"{ {k: report['proposed_config'][k] for k in SWEPT} }")
    print(f"holdout ({h['episodes']} eps): "
          f"mttr default {h['mttr_default_s']}s vs proposed "
          f"{h['mttr_proposed_s']}s · unresolved "
          f"{h['unresolved_default']} vs {h['unresolved_proposed']} · "
          f"escalations {h['escalations_default']} vs "
          f"{h['escalations_proposed']} · probes {h['probes_default']} vs "
          f"{h['probes_proposed']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
