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

- [ ] `dash-docset`, after its first version (the user, 2026-11-14):
      - semantic search, which needs its own index over page text and
        probably an embedding model (a dependency or a network service);
        the first version has only SQLite FTS5 full-text search.
      - MCP server mode for the script, once the CLI commands have settled.

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
