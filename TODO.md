# TODO

## Formats

- [ ] Claude Code plugin: `.claude-plugin/plugin.json` (+ `marketplace.json`)
      pointing at `skills/`; the skills CLI also reads these manifests.
- [ ] Claude desktop/web plugin (zip upload).
- [ ] opencode v2 plugin (and v1, if still worth it).
- [ ] Versioning, once a format with a version field exists.

## Skills

- [ ] `opencode-console`: on hold (the user, 2026-11-08). Checked 2026-11-08:
      the Console docs have no API for reading or writing Go/Zen account data
      (usage, balance, billing and budgets are web-UI only; usage export is a
      CSV button). They document only the inference endpoints
      (`https://opencode.ai/inference/...`), the model lists
      (`GET /inference/v1/models`, `/inference/go/v1/models`), API key types
      and SCIM user sync. Revisit if an account API appears.
- [ ] Docs-cache skills copy their refresh script (each skill must stand
      alone when installed). If they drift, generate the copies from one
      template instead of hand-editing each.
- [ ] `opencode-build` `ERRATA.md`: record the doc mistakes already seen
      (verify each against the installed `@opencode/plugin` types).
### docshelf

Numbered so items can be referred to (e.g. "6.2.3"); renumber freely when
items are done.

#### 1. Features

(none open)

#### 2. Dash/Zeal docsets

- [ ] 2.1 Verify where Dash for Windows (Microsoft Store app) keeps docsets
      on a real install, and pin the exact path in `shelf_dash.py` and
      `references/dash-zeal.md` (marked unverified there; discovery searches
      `%LOCALAPPDATA%\Packages\<Kapeli Dash package>\` up to 4 levels deep).
- [ ] 2.3 (low priority) Some docsets' `Info.plist` has a full-text-search
      flag (keys to verify; possibly `DashDocSetDefaultFTSEnabled` /
      `DashDocSetFTSNotSupported`): do such docsets ship a text index `fts`
      could use, and should "not supported" skip indexing? (the user,
      2026-11-16)

#### 3. Rendering

(none open)

#### 4. Full-text search

- [ ] 4.2 Cap index builds on huge docvols and mark the index partial
      (bbsvip/docset-mcp).

#### 5. Agents and docs

- [ ] 5.2 Agent trials as dash-docset ran them (no-skill baseline, Haiku,
      the opencode model set, CLI vs `--mcp`), DevDocs and docsets
      (the user, 2026-11-16).
  - Done 2026-11-17 (0.6.0, one Jinja task, DevDocs, CLI, default effort):
    Haiku x3, Sonnet x1. All found `select_autoescape` and cited the REF.
    After the "First lookup" steps moved near the top of SKILL.md, all ran
    `suggest` and asked the lookup-defaults question; Sonnet also offered
    the `"docvols"` list, Haiku sometimes skips that offer. Accepted: weaker
    models may skip it (the user, 2026-11-17).
  - Still open: no-skill baseline, the opencode model set, `--mcp`,
    docsets.

#### 6. Deferred review items

- [ ] 6.1 Links and REFs
  - [ ] 6.1.2 A link with `..` past the docvol root is clamped silently.
  - [ ] 6.1.3 `resolve()` scans a docset's entries linearly per id.
- [ ] 6.2 DevDocs install, update and sources
  - [ ] 6.2.2 The real `fetch()` is untested (User-Agent, redirects, error
        mapping): add a loopback `http.server` test.
  - [ ] 6.2.4 A same-mtime reinstall trusts `meta.json` without checking
        the files exist; the page index is built twice at install.
  - [ ] 6.2.5 Temp files from `mkstemp` are mode 0600, so cache files lose
        the umask permissions (matters only for a shared cache); a process
        killed mid-build leaves a stray `*.tmp`.
  - [ ] 6.2.6 Every command parses each DevDocs docvol's `index.json` for
        `entry_count`; store the count in `meta.json` at install.
- [ ] 6.3 MCP
  - [ ] 6.3.1 Error text still says "(see: docshelf.py list)" and uses CLI
        flag names.
  - [ ] 6.3.2 `initialize` sends no "instructions".
  - [ ] 6.3.3 `"id": null` is treated as a request.
  - [ ] 6.3.4 Batch arrays are rejected while 2025-03-26 is advertised.
  - [ ] 6.3.5 `_parser_defaults` reads argparse's private attributes.
- [ ] 6.4 Docset reading (index, tarix)
  - [ ] 6.4.1 WAL stamps use whole-second mtimes; the stamp test only
        checks for "-".
  - [ ] 6.4.2 Containment tests cover `..` only (no absolute or backslash
        paths).
  - [ ] 6.4.3 The `Info.plist` and `_index_page` reads catch a bare
        `Exception`.
  - [ ] 6.4.4 Tarix: no tests for symlink or directory members or a
        truncated archive; the containment-before-lookup test isn't
        discriminating.
  - [ ] 6.4.5 Tarix: `resolve_href` turns exit-7 errors into "no link"
        silently; the index is opened and its prefix probed per lookup
        (cache the prefix per docvol).
- [ ] 6.5 Discovery, `where` and `list`
  - [ ] 6.5.1 `where` prints `[source]` only for folders that exist.
  - [ ] 6.5.2 `where_lines` and `installed_docvols` each open every docset.
  - [ ] 6.5.3 `list` repeats "also as" once per matching pair.
  - [ ] 6.5.4 No test for `remove`/`update` with a family name matching
        both a DevDocs docvol and a docset.
  - [ ] 6.5.5 `import shelf_backends` is repeated lazily in 3 functions.
- [ ] 6.6 Repeated header/footer cache
  - [ ] 6.6.1 `repeats.json` items aren't type-checked on read.
  - [ ] 6.6.2 `REPEAT_FORMAT` bumps don't rebuild the fts and headings
        indexes (bump `FTS_FORMAT` and `HEADINGS_FORMAT` by hand).
  - [ ] 6.6.3 No tests for cache reuse, rebuild when the docset changes,
        the `Info.plist` keeper page or the write-failure warning.
- [ ] 6.7 Dash/Zeal catalogs
  - [ ] 6.7.1 The "came from Zeal's catalog" note prints once per list when
        both fall back (the catalog itself is fetched once).
  - [ ] 6.7.3 Unused loop variables in `cached_catalog_match`.
  - [ ] 6.7.4 No tests for catalog cache expiry, malformed JSON or the MCP
        text of the new network error.
- [ ] 6.8 Tests and small cleanups
  - [ ] 6.8.1 An expected "skipping" warning leaks into test stderr.
  - [ ] 6.8.2 No tests for CRLF notes files or exit 2 for help with no
        command.
  - [ ] 6.8.3 `show` reads the notes file twice, through the private
        `_read_notes`.
  - [ ] 6.8.4 The first line of SKILL.md's body is very long.
  - [ ] 6.8.6 Tests: no lock on the SKIP_TAGS-before-STRUCTURE_TAGS order;
        `<html>` cases untested; `FtsMaxLinesTests` checks counts only; no
        `show --offset` boundary tests (total == max_lines, offset =
        total-1) or MCP nonneg test; no exit-4 scope test for `types`;
        `TypesTests.setUp` builds its own env; no MCP no-argument install
        test; the docset-skip install test doesn't prove no download; no
        temp-cleanup or traversal tests for notes writes.
  - [ ] 6.8.7 Cosmetics: an extra blank line in `shelf_render`'s imports;
        the `types` help line is ~81 columns.
- [ ] 6.9 Notes
  - [ ] 6.9.2 No lock against concurrent writers of notes files (writes are
        atomic; last writer wins).
- [ ] 6.10 Full-text search
  - [ ] 6.10.1 The match expression is built more than once; the `ids`
        query keeps punctuation for plain tokens.

- [ ] 6.12 After the 0.6.0 reviews
  - [ ] 6.12.1 No CLI test for a double-encoded anchor or the
        "warning: no #..." path in `show` (only `section_lines` is tested).
  - [ ] 6.12.2 `unquote_all` stops after 3 passes; untested and
        undocumented.
  - [ ] 6.12.3 `suggest`: a docset and a DevDocs docvol of the same family
        are chosen by `installed_docvols` order (DevDocs first); untested.
  - [ ] 6.12.5 `shelf_suggest`: `_has_parser_file` repeats `_scan_dir`'s
        filter; CMake `#` inside quotes or `#[[ ]]` comments isn't handled.
  - [ ] 6.12.6 Tests: `.ruby-version` with a `ruby-` prefix, Docker
        `--platform` and registry prefixes (`localhost:5000/`, `ghcr.io/`),
        an `==3.11` Python spec, a non-UTF-8 build file;
        `test_installed_and_available` re-sorts `docs.json` instead of
        listing rows in order.
  - [ ] 6.12.7 `name=` on `<details>` (an accordion group name) still adds
        an anchor; harmless unless it collides.

- [ ] 6.13 After the 0.6.1 reviews
  - [ ] 6.13.1 Notes tests: an LF file stays LF; a mixed-ending file takes
        the majority ending.
  - [ ] 6.13.2 Test `--delete` on a notes file that is a dangling symlink.
  - [ ] 6.13.3 Install tests: a failure message names the slug; a 404
        leaves no folder behind; a redundant skip plus a failure exits with
        the failure's code.
  - [ ] 6.13.4 `sources` dedupes after the query filter; it should keep
        the first row overall.
  - [ ] 6.13.5 `_cached_or_fetched`: `getmtime` can raise OSError if the
        file goes away between checks.
  - [ ] 6.13.6 No test for reusing a stale Zeal catalog cache offline.
  - [ ] 6.13.7 Nameless catalog entries are undercounted when only the
        contrib catalog falls back.
  - [ ] 6.13.8 `_zeal_rows` docstring has a stray "((".
  - [ ] 6.13.9 The 6.12.4 lower-bound test lists the newer version first
        only.
  - [ ] 6.13.10 `install` repeats an exit-2 error (unwritable cache) once
        per name.

#### Reference: other docset and DevDocs readers (skimmed 2026-11-17)

Read Zeal's folder, no network:
https://github.com/andreas-mausch/docset-mcp (Rust),
https://github.com/keturn/ZDocsetMCP (Python, MIT),
https://github.com/erno-szabados/zealmcp (Python, MIT, tiny).
Downloads docsets via Zeal's catalog: https://github.com/bbsvip/docset-mcp.
macOS / Dash only: https://github.com/Kapeli/dash-mcp-server,
https://github.com/codybrom/DocsetMCP,
https://github.com/joshuadanpeterson/enhanced-dash-mcp,
https://github.com/Robdel12/doc-fetcher-mcp,
https://github.com/nzrsky/appleref-mcp.
DevDocs-based: https://github.com/maxwhipw/devdocs-mcp,
`@madhan-g-p/devdocs-mcp-server` (npm). Non-MCP: dasht,
`zeal python:pprint` (opens the GUI). Not worth taking from them: HTTP or
Docker transports, talking to the running Dash app, Readability/Turndown
conversion, Apple's DocC format (needs brotli), downloading from Kapeli's
servers.

## Automation

- [ ] Scheduled workflow: run each skill's `refresh_references.py` weekly and
      open a PR when the docs changed.

## Consumers

- [x] The project where `opencode-build` started: it installs the opencode
      skills as copies with `npx skills add ... --copy` (for other harnesses)
      and loads the HTTP catalog in opencode (the user, 2026-11-08).

## Ideas for later

- [ ] Group skills into category folders, e.g. `skills/opencode/<name>/` and
      `skills/misc/<name>/`, each with its own generated `index.json`, so an
      opencode project can load one group:
      `https://raw.githubusercontent.com/rjstone/agent-skills/main/skills/opencode/`.
      Checked against opencode 2.2.5's catalog code (2026-11-08):
      - A catalog URL is always a folder (`<url>/index.json`); it cannot
        name another file such as `index-opencode.json`.
      - A top-level `skills/index.json` cannot aggregate the groups: entry
        files come only from `<base>/<name>/`, `name` cannot contain `/`,
        paths cannot use `..`, and an entry must list its own `SKILL.md`.
        For "everything", list each group's URL in `skills` (entries are
        combined).
      - skills.sh already discovers `skills/<category>/<name>/SKILL.md`.
      - Needs: the layout rule and tests (`skills/<name>/` assumed), the CI
        skill selector, the index generator (one index per group) and the
        `skills-index` CI job.
      Until then, a project can hide skills it doesn't want with opencode
      `skill` permission rules.
