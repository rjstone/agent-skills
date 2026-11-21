---
name: opencode-console
description: Use when setting up or administering an OpenCode Console workspace (members, roles, SSO, SCIM, budgets, billing, policies), connecting Claude Code, Codex, Hermes, Pi or another harness to Console models with npx @opencode/console, adding the Console MCP server, calling Console inference or model-list endpoints with an oc_sk_ API key, using OpenCode Go or OpenCode Models, or looking up a Console model's current price.
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
service: workspaces for teams, pay-as-you-go inference (OpenCode Models),
the Go subscriptions, provider connections, budgets and policies. It is not
the opencode CLI (see the `opencode-cli` skill) or the local server API
(`opencode-api`). **Don't give Console URLs, commands or menu paths from
memory:** older names (such as "Zen" URLs) are wrong now. Check
`references/` first.

## Essentials

- **Console CLI** (Node.js 22+): `npx @opencode/console setup <harness>`,
  where `<harness>` is `claude-code`, `codex`, `hermes`, `pi` or
  `deepseek-harness`. It opens the browser to sign in and pick the workspace,
  then gives the harness the workspace's models, policies, MCP servers,
  skills and instructions, and keeps them in sync. Add `--keep-provider`
  to keep the harness's own sign-in and models (Claude Code, Codex, Hermes).
- **Console MCP server:** `https://opencode.ai/console/mcp` (HTTP, OAuth with
  dynamic client registration: sign in from the browser, no key). Claude Code:
  `claude mcp add --transport http --scope user opencode-console https://opencode.ai/console/mcp`,
  then `/mcp`, select it, sign in. Other harnesses: `references/harnesses-*.md`.
  OpenCode itself adds it as `opencode_console` when the workspace enables it.
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

## Prices: `[check-api]`

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

## Which reference

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
| Console CLI, base URLs, Console MCP for any harness | `references/harnesses.md` |
| One harness by hand | `references/harnesses-claude-code.md`, `references/harnesses-codex.md`, `references/harnesses-hermes.md`, `references/harnesses-pi.md`, `references/harnesses-raycast.md` |

## Common mistakes

- Old "Zen" URLs or a made-up base path: use the base URLs above.
- Go key on the pay-as-you-go URL (or the reverse): match the URL to the plan.
- Pasting an API key into an MCP config: the Console MCP uses browser OAuth.
- Quoting a cached or remembered price: look it up live (above).

## Maintaining

`python scripts/refresh_references.py` re-downloads changed pages from the
"## Console" section of https://opencode.ai/docs/llms.txt (`--check`,
`--force`, `--prune`). Never hand-edit `references/`: a test compares each
file with its hash in `references/manifest.json`.
