"""Condense the opencode event streams that run_trials.sh writes.

    python3 score_trials.py [-v] MODEL_DIR...

One block per model: whether the docshelf skill was loaded, docshelf calls,
calls that ended in a docshelf error, other tools used, the docshelf I/O
estimate ((characters typed + characters printed) / 4, as in the
2026-11-18 Haiku trial), input tokens, and which expected answers are
missing from the reply. -v adds every docshelf command and the reply.

The answer checks are patterns over the reply, so read a flagged reply
before calling it wrong. Adapted from the dash-docset trial scorer
(rjstone/experiments, branch skill/dash-docset).
"""
import json
import os
import re
import sys

args = sys.argv[1:]
verbose = "-v" in args
dirs = [a for a in args if a != "-v"]

CHECKS = [
    ("Z1 divFloor=-2", r"divFloor[\s\S]{0,120}(-2|−2)"),
    ("Z1 divTrunc=-1", r"divTrunc[\s\S]{0,120}(-1|−1)"),
    ("Z2 continue :label", r"continue\s*:\s*\w+"),
    ("Z2 operand", r"operand"),
    ("Z3 @Int(.unsigned, 18)", r"@Int\(\s*\.unsigned\s*,\s*18\s*\)"),
    ("Z3 std.lang.Signedness", r"std\.lang\.Signedness"),
    ("Z3 bits: u16", r"bits\s*:\s*u16"),
]
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
    try:
        with open(os.path.join(d, "out", "summary.txt")) as f:
            summary = f.read().strip()
    except OSError:
        summary = "no summary"
    skill, cmds, bad, other, texts, errs = False, [], [], [], [], []
    io_chars = tok_in = 0
    for e in events(os.path.join(d, "out", "zig.jsonl")):
        t, part = e.get("type"), e.get("part") or {}
        if t == "tool_use":
            st = part.get("state") or {}
            inp = st.get("input") or {}
            out = str(st.get("output") or st.get("error") or "")
            blob = json.dumps(inp)
            if part.get("tool") == "skill" and "docshelf" in blob:
                skill = True
            cmd = inp.get("command", "")
            if "docshelf.py" in cmd:
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
    reply = "\n".join(texts)
    miss = [n for n, rx in CHECKS if not re.search(rx, reply)]
    print("%s | skill=%s docshelf-calls=%d errors=%d other-tools=%d "
          "docshelf-io~tok=%d input-tokens=%d"
          % (summary, "Y" if skill else "N", len(cmds), len(bad), len(other),
             io_chars // 4, tok_in))
    print("   answers missing: %s" % (", ".join(miss) or "none"))
    for x in errs:
        print("   RUN ERROR " + x)
    for cmd, out in bad[: (30 if verbose else 5)]:
        print("   ERROR $ " + short(typed(cmd), 160))
        print("        -> " + short(out, 200))
    if verbose:
        for c in cmds:
            print("   $ " + short(typed(c), 170))
        for o in other:
            print("   other: " + o)
        print("   REPLY: " + short("\n".join(texts[-2:]), 2000))
    elif miss or not skill:
        print("   REPLY: " + short("\n".join(texts[-2:]), 700))
