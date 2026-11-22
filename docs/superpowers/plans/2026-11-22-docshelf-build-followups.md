# docshelf-build follow-ups (TODO 8.12, 8.14) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the eleven llms.txt follow-ups parked in TODO 8.12, and replace the classify rule set with a `rules-2` that holds up out of sample (TODO 8.14).

**Architecture:** Small, independent fixes in the existing modules (`build_llms.py`, `build_fetch.py`, `build_markdown.py`, `build_html.py`, `build_docvol.py`), each with a regression test; then new thresholds in `build_classify.py` tuned on the calibration and holdout splits and checked on a fresh split.

**Tech Stack:** Python 3 stdlib, `unittest`.

**Spec:** TODO.md items 8.12 and 8.14 (the user, 2026-11-22: "do 8.12-14"); the classify spec `docs/superpowers/specs/2026-11-22-docshelf-build-classify-design.md` for the rules' constraints; the llms.txt spec `docs/superpowers/specs/2026-11-21-docshelf-build-llms-txt-design.md`.

## Global Constraints

- Stdlib only; no network in tests; tests in `tests/test_docshelf_build.py`.
- Version: Task 1 bumps `metadata.version` and `build_core.VERSION` to `0.3.1`; Task 5 bumps both to `0.4.0` (rules-2 changes classify's results). Both always equal.
- Rules ids: the new set is `model:rules-2`; `may_decide` must keep treating every `model:rules-*` id as the rules' own (an old `model:rules-1` page is re-decided by rules-2).
- Classify anti-goal (spec): a wrongly stubbed reference page costs more than a review; when in doubt, review.
- Public repo: no account or machine details, no absolute `/` paths outside made-up test fixtures; fixtures hold keys and numbers only, no page text.
- Commit trailers: `Co-Authored-By: <your model> <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01QT6szzQQtHsMSBHFWoFYJB`. Branch `update/docshelf-build`; do not push.

## Review Focus

1. An index whose links point at other hosts only (social links, CDN files): the plan must still build, with those links visible but not fetched.
2. A Markdown page built to be slow (thousands of `*` or `_`, deep nested lists or quotes): conversion finishes quickly (under 1 s for 50 KB in the test) and never raises.
3. Stored HTML with `onclick=` or `javascript:` links from a hostile page: gone after conversion.
4. A plan made by 0.3.0 (`model:rules-1` choices) classified by rules-2: rules' pages re-decided, agent and person choices untouched.
5. A `.md` retry for a URL with a query string or fragment.

---

### Task 1: Index and fetch fixes (8.12 a, b, c, k), version 0.3.1

**Files:** Modify `skills/docshelf-build/scripts/build_llms.py`, `skills/docshelf-build/scripts/build_fetch.py`, `build_core.py` (VERSION), `skills/docshelf-build/SKILL.md` (version); Test: `tests/test_docshelf_build.py` (class `FollowupIndexTests`).

Decisions:
- (a) A listed page on a host other than `main_host` is planned as a stub (`keep: "stub"`, `why: "llms: other host"`) and never fetched; the rule is the default in `make_llms_plan` (overrides and `manual` still win). Its key keeps today's form (`<host>/<path>`).
- (b) `.txt` links named `robots.txt`, `humans.txt`, `security.txt`, `ads.txt` or `app-ads.txt` (last path segment, case-insensitive) are not sub-indexes: they are skipped like other non-page links and noted nowhere.
- (c) `fetch_llms_page`'s `.md` retry inserts `.md` at the end of the URL path and keeps the query; the fragment is dropped.
- (k) A local root that lists only sub-indexes takes `main_host` from the sub-index links' host (most common), not "".

- [ ] **Step 1: Failing tests** (RF 1, RF 5): `test_other_host_pages_are_stubs` (index with one same-host page and `https://discord.gg/x`: plan has the second as stub with that why; `build` requests only the first page); `test_well_known_txt_not_followed` (index linking `/humans.txt` and `/sub/llms-a.txt`: only the second fetched); `test_md_retry_keeps_query` (`https://x.io/docs/a?lang=py#top` served HTML: retry URL is `https://x.io/docs/a.md?lang=py`); `test_local_root_only_subindexes_main_host` (local root listing two `https://x.io/...txt` sub-indexes: `main_host == "x.io"`).
- [ ] **Step 2:** Run the class: FAIL.
- [ ] **Step 3:** Implement; bump versions to 0.3.1.
- [ ] **Step 4:** Full suite OK.
- [ ] **Step 5:** Commit `docshelf-build 0.3.1: llms.txt index and fetch follow-ups`.

### Task 2: Markdown fixes (8.12 d, e, f, h, i)

**Files:** Modify `skills/docshelf-build/scripts/build_markdown.py`; Test: class `FollowupMarkdownTests`.

Decisions:
- (d) Blockquote lazy continuation (CommonMark): a non-blank line without `>` right after a quote paragraph line continues that paragraph.
- (e) A closing MDX tag matches only its exact name: `</Tab>` does not close `<Tabs>` (match `</Name` followed by `>` or whitespace).
- (f) Indented code inside a list item (4 spaces beyond the item's content column) is code, not a tag-scanned paragraph.
- (h) Emphasis parsing is linear-time: no regex with nested lazy quantifiers over the whole paragraph; e.g. scan delimiter runs, or bound the span (emphasis never crosses 2000 characters).
- (i) Nesting depth (lists, quotes, MDX components) is capped at 32 levels; deeper content is rendered as plain text at the cap.

- [ ] **Step 1: Failing tests** (RF 2): `test_blockquote_lazy` (`"> a\nb\n"` -> one `<blockquote><p>a\nb</p></blockquote>`, whitespace normalised as in MarkdownTests); `test_mdx_exact_closer` (`<Tabs>\n<Tab>x</Tab>\n</Tabs>` keeps `x` and leaves no tag text); `test_list_indented_code` (`- item\n\n      <Card />\n` gives `<pre><code>&lt;Card /&gt;`); `test_emphasis_hostile_is_fast` (`"*a" * 20000` and `"_" * 50000`: md_to_html returns in under 1 s each); `test_deep_nesting_capped` (`"> " * 500 + "x"` and 500-level nested lists: returns, no RecursionError, contains `x`).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite OK (existing MarkdownTests unchanged).
- [ ] **Step 5:** Commit `docshelf-build: Markdown follow-ups (quotes, MDX closers, list code, linear emphasis, depth cap)`.

### Task 3: HTML and docvol fixes (8.12 g, j)

**Files:** Modify `skills/docshelf-build/scripts/build_html.py`, `skills/docshelf-build/scripts/build_docvol.py`; Test: class `FollowupHtmlTests`.

Decisions:
- (j) `_serialize` drops every attribute whose name starts with `on` (case-insensitive), and any `href`/`src` whose value, after stripping whitespace and control characters, starts with `javascript:`, `vbscript:` or `data:` (case-insensitive): the attribute is removed, the element kept.
- (g) The meta and types code duplicated between `write_docvol` and `write_llms_docvol` / `_index` and `_llms_index` moves into two helpers (`_meta(...)`, `_types(entries)`); output unchanged (existing DocvolTests and LlmsDocvolTests pass untouched).

- [ ] **Step 1: Failing tests** (RF 3): `test_on_attributes_dropped` (`<p onclick="x" ONLOAD="y" class="c">t</p>` -> `<p class="c">t</p>`); `test_script_urls_dropped` (`<a href=" JaVaScRiPt:alert(1)">x</a>` and `<a href="data:text/html,..">` lose `href`; `<a href="https://x.io">` keeps it).
- [ ] **Step 2:** FAIL. **Step 3:** Implement both. **Step 4:** Full suite OK.
- [ ] **Step 5:** Commit `docshelf-build: strip event handlers and script URLs; share docvol meta code`. Mark TODO 8.12 done with a one-line summary.

### Task 4: Fresh holdout labels (8.14, labelling)

**Files:** Modify `tests/fixtures/docshelf_build_classify.json`.

The controller provides a built TypeScript sub-index in the scratchpad cache (`built-plans/lc-ts.json`, raw pages in `built-src/lc-ts/`). Label at least 60 of its pages with signals (spread over key prefixes) as `reference` / `guide` (definitions as in the fixture's note), site `langchain-ts`, `"split": "fresh"`. Rules: an agent that never saw the rules' thresholds labels them; no page text.

- [ ] **Step 1:** Label and add the pages; update the note. **Step 2:** JSON parses; `tests.test_public_safety` OK. **Step 3:** Commit `docshelf-build: fresh labelled split for classify (LangChain TypeScript)`.

### Task 5: rules-2 (8.14), version 0.4.0

**Files:** Modify `skills/docshelf-build/scripts/build_classify.py`, `tests/test_docshelf_build.py`, `build_core.py`, `SKILL.md`, `BUILD-llmstxt.md` (the id in the docs), `TODO.md` (8.14 done).

**Interfaces:** `RULES_ID = "model:rules-2"`; `rule_choice(signals) -> "full" | "stub" | "review"` (same signature).

- [ ] **Step 1: Tests:** tune on `calibration` + `holdout` (all sites): agreement on decided pages at least 0.95 per site; at most 1 labelled-reference page stubbed across those splits. Check on `fresh` (never used for tuning, read only after tuning is frozen): report agreement, decided share and stubbed-reference count; the test pins today's fresh figures as floors (regression guard, commented as such). `test_rules1_pages_redecided` (RF 4): a page with `why: "model:rules-1"` is decided by rules-2 and gets `model:rules-2`; `model:agent` and `manual` untouched.
- [ ] **Step 2:** FAIL (old thresholds and id). **Step 3:** Tune; keep thresholds few, named and commented; widen review rather than miss the bar. Report per site and split: decided, agreement, review share, confusion.
- [ ] **Step 4:** Full suite OK; `ci_changed_skills --base main --check-versions` OK.
- [ ] **Step 5:** Commit `docshelf-build 0.4.0: classify rules-2`.
