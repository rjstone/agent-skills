"""Condense the opencode event streams that run_trials.sh writes.

    python3 score_trials.py [-v] [-t RUN_ID] MODEL_DIR...

One block per run: whether the skill was loaded, which references were
opened, script calls and their output size, calls that ended in an error,
expected answers that are missing from the reply, and what the run left
behind (store, docsets, notes). -v adds every script command and the reply.

The answer checks are patterns over the reply, so read a flagged reply
before calling it wrong: a correct answer in other words is flagged too,
and a pattern can match by accident.
"""
import json
import os
import re
import sys

args = sys.argv[1:]
verbose = "-v" in args
only = args[args.index("-t") + 1] if "-t" in args else None
dirs = [a for a in args if a not in ("-v", "-t", only)]

# run id -> [(label, pattern that a correct reply matches)]
CHECKS = {
    "S1": [("'error'", r"error"), ("warn", r"warn"), ("skip", r"skip"),
           ("Callable", r"[Cc]allable")],
    "S2": [("signature", r"batch\(value[^)]*linecount[^)]*fill_with"),
           ("fill", r"fill")],
    "S3": [("signature", r"redirect\(location,\s*code=302,\s*Response=None\)"),
           ("302", r"\b302\b")],
    "S4": [],
    "duckdb": [("diff=2", r"\b2\b"), ("why", r"boundar|truncat|whole"),
               ("BIGINT", r"BIGINT"),
               ("default 0", r"default[^.\n]{0,40}\b0\b|\b0\b[^.\n]{0,20}default|\|\s*0\b"),
               ("count_if=1", r"count_if[\s\S]{0,400}\b1\b")],
    # "ignored" (nothing happens) and "protected" (the enemy stops the
    # attack) both make an enemy unaffected by arrows
    "solarus": [("return true", r"returns?\s+\**`?true"), ("hurt", r"hurt"),
                ("immobilized", r"immobili[sz]ed"),
                ("call", r"set_attack_consequence\(\s*[\"']arrow[\"']\s*,\s*"
                         r"[\"'](ignored|protected)[\"']\s*\)"),
                ("88", r"\b88\b")],
    "python": [("False", r"False"), ("result list", r"result list|aggregated"),
               ("--keep", r"--keep"), ("ContextVar", r"ContextVar")],
    "morello": [("tag cleared", r"[Tt]ag"),
                ("syntax", r"GCBASE\W{0,4}<Xd>\W{0,6}<Cn\|CSP>"), ("CSP", r"CSP"),
                ("Cn 9:5", r"9\s*[:\-–]\s*5|5\s*[:\-–]\s*9|\[9:5\]|bits?\s*5\D{1,12}9"),
                ("Rd 4:0", r"4\s*[:\-–]\s*0|0\s*[:\-–]\s*4|\[4:0\]|bits?\s*0\D{1,12}4")],
}
NOTE = {"duckdb": "non-zero number counts as true",
        "solarus": "Return true from the callback",
        "python": "puts exceptions in the result list",
        "morello": "Cn=31 selects CSP"}
ERROR = re.compile(r"^usage: docset|^docset\.py[^\n]*: error:|unknown docset|"
                   r"^no entry |already sets the store|^no matches for|"
                   r"^no lines match", re.M)


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


def script(cmd):
    return re.sub(r"\S*/scripts/docset\.py", "docset.py", cmd)


for d in dirs:
    print("=" * 96)
    print(os.path.basename(d.rstrip("/")))
    summ = {}
    try:
        with open(os.path.join(d, "out", "summary.txt")) as f:
            for line in f:
                p = line.split()
                if len(p) == 3:
                    summ[p[0]] = " ".join(p[1:])
    except OSError:
        pass
    for run in CHECKS:
        if (only and run != only) or not os.path.exists(
                os.path.join(d, "out", run + ".jsonl")):
            continue
        skill, refs, cmds, bad, other, texts, errs = False, set(), [], [], [], [], []
        out_chars = tok_in = 0
        for e in events(os.path.join(d, "out", run + ".jsonl")):
            t, part = e.get("type"), e.get("part") or {}
            if t == "tool_use":
                st = part.get("state") or {}
                inp = st.get("input") or {}
                out = str(st.get("output") or st.get("error") or "")
                blob = json.dumps(inp)
                if part.get("tool") == "skill" and "dash-docset" in blob:
                    skill = True
                for r in ("setup.md", "installing.md", "notes.md"):
                    if r in blob:
                        refs.add(r[:-3])
                cmd = inp.get("command", "")
                if "docset.py" in cmd:
                    cmds.append(cmd)
                    out_chars += len(out)
                    if "--help" not in cmd and ERROR.search(out):
                        bad.append((cmd, out))
                elif part.get("tool") != "skill":
                    other.append("%s %s" % (part.get("tool"), short(cmd or blob, 90)))
            elif t == "text":
                texts.append(part.get("text", ""))
            elif t == "error":
                errs.append(short(json.dumps(e.get("error")), 200))
            elif t == "step_finish":
                tok_in += (part.get("tokens") or {}).get("input", 0)
        reply = "\n".join(texts)
        miss = [n for n, rx in CHECKS[run] if not re.search(rx, reply)]
        try:
            with open(os.path.join(d, "out", run + ".state.txt")) as f:
                state = f.read()
        except OSError:
            state = ""
        print("-" * 96)
        print("%s: %s skill=%s refs=%s script-calls=%d errors=%d other-tools=%d "
              "script-output=%d input-tokens=%d"
              % (run, summ.get(run, "no summary"), "Y" if skill else "N",
                 ",".join(sorted(refs)) or "-", len(cmds), len(bad), len(other),
                 out_chars, tok_in))
        line = "   answers missing: %s" % (", ".join(miss) or "none")
        if run in NOTE:
            line += " | note in file: %s | notes --check ok: %s" % (
                NOTE[run].lower() in state.lower(),
                bool(re.search(r"^ok\b", state, re.M)))
        print(line)
        for x in errs:
            print("   RUN ERROR " + x)
        for cmd, out in bad[: (30 if verbose else 5)]:
            print("   ERROR $ " + short(script(cmd), 160))
            print("        -> " + short(out, 200))
        if verbose:
            for c in cmds:
                print("   $ " + short(script(c), 170))
            for o in other:
                print("   other: " + o)
            print("   REPLY: " + short("\n".join(texts[-2:]), 1500))
            print("   STATE: " + short(state, 500))
        elif miss or not skill:
            print("   REPLY: " + short("\n".join(texts[-2:]), 600))
