# `decisions` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `skills/decisions/`: a skill plus a stdlib System One client
(`decide.py`) that lets any agent set up, privacy-check, calibrate and run a
cheap decision model as a pre-filter, for novice and expert users.

**Architecture:** One importable, CLI-capable Python file talks to every
System One host through a provider table; a JSON setup file in the user's
project holds questions, reference text, model, cutoffs, calibration and
privacy confirmations. `SKILL.md` teaches the workflow (fit check, interview,
provider, privacy, calibrate or cautious, run, hand over); `references/` holds
the detail; `scripts/adapters/` holds untested sample converters for other
wire formats.

**Tech Stack:** Python 3.9+ standard library only (`urllib.request`, `json`,
`sqlite3`, `csv`, `hashlib`, `argparse`, `http.server` in tests); stdlib
`unittest`; Agent Skills `SKILL.md`.

**Spec:** `docs/superpowers/specs/2026-11-23-decisions-design.md`

## Global Constraints

- Branch `skill/decisions`; push there; squash-merge to `main` only after the user's review (`AGENTS.md` "Adding a skill").
- Stdlib only; Python 3.9+; must run on Linux, macOS and Windows (no `fcntl`, no POSIX-only paths).
- No account names, private repo names, private hostnames, home paths or secrets anywhere; placeholders like `<user>`, `~`.
- Keys only from env vars, sent in a header, never printed, never in argv, scrubbed from every error string.
- Frontmatter order: `name`, `description` ("Use when ..."), `compatibility`, `license: MIT`, `metadata` (`author: Robert Stone`, `source: https://github.com/rjstone/agent-skills`, `version: "0.1.0"`).
- `decide.py` has `VERSION = "0.1.0"`, equal to `metadata.version`.
- Every `references/*.md` is linked from `SKILL.md`; no nested `SKILL.md`.
- `tests/test_decisions.py` starts with the `selected("decisions")` skip and makes no network calls.
- Scripts are invoked through the interpreter in prose: `python3 scripts/decide.py ...`.
- Text only in v1: no image input, no `box` questions.
- Built-in providers are the verified ones only: `typesafe`, `openrouter`, `opencode`, `asi`, `perplexity` (live call verified 2026-11-23).
- Cautious-mode starting defaults: noul reject below 0.05, pass above 0.90; choice/score `min_confidence` 0.6; score reject below 0.5, pass above `levels - 1.5`.
- Calibration defaults: target recall 0.95 (per item), target precision 0.90; warn below 20 labels or fewer than 3 for any class.
- Default rate 2 calls/s, workers 1, timeout 60 s.

## Review Focus

1. A provider returns 200 with an answer missing a question, or a NaN/out-of-range number: expect a failed hop (fallback), never a silent `pass`. Test in Task 3.
2. An item whose text contains the API key (pasted by mistake) or an error body echoing the key: expect the key scrubbed from all output and errors. Test in Task 2.
3. A JSONL/CSV input with a blank line, a missing `id`, or a non-UTF-8 byte: expect a clear per-line error naming the line, other items still processed. Test in Task 6.
4. The setup file is edited while a run is going, or the process is killed mid-write: expect no truncated setup file (atomic replace). Test in Task 5.
5. A fallback hop to a provider with no privacy entry: expect refusal of that hop, reported, not a send. Test in Task 3.

---

### Task 1: Baseline scenarios without the skill (RED)

**Files:**
- Create: `skills/decisions/evals/scenarios.md`
- Create: `skills/decisions/evals/baseline-2026-11.md`

**Interfaces:**
- Produces: the rubric R1-R8 and the baseline failures that Tasks 8-9 must fix.

- [ ] **Step 1: Write `evals/scenarios.md`** with the five user requests from the spec's Intent section, verbatim, plus this rubric (each scored yes/no per run):
  - R1 calls a System One endpoint (`/v1/systemone` or `/v1/decisions`), not a chat endpoint
  - R2 runs the three privacy confirmations before any real data is sent
  - R3 offers calibration; if declined, warns and uses an over-including mode
  - R4 puts domain reference text and examples in every request
  - R5 routes uncertain items to review instead of dropping them
  - R6 does a fit check (item count, task shape)
  - R7 explains in plain language to a novice
  - R8 ties calibration to one model family
- [ ] **Step 2: Run each scenario twice** with a fresh general-purpose subagent (no skill loaded, told not to make network calls or write files outside the scratchpad, asked to respond as it would to the user and draft its first steps and code). Ten runs.
- [ ] **Step 3: Record in `evals/baseline-2026-11.md`** the rubric score per run and verbatim quotes of each failure (wrong endpoint, missing privacy step, and so on).
- [ ] **Step 4: Commit**

```bash
git add skills/decisions/evals
git commit -m "decisions: baseline scenarios and results without the skill"
```

### Task 2: Provider table, request building, redaction

**Files:**
- Create: `skills/decisions/scripts/decide.py`
- Create: `tests/test_decisions.py`

**Interfaces:**
- Produces:
  - `VERSION = "0.1.0"`
  - `PROVIDERS: dict[str, dict]`, keys per entry: `endpoint` (full URL), `key_env` (list of env var names, first found wins), `models_url` (str or None), `default_model`, `docs`, `verified` (bool)
  - `FAMILIES: dict[str, str]` model-id prefix -> family; `family_of(model: str) -> str` (longest matching prefix, else the id itself)
  - `class DecisionError(Exception)` with attribute `kind` in `{"request", "fallback", "privacy", "config"}`
  - `redact(text: str, *secrets: str) -> str`
  - `build_state(reference: str | None, item) -> object`
  - `build_request(model: str, state, questions: dict) -> dict`
  - `provider_config(name: str, setup: dict | None = None) -> dict` (setup `providers` block entries are merged over built-ins and get `verified: False`)
  - `api_key(cfg: dict) -> str | None`

- [ ] **Step 1: Write the failing tests** (file header: the `selected("decisions")` skip, load `decide.py` with `importlib` like `test_provider_onboarding.py`):
  - `test_version_constant`: `decide.VERSION == "0.1.0"`
  - `test_builtin_providers`: keys are exactly `{"typesafe", "openrouter", "opencode", "asi", "perplexity"}`; endpoints equal `https://api.typesafe.ai/v1/systemone`, `https://openrouter.ai/api/v1/systemone`, `https://opencode.ai/inference/systemone/v1/systemone`, `https://inference.asicloud.cudos.org/v1/systemone`, `https://api.perplexity.ai/v1/decisions`; `key_env` for typesafe is `["TYPESAFE_AI_API_KEY", "TYPESAFE_API_KEY"]`, perplexity `["PERPLEXITY_API_KEY"]`, asi `["ASI_API_KEY"]`
  - `test_family_of`: `jev-1.13-free`, `jev-latest`, `typesafe/jev-1.14`, `~typesafe/jev-latest` -> `"jev"`; `perplexity/pplx-decider-flash-v1.3:free` and `pplx-decider-latest` -> `"pplx-decider"`; `liquid/d1.2` -> `"liquid-d1"`; `unknown/model` -> `"unknown/model"`
  - `test_build_state_with_reference`: `build_state("defs", {"text": "x"}) == {"reference": "defs", "item": {"text": "x"}}`; `build_state(None, "x") == "x"`
  - `test_build_request_shape`: keys exactly `{"model", "state", "questions"}`
  - `test_redact`: `redact("Bearer sk-abc123 failed sk-abc123", "sk-abc123")` contains no `sk-abc123`; also scrubs `Authorization: Bearer <anything>` patterns with no secret given
  - `test_setup_provider_block_unverified`: a setup with `providers: {"liquid": {...}}` yields `provider_config("liquid", setup)["verified"] is False`
- [ ] **Step 2: Run** `python3 -m unittest tests.test_decisions -v`; expected FAIL (file or names missing).
- [ ] **Step 3: Implement** the names above in `decide.py`. Default models: typesafe `jev-latest`, openrouter `typesafe/jev-1.14`, opencode `jev-1.13-free`, asi `super-decider`, perplexity `pplx-decider-latest`. `models_url`: typesafe `https://api.typesafe.ai/v1/models`, others `None` unless confirmed. All five built-ins are `verified: True` (live calls 2026-11-23).
- [ ] **Step 4: Run** the tests; expected PASS.
- [ ] **Step 5: Commit** `decisions: provider table, request building, redaction`.

### Task 3: HTTP call, answer validation, fallback, privacy gate

**Files:**
- Modify: `skills/decisions/scripts/decide.py`
- Modify: `tests/test_decisions.py`

**Interfaces:**
- Consumes: Task 2 names.
- Produces:
  - `FALLBACK_STATUSES = {401, 402, 403, 429}` (plus any 5xx)
  - `post_json(url: str, key: str | None, payload: dict, timeout: float) -> dict` (raises `DecisionError`: kind `fallback` for network, timeout, 5xx, `FALLBACK_STATUSES`; kind `request` for other 4xx, message includes the provider's error text, redacted)
  - `validate_answers(answers: dict, questions: dict) -> None` (raises kind `fallback` on a missing question, a wrong `type`, a non-finite number, a probability outside [0, 1])
  - `evaluate(state, questions: dict, *, provider: str, model: str | None = None, fallbacks: list[dict] = (), setup: dict | None = None, timeout: float = 60, test_data: bool = False) -> tuple[dict, dict]`; meta keys: `provider`, `model_requested`, `model_returned`, `usage`, `hops` (list of `"name: reason"` strings for failed hops)
  - `check_privacy(provider: str, setup: dict | None, test_data: bool) -> None` (raises kind `privacy`)

- [ ] **Step 1: Write the failing tests** using an in-test `FakeSystemOne` (`http.server.ThreadingHTTPServer` on `127.0.0.1:0`, scripted responses per path, records request bodies and headers); tests point provider endpoints at it through a setup `providers` block:
  - `test_evaluate_success_meta`: returns answers; `meta["model_returned"]` is the server's `model` field
  - `test_bearer_header_sent_from_env`: with `TYPESAFE_AI_API_KEY=placeholder` the request has `Authorization: Bearer placeholder`
  - `test_fallback_on_429_then_success`: first hop 429, second hop 200; `meta["provider"]` is the second; `meta["hops"]` has one entry
  - `test_no_fallback_on_422`: raises kind `request`; second hop never called
  - `test_200_without_answers_retried_once_then_fallback`: same hop called twice, then the next hop
  - `test_invalid_answer_is_fallback` (Review Focus 1): answer missing a question, `noul: NaN`, `noul: 1.5` each -> next hop
  - `test_each_hop_uses_its_own_model`: primary `model="a"`, fallback `{"provider": ..., "model": "b"}`; recorded bodies have `a` then `b`
  - `test_privacy_refused_without_entry`: kind `privacy`, nothing sent; `test_data=True` sends
  - `test_fallback_hop_without_privacy_skipped` (Review Focus 5): hop reported in `hops` as refused, never contacted
  - `test_fallback_must_share_family`: fallback with another family raises kind `config` before any send
  - `test_key_not_in_errors` (Review Focus 2): server echoes the Authorization header in a 400 body; the raised message does not contain the key
- [ ] **Step 2: Run**; expected FAIL.
- [ ] **Step 3: Implement** with `urllib.request`; User-Agent `decide.py/<VERSION>`; JSON `Content-Type`; catch `HTTPError`, `URLError`, `TimeoutError`, `OSError`, `http.client.HTTPException`, `ValueError` (bad JSON). `evaluate` uses `setup["model"]` / `setup["fallbacks"]` when given; `model` argument overrides the primary hop only.
- [ ] **Step 4: Run**; expected PASS.
- [ ] **Step 5: Commit** `decisions: evaluate with fallback, answer validation, privacy gate`.

### Task 4: Routing and cautious mode

**Files:**
- Modify: `skills/decisions/scripts/decide.py`, `tests/test_decisions.py`

**Interfaces:**
- Consumes: answers from Task 3.
- Produces:
  - `CAUTIOUS = {"noul": {"reject_below": 0.05, "pass_above": 0.90}, "min_confidence": 0.6, "score_reject_below": 0.5, "score_pass_margin": 1.5}`
  - `is_cautious(setup: dict, model_returned: str | None = None) -> tuple[bool, str]` (true when `policy.mode != "calibrated"`, no `calibration`, or `family_of(model_returned) != family_of(calibration["model"])`; the str is the reason)
  - `effective_rules(policy: dict, questions: dict, cautious: bool) -> list[dict]`
  - `route(answers: dict, rules: list[dict]) -> str` in `{"pass", "review", "reject"}`

- [ ] **Step 1: Write the failing tests:**
  - `test_route_noul_bands`: rule reject_below 0.2 / pass_above 0.8: 0.1 reject, 0.5 review, 0.9 pass
  - `test_route_any_reject_wins_then_review`: two rules, one reject one pass -> reject; one review one pass -> review
  - `test_route_low_confidence_reviews`: score above `pass_above` but confidence 0.4 with `min_confidence` 0.5 -> review
  - `test_route_score_uses_expected_score`: `score` 2.6 with pass_above 2.5 -> pass regardless of argmax in `probabilities`
  - `test_choice_rule_maps_names`: rule `{"question": "team", "routes": {"ops": "pass", "sales": "reject"}, "min_confidence": 0.7}`; unknown choice -> review
  - `test_question_without_rule_is_informational`: does not affect the route
  - `test_cautious_widens_never_narrows`: user noul rule 0.10/0.70 -> effective 0.05/0.90; user rule 0.01/0.95 -> stays 0.01/0.95; min_confidence max(user, 0.6)
  - `test_cautious_score_defaults`: 4-level score with no user bounds -> reject_below 0.5, pass_above 1.5 (= 4 - 1 - 1.5)
  - `test_is_cautious_reasons`: no calibration -> True; calibrated jev, answered `jev-1.14.0` -> False; answered `pplx-decider-...` -> True with "family" in the reason
- [ ] **Step 2: Run**; FAIL. **Step 3: Implement.** **Step 4: Run**; PASS.
- [ ] **Step 5: Commit** `decisions: routing and cautious mode`.

### Task 5: Setup file, privacy record, cache

**Files:**
- Modify: `skills/decisions/scripts/decide.py`, `tests/test_decisions.py`

**Interfaces:**
- Produces:
  - `load_setup(path: str) -> dict` (raises kind `config` naming the missing key; required: `questions`, `provider`; `model` defaults to the provider default)
  - `save_setup(path: str, setup: dict) -> None` (write to a temp file in the same folder, then `os.replace`)
  - `record_privacy(setup: dict, provider: str, policy_url: str, summary: str, today: str) -> dict`
  - `cache_key(provider: str, model: str, questions: dict, reference: str | None, item) -> str` (SHA-256 hex of canonical JSON, `sort_keys=True`)
  - `class Cache` with `__init__(self, path: str | None)` (`None` = disabled), `get(key) -> dict | None`, `put(key, answers: dict, model_returned: str) -> None`; `sqlite3`, one table, created on first use
  - Default cache path: `<setup file stem>.cache.sqlite` beside the setup file

- [ ] **Step 1: Write the failing tests:**
  - `test_load_setup_missing_questions_names_key`
  - `test_save_setup_atomic` (Review Focus 4): patch `os.replace` to raise; the original file is unchanged and no partial file remains
  - `test_record_privacy_fields`: entry has `confirmed`, `policy_url`, `summary`
  - `test_cache_key_changes_with_questions_and_reference`, `test_cache_key_stable_across_dict_order`
  - `test_cache_roundtrip` in a temp dir; `Cache(None).get(k) is None`
- [ ] **Step 2: Run**; FAIL. **Step 3: Implement.** **Step 4: Run**; PASS.
- [ ] **Step 5: Commit** `decisions: setup file, privacy record, cache`.

### Task 6: CLI (`run`, `ask`, `privacy`, `providers`, `models`)

**Files:**
- Modify: `skills/decisions/scripts/decide.py`, `tests/test_decisions.py`

**Interfaces:**
- Consumes: Tasks 2-5.
- Produces:
  - `read_items(source: str, fmt: str | None = None, id_field: str = "id", text_field: str | None = None) -> Iterator[tuple[str, object, str | None]]` yielding `(id, item, error)`; formats `jsonl`, `csv`, `dir` (one item per `*.txt`/`*.md` file, id = file name), detected from the extension or a directory
  - `main(argv: list[str] | None = None) -> int`
  - Subcommands and flags exactly as the spec's `scripts/decide.py` section: `run SETUP --input SRC [--format] [--out FILE] [--state TEXT]`, `ask [SETUP] --state TEXT (--yes Q | --choice NAME[=DESC]... | --score LEVEL...) [--test-data]`, `privacy SETUP --provider X --policy-url URL --summary TEXT`, `providers`, `models [--provider X]`; common `--dry-run --provider --model --timeout --workers --rate --json --no-cache --test-data`
  - Output line per item: `{"id", "route", "answers", "model", "provider", "cached", "error"}`; summary on stderr: counts per route, `mode: calibrated|cautious (<reason>)`, tokens in/out, cost when reported, fallbacks used
  - Exit codes: 0 ok, 2 usage/config, 3 privacy refused, 4 all providers failed

- [ ] **Step 1: Write the failing tests** (`main([...])` with captured stdout/stderr and the fake server):
  - `test_run_jsonl_routes_and_summary`: 3 items -> 3 output lines with routes; stderr contains `mode: cautious`
  - `test_run_bad_lines_reported` (Review Focus 3): blank line skipped silently; line without `id` and a non-UTF-8 line each produce an `error` row naming the line number; valid items still scored
  - `test_run_csv_and_dir_inputs`
  - `test_run_uses_cache_second_time`: second run makes no HTTP calls, rows have `cached: true`
  - `test_dry_run_sends_nothing_and_needs_no_key`: prints the first payload; server receives nothing; exit 0
  - `test_run_refuses_without_privacy_exit_3`
  - `test_ask_requires_setup_or_test_data`
  - `test_providers_lists_names_only`: with a key set, output names the provider and env var name, never the value
  - `test_privacy_subcommand_writes_entry`
- [ ] **Step 2: Run**; FAIL.
- [ ] **Step 3: Implement.** Throttle with a simple monotonic-clock limiter shared by workers (`concurrent.futures.ThreadPoolExecutor` when `--workers > 1`). `ask` prints plain language: noul `Yes - 97% likely`; choice `ops (97%), next: billing (1%)`; score `2.6 of 0-4 ("plausible"-"strong"), confidence 0.82`.
- [ ] **Step 4: Run**; PASS.
- [ ] **Step 5: Commit** `decisions: command line`.

### Task 7: Calibration

**Files:**
- Modify: `skills/decisions/scripts/decide.py`, `tests/test_decisions.py`

**Interfaces:**
- Consumes: `evaluate`, `route`, `effective_rules`, `save_setup`.
- Produces:
  - `auroc(values: list[float], positives: list[bool]) -> float | None` (Mann-Whitney, ties count half; None if one class is empty)
  - `is_good(expected: dict, good_if: list[dict]) -> bool`; conditions `{"question", "is": bool}`, `{"question", "at_least": number}`, `{"question", "in": [names]}`
  - `suggest_rules(results: list[dict], questions: dict, good_if: list[dict], target_recall: float, target_precision: float) -> list[dict]` (each `source: "calibration"`)
  - `calibrate(setup: dict, labels: list[dict], *, target_recall=0.95, target_precision=0.90, replace_user_rules=False, scorer=evaluate) -> dict` returning the report; sets `setup["calibration"]` and merges rules; `mode` becomes `"calibrated"`
  - CLI: `calibrate SETUP --labels FILE [--target-recall] [--target-precision] [--replace-user-rules] [--check]` (`--check` re-scores and compares to the stored calibration without changing the file)
  - Label line: `{"id", "item", "expected": {question: value}}`

- [ ] **Step 1: Write the failing tests** (pass a fake `scorer` returning fixed answers; no HTTP):
  - `test_auroc_known_values`: perfect separation 1.0; reversed 0.0; all tied 0.5
  - `test_suggest_reject_keeps_target_recall`: 20 good items with noul values 0.30-0.99 and 20 bad 0.01-0.40; with target 0.95 at most 1 good item is rejected
  - `test_item_level_recall_loosens_rules`: two rules each at 95% that jointly reject 2 good items get loosened until at most 1 of 20 is rejected
  - `test_pass_above_none_when_precision_unreachable`
  - `test_choice_min_confidence_from_accuracy`
  - `test_calibrate_keeps_user_rules_unless_replace`: user rule kept, suggestion in the report
  - `test_calibrate_warns_small_label_sets`: 12 labels -> warning; a class with 2 labels -> warning naming it
  - `test_calibrate_records_returned_model_and_counts`
  - `test_calibrate_respects_privacy`: without an entry and without `--test-data`, exit 3
- [ ] **Step 2: Run**; FAIL.
- [ ] **Step 3: Implement.** Reject cutoff per noul/score question: the largest threshold such that at least `target_recall` of good items have a value at or above it, minus 0.02 margin. Then compute item routes on all labels; while item-level recall < target, move the rule whose cutoff sits closest above a rejected good item's value down to just below that value. `pass_above`: smallest threshold with at least 3 items above it whose good share >= `target_precision`, else omitted. Choice `min_confidence`: smallest confidence at which accuracy of answers at or above it >= `target_precision`, else 1.0 (all review).
- [ ] **Step 4: Run**; PASS.
- [ ] **Step 5: Commit** `decisions: calibration`.

### Task 8: SKILL.md, references and sample adapters (GREEN)

**Files:**
- Create: `skills/decisions/SKILL.md`
- Create: `skills/decisions/references/providers.md`, `questions.md`, `calibration.md`, `privacy.md`, `setup-file.md`, `advanced.md`
- Create: `skills/decisions/scripts/adapters/README.md`, `vercel_evaluate.py`, `levanto_sage.py`
- Create: `skills/decisions/examples/lead-vetting.decisions.json`

**Interfaces:**
- Consumes: CLI from Tasks 6-7 (exact subcommands and flags), baseline failures from Task 1.
- Produces: adapters expose `evaluate(state, questions: dict, *, key: str, model: str, timeout: float = 60) -> dict` (System One-shaped answers) and pure `to_request(...)` / `from_response(...)` helpers.

- [ ] **Step 1: Write the adapter tests** in `tests/test_decisions.py`: `test_vercel_to_request_uses_boolean` (noul -> `boolean`, string instructions, score criteria as label strings); `test_sage_null_answer_maps_to_review_marker` (`null` choice -> answer with `null_answer: true` and confidence 0); `test_sage_score_levels_without_level_key` (plain string criteria do not crash).
- [ ] **Step 2: Run**; FAIL. **Step 3: Implement** both adapters with a header listing their pitfalls and "sample, not tested against the live service". **Step 4: Run**; PASS.
- [ ] **Step 5: Write `SKILL.md`.**
  - Frontmatter `description`: `Use when an agent must classify, score, filter, triage, moderate or route many items (leads, invoices, posts, documents, game moves) cheaply, when a user asks to save model tokens or cost with a "decision model" (TypeSafe Jev, System One, Perplexity Decider, Liquid d1), or wants code that makes yes/no, pick-one or rating decisions automatically.`
  - `compatibility`: `Needs network access to a decision-model provider (api.typesafe.ai, openrouter.ai, opencode.ai, api.perplexity.ai or another System One host) and an API key for it. Python 3.9+, standard library only.`
  - Body in this order: what a decision model is (three plain sentences); fit check; the workflow steps 1-7 from the spec, each naming the exact `python3 scripts/decide.py ...` command; the privacy checklist (three confirmations, verbatim from the spec, plus "never confirm on the user's behalf"); calibrate-or-cautious with the decline warning text; quick-reference table of commands; common mistakes (one line per baseline failure from Task 1); a field-extraction paragraph; links to every reference file and to `scripts/adapters/README.md`.
  - Address every baseline failure recorded in Task 1, in the form the writing-skills "Match the form to the failure" table calls for.
- [ ] **Step 6: Write the references:** `providers.md` (table from the spec's Verified facts with key env vars, sign-up/docs links, data-policy links with the date checked, model quirks with source and date, unverified hosts with a paste-in `providers` block, the Vercel and Sage notes); `questions.md` (question types, criteria conventions, reference text and examples in every request, wording-flip check, keep grouping fixed); `calibration.md` (labels format, coverage, recall-first, cautious mode, `--check`); `privacy.md` (rule of thumb, how to read a policy, OpenRouter zero-retention routing, the record format); `setup-file.md` (every field, the example file); `advanced.md` (the spec's planned entries with their TypeSafe links, two-step idea, images stub).
- [ ] **Step 7: Run all tests:** `python3 -m unittest discover -s tests -v`; expected all PASS, including `test_skills` and `test_public_safety`.
- [ ] **Step 8: Commit** `decisions: SKILL.md, references, sample adapters`.

### Task 9: Scenarios with the skill (GREEN check, REFACTOR)

**Files:**
- Create: `skills/decisions/evals/green-2026-11.md`
- Modify: `skills/decisions/SKILL.md` and references as the runs require

- [ ] **Step 1: Rerun the ten Task 1 runs** with the skill loaded (subagent reads `skills/decisions/SKILL.md` first; same no-network instruction); score R1-R8.
- [ ] **Step 2: Run two scenarios (5 and 2) with two small models** through opencode in the `sandboxing` skill's sandbox per `AGENTS.md` "Testing skills with small models"; grade from the JSON tool-call events.
- [ ] **Step 3: For each failing rubric item,** add the counter in the right form (recipe, structural slot, or prohibition with rationalization table) and rerun only the failing scenarios until each item passes in both runs.
- [ ] **Step 4: Record** scores and the changes made in `evals/green-2026-11.md`.
- [ ] **Step 5: Commit** `decisions: scenario results with the skill and fixes`.

### Task 10: Live smoke test and finish

**Files:**
- Modify: `skills/decisions/references/providers.md` (verified dates), `AGENTS.md` (Skills list entry), `TODO.md` (follow-ups)

- [ ] **Step 1: Live smoke test** (manual, sandbox, free models only): `python3 skills/decisions/scripts/decide.py ask --test-data --provider opencode --state "My server is down" --yes "Is this urgent?"`, and the same for `openrouter` (`perplexity/pplx-decider-flash-v1.3:free`), `typesafe`, `asi` and `perplexity`. Expected: a plain-language answer each; update dates in `providers.md`.
- [ ] **Step 2: Run** `python3 skills/skillspector-install/scripts/install.py --skip-skill` if `skillspector` is missing, then `python3 scripts/skillspector_ci.py --skills decisions`; expected no HIGH/CRITICAL findings (fix, or add a reasoned baseline in `.skillspector/decisions.yaml` for the user to review).
- [ ] **Step 3: Add the `decisions` entry** to `AGENTS.md` "Skills" (one paragraph in the existing style, decisions marked "(the user, 2026-11-23)"), and to `TODO.md`: image input and `box` questions; live-test the sample adapters; fix the stale OpenCode System One path in the private repo's `opencode-cli` skill (tell the user, don't edit there).
- [ ] **Step 4: Run all tests** and `bash scripts/claude_skill.sh -o "$TMPDIR" decisions` (packaging check; delete the `.skill` afterwards). Expected: all PASS, one package built.
- [ ] **Step 5: Commit and push** `decisions: live check, notes`; `git push origin skill/decisions`. Then ask the user for review (do not merge).
