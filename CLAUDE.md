@AGENTS.md

# Claude Code notes

Only Claude-specific notes go here: Claude Code tools, subagents, settings,
hooks, slash commands and quirks of the Claude Code (web) container.
Everything shared lives in `AGENTS.md`, imported above. Agents other than
Claude treat this file as read-only. Keep this paragraph (and its twin in
`AGENTS.md`) when editing either file.

## Config that persists

On Claude Code on the web the container is rebuilt each session, so anything
only in `~/.claude` is lost. Persistent Claude config goes in this repo's
`.claude/` (settings, agents, commands). If something must sit at user scope,
link that one item into `~/.claude/` (re-create it each session, e.g. from a
SessionStart hook). Never link `~/.claude` itself into the repo or the other
way: it holds credentials and transcripts. Skills stay in `skills/` (no
symlinks, see AGENTS.md).

Claude Code keeps the working plan in `~/.claude/plans/`, which disappears
with a cloud container: archive it to `docs/plans/` before the session ends.

## Claude Code on the web: cloud environment

This repo's sessions run in the personal cloud environment named `Agents`,
which several other repos share (it holds their network secrets). The one
named `agent-skills` was created by accident: don't use it (the user,
2026-11-15). The network of `Agents` allows package registries, MCP servers
and a list of hosts that includes the ones the skills' scripts use; add a
host there (environment settings, or the environment tools) when a script
needs a new one. Its setup script:

- writes `~/.claude/CLAUDE.md` with one `PASS`, `FAIL` or `SKIP` line per
  step and a last "finished" line; details are in `~/install.log`. No step
  stops the script. Read those lines at session start: on a `FAIL`, or when
  "finished" is missing, tell the user and fix it by hand if the task needs
  it (the user, 2026-11-15).
- installs `python3-tk`. That gives Tk only to the system Python 3.12; the
  `python3` on `PATH` is 3.13 and apt has no Tk for it, so run Tk work
  (`capturing-tk-screenshots-headless`, `thonny-plugin`) with `python3.12`.
- links each `skills/<name>` into `~/.claude/skills/<name>`, only when this
  repo is cloned in the session, so its working copies load as skills.
  Copies synced from claude.ai may also show up under `anthropic-skills:`;
  the bare names are the repo versions.
- installs gpg, uv and the opencode v2 CLI (`npm install -g @opencode/cli`)
  for the other repos.

Pandoc, Xvfb and ImageMagick come with the base image. A setup script
change takes effect only in a container built fresh, so test it by running
its commands in the session, from the directory above the checkout. A
running session can't be moved off `Agents` to another environment (the
environment tools refuse); start a new session instead.

## Claude Code on the web: skills CLI

- `npx skills find <query>` returns "No skills found" for every query in the
  web container (even `react`): its search service isn't reachable there.
  To find a skill, identify the source repo (e.g. a plugin's
  `.claude-plugin/plugin.json`, or Anthropic's
  `anthropics/claude-plugins-official`) and run
  `npx skills add <owner/repo> --list`, which works.

## Claude Code on the web: git

- The session's git proxy refuses deleting remote branches (HTTP 403 on
  `git push origin --delete`), and the GitHub tools here have no delete. No
  need: GitHub deletes a PR's branch when it is merged (repo setting; the
  user, 2026-11-10). After a merge, delete only the local branch.
- The clone is shallow (`--depth 1`) and tracks only `main`. A branch you
  push later gets no `origin/<branch>` ref, even with `git push -u`
  ("upstream branch ... not stored as a remote-tracking branch"), so `git
  status` and the session's stop hook report it as unpushed with no remote
  branch although the push worked. Before the first push of a new branch:
  `git config --add remote.origin.fetch '+refs/heads/<branch>:refs/remotes/origin/<branch>'`,
  then `git push -u origin <branch>`. Already pushed: add the same line,
  `git fetch origin <branch>`, `git branch -u origin/<branch>`.

## Delegating to subagents

- Hand long, mechanical runs (batch jobs, long waits, log sweeps) to a cheap
  subagent (usually Haiku, only the tools it needs) that returns a short
  report.
- Two or more independent problems with no shared state: use
  `dispatching-parallel-agents` (obra/superpowers), one subagent per problem
  in the same response, then verify everything yourself.
- Larger plans with several tasks: use `subagent-driven-development`.
- When the opencode subagent tools are available, read `delegate-to-opencode`
  before delegating; it suits mechanical, well-specified jobs. Keep
  judgment-heavy work and anything touching secrets on native subagents.
- Parallel code changes: give each agent its own worktree
  (`using-git-worktrees`). Read-only or non-overlapping work doesn't need it.
- On the web, when the egress proxy injects a host's real credentials, set
  the key variables a client needs to a placeholder (e.g. `proxy-injected`);
  never ask for or write in a real value.
