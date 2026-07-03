# DEMO_SCRIPT.md — presenter storyboard

Target: **6:00** talk track + ~1:30 buffer. Two browser tabs pre-opened:
`deploy.html` (tab 1), `devboard.html` (tab 2). Board pre-warmed in
HEALTHY with the feed streaming. If venue has no network → same script,
click **Replay recorded incident** instead of **Inject chaos** in Act 3
and say the REPLAY line.

---

## Act 1 — Deploy, agent-assisted (0:00–1:15) · tab 1
**You do:** nothing yet; the timeline is already on screen. Scroll slowly
from attempt 1 to LIVE.
**Audience sees:** six real failures descending — red error blocks, each
with the agent's diagnosis and a Baseten-docs citation pill — ending in a
green LIVE node.
**The line:** "Six real failures to get Qwen3 on a T4 — and every retry
was grounded in your docs, not guesswork. That's the deploy agent."
**Timing check:** leave Act 1 by 1:15.

## Act 2 — Serve traffic (1:15–2:15) · switch to tab 2
**You do:** click **Live Board** nav (or switch tab). Point at the feed,
then the two pool cards.
**Audience sees:** requests streaming with placement reasons — realtime
traffic pinned to `baseten-l4` (affinity), batch spilling to `model-api`
(cost) — TTFT per request, sub-millisecond routing decisions; both pools
green, p99s under the rendered SLOs.
**The line:** "Live traffic, two Baseten pools, every placement decided in
under a millisecond — and you can read the router's reason on every row."

## Act 3 — Chaos on (2:15–2:45)
**You do:** click **Inject chaos** (say what it is: a real
`POST /v1/dev/chaos` against the running system — nothing staged).
**Audience sees:** state chip → amber DEGRADING; `baseten-l4` health bar
drops, TTFT p99 goes red past 500ms; slow red rows appear in the feed.
**The line:** "I'm injecting real latency into the dedicated pool. Watch
the top-right — I won't touch anything else."
**(REPLAY variant line:** "No network here, so this is the recorded trace
of the same real incident — the violet chip is honest about that.")

## Act 4 — Agentic resolution (2:45–4:00) — *the moment*
**You do:** hands off the keyboard. Optionally step back from the laptop.
**Audience sees:** ~4s in, the incident panel ignites red and the rest of
the board dims. MTTR counts up live in the hero card AND the incident
panel. Phase bar fills detect → diagnose → resolve. The agent's actions
stream in: breach detected → quarantine + spill (feed flips amber to
`model-api-spill`) → probe fail ✕ → probe pass ✓ → probe pass ✓ →
reinstated. MTTR freezes at **8.8s**; board returns to green.
**The line (say it as MTTR freezes):** "Eight point eight seconds,
detection to reinstatement, zero humans. The baseline without the agent
is on the card: never."
**Timing check:** the incident is self-timed (~13s total from click);
don't talk over the resolve — let the counter freeze in silence.

## Act 5 — Economics + learning (4:00–5:30)
**You do:** point at the cost hero card, then the learning panel; note
INC-0002 in the incident panel is now the resolved record with a
postmortem link.
**Audience sees:** blended $2.17/Mtok, −27% vs single-pool; TPOT p99 back
to ~35ms vs the 60ms voice SLO. Learning panel: the incident became an RL
episode — the exact policy parameters that ran (breach threshold 0.5,
probe every 3s, 2 probes to reinstate), the probe outcomes, and the
shaped reward (+10 resolved, −8.8 MTTR penalty, 0 escalation → +1.2).
**The line:** "Every incident pays twice: 27% cheaper serving, and a
reward-shaped episode — this is how the resolution policy gets better
without a human writing runbooks."

## Close (5:30–6:00)
**You do:** nothing on screen.
**The line:** "Everything you watched was the live system — the board is
just a window on its API. Happy to break it again in Q&A."
**Buffer use:** re-run **Inject chaos** on request (button re-arms when
HEALTHY); MTTR will land ~9s again because the policy is deterministic.

---

## Pre-flight checklist
- [ ] Replace placeholder deploy attempts in `mock-data.js` with the real
      6-attempt JSON (marked PLACEHOLDER in the file).
- [ ] Wire MockAPI fetchers to live endpoints (see DESIGN.md §6); keep
      mock-data.js loadable as fallback for REPLAY.
- [ ] External display mirrored at 1512-wide-equivalent scaling; board
      must show all panels without scroll.
- [ ] Dry-run one full chaos cycle on venue network; confirm MTTR freezes
      and buttons re-arm.
- [ ] Kill notifications / dark room test: cyan-on-dark reads at 2m.
