"""Condense the opencode event streams that run_trials.sh writes.

    python3 score_trials.py [-v] RUN_DIR...

One block per run dir (<model>-<site>): exit code and wall time, tool calls,
skills loaded, the docshelf-build files the model opened (SKILL.md,
BUILD-sphinx.md, BUILD-llmstxt.md: read tool or a cat/sed/head command),
whether `detect` ran, the docshelf_build.py calls (their SOURCE shows
whether an llms.txt run narrowed to a sub-index), docshelf.py queries, web
fetches, build-before-query, answer checks and bytes left on disk.

Routing passes when the run opened the BUILD file for its site and not the
other one. Answer checks are patterns over the final reply; read a flagged
reply before calling it wrong (answer_key.md has the real answers).
-v adds every command and the reply.
"""
import json
import os
import re
import sys

args = sys.argv[1:]
verbose = "-v" in args
dirs = [a for a in args if a != "-v"]

CHECKS = {  # site -> [(name, pattern, wanted)]
    "sphinx": [
        ("-purge named", r"-purge", True),
        ("purge meaning (internal nets, public name)", r"(?is)purge.{0,300}(internal|public name)|(internal|public name).{0,300}purge", True),
        ("selection arg", r"(?i)selection", True),
        ("no invented -noremove", r"-noremove", False),
    ],
    "llms": [
        ("ToolStrategy", r"ToolStrategy", True),
        ("ProviderStrategy", r"ProviderStrategy", True),
        ("None accepted", r"(?i)\bNone\b", True),
        ("auto choice: provider-native if supported, else tool", r"(?is)(native|provider).{0,400}(otherwise|else|fall|other models|ToolStrategy)", True),
        ("JSON Schema dicts need an explicit strategy", r"(?is)json schema.{0,300}(wrap|explicit|must)", True),
    ],
}
WANT_DOC = {"sphinx": "BUILD-sphinx.md", "llms": "BUILD-llmstxt.md"}
DOCS = ("SKILL.md", "BUILD-sphinx.md", "BUILD-llmstxt.md")
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
    site = "llms" if name.endswith("-llms") else "sphinx"
    opened, detect = [], []
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
                skills.append(inp.get("name") or inp.get("id") or blob)
            for doc in DOCS:
                if ("docshelf-build" in blob and doc in blob and
                        (tool == "read" or re.search(r"\b(cat|sed|head|less|more|tail)\b", cmd))):
                    opened.append(doc)
            if tool == "skill" and "docshelf-build" in (inp.get("name"), inp.get("id")):
                opened.append("SKILL.md")
            if re.search(r"docshelf_build\.py\s+detect\b", cmd):
                detect.append(cmd)
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
    for n, rx, want in CHECKS[site]:
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
    want = WANT_DOC[site]
    other = [x for x in DOCS[1:] if x != want]
    routed = want in opened and not any(x in opened for x in other)
    print("  opened: %s | detect=%d | routing=%s" % (
        " > ".join(dict.fromkeys(opened)) or "none", len(detect), "PASS" if routed else "FAIL"))
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
