# docshelf-build classify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `classify NAME` command that sorts an llms.txt docvol's pages into reference (full) and guide (stub): fixed thresholds decide the clear cases, the agent running the skill reviews the rest and writes its choices back with `--apply`.

**Architecture:** A new `scripts/build_classify.py` holds the pure parts (rules on `signals`, which pages the rules may decide, buckets, preview text, review listing, choice parsing and applying). `docshelf_build.py` wires a `classify` subcommand that loads and saves the plan; `build NAME` is unchanged and rebuilds from the page cache. Thresholds are calibrated on a labelled sample committed as a fixture.

**Tech Stack:** Python 3 stdlib only, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-22-docshelf-build-classify-design.md`

## Global Constraints

- Stdlib only; no network in tests; tests in `tests/test_docshelf_build.py` (it already starts with the `selected("docshelf-build")` skip).
- Rules' id: `why: "model:rules-1"` (bump the number whenever thresholds change). Agent id: `why: "model:<ID>"`, ID default `agent`.
- Rules never change a page whose `why` is `manual`, starts `override:`, or starts `model:` but not `model:rules-`.
- A `review` page keeps `keep: "full"`; if its `why` started `model:rules-` it is reset to `"llms: all"` (the llms plan's default rule).
- Agreement of the rules' decided pages with the labels: at least 95% on each site separately; review share aimed under half (reported, not asserted).
- Fixture holds numbers and keys only, no page text (public repo).
- Version 0.3.0 in `skills/docshelf-build/SKILL.md` `metadata.version` and `build_core.VERSION`.
- Public-repo rules (AGENTS.md): no account or machine details, no absolute `/` paths outside made-up test fixtures.
- Commit trailers: `Co-Authored-By: <your model> <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01QT6szzQQtHsMSBHFWoFYJB`. Branch `update/docshelf-build`; do not push (the controller pushes).

## Review Focus

1. A plan whose pages lack `signals` (built before 0.2.0, or `--stub` pages never fetched): classify must count them as "no signals", never crash on a missing key.
2. A decisions file with Windows line endings, trailing spaces, a key containing `#` or spaces in the description: parsed as written, no silent drops.
3. A cached raw page that is HTML, empty, or front matter only: preview is empty or short text, never a traceback.
4. Running `classify` twice, or after `plan SOURCE` re-plans: same buckets, rules' choices kept, agent choices kept.
5. `--apply` naming a page that is `manual` or `override:`: reported as skipped with its line number, other lines applied.

Each line has its test in the task that owns the code (marked "RF n").

---

### Task 1: Calibration sample and fixture

**Files:**
- Create: `tests/fixtures/docshelf_build_classify.json`

**Interfaces:**
- Produces: fixture JSON `{"note": str, "pages": [{"site": "langchain" | "opencode", "key": str, "label": "reference" | "guide", "signals": {...as in the plan...}}]}`

The controller provides `DOCSHELF_CACHE_DIR` holding the 0.2.0 trial's
caches: plans `built-plans/lc-python.json` (LangChain `build/python.txt`,
240 pages) and `built-plans/opencode.json` (90 pages), raw pages under
`built-src/<name>/` (read with `PageCache(root).get(key) -> (text, kind)`).

- [ ] **Step 1:** Pick at least 120 pages with `signals`, at least 40 from each site, spread over sections (not the first N). Read each cached page and label it `reference` (an agent looks things up in it: API pages, parameters, options, config keys, error lists, CLI flags, integration pages that are mostly signatures and settings) or `guide` (tutorials, concepts, overviews, how-tos told in steps, marketing, changelogs/release notes). A page that is both goes by what most of it is.
- [ ] **Step 2:** Write the fixture: keys sorted per site, signals copied from the plan, `note` saying what the labels mean and the date. No page text.
- [ ] **Step 3:** `python3 -c "import json;d=json.load(open('tests/fixtures/docshelf_build_classify.json'));print(len(d['pages']))"` prints 120 or more; `python3 -m unittest tests.test_public_safety` OK.
- [ ] **Step 4:** Commit `docshelf-build: labelled calibration sample for classify`.

### Task 2: Rules

**Files:**
- Create: `skills/docshelf-build/scripts/build_classify.py`
- Test: `tests/test_docshelf_build.py` (new class `ClassifyRulesTests`)

**Interfaces:**
- Consumes: Task 1 fixture.
- Produces: `RULES_ID = "model:rules-1"`; `rule_choice(signals: dict) -> str` returning `"full"`, `"stub"` or `"review"`.

- [ ] **Step 1: Failing tests**

```python
class ClassifyRulesTests(unittest.TestCase):
    def test_clear_reference(self):
        self.assertEqual(rule_choice({"words": 900, "code_ratio": 0.6, "you_per_1k": 1.0,
                                      "steps": 0, "signature_lines": 40, "headings": 12,
                                      "tables": 3}), "full")

    def test_clear_guide(self):
        self.assertEqual(rule_choice({"words": 1500, "code_ratio": 0.05, "you_per_1k": 25.0,
                                      "steps": 8, "signature_lines": 0, "headings": 6,
                                      "tables": 0}), "stub")

    def test_thin_page_reviewed(self):
        self.assertEqual(rule_choice({"words": 40, "code_ratio": 0.0, "you_per_1k": 0.0,
                                      "steps": 0, "signature_lines": 0, "headings": 0,
                                      "tables": 0}), "review")

    def test_missing_signal_keys_reviewed(self):  # RF 1
        self.assertEqual(rule_choice({}), "review")

    def test_fixture_agreement_per_site(self):
        data = json.load(open(os.path.join(HERE, "fixtures", "docshelf_build_classify.json")))
        for site in ("langchain", "opencode"):
            pages = [p for p in data["pages"] if p["site"] == site]
            decided = [(rule_choice(p["signals"]), p["label"]) for p in pages]
            decided = [(c, l) for c, l in decided if c != "review"]
            agree = sum((c == "full") == (l == "reference") for c, l in decided)
            self.assertGreaterEqual(agree / max(1, len(decided)), 0.95, site)
            self.assertGreater(len(decided), 0, site)
```

(`HERE` is the tests folder; add it if the file has no such name.)

- [ ] **Step 2:** Run `python3 -m unittest tests.test_docshelf_build.ClassifyRulesTests -v`: FAIL (ImportError).
- [ ] **Step 3:** Implement `rule_choice` with thresholds chosen from the fixture: `full` for clear reference, `stub` for clear guide, otherwise `review` (thin pages: few `words`; any missing key reads as 0). Tune until per-site agreement is at least 0.95; if impossible, widen the review band, never lower the bar. Print (in the task report, not the code) each site's agreement and review share. Keep the threshold constants named at the top of the module with a one-line comment each.
- [ ] **Step 4:** Run the class: PASS. Run the whole file: OK.
- [ ] **Step 5:** Commit `docshelf-build: classify rules calibrated on the labelled sample`.

### Task 3: Plan buckets, preview and review listing

**Files:**
- Modify: `skills/docshelf-build/scripts/build_classify.py`
- Test: `tests/test_docshelf_build.py` (class `ClassifyPlanTests`)

**Interfaces:**
- Consumes: `rule_choice`, `RULES_ID`; `build_markdown.front_matter(text) -> (meta, body)`; `build_html.main_content(html) -> str`; `PageCache.get(key) -> Optional[(text, kind)]`.
- Produces:
  - `may_decide(page: dict) -> bool` (has `signals`; `why` not `manual`, not `override:*`, not `model:*` unless `model:rules-*`).
  - `run_rules(plan: dict) -> None`: for each page `may_decide` allows, sets `keep`/`why` per the Global Constraints (`full`/`stub` -> `why = RULES_ID`; `review` -> `keep "full"`, `why` reset to `"llms: all"` if it was a rules id). Idempotent.
  - `bucket(page: dict) -> str`: one of `"reference"`, `"stub"`, `"person"`, `"agent"`, `"review"`, `"no signals"`. No signals wins first; `manual`/`override:` -> person; `model:` not rules -> agent; rules id -> reference or stub by `keep`; else review.
  - `counts(plan) -> Dict[str, int]` over those six buckets (every bucket present, sum = number of pages).
  - `preview(text: str, kind: str, n: int = 200) -> str`: page text without front matter, MDX/HTML tags and the first heading, whitespace collapsed, cut to n characters.
  - `review_lines(plan: dict, get_raw: Callable[[str], Optional[Tuple[str, str]]], offset: int, limit: int) -> List[str]`: for review pages in plan order from offset: line 1 `KEY   [SECTION] TITLE` (`[SECTION] ` omitted when none), line 2 `  words=W code=C you=Y sig=S steps=T tables=B`, line 3 `  > PREVIEW` (omitted when empty).

- [ ] **Step 1: Failing tests** (plan pages built with a small helper `pg(why="llms: all", keep="full", signals=REF)`):
  - `test_may_decide`: True for `llms: all`, `model:rules-1`; False for `manual`, `override: a/*`, `model:agent`, and a page without `signals`.
  - `test_run_rules_idempotent` (RF 4): plan with one clear-reference, one clear-guide, one thin page; after `run_rules` keeps are `full`/`stub`/`full`, whys `model:rules-1`/`model:rules-1`/`llms: all`; a second `run_rules` leaves the plan equal.
  - `test_run_rules_leaves_people_and_agents`: `manual` stub with guide signals and `model:agent` full with guide signals unchanged.
  - `test_counts_add_up` (RF 1): six-page plan covering every bucket, including one page with no `signals` key; `counts` has all six keys and sums to 6.
  - `test_preview_markdown`: `"---\ntitle: X\n---\n# X\n\nUse <Tabs>the thing</Tabs> here.\n"` -> `"Use the thing here."`.
  - `test_preview_html_and_empty` (RF 3): HTML `"<html><body><main><h1>T</h1><p>Body text</p></main></body></html>"` with kind `"html"` -> `"Body text"`; `""` and `"---\ntitle: X\n---\n"` -> `""`.
  - `test_review_lines_format_and_paging`: two review pages; `review_lines(plan, get, 0, 1)` is exactly three lines for the first page in the format above (`code=0.33` printed as stored); offset 1 gives the second; a page whose `get` returns None has no `>` line.
- [ ] **Step 2:** Run `ClassifyPlanTests`: FAIL.
- [ ] **Step 3:** Implement the six functions.
- [ ] **Step 4:** Run the class and the whole file: OK.
- [ ] **Step 5:** Commit `docshelf-build: classify buckets and review listing`.

### Task 4: Parsing and applying choices

**Files:**
- Modify: `skills/docshelf-build/scripts/build_classify.py`
- Test: `tests/test_docshelf_build.py` (class `ClassifyApplyTests`)

**Interfaces:**
- Produces:
  - `parse_choices(text: str) -> Tuple[List[Tuple[int, str, str, Optional[str]]], List[str]]`: (line number, keep, key, description or None) and error strings `"line N: ..."`. A line is `full KEY` or `stub KEY [description]` (key = second whitespace-separated field; description = rest of line, stripped, None if empty); blank lines and lines whose first non-space character is `#` are skipped; `\r` stripped.
  - `apply_choices(plan: dict, choices, model_id: str) -> Tuple[int, List[str]]`: applied count and messages `"line N: KEY: unknown page"` / `"line N: KEY: decided by a person (manual|override), skipped"`. Sets `keep`, `why = "model:" + model_id`, and `description` when given. Last line wins for a repeated key.

- [ ] **Step 1: Failing tests**
  - `test_parse_basic_and_crlf` (RF 2): `"full a/b\r\nstub c/d  Short note here  \r\n\n# x\n"` -> `[(1, "full", "a/b", None), (2, "stub", "c/d", "Short note here")]`, no errors.
  - `test_parse_errors`: `"keep a\nfull\nstub\n"` -> no choices, three errors naming lines 1, 2, 3.
  - `test_key_with_hash` (RF 2): `"full a#b"` -> key `"a#b"`.
  - `test_apply` (RF 5): plan with pages `a` (rules), `b` (`manual`), `c` (`override: c*`); choices stub a "Guide", full b, full c, full zz -> applied 1; messages for lines 2, 3 (skipped) and 4 (unknown); `a` is `stub`, `why "model:tester"`, description `"Guide"`.
  - `test_apply_overwrites_agent`: page with `model:old` -> `model:new`.
- [ ] **Step 2:** Run: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run class and file: OK.
- [ ] **Step 5:** Commit `docshelf-build: parse and apply classify choices`.

### Task 5: `classify` command, docs, version 0.3.0

**Files:**
- Modify: `skills/docshelf-build/scripts/docshelf_build.py` (parser, `main`, `DESCRIPTION` loop line)
- Modify: `skills/docshelf-build/scripts/build_core.py` (`VERSION = "0.3.0"`)
- Modify: `skills/docshelf-build/SKILL.md` (`version: "0.3.0"`), `skills/docshelf-build/BUILD-llmstxt.md`, `AGENTS.md` (docshelf-build entry), `TODO.md` (8.11 done)
- Test: `tests/test_docshelf_build.py` (class `ClassifyCliTests`, reusing `LlmsCliTests`' fake site pattern)

**Interfaces:**
- Consumes: everything in `build_classify`; `load_plan`, `save_plan`, `_plan_path`, `PageCache`, `src_dir`.
- Produces: CLI `classify NAME [--offset K] [--limit N] [--apply FILE] [--model ID]`.

Behaviour (spec "Command" and "Applying choices"):
- No plan: exit 2 (as `build NAME` reports it). `kind != "llms"`: exit 2, message `classify works on llms.txt docvols; Sphinx plans use the role rule`. No page has `signals`: exit 2, `build NAME first`.
- Without `--apply`: `run_rules`, save, print `counts` as one line (`reference R, stub S, review V, decided by a person P, by an agent A, no signals N`), then `review_lines` (default offset 0, limit 25), then the next-step lines:
  `next: write one line per page to a file: "full KEY" or "stub KEY [short description]",`
  `then run: classify NAME --apply FILE --model YOUR_MODEL_ID, then classify NAME again`
  and, when more review pages follow the batch, `more: classify NAME --offset K+limit`. No review pages: `nothing left to review; run: build NAME`.
- With `--apply FILE` (`-` = stdin): parse, apply, save, print `applied N`, each message, and `left for review: V`. Exit 2 when no line parsed (and nothing applied); otherwise 0.

- [ ] **Step 1: Failing tests**
  - `test_refuses_sphinx_and_unbuilt`: a Sphinx plan -> exit 2 with the message; an llms plan before `build` -> exit 2 `build NAME first`.
  - `test_classify_apply_build_offline`: fake site with one reference-looking page and one guide-looking page and one thin page; `build`, then `classify` -> output has the counts line and one review block for the thin page; write a choices file `stub <thin> Short`; `classify --apply FILE --model t` -> `applied 1`, `left for review: 0`; `build NAME` again with an opener that fails every page request (index requests still answered) succeeds and the stored HTML of the thin page is a stub containing `Short` (cache used, no page downloads).
  - `test_replan_keeps_choices` (RF 4): after the above, `plan SOURCE --name NAME` then `classify` -> same counts; the agent's page still `model:t`.
  - `test_apply_stdin_and_bad_file`: `--apply -` with stdin patched; a file of only bad lines -> exit 2.
- [ ] **Step 2:** Run `ClassifyCliTests`: FAIL.
- [ ] **Step 3:** Implement the subcommand; update `DESCRIPTION` with `classify NAME` in the loop list.
- [ ] **Step 4:** Docs: `BUILD-llmstxt.md` section "Sorting reference from tutorials" becomes the loop (build, `classify NAME`, review batch, write choices, `--apply`, rerun `classify`, `build NAME`), says the rules never touch `manual`/override/agent choices, that patterns go through `plan --full/--stub` (a hand-edited plan pattern loses to an earlier choice), and that `--reset` drops agent choices. `SKILL.md`: version only. `AGENTS.md`: one sentence on classify (rules + agent, `model:rules-1`, fixture). `TODO.md`: mark 8.11 done with a pointer to the spec.
- [ ] **Step 5:** Run `python3 -m unittest discover -s tests` (all OK) and `python3 scripts/ci_changed_skills.py --base main --check-versions` (OK).
- [ ] **Step 6:** Commit `docshelf-build 0.3.0: classify command`.

### Task 6: Small-model trial (controller; network)

- [ ] Copy `docs/trials/2026-11-22-docshelf-build-detect/` to `docs/trials/2026-11-22-docshelf-build-classify/`; the llms prompt only, adding "keep only reference material; drop tutorials" to the user's request. Score: classify and `--apply` calls, pages reviewed, agreement with the fixture labels where keys overlap, docvol size before and after, answer correct. Write the README with the results, commit.
