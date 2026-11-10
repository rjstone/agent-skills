# Server plugins: local additions

Supplements `plugins-server.md`. Not from the opencode docs site: written for
this skill from the installed type declarations of `@opencode/plugin@2.2.5`
(`dist/promise/*.d.ts`) and `@opencode/client@2.2.5`. Re-check against the
installed `.d.ts` files after an opencode upgrade; they win on any conflict.

The vendor Reference sections name the domains `AgentContext` and so on and
flatten them. The real exported names are `AgentDomain` and so on, importable
from `@opencode/plugin/promise/<area>` (`agent`, `session`, `tool`, ...). The
main entry `@opencode/plugin` re-exports `Plugin.Context` but not the domain
or editor types.

### Context

#### Reference

`setup(ctx)` receives `Context`. Nothing annotates `ctx`: `Plugin.define`
takes a `Plugin`, so TypeScript infers it. `define` returns its argument
unchanged and exists only for that inference. The loader accepts any default
export with a string `id` and a function `setup` (or `effect`).

```ts
// @opencode/plugin/promise/plugin
interface Plugin {
  readonly id: string
  readonly setup: (context: Context) => Promise<Cleanup | void> | Cleanup | void
}
type Cleanup = () => Promise<void> | void   // runs when the plugin unloads or reloads
declare function define(plugin: Plugin): Plugin

interface Context {
  readonly app: App
  readonly location: Location.Info          // @opencode/schema/location
  readonly options: PluginOptions           // the plugin entry's `options` in opencode.json
  readonly agent: AgentDomain
  readonly aisdk: AISDKDomain
  readonly command: CommandDomain
  readonly credential: Pick<CredentialApi, "activate">
  readonly event: EventDomain
  readonly experimental: {
    readonly terminal: Pick<OpenCodeClient["experimental"]["persistentPty"], "read">
    /** Stateless generation with a model and a prompt: no session, history or tools. */
    readonly generate: ExperimentalGenerateApi
    readonly artifact: ExperimentalArtifactDomain
  }
  readonly integration: IntegrationDomain
  readonly mcp: MCPDomain
  readonly model: ModelDomain
  /** @deprecated Use `experimental.generate.text`. */
  readonly generate: Pick<ExperimentalGenerateApi, "text">
  readonly permission: PermissionDomain
  readonly plugin: Pick<PluginApi, "list">
  readonly provider: ProviderDomain
  readonly reference: ReferenceDomain
  readonly rpc: RpcDomain
  readonly session: SessionDomain
  readonly shell: ShellDomain
  readonly skill: SkillDomain
  readonly storage: StorageDomain
  readonly tool: ToolDomain
  readonly vcs: VcsDomain
  readonly websearch: WebSearchDomain
  readonly worktree: WorktreeDomain
}

// @opencode/plugin dist/app.d.ts, dist/options.d.ts
interface App {
  readonly name: string
  readonly version: string
  readonly channel: string
}
type PluginOptions = Readonly<Record<string, any>>
```

### Domain types

#### Reference

`Context` does not extend the client type (`OpenCodeClient`, see
`client.local.md`). Most domains are derived from one slice of it instead:
`XApi` is an indexed access type on the client, so a domain's read and action
methods have exactly the client's types and follow it when it changes. Each
domain then adds plugin-only members (`transform`, `hook`, `reload`, ...).

```ts
// @opencode/client/promise/api
type Client = OpenCodeClient
type AgentApi = Client["agent"]
type CommandApi = Client["command"]
type CredentialApi = Client["credential"]
type ExperimentalGenerateApi = Client["experimental"]["generate"]
type ExperimentalSessionApi = Client["experimental"]["session"]
type IntegrationApi = Client["integration"]
type McpApi = Client["mcp"]
type ModelApi = Client["model"]
type PluginApi = Client["plugin"]
type PermissionApi = Client["permission"]
type ProviderApi = Client["provider"]
type ReferenceApi = Client["reference"]
type SessionApi = Client["session"]
type SkillApi = Client["skill"]
type VcsApi = Client["vcs"]
type WebSearchApi = Client["websearch"]
type WorktreeApi = Client["worktree"]

// @opencode/plugin/promise/registration: shared by the domains below
interface Registration {
  readonly dispose: () => Promise<void>
}
type Transform<Input> = (callback: (input: Input) => void) => Promise<Registration>
type Hooks<Spec> = <Name extends keyof Spec>(
  name: Name,
  callback: (input: Spec[Name]) => Promise<void> | void,
) => Promise<Registration>
// Like Hooks; events that carry a model also take { providerID? } to scope the hook.
type ModelHooks<Spec> = <Name extends keyof Spec>(
  name: Name,
  callback: (input: Spec[Name]) => Promise<void> | void,
  options?: Spec[Name] extends { readonly model: unknown } ? ModelHookOptions : never,
) => Promise<Registration>
interface ModelHookOptions {
  /** Limits the hook to one provider. Unscoped hooks apply to every provider. */
  readonly providerID?: string
}

// Whole client slice + plugin members
interface AgentDomain extends AgentApi {
  readonly transform: Transform<AgentEditor>
  readonly reload: () => Promise<void>
}
interface ModelDomain extends ModelApi {
  readonly transform: Transform<ModelEditor>
  readonly reload: () => Promise<void>
}
interface ProviderDomain extends ProviderApi {
  readonly transform: Transform<ProviderEditor>
  readonly reload: () => Promise<void>
}
interface ReferenceDomain extends ReferenceApi {
  readonly transform: Transform<ReferenceEditor>
  readonly reload: () => Promise<void>
}
interface SkillDomain extends SkillApi {
  readonly transform: Transform<SkillEditor>
  readonly reload: () => Promise<void>
}
interface WebSearchDomain extends WebSearchApi {
  readonly transform: Transform<WebSearchEditor>
  readonly reload: () => Promise<void>
}
interface WorktreeDomain extends WorktreeApi {
  readonly transform: Transform<WorktreeEditor>
  readonly reload: () => Promise<void>
}

// Part of a client slice (Pick / Omit) + plugin members
interface CommandDomain extends Pick<CommandApi, "list"> {
  readonly transform: Transform<CommandEditor>
  readonly reload: () => Promise<void>
}
interface MCPDomain extends Pick<McpApi, "list"> {
  readonly transform: Transform<MCPEditor>
  readonly reload: () => Promise<void>
}
interface IntegrationDomain extends Omit<IntegrationApi, "wellknown"> {
  readonly transform: Transform<IntegrationEditor>
  readonly reload: () => Promise<void>
  readonly connection: {
    readonly active: (integrationID: string) => Promise<ConnectionInfo | undefined>
    readonly resolve: (connection: ConnectionInfo) => Promise<Credential.Value | undefined>
    /** Reports a problem with a connection, such as a required sign-in; `undefined` clears it. */
    readonly status: (input: {
      readonly integrationID: string
      readonly connection: ConnectionInfo
      readonly status: Connection.Status | undefined
    }) => Promise<void>
  }
}
interface VcsDomain extends Omit<VcsApi, "init"> {
  readonly transform: Transform<VcsEditor>
  readonly reload: () => Promise<void>
}
type PermissionDomain = Pick<PermissionApi, "list" | "get" | "reply"> & {
  readonly hook: Hooks<PermissionHooks>
  /**
   * Evaluates the session's permission rules and, when approval is required, prompts the user and
   * waits for the reply. Resolves when allowed. A deny rule or a rejection with feedback rejects with
   * a `Tool.Error` carrying the reason. A plain rejection rejects with an error that ends the current
   * step; rethrow it rather than returning it as tool output.
   */
  readonly assert: (input: typeof AssertInput.Encoded) => Promise<void>
}
type SessionDomain =
  Pick<SessionApi,
    | "list" | "create" | "get" | "remove" | "switchAgent" | "switchModel" | "prompt"
    | "generate" | "command" | "compact" | "synthetic" | "interrupt" | "update" | "move" | "context">
  & Pick<ExperimentalSessionApi, "wait" | "instructions">
  & { readonly hook: ModelHooks<SessionHooks> }

// No client counterpart: plugin-only
interface ToolDomain {
  readonly transform: Transform<ToolEditor>
  readonly reload: () => Promise<void>
  /** Currently registered tools, after every transform, keyed by effective name. */
  readonly list: () => Promise<readonly (Info & { readonly id: string })[]>
  readonly hook: Hooks<ToolHooks>
}
interface ShellDomain {
  readonly hook: Hooks<ShellHooks>
}
interface StorageDomain {
  readonly get: (key: string) => Promise<Schema.Json | undefined>
  readonly set: (key: string, value: Schema.Json) => Promise<void>
  readonly remove: (key: string) => Promise<void>
  readonly scan: (options: StorageScanOptions) => Promise<StorageScanResult>
}
interface EventDomain {
  readonly subscribe: <Type extends EventType = EventType>(
    options?: SubscribeOptions<Type>,
  ) => AsyncIterable<SelectedEvent<OpenCodeEvent, Type>>
}
interface AISDKDomain {
  readonly hook: ModelHooks<AISDKHooks>
}
interface ExperimentalArtifactDomain {
  readonly transform: Transform<ArtifactEditor>
  readonly reload: () => Promise<void>
}

// RPC: the client's typed RPC caller, minus per-call location/headers, plus handler registration
interface RpcDomain extends RpcApi<
  Pick<RpcCallOptions, "signal"> & { readonly location?: never; readonly headers?: never }
> {
  readonly register: <const D extends Rpc.PortableDefinition>(
    definition: D,
    handlers: RpcHandlers<NoInfer<D>>,
  ) => Promise<RpcRegistration<D>>
}
```

Name a precise type for one part of the context as `Plugin.Context["session"]`
(or `SessionDomain` from `@opencode/plugin/promise/session`), not as the
client's `SessionApi`: the `Pick` drops members, so `ctx.session` is not
assignable to `OpenCodeClient["session"]`.

### Domain notes

Plugin-only members; non-obvious ones only.

- `transform(cb)`: `cb` is replayed onto a fresh value on every registry
  change (any registration, removal or `reload()`), so keep it sync, cheap
  and repeatable: do file reads etc. before registering. Returns a
  `Registration`; `dispose()` drops it.
- `hook(name, cb)`: runtime interception; returns a `Registration`.
  `ModelHooks` take `{ providerID }` to scope hooks whose event has a model.
- `session.hook("prompt")`: runs once at inbox admission, before attachment
  and skill resolution. Edits to `prompt` (text, files, skills),
  `metadata` and `delivery` become the stored input. Not run for synthetic,
  shell, compaction or move items. Not exactly-once: keep it retry-safe.
- `ctx.session` lacks these client members: `fork`, `revert.*`, `diff`,
  `inbox.*`, `message.get`, `form.*`, `shell`, `background`, `active`,
  `environment`, `view`.
- `storage`: per-plugin JSON key-value store that outlives sessions.
- `tool.list()`: registered tools after every transform, keyed by effective
  name (namespaced ids included).
- `permission.assert(input)`: runs the session's permission rules and, if
  needed, asks the user; resolves when allowed. Rethrow its rejection rather
  than returning it as tool output.

Members with the same name as a client method (`session.context`,
`session.wait`, `session.instructions`, inbox `delivery`, ...) are covered
in the Notes of `client.local.md`.
