# Trial: sandboxing 0.1.0

Date: 2026-11-18. Two checks of the `sandboxing` skill: the sandboxed
opencode docshelf trial rerun through `sandbox.py`, and a with/without-skill
check with two Haiku agents (AGENTS.md rule 4).

## 1. opencode docshelf trial through sandbox.py

`run_trials.sh` reruns the Zig set of
`../2026-11-18-opencode-docshelf-sandboxed/` (questions Z1-Z3, the same
eight models, opencode 2.3.2, docshelf 0.8.0) with the hand-written
`env -i setpriv bwrap` command replaced by one `sandbox.py` call:
`--work` (the model's folder: skill copy, docshelf cache, opencode config),
`--ro` the Node.js folder (its `bin/` lands on `PATH`) and placeholder
provider keys via `--setenv`; the egress proxy injects the real ones.
Scored with that trial's `score_trials.py`, unchanged.

| Model | Score | Used docshelf | docshelf calls | docshelf I/O (~tok) | Earlier sandboxed zig run (~tok) | Time |
|---|---|---|---|---|---|---|
| `gpt-6-luna` | 3/3 | yes | 15 | 1,867 | 1,450 | 45 s |
| `Beam-1.0-501B-A23B` | 3/3 | yes | 11 | 1,875 | did not use docshelf | 30 s |
| `mimo-v2.6-flash` | 3/3 | yes | 15 | 1,827 | 3,629 | 245 s |
| `nvidia/nemotron-3-super-120b-a12b` | 3/3 | yes | 18 | 2,335 | no reply (stopped after tool calls) | 110 s |
| `deepseek-v4.1-flash` | 3/3 | yes | 16 | 2,671 | 2,559 | 91 s |
| `muse-spark-1.3-contributor` | 3/3 | yes | 11 | 2,764 | 3,199 | 48 s |
| `stepfun/step-3.7-flash` | 3/3 | yes | 41 | 6,047 | 2,201 | 149 s |
| `nvidia/nemotron-3.5-super-vl:free` | 0/3 (timeout) | no | 0 | - | did not use docshelf | 600 s |

- Seven of eight answered all three questions, all through docshelf, with
  no docshelf errors. No run failed for a sandbox reason.
- nemotron-3.5-super-vl skipped the skill again: `find /`, `ls /root
  /home` (neither exists inside), then `grep` over docshelf's `db.json`
  until the 600 s timeout. Its `find /` saw only its own work folder.
- The timeout's exit status 124 came through `sandbox.py` unchanged.
- Setting up the harness hit the preflight check it was built for: an
  output folder from `mktemp -d` (mode 700) was refused with the folder
  named; the harness now runs `chmod 755` on it.

## 2. With and without the skill (Haiku)

Prompt to both: "Run this test harness so it can't see my environment
variables or files outside its folder: `<folder>/run_tests.py`" (a two-test
`unittest` file that writes `scratch.txt` and prints how many environment
variables it sees). Both agents ran as root in a container where bubblewrap
was already installed. Only one was told where the skill was installed.

| | With the skill | Without |
|---|---|---|
| Sandbox | `sandbox.py --work W --ro <folder> -- python3 <folder>/run_tests.py` | hand-written `bwrap` (`--unshare-all --clearenv`, `/usr` read-only, the folder bound writable as `/work`) |
| Checked it first | `leak_test.py` (PASS) and `sandbox.py --check` | its own spot check |
| Host user of the process | `sandboxer` (unprivileged) | root |
| Harness folder | read-only; writes go to a separate work folder | writable |
| Network | via the proxy (proxy and CA variables, 13 in all) | none (4 variables) |
| Result | 2 tests OK, exit 0 | 2 tests OK, exit 0 |

Both met the prompt. With the skill the agent verified the sandbox before
use, kept the harness read-only and did not run it as host root. Without
it, the agent depended on bubblewrap already being installed, ran the
process as host root and gave it a writable copy of the folder. It also cut
the network, which this prompt allowed.

## Re-run

```bash
export SRC_CACHE=<a docshelf cache with devdocs/zig>   # docshelf install zig
docs/trials/2026-11-18-sandboxing-skill/run_trials.sh \
  nous/nvidia/nemotron-3-super-120b-a12b "openrouter/nvidia/nemotron-3.5-super-vl:free" \
  nous/stepfun/step-3.7-flash opencode-go/mimo-v2.6-flash \
  reflection/Beam-1.0-501B-A23B opencode-go/deepseek-v4.1-flash \
  opencode-go/gpt-6-luna opencode-go/muse-spark-1.3-contributor
python3 docs/trials/2026-11-18-opencode-docshelf-sandboxed/score_trials.py -v "$OUT"/*/
```
