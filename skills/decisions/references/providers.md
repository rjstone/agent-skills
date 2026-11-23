# Providers and models

All prices and model lists change; check before quoting. Data retention and
use policies change too: the user confirms the provider's current policy at
its source for each new setup, and again when reusing an old one
([privacy.md](privacy.md)). Prices are USD per
1M **input** tokens (output is free or not billed on most decision models). A
typical decision is 100-1,500 input tokens.

## Built-in providers (live System One call verified 2026-11-23)

| Provider | Endpoint (POST) | Key env var | Default model | Sign-up / docs |
|---|---|---|---|---|
| `opencode` | `https://opencode.ai/inference/systemone/v1/systemone` | `OPENCODE_API_KEY` | `jev-1.13-free` ($0) | https://opencode.ai (Console); https://opencode.ai/docs/console/models/ |
| `typesafe` | `https://api.typesafe.ai/v1/systemone` | `TYPESAFE_AI_API_KEY` (or `TYPESAFE_API_KEY`) | `jev-latest` | https://typesafe.ai; docs index https://docs.typesafe.ai/llms.txt |
| `openrouter` | `https://openrouter.ai/api/v1/systemone` | `OPENROUTER_API_KEY` | `typesafe/jev-1.14` | https://openrouter.ai; many decision models, some `:free` |
| `perplexity` | `https://api.perplexity.ai/v1/decisions` | `PERPLEXITY_API_KEY` | `pplx-decider-latest` | https://docs.perplexity.ai (same body, different path) |
| `liquid` | `https://api.liquid.ai/decisions/v1/systemone` | `LIQUID_API_KEY` | `d1.1` | https://www.liquid.ai; every question needs `instructions` |

`GET https://api.typesafe.ai/v1/models` lists TypeSafe's names (`jev-latest`,
`jev-preview`). OpenRouter's `/api/v1/models` does **not** list decision
models; find them with the `provider-onboarding` skill
(`lookup.py --type decision --sort price`) or OpenRouter's site.

## Model families (calibration and fallbacks stay inside one)

| Family | Example ids | Notes |
|---|---|---|
| `jev` | `jev-1.13-free`, `jev-latest` (-> `jev-1.14.0`), `typesafe/jev-1.14` | ~32K context; no domain knowledge assumed; `noul` has no confidence |
| `pplx-decider` | `pplx-decider-latest`, `perplexity/pplx-decider-flash-v1.3:free` | 1-255 choices, 1-10 score levels, 256K context; questions in one request can see each other's answers (v1.2), so keep grouping fixed once calibrated |
| `liquid-d1` | `d1`, `d1.1`, `d1.2`, `d1.2-ultra`, `d1-ultra`; on OpenRouter `liquid/d1.2` | Liquid direct verified 2026-11-23; requires `instructions` on every question (422 otherwise) |
| `asi-super-decider` | `super-decider` | answers noul and choice |

Cheapest listings seen 2026-11-23 (input $/1M): `jev-1.13-free`,
`perplexity/pplx-decider-flash-v1.3:free`, `respan/span-01-lite:free` $0;
Perplexity Decider Flash $0.01; Liquid d1.2 $0.02; Jev $0.042; Gemini Decision
1 and GPT-6 Luna Decisions $0.10.

## Model quirks (source, date)

- `respan/span-01-lite(:free)`: answers only `noul`, needs explicit
  true/false criteria, `state` must be a string (live tests, 2026-10).
- Mercury Decide (gone from OpenRouter by 2026-11): near-binary scores;
  cutoffs fitted on Jev lost about half the good items. Lesson: cutoffs never
  transfer across families (live tests, 2026-10).
- Through Vercel AI Gateway (2026-11-23, one made-up item, three questions):
  `microsoft/microsoft-decision-1` sharp and confident, about $0.0000034 a
  call; `google/gemini-decision-1` fine, about $0.00002, adds a free-text
  `text` field; `openai/gpt-6-luna-decisions` returns probabilities rounded
  to 0 or 1 (near-binary like Mercury: calibrate before trusting cutoffs),
  about $0.00004; `nace-ai/drex-v2.0` cheapest (about $0.0000018) and much
  less certain (choice confidence 0.50 on a clear case).
- Probabilities wobble in the second decimal between identical calls: keep a
  margin around cutoffs (Perplexity docs; observed 2026-10).
- Jev reads `state` as given; put definitions and examples in it
  (`reference`), not in the model's head (TypeSafe docs).

## Data-policy pages

Read the current page before the privacy check; these change.

| Provider | Where | Checked |
|---|---|---|
| OpenRouter | https://openrouter.ai/privacy ; per-provider retention and training: https://openrouter.ai/docs/guides/privacy/provider-logging ; zero data retention routing: https://openrouter.ai/docs/guides/features/zdr | page reachable 2026-11-23 |
| OpenCode | https://opencode.ai/legal/privacy-policy ; model terms: https://opencode.ai/docs/console/models/ | page reachable 2026-11-23 |
| TypeSafe | https://typesafe.ai (privacy/terms links) | not checked |
| Perplexity | https://www.perplexity.ai (legal: privacy policy, API terms) | not checked |
| ASI Cloud | the provider's site (privacy/terms) | not checked |

## Other System One hosts (not built in)

Add one to a setup file's `providers` block (marked unverified
automatically), for example:

```json
"providers": {
  "decisionmodels": {"endpoint": "https://api.decisionmodels.io/v1/systemone",
                     "key_env": ["DECISIONMODELS_API_KEY"], "default_model": "s1-fast"}
}
```

Tested live 2026-11-23 but not built in (a small provider; `super-decider`
is experimental): ASI Cloud, `https://inference.asicloud.cudos.org/v1/systemone`,
model `super-decider` (answers noul and choice), key env var unconfirmed
(`ASI_API_KEY` used in testing), price not published in the catalogs used.

Listed by models.dev with the TypeSafe SDK but never called live:
decisionmodels.io (`https://api.decisionmodels.io/v1` +
`/systemone`; `s1-fast`, `s1-pro`, `reax-1`), Butler (`cicero`), GreenPT
(`metis`), Melious (`clef`, `clef-flash`), NEAR AI (`typesafe/jev-1.13`),
Vivgrid (`jev`). Try one call with `ask --test-data` before real use.

## Not System One

- Vercel AI Gateway `/v1/evaluate` (`AI_GATEWAY_API_KEY`, ids like
  `typesafe-ai/jev`): `boolean` instead of `noul`, simpler criteria; decision
  models need paid gateway credits. Checked live 2026-11-23 through
  `scripts/adapters/vercel_evaluate.py`.
- Levanto Sage `/decide/batch`: its own schema (one item per request,
  questions with `kind`/`id`/`instructions`), `null` on near-ties; checked
  live 2026-11-23 through `scripts/adapters/levanto_sage.py`.
- Cloudflare Workers AI `@cf/cloudflare/clef*` via `/ai/run`: own format
  (not covered).
