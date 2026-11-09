# agent-skills

One skill pack shared by several projects and agent harnesses (Claude Code,
opencode, Codex, Cursor and others).

## Instruction files

Everything that is not specific to one harness lives here in `AGENTS.md`:
layout, commands, workflow, conventions. `CLAUDE.md` holds only Claude Code
notes and imports this file with `@AGENTS.md`. Agents other than Claude treat
`CLAUDE.md` as read-only and put their notes here or in their own vendor file.
Keep this paragraph (and its twin in `CLAUDE.md`) when editing either file.

## Layout

Follows the layout of `obra/superpowers` (a popular pack that supports several
vendors' plugin formats):

- `skills/<name>/SKILL.md` - one folder per skill; `<name>` is lowercase with
  hyphens and equals the frontmatter `name`. Optional `references/` (Markdown
  the skill links to), `scripts/` (tools the skill runs; invoke them through
  their interpreter, e.g. `python scripts/x.py`).
- `tests/` - stdlib `python3` `unittest` tests. `test_skills.py` checks every
  skill (frontmatter, name = folder, single-line `description` starting
  "Use when", every `references/*.md` linked from `SKILL.md`, no nested
  `SKILL.md`); per-skill tests are `test_<skill>.py`.
- `.github/workflows/ci.yml` - runs the tests and checks that the skills CLI
  (`npx skills add . --list`) discovers every skill. No network in the tests.
- `docs/plans/` - finished plans (`YYYY-MM-<topic>.md`).
- `TODO.md` - open work. `BUGS.md` - upstream bugs (create when needed).

Run the tests from the repo root: `python3 -m unittest discover -s tests -v`.

## Skills

- `opencode-build` - opencode v2 Build docs (plugins, client, SDK) cached as
  Markdown in `references/`, with `scripts/refresh_references.py` to update
  them and `ERRATA.md` for known doc mistakes. Never hand-edit `references/`
  (a test compares each file with its hash in `references/manifest.json`).
  Moved here from `rjstone/thonny-opencode-tutor` `.agents/skills/` (that copy
  stays until this repo is set up and tested; the user, 2026-11-08).

## Decisions (the user, 2026-11-08)

- **Formats:** ship for skills.sh (`npx skills add rjstone/agent-skills`) first.
  It discovers `skills/<name>/SKILL.md` directly, so no manifest is needed.
  Other formats are in `TODO.md`.
- **One pack**, not a marketplace of separate plugins.
- **No symlinks** (Windows needs admin or Developer Mode for them). Keep one
  real `skills/` tree; a format that needs files elsewhere points its manifest
  at `skills/`, or a script generates the copy. Never link.
- **Tests:** stdlib `python3` `unittest` plus GitHub Actions.
- **Git:** commit straight to `main`; use a branch only for large changes.
- **Versioning:** no releases yet; skills.sh installs from the default branch.
  Add versioning with the first plugin format that has a version field.

## Formats (status)

- skills.sh (`npx skills`) - **supported** (https://github.com/vercel-labs/skills,
  discovery rules in its `docs/creating-skills.md`).
- Claude Code plugin (`.claude-plugin/plugin.json` / `marketplace.json`) - TODO.
- Claude desktop/web plugins - TODO.
- opencode v1/v2 plugins - TODO.

## Standing policies

- **Dependencies:** prefer the language's standard library and no install
  step, so any harness, container or fresh machine runs the code as is. Add a
  dependency only when it clearly earns its keep, and note why here.
- **Secrets:** never print, `cat` or otherwise read a key file, token or
  passphrase into context, and never put one in a commit, log or message;
  check existence with `ls -l` or `wc -c` only. If one reaches the context,
  say so at once and tell the user to rotate it. Commit secrets only
  encrypted (e.g. GnuPG symmetric `<name>.pgp` plus a small encrypt/decrypt
  script); decrypted copies are git-ignored and mode 600.
- **Pushes:** if a push is rejected with "fetch first", rebase your unpushed
  commits onto the remote (`git pull --rebase`) and push again. Never
  force-push over someone else's commits.
- **Notes:** when a session finds a new fact, quirk or workaround, write it
  here (or in `CLAUDE.md` if Claude-only) before the session ends. Mark the
  user's decisions with who and when, e.g. "(the user, 2026-11-08)".
- **Plans:** finished plans go in `docs/plans/YYYY-MM-<topic>.md`.
  "Archiving the plan" means: once the work is done, copy the working plan
  there, remove the original, commit and push.
