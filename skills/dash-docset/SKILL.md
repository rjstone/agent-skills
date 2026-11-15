---
name: dash-docset
description: Use when you need exact API, framework or library reference from Dash docsets (Kapeli, user-contributed, cheat sheets) offline, or when installing, updating, searching or annotating docsets from the command line.
compatibility: network access needed for docset downloads and source lists; searching installed docsets works offline. Host allowlist in assets/allowlist.txt.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# Dash docsets

Search Dash docsets offline with `python scripts/docset.py` (stdlib only;
the path is relative to this skill's folder). Stay in the project folder and
give the script's full path; don't `cd` to the skill folder, because a
project's `.dash-docset.json` is found from the current folder. Run its
`--help` first: that is the command reference, with the usual command lines. A subcommand's own `--help` only adds the rarer options that
`--help` names at its end. This file covers what help can't.

Use for exact, version-pinned reference (signatures, options, return values)
quoted from the docs. Prefer Context7 or web search when the library has no
docset or you need the very latest release, and a per-library skill when one
covers the task. Docsets can be stale: `list` shows versions.

Kapeli's terms (README of github.com/Kapeli/feeds) allow its docsets for
personal use or with Dash or Zeal, and not in other applications without
Kapeli's permission. If the use looks non-personal (a product, a service, a
shared team tool), point the user to those terms. User-contributed docsets
carry their own licences.

## Read when needed

- `where` exits 3 (no location set), or the user asks how to set up:
  [references/setup.md](references/setup.md) (also lists alternatives such
  as Kapeli's Dash MCP server).
- Before `sources`, `install`, `update` or `remove`, or on exit 7 (network
  or incomplete source list): [references/installing.md](references/installing.md).
- Before writing notes: [references/notes.md](references/notes.md).

## Looking things up

- Try `search` first; use `fts` when names don't match. Function options,
  parameters and settings are often only in page text (`read_csv`'s `skip`
  is a row in a table), so look for them with `fts`, adding the function
  name (`fts read_csv skip`, not `fts skip`).
- Hits below a "fuzzy matches" line only share letters in order; treat them
  as misses. Entries that open the same section are listed once.
- For one option or row of a long section, `show REF --grep TEXT` prints
  every matching line, and a matching parameter name comes with its
  description; `...` marks lines without a match, so there's no need to
  rerun without `--grep` or to pipe the section through `grep`. A `(page: Title)` line names the page a
  section belongs to.
- Scope: a project `"docsets"` list in `.dash-docset.json` limits searches
  to those docsets. Without one, searches cover every docset unless more
  than 4 are full-size; then narrow with `-d NAME`, set the list, or pass
  `--all`. The first `fts` on a docset builds its index (seconds for large
  docsets).
