# Running an agent CLI inside the sandbox

The pattern for any agent CLI (opencode, codex, a custom harness):

1. **Runtime.** Bind the folder that holds the CLI and its interpreter with
   `--ro` (Node.js under `/opt`, a Python venv). Its `bin/` goes on `PATH`.
2. **Per-run home.** `HOME` is `/work`, so the agent reads its config from
   `/work/.config/...`. Create that from outside before the run, with only
   what the run needs. Never bind your real config or data folders (they
   often hold auth tokens; sandbox.py refuses the common ones).
3. **Keys.** Set each provider key the agent checks to a placeholder with
   `--setenv`, and let an egress proxy that injects credentials replace it.
   Without such a proxy the real key has to go in (`--pass-env`), and then
   the agent can read it: see [limits.md](limits.md).
4. **Non-interactive, machine-readable output** on stdout, captured outside.
   Auto-approve the agent's permission prompts: the sandbox is the guard.
5. **Results** go to `/work` (or stdout). `/tmp` inside is gone after the
   run.
6. **Time and size.** Wrap the call in `timeout`; add `--mem`, `--nproc` or
   `--cpu` if a runaway would hurt.

## Worked example: opencode

```bash
SANDBOX=path/to/skills/sandboxing/scripts/sandbox.py
NODE_DIR=$(dirname "$(dirname "$(command -v opencode)")")  # holds bin/opencode
RUN=$(mktemp -d /tmp/agent-run.XXXXXX); chmod 755 "$RUN"
mkdir -p "$RUN/work/.config/opencode" "$RUN/work/proj"
cp opencode.json "$RUN/work/.config/opencode/"   # providers, models, no keys
cp -r task-files/. "$RUN/work/proj/"             # what the agent works on

timeout 900 python3 "$SANDBOX" --work "$RUN/work" --ro "$NODE_DIR" \
    --setenv OPENROUTER_API_KEY=placeholder \
    -- sh -c 'cd /work/proj && exec opencode run --standalone --archived \
              --auto --format json --model "$1" "$2"' sh "$MODEL" "$PROMPT" \
    > "$RUN/events.jsonl" 2> "$RUN/stderr.txt"
echo "exit $?"
```

- `NODE_DIR` must be readable by the sandbox user: a runtime under `/opt`
  or `/usr/local` usually is; one under `/root` (or another root-only
  folder) fails preflight: copy it out.
- `--format json` prints one JSON event per line; read `events.jsonl` from
  outside. opencode's own data (sessions, logs) lands in
  `$RUN/work/.local/share/opencode`.
- `--standalone` gives the run a private opencode server instead of a shared
  background one; `--archived` keeps the session out of session lists;
  `--auto` approves permissions that aren't explicitly denied.
- Skills for the nested agent: copy them into its skill folder under
  `$RUN/work` (e.g. `$RUN/work/.claude/skills/<name>`), not as binds of your
  own skill folders.
- Started as root, `$RUN/work` is chowned to the sandbox user; you can still
  read and delete it. With `--work`, the folder is never removed for you.
- Several runs in parallel: one `$RUN` per run.

Check first what the run can see, with the same binds:

```bash
python3 "$SANDBOX" --work "$RUN/work" --ro "$NODE_DIR" --check
```
