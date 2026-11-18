---
name: docshelf
description: Use when you need exact, version-pinned API, library or tool reference offline from DevDocs documentation or Dash/Zeal docsets already on disk, or must search, install or annotate offline documentation instead of guessing from memory.
compatibility: Network access only for sources, install and update; Python sqlite3 built with FTS5 for full-text search.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.7.3"
  credits: "DevDocs, devdocs-mcp, Zeal"
---

# docshelf

Look up DevDocs documentation and Dash/Zeal docsets offline with
`python scripts/docshelf.py` (stdlib only; the path is relative to this
skill's folder). Stay in the
project folder and give the script's full path; don't `cd` to the skill
folder, because a project's `.docshelf.json` is found from the current
folder. Run its `--help` first: that is the command reference, with the
usual command lines. A subcommand's own `--help` only adds the rarer options
that `--help` names at its end. This file covers what help can't. If
`docshelf` MCP tools (`mcp__docshelf__search` and so on) are available,
use them instead of the script.

A docvol is a DevDocs documentation, or a Dash/Zeal docset found on disk
(read-only), plus docshelf's own metadata, indexes and notes.

Use for exact, version-pinned reference (signatures, options, return values)
quoted from the docs. A `## Documentation lookups` section in AGENTS.md or
CLAUDE.md takes precedence over what follows. Default when none exists:
prefer Context7 or web search when the library has no docvol or you need
the very latest release, and a per-library skill when one covers the task.
Docvols can be stale: `list` shows versions.

## First lookup in a project

Do these before the first lookup, once per project:

1. No AGENTS.md or CLAUDE.md you can see (project or user) has a
   `## Documentation lookups` section: read
   [references/lookup-defaults.md](references/lookup-defaults.md) now and
   follow it. It asks the user once and records the answer.
2. No `"docvols"` list in a `.docshelf.json`: run `suggest` (not `list`)
   and show the user its `"docvols"` line, offering to add it to
   `.docshelf.json` (if you can't ask now, put the offer in your reply).

The documentation comes from DevDocs (https://devdocs.io); docshelf is not
affiliated with DevDocs, and each documentation keeps its own licence:
the table on https://devdocs.io/about lists each one's sources and
licence.

## Policy for docsets

1. If an MCP server that reads Dash docsets (such as Kapeli's Dash MCP
   server) is configured and works, prefer it.
2. Otherwise use docshelf for docsets already on disk.
3. docshelf never installs a docset. If the needed one isn't on disk but
   Dash or Zeal looks installed, tell the user (wording in
   [references/dash-zeal.md](references/dash-zeal.md)) and ask how to proceed.
4. Don't download documentation that is on disk in another format; use
   `install --force` only when the user explicitly asks.
5. Narrow every search: `-d FAMILY` (or an exact name) or a project
   `"docvols"` list.
6. With several versions installed, pick the one the project uses. When
   `list` shows "also as" (DevDocs copy and docset of one documentation),
   ask the user whether to remove the DevDocs copy. Never remove a docset:
   Dash or Zeal manages it.

Kapeli's docsets are for personal use or use with Dash or Zeal, not other
applications without Kapeli's permission. If the use looks non-personal,
point the user to the terms in the README of https://github.com/Kapeli/feeds.
User-contributed docsets carry their own licences.

## Read when needed

- Docsets, their folders, REF forms or the message for step 3:
  [references/dash-zeal.md](references/dash-zeal.md).
- A needed docvol is missing, or before `sources`, `install`, `update` or
  `remove`, or on exit 7 (network, or an unreadable docset archive):
  [references/getting-docvols.md](references/getting-docvols.md). `sources`,
  `install` and `update` use the network; lookups do not.
- Before writing notes: [references/notes.md](references/notes.md).
- Registering docshelf as an MCP server: [references/mcp.md](references/mcp.md).

## Looking things up

- Try `search` first; use `fts` when names don't match. When no entry name
  is an exact match, `search` also lists headings inside pages, marked
  `(heading)` (DuckDB's functions are headings, not entries). Function options,
  parameters and settings are often only in page text (`read_csv`'s `skip`
  is a row in a table), so look for them with `fts`, adding the function
  name (`fts read_csv skip`, not `fts skip`).
- Hits below a "fuzzy matches" line only share letters in order; treat them
  as misses. Entries that open the same section are listed once.
- For one option or row of a long section, `show REF --grep=TEXT` prints
  every matching line, and a matching parameter name comes with its
  description; `...` marks lines without a match, so there's no need to
  rerun without `--grep` or to pipe the section through `grep`. REF is the
  `<docvol>:<path>[#anchor]` that `search` and `fts` print.
- `toc REF` prints a page's headings with their REFs: use it before
  reading a long page, then `show` the section. `show` says where it cut
  a long page; `show REF --offset N` continues from there. `types -d NAME`
  lists a docvol's entry types (the names `search --type` takes).
- Notes: write a lesson with `notes NAME --set HEADING --text TEXT` (or
  `--delete HEADING`); see [references/notes.md](references/notes.md).
- Scope: a project `"docvols"` list in `.docshelf.json` limits searches to
  those docvols. No list: run `suggest` and offer its list to the user;
  until one is set, searches cover every installed docvol unless more
  than 4 are full-size; then (exit 4) narrow with `-d NAME`, set the
  list, or pass `--all`. The first `fts` on a docvol builds its index
  (seconds for large docvols); `index-text DOCVOL` builds it ahead.

## Credits

- [DevDocs](https://devdocs.io): the documentation data. DevDocs was
  created by Thibaut Courouble and is operated by freeCodeCamp. See details
  including other contributors and supporters on the
  [About Page](https://devdocs.io/about).
- [devdocs-mcp](https://github.com/maxwhipw/devdocs-mcp): prior work.
- [Zeal](https://github.com/zealdocs/zeal): docset format information.
