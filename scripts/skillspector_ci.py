#!/usr/bin/env python3
"""Scan every skill with NVIDIA SkillSpector and gate on what is left.

    python3 scripts/skillspector_ci.py [--skills a,b] [--output FILE.sarif]
                                       [--fail-on HIGH] [--jobs 4]

Each skills/<name>/ is copied (without __pycache__ and *.pyc, which the
scanner flags) and scanned statically (--no-llm), with .skillspector/<name>.yaml
as its baseline when that file exists. The per-skill SARIF reports are merged
into one run whose paths start at the repo root (skills/<name>/...), for one
code-scanning upload. Suppressed findings stay in it, marked with the
baseline's reason.

Exit 1 when a finding at or above --fail-on is not in a baseline, a scan
fails, or a baseline names no skill; 2 on bad usage or no scanner; else 0.
Coverage gaps reach the gate as AE1 findings, accepted per file in a
baseline. Install the scanner with skills/skillspector-install. Stdlib only.
"""
import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess  # nosec B404 - runs the skillspector CLI with fixed argv
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
SCAN_TIMEOUT = 900


def discover(skills_dir):
    return sorted(n for n in os.listdir(skills_dir)
                  if os.path.isfile(os.path.join(skills_dir, n, "SKILL.md")))


def stale_baselines(baseline_dir, skills):
    if not os.path.isdir(baseline_dir):
        return []
    return sorted(f for f in os.listdir(baseline_dir)
                  if f.endswith(".yaml") and f[:-5] not in skills)


def scan(exe, name, skills_dir, baseline_dir, work):
    """Scan one skill. Returns (name, sarif dict or None, error text or None)."""
    src = os.path.join(work, "src", name)
    shutil.copytree(os.path.join(skills_dir, name), src,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    out = os.path.join(work, name + ".sarif")
    cmd = [exe, "scan", src, "--no-llm", "--format", "sarif", "--output", out]
    baseline = os.path.join(baseline_dir, name + ".yaml")
    if os.path.isfile(baseline):
        cmd += ["--baseline", baseline]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,  # nosec B603
                             timeout=SCAN_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return name, None, f"timed out after {SCAN_TIMEOUT}s"
    # exit 1 only means findings remain; the gate reads the report itself
    if res.returncode not in (0, 1) or not os.path.isfile(out):
        tail = (res.stderr or res.stdout).strip().splitlines()[-3:]
        return name, None, f"exit {res.returncode}: " + " | ".join(tail)
    with open(out, encoding="utf-8") as f:
        sarif = json.load(f)
    invs = sarif.get("runs", [{}])[0].get("invocations", [])
    if not invs or not all(i.get("executionSuccessful") for i in invs):
        return name, None, "scanner reported executionSuccessful=false"
    return name, sarif, None


def _rebase(node, prefix):
    """Prefix every relative artifactLocation uri with the skill's repo path."""
    if isinstance(node, dict):
        loc = node.get("artifactLocation")
        if isinstance(loc, dict):
            uri = loc.get("uri", "")
            if uri and "://" not in uri and not uri.startswith("/"):
                loc["uri"] = prefix + uri
        for v in node.values():
            _rebase(v, prefix)
    elif isinstance(node, list):
        for v in node:
            _rebase(v, prefix)


def merge(reports):
    """One SARIF run from {skill: sarif}. Rules deduplicated by id."""
    merged, rules, results, notes = None, {}, [], []
    ok, coverage = True, {}  # ok: every merged scan ran (failed ones never get here)
    for name in sorted(reports):
        sarif = reports[name]
        run = sarif["runs"][0]
        _rebase(run, f"skills/{name}/")
        if merged is None:
            merged = {k: v for k, v in sarif.items() if k != "runs"}
            driver = {k: v for k, v in run["tool"]["driver"].items() if k != "rules"}
        for rule in run["tool"]["driver"].get("rules", []):
            rules.setdefault(rule["id"], rule)
        for r in run.get("results", []):
            r.setdefault("properties", {})["skill"] = name
            results.append(r)
        for inv in run.get("invocations", []):
            ok = ok and inv.get("executionSuccessful", False)
            notes += inv.get("toolExecutionNotifications", [])
            comp = inv.get("properties", {}).get("analysisCompleteness")
            if comp:
                coverage[name] = comp
    if merged is None:
        return None
    driver["rules"] = [rules[k] for k in sorted(rules)]
    merged["runs"] = [{
        "tool": {"driver": driver},
        "results": results,
        "columnKind": "utf16CodeUnits",
        "invocations": [{"executionSuccessful": ok, "toolExecutionNotifications": notes,
                         "properties": {"analysisCompleteness": coverage}}],
    }]
    return merged


def severity(result):
    return result.get("properties", {}).get("severity", "").upper()


def blocking(sarif, fail_on):
    floor = SEVERITIES.index(fail_on)
    out = []
    for r in sarif["runs"][0]["results"] if sarif else []:
        sev = severity(r)
        if sev in SEVERITIES and SEVERITIES.index(sev) >= floor and not r.get("suppressions"):
            out.append(r)
    return out


def summary(sarif, fail_on, errors):
    """Markdown table: one row per skill."""
    rows = {}
    run = sarif["runs"][0] if sarif else {"results": [], "invocations": [{}]}
    cov = run["invocations"][0].get("properties", {}).get("analysisCompleteness", {})
    for r in run["results"]:
        row = rows.setdefault(r["properties"]["skill"], {"active": {}, "suppressed": 0})
        if r.get("suppressions"):
            row["suppressed"] += 1
        else:
            row["active"][severity(r)] = row["active"].get(severity(r), 0) + 1
    names = sorted(set(rows) | set(cov) | set(errors))
    lines = [f"| skill | active (gate: {fail_on}+) | suppressed | coverage |",
             "| --- | --- | --- | --- |"]
    for n in names:
        if n in errors:
            lines.append(f"| {n} | scan failed: {errors[n]} | | |")
            continue
        row = rows.get(n, {"active": {}, "suppressed": 0})
        act = ", ".join(f"{s} {row['active'][s]}" for s in reversed(SEVERITIES) if s in row["active"]) or "none"
        c = cov.get(n, {})
        pct = c.get("coveragePercent")
        lines.append(f"| {n} | {act} | {row['suppressed']} | "
                     f"{'' if pct is None else f'{pct:g}%'} {'' if c.get('isComplete', True) else '(partial)'} |")
    return "\n".join(lines)


def location(result):
    loc = result["locations"][0]["physicalLocation"] if result.get("locations") else {}
    return loc.get("artifactLocation", {}).get("uri", ""), loc.get("region", {}).get("startLine", 1)


def annotate(result):
    path, line = location(result)
    msg = result.get("message", {}).get("text", "").replace("\n", " ")[:300]
    return f"::error file={path},line={line},title=SkillSpector {result.get('ruleId')}::{msg}"


def parse(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--skills", help="comma list of skills (default: every skill)")
    p.add_argument("--output", default="skillspector.sarif", help="merged SARIF path")
    p.add_argument("--fail-on", default="HIGH", choices=SEVERITIES, help="lowest blocking severity")
    p.add_argument("--jobs", type=int, default=4, help="parallel scans")
    p.add_argument("--skillspector", default=None, help="scanner command (default: skillspector on PATH)")
    p.add_argument("--skills-dir", default=os.path.join(REPO, "skills"), help=argparse.SUPPRESS)
    p.add_argument("--baselines", default=os.path.join(REPO, ".skillspector"), help="baseline folder")
    return p.parse_args(argv)


def main(argv=None):
    args = parse(argv)
    exe = args.skillspector or shutil.which("skillspector")
    if not exe:
        print("skillspector not found: install it with "
              "python3 skills/skillspector-install/scripts/install.py --skip-skill", file=sys.stderr)
        return 2
    every = discover(args.skills_dir)
    names = every if not args.skills else [s.strip() for s in args.skills.split(",") if s.strip()]
    unknown = [n for n in names if n not in every]
    if unknown:
        print(f"unknown skills: {', '.join(unknown)}", file=sys.stderr)
        return 2
    stale = stale_baselines(args.baselines, every)
    reports, errors = {}, {}
    with tempfile.TemporaryDirectory() as work, \
            concurrent.futures.ThreadPoolExecutor(max(1, args.jobs)) as pool:
        futures = [pool.submit(scan, exe, n, args.skills_dir, args.baselines, work) for n in names]
        for fut in concurrent.futures.as_completed(futures):
            name, sarif, err = fut.result()
            if err:
                errors[name] = err
            else:
                reports[name] = sarif
    merged = merge(reports)
    if merged:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=1)
    block = blocking(merged, args.fail_on)
    table = summary(merged, args.fail_on, errors)
    print(table)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## SkillSpector\n\n" + table + "\n")
    in_actions = bool(os.environ.get("GITHUB_ACTIONS"))
    for r in block:
        path, line = location(r)
        print(annotate(r) if in_actions else f"BLOCKING {r.get('ruleId')} {severity(r)} {path}:{line}")
    for b in stale:
        print(f"stale baseline: .skillspector/{b} names no skill", file=sys.stderr)
    for n, e in sorted(errors.items()):
        print(f"scan failed: {n}: {e}", file=sys.stderr)
    failed = bool(block or errors or stale)
    print(f"{'FAIL' if failed else 'PASS'}: {len(block)} blocking finding(s), "
          f"{len(errors)} failed scan(s), {len(stale)} stale baseline(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
