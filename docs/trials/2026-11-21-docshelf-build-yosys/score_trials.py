"""Condense the opencode event streams that run_trials.sh writes.

    python3 score_trials.py [-v] RUN_DIR...

One block per run dir (<model>-<arm>): exit code and wall time, tool calls,
docshelf_build.py calls (plan / build), docshelf.py calls (search / show),
web fetches (webfetch tool, curl, wget, urllib in a command), whether a skill
was loaded, whether docshelf_build ran BEFORE the first docshelf query, the
answer checks, and bytes left on disk (docshelf cache, other folders).

Answer checks are patterns over the final reply; read a flagged reply before
calling it wrong. The key (answer_key.md): the only option is -purge, plus
the [selection] argument; -noremove does not exist (a made-up option).
-v adds every command and the reply.
"""
import json
import os
import re
import sys

args = sys.argv[1:]
verbose = "-v" in args
dirs = [a for a in args if a != "-v"]

CHECKS = [  # (name, pattern, wanted)
    ("-purge named", r"-purge", True),
    ("purge meaning (internal nets, public name)", r"(?is)purge.{0,300}(internal|public name)|(internal|public name).{0,300}purge", True),
    ("selection arg", r"(?i)selection", True),
    ("no invented -noremove", r"-noremove", False),
]
WEB = re.compile(r"curl |wget |urllib|requests\.get|httpx|webfetch|WebFetch|git clone|pip install")


def events(path):
    out = []
    try:
        with open(path, errors="replace") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def short(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 3] + "..."


for d in dirs:
    d = d.rstrip("/")
    name = os.path.basename(d)
    run = os.path.join(d, "out", "run.jsonl")
    summ = ""
    try:
        summ = open(os.path.join(d, "out", "summary.txt")).read().strip()
    except OSError:
        pass
    skills, calls, build, query, web, errs, texts = [], [], [], [], [], [], []
    order = []  # "build" / "query" in event order
    tok_in = 0
    for e in events(run):
        t, part = e.get("type"), e.get("part") or {}
        if t == "tool_use":
            st = part.get("state") or {}
            inp = st.get("input") or {}
            tool = part.get("tool", "")
            blob = json.dumps(inp)
            cmd = inp.get("command", "") if isinstance(inp.get("command"), str) else ""
            calls.append((tool, cmd or blob, str(st.get("output") or st.get("error") or ""), st.get("status")))
            if tool == "skill":
                skills.append(inp.get("name") or blob)
            elif "docshelf_build.py" in cmd or "docshelf_build.py" in blob:
                build.append(cmd or blob)
                order.append("build")
            elif "docshelf.py" in cmd:
                if re.search(r"docshelf\.py\s+(?:-\S+\s+)*(search|show|toc|fts)\b", cmd):
                    query.append(cmd)
                    order.append("query")
            if tool in ("webfetch", "websearch") or WEB.search(cmd):
                web.append("%s %s" % (tool, short(cmd or blob, 100)))
        elif t == "text":
            texts.append(part.get("text", ""))
        elif t == "error":
            errs.append(short(json.dumps(e.get("error")), 200))
        elif t == "step_finish":
            tok_in += (part.get("tokens") or {}).get("input", 0)
    reply = re.sub("[‐-―−]", "-", "\n".join(texts[-1:]) if texts else "")
    all_text = re.sub("[‐-―−]", "-", "\n".join(texts))
    miss = []
    for n, rx, want in CHECKS:
        if bool(re.search(rx, reply)) != want:
            miss.append(n if want else "HAS " + n)
    disk = {}
    try:
        for line in open(os.path.join(d, "out", "disk.txt")):
            sz, p = line.split(None, 1)
            disk[p.strip()] = int(sz)
    except OSError:
        pass
    cache = 0
    try:  # du -sb of .cache includes opencode's own cache: count docshelf's only
        for root, _, fs in os.walk(os.path.join(d, "work", ".cache", "docshelf")):
            cache += sum(os.path.getsize(os.path.join(root, f)) for f in fs)
    except OSError:
        pass
    proj = disk.get("proj", 0)
    first_build = order.index("build") if "build" in order else None
    first_query = order.index("query") if "query" in order else None
    intended = first_build is not None and first_query is not None and first_build < first_query
    print("=" * 96)
    print(name, "|", summ)
    print("  tool-calls=%d skill-loads=%s build-calls=%d docshelf-queries=%d web-ish=%d "
          "build-before-query=%s input-tokens=%d" % (len(calls), ",".join(skills) or "none",
          len(build), len(query), len(web), "Y" if intended else "N", tok_in))
    print("  disk: docshelf cache=%d B, proj folder=%d B" % (cache, proj))
    print("  answer checks failed: %s" % (", ".join(miss) or "none"))
    for x in errs:
        print("  RUN ERROR " + x)
    for c in build[:6]:
        print("  BUILD $ " + short(c, 200))
    if verbose:
        for tool, c, out, st in calls:
            print("  [%s/%s] %s" % (tool, st, short(c, 170)))
            if st == "error" or re.search(r"(?m)^(error|usage:|Traceback)", out):
                print("       -> " + short(out, 220))
        for w in web:
            print("  web: " + w)
        print("  REPLY: " + short(reply or all_text, 1800))
