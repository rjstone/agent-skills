# agent-skills

One skill pack shared by several projects and agent harnesses (Claude Code,
opencode, Codex, Cursor and others).

## Instruction files

Everything that is not specific to one harness lives here in `AGENTS.md`:
layout, commands, workflow, conventions. `CLAUDE.md` holds only Claude Code
notes and imports this file with `@AGENTS.md`. Agents other than Claude treat
`CLAUDE.md` as read-only and put their notes here or in their own vendor file.
Keep this paragraph (and its twin in `CLAUDE.md`) when editing either file.

## Public repo: what may be committed (the user, 2026-11-08)

This repository is public. Anything sensitive, too specific to one person or
machine, or half-baked stays out. A new skill (or a change to one) is
committed only when it meets all of these:

1. **Generally useful** to many people, not just one project or one person.
2. **No machine or account details:** no user or account names, hostnames,
   personal email addresses, home-directory paths, private repo names or
   internal URLs. Use placeholders (`<user>`, `~`, `$HOME`, `%USERPROFILE%`,
   `user@example.com`) and paths relative to the skill.
3. **No secrets:** no passwords, tokens, API keys, private keys or
   credentials of any kind, not even expired or "test" ones.
4. **Reasonable quality** by the Agent Skills standard
   (https://agentskills.io/specification) and the obra/superpowers
   `writing-skills` checklist: a "Use when..." trigger description, tested
   against agents with and without the skill, concise, no narrative.
5. **Original to this repo:** skills that started elsewhere (third-party
   packs, even with local edits) stay out. Point to their upstream instead,
   and send improvements there as a PR. Check a skill's frontmatter
   (`metadata.author`, `license`) and footer for its origin before adding it
   (the user, 2026-11-08).

Before committing: run the tests (`tests/test_public_safety.py` catches the
mechanical cases of 2 and 3) **and** read the whole diff for anything the
patterns can't see. When in doubt, leave it out; keep personal or
project-specific skills in that project's own repo.

## Paths: no machine or account details

Everything committed must work for any account on any machine.

- Never write a user name, account name or machine name into the repo.
- Never write an absolute path that starts with a drive letter (`C:`, `D:`,
  ...) or with `/`. Start absolute paths from a standard location variable
  instead:
  - Windows prose: `%USERPROFILE%`, `%APPDATA%`, `%LOCALAPPDATA%`,
    `%ProgramFiles%`
  - PowerShell: `$env:USERPROFILE`, `$env:APPDATA`, `$env:LOCALAPPDATA`,
    `$env:ProgramFiles`, in double quotes (single quotes don't expand)
  - Linux/macOS: `~/`, `$HOME`; in CI, `$RUNNER_TEMP`
- Inside a skill, use paths relative to the skill's folder (`scripts/x.py`,
  `references/y.md`): the skill is installed in different places by
  different harnesses.
- Exceptions:
  - system locations that have no variable (`/Applications/...` on macOS)
  - verbatim upstream copies (`skills/*/references/`), which keep their own
    example paths
  - made-up fixture paths in `tests/`
- `tests/test_public_safety.py` fails on drive-letter paths and on home paths
  with a real-looking account name; other `/` paths need the diff review.

## Layout

Follows the layout of `obra/superpowers` (a popular pack that supports several
vendors' plugin formats):

- `skills/<name>/SKILL.md` - one folder per skill; `<name>` is lowercase with
  hyphens and equals the frontmatter `name`. Optional `references/` (Markdown
  the skill links to), `scripts/` (tools the skill runs; invoke them through
  their interpreter, e.g. `python scripts/x.py`).
- `tests/` - stdlib `python3` `unittest` tests. `test_skills.py` checks every
  skill (the frontmatter standard below, name = folder, single-line
  `description` starting "Use when", every `references/*.md` linked from
  `SKILL.md`, no nested `SKILL.md`); `test_public_safety.py` scans every tracked file for secrets,
  personal emails, account home paths and drive-letter paths; per-skill
  tests are `test_<skill>.py`.
- `.github/workflows/ci.yml` - runs the tests and checks that the skills CLI
  (`npx skills add . --list`) discovers every skill. No network in the tests.
- `docs/plans/` - finished plans (`YYYY-MM-<topic>.md`).
- `TODO.md` - open work. `BUGS.md` - upstream bugs (create when needed).

Run the tests from the repo root: `python3 -m unittest discover -s tests -v`.

## Skill frontmatter (the user, 2026-11-08)

Format: the Agent Skills specification,
https://agentskills.io/specification.md (index of all its pages:
https://agentskills.io/llms.txt). Every `SKILL.md` in this repo starts with
these fields, in this order:

```yaml
---
name: <skill-name>
description: <triggering conditions only, starting "Use when">
compatibility: <only if the skill needs an atypical environment>
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---
```

- Required here: `name`, `description`, `license`, and `metadata` with
  `author`, `source` and `version`. Add co-authors to `author`, separated
  by commas.
- `version` is a quoted `"X.Y.Z"` string (metadata values are strings).
  New skills start at `"0.1.0"`.
- `compatibility` (1-500 characters) only when it's worthwhile: system
  packages or tools that usually aren't installed (Xvfb, ImageMagick,
  tkinter), network access a script needs, or one intended product. Leave
  it out for things nearly everyone has (Python, git, a shell).
- License and attribution live only in the frontmatter: no license or
  "maintained by" prose in the body.

## Skills

- `opencode-build` - opencode v2 Build docs (plugins, client, SDK) cached as
  Markdown in `references/`, with `scripts/refresh_references.py` to update
  them and `ERRATA.md` for known doc mistakes. Never hand-edit `references/`
  (a test compares each file with its hash in `references/manifest.json`).
  Started in the project that first needed it; that copy stays until this
  repo is set up and tested (the user, 2026-11-08).

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
