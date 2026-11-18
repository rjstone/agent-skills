# Portkey pricing in provider-onboarding (2026-11-18)

Goal: optional second data source for detailed pricing and parameter ranges in
`skills/provider-onboarding/scripts/lookup.py`, without changing default output.

1. `--portkey` / `--portkey-dir`: read `pricing/` and `general/<provider>.json`
   from `Portkey-AI/models`. The API (`configs.portkey.ai`) first, GitHub raw
   files as the fallback (the user's requirement); files fetched by name.
2. Map models.dev ids to Portkey file names (`PORTKEY_IDS`), checked against
   live data on both sides; convert cents/token to USD per 1M tokens.
3. Render a separate Portkey section with its source in the card and JSON.
4. Offline tests (fixture dir, fake fetch for the fallback order), docs, version 0.2.0.

Done. In the session sandbox the Portkey hosts were blocked and the GitHub
fallback served the data (gpt-4o: $2.50 / $10 per 1M, matching OpenAI).

## Follow-up: community list (0.3.0)

`--extra-list`: `foisalislambd/all-llm-provider-list` as a last resort when
models.dev has no or only a weak match. Read at run time (no license), every
field tagged UNVERIFIED, Web Cookie / OAuth / No-auth categories and non-URL
endpoints skipped (the user, 2026-11-18). Offline tests use a fixture file.
