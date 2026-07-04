#!/usr/bin/env python3
"""Record a real Reliability Console session to a frame-accurate JSON.

Polls every board endpoint (+ the placement SSE) at a fixed cadence while a
real drill runs, timestamping each frame relative to session start. The output
(site/session-recording.json) is what the static console replays at true
speed — a recording of a real incident on real infrastructure, not mock data.

    # with the live stack up (router on :PORT), in another shell:
    python3 tools/replay/record_session.py --router http://localhost:8090 \
        --seconds 90 --fire-drill

Every value in the recording comes from a live endpoint response.
"""
import argparse
import json
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def record_feed(router, frames, t0, stop):
    """Tail the placement SSE, appending each item with its relative ts."""
    try:
        req = urllib.request.Request(f"{router}/v1/placement/feed")
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw in resp:
                if stop.is_set():
                    return
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:"):
                    try:
                        item = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    frames.append({"t": round(time.monotonic() - t0, 2),
                                   "kind": "feed", "item": item})
    except Exception:  # noqa: BLE001 — SSE ends when the stack stops
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--router", default="http://localhost:8090")
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--model", default="qwen3-8b")
    ap.add_argument("--rps", type=float, default=1.5)
    ap.add_argument("--drill-latency", type=float, default=1500)
    ap.add_argument("--label", default="live capture — real Baseten T4 + Model APIs")
    ap.add_argument("--fire-drill", action="store_true",
                    help="POST /v1/dev/drill 8s in (server-side chaos)")
    ap.add_argument("--out", default=str(REPO / "site" / "session-recording.json"))
    args = ap.parse_args()
    router = args.router.rstrip("/")

    t0 = time.monotonic()
    frames = []
    stop = threading.Event()
    feed_thread = threading.Thread(
        target=record_feed, args=(router, frames, t0, stop), daemon=True)
    feed_thread.start()

    # warm + drive traffic server-side for the whole window
    post(f"{router}/v1/dev/load",
         {"model": args.model, "rps": args.rps, "seconds": args.seconds})

    fired = False
    deadline = time.monotonic() + args.seconds
    print(f"recording {args.seconds}s @ {args.interval}s cadence …")
    while time.monotonic() < deadline:
        t = round(time.monotonic() - t0, 2)
        if args.fire_drill and not fired and t >= 8:
            post(f"{router}/v1/dev/drill",
                 {"model": args.model, "latency_ms": args.drill_latency})
            fired = True
            print(f"  [{t:6.1f}s] fired drill")
        frame = {"t": t, "kind": "poll"}
        for key, path in (("hero", "/v1/metrics/hero"),
                          ("slo", "/v1/metrics/slo"),
                          ("pools", "/v1/pools"),
                          ("incidents", "/v1/incidents"),
                          ("releases", "/v1/releases/active"),
                          ("episodes", "/v1/learning/episodes?limit=12")):
            try:
                frame[key] = get(f"{router}{path}")
            except Exception:  # noqa: BLE001
                frame[key] = None
        frames.append(frame)
        live = frame.get("incidents") or []
        mark = next((i for i in live if i.get("live")), None)
        if mark:
            print(f"  [{t:6.1f}s] LIVE incident {mark['id']} "
                  f"mttr {mark['mttr_s']}s")
        time.sleep(args.interval)

    # drain: keep recording until no incident is live (so playback ends
    # calm), capped so a stuck incident can't record forever.
    drain_end = time.monotonic() + 30
    while time.monotonic() < drain_end:
        t = round(time.monotonic() - t0, 2)
        frame = {"t": t, "kind": "poll"}
        for key, path in (("hero", "/v1/metrics/hero"),
                          ("slo", "/v1/metrics/slo"),
                          ("pools", "/v1/pools"),
                          ("incidents", "/v1/incidents"),
                          ("releases", "/v1/releases/active"),
                          ("episodes", "/v1/learning/episodes?limit=12")):
            try:
                frame[key] = get(f"{router}{path}")
            except Exception:  # noqa: BLE001
                frame[key] = None
        frames.append(frame)
        if not any(i.get("live") for i in (frame.get("incidents") or [])):
            print(f"  [{t:6.1f}s] drained — all incidents resolved")
            break
        time.sleep(args.interval)

    stop.set()
    frames.sort(key=lambda f: f["t"])
    # static context the console needs alongside the timeline
    deploy = json.loads((REPO / "demo" / "deploy-timeline.json").read_text())
    out = {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": args.label,
        "duration_s": args.seconds,
        "deploy_timeline": deploy,
        "frames": frames,
    }
    Path(args.out).write_text(json.dumps(out) + "\n")
    polls = sum(1 for f in frames if f["kind"] == "poll")
    feeds = sum(1 for f in frames if f["kind"] == "feed")
    incs = {i["id"] for f in frames if f["kind"] == "poll"
            for i in (f.get("incidents") or [])}
    print(f"\nwrote {args.out}: {polls} polls + {feeds} feed items, "
          f"incidents {sorted(incs)}")


if __name__ == "__main__":
    main()
