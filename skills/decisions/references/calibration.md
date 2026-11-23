# Calibration and cautious mode

A decision model ranks items well but its probabilities do not match your
data's base rates, so a cutoff must come from your own labeled items. Cutoffs
belong to one **model family**; another family needs its own calibration.

## Labels

JSONL, one labeled item per line, with the expected answer per question:

```json
{"id": "L1", "item": {"text": "We need 40 seats of X by March"}, "expected": {"real": true, "quality": 3}}
{"id": "L2", "item": {"text": "Best SEO deals!!!"}, "expected": {"real": false, "quality": 0}}
{"id": "I7", "item": "Invoice: Acme Cloud, annual subscription", "expected": {"code": "6100"}}
```

More is better. Aim for 20+ items, at least 3 per class (good and not good,
and each choice option you care about), including borderline cases. A few is
the bare minimum and better than none. Labels the user gives beat labels you
make up; if you label, show the user your labels first.

`policy.good_if` defines a good item from the expected answers, set during
the interview: `[{"question": "real", "is": true}, {"question": "quality",
"at_least": 2}]` (also `{"question": "code", "in": ["6100", "6200"]}`).
Without it, every yes/no must be yes and every score at least its middle level.

## What `calibrate` does

- Scores every label (real data: needs the privacy confirmation).
- Reports AUROC for yes/no and score questions (1.0 perfect ranking, 0.5
  chance), accuracy and a confusion table for choice questions, and warnings
  for small label sets.
- Sets cutoffs, recall first: `reject_below` keeps at least 95% of good items
  (`--target-recall`), loosened per item when several questions combine;
  `pass_above` only where passed items are at least 90% good
  (`--target-precision`), otherwise everything not rejected goes to review;
  `min_confidence` for choice questions where answers at or above it are at
  least 90% right.
- Keeps rules the user wrote (`"source": "user"`) unless
  `--replace-user-rules`; its suggestions appear in the report.
- Records model, provider, date, counts and metrics in `calibration`, and
  sets `policy.mode` to `calibrated`.

`calibrate --check` rescoring compares against the stored record without
changing anything: run it after a model version change within the family.

## Cautious mode

On when the setup is not calibrated, or the answering model is from another
family than the calibrated one. It only widens the review band: yes/no
rejects only below 0.05 and passes only above 0.90; scores reject below 0.5
and pass only near the top level; choice and score answers with confidence
under 0.6 go to review. Every run's summary says cautious mode is on and why.

When the user declines calibration, say so plainly (wording in `SKILL.md`
step 5) and keep cautious mode. Read every `review` item. Offer calibration
again once there are reviewed items: those make good labels.
