---
name: opencode-cli
description: Use when running or scripting the opencode command line or TUI - opencode run in CI, sessions (export, import, continue), models and auth, mcp/plugin/service/serve commands, the shared background server vs --standalone or --server, cli.json settings, keybinds, themes, the web UI, ACP editor integration - or unsure whether an opencode command or flag is v1 or v2.
compatibility: Refreshing references/ (scripts/refresh_references.py) needs network access to opencode.ai; the cached docs work offline.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# opencode CLI docs (v2)

## Overview

opencode v2 changed the CLI, and what you remember is probably v1: v2 runs one
**shared background server** per account (`--standalone` for a private one,
`--server <url>` to pick one), sessions live under `opencode session ...`, and
CLI/TUI settings are in `cli.json` (not `opencode.json`). **Do not give opencode
commands or flags from memory.** Look them up first:

1. `opencode <command> --help` on the installed version, when you can run it.
2. **`ERRATA.md`** beside this file: known mistakes in the docs below.
3. **`references/`**: the v2 CLI docs cached as Markdown.

When they disagree, the higher source wins.

## Which reference

| Task | Read |
| --- | --- |
| Starting opencode, automation, shared background service, `debug paths`, uninstall | `references/intro.md` |
| A command or flag: `run`, `session`, `auth`, `models`, `mcp`, `plugin`, `stats`, `serve`, `pair`, `service`, `api`, `acp`, `debug`, `upgrade` | `references/commands.md` |
| TUI basics: context, shell, side questions, models, history, editor | `references/tui.md` |
| `cli.json`: appearance, input, sessions, diffs, alerts, terminal, plugins | `references/config.md` |
| A keybind, or rebinding one | `references/keybinds.md` |
| Themes: choose, system colors, create one, use one in a plugin | `references/theme.md` |
| Signing in to providers, credential storage, env vars | `references/providers.md` |
| Web UI access, ports, password, standalone | `references/web.md` |
| Editor integration over ACP | `references/acp.md` |
| Loading TUI-only plugins | `references/plugins.md` |

`commands.md`, `config.md`, `keybinds.md` and `acp.md` are 380-630 lines:
list their headings first (`grep -n '^##' <file>`), then read only the section
you need.

## Quick facts (checked against the references)

- CI: `opencode run --standalone --model <provider/model> "<prompt>"` with the
  provider key as a secret env var (`commands.md`, top).
- Export a session redacted: `opencode session export <id> --sanitize`.
- Stop or start the shared server: `opencode service stop|start`.

## Keeping it current

- References are verbatim copies; **never edit them**. Refresh with
  `python scripts/refresh_references.py` (path relative to this skill's folder;
  `--check` reports staleness without writing; `--help` for the rest).
- No cached page for it? The live Markdown of any docs page is its URL with
  the trailing `/` replaced by `.md`; the index is `https://opencode.ai/docs/llms.txt`.
- Cite the page URL without `.md` (it is in `references/manifest.json`).
- Found a doc mistake (the docs contradict `--help` or real behavior)? Add an
  entry to `ERRATA.md` with your evidence.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| `opencode export <id>` (v1) | `opencode session export <id>` |
| Assuming each TUI or `run` starts its own server | One shared background server; `--standalone` for a private one in CI |
| Theme/keybinds in `opencode.json` | `cli.json` (`config.md`) |
| Adding a TUI-only package to `opencode.json` | It goes in `cli.json`; a plugin in `opencode.json` loads its TUI part automatically (`plugins.md`) |
| Reading a whole 600-line reference | Search headings, read one section |
