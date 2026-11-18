# Trial: Haiku with and without docshelf (Node.js, Zig, Pony)

Date: 2026-11-18. docshelf 0.7.3, DevDocs docvols `node` (Node.js 26.3.1),
`zig` (Zig 0.17.1), `pony` (Pony 0.38.1), CLI. Model: Haiku, default effort,
as Claude Code general-purpose subagents.

## Method

- Three questions per documentation, easy to hard (`questions.md`). Every
  answer was checked against the installed docs first (`key.md`, with the
  REF each answer comes from). The key was kept out of the agents' reach.
- One agent per documentation and arm, all in parallel:
  - **no skill:** answer from memory; no tools except writing the answer file.
  - **skill:** told the docshelf skill is available and where the docs cache
    is; no web search or fetch.
  - **web** (added later, see below): no skill; built-in WebSearch/WebFetch
    allowed.
- Answers are in `answers/<docs>-<arm>.md`. Grading: full 1, partial ½,
  wrong 0.

## Results

| Run | Easy | Medium | Hard | Score | Tool calls | Time | Tokens |
|---|---|---|---|---|---|---|---|
| node, no skill | ✅ | ½ defaults right, versions unknown | ½ "no" right; alternative (`drop('fs.read', '*')`) and version (25.4) wrong | 2 | 1 | 13 s | 98k |
| node, skill | ✅ | ✅ | ✅ | 3 | 8 | 29 s | 123k |
| zig, no skill | ✅ | ½ invented "operand must be comptime-known" | ½ `@Int` right, `std.builtin.Signedness` (not `std.lang`) | 2 | 1 | 10 s | 109k |
| zig, skill | ✅ | ✅ | ✅ | 3 | 8 | 21 s | 119k |
| pony, no skill | ✅ | ½ capabilities missing | ❌ join order "input order" at high confidence; wrong `next` signature | 1.5 | 1 | 18 s | 111k |
| pony, skill | ✅ | ✅ | ✅ | 3 | 8 | 27 s | 120k |
| node, web | ✅ | ✅ | ✅ | 3 | 9 | 39 s | 117k |
| zig, web | ✅ | ✅ | ½ `@Int` right, `std.builtin.Signedness` again | 2.5 | 10 | 33 s | 121k |
| pony, web | ✅ | ❌ gave today's `AmbientAuth` (no `None`), not 0.38.1's union | ½ order right; `next` parameter types wrong | 1.5 | 15 | 41 s | 123k |
| node, web via MCP (Firecrawl) | ✅ | ✅ | ✅ | 3 | 10 | 39 s | 155k |
| zig, web via MCP (Firecrawl) | ✅ | ✅ | ✅ | 3 | 7 | 57 s | 132k |
| pony, web via MCP (Firecrawl) | ✅ | ❌ today's `AmbientAuth val`, "high" confidence | ½ order right; `next` default is today's `RejectAlways[B]`, 0.38.1 has `qualify` | 1.5 | 7 | 23 s | 132k |

Totals: skill 9/9 (every answer cites a REF), web via MCP 7.5/9, built-in web 7/9, no skill 5.5/9.

## Observations

- The skill's gain grows with difficulty and with how thin the training
  data is (node ½+½ lost, pony ½+1 lost). Easy questions were equal.
- The worst no-skill error was confident (Pony join order, "high").
  On Node and Zig, Haiku flagged its weak answers as low or medium.
- From memory Haiku knew `@Int` replaced `@Type`, but not its namespace.
- Cost of the skill: about 7 more tool calls and 10-15 s per three
  questions, about 10-20k more tokens.
- The Node skill run noticed an example on the `process` page that seems to
  contradict the stated wildcard rule; it followed the rule (correct).
- One skill run made a stray session-messaging tool call with no arguments;
  the permission check denied it.

## Web arm

- The sandbox's network allowlist blocked ziglang.org, codeberg.org,
  stdlib.ponylang.io and docs.w3cub.com, so the Zig and Pony web runs
  worked from search snippets and mirrors; nodejs.org was reachable. On an
  open network the web arm would likely do better on Zig and Pony.
- Version drift is the web's real weakness here: for Pony P2 it found the
  current `Env.root: AmbientAuth` (ponyc PR #3962, 2022) and answered with
  it, though it saw that older docs had `(AmbientAuth val | None val)`.
  docshelf answers from the pinned 0.38.1 docvol.
- The web arm cost more than the skill: 9-15 tool calls and 33-41 s per
  three questions, against 8 calls and 21-29 s.

## Web via MCP arm

- Each agent could pick one search/scrape MCP service (Firecrawl, Exa,
  Brave, Parallel); all three picked Firecrawl. Its fetches run server-side,
  so the sandbox allowlist did not block ziglang.org or stdlib.ponylang.io.
- With the real pages reachable, Zig rose to 3/3. Pony did not improve:
  stdlib.ponylang.io serves only the latest release, and the agent took it
  for 0.38.1 ("high" confidence) and answered P2 and P3's default with
  today's API. Version drift, not access, is what the web arms miss.
- Cost: 7-10 tool calls, 23-57 s and 132-155k tokens per three questions;
  the skill used 8 calls, 21-29 s and 119-123k tokens.
- The Node run created a one-minute "noop" scheduled message in the
  session against its instructions; the controller deleted it before it
  fired. (A second rule slip by a Haiku subagent in this trial; see above.)

## Skill runs: tokens per docshelf command

Estimate as in earlier trials: (characters typed + characters printed) / 4.
Typed = `python scripts/docshelf.py ARGS` (plus the agent's `| head -N`) as
an agent types it with a default cache; the trial's `export
DOCSHELF_CACHE_DIR=...` and absolute paths are left out. Printed = what the
command prints, re-measured by replaying each command exactly as run
(`tools/replay_docshelf.py`); docshelf output is deterministic.
`tools/count_calls.py` gives the raw per-tool-call counts from a transcript.

| Docs | Commands | Typed | Printed | ~Tokens | Orientation (`--help`, `list`, `sources`) | Lookups for 3 answers |
|---|---|---|---|---|---|---|
| node | 12 | 856 | 21,725 | 5,645 | 1,711 (incl. `search node`, 766) | 3,934 |
| zig | 13 | 631 | 13,112 | 3,435 | 1,038 | 2,397 |
| pony | 16 | 983 | 12,658 | 3,410 | 1,083 | 2,327 |

Each run also read SKILL.md (about 6.5k characters, ~1.6k tokens). Lookups
cost about 0.8k tokens per answer (zig, pony) to 1.3k (node).

Largest single outputs (TODO.md docshelf group 7):
- `--help`, about 3.9k characters, read by every run right after SKILL.md;
  paid once per session, so only worth a look.
- Short or generic `search` queries: `search node` (all docvols) 3.0k,
  `search Int -d zig` 2.8k.
- `toc node:sqlite | head -60`: 4.4k, where `show --grep` found the answer
  in 1.2k.
- Long sections: the `DatabaseSync` options (3.8k) are the answer; the zig
  `Labeled-switch` section (3.8k) is mostly one example, with the answer in
  its first 5 lines; pony's whole `builtin-env` page (1.6k) repeated two
  field sections already read.
