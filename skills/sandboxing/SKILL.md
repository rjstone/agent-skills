---
name: sandboxing
description: Use when running a nested agent CLI (opencode, codex, another model), a test harness or an untrusted-but-cooperative script on Linux that must not see your environment variables, API keys, other processes or files outside its own folder, or must not damage files it wasn't given - "run it so it can't read my keys", "keep the tested model away from my home folder", bubblewrap/bwrap.
compatibility: "Linux only: needs bubblewrap (bwrap) with unprivileged user namespaces, and util-linux setpriv and prlimit."
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.2.0"
---

# Sandboxing

**Not for hostile code.** This keeps a cooperative program (a nested agent, a
test harness) from wandering: reading your keys or files by accident, sending
them to an inference provider, or `rm -rf`-ing the wrong folder. Code that is
trying to escape needs stronger isolation: see
[references/limits.md](references/limits.md).

## Cheapest protection first
1. **No shell for the tested model** when narrow tools will do (a read-only
   docs tool, a fixed command). Nothing to sandbox.
2. **Keep real keys outside.** Use an egress proxy that injects credentials,
   or a key file read only by the caller; inside, set placeholder keys
   (`--setenv OPENROUTER_API_KEY=placeholder`).
3. **Then the sandbox** for whatever still runs commands.

## Quick start
```bash
python3 scripts/leak_test.py        # once per machine: must print PASS
python3 scripts/sandbox.py --check  # what a sandboxed command sees
python3 scripts/sandbox.py --work /tmp/run1 --ro /opt/node \
    --setenv OPENROUTER_API_KEY=placeholder -- CMD [ARGS...]
```
`scripts/` is relative to this skill's folder. Exit status is the command's
(a signal gives 128+N; under `timeout`, 124). sandbox.py's own errors (bad
option, preflight, missing tool) exit 125, as `env` and `timeout` do, with a
`sandbox.py: error:` line on stderr saying what to fix; check that line when
the command itself might exit 125. `--show` prints the full `bwrap` command
without running it.

Inside, the command sees: an empty environment plus `HOME=/work`, `PATH`,
`LANG`, `TMPDIR=/tmp`, the caller's proxy variables and the CA variables;
uid 1000; read-only `/usr`, `/etc/ssl`; private `/proc`, `/dev` and `/tmp`;
`/work` (writable) and only the binds you add.

| Option | Effect |
|-|-|
| `--work DIR` | writable folder at `/work` (also `HOME` and the cwd); default: a new folder in `/tmp`, removed afterwards unless `--keep` |
| `--cwd DIR` | working directory inside, relative to `/work` (e.g. `--cwd proj`); must exist |
| `--ro SRC[:DEST]`, `--rw SRC[:DEST]` | read-only / writable bind (repeatable); `SRC/bin` of a `--ro` bind goes on `PATH` |
| `--setenv NAME=VALUE`, `--pass-env NAME` | set a variable inside; copy one of yours in (readable inside: never a real key) |
| `--no-net` | no network; default is shared network with your proxy variables and a CA copy at `/ca.crt` |
| `--mem MB`, `--nproc N`, `--cpu SEC` | limits (prlimit); `--mem` caps address space, not memory use |
| `--user NAME` | host user when started as root (default `sandboxer`, created if missing) |

## Gotchas
- **Started as root**, bwrap runs as the `sandboxer` host user (setpriv), and
  `--work` is chowned to it. Every bind source must be readable by that user:
  a root-only parent (an agent's scratch folder) fails preflight with the
  folder's name. Copy the data under `/tmp` (`chmod -R a+rX`) instead.
  A `--rw` source must also be writable by it (preflight says so otherwise);
  files made there belong to `sandboxer` on the host.
- **`--mem` and Node.js**: `--mem` limits virtual address space, and V8
  reserves a lot of it at startup, so Node (and opencode's runtime) dies below
  about 768 MB ("Failed to reserve virtual memory", exit 133/134) while using
  far less. Use `--mem 1024` or more for Node-based commands; sandbox.py warns.
- **Runtimes outside `/usr`** (Node.js under `/opt`, a venv): bind the
  runtime's folder with `--ro`; its `bin/` is then on `PATH`.
- **`HOME=/work`**: config goes in `/work/.config/...`; put it in the work
  folder before the run. `/tmp` is private and gone after the run: write
  results to `/work` and read them from outside.
- **Refused binds**: your home, `/root`, `~/.ssh`, `~/.aws`, `~/.config/gh`,
  `~/.claude`, `~/.codex`, `~/.local/share/opencode`, or a folder holding
  them. Bind a narrower folder (`--allow-sensitive` overrides; don't).
- **Proxy URL with `user:password@`** is refused, since it would be readable
  inside (`--allow-proxy-credentials` overrides).
- **No `/etc/passwd`**: `whoami` fails and git needs `user.name`/`user.email`
  set. `/etc/hosts` is a minimal one (`localhost` only, not the host's file,
  which may name internal hosts); `--ro /etc/hosts` binds yours instead.
- Everything you bind or pass in is readable by the command: that is the
  boundary.

## Read when needed
- [references/nested-agents.md](references/nested-agents.md): running
  opencode (or any agent CLI) inside, with placeholder keys and JSON output.
- [references/limits.md](references/limits.md): threat model, what this does
  not protect, stronger tools.
