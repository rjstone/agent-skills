# Console HTTP API without the MCP server

For an agent that can't use the Console MCP server (no browser for its OAuth
sign-in, CI, a headless job) and must read the workspace with an API key.
The Console MCP rejects API keys (HTTP 403): it takes only its browser
sign-in.

## Key

`Authorization: Bearer oc_sk_...`, one workspace per key, no workspace
header. For automation use a **service account** key (owners and admins:
**Settings › Service accounts**). Give it the least it needs, e.g.
**Restricted** with **Models: Read** and **Usage: Read**. Service account
keys can never invite or remove members, change roles, manage billing or
models, or change workspace settings, even with **All**. Outside a key's
permissions: HTTP 403. Details: `references/api.md`.

## Documented endpoints (stable)

| Need | Call |
| --- | --- |
| Models and providers the workspace can use, with `cost` | `GET https://opencode.ai/console/api/v1/models` (`references/api-models.md`) |
| Public catalogs (no key) | `GET https://opencode.ai/inference/v1/models`, `.../inference/go/v1/models` |
| Call a model | `https://opencode.ai/inference[/go]/<api path>` (`references/api-inference.md`) |
| Call a connected provider | `https://opencode.ai/inference/custom/<conn_id>/...` (`references/api-providers.md`) |

The docs publish no REST endpoints for members, usage or budgets: those are
in the Console UI and the MCP tools (`get_usage`, `get_member_usage`,
`list_members`) only.

## The CLI's wire contract (undocumented; may change)

`@opencode/console` exports the schemas it uses with Console's API, for
anyone building a client (Effect `Schema`; `effect` is an optional peer
dependency the subpaths need):

- `@opencode/console/contract`: API responses and headers the CLI reads and
  sends.
- `@opencode/console/event-watch`: what a session can watch, the events
  Console sends, the protocol's limits.
- `@opencode/console/event-watch-tool`: which Slack and GitHub tool calls
  start a watch.

Read the types without installing: `npm pack @opencode/console` into an
empty folder, extract, open `package/types/*.d.ts`.

Paths the CLI calls, relative to `https://opencode.ai/console` (seen in
0.1.15; a key without the matching permission or workspace feature gets 403):

| Path | Contract schema |
| --- | --- |
| `GET /api/v2/config` | `ConfigDocument`: the workspace's generated OpenCode config (providers, models). Response headers `x-opencode-event-watches: 1`, `x-opencode-instructions-skills: 1` say which features the caller may use |
| `GET /api/v1/models` | `ModelsDocument` |
| `GET /api/v2/instructions`, `/api/v2/skills`, `/api/v2/skills/<name>` | `Instructions`, `Skills`, `SkillBundle` |
| `GET /api/v2/codex/models` | `CodexModels` (Codex's `model_catalog_url`) |
| `/api/event-watches`, `/types`, `/events`, `/ack`, `/<id>` | `WatchList`, `EventTypeList`, `WatchEvent`, `Watch` |
| `/api/artifacts`, `/prepare`, `/<slug>`, `/<slug>/files[?revision=N]`, `/<slug>/blobs/<sha256>` | `ArtifactList`, `ArtifactPrepare(d)`, `ArtifactPublish(ed)`, `ArtifactFiles` |
| `POST /auth/device/code` | `Device`, `Token`: the CLI's device sign-in |

Request headers the CLI sends: `x-opencode-plugin: opencode-console/<version>`
(names the client), `x-opencode-watch-session` (the session behind an MCP
connection).

Prefer the documented endpoints; use these only to read what the CLI itself
reads, and re-check the types of the installed version first.
