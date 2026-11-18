"""Replay the docshelf commands a CLI agent ran (from its transcript) through
`docshelf.py --mcp`, and count characters on both interfaces for the SAME
queries:
  CLI: typed = 'python scripts/docshelf.py ARGS'; out = what the command prints
  MCP: typed = the tool call's JSON arguments; out = the tool result text
A '| head -N' the agent used is applied to both outputs. `--help` has no MCP
counterpart (the server's `instructions` play that part) and is listed
separately. tokens ~= (typed+out)/4. Prints labels and numbers only.

Usage: DOCSHELF_CACHE_DIR=<trial cache> python3 replay_mcp.py \\
           node=<transcript.jsonl> [zig=<transcript.jsonl> ...]"""
import json, os, re, shlex, subprocess, sys

SK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "..", "..", "..", "skills", "docshelf"))
SCRIPT = os.path.join(SK, "scripts", "docshelf.py")

def segments(cmd):
    # a shell variable holding the script path (S=.../docshelf.py; $S show ...)
    svars = dict((v, p) for v, p in re.findall(
        r"\b([A-Za-z_]\w*)=([^\s;&]*docshelf\.py)", cmd))
    for seg in re.split(r";|&&|\n", cmd):
        seg = seg.strip()
        for v, p in svars.items():
            seg = seg.replace("$%s " % v, p + " ").replace('"$%s" ' % v, p + " ")
        if "docshelf.py" in seg and not re.match(r"(export\s|[A-Za-z_]\w*=)", seg):
            yield seg

def to_call(args):
    """CLI args -> (tool, arguments) or None."""
    w = shlex.split(args)
    if not w or w[0].startswith("--help"):
        return None
    cmd, rest, a, pos = w[0], w[1:], {}, []
    i = 0
    while i < len(rest):
        t = rest[i]
        if t == "-d":
            a.setdefault("docvols", []).append(rest[i + 1]); i += 2; continue
        if t.startswith("--grep="):
            a.setdefault("grep", []).append(t.split("=", 1)[1]); i += 1; continue
        if t in ("--max-lines", "--offset", "--type"):
            a[t[2:].replace("-", "_")] = int(rest[i + 1]) if t != "--type" else rest[i + 1]
            i += 2; continue
        if t in ("--full", "--all", "--json"):
            a[t[2:]] = True; i += 1; continue
        pos.append(t); i += 1
    if cmd in ("search", "fts", "sources"):
        a["query"] = pos
    elif cmd in ("show", "toc"):
        a["ref"] = pos[0]
    return cmd, a

def head(text, seg):
    m = re.search(r"\|\s*head\s+-(\d+)", seg)
    return "".join(text.splitlines(True)[:int(m.group(1))]) if m else text

class Server:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, SCRIPT, "--mcp"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, cwd=SK)
        self.n = 0
        r = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "replay", "version": "0"}})
        self.instructions = r.get("instructions", "")
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.schemas = json.dumps(self.rpc("tools/list", {})["tools"])
    def rpc(self, method, params):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method,
                                       "params": params}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())["result"]
    def call(self, tool, args):
        r = self.rpc("tools/call", {"name": tool, "arguments": args})
        return "".join(c.get("text", "") for c in r["content"])

def run(path, title, srv):
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
            if x.get("type") != "tool_use" or x["name"] != "Bash" or "answers/" in x["input"]["command"]:
                continue
            for seg in segments(x["input"]["command"]):
                args = re.sub(r"\s*2>&1", "", re.sub(r"^.*?docshelf\.py\s*", "", seg))
                args = re.sub(r"\s*\|.*$", "", args)
                cli_typed = len("python scripts/docshelf.py " + args)
                out = subprocess.run(seg, shell=True, capture_output=True, text=True, cwd=SK)
                cli_out = len(out.stdout) + len(out.stderr)
                call = to_call(args)
                if call is None:
                    rows.append((args[:40], cli_typed, cli_out, None, None)); continue
                mcp_out = len(head(srv.call(*call), seg))
                rows.append((args[:40], cli_typed, cli_out, len(json.dumps(call[1])), mcp_out))
    print("== " + title)
    print("%-42s %6s %6s %6s | %6s %6s %6s" % ("command", "typed", "out", "~tok", "json", "result", "~tok"))
    tc = tm = hc = 0
    for a, ct, co, mt, mo in rows:
        if mt is None:
            hc += (ct + co) // 4
            print("%-42s %6d %6d %6d | %20s" % (a, ct, co, (ct + co) // 4, "(no MCP counterpart)"))
            continue
        tc += (ct + co) // 4; tm += (mt + mo) // 4
        print("%-42s %6d %6d %6d | %6d %6d %6d" % (a, ct, co, (ct + co) // 4, mt, mo, (mt + mo) // 4))
    print("%-42s %20d | %20d   (same queries; --help excluded: %d)" % ("TOTAL ~tokens", tc, tm, hc))

srv = Server()
print("MCP fixed context: instructions %d chars (~%d tok), tool schemas %d chars (~%d tok)"
      % (len(srv.instructions), len(srv.instructions) // 4, len(srv.schemas), len(srv.schemas) // 4))
skill = os.path.join(SK, "SKILL.md")
print("CLI fixed context: SKILL.md %d chars (~%d tok)" % (os.path.getsize(skill), os.path.getsize(skill) // 4))
for arg in sys.argv[1:]:
    t, p = arg.split("=", 1)
    run(p, t, srv)
