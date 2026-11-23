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

import argparse
import csv
import datetime
import hashlib
import http.client
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

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
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        msg = redact(f"HTTP {e.code}: {detail}", key)[:400]
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
            crit = q.get("criteria")
            ok = (isinstance(a.get("choice"), str) and _prob(a.get("confidence"))
                  and all(_prob(v) for v in probs.values())
                  and (not isinstance(crit, dict) or a["choice"] in crit))
        elif qtype == "score":
            s = a.get("score")
            crit = q.get("criteria")
            top = len(crit) - 1 if isinstance(crit, list) and crit else None
            ok = (isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s)
                  and _prob(a.get("confidence"))
                  and (top is None or -1e-6 <= s <= top + 1e-6))
        else:
            ok = True
        if not ok:
            raise DecisionError("fallback", f"answer {name!r} has an invalid or out-of-range value")


def check_privacy(provider: str, setup: dict | None, test_data: bool) -> None:
    """Refuse to send real data to a provider without a recorded privacy confirmation."""
    if test_data:
        return
    entry = ((setup or {}).get("privacy") or {}).get(provider)
    if isinstance(entry, dict) and entry.get("confirmed") and entry.get("endpoint"):
        current = provider_config(provider, setup)["endpoint"]
        if entry["endpoint"] != current:
            raise DecisionError(
                "privacy", f"the privacy confirmation for {provider!r} was given for endpoint "
                f"{entry['endpoint']}, but the provider now points at {current}; repeat the privacy "
                "check for the new endpoint (references/privacy.md)")
    if not (isinstance(entry, dict) and entry.get("confirmed")):
        raise DecisionError(
            "privacy",
            f"no privacy confirmation recorded for provider {provider!r}. Read the provider's current "
            "data terms, summarize them for the user, and get an explicit yes to all three: "
            "(1) this data is OK to send to the provider; (2) the provider's retention and training "
            "terms are acceptable; (3) whoever owns the data (employer, client) agrees, or the user is "
            "that party (references/privacy.md). Only then run: decide.py privacy SETUP "
            f"--provider {provider} --policy-url URL --summary TEXT. Never confirm on the user's "
            "behalf. Use --test-data only for made-up data.")


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
CAUTIOUS = {"noul": {"reject_below": 0.05, "pass_above": 0.90},  # nosec B105 - routing cutoffs, not passwords
            "min_confidence": 0.6,
            "score_reject_below": 0.5, "score_pass_margin": 1.5}  # nosec B105 - routing cutoffs, not passwords


def answering_model(meta: dict):
    """The model that answered: the id the provider returned, else the one requested."""
    return (meta or {}).get("model_returned") or (meta or {}).get("model_requested")


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
        if qtype in ("noul", "score"):
            if qtype == "noul":
                low, high = CAUTIOUS["noul"]["reject_below"], CAUTIOUS["noul"]["pass_above"]
            else:
                levels = len(questions[r["question"]].get("criteria") or [])
                low, high = CAUTIOUS["score_reject_below"], max(levels - CAUTIOUS["score_pass_margin"], 0.0)
            # a rule with no bounds gets both defaults; a partial rule keeps its missing bound missing
            if "reject_below" not in r and "pass_above" not in r:
                r["reject_below"], r["pass_above"] = low, high
            else:
                if "reject_below" in r:
                    r["reject_below"] = min(r["reject_below"], low)
                if "pass_above" in r:
                    r["pass_above"] = max(r["pass_above"], high)
        if qtype in ("score", "choice"):
            r["min_confidence"] = max(r.get("min_confidence", 0.0), CAUTIOUS["min_confidence"])
    return rules


def _rule_route(answer: dict | None, rule: dict) -> str:
    if not isinstance(answer, dict):
        return "review"
    conf = answer.get("confidence")
    low_conf = "min_confidence" in rule and (conf is None or conf < rule["min_confidence"])
    if answer.get("type") == "choice":
        if answer.get("choice") is None:
            return "review"
        routes = rule.get("routes")
        r = "pass" if routes is None else routes.get(answer.get("choice"), "review")
        return "review" if low_conf else r
    value = answer.get("noul") if answer.get("type") == "noul" else answer.get("score")
    if value is None:
        return "review"
    if "reject_below" in rule and value < rule["reject_below"]:
        return "review" if low_conf else "reject"
    if "pass_above" in rule and value > rule["pass_above"] and not low_conf:
        return "pass"
    return "review"


def combine_of(setup: dict) -> str:
    return ((setup or {}).get("policy") or {}).get("combine") or "all"


def route(answers: dict, rules: list, combine: str = "all") -> str:
    """combine "all" (default; screening): "reject" if any rule rejects, else
    "review" if any rule reviews, else "pass".
    combine "any" (flagging, e.g. moderation): "pass" (= flagged) if any rule
    passes, "reject" only if every rule rejects, else "review".
    Questions without a rule are informational and never change the route."""
    results = [_rule_route(answers.get(r["question"]), r) for r in rules]
    if combine == "any":
        if "pass" in results:
            return "pass"
        if results and all(x == "reject" for x in results):
            return "reject"
        return "review"
    if "reject" in results:
        return "reject"
    if "review" in results:
        return "review"
    return "pass"


# --- setup file, privacy record, cache -----------------------------------------

def load_setup(path: str) -> dict:
    """Read a setup file (<name>.decisions.json). Requires "provider" and "questions"."""
    try:
        with open(path, encoding="utf-8") as f:
            setup = json.load(f)
    except OSError as e:
        raise DecisionError("config", f"cannot read setup file {path}: {e}") from None
    except ValueError as e:
        raise DecisionError("config", f"setup file {path} is not valid JSON: {e}") from None
    if not isinstance(setup, dict):
        raise DecisionError("config", f"setup file {path} must hold a JSON object")
    for key in ("provider", "questions"):
        if not setup.get(key):
            raise DecisionError("config", f"setup file {path} is missing {key!r}")
    validate_setup(setup, path)
    if not setup.get("model"):
        setup["model"] = provider_config(setup["provider"], setup)["default_model"]
    return setup


QUESTION_TYPES = ("noul", "choice", "score")


def validate_setup(setup: dict, path: str = "setup") -> None:
    """Raise kind "config" naming the first shape problem (see references/setup-file.md)."""
    def bad(msg):
        raise DecisionError("config", f"{path}: {msg} (see references/setup-file.md and "
                            "examples/lead-vetting.decisions.json)")
    qs = setup.get("questions")
    if not isinstance(qs, dict):
        bad("'questions' must be an object mapping names to questions, not a list")
    for name, q in qs.items():
        if not isinstance(q, dict) or q.get("type") not in QUESTION_TYPES:
            bad(f"question {name!r}: 'type' must be one of noul, choice, score")
        crit = q.get("criteria")
        if q["type"] == "choice" and not isinstance(crit, dict):
            bad(f"question {name!r}: choice 'criteria' must be an object {{option: description or null}}")
        if q["type"] == "score" and not (isinstance(crit, list) and len(crit) >= 2):
            bad(f"question {name!r}: score 'criteria' must be a list of 2+ levels, lowest first")
        if q["type"] == "noul" and crit is not None and not isinstance(crit, dict):
            bad(f"question {name!r}: noul 'criteria' must be {{\"true\": ..., \"false\": ...}}")
    policy = setup.get("policy") or {}
    if not isinstance(policy, dict):
        bad("'policy' must be an object")
    good_if = policy.get("good_if")
    if good_if is not None and not (isinstance(good_if, list)
                                    and all(isinstance(c, dict) and c.get("question") in qs for c in good_if)):
        bad("'policy.good_if' must be a list like [{\"question\": \"real\", \"is\": true}] "
            "naming questions in 'questions'")
    rules = policy.get("rules") or []
    if not isinstance(rules, list):
        bad("'policy.rules' must be a list")
    for r in rules:
        if not isinstance(r, dict) or r.get("question") not in qs:
            bad(f"rule {r!r} must name a question in 'questions'")
    if policy.get("combine", "all") not in ("all", "any"):
        bad("'policy.combine' must be 'all' (screening) or 'any' (flagging)")


def save_setup(path: str, setup: dict) -> None:
    """Write atomically: a temp file in the same folder, then os.replace."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(setup, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_privacy(setup: dict, provider: str, policy_url: str, summary: str, today: str) -> dict:
    """Record the user's privacy confirmation for a provider. Call only after the
    user explicitly confirmed all three items in references/privacy.md."""
    setup.setdefault("privacy", {})[provider] = {
        "confirmed": today, "policy_url": policy_url, "summary": summary,
        "endpoint": provider_config(provider, setup)["endpoint"]}
    return setup


def cache_key(provider: str, model: str, questions: dict, reference, item) -> str:
    blob = json.dumps([provider, model, questions, reference, item],
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def default_cache_path(setup_path: str) -> str:
    base = setup_path[:-5] if setup_path.endswith(".json") else setup_path
    return base + ".cache.sqlite"


class Cache:
    """Answers keyed by cache_key(); path None disables caching."""

    def __init__(self, path: str | None):
        self.db = None
        self.lock = threading.Lock()
        if path:
            self.db = sqlite3.connect(path, check_same_thread=False)
            self.db.execute("CREATE TABLE IF NOT EXISTS answers (key TEXT PRIMARY KEY, "
                            "answers TEXT, model_returned TEXT, saved REAL)")

    def get(self, key: str):
        if not self.db:
            return None
        with self.lock:
            row = self.db.execute("SELECT answers, model_returned FROM answers WHERE key = ?",
                                  (key,)).fetchone()
        return {"answers": json.loads(row[0]), "model_returned": row[1]} if row else None

    def put(self, key: str, answers: dict, model_returned) -> None:
        if not self.db:
            return
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO answers VALUES (?, ?, ?, ?)",
                            (key, json.dumps(answers), model_returned, time.time()))
            self.db.commit()

    def close(self) -> None:
        if self.db:
            self.db.close()
            self.db = None


# --- inputs --------------------------------------------------------------------

TEXT_SUFFIXES = (".txt", ".md")


def _split(obj: dict, id_field: str, text_field):
    item = obj.get(text_field) if text_field else {k: v for k, v in obj.items() if k != id_field}
    return str(obj[id_field]), item


def read_items(source: str, fmt=None, id_field: str = "id", text_field=None):
    """Yield (id, item, error) from JSONL, CSV, a folder of .txt/.md files, or "-" (stdin JSONL).
    A bad line yields an error row naming the line; blank lines are skipped."""
    if fmt is None:
        if source == "-" or source.endswith((".jsonl", ".json", ".ndjson")):
            fmt = "jsonl"
        elif source.endswith(".csv"):
            fmt = "csv"
        elif os.path.isdir(source):
            fmt = "dir"
        else:
            raise DecisionError("config", f"cannot tell the format of {source}; use --format")
    if fmt == "dir":
        for name in sorted(os.listdir(source)):
            if name.endswith(TEXT_SUFFIXES):
                path = os.path.join(source, name)
                try:
                    with open(path, encoding="utf-8") as f:
                        yield name, f.read(), None
                except (OSError, UnicodeDecodeError) as e:
                    yield name, None, f"{name}: {type(e).__name__}"
        return
    if fmt == "csv":
        with open(source, newline="", encoding="utf-8-sig", errors="surrogateescape") as f:
            reader = csv.DictReader(f, restkey="_extra")
            for row in reader:
                n = reader.line_num
                if any(isinstance(v, str) and re.search("[\udc80-\udcff]", v)
                       for v in row.values()):
                    yield f"line {n}", None, f"line {n}: not UTF-8 text"
                    continue
                if not row.get(id_field):
                    yield f"line {n}", None, f"line {n}: missing {id_field!r}"
                    continue
                if text_field and row.get(text_field) is None:
                    yield str(row[id_field]), None, f"line {n}: missing field {text_field!r}"
                    continue
                yield (*_split(row, id_field, text_field), None)
        return
    if fmt != "jsonl":
        raise DecisionError("config", f"unknown format {fmt!r} (jsonl, csv, dir)")
    stream = sys.stdin.buffer if source == "-" else open(source, "rb")
    try:
        for n, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw.decode("utf-8"))
            except UnicodeDecodeError:
                yield f"line {n}", None, f"line {n}: not UTF-8 text"
                continue
            except ValueError:
                yield f"line {n}", None, f"line {n}: invalid JSON"
                continue
            if not isinstance(obj, dict) or id_field not in obj:
                yield f"line {n}", None, f"line {n}: missing {id_field!r}"
                continue
            if text_field and obj.get(text_field) is None:
                yield str(obj[id_field]), None, f"line {n}: missing field {text_field!r}"
                continue
            yield (*_split(obj, id_field, text_field), None)
    finally:
        if stream is not sys.stdin.buffer:
            stream.close()


# --- command line ----------------------------------------------------------------

class RateLimiter:
    def __init__(self, per_second: float):
        self.gap = 1.0 / per_second if per_second and per_second > 0 else 0.0
        self.next = 0.0
        self.lock = threading.Lock()

    def wait(self):
        if not self.gap:
            return
        with self.lock:
            now = time.monotonic()
            delay = self.next - now
            self.next = max(now, self.next) + self.gap
        if delay > 0:
            time.sleep(delay)


def _err(msg: str) -> None:
    print(f"decide: {msg}", file=sys.stderr)


def _questions_from_flags(args):
    if args.yes:
        return {"answer": {"type": "noul", "instructions": args.yes}}
    if args.choice:
        crit = {}
        for c in args.choice:
            name, _, desc = c.partition("=")
            crit[name] = desc or None
        return {"answer": {"type": "choice", "criteria": crit}}
    if args.score:
        return {"answer": {"type": "score", "criteria": list(args.score)}}
    return None


def describe(name: str, a: dict) -> str:
    """One plain-language line for an answer."""
    t = a.get("type")
    if t == "noul":
        p = a["noul"]
        word = "Yes" if p >= 0.5 else "No"
        return f"{name}: {word} - {round(100 * max(p, 1 - p))}% likely (P(yes) = {p:.2f})"
    if t == "choice":
        probs = sorted((a.get("probabilities") or {}).items(), key=lambda kv: -kv[1])
        rest = ", ".join(f"{k} ({round(100 * v)}%)" for k, v in probs if k != a["choice"])[:200]
        top = (a.get("probabilities") or {}).get(a["choice"], a.get("confidence", 0))
        line = f"{name}: {a['choice']} ({round(100 * top)}%)"
        line += f", next: {rest}" if rest else ""
        return line + f"; confidence {a.get('confidence', 0):.2f}"
    if t == "score":
        return f"{name}: score {a['score']:.1f}, confidence {a.get('confidence', 0):.2f}"
    return f"{name}: {json.dumps(a)}"


def _usage_add(total: dict, usage: dict) -> None:
    for k in ("input_tokens", "output_tokens"):
        if isinstance(usage.get(k), (int, float)):
            total[k] = total.get(k, 0) + usage[k]
    if isinstance(usage.get("cost"), (int, float)):
        total["cost"] = total.get("cost", 0.0) + usage["cost"]


def _batches(iterable, size: int):
    """Submit work in bounded batches so a fatal error stops before the rest is sent."""
    batch = []
    for x in iterable:
        batch.append(x)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _check_override(args, setup) -> None:
    """--provider other than the setup's needs --model too: model ids differ by provider."""
    want = getattr(args, "provider", None)
    if setup and want and want != setup.get("provider") and not getattr(args, "model", None):
        raise DecisionError(
            "config", f"--provider {want} differs from the setup's provider "
            f"{setup.get('provider')!r}: also give --model with that provider's model id "
            "(ids differ by provider), and run the privacy check for it")


def cmd_run(args) -> int:
    setup = load_setup(args.setup)
    _check_override(args, setup)
    questions = setup["questions"]
    reference = setup.get("reference")
    if args.state is not None:
        items = iter([("state", args.state, None)])
    elif args.input:
        items = read_items(args.input, args.format, args.id_field, args.text_field)
    else:
        raise DecisionError("config", "give --input FILE|DIR|- or --state TEXT")
    model = args.model or setup["model"]
    if args.dry_run:
        for _id, item, error in items:
            if not error:
                print(json.dumps(build_request(model, build_state(reference, item), questions), indent=2))
                return 0
        _err("no valid item to show")
        return 2
    first = args.provider or setup["provider"]
    check_privacy(first, setup, args.test_data)
    cache = Cache(None if args.no_cache else default_cache_path(args.setup))
    limiter = RateLimiter(args.rate)
    _, base_reason = is_cautious(setup)

    def one(entry):
        try:
            return _one(entry)
        except DecisionError as e:
            if e.kind == "privacy":
                raise
            return {"id": entry[0], "route": "review", "answers": None, "model": None,
                    "provider": None, "cached": False, "error": str(e)}, None
        except Exception as e:  # never drop an item: anything unexpected goes to review
            return {"id": entry[0], "route": "review", "answers": None, "model": None,
                    "provider": None, "cached": False,
                    "error": redact(f"{type(e).__name__}: {e}")}, None

    def _one(entry):
        item_id, item, error = entry
        row = {"id": item_id, "route": "review", "answers": None, "model": None,
               "provider": None, "cached": False, "error": error}
        if error:
            return row, None
        key = cache_key(first, model, questions, reference, item)
        hit = cache.get(key)
        meta = None
        if hit:
            answers, returned = hit["answers"], hit["model_returned"]
            row.update(cached=True, provider=first)
        else:
            limiter.wait()
            try:
                answers, meta = evaluate(build_state(reference, item), questions, provider=args.provider,
                                         model=args.model, setup=setup, timeout=args.timeout,
                                         test_data=args.test_data)
            except DecisionError as e:
                if e.kind == "privacy":
                    raise
                row["error"] = str(e)
                return row, None
            returned = answering_model(meta)
            row["provider"] = meta["provider"]
            if meta["provider"] == first:
                cache.put(key, answers, returned)
        cautious, _ = is_cautious(setup, returned)
        rules = effective_rules(setup.get("policy") or {}, questions, cautious)
        row.update(route=route(answers, rules, combine_of(setup)), answers=answers, model=returned)
        row["cautious"] = cautious
        return row, meta

    counts = {r: 0 for r in ROUTES}
    totals, fallbacks, failed, n, cautious_any = {}, 0, 0, 0, False
    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        workers = max(1, args.workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for row, meta in (r for batch in _batches(items, workers * 8) for r in pool.map(one, batch)):
                n += 1
                counts[row["route"]] += 1
                failed += bool(row["error"])
                cautious_any = cautious_any or row.pop("cautious", True)
                if meta:
                    _usage_add(totals, meta["usage"])
                    fallbacks += bool(meta["hops"])
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
    finally:
        if out is not sys.stdout:
            out.close()
        cache.close()
    mode = f"cautious ({base_reason})" if cautious_any else f"calibrated ({base_reason})"
    cost = (", cost USD " + format(totals["cost"], ".6f")) if "cost" in totals else ""
    _err(f"{n} items: pass {counts['pass']}, review {counts['review']}, reject {counts['reject']}, "
         f"errors {failed} | mode: {mode} | tokens in {totals.get('input_tokens', 0)} "
         f"out {totals.get('output_tokens', 0)}{cost} | items that used a fallback: {fallbacks}")
    if cautious_any:
        _err("cautious mode: wider review band; read every 'review' item. Calibrate to narrow it.")
    return 4 if n and failed == n else 0


def cmd_ask(args) -> int:
    setup = load_setup(args.setup) if args.setup else {}
    _check_override(args, setup)
    questions = _questions_from_flags(args) or setup.get("questions")
    if not questions:
        raise DecisionError("config", "give --yes, --choice or --score (or a setup file with questions)")
    provider = args.provider or setup.get("provider") or "opencode"
    state = build_state(setup.get("reference"), args.state)
    answers, meta = evaluate(state, questions, provider=provider, model=args.model,
                             fallbacks=None if setup else [], setup=setup or None,
                             timeout=args.timeout, test_data=args.test_data)
    if args.json:
        print(json.dumps({"answers": answers, "meta": meta}, indent=2))
    else:
        for name, a in answers.items():
            print(describe(name, a))
        print(f"(model {meta['model_returned']} via {meta['provider']})")
    return 0


def cmd_privacy(args) -> int:
    setup = load_setup(args.setup)
    record_privacy(setup, args.provider, args.policy_url, args.summary,
                   datetime.date.today().isoformat())
    save_setup(args.setup, setup)
    print(f"recorded privacy confirmation for {args.provider} in {args.setup}")
    return 0


def cmd_providers(args) -> int:
    for name, cfg in PROVIDERS.items():
        found = [v for v in cfg["key_env"] if os.environ.get(v)]
        key = f"key: {found[0]} is set" if found else f"key: not set ({' or '.join(cfg['key_env'])})"
        print(f"{name:11} {cfg['endpoint']}  default model {cfg['default_model']}  {key}")
    return 0


def get_json(url: str, key, timeout: float):
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 - provider URL from table
            return json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
        raise DecisionError("fallback", redact(f"{type(e).__name__}: {e}", key)) from None


def cmd_models(args) -> int:
    setup = load_setup(args.setup) if args.setup else None
    extra = [n for n in ((setup or {}).get("providers") or {}) if n not in PROVIDERS]
    names = [args.provider] if args.provider else list(PROVIDERS) + extra
    for name in names:
        cfg = provider_config(name, setup)
        if not cfg.get("models_url"):
            print(f"{name}: no model-list endpoint; see {cfg['docs']} (default {cfg['default_model']})")
            continue
        data = get_json(cfg["models_url"], api_key(cfg), args.timeout)
        rows = data.get("data") or data.get("models") or [] if isinstance(data, dict) else data
        for m in rows:
            desc = m.get("description") or "no description"
            print(f"{name}: {m.get('name') or m.get('id')}  {str(desc)[:80]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="decide.py", description="Decision-model client (System One).")
    p.add_argument("--version", action="version", version=f"decide.py {VERSION}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--provider", help="override the setup's provider")
    common.add_argument("--model", help="override the primary hop's model")
    common.add_argument("--timeout", type=float, default=60.0)
    common.add_argument("--test-data", action="store_true",
                        help="the data is made up: skip the privacy check")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", parents=[common], help="score a batch and route each item")
    r.add_argument("setup")
    r.add_argument("--input", help="JSONL, CSV, a folder of .txt/.md files, or - for stdin")
    r.add_argument("--state", help="one item given as text")
    r.add_argument("--format", choices=("jsonl", "csv", "dir"))
    r.add_argument("--id-field", default="id")
    r.add_argument("--text-field", help="send only this field of each item")
    r.add_argument("--out", help="write result rows here instead of stdout")
    r.add_argument("--dry-run", action="store_true", help="print the first request; send nothing")
    r.add_argument("--no-cache", action="store_true")
    r.add_argument("--workers", type=int, default=1)
    r.add_argument("--rate", type=float, default=2.0, help="max calls per second (default 2)")
    r.set_defaults(func=cmd_run)

    a = sub.add_parser("ask", parents=[common], help="ask one question about one text")
    a.add_argument("setup", nargs="?")
    a.add_argument("--state", required=True)
    g = a.add_mutually_exclusive_group()
    g.add_argument("--yes", metavar="QUESTION", help="a yes/no question")
    g.add_argument("--choice", nargs="+", metavar="NAME[=DESC]")
    g.add_argument("--score", nargs="+", metavar="LEVEL", help="levels, lowest first")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_ask)

    c = sub.add_parser("calibrate", parents=[common], help="score labeled items and set cutoffs")
    c.add_argument("setup")
    c.add_argument("--labels", required=True, help='JSONL: {"id", "item", "expected": {...}}')
    c.add_argument("--target-recall", type=float, default=0.95)
    c.add_argument("--target-precision", type=float, default=0.90)
    c.add_argument("--replace-user-rules", action="store_true")
    c.add_argument("--check", action="store_true", help="re-score and compare; change nothing")
    c.set_defaults(func=cmd_calibrate)

    pv = sub.add_parser("privacy", help="record the user's privacy confirmation for a provider")
    pv.add_argument("setup")
    pv.add_argument("--provider", required=True)
    pv.add_argument("--policy-url", required=True)
    pv.add_argument("--summary", required=True)
    pv.set_defaults(func=cmd_privacy)

    pr = sub.add_parser("providers", help="built-in providers and whether a key is set")
    pr.set_defaults(func=cmd_providers)

    m = sub.add_parser("models", help="list a provider's models where it has a list endpoint")
    m.add_argument("--provider")
    m.add_argument("--setup", help="also list providers defined in this setup file")
    m.add_argument("--timeout", type=float, default=30.0)
    m.set_defaults(func=cmd_models)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DecisionError as e:
        _err(str(e))
        return {"privacy": 3, "fallback": 4}.get(e.kind, 2)



# --- calibration -----------------------------------------------------------------

MARGIN = 0.02  # probabilities wobble in the second decimal; leave room around cutoffs


def auroc(values, positives):
    """Area under the ROC curve (Mann-Whitney, ties count half); None if a class is empty."""
    pos = [v for v, p in zip(values, positives) if p]
    neg = [v for v, p in zip(values, positives) if not p]
    if not pos or not neg:
        return None
    wins = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in pos for b in neg)
    return wins / (len(pos) * len(neg))


def is_good(expected: dict, good_if) -> bool:
    for c in good_if:
        v = expected.get(c["question"])
        if v is None:
            return False
        if "is" in c and v != c["is"]:
            return False
        if "at_least" in c and not (isinstance(v, (int, float)) and v >= c["at_least"]):
            return False
        if "in" in c and v not in c["in"]:
            return False
    return True


def _value(answer):
    if not isinstance(answer, dict):
        return None
    return answer.get("noul") if answer.get("type") == "noul" else answer.get("score")


def _default_good_if(questions: dict) -> list:
    out = []
    for name, q in questions.items():
        if q.get("type") == "noul":
            out.append({"question": name, "is": True})
        elif q.get("type") == "score":
            out.append({"question": name, "at_least": (len(q.get("criteria") or []) - 1) / 2})
    return out


def suggest_rules(results, questions: dict, good_if, target_recall: float,
                  target_precision: float, targets=None) -> list:
    """Cutoffs from scored labels. results: [{"answers", "expected", "good"}].
    targets: the questions to set cutoffs for (those with a rule); None = all."""
    good = [r for r in results if r["good"]]
    allowed = int((1 - target_recall) * len(good) + 1e-9)
    rules = []
    for name, q in questions.items():
        if targets is not None and name not in targets:
            continue
        qtype = q.get("type")
        if qtype in ("noul", "score"):
            rule = {"question": name, "source": "calibration"}
            gv = sorted(v for v in (_value(r["answers"].get(name)) for r in good) if v is not None)
            if gv:
                rule["reject_below"] = round(gv[min(allowed, len(gv) - 1)] - MARGIN, 4)
            pairs = sorted((_value(r["answers"].get(name)), r["good"]) for r in results
                           if _value(r["answers"].get(name)) is not None)
            for i, (t, _) in enumerate(pairs):
                above = [g for v, g in pairs[i:] if v > t]
                if len(above) >= 3 and sum(above) / len(above) >= target_precision:
                    rule["pass_above"] = round(t, 4)
                    break
            rules.append(rule)
        elif qtype == "choice":
            scored = sorted((r["answers"][name].get("confidence", 0),
                             r["answers"][name].get("choice") == r["expected"].get(name))
                            for r in results if name in r["expected"] and name in r["answers"])
            min_conf = 1.0
            for i, (c, _) in enumerate(scored):
                tail = [ok for _, ok in scored[i:]]
                if len(tail) >= 3 and sum(tail) / len(tail) >= target_precision:
                    min_conf = round(c, 4)
                    break
            rules.append({"question": name, "min_confidence": min_conf, "source": "calibration"})
    # item level: loosen the rule closest to each rejected good item until recall holds
    for _ in range(len(good) + 1):
        rejected = []
        for r in good:
            for rule in rules:
                v = _value(r["answers"].get(rule["question"]))
                if v is not None and "reject_below" in rule and v < rule["reject_below"]:
                    rejected.append((rule["reject_below"] - v, rule, v))
        if len({id(x) for x in good if route(x["answers"], rules) == "reject"}) <= allowed or not rejected:
            break
        _, rule, v = min(rejected, key=lambda x: x[0])
        rule["reject_below"] = round(v - MARGIN, 4)
    return rules


def calibrate(setup: dict, labels, *, target_recall: float = 0.95, target_precision: float = 0.90,
              replace_user_rules: bool = False, scorer=None, test_data: bool = False,
              today=None, write: bool = True, provider: str | None = None,
              model: str | None = None, timeout: float = 60) -> dict:
    """Score labeled items, report agreement, and (write=True) store cutoffs and the
    calibration record in the setup. Labels: [{"id", "item", "expected": {question: value}}]."""
    scorer = scorer or evaluate
    if combine_of(setup) == "any":
        raise DecisionError("config", "calibrate does not support policy.combine 'any' yet; set "
                            "flagging cutoffs by hand, or run in cautious mode")
    check_privacy(provider or setup["provider"], setup, test_data)
    questions = setup["questions"]
    policy = setup.setdefault("policy", {})
    good_if = policy.get("good_if") or _default_good_if(questions)
    targets = {r["question"] for r in policy.get("rules") or []} or None
    want_provider, want_model = provider, model
    results, model, provider = [], None, None
    for lab in labels:
        answers, meta = scorer(build_state(setup.get("reference"), lab["item"]), questions,
                               setup=setup, test_data=test_data, provider=want_provider,
                               model=want_model, timeout=timeout)
        model = model or answering_model(meta)
        provider = provider or meta.get("provider")
        results.append({"id": lab.get("id"), "answers": answers, "expected": lab["expected"],
                        "good": is_good(lab["expected"], good_if)})
    n_good = sum(r["good"] for r in results)
    counts = {"good": n_good, "not good": len(results) - n_good}
    warnings = []
    if len(results) < 20:
        warnings.append(f"only {len(results)} labels; 20 or more recommended, covering every class "
                        "and the borderline cases")
    metrics = {}
    for name, q in questions.items():
        if q.get("type") in ("noul", "score"):
            vals = [(_value(r["answers"].get(name)), r["good"]) for r in results]
            vals = [(v, g) for v, g in vals if v is not None]
            metrics[name] = {"auroc": auroc([v for v, _ in vals], [g for _, g in vals])}
        elif q.get("type") == "choice":
            conf, right = {}, 0
            per = {}
            for r in results:
                exp, got = r["expected"].get(name), (r["answers"].get(name) or {}).get("choice")
                if exp is None:
                    continue
                per[exp] = per.get(exp, 0) + 1
                conf.setdefault(exp, {})[got] = conf.setdefault(exp, {}).get(got, 0) + 1
                right += exp == got
            total = sum(per.values())
            metrics[name] = {"accuracy": right / total if total else None, "confusion": conf}
            counts.update({f"{name}={k}": v for k, v in per.items()})
    for cls, k in counts.items():
        if k < 3 and (cls in ("good", "not good") or "=" in cls):
            warnings.append(f"class {cls!r} has only {k} labels; add at least 3")
    suggested = suggest_rules(results, questions, good_if, target_recall, target_precision, targets)
    old = policy.get("rules") or []
    user = [r for r in old if r.get("source") != "calibration"]
    kept = [] if replace_user_rules else user
    kept_q = {r["question"] for r in kept}
    final = kept + [r for r in suggested if r["question"] not in kept_q]
    good_routes = [route(r["answers"], final) for r in results if r["good"]]
    item_recall = (sum(x != "reject" for x in good_routes) / len(good_routes)) if good_routes else None
    report = {"labels": len(results), "counts": counts, "questions": metrics, "warnings": warnings,
              "suggested_rules": suggested, "kept_user_rules": kept, "rules": final,
              "item_recall": item_recall, "model": model, "provider": provider}
    if write:
        policy["rules"] = final
        policy["mode"] = "calibrated"
        setup["calibration"] = {
            "model": model, "provider": provider,
            "date": today or datetime.date.today().isoformat(),
            "labels": len(results), "counts": counts, "metrics": metrics,
            "targets": {"recall": target_recall, "precision": target_precision},
            "item_recall": item_recall}
    return report


def read_labels(path: str) -> list:
    labels = []
    for item_id, obj, error in read_items(path, "jsonl", "id", None):
        if error:
            raise DecisionError("config", f"labels file {path}: {error}")
        if not isinstance(obj, dict) or "item" not in obj or "expected" not in obj:
            raise DecisionError("config", f"labels file {path}: {item_id} needs 'item' and 'expected'")
        labels.append({"id": item_id, "item": obj["item"], "expected": obj["expected"]})
    return labels


def cmd_calibrate(args) -> int:
    setup = load_setup(args.setup)
    _check_override(args, setup)
    labels = read_labels(args.labels)
    report = calibrate(setup, labels, target_recall=args.target_recall,
                       target_precision=args.target_precision,
                       replace_user_rules=args.replace_user_rules, test_data=args.test_data,
                       write=not args.check, provider=args.provider, model=args.model,
                       timeout=args.timeout)
    if args.check:
        stored = setup.get("calibration") or {}
        report["stored"] = {"model": stored.get("model"), "metrics": stored.get("metrics")}
    else:
        # re-read so edits made while scoring (privacy, questions) are kept; merge only our parts
        with open(args.setup, encoding="utf-8") as f:
            fresh = json.load(f)
        fresh.setdefault("policy", {})
        fresh["policy"]["rules"] = setup["policy"]["rules"]
        fresh["policy"]["mode"] = setup["policy"]["mode"]
        fresh["calibration"] = setup["calibration"]
        save_setup(args.setup, fresh)
    print(json.dumps(report, indent=2))
    for w in report["warnings"]:
        _err("warning: " + w)
    return 0

if __name__ == "__main__":
    sys.exit(main())
