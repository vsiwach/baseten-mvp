"""KV-affinity graceful migration — state-machine legality (migration.py),
the routing pre-filter (policy.select_replica migration kwarg), drain
accounting (kvstate.ttl_horizon_s), and the /v1/migrations endpoints.
Everything deterministic: fake clocks, injected kvstate, no network."""

import pytest

from router_app.kvstate import KVState
from router_app.migration import (ABORTED, COMPLETED, DRAINED, MIGRATING,
                                  Migration, MigrationConflict,
                                  MigrationManager)
from router_app.policy import select_replica

# ---------------------------------------------------------------------------
# state machine
# ---------------------------------------------------------------------------


def _manager(events=None):
    clock = {"t": 100.0}
    emit = (lambda kind, **f: events.append((kind, f))) if events is not None \
        else None
    mgr = MigrationManager(clock=lambda: clock["t"], emit=emit)
    return mgr, clock


def _start(mgr, **kw):
    args = dict(model="qwen3-8b", source="src", target="dst",
                mode="graceful", weight=1.0,
                source_snapshot={"live_prefixes": 2, "in_flight": 1})
    args.update(kw)
    return mgr.start(**args)


def test_start_transitions_idle_to_migrating_and_emits():
    events = []
    mgr, _ = _manager(events)
    assert mgr.active() is None
    mig = _start(mgr)
    assert mig.state == MIGRATING
    assert mig.active
    assert mgr.active() is mig
    assert mig.started_at == 100.0
    assert events[0][0] == "migration_started"
    assert events[0][1]["source"] == "src"
    assert events[0][1]["mode"] == "graceful"


def test_double_start_conflicts_while_active_only():
    mgr, _ = _manager()
    _start(mgr)
    with pytest.raises(MigrationConflict):
        _start(mgr)                      # migrating blocks
    mgr.observe(0, 0)                    # -> drained (still active)
    with pytest.raises(MigrationConflict):
        _start(mgr)
    mgr.complete()                       # terminal — the slot frees up
    again = _start(mgr)
    assert again.state == MIGRATING
    assert again.id != "mig-0001"        # a NEW migration, not a resurrection


def test_drained_fires_exactly_once():
    events = []
    mgr, clock = _manager(events)
    _start(mgr)
    clock["t"] = 130.0
    mgr.observe(1, 0)                    # not drained yet — progress
    mgr.observe(0, 0)                    # drained
    mgr.observe(0, 0)                    # drained state is sticky, no re-emit
    mgr.observe(0, 0)
    drained = [e for e in events if e[0] == "migration_drained"]
    assert len(drained) == 1
    assert drained[0][1]["drained_after_s"] == 30.0
    assert mgr.current.state == DRAINED


def test_progress_emits_only_when_counts_move():
    events = []
    mgr, _ = _manager(events)
    _start(mgr)
    mgr.observe(2, 1)
    mgr.observe(2, 1)                    # unchanged — silent
    mgr.observe(1, 0)
    progress = [e for e in events if e[0] == "migration_progress"]
    assert len(progress) == 2
    assert progress[-1][1] == {"migration_id": "mig-0001", "source": "src",
                               "target": "dst", "live_prefixes": 1,
                               "in_flight": 0}


def test_abort_legal_from_migrating_and_drained_only():
    mgr, _ = _manager()
    mig = _start(mgr)
    mgr.abort()
    assert mig.state == ABORTED
    assert not mig.active
    with pytest.raises(MigrationConflict):
        mgr.abort()                      # already terminal

    mig2 = _start(mgr)                   # slot freed by abort
    mgr.observe(0, 0)
    mgr.abort()                          # drained -> aborted is legal
    assert mig2.state == ABORTED


def test_complete_requires_drained_no_force():
    mgr, _ = _manager()
    mig = _start(mgr)
    with pytest.raises(MigrationConflict):
        mgr.complete()                   # migrating: refused
    mgr.observe(0, 0)
    mgr.complete()
    assert mig.state == COMPLETED
    with pytest.raises(MigrationConflict):
        mgr.complete()                   # completed: refused again


def test_start_validates_mode_and_weight():
    mgr, _ = _manager()
    with pytest.raises(ValueError):
        _start(mgr, mode="yolo")
    with pytest.raises(ValueError):
        _start(mgr, weight=0.0)          # weight ∈ (0, 1]
    with pytest.raises(ValueError):
        _start(mgr, weight=1.5)
    assert _start(mgr, weight=1.0).state == MIGRATING


def test_takes_target_is_deterministic_and_weighted():
    def mig(weight):
        return Migration(id="m", model="qwen3-8b", source="src",
                         target="dst", mode="graceful", weight=weight,
                         started_at=0.0, source_snapshot={})
    prefixes = [f"{n:016x}" for n in range(0, 2000, 7)]
    full = mig(1.0)
    assert all(full.takes_target(p) for p in prefixes)   # weight=1: all
    half = mig(0.5)
    first = [half.takes_target(p) for p in prefixes]
    assert first == [half.takes_target(p) for p in prefixes]  # deterministic
    share = sum(first) / len(first)
    assert 0.3 < share < 0.7             # a genuine split, both classes hit


# ---------------------------------------------------------------------------
# placement: select_replica with an active migration (pure, injected state)
# ---------------------------------------------------------------------------

REPLICAS = [
    {"id": "r0", "provider": "local-docker", "url": "http://r0"},
    {"id": "r1", "provider": "local-docker", "url": "http://r1"},
    {"id": "r2", "provider": "local-docker", "url": "http://r2"},
]
AFFINITY = {"enabled": True, "prefix_tokens": 8, "capacity": 4}


def _mig(source, target, weight=1.0, state=MIGRATING):
    return Migration(id="mig-0001", model="qwen3-8b", source=source,
                     target=target, mode="graceful", weight=weight,
                     started_at=0.0, source_snapshot={}, state=state)


def _select(prompt, *, kv, migration=None, now=0.0):
    return select_replica(
        prompt, REPLICAS, is_usable=lambda u: True, kvstate=kv,
        tier_rules={"prefer": "lowest_cost"}, cost_of=lambda p: 0.10,
        affinity_cfg=AFFINITY, capacity=4, migration=migration, now=now)


def _prompt_owned_by(kv, owner):
    """A prompt whose baseline (no-migration) placement is `owner`."""
    for n in range(200):
        p = f"prefix {n:03d} needs to land on a known owner replica ok"
        if _select(p, kv=kv).replica_id == owner:
            return p
    raise AssertionError(f"no prompt found for owner {owner}")


def test_new_prefix_steers_to_target():
    kv = KVState(kv_ttl_s=300.0, clock=lambda: 0.0)
    prompt = _prompt_owned_by(kv, "r0")
    choice = _select(prompt, kv=kv, migration=_mig("r0", "r2"))
    assert choice.replica_id == "r2"
    assert choice.reason == "migration_target"


def test_warm_prefix_on_source_stays_and_rides_ttl():
    kv = KVState(kv_ttl_s=300.0, clock=lambda: 0.0)
    prompt = _prompt_owned_by(kv, "r0")
    base = _select(prompt, kv=kv)
    kv.record_prefix("r0", base.prefix, now=0.0)     # warm on source
    choice = _select(prompt, kv=kv, migration=_mig("r0", "r2"), now=10.0)
    assert choice.replica_id == "r0"                 # stays on source
    assert choice.reason == "affinity_warm"
    assert choice.cache_hit is True


def test_ttl_expiry_flips_warm_session_to_target():
    kv = KVState(kv_ttl_s=300.0, clock=lambda: 0.0)
    prompt = _prompt_owned_by(kv, "r0")
    base = _select(prompt, kv=kv)
    kv.record_prefix("r0", base.prefix, now=0.0)     # expires at t=300
    mig = _mig("r0", "r2")
    assert _select(prompt, kv=kv, migration=mig, now=299.0).replica_id == "r0"
    flipped = _select(prompt, kv=kv, migration=mig, now=301.0)
    assert flipped.replica_id == "r2"
    assert flipped.reason == "migration_target"


def test_abort_restores_byte_identical_selection():
    kv = KVState(kv_ttl_s=300.0, clock=lambda: 0.0)
    prompts = [f"abort restore check {n} same ring same answer" for n in
               range(30)]
    before = [_select(p, kv=kv) for p in prompts]
    mig = _mig("r0", "r2")
    during = [_select(p, kv=kv, migration=mig) for p in prompts]
    assert during != before                          # migration DID steer
    mig.state = ABORTED                              # abort() sets this
    after = [_select(p, kv=kv, migration=mig) for p in prompts]
    assert after == before                           # byte-identical restore


def test_weight_half_splits_deterministically_weight_one_takes_all():
    kv = KVState(kv_ttl_s=300.0, clock=lambda: 0.0)
    prompts = [f"weighted ramp prefix {n:03d} varies across the ring" for n
               in range(60)]
    half = _mig("r0", "r2", weight=0.5)
    first = [_select(p, kv=kv, migration=half) for p in prompts]
    assert first == [_select(p, kv=kv, migration=half) for p in prompts]
    reasons = {c.reason for c in first}
    assert "migration_target" in reasons             # steered share exists
    baseline = [_select(p, kv=kv) for p in prompts]
    kept = [i for i, c in enumerate(first) if c.reason != "migration_target"]
    assert kept                                      # unsteered share exists
    for i in kept:                                   # ...and is untouched
        assert first[i] == baseline[i]
    full = [_select(p, kv=kv, migration=_mig("r0", "r2", weight=1.0))
            for p in prompts]
    assert all(c.replica_id != "r0" for c in full)   # weight=1: source empty


def test_drained_migration_still_steers_new_prefixes():
    kv = KVState(kv_ttl_s=300.0, clock=lambda: 0.0)
    prompt = _prompt_owned_by(kv, "r0")
    choice = _select(prompt, kv=kv,
                     migration=_mig("r0", "r2", state=DRAINED))
    assert choice.replica_id == "r2"                 # no un-draining allowed


# ---------------------------------------------------------------------------
# drain accounting: kvstate.ttl_horizon_s
# ---------------------------------------------------------------------------

def test_ttl_horizon_is_last_unexpired_prefix():
    kv = KVState(kv_ttl_s=100.0, clock=lambda: 0.0)
    assert kv.ttl_horizon_s("r0", now=0.0) == 0.0    # holds nothing
    kv.record_prefix("r0", "aaaa", now=0.0)          # expires 100
    kv.record_prefix("r0", "bbbb", now=40.0)         # expires 140 — the LAST
    assert kv.ttl_horizon_s("r0", now=50.0) == 90.0
    assert kv.ttl_horizon_s("r0", now=110.0) == 30.0  # first one expired
    assert kv.ttl_horizon_s("r0", now=141.0) == 0.0
    assert kv.cached_prefixes("r0", now=50.0) == 2
    assert kv.cached_prefixes("r0", now=110.0) == 1


# ---------------------------------------------------------------------------
# endpoints (TestClient; fake kvstate clock injected where drain needs it)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mig_client(tmp_path, monkeypatch):
    """Router app with two qwen3-8b pools (no live backends — nothing sends
    traffic) and a fake-clock kvstate so TTL expiry is scripted."""
    from starlette.testclient import TestClient

    from router_app.main import get_app

    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "backends:\n"
        "  qwen3-8b:\n"
        "    tier: interactive\n"
        "    target: gpu\n"
        "    engine: vllm\n"
        "    max_replicas: 2\n")
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "tiers:\n"
        "  interactive: {max_latency_ms: 1000, prefer: lowest_latency,"
        " ttft_ms: 800, tpot_ms: 60}\n"
        "cost_table: {baseten-l4: 1.05, runpod-vllm-l4: 0.60}\n"
        "cache: {enabled: false}\n"
        "affinity: {enabled: true, prefix_tokens: 32, capacity: 8}\n"
        "endpoints:\n"
        "  qwen3-8b:\n"
        "    - {id: baseten-l4, provider: baseten-l4,"
        " url: http://pool-baseten:8080}\n"
        "    - {id: vllm-l4, provider: runpod-vllm-l4,"
        " url: http://pool-vllm:8080}\n")
    monkeypatch.setenv("ROUTER_QUEUE_DIR", str(tmp_path / "queue"))
    app = get_app(registry, policy, start_background=False)
    state = app.state.router_state
    clock = {"t": 0.0}
    state.kvstate = KVState(kv_ttl_s=20.0, clock=lambda: clock["t"])
    with TestClient(app) as client:
        client.state = state
        client.clock = clock
        yield client


START = {"model": "qwen3-8b", "source": "baseten-l4", "target": "vllm-l4",
         "mode": "graceful", "weight": 1.0}


def test_start_payload_shape_and_snapshot(mig_client):
    st = mig_client.state
    st.kvstate.record_prefix("baseten-l4", "feedbeefcafe0001")
    st.kvstate.inc_pending("baseten-l4")
    body = mig_client.post("/v1/migrations", json=START).json()
    assert body == {"migration_id": "mig-0001", "state": "migrating",
                    "source_snapshot": {"live_prefixes": 1, "in_flight": 1}}
    kinds = st.events.kinds()
    assert kinds.get("migration_started") == 1


def test_start_404_unknown_pool_409_double_400_bad_input(mig_client):
    assert mig_client.post("/v1/migrations", json={
        **START, "source": "nope"}).status_code == 404
    assert mig_client.post("/v1/migrations", json={
        **START, "target": "nope"}).status_code == 404
    assert mig_client.post("/v1/migrations", json={
        **START, "target": "baseten-l4"}).status_code == 400
    assert mig_client.post("/v1/migrations", json={
        **START, "weight": 0}).status_code == 400
    assert mig_client.post("/v1/migrations", json={
        **START, "mode": "yolo"}).status_code == 400
    assert mig_client.post("/v1/migrations", json=START).status_code == 200
    assert mig_client.post("/v1/migrations", json=START).status_code == 409


def test_current_reports_drain_accounting_then_drains(mig_client):
    st, clock = mig_client.state, mig_client.clock
    st.kvstate.record_prefix("baseten-l4", "feedbeefcafe0001")  # expires t=20
    mig_client.post("/v1/migrations", json=START)
    cur = mig_client.get("/v1/migrations/current").json()
    assert cur["id"] == "mig-0001"
    assert cur["state"] == "migrating"
    assert cur["mode"] == "graceful"
    assert cur["source"] == "baseten-l4" and cur["target"] == "vllm-l4"
    assert cur["weight"] == 1.0
    assert cur["live_prefixes_remaining"] == 1
    assert cur["in_flight"] == 0
    assert cur["ttl_horizon_s"] == 20.0
    assert cur["progress_pct"] == 0.0
    assert cur["routed"] == {"target_new": 0, "source_warm": 0}
    clock["t"] = 21.0                       # TTL expires the last prefix
    cur = mig_client.get("/v1/migrations/current").json()
    assert cur["state"] == "drained"
    assert cur["live_prefixes_remaining"] == 0
    assert cur["ttl_horizon_s"] == 0.0
    assert cur["progress_pct"] == 100.0
    assert st.events.kinds().get("migration_drained") == 1


def test_current_idle_when_no_or_terminal_migration(mig_client):
    assert mig_client.get("/v1/migrations/current").json() == {
        "state": "idle"}
    mig_client.post("/v1/migrations", json=START)
    mig_client.post("/v1/migrations/mig-0001/abort")
    assert mig_client.get("/v1/migrations/current").json() == {
        "state": "idle"}


def test_pending_requests_block_drain(mig_client):
    st = mig_client.state
    st.kvstate.inc_pending("baseten-l4")
    mig_client.post("/v1/migrations", json=START)
    assert mig_client.get(
        "/v1/migrations/current").json()["state"] == "migrating"
    st.kvstate.dec_pending("baseten-l4")
    assert mig_client.get(
        "/v1/migrations/current").json()["state"] == "drained"


def test_complete_409_until_drained_then_200(mig_client):
    st = mig_client.state
    st.kvstate.record_prefix("baseten-l4", "feedbeefcafe0001")
    mig_client.post("/v1/migrations", json=START)
    assert mig_client.post(
        "/v1/migrations/mig-0001/complete").status_code == 409
    mig_client.clock["t"] = 21.0
    mig_client.get("/v1/migrations/current")          # lazy check drains
    r = mig_client.post("/v1/migrations/mig-0001/complete")
    assert r.status_code == 200
    assert r.json() == {"state": "completed"}
    assert st.events.kinds().get("migration_complete") == 1
    assert mig_client.post(
        "/v1/migrations/mig-0001/complete").status_code == 409


def test_abort_endpoint_and_unknown_id_404(mig_client):
    mig_client.post("/v1/migrations", json=START)
    assert mig_client.post("/v1/migrations/mig-9999/abort").status_code == 404
    r = mig_client.post("/v1/migrations/mig-0001/abort")
    assert r.status_code == 200
    assert r.json() == {"state": "aborted"}
    assert mig_client.state.events.kinds().get("migration_aborted") == 1
    assert mig_client.post(
        "/v1/migrations/mig-0001/abort").status_code == 409  # terminal


def test_immediate_mode_quarantines_source_and_abort_clears(mig_client):
    st = mig_client.state
    src_url = "http://pool-baseten:8080"
    mig_client.post("/v1/migrations", json={**START, "mode": "immediate"})
    assert st.poller.status_for(src_url).quarantined is True
    assert st.poller.status_for(src_url).usable is False   # ALL prefixes move
    mig_client.post("/v1/migrations/mig-0001/abort")
    assert st.poller.status_for(src_url).quarantined is False
    assert st.poller.status_for(src_url).usable is True


def test_abort_preserves_pre_existing_agent_quarantine(mig_client):
    # A sick pool the incident agent quarantined BEFORE the migration must
    # stay quarantined after an immediate-mode abort — we lift only what
    # migration start itself set (evals/migration known limit #3).
    st = mig_client.state
    src_url = "http://pool-baseten:8080"
    st.poller.status_for(src_url).quarantined = True   # agent-set, pre-existing
    mig_client.post("/v1/migrations", json={**START, "mode": "immediate"})
    assert st.poller.status_for(src_url).quarantined is True
    mig_client.post("/v1/migrations/mig-0001/abort")
    assert st.poller.status_for(src_url).quarantined is True  # NOT lifted


def test_graceful_mode_never_quarantines(mig_client):
    st = mig_client.state
    mig_client.post("/v1/migrations", json=START)
    assert st.poller.status_for("http://pool-baseten:8080").quarantined \
        is False


def test_migration_events_ride_the_placement_feed(mig_client):
    mig_client.post("/v1/migrations", json=START)
    mig_client.get("/v1/migrations/current")          # drains (nothing held)
    feed = mig_client.get("/v1/placement/feed/snapshot").json()
    reasons = [r["reason"] for r in feed]
    assert any(r.startswith("migration_started") for r in reasons)
    assert any(r.startswith("migration_drained") for r in reasons)
    mig_row = feed[0]
    assert mig_row["pool"] == "baseten-l4→vllm-l4"
    assert mig_row["req"] == "mig-0001"
    assert set(mig_row) >= {"req", "tier", "pool", "reason", "ttft_ms",
                            "decide_ms"}
