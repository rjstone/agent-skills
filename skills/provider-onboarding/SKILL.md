---
name: provider-onboarding
description: Use when the user wants to add support for, wire up, onboard or integrate an LLM provider or model ("add support for X's Y model"), asks how to call a model, what a provider's endpoint, API-key env var, model id, context limit or price is, or where to get an API key, or wants a new OpenAI- or Anthropic-compatible provider configured (opencode, fast-agent, curl) - even if they never say "provider card" or name a data source.
compatibility: scripts/lookup.py needs network access to models.dev and models.opencode.ai, or a local api.json passed with --file.
license: MIT
metadata:
  author: Robert Stone
  source: https://github.com/rjstone/agent-skills
  version: "0.1.0"
---

# Provider onboarding

Turn "add support for `<provider>`'s `<model>`" into a verified-where-possible provider card and config snippets. The card is only as good as its sources, so every field is labeled with where it came from and anything inferred is said to be inferred.

## Workflow

1. **Parse the request** into a provider name, a model name, or both. "Add the Y model" with no provider is valid; the lookup lists every provider serving it.
2. **Run the lookup** (stdlib Python, no installs):
   ```bash
   python3 scripts/lookup.py --provider "<provider>" --model "<model>"
   python3 scripts/lookup.py --model "<model>"            # who serves this model?
   python3 scripts/lookup.py --list-providers             # browse
   python3 scripts/lookup.py -p X -m Y --format json      # machine-readable
   ```
   Paths are relative to this skill's directory. It reads `https://models.dev/api.json` and `https://models.opencode.ai/api.json` (override with `--url`, env `MODELS_DEV_URLS`, or `--file api.json`), merges `references/providers-overrides.json`, and caches for an hour. `--all-types` includes specialized model types hidden by default.
3. **Handle failure** by reading the lookup's message, then `references/data-sources.md`. In order: GitHub read of `anomalyco/models.dev` (`providers/<id>/provider.toml`), ask the user to upload `api.json` (`--file`), ask them to allow `models.dev` and `models.opencode.ai` in their agent's network settings (on claude.ai: Settings > Capabilities), or web-search the provider's docs. If the network refuses a host, say so plainly; do not hunt for a workaround.
4. **Provider not in any database?** Use manual mode after finding the docs: `--name X --base-url https://api.x.com/v1 --env-var X_API_KEY --model-id y`. It generates the same card and snippets.
5. **Deliver the card** (below), then the snippets the user's tooling needs, then the operator checklist.

## What the card must contain

- Base URL, API-key env var, protocol (OpenAI chat, Responses, Anthropic messages), docs URL
- Model id exactly as the API expects it, context/output limits, price per 1M tokens (omit if none published)
- Other providers serving the same model, with base URL and price, when the user hasn't pinned a provider
- Sign-up / key page candidates with confidence
- Hosts that must be allowlisted in any sandboxed agent
- A source tag per field: models.dev, override table (with verified date), inferred, manual, or MISSING

## Sign-up page inference

models.dev has no sign-up field, so the lookup infers. The rule: if the API lives at `api.modelprovider.com`, then `modelprovider.com` is probably where sign-up or subscribe links are.

- Apex of the API host: medium confidence. Apex of the docs host, if different: medium.
- Hosts on shared infrastructure (googleapis.com, amazonaws.com, azure.com, workers.dev, vercel.app, ...) get no apex guess, because the apex belongs to the cloud, not the provider. Say that and search the docs instead.
- The models.dev `doc` URL is low confidence; it is documentation, not necessarily sign-up.
- Never present an inferred URL as verified. Say "likely: <url>" and name the basis. Common paths to try by hand, all unverified: `/signup`, `/login`, `/dashboard`, `/keys`, `/api-keys`, `/console`. If a browser or fetch tool is available and the user wants confirmation, check the page and report what is really there.
- When a URL is confirmed, suggest adding it to `signup_url` in `references/providers-overrides.json` so it stops being a guess.

## Snippets generated

- **opencode v2** provider block with `{env:VAR}` substitution and top-level `model`. The `package` value comes from the data when present; otherwise it is `@opencode/ai/providers/openai-compatible` for OpenAI-compatible providers, or a flagged guess. Tell the user to confirm with `opencode debug config`.
- **fast-agent** `generic:` config using `base_url` and `api_key: "${VAR}"`, plus a `fast-agent go --model generic.<id> --message ...` smoke test.
- **curl** smoke test (OpenAI-style `/chat/completions` with a Bearer env var, or Anthropic `/messages` with `x-api-key` and `anthropic-version`); for unknown protocols it points at the docs instead of guessing.
- **env var** export line. Never ask the user to paste a key into chat, and never print one.

## Operator checklist (end every card with this)

1. Get an API key from the sign-up candidate (verify the page first).
2. Allowlist the hosts from the card in the agent's network settings.
3. Provide the key as an env var (or a placeholder if an egress proxy injects it).
4. Run the curl smoke test; a 200 with text is the real confirmation.
5. Record what was verified and the date; offer to add or fix an override entry.

## Honesty rules

- Date-stamp the lookup. Prices and model lists change; models.dev may lag the provider.
- A model name the user gives (or you remember) may be retired or renamed. Check the provider's
  models list or changelog before putting it in config, and say what replaced it.
- `UNVERIFIED author knowledge` in a source tag means it came from the seed override table, not a live check. Say so.
- A model with `status: deprecated/alpha/beta` or `experimental` gets a visible note.
- If matches were ambiguous (the lookup prints a warning), name the alternatives instead of silently choosing.
- The schema in `references/data-sources.md` was read from repo source, not live responses. If a live response differs, trust it and say so.

## Extending

Add verified providers to `references/providers-overrides.json` (fields: `base_url`, `env`, `hosts`, `signup_url`, `docs`, `headers`, `quirks`, `verified`, `source`). Quirks that burned someone belong there (free-tier limits, required headers, single-protocol models).
