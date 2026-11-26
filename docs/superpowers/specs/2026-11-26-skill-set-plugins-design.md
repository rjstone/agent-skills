# Skill-set plugins - design

Status: for the user's approval (2026-11-26). Reviewed by a builder check.

## Intent

Offer this repo's skills as **plugins, one per use case** ("skill set"), so a
user installs only the skills for the job they do, in whichever harness they use.
Every plugin is listed in the single, pointer-only marketplace
`rjstone/plugin-marketplace`. agent-skills may also carry its own local
marketplace; that is harmless as long as the central one works.

First sets (the user, 2026-11-26):

| Plugin | Skills |
|---|---|
| `opencode-dev` | opencode-build, opencode-cli, opencode-api, opencode-console |
| `docshelf` | docshelf, docshelf-build |
| `special-agents` | provider-onboarding, decisions |

Skills not in a set stay installable on their own (skills.sh, the opencode
HTTP catalog) exactly as today.

## Goals

- One plugin per set, each listing only its skills.
- Sets are defined **by reference**: every skill stays in `skills/<name>/`.
  No copies of skills in the repo, generated or not, and no symlinks.
- skills.sh (`npx skills add rjstone/agent-skills`) keeps working.
- opencode users can pick plugins by set, not only "all skills in the repo".
- The sets are written once; everything else is generated from that file and
  checked for staleness in CI.

## Non-goals

- Moving skills into `plugins/<set>/skills/` (approach B, the fallback only).
- npm publishing (phase 3).
- Cursor (deferred in plugin-marketplace), Copilot, Gemini and other harnesses
  beyond what the Claude catalog already gives them for free.
- Per-plugin version tags. All sets share the repo's release tags.

## Anti-goals (failure even if it "works")

- A plugin that silently loads every skill in the repo.
- Any change that breaks `npx skills add rjstone/agent-skills`, the existing
  opencode HTTP catalog URL (`.../main/skills/`), or CI's per-skill selection.
- A second copy of a skill that can drift from `skills/<name>/`.

## Constraints and findings

Verified with a throwaway test (2026-11-26, Claude Code 2.1.332, skills CLI
from npx), using a fake repo with skills `a b c d`:

| Case | Result |
|---|---|
| Claude, remote `url` source at the repo root + `skills: ["./skills/a","./skills/b"]` | loads **a, b, c**: an entry's list *adds to* the default `skills/` scan |
| Claude, remote `git-subdir` source, `path: "skills"`, `skills: ["./a","./b"]` | loads **a, b only**: the plugin root is `skills/`, whose default scan (`skills/skills/`) doesn't exist |
| Claude, local marketplace `source: "./skills"`, `skills: ["./a","./b"]` | loads **a, b only** |
| `claude plugin validate` on such a marketplace | passes |
| `npx skills add <repo> --list` with that local marketplace | every skill listed once, grouped by plugin ("Set Ab", "Set C"), unassigned skills under "General" |

Other facts this design rests on:

- Claude plugin component paths must start with `./` and may not contain
  `..`; with no `plugin.json` behind an entry, the entry is the manifest.
- skills.sh reads `.claude-plugin/marketplace.json` plugin `skills` lists, but
  has no per-plugin install; users select with `--skill <name>`.
- The opencode HTTP catalog fetches `<url>/<name>/<file>`, so a per-set
  catalog would need per-set copies. Not usable here.
- An opencode v2 server plugin can add skills from code:
  `ctx.skill.transform(editor => editor.add({id, name, description, path, content}))`
  (`skills/opencode-build/references/plugins-server.md`, "Skills").
- plugin-marketplace already maps `{type:'github', repo, path}` to a Claude
  `git-subdir` source pinned to the repo's highest `vX.Y.Z` tag, merges extra
  Claude fields from `claude: {...}`, and lists opencode entries as
  `{package, options}`.
- Codex was **not** tested (no CLI here).

## Approaches

- **A. Sets by reference (chosen, the user 2026-11-26).** Skills stay in
  `skills/`; each plugin's root is the `skills/` folder and its entry lists its
  skill folders. opencode gets one small TypeScript plugin whose options name
  the sets. No moves, no copies. Risk: depends on the harness honouring an
  entry-level skills list (verified for Claude and skills.sh; Codex unknown).
- **B. Move skills into `plugins/<set>/skills/<name>/`.** The most
  conventional layout and works everywhere, but breaks the catalog URL, CI's
  path selector, tests, docs and existing installs, and splits the repo into
  two layouts. Kept as the fallback if A fails a harness that matters.
- **C. CI builds per-set copies on a release branch.** Works everywhere, keeps
  `main` copy-free, but adds a second branch with its own tags, and copies
  still live in history. Rejected.

## Design

### Source of truth: `skill-sets.json` (repo root)

```json
{
  "marketplace": { "name": "agent-skills", "owner": { "name": "Robert Stone" },
                   "description": "Skill sets from rjstone/agent-skills" },
  "sets": [
    { "name": "opencode-dev", "description": "...",
      "skills": ["opencode-build", "opencode-cli", "opencode-api", "opencode-console"] },
    { "name": "docshelf", "description": "...", "skills": ["docshelf", "docshelf-build"] },
    { "name": "special-agents", "description": "...", "skills": ["provider-onboarding", "decisions"] }
  ]
}
```

Rules, enforced by the build script and tests: set names are lowercase
kebab-case and unique; every listed skill exists as `skills/<name>/SKILL.md`;
a skill may appear in more than one set (allowed, warned: installing both
plugins in Claude loads it twice); descriptions are present. A set may share
its name with a skill (e.g. the `docshelf` set): plugin and skill names are
separate namespaces in every harness (my call, 2026-11-26).

### Generator: `scripts/build_plugins.py`

Stdlib Python, same pattern as `scripts/build_skills_index.py`:
`python3 scripts/build_plugins.py` writes the outputs, `--check` exits 1 when
any is missing or stale. Outputs:

1. `.claude-plugin/marketplace.json` - the local marketplace. One entry per
   set: `"source": "./skills"`, `"skills": ["./<skill>", ...]`, `name`,
   `description`, and **no `version`** (Claude then follows the commit SHA; the
   central marketplace pins tags). Serves Claude Code (`/plugin marketplace add
   rjstone/agent-skills`), skills.sh grouping, and the other readers of
   Claude's format.
2. `opencode/sets.json` - `{ "<set>": ["<skill>", ...] }`, read by the opencode
   plugin at run time (keeps the plugin free of build steps).

No `plugin.json` files are generated: the entries are the manifests.

### opencode plugin: `opencode/` (phase 1: local only)

- `opencode/index.ts` (or `.js` if opencode won't load TS from a local path;
  builder checks with the opencode-build skill): a v2 server plugin built with
  `@opencode/plugin`. Options: `{ "sets": ["docshelf", ...] }`; an unknown set
  name is an error naming the known sets; no `sets` option loads nothing and
  logs why.
- For each skill in the chosen sets it reads `skills/<name>/SKILL.md` from the
  package/repo root, parses `name` and `description` from the frontmatter, and
  adds it with `ctx.skill.transform(... editor.add({id, name, description,
  path, content}))`, `path` pointing at the real file so the skill's relative
  `scripts/` and `references/` resolve.
- If a skill with the same id is already present (for example from the HTTP
  catalog), it is left alone and a log line says so, rather than replaced.
- A root `package.json` (`"private": true` until phase 3) names the package and
  its `files` (`opencode/`, `skills/`), so phase 3 publishes the real
  `skills/` folder with no copy in git.
- Phase 1 install: a local-path plugin entry in `opencode.json` with
  `options.sets`, as documented in the opencode-build references. Phase 1's
  plugin is for **verification only**: a short maintainer note in `AGENTS.md`
  covers it, and user-facing install docs wait for npm in phase 3. It must
  import nothing but `@opencode/plugin` (resolved from the host) and Node
  built-ins, so it needs no install step (my call, 2026-11-26).

### CI and tests

- `tests/test_plugins.py` (stdlib unittest, shared test, so it runs for every
  change): `skill-sets.json` is valid per the rules above, and
  `build_plugins.py --check` passes. Uses fixture repos for the rule failures.
- `ci.yml` runs `python3 scripts/build_plugins.py --check` on **every** push
  and PR, like the safety scan, not only when a skill is selected: a renamed
  or deleted skill or an edit to `skill-sets.json` must trip it. On pushes to
  `main`, the existing `skills-index` job also runs the generator and commits
  stale outputs, the same way it handles `skills/index.json` (my call,
  2026-11-26).
- `claude plugin validate .` in CI if the Claude CLI is cheap to install there;
  otherwise documented as a manual step.
- An opencode smoke test runs in the `sandboxing` skill's sandbox (as in
  AGENTS.md "Testing skills with small models"), loading one set and checking
  that only its skills are listed. Manual in phase 1.
- Adding a skill to a set, or changing `skill-sets.json`, does **not** need a
  skill version bump (the skills themselves don't change).
  `scripts/ci_changed_skills.py` treats `skill-sets.json`, `opencode/` and
  `.claude-plugin/` as shared files.

### Releases

- The repo gets `vX.Y.Z` release tags, starting with `v0.1.0` at the end of
  phase 1. All sets share them. Tagging is manual for now (the user tags, or
  asks an agent to). The notify workflow from plugin-marketplace
  (`docs/plugin-repo-release-workflow.yml`) is optional and phase 2.
- Skill `metadata.version` rules are unchanged; a repo tag is a snapshot, not a
  replacement for skill versions.

## Phases (the user, 2026-11-26)

1. **agent-skills only.** `skill-sets.json`, generator, local marketplace,
   opencode plugin loaded from a local path, tests, CI, docs (`AGENTS.md`
   Layout/Formats, `TODO.md`). Verify: Claude installs each set from the local
   marketplace with only its skills; skills.sh lists all skills once; opencode
   loads only the chosen set. Tag `v0.1.0`.
2. **plugin-marketplace.** Add three entries:
   `source: {type:'github', repo:'rjstone/agent-skills', path:'skills'}`,
   `claude: {skills: [...]}`; run `npm run update`; install each from
   `rjstone/plugin-marketplace` in Claude and check the skill lists. Test Codex
   (install its CLI); if Codex can't honour the list, mark the entries
   `exclude: ['codex']` and note why. Consider a first-class `skills` field in
   the marketplace config instead of the Claude-only merge, and possibly
   generating those entries from agent-skills' `skill-sets.json`.
3. **npm.** Publish the opencode package; add `opencode: {package, options:
   {sets}}` to each marketplace entry.

## Left to the builder

- Exact file names inside `opencode/` and whether it is TS or JS.
- Frontmatter parsing details (reuse the regex style of
  `build_skills_index.py`).
- Wording of set descriptions (short, "Use when..." not required: these are
  plugin descriptions, not skill triggers).
- Whether `claude plugin validate` runs in CI or stays a documented manual step.
