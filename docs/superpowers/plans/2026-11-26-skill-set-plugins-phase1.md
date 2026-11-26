# Skill-set plugins, phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define skill sets once in `skill-sets.json` and generate from it a local Claude marketplace (one plugin per set, skills by reference) and an opencode plugin that loads chosen sets, all inside agent-skills, with no npm publishing.

**Architecture:** A stdlib Python generator (`scripts/build_plugins.py`, modeled on `scripts/build_skills_index.py`) validates `skill-sets.json` and writes `.claude-plugin/marketplace.json` and `opencode/sets.json`; `--check` guards staleness in CI. A dependency-free opencode v2 server plugin (`opencode/index.ts`) reads `opencode/sets.json` and adds the chosen sets' `skills/<name>/SKILL.md` via `ctx.skill.transform`; its pure logic lives in `opencode/skills.ts` and is unit-tested with `node --test`.

**Tech Stack:** Python 3 stdlib + unittest; TypeScript run directly by Node >= 22.18 (type stripping) and by opencode; `@opencode/plugin` from the host only; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-26-skill-set-plugins-design.md`

## Global Constraints

- Every skill stays in `skills/<name>/`; no copies, no symlinks.
- First sets, exactly: `opencode-dev` = opencode-build, opencode-cli, opencode-api, opencode-console; `docshelf` = docshelf, docshelf-build; `special-agents` = provider-onboarding, decisions.
- Marketplace entries: `"source": "./skills"`, `"skills": ["./<skill>", ...]`, `name`, `description`, **no `version`**, no `plugin.json` files.
- Marketplace `name`: `agent-skills`; `owner.name`: `Robert Stone`.
- A set may share its name with a skill; a skill may be in several sets (warning, not error).
- Set names lowercase kebab-case, unique; every listed skill has `skills/<name>/SKILL.md`; every set has a non-empty description.
- opencode plugin imports only `@opencode/plugin` (from the host) and `node:` built-ins; no install step. Phase 1 plugin is for verification only.
- Root `package.json` is `"private": true` (npm is phase 3).
- Generated files: 2-space JSON, LF, trailing newline, deterministic order (file order of sets and skills).
- `skill-sets.json` changes need no skill version bump.
- `.ts` files use erasable syntax only (no `enum`, `namespace`, parameter properties) and import with explicit `.ts` extensions.
- Commit attribution lines per the session's system reminder.

## Review Focus

1. A set names a skill that was renamed or deleted: the generator must exit 2 naming the set and the skill, and CI must fail even when no skill was "selected" (Task 1 test, Task 3 CI step).
2. `skill-sets.json` is malformed (bad JSON, missing `sets`, duplicate or non-kebab set name, empty description): exit 2 with a one-line message, never a traceback (Task 1 tests).
3. opencode `sets` option given as a single string, or with an unknown set name: a string means one set; an unknown name throws an error listing the known sets (Task 2 tests).
4. A `SKILL.md` with CRLF line endings or a quoted `description`: parsed the same as LF/unquoted (Task 2 test).
5. A skill with the same id already loaded (e.g. from the HTTP catalog): left in place, reported as skipped, never replaced (Task 2 test of `planAdds`).

---

### Task 1: `skill-sets.json` and the generator

**Files:**
- Create: `skill-sets.json`
- Create: `scripts/build_plugins.py`
- Create: `tests/test_plugins.py`
- Create (generated): `.claude-plugin/marketplace.json`, `opencode/sets.json`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class SetsError(Exception)` - invalid config; message is one line.
  - `load_sets(path: str) -> dict` - parsed JSON; raises `SetsError` on unreadable/invalid JSON.
  - `validate(config: dict, skills_dir: str) -> list[str]` - raises `SetsError` on rule violations, returns warning strings (skill in several sets).
  - `build_marketplace(config: dict) -> dict`
  - `build_opencode_sets(config: dict) -> dict` - `{set_name: [skill, ...]}`
  - `render(obj: dict) -> str` - `json.dumps(obj, indent=2) + "\n"`
  - `main(argv=None) -> int` - flags `--check`, `--root DIR` (default repo root; `skill-sets.json`, `skills/` and outputs are under it). Exit 0 ok, 1 stale/missing outputs under `--check`, 2 `SetsError` (message on stderr as `error: <msg>`). Warnings go to stderr as `warning: <msg>`.
  - Output paths: `<root>/.claude-plugin/marketplace.json`, `<root>/opencode/sets.json`.

- [ ] **Step 1: Write the failing tests** in `tests/test_plugins.py` (shared test: no `selected()` guard; load the script with `importlib` like `tests/test_skills_index.py`; each test builds a temp root with `skills/a`, `skills/b`, `skills/c` SKILL.md files and its own `skill-sets.json`):

```python
def test_marketplace_lists_only_set_skills_from_skills_root(self):
    cfg = {"marketplace": {"name": "agent-skills", "owner": {"name": "Robert Stone"},
                           "description": "d"},
           "sets": [{"name": "ab", "description": "A and B", "skills": ["a", "b"]}]}
    self.assertEqual(bp.build_marketplace(cfg), {
        "name": "agent-skills", "owner": {"name": "Robert Stone"},
        "metadata": {"description": "d"},
        "plugins": [{"name": "ab", "description": "A and B",
                     "source": "./skills", "skills": ["./a", "./b"]}]})

def test_opencode_sets_map(self):            # {"ab": ["a", "b"]}
def test_missing_skill_is_error_naming_set_and_skill(self):
    # sets: ab -> ["a", "zzz"]; main() returns 2; stderr contains "ab" and "zzz"
def test_bad_json_missing_sets_duplicate_badname_empty_description_exit_2(self):
    # subTest per case; returns 2; stderr is one line starting "error:"; no "Traceback"
def test_set_may_share_name_with_skill(self):  # set "a" -> ["a"] validates
def test_skill_in_two_sets_warns(self):        # validate() returns 1 warning naming the skill
def test_check_reports_stale_then_clean(self):
    # main(["--check","--root",r]) == 1 before build; main(["--root",r]) == 0;
    # then --check == 0; edit skill-sets.json; --check == 1
def test_render_lf_trailing_newline(self):
def test_repo_outputs_are_current(self):
    # main(["--check"]) on the real repo == 0
def test_repo_first_sets_are_exact(self):
    # real skill-sets.json sets == the three sets in Global Constraints, in that order
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tests.test_plugins -v`
Expected: errors (`scripts/build_plugins.py` not found).

- [ ] **Step 3: Implement `scripts/build_plugins.py`** with the interfaces above. Module docstring in the style of `build_skills_index.py` (what it builds, the two commands). Kebab-case rule: `^[a-z0-9]+(?:-[a-z0-9]+)*$`. `--check` compares rendered text with each file on disk (missing file = stale) and prints which file is stale.

- [ ] **Step 4: Write `skill-sets.json`** with the `marketplace` block (description "Skill sets from rjstone/agent-skills") and the three sets from Global Constraints, each with a one-sentence plain description of what the set is for. Run `python3 scripts/build_plugins.py` to generate the outputs.

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest tests.test_plugins -v && python3 -m unittest discover -s tests`
Expected: all pass (including `test_public_safety` on the new files).

- [ ] **Step 6: Commit**

```bash
git add skill-sets.json scripts/build_plugins.py tests/test_plugins.py .claude-plugin/marketplace.json opencode/sets.json
git commit -m "feat: skill-sets.json and generated local marketplace"
```

### Task 2: opencode plugin

**Files:**
- Create: `opencode/skills.ts` (pure logic, `node:` imports only)
- Create: `opencode/index.ts` (the plugin; imports `@opencode/plugin` and `./skills.ts`)
- Create: `opencode/test/skills.test.ts`
- Create: `package.json` (repo root)

**Interfaces:**
- Consumes: `opencode/sets.json` (`{set: [skill, ...]}`) from Task 1.
- Produces (`opencode/skills.ts`):
  - `type SkillEntry = { id: string; name: string; description: string; path: string; content: string }` - `path` is the absolute `SKILL.md` path; `content` is the body after the frontmatter.
  - `parseFrontmatter(text: string): { name?: string; description?: string; body: string }` - handles `\r\n`, strips one pair of surrounding `"` or `'` from values.
  - `resolveSets(option: unknown, sets: Record<string, string[]>): string[]` - skill names, de-duplicated, first-seen order; a string is one set; `undefined`/empty returns `[]`; unknown name throws `Error("unknown skill set \"x\"; known sets: a, b, c")`.
  - `loadSkills(root: string, names: string[]): Promise<SkillEntry[]>` - reads `<root>/skills/<name>/SKILL.md`; `id` = frontmatter `name`; throws naming the file if `name` or `description` is missing.
  - `planAdds(existing: Set<string>, entries: SkillEntry[]): { add: SkillEntry[]; skipped: string[] }`
- `package.json`: `{"name": "agent-skills", "private": true, "type": "module", "exports": {".": "./opencode/index.ts", "./server": "./opencode/index.ts"}, "files": ["opencode/", "skills/"], "engines": {"node": ">=22.18"}}` (both export keys, per `skills/opencode-build/references/plugins.local.md` "Stale exports").

- [ ] **Step 1: Write the failing tests** in `opencode/test/skills.test.ts` with `node:test` + `node:assert/strict`, using a temp dir with `skills/a/SKILL.md` (LF) and `skills/b/SKILL.md` (CRLF, quoted description):

```ts
test("parseFrontmatter handles CRLF and quotes", ...)   // b: name "b", description unquoted, body starts "# b"
test("resolveSets: string means one set", ...)          // resolveSets("ab", {ab:["a","b"]}) -> ["a","b"]
test("resolveSets: dedupes across sets", ...)           // (["ab","bc"], {ab:["a","b"], bc:["b","c"]}) -> ["a","b","c"]
test("resolveSets: unknown set lists known sets", ...)  // throws /unknown skill set "zz"; known sets: ab, bc/
test("resolveSets: no option loads nothing", ...)       // undefined -> []
test("loadSkills reads real path and body", ...)        // path endsWith "skills/a/SKILL.md", isAbsolute
test("planAdds skips existing ids", ...)                // existing {"a"} -> add [b], skipped ["a"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `node --test opencode/test/`
Expected: FAIL (cannot find `../skills.ts`).

- [ ] **Step 3: Implement `opencode/skills.ts`** per the interfaces.

- [ ] **Step 4: Run the tests**

Run: `node --test opencode/test/`
Expected: 7 passing.

- [ ] **Step 5: Implement `opencode/index.ts`**: `export default Plugin.define({ id: "agent-skills", async setup(ctx) {...} })`. Root = `dirname(dirname(fileURLToPath(import.meta.url)))` (the folder holding `skills/` and `opencode/`). Read `opencode/sets.json`, `resolveSets(ctx.options.sets, ...)`, `loadSkills`; if none, log that no sets were chosen and return. Then `ctx.skill.transform(editor => ...)`: build `existing` from `editor.list()` ids, `planAdds`, add each with `Skill.ID.make`, `Skill.Name.make`, `Skill.Info.fields.path.make` (API in `skills/opencode-build/references/plugins-server.md`, "Skills"); log each skipped id.

- [ ] **Step 6: Verify in opencode (manual).** In the scratchpad, write a small script modeled on `skills/opencode-build/scripts/plugin_probe.py` (temp XDG dirs, `opencode serve`, poll) whose temp `opencode.jsonc` is `{"plugins": [{"package": "<repo root>", "options": {"sets": ["docshelf"]}}]}`. Expected: `/api/plugin` shows the plugin `active`; the skill list contains `docshelf` and `docshelf-build` and none of the other set skills. Repeat with `"sets": "nope"` and confirm the error names the known sets. Record the opencode version and result in the commit message. Don't commit the script.

- [ ] **Step 7: Commit**

```bash
git add opencode/skills.ts opencode/index.ts opencode/test/skills.test.ts package.json
git commit -m "feat: opencode plugin that loads chosen skill sets"
```

### Task 3: CI wiring

**Files:**
- Modify: `scripts/ci_changed_skills.py:25-26` (shared paths)
- Modify: `tests/test_ci_changed_skills.py` (new cases)
- Modify: `.github/workflows/ci.yml` (test job; `skills-index` job)

**Interfaces:**
- Consumes: `scripts/build_plugins.py --check` (Task 1), `node --test opencode/test/` (Task 2).
- Produces: `SHARED_PREFIXES` gains `".claude-plugin/"`, `"opencode/"`; a new exact-path set `SHARED_FILES = {"skill-sets.json", "package.json"}` checked in `classify`; `SHARED_TESTS` gains `test_plugins\.py`.

- [ ] **Step 1: Write the failing tests** in `tests/test_ci_changed_skills.py`: `classify(["skill-sets.json"], skills)` -> test set is `ALL`, own set empty (so no version bump is demanded); same for `opencode/index.ts`, `.claude-plugin/marketplace.json`, `package.json`, `tests/test_plugins.py`.

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tests.test_ci_changed_skills -v`
Expected: the new cases FAIL.

- [ ] **Step 3: Update `scripts/ci_changed_skills.py`** per Produces.

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tests.test_ci_changed_skills -v`
Expected: PASS.

- [ ] **Step 5: Update `.github/workflows/ci.yml`:**
  - In `test`, after the safety scan, add an always-run step "Plugin files are current (always)": `python3 scripts/build_plugins.py --check`.
  - Make the `actions/setup-node` step unconditional and add an always-run step "opencode plugin unit tests": `node --test opencode/test/`.
  - In `skills-index`: also regenerate when `skill-sets.json` or `skills/` changed or `build_plugins.py --check` fails; the commit loop runs both generators and `git add skills/index.json .claude-plugin/marketplace.json opencode/sets.json`; commit message `chore: regenerate skills index and plugin files`. Update the job's header comment.

- [ ] **Step 6: Lint the workflow locally**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` (skip if PyYAML is missing), then `python3 -m unittest discover -s tests`
Expected: no YAML error; all tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/ci_changed_skills.py tests/test_ci_changed_skills.py .github/workflows/ci.yml
git commit -m "ci: check plugin files and test the opencode plugin on every run"
```

### Task 4: End-to-end checks and docs

**Files:**
- Modify: `AGENTS.md` (Layout: `skill-sets.json`, `scripts/build_plugins.py`, `.claude-plugin/`, `opencode/`, `package.json`; Formats: Claude Code plugin **supported (local marketplace)**, opencode plugin **phase 1, local path only**; a "Skill sets" rule block: edit only `skill-sets.json`, run the generator, no version bump, plugin root is `skills/` because a remote repo-root source loads every skill (tested 2026-11-26))
- Modify: `TODO.md` (Formats: tick the Claude plugin item; add phase 2 and phase 3 items from the spec)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing new for code.

- [ ] **Step 1: Claude check.** With `CLAUDE_CONFIG_DIR` set to a scratchpad folder: `claude plugin validate .`; `claude plugin marketplace add "$PWD"`; for each set `claude plugin install <set>@agent-skills` then `claude plugin details <set>@agent-skills`.
Expected: validate passes; each "Skills (n)" line lists exactly that set's skills.

- [ ] **Step 2: skills.sh check.** `DISABLE_TELEMETRY=1 npx -y skills add . --list`
Expected: all 15 skills listed once; the three sets as groups, the rest under "General".

- [ ] **Step 3: Update `AGENTS.md` and `TODO.md`** as listed under Files; keep the AGENTS.md/CLAUDE.md twin paragraphs intact.

- [ ] **Step 4: Full test run**

Run: `python3 -m unittest discover -s tests && node --test opencode/test/ && python3 scripts/build_plugins.py --check && python3 scripts/build_skills_index.py --check`
Expected: all pass.

- [ ] **Step 5: Commit, archive, push**

```bash
git add AGENTS.md TODO.md docs/superpowers/plans/2026-11-26-skill-set-plugins-phase1.md
git commit -m "docs: skill-set plugins (phase 1)"
git config --add remote.origin.fetch '+refs/heads/skill-set-plugins:refs/remotes/origin/skill-set-plugins'
git push -u origin skill-set-plugins
```

Then ask the user whether to open a PR (template: `.github/pull_request_template.md`) and, after merge, whether to tag `v0.1.0` on `main`.
