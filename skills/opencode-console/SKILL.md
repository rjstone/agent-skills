---
name: opencode-console
description: Use when setting up or administering an OpenCode Console workspace (members, roles, SSO, SCIM, budgets, billing, policies, providers, models), connecting Claude Code, Codex, Hermes, Pi or another harness to Console with npx @opencode/console, using the Console MCP server or its tools, calling Console inference or model-list endpoints with an oc_sk_ API key, using OpenCode Go or OpenCode Models, or looking up a Console model's current price.
compatibility: Refreshing references/ (scripts/refresh_references.py) and live price lookups need network access to opencode.ai; the cached docs work offline.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# OpenCode Console

## Overview

The OpenCode Console (https://opencode.ai/console) is opencode's hosted
service: workspaces for teams, pay-as-you-go inference (OpenCode Models), the
Go subscriptions, provider connections, budgets and policies. It is not the
opencode CLI (`opencode-cli` skill) or the local server API (`opencode-api`).
**Don't give Console URLs, commands or menu paths from memory:** older names
(such as "Zen" URLs) are wrong now.

Two kinds of request:

- **The user wants to configure something themselves** (settings, keys,
  endpoints, prices): Part 1.
- **The user asks you to do something in the Console** (connect a harness,
  read usage, enable models): Part 2.

## Part 1: helping a user configure it

- **Inference base URLs:** pay-as-you-go `https://opencode.ai/inference`,
  Go `https://opencode.ai/inference/go`. Append the API path:
  `/openai/v1/responses`, `/openai/v1/chat/completions`,
  `/anthropic/v1/messages`, `/google/v1beta/models/<model>:generateContent`.
  Every path serves every paid and Go text model.
- **Auth:** `Authorization: Bearer oc_sk_...`. A personal API key (any
  member, **Account › Personal API keys**) or a service account key (owners
  and admins, **Settings › Service accounts**). A key belongs to one
  workspace; no workspace header.
- **Model lists:** `GET https://opencode.ai/console/api/v1/models` (key
  required; everything the workspace can use, connected providers included),
  `https://opencode.ai/inference/v1/models` and `.../inference/go/v1/models`
  (OpenAI list shape; the public catalog without a key).
- **OpenCode itself:** run `/connect` and choose the workspace.

### Prices: `[check-api]`

The refresh script replaces every dollar amount in `references/` (except a
`$0` setting) with `[check-api]`, because prices change faster than the
cache. When you need one:

- **Per-token model prices:** read `cost` from the live model list (US
  dollars per 1M tokens; `0` = free). No key needed:

  ```bash
  curl -s https://opencode.ai/inference/v1/models \
    | jq '.data[] | select(.id=="<model-id>") | {id, cost}'
  ```

  Use `.../inference/go/v1/models` for Go models, or the Console list with a
  key for the workspace's own view.
- **Subscription, seat, fee and web search prices** (Go, Go Plus, Go Teams,
  credit top-ups): not in any API. Fetch the live page, e.g.
  `curl -s https://opencode.ai/docs/console/go.md` (or `billing.md`,
  `websearch.md`).

Quote prices with the date you fetched them. Never fill in `[check-api]`
from memory.

### Which reference

| Task | Read |
| --- | --- |
| What the Console is, get started, workspace policies | `references/intro.md` |
| Create, switch, delete a workspace; roles; connect OpenCode | `references/workspaces.md` |
| Invite members, Go Teams seats | `references/members.md` |
| SSO, SCIM provisioning | `references/sso.md`, `references/scim.md` |
| Member and service-account spending limits | `references/budgets.md` |
| Credits, invoices, auto-reload | `references/billing.md` |
| OpenCode Models catalog and endpoints | `references/models.md` |
| Go, Go Plus, Go Teams: limits, allowance | `references/go.md` |
| Bring your own provider account (gateway) | `references/providers.md` |
| Web search tool | `references/websearch.md` |
| API keys, service accounts, permissions, revocation | `references/api.md` |
| Model list API, `cost` fields | `references/api-models.md` |
| Inference requests, cost reporting | `references/api-inference.md` |
| Calling connected providers (`/inference/custom/...`) | `references/api-providers.md` |
| Base URLs and setup for any harness | `references/harnesses.md` |
| One harness by hand | `references/harnesses-claude-code.md`, `references/harnesses-codex.md`, `references/harnesses-hermes.md`, `references/harnesses-pi.md`, `references/harnesses-raycast.md` |

## Part 2: acting for the user

Before connecting a harness, run `npx @opencode/console status`: if it is
already connected, skip setup, and check whether the Console MCP tools are
already available before adding the server. Tasks that only use MCP tools
don't need it.

Three ways in, best first:

### Console MCP server (manage the workspace)

`https://opencode.ai/console/mcp`, HTTP, OAuth with dynamic client
registration: the user signs in from the browser; API keys are refused.
Claude Code:
`claude mcp add --transport http --scope user opencode-console https://opencode.ai/console/mcp`,
then `/mcp`, select it, sign in. Other harnesses: `references/harnesses.md`.
OpenCode adds it as `opencode_console` when the workspace enables it.

Tools act on one workspace as the signed-in member; call `get_context` first.

| Area | Tools |
| --- | --- |
| Who and where | `get_context` |
| Usage and spend | `get_usage` (yours, plus your spend limits), `get_member_usage` (`user_id`, range `24h`/`7d`/`30d`/`all`) |
| Members | `list_members` (search, 100 per page) |
| Providers | `list_providers`, `create_provider` (custom HTTP provider: `oa-compat`, `openai`, `anthropic`, `google`) |
| Models | `list_models`, `set_model_enabled`, `set_models_enabled` (bulk), `create_model`, `update_model` (name, limits, capabilities, `cost_tiers`) |

Model and provider changes reach every member within about a minute: confirm
with the user before enabling, disabling or adding.

The MCP has no tools for API keys, service accounts, budgets, billing,
policies, or workspace skills and instructions: those need the Console UI.

### Console CLI (connect a harness, share files)

`npx @opencode/console setup <claude-code|codex|pi|deepseek-harness|hermes>`
(browser sign-in, Node.js 22+; `--keep-provider` keeps the harness's own
models) gives that harness the workspace's models, policies, MCP servers,
skills and instructions. Also: `status`, `--remove`, `artifact
share|list|pull|delete`, `update`, event watches, `OPENCODE_API_KEY` for CI.
Commands, flags, files written and no-Node installers: **`CLI.md`**.

### HTTP API with a key (no MCP available)

For headless or CI use with a service account key: the documented endpoints
and the CLI's undocumented wire contract (`@opencode/console/contract`) are
in **`API.md`**. Members and usage have no documented REST endpoints.

## Common mistakes

- Old "Zen" URLs or a made-up base path: use the base URLs above.
- Go key on the pay-as-you-go URL (or the reverse): match the URL to the plan.
- Pasting an API key into an MCP config: the Console MCP uses browser OAuth.
- Calling a free-tier model from your own script or another harness: free
  chat models answer only inside OpenCode; other clients get HTTP 403.
- Quoting a cached or remembered price: look it up live (above).

## Maintaining

`python scripts/refresh_references.py` re-downloads changed pages from the
"## Console" section of https://opencode.ai/docs/llms.txt (`--check`,
`--force`, `--prune`). Never hand-edit `references/`: a test compares each
file with its hash in `references/manifest.json`. `CLI.md` (from the npm
package README) and `API.md` (from the package's `types/`) are ours: re-check
them when `@opencode/console` changes.
