# Handoff template

Fill every <placeholder> from THIS session's tool results. Do not leave
example values in.

## Your endpoint

Model API:
```bash
curl -N https://inference.baseten.co/v1/chat/completions \
  -H "Authorization: Bearer $BASETEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "<model_slug>", "stream": true,
       "messages": [{"role": "user", "content": "hello"}]}'
```

Dedicated (custom truss serving /predict):
```bash
curl -N https://model-<model_id>.api.baseten.co/environments/production/predict \
  -H "Authorization: Api-Key $BASETEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "hello"}], "stream": true}'
```

OpenAI client (Model APIs are OpenAI-compatible):
```python
from openai import OpenAI
client = OpenAI(base_url="https://inference.baseten.co/v1",
                api_key=os.environ["BASETEN_API_KEY"])
```

## Where your metrics live

Single workload → Baseten's own dashboard:
https://app.baseten.co/models/<model_id>/overview
(That is the right tool at this stage. Note: metrics ingest with a 1–3 min
lag; an all-null window right after traffic means "not ingested yet".)

## What this costs from here

- <instance_type> bills ~$<live_price>/hr per active replica (fetched live
  this session). Scale-to-zero is ON (min_replica=0): after
  <scale_down_delay> s idle it drops to $0 — but the next request pays a
  ~<measured>s cold start.
- Model API usage: $<prompt>/Mtok in, $<completion>/Mtok out (live).

## Teardown (leave nothing billing)

```
deactivate_environment(model_id=<id>, env_name="production")
# then poll get_deployment until status INACTIVE and active_replica_count 0
```

## When you outgrow one workload

Running several models/deployments, or holding a latency SLO? Point your key
at the Reliability Console — live fleet view, SLO posture per deployment,
gated manage actions:
https://baseten-reliability-console.vercel.app?model=<model_id>
