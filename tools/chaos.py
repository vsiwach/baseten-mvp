#!/usr/bin/env python3
"""chaos.py — CHAOS-AGENT's fault-injection arsenal. Stdlib-only.

Every attack the eval agent runs goes through this tool (it is the audit
trail). Sim targets are the local pool proxies; live targets delegate to
deploy/ scripts so keys/budget guards stay in one place.

Attacks:
  inject      add latency and/or a 5xx rate to a pool (needs CHAOS_ENABLED=1
              on that pool instance)
  clear       remove all injection from a pool
  status      show a pool's current injection
  kill        kill the local pool process listening on a port (sim pod kill);
              --runpod delegates to deploy/runpod/pod.py down (REAL teardown)
  exhaust     saturate the router past a concurrency target via the bench
              harness (writes CSVs like any run — evidence included)
  drill       SCRIPTED incident drill with measured MTTR: start load, inject
              a fault through the router, watch the incident agent detect →
              quarantine → probe → reinstate → resolve, and write the whole
              timeline + MTTR to benchmarks/raw/ (the evidence chain)
  migrate     SCRIPTED KV-affinity migration drill: N sessions with fixed
              prompt prefixes, start a graceful and/or immediate migration
              (POST /v1/migrations), measure per-phase TTFT + re-prefills
              until DRAINED, write per-request + timeline + summary CSVs
  deactivate-baseten
              delegates to deploy/baseten/manage.py deactivate (REAL)
  bad-release not implemented until F5 wires live canary control — the
              release engine must exist before we can push a bad version

Examples:
  python3 tools/chaos.py inject --target http://localhost:8102 --latency-ms 500
  python3 tools/chaos.py inject --target http://localhost:8102 --error-rate 0.5
  python3 tools/chaos.py clear  --target http://localhost:8102
  python3 tools/chaos.py kill --port 8102 --yes
  python3 tools/chaos.py exhaust --router http://localhost:8090 --concurrency 32
  python3 tools/chaos.py drill --scenario latency --router http://localhost:8090
  python3 tools/chaos.py drill --suite --model glm-4.7 --latency-ms 2500
  python3 tools/chaos.py migrate --source baseten-l4 --target vllm-l4 --mode both
"""

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"POST {url} -> HTTP {e.code} "
                 "(is the pool running with CHAOS_ENABLED=1?)")
    except urllib.error.URLError as e:
        sys.exit(f"POST {url} -> {e.reason}")


def _chaos_surface(args):
    """Two audited injection surfaces:
    pool-direct (--target http://pool:PORT -> POST {target}/chaos) or
    router dev  (--router http://router:PORT --pool-id X ->
                 POST {router}/v1/dev/chaos with pool_id) — same surface the
    incident agent watches, so router-mode is preferred for invariant attacks.
    """
    if getattr(args, "pool_id", None):
        if not getattr(args, "router", None):
            sys.exit("--pool-id requires --router")
        return f"{args.router}/v1/dev/chaos", {"pool_id": args.pool_id}
    if not args.target:
        sys.exit("need --target (pool-direct) or --router + --pool-id")
    return f"{args.target}/chaos", {}


def cmd_inject(args):
    url, extra = _chaos_surface(args)
    out = _post(url, {**extra, "latency_ms": args.latency_ms,
                      "error_rate": args.error_rate})
    print(f"injected on {url}"
          f"{' pool=' + args.pool_id if extra else ''}: {out}")


def cmd_clear(args):
    url, extra = _chaos_surface(args)
    out = _post(url, {**extra, "latency_ms": 0, "error_rate": 0})
    print(f"cleared on {url}"
          f"{' pool=' + args.pool_id if extra else ''}: {out}")


def cmd_status(args):
    url = (f"{args.router}/v1/dev/chaos" if getattr(args, "pool_id", None)
           or not args.target else f"{args.target}/chaos")
    with urllib.request.urlopen(url, timeout=5) as resp:
        print(resp.read().decode())


def cmd_kill(args):
    if args.runpod:
        os.execv(sys.executable,
                 [sys.executable, os.path.join(REPO, "deploy/runpod/pod.py"),
                  "down"] + (["--yes"] if args.yes else []))
    out = subprocess.run(["lsof", "-ti", f":{args.port}"],
                         capture_output=True, text=True)
    pids = [int(p) for p in out.stdout.split()]
    if not pids:
        sys.exit(f"nothing listening on :{args.port}")
    print(f"about to SIGKILL pid(s) {pids} on :{args.port}")
    if not args.yes:
        sys.exit("killing a pool requires --yes")
    for pid in pids:
        os.kill(pid, signal.SIGKILL)
    print(f"killed — pool on :{args.port} is gone; watch the router eject it")


def cmd_exhaust(args):
    os.execv(sys.executable,
             [sys.executable, os.path.join(REPO, "benchmarks/harness.py"),
              "--router", args.router, "--model", args.model,
              "--concurrency", str(args.concurrency),
              "--duration", str(args.duration),
              "--label", f"chaos-exhaust-c{args.concurrency}"])


# ---------------------------------------------------------------------------
# drill — scripted fault → agent-resolved incident → measured MTTR evidence
# ---------------------------------------------------------------------------

SCENARIOS = {
    # magnitudes must clearly breach the watched tier's SLO; --latency-ms /
    # --error-rate override per run (realtime tier: TTFT SLO 500ms)
    "latency": {"latency_ms": 600.0, "error_rate": 0.0},
    "errors":  {"latency_ms": 0.0,   "error_rate": 0.9},
    "combo":   {"latency_ms": 600.0, "error_rate": 0.5},
}


def _get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


class _Load(threading.Thread):
    """Steady streaming chat load through the router — the traffic whose
    breach samples the incident agent detects. Streaming so injected latency
    lands in the ROUTER-measured TTFT (non-stream TTFT comes from backend
    headers, which chaos sleeps don't touch)."""

    def __init__(self, router, model, rps=3.0):
        super().__init__(daemon=True)
        self.router, self.model, self.period = router, model, 1.0 / rps
        self.stop = threading.Event()
        self.sent = 0
        self.errors = 0

    def run(self):
        while not self.stop.is_set():
            # vary the prompt so prefix-affinity spreads load across ALL
            # replicas — identical prompts would pin every request to one
            # replica and chaos on the other pool would go undetected
            body = json.dumps({"model": self.model, "max_tokens": 8,
                               "stream": True,
                               "messages": [{"role": "user",
                                             "content": f"drill traffic "
                                                        f"{self.sent}"}]
                               }).encode()
            req = urllib.request.Request(
                f"{self.router}/v1/chat/completions", data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    for _ in resp:  # drain the stream
                        pass
                self.sent += 1
            except (urllib.error.URLError, OSError):
                self.sent += 1
                self.errors += 1
            self.stop.wait(self.period)


def _drill_once(args, scenario: str) -> dict:
    router = args.router.rstrip("/")
    magnitudes = dict(SCENARIOS[scenario])
    if args.latency_ms is not None and magnitudes["latency_ms"]:
        magnitudes["latency_ms"] = args.latency_ms
    if args.error_rate is not None and magnitudes["error_rate"]:
        magnitudes["error_rate"] = args.error_rate

    caps = _get_json(f"{router}/v1/dev/chaos")["pools"]
    capable = [p["id"] for p in caps if p["capable"]]
    if not capable:
        sys.exit("no chaos-capable pools behind the router "
                 "(pools need CHAOS_ENABLED=1)")
    pool = args.pool_id or capable[0]
    if pool not in capable:
        sys.exit(f"pool {pool!r} is not chaos-capable (capable: {capable})")

    known = {i["id"] for i in _get_json(f"{router}/v1/incidents")}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    timeline: list[tuple[float, str, str]] = []
    t0 = time.monotonic()

    def mark(event, detail=""):
        timeline.append((round(time.monotonic() - t0, 2), event, detail))
        print(f"  [{timeline[-1][0]:7.2f}s] {event:12s} {detail}")

    print(f"drill '{scenario}' → pool {pool} via {router} "
          f"(model {args.model})")
    load = _Load(router, args.model, rps=args.rps)
    load.start()
    mark("load_start", f"{args.rps} rps streaming, model={args.model}")
    time.sleep(args.warmup_s)   # healthy baseline samples first

    _post(f"{router}/v1/dev/chaos", {"pool_id": pool, **magnitudes})
    mark("inject", json.dumps(magnitudes))

    incident, detected_s, quarantined_s, cleared_s = None, None, None, None
    deadline = time.monotonic() + args.timeout_s
    try:
        while time.monotonic() < deadline:
            time.sleep(0.5)
            snap = _get_json(f"{router}/v1/incidents")
            if incident is None:
                # only incidents naming OUR target pool count — an unrelated
                # flap on another pool must not be scored as this drill
                fresh = [i for i in snap
                         if i["id"] not in known and pool in i["title"]]
                if fresh:
                    incident = fresh[-1]["id"]
                    detected_s = round(time.monotonic() - t0, 2)
                    mark("detected", f"{incident}: {fresh[-1]['title']}")
            if incident is not None:
                inc = next(i for i in snap if i["id"] == incident)
                acts = " | ".join(inc["actions"])
                if quarantined_s is None and "quarantined" in acts:
                    quarantined_s = round(time.monotonic() - t0, 2)
                    mark("quarantined", "traffic spilled to healthy pool")
                # lift the fault once the agent has contained it (or
                # immediately for uncontainable last-pool cases after hold_s)
                if cleared_s is None and (
                        quarantined_s is not None
                        or time.monotonic() - t0 > args.hold_s):
                    _post(f"{router}/v1/dev/chaos",
                          {"pool_id": pool, "latency_ms": 0, "error_rate": 0})
                    cleared_s = round(time.monotonic() - t0, 2)
                    mark("cleared", "fault removed — agent must now verify")
                if not inc["live"]:
                    mark("resolved", f"MTTR {inc['mttr_s']}s "
                                     f"(agent={inc['agent']})")
                    return _drill_record(args, scenario, pool, magnitudes,
                                         stamp, timeline, load, inc,
                                         detected_s, quarantined_s, cleared_s)
        mark("timeout", f"no resolution within {args.timeout_s}s — FAIL")
        return _drill_record(args, scenario, pool, magnitudes, stamp,
                             timeline, load, None, detected_s, quarantined_s,
                             cleared_s)
    finally:
        load.stop.set()
        if cleared_s is None:  # never leave a fault armed, on ANY exit path
            _post(f"{router}/v1/dev/chaos",
                  {"pool_id": pool, "latency_ms": 0, "error_rate": 0})


def _drill_record(args, scenario, pool, magnitudes, stamp, timeline, load,
                  inc, detected_s, quarantined_s, cleared_s) -> dict:
    raw_dir = os.path.join(REPO, "benchmarks", "raw")
    os.makedirs(raw_dir, exist_ok=True)
    detail = os.path.join(raw_dir, f"chaos_drill_{scenario}_{stamp}.csv")
    with open(detail, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_rel_s", "event", "detail"])
        w.writerows(timeline)
    summary_path = os.path.join(raw_dir, "chaos_drills.csv")
    new = not os.path.exists(summary_path)
    row = {
        "stamp": stamp, "scenario": scenario, "pool": pool,
        "model": args.model, "latency_ms": magnitudes["latency_ms"],
        "error_rate": magnitudes["error_rate"],
        "agent": inc["agent"] if inc else "",
        "detected_s": detected_s, "quarantined_s": quarantined_s,
        "cleared_s": cleared_s,
        "mttr_s": inc["mttr_s"] if inc else "",
        "resolved": bool(inc), "requests": load.sent,
        "request_errors": load.errors,
    }
    with open(summary_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"  evidence: {os.path.relpath(detail, REPO)}  +  "
          f"{os.path.relpath(summary_path, REPO)}")
    return row


def cmd_drill(args):
    scenarios = list(SCENARIOS) if args.suite else [args.scenario]
    results = []
    for i, sc in enumerate(scenarios):
        if i:
            print(f"cooldown {args.cooldown_s}s (agent anti-flap window)…")
            time.sleep(args.cooldown_s)
        results.append(_drill_once(args, sc))
    failed = [r["scenario"] for r in results if not r["resolved"]]
    print("\nMTTR summary:")
    for r in results:
        status = f"{r['mttr_s']}s" if r["resolved"] else "UNRESOLVED"
        print(f"  {r['scenario']:8s} detect {r['detected_s']}s  "
              f"quarantine {r['quarantined_s']}s  mttr {status}")
    if failed:
        sys.exit(f"drill FAILED: unresolved scenarios: {failed}")


# ---------------------------------------------------------------------------
# migrate — KV-affinity migration drill with per-phase TTFT/re-prefill evidence
# ---------------------------------------------------------------------------

def _try_post(url, body):
    """Best-effort POST for cleanup paths — never sys.exit mid-teardown."""
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _pctl(vals, pct):
    """p50/p95 over floats; '' for an empty phase (honest, not fabricated)."""
    if not vals:
        return ""
    s = sorted(vals)
    return round(s[max(0, min(len(s) - 1, round(pct / 100 * len(s)) - 1))], 1)


def _session_prefix(sid: int, prefix_tokens: int) -> str:
    """Fixed per-session prefix covering the router's whole affinity window
    (prefix_tokens * ~4 chars/token) so every request in a session shares
    one prefix hash — the unit the migration steers."""
    base = (f"migration drill session {sid:02d} :: shared context block "
            "for kv reuse ") * (prefix_tokens // 4 + 2)
    return base[:prefix_tokens * 4]


def _mig_request(router, model, prompt, timeout=60):
    """One streaming chat request; measures CLIENT TTFT (first SSE data
    line) and returns the router's routing/economics headers."""
    body = json.dumps({"model": model, "max_tokens": 8, "stream": True,
                       "messages": [{"role": "user", "content": prompt}]
                       }).encode()
    req = urllib.request.Request(
        f"{router}/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            first = None
            for line in resp:
                if first is None and line.startswith(b"data:"):
                    first = time.monotonic()
            end = time.monotonic()
            h = resp.headers
            return {"ok": True,
                    "client_ttft_ms": round(((first or end) - t0) * 1000, 1),
                    "replica": h.get("X-Replica", ""),
                    "route_reason": h.get("X-Route-Reason", ""),
                    "cache": h.get("X-Cache", ""),
                    "server_ttft_ms": h.get("X-TTFT-Ms", ""),
                    "prompt_tokens": h.get("X-Prompt-Tokens", "")}
    except (urllib.error.URLError, OSError) as e:
        return {"ok": False, "error": str(e)}


class _MigrationDrill:
    """Shared drill state: current phase, the per-request evidence rows,
    session workers with staggered starts and fixed prefixes."""

    def __init__(self, args, mode):
        self.args, self.mode = args, mode
        self.router = args.router.rstrip("/")
        self.phase = "warmup"
        self.t0 = time.monotonic()
        self.rows = []
        self.errors = 0
        self._lock = threading.Lock()
        self.stop = threading.Event()

    def rel(self):
        return round(time.monotonic() - self.t0, 2)

    def record(self, sid, r):
        with self._lock:
            if not r["ok"]:
                self.errors += 1
                self.rows.append([self.rel(), sid, self.phase, self.mode,
                                  "", "", "", "", "", ""])
                return
            self.rows.append([self.rel(), sid, self.phase, self.mode,
                              r["replica"], r["route_reason"], r["cache"],
                              r["server_ttft_ms"], r["client_ttft_ms"],
                              r["prompt_tokens"]])

    def session(self, sid, start_delay):
        prefix = _session_prefix(sid, self.args.prefix_tokens)
        if self.stop.wait(start_delay):
            return
        end = time.monotonic() + self.args.session_len_s
        period = 1.0 / self.args.rps_per_session
        n = 0
        while not self.stop.is_set() and time.monotonic() < end:
            n += 1
            self.record(sid, _mig_request(self.router, self.args.model,
                                          f"{prefix} turn {n}"))
            self.stop.wait(period)


def _migrate_once(args, mode) -> dict:
    router = args.router.rstrip("/")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    drill = _MigrationDrill(args, mode)
    timeline = []

    def mark(event, detail=""):
        timeline.append((drill.rel(), event, detail))
        print(f"  [{timeline[-1][0]:7.2f}s] {event:16s} {detail}")

    print(f"migrate drill mode={mode}: {args.source} → {args.target} "
          f"via {router} (model {args.model}, {args.sessions} sessions × "
          f"{args.session_len_s:.0f}s)")
    stagger = args.warmup_s / max(1, args.sessions)
    threads = []
    for sid in range(args.sessions):
        t = threading.Thread(target=drill.session, args=(sid, sid * stagger),
                             daemon=True)
        t.start()
        threads.append(t)
    mark("load_start", f"{args.sessions} sessions staggered {stagger:.1f}s, "
                       f"{args.rps_per_session} rps each, "
                       f"prefix {args.prefix_tokens} tokens")
    time.sleep(args.warmup_s)   # warm KV on the source first

    resp = _post(f"{router}/v1/migrations",
                 {"model": args.model, "source": args.source,
                  "target": args.target, "mode": mode,
                  "weight": args.weight})
    mig_id = resp["migration_id"]
    mig_start_rel = drill.rel()
    drill.phase = "during"
    mark("migrate_start", f"{mig_id} mode={mode} weight={args.weight} "
                          f"snapshot={resp['source_snapshot']}")

    drained_s = ""
    try:
        deadline = time.monotonic() + args.timeout_s
        while time.monotonic() < deadline:
            time.sleep(1.0)
            cur = _get_json(f"{router}/v1/migrations/current")
            if cur.get("state") == "drained":
                drained_s = round(drill.rel() - mig_start_rel, 2)
                drill.phase = "drained"
                mark("drained", f"after {drained_s}s "
                                f"(routed {cur.get('routed')})")
                break
            if cur.get("state") == "idle":
                mark("vanished", "migration went idle without draining")
                break
        else:
            mark("timeout", f"never DRAINED within {args.timeout_s}s")

        if drained_s != "":
            if mode == "graceful":
                # the designed operator flow: complete once drained
                _try_post(f"{router}/v1/migrations/{mig_id}/complete", {})
                mark("complete", "graceful migration completed at DRAINED")
            drill.phase = "after"
            mark("after_probes", f"{args.sessions} probes, one per "
                                 "session prefix")
            for sid in range(args.sessions):
                drill.record(sid, _mig_request(
                    router, args.model,
                    f"{_session_prefix(sid, args.prefix_tokens)} turn after"))
            if mode == "immediate":
                # cleanup: abort lifts the sticky source quarantine the
                # immediate start set — never leave the pool excluded
                _try_post(f"{router}/v1/migrations/{mig_id}/abort", {})
                mark("abort_cleanup", "source quarantine lifted")
    finally:
        drill.stop.set()
        try:
            cur = _get_json(f"{router}/v1/migrations/current")
        except (urllib.error.URLError, OSError, ValueError):
            cur = None
        if cur and cur.get("state") in ("migrating", "drained"):
            _try_post(f"{router}/v1/migrations/{cur['id']}/abort", {})
            mark("abort_cleanup", "active migration aborted on exit")
    for t in threads:
        t.join(timeout=5)
    return _migrate_record(args, mode, stamp, drill, timeline, drained_s)


def _migrate_record(args, mode, stamp, drill, timeline, drained_s) -> dict:
    raw_dir = os.path.join(REPO, "benchmarks", "raw")
    os.makedirs(raw_dir, exist_ok=True)
    detail = os.path.join(raw_dir, f"migration_{mode}_{stamp}.csv")
    with open(detail, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_rel_s", "session_id", "phase", "mode", "replica",
                    "route_reason", "cache", "server_ttft_ms",
                    "client_ttft_ms", "prompt_tokens"])
        w.writerows(drill.rows)
    tl_path = os.path.join(raw_dir, f"migration_timeline_{mode}_{stamp}.csv")
    with open(tl_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_rel_s", "event", "detail"])
        w.writerows(timeline)

    def phase_ttfts(phase):
        return [r[8] for r in drill.rows if r[2] == phase and r[8] != ""]

    row = {"stamp": stamp, "mode": mode}
    for ph in ("warmup", "during", "drained", "after"):
        vals = phase_ttfts(ph)
        row[f"{ph}_ttft_p50_ms"] = _pctl(vals, 50)
        row[f"{ph}_ttft_p95_ms"] = _pctl(vals, 95)
    # re-prefills: ONLY sessions that were already warm when the migration
    # started and are then forced to recompute their prefix on the TARGET.
    # New sessions' first prefills happen wherever they land and are counted
    # separately — conflating the two hides the graceful-vs-immediate story.
    warm_sessions = {r[1] for r in drill.rows if r[2] == "warmup"}
    migrated_cold = [
        r for r in drill.rows
        if r[2] in ("during", "drained", "after")
        and r[4] == args.target and r[6] == "miss"]
    row["re_prefill_count"] = sum(
        1 for r in migrated_cold if r[1] in warm_sessions)
    row["new_session_first_prefills"] = sum(
        1 for r in migrated_cold if r[1] not in warm_sessions)
    # The customer-facing cohort: sessions HOMED ON THE SOURCE at migration
    # start (the two-pool ring homes ~half the sessions on the target
    # natively — those never migrate and must not dilute the comparison).
    # For this cohort, mid-conversation experience is the whole story:
    # graceful should show zero live misses; immediate shows one forced
    # re-prefill per session, mid-conversation.
    src_homed = {r[1] for r in drill.rows
                 if r[2] == "warmup" and r[4] == args.source}
    cohort_live = [r for r in drill.rows
                   if r[2] in ("during", "drained") and r[1] in src_homed]
    cohort_ttft = [r[8] for r in cohort_live if r[8] != ""]
    cohort_miss = [r[8] for r in cohort_live
                   if r[6] == "miss" and r[8] != ""]
    cohort_hit = [r[8] for r in cohort_live
                  if r[6] == "hit" and r[8] != ""]
    row["cohort_sessions"] = len(src_homed)
    row["cohort_live_requests"] = len(cohort_live)
    row["cohort_mid_conversation_re_prefills"] = len(cohort_miss)
    row["cohort_ttft_p95_ms"] = _pctl(cohort_ttft, 95)
    row["cohort_hit_ttft_p50_ms"] = _pctl(cohort_hit, 50)
    row["cohort_miss_ttft_p50_ms"] = _pctl(cohort_miss, 50)
    row["drained_s"] = drained_s
    row["requests"] = len(drill.rows)
    row["errors"] = drill.errors
    summary = os.path.join(raw_dir, "migration_drills.csv")
    new = not os.path.exists(summary)
    with open(summary, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"  evidence: {os.path.relpath(detail, REPO)}  +  "
          f"{os.path.relpath(tl_path, REPO)}  +  "
          f"{os.path.relpath(summary, REPO)}")
    return row


def cmd_migrate(args):
    modes = ["graceful", "immediate"] if args.mode == "both" else [args.mode]
    results = []
    for i, mode in enumerate(modes):
        if i:
            print(f"cooldown {args.cooldown_s}s between modes…")
            time.sleep(args.cooldown_s)
        results.append(_migrate_once(args, mode))
    print("\nmigration drill summary:")
    for r in results:
        drained = f"{r['drained_s']}s" if r["drained_s"] != "" else "NEVER"
        print(f"  {r['mode']:9s} drained {drained:>8s}  "
              f"cohort({r['cohort_sessions']} src-homed sessions): "
              f"mid-conversation re-prefills {r['cohort_mid_conversation_re_prefills']}, "
              f"ttft p95 {r['cohort_ttft_p95_ms']}ms "
              f"(hit p50 {r['cohort_hit_ttft_p50_ms']} / miss p50 {r['cohort_miss_ttft_p50_ms']})  "
              f"requests {r['requests']}  errors {r['errors']}")
    if any(r["mode"] == "graceful" and r["drained_s"] == "" for r in results):
        sys.exit("migrate FAILED: graceful migration never reached DRAINED "
                 f"within --timeout-s {args.timeout_s}")


def cmd_deactivate_baseten(args):
    argv = [sys.executable, os.path.join(REPO, "deploy/baseten/manage.py"),
            "deactivate", args.deployment_id, "--model-id", args.model_id]
    if args.yes:
        argv.append("--yes")
    os.execv(sys.executable, argv)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("inject")
    i.add_argument("--target", help="pool base URL (pool-direct mode)")
    i.add_argument("--router", help="router base URL (router dev-chaos mode)")
    i.add_argument("--pool-id", help="pool id for router dev-chaos mode")
    i.add_argument("--latency-ms", type=float, default=0.0)
    i.add_argument("--error-rate", type=float, default=0.0)
    i.set_defaults(fn=cmd_inject)

    for name, fn in (("clear", cmd_clear), ("status", cmd_status)):
        c = sub.add_parser(name)
        c.add_argument("--target", help="pool base URL (pool-direct mode)")
        c.add_argument("--router", help="router base URL")
        c.add_argument("--pool-id", help="pool id for router dev-chaos mode")
        c.set_defaults(fn=fn)

    k = sub.add_parser("kill")
    k.add_argument("--port", type=int)
    k.add_argument("--runpod", action="store_true")
    k.add_argument("--yes", action="store_true")
    k.set_defaults(fn=cmd_kill)

    e = sub.add_parser("exhaust")
    e.add_argument("--router", default="http://localhost:8090")
    e.add_argument("--model", default="qwen3-8b")
    e.add_argument("--concurrency", type=int, default=32)
    e.add_argument("--duration", type=float, default=20.0)
    e.set_defaults(fn=cmd_exhaust)

    dr = sub.add_parser("drill", help="scripted incident drill with "
                                      "measured MTTR evidence")
    dr.add_argument("--router", default="http://localhost:8090")
    dr.add_argument("--scenario", choices=sorted(SCENARIOS),
                    default="latency")
    dr.add_argument("--suite", action="store_true",
                    help="run every scenario back to back")
    dr.add_argument("--pool-id", help="target pool (default: first "
                                      "chaos-capable pool)")
    dr.add_argument("--model", default="qwen3-8b",
                    help="model to load-test — must be the model the "
                         "incident agent watches (DEVBOARD_MODEL)")
    dr.add_argument("--latency-ms", type=float, default=None,
                    help="override scenario latency (must breach the "
                         "tier's TTFT SLO to be detectable)")
    dr.add_argument("--error-rate", type=float, default=None)
    dr.add_argument("--rps", type=float, default=1.0,
                    help="drill load; keep low against LIVE pools — hosted "
                         "Model APIs enforce request quotas, and tripping "
                         "them mid-drill poisons probe verification")
    dr.add_argument("--warmup-s", type=float, default=4.0)
    dr.add_argument("--hold-s", type=float, default=25.0,
                    help="clear the fault after this long even without "
                         "quarantine (last-pool cases)")
    dr.add_argument("--timeout-s", type=float, default=150.0)
    dr.add_argument("--cooldown-s", type=float, default=35.0,
                    help="gap between suite scenarios (> agent cooldown)")
    dr.set_defaults(fn=cmd_drill)

    mg = sub.add_parser("migrate", help="KV-affinity migration drill: "
                                        "sessioned prefix load, graceful "
                                        "and/or immediate migration, "
                                        "per-phase TTFT + re-prefill CSVs")
    mg.add_argument("--router", default="http://localhost:8090")
    mg.add_argument("--model", default="qwen3-8b")
    mg.add_argument("--source", default="baseten-l4")
    mg.add_argument("--target", default="vllm-l4",
                    help="needs the two-pool drill overlay: "
                         "ROUTING_POLICY_SRC=configs/routing-policy.drill.yaml "
                         "KV_TTL_S=20 ./scripts/run_local_stack.sh")
    mg.add_argument("--mode", choices=["graceful", "immediate", "both"],
                    default="both",
                    help="both = graceful then immediate, sequential")
    mg.add_argument("--sessions", type=int, default=12)
    mg.add_argument("--session-len-s", type=float, default=90.0,
                    help="per-session lifetime; starts are staggered "
                         "across --warmup-s")
    mg.add_argument("--prefix-tokens", type=int, default=32,
                    help="fixed shared prefix per session (>= the router's "
                         "affinity prefix_tokens so the whole hash window "
                         "is covered)")
    mg.add_argument("--rps-per-session", type=float, default=0.5)
    mg.add_argument("--weight", type=float, default=1.0,
                    help="share of new prefixes steered to target, (0,1]")
    mg.add_argument("--warmup-s", type=float, default=20.0)
    mg.add_argument("--timeout-s", type=float, default=240.0,
                    help="graceful must reach DRAINED within this or the "
                         "drill exits nonzero (allow session-len-s + the "
                         "router's KV TTL + slack)")
    mg.add_argument("--cooldown-s", type=float, default=10.0)
    mg.set_defaults(fn=cmd_migrate)

    d = sub.add_parser("deactivate-baseten")
    d.add_argument("deployment_id")
    d.add_argument("--model-id", required=True)
    d.add_argument("--yes", action="store_true")
    d.set_defaults(fn=cmd_deactivate_baseten)

    b = sub.add_parser("bad-release")
    b.set_defaults(fn=lambda a: sys.exit(
        "bad-release arms in F5 when the release engine takes live pushes"))

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
