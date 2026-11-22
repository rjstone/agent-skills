# Trial: docshelf-build 0.2.0 routing, three opencode models, two site types

Date: 2026-11-22. opencode 2.3.x, `opencode run --standalone --archived --auto
--format json`, one run per model and site. Skill under test:
`skills/docshelf-build` 0.2.0 (branch `update/docshelf-build`, PR #31): a
`SKILL.md` that only finds the site type (`detect`) and points to
`BUILD-sphinx.md` or `BUILD-llmstxt.md`. Paired with `docshelf` 0.9.0.

## Setup

- `run_trials.sh PROVIDER/MODEL...` is the 2026-11-21 Yosys trial's runner
  (`../2026-11-21-docshelf-build-yosys/`) with a prompt per site and no
  baseline arm (that trial already compared against no skill). Every run is
  in the `sandboxing` skill's bubblewrap sandbox: empty environment,
  unprivileged user, private `/work` as `HOME`, network through the egress
  proxy, placeholder provider keys. Both skills copied to
  `/work/.claude/skills/`.
- Models: `opencode-go/gpt-6-luna`, `opencode-go/deepseek-v4.1-flash`,
  `nous/stepfun/step-3.7-flash`. No retries were needed.
- Prompts (neither names a skill or a build type):
  - **sphinx**: the Yosys prompt of the 2026-11-21 trial (offline docs, then
    the options of `opt_clean`).
  - **llms**: "I want the LangChain documentation (https://docs.langchain.com/)
    available offline ... I only use the Python SDK. Set that up, then using
    only the offline copy tell me what values create_agent's response_format
    parameter accepts, and what happens when I pass a schema type directly."
    The site's root `llms.txt` lists 1,407 pages; its Python sub-index 240.
- `score_trials.py` reads the JSON events (tool calls, not the model's
  claims). **Routing passes** when the run opened the BUILD file for its site
  and not the other one. `answer_key.md` has both answers.

## Results

| Run | Files opened (docshelf-build) | detect | Plan / build SOURCE | Answer | Wall time | Tool calls |
|---|---|---|---|---|---|---|
| luna, sphinx | SKILL.md > BUILD-sphinx.md | yes | site URL; rebuilt with `--all` | correct | 192 s | 22 |
| deepseek, sphinx | SKILL.md > BUILD-sphinx.md | yes | site URL | correct | 116 s | 27 |
| step, sphinx | SKILL.md > BUILD-sphinx.md | yes | site URL | correct | 105 s | 13 |
| luna, llms | SKILL.md > BUILD-llmstxt.md | yes | root plan, then `build/python.txt` sub-index | correct | 228 s | 32 |
| deepseek, llms | SKILL.md > BUILD-llmstxt.md | yes | root plan, then `build/python.txt` sub-index | correct | 255 s | 26 |
| step, llms | SKILL.md > BUILD-llmstxt.md | yes (twice) | root plan, then `build/python.txt` sub-index | correct | 308 s | 26 |

Routing passed 6 of 6: every run ran `detect`, opened only its own
type's BUILD file, built, and then answered from `docshelf.py search` /
`show` (2 to 11 queries). Every answer passed its checks; no run invented an
`opt_clean` option or `response_format` value.

All three llms runs planned the root index, saw the 1,407-page warning and
the index tree, and re-planned with the Python sub-index as SOURCE before
building (240 pages, 16.8 to 18.0 MB of docshelf cache including the page
cache). None built the whole site.

## Observations

- Extra manual probes despite `detect`, in 4 of 6 runs: deepseek downloaded
  `objects.inv` with `curl` (sphinx) and fetched `llms.txt` with `urllib`
  (llms); step fetched `llms.txt` with `curl`, opened the Yosys site with
  `webfetch`, and checked `devdocs.io/yosys` with `webfetch` instead of
  `docshelf.py sources`. `BUILD-sphinx.md` still has a "By hand: the site is
  Sphinx when `objects.inv` downloads" sentence that may invite the first.
- step ran `detect` a second time on a made-up `/en/latest/` path of the
  LangChain site (harmless; the first result was used).
- luna-sphinx rebuilt with `--all` after the default plan, as in the 0.1.0
  trial.
- Compared with the 0.1.0 Yosys trial (same models and prompt, skill arm):
  wall times 105 to 192 s now vs 93 to 165 s then, tool calls 13 to 27 vs
  15 to 25; the extra `detect` call and BUILD file read cost little.
