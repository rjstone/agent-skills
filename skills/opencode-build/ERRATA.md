# Errata: mistakes in the cached opencode Build docs

`references/` is overwritten by `scripts/refresh_references.py`; corrections
live here instead. When a refresh changes a page with entries, the script
prints `re-check errata: <ids>`: re-verify each, then update or delete it.

Entry format (the script reads the `## E..` heading and the `- Page:` line):

```
## E01: <short title>
- Page: `plugins-server.md` (section "<heading>")
- Docs say: <claim>
- Actually: <what is true>
- Evidence: <type file + symbol, test, or commit>
- Checked: <YYYY-MM-DD> against @opencode/plugin <version>
```

## E01: `editor.namespace()` alone does not namespace a tool; id vs Code Mode path
- Page: `plugins-server.md` (section "Tools", the `ctx.tool.transform` example)
- Docs say: the example calls `editor.namespace({ name: "acme", ... })` and adds a
  tool with `options: { namespace: "acme", codemode: true }`, then: "Use `update`
  and `remove` with the effective tool name, including its namespace
  (`acme_greeting` above)." It never says which of the two calls makes the
  prefix, or how the model then sees the tool.
- Actually:
  - Only `options.namespace` on each `editor.add(...)` puts a tool in a
    namespace. Effective id = `<namespace, "." -> "_">_<name>`; without
    `options.namespace` the id is just the name. `editor.namespace()` only
    records a namespace's description (shown in the Code Mode catalog) and
    prefixes nothing. Declaring the namespace and omitting the option gives
    an un-prefixed id: `enter`, not `tutor_enter`.
  - `codemode` is on unless set to `false`. A Code Mode tool is called by the
    model inside Code Mode as `tools.<namespace>.<name>(...)` (dots), or
    `tools.<name>(...)` with no namespace; `pinned: true` lists it up front in
    that catalog. So one tool has two names: id `tutor_enter`
    (`list`/`get`/`update`/`remove`) and Code Mode path `tools.tutor.enter()`.
  - For a plain, direct tool call set `codemode: false`, as opencode's own
    direct tools (bash, patch, question) do. While Code Mode (the `execute`
    tool) is allowed, the model's direct tool list holds only
    `codemode: false` tools; the rest are reachable only through Code Mode.
    If `execute` is denied by permissions, every tool is direct.
  - `ctx.tool.hook("execute.before" | "execute.after")` also fire for calls
    made from Code Mode, and `event.tool` is always the effective id
    (`tutor_enter`, `thonny-agent_eval`), never the bare name or the dotted
    Code Mode path. MCP tools are namespaced by server name
    (`<server>_<tool>`, unsupported characters -> `_`).
- Evidence: opencode v2.2.5 server (`opencode serve`) with a probe plugin;
  `ctx.tool.list()` returned:
  `namespace()` + no option -> id `enter_declared_only`;
  `options: { namespace: "tutor" }` -> `tutor_enter_with_option`;
  `options: { namespace: "tutor", codemode: false }` -> `tutor_enter_direct`.
  The server's bundled source names ids with
  `options?.namespace === undefined ? name : ns.replaceAll(".", "_") + "_" + name`
  and Code Mode paths with `ns + "." + name`, and tells models to call tools as
  `tools.<ns>.<tool>(...)`. Seen in practice: a tool added without the option
  showed up as `tools.enter()`. The direct-list filter and the hook names
  come from the server's tool snapshot and `Tool.execute` code.
- Checked: 2026-11-08 against @opencode/plugin 2.2.5 (opencode v2.2.5)

## E02: session hook reference uses made-up type names (`SessionContextHook` vs `SessionHookContext`)
- Page: `plugins-server.md` (section "Sessions", "Session reference")
- Docs say: `SessionHooks` maps `context` to `SessionContextHook` (also used for
  `compaction` and `generate`), and a separate `interface SessionHookContext`
  declares `hook(name, callback, options)`. Neither name exists in the
  package; the two near-identical names stand for unrelated things.
- Actually (the real `@opencode/plugin/promise/session` types):
  - The hook events are `SessionContext` (`context`), `SessionCompaction`
    (`compaction`; `SessionContext` + `result?`), `SessionGenerate`
    (`generate`), `SessionTitle` (`title`), built on `SessionRequest`. The
    docs' other `...Hook` names are the real names without `Hook`
    (`SessionModelRequest`, `SessionHttpRequest`, `SessionWebSocketSend`,
    `SessionRetry`, ...).
  - "`SessionHookContext`" is the registration function itself:
    `ctx.session.hook`, typed `ModelHooks<SessionHooks>` (part of
    `SessionDomain`), not an event.
  - `SessionHooks` also has `"experimental.idle"` (event `SessionIdle`), missing
    from the docs' list.
  - `options` (`{ providerID?: string }`, `ModelHookOptions`) is allowed only for
    hooks whose event has a `model` field: not for `prompt` or
    `experimental.idle` (the docs say only `prompt`).
  - Import the real names when typing a hook callback; usually
    `ctx.session.hook("context", (event) => ...)` infers them.
- Evidence: `@opencode/plugin` 2.2.5 `dist/promise/session.d.ts`
  (`SessionHooks`, `SessionDomain`) and `dist/promise/registration.d.ts`
  (`ModelHooks`, `ModelHookOptions`); no `SessionContextHook` or
  `SessionHookContext` anywhere in the package.
- Checked: 2026-11-08 against @opencode/plugin 2.2.5

## E03: tool results - `content` vs `output`, and what the model gets in Code Mode
- Page: `plugins-server.md` (sections "Tools" and the `execute.after` tool hook)
- Docs say: tool examples return only `{ content }`, and the `execute.after`
  example edits `event.result`, but nothing says how `content` and `output`
  differ or which one reaches the model.
- Actually:
  - Direct (non-Code-Mode) call: the model sees `content` when present;
    `output` (JSON-stringified) only when there is no content.
  - Code Mode call: the tool function returns `output` to the model's code
    whenever it is defined; only otherwise the text of `content`.
  - MCP tools always set `output` (the MCP structured content; else the text,
    parsed as JSON when it looks like JSON; else `null`) and keep the MCP
    content as `content`. MCP tools default to Code Mode.
  - So text appended to `event.result.content` in `execute.after` reaches the
    model for direct calls but is invisible in Code Mode when `output` is set,
    which for MCP tools is always. Edit `output` too (or instead), or make
    the tool `codemode: false`.
- Evidence: opencode v2.2.5 server bundle: the Code Mode result function
  returns `output` when defined, else the joined text content; the direct path
  sends `content`, falling back to stringified `output`; the MCP bridge
  returns `{ output: structured ?? text ?? null, content }`.
- Checked: 2026-11-08 against opencode v2.2.5 (@opencode/plugin 2.2.5)
