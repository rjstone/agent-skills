# sandboxing skill (design)

Status: for the user's review. Branch `skill/sandboxing` (from `main`).

## Intent

A harness-agnostic skill (Claude Code, opencode, Codex, others) that lets an
agent run a nested agent or test harness on Linux in a lightweight
bubblewrap sandbox, so the nested run can't wander outside the folder and
environment it is given (the user, 2026-11-18). Two harms to prevent:

1. **Secrets reaching an inference provider.** The nested run can't read the
   caller's environment variables, other processes' `/proc/*/environ` or
   `cmdline`, or credential files, so it can't pull an API key, a session
   token or the caller's home folder into a prompt.
2. **Bumbling damage.** A test that runs `rm -rf` on the wrong path, or edits
   files it shouldn't, can touch only the work folder it was given.

The nested agent is cooperative: it is not trying to break out.

## Goals

- One stdlib Python script that runs a command in bwrap with: an empty
  environment (`env -i` before bwrap, `--clearenv`), its own PID, IPC, UTS
  and user namespaces with a private `/proc`, `/dev`, `/tmp`; read-only
  `/usr` and the TLS bits; an explicit list of read-only and writable binds;
  a non-root host user (`setpriv`) when started as root; network on (through
  the caller's HTTP(S) proxy) or off; optional address-space, process and CPU
  limits.
- A leak self-test that proves, on the machine at hand, that the sandbox
  hides a planted secret (environment variable, another process's
  environment, a root-only file, `grep -r /`) before an agent trusts it.
- SKILL.md that teaches the cheapest protection first: no shell for the
  tested model when narrow tools suffice; real keys kept outside the
  sandbox (proxy-injected credentials, placeholder keys inside); then the
  sandbox for the rest.
- A recipe for running a nested agent CLI (opencode as the worked example)
  inside it, including a runtime that lives outside `/usr` (e.g. Node.js
  under `/opt`), a per-run `HOME`, and placeholder keys.

## Non-goals and anti-goals

- **Not malware or adversarial containment.** A capable model told to
  escape, or hostile code, needs stronger isolation (nsjail with a syscall
  policy, gVisor, a microVM). SKILL.md says so up front and names them
  (the user, 2026-11-18).
- No macOS or Windows support now: `compatibility` says Linux (the user,
  2026-11-18: usually done in a Linux container; others may come later).
- No network allowlist or traffic inspection: the sandbox shares the
  network (or has none); filtering is the proxy's job.
- No seccomp filter, no per-harness integration (hooks, settings files).
- Anti-goal: a sandbox that silently leaks, e.g. one launched without
  `env -i` (bwrap's own PID 1 keeps the launcher's environment, readable via
  `/proc/1/environ`), or one that binds the caller's home "for convenience".

## Constraints

- Public repo rules (AGENTS.md): no machine or account details, no private
  repo names; paths in the skill are relative to its folder; stdlib only.
- Frontmatter standard; `compatibility`: Linux with bubblewrap and
  unprivileged user namespaces; `setpriv` (util-linux) for the non-root
  user.
- Runs where agents run: often root in a container. Bind sources must be
  readable by the non-root sandbox user (a root-only parent folder, such as
  an agent's scratch folder, makes bwrap fail with "Permission denied").

## Approaches (picked: A, the builder's call; the user handed over the how)

- **A. Stdlib Python script driving `bwrap` (picked).** Testable with the
  repo's `unittest` suite (the bwrap command is built by a pure function),
  preflight checks with clear errors, works from any harness that can run a
  shell command.
- B. A bash script (a `run.sh`-style wrapper). Shorter, but harder to test
  and to give good errors; the repo prefers Python scripts.
- C. Docs only: SKILL.md teaches agents to assemble bwrap commands. Fragile:
  the easy-to-miss parts (`env -i`, readable sources, the CA copy) are
  exactly what agents drop.

## Design

```
skills/sandboxing/
  SKILL.md
  scripts/sandbox.py        # the wrapper
  scripts/leak_test.py      # self-test: plants markers, probes inside
  references/limits.md      # threat model, what it does not protect, stronger tools
  references/nested-agents.md  # recipe: an agent CLI (opencode) inside the sandbox
tests/test_sandboxing.py
```

`sandbox.py [options] -- COMMAND [ARGS...]`:

| Option | Meaning |
|-|-|
| `--work DIR` | writable folder mounted at `/work`, also `HOME` and the working directory (default: a new temp folder, removed afterwards unless `--keep`) |
| `--ro SRC[:DEST]` | read-only bind (repeatable); DEST defaults to SRC |
| `--rw SRC[:DEST]` | writable bind (repeatable) |
| `--setenv NAME=VALUE` | set a variable inside (repeatable): placeholders, config |
| `--pass-env NAME` | copy a caller variable in (repeatable; it becomes readable inside) |
| `--user NAME` | host user to run bwrap as (default `sandboxer` when started as root; created if missing); refuses `root` |
| `--no-net` | no network (default: shared, with the caller's proxy variables and a readable CA copy) |
| `--mem MB`, `--nproc N`, `--cpu SEC` | `prlimit` limits |
| `--keep` | keep the default work folder |
| `--allow-proxy-credentials` | pass a proxy URL that contains `user@` (refused otherwise) |
| `--show` | print the bwrap command and exit |
| `--check` | run a probe inside that prints what it can see (env names, `/`, whether the caller's home exists) |

Preflight (each fails with exit 2 and a message saying what to do): bwrap
missing; user namespaces unusable; a bind source missing or not readable by
the sandbox user (names the first unreadable parent); a bind of the caller's
home, `/root` or a known credential folder (`~/.ssh`, `~/.aws`, `~/.config/gh`,
`~/.claude`, `~/.codex`, `~/.local/share/opencode`) unless `--allow-sensitive`;
a proxy URL with credentials.

Inside: uid 1000, `HOME=/work`, `PATH` with `/usr/local/bin:/usr/bin:/bin`
plus the `bin` folder of each `--ro` bind that has one (so a runtime under
`/opt` works), `LANG=C.UTF-8`, the CA copy at `/ca.crt` set as
`SSL_CERT_FILE`, `CURL_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`,
`NODE_EXTRA_CA_CERTS`. The CA source: `SSL_CERT_FILE` if set and readable,
else the system bundle.

`leak_test.py [--user NAME]`: plants a random marker (split in halves so the
probe's own argv can't contain it) in an environment variable, in a
long-running outside process's environment, and in a root-only file; runs
probes inside via `sandbox.py`: `env`, `/proc/*/environ`, `/proc/*/cmdline`,
the file, the caller's home, `grep -r /`; also checks `/work` is writable,
HTTPS through the proxy (when a proxy is set), and from the host side which
user the sandboxed process runs as. Prints `ok`/`LEAK` per probe and exits 1
on any leak.

## Tests

`tests/test_sandboxing.py` (stdlib `unittest`, `selected("sandboxing")`):
unit tests of the pure command builder and the preflight checks (no bwrap
needed); integration tests (the leak test, `--check`, limits, `--no-net`)
skipped unless bwrap works on the machine (GitHub's Ubuntu runners may
restrict unprivileged user namespaces). Agent trial per the repo's rule 4:
the sandboxed opencode trial rerun through `sandbox.py`, and a with/without
skill check that an agent asked to "run this harness so it can't see my
keys" uses the script and the leak test.

## Left to the builder

Exact option spellings beyond those above, message wording, the PATH rule's
details, how the leak test's outside process is started and stopped,
integration-test skip logic.
