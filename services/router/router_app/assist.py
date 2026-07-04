"""Deploy-assist agent as a platform endpoint — docs-grounded RAG whose
reasoning runs on a Baseten-hosted model THROUGH THIS ROUTER.

POST /v1/assist {"question": "...", "deployment_id": "...", "model_id": "..."}

Pipeline: retrieve the top docs pages from the local corpus (tools/kb,
term-frequency search — the same index behind the interactive baseten-docs
agent), optionally pull the deployment's recent logs from the management API,
then ask a catalog model (default glm-4.7) to answer WITH CITATIONS ONLY from
the provided pages. The completion goes through the router's own chat path,
so the copilot's inference appears in the placement feed and cost ledger like
any other workload — the platform serves its own copilot.
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_KB = _REPO / "tools" / "kb" / "baseten"

sys.path.insert(0, str(_REPO / "tools" / "kb"))

SYSTEM = (
    "You are a Baseten deployment assistant. Answer ONLY from the provided "
    "documentation excerpts and log lines. Cite the Source URL of every doc "
    "page you rely on. If the excerpts don't answer the question, say so "
    "plainly. Be concise and operator-focused: the reader is mid-deploy."
)


def retrieve(question: str, top: int = 4, chars: int = 1800) -> list[dict]:
    """Top KB pages for the question: [{title, url, excerpt}]."""
    from search import search  # tools/kb/search.py
    out = []
    for _score, page, _snippet in search(str(_KB), question, top):
        body = (_KB / page["file"]).read_text(errors="replace")
        out.append({"title": page["title"], "url": page["url"],
                    "excerpt": body[:chars]})
    return out


def deployment_logs(model_id: str, deployment_id: str,
                    limit: int = 12) -> list[str]:
    """Recent log lines for a deployment (management API; needs
    BASETEN_API_KEY). Best-effort: assist works without them."""
    key = os.environ.get("BASETEN_API_KEY")
    if not key:
        return []
    url = (f"https://api.baseten.co/v1/models/{model_id}"
           f"/deployments/{deployment_id}/logs")
    req = urllib.request.Request(url,
                                 headers={"Authorization": f"Api-Key {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            logs = json.loads(resp.read()).get("logs", [])
    except Exception:  # noqa: BLE001 — assist must degrade, not die
        return []
    return [f"[{l.get('level', '?')}] {l.get('message', '')[:300]}"
            for l in logs[:limit]]


def build_prompt(question: str, pages: list[dict], logs: list[str]) -> str:
    parts = [SYSTEM, "\n## Documentation excerpts"]
    for p in pages:
        parts.append(f"\n### {p['title']}\nSource: {p['url']}\n{p['excerpt']}")
    if logs:
        parts.append("\n## Recent deployment log lines (newest first)")
        parts.extend(logs)
    parts.append(f"\n## Operator question\n{question}\n"
                 "\nAnswer with citations: /no_think")
    return "\n".join(parts)


def extract_citations(answer: str, pages: list[dict]) -> list[dict]:
    cited = [{"title": p["title"], "url": p["url"]} for p in pages
             if p["url"] in answer]
    return cited or [{"title": p["title"], "url": p["url"]} for p in pages]


def run(state, question: str, model: str = "glm-4.7",
        model_id: str | None = None,
        deployment_id: str | None = None) -> dict:
    """Full assist pipeline over the router's own chat path."""
    pages = retrieve(question)
    logs = deployment_logs(model_id, deployment_id) \
        if (model_id and deployment_id) else []
    body = {"model": model, "max_tokens": 500,
            "messages": [{"role": "user",
                          "content": build_prompt(question, pages, logs)}]}
    resp, choice = state.proxy_chat(model, body, {})
    data = resp.json()
    answer = data["choices"][0]["message"]["content"]
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip()
    return {
        "answer": answer,
        "citations": extract_citations(answer, pages),
        "log_lines_used": len(logs),
        "served_by": {"replica": choice.replica_id,
                      "model": model,
                      "ttft_ms": float(resp.headers.get("X-TTFT-Ms", 0)),
                      "est_cost_usd": float(resp.headers.get("X-Est-Cost", 0))},
    }
