"""Replay each docshelf command an agent ran (from its transcript) and count
characters. typed = 'python scripts/docshelf.py ARGS' plus any '| head -N'
(what an agent types with a default cache, no setup); out = characters the
command prints (stdout+stderr, after the agent's own head limit).
tokens ~= (typed+out)/4. Prints labels and numbers only.

Usage: DOCSHELF_CACHE_DIR=<trial cache> python3 replay_docshelf.py \
           node-skill=<transcript.jsonl> [zig-skill=<transcript.jsonl> ...]
Commands are re-run in the agent's form (with its own paths and pipes), so
the cache must hold the same docvol versions as the trial."""
import json, os, re, subprocess, sys

# The skill folder, found from this file (docs/trials/<trial>/tools/ in the
# repo). Set DOCSHELF_CACHE_DIR to the cache the trial used before running.
SK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "..", "..", "..", "skills", "docshelf"))
ENV = dict(os.environ)

def segments(cmd):
    # a shell variable holding the script path (S=.../docshelf.py; $S show ...)
    svars = dict((v, p) for v, p in re.findall(
        r"\b([A-Za-z_]\w*)=([^\s;&]*docshelf\.py)", cmd))
    for seg in re.split(r";|&&|\n", cmd):
        seg = seg.strip()
        for v, p in svars.items():
            seg = seg.replace("$%s " % v, p + " ").replace('"$%s" ' % v, p + " ")
        if "docshelf.py" not in seg or re.match(r"(export\s|[A-Za-z_]\w*=)", seg):
            continue
        yield seg

def run(path, title):
    rows = []
    for line in open(path):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        c = (d.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        for x in c:
            if x.get("type") != "tool_use" or x["name"] != "Bash":
                continue
            cmd = x["input"]["command"]
            if "answers/" in cmd:
                continue
            for seg in segments(cmd):
                args = re.sub(r"^.*?docshelf\.py\s*", "", seg)
                args = re.sub(r"\s*2>&1", "", args)
                typed = "python scripts/docshelf.py " + args
                out = subprocess.run(seg, shell=True, env=ENV, capture_output=True,
                                     text=True, cwd=SK)
                shown = 0 if ">/dev/null" in seg.replace(" ", "") and "2>&1" in seg \
                    else len(out.stdout) + len(out.stderr)  # the agent saw nothing
                rows.append((args[:62], len(typed), shown))
    print("== " + title)
    print("%-64s %6s %7s %6s" % ("docshelf command (as run)", "typed", "out", "~tok"))
    ti = to = 0
    for a, t, o in rows:
        ti += t; to += o
        print("%-64s %6d %7d %6d" % (a, t, o, (t + o) // 4))
    print("%-64s %6d %7d %6d" % ("TOTAL (%d commands)" % len(rows), ti, to, (ti + to) // 4))

for arg in sys.argv[1:]:
    t, p = arg.split("=", 1)
    run(p, t)
