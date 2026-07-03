# CLAUDE.md — baseten-mvp

Agentic inference control plane on Baseten. Read README.md for architecture.

## Build & test
- Tests run per package (the tests dirs share a module name):
  `(cd services/router && python3 -m pytest tests -q)` ·
  `(cd services/llm && python3 -m pytest tests -q)` ·
  `(cd benchmarks && python3 -m pytest tests -q)` — all green before commit.
- Local stack: `./scripts/run_local_stack.sh` (sims by default; live via env).

## Rules (do not violate)
1. **Provenance**: every number shown anywhere (README, devboard, site/)
   traces to a file in `benchmarks/raw/`. No fabricated or remembered values.
2. **Keys are env-only** (`BASETEN_API_KEY`, `RUNPOD_API_KEY`) — never in
   files, args, or commits.
3. **Spend guard**: nothing that bills runs without explicit human approval;
   `deploy/runpod/pod.py` enforces the ledger + cap; always run the shutdown
   checklist in `deploy/LIVE_SETUP.md` after live sessions.
4. **No keys/GPU/network in tests**: adapters fall back to the sim when
   `*_BASE_URL` is unset; all I/O is injectable; decision logic stays pure.
5. **Agent allowlist is closed**: quarantine, probe, reinstate, resolve,
   escalate. Learning (learning/) tunes parameters, never adds actions.
6. **Config over code**: new model = registry + policy YAML entry
   (configs/), never router changes. Baseten surfaces are adapter classes.
7. Adapters and tools stay stdlib-only; FastAPI/httpx live in the service
   layers only.

## Conventions
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`).
- Platform friction discovered first-hand goes in `docs/FRICTION_LOG.md`
  (what → happened → cost → workaround → what the product could do).
- Resolved incidents auto-append episodes to `learning/episodes/live.jsonl`;
  regenerate the backfill with `python3 learning/build_episodes.py`.
- Use the `baseten-docs` agent for any Baseten platform question — it cites
  doc URLs instead of answering from memory.
