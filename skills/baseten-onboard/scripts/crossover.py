#!/usr/bin/env python3
"""Break-even math for Baseten Model API (serverless) vs Dedicated Inference.

Reads a JSON object on stdin — ALL prices must be fetched live in-session
(list_instance_type_prices / list_model_apis); this script only does the
arithmetic and shows its work:

  {"instance_usd_per_min": 0.01504,
   "utilization_hours_per_month": 730,
   "model_api_usd_per_mtok_prompt": 0.10,
   "model_api_usd_per_mtok_completion": 0.50,
   "prompt_completion_ratio": 3.0,          # optional, default 3.0
   "user_tokens_per_month": 300000}          # optional, for the cost table

Usage:  echo '<json>' | python3 crossover.py
        python3 crossover.py --self-test
"""
import json
import sys


def blended_usd_per_mtok(p_prompt, p_completion, ratio):
    return (ratio * p_prompt + p_completion) / (ratio + 1.0)


def compute(inp):
    ratio = float(inp.get("prompt_completion_ratio", 3.0))
    blended = blended_usd_per_mtok(
        float(inp["model_api_usd_per_mtok_prompt"]),
        float(inp["model_api_usd_per_mtok_completion"]), ratio)
    dedicated_floor = (float(inp["instance_usd_per_min"]) * 60.0 *
                       float(inp["utilization_hours_per_month"]))
    break_even_tokens = (dedicated_floor / blended) * 1_000_000
    return {"blended_usd_per_mtok": blended,
            "dedicated_floor_usd_per_month": dedicated_floor,
            "break_even_tokens_per_month": break_even_tokens}


def main():
    if "--self-test" in sys.argv:
        r = compute({"instance_usd_per_min": 0.01,
                     "utilization_hours_per_month": 100,
                     "model_api_usd_per_mtok_prompt": 1.0,
                     "model_api_usd_per_mtok_completion": 1.0,
                     "prompt_completion_ratio": 3.0})
        # blended = 1.0; floor = 0.01*60*100 = 60; break-even = 60M tokens
        assert abs(r["blended_usd_per_mtok"] - 1.0) < 1e-9, r
        assert abs(r["break_even_tokens_per_month"] - 60_000_000) < 1e-3, r
        print("self-test OK")
        return
    inp = json.load(sys.stdin)
    r = compute(inp)
    print(f"blended Model API price : ${r['blended_usd_per_mtok']:.4f}/Mtok "
          f"(ratio {inp.get('prompt_completion_ratio', 3.0)}:1)")
    print(f"dedicated monthly floor : ${r['dedicated_floor_usd_per_month']:.2f} "
          f"({inp['instance_usd_per_min']}/min x 60 x "
          f"{inp['utilization_hours_per_month']}h)")
    print(f"break-even              : {r['break_even_tokens_per_month']:,.0f} tokens/month")
    vol = inp.get("user_tokens_per_month")
    if vol:
        print(f"\n{'tokens/mo':>15} {'Model API':>12} {'Dedicated':>12}")
        for mult in (1, 10, 100):
            t = float(vol) * mult
            api = t / 1e6 * r["blended_usd_per_mtok"]
            print(f"{t:>15,.0f} {api:>11.2f}$ "
                  f"{r['dedicated_floor_usd_per_month']:>11.2f}$")
        cheaper = ("Model API" if float(vol) < r["break_even_tokens_per_month"]
                   else "Dedicated")
        print(f"\nat your stated volume, {cheaper} is cheaper")


if __name__ == "__main__":
    main()
