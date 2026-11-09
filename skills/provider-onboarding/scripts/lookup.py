#!/usr/bin/env python3
"""provider-onboarding lookup: find API endpoint info for a provider/model.

Python 3 standard library only. Reads a models.dev-style api.json (from URL(s)
or a local file), merges in references/providers-overrides.json, infers a
likely sign-up URL, and prints a "provider card" plus config snippets.

Exit codes: 0 ok, 2 no match, 3 no data source reachable and no override/manual match.
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

DEFAULT_URLS = "https://models.dev/api.json,https://models.opencode.ai/api.json"
UA = "provider-onboarding/1.0"
TTL = 3600

MULTI_TLDS = {"co.uk", "org.uk", "ac.uk", "com.au", "co.jp", "com.br", "co.in",
              "com.cn", "co.kr", "com.sg", "co.nz", "com.tr", "com.mx", "co.za",
              "com.hk", "com.tw"}
SHARED_HOSTS = {"googleapis.com", "amazonaws.com", "azure.com", "azure-api.net",
                "windows.net", "cloudflare.com", "workers.dev", "vercel.app",
                "herokuapp.com", "run.app", "github.io", "ngrok.io", "fly.dev",
                "onrender.com", "netlify.app"}

FALLBACK_HELP = """\
No models.dev-style data source could be loaded. Options, in order:
  1. Read the upstream repo with a GitHub tool: anomalyco/models.dev
     providers/<id>/provider.toml and providers/<id>/models/<model>.toml
  2. Ask the user to upload api.json, then re-run with --file <path>
  3. Ask the user to allow models.dev (and models.opencode.ai) in their
     agent's network settings (claude.ai: Settings > Capabilities), then re-run
  4. Web-search the provider's docs, or use manual mode:
     --name X --base-url URL --env-var VAR --model-id ID
"""


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


# ---------- data loading ----------

def cache_paths(cache_dir, url):
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return os.path.join(cache_dir, h + ".json"), os.path.join(cache_dir, h + ".etag")


def fetch(url, cache_dir, refresh):
    os.makedirs(cache_dir, exist_ok=True)
    body_p, etag_p = cache_paths(cache_dir, url)
    have = os.path.exists(body_p)
    if have and not refresh and time.time() - os.path.getmtime(body_p) < TTL:
        return json.load(open(body_p)), "cache"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    if have and os.path.exists(etag_p):
        req.add_header("If-None-Match", open(etag_p).read().strip())
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            etag = r.headers.get("ETag")
        data = json.loads(raw)
        open(body_p, "wb").write(raw)
        if etag:
            open(etag_p, "w").write(etag)
        return data, "network"
    except urllib.error.HTTPError as e:
        if e.code == 304 and have:
            os.utime(body_p, None)
            return json.load(open(body_p)), "cache(304)"
        err = "HTTP %s" % e.code
    except Exception as e:  # network blocked, DNS, TLS, bad JSON
        err = "%s: %s" % (type(e).__name__, e)
    if have:
        return json.load(open(body_p)), "stale-cache (%s)" % err
    raise RuntimeError(err)


def providers_of(data):
    if isinstance(data, dict) and isinstance(data.get("providers"), dict):
        return data["providers"]
    return data if isinstance(data, dict) else {}


def load_data(args):
    merged, notes = {}, []
    if args.file:
        for f in args.file:
            try:
                d = providers_of(json.load(open(f)))
                for k, v in d.items():
                    merged.setdefault(k, dict(v, _src=f))
                notes.append("loaded %s (%d providers)" % (f, len(d)))
            except Exception as e:
                notes.append("FAILED %s: %s" % (f, e))
        return merged, notes
    urls = args.url or [u for u in os.environ.get("MODELS_DEV_URLS", DEFAULT_URLS).split(",") if u]
    cache_dir = args.cache_dir or os.path.join(tempfile.gettempdir(), "provider-onboarding-cache")
    for u in urls:
        if args.all_types and "?" not in u:
            u += "?type=all"
        try:
            d, how = fetch(u, cache_dir, args.refresh)
            d = providers_of(d)
            for k, v in d.items():
                merged.setdefault(k, dict(v, _src=u))
            notes.append("loaded %s via %s (%d providers)" % (u, how, len(d)))
        except Exception as e:
            notes.append("FAILED %s: %s" % (u, e))
    return merged, notes


def load_overrides(path):
    p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references", "providers-overrides.json")
    try:
        d = json.load(open(p))
        return {k: v for k, v in d.items() if not k.startswith("_")}
    except Exception:
        return {}


# ---------- matching ----------

def score(q, *cands):
    qn = norm(q)
    if not qn:
        return 0
    best = 0
    for c in cands:
        cn = norm(c)
        if not cn:
            continue
        if cn == qn:
            s = 100
        elif cn.startswith(qn) or qn.startswith(cn):
            s = 80
        elif qn in cn or cn in qn:
            s = 65
        else:
            r = difflib.SequenceMatcher(None, qn, cn).ratio()
            s = r * 50 if r > 0.7 else 0
        best = max(best, s)
    return best


def match_providers(q, data, ov):
    out = []
    for pid in set(data) | set(ov):
        p = data.get(pid, {})
        o = ov.get(pid, {})
        s = score(q, pid, p.get("name"), o.get("name"))
        if s:
            out.append((s, pid))
    return sorted(out, key=lambda x: (-x[0], x[1]))


def match_models(q, prov):
    out = []
    for mid, m in (prov.get("models") or {}).items():
        m = m or {}
        s = score(q, mid, mid.split("/")[-1], m.get("name"))
        if s:
            out.append((s, mid, m))
    return sorted(out, key=lambda x: (-x[0], x[1]))


def model_key(mid, m):
    return norm((m or {}).get("canonical_model_id") or mid.split("/")[-1])


# ---------- derived fields ----------

def registrable(host):
    parts = host.lower().split(".")
    if len(parts) <= 2:
        return host.lower()
    last2 = ".".join(parts[-2:])
    return ".".join(parts[-3:]) if last2 in MULTI_TLDS else last2


def is_shared(host):
    h = host.lower()
    return any(h == s or h.endswith("." + s) for s in SHARED_HOSTS)


def signup_candidates(base_url, docs, ov):
    c = []
    if ov.get("signup_url"):
        c.append({"url": ov["signup_url"], "confidence": "high", "basis": "override table"})
    seen = {x["url"] for x in c}
    for label, u in (("API host", base_url), ("docs host", docs)):
        if not u:
            continue
        host = urlparse(u).hostname
        if not host:
            continue
        if is_shared(host):
            c.append({"url": None, "confidence": "none",
                      "basis": "%s %s is shared infrastructure; the apex is not the provider" % (label, host)})
            continue
        apex = "https://" + registrable(host)
        if apex not in seen:
            seen.add(apex)
            c.append({"url": apex, "confidence": "medium",
                      "basis": "apex of %s (%s) - inferred, not verified" % (label, host)})
    if docs and docs not in seen:
        c.append({"url": docs, "confidence": "low", "basis": "models.dev docs URL - docs, not a sign-up page"})
    return c


def protocol_of(npm, base_url):
    n = (npm or "").lower()
    if "anthropic" in n:
        return "anthropic"
    if "openai" in n or "openrouter" in n or (base_url and "google" not in (base_url or "")):
        return "openai"
    return "unknown"


def money(v):
    return "$%g" % v if isinstance(v, (int, float)) else "?"


def fmt_cost(c):
    if not c:
        return None
    s = "%s in / %s out per 1M tokens" % (money(c.get("input")), money(c.get("output")))
    if c.get("cache_read") is not None:
        s += " (cache read %s)" % money(c["cache_read"])
    return s


# ---------- entry construction ----------

def build_entry(pid, prov, mid, model, ov, manual=None):
    manual = manual or {}
    mp = (model or {}).get("provider") or {}
    base, bsrc = None, "missing"
    verified_ov = ov.get("base_url") and not ov.get("unverified")
    if manual.get("base_url"):
        base, bsrc = manual["base_url"], "manual"
    elif mp.get("api"):
        base, bsrc = mp["api"], "models.dev (model-level)"
    elif verified_ov:
        base, bsrc = ov["base_url"], "override (verified %s)" % ov.get("verified", "?")
    elif prov.get("api"):
        base, bsrc = prov["api"], "models.dev"
    elif ov.get("base_url"):
        base, bsrc = ov["base_url"], "override (UNVERIFIED author knowledge)"
    env = manual.get("env") and [manual["env"]] or (ov.get("env") if verified_ov else None) or prov.get("env") or ov.get("env") or []
    npm = mp.get("npm") or prov.get("npm")
    docs = ov.get("docs") or prov.get("doc")
    m = model or {}
    return {
        "provider_id": pid,
        "provider_name": manual.get("name") or prov.get("name") or ov.get("name") or pid,
        "base_url": base, "base_url_source": bsrc,
        "env": env, "npm": npm, "docs": docs,
        "protocol": protocol_of(npm, base),
        "model": {
            "id": mid or manual.get("model_id"), "name": m.get("name"),
            "limit": m.get("limit"), "cost": fmt_cost(m.get("cost")),
            "modalities": m.get("modalities"), "reasoning": m.get("reasoning"),
            "tool_call": m.get("tool_call"), "status": m.get("status"),
            "release_date": m.get("release_date"), "open_weights": m.get("open_weights"),
        } if (mid or manual.get("model_id")) else None,
        "signup_candidates": signup_candidates(base, docs, ov),
        "hosts_to_allowlist": ov.get("hosts") or ([urlparse(base).hostname] if base else []),
        "extras": {k: ov[k] for k in ("models_endpoint", "protocols", "headers", "quirks", "verified", "source", "note") if ov.get(k)},
        "data_source": prov.get("_src"),
        "opencode_package": prov.get("opencodeai"),
    }


def snippets(e):
    pid, base = e["provider_id"], e["base_url"]
    env = (e["env"] or ["<PROVIDER>_API_KEY"])[0]
    mid = (e["model"] or {}).get("id") or "<model-id>"
    out = {}
    pkg = e["opencode_package"]
    guess = ""
    if not pkg:
        if "openai-compatible" in (e["npm"] or ""):
            pkg = "@opencode/ai/providers/openai-compatible"
        elif not e["npm"] and e["protocol"] == "openai":
            # no SDK package known (e.g. manual mode): the protocol guess says OpenAI-style
            pkg = "@opencode/ai/providers/openai-compatible"
            guess = "  // package inferred from the OpenAI-style protocol guess - verify with `opencode debug config`"
        else:
            pkg = "@opencode/ai/providers/%s" % pid
            guess = "  // package name is a GUESS - verify with `opencode debug config`"
    lim = (e["model"] or {}).get("limit") or {}
    mcfg = {"name": (e["model"] or {}).get("name") or mid}
    if lim:
        mcfg["limit"] = {k: lim[k] for k in ("context", "output") if k in lim}
    oc = {"providers": {pid: {"name": e["provider_name"], "env": e["env"] or [env], "package": pkg,
                              "settings": {"baseURL": base or "<base-url>", "apiKey": "{env:%s}" % env},
                              "models": {mid: mcfg}}},
          "model": "%s/%s" % (pid, mid)}
    out["opencode"] = json.dumps(oc, indent=2) + guess
    out["fast_agent"] = ('generic:\n  base_url: "%s"\n  api_key: "${%s}"\n\n'
                         'fast-agent go --model generic.%s --message "ping"' % (base or "<base-url>", env, mid))
    out["env"] = "export %s=...   # set in your shell or secret store; never paste the key into chat" % env
    if base and e["protocol"] == "openai":
        out["curl"] = ('curl -sS %s/chat/completions \\\n  -H "Authorization: Bearer $%s" -H "Content-Type: application/json" \\\n'
                       '  -d \'{"model":"%s","messages":[{"role":"user","content":"ping"}],"max_tokens":16}\'' % (base.rstrip("/"), env, mid))
    elif base and e["protocol"] == "anthropic":
        out["curl"] = ('curl -sS %s/messages \\\n  -H "x-api-key: $%s" -H "anthropic-version: 2023-06-01" -H "Content-Type: application/json" \\\n'
                       '  -d \'{"model":"%s","max_tokens":16,"messages":[{"role":"user","content":"ping"}]}\'' % (base.rstrip("/"), env, mid))
    else:
        out["curl"] = "# protocol unknown: follow the provider docs (%s)" % (e["docs"] or "no docs URL known")
    return out


# ---------- rendering ----------

def render_md(res):
    L = ["# Provider card query: %s" % res["query"], "", "_Data: %s_" % "; ".join(res["notes"] or ["no remote data"]), ""]
    for w in res.get("warnings", []):
        L.append("> WARNING: " + w)
    for e in res["entries"]:
        m = e["model"]
        L += ["## %s (`%s`)" % (e["provider_name"], e["provider_id"]), "",
              "- Base URL: %s  _[%s]_" % (e["base_url"] or "MISSING", e["base_url_source"]),
              "- API key env var: %s" % (", ".join(e["env"]) or "MISSING"),
              "- Protocol guess: %s (npm: %s)" % (e["protocol"], e["npm"] or "n/a"),
              "- Docs: %s" % (e["docs"] or "MISSING"),
              "- Hosts to allowlist: %s" % (", ".join(e["hosts_to_allowlist"]) or "?")]
        if m:
            L.append("- Model: `%s`%s" % (m["id"], " (%s)" % m["name"] if m["name"] else ""))
            for k in ("limit", "cost", "modalities", "reasoning", "tool_call", "status", "release_date", "open_weights"):
                if m.get(k) is not None:
                    L.append("  - %s: %s" % (k, json.dumps(m[k]) if not isinstance(m[k], str) else m[k]))
        L.append("- Sign-up / key page candidates (inferred, NOT verified):")
        for c in e["signup_candidates"] or [{"url": None, "confidence": "none", "basis": "no base URL or docs"}]:
            L.append("  - %s [%s] %s" % (c["url"] or "(none)", c["confidence"], c["basis"]))
        for k, v in e["extras"].items():
            L.append("- %s: %s" % (k, json.dumps(v) if not isinstance(v, str) else v))
        sn = snippets(e)
        L += ["", "Snippets:", "```json", sn["opencode"], "```", "```yaml", sn["fast_agent"], "```",
              "```bash", sn["env"], sn["curl"], "```", ""]
    if res.get("also_served_by"):
        L.append("## Also served by")
        for a in res["also_served_by"]:
            L.append("- %s (`%s`): base %s; model `%s`; %s" % (a["provider_name"], a["provider_id"], a["base_url"] or "n/a", a["model_id"], a["cost"] or "no price"))
        L.append("")
    return "\n".join(L)


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--provider")
    ap.add_argument("-m", "--model")
    ap.add_argument("--file", action="append", help="local api.json (repeatable)")
    ap.add_argument("--url", action="append", help="api.json URL (repeatable); env MODELS_DEV_URLS")
    ap.add_argument("--all-types", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--cache-dir")
    ap.add_argument("--overrides")
    ap.add_argument("--list-providers", action="store_true")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--limit", type=int, default=8, help="max providers listed for a model-only query")
    ap.add_argument("--name"); ap.add_argument("--base-url"); ap.add_argument("--env-var"); ap.add_argument("--model-id")
    a = ap.parse_args()

    ov = load_overrides(a.overrides)

    # manual mode: no data needed
    if a.base_url:
        manual = {"name": a.name, "base_url": a.base_url, "env": a.env_var, "model_id": a.model_id}
        pid = norm(a.name or a.provider or urlparse(a.base_url).hostname) or "custom"
        e = build_entry(pid, {}, a.model_id, {}, {}, manual)
        res = {"query": "manual: %s" % (a.name or a.base_url), "notes": ["manual mode"], "entries": [e]}
        print(json.dumps(res, indent=2) if a.format == "json" else render_md(res))
        return 0

    data, notes = load_data(a)
    if a.list_providers:
        for pid in sorted(data):
            p = data[pid]
            print("%s\t%s\t%s\t%s" % (pid, p.get("name"), p.get("api") or "-", ",".join(p.get("env") or [])))
        return 0 if data else 3
    if not (a.provider or a.model):
        ap.error("give --provider and/or --model (or --list-providers, or manual flags)")

    warnings = []
    if not data:
        warnings.append("no remote data loaded; results come only from the override table")
    entries, also = [], []
    query = " / ".join(x for x in (a.provider, a.model) if x)

    if a.provider:
        pm = match_providers(a.provider, data, ov)
        if not pm:
            if not data:
                sys.stderr.write(FALLBACK_HELP)
                return 3
            names = difflib.get_close_matches(norm(a.provider), [norm(k) for k in data], n=5, cutoff=0.4)
            sys.stderr.write("No provider matches %r. Closest: %s\nTry --list-providers, or manual mode.\n" % (a.provider, names or "none"))
            return 2
        top = pm[0][0]
        close = [pid for s, pid in pm if s >= top - 10][:3]
        if len(close) > 1:
            warnings.append("ambiguous provider match; showing %s" % ", ".join(close))
        for pid in close:
            prov, o = data.get(pid, {}), ov.get(pid, {})
            if a.model:
                mm = match_models(a.model, prov)
                if mm:
                    for s, mid, m in mm[:2]:
                        entries.append(build_entry(pid, prov, mid, m, o))
                else:
                    warnings.append("provider %s has no model matching %r; listing provider only" % (pid, a.model))
                    entries.append(build_entry(pid, prov, a.model, {}, o))
            else:
                entries.append(build_entry(pid, prov, None, None, o))
        if a.model and entries and entries[0]["model"] and data:
            key = norm(entries[0]["model"]["id"].split("/")[-1])
            for pid, prov in data.items():
                if pid == entries[0]["provider_id"]:
                    continue
                for mid, m in (prov.get("models") or {}).items():
                    if model_key(mid, m) == key:
                        e = build_entry(pid, prov, mid, m, ov.get(pid, {}))
                        also.append({"provider_id": pid, "provider_name": e["provider_name"], "base_url": e["base_url"],
                                     "model_id": mid, "cost": e["model"]["cost"]})
                        break
    else:
        if not data:
            sys.stderr.write(FALLBACK_HELP)
            return 3
        hits = []
        for pid, prov in data.items():
            mm = match_models(a.model, prov)
            if mm:
                hits.append((mm[0][0], pid, mm[0][1], mm[0][2]))
        hits.sort(key=lambda x: (-x[0], x[1]))
        if not hits:
            sys.stderr.write("No model matches %r in %d providers.\n" % (a.model, len(data)))
            return 2
        warnings.append("model-only query: %d providers serve something matching; showing %d" % (len(hits), min(len(hits), a.limit)))
        for s, pid, mid, m in hits[: a.limit]:
            entries.append(build_entry(pid, data[pid], mid, m, ov.get(pid, {})))

    res = {"query": query, "notes": notes, "warnings": warnings, "entries": entries, "also_served_by": also[:10]}
    if a.format == "json":
        for e in res["entries"]:
            e["snippets"] = snippets(e)
        print(json.dumps(res, indent=2))
    else:
        print(render_md(res))
    if not data:
        sys.stderr.write(FALLBACK_HELP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
