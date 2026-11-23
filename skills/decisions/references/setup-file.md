# Setup file (`<name>.decisions.json`)

One JSON file per task, in the user's project. `decide.py` reads it and writes
the `privacy` and `calibration` parts (atomically). The cache lives beside it
as `<name>.decisions.cache.sqlite`.

| Field | Required | Meaning |
|---|---|---|
| `name` | no | a label |
| `provider` | yes | built-in name (`opencode`, `typesafe`, `openrouter`, `perplexity`) or one in `providers` |
| `model` | no | model id for the primary provider; defaults to the provider's default |
| `fallbacks` | no | `[{"provider", "model"}]`, tried in order; same model family only |
| `reference` | no | definitions and labeled examples sent with every item |
| `questions` | yes | see `questions.md` |
| `policy.mode` | no | `cautious` (default) or `calibrated` (set by `calibrate` when its warning list is empty) |
| `policy.good_if` | no | what a good item is, for calibration |
| `policy.rules` | no | routing rules (below) |
| `policy.combine` | no | `all` (default, screening: any reject rejects) or `any` (flagging: any pass flags) |
| `calibration` | no | written by `calibrate`: model, provider, date, labels, counts, metrics, warnings |
| `privacy` | no | written by `decide.py privacy`: `{provider: {confirmed, policy_url, summary, endpoint}}` |
| `providers` | no | extra hosts: `{name: {endpoint, key_env, default_model}}`, always unverified |

## Rules

```json
{"question": "real", "reject_below": 0.10, "pass_above": 0.80, "source": "user"}
{"question": "quality", "reject_below": 0.8, "pass_above": 2.2, "min_confidence": 0.5}
{"question": "team", "routes": {"ops": "pass", "sales": "reject"}, "min_confidence": 0.7}
{"question": "code", "min_confidence": 0.72}
```

- yes/no and score: below `reject_below` -> reject; above `pass_above` ->
  pass; otherwise, or confidence under `min_confidence` -> review. No
  `pass_above` means nothing passes automatically.
- choice: `routes` maps option names to routes, unlisted options -> review;
  no `routes` means any confident answer passes (code assignment).
- An item is `reject` if any rule rejects, else `review` if any reviews, else
  `pass`. Questions without a rule are informational. Errors -> review.
- With `"combine": "any"` (moderation, alerts): `pass` (flagged) if any rule
  passes, `reject` only if every rule rejects, otherwise `review`.

`decide.py` checks this shape when it loads the file and names the first
problem (questions as a list, `good_if` as text, a rule naming an unknown
question).

## Example

[`examples/lead-vetting.decisions.json`](../examples/lead-vetting.decisions.json)
is a starting point: cautious mode, no privacy entry yet (so it refuses real
data until the privacy step, `new-setup.md` step 5).
