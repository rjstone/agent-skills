# docshelf smaller output defaults (phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lower docshelf's default output caps (`show` 40 lines, `search` 20,
`toc` 60, toc's cut line points to `--grep`), ship 0.8.0, and measure with
the 2026-11-18 Haiku trial.

**Architecture:** The defaults live in `shelf_cli.COMMANDS` (one table
drives argparse and the MCP tool schemas), so both interfaces change
together. toc's cut-line hint is in `shelf_lookup.cmd_toc`. The card
(`shelf_cli.TOP_HELP`) and SKILL.md follow.

**Tech Stack:** Python 3 stdlib, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-18-docshelf-output-defaults-design.md`

## Global Constraints

- Defaults: `show --max-lines` **40** (was 150), `search --max-lines` **20**
  (was 40), `toc --max-lines` **60** (was 150). `fts` unchanged (5 hits).
- No change to output format or to what `--full`, `--max-lines` and
  `--offset` do; existing cut lines keep their wording except toc's, which
  adds `show REF --grep=TEXT`.
- MCP tool schemas change only in those three `default` values.
- Card: within 1,600 characters and 76 columns (existing tests). SKILL.md
  must not grow (6,002 bytes now).
- Version **0.8.0** in SKILL.md `metadata.version` and `shelf_core.VERSION`
  (Task 2). Never hand-edit `skills/index.json`.
- Full suite: `python3 -m unittest discover -s tests` (712 pass before).
  Public repo: no names, hostnames, home or drive paths.
- Subagents never call session, messaging, scheduling, trigger or
  environment tools, and never dispatch subagents.

## Review Focus

1. Paging past the new cut: `show REF` then `--offset 40` continues exactly
   where the cut was, and its cut line names `--offset 80`: Task 1's updated
   `test_offset_skips_lines` / `test_cut_line_names_next_offset`.
2. MCP: a `show` call without `max_lines` returns 40 lines plus the cut
   line: Task 1's `test_mcp_show_default_40_lines`.
3. `show --grep` with more than 40 matching lines still prints a cut line
   (the agent can see there is more): Task 1's
   `test_grep_output_cut_at_default_shows_cut_line`.
4. Notes still follow a section cut at 40 lines: Task 1's
   `test_notes_after_cut_section`.
5. `search --json` with more than 20 hits stays one valid JSON array of 20
   items (the cap is silent in JSON, as it was at 40): Task 1's
   `test_search_json_default_20_items`.

---

### Task 1: The new defaults

**Files:**
- Modify: `skills/docshelf/scripts/shelf_cli.py:86-110` (three `default=`),
  `skills/docshelf/scripts/shelf_lookup.py` (`cmd_toc` cut-line hint)
- Test: `tests/test_docshelf.py` (show-offset tests near 1240, the schema
  test near 3191, `TOOL_SCHEMAS_SHA256`, new tests)

**Interfaces:**
- Produces: the defaults above; toc's cut line contains
  `show REF --grep=TEXT`.

- [ ] **Step 1: Write the failing tests:**
  - Update `test_offset_skips_lines` (fixture: 400-line section):
    `show l:p#s --offset 40` -> `out[0] == full[40]`, `out[39] == full[79]`.
  - Update `test_cut_line_names_next_offset`: `show l:p#s` last line
    `"... 360 more lines; --offset 40 continues (or --full)"`; after
    `--offset 40` the cut line names `--offset 80`.
  - Update the MCP schema test (near 3191): `search` `max_lines`
    `"integer=20>=1"`, `show` `"integer=40>=1"`, `toc` `"integer=60>=1"`.
  - `TOOL_SCHEMAS_SHA256`: re-pin to the hash after the change (record the
    value in Step 3); keep the test.
  - `test_mcp_show_default_40_lines`: an MCP `tools/call` `show` on the
    400-line fixture without `max_lines` returns 40 content lines plus the
    `... 360 more lines` line.
  - `test_search_default_20_lines`: a search with more than 20 hits prints
    20 hit lines and a `... N more lines cut` line.
  - `test_search_json_default_20_items`: same search with `--json`:
    `json.loads(stdout)` is a list of length 20.
  - `test_toc_default_60_and_grep_hint`: `toc` of a page with more than 60
    headings prints 60 lines and a cut line containing
    `show REF --grep=TEXT`.
  - `test_grep_output_cut_at_default_shows_cut_line`: `show REF
    --grep=TEXT` where more than 40 lines match prints a cut line.
  - `test_notes_after_cut_section`: a docvol with a notes section for the
    400-line REF: `show` (default) prints the cut line and then the note.
- [ ] **Step 2: Run, verify the new/updated ones fail:**
  `python3 -m unittest tests.test_docshelf -v 2>&1 | grep -E "FAIL|ERROR"`
- [ ] **Step 3: Implement.** Set the three `default=` values; add
  `show REF --grep=TEXT` to toc's cut-line hint (keep `--max-lines` in it);
  re-pin `TOOL_SCHEMAS_SHA256`.
- [ ] **Step 4: Run the changed tests, then the full suite.**
- [ ] **Step 5: Commit** `docshelf: smaller defaults (show 40, search 20, toc 60); toc points to --grep`.

### Task 2: Card, SKILL.md, version 0.8.0

**Files:**
- Modify: `skills/docshelf/scripts/shelf_cli.py` (`TOP_HELP`),
  `skills/docshelf/SKILL.md`, `skills/docshelf/scripts/shelf_core.py`
  (`VERSION`), `skills/docshelf/references/*.md` only where they state a
  replaced default
- Test: `tests/test_docshelf.py` (`TOP_HELP_EXPECTED`)

**Interfaces:**
- Consumes: Task 1's defaults.

- [ ] **Step 1: Write the failing test:** `TOP_HELP_EXPECTED`'s `show`
  lines become
  `  show REF                     read a section, 40 lines; the "... more`
  / `lines" line gives the --offset N to go on` (re-wrapped to the card's
  columns; no `--max-lines 40` and no `150` left in the card), and
  `test_card_states_current_show_default`: `"40 lines"` in `top_help()`
  and `"150"` not in it.
- [ ] **Step 2: Run, verify they fail.**
- [ ] **Step 3: Edit** `TOP_HELP`; grep SKILL.md and
  `skills/docshelf/references/` for `150` / `40 lines` / `max-lines`
  statements of the old defaults and fix only those (SKILL.md must stay
  at or under 6,002 bytes); set `0.8.0` in both places.
- [ ] **Step 4: Full suite; `python3 scripts/ci_changed_skills.py --base origin/main --check-versions`.**
- [ ] **Step 5: Commit** `docshelf 0.8.0: card and docs follow the new defaults`.

### Task 3 (controller): Measure

- [ ] Same scratch cache (node 26.3.1, zig 0.17.1, pony 0.38.1), same three
  Haiku skill prompts as phase 1 (answers to `answers/<docs>-skill-p2.md`).
- [ ] Grade against `key.md`; tool calls, time, tokens; docshelf I/O with
  `tools/replay_docshelf.py`; count `--offset` calls.
- [ ] Add "Phase 2: smaller defaults" to the trial README (table against
  phase 1, 0.7.3 and the MCP arm), commit, report.
