# TODO

## Formats

- [ ] Claude Code plugin: `.claude-plugin/plugin.json` (+ `marketplace.json`)
      pointing at `skills/`; the skills CLI also reads these manifests.
- [ ] Claude desktop/web plugin (zip upload).
- [ ] opencode v2 plugin (and v1, if still worth it).
- [ ] Versioning, once a format with a version field exists.

## Skills

- [ ] `decisions`: image input and `box` questions (TypeSafe `assets`,
      Perplexity image parts).
- [ ] `decisions`: after 2027-05-23, re-check the Vercel sample adapter
      (`scripts/adapters/vercel_evaluate.py`) with a live call, sooner if
      Vercel announces an AI Gateway `/v1/evaluate` change; update its
      "Checked live" date.
- [ ] `decisions`: after 2027-05-23, re-check the Levanto Sage sample
      adapter (`scripts/adapters/levanto_sage.py`) with a live call, sooner
      if Levanto announces a `/decide/batch` change; update its "Checked
      live" date.
- [ ] Docs-cache skills copy their refresh script (each skill must stand
      alone when installed). If they drift, generate the copies from one
      template instead of hand-editing each.
### opencode skills

Moved to https://github.com/rjstone/opencode-dev-plugin (its TODO.md), 2026-11-28.

### docshelf

Moved to https://github.com/rjstone/docshelf-plugin (its TODO.md), 2026-11-28.

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
