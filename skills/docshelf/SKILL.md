---
name: docshelf
description: Use when you need exact, version-pinned API, library or tool reference offline from DevDocs documentation sets, or must search, install or annotate such docsets instead of guessing from memory.
compatibility: Network access only to install docsets; Python sqlite3 built with FTS5 for full-text search.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
  credits: "DevDocs, devdocs-mcp, Zeal"
---

# docshelf

Look up DevDocs documentation sets offline with `python scripts/docshelf.py`.
Run `python scripts/docshelf.py --help` for the commands and `where` to see
the cache, notes and project file in use.

Installing or updating docsets, or exit 7:
[references/getting-docsets.md](references/getting-docsets.md).

Before writing notes: [references/notes.md](references/notes.md).
