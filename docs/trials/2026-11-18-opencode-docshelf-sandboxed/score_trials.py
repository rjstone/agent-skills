"""Condense the opencode event streams that run_trials.sh writes.

    python3 score_trials.py [-v] MODEL_DIR...

One block per model and run (zig, node, pony, http): whether the docshelf skill was loaded, docshelf calls,
calls that ended in a docshelf error, other tools used, the docshelf I/O
estimate ((characters typed + characters printed) / 4, as in the
2026-11-18 Haiku trial), input tokens, and which expected answers are
missing from the reply. -v adds every docshelf command and the reply.

The answer checks are patterns over the reply, so read a flagged reply
before calling it wrong. Adapted from the dash-docset trial scorer
(an earlier trial, kept outside this repo).
"""
import json
import os
import re
import sys

args = sys.argv[1:]
verbose = "-v" in args
dirs = [a for a in args if a != "-v"]

CHECKS = {
    "zig": [
        ("Z1 divFloor=-2", r"divFloor[\s\S]{0,120}(-2|−2)"),
        ("Z1 divTrunc=-1", r"divTrunc[\s\S]{0,120}(-1|−1)"),
        ("Z2 label", r"(?i)label"),
        ("Z2 operand", r"operand"),
        ("Z3 @Int(.unsigned, 18)", r"@Int\(\s*\.unsigned\s*,\s*18\s*\)"),
        ("Z3 std.lang.Signedness", r"std\.lang\.Signedness"),
        ("Z3 bits: u16", r"bits\s*:\s*u16"),
    ],
    "node": [
        ("N1 quux", r"['\"`]quux['\"`]"),
        ("N2 defaults true", r"enableForeignKeyConstraints[\s\S]{0,200}true"),
        ("N2 25.5.0", r"25\.5\.0"), ("N2 24.14.0", r"24\.14\.0"),
        ("N3 whole scope", r"drop\(\s*['\"]fs\.read['\"]\s*\)"),
        ("N3 26.3.0", r"26\.3\.0"),
    ],
    "pony": [
        ("P1 OutStream tag", r"OutStream\s+tag"),
        ("P2 (AmbientAuth val | None val)", r"AmbientAuth\s+val\s*\|\s*None\s+val"),
        ("P3 fulfillment order", r"second[\s\S]{0,40}third[\s\S]{0,40}first|p2[\s\S]{0,20}p3[\s\S]{0,20}p1|fulfill(ed|ment) order|order[^.\n]{0,40}fulfill"),
        ("P3 Fulfill[A, B] iso", r"Fulfill\[A,\s*B\]\s+iso"),
        ("P3 = qualify", r"qualify"),
        ("P3 Promise[B] tag", r"Promise\[B\]\s+tag"),
    ],
    "http": [
        ("H1 429", r"\b429\b"), ("H1 Retry-After", r"Retry-After"),
        ("H2 0-7", r"\b0\b[^.\n]{0,12}\b7\b"), ("H2 default 3", r"default[^.\n]{0,40}\b3\b|\b3\b[^.\n]{0,30}default"),
        ("H2 incremental", r"incremental"),
        ("H3 params, except", r"params\s*,\s*except\s*=\s*\(\s*\"(id|lang)\"\s+\"(id|lang)\"\s*\)"),
        ("H3 key-order", r"key-order[\s\S]{0,200}order"),
    ],
}
ERROR = re.compile(r"^usage: docshelf|^docshelf\.py[^\n]*: error:|"
                   r"^error: |unknown docvol|is not installed", re.M)


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


def typed(cmd):
    """What an agent types for the command with a default setup."""
    return re.sub(r"\S*/scripts/docshelf\.py", "python scripts/docshelf.py", cmd)


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
        path = os.path.join(d, "out", run + ".jsonl")
        if not os.path.exists(path):
            continue
        skill, cmds, bad, other, texts, errs = False, [], [], [], [], []
        mcp_calls = 0
        io_chars = tok_in = 0
        for e in events(path):
            t, part = e.get("type"), e.get("part") or {}
            if t == "tool_use":
                st = part.get("state") or {}
                inp = st.get("input") or {}
                out = str(st.get("output") or st.get("error") or "")
                blob = json.dumps(inp)
                if part.get("tool") == "skill" and "docshelf" in blob:
                    skill = True
                cmd = inp.get("command", "")
                code = inp.get("code", "") if isinstance(inp.get("code"), str) else ""
                if part.get("tool") == "execute" and "docshelf" in code:
                    # opencode's code mode: JS calling the server's tools as
                    # tools.docshelf.search(...), tools["docshelf"].search(...)
                    # or through an alias (d = tools.docshelf; d.search(...))
                    mcp_calls += len(re.findall(
                        r"\.(?:list|search|show|toc|fts|types|sources|suggest|"
                        r"install|remove|notes)\s*\(", code))
                    io_chars += len(code) + len(out)
                    if st.get("status") == "error" or ERROR.search(out):
                        bad.append(("execute " + short(code, 120), out))
                elif str(part.get("tool", "")).startswith("docshelf"):
                    mcp_calls += 1  # the MCP server's tools (ARM=mcp)
                    io_chars += len(json.dumps(inp)) + len(out)
                    if (st.get("status") == "error" or ERROR.search(out)):
                        bad.append((part.get("tool") + " " + blob, out))
                elif "docshelf.py" in cmd:
                    cmds.append(cmd)
                    io_chars += len(typed(cmd)) + len(out)
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
        # models write hyphens as U+2010-U+2015 or U+2212 (e.g. "Retry\u2011After")
        reply = re.sub("[\u2010-\u2015\u2212]", "-", "\n".join(texts))
        miss = [n for n, rx in CHECKS[run] if not re.search(rx, reply)]
        print("  %-5s %s | skill=%s docshelf-calls=%d mcp-calls=%d errors=%d "
              "other-tools=%d docshelf-io~tok=%d input-tokens=%d"
              % (run, summ.get(run, "no summary"), "Y" if skill else "N", len(cmds),
                 mcp_calls, len(bad), len(other), io_chars // 4, tok_in))
        if miss:
            print("        answers missing: %s" % ", ".join(miss))
        for x in errs:
            print("        RUN ERROR " + x)
        for cmd, out in bad[: (30 if verbose else 3)]:
            print("        ERROR $ " + short(typed(cmd), 150))
            print("             -> " + short(out, 180))
        if verbose:
            for c in cmds:
                print("        $ " + short(typed(c), 160))
            for o in other:
                print("        other: " + o)
            print("        REPLY: " + short("\n".join(texts[-2:]), 2000))
