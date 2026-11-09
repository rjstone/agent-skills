# TODO

## Formats

- [ ] Claude Code plugin: `.claude-plugin/plugin.json` (+ `marketplace.json`)
      pointing at `skills/`; the skills CLI also reads these manifests.
- [ ] Claude desktop/web plugin (zip upload).
- [ ] opencode v2 plugin (and v1, if still worth it).
- [ ] Versioning, once a format with a version field exists.

## Skills

- [ ] `opencode-cli`, `opencode-api`, `opencode-console`: the other top-level
      sections of https://opencode.ai/docs/llms.txt, built like
      `opencode-build`. When the second one lands, share one refresh script
      (section name as an argument) instead of copying it.
- [ ] `opencode-build` `ERRATA.md`: record the doc mistakes already seen
      (verify each against the installed `@opencode/plugin` types).

## Automation

- [ ] Scheduled workflow: run each skill's `refresh_references.py` weekly and
      open a PR when the docs changed.

## Consumers

- [ ] The project where `opencode-build` started: decide how it uses the
      skill (install with `npx skills` vs keep a vendored copy), then remove
      or sync its own copy.
