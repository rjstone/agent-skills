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

## Hard rules

- **No real data before the privacy check is recorded** for that provider:
  the user reads the provider's current data-handling policy at its source,
  and confirms the three points in
  [references/new-setup.md](references/new-setup.md) step 4. Never record
  it on the user's behalf; a summary you write never replaces their reading.
- **No run on real data without calibration** unless the user has said yes
  to the cautious-mode drawbacks (wording in new-setup.md step 5).
- **Errors and uncertain answers go to `review`,** never dropped.

## Workflow

### 1. Find existing work first

Before setting anything up, look for a decision-model project this request
continues, especially when the user refers to earlier work:

- check the environment's memory (memory tools or files, `AGENTS.md` /
  `CLAUDE.md` notes, the project README) for recorded locations of
  `*.decisions.json` setups;
- search the user's project for `*.decisions.json`;
- if still unsure, ask the user.

**Found one:** load it (`python3 <skill>/scripts/decide.py run <setup>
--dry-run --state "test"` checks it). Most setup questions are answered by
the file: questions, reference text, provider, calibration and privacy
records. Then check two things with the user before running:

- **Privacy still current:** show each provider's confirmation date and
  policy link. Policies change; if the confirmation is older than about 90
  days (the script warns), or the provider's page shows a newer update,
  the user re-reads the policy and confirms again (new-setup.md step 4).
- **Calibration status:** `mode` and the `calibration` record. Cautious or
  poor calibration needs the user's yes to the drawbacks (step 5 there).

Then go to step 3.

### 2. New use case

No existing project fits: follow
[references/new-setup.md](references/new-setup.md) (fit check, interview,
setup file, provider, privacy check, calibration, remembering the project's
location). Then go to step 3.

### 3. Run and act on the routes

`python3 <skill>/scripts/decide.py run <setup> --input items.jsonl --out routed.jsonl`
(also CSV, a folder of .txt/.md files, or `-`; `--dry-run` shows the first
request and sends nothing). Each output row has `route`:

| route | what you do |
|---|---|
| `pass` | read or act on it |
| `review` | read it in full (or a person does); errors and malformed answers land here |
| `reject` | skip it; mention the count |

Never drop `review` items to save tokens. Report the summary line (counts,
mode, tokens, cost) to the user.

For **flagging** jobs (moderation, alerts: "act if any harm question says
yes"), set `"combine": "any"` in `policy`: then `pass` means flagged by any
rule, `reject` means every rule says clean, and the rest is `review`. The
default `"all"` suits screening (any disqualifier rejects).

### 4. Hand over code the user keeps

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
| `models [--provider X] [--setup F]` | list models where the provider has a list endpoint (with `--setup`, its extra providers too) |
| `ask [setup] --state T --yes Q` | one question, plain-language answer (`--choice`, `--score` too) |
| `privacy setup --provider X --policy-url U --summary S` | record the user's confirmation (S: what they confirmed, with the date) |
| `calibrate setup --labels F [--check]` | score labels, set cutoffs (`--check` compares only) |
| `run setup --input F [--out F] [--dry-run]` | score a batch, route each item |

Exit codes: 0 ok, 2 usage or setup problem, 3 privacy not confirmed, 4 every
provider failed.

## Common mistakes

| Mistake | Instead |
|---|---|
| Calling a chat endpoint and parsing JSON "confidence" | System One via `decide.py`; probabilities come from the model |
| One "is it OK to send?" question, or your summary of the policy | The user reads the policy at its source; all three confirmations, recorded per provider |
| Treating a failed or malformed answer as low score | It routes to `review` |
| Cutoffs picked by feel and never checked | Calibrate on labels, or the user's yes to cautious-mode drawbacks |
| Reusing cutoffs after switching model family | Recalibrate; the script drops to cautious mode |
| Questions without definitions or examples | Put them in `reference`; the model knows nothing of the domain |
| Starting a new setup when one already exists | Check memory and `*.decisions.json` first (step 1) |

## References

- [references/new-setup.md](references/new-setup.md) - setting up a new use case, step by step
- [references/questions.md](references/questions.md) - writing questions and reference text
- [references/setup-file.md](references/setup-file.md) - the setup file and routing rules
- [references/calibration.md](references/calibration.md) - labels, cutoffs, cautious mode
- [references/privacy.md](references/privacy.md) - the privacy check and keeping it current
- [references/providers.md](references/providers.md) - providers, models, families, policy pages
- [references/advanced.md](references/advanced.md) - common patterns; links to TypeSafe docs

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
