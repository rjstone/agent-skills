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
the path is relative to this skill's folder, so from elsewhere give its full
path). `--help` and `<command> --help` are the command reference; this file
covers only what they don't.

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

1. `search QUERY` finds entries by name and prints a REF for each. Several
   words need no quotes; a name must contain all of them (`search walking
   speed` finds `hero:get_walking_speed()`). Hits below the "fuzzy matches"
   line only share letters in order; treat them as misses (when real hits
   exist, fuzzy ones are hidden). No hits prints "no matches" and exits 0;
   exit 5 means a named docset or REF doesn't exist.
2. `show REF` prints that entry's trimmed section plus any notes, capped at
   150 lines (`--full` lifts the cap). Use `--max-lines` on `search`, `fts`
   and `show` rather than dumping everything.
3. `fts QUERY` searches the text inside pages when entry names don't match.
   Function options, parameters and settings are often only in page text
   (e.g. `read_csv`'s `skip` is a row in a table), so look for them with
   `fts`. Each hit prints a REF for the section around the match: an entry
   REF (`<Name>:<id>`) when that section is an entry's, else
   `<Name>:page:<path>#<anchor>` (without `#<anchor>`, `show` prints the
   whole page). The first `fts` on a docset builds its index (seconds for
   large docsets).
4. Scope: a project `"docsets"` list in `.dash-docset.json` limits searches
   to those docsets. Without one, searches cover every docset unless more
   than 4 are full-size; then narrow with `-d NAME` (repeatable; the name
   `list` prints), set the list, or pass `--all`.
