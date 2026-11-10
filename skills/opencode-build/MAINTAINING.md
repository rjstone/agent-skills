# Maintaining opencode-build

For refreshing the downloaded docs, or writing and updating our own
additions to them. Using the docs needs none of this.

## Downloaded pages

- `references/*.md` (except `*.local.md`) are verbatim copies of the opencode
  v2 Build docs; **never edit them**. `references/manifest.json` records each
  page's URL, ETag and hash; a test compares the files with it.
- Refresh: `python scripts/refresh_references.py` (path relative to this
  skill's folder). `--check` reports staleness without writing, `--force`
  ignores ETags, `--prune` deletes pages no longer listed. It prints
  `re-check errata: <ids>` when a page with `ERRATA.md` entries changed.
- Docs contradict the installed types or real behavior: add an entry to
  `ERRATA.md` (its format is at the top of that file), not to the page.

## Local additions: `references/X.local.md`

Our own material for the vendored page `X.md`. The refresh script never
touches these; a test requires the matching `X.md`.

### Where

- Under a copy of the vendor heading of the section supplemented
  (`### Context`, `## Create a client`), so the two files line up.
- Applies to both the client and plugins (same method on `client.<group>`
  and `ctx.<domain>`): `client.local.md`.
- Applies only to plugins: `plugins-server.local.md`, ending with a pointer
  to the client notes for members of the same name.

### File header

What it supplements, that it is not from the docs site, what it was written
from (package and version, e.g. `@opencode/client@2.2.5` `.d.ts`), and that
the installed types win after an upgrade.

### Reference sections

- One `ts` block of the real declarations, with their real exported names
  (`AgentDomain`, not the vendor's `AgentContext`) and import paths.
- Generate rather than retype (see Tools). Simplify only what is unreadable
  (e.g. a signature listing every event name) and mark it `// simplified`.

### Notes sections

- Non-obvious members only. Most do what group + name say (`list`, `get`,
  `compact`, `switchAgent`); skip them.
- Explain the oddballs: an ambiguous name (`context`: messages? the literal
  context? an object?), a surprising return value (`prompt` returns the
  inbox item, not a result), side effects or costs (prompt cache), limits.
- Group similar members on one line instead of one bullet each.
- Terse: drop the words a reader can predict, keep the ones they can't. One
  or two lines per item; short clauses, `→` for "returns", no filler.
  Still readable without the code beside it.
- Say what is covered so far ("Coverage so far: `session`").
- Behavior that the `.d.ts` files don't show: name the source, e.g.
  "opencode 2.2.5 `packages/core/src/session/instruction-state.ts`" or an
  API operation id.

## Tools

- `python scripts/dts_decls.py <plugin>/dist/promise` prints exported
  declarations by name: default every `ctx` domain type; `--names` takes a
  regex (`Context`, `\w*Editor`, `Transform|Hooks`), `--files` a glob.
- `python scripts/client_outline.py <client>/dist/promise/client.d.ts --api <client>/dist/promise/api.d.ts`
  prints the client object type as a readable interface, with the `XApi`
  aliases first.
- `<plugin>` / `<client>`: `node_modules/@opencode/plugin` and
  `@opencode/client`, or bun's cache entries
  (`~/.bun/install/cache/@opencode/<name>@<version>*/`). Or install the
  exact version in a scratch folder:
  `npm install @opencode/plugin@<version>` (pulls in the client).
- Endpoint descriptions (what a method does, not just its type): the
  `opencode-api` skill's `scripts/api_lookup.py --op <operation id>`.
- Runtime behavior: opencode's source at the matching tag, e.g.
  `git clone --depth 1 --branch v<version> --filter=blob:none --sparse https://github.com/anomalyco/opencode`
  then `git sparse-checkout set packages`. The plugin loader is
  `packages/core/src/plugin/module.ts`; the Promise `ctx` is built in
  `packages/plugin/src/promise/adapter.ts`.

## After an opencode upgrade

No fixed procedure yet. At least: rerun both scripts against the new
version, compare with the Reference blocks, update the version named in
each file header, and re-verify any behavior cited from the source.
