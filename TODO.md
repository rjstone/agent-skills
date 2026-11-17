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
- [ ] `docshelf`: skim other docset and DevDocs readers for ideas (list
      gathered 2026-11; the user wants to look through them later).
      Read Zeal's folder, no network:
      https://github.com/andreas-mausch/docset-mcp (Rust, list/search/page),
      https://github.com/keturn/ZDocsetMCP (Python, MIT, many tools incl.
      cheat sheets, entries by type),
      https://github.com/erno-szabados/zealmcp (Python, MIT, tiny).
      Downloads docsets itself (via Zeal's catalog):
      https://github.com/bbsvip/docset-mcp.
      macOS / Dash only: https://github.com/Kapeli/dash-mcp-server,
      https://github.com/codybrom/DocsetMCP,
      https://github.com/joshuadanpeterson/enhanced-dash-mcp,
      https://github.com/Robdel12/doc-fetcher-mcp,
      https://github.com/nzrsky/appleref-mcp.
      DevDocs-based: https://github.com/maxwhipw/devdocs-mcp,
      `@madhan-g-p/devdocs-mcp-server` (npm). Non-MCP: dasht, and Zeal's
      `zeal python:pprint` (opens the GUI). These are also candidates for
      `references/dash-zeal.md`'s "check for an existing MCP server first".
- [ ] `docshelf`: agent trials as dash-docset ran them (no-skill baseline,
      Haiku, the opencode model set, CLI vs `--mcp`): fine-tuning after v1
      (the user, 2026-11-16).
- [ ] `docshelf`: writing notes over MCP (v1's `notes` tool is read-only).
- [ ] `docshelf` (low priority, with the Dash/Zeal backend): some docsets'
      `Info.plist` has a full-text-search flag (keys to verify; possibly
      `DashDocSetDefaultFTSEnabled` / `DashDocSetFTSNotSupported`). Find out
      whether such docsets ship their own text index that `fts` could use
      instead of building one, and whether "not supported" should skip
      indexing (the user, 2026-11-16).
- [ ] `docshelf`: deferred from the v1 reviews:
  - link hrefs with `?query` or percent-encoding get no REF; `..` past the
    docvol root clamps silently
  - fts: punctuation-only query tokens zero the results; snippet highlights
    only "return" for `return_exceptions` (unicode61 splits on `_`);
    `--max-lines` < 3 overshoots by one line
  - `sources` lists duplicate slugs (bun, vitest) twice; de-duplicate,
    keeping the first row
  - real `fetch()` untested (UA, redirects, error mapping): add a loopback
    `http.server` test
  - 404 from documents.devdocs.io still shows the allowlist hint
  - same-mtime reinstall trusts `meta.json` without checking files exist;
    page index built twice at install
  - temp files from `mkstemp` are mode 0600, so cache files lose the umask
    permissions (matters only for a cache shared between users); a process
    killed mid-build leaves a random-named `*.tmp` behind, which nothing
    cleans up
  - every command parses each installed docvol's `index.json` for
    `entry_count`; store the count in `meta.json` at install
  - MCP: error text still says "(see: docshelf.py list)" and CLI flag
    names; `initialize` has no "instructions"; `"id": null` treated as a
    request; batch arrays rejected while 2025-03-26 is advertised;
    `_parser_defaults` reads argparse private attributes
  - tests: expected "skipping" warning leaks to test stderr; no tests for
    `name=`-only anchors, CRLF notes, no-command help exit 2
  - `show` reads the notes file twice via private `_read_notes`
- [ ] `docshelf`: deferred from the Dash/Zeal backend (0.4.0) reviews:
  - WAL stamp uses whole-second mtimes; the stamp test only checks for "-"
  - containment tests cover `..` only (no absolute or backslash paths);
    `resolve()` scans entries linearly per id
  - plist and `_index_page` reads catch bare `Exception`
  - tarix: no tests for symlink/dir members or a truncated archive; the
    containment-before-lookup test isn't discriminating; `resolve_href`
    turns exit-7 errors into None silently; the tarix index is opened and
    its prefix probed per lookup (cache the prefix per docvol)
  - `where` prints `[source]` only for existing folders; `where_lines` and
    `installed_docvols` each open every docset
  - `repeats.json` items not type-checked on read; `REPEAT_FORMAT` bumps
    don't invalidate the fts/headings indexes (bump `FTS_FORMAT` and
    `HEADINGS_FORMAT` by hand); no tests for its cache reuse, stamp
    rebuild, plist keeper page or write-failure warning
  - lazy `import shelf_backends` in 3 functions; no
    test for remove/update with a family name matching both kinds; `list`
    repeats "also as" per pair
  - the "came from Zeal's catalog" note prints once per list when both
    fall back (the catalog itself is fetched once); one malformed `versions` entry discards the whole catalog with an
    unclear note; unused loop variables in `cached_catalog_match`; no tests
    for catalog cache expiry, malformed JSON or the MCP text of the new
    NetError; a stale GitHub cache isn't reused when a refetch fails
  - the long first line of SKILL.md's body

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
