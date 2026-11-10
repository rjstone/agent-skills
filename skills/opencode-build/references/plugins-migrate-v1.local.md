# Migrate plugins from V1: local additions

Supplements `plugins-migrate-v1.md`. Not from the opencode docs site:
observed by loading one dual-export plugin in `opencode-ai@1.18.29` (V1) and
`@opencode/cli@2.2.6` (V2), checked with `tsc` against `@opencode/plugin@2.2.6`.
Re-check after an upgrade on either side.

Code (https://github.com/anomalyco/opencode): the V2 loader is
`packages/core/src/plugin/module.ts` at tag `v2.2.6` (shape check: see
`plugins.local.md` "Load"). V1 source not consulted.

## Support V1 and V2 from one package

#### Notes

- Works as documented on both: one default export
  `{ ...Plugin.define({ id, setup }), server }`. V2 ran `setup()`; V1 ran
  `server()`. The spread keeps the V2 part type-checked by `Plugin.define`;
  `server` needs no V1 package if typed with local stand-in types.
- Getting each CLI: V1 is the npm package `opencode-ai` (its `latest` stays
  1.x); V2 is `@opencode/cli`. Install the V2 one with `npm install`: bun
  blocks its postinstall, which fetches the binary ("postinstall script was
  not run").
- V1 config key is `"plugin"` (singular). A plugin folder loads by
  `"plugin": ["file://<absolute dir>"]`; it resolved the entry through the
  folder's `package.json` `exports` (`"."` and `"./server"` both pointed at it).
- Sharing code: give each V2 domain file a plain loader (read files, resolve
  paths) and call it from both the V2 transform and the V1 hook. Translate
  nothing between hook APIs.
- V1 `config` hook, mutating the loaded config, did the V2 agent and MCP
  transforms' job:
  - `config.agent[<id>] = { description, mode, prompt, color }` (`prompt` =
    system prompt) → `opencode debug agent <id>` showed every field.
  - `config.mcp[<name>] = { type: "local", command: [...] }` →
    `opencode mcp list` showed it connected.
- V1 tools need the old `tool()` helper and zod schemas from
  `@opencode-ai/plugin` 1.x; there is no plain-JSON-Schema form.
- Inspecting without a model: V1 `opencode debug config | agent <name> |
  skill`, `opencode mcp list`. V2 `debug` has only `agents`, `config`,
  `paths`, `heap-dump`; use the HTTP API, or `scripts/plugin_probe.py`.
- Isolate either CLI from your real setup with `XDG_CONFIG_HOME`,
  `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME` pointing at a temp
  folder.
