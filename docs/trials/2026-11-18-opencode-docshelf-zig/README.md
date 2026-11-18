# Trial: docshelf 0.8.0 with eight opencode models (Zig questions)

Date: 2026-11-18. opencode 2.3.0, `opencode run --format json`, one run per
model, each in its own `HOME` whose only skill is docshelf 0.8.0 and whose
default docshelf cache holds only the Zig 0.17.1 docvol (`run_trials.sh`).
The prompt asks about "the offline Zig 0.17.1 documentation available on
this machine" and never names the skill, so loading it from its description
is part of the test (as in the dash-docset opencode trials; the Haiku runs
in `../2026-11-18-haiku-node-zig-pony/` named the skill instead). Questions
Z1-Z3 and the answer key: that trial's `questions.md` and `key.md`.

Models: the set from an earlier dash-docset opencode trial (kept outside
this repo), keeping only models as strong as `nemotron-3-super-120b` or
stronger (the user, 2026-11-18: smaller ones were not worth testing).

## Results

docshelf I/O = (characters of each docshelf command as an agent types it +
characters it printed) / 4, as in the Haiku trial (`score_trials.py`).

| Model | Provider | Loaded docshelf | Score | docshelf calls | docshelf I/O (~tok) | Time |
|---|---|---|---|---|---|---|
| `nvidia/nemotron-3-super-120b-a12b` | Nous | yes | 3/3 | 11 | 1,221 | 132 s |
| `nvidia/nemotron-3.5-super-vl:free` | OpenRouter | **no** | 3/3 | 0 | - | 118 s |
| `stepfun/step-3.7-flash` | Nous | yes | 3/3 | 32 | 5,783 | 118 s |
| `mimo-v2.6-flash` | OpenCode Go | yes | 3/3 | 20 | 2,864 | 213 s |
| `Beam-1.0-501B-A23B` | Reflection | yes | 3/3 | 13 | 2,241 | 46 s |
| `deepseek-v4.1-flash` | OpenCode Go | yes | 3/3 | 10 | 1,912 | 82 s |
| `gpt-6-luna` | OpenCode Go | yes | 3/3 | 16 | 1,834 | 53 s |
| `muse-spark-1.3-contributor` | OpenCode Go | yes | 3/3 | 7 | 2,131 | 64 s |
| Haiku (Claude Code, skill named) | Anthropic | - | 3/3 | ~9 | 1,928 | 26 s |

All eight answered all three correctly. The scorer's patterns flagged
nemotron-120b's Z2 (no literal `continue :label` in the reply); the reply
says to label the switch and `continue` with the label and an operand,
quoting `zig:index#Labeled-switch`: correct.

## Observations

- 7 of 8 loaded docshelf from its description alone and answered with its
  REFs; none hit a docshelf error.
- `nemotron-3.5-super-vl` never loaded the skill: it ran `find / -iname
  "*zig*"`, found the cached docvol files, extracted the HTML from
  `db.json` to a file in `/tmp` and grepped it. Correct, but 25 shell calls
  and ~115k input tokens.
- nemotron-120b also searched the filesystem first (glob, `ls $HOME`) before
  loading the skill; ~208k input tokens.
- Cost spread with the skill: 7-32 docshelf calls and 1.2k-5.8k tokens of
  docshelf I/O. Step 3.7 Flash ran 32 calls (5.8k); nemotron-120b,
  DeepSeek and Luna were at or below Haiku's 1.9k.
- Input tokens (opencode's `step_finish` totals) depend on how each provider
  reports them (Luna reported almost none), so they are not compared here.

## Harness caveat

An isolated `HOME` does not stop `find /`: nemotron-vl listed the source
cache outside its home (it read only Zig docs there). Keep answer keys and
other runs' answers outside any path a model can read during a run. The raw
event logs are not committed (they hold local scratch paths).

## Re-run

```bash
export SRC_CACHE=<a docshelf cache with devdocs/zig>   # docshelf install zig
export OUT=<output folder>
docs/trials/2026-11-18-opencode-docshelf-zig/run_trials.sh \
  nous/nvidia/nemotron-3-super-120b-a12b "openrouter/nvidia/nemotron-3.5-super-vl:free" \
  nous/stepfun/step-3.7-flash opencode-go/mimo-v2.6-flash \
  reflection/Beam-1.0-501B-A23B opencode-go/deepseek-v4.1-flash \
  opencode-go/gpt-6-luna opencode-go/muse-spark-1.3-contributor
python3 docs/trials/2026-11-18-opencode-docshelf-zig/score_trials.py -v "$OUT"/*/
```
