# Console CLI quick reference (`@opencode/console`)

Connects Claude Code, Codex, Pi, DeepSeek Harness and Hermes Agent to an
OpenCode Console workspace: its models, MCP servers, skills and instructions,
with every tool call checked against the workspace's policies. OpenCode itself
connects on its own (`/connect`) and doesn't need it. Source: the package
README (npm `@opencode/console`, checked at 0.1.15); `npx @opencode/console
help` lists every command of the installed version.

## Install and set up

| Do | Command |
| --- | --- |
| Set up a harness (Node.js 22+) | `npx @opencode/console setup <harness>` |
| Without Node (Linux/macOS) | `curl -fsSL https://raw.githubusercontent.com/anomalyco/opencode-console-cli/production/install \| sh -s -- setup <harness>` |
| Without Node (Windows PowerShell) | `& ([scriptblock]::Create((irm https://raw.githubusercontent.com/anomalyco/opencode-console-cli/production/install.ps1))) setup <harness>` |
| Keep the harness's own sign-in and models | add `--keep-provider` (claude-code, codex, hermes) |
| Undo a setup, keep the sign-in | `setup <harness> --remove` |
| Pi, as a Pi package | `pi install npm:@opencode/console`, then `npx @opencode/console login` |

`<harness>`: `claude-code`, `codex`, `pi`, `deepseek-harness`, `hermes`.
Setup opens the browser to sign in and pick the workspace, then installs the
signed `opencode-console` binary that the agents run without Node. Installer
options before `setup`: `--channel beta|dev`, `--version <version>`. On Linux
the installer needs OpenSSL 3.

What setup writes:

| Harness | Writes | After setup |
| --- | --- | --- |
| Claude Code | Claude Code's user settings | - |
| Codex | `~/.codex/config.toml`, `hooks.json` (or under `CODEX_HOME`), approves the policy hooks | `--keep-provider` usage reporting needs Codex 0.164.0+ |
| DeepSeek Harness | plugin in `~/.dsh/cordis.patch.yml` (or `DSH_HOME`); workspace models replace your providers | restart running `dsh` |
| Hermes Agent (0.22.6+) | `~/.hermes/config.yaml` (or `HERMES_HOME`, `--profile <name>`), `plugins/opencode-console`, instructions in `SOUL.md` | `hermes gateway restart` |

`--keep-provider` leaves the harness's own sign-in, models and default
provider alone: setup still writes the files above, but only to add the
workspace's policies, MCP servers, skills and instructions. (The by-hand
steps in `references/harnesses-codex.md` and the other harness pages are the
opposite: they make Console the default provider.)

With `--keep-provider`, Claude Code and Codex report token counts and model
(never prompts or code) so the workspace counts the usage at $0; Hermes reports
nothing.

## Everyday commands

| Command | Does |
| --- | --- |
| `status` | Sign-in, workspace and config; whether `--keep-provider` reporting applies |
| `login` / `logout` | Sign in / out |
| `update` / `update --check` | Install / check for a newer build on this install's channel |
| `artifact share <dir> [--name N] [--ttl 12h\|7d\|2w] [--replace]` | Upload a folder with `index.md` or `index.html`, print its link (workspace members open and comment) |
| `artifact list` / `artifact delete <name>` | List artifacts / delete one you shared |
| `artifact pull <name> [dir] [--revision N] [--force]` | Download an artifact's files, SHA-256 checked |
| `help` | Every command |

Prefix each with `npx @opencode/console` (or run the installed
`opencode-console`). Artifact limits: 500 files, 100 MB, 25 MB per file,
dotfiles skipped; re-sharing a name updates the same link.

## Event watches (when the workspace turns them on)

Sessions in Claude Code, Codex, Pi and DeepSeek Harness get updates on the
Slack threads and GitHub PRs, issues, commits and Actions runs they work on,
plus events from the workspace's other MCP servers (MCP Events). The agent
gets `watch` (takes `minutes`, or a server, event and arguments) and `events`
(lists what each server offers). Idle sessions are woken; after 5 wakes in 10
minutes or 20 since your last prompt, updates wait for the next prompt. Codex
can't start a turn on its own; Hermes doesn't watch yet.

## Environment variables

| Variable | Use |
| --- | --- |
| `OPENCODE_API_KEY` | Use a personal or service account key instead of signing in (CI) |
| `OPENCODE_CONSOLE_AUTO_UPDATE=off` | Stop self-updates (manage the binary yourself, e.g. MDM) |

The binary updates itself (checked per session start, at most hourly
otherwise), verifies SHA-256 and signature, and rolls back a build whose hooks
crash three times. With `npx` or `pi install`, npm picks the version instead.
