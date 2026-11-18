# docshelf lookup-only top-level help (phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace docshelf's 3.9k-character top-level `--help` with a
~1.5k lookup card whose command lines carry the cheap query habits, then
measure with the 2026-11-18 Haiku trial.

**Architecture:** `shelf_cli.TOP_HELP` / `top_help()` produce the card;
every detail it drops moves to that command's own argparse `--help`
(built from `shelf_cli.COMMANDS`). `Param.rare` and the generated
rarer-flags table go. SKILL.md is reworded so it does not grow.

**Tech Stack:** Python 3 stdlib, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-18-docshelf-help-trim-design.md`

## Global Constraints

- Stdlib only. No change to any command's behaviour, defaults or output
  other than `--help` texts (phase 2 is separate).
- MCP `instructions` and tool schemas unchanged (byte-identical
  `tools/list` before and after).
- Top-level help: at most 1,600 characters, every line at most 76
  columns, names every command in `COMMANDS`.
- Version 0.7.4 (patch) in SKILL.md `metadata.version` and
  `shelf_core.VERSION`, set in Task 2. Never hand-edit `skills/index.json`.
- SKILL.md must not grow (6,398 bytes before).
- Full suite from the repo root: `python3 -m unittest discover -s tests`
  (all pass before). Public repo: no names, hostnames, home or drive paths.
- Subagents never call session, messaging, scheduling, trigger or
  environment tools, and never dispatch subagents.

## Review Focus

1. A detail dropped from the top-level help that no `<command> --help`
   carries (e.g. `install NAME` without a version = the newest): Task 1's
   `test_moved_facts_in_command_help`.
2. MCP clients: removing `Param.rare` changes the tool schemas or
   descriptions: Task 1's `test_mcp_tools_list_unchanged`.
3. `docshelf.py` with no command, and `-h`, still print the same card as
   `--help`: Task 1's `test_no_command_and_dash_h_print_card`.
4. A narrow terminal or an agent quoting lines: a line over 76 columns:
   Task 1's `test_top_help_fits`.
5. SKILL.md still points to the references (notes, getting docvols,
   docsets, MCP) after the rewording: Task 2's
   `test_skill_md_keeps_reference_links`.

---

### Task 1: The lookup card and moved details

**Files:**
- Modify: `skills/docshelf/scripts/shelf_cli.py` (`Param`, `COMMANDS`,
  `TOP_HELP`, `top_help()`; `EXIT_CODES` stays for `--help`'s exit line)
- Test: `tests/test_docshelf.py` (`TOP_HELP_EXPECTED` near line 2755, the
  help tests near 2826)

**Interfaces:**
- Produces: `shelf_cli.top_help() -> str` (same name); `Param` without
  `rare`.

- [ ] **Step 1: Write the failing tests** (in the help test class):
  - Replace `TOP_HELP_EXPECTED` with the new card. Start from the spec's
    sketch; it must contain the lines `search NAME... -d DOCVOL`,
    `show REF --max-lines 40`, `--offset N`, `show REF --grep=TEXT`,
    `fts WORDS... -d DOCVOL`, `toc REF`, `list`, the sentence naming the
    other commands ("each with its own --help"), `--mcp`, and an
    `Exit codes:` line covering 0, 1, 2, 4, 5, 7.
  - `test_top_help_fits`: `len(top_help()) <= 1600`; every line
    `len(line) <= 76`.
  - `test_every_command_in_help` (keep as is).
  - `test_no_command_and_dash_h_print_card`: `run_cli()` (no args, if it
    printed the card before; otherwise skip this assertion) and
    `run_cli("-h")` give `TOP_HELP_EXPECTED`.
  - `test_every_option_in_command_help`: for each `c` in `COMMANDS` and
    each `p` in `c.params` with a flag starting `--`,
    `p.flags[0] in run_cli(c.name, "--help").stdout`.
  - `test_moved_facts_in_command_help`: `" ".join(stdout.split())` of
    `<command> --help` contains, case-insensitively:
    `install`: "newest", "docvols", "--force"; `remove`: "devdocs" and
    "dash or zeal"; `list`: "also as"; `suggest`: "no network";
    `sources`: "dash or zeal"; `show`: "notes" and "--grep";
    `types`: "--type"; `fts`: "function name"; `notes`: "--check".
  - `test_mcp_tools_list_unchanged`: `json.dumps` of `shelf_mcp`'s tools
    list equals a fixture captured from the current code before any edit
    (capture it in this step: run the server's tools/list once and paste
    the JSON into the test as `TOOLS_LIST_BEFORE`, or compare against a
    hash recorded now).
- [ ] **Step 2: Run, verify the new/changed ones fail** (the card and the
  facts not yet in subcommand help):
  `python3 -m unittest tests.test_docshelf -k help -v`
- [ ] **Step 3: Implement.** New `TOP_HELP` text and a simpler
  `top_help()` (version and exit line only). Delete `Param.rare` and every
  `rare=True`. Add each missing fact to the command's `help`/`description`
  or the param's help in `COMMANDS` (argparse renders both; the MCP tool
  description reads the same fields: if a fact must go only to argparse,
  use the argparse `epilog`/description path so `tools/list` stays
  unchanged).
- [ ] **Step 4: Run the help tests, then the full suite.**
- [ ] **Step 5: Commit** `docshelf: lookup-only top-level help; details move to <command> --help`.

### Task 2: SKILL.md wording and version

**Files:**
- Modify: `skills/docshelf/SKILL.md`, `skills/docshelf/scripts/shelf_core.py`
  (`VERSION`)
- Test: `tests/test_docshelf.py`

**Interfaces:**
- Consumes: Task 1's card (SKILL.md must not contradict it).

- [ ] **Step 1: Write the failing tests:**
  - `test_skill_md_not_larger`: `os.path.getsize(SKILL.md) <= 6398`.
  - `test_skill_md_keeps_reference_links`: SKILL.md links
    `references/notes.md`, `references/getting-docvols.md`,
    `references/dash-zeal.md`, `references/mcp.md`,
    `references/lookup-defaults.md`.
  - `test_skill_md_no_rare_table_wording`: SKILL.md does not contain
    "names at its end".
- [ ] **Step 2: Run, verify `test_skill_md_no_rare_table_wording` fails.**
- [ ] **Step 3: Edit SKILL.md.** Keep "Run its `--help` first: that is
  the command reference"; replace the "A subcommand's own `--help` only
  adds the rarer options that `--help` names at its end" sentence with
  "Other commands' details: `<command> --help`." In "Looking things up",
  drop what the card now says (REF definition, `show --offset N`
  continuing, `toc REF` lists headings with REFs) and keep what it can't
  (fuzzy-match line, `(heading)` hits, options often only in page text,
  `--grep` details and `...` marks, scope / exit 4, first `fts` builds the
  index). Set `metadata.version: "0.7.4"` and `VERSION = "0.7.4"`.
- [ ] **Step 4: Full suite; `python3 scripts/ci_changed_skills.py --base origin/main --check-versions`.**
- [ ] **Step 5: Commit** `docshelf 0.7.4: SKILL.md follows the lookup card`.

### Task 3 (controller): Measure

Not for an implementer subagent; the controller runs it after the task
reviews and the whole-branch review.

- [ ] Install node, zig, pony into a scratch `DOCSHELF_CACHE_DIR`; check
  the versions (26.3.1, 0.17.1, 0.38.1).
- [ ] Three Haiku subagents (default effort), the skill arm's prompts from
  the 2026-11-18 run unchanged (questions inline; never the trial folder
  path), answers to `answers/<docs>-skill-p1.md`.
- [ ] Grade against `key.md`; record tool calls, time, tokens; per-command
  counts with `tools/replay_docshelf.py` and `tools/count_calls.py`.
- [ ] Add a "Phase 1: lookup-only --help" section to the trial README
  (table against the skill and MCP arms, which habits changed), commit,
  report to the user with the phase-2 recommendation.
