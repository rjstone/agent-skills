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
- [ ] `docshelf`: a read-only Dash/Zeal backend for docsets the user
      already has (from `skill/dash-docset` before it is archived). It
      downloads nothing and may be preferred over downloading the same
      documentation from DevDocs. Same CLI and MCP interface,
      equivalent search and FTS (the user, 2026-11-16).
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
  - backend interface before the Dash backend: add `display_name` to the
    Docvol base; a core installed-docvols aggregator; move href resolution
    into a backend hook; `shelf_lookup` imports `_warn` from the backend
  - tests: expected "skipping" warning leaks to test stderr; no tests for
    `name=`-only anchors, CRLF notes, no-command help exit 2
  - `show` reads the notes file twice via private `_read_notes`
- [ ] `docshelf`: from the Haiku trials with the earlier prompts (2026-11-16):
  - strip a footer repeated on every page (LÖVE's licence line), as the
    earlier skill's footer detection did.
  - notes headings cache: no format-version key (an old-format cache would
    be reused); `notes --check` skips pages that fail to render without
    saying how many; the `--grep X` -> `--grep=X` rewrite ignores `--`.

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
