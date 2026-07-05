"""Manage-screen options builder — design/mock-data.js '/v1/manage/options'.

Pure: every input is an injected snapshot (pools snapshot, metrics samples,
replica config, route events, placement policy, Model-API catalog, the
recorded deploy timeline). Every number in the output traces to one of them;
consequence texts cite their sources (Baseten T4 pricing, the measured cold
start in docs/FRICTION_LOG.md #17, deploy/baseten/model-apis.json prices,
demo/deploy-timeline.json durations). No fabricated values: empty windows
say "n/a", never a plausible-looking number.

Only pools that carry real Baseten management ids (model_id/deployment_id on
the routing-policy endpoint entry) get option cards — a mutation preview
without real ids would be demo-ware.
"""

import json

T4_USD_PER_HR = 0.90          # Baseten dedicated T4, per replica while active
COLD_START_S = 148            # measured with weights: BDN — FRICTION_LOG #17
DRAIN_TIMEOUT_S = 30          # graceful drain in-flight wait (router default)
SPILL_WINDOW_S = 300.0
TREND_WINDOW_LABEL = "15m"


def _p95(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[max(0, min(len(s) - 1, round(0.95 * len(s)) - 1))]


def _tpot_trend_pct(samples: list) -> float | None:
    """p95 TPOT, second half of the window vs first half. None (= "n/a")
    below 6 samples — a trend from 2 points is fabrication."""
    vals = [s.tpot_ms for s in sorted(samples, key=lambda s: s.ts)]
    if len(vals) < 6:
        return None
    half = len(vals) // 2
    first, second = _p95(vals[:half]), _p95(vals[half:])
    if first <= 0:
        return None
    return round((second - first) / first * 100.0, 1)


def _spill_count(events: list[dict], pool_id: str, now: float,
                 window_s: float = SPILL_WINDOW_S) -> int:
    """Placements of this pool's model that landed on ANOTHER pool in the
    window. Honest definition: with prefix affinity enabled the spill
    replica is a consistent-hash PEER (policy.py rings over all candidates),
    not overflow-only — a hash share of new prefixes lands off-pool even
    when this pool is healthy; quarantine/capacity sends the rest. So this
    counts "traffic not on this pool", not "degraded-mode overflow"."""
    return sum(1 for e in events
               if e.get("kind") == "route"
               and e.get("replica") not in (None, pool_id)
               and now - e.get("ts", 0) <= window_s)


def _risk_line(util_pct: float, trend_pct: float | None, spills: int) -> str:
    trend = ("TPOT p95 trend n/a (insufficient samples)"
             if trend_pct is None else
             f"TPOT p95 {trend_pct:+.0f}% over last {TREND_WINDOW_LABEL}")
    return (f"util {util_pct:.0f}%; {trend}; "
            f"{spills} spill placement{'s' if spills != 1 else ''} "
            f"in last 5m")


def _fleet_option(model_id: str, deployment_id: str,
                  registry_entry: dict) -> dict:
    n_max = int(registry_entry.get("max_replicas", 1))
    return {
        "kind": "fleet",
        "label": f"Fleet upgrade — max_replica {n_max} → {n_max + 1}",
        "consequence_text": (
            f"+${T4_USD_PER_HR:.2f}/hr per T4 replica while active (Baseten "
            f"pricing); new replica serves after ~{COLD_START_S} s measured "
            "cold start (docs/FRICTION_LOG.md #17)"),
        "mutation_preview": (
            f"PATCH /v1/models/{model_id}/deployments/{deployment_id}"
            "/autoscaling_settings\n"
            + json.dumps({"max_replica": n_max + 1})),
    }


def _model_option(model_id: str, deployment_id: str,
                  timeline: dict | None) -> dict:
    attempts = (timeline or {}).get("attempts") or []
    if attempts:
        last = attempts[-1]
        total = sum(a.get("duration_s") or 0 for a in attempts)
        consequence = (
            "Promotes this deployment to production. Recorded deploy "
            f"(demo/deploy-timeline.json): final attempt reached live in "
            f"{last.get('duration_s')} s; full attempt trail {total} s "
            f"across {len(attempts)} attempts.")
    else:
        consequence = ("Promotes this deployment to production "
                       "(duration: estimate — no recorded timeline).")
    return {
        "kind": "model",
        "label": "Model upgrade — promote deployment",
        "consequence_text": consequence,
        "mutation_preview": (f"POST /v1/models/{model_id}/deployments/"
                             f"{deployment_id}/promote"),
    }


def _spill_option(placement: dict, catalog: dict | None,
                  default_alias: str | None) -> dict:
    models = (catalog or {}).get("models") or []
    target = None
    if default_alias:
        target = next((m for m in models if m.get("alias") == default_alias),
                      None)
    if target is None and models:
        # the Model-API mux default: cheapest by completion price (mux.py)
        target = min(models,
                     key=lambda m: m.get("usd_per_1m_completion", 0.0))
    if target:
        price = (f"default target {target['slug']} at "
                 f"${target['usd_per_1m_prompt']}/M prompt · "
                 f"${target['usd_per_1m_completion']}/M completion "
                 "(deploy/baseten/model-apis.json)")
    else:
        price = "per-token prices unavailable (catalog snapshot missing)"
    return {
        "kind": "spill",
        "label": "Spill to Model APIs (current default — no-op)",
        "consequence_text": (
            "No-op default: the per-token Model-API replica is already in "
            "this model's replica set (configs/routing-policy.yaml) as a "
            "consistent-hash affinity peer — it takes a hash share of new "
            "prefixes in steady state and absorbs ALL traffic when this "
            "pool is quarantined or at capacity. Overflow-only spill "
            "(dedicated-first, per-token fallback) is roadmap. Spilled "
            f"tokens bill per-token — {price}."),
        "mutation_preview": ("POST /v1/policy/placement\n"
                             + json.dumps(placement or {}, indent=1)),
        "no_op": True,
    }


def _drain_plan(pool_id: str) -> dict:
    return {
        "modes": ["graceful", "immediate"],
        "steps": {
            "graceful": [
                "[built] Exclude pool from placement (sticky quarantine — "
                "no new requests land here)",
                f"[built] Wait for in-flight requests on the pool to reach 0 "
                f"(timeout {DRAIN_TIMEOUT_S} s)",
                f"[built] Report drained "
                f"(POST /v1/pools/{pool_id}/drain?mode=graceful)",
                "[roadmap] Weighted, KV-aware drain — migrate warm KV "
                "sessions before detach",
            ],
            "immediate": [
                "[built] Immediate placement exclusion — new requests stop "
                "now, in-flight requests are not waited on "
                f"(POST /v1/pools/{pool_id}/drain?mode=immediate)",
            ],
        },
    }


def build(*, pools: list[dict], samples: list, replicas: list[dict],
          registry_entry: dict, events: list[dict], placement: dict,
          catalog: dict | None, timeline: dict | None, now: float,
          default_alias: str | None = None) -> dict:
    """The '/v1/manage/options' payload. `pools` is devboard.pools_snapshot()
    output; `samples` a MetricsWindow slice; `replicas` cfg.replicas_for()
    entries (Baseten ids ride along from the routing policy); `events`
    route events for the watched model."""
    by_id = {p["id"]: p for p in pools}
    out = []
    for rep in replicas:
        model_id = rep.get("model_id")
        deployment_id = rep.get("deployment_id")
        if not (model_id and deployment_id):
            continue
        pool = by_id.get(rep["id"], {})
        pool_samples = [s for s in samples if s.replica == rep["id"]]
        out.append({
            "id": rep["id"],
            "status": pool.get("status", "ok"),
            "risk": _risk_line(pool.get("util_pct", 0.0),
                               _tpot_trend_pct(pool_samples),
                               _spill_count(events, rep["id"], now)),
            "options": [
                _fleet_option(model_id, deployment_id, registry_entry),
                _model_option(model_id, deployment_id, timeline),
                _spill_option(placement, catalog, default_alias),
            ],
            "drain": _drain_plan(rep["id"]),
        })
    return {"pools": out}
