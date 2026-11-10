"""Print exported interface/type declarations from installed .d.ts files.

Scans every `*.d.ts` in a folder (default pattern: the plugin context's
domain types, `\\w*Domain`) and prints each matching `export interface` /
`export type` declaration whole, with `import("...").` qualifiers dropped and
a `// <file>` comment above it. Relies on tsc's emitted layout: an interface
ends at a line that is just `}`; a type alias ends at the first line ending
in `;` with its braces, brackets and parentheses balanced.

Used to write references/plugins-server.local.md. Stdlib only.

    python scripts/dts_decls.py <plugin>/dist/promise
    python scripts/dts_decls.py <plugin>/dist/promise --names "Transform|Hooks|ModelHooks|Registration"
    python scripts/dts_decls.py <plugin>/dist/promise --names "\\w*Editor" --files tool.d.ts

<plugin> is node_modules/@opencode/plugin, or bun's cache entry for it.
"""
import argparse
import glob
import os
import re
import sys

OPEN = "{[("
CLOSE = "}])"


def depth_change(line):
    return sum(line.count(c) for c in OPEN) - sum(line.count(c) for c in CLOSE)


def declarations(dts, names=r"\w*Domain"):
    """[(name, text)] for exported declarations whose name fully matches `names`."""
    head = re.compile(r"^export (?:declare )?(interface|type) (" + names + r")\b(?![\w$])")
    lines = re.sub(r'import\("[^"]*"\)\.', "", dts).splitlines()
    out, i = [], 0
    while i < len(lines):
        m = head.match(lines[i])
        if not m or not re.fullmatch(names, m.group(2)):
            i += 1
            continue
        kind, j = m.group(1), i
        if kind == "interface":
            while j < len(lines) and lines[j] != "}" and not (
                j == i and lines[j].rstrip().endswith("}")
            ):
                j += 1
        else:
            depth = 0
            while j < len(lines):
                depth += depth_change(lines[j])
                if depth <= 0 and lines[j].rstrip().endswith(";"):
                    break
                j += 1
        out.append((m.group(2), "\n".join(lines[i : j + 1])))
        i = j + 1
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("folder", help="folder of .d.ts files, e.g. <plugin>/dist/promise")
    p.add_argument("--names", default=r"\w*Domain", help="regex the whole name must match")
    p.add_argument("--files", default="*.d.ts", help="glob within the folder")
    a = p.parse_args(argv)
    found = 0
    for path in sorted(glob.glob(os.path.join(a.folder, a.files))):
        with open(path, encoding="utf-8") as f:
            for _, text in declarations(f.read(), a.names):
                print(f"// {os.path.basename(path)}\n{text}\n")
                found += 1
    if not found:
        print(f"no declarations matching {a.names!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
