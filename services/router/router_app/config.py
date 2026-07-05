"""Config loading for the router: inference-registry.yaml + routing-policy.yaml.

Config files live in configs/ in development and are copied to the image
root in Docker; override locations with REGISTRY_PATH / ROUTING_POLICY_PATH.
"""

import os
from pathlib import Path

import yaml

def _default_root() -> Path:
    """Repo root in development; the package's grandparent (/srv) in the
    container, where the Dockerfile copies both YAML files."""
    here = Path(__file__).resolve()
    return here.parents[3] if len(here.parents) > 3 else here.parents[1]


def registry_path() -> Path:
    return Path(os.environ.get(
        "REGISTRY_PATH", _default_root() / "configs" / "inference-registry.yaml"))


def policy_path() -> Path:
    return Path(os.environ.get(
        "ROUTING_POLICY_PATH", _default_root() / "configs" / "routing-policy.yaml"))


def placement_path() -> Path:
    return Path(os.environ.get(
        "PLACEMENT_POLICY_PATH", _default_root() / "configs" / "placement-policy.yaml"))


def load_placement(path: Path | None = None) -> dict:
    """Placement policy (Phase 8). Absent file → empty policy (no-op)."""
    p = path or placement_path()
    if not p.exists():
        return {"pools": [], "compliance": {}}
    return yaml.safe_load(p.read_text()) or {"pools": [], "compliance": {}}


def load_registry(path: Path | None = None) -> dict:
    """Returns {model_name: {tier, target, ...}} from the backends section."""
    data = yaml.safe_load((path or registry_path()).read_text()) or {}
    return data.get("backends") or {}


def load_policy(path: Path | None = None) -> dict:
    data = yaml.safe_load((path or policy_path()).read_text()) or {}
    data.setdefault("tiers", {})
    data.setdefault("cost_table", {})
    data.setdefault("cache", {"enabled": False})
    data.setdefault("endpoints", {})
    data.setdefault("affinity", {"enabled": False, "prefix_tokens": 32,
                                 "capacity": 8})
    return data


def replicas_for(policy: dict, model: str) -> list[dict]:
    """Endpoint entries for a model as replica dicts: each gets a stable `id`
    (defaults to the url) so the affinity ring and KV state can key on it.
    Baseten management ids (model_id/deployment_id) ride along when the
    endpoint entry declares them — manage-options previews and gated writes
    use them; routing never does."""
    out = []
    for ep in policy.get("endpoints", {}).get(model, []):
        rep = {"id": ep.get("id", ep["url"]), "provider": ep["provider"],
               "url": ep["url"]}
        for extra in ("model_id", "deployment_id"):
            if extra in ep:
                rep[extra] = ep[extra]
        out.append(rep)
    return out
