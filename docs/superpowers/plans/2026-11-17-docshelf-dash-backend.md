# docshelf Dash/Zeal Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** docshelf reads Dash and Zeal docsets already on disk as read-only docvols, with the same commands, output and MCP tools as DevDocs docvols.

**Architecture:** First generalize the backend interface (one aggregator of installed docvols, `page_blocks`, link resolution and provenance on the `Docvol` base) and the scope rules (family names select every docvol of a family). Then add `shelf_dash.py`: docset reading (both index forms, tarix), discovery (Zeal, Dash on macOS and Windows, `DOCSHELF_DOCSET_DIRS`), footer stripping, and the Dash/Zeal catalogs for `sources`. Finally the read-only and redundancy rules for `install`/`update`/`remove`/`list`, and the docs.

**Tech Stack:** Python 3.9+ stdlib only (`sqlite3`, `plistlib`, `zlib`, `tarfile`, `configparser`, `winreg` on Windows); `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-17-docshelf-dash-backend-design.md`. Code to port: branch `skill/dash-docset`, `skills/dash-docset/scripts/docset.py` (in this repo until the branch is deleted, and in the author's experiments repo). Function names below in `old:` refer to that file.

## Global Constraints

- Stdlib only; Python 3.9+; no install step (AGENTS.md "Dependencies").
- Never write into a Dash, Zeal or other docset folder; derived files go under `DOCSHELF_CACHE_DIR/docsets/<name>-<8 hex of sha1(abs docset path)>/`.
- Never contact kapeli.com. Network only in `sources`: api.github.com and api.zealdocs.org, and only when Dash or Zeal is installed or a docset folder exists.
- Lookups (`search`, `show`, `fts`, `notes`, `list`, `where`) never use the network.
- `shelf_core` imports no backend module.
- No account names, real home paths or drive-letter paths in code, tests or docs (AGENTS.md "Paths"); fixture paths live under temporary folders.
- REFs: a docset entry is `<Name>:<id>`; a page or heading is `<Name>:page:<path>[#anchor]`. DevDocs REFs unchanged.
- Unscoped-search limit unchanged: more than `MAX_FULL_UNSCOPED` (4) full-size docvols in scope exits 4; full-size is `entry_count >= 500` for docsets too.
- Version: `metadata.version` and `shelf_core.VERSION` become `"0.4.0"` (minor: feature). Tests read `shelf_core.VERSION`, never a literal.
- Every PR fills `.github/pull_request_template.md`.

## Review Focus

1. A docset whose `docSet.dsidx` is missing, locked or corrupt: skipped with one `warning:` line; every other command still works. (Task 3)
2. Index rows whose path is a URL (`http://...`, Dash's online entries) or empty: not entries, never a page; `fts` and headings ignore them. (Task 3)
3. The same docset name in two discovery folders (Zeal and Dash both on macOS; `DOCSHELF_DOCSET_DIRS` overlapping a default folder): one docvol, the first folder wins, `where` names the other. (Task 5)
4. Entry paths with percent-encoding, `<dash_entry_...>` markers and backslashes: `show` opens the page; a path escaping `Documents/` (`../`) is refused with exit 5. (Task 3)
5. `-d python` with three python docvols and no others: searches all three and prints the same-family note once; with `--json` the note goes to stderr so stdout stays valid JSON. (Task 2)

---

### Task 1: Backend interface preparation

Removes every direct `shelf_devdocs.installed_docvols` use outside the backend, moves link resolution and page rendering behind the `Docvol` base, and gives docvols a provenance. Behavior is unchanged; the existing 291 tests are the main check.

**Files:**
- Create: `skills/docshelf/scripts/shelf_backends.py`
- Modify: `skills/docshelf/scripts/shelf_core.py`, `shelf_devdocs.py`, `shelf_lookup.py`, `shelf_notes.py`, `shelf_cli.py`, `shelf_mcp.py`
- Test: `tests/test_docshelf.py` (new class `BackendInterfaceTests`)

**Interfaces:**
- Produces:
  - `shelf_core.warn(msg: str) -> None` (prints `warning: <msg>` to stderr; `shelf_devdocs._warn` becomes an alias of it, and `shelf_lookup` imports `warn` from `shelf_core`).
  - On `shelf_core.Docvol`: `display_name: str` (default: `title`), `source: str` (`"devdocs"`, `"dash"`, `"zeal"`, `"folder"`), `read_only: bool` (default `False`), `version: str` (default `""`; DevDocs sets it from the slug or meta, as its title does).
  - `Docvol.page_blocks(self, page: str, link=None) -> List[Block]`: default `html_to_text(self.page_html(page), link=link)`. Every `html_to_text(ds.page_html(...))` call in `shelf_lookup` and `shelf_notes` uses it instead.
  - `Docvol.resolve_href(self, page: str, href: str) -> Optional[str]`: the REF a link on `page` points to, or `None`. Default: `resolve_doc_path` (moved to `shelf_core`) plus membership in `self.pages()`, cached per docvol. `cmd_show` calls it.
  - `shelf_backends.installed_docvols(cfg: Config) -> List[Docvol]`: DevDocs docvols (this task), docsets added in Task 5. All former call sites in `shelf_cli`, `shelf_lookup`, `shelf_notes`, `shelf_mcp` and `shelf_devdocs.not_installed_message` callers use it. `shelf_devdocs.installed_docvols` stays as the DevDocs part.

- [ ] **Step 1: Write the failing tests** in `BackendInterfaceTests`:
  - `test_commands_use_the_backend_aggregator`: patch `shelf_backends.installed_docvols` to return one in-memory `Docvol` subclass (`name="fake"`, one entry `f` on page `p`, `page_html` returns `<h1 id='f'>f</h1><p>body</p>`); in-process `main` for `list`, `search f -d fake`, `show fake:p`: each exits 0 and prints `fake`, `fake:p#f`, `body`.
  - `test_show_link_uses_resolve_href`: the fake overrides `resolve_href` to return `"fake:other"`; `show fake:p` on a page with `<a href='x'>x</a>` prints `[fake:other]`.
  - `test_page_blocks_is_used_by_fts_and_headings`: the fake overrides `page_blocks` to drop a block with text `DROPME`; `fts DROPME -d fake` finds nothing and `notes fake --check` lists no `DROPME` heading.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_docshelf.BackendInterfaceTests -v`. Expected: FAIL (`shelf_backends` missing).
- [ ] **Step 3: Implement** the Interfaces above. `DevDocsDocvol` sets `source = "devdocs"` and `version`; `resolve_doc_path` moves from `shelf_lookup` to `shelf_core` (keep the name).
- [ ] **Step 4: Run** `python3 -m unittest discover -s tests`. Expected: all pass (291 + 3).
- [ ] **Step 5: Commit** `docshelf: backend aggregator, page_blocks, resolve_href, provenance on Docvol`.

### Task 2: Family names select every docvol of the family

**Files:**
- Modify: `skills/docshelf/scripts/shelf_core.py` (`select_docvols`, scope error), `shelf_lookup.py` (`cmd_search`, `cmd_fts` print the note), `shelf_cli.py` (help line for `-d`)
- Test: `tests/test_docshelf.py` (new class `FamilyScopeTests`)

**Interfaces:**
- Consumes: Task 1 `installed_docvols`.
- Produces:
  - `select_docvols(cfg, all_docvols, names, use_all) -> List[Docvol]`: for each name: an exact docvol name (case-insensitive) selects that one; else a family name selects every docvol whose `family` equals it (case-insensitive); else `pick_docvol`'s existing alias/title steps and errors. Order: as `all_docvols`; no duplicates.
  - `shelf_core.same_family_note(docs: List[Docvol]) -> Optional[str]`: for the first family with two or more docvols in `docs`: `note: searching N docvols of FAMILY (a, b, ...); -d NAME picks one`; `None` otherwise.
  - The exit-4 scope message lists families as `family (count)` when a family has more than one docvol, sorted by family, instead of every name.
  - `pick_docvol` is unchanged (single selection for `show` REFs, `notes`, `remove`, `update`).

- [ ] **Step 1: Write the failing tests:**
  - `test_family_selects_all_versions`: DevDocs fixtures `python~3.11`, `python~3.12`, `lua~5.4`; `search x -d python` lists hits from both python docvols, exit 0; stdout's first line is `note: searching 2 docvols of python (python~3.11, python~3.12); -d NAME picks one`.
  - `test_exact_name_selects_one`: `search x -d python~3.12` has no note and no `python~3.11` hits.
  - `test_json_note_goes_to_stderr`: `search x -d python --json`: stdout parses as JSON; stderr contains the note.
  - `test_project_list_family`: `.docshelf.json` `{"docvols": ["python"]}` and no `-d`: both python docvols searched.
  - `test_scope_error_lists_families`: five full-size fixtures `a~1`, `a~2`, `b`, `c`, `d` (500 entries each); `search x` exits 4 and stderr contains `a (2), b, c, d`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_docshelf.FamilyScopeTests -v`. Expected: FAIL (`-d python` exits 2 "matches ... give one").
- [ ] **Step 3: Implement** the Interfaces. The note prints to stdout (text) or stderr (`--json`) before any hits, in `search` and `fts`.
- [ ] **Step 4: Run** the full suite. Expected: all pass; update any existing test that asserted the old "matches ... give one" error for `-d` (keep it for `show` and `remove`).
- [ ] **Step 5: Commit** `docshelf: a family name in -d or the project list selects all its docvols`.

### Task 3: Docset reader (index, pages, REFs)

**Files:**
- Create: `skills/docshelf/scripts/shelf_dash.py`
- Test: `tests/test_docshelf.py` (helper `make_docset`, class `DashReaderTests`)

**Interfaces:**
- Consumes: Task 1 `Docvol`, `Entry`, `warn`, `page_blocks`, `resolve_href`.
- Produces:
  - `shelf_dash.DashDocvol(path: str, source: str, cache_dir: str)`: `name` = folder name without `.docset`; `family = dash_family(name)`; `title` = `CFBundleName` from `Contents/Info.plist`, else `name`; `display_name = title`; `version` and `release` = `meta.json` `"version"` (Zeal writes it beside `Contents/`), else `""`; `read_only = True`; `entry_count` = `COUNT(*)` of the index table; `stamp()` = size and mtime of `docSet.dsidx` and `tarix.tgz` when present; `data_dir()` per Global Constraints.
  - `dash_family(name: str) -> str`: lowercased; spaces to `_`; a trailing `[_-]\d+(\.\d+)*` removed (`Python_3` -> `python`, `Node.js` -> `node.js`, `Qt_6.5` -> `qt`).
  - `entries()`: from `searchIndex` or the `ZTOKEN` join (old: `iter_entries`), ordered by id; `Entry(name, type, ref="<Name>:<id>", page, anchor)` with `page, anchor = entry_location(path)` (old). Rows whose path is empty or starts with `http://`/`https://` are skipped.
  - `resolve(rest)`: `rest` all digits -> that entry (exit 5 if no such id); `page:<path>[#anchor]` -> `(path, anchor, None)`; anything else -> CLIError 2 `bad reference` naming both forms.
  - `make_ref(page, anchor)` -> `<Name>:page:<page>[#anchor]`.
  - `pages()`: the distinct entry pages, in entry order.
  - `page_html(page)`: the file under `Contents/Resources/Documents/` (old: `page_file`, refusing paths outside it with exit 5), decoded UTF-8 with `errors="replace"`; tarix comes in Task 4.
  - `resolve_href(page, href)`: target resolved with `resolve_doc_path`; a REF when the file exists under `Documents/` (or, after Task 4, in the tarix index), else `None`. No full page scan.
  - `open_docset(path, source, cache_dir) -> Optional[DashDocvol]`: `None` plus one `warn` line when the index can't be read.
- Test helper (in `tests/test_docshelf.py`): `make_docset(root, name, entries, pages, form="searchIndex", plist_name=None, meta_version=None) -> str` writes `<root>/<name>.docset/Contents/{Info.plist, Resources/docSet.dsidx, Resources/Documents/...}`; `entries` are `(name, type, path)`; `form="ztoken"` writes the `ZTOKEN`, `ZTOKENTYPE`, `ZTOKENMETAINFORMATION`, `ZFILEPATH` tables with the anchor in `ZANCHOR`.

- [ ] **Step 1: Write the failing tests** (in-process, constructing `DashDocvol` directly; discovery comes in Task 5):
  - `test_search_index_entries_and_refs`: entries `("open", "Function", "lib.html#open")`, `("os", "Module", "os.html")`; `entries()` gives REFs `Lib:1`, `Lib:2`, pages `lib.html`, `os.html`, anchor `open`/`None`.
  - `test_ztoken_form_reads_the_same`: the same docset with `form="ztoken"` gives equal `(name, type, page, anchor)` tuples.
  - `test_marker_and_percent_paths`: path `<dash_entry_name=x>a%20b.html#x` gives page `a b.html`, anchor `x`; path `sub\\c.html` gives page `sub/c.html` (backslashes become `/` in `entry_location`).
  - `test_url_rows_are_not_entries`: a row with path `https://example.org/x` is not in `entries()` or `pages()`.
  - `test_resolve_forms`: `resolve("1")` returns the entry; `resolve("page:os.html#top")` returns `("os.html", "top", None)`; `resolve("x")` raises CLIError code 2; `resolve("99")` code 5.
  - `test_path_outside_documents_refused`: `page_html("../Info.plist")` raises CLIError code 5.
  - `test_title_version_family`: plist `CFBundleName` `Python 3`, `meta.json` `{"version": "3.12.4"}`: `title == "Python 3"`, `version == "3.12.4"`, `family == "python"` for folder `Python_3.docset`.
  - `test_unreadable_index_is_skipped`: an empty `docSet.dsidx` file: `open_docset` returns `None` and stderr has one line starting `warning: skipping`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_docshelf.DashReaderTests -v`. Expected: FAIL (no `shelf_dash`).
- [ ] **Step 3: Implement** the Interfaces, porting old `count_entries`, `iter_entries`, `entry_location`, `page_file`.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `docshelf: read Dash docsets (searchIndex and ZTOKEN forms)`.

### Task 4: Tarix docsets

**Files:**
- Modify: `skills/docshelf/scripts/shelf_dash.py`
- Test: `tests/test_docshelf.py` (helper `make_tarix`, class `DashTarixTests`)

**Interfaces:**
- Consumes: Task 3 `DashDocvol.page_html`, `resolve_href`.
- Produces: `page_html` falls back to the tarix archive (old: `_tarix`, `read_tarix`, `read_page_bytes`; `TARIX_MAX_RECORD = 64 MiB`) when `Documents/<page>` doesn't exist; `resolve_href` checks the tarix index (`tarindex.path`, case-insensitive) too. Connections are cached per docvol and closed at exit.
- Test helper: `make_tarix(docset_path, files: Dict[str, bytes])` moves the docset's `Documents/` files into `Contents/Resources/tarix.tgz` written with `zlib` full flushes before each tar record, and writes `tarixIndex.db` with `tarindex(path, hash)` = `"<Name>.docset/Contents/Resources/Documents/<file>"`, `"<block> <offset> <blocks>"` (see the old comment block above `TARIX_MAX_RECORD`).

- [ ] **Step 1: Write the failing tests:** `test_page_read_from_tarix` (no `Documents/` folder; `page_html("os.html")` returns its HTML); `test_tarix_missing_page_exit_5`; `test_tarix_link_resolves` (`resolve_href` on a link to a page only in the archive returns its REF); `test_corrupt_tarix_entry_exit_7` (a hash of `"0 0 999999999"` raises CLIError code 7).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_docshelf.DashTarixTests -v`. Expected: FAIL.
- [ ] **Step 3: Implement** by porting the old tarix functions into `shelf_dash`.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `docshelf: read pages from Dash tarix archives`.

### Task 5: Discovery, `list` and `where`

**Files:**
- Modify: `skills/docshelf/scripts/shelf_dash.py`, `shelf_backends.py`, `shelf_cli.py` (`cmd_list`, `cmd_where`)
- Test: `tests/test_docshelf.py` (class `DashDiscoveryTests`)

**Interfaces:**
- Consumes: Task 3 `open_docset`; Task 1 `installed_docvols`.
- Produces:
  - `shelf_dash.viewer_apps(env) -> List[Tuple[str, str]]` (old `viewer_apps`, plus Dash for Windows: a folder in `%LOCALAPPDATA%\Packages` whose name contains `Dash` and `Kapeli`, case-insensitive).
  - `shelf_dash.docset_folders(env) -> List[Tuple[str, str]]`: `(folder, source)`, in this order: each entry of `DOCSHELF_DOCSET_DIRS` (split on `os.pathsep`; `source="folder"`), then old `discover` candidates (`zeal` for Zeal folders including custom paths, `dash` for Dash's macOS folder and dasht's as `folder`), then each Dash for Windows package folder (`dash`). Only existing folders.
  - `shelf_dash.installed_docsets(cfg, env=None) -> List[DashDocvol]`: `.docset` folders directly in each folder, or one level down (old `_docset_dirs` depth 2), except Dash for Windows package folders, searched to depth 4. First folder wins a name; later copies go in the winner's `shadowed: List[str]`.
  - `shelf_backends.installed_docvols` returns DevDocs docvols, then docsets; a docset whose name equals a DevDocs name exactly is skipped with a `warn` naming both.
  - `list` line: `NAME  DISPLAY  RELEASE  N entries  full|small  SOURCE` (adds the source column for all docvols).
  - `where` adds `docset folders:` (each searched folder with `(found N)` or `(missing)`, and shadowed copies) and `apps: Dash (where), Zeal (where)` or `apps: none found`.
- Tests set `HOME`, `USERPROFILE`, `LOCALAPPDATA`, `XDG_DATA_HOME`, `XDG_CONFIG_HOME` to temporary folders, and `PATH` to an empty folder.

- [ ] **Step 1: Write the failing tests:**
  - `test_zeal_linux_default_folder`: a docset under `$XDG_DATA_HOME/Zeal/Zeal/docsets/`: `list` shows it with source `zeal`; `search` and `show <Name>:1` work.
  - `test_dash_macos_folder`: a docset under `$HOME/Library/Application Support/Dash/DocSets/X/`: source `dash`.
  - `test_dash_windows_package`: `$LOCALAPPDATA/Packages/Kapeli.Dash_abc123/LocalState/DocSets/Y.docset`: found, source `dash`; `where` lists `Dash` under apps.
  - `test_zeal_custom_path_from_conf`: `$XDG_CONFIG_HOME/Zeal/Zeal.conf` with `[docsets]\npath=<tmp>/custom`: a docset there is found.
  - `test_env_dirs_first_and_shadowing`: the same `Lib.docset` in `DOCSHELF_DOCSET_DIRS` and the Zeal folder: one `Lib` with source `folder`; `where` names the Zeal copy as shadowed.
  - `test_missing_env_dir_is_reported_not_fatal`: `DOCSHELF_DOCSET_DIRS` naming a missing folder: `list` exits 0; `where` shows it `(missing)`.
  - `test_where_reports_no_apps`: no apps and no folders: `where` prints `apps: none found`.
  - `test_docset_over_mcp`: with a Zeal-folder docset, the MCP `search` tool returns the same text as the CLI `search`, and `show` on its REF is not an error.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_docshelf.DashDiscoveryTests -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the Interfaces, porting old `_zeal_custom_paths`, `_ini_docsets_path`, `viewer_apps`, `discover`, `_docset_dirs`.
- [ ] **Step 4: Run** the full suite. Expected: all pass (update `list` output expectations for the new source column).
- [ ] **Step 5: Commit** `docshelf: discover Dash and Zeal docsets; list and where show them`.

### Task 6: Repeated-footer stripping for docsets

**Files:**
- Modify: `skills/docshelf/scripts/shelf_dash.py`
- Test: `tests/test_docshelf.py` (class `DashFooterTests`)

**Interfaces:**
- Consumes: Task 1 `page_blocks`; Task 3 `pages()`, `data_dir()`, `stamp()`.
- Produces: `DashDocvol.page_blocks(page, link=None)` drops the docset's repeated footer on every page except the keeper (old `detect_footer`, `footer_info`, `page_blocks`; constants `FOOTER_SAMPLE = 40`, `FOOTER_MIN_PAGES = 5`, `FOOTER_SHARE = 0.6`, `FOOTER_MAX_BLOCKS = 30`). Keeper: the `dashIndexFilePath` page from `Info.plist` when it is one of `pages()`, else `pages()[0]`. Cache: `<data_dir>/footer.json` with `{"stamp": "<stamp>|footer1", "footer": [...], "keep": page}`. Bump `FTS_FORMAT` to 3 and `HEADINGS_FORMAT` to 3 so existing indexes rebuild.

- [ ] **Step 1: Write the failing tests:** `test_repeated_footer_left_out_but_kept_once` (6 pages ending with the same two blocks `© Example` / `Licensed ...`: `show` of page 2 lacks them, `show` of the keeper has them, `fts Licensed` finds exactly one page); `test_no_footer_when_pages_differ` (pages ending differently: nothing dropped); `test_too_few_pages_no_detection` (4 identical-ending pages: nothing dropped).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_docshelf.DashFooterTests -v`. Expected: FAIL.
- [ ] **Step 3: Implement** by porting the old footer functions onto `DashDocvol`.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `docshelf: leave a docset's repeated page footer out of show, fts and headings`.

### Task 7: Read-only docsets and redundant installs

**Files:**
- Modify: `skills/docshelf/scripts/shelf_backends.py`, `shelf_devdocs.py` (`cmd_install`, `cmd_update`, `cmd_remove`), `shelf_cli.py` (`install --force`, `list` flags)
- Test: `tests/test_docshelf.py` (class `DashReadOnlyTests`)

**Interfaces:**
- Consumes: Task 5 `installed_docvols` with docsets; Task 1 `read_only`, `version`, `family`.
- Produces:
  - `shelf_backends.same_documentation(a: Docvol, b: Docvol) -> bool`: same `family`, different `source` kind (one DevDocs, one docset), and (`major.minor` of both versions equal, or the docset's version empty). `major.minor` = the first two dot-separated numbers found in the version string.
  - `install NAME`: when a read-only docvol is `same_documentation` as the DevDocs row about to be installed (family from the slug, version from the row): exit 2, `NAME: Dash/Zeal docset DOCSET has this documentation and is used as is; install --force NAME downloads it anyway`. `--force` (flag on `install`) skips the check.
  - `update NAME` / `remove NAME` on a read-only docvol: exit 2, `NAME is a Dash/Zeal docset; Dash or Zeal manages it`. `update` with no names skips docsets.
  - `list` appends `  also as docset X` to a DevDocs line and `  also as DevDocs Y` to a docset line for each `same_documentation` pair.

- [ ] **Step 1: Write the failing tests:**
  - `test_install_refuses_redundant_without_force`: docset `Python_3` (version `3.12.1`) on disk, DevDocs row `python~3.12` in the fake manifest: `install python~3.12` exits 2 with the message above and fetches nothing; `install python~3.12 --force` installs.
  - `test_install_other_version_is_not_redundant`: same docset, row `python~3.11`: installs without `--force`.
  - `test_unknown_docset_version_counts_as_same`: docset without `meta.json`: `install python~3.12` exits 2.
  - `test_remove_and_update_refuse_docsets`: both exit 2 with `Dash or Zeal manages it`; the docset folder is unchanged (same file list and mtimes).
  - `test_list_flags_redundant_pairs`: DevDocs `python~3.12` and docset `Python_3` 3.12: both lines carry the `also as` suffix.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_docshelf.DashReadOnlyTests -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the Interfaces; MCP gets `force` on `install` automatically from the command table.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `docshelf: docsets are read-only; install refuses redundant documentation unless --force`.

### Task 8: Dash/Zeal catalogs in `sources` and the not-installed hint

**Files:**
- Modify: `skills/docshelf/scripts/shelf_dash.py` (catalog code), `shelf_devdocs.py` (`cmd_sources`, `NetError` message, `not_installed_message`), `skills/docshelf/assets/allowlist.txt`
- Test: `tests/test_docshelf.py` (class `DashCatalogTests`, using `FakeNet`)

**Interfaces:**
- Consumes: Task 5 `viewer_apps`, `docset_folders`, `installed_docsets`; `shelf_devdocs.fetch` (patched by `FakeNet`).
- Produces:
  - Constants (old values): `FEEDS_LIST_URL`, `CONTRIB_LIST_URL`, `ZEAL_CATALOG_URL`, `CATALOG_MAX_AGE = 7 * 86400`.
  - `shelf_dash.catalog_names(cfg, refresh: bool) -> List[Tuple[str, str, str, str]]`: `(name, version, title, label)` with label `official` or `user-contributed`: the GitHub listings (official: `*.xml` file names minus `.xml` at the root of Kapeli/feeds; contributed: folder names under `docsets/`), each cached in `<cache>/docsets/catalogs/<key>.json` for `CATALOG_MAX_AGE`; Zeal's catalog only when a GitHub listing fails (`sourceId` `com.kapeli.dash` / `com.kapeli.contrib`). Raises `CLIError(7)` when both fail for a label.
  - `shelf_dash.catalogs_wanted(env) -> bool`: `viewer_apps(env)` or `docset_folders(env)` non-empty.
  - `sources QUERY`: DevDocs rows as now; then, when `catalogs_wanted`, matching catalog names as `NAME  (Dash/Zeal: download in the app, LABEL)` plus `  (here as X)` when on disk. A failing catalog prints `note: the Dash/Zeal LABEL list could not be loaded (...)` and the exit code stays that of the DevDocs part.
  - `NetError` names the host it failed on and points to `assets/allowlist.txt` without a fixed host list.
  - `not_installed_message`: when no DevDocs row matches but a cached catalog (never fetched here) has the name and an app is installed: `docvol 'X' is not installed; Dash/Zeal can download docset 'Y' (in the app); docshelf doesn't install docsets`.
  - `allowlist.txt` lists exactly devdocs.io, documents.devdocs.io, api.github.com, api.zealdocs.org.

- [ ] **Step 1: Write the failing tests:**
  - `test_sources_lists_catalog_names_when_app_present`: a fake Zeal install (`$XDG_DATA_HOME/Zeal/Zeal/docsets` exists); FakeNet serves the two GitHub listings; `sources python` prints `Python_3  (Dash/Zeal: download in the app, official)`.
  - `test_sources_no_catalog_without_app_or_folder`: no apps, no folders: FakeNet records no GitHub or Zeal URL.
  - `test_zeal_catalog_fallback`: GitHub URLs raise `NetError`; Zeal's catalog served: names still listed, stderr has the fallback note.
  - `test_catalog_failure_keeps_devdocs_part`: all three fail: DevDocs rows printed, the `could not be loaded` note printed, exit 0.
  - `test_catalog_cached_for_a_week`: two `sources` runs fetch each listing once.
  - `test_not_installed_hint_from_cached_catalog`: cached catalog with `Lua`, a Zeal folder present, `search x -d Lua` exits 4 with `Dash/Zeal can download docset 'Lua'`.
  - `test_allowlist_lists_exactly_the_hosts_used` (in the existing allowlist test, updated).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_docshelf.DashCatalogTests -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the Interfaces, porting old `_github_names`, `_slim_catalog`, `docset_names`, `_norm` (a plain timed cache is enough; no ETag handling).
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `docshelf: sources lists Dash/Zeal docsets; hint names a downloadable docset`.

### Task 9: Docs, version and real-data check

**Files:**
- Create: `skills/docshelf/references/dash-zeal.md`
- Modify: `skills/docshelf/SKILL.md`, `references/getting-docvols.md`, `scripts/shelf_cli.py` (top-level help), `scripts/shelf_core.py` (`VERSION`), `AGENTS.md` (docshelf line), `TODO.md`
- Test: `tests/test_docshelf.py` (`TOP_HELP_EXPECTED` updated; `test_skills.py` link check covers the new reference)

**Interfaces:**
- Consumes: everything above.
- Produces: user-facing docs only.

- [ ] **Step 1: Update the help test** `TOP_HELP_EXPECTED` for: `-d` takes a docvol or family name; `install NAME --force`; `list` source column; docset REF forms. Run `python3 -m unittest tests.test_docshelf.HelpTests -v`. Expected: FAIL.
- [ ] **Step 2: Update** the top-level help to match; run the help tests. Expected: PASS.
- [ ] **Step 3: Write the docs:**
  - `SKILL.md` (stay short): the description gains "or Dash/Zeal docsets already on disk"; the agent policy (spec "Agent policy" steps 1-6) in a few lines; Kapeli terms sentence (personal use or with Dash or Zeal; point the user to the Kapeli/feeds README terms when use looks non-personal); "Read when needed" pointer to `references/dash-zeal.md`.
  - `references/dash-zeal.md`: discovery folders per OS (Dash for Windows path marked unverified), `DOCSHELF_DOCSET_DIRS`, REF forms, read-only rule, the policy-3 message to the user, other docset MCP servers to check first (Kapeli's Dash MCP server), `install --force`.
  - `references/getting-docvols.md`: a docset on disk is used instead of `install`; redundant installs need `--force` and the user's explicit request.
  - `AGENTS.md` docshelf line: DevDocs and Dash/Zeal docsets (read-only); `TODO.md`: remove the Dash/Zeal backend item and the "backend interface before the Dash backend" item; keep the Info.plist FTS item.
  - `VERSION = "0.4.0"` and SKILL.md `version: "0.4.0"`.
- [ ] **Step 4: Run** `python3 -m unittest discover -s tests` and `python3 scripts/ci_changed_skills.py --base origin/main --check-versions`. Expected: all pass; `skills=docshelf`.
- [ ] **Step 5: Real-data check** with the docset the user uploads: put it in a temporary `DOCSHELF_DOCSET_DIRS` folder and also in `~/.local/share/Zeal/Zeal/docsets` (Zeal is installed in the sandbox); run `where`, `list`, `search`, `show`, `fts`, `notes --check`; record the results (entry count, any footer found, odd pages) at the end of this plan.
- [ ] **Step 6: Commit** `docshelf 0.4.0: Dash/Zeal docsets, docs and policy`, push `update/docshelf`, open the PR with the template.
