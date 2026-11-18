# docshelf: lookup-only top-level help (design)

Short design (a small change). Phase 1 of the token work on branch
`optimize/docshelf` (the user, 2026-11-18): wording first, measure, then new
output defaults (phase 2, TODO 7.2-7.4), measure.

## Intent

In the 2026-11-18 Haiku trial (`docs/trials/2026-11-18-haiku-node-zig-pony/`)
the same queries cost the same over the CLI and `--mcp`, but the CLI agents
spent 3.4-5.6k tokens of docshelf I/O per three questions against 1.6-2.4k
over MCP. Two causes: every CLI run read the 3.9k-character top-level
`--help` (SKILL.md says to), and the CLI agents queried more broadly
(no line cap on `show`, broad search words, `toc` of big pages). Over MCP
the line cap and `docvols` are named parameters the model sees on every
call. Goal: make the top-level `--help` a short lookup card whose usual
command lines carry the cheap habits, so CLI agents read less up front and
query like the MCP agents. TODO.md docshelf 7.1 and 7.5.

Non-goals: no change to any command's behaviour, defaults or output (phase
2); no change to MCP `instructions` or tool schemas; no trimming of the rest
of SKILL.md (a later candidate). Anti-goal: an agent that can no longer find
how to install, write notes or narrow a search without guessing.

## Approaches (the user picked A, 2026-11-18)

- **A. Lookup-only top-level `--help` (picked).** About 1.3-1.5k characters:
  the lookup lines with the habits built in, one line naming the other
  commands (each has its own `--help`), a compact exit-code line. Close to
  the MCP server's `instructions`, which were enough for the MCP agents.
- B. Keep `--help`; move the habits into SKILL.md and say "skip --help".
  SKILL.md (read every run) grows ~1.5k; against the original design
  ("--help is the command reference; SKILL.md covers what help can't").
- C. A plus a "Query habits" list in SKILL.md. Held in reserve if A's
  measurement shows the habits didn't change.

## Design

Top-level `--help` (`shelf_cli.TOP_HELP`), target about 1.5k characters,
along these lines (exact wording is the builder's, within the rules below):

```
docshelf X.Y.Z: look up DevDocs documentation and Dash/Zeal docsets offline.
REF = <docvol>:<path>[#anchor], as search and fts print it (docsets:
<Name>:<id> or <Name>:page:<path>[#anchor]); docvol names: list.
-d takes a docvol or a family (all its versions).

Look up:
  search NAME... -d DOCVOL     entry names (and page headings) with all the
                               words; the exact name is best
  show REF --max-lines 40      read a section (default 150 lines); go on with
                               --offset N, as its last line says
  show REF --grep=TEXT         only lines with TEXT (repeatable); try before toc
  fts WORDS... -d DOCVOL       words inside pages; include the function name
  toc REF                      a long page's headings, each with its REF
  list                         installed docvols and versions

Other commands, each with its own --help: types, notes, suggest, sources,
install, update, remove, where, index-text. --mcp runs a stdio MCP server.
Exit codes: 0 ok; 1 notes --check problems; 2 usage; 4 scope too wide or
unknown -d; 5 not found or damaged; 7 network or unreadable docset archive.
```

Rules:
- Every option the old top-level help described stays documented in its
  command's own `--help` (argparse); nothing is lost, only moved down.
- The generated "Only if you need these" table goes; `--max-lines` and
  `--offset` are shown in the `show` line. (The table existed so a new
  option couldn't be left out; each `<command> --help` now carries that.)
- SKILL.md: keep "run `--help` first"; replace "A subcommand's own `--help`
  only adds the rarer options that `--help` names at its end" with one line
  saying the other commands' details are in `<command> --help`. Remove the
  "Looking things up" text that the new help now states (net SKILL.md size
  must not grow). Keep the references links (notes, getting docvols,
  docsets, MCP).
- `TOP_HELP_EXPECTED` in the tests changes in the same commit; any test of
  the rare-flags table is replaced by a test that each command's `--help`
  lists all its options.
- Version: patch, 0.7.3 -> 0.7.4 (wording, no feature), SKILL.md
  `metadata.version` and `shelf_core.VERSION` together.

## Measure (then decide phase 2)

Re-run the trial's skill arm with the same nine questions and prompts
(Haiku, default effort, one agent per documentation; node 26.3.1, zig
0.17.1, pony 0.38.1), count with `tools/count_calls.py` and
`tools/replay_docshelf.py`, add a "phase 1" section to the trial README.
Success: 9/9 kept; docshelf I/O per three questions down from 3.4-5.6k
toward the MCP arm's 1.6-2.4k; `--help` read cost down from ~1k to
~0.4k tokens. If the query habits did not change, consider approach C
before phase 2.

## Left to the builder

Exact help wording and line breaks (keep within ~1.5k characters and 76
columns); which SKILL.md sentences become redundant; test names.
