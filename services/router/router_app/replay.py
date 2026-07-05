"""Offline tape replay — re-run IncidentAgentLogic against a recorded fault.

A "tape" (recorded by IncidentAgentRunner, schema in learning/README.md) is
the flight-recorder slice of one chaos-injected incident: signal ticks,
probe results, and the ground-truth fault window. replay() re-drives the
pure decision core over that tape under an arbitrary AgentConfig, so
learning/evaluate.py can grid-search policy parameters offline.

Pure function of (tape, cfg): no I/O, no wall clock, no randomness, no
dict-order dependence (pools are sorted by pool_id). The replay never
invents action types — every action comes out of IncidentAgentLogic.

Counterfactual reconstruction heuristics (deliberately simple, listed in
policy-eval.json caveats):
  * Binary fault oracle: a probe succeeds iff it fires at or after
    fault.cleared_at. Probe latencies are taped magnitudes, not remeasured.
  * Breach-rate hold: while the fault is active the faulted pool's
    breach_rate holds the peak taped value (the original run's quarantine
    drained its sample window, which would hide the fault from stricter
    counterfactual policies). Between cleared_at and cleared_at + 15s (one
    SLO window) it keeps that last hot value, then drops to 0.0 — a step,
    not a decay.
  * The faulted pool's healthz_ok is forced True after cleared_at.
  * usable = healthz-based usability AND not quarantined by THIS replay.
"""

from router_app.incident_agent import (AgentConfig, IncidentAgentLogic,
                                       PoolSignal)

SLO_WINDOW_S = 15.0     # one metrics/SLO window: breach rate decays to 0
HORIZON_S = 180.0       # synthetic ticks stop at cleared_at + HORIZON_S


def _median(vals: list[float]) -> float:
    vals = sorted(vals)
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def replay(tape: dict, cfg: AgentConfig) -> dict:
    """Re-run the incident on the tape under `cfg`. Returns
    {"resolved", "mttr_s", "escalated", "probes_run", "detected_s"}."""
    logic = IncidentAgentLogic(cfg)
    fault = tape["fault"]
    fault_pool = fault["pool_id"]
    injected = float(fault["injected_at"])
    cleared = float(fault["cleared_at"])
    interval = float(tape.get("tick_interval_s", 2.0))

    taped_ticks = sorted(tape.get("ticks", []), key=lambda tk: float(tk["t"]))
    result = {"resolved": False, "mttr_s": None, "escalated": False,
              "probes_run": 0, "detected_s": None}
    if not taped_ticks:
        return result

    # probe latencies come from the tape (magnitudes only — the ok/fail
    # verdict is the binary fault oracle, latency is cosmetic to the logic)
    pass_lat = [float(p["latency_ms"]) for p in tape.get("probes", [])
                if p["ok"]]
    fail_lat = [float(p["latency_ms"]) for p in tape.get("probes", [])
                if not p["ok"]]
    ok_latency = _median(pass_lat) if pass_lat else 25.0
    fail_latency = (max(cfg.probe_slo_ms + 100.0, _median(fail_lat))
                    if fail_lat else cfg.probe_slo_ms + 100.0)

    pools = sorted({s["pool_id"] for tk in taped_ticks
                    for s in tk["signals"]})
    # last taped signal per pool, seeded with each pool's first occurrence
    last: dict[str, dict] = {}
    for tk in taped_ticks:
        for s in tk["signals"]:
            last.setdefault(s["pool_id"], s)

    # timeline: taped ticks, then synthetic ticks every `interval` up to
    # cleared_at + HORIZON_S (index-based to avoid float drift)
    timeline: list[tuple[float, dict | None]] = [
        (float(tk["t"]), tk) for tk in taped_ticks]
    t_last = timeline[-1][0]
    i = 1
    while t_last + i * interval <= cleared + HORIZON_S:
        timeline.append((t_last + i * interval, None))
        i += 1

    quarantined: set[str] = set()
    open_t: float | None = None
    resolve_t: float | None = None
    escalated = False
    probes_run = 0
    peak_breach = 0.0

    for t, taped in timeline:
        if taped is not None:
            for s in taped["signals"]:
                last[s["pool_id"]] = s
        signals = []
        for pid in pools:
            src = None
            if taped is not None:
                src = next((s for s in taped["signals"]
                            if s["pool_id"] == pid), None)
            base = src if src is not None else last.get(pid)
            if base is None:
                continue
            healthz = bool(base["healthz_ok"])
            breach = float(base["breach_rate"])
            if pid == fault_pool:
                if t >= cleared:
                    healthz = True
                if src is not None and t < cleared:
                    peak_breach = max(peak_breach,
                                      float(src["breach_rate"]))
                if t < cleared:
                    breach = max(breach, peak_breach)
                elif t < cleared + SLO_WINDOW_S:
                    breach = peak_breach       # hold the last hot value
                else:
                    breach = 0.0
            usable = healthz and pid not in quarantined
            signals.append(PoolSignal(
                pool_id=pid, url=str(base.get("url", "")), usable=usable,
                healthz_ok=healthz, breach_rate=breach,
                samples=int(base["samples"])))
        healthy = sum(1 for s in signals if s.usable)

        pending = list(logic.step(t, signals, healthy))
        idx = 0
        while idx < len(pending):
            e = pending[idx]
            idx += 1
            op = e["op"]
            if op == "quarantine":
                quarantined.add(e["pool_id"])
            elif op == "reinstate":
                quarantined.discard(e["pool_id"])
            elif op == "open":
                if open_t is None:
                    open_t = t
            elif op == "escalate":
                escalated = True
            elif op == "resolve":
                resolve_t = t
                break
            elif op == "probe":
                probes_run += 1
                ok = t >= cleared
                pending.extend(logic.record_probe(
                    t, e["pool_id"], ok,
                    ok_latency if ok else fail_latency))
        if resolve_t is not None:
            break

    result["resolved"] = resolve_t is not None
    result["escalated"] = escalated
    result["probes_run"] = probes_run
    if open_t is not None:
        result["detected_s"] = round(open_t - injected, 3)
        if resolve_t is not None:
            result["mttr_s"] = round(resolve_t - open_t, 3)
    return result
