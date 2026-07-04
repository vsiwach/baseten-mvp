#!/usr/bin/env python3
"""Real inference smoke test against the MCP-activated Baseten deployment.

Sends streaming chat requests to the production environment endpoint,
measures TTFT / total latency / chunk count, writes a provenance CSV to
benchmarks/raw/. Auth via BASETEN_API_KEY env only.
"""
import csv
import json
import os
import sys
import time
import urllib.request

MODEL_ID = "3ydn1e43"
URL = f"https://model-{MODEL_ID}.api.baseten.co/environments/production/predict"
KEY = os.environ["BASETEN_API_KEY"]

PROMPTS = [
    "Reply with exactly: warmup ok",
    "In one sentence, what is a KV cache?",
    "Name two causes of GPU cold starts. Be brief.",
    "One-line answer: what does p99 latency measure?",
    "Briefly: why pin dependency versions in serving containers?",
    "In one sentence, what is scale-to-zero?",
    "One short sentence: what is TTFT?",
]

def one(prompt, max_tokens=48):
    body = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "stream": True,
    }).encode()
    req = urllib.request.Request(URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {KEY}",
    })
    t0 = time.monotonic()
    first = None
    chunks = 0
    status = 0
    err = ""
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            status = resp.status
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:") and line != "data: [DONE]":
                    if first is None:
                        first = time.monotonic()
                    chunks += 1
    except Exception as e:  # noqa: BLE001
        err = str(e)[:120]
    t1 = time.monotonic()
    return {
        "ts": round(time.time(), 3),
        "http_status": status,
        "ttft_ms": round((first - t0) * 1000, 1) if first else "",
        "total_ms": round((t1 - t0) * 1000, 1),
        "chunks": chunks,
        "error": err,
    }

def main():
    out = sys.argv[1]
    rows = []
    for i, p in enumerate(PROMPTS):
        r = one(p)
        r["req_id"] = f"live-{i}"
        r["label"] = "warmup" if i == 0 else "measured"
        rows.append(r)
        print(f"{r['req_id']} status={r['http_status']} ttft={r['ttft_ms']}ms "
              f"total={r['total_ms']}ms chunks={r['chunks']} {r['error']}")
    fields = ["ts", "req_id", "label", "http_status", "ttft_ms", "total_ms",
              "chunks", "error"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")

if __name__ == "__main__":
    main()
