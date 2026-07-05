"""Router — the single public entrypoint for inference.

Request flow for POST /v1/predict?model=M&tier=T:
  cache -> healthy candidates from registry+policy -> tier-policy pick ->
  proxy -> record latency/cost -> X-Cache / X-Backend / X-Est-Cost headers.
Batch tier requests are enqueued instead (see batch.py, /v1/batch routes).
Config hot-reloads on SIGHUP. No per-model logic anywhere in this package.
"""

import json
import os
import signal
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from router_app import config as cfg
from router_app import devboard
from router_app.batch import BatchQueue, BatchWorker
from router_app.cache import TTLCache, cache_key
from router_app.costs import CostLedger
from router_app.autoscaler import AutoScaler, AutoscaleConfig
from router_app.events import EventLog
from router_app.health import HealthPoller
from router_app.incidents import IncidentStore
from router_app.kvstate import KVState
from router_app.metrics import MetricsWindow
from router_app.placement import eligible_pools
from router_app.policy import (NoHealthyBackend, UnknownModel, resolve_tier,
                               select, select_replica)

ROUTER_VERSION = "1.0"
FORWARDED_HEADERS = ("token",)


class RouterState:
    def __init__(self, registry_path: Path | None = None,
                 policy_path: Path | None = None):
        self.registry_path = registry_path
        self.policy_path = policy_path
        self.ledger = CostLedger()
        self.events = EventLog()
        self.metrics = MetricsWindow()
        self.incidents = IncidentStore(emit=self.events.emit)
        self.release = None            # F5 wires live canary control
        # ground-truth fault windows written by /v1/dev/chaos — the incident
        # agent's tape recorder reads these to attach replayable tapes to
        # resolved-incident episodes (learning.py / replay.py)
        self.chaos_windows: dict[str, dict] = {}
        self.goodput_curves = self._load_goodput_curves()
        self.reload()
        self.poller = HealthPoller(
            get_endpoints=lambda: self.policy["endpoints"],
            interval_s=float(os.environ.get("HEALTH_POLL_INTERVAL_S", "10")),
        )
        queue_dir = Path(os.environ.get("ROUTER_QUEUE_DIR",
                                        "/tmp/router-batch-queue"))
        self.queue = BatchQueue(queue_dir)
        concurrency = int(self.policy["tiers"].get("batch", {})
                          .get("concurrency", 2))
        self.worker = BatchWorker(self.queue, self.process_batch_job,
                                  concurrency=concurrency)

    def reload(self) -> None:
        self.registry = cfg.load_registry(self.registry_path)
        self.policy = cfg.load_policy(self.policy_path)
        cache_cfg = self.policy["cache"]
        self.cache = TTLCache(ttl_s=float(cache_cfg.get("ttl_s", 300)),
                              enabled=bool(cache_cfg.get("enabled", True)))
        # KV/prefix state shared across reloads would lose warmth; keep it if
        # present, else create with the configured TTL.
        ttl = float(cache_cfg.get("ttl_s", 300))
        if getattr(self, "kvstate", None) is None:
            self.kvstate = KVState(kv_ttl_s=ttl)
        else:
            self.kvstate.kv_ttl_s = ttl
        self.placement = cfg.load_placement()
        if getattr(self, "autoscalers", None) is None:
            self.autoscalers = {}  # model -> AutoScaler (created on first use)

    @staticmethod
    def _load_goodput_curves() -> dict:
        """Measured goodput curves from the bench harness artifact — never
        synthesized. Empty until benchmarks run (the board shows no curve)."""
        path = Path(os.environ.get("GOODPUT_CURVES_PATH",
                                   "benchmarks/goodput.json"))
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def devboard_model(self) -> str | None:
        """The LLM model the devboard watches: DEVBOARD_MODEL env, else the
        first chat backend with endpoints in the routing policy."""
        configured = os.environ.get("DEVBOARD_MODEL")
        if configured:
            return configured
        for engines in (("baseten", "vllm"), ("baseten-api",), ("max",)):
            for name, entry in self.registry.items():
                if entry.get("engine") in engines and \
                        self.policy["endpoints"].get(name):
                    return name
        return None

    def _autoscaler(self, model: str) -> AutoScaler:
        if model not in self.autoscalers:
            entry = self.registry.get(model, {})
            scale_to_zero = str(entry.get("scale_to_zero", "true")) == "true"
            self.autoscalers[model] = AutoScaler(
                AutoscaleConfig(
                    cold_start_s=float(entry.get("cold_start_s", 8.0)),
                    min_warm=0 if scale_to_zero else 1,
                    max_replicas=int(entry.get("max_replicas", 3))),
                emit=lambda kind, **f: self.events.emit(kind, model=model, **f))
        return self.autoscalers[model]

    def _select_for_chat(self, model: str, body: dict,
                         region: str | None, compliance: str | None,
                         exclude: set | None = None):
        """Shared selection for the chat paths: placement + affinity +
        autoscale signal. `exclude` drops replica ids already tried this
        request so 5xx failover can't re-pick the same sick pool through
        prefix affinity. Returns (choice, tier, tier_rules, decide_ms,
        prompt). Raises UnknownModel / NoHealthyBackend."""
        if model not in self.registry:
            raise UnknownModel(model)
        replicas = cfg.replicas_for(self.policy, model)
        if not replicas:
            raise NoHealthyBackend(model)
        prompt = "\n".join(m.get("content", "")
                           for m in body.get("messages", []))
        tier = self.registry[model].get("tier", "realtime")
        tier_rules = self.policy["tiers"].get(tier, {})
        affinity = self.policy.get("affinity", {})

        # Layer 1 — placement: which capacity pools may serve this request.
        # Replicas declare a `pool` only when placement is in use; otherwise the
        # filter is a no-op (back-compat with the single-pool local demo).
        placement_filter = None
        if self.placement.get("pools") and (region or compliance):
            allowed = {p["id"] for p in eligible_pools(
                {"region": region, "compliance": compliance}, self.placement)}
            self.events.emit("placement", model=model, region=region,
                             compliance=compliance, eligible_pools=sorted(allowed))
            placement_filter = lambda c: c.get("pool") is None or c["pool"] in allowed
        if exclude:
            base_filter = placement_filter
            placement_filter = lambda c: c["id"] not in exclude and (
                base_filter is None or base_filter(c))

        # autoscale signal: in-flight requests for this model right now
        pending = sum(self.kvstate.pending(r["id"]) for r in replicas) + 1
        self._autoscaler(model).step(time.monotonic(), pending)

        decide_start = time.monotonic()
        choice = select_replica(
            prompt, replicas, is_usable=lambda u: self.poller.status_for(u).usable,
            kvstate=self.kvstate, tier_rules=tier_rules,
            cost_of=lambda p: float(self.policy["cost_table"].get(p, 0.0)),
            affinity_cfg=affinity, capacity=int(affinity.get("capacity", 8)),
            latency_of=lambda u: self.poller.status_for(u).p50_ms,
            placement_filter=placement_filter)
        decide_ms = round((time.monotonic() - decide_start) * 1000, 2)
        return choice, tier, tier_rules, decide_ms, prompt

    def _record_chat(self, model: str, choice, tier: str, tier_rules: dict,
                     decide_ms: float, *, ttft: float, decode_ms: float,
                     tps: float, cost: float, prompt_tokens: int,
                     completion_tokens: int, backend_hit: bool,
                     tag: str | None, http_ok: bool = True) -> None:
        """One bookkeeping path for both chat modes: ledger, metrics window,
        route/breach events. A 5xx from the backend is an SLO violation by
        definition — the incident agent keys off these samples."""
        tpot = round(decode_ms / completion_tokens, 2) if completion_tokens \
            else 0.0
        slo_ttft = tier_rules.get("ttft_ms")
        slo_tpot = tier_rules.get("tpot_ms")
        ttft_ok = http_ok and (slo_ttft is None or ttft <= slo_ttft)
        tpot_ok = http_ok and (slo_tpot is None or tpot <= slo_tpot)
        self.ledger.record_llm(
            model, choice.provider, est_cost_usd=cost,
            cache_hit=choice.cache_hit or backend_hit, ttft_ms=ttft,
            tokens_per_sec=tps, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            slo_met=ttft_ok and tpot_ok)
        self.metrics.record(
            model=model, replica=choice.replica_id, provider=choice.provider,
            ttft_ms=ttft, tpot_ms=tpot, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens, est_cost_usd=cost,
            ttft_slo_met=ttft_ok, tpot_slo_met=tpot_ok)
        self.events.emit("route", model=model, replica=choice.replica_id,
                         provider=choice.provider, cache_hit=choice.cache_hit,
                         reason=choice.reason, ttft_ms=round(ttft, 1),
                         tpot_ms=tpot,
                         req=f"#{self.events.seq() % 10000:04d}",
                         wl_tier=tier, tag=tag, decide_ms=decide_ms,
                         iso_ts=time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                              time.gmtime()))
        if not (ttft_ok and tpot_ok):
            # feeds the devboard's self-serve incident management
            self.events.emit("slo_breach", model=model,
                             replica=choice.replica_id, ttft_ms=round(ttft, 1),
                             tpot_ms=tpot, slo_ttft_ms=slo_ttft,
                             slo_tpot_ms=slo_tpot, tier=tier,
                             remediation="scale up / reroute / roll back")

    def _chat_attempts(self, model: str) -> int:
        return max(1, len(self.policy["endpoints"].get(model, [])))

    def proxy_chat(self, model: str, body: dict, headers: dict,
                   region: str | None = None, compliance: str | None = None):
        """Non-streaming chat: forward, record LLM economics, return
        (httpx.Response, ReplicaChoice). A replica that can't be reached is
        marked unhealthy and the NEXT one is tried (failover, like
        /v1/predict always had) — one sick pool never becomes a client 502
        while a healthy pool exists. Raises UnknownModel /
        NoHealthyBackend."""
        last_error: Exception | None = None
        last_resp = last_choice = None
        tried: set = set()
        for _ in range(self._chat_attempts(model)):
            choice, tier, tier_rules, decide_ms, _ = self._select_for_chat(
                model, body, region, compliance, exclude=tried)
            self.kvstate.inc_pending(choice.replica_id)
            try:
                fwd = {k: v for k, v in headers.items()
                       if k.lower() in FORWARDED_HEADERS}
                try:
                    resp = httpx.post(f"{choice.url}/v1/chat/completions",
                                      json=body, headers=fwd, timeout=120)
                except httpx.HTTPError as exc:
                    self.poller.mark_unhealthy(choice.url)
                    self.events.emit("failover", model=model,
                                     replica=choice.replica_id,
                                     error=str(exc))
                    tried.add(choice.replica_id)
                    last_error = exc
                    continue
                ttft = float(resp.headers.get("X-TTFT-Ms", 0.0))
                decode_ms = float(resp.headers.get("X-Decode-Ms", 0.0))
                tps = float(resp.headers.get("X-Tokens-Per-Sec", 0.0))
                cost = float(resp.headers.get("X-Est-Cost", 0.0))
                prompt_tokens = int(resp.headers.get("X-Prompt-Tokens", 0))
                completion_tokens = int(
                    resp.headers.get("X-Completion-Tokens", 0))
                backend_hit = resp.headers.get("X-Cache") == "hit"
            finally:
                self.kvstate.dec_pending(choice.replica_id)
            # record what the replica now holds (warm + prefix cached)
            self.kvstate.record_prefix(choice.replica_id, choice.prefix)
            # 429 is an SLO violation by definition (the pool is refusing
            # capacity) — it must feed breach detection, not hide under
            # "http_ok" (FRICTION_LOG #10 made this failure mode invisible)
            self._record_chat(model, choice, tier, tier_rules, decide_ms,
                              ttft=ttft, decode_ms=decode_ms, tps=tps,
                              cost=cost, prompt_tokens=prompt_tokens,
                              completion_tokens=completion_tokens,
                              backend_hit=backend_hit, tag=compliance,
                              http_ok=resp.status_code < 500
                              and resp.status_code != 429)
            if resp.status_code < 500:
                return resp, choice
            # backend 5xx: the sample is recorded against the sick pool —
            # now try a different replica instead of punting to the client
            tried.add(choice.replica_id)
            last_resp, last_choice = resp, choice
        if last_resp is not None:
            return last_resp, last_choice   # every replica 5xx'd: be honest
        raise NoHealthyBackend(f"{model}: all replicas failed "
                               f"({last_error})")

    def proxy_chat_stream(self, model: str, body: dict, headers: dict,
                          region: str | None = None,
                          compliance: str | None = None):
        """Streaming chat: returns (line_generator, choice). Tokens flow to
        the client AS the backend emits them — the router adds selection, not
        buffering (client TTFT ≈ backend TTFT). Economics come from backend
        headers when present (sim), else are measured here and costed from
        the provider's $/1M-output-token entry in cost_table (live pools)."""
        fwd = {k: v for k, v in headers.items()
               if k.lower() in FORWARDED_HEADERS}
        # Open the upstream response BEFORE returning so its headers (the
        # sim's economics) can be forwarded on our own response; the body
        # still streams token by token through the generator below. A replica
        # failing at connect is marked unhealthy and the next one is tried —
        # failover happens while the stream is still uncommitted.
        tried: set = set()
        for _ in range(self._chat_attempts(model)):
            choice, tier, tier_rules, decide_ms, _ = self._select_for_chat(
                model, body, region, compliance, exclude=tried)
            self.kvstate.inc_pending(choice.replica_id)
            t0 = time.monotonic()
            ctx = httpx.stream("POST", f"{choice.url}/v1/chat/completions",
                               json=body, headers=fwd, timeout=120)
            try:
                upstream = ctx.__enter__()
            except httpx.HTTPError as exc:
                self.kvstate.dec_pending(choice.replica_id)
                self.poller.mark_unhealthy(choice.url)
                self.events.emit("failover", model=model,
                                 replica=choice.replica_id, error=str(exc))
                tried.add(choice.replica_id)
                continue
            if upstream.status_code >= 500:
                # stream not yet committed to the client — record the breach
                # against this pool and try another replica
                ctx.__exit__(None, None, None)
                self.kvstate.dec_pending(choice.replica_id)
                self._record_chat(model, choice, tier, tier_rules, decide_ms,
                                  ttft=0.0, decode_ms=0.0, tps=0.0, cost=0.0,
                                  prompt_tokens=0, completion_tokens=0,
                                  backend_hit=False, tag=compliance,
                                  http_ok=False)
                self.events.emit("failover", model=model,
                                 replica=choice.replica_id,
                                 error=f"upstream {upstream.status_code}")
                tried.add(choice.replica_id)
                continue
            break
        else:
            raise NoHealthyBackend(f"{model}: all replicas unreachable "
                                   "or failing")
        hdrs = upstream.headers

        def stream():
            first = None
            chunks = 0
            try:
                for line in upstream.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:") and "[DONE]" not in line:
                        if first is None:
                            first = time.monotonic()
                        chunks += 1
                    yield f"{line}\n\n"
            except httpx.HTTPError as exc:
                self.poller.mark_unhealthy(choice.url)
                yield ("data: " + json.dumps(
                    {"error": {"type": "backend_error",
                               "message": str(exc)}}) + "\n\n")
            finally:
                ctx.__exit__(None, None, None)
                self.kvstate.dec_pending(choice.replica_id)
                t_end = time.monotonic()
                measured_ttft = ((first or t_end) - t0) * 1000.0
                measured_decode = ((t_end - first) * 1000.0) if first else 0.0
                completion_tokens = int(hdrs.get("X-Completion-Tokens",
                                                 0) or 0) or chunks
                cost = float(hdrs.get("X-Est-Cost", 0.0) or 0.0)
                if not cost and completion_tokens:
                    per_mtok = float(
                        self.policy["cost_table"].get(choice.provider, 0.0))
                    cost = completion_tokens / 1_000_000 * per_mtok
                total_s = t_end - t0
                self.kvstate.record_prefix(choice.replica_id, choice.prefix)
                # ttft/decode are ROUTER-measured: they include queueing and
                # network, which is what the client actually experienced.
                self._record_chat(
                    model, choice, tier, tier_rules, decide_ms,
                    ttft=round(measured_ttft, 1),
                    decode_ms=round(measured_decode, 1),
                    tps=round(completion_tokens / total_s, 2)
                    if total_s > 0 else 0.0,
                    cost=cost,
                    prompt_tokens=int(hdrs.get("X-Prompt-Tokens", 0) or 0),
                    completion_tokens=completion_tokens,
                    backend_hit=hdrs.get("X-Cache") == "hit",
                    tag=compliance,
                    http_ok=upstream.status_code < 500
                    and upstream.status_code != 429)

        return stream(), choice, hdrs, upstream.status_code

    # ---- core proxy path (shared by live predict and batch worker) ----

    def call_backend(self, model: str, tier_param: str | None,
                     payload: dict, headers: dict) -> tuple[dict, "object"]:
        """Returns (response_json, Choice). Raises UnknownModel /
        NoHealthyBackend. Failing endpoints are marked unhealthy and the
        next candidate is tried."""
        attempts = len(self.policy["endpoints"].get(model, [])) or 1
        last_error: Exception | None = None
        for _ in range(attempts):
            choice = select(model, tier_param, self.registry, self.policy,
                            self.poller.status_for)
            tier_rules = self.policy["tiers"].get(choice.tier, {})
            max_ms = tier_rules.get("max_latency_ms")
            timeout_s = (max_ms / 1000) if max_ms else 30.0
            start = time.monotonic()
            try:
                resp = httpx.post(
                    f"{choice.url}/v1/predict", json=payload,
                    headers={k: v for k, v in headers.items()
                             if k.lower() in FORWARDED_HEADERS},
                    timeout=timeout_s,
                )
                latency_ms = (time.monotonic() - start) * 1000
            except httpx.HTTPError as exc:
                self.poller.mark_unhealthy(choice.url)
                last_error = exc
                continue
            self.poller.record_latency(choice.url, latency_ms)
            if resp.status_code >= 500:
                self.poller.mark_unhealthy(choice.url)
                last_error = NoHealthyBackend(f"{choice.url} -> {resp.status_code}")
                continue
            self.ledger.record(model, choice.provider, choice.est_cost_usd,
                               latency_ms)
            body = resp.json() if resp.status_code == 200 else {
                "status_code": resp.status_code, "detail": resp.json()}
            if resp.status_code != 200:
                # backend rejected the request (auth/validation) — not a
                # routing failure; surface as-is without caching
                raise BackendRejection(resp.status_code, body["detail"])
            return body, choice
        raise NoHealthyBackend(str(last_error) if last_error else model)

    def process_batch_job(self, job: dict) -> dict:
        body, choice = self.call_backend(job["model"], "batch",
                                         job["payload"], job["headers"])
        return {"prediction": body, "backend": choice.provider,
                "est_cost_usd": choice.est_cost_usd}


class BackendRejection(Exception):
    def __init__(self, status_code: int, detail):
        self.status_code = status_code
        self.detail = detail


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message,
                                           **extra}})


def get_app(registry_path: Path | None = None,
            policy_path: Path | None = None,
            start_background: bool = True) -> FastAPI:
    state = RouterState(registry_path, policy_path)
    app = FastAPI(title="inference-router", version=ROUTER_VERSION)
    app.state.router_state = state

    if start_background:
        state.poller.start()
        state.worker.start()
        # Governed incident agent (quarantine/probe/reinstate/resolve only).
        # INCIDENT_AGENT=0 runs manual-baseline drills — the MTTR contrast.
        if os.environ.get("INCIDENT_AGENT", "1") == "1":
            from router_app.incident_agent import IncidentAgentRunner
            state.incident_agent = IncidentAgentRunner(
                state, interval_s=float(
                    os.environ.get("INCIDENT_AGENT_INTERVAL_S", "2")))
            state.incident_agent.start()
        try:  # SIGHUP hot-reload (unavailable in some test harnesses)
            signal.signal(signal.SIGHUP, lambda *_: state.reload())
        except ValueError:
            pass

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "degraded": state.poller.degraded()}

    @app.get("/v1/info")
    def info():
        return {"model": "router", "version": ROUTER_VERSION,
                "tier": "realtime", "target": "cpu",
                "capabilities": ["predict", "chat", "kv_affinity", "autoscale",
                                 "placement", "failover", "release",
                                 "costs", "events"]}

    @app.post("/v1/predict")
    async def predict(request: Request,
                      model: str = Query(...),
                      tier: str | None = Query(default=None)):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _error(400, "invalid_json", "request body must be JSON")
        headers = dict(request.headers)

        try:
            resolved = resolve_tier(model, tier, state.registry, state.policy)
            tier_rules = state.policy["tiers"].get(resolved, {})
        except UnknownModel:
            return _error(404, "unknown_model",
                          f"model '{model}' is not in inference-registry.yaml",
                          model=model)

        if tier_rules.get("queue"):
            job_id = state.queue.submit(model, payload, {
                k: v for k, v in headers.items()
                if k.lower() in FORWARDED_HEADERS})
            return JSONResponse(status_code=202, content={
                "job_id": job_id, "status": "pending",
                "poll": f"/v1/batch/{job_id}"})

        key = cache_key(model, payload)
        cached = state.cache.get(key)
        if cached is not None:
            entry = json.loads(cached)
            state.ledger.record(model, entry["provider"], 0.0, cached=True)
            return JSONResponse(content=entry["body"], headers={
                "X-Cache": "hit", "X-Backend": entry["provider"],
                "X-Est-Cost": "0"})

        try:
            body, choice = state.call_backend(model, tier, payload, headers)
        except UnknownModel:
            return _error(404, "unknown_model",
                          f"model '{model}' is not in inference-registry.yaml",
                          model=model)
        except NoHealthyBackend as exc:
            return _error(503, "no_healthy_backend",
                          f"no healthy backend for model '{model}': {exc}",
                          model=model)
        except BackendRejection as exc:
            return JSONResponse(status_code=exc.status_code,
                                content=exc.detail if isinstance(exc.detail, dict)
                                else {"detail": exc.detail})

        state.cache.put(key, json.dumps(
            {"body": body, "provider": choice.provider}).encode())
        return JSONResponse(content=body, headers={
            "X-Cache": "miss", "X-Backend": choice.provider,
            "X-Est-Cost": f"{choice.est_cost_usd:.10f}"})

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request,
                               model: str = Query(default=None),
                               region: str = Query(default=None),
                               compliance: str = Query(default=None)):
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _error(400, "invalid_json", "request body must be JSON")
        model = model or body.get("model")
        from fastapi.concurrency import run_in_threadpool
        try:
            if body.get("stream"):
                # tokens flow as the backend emits them; bookkeeping happens
                # when the stream closes (inside the generator). Selection +
                # the blocking upstream connect run OFF the event loop — a
                # slow pool must never stall every other request + /healthz.
                gen, choice, up_hdrs, up_status = await run_in_threadpool(
                    state.proxy_chat_stream, model, body,
                    dict(request.headers), region, compliance)
                out_headers = {"X-Backend": choice.provider,
                               "X-Replica": choice.replica_id,
                               "X-Route-Reason": choice.reason}
                for h in ("X-TTFT-Ms", "X-Decode-Ms", "X-Tokens-Per-Sec",
                          "X-Est-Cost", "X-Prompt-Tokens",
                          "X-Completion-Tokens", "X-Cache"):
                    if h in up_hdrs:
                        out_headers[h] = up_hdrs[h]
                return StreamingResponse(
                    gen, media_type="text/event-stream",
                    status_code=up_status, headers=out_headers)
            resp, choice = await run_in_threadpool(
                state.proxy_chat, model, body, dict(request.headers),
                region, compliance)
        except UnknownModel:
            return _error(404, "unknown_model",
                          f"model '{model}' is not in inference-registry.yaml",
                          model=model)
        except NoHealthyBackend as exc:
            return _error(503, "no_healthy_backend",
                          f"no healthy replica for model '{model}': {exc}",
                          model=model)
        except httpx.HTTPError as exc:
            return _error(502, "backend_error", f"chat backend failed: {exc}",
                          model=model)
        headers = {
            "X-Backend": choice.provider, "X-Replica": choice.replica_id,
            "X-Cache": "hit" if choice.cache_hit else "miss",
            "X-Route-Reason": choice.reason,
        }
        # forward backend economics so clients (bench harness) can log the
        # same numbers the router recorded — one provenance chain end to end
        for h in ("X-TTFT-Ms", "X-Decode-Ms", "X-Tokens-Per-Sec",
                  "X-Est-Cost", "X-Prompt-Tokens", "X-Completion-Tokens"):
            if h in resp.headers:
                headers[h] = resp.headers[h]
        media = resp.headers.get("content-type", "application/json")
        if media.startswith("text/event-stream"):
            return Response(content=resp.content, media_type=media,
                            status_code=resp.status_code, headers=headers)
        try:
            payload = resp.json()
        except ValueError:
            payload = {"error": {"type": "backend_error",
                                 "message": resp.text[:300]}}
        # the backend's status IS the client's status — a 5xx/429 must
        # never be laundered into a 200 (staff-skeptic finding)
        return JSONResponse(content=payload, status_code=resp.status_code,
                            headers=headers)

    @app.get("/v1/events")
    def events(limit: int = 100, kind: str | None = None):
        return {"events": state.events.recent(limit, kind),
                "counts": state.events.kinds()}

    # ---- config-as-UX: the policy stays the source of truth; the devboard is
    # a lens that can read it and propose changes that take effect live. ----
    @app.get("/v1/policy/placement")
    def get_placement():
        return state.placement

    @app.post("/v1/policy/placement")
    async def set_placement(request: Request):
        new_policy = await request.json()
        state.placement = new_policy            # applies to the next request
        state.events.emit("config_change", target="placement-policy",
                          pools=[p.get("id") for p in new_policy.get("pools", [])])
        return {"status": "applied", "pools": len(new_policy.get("pools", []))}

    @app.get("/v1/simulate/route")
    def simulate_route(region: str | None = None, compliance: str | None = None):
        """'What would route where' — eligible capacity for a hypothetical
        request under the CURRENT placement policy, without sending traffic."""
        from router_app.placement import eligible_pools
        pools = eligible_pools({"region": region, "compliance": compliance},
                               state.placement)
        return {"region": region, "compliance": compliance,
                "eligible_pools": [{"id": p["id"], "region": p.get("region"),
                                    "sensitive": "sensitive" in p.get("tags", [])}
                                   for p in pools]}

    @app.post("/v1/batch")
    async def submit_batch(request: Request, model: str = Query(...)):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _error(400, "invalid_json", "request body must be JSON")
        if model not in state.registry:
            return _error(404, "unknown_model",
                          f"model '{model}' is not in inference-registry.yaml",
                          model=model)
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() in FORWARDED_HEADERS}
        job_id = state.queue.submit(model, payload, headers)
        return JSONResponse(status_code=202, content={
            "job_id": job_id, "status": "pending",
            "poll": f"/v1/batch/{job_id}"})

    @app.get("/v1/batch/{job_id}")
    def batch_status(job_id: str):
        job = state.queue.get(job_id)
        if job is None:
            return _error(404, "unknown_job", f"no job '{job_id}'")
        return {"job_id": job["id"], "status": job["status"],
                "result": job["result"], "error": job["error"]}

    @app.get("/v1/costs")
    def costs():
        snap = state.ledger.snapshot()
        snap["cache"] = {"hits": state.cache.hits,
                         "misses": state.cache.misses,
                         "hit_rate": round(state.cache.hit_rate, 4)}
        return snap

    @app.get("/devboard")
    def devboard_page():
        """The operator surface (docs/design contract) — single file, served
        by the router per the repo's zero-install philosophy."""
        from fastapi.responses import HTMLResponse
        page = Path(__file__).parent / "static" / "devboard.html"
        return HTMLResponse(page.read_text())

    # ---- live demo board (design handoff wired to real data) -------------
    # demo/devboard.html is the design source of truth; serving it with
    # mock-data.js swapped for live-data.js IS the integration — no copies.
    _repo_root = Path(__file__).resolve().parents[3]

    @app.get("/demoboard")
    def demoboard_page():
        from fastapi.responses import HTMLResponse
        page = (_repo_root / "demo" / "devboard.html").read_text()
        return HTMLResponse(page.replace("mock-data.js", "demo-assets/live-data.js")
                                .replace('href="tokens.css"',
                                         'href="demo-assets/tokens.css"'))

    @app.get("/demoboard/deploy")
    def demoboard_deploy_page():
        from fastapi.responses import HTMLResponse
        page = (_repo_root / "demo" / "deploy.html").read_text()
        return HTMLResponse(page.replace("mock-data.js", "demo-assets/live-data.js")
                                .replace('href="tokens.css"',
                                         'href="demo-assets/tokens.css"'))

    @app.get("/demo-assets/{name}")
    def demo_asset(name: str):
        from fastapi.responses import FileResponse
        allowed = {"live-data.js": "application/javascript",
                   "tokens.css": "text/css",
                   "deploy-timeline.json": "application/json"}
        if name not in allowed:
            return _error(404, "unknown_asset", name)
        return FileResponse(_repo_root / "demo" / name,
                            media_type=allowed[name])

    # ---- reliability console (design/ package wired to live data) --------
    # design/*.html is the design source of truth; serving it with
    # live-fetch.js layered over console.js IS the integration — no copies,
    # no restyling (design/DESIGN.md, 2026-07-04 deviations).
    _design_dir = _repo_root / "design"
    _board_pages = ("operate", "deploy", "policy", "manage", "roadmap")
    _board_assets = {"tokens.css": "text/css", "shell.css": "text/css",
                     "console.js": "application/javascript",
                     "mock-data.js": "application/javascript",
                     "live-fetch.js": "application/javascript"}

    @app.get("/board/{page}")
    def board_page(page: str):
        from fastapi.responses import HTMLResponse
        if page not in _board_pages:
            return _error(404, "unknown_page", page)
        html = (_design_dir / f"{page}.html").read_text()
        html = (html
                .replace('href="tokens.css"', 'href="/board-assets/tokens.css"')
                .replace('href="shell.css"', 'href="/board-assets/shell.css"')
                .replace('src="console.js"', 'src="/board-assets/console.js"')
                .replace('src="mock-data.js"',
                         'src="/board-assets/mock-data.js"')
                .replace('<script src="/board-assets/console.js"></script>',
                         '<script src="/board-assets/console.js"></script>\n'
                         '<script src="/board-assets/live-fetch.js"></script>'))
        for p in _board_pages:  # in-page links (nav tabs move in live-fetch.js)
            html = html.replace(f'href="{p}.html"', f'href="/board/{p}"')
        return HTMLResponse(html)

    @app.get("/board-assets/{name}")
    def board_asset(name: str):
        from fastapi.responses import FileResponse
        if name not in _board_assets:
            return _error(404, "unknown_asset", name)
        return FileResponse(_design_dir / name,
                            media_type=_board_assets[name])

    @app.get("/replay/")
    def replay_page():
        from fastapi.responses import HTMLResponse
        return HTMLResponse((_repo_root / "site" / "index.html").read_text())

    @app.get("/replay/replay-data.js")
    def replay_data():
        from fastapi.responses import FileResponse
        return FileResponse(_repo_root / "site" / "replay-data.js",
                            media_type="application/javascript")

    @app.post("/v1/dev/drill")
    async def dev_drill(request: Request):
        """One-call scripted chaos drill (server-side, so a throttled demo
        tab can trigger it): drive load, inject a fault on a pool, wait for
        the agent to quarantine, then clear the fault — the agent probes,
        reinstates and resolves on its own. Mirrors tools/chaos.py drill."""
        import threading
        import time as _t
        body = await request.json()
        latency_ms = float(body.get("latency_ms", 600))
        error_rate = float(body.get("error_rate", 0))
        model = body.get("model", "qwen3-8b")

        def run():
            ctx = _board_ctx()
            if ctx is None:
                return
            pool = ctx[1][0]["id"]
            url = ctx[1][0]["url"]
            def load(n_end):
                n = 0
                while _t.monotonic() < n_end:
                    n += 1
                    try:
                        gen, *_ = state.proxy_chat_stream(
                            model, {"model": model, "max_tokens": 8,
                                    "stream": True, "messages": [{"role":
                                    "user", "content": f"drill {n}"}]}, {})
                        for _ in gen:
                            pass
                    except Exception:  # noqa: BLE001
                        pass
                    _t.sleep(0.7)
            threading.Thread(target=load,
                             args=(_t.monotonic() + 120,), daemon=True).start()
            _t.sleep(5)
            httpx.post(f"{url}/chaos",
                       json={"latency_ms": latency_ms,
                             "error_rate": error_rate}, timeout=5)
            state.events.emit("config_change", target="chaos-injection",
                              pool_id=pool, latency_ms=latency_ms,
                              error_rate=error_rate)
            deadline = _t.monotonic() + 60
            while _t.monotonic() < deadline:
                _t.sleep(1)
                incs = state.incidents.snapshot()
                if any(i["live"] and any("quarantined" in a
                       for a in i["actions"]) for i in incs):
                    break
            httpx.post(f"{url}/chaos",
                       json={"latency_ms": 0, "error_rate": 0}, timeout=5)
            state.events.emit("config_change", target="chaos-cleared",
                              pool_id=pool)

        threading.Thread(target=run, daemon=True, name="dev-drill").start()
        return {"status": "drill started"}

    @app.post("/v1/dev/load")
    async def dev_load(request: Request):
        """Server-side demo load: streams N rps of real chat requests through
        the router's own selection/telemetry path for `seconds`. The demo
        board toggles this instead of driving load from the browser (background
        tabs throttle timers to ~1/min, which starves breach detection)."""
        import threading
        import time as _t
        body = await request.json()
        model = body.get("model", "qwen3-8b")
        rps = min(float(body.get("rps", 1.5)), 5.0)
        seconds = min(float(body.get("seconds", 90)), 300.0)
        if model not in state.registry:
            return _error(404, "unknown_model", model)

        def loop():
            n = 0
            t_end = _t.monotonic() + seconds
            while _t.monotonic() < t_end:
                n += 1
                try:
                    gen, _c, _h, _s = state.proxy_chat_stream(
                        model, {"model": model, "max_tokens": 8,
                                "stream": True,
                                "messages": [{"role": "user",
                                              "content": f"demo load {n}"}]},
                        {})
                    for _ in gen:
                        pass
                except Exception:  # noqa: BLE001 — mid-quarantine is the demo
                    pass
                _t.sleep(1.0 / rps)

        threading.Thread(target=loop, daemon=True, name="dev-load").start()
        state.events.emit("config_change", target="dev-load",
                          model=model, rps=rps, seconds=seconds)
        return {"status": "running", "model": model, "rps": rps,
                "seconds": seconds}

    @app.post("/v1/assist")
    async def assist(request: Request):
        """Docs-grounded deploy assistant; reasoning served by a catalog
        model through this router (see router_app/assist.py)."""
        from fastapi.concurrency import run_in_threadpool
        from router_app import assist as assist_mod
        body = await request.json()
        question = body.get("question")
        if not question:
            return _error(400, "missing_question", "body needs 'question'")
        try:
            result = await run_in_threadpool(
                assist_mod.run, state, question,
                body.get("model", "glm-4.7"),
                body.get("model_id"), body.get("deployment_id"))
        except (UnknownModel, NoHealthyBackend) as exc:
            return _error(503, "assist_unavailable", str(exc))
        state.events.emit("assist", question=question[:80],
                          replica=result["served_by"]["replica"])
        return result

    @app.get("/v1/learning/episodes")
    def learning_episodes(limit: int = 30):
        """Recorded agent episodes (learning/README.md schema), newest
        first — live recordings then backfill."""
        import json as _json
        from router_app.learning import episodes_path
        out = []
        live = episodes_path()
        files = [live, _repo_root / "learning" / "episodes" / "backfill.jsonl"]
        for f in files:
            if f is None or not f.exists():
                continue
            lines = f.read_text().splitlines()
            for line in reversed(lines):
                try:
                    out.append(_json.loads(line))
                except ValueError:
                    continue
                if len(out) >= limit:
                    return out
        return out

    @app.get("/v1/learning/policy-eval")
    def learning_policy_eval(raw: int = 0):
        """Latest offline policy evaluation (learning/evaluate.py output),
        adapted to the design package's contract; ?raw=1 returns the Phase-B
        artifact untouched. POLICY_EVAL_PATH overrides the repo-root default
        (tests)."""
        path = Path(os.environ.get(
            "POLICY_EVAL_PATH",
            _repo_root / "learning" / "policy-eval.json"))
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"available": False}
        if raw:
            data["available"] = True
            return data
        return devboard.policy_eval_shape(data)

    def _pending_policy_path() -> Path:
        return Path(os.environ.get(
            "PENDING_POLICY_PATH",
            _repo_root / "learning" / "pending-policy.json"))

    @app.post("/v1/learning/policy/promote")
    async def policy_promote(request: Request):
        """Governed promote: records the proposal for a human approver. NO
        hot-apply — the live AgentConfig is untouched until a human acts on
        learning/pending-policy.json (CLAUDE.md rule 5: learning tunes
        parameters through governance, never directly)."""
        from dataclasses import fields as dc_fields
        from router_app.incident_agent import AgentConfig
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _error(400, "invalid_json", "request body must be JSON")
        config = body.get("config")
        if not isinstance(config, dict):
            return _error(400, "invalid_config", "body needs a 'config' object")
        expected = {f.name for f in dc_fields(AgentConfig)}
        if set(config) != expected:
            return _error(400, "invalid_config",
                          f"config keys must be exactly {sorted(expected)}",
                          unexpected=sorted(set(config) ^ expected))
        bad = [k for k, v in config.items()
               if isinstance(v, bool) or not isinstance(v, (int, float))]
        if bad:
            return _error(400, "invalid_config",
                          f"non-numeric values for: {sorted(bad)}")
        record = {"config": config,
                  "proposed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                               time.gmtime()),
                  "status": "awaiting_approver"}
        path = _pending_policy_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2))
        state.events.emit("policy_promote_proposed",
                          approver=body.get("approver"),
                          keys=sorted(config))
        return {"status": "awaiting_approver"}

    @app.get("/v1/learning/policy/pending")
    def policy_pending():
        try:
            return json.loads(_pending_policy_path().read_text())
        except (OSError, json.JSONDecodeError):
            return {"status": "none"}

    # ---- devboard data surface (contracts/devboard.openapi.yaml) ----------
    # Shapes come from router_app/devboard.py builders over live state; the
    # board renders ONLY what the router measured (SLO-AUDITOR provenance).

    def _board_ctx():
        model = state.devboard_model()
        if model is None:
            return None
        replicas = cfg.replicas_for(state.policy, model)
        entry = state.registry.get(model, {})
        tier_rules = state.policy["tiers"].get(
            entry.get("tier", "realtime"), {})
        return model, replicas, entry, tier_rules

    @app.get("/v1/metrics/hero")
    def metrics_hero():
        ctx = _board_ctx()
        tpot_slo = (ctx[3].get("tpot_ms", 60) if ctx else 60)
        return devboard.hero(state.metrics, state.incidents,
                             tpot_slo_ms=tpot_slo)

    @app.get("/v1/metrics/slo")
    def metrics_slo():
        ctx = _board_ctx()
        if ctx is None:
            return {"pools": []}
        _, replicas, entry, tier_rules = ctx
        return devboard.slo_panel(
            state.metrics, replicas, tier_rules,
            is_usable=lambda u: state.poller.status_for(u).usable,
            pending_of=state.kvstate.pending,
            goodput_curves=state.goodput_curves,
            tier=entry.get("tier", "realtime"))

    @app.get("/v1/pools")
    def pools():
        ctx = _board_ctx()
        if ctx is None:
            return {"pools": []}
        _, replicas, entry, _ = ctx
        affinity = state.policy.get("affinity", {})
        return devboard.pools_snapshot(
            state.metrics, replicas, entry,
            is_usable=lambda u: state.poller.status_for(u).usable,
            pending_of=state.kvstate.pending,
            capacity=int(affinity.get("capacity", 8)))

    @app.get("/v1/placement/feed")
    def placement_feed():
        """SSE stream of placement decisions (newest events as they land)."""
        def tail():
            last = state.events.seq()
            # replay the most recent decisions so the board fills instantly
            for ev in state.events.recent(8, "route"):
                item = devboard.feed_item(ev)
                if item:
                    yield f"data: {json.dumps(item)}\n\n"
            while True:
                for ev in state.events.since(last, "route"):
                    last = max(last, ev["seq"])
                    item = devboard.feed_item(ev)
                    if item:
                        yield f"data: {json.dumps(item)}\n\n"
                time.sleep(0.25)
        return StreamingResponse(tail(), media_type="text/event-stream")

    @app.get("/v1/placement/feed/snapshot")
    def placement_feed_snapshot():
        """Last 30 placement decisions as one JSON array — the console's
        non-SSE lens over the same EventLog ring the SSE feed tails."""
        items = [devboard.feed_item(ev)
                 for ev in state.events.recent(30, "route")]
        return [i for i in items if i]

    @app.get("/v1/releases/timeline")
    def releases_timeline():
        """The recorded deploy trail (demo/deploy-timeline.json — a real
        artifact) adapted to the console's timeline shape. DEPLOY_TIMELINE_PATH
        overrides for tests."""
        path = Path(os.environ.get("DEPLOY_TIMELINE_PATH",
                                   _repo_root / "demo" / "deploy-timeline.json"))
        try:
            raw = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"version": None, "model": None, "strategy": None,
                    "tier_target": None, "attempts": [],
                    "source": "no recorded deploy timeline found"}
        return devboard.release_timeline(raw)

    @app.get("/v1/manage/options")
    def manage_options_route():
        """Remediation options + drain plan for the managed pool(s), built
        from live snapshots by the pure builder (manage_options.py)."""
        from router_app import manage_options
        ctx = _board_ctx()
        if ctx is None:
            return {"pools": []}
        model, replicas, entry, _ = ctx
        affinity = state.policy.get("affinity", {})
        pools_snap = devboard.pools_snapshot(
            state.metrics, replicas, entry,
            is_usable=lambda u: state.poller.status_for(u).usable,
            pending_of=state.kvstate.pending,
            capacity=int(affinity.get("capacity", 8)))["pools"]

        def _read_json(path: Path):
            try:
                return json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                return None

        return manage_options.build(
            pools=pools_snap,
            samples=state.metrics.window(900.0),
            replicas=replicas,
            registry_entry=entry,
            events=[e for e in state.events.recent(500, "route")
                    if e.get("model") == model],
            placement=state.placement,
            catalog=_read_json(_repo_root / "deploy" / "baseten"
                               / "model-apis.json"),
            timeline=_read_json(_repo_root / "demo" / "deploy-timeline.json"),
            now=time.time(),
            default_alias=os.environ.get("MODEL_API_DEFAULT"))

    @app.post("/v1/pools/{pool_id}/drain")
    def drain_pool(pool_id: str, mode: str = Query(default="graceful"),
                   timeout_s: float = Query(default=30.0)):
        """Minimal REAL drain. (1) Sticky-quarantine the pool — the existing
        placement-exclusion mechanism; selection skips unusable pools, so no
        new requests land here. (2) graceful: wait for the router's in-flight
        count on the pool (kvstate.pending) to reach 0, bounded by timeout.
        'immediate' = exclusion only. Sync def → threadpool, so the wait
        never blocks the event loop. The KV-aware weighted drain is roadmap
        (see /v1/manage/options drain steps)."""
        ctx = _board_ctx()
        rep = next((r for r in (ctx[1] if ctx else [])
                    if r["id"] == pool_id), None)
        if rep is None:
            return _error(404, "unknown_pool", pool_id)
        state.poller.status_for(rep["url"]).quarantined = True
        state.events.emit("drain_started", pool=pool_id, mode=mode)
        if mode != "graceful":
            return {"status": "excluded", "pool": pool_id,
                    "mode": "immediate",
                    "pending": state.kvstate.pending(pool_id)}
        start = time.monotonic()
        deadline = start + min(timeout_s, 300.0)
        while time.monotonic() < deadline:
            if state.kvstate.pending(pool_id) == 0:
                waited = round(time.monotonic() - start, 2)
                state.events.emit("drain_complete", pool=pool_id,
                                  waited_s=waited)
                return {"status": "drained", "pool": pool_id,
                        "mode": "graceful", "waited_s": waited}
            time.sleep(0.2)
        state.events.emit("drain_timeout", pool=pool_id,
                          pending=state.kvstate.pending(pool_id))
        return {"status": "timeout", "pool": pool_id, "mode": "graceful",
                "pending": state.kvstate.pending(pool_id)}

    @app.get("/v1/releases/active")
    def releases_active():
        ctx = _board_ctx()
        model = ctx[0] if ctx else "none"
        return devboard.release_active(state.release, model)

    @app.get("/v1/incidents")
    def incidents():
        return state.incidents.snapshot()

    # Dev-mode chaos controls: the devboard's state switcher triggers REAL
    # fault injection through here (pool /chaos hooks, env-gated on the
    # pools). GET reports which pools accept chaos; POST forwards.
    @app.get("/v1/dev/chaos")
    def dev_chaos_capabilities():
        ctx = _board_ctx()
        if ctx is None:
            return {"pools": []}
        out = []
        for rep in ctx[1]:
            try:
                r = httpx.get(f"{rep['url']}/chaos", timeout=2)
                out.append({"id": rep["id"], "capable": r.status_code == 200,
                            "state": r.json() if r.status_code == 200 else None})
            except httpx.HTTPError:
                out.append({"id": rep["id"], "capable": False, "state": None})
        return {"pools": out}

    @app.post("/v1/dev/chaos")
    async def dev_chaos(request: Request):
        body = await request.json()
        ctx = _board_ctx()
        if ctx is None:
            return _error(404, "no_model", "no LLM model configured")
        targets = [r for r in ctx[1]
                   if body.get("pool_id") in (None, r["id"])]
        lat = float(body.get("latency_ms") or 0)
        err = float(body.get("error_rate") or 0)
        results = {}
        for rep in targets:
            try:
                r = httpx.post(f"{rep['url']}/chaos", json={
                    "latency_ms": body.get("latency_ms", 0),
                    "error_rate": body.get("error_rate", 0)}, timeout=3)
                results[rep["id"]] = r.json()
            except httpx.HTTPError as exc:
                results[rep["id"]] = {"error": str(exc)}
                continue
            # ground-truth fault window for the episode tape recorder:
            # any nonzero injection opens a window, all-zeros clears it
            if lat > 0 or err > 0:
                kind = ("combo" if lat > 0 and err > 0
                        else "latency" if lat > 0 else "errors")
                state.chaos_windows[rep["id"]] = {
                    "injected_at": time.monotonic(),
                    "injected_at_utc": time.time(),
                    "cleared_at": None, "cleared_at_utc": None,
                    "kind": kind}
            else:
                win = state.chaos_windows.get(rep["id"])
                if win is not None and win.get("cleared_at") is None:
                    win["cleared_at"] = time.monotonic()
                    win["cleared_at_utc"] = time.time()
        state.events.emit("config_change", target="chaos-injection",
                          **{k: body.get(k) for k in
                             ("pool_id", "latency_ms", "error_rate")})
        return results

    # Dev surface for the incident agent + chaos drills (not in the board's
    # read contract): open / act / resolve.
    @app.post("/v1/incidents")
    async def incident_open(request: Request):
        body = await request.json()
        inc = state.incidents.open(body.get("title", "untitled incident"),
                                   agent=bool(body.get("agent", True)))
        return {"id": inc["id"]}

    @app.post("/v1/incidents/{incident_id}/actions")
    async def incident_act(incident_id: str, request: Request):
        body = await request.json()
        inc = state.incidents.act(incident_id, body.get("action", ""),
                                  phase=body.get("phase"))
        if inc is None:
            return _error(404, "unknown_incident", incident_id)
        return {"id": incident_id, "actions": len(inc["actions"])}

    @app.post("/v1/incidents/{incident_id}/resolve")
    async def incident_resolve(incident_id: str, request: Request):
        body = await request.json()
        inc = state.incidents.resolve(incident_id,
                                      postmortem_url=body.get("postmortem_url"))
        if inc is None:
            return _error(404, "unknown_incident", incident_id)
        return {"id": incident_id, "mttr_s": inc["mttr_s"]}

    # ---- gated Baseten writes (writes.py holds the policy; routes are glue).
    # Off by default: every /v1/writes/* 403s unless CONSOLE_ALLOW_WRITES=1.
    from router_app import writes as writes_mod

    def _writes_denied(reason: str, **fields) -> JSONResponse:
        state.events.emit("baseten_write_denied", reason=reason, **fields)
        return JSONResponse(status_code=403, content={"error": reason})

    @app.get("/v1/writes/token")
    def writes_token(op: str = Query(default=""),
                     model_id: str = Query(default=""),
                     deployment_id: str = Query(default=""),
                     body_sha256: str = Query(default="")):
        """Step 1 of the confirm handshake: a short-lived single-use token
        bound to the exact (op, ids, body-hash) the console previewed."""
        if not writes_mod.gate_open():
            return _writes_denied("writes disabled", op=op)
        err = writes_mod.validate_target(op, model_id, deployment_id)
        if err:
            return _writes_denied(err, op=op, model_id=model_id,
                                  deployment_id=deployment_id)
        ts = int(time.time())
        token = writes_mod.mint(op, model_id, deployment_id, body_sha256, ts)
        return {"token": token, "ts": ts, "ttl_s": writes_mod.TOKEN_TTL_S}

    @app.post("/v1/writes/baseten")
    async def writes_baseten(request: Request):
        """Step 2: verify gate + allowlist + token, then call Baseten via
        the injectable transport. The API key never appears in events or
        responses (writes.py reads it inside the transport)."""
        if not writes_mod.gate_open():
            return _writes_denied("writes disabled")
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _writes_denied("request body must be JSON")
        op = body.get("op", "")
        model_id = body.get("model_id", "")
        deployment_id = body.get("deployment_id", "")
        payload = body.get("body") or {}
        err = (writes_mod.validate_target(op, model_id, deployment_id)
               or writes_mod.validate_body(op, payload))
        if err:
            return _writes_denied(err, op=op, model_id=model_id,
                                  deployment_id=deployment_id)
        state.events.emit("baseten_write_requested", op=op,
                          model_id=model_id, deployment_id=deployment_id)
        err = writes_mod.check_token(body.get("token"), body.get("ts"),
                                     op, model_id, deployment_id, payload)
        if err:
            return _writes_denied(err, op=op, model_id=model_id,
                                  deployment_id=deployment_id)
        status, upstream, method, path = writes_mod.execute(
            op, model_id, deployment_id, payload)
        state.events.emit("baseten_write_executed", op=op,
                          model_id=model_id, deployment_id=deployment_id,
                          status=status, method=method, path=path,
                          body=payload if op == "autoscaling" else None)
        return JSONResponse(status_code=status,
                            content={"upstream_status": status,
                                     "body": upstream})

    return app


app = get_app() if os.environ.get("ROUTER_AUTOSTART", "1") == "1" else None
