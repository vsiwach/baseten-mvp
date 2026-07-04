# Competitive landscape — where this repo sits next to Baseten's own tooling

One-page positioning, written after proving both surfaces live on 2026-07-04
(evidence: evals/mcp-deploy/, evals/console-live/).

## The two layers

| | Baseten AI tools (MCP + skill) | This repo |
|---|---|---|
| **What it is** | Hosted MCP servers (api.baseten.co/mcp — 88 tools; docs.baseten.co/mcp) + an agent skill, from basetenlabs/baseten-skills | An after-deploy reliability layer: live Reliability Console (console-live/) + autonomous incident-handling router (services/router) |
| **Who drives** | A developer in the loop, via an agent (deploy, configure, promote, read logs/metrics, manage training) | The system itself: Console observes + advises; router detects, quarantines, spills, probes, reinstates — no human in the loop |
| **When it acts** | Build/deploy/operate time, on request | After deploy, continuously, at traffic time |
| **Proven here** | Full dedicated-deployment lifecycle via their MCP: activate → ready 114 s → served 7/7 → metrics → deactivate (evals/mcp-deploy/PHASE1_EVIDENCE.md) | Console renders real workspace metrics with SLO verdicts + cold-start annotation (evals/console-live/); router MTTR 8.8–9.2 s on live T4 drills (benchmarks/raw/, recorded in site-console/) |

## The boundary (kept honest everywhere)

- **Baseten's MCP+skill is the supported deploy/operate surface. Use it.**
  We deleted our own RAG deploy-assistant plans the day theirs shipped — an
  agent grounded in their MCP is strictly better than a reimplementation.
- **Observe vs control:** console-live is read-only by construction (GET-only
  proxy, 3-path allowlist). It can tell you p99 breached and why; it cannot
  fix it. Traffic-level mitigation — quarantine, spill to Model APIs,
  probe-gated reinstatement, measured MTTR — requires a router in the request
  path, which is the recorded control-plane demo.
- **Segment:** the Console is for DEDICATED-inference customers (per-deployment
  metrics exist there). Pure Model-API developers see an honest empty state —
  that segment's reliability story is rate-limit/failover handling, which
  lives in the router, not this Console.

## Why the layers compose instead of compete

Baseten's MCP gives agents hands (create/patch/promote/scale). This repo gives
the deployment a nervous system afterwards: the Console turns raw
deployment metrics into SLO posture a human can act on in seconds, and the
router closes the loop autonomously where seconds matter (voice SLO breaches
don't wait for a human to read a dashboard). The natural end state is all
three: agent-driven deploys (their MCP), continuous SLO observation
(this Console), autonomous traffic-time mitigation (this router).

## Gaps in the platform this repo currently papers over

First-hand, logged in docs/FRICTION_LOG.md: metrics ingestion lag returns
silent nulls with no data-completeness marker (#18); dashboard-scale GET
patterns trip undocumented 429s (#19); cold-start p99 pollution has no
server-side annotation (the Console detects it client-side); failed deploys
can hold environment pointers (#15); the fast cold-start path (BDN `weights:`)
is opt-in and undiscoverable (#17). Each is a place the platform could absorb
this repo's value — which is exactly the point of building it.
