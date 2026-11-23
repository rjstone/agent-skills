# decisions: deferred review minors (version warning, 429 backoff, Windows) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three review findings deferred from PR #39: no warning on a model version change within a family; the rate limit covers only the first call per item and a 429 has no backoff; Windows cp1252 stdout and `os.replace` on an open file.

**Architecture:** All changes are in `skills/decisions/scripts/decide.py` (stdlib only) with tests in `tests/test_decisions.py`. A small helper per finding; `evaluate()` gains one optional `limiter` keyword; `DecisionError` gains optional `status` and `retry_after`. No new files.

**Tech Stack:** Python 3 stdlib, `unittest`, the existing `FakeSystemOne` HTTP fake.

**Spec:** `docs/superpowers/specs/2026-11-23-decisions-design.md` (decision 4: "A version change within a family keeps the calibration but warns and suggests `calibrate --check`"; CLI: `--rate` calls per second, fallback on 429). Findings text: PR #39 final review ("The rate limit covers only the first call for each item. Retries and fallback hops ignore it, and a 429 jumps straight to the fallback with no backoff"; "Writing to stdout with `ensure_ascii=False` raises `UnicodeEncodeError` ... under cp1252"; "`os.replace` raises `PermissionError` (uncaught) if an editor has the setup file open").

## Global Constraints

- Stdlib only; no new dependencies.
- Branch: `update/decisions` if PR #40 is still open (its 0.2.0 bump covers this), else a new `update/decisions` from `main` with `metadata.version` and `VERSION` bumped to `"0.3.0"` together.
- f-strings must not contain `${` (SkillSpector AE1).
- Every fix gets a test that fails first.
- Tests never sleep for real: sleeping goes through a module-level `decide._sleep` (alias of `time.sleep`) that tests patch.
- Exit codes unchanged: 0 ok, 2 config, 3 privacy, 4 every provider failed.

## Review Focus

1. A 429 on a fallback hop (not only the primary) gets the same backoff.
2. `Retry-After` as an HTTP date, empty, negative or non-numeric: use the default backoff, never crash.
3. `--workers 4` with 429s: each worker sleeps on its own; output order and counts are unchanged.
4. A cached row (no HTTP call) never triggers the version warning by itself unless its stored model differs.
5. stdout that is a pipe with no `reconfigure` (e.g. `io.StringIO` in tests, some IDE consoles): no crash.

Tests for 1, 2 and 5 are in Tasks 2 and 3; 3 and 4 are covered by the existing `--workers` and cache tests plus Task 1's cache test.

---

### Task 1: Warn on a model version change within the calibrated family

**Files:**
- Modify: `skills/decisions/scripts/decide.py` (`is_cautious` neighbourhood, `cmd_run` summary, `cmd_ask`)
- Modify: `skills/decisions/references/calibration.md:52-53`
- Test: `tests/test_decisions.py`

**Interfaces:**
- Produces: `version_drift(setup: dict, model_returned: str | None) -> str | None` - a warning text when the setup is calibrated (`policy.mode == "calibrated"`), `model_returned` is not None, it is the same family as `calibration.model` and not equal to it; else None.

- [ ] **Step 1: Write the failing tests**

```python
def test_version_drift_same_family_other_version(self):
    s = {"policy": {"mode": "calibrated"}, "calibration": {"model": "jev-1.13.0"}}
    msg = decide.version_drift(s, "jev-1.14.0")
    self.assertIn("jev-1.13.0", msg); self.assertIn("jev-1.14.0", msg)
    self.assertIn("calibrate", msg); self.assertIn("--check", msg)

def test_version_drift_none_when_same_model_other_family_uncalibrated_or_unknown(self):
    s = {"policy": {"mode": "calibrated"}, "calibration": {"model": "jev-1.13.0"}}
    self.assertIsNone(decide.version_drift(s, "jev-1.13.0"))
    self.assertIsNone(decide.version_drift(s, "d1.1"))      # family change = cautious, not this warning
    self.assertIsNone(decide.version_drift(s, None))
    self.assertIsNone(decide.version_drift({"policy": {}}, "jev-1.14.0"))

def test_run_summary_warns_once_per_drifted_model(self):
    # calibrated setup on jev-1.13.0, fake answers model "jev-1.14.0" for 3 items
    # (run via decide.main(["run", sp, "--input", src, "--no-cache", "--rate", "0"]))
    self.assertEqual(err.count("jev-1.14.0 answered"), 1)
    self.assertEqual(code, 0)
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m unittest tests.test_decisions -k version_drift -k drifted -v`
Expected: FAIL / ERROR, `module 'decide' has no attribute 'version_drift'`.

- [ ] **Step 3: Implement `version_drift` and wire it in**

Message (exact): `"{model_returned} answered, but the cutoffs were calibrated on {cal_model} (same family). The calibration is kept; re-check it with: decide.py calibrate SETUP --labels FILE --check"`.
`cmd_run`: collect `version_drift(setup, row["model"])` per routed row into a set; after the summary line, `_err` each distinct message once. `cmd_ask`: `_err` it after the answer when not None.

- [ ] **Step 4: Run the tests to see them pass**

Run: `python3 -m unittest tests.test_decisions -v 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Docs, then commit**

`calibration.md` line 52-53 becomes: "`calibrate --check` re-scores the labels and compares them with the stored record without changing anything. `run` and `ask` print a warning when a newer version of the calibrated family answers; run the check then."

```bash
git add skills/decisions/scripts/decide.py skills/decisions/references/calibration.md tests/test_decisions.py
git commit -m "decisions: warn when another version of the calibrated family answers"
```

### Task 2: Rate-limit every call and back off on 429

**Files:**
- Modify: `skills/decisions/scripts/decide.py` (`DecisionError`, `post_json`, `evaluate`, `cmd_run`, `--rate` help)
- Test: `tests/test_decisions.py` (`FakeSystemOne` reply headers; `EvaluateTest`; tests at lines ~218 and ~287 patch `decide._sleep`)

**Interfaces:**
- Produces: `DecisionError(kind, message, *, status: int | None = None, retry_after: float | None = None)`.
- Produces: `RETRIES_429 = 2`, `BACKOFF_429 = (1.0, 2.0)`, `MAX_RETRY_AFTER = 30.0`, `_sleep = time.sleep`.
- Produces: `parse_retry_after(value: str | None) -> float | None` - non-negative number of seconds, capped at `MAX_RETRY_AFTER`; None for missing, dates or junk.
- Produces: `evaluate(..., limiter=None)` - `limiter` is a no-argument callable run before every HTTP POST (first try, the no-answers retry, 429 retries, every fallback hop).
- `FakeSystemOne` replies may be `(status, body, headers_dict)`; two-tuples still work.

- [ ] **Step 1: Write the failing tests**

```python
def test_429_backs_off_then_same_hop_succeeds(self):
    self.fake.script["/a"] = [(429, {"error": "rate"}), (200, good_answer())]
    with mock.patch.object(decide, "_sleep") as sl:
        answers, meta = self.ev()
    self.assertEqual(meta["provider"], "a"); self.assertEqual(meta["hops"], [])
    sl.assert_called_once_with(1.0)

def test_429_honours_retry_after_capped(self):
    self.fake.script["/a"] = [(429, {}, {"Retry-After": "3"}), (429, {}, {"Retry-After": "999"}), (200, good_answer())]
    with mock.patch.object(decide, "_sleep") as sl:
        self.ev()
    self.assertEqual([c.args[0] for c in sl.call_args_list], [3.0, 30.0])

def test_429_exhausted_falls_back_after_backoff(self):
    self.fake.script["/a"] = [(429, {"error": "rate"})]
    self.fake.script["/b"] = [(200, good_answer())]
    with mock.patch.object(decide, "_sleep") as sl:
        answers, meta = self.ev()
    self.assertEqual(len(self.fake.calls("/a")), 3)      # 1 + RETRIES_429
    self.assertEqual([c.args[0] for c in sl.call_args_list], [1.0, 2.0])
    self.assertEqual(meta["provider"], "b"); self.assertIn("429", meta["hops"][0])

def test_429_on_fallback_hop_also_backs_off(self):   # Review Focus 1
    self.fake.script["/a"] = [(500, {})]
    self.fake.script["/b"] = [(429, {}), (200, good_answer())]
    with mock.patch.object(decide, "_sleep") as sl:
        _, meta = self.ev()
    self.assertEqual(meta["provider"], "b"); sl.assert_called_once_with(1.0)

def test_parse_retry_after(self):                     # Review Focus 2
    for raw, want in [("2", 2.0), ("0", 0.0), ("999", 30.0), ("-1", None), ("", None), (None, None),
                      ("Wed, 21 Oct 2026 07:28:00 GMT", None), ("soon", None)]:
        self.assertEqual(decide.parse_retry_after(raw), want)

def test_limiter_runs_before_every_post(self):
    self.fake.script["/a"] = [(200, {"no": "answers"})]          # retried once, then fallback
    self.fake.script["/b"] = [(200, good_answer())]
    ticks = []
    self.ev(limiter=lambda: ticks.append(1))
    self.assertEqual(len(ticks), len(self.fake.requests))       # 3
```

Also wrap the existing 429 tests (`test_fallback_on_429_then_success`, the 429 in the fallback-without-privacy test) in `mock.patch.object(decide, "_sleep")`.

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m unittest tests.test_decisions -k 429 -k retry_after -k limiter -v`
Expected: FAIL (one call to `/a` before fallback; no `parse_retry_after`; `evaluate` has no `limiter`).

- [ ] **Step 3: Implement**

`post_json` raises the 429 `DecisionError` with `status=429` and `retry_after=parse_retry_after(e.headers.get("Retry-After"))`. In `evaluate`, each hop's POST goes through one inner helper that calls `limiter()` (when given) before every `post_json`, and on a status-429 error retries the same hop up to `RETRIES_429` times, sleeping `retry_after` if set else `BACKOFF_429[attempt]`; after that it raises as before so the hop falls back. `cmd_run` passes `limiter=limiter.wait` and drops its own `limiter.wait()` call. `--rate` help: "max calls per second across all workers, retries and fallbacks included (default 2)".

- [ ] **Step 4: Run the whole suite**

Run: `python3 -m unittest tests.test_decisions -v 2>&1 | tail -3`
Expected: `OK`, and the run takes no longer than before (no real sleeps).

- [ ] **Step 5: Commit**

```bash
git add skills/decisions/scripts/decide.py tests/test_decisions.py
git commit -m "decisions: rate-limit every call; back off and retry a 429 before falling back"
```

### Task 3: Windows: non-UTF-8 stdout and a setup file held open

**Files:**
- Modify: `skills/decisions/scripts/decide.py` (`main`, `cmd_run` row writer, `save_setup`)
- Test: `tests/test_decisions.py`

**Interfaces:**
- Produces: `json_line(obj, stream) -> str` - `json.dumps(obj, ensure_ascii=not _is_utf8(stream))`; `_is_utf8(stream) -> bool` is true when `codecs.lookup(stream.encoding).name == "utf-8"`, false when the encoding is missing or anything else.
- Produces: `SAVE_RETRIES = 5`, `SAVE_RETRY_DELAY = 0.2`; `save_setup` raises `DecisionError("config", ...)` after the last `PermissionError`.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_to_cp1252_stdout_keeps_valid_json(self):
    buf = io.BytesIO(); stream = io.TextIOWrapper(buf, encoding="cp1252")
    # item id "项目-1", answers from the fake; run with sys.stdout patched to `stream`
    stream.flush()
    row = json.loads(buf.getvalue().decode("cp1252").splitlines()[0])
    self.assertEqual(row["id"], "项目-1"); self.assertEqual(code, 0)

def test_ask_human_output_to_cp1252_does_not_crash(self):
    # choice option "团队" answered; decide.main(["ask", ...]) with sys.stdout = cp1252 wrapper
    self.assertEqual(code, 0)                              # characters become "?" in human text

def test_main_tolerates_stdout_without_reconfigure(self):  # Review Focus 5
    with contextlib.redirect_stdout(io.StringIO()):
        self.assertEqual(decide.main(["providers"]), 0)

def test_save_setup_retries_permission_error(self):
    with mock.patch("os.replace", side_effect=[PermissionError("in use"), None]) as rep, \
         mock.patch.object(decide, "_sleep") as sl:
        decide.save_setup(path, {"x": 1})
    self.assertEqual(rep.call_count, 2); sl.assert_called_once_with(0.2)

def test_save_setup_gives_up_cleanly(self):
    # original file content kept, no .tmp-*.json left in the folder
    with mock.patch("os.replace", side_effect=PermissionError("in use")), mock.patch.object(decide, "_sleep"):
        with self.assertRaises(decide.DecisionError) as cm:
            decide.save_setup(path, {"x": 2})
    self.assertEqual(cm.exception.kind, "config"); self.assertIn("open in another program", str(cm.exception))
```

- [ ] **Step 2: Run them to see them fail**

Run: `python3 -m unittest tests.test_decisions -k cp1252 -k reconfigure -k permission -k gives_up -v`
Expected: `UnicodeEncodeError` in the cp1252 tests; `PermissionError` escapes `save_setup`.

- [ ] **Step 3: Implement**

`cmd_run` writes rows with `json_line(row, out)` (the `--out` file is UTF-8, so it keeps real characters). `main` first calls `reconfigure(errors="replace")` on `sys.stdout` and `sys.stderr` when they have it (human-readable text only; JSON is already safe). `save_setup` tries `os.replace` `SAVE_RETRIES` times, `_sleep(SAVE_RETRY_DELAY)` between tries, then removes the temp file and raises: `"could not save {path}: {e}. It may be open in another program (an editor, a sync or backup tool); close it and run the command again. The file was not changed."`

- [ ] **Step 4: Run the whole suite and the repo checks**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -3` and `python3 scripts/ci_changed_skills.py --check-versions`
Expected: `OK`; the version check passes.

- [ ] **Step 5: Commit**

```bash
git add skills/decisions/scripts/decide.py tests/test_decisions.py
git commit -m "decisions: valid JSON on non-UTF-8 stdout; retry saving a setup file held open"
```

### Task 4: Close out

- [ ] Remove the "review minors" item from `TODO.md`; update the PR description's follow-ups.
- [ ] Run SkillSpector on the skill (`python3 scripts/skillspector_ci.py --skills decisions`) and Bandit as in `bandit.yml`'s header; fix new findings in code, report scanner false positives to the user.
- [ ] Push; report CI.
