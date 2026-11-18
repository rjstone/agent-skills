"""Per-call character counts from a Claude Code subagent transcript (JSONL)
file, e.g. ~/.claude/projects/<project>/<session>/subagents/agent-<id>.jsonl.
Prints labels and numbers only, never transcript text beyond a short label.
in = characters the agent typed for the call (the command, or the tool's
JSON input); out = characters the tool returned. tokens ~= (in+out)/4."""
import json, re, sys

def text_len(c):
    if isinstance(c, str):
        return len(c)
    if isinstance(c, list):
        return sum(len(x.get("text", "")) for x in c if isinstance(x, dict))
    return 0

def label(name, inp):
    if name == "Bash":
        cmd = inp.get("command", "")
        if "answers/" in cmd or "cat >" in cmd or "<<" in cmd:
            return "WRITE answers (bash)"
        subs = re.findall(r"(?:docshelf\.py|\$D|docshelf)\s+([a-z-]+(?:\s+[^;&|\n]{0,40})?)", cmd)
        if subs:
            return "docshelf " + " ; ".join(x.strip() for x in subs)[:66]
        w = cmd.split()
        return "bash: " + (w[0] if w else "")
    if name == "Skill":
        return "Skill " + inp.get("skill", "")
    if name == "Write":
        return "WRITE answers"
    if name == "Read":
        p = inp.get("file_path", "")
        return "%s %s" % (name, p.rsplit("/", 2)[-2] + "/" + p.rsplit("/", 1)[-1] if "/" in p else p)
    return name

def run(path, title):
    uses, rows = {}, []
    for line in open(path):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        c = (d.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        for x in c:
            if x.get("type") == "tool_use":
                inp = x.get("input", {})
                typed = len(inp["command"]) if x["name"] == "Bash" else len(json.dumps(inp))
                uses[x["id"]] = (label(x["name"], inp), typed)
            elif x.get("type") == "tool_result" and x.get("tool_use_id") in uses:
                lab, typed = uses[x["tool_use_id"]]
                rows.append((lab, typed, text_len(x.get("content"))))
    print("== " + title)
    print("%-70s %6s %7s %7s" % ("call", "in", "out", "~tok"))
    ti = to = 0
    for lab, i, o in rows:
        ti += i; to += o
        print("%-70s %6d %7d %7d" % (lab, i, o, (i + o) // 4))
    print("%-70s %6d %7d %7d" % ("TOTAL (%d calls)" % len(rows), ti, to, (ti + to) // 4))

for arg in sys.argv[1:]:
    title, path = arg.split("=", 1)
    run(path, title)
