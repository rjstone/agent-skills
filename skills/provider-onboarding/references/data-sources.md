# Data sources and schema notes

Read this when the default lookup fails, or when you need to interpret a field.

## Primary source: models.dev

Repo: `anomalyco/models.dev` (formerly SST). The schema below was read from the repo source
(`packages/function/src/worker.ts`, `packages/sdk/src/types.ts`) on 2026-11-02. It was NOT
checked against live responses, because the site was unreachable from where this was written.
If a live response disagrees with this file, trust the response and tell the user.

| Endpoint | Shape |
|---|---|
| `/api.json` | `{ providerId: Provider }` (what `lookup.py` reads) |
| `/models.json` | `{ "lab/model": ModelMetadata }` |
| `/catalog.json` | `{ providers, models }` |
| `/model-schema.json` | JSON Schema enum of `provider/model` ids only |
| `?type=all` | include specialized model types hidden by default; comma-separated types allowed; invalid type gives 400 with an `allowed` list |

The server sends an ETag, honors `If-None-Match` (304), and sets `Cache-Control: max-age=3600`.
`lookup.py` caches on disk with the same 1 hour TTL and falls back to a stale cache if the network fails.

### Provider fields
`id, name, env[], npm, doc, api?, models{}`.
- `api` exists only for gateway / OpenAI-compatible providers (OpenRouter, DeepSeek, ...).
  First-party providers such as Anthropic usually have no `api`; the base URL is implied by the SDK in `npm`.
  This is why `providers-overrides.json` exists.
- There is NO sign-up or key-page field anywhere. Sign-up URLs are always inferred or come from overrides.

### Model fields
`id, canonical_model_id?, type?, name, description, family?, attachment, reasoning, reasoning_options?,
tool_call, interleaved?, structured_output?, temperature?, knowledge?, release_date, last_updated,
modalities{input,output}, open_weights, limit{context,input?,output}, status? (alpha|beta|deprecated),
experimental?, provider?{npm,api,shape,body,headers}, cost?{input,output,reasoning?,cache_read?,cache_write?,...}`.
Prices are USD per 1M tokens; `cost` is absent when no price is published.
A model-level `provider.api` / `provider.npm` overrides the provider's, and `lookup.py` honors that.
`canonical_model_id` is how the same model is matched across providers.

## Alternate sources (use when models.dev is unreachable)

1. GitHub read of the upstream repo: `providers/<id>/provider.toml` and `providers/<id>/models/<model>.toml`.
   Fine for one provider; too slow for sweeping queries.
2. `https://models.opencode.ai/api.json` is probably a mirror of models.dev (UNVERIFIED). It is in the
   default URL list so it is tried automatically.
3. A user-uploaded `api.json` via `--file`.
4. The provider's own docs and `/models` endpoint (OpenAI-compatible providers usually expose `GET <base>/models`).
5. A local stdio MCP server such as `arifpambudi242/models.dev-mcp` if the user already runs it.

## Pricing source: Portkey-AI/models (`--portkey`)

MIT-licensed data behind Portkey's AI Gateway, about 54 providers. Read 2026-11-18.

| Path | Shape |
|---|---|
| `pricing/<provider>.json` | `{ "default": {...}, "<model>": {"pricing_config": {"pay_as_you_go": {...}, "batch_config": {...}, "calculate": {...}}}}` |
| `general/<provider>.json` | `{ "name", "default": {"params": [{key, defaultValue, minValue, maxValue, ...}], "messages", "type"}, "<model>": {...} }` |

- **Prices are in cents per token** (their README says so). `lookup.py` converts to USD per 1M
  tokens (x 10,000). `additional_units` (web_search, file_search, ...) are cents per unit; shown as USD.
- A model entry lists only the fields it overrides; a field it omits falls back to `default`.
- Sources, in order: `https://configs.portkey.ai/<path>`, then
  `https://raw.githubusercontent.com/Portkey-AI/models/main/<path>`. The GitHub contents API (folder
  listing) may be refused where raw files work, so the lookup fetches files by name, never by listing.
- Provider names differ from models.dev (`mistral` vs `mistral-ai`); `PORTKEY_IDS` in `lookup.py` maps
  them. Portkey-only providers (fal-ai, voyage, elevenlabs, ...) work in manual mode via `--name`.
- Per-model API: `https://api.portkey.ai/model-configs/pricing/<provider>/<model>` (not used by the script).

## Network notes

- Sandboxed agents often block models.dev until the user allows the host in the agent's network settings
  (on claude.ai: Settings > Capabilities > allowed domains).
- WebFetch refuses models.dev (robots). Do not route around a refusal with curl, mirrors or caches.
- A refusal or proxy 403 is a fact to report, then move to the next source above.

## Override table

`providers-overrides.json` holds what models.dev lacks: first-party base URLs, header requirements, quirks,
sign-up URLs. Entries carry a `verified` date and `source`; entries marked `unverified` are general knowledge
and only used when models.dev has no `api` field. Extend it as providers are confirmed.
