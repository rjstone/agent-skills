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
    effort): no-skill 5.5/9, web 7/9, web via MCP 7.5/9, skill 9/9; see
    `docs/trials/2026-11-18-haiku-node-zig-pony/`.
  - Done 2026-11-18 (0.7.3, same trial, `--mcp` only, Haiku, default effort):
    9/9; docshelf calls about 1.6-2.4k tokens per 3 questions against
    3.4-5.6k for the skill; see its "docshelf MCP arm".
  - Done 2026-11-18 (0.8.0, Zig questions, opencode 2.3.0, eight models
    from nemotron-3-super-120b up, prompt not naming the skill): 8/8 answered
    3/3; 7 loaded docshelf, nemotron-3.5-super-vl grepped the cache files;
    see `docs/trials/2026-11-18-opencode-docshelf-zig/`.
  - Done 2026-11-18 (0.8.0, zig/node/pony/HTTP docset, same eight models,
    bubblewrap sandbox): seven answered all four sets; see
    `docs/trials/2026-11-18-opencode-docshelf-sandboxed/`.
  - Still open: a docsets-only trial with more docsets.

#### 6. Deferred review items

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

#### 7. Output size

(none open; 7.1-7.7 done in 0.7.4-0.8.2, results in
`docs/trials/2026-11-18-haiku-node-zig-pony/` and
`docs/trials/2026-11-18-opencode-docshelf-sandboxed/`)

#### 8. Import formats (the user, 2026-11-21)

Goal: import more documentation formats into docshelf's own docvol format
(no need to write Dash docsets). Source: Kapeli's docset generation guide,
https://kapeli.com/docsets (read 2026-11-21). Most of its entries are doc
*generators* whose HTML a converter (doc2dash, javadocset, ...) scrapes
into a docset; most generators also write a machine-readable search index
beside the HTML, which is the better import source. The "Index to read"
column is from memory: verify each against real output before building.

| # | Generator | Dash's converter | Index to read instead | Value |
|---|---|---|---|---|
| 1 | Swift DocC | built into Dash | `.doccarchive`: `index/index.json` + RenderNode JSON (needs brotli, see Reference below) | low (no stdlib brotli) |
| 2 | Sphinx / PyDoctor | doc2dash | `objects.inv` (Intersphinx inventory, zlib, stdlib-readable) | high |
| 3 | Javadoc | javadocset | `*-search-index.js` (members, types, packages; JDK 9+) | high |
| 4 | RDoc / YARD | built into Dash | RDoc `search_index.js`; YARD `class_list.html` / `method_list.html` | low-medium |
| 5 | Scaladoc | sbt-dash, mkscaladocset | `searchData.js` (Scala 3) | low-medium |
| 6 | GoDoc | godocdash | none static; scrape HTML or `go doc` | low |
| 7 | ExDoc (Hex) | built into Dash | `search_data-*.js`, `sidebar_items-*.js` | medium |
| 8 | dartdoc | built into Dash | `index.json` | medium |
| 9 | Haddock | built into Dash | Hoogle text database (`--hoogle`) | medium |
| 10 | rustdoc / Cargo | cargo-docset, rsdocs-dashing | `search-index.js` (format changes often; JSON output nightly-only) | medium, fragile |
| 11 | JSDoc | jsdoc-dash-template | `jsdoc -X` JSON (TypeDoc: `--json`) | medium-high |
| 12 | Doxygen | doxygen2docset | tagfile (XML, `GENERATE_TAGFILE`) or XML output | high |
| 13 | any HTML | Dashing, dash-docset-builder | CSS selector -> entry type config (Dashing's `dashing.json`) | high (fallback) |

- [x] 8.1 `objects.inv` importer: done 2026-11-21 as the `docshelf-build`
      skill 0.1.0 (#29) plus docshelf 0.9.0 (#30). Deferred minors from
      its final review: robots.txt 5xx/network counts as allow-all and
      `objects.inv` is not checked against robots.txt; the final file
      swap is not Ctrl-C-safe; `build docs` in a folder with `docs/` is
      taken as a SOURCE; docshelf `remove` cannot remove a damaged built
      docvol; `install` of a built name from the project list prints the
      "installed" note.
- [ ] 8.2 Generic HTML importer driven by CSS selectors, Dashing-style;
      maybe read existing `dashing.json` files.
- [ ] 8.3 Javadoc search indexes.
- [ ] 8.4 Doxygen tagfile.
- [ ] 8.5 MkDocs `search/search_index.json` (not on Kapeli's list; common
      on current project sites; full text and headings, no API types).
- [ ] 8.6 The rest of the table, by value.
- [ ] 8.7 Map every importer onto Dash's entry types (guide section
      13.5.1) so `types` means the same thing across sources.
- [ ] 8.8 Look at Crawl4AI (https://github.com/unclecode/crawl4ai,
      v0.9.6, 2026-11-20) for fetching docs that have no downloadable
      archive: `pip install -U crawl4ai`, `crawl4ai-setup` (browser),
      `crwl <url> -o markdown`, `crwl <url> --deep-crawl bfs --max-pages N`.
      A heavy, optional dependency (Playwright + Chromium) against the
      stdlib-only policy: keep it outside docshelf's core (a separate
      fetch step whose output docshelf imports) (the user, 2026-11-21).
- [x] 8.9 llms.txt sites: docshelf-build 0.2.0 (every listed page kept in
      full, page cache, per-page `signals`). Live trial 2026-11-21:
      opencode.ai 90 pages (88 built, 2 social links on other hosts
      failed), docs.langchain.com 1,407 pages in a 4-level tree, its
      `build/python.txt` sub-index 240/240 built.
- [x] 8.11 Done in docshelf-build 0.3.0 (`classify`; spec
      `docs/superpowers/specs/2026-11-22-docshelf-build-classify-design.md`).
      Reference-vs-guide classifier for built docvols (both kinds): a
      separate step that reads `pages.<key>.signals` (and the cached raw
      pages) and writes `keep` and `why: "model:<id>"` into the plan, which
      re-planning keeps. Options: cheap thresholds, an embedding classifier
      trained on Sphinx-built role labels, or a decision model. Signal
      spread from the 0.2.0 trial (min / median / max): opencode `words`
      138 / 676 / 22480, `code_ratio` 0 / 0.26 / 0.72, `you_per_1k`
      0 / 7.1 / 57.5; LangChain Python `words` 157 / 1274 / 16478,
      `code_ratio` 0 / 0.33 / 0.90, `you_per_1k` 0.5 / 8.5 / 45.2,
      `signature_lines` 0 / 9 / 236 (the user, 2026-11-21).
- [ ] 8.12 docshelf-build llms.txt follow-ups (0.2.0 reviews and trial):
      links to other hosts (discord.gg, x.com) are planned as pages and
      fail; `humans.txt` is followed as a sub-index (0 pages); `.md` retry
      URL ignores a query string; blockquote lazy continuation and a few
      MDX tag heuristics (prefix match on `</Name`, list-continuation
      indented code); duplicated meta/types code in `build_docvol.py`.
      Quadratic emphasis parsing on hostile paragraphs (`build_markdown`).
      Deep nesting recursion is capped only by the per-page convert guard.
      `on*=` attributes and `javascript:` hrefs pass through `_serialize`
      (inert in docshelf's text renderer). A local root listing only
      sub-indexes gives an empty `main_host`.
- [ ] 8.10 Finding Sphinx docs for a library: the best way to search for
      a project's `objects.inv` site. Ideas: hosting domains with a search
      API (Read the Docs), or a list of docs-hosting domains to restrict a
      general web search to (`readthedocs.io`, `github.io`, ...); maybe
      PyPI `project_urls` "Documentation" (the user, 2026-11-21, PR #29
      review).
- [ ] 8.13 docshelf-build bulk downloads: when a site offers its docs as
      one archive (zip or tgz: Read the Docs "Downloads" HTML zip, a
      project's release docs tarball), fetch that once instead of page by
      page, and have `detect` report it (the user, 2026-11-22).
- Ignore Dash-only extras: `dashtoc`, playground URLs, docset feeds
  (`dash-feed://`), per-docset JavaScript and full-text-search switches.

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

### provider-onboarding

Follow-ups from PR #20 (0.6.0, five rounds of Haiku trials):

- [ ] OpenAI's TTS models (`tts-1`, `gpt-4o-mini-tts`) aren't under `openai`
      in models.dev, so `-p openai -m tts-1` has no model type and gets chat
      snippets. An override with a `models` list, or a note in SKILL.md.
- [ ] Providers only LiteLLM knows (e.g. Fireworks, Together for Kimi K2
      Instruct) aren't listed: the card is built from models.dev.
- [ ] A compact summary mode: `--limit 100 --litellm --portkey` can print
      thousands of lines; agents grep it.
- [ ] Check recursive-providers' `key_url` values (CC0) and add them to the
      overrides as `signup_url` with a verified date.
- [ ] Flag odd-precision prices (currency conversion, e.g. $0.57971).

### sandboxing

- [ ] A real memory limit (resident memory, whole process tree): `--mem` is
      `prlimit --as` (address space), which Node.js needs 768 MB+ of just to
      start (0.2.0 warns and documents it). Options: a cgroup v2
      `memory.max` when delegated, or `systemd-run --scope -p MemoryMax=`.

## Automation

- [ ] Scheduled workflow: run each skill's `refresh_references.py` weekly and
      open a PR when the docs changed.

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
