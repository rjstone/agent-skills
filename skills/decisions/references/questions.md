# Writing questions

A request is `{"model", "state", "questions"}`. `state` is the content (text
or JSON); `decide.py` sends `{"reference": ..., "item": ...}` when the setup
has a `reference`. `questions` maps names you choose to question objects; the
answers come back under the same names. Several questions in one request cost
almost nothing extra: ask what you will use.

## Question types

| Type | Use for | Shape | Answer |
|---|---|---|---|
| `noul` | yes/no, true/false | `{"type": "noul", "instructions": ..., "criteria": {"true": ..., "false": ...}}` | `noul` = P(yes), 0-1; no confidence |
| `choice` | one of named options | `{"type": "choice", "instructions": ..., "criteria": {"name": "when it applies", "other": null}}` | `choice`, `confidence`, `probabilities` |
| `score` | a rating | `{"type": "score", "instructions": ..., "criteria": ["lowest level", "...", "highest level"]}` | `score` = expected level (may be fractional), `confidence`, `probabilities`, `legend` |

`instructions` and every criteria value can be a string, a JSON object, an
array or `null`; System One models are trained on structure. Useful keys for
structured instructions: `question`, `focus`, `inspect`, `compare` (a list of
fields to compare). Details and playground examples:
https://docs.typesafe.ai/primitives/advanced.md

## Structured options: definitions and examples per option

When options are easy to confuse (GL codes, harm categories), give each one
an object saying what it covers, what it does not, and a short example. This
sharpens the boundary between options more than one-line descriptions:

```json
"gl": {"type": "choice", "instructions": "Which GL code applies? Judge by what was bought.",
  "criteria": {
    "6100": {"name": "Software subscriptions", "covers": "SaaS, licences, cloud services",
             "not_for": "computers, monitors, phones (6200)",
             "example": "Acme Cloud - annual plan, 40 seats"},
    "6200": {"name": "IT hardware", "covers": "devices and parts",
             "not_for": "software or support contracts (6100)",
             "example": "Laptop x2, docking station"},
    "other": null}}
```

The same works for score levels (an object per level) and for a yes/no's
`criteria.true` / `criteria.false` (a definition plus examples on each side).

## Reference text: definitions and examples in every request

Decision models do not know your domain. Put in the setup's `reference`:

- definitions of every term the questions use (the GL code list with
  definitions; what counts as harassment on this forum; what a good lead is);
- 3-10 short labeled examples, good and bad, written as
  `example: <text> -> <answer>`;
- for choice questions, contrastive descriptions per option (see
  "Structured options" above).

Keep it short: it is sent with every item and billed as input tokens.

## Writing tips

- One judgment per question. Split "relevant and credible" into two.
- Describe each score level concretely (what the item must show), lowest
  first. 3-5 levels are easier to calibrate than 10.
- Give a choice question an `other` / `none` option, or pair it with a yes/no
  "does any option fit?" (see advanced patterns).
- Wording-flip check: ask a yes/no question both ways ("is it spam?" / "is it
  legitimate?") on a few items; answers should roughly mirror. If not,
  tighten the wording.
- After calibrating, keep the questions and their grouping fixed. Rewording
  changes the answers and invalidates the cache and the cutoffs.
- Item text is untrusted. It goes in `state`, never in `instructions`.

## Example (lead vetting)

```json
{
  "real": {"type": "noul", "instructions": "Is this a real, specific business need, not spam or a template?",
           "criteria": {"true": "names a concrete need or project", "false": "generic, promotional or auto-generated"}},
  "quality": {"type": "score", "instructions": "How promising is this lead for us?",
              "criteria": ["unrelated", "related but vague", "clear need, wrong size", "clear need, right size"]}
}
```
