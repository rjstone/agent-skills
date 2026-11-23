# Baseline without the skill (2026-11-23)

Ten runs (S1-S5, two each), fresh general-purpose subagent, no network, the
`decisions` skill and its design docs off limits. Other installed skills were
allowed (several runs named `provider-onboarding`). Rubric in `scenarios.md`.

## Scores

| Run | R1 endpoint | R2 privacy x3 | R3 calibrate / decline path | R4 reference | R5 review not drop | R6 fit | R7 plain | R8 family |
|---|---|---|---|---|---|---|---|---|
| S1a | no | no | offer yes / no decline path | yes | partial | no | yes | no |
| S1b | no | no | offer yes / no decline path | yes | no | no | yes | no |
| S2a | no | partial (1 of 3) | offer yes / no | yes | yes | no | yes | no |
| S2b | no | partial (1 of 3) | offer yes / no | yes | yes | partial | yes | no |
| S3a | no | no | no | partial | n/a | partial | yes | no |
| S3b | no | no | no | partial | n/a | partial | yes | no |
| S4a | no | partial (1 of 3) | offer yes / no | yes | yes | no | yes | no |
| S4b | no | partial (1 of 3) | offer yes / no | yes | yes | no | yes | no |
| S5a | no | partial | offer yes / no | n/a | yes | yes | yes | no |
| S5b | no | no | offer yes / no | n/a | yes | yes | yes | no |

Totals: R1 0/10, R2 0/10 full (5 partial), R3 offer 8/10 but decline path
0/10, R8 0/10. R4, R5 and R7 mostly pass; R6 mostly missing.

## Failures, verbatim

- **R1, decision model = cheap chat model (10/10).** Every draft posts to
  `/chat/completions` and parses JSON from text: "OpenAI-compatible chat
  payload; endpoint and model id are pending the provider check" (S1a);
  "Assumed an OpenAI-compatible /chat/completions endpoint" (S4a); "A normal
  LLM constrained to output only a valid code, plus a reason, would work the
  same way" (S2a). None knew the System One request shape or that answers
  are calibrated probabilities.
- **Self-reported confidence.** Drafts ask the chat model to output
  `"confidence": 0.0` in JSON (S2b, S2a) and threshold on it.
- **R2, privacy reduced to one question or missing.** Best case: "Is it
  acceptable to send invoice text to an external model API?" (S2a); "check
  your terms first" (S4a). No run named retention or training, assumed free
  models keep data, or asked who else must agree. S1a/S1b/S3 never raised it.
- **R3, no path for "no labels / no time".** Calibration is offered as the
  agent labelling items itself ("about 20 leads I've labelled myself", S1b) or
  a week of shadow mode; nothing says what to do or warn if the user declines.
- **R5, silent loss.** "Output that fails the schema gets a score of 0 and is
  flagged" then is not read (S1b); S1a reads only >= 70 plus a 5% sample.
- **R6, no fit check** except S5 ("If your routines already cost little, the
  honest answer may be 'not worth it'") and S3 (turn-based vs real-time).
- **R8, no model-family awareness.** S2b plans to "compare against one
  stronger model on the same set" with the same thresholds.
- **Repo bleed.** S5a/S5b went straight to a specific routine in the local
  environment; S2a reached for repo PDF tools. Not a rubric item; the skill
  should keep the first step generic (what are the items, how many, which
  decisions).

## What the skill must fix (form per writing-skills "match the form")

1. R1: a positive recipe - what a decision model is and the exact request
   (`decide.py`), plus one line that chat endpoints are not decision models.
2. R2: structural - the three confirmations as a required step with a slot
   in the setup file, enforced by the script.
3. R3: a conditional keyed on the user's answer (labels yes -> calibrate;
   no -> the warning text and cautious mode).
4. R5: routing contract (pass / review / reject) with errors -> review.
5. R6: a fit-check step first, with the rule of thumb.
6. R8: one line in the calibration step plus the script's family check.
