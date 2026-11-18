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
  - Done 2026-11-18 (0.7.3, DevDocs node/zig/pony, CLI, Haiku, default
    effort): no-skill 5.5/9, web 7/9, skill 9/9; see
    `docs/trials/2026-11-18-haiku-node-zig-pony/`.
  - Still open: the opencode model set, `--mcp`, docsets.

#### 6. Deferred review items

- [ ] 6.9 Notes
  - [x] 6.9.2 No lock against concurrent writers of notes files (writes are
        atomic; last writer wins).
- [ ] 6.13 After the 0.6.1 reviews
  - [x] 6.13.12 Over MCP, hint lines in normal output still use CLI wording
        (`-d NAME picks one`, `raise --max-lines`, `show REF opens`);
        `explain()` runs only on error text, since rewriting output could
        change quoted doc text. This includes stderr notes such as the
        catalog network note naming `assets/allowlist.txt`.
  - [x] 6.13.18 A live temp older than one hour can be swept by a
        concurrent process (a long fts build or install). Won't fix: a live
        temp keeps a fresh mtime, and pid checks are unsafe on Windows.
  - [x] 6.13.21 The `ids` term is useless for `printf(3)` / `vector<int>`
        tokens.
  - [x] 6.13.25 A docvol whose index can't be read (a corrupt DevDocs
        `index.json` with `entry_count`, or a damaged docset index) stops
        every search over all docvols; warn and skip it there instead (one
        helper for every multi-docvol loop; `-d NAME` still exits 5).
  - [x] 6.13.26 "zzz: no DevDocs documentation matches 'zzz'" repeats the
        name after the new prefix.
  - [x] 6.13.27 Tests missing: meta.json untouched when `entry_count` is
        present; the docset folder survives a family `remove`.
  - [x] 6.13.28 `make_temp` and install's meta.json write can raise a raw
        OSError (not CacheError).
  - [x] 6.13.29 The catalog note order (after the list) and the
        second-list failure path are untested.
  - [x] 6.13.30 The MCP tool schema reads `p.default` directly, a second
        place that knows the default rule.
- [ ] 6.14 Better recovery for broken docvols (the user, 2026-11-17). 0.7.3
      only skips them with a warning and repair advice (DevDocs: `remove`
      then `install`; docsets: reinstall in Dash/Zeal). Examine: `install`
      re-downloading when index.json/db.json is damaged (today it says "up
      to date"), a `check`/`repair` command, verifying files after download.
      `list` does not warn for a DevDocs docvol whose meta.json entry_count
      masks a corrupt index.json (detecting it needs reading the index).
      When every docvol of a family is unusable, a notes write prints
      "wrote" and then exits 5 (or 2); warn after the write instead. A
      meta.json missing a key gives a cryptic "'slug'; repair with: ..."
      (prefix "unreadable meta.json"). `list` shows an unusable WAL docset
      as "0 entries" (with a warning); say "unusable" in the row instead.

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
