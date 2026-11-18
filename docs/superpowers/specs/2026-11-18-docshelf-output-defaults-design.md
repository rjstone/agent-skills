# docshelf: smaller output defaults (phase 2 design)

Short design (a small change). Phase 2 of the token work on branch
`optimize/docshelf` (the user, 2026-11-18). Phase 1 (0.7.4, lookup-only
`--help`) cut docshelf I/O per three questions to 3,576 (node), 2,649 (zig)
and 2,893 (pony) tokens; the MCP arm spent ~2.4k, ~2.3k and ~1.6k. Trial and
measurements: `docs/trials/2026-11-18-haiku-node-zig-pony/`.

## Intent

What is still large after phase 1 is default output: short searches
(`search Int -d zig`, 40 lines, 2.8k characters) and long sections or whole
pages read with the 150-line `show` cap or agents' own generous caps (pony
`show ... --max-lines 200`, 3.3k). In the trial every answer section was
7-37 lines long; whole pages and long sections were 54-124 lines. Smaller
defaults cut what an agent reads without changing what it can reach: every
cut line already says how to go on. TODO.md docshelf 7.2, 7.3, 7.4.

Non-goals: no change to `fts` (5 hits; always small), to output format, or
to what `--full`, `--max-lines` and `--offset` do. Anti-goal: an answer an
agent can no longer find, or a cut it can't see past.

## Decisions (the user, 2026-11-18)

- `show` caps by **lines** (picked over a character budget): default 150 ->
  **40 lines**, for sections and whole pages alike.

## Approaches considered

- Lines (picked): simple; matches `--max-lines` and the card; the
  `--offset` hint already counts lines. A 40-line cut of long table lines
  can still be ~4k characters.
- Character budget (~2,000): caps tokens directly, but needs a new cut rule
  and cut line. Not picked.
- A tighter `search` cap only for short queries: a rule people must learn,
  for two trial searches. Not picked; one smaller default instead.
- Different caps for whole pages and sections: `show` can't cheaply tell
  them apart, and 40 covers both. Not picked.

## Design

1. `show`: default `--max-lines` 150 -> **40**. Its cut line ("... N more
   lines; --offset N continues (or --full)") is unchanged.
2. `search`: default `--max-lines` 40 -> **20**. Its cut line (narrow the
   query, `-d`/`--type`, or raise `--max-lines`) is unchanged.
3. `toc`: default `--max-lines` 150 -> **60**, and its cut line also points
   to `show REF --grep=TEXT` (one option or row of a long page).
4. MCP: the same defaults (one command table drives both); the tool schemas'
   `default` values change on purpose. The phase-1 schema hash test gets a
   new pinned value, and a test checks each new default in the schema.
5. The top-level card: the `show` line becomes `show REF` ("read a section,
   40 lines; the '... more lines' line gives the --offset N"), dropping its
   own `--max-lines 40`; still within 1,600 characters and 76 columns.
   SKILL.md: only what now contradicts the defaults changes; must not grow.
6. Version 0.7.4 -> **0.8.0** (minor: every caller's default output changes),
   SKILL.md `metadata.version` and `shelf_core.VERSION` together.

## Measure

Same nine questions, docs, model (Haiku, default effort) and phase-1 prompts;
count with `tools/replay_docshelf.py` and `count_calls.py`; add a "Phase 2"
section to the trial README. Success: 9/9 kept; docshelf I/O below phase 1
(3,576 / 2,649 / 2,893) and toward the MCP arm. Watch for more `--offset`
round trips: a cut that costs an extra call per answer would show as more
tool calls.

## Left to the builder

Exact toc cut-line wording; which existing tests pin the old defaults and
how to update them.
