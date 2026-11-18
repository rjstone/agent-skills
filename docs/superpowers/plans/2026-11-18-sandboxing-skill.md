# sandboxing skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A harness-agnostic, Linux-only skill whose stdlib script runs a
nested agent or test harness in a bubblewrap sandbox that hides the caller's
environment, processes and files, plus a leak self-test.

**Architecture:** `scripts/sandbox.py` parses options, runs preflight checks
and builds the `env -i [setpriv ...] bwrap ...` command with a pure function
(`build_command`), then `exec`s it. `scripts/leak_test.py` plants markers and
probes from inside via `sandbox.py`. SKILL.md teaches when to use it (and the
cheaper protections first); two references hold the limits and the
nested-agent recipe.

**Tech Stack:** Python 3 stdlib, `unittest`; system `bwrap`, `setpriv`,
`prlimit`.

**Spec:** `docs/superpowers/specs/2026-11-18-sandboxing-skill-design.md`

## Global Constraints

- Skill name `sandboxing`, folder `skills/sandboxing/`, version `"0.1.0"`,
  frontmatter per AGENTS.md; `compatibility`: "Linux only: needs bubblewrap
  (bwrap) with unprivileged user namespaces, and util-linux setpriv and
  prlimit." Description starts "Use when".
- Stdlib only; scripts run as `python3 scripts/sandbox.py` from anywhere
  (paths relative to the script's folder).
- Public repo: no machine or account details, no private repo names, no
  absolute paths except system locations (`/usr`, `/etc/ssl`, `/proc`,
  `/tmp`, `/work` inside the sandbox) and made-up test fixtures.
- Not a security boundary against hostile code: SKILL.md and
  `references/limits.md` say so and name stronger tools (nsjail, gVisor,
  microVMs).
- `env -i` before bwrap and `--clearenv` always; never bind the caller's
  home, `/root` or known credential folders without `--allow-sensitive`;
  refuse a proxy URL with credentials without `--allow-proxy-credentials`.
- Tests: `tests/test_sandboxing.py` starts with the `selected("sandboxing")`
  skip; integration tests skip unless bwrap works here; no network in tests
  except the proxy probe, which skips without a proxy.
- Branch `skill/sandboxing`; when approved, squash-merge (AGENTS.md "Adding a
  skill").
- Subagents never call session, messaging, scheduling, trigger or
  environment tools, and never dispatch subagents.

## Review Focus

1. A bind source under a root-only parent (an agent's scratch folder) when
   bwrap runs as the non-root user: a preflight error naming the unreadable
   folder, not bwrap's bare "Permission denied" (Task 1
   `test_preflight_unreadable_parent`).
2. A command whose runtime lives outside `/usr` (Node.js under `/opt`):
   bound with `--ro` and found on `PATH` inside (Task 1
   `test_path_includes_bin_of_ro_binds`, Task 2 integration
   `test_runtime_outside_usr`).
3. Started as a non-root user already: no `setpriv`/`useradd`, still works
   (Task 1 `test_non_root_caller_skips_setpriv`).
4. The work folder's ownership after the run: the caller can still read and
   delete it (Task 2 `test_work_folder_usable_after_run`).
5. Exit status of the sandboxed command is passed through, including a
   timeout or limit kill (Task 2 `test_exit_status_passed_through`).

---

### Task 1: `scripts/sandbox.py` (options, preflight, command builder)

**Files:**
- Create: `skills/sandboxing/scripts/sandbox.py`
- Create: `tests/test_sandboxing.py`

**Interfaces:**
- Produces: `VERSION = "0.1.0"`;
  `parse_args(argv: list[str]) -> argparse.Namespace`;
  `preflight(opts, env: dict, euid: int) -> list[str]` (error messages;
  empty when fine);
  `build_command(opts, env: dict, euid: int, work: str, ca_copy: str | None) -> list[str]`;
  `main(argv=None) -> int` (exit 2 on usage/preflight errors; otherwise
  `os.execvp`s the built command).

- [x] **Step 1: Write the failing unit tests** (no bwrap needed):
  - `test_command_starts_with_env_i`: `build_command(...)[0:2] == ["env", "-i"]`.
  - `test_root_caller_uses_setpriv`: euid 0 -> `setpriv` with `--reuid`,
    `--no-new-privs`, `--bounding-set=-all` before `bwrap`.
  - `test_non_root_caller_skips_setpriv`: euid 1000 -> no `setpriv`.
  - `test_clearenv_and_home`: `--clearenv`, `--setenv HOME /work`,
    `--bind <work> /work`, `--chdir /work`.
  - `test_ro_and_rw_binds`: `--ro a:b` -> `--ro-bind a b`; `--ro a` ->
    `--ro-bind a a`; `--rw` -> `--bind`.
  - `test_path_includes_bin_of_ro_binds`: a `--ro` dir with a `bin/`
    subfolder puts `<dest>/bin` first in `PATH`.
  - `test_no_net`: `--no-net` -> no `--share-net`, no proxy variables, no
    `/ca.crt`; default -> `--share-net`, proxy variables copied, `/ca.crt`
    bound and set as `SSL_CERT_FILE`, `CURL_CA_BUNDLE`,
    `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`.
  - `test_setenv_and_pass_env`: values appear as `--setenv`; `--pass-env X`
    with X unset is a preflight error.
  - `test_limits_use_prlimit`: `--mem 256 --nproc 30 --cpu 5` -> `prlimit
    --as=268435456 --nproc=30 --cpu=5 --` before the command.
  - `test_preflight_refuses_sensitive_binds`: binding `$HOME`, `/root`,
    `$HOME/.ssh`, `$HOME/.aws`, `$HOME/.config/gh`, `$HOME/.claude`,
    `$HOME/.codex`, `$HOME/.local/share/opencode` -> error; with
    `--allow-sensitive` -> none.
  - `test_preflight_refuses_proxy_credentials`: `HTTPS_PROXY=http://u:p@h:1`
    -> error; with `--allow-proxy-credentials` -> none.
  - `test_preflight_unreadable_parent`: a source under a mode-700 folder,
    euid 0, sandbox user not root -> error naming that folder.
  - `test_refuses_user_root`: `--user root` -> error.
  - `test_show_prints_command`: `main(["--show", "--", "true"])` prints the
    command, exit 0.
- [x] **Step 2: Run, verify they fail:** `python3 -m unittest tests.test_sandboxing -v`
- [x] **Step 3: Implement.** Bind set from the spec (read-only `/usr`, the
  `/bin`, `/lib`, `/lib64`, `/sbin` symlinks, `/etc/resolv.conf`,
  `/etc/ssl`, `--ro-bind-try /etc/alternatives`; `--proc /proc`, `--dev
  /dev`, `--tmpfs /tmp`; `--unshare-all --die-with-parent --new-session
  --uid 1000 --gid 1000`). Default work folder and CA copy in a new
  `/tmp/sandbox.*` folder with mode 755 (readable by the sandbox user),
  removed after the run unless `--keep` (so `main` runs the command with
  `subprocess` and returns its status when cleanup is needed, else
  `execvp`). Create the sandbox user with `useradd -M -s /usr/sbin/nologin`
  when missing; `chown -R` the work folder to it.
- [x] **Step 4: Run the unit tests, then the full suite.**
- [x] **Step 5: Commit** `sandboxing: sandbox.py (bwrap wrapper) with unit tests`.

### Task 2: `scripts/leak_test.py` and integration tests

**Files:**
- Create: `skills/sandboxing/scripts/leak_test.py`
- Modify: `tests/test_sandboxing.py` (class `IntegrationTests`)

**Interfaces:**
- Consumes: `sandbox.py`'s CLI (run as a subprocess).
- Produces: `leak_test.py [--user NAME] [--no-net]`: prints one
  `ok`/`LEAK`/`info` line per probe and `PASS`/`FAIL`; exit 0/1 (2 when
  bwrap is unusable).

- [x] **Step 1: Write the failing integration tests** (skip unless
  `bwrap --unshare-all --uid 1000 -- true` works here):
  - `test_leak_test_passes`: `leak_test.py` exit 0, output ends `PASS`.
  - `test_env_not_visible`: a caller variable `SECRET_X=marker` is absent
    inside `sandbox.py -- env`.
  - `test_caller_home_not_visible`: `test -e $HOME` inside is false.
  - `test_runtime_outside_usr`: a temp folder with `bin/hello` (a shell
    script) bound with `--ro` runs as `hello`.
  - `test_work_folder_usable_after_run`: after `--work W -- touch /work/f`,
    the caller can read and delete `W/f`.
  - `test_exit_status_passed_through`: `-- sh -c "exit 7"` -> 7; `--cpu 1 --
    sh -c "while :; do :; done"` -> killed (non-zero).
  - `test_no_net_blocks_network`: `--no-net -- python3 -c` socket connect
    fails.
- [x] **Step 2: Run, verify they fail** (leak_test.py missing).
- [x] **Step 3: Implement `leak_test.py`.** Marker split in halves (the
  probe reads it from a file, so its own argv never holds it); an outside
  `sleep` process started with the marker in its environment and killed
  afterwards; a root-only file (mode 600) under a temp folder; probes
  inside via `sandbox.py`: `env`, `/proc/*/environ`, `/proc/*/cmdline`, the
  file, the caller's home, `grep -r` over `/`; `/work` writable; HTTPS via
  the proxy when one is set (`info`); the host user of the sandboxed process
  from the host side (`ps -o user`), `info`.
- [x] **Step 4: Run the integration tests here (bwrap installed), then the full suite.**
- [x] **Step 5: Commit** `sandboxing: leak_test.py and integration tests`.

### Task 3: SKILL.md and references

**Files:**
- Create: `skills/sandboxing/SKILL.md`, `skills/sandboxing/references/limits.md`,
  `skills/sandboxing/references/nested-agents.md`
- Modify: `AGENTS.md` (Skills list: one entry), `TODO.md` if follow-ups

**Interfaces:**
- Consumes: Tasks 1-2 CLIs (SKILL.md documents them; no syntax beyond
  them).

- [x] **Step 1: Write the failing test:** `test_skill_md_names_only_real_options`:
  every `--option` named in SKILL.md and the references exists in
  `sandbox.py`'s or `leak_test.py`'s parser (the repo's `test_skills.py`
  then also checks frontmatter and that both references are linked).
- [x] **Step 2: Run, verify it fails.**
- [x] **Step 3: Write.** SKILL.md (short): when to use; "Not for hostile
  code" first; cheapest first (no shell for the tested model when narrow
  tools do; keep real keys outside, placeholders inside); quick start
  (`leak_test.py` once, then `sandbox.py --work DIR --ro RUNTIME --setenv
  KEY=placeholder -- CMD`); gotchas (bind sources readable by the sandbox
  user; runtimes outside `/usr`; `HOME=/work`; private `/tmp`); "Read when
  needed" links. `limits.md`: threat model, what it does not protect
  (anything bound or passed in; network exfiltration to allowed hosts;
  kernel exploits; no seccomp), stronger tools by need. `nested-agents.md`:
  opencode as the worked example (binding its Node.js folder, a per-run
  config in `/work/.config`, placeholder keys, `--format json` output read
  from outside), plus the same pattern for any CLI agent.
- [x] **Step 4: Full suite; `python3 scripts/build_skills_index.py --check`
  is not run on the branch (CI regenerates on main).**
- [x] **Step 5: Commit** `sandboxing: SKILL.md and references`.

### Task 4 (controller): agent trials

- [x] Rerun the sandboxed opencode docshelf trial (one documentation set,
  the eight models) with its harness switched to `sandbox.py`; same results
  shape as `docs/trials/2026-11-18-opencode-docshelf-sandboxed/`.
- [x] With/without-skill check (AGENTS.md rule 4): two Haiku agents, the
  prompt "Run this test harness so it can't see my environment variables or
  files outside its folder: <harness>", one with the skill installed, one
  without; record whether each used `sandbox.py` and the leak test.
- [x] Write the results to `docs/trials/2026-11-18-sandboxing-skill/README.md`;
  open the PR (`skill/sandboxing`, squash-merge when approved).
