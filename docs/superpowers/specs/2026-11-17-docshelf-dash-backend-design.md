# docshelf: a read-only Dash/Zeal docset backend

Status: design, for review (2026-11-17). Skill: `skills/docshelf/`
(0.3.0 on `main`). Earlier design: `2026-11-16-docshelf-design.md`
("Backend interface", "Later: a second backend").

## Intent

docshelf reads DevDocs documentations it downloads itself. Many users
already have Dash (macOS) or Zeal (Linux, Windows, macOS) with docsets
downloaded. docshelf should read those docsets in place, so an agent can
look things up in them with the same commands and output as a DevDocs
docvol, without downloading the same documentation again from DevDocs
(TODO.md, the user, 2026-11-16).

The user runs this only on their own computer (the user, 2026-11-17), so
finding Dash's and Zeal's folders automatically comes first; cloud
sandboxes and CI, where no docsets exist, need nothing new.

## Agent policy (the user, 2026-11-17; goes into SKILL.md)

1. Check for an existing MCP server that reads Dash docsets (for example
   Kapeli's Dash MCP server). If one is configured and works, prefer it.
2. Otherwise use docshelf (the script or `--mcp`) for docsets that are
   already on disk.
3. docshelf never installs a docset. When the needed one isn't on disk but
   Dash or Zeal looks installed, tell the user, in substance: "It looks
   like you have <Dash/Zeal> installed and there's a docset called '...'
   for this, but I can't install it. If you install it, I can use it.
   Otherwise I'll download <the DevDocs alternative>." Then ask how to
   proceed.
4. Before downloading a DevDocs documentation, check `list` for a docset
   of the same documentation; if there is one, use it instead.
5. Always narrow searches to the subject: `-d FAMILY` (or an exact name)
   or a project `"docvols"` list, not unscoped searches (the user,
   2026-11-17).
6. When several versions of one documentation are installed, pick the
   one that fits the project. When `list` flags redundant documentation
   (a DevDocs docvol and a docset of the same documentation), warn the
   user and ask whether to remove the DevDocs copies. Never remove a
   docset: Dash or Zeal manages it (the user, 2026-11-17).

## Goals

- Docsets found on disk appear as docvols: `list`, `search`, `show`
  (with `--grep`), `fts`, `notes`, `where`, over the CLI and `--mcp`,
  with the same output conventions as DevDocs docvols.
- Equivalent search: entry names, the in-page heading fallback, and FTS5
  full-text search built on first use, as for DevDocs.
- `where` reports the docset folders found and whether Dash or Zeal is
  installed.
- `sources QUERY` also lists docsets that Dash or Zeal can download, from
  their catalogs, marked as "download in Dash or Zeal", and marks ones
  already on disk. This gives the agent the exact name for the message
  in policy step 3.

## Non-goals

- Downloading, updating or removing docsets. `install`, `update` and
  `remove` refuse a docset and say Dash or Zeal manages it.
- Any contact with kapeli.com (Kapeli asked for no extra load; every
  docset archive is served from there).
- Using a docset's own full-text index, or the `Info.plist`
  full-text-search flags (stays in TODO.md, low priority).
- Cloud-sandbox setup (copying docsets in). A folder given in
  `DOCSHELF_DOCSET_DIRS` works anywhere, but nothing is documented or
  tested for sandboxes beyond that.

## Anti-goals

- Writing anything into a Dash, Zeal or other docset folder. All derived
  files (indexes, caches) go under docshelf's cache.
- Slower DevDocs lookups because docsets exist: discovery must be cheap
  (no page reads; entry counts are read only when needed).
- Breaking anything about DevDocs docvols: names, REFs, notes and
  caches stay as they are.

## Constraints

- Stdlib only, Python 3.9+, as now (`sqlite3`, `plistlib`, `zlib`,
  `tarfile`, `configparser`, `winreg` on Windows).
- Kapeli's terms (README of github.com/Kapeli/feeds): its docsets are for
  personal use or with Dash or Zeal, and not in other applications without
  Kapeli's permission. SKILL.md says so; if the use looks non-personal,
  the agent points the user to those terms. User-contributed docsets carry
  their own licences.
- Network: only `sources` uses it for docsets: api.github.com (Kapeli/feeds
  and Kapeli/Dash-User-Contributions listings) and api.zealdocs.org (Zeal's
  catalog, fallback). Both go into `assets/allowlist.txt`. Lookups stay
  offline.
- Public repo rules (AGENTS.md): no account names or real home paths in
  code, tests or docs.

## Approaches

- **A. Full backend with catalogs (chosen by the user, 2026-11-17).** A
  `shelf_dash.py` backend beside `shelf_devdocs.py`, plus Dash/Zeal
  catalogs in `sources`, so the agent can name a docset exactly.
- B. Full backend, no catalogs: smaller, no new hosts, but the agent would
  name a Dash docset from memory and could get it wrong. Rejected.
- C. Revive `dash-docset` as a separate skill and point to it: two
  interfaces and a duplicate front end, against the one-skill design.
  Rejected.

## Design (as decided)

### Source of the code

Port from `skill/dash-docset` (same author, MIT; a backup is in the
author's experiments repo under the same branch name), adapting to
docshelf's modules rather than copying the single-file layout:

- discovery: `discover()`, `viewer_apps()`, `_zeal_custom_paths()`,
  `_docset_dirs()` (Zeal default and custom folders on Linux, macOS,
  Windows, Flatpak and portable installs; Dash's
  `~/Library/Application Support/Dash/DocSets`; dasht's folder);
- the index: `docSet.dsidx` in both forms (`searchIndex`, and Dash's Core
  Data `ZTOKEN` tables), `count_entries()`, `iter_entries()`;
- pages: `entry_location()` (drops `<dash_entry_...>` markers, decodes the
  file part), `page_file()` (stays inside `Documents/`), and tarix
  archives (`read_tarix()`: Dash's `tarix.tgz` + `tarixIndex.db`);
- the repeated-footer detection (`detect_footer()` and its cache): exact
  trailing blocks shared by at least 60% of up to 40 sampled pages are
  left out of `show`, `fts` and the headings index on every page but one;
- catalogs for `sources`: Kapeli/feeds root listing (official names),
  Kapeli/Dash-User-Contributions listing, Zeal's catalog as fallback,
  cached for a week.

### Backend interface preparation (first, as its own step)

The TODO.md items, done before the Dash backend so both backends use them:

- `display_name` on the `Docvol` base;
- one aggregator of installed docvols across backends (used everywhere
  `shelf_devdocs.installed_docvols(cfg)` is called today);
- a backend hook for resolving a link `href` on a page to a REF (today
  `resolve_doc_path` in `shelf_lookup`);
- `shelf_lookup` no longer imports `_warn` from the DevDocs backend.

### Docsets as docvols

- **Name:** the folder name without `.docset` (`Python_3`, `NodeJS`), as
  dash-docset did. Two docsets with the same name in different folders:
  the first folder in discovery order wins, and `where` names the others.
- **REF:** an entry is `<Name>:<id>` (the index row id). A page or a
  heading inside one is `<Name>:page:<path>[#anchor]`. Both are what
  dash-docset printed.
- **Family** (shared notes file): the name lowercased, with a trailing
  version part (`_3`, `_3.12`, `-2`) removed, so `Python_3` shares
  `python.md` with DevDocs' `python~3.12`. My call: it lets notes follow
  the documentation, not the format; a wrong family only means a separate
  notes file.
- **Title:** `CFBundleName` from `Info.plist`; else the name.
- **Release:** the version Zeal records in the docset's `meta.json` when
  present; else empty.
- **Size class:** the existing entry-count threshold (500), as for DevDocs.
  Docsets count toward the unscoped-search limit like any docvol (the
  user, 2026-11-17).
- **Stamp:** size and mtime of `docSet.dsidx` and, when present,
  `tarix.tgz`, as dash-docset did, so derived files rebuild when Dash or
  Zeal updates the docset in place.
- **Derived files:** under the cache, `DOCSHELF_CACHE_DIR/docsets/<name>-<short
  hash of the docset path>/` (FTS index, headings, footer).
- **Pages:** the pages the index entries point to (as dash-docset did),
  for `fts`, the headings index and footer detection. My call: scanning
  every HTML file can mean tens of thousands of pages in large docsets.
  A `page:` REF or link to any other file under `Documents/` (or in the
  tarix index) still opens, by a direct existence check, so link
  resolution doesn't need the full page list.

### Scope and names across docvols (the user, 2026-11-17)

- Unscoped searches: unchanged rule for every docvol, DevDocs or docset:
  more than 4 full-size docvols in scope and no `-d`, project list or
  `--all` exits 4. With many docvols the message lists families with a
  count (`python (3), duckdb, love, ...`) instead of every name (my call:
  with dozens of docvols a flat list floods the output).
- A family name in `-d` or a project list selects every docvol of that
  family (DevDocs and docsets, all versions); an exact docvol name selects
  one. Today a family matching several docvols is an error; that changes
  for DevDocs too (`-d python` with `python~3.11` and `python~3.12`).
- When one search covers several docvols of the same family, the output
  starts with one note line naming them and saying `-d NAME` picks one.
- Redundancy: a DevDocs docvol and a docset of the same family, with the
  same major.minor version or a docset version that is unknown, are
  flagged in `list` (`also as docset Python_3` / `also as DevDocs
  python~3.12`). My call on "same documentation": same family plus
  matching or unknown version.
- `remove` refuses docsets (see Commands).

### Where docsets are looked for

- The discovery folders above, every run.
- Plus `DOCSHELF_DOCSET_DIRS`: extra folders, separated by the OS path
  separator, searched first (they win name clashes). My call: one variable,
  like the other `DOCSHELF_*` settings; no config file.
- A docset that can't be opened is skipped with one warning line.

### Commands

- `list`: docsets appear with DevDocs docvols; each line says where a
  docvol comes from (`devdocs`, `dash`, `zeal`, or `folder` for
  `DOCSHELF_DOCSET_DIRS`).
- `where`: adds the docset folders searched (found or not) and the Dash or
  Zeal apps found.
- `sources QUERY`: DevDocs rows as now, then matching Dash/Zeal catalog
  names marked "(Dash/Zeal: download in the app)" and "(here as NAME)"
  when on disk. If a catalog can't be fetched, a note says which, and the
  DevDocs part still prints. The catalogs are fetched only when Dash or
  Zeal is installed or a docset folder exists (my call): elsewhere
  `sources` stays DevDocs-only and contacts no new host.
- `install`, `update`, `remove` on a docset name: exit 2 with "NAME is a
  Dash/Zeal docset; Dash or Zeal manages it".
- The "not installed" hint (0.3.0) also says, when a cached Dash/Zeal
  catalog has the name and an app is installed, that it can be downloaded
  in that app. Offline: cached catalogs only.

### Docs

- `SKILL.md`: the agent policy above (short), the Kapeli terms sentence,
  and a pointer to a new `references/dash-zeal.md` (discovery folders,
  `DOCSHELF_DOCSET_DIRS`, REF forms, read-only rule, the message for
  policy step 3, other docset MCP servers).
- `references/getting-docvols.md`: a docset is an alternative to
  `install` when one is on disk.
- `## Credits` already credits Zeal for the format.

### Testing

- Synthetic docsets built by the tests: a `searchIndex` docset, a `ZTOKEN`
  docset, a tarix docset, a docset with a repeated footer, discovery
  folders under a temporary `HOME` (Linux, macOS and Windows layouts,
  Flatpak, a Zeal custom path), catalog responses through the existing
  fake network.
- A real-data check with a docset the user uploads when the code is ready
  (the user, 2026-11-17).
- Version: minor bump to 0.4.0 (a feature, AGENTS.md).

## Left to the builder

- Module boundaries beyond `shelf_dash.py` (where the aggregator and the
  catalog code live), as long as `shelf_core` stays backend-free.
- How discovery caches entry counts within one run.
- Exact wording of messages and help lines, following the existing style.
- The order of the plan's tasks, after the interface preparation.
