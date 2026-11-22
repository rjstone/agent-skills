# docshelf-build: classify (reference vs guide) for llms.txt docvols

Date: 2026-11-22. TODO 8.11. Builds on
`2026-11-21-docshelf-build-llms-txt-design.md` (0.2.0).

## Intent

Agents want dense reference, not tutorials (the user, 2026-11-21). 0.2.0
keeps every page of an llms.txt site in full on purpose ("fetch too much,
sort later"), caches the raw pages and records per-page `signals`. This is
the "sort later" step: mark each page reference (`keep: full`) or guide
(`keep: stub`) so the docvol shrinks to what an agent looks things up in,
while the raw cache keeps every choice reversible.

## Goals

- A `classify NAME` command for a planned and built llms.txt docvol.
- Fixed thresholds on `signals` settle the clear cases; the agent running
  the skill judges the rest from a compact listing, and writes its choices
  back with `classify NAME --apply FILE` (the user, 2026-11-22: approach
  "rules + agent").
- Choices are stored as `keep` plus `why: "model:<id>"`, which re-planning
  already keeps (0.2.0). A rebuild after classifying needs no downloads.
- Stdlib only; no API key; no network for classify itself.

## Non-goals

- Sphinx docvols: their stub pages are never downloaded, so there is
  nothing to judge (no `signals`). The role rule stays their classifier.
- A decision model called over an API (approach 3 below): possible later
  through the same `--apply` file format.
- Embedding classifiers or any non-stdlib dependency.

## Anti-goals

- Stubbing a real reference page (an API page, an options or config
  reference) is worse than keeping a tutorial: when in doubt, the rules
  leave the page in full and list it for review.
- Dumping whole pages into the agent's context: the review listing is a
  few lines per page, in batches.
- Overriding a person's choice: `manual` pages, stored or command-line
  `--full`/`--stub` patterns, and an agent's earlier `model:` choice are
  never changed by the rules.

## Approaches

1. **Thresholds in the script only.** Free, offline, repeatable; crude on
   prose-heavy reference pages.
2. **The agent decides every page.** No key, stdlib; costs agent context
   on every page (1,407 pages on LangChain's root index).
3. **An external decision model over an OpenAI-compatible API.**
   Unattended and cheap with a small model, but needs a key and network,
   and each user must configure it.
4. **Rules first, agent for the rest (chosen, the user, 2026-11-22).**
   Rules decide the clear ends; the agent reviews only the middle. Keeps
   1's cost and 2's judgment; 3 can later write the same `--apply` file.

## Design

### Command

`classify NAME [--offset K] [--limit N]`

1. Loads the plan; refuses a non-llms plan (exit 2: "classify works on
   llms.txt docvols; Sphinx plans use the role rule") and a plan with no
   `signals` yet (exit 2: "build NAME first").
2. Runs the rules over every page that the rules may decide (below) and
   saves the plan.
3. Prints a summary (pages kept as reference, made stubs, left for review,
   decided by a person or an earlier agent choice), then a batch of
   review pages from `--offset` (default 0), `--limit` (default 25), then
   the next step.

The rules are deterministic, so running `classify` again gives the same
result and only moves through the batches.

Which pages the rules may decide: a page with `signals` whose `why` is not
`manual`, does not start `override:`, and is not a `model:` choice other
than the rules' own (`model:rules-<n>`). Others are counted as "decided"
and never listed.

### Rules

A function of `signals` only (pure, tested on its own), returning
`full`, `stub` or `review`. Written as `why: "model:rules-1"` for `full`
and `stub`; a `review` page keeps `keep: full` (fetch too much) and its
previous `why` unless that was `model:rules-*`, which is reset to the
plan's default rule. The rule-set version in the id changes whenever the
thresholds change, so stored choices say which rules made them.

Shape (exact thresholds set by calibration, below):

- `full` when the page is clearly reference: many `signature_lines`, or a
  high `code_ratio` with low `you_per_1k`, or many `tables` with few
  `steps`.
- `stub` when the page is clearly a guide: no or very few
  `signature_lines`, low `code_ratio`, high `you_per_1k` or several
  `steps`.
- `review` otherwise, including very short pages (few `words`) whose
  signals are too thin to judge.

### Calibration (builder's task)

Label a sample of the two sites already cached during the 0.2.0 trial
(LangChain `build/python.txt`, 240 pages; opencode, 90 pages; rebuild the
caches if they are gone): at least 120 pages, both sites, each labelled
reference or guide from its cached text. Choose thresholds so that the
rules' `full` and `stub` choices agree with the labels on at least 95% of
the pages they decide, on each site separately (a pooled figure could hide
a weak site), and report what share they leave for review (aim: under
half). If one threshold set cannot reach 95% on both sites, widen the
review band (more pages left for the agent) rather than accept lower
agreement: a wrong stub costs more than a review. Commit the labels with the pages' signals as a test fixture
(`tests/fixtures/docshelf_build_classify.json`: key, site, label, signals;
numbers only, no page text). A test checks the agreement figure against
the fixture, so a later threshold change shows its effect.

### Precedence with overrides (answered by 0.2.0 code)

A stored override beats the default rule but loses to an earlier `model:`
choice (0.2.0 `_choose`). In practice a person's pattern still wins: it
enters through `plan --full/--stub PAT`, where it is a command-line
override that beats `model:`, and the page's `why` becomes
`override: PAT`, so the `model:` choice is gone; later re-plans apply the
stored pattern because there is no `model:` choice left. No change to
`_choose`. Only a pattern added by hand-editing the plan file loses to an
existing `model:` choice; `BUILD-llmstxt.md` says to add patterns with
`plan`, not by editing.

### Counting and paging (builder's calls, settled here)

- The summary puts every page in exactly one bucket, so the counts add up
  to the plan's page count: reference (rules), stub (rules), decided by a
  person (`manual`, `override:`), decided by an agent (`model:` other than
  `model:rules-*`), left for review, and no signals (not built yet, or the
  fetch failed and there is no cached copy).
- The listing always shows the review pages in plan order, starting at
  `--offset`. After an `--apply` those pages leave the review set, so the
  loop is: `classify NAME` (offset 0), apply, `classify NAME` again.
  `--offset` is for looking ahead without applying; the "more:" hint is
  printed only when nothing has been applied to this batch yet, and the
  "next:" text says to rerun `classify NAME` after applying.
- A review page the agent leaves alone stays `keep: full` (fetch too
  much). Writing `full KEY` records the agent's decision and removes it
  from review.
- `--apply` accepts any page key in the plan, including no-signals pages.
- A later `--apply` overwrites an earlier agent choice (last write wins),
  except on `manual` and `override:` pages.
- A description on a `full` line is stored in the plan (as for stubs) and
  used only where the docvol already uses descriptions (stub pages).
- `--reset` drops `model:` choices, as in 0.2.0: `BUILD-llmstxt.md` says
  so, and that `classify` restores the rules' part but not the agent's.

### Review listing

Per page, three lines, small enough for a small model's context:

```
docs/guides/streaming   [Docs / Guides] Streaming
  words=1274 code=0.33 you=8.5 sig=9 steps=3 tables=0
  > First ~200 characters of the page text, whitespace collapsed ...
```

The text line comes from the cached raw page (Markdown with front matter
and MDX tags stripped, or the HTML's text), skipping the first heading.
After the batch:

```
next: write one line per page to a file: "full KEY" or "stub KEY [short description]",
then run: classify NAME --apply FILE --model YOUR_MODEL_ID
more: classify NAME --offset 25
```

### Applying choices

`classify NAME --apply FILE [--model ID]` (`FILE` may be `-` for stdin):

- One choice per line: `full KEY` or `stub KEY` with an optional
  description after the key (shown on the stub page). Blank lines and
  lines starting `#` are ignored.
- Each listed page gets `keep`, `why: "model:<ID>"` (ID default `agent`)
  and, when given, `description`. An agent may also decide a page the rules
  decided; it may not change a `manual` or `override:` page (reported,
  skipped).
- Unknown keys and malformed lines are reported with their line numbers;
  the valid lines are still applied. Exit 2 if no line was valid.
- Prints counts and how many pages are still left for review.

### Rebuild

Unchanged command: `build NAME` writes the docvol from the page cache (no
downloads unless `--refetch`). Stubs show the title, section, description
and live link, as today.

### Docs

- `BUILD-llmstxt.md`: the "Sorting reference from tutorials" section
  becomes the classify loop (classify, review batches, apply, build), with
  the rule that the rules never touch a person's choice.
- `SKILL.md`: no change beyond the version.
- `AGENTS.md` skill entry and `TODO.md` (8.11 done).

### Version

0.3.0 (new feature, skill with scripts); `build_core.VERSION` matches.

### Testing

- Stdlib `unittest`, no network: the rules function on hand-made signals;
  the calibration fixture's agreement figure; which pages the rules may
  decide (manual, override, agent `model:` untouched); review listing
  format and paging; `--apply` parsing, errors, stdin; a re-plan keeping
  classify's choices; `build` after classify writing stubs without
  downloads.
- Small-model trial like `docs/trials/2026-11-22-docshelf-build-detect`:
  the LangChain Python prompt, with the classify step in the skill; record
  how many pages each model reviewed, its agreement with the calibration
  labels where they overlap, and the docvol size before and after.

## Left to the builder

- The exact thresholds and the labelled sample (above).
- How the text preview strips Markdown, MDX and HTML (reuse
  `build_markdown`/`build_html` helpers where they fit).
- Module layout (a new `build_classify.py` is the expected home).
