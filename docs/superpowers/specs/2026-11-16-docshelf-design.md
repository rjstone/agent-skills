# docshelf skill: design

> Terminology: after this was written, docshelf's unit was renamed from "docset" to "docvol" (the user, 2026-11-16); "docset" now means only a Dash/Zeal docset.

Status: approved by the user (2026-11-16, review on PR #7).

## Intent

Agents need exact, version-pinned API reference without guessing from
memory or paying for web searches. `dash-docset` (branch
`skill/dash-docset`, about to be archived) proved the approach in trials
with Haiku, Sonnet and about ten other models, but Dash docsets come with
sticky licensing (Kapeli's terms; his request that tools not download
from kapeli.com). DevDocs (https://devdocs.io, 844 docsets) publishes the
same kind of documentation as static JSON meant for offline use, with
milder terms. `docshelf` is dash-docset's trial-tuned interface on top of
DevDocs' data first, and later on more than one documentation format.

The TypeScript MCP server `devdocs-mcp` (MIT; the user's fork, now being
deleted) showed the DevDocs side: the endpoints, the cache layout and a
fuzzy scorer. Its ideas are reused; it is not kept alongside.

Success: an agent stuck on an API detail runs one or two commands and gets
the relevant lines of the real docs as compact text, cheaper than a web
search, near the token figures dash-docset reached in its trials (about
3-10k characters of script output per three-question task).

## Goals (first version)

- CLI first: `python scripts/docshelf.py`, stdlib only, for coding agents
  that have a shell.
- The same command surface and output conventions as dash-docset
  (`--help` as the command reference, REFs, `show --grep`, fuzzy-hit
  marking, exit codes, notes), changed only where DevDocs differs.
- `sources` / `install` / `update` / `list` / `remove` DevDocs docsets.
- `search` entry names, `show` an entry's section, `fts` full-text search
  (SQLite FTS5, built on first use per docset).
- Per-docset notes, as in dash-docset.
- Secondary, built last: `docshelf.py --mcp` runs the same commands as a
  stdio MCP server, for harnesses without a shell or models that do
  better with tool schemas.

## Non-goals (first version)

Tracked in `TODO.md`:
- **Dash/Zeal backend** (see "Later: a second backend"); v1 only keeps the
  door open.
- **Agent trials** (no-skill baseline, Haiku, the opencode model set,
  CLI vs MCP): fine-tuning after v1 (the user, 2026-11-16).
- Writing notes over MCP.

Not planned:
- Fetching single pages on demand (`documents.devdocs.io/<slug>/<path>.html`
  works, but every lookup would need the network and load DevDocs).
- DevDocs' bundled archives (`downloads.devdocs.io/<slug>.tar.gz`): a
  third host, and they repeat `db.json`.
- Semantic search (dropped for dash-docset after its trials).
- MCP over HTTP, MCP resources or prompts; rendering HTML for humans.
- Running next to devdocs-mcp: users pick one or the other (the user,
  2026-11-16).

## Anti-goals

- Output that floods context (whole pages, raw HTML) by default.
- Any install step or third-party dependency.
- Losing the user's notes on update, reinstall or cache cleanup.
- Load on DevDocs' servers beyond what its web app's offline mode does:
  no network on lookups; manifest cached 24 h; docsets downloaded only on
  `install` / `update`.
- Using the DevDocs name for the skill, its files or its MCP server
  (DevDocs' `COPYRIGHT`: the name isn't to be used to endorse or promote
  derived products without permission).

## Constraints

- This repo's rules (`AGENTS.md`): stdlib only, public-safe, the
  frontmatter standard, tests in `tests/test_docshelf.py` with the
  `selected()` guard, no network in tests, paths relative to the skill.
- Linux, macOS and Windows; Python 3.9+; `sqlite3` with FTS5 (without it,
  `fts` exits 2 and the rest works), as in dash-docset.
- Agent Skills spec: `SKILL.md` short (dash-docset's is about 60 lines).
- Attribution: DevDocs asks that documentation generated with it be
  attributed to DevDocs; each docset carries its own licence
  (`attribution` in the manifest). Covered by the skill's text and
  metadata, not by script output (the user, 2026-11-16); see "Name and
  attribution".
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
  equal search by construction, but duplicates data and needs rebuilds
  when Dash updates a docset in place. Rejected.

**MCP vs CLI** (the user, 2026-11-16): the skill will mostly serve coding
agents that already need a shell, so the CLI is primary and `--mcp` is
added afterwards on the same command table.

## Design (as decided)

### Name and attribution (the user, 2026-11-16)

- Name `docshelf`: neutral about the source and format, so it still fits
  with a Dash/Zeal backend. Used for the skill folder, `scripts/docshelf.py`,
  `.docshelf.json`, `DOCSHELF_*` variables, the cache and notes folders and
  the MCP server name.
- `SKILL.md` says the docs come from DevDocs (devdocs.io), that docshelf
  isn't affiliated with DevDocs, and that each docset keeps its own
  licence (`list` doesn't print it; the manifest has it). Frontmatter
  `metadata.credits: "DevDocs, devdocs-mcp, Zeal"` names them briefly; a
  `## Credits` section (allowed by `AGENTS.md`) credits, with links: DevDocs
  (https://devdocs.io) as the data source, devdocs-mcp
  (https://github.com/maxwhipw/devdocs-mcp, the upstream of the user's
  fork) as prior work, and Zeal (https://github.com/zealdocs/zeal) for the
  docset format information (the user, 2026-11-16, review on PR #7).
  dash-docset isn't named: it was never merged or released and will be
  archived (the user, 2026-11-16).

### Files

```
skills/docshelf/
  SKILL.md                  short; --help is the command reference
  assets/allowlist.txt      hosts for sandboxed networks
  references/               read-when-needed files, keyed to exit codes
                            (incl. mcp.md)
  scripts/docshelf.py       entry point: CLI and --mcp
  scripts/<modules>.py      split by concern (front end, renderer,
                            DevDocs backend, MCP layer); the entry point
                            adds its own folder to sys.path
tests/test_docshelf.py      offline; fixtures built in the test or stored
                            small under tests/fixtures/docshelf/
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
4), case-insensitive names, and finding the project file from the skill
folder. The trial notes in
`docs/superpowers/plans/2026-11-14-dash-docset-after-plan.md` explain why
each exists; keep the behaviour unless DevDocs makes it moot.

The branch head (`1058b98`) no longer has `install` / `update` (removed in
`2fb24ec` for Kapeli's sake). Install logic comes from devdocs-mcp
(`docsets.ts`, `manifest.ts`) and the after-plan notes, plus dash-docset's
earlier safe-download pattern (temp file, then move).

### Backend interface

The front end sees a docset only through:

- `name` (the REF prefix and `-d` name), family (for notes), display
  name, release, size class (for the scope rule);
- `entries()`: (name, type, locator) rows;
- `page(locator)`: HTML of the page plus the anchor to trim to;
- `pages()`: every (page key, HTML) for building the FTS index;
- `parse_ref(rest)` / `format_ref(locator)`: the backend owns the part of
  a REF after `<name>:`.

The DevDocs backend's locator is the entry path, so a REF is
`<slug>:<path>[#anchor]` (`vite:config/shared-options#define`). A later
Dash backend keeps dash-docset's `<Name>:<id>` / `<Name>:page:<path>`.

### Storage

- Cache: `DOCSHELF_CACHE_DIR`, else `~/.cache/docshelf/`
  (`%LOCALAPPDATA%\docshelf\cache\` on Windows). Per DevDocs docset, the
  layout devdocs-mcp used, so either tool can read the other's installs:
  `devdocs/docs.json` (manifest), `devdocs/<slug>/index.json`, `db.json`,
  `meta.json` (`{slug, name, release, mtime, installedAt}`). The
  `devdocs/` level leaves room for other backends' files.
- This skill's derived files go in `devdocs/<slug>/.docshelf/`: a
  page-offset index and `fts.sqlite`. They record the `db.json` size and
  mtime they were built from and are rebuilt when it changes.
- Page access: a one-shot CLI can't `json.load` a 281 MB `db.json` per
  call. At install (or first use), record each page's byte span in
  `db.json`; `show` reads and decodes only that span.
- Notes live outside the cache, which is meant to be deletable:
  `DOCSHELF_NOTES_DIR`, else `$XDG_DATA_HOME/docshelf/notes/`
  (`~/.local/share/docshelf/notes/`), `%APPDATA%\docshelf\notes\` on
  Windows.
- Notes are keyed by docset family, the slug before `~`
  (`notes/python.md` serves `python~3.13` and `python~3.14`), so they
  survive an upgrade to a new release, and a later Dash docset for the
  same documentation can use the same file. `notes --check` checks
  headings against the installed release(s) of that family. (Claude's
  call.)
- Project scope: an optional `.docshelf.json` (current folder or a parent,
  found as dash-docset finds `.dash-docset.json`, including from the skill
  folder) with a `"docsets"` list limiting searches. No store
  conversation: the cache has a working default.

### Commands (sketch; `--help` is the reference)

```
docshelf.py search QUERY... [-d NAME]... [--type T] [--all] [--json]
docshelf.py show REF [--grep TEXT]... [--full] [--max-lines N] [--no-notes]
docshelf.py fts QUERY... [-d NAME]... [--all] [--json]
docshelf.py notes DOCSET (--path | --check)
docshelf.py sources QUERY... [--refresh]    catalog search; marks installed
docshelf.py install NAME... | update [NAME...] | list | remove NAME
docshelf.py index-text NAME...              build the FTS index now
docshelf.py where                           cache, notes dir, project file
docshelf.py --mcp                           stdio MCP server
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

### MCP mode (secondary, built last)

- Same file: `docshelf.py --mcp` reads newline-delimited JSON-RPC on
  stdin (`initialize`, `notifications/initialized`, `tools/list`,
  `tools/call`, `ping`), stdlib only.
- Server name `docshelf`, so tools appear as `mcp__docshelf__search` and
  so on, distinct from devdocs-mcp's `devdocs` prefix. Tool names may
  match devdocs-mcp's where the job matches (the user, 2026-11-16).
- One command table drives argparse and the tool schemas, so help text and
  tool descriptions can't drift. Tools: search, show, fts, list, sources,
  install, remove, notes. Multi-word queries are arrays.
- The `notes` tool returns the notes text and the `--check` report; it
  doesn't write (an MCP-only agent may have no file tools, and writing
  user files over MCP needs its own guards). (Claude's call.)
- A tool result is exactly the CLI's output. Errors are `isError` results
  whose text includes the fix inline (an MCP-only agent can't open
  `references/`).
- Project scope: the server's working directory, plus an optional
  `docsets` argument.
- `references/mcp.md`: registration snippets for Claude Code, `mcpServers`
  JSON clients, Codex and opencode. `SKILL.md`: if `docshelf` MCP tools
  are present, use them instead of the script.

### Testing (v1)

- Unit tests offline, against a tiny fake docset in DevDocs' format
  (`index.json`, `db.json`, `meta.json`, `docs.json`), plus an MCP
  round-trip through a subprocess.
- One manual live check before review: install a small and a mid-size
  docset (vite, python~3.14) and look up a few entries. Agent trials are
  later work (see Non-goals).

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
- How DevDocs-specific HTML (`hidden` divs, link rewriting) is handled in
  the shared renderer.
- MCP protocol version negotiation details.
