# dash-docset skill: design

> **Later changes:** see `../plans/2026-11-14-dash-docset-after-plan.md`. It records the rulings made while executing
> the plan and every change since, and lists what below no longer holds.

Status: approved by the user (2026-11-14).

## Intent

Agents often hit friction looking up API docs: the library isn't in
Context7, no skill covers it, or the web is slow, costly or unreachable.
The user's habit so far is a hand-built skill per library (cached docs plus
notes). `dash-docset` is the general version: any of the hundreds of
existing Dash docsets is one install away, and lookups are local, fast,
cheap and offline. It adds an option; it replaces neither Context7 nor
per-library skills.

Success: an agent stuck on an API detail runs one or two commands and gets
the relevant part of the real docs as compact text, cheaper than a web
search.

Prior art: `sunaku/dasht` (bash + sqlite3 + wget + w3m, plus a web server).
We keep its ideas, not its code or its web server.

## Goals (first version)

- Choose where docsets live, with the user, once per machine or project.
- `sources` / `install` / `update` / `list` / `remove` docsets from Kapeli's
  official feeds, user-contributed docsets and cheat sheets.
- `search` entry names in the docsets' own index: exact, then prefix, then
  fuzzy (dasht's `%a%b%c%`).
- `show` an entry: its page converted to plain text and trimmed to the
  entry's anchor, small enough to read into context.
- Full-text search over page text with SQLite FTS5, index built on demand
  per docset.
- One Markdown notes file per docset, shown with matching results, with a
  size check.

## Non-goals (first version)

Tracked in `TODO.md`: semantic search (embeddings), MCP server mode.
Not planned: dasht's web server; rendering HTML for humans; building
docsets from source docs; non-Dash formats (DevDocs etc.).

## Anti-goals

- Output that floods context (whole pages, raw HTML) by default.
- Any install step or third-party dependency.
- Losing the user's notes on update or reinstall.
- Silently choosing a storage location the user didn't agree to.

## Constraints

- This repo's rules (`AGENTS.md`): stdlib only, public-safe, frontmatter
  standard, tests in `tests/test_dash_docset.py` with the `selected()`
  guard, no network in tests, paths relative to the skill.
- Must run on Linux, macOS and Windows, Python 3.9+ (`sqlite3` with FTS5;
  if FTS5 is missing, full-text search reports that and the rest works).
- Agent Skills spec: `SKILL.md` well under 500 lines / 5,000 tokens.

## Approaches

1. **Python, one stdlib script with subcommands** (chosen). `sqlite3`,
   `tarfile`, `urllib`, `plistlib`, `html.parser`, `json` cover everything.
2. Node.js: built-in SQLite only in recent Node versions (`node:sqlite`),
   so many machines would need an install step. Rejected for the
   no-dependency rule; harness TUIs being Node doesn't matter for a
   separately run script.
3. Python split into several modules: no gain at this size; one file is
   simplest to run and copy into every harness. Rejected.

## Design (as decided)

### Files

```
skills/dash-docset/
  SKILL.md            short: when to use, storage conversation, workflow,
                      notes rule; everything else is in --help
  scripts/docset.py   the CLI
tests/test_dash_docset.py   with a tiny fake docset built in the test
```

### Storage location

`SKILL.md` drives a short conversation the first time; the script only
resolves and reports. Resolution order:

1. `--dir <path>`
2. `DASH_DOCSET_DIR` environment variable
3. a project config file `.dash-docset.json` in the current directory or a
   parent (for docsets kept with a project)
4. a user config file (`$XDG_CONFIG_HOME/dash-docset/config.json`, i.e.
   `~/.config/...`; `%APPDATA%\dash-docset\config.json` on Windows)
5. none: the script exits with a message saying the location isn't set
   and listing existing docset folders it found, for the agent to put to
   the user.

`docset.py where` prints the resolved location and its source;
`docset.py where --discover` lists existing docset folders it can read:
dasht's (`$DASHT_DOCSETS_DIR`, `$XDG_DATA_HOME/dasht/docsets`), Zeal's
(`~/.local/share/Zeal/Zeal/docsets`, `%LOCALAPPDATA%\Zeal\Zeal\docsets`)
and Dash's on macOS (`~/Library/Application Support/Dash/DocSets`).
`docset.py where --set <path> [--project|--user]` writes the config.

The choices `SKILL.md` offers the user:
- also read docsets from existing folders found by `--discover` (dasht,
  Zeal, Dash), which saves re-downloading them; this adds those folders
  to the config's `"read_from"` list and still needs one of the store
  choices below for the script's own files;
- a new permanent central folder (default suggestion:
  `$XDG_DATA_HOME/dash-docset`, i.e. `~/.local/share/dash-docset`);
- the project the user is working in (`.docsets/` at its root; the script
  writes a `.gitignore` there that ignores docsets but keeps `notes/`, and
  `SKILL.md` warns that docsets are large);
- a temporary folder (lost on reboot; for one-off sessions and CI).

### Layout of a store

```
<store>/
  <Name>.docset/          as unpacked from the archive, never edited
  notes/<Name>.md         the user's notes, outside the docset
  .dash-docset/
    installed.json        name, source, version, archive URL, install date
    fts/<Name>.sqlite     full-text index, built on demand
    cache/                downloaded feed lists (with fetch time)
```

### Sources

- Kapeli official feeds: the XML feed files in `Kapeli/feeds` on GitHub;
  each lists a version and mirror URLs for a `.tgz`.
- User-contributed: `index.json` under
  `kapeli.com/feeds/zzz/user_contributed/build/`.
- Cheat sheets: Kapeli's cheat-sheet index under `kapeli.com/feeds/zzz/`.

Exact URLs and formats are checked against the live services while
building (see "Left to the builder"). Feed lists are cached; `sources
--refresh` re-fetches. `install` picks a mirror, downloads to a temp file,
checks it is a gzip tar, extracts safely (rejects absolute paths, `..` and
links leaving the target), then moves it into place.

### Commands (sketch; `--help` is the reference)

```
docset.py where [--discover] [--set PATH --project|--user]
docset.py sources [QUERY] [--refresh]
docset.py install NAME... | update [NAME...] | list | remove NAME
docset.py search QUERY [-d DOCSET]... [--type TYPE] [--limit N] [--json]
docset.py show REF [--full] [--max-lines N] [--no-notes]
docset.py fts QUERY [-d DOCSET]... [--limit N]   (builds index if missing)
docset.py index-text DOCSET...                    (build/rebuild FTS index)
docset.py notes DOCSET [--check | --path]
```

- `search` reads the docset's index: the `searchIndex` table (name, type,
  path), or the Core Data form (`ZTOKEN`, `ZTOKENMETAINFORMATION`,
  `ZFILEPATH`) some docsets use. Results: rank, docset, type, name, and a
  short REF that `show` accepts.
- `show` resolves the path (strips Dash's `<dash_entry_...>` markers,
  splits `#anchor`), converts HTML to text with headings, code blocks and
  lists kept, drops navigation/script/style, and trims to the section
  starting at the anchor up to the next heading of the same level. Default
  limit ~150 lines with a "truncated, use --full" note.
- `fts` searches page text with snippets and REFs; the index maps each
  page to the entries that point into it.
- Default output is plain text for agents; `--json` on search and fts.

### Notes

- One file per docset: `notes/<Name>.md`. A `## General` section and
  `## <entry name>` sections.
- `search` and `show` print the General section and any section whose
  heading matches the entry name, after the doc text, marked as notes.
- Size rule, run by `notes --check` and printed as a warning after
  `show` when exceeded: General > 50 lines, any one section > 100 lines,
  or total > 2,000 lines. The per-lookup cost is General plus one section,
  so many small sections are fine and one big one is not.
- `SKILL.md`: on a warning, suggest to the user turning the heavy section
  into its own minimal skill built around the tasks it covers. Agents
  edit notes with their normal file tools (`notes --path` prints where).

### Calls made after the builder check (Claude's calls, for the user to check)

- **Names.** A docset's name is its folder name without `.docset`; it
  keys the notes file, FTS index and `-d`. `install NAME` searches all
  sources; if a name exists in more than one, it stops and asks for a
  prefix (`kapeli:`, `user:`, `cheat:`). A store never holds two docsets
  with the same folder name.
- **Other apps' folders (the user, 2026-11-14).** The script never writes
  into a dasht, Zeal or Dash folder. Docsets found there through
  `"read_from"` are "foreign": searchable, showable and indexable, but
  `update` and `remove` refuse them. Their notes (`notes/<Name>.md`) and
  FTS indexes go in the script's own store, beside its own docsets, even
  though the docset itself lives elsewhere. If a store docset and a
  foreign one share a name, the store's wins and `list` shows the clash.
- **After update.** `installed.json` records the version each FTS index
  was built from; `fts` rebuilds a stale index automatically and says so.
  `notes --check` (and `update`) list note sections whose heading matches
  no entry any more.
- **Network.** Frontmatter gets `compatibility: network access to Kapeli
  feeds and GitHub for install/update; search works offline`. No live
  checks in CI; the builder verifies feeds by hand once and records them.
- **Heading match.** A `## ` heading matches an entry when equal after
  trimming and ignoring case; a trailing ` (Type)` in the heading limits
  it to that entry type.

### Search scope (the user, 2026-11-14)

Applies to `search` and `fts` when no `-d` is given.

- The project's `.dash-docset.json` may list `"docsets": [...]`; search
  uses that list.
- With no list, search uses all installed docsets, unless more than 4
  are "full size". Then it stops with an error listing them and pointing to
  `-d`, the project list, or `--all`. `--all` overrides.
- "Full size" (Claude's call): anything not from the cheat-sheet source,
  except a foreign docset whose index has fewer than 500 entries, which is
  treated as cheat-sheet sized.
- Output cap: `--max-lines N` on `search`, `fts` and `show`. Defaults
  (Claude's call): 40 for `search` and `fts`, 150 for `show`. Truncated
  output ends with a line saying how much was cut and how to see more.
  With `--all` the default is the same; results are ranked across
  docsets before the cap, so the best matches survive.

## Left to the builder

- Exact feed and mirror URLs and formats, verified live; record them in
  the script with a comment, and add the hosts to the `agent-skills`
  environment's allow list when needed.
- Fuzzy ranking details and the REF format.
- The HTML-to-text converter's rules beyond those above.
- FTS tokenizer choice (`unicode61` default or `porter`).
- How `update` compares versions per source.
- Test fixtures: build a small `.docset` in a temp dir in the test (both
  index forms, one HTML page with anchors), and feed files as fixtures.
