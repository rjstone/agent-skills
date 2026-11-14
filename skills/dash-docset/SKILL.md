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

Install Dash docsets and search them offline with `python scripts/docset.py`
(stdlib only). The script's `--help` and `<command> --help` are the command
reference; this file covers only what they don't.

## When to use

Use for exact, version-pinned reference (signatures, options, return values)
that should be quoted from the docs, offline or without a network round trip.
Prefer Context7 or web search when the library has no docset or you need the
very latest release; prefer a per-library skill when one exists and covers the
task. Docsets can be stale: check `list` for versions. See "Other options"
below before installing, in case another tool suits the user better.

If the network only reaches allowed hosts (a sandbox, a corporate proxy, a
cloud agent environment) and downloads or source lists fail, give the user
[assets/allowlist.txt](assets/allowlist.txt): the hosts to allow.

Kapeli's terms (README of github.com/Kapeli/feeds) allow its docsets for
personal use or with Dash or Zeal, and not in other applications without
Kapeli's permission. If the use looks non-personal (a product, a service,
a shared team tool), point the user to those terms. User-contributed
docsets carry their own licences.

## First run: choose a storage location

1. Run `python scripts/docset.py where`. If it prints a location, go on.
2. Otherwise run `where --discover` to find existing dasht, Zeal and Dash
   folders.
3. Never pick a location yourself. Offer the user these choices:
   - Also read docsets from the existing folders found (saves re-downloading;
     read-only, add with `--read-from DIR`). Still needs one of the stores
     below for notes and indexes.
   - A new permanent central folder (suggest `~/.local/share/dash-docset`).
   - `.docsets/` in the user's project: docsets are large, the script writes a
     `.gitignore` that ignores them but keeps `notes/` so notes can be
     committed. Warn about the size.
   - A temporary folder (lost on reboot; one-off sessions, CI). The user
     names or approves the path.
4. Run `where --set PATH [--project|--user] [--read-from DIR]` with the choice.
   Quote a `~` path (`'~/.local/share/dash-docset'`): the script expands it
   and the config keeps the portable form.

Never write into a Dash, Zeal or dasht folder; docsets found there are
read-only to the script (`update` and `remove` refuse them).

## Workflow

1. Find a docset: `sources QUERY` (matches names, titles and keywords),
   then `install NAME` (several at once is fine). Prefix names when you
   can (`kapeli:Name`, `user:Name`, `cheat:Name`); a prefix is required
   when sources share a name. Official names match Dash's feed files
   (`kapeli:Python`, `kapeli:NodeJS`, `kapeli:Django`) or Zeal's names
   (`kapeli:Python_3`, `kapeli:Python_2`). `kapeli:Python` is the newest
   Python; `kapeli:Python_3` is the same feed limited to 3.x (and
   `Python_2` to 2.x), so `update` never crosses that line. Git is only a cheat sheet
   (`cheat:Git`). Pin an older official version with `@`:
   `kapeli:Python@3.12` installs the newest 3.12.x and `update` keeps the
   pin. A not-found error suggests close names and the other prefixes.
   Source lists are cached for a week; `sources --refresh` re-checks them.
   A "note:" on stderr says when a list came from a fallback source. Cheat
   sheets are short (Git's has 81 entries); prefer a full docset when one
   exists.
2. `search QUERY` finds entries by name and prints a REF for each. Hits
   below the "fuzzy matches" line only share letters in order; treat them
   as misses. No hits prints "no matches" and exits 0 (exit 5 means a
   named docset or REF doesn't exist).
3. `show REF` prints that entry's trimmed section plus your notes. The
   default cap is 150 lines; `--full` lifts it (page REFs from `fts` are
   capped the same way). Respect `--max-lines` on
   `search`, `fts` and `show` instead of dumping everything.
4. `fts QUERY` searches the text inside pages when entry names don't match.
   Each hit prints `<Name>:page:<path>#<anchor>`: `show` on it prints the
   section around the match (without `#<anchor>`, the whole page). The
   first `fts` on a docset builds its index (seconds for large docsets);
   `index-text NAME` builds it ahead of time.
5. Manage: `list` shows installed docsets and versions, `update [NAME]`
   refreshes one or all, `remove NAME` deletes one (notes are kept).
6. Exit codes are listed at the end of `--help` (3: location not set,
   5: not found, 7: network or incomplete source list).
7. Scope: a project `"docsets"` list in `.dash-docset.json` limits searches to
   those docsets. Without one, searches cover every docset unless more than 4
   are full-size; then narrow with `-d NAME` (repeatable), set the list, or
   pass `--all`.

## Notes

Keep durable lessons (gotchas, project conventions) in the docset's notes
file. Find it with `notes DOCSET --path` (creates the `notes/` folder; the
file itself appears when you write it),
and edit it with normal file tools. Format: a `## General` section, plus
`## <entry name>` sections (optional ` (Type)` suffix to disambiguate). Only
`show` prints notes: General and the matching section (General alone for
page REFs), so many small sections are cheap and one big one is not.

Run `notes DOCSET --check` after editing: it warns about oversized notes and
headings that match no entry. On a size warning, suggest to the user turning
the heavy section into its own minimal skill built around the tasks it
covers.

## Other options

Mention these to the user when they fit better:

- Dash installed (macOS): Kapeli's MCP servers talk to the Dash app and use
  its docsets directly: https://github.com/Kapeli/dash-mcp-server (Python)
  or https://github.com/Kapeli/dash-mcp-server-node (Node.js).
- An MCP server instead of a CLI, without Dash or Zeal:
  https://github.com/keturn/ZDocsetMCP.
- Reading docs directly in a viewer app: Zeal (Linux, Windows;
  https://zealdocs.org/) or Dash (macOS; https://kapeli.com/).
- Docset sources, to browse or contribute:
  https://github.com/Kapeli/Dash-User-Contributions and
  https://github.com/Kapeli/cheatsheets.
