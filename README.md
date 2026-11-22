# agent-skills

Agent skills for coding agents (Claude Code, opencode, Codex, Cursor and others).

## Install

With the [skills CLI](https://github.com/vercel-labs/skills) (Node 22.20+), from your project's root:

```bash
# Pick skills and coding agents interactively
npx skills add rjstone/agent-skills

# Every skill, for every coding agent the CLI supports, no prompts
npx skills add rjstone/agent-skills --all

# Only some skills (asks which agents to install for)
npx skills add rjstone/agent-skills --skill opencode-build opencode-api

# Only some skills, for more than one coding agent
npx skills add rjstone/agent-skills --skill opencode-build opencode-api -a opencode claude-code

# Into ./.agents/skills only (the shared folder that opencode, Codex, Cursor
# and many others read); there is no free-form path option, the agent picks
# the folder (claude-code -> ./.claude/skills)
npx skills add rjstone/agent-skills --skill opencode-api -a universal

# List the skills without installing
npx skills add rjstone/agent-skills --list
```

- Installs go into the project; add `-g` to install for your user account instead.
- With more than one agent, the CLI keeps one copy in `./.agents/skills` and
  symlinks the others to it. Add `--copy` for real copies instead, for example
  on Windows without Developer Mode.
- Update installed skills with `npx skills update`; `npx skills check` lists updates.

## Skills

- **capturing-tk-screenshots-headless** - run a Tkinter or other Tk GUI on a headless Linux machine or CI and take reliable screenshots of it.
- **concept-parable** - explain a concept as a short fable whose plot carries the concept's real mechanics, followed by a mapping back to it.
- **docshelf** - search and read DevDocs documentation and Dash/Zeal docsets offline, with your own notes, from the command line or as an MCP server.
- **docshelf-build** - build a trimmed docshelf docvol from a documentation site's Sphinx `objects.inv` or `llms.txt` page list, keeping reference pages in full and guides as stubs.
- **opencode-api** - call opencode's v2 server HTTP API correctly, using its OpenAPI spec cached in the skill.
- **opencode-build** - write and port opencode v2 plugins and SDK/client code from the current docs, not v1 habits.
- **opencode-cli** - use and script the opencode v2 command line and TUI from the current docs.
- **opencode-console** - set up and administer an OpenCode Console workspace, connect coding agents to it, and use its MCP server, CLI and inference endpoints.
- **pygameturbo** - help with and teach Pygame Turbo (the Pygame Zero fork) games, from its docs vendored in the skill (LGPL-3.0, see the skill's `references/README.md`).
- **provider-onboarding** - find how to call an LLM provider or model and get ready-to-paste config for it.
- **sandboxing** - run a nested agent CLI or test harness in a bubblewrap sandbox (Linux) that hides your environment variables, processes and files, with a leak self-test (not for hostile code).
- **skillspector-install** - install NVIDIA SkillSpector and its `skill-inspector` skill from one pinned release, to scan agent skills for security problems.
- **thonny-plugin** - write, install and debug Thonny IDE plugins: discovery, the plugin folder that actually loads, the UI-thread rule, a test ladder and a verified Thonny 5.0.1 API reference.
- **timestamp** - toggle time stamps with deltas at the start and/or end of each agent turn.

## License

MIT
