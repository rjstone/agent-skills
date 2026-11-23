# `decisions` skill - design

Date: 2026-11-23. Status: design, approved approach A (the user, 2026-11-23).

## Intent

Decision models (TypeSafe Jev, Perplexity Decider, Liquid d1, Cloudflare Clef
and others) answer structured questions about content - yes/no, pick one,
rate on a rubric, locate in an image - for roughly $0.00001-0.0004 per call
and return probabilities instead of text. An agent can use one as a cheap
first pass: score thousands of items, then spend its own (far more expensive)
tokens only on the items that pass or are uncertain.

The `decisions` skill lets any agent set this up for a user who may know
nothing about decision models, and lets an expert skip the legwork (finding a
provider and model, sign-up, docs, request format, a working client).

Typical requests the skill must handle (from the user):

1. Vet a large set of leads: interview the user to build a scoring rubric,
   score every lead with a decision model, and read only the high scorers.
2. Assign GL codes to thousands of invoices from the company's code list
   (with definitions) and some correctly coded examples; continue the
   workflow (reports) with the results.
3. Use a decision model as an AI game player, for a user who knows a little
   Python.
4. Moderate forum posts by category of harm/sentiment and trigger automatic
   action or notify a moderator, as code that runs in a post hook.
5. "Someone said decision models save money. What do you need from me to make
   it work for my routines?"

So the skill has two output modes: **in-session pre-filtering** that the agent
runs itself (1, 2, often 5), and **code the user keeps and runs** without an
agent (3, 4).

## Goals

- An agent with the skill can go from a vague request to a working, tested
  decision setup: provider chosen, privacy confirmed, questions written with
  domain reference text, calibration done or cautious mode on, batch run,
  items routed pass / review / reject.
- Plain-language explanations for novices; no step needs the user to read
  API docs.
- One stdlib-only Python client that runs in any agent sandbox (Linux, macOS,
  Windows; Python 3.9+), usable as a CLI and as an importable module the user
  copies into their own project.
- Reusable setup: the user's routines reuse one saved setup file instead of
  rebuilding the questions each time.

## Non-goals

- Field extraction (Perplexity's `locate` question, span extraction). It often
  overlaps with scoring and gets one paragraph pointing elsewhere; it is not
  implemented or taught.
- Chat/completion models, embeddings, fine-tuning.
- First-class support for non-System-One wire formats (Vercel AI Gateway
  `/v1/evaluate`, Levanto Sage `/decide`). They get sample adapters only.
- A model leaderboard. The skill lists models and prices with dates; it does
  not rank quality.

## Anti-goals (failure even if it "works")

- **Silent loss.** A filter that quietly discards good items is worse than no
  filter. Every design choice leans toward over-including.
- **Sending data without informed consent.** Data must never reach a new
  third-party provider before the user has confirmed the privacy checklist
  (below). The agent never confirms on the user's behalf.
- **Trusting an untested model.** Calibration from one model family is never
  silently reused for another.
- **Machine or account details in the public repo**, or code that only works
  in one sandbox.

## Constraints

- Public repo rules in `AGENTS.md`: no account names, private repo names,
  hostnames of private machines, home paths or secrets; stdlib-only; Agent
  Skills frontmatter in this repo's order; `metadata.version` "0.1.0";
  `VERSION` in the script equal to it; tests are stdlib `unittest` with no
  network; `tests/test_decisions.py` starts with the `selected("decisions")`
  skip; `references/*.md` all linked from `SKILL.md`.
- New skill workflow: branch `skill/decisions`, review, squash-merge.
- Keys only from environment variables, sent in headers, never printed, never
  in argv, scrubbed from error text. Behind an egress proxy that injects keys,
  a placeholder value works.
- Prior art exists in the user's private projects (a provider-chain client
  with fallback, key redaction, dry-run, model listing, question files with
  thresholds, score caching, calibration notes). Port ideas, not files, and
  name no private repo.

## Verified facts (2026-11-23)

Same request body on all four (one yes/no question; ASI also a choice
question):

| Provider | Endpoint | Tested model | Notes |
|---|---|---|---|
| TypeSafe | `https://api.typesafe.ai/v1/systemone` | `jev-latest` -> `jev-1.14.0` | OpenAPI at `/openapi.json`; `GET /v1/models` lists `jev-latest`, `jev-preview` |
| OpenRouter | `https://openrouter.ai/api/v1/systemone` | `perplexity/pplx-decider-flash-v1.3:free`, `respan/span-01-lite:free` | `/v1/models` does not list decision models; usage carries `cost`; presets don't route here |
| OpenCode Console | `https://opencode.ai/inference/systemone/v1/systemone` | `jev-1.13-free` | free Jev works outside OpenCode |
| ASI Cloud | `https://inference.asicloud.cudos.org/v1/systemone` | `super-decider` | not in models.dev; price and key env var undocumented here |

Unverified (models.dev lists them with the TypeSafe SDK package, or docs say
so): Liquid `https://api.liquid.ai/decisions/v1/systemone`, decisionmodels.io,
Butler, GreenPT, Melious, NEAR AI, Vivgrid; Perplexity direct
`https://api.perplexity.ai/v1/decisions` (same body per its docs; this
environment's key was rejected, 401).

Wire format (TypeSafe OpenAPI 0.2.0): request `{model, state, questions,
assets?}`; question types `noul` (yes/no; answer `noul` = P(yes), no
confidence), `choice` (`criteria` = {name: description|null}; answer
`choice`, `confidence`, `probabilities`), `score` (`criteria` = ordered level
descriptions; answer expected `score`, `confidence`, `legend`,
`probabilities`), `box` (image location). Images: `assets` map of placeholder
-> base64 plus header `TypeSafe-Danger-Zone-Images: true`. Usage:
`input_tokens`, `output_tokens` (output currently free).

Known model quirks (to go in `references/providers.md`, each with source and
date):

- `respan/span-01-lite(:free)`: `noul` only, needs explicit true/false
  criteria, `state` must be a string.
- Mercury Decide (now gone from OpenRouter): near-binary scores; thresholds
  fitted on Jev lost about half the good items. General lesson: thresholds
  never transfer across model families.
- Perplexity Decider: 1-255 choices, 1-10 score levels, 256K context; its
  questions can see each other's answers (v1.2), so keep question grouping
  fixed once calibrated.
- Jev: about 32K context, assumes no domain knowledge.
- Probabilities wobble in the second decimal: leave a margin around cutoffs.

## Approaches considered

- **A. One System One client with a flexible provider table (chosen).** Each
  provider entry carries endpoint, key env var, default model, URL path and
  image placement, which covers every System One host plus Perplexity's path.
  Other wire formats get sample adapter files, not core code. Small, testable,
  copyable into user projects.
- **B. One client with adapters for all four wire formats.** Widest coverage,
  about twice the code and tests; adapters were where prior bugs lived; the
  extra providers add little (Vercel's free model: 8K context, 5 req/min).
- **C. Instructions plus a template the agent adapts each time.** Most
  flexible; nothing tested ships, novices get a different script every time.

The user chose A, plus sample adapter files for the other interfaces so an
agent has a head start if it must swap (the user, 2026-11-23).

## Design

### Files

```
skills/decisions/
  SKILL.md                    trigger, when (not) to use, the workflow below
  scripts/decide.py           System One client: CLI + importable, stdlib only
  scripts/adapters/
    README.md                 what an adapter is, the evaluate() contract
    vercel_evaluate.py        sample: System One questions -> Vercel /v1/evaluate
    levanto_sage.py           sample: -> Sage /decide (null-on-tie handling)
  references/providers.md     provider table, data-policy links, model quirks
  references/questions.md     writing questions and reference text
  references/calibration.md   labels, coverage, metrics, cutoffs, cautious mode
  references/privacy.md       rule of thumb, the three confirmations, reading a policy
  references/setup-file.md    the setup file format, with one full example
tests/test_decisions.py       unit tests against a local fake server
```

### Workflow `SKILL.md` teaches

1. **Fit check.** Use a decision model when there are many items (rule of
   thumb: more than about 50) and each needs a judgment that fits yes/no,
   pick-one, a rating or a location. Skip it for a handful of items or for
   tasks needing reasoning, writing or extraction. Say so plainly to the user.
2. **Interview.** In plain words, ask what a good/bad item looks like, what
   happens to each outcome, and for the domain reference material (code
   lists, definitions, examples of good and bad items). The agent drafts the
   questions and rubric from the answers and shows them back.
3. **Pick a provider and model.** Default free-first within one model family
   (for example OpenCode `jev-1.13-free`, then paid Jev on TypeSafe or
   OpenRouter). Use the user's existing keys when present (`decide.py
   providers`). For a new provider, give the sign-up page from
   `references/providers.md` (or the `provider-onboarding` skill when
   installed).
4. **Privacy check** (below). No real data is sent before it.
5. **Calibrate or go cautious** (below).
6. **Run** the batch; act on routes: the agent reads `pass` and `review`
   items, skips `reject`, reports counts and cost.
7. **Hand over.** For code the user keeps (hooks, game player), copy
   `decide.py` and the setup file into their project with a short usage
   example; the same routing rules apply there.

### Setup file (`<name>.decisions.json`, in the user's project)

One file per task, read and written by `decide.py`. Sketch:

```json
{
  "name": "lead-vetting",
  "provider": "opencode",
  "model": "jev-1.13-free",
  "fallbacks": [{"provider": "typesafe", "model": "jev-latest"}],
  "reference": "Definitions, the code list, and 3-10 labeled examples, prepended to every request's state.",
  "questions": {
    "quality": {"type": "score", "instructions": "...", "criteria": ["junk", "weak", "plausible", "strong"]},
    "is_real": {"type": "noul", "instructions": "...", "criteria": {"true": "...", "false": "..."}}
  },
  "policy": {
    "mode": "cautious",
    "rules": [
      {"question": "is_real", "reject_below": 0.10, "pass_above": 0.70},
      {"question": "quality", "reject_below": 0.8, "pass_above": 2.0, "min_confidence": 0.5}
    ]
  },
  "calibration": null,
  "privacy": {"opencode": {"confirmed": "2026-11-23", "policy_url": "...", "summary": "..."}}
}
```

- `reference` and each item's content are combined into `state` as
  `{"reference": ..., "item": ...}` so the model gets the domain knowledge on
  every call (the user, 2026-11-23: decision models need reference knowledge
  and examples in each request).
- `fallbacks` may only name the same model family; `decide.py` refuses a
  fallback whose provider has no `privacy` entry.

### Routing

Per rule: below `reject_below` -> reject; above `pass_above` -> pass; between,
or `confidence` under `min_confidence` (choice/score only) -> review. An item
is `reject` if any rule rejects, else `review` if any rule says review, else
`pass`. Choice rules map choice names to routes (for GL codes: any choice with
confidence under the cutoff goes to review). Scores use the expected `score`,
never the argmax.

**Cautious mode** (no calibration, calibration for another model family, or
the user declined testing): `decide.py` applies a wider review band and
rejects only at the extremes (starting defaults: noul reject below 0.05, pass
above 0.90; score/choice confidence under 0.6 -> review). The run summary
says cautious mode is on and why, every time.

### Calibration

The skill always offers it. More labeled examples are better, with coverage
across every class and the borderline cases; a few is the bare minimum, and
better than none (the user, 2026-11-23).

- Labels file: JSONL, one item per line with `id`, the item content and the
  expected answer per question (or an expected route).
- `decide.py calibrate` scores them and reports agreement, AUROC for noul and
  score questions, a confusion table for choice questions, and suggested
  cutoffs chosen for recall (default target: keep 95% of good items; a missed
  good item costs more than an extra read). It warns when there are fewer
  than 20 labels or fewer than 3 for any class.
- It writes `calibration` into the setup file: model id as the API returned it
  (versioned), provider, date, label count per class, metrics, and the
  cutoffs, which become the `policy` rules. `mode` becomes `calibrated`.
- A later run whose answering model differs in family from the calibrated
  one switches to cautious mode and says so.
- Optional checks the skill teaches: ask a yes/no question both ways (wording
  flip); keep question grouping fixed after calibrating.

If the user declines, the agent tells them in plain words that wrong passes,
wrong rejections and wrong choices are more likely, that confidence values
matter more, and that cautious mode will send more items to full review
(costs more, misses less). Then it proceeds in cautious mode.

### Privacy check

Rule of thumb in `references/privacy.md`: assume free or very cheap models
keep data indefinitely and train on it; paid providers may also retain or
train unless the user opts out. Always verify the current policy.

Before the first real data goes to a provider, the agent fetches that
provider's current data, retention and training terms (links in
`references/providers.md`, plus provider options such as OpenRouter's
zero-data-retention routing), summarizes them in plain words, and asks the
user to confirm all three:

1. **The data is OK to send:** what kind of data it is, and that no
   regulated or confidential data goes out beyond what is allowed.
2. **The terms are acceptable:** they have read the retention and training
   summary and accept it.
3. **The responsible parties agree:** employer, client or whoever owns the
   data agrees, or the user is that party.

The agent records the confirmation per provider in the setup file
(`decide.py privacy --provider X --policy-url URL --summary TEXT`), only after
the user's explicit yes. `decide.py run` refuses to send to a provider
without an entry unless `--test-data` is given (made-up data for trying
things out); `--dry-run` sends nothing. Adding or switching a provider re-runs
the checklist.

### `scripts/decide.py`

- `run SETUP --input FILE|DIR|-` : items from JSONL (`id` + content fields),
  CSV, a folder of text files, or `--state TEXT` for one item. Output JSONL
  per item (`id`, `route`, `answers`, `model`, `provider`, `cached`) to stdout
  or `--out`, and a summary on stderr (counts per route, mode, tokens, cost
  where the provider reports it, fallbacks used).
- `calibrate SETUP --labels FILE [--target-recall 0.95]`
- `privacy SETUP --provider X --policy-url URL --summary TEXT`
- `providers` : which providers have a key env var set (names only).
- `models [--provider X]` : `GET` the models endpoint where one exists.
- `ask` : one-off questions from flags (`--yes`, `--choice`, `--score`) for
  quick tries; prints a plain-language answer.
- Common flags: `--dry-run`, `--provider`, `--model`, `--timeout`,
  `--workers N` (default 1), `--rate` calls per second (default 2), `--json`.
- Library API: `evaluate(state, questions, provider=..., model=...) ->
  (answers, meta)` and `route(answers, policy) -> str`, so hooks and game
  code can import it.
- Fallback: try the configured provider, then each fallback once, on network
  error, timeout, 5xx, 401/402/403/429, or a 200 without `answers` (retried
  once on the same hop first). 400/422 are request bugs: stop and show the
  provider's message. Each hop uses the model configured for it in the setup
  file; `--model` overrides the primary hop only. No hop ever silently falls
  back to a built-in default model.
- Cache: `sqlite3` file beside the setup file, keyed by SHA-256 of model id +
  questions + reference + item content, so changing the questions or
  reference re-scores. `--no-cache` to skip.
- Answer validation: non-finite or out-of-range numbers count as a failed
  answer.
- Images: the provider table says where images go (`assets` map with the
  TypeSafe header, or image parts inside `state`); v1 implements both.
- User-Agent: a generic client name, no personal details.

### Sample adapters

`scripts/adapters/*.py`: each a small module exposing the same
`evaluate(state, questions, *, key, model, timeout) -> answers` and converting
System One questions to the other format and back. Marked as samples:
untested against the live services in v1, with the known pitfalls listed at
the top (Vercel: `boolean` for `noul`, string `instructions`, 8K context on
the free model; Sage: different question kinds, `null` answer on near-ties ->
route to review, level units are not 0..n-1).

### Field extraction

One paragraph in `SKILL.md`: some decision APIs also extract fields or text
spans (Perplexity `locate`); that is a different job, not covered here.

## Testing

- **Unit tests** (`tests/test_decisions.py`, stdlib, no network): a local
  `http.server` fake answering System One requests, covering request
  building, routing (both modes), fallback rules, privacy refusal, cache
  keys, calibration metrics on a fixed label set, key redaction, `--dry-run`
  sending nothing.
- **Skill tests** (writing-skills RED/GREEN): baseline subagent runs without
  the skill on the five requests above, recording what goes wrong (likely: no
  privacy check, calling a chat endpoint, no calibration offer, reading every
  item anyway); then the same with the skill. Also small models via opencode
  in the `sandboxing` skill's sandbox, per `AGENTS.md`.
- **Live smoke test** (manual, not in CI): one `ask` call per verified
  provider.

## Decided by the user

- Calibration offered every time, never forced; declining means warnings plus
  cautious mode that over-includes.
- Calibration is per model family; never reused across families.
- Domain reference text and examples go into every request.
- Privacy checklist of three confirmations before any provider is used; free
  or cheap models assumed to retain and train.
- Approach A, with sample adapters in separate files.
- Field extraction only mentioned.

## Calls made after the builder check (Claude, 2026-11-23; the user may override)

1. **Cautious mode vs written rules.** Cautious mode widens, never narrows:
   for each bound the more inclusive value wins (the lower `reject_below`,
   the higher `pass_above`, the higher `min_confidence`). Questions with no
   rule are informational: returned, never routed. Each rule carries
   `"source": "user" | "calibration"`; `calibrate` replaces only
   `calibration` rules unless `--replace-user-rules` is given, and prints
   its suggestions next to any user rule it kept.
2. **Model family.** The provider table gives each known model a `family`
   (`jev`, `pplx-decider`, `liquid-d1`, ...), the same across hosts (OpenCode
   `jev-1.13-free`, TypeSafe `jev-latest`, OpenRouter `typesafe/jev-1.14` are
   all `jev`). An unknown model is its own family. Fallbacks must share the
   primary's family. A version change within a family keeps the calibration
   but warns and suggests `calibrate --check` (re-score the labels, compare);
   a family change means cautious mode. Setup files should pin versioned ids
   where the host offers them. The cache key uses the requested id plus
   provider; the returned id is stored with each entry, and a moving alias is
   documented as a reason for `--no-cache` or a pinned id.
3. **Calibration beyond one yes/no.** Labels give the expected answer per
   question (bool, level, choice name). During the interview the user says
   what "good" means for the item (for example `quality >= 2` and
   `is_real`), stored as `policy.good_if`. The recall target (default 0.95)
   is per item: the share of good-labeled items not rejected. `calibrate`
   picks each `reject_below` for target recall on its own question, then
   loosens the lowest-margin one until the item-level recall holds.
   `pass_above` is set so the passed labeled items reach a precision target
   (default 0.90); if none reaches it, there is no `pass_above` and
   everything not rejected goes to review. Choice questions report accuracy
   and a confusion table, and get a `min_confidence` chosen the same way.
4. **Fallback models.** See the fallback bullet above: per-hop models;
   `--model` overrides the primary hop only.
5. **Privacy on every sending path.** `calibrate` enforces the same refusal
   as `run` (labels are real data). `ask` requires a setup file with a
   privacy entry for the provider, or `--test-data`.
6. **Provider table.** Built into `decide.py`: the verified providers only.
   A setup file may add a `providers` block (endpoint, path, key env vars,
   image placement), marked user-added and treated as unverified;
   `references/providers.md` lists unverified hosts with a block to paste.
   Key env vars: `TYPESAFE_AI_API_KEY` (also accepts `TYPESAFE_API_KEY`),
   `OPENROUTER_API_KEY`, `OPENCODE_API_KEY`, and for ASI Cloud a name the
   builder confirms from ASI's docs (`ASI_API_KEY` until then, marked
   unverified).

## Left to the builder

- Exact default numbers for cautious mode and the review bands (starting
  values above).
- CSV column mapping details and the label-file field names.
- How `ask` formats its plain-language output.
- Whether `ask` and `run` share code paths internally.
- The exact `providers.md` table layout and which unverified providers to
  include (each marked unverified with its source).
