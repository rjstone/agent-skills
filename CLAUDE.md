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

## Claude Code on the web: git

- The session's git proxy refuses deleting remote branches (HTTP 403 on
  `git push origin --delete`), and the GitHub tools here have no delete. After
  a squash-merge, delete the local branch and ask the user to delete the
  remote one (AGENTS.md "Adding a skill", step 6).

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
