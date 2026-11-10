# Client: local additions

Supplements `client.md`. Not from the opencode docs site: written for this
skill from the installed type declarations of `@opencode/client@2.2.5`
(`dist/promise/client.d.ts`, `api.d.ts`, `index.d.ts`). Re-check against the
installed `.d.ts` files after an opencode upgrade; they win on any conflict.

Code (https://github.com/anomalyco/opencode, tag `v2.2.5`): `@opencode/client` is `packages/client/`:
`make()` in `src/promise/client.ts`, the `XApi` aliases in
`src/promise/api.ts`, `Input`/`Output` types in
`src/promise/generated/types.ts`. Server side of a group: usually
`packages/server/src/handlers/<group>.ts`, which calls
`packages/core/src/<group>.ts` or `packages/core/src/<group>/`.

## Create a client

### Reference

`OpenCode.make(options)` returns a plain object of method groups. Its type has
no declared name in the package; `index.d.ts` names it
`OpenCodeClient = ReturnType<typeof OpenCode.make>`. Each group is one
`ClientApi` group of the server's HTTP API, and every method takes an optional
`requestOptions` last.

The plugin context's domains are derived from these groups (see the
"Domain types" Reference in `plugins-server.local.md`), so the
`Input`/`Output` types below are the ones `ctx.<domain>` methods use.

```ts
// @opencode/client (also @opencode/client/promise): packages/client/src/promise/client.ts
declare namespace OpenCode {
  function make(options: ClientOptions): OpenCodeClient
}
type OpenCodeClient = ReturnType<typeof OpenCode.make>

// @opencode/client/promise/api (packages/client/src/promise/api.ts): one alias per group, used by @opencode/plugin
type AgentApi = OpenCodeClient["agent"]
type CommandApi = OpenCodeClient["command"]
type ConfigApi = OpenCodeClient["config"]
type CredentialApi = OpenCodeClient["credential"]
type EventApi = OpenCodeClient["event"]
/** @deprecated Use `ExperimentalGenerateApi`. */
type GenerateApi = OpenCodeClient["generate"]
type ExperimentalGenerateApi = OpenCodeClient["experimental"]["generate"]
type ExperimentalSessionApi = OpenCodeClient["experimental"]["session"]
type IntegrationApi = OpenCodeClient["integration"]
type McpApi = OpenCodeClient["mcp"]
type ModelApi = OpenCodeClient["model"]
type PluginApi = OpenCodeClient["plugin"]
type PermissionApi = OpenCodeClient["permission"]
type ProviderApi = OpenCodeClient["provider"]
type ReferenceApi = OpenCodeClient["reference"]
type WebSearchApi = OpenCodeClient["websearch"]
type SessionApi = OpenCodeClient["session"]
type SkillApi = OpenCodeClient["skill"]
type VcsApi = OpenCodeClient["vcs"]
type WorktreeApi = OpenCodeClient["worktree"]
// The main entry re-exports only some aliases (AgentApi, CommandApi, ConfigApi, EventApi,
// IntegrationApi, ModelApi, PluginApi, ProviderApi, ReferenceApi, RpcApi, WebSearchApi,
// SessionApi, SkillApi); import the others from "@opencode/client/promise/api".

// Input/Output types are exported from @opencode/client (packages/client/src/promise/generated/types.ts).
interface OpenCodeClient {
    server: {
        info(requestOptions?: RequestOptions): Promise<ServerInfo>
        pair(requestOptions?: RequestOptions): Promise<PairingCode>
        connect(input: ServerConnectInput, requestOptions?: RequestOptions): Promise<PairingSession>
    }
    location: {
        get(input?: LocationGetInput, requestOptions?: RequestOptions): Promise<LocationPublicInfo>
        reload(requestOptions?: RequestOptions): Promise<void>
    }
    agent: {
        list(input?: AgentListInput, requestOptions?: RequestOptions): Promise<AgentListOutput>
        get(input: AgentGetInput, requestOptions?: RequestOptions): Promise<AgentGetOutput>
    }
    plugin: {
        list(input?: PluginListInput, requestOptions?: RequestOptions): Promise<PluginListOutput>
        gui(input: PluginGuiInput, requestOptions?: RequestOptions): Promise<PluginGuiOutput>
        check(input?: PluginCheckInput, requestOptions?: RequestOptions): Promise<PluginCheckOutput>
        update(input: PluginUpdateInput, requestOptions?: RequestOptions): Promise<void>
    }
    experimental: {
        session: {
            stats(input?: ExperimentalSessionStatsInput, requestOptions?: RequestOptions): Promise<SessionStatsInfo>
            import(input: ExperimentalSessionImportInput, requestOptions?: RequestOptions): Promise<SessionInfo>
            export(input: ExperimentalSessionExportInput, requestOptions?: RequestOptions): Promise<SessionTransferData>
            skill(input: ExperimentalSessionSkillInput, requestOptions?: RequestOptions): Promise<void>
            wait(input: ExperimentalSessionWaitInput, requestOptions?: RequestOptions): Promise<void>
            instructions: {
                entry: {
                    list(input: ExperimentalSessionInstructionsEntryListInput, requestOptions?: RequestOptions): Promise<InstructionEntryInfo[]>
                    put(input: ExperimentalSessionInstructionsEntryPutInput, requestOptions?: RequestOptions): Promise<void>
                    remove(input: ExperimentalSessionInstructionsEntryRemoveInput, requestOptions?: RequestOptions): Promise<void>
                }
            }
            log(input: ExperimentalSessionLogInput, requestOptions?: RequestOptions): AsyncIterable<ExperimentalSessionLogOutput>
        }
        generate: {
            text(input: ExperimentalGenerateTextInput, requestOptions?: RequestOptions): Promise<{ text: string }>
            image(input: ExperimentalGenerateImageInput, requestOptions?: RequestOptions): Promise<GenerateImageResult>
            decisions(input: ExperimentalGenerateDecisionsInput, requestOptions?: RequestOptions): Promise<GenerateDecisionResult>
        }
        voice: {
            models(requestOptions?: RequestOptions): Promise<{ models: Array<VoiceModel>; default?: string | undefined }>
            session(input: ExperimentalVoiceSessionInput, requestOptions?: RequestOptions): Promise<{ transport: VoiceTransport }>
        }
        integration: {
            wellknown: {
                add(input: ExperimentalIntegrationWellknownAddInput, requestOptions?: RequestOptions): Promise<void>
            }
        }
        mcp: {
            add(input: ExperimentalMcpAddInput, requestOptions?: RequestOptions): Promise<void>
            remove(input: ExperimentalMcpRemoveInput, requestOptions?: RequestOptions): Promise<void>
            connect(input: ExperimentalMcpConnectInput, requestOptions?: RequestOptions): Promise<void>
            disconnect(input: ExperimentalMcpDisconnectInput, requestOptions?: RequestOptions): Promise<void>
            client: {
                token(input: ExperimentalMcpClientTokenInput, requestOptions?: RequestOptions): Promise<ExperimentalMcpClientTokenOutput>
            }
        }
        file: {
            write(input: ExperimentalFileWriteInput, requestOptions?: RequestOptions): Promise<ExperimentalFileWriteOutput>
            watch(input: ExperimentalFileWatchInput, requestOptions?: RequestOptions): Promise<void>
            unwatch(input: ExperimentalFileUnwatchInput, requestOptions?: RequestOptions): Promise<void>
        }
        persistentPty: {
            read(input: ExperimentalPersistentPtyReadInput, requestOptions?: RequestOptions): Promise<PersistentPtyReadResult | null>
            list(input: ExperimentalPersistentPtyListInput, requestOptions?: RequestOptions): Promise<PersistentPtyInfo[]>
            create(input: ExperimentalPersistentPtyCreateInput, requestOptions?: RequestOptions): Promise<PersistentPtyInfo>
            shutdown(requestOptions?: RequestOptions): Promise<void>
            handoff(requestOptions?: RequestOptions): Promise<ExperimentalPersistentPtyHandoffOutput>
            get(input: ExperimentalPersistentPtyGetInput, requestOptions?: RequestOptions): Promise<PersistentPtyInfo>
            update(input: ExperimentalPersistentPtyUpdateInput, requestOptions?: RequestOptions): Promise<PersistentPtyInfo>
            snapshot(input: ExperimentalPersistentPtySnapshotInput, requestOptions?: RequestOptions): Promise<PersistentPtySnapshot>
            remove(input: ExperimentalPersistentPtyRemoveInput, requestOptions?: RequestOptions): Promise<void>
            connectToken(input: ExperimentalPersistentPtyConnectTokenInput, requestOptions?: RequestOptions): Promise<PtyTicketConnectToken>
        }
        media: {
            get(input: ExperimentalMediaGetInput, requestOptions?: RequestOptions): Promise<ExperimentalMediaGetOutput>
        }
        schedule: {
            create(input: ExperimentalScheduleCreateInput, requestOptions?: RequestOptions): Promise<ScheduleInfo>
            list(input: ExperimentalScheduleListInput, requestOptions?: RequestOptions): Promise<ScheduleInfo[]>
            get(input: ExperimentalScheduleGetInput, requestOptions?: RequestOptions): Promise<ScheduleInfo>
            pause(input: ExperimentalSchedulePauseInput, requestOptions?: RequestOptions): Promise<ScheduleInfo>
            resume(input: ExperimentalScheduleResumeInput, requestOptions?: RequestOptions): Promise<ScheduleInfo>
            delete(input: ExperimentalScheduleDeleteInput, requestOptions?: RequestOptions): Promise<void>
        }
        artifacts: {
            providers(input?: ExperimentalArtifactsProvidersInput, requestOptions?: RequestOptions): Promise<ExperimentalArtifactsProvidersOutput>
            list(input?: ExperimentalArtifactsListInput, requestOptions?: RequestOptions): Promise<ExperimentalArtifactsListOutput>
            create(input: ExperimentalArtifactsCreateInput, requestOptions?: RequestOptions): Promise<ExperimentalArtifactsCreateOutput>
            get(input: ExperimentalArtifactsGetInput, requestOptions?: RequestOptions): Promise<ExperimentalArtifactsGetOutput>
            update(input: ExperimentalArtifactsUpdateInput, requestOptions?: RequestOptions): Promise<ExperimentalArtifactsUpdateOutput>
            delete(input: ExperimentalArtifactsDeleteInput, requestOptions?: RequestOptions): Promise<void>
            view(input: ExperimentalArtifactsViewInput, requestOptions?: RequestOptions): Promise<ExperimentalArtifactsViewOutput>
        }
        migration: {
            v1: {
                status(requestOptions?: RequestOptions): Promise<ExperimentalMigrationV1StatusOutput>
            }
        }
        usage: {
            limits(input?: ExperimentalUsageLimitsInput, requestOptions?: RequestOptions): Promise<ExperimentalUsageLimitsOutput>
        }
        config: {
            update(input: ExperimentalConfigUpdateInput, requestOptions?: RequestOptions): Promise<void>
        }
    }
    message: {
        list(input: MessageListInput, requestOptions?: RequestOptions): Promise<SessionMessagesResponse>
    }
    model: {
        list(input?: ModelListInput, requestOptions?: RequestOptions): Promise<ModelListOutput>
        default(input?: ModelDefaultInput, requestOptions?: RequestOptions): Promise<ModelDefaultOutput>
    }
    provider: {
        list(input?: ProviderListInput, requestOptions?: RequestOptions): Promise<ProviderListOutput>
        get(input: ProviderGetInput, requestOptions?: RequestOptions): Promise<ProviderGetOutput>
    }
    credential: {
        list(requestOptions?: RequestOptions): Promise<CredentialEntry[]>
        create(input: CredentialCreateInput, requestOptions?: RequestOptions): Promise<CredentialEntry>
        update(input: CredentialUpdateInput, requestOptions?: RequestOptions): Promise<void>
        activate(input: CredentialActivateInput, requestOptions?: RequestOptions): Promise<void>
        remove(input: CredentialRemoveInput, requestOptions?: RequestOptions): Promise<void>
    }
    project: {
        list(input?: ProjectListInput, requestOptions?: RequestOptions): Promise<ProjectListOutput>
        update(input: ProjectUpdateInput, requestOptions?: RequestOptions): Promise<Project>
    }
    form: {
        list(input?: FormListInput, requestOptions?: RequestOptions): Promise<FormListOutput>
    }
    permission: {
        request: {
            list(input?: PermissionRequestListInput, requestOptions?: RequestOptions): Promise<PermissionRequestListOutput>
        }
        saved: {
            list(input?: PermissionSavedListInput, requestOptions?: RequestOptions): Promise<PermissionSavedInfo[]>
            update(input: PermissionSavedUpdateInput, requestOptions?: RequestOptions): Promise<PermissionSavedInfo>
            remove(input: PermissionSavedRemoveInput, requestOptions?: RequestOptions): Promise<void>
        }
        create(input: PermissionCreateInput, requestOptions?: RequestOptions): Promise<{ id: PermissionID; effect: PermissionEffect }>
        list(input: PermissionListInput, requestOptions?: RequestOptions): Promise<PermissionRequest[]>
        get(input: PermissionGetInput, requestOptions?: RequestOptions): Promise<PermissionRequest>
        reply(input: PermissionReplyInput, requestOptions?: RequestOptions): Promise<void>
    }
    command: {
        list(input?: CommandListInput, requestOptions?: RequestOptions): Promise<CommandListOutput>
    }
    skill: {
        list(input?: SkillListInput, requestOptions?: RequestOptions): Promise<SkillListOutput>
    }
    pty: {
        list(input?: PtyListInput, requestOptions?: RequestOptions): Promise<PtyListOutput>
        create(input?: PtyCreateInput, requestOptions?: RequestOptions): Promise<PtyCreateOutput>
        get(input: PtyGetInput, requestOptions?: RequestOptions): Promise<PtyGetOutput>
        update(input: PtyUpdateInput, requestOptions?: RequestOptions): Promise<PtyUpdateOutput>
        remove(input: PtyRemoveInput, requestOptions?: RequestOptions): Promise<void>
        connect: {
            token(input: PtyConnectTokenInput, requestOptions?: RequestOptions): Promise<PtyConnectTokenOutput>
        }
    }
    shell: {
        list(input?: ShellListInput, requestOptions?: RequestOptions): Promise<ShellListOutput>
        create(input: ShellCreateInput, requestOptions?: RequestOptions): Promise<ShellCreateOutput>
        get(input: ShellGetInput, requestOptions?: RequestOptions): Promise<ShellGetOutput>
        output(input: ShellOutputInput, requestOptions?: RequestOptions): Promise<ShellOutputOutput>
        remove(input: ShellRemoveInput, requestOptions?: RequestOptions): Promise<void>
    }
    reference: {
        list(input?: ReferenceListInput, requestOptions?: RequestOptions): Promise<ReferenceListOutput>
    }
    worktree: {
        list(input: WorktreeListInput, requestOptions?: RequestOptions): Promise<WorktreeList>
        create(input: WorktreeCreateInput, requestOptions?: RequestOptions): Promise<WorktreeInfo>
        remove(input: WorktreeRemoveInput, requestOptions?: RequestOptions): Promise<void>
        refresh(input: WorktreeRefreshInput, requestOptions?: RequestOptions): Promise<void>
    }
    vcs: {
        init(input?: VcsInitInput, requestOptions?: RequestOptions): Promise<void>
        get(input?: VcsGetInput, requestOptions?: RequestOptions): Promise<VcsGetOutput>
        base(input?: VcsBaseInput, requestOptions?: RequestOptions): Promise<VcsBaseOutput>
        status(input?: VcsStatusInput, requestOptions?: RequestOptions): Promise<VcsStatusOutput>
        branch: {
            list(input?: VcsBranchListInput, requestOptions?: RequestOptions): Promise<VcsBranchListOutput>
        }
        diff(input: VcsDiffInput, requestOptions?: RequestOptions): Promise<VcsDiffOutput>
    }
    debug: {
        heapDump(input?: DebugHeapDumpInput, requestOptions?: RequestOptions): Promise<DebugHeapDumpOutput>
        location: {
            list(requestOptions?: RequestOptions): Promise<DebugLocationListOutput>
            evict(input?: DebugLocationEvictInput, requestOptions?: RequestOptions): Promise<void>
        }
    }
    websearch: {
        providers(input?: WebsearchProvidersInput, requestOptions?: RequestOptions): Promise<WebsearchProvidersOutput>
        query(input: WebsearchQueryInput, requestOptions?: RequestOptions): Promise<WebsearchQueryOutput>
    }
    session: {
        list(input?: SessionListInput, requestOptions?: RequestOptions): Promise<SessionsResponse>
        create(input?: SessionCreateInput, requestOptions?: RequestOptions): Promise<SessionInfo>
        active(requestOptions?: RequestOptions): Promise<{ [x: string]: SessionActive }>
        get(input: SessionGetInput, requestOptions?: RequestOptions): Promise<SessionInfo>
        remove(input: SessionRemoveInput, requestOptions?: RequestOptions): Promise<void>
        fork(input: SessionForkInput, requestOptions?: RequestOptions): Promise<SessionInfo>
        switchAgent(input: SessionSwitchAgentInput, requestOptions?: RequestOptions): Promise<void>
        switchModel(input: SessionSwitchModelInput, requestOptions?: RequestOptions): Promise<void>
        update(input: SessionUpdateInput, requestOptions?: RequestOptions): Promise<void>
        move(input: SessionMoveInput, requestOptions?: RequestOptions): Promise<void>
        prompt(input: SessionPromptInput, requestOptions?: RequestOptions): Promise<SessionInboxUser>
        command(input: SessionCommandInput, requestOptions?: RequestOptions): Promise<void>
        synthetic(input: SessionSyntheticInput, requestOptions?: RequestOptions): Promise<SessionInboxSynthetic>
        shell(input: SessionShellInput, requestOptions?: RequestOptions): Promise<void>
        compact(input: SessionCompactInput, requestOptions?: RequestOptions): Promise<SessionInboxCompaction>
        revert: {
            stage(input: SessionRevertStageInput, requestOptions?: RequestOptions): Promise<SessionRevert>
            clear(input: SessionRevertClearInput, requestOptions?: RequestOptions): Promise<void>
            commit(input: SessionRevertCommitInput, requestOptions?: RequestOptions): Promise<void>
        }
        context(input: SessionContextInput, requestOptions?: RequestOptions): Promise<SessionMessageInfo[]>
        diff(input: SessionDiffInput, requestOptions?: RequestOptions): Promise<FileDiffInfo[]>
        inbox: {
            list(input: SessionInboxListInput, requestOptions?: RequestOptions): Promise<SessionInboxInfo[]>
            cancel(input: SessionInboxCancelInput, requestOptions?: RequestOptions): Promise<void>
            update(input: SessionInboxUpdateInput, requestOptions?: RequestOptions): Promise<void>
        }
        generate(input: SessionGenerateInput, requestOptions?: RequestOptions): Promise<{ text: string }>
        interrupt(input: SessionInterruptInput, requestOptions?: RequestOptions): Promise<SessionInterruptResponse>
        background(input: SessionBackgroundInput, requestOptions?: RequestOptions): Promise<void>
        message: {
            get(input: SessionMessageGetInput, requestOptions?: RequestOptions): Promise<SessionMessageAgentSelected | SessionMessageAssistant | SessionMessageCompactionCompleted | SessionMessageCompactionFailed | SessionMessageCompactionRunning | SessionMessageIdle | SessionMessageLocationSwitched | SessionMessageModelSelected | SessionMessageShell | SessionMessageSkill | SessionMessageSynthetic | SessionMessageSystem | SessionMessageUser>
        }
        form: {
            list(input: SessionFormListInput, requestOptions?: RequestOptions): Promise<FormInfo[]>
            create(input: SessionFormCreateInput, requestOptions?: RequestOptions): Promise<FormInfo>
            get(input: SessionFormGetInput, requestOptions?: RequestOptions): Promise<FormDetail>
            reply(input: SessionFormReplyInput, requestOptions?: RequestOptions): Promise<void>
            cancel(input: SessionFormCancelInput, requestOptions?: RequestOptions): Promise<void>
        }
        environment(input: SessionEnvironmentInput, requestOptions?: RequestOptions): Promise<void>
        view(input: SessionViewInput, requestOptions?: RequestOptions): Promise<void>
        stats(input?: ExperimentalSessionStatsInput, requestOptions?: RequestOptions): Promise<SessionStatsInfo>
        import(input: ExperimentalSessionImportInput, requestOptions?: RequestOptions): Promise<SessionInfo>
        export(input: ExperimentalSessionExportInput, requestOptions?: RequestOptions): Promise<SessionTransferData>
        skill(input: ExperimentalSessionSkillInput, requestOptions?: RequestOptions): Promise<void>
        wait(input: ExperimentalSessionWaitInput, requestOptions?: RequestOptions): Promise<void>
        instructions: {
            entry: {
                list(input: ExperimentalSessionInstructionsEntryListInput, requestOptions?: RequestOptions): Promise<InstructionEntryInfo[]>
                put(input: ExperimentalSessionInstructionsEntryPutInput, requestOptions?: RequestOptions): Promise<void>
                remove(input: ExperimentalSessionInstructionsEntryRemoveInput, requestOptions?: RequestOptions): Promise<void>
            }
        }
        log(input: ExperimentalSessionLogInput, requestOptions?: RequestOptions): AsyncIterable<ExperimentalSessionLogOutput>
    }
    generate: {
        text(input: ExperimentalGenerateTextInput, requestOptions?: RequestOptions): Promise<{ text: string }>
        image(input: ExperimentalGenerateImageInput, requestOptions?: RequestOptions): Promise<GenerateImageResult>
        decisions(input: ExperimentalGenerateDecisionsInput, requestOptions?: RequestOptions): Promise<GenerateDecisionResult>
    }
    voice: {
        models(requestOptions?: RequestOptions): Promise<{ models: Array<VoiceModel>; default?: string | undefined }>
        session(input: ExperimentalVoiceSessionInput, requestOptions?: RequestOptions): Promise<{ transport: VoiceTransport }>
    }
    integration: {
        list(input?: IntegrationListInput, requestOptions?: RequestOptions): Promise<IntegrationListOutput>
        get(input: IntegrationGetInput, requestOptions?: RequestOptions): Promise<IntegrationGetOutput>
        connect: {
            key(input: IntegrationConnectKeyInput, requestOptions?: RequestOptions): Promise<void>
            external(input: IntegrationConnectExternalInput, requestOptions?: RequestOptions): Promise<void>
        }
        oauth: {
            connect(input: IntegrationOauthConnectInput, requestOptions?: RequestOptions): Promise<IntegrationOauthConnectOutput>
            status(input: IntegrationOauthStatusInput, requestOptions?: RequestOptions): Promise<IntegrationOauthStatusOutput>
            complete(input: IntegrationOauthCompleteInput, requestOptions?: RequestOptions): Promise<void>
            cancel(input: IntegrationOauthCancelInput, requestOptions?: RequestOptions): Promise<void>
        }
        command: {
            connect(input: IntegrationCommandConnectInput, requestOptions?: RequestOptions): Promise<IntegrationCommandConnectOutput>
            status(input: IntegrationCommandStatusInput, requestOptions?: RequestOptions): Promise<IntegrationCommandStatusOutput>
            cancel(input: IntegrationCommandCancelInput, requestOptions?: RequestOptions): Promise<void>
        }
        wellknown: {
            add(input: ExperimentalIntegrationWellknownAddInput, requestOptions?: RequestOptions): Promise<void>
        }
    }
    mcp: {
        list(input?: McpListInput, requestOptions?: RequestOptions): Promise<McpListOutput>
        resource: {
            catalog(input?: McpResourceCatalogInput, requestOptions?: RequestOptions): Promise<McpResourceCatalogOutput>
        }
        add(input: ExperimentalMcpAddInput, requestOptions?: RequestOptions): Promise<void>
        remove(input: ExperimentalMcpRemoveInput, requestOptions?: RequestOptions): Promise<void>
        connect(input: ExperimentalMcpConnectInput, requestOptions?: RequestOptions): Promise<void>
        disconnect(input: ExperimentalMcpDisconnectInput, requestOptions?: RequestOptions): Promise<void>
        client: {
            token(input: ExperimentalMcpClientTokenInput, requestOptions?: RequestOptions): Promise<ExperimentalMcpClientTokenOutput>
        }
    }
    file: {
        read(input: FileReadInput, requestOptions?: RequestOptions): Promise<FileReadOutput>
        list(input?: FileListInput, requestOptions?: RequestOptions): Promise<FileListOutput>
        find(input: FileFindInput, requestOptions?: RequestOptions): Promise<FileFindOutput>
        write(input: ExperimentalFileWriteInput, requestOptions?: RequestOptions): Promise<ExperimentalFileWriteOutput>
        watch(input: ExperimentalFileWatchInput, requestOptions?: RequestOptions): Promise<void>
        unwatch(input: ExperimentalFileUnwatchInput, requestOptions?: RequestOptions): Promise<void>
    }
    migration: {
        v1: {
            status(requestOptions?: RequestOptions): Promise<ExperimentalMigrationV1StatusOutput>
        }
    }
    usage: {
        limits(input?: ExperimentalUsageLimitsInput, requestOptions?: RequestOptions): Promise<ExperimentalUsageLimitsOutput>
    }
    config: {
        get(input?: ConfigGetInput, requestOptions?: RequestOptions): Promise<ConfigGetOutput>
        shells(requestOptions?: RequestOptions): Promise<ConfigShellsOutput>
        update(input: ExperimentalConfigUpdateInput, requestOptions?: RequestOptions): Promise<void>
    }
    rpc: RpcApi<RpcCallOptions> & {
        call(input: RpcCallInput, requestOptions?: RequestOptions): Promise<RpcOutput>
    }
    event: {
        // simplified: the real signature spells out every event name and maps each to its payload type
        subscribe<Type extends OpenCodeEvent["type"] = OpenCodeEvent["type"]>(options?: SubscribeOptions<Type>): AsyncIterable<SelectedEvent<OpenCodeEvent, Type>>
    }
}
```

### Notes

Non-obvious members only; the rest do what group + name say. Apply to
`ctx.<domain>` too (same methods). Coverage so far: `session`.

- Top-level `session` also carries the experimental members (`wait`,
  `instructions`, `stats`, `log`, ...): same as `experimental.session.*`,
  same `ExperimentalSession*` inputs, `/api/experimental/` routes.
- `session.context` → `Session.Message.*[]`: the model-visible history since
  the last compaction. Not the full transcript, not a context object.
- `session.prompt` / `synthetic` / `compact` → the admitted inbox item, not a
  result. `synthetic`: transcript message, no model turn, no prompt hooks.
  `generate`: one-off text from the session's context; writes nothing.
  `wait`: resolves when the agent loop is idle. `message.get`: one message by
  id (union of every message kind).
- Session code: `packages/server/src/handlers/session.ts` (HTTP side of
  every method) → `packages/core/src/session.ts` and `packages/core/src/session/`
  (`context.ts`, `inbox.ts`, `instruction-*.ts`, ...).
- `session.inbox.*`: the durable queue of undelivered input (user, synthetic,
  compaction, move items), in enqueue order. `delivery`:
  - `steer` (default for `prompt`, `compact`): taken at the next step
    boundary, so it can redirect a running loop.
  - `queue`: waits until current work is done.
  - `inbox.update` changes an item's mode (to `steer` wakes the loop);
    `inbox.cancel` withdraws an undelivered item. `interrupt({ resume: true })`
    resumes `steer` items; `queue` items stay parked.
- `session.instructions.entry.*`: keyed `<context key="k">` blocks in the
  session's instructions. Key `^[a-z0-9][a-z0-9._-]*$`; value any JSON up to
  256 KiB (a string renders verbatim, anything else as indented JSON).
  - Prompt cache: the instruction prefix holds an epoch baseline, frozen at
    session start and re-based at each compaction. A later `put`/`remove`
    does not edit the prefix: at the next step boundary it is appended to
    the history as a message ("The context under "k" changed and
    supersedes the previous value: ..." / "... no longer applies"). The
    cached prefix survives; a same-value `put` is a no-op.
  - Each change re-sends the whole value, so frequent large updates grow the
    history until the next compaction.
  - Source: opencode 2.2.5 `packages/core/src/session/instruction-state.ts`,
    `instruction-entry.ts`.
