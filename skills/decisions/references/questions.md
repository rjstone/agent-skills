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

`instructions` and criteria can be strings or small JSON objects. Useful keys
for structured instructions: `question`, `focus`, `inspect`, `compare`.

## Reference text: definitions and examples in every request

Decision models do not know your domain. Put in the setup's `reference`:

- definitions of every term the questions use (the GL code list with
  definitions; what counts as harassment on this forum; what a good lead is);
- 3-10 short labeled examples, good and bad, written as
  `example: <text> -> <answer>`;
- for choice questions, contrastive descriptions (`"6100": "software
  subscriptions, not hardware"`).

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
