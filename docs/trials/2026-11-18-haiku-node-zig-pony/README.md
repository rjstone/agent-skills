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
