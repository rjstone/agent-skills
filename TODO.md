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

- [ ] Bind `/etc/hosts` read-only by default: without it `localhost`
      doesn't resolve inside (SKILL.md says to pass `--ro /etc/hosts`).
- [ ] A working-directory option below `/work` (today: `sh -c 'cd ... &&
      exec CMD'`, as in `references/nested-agents.md`).
- [ ] sandbox.py's own errors exit 2, the same as a command that exits 2;
      consider a distinct status or a marker line on stderr.
- [ ] Started as root, `--rw` binds are checked only for read access by the
      sandbox user: a root-owned `--rw` folder passes preflight but is
      read-only inside. Check write access too, or chown it like `--work`.
- [ ] `--mem` is an address-space limit (`prlimit --as`); Node.js/V8
      reserves large virtual ranges, so it likely breaks Node agents such as
      opencode. Test, then document it or offer a cgroup-based limit.

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
