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

## Pricing source: LiteLLM (`--litellm`)

`BerriAI/litellm`, `model_prices_and_context_window.json` (MIT, about 4 MB, read 2026-11-18): about
6,200 entries from about 157 providers, keyed by LiteLLM model name (OpenAI models unprefixed,
most others `<litellm_provider>/<model>`, e.g. `groq/openai/gpt-oss-120b`).

- Prices are USD **per token**; `lookup.py` shows USD per 1M tokens. Fields used: `input/output_cost_per_token`,
  `cache_read_input_token_cost`, `cache_creation_input_token_cost`, `*_batches`, `*_priority`, `*_flex`,
  `*_above_<N>_tokens`. Also `max_input_tokens`, `max_output_tokens`, `supports_*`, `source`
  (provider pricing page, on about 3/4 of chat entries), `deprecation_date`, `successor_model`.
- Only `mode` chat / responses entries are matched; embeddings, images, audio and video are ignored.
- Provider names differ from models.dev (`gemini` vs `google`, `bedrock_converse` vs `amazon-bedrock`);
  `LITELLM_IDS` in `lookup.py` maps them, otherwise names match after removing punctuation.
- Spot check (2026-11-18): 247 of 266 shared models had the same in/out price as models.dev. DeepSeek
  differs by exactly 2x (LiteLLM has the peak price); Mistral `-latest` aliases were newer in LiteLLM.
- `--litellm-file` reads a local copy.

## Second pricing opinion: Portkey-AI/models (`--portkey`)

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

## Last resort: community provider list (`--extra-list`)

`foisalislambd/all-llm-provider-list`, `data/providers.json`: about 494 providers (slug, aliases,
category, website, `api_base_url`, `env_variable`, `openai_compatible`, popular models, notes).
Read 2026-11-18. No license file and no per-entry sources or dates, so it is read at run time from
GitHub raw and never copied into this repo.

- Used only when models.dev and the overrides have no match or a weak fuzzy one (score below 80),
  and the list matches better. Every field is tagged `community list (UNVERIFIED ...)`.
- Skipped: categories `Web Cookie`, `OAuth` and `No-auth` (pasted browser cookies, reused app
  logins, anonymous chat widgets; many break the services' terms), and entries whose base URL
  is not an `http` URL. About 416 entries remain.
- Its base URLs agreed with models.dev for 82 of 115 shared providers (2026-11-18): check them.
- `--extra-list-file` reads a local copy of `providers.json`.

## Reviewed and skipped (2026-11-18)

Don't re-review these unless they change shape:

- `tashfeenahmed/freellmapi` - free-tier router app. Its free-tier rate limits are only in TypeScript
  database migrations; the current catalog is a signed feed from its own service (free tier 30 days late).
- `cheaper-inference/OmniRoute` - free-tier gateway app built around reusing Claude Code, Codex,
  Cursor and Copilot logins (client-fingerprint files); no data file, provider details live in app code.
- `latere-ai/lux` - self-hosted gateway; only an example catalog (7 providers, 94 models) that
  is a 2026-09 snapshot its README says users must keep current themselves.
- `vercel-labs/provider-models-monitor` - model-id lists from the `/models` endpoints of 4 providers
  (Anthropic, Google, OpenAI, xAI), ids only; updates arrive as PRs and `main` was last updated
  2026-04-21. Checking the provider's own `/models` endpoint does the same job live.
- `jeffkit/recursive-providers` (CC0) - 12 providers mirrored from LiteLLM; not a source, but its
  `key_url` values are a good seed for `signup_url` in the overrides once checked.

## Network notes

- Sandboxed agents often block models.dev until the user allows the host in the agent's network settings
  (on claude.ai: Settings > Capabilities > allowed domains).
- WebFetch refuses models.dev (robots). Do not route around a refusal with curl, mirrors or caches.
- A refusal or proxy 403 is a fact to report, then move to the next source above.

## Override table

`providers-overrides.json` holds what models.dev lacks: first-party base URLs, header requirements, quirks,
sign-up URLs. Entries carry a `verified` date and `source`; entries marked `unverified` are general knowledge
and only used when models.dev has no `api` field. Extend it as providers are confirmed.
