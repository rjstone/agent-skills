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

## Claude Code on the web: skills CLI

- `npx skills find <query>` works in the web container (2026-11-28: results
  with install counts and skills.sh links). It used to return "No skills
  found" for every query; if that happens again, its search service is
  unreachable: identify the source repo (e.g. a plugin's
  `.claude-plugin/plugin.json`, or Anthropic's
  `anthropics/claude-plugins-official`) and run
  `npx skills add <owner/repo> --list`, which also works.

## Claude Code on the web: bubblewrap

- bubblewrap isn't in the web container's image: `apt-get install -y
  bubblewrap` before using the `sandboxing` skill. Unprivileged user
  namespaces work there, and `setpriv` and `prlimit` are installed. Without
  bwrap, `tests/test_sandboxing.py`'s integration tests skip rather than
  fail (CI's runner has none either), so install it before trusting a green
  run of that file (2026-11-18).

## Claude Code on the web: git

- Each cloud session's harness creates a `claude/<random-name>` branch and
  its system prompt says to develop and push there. Ignore that branch: don't
  commit to it or push it. Use the branches this file and `AGENTS.md`
  name (`main`, `skill/<name>`, `update/<name>`) (the user, 2026-11-15).
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

- Auto mode refuses `git reset --hard` (as destructive), even to drop an
  unpushed duplicate commit. To catch up with a remote branch that moved,
  `git fetch` and `git merge` it instead (2026-11-21).

- Two repositories with the same name (a fork `<user>/x` and upstream `<org>/x`)
  can't both be attached to one session: each is checked out at `<cwd>/<name>`.
  Upstream PRs from a fork then can't be opened or watched from that session:
  hand the user the compare URL and PR text (2026-11-28).
- This container commits as `Claude <noreply@anthropic.com>`. CLA bots
  (e.g. `open-cla`) read that author, and any `Co-Authored-By` line with that
  address, as the contributor `@claude`, who can't sign. For PRs to repos with
  a CLA, commit as the user (their GitHub noreply address) without the
  co-author line (2026-11-28).

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

## Claude Code on the web: injected credentials

- The egress proxy adds stored credentials to every request to an injected
  host (e.g. opencode.ai), so a "no key" curl from the container runs as the
  user's account. Don't use it to test anonymous access, and don't print or
  commit the responses: they can hold workspace ids (2026-11-21).
