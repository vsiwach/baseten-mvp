"""KV-affinity graceful migration — pure state machine, injected clock.

One migration per router, moving a model's traffic from a `source` pool to a
`target` pool without the re-prefill storm a hard drain causes:

  idle ──start()──▶ migrating ──(live_prefixes==0 & pending==0)──▶ drained
                        │                                             │
                        └───────────── abort() ──────────────────────┤
                                                                 complete()
                                                                      ▼
                                                    aborted        completed

- graceful: new prefixes steer to target (policy.py pre-filter); sessions
  whose KV is still warm on source ride out the KV TTL there. DRAINED fires
  when the source holds no unexpired prefixes and no in-flight requests —
  a LAZY check (`observe`) driven by progress reads and request completions,
  never a background thread.
- immediate: the HTTP layer additionally sets the sticky poller quarantine
  on source (the existing /v1/pools/{id}/drain mechanism) so ALL prefixes
  re-prefill on target. This module stays pure — it records the mode; the
  quarantine side effect lives in main.py, as does clearing it on abort.
- weight ∈ (0,1] ramps what share of NEW prefixes steer to target:
  takes_target(prefix) = int(prefix_hash, 16) % 100 < weight*100 —
  deterministic per prefix, so a session never flaps between pools.

Everything is injected (clock, emit) so unit tests are deterministic; no
router state, no I/O, no FastAPI imports (CLAUDE.md: pure decision logic).
"""

import threading
from dataclasses import dataclass, field

MIGRATING = "migrating"
DRAINED = "drained"
ABORTED = "aborted"
COMPLETED = "completed"
MODES = ("graceful", "immediate")


class MigrationConflict(Exception):
    """Illegal state transition — the HTTP layer maps this to 409."""


@dataclass
class Migration:
    id: str
    model: str
    source: str
    target: str
    mode: str                     # "graceful" | "immediate"
    weight: float                 # (0, 1] — share of new prefixes steered
    started_at: float
    source_snapshot: dict         # {live_prefixes, in_flight} at start
    state: str = MIGRATING
    drained_at: float | None = None
    routed: dict = field(
        default_factory=lambda: {"target_new": 0, "source_warm": 0})
    last_observed: tuple | None = None   # (live_prefixes, pending) last seen

    @property
    def active(self) -> bool:
        """Active migrations steer routing; terminal ones are inert."""
        return self.state in (MIGRATING, DRAINED)

    def takes_target(self, prefix: str) -> bool:
        """Deterministic weighted split over prefix hashes: the same prefix
        always gets the same answer, so a steered session stays steered."""
        return int(prefix, 16) % 100 < self.weight * 100


class MigrationManager:
    """Holds the router's single migration slot and enforces the state
    machine. Side-effect-free except the injected `emit`."""

    def __init__(self, clock=None, emit=None):
        self._clock = clock or __import__("time").monotonic
        self._emit = emit or (lambda kind, **fields: None)
        self._lock = threading.Lock()
        self._seq = 0
        self.current: Migration | None = None

    def active(self) -> Migration | None:
        mig = self.current
        return mig if mig is not None and mig.active else None

    # --- transitions ------------------------------------------------------

    def start(self, *, model: str, source: str, target: str,
              mode: str = "graceful", weight: float = 1.0,
              source_snapshot: dict | None = None) -> Migration:
        """idle → migrating. Raises MigrationConflict if one is active (at
        most one per router), ValueError on bad mode/weight."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        weight = float(weight)
        if not 0.0 < weight <= 1.0:
            raise ValueError(f"weight must be in (0, 1], got {weight}")
        with self._lock:
            if self.current is not None and self.current.active:
                raise MigrationConflict(
                    f"migration {self.current.id} is {self.current.state}")
            self._seq += 1
            mig = Migration(
                id=f"mig-{self._seq:04d}", model=model, source=source,
                target=target, mode=mode, weight=weight,
                started_at=self._clock(),
                source_snapshot=dict(source_snapshot or {}))
            self.current = mig
        self._emit("migration_started", migration_id=mig.id, model=model,
                   source=source, target=target, mode=mode, weight=weight,
                   **{f"source_{k}": v for k, v in mig.source_snapshot.items()})
        return mig

    def observe(self, live_prefixes: int, pending: int) -> Migration | None:
        """The lazy drained check — called on progress reads and after
        request completions with the CURRENT source counts. migrating →
        drained when both hit 0; emits migration_progress when the counts
        move and migration_drained exactly once (the transition happens
        under the lock, so concurrent observers can't double-fire)."""
        with self._lock:
            mig = self.current
            if mig is None or mig.state != MIGRATING:
                return mig
            moved = (live_prefixes, pending) != mig.last_observed
            mig.last_observed = (live_prefixes, pending)
            drained = live_prefixes == 0 and pending == 0
            if drained:
                mig.state = DRAINED
                mig.drained_at = self._clock()
        if drained:
            self._emit("migration_drained", migration_id=mig.id,
                       source=mig.source, target=mig.target,
                       drained_after_s=round(
                           mig.drained_at - mig.started_at, 2))
        elif moved:
            self._emit("migration_progress", migration_id=mig.id,
                       source=mig.source, target=mig.target,
                       live_prefixes=live_prefixes, in_flight=pending)
        return mig

    def abort(self) -> Migration:
        """migrating|drained → aborted. The routing pre-filter deactivates
        with `active`; the ring was never touched, so selection returns
        byte-identical to pre-migration. Raises MigrationConflict from any
        other state."""
        with self._lock:
            mig = self.current
            if mig is None or not mig.active:
                raise MigrationConflict("no active migration to abort")
            mig.state = ABORTED
        self._emit("migration_aborted", migration_id=mig.id,
                   source=mig.source, target=mig.target, mode=mig.mode)
        return mig

    def complete(self) -> Migration:
        """drained → completed. 409 from ANY other state — there is no
        force flag; an undrained source cannot be declared migrated."""
        with self._lock:
            mig = self.current
            if mig is None or mig.state != DRAINED:
                state = mig.state if mig else "idle"
                raise MigrationConflict(
                    f"complete requires state drained, not {state}")
            mig.state = COMPLETED
        self._emit("migration_complete", migration_id=mig.id,
                   source=mig.source, target=mig.target,
                   routed=dict(mig.routed))
        return mig

    # --- accounting ---------------------------------------------------------

    def note_route(self, replica_id: str, reason: str) -> None:
        """Bump the routed counters the progress payload reports."""
        mig = self.active()
        if mig is None:
            return
        with self._lock:
            if reason == "migration_target" and replica_id == mig.target:
                mig.routed["target_new"] += 1
            elif replica_id == mig.source and reason == "affinity_warm":
                mig.routed["source_warm"] += 1
