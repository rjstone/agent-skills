---
name: opencode-api
description: Use when calling or scripting the opencode server's HTTP API - sessions, prompts, messages, the event stream, PTYs and shells, files, MCP, config, permissions, worktrees, integrations - with curl, opencode api or another HTTP client, when reading the server's OpenAPI spec, or when unsure whether an opencode endpoint is v1 (/session, /event, /global/...) or v2 (/api/...).
compatibility: Refreshing references/openapi.json (scripts/refresh_references.py) needs network access to opencode.ai; calls need a running opencode server.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# opencode server API (v2)

## Overview

opencode v2 moved every server route under `/api/` (`POST /api/session`,
`GET /api/event`, `GET /api/info`), so the v1 routes you remember (`/session`,
`/event`, `/global/health`, `/doc`) are probably wrong. **Do not write opencode
API calls from memory.** Look each one up in the cached OpenAPI spec,
`references/openapi.json` (~880 KB, 170 operations): search it with the script
instead of reading it.

```bash
python scripts/api_lookup.py --tags                  # areas and operation counts
python scripts/api_lookup.py --list session          # operations in a tag (or matching text)
python scripts/api_lookup.py --op session.prompt     # params, body, responses, how to call
python scripts/api_lookup.py --op POST /api/session  # same, by method and path
python scripts/api_lookup.py --schema Session        # one schema
python scripts/api_lookup.py --grep "fork session"   # words in ids, paths, summaries
```

Paths are relative to this skill's folder. `--depth N` limits how far `$ref`s
expand (default 3; use 1 for large bodies). When the spec and `ERRATA.md`
disagree, `ERRATA.md` wins.

## Calling the server

- **Easiest:** `opencode api <operationId>` (or `opencode api GET /api/...`)
  talks to the running server with its connection and password already set:
  `opencode api session.list --param limit=10`,
  `opencode api session.create --data '{"title": "x"}'`. `--op` prints this
  form for each operation.
- **Other clients:** HTTP Basic auth, user `opencode`, the server password
  (`OPENCODE_PASSWORD`, or set it with `opencode service set password`):
  `curl -u opencode:$OPENCODE_PASSWORD http://127.0.0.1:<port>/api/info`.
  `opencode service status` prints the address. Never print or log the
  password. Details: https://opencode.ai/docs/cli/web (Markdown: same URL + `.md`).
- `GET /api/info` (`server.info`) returns the version, URLs and paths: a
  cheap first call to check the connection.
- The running server does not serve its own spec (no route for it; v1's
  `/doc` is gone, checked 2026-11-08). The published copy is
  https://opencode.ai/docs/openapi.json, cached here.
- Events: `GET /api/event` (`event.subscribe`) is a `text/event-stream`;
  filter with the `types` query parameter. It is volatile: a slow reader is
  dropped, and events during a disconnect are lost.

## Keeping it current

- `references/openapi.json` is a verbatim copy; **never edit it**. Refresh with
  `python scripts/refresh_references.py` (`--check` reports staleness without
  writing). The docs page https://opencode.ai/docs/api/ is generated from the
  same file.
- Found a mistake (the spec contradicts the running server)? Add an entry to
  `ERRATA.md` with the request, the response and the date.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| v1 routes (`/session/{id}/message`, `/event`, `/global/health`) | Look up the v2 operation: `--grep`, then `--op` |
| Reading `openapi.json` directly | `api_lookup.py`; the file is far too large for context |
| curl without auth | `-u opencode:<password>`, or use `opencode api` |
| Guessing a request body | `--op <id>` shows the schema; `--schema <Name>` for nested types |
