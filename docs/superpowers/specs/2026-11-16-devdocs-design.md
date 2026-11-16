# devdocs skill: design

Status: draft for the user's review (2026-11-16).

## Intent

Agents need exact, version-pinned API reference without guessing from
memory or paying for web searches. `dash-docset` (branch
`skill/dash-docset`, about to be archived) proved the approach in trials
with Haiku, Sonnet and about ten other models, but Dash docsets come with
sticky licensing (Kapeli's terms; his request that tools not download
from kapeli.com). DevDocs (https://devdocs.io, 844 docsets) publishes the
same kind of documentation as static JSON meant for offline use, with
milder terms. `devdocs` is dash-docset's trial-tuned interface on top of
DevDocs' data.

The fork `rjstone/devdocs-mcp` (TypeScript MCP server, MIT) showed the
DevDocs side: the endpoints, the cache layout and a fuzzy scorer. This
skill reuses its cache so both tools share installed docsets.

Success: an agent stuck on an API detail runs one or two commands and gets
the relevant lines of the real docs as compact text, cheaper than a web
search, with the same token figures dash-docset reached in its trials
(about 3-10k characters of script output per three-question task).

## Goals (first version)

- CLI first: `python scripts/devdocs.py`, stdlib only, used by coding
  agents that have a shell.
- The same command surface and output conventions as dash-docset
  (`--help` as the command reference, REFs, `show --grep`, fuzzy-hit
  marking, exit codes, notes), changed only where DevDocs differs.
- `sources` / `install` / `update` / `list` / `remove` DevDocs docsets.
- `search` entry names, `show` an entry's section, `fts` full-text search
  (SQLite FTS5, built on first use per docset).
- Per-docset notes, as in dash-docset.
- Secondary, built last: `devdocs.py --mcp` runs the same commands as a
  stdio MCP server, for harnesses without a shell or models that do
  better with tool schemas.

## Non-goals (first version)

- **Dash/Zeal backend** (in `TODO.md`, see "Later: a second backend"): no
  reading of locally installed Dash or Zeal docsets in v1, but the design
  must not make it hard.
- Fetching single pages on demand (`documents.devdocs.io/<slug>/<path>.html`
  works, but every lookup would need the network and load DevDocs).
- DevDocs' bundled archives (`downloads.devdocs.io/<slug>.tar.gz`): a
  third host, and they repeat `db.json`.
- Semantic search (dropped for dash-docset after its trials).
- MCP over HTTP, MCP resources or prompts; rendering HTML for humans.

## Anti-goals

- Output that floods context (whole pages, raw HTML) by default.
- Any install step or third-party dependency.
- Breaking devdocs-mcp's use of the shared cache: never rewrite its files
  in another format, never remove what it needs.
- Losing the user's notes on update, reinstall or cache cleanup.
- Load on DevDocs' servers beyond what its web app's offline mode does:
  no network on lookups; manifest cached 24 h; docsets downloaded only on
  `install` / `update`.

## Constraints

- This repo's rules (`AGENTS.md`): stdlib only, public-safe, the
  frontmatter standard, tests in `tests/test_devdocs.py` with the
  `selected()` guard, no network in tests, paths relative to the skill.
- Linux, macOS and Windows; Python 3.9+; `sqlite3` with FTS5 (without it,
  `fts` exits 2 and the rest works), as in dash-docset.
- Agent Skills spec: `SKILL.md` short (dash-docset's is about 60 lines).
- DevDocs' `COPYRIGHT` asks that generated documentation be attributed to
  DevDocs, and that the DevDocs name not be used to endorse or promote
  derived products without permission. Each docset also has its own
  `attribution` (licence) in the manifest.
- Network: `devdocs.io` (manifest; it 302-redirects and needs a
  User-Agent) and `documents.devdocs.io` (`index.json`, `db.json`).
  Listed in `assets/allowlist.txt`.

Facts checked 2026-11-16: 844 docsets, 667 with a version in the slug
(`python~3.14`, `pandas~2`); `db.json` from 0.7 MB (vite, 41 pages) to
281 MB (ansible); python~3.14 is 20 MB, 499 pages, and `json.load` of it
takes 0.35 s. Manifest fields: `name slug type version release mtime
db_size attribution alias links`. Index entries: `name path type`, with
`#anchor` in `path` for sub-entries; no ids. Pages contain
`<div hidden>` LLM hints; code blocks are `<pre data-language=...>`.

## Approaches

- **A. Fork dash-docset's front end, add a DevDocs backend** (chosen by the
  user, 2026-11-16: least duplicated effort). Keep its trial-tuned parts
  (help, REFs, scorer, renderer, `--grep`, FTS, notes, exit codes) behind
  a small backend interface; write the DevDocs backend now; the Dash
  reader comes back later as a second backend.
- B. Port devdocs-mcp to Python and add dash-docset's features: smaller
  start, but loses the trial fixes and needs a hand-written turndown.
  Rejected.
- C. Convert both formats into one common SQLite index at install:
  equal search by construction, but duplicates data, breaks the shared
  cache with devdocs-mcp, and needs rebuilds when Dash updates in place.
  Rejected.

**MCP vs CLI** (the user, 2026-11-16): the skill will mostly serve coding
agents that already need a shell, so the CLI is primary and `--mcp` is
added afterwards on the same command table.

## Design (as decided)

### Files

```
skills/devdocs/
  SKILL.md                  short; --help is the command reference
  assets/allowlist.txt      hosts for sandboxed networks
  references/               read-when-needed files, keyed to exit codes
  scripts/devdocs.py        entry point: CLI and --mcp
  scripts/<modules>.py      split by concern (front end, renderer,
                            DevDocs backend, MCP layer); the entry point
                            adds its own folder to sys.path
tests/test_devdocs.py       offline; fixtures built in the test or stored
                            small under tests/fixtures/devdocs/
```

Splitting into modules is a change from dash-docset's single file: with a
second backend and the MCP layer the script would pass 3k lines.

### Reuse from dash-docset

Taken from `skill/dash-docset` (same author, MIT, original to this repo),
adapted, not rewritten: the `--help` layout and wording style, REF
handling, the search scorer and its output (fuzzy line, multi-word best
hit per word, "(same section: ...)" collapsing), the HTML-to-text
renderer with section trimming and `--grep`, the FTS5 index and query
quoting, notes (`--path`, `--check`, size warnings), scope limiting (exit
4), and case-insensitive names. The trial notes in
`docs/superpowers/plans/2026-11-14-dash-docset-after-plan.md` explain why
each exists; keep the behaviour unless DevDocs makes it moot.

The branch head (`1058b98`) no longer has `install` / `update` (removed in
`2fb24ec` for Kapeli's sake). Install logic comes from devdocs-mcp
(`docsets.ts`, `manifest.ts`) and the after-plan notes, plus dash-docset's
earlier safe-download pattern (temp file, then move).

### Backend interface

The front end sees a docset only through:

- `name` (the REF prefix and `-d` name), display name, release, size
  class (for the scope rule), attribution;
- `entries()`: (name, type, locator) rows;
- `page(locator)`: HTML of the page plus the anchor to trim to;
- `pages()`: every (page key, HTML) for building the FTS index;
- `parse_ref(rest)` / `format_ref(locator)`: the backend owns the part of
  a REF after `<name>:`.

The DevDocs backend's locator is the entry path, so a REF is
`<slug>:<path>[#anchor]` (`vite:config/shared-options#define`). A later
Dash backend keeps dash-docset's `<Name>:<id>` / `<Name>:page:<path>`.

### Storage

- Cache: `DEVDOCS_CACHE_DIR`, else `~/.cache/devdocs-mcp/` (shared with
  devdocs-mcp; the user, 2026-11-16). Layout as devdocs-mcp writes it:
  `docs.json`, `<slug>/index.json`, `<slug>/db.json`, `<slug>/meta.json`
  (`{slug, name, release, mtime, installedAt}`).
- This skill's derived files go in `<slug>/.devdocs-skill/`: a page-offset
  index and `fts.sqlite`. They record the `db.json` size and mtime they
  were built from and are rebuilt when it changes (devdocs-mcp may update
  a docset). Docsets installed by devdocs-mcp work without reinstalling.
- Page access: a one-shot CLI can't `json.load` a 281 MB `db.json` per
  call. At install (or first use), record each page's byte span in
  `db.json`; `show` reads and decodes only that span.
- Notes live outside the cache, which is meant to be deletable:
  `DEVDOCS_NOTES_DIR`, else `$XDG_DATA_HOME/devdocs/notes/`
  (`~/.local/share/devdocs/notes/`), `%APPDATA%\devdocs\notes\` on
  Windows.
- Notes are keyed by docset family, the slug before `~`
  (`notes/python.md` serves `python~3.13` and `python~3.14`), so they
  survive an upgrade to a new release, and a later Dash docset for the
  same documentation can use the same file. `notes --check` checks
  headings against the installed release(s) of that family. (Claude's
  call, after the builder check.)
- Project scope: an optional `.devdocs.json` (current folder or a parent,
  found as dash-docset finds `.dash-docset.json`, including from the skill
  folder) with a `"docsets"` list limiting searches. No store
  conversation: the cache has a working default.

### Commands (sketch; `--help` is the reference)

```
devdocs.py search QUERY... [-d NAME]... [--type T] [--all] [--json]
devdocs.py show REF [--grep TEXT]... [--full] [--max-lines N] [--no-notes]
devdocs.py fts QUERY... [-d NAME]... [--all] [--json]
devdocs.py notes DOCSET (--path | --check)
devdocs.py sources QUERY... [--refresh]     catalog search; marks installed
devdocs.py install NAME... | update [NAME...] | list | remove NAME
devdocs.py index-text NAME...               build the FTS index now
devdocs.py where                            cache, notes dir, project file
devdocs.py --mcp                            stdio MCP server
```

- Names: slug, alias or display name, case-insensitive. A name without a
  version (`python`) means the one installed release; if several are
  installed, exit 2 listing them. For `install`, it means the newest
  release in the manifest, and the output says which slug was installed.
- `install` refuses slugs outside DevDocs' shape (devdocs-mcp's
  `assertSafeSlug` rule) and downloads to a temporary file before moving
  into place.
- Exit codes as dash-docset: 0 ok; 1 `notes --check` problems; 2 usage,
  unknown name or no FTS5; 4 scope too wide; 5 not found; 7 network. Exit
  3 (no store set) is unused and stays reserved.
- Relative links in pages become REFs, as devdocs-mcp's `rewriteHref`
  does, so an agent can `show` them directly.

### MCP mode (secondary)

- Same file: `devdocs.py --mcp` reads newline-delimited JSON-RPC on stdin
  (`initialize`, `notifications/initialized`, `tools/list`, `tools/call`,
  `ping`), stdlib only.
- One command table drives argparse and the tool schemas, so help text and
  tool descriptions can't drift. Tools: search, show, fts, list, sources,
  install, remove, notes. Multi-word queries are arrays.
- The MCP `notes` tool returns the notes text and the `--check` report;
  it doesn't write (an MCP-only agent may have no file tools, and writing
  user files over MCP needs its own guards). Writing notes over MCP is a
  later option. (Claude's call, after the builder check.)
- A tool result is exactly the CLI's output. Errors are `isError` results
  whose text includes the fix inline (an MCP-only agent can't open
  `references/`).
- Project scope: the server's working directory, plus an optional
  `docsets` argument.
- `references/mcp.md`: registration snippets for Claude Code, `mcpServers`
  JSON clients, Codex and opencode. `SKILL.md`: if `devdocs` MCP tools are
  present, use them instead of the script.

### Testing

- Unit tests offline, against a tiny fake docset in DevDocs' format
  (`index.json`, `db.json`, `meta.json`, `docs.json`), plus an MCP
  round-trip through a subprocess.
- Agent trials as dash-docset ran them (copy its
  `docs/superpowers/trials/` scripts): a no-skill baseline first, then
  the skill, Haiku plus the opencode model set, measuring answers and
  script output size. Later, the same prompts in CLI and MCP mode.

### Later: a second backend (`TODO.md`; the user, 2026-11-16)

dash-docset will be archived. Before that, bring its Dash/Zeal reader in
as a read-only backend for docsets the user already has from Dash or
Zeal. It downloads nothing; when an installed Dash docset covers the same
documentation as a DevDocs docset, it may be preferred over downloading
the DevDocs one. Same CLI and MCP interface, equivalent search and FTS.
v1 only has to keep the backend interface free of DevDocs assumptions.

## Left to the builder

- Module boundaries and names inside `scripts/`.
- The page-offset index format and how it's built (a scan of `db.json`
  with `json.JSONDecoder.raw_decode`, or another way), within the "never
  load the whole file per call" rule.
- How DevDocs-specific HTML (attribution footers, `hidden` divs, link
  rewriting) is handled in the shared renderer.
- MCP protocol version negotiation details.
- Trial questions and docsets.
