# Plan: `.agents/skills/opencode-build` (cached opencode v2 Build docs)

## Context

An agent got confused about opencode tool/API naming (the `enter` / `tutor_enter`
episode), and the opencode v2 docs change fast and already contain mistakes.
Agents also fall back on v1 habits from training data. Goal: a repo-dev skill
that makes agents read the *current v2* Build docs before touching the plugin,
backed by a local cached copy that a script can refresh, plus a place to record
known doc mistakes that survives refreshes. First of a family that mirrors the
docs' top-level sections: `opencode-build` now; `opencode-cli`, `opencode-api`,
`opencode-console` later (TODO only).

Branch: `chore/harness-config` (exists, pushed, has `.claude/.gitkeep`,
`.opencode/.gitkeep`).

## Facts established (verified this session)

- `https://opencode.ai/docs/llms.txt` lists every v2 docs page under `## CLI`,
  `## Build`, `## API`, ... headings. The `## Build` section has 14 pages:
  intro, plugins/{overview, server, cli (TUI), gui, rpc, migrate-v1}, client,
  sdk, sdk/cloudflare, effect/{plugins, rpc, client, sdk}.
- Markdown form: canonical URL minus trailing `/` plus `.md`
  (`/docs/build/plugins/server/` -> `/docs/build/plugins/server.md`);
  `/index.md` only 302s. Cite the canonical URL without `.md`.
- Pages send `ETag`; `If-None-Match` returns `304`. Total ~310 KB (gui 125 KB,
  server 62 KB, effect 52 KB).
- Python stdlib `urllib` works through the sandbox proxy; `opencode.ai` is now
  on the environment allowlist.
- `.gitattributes` is `* text=auto` -> CRLF on Windows checkouts, so content
  comparisons must normalize line endings.
- No page trips CI's drive-letter guard. Pages do contain `/absolute/path/...`
  examples, so AGENTS.md "Paths" needs a verbatim-upstream exception for them.

## Layout

```
.agents/skills/opencode-build/
  SKILL.md                      router: trigger description + task -> reference table
  ERRATA.md                     known doc mistakes (hand-maintained, never refreshed)
  references/
    manifest.json               per page: url, md_url, etag, sha256 (LF-normalized), fetched
    intro.md
    plugins.md  plugins-server.md  plugins-cli.md  plugins-gui.md
    plugins-rpc.md  plugins-migrate-v1.md
    client.md  sdk.md  sdk-cloudflare.md
    plugins-effect.md  plugins-effect-rpc.md  client-effect.md  sdk-effect.md
  scripts/
    refresh_references.py       stdlib-only, cross-platform
```

File name = path after `/docs/build/`, `/` -> `-`; the intro page -> `intro.md`.
References are verbatim (no added header) so hashes compare cleanly; the source
URL lives in `manifest.json` and the SKILL.md table.

## `scripts/refresh_references.py`

`python .agents/skills/opencode-build/scripts/refresh_references.py [--check] [--force] [--prune]`

1. Fetch `docs/llms.txt`, take the links under `## Build` (up to the next `## `).
   The page list comes from the index, so new pages are picked up automatically.
2. For each page, a GET on its `.md` URL with `If-None-Match: <manifest etag>`
   (skipped with `--force`). `304` -> unchanged. `200` -> LF-normalize, sha256,
   write only if the hash differs (`newline="\n"`, UTF-8).
3. Pages in the manifest but no longer in the index -> reported as removed;
   deleted only with `--prune`.
4. Update `manifest.json` (sorted keys, stable output -> clean diffs).
5. Print a summary: new / updated / removed / unchanged. For every updated page
   that has `ERRATA.md` entries, print "re-check errata: <ids>".
6. `--check`: no writes; exit 1 if anything would change (so a human or a
   scheduled job can see staleness). Network errors exit 2 with the URL.
7. Structure: pure functions (`parse_section`, `page_file`, `normalize`,
   `plan_updates`) plus one injectable `fetch(url, etag)`, so tests run offline.
   Generic User-Agent, no credentials. urllib honors `HTTPS_PROXY`.

## `SKILL.md` (draft shape, < 500 words)

- Frontmatter: `name: opencode-build` (spec form: lowercase, matches folder, so
  every harness that scans `.agents/skills` accepts it); single-line
  `description: Use when writing or changing an opencode v2 plugin (server, TUI,
  GUI or RPC part, @opencode/plugin, Plugin.define, hooks, tools, MCP
  registration), using @opencode/sdk or the JavaScript client, migrating a v1
  plugin, or unsure whether an opencode API is v1 or v2.`
- Body:
  - Core rule: opencode v1 and v2 differ; answers from memory are probably v1.
  - **Before** writing plugin code, read the matching reference.
  - Trust order when sources disagree: the installed `@opencode/plugin` types
    (`node_modules/@opencode/plugin`, pinned 2.2.5) > `ERRATA.md` > `references/` > memory.
  - Task -> reference table (e.g. add a tool or hook -> `plugins-server.md`;
    package.json `exports` -> `plugins.md`; v1 code -> `plugins-migrate-v1.md`).
  - Stale or missing page -> run the refresh script; live page = `.md` URL rule above.
  - When citing, use the canonical URL without `.md`.
  - Found a doc mistake -> add an `ERRATA.md` entry (never edit `references/`).
- `ERRATA.md` entry shape: `E01`, page file, what the doc says, what is
  actually true, evidence (type path / test / commit), date checked. Seeded with
  the mistakes you have seen (you name them; I verify each against the 2.2.5 types).

## Repo integration

- `AGENTS.md`:
  - Layout: `.agents/skills/` = repo-dev skills (not shipped; `skills/` is what the
    plugin ships to students). Harnesses that don't scan `.agents/skills`
    (Claude Code reads `.claude/skills`) should read the SKILL.md there when its
    description applies.
  - Paths: add the exception `.agents/skills/*/references/` (verbatim upstream copies).
  - Rule: never hand-edit `references/`; refresh with the script; mistakes go to `ERRATA.md`.
- **No CI changes, no committed tests.** This repo is a temporary home: the
  skills, with their tests and CI, move to a dedicated shared skills repo next.
- `.claude/.gitkeep` and `.opencode/.gitkeep` stay (nothing goes there yet).
- Future TODO: `opencode-cli`, `opencode-api` and `opencode-console`, recorded in
  AGENTS.md. The script takes the section name as a constant, so they can copy it
  or share it later.

## Process (writing-skills TDD)

1. **RED baseline:** fresh subagents *without* the skill (3 scenarios, a few reps):
   - (a) "add a tool to this repo's plugin server part": does it use v1 API shapes
     (`@opencode-ai/plugin`, `export const X: Plugin = async (...)`, the `tool()` helper)?
   - (b) Retrieval: which `package.json` export key the TUI part uses.
   - (c) Loading a local plugin from `opencode.jsonc`.
   - Record the failures verbatim.
2. Write the script plus its tests first (TDD), run the first refresh, and commit
   the references and the manifest.
3. **GREEN:** write SKILL.md and ERRATA.md against the baseline failures; re-run
   the same scenarios *with* the skill.
4. **REFACTOR:** close the gaps found, re-test, check word count.

## Tests (offline, NOT committed here)

- Written and run only in the session scratchpad
  (`<scratchpad>/opencode-build-tests/test_refresh.py`, which loads the script
  by path). They are kept ready to move into the future skills repo and its CI.
  They use a fixture llms.txt and a fake fetcher:
  - section parsing, including stopping at the next `##`
  - file naming, including intro
  - a 304 keeps the file
  - a changed body writes it
  - CRLF/LF compare equal
  - removed pages are reported, and deleted only with `--prune`
  - `--check` exit codes
  - errata re-check listing
- **Integrity test (same module)**, checking the committed tree:
  - every `references/*.md` is in the manifest, and the reverse
  - each sha256 matches the LF-normalized file, which catches hand edits
  - every reference is linked from SKILL.md
  - the frontmatter is valid

## Verification

- The scratchpad tests pass. The existing repo suites and `bun test` still pass,
  and CI's drive-letter guard stays green with the new references.
- Run the script twice: the first run downloads 14 pages; the second reports
  14 unchanged (all 304).
- Run `--check`: it should exit 0.
- Simulate an edited page (fake fetcher in the tests) and a hand-edited reference
  (the integrity test fails).
- Re-run the subagent scenarios with the skill present: they read the reference
  and produce v2 code and correct answers.
- Push the branch and report. CI is unchanged, so it only re-runs the existing checks.

## Suggested extras (approve or drop individually)

1. **`ERRATA.md`** (above): recommended, since refresh would otherwise wipe corrections.
2. **Integrity test** (above): recommended; it enforces "never hand-edit
   references". It lives in the scratchpad for now, then moves to the skills repo.
3. **Scheduled refresh workflow:** belongs in the future skills repo, not here.
4. **Shared script:** when `opencode-api` arrives, move the script to
   `.agents/scripts/refresh_opencode_docs.py <section>`. Deferred.
