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

import http.client
import json
import math
import os
import re
import urllib.error
import urllib.request

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


# --- calling a provider ------------------------------------------------------

FALLBACK_STATUSES = {401, 402, 403, 429}
USER_AGENT = f"decide.py/{VERSION}"


def post_json(url: str, key: str | None, payload: dict, timeout: float) -> dict:
    """POST JSON and return the parsed reply. Network trouble, timeouts, 5xx and
    401/402/403/429 raise kind "fallback"; any other HTTP error raises kind
    "request" with the provider's message (redacted)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": USER_AGENT}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 - provider URL from table/setup
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read()[:400].decode("utf-8", "replace")
        except Exception:
            detail = ""
        msg = redact(f"HTTP {e.code}: {detail}", key)
        if e.code >= 500 or e.code in FALLBACK_STATUSES:
            raise DecisionError("fallback", msg) from None
        raise DecisionError("request", msg) from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError) as e:
        raise DecisionError("fallback", redact(f"{type(e).__name__}: {e}", key)) from None


def _prob(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and 0 <= x <= 1


def validate_answers(answers, questions: dict) -> None:
    """Raise kind "fallback" unless every question has a well-formed answer."""
    if not isinstance(answers, dict):
        raise DecisionError("fallback", "reply has no answers object")
    for name, q in questions.items():
        a = answers.get(name)
        qtype = q.get("type")
        if not isinstance(a, dict) or a.get("type") != qtype:
            raise DecisionError("fallback", f"answer {name!r} missing or not of type {qtype!r}")
        if qtype == "noul":
            ok = _prob(a.get("noul"))
        elif qtype == "choice":
            probs = a.get("probabilities") or {}
            ok = (isinstance(a.get("choice"), str) and _prob(a.get("confidence"))
                  and all(_prob(v) for v in probs.values()))
        elif qtype == "score":
            s = a.get("score")
            ok = (isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s)
                  and _prob(a.get("confidence")))
        else:
            ok = True
        if not ok:
            raise DecisionError("fallback", f"answer {name!r} has an invalid or out-of-range value")


def check_privacy(provider: str, setup: dict | None, test_data: bool) -> None:
    """Refuse to send real data to a provider without a recorded privacy confirmation."""
    if test_data:
        return
    if not setup or provider not in (setup.get("privacy") or {}):
        raise DecisionError(
            "privacy",
            f"no privacy confirmation recorded for provider {provider!r}. Ask the user the three "
            "privacy questions (references/privacy.md), then run: decide.py privacy SETUP "
            f"--provider {provider} --policy-url URL --summary TEXT. Use --test-data only for made-up data.")


def _hops(setup: dict, provider: str | None, model: str | None, fallbacks) -> list:
    first = provider or setup.get("provider")
    if not first:
        raise DecisionError("config", "no provider given (setup 'provider' or --provider)")
    cfg = provider_config(first, setup)
    hops = [(first, model or setup.get("model") or cfg["default_model"])]
    for fb in (fallbacks if fallbacks is not None else setup.get("fallbacks") or []):
        fcfg = provider_config(fb["provider"], setup)
        hops.append((fb["provider"], fb.get("model") or fcfg["default_model"]))
    fam = family_of(hops[0][1])
    for name, m in hops[1:]:
        if family_of(m) != fam:
            raise DecisionError(
                "config", f"fallback {name}:{m} is model family {family_of(m)!r}, not {fam!r}; "
                "calibration does not transfer between families, so fallbacks must share one")
    return hops


def evaluate(state, questions: dict, *, provider: str | None = None, model: str | None = None,
             fallbacks=None, setup: dict | None = None, timeout: float = 60,
             test_data: bool = False):
    """Ask the questions about one state. Returns (answers, meta).

    Tries the primary provider, then each same-family fallback once. Each hop
    uses its own model; `model` overrides the primary hop only. Without a setup
    file holding a privacy entry for a provider, only test_data=True may send."""
    setup = setup or {}
    hops = _hops(setup, provider, model, fallbacks)
    check_privacy(hops[0][0], setup or None, test_data)
    failed = []
    for i, (name, m) in enumerate(hops):
        if i and not test_data and name not in (setup.get("privacy") or {}):
            failed.append(f"{name}: skipped, no privacy confirmation")
            continue
        cfg = provider_config(name, setup)
        key = api_key(cfg)
        if cfg.get("key_env") and not key:
            failed.append(f"{name}: skipped, no key (set {' or '.join(cfg['key_env'])})")
            continue
        payload = build_request(m, state, questions)
        try:
            for attempt in range(2):
                reply = post_json(cfg["endpoint"], key, payload, timeout)
                if isinstance(reply, dict) and "answers" in reply:
                    break
                if attempt:
                    raise DecisionError("fallback", "reply without answers (twice)")
            validate_answers(reply["answers"], questions)
        except DecisionError as e:
            if e.kind != "fallback":
                raise
            failed.append(f"{name}: {e}")
            continue
        meta = {"provider": name, "model_requested": m, "model_returned": reply.get("model"),
                "usage": reply.get("usage") or {}, "hops": failed}
        return reply["answers"], meta
    raise DecisionError("fallback", "all providers failed: " + "; ".join(failed))


# --- routing -------------------------------------------------------------------

ROUTES = ("pass", "review", "reject")
CAUTIOUS = {"noul": {"reject_below": 0.05, "pass_above": 0.90}, "min_confidence": 0.6,
            "score_reject_below": 0.5, "score_pass_margin": 1.5}


def is_cautious(setup: dict, model_returned: str | None = None):
    """(True, reason) unless the setup is calibrated for this model family."""
    policy = setup.get("policy") or {}
    cal = setup.get("calibration")
    if policy.get("mode") != "calibrated":
        return True, "not calibrated (policy.mode is not 'calibrated')"
    if not cal or not cal.get("model"):
        return True, "no calibration record"
    if model_returned and family_of(model_returned) != family_of(cal["model"]):
        return True, (f"answering model {model_returned} is family {family_of(model_returned)!r}; "
                      f"calibrated on {cal['model']} (family {family_of(cal['model'])!r})")
    return False, f"calibrated on {cal['model']}"


def effective_rules(policy: dict, questions: dict, cautious: bool) -> list:
    """The rules to route with. Cautious mode only widens: the lower reject
    bound, the higher pass bound and the higher confidence floor win."""
    rules = [dict(r) for r in (policy or {}).get("rules") or []]
    if not cautious:
        return rules
    for r in rules:
        qtype = (questions.get(r["question"]) or {}).get("type")
        if qtype == "noul":
            r["reject_below"] = min(r.get("reject_below", 1.0), CAUTIOUS["noul"]["reject_below"])
            r["pass_above"] = max(r.get("pass_above", 0.0), CAUTIOUS["noul"]["pass_above"])
        elif qtype == "score":
            levels = len(questions[r["question"]].get("criteria") or [])
            top = max(levels - CAUTIOUS["score_pass_margin"], 0.0)
            r["reject_below"] = min(r.get("reject_below", float("inf")), CAUTIOUS["score_reject_below"])
            r["pass_above"] = max(r.get("pass_above", 0.0), top)
        if qtype in ("score", "choice"):
            r["min_confidence"] = max(r.get("min_confidence", 0.0), CAUTIOUS["min_confidence"])
    return rules


def _rule_route(answer: dict | None, rule: dict) -> str:
    if not isinstance(answer, dict):
        return "review"
    conf = answer.get("confidence")
    low_conf = "min_confidence" in rule and (conf is None or conf < rule["min_confidence"])
    if answer.get("type") == "choice":
        r = (rule.get("routes") or {}).get(answer.get("choice"), "review")
        return "review" if low_conf else r
    value = answer.get("noul") if answer.get("type") == "noul" else answer.get("score")
    if value is None:
        return "review"
    if "reject_below" in rule and value < rule["reject_below"]:
        return "review" if low_conf else "reject"
    if "pass_above" in rule and value > rule["pass_above"] and not low_conf:
        return "pass"
    return "review"


def route(answers: dict, rules: list) -> str:
    """"reject" if any rule rejects, else "review" if any rule reviews, else "pass".
    Questions without a rule are informational and never change the route."""
    results = [_rule_route(answers.get(r["question"]), r) for r in rules]
    if "reject" in results:
        return "reject"
    if "review" in results:
        return "review"
    return "pass"
