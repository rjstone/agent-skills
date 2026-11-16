---
name: docshelf
description: Use when you need exact, version-pinned API, library or tool reference offline from DevDocs documentation, or must search, install or annotate offline documentation instead of guessing from memory.
compatibility: Network access only for sources, install and update; Python sqlite3 built with FTS5 for full-text search.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
  credits: "DevDocs, devdocs-mcp, Zeal"
---

# docshelf

Look up DevDocs documentation offline with `python scripts/docshelf.py`
(stdlib only; the path is relative to this skill's folder). Stay in the
project folder and give the script's full path; don't `cd` to the skill
folder, because a project's `.docshelf.json` is found from the current
folder. Run its `--help` first: that is the command reference, with the
usual command lines. A subcommand's own `--help` only adds the rarer options
that `--help` names at its end. This file covers what help can't. If
`docshelf` MCP tools (`mcp__docshelf__search` and so on) are available,
use them instead of the script.

A docvol is a DevDocs documentation plus docshelf's own metadata, indexes
and notes.

Use for exact, version-pinned reference (signatures, options, return values)
quoted from the docs. Prefer Context7 or web search when the library has no
docvol or you need the very latest release, and a per-library skill when one
covers the task. Docvols can be stale: `list` shows versions.

The documentation comes from DevDocs (https://devdocs.io); docshelf is not
affiliated with DevDocs, and each documentation keeps its own licence:
the table on https://devdocs.io/about lists each one's sources and
licence.

## Read when needed

- A needed docvol is missing, or before `sources`, `install`, `update` or
  `remove`, or on exit 7 (network):
  [references/getting-docvols.md](references/getting-docvols.md). `sources`,
  `install` and `update` use the network; lookups do not.
- Before writing notes: [references/notes.md](references/notes.md).
- Registering docshelf as an MCP server: [references/mcp.md](references/mcp.md).

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
  rerun without `--grep` or to pipe the section through `grep`. REF is the
  `<docvol>:<path>[#anchor]` that `search` and `fts` print.
- Scope: a project `"docvols"` list in `.docshelf.json` limits searches to
  those docvols. Without one, searches cover every installed docvol unless
  more than 4 are full-size; then (exit 4) narrow with `-d NAME`, set the
  list, or pass `--all`. The first `fts` on a docvol builds its index
  (seconds for large docvols); `index-text DOCVOL` builds it ahead.

## Credits

- [DevDocs](https://devdocs.io): the documentation data. DevDocs was
  created by Thibaut Courouble and is operated by freeCodeCamp. See details
  including other contributors and supporters on the
  [About Page](https://devdocs.io/about).
- [devdocs-mcp](https://github.com/maxwhipw/devdocs-mcp): prior work.
- [Zeal](https://github.com/zealdocs/zeal): docset format information.
