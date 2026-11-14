# dash-docset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `dash-docset` skill whose stdlib Python script installs Dash docsets and searches/shows them as compact text with per-docset notes.

**Architecture:** One CLI file, `skills/dash-docset/scripts/docset.py`, with argparse subcommands over small pure functions (store resolution, index reading, ranking, HTML-to-text, notes, FTS, feeds). Tests import the script as a module and also run it as a subprocess against fixture docsets built in a temp dir.

**Tech Stack:** Python 3.9+ stdlib only (`sqlite3` + FTS5, `tarfile`, `urllib.request`, `plistlib`, `html.parser`, `json`, `argparse`).

**Spec:** `docs/superpowers/specs/2026-11-14-dash-docset-design.md`

## Global Constraints

- Stdlib only; no install step. Python 3.9+.
- Files: `skills/dash-docset/SKILL.md`, `skills/dash-docset/scripts/docset.py`, `tests/test_dash_docset.py` (starts with `if not selected("dash-docset"): raise unittest.SkipTest(...)`).
- Frontmatter per `AGENTS.md`, `version: "0.1.0"`, `description` one line starting "Use when", and `compatibility: network access to Kapeli feeds and GitHub for install/update; search works offline`.
- `SKILL.md` under 500 lines / 5,000 tokens; details live in `--help`.
- No network in tests. No machine/account details in any file (`tests/test_public_safety.py`).
- Never write into a dasht, Zeal or Dash folder. Notes and FTS indexes for every docset live in the script's own store.
- Defaults: `--max-lines` 40 for `search`/`fts`, 150 for `show`. Notes limits: General > 50, any section > 100, total > 2,000 lines. Scope: error without `--all` when no project list and more than 4 full-size docsets; full size = not from the cheat-sheet source, except foreign docsets with < 500 index entries.
- Run all tests from repo root: `python3 -m unittest discover -s tests -v`.

## Review Focus

1. Docset paths with `<dash_entry_...>` markers, URL-encoded characters, `#anchors` and no anchor: `show` must still find the page (Task 5 test `test_show_path_variants`).
2. Malicious or odd archives (absolute paths, `..`, symlinks out, not gzip): install refuses and leaves the store unchanged (Task 8 test `test_safe_extract_rejects`).
3. Docsets with neither `searchIndex` nor `ZTOKEN` tables, or a locked/corrupt `docSet.dsidx`: skipped with a one-line warning, other docsets still searched (Task 3 test `test_unreadable_docset_skipped`).
4. Python built without FTS5: `fts` prints a clear message and exits 2; everything else works (Task 7 test `test_fts_unavailable`).
5. Non-UTF-8 or huge HTML pages: decoded with replacement, output still capped by `--max-lines` (Task 5 test `test_show_bad_encoding_and_cap`).

---

### Task 1: Skeleton, fixtures, and frontmatter

**Files:**
- Create: `skills/dash-docset/SKILL.md` (frontmatter + one-paragraph placeholder body; finished in Task 9)
- Create: `skills/dash-docset/scripts/docset.py`
- Create: `tests/test_dash_docset.py`

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int`; subcommands registered (stubs exit 2 "not implemented"): `where sources install update list remove search show fts index-text notes`.
- Produces (tests): `make_docset(root: str, name: str, form: str = "searchIndex", entries: list[tuple[str,str,str]] | None = None, pages: dict[str,str] | None = None) -> str` returns the `.docset` path. `form` is `"searchIndex"` or `"ztoken"`. Default entries: `("asyncio.gather","Function","library/asyncio.html#asyncio.gather")`, `("asyncio.sleep","Function","library/asyncio.html#asyncio.sleep")`, `("Gather","Guide","guide.html")`. Default page `library/asyncio.html` has `<h2 id="asyncio.gather">`, a `<pre>` block, then `<h2 id="asyncio.sleep">`.
- Produces (tests): `run_cli(*args, env=None) -> subprocess.CompletedProcess` running the script with `sys.executable`.

- [ ] **Step 1:** Write `test_help_lists_subcommands` (`--help` exit 0, every subcommand name in stdout) and `test_fixture_both_forms` (both forms create `Contents/Resources/docSet.dsidx` and `Contents/Info.plist`).
- [ ] **Step 2:** Run `python3 -m unittest tests.test_dash_docset -v`. Expected: FAIL (script missing).
- [ ] **Step 3:** Create the script with argparse subparsers and the stub handlers; the module must be importable without side effects (`if __name__ == "__main__": sys.exit(main())`). Write `SKILL.md` frontmatter.
- [ ] **Step 4:** Run the whole suite. Expected: PASS, including `test_skills.py` on the new skill.
- [ ] **Step 5:** Commit `dash-docset: skeleton, fixtures, frontmatter`.

### Task 2: Store resolution (`where`)

**Files:** Modify `scripts/docset.py`; Test `tests/test_dash_docset.py`

**Interfaces:**
- Produces: `@dataclass Store(path: str, source: str, read_from: list[str], project_docsets: list[str] | None)`.
- Produces: `resolve_store(cli_dir: str | None, cwd: str, env: Mapping[str,str]) -> Store | None`. Order: `--dir` > `DASH_DOCSET_DIR` > nearest `.dash-docset.json` walking up from `cwd` > user config (`$XDG_CONFIG_HOME/dash-docset/config.json`, default `~/.config/...`; Windows `%APPDATA%\dash-docset\config.json`) > `None`. Config keys: `"store"`, `"read_from"`, `"docsets"` (project file only). Relative paths in a project file resolve against that file's folder.
- Produces: `discover(env: Mapping[str,str]) -> list[str]` existing folders among `$DASHT_DOCSETS_DIR`, `$XDG_DATA_HOME/dasht/docsets` (default `~/.local/share/...`), `~/.local/share/Zeal/Zeal/docsets`, `%LOCALAPPDATA%\Zeal\Zeal\docsets`, `~/Library/Application Support/Dash/DocSets`.
- Produces: `require_store(args) -> Store` prints "storage location not set" plus `discover()` results to stderr and exits 3 when `None`. Every later command uses it.
- CLI: `where`, `where --discover`, `where --set PATH (--project|--user) [--read-from DIR]...`. `--set ... --project` with a path named `.docsets` inside the project also writes `.docsets/.gitignore` containing `*`, `!.gitignore`, `!notes/`, `!notes/**`.

- [ ] **Step 1:** Tests (all with a temp `HOME`/`XDG_*` env): `test_resolve_order` (each source beats the next), `test_project_file_relative_paths`, `test_unset_exits_3_and_lists_discovered` (fake dasht dir exists → listed), `test_set_project_writes_gitignore`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement. Use `os.path.expanduser` / env lookups only; no hardcoded home paths.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit `dash-docset: store resolution and where`.

### Task 3: Reading docsets (`list`, index access)

**Interfaces:**
- Produces: `@dataclass Docset(name: str, path: str, foreign: bool, source: str | None, version: str | None, entry_count: int)`; `full_size` property per Global Constraints (source `"cheat"` → False; foreign and `entry_count < 500` → False; else True).
- Produces: `find_docsets(store: Store) -> list[Docset]` from `store.path` (with `installed.json` metadata) then each `read_from` dir (foreign). Same-name clash: store wins, clash recorded for `list`.
- Produces: `iter_entries(ds: Docset) -> Iterator[tuple[int, str, str, str]]` yielding `(id, name, type, path)` for either index form (`ZTOKEN` join: `ZTOKENNAME`, `ZTOKENTYPE→ZTYPENAME`, `ZFILEPATH.ZPATH` + `ZTOKENMETAINFORMATION.ZANCHOR`). Open SQLite read-only (`file:...?mode=ro`, `uri=True`).
- Produces: `meta_dir(store) -> str` = `<store>/.dash-docset`; `load_installed(store) -> dict`, `save_installed(store, data) -> None` (atomic write via temp + `os.replace`).
- CLI `list`: one line per docset: name, source or "foreign (<dir>)", version, entries, `full`/`small`, and clash notes.

- [ ] **Step 1:** Tests: `test_iter_entries_both_forms` (same 3 entries from each fixture form), `test_list_marks_foreign_and_clash`, `test_full_size_rule` (cheat → small; foreign 3 entries → small; installed kapeli → full), `test_unreadable_docset_skipped` (a `.docset` with an empty dsidx: warning on stderr, others listed).
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `dash-docset: read docsets and list`.

### Task 4: `search` (ranking, scope, caps)

**Interfaces:**
- Produces: REF format `"<DocsetName>:<id>"`; `parse_ref(ref: str) -> tuple[str, int]`.
- Produces: `rank(query: str, name: str) -> int | None`: 0 exact (case-insensitive), 1 prefix, 2 substring, 3 fuzzy (characters in order, dasht's `%a%b%c%`), `None` no match. Ties: shorter name first, then name.
- Produces: `select_docsets(store, all_docsets, names: list[str], use_all: bool) -> list[Docset]` implementing scope: `-d` names > `store.project_docsets` > all if ≤ 4 full-size or `use_all`; otherwise raise `ScopeError` whose message lists the full-size docsets and suggests `-d`, `"docsets"` in `.dash-docset.json`, or `--all`. CLI exits 4 on it.
- Produces: `cap_lines(lines: list[str], max_lines: int, hint: str) -> list[str]` appends `"... N more lines cut; <hint>"` when truncated. Shared by `fts`, `show`.
- CLI: `search QUERY [-d NAME]... [--all] [--type TYPE] [--max-lines N=40] [--json]`. Text line: `REF  Type  Name  (Docset)`. Results ranked across all selected docsets before the cap. `--json` emits a list of `{ref, docset, type, name, rank}` (cap applies to items).

- [ ] **Step 1:** Tests: `test_rank_order`, `test_search_ranks_across_docsets`, `test_scope_project_list`, `test_scope_error_over_four_full` (5 full fixtures → exit 4, names in stderr; `--all` → exit 0), `test_scope_small_docsets_dont_count`, `test_search_max_lines_and_hint`, `test_search_json`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `dash-docset: search`.

### Task 5: `show` (HTML to trimmed text)

**Interfaces:**
- Consumes: `parse_ref`, `iter_entries` (lookup by id), `cap_lines`.
- Produces: `entry_location(path: str) -> tuple[str, str | None]`: strips `<dash_entry_...>` markers, splits `#anchor`, URL-decodes the file part.
- Produces: `html_to_text(html: str) -> list[tuple[int, str | None, str]]`: blocks of `(heading_level or 0, element_id or None, text)`; keeps headings as `#`-prefixed lines, `<pre>` verbatim, list items as `- `; drops `script`, `style`, `nav`, `header`, `footer`.
- Produces: `trim_to_anchor(blocks, anchor: str | None) -> list[str]`: from the block whose id (or any inner `id`/`name` seen in it) equals the anchor to before the next heading of the same or higher level; no anchor → whole page.
- CLI: `show REF [--full] [--max-lines N=150] [--no-notes]`. Decode bytes as UTF-8 with `errors="replace"`. Notes appended in Task 6.

- [ ] **Step 1:** Tests: `test_show_trims_to_anchor` (gather section shown, sleep heading absent, `<pre>` text kept), `test_show_path_variants` (marker, `%20`, no anchor), `test_show_bad_encoding_and_cap` (latin-1 bytes, 1,000-line page → 150 lines + hint; `--full` → all), `test_show_unknown_ref` (exit 5, message).
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `dash-docset: show`.

### Task 6: Notes

**Interfaces:**
- Produces: `notes_path(store, docset_name) -> str` = `<store>/notes/<Name>.md` (also for foreign docsets).
- Produces: `parse_notes(text: str) -> tuple[list[str], dict[str, list[tuple[str | None, list[str]]]]]`: General lines, and sections keyed by lowercased trimmed heading name, each with optional type from a trailing ` (Type)`.
- Produces: `notes_for(store, docset_name, entry_name, entry_type) -> list[str]` (General + matching sections, prefixed by a `--- notes (<path>) ---` line; empty if no file).
- Produces: `check_notes(text, entry_names: set[str]) -> list[str]` warnings: General > 50, section > 100 (names it), total > 2,000, orphan headings (no matching entry).
- CLI: `notes DOCSET [--check | --path]`; `show` appends `notes_for` unless `--no-notes` and prints `check_notes` size warnings (not orphans) to stderr; `search` prints the General section once per docset with results, only in text mode.

- [ ] **Step 1:** Tests: `test_notes_match_case_and_type`, `test_notes_shown_with_show`, `test_notes_for_foreign_docset_live_in_store` (foreign folder unchanged after `notes --path` + write), `test_check_limits` (one 250-line section warns; 100 sections x 10 lines doesn't), `test_check_orphans`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `dash-docset: notes`.

### Task 7: Full-text search (`index-text`, `fts`)

**Interfaces:**
- Produces: `fts_available() -> bool` (try creating an in-memory FTS5 table).
- Produces: `build_fts(store, ds: Docset) -> int` (pages indexed) into `<store>/.dash-docset/fts/<Name>.sqlite`: table `pages(path, text)` FTS5 `unicode61`; table `page_entries(path, entry_id)`; table `meta(key, value)` with `docset_version` and `built_at`.
- Produces: `fts_search(store, docsets, query, limit) -> list[dict]` with `ref` (first entry pointing into the page, else `"<Name>:page:<path>"`, which `show` must also accept), `docset`, `path`, `snippet` (FTS5 `snippet()`), ranked by `bm25`.
- CLI: `index-text DOCSET...`; `fts QUERY [-d]... [--all] [--max-lines N=40] [--json]`. Builds missing indexes; rebuilds when `docset_version` differs and prints "rebuilt index for X" to stderr. Same scope rules as `search`.

- [ ] **Step 1:** Tests: `test_fts_finds_text_in_page` (word only in `<pre>` body), `test_fts_rebuilds_stale` (change version in `installed.json`), `test_fts_unavailable` (monkeypatch `fts_available` → False via module call of `main`; exit 2, message), `test_show_accepts_page_ref`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `dash-docset: full-text search`.

### Task 8: Sources, install, update, remove

**Interfaces:**
- Produces: `@dataclass Feed(name: str, source: str, version: str, urls: list[str])` with source in `kapeli`, `user`, `cheat`.
- Produces: `parse_kapeli_xml(text: str, name: str) -> Feed`, `parse_index_json(data: dict, source: str, base_url: str) -> list[Feed]`.
- Produces: `fetch(url: str) -> bytes` (the only network function; tests replace it), `load_sources(store, refresh: bool) -> list[Feed]` cached in `<store>/.dash-docset/cache/` with fetch time; cache older than 7 days refetched.
- Produces: `safe_extract(tgz_path: str, dest: str) -> str` returns the extracted `.docset` dir; rejects absolute paths, `..`, links pointing outside, non-gzip; raises `ArchiveError`.
- Produces: `install(store, spec: str) -> Docset`; `spec` may be `kapeli:`/`user:`/`cheat:` prefixed; an unprefixed name found in more than one source raises `AmbiguousName` listing prefixes (exit 6). Download to temp in the store, extract to temp, `os.replace` into place, update `installed.json` (name, source, version, url, installed date).
- CLI: `sources [QUERY] [--refresh]`, `install SPEC...`, `update [NAME...]` (compares version strings for inequality; foreign → refused; after updating, prints `check_notes` orphan warnings for that docset), `remove NAME` (refuses foreign; leaves notes; deletes FTS index).
- Hand step: verify the live feed URLs and formats once, put the base URLs as constants with a dated comment, and add the needed hosts to the `agent-skills` cloud environment's allow list (ask the user via the environment tools).

- [ ] **Step 1:** Tests with fixture feed XML/JSON and a fixture `.tgz` made from `make_docset`, `fetch` replaced: `test_parse_feeds`, `test_install_and_list`, `test_install_ambiguous_needs_prefix`, `test_safe_extract_rejects` (each bad archive; store unchanged), `test_update_and_remove_refuse_foreign`, `test_remove_keeps_notes`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Hand-verify feeds live: `python3 skills/dash-docset/scripts/docset.py --dir "$(mktemp -d)" sources python` lists Python, then `install` a small cheat sheet and `search` it.
- [ ] **Step 6:** Commit `dash-docset: sources, install, update, remove`.

### Task 9: SKILL.md and finish

**Files:** Modify `skills/dash-docset/SKILL.md`; maybe `AGENTS.md` (Skills list entry).

Content `SKILL.md` must carry (not in `--help`):
- When to reach for it vs Context7/web/per-library skills (one short paragraph).
- First-run storage conversation: run `where`; if unset, run `where --discover`, then put the options from the spec's "Storage location" to the user and run `where --set`. Never pick a location without the user.
- Workflow: `search` → `show REF`; `fts` when names don't match; use `-d`/project `"docsets"` list; respect `--max-lines`.
- Notes: edit with normal file tools at `notes --path`; heading format; on a size warning, suggest to the user turning the heavy section into its own minimal skill built around the tasks it covers.
- Pointer: `python scripts/docset.py --help` and `<command> --help`.

- [ ] **Step 1:** Write `SKILL.md`; check under 500 lines.
- [ ] **Step 2:** Add the skill to `AGENTS.md` "Skills" list (one entry).
- [ ] **Step 3:** Run the full suite and `npx skills add . --list` (lists `dash-docset`).
- [ ] **Step 4:** Read the whole branch diff for machine/account details.
- [ ] **Step 5:** Commit `dash-docset: SKILL.md` and push `skill/dash-docset`; ask the user for review (AGENTS.md "Adding a skill" step 4).
