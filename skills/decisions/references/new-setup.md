# New use case: setting up

Read this only when no existing decision-model project fits the user's
request (SKILL.md step 1). Do the steps in order and say each step's outcome
to the user in plain words.

## 1. Fit check

A decision model fits when **all** are true:

- there are many items (rule of thumb: more than about 50, or a stream);
- each decision is yes/no, pick-one from a known list, or a rating;
- a wrong call can be caught by a later step (review, a person, a rule).

It does not fit reasoning, writing, multi-step work, or extracting fields.
For a handful of items, read them yourself. Tell the user which case this is
before going on.

## 2. Interview and draft the setup

Ask, in the user's terms, one or two questions at a time:

- What is a good item and a bad one? Ask for 2-3 real examples of each.
- What happens to each outcome (read, skip, flag, act automatically)?
- What reference material defines the domain: code lists, definitions,
  policies, a rubric? Decision models assume **no domain knowledge**.

Then write `<name>.decisions.json` in the user's project. Start from a copy
of `<skill>/examples/lead-vetting.decisions.json`: `questions` is an object
keyed by name, `policy.good_if` a list of conditions (format:
[setup-file.md](setup-file.md), question writing:
[questions.md](questions.md)). `decide.py run <setup> --dry-run --state
"test"` checks the file's shape without sending. Put the definitions and
3-10 labeled examples in its `reference` field: `decide.py` adds them to
**every** request. Set `policy.good_if` to what the user called a good item.
Show the questions back to the user before any call.

## 3. Provider and model

Run `python3 <skill>/scripts/decide.py providers` to see which keys are set.
Prefer free first, within one model family: OpenCode `jev-1.13-free`, with
paid Jev on TypeSafe or OpenRouter as fallbacks. Provider details, sign-up
pages and model quirks: [providers.md](providers.md). Fallbacks must be the
**same model family**; the script refuses others.

## 4. Privacy check (required before any real data is sent)

Sending items to a provider the user has no agreement with is the user's
decision, not yours. Assume free or very cheap models keep data indefinitely
and may train on it; paid ones may too unless the user opts out. Details:
[privacy.md](privacy.md).

Give the user the link to the provider's current data-handling policy (its
own page). The user reads it there: your summary is no substitute and must
not replace it. If you add a short summary, start it with: "This summary may
be incomplete or wrong; the provider's written policy is the only binding
source, and you must read it yourself." Suggest contacting the provider about
anything unclear. Then ask the user to confirm **all three**:

1. **The data is OK to send:** what kind of data it is, and that nothing
   regulated or confidential goes out beyond what is allowed.
2. **They read the provider's current policy at its source and accept it**
   for this data.
3. **The responsible party agrees:** whoever is liable and principally
   responsible for decisions about proper handling of the data under
   applicable laws (employer, client, data controller) agrees, or the user
   is that party.

Only after an explicit yes to all three, record it:
`python3 <skill>/scripts/decide.py privacy <setup> --provider <name> --policy-url <url> --summary "<what the user confirmed, with the date>"`.
Never record it on the user's behalf. Until it is recorded, `run`, `ask` and
`calibrate` refuse to send (exit 3); `--test-data` is only for made-up data.

## 5. Calibrate, or confirm the risk of skipping it

Ask the user for labeled examples: items with the right answer, as many as
they can, covering every class and the borderline cases (20+ is good, a few
is the bare minimum, more is better). Then:

- **Labels available:** write them as JSONL (format in
  [calibration.md](calibration.md)) and run
  `python3 <skill>/scripts/decide.py calibrate <setup> --labels labels.jsonl`.
  Report the agreement and warnings to the user in plain words. The cutoffs
  are tied to the answering model's family; another family needs its own
  calibration. If the result looks poor (the script warns about too few
  labels or a class with fewer than 3, an AUROC under about 0.75, or a case
  the labels don't cover), treat it like the next case.
- **User declines, has no labels, or the calibration is poor:** tell them,
  in these words or close: "We haven't checked this model on enough
  examples you've judged, so we can't know how often it gets your items
  wrong. Expect more good items marked low, bad ones marked high, and wrong
  choices, so the confidence numbers matter more. I'll run in cautious
  mode: only near-certain rejects are skipped and everything uncertain goes
  to a full read. That costs more but loses fewer good items. We can
  calibrate any time later. Do you accept these drawbacks for now?" Wait
  for an explicit yes before running on real data; on a no, collect more
  labels instead.

## 6. Remember where the project is

Suggest saving the setup's location in whatever memory the environment has,
so a later session finds it: a memory tool or memory file, the project's
`AGENTS.md` / `CLAUDE.md` or README, or the user's notes. One line is enough,
for example: "Decision-model project: `<path>/leads.decisions.json` (lead
vetting, calibrated 2026-11-23, provider opencode)". Ask before writing to a
shared or committed file.

Then continue with SKILL.md step 3 (run and act on the routes).
