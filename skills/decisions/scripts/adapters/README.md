# Sample adapters

`decide.py` speaks only the System One format. A few decision APIs use their
own format; these files are a head start for those, not supported code.
`systemone_minimal.py` is the shortest possible System One call, for a
person to read in a minute; use `decide.py` for real work.

| File | Service | Status |
|---|---|---|
| `systemone_minimal.py` | any System One host (plain request, for reading) | sample |
| `vercel_evaluate.py` | Vercel AI Gateway `/v1/evaluate` | sample, unverified |
| `levanto_sage.py` | Levanto Sage `/decide` | sample, unverified |

Every adapter exposes the same contract:

```python
evaluate(state, questions, *, key, model, timeout=60) -> answers
```

`questions` are System One questions and `answers` come back System One-shaped
(`{"type": "noul", "noul": p}`, `{"type": "choice", ...}`, `{"type": "score", ...}`),
so `decide.route()` and `decide.effective_rules()` work unchanged:

```python
import decide, vercel_evaluate as adapter
answers = adapter.evaluate(state, setup["questions"], key=key, model="...")
cautious, _ = decide.is_cautious(setup)
print(decide.route(answers, decide.effective_rules(setup["policy"], setup["questions"], cautious)))
```

Each adapter's `evaluate()` starts with a `raise RuntimeError(...)` line. It
stays until your code runs the privacy check first (record the confirmation
with `decide.py privacy`, then call `decide.check_privacy(name, setup, False)`
before `evaluate()`); delete that line only then.

Before using one: read the service's current docs and fix the field names,
run one call with made-up data, keep the privacy check (`references/privacy.md`)
and calibrate again: a different service is a different model family.
