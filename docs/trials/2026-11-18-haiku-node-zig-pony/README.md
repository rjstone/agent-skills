# Trial: Haiku with and without docshelf (Node.js, Zig, Pony)

Date: 2026-11-18. docshelf 0.7.3, DevDocs docvols `node` (Node.js 26.3.1),
`zig` (Zig 0.17.1), `pony` (Pony 0.38.1), CLI (the MCP arm: `--mcp` server).
Model: Haiku, default effort, as Claude Code general-purpose subagents.

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
  - **docshelf MCP** (added last, see below): no skill, no Bash; only the
    `mcp__docshelf__*` tools (docshelf `--mcp`, registered as a project MCP
    server) and Write.
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
| node, docshelf MCP | ✅ | ✅ | ✅ | 3 | 12 | 22 s | 117k |
| zig, docshelf MCP | ✅ | ✅ | ✅ | 3 | 16 | 17 s | 116k |
| pony, docshelf MCP | ✅ | ✅ | ✅ | 3 | 16 | 30 s | 117k |

Totals: skill 9/9 (every answer cites a REF), docshelf MCP 9/9 (every answer
cites a REF), web via MCP 7.5/9, built-in web 7/9, no skill 5.5/9.

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

## docshelf MCP arm

Run after the others, from a second session on branch `testing/docshelf`
(`.mcp.json` registers `python3 skills/docshelf/scripts/docshelf.py --mcp`).
The docvols were installed into the default cache by the controller (CLI);
the MCP server had started before that and still listed all three at once,
so it reads the cache on each call. DevDocs still served node 26.3.1, zig
0.17.1 and pony 0.38.1 (the first `install node` failed on a truncated
download, "unterminated string", and worked on retry). Tool calls and
tokens below are in the table's "Tool calls" column (counted as in the
other arms: ToolSearch, docshelf calls and Write all count).

- **Scores:** 9/9, every answer cites the right REF (the same REFs as
  `key.md`), confidence "high" except Zig Z3 "medium-high" (it did not open
  the `std.lang.Signedness` declaration). Pony P3's order came from the
  documented rule (the docs print no output) and the agent said so.
- **What the agents did:** ToolSearch to load the schemas, then `list`
  (every run, to confirm the version), `search` (entry names, then the
  `docvols` filter), `show` with the REF, plus `fts` once in zig and once
  in pony. None opened SKILL.md or any `--help`: the server's instruction
  line and the tool descriptions were enough. `show` used `max_lines` (node,
  zig) or `full` (pony) to keep output small.
- **Cost vs the skill arm** (per-call counts from `tools/count_calls.py`,
  (typed + printed) / 4): the docshelf calls cost about 2.4k tokens (node),
  2.3k (zig, of which 0.4k the four failed calls below) and 1.6k (pony),
  against 3.4-5.6k per run for the skill, because the MCP agents skip
  SKILL.md (~1.6k) and `--help` (~1k) and orientation is ToolSearch plus
  `list` (about 0.1k). The lookups alone are about the same (skill:
  2.3-3.9k). Agent totals: 116-117k tokens against 119-123k, 17-30 s
  against 21-29 s; the baseline context is most of the tokens, so the
  difference is small. Tool calls are higher (12-16 against 8) because each
  MCP call is one small lookup, and four of zig's 16 were failed calls.
- **MCP-specific:**
  - Zig's first four `search` calls failed with `InputValidationError`:
    Haiku sent `{"query": divFloor, ...}` (a bare, unquoted word) although
    `query` is an array of strings. docshelf's server never saw them. The
    harness's error text ("could not be parsed as JSON ... unescaped
    backslashes in file paths") names common causes that do not fit; the
    agent corrected to `["divFloor"]` on the fifth call and made no more.
  - docshelf itself returned no `isError`. Its no-match texts helped: zig's
    "no matches for 'continue' (entry names and page headings; fts searches
    the text inside pages)" led to `fts` and the `Labeled-switch` REF;
    pony's "search wants all the words in one entry name. Best entry for
    each word: ..." came after a three-word query and led to a better one.
  - Node's `all: true` searches (one or two words) stayed short (57-165 characters)
    because they named the entry (`path.basename`, `DatabaseSync`,
    `permission drop`); only zig's `search Int` was large (2.8k characters,
    all entries containing "Int"), as in the skill arm.
- **Rule slips by the agent:** the node agent called `send_message`
  (`session_id: "none"`, message "done") after finishing; the auto mode
  classifier denied it, so nothing was sent. No scheduled task was created
  this time (`list_triggers` shows none from 2026-11-18). That is the third
  such slip by a Haiku subagent in this trial, so keep the "never call
  session, messaging, scheduling ..." line in the prompt. The pony agent
  wrote its answer file twice (same content).

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

## CLI vs MCP: command I/O only

Estimate: CLI = (command typed + output) / 4; MCP = (tool-call JSON +
result text) / 4. Harness framing, ToolSearch and answer writing are left
out on both sides.

**Same queries on both interfaces.** `tools/replay_mcp.py` replays the CLI
agents' own docshelf commands through `docshelf --mcp` (each `| head -N`
applied to both outputs; `--help` has no MCP counterpart and is left out):

| Docs | Queries | CLI | MCP | Difference |
|---|---|---|---|---|
| node | 11 | 4,714 | 4,669 | −1% |
| zig | 12 | 2,436 | 2,405 | −1% |
| pony | 15 | 2,379 | 2,299 | −3% |

Results are the same size to within a few characters (MCP's tool wording
added 7 characters to two results); the call JSON is 5-25 characters
shorter than the typed command. Pony's bare `sources` (no query) is an
error over MCP, where `query` is required.

**Fixed context, once per session:**

| | CLI | MCP |
|---|---|---|
| Up front | SKILL.md, 6,398 chars (~1.6k tok) | server `instructions`, 519 chars (~130 tok) |
| Orientation | `--help`, ~3.9k chars (~1.0k tok) | tool schemas, 5,013 chars (~1.25k tok) |
| Total | ~2.6k tok | ~1.4k tok |

Claude Code defers MCP schemas until ToolSearch loads them; a client that
loads all schemas at start keeps the 1.25k in context all session.

**What each arm spent** (its own queries):

| Docs | CLI arm | MCP arm |
|---|---|---|
| node | 5,645 | ~2.4k |
| zig | 3,435 | ~2.3k (0.4k on four failed calls) |
| pony | 3,410 | ~1.6k |

Since the same queries cost the same on both interfaces, the gap is the
agents' behaviour: the MCP agents set `max_lines`, searched exact entry
names (`path.basename`, `DatabaseSync`) rather than broad words (`node`,
`Int`), and skipped `--help`, whole-page `show` and `toc`. The tool
schemas put `max_lines` and `docvols` in front of the model as named
parameters; SKILL.md can teach the same habits to CLI agents (TODO.md
docshelf 7.5).
