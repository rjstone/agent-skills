# Trial: docshelf-build, three opencode models, Yosys docs, sandboxed

Date: 2026-11-21. opencode 2.3.x, `opencode run --standalone --archived --auto
--format json`, one run per model and arm. Skill under test:
`skills/docshelf-build` (0.1.0, branch `skill/docshelf-build`), paired with
the `docshelf` skill from the branch that lists built docvols (docshelf 0.9.0;
the 0.8.x copy on `main` cannot see a built docvol).

## Setup

- `run_trials.sh PROVIDER/MODEL...` runs every run in the `sandboxing`
  skill's bubblewrap sandbox (`skills/sandboxing/scripts/sandbox.py`): empty
  environment, unprivileged host user, private `/work` as `HOME` and cwd
  (`/work/proj`), network through the egress proxy (sandbox.py passes the
  proxy variables and a CA copy), placeholder provider keys
  (`proxy-injected`; the proxy adds the real ones). Provider config is the
  2026-11-18 trial's `opencode.json` (only needed for the `nous` model;
  `opencode-go/*` models are built in). Models: `opencode-go/gpt-6-luna`,
  `opencode-go/deepseek-v4.1-flash`, `nous/stepfun/step-3.7-flash`.
- Arm **skill**: `docshelf-build` and `docshelf` copied to
  `/work/.claude/skills/`. Arm **base**: no skills. The two arms of a model
  run one after the other, models in parallel. No retries were needed (no
  429 or provider errors).
- One prompt, which never names a skill: "I want the Yosys documentation
  (https://yosyshq.readthedocs.io/projects/yosys/en/stable/) available
  offline on this machine so I can look things up later without the web. Set
  that up, then using only the offline copy tell me what options the
  opt_clean pass accepts and what each does."
- `score_trials.py` reads the JSON events (tool calls, not the model's claims).
  `answer_key.md` has the real answer from `docshelf show`. Raw event logs
  are not kept in the repo.
- A first attempt used the repo's `main` docshelf copy by mistake; every
  model then had to find out by hand how to make a built docvol visible
  (one symlinked it into `devdocs/`). Discarded; the results below are the
  re-run with the 0.9.0 docshelf.

## Results

Correct answer: one option, `-purge` (also remove internal nets that have a
public name), plus `[selection]`; no other option exists.

| Run | Used skills | Setup method (from tool calls) | build, then query | Answer | Wall time | Tool calls | Disk left |
|---|---|---|---|---|---|---|---|
| gpt-6-luna, skill | both | `docshelf_build.py` plan, build, then rebuilt with `--all` | yes | correct (`-purge`; no `[selection]` mention) | 165 s | 25 | 6.5 MB |
| deepseek-v4.1-flash, skill | both | `docshelf_build.py` plan, build | yes | correct, complete | 96 s | 21 | 4.7 MB |
| step-3.7-flash, skill | both | `docshelf_build.py` plan, build | yes | correct (no `[selection]` mention) | 93 s | 15 | 3.2 MB |
| gpt-6-luna, base | none | webfetch, then `wget --mirror` of the site | n/a (grep/read HTML files) | correct, complete | 51 s | 12 | 17.2 MB |
| deepseek-v4.1-flash, base | none | `wget` mirror, link check, local server script | n/a | correct, complete | 214 s | 50 | 41.0 MB |
| step-3.7-flash, base | none | `wget` mirror, `git clone` of the Yosys repo, `pip install sphinx`, local Sphinx build | n/a | correct (read from the C++ source in the clone, not the site) | 268 s | 34 | 51.9 MB |

"Disk left" is the size of `/work/proj` (base) or of docshelf's cache under
`/work/.cache/docshelf` (skill; luna and deepseek include a full-text index
that their own `fts` call created, about 0.5 to 0.8 MB). The skill-arm
docvol alone is 3.2 to 6.2 MB.

All six answers were correct and none invented an option (`-noremove` does
not exist). The `[selection]` check in the scorer flagged luna-skill and
step-skill only because their replies never mention the selection argument.

## Observations

- Every skill-arm run loaded both skills first, ran `docshelf_build.py`
  plan then build, and then answered with `docshelf.py search` / `show`
  (4 to 6 queries) without fetching the web again. The only web access
  outside the build was `curl -sI .../objects.inv`, which the skill's "Is the
  site Sphinx?" section suggests. Each ran the 49-full / 65-stub default
  plan except luna, which rebuilt with every page in full.
- Baseline runs also succeeded, but each made an ad hoc copy: a `wget`
  mirror (17 to 41 MB, HTML with theme assets, searchable only by grep or a
  local server) and, for step, a clone of the whole Yosys source plus a
  Sphinx build, then answered from the C++ source rather than the docs
  site. Skill arm: 2.6x to 16x less disk, about 2x to 3x faster for two of
  the three models (luna's baseline was the fastest run of all, 51 s), and
  every answer came from a docshelf lookup that is repeatable later.
- The baselines' offline copy is a plain folder with no index; "look things
  up later" needs the next agent to know about it. The docvol is listed by
  `docshelf list` and found by `docshelf search`.

## docshelf-build problems seen

1. **Changing a plan is not obvious.** luna ran `build yosys --all` after the
   first build and got `plan options need a SOURCE; to change the plan of
   yosys run: plan SOURCE --name yosys ...`. SKILL.md step 2 says "rerun
   with `--full 'group/*'`" and the `build NAME` description says it reuses
   the plan; neither says that options only work with a SOURCE or with
   `plan`. luna recovered from the error message. Suggest one sentence:
   "to change a built docvol's plan: `plan SOURCE --name NAME --full ...`,
   then `build NAME`."
2. **Misleading warning with `--all`.** `plan ... --all` for Yosys printed
   "114 pages: 114 full, 0 stub" and then "warning: no page has a domain
   role (every entry is std:*), so the rule keeps nothing in full". With
   `--all` the rule does not apply, so the warning contradicts the summary.
   (The default plan printed no such warning.)
3. **404 page in the inventory.** The `--all` build reported `1 failed
   py-modindex.html: HTTP 404`: the inventory lists a generated Python module
   index the site does not serve. Handled as a stub, but luna reported it to
   the user as part of the setup.
4. **Docvol entry whose anchor does not resolve.** `search opt_clean` lists
   `yosys:cmd/index_passes_opt#opt_clean.opt_clean` (kind `cmdusage`), but
   `show` of it prints `warning: no #opt_clean.opt_clean on
   cmd/index_passes_opt` and then dumps the page from its top (an unrelated
   section, `clean`). Seen in luna's and step's runs; step then used the
   other two entries. Either the build should not emit that entry or its
   anchor should be fixed. Not a docshelf-build failure of the run, but
   easy to take for the answer.
5. **Docvol name default.** The models chose the name `yosys`; the skill's
   own default would be derived from the project and version (the answer-key
   build used `--name yosyshq-yosys`). No problem seen.
6. Behaviour that came from the docshelf skill, not docshelf-build: after
   building, luna and deepseek asked the user which lookup tool to make the
   project default (docshelf's `lookup-defaults.md`); deepseek's `question`
   tool call was cancelled by the non-interactive run, luna put the question
   in its final reply. It adds noise to a "set it up and answer" task.

## Fixed after the trial (same PR)

- 1: SKILL.md now says plan options go with `plan` or a SOURCE, and how to
  change a built docvol.
- 2: the warning appears only when no page is full (fixed during the final
  code review, before these runs' code was replaced).
- 3: Sphinx's generated pages (`genindex`, `search`, `*modindex`) are left
  out of the plan.
- 4: cause found: Sphinx wrote anchors holding spaces unescaped
  (`#opt_clean.opt_clean [options] [selection]`), so the inventory line's
  anchor tail spilled into the display name (376 Yosys entries). The parser
  now moves the tail back, and whitespace in ids, link fragments and entry
  anchors becomes `_`. After a fresh Yosys build all 1,309 anchored entries
  resolve to an id on their page.

## Re-run

```bash
apt-get install -y bubblewrap                  # if missing
export DOCSHELF_SKILL=<docshelf skill folder, version 0.9.0 or later>
export OUT=<output folder readable by the sandbox user, e.g. a new /tmp folder>
docs/trials/2026-11-21-docshelf-build-yosys/run_trials.sh \
  opencode-go/gpt-6-luna opencode-go/deepseek-v4.1-flash nous/stepfun/step-3.7-flash
python3 docs/trials/2026-11-21-docshelf-build-yosys/score_trials.py -v "$OUT"/*/
```
