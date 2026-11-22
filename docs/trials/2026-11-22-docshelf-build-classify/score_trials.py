"""Condense the opencode event streams that run_trials.sh writes.

    python3 score_trials.py [-v] RUN_DIR...

One block per run dir: exit code and wall time, tool calls, classify and
`classify --apply` calls (and choice lines written), docshelf.py queries,
answer checks, and from the run's final plan: counts per classify bucket,
agreement of the final keep (full = reference, stub = guide) with the
calibration labels in tests/fixtures/docshelf_build_classify.json on the
LangChain keys both have, and the docvol's db.json size.
-v adds every command and the reply.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "skills", "docshelf-build", "scripts"))
from build_classify import counts  # noqa: E402

args = sys.argv[1:]
verbose = "-v" in args
dirs = [a for a in args if a != "-v"]
CHECKS = [
    ("ToolStrategy", r"ToolStrategy", True),
    ("ProviderStrategy", r"ProviderStrategy", True),
    ("auto choice: provider-native if supported, else tool",
     r"(?is)(native|provider).{0,400}(otherwise|else|fall|other models|ToolStrategy)", True),
]
LABELS = {p["key"]: p["label"] for p in json.load(open(os.path.join(
    REPO, "tests", "fixtures", "docshelf_build_classify.json")))["pages"] if p["site"] == "langchain"}


def short(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 3] + "..."


for d in dirs:
    d = d.rstrip("/")
    try:
        summ = open(os.path.join(d, "out", "summary.txt")).read().strip()
    except OSError:
        summ = ""
    calls, cls, apply_, query, texts, chosen = [], [], [], [], [], 0
    for line in open(os.path.join(d, "out", "run.jsonl"), errors="replace"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        part = e.get("part") or {}
        if e.get("type") == "tool_use":
            st = part.get("state") or {}
            inp = st.get("input") or {}
            cmd = inp.get("command", "") if isinstance(inp.get("command"), str) else ""
            calls.append((part.get("tool", ""), cmd or json.dumps(inp), str(st.get("output") or "")))
            if re.search(r"docshelf_build\.py\s+classify\b", cmd):
                (apply_ if "--apply" in cmd else cls).append(cmd)
                m = re.search(r"applied (\d+)", str(st.get("output") or ""))
                chosen += int(m.group(1)) if m and "--apply" in cmd else 0
            elif re.search(r"docshelf\.py\s+(?:-\S+\s+)*(search|show|toc|fts)\b", cmd):
                query.append(cmd)
        elif e.get("type") == "text":
            texts.append(part.get("text", ""))
    reply = "\n".join(texts[-1:])
    miss = [n for n, rx, want in CHECKS if bool(re.search(rx, reply)) != want]
    plans = []
    for p in glob.glob(os.path.join(d, "work", ".cache", "docshelf", "built-plans", "*.json")):
        try:
            plan = json.load(open(p))
        except (OSError, ValueError):
            continue
        if plan.get("kind") == "llms":
            plans.append((len(plan.get("pages", {})), os.path.basename(p)[:-5], plan))
    print("=" * 96)
    print(os.path.basename(d), "|", summ)
    print("  tool-calls=%d classify=%d apply=%d choices-applied=%d docshelf-queries=%d" % (
        len(calls), len(cls), len(apply_), chosen, len(query)))
    print("  answer checks failed: %s" % (", ".join(miss) or "none"))
    for n, name, plan in sorted(plans, reverse=True):
        c = counts(plan)
        pages = plan["pages"]
        both = [k for k in pages if k in LABELS]
        agree = sum((pages[k]["keep"] == "full") == (LABELS[k] == "reference") for k in both)
        wrong_stub = sum(pages[k]["keep"] == "stub" and LABELS[k] == "reference" for k in both)
        db = os.path.join(d, "work", ".cache", "docshelf", "built", name, "db.json")
        size = os.path.getsize(db) if os.path.exists(db) else 0
        print("  plan %s: %d pages; %s" % (name, n, ", ".join("%s %d" % kv for kv in c.items())))
        print("    vs labels: %d/%d agree, %d reference pages stubbed; db.json %d B" % (
            agree, len(both), wrong_stub, size))
    if verbose:
        for tool, c, out in calls:
            print("  [%s] %s" % (tool, short(c, 170)))
        print("  REPLY: " + short(reply, 1500))
