"""Print the opencode client object type as a readable nested interface.

Reads `dist/promise/client.d.ts` of an installed `@opencode/client`
(`make()`'s return type, emitted by tsc as one big object literal) and prints
it vendor-docs style: `name(input, requestOptions?): Promise<Output>`, with
`import("...").` qualifiers dropped and multi-line inline return types folded
onto one line. Lines longer than --max-line are replaced by a comment naming
the member (the event `subscribe` signature spells out every event name).

With --api, first prints the `XApi = OpenCodeClient["x"]` aliases from
`dist/promise/api.d.ts` (the slices the plugin context's domains derive from).

Used to write references/client.local.md. Stdlib only.

    python scripts/client_outline.py <client>/dist/promise/client.d.ts
    python scripts/client_outline.py <client.d.ts> --api <api.d.ts> --max-line 200

Unclassified lines are printed as-is and listed on stderr.
"""
import argparse
import re
import sys

MAKE = "export declare function make(options: ClientOptions): {"
METHOD = re.compile(r"^(\s*)([A-Za-z_$][\w$]*): (\(.*\)) => (.+);$")
GROUP = re.compile(r"^(\s*)([A-Za-z_$][\w$]*): \{$")
CLOSE = re.compile(r"^(\s*)\};?$")
ALIAS = re.compile(r"^export type (\w+) = Client(\[.+\]);$")


def clean(text):
    text = re.sub(r'import\("[^"]*"\)\.', "", text)
    return text.replace("OpenCode.RequestOptions", "RequestOptions")


def fold(lines):
    """Join `=> Promise<{` ... `}>;` inline return types onto one line."""
    out, pending = [], None
    for line in lines:
        if pending is not None:
            pending += " " + line.strip()
            if line.strip() == "}>;":
                out.append(pending.replace("; }>;", " }>;"))
                pending = None
            continue
        if line.rstrip().endswith("=> Promise<{"):
            pending = line.rstrip()
            continue
        out.append(line)
    if pending is not None:
        out.append(pending)
    return out


def outline(dts, max_line=1000):
    """(lines, unclassified) for the make() return type in client.d.ts text."""
    text = clean(dts)
    if MAKE not in text:
        raise ValueError("no `make(options: ClientOptions)` declaration found")
    body = text.split(MAKE, 1)[1]
    out, bad = ["interface OpenCodeClient {"], []
    for line in fold(body.splitlines()):
        if not line.strip():
            continue
        if m := METHOD.match(line):
            ind, name, params, ret = m.groups()
            line = f"{ind}{name}{params}: {ret}"
        elif GROUP.match(line):
            pass
        elif m := CLOSE.match(line):
            line = m.group(1) + "}"
        else:
            bad.append(line)
        if len(line) > max_line:
            ind = line[: len(line) - len(line.lstrip())]
            name = re.match(r"\s*([\w$]+)", line).group(1)
            line = f"{ind}// {name}: signature over {max_line} characters, see client.d.ts"
        out.append(line)
        if line == "}" and not line.startswith(" "):
            break
    return out, bad


def aliases(api_dts):
    """`type XApi = OpenCodeClient["x"]` lines from api.d.ts text."""
    out = []
    for line in api_dts.splitlines():
        if m := ALIAS.match(line.strip()):
            out.append(f"type {m.group(1)} = OpenCodeClient{m.group(2)}")
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("client_dts", help="path to @opencode/client dist/promise/client.d.ts")
    p.add_argument("--api", help="path to dist/promise/api.d.ts: print its aliases first")
    p.add_argument("--max-line", type=int, default=1000)
    a = p.parse_args(argv)
    if a.api:
        with open(a.api, encoding="utf-8") as f:
            print("\n".join(aliases(f.read())) + "\n")
    with open(a.client_dts, encoding="utf-8") as f:
        lines, bad = outline(f.read(), a.max_line)
    print("\n".join(lines))
    for b in bad:
        print("unclassified:", b.strip()[:200], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
