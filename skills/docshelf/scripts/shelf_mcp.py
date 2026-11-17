"""docshelf --mcp: a stdio MCP server (newline-delimited JSON-RPC 2.0).

Every Command with mcp=True becomes a tool. Nothing but protocol messages is
ever written to the output stream: each tool call redirects stdout and stderr.
"""
import argparse
import contextlib
import io
import json
import re
import sys
from typing import Any, Dict, List, Optional, TextIO, Tuple

import shelf_cli
import shelf_core
import shelf_devdocs
from shelf_core import CLIError

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

# Sent in the initialize result: how a client's model should use the tools.
INSTRUCTIONS = (
    "Offline DevDocs and Dash/Zeal reference. Call `search` with a name; it "
    "prints REFs (docvol:path#anchor); pass one to `show` to read it. When "
    "names don't match, `fts` searches the words in page text (include the "
    "function name). `toc` lists a long page's headings; `show` a REF from "
    "it, or use `grep` to see only matching lines. Narrow searches with "
    "`docvols`; `suggest` proposes a project's docvols. Run `list` to see "
    "what is installed. Record lessons with `notes`."
)

# One-line fixes that replace a "references/X.md" (or assets/) pointer in an
# error message: a client has no skill folder to open.
HINTS = {
    "references/getting-docvols.md":
        "run the `sources` tool to find a name, then `install`",
    "references/notes.md":
        "notes files are plain Markdown, one section per entry; "
        "run the `notes` tool with check=true to see which REFs a section shows",
    "assets/allowlist.txt":
        "allow the hosts docshelf contacts (devdocs.io, documents.devdocs.io, "
        "api.github.com, api.zealdocs.org) in the network settings",
}
_POINTER = re.compile(
    r"(?:[Hh]osts to allow are |[Tt]he hosts docshelf may contact are )?"
    r"(?:listed in |see |in )?"
    r"((?:references|assets)/[\w.-]+\.(?:md|txt))"
    r"(?: in the skill folder)?(?: \([^)]*\))?")


def _dest(p: shelf_cli.Param) -> str:
    if not p.flags[0].startswith("-"):
        return p.flags[0]
    long = [f for f in p.flags if f.startswith("--")] or list(p.flags)
    return long[0].lstrip("-").replace("-", "_")


def _prop_name(p: shelf_cli.Param) -> str:
    d = _dest(p)
    return "docvols" if p.repeat and d == "docvol" else d


def _positional(p: shelf_cli.Param) -> bool:
    return not p.flags[0].startswith("-")


def _tool_params(c: shelf_cli.Command) -> List[shelf_cli.Param]:
    if c.name == "notes":  # read-only over MCP: no --path
        return [p for p in c.params if p.flags[0] != "--path"]
    return c.params


def _first_positional(c: shelf_cli.Command) -> Optional[shelf_cli.Param]:
    return next((p for p in _tool_params(c) if _positional(p)), None)


def _flag_names() -> Dict[str, str]:
    """CLI flag -> tool argument name, from the COMMANDS table."""
    names: Dict[str, str] = {}
    for c in _mcp_commands():
        for p in _tool_params(c):
            for f in p.flags:
                if f.startswith("-"):
                    names[f] = _prop_name(p)
    return names


_QUOTED = re.compile(r"""(?<!\w)'[^'\n]*'(?!\w)|"[^"\n]*\"""")


def explain(message: str) -> str:
    """Rewrite an error message for a tool caller: the replacement for each
    `docshelf.py <cmd>`, bare `<cmd> PLACEHOLDER` phrase or CLI flag is the
    tool or argument name, so nothing points at a command line."""
    def fix(m):
        return HINTS.get(m.group(1), m.group(0))
    message = _POINTER.sub(fix, message)
    # docshelf quotes user input ('x' or "x"); only the text around it is ours
    out, pos = [], 0
    for q in _QUOTED.finditer(message):
        out.append(_rewrite(message[pos:q.start()]))
        out.append(q.group(0))
        pos = q.end()
    out.append(_rewrite(message[pos:]))
    return "".join(out)


def _rewrite(message: str) -> str:
    cmds = {c.name: c for c in _mcp_commands()}
    alt = "|".join(re.escape(n) for n in sorted(cmds, key=len, reverse=True))
    flags = _flag_names()

    def flag_name(flag: str) -> str:
        return flags.get(flag) or flag.lstrip("-").replace("-", "_")

    def program(m):  # docshelf.py install alpha
        tool = "the `%s` tool" % m.group(1)
        arg, pos = m.group(2), _first_positional(cmds[m.group(1)])
        if not arg:
            return tool
        if arg.isupper():  # a placeholder such as QUERY
            return tool
        if pos is None:
            return "%s %s" % (tool, arg)
        many = pos.nargs in ("+", "*") or pos.repeat
        return "%s with %s %s" % (tool, _prop_name(pos),
                                  json.dumps([arg] if many else arg))

    message = re.sub(r"docshelf\.py (%s)(?: ([^\s)]+))?" % alt, program, message)

    def needs(m):  # install needs NAME
        pos = _first_positional(cmds[m.group(1)])
        return "the `%s` tool needs %s" % (
            m.group(1), "`%s`" % _prop_name(pos) if pos else "an argument")

    message = re.sub(r"\b(%s) needs [A-Z]{2,}\b" % alt, needs, message)

    def with_flag(m):  # install --force alpha
        rest = m.group(3)
        if rest and rest in message[:m.start()]:
            rest = None  # a value already named earlier in the message
        return "the `%s` tool with `%s`%s" % (
            m.group(1), flag_name(m.group(2)), " " + rest if rest else "")

    message = re.sub(r"\b(%s) (--[a-z][\w-]*)(?: ([^\s-]\w*))?" % alt,
                     with_flag, message)
    message = re.sub(r"\b(%s) [A-Z]{2,}(?:\.\.\.)?\b" % alt,
                     lambda m: "the `%s` tool" % m.group(1), message)
    return re.sub(r"(?<![\w-])(-d|--[a-z][\w-]*)(?![\w-])(?: [A-Z]{2,}\b)?",
                  lambda m: "`%s`" % flag_name(m.group(1)), message)


def _mcp_commands() -> List[shelf_cli.Command]:
    return [c for c in shelf_cli.COMMANDS if c.mcp]


def _schema(c: shelf_cli.Command) -> dict:
    props: Dict[str, Any] = {}
    required: List[str] = []
    for p in _tool_params(c):
        name = _prop_name(p)
        if p.kind == "flag":
            prop: Dict[str, Any] = {"type": "boolean"}
        elif p.kind in ("int", "posint", "nonneg"):
            prop = {"type": "integer"}
            if p.kind in ("posint", "nonneg"):
                prop["minimum"] = 1 if p.kind == "posint" else 0
        else:
            prop = {"type": "string"}
        if p.nargs in ("+", "*") or p.repeat:
            prop = {"type": "array", "items": prop}
        prop["description"] = p.help
        if p.default is not None:
            prop["default"] = p.default
        props[name] = prop
        if _positional(p) and p.nargs != "*":
            required.append(name)
    out = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def tool_schemas() -> List[dict]:
    return [{"name": c.name, "description": c.summary, "inputSchema": _schema(c)}
            for c in _mcp_commands()]


def _parser_defaults(c: shelf_cli.Command) -> dict:
    """Every dest the command's argparse parser defines, with its default, so
    tools and the command line cannot drift apart."""
    sub = shelf_cli.build_parser()._subparsers._group_actions[0].choices[c.name]
    return {a.dest: a.default for a in sub._actions if a.dest != "help"}


def _build_namespace(c: shelf_cli.Command, arguments: dict) -> argparse.Namespace:
    """Namespace as argparse would give it; raises ValueError on bad input."""
    ns = _parser_defaults(c)
    ns.update({"command": c.name, "help": False, "_command": c})
    known = set()
    for p in _tool_params(c):
        name, dest = _prop_name(p), _dest(p)
        known.add(name)
        if name != dest and name != "docvols":
            known.add(dest)
        value = arguments.get(name)
        if value is None and name != dest:
            value = arguments.get(dest)  # alias: "docvol"
        if p.kind == "flag":
            if value is not None and not isinstance(value, bool):
                raise ValueError("argument %s must be a boolean" % name)
            if value is not None:
                ns[dest] = value
            continue
        many = p.nargs in ("+", "*") or p.repeat
        if value is None:
            if _positional(p) and p.nargs != "*":
                raise ValueError("missing required argument: %s" % name)
            continue
        items = value if isinstance(value, list) else [value]
        if not many and isinstance(value, list):
            raise ValueError("argument %s must not be an array" % name)
        conv = []
        for item in items:
            if p.kind in ("int", "posint", "nonneg"):
                if isinstance(item, bool) or not isinstance(item, int):
                    raise ValueError("argument %s must be an integer" % name)
                if p.kind == "posint" and item < 1:
                    raise ValueError("argument %s must be >= 1" % name)
                if p.kind == "nonneg" and item < 0:
                    raise ValueError("argument %s must be >= 0" % name)
            elif not isinstance(item, str):
                raise ValueError("argument %s must be a string" % name)
            conv.append(item)
        if p.nargs == "+" and not conv:
            raise ValueError("missing required argument: %s" % name)
        ns[dest] = conv if many else conv[0]
    extra = sorted(k for k in arguments if k not in known)
    if extra:
        raise ValueError("unknown argument: %s" % ", ".join(extra))
    return argparse.Namespace(**ns)


def _result(text: str, is_error: bool) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_tool(name: str, arguments: Any) -> dict:
    cmds = {c.name: c for c in _mcp_commands()}
    if name not in cmds:
        return _result("unknown tool: %s" % name, True)
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _result("arguments must be an object", True)
    c = cmds[name]
    try:
        ns = _build_namespace(c, arguments)
    except ValueError as e:
        return _result(str(e), True)
    out, err = io.StringIO(), io.StringIO()
    code = 0
    message = cfg = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cfg = shelf_core.load_config()
            code = c.func(cfg, ns)
    except CLIError as e:
        code, message = e.code, explain(str(e))
        if e.docvol and cfg:
            message = shelf_devdocs.not_installed_message(
                cfg, e.docvol, lambda slug: "run the `install` tool with names "
                + json.dumps([slug])) or message
    except Exception as e:  # keep serving whatever a command does
        code, message = 1, "internal error: %s: %s" % (type(e).__name__, e)
    text = out.getvalue() + err.getvalue()
    if message is not None:
        text += message
    return _result(text, bool(code))


def _error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle(msg: Any) -> Optional[dict]:
    """Reply to one decoded message, or None (a notification)."""
    if not isinstance(msg, dict) or not isinstance(msg.get("method"), str):
        id_ = msg.get("id") if isinstance(msg, dict) else None
        return _error(id_ if isinstance(id_, (str, int)) else None,
                      -32600, "invalid request")
    if "id" in msg and msg["id"] is None:  # MCP forbids a null request id
        return _error(None, -32600, "invalid request")
    if "id" not in msg:
        return None
    id_, method = msg["id"], msg["method"]
    params = msg.get("params")
    if not isinstance(params, dict):
        params = {}
    if method == "initialize":
        want = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "docshelf", "version": shelf_core.VERSION},
            "instructions": INSTRUCTIONS}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": id_, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tool_schemas()}}
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            return _error(id_, -32602, "tools/call needs a tool name")
        return {"jsonrpc": "2.0", "id": id_,
                "result": call_tool(name, params.get("arguments"))}
    return _error(id_, -32601, "method not found: %s" % method)


def handle_batch(msgs: list) -> Any:
    """Reply to a JSON-RPC batch: the non-null replies in order as an array,
    None when every message was a notification, one error for `[]`."""
    if not msgs:
        return _error(None, -32600, "invalid request")
    replies = [r for r in map(handle, msgs) if r is not None]
    return replies or None


def serve(inp: TextIO, out: TextIO) -> int:
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = _error(None, -32700, "parse error")
        else:
            reply = handle_batch(msg) if isinstance(msg, list) else handle(msg)
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            out.flush()
    return 0
