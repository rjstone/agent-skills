---
name: decisions
description: Use when an agent must classify, score, filter, triage, moderate or route many items (leads, invoices, posts, documents, game moves) cheaply, when a user asks to save model tokens or cost with a "decision model" (TypeSafe Jev, System One, Perplexity Decider, Liquid d1), or wants code that makes yes/no, pick-one or rating decisions automatically.
compatibility: Needs network access to a decision-model provider (api.typesafe.ai, openrouter.ai, opencode.ai, api.perplexity.ai or another System One host) and an API key for it. Python 3.9+, standard library only.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# Decisions

A **decision model** is not a chat model. You send it content (`state`) and
typed questions; it returns **calibrated probabilities**, not text: yes/no
(`noul`), pick one of named options (`choice`), or a rating on an ordered
rubric (`score`). One call costs roughly $0.00001-0.0004, so it can pre-screen
thousands of items before you or another large model read the few that matter.

Use the System One request format through `scripts/decide.py`. Do not build a
decision step on a chat-completions endpoint with "reply in JSON": that loses
the calibrated probabilities this skill depends on.

`<skill>` below means this skill's folder. Run the script as
`python3 <skill>/scripts/decide.py ...`.

## Workflow

Do the steps in order. Say each step's outcome to the user in plain words.

### 1. Fit check

A decision model fits when **all** are true:

- there are many items (rule of thumb: more than about 50, or a stream);
- each decision is yes/no, pick-one from a known list, or a rating;
- a wrong call can be caught by a later step (review, a person, a rule).

It does not fit reasoning, writing, multi-step work, or extracting fields (see
"Out of scope"). For a handful of items, read them yourself. Tell the user
which case this is before going on.

### 2. Interview and draft the setup

Ask, in the user's terms, one or two questions at a time:

- What is a good item and a bad one? Ask for 2-3 real examples of each.
- What happens to each outcome (read, skip, flag, act automatically)?
- What reference material defines the domain: code lists, definitions,
  policies, a rubric? Decision models assume **no domain knowledge**.

Then write `<name>.decisions.json` in the user's project. Start from a copy
of `<skill>/examples/lead-vetting.decisions.json`: `questions` is an object
keyed by name, `policy.good_if` a list of conditions (format:
[references/setup-file.md](references/setup-file.md), question writing:
[references/questions.md](references/questions.md)). `decide.py run
<setup> --dry-run --state "test"` checks the file's shape without sending. Put the definitions and
3-10 labeled examples in its `reference` field: `decide.py` adds them to
**every** request. Set `policy.good_if` to what the user called a good item.
Show the questions back to the user before any call.

### 3. Provider and model

Run `python3 <skill>/scripts/decide.py providers` to see which keys are set.
Prefer free first, within one model family: OpenCode `jev-1.13-free`, with
paid Jev on TypeSafe or OpenRouter as fallbacks. Provider details, sign-up
pages and model quirks: [references/providers.md](references/providers.md).
Fallbacks must be the **same model family**; the script refuses others.

### 4. Privacy check (required before any real data is sent)

Sending items to a provider the user has no agreement with is the user's
decision, not yours. Assume free or very cheap models keep data indefinitely
and may train on it; paid ones may too unless the user opts out. For each
provider, read its current data, retention and training terms (links in
[references/privacy.md](references/privacy.md)), summarize them in plain
words, and ask the user to confirm **all three**:

1. **The data is OK to send:** what kind of data it is, and that nothing
   regulated or confidential goes out beyond what is allowed.
2. **The terms are acceptable:** they read your retention and training
   summary and accept it.
3. **The responsible parties agree:** employer, client or whoever owns the
   data agrees, or the user is that party.

Only after an explicit yes to all three, record it:
`python3 <skill>/scripts/decide.py privacy <setup> --provider <name> --policy-url <url> --summary "<one line>"`.
Never record it on the user's behalf. Until it is recorded, `run`, `ask` and
`calibrate` refuse to send (exit 3); `--test-data` is only for made-up data.

### 5. Calibrate, or run cautious

Ask the user for labeled examples: items with the right answer, as many as
they can, covering every class and the borderline cases (20+ is good, a few
is the bare minimum, more is better). Then:

- **Labels available:** write them as JSONL (format in
  [references/calibration.md](references/calibration.md)) and run
  `python3 <skill>/scripts/decide.py calibrate <setup> --labels labels.jsonl`.
  Report the agreement and warnings to the user in plain words. The cutoffs
  are tied to the answering model's family; another family needs its own
  calibration.
- **User declines or has no labels:** tell them, in these words or close:
  "Without checking the model on examples you've judged, we can't know how
  often it gets your items wrong. Expect more good items marked low, bad ones
  marked high, and wrong choices, so the confidence numbers matter more. I'll
  run in cautious mode: only near-certain rejects are skipped and everything
  uncertain goes to a full read. That costs more but loses fewer good items.
  We can calibrate any time later." Then go on; the setup stays in cautious
  mode.

### 6. Run and act on the routes

`python3 <skill>/scripts/decide.py run <setup> --input items.jsonl --out routed.jsonl`
(also CSV, a folder of .txt/.md files, or `-`; `--dry-run` shows the first
request and sends nothing). Each output row has `route`:

| route | what you do |
|---|---|
| `pass` | read or act on it |
| `review` | read it in full (or a person does); errors and malformed answers land here |
| `reject` | skip it; mention the count |

Never drop `review` items to save tokens.

For **flagging** jobs (moderation, alerts: "act if any harm question says
yes"), set `"combine": "any"` in `policy`: then `pass` means flagged by any
rule, `reject` means every rule says clean, and the rest is `review`. The
default `"all"` suits screening (any disqualifier rejects). Report the summary line (counts,
mode, tokens, cost) to the user.

### 7. Hand over code the user keeps

For a hook, a bot or a scheduled job, copy `scripts/decide.py` and the setup
file into the user's project and show the import:

```python
from decide import load_setup, evaluate, route, effective_rules, is_cautious, build_state, combine_of
setup = load_setup("moderation.decisions.json")
answers, meta = evaluate(build_state(setup.get("reference"), post_text),
                         setup["questions"], setup=setup)
cautious, _ = is_cautious(setup, meta["model_returned"])
rules = effective_rules(setup["policy"], setup["questions"], cautious)
action = route(answers, rules, combine_of(setup))
```

Wrap the call so that any exception means `review`, never `pass`. Questions
can also be built per call (for example this turn's legal moves as a choice
question); keep their names and rules fixed so the cutoffs still apply.

## Quick reference

| Command | Does |
|---|---|
| `providers` | built-in providers, whether a key is set (names only) |
| `models [--provider X]` | list models where the provider has a list endpoint |
| `ask [setup] --state T --yes Q` | one question, plain-language answer (`--choice`, `--score` too) |
| `privacy setup --provider X --policy-url U --summary S` | record the user's confirmation |
| `calibrate setup --labels F [--check]` | score labels, set cutoffs (`--check` compares only) |
| `run setup --input F [--out F] [--dry-run]` | score a batch, route each item |

Exit codes: 0 ok, 2 usage or setup problem, 3 privacy not confirmed, 4 every
provider failed.

## Common mistakes

| Mistake | Instead |
|---|---|
| Calling a chat endpoint and parsing JSON "confidence" | System One via `decide.py`; probabilities come from the model |
| One "is it OK to send?" question | All three privacy confirmations, recorded per provider |
| Treating a failed or malformed answer as low score | It routes to `review` |
| Cutoffs picked by feel and never checked | Calibrate on labels, or cautious mode with the warning |
| Reusing cutoffs after switching model family | Recalibrate; the script drops to cautious mode |
| Questions without definitions or examples | Put them in `reference`; the model knows nothing of the domain |
| Jumping into the user's existing routines first | Fit check and interview first, generically |

## Out of scope

- **Field extraction.** Some decision APIs also pull out fields or text spans
  (Perplexity's `locate` question). That overlaps with scoring but is a
  different job; this skill does not cover it.
- **Images and `box` questions.** Not in this version; see the stub in
  [references/advanced.md](references/advanced.md).
- **Other wire formats.** Vercel's `/v1/evaluate` and Levanto Sage differ;
  sample converters are in [scripts/adapters/README.md](scripts/adapters/README.md).

More patterns (screen first, companion yes/no, large code lists in two
steps): [references/advanced.md](references/advanced.md).
