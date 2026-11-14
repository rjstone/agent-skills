---
name: dash-docset
description: Use when you need exact API, framework or library reference from Dash docsets (Kapeli, user-contributed, cheat sheets) offline, or when installing, updating, searching or annotating docsets from the command line.
compatibility: network access to Kapeli feeds and GitHub for install/update; search works offline
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
task. Docsets can be stale: check `list` for versions.

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

Never write into a Dash, Zeal or dasht folder; docsets found there are
read-only to the script (`update` and `remove` refuse them).

## Workflow

1. Find a docset: `sources QUERY`, then `install NAME` (several at once is
   fine). Prefixed names (`kapeli:Name`, `user:Name`, `cheat:Name`) install
   without the GitHub API; unprefixed names and the official and cheat
   `sources` listings call api.github.com (anonymous limit 60 requests an
   hour), so prefix when you can. A prefix is required when sources share a
   name.
2. `search QUERY` finds entries by name and prints a REF for each.
3. `show REF` prints that entry's trimmed section plus your notes. The
   default cap is 150 lines; `--full` lifts it (page REFs from `fts` are
   capped the same way). Respect `--max-lines` on
   `search`, `fts` and `show` instead of dumping everything.
4. `fts QUERY` searches the text inside pages when entry names don't match.
   It prints `<Name>:page:<path>` REFs; `show` on one prints the page, capped
   at `--max-lines` unless `--full`.
5. Manage: `list` shows installed docsets and versions, `update [NAME]`
   refreshes one or all, `remove NAME` deletes one (notes are kept).
6. Scope: a project `"docsets"` list in `.dash-docset.json` limits searches to
   those docsets. Without one, searches cover every docset unless more than 4
   are full-size; then narrow with `-d NAME` (repeatable), set the list, or
   pass `--all`.

## Notes

Keep durable lessons (gotchas, project conventions) in the docset's notes
file. Find it with `notes DOCSET --path` (not created until you write it),
and edit it with normal file tools. Format: a `## General` section, plus
`## <entry name>` sections (optional ` (Type)` suffix to disambiguate). `show`
appends General and the matching section, so many small sections are cheap
and one big one is not.

Run `notes DOCSET --check` after editing: it warns about oversized notes and
headings that match no entry. On a size warning, suggest to the user turning
the heavy section into its own minimal skill built around the tasks it
covers.
