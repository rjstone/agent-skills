---
name: opencode-build
description: Use when writing, changing or reviewing an opencode plugin (server, TUI, GUI or RPC part, Plugin.define, hooks, custom tools, package.json exports, loading from opencode.json), using @opencode/plugin, @opencode/sdk or @opencode/client, porting a v1 plugin (@opencode-ai/plugin), or unsure whether an opencode API is v1 or v2.
compatibility: Refreshing references/ (scripts/refresh_references.py) needs network access to opencode.ai; the cached docs work offline.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.1"
---

# opencode Build docs (v2)

## Overview

opencode v2 replaced the v1 plugin API, and what you remember is probably v1
(v1 -> v2): `@opencode-ai/plugin` -> `@opencode/plugin`; exported async
function returning hooks -> `Plugin.define({ id, setup(ctx) })`; `tool()` ->
`ctx.tool.transform`; config `"plugin"` -> `"plugins"`; `.opencode/plugin/` ->
`.opencode/plugins/`. **Do not write opencode plugin code from memory.** Look
it up first, in this order:

1. **Installed types** (the authority for the version the project uses):
   `dist/promise/<area>.d.ts` (`tool.d.ts`, `plugin.d.ts`, `command.d.ts`, ...)
   in `node_modules/@opencode/plugin/`, or in bun's cache
   `~/.bun/install/cache/@opencode/plugin@<version>*/` (Windows:
   `%USERPROFILE%\.bun\install\cache\...`).
2. **`ERRATA.md`** beside this file: known mistakes in the docs below.
3. **`references/`**: the v2 Build docs cached as Markdown.

When they disagree, the higher source wins.

## Which reference

| Task | Read |
| --- | --- |
| Parts (server/TUI/GUI/RPC), `package.json` `exports`, loading, `plugins` config, publish | `references/plugins.md` |
| Server part: `setup(ctx)`, tools, hooks, transforms, agents, commands, MCP | `references/plugins-server.md` |
| TUI part: commands, keymaps, slash commands, toasts, dialogs, routes, slots | `references/plugins-cli.md` |
| GUI part (Desktop panels, settings, main process) | `references/plugins-gui.md` |
| Typed methods/events between parts and clients | `references/plugins-rpc.md` |
| Porting v1 code, or supporting v1 and v2 from one package | `references/plugins-migrate-v1.md` |
| Effect API versions | `references/plugins-effect.md`, `references/plugins-effect-rpc.md` |
| Driving a running server from code | `references/client.md`, `references/client-effect.md` |
| Embedding opencode in your app | `references/sdk.md`, `references/sdk-effect.md`, `references/sdk-cloudflare.md` |
| What the Build section covers | `references/intro.md` |

`plugins-server.md` (~1800 lines) and `plugins-gui.md` (~3700 lines) are
large: list their headings first (`grep -n '^##' <file>`), then read only the
section you need.

## Keeping it current

- References are verbatim copies; **never edit them**. Refresh with
  `python scripts/refresh_references.py` (path relative to this skill's folder)
  (`--check` reports staleness without writing; `--help` for the rest).
- No cached page for it? The live Markdown of any docs page is its URL with
  the trailing `/` replaced by `.md`; the index is `https://opencode.ai/docs/llms.txt`.
- Cite the page URL without `.md` (it is in `references/manifest.json`).
- Found a doc mistake (the docs contradict the installed types or real
  behavior)? Add an entry to `ERRATA.md` with your evidence.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| v1 imports or exported async function | `import { Plugin } from "@opencode/plugin"`; `export default Plugin.define({ id, setup(ctx) { ... } })` |
| Guessing an `exports` key | `plugins.md` "Parts" lists them (`.`, `./tui`, `./gui-experimental`, `./rpc`) |
| `editor.namespace()` but no `options.namespace` on the tool (id stays un-prefixed; Code Mode shows `tools.<name>()`) | Pass `options: { namespace }` on every `add`; see `ERRATA.md` E01 |
| Editing only `event.result.content` in `execute.after` (Code Mode returns `output`; MCP tools always set it) | Edit `output` too; see `ERRATA.md` E03 |
| Reading a whole 2000-line reference | Search headings, read one section |
| Trusting a reference over the installed types | Types win; record the conflict in `ERRATA.md` |
