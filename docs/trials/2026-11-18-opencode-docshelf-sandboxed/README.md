# Trial: docshelf 0.8.0, eight opencode models, four documentation sets, sandboxed

Date: 2026-11-18. opencode 2.3.0, `opencode run --format json`, one run per
model and documentation set: Zig 0.17.1, Node.js 26.3.1, Pony 0.38.1
(DevDocs) and HTTP (MDN, a Dash docset). Questions and answer key:
`questions.md`, `key.md` (Z/N/P as in `../2026-11-18-haiku-node-zig-pony/`,
plus three HTTP questions). The prompts never name the skill. Models: as in
`../2026-11-18-opencode-docshelf-zig/` (the eight from
`nemotron-3-super-120b` up).

## Sandbox

`run_trials.sh` runs every opencode run in a bubblewrap sandbox: started
under `env -i`, as an unprivileged host user (`setpriv`), with
`--clearenv`. A run sees placeholder provider keys (the egress proxy
injects the real ones), the proxy and CA variables, read-only `/usr`,
`/etc/ssl`, the Node.js folder and the HTTP docset (`/docsets`,
`DOCSHELF_DOCSET_DIRS`); a private `/tmp`, `/proc` and `/dev`; and its
model's own work folder, writable, as `/work` and `HOME` (a copy of the
skill, a docshelf cache with zig, node and pony, the opencode config). The
caller's home, the repos, other models' folders and the answer key do not
exist inside; `SMOKE=1` prints that view instead of running a model. Unlike
the unsandboxed Zig run, `find /` now finds only the model's own docs.

## Results

All 32 runs exited 0. Answers were checked with `score_trials.py` patterns
and, where flagged, by reading the reply. docshelf I/O = (characters typed
+ printed) / 4, as in the Haiku trial.

| Model | Sets answered (of 4) | Used docshelf | docshelf I/O, sum (~tok) | Time, sum |
|---|---|---|---|---|
| `gpt-6-luna` | 4 | 4 | 11,226 | 184 s |
| `stepfun/step-3.7-flash` | 4 | 4 | 13,699 | 249 s |
| `mimo-v2.6-flash` | 4 | 4 | 17,626 | 790 s |
| `deepseek-v4.1-flash` | 4 | 4 | 18,965 | 274 s |
| `muse-spark-1.3-contributor` | 4 | 4 | 21,948 | 193 s |
| `Beam-1.0-501B-A23B` | 4 | 2 (node, pony) | 4,838 (2 sets) | 94 s |
| `nvidia/nemotron-3.5-super-vl:free` | 4 | 0 | - | 314 s |
| `nvidia/nemotron-3-super-120b-a12b` | 1 (node) | 3 | 3,137 | 271 s |

Per set (docshelf I/O, ~tokens, runs that used the skill):

| Set | Luna | Step | MiMo | DeepSeek | Muse Spark | Beam | Haiku 0.8.0 (skill named) |
|---|---|---|---|---|---|---|---|
| zig | 1,450 | 2,201 | 3,629 | 2,559 | 3,199 | - | 1,928 |
| node | 3,726 | 2,279 | 3,443 | 3,983 | 4,562 | 2,296 | 2,997 |
| pony | 2,630 | 4,094 | 5,272 | 6,911 | 7,469 | 2,542 | ~2,591 |
| http | 3,420 | 5,125 | 5,282 | 5,512 | 6,718 | - | - |

## Observations

- Seven of eight answered every set correctly; five of them used
  docshelf in every run.
- Skipping the skill: nemotron-3.5-super-vl (all four) and Beam (zig,
  http) found the docs in their own home and read docshelf's cache files
  directly (`db.json` with `node -e`, docshelf's `fts.sqlite` with
  sqlite3) or the docset; correct, but nemotron-vl used 65k-107k input
  tokens per run.
- nemotron-3-super-120b failed three sets on its own side: on zig and http
  it ran 10-12 tool calls and stopped without a reply; on pony its reply
  degenerated into a repeated `<t <l <l ...`.
- docshelf usage errors: three models (DeepSeek, Muse Spark, nemotron-120b)
  passed `-d DOCVOL` to `show`, which rejects it ("unrecognized arguments:
  -d zig") though the REF already names the docvol; nemotron-120b ran
  `sources` without a query. TODO.md docshelf 7.6.
- docshelf I/O per set: 1.5k-7.5k tokens; DevDocs zig and node cheapest,
  pony and the HTTP docset dearest (long MDN pages).
- Input tokens (opencode's `step_finish` totals) depend on how providers
  report them (Luna reports almost none), so they are not compared.

## Re-run

```bash
apt-get install -y bubblewrap                 # if missing
export SRC_CACHE=<docshelf cache with devdocs/zig, node, pony>
export DOCSET_DIR=<folder holding HTTP.docset>
docs/trials/2026-11-18-opencode-docshelf-sandboxed/run_trials.sh <provider/model>...
python3 docs/trials/2026-11-18-opencode-docshelf-sandboxed/score_trials.py -v "$OUT"/*/
```

## Round 2: docshelf 0.8.1 (branch `update/docshelf`, PR #21)

Same eight models, sets and sandbox, one run each, on 0.8.1 (`show` and
`toc` accept a `-d` naming the REF's docvol). The scorer now reads Unicode
hyphens (U+2010-U+2015, U+2212) as `-`: nemotron-120b wrote
`Retry‑After` with a non-breaking hyphen.

| Model | Sets answered (of 4) | Used docshelf | docshelf I/O, sum (~tok) | Time, sum |
|---|---|---|---|---|
| `gpt-6-luna` | 4 | 4 | 10,502 | 129 s |
| `nvidia/nemotron-3-super-120b-a12b` | 4 | 4 | 9,889 | 206 s |
| `stepfun/step-3.7-flash` | 4 | 4 | 15,854 | 403 s |
| `deepseek-v4.1-flash` | 4 | 4 | 16,577 | 330 s |
| `muse-spark-1.3-contributor` | 4 | 4 | 16,718 | 189 s |
| `mimo-v2.6-flash` | 4 | 4 | 17,779 | 604 s |
| `Beam-1.0-501B-A23B` | 4 | 3 (not http) | 10,191 (3 sets) | 103 s |
| `nvidia/nemotron-3.5-super-vl:free` | 4 | 0 | - | 334 s |

- All eight answered all four sets (round 1: seven).
- nemotron-120b, which failed three sets in round 1 (no reply twice, a
  degenerate reply once), used docshelf in all four and answered all of
  them: round 1's failures were run-to-run variance, not a pattern.
- nemotron-vl again never loaded the skill (read the cache files).
- No run passed `-d` to `show` or `toc` this time, so 0.8.1's change was
  not exercised; no run failed on it either.
- New usage slips (mimo): `search "--permission"` (a query starting with
  `--` is read as an option; `search -d node -- --permission` works:
  options before `--`) and
  `list HTTP` (`list` takes no arguments).
- Luna stayed the cheapest and fastest of the models that always used the
  skill; totals moved by up to ~30% per model between rounds.
