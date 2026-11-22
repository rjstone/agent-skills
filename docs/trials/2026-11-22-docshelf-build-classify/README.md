# Trial: docshelf-build 0.3.0 classify, three opencode models, LangChain

Date: 2026-11-22. opencode 2.3.x, `opencode run --standalone --archived --auto
--format json`, one run per model and round, sandboxed as in
`../2026-11-22-docshelf-build-detect/` (same runner, llms.txt site only).
Skill under test: `skills/docshelf-build` 0.3.0 (branch
`update/docshelf-build`), paired with `docshelf` 0.9.0.

Prompt (names no skill): "I want the LangChain documentation
(https://docs.langchain.com/) available offline ... I only use the Python
SDK, and I want reference material only: leave out tutorials and conceptual
guides. Set that up, then using only the offline copy tell me what values
create_agent's response_format parameter accepts, and what happens when I
pass a schema type directly." Models: `opencode-go/gpt-6-luna`,
`opencode-go/deepseek-v4.1-flash`, `nous/stepfun/step-3.7-flash`.

`score_trials.py` reads the JSON events and each run's final plan: classify
buckets, and agreement of the final `keep` with the 80 LangChain labels in
`tests/fixtures/docshelf_build_classify.json` (full = reference, stub =
guide). `answer_key.md` has the answer.

## Round 1 (commit e23870f)

All three answers correct, all three read `BUILD-llmstxt.md`, and none used
classify as intended: its loop said to narrow a large site "before building"
with `--stub 'group/*'`, so every model cut pages by guessed path patterns
first.

- step: planned the Python sub-index, stubbed 97 pages before building,
  never ran `classify`.
- deepseek: stubbed 185 pages by pattern before building, then classified
  the 55 it built (49 choices applied).
- luna: `--stub '*' --full 'oss/python/reference/*'`, then built from its
  own index of reference.langchain.com (3 pages).

Fix (commit 5b9f467): the loop narrows by sub-index, keeps `--stub` for
whole unwanted groups, and says to run `classify` after `build` when the
user wants reference only.

## Round 2 (commit 5b9f467)

| Run | Flow (from tool calls) | Choices applied | Final plan (rules ref / rules stub / agent) | vs labels | Reference pages stubbed | Answer | Time |
|---|---|---|---|---|---|---|---|
| luna | sub-index, build, classify x5, apply x3, build | 162 | 9 / 70 / 161 (240 pages) | 63/80 | 5 | correct | 350 s |
| deepseek | sub-index, build, classify x3, apply x2, build | 168 | 9 / 63 / 168 (240 pages) | 60/80 | 5 | correct | 336 s |
| step | root index with group `--stub` (other languages, LangSmith), build, classify x4, apply, build | 149 | 9 / 67 / 148 (224 fetched of 1,407) | 49/80 | 4 | correct | 378 s |

- Every run now builds first and then classifies with the rules plus its
  own review; every answer passes.
- The rules decided 72, 76 and 79 pages per run. Only 22, 20 and 24 of
  those carry a label, and all of those agree. The labelled pages are the
  calibration sample the thresholds were fitted on (in-sample), so this is
  no out-of-sample measure of the rules; the other decisions are
  unlabelled. All reference pages stubbed came from the model's choices or
  a group pattern.
- luna and deepseek stubbed the same five reference pages
  (`oss/python/deepagents/customization`, `.../profiles`,
  `oss/openwiki/customize`, `langsmith/python/managed-deep-agents-cli`,
  `.../managed-deep-agents-agent-definition`): configuration pages with
  prose around them. Step stubbed four of them (all but
  `oss/python/deepagents/customization`), two of those through its
  `langsmith/*` group pattern. Several models agreeing suggests
  the labels there are borderline (Task 1 flagged about 15 such pages).
- Otherwise the models err toward keeping guides in full (12 to 27 labelled
  guides kept), the cheap direction.
- luna and deepseek wrote their choices with small scripts over the plan
  (prefix rules, or "full" for every remaining review page) after reading
  part of the listing, rather than page by page. The listing was used, but
  the long review tail (about 160 pages) invites bulk decisions.

## Follow-ups

- Bulk decisions on a long review tail: a `--limit` default of 25 still
  led two models to script the rest. Possible: sort the review listing by
  how close a page is to the thresholds, or let `--apply` take `full REST`.
- The five shared "reference stubbed" pages: relabel after a second look,
  or keep as the honest borderline they are.
