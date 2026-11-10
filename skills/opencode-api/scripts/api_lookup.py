#!/usr/bin/env python3
"""Search the cached opencode server OpenAPI spec (references/openapi.json)
without reading all of it.

    python scripts/api_lookup.py --tags                  # tags with operation counts
    python scripts/api_lookup.py --list session          # operations by tag or path/id substring
    python scripts/api_lookup.py --op session.create     # one operation: params (in, style), body,
                                                         # responses, opencode api and curl lines
    python scripts/api_lookup.py --op POST /api/session  # same, by method and path
    python scripts/api_lookup.py --schema Session        # one schema, $refs expanded
    python scripts/api_lookup.py --grep "server info"    # words in ids, paths, summaries

Paths are relative to this skill's folder. --depth N limits $ref expansion
(default 3). Exit 2 when nothing matches. Standard library only.
"""
import argparse
import difflib
import json
import os
import sys

SPEC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references", "openapi.json")
METHODS = ("get", "post", "put", "patch", "delete")


def operations(spec):
    for path, item in spec.get("paths", {}).items():
        for method in METHODS:
            op = item.get(method)
            if isinstance(op, dict):
                yield method.upper(), path, op


def resolve(spec, node, depth, seen=()):
    """Expand $refs up to `depth` levels; a repeated ref stays a ref (no loops)."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if ref:
            name = ref.rsplit("/", 1)[-1]
            if depth <= 0 or ref in seen:
                return {"$ref": name}
            target = spec
            for part in ref.lstrip("#/").split("/"):
                target = target.get(part, {}) if isinstance(target, dict) else {}
            return {"$schema_name": name, **resolve(spec, target, depth - 1, seen + (ref,))}
        return {k: resolve(spec, v, depth, seen) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve(spec, v, depth, seen) for v in node]
    return node


def find_op(spec, query):
    q = " ".join(query).strip()
    parts = q.split(None, 1)
    for method, path, op in operations(spec):
        if op.get("operationId") == q:
            return method, path, op
        if len(parts) == 2 and parts[0].upper() == method and parts[1] == path:
            return method, path, op
    return None


def param_flags(p):
    """'query, required, style=deepObject, explode': where and how a parameter is sent."""
    flags = [p.get("in", "?")]
    if p.get("required"):
        flags.append("required")
    if p.get("style"):
        flags.append("style=" + p["style"])
        if "explode" in p:
            flags.append("explode" if p["explode"] else "no explode")
    return ", ".join(flags)


def query_example(p):
    """How a query parameter appears in the URL. deepObject sends each property
    as name[prop]=value; everything else here is name=value."""
    name = p.get("name", "?")
    if p.get("style") == "deepObject":
        props = (p.get("schema") or {}).get("properties") or {}
        if props:
            return "&".join("%s[%s]=<%s>" % (name, k, k) for k in props)
        return "%s[<key>]=<value>" % name
    return "%s=<%s>" % (name, name)


def curl_example(method, path, params, body):
    """A curl line to adapt: Basic auth, the required and deepObject query
    parameters (optional ones are in the parameter list), a JSON body if any."""
    query = [query_example(p) for p in params
             if p.get("in") == "query" and (p.get("required") or p.get("style") == "deepObject")]
    url = "http://127.0.0.1:<port>" + path + ("?" + "&".join(query) if query else "")
    parts = ["curl"]
    if "[" in url:
        parts.append("-g")  # curl globbing would eat the brackets
    parts.append("-u opencode:$OPENCODE_PASSWORD")
    if method != "GET":
        parts.append("-X " + method)
    if body:
        parts.append("-H 'content-type: application/json' -d '<json>'")
    parts.append('"%s"' % url)
    return " ".join(parts)


def show_op(spec, method, path, op, depth):
    oid = op.get("operationId", "")
    print("%s %s  (%s)" % (method, path, oid))
    for key in ("summary", "description"):
        if op.get(key):
            print("%s: %s" % (key, op[key]))
    if op.get("tags"):
        print("tags: " + ", ".join(op["tags"]))
    params = [resolve(spec, p, depth) for p in op.get("parameters", [])]
    if params:
        print("parameters:")
        for p in params:
            print("  - %s (%s): %s" % (p.get("name"), param_flags(p), json.dumps(p.get("schema", {}))))
            if p.get("in") == "query" and p.get("style") == "deepObject":
                print("    in the URL: ?%s  (not ?%s=... and not the bare property names)"
                      % (query_example(p), p.get("name")))
    body = op.get("requestBody")
    if body:
        print("request body:")
        print(json.dumps(resolve(spec, body, depth), indent=2))
    if op.get("responses"):
        print("responses:")
        print(json.dumps(resolve(spec, op["responses"], depth), indent=2))
    args = ""
    if any(p.get("in") == "query" for p in params):
        args += " --param <name>=<value>"
    if body:
        args += " --data '<json>'"
    print("call: opencode api %s%s" % (oid or "%s %s" % (method, path), args))
    print("curl: " + curl_example(method, path, params, body))


def main(argv=None, spec=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--tags", action="store_true")
    g.add_argument("--list", metavar="TAG_OR_TEXT", nargs="?", const="")
    g.add_argument("--op", nargs="+", metavar="ID_OR_METHOD_PATH")
    g.add_argument("--schema", metavar="NAME")
    g.add_argument("--grep", metavar="WORDS")
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--spec", default=SPEC_PATH, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if spec is None:
        with open(a.spec, encoding="utf-8") as f:
            spec = json.load(f)
    ops = list(operations(spec))

    if a.tags:
        counts = {}
        for _, _, op in ops:
            for t in op.get("tags", ["(none)"]):
                counts[t] = counts.get(t, 0) + 1
        for t, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
            print("%4d  %s" % (n, t))
        return 0

    if a.list is not None:
        q = a.list.lower()
        hits = [(m, p, op) for m, p, op in ops
                if not q or q in [t.lower() for t in op.get("tags", [])]
                or q in p.lower() or q in (op.get("operationId") or "").lower()]
        for m, p, op in hits:
            print("%-6s %s  %s  %s" % (m, p, op.get("operationId", ""), op.get("summary", "")))
        return 0 if hits else 2

    if a.op:
        hit = find_op(spec, a.op)
        if not hit:
            ids = [op.get("operationId", "") for _, _, op in ops]
            close = difflib.get_close_matches(" ".join(a.op), ids, n=5, cutoff=0.3)
            print("No operation %r. Close: %s. Try --list <tag> or --grep <words>." % (" ".join(a.op), ", ".join(close) or "none"))
            return 2
        show_op(spec, *hit, depth=a.depth)
        return 0

    if a.schema:
        schemas = spec.get("components", {}).get("schemas", {})
        if a.schema not in schemas:
            close = difflib.get_close_matches(a.schema, list(schemas), n=5, cutoff=0.4)
            print("No schema %r. Close: %s" % (a.schema, ", ".join(close) or "none"))
            return 2
        print(json.dumps(resolve(spec, {"$ref": "#/components/schemas/" + a.schema}, a.depth), indent=2))
        return 0

    words = a.grep.lower().split()
    hits = []
    for m, p, op in ops:
        fields = {"id": op.get("operationId", ""), "path": "%s %s" % (m, p),
                  "summary": op.get("summary", ""), "description": op.get("description", "")}
        hay = " ".join(fields.values()).lower()
        if all(w in hay for w in words):
            where = [k for k, v in fields.items() if any(w in v.lower() for w in words)]
            hits.append((m, p, op, where))
    for m, p, op, where in hits:  # [fields] shows why it matched
        print("%-6s %s  %s  %s  [%s]" % (m, p, op.get("operationId", ""), op.get("summary", ""), ", ".join(where)))
    return 0 if hits else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # e.g. piped into head
        sys.exit(0)
