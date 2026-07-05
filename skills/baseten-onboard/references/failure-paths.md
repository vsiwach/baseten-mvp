# Failure paths — first-deploy playbook

Each play cites its friction-log entry (docs/FRICTION_LOG.md in
vsiwach/baseten-mvp) — these were all hit for real.

| Symptom | Play | Friction # |
|---|---|---|
| Push/deploy rejected: "GPU type not supported for your organization" | Drop to the next SKU in the ladder (T4x8x32 first for 8B-AWQ). The gate is org-level and invisible until push — nothing in the config was wrong. | #13 |
| BUILD_FAILED, or ACTIVE→crash-loop during model load | `get_deployment_logs` — and widen `start_epoch_millis` (default window is only the last 30 min; a failed build may predate it). Most common cause: unpinned transitive deps — check the requirements pin set (e.g. vllm 0.9.1 ⇄ transformers 4.53.2). Build logs may be console-only (#12) — if the API shows nothing, look at app.baseten.co. | #14, #12 |
| Deployment says ACTIVE but the environment URL returns 500 "Model is unhealthy" | The environment pointer is on a corpse from an earlier failed deploy. Probe the deployment-scoped URL (`/deployment/<id>/predict`); if THAT serves, `promote_to_environment` your good deployment. | #15 |
| "Add a payment method" at push time | Stop immediately (don't retry). Link app.baseten.co billing. Free credits do NOT unlock dedicated deploys — card required. | #4 |
| First test request 404s after things worked earlier | Scale-to-zero kicked in and deactivated deployments return 404 (not 5xx). For a testing session set `min_replica=1` temporarily — and REVERT it after (it bills while warm). | ACTIVATION_RUNBOOK |
| Metrics show zero / all-null right after traffic | Ingestion lag is 1–3 min and lag looks identical to "never served". Wait 2–3 min and re-read before concluding anything. | #18 |
| 429s on Model APIs at modest rates | Limits are account-tier (Basic-unverified 15 RPM / verified 120 RPM), per workspace. No Retry-After on some paths — back off manually. | #10, ACTIVATION_RUNBOOK |
