#!/usr/bin/env python3
"""decide.py - a small client for decision models (TypeSafe System One wire format).

Decision models answer typed questions about content (yes/no "noul", "choice",
"score") with probabilities instead of text, for a tiny fraction of a chat
model's cost. This file is both a command-line tool and an importable module:

    python3 decide.py providers
    python3 decide.py ask --test-data --provider opencode --state "Server down" --yes "Urgent?"
    python3 decide.py run leads.decisions.json --input leads.jsonl --out routed.jsonl
    python3 decide.py calibrate leads.decisions.json --labels labeled.jsonl

    from decide import load_setup, evaluate, route, effective_rules

Standard library only (Python 3.9+). Keys come from environment variables and
are never printed. See the skill's SKILL.md for the workflow.
"""
from __future__ import annotations

import json
import os
import re

VERSION = "0.1.0"

# Built-in providers: only hosts verified with a live System One call.
# Unverified hosts go in a setup file's "providers" block (see references/providers.md).
PROVIDERS = {
    "typesafe": {
        "endpoint": "https://api.typesafe.ai/v1/systemone",
        "key_env": ["TYPESAFE_AI_API_KEY", "TYPESAFE_API_KEY"],
        "models_url": "https://api.typesafe.ai/v1/models",
        "default_model": "jev-latest",
        "docs": "https://docs.typesafe.ai",
        "verified": True,
    },
    "openrouter": {
        "endpoint": "https://openrouter.ai/api/v1/systemone",
        "key_env": ["OPENROUTER_API_KEY"],
        "models_url": None,  # /api/v1/models does not list decision models
        "default_model": "typesafe/jev-1.14",
        "docs": "https://openrouter.ai/docs",
        "verified": True,
    },
    "opencode": {
        "endpoint": "https://opencode.ai/inference/systemone/v1/systemone",
        "key_env": ["OPENCODE_API_KEY"],
        "models_url": None,
        "default_model": "jev-1.13-free",
        "docs": "https://opencode.ai/docs/console/models/",
        "verified": True,
    },
    "asi": {
        "endpoint": "https://inference.asicloud.cudos.org/v1/systemone",
        "key_env": ["ASI_API_KEY"],
        "models_url": None,
        "default_model": "super-decider",
        "docs": "https://docs.asicloud.cudos.org",
        "verified": True,
    },
    "perplexity": {
        "endpoint": "https://api.perplexity.ai/v1/decisions",
        "key_env": ["PERPLEXITY_API_KEY"],
        "models_url": None,
        "default_model": "pplx-decider-latest",
        "docs": "https://docs.perplexity.ai",
        "verified": True,
    },
}

# Model-id prefix -> family. Calibration and fallbacks are tied to a family:
# thresholds fitted on one family do not transfer to another.
FAMILIES = {
    "jev": "jev",
    "typesafe/jev": "jev",
    "~typesafe/jev": "jev",
    "typesafe-ai/jev": "jev",
    "pplx-decider": "pplx-decider",
    "perplexity/pplx-decider": "pplx-decider",
    "~perplexity/pplx-decider": "pplx-decider",
    "d1": "liquid-d1",
    "liquid/d1": "liquid-d1",
    "~liquid/d1": "liquid-d1",
    "super-decider": "asi-super-decider",
}


def family_of(model: str) -> str:
    """The model family for a model id (longest known prefix), else the id itself."""
    best = ""
    for prefix in FAMILIES:
        if model.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return FAMILIES[best] if best else model


class DecisionError(Exception):
    """kind: "request" (fix the request), "fallback" (try another provider),
    "privacy" (no confirmed privacy record), "config" (setup or usage problem)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


_AUTH_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.I),
    re.compile(r"((?:api[_-]?key|x-api-key)[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._~+/=-]+", re.I),
]


def redact(text: str, *secrets) -> str:
    """Remove the given secrets and anything that looks like a bearer token or API key."""
    for s in secrets:
        if s:
            text = text.replace(s, "[REDACTED]")
    for pat in _AUTH_PATTERNS:
        text = pat.sub(r"\1[REDACTED]", text)
    return text


def provider_config(name: str, setup: dict | None = None) -> dict:
    """A provider's settings; a setup file's "providers" block adds or overrides
    entries, which are always treated as unverified."""
    extra = (setup or {}).get("providers") or {}
    if name in extra:
        cfg = dict(PROVIDERS.get(name, {}))
        cfg.update(extra[name])
        cfg.setdefault("models_url", None)
        cfg.setdefault("docs", "")
        if isinstance(cfg.get("key_env"), str):
            cfg["key_env"] = [cfg["key_env"]]
        cfg["verified"] = False
        cfg["name"] = name
        return cfg
    if name not in PROVIDERS:
        raise DecisionError("config", f"unknown provider {name!r}; known: {', '.join(PROVIDERS)}")
    cfg = dict(PROVIDERS[name])
    cfg["name"] = name
    return cfg


def api_key(cfg: dict) -> str | None:
    """The first set environment variable among the provider's key_env names."""
    for var in cfg.get("key_env") or []:
        value = os.environ.get(var)
        if value:
            return value
    return None


def build_state(reference: str | None, item):
    """Combine the setup's reference text (definitions, examples) with one item."""
    if reference:
        return {"reference": reference, "item": item}
    return item


def build_request(model: str, state, questions: dict) -> dict:
    return {"model": model, "state": state, "questions": questions}
