# Plugins: local additions

Supplements `plugins.md`. Not from the opencode docs site: written for this
skill from the opencode source at `v2.2.5` and the installed
`@opencode/plugin@2.2.5`. Re-check after an opencode upgrade.

Code (https://github.com/anomalyco/opencode, tag `v2.2.5`): part resolution
`packages/plugin/src/host.ts` (`Host.resolve`); the server loader
`packages/core/src/plugin/module.ts` (`load`, `loadServer`); module import
`packages/util/src/runtime/import.{bun,node}.ts`; host-provided modules
`packages/plugin/src/runtime.ts`; Promise-plugin adapter
`packages/plugin/src/promise/adapter.ts` (`fromPromise`).

## Parts

#### Notes

- Server key order: `<name>/server`, then `<name>` (`.`). A package may use
  either; `./server` wins if both exist.
- Stale `exports` after `/reload` (observed on 2.2.6, not traced in the
  source): a running opencode can keep the previous `exports` map. A plugin
  whose old version had `".": "./src/index.ts"` and whose new one has only
  `./server` then still resolves the stale `.` and fails with `ENOENT` on the
  deleted file. Declaring both `.` and `./server` with the same entry avoids
  it; a fresh start (`Host.resolve` on 2.2.6) resolves `./server` alone fine.
- A part whose file is missing or not exported (`ENOENT`,
  `MODULE_NOT_FOUND`, `ERR_PACKAGE_PATH_NOT_EXPORTED`, ...) counts as absent;
  other resolution errors throw.
- Check what opencode will find, offline:
  `import { Host } from "@opencode/plugin/host"`, then
  `Host.resolve({ directory })` → `{ server, tui, rpc, gui }` (absent parts
  omitted) and `Host.packageID({ directory })`.

## Load

#### Notes

- Server entry check: the default export must be `{ id: string, setup:
  function }` (Promise) or `{ id, effect: function }` (Effect), checked by
  shape only. `Plugin.define` returns its argument; named exports are
  ignored. Otherwise: "Plugin must export a default definition with an id
  and an effect or setup function."
- A Promise plugin is wrapped into an Effect one (`fromPromise`): `setup`
  runs under `acquireRelease`, and the function it returns runs when the
  plugin's scope closes (unload, reload).
- A plugin loaded by path is not installed: opencode runs `npm` only for
  package plugins. Install a local plugin's dependencies yourself
  (`bun install`), or keep imports of them lazy so the plugin still loads
  without `node_modules`.
- `@opencode/plugin` and `effect` always come from opencode (a Bun plugin
  maps them); one loaded from the plugin's own `node_modules` throws
  ("plugins must use the host's \"effect\" and \"@opencode/plugin\"
  modules"). Pin `@opencode/plugin` to the running version for types only.
- Under Bun the entry is a plain `import()` (TypeScript runs as is); under
  Node it is imported through `vm.Script`, with a CommonJS `module.exports`
  merged into the namespace.
